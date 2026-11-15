#!/usr/bin/env python3
"""Regression test for cron #15's earnings-event tiering (contract v5, 2026-11-15).

WHY THIS TEST EXISTS. On the 2026-11-12 fire the artifact published NBIS with
"Last earnings 2026-08-12 (92d ago)" and NO catalyst, although Nebius Group
had reported PRE-OPEN that morning (Q3 revenue $980.8M, +571%). Two defects
were behind it, and both are pinned here:

  1. the screener's `earnings_release_date` is refreshed per company and
     ASYNCHRONOUSLY, so at the 08:03 ET scan a same-morning reporter still
     carried the previous quarter's date - a FALSE-verdict trap, not a
     missing one;
  2. the search budget ranked by |move| alone, so among a table whose biggest
     movers were ALL earnings names, the ranking could not tell them apart -
     NBIS (rank 7) lost a slot to a name whose report was a day old.

The fix: the Nasdaq public earnings calendar becomes the source of record for
the earnings date, and the budget ranks by EVENT FRESHNESS first.

WHAT IS ACTUALLY EXECUTED. The tier ordering and the ADR test are extracted
from the SHIPPED pipeline source and executed here, so a later edit that
changes them fails this test instead of quietly reordering the budget.

Usage:
    python3 tools/test_reaction_earnings_tier.py
    python3 tools/test_reaction_earnings_tier.py --pipeline <path to scanner>
    python3 tools/test_reaction_earnings_tier.py --artifact <published artifact>

Exit codes: 0 = all assertions hold, 1 = a regression.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request

API = "https://api.github.com/repos/karizaco/minimax-cloud-outputs/contents/scripts/earnings_reaction_scanner.py"
OUT_REPO = "https://api.github.com/repos/karizaco/minimax-cloud-outputs/contents/earnings"

# The 2026-11-12 US rows the Nasdaq earnings calendar matched, with the date
# the calendar gave for each and the earnings date the artifact published.
# Frozen on 2026-11-12 (the calendar is a moving target; the artifact is not).
CALENDAR_HITS = {
    # ticker: (calendar report date, published "Last earnings" cell, pre-mkt %)
    "EYE": ("2026-11-12", "2026-11-12 (0d ago)", "-16.09"),
    "DPC": ("2026-11-12", "2026-11-12 (0d ago)", "13.64"),
    "EROC": ("2026-11-12", "2026-11-12 (0d ago)", "-9.98"),
    "NBIS": ("2026-11-12", "2026-08-12 (92d ago)", "-9.11"),
    "YETI": ("2026-11-12", "2026-11-12 (0d ago)", "-8.62"),
    "TWST": ("2026-11-12", "2026-11-12 (0d ago)", "-8.23"),
    "FPS": ("2026-11-12", "2026-11-12 (0d ago)", "-5.98"),
    "LGN": ("2026-11-12", "2026-11-12 (0d ago)", "-3.91"),
    "AMAT": ("2026-11-12", "2026-11-12 (0d ago)", "-3.62"),
    "CBRS": ("2026-11-12", "2026-11-12 (0d ago)", "-3.22"),
    "AVEX": ("2026-11-11", "2026-11-11 (1d ago)", "11.29"),
    "TTEK": ("2026-11-11", "2026-11-11 (1d ago)", "10.77"),
    "CRWV": ("2026-11-10", "2026-11-10 (2d ago)", "-9.45"),
    "SNDK": ("2026-10-29", "2026-10-29 (14d ago)", "-6.00"),
    "AXTI": ("2026-10-29", "2026-10-29 (14d ago)", "-5.98"),
    "AAOI": ("2026-11-05", "2026-11-05 (7d ago)", "-5.96"),
    "SMCI": ("2026-11-03", "2026-11-03 (9d ago)", "-5.75"),
    "NVDA": ("2026-08-26", "2026-08-26 (78d ago)", "-7.56"),
    "YPSN": ("2026-08-19", "2026-08-19 (85d ago)", "-6.91"),
}
# The pre-market percentages of the published US headline table on 2026-11-12,
# in the published order, so the OLD ranking can be reproduced exactly.
PUBLISHED_PREMKT = {
    "EYE": -16.09, "DPC": 13.64, "AVEX": 11.29, "TTEK": 10.77, "EROC": -9.98,
    "CRWV": -9.45, "NBIS": -9.11, "YETI": -8.62, "TWST": -8.23, "NVDA": -7.56,
    "SNDK": -6.00, "FPS": -5.98, "AXTI": -5.98, "AAOI": -5.96, "SMCI": -5.75,
    "LGN": -3.91, "AMAT": -3.62, "CBRS": -3.22, "YPSN": -6.91,
}
RUN_DATE = "2026-11-12"
PREV_SESSION = "2026-11-11"
OLD_BUDGET = 5
NEW_BUDGET_CAP = 16
FOREIGN_FLOORS = 8

FAIL = []


def check(ok, label, detail=""):
    print(f"{'PASS' if ok else 'FAIL'} | {label}" + (f" - {detail}" if detail else ""))
    if not ok:
        FAIL.append(label)
    return ok


def fetch_pipeline():
    req = urllib.request.Request(API, headers={
        "Accept": "application/vnd.github.raw",
        "User-Agent": "maxhermes-cloud-cron",
        **({"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}"}
           if os.environ.get("GITHUB_TOKEN") else {}),
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def fetch_artifact(date):
    url = f"{OUT_REPO}/{date}-reactions.md?ref=main"
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github.raw",
        "User-Agent": "maxhermes-cloud-cron",
        **({"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}"}
           if os.environ.get("GITHUB_TOKEN") else {}),
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def extract(src, *names):
    """Pull top-level functions out of the pipeline source and exec them.

    They are exec'd in the order given, into ONE namespace, because the
    shipped functions call each other (event_freshness -> cal_rec).
    """
    ns = {"re": re, "json": json, "CAL": {}, "RUN_DATE": RUN_DATE,
          "PREV_SESSION": PREV_SESSION, "CATALYST_TOTAL_CAP": NEW_BUDGET_CAP}
    for name in names:
        m = re.search(rf"^def {re.escape(name)}\(.*?(?=^\S)", src, re.S | re.M)
        if not m:
            raise SystemExit(f"FAIL | the pipeline has no function {name}()")
        exec(m.group(0), ns)
    return ns


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pipeline", help="path to the pipeline script")
    ap.add_argument("--artifact", help="path to a published artifact to check")
    ap.add_argument("--date", default="2026-11-12")
    args = ap.parse_args()

    src = open(args.pipeline).read() if args.pipeline else fetch_pipeline()
    check("SCRIPT_VERSION = \"2026-11-15" in src or 'SCRIPT_VERSION = "2026-11-15' in src,
          "the pipeline carries the v5 script version",
          re.search(r'SCRIPT_VERSION = "([^"]+)"', src).group(1))

    # --- the calendar is fetched and used -------------------------------
    check("fetch_earnings_calendar" in src and
          "api.nasdaq.com/api/calendar/earnings" in src,
          "the pipeline fetches the Nasdaq bulk earnings calendar")
    check("earnings_field_stale_rows" in src,
          "the pipeline publishes the stale-field count")
    check("event_freshness" in src and "cal_event_cell" in src,
          "the pipeline tiers the US rows and writes calendar event cells")

    # --- the shipped tiering function, executed -------------------------
    lib = extract(src, "cal_rec", "event_freshness")
    lib["CAL"] = {k: {"date": v[0]} for k, v in CALENDAR_HITS.items()}
    freshness = lib["event_freshness"]

    def fresh(name):
        return freshness({"name": name})

    for t, want in (("NBIS", 0), ("EYE", 0), ("AVEX", 1), ("CRWV", 2),
                    ("NVDA", 2)):
        check(fresh(t) == want, f"event_freshness({t}) == {want}",
              f"got {fresh(t)}")

    # --- the OLD ranking missed NBIS; the NEW one catches it -------------
    old_order = sorted(PUBLISHED_PREMKT, key=lambda t: -abs(PUBLISHED_PREMKT[t]))
    old_top5 = old_order[:OLD_BUDGET]
    check("NBIS" not in old_top5,
          "the OLD rule (top 5 by |pre-market|) missed NBIS",
          "top 5 = " + ", ".join(old_top5))

    new_order = sorted(PUBLISHED_PREMKT,
                       key=lambda t: (fresh(t), -abs(PUBLISHED_PREMKT[t])))
    check("NBIS" in new_order[:NEW_BUDGET_CAP - FOREIGN_FLOORS],
          "the NEW rule (freshness first) catches NBIS",
          "order = " + ", ".join(new_order[:10]))

    fresh_rows = [t for t in PUBLISHED_PREMKT if fresh(t) == 0]
    check(len(fresh_rows) == 10, "ten published rows had reported that morning",
          f"got {len(fresh_rows)}: {sorted(fresh_rows)}")
    covered_old = [t for t in old_top5 if fresh(t) == 0]
    check(len(covered_old) == 3,
          "the OLD budget covered only 3 of the 10 same-day reporters "
          "(the other two slots went to names that reported YESTERDAY)",
          f"covered {covered_old}")
    check(len(fresh_rows) > OLD_BUDGET,
          "the same-day reporters alone outran the old 5-lookup budget",
          f"{len(fresh_rows)} fresh rows vs a budget of {OLD_BUDGET}")

    # --- NBIS's published row carries the STALE date ---------------------
    check(CALENDAR_HITS["NBIS"][1] == "2026-08-12 (92d ago)",
          "the published NBIS row carried the stale 92-day-old earnings date")
    check(CALENDAR_HITS["NBIS"][0] == "2026-11-12",
          "the calendar says NBIS reported on the scan date")

    # --- the ADR test, executed from the shipped source ------------------
    lib2 = extract(src, "is_adr_security")
    am = re.search(r"^ADR_TEXT_MARKERS = .*?\)\s*$", src, re.S | re.M)
    if not am:
        raise SystemExit("FAIL | the pipeline has no ADR_TEXT_MARKERS")
    exec(am.group(0), lib2)
    is_adr = lib2["is_adr_security"]
    check(is_adr("dr", "Nebius Group N.V.") is True,
          "a depositary form (type=dr) is an ADR")
    check(is_adr("stock", "Nebius Group N.V.") is False,
          "a primary ordinary share (type=stock) is NOT an ADR")
    check(is_adr("stock", "Agnico Eagle Mines Limited") is False,
          "a foreign issuer's primary US line is NOT an ADR")
    check(is_adr("", "") is False,
          "a security with no evidence is NOT called an ADR")

    # --- the checker, if the repo's copy is available --------------------
    checker = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "check_reaction_artifact.py")
    if os.path.exists(checker):
        art = args.artifact
        if not art:
            try:
                art = "/tmp/_tier_artifact.md"
                open(art, "w").write(fetch_artifact(args.date))
            except Exception as e:
                print(f"SKIP | artifact check - cannot fetch the published artifact ({e})")
                art = None
        if art:
            r = subprocess.run([sys.executable, checker, art],
                               capture_output=True, text=True)
            check(r.returncode == 0, "the checker accepts the published artifact",
                  r.stdout.strip().splitlines()[0] if r.stdout else "")
            # a fault injection: a verdict beside a calendar event cell
            body = open(art).read()
            mutated = body.replace("| PRE_GAP | — |", "| PRE_GAP | Y |", 1)
            if mutated != body:
                open("/tmp/_tier_inject.md", "w").write(mutated)
                r2 = subprocess.run([sys.executable, checker, "/tmp/_tier_inject.md"],
                                    capture_output=True, text=True)
                check(r2.returncode != 0,
                      "the checker rejects a verdict beside an unresearched cell")
            else:
                print("SKIP | the verdict fault injection (no PRE_GAP row found)")

    print()
    if FAIL:
        print(f"FAILED: {len(FAIL)} assertion(s): " + "; ".join(FAIL))
        return 1
    print("OK: every assertion holds")
    return 0


if __name__ == "__main__":
    sys.exit(main())
