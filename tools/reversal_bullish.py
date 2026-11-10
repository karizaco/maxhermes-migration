#!/usr/bin/env python3
"""
reversal_bullish.py — Bonde "Reversal Bullish" scan for the CURRENT (live) US session.

WHY THIS EXISTS
---------------
The original routine resolved the screen date as "the latest settled date in shibui".
shibui is end-of-day, so at 15:55 ET that is YESTERDAY's bar: the routine measured
Thursday's candle on a Friday and pointed at a Friday entry. That is a one-session
lag baked into the data source, not into the playbook. Bonde's process is a SAME-DAY
scan (run 3:30-3:55 PM, enter 3:58-4:00 PM the same afternoon) and it is achievable:
the TradingView public scanner carries the CURRENT session's open/high/low/close,
which at 15:55 ET is ~99% complete.

THE ONE THING THAT MUST NEVER BREAK
-----------------------------------
A screener that fires at 15:55 must prove which session it is looking at. This script
does that with a DAY-ALIGNMENT ASSERTION before it computes anything:

    TV implied previous close  ==  shibui's latest settled close

If TV's session is today D, then TV's `close` and `change` imply the previous close,
which must be shibui's most recent settled bar. If they match, the scanner is on
today's live session and the scan is for TODAY. If instead TV's `close` equals
shibui's latest settled close, the scanner is describing an OLDER session (weekend,
holiday, or pre-open) and there is NO session to scan. Anything else is a degraded
run and is reported as such rather than silently scanning the wrong day.

Sessions are anchored to the SESSION SEQUENCE (shibui's ordered bars), never to
calendar arithmetic, so weekends and holidays need no special-casing.

USAGE
-----
    python3 reversal_bullish.py                       # today in US/Eastern
    python3 reversal_bullish.py --date 2026-11-02     # re-run a specific session
    python3 reversal_bullish.py --bridge /workspace/mcp_bridge.py
    python3 reversal_bullish.py --out-dir /workspace/daily-screens/<date>

Exit codes: 0 = artifact written; 1 = error; 3 = no US session today (not an error).

THE ARTIFACT CONTRACT (2026-11-05)
-----------------------------------
The markdown this script writes has a FIXED skeleton — TL;DR, Candidates, Promoted ideas,
Not promoted, Bonde gate matrix, Filter funnel, Method/source health/caveats — and two
slots the agent fills afterwards:

    <!-- REVIEW:PROMOTED -->      -> one '### ✅ IDEA n - TICKER ...' block per promoted name
    <!-- REVIEW:NOT_PROMOTED -->   -> one line per non-promoted candidate
    <!-- REVIEW:PROMOTED_COUNT --> -> set the TL;DR count to the number of ✅ IDEA blocks

The script publishes, on EVERY candidate row (markdown table AND CSV), the numbers that
were previously buried in prose:

    bar_low / bar_high            the signal bar's own range
    stop_vs_bar_low_pct           signed distance from the published stop to the bar low
    stop_class                    STRUCTURAL | NOISE_BREACH | CAPPED
    stop_capped                   yes/no - did the 2.5% cap bind the stop
    vol_vs_30d_avg_pct            the session's volume vs the 30-session mean
    capitulation                  CAPITULATION | LOW_VOLUME | UNKNOWN
    invalidation_level            a close below this level kills the setup

`tools/check_bonde_artifact.py` asserts all of it. Run it after the review is written.
"""

import argparse

import csv

import json

import os

import subprocess

import sys

import urllib.request

from datetime import datetime, timedelta

from zoneinfo import ZoneInfo

# Windows-safe artifact basename. Never use ":" — invalid on Windows NTFS.
# Historical outputs used reversal-bullish-3:55.*; new writes use 3_55.
ARTIFACT_STEM = "reversal-bullish-3_55"



ET = ZoneInfo("America/New_York")
TV_ENDPOINT = "https://scanner.tradingview.com/america/scan"

# Bump this whenever the artifact contract changes. The run-time fetch in the skill spec
# requires this marker, so a CDN-cached copy of an OLD script cannot produce an artifact in
# the old shape (raw.githubusercontent has been measured serving a stale blob for >17
# minutes after a push). The checker asserts the same string in the artifact footer.
CONTRACT_VERSION = "bonde-artifact-v3"

TV_COLS = ["name", "description", "close", "open", "high", "low", "change", "change_abs",
           "volume", "average_volume_10d_calc", "market_cap_basic", "exchange", "type", "sector"]

# ---------------------------------------------------------------- gate values
# Bonde's PUBLISHED gate (stockbee.blogspot.com, 2019-11-26, "Reversal Bullish Scan I use"):
#   l = minl5 and (o-l) > (c-o) and (c-l)/(h-l) >= .6 and v >= 290000 and c >= 5 and minv3.1 >= 100000
# plus the prose rules from the same source and the BreakoutsHappen write-up.
G = dict(
    dcr_min=0.60,            # (c-l)/(h-l) >= .6        published
    body_ratio_max=0.30,     # "small body"            published prose
    lower_shadow_gt_body=True,   # (o-l) > (c-o)        published
    hammer_mult=2.0,         # lower_shadow >= 2*upper_shadow   published prose
    washout_1d=-0.015,       # low/close_1d_ago - 1 <= -1.5%     published prose
    washout_decline=-0.03,   # close/close_3d_ago - 1 <= -3% (or 5d)  published prose
    adr_min=0.03,            # 20-day average daily range >= 3%
    close_min=5.0,           # published (c >= 5); "prefer higher priced" is a RANKING pref
    trend_floor=0.92,        # close >= close_20d_ago * 0.92
    volume_min=290_000,      # published v >= 290000
    minv3_min=100_000,       # published minv3.1 >= 100000
    mcap_min=5_000_000_000,
    avg_vol_30d_min=1_000_000,
    stop_max_pct=2.5,        # published: stop must not exceed 2.5% loss
    body_ratio_stop_switch=0.15,   # if body_ratio < 0.15 use the bar's LOW, not the body low
    capitulation_mult=1.5,   # flush volume >= 1.5x the 30-session mean = capitulation
    hist_sessions=30,        # settled sessions pulled per symbol
    universe_band=(5e9, 1.5e12),
)

# stop_class vocabulary (published on every candidate row, in the markdown AND the CSV)
STOP_CLASSES = ("STRUCTURAL", "NOISE_BREACH", "CAPPED")
CAPITULATION_CLASSES = ("CAPITULATION", "LOW_VOLUME", "UNKNOWN")


# ---------------------------------------------------------------- helpers
def et_now():
    return datetime.now(ET)


def session_is_settled(date_str):
    """True when this run happened AFTER the 16:00 ET bell for the scanned session.

    TradingView's daily bar finalizes LATE. Measured 2026-11-10: the 15:56 ET read saw a
    partial bar, the 16:02 ET and 16:04 ET reads still carried a PRE-AUCTION print, and only
    the 16:23 ET read carried the official 16:00 close. A pre-auction read is not a small
    discrepancy: on 2026-11-10 it published EAT with a 0.00% stop line, and EAT and EFX both
    fail the settled close. A settled read must be cross-checked against the market-recap
    quote (`as_of` 16:00:00 ET) before it is published. See SKILL.md §5.
    """
    now = et_now()
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
    except Exception:
        return False
    if now.date() > d:
        return True          # a replay of a past session
    if now.date() < d:
        return False
    return now.hour >= 16


def tv_scan(filters, sort, rng, cols=None, retries=3):
    """One TradingView scanner POST. Returns a list of row dicts."""
    body = {"markets": ["america"], "symbols": {"query": {"types": []}},
            "columns": cols or TV_COLS, "range": list(rng), "options": {"lang": "en"},
            "filter": filters, "sort": sort}
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                TV_ENDPOINT, data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0",
                         "Origin": "https://www.tradingview.com"})
            with urllib.request.urlopen(req, timeout=45) as fh:
                data = json.load(fh).get("data", [])
            return [dict(zip(cols or TV_COLS, r["d"])) for r in data]
        except Exception as exc:                     # noqa: BLE001
            last = exc
            if attempt < retries - 1:
                import time

                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"TradingView scanner failed: {last}")


def tv_universe():
    """The full eligible universe for one session, with a LIVE candle for each name.

    A single call with a generous `range` returns the complete filtered set — this
    avoids `range` paging entirely, because WITHOUT an explicit `sort` the scanner's
    page order is not stable between requests and paging silently DUPLICATES rows
    (measured 2026-11-03: 1500 rows fetched, only 1212 unique -> 288 names lost).
    """
    base = [{"left": "market_cap_basic", "operation": "greater", "right": G["mcap_min"]},
            {"left": "exchange", "operation": "in_range", "right": ["NYSE", "NASDAQ", "AMEX"]},
            {"left": "type", "operation": "equal", "right": "stock"},
            {"left": "close", "operation": "greater", "right": G["close_min"]},
            {"left": "average_volume_10d_calc", "operation": "greater",
             "right": G["avg_vol_30d_min"]}]
    rows = tv_scan(base, {"sortBy": "name", "sortOrder": "asc"}, [0, 2000])
    uniq = {}
    for r in rows:
        uniq[r["name"]] = r
    if len(rows) != len(uniq):
        print(f"note: {len(rows) - len(uniq)} duplicate rows collapsed", file=sys.stderr)
    return list(uniq.values()), len(rows)


def shibui_query(sql, bridge):
    args = {"query": sql, "user_prompt": "Bonde reversal bullish same-day scan"}
    path = "/workspace/_mcp/_rb_args.json"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(args, fh)
    proc = subprocess.run([sys.executable, bridge, "shibui", "stock_data_query", path],
                          capture_output=True, text=True, timeout=180)
    os.remove(path)
    if proc.returncode != 0:
        raise RuntimeError(f"shibui bridge failed: {proc.stdout[:400]} {proc.stderr[:200]}")
    try:
        data = json.loads(proc.stdout)
    except Exception:
        raise RuntimeError(f"shibui returned non-JSON: {proc.stdout[:400]}")
    if isinstance(data, dict) and data.get("error"):
        raise RuntimeError(f"shibui error: {data['error']}")
    return data


def nasdaq_history(ticker, date_str, sessions=30, include=False):
    """Settled daily OHLCV for one ticker from Nasdaq's public historical endpoint.

    `include=False` returns the sessions strictly BEFORE `date_str` (the history a
    screen needs). `include=True` also returns `date_str` itself, so a replay can
    pick the session's own bar off the end of the list.

    Used as the fallback when shibui's tool-call endpoint is unavailable. The
    endpoint is 1 call per ticker, so it is only used for the (small) set of
    candle-gate survivors, and it is called concurrently.
    """
    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    frm = (d - timedelta(days=max(45, sessions * 3))).isoformat()
    to = d.isoformat() if include else (d - timedelta(days=1)).isoformat()
    url = (f"https://api.nasdaq.com/api/quote/{ticker}/historical"
           f"?assetclass=stocks&fromdate={frm}&todate={to}&limit={sessions + 10}")
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/124 Safari/537.36", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as fh:
            data = json.load(fh)
    except Exception as exc:                           # noqa: BLE001
        # Nasdaq 404s on symbols it does not carry (some ADRs, some OTC lines).
        # One bad symbol must never abort the run.
        print(f"note: nasdaq history failed for {ticker}: {type(exc).__name__}", file=sys.stderr)
        return []
    tbl = (data.get("data") or {}).get("tradesTable") or {}
    out = []
    for r in (tbl.get("rows") or []):
        def num(x):
            """Nasdaq prints 'N/A' for some cells; never let that abort the run."""
            if x is None:
                return None
            s = str(x).replace("$", "").replace(",", "").strip()
            if s in ("", "N/A", "--", "UNCH"):
                return None
            try:
                return float(s)
            except ValueError:
                return None
        o, h, l, c, v = num(r.get("open")), num(r.get("high")), num(r.get("low")), \
            num(r.get("close")), num(r.get("volume"))
        if None in (o, h, l, c):
            continue
        try:
            dt = datetime.strptime(r["date"], "%m/%d/%Y").date().isoformat()
        except Exception:
            continue
        if not include and dt >= date_str:
            continue
        out.append(dict(ticker=ticker, date=dt, open=o, high=h, low=l, close=c, volume=v or 0))
    out.sort(key=lambda b: b["date"])
    return out[-sessions:]


def fetch_history(tickers, date_str, bridge, sessions=30, prefer_shibui=True):
    """Settled history for a set of tickers. shibui first (batched), Nasdaq second.

    Returns (history_dict, source_name).
    """
    if prefer_shibui:
        try:
            hist = shibui_history(tickers, date_str, bridge, sessions=sessions)
            if all(t in hist and hist[t] for t in tickers):
                return hist, "shibui"
            missing = [t for t in tickers if not hist.get(t)]
            print(f"note: shibui returned no history for {len(missing)} ticker(s); "
                  f"falling back to Nasdaq for those", file=sys.stderr)
        except Exception as exc:                       # noqa: BLE001
            print(f"note: shibui history unavailable ({str(exc)[:120]}); using Nasdaq",
                  file=sys.stderr)
            hist, missing = {}, list(tickers)
    else:
        hist, missing = {}, list(tickers)
    if missing:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=8) as pool:
            for t, bars in pool.map(
                    lambda tk: (tk, nasdaq_history(tk, date_str, sessions)), missing):
                if bars:
                    hist[t] = bars
    src = "shibui" if (prefer_shibui and len(hist) == len(tickers) and not missing) else "nasdaq"
    return hist, src


def shibui_history(tickers, date_str, bridge, sessions=30):
    """Settled daily bars for each ticker, strictly BEFORE `date_str`.

    Returns {ticker: [bar, ...]} oldest-first, where bar = {date,open,high,low,close,volume}.
    Uses QUALIFY to take exactly the last `sessions` rows per ticker, so the row
    count is deterministic and never silently truncated by the 200-row cap.
    """
    out = {}
    chunk = 6                       # 6 x 30 = 180 rows < the 200-row server cap
    for i in range(0, len(tickers), chunk):
        part = tickers[i:i + chunk]
        lst = ", ".join("'%s'" % t for t in part)
        sql = (f"SELECT ticker, date, open, high, low, close, volume FROM shibui.stock_quotes "
               f"WHERE ticker IN ({lst}) AND date < '{date_str}' "
               f"QUALIFY ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) <= {sessions} "
               f"ORDER BY ticker, date LIMIT 200")
        rows = shibui_query(sql, bridge)
        got = set()
        for r in rows:
            out.setdefault(r["ticker"], []).append(r)
            got.add(r["ticker"])
        missing = [t for t in part if t not in got]
        if missing:
            # never let a truncated chunk look like a short history
            for t in missing:
                sql1 = (f"SELECT ticker, date, open, high, low, close, volume FROM shibui.stock_quotes "
                        f"WHERE ticker = '{t}' AND date < '{date_str}' "
                        f"QUALIFY ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) <= {sessions} "
                        f"ORDER BY date LIMIT 200")
                for r in shibui_query(sql1, bridge):
                    out.setdefault(r["ticker"], []).append(r)
    return out


# Reference names used only to prove WHICH session the scanner is describing.
# Large, always-listed, liquid — their previous close is unambiguous.
ALIGNMENT_TICKERS = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META",
                     "TSLA", "JPM", "XOM", "WMT", "LLY", "AVGO"]


def shibui_latest_close(date_str, bridge):
    """Most recent settled close per ticker (one row each) for the reference names."""
    lst = ", ".join("'%s'" % t for t in ALIGNMENT_TICKERS)
    sql = (f"SELECT ticker, date, close FROM shibui.stock_quotes "
           f"WHERE ticker IN ({lst}) AND date < '{date_str}' "
           f"QUALIFY ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) = 1 "
           f"LIMIT 200")
    rows = shibui_query(sql, bridge)
    return {r["ticker"]: r for r in rows}


def market_state(bridge, symbols=("SPY",)):
    path = "/workspace/_mcp/_rb_mr.json"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump({"symbols": ",".join(symbols)}, fh)
    proc = subprocess.run([sys.executable, bridge, "market-recap", "get_quotes", path],
                          capture_output=True, text=True, timeout=120)
    os.remove(path)
    if proc.returncode != 0:
        return None
    try:
        return json.loads(proc.stdout)
    except Exception:
        return None


# ---------------------------------------------------------------- filters
def candle_metrics(row):
    """Bonde's candle geometry from a (live) OHLC row."""
    o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
    rng = h - l
    if rng <= 0:
        return None
    lower = min(o, c) - l
    upper = h - max(o, c)
    return dict(
        open=o, high=h, low=l, close=c, volume=float(row.get("volume") or 0),
        rng=rng,
        dcr=(c - l) / rng,
        body_ratio=abs(c - o) / rng,
        lower_shadow=lower,
        upper_shadow=upper,
        tail_ratio=(lower / abs(c - o)) if abs(c - o) > 1e-9 else float("inf"),
        published_shadow_ok=(o - l) > (c - o),
        hammer_ok=lower >= G["hammer_mult"] * upper,
    )


def history_metrics(bars):
    """Derived metrics from the settled session sequence (oldest-first)."""
    n = len(bars)
    if n < 21:
        return None
    closes = [b["close"] for b in bars]
    vols = [b["volume"] for b in bars]
    last = bars[-1]
    def ago(k):
        return closes[-k] if k <= n else None
    adr = sum((b["high"] - b["low"]) / b["close"] for b in bars[-20:]) / 20.0
    drop_days = 0
    for i in range(n - 1, 0, -1):
        if closes[i] < closes[i - 1]:
            drop_days += 1
        else:
            break
    return dict(
        latest_date=str(last["date"]),
        close_1d_ago=ago(1), close_3d_ago=ago(3), close_5d_ago=ago(5), close_20d_ago=ago(20),
        low_5_prev=min(b["low"] for b in bars[-5:]),
        low_4_prev=min(b["low"] for b in bars[-4:]) if n >= 4 else None,
        adr=adr,
        avg_vol_30d=sum(vols[-30:]) / len(vols[-30:]),
        minv3=min(vols[-3:]),
        drop_days=drop_days,
        sessions=n,
    )


def evaluate(row, hist):
    """Apply every Bonde gate to a live candle + its settled history.

    Returns (passes: bool, checks: dict) — `checks` records every gate so the
    artifact can show WHY a name failed, not just that it did.
    """
    m = candle_metrics(row)
    h = hist
    c = {}
    c["f1_5day_low"] = m["low"] <= h["low_4_prev"]
    c["f2_dcr"] = m["dcr"] >= G["dcr_min"]
    c["f3_shadow_gt_body"] = m["published_shadow_ok"]
    c["f3b_hammer"] = m["hammer_ok"]
    c["f3c_small_body"] = m["body_ratio"] <= G["body_ratio_max"]
    wash1 = (m["low"] / h["close_1d_ago"] - 1.0) <= G["washout_1d"]
    wash2 = ((m["close"] / h["close_3d_ago"] - 1.0) <= G["washout_decline"] or
             (m["close"] / h["close_5d_ago"] - 1.0) <= G["washout_decline"])
    c["f5_decline_washout"] = wash1 and wash2
    c["f6_adr"] = h["adr"] >= G["adr_min"]
    c["f7_price"] = m["close"] >= G["close_min"]
    c["f8_trend"] = m["close"] >= h["close_20d_ago"] * G["trend_floor"]
    c["f_volume"] = m["volume"] >= G["volume_min"]
    c["f_minv3"] = h["minv3"] >= G["minv3_min"]
    c["f_avgvol30"] = h["avg_vol_30d"] > G["avg_vol_30d_min"]
    passes = all(c.values())
    return passes, c, m, h


def stop_profile(m, entry):
    """Bonde's stop PLUS the geometry a reader needs before sizing the trade.

    The stop itself is unchanged from Bonde's published rule: the body low, except on a
    near-doji body (under 15% of the range) where the signal bar's LOW is used, and never
    more than 2.5% of loss from the entry.

    What this adds is the CONFLICT that the 2026-11-03 artifact disclosed only in prose:
    a stop tightened to the 2.5% cap can land INSIDE the signal bar's own range, so a
    print through it is a *noise breach*, not a structural failure. That fact is published
    as a field, never as a caveat sentence.

    Returns a dict:
      stop                 published stop level (2.5% cap applied)
      stop_basis           human-readable stop basis
      structural           the structural stop level (body low, or the bar's low on a doji body)
      stop_capped         True when the 2.5% max-loss cap tightened the stop
      stop_class           STRUCTURAL | NOISE_BREACH | CAPPED  (see below)
      stop_vs_bar_low_pct  signed: how far the published stop sits from the bar low
                           (negative = the stop is BELOW the bar low -> survives noise;
                            positive = the stop is ABOVE the bar low -> inside the bar's range)
      bar_low_vs_entry_pct the structural distance to the bar low (the real risk, uncapped)
      invalidation_level   a close below this level kills the setup

    stop_class precedence (exactly one value per candidate):
      NOISE_BREACH  the published stop is ABOVE the signal bar's low, so the bar itself
                    already traded through it. A print through the stop is noise.
      CAPPED        the 2.5% cap bound the stop AND the published stop is still at or below
                    the bar low, so it survives the bar's noise but is tighter than the
                    structural level.
      STRUCTURAL    the published stop is the structural level itself.

    Note: with today's stop rule the cap can only pull a stop UP into the bar's range (the
    bar low is always at least as far from the entry as the structural stop), so a capped
    stop is ALWAYS classified NOISE_BREACH and CAPPED does not occur. `stop_capped` and
    `stop_basis` carry the cap fact in every case, so no information is lost.
    """
    body_low = min(m["open"], m["close"])
    if m["body_ratio"] < G["body_ratio_stop_switch"]:
        structural = m["low"]
        basis = "bar low (body < 15% of range)"
    else:
        structural = body_low
        basis = "body low"
    cap_applied = bool(entry) and (entry - structural) / entry * 100.0 > G["stop_max_pct"]
    if cap_applied:
        stop = entry * (1 - G["stop_max_pct"] / 100.0)
        basis += " (tightened to the 2.5% cap)"
    else:
        stop = structural
    stop = round(stop, 2)
    bar_low = m["low"]
    tol = max(0.005, bar_low * 0.0005)          # a cent of rounding must not create a class
    if stop > bar_low + tol:
        stop_class = "NOISE_BREACH"
    elif cap_applied:
        stop_class = "CAPPED"
    else:
        stop_class = "STRUCTURAL"
    return dict(
        stop=stop,
        stop_basis=basis,
        structural=round(structural, 2),
        stop_capped=cap_applied,
        stop_class=stop_class,
        stop_vs_bar_low_pct=round((stop - bar_low) / bar_low * 100.0, 3) if bar_low else None,
        bar_low_vs_entry_pct=round((bar_low - entry) / entry * 100.0, 3) if entry else None,
        invalidation_level=round(bar_low, 2),
    )


def volume_conviction(m, h):
    """Trade quality: was there capitulation behind the flush?

    `vol_vs_30d_avg_pct` = the session's volume as a percentage of the 30-session mean
    (the mean of the last 30 SETTLED sessions' volume). CAPITULATION at >= 1.5x.
    Published as a number on every candidate row — a trader must know the setup lacked
    capitulation BEFORE sizing it, not in a footnote.
    """
    avg = float(h.get("avg_vol_30d") or 0)
    vol = float(m.get("volume") or 0)
    if avg <= 0:
        return dict(vol_vs_30d_avg_pct=None, capitulation="UNKNOWN", avg_vol_30d=0.0)
    pct = vol / avg * 100.0
    return dict(
        vol_vs_30d_avg_pct=round(pct, 1),
        capitulation="CAPITULATION" if pct >= G["capitulation_mult"] * 100 else "LOW_VOLUME",
        avg_vol_30d=avg,
    )



# ---------------------------------------------------------------- main
def run_settled(date_str, bridge, out_dir, dry_run=False):
    """REPLAY path: scan a PAST session from settled bars.

    Used for a delayed replay (the routine's OUTPUT section says to rebuild for the
    scheduled date). A past session cannot be scanned live, so the signal bar is the
    settled bar for that date and the artifact is flagged as a reconstruction.
    The universe comes from today's scanner (market cap / exchange / type are close
    enough for a recent date); the bars come from Nasdaq.
    """
    started = et_now()
    report = {"date": date_str, "started_et": started.isoformat(timespec="seconds"),
              "mode": "SETTLED_REPLAY", "reconstruction": True,
              "note": "past session rebuilt from settled bars - not a live scan"}
    rows, raw_rows = tv_universe()
    report["universe_rows"] = len(rows)
    report["universe_raw_rows"] = raw_rows
    tickers = [r["name"] for r in rows]

    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=12) as pool:
        H = dict(pool.map(lambda t: (t, nasdaq_history(t, date_str, G["hist_sessions"] + 2,
                                                       include=True)), tickers))
    report["history_source"] = "nasdaq"
    report["shibui_latest_sessions"] = ["n/a (settled replay)"]
    report["alignment"] = dict(reference_names=0, live_hits=0, stale_hits=0,
                               live_ratio=0.0, stale_ratio=0.0)

    prelim, results = [], []
    for r in rows:
        bars = H.get(r["name"], [])
        if not bars:
            continue
        b = bars[-1]
        if str(b["date"]) != date_str:
            continue
        hm = history_metrics(bars[:-1])
        if hm is None:
            continue
        row = dict(open=b["open"], high=b["high"], low=b["low"], close=b["close"],
                   volume=b["volume"], change=0.0)
        m = candle_metrics(row)
        if m is None:
            continue
        prelim.append((r, m))
        ok, checks, mm, hh = evaluate(row, hm)
        if not ok:
            continue
        mm["checks"] = checks
        results.append(dict(ticker=r["name"], desc=r.get("description") or r["name"],
                            exchange=r.get("exchange"), sector=r.get("sector"),
                            mcap=float(r.get("market_cap_basic") or 0),
                            avg_vol_10d=float(r.get("average_volume_10d_calc") or 0),
                            change_pct=0.0, m=mm, h=hh, passes=True))
    report["candle_gate_survivors"] = len(prelim)
    report["passing"] = len(results)
    for x in results:
        entry = x["m"]["close"]
        prof = stop_profile(x["m"], entry)
        vol = volume_conviction(x["m"], x["h"])
        x["entry"] = round(entry, 2)
        x.update(prof)
        x.update(vol)
        x["stop_pct"] = round((entry - prof["stop"]) / entry * 100.0, 2)
        x["tail_band"] = (3.0 <= x["m"]["tail_ratio"] <= 5.0)
    results.sort(key=lambda x: (-x["m"]["dcr"], -x["h"]["adr"]))
    if not dry_run:
        os.makedirs(out_dir, exist_ok=True)
        write_csv(os.path.join(out_dir, ARTIFACT_STEM + ".csv"), results, report)
        write_md(os.path.join(out_dir, ARTIFACT_STEM + ".md"), results, report, bridge)
    print(json.dumps(report, indent=2))
    return 0, report


def run(date_str, bridge, out_dir, dry_run=False):
    started = et_now()
    report = {"date": date_str, "started_et": started.isoformat(timespec="seconds")}
    report["candle_settled"] = session_is_settled(date_str)

    today_et = started.strftime("%Y-%m-%d")
    if date_str != today_et:
        return run_settled(date_str, bridge, out_dir, dry_run=dry_run)

    # ---- 1. the live universe -------------------------------------------------
    rows, raw_rows = tv_universe()
    report["universe_rows"] = len(rows)
    report["universe_raw_rows"] = raw_rows
    if not rows:
        raise RuntimeError("TradingView universe came back empty")

    # ---- 2. shibui's latest settled close (the alignment reference) ----------
    by_ticker = {r["name"]: r for r in rows}
    ref_hist, hist_src = fetch_history(ALIGNMENT_TICKERS, date_str, bridge, sessions=2)
    latest = {}
    for t, bars in ref_hist.items():
        if bars:
            latest[t] = bars[-1]
    report["history_source"] = hist_src
    report["shibui_latest_sessions"] = sorted({str(r["date"]) for r in latest.values()})

    # ---- 3. DAY-ALIGNMENT ASSERTION -----------------------------------------
    live_hits = stale_hits = 0
    ref = {}
    for t, row in latest.items():
        r = by_ticker.get(t)
        if r is None:
            continue
        chg = float(r.get("change") or 0.0)
        denom = 1.0 + chg / 100.0
        implied_prev = float(r["close"]) / denom if denom else None
        sh = float(latest[t]["close"])
        ref[t] = (implied_prev, sh, float(r["close"]))
        if implied_prev is None:
            continue
        if abs(implied_prev - sh) <= max(0.02, sh * 0.004):
            live_hits += 1
        elif abs(float(r["close"]) - sh) <= max(0.02, sh * 0.004):
            stale_hits += 1
    n_ref = len(ref) or 1
    live_ratio = live_hits / n_ref
    stale_ratio = stale_hits / n_ref
    report["alignment"] = dict(reference_names=len(ref), live_hits=live_hits,
                                stale_hits=stale_hits, live_ratio=round(live_ratio, 4),
                                stale_ratio=round(stale_ratio, 4))
    if live_ratio >= 0.90:
        mode = "LIVE"
    elif stale_ratio >= 0.90:
        mode = "NO_SESSION"
    else:
        mode = "DEGRADED"
    report["mode"] = mode

    if mode == "NO_SESSION":
        print(f"no US session on {date_str}: the scanner is describing the session that "
              f"shibui already has ({report['shibui_latest_sessions'][:1]}). Nothing to scan.")
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, ARTIFACT_STEM + ".md"), "w") as fh:
            fh.write("\n".join([
                f"# Bonde Reversal Bullish — {title_date(date_str)}",
                "",
                "## TL;DR",
                "",
                f"- **Mechanical passers: 0** — no US session on {date_str} (market holiday or "
                f"weekend); the scanner was still describing the prior session "
                f"({report['shibui_latest_sessions'][:1]}).",
                "- **Ideas promoted: 0** — there is no session, so there is no signal.",
                "- **No candidates, no entry window, no alert.** The previous session's scan is "
                "NOT substituted for this one.",
                "",
                "## Candidates",
                "",
                "_No US session — no candidates._",
                "",
                "## Promoted ideas",
                "",
                "_No US session — no idea promoted._",
                "",
                "## Not promoted",
                "",
                "_No US session — nothing to review._",
                "",
                "## Bonde gate matrix",
                "",
                "_No US session — no gate matrix._",
                "",
                "## Filter funnel",
                "",
                "_No US session._",
                "",
                "## Method, source health & caveats",
                "",
                f"- **Mode: NO_SESSION.** The day-alignment assertion found the scanner "
                f"describing the session shibui already holds "
                f"({report['shibui_latest_sessions'][:1]}), so there was no live session to scan "
                f"on {date_str}.",
                "- **The previous session's scan was NOT substituted.** That is the one-session "
                "lag this routine exists to avoid.",
                "",
                "| Source | Used for | Status |",
                "|---|---|---|",
                f"| TradingView public scanner | live session OHLC | ok "
                f"({report.get('universe_rows', 0)} names) |",
                f"| shibui-finance (bridge) | latest settled close | ok "
                f"(latest session {report.get('shibui_latest_sessions', ['n/a'])[:1]}) |",
                "",
                f"_Generated by cron #4 `reversal-bullish-3:55` · tool `tools/reversal_bullish.py` "
                f"· session {date_str} · contract `{CONTRACT_VERSION}` · `_source=mcp`_",
            ]) + "\n")
        return 3, report

    if mode == "DEGRADED":
        print(f"WARNING: session alignment could not be established "
              f"(live {live_ratio:.0%} / stale {stale_ratio:.0%}). Running degraded: the "
              f"candle may not be today's. This artifact must not be traded.", file=sys.stderr)

    # ---- 4. candle-side gates (free, no history) ----------------------------
    prelim = []
    for r in rows:
        m = candle_metrics(r)
        if m is None:
            continue
        if m["dcr"] < G["dcr_min"] or not m["published_shadow_ok"]:
            continue
        if not m["hammer_ok"] or m["body_ratio"] > G["body_ratio_max"]:
            continue
        if m["close"] < G["close_min"]:
            continue
        if float(r.get("volume") or 0) < G["volume_min"]:
            continue
        prelim.append((r, m))
    report["candle_gate_survivors"] = len(prelim)

    # ---- 5. history-side gates ------------------------------------------------
    tickers = [r["name"] for r, _ in prelim]
    hist, hist_src2 = fetch_history(tickers, date_str, bridge, sessions=G["hist_sessions"])
    report["history_source"] = hist_src2
    results = []
    for r, m in prelim:
        bars = hist.get(r["name"], [])
        h = history_metrics(bars)
        if h is None:
            continue
        ok, checks, mm, hh = evaluate(r, h)
        mm["checks"] = checks
        results.append(dict(ticker=r["name"], desc=r.get("description") or r["name"],
                            exchange=r.get("exchange"), sector=r.get("sector"),
                            mcap=float(r.get("market_cap_basic") or 0),
                            avg_vol_10d=float(r.get("average_volume_10d_calc") or 0),
                            change_pct=float(r.get("change") or 0),
                            m=mm, h=hh, passes=ok))
    report["history_gate_survivors"] = sum(1 for x in results if x["passes"])
    results = [x for x in results if x["passes"]]
    results.sort(key=lambda x: (-x["m"]["dcr"], -x["h"]["adr"]))

    # ---- 6. tiering + stops ---------------------------------------------------
    for x in results:
        entry = x["m"]["close"]
        prof = stop_profile(x["m"], entry)
        vol = volume_conviction(x["m"], x["h"])
        x["entry"] = round(entry, 2)
        x.update(prof)
        x.update(vol)
        x["stop_pct"] = round((entry - prof["stop"]) / entry * 100.0, 2)
        x["tail_band"] = (3.0 <= x["m"]["tail_ratio"] <= 5.0)
    report["passing"] = len(results)

    # ---- 7. write the artifact -------------------------------------------------
    if dry_run:
        print(json.dumps(report, indent=2))
        for x in results:
            print(x["ticker"], x["entry"], x["stop"], x["m"]["dcr"], x["h"]["adr"])
        return 0, report

    os.makedirs(out_dir, exist_ok=True)
    write_csv(os.path.join(out_dir, ARTIFACT_STEM + ".csv"), results, report)
    write_md(os.path.join(out_dir, ARTIFACT_STEM + ".md"), results, report, bridge)
    print(json.dumps(report, indent=2))
    return 0, report


CSV_COLS = ["ticker", "company", "exchange", "sector", "signal_session", "entry_price",
            "stop", "stop_basis", "stop_pct", "stop_class", "stop_capped",
            "bar_low", "bar_high", "stop_vs_bar_low_pct", "bar_low_vs_entry_pct",
            "invalidation_level",
            "open", "high", "low", "close", "volume",
            "dcr", "body_ratio", "lower_shadow", "upper_shadow", "tail_ratio", "tail_in_3to5",
            "adr_pct", "drop_days", "chg_1d_pct", "chg_3d_pct", "chg_20d_pct", "low_5_prev",
            "market_cap", "avg_vol_30d", "vol_vs_30d_avg_pct", "capitulation", "day_tag",
            "gate_f1_5day_low", "gate_f2_dcr",
            "gate_f3_shadow_gt_body", "gate_f3b_hammer", "gate_f3c_small_body",
            "gate_f5_decline_washout", "gate_f6_adr", "gate_f7_price", "gate_f8_trend",
            "gate_volume", "gate_minv3", "gate_avgvol30", "_source"]


def write_csv(path, results, report):
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(CSV_COLS)
        for x in results:
            m, h, c = x["m"], x["h"], x["m"]["checks"]
            if x["stop_class"] not in STOP_CLASSES:
                raise ValueError(f"{x['ticker']}: unknown stop_class {x['stop_class']!r}")
            if x["capitulation"] not in CAPITULATION_CLASSES:
                raise ValueError(f"{x['ticker']}: unknown capitulation {x['capitulation']!r}")
            w.writerow([x["ticker"], x["desc"], x["exchange"], x["sector"], report["date"],
                        x["entry"], x["stop"], x["stop_basis"], x["stop_pct"],
                        x["stop_class"], "yes" if x["stop_capped"] else "no",
                        x["invalidation_level"], m["high"],
                        ("" if x["stop_vs_bar_low_pct"] is None else x["stop_vs_bar_low_pct"]),
                        ("" if x["bar_low_vs_entry_pct"] is None else x["bar_low_vs_entry_pct"]),
                        x["invalidation_level"],
                        m["open"], m["high"], m["low"], m["close"], int(m["volume"]),
                        round(m["dcr"], 4), round(m["body_ratio"], 4),
                        round(m["lower_shadow"], 4), round(m["upper_shadow"], 4),
                        ("inf" if m["tail_ratio"] == float("inf") else round(m["tail_ratio"], 2)),
                        "yes" if x["tail_band"] else "no",
                        round(h["adr"] * 100, 2), h["drop_days"],
                        round((m["close"] / h["close_1d_ago"] - 1) * 100, 2),
                        round((m["close"] / h["close_3d_ago"] - 1) * 100, 2),
                        round((m["close"] / h["close_20d_ago"] - 1) * 100, 2),
                        round(h["low_5_prev"], 4), int(x["mcap"]), int(h["avg_vol_30d"]),
                        ("" if x["vol_vs_30d_avg_pct"] is None else x["vol_vs_30d_avg_pct"]),
                        x["capitulation"],
                        "Day 1 (signal is the current session)", c["f1_5day_low"], c["f2_dcr"],
                        c["f3_shadow_gt_body"], c["f3b_hammer"], c["f3c_small_body"],
                        c["f5_decline_washout"], c["f6_adr"], c["f7_price"], c["f8_trend"],
                        c["f_volume"], c["f_minv3"], c["f_avgvol30"], "mcp"])


# ---------------------------------------------------------------- artifact contract
# The agent fills the two review slots below and sets the promoted count. The checker
# (tools/check_bonde_artifact.py) fails the run if a marker is left behind or if the
# count and the number of ✅ IDEA blocks disagree.
PROMOTED_MARK = "<!-- REVIEW:PROMOTED -->"
NOT_PROMOTED_MARK = "<!-- REVIEW:NOT_PROMOTED -->"
PROMOTED_COUNT_MARK = "<!-- REVIEW:PROMOTED_COUNT -->"

SKELETON = ["TL;DR", "Candidates", "Promoted ideas", "Not promoted",
            "Bonde gate matrix", "Filter funnel", "Method, source health & caveats"]

_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
           "September", "October", "November", "December"]


def title_date(date_str):
    """'Tuesday, 03 November 2026' — the title form the artifact contract fixes."""
    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    return f"{_DAYS[d.weekday()]}, {d.day:02d} {_MONTHS[d.month - 1]} {d.year}"


def tldr_caveat(results):
    """The ONE caveat that changes how the candidates must be read.

    Priority: a stop conflict (NOISE_BREACH) beats a capped stop beats missing
    capitulation beats the plain timing caveat. It is computed from the data, never
    left to prose. One line, the way the fleet's reply format wants it.
    """
    noise = [x for x in results if x["stop_class"] == "NOISE_BREACH"]
    if noise:
        # worst conflict first: the stop furthest above the bar low is the one that
        # most changes how the trade must be sized
        noise.sort(key=lambda x: -abs(x["stop_vs_bar_low_pct"] or 0.0))
        bits = ", ".join(f"{x['ticker']} (stop {x['stop']:.2f} vs bar low {x['m']['low']:.2f})"
                         for x in noise[:3])
        more = f" +{len(noise) - 3} more" if len(noise) > 3 else ""
        return ("⚠ **Stop conflict:** the published stop sits INSIDE the signal bar's own range "
                f"for {bits}{more} — a print through it is a NOISE_BREACH, not a structural "
                "failure; the structural level is the bar low.")
    capped = [x for x in results if x.get("stop_capped")]
    if capped:
        x = capped[0]
        return (f"**Capped stop:** {x['ticker']}'s stop was tightened to Bonde's 2.5% max-loss cap "
                f"({x['stop']:.2f}); the structural level is {x['m']['low']:.2f} "
                f"({x['bar_low_vs_entry_pct']:.2f}% from entry).")
    lowv = [x for x in results if x.get("capitulation") == "LOW_VOLUME"]
    if lowv:
        x = lowv[0]
        return (f"**No capitulation:** {x['ticker']} traded {x['vol_vs_30d_avg_pct']:.0f}% of its "
                f"30-session average volume — the flush lacked conviction; size the position for "
                f"that, not for a capitulation flush.")
    return ("**The candle is read at ~15:55 ET** — the 16:00 print can still move the close, the "
            "DCR and the stop.")


def _md_candidates_table(results):
    """One table, one row per name — every gate/metric/stop column the contract requires."""
    out = []
    A = out.append
    A("| Ticker | Company | Entry | Stop | Stop % | Stop class | Bar low | Bar high | "
      "Stop vs bar low | DCR | Body | Lower shdw | Tail | ADR | Drop days | 1-day chg | "
      "Vol vs 30d avg | Capitulation | Mkt cap |")
    A("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for x in results:
        m, h = x["m"], x["h"]
        tail = "inf" if m["tail_ratio"] == float("inf") else f"{m['tail_ratio']:.2f}x"
        svbl = ("n/a" if x["stop_vs_bar_low_pct"] is None
                else f"{x['stop_vs_bar_low_pct']:+.2f}%")
        vol = ("n/a" if x.get("vol_vs_30d_avg_pct") is None
               else f"{x['vol_vs_30d_avg_pct']:.0f}%")
        A(f"| **{x['ticker']}** | {x['desc']} | **{x['entry']:.2f}** | {x['stop']:.2f} | "
          f"{x['stop_pct']:.2f}% | `{x['stop_class']}` | {m['low']:.2f} | {m['high']:.2f} | "
          f"{svbl} | {m['dcr']:.3f} | {m['body_ratio']:.3f} | "
          f"{m['lower_shadow']:.2f} | {tail}{' ✓' if x['tail_band'] else ''} | "
          f"{h['adr']*100:.2f}% | {h['drop_days']} | "
          f"{(m['close']/h['close_1d_ago']-1)*100:+.2f}% | {vol} | "
          f"{x['capitulation']} | ${x['mcap']/1e9:.2f}B |")
    return out


def write_md(path, results, report, bridge):
    a = report["date"]
    L = []
    A = L.append
    A(f"# Bonde Reversal Bullish — {title_date(a)}")
    A("")
    if report.get("mode") == "DEGRADED":
        A("> **DEGRADED RUN — do not trade this.** The session could not be pinned down; the "
          "candle may not be today's.")
        A("")
    A("## TL;DR")
    A("")
    settled = bool(report.get("candle_settled"))
    entry_note = ("entry = the settled 16:00 ET close (the screen was read after the bell)."
                  if settled else "entry 15:58–16:00 ET.")
    A(f"- **Mechanical passers: {report.get('passing', 0)}** of "
      f"{report.get('universe_rows', 0)} names scanned · mode **{report.get('mode')}** · "
      f"signal session **{a}** · {entry_note}")
    A(f"- **Ideas promoted: 0** {PROMOTED_COUNT_MARK} — _pending the discretionary review; set "
      f"this count to the number of ✅ IDEA blocks below._")
    A(f"- {tldr_caveat(results)}")
    A("")
    A("## Candidates")
    A("")
    if not results:
        A("_No name passed every gate today._")
    else:
        for line in _md_candidates_table(results):
            A(line)
    A("")
    A("## Promoted ideas")
    A("")
    A(PROMOTED_MARK)
    A("_No idea promoted yet — the discretionary review has not been written. Replace the marker "
      "above with one block per promoted name:_")
    A("")
    A("```")
    A("### ✅ IDEA 1 — TICKER (Company) · entry X.XX · stop Y.YY (-2.50%) · stop_class "
      "NOISE_BREACH · vol 63% of 30d avg (LOW_VOLUME) · Day 1")
    A("**Catalyst:** <named, dated>")
    A("**Invalidated if** <price> closes below <level> / <named event> does not happen by <date>.")
    A("```")
    A("")
    A("## Not promoted")
    A("")
    A(NOT_PROMOTED_MARK)
    A("_No candidate reviewed yet. One line per non-promoted candidate: the mechanical gate it "
      "passed, the reason it was not promoted, and its invalidation test._")
    A("")
    A("## Bonde gate matrix")
    A("")
    if not results:
        A("_No candidates._")
    else:
        A("| Ticker | 1. 5-day low | 2. DCR ≥ .60 | 3. shadow > body | 3b. hammer | "
          "3c. body ≤ .30 | 5. decline + washout | 6. ADR ≥ 3% | 7. price ≥ $5 | 8. trend | "
          "vol | minv3 | avolv30 |")
        A("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
        for x in results:
            c = x["m"]["checks"]
            A(f"| {x['ticker']} | " + " | ".join(
                ("✓" if c[k] else "✗") for k in
                ("f1_5day_low", "f2_dcr", "f3_shadow_gt_body", "f3b_hammer", "f3c_small_body",
                 "f5_decline_washout", "f6_adr", "f7_price", "f8_trend", "f_volume",
                 "f_minv3", "f_avgvol30")) + " |")
    A("")
    A("## Filter funnel")
    A("")
    A("| Step | Filter | Left |")
    A("|---|---|---|")
    for s, f, n in [
        ("1", "NYSE/NASDAQ/AMEX, type=stock, mcap > $5B, close ≥ $5, avg vol(10d) > 1M",
         report.get("universe_rows", 0)),
        ("2", "DCR ≥ 0.60 (close in the top 40% of the day's range)",
         report.get("candle_gate_survivors", 0)),
        ("3", "+ published shadow > body, hammer (lower ≥ 2× upper), body ≤ 0.30, volume ≥ 290k",
         report.get("candle_gate_survivors", 0)),
        ("4", "+ 5-day low, decline+washout, ADR ≥ 3%, trend, minv3, avg vol 30d",
         report.get("passing", 0)),
    ]:
        A(f"| {s} | {f} | {n} |")
    A("")
    A("## Method, source health & caveats")
    A("")
    al = report.get("alignment", {})
    if report.get("mode") == "SETTLED_REPLAY":
        A(f"- **This is a RECONSTRUCTION, not a live scan.** It was rebuilt at "
          f"{report.get('started_et','')} from the settled bars for {a}, because the live scanner "
          f"can only describe the CURRENT session. The entry it describes was that session's "
          f"close — it is a planning artifact for {a}, not a signal for today.")
    else:
        A(f"- **Session alignment — proof this scan is for today:** TV implied previous close vs "
          f"shibui's latest settled close: **{al.get('live_hits', 0)}/"
          f"{al.get('reference_names', 0)} agree** ({al.get('live_ratio', 0):.1%}) → mode "
          f"**{report.get('mode')}**. The scanner's session is pinned before any gate is applied.")
    A(f"- **The signal is TODAY's live candle, not yesterday's.** The routine proves this at "
      f"runtime (alignment above); it no longer resolves the screen date as \"shibui's latest "
      f"settled date\", which was a one-session lag.")
    if settled:
        A("- **The candle was read AFTER the 16:00 ET bell — these are the settled "
          f"{a} numbers.** TradingView's daily bar finalizes late (measured 2026-11-10: the "
          "16:02 ET and 16:04 ET reads still carried a PRE-AUCTION print; only the 16:23 ET read "
          "carried the official close), so a post-close read must be cross-checked against the "
          "`market-recap get_quotes` close (`as_of` 16:00:00 ET) before it is published. If the "
          "two disagree by more than ~0.3%, the bar is not settled yet — re-read.")
        A("- **`v ≥ 290,000` is judged on the FULL day's volume** — the read is post-close, so no "
          "name was excluded for clearing 290k only in the last minutes.")
    else:
        A("- **The candle is read at ~15:55 ET, five minutes before the close.** The 16:00 print "
          "can change the close, the DCR and the stop. Treat the entry as the 16:00 close.")
        A("- **`v ≥ 290,000` uses a partial day's volume** (as of ~15:55 ET). A name that clears "
          "290k only after the close was wrongly excluded.")
    A("- **ADR(20) is computed over the 20 SETTLED sessions before today**, not over a window that "
      "includes the incomplete live bar.")
    if settled:
        A("- **`vol_vs_30d_avg_pct` compares the FULL day's volume with the full-day 30-session "
          "mean** (both settled), so no partial-day discount applies. `capitulation = "
          "CAPITULATION` at ≥ 150% of that mean, `LOW_VOLUME` below it.")
    else:
        A("- **`vol_vs_30d_avg_pct` compares a partial day's volume with a full-day 30-session "
          "mean**, so it reads slightly low at 15:55 ET. `capitulation = CAPITULATION` at ≥ 150% "
          "of that mean, `LOW_VOLUME` below it.")
    A("- **The market-cap gate uses TradingView's live `market_cap_basic`**, not shibui's "
      "`valuation` table, which stores stale rows per symbol and can admit a phantom name if the "
      "cap filter is applied before the latest-row pick.")
    A("- **\"Prefer higher priced stocks\" is a ranking preference, not a filter** — the published "
      "gate is `c >= 5`; names are ordered by DCR then ADR.")
    A("- **`stop_class` is published on every row, not buried in prose.** `NOISE_BREACH` = the "
      "published stop sits inside the signal bar's own range, so the bar already traded through "
      "it; `CAPPED` = the 2.5% cap bound the stop while it still sits at/below the bar low; "
      "`STRUCTURAL` = the published stop is the structural level. `stop_vs_bar_low_pct` is signed: "
      "negative = the stop is below the bar low.")
    A("- **Bonde's discretionary step is mandatory**: the mechanical screen returns candidates, "
      "then the review reduces them to **1–3 ideas** (\"no catalyst, no trade\", \"the reversal bar "
      "has to jump off the chart\"). Every promoted idea carries a named catalyst and an "
      "invalidation test.")
    A("")
    A("| Source | Used for | Status |")
    A("|---|---|---|")
    A(f"| TradingView public scanner | live session OHLC for the universe | ok "
      f"({report.get('universe_rows', 0)} names) |")
    hist_src = report.get("history_source", "shibui")
    if hist_src == "shibui":
        A(f"| shibui-finance (bridge) | settled history, latest close | ok "
          f"(latest session {report.get('shibui_latest_sessions', ['n/a'])[:1]}) |")
    else:
        A(f"| shibui-finance (bridge) | settled history, latest close | **degraded** — the bridge "
          f"call failed on this run, so settled history came from the documented **{hist_src}** "
          f"fallback; the day-alignment check still resolved against those closes |")
    A("| market-recap (bridge) | market state / index backdrop | see caveats |")
    if hist_src != "shibui":
        A("")
        A(f"degraded_sources: 1 (shibui-finance settled history — the documented {hist_src} "
          f"fallback was used)")
    A("")
    A(f"_Generated by cron #4 `reversal-bullish-3:55` · tool `tools/reversal_bullish.py` · "
      f"session {a} · contract `{CONTRACT_VERSION}` · `_source=mcp`_")
    with open(path, "w") as fh:
        fh.write("\n".join(L) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    ap.add_argument("--bridge", default="/workspace/mcp_bridge.py")
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    date_str = args.date or et_now().strftime("%Y-%m-%d")
    out_dir = args.out_dir or f"/workspace/daily-screens/{date_str}"
    code, report = run(date_str, args.bridge, out_dir, dry_run=args.dry_run)
    print(f"exit={code} mode={report.get('mode')} passing={report.get('passing')}")
    sys.exit(code)


if __name__ == "__main__":
    main()
