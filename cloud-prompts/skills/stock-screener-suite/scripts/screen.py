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
from datetime import date as date_cls
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Vault layout
# ---------------------------------------------------------------------------

DEFAULT_VAULT = Path("C:/Users/admin/research/markets/daily-screens")


def vault_dir(date: str, root: Path = DEFAULT_VAULT) -> Path:
    return root / date


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
#     reversal-bullish-3:55.{md,csv} — written by reversal-bullish cron ONLY
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

    Schema: stock_quotes (OHLCV) + valuation (market_cap) + technical_indicators joined
    on (symbol, date). LIMIT 200 enforced by the server.
    """
    return f"""
-- Pre-filter for {date}
SELECT q.symbol, q.close, q.exchange, q.volume AS today_volume, v.market_cap
FROM shibui.stock_quotes q
JOIN shibui.valuation v ON q.symbol = v.symbol AND q.date = v.date
WHERE q.date = '{date}'
  AND q.exchange IN ('NYSE', 'NASDAQ', 'AMEX')
  AND q.close > 3
  AND v.market_cap > 300000000
  AND q.volume > 100000
ORDER BY v.market_cap DESC
LIMIT 200
""".strip()


def emit_sweep_sql_stockbee(date: str) -> str:
    """Stockbee group: 4% breakout + EP9M + Anticipation. Single shibui call, UNION ALL."""
    return f"""
-- Stockbee sweep for {date}: 4% breakout + EP9M + Anticipation
WITH today AS (
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
  WHERE q.date BETWEEN '2026-07-23' AND '{date}'
    AND q.exchange IN ('NYSE','NASDAQ','AMEX')
)
A_stockbee_4pct AS (
  SELECT 'A_stockbee_4pct' AS origin, symbol, close, volume,
         (close / NULLIF(prev_close, 0) - 1) * 100 AS chg_pct
  FROM today
  WHERE date = '{date}'
    AND prev_close IS NOT NULL AND prev_close > 0
    AND close / prev_close >= 1.04
    AND volume > prev_volume
    AND volume >= 100000
    AND close >= 3
  ORDER BY chg_pct DESC
  LIMIT 50
),
B_stockbee_ep9m AS (
  SELECT 'B_stockbee_ep9m' AS origin, symbol, close, volume,
         (close - low) / NULLIF(high - low, 0) * 100 AS dcr_pct
  FROM today
  WHERE date = '{date}'
    AND volume >= 8900000
    AND close >= 3
  ORDER BY volume DESC
  LIMIT 50
),
K_stockbee_anticipation AS (
  SELECT 'K_stockbee_anticipation' AS origin, symbol, close,
         atr_7d / NULLIF(atr_65d, 0) AS trend_intensity,
         (max_high_10d - min_low_10d) / NULLIF(close, 0) AS base_width_pct
  FROM today
  WHERE date = '{date}'
    AND atr_7d / NULLIF(atr_65d, 0) >= 1.05
    AND (max_high_10d - min_low_10d) / NULLIF(close, 0) <= 0.08
    AND prev_close IS NOT NULL
    AND close / prev_close < 1.04
  ORDER BY trend_intensity DESC
  LIMIT 30
)
SELECT * FROM A_stockbee_4pct
UNION ALL SELECT * FROM B_stockbee_ep9m
UNION ALL SELECT * FROM K_stockbee_anticipation
ORDER BY origin, symbol
LIMIT 200
""".strip()


def emit_sweep_sql_qullamaggie(date: str) -> str:
    """Qullamägi group: RS leaders + EP + 5d gainers + 5d losers. Single shibui call."""
    return f"""
-- Qullamägi sweep for {date}: multi-timeframe RS + EP + 5d movers
WITH hist AS (
  SELECT q.symbol, q.date, q.open, q.high, q.low, q.close, q.volume,
         t.atr_14,
         LAG(q.close, 5)  OVER w AS close_5d_ago,
         LAG(q.close, 21) OVER w AS close_21d_ago,
         LAG(q.close, 63) OVER w AS close_63d_ago,
         LAG(q.close, 126) OVER w AS close_126d_ago,
         LAG(q.close, 252) OVER w AS close_252d_ago,
         LAG(q.close) OVER w AS prev_close,
         AVG((q.high - q.low) / NULLIF(q.close, 0)) OVER (PARTITION BY q.symbol ORDER BY q.date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) * 100 AS adr_pct_20d,
         AVG(q.close * q.volume) OVER (PARTITION BY q.symbol ORDER BY q.date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS adv_dollar_20d
  FROM shibui.stock_quotes q
  JOIN shibui.technical_indicators t ON q.symbol = t.symbol AND q.date = t.date
  WHERE q.date >= '2025-12-01'  -- ~9 months, covers 252 trading days
    AND q.exchange IN ('NYSE','NASDAQ','AMEX')
  WINDOW w AS (PARTITION BY q.symbol ORDER BY q.date)
)
C_qullamaggie_rs AS (
  SELECT 'C_qullamaggie_rs' AS origin, symbol, close,
         (close / NULLIF(close_252, 0) - 1) * 100 AS rs_12m,
         (close / NULLIF(close_126, 0) - 1) * 100 AS rs_6m,
         (close / NULLIF(close_63, 0) - 1) * 100 AS rs_3m,
         (close / NULLIF(close_21, 0) - 1) * 100 AS rs_1m,
         adr_pct_20d, adv_dollar_20d
  FROM hist
  WHERE date = '{date}'
    AND adv_dollar_20d >= 20000000
    AND adr_pct_20d >= 4.5
    AND close_252 IS NOT NULL AND close_126 IS NOT NULL AND close_63 IS NOT NULL AND close_21 IS NOT NULL
    AND ((close / close_21 - 1) >= 0.25 OR (close / close_63 - 1) >= 0.50 OR (close / close_126 - 1) >= 1.50)
  ORDER BY rs_3m DESC
  LIMIT 60
),
D_qullamaggie_ep AS (
  SELECT 'D_qullamaggie_ep' AS origin, symbol, close,
         (open / NULLIF(prev_close, 0) - 1) * 100 AS gap_pct,
         volume / NULLIF(adv_dollar_20d / NULLIF(close, 0), 0) AS vol_ratio
  FROM hist
  WHERE date = '{date}'
    AND prev_close IS NOT NULL AND prev_close > 0
    AND open / prev_close >= 1.10
    AND adv_dollar_20d >= 50000000
  ORDER BY gap_pct DESC
  LIMIT 30
),
E_qullamaggie_5d_gainers AS (
  SELECT 'E_qullamaggie_5d_gainers' AS origin, symbol, close,
         (close / NULLIF(close_5d_ago, 0) - 1) * 100 AS gain_5d,
         adr_pct_20d
  FROM hist
  WHERE date = '{date}'
    AND close_5d_ago IS NOT NULL AND close_5d_ago > 0
    AND (close / close_5d_ago - 1) >= 0.25
    AND adv_dollar_20d >= 50000000
  ORDER BY gain_5d DESC
  LIMIT 30
),
F_qullamaggie_5d_losers AS (
  SELECT 'F_qullamaggie_5d_losers' AS origin, symbol, close,
         (close / NULLIF(close_5d_ago, 0) - 1) * 100 AS loss_5d
  FROM hist
  WHERE date = '{date}'
    AND close_5d_ago IS NOT NULL AND close_5d_ago > 0
    AND (close / close_5d_ago - 1) <= -0.25
    AND (close / close_5d_ago - 1) >= -0.50
    AND adv_dollar_20d >= 50000000
  ORDER BY loss_5d ASC
  LIMIT 30
)
SELECT * FROM C_qullamaggie_rs
UNION ALL SELECT * FROM D_qullamaggie_ep
UNION ALL SELECT * FROM E_qullamaggie_5d_gainers
UNION ALL SELECT * FROM F_qullamaggie_5d_losers
ORDER BY origin, symbol
LIMIT 200
""".strip()


def emit_sweep_sql_peoplewish(date: str) -> str:
    """peoplewish: ADR% > 5% + Dollar Volume > $50M, sort by velocity. Single shibui call."""
    return f"""
-- peoplewish sweep for {date}: ADR + dollar volume + velocity
WITH hist AS (
  SELECT q.symbol, q.date, q.close, q.volume,
         LAG(q.close, 14) OVER w AS close_14d_ago,
         AVG((q.high - q.low) / NULLIF(q.close, 0)) OVER (PARTITION BY q.symbol ORDER BY q.date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) * 100 AS adr_pct_20d,
         AVG(q.close * q.volume) OVER (PARTITION BY q.symbol ORDER BY q.date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS adv_dollar_20d
  FROM shibui.stock_quotes q
  WHERE q.date >= '2026-08-15'  -- ~30 days, covers 14-day LAG + 20-day rolling window
    AND q.exchange IN ('NYSE','NASDAQ','AMEX')
  WINDOW w AS (PARTITION BY q.symbol ORDER BY q.date)
)
SELECT 'G_peoplewish' AS origin, symbol, close,
       adr_pct_20d,
       adv_dollar_20d,
       (close / NULLIF(close_14d_ago, 0) - 1) * 100 AS velocity_14d
FROM hist
WHERE date = '{date}'
  AND adr_pct_20d >= 5
  AND adv_dollar_20d >= 50000000
ORDER BY velocity_14d DESC
LIMIT 200
""".strip()


# Legacy single-call sweep — kept for back-compat with the SQL subcommand choices.
def emit_sweep_sql(date: str) -> str:
    """Default sweep SQL (uses the Stockbee group)."""
    return emit_sweep_sql_stockbee(date)


def emit_breadth_sql(date: str) -> str:
    """Breadth (large-cap proxy above 20-DMA) + ATR extension on 5 index ETFs.

    Uses large-cap (market_cap > 10B) as the breadth proxy instead of a hardcoded
    constituents list (no sp500_constituents table exists in shibui).
    """
    return f"""
-- Breadth + ATR extension + index-below-20sma flag for {date}
WITH idx AS (
  SELECT q.symbol, q.close,
         t.sma_20, t.sma_50, t.atr_14,
         AVG(t.atr_14) OVER (PARTITION BY q.symbol ORDER BY q.date ROWS BETWEEN 251 PRECEDING AND CURRENT ROW) AS atr_252d_avg
  FROM shibui.stock_quotes q
  JOIN shibui.technical_indicators t ON q.symbol = t.symbol AND q.date = t.date
  WHERE q.ticker IN ('SPY','RSP','QQQ','QQQE','IWM')
    AND q.date = '{date}'
),
largecap AS (
  SELECT q.symbol, q.close,
         t.sma_20
  FROM shibui.stock_quotes q
  JOIN shibui.technical_indicators t ON q.symbol = t.symbol AND q.date = t.date
  JOIN shibui.valuation v ON q.symbol = v.symbol AND q.date = v.date
  WHERE q.date = '{date}'
    AND q.exchange IN ('NYSE','NASDAQ','AMEX')
    AND v.market_cap > 10000000000
),
largecap_breadth AS (
  SELECT AVG(CASE WHEN close > sma_20 THEN 1.0 ELSE 0.0 END) * 100 AS pct
  FROM largecap
),
idx_summary AS (
  SELECT
    AVG(CASE WHEN close > sma_20 THEN 1.0 ELSE 0.0 END) AS pct_above_sma_20,
    AVG(CASE WHEN close > sma_50 THEN 1.0 ELSE 0.0 END) AS pct_above_sma_50
  FROM idx
)
SELECT 'largecap_breadth' AS metric,
       NULL AS symbol,
       NULL AS close,
       NULL AS sma_20,
       NULL AS sma_50,
       NULL AS atr_14,
       NULL AS atr_252d_avg,
       NULL AS extension_pct,
       NULL AS pct_above_sma_20,
       NULL AS pct_above_sma_50,
       (SELECT pct FROM largecap_breadth) AS breadth_pct_largecap
UNION ALL
SELECT 'index_above_sma_summary' AS metric,
       NULL, NULL, NULL, NULL, NULL, NULL, NULL,
       (SELECT pct_above_sma_20 FROM idx_summary),
       (SELECT pct_above_sma_50 FROM idx_summary),
       NULL
UNION ALL
SELECT 'index_atr_extension' AS metric,
       symbol,
       close,
       sma_20,
       sma_50,
       atr_14,
       atr_252d_avg,
       (close - sma_50) / NULLIF(sma_50, 0) * 100 AS extension_pct,
       NULL, NULL,
       NULL
FROM idx
ORDER BY metric, symbol
""".strip()


def emit_reversal_bullish_sql(date: str) -> str:
    """Bonde 3:55 PM reversal-bullish SQL.

    Schema note: shibui has no `institutional_holders_count`. Falls back to a
    market_cap proxy (`> 5B`, the rough proxy for "held by ≥ 1,000 funds").
    """
    return f"""
-- Reversal bullish for {date}
WITH today AS (
  SELECT q.symbol, q.date, q.open, q.high, q.low, q.close,
         v.market_cap,
         LAG(q.close, 2) OVER (PARTITION BY q.symbol ORDER BY q.date) AS close_2d_ago,
         LAG(q.close)    OVER (PARTITION BY q.symbol ORDER BY q.date) AS prev_close
  FROM shibui.stock_quotes q
  JOIN shibui.valuation v ON q.symbol = v.symbol AND q.date = v.date
  WHERE q.date = '{date}'
    AND q.exchange IN ('NYSE','NASDAQ','AMEX')
    AND v.market_cap > 5000000000
)
SELECT symbol,
       close AS entry_price,
       LEAST(open, close) AS next_day_stop,
       NULL AS funds_held_proxy,
       (close - low) / NULLIF(high - low, 0) AS lower_shadow_ratio,
       ABS(close - open) / NULLIF(high - low, 0) AS body_ratio
FROM today
WHERE close < open * 1.02
  AND (close - low) / NULLIF(high - low, 0) >= 0.6
  AND ABS(close - open) / NULLIF(high - low, 0) <= 0.4
  AND close_2d_ago IS NOT NULL AND close_2d_ago > 0
  AND close / close_2d_ago < 1.0
ORDER BY (close - low) / NULLIF(high - low, 0) DESC
LIMIT 10
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
    """Weekly refresh placeholder.

    Schema note: shibui does NOT have IPO date or short_interest_pct_float
    columns. Both are served via the Finviz tier-2 fallback (see
    `references/fallbacks.md`). This SQL is a no-op stub kept for back-compat
    with the `emit-sql weekly` subcommand.
    """
    return f"""
-- Weekly refresh for {date}: shibui has no IPO date or short-interest columns.
-- Fall back to Finviz URL builders:
--   finviz_ipo_recent() and finviz_high_short_float() from screen.py.
-- See references/fallbacks.md for the chain.
SELECT 'fallback_to_finviz' AS note, '{date}' AS date
""".strip()


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

    # Batch: 3 parallel shibui sweep calls (Stockbee group, Qullamägi group, peoplewish).
    # The Stockbee group needs only ~30 days of history (LAG 1, rolling 7/65 atr);
    # the Qullamägi group needs ~252 days (multi-timeframe RS); the peoplewish
    # group needs ~30 days (14-day velocity + 20-day rolling). Splitting by
    # lookback keeps each CTE small and avoids one giant query.
    plan.batches.append(MCPBatch(
        name="sweep_sql",
        parallel=True,
        calls=[
            {
                "tool": "mcp__shibui-finance__stock_data_query",
                "label": "sweep_stockbee",
                "args": {
                    "user_prompt": f"Stockbee sweep (4% breakout + EP9M + Anticipation) on {date}",
                    "query": emit_sweep_sql_stockbee(sql_date),
                },
            },
            {
                "tool": "mcp__shibui-finance__stock_data_query",
                "label": "sweep_qullamaggie",
                "args": {
                    "user_prompt": f"Qullamägi sweep (RS leaders + EP + 5d movers) on {date}",
                    "query": emit_sweep_sql_qullamaggie(sql_date),
                },
            },
            {
                "tool": "mcp__shibui-finance__stock_data_query",
                "label": "sweep_peoplewish",
                "args": {
                    "user_prompt": f"peoplewish sweep (ADR + dollar volume + velocity) on {date}",
                    "query": emit_sweep_sql_peoplewish(sql_date),
                },
            },
        ],
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
_STYLIST_FROM_ORIGIN = {
    "A_stockbee_4pct": "stockbee",
    "B_stockbee_ep9m": "stockbee",
    "K_stockbee_4pct_with_volume": "stockbee",
    "C_qullamaggie_rs": "qullamaggie",
    "D_qullamaggie_ep": "qullamaggie",
    "E_qullamaggie_5d_gainers": "qullamaggie",
    "F_qullamaggie_5d_losers": "qullamaggie",
    "G_peoplewish": "peoplewish",
    "TV_volume_breakout": "tv_volume_breakout",  # Jeff Sun's volume proxy
    "jeff_sun_canslim": "jeff_sun_canslim",
}


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
    flags = {
        "atr_shrink": False,
        "wicky_breakout": False,
        "ma_shrink_5d": False,
        "day2_no_follow": False,
        "no_reclaim_15m": False,
        "second_bite_d2": False,
    }
    # atr_shrink: atr_14 < 0.6 × median(atr_14, 63d)
    atr14 = d.get("atr_14")
    atr63 = d.get("atr_63_median")
    if atr14 is not None and atr63 is not None and atr63 > 0:
        flags["atr_shrink"] = atr14 < 0.6 * atr63

    # wicky_breakout: breakout candle wick > body AND close RVOL < 1.2
    body = abs(d.get("close", 0) - d.get("open", 0))
    high = d.get("high", 0)
    low = d.get("low", 0)
    rng = max(high - low, 1e-9)
    wick = rng - body
    rvol = d.get("rvol_close", 1.0)
    if body > 0:
        flags["wicky_breakout"] = (wick > body) and (rvol < 1.2)

    # ma_shrink_5d: 5d range < 50% of 20d range
    rng5 = d.get("range_5d", 0)
    rng20 = d.get("range_20d", 1e-9)
    if rng20 > 0:
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
    the `_summary.md` label "≥ 3 stylists" matches what the trader sees."""
    return {s: c for s, c in candidates.items() if c.n_stylists >= TIER_A_THRESHOLD_STYLISTS}


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
                sym = row.get("symbol")
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


def write_summary(path: Path, regime: dict, tier_a: dict, short_cands: list, long_cands: list, reversal: list) -> None:
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
    plan = build_sweep_plan(args.date, resolve_latest=args.resolve_latest)
    out = args.out or "plan.json"
    Path(out).write_text(plan.to_json())
    total = sum(len(b.calls) for b in plan.batches)
    label = f"{len(plan.batches)} batches, {total} MCP calls"
    if plan.cron_date:
        label += f", resolve_latest=True (cron_date={plan.cron_date})"
    print(f"Plan written to {out}: {label}")
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

    out_dir = vault_dir(args.date)
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
        write_csv(out_dir / "reversal-bullish-3:55.csv", reversal_rows)

    # Regime payload
    (out_dir / "_regime.json").write_text(json.dumps(regime, indent=2))

    # Summary
    write_summary(out_dir / "_summary.md", regime, tier_a, short_cands, long_reversal_cands, reversal_rows)

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

    sql_p = sub.add_parser("emit-sql", help="emit a single shibui SQL string")
    sql_p.add_argument("kind", choices=["prefilter", "sweep", "sweep_stockbee", "sweep_qullamaggie", "sweep_peoplewish", "breadth", "reversal_bullish", "weekly", "resolve_date"])
    sql_p.add_argument("date")

    cons_p = sub.add_parser("consume", help="apply tiering + write outputs from MCP results JSON")
    cons_p.add_argument("--in", dest="in_path", required=True)
    cons_p.add_argument("--date", required=True)
    cons_p.add_argument("--dry-run", dest="dry_run", action="store_true",
                       help="compute tiering/regime and print what would be written, but DO NOT create any files")

    fv_p = sub.add_parser("finviz-url", help="print a Finviz screener URL for tier-2 fallback")
    fv_p.add_argument("kind", choices=sorted(FINVIZ_BUILDERS.keys()) + ["custom"])
    fv_p.add_argument("--filter", dest="filters", action="append", default=[], help="filter codes (only with kind=custom)")

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
