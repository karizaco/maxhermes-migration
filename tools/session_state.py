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

      A MISMATCH IS NOT A SESSION ON ITS OWN. It has to be CORROBORATED before it can decide.
      Measured 2026-11-18: the scanner served a PRE-MARKET print (66.26) in the `close` column
      for one name, AUGO, against the morning brief's corrected prior close of 66.98 — 72 cents
      against this tool's 2-cent tolerance — and the old logic read that single row as "the
      session is live" and returned OPEN for a pull that landed 5 minutes 20 seconds BEFORE the
      09:30 ET open. A LIVE session moves the `close` column off the prior close for essentially
      EVERY name; a scanner field defect moves it for a handful. So the mismatch RATE is the
      discriminator now: at or above OPEN_MISMATCH_RATE it is a session, below it the disagreeing
      names are ISOLATED defects and the verdict is PRE-OPEN with the defects named. The
      live-like fraction corroborates it independently.
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

ISOLATED DEFECTS
    A PRE-OPEN verdict that carries `close_field_defects` is NOT a clean pull: those names' rows
    disagreed with the morning brief and the names are listed in the output. The run must name
    them in Source health — they are the scanner's `close` column misreporting, and the morning
    brief's own Source health usually already names the ones it corrected.
"""

import argparse
import csv
import datetime
import json
import os
import sys

SESSION_STATE_V2 = "session-state-v2"

# The environment's America/New_York has NO DST: November is EST (UTC-5). Confirmed against
# the platform's own scheduled_at_ms (cron #26 at 08:30 ET = 13:50 UTC, cron #26b at 09:20 ET
# = 14:20 UTC, exactly 50 minutes apart) and against the scanner's premarket_time (09:00 UTC
# = 04:00 ET). The offset is REPORTED in the output so a wrong clock is visible rather than
# silently baked in.
ET_OFFSET_HOURS = -5

TOL_IDENTITY = 0.02          # a settled session's change_abs, in price units
TOL_PRIOR_CLOSE = 0.02       # the scanner's close vs the morning brief's prior_close
LIVE_LIKE_PCT = 1.0          # |pm - close| within this % of close = "the live price is here"
OPEN_MISMATCH_RATE = 0.25     # the share of common names whose `close` disagrees with the
                              # morning brief's prior_close that a LIVE session produces. A live
                              # session flips the `close` column for essentially every name
                              # (measured 2026-11-18: a live pull mismatched ~100% of 703); an
                              # isolated scanner field defect flips it for one (1 of 703).
OPEN_MISMATCH_MIN = 3         # and the mismatching names must be at least this many, so a
                              # SMALL common set cannot tip the verdict on one defect (a 4-name
                              # common set with one defect is a 25% rate — and a defect).


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
    defects = []
    for r in rows:
        t = (r.get("ticker") or "").strip()
        c = num(r.get("close"))
        if t not in prior or c is None:
            continue
        checked += 1
        if abs(c - prior[t]) > TOL_PRIOR_CLOSE:
            failed += 1
            defects.append(t)
            if len(bad) < 5:
                bad.append(t)
    rate = (failed / checked) if checked else None
    return {"ok": (checked > 0 and failed == 0), "checked": checked, "failed": failed,
            "examples": bad, "mismatch_rate": round(rate, 6) if rate is not None else None,
            "defects": defects[:20], "defects_total": len(defects)}


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

    live_frac = live_like["value"] or 0.0
    rate = prior.get("mismatch_rate")
    defects = prior.get("defects") or []

    reasons = []
    if not ident["ok"]:
        reasons.append("the settled-session identity failed on %d of %d rows"
                       % (ident["failed"], ident["checked"]))
    if prior["ok"] is None:
        reasons.append("the morning baseline is missing, so the primary discriminator could "
                       "not be run")
    elif not prior["ok"]:
        reasons.append("the scanner's close no longer matches the morning brief's prior_close "
                       "on %d of %d common names (%.2f%% mismatching)"
                       % (prior["failed"], prior["checked"], (rate or 0.0) * 100))
    if live_like["value"] is not None and live_like["value"] >= 0.5:
        reasons.append("%.0f%% of the rows sit within 1%% of the scanner's close — the live "
                       "price is already there" % (live_like["value"] * 100))

    # A MISMATCH IS NOT A SESSION ON ITS OWN — it has to clear the rate a live session
    # produces, or be corroborated by the live-like fraction. See the (b) note above.
    if not ident["ok"]:
        state = "INDETERMINATE"
        reason = "; ".join(reasons)
    elif prior["ok"] is None:
        if live_frac >= 0.5:
            state = "OPEN"
            reason = "; ".join(reasons)
        else:
            state = "INDETERMINATE"
            reason = "; ".join(reasons)
    elif ((rate or 0.0) >= OPEN_MISMATCH_RATE and prior["failed"] >= OPEN_MISMATCH_MIN) \
            or live_frac >= 0.5:
        state = "OPEN"
        reason = ("the scanner's close no longer matches the morning brief's prior_close on "
                  "%d of %d common names (%.2f%% mismatching, at or above the %.0f%% a live "
                  "session produces) and %.1f%% of the rows sit within 1%% of the close"
                  % (prior["failed"], prior["checked"], (rate or 0.0) * 100,
                     OPEN_MISMATCH_RATE * 100, live_frac * 100))
    else:
        state = "PRE-OPEN"
        reason = ("the scanner's close still matches the morning brief's prior_close on %d of "
                  "%d common names (%.2f%% mismatching, below the %.0f%% a live session "
                  "produces, and fewer than the %d names a live session moves), the "
                  "settled-session identity holds on %d rows, and %.1f%% of the rows sit within "
                  "1%% of the close"
                  % (prior["checked"] - prior["failed"], prior["checked"], (rate or 0.0) * 100,
                     OPEN_MISMATCH_RATE * 100, OPEN_MISMATCH_MIN, ident["checked"],
                     live_frac * 100))
        if prior["failed"]:
            reason += (" — the %d name(s) that disagree are ISOLATED scanner `close` defects, "
                       "not a live session: %s" % (prior["failed"], ", ".join(defects)))

    out = {
        "marker": SESSION_STATE_V2,
        "session_state": state,
        "rows": len(rows),
        "pulled_at_et": merged.get("pulled_at_et") or now_et().strftime("%Y-%m-%d %H:%M:%S"),
        "et_offset_hours": ET_OFFSET_HOURS,
        "tests": {"settled_session_identity": ident, "prior_close_matches_morning": prior,
                  "live_like_fraction": live_like},
        "close_field_defects": defects,
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
        print("  (b) close == the morning brief's prior_close: ok=%s checked=%d failed=%d "
              "mismatch_rate=%s"
              % (prior["ok"], prior["checked"], prior["failed"],
                 ("n/a" if prior.get("mismatch_rate") is None
                  else "%.4f" % prior["mismatch_rate"])))
        if prior.get("defects"):
            print("      isolated close-field defects: %s" % ", ".join(prior["defects"]))
        print("  (c) rows within 1%% of the close: %s" % live_like["value"])
        print("  why: %s" % reason)
    else:
        print(json.dumps(out, indent=1))
    return {"PRE-OPEN": 0, "OPEN": 3, "INDETERMINATE": 4}[state]


if __name__ == "__main__":
    sys.exit(main())
