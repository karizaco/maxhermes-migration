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

THE SECOND GAP: THE ROSTER IS COPIED FOUR TIMES
----------------------------------------------
The fleet's routine list exists in FOUR places, and they can drift apart:

  1. `tools/schedule-ground-truth.json`          - the schedules of record
  2. `cloud-prompts/_shared/auditor-procedure.md` STEP 4 - the AUDITOR's roster
  3. `tools/deploy_prompts.py`                   - the deploy harness's task map
  4. `tools/gen_roster.py` ARTIFACTS             - the roster/index GENERATOR's map

`check()` compares (1) against the live scheduler. `copy_drift()` compares (1)
against (2), (3) and (4), so a routine that is monitored in one copy and missing
from another is reported instead of quietly diverging.

This is not hypothetical. On 2026-11-12 cron #92's two pre-open slots were
MISSING from copy (4) and from nothing else. The consequence was that
`cloud-prompts/cron-prompts/README.md` - which is GENERATED from copy (4) -
published their Output column as "-", claiming they write no artifact, while
the auditor's own table and the ground truth both knew they write
`preopen-feed/`. The index told the reader something false about two live
routines, and nothing compared the copies, so nothing caught it.

A copy that drifts is a copy that lies. The auditor procedure's own STEP 4e
calls the roster table and the ground truth "COPIES of what should be one
source" - this check is the machine that makes that true.

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
  0  every live routine is in the ground truth, and every copy agrees
  1  at least one live routine is NOT in the ground truth (a roster gap)
  2  usage / input error
  3  the copies of the roster disagree (roster_copy_drift) - NOT a roster gap,
     and deliberately a DIFFERENT code so nothing that branches on "1 = a live
     routine is unmonitored" changes meaning
"""
import argparse
import json
import os
import re
import sys
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DEFAULT_GROUND_TRUTH = os.path.join(HERE, "schedule-ground-truth.json")
DEFAULT_AUDITOR_PROCEDURE = os.path.join(
    REPO, "cloud-prompts", "_shared", "auditor-procedure.md")

# The id is the routine's leading alphanumeric token: "15" and "15b" are two
# routines, "26" and "26b" are two routines, "92a" and "92b" are two routines.
# A numeric-only prefix would collide all three pairs, so the letter is part
# of the id.
ID_RE = re.compile(r"^([0-9]+[a-z]?)")


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


# --------------------------------------------------------------------------
# The copy-drift check: the ground truth against the OTHER three copies.
# --------------------------------------------------------------------------

def routine_id(name):
    """The leading alphanumeric id of a routine name: '15b-x.md' -> '15b'."""
    stem = name[:-3] if name.endswith(".md") else name
    m = ID_RE.match(stem)
    return m.group(1) if m else stem


def _ids(names):
    return {routine_id(n) for n in names}


def gen_roster_artifacts(repo=REPO):
    """The ARTIFACTS keys of tools/gen_roster.py: {stem: spec}."""
    path = os.path.join(repo, "tools", "gen_roster.py")
    src = open(path, encoding="utf-8").read()
    m = re.search(r"ARTIFACTS\s*=\s*\{(.*?)\n\}", src, re.S)
    if not m:
        raise ValueError("gen_roster.py has no ARTIFACTS map")
    return set(re.findall(r'"([^"]+)"\s*:', m.group(1)))


def gen_roster_no_artifact(repo=REPO):
    """The routines declared as producing no artifact, by gen_roster.py and gen_index.py.

    gen_roster.py and gen_index.py EACH carry their own NO_ARTIFACT map (the two files
    were written independently and both need the set). The exempt set is the UNION of
    the two: a routine that either file declares artifact-less is exempt, so the check
    does not report a drift that is really just "this file names the exception".
    """
    names = set()
    for fname, var in (("gen_roster.py", "NO_ARTIFACT"), ("gen_index.py", "NO_ARTIFACT")):
        path = os.path.join(repo, "tools", fname)
        if not os.path.exists(path):
            continue
        src = open(path, encoding="utf-8").read()
        m = re.search(var + r"\s*=\s*\{([^}]*)\}", src)
        if m:
            names |= set(re.findall(r'"([^"]+)"', m.group(1)))
    return names


def deploy_prompts_map(repo=REPO):
    """The task map of tools/deploy_prompts.py: {cron_name: (task_id, sched)}."""
    path = os.path.join(repo, "tools", "deploy_prompts.py")
    src = open(path, encoding="utf-8").read()
    m = re.search(r"^[A-Z_]+\s*=\s*\{(.*?)\n\}", src, re.S | re.M)
    if not m:
        raise ValueError("deploy_prompts.py has no task map")
    return set(re.findall(r'"([^"]+\.md)"\s*:', m.group(1)))


def auditor_procedure_roster(path=DEFAULT_AUDITOR_PROCEDURE):
    """The routine ids in the auditor procedure's STEP 4 roster table."""
    if not os.path.exists(path):
        raise ValueError("auditor procedure not found")
    src = open(path, encoding="utf-8").read()
    # The STEP 4 table runs from its heading to the next heading.
    m = re.search(r"##\s*STEP 4\b(.*?)(?=\n##\s|\Z)", src, re.S)
    if not m:
        raise ValueError("auditor procedure has no STEP 4 section")
    ids = set()
    for line in m.group(1).splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        name = cells[0].strip("` ")
        if not name or name in ("Routine", "---") or set(name) <= set("- "):
            continue
        mm = ID_RE.match(name)
        if mm:
            ids.add(mm.group(1))
    return ids


def copy_drift(ground_truth, repo=REPO, procedure=None):
    """Compare the ground truth against the other three copies of the roster."""
    if procedure is None:
        procedure = os.path.join(repo, "cloud-prompts", "_shared", "auditor-procedure.md")
    gt_ids = _ids(ground_truth)
    drift = []

    def note(copy, missing, why):
        for name in sorted(missing):
            # The line is the AUDITOR'S OWN gap format, verbatim:
            #   gap: <routine> <label> <path> — cause=<token> age_h=<n> — <detail>
            # `roster_desync` and its cause `cron_update_failed` are already in the
            # contract's label_causes, so a copy drift is published with the labels
            # the auditor already knows - no new vocabulary and no prompt edit.
            drift.append({
                "name": name,
                "routine_id": routine_id(name),
                "copy": copy,
                "why": why,
                "label": "roster_desync",
                "cause": "cron_update_failed",
                "line": f"gap: {name} ROSTER_DESYNC {copy} — cause=cron_update_failed "
                        f"age_h=0 — {why}",
            })

    # (4) the roster/index generator's ARTIFACTS map
    try:
        arts = gen_roster_artifacts(repo)
        exempt = gen_roster_no_artifact(repo)
        # NO_ARTIFACT holds STEMS ("91-schedule-drift-guard") while the ground truth
        # holds FILENAMES ("91-schedule-drift-guard.md"), so the two are compared by
        # routine id - the same key every other copy is compared by.
        missing = {n for n in ground_truth
                   if routine_id(n) not in _ids(exempt)
                   and routine_id(n) not in _ids(arts)}
        note("tools/gen_roster.py ARTIFACTS", missing,
             "the generated README index and ROSTER.md cannot show its output path")
    except (OSError, ValueError) as exc:
        drift.append({"name": "-", "routine_id": "-", "copy": "tools/gen_roster.py",
                      "why": f"unreadable: {exc}", "label": "roster_desync",
                      "cause": "cron_update_failed",
                      "line": f"gap: tools/gen_roster.py ROSTER_DESYNC tools/gen_roster.py "
                              f"— cause=cron_update_failed age_h=0 — unreadable: {exc}"})

    # (3) the deploy harness's task map
    try:
        dep = deploy_prompts_map(repo)
        missing = {n for n in ground_truth if n not in dep}
        note("tools/deploy_prompts.py", missing,
             "the deploy harness cannot deploy or byte-verify it")
    except (OSError, ValueError) as exc:
        drift.append({"name": "-", "routine_id": "-", "copy": "tools/deploy_prompts.py",
                      "why": f"unreadable: {exc}", "label": "roster_desync",
                      "cause": "cron_update_failed",
                      "line": f"gap: tools/deploy_prompts.py ROSTER_DESYNC tools/deploy_prompts.py "
                              f"— cause=cron_update_failed age_h=0 — unreadable: {exc}"})

    # (2) the auditor procedure's own STEP 4 roster table
    try:
        ids = auditor_procedure_roster(procedure)
        missing = {n for n in ground_truth if routine_id(n) not in ids}
        note("cloud-prompts/_shared/auditor-procedure.md STEP 4", missing,
             "the auditor never checks its artifact")
    except (OSError, ValueError) as exc:
        drift.append({"name": "-", "routine_id": "-",
                      "copy": "cloud-prompts/_shared/auditor-procedure.md",
                      "why": f"unreadable: {exc}", "label": "roster_desync",
                      "cause": "cron_update_failed",
                      "line": f"gap: auditor-procedure.md ROSTER_DESYNC "
                              f"cloud-prompts/_shared/auditor-procedure.md "
                              f"— cause=cron_update_failed age_h=0 — unreadable: {exc}"})

    return {"roster_copy_drift": drift, "roster_copy_drift_count": len(drift)}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tasks", required=True, help="saved cron_read view=list JSON")
    ap.add_argument("--ground-truth", default=DEFAULT_GROUND_TRUTH)
    ap.add_argument("--repo", default=REPO,
                    help="the maxhermes-migration checkout the copies are read from")
    ap.add_argument("--no-copies", action="store_true",
                    help="skip the copy-drift check (the live-vs-ground-truth check always runs)")
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

    drift = {"roster_copy_drift": [], "roster_copy_drift_count": 0}
    if not args.no_copies:
        drift = copy_drift(gt, repo=args.repo)
    report.update(drift)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"live routines: {report['live_routines']}  ground truth: {report['ground_truth_routines']}")
        for gap in report["roster_gap"]:
            print(gap["line"])
        for name in report["ground_truth_only"]:
            print(f"GROUND-TRUTH-ONLY  {name}  (in schedule-ground-truth.json but not on the scheduler)")
        for d in report["roster_copy_drift"]:
            print(d["line"])
        print(f"RESULT: roster_gap={report['roster_gap_count']}  "
              f"roster_copy_drift={report['roster_copy_drift_count']}")

    if report["roster_gap_count"]:
        return 1
    if report["roster_copy_drift_count"]:
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
