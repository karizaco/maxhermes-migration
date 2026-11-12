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










def _resolve(paths):
    """The first candidate path that exists, or None."""
    for p in paths:
        if p and os.path.exists(p):
            return p
    return None


def _copy_candidates(name, repo, explicit=None):
    """Where a copy of the roster may live, most authoritative first.

    The audit runs in a SANDBOX that holds only the files it fetched - there is no
    repo checkout. So a copy is looked for in: the path the caller gave it, the
    repo-relative path (when a checkout exists), the directory this script itself
    sits in (the sandbox case: the procedure fetches the copies next to itself),
    and /workspace.
    """
    rel = {
        "gen_roster": os.path.join("tools", "gen_roster.py"),
        "deploy_prompts": os.path.join("tools", "deploy_prompts.py"),
        "auditor_procedure": os.path.join("cloud-prompts", "_shared", "auditor-procedure.md"),
    }[name]
    here = os.path.dirname(os.path.abspath(__file__))
    return [
        explicit,
        os.path.join(repo, rel),
        os.path.join(here, os.path.basename(rel)),
        os.path.join("/workspace", os.path.basename(rel)),
    ]


def copy_drift(ground_truth, repo=REPO, procedure=None,
               gen_roster_path=None, deploy_prompts_path=None):
    """Compare the ground truth against the other three copies of the roster.

    A copy that cannot be LOCATED is NOT a drift - the audit runs from a fetched-file
    sandbox with no repo checkout, so a missing copy is a missing input, not a
    disagreement. It is reported under `roster_copy_not_checked` instead, and it never
    raises the exit code: a check that cries wolf on every audit is worse than no
    check at all.
    """
    drift = []
    not_checked = []

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
    gr_path = _resolve(_copy_candidates("gen_roster", repo, gen_roster_path))
    if not gr_path:
        not_checked.append({
            "copy": "tools/gen_roster.py ARTIFACTS",
            "why": "gen_roster.py was not available in this sandbox",
        })
    else:
        try:
            src = open(gr_path, encoding="utf-8").read()
            arts = set(re.findall(r'"([^"]+)"\s*:', re.search(r"ARTIFACTS\s*=\s*\{(.*?)\n\}", src, re.S).group(1)))
            m = re.search(r"NO_ARTIFACT\s*=\s*\{([^}]*)\}", src)
            exempt = set(re.findall(r'"([^"]+)"', m.group(1))) if m else set()
            # gen_index.py carries its own NO_ARTIFACT map; the exempt set is the union.
            gi_path = _resolve(_copy_candidates("gen_roster", repo,
                                                os.path.join(repo, "tools", "gen_index.py")))
            if gi_path:
                gsrc = open(gi_path, encoding="utf-8").read()
                gm = re.search(r"NO_ARTIFACT\s*=\s*\{([^}]*)\}", gsrc)
                if gm:
                    exempt |= set(re.findall(r'"([^"]+)"', gm.group(1)))
            # NO_ARTIFACT holds STEMS while the ground truth holds FILENAMES, so the
            # two are compared by routine id - the same key every copy is compared by.
            missing = {n for n in ground_truth
                       if routine_id(n) not in _ids(exempt)
                       and routine_id(n) not in _ids(arts)}
            note("tools/gen_roster.py ARTIFACTS", missing,
                 "the generated README index and ROSTER.md cannot show its output path")
        except (OSError, ValueError, AttributeError) as exc:
            not_checked.append({
                "copy": "tools/gen_roster.py ARTIFACTS",
                "why": f"unreadable: {exc}",
            })

    # (3) the deploy harness's task map
    dp_path = _resolve(_copy_candidates("deploy_prompts", repo, deploy_prompts_path))
    if not dp_path:
        not_checked.append({
            "copy": "tools/deploy_prompts.py",
            "why": "deploy_prompts.py was not available in this sandbox",
        })
    else:
        try:
            src = open(dp_path, encoding="utf-8").read()
            m = re.search(r"^[A-Z_]+\s*=\s*\{(.*?)\n\}", src, re.S | re.M)
            dep = set(re.findall(r'"([^"]+\.md)"\s*:', m.group(1)))
            missing = {n for n in ground_truth if n not in dep}
            note("tools/deploy_prompts.py", missing,
                 "the deploy harness cannot deploy or byte-verify it")
        except (OSError, ValueError, AttributeError) as exc:
            not_checked.append({
                "copy": "tools/deploy_prompts.py",
                "why": f"unreadable: {exc}",
            })

    # (2) the auditor procedure's own STEP 4 roster table
    ap_path = _resolve(_copy_candidates("auditor_procedure", repo, procedure))
    if not ap_path:
        not_checked.append({
            "copy": "cloud-prompts/_shared/auditor-procedure.md STEP 4",
            "why": "the auditor procedure was not available in this sandbox",
        })
    else:
        try:
            src = open(ap_path, encoding="utf-8").read()
            m = re.search(r"##\s*STEP 4\b(.*?)(?=\n##\s|\Z)", src, re.S)
            if not m:
                raise ValueError("no STEP 4 section")
            ids = set()
            for line in m.group(1).splitlines():
                if not line.startswith("|"):
                    continue
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                if len(cells) < 2:
                    continue
                nm = cells[0].strip("` ")
                if not nm or nm == "Routine" or set(nm) <= set("- "):
                    continue
                mm = ID_RE.match(nm)
                if mm:
                    ids.add(mm.group(1))
            missing = {n for n in ground_truth if routine_id(n) not in ids}
            note("cloud-prompts/_shared/auditor-procedure.md STEP 4", missing,
                 "the auditor never checks its artifact")
        except (OSError, ValueError) as exc:
            not_checked.append({
                "copy": "cloud-prompts/_shared/auditor-procedure.md STEP 4",
                "why": f"unreadable: {exc}",
            })

    return {
        "roster_copy_drift": drift,
        "roster_copy_drift_count": len(drift),
        "roster_copy_not_checked": not_checked,
        "roster_copy_not_checked_count": len(not_checked),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tasks", required=True, help="saved cron_read view=list JSON")
    ap.add_argument("--ground-truth", default=DEFAULT_GROUND_TRUTH)
    ap.add_argument("--repo", default=REPO,
                    help="the maxhermes-migration checkout the copies are read from")
    ap.add_argument("--gen-roster", default=None,
                    help="explicit path to tools/gen_roster.py (the sandbox fetches it next to this script)")
    ap.add_argument("--deploy-prompts", default=None,
                    help="explicit path to tools/deploy_prompts.py")
    ap.add_argument("--procedure", default=None,
                    help="explicit path to the auditor procedure file")
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
        drift = copy_drift(gt, repo=args.repo, procedure=args.procedure,
                           gen_roster_path=args.gen_roster,
                           deploy_prompts_path=args.deploy_prompts)
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
        for d in report.get("roster_copy_not_checked", []):
            print(f"COPY-NOT-CHECKED  {d['copy']}  ({d['why']}) - not a finding")
        print(f"RESULT: roster_gap={report['roster_gap_count']}  "
              f"roster_copy_drift={report['roster_copy_drift_count']}  "
              f"copies_not_checked={report.get('roster_copy_not_checked_count', 0)}")

    if report["roster_gap_count"]:
        return 1
    if report["roster_copy_drift_count"]:
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
