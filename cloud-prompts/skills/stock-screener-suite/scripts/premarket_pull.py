#!/usr/bin/env python3
"""Pre-market prices that survive Nasdaq's stale HTTP cache — and a verdict.

Why
---
Cron #08 (stock-screener-pre-market-gapper) must publish a pre-market gap for
every Focus name. The obvious source, `api.nasdaq.com/.../extended-trading`,
is served through a **shared HTTP cache** that can hand back a snapshot
captured much earlier. Measured 2026-11-03: the *same URL* returned a
4.5-hour-old vintage (AAPL pre-market 05:33:19) alongside a current one
(09:30:01) in the same second, and MSFT/GOOGL alternated between 05:31-05:33
and 09:30:01 across rapid pulls. Responses carry a `cache-hit` header. A
cache-buster query string does **not** reliably route around it - eight pulls
with eight distinct URLs still alternated.

The symptom is a tape whose newest print appears to run 16-39 minutes behind
wall clock, which reads exactly like a slow exchange feed but is not one. The
tape's own newest print advanced ~1:1 with wall clock at a constant offset:
the signature of a periodically-refreshed cache.

Meanwhile `/info` is the LIVE source - `primaryData.lastTradeTimestamp`
tracks wall clock to the minute and the price changes on every pull. But a
live last sale is not necessarily a *market*: on 2026-11-03 PURR's `/info` last
sale was $10.14 while the consolidated tape's last executed print was
$10.0083, and $10.14 was the ASK. A gap is only real if a print with size
behind it crossed it.

How this script fixes it
------------------------
1. Pull the tape N times and keep the payload with the **newest internal
   timestamp** (the latest `tradeDetailTable` clock time, AFTER sorting - the
   table is served newest-first). A stale vintage can never win a
   max-timestamp comparison.
2. Take the **price** from `/info` `primaryData` (live); use the tape for
   *which prints actually traded*, the pre-market high/low, and volume.
3. Cross-check with the **Cboe delayed-quote CDN**, which returns an explicit
   `last_trade_time` and `timestamp` - freshness is verifiable from the
   payload rather than inferred, and it is not subject to the Nasdaq cache.
4. When the trade-detail tape is **complete** (fewer than 100 rows - Nasdaq
   caps that table at 100) it can arbitrate a contradictory cumulative volume
   counter; when the tape is truncated it cannot, and the counter is used.
5. Compute the **verdict** — a fixed vocabulary — instead of leaving the reader
   to infer it from two numbers and a caveat. See `VERDICTS` below.
6. Take the reference close from the prior sweep's own `focus.csv` and
   cross-check it against TradingView and Cboe, publishing which sources agreed
   in `ref_close_source`.

Everything it reports carries its own provenance, so the artifact can state
the margin against the trigger and show that the flag decision is immune to
whatever the cache served.

Usage
-----
    python scripts/premarket_pull.py --symbols AAPL,MSFT,NVDA
    python scripts/premarket_pull.py --from-csv daily-screens/2026-10-30/focus.csv \
        --out-dir daily-screens/2026-11-02
    python scripts/premarket_pull.py --symbols AAPL --pulls 6 --gap-trigger 4

Outputs
-------
    <out-dir>/_premarket-pull.json   full per-symbol provenance
    <out-dir>/premarket-pull.md      a markdown table
    <out-dir>/pre-market-gapper.csv  the CONTRACT csv (one row per Focus name)
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36",
    "Referer": "https://www.nasdaq.com/",
    "Accept": "application/json, text/plain, */*",
}
NASDAQ_INFO = "https://api.nasdaq.com/api/quote/{sym}/info?assetclass={ac}"
# ETFs (SPY/QQQ/IWM...) return data:null under assetclass=stocks - they need etf.
ASSET_CLASSES = ("stocks", "etf")
NASDAQ_TAPE = ("https://api.nasdaq.com/api/quote/{sym}/extended-trading"
               "?assetclass={ac}&markettype=pre")
CBOE_QUOTE = "https://cdn.cboe.com/api/global/delayed_quotes/quotes/{sym}.json"
TV_SCAN = "https://scanner.tradingview.com/america/scan"

TAPE_ROW_CAP = 100        # Nasdaq caps tradeDetailTable at 100 rows
MIN_REAL_PRINT = 25       # a print of >= 25 shares is a market; 1-2 lots are quotes

# ---- THE PUBLISHED CONTRACT (kept in sync with the skill spec §6) -------------
CONTRACT_VERSION = "premarket-artifact-v5"
GAP_TRIGGER_PCT = 4.0        # unchanged since the routine was written
MIN_PM_VOLUME_SHARES = 50_000  # unchanged
MIN_EXECUTED_SHARES = 25     # NEW: the print that carries the gap must have size behind it

VERDICTS = (
    "FLAGGED",              # clears on the tape AND size
    "BORDERLINE_THIN",      # the bar was printed, but the market behind it is too thin
    "BORDERLINE_TAPE_ONLY",  # clears on the live quote, not on the executed tape
    "BORDERLINE_INTRADAY",   # crossed the bar during the session, not at the snapshot
    "NO_PRINT",              # no executed print at all
    "BELOW",                 # printed, and below the bar on every reading
)

CSV_COLUMNS = [
    # v5: the universe's own date and the denominator's session are published
    # per row, so a consumer can never read a gap without knowing which session
    # it is measured against.
    "universe_date", "ref_close_date", "universe_source",
    "ticker", "ref_close", "ref_close_source", "pm_price", "pm_gap_pct",
    "exec_shares", "exec_notional", "pm_volume", "pm_volume_source",
    "quote_price", "quote_gap_pct", "bid", "ask",
    "pm_high", "pm_low", "pm_high_gap_pct", "pm_low_gap_pct",
    "tv_pm_pct", "tv_pm_volume", "stylists", "origins",
    "verdict", "flag_reason",
]


def _num(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("$", "").replace(",", "").replace("%", "")
    try:
        return float(s)
    except ValueError:
        return None


def _get(url: str, timeout: int = 25):
    """GET + JSON parse. Returns (payload, cache_hit) or (None, None)."""
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            cache_hit = resp.headers.get("cache-hit")
            body = resp.read().decode("utf-8", errors="replace")
        return json.loads(body), cache_hit
    except Exception:
        return None, None


def _consol_price(raw: str | None):
    """'$7.9699 -0.1559 (-1.92%)' -> 7.9699 (the composite's first token)."""
    if not raw:
        return None
    m = re.match(r"^\$?([\d,]+\.?\d*)", raw)
    return float(m.group(1).replace(",", "")) if m else None


def _consol_pct(raw: str | None):
    if not raw:
        return None
    m = re.search(r"\(([-+]?[\d.]+)%\)", raw)
    return float(m.group(1)) if m else None


def _px_field(raw: str | None):
    """'$8.0009 (07:19:14 AM)' -> 8.0009. The parenthetical is a print time."""
    if not raw:
        return None
    m = re.match(r"^\s*\$?\s*([\d,]+(?:\.\d+)?)", str(raw))
    return float(m.group(1).replace(",", "")) if m else None


def _hhmm_to_min(hhmm: str | None):
    if not hhmm:
        return None
    m = re.match(r"^(\d{1,2}):(\d{2})\s*([AP]M)", str(hhmm))
    if not m:
        return None
    h = int(m.group(1)) % 12
    if m.group(3).upper() == "PM":
        h += 12
    return h * 60 + int(m.group(2))


def _clock_to_min(clock: str | None):
    if not clock:
        return None
    m = re.match(r"^(\d{2}):(\d{2}):(\d{2})$", str(clock).strip())
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def _pull_tape(sym: str, bust: bool, asset_class: str = "stocks"):
    """One tape pull. Returns a record describing what came back."""
    url = NASDAQ_TAPE.format(sym=sym, ac=asset_class)
    if bust:
        url += "&u=%d" % time.time_ns()
    payload, cache_hit = _get(url)
    if not payload:
        return None
    data = payload.get("data") or {}
    rows = ((data.get("tradeDetailTable") or {}).get("rows") or [])
    info_rows = ((data.get("infoTable") or {}).get("rows") or [{}])
    info_row = info_rows[0] if info_rows else {}

    prints = []
    for r in rows:
        px = _num(r.get("price"))
        if px is None:
            continue
        prints.append({
            "time": r.get("time"),
            "minutes": _clock_to_min(r.get("time")),
            "price": px,
            "vol": _num(r.get("shareVolume")),
        })
    # The table is served NEWEST-FIRST: rows[-1] is the OLDEST print. Sorting by
    # clock time is what makes "the last print" mean the last EXECUTED print.
    prints.sort(key=lambda p: (p["minutes"] is None, p["minutes"]))

    newest = prints[-1] if prints else None
    return {
        "prints": prints,
        "newest": newest,
        "consol_raw": info_row.get("consolidated"),
        "consol_price": _consol_price(info_row.get("consolidated")),
        "consol_pct": _consol_pct(info_row.get("consolidated")),
        "counter_vol": _num(info_row.get("volume")),
        "pm_high": info_row.get("highPrice"),
        "pm_low": info_row.get("lowPrice"),
        "tape_rows": len(rows),
        "cache_hit": cache_hit,
        "updated": (data.get("lastUpdateInfo") or [None])[0],
    }


def _best_tape(sym: str, pulls: int):
    """Pull N times; keep the payload whose newest internal timestamp is latest.

    This is the core defence against the stale cache: a stale vintage can be
    hours old, but it can never carry a NEWER internal timestamp than the
    current one, so it can never win this comparison.
    """
    seen = []
    for i in range(pulls):
        for ac in ASSET_CLASSES:
            rec = _pull_tape(sym, bust=(i % 2 == 0), asset_class=ac)
            if rec and rec.get("prints") or (rec and rec.get("consol_raw")):
                rec["asset_class"] = ac
                seen.append(rec)
                break
        if i + 1 < pulls:
            time.sleep(0.3)
    if not seen:
        return None, []
    ranked = sorted(
        [s for s in seen if s.get("newest")],
        key=lambda s: (s["newest"]["minutes"] or 0),
    )
    best = ranked[-1] if ranked else seen[-1]
    return best, seen


def _fetch_info(sym: str):
    """The LIVE source. primaryData.lastTradeTimestamp tracks wall clock.

    Two wrinkles:
    * `secondaryData` holds the official close ONLY while the regular session is
      running; once the market is Closed it comes back null. The prior close
      then has to come from the caller (the sweep's own focus.csv) or from Cboe.
      It also DRIFTS intraday - on 2026-11-03 it read $206.00 for QLYS whose
      settled close was $207.60, and it flipped mid-session for KOD. Never use
      it as the denominator without a second source agreeing.
    * ETFs (SPY/QQQ/IWM) return data:null under assetclass=stocks and need
      assetclass=etf, so both are tried.
    """
    for ac in ASSET_CLASSES:
        payload, _ = _get(NASDAQ_INFO.format(sym=sym, ac=ac))
        if not payload:
            continue
        data = payload.get("data") or {}
        if not data:
            continue
        primary = data.get("primaryData") or {}
        secondary = data.get("secondaryData") or {}
        ts = primary.get("lastTradeTimestamp")
        price = _num(primary.get("lastSalePrice"))
        if price is None:
            continue
        return {
            "price": price,
            "pct": _num(primary.get("percentageChange")),
            "ts": ts,
            "ts_minutes": _hhmm_to_min(ts),
            "bid": _num(primary.get("bidPrice")),
            "ask": _num(primary.get("askPrice")),
            "secondary_close": _num(secondary.get("lastSalePrice")),
            "market_status": data.get("marketStatus"),
            "asset_class": ac,
        }
    return None


def _fetch_cboe(sym: str):
    """Independent venue with an explicit print time - freshness is verifiable."""
    payload, _ = _get(CBOE_QUOTE.format(sym=sym))
    if not payload:
        return None
    data = payload.get("data") or {}
    if not data:
        return None
    return {
        "price": _num(data.get("current_price")),
        "close": _num(data.get("close")),
        "prev_day_close": _num(data.get("prev_day_close")),
        "volume": data.get("volume"),
        "last_trade_time": data.get("last_trade_time"),
        "timestamp": (payload.get("timestamp")),
    }


def _fetch_tv(symbols):
    """One TradingView america-scanner call for the whole Focus list.

    Gives the second independent reference close and a pre-market cross-check.
    `premarket_price` is null for US names - use `premarket_change` and
    `premarket_high`/`premarket_low`. A filter with `name` + `in_range` works;
    bare tickers in `symbols` + a filter returns 0 rows (measured 2026-11-03).
    """
    if not symbols:
        return {}
    cols = ["name", "close", "premarket_change", "premarket_high", "premarket_low",
            "premarket_volume", "description"]
    body = {
        "filter": [{"left": "type", "operation": "equal", "right": "stock"},
                   {"left": "name", "operation": "in_range", "right": list(symbols)}],
        "columns": cols,
        "range": [0, len(symbols) + 5],
    }
    req = urllib.request.Request(TV_SCAN, data=json.dumps(body).encode(),
                                 headers={**UA, "Content-Type": "application/json"})
    try:
        res = json.loads(urllib.request.urlopen(req, timeout=30).read())
    except Exception:
        return {}
    out = {}
    for row in res.get("data") or []:
        s = row.get("d") or []
        if not s:
            continue
        out[str(s[0]).upper()] = {
            "close": _num(s[1]),
            "premarket_change": _num(s[2]),
            "premarket_high": _num(s[3]),
            "premarket_low": _num(s[4]),
            "premarket_volume": _num(s[5]),
            "description": s[6] if len(s) > 6 else "",
        }
    return out


def _load_symbols(args) -> list[str]:
    syms: list[str] = []
    if args.symbols:
        syms += [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    if args.from_csv:
        with open(args.from_csv, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                for key in ("ticker", "symbol", "Ticker", "Symbol"):
                    if row.get(key):
                        syms.append(str(row[key]).strip().split(".")[0].split("/")[0].upper())
                        break
    seen, out = set(), []
    for s in syms:
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _load_focus(csv_path: str, session: str | None = None,
                sweep_date: str | None = None) -> dict[str, dict]:
    """Read the prior sweep's own focus.csv.

    Three things come from it, and all three matter:

    * the **reference close** — the sweep's session close, taken from the
      LATEST dated `close_<YYYY-MM-DD>` column (the sweep's own session date is
      the newest one). The sweep's CSV also carries undated keys (`close`,
      `prior_close`), which win when present.
    * the **screen provenance** — `stylists` (how many screens picked the name)
      and `origins` (which ones). This is what lets the artifact say "CDNA, five
      origins and three stylists" instead of dropping a high-quality setup that
      went nowhere.
    * the sweep's own `flags` column.
    """
    out: dict[str, dict] = {}
    if not csv_path:
        return out
    try:
        with open(csv_path, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            fieldnames = reader.fieldnames or []
            dated = sorted([f for f in fieldnames
                            if re.fullmatch(r"close[_-]?\d{4}-\d{2}-\d{2}", f)])
            # FIXED 2026-11-09 (cron #08): `today_col` / `screen_col` were USED
            # below but never DEFINED, so _load_focus() raised NameError, the
            # blanket `except` swallowed it, and the function returned {} - which
            # silently dropped the screen provenance (stylists, origins) AND the
            # focus.csv close from every row. The column names are resolved from
            # the CSV HEADER, and the close column is still chosen BY DATE.
            today_col = "today_close" if "today_close" in fieldnames else None
            screen_col = ("screen_close_resolved"
                          if "screen_close_resolved" in fieldnames else None)
            for row in reader:
                sym = None
                for key in ("ticker", "symbol", "Ticker", "Symbol"):
                    if row.get(key):
                        sym = str(row[key]).strip().split(".")[0].split("/")[0].upper()
                        break
                if not sym:
                    continue
                close, close_col = None, None
                # 1. the dated column whose DATE is the denominator session
                if dated:
                    for f in dated:
                        m = re.search(r"(\d{4}-\d{2}-\d{2})", f)
                        if m and m.group(1) == session:
                            close, close_col = _num(row.get(f)), f
                            break
                # 2. the current schema's `today_close` - valid ONLY when the
                #    sweep's own session IS the denominator session
                if close is None and today_col and session == sweep_date:
                    close, close_col = _num(row.get(today_col)), today_col
                # 3. legacy undated keys
                if close is None:
                    for key in ("prior_close", "close", "last_close", "close_1030"):
                        if row.get(key) and _num(row[key]):
                            close, close_col = _num(row[key]), key
                            break
                # 4. last resort: the newest dated column (flagged as such)
                if close is None and dated:
                    close_col = dated[-1]
                    close = _num(row.get(close_col))
                out[sym] = {
                    "close": close,
                    "close_col": close_col,
                    "universe_date": sweep_date,
                    "ref_close_date": session if close_col else None,
                    "universe_source": (f"focus.csv:{close_col}"
                                        if close_col and close_col in (today_col, *dated)
                                        else "focus.csv (legacy key)"),
                    "screen_col_rejected": screen_col,
                    "stylists": (row.get("stylists") or "").strip(),
                    "origins": (row.get("origins") or "").strip(),
                    "flags": (row.get("flags") or "").strip(),
                }
    except Exception:
        return out
    return out


def _one(sym: str, args, focus: dict | None = None,
         tv: dict | None = None) -> tuple[str, dict | None]:
    best, seen = _best_tape(sym, args.pulls)
    info = _fetch_info(sym)
    cboe = _fetch_cboe(sym) if args.cboe else None
    focus = focus or {}
    tv = tv or {}

    if best is None and info is None:
        return sym, None

    rec: dict = {
        "ticker": sym,
        "tape_pulls": len(seen),
        "tape_vintages": sorted({s["newest"]["time"] for s in seen if s.get("newest")}),
        "cache_hits": sorted({str(s.get("cache_hit")) for s in seen if s.get("cache_hit")}),
    }

    if best:
        prints = best["prints"]
        real = [p for p in prints if (p.get("vol") or 0) >= MIN_REAL_PRINT]
        tape_sum = sum((p.get("vol") or 0) for p in prints)
        counter = best.get("counter_vol")
        # A COMPLETE tape (fewer rows than the cap) can arbitrate a bad counter.
        if counter is None:
            volume, vol_src = tape_sum, "tape sum (LOWER BOUND - no cumulative counter published)"
        elif best["tape_rows"] < TAPE_ROW_CAP and tape_sum and counter > tape_sum * 3:
            volume = tape_sum
            vol_src = ("tape sum - Nasdaq counter %s REJECTED as faulty (complete %d-print tape "
                       "sums to %s)" % ("{:,}".format(int(counter)), best["tape_rows"],
                                         "{:,}".format(int(tape_sum))))
        else:
            volume, vol_src = counter, "Nasdaq extended-trading cumulative counter"

        rec.update({
            "tape_newest_print": best["newest"]["time"] if best.get("newest") else None,
            "tape_last_price": best["newest"]["price"] if best.get("newest") else None,
            "tape_last_print_vol": best["newest"]["vol"] if best.get("newest") else None,
            "tape_consol_raw": best.get("consol_raw"),
            "tape_consol_pct": best.get("consol_pct"),
            "pm_high": best.get("pm_high"),
            "pm_low": best.get("pm_low"),
            "pm_high_px": _px_field(best.get("pm_high")),
            "pm_low_px": _px_field(best.get("pm_low")),
            "tape_rows": best["tape_rows"],
            "tape_sum": tape_sum,
            "pm_volume": volume,
            "pm_volume_source": vol_src,
            "real_print_high": max((p["price"] for p in real), default=None),
            "real_print_low": min((p["price"] for p in real), default=None),
            "real_prints": len(real),
            "tape_print_gaps": [],
        })

    if info:
        rec.update({
            "info_price": info["price"], "info_pct": info["pct"], "info_ts": info["ts"],
            "info_bid": info["bid"], "info_ask": info["ask"],
            "secondary_close": info["secondary_close"], "market_status": info["market_status"],
        })
    if cboe:
        rec.update({
            "cboe_price": cboe["price"], "cboe_close": cboe["close"],
            "cboe_last_trade_time": cboe["last_trade_time"], "cboe_timestamp": cboe["timestamp"],
        })
    if tv:
        rec.update({
            "tv_close": tv.get("close"),
            "tv_pm_pct": tv.get("premarket_change"),
            "tv_pm_high": tv.get("premarket_high"),
            "tv_pm_low": tv.get("premarket_low"),
            "tv_pm_volume": tv.get("premarket_volume"),
        })

    # ---- price selection, in priority order ----
    price = None
    price_src = None
    if info and info.get("price") is not None:
        price, price_src = info["price"], "/info primaryData (LIVE)"
        # `last == ask` means the reading is the OFFER, not an executed trade.
        if info.get("ask") is not None and abs(info["price"] - info["ask"]) < 1e-9:
            price_src += " - equals the ASK, so it is a quote not a print"
    if price is None and best and best.get("newest"):
        price = best["newest"]["price"]
        price_src = "tape last executed print (fallback)"
    rec["price"] = price
    rec["price_source"] = price_src

    # ---- the reference close, and WHICH sources agreed on it ----
    # Priority: the sweep's own focus.csv > TradingView close > Cboe close >
    # Nasdaq secondaryData (the drifting one - last, and only on its own).
    # When the universe manifest says the live sources have already rolled
    # forward to a LATER session than the denominator, their `close` is NOT a
    # contradiction - it is a different session. It is then excluded from both
    # the candidates and the conflict list.
    live_ok = focus.get("live_sources_session_valid", True)
    candidates = [("focus.csv", focus.get("close"))]
    if live_ok:
        candidates += [("tradingview", tv.get("close")),
                       ("cboe", (cboe or {}).get("close"))]
    candidates += [("nasdaq-secondaryData", rec.get("secondary_close"))]
    primary_name, primary = None, None
    for name, val in candidates:
        if val:
            primary_name, primary = name, val
            break
    agree, conflict = [], []
    for name, val in candidates:
        if not val or primary is None:
            continue
        if abs(val - primary) <= max(0.005, primary * 0.0005):
            agree.append(name)
        else:
            conflict.append("%s %.4f vs %.4f" % (name, val, primary))
    src = "+".join(agree) if agree else (primary_name or "none")
    if conflict:
        src += " (CONFLICT: " + "; ".join(conflict) + ")"
    rec["base_close"] = primary
    rec["base_close_source"] = src
    rec["base_close_conflict"] = "; ".join(conflict)

    # ---- the published gap: ALWAYS from an executed print ----
    tape_px = rec.get("tape_last_price")
    tape_gap = None
    if tape_px is not None and primary:
        tape_gap = round((tape_px / primary - 1) * 100, 3)
    rec["pm_gap_pct"] = tape_gap
    rec["pm_price"] = tape_px

    quote_px = (info or {}).get("price")
    quote_gap = None
    if quote_px is not None and primary:
        quote_gap = round((quote_px / primary - 1) * 100, 3)
    rec["quote_price"] = quote_px
    rec["quote_gap_pct"] = quote_gap

    # ---- the print that carries the gap, and its size ----
    exec_shares = rec.get("tape_last_print_vol") or 0
    rec["exec_shares"] = int(exec_shares)
    rec["exec_notional"] = round(exec_shares * tape_px, 2) if (tape_px and exec_shares) else 0

    # every print's gap, so "it crossed intraday" is a measured fact
    gaps = []
    if primary and best:
        for p in best.get("prints") or []:
            if p.get("price"):
                gaps.append(round((p["price"] / primary - 1) * 100, 3))
    rec["tape_print_gaps"] = gaps
    rec["max_tape_gap_pct"] = max((abs(g) for g in gaps), default=None)

    # the reported pre-market range, as gaps
    for side in ("pm_high", "pm_low"):
        px = rec.get(side + "_px")
        rec[side + "_gap_pct"] = round((px / primary - 1) * 100, 3) if (px and primary) else None

    rec["stylists"] = focus.get("stylists") or ""
    rec["origins"] = focus.get("origins") or ""

    return sym, rec


def _verdict(rec: dict, gap_trigger: float, volume_floor: int,
             min_exec: int) -> tuple[str, str]:
    """The fixed vocabulary. Precedence is explicit, because the order IS the
    meaning: a name that printed nothing cannot be a borderline anything."""
    gap = rec.get("pm_gap_pct")
    quote_gap = rec.get("quote_gap_pct")
    exec_shares = rec.get("exec_shares") or 0
    volume = rec.get("pm_volume") or 0
    has_print = rec.get("tape_last_price") is not None

    if not has_print:
        return "NO_PRINT", ("no executed pre-market print: the quote is not a market "
                            "(no tape print to measure)")

    crossed_now = gap is not None and abs(gap) >= gap_trigger
    crossed_quote = quote_gap is not None and abs(quote_gap) >= gap_trigger
    crossed_session = False
    for key in ("max_tape_gap_pct", "pm_high_gap_pct", "pm_low_gap_pct"):
        v = rec.get(key)
        if v is not None and abs(v) >= gap_trigger:
            crossed_session = True
            break

    if crossed_now and volume >= volume_floor and exec_shares >= min_exec:
        return "FLAGGED", ("gap %.2f%% >= %.1f%% on %s executed shares and %s pre-market "
                           "shares" % (gap, gap_trigger, "{:,}".format(exec_shares),
                                       "{:,}".format(int(volume))))

    if crossed_now:
        thin = []
        if exec_shares < min_exec:
            thin.append("exec_shares %s < %s" % ("{:,}".format(int(exec_shares)),
                                                  "{:,}".format(min_exec)))
        if volume < volume_floor:
            thin.append("pre-market volume %s < %s" % ("{:,}".format(int(volume)),
                                                       "{:,}".format(volume_floor)))
        return "BORDERLINE_THIN", ("gap %.2f%% printed, but %s - a rounding artifact, not a "
                                   "market" % (gap, " and ".join(thin)))

    if crossed_quote:
        return "BORDERLINE_TAPE_ONLY", ("above the bar on the live quote (%.2f%%) and below it "
                                         "on the executed tape (%.2f%%): a quote is not a market"
                                         % (quote_gap, gap))

    if crossed_session:
        legs = []
        if rec.get("max_tape_gap_pct") is not None:
            legs.append("pre-market high/low reached %.2f%%" % rec["max_tape_gap_pct"])
        if rec.get("pm_high_gap_pct") is not None and abs(rec["pm_high_gap_pct"]) >= gap_trigger:
            legs.append("pre-market high %.2f%%" % rec["pm_high_gap_pct"])
        if rec.get("pm_low_gap_pct") is not None and abs(rec["pm_low_gap_pct"]) >= gap_trigger:
            legs.append("pre-market low %.2f%%" % rec["pm_low_gap_pct"])
        return "BORDERLINE_INTRADAY", ("crossed the bar intraday (%s) but is not there at the "
                                        "snapshot (%.2f%%)" % ("; ".join(legs) or "it touched "
                                                                "the bar", gap))

    return "BELOW", ("gap %.2f%% is below the %.1f%% bar" % (gap if gap is not None else 0.0,
                                                             gap_trigger))


def _fmt(v, nd=2):
    if v is None:
        return ""
    return ("{:,." + str(nd) + "f}").format(v)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Cache-safe pre-market prices for the Focus list")
    p.add_argument("--symbols", default="", help="comma-separated tickers")
    p.add_argument("--from-csv", default=None,
                   help="the prior sweep's focus.csv (tickers + reference close + provenance)")
    p.add_argument("--out-dir", default=".", help="where to write the JSON + markdown + CSV")
    p.add_argument("--pulls", type=int, default=4, help="tape pulls per symbol (N >= 4)")
    p.add_argument("--gap-trigger", type=float, default=GAP_TRIGGER_PCT,
                   help="gap trigger in percent")
    p.add_argument("--volume-floor", type=int, default=MIN_PM_VOLUME_SHARES,
                   help="pre-market volume floor")
    p.add_argument("--min-exec", type=int, default=MIN_EXECUTED_SHARES,
                   help="minimum executed shares behind the print that carries the gap")
    p.add_argument("--csv-name", default="pre-market-gapper.csv",
                   help="name of the contract CSV written into --out-dir")
    p.add_argument("--cboe", action="store_true", default=True,
                   help="cross-check with the Cboe delayed-quote CDN (default on)")
    p.add_argument("--no-cboe", dest="cboe", action="store_false")
    p.add_argument("--no-tv", dest="tv", action="store_false", default=True,
                   help="cross-check with the TradingView america scanner (default on)")
    p.add_argument("--universe-manifest", default=None,
                   help="the _universe.json written by premarket_universe.py. It is "
                        "AUTHORITATIVE: the universe's date, the denominator session and "
                        "the reference close all come from it. A manifest whose status "
                        "is FAIL aborts the run.")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    manifest = None
    if args.universe_manifest:
        try:
            with open(args.universe_manifest, encoding="utf-8") as fh:
                manifest = json.load(fh)
        except Exception as e:
            print("premarket_pull: the universe manifest could not be read (%s) - the "
                  "universe is not proven, so there is no run" % type(e).__name__,
                  file=sys.stderr)
            return 3
        if str(manifest.get("status", "")).startswith("FAIL"):
            print("premarket_pull: the universe manifest reports FAIL (%s) - refusing to "
                  "scan an unproven universe" % "; ".join(manifest.get("failures", [])),
                  file=sys.stderr)
            return 3

    if args.pulls < 4:
        print("warning: --pulls < 4 weakens the max-timestamp defence against the stale cache",
              file=sys.stderr)

    syms = _load_symbols(args)
    if not syms:
        print("no symbols given (use --symbols or --from-csv)", file=sys.stderr)
        return 2

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    session = (manifest or {}).get("expected_prior_session")
    sweep_date = (manifest or {}).get("universe_date")
    focus_rows = (_load_focus(args.from_csv, session, sweep_date)
                  if args.from_csv else {})
    if manifest:
        live_valid = manifest.get("tv_cboe_session_valid", True)
        # the manifest's reference closes are authoritative
        for sym, mrec in (manifest.get("reference_closes") or {}).items():
            row = focus_rows.setdefault(sym, {})
            if mrec.get("ref_close") is not None:
                row["close"] = mrec["ref_close"]
                row["close_col"] = mrec.get("ref_close_source")
                row["universe_date"] = sweep_date
                row["ref_close_date"] = session
                row["universe_source"] = mrec.get("ref_close_source")
                row["live_sources_session_valid"] = live_valid
    tv_rows = _fetch_tv(syms) if args.tv else {}

    records: dict[str, dict] = {}
    failures = 0
    with ThreadPoolExecutor(max_workers=6) as ex:
        for sym, rec in ex.map(
                lambda s: _one(s, args, focus_rows.get(s), tv_rows.get(s)), syms):
            if rec:
                records[sym] = rec
            else:
                failures += 1

    for sym, rec in records.items():
        verdict, reason = _verdict(rec, args.gap_trigger, args.volume_floor, args.min_exec)
        rec["verdict"] = verdict
        rec["flag_reason"] = reason
        rec["flagged"] = verdict == "FLAGGED"

    flagged = [r for r in records.values() if r.get("flagged")]
    payload = {
        "contract": CONTRACT_VERSION,
        "requested": len(syms),
        "ok": len(records),
        "failed": failures,
        "gap_trigger": args.gap_trigger,
        "volume_floor": args.volume_floor,
        "min_executed_shares": args.min_exec,
        "pulls_per_symbol": args.pulls,
        "flagged": len(flagged),
        "records": records,
    }
    (out_dir / "_premarket-pull.json").write_text(json.dumps(payload, indent=2))

    # ---- the CONTRACT csv ----
    with open(out_dir / args.csv_name, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for sym in syms:
            r = records.get(sym)
            if not r:
                continue
            w.writerow({
                "ticker": sym,
                "ref_close": _fmt(r.get("base_close"), 4),
                "universe_date": (focus_rows.get(sym, {}) or {}).get("universe_date") or "",
                "ref_close_date": (focus_rows.get(sym, {}) or {}).get("ref_close_date") or "",
                "universe_source": (focus_rows.get(sym, {}) or {}).get("universe_source") or "",
                "ref_close_source": r.get("base_close_source") or "",
                "pm_price": _fmt(r.get("pm_price"), 4),
                "pm_gap_pct": _fmt(r.get("pm_gap_pct"), 3),
                "exec_shares": r.get("exec_shares", 0),
                "exec_notional": _fmt(r.get("exec_notional"), 2),
                "pm_volume": r.get("pm_volume") if r.get("pm_volume") is not None else "",
                "pm_volume_source": r.get("pm_volume_source") or "",
                "quote_price": _fmt(r.get("quote_price"), 4),
                "quote_gap_pct": _fmt(r.get("quote_gap_pct"), 3),
                "bid": _fmt(r.get("info_bid"), 4),
                "ask": _fmt(r.get("info_ask"), 4),
                "pm_high": r.get("pm_high") or "",
                "pm_low": r.get("pm_low") or "",
                "pm_high_gap_pct": _fmt(r.get("pm_high_gap_pct"), 3),
                "pm_low_gap_pct": _fmt(r.get("pm_low_gap_pct"), 3),
                "tv_pm_pct": _fmt(r.get("tv_pm_pct"), 3),
                "tv_pm_volume": r.get("tv_pm_volume") if r.get("tv_pm_volume") is not None else "",
                "stylists": r.get("stylists") or "",
                "origins": r.get("origins") or "",
                "verdict": r.get("verdict") or "",
                "flag_reason": r.get("flag_reason") or "",
            })

    # ---- the helper markdown ----
    lines = [
        "# Pre-market pull",
        "",
        "_Cache-safe pre-market prices. The tape is pulled %d times per symbol and the "
        "payload with the newest internal timestamp wins, because Nasdaq's extended-trading "
        "endpoint is served from a shared HTTP cache that can return hours-old snapshots for "
        "the same URL. The published gap comes from the tape's last EXECUTED print; the live "
        "quote is published separately; Cboe and TradingView supply independent, "
        "explicitly-timestamped cross-checks._" % args.pulls,
        "",
        "| Ticker | Close | Gap % (tape) | Exec shares | Exec notional | PM volume | Quote % | "
        "Verdict | Price source | Tape newest | Tape vintages seen | Cboe | Mkt |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for sym in syms:
        r = records.get(sym)
        if not r:
            lines.append(f"| {sym} | — | — | — | — | — | — | — | _no quote_ | — | — | — | — |")
            continue
        lines.append(
            "| **{sym}** | {close} | {gap} | {es} | {en} | {vol} | {qgap} | {verdict} | {src} | "
            "{newest} | {vint} | {cboe} | {mkt} |".format(
                sym=sym,
                close=("%.4f" % r["base_close"]) if r.get("base_close") else "—",
                gap=("%+.2f%%" % r["pm_gap_pct"]) if r.get("pm_gap_pct") is not None else "—",
                es="{:,}".format(r.get("exec_shares") or 0),
                en=("{:,.0f}".format(r["exec_notional"])) if r.get("exec_notional") else "—",
                vol=("{:,.0f}".format(r["pm_volume"])) if r.get("pm_volume") else "—",
                qgap=("%+.2f%%" % r["quote_gap_pct"]) if r.get("quote_gap_pct") is not None else "—",
                verdict=r.get("verdict") or "—",
                src=r.get("price_source") or "—",
                newest=r.get("tape_newest_print") or "—",
                vint=", ".join(r.get("tape_vintages") or []) or "—",
                cboe=("%.2f" % r["cboe_price"]) if r.get("cboe_price") is not None else "—",
                mkt=r.get("market_status") or "—",
            )
        )

    gaps = [abs(r["pm_gap_pct"]) for r in records.values() if r.get("pm_gap_pct") is not None]
    margin = ""
    if gaps:
        worst = max(gaps)
        margin = (f"\n_Widest absolute gap on any source: {worst:.2f}% against a "
                  f"{args.gap_trigger:.2f}% trigger — a {args.gap_trigger / worst:.2f}x margin, "
                  f"so the flag decision is immune to whichever cached vintage a source "
                  f"returns._\n" if worst > 0 else "")
    lines += ["", margin, f"_{len(records)} of {len(syms)} symbols priced"
              + (f"; {failures} missing." if failures else "."), ""]
    (out_dir / "premarket-pull.md").write_text("\n".join(lines))

    # ---- the marker line the artifact must carry ----
    marker = ("_contract: %s · flagged: %d · scanned: %d · gate: |gap|>=%.1f%% and "
              "pm_volume>=%s and exec_shares>=%s · reference close: %s_"
              % (CONTRACT_VERSION, len(flagged), len(records), args.gap_trigger,
                 "{:,}".format(args.volume_floor), "{:,}".format(args.min_exec),
                 "prior sweep focus.csv"))
    payload["marker_line"] = marker
    (out_dir / "_premarket-pull.json").write_text(json.dumps(payload, indent=2))

    if not args.quiet:
        print(marker)
        print("premarket pull: %d/%d priced, %d missing, %d flagged -> %s"
              % (len(records), len(syms), failures, len(flagged), out_dir / args.csv_name))
    return 0


if __name__ == "__main__":
    sys.exit(main())
