#!/usr/bin/env python3
"""
breadth_metrics.py — the SETTLED layer of the cron #10 breadth snapshot.

Contract marker: breadth-artifact-v1

WHY THIS EXISTS
---------------
The 2026-11-03 artifact published "65.19% of the 902 large caps are above their 20-DMA" and
nothing else a breadth reader actually trades: no advance/decline tally (the routine said
out loud that it could not compute one), no percentile (65% is unremarkable in one regime and
alarming in another), and no first-class divergence metric (the one genuinely new thing the
run found — broad breadth healthy while the index posture was weak — was buried in a bullet).

Everything in this script is SETTLED data from shibui: the session that has actually closed.
The LIVE tape (VIX, index levels, sector ETFs) is NOT touched here — that layer belongs to
other feeds and is never blended with these numbers.

THE FOUR THINGS THIS ADDS
-------------------------
1. A REAL advance/decline tally, computed from `stock_quotes` closes with a LAG() self-join,
   over the SAME universe the breadth percentage uses (the indicator-joined large-cap set),
   plus the 10-session cumulative net advances (the ADL) and its slope.
2. `breadth_pctile_1y` — today's breadth level ranked against its own trailing 1-year
   distribution, and the same percentile for the 50-DMA split and the index-ETF count.
3. `breadth_divergence` — large-cap breadth minus index-ETF breadth, banded, with the last
   five sessions so the reader can see it widening or closing.
4. The regime flags as STRUCTURED fields, with `atr_extensions` asserted non-empty.

THE `late_cycle` TRAP (read this before trusting the flag)
-----------------------------------------------------------
`emit_breadth_sql()` selects the index identifier into a column named **`ticker`**:
    SELECT 'index_atr_extension', ticker, close, ...
A consumer that reads only `row.get("symbol")` therefore gets an EMPTY extension map, and
`late_cycle` — computed as `any(...)` over that empty map — is **always False**. It fails
silently and looks plausible. `compute_regime()` in `screen.py` reads
`row.get("symbol") or row.get("ticker") or row.get("etf")`, and this script asserts the
extension map is non-empty whenever the five ETF rows are present. A regime flag computed
over an empty collection is not a flag.

USAGE
    python3 breadth_metrics.py --date 2026-11-05 --out-dir /workspace/daily-screens/2026-11-05

    --date          the session to describe. Defaults to the latest shibui session that has
                    closed on or before today (shibui is T+1, so on a fire day this is the
                    PRIOR session — that is correct, not an error).
    --out-dir       where to write breadth-snapshot.csv, breadth-snapshot.json and
                    _regime-intraday.json.
    --bridge        path to mcp_bridge.py (default /workspace/mcp_bridge.py).
    --lookback-days trailing window for the percentile distributions (default 380 ≈ 1 year).
    --ad-sessions   sessions in the advance/decline window (default 12; 10 are published).
    --csv-rows      trailing sessions written to the CSV (default 30).

Exit codes: 0 = metrics computed and written; 1 = a data guard failed (nothing written).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

CONTRACT = "breadth-artifact-v1"

# --------------------------------------------------------------------------------------
# the published constants — these are the CONTRACT. Keep them in sync with
# tools/check_breadth_artifact.py and with SKILL.md §3.5.
# --------------------------------------------------------------------------------------
MARKET_CAP_FLOOR = 10_000_000_000      # $10B, unchanged — the universe is not being re-cut
EXCHANGES = ("NYSE", "NASDAQ", "AMEX")
INDEX_ETFS = ("SPY", "RSP", "QQQ", "QQQE", "IWM")

PCTILE_WINDOW_DAYS = 380               # ~1 year of sessions for the percentile distributions
AD_SESSION_WINDOW = 60                 # sessions fetched for A/D (the ADL needs a real base)
AD_PUBLISH_WINDOW = 10                 # the published ADL window (and the slope's window)
CSV_TRAILING_ROWS = 30

# bands
PCTILE_HIGH = 80.0                    # >= 80th percentile -> ABOVE_NORMAL
PCTILE_LOW = 20.0                     # <= 20th percentile -> BELOW_NORMAL
DIVERGENCE_BROAD_PP = 15.0            # >= +15 pp -> BROAD
DIVERGENCE_NARROW_PP = -15.0          # <= -15 pp -> NARROW

# the five regimes' thresholds live in screen.py; these mirror them for the inline path
LATE_CYCLE_EXTENSION_PCT = 6.0

USER_PROMPT = (
    "cron #10 breadth snapshot: settled large-cap breadth, advance/decline, "
    "percentile and divergence metrics for the market breadth artifact"
)

SQL_BREADTH_SERIES = """
WITH mc AS (
  SELECT symbol, market_cap FROM shibui.valuation
  WHERE date = (SELECT MAX(date) FROM shibui.valuation WHERE date <= '{end_date}')
)
SELECT q.date AS date,
       COUNT(*) AS n_lc,
       AVG(CASE WHEN q.close > t.sma_20 THEN 1.0 ELSE 0.0 END) * 100 AS pct_above_sma_20,
       AVG(CASE WHEN q.close > t.sma_50 THEN 1.0 ELSE 0.0 END) * 100 AS pct_above_sma_50,
       COUNT(*) OVER () AS rows_passing
FROM shibui.stock_quotes q
JOIN shibui.technical_indicators t ON q.symbol = t.symbol AND q.date = t.date
JOIN mc ON mc.symbol = q.symbol
WHERE q.exchange IN ('NYSE','NASDAQ','AMEX')
  AND mc.market_cap > {mc_floor}
  AND q.date BETWEEN DATE '{start_date}' AND DATE '{end_date}'
GROUP BY q.date
ORDER BY q.date
LIMIT {limit} OFFSET {offset}
""".strip()

SQL_INDEX_SERIES = """
WITH idx AS (
  SELECT q.ticker AS ticker, q.date AS date, q.close AS close, t.sma_20 AS sma_20, t.sma_50 AS sma_50
  FROM shibui.stock_quotes q
  JOIN shibui.technical_indicators t ON q.symbol = t.symbol AND q.date = t.date
  WHERE q.ticker IN ('SPY','RSP','QQQ','QQQE','IWM')
    AND q.date BETWEEN DATE '{start_date}' AND DATE '{end_date}'
)
SELECT date,
       COUNT(*) AS n_etf,
       SUM(CASE WHEN close > sma_20 THEN 1 ELSE 0 END) AS n_above_sma_20,
       SUM(CASE WHEN close > sma_50 THEN 1 ELSE 0 END) AS n_above_sma_50,
       COUNT(*) OVER () AS rows_passing
FROM idx
GROUP BY date
ORDER BY date
LIMIT {limit} OFFSET {offset}
""".strip()

SQL_AD_SERIES = """
WITH mc AS (
  SELECT symbol, market_cap FROM shibui.valuation
  WHERE date = (SELECT MAX(date) FROM shibui.valuation WHERE date <= '{end_date}')
), q AS (
  SELECT q.symbol AS symbol, q.date AS date, q.close AS close,
         LAG(q.close) OVER (PARTITION BY q.symbol ORDER BY q.date) AS prev_close
  FROM shibui.stock_quotes q
  WHERE q.exchange IN ('NYSE','NASDAQ','AMEX')
    AND q.date BETWEEN DATE '{start_date}' AND DATE '{end_date}'
)
SELECT q.date AS date,
       COUNT(*) AS n,
       COUNT(*) FILTER (WHERE q.close > q.prev_close) AS advancing,
       COUNT(*) FILTER (WHERE q.close < q.prev_close) AS declining,
       COUNT(*) FILTER (WHERE q.close = q.prev_close) AS unchanged,
       COUNT(*) OVER () AS rows_passing
FROM q
JOIN mc ON mc.symbol = q.symbol
JOIN shibui.technical_indicators t ON t.symbol = q.symbol AND t.date = q.date
WHERE mc.market_cap > {mc_floor}
GROUP BY q.date
ORDER BY q.date
LIMIT {limit} OFFSET {offset}
""".strip()

SQL_ETF_EXTENSION = """
WITH idx_hist AS (
  SELECT q.symbol AS symbol, q.ticker AS ticker, q.date AS date, q.close AS close,
         t.sma_20 AS sma_20, t.sma_50 AS sma_50, t.atr_14 AS atr_14,
         AVG(t.atr_14) OVER (PARTITION BY q.symbol ORDER BY q.date
                             ROWS BETWEEN 251 PRECEDING AND CURRENT ROW) AS atr_252d_avg,
         ROW_NUMBER() OVER (PARTITION BY q.symbol ORDER BY q.date DESC) AS rn
  FROM shibui.stock_quotes q
  JOIN shibui.technical_indicators t ON q.symbol = t.symbol AND q.date = t.date
  WHERE q.ticker IN ('SPY','RSP','QQQ','QQQE','IWM')
    AND q.date BETWEEN DATE '{start_date}' AND DATE '{end_date}'
)
SELECT symbol, ticker, date, close, sma_20, sma_50, atr_14, atr_252d_avg,
       (close - sma_50) / NULLIF(sma_50, 0) * 100 AS extension_pct,
       (close - sma_50) / NULLIF(atr_252d_avg, 0) AS atr_extension_multiple
FROM idx_hist
WHERE rn = 1 AND date = '{end_date}'
ORDER BY ticker
""".strip()

SQL_LATEST_SESSION = """
SELECT MAX(date) AS latest FROM shibui.stock_quotes WHERE date <= '{end_date}'
""".strip()

SQL_VALUATION_SNAPSHOT = """
SELECT MAX(date) AS snapshot_date FROM shibui.valuation WHERE date <= '{end_date}'
""".strip()

CSV_COLUMNS = [
    "date", "n_lc", "pct_above_sma_20", "pct_above_sma_50",
    "n_etf_above_sma_20", "n_etf_above_sma_50", "breadth_divergence_pp",
    "advancing", "declining", "unchanged", "ad_net", "adl_cum", "adl_slope_10d",
    "breadth_pctile_1y", "divergence_pctile_1y", "is_data_date",
]


class DataGuardError(RuntimeError):
    """A data guard failed — the metrics are NOT published."""


# --------------------------------------------------------------------------------------
# bridge plumbing
# --------------------------------------------------------------------------------------
class Bridge:
    """Thin, safe wrapper around the shibui MCP-over-HTTP bridge.

    Two rules from the fleet's hard-won lessons are enforced here:
      * EVERY call writes its OWN args file. A shared path means that parallel workers
        overwrite each other's query and every worker returns the same rows — a run that
        looks perfectly healthy and is entirely wrong.
      * EVERY paged query asserts `rows_kept == rows_passing`. A per-page cap that
        silently truncates a series deletes data while the query still SUCCEEDS.
    """

    PAGE = 200  # shibui's per-query row ceiling

    def __init__(self, bridge_path: str):
        self.bridge_path = bridge_path
        self._seq = 0
        self.calls = 0

    def query(self, sql: str) -> list[dict]:
        self._seq += 1
        self.calls += 1
        fd, path = tempfile.mkstemp(prefix=f"_breadth_args_{os.getpid()}_{self._seq}_", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump({"query": sql, "user_prompt": USER_PROMPT}, fh)
            proc = subprocess.run(
                [sys.executable, self.bridge_path, "shibui", "stock_data_query", path],
                capture_output=True, text=True, timeout=180,
            )
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
        out = (proc.stdout or "").strip()
        if proc.returncode != 0 and not out:
            raise DataGuardError(f"bridge call failed (rc={proc.returncode}): {(proc.stderr or '')[:400]}")
        try:
            payload = json.loads(out)
        except json.JSONDecodeError:
            raise DataGuardError(f"bridge returned non-JSON: {out[:400]}")
        if isinstance(payload, dict):
            detail = payload.get("detail") or payload.get("error") or payload
            raise DataGuardError(f"bridge error: {str(detail)[:500]}")
        return payload

    def query_paged(self, sql_template: str, **fmt) -> list[dict]:
        """Run a paged query and assert the collected rows match the passing count."""
        rows: list[dict] = []
        offset = 0
        rows_passing = None
        while True:
            page = self.query(sql_template.format(limit=self.PAGE, offset=offset, **fmt))
            if not page:
                break
            if "rows_passing" not in page[0]:
                raise DataGuardError("paged query did not return rows_passing — refusing to publish an unverified series")
            rows_passing = int(page[0]["rows_passing"])
            rows.extend(page)
            offset += self.PAGE
            if offset >= rows_passing:
                break
        if rows_passing is None:
            raise DataGuardError("paged query returned no rows")
        if len(rows) != rows_passing:
            raise DataGuardError(
                f"truncated series: collected {len(rows)} rows, the query says {rows_passing} pass"
            )
        return rows


# --------------------------------------------------------------------------------------
# metric helpers
# --------------------------------------------------------------------------------------
def percentile_rank(value: float, population: list[float]) -> float:
    """Inclusive percentile: the share of the population at or below `value`, 0..100."""
    if not population:
        raise DataGuardError("percentile of an empty population")
    below = sum(1 for v in population if v <= value)
    return round(below / len(population) * 100.0, 1)


def pctile_band(pctile: float) -> str:
    if pctile >= PCTILE_HIGH:
        return "ABOVE_NORMAL"
    if pctile <= PCTILE_LOW:
        return "BELOW_NORMAL"
    return "NORMAL"


def divergence_band(pp: float) -> str:
    if pp >= DIVERGENCE_BROAD_PP:
        return "BROAD"
    if pp <= DIVERGENCE_NARROW_PP:
        return "NARROW"
    return "MATCHED"


def ols_slope(values: list[float]) -> float:
    """Least-squares slope of values against their index (points per session)."""
    n = len(values)
    if n < 2:
        return 0.0
    xs = list(range(n))
    mx = sum(xs) / n
    my = sum(values) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, values))
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return 0.0
    return num / den


def compute_regime(breadth_rows: list[dict], vix: float | None, vix3m: float | None) -> dict:
    """The regime flags, computed from the breadth rows.

    This mirrors `screen.py::compute_regime()` and, critically, reads the index identifier
    from `symbol` OR `ticker` OR `etf` — the breadth SQL emits `ticker`, so a consumer that
    reads only `symbol` gets an empty extension map and a `late_cycle` that can never fire.
    """
    breadth_pct = 100.0
    index_below_20sma = False
    atr_extensions: dict[str, dict] = {}
    for row in breadth_rows:
        metric = row.get("metric")
        if metric == "largecap_breadth":
            v = row.get("breadth_pct_largecap")
            if v is not None:
                breadth_pct = float(v)
        elif metric == "index_above_sma_summary":
            pct = row.get("pct_above_sma_20")
            if pct is not None and float(pct) < 0.5:
                index_below_20sma = True
        elif metric == "index_atr_extension":
            sym = row.get("symbol") or row.get("ticker") or row.get("etf")
            ext = row.get("extension_pct")
            if sym and ext is not None:
                atr_extensions[sym] = {"extension_pct": float(ext)}

    size_cut = 0
    if index_below_20sma and breadth_pct < 40:
        size_cut = 50
    uncertainty = bool(vix and vix3m and vix3m > 0 and (vix / vix3m) > 1.0)
    late_cycle = any(
        (ext or {}).get("extension_pct", 0) > LATE_CYCLE_EXTENSION_PCT
        for ext in atr_extensions.values()
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


# --------------------------------------------------------------------------------------
# the live volatility pair (Cboe delayed-quote CDN)
# --------------------------------------------------------------------------------------
CBOE_QUOTES = "https://cdn.cboe.com/api/global/delayed_quotes/quotes/{sym}.json"


def fetch_vix_pair(symbols=("_VIX", "_VIX3M"), timeout: int = 30, pulls: int = 2) -> dict:
    """Fetch the VIX/VIX3M pair from the Cboe delayed-quote CDN.

    Two rules from the fleet's memory of this feed:
      * `curl -L` is MANDATORY — the CDN answers a 307 without it.
      * DURING REGULAR HOURS `close` == `current_price` (both are the live trade) and
        `prev_day_close` is the prior settle. AFTER 16:00 ET `close` is the cash settle
        and `current_price` is the after-hours print. BEFORE 09:30 ET there is no live
        VIX print on this feed at all — the CDN serves the PRIOR session's settle, and it
        has been seen serving a TRANSIENT value for it minutes after the close (16.89 for
        a session that settled at 16.61). So the pair is pulled TWICE and a disagreement
        is published as `vix_stable: false` rather than hidden behind one number.

    A failure here degrades the regime payload; it does NOT fail the breadth metrics.
    """
    first = _fetch_vix_once(symbols, timeout)
    second = _fetch_vix_once(symbols, timeout) if pulls > 1 else first
    out = second if second.get("vix") is not None else first
    out["vix_fetches"] = [
        {"vix": first.get("vix"), "vix3m": first.get("vix3m"), "quote_time_et": first.get("quote_time_et")},
        {"vix": second.get("vix"), "vix3m": second.get("vix3m"), "quote_time_et": second.get("quote_time_et")},
    ]
    out["vix_stable"] = (
        first.get("vix") is not None and second.get("vix") is not None
        and abs(float(first["vix"]) - float(second["vix"])) < 0.01
        and abs(float(first.get("vix3m") or 0) - float(second.get("vix3m") or 0)) < 0.01
    )
    return out


def _fetch_vix_once(symbols=("_VIX", "_VIX3M"), timeout: int = 30) -> dict:
    out = {"vix": None, "vix3m": None, "quote_time_et": None, "source": "unavailable",
           "prev_close": {}, "price_change_pct": {}, "session_mode": None, "quote_date": None}
    try:
        from zoneinfo import ZoneInfo
        et = datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        et = datetime.now()
    minutes = et.hour * 60 + et.minute
    weekday = et.weekday() < 5
    if not weekday:
        mode = "weekend — the CDN serves the last session's settle"
        use = "close"
    elif minutes < 9 * 60 + 30:
        # Pre-market: the VIX has no live print on this feed before 09:30 ET, so the CDN
        # is serving the PREVIOUS session's settle. Label it as that — quoting it as a
        # live print is how a stale number gets published as today's.
        mode = "pre-market — prior session settle (no live VIX print on this feed before 09:30 ET)"
        use = "close"
    elif minutes < 16 * 60:
        # Regular hours: `close` == `current_price` == the live trade.
        mode = "regular hours — live print"
        use = "current_price"
    else:
        # After the close: `close` is the cash settle, `current_price` is the after-hours print.
        mode = "after hours — settled close"
        use = "close"
    for sym in symbols:
        try:
            proc = subprocess.run(
                ["curl", "-sL", "--max-time", str(timeout),
                 "-H", "User-Agent: Mozilla/5.0 (X11; Linux x86_64) breadth-snapshot",
                 CBOE_QUOTES.format(sym=sym)],
                capture_output=True, text=True, timeout=timeout + 10,
            )
            payload = json.loads(proc.stdout or "{}")
            data = payload.get("data") or {}
            if not data:
                continue
            price = data.get(use)
            if price is None:
                price = data.get("close") or data.get("current_price")
            key = "vix" if sym == "_VIX" else "vix3m"
            out[key] = float(price) if price is not None else None
            out["prev_close"][key] = data.get("prev_day_close")
            out["price_change_pct"][key] = data.get("price_change_percent")
            if sym == "_VIX":
                out["quote_time_et"] = data.get("last_trade_time")
                out["timestamp_utc"] = data.get("timestamp")
                stamp = str(data.get("last_trade_time") or "")
                out["quote_date"] = stamp[:10] if len(stamp) >= 10 else None
        except Exception:
            continue
    if out["vix"] is not None and out["vix3m"] is not None:
        out["source"] = "Cboe delayed-quote CDN (_VIX.json / _VIX3M.json)"
        out["session_mode"] = mode
    return out


def build_regime_payload(metrics: dict, etf_rows: list[dict], vix: dict) -> dict:
    """The regime flags + the `_regime-intraday.json` payload.

    The payload is FLAT (`_schema`, then the eight regime keys at the top level) — that is
    the shape `screen.py::assert_regime_schema` enforces and the shape every consumer
    reads. The nested `{"regime": {...}}` shape is the 2026-11-04 break and is rejected.
    """
    breadth_rows = [{
        "metric": "largecap_breadth",
        "breadth_pct_largecap": metrics["breadth"]["pct_above_sma_20"],
    }, {
        "metric": "index_above_sma_summary",
        "pct_above_sma_20": metrics["index_etfs"]["n_above_sma_20"] / max(metrics["index_etfs"].get("n_etf", 5), 1),
    }]
    for r in etf_rows:
        breadth_rows.append({
            "metric": "index_atr_extension",
            "ticker": r.get("ticker"),       # the breadth SQL emits `ticker`
            "close": r.get("close"),
            "sma_20": r.get("sma_20"),
            "sma_50": r.get("sma_50"),
            "atr_14": r.get("atr_14"),
            "atr_252d_avg": r.get("atr_252d_avg"),
            "extension_pct": r.get("extension_pct"),
        })

    regime = compute_regime(breadth_rows, vix.get("vix"), vix.get("vix3m"))
    regime["atr_extensions"] = {
        sym: {"extension_pct": round(float(ext.get("extension_pct", 0)), 2)}
        for sym, ext in regime["atr_extensions"].items()
    }

    # GUARD: a regime flag computed over an empty collection is not a flag. If the five
    # ETF rows are present, the extension map MUST be populated.
    if etf_rows and not regime["atr_extensions"]:
        raise DataGuardError(
            "atr_extensions is EMPTY while the five index-ETF rows are present — "
            "the index identifier key does not match what the SQL emits "
            "(it is `ticker`, not `symbol`); late_cycle could never fire"
        )

    payload = {
        "_schema": 2,
        "_note": "cron #10 intraday breadth snapshot — flat regime schema, see SKILL.md §3.5",
        "size_cut_pct": regime["size_cut_pct"],
        "uncertainty": regime["uncertainty"],
        "late_cycle": regime["late_cycle"],
        "breadth_pct_spx": regime["breadth_pct_spx"],
        "index_below_20sma": regime["index_below_20sma"],
        "vix": regime["vix"],
        "vix3m": regime["vix3m"],
        "atr_extensions": regime["atr_extensions"],
        "_vix_source": vix.get("source"),
        "_vix_quote_time_et": vix.get("quote_time_et"),
        "_vix_session_mode": vix.get("session_mode"),
        "_data_date": metrics["data_date"],
    }
    return payload


# --------------------------------------------------------------------------------------
# the metric assembly
# --------------------------------------------------------------------------------------
def build_metrics(bridge: Bridge, end_date: str, lookback_days: int, ad_sessions: int) -> dict:
    start_date = (datetime.strptime(end_date, "%Y-%m-%d").date() - timedelta(days=lookback_days)).isoformat()

    breadth_rows = bridge.query_paged(
        SQL_BREADTH_SERIES,
        end_date=end_date, start_date=start_date, mc_floor=MARKET_CAP_FLOOR,
    )
    index_rows = bridge.query_paged(
        SQL_INDEX_SERIES, end_date=end_date, start_date=start_date,
    )
    if not breadth_rows:
        raise DataGuardError("the breadth series came back empty")
    if not index_rows:
        raise DataGuardError("the index-ETF series came back empty")

    sessions = [r["date"] for r in breadth_rows]
    data_date = sessions[-1]

    # the A/D window: the last `ad_sessions` sessions of the breadth series, plus one extra
    # at the front so the LAG() has a prior close for the first published session.
    if len(sessions) < ad_sessions + 1:
        raise DataGuardError(f"only {len(sessions)} sessions available, need {ad_sessions + 1}")
    ad_window = sessions[-(ad_sessions + 1):]
    ad_rows = bridge.query_paged(
        SQL_AD_SERIES,
        end_date=ad_window[-1], start_date=ad_window[0], mc_floor=MARKET_CAP_FLOOR,
    )
    ad_by_date = {r["date"]: r for r in ad_rows}

    idx_by_date = {r["date"]: r for r in index_rows}

    # ---- the level series, joined -------------------------------------------------
    series = []
    for r in breadth_rows:
        d = r["date"]
        ir = idx_by_date.get(d)
        n_etf = int(ir["n_etf"]) if ir else 0
        n20 = int(ir["n_above_sma_20"]) if ir else 0
        idx_pct = (n20 / n_etf * 100.0) if n_etf else None
        div = None if idx_pct is None else round(float(r["pct_above_sma_20"]) - idx_pct, 2)
        ad = ad_by_date.get(d)
        series.append({
            "date": d,
            "n_lc": int(r["n_lc"]),
            "pct_above_sma_20": round(float(r["pct_above_sma_20"]), 2),
            "pct_above_sma_50": round(float(r["pct_above_sma_50"]), 2),
            "n_etf_above_sma_20": n20,
            "n_etf_above_sma_50": int(ir["n_above_sma_50"]) if ir else 0,
            "n_etf": n_etf,
            "breadth_divergence_pp": div,
            "advancing": int(ad["advancing"]) if ad else None,
            "declining": int(ad["declining"]) if ad else None,
            "unchanged": int(ad["unchanged"]) if ad else None,
        })

    # ---- the ADL ------------------------------------------------------------------
    ad_series = [s for s in series if s["advancing"] is not None]
    if len(ad_series) < AD_PUBLISH_WINDOW:
        raise DataGuardError(
            f"only {len(ad_series)} advance/decline sessions, need {AD_PUBLISH_WINDOW}"
        )
    cum = 0.0
    cum_by_date: dict[str, float] = {}
    for s in ad_series:
        cum += s["advancing"] - s["declining"]
        cum_by_date[s["date"]] = cum
    for s in series:
        s["ad_net"] = None if s["advancing"] is None else s["advancing"] - s["declining"]
        s["adl_cum"] = cum_by_date.get(s["date"])

    # ---- percentiles --------------------------------------------------------------
    pop20 = [s["pct_above_sma_20"] for s in series]
    pop50 = [s["pct_above_sma_50"] for s in series]
    pop_div = [s["breadth_divergence_pp"] for s in series if s["breadth_divergence_pp"] is not None]
    pop_etf = [float(s["n_etf_above_sma_20"]) for s in series]

    for i, s in enumerate(series):
        # expanding percentile: vs every session from the start of the window to here
        s["breadth_pctile_1y"] = percentile_rank(s["pct_above_sma_20"], pop20[: i + 1])
        if s["breadth_divergence_pp"] is not None:
            div_pop = [x["breadth_divergence_pp"] for x in series[: i + 1]
                       if x["breadth_divergence_pp"] is not None]
            s["divergence_pctile_1y"] = percentile_rank(s["breadth_divergence_pp"], div_pop)
        else:
            s["divergence_pctile_1y"] = None

    # rolling 10-session ADL slope (net advances per session) at every session.
    # A slope needs a FULL window — a 2-point slope off the start of the series is noise,
    # so it is published as blank until there are 10 sessions behind it.
    for i, s in enumerate(series):
        if s["adl_cum"] is None:
            s["adl_slope_10d"] = None
            continue
        window = [cum_by_date[x["date"]] for x in series[max(0, i - AD_PUBLISH_WINDOW + 1): i + 1]
                  if x["date"] in cum_by_date]
        s["adl_slope_10d"] = (round(ols_slope(window), 2)
                              if len(window) >= AD_PUBLISH_WINDOW else None)

    cur = series[-1]
    ad_pub = ad_series[-AD_PUBLISH_WINDOW:]
    adl_points = [cum_by_date[s["date"]] for s in ad_pub]
    adv_sum = sum(s["advancing"] for s in ad_pub)
    dec_sum = sum(s["declining"] for s in ad_pub)
    net_sum = adv_sum - dec_sum

    # ---- the index ETFs' own positioning ---------------------------------------------
    etf_start = (datetime.strptime(data_date, "%Y-%m-%d").date() - timedelta(days=430)).isoformat()
    etf_rows = bridge.query(SQL_ETF_EXTENSION.format(start_date=etf_start, end_date=data_date))
    if len(etf_rows) != len(INDEX_ETFS):
        raise DataGuardError(
            f"expected {len(INDEX_ETFS)} index-ETF rows for {data_date}, got {len(etf_rows)}"
        )

    # ---- the headline metrics ------------------------------------------------------
    divergence_hist = [
        {"date": s["date"], "pp": s["breadth_divergence_pp"]}
        for s in series[-5:]
    ]

    metrics = {
        "_contract": CONTRACT,
        "_schema": 1,
        "generated_at_et": datetime.now().astimezone().isoformat(timespec="seconds"),
        "data_date": data_date,
        "history": {
            "sessions": len(series),
            "start": sessions[0],
            "end": data_date,
            "lookback_days": lookback_days,
        },
        "universe": {
            "filter": "NYSE/NASDAQ/AMEX, market cap > $10B",
            "n": cur["n_lc"],
            "market_cap_floor": MARKET_CAP_FLOOR,
        },
        "breadth": {
            "pct_above_sma_20": cur["pct_above_sma_20"],
            "pctile_1y": cur["breadth_pctile_1y"],
            "band": pctile_band(cur["breadth_pctile_1y"]),
            "pct_above_sma_50": cur["pct_above_sma_50"],
            "pctile_1y_50dma": percentile_rank(cur["pct_above_sma_50"], pop50),
            "band_50dma": pctile_band(percentile_rank(cur["pct_above_sma_50"], pop50)),
        },
        "index_etfs": {
            "symbols": list(INDEX_ETFS),
            "n_etf": cur["n_etf"],
            "n_above_sma_20": cur["n_etf_above_sma_20"],
            "n_above_sma_50": cur["n_etf_above_sma_50"],
            "pct_above_sma_20": round(cur["n_etf_above_sma_20"] / cur["n_etf"] * 100, 2) if cur["n_etf"] else None,
            "pctile_1y": percentile_rank(float(cur["n_etf_above_sma_20"]), pop_etf),
        },
        "divergence": {
            "pp": cur["breadth_divergence_pp"],
            "band": divergence_band(cur["breadth_divergence_pp"]),
            "pctile_1y": percentile_rank(cur["breadth_divergence_pp"], pop_div),
            "history_5d": divergence_hist,
        },
        "advance_decline": {
            "advancing": cur["advancing"],
            "declining": cur["declining"],
            "unchanged": cur["unchanged"],
            "ad_ratio": round(cur["advancing"] / cur["declining"], 3) if cur["declining"] else None,
            "ad_net": cur["ad_net"],
            "ad_net_10d": net_sum,
            "ad_ratio_10d": round(adv_sum / dec_sum, 3) if dec_sum else None,
            "adl_slope_10d": round(ols_slope(adl_points), 2),
            "adl_since_start": round(cum, 1),
            "adl_base_date": ad_series[0]["date"],
            "adl_window_start": ad_pub[0]["date"],
            "adl_window_end": ad_pub[-1]["date"],
        },
        "series": series,
    }

    # ---- the regime + the live volatility pair --------------------------------------
    vix = fetch_vix_pair()
    metrics["vix"] = vix
    metrics["regime"] = build_regime_payload(metrics, etf_rows, vix)
    metrics["etf_positioning"] = [
        {
            "ticker": r.get("ticker"), "close": r.get("close"),
            "sma_20": r.get("sma_20"), "sma_50": r.get("sma_50"),
            "atr_14": r.get("atr_14"), "atr_252d_avg": r.get("atr_252d_avg"),
            "extension_pct": round(float(r["extension_pct"]), 2) if r.get("extension_pct") is not None else None,
            "atr_extension_multiple": round(float(r["atr_extension_multiple"]), 2)
            if r.get("atr_extension_multiple") is not None else None,
            "above_sma_20": (r.get("close") is not None and r.get("sma_20") is not None
                             and float(r["close"]) > float(r["sma_20"])),
            "above_sma_50": (r.get("close") is not None and r.get("sma_50") is not None
                             and float(r["close"]) > float(r["sma_50"])),
        }
        for r in etf_rows
    ]

    # ---- guards ---------------------------------------------------------------------
    if not metrics["advance_decline"]["advancing"] and not metrics["advance_decline"]["declining"]:
        raise DataGuardError("the advance/decline tally is empty — refusing to publish a proxy as if it were a tally")
    if metrics["universe"]["n"] <= 0:
        raise DataGuardError("the universe is empty")
    if not (0.0 <= metrics["breadth"]["pctile_1y"] <= 100.0):
        raise DataGuardError(f"breadth percentile out of range: {metrics['breadth']['pctile_1y']}")
    if len(metrics["divergence"]["history_5d"]) != 5:
        raise DataGuardError("the divergence history is not five sessions")
    return metrics


def write_outputs(metrics: dict, out_dir: Path, csv_rows: int) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    series = metrics["series"]
    rows = series[-csv_rows:] if csv_rows and csv_rows < len(series) else series
    data_date = metrics["data_date"]

    csv_path = out_dir / "breadth-snapshot.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(CSV_COLUMNS)
        for s in rows:
            w.writerow([
                s["date"], s["n_lc"], s["pct_above_sma_20"], s["pct_above_sma_50"],
                s["n_etf_above_sma_20"], s["n_etf_above_sma_50"], s["breadth_divergence_pp"],
                s["advancing"] if s["advancing"] is not None else "",
                s["declining"] if s["declining"] is not None else "",
                s["unchanged"] if s["unchanged"] is not None else "",
                s["ad_net"] if s["ad_net"] is not None else "",
                s["adl_cum"] if s["adl_cum"] is not None else "",
                s.get("adl_slope_10d", ""),
                s["breadth_pctile_1y"],
                s["divergence_pctile_1y"] if s["divergence_pctile_1y"] is not None else "",
                "yes" if s["date"] == data_date else "no",
            ])

    json_path = out_dir / "breadth-snapshot.json"
    payload = {k: v for k, v in metrics.items() if k != "series"}
    payload["series_csv"] = csv_path.name
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=False)
        fh.write("\n")

    # the regime sidecar — cron #10 owns `_regime-intraday.json` (cron #09 owns `_regime.json`)
    regime_path = out_dir / "_regime-intraday.json"
    with open(regime_path, "w", encoding="utf-8") as fh:
        json.dump(metrics["regime"], fh, indent=2, sort_keys=False)
        fh.write("\n")

    return {"csv": str(csv_path), "json": str(json_path), "regime": str(regime_path), "rows": len(rows)}


def _fmt_date_long(d: str) -> str:
    try:
        return datetime.strptime(d, "%Y-%m-%d").strftime("%A, %d %B %Y")
    except Exception:
        return d


def render_markdown(metrics: dict, live: dict | None = None) -> str:
    """Render the contract-shaped markdown from the settled metrics.

    The SETTLED layer is rendered complete and correct — it is the layer this script
    owns. The LIVE layer (the fire time, the live tape, the sector rotation, the events,
    the flags and the method notes) is supplied by the Agent in `live`; any key it does
    NOT supply is rendered as a `<!-- FILL: ... -->` marker, and the checker REJECTS an
    artifact that still carries one. A stub cannot ship.

    Keys accepted in `live`:
        fire_time_et, live_date, vix_quote_time, vix_pair, tape_block, volatility_block,
        events_block, flags_block, method_block, headline
    """
    live = live or {}
    b = metrics["breadth"]
    d = metrics["divergence"]
    a = metrics["advance_decline"]
    ix = metrics["index_etfs"]
    u = metrics["universe"]
    r = metrics["regime"]
    hist = metrics["history"]
    data_date = metrics["data_date"]
    series = metrics["series"]
    etfs = metrics.get("etf_positioning", [])
    n_lc = u["n"]
    above20 = round(b["pct_above_sma_20"] / 100 * n_lc)
    above50 = round(b["pct_above_sma_50"] / 100 * n_lc)

    def fill(key: str, fallback: str = "") -> str:
        val = live.get(key)
        if val is None or str(val).strip() == "":
            return f"<!-- FILL: {key} -->"
        return str(val)

    fm = [
        "---",
        "artifact: breadth-snapshot",
        f"contract: {CONTRACT}",
        'cron: "#10 stock-screener-breadth-snapshot"',
        f"fire_time_et: \"{fill('fire_time_et')}\"",
        f"data_date: \"{data_date}\"",
        f"live_date: \"{fill('live_date')}\"",
        f"breadth_universe: \"{u['filter']}, {n_lc} names\"",
        f"vix_quote_time: \"{fill('vix_quote_time')}\"",
        f"vix_pair: \"{fill('vix_pair')}\"",
        'cross_reference: "end-of-day counterpart: daily-screens/<date>/breadth.md (cron #09, 18:30 ET)"',
        f"size_cut_pct: {r['size_cut_pct']}",
        f"uncertainty: {str(r['uncertainty']).lower()}",
        f"late_cycle: {str(r['late_cycle']).lower()}",
        "---",
        "",
    ]

    head = [
        f"_contract: {CONTRACT} · data_date {data_date} · universe {n_lc} names · "
        f"breadth {b['pct_above_sma_20']:.2f}% (pctile {b['pctile_1y']} · {b['band']}) · "
        f"divergence {d['pp']:+.2f} pp ({d['band']}) · "
        f"AD {a['advancing']}/{a['declining']}/{a['unchanged']}_",
        "",
        f"# Breadth & Regime Snapshot — {_fmt_date_long(str(live.get('live_date') or data_date))} "
        "(intraday, cron #10)",
        "",
        fill("banner", "<!-- FILL: banner -->"),
        "",
        "## TL;DR",
        "",
        fill("tldr", "<!-- FILL: tldr -->"),
        "",
        "## Breadth — " + data_date + " settled session (shibui)",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Universe | {u['filter']} |",
        f"| Names in universe | {n_lc} |",
        f"| Above 20-DMA | {above20} ({b['pct_above_sma_20']:.2f}%) |",
        f"| Below 20-DMA | {n_lc - above20} ({100 - b['pct_above_sma_20']:.2f}%) |",
        f"| Above 50-DMA | {above50} ({b['pct_above_sma_50']:.2f}%) |",
        f"| Index ETFs above their own 20-DMA | {ix['n_above_sma_20']} of {ix.get('n_etf', 5)} "
        f"({ix['pct_above_sma_20']:.1f}%) |",
        f"| Index ETFs above their own 50-DMA | {ix['n_above_sma_50']} of {ix.get('n_etf', 5)} "
        f"({ix['n_above_sma_50'] / max(ix.get('n_etf', 5), 1) * 100:.1f}%) |",
        f"| Advance/decline — settled session | {a['advancing']} advancing / {a['declining']} "
        f"declining / {a['unchanged']} unchanged (A/D ratio {a['ad_ratio']}) |",
        "",
        f"The universe is **not frozen** — the market-cap floor is applied to the latest "
        f"`valuation` row, so the count moves as those rows refresh. Today's universe: "
        f"**{n_lc} names**.",
        "",
        "## Participation — advance/decline and the 10-session ADL",
        "",
        "| Date | Advancing | Declining | Unchanged | Net | ADL (cumulative) | ADL slope (10d) |",
        "|---|---|---|---|---|---|---|",
    ]
    for s in series[-AD_PUBLISH_WINDOW:]:
        head.append(
            f"| {s['date']} | {s['advancing']} | {s['declining']} | {s['unchanged']} | "
            f"{s['ad_net']:+d} | {s['adl_cum']:.0f} | "
            f"{s.get('adl_slope_10d') if s.get('adl_slope_10d') is not None else '—'} |"
        )
    head += [
        "",
        f"**A/D ratio {a['ad_ratio']} today** ({a['advancing']} advancing / {a['declining']} "
        f"declining). Over the last 10 sessions the net advances total **{a['ad_net_10d']:+d}** "
        f"and the ADL slope is **{a['adl_slope_10d']:+.2f} net advances per session** "
        f"(10-session A/D ratio {a['ad_ratio_10d']}). The ADL is cumulative from "
        f"{a.get('adl_base_date') or a['adl_window_start']}, so it is a LEVEL; the slope is the "
        f"rate.",
        "",
        "## Breadth percentile — where today's level sits in its own history",
        "",
        f"Percentiles are against the trailing 1-year distribution of the same series "
        f"({hist['sessions']} sessions, {hist['start']} → {hist['end']}). "
        f"A level without a percentile is a number without a context.",
        "",
        "| Metric | Value | Percentile | Band |",
        "|---|---|---|---|",
        f"| `breadth_pct` | {b['pct_above_sma_20']:.2f}% | — | — |",
        f"| `breadth_pctile_1y` | {b['pctile_1y']} | — | {b['band']} |",
        f"| `breadth_pct_50dma` | {b['pct_above_sma_50']:.2f}% | — | — |",
        f"| `breadth_pctile_1y_50dma` | {b['pctile_1y_50dma']} | — | {b['band_50dma']} |",
        f"| `index_etfs_above_20dma` | {ix['n_above_sma_20']} of {ix.get('n_etf', 5)} | "
        f"{ix['pctile_1y']} | {pctile_band(ix['pctile_1y'])} |",
        "",
        "## Breadth divergence — broad market versus index ETFs",
        "",
        f"| Metric | Value | Band | 1-year percentile |",
        "|---|---|---|---|",
        f"| `breadth_divergence` | {d['pp']:+.2f} pp | {d['band']} | {d['pctile_1y']} |",
        "",
        "`breadth_divergence` = the large-cap universe's share above its own 20-DMA minus the "
        "index ETFs' share above their own 20-DMA. **BROAD** means the average large cap is "
        "materially healthier than the index; **NARROW** means the index is healthier than the "
        "average large cap — the cap-weighted index is carried by its biggest names while the "
        "average stock is not participating; **MATCHED** means they agree.",
        "",
        "| Date | Divergence (pp) |",
        "|---|---|",
    ]
    for h in d["history_5d"]:
        head.append(f"| {h['date']} | {h['pp']:+.2f} |")

    head += [
        "",
        "## Index positioning — distance from the 50-DMA",
        "",
        "| Symbol | Close | 20-DMA | 50-DMA | Distance from 50-DMA | ATR multiple |",
        "|---|---|---|---|---|---|",
    ]
    for e in etfs:
        def _r(v):
            try:
                return f"{float(v):,.2f}"
            except (TypeError, ValueError):
                return "—"
        head.append(
            f"| {e['ticker']} | {_r(e['close'])} | {_r(e['sma_20'])} | {_r(e['sma_50'])} | "
            f"{e['extension_pct']:+.2f}% | {e['atr_extension_multiple']} |"
        )

    head += [
        "",
        "## Live tape — " + fill("live_date"),
        "",
        fill("tape_block", "<!-- FILL: tape_block -->"),
        "",
        "## Volatility — single pair, live",
        "",
        fill("volatility_block", "<!-- FILL: volatility_block -->"),
        "",
        "## Regime",
        "",
        "| Flag | Value | Rule |",
        "|---|---|---|",
        f"| `size_cut_pct` | {r['size_cut_pct']} | size cut triggers only when the index is "
        f"below its 20-DMA **and** breadth < 40% |",
        f"| `uncertainty` | {str(r['uncertainty']).lower()} | VIX/VIX3M > 1.0 |",
        f"| `late_cycle` | {str(r['late_cycle']).lower()} | any index ETF more than 6% above its "
        f"own 50-DMA |",
        f"| `index_below_20sma` | {str(r['index_below_20sma']).lower()} | fewer than 3 of the 5 "
        f"index ETFs above their own 20-DMA |",
        "",
        "## Flags",
        "",
        fill("flags_block", "<!-- FILL: flags_block -->"),
        "",
        "## Method, source health & caveats",
        "",
        fill("method_block", "<!-- FILL: method_block -->"),
        "",
    ]
    return "\n".join(fm) + "\n".join(head)


def summarise(metrics: dict) -> str:
    b = metrics["breadth"]
    d = metrics["divergence"]
    a = metrics["advance_decline"]
    ix = metrics["index_etfs"]
    r = metrics["regime"]
    v = metrics.get("vix", {})
    lines = [
        f"data_date: {metrics['data_date']}  ({metrics['history']['sessions']} sessions "
        f"{metrics['history']['start']} → {metrics['history']['end']})",
        f"universe: {metrics['universe']['n']} names — {metrics['universe']['filter']}",
        f"breadth: {b['pct_above_sma_20']:.2f}% above 20-DMA · pctile_1y {b['pctile_1y']} · {b['band']}",
        f"50-DMA split: {b['pct_above_sma_50']:.2f}% · pctile_1y {b['pctile_1y_50dma']} · {b['band_50dma']}",
        f"index ETFs: {ix['n_above_sma_20']} of {len(ix['symbols'])} above their own 20-DMA "
        f"· pctile_1y {ix['pctile_1y']}",
        f"divergence: {d['pp']:+.2f} pp · {d['band']} · pctile_1y {d['pctile_1y']}",
        f"advance/decline: {a['advancing']} advancing / {a['declining']} declining / "
        f"{a['unchanged']} unchanged · ratio {a['ad_ratio']} · net {a['ad_net']:+d}",
        f"10-session: net {a['ad_net_10d']:+d} · ADL slope {a['adl_slope_10d']:+.2f} net/session "
        f"· ratio {a['ad_ratio_10d']}",
        f"regime: size_cut_pct={r['size_cut_pct']} · uncertainty={r['uncertainty']} · "
        f"late_cycle={r['late_cycle']} · index_below_20sma={r['index_below_20sma']}",
        f"vix: {v.get('vix')} / {v.get('vix3m')} @ {v.get('quote_time_et')} ({v.get('source')})",
        f"atr_extensions: {json.dumps(r['atr_extensions'])}",
    ]
    for h in d["history_5d"]:
        lines.append(f"  divergence {h['date']}: {h['pp']:+.2f} pp")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="cron #10 breadth snapshot — settled metrics")
    ap.add_argument("--date", default=date.today().isoformat(), help="session to describe (YYYY-MM-DD)")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--bridge", default="/workspace/mcp_bridge.py")
    ap.add_argument("--lookback-days", type=int, default=PCTILE_WINDOW_DAYS)
    ap.add_argument("--ad-sessions", type=int, default=AD_SESSION_WINDOW)
    ap.add_argument("--csv-rows", type=int, default=CSV_TRAILING_ROWS)
    ap.add_argument("--print-only", action="store_true", help="compute and print, write nothing")
    ap.add_argument("--render-md", help="write the contract-shaped markdown to this path")
    ap.add_argument("--live-json", help="JSON file with the live-layer values for the renderer")
    args = ap.parse_args(argv)

    if not os.path.exists(args.bridge):
        print(f"breadth_metrics: bridge not found at {args.bridge}", file=sys.stderr)
        return 1

    bridge = Bridge(args.bridge)
    try:
        metrics = build_metrics(bridge, args.date, args.lookback_days, args.ad_sessions)
    except DataGuardError as exc:
        print(f"breadth_metrics: DATA GUARD FAILED — {exc}", file=sys.stderr)
        return 1

    print(summarise(metrics))
    if args.print_only:
        return 0

    out = write_outputs(metrics, Path(args.out_dir), args.csv_rows)
    print(f"wrote: {out['csv']} ({out['rows']} rows)")
    print(f"wrote: {out['json']}")
    print(f"wrote: {out['regime']}")

    if args.render_md:
        live = {}
        if args.live_json:
            live = json.load(open(args.live_json, encoding="utf-8"))
        md = render_markdown(metrics, live)
        Path(args.render_md).write_text(md, encoding="utf-8")
        missing = [k for k, v in live.items() if v is None]
        print(f"wrote: {args.render_md}")
        if "<!-- FILL" in md:
            print("NOTE: the rendered markdown still carries FILL markers — the live layer is "
                  "not complete; the checker rejects an artifact that still has one")
        else:
            print("live layer: complete (no FILL markers)")

    print(f"_contract: {CONTRACT} · data_date {metrics['data_date']} · "
          f"breadth {metrics['breadth']['pct_above_sma_20']:.2f}% "
          f"(pctile {metrics['breadth']['pctile_1y']}) · "
          f"divergence {metrics['divergence']['pp']:+.2f} pp "
          f"({metrics['divergence']['band']}) · "
          f"AD {metrics['advance_decline']['advancing']}/{metrics['advance_decline']['declining']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
