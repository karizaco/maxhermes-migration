#!/usr/bin/env python3
"""Cron #09 daily-sweep engines — the FRESH book, the extension metrics, and the
valuation/quality overlay.

CAPABILITY MARKER: DAILY_SWEEP_ENGINES_V1

WHY THIS EXISTS
---------------
shibui is T+1: at the 18:30 ET fire its newest settled session is the PREVIOUS
session.  The 2026-11-09 run published a book whose every screen metric described
2026-11-06 while the artifact was read as "today's screen".  Twenty-five of the
sixty-eight names that met the same 4%-breakout + 2x-volume gate on the 2026-11-09
settled bar were absent from the book entirely.

This engine computes the price/volume TRIGGER branches on the cron day's own
settled bar (TradingView's scanner), so the artifact describes the session the
trader just saw.  It does NOT replace the multi-session context branches
(5-day gainers/losers, 14-day velocity, the coil) — those stay on shibui and stay
labelled T+1, for a measured reason (see PERF_W_BASIS below).

MEASURED CALIBRATION (2026-11-09, 11 names, shibui history + TV settled bar)
--------------------------------------------------------------------------
* ``Perf.W`` is a SIX-session move, not five.  Correlation against a
  5-session move r=0.924 (mean abs error 6.85 pp); against a 6-session move
  r=0.997 (mean abs error 1.31 pp).  A 5-session gate copied onto ``Perf.W``
  would silently shift the parabolic books, so it is NOT done.
* ``average_volume_10d_calc`` is EXACTLY the mean of the last ten sessions
  INCLUDING today (bias 0.00% against a hand-computed reference on 11 names).
  The prior-nine-session baseline is therefore reconstructed exactly as
  ``(10 * avg10 - volume_today) / 9`` — no extra data source needed.
* TradingView's settled ``close`` equals the official 16:00 ET print (verified
  15/15 against Nasdaq's ``secondaryData`` on 2026-11-04) and the day-alignment
  assertion passes on every run.

SUB-COMMANDS
------------
``tv-sweep``  the fresh book + per-symbol extension metrics (TradingView only)
``overlay``   the valuation/quality overlay + the up-day streak (shibui, 1 call)
``selftest``  offline checks of every derived quantity

Every subcommand writes JSON and exits non-zero on a failed assertion.  A
truncated scan is a FAILURE, never a shorter book.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

CAPABILITY_MARKER = "DAILY_SWEEP_ENGINES_V1"
TV_SCAN_URL = "https://scanner.tradingview.com/america/scan"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"

# --- Published gates. Every one of these is published in the artifact. --------
# The fresh branches mirror the canonical shibui gates where the data allows an
# exact mirror, and state plainly where the gate is a documented VARIANT.
GATES = {
    # Bonde 4% breakout. shibui's gate is "volume > prev_volume" (the PRIOR
    # session). TradingView publishes no prior-session volume, so the fresh
    # gate is "volume > the prior-nine-session mean" — a STRICTER expansion
    # test, published as its own gate, not a silent copy.
    "A_tv_breakout_4pct": {
        "min_change_pct": 4.0,
        "min_close": 3.0,
        "volume_vs": "prior9_mean",
        "volume_operator": ">",
        "min_avg_volume_10d": 100_000,
    },
    # Stockbee EP9M — exact mirror: 8.9M SHARES of session volume.
    "B_tv_ep9m": {
        "min_volume_shares": 8_900_000,
        "min_close": 3.0,
        "min_avg_volume_10d": 100_000,
    },
    # Qullamaggi 10% GAP (the canonical gate is open/prev_close >= 1.10) plus a
    # $50M average-dollar-volume floor. The 20-day ADV is not published by the
    # scanner, so the floor is measured on the prior-nine-session mean dollar
    # volume and is labelled as such.
    "D_tv_gap_10pct": {
        "min_gap_pct": 10.0,
        "min_adv_dollar_prior9": 50_000_000,
        "min_close": 3.0,
    },
    # The volume-breakout cross-check that already existed in the suite
    # (momentum + volume), unchanged.
    "TV_volume_breakout": {
        "min_change_pct": 3.0,
        "min_relative_volume_10d": 1.5,
    },
}

# --- The extension rules (labels a name, never drops it) --------------------
EXTENSION_RULES = {
    "atr_pct": {"op": ">", "value": 5.0, "label": "ATR% > 5.0 (a normal large cap is 1.5-3%)"},
    "rsi": {"op": ">", "value": 75.0, "label": "RSI > 75 (overbought)"},
    "pct_above_sma20": {"op": ">", "value": 15.0, "label": "> 15% above its 20-DMA"},
    "up_days_streak": {"op": ">=", "value": 3, "label": "3+ consecutive up sessions"},
}

# --- The valuation / quality overlay ---------------------------------------
# A NULL is a RISK FLAG, never a pass. The overlay exists because the suite
# never joined a table it already pays for: shibui's
# fundamentals_derived_daily carries trailing_pe, operating_pe, ev_ebit,
# price_to_sales, free_cash_flow_yield, trailing_revenue_peg and
# earnings_quality_flags, and the CANSLIM branch ignored every one of them.
QUALITY_RULES = {
    "trailing_pe": {"op": ">", "value": 50.0, "label": "trailing P/E > 50"},
    "operating_pe": {"op": ">", "value": 40.0, "label": "operating P/E > 40"},
    # PEG > 3 (not > 2): at 2 the rule fired on AAPL (PEG 2.4) and on 168
    # names, and it did NOT catch KRMN (PEG 1.84). A rule that misses the case
    # it was written for and fires on the good names is not a rule.
    "trailing_revenue_peg": {"op": ">", "value": 3.0, "label": "PEG > 3"},
    "free_cash_flow_yield": {"op": "<", "value": 0.0, "label": "negative free cash flow"},
    "debt_to_equity": {"op": ">", "value": 1.5, "label": "debt/equity > 1.5"},
}


class EngineError(RuntimeError):
    """A failed assertion. The run must fail loudly, never publish a short book."""


# ---------------------------------------------------------------- utilities


def _num(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(float(value)) else None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _f(value, default=None):
    out = _num(value)
    return default if out is None else out


def tv_scan(filters, columns, rng=(0, 2000), sort=None):
    """One POST to the TradingView scanner. The payload key is `filter`
    (singular) and the dialect is left/operation/right — the
    field/operator/value dialect is rejected with HTTP 400."""
    body = {
        "filter": filters,
        "options": {"lang": "en"},
        "symbols": {"query": {"types": []}, "tickers": []},
        "columns": columns,
        "sort": sort or {"sortBy": "description", "sortOrder": "asc"},
        "range": list(rng),
    }
    req = urllib.request.Request(
        TV_SCAN_URL,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode())


def _flt(left, operation, right):
    return {"left": left, "operation": operation, "right": right}


def _rows(payload, columns):
    """Zip the response against the column list WE sent. The response has no
    `columns` key — the values arrive in request order."""
    out = []
    for item in payload.get("data", []):
        row = dict(zip(columns, item.get("d", [])))
        row["_ticker"] = str(item.get("s", "")).split(":")[-1]
        out.append(row)
    return out


def _bridge_call(bridge, server, tool, args):
    path = Path("/workspace/scratch/_daily_sweep_call.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(args), encoding="utf-8")
    proc = subprocess.run(
        ["python3", str(bridge), server, tool, str(path)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise EngineError(f"bridge call failed ({server}/{tool}): {proc.stdout[:400]}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise EngineError(f"bridge returned non-JSON ({server}/{tool}): {proc.stdout[:200]}") from exc


# ------------------------------------------------------------- the TV engine

TV_COLUMNS = [
    "description", "close", "open", "high", "low", "change", "volume",
    "average_volume_10d_calc", "relative_volume_10d_calc", "market_cap_basic",
    "exchange", "sector", "SMA20", "SMA50", "SMA150", "SMA200", "ATR", "RSI",
    "Perf.W", "Perf.1M", "Perf.3M", "Perf.6M", "Perf.YTD",
    "price_52_week_high", "price_52_week_low", "Volatility.D", "Volatility.W",
]


def fetch_universe(min_cap, page=2000):
    """The whole pre-filtered universe, paged with a TOTAL order.

    A scan whose `range` is smaller than `totalCount` is a silent truncation —
    the exact defect class this suite keeps guarding against — so the pages are
    walked to exhaustion and the row count is asserted against totalCount."""
    filters = [
        _flt("exchange", "in_range", ["NYSE", "NASDAQ", "AMEX"]),
        _flt("type", "in_range", ["stock", "dr"]),
        _flt("market_cap_basic", "greater", min_cap),
    ]
    rows, seen, total = [], set(), None
    offset = 0
    while True:
        payload = tv_scan(filters, TV_COLUMNS, rng=(offset, offset + page),
                          sort={"sortBy": "description", "sortOrder": "asc"})
        total = payload.get("totalCount")
        chunk = _rows(payload, TV_COLUMNS)
        if not chunk:
            break
        for row in chunk:
            ticker = row["_ticker"]
            if ticker in seen:
                continue
            seen.add(ticker)
            rows.append(row)
        offset += page
        if total is not None and offset >= total:
            break
        if len(chunk) < page:
            break
    if total is None:
        raise EngineError("scanner returned no totalCount — the universe cannot be proven complete")
    if len(rows) != total:
        raise EngineError(
            f"TRUNCATED SCAN: fetched {len(rows)} rows against totalCount {total}. "
            "Refusing to publish a short book."
        )
    return rows, total


def derive(row):
    """Everything the fresh branches and the extension labels need."""
    close = _f(row.get("close"))
    change = _f(row.get("change"))
    volume = _f(row.get("volume"))
    avg10 = _f(row.get("average_volume_10d_calc"))
    out = {
        "symbol": row["_ticker"],
        "name": row.get("description"),
        "close": close,
        "change_pct": change,
        "volume": volume,
        "avg_volume_10d_calc": avg10,
        "relative_volume_10d_calc": _f(row.get("relative_volume_10d_calc")),
        "market_cap_basic": _f(row.get("market_cap_basic")),
        "exchange": row.get("exchange"),
        "sector": row.get("sector"),
        "sma20": _f(row.get("SMA20")),
        "sma50": _f(row.get("SMA50")),
        "sma150": _f(row.get("SMA150")),
        "sma200": _f(row.get("SMA200")),
        "atr": _f(row.get("ATR")),
        "rsi": _f(row.get("RSI")),
        "perf_w": _f(row.get("Perf.W")),
        "perf_1m": _f(row.get("Perf.1M")),
        "perf_3m": _f(row.get("Perf.3M")),
        "perf_6m": _f(row.get("Perf.6M")),
        "perf_ytd": _f(row.get("Perf.YTD")),
        "high_52w": _f(row.get("price_52_week_high")),
        "low_52w": _f(row.get("price_52_week_low")),
        "open": _f(row.get("open")),
        "high": _f(row.get("high")),
        "low": _f(row.get("low")),
    }
    # prev_close is derived from the settled close and the session's change.
    # `change` is in PERCENT units on this scanner (never a fraction).
    if close is not None and change is not None and change > -100:
        out["implied_prev_close"] = close / (1.0 + change / 100.0)
    else:
        out["implied_prev_close"] = None
    if out["open"] is not None and out["implied_prev_close"]:
        out["gap_pct"] = (out["open"] / out["implied_prev_close"] - 1.0) * 100.0
    else:
        out["gap_pct"] = None
    # The prior-NINE-session mean volume is reconstructed exactly from the
    # scanner's own arithmetic: avg10 == mean(last 10 sessions INCLUDING today).
    if avg10 is not None and volume is not None:
        out["prior9_avg_volume"] = (10.0 * avg10 - volume) / 9.0
        out["volume_expansion_ratio"] = (
            volume / out["prior9_avg_volume"] if out["prior9_avg_volume"] > 0 else None
        )
    else:
        out["prior9_avg_volume"] = None
        out["volume_expansion_ratio"] = None
    if close is not None:
        out["dollar_volume"] = close * volume if volume is not None else None
        out["adv_dollar_prior9"] = (
            close * out["prior9_avg_volume"] if out["prior9_avg_volume"] is not None else None
        )
        out["atr_pct"] = out["atr"] / close * 100.0 if out["atr"] is not None else None
        for key in ("sma20", "sma50", "sma150", "sma200"):
            ref = out[key]
            out[f"pct_above_{key}"] = (close / ref - 1.0) * 100.0 if ref else None
        if out["high_52w"]:
            out["pct_from_52w_high"] = (close / out["high_52w"] - 1.0) * 100.0
        else:
            out["pct_from_52w_high"] = None
    else:
        out["atr_pct"] = None
        for key in ("sma20", "sma50", "sma150", "sma200"):
            out[f"pct_above_{key}"] = None
        out["pct_from_52w_high"] = None
    return out


def branch_rows(name, rows):
    """Apply one published gate. Returns (passing_rows, rows_passing)."""
    gate = GATES[name]
    kept = []
    for row in rows:
        if name == "A_tv_breakout_4pct":
            if row["close"] is None or row["change_pct"] is None:
                continue
            if row["change_pct"] < gate["min_change_pct"] or row["close"] < gate["min_close"]:
                continue
            if (row["avg_volume_10d_calc"] or 0) < gate["min_avg_volume_10d"]:
                continue
            if row["volume_expansion_ratio"] is None or not row["volume_expansion_ratio"] > 1.0:
                continue
        elif name == "B_tv_ep9m":
            if row["volume"] is None or row["close"] is None:
                continue
            if row["volume"] < gate["min_volume_shares"] or row["close"] < gate["min_close"]:
                continue
            if (row["avg_volume_10d_calc"] or 0) < gate["min_avg_volume_10d"]:
                continue
        elif name == "D_tv_gap_10pct":
            if row["gap_pct"] is None or row["close"] is None:
                continue
            if row["gap_pct"] < gate["min_gap_pct"] or row["close"] < gate["min_close"]:
                continue
            if (row["adv_dollar_prior9"] or 0) < gate["min_adv_dollar_prior9"]:
                continue
        elif name == "TV_volume_breakout":
            if row["change_pct"] is None or row["relative_volume_10d_calc"] is None:
                continue
            if row["change_pct"] < gate["min_change_pct"]:
                continue
            if row["relative_volume_10d_calc"] < gate["min_relative_volume_10d"]:
                continue
        else:
            raise EngineError(f"unknown branch {name}")
        kept.append(row)
    return kept, len(kept)


def extension_labels(row, up_days_streak=None):
    """The extension verdict for one name: a LABEL with reasons, never a drop.

    The absolute thresholds are the published gates. `atr_pct_pctile` is the
    name's ATR percentile inside the SAME universe, because an absolute ATR
    threshold means different things at different market caps: measured
    2026-11-09, ATR% > 5 fires on 15.8% of the $10B+ names but on 36.0% of the
    $1-10B names, so the percentile is published next to the absolute hit.
    """
    reasons, fired = [], []
    for key, rule in EXTENSION_RULES.items():
        value = up_days_streak if key == "up_days_streak" else row.get(key)
        if value is None:
            continue
        hit = value > rule["value"] if rule["op"] == ">" else value >= rule["value"]
        if hit:
            fired.append(key)
            reasons.append(f"{rule['label']} ({value:.2f})" if isinstance(value, float) else f"{rule['label']} ({value})")
    return {
        "extended": bool(fired),
        "extension_reasons": reasons,
        "extension_hits": fired,
        "extension_count": len(fired),
        "atr_pct_pctile": row.get("atr_pct_pctile"),
        "atr_pct_pctile_lc": row.get("atr_pct_pctile_lc"),
        "pct_above_sma20_pctile_lc": row.get("pct_above_sma20_pctile_lc"),
    }


def _percentiles(rows, key, suffix="", against=None):
    """The percentile of `key` for every row that has it.

    `against` is the population the rank is measured IN; `rows` is who
    RECEIVES the value. The $10B+ percentiles are published for every name,
    not only for the large caps themselves — a $2B name still needs to know
    where its volatility sits among the large caps."""
    population = against if against is not None else rows
    values = [r[key] for r in population if r.get(key) is not None]
    if not values:
        return
    values.sort()

    def rank(value):
        # bisect_right on the sorted list: the share of the population at or
        # below this value, in 0..100.
        lo, hi = 0, len(values)
        while lo < hi:
            mid = (lo + hi) // 2
            if values[mid] <= value:
                lo = mid + 1
            else:
                hi = mid
        return lo / len(values) * 100.0

    for row in rows:
        if row.get(key) is not None:
            row[f"{key}_pctile{suffix}"] = round(rank(row[key]), 1)


def cmd_tv_sweep(args):
    rows, total = fetch_universe(args.min_cap)
    derived = [derive(r) for r in rows]
    _percentiles(derived, "atr_pct")
    _percentiles(derived, "pct_above_sma20")
    _percentiles(derived, "rsi")
    # The same percentiles inside the $10B+ sub-universe, because the Tier-A
    # book lives there and a market-wide percentile understates a large cap's
    # volatility.
    large = [r for r in derived if (r.get("market_cap_basic") or 0) > 1e10]
    _percentiles(derived, "atr_pct", "_lc", against=large)
    _percentiles(derived, "pct_above_sma20", "_lc", against=large)

    branches = {}
    for name in GATES:
        kept, passing = branch_rows(name, derived)
        branches[name] = {"rows_passing": passing, "rows": kept}
        print(f"  {name}: {passing} names", flush=True)

    extension = {}
    for row in derived:
        label = extension_labels(row)
        # The extension metrics are ALWAYS the cron day's (they describe the
        # name's state right now), even for a name that is only in the T+1
        # book. The date is published so a reader cannot mistake a Monday
        # ATR% for a Friday one.
        label["data_as_of"] = args.date
        extension[row["symbol"]] = label

    payload = {
        "_engine": CAPABILITY_MARKER,
        "_source": "tradingview_scanner",
        "data_as_of": args.date,
        "universe": {
            "count": len(derived),
            "total_count": total,
            "filter": (
                "exchange in_range [NYSE,NASDAQ,AMEX]; type in_range [stock,dr]; "
                f"market_cap_basic > {args.min_cap}"
            ),
            "columns": TV_COLUMNS,
        },
        "gates": GATES,
        "extension_rules": EXTENSION_RULES,
        "branches": branches,
        "extension": extension,
        "rows": derived,
        "notes": {
            "perf_w_basis": (
                "Perf.W is a SIX-session move (r=0.997 vs 6 sessions, r=0.924 vs 5, "
                "measured 2026-11-09 on 11 names). The 5-session parabolic gates are "
                "NOT re-expressed on this basis; they stay on shibui and stay T+1."
            ),
            "volume_basis": (
                "average_volume_10d_calc == mean(last 10 sessions INCLUDING today) "
                "(bias 0.00% vs a hand-computed reference, 2026-11-09). The "
                "prior-nine-session baseline is reconstructed exactly."
            ),
            "change_units": "change is in PERCENT units on this scanner, never a fraction.",
        },
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")
    print(f"tv-sweep: wrote {out} ({len(derived)} universe names, {total} totalCount)")
    return 0


# ---------------------------------------------------------- the overlay engine

def _sql_list(symbols):
    return ",".join("'" + s.replace("'", "") + "'" for s in symbols)


def overlay_quality(bridge, symbols, t1_date, page=200):
    """The valuation/quality fields AND the up-day streak, joined server-side so
    the result is one row per symbol.

    THE SYMBOL LIST IS CHUNKED (200 per bridge call).  Measured 2026-11-12: a
    single request carrying the whole book (3,814 tickers in one IN list) came
    back as `{"error": "rpc_failed", "response": {"error":
    "unparseable_response", "raw": ""}}` — an EMPTY body, not a query error, so
    the run could not tell a transport failure from an empty result.  The
    LIMIT/OFFSET paging inside a chunk did NOT help: the request size, not the
    result size, is what the bridge refuses.  Chunking the IN list fixes it and
    keeps the one-call-per-200-symbols budget the function always claimed.
    """
    if not symbols:
        return {}
    out: dict = {}
    for i in range(0, len(symbols), page):
        out.update(_overlay_chunk(bridge, symbols[i:i + page], t1_date, page))
    return out


def _overlay_chunk(bridge, symbols, t1_date, page=200):
    """One chunk of the overlay: the valuation/quality fields AND the up-day
    streak, joined server-side so the result is one row per symbol."""
    if not symbols:
        return {}
    sym_sql = _sql_list(symbols)
    # The book is keyed on BARE tickers (TradingView's form), while shibui's
    # `symbol` column is venue-suffixed. `ticker` is bare on every table, so
    # the whole overlay joins on `ticker` and no mapping file is needed.
    query = f"""
WITH h AS (
  SELECT q.ticker, q.symbol, q.date, q.close,
         LAG(q.close) OVER (PARTITION BY q.ticker ORDER BY q.date) AS prev_close
  FROM shibui.stock_quotes q
  WHERE q.ticker IN ({sym_sql})
    AND q.date BETWEEN DATE '{t1_date}' - INTERVAL '40 days' AND '{t1_date}'
),
g AS (
  SELECT h.*,
         SUM(CASE WHEN h.close <= h.prev_close THEN 1 ELSE 0 END)
           OVER (PARTITION BY h.ticker ORDER BY h.date) AS grp
  FROM h
),
lastg AS (
  SELECT ticker, MAX(grp) AS grp FROM g GROUP BY ticker
),
streak AS (
  SELECT g.ticker, COUNT(*) AS up_days_streak
  FROM g JOIN lastg l ON g.ticker = l.ticker AND g.grp = l.grp
  WHERE g.close > g.prev_close AND g.prev_close IS NOT NULL
  GROUP BY g.ticker
),
qc AS (
  SELECT ticker, close FROM (
    SELECT q.ticker, q.close,
           ROW_NUMBER() OVER (PARTITION BY q.ticker ORDER BY q.symbol) AS rn
    FROM shibui.stock_quotes q
    WHERE q.ticker IN ({sym_sql}) AND q.date = '{t1_date}'
  ) WHERE rn = 1
),
fd AS (
  SELECT ticker, trailing_pe, operating_pe, ev_ebit, price_to_sales,
         free_cash_flow_yield, trailing_revenue_peg, earnings_quality_flags
  FROM (
    SELECT f.ticker, f.trailing_pe, f.operating_pe, f.ev_ebit, f.price_to_sales,
           f.free_cash_flow_yield, f.trailing_revenue_peg, f.earnings_quality_flags,
           ROW_NUMBER() OVER (PARTITION BY f.ticker ORDER BY f.date DESC) AS rn
    FROM shibui.fundamentals_derived_daily f
    WHERE f.ticker IN ({sym_sql})
  ) WHERE rn = 1
),
fq AS (
  SELECT ticker, debt_to_equity, profit_margin_ttm, return_on_invested_capital
  FROM (
    SELECT f.ticker, f.debt_to_equity, f.profit_margin_ttm, f.return_on_invested_capital,
           ROW_NUMBER() OVER (PARTITION BY f.ticker ORDER BY f.date DESC) AS rn
    FROM shibui.fundamentals_derived_quarterly f
    WHERE f.ticker IN ({sym_sql})
  ) WHERE rn = 1
)
SELECT s.ticker AS symbol,
       qc.close AS t1_close,
       st.up_days_streak,
       fd.trailing_pe, fd.operating_pe, fd.ev_ebit, fd.price_to_sales,
       fd.free_cash_flow_yield, fd.trailing_revenue_peg, fd.earnings_quality_flags,
       fq.debt_to_equity, fq.profit_margin_ttm, fq.return_on_invested_capital
FROM (SELECT DISTINCT ticker FROM h) s
LEFT JOIN qc ON qc.ticker = s.ticker
LEFT JOIN streak st ON st.ticker = s.ticker
LEFT JOIN fd ON fd.ticker = s.ticker
LEFT JOIN fq ON fq.ticker = s.ticker
ORDER BY s.ticker
LIMIT {page} OFFSET 0"""
    out = {}
    offset = 0
    while True:
        paged = query.replace(f"LIMIT {page} OFFSET 0", f"LIMIT {page} OFFSET {offset}")
        rows = _bridge_call(
            bridge, "shibui", "stock_data_query",
            {"query": paged, "user_prompt": "cron #09 valuation/quality overlay + up-day streak"},
        )
        if not isinstance(rows, list):
            raise EngineError(f"overlay query returned {type(rows).__name__}, expected a list")
        for row in rows:
            if row.get("symbol"):
                out[row["symbol"]] = row
        if len(rows) < page:
            break
        offset += page
        if offset > 20_000:
            raise EngineError("overlay paging did not terminate")
    return out


def quality_labels(row):
    """The valuation/quality verdict.

    A MISSING value is a DISCLOSURE, not a flag: a name with no trailing P/E
    is published as `earnings_data_missing` with `valuation_gate: unknown`,
    which is different from a name that PASSED the gate. The 2026-11-09
    overlay flagged 910 of 1,232 names when a null P/E counted as a red flag —
    a label that fires on three quarters of the book is as useless as one that
    never fires, so the two are separated.

    The five RED flags are the ones the suite never asked about at all:
    an extreme multiple, negative free cash flow, a high PEG, heavy leverage,
    and shibui's own `earnings_quality_flags`.
    """
    flags, reasons = [], []
    for key, rule in QUALITY_RULES.items():
        value = _f(row.get(key))
        if value is None:
            continue
        hit = value > rule["value"] if rule["op"] == ">" else value < rule["value"]
        if hit:
            flags.append(key)
            reasons.append(f"{rule['label']} ({value:.4g})")
    raw_flags = row.get("earnings_quality_flags")
    if isinstance(raw_flags, str) and raw_flags.strip() not in ("", "[]"):
        flags.append("earnings_quality_flags")
        reasons.append(f"earnings_quality_flags: {raw_flags}")
    elif isinstance(raw_flags, list) and raw_flags:
        flags.append("earnings_quality_flags")
        reasons.append(f"earnings_quality_flags: {raw_flags}")

    # A NULL trailing P/E means the company does not report trailing earnings
    # (or the row is missing). It is DISCLOSED, never a silent pass — and it
    # is never counted as a red flag, because most of the book's small caps
    # have no trailing multiple at all.
    earnings_missing = _f(row.get("trailing_pe")) is None
    if earnings_missing:
        reasons.append("no trailing P/E — earnings data missing (disclosed, not a red flag)")

    if flags:
        severity = "flagged" if len(flags) >= 2 else "watch"
    else:
        severity = "clean"
    if earnings_missing and not flags:
        gate = "unknown"
    elif flags:
        gate = "fail"
    else:
        gate = "pass"

    return {
        "quality_flags": flags,
        "quality_reasons": reasons,
        "quality_clean": not flags,
        "quality_severity": severity,
        "quality_checked": True,
        "earnings_data_missing": earnings_missing,
        "valuation_gate": gate,
    }


def cmd_overlay(args):
    symbols = [s.strip() for s in Path(args.symbols).read_text().split() if s.strip()] \
        if Path(args.symbols).exists() else [s.strip() for s in args.symbols.split(",") if s.strip()]
    if args.max_symbols:
        symbols = symbols[: args.max_symbols]
    rows = overlay_quality(args.bridge, symbols, args.t1_date)

    fresh = {}
    if args.tv_json and Path(args.tv_json).exists():
        tv = json.loads(Path(args.tv_json).read_text())
        for row in tv.get("rows", []):
            fresh[row["symbol"]] = row

    out = {}
    for symbol, row in rows.items():
        verdict = quality_labels(row)
        streak = int(row.get("up_days_streak") or 0)
        fresh_row = fresh.get(symbol)
        if fresh_row is not None and fresh_row.get("close") is not None:
            t1_close = _f(row.get("t1_close"))
            fresh_close = fresh_row.get("close")
            if t1_close and fresh_close:
                # The streak through the FRESH session: the T+1 streak, extended
                # by the fresh session if it was an up day, reset to 0 if it
                # was not.
                streak = streak + 1 if fresh_close > t1_close else 0
                verdict["fresh_session_up"] = fresh_close > t1_close
        verdict["up_days_streak"] = streak
        out[symbol] = {
            "data_as_of": args.date,
            "t1_data_as_of": args.t1_date,
            "t1_close": _f(row.get("t1_close")),
            "up_days_streak": streak,
            "trailing_pe": _f(row.get("trailing_pe")),
            "operating_pe": _f(row.get("operating_pe")),
            "ev_ebit": _f(row.get("ev_ebit")),
            "price_to_sales": _f(row.get("price_to_sales")),
            "free_cash_flow_yield": _f(row.get("free_cash_flow_yield")),
            "trailing_revenue_peg": _f(row.get("trailing_revenue_peg")),
            "earnings_quality_flags": row.get("earnings_quality_flags"),
            "debt_to_equity": _f(row.get("debt_to_equity")),
            "profit_margin_ttm": _f(row.get("profit_margin_ttm")),
            "return_on_invested_capital": _f(row.get("return_on_invested_capital")),
            **verdict,
        }
    payload = {
        "_engine": CAPABILITY_MARKER,
        "_source": "shibui fundamentals + history",
        "data_as_of": args.date,
        "t1_data_as_of": args.t1_date,
        "quality_rules": QUALITY_RULES,
        "symbols": out,
    }
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")
    flagged = sum(1 for v in out.values() if not v["quality_clean"])
    print(f"overlay: {len(out)} symbols, {flagged} carry a quality flag -> {path}")
    return 0


# ----------------------------------------------------------------- selftest


def cmd_selftest(_args):
    checks = []

    def check(name, condition, detail=""):
        checks.append((name, bool(condition), detail))

    # change is in PERCENT units and prev_close is derived correctly
    row = derive({"_ticker": "X", "description": "X", "close": 110.0, "change": 10.0,
                  "volume": 1_000_000, "average_volume_10d_calc": 500_000, "open": 100.0,
                  "SMA20": 100.0, "SMA50": 100.0, "ATR": 3.0, "RSI": 50.0})
    check("implied_prev_close", abs(row["implied_prev_close"] - 100.0) < 1e-6, str(row["implied_prev_close"]))
    check("gap_pct", abs(row["gap_pct"] - 0.0) < 1e-6, str(row["gap_pct"]))
    # prior-nine mean is reconstructed exactly from the ten-day average
    check("prior9 reconstruction",
          abs(row["prior9_avg_volume"] - (10 * 500_000 - 1_000_000) / 9) < 1e-6,
          str(row["prior9_avg_volume"]))
    check("volume_expansion_ratio", abs(row["volume_expansion_ratio"] - 1_000_000 / row["prior9_avg_volume"]) < 1e-9)
    check("pct_above_sma20", abs(row["pct_above_sma20"] - 10.0) < 1e-9)
    check("atr_pct", abs(row["atr_pct"] - 3.0 / 110.0 * 100) < 1e-9)

    # the extension rules fire, and a clean name does not
    clean = extension_labels({"atr_pct": 2.0, "rsi": 55.0, "pct_above_sma20": 3.0}, up_days_streak=1)
    check("clean name is not extended", clean["extended"] is False, json.dumps(clean))
    hot = extension_labels({"atr_pct": 8.0, "rsi": 80.0, "pct_above_sma20": 30.0}, up_days_streak=4)
    check("hot name is extended", hot["extended"] is True)
    check("all four rules fired", hot["extension_count"] == 4, json.dumps(hot["extension_hits"]))
    check("a missing input is not a hit",
          extension_labels({"atr_pct": None, "rsi": 50.0, "pct_above_sma20": 1.0}, up_days_streak=1)["extension_count"] == 0)

    # the quality overlay: a KRMN-shaped row must be flagged
    krmn = quality_labels({"trailing_pe": 120.587, "operating_pe": 55.76, "ev_ebit": 62.72,
                           "free_cash_flow_yield": -0.00116, "trailing_revenue_peg": 1.8395,
                           "debt_to_equity": 2.2841, "earnings_quality_flags": ["LOW_EARNINGS_QUALITY"]})
    for want in ("trailing_pe", "operating_pe", "free_cash_flow_yield", "debt_to_equity",
                 "earnings_quality_flags"):
        check(f"quality flags {want}", want in krmn["quality_flags"], json.dumps(krmn["quality_flags"]))
    check("KRMN is not quality-clean", krmn["quality_clean"] is False)
    check("KRMN fails the valuation gate", krmn["valuation_gate"] == "fail", json.dumps(krmn))
    check("KRMN severity is flagged", krmn["quality_severity"] == "flagged")
    # a NULL P/E is DISCLOSED and the gate is "unknown" — never a silent pass
    null_pe = quality_labels({"trailing_pe": None, "price_to_sales": 4.0})
    check("null P/E is disclosed", null_pe["earnings_data_missing"] is True)
    check("null P/E is not a red flag", null_pe["quality_flags"] == [])
    check("null P/E fails the gate as unknown, not as a pass",
          null_pe["valuation_gate"] == "unknown", json.dumps(null_pe))
    check("null P/E is not a silent clean", null_pe["quality_clean"] is True)
    # a genuinely clean row passes
    ok = quality_labels({"trailing_pe": 18.0, "operating_pe": 15.0, "free_cash_flow_yield": 0.05,
                         "trailing_revenue_peg": 1.1, "debt_to_equity": 0.4, "earnings_quality_flags": []})
    check("a clean row is clean", ok["quality_clean"] is True, json.dumps(ok["quality_flags"]))
    check("a clean row passes the gate", ok["valuation_gate"] == "pass", json.dumps(ok))
    check("a clean row has earnings data", ok["earnings_data_missing"] is False)

    # the percentile helper ranks against the population it is given
    pop = [{"atr_pct": 1.0}, {"atr_pct": 2.0}, {"atr_pct": 3.0}, {"atr_pct": 4.0}]
    _percentiles(pop, "atr_pct")
    check("percentile bottom", abs(pop[0]["atr_pct_pctile"] - 25.0) < 1e-6, str(pop[0]))
    check("percentile top", abs(pop[3]["atr_pct_pctile"] - 100.0) < 1e-6, str(pop[3]))
    ranked = [{"atr_pct": 2.0}, {"atr_pct": 10.0}]
    _percentiles(ranked, "atr_pct", "_lc", against=pop)
    check("percentile against another population",
          abs(ranked[1]["atr_pct_pctile_lc"] - 100.0) < 1e-6, str(ranked[1]))
    check("percentile published for a row outside the population",
          "atr_pct_pctile_lc" in ranked[0], str(ranked[0]))

    # the branch gates
    good = {"close": 50.0, "change_pct": 5.0, "volume": 9_000_000, "avg_volume_10d_calc": 1_000_000,
            "prior9_avg_volume": 1_000_000, "volume_expansion_ratio": 9.0, "gap_pct": 12.0,
            "adv_dollar_prior9": 60_000_000, "relative_volume_10d_calc": 3.0}
    check("A gate fires", branch_rows("A_tv_breakout_4pct", [good])[1] == 1)
    check("B gate fires", branch_rows("B_tv_ep9m", [good])[1] == 1)
    check("D gate fires", branch_rows("D_tv_gap_10pct", [good])[1] == 1)
    flat = dict(good, change_pct=1.0, gap_pct=2.0, volume_expansion_ratio=0.8)
    check("A gate blocks a flat name", branch_rows("A_tv_breakout_4pct", [flat])[1] == 0)
    check("D gate blocks a small gap", branch_rows("D_tv_gap_10pct", [flat])[1] == 0)

    failed = [c for c in checks if not c[1]]
    for name, ok_, detail in checks:
        print(f"  {'PASS' if ok_ else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok_ else ""))
    print(f"\n{'All selftests passed' if not failed else str(len(failed)) + ' selftest(s) FAILED'}")
    return 1 if failed else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="cron #09 daily-sweep engines")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_tv = sub.add_parser("tv-sweep", help="the fresh book + extension metrics (TradingView)")
    p_tv.add_argument("--date", required=True, help="the cron day (the settled session)")
    p_tv.add_argument("--out", required=True)
    p_tv.add_argument("--min-cap", type=float, default=300_000_000)
    p_tv.set_defaults(func=cmd_tv_sweep)

    p_ov = sub.add_parser("overlay", help="the valuation/quality overlay + up-day streak (shibui)")
    p_ov.add_argument("--date", required=True, help="the cron day")
    p_ov.add_argument("--t1-date", required=True, help="shibui's newest settled session")
    p_ov.add_argument("--symbols", required=True, help="a file of symbols, or a comma-separated list")
    p_ov.add_argument("--out", required=True)
    p_ov.add_argument("--bridge", default="/workspace/mcp_bridge.py")
    p_ov.add_argument("--tv-json", default=None, help="tv-sweep output, for the fresh-session streak")
    p_ov.add_argument("--max-symbols", type=int, default=0)
    p_ov.set_defaults(func=cmd_overlay)

    p_st = sub.add_parser("selftest", help="offline checks of every derived quantity")
    p_st.set_defaults(func=cmd_selftest)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except EngineError as exc:
        print(f"ENGINE FAILURE: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
