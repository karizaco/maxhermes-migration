#!/usr/bin/env python3
"""
auditor_roster_check.py - is every LIVE routine MONITORED?

THE BUG THIS EXISTS TO CATCH
----------------------------
Cron #90 (delivery-auditor) watches the fleet by consulting
`tools/schedule-ground-truth.json`. A routine that is LIVE on the scheduler but
absent from that file is UNMONITORED: the auditor never checks its artifact,
cron #91's drift guard cannot repair its schedule, and both report a clean
fleet. That is exactly what happened to #26b (`26b-agentic-pre-market-brief-
refresh-0920.md`, task 459637559267655, 09:20 ET): it was live and firing while
the 2026-11-03 audit reported `roster_desync: 0`.

A check that only runs when someone remembers to add a routine is not a check.
This script compares the LIVE routine set against the ground truth on every
audit, and reports every live-but-unrostered routine as its own finding.

WHAT COUNTS AS A "LIVE ROUTINE"
-------------------------------
The scheduler also holds tasks that are not fleet routines:
  * `@self-reminder/...`   - one-off follow-ups this agent scheduled for itself
  * one-off tasks whose name does not end in `.md`
Both are excluded: a fleet routine is a task whose (URL-decoded) `cron_name`
ends in `.md`, because that is how the fleet names itself.

USAGE
-----
  python3 tools/auditor_roster_check.py --tasks tasks.json
  python3 tools/auditor_roster_check.py --tasks tasks.json --json
  python3 tools/auditor_roster_check.py --tasks tasks.json \
      --ground-truth tools/schedule-ground-truth.json

`--tasks` takes the saved JSON of `cron_read {"view":"list","limit":100}`,
verbatim - the raw response envelope, a bare task list, or the tool-result
artifact shape all work.

EXIT CODES
----------
  0  every live routine is in the ground truth
  1  at least one live routine is NOT in the ground truth (a roster gap)
  2  usage / input error
"""
import argparse
import json
import os
import sys
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DEFAULT_GROUND_TRUTH = os.path.join(HERE, "schedule-ground-truth.json")


def _read_json(path):
    with open(path, encoding="utf-8") as fh:
        raw = fh.read()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start < 0 or end <= start:
            raise ValueError("cannot parse JSON")
        return json.loads(raw[start:end])


def load_tasks(path):
    """Parse a saved `cron_read view=list` payload into a list of tasks."""
    doc = _read_json(path)
    if isinstance(doc, dict):
        if isinstance(doc.get("response"), dict):
            doc = doc["response"]
        if isinstance(doc.get("tasks"), list):
            return doc["tasks"]
    if isinstance(doc, list):
        return doc
    raise ValueError("no task list found in the JSON")


def load_ground_truth(path=DEFAULT_GROUND_TRUTH):
    """Load {cron_name: {schedule, timezone, session_mode}} from the ground truth."""
    doc = _read_json(path)
    routines = doc.get("routines")
    if not isinstance(routines, dict):
        raise ValueError("ground truth has no 'routines' map")
    return routines


def live_routines(tasks):
    """The fleet routines that are live right now: name -> task record."""
    out = {}
    for t in tasks:
        if not isinstance(t, dict):
            continue
        # The platform URL-encodes the cron_name: cron #07 arrives as
        # "07-stock-screener-focus-rvol-09%3A45.md" while the repo file is
        # "...-09:45.md". Compare the DECODED name or the routine silently
        # reads as unrostered.
        name = urllib.parse.unquote(t.get("cron_name", "") or "")
        if not name.endswith(".md"):
            continue          # self-reminders and one-off tasks are not routines
        out[name] = t
    return out


def check(tasks, ground_truth):
    """Compare the live routine set against the ground truth."""
    live = live_routines(tasks)
    roster_gap = []
    for name, t in sorted(live.items()):
        if name not in ground_truth:
            roster_gap.append({
                "name": name,
                "task_id": str(t.get("task_id", "")),
                "schedule": (t.get("schedule") or "").strip(),
                "timezone": (t.get("timezone") or "").strip(),
                "enabled": bool(t.get("enabled", True)),
                "line": f"roster_gap: {name} (task {t.get('task_id', '')}) is live "
                        f"but not in schedule-ground-truth.json",
            })
    # The inverse: a routine the ground truth knows but the scheduler does not
    # have. That is a different problem (a deleted task), reported for context
    # but NOT a roster gap - the operator's file is the record of intent.
    unrostered = sorted(set(ground_truth) - set(live))
    return {
        "live_routines": len(live),
        "ground_truth_routines": len(ground_truth),
        "roster_gap": roster_gap,
        "ground_truth_only": unrostered,
        "roster_gap_count": len(roster_gap),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tasks", required=True, help="saved cron_read view=list JSON")
    ap.add_argument("--ground-truth", default=DEFAULT_GROUND_TRUTH)
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    if not os.path.exists(args.tasks):
        print(f"ERROR: no such file: {args.tasks}", file=sys.stderr)
        return 2
    try:
        tasks = load_tasks(args.tasks)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    try:
        gt = load_ground_truth(args.ground_truth)
    except (OSError, ValueError) as exc:
        print(f"ERROR: ground truth unusable: {exc}", file=sys.stderr)
        return 2

    report = check(tasks, gt)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"live routines: {report['live_routines']}  ground truth: {report['ground_truth_routines']}")
        for gap in report["roster_gap"]:
            print(gap["line"])
        for name in report["ground_truth_only"]:
            print(f"GROUND-TRUTH-ONLY  {name}  (in schedule-ground-truth.json but not on the scheduler)")
        print(f"RESULT: roster_gap={report['roster_gap_count']}")

    return 1 if report["roster_gap_count"] else 0


if __name__ == "__main__":
    sys.exit(main())
