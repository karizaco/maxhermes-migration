#!/usr/bin/env python3
"""
test_auditor_roster_check.py - prove the roster copy-drift check CATCHES drift.

WHY
---
The fleet's routine list is copied into four places (the ground truth, the
auditor procedure's STEP 4 table, the deploy harness's task map, and the roster
generator's ARTIFACTS map). On 2026-11-12 cron #92's two pre-open slots were
missing from the fourth copy only, and the generated README index published
their Output column as "-" - a false statement about two live routines - while
the other three copies were correct. Nothing compared the copies, so nothing
caught it.

A check that only ever passes is not a check. This test builds a SYNTHETIC
repo (a temp directory, no network, no real files) and proves that:

  1. a repo whose four copies AGREE produces zero drift and exit 0,
  2. removing a routine from ANY ONE of the three copies produces drift that
     names the right copy and the right routine,
  3. the original 2026-11-12 defect - #92a/#92b absent from gen_roster.py's
     ARTIFACTS map while present everywhere else - is caught, and
  4. the live-vs-ground-truth check still works exactly as before (the copy
     check does not change its meaning): a live routine absent from the ground
     truth is still exit 1, not exit 3.

USAGE
    python3 tools/test_auditor_roster_check.py

EXIT CODES
    0  all good
    1  a drift was not caught, or a clean repo was reported as drifted
"""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RC = ROOT / "tools" / "auditor_roster_check.py"

PASS, FAIL = "PASS", "FAIL"
RESULTS = []


def record(ok, name, detail=""):
    RESULTS.append((PASS if ok else FAIL, name, detail))
    return ok


# ----------------------------------------------------------------------------------
# a synthetic repo: four copies of a three-routine fleet that AGREE
# ----------------------------------------------------------------------------------

GT = {
    "routines": {
        "01-weekly-health.md": {"schedule": "0 2 * * 0", "timezone": "America/New_York"},
        "92a-preopen-0830.md": {"schedule": "30 8 * * 1-5", "timezone": "America/New_York"},
        "92b-preopen-0950.md": {"schedule": "50 9 * * 1-5", "timezone": "America/New_York"},
    }
}

GEN_ROSTER = '''ARTIFACTS = {
 "01-weekly-health": ("mcp-health/YYYY-Wnn.md", "mcp-health", ".md"),
 "92a-preopen-0830": ("preopen-feed/{date}-0830.md", "preopen-feed", "-0830.md"),
 "92b-preopen-0950": ("preopen-feed/{date}-0950.md", "preopen-feed", "-0950.md"),
}
NO_ARTIFACT = {"91-schedule-drift-guard"}
'''

GEN_INDEX = '''NO_ARTIFACT = {
    "01-weekly-mcp-health-check.md": "x",
    "91-schedule-drift-guard.md": "y",
}
'''

DEPLOY = '''TASKS = {
    "01-weekly-health.md":               ("111", "0 2 * * 0"),
    "92a-preopen-0830.md":               ("222", "30 8 * * 1-5"),
    "92b-preopen-0950.md":               ("333", "50 9 * * 1-5"),
}
'''

PROCEDURE = """## STEP 4 - CHECK EVERY ROUTINE

| Routine | Schedule (ET) | Expected artifact on origin/main | Fires on |
|---|---|---|---|
| 01-weekly-health | `0 2 * * 0` | `mcp-health/{ISO-week}.md` | Sun |
| 92a-preopen-0830 | `30 8 * * 1-5` | `preopen-feed/{date}-0830.jsonl` | Mon-Fri |
| 92b-preopen-0950 | `50 9 * * 1-5` | `preopen-feed/{date}-0950.jsonl` | Mon-Fri |

## STEP 5 - CLASSIFY EVERY GAP
"""

TASKS = {"tasks": [
    {"task_id": "111", "cron_name": "01-weekly-health.md", "schedule": "0 2 * * 0",
     "timezone": "America/New_York", "enabled": True},
    {"task_id": "222", "cron_name": "92a-preopen-0830.md", "schedule": "30 8 * * 1-5",
     "timezone": "America/New_York", "enabled": True},
    {"task_id": "333", "cron_name": "92b-preopen-0950.md", "schedule": "50 9 * * 1-5",
     "timezone": "America/New_York", "enabled": True},
]}


def build_repo(tmp, root, gen_roster=GEN_ROSTER, deploy=DEPLOY, procedure=PROCEDURE):
    (root / "tools").mkdir(parents=True, exist_ok=True)
    (root / "cloud-prompts" / "_shared").mkdir(parents=True, exist_ok=True)
    (root / "tools" / "schedule-ground-truth.json").write_text(json.dumps(GT))
    (root / "tools" / "gen_roster.py").write_text(gen_roster)
    (root / "tools" / "gen_index.py").write_text(GEN_INDEX)
    (root / "tools" / "deploy_prompts.py").write_text(deploy)
    (root / "cloud-prompts" / "_shared" / "auditor-procedure.md").write_text(procedure)
    tasks_path = Path(tmp) / "tasks.json"
    tasks_path.write_text(json.dumps(TASKS))
    return tasks_path


def run_check(repo_root, tasks_path, extra=()):
    p = subprocess.run(
        [sys.executable, str(RC), "--tasks", str(tasks_path),
         "--ground-truth", str(Path(repo_root) / "tools" / "schedule-ground-truth.json"),
         "--repo", str(repo_root), "--json", *extra],
        capture_output=True, text=True, timeout=120)
    try:
        report = json.loads(p.stdout)
    except Exception:
        report = {"_stdout": p.stdout, "_stderr": p.stderr, "_rc": p.returncode}
    return p.returncode, report


def main():
    tmp = tempfile.mkdtemp(prefix="roster-check-")
    try:
        # ---- 1. a repo whose four copies AGREE ------------------------------
        root = Path(tmp) / "clean"
        tasks = build_repo(tmp, root)
        rc, rep = run_check(root, tasks)
        record(rc == 0 and rep.get("roster_copy_drift_count") == 0,
               "a repo whose copies agree reports no drift and exits 0",
               f"rc={rc} drift={rep.get('roster_copy_drift_count')}")

        # ---- 2. drift in each copy is caught and NAMED ----------------------
        cases = [
            ("gen_roster.py ARTIFACTS",
             GEN_ROSTER.replace(' "92a-preopen-0830": ("preopen-feed/{date}-0830.md", "preopen-feed", "-0830.md"),\n', ""),
             DEPLOY, PROCEDURE, "92a-preopen-0830.md", "tools/gen_roster.py"),
            ("the auditor procedure's STEP 4 table",
             GEN_ROSTER, DEPLOY,
             PROCEDURE.replace("| 92a-preopen-0830 | `30 8 * * 1-5` | `preopen-feed/{date}-0830.jsonl` | Mon-Fri |\n", ""),
             "92a-preopen-0830.md", "auditor-procedure.md"),
            ("deploy_prompts.py",
             GEN_ROSTER,
             DEPLOY.replace('    "92b-preopen-0950.md":               ("333", "50 9 * * 1-5"),\n', ""),
             PROCEDURE, "92b-preopen-0950.md", "deploy_prompts.py"),
        ]
        for label, gr, dp, proc, missing, expect_copy in cases:
            root = Path(tmp) / ("drift-" + expect_copy.replace("/", "-").replace(".", "-"))
            t = build_repo(tmp, root, gen_roster=gr, deploy=dp, procedure=proc)
            rc, rep = run_check(root, t)
            drift = rep.get("roster_copy_drift", [])
            names = [d.get("name", "") for d in drift]
            record(rc == 3 and missing in names
                   and any(expect_copy in d.get("copy", "") for d in drift),
                   f"drift in {label} is caught and names the copy",
                   f"rc={rc} drift={names}")

        # ---- 3. THE 2026-11-12 DEFECT, reproduced ---------------------------
        # #92a/#92b present in the ground truth, the auditor's table and the
        # deploy harness, but ABSENT from gen_roster.py's ARTIFACTS map.
        root = Path(tmp) / "the-original-bug"
        gr = GEN_ROSTER.replace(' "92a-preopen-0830": ("preopen-feed/{date}-0830.md", "preopen-feed", "-0830.md"),\n', "")
        gr = gr.replace(' "92b-preopen-0950": ("preopen-feed/{date}-0950.md", "preopen-feed", "-0950.md"),\n', "")
        t = build_repo(tmp, root, gen_roster=gr)
        rc, rep = run_check(root, t)
        names = sorted(d.get("name", "") for d in rep.get("roster_copy_drift", []))
        record(rc == 3 and names == ["92a-preopen-0830.md", "92b-preopen-0950.md"],
               "the 2026-11-12 defect (both pre-open slots absent from gen_roster) is caught",
               f"rc={rc} drift={names}")

        # ---- 4. the copy check did not change the live-vs-ground-truth check --
        root = Path(tmp) / "roster-gap"
        t = build_repo(tmp, root)
        gap_tasks = Path(tmp) / "gap-tasks.json"
        tasks2 = json.loads(json.dumps(TASKS))
        tasks2["tasks"].append({"task_id": "999", "cron_name": "99-unristered.md",
                                "schedule": "0 1 * * *", "timezone": "America/New_York",
                                "enabled": True})
        gap_tasks.write_text(json.dumps(tasks2))
        rc, rep = run_check(root, gap_tasks)
        record(rc == 1 and rep.get("roster_gap_count") == 1,
               "a live routine absent from the ground truth is still exit 1, not exit 3",
               f"rc={rc} roster_gap={rep.get('roster_gap_count')}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("-" * 78)
    failures = 0
    for status, name, detail in RESULTS:
        print(f"  {status}  {name}")
        if detail:
            print(f"        {detail[:160]}")
        if status == FAIL:
            failures += 1
    print("-" * 78)
    print(f"  {len(RESULTS) - failures}/{len(RESULTS)} checks behaved correctly")
    if failures:
        print(f"  RESULT: {failures} problem(s)")
        return 1
    print("  RESULT: every drift is caught and a clean repo is not cried up")
    return 0


if __name__ == "__main__":
    sys.exit(main())
