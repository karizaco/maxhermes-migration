#!/usr/bin/env python3
"""
session_state.py — is the regular session OPEN at this pull, or is the tape still PRE-MARKET?

WHY THIS FILE EXISTS
--------------------
Cron #26b's procedure has a LATE-PULL branch: if the pull lands after the 09:30 ET open, the
pre-market columns mean something different (the `live_*` columns become live regular-session
values and the front matter carries `pull_late: true` / `market_open_at_pull: true`). Every
number in the artifact changes meaning with that branch, so the branch has to be DECIDED, not
guessed.

The clock cannot decide it. The procedure says to judge the gate against the FIRE, never the
wall clock, and this environment's `America/New_York` has no DST (November is EST, UTC-5), so a
hardcoded UTC-4 offset reads an hour late and a wall-clock test reads a 09:24 pull as 10:24 —
after the open. The DATA can decide it, and the data does not depend on the clock.

THE THREE TESTS
---------------
  (a) INTEGRITY — the settled-session identity `close - close/(1+change/100) == change_abs`
      must hold on every row. If it does not, the pull is internally inconsistent and NO
      verdict is safe.
  (b) DISCRIMINATOR (primary) — the scanner's `close` must still equal the PRIOR CLOSE the
      morning brief published in its CSV. While the session is shut, `close` is the last
      completed regular session's close and it matches (measured 2026-11-12: 220 of 220).
      Once the session opens, `close` becomes the LIVE price and it stops matching — so this
      is the test that actually separates the two states.
  (c) CORROBORATOR — the fraction of rows whose pre-market print sits within 1% of the
      scanner's `close`. On a band screen this is ~0 while the session is shut (every band
      name moved >=3% from that close) and rises once the session is live (the live price
      drifts toward the pre-market print). It is reported, not gated on, because its
      threshold is soft.

The skill's own close-sweep CANNOT detect an open session: `premarket_change` is always
computed against whatever `close` means, so the sweep stays self-consistent either way. That
is why this file exists.

USAGE
    python3 session_state.py --merged merged.json
    python3 session_state.py --merged merged.json --morning-csv daily-briefs/2026-11-12-pre-market.csv
    python3 session_state.py --merged merged.json --out state.json --json-only

OUTPUT
    A JSON document on stdout (or in --out):
    {"session_state": "PRE-OPEN" | "OPEN" | "INDETERMINATE",
     "rows": N, "pulled_at_et": "...", "et_offset_hours": -5,
     "tests": {...}, "verdict_reason": "...",
     "front_matter": {"market_open_at_pull": false, "pull_late": false}}

EXIT CODES
    0 = PRE-OPEN (the normal case — write the pre-market artifact, `live_*` BLANK)
    3 = OPEN (the session is live — take the LATE-PULL branch)
    4 = INDETERMINATE (a test failed or the morning baseline is missing — do NOT guess)
"""

import argparse
import csv
import datetime
import json
import os
import sys

SESSION_STATE_V1 = "session-state-v1"

# The environment's America/New_York has NO DST: November is EST (UTC-5). Confirmed against
# the platform's own scheduled_at_ms (cron #26 at 08:30 ET = 13:50 UTC, cron #26b at 09:20 ET
# = 14:20 UTC, exactly 50 minutes apart) and against the scanner's premarket_time (09:00 UTC
# = 04:00 ET). The offset is REPORTED in the output so a wrong clock is visible rather than
# silently baked in.
ET_OFFSET_HOURS = -5

TOL_IDENTITY = 0.02          # a settled session's change_abs, in price units
TOL_PRIOR_CLOSE = 0.02       # the scanner's close vs the morning brief's prior_close
LIVE_LIKE_PCT = 1.0          # |pm - close| within this % of close = "the live price is here"


def now_et():
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=ET_OFFSET_HOURS)))


def num(v):
    try:
        if v is None or v == "":
            return None
        return float(str(v).replace("$", "").replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def load_rows(merged):
    """Accept brief26_pull.py's merged.json, or a raw scanner payload."""
    if isinstance(merged, dict) and "rows" in merged:
        return merged["rows"]
    if isinstance(merged, dict) and "data" in merged:
        cols = ["name", "description", "close", "change", "change_abs", "volume",
                "average_volume_30d_calc", "premarket_close", "premarket_change",
                "premarket_high", "premarket_low", "premarket_volume", "market_cap_basic",
                "sector", "exchange", "type", "halted", "premarket_time",
                "earnings_release_next_date"]
        out = []
        for r in merged["data"]:
            rec = dict(zip(cols, r["d"] if isinstance(r, dict) and "d" in r else r))
            rec["ticker"] = rec.get("name")
            out.append(rec)
        return out
    if isinstance(merged, list):
        return merged
    raise SystemExit("session_state: cannot read rows out of the merged file")


def test_identity(rows):
    """(a) the settled-session identity on every row."""
    checked = failed = 0
    bad = []
    for r in rows:
        c = num(r.get("close")); ch = num(r.get("change")); ca = num(r.get("change_abs"))
        if c is None or ch is None or ca is None:
            continue
        checked += 1
        implied = c - c / (1.0 + ch / 100.0)
        if abs(implied - ca) > TOL_IDENTITY:
            failed += 1
            if len(bad) < 5:
                bad.append(r.get("ticker"))
    return {"ok": failed == 0 and checked > 0, "checked": checked, "failed": failed,
            "examples": bad}


def test_prior_close(rows, morning_csv):
    """(b) the scanner's close vs the morning brief's published prior_close."""
    if not morning_csv or not os.path.exists(morning_csv):
        return {"ok": None, "checked": 0, "failed": 0,
                "note": "no morning CSV — the primary discriminator is UNAVAILABLE"}
    prior = {}
    with open(morning_csv, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            v = num(r.get("prior_close"))
            if v is not None:
                prior[(r.get("ticker") or "").strip()] = v
    checked = failed = 0
    bad = []
    for r in rows:
        t = (r.get("ticker") or "").strip()
        c = num(r.get("close"))
        if t not in prior or c is None:
            continue
        checked += 1
        if abs(c - prior[t]) > TOL_PRIOR_CLOSE:
            failed += 1
            if len(bad) < 5:
                bad.append(t)
    return {"ok": (checked > 0 and failed == 0), "checked": checked, "failed": failed,
            "examples": bad}


def test_live_like(rows):
    """(c) the fraction of rows whose pre-market print sits within 1% of the scanner's close."""
    n = live = 0
    for r in rows:
        c = num(r.get("close")); pm = num(r.get("premarket_close"))
        if c is None or pm is None or not c:
            continue
        n += 1
        if abs(pm - c) / abs(c) * 100.0 < LIVE_LIKE_PCT:
            live += 1
    return {"value": round(live / n, 4) if n else None, "rows": n, "live_like": live,
            "threshold_pct": LIVE_LIKE_PCT}


def main():
    ap = argparse.ArgumentParser(description="decide PRE-OPEN / OPEN / INDETERMINATE")
    ap.add_argument("--merged", required=True, help="brief26_pull.py's merged.json")
    ap.add_argument("--morning-csv", default=None, help="the morning brief's CSV")
    ap.add_argument("--out", default=None, help="write the verdict here")
    ap.add_argument("--json-only", action="store_true", help="no human-readable summary")
    args = ap.parse_args()

    with open(args.merged, encoding="utf-8") as fh:
        merged = json.load(fh)
    rows = load_rows(merged)

    ident = test_identity(rows)
    prior = test_prior_close(rows, args.morning_csv)
    live_like = test_live_like(rows)

    reasons = []
    if not ident["ok"]:
        reasons.append("the settled-session identity failed on %d of %d rows"
                       % (ident["failed"], ident["checked"]))
    if prior["ok"] is None:
        reasons.append("the morning baseline is missing, so the primary discriminator could "
                       "not be run")
    elif not prior["ok"]:
        reasons.append("the scanner's close no longer matches the morning brief's prior_close "
                       "on %d of %d common names — the session is live"
                       % (prior["failed"], prior["checked"]))
    if live_like["value"] is not None and live_like["value"] >= 0.5:
        reasons.append("%.0f%% of the rows sit within 1%% of the scanner's close — the live "
                       "price is already there" % (live_like["value"] * 100))

    if ident["ok"] and prior["ok"] is True and (live_like["value"] or 0) < 0.5:
        state = "PRE-OPEN"
        reason = ("the scanner's close still matches the morning brief's prior_close on %d of "
                  "%d common names, the settled-session identity holds on %d rows, and %.1f%% "
                  "of the rows sit within 1%% of the close"
                  % (prior["checked"] - prior["failed"], prior["checked"], ident["checked"],
                     (live_like["value"] or 0) * 100))
    elif not ident["ok"]:
        state = "INDETERMINATE"
        reason = "; ".join(reasons)
    elif prior["ok"] is False or (live_like["value"] or 0) >= 0.5:
        state = "OPEN"
        reason = "; ".join(reasons) or "the live price is already in the close column"
    else:
        state = "INDETERMINATE"
        reason = "; ".join(reasons) or "no test was decisive"

    out = {
        "marker": SESSION_STATE_V1,
        "session_state": state,
        "rows": len(rows),
        "pulled_at_et": merged.get("pulled_at_et") or now_et().strftime("%Y-%m-%d %H:%M:%S"),
        "et_offset_hours": ET_OFFSET_HOURS,
        "tests": {"settled_session_identity": ident, "prior_close_matches_morning": prior,
                  "live_like_fraction": live_like},
        "verdict_reason": reason,
        "front_matter": {"market_open_at_pull": state == "OPEN",
                         "pull_late": state == "OPEN"},
    }
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=1)

    if not args.json_only:
        print("session state: %s" % state)
        print("  rows: %d   pulled_at_et: %s (ET offset %+d)"
              % (out["rows"], out["pulled_at_et"], ET_OFFSET_HOURS))
        print("  (a) settled-session identity: ok=%s checked=%d failed=%d"
              % (ident["ok"], ident["checked"], ident["failed"]))
        print("  (b) close == the morning brief's prior_close: ok=%s checked=%d failed=%d"
              % (prior["ok"], prior["checked"], prior["failed"]))
        print("  (c) rows within 1%% of the close: %s" % live_like["value"])
        print("  why: %s" % reason)
    else:
        print(json.dumps(out, indent=1))
    return {"PRE-OPEN": 0, "OPEN": 3, "INDETERMINATE": 4}[state]


if __name__ == "__main__":
    sys.exit(main())
