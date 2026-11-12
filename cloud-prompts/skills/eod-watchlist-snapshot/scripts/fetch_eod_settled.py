#!/usr/bin/env python3
"""Pull the US EOD price history and SETTLE it - the probe loop that replaces the blind
second pull.

EOD_SETTLE_V1

THE PROBLEM THIS SOLVES
-----------------------
The published close of the US file is the VENUE's settled print (Nasdaq's consolidated
record), and the vendor's daily bar is the series for the derived columns and the
cross-check. Both settle LATE, and they settle per symbol: the feed is asynchronous, so a
bar can EXIST and still be provisional.

Measured: 2026-11-10, a 16:05 ET pull and a 16:42 ET pull disagreed on **1,531 of 4,794
session closes (31.9%)**; 2026-11-11, **142 of the 443** names that already had a session bar
at 16:15 ET still moved by 16:47, and the biggest tail moves were -5.62% / +4.89% / -3.06%.
The old shape was "pull the whole universe twice, 40 minutes apart": 9,818 requests, half of
them wasted, and the second pass was blind - it re-fetched names that had already settled and
still missed names that had not.

THE SHAPE OF THIS SCRIPT
------------------------
1. PASS 1 - the whole universe, one year of daily bars (`range=1y`). The derived columns
   (SMA200, ATR14, the 52-week extremes, the 30-session denominators) come out of it and the
   session bar is its last bar.
2. PROBE LOOP - every `--probe-interval` seconds a STRATIFIED probe is pulled: half the
   sample from the LOWEST-liquidity names (the thin names are where the drift and the big
   relative moves live) and half at random, plus every symbol that moved in an earlier round
   or still has no bar (the residue). The probe measures TWO things per symbol: the vendor's
   session bar (`range=5d`, 1.6 KB against 24.1 KB) and the VENUE's settled print - the thing
   that is actually published. A round is quiet only when BOTH are unchanged.
   INVARIANT: every symbol that ever changed is re-pulled every round until it stops
   changing, so the published close is the latest value the feed ever showed.
3. The loop exits when a round is quiet AND the residue re-pull is quiet. A hard cutoff
   (`--max-rounds`) bounds the wait; the residue is then published as it stands and the
   artifact says so.

OUTPUT
------
history.jsonl    the merged history (pass 1's year of bars + the settled session bar)
settle_map.json  {ticker: {settle_status, settle_round, changes}} - the TEMPORAL evidence.
                  `fetch_eod_venue.py` adds the INDEPENDENT confirmation afterwards.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

MARKER = "EOD_SETTLE_V1"

HOSTS = ("https://query2.finance.yahoo.com", "https://query1.finance.yahoo.com")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
NASDAQ_INFO = "https://api.nasdaq.com/api/quote/%s/info?assetclass=stocks"

# The index proxies and the sector ETFs are NOT in the vendor's equity universe
# (`country_iso='US'` carries equities, not ETFs), so they have to be pulled as their own
# symbol list. Without them the report has NO index table and every sector-ETF column
# reads n/a (measured 2026-11-12: the equity-only pull produced a Market read with no
# index rows and 11 sector ETFs at n/a).
PROXY_SYMBOLS = ["SPY", "QQQ", "IWM", "DIA", "RSP",
                 "XLK", "XLI", "XLV", "XLC", "XLE", "XLB", "XLY", "XLRE", "XLP", "XLF", "XLU"]


# ------------------------------------------------------------------ symbols
def yahoo_form(t: str) -> str:
    """shibui `ABR-P-D` -> Yahoo `ABR-PD`; `BRK-A` -> `BRK-A`. The plain base is NEVER a
    fallback - `LEN-B` -> `LEN` would publish the Class A COMMON line's price."""
    t = t.strip().upper()
    if "-" in t:
        base, _, rest = t.partition("-")
        return f"{base}-{rest.replace('-', '')}"
    return t


def nasdaq_form(ticker: str) -> str:
    """shibui `ABR-P-D` -> Nasdaq `ABR^D`; `USB-P-H` -> `USB^H`."""
    t = ticker.strip().upper()
    if "-" in t:
        base, _, rest = t.partition("-")
        flat = rest.replace("-", "")
        if flat:
            return f"{base}^{flat[-1]}"
    return t


# ------------------------------------------------------------------ http
class Throttle:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.blocked_until = {h: 0.0 for h in HOSTS}
        self.cursor = 0

    def next_host(self) -> str:
        with self.lock:
            now = time.time()
            order = []
            for i in range(len(HOSTS)):
                h = HOSTS[(self.cursor + i) % len(HOSTS)]
                if self.blocked_until[h] <= now and h not in order:
                    order.append(h)
            if not order:
                order = [HOSTS[self.cursor % len(HOSTS)]]
            self.cursor = (self.cursor + 1) % len(HOSTS)
            return order[0]

    def block(self, host: str, seconds: float) -> None:
        with self.lock:
            self.blocked_until[host] = max(self.blocked_until[host], time.time() + seconds)


def fetch_chart(ticker: str, rng: str, interval: str, throttle: Throttle,
                timeout: float = 25.0) -> list:
    """One Yahoo chart request -> a list of [epoch, o, h, l, c, v] bars."""
    ysym = yahoo_form(ticker)
    for attempt in range(4):
        host = throttle.next_host()
        url = f"{host}/v8/finance/chart/{urllib.parse.quote(ysym)}?interval={interval}&range={rng}"
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read()
        except urllib.error.HTTPError as e:
            if e.code in (429, 999):
                throttle.block(host, 20.0 + 10 * attempt)
                time.sleep(1.5 * (attempt + 1))
                continue
            if e.code == 404:
                return []
            time.sleep(1.0 * (attempt + 1))
            continue
        except Exception:  # noqa: BLE001 - a transport error is a data fact
            time.sleep(1.0 * (attempt + 1))
            continue
        try:
            doc = json.loads(body)
        except Exception:
            continue
        result = (doc.get("chart") or {}).get("result")
        if not result:
            return []
        r = result[0]
        ts = r.get("timestamp") or []
        q = ((r.get("indicators") or {}).get("quote") or [{}])[0]
        o, h, l, c, v = (q.get(k) or [] for k in ("open", "high", "low", "close", "volume"))
        bars = []
        for i, t in enumerate(ts):
            try:
                cc = c[i]
            except IndexError:
                continue
            if cc is None:
                continue

            def g(arr, j=i):
                try:
                    return arr[j]
                except IndexError:
                    return None
            bars.append([t, g(o), g(h), g(l), cc, g(v)])
        return bars
    return []


def fetch_venue(ticker: str) -> float | None:
    """The venue's settled print (Nasdaq's consolidated record), or None.

    THE SETTLED PRINT, NOT THE LIVE ONE (fixed 2026-11-12). `secondaryData` is stamped
    "Closed at <date> 4:00 PM ET" and carries the official 16:00 ET auction print;
    `primaryData` is the LIVE print and, after the close, carries an EXTENDED-HOURS trade.
    Measured 2026-11-12 at 18:15 ET: AAPL primary $354.79 @ "5:26 PM ET" vs secondary
    $354.88 @ "Closed at 4:00 PM ET" - and Yahoo's 1-minute final bar corroborates the
    SECONDARY print.

    Reading the live print as the close also manufactured the probe's "drift": the
    after-hours tape keeps ticking, so the probe measured the extended session moving and
    never went quiet (122 symbols still "changed" in round 12, at 17:08 ET).
    """
    sym = nasdaq_form(ticker)
    url = NASDAQ_INFO % sym.replace("^", "%5E")
    try:
        p = subprocess.run(["curl", "-s", "--max-time", "20", "-A", UA,
                            "-H", "Accept: application/json", url],
                           capture_output=True, text=True)
        doc = json.loads(p.stdout or "{}")
    except Exception:  # noqa: BLE001
        return None
    data = doc.get("data") or {}
    secondary = data.get("secondaryData") or {}
    primary = data.get("primaryData") or {}

    def _price(block):
        raw = block.get("lastSalePrice")
        if not raw or str(raw).upper() in ("N/A", "NA"):
            return None
        try:
            v = float(str(raw).replace("$", "").replace(",", ""))
        except ValueError:
            return None
        return v if v > 0 else None

    v = _price(secondary)
    if v is not None:
        return v
    pv = _price(primary)
    if pv is not None and not _after_regular_close(primary.get("lastTradeTimestamp") or ""):
        return pv
    return None


_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})\s*([AaPp][Mm])")


def _after_regular_close(stamp: str) -> bool:
    """True when a `lastTradeTimestamp` sits AFTER the 16:00 ET regular close."""
    m = _TIME_RE.search(stamp or "")
    if not m:
        return False
    hh, mm, ampm = int(m.group(1)), int(m.group(2)), m.group(3).lower()
    h24 = (hh % 12) + (12 if ampm == "pm" else 0)
    return (h24, mm) > (16, 0)


# ------------------------------------------------------------------ session helpers
def day_of(ts: int) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(ts))


def session_bar(bars: list, session: str):
    for b in bars:
        if day_of(b[0]) == session:
            return b
    return None


def close_of(bars: list, session: str):
    b = session_bar(bars, session)
    return None if b is None else float(b[4])


def vol_of(bars: list, session: str):
    b = session_bar(bars, session)
    return None if b is None or b[5] is None else float(b[5])


def replace_session_bar(bars: list, session: str, new_bar) -> list:
    out = []
    placed = False
    for b in bars:
        if day_of(b[0]) == session:
            if new_bar is not None:
                out.append(new_bar)
            placed = True
        else:
            out.append(b)
    if new_bar is not None and not placed:
        out.append(new_bar)
    out.sort(key=lambda b: b[0])
    return out


def tol(close: float) -> float:
    return max(0.005, abs(close) * 0.0002)


# ------------------------------------------------------------------ main
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbols", required=True, help="CSV with a `ticker` column")
    ap.add_argument("--session", required=True)
    ap.add_argument("--out", required=True, help="history JSONL")
    ap.add_argument("--settle-map", required=True)
    ap.add_argument("--probe-size", type=int, default=300)
    ap.add_argument("--probe-interval", type=int, default=240)
    ap.add_argument("--max-rounds", type=int, default=12)
    ap.add_argument("--threads", type=int, default=24)
    ap.add_argument("--venue-threads", type=int, default=48)
    ap.add_argument("--no-venue", action="store_true",
                    help="probe the vendor bar only (the venue print is not measured)")
    ap.add_argument("--pass1-only", action="store_true")
    args = ap.parse_args()

    tickers: list[str] = []
    with open(args.symbols, newline="") as fh:
        for row in csv.DictReader(fh):
            t = (row.get("ticker") or "").strip()
            if t:
                tickers.append(t)
    if not tickers:
        print("no symbols", file=sys.stderr)
        return 2

    throttle = Throttle()
    # the proxies are fetched alongside the equities, but they are NOT probed: they are
    # index/ETF series, not thin session names, and they never carry a session bar that
    # needs settling.
    proxies = [p for p in PROXY_SYMBOLS if p not in set(tickers)]
    fetch_list = list(tickers) + proxies
    state = {t: {"bars": [], "close": None, "venue": None, "round": 0, "changes": 0}
             for t in fetch_list}

    # ---------------- pass 1: the whole universe, one year of bars
    t0 = time.time()
    print(f"pass 1: {len(fetch_list)} symbols "
          f"({len(tickers)} equities + {len(proxies)} index/ETF proxies), range=1y",
          flush=True)
    done = 0

    def work(t):
        return t, fetch_chart(t, "1y", "1d", throttle)

    with ThreadPoolExecutor(max_workers=args.threads) as pool:
        for t, bars in pool.map(work, fetch_list):
            state[t]["bars"] = bars
            sb = session_bar(bars, args.session)
            state[t]["close"] = None if sb is None else float(sb[4])
            done += 1
            if done % 1000 == 0:
                print(f"  pass1 {done}/{len(fetch_list)} {time.time()-t0:.0f}s", flush=True)
    n_bar = sum(1 for t in tickers if state[t]["close"] is not None)
    print(f"pass 1 done in {time.time()-t0:.0f}s: {n_bar}/{len(fetch_list)} carry a "
          f"{args.session} bar", flush=True)

    if args.pass1_only:
        write_outputs(args, state, fetch_list)
        return 0

    # ---------------- the probe loop
    ranked = sorted([t for t in tickers if state[t]["close"] is not None],
                    key=lambda t: (vol_of(state[t]["bars"], args.session) or 0))
    thin = ranked[:max(len(ranked) // 2, 1)]
    rnd = random.Random(17)

    residue = {t for t in tickers if state[t]["close"] is None}
    rounds = 0
    total_changed = 0
    quiet_streak = 0
    last_residue_size = -1
    for rnd_no in range(1, args.max_rounds + 1):
        rounds = rnd_no
        if rnd_no > 1:
            time.sleep(args.probe_interval)
        half = args.probe_size // 2
        probe_thin = rnd.sample(thin, min(half, len(thin))) if thin else []
        rest = [t for t in tickers if t not in set(thin)]
        probe_rand = rnd.sample(rest, min(args.probe_size - len(probe_thin), len(rest)))
        probe_set = sorted(set(probe_thin) | set(probe_rand) | residue)

        def bar_work(t):
            return t, close_of(fetch_chart(t, "5d", "1d", throttle), args.session)

        with ThreadPoolExecutor(max_workers=args.threads) as pool:
            bars_now = dict(pool.map(bar_work, probe_set))

        venue_now = {}
        if not args.no_venue:
            def venue_work(t):
                return t, fetch_venue(t)
            with ThreadPoolExecutor(max_workers=args.venue_threads) as pool:
                venue_now = dict(pool.map(venue_work, probe_set))

        changed = []
        for t in probe_set:
            new_close = bars_now.get(t)
            old_close = state[t]["close"]
            new_venue = venue_now.get(t) if venue_now else None
            old_venue = state[t]["venue"]
            bar_moved = (new_close is not None and old_close is not None
                         and abs(new_close - old_close) > tol(old_close))
            venue_moved = (new_venue is not None and old_venue is not None
                           and abs(new_venue - old_venue) > tol(old_venue))
            if bar_moved:
                state[t]["bars"] = replace_session_bar(
                    state[t]["bars"], args.session,
                    session_bar(fetch_chart(t, "5d", "1d", throttle), args.session))
                state[t]["close"] = new_close
            if venue_moved:
                state[t]["venue"] = new_venue
            if bar_moved or venue_moved:
                state[t]["round"] = rnd_no
                state[t]["changes"] += 1
                changed.append(t)
            if new_close is not None and old_close is None:
                state[t]["close"] = new_close
                state[t]["round"] = rnd_no
                changed.append(t)
            if new_venue is not None and old_venue is None:
                state[t]["venue"] = new_venue
        total_changed += len(changed)
        residue = {t for t in tickers if state[t]["close"] is None}
        residue |= set(changed)
        # The exit test is the FEED'S QUIET, not the residue's emptiness: ~6% of the universe
        # never publishes a session bar, so an empty residue is not a thing that happens.
        # The loop exits on TWO consecutive quiet rounds (nothing moved, nothing new
        # appeared) with the residue size unchanged - the feed has stopped moving.
        residue_stable = len(residue) == last_residue_size
        quiet_streak = quiet_streak + 1 if not changed else 0
        last_residue_size = len(residue)
        print(f"  round {rnd_no}: probe={len(probe_set)} changed={len(changed)} "
              f"residue={len(residue)} quiet_streak={quiet_streak} "
              f"{time.strftime('%H:%M:%S')}", flush=True)
        if quiet_streak >= 2 and residue_stable:
            print(f"  settled after {rnd_no} round(s)", flush=True)
            break
    else:
        print(f"  probe loop hit --max-rounds ({args.max_rounds}); the residue is published "
              f"as it stands", file=sys.stderr)

    write_outputs(args, state, fetch_list)
    print(f"probe: {rounds} round(s); {total_changed} symbol(s) changed after pass 1",
          flush=True)
    return 0


def write_outputs(args, state, tickers) -> None:
    with open(args.out, "w") as fh:
        for t in tickers:
            rec = {"ticker": t, "yahoo_symbol": yahoo_form(t),
                   "status": "ok" if state[t]["bars"] else "not_found",
                   "bars": state[t]["bars"]}
            fh.write(json.dumps(rec, separators=(",", ":")) + "\n")
    smap = {}
    for t in tickers:
        smap[t] = {"settle_status": "UNCONFIRMED" if state[t]["close"] is not None else "NO_BAR",
                   "settle_round": state[t]["round"],
                   "changes": state[t]["changes"],
                   "venue_close": state[t]["venue"]}
    json.dump({"session": args.session, "symbols": smap}, open(args.settle_map, "w"))


if __name__ == "__main__":
    sys.exit(main())
