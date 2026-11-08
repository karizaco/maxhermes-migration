"""stock-screener-suite deterministic orchestrator.

The Agent invokes MCP tools (shibui-finance SQL, tradingview screens, etc.). This
script does the deterministic bookkeeping: cache check, plan emission, tier merge,
CSV / Markdown output, regime flag, and fallback URL builders.

Subcommands
-----------
plan <YYYY-MM-DD>        Emit a JSON plan of MCP calls for the date.
consume <results.json>   Apply tiering + write outputs from MCP results.
prefilter <YYYY-MM-DD>   Emit a single shibui SQL for the universe pre-filter.
breadth <YYYY-MM-DD>     Emit shibui SQL + MCP call list for the breadth snapshot.
reversal-bullish <date>  Emit the SQL for Bonde's 3:55 PM reversal-bullish scan.
tier <daily-dir>         Tier-merge the per-stylist outputs in a daily-screens dir.
regime <breadth.json>    Compute regime flag from breadth JSON output.
finviz-url <kind>        Print a Finviz screener URL (used by the Agent for tier-2 fallback).
finviz-parse <html>      Parse a Finviz screener HTML page to ticker rows.

Usage (from the Agent)
----------------------
1. Run `python screen.py plan 2026-09-21 --out plan.json`
2. Agent reads plan.json, invokes each MCP call, writes results to results.json
3. Run `python screen.py consume results.json --date 2026-09-21`
4. Outputs land under <vault>/daily-screens/2026-09-21/

Cache key: (date, "sweep"). Force-run with --force.

Fallback chain
--------------
When an MCP call returns error / rate_limited / timeout, the Agent falls back:
  tier 1: MCP (primary, default)
  tier 2: Finviz GET screener (web_fetch, see references/fallbacks.md)
  tier 3: TradingView symbol-search JSON (web_fetch)
  tier 4: Yahoo Finance quote page HTML (web_fetch, last resort)
The functions in this module generate the URLs for tier 2.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field, asdict
from datetime import date as date_cls, timedelta
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Vault layout
# ---------------------------------------------------------------------------

DEFAULT_VAULT = Path("C:/Users/admin/research/markets/daily-screens")


# ---------------------------------------------------------------------------
# shibui's per-query row ceiling
# ---------------------------------------------------------------------------
#
# shibui hard-caps EVERY query result at 200 rows (the 2026-11-03 sweep measured
# 233 names passing the 4%-breakout filter and 236 passing EP9M, so a single
# capped query cannot return them). Two different limits must therefore never
# be confused:
#
#   * the ROW CAP (200) is a hard server ceiling — one query cannot return more;
#   * a PER-BRANCH LIMIT is a cap the EMITTER chose (50 / 30 / 60), and it is
#     the bug: it silently truncated a book while the query still succeeded and
#     every downstream count still looked plausible.
#
# The fix is: no branch carries its own LIMIT; a branch is fetched on its own,
# paged 200 rows at a time, and every row carries `rows_passing` — the TRUE
# count of rows that pass that branch's filter, computed inside the branch
# before any cap applies. The run then asserts rows_kept == rows_passing.
SHIBUI_ROW_CAP = 200

# The per-branch caps that used to live in the emitters. They are kept here
# ONLY as the signature of the defect: a published branch count equal to one of
# these is the truncation fingerprint, not a screen outcome.
LEGACY_BRANCH_CAPS = (30, 50, 60)


def vault_dir(date: str, root: Path = DEFAULT_VAULT) -> Path:
    return root / date


# ---------------------------------------------------------------------------
# `_regime.json` — ONE declared shape, pinned
# ---------------------------------------------------------------------------
#
# The payload changed shape between 2026-11-03 (flat) and 2026-11-04 (nested
# under a `regime` key). A consumer doing `d.get("late_cycle")` on the nested
# file gets `None`, which is indistinguishable from "not computed" — a silent
# contract break in a file the suite spec calls "the file downstream routines
# should read".
#
# The FLAT shape is canonical: it is what the 2026-11-03 consumers read and
# what `compute_regime()` returns. The schema version travels in the payload so
# a consumer can tell the shapes apart.
REGIME_SCHEMA_VERSION = 2

# Every one of these MUST be present in a published `_regime.json`. A missing
# key is a failed run, not a default.
REGIME_REQUIRED_KEYS = (
    "size_cut_pct",
    "uncertainty",
    "late_cycle",
    "breadth_pct_spx",
    "index_below_20sma",
    "vix",
    "vix3m",
    "atr_extensions",
)


class RegimeSchemaError(ValueError):
    """Raised when a regime payload does not match the declared schema."""


def assert_regime_schema(payload: dict) -> dict:
    """Validate a regime payload against the declared schema.

    Raises `RegimeSchemaError` when a required key is missing. A payload that
    nests the regime under a `regime` key is ALSO rejected: that shape is the
    2026-11-04 break, and accepting it would let the break persist.
    """
    if not isinstance(payload, dict):
        raise RegimeSchemaError(f"regime payload is {type(payload).__name__}, expected dict")
    if "regime" in payload and not any(k in payload for k in REGIME_REQUIRED_KEYS):
        raise RegimeSchemaError(
            "regime payload is NESTED under a 'regime' key — that is the "
            "2026-11-04 schema break. The canonical shape is FLAT: the regime "
            "fields sit at the top level next to '_schema'."
        )
    missing = [k for k in REGIME_REQUIRED_KEYS if k not in payload]
    if missing:
        raise RegimeSchemaError(
            f"regime payload is missing required key(s): {', '.join(missing)}"
        )
    return payload


def write_regime_payload(path: Path, payload: dict) -> dict:
    """Write `_regime.json` in the canonical flat shape, with a schema version.

    The payload is validated BEFORE it is written, so a broken shape never
    lands on disk. `_schema` and `_note` are siblings of the regime fields,
    never parents of them.
    """
    assert_regime_schema(payload)
    out = {"_schema": REGIME_SCHEMA_VERSION}
    out.update(payload)
    Path(path).write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out


def read_regime(path: Path) -> dict:
    """Read a `_regime.json` into the flat shape, tolerating the legacy nesting.

    A consumer must never see `None` where a regime field belongs. If the file
    on disk is the 2026-11-04 nested shape, it is unwrapped here (and the
    caller can see `read_regime` returned a payload whose `_schema` is absent).
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict) and "regime" in data and isinstance(data["regime"], dict):
        flat = dict(data["regime"])
        flat["_note"] = data.get("_note") or flat.get("_note")
        flat["_legacy_nested"] = True
        return flat
    return data


# Vault layout reference (also documented in references/vault-concurrency.md):
#
#   C:/Users/admin/research/markets/daily-screens/<DATE>/
#     _regime.json                — written by breadth-snapshot AND daily-sweep (latter wins)
#     _summary.md                 — written by daily-sweep ONLY
#     _audit.log                  — append-only; every cron appends one line
#     master.md, stalk.md         — written by daily-sweep ONLY
#     focus.md                    — written by daily-sweep; **read** by premarket-gapper, focus-rvol-rerank
#     tier-a.md                   — written by daily-sweep; **read** by agentic-pre-market-brief, agentic-weekly-brief
#     <stylist>.md (5 files)      — written by daily-sweep ONLY (Stockbee / Qullamaggie / Sun / Hernandez / peoplewish)
#     short-candidates.csv        — written by daily-sweep ONLY
#     long-reversal-candidates.csv — written by daily-sweep ONLY
#     reversal-bullish-3_55.{md,csv} — written by reversal-bullish cron ONLY
#     premarket-gappers.md        — written by premarket-gapper cron ONLY
#     focus-rvol-snapshot.md      — written by focus-rvol-rerank cron ONLY (every 1-2h intraday)
#     weekly-ipo.md, weekly-high-short-float.md — written by pattern-study cron ONLY (Sat)
#
# Race-window map (only same-file writes matter):
#   breadth-snapshot  06:30 ET  -> _regime.json
#   daily-sweep      18:30 ET  -> _regime.json, _summary.md, master/stalk/focus/tier-a, 5 per-stylist,
#                                  short/long CSVs, reversal-bullish CSV (if any), appends _audit.log
# 12h gap between the two _regime.json writers — daily-sweep's value is authoritative.
# No other crons share write targets.
#
# READ side — which crons read which files:
#   premarket-gapper     reads yesterday/focus.md
#   focus-rvol-rerank   reads today/focus.md, prior-snapshot rvol values
#   reversal-bullish     reads nothing from prior runs
#   pattern-study        appends to long-lived pattern-study/peoplewish-1000pct-backlog.md (separate dir)


def vault_exists(date: str, root: Path = DEFAULT_VAULT) -> bool:
    p = vault_dir(date, root)
    return (p / "_summary.md").exists()


def cache_status(date: str, root: Path = DEFAULT_VAULT) -> dict:
    """Is the day's sweep already done, and on which data date?

    The 18:30 ET sweep is expensive (~20 MCP calls). A re-fire on the same
    calendar day should not repeat it. The cache marker `_cache.json` records
    the resolved data date, so a later fire that sees shibui's data date
    unchanged can short-circuit; a changed data date means new information and
    the sweep must run again.
    """
    root = Path(root) if root is not None else DEFAULT_VAULT
    p = vault_dir(date, root)
    marker = p / "_cache.json"
    out = {
        "cron_date": date,
        "vault": str(p),
        "cache_file": str(marker),
        "cache_present": marker.exists(),
        "complete": vault_exists(date, root),
        "data_as_of": None,
        "valid": False,
        "reason": "",
    }
    if not marker.exists():
        out["reason"] = "no cache marker"
        return out
    try:
        meta = json.loads(marker.read_text(encoding="utf-8"))
    except Exception as exc:
        out["reason"] = f"cache marker unreadable: {exc}"
        return out
    out["data_as_of"] = meta.get("data_as_of")
    out["counts"] = meta.get("counts")
    out["complete"] = (p / "_summary.md").exists() and (p / "_results.json").exists()
    out["valid"] = bool(out["complete"])
    out["reason"] = "cached run is complete" if out["valid"] else "cache marker present but outputs incomplete"
    return out


# ---------------------------------------------------------------------------
# Tier-2 fallback: Finviz URL builders
# ---------------------------------------------------------------------------
#
# When MCP returns rate_limit / timeout / error, the Agent should:
#   1. Build the Finviz URL via one of these functions
#   2. web_fetch the URL
#   3. Parse the HTML via parse_finviz_table()
#
# See references/fallbacks.md for the full decision matrix.

def finviz_url(filters: list[str], order: str = "-change", view: int = 111, ticker_filter: str | None = None) -> str:
    """Build a Finviz screener URL from a filter list."""
    f = ",".join(filters)
    t = ticker_filter or ""
    base = f"https://finviz.com/screener.ashx?v={view}&f={f}&o={order}&r=0"
    if t:
        base += f"&t={t}"
    return base


def finviz_bonde_4pct() -> str:
    return finviz_url(["ta_change_o4", "sh_avgvol_o100k", "sh_price_o5"])


def finviz_peoplewish() -> str:
    return finviz_url(["ta_volatility_wo5", "sh_avgvol_o1000k", "cap_midover"])


def finviz_qullamaggie_1m() -> str:
    return finviz_url(["ta_perf1mup25", "sh_avgvol_o1000k", "ta_sma200_pa", "cap_midover"])


def finviz_jeff_sun_canslim() -> str:
    return finviz_url([
        "cap_midover", "fa_epsqoq_o25", "fa_salesqoq_o25",
        "sh_price_o5", "ta_sma50_pa", "ta_rsi_nob40", "ta_rsi_nob80",
    ])


def finviz_5d_gainers() -> str:
    return finviz_url(["ta_perf5dup25", "sh_avgvol_o1000k"])


def finviz_5d_losers() -> str:
    return finviz_url(["ta_perf5ddown25", "sh_avgvol_o1000k"])


def finviz_reversal_bullish() -> str:
    return finviz_url(["ta_change_d", "ta_sma50_pa", "sh_avgvol_o1000k", "cap_largeover"])


def finviz_high_short_float() -> str:
    return finviz_url(["sh_short_o20", "sh_avgvol_o500k"])


def finviz_ipo_recent() -> str:
    return finviz_url(["ipodate_l5y", "cap_midover"])


def finviz_premarket_gap_url(tickers: list[str], gap_pct_min: float = 4.0, pm_vol_min: int = 50000) -> str:
    """Pre-market gap scan on Finviz — v=170 view with a ticker scope."""
    t_filter = ",".join(f"t_{t.upper()}" for t in tickers) if tickers else ""
    return finviz_url(
        filters=[],
        order="-change",
        view=170,
        ticker_filter=t_filter,
    )


FINVIZ_BUILDERS = {
    "bonde_4pct": finviz_bonde_4pct,
    "peoplewish": finviz_peoplewish,
    "qullamaggie_1m": finviz_qullamaggie_1m,
    "jeff_sun_canslim": finviz_jeff_sun_canslim,
    "5d_gainers": finviz_5d_gainers,
    "5d_losers": finviz_5d_losers,
    "reversal_bullish": finviz_reversal_bullish,
    "high_short_float": finviz_high_short_float,
    "ipo_recent": finviz_ipo_recent,
}


def parse_finviz_table(html: str) -> list[dict]:
    """Parse a Finviz screener HTML page into a list of ticker dicts.

    Returns one dict per row with at least `ticker` and a `cells` list of raw
    cell text in column order. Column-to-field mapping depends on the `v=` view
    and the `c=` column-visibility param in the URL; for v=111 with default
    columns, see references/fallbacks.md.

    Supports both the legacy ``quote.ashx?t=<TICKER>`` URL pattern (pre-2024
    Finviz) and the redesigned ``stock?t=<TICKER>&ty=c&p=d&b=1`` pattern
    (2024+ Finviz). Restricts the row sweep to the screener's data rows
    (``<tr class="styled-row ...">``) so page header/footer/sidebar noise
    doesn't leak through; falls back to all ``<tr>`` elements if the
    styled-row class is not present (legacy pages).
    """
    import re
    from html import unescape

    # Finviz redesign (2024+): data rows are <tr class="styled-row ...">.
    # Fall back to all <tr> if no styled-row match (legacy pages).
    styled_rows = re.findall(
        r'<tr[^>]*class="[^"]*styled-row[^"]*"[^>]*>(.*?)</tr>',
        html,
        re.DOTALL,
    )
    rows = styled_rows if styled_rows else re.findall(
        r"<tr[^>]*>(.*?)</tr>",
        html,
        re.DOTALL,
    )

    # Ticker links: both "quote.ashx?t=AAPL" and "stock?t=AAPL&ty=c&p=d&b=1"
    # match ?t=<TICKER>; the char class excludes `&` so capture stops naturally.
    ticker_re = re.compile(r"\?t=([A-Z0-9.\-]+)")

    out: list[dict] = []
    for row in rows:
        ticker_match = ticker_re.search(row)
        if not ticker_match:
            continue
        ticker = unescape(ticker_match.group(1))
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
        cells = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
        out.append({"ticker": ticker, "cells": cells})
    return out


def tv_symbol_search_url(query: str) -> str:
    """Tier-3 fallback: TradingView symbol-search JSON endpoint."""
    return f"https://symbol-search.tradingview.com/symbol_search/?text={query}&type=stocks&hl=en"


def yahoo_quote_url(ticker: str) -> str:
    """Tier-4 fallback: Yahoo Finance quote page."""
    return f"https://finance.yahoo.com/quote/{ticker.upper()}"


# ---------------------------------------------------------------------------
# Plan emission (what MCPs to call and in what order)
# ---------------------------------------------------------------------------

@dataclass
class MCPBatch:
    """A group of MCP calls the Agent should make together (parallel where possible)."""

    name: str
    parallel: bool
    calls: list[dict]


@dataclass
class SweepPlan:
    date: str  # The date the sweep SQL uses. When --resolve-latest is set, this
               # is the placeholder '__RESOLVED_DATE__' until the Agent runs the
               # preflight batch and substitutes the actual latest available date.
    cron_date: str | None = None  # The cron-fire date (always the agent's input).
                                  # Used by `consume --date` so output lands in
                                  # daily-screens/<cron_date>/ even though the
                                  # sweep SQL targets a possibly-earlier data date.
    batches: list[MCPBatch] = field(default_factory=list)

    def to_json(self) -> str:
        out = {
            "date": self.date,
            "batches": [asdict(b) for b in self.batches],
            "mcp_call_count": sum(len(b.calls) for b in self.batches),
        }
        if self.cron_date is not None:
            out["cron_date"] = self.cron_date
        return json.dumps(out, indent=2)


# SQL placeholder the Agent substitutes with shibui's latest available date
# after running the preflight batch. Kept in a constant so it's grep-able.
RESOLVED_DATE_PLACEHOLDER = "__RESOLVED_DATE__"


def emit_prefilter_sql(date: str) -> str:
    """Single shibui SQL for the universe pre-filter.

    Schema: stock_quotes (OHLCV) + valuation (market_cap) joined on symbol.
    LIMIT 200 enforced by the server.

    The market-cap lookup takes the LATEST valuation row per symbol FIRST
    and only then applies the cap filter. `shibui.valuation` keeps multiple
    rows per symbol per date, so filtering on the cap before the latest-row
    pick admits stale rows whose cap was once above the threshold.
    """
    return f"""
-- Pre-filter for {date}
WITH mc AS (
  SELECT symbol, market_cap FROM shibui.valuation
  WHERE date = (SELECT MAX(date) FROM shibui.valuation WHERE date <= '{date}')
)
SELECT q.symbol, q.close, q.exchange, q.volume AS today_volume, mc.market_cap
FROM shibui.stock_quotes q
JOIN mc ON mc.symbol = q.symbol
WHERE q.date = '{date}'
  AND q.exchange IN ('NYSE', 'NASDAQ', 'AMEX')
  AND q.close > 3
  AND mc.market_cap > 300000000
  AND q.volume > 100000
ORDER BY mc.market_cap DESC
LIMIT 200
""".strip()




def emit_sweep_sql_stockbee(date: str) -> str:
    """Stockbee group: 4% breakout + EP9M + Anticipation. Single shibui call, UNION ALL.

    Every branch emits the SAME explicitly-named column set. A UNION ALL
    takes its output column names from the FIRST branch, so branches with
    ad-hoc names silently publish one metric under another metric's header
    (the EP9M close-location value used to appear under `chg_pct`).

    The market-cap pre-filter floor is applied inside the query so the
    equity universe is enforced at the source, not after the merge.

    NO BRANCH CARRIES ITS OWN LIMIT. Each branch used to end in
    `LIMIT 50` / `LIMIT 50` / `LIMIT 30`, which silently truncated the book
    while the query still succeeded — on 2026-11-04 the artifact published
    `A_stockbee_4pct 50` and `B_stockbee_ep9m 50`, which are the CAPS, not
    screen outcomes (the true passing counts that day were 233 and 236).
    Every branch now carries `rows_passing` — `COUNT(*) OVER ()` computed
    INSIDE the branch, before any cap applies — so the true passing count
    travels with the rows and the coverage assertion can prove nothing was
    dropped. The single outer `LIMIT 200` is shibui's own row ceiling and
    must stay.
    """
    support = _stockbee_support_ctes(date)
    branches = _stockbee_branch_ctes(date)
    union = "\nUNION ALL ".join(f"SELECT * FROM {name}" for name in branches)
    cte_list = ",\n".join(branches.values())
    return f"""
-- Stockbee sweep for {date}: 4% breakout + EP9M + Anticipation
WITH {support},
{cte_list}
{union}
ORDER BY origin, symbol
LIMIT {SHIBUI_ROW_CAP}
""".strip()


def _stockbee_support_ctes(date: str) -> str:
    """The CTEs every Stockbee branch reads: the market-cap lookup and the
    per-symbol window frame (prev close/volume, rolling ATRs, 10-day range)."""
    return f"""
mc AS (
  SELECT symbol, market_cap FROM shibui.valuation
  WHERE date = (SELECT MAX(date) FROM shibui.valuation WHERE date <= '{date}')
),
today AS (
  SELECT q.symbol, q.date, q.open, q.high, q.low, q.close, q.volume,
     t.atr_14,
     LAG(q.close) OVER (PARTITION BY q.symbol ORDER BY q.date)  AS prev_close,
     LAG(q.volume) OVER (PARTITION BY q.symbol ORDER BY q.date) AS prev_volume,
     AVG(t.atr_14) OVER (PARTITION BY q.symbol ORDER BY q.date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW) AS atr_7d,
     AVG(t.atr_14) OVER (PARTITION BY q.symbol ORDER BY q.date ROWS BETWEEN 64 PRECEDING AND CURRENT ROW) AS atr_65d,
     MAX(q.high) OVER (PARTITION BY q.symbol ORDER BY q.date ROWS BETWEEN 9 PRECEDING AND CURRENT ROW) AS max_high_10d,
     MIN(q.low)  OVER (PARTITION BY q.symbol ORDER BY q.date ROWS BETWEEN 9 PRECEDING AND CURRENT ROW) AS min_low_10d
  FROM shibui.stock_quotes q
  JOIN shibui.technical_indicators t ON q.symbol = t.symbol AND q.date = t.date
  JOIN mc ON mc.symbol = q.symbol AND mc.market_cap > 300000000
  WHERE q.date BETWEEN DATE '{date}' - INTERVAL '150 days' AND '{date}'
AND q.exchange IN ('NYSE','NASDAQ','AMEX')
)""".strip()


def _stockbee_branch_ctes(date: str) -> dict[str, str]:
    """Branch name -> CTE text. No branch carries a LIMIT; every branch
    carries `rows_passing` (the true count of rows passing its filter)."""
    return {
        "A_stockbee_4pct": f"""
A_stockbee_4pct AS (
  SELECT 'A_stockbee_4pct' AS origin, symbol, close, volume,
     (close / NULLIF(prev_close, 0) - 1) * 100 AS chg_pct,
     NULL AS dcr_pct, NULL AS trend_intensity, NULL AS base_width_pct,
     COUNT(*) OVER () AS rows_passing
  FROM today
  WHERE date = '{date}'
AND prev_close IS NOT NULL AND prev_close > 0
AND close / NULLIF(prev_close, 0) >= 1.04
AND volume > prev_volume
AND volume >= 100000
AND close >= 3
)""".strip(),
        "B_stockbee_ep9m": f"""
B_stockbee_ep9m AS (
  SELECT 'B_stockbee_ep9m' AS origin, symbol, close, volume,
     NULL AS chg_pct,
     (close - low) / NULLIF(high - low, 0) * 100 AS dcr_pct,
     NULL AS trend_intensity, NULL AS base_width_pct,
     COUNT(*) OVER () AS rows_passing
  FROM today
  WHERE date = '{date}'
AND volume >= 8900000
AND close >= 3
)""".strip(),
        "K_stockbee_anticipation": f"""
K_stockbee_anticipation AS (
  SELECT 'K_stockbee_anticipation' AS origin, symbol, close, NULL AS volume,
     NULL AS chg_pct, NULL AS dcr_pct,
     atr_7d / NULLIF(atr_65d, 0) AS trend_intensity,
     (max_high_10d - min_low_10d) / NULLIF(close, 0) AS base_width_pct,
     COUNT(*) OVER () AS rows_passing
  FROM today
  WHERE date = '{date}'
AND atr_7d / NULLIF(atr_65d, 0) >= 1.05
AND (max_high_10d - min_low_10d) / NULLIF(close, 0) <= 0.08
AND prev_close IS NOT NULL
AND close / NULLIF(prev_close, 0) < 1.04
)""".strip(),
    }





def emit_sweep_sql_qullamaggie(date: str) -> str:
    """Qullamägi group: RS leaders + EP + 5d gainers + 5d losers. Single shibui call.

    Two traps this query used to fall into, both silent:
      * the lookback window was hardcoded to '2025-12-01' (~231 trading
        days) while the RS screen needs LAG(close, 252), so every
        close_252d_ago was NULL and the whole RS book came back EMPTY.
        The window is now relative to the target date and long enough
        (~430 calendar days) for 252 trading days with headroom.
      * the CTE aliased close_252d_ago / close_126d_ago / close_63d_ago /
        close_21d_ago while the SELECT and WHERE referenced close_252 /
        close_126 / close_63 / close_21, which is a Binder Error.

    NO BRANCH CARRIES ITS OWN LIMIT — the four branches used to end in
    `LIMIT 60` / `LIMIT 30` x3, which silently truncated each book. Every
    branch carries `rows_passing` (`COUNT(*) OVER ()` inside the branch) so
    the true passing count travels with the rows and the coverage assertion
    can prove nothing was dropped. The outer `LIMIT 200` is shibui's own row
    ceiling and must stay.
    """
    support = _qullamaggie_support_ctes(date)
    branches = _qullamaggie_branch_ctes(date)
    union = "\nUNION ALL ".join(f"SELECT * FROM {name}" for name in branches)
    cte_list = ",\n".join(branches.values())
    return f"""
-- Qullamägi sweep for {date}: multi-timeframe RS + EP + 5d movers
WITH {support},
{cte_list}
{union}
ORDER BY origin, symbol
LIMIT {SHIBUI_ROW_CAP}
""".strip()


def _qullamaggie_support_ctes(date: str) -> str:
    """mc + hist — the shared CTEs every Qullamägi branch reads."""
    return f"""
mc AS (
  SELECT symbol, market_cap FROM shibui.valuation
  WHERE date = (SELECT MAX(date) FROM shibui.valuation WHERE date <= '{date}')
),
hist AS (
  SELECT q.symbol, q.date, q.open, q.high, q.low, q.close, q.volume,
     LAG(q.close, 5)  OVER w AS close_5d_ago,
     LAG(q.close, 21) OVER w AS close_21d_ago,
     LAG(q.close, 63) OVER w AS close_63d_ago,
     LAG(q.close, 126) OVER w AS close_126d_ago,
     LAG(q.close, 252) OVER w AS close_252d_ago,
     LAG(q.close) OVER w AS prev_close,
     AVG((q.high - q.low) / NULLIF(q.close, 0)) OVER (PARTITION BY q.symbol ORDER BY q.date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) * 100 AS adr_pct_20d,
     AVG(q.close * q.volume) OVER (PARTITION BY q.symbol ORDER BY q.date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS adv_dollar_20d
  FROM shibui.stock_quotes q
  JOIN mc ON mc.symbol = q.symbol AND mc.market_cap > 300000000
  WHERE q.date BETWEEN DATE '{date}' - INTERVAL '430 days' AND '{date}'
AND q.exchange IN ('NYSE','NASDAQ','AMEX')
  WINDOW w AS (PARTITION BY q.symbol ORDER BY q.date)
)""".strip()


def _qullamaggie_branch_ctes(date: str) -> dict[str, str]:
    """Branch name -> CTE text. No branch carries a LIMIT; every branch
    carries `rows_passing` (the true count of rows passing its filter)."""
    return {
        "C_qullamaggie_rs": f"""
C_qullamaggie_rs AS (
  SELECT 'C_qullamaggie_rs' AS origin, symbol, close,
     (close / NULLIF(close_252d_ago, 0) - 1) * 100 AS rs_12m,
     (close / NULLIF(close_126d_ago, 0) - 1) * 100 AS rs_6m,
     (close / NULLIF(close_63d_ago, 0) - 1) * 100 AS rs_3m,
     (close / NULLIF(close_21d_ago, 0) - 1) * 100 AS rs_1m,
     adr_pct_20d, adv_dollar_20d, NULL AS m1, NULL AS m2,
     COUNT(*) OVER () AS rows_passing
  FROM hist
  WHERE date = '{date}'
AND adv_dollar_20d >= 20000000
AND adr_pct_20d >= 4.5
AND close_252d_ago IS NOT NULL AND close_126d_ago IS NOT NULL
AND close_63d_ago IS NOT NULL AND close_21d_ago IS NOT NULL
AND ((close / NULLIF(close_21d_ago, 0) - 1) >= 0.25 OR (close / NULLIF(close_63d_ago, 0) - 1) >= 0.50 OR (close / NULLIF(close_126d_ago, 0) - 1) >= 1.50)
)""".strip(),
        "D_qullamaggie_ep": f"""
D_qullamaggie_ep AS (
  SELECT 'D_qullamaggie_ep' AS origin, symbol, close,
     NULL AS rs_12m, NULL AS rs_6m, NULL AS rs_3m, NULL AS rs_1m,
     NULL AS adr_pct_20d, adv_dollar_20d,
     (open / NULLIF(prev_close, 0) - 1) * 100 AS m1,
     volume / NULLIF(adv_dollar_20d / NULLIF(close, 0), 0) AS m2,
     COUNT(*) OVER () AS rows_passing
  FROM hist
  WHERE date = '{date}'
AND prev_close IS NOT NULL AND prev_close > 0
AND open / NULLIF(prev_close, 0) >= 1.10
AND adv_dollar_20d >= 50000000
)""".strip(),
        "E_qullamaggie_5d_gainers": f"""
E_qullamaggie_5d_gainers AS (
  SELECT 'E_qullamaggie_5d_gainers' AS origin, symbol, close,
     NULL AS rs_12m, NULL AS rs_6m, NULL AS rs_3m, NULL AS rs_1m,
     adr_pct_20d, adv_dollar_20d,
     (close / NULLIF(close_5d_ago, 0) - 1) * 100 AS m1, NULL AS m2,
     COUNT(*) OVER () AS rows_passing
  FROM hist
  WHERE date = '{date}'
AND close_5d_ago IS NOT NULL AND close_5d_ago > 0
AND (close / NULLIF(close_5d_ago, 0) - 1) >= 0.25
AND adv_dollar_20d >= 50000000
)""".strip(),
        "F_qullamaggie_5d_losers": f"""
F_qullamaggie_5d_losers AS (
  SELECT 'F_qullamaggie_5d_losers' AS origin, symbol, close,
     NULL AS rs_12m, NULL AS rs_6m, NULL AS rs_3m, NULL AS rs_1m,
     NULL AS adr_pct_20d, adv_dollar_20d,
     (close / NULLIF(close_5d_ago, 0) - 1) * 100 AS m1, NULL AS m2,
     COUNT(*) OVER () AS rows_passing
  FROM hist
  WHERE date = '{date}'
AND close_5d_ago IS NOT NULL AND close_5d_ago > 0
AND (close / NULLIF(close_5d_ago, 0) - 1) <= -0.25
AND (close / NULLIF(close_5d_ago, 0) - 1) >= -0.50
AND adv_dollar_20d >= 50000000
)""".strip(),
    }





def emit_sweep_sql_peoplewish(date: str) -> str:
    """peoplewish: ADR% > 5% + Dollar Volume > $50M, sort by velocity. Single shibui call.

    The branch carries `rows_passing` (`COUNT(*) OVER ()` computed inside the
    branch, before the cap applies) so the true passing count travels with
    the rows. On 2026-11-03 **243** names passed this filter while the
    published book held 200 — the shibui row ceiling, which the coverage
    assertion must surface rather than hide. The outer `LIMIT 200` is
    shibui's own ceiling and must stay; the branch itself is uncapped.
    """
    support = _peoplewish_support_ctes(date)
    branch = _peoplewish_branch_ctes(date)
    return f"""
-- peoplewish sweep for {date}: ADR + dollar volume + velocity
WITH {support},
{branch}
SELECT * FROM G_peoplewish
ORDER BY velocity_14d DESC, symbol
LIMIT {SHIBUI_ROW_CAP}
""".strip()


def _peoplewish_support_ctes(date: str) -> str:
    """mc + hist — the shared CTEs the peoplewish branch reads."""
    return f"""
mc AS (
  SELECT symbol, market_cap FROM shibui.valuation
  WHERE date = (SELECT MAX(date) FROM shibui.valuation WHERE date <= '{date}')
),
hist AS (
  SELECT q.symbol, q.date, q.close, q.volume,
     LAG(q.close, 14) OVER w AS close_14d_ago,
     AVG((q.high - q.low) / NULLIF(q.close, 0)) OVER (PARTITION BY q.symbol ORDER BY q.date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) * 100 AS adr_pct_20d,
     AVG(q.close * q.volume) OVER (PARTITION BY q.symbol ORDER BY q.date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS adv_dollar_20d
  FROM shibui.stock_quotes q
  JOIN mc ON mc.symbol = q.symbol AND mc.market_cap > 300000000
  WHERE q.date BETWEEN DATE '{date}' - INTERVAL '120 days' AND '{date}'
AND q.exchange IN ('NYSE','NASDAQ','AMEX')
  WINDOW w AS (PARTITION BY q.symbol ORDER BY q.date)
)""".strip()


def _peoplewish_branch_ctes(date: str) -> str:
    """The peoplewish branch as a CTE, with `rows_passing` and no LIMIT."""
    return f"""
G_peoplewish AS (
  SELECT 'G_peoplewish' AS origin, symbol, close,
     adr_pct_20d,
     adv_dollar_20d,
     (close / NULLIF(close_14d_ago, 0) - 1) * 100 AS velocity_14d,
     COUNT(*) OVER () AS rows_passing
  FROM hist
  WHERE date = '{date}'
  AND adr_pct_20d >= 5
  AND adv_dollar_20d >= 50000000
)""".strip()

def emit_sweep_sql(date: str) -> str:
    """Default sweep SQL (uses the Stockbee group)."""
    return emit_sweep_sql_stockbee(date)


def emit_breadth_sql(date: str) -> str:
    """Breadth (large-cap proxy above 20-DMA) + ATR extension on 5 index ETFs.

    Uses large-cap (market_cap > 10B) as the breadth proxy instead of a hardcoded
    constituents list (no sp500_constituents table exists in shibui).

    Two corrections over the previous version:
      * the large-cap population joins valuation on SYMBOL, not on (symbol, date).
        `shibui.valuation` keeps several rows per symbol per date, so the old
        join double-counted symbols (biasing the breadth percentage) and could
        admit a symbol on a stale market-cap row.
      * the 252-day average ATR is computed over a real trailing window instead
        of a one-row window, which previously made it identical to atr_14.
    """
    return f"""
-- Breadth + ATR extension + index-below-20sma flag for {date}
WITH mc AS (
  SELECT symbol, market_cap FROM shibui.valuation
  WHERE date = (SELECT MAX(date) FROM shibui.valuation WHERE date <= '{date}')
),
idx_hist AS (
  SELECT q.symbol, q.ticker, q.date, q.close,
         t.sma_20, t.sma_50, t.atr_14,
         AVG(t.atr_14) OVER (PARTITION BY q.symbol ORDER BY q.date ROWS BETWEEN 251 PRECEDING AND CURRENT ROW) AS atr_252d_avg,
         ROW_NUMBER() OVER (PARTITION BY q.symbol ORDER BY q.date DESC) AS rn
  FROM shibui.stock_quotes q
  JOIN shibui.technical_indicators t ON q.symbol = t.symbol AND q.date = t.date
  WHERE q.ticker IN ('SPY','RSP','QQQ','QQQE','IWM')
    AND q.date BETWEEN DATE '{date}' - INTERVAL '430 days' AND '{date}'
),
idx AS (
  SELECT symbol, ticker, close, sma_20, sma_50, atr_14, atr_252d_avg
  FROM idx_hist
  WHERE rn = 1 AND date = '{date}'
),
largecap AS (
  SELECT q.symbol, q.close,
         t.sma_20
  FROM shibui.stock_quotes q
  JOIN shibui.technical_indicators t ON q.symbol = t.symbol AND q.date = t.date
  JOIN mc ON mc.symbol = q.symbol
  WHERE q.date = '{date}'
    AND q.exchange IN ('NYSE','NASDAQ','AMEX')
    AND mc.market_cap > 10000000000
),
largecap_breadth AS (
  SELECT COUNT(*) AS n_lc,
         AVG(CASE WHEN close > sma_20 THEN 1.0 ELSE 0.0 END) * 100 AS pct
  FROM largecap
),
idx_summary AS (
  SELECT
    AVG(CASE WHEN close > sma_20 THEN 1.0 ELSE 0.0 END) AS pct_above_sma_20,
    AVG(CASE WHEN close > sma_50 THEN 1.0 ELSE 0.0 END) AS pct_above_sma_50
  FROM idx
)
SELECT 'largecap_breadth' AS metric,
       NULL AS ticker,
       NULL AS close,
       NULL AS sma_20,
       NULL AS sma_50,
       NULL AS atr_14,
       NULL AS atr_252d_avg,
       NULL AS extension_pct,
       NULL AS pct_above_sma_20,
       NULL AS pct_above_sma_50,
       (SELECT pct FROM largecap_breadth) AS breadth_pct_largecap,
       (SELECT n_lc FROM largecap_breadth) AS n_largecap
UNION ALL
SELECT 'index_above_sma_summary', NULL, NULL, NULL, NULL, NULL, NULL, NULL,
       (SELECT pct_above_sma_20 FROM idx_summary),
       (SELECT pct_above_sma_50 FROM idx_summary), NULL, NULL
UNION ALL
SELECT 'index_atr_extension', ticker, close, sma_20, sma_50, atr_14, atr_252d_avg,
       (close - sma_50) / NULLIF(sma_50, 0) * 100, NULL, NULL, NULL, NULL
FROM idx
ORDER BY metric, ticker
""".strip()
def emit_reversal_bullish_sql(date: str) -> str:
    """Bonde 3:55 PM reversal-bullish SQL — CORRECTED to Bonde's PUBLISHED criteria.

    Gate values come from Pradeep Bonde, stockbee.blogspot.com (2019-11-26),
    "Reversal Bullish Scan I use":

        l=minl5 and (o-l)>(c-o) and (c-l)/(h-l)>=.6 and v>=290000 and c>=5 and minv3.1>=100000

    The previous version of this function encoded the skill table's SQL floors, which
    differ from the published scan in four ways, all of which were audited on the
    2026-10-26 signal bar (see daily-screens/2026-10-27/reversal-bullish-3:55-CORRECTION.md
    in karizaco/minimax-cloud-outputs):

      * DCR floor 0.50 -> 0.60 (published: close in the top 40% of the day's range)
      * prior-decline test `close < close_2d_ago` -> a real washout: the bar must
        undercut the prior close intraday (>= 1.5%) and the stock must be down
        >= 3% over the 3 preceding sessions, or down >= 3% over 5 (Bonde: "the drop
        should last at least two to three days" / "there has to be some sort of a wash out")
      * tail:body ratio -> the published `(o-l) > (c-o)` plus a scale-free hammer test
        (lower shadow >= 2x upper shadow). The ratio explodes on doji bodies
        (a 3% body makes the ratio 15-17x) and is not usable as a gate.
      * price floor $15 -> $5 (published). "Prefer higher priced stocks" is a RANKING
        preference, not a filter; keep it as a tie-break in the discretionary step.

    Stop handling: the body low is the invalidation, but on a near-doji body it sits
    inside the bar's own noise (0.07% away on the 2026-10-26 CBRE bar) and produces
    false exits, so a body under 15% of the range uses the signal bar's LOW instead.
    Bonde sanctions the shadow stop: "If you prefer to place the stop at the low of the
    shadow instead, make sure that level does not exceed a 2.5% loss from your purchase
    price." The 2.5% cap is enforced here as a filter.

    Schema notes: shibui exposes no `institutional_holders_count`; `market_cap > $5B`
    stands in for "held by >= 1,000 institutional funds". `shibui.valuation` keeps stale
    rows per symbol, so the cap is taken from each symbol's MOST RECENT valuation row
    (QUALIFY ... = 1), not from an arbitrary historical row.
    """
    win_start = (date_cls.fromisoformat(date) - timedelta(days=60)).isoformat()
    return f"""
-- Reversal bullish for {date} — corrected to Bonde's published criteria
-- Gate values: Pradeep Bonde, stockbee.blogspot.com 2019-11-26
--   l=minl5 and (o-l)>(c-o) and (c-l)/(h-l)>=.6 and v>=290000 and c>=5 and minv3.1>=100000
-- T+1-safe shape: the inner CTE is windowed over {win_start}..{date} so LAG() and the
-- 5-day/20-day windows see full history; the outer query takes rn=1 per symbol.
WITH q AS (
  SELECT symbol, ticker, exchange, date, open, high, low, close, volume
  FROM shibui.stock_quotes
  WHERE date BETWEEN DATE '{win_start}' AND DATE '{date}'
    AND exchange IN ('NYSE','NASDAQ','AMEX')
), w AS (
  SELECT q.*,
         LAG(close,1)  OVER w AS c1d,
         LAG(close,2)  OVER w AS c2d,
         LAG(close,3)  OVER w AS c3d,
         LAG(close,5)  OVER w AS c5d,
         LAG(close,20) OVER w AS c20d,
         MIN(low) OVER (PARTITION BY symbol ORDER BY date
                        ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) AS low5,
         AVG((high-low)/close) OVER (PARTITION BY symbol ORDER BY date
                        ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS adr20,
         AVG(volume) OVER (PARTITION BY symbol ORDER BY date
                        ROWS BETWEEN 29 PRECEDING AND CURRENT ROW) AS adv30,
         ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date DESC) AS rn
  FROM q
  WINDOW w AS (PARTITION BY symbol ORDER BY date)
), val AS (
  SELECT symbol, market_cap
  FROM shibui.valuation
  WHERE date <= DATE '{date}'
  QUALIFY ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date DESC) = 1
), sig AS (
  SELECT w.*, val.market_cap,
         (close - low) / NULLIF(high - low, 0) AS dcr,
         ABS(close - open) / NULLIF(high - low, 0) AS body_ratio,
         (LEAST(open,close) - low) AS lower_shadow,
         (high - GREATEST(open,close)) AS upper_shadow,
         (open - low) > (close - open) AS shadow_gt_body,
         (low / c1d - 1) AS shakeout_vs_prev_close,
         (close / c3d - 1) AS drop_3d,
         (close / c5d - 1) AS drop_5d
  FROM w LEFT JOIN val ON val.symbol = w.symbol
  WHERE w.rn = 1 AND w.date = DATE '{date}'
), calc AS (
  SELECT sig.*,
         CASE WHEN body_ratio < 0.15 THEN low ELSE LEAST(open, close) END AS next_day_stop,
         (close - LEAST(open, close)) / NULLIF(close, 0) AS body_stop_pct,
         (close - low) / NULLIF(close, 0) AS shadow_stop_pct
  FROM sig
), scored AS (
  SELECT *,
         CASE WHEN body_ratio < 0.15 THEN shadow_stop_pct ELSE body_stop_pct END AS stop_risk_pct
  FROM calc
)
SELECT symbol, ticker, exchange, date AS signal_date,
       open, high, low, close AS entry_price, volume,
       dcr, body_ratio, lower_shadow, upper_shadow,
       (lower_shadow / NULLIF(ABS(close - open), 0)) AS tail_body_ratio,
       shadow_gt_body,
       c1d AS close_1d_ago, c2d AS close_2d_ago, c3d AS close_3d_ago, c20d AS close_20d_ago,
       low5, adr20, adv30, market_cap,
       'market_cap $' || ROUND(market_cap / 1000000000, 1) || 'B proxy' AS funds_held,
       'market_cap $' || ROUND(market_cap / 1000000000, 1) || 'B proxy' AS funds_held_proxy,
       drop_3d, drop_5d, shakeout_vs_prev_close,
       next_day_stop, stop_risk_pct, body_stop_pct, shadow_stop_pct
FROM scored
WHERE market_cap > 5000000000                 -- U: institutional proxy (>= 1,000 funds)
  AND adv30 > 1000000                        -- U: liquidity floor
  AND close >= 5.0                           -- F7 published price floor ("prefer higher priced" is a RANKING input)
  AND low <= low5                            -- F1 5-day low
  AND dcr >= 0.60                            -- F2 published: close in the top 40% of the range
  AND shadow_gt_body                         -- F3 published: (o-l) > (c-o)
  AND lower_shadow >= 2 * upper_shadow       -- F3b hammer: long lower wick, short upper wick
  AND body_ratio <= 0.30                     -- F3c small body (published "small, narrow, toward the top")
  AND body_ratio <= 0.40                     -- F4 house rule (kept, non-binding given F3c)
  AND shakeout_vs_prev_close <= -0.015       -- F5 washout: the bar undercut the prior close intraday
  AND (drop_3d <= -0.03 OR drop_5d <= -0.03) -- F5 prior decline of 2-3 days (or a 5-day slide)
  AND adr20 >= 0.03                          -- F6 ADR >= 3% (house rule)
  AND close >= c20d * 0.92                   -- F8 long-term trend intact
  AND stop_risk_pct <= 0.025                 -- S: maximum 2.5% loss from the signal close
ORDER BY dcr DESC
LIMIT 50
""".strip()


def emit_resolve_date_sql(date: str) -> str:
    """Returns the latest available date in shibui ≤ the given date.

    Use this to handle the T+1 day data lag: shibui updates overnight, so today's
    bar usually doesn't exist yet. The Agent calls this FIRST and substitutes
    `latest_date` into the rest of the SQL.
    """
    return f"""
-- Resolve latest available date in shibui <= '{date}'
SELECT MAX(date) AS latest_date
FROM shibui.stock_quotes
WHERE date <= '{date}'
  AND exchange IN ('NYSE','NASDAQ','AMEX')
""".strip()


def emit_adr_enrichment_sql(symbols: list[str]) -> str:
    """Compute 20-day ADR% for an explicit list of symbols.

    Used as a consume-time enrichment pass AFTER sweep_sql + tradingview_screens
    have produced their candidate set. The Agent:

      1. Reads the unique `symbol` values from sweep + TV-screens results.
      2. Calls `python screen.py emit-sql adr_enrichment SYM1,SYM2,...` (or
         writes the symbol list to a JSON file and runs the SQL via MCP).
      3. Merges each returned `{symbol, adr_pct_20d}` row into the
         corresponding Candidate's `data` dict in results.json BEFORE
         calling `screen.py consume`.

    This fills in `adr_pct_20d` for EVERY candidate — not just the ones
    that peoplewish/qullamaggie happened to emit it for. Stockbee-only
    candidates (which never compute ADR% in their own SQL) also get the
    value. Cost: 1 shibui MCP call per cron run.

    `symbols` may be empty; the SQL then returns no rows. Pass at least the
    sweep+TV-screen symbol set, capped at ~500 symbols per call (shibui IN
    clause works fine at that scale; >1000 starts to get expensive).
    """
    if not symbols:
        return "-- adr_enrichment: empty symbol list, nothing to compute"
    sym_list = ", ".join(f"'{s.replace(chr(39), chr(39)+chr(39))}'" for s in symbols)
    return f"""
-- ADR% enrichment: 20-day average daily range as % of close, for {len(symbols)} candidate symbols
WITH hist AS (
  SELECT q.symbol, q.date, q.high, q.low, q.close,
         AVG((q.high - q.low) / NULLIF(q.close, 0)) OVER (
           PARTITION BY q.symbol ORDER BY q.date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
         ) * 100 AS adr_pct_20d,
         ROW_NUMBER() OVER (PARTITION BY q.symbol ORDER BY q.date DESC) AS rn
  FROM shibui.stock_quotes q
  WHERE q.symbol IN ({sym_list})
    AND q.exchange IN ('NYSE','NASDAQ','AMEX')
    AND q.date >= (CURRENT_DATE - INTERVAL '45 days')
)
SELECT symbol, ROUND(adr_pct_20d::NUMERIC, 2) AS adr_pct_20d
FROM hist
WHERE rn = 1
ORDER BY symbol
""".strip()


def emit_weekly_sql(date: str) -> str:
    """Weekly refresh: recent IPOs + high short interest. One shibui call.

    The old version of this function was a stub that said "shibui does NOT
    have IPO date or short-interest columns - fall back to Finviz". That was
    true when the skill was written and is now stale: shibui carries
    `general_info.ipo_date` and `ownership_stats.short_percent_float` (both
    verified live 2026-11-03). Finviz is Cloudflare-403 from the Cloud
    runtime in any case, so the fallback was never reachable there.

    Both branches emit the SAME explicitly-named column set, because a UNION
    ALL takes its output column names from the FIRST branch.

    NO BRANCH CARRIES ITS OWN LIMIT — `ipo` used to end in `LIMIT 50` and
    `hsf` in `LIMIT 30`, silently truncating both books. Each branch now
    carries `rows_passing` (`COUNT(*) OVER ()` inside the branch) and the
    outer `LIMIT 200` is shibui's own row ceiling.
    """
    return f"""
-- Weekly refresh for {date}: recent IPOs + high short interest
WITH mc AS (
  SELECT symbol, market_cap FROM shibui.valuation
  WHERE date = (SELECT MAX(date) FROM shibui.valuation WHERE date <= '{date}')
),
ipo AS (
  SELECT 'ipo' AS kind, g.symbol, g.name AS label, g.ipo_date AS event_date,
         mc.market_cap, NULL AS short_percent_float, NULL AS shares_float,
         NULL AS volume, g.gics_sector AS sector, g.type AS security_type,
         COUNT(*) OVER () AS rows_passing
  FROM shibui.general_info g
  JOIN mc ON mc.symbol = g.symbol
  WHERE g.ipo_date >= DATE '{date}' - INTERVAL '365 days'
    AND g.type = 'Common Stock'
    AND mc.market_cap > 1000000000
),
hsf AS (
  SELECT 'high_short_float' AS kind, o.symbol, NULL AS label, NULL AS event_date,
         mc.market_cap, o.short_percent_float, o.shares_float,
         q.volume, g.gics_sector AS sector, g.type AS security_type,
         COUNT(*) OVER () AS rows_passing
  FROM shibui.ownership_stats o
  JOIN mc ON mc.symbol = o.symbol
  JOIN shibui.general_info g ON g.symbol = o.symbol
  JOIN shibui.stock_quotes q ON q.symbol = o.symbol AND q.date = '{date}'
  WHERE o.short_percent_float > 0.20
    AND mc.market_cap > 1000000000
    AND q.volume > 1000000
)
SELECT * FROM ipo
UNION ALL SELECT * FROM hsf
ORDER BY kind, event_date DESC NULLS LAST, short_percent_float DESC NULLS LAST, symbol
LIMIT {SHIBUI_ROW_CAP}
""".strip()


# ---------------------------------------------------------------------------
# Per-branch fetch — the coverage-safe path
# ---------------------------------------------------------------------------
#
# The merged group queries above are the fast path (one call per stylist
# group). But shibui caps every RESULT at 200 rows, so a merged group whose
# branches pass more than 200 rows in total gets cut by the outer LIMIT —
# silently, exactly like the old per-branch caps did.
#
# The coverage-safe path fetches ONE branch per call. The branch's filter is
# uncapped; the query returns one page of at most 200 rows; every row
# carries `rows_passing` — the TRUE count of rows that passed the branch's
# filter — so the caller knows exactly how many more pages to fetch and can
# assert that the published book is complete.
#
# `ORDER BY` is always TOTAL (the branch's sort key plus `symbol`), so
# LIMIT/OFFSET paging is stable and a row cannot appear on two pages or on
# none.

SWEEP_BRANCH_ORDER = {
    "A_stockbee_4pct": "chg_pct DESC, symbol",
    "B_stockbee_ep9m": "volume DESC, symbol",
    "K_stockbee_anticipation": "trend_intensity DESC, symbol",
    "C_qullamaggie_rs": "rs_3m DESC, symbol",
    "D_qullamaggie_ep": "m1 DESC, symbol",
    "E_qullamaggie_5d_gainers": "m1 DESC, symbol",
    "F_qullamaggie_5d_losers": "m1 ASC, symbol",
    "G_peoplewish": "velocity_14d DESC, symbol",
}

# The eight shibui sweep branches, in tiering order.
SWEEP_BRANCHES = tuple(SWEEP_BRANCH_ORDER)

# Which stylist group each branch belongs to.
SWEEP_BRANCH_GROUP = {
    "A_stockbee_4pct": "stockbee",
    "B_stockbee_ep9m": "stockbee",
    "K_stockbee_anticipation": "stockbee",
    "C_qullamaggie_rs": "qullamaggie",
    "D_qullamaggie_ep": "qullamaggie",
    "E_qullamaggie_5d_gainers": "qullamaggie",
    "F_qullamaggie_5d_losers": "qullamaggie",
    "G_peoplewish": "peoplewish",
}


def _branch_sql_parts(date: str, branch: str) -> tuple[str, str]:
    """(support CTEs, branch CTE) for one sweep branch."""
    stockbee = _stockbee_branch_ctes(date)
    if branch in stockbee:
        return _stockbee_support_ctes(date), stockbee[branch]
    qullamaggie = _qullamaggie_branch_ctes(date)
    if branch in qullamaggie:
        return _qullamaggie_support_ctes(date), qullamaggie[branch]
    if branch == "G_peoplewish":
        return _peoplewish_support_ctes(date), _peoplewish_branch_ctes(date)
    raise KeyError(f"unknown sweep branch: {branch!r}")


def emit_sweep_sql_branch(
    date: str,
    branch: str,
    *,
    offset: int = 0,
    limit: int = SHIBUI_ROW_CAP,
) -> str:
    """Emit the SQL for ONE sweep branch, one page.

    The branch's filter is UNCAPCED — there is no `LIMIT` inside the branch
    CTE, so `rows_passing` (`COUNT(*) OVER ()`) is the true number of names
    that passed it. The only LIMIT is the page size, which is shibui's own
    row ceiling and must never be applied inside the branch.

    Fetch pages with `offset = 0, 200, 400, ...` until the number of rows
    collected equals `rows_passing`.
    """
    if branch not in SWEEP_BRANCH_ORDER:
        raise KeyError(f"unknown sweep branch: {branch!r}")
    support, cte = _branch_sql_parts(date, branch)
    order = SWEEP_BRANCH_ORDER[branch]
    return f"""
-- {branch} for {date} (page: offset {offset}, limit {limit})
WITH {support},
{cte}
SELECT * FROM {branch}
ORDER BY {order}
LIMIT {limit} OFFSET {offset}
""".strip()


# ---------------------------------------------------------------------------
# Coverage — the assertion that makes a truncated book impossible to ship
# ---------------------------------------------------------------------------

def branch_coverage(rows: list[dict]) -> dict[str, dict]:
    """Per-branch `rows_passing` / `rows_kept`.

    `rows_passing` is the count the branch itself reports (`COUNT(*) OVER ()`
    computed inside the branch, before any cap applies). `rows_kept` is how
    many rows for that branch were actually published. A branch where the two
    differ was truncated — the defect this whole mechanism exists to catch.
    """
    out: dict[str, dict] = {}
    for row in rows or []:
        origin = row.get("origin")
        if not origin:
            continue
        entry = out.setdefault(
            origin,
            {"rows_passing": None, "rows_kept": 0, "consistent": True},
        )
        entry["rows_kept"] += 1
        raw = row.get("rows_passing")
        if raw is None:
            continue
        try:
            passing = int(raw)
        except (TypeError, ValueError):
            entry["consistent"] = False
            continue
        if entry["rows_passing"] is None:
            entry["rows_passing"] = passing
        elif entry["rows_passing"] != passing:
            entry["consistent"] = False
    return out


def coverage_failures(coverage: dict[str, dict]) -> list[dict]:
    """Branches whose published rows are short of what passed the filter."""
    bad: list[dict] = []
    for origin, c in sorted(coverage.items()):
        passing = c.get("rows_passing")
        kept = int(c.get("rows_kept", 0))
        if not c.get("consistent", True):
            bad.append({
                "origin": origin,
                "rows_passing": passing,
                "rows_kept": kept,
                "reason": "inconsistent rows_passing across the branch's rows",
            })
            continue
        if passing is None:
            continue
        if kept != passing:
            bad.append({
                "origin": origin,
                "rows_passing": passing,
                "rows_kept": kept,
                "short_by": passing - kept,
                "reason": "published rows are fewer than the names that passed the filter",
            })
    return bad


def coverage_cap_signature(coverage: dict[str, dict]) -> list[str]:
    """Branches whose kept count lands EXACTLY on a known cap.

    A branch that returns exactly 30, 50, 60 or 200 rows is a cap, not a
    screen outcome — those are the legacy per-branch caps plus shibui's row
    ceiling. It is reported as a warning even when rows_passing agrees,
    because landing exactly on a cap means the branch MAY have been cut at
    the boundary.
    """
    caps = set(LEGACY_BRANCH_CAPS) | {SHIBUI_ROW_CAP}
    return sorted(
        origin for origin, c in coverage.items()
        if int(c.get("rows_kept", 0)) in caps
    )


def format_coverage_failure(failures: list[dict], coverage: dict[str, dict]) -> str:
    """The loud, actionable message for a coverage failure."""
    lines = [
        "COVERAGE FAILURE — the screen book is INCOMPLETE and must NOT be published.",
        "",
        "A branch published fewer rows than the number of names that passed its filter.",
        "Publishing it would ship a silently truncated book, which is the exact defect",
        "this assertion exists to stop.",
        "",
        "  branch                       rows_passing  rows_kept  short_by",
    ]
    for f in failures:
        lines.append(
            f"  {f['origin']:<28} {str(f.get('rows_passing')):>12} "
            f"{str(f.get('rows_kept')):>10} {str(f.get('short_by', '-')):>9}"
        )
    lines += [
        "",
        "FIX: re-fetch each short branch on its own and page it until the rows",
        "collected equal rows_passing —",
        "  python3 scripts/screen.py emit-branch <branch> <date> --offset <n> --limit 200",
        "Then rebuild. Do NOT publish a truncated book.",
    ]
    sig = coverage_cap_signature(coverage)
    if sig:
        lines += [
            "",
            "CAP SIGNATURE (kept count lands exactly on a cap — the truncation fingerprint): "
            + ", ".join(sig),
        ]
    return "\n".join(lines)


def build_sweep_plan(date: str, *, resolve_latest: bool = False) -> SweepPlan:
    """Build the daily-sweep MCP plan.

    Args:
        date: The cron-fire date (ISO YYYY-MM-DD).
        resolve_latest: If True, emit a preflight batch that resolves
            shibui's `MAX(date) <= date` and use `__RESOLVED_DATE__` as
            a placeholder in every sweep SQL string. The Agent must
            run the preflight batch FIRST, read `latest_date` from the
            response, then string-replace `__RESOLVED_DATE__` with it
            before executing the rest of the batches.

            This handles the shibui T+1 lag: at 18:30 ET on the cron
            day, today's close usually hasn't been ingested yet, so a
            literal `WHERE q.date = '{date}'` returns zero rows and the
            consume step writes all-zero skeleton files. Resolving to
            shibui's latest available date makes the next 18:30 ET cron
            self-heal.

            When True, `SweepPlan.cron_date` is set to `date` so the
            Agent passes it to `consume --date` and outputs land in
            `daily-screens/<cron_date>/` regardless of which data date
            the SQL actually targeted.

            Defaults to False for backwards compat.
    """
    plan = SweepPlan(date=date)

    # The date string that goes into the sweep SQL. When resolving, this
    # is the placeholder the Agent substitutes AFTER running the preflight.
    sql_date = RESOLVED_DATE_PLACEHOLDER if resolve_latest else date

    if resolve_latest:
        plan.cron_date = date
        # Preflight batch: MUST be the first batch and MUST be sequential.
        # Emits one shibui SQL that returns the latest available trading
        # date <= the cron date. The Agent reads `latest_date` from the
        # response and substitutes it into every other SQL string.
        plan.batches.append(MCPBatch(
            name="preflight_resolve_date",
            parallel=False,
            calls=[{
                "tool": "mcp__shibui-finance__stock_data_query",
                "label": "resolve_latest_date",
                "args": {
                    "user_prompt": f"Resolve latest available date in shibui <= {date} (T+1 fallback)",
                    "query": emit_resolve_date_sql(date),
                },
            }],
        ))

    # Batch: pre-filter (one shibui SQL)
    plan.batches.append(MCPBatch(
        name="prefilter",
        parallel=False,
        calls=[{
            "tool": "mcp__shibui-finance__stock_data_query",
            "label": "prefilter_universe",
            "args": {
                "user_prompt": f"Pre-filter universe for stock-screener-suite on {date}",
                "query": emit_prefilter_sql(sql_date),
            },
        }],
    ))

    # Batch: one shibui sweep call PER BRANCH (8 branches, in parallel).
    #
    # This used to be 3 calls — one per stylist group, each a UNION ALL with
    # an outer LIMIT 200. Two things were wrong with that:
    #   * each BRANCH carried its own LIMIT (50 / 50 / 30 and 60 / 30 x3), so
    #     a book was silently truncated while every count still looked
    #     plausible (the 2026-11-04 artifact published `A_stockbee_4pct 50`
    #     and `B_stockbee_ep9m 50` — the CAPS, not screen outcomes);
    #   * even with the per-branch caps removed, shibui caps every RESULT at
    #     200 rows, so a merged group whose branches pass more than 200 rows
    #     in total gets cut by the outer LIMIT — the same silent truncation,
    #     one level up.
    #
    # Fetching one branch per call fixes both: the branch's filter is
    # uncapped, the query returns one page of at most 200 rows, and every row
    # carries `rows_passing` — the TRUE count of names that passed the
    # branch's filter. The Agent then pages any branch whose rows_passing
    # exceeds the rows it collected, and `consume` asserts rows_kept ==
    # rows_passing before anything is published.
    sweep_calls = []
    for branch in SWEEP_BRANCHES:
        sweep_calls.append({
            "tool": "mcp__shibui-finance__stock_data_query",
            "label": f"sweep_branch_{branch}",
            "args": {
                "user_prompt": (
                    f"Sweep branch {branch} on {date} (page 1). Every row carries "
                    f"rows_passing = the number of names that passed this branch's "
                    f"filter. If rows_passing exceeds the rows returned, fetch the "
                    f"next page with --offset."
                ),
                "query": emit_sweep_sql_branch(sql_date, branch),
            },
        })
    plan.batches.append(MCPBatch(
        name="sweep_sql",
        parallel=True,
        calls=sweep_calls,
    ))

    # Batch 3: parallel TradingView calls (Jeff Sun CANSLIM + sector ETF RS + volume breakout)
    plan.batches.append(MCPBatch(
        name="tradingview_screens",
        parallel=True,
        calls=[
            {
                "tool": "mcp__tradingview__screen_stocks",
                "label": "jeff_sun_canslim",
                "args": {
                    "markets": ["america"],
                    "filters": [
                        {"field": "market_cap_basic", "operator": "greater", "value": 1_000_000_000},
                        {"field": "earnings_growth_quarterly_yoy", "operator": "greater", "value": 25},
                        {"field": "sales_growth_quarterly_yoy", "operator": "greater", "value": 25},
                        {"field": "price", "operator": "greater", "value": 5},
                        {"field": "change", "operator": "greater", "value": 0},
                        {"field": "RSI", "operator": "less_or_equal", "value": 80},
                        {"field": "RSI", "operator": "greater_or_equal", "value": 40},
                        {"field": "exchange", "operator": "in_range", "value": ["NASDAQ", "NYSE", "AMEX"]},
                    ],
                    "sort_by": "change",
                    "sort_order": "desc",
                    "limit": 200,
                },
            },
            {
                # NOTE: ETF screener lives in the base `mcp__tradingview__` MCP,
                # not in the `tradingview-advanced__` namespace (which has no
                # `screen_etf` tool). The base MCP's `screen_etf` supports
                # `markets` / `sort_by` / `limit` with `Perf.1M` / `Perf.3M` /
                # `Perf.6M` sortable fields — enough for Hernandez's
                # theme → group RS funnel.
                "tool": "mcp__tradingview__screen_etf",
                "label": "ariel_sector_rs",
                "args": {
                    "markets": ["america"],
                    "sort_by": "Perf.1M",
                    "sort_order": "desc",
                    "limit": 30,
                },
            },
            {
                "tool": "mcp__tradingview-advanced__volume_breakout_scanner",
                "label": "kse_volume_breakout",
                "args": {
                    "exchange": "NASDAQ",
                    "timeframe": "1D",
                    "volume_multiplier": 2,
                    "price_change_min": 3,
                    "limit": 25,
                },
            },
        ],
    ))

    # Batch 4: breadth (shibui SQL + VIX price + sector rotation)
    plan.batches.append(MCPBatch(
        name="breadth",
        parallel=True,
        calls=[
            {
                "tool": "mcp__shibui-finance__stock_data_query",
                "label": "breadth_snapshot",
                "args": {
                    "user_prompt": f"Breadth + ATR extension for {date}",
                    "query": emit_breadth_sql(sql_date),
                },
            },
            {
                "tool": "mcp__tradingview-advanced__yahoo_price",
                "label": "vix_price",
                "args": {"symbol": "^VIX"},
            },
            {
                "tool": "mcp__tradingview-advanced__yahoo_price",
                "label": "vix3m_price",
                "args": {"symbol": "^VIX3M"},
            },
            {
                "tool": "mcp__financekit__sector_rotation",
                "label": "sector_rotation_3mo",
                "args": {"period": "3mo"},
            },
        ],
    ))

    return plan


# ---------------------------------------------------------------------------
# Tiering + output (consume the MCP results)
# ---------------------------------------------------------------------------

@dataclass
class Candidate:
    symbol: str
    origins: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)
    # `convergence_score` counts UNIQUE origins (sub-screen + stylist labels).
    # `n_stylists` counts UNIQUE stylists — the two diverge when a ticker
    # appears in 2+ sub-screens from the same stylist. Tier-A promotion
    # should use `n_stylists`, not `convergence_score`, otherwise a name
    # that hits Stockbee 4% + Stockbee EP9m + Qullamägi + peoplewish
    # (3 stylists) gets the same convergence_score as a name that hits
    # all 5 stylists. Both are added by `tier_candidates`; downstream
    # `select_tier_a` was rewritten to use `n_stylists`.
    convergence_score: int = 0
    n_stylists: int = 0
    flags: dict[str, bool] = field(default_factory=dict)


# Map origin labels (already namespaced "<stylist>_<subquery>" in SQL output
# or written by `tier_candidates` for TV sub-screens) to a short stylist
# tag so we can count unique STYLISTS, not unique sub-screens.
#
# There are FIVE stylist buckets, matching references/tiering.md's
# thresholds ("≥ 3 stylists (out of 5)"):
#
#   stockbee    Pradeep Bonde
#   qullamaggie Kristjan Kullamägi
#   jeff_sun    Jeff Sun — his CANSLIM screen AND his volume-breakout proxy
#   hernandez   Ariel Hernandez
#   peoplewish  Alec Riffle
#
# The volume-breakout screen is folded into `jeff_sun` rather than counted as
# a sixth bucket: it is Jeff Sun's volume proxy, and counting it separately
# would let one stylist's two screens masquerade as two independent opinions
# (a name hitting both would score 2 stylist hits, not 1).
_STYLIST_FROM_ORIGIN = {
    "A_stockbee_4pct": "stockbee",
    "B_stockbee_ep9m": "stockbee",
    "K_stockbee_4pct_with_volume": "stockbee",
    "K_stockbee_anticipation": "stockbee",
    "C_qullamaggie_rs": "qullamaggie",
    "D_qullamaggie_ep": "qullamaggie",
    "E_qullamaggie_5d_gainers": "qullamaggie",
    "F_qullamaggie_5d_losers": "qullamaggie",
    "G_peoplewish": "peoplewish",
    "TV_volume_breakout": "jeff_sun",   # Jeff Sun's volume proxy
    "jeff_sun_canslim": "jeff_sun",
    "H_hernandez_theme": "hernandez",
}

# The five stylist buckets, for validation and for the summary line.
STYLIST_BUCKETS = ("stockbee", "qullamaggie", "jeff_sun", "hernandez", "peoplewish")


def tier_candidates(
    sweep_results: list[dict],
    prefilter_symbols: set[str],
    volume_breakout_results: list[dict],
    canslim_results: list[dict],
) -> dict[str, Candidate]:
    """Merge per-stylist results into a single Candidate map keyed by symbol."""
    out: dict[str, Candidate] = {}

    def add(symbol: str, origin: str, data: dict) -> None:
        if symbol not in out:
            out[symbol] = Candidate(symbol=symbol)
        out[symbol].origins.append(origin)
        out[symbol].data.update(data)

    for row in sweep_results:
        origin = row.get("origin", "?")
        sym = row.get("symbol")
        if sym:
            add(sym, origin, row)

    for row in volume_breakout_results:
        sym = row.get("symbol") or row.get("ticker")
        if sym:
            add(sym, "TV_volume_breakout", row)

    for row in canslim_results:
        sym = row.get("symbol") or row.get("ticker")
        if sym:
            add(sym, "jeff_sun_canslim", row)

    for c in out.values():
        c.convergence_score = len(set(c.origins))
        # Count unique stylists (collapse Stockbee's A/B into one bucket).
        c.n_stylists = len({_STYLIST_FROM_ORIGIN.get(o, o) for o in c.origins})
        c.flags = _compute_skip_flags(c.data)
    return out


def _compute_skip_flags(d: dict) -> dict[str, bool]:
    """Compute the 6 skip-rule flags from OHLC-derived data."""
    # A flag is True, False, or None. None means "NOT COMPUTABLE from this
    # row's fields" — it is NOT the same as False, and it must never be
    # rendered as a positive flag. (2026-11-05: the old defaults made
    # `ma_shrink_5d` TRUE on every row that lacked range_5d/range_20d,
    # because `0 < 0.5 * 1e-9` is True — a missing input became a positive
    # signal on all 1,407 candidates.)
    flags = {
        "atr_shrink": None,
        "wicky_breakout": None,
        "ma_shrink_5d": None,
        "day2_no_follow": None,
        "no_reclaim_15m": None,
        "second_bite_d2": None,
    }
    # atr_shrink: atr_14 < 0.6 × median(atr_14, 63d)
    atr14 = d.get("atr_14")
    atr63 = d.get("atr_63_median")
    if atr14 is not None and atr63 is not None and atr63 > 0:
        flags["atr_shrink"] = atr14 < 0.6 * atr63

    # wicky_breakout: breakout candle wick > body AND close RVOL < 1.2
    if all(d.get(k) is not None for k in ("open", "high", "low")):
        body = abs(d.get("close", 0) - d.get("open", 0))
        high = d.get("high", 0)
        low = d.get("low", 0)
        rng = max(high - low, 1e-9)
        wick = rng - body
        rvol = d.get("rvol_close")
        if body > 0 and rvol is not None:
            flags["wicky_breakout"] = (wick > body) and (rvol < 1.2)

    # ma_shrink_5d: 5d range < 50% of 20d range
    rng5 = d.get("range_5d")
    rng20 = d.get("range_20d")
    if rng5 is not None and rng20 is not None and rng20 > 0:
        flags["ma_shrink_5d"] = rng5 < 0.5 * rng20

    # day2_no_follow: requires day-2 data — filled by Agent post-entry
    # no_reclaim_15m: requires intraday tape — live only
    # second_bite_d2: requires intraday tape — live only
    return flags


# Tier thresholds. Single source of truth — referenced by both `select_focus`,
# `select_tier_a`, and the markdown summary writer. Tier-A is the strict
# "appears in 3+ stylists" filter; Focus is the looser "2+ stylists OR
# top-velocity" filter. Tunable in one place from `references/tiering.md`.
FOCUS_THRESHOLD_STYLISTS = 2   # appears in ≥ 2 stylists
TIER_A_THRESHOLD_STYLISTS = 3  # appears in ≥ 3 stylists (out of 5)
FOCUS_MAX = 12                 # references/tiering.md size cap
TIER_A_MAX = 8                 # references/tiering.md size cap


def select_focus(candidates: dict[str, Candidate]) -> dict[str, Candidate]:
    """Filter to Focus tier: appears in ≥ FOCUS_THRESHOLD_STYLISTS stylists
    OR top-5 velocity."""
    if not candidates:
        return {}
    high_conv = {s: c for s, c in candidates.items() if c.n_stylists >= FOCUS_THRESHOLD_STYLISTS}
    # top-5 velocity
    by_velocity = sorted(
        candidates.items(),
        key=lambda kv: kv[1].data.get("velocity_14d", 0),
        reverse=True,
    )[:5]
    top_velocity = {s: c for s, c in by_velocity}
    out = {}
    out.update(high_conv)
    for s, c in top_velocity.items():
        if s not in out:
            out[s] = c
    return dict(list(out.items())[:12])  # cap at 12


def select_tier_a(candidates: dict[str, Candidate]) -> dict[str, Candidate]:
    """Tier-A: appears in ≥ TIER_A_THRESHOLD_STYLISTS distinct stylists.

    Note: this is intentionally STRICTER than Focus — Tier-A is the actionable
    shortlist the trader opens positions on, Focus is the broader watchlist.
    Past back-test on 2026-09-18: original `convergence_score ≥ 4` (which
    counted UNIQUE ORIGINS, not unique stylists) produced only USDE.NASDAQ —
    a 3-stylist × 4-origin hit that was misleadingly labelled "convergence 4".
    With `n_stylists ≥ 3`, expect 3-8 names per day in a normal regime and
    the `_summary.md` label "≥ 3 stylists" matches what the trader sees.

    Capped at TIER_A_MAX (8) per references/tiering.md's size cap. The cap is
    applied AFTER the threshold, so on a broad day the list is truncated — the
    truncation is reported in `_results.json` as `tier_a_truncated`."""
    hits = {s: c for s, c in candidates.items() if c.n_stylists >= TIER_A_THRESHOLD_STYLISTS}
    if len(hits) <= TIER_A_MAX:
        return hits
    ranked = sorted(
        hits.items(),
        key=lambda kv: (-kv[1].n_stylists, -(kv[1].data.get("velocity_14d") or 0), kv[0]),
    )
    return dict(ranked[:TIER_A_MAX])


def compute_regime(breadth_rows: list, vix: float | None, vix3m: float | None) -> dict:
    """Compute the regime flag from the breadth rows + VIX/VIX3M.

    Accepts the breadth SQL output (list of dicts with `metric` field) and reshapes it.
    Backwards-compat: also accepts a dict (the old shape).

    Note: ^VXV has no live data on Yahoo Finance; we use ^VIX3M (VIX 3-month)
    as the long-end VIX proxy. ratio = VIX / VIX3M > 1 means front-end stress
    is elevated vs the long end (the "uncertainty band" Sun watches).
    """
    # Reshape if breadth_rows is a dict (backwards compat)
    if isinstance(breadth_rows, dict):
        # 1) Old shape (pre-patch): breadth_pct_largecap / index_below_20sma / atr_extensions
        breadth_pct = breadth_rows.get("breadth_pct_largecap", 100)
        index_below_20sma = breadth_rows.get("index_below_20sma", False)
        atr_extensions = breadth_rows.get("atr_extensions", {})

        # 2) Agent-pre-aggregated shape (what a daily-sweep Agent emits when it summarises
        #    the breadth SQL output into one object): largecap_breadth_pct_above_sma_20 /
        #    index_pct_above_sma_20 / indices_atr_extension_pct
        if "largecap_breadth_pct_above_sma_20" in breadth_rows:
            breadth_pct = float(breadth_rows["largecap_breadth_pct_above_sma_20"])
        if "index_pct_above_sma_20" in breadth_rows:
            index_below_20sma = float(breadth_rows["index_pct_above_sma_20"]) < 50.0
        if "indices_atr_extension_pct" in breadth_rows and isinstance(
            breadth_rows["indices_atr_extension_pct"], dict
        ):
            atr_extensions = {
                sym: {"extension_pct": float(v)}
                for sym, v in breadth_rows["indices_atr_extension_pct"].items()
            }
    else:
        # breadth_rows is a list of dicts from the new breadth SQL
        breadth_pct = 100.0
        index_below_20sma = False
        atr_extensions = {}
        for row in breadth_rows:
            metric = row.get("metric")
            if metric == "largecap_breadth":
                v = row.get("breadth_pct_largecap")
                if v is not None:
                    breadth_pct = float(v)
            elif metric == "index_above_sma_summary":
                # if majority of the 5 ETFs are below SMA20, the index is below
                pct = row.get("pct_above_sma_20")
                if pct is not None and float(pct) < 0.5:
                    index_below_20sma = True
            elif metric == "index_atr_extension":
                # The breadth SQL emits the index identifier as `ticker`
                # (`SELECT 'index_atr_extension', ticker, close, …`), and the
                # documented pre-aggregated shape calls it `etf`. This
                # function used to read `row.get("symbol")` ONLY, so the
                # extension map came back EMPTY and `late_cycle` could
                # never be anything but False — a flag that can only ever be
                # false is not a flag. `tier_candidates` already reads
                # `symbol or ticker`; this now reads the same chain.
                sym = row.get("symbol") or row.get("ticker") or row.get("etf")
                ext_pct = row.get("extension_pct")
                if sym and ext_pct is not None:
                    atr_extensions[sym] = {"extension_pct": float(ext_pct)}

    size_cut = 0
    if index_below_20sma and breadth_pct < 40:
        size_cut = 50

    uncertainty = False
    if vix and vix3m and vix3m > 0:
        uncertainty = (vix / vix3m) > 1.0

    # late_cycle: any index ETF more than 6% above its 50-DMA
    late_cycle = any(
        (ext or {}).get("extension_pct", 0) > 6 for ext in atr_extensions.values()
    )

    return {
        "size_cut_pct": size_cut,
        "uncertainty": uncertainty,
        "late_cycle": late_cycle,
        "breadth_pct_spx": breadth_pct,
        "index_below_20sma": index_below_20sma,
        "vix": vix,
        "vix3m": vix3m,
        "atr_extensions": atr_extensions,
    }


# ---------------------------------------------------------------------------
# Markdown writers
# ---------------------------------------------------------------------------

def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("")
        return
    keys: list[str] = []
    for r in rows:
        for k in r.keys():
            if k not in keys:
                keys.append(k)
    lines = [",".join(keys)]
    for r in rows:
        lines.append(",".join(str(r.get(k, "")) for k in keys))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_per_stylist_markdown(path: Path, label: str, candidates: dict[str, Candidate]) -> None:
    lines = [f"# {label}", "", f"Generated {date_cls.today().isoformat()}", "", f"Count: {len(candidates)}", "", "| Symbol | Stylists | Origins | Flags | Velocity | ADR% | Notes |", "|---|---|---|---|---|---|---|"]
    for sym, c in sorted(candidates.items()):
        flags = ", ".join(k for k, v in c.flags.items() if v) or "—"
        lines.append(
            f"| {sym} | {c.n_stylists} | {c.convergence_score} | {flags} | "
            f"{c.data.get('velocity_14d', '')} | {c.data.get('adr_pct_20d', c.data.get('adr_pct', ''))} | "
            f"{', '.join(sorted(set(c.origins)))} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_summary(
    path: Path,
    regime: dict,
    tier_a: dict,
    short_cands: list,
    long_cands: list,
    reversal: list,
    coverage: dict[str, dict] | None = None,
) -> None:
    lines = [
        "# Daily sweep summary",
        "",
        f"Generated {date_cls.today().isoformat()}",
        "",
        "## Regime",
        "",
        f"- size_cut_pct: **{regime.get('size_cut_pct', 0)}**",
        f"- uncertainty: **{regime.get('uncertainty', False)}**",
        f"- late_cycle: **{regime.get('late_cycle', False)}**",
        f"- breadth % S&P > 20-DMA: **{regime.get('breadth_pct_spx', 'n/a')}**",
        "",
    ]
    if coverage:
        lines += [
            "## Screen coverage (rows_passing = names that passed the branch filter)",
            "",
            "| Branch | rows_passing | rows_kept |",
            "|---|---|---|",
        ]
        for origin, c in sorted(coverage.items()):
            lines.append(
                f"| {origin} | {c.get('rows_passing')} | {c.get('rows_kept')} |"
            )
        lines.append("")
        sig = coverage_cap_signature(coverage)
        if sig:
            lines += [
                "> **Cap signature:** " + ", ".join(sig) + " land(s) exactly on a known cap "
                "(30 / 50 / 60 / 200). When `rows_passing` agrees, that is the true count; "
                "when it does not, the branch was truncated and the run must fail.",
                "",
            ]
    lines += [
        f"## Tier-A (appears in ≥ {TIER_A_THRESHOLD_STYLISTS} stylists): {len(tier_a)}",
        "",
    ]
    for sym, c in sorted(tier_a.items()):
        lines.append(f"- **{sym}** (stylists: {c.n_stylists}, origins: {c.convergence_score}, sources: {', '.join(sorted(set(c.origins)))})")
    if not tier_a:
        lines.append("- (none)")

    lines += [
        "",
        f"## Parabolic short candidates: {len(short_cands)}",
        "",
    ]
    for s in short_cands[:10]:
        lines.append(f"- {s}")

    lines += [
        "",
        f"## Parabolic long / mean-reversion: {len(long_cands)}",
        "",
    ]
    for s in long_cands[:10]:
        lines.append(f"- {s}")

    if reversal:
        lines += [
            "",
            f"## 3:55 PM reversal-bullish: {len(reversal)}",
            "",
        ]
        for r in reversal:
            lines.append(
                f"- {r.get('symbol')} entry ~{r.get('entry_price')} "
                f"stop {r.get('next_day_stop')} (funds held {r.get('funds_held')})"
            )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def cmd_plan(args: argparse.Namespace) -> int:
    # Same-day short-circuit: if today's sweep already ran and produced a
    # complete output set, do not spend the ~20 MCP calls again unless the
    # caller forces it. The resolved data date is compared too, so a later
    # ingestion (shibui's T+1 catch-up) invalidates the cache.
    if getattr(args, "use_cache", False):
        status = cache_status(args.date, getattr(args, "vault", None) or DEFAULT_VAULT)
        if status.get("valid"):
            resolved = getattr(args, "resolved_date", None)
            if resolved and status.get("data_as_of") and resolved != status["data_as_of"]:
                print(
                    f"cache for {args.date} is stale: cached data_as_of="
                    f"{status['data_as_of']} but shibui now resolves to {resolved}; "
                    f"re-running the sweep"
                )
            else:
                print(json.dumps(status, indent=2))
                print("CACHE HIT — outputs already exist for this date; nothing to do.")
                return 0
        else:
            print(f"no usable cache for {args.date} ({status.get('reason')}); running the sweep.")
    plan = build_sweep_plan(args.date, resolve_latest=args.resolve_latest)
    out = args.out or "plan.json"
    Path(out).write_text(plan.to_json())
    total = sum(len(b.calls) for b in plan.batches)
    label = f"{len(plan.batches)} batches, {total} MCP calls"
    if plan.cron_date:
        label += f", resolve_latest=True (cron_date={plan.cron_date})"
    print(f"Plan written to {out}: {label}")
    return 0


def cmd_cache(args: argparse.Namespace) -> int:
    """Report the cache state for a date (JSON on stdout)."""
    status = cache_status(args.date, Path(args.vault) if args.vault else DEFAULT_VAULT)
    print(json.dumps(status, indent=2))
    return 0


def cmd_emit_sql(args: argparse.Namespace) -> int:
    # adr_enrichment takes a symbol list, not a date — handle it specially
    # so the existing date-keyed dispatch stays simple.
    if args.kind == "adr_enrichment":
        symbols = [s.strip() for s in (args.symbols or "").split(",") if s.strip()]
        print(emit_adr_enrichment_sql(symbols))
        return 0
    sql = {
        "prefilter": emit_prefilter_sql,
        "sweep": emit_sweep_sql,
        "sweep_stockbee": emit_sweep_sql_stockbee,
        "sweep_qullamaggie": emit_sweep_sql_qullamaggie,
        "sweep_peoplewish": emit_sweep_sql_peoplewish,
        "breadth": emit_breadth_sql,
        "reversal_bullish": emit_reversal_bullish_sql,
        "weekly": emit_weekly_sql,
        "resolve_date": emit_resolve_date_sql,
    }.get(args.kind)
    if sql is None:
        print(f"unknown sql kind: {args.kind}", file=sys.stderr)
        return 2
    print(sql(args.date))
    return 0


def cmd_consume(args: argparse.Namespace) -> int:
    results_path = Path(args.in_path)
    if not results_path.exists():
        print(f"results file not found: {results_path}", file=sys.stderr)
        return 2
    data = json.loads(results_path.read_text())
    dry_run = bool(getattr(args, "dry_run", False))

    # Accept either a unified "sweep" array (older Agent behaviour) or the
    # per-stylist "sweep_stockbee" / "sweep_qullamaggie" / "sweep_peoplewish"
    # keys a daily-sweep Agent naturally emits. Merge the per-stylist keys in
    # if "sweep" is missing.
    sweep_rows = data.get("sweep", [])
    if not sweep_rows:
        sweep_rows = (
            data.get("sweep_stockbee", [])
            + data.get("sweep_qullamaggie", [])
            + data.get("sweep_peoplewish", [])
        )

    # --- Coverage assertion -------------------------------------------------
    # Every shibui sweep row carries `rows_passing`: the number of names that
    # passed ITS branch's filter, computed inside the branch before any cap
    # applied. If a branch published fewer rows than that, the book was
    # truncated, and a truncated book must NOT be published.
    coverage = branch_coverage(sweep_rows)
    declared = data.get("screen_coverage")
    if isinstance(declared, dict) and declared:
        # The Agent may declare its own per-branch measurement (it knows how
        # many pages it fetched). Cross-check it against the rows: a declared
        # count that disagrees with the rows is itself a defect.
        for origin, d in declared.items():
            if not isinstance(d, dict):
                continue
            entry = coverage.setdefault(
                origin, {"rows_passing": None, "rows_kept": 0, "consistent": True}
            )
            try:
                entry["rows_passing"] = int(d.get("rows_passing"))
            except (TypeError, ValueError):
                entry["consistent"] = False
            try:
                entry["rows_kept"] = int(d.get("rows_kept"))
            except (TypeError, ValueError):
                entry["consistent"] = False
    failures = coverage_failures(coverage)
    if failures:
        print(format_coverage_failure(failures, coverage), file=sys.stderr)
        print(
            "COVERAGE FAILURE: nothing was written. Re-fetch the short branches "
            "and rebuild.",
            file=sys.stderr,
        )
        return 1
    prefilter_rows = data.get("prefilter", [])
    prefilter_symbols = {r.get("symbol") for r in prefilter_rows if r.get("symbol")}
    volume_breakout_rows = data.get("volume_breakout", [])
    # CANSNALIM daily-sweep Agent writes under "jeff_sun_canslim"; consume's
    # legacy key was "canslim". Accept either.
    canslim_rows = data.get("canslim") or data.get("jeff_sun_canslim") or []
    breadth = data.get("breadth", {})
    vix = data.get("vix_price")
    vix3m = data.get("vix3m_price")
    atr_extensions = data.get("atr_extensions", {})
    reversal_rows = data.get("reversal_bullish", [])

    candidates = tier_candidates(sweep_rows, prefilter_symbols, volume_breakout_rows, canslim_rows)

    # Stylist groupings
    stockbee_syms = {s for s, c in candidates.items() if any(o.startswith("A_stockbee") or o.startswith("B_stockbee") or o.startswith("K_stockbee") for o in c.origins)}
    qullamaggie_syms = {s for s, c in candidates.items() if any(o.startswith("C_qullamaggie") or o.startswith("D_qullamaggie") or o.startswith("E_qullamaggie") or o.startswith("F_qullamaggie") for o in c.origins)}
    sun_syms = {s for s, c in candidates.items() if any(o == "jeff_sun_canslim" or o == "TV_volume_breakout" for o in c.origins)}
    ariel_syms = {s for s, c in candidates.items() if any(o == "jeff_sun_canslim" for o in c.origins)}  # CANSLIM is the proxy; refine via sector ETF
    peoplewish_syms = {s for s, c in candidates.items() if any(o.startswith("G_peoplewish") for o in c.origins)}

    short_cands = sorted({s for s, c in candidates.items() if any(o.startswith("E_qullamaggie_5d_gainers") for o in c.origins)})
    long_reversal_cands = sorted({s for s, c in candidates.items() if any(o.startswith("F_qullamaggie_5d_losers") for o in c.origins)})

    focus = select_focus(candidates)
    tier_a = select_tier_a(focus)

    regime = compute_regime(breadth, vix, vix3m)

    out_dir = vault_dir(args.date, Path(args.vault) if args.vault else DEFAULT_VAULT)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Per-stylist Markdown
    write_per_stylist_markdown(out_dir / "stockbee.md", "Stockbee — Pradeep Bonde", {s: candidates[s] for s in stockbee_syms})
    write_per_stylist_markdown(out_dir / "qullamaggie.md", "Qullamàgi — Kristjan Kullamägi", {s: candidates[s] for s in qullamaggie_syms})
    write_per_stylist_markdown(out_dir / "jeff-sun.md", "Jeff Sun, CFTe", {s: candidates[s] for s in sun_syms})
    write_per_stylist_markdown(out_dir / "ariel-hernandez.md", "Ariel Hernandez", {s: candidates[s] for s in ariel_syms})
    write_per_stylist_markdown(out_dir / "peoplewish.md", "peoplewish — Alec Riffle", {s: candidates[s] for s in peoplewish_syms})

    # Merged tiers
    write_per_stylist_markdown(out_dir / "master.md", "Master (union, deduped)", candidates)
    write_per_stylist_markdown(out_dir / "focus.md", f"Focus (appears in ≥{FOCUS_THRESHOLD_STYLISTS} stylists OR top-5 velocity)", focus)
    write_per_stylist_markdown(out_dir / "tier-a.md", f"Tier-A (appears in ≥{TIER_A_THRESHOLD_STYLISTS} stylists)", tier_a)

    # Parabolic sub-screens. Each row carries an explicit `_source` so the
    # next-day Agent can see whether a tier was populated from Tier-1 MCP
    # (shibui SQL) or a fallback tier. For these two CSVs the rows always
    # come from a shibui SQL sweep → _source=mcp.
    write_csv(
        out_dir / "short-candidates.csv",
        [{"symbol": s, "origin": "qullamaggie_5d_gainers", "_source": "mcp"} for s in short_cands],
    )
    write_csv(
        out_dir / "long-reversal-candidates.csv",
        [{"symbol": s, "origin": "qullamaggie_5d_losers", "_source": "mcp"} for s in long_reversal_cands],
    )

    # Reversal-bullish (Bonde 3:55 PM)
    if reversal_rows:
        write_csv(out_dir / "reversal-bullish-3_55.csv", reversal_rows)

    # Regime payload — FLAT shape with a schema version, validated before it
    # is written. A payload that nests the regime under a `regime` key (the
    # 2026-11-04 break) is rejected here rather than published.
    write_regime_payload(out_dir / "_regime.json", regime)

    # Machine-readable companion. Downstream routines (pre-market brief,
    # weekly recap, setup journal) read this instead of re-parsing Markdown,
    # so a wording change in a .md file can never silently break them.
    tier_a_pool = {s for s, c in focus.items() if c.n_stylists >= TIER_A_THRESHOLD_STYLISTS}
    results_payload = {
        "date": args.date,
        "data_as_of": data.get("data_as_of") or args.date,
        "regime": regime,
        "stylist_buckets": list(STYLIST_BUCKETS),
        "thresholds": {
            "focus_stylists": FOCUS_THRESHOLD_STYLISTS,
            "focus_max": FOCUS_MAX,
            "tier_a_stylists": TIER_A_THRESHOLD_STYLISTS,
            "tier_a_max": TIER_A_MAX,
        },
        "counts": {
            "candidates": len(candidates),
            "focus": len(focus),
            "tier_a": len(tier_a),
            "short_candidates": len(short_cands),
            "long_reversal_candidates": len(long_reversal_cands),
        },
        "tier_a_pool": len(tier_a_pool),
        "tier_a_truncated": len(tier_a_pool) > len(tier_a),
        "screen_coverage": coverage,
        "tier_a": sorted(tier_a),
        "focus": sorted(focus),
        "short_candidates": short_cands,
        "long_reversal_candidates": long_reversal_cands,
        "candidates": [
            {
                "symbol": sym,
                "origins": c.origins,
                "stylists": sorted({_STYLIST_FROM_ORIGIN.get(o, o) for o in c.origins}),
                "n_stylists": c.n_stylists,
                "convergence_score": c.convergence_score,
                "flags": {k: v for k, v in c.flags.items() if v},
                "data": c.data,
            }
            for sym, c in sorted(candidates.items())
        ],
    }
    (out_dir / "_results.json").write_text(json.dumps(results_payload, indent=2, default=str))

    # Cache marker: the next run reads this to decide whether the day's work
    # is already done (same date, same resolved data date).
    (out_dir / "_cache.json").write_text(json.dumps({
        "cron_date": args.date,
        "data_as_of": data.get("data_as_of") or args.date,
        "regime": {k: regime.get(k) for k in ("size_cut_pct", "uncertainty", "late_cycle")},
        "counts": results_payload["counts"],
    }, indent=2))

    # Summary
    write_summary(out_dir / "_summary.md", regime, tier_a, short_cands, long_reversal_cands, reversal_rows, coverage)

    if dry_run:
        # Undo every write we just did. Cleaner than branching every path:
        # the Agent dry-running wants a "what would happen" answer, not a
        # half-written directory.
        written = list(out_dir.iterdir())
        for p in written:
            try:
                p.unlink()
            except OSError:
                pass
        try:
            out_dir.rmdir()
        except OSError:
            pass  # directory wasn't empty after rmtree cycle
        # Print the would-be regime + counts so the Agent can sanity-check
        # the tiering logic without re-running MCP calls.
        print(f"DRY-RUN: would have written {len(written)} files (none written) to {out_dir}")
        print(f"DRY-RUN regime: {json.dumps(regime)}")
        print(f"DRY-RUN tier-a count: {len(tier_a)}; focus count: {len(focus)}; short: {len(short_cands)}; long: {len(long_reversal_cands)}")
        return 0

    print(f"Wrote {len(list(out_dir.iterdir()))} files to {out_dir}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="stock-screener-suite orchestrator")
    sub = p.add_subparsers(dest="cmd")

    plan_p = sub.add_parser("plan", help="emit a JSON plan of MCP calls for a date")
    plan_p.add_argument("date")
    plan_p.add_argument("--out", default=None)
    plan_p.add_argument(
        "--resolve-latest",
        action="store_true",
        help=(
            "Emit a preflight batch that resolves shibui's latest available "
            "trading date <= the cron date, and use __RESOLVED_DATE__ as a "
            "placeholder in every sweep SQL string. The Agent must run the "
            "preflight batch first and string-substitute the placeholder with "
            "the resolved date before executing the rest. Handles shibui's "
            "T+1 data lag so the 18:30 ET daily-sweep cron self-heals instead "
            "of writing zero-hit skeleton files when today's close hasn't "
            "been ingested yet."
        ),
    )

    plan_p.add_argument(
        "--use-cache",
        action="store_true",
        help=(
            "Short-circuit when this date's sweep already produced a complete "
            "output set. The cached resolved data date is compared with "
            "--resolved-date, so a later shibui ingestion invalidates the cache."
        ),
    )
    plan_p.add_argument(
        "--resolved-date",
        dest="resolved_date",
        default=None,
        help="The data date shibui resolved to (from the preflight query), used to invalidate a stale cache.",
    )
    plan_p.add_argument(
        "--vault",
        default=None,
        help="Vault root that holds <date>/ directories (default: the local vault path).",
    )

    cache_p = sub.add_parser("cache", help="report whether a date's sweep is already done")
    cache_p.add_argument("date")
    cache_p.add_argument("--vault", default=None, help="Vault root that holds <date>/ directories")

    sql_p = sub.add_parser("emit-sql", help="emit a single shibui SQL string")
    sql_p.add_argument("kind", choices=["prefilter", "sweep", "sweep_stockbee", "sweep_qullamaggie", "sweep_peoplewish", "breadth", "reversal_bullish", "weekly", "resolve_date"])
    sql_p.add_argument("date")

    cons_p = sub.add_parser("consume", help="apply tiering + write outputs from MCP results JSON")
    cons_p.add_argument("--in", dest="in_path", required=True)
    cons_p.add_argument("--date", required=True)
    cons_p.add_argument("--dry-run", dest="dry_run", action="store_true",
                       help="compute tiering/regime and print what would be written, but DO NOT create any files")
    cons_p.add_argument("--vault", default=None,
                       help="Vault root that holds <date>/ directories (default: the local vault path).")

    fv_p = sub.add_parser("finviz-url", help="print a Finviz screener URL for tier-2 fallback")
    fv_p.add_argument("kind", choices=sorted(FINVIZ_BUILDERS.keys()) + ["custom"])
    fv_p.add_argument("--filter", dest="filters", action="append", default=[], help="filter codes (only with kind=custom)")

    br_p = sub.add_parser(
        "emit-branch",
        help="emit the SQL for ONE sweep branch, one page (the coverage-safe fetch path)",
    )
    br_p.add_argument("branch", choices=list(SWEEP_BRANCHES))
    br_p.add_argument("date")
    br_p.add_argument("--offset", type=int, default=0,
                      help="row offset for paging (default 0)")
    br_p.add_argument("--limit", type=int, default=SHIBUI_ROW_CAP,
                      help=f"page size (default {SHIBUI_ROW_CAP} = shibui's row ceiling)")

    fp_p = sub.add_parser("finviz-parse", help="parse Finviz screener HTML to tickers (used after web_fetch)")
    fp_p.add_argument("--html-file", required=True, help="path to a saved Finviz HTML page")
    fp_p.add_argument("--out", default=None, help="output CSV path (default: stdout)")

    # Top-level convenience wrapper for `python screen.py reversal-bullish <date>`
    # (matches the SKILL.md spec; avoids Agents re-discovering that the kind lives
    # under `emit-sql` and getting confused).
    rb_p = sub.add_parser("reversal-bullish", help="emit the Bonde 3:55 PM reversal-bullish SQL (alias for `emit-sql reversal_bullish`)")
    rb_p.add_argument("date")

    # Find the most recent prior trading day that has a vault entry on disk.
    # Used by the pre-market brief cron to skip file-walk reasoning when
    # looking up "yesterday's" output.
    prev_p = sub.add_parser(
        "previous-trading-day",
        help="walk backward from <date> (default: today) and print the most recent prior "
             "vault/<DATE>/ directory that exists with at least _regime.json inside. "
             "Output: ISO date string on stdout; empty string if none found within --walkback days.",
    )
    prev_p.add_argument("date", nargs="?", default=None, help="start date (YYYY-MM-DD); default = today ET")
    prev_p.add_argument("--walkback", type=int, default=7, help="max calendar days to look back (default 7)")
    prev_p.add_argument("--vault", default=None, help="override vault root (default: DEFAULT_VAULT)")

    args = p.parse_args(argv)
    if args.cmd == "plan":
        return cmd_plan(args)
    if args.cmd == "emit-sql":
        return cmd_emit_sql(args)
    if args.cmd == "consume":
        return cmd_consume(args)
    if args.cmd == "cache":
        return cmd_cache(args)
    if args.cmd == "emit-branch":
        print(emit_sweep_sql_branch(
            args.date, args.branch, offset=args.offset, limit=args.limit))
        return 0
    if args.cmd == "finviz-url":
        return _cmd_finviz_url(args)
    if args.cmd == "finviz-parse":
        return _cmd_finviz_parse(args)
    if args.cmd == "reversal-bullish":
        # Reuse cmd_emit_sql's logic with the reversal_bullish kind pinned.
        args.kind = "reversal_bullish"
        return cmd_emit_sql(args)
    if args.cmd == "previous-trading-day":
        return _cmd_previous_trading_day(args)
    p.print_help()
    return 2


def _cmd_previous_trading_day(args: argparse.Namespace) -> int:
    """Return the most recent prior date that has a non-empty vault/<date>/ dir.

    A "non-empty" vault day is one with at least _regime.json inside
    (regime is written by both breadth-snapshot 06:30 ET and daily-sweep
    18:30 ET, so its presence is a strong proxy for "this trading day
    completed an end-of-day snapshot").

    Skips Sat/Sun automatically — those have no writes unless the
    breadth-snapshot cron mistakenly fired on a holiday, in which case
    the next business day's run will still find the prior business day.
    """
    from datetime import date as _date, timedelta

    if args.date:
        try:
            start = _date.fromisoformat(args.date)
        except ValueError:
            print(f"bad date: {args.date} (expected YYYY-MM-DD)", file=sys.stderr)
            return 2
    else:
        start = _date.today()

    vault = Path(args.vault) if args.vault else DEFAULT_VAULT
    for d in range(1, args.walkback + 1):
        candidate = start - timedelta(days=d)
        # Skip weekends — those don't have end-of-day snapshots unless
        # Monday is a holiday (in which case this returns Friday, which
        # is what the pre-market brief actually wants).
        if candidate.weekday() >= 5:
            continue
        day_dir = vault / candidate.isoformat()
        if (day_dir / "_regime.json").exists():
            print(candidate.isoformat())
            return 0
    # Nothing found within walkback window
    print("")
    return 0


def _cmd_finviz_url(args: argparse.Namespace) -> int:
    if args.kind == "custom":
        print(finviz_url(args.filters))
    else:
        print(FINVIZ_BUILDERS[args.kind]())
    return 0


def _cmd_finviz_parse(args: argparse.Namespace) -> int:
    html_path = Path(args.html_file)
    if not html_path.exists():
        print(f"file not found: {html_path}", file=sys.stderr)
        return 2
    rows = parse_finviz_table(html_path.read_text(encoding="utf-8", errors="ignore"))
    if args.out:
        write_csv(
            Path(args.out),
            [
                {
                    "ticker": r["ticker"],
                    "_source": "finviz_fallback",  # finviz-parse always emits Tier-2 output
                    **{f"c{i}": r["cells"][i] if i < len(r["cells"]) else "" for i in range(20)},
                }
                for r in rows
            ],
        )
        print(f"wrote {len(rows)} rows to {args.out}")
    else:
        for r in rows[:20]:
            print(r["ticker"], "|", " | ".join(r["cells"][:6]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
