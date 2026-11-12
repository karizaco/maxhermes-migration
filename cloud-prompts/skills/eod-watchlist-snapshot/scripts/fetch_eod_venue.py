#!/usr/bin/env python3
"""Pull the VENUE's settled print for the US EOD universe.

EOD_SETTLE_V1

WHY THE VENUE
-------------
The published close of the US file is the **venue's settled print** - Nasdaq's consolidated
record - and NOT Yahoo's daily bar. Measured 2026-11-11: the venue and Yahoo's settled daily
bar agree within 0.01% on 2,652 of 4,774 rows, within 0.1% on 3,847, and differ by 0.5% or
more on **314 rows** (14 above 5%): MDBH 1.51 vs 1.7195, TVGN 5.47 vs 6.00, VRM 6.45 vs 6.99.
On those thin names Yahoo's bar holds a **pre-auction print**, and Yahoo's synthetic 1-minute
final bar carries the session's HIGH or LOW rather than the close. The venue's print is the
close of record; the vendor's bar is the cross-check and the series for the derived columns.

THE ENDPOINT
------------
`GET https://api.nasdaq.com/api/quote/{SYMBOL}/info?assetclass=stocks`

  data.primaryData.lastSalePrice    the venue's last sale price, e.g. "$355.63" (the string
                                     carries a `$` and thousands separators, and a thin name
                                     carries 3 decimals: "$7.135")
  data.primaryData.volume            the venue's session volume, e.g. "34,453,477"
  data.primaryData.lastTradeTimestamp  the session date, e.g. "Nov 11, 2026"
  data.secondaryData.lastSalePrice   the same print for the symbols that serve it there
  data.keyStats.dayrange             "NA" on this endpoint - the day range is NOT here

A symbol Nasdaq does not serve answers HTTP 200 with `status.rCode != 200` and a
"Symbol not exists" message: that is a MISSING ROW, not a failure - it is recorded as such.

CLASS-SHARE SYMBOL FORMS ARE PER VENDOR
---------------------------------------
shibui writes `ABR-P-D`; Nasdaq serves `ABR^D` (base + "^" + the LAST class letter) and
`USB^H`. The plain base is NEVER a fallback - `LEN-B` -> `LEN` would publish the Class A
COMMON line's price under the Class B ticker.

NO TRADINGVIEW UNIVERSE PULL (removed 2026-11-12)
------------------------------------------------
This module used to carry a TradingView universe pull (`fetch_tv()`) as a confirmation
source. It was **dead code** - added 2026-11-12 and never wired in - and it was WRONG twice
over, so it is gone rather than repaired:

1. **TV corroborates the BAR, not the venue.** Measured 2026-11-11: the TV America scanner
   agrees with the VENDOR'S DAILY BAR on 4,497 of 4,526 rows (99.4%) and with the VENUE's
   settled print on only **67.8%**. TV is therefore not a confirmation source for the
   published close, which is the venue's print. The live confirmation is Yahoo's 1-minute
   FINAL bar (a different feed, so agreement is real corroboration).
2. **Its pagination lost names.** The pull paged the universe on `sort {"sortBy":"close"}`
   - a LIVE column, so the page order is not stable between requests. Measured 2026-11-12:
   20,343-20,345 names against a `totalCount` of 20,347 (**2-5 names missing**) and **two
   identical pulls returned DIFFERENT name sets** (IVRO, LYCA in one run only; AGCCF in the
   other). The same pull paged on `{"sortBy":"name"}` returned 20,347 == `totalCount`, every
   time. The `totalCount == rows returned` check cannot see this - it is a SET test (the
   pages must be DISJOINT and their UNION must equal `totalCount`).

**Do NOT re-add a TV universe pull here.** If a TV cross-check is ever wanted, it must be a
TARGETED pull of the names already in hand - `filter [{"left":"name","operation":"in_range",
"right":[...]}]` in ONE call - and it must assert `len(unique names) == totalCount`.
See `cloud-prompts/_shared/RUNTIME-CONTRACT.md` §2a-bis.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

MARKER = "EOD_SETTLE_V1"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
INFO = "https://api.nasdaq.com/api/quote/%s/info?assetclass=stocks"
TV_SCAN = "https://scanner.tradingview.com/america/scan"   # not queried any more (see the module note)


def nasdaq_form(ticker: str) -> str:
    """shibui `ABR-P-D` -> Nasdaq `ABR^D`; `USB-P-H` -> `USB^H`; `AAPL` -> `AAPL`.
    The plain base is never substituted for a class line."""
    t = ticker.strip().upper()
    if "-" in t:
        base, _, rest = t.partition("-")
        flat = rest.replace("-", "")
        if flat:
            return f"{base}^{flat[-1]}"
    return t


def parse_num(x):
    if x is None:
        return None
    s = str(x).strip().replace("$", "").replace(",", "").replace("%", "")
    if not s or s.upper() in ("N/A", "NA", "--"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def tv_candidates(t: str) -> list[str]:
    """TradingView's symbol forms for a shibui ticker. TV uses a DOT for a single class
    letter (`AGM-A` -> `AGM.A`) and carries no hyphenated form, so the preferred lines
    (`ABR-P-D`) are usually absent from its America scanner.

    KEPT AS A SYMBOL-FORM HELPER ONLY. There is no TradingView QUERY behind it any more:
    the TV universe pull that used to sit next to it was DEAD CODE (added 2026-11-12, never
    wired in) and it was WRONG - see the module note."""
    t = t.strip().upper()
    out = [t]
    if "-" in t:
        base, _, rest = t.partition("-")
        flat = rest.replace("-", "")
        out.append(f"{base}-{flat}")
        out.append(f"{base}.{flat}")
    seen = []
    for c in out:
        if c not in seen:
            seen.append(c)
    return seen




def fetch_final_bars(tickers: list[str], threads: int) -> dict:
    """Yahoo's 1-minute FINAL bar per symbol (O=H=L=C, volume 0) - the independent reading
    of the 16:00 ET auction print. On thin names it carries the session's high or low
    instead of the close, which is why a disagreement is published, never smoothed."""
    ua = UA

    def work(t):
        ysym = t.strip().upper()
        if "-" in ysym:
            base, _, rest = ysym.partition("-")
            ysym = f"{base}-{rest.replace('-', '')}"
        url = (f"https://query2.finance.yahoo.com/v8/finance/chart/{ysym}"
               f"?interval=1m&range=1d")
        try:
            p = subprocess.run(["curl", "-s", "--max-time", "20", "-A", ua, url],
                               capture_output=True, text=True)
            doc = json.loads(p.stdout or "{}")
            res = ((doc.get("chart") or {}).get("result")) or []
            if not res:
                return t, None
            q = ((res[0].get("indicators") or {}).get("quote") or [{}])[0]
            closes = q.get("close") or []
            for i in range(len(closes) - 1, -1, -1):
                if closes[i] is not None:
                    return t, float(closes[i])
        except Exception:  # noqa: BLE001
            pass
        return t, None

    out: dict[str, float] = {}
    with ThreadPoolExecutor(max_workers=threads) as pool:
        for t, v in pool.map(work, tickers):
            if v is not None:
                out[t] = v
    return out


def fetch_day_range(ticker: str) -> tuple[str, dict]:
    """The venue's own day range: `GET /api/quote/{SYM}/summary` -> summaryData.TodayHighLow
    ("$1.7195/$1.5100")."""
    sym = nasdaq_form(ticker)
    url = "https://api.nasdaq.com/api/quote/%s/summary?assetclass=stocks" % sym.replace("^", "%5E")
    try:
        p = subprocess.run(["curl", "-s", "--max-time", "20", "-A", UA,
                            "-H", "Accept: application/json", url],
                           capture_output=True, text=True)
        doc = json.loads(p.stdout or "{}")
    except Exception:  # noqa: BLE001
        return ticker, {}
    data = doc.get("data") or {}
    raw = ((data.get("summaryData") or {}).get("TodayHighLow") or {}).get("value")
    if not raw or "/" not in str(raw):
        return ticker, {}
    hi_s, _, lo_s = str(raw).partition("/")
    hi = parse_num(hi_s)
    lo = parse_num(lo_s)
    if hi is None or lo is None:
        return ticker, {}
    return ticker, {"day_high": hi, "day_low": lo}


def rows_needing_venue_range(tickers, venue, history_path, quotes_path, session) -> list[str]:
    """The rows whose published close no candidate range brackets."""
    import time as _time
    hist: dict[str, list] = {}
    for line in open(history_path):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        bars = rec.get("bars") or []
        for b in bars:
            if len(b) >= 6 and _time.strftime("%Y-%m-%d", _time.gmtime(int(b[0]))) == session:
                hist[rec.get("ticker", "")] = b
                break
    quotes = json.load(open(quotes_path)) if os.path.exists(quotes_path) else {}
    need = []
    for t in tickers:
        close = (venue.get(t) or {}).get("close")
        if close is None:
            continue
        cands = []
        b = hist.get(t)
        if b and b[2] is not None and b[3] is not None:
            cands.append((b[3], b[2]))
        q = quotes.get(t) or {}
        if q.get("dayHigh") is not None and q.get("dayLow") is not None:
            cands.append((q["dayLow"], q["dayHigh"]))
        if not any(lo <= close <= hi for lo, hi in cands):
            need.append(t)
    return need


def fetch_one(ticker: str, timeout: float = 25.0) -> tuple[str, dict]:
    sym = nasdaq_form(ticker)
    url = INFO % sym.replace("^", "%5E")
    try:
        p = subprocess.run(["curl", "-s", "--max-time", str(int(timeout)), "-A", UA,
                            "-H", "Accept: application/json", url],
                           capture_output=True, text=True)
        doc = json.loads(p.stdout or "{}")
    except Exception as e:  # noqa: BLE001 - a transport error is a data fact
        return ticker, {"ok": False, "error": type(e).__name__, "nasdaq_symbol": sym}
    status = doc.get("status") or {}
    data = doc.get("data") or {}
    if not data:
        return ticker, {"ok": False, "error": "no_data", "nasdaq_symbol": sym,
                        "message": str(status.get("bCodeMessage") or "")[:80]}
    primary = data.get("primaryData") or {}
    secondary = data.get("secondaryData") or {}
    close = parse_num(primary.get("lastSalePrice"))
    if close is None:
        close = parse_num(secondary.get("lastSalePrice"))
    vol = parse_num(primary.get("volume"))
    if vol is None:
        vol = parse_num(secondary.get("volume"))
    return ticker, {
        "ok": close is not None,
        "nasdaq_symbol": sym,
        "close": close,
        "volume": vol,
        "exchange": data.get("exchange") or "",
        "session_stamp": primary.get("lastTradeTimestamp") or "",
        "error": "" if close is not None else "no_close",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbols", required=True, help="CSV with a `ticker` column")
    ap.add_argument("--out", required=True, help="venue.json")
    ap.add_argument("--settle-map", default="",
                    help="the probe's settle map - updated in place with the confirmation")
    ap.add_argument("--threads", type=int, default=96)
    ap.add_argument("--timeout", type=int, default=25)
    ap.add_argument("--no-tv", action="store_true",
                    help="DEPRECATED NO-OP. There is no TradingView confirmation to skip: "
                         "the TV universe pull was removed on 2026-11-12 (TV corroborates the "
                         "BAR, not the venue - see the module note). The flag is still "
                         "accepted so an existing invocation does not fail.")
    ap.add_argument("--history", default="", help="history JSONL - used to find the rows that need the venue's day range")
    ap.add_argument("--quotes", default="", help="quotes.json - the same purpose")
    ap.add_argument("--session", default="", help="the session date (for the range pass)")
    ap.add_argument("--skip-info", action="store_true", help="reuse the venue records already in --out")
    ap.add_argument("--skip-range", action="store_true", help="skip the venue day-range pass")
    ap.add_argument("--skip-confirm", action="store_true", help="skip the independent confirmation")
    args = ap.parse_args()

    tickers: list[str] = []
    with open(args.symbols, newline="") as fh:
        reader = csv_rows(fh)
        for row in reader:
            t = (row.get("ticker") or "").strip()
            if t:
                tickers.append(t)
    if not tickers:
        print("no symbols", file=sys.stderr)
        return 2

    out: dict[str, dict] = {}
    if args.skip_info and os.path.exists(args.out):
        out = json.load(open(args.out))
        print(f"venue: reusing {len(out)} records from {args.out}")
    else:
        lock = threading.Lock()
        t0 = time.time()
        done = 0
        with ThreadPoolExecutor(max_workers=args.threads) as pool:
            for ticker, rec in pool.map(lambda t: fetch_one(t, args.timeout), tickers):
                with lock:
                    out[ticker] = rec
                done += 1
                if done % 1000 == 0:
                    print(f"  venue {done}/{len(tickers)} {time.time()-t0:.0f}s", flush=True)
        json.dump(out, open(args.out, "w"))
        ok = sum(1 for v in out.values() if v.get("ok"))
        print(f"venue: {ok}/{len(tickers)} settled prints in {time.time()-t0:.0f}s -> {args.out}")

    # ---- the VENUE'S DAY RANGE, for the rows whose close no candidate range brackets.
    #
    # The published close is the venue's settled print, and on a thin name that print can sit
    # OUTSIDE the vendor's bar range (the bar holds a pre-auction print). The venue's own
    # day range (`/summary` -> `TodayHighLow`) is the only range that brackets it, so it is
    # pulled for exactly those rows - not for the whole universe.
    if args.history and args.quotes and not args.skip_range:
        need = rows_needing_venue_range(tickers, out, args.history, args.quotes, args.session)
        print(f"venue range: {len(need)} row(s) need the venue's own day range", flush=True)
        if need:
            with ThreadPoolExecutor(max_workers=args.threads) as pool:
                for t, rec in pool.map(fetch_day_range, need):
                    if rec.get("day_high") is not None:
                        out[t] = {**out.get(t, {}), **rec}
            json.dump(out, open(args.out, "w"))

    # ---- the INDEPENDENT CONFIRMATION of the published close.
    #
    # The published close is the VENUE's settled print. The independent reading is Yahoo's
    # 1-minute FINAL bar (O=H=L=C, volume 0) - a different feed, so an agreement is a real
    # corroboration. MEASURED 2026-11-11: the TradingView America scanner agrees with the
    # VENDOR'S DAILY BAR on 4,497 of 4,526 rows (99.4%) and with the VENUE's print on only
    # 67.8% - TV corroborates the BAR, not the venue, so it must NOT be used to confirm the
    # published close. And on thin names Yahoo's synthetic bar carries the session's high or
    # low rather than the close, so a disagreement there is EXPECTED and the row is published
    # as UNCONFIRMED rather than smoothed.
    #
    # CNBC/CTA is the fleet's third source but it is only usable INSIDE the session window:
    # outside it, `last_time` degrades to a DATE ("2026-11-11") and the "stamped exactly
    # 16:00:00" test cannot be applied.
    if args.settle_map and not args.skip_confirm:
        final_bar = fetch_final_bars(tickers, args.threads)
        # the PUBLISHED close falls back to the vendor's settled bar when the venue carries
        # no print (29 rows on 2026-11-11) - so the status must follow the published close,
        # not the venue's: a row that publishes the bar's close is UNCONFIRMED (or
        # CONFIRMED if the final bar agrees), never NO_BAR.
        bar_close = {}
        if args.history and os.path.exists(args.history):
            import time as _time
            for line in open(args.history):
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                for b in rec.get("bars") or []:
                    if len(b) >= 6 and _time.strftime("%Y-%m-%d",
                                                        _time.gmtime(int(b[0]))) == args.session:
                        bar_close[rec.get("ticker", "")] = float(b[4])
                        break
        blob = json.load(open(args.settle_map))
        smap = blob.get("symbols") or blob
        conf = unconf = nobar = 0
        for t in tickers:
            sm = smap.get(t) or {}
            published = (out.get(t) or {}).get("close")
            if published is None:
                published = sm.get("venue_close")
            if published is None:
                published = bar_close.get(t)
            if published is None:
                sm["settle_status"] = "NO_BAR"
                nobar += 1
                smap[t] = sm
                continue
            fb = final_bar.get(t)
            if fb is not None and abs(fb - published) <= max(0.005, abs(published) * 0.0005):
                sm["settle_status"] = "CONFIRMED"
                sm["confirmed_by"] = "yahoo_final_bar"
                sm["independent_close"] = fb
                conf += 1
            else:
                sm["settle_status"] = "UNCONFIRMED"
                sm["confirmed_by"] = ""
                if fb is not None:
                    sm["independent_close"] = fb
                    sm["independent_delta"] = fb - published
                unconf += 1
            smap[t] = sm
        json.dump({"session": blob.get("session"), "symbols": smap},
                  open(args.settle_map, "w"))
        print(f"confirmation: {conf} CONFIRMED, {unconf} UNCONFIRMED, {nobar} NO_BAR "
              f"(the 1-minute final bar resolved {sum(1 for v in final_bar.values() if v)}"
              f"/{len(tickers)})", flush=True)
    return 0


def csv_rows(fh):
    import csv as _csv
    return _csv.DictReader(fh)


if __name__ == "__main__":
    sys.exit(main())
