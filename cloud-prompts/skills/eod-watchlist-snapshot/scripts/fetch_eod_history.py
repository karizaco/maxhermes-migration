#!/usr/bin/env python3
"""Fetch daily price history for the US EOD universe (cron #20 derived-column stage).

EOD_DERIVE_V2 — one history pull per symbol, one output file, one bar set.

WHY THIS EXISTS
---------------
The fleet's derived columns (rel_volume, sma_20/50/200, atr_14, pct_from_52w_high/low,
gap_pct, avg_daily_dollar_volume) used to be re-derived by every downstream routine on its
own, from whatever it happened to have. That is how the fleet ended up with several
definitions of relative volume. This script pulls the history ONCE, into one file, and the
derive engine (`eod_derive.py`) turns it into the published columns.

THE SOURCE
----------
Yahoo's daily chart API: `/v8/finance/chart/{SYMBOL}?interval=1d&range=1y`.
No crumb is required for the chart endpoint (the crumb is a quoteSummary/options requirement).

Yahoo's availability is PER-EGRESS — query1 can 429 while query2 answers from the same
sandbox. So the script rotates between both hosts and treats 429/404 as "try the other
host / no data for this symbol", never as a global failure. A 429 is a rate limit, not an
absence; a 404 for one symbol is that symbol's data, not the source's.

CLASS-SHARE SYMBOL FORMS ARE PER-VENDOR
----------------------------------------
shibui writes `ABR-P-E`; Yahoo serves `ABR-PE` (base + "-" + the class letters with their
hyphens removed). `USB-P-H` -> `USB-PH`. A plain-base fallback (`LEN-B` -> `LEN`) returns
the Class A COMMON line — a DIFFERENT security's price, which is worse than no data, so
this script never falls back to the plain base.

OUTPUT (JSONL, one line per symbol, resumable)
-----------------------------------------------
{"ticker": "<shibui ticker>", "yahoo_symbol": "<symbol used>",
 "status": "ok|not_found|error", "bars": [[epoch, open, high, low, close, volume], ...]}
Bars are DAILY, ascending, and are the vendor's split-adjusted series.

USAGE
-----
  python3 fetch_eod_history.py --symbols universe.csv --out history.jsonl \
      --session 2026-11-05 --threads 24
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

MARKER = "EOD_DERIVE_V2"

HOSTS = (
    "https://query2.finance.yahoo.com",
    "https://query1.finance.yahoo.com",
)
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


# --------------------------------------------------------------------------- symbol maps
def yahoo_form(ticker: str) -> str:
    """Map a shibui ticker to Yahoo's own form for the same security.

    `ABR-P-E` -> `ABR-PE`   (base + "-" + the class letters, hyphens removed)
    `USB-P-H` -> `USB-PH`
    `BRK-A`   -> `BRK-A`    (single-letter class lines are already Yahoo's form)
    `LEN-B`   -> `LEN-B`

    The plain base is NEVER substituted: `LEN-B` -> `LEN` would silently publish the
    Class A COMMON line's price under the Class B ticker.
    """
    t = ticker.strip().upper()
    if "-" in t:
        base, _, rest = t.partition("-")
        return f"{base}-{rest.replace('-', '')}"
    return t


def nasdaq_form(ticker: str) -> str:
    """Map a shibui ticker to Nasdaq's own form (`ABR-P-E` -> `ABR^E`)."""
    t = ticker.strip().upper()
    if "-" in t:
        base, _, rest = t.partition("-")
        return f"{base}^{rest.replace('-', '')[-1]}"
    return t


# --------------------------------------------------------------------------- http
class Throttle:
    """Per-host backoff: a 429 on one host pushes that host out of rotation briefly."""

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
                if self.blocked_until[h] <= now:
                    order.append(h)
            if not order:
                order = [HOSTS[self.cursor % len(HOSTS)]]
            self.cursor = (self.cursor + 1) % len(HOSTS)
            return order[0]

    def block(self, host: str, seconds: float) -> None:
        with self.lock:
            self.blocked_until[host] = max(self.blocked_until[host], time.time() + seconds)


def fetch_one(ticker: str, session: str, throttle: Throttle, timeout: float = 25.0) -> dict:
    """Fetch one symbol's daily history. Returns the output record for the JSONL."""
    ysym = yahoo_form(ticker)
    last_err = "unknown"
    for attempt in range(4):
        host = throttle.next_host()
        url = f"{host}/v8/finance/chart/{urllib.parse.quote(ysym)}?interval=1d&range=1y"
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read()
        except urllib.error.HTTPError as e:
            if e.code in (429, 999):
                throttle.block(host, 20.0 + 10 * attempt)
                last_err = f"http_{e.code}"
                time.sleep(1.5 * (attempt + 1))
                continue
            if e.code == 404:
                return {"ticker": ticker, "yahoo_symbol": ysym, "status": "not_found",
                        "bars": [], "error": "http_404"}
            last_err = f"http_{e.code}"
            time.sleep(1.0 * (attempt + 1))
            continue
        except Exception as e:  # noqa: BLE001 - transport error is a data fact
            last_err = type(e).__name__
            time.sleep(1.0 * (attempt + 1))
            continue

        try:
            doc = json.loads(body)
        except Exception:
            last_err = "unparseable"
            continue
        result = (doc.get("chart") or {}).get("result")
        if not result:
            err = ((doc.get("chart") or {}).get("error") or {}).get("description", "no_result")
            if "not found" in err.lower() or "No data" in err:
                return {"ticker": ticker, "yahoo_symbol": ysym, "status": "not_found",
                        "bars": [], "error": err[:80]}
            last_err = err[:60]
            continue
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
            # keep bars up to and including the session (UTC day == ET day for 16:00 ET bars)
            day = time.strftime("%Y-%m-%d", time.gmtime(t))
            if day > session:
                continue
            def g(arr, j=i):
                try:
                    x = arr[j]
                except IndexError:
                    return None
                return x
            bars.append([t, g(o), g(h), g(l), cc, g(v)])
        return {"ticker": ticker, "yahoo_symbol": ysym, "status": "ok", "bars": bars}

    return {"ticker": ticker, "yahoo_symbol": ysym, "status": "error", "bars": [],
            "error": last_err}


# --------------------------------------------------------------------------- cli
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbols", required=True,
                    help="CSV with a `ticker` column (shibui ticker form)")
    ap.add_argument("--out", required=True, help="output JSONL path")
    ap.add_argument("--session", required=True, help="session date YYYY-MM-DD")
    ap.add_argument("--threads", type=int, default=24)
    ap.add_argument("--resume", action="store_true",
                    help="keep already-fetched symbols in --out and fetch only the rest")
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

    done: dict[str, dict] = {}
    mode = "w"
    if args.resume and os.path.exists(args.out):
        mode = "a"
        with open(args.out) as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                done[rec["ticker"]] = rec
        tickers = [t for t in tickers if t not in done]
        print(f"resume: {len(done)} already fetched, {len(tickers)} to go")

    throttle = Throttle()
    lock = threading.Lock()
    fh = open(args.out, mode, buffering=1 << 20)
    counts = {"ok": 0, "not_found": 0, "error": 0}
    t0 = time.time()

    def work(t: str) -> None:
        rec = fetch_one(t, args.session, throttle)
        with lock:
            fh.write(json.dumps(rec, separators=(",", ":")) + "\n")
            counts[rec["status"]] = counts.get(rec["status"], 0) + 1
            n = sum(counts.values())
            if n % 250 == 0:
                rate = n / max(time.time() - t0, 1e-9)
                print(f"  {n}/{len(tickers)} ok={counts['ok']} nf={counts['not_found']} "
                      f"err={counts['error']} {rate:.1f}/s", flush=True)

    with ThreadPoolExecutor(max_workers=args.threads) as pool:
        list(pool.map(work, tickers))
    fh.close()
    print(f"done: {counts} in {time.time() - t0:.0f}s -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
