#!/usr/bin/env python3
"""
preopen_feed.py — gap provenance for the us-stocks-in-play digest.

WHAT THIS SOLVES
----------------
Cron #17 fires at 15:50 ET. From that point it can see where a stock IS, but not where it
CAME FROM. A name that gapped +12% on an FDA approval at 09:12 and now trades +2% looks
identical to one that never moved. "In play" is a claim about the *journey*, and the
journey is what the digest was missing.

This tool rebuilds that journey from 5-minute bars, and — when a catalyst feed is
available — attaches the *reason* and the *timestamp* of the move.

TWO INDEPENDENT SOURCES, TWO JOBS
----------------------------------
  prices  -> Yahoo chart API, interval=5m        (ground truth, always available)
  reason  -> preopen-feed/{date}.jsonl           (optional; absent is NOT an error)

The feed is optional by design. `provenance` works with no feed at all; `merge` adds the
catalyst column when the feed exists and degrades cleanly when it does not.

VERDICT LOGIC
-------------
  held        the move from the open is still largely intact at the decision time
  faded       the open move has been substantially given back
  no_move     the open move was inside the noise band, so there is no gap to fade
  reverse     the sign flipped (gapped up, now down, or the reverse) — the strongest form

USAGE
  preopen_feed.py provenance --date 2026-10-23 --symbols CCI,XLAB
  preopen_feed.py feed       --date 2026-11-03
  preopen_feed.py merge      --date 2026-10-23 --symbols CCI,XLAB
  preopen_feed.py selftest

EXIT CODES
  0 = ran (a missing feed is reported as `feed_absent`, not an error)
  1 = a data source failed outright
  2 = usage error
"""

import argparse
import datetime
import json
import os
import sys
import urllib.error
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
ET = None

# A gap smaller than this is noise, not a gap. Tuned against the four known sessions.
NOISE_BAND_PCT = 2.0
# How much of the open move must survive for the verdict to be "held".
HELD_RATIO = 0.50

# The capture routine may write several checkpoints per day (0830/0920/0950 ET), each to
# its own file, so three crons never clobber each other. Read them all, oldest first.
FEED_RAW = ("https://raw.githubusercontent.com/karizaco/minimax-cloud-outputs/main/"
            "preopen-feed/{date}-{cp}.jsonl")
FEED_LOCAL = "/workspace/preopen-feed/{date}-{cp}.jsonl"
FEED_CHECKPOINTS = ("0830", "0920", "0950")

CAT_VOCAB = {"acquisition", "merger", "earnings", "guidance", "fda", "trial", "offering",
             "halt", "downgrade", "guidance-cut", "spin", "dividend", "other"}


def _et():
    global ET
    if ET is None:
        try:
            from zoneinfo import ZoneInfo
            ET = ZoneInfo("America/New_York")
        except Exception:
            ET = datetime.timezone(datetime.timedelta(hours=-5))
    return ET


def _get(url, timeout=30):
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=timeout).read()


def _ts(date_str, hh, mm=0):
    d = datetime.date.fromisoformat(date_str)
    return int(datetime.datetime(d.year, d.month, d.day, hh, mm, tzinfo=_et()).timestamp())


def prior_close(symbol, date_str, lookback=5):
    """Last completed session's close before `date_str`."""
    d = datetime.date.fromisoformat(date_str)
    p1 = int(datetime.datetime(d.year, d.month, d.day, tzinfo=_et()).timestamp()) - lookback * 86400
    p2 = int(datetime.datetime(d.year, d.month, d.day, tzinfo=_et()).timestamp()) + 86400
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
           f"?period1={p1}&period2={p2}&interval=1d")
    try:
        res = json.loads(_get(url))["chart"]["result"][0]
    except Exception:
        return None
    ts = res.get("timestamp") or []
    q = res["indicators"]["quote"][0]
    best = None
    for i, t in enumerate(ts):
        day = datetime.datetime.fromtimestamp(t, _et()).strftime("%Y-%m-%d")
        if day < date_str and q["close"][i]:
            best = q["close"][i]
    return best


def intraday_path(symbol, date_str):
    """{HH:MM: {px, chg_pct}} for the session, plus the prior close."""
    d = datetime.date.fromisoformat(date_str)
    p1 = int(datetime.datetime(d.year, d.month, d.day, tzinfo=_et()).timestamp()) - 86400
    p2 = int(datetime.datetime(d.year, d.month, d.day, tzinfo=_et()).timestamp()) + 86400
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
           f"?period1={p1}&period2={p2}&interval=5m&includePrePost=true")
    try:
        res = json.loads(_get(url))["chart"]["result"][0]
    except Exception:
        return {"error": "yahoo_5m_failed"}
    ts = res.get("timestamp") or []
    q = res["indicators"]["quote"][0]
    prev = prior_close(symbol, date_str)
    marks = {}
    for i, t in enumerate(ts):
        lt = datetime.datetime.fromtimestamp(t, _et())
        if lt.strftime("%Y-%m-%d") != date_str:
            continue
        if lt.hour < 9 or lt.hour > 16:
            continue
        hm = lt.strftime("%H:%M")
        if hm in ("09:30", "09:35", "10:00", "12:00", "15:50", "16:00") and q["open"][i]:
            marks[hm] = {"px": round(q["open"][i], 4),
                         "chg_pct": round((q["open"][i] / prev - 1) * 100, 2) if prev else None}
    marks["_prior_close"] = round(prev, 4) if prev else None
    return marks


def scanner_premarket(symbols):
    """Ground-truth premarket prints + halted flag from the TradingView scanner."""
    cols = ["name", "description", "close", "change", "volume", "relative_volume_10d_calc",
            "market_cap_basic", "premarket_change", "premarket_volume", "premarket_close",
            "halted", "exchange"]
    body = {"filter": [{"left": "type", "operation": "equal", "right": "stock"},
                       {"left": "name", "operation": "in_range", "right": list(symbols)}],
            "columns": cols, "range": [0, len(symbols) + 5]}
    req = urllib.request.Request("https://scanner.tradingview.com/america/scan",
                                 data=json.dumps(body).encode(), headers={**UA, "Content-Type": "application/json"})
    try:
        res = json.loads(urllib.request.urlopen(req, timeout=30).read())
    except Exception as exc:
        return {"error": f"scanner_failed: {str(exc)[:120]}"}
    out = {}
    for row in res.get("data") or []:
        s = row["d"]
        out[s[0]] = {"name": s[1], "close": s[2], "change_pct": s[3], "volume": s[4],
                     "rvol10": s[5], "market_cap": s[6], "premarket_change": s[7],
                     "premarket_volume": s[8], "premarket_close": s[9], "halted": s[10],
                     "exchange": s[11]}
    return out


def verdict(open_pct, now_pct):
    """Classify what happened to the opening move.

    `reverse` covers BOTH directions: a gap down that flips up is as much a reversal as a
    gap up that flips down (XLAB on 2026-10-15: gapped -8.2%, closed +49.6%).
    """
    if open_pct is None or now_pct is None:
        return "unknown"
    if abs(open_pct) < NOISE_BAND_PCT:
        return "no_move"
    if open_pct * now_pct < 0:          # sign flip, either direction
        return "reverse"
    moved = abs(now_pct - open_pct)
    kept = abs(now_pct)
    if kept >= abs(open_pct) * HELD_RATIO:
        return "held"
    if moved >= abs(open_pct) * (1 - HELD_RATIO):
        return "faded"
    return "held"


def load_feed(date_str):
    """Read + validate the catalyst feed. Never raises; absence is a state, not an error.

    Reads every checkpoint file for the date (0830/0920/0950 ET) and merges them in
    timestamp order. Missing checkpoints are normal and are not an error.
    """
    out = {"status": "feed_absent", "rows": [], "reason": None, "checkpoints": []}
    good, bad, found_any = [], 0, False
    for cp in FEED_CHECKPOINTS:
        raw = None
        for path in (FEED_LOCAL.format(date=date_str, cp=cp),
                     FEED_RAW.format(date=date_str, cp=cp)):
            try:
                raw = _get(path, timeout=20).decode("utf-8", "ignore")
                break
            except Exception:
                raw = None
        if raw is None:
            continue
        found_any = True
        n_cp = 0
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                bad += 1
                continue
            if not isinstance(rec, dict) or not rec.get("ticker"):
                bad += 1
                continue
            rec["_cat"] = rec.get("cat") if rec.get("cat") in CAT_VOCAB else "other"
            rec["_cp"] = cp
            good.append(rec)
            n_cp += 1
        out["checkpoints"].append({"cp": cp, "records": n_cp})
    if not found_any:
        out["reason"] = ("no feed file for this date (expected preopen-feed/%s-{0830,0920,0950}.jsonl)"
                         % date_str)
        return out
    good.sort(key=lambda r: r.get("ts") or "")
    out["status"] = "feed_ok" if good else "feed_empty"
    out["rows"] = good
    out["malformed"] = bad
    if not good:
        out["reason"] = "feed file(s) present but had no usable records"
    return out


def build(symbols, date_str, want_feed=True):
    scan = scanner_premarket(symbols) if isinstance(scanner_premarket(symbols), dict) else {}
    scan_err = scan.get("error") if isinstance(scan, dict) else None
    scan = {k: v for k, v in (scan or {}).items() if k != "error"}
    feed = load_feed(date_str) if want_feed else {"status": "feed_absent", "rows": [], "reason": "not requested"}
    feed_by_ticker = {}
    for rec in feed["rows"]:
        feed_by_ticker.setdefault(rec["ticker"].upper(), []).append(rec)

    # The TradingView scanner's premarket_* fields are LIVE ONLY — they reflect the most
    # recent premarket session, not a historical one. For a past date they are stale and
    # must not be trusted; the 5-minute-bar path below IS historical and always valid.
    today = datetime.datetime.now(_et()).strftime("%Y-%m-%d")
    premkt_is_live = (date_str == today)

    rows = []
    for sym in symbols:
        s = sym.upper()
        path = intraday_path(s, date_str)
        if path.get("error"):
            rows.append({"ticker": s, "error": path["error"]})
            continue
        open_pct = path.get("09:30", {}).get("chg_pct")
        now_pct = path.get("15:50", {}).get("chg_pct") or path.get("16:00", {}).get("chg_pct")
        sc = scan.get(s, {})
        premkt_pct = sc.get("premarket_change")
        recs = feed_by_ticker.get(s, [])
        # A feed record whose price disagrees with the scanner/5m data is not trusted.
        verified = []
        for rec in recs:
            try:
                fpct = float(rec.get("pct"))
            except Exception:
                fpct = None
            if fpct is not None and open_pct is not None and abs(fpct - open_pct) > 2.0:
                rec = dict(rec, conf="unverified")
            verified.append(rec)
        rows.append({
            "ticker": s,
            "name": sc.get("name") or (verified[0].get("name") if verified else None),
            "prior_close": path.get("_prior_close"),
            "premarket_pct": premkt_pct if premkt_is_live else None,
            "premarket_volume": sc.get("premarket_volume") if premkt_is_live else None,
            "premarket_source": "live" if premkt_is_live else "unavailable_for_past_date",
            "open_0930_pct": open_pct,
            "open_0935_pct": path.get("09:35", {}).get("chg_pct"),
            "at_1000_pct": path.get("10:00", {}).get("chg_pct"),
            "at_1200_pct": path.get("12:00", {}).get("chg_pct"),
            "at_1550_pct": path.get("15:50", {}).get("chg_pct"),
            "close_pct": path.get("16:00", {}).get("chg_pct"),
            "verdict": verdict(open_pct, now_pct),
            "premarket_verdict": verdict(premkt_pct, now_pct) if premkt_is_live else None,
            "rvol10": sc.get("rvol10"),
            "halted": sc.get("halted"),
            "exchange": sc.get("exchange"),
            "catalyst": verified[-1].get("why") if verified else None,
            "catalyst_cat": verified[-1].get("_cat") if verified else None,
            "catalyst_ts": verified[-1].get("ts") if verified else None,
            "catalyst_conf": verified[-1].get("conf") if verified else None,
            "feed_records": len(verified),
        })
    return {"date": date_str, "premarket_note": (
        None if premkt_is_live else
        "premarket columns are LIVE ONLY and are blank for a past date; the 09:30/10:00/12:00 "
        "path from 5-minute bars is historical and valid"),
        "feed_status": feed["status"], "feed_reason": feed.get("reason"),
            "feed_rows": len(feed["rows"]), "feed_malformed": feed.get("malformed", 0),
            "scanner_error": scan_err, "rows": rows}


def render(res):
    lines = []
    if res.get("feed_status") == "feed_ok":
        lines.append(f"pre-open feed: ok ({res['feed_rows']} records, "
                     f"{res['feed_malformed']} malformed)")
    else:
        lines.append(f"pre-open feed: {res['feed_status']} — {res.get('feed_reason')}. "
                     f"Path/verdict still computed from intraday bars.")
    if res.get("scanner_error"):
        lines.append(f"  scanner: {res['scanner_error']}")
    if res.get("premarket_note"):
        lines.append(f"  {res['premarket_note']}")
    lines.append("")
    lines.append(f"{'ticker':<7}{'premk%':>8}{'0930%':>8}{'1000%':>8}{'1200%':>8}"
                 f"{'now%':>8}  {'verdict':<9}{'pm-verdict':<11}{'catalyst'}")
    for r in res["rows"]:
        if r.get("error"):
            lines.append(f"{r['ticker']:<7}  ERROR {r['error']}")
            continue
        def g(k):
            v = r.get(k)
            return f"{v:>7.2f}" if isinstance(v, (int, float)) else f"{'-':>8}"
        cat = r.get("catalyst") or ""
        if r.get("catalyst_conf") == "unverified":
            cat = "[UNVERIFIED] " + cat
        lines.append(f"{r['ticker']:<7}{g('premarket_pct')}{g('open_0930_pct')}"
                     f"{g('at_1000_pct')}{g('at_1200_pct')}{g('at_1550_pct')}  "
                     f"{r['verdict']:<9}{(r.get('premarket_verdict') or '-'):<11}{cat[:70]}")
    return "\n".join(lines)


def selftest():
    """Regression against four sessions with known ground truth."""
    cases = [("XLAB", "2026-10-15", "reverse", "gapped down then closed +49.6%"),
             ("CCI", "2026-10-23", "held", "gapped +15.5%, closed +9.1%"),
             ("SKYD", "2026-10-14", "held", "gapped -18.6%, closed -23.8%"),
             ("BRZE", "2026-10-23", "no_move", "flat all day — merger arb")]
    res = build([c[0] for c in cases], cases[0][1], want_feed=False)
    by = {r["ticker"]: r for r in res["rows"]}
    ok = True
    for sym, date, expect, note in cases:
        r = by.get(sym, {})
        got = r.get("verdict")
        # re-evaluate each symbol on its own date
        if date != cases[0][1]:
            r = build([sym], date, want_feed=False)["rows"][0]
            got = r.get("verdict")
        flag = "PASS" if got == expect else "FAIL"
        ok = ok and got == expect
        print(f"  {flag}  {sym:<6} {date}  verdict={got!r} (expected {expect!r})  "
              f"open={r.get('open_0930_pct')}% now={r.get('at_1550_pct')}%  # {note}")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["provenance", "feed", "merge", "selftest"])
    ap.add_argument("--date")
    ap.add_argument("--symbols", default="")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.command == "selftest":
        return selftest()

    if not args.date:
        print("--date YYYY-MM-DD is required", file=sys.stderr)
        return 2
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    if args.command == "feed":
        res = load_feed(args.date)
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            print(f"feed_status: {res['status']}")
            if res.get("reason"):
                print(f"reason: {res['reason']}")
            print(f"records: {len(res['rows'])}  malformed: {res.get('malformed', 0)}")
            for rec in res["rows"][:40]:
                print(f"  {rec.get('ts')}  {rec.get('ticker'):<7} {str(rec.get('pct')):>8}  "
                      f"{rec.get('_cat'):<14} {str(rec.get('why'))[:70]}")
        return 0

    if not symbols:
        print("--symbols is required for provenance/merge", file=sys.stderr)
        return 2
    res = build(symbols, args.date, want_feed=(args.command == "merge"))
    print(json.dumps(res, indent=2) if args.json else render(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
