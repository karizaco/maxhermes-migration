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
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# The tape's clock is the EXCHANGE's clock (ET). The wall clock has to be read
# in the same zone or every lag is off by the UTC offset.
ET = ZoneInfo("America/New_York")

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
# The capability marker moves with every shape change: the fetch ladder DEMANDS
# it, so a cached OLD copy of this script can never win and then write the OLD
# artifact shape (which the checker would fail for no visible reason).
CONTRACT_VERSION = "premarket-artifact-v6"
PULL_MARKER = "premarket-pull-v2"       # adaptive pulls, tape lag, driver class, market ladder
RENDER_MARKER = "premarket-render-v1"   # the renderer that owns the contract files
GAP_TRIGGER_PCT = 4.0        # unchanged since the routine was written
MIN_PM_VOLUME_SHARES = 50_000  # unchanged
MIN_EXECUTED_SHARES = 25     # the print that carries the gap must have size behind it

# ---- the driver vocabulary (published as a FIELD, never as prose) -----------
# WHY: a gap that clears the bar is not automatically a setup. MARA cleared the
# 4%/50,000/25 gate on 2026-11-12 and was a BITCOIN gap, not a company event;
# NBIS and CRWV were an index/news drag. Naming the driver is what stops a
# beta gap being read as a stock-pick.
#   CATALYST      a confirmed issuer/wire catalyst explains the move
#   CRYPTO_BETA   a crypto-linked equity tracking bitcoin
#   MARKET_BETA   the gap tracks the index proxy
#   SECTOR_BETA   the gap tracks the sector proxy
#   IDIOSYNCRATIC company-specific move, no proxy and no confirmed catalyst
#   NO_MOVE       no material move to attribute
DRIVER_CLASSES = ("CATALYST", "CRYPTO_BETA", "MARKET_BETA", "SECTOR_BETA",
                  "IDIOSYNCRATIC", "NO_MOVE")

# the crypto-linked equity basket (the names whose gap is bitcoin's gap)
CRYPTO_BASKET = ("MARA", "RIOT", "CIFR", "HUT", "BTDR", "IREN", "WULF", "CLMT",
                 "GLXY", "HIVE", "BITF", "SGHC", "ARBK", "BKSY", "CORZ", "TREE")

# TradingView sector -> the ETF that prices it. Used as the SECTOR proxy.
SECTOR_ETF = {
    "Technology Services": "XLK", "Electronic Technology": "SMH",
    "Health Technology": "XLV", "Health Services": "XLV",
    "Consumer Services": "XLY", "Consumer Durables": "XLY",
    "Retail Trade": "XLY", "Communications": "XLC",
    "Producer Manufacturing": "XLI", "Industrial Services": "XLI",
    "Transportation": "XLI", "Distribution Services": "XLI",
    "Energy": "XLE", "Finance": "XLF", "Utilities": "XLU",
    "Real Estate": "XLRE", "Materials": "XLB", "Miscellaneous": "XLY",
    "Defense": "XLI", "Government": "XLI",
}

# the index + sector proxies, fetched in the SAME TradingView call as the Focus
# names (the `in_range` filter takes a LIST, so it costs no extra request)
PROXY_SYMBOLS = ("SPY", "QQQ", "IWM", "XLK", "XLV", "XLY", "XLC", "XLI", "XLE",
                 "XLF", "XLU", "XLRE", "XLB", "SMH")

COINGECKO_CHART = "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart"

# a gap within this many points of a proxy is that proxy's move, not the stock's
MARKET_BETA_TOL = 1.0
SECTOR_BETA_TOL = 1.5

VERDICTS = (
    "FLAGGED",              # clears on the tape AND size
    "BORDERLINE_THIN",      # the bar was printed, but the market behind it is too thin
    "BORDERLINE_TAPE_ONLY",  # clears on the live quote, not on the executed tape
    "BORDERLINE_INTRADAY",   # crossed the bar during the session, not at the snapshot
    "NO_PRINT",              # no executed print at all
    "BELOW",                 # printed, and below the bar on every reading
)

# The CONTRACT csv is written by the RENDERER (render_premarket_artifact.py),
# not here: one owner per output file, so the csv and the markdown can never
# disagree about a column set. This script owns the NUMBERS
# (_premarket-pull.json) and the helper table (premarket-pull.md).


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


def _best_tape(sym: str, pulls: int, min_pulls: int = 2):
    """Pull until the cached vintage stops CHANGING (min `min_pulls`, max `pulls`).

    The max-newest-timestamp rule is still the defence against a stale cache: a
    stale vintage can be hours old, but it can never carry a NEWER internal
    timestamp, so it can never win the comparison.

    Measured 2026-11-12: every one of the 48 responses carried a cache-hit and
    **10 of 12 symbols returned a SINGLE vintage across all four pulls**, so the
    rule had nothing to choose from and 36 of the 48 requests were redundant
    (the endpoint answers in 1.2-3.3 s, so that is ~9 s of wall clock). The loop
    therefore stops as soon as two consecutive pulls AGREE, and keeps going
    while they differ - which is exactly the case the rule exists for (a
    rotating cache serving different vintages).
    """
    seen = []
    last_sig = None
    for i in range(pulls):
        rec = None
        for ac in ASSET_CLASSES:
            cand = _pull_tape(sym, bust=(i % 2 == 0), asset_class=ac)
            if cand and (cand.get("prints") or cand.get("consol_raw")):
                cand["asset_class"] = ac
                rec = cand
                break
        if rec:
            seen.append(rec)
            sig = rec["newest"]["minutes"] if rec.get("newest") else None
            if sig is not None and sig == last_sig and len(seen) >= min_pulls:
                break  # the cache is stable: another pull cannot change the answer
            last_sig = sig if sig is not None else last_sig
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


def _now_et():
    return datetime.now(ET)


def _lag_minutes(clock: str | None):
    """How many minutes the tape's newest print is BEHIND the wall clock (ET).

    This is the number that makes staleness visible. Measured 2026-11-12: the
    newest print was 14-24 minutes old for 11 of 12 names and 86 minutes old for
    one - and nothing in the artifact said so, because a stable cache returns
    the SAME vintage however many times it is asked.
    """
    if not clock:
        return None
    m = re.match(r"^(\d{2}):(\d{2}):(\d{2})$", str(clock).strip())
    if not m:
        return None
    now = _now_et()
    stamp = now.replace(hour=int(m.group(1)), minute=int(m.group(2)),
                        second=int(m.group(3)), microsecond=0)
    if stamp > now:
        stamp -= timedelta(days=1)
    return round((now - stamp).total_seconds() / 60.0, 1)


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


def _tv_post(body):
    req = urllib.request.Request(TV_SCAN, data=json.dumps(body).encode(),
                                 headers={**UA, "Content-Type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=30).read())
    except Exception:
        return {}


def _fetch_tv(symbols):
    """ONE TradingView america-scanner call for the Focus list AND the proxies.

    Gives the second independent reference close, a pre-market cross-check, the
    sector (for the SECTOR proxy) and `earnings_release_date` (for the forward
    calendar). `premarket_price` is null for US names - use `premarket_change`
    and `premarket_high`/`premarket_low`.

    A filter with `name` + `in_range` works; bare tickers in `symbols` + a
    filter returns 0 rows (measured 2026-11-03). The `in_range` right side is a
    LIST, so the index and sector proxies ride along in the SAME call - they
    cost no extra request, which is why the driver classification is free.

    The `type == stock` filter is applied CLIENT-side, not server-side: the
    proxies are ETFs (`type: fund`) and a server-side type filter would drop
    every one of them.
    """
    names = list(symbols) + [p for p in PROXY_SYMBOLS if p not in symbols]
    if not names:
        return {}, {}
    cols = ["name", "close", "premarket_change", "premarket_high", "premarket_low",
            "premarket_volume", "description", "sector", "type",
            "earnings_release_date", "average_volume_30d_calc"]
    body = {
        "filter": [{"left": "name", "operation": "in_range", "right": names}],
        "columns": cols,
        "range": [0, len(names) + 5],
    }
    res = _tv_post(body)
    stocks, proxies = {}, {}
    for row in res.get("data") or []:
        d = row.get("d") or []
        if not d:
            continue
        sym = str(d[0]).upper()
        rec = {
            "close": _num(d[1]),
            "premarket_change": _num(d[2]),
            "premarket_high": _num(d[3]),
            "premarket_low": _num(d[4]),
            "premarket_volume": _num(d[5]),
            "description": d[6] if len(d) > 6 else "",
            "sector": d[7] if len(d) > 7 else "",
            "type": d[8] if len(d) > 8 else "",
            "earnings_release_date": d[9] if len(d) > 9 else None,
            "average_volume_30d": _num(d[10]) if len(d) > 10 else None,
        }
        if sym in PROXY_SYMBOLS:
            proxies[sym] = rec
        elif rec.get("type") == "stock" or sym in symbols:
            stocks[sym] = rec
    return stocks, proxies


def _fetch_market_ladder(min_gap: float = GAP_TRIGGER_PCT,
                         min_mcap: float = 200_000_000,
                         min_pmvol: int = 20_000):
    """The MARKET's pre-market gap leaders - the event book.

    The Focus list is a momentum screen built on the PREVIOUS session, so it
    structurally cannot contain a name whose move has not happened yet. Measured
    2026-11-12: the Focus book held 0 of the day's real movers (LUNR +11.5%,
    TTEK +11.1%, NBIS -13.5%, CRWV -10.0%).

    The filters are NOT optional. Pulled raw (`premarket_change >= 4` only) the
    list is 79 up / 313 down and the top of it is PLCE +489% ($0.1985) plus a
    wall of single-stock leveraged ETFs (`Tradr 2X Short NBIS Daily ETF`) whose
    move is a DERIVATIVE of the underlying, not a gap anyone can trade.
    `type = stock` + a market-cap floor + a pre-market-volume floor cuts it to
    real companies.

    Two scans (up and down) because a scanner filter is AND-ed, so one scan
    cannot express "gap >= 4% OR gap <= -4%".
    """
    cols = ["name", "description", "close", "premarket_change", "premarket_volume",
            "premarket_high", "premarket_low", "earnings_release_date",
            "market_cap_basic", "sector"]
    out = []
    for op, right in (("egreater", min_gap), ("eless", -min_gap)):
        body = {
            "filter": [{"left": "premarket_change", "operation": op, "right": right},
                       {"left": "premarket_volume", "operation": "egreater",
                        "right": min_pmvol},
                       {"left": "market_cap_basic", "operation": "egreater",
                        "right": int(min_mcap)},
                       {"left": "type", "operation": "equal", "right": "stock"}],
            "columns": cols,
            # the canonical sort form. An ARRAY sort 400s; {"column","order"}
            # returns 200 with UNSORTED rows.
            "sort": {"sortBy": "name", "sortOrder": "asc"},
            "range": [0, 300],
        }
        res = _tv_post(body)
        for row in res.get("data") or []:
            d = row.get("d") or []
            if not d:
                continue
            out.append({
                "ticker": str(d[0]).upper(),
                "description": d[1] if len(d) > 1 else "",
                "close": _num(d[2]),
                "gap_pct": _num(d[3]),
                "pm_volume": _num(d[4]),
                "pm_high": _num(d[5]),
                "pm_low": _num(d[6]),
                "earnings_release_date": d[7] if len(d) > 7 else None,
                "market_cap": _num(d[8]),
                "sector": d[9] if len(d) > 9 else "",
            })
    out.sort(key=lambda r: -(abs(r.get("gap_pct") or 0)))
    return out


def _fetch_crypto_proxy():
    """Bitcoin's move over the EQUITY overnight window (16:00 ET yesterday -> now).

    CoinGecko's rolling 24h change is the wrong window for a pre-market gap
    (it spans two equity sessions), so the chart is used and the change is
    measured from the timestamp nearest the prior 16:00 ET close.
    """
    payload, _ = _get(COINGECKO_CHART + "?vs_currency=usd&days=2")
    if not payload:
        return None
    pts = payload.get("prices") or []
    if len(pts) < 3:
        return None
    now = _now_et()
    target = (now - timedelta(days=1)).replace(hour=16, minute=0, second=0, microsecond=0)
    if target > now:
        target -= timedelta(days=1)
    base = min(pts, key=lambda p: abs(p[0] / 1000.0 - target.timestamp()))
    last = pts[-1]
    if not base[1]:
        return None
    return {
        "usd": round(last[1], 2),
        "overnight_pct": round((last[1] / base[1] - 1) * 100, 2),
        "from_et": datetime.fromtimestamp(base[0] / 1000.0, ET).strftime("%m-%d %H:%M ET"),
    }


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
                # the PRIOR session's own move, from the sweep's own CSV. It
                # costs no extra call and it tells the reader whether today's
                # gap is a CONTINUATION (the name was already running) or a
                # REVERSAL - which changes how the gap should be read.
                # `today_change` is the sweep's OWN session (the denominator
                # session); `chg_pct_resolved` is the screen's T+1 data date,
                # i.e. a DIFFERENT session, so it is only the fallback.
                psc, psc_col = None, None
                for key in ("today_change", "chg_pct_resolved"):
                    if row.get(key) and _num(row[key]) is not None:
                        psc, psc_col = _num(row[key]), key
                        break
                out[sym] = {
                    "close": close,
                    "close_col": close_col,
                    "prior_session_change": psc,
                    "prior_session_change_col": psc_col,
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


def _apply_tape(rec: dict, best, seen):
    """Write every TAPE-derived field onto `rec`.

    Split out of `_one` so the RE-PULL WAVE can reuse it: a second wave that
    finds a newer print must produce exactly the same shape as the first, or
    the merged record would be a mixture of two contracts.
    """
    rec["tape_pulls"] = len(seen)
    rec["tape_vintages"] = sorted({s["newest"]["time"] for s in seen if s.get("newest")})
    rec["cache_hits"] = sorted({str(s.get("cache_hit")) for s in seen if s.get("cache_hit")})
    rec["tape_vintage_count"] = len(rec["tape_vintages"])
    if not best:
        return rec
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

    newest_clock = best["newest"]["time"] if best.get("newest") else None
    rec.update({
        "tape_newest_print": newest_clock,
        "tape_lag_min": _lag_minutes(newest_clock),
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
    return rec


def _compute_gap_fields(rec: dict, primary):
    """Every gap, the print that carries it, and the range - from `primary`."""
    tape_px = rec.get("tape_last_price")
    rec["pm_gap_pct"] = round((tape_px / primary - 1) * 100, 3) if (tape_px and primary) else None
    rec["pm_price"] = tape_px
    quote_px = rec.get("quote_price")
    rec["quote_gap_pct"] = round((quote_px / primary - 1) * 100, 3) if (quote_px and primary) else None

    exec_shares = rec.get("tape_last_print_vol") or 0
    rec["exec_shares"] = int(exec_shares)
    rec["exec_notional"] = round(exec_shares * tape_px, 2) if (tape_px and exec_shares) else 0

    # every print's gap, so "it crossed intraday" is a measured fact
    gaps = []
    for p in rec.pop("_prints", []) or []:
        if p.get("price") and primary:
            gaps.append(round((p["price"] / primary - 1) * 100, 3))
    rec["tape_print_gaps"] = gaps
    rec["max_tape_gap_pct"] = max((abs(g) for g in gaps), default=None)
    for side in ("pm_high", "pm_low"):
        px = rec.get(side + "_px")
        rec[side + "_gap_pct"] = round((px / primary - 1) * 100, 3) if (px and primary) else None
    return rec


def _one(sym: str, args, focus: dict | None = None,
         tv: dict | None = None) -> tuple[str, dict | None]:
    best, seen = _best_tape(sym, args.pulls)
    info = _fetch_info(sym)
    cboe = _fetch_cboe(sym) if args.cboe else None
    focus = focus or {}
    tv = tv or {}

    if best is None and info is None:
        return sym, None

    rec: dict = {"ticker": sym}
    _apply_tape(rec, best, seen)
    rec["_prints"] = (best or {}).get("prints") or []

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
            "tv_sector": tv.get("sector") or "",
            "tv_earnings_release_date": tv.get("earnings_release_date"),
            "tv_avg_volume_30d": tv.get("average_volume_30d"),
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
    # The label of the universe-derived close comes from the MANIFEST, not from
    # the literal "focus.csv": when the sweep published its Focus list without a
    # close column, the close comes from the independent sources and calling it
    # "focus.csv" would publish a source that does not exist. (Measured
    # 2026-11-10: the 2026-11-09 sweep published focus.md but no focus.csv.)
    label = (focus.get("close_col") or "focus.csv").split(":")[0]
    candidates = [(label, focus.get("close"))]
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
            if name not in agree:
                agree.append(name)
        else:
            conflict.append("%s %.4f vs %.4f" % (name, val, primary))
    # the manifest's independent confirmations (e.g. session-exact Nasdaq history)
    # belong in the published source string
    for lab in (focus.get("confirmed_by") or []):
        if lab not in agree:
            agree.append(lab)
    src = "+".join(agree) if agree else (primary_name or "none")
    if conflict:
        src += " (CONFLICT: " + "; ".join(conflict) + ")"
    rec["base_close"] = primary
    rec["base_close_source"] = src
    rec["base_close_conflict"] = "; ".join(conflict)

    # ---- the published gap: ALWAYS from an executed print ----
    rec["quote_price"] = (info or {}).get("price")
    _compute_gap_fields(rec, primary)

    rec["stylists"] = focus.get("stylists") or ""
    rec["origins"] = focus.get("origins") or ""
    rec["prior_session_change"] = focus.get("prior_session_change")
    rec["prior_session_change_col"] = focus.get("prior_session_change_col")
    # the universe's own session, the denominator's session and WHERE the close
    # came from - per row, so the renderer never has to guess them
    rec["universe_date"] = focus.get("universe_date")
    rec["ref_close_date"] = focus.get("ref_close_date")
    rec["universe_source"] = focus.get("universe_source")

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


def _classify_drivers(records: dict, proxies: dict, crypto: dict | None,
                      catalysts: dict | None = None, ladder: list | None = None):
    """Name the driver of every gap. Published as a FIELD, never as prose.

    WHY this exists: a gap that clears the bar is not automatically a setup.
    Measured 2026-11-12 - MARA cleared the 4%/50,000/25 gate and was a BITCOIN
    gap (BTC -1.51% overnight), not a company event; NBIS and CRWV were an
    index/news drag. Without a driver field a beta gap reads exactly like a
    stock-pick, which is the false positive this routine can still afford.

    The comparison is made on TradingView's `premarket_change` for BOTH the name
    and the proxy, so the two numbers come from the same snapshot of the same
    feed; the published gap stays the Nasdaq tape's.

    Vocabulary: CATALYST > CRYPTO_BETA > MARKET_BETA > SECTOR_BETA >
    IDIOSYNCRATIC, and NO_MOVE when there is nothing to attribute.
    """
    market = (proxies.get("SPY") or {}).get("premarket_change")
    for sym, rec in records.items():
        gap = rec.get("tv_pm_pct")
        if gap is None:
            gap = rec.get("pm_gap_pct")
        cat = (catalysts or {}).get(sym) or {}
        cls, basis = None, None
        if gap is None:
            cls, basis = "NO_MOVE", "no gap to attribute"
        else:
            # The STRUCTURAL driver is tested FIRST: a name that tracks a proxy
            # moves with that proxy, and a trader needs to know that before the
            # news. A confirmed catalyst on a beta name is appended to the
            # basis, not thrown away.
            beta = None
            if abs(gap) >= 1.0:
                if sym in CRYPTO_BASKET and crypto and crypto.get("overnight_pct") is not None:
                    c = crypto["overnight_pct"]
                    if (gap > 0) == (c > 0):
                        beta = "CRYPTO_BETA"
                        basis = "bitcoin %+.2f%% overnight (from %s)" % (c, crypto.get("from_et"))
                if beta is None and market is not None and abs(gap - market) <= MARKET_BETA_TOL:
                    beta, basis = "MARKET_BETA", "SPY %+.2f%% pre-market" % market
                if beta is None:
                    sector = rec.get("tv_sector") or ""
                    etf = SECTOR_ETF.get(sector)
                    pv = (proxies.get(etf) or {}).get("premarket_change") if etf else None
                    if pv is not None and abs(gap - pv) <= SECTOR_BETA_TOL:
                        beta, basis = "SECTOR_BETA", "%s %+.2f%% pre-market (%s)" % (etf, pv, sector)
            if beta:
                cls = beta
                if cat.get("confirmed"):
                    basis += "; confirmed catalyst: %s" % (cat.get("source") or "")
            elif cat.get("confirmed"):
                cls = "CATALYST"
                basis = cat.get("source") or "confirmed issuer/wire catalyst"
            elif abs(gap) < 1.0:
                cls, basis = "NO_MOVE", "gap %.2f%% - under 1%%, nothing to attribute" % gap
            else:
                cls = "IDIOSYNCRATIC"
                basis = "no proxy within %.1fpp of %.2f%%" % (SECTOR_BETA_TOL, gap)
        rec["driver_class"] = cls
        rec["driver_basis"] = basis
        rec["driver_gap_pct"] = gap
    # the MARKET LADDER gets the same treatment: a pre-market gap leader whose
    # move is the index's move is not the same trade as a company-specific one.
    for row in (ladder or []):
        fake = {"tv_pm_pct": row.get("gap_pct"), "tv_sector": row.get("sector") or ""}
        _classify_drivers({row.get("ticker"): fake}, proxies, crypto, catalysts)
        row["driver_class"] = fake.get("driver_class")
        row["driver_basis"] = fake.get("driver_basis")
    return records


def _fmt(v, nd=2):
    if v is None:
        return ""
    return ("{:,." + str(nd) + "f}").format(v)


def _build_marker(payload: dict, args) -> str:
    recs = payload.get("records") or {}
    flagged = sum(1 for r in recs.values() if r.get("verdict") == "FLAGGED")
    src = "prior sweep focus.csv"
    return ("_contract: %s · flagged: %d · scanned: %d · gate: |gap|>=%.1f%% and "
            "pm_volume>=%s and exec_shares>=%s · reference close: %s · pull: %s · "
            "renderer: %s_"
            % (CONTRACT_VERSION, flagged, len(recs), args.gap_trigger,
               "{:,}".format(args.volume_floor), "{:,}".format(args.min_exec),
               src, PULL_MARKER, RENDER_MARKER))


def _write_helper_md(payload: dict, out_dir: Path, args, syms):
    recs = payload.get("records") or {}
    lines = [
        "# Pre-market pull",
        "",
        "_Cache-safe pre-market prices. The tape is pulled until the cached vintage "
        "STOPS CHANGING (min 2, max %d) and the payload with the newest internal "
        "timestamp wins, because Nasdaq's extended-trading endpoint is served from a "
        "shared HTTP cache that can return hours-old snapshots for the same URL. The "
        "published gap comes from the tape's last EXECUTED print; the live quote is "
        "published separately; Cboe and TradingView supply independent, "
        "explicitly-timestamped cross-checks. `tape_lag_min` is how many minutes the "
        "newest print is BEHIND the wall clock - the number that makes staleness "
        "visible._" % args.pulls,
        "",
        "| Ticker | Close | Gap % (tape) | Exec shares | Exec notional | PM volume | "
        "Quote % | Verdict | Driver | Tape newest | Lag (min) | Pulls | Vintages | Cboe | Mkt |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for sym in syms:
        r = recs.get(sym)
        if not r:
            lines.append(f"| {sym} | — | — | — | — | — | — | — | — | — | — | — | — | — | — |")
            continue
        lines.append(
            "| **{sym}** | {close} | {gap} | {es} | {en} | {vol} | {qgap} | {verdict} | "
            "{driver} | {newest} | {lag} | {pulls} | {vint} | {cboe} | {mkt} |".format(
                sym=sym,
                close=("%.4f" % r["base_close"]) if r.get("base_close") else "—",
                gap=("%+.2f%%" % r["pm_gap_pct"]) if r.get("pm_gap_pct") is not None else "—",
                es="{:,}".format(r.get("exec_shares") or 0),
                en=("{:,.0f}".format(r["exec_notional"])) if r.get("exec_notional") else "—",
                vol=("{:,.0f}".format(r["pm_volume"])) if r.get("pm_volume") else "—",
                qgap=("%+.2f%%" % r["quote_gap_pct"]) if r.get("quote_gap_pct") is not None else "—",
                verdict=r.get("verdict") or "—",
                driver=r.get("driver_class") or "—",
                newest=r.get("tape_newest_print") or "—",
                lag=("%.0f" % r["tape_lag_min"]) if r.get("tape_lag_min") is not None else "—",
                pulls=r.get("tape_pulls") or "—",
                vint=", ".join(r.get("tape_vintages") or []) or "—",
                cboe=("%.2f" % r["cboe_price"]) if r.get("cboe_price") is not None else "—",
                mkt=r.get("market_status") or "—",
            )
        )
    gaps = [abs(r["pm_gap_pct"]) for r in recs.values() if r.get("pm_gap_pct") is not None]
    lags = [r["tape_lag_min"] for r in recs.values() if r.get("tape_lag_min") is not None]
    notes = []
    if gaps:
        worst = max(gaps)
        if worst > 0:
            notes.append("_Widest absolute gap on any source: %.2f%% against a %.2f%% "
                         "trigger - a %.2fx margin, so the flag decision is immune to "
                         "whichever cached vintage a source returns._"
                         % (worst, args.gap_trigger, args.gap_trigger / worst))
    if lags:
        notes.append("_Tape lag (newest print behind the wall clock): median %.0f min, "
                     "max %.0f min._" % (sorted(lags)[len(lags) // 2], max(lags)))
    if payload.get("tape_waves"):
        notes.append("_Tape waves: " + "; ".join(
            "wave %d at %s (%d names)" % (w.get("wave"), w.get("at_et"), w.get("symbols") or 0)
            for w in payload["tape_waves"]) + "_")
    lines += [""] + ["\n".join(notes)] + [
        "", "_%d of %d symbols priced%s_" % (len(recs), len(syms),
                                             ("; %d missing" % payload.get("failed", 0))
                                             if payload.get("failed") else "."), ""]
    (out_dir / "premarket-pull.md").write_text("\n".join(lines))


def _write_payload(payload: dict, out_dir: Path, args, syms):
    payload["contract"] = CONTRACT_VERSION
    payload["pull_marker"] = PULL_MARKER
    payload["render_marker"] = RENDER_MARKER
    payload["driver_classes"] = list(DRIVER_CLASSES)
    payload["marker_line"] = _build_marker(payload, args)
    (out_dir / "_premarket-pull.json").write_text(json.dumps(payload, indent=2))
    _write_helper_md(payload, out_dir, args, syms)
    return payload["marker_line"]


def _do_repull(args, out_dir: Path) -> int:
    """The SECOND WAVE: re-pull the decision-relevant names and merge.

    Why a second wave at all: the burst of pulls protects against a ROTATING
    cache, but it cannot see a tape that is simply OLD - a stable cache returns
    the same vintage however many times it is asked (measured 2026-11-12: 10 of
    12 symbols served ONE vintage across four pulls, and the newest print was
    14-24 minutes behind the wall clock, 86 minutes for one name). A wave that
    is SPREAD across the run is what produces the divergence record the spec
    asks for.

    Only the decision-relevant names are re-pulled: a name below the near-miss
    band cannot change the flag decision, so re-pulling it buys nothing.
    Selection: |gap| >= --re-pull-min-gap OR a tape lag above --max-lag-min.
    """
    path = out_dir / "_premarket-pull.json"
    if not path.exists():
        print("premarket_pull: --re-pull needs the wave-1 %s" % path, file=sys.stderr)
        return 3
    payload = json.loads(path.read_text())
    records = payload.get("records") or {}
    if not records:
        print("premarket_pull: --re-pull found no records in %s" % path, file=sys.stderr)
        return 3

    targets = []
    for sym, rec in records.items():
        gap = abs(rec.get("pm_gap_pct") or 0.0)
        lag = rec.get("tape_lag_min")
        if gap >= args.re_pull_min_gap or (lag is not None and lag >= args.max_lag_min):
            targets.append(sym)

    def _pull_one(sym):
        return sym, _best_tape(sym, args.pulls)

    divergent = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        for sym, (best, seen) in ex.map(_pull_one, targets):
            rec = records[sym]
            old_newest = rec.get("tape_newest_print")
            new_newest = best["newest"]["time"] if (best and best.get("newest")) else None
            old_min = _clock_to_min(old_newest)
            new_min = _clock_to_min(new_newest)
            newer = new_min is not None and (old_min is None or new_min > old_min)
            rec["tape_divergent"] = bool(newer)
            rec["tape_wave2_newest"] = new_newest
            rec["tape_pulls_wave2"] = len(seen)
            if newer:
                _apply_tape(rec, best, seen)
                rec["_prints"] = (best or {}).get("prints") or []
                info = _fetch_info(sym)
                if info:
                    rec.update({"info_price": info["price"], "info_pct": info["pct"],
                                "info_ts": info["ts"], "info_bid": info["bid"],
                                "info_ask": info["ask"], "quote_price": info["price"]})
                _compute_gap_fields(rec, rec.get("base_close"))
                divergent.append(sym)
            else:
                # the lag grows with time - it must be re-stated even when the
                # tape itself did not move
                rec["tape_lag_min"] = _lag_minutes(old_newest)
            verdict, reason = _verdict(rec, args.gap_trigger, args.volume_floor,
                                        args.min_exec)
            rec["verdict"] = verdict
            rec["flag_reason"] = reason
            rec["flagged"] = verdict == "FLAGGED"

    # the LADDER is a snapshot too - refresh it in the same wave (2 requests)
    if args.ladder:
        fresh_ladder = _fetch_market_ladder(args.gap_trigger)
        if fresh_ladder:
            payload["market_ladder"] = fresh_ladder
    # and the driver classes, because a merged gap can change them
    _classify_drivers(records, payload.get("proxies") or {}, payload.get("crypto_proxy"),
                      payload.get("catalysts") or {}, payload.get("market_ladder") or [])

    waves = payload.get("tape_waves") or []
    waves.append({"wave": 2, "at_et": _now_et().strftime("%H:%M:%S ET"),
                  "symbols": len(targets), "targets": targets})
    payload["tape_waves"] = waves
    payload["records"] = records
    payload["flagged"] = sum(1 for r in records.values() if r.get("flagged"))
    payload["re_pull"] = {"min_gap": args.re_pull_min_gap, "max_lag_min": args.max_lag_min,
                          "targets": targets, "divergent": divergent}
    syms = list(records)
    marker = _write_payload(payload, out_dir, args, syms)
    if not args.quiet:
        print("premarket re-pull: %d names re-pulled, %d tape(s) moved -> %s"
              % (len(targets), len(divergent), out_dir))
        print(marker)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Cache-safe pre-market prices for the Focus list")
    p.add_argument("--symbols", default="", help="comma-separated tickers")
    p.add_argument("--from-csv", default=None,
                   help="the prior sweep's focus.csv (tickers + reference close + provenance)")
    p.add_argument("--out-dir", default=".", help="where to write the JSON + markdown")
    p.add_argument("--pulls", type=int, default=4,
                   help="MAX tape pulls per symbol (the loop stops early once the "
                        "cached vintage stops changing; min 2)")
    p.add_argument("--gap-trigger", type=float, default=GAP_TRIGGER_PCT,
                   help="gap trigger in percent")
    p.add_argument("--volume-floor", type=int, default=MIN_PM_VOLUME_SHARES,
                   help="pre-market volume floor")
    p.add_argument("--min-exec", type=int, default=MIN_EXECUTED_SHARES,
                   help="minimum executed shares behind the print that carries the gap")
    p.add_argument("--csv-name", default="pre-market-gapper.csv",
                   help="DEPRECATED - the contract csv is written by the RENDERER")
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
    p.add_argument("--context", default=None,
                   help="an optional JSON file with confirmed catalysts, e.g. "
                        "{\"LUNR\": {\"confirmed\": true, \"source\": \"issuer PR\"}}")
    p.add_argument("--no-ladder", dest="ladder", action="store_false", default=True,
                   help="skip the market-wide pre-market gap-leader scan")
    p.add_argument("--re-pull", action="store_true",
                   help="SECOND WAVE: re-pull the decision-relevant names in an existing "
                        "out-dir and merge them into _premarket-pull.json")
    p.add_argument("--re-pull-min-gap", type=float, default=2.0,
                   help="re-pull names whose |gap| is at or above this (default 2.0)")
    p.add_argument("--max-lag-min", type=float, default=45.0,
                   help="also re-pull names whose tape lag is above this (default 45)")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    if args.csv_name != "pre-market-gapper.csv":
        print("premarket_pull: --csv-name is deprecated - the contract csv is written "
              "by render_premarket_artifact.py", file=sys.stderr)
    if args.pulls < 2:
        print("premarket_pull: --pulls must be at least 2", file=sys.stderr)
        return 2

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.re_pull:
        return _do_repull(args, out_dir)

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

    syms = _load_symbols(args)
    if not syms:
        print("no symbols given (use --symbols or --from-csv)", file=sys.stderr)
        return 2

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
                row["confirmed_by"] = mrec.get("confirmed_by") or []
                row["live_sources_session_valid"] = live_valid
    tv_rows, proxies = (_fetch_tv(syms) if args.tv else ({}, {}))

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

    # the driver's name - a gap that clears the bar is not automatically a setup
    catalysts = {}
    if args.context and Path(args.context).exists():
        try:
            ctx = json.loads(Path(args.context).read_text())
            catalysts = ctx.get("catalysts") or ctx.get("confirmed_catalysts") or {}
        except Exception:
            catalysts = {}
    crypto = _fetch_crypto_proxy() if (set(CRYPTO_BASKET) & set(records)) else None
    ladder = _fetch_market_ladder(args.gap_trigger) if args.ladder else []
    _classify_drivers(records, proxies, crypto, catalysts, ladder)

    payload = {
        "contract": CONTRACT_VERSION,
        "pull_marker": PULL_MARKER,
        "render_marker": RENDER_MARKER,
        "requested": len(syms),
        "ok": len(records),
        "failed": failures,
        "gap_trigger": args.gap_trigger,
        "volume_floor": args.volume_floor,
        "min_executed_shares": args.min_exec,
        "pulls_per_symbol": args.pulls,
        "flagged": sum(1 for r in records.values() if r.get("flagged")),
        "tape_waves": [{"wave": 1, "at_et": _now_et().strftime("%H:%M:%S ET"),
                        "symbols": len(records)}],
        "proxies": {k: {"premarket_change": v.get("premarket_change"),
                        "close": v.get("close")} for k, v in proxies.items()},
        "crypto_proxy": crypto,
        "market_ladder": ladder,
        "catalysts": catalysts,
        "records": records,
    }
    marker = _write_payload(payload, out_dir, args, syms)

    if not args.quiet:
        print(marker)
        print("premarket pull: %d/%d priced, %d missing, %d flagged -> %s"
              % (len(records), len(syms), failures, payload["flagged"], out_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
