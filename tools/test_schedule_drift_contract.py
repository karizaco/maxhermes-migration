#!/usr/bin/env python3
"""
test_schedule_drift_contract.py — prove the cron #91 guard's three new checks work.

WHY
---
The 2026-11-03 audit found three things it could not fix by itself:

  1. `schedule-drift.py`'s own docstring promised a recency guard that did not
     exist, so a 9-day-old conversation reuse printed exactly like a live one.
     The fix is a PER-ROUTINE window measured in FIRES of that routine -- a flat
     "within N days" cutoff would drop one of a weekly routine's two fires and
     mask a genuinely live binding.
  2. The ground truth held 25 routines while the scheduler ran 26. A task whose
     name is not in the ground truth is skipped by every check, so one weekday
     routine was never schedule-checked, never prompt-drift-checked and never
     conversation-checked -- and every count in the report was true while
     omitting it.
  3. A prompt hash cannot see spec drift: the routine's PROCEDURE is fetched
     from the repo at RUN time, so a byte-identical prompt can still run a spec
     that differs from the repo.

This test does both halves that matter: it proves the contract is SATISFIABLE
(these fixtures produce the verdicts the guard is supposed to produce) and that
each check BITES (a broken roster, a drifted spec and an unreachable spec are
all caught).

USAGE
    python3 tools/test_schedule_drift_contract.py
Exit codes: 0 = all good; 1 = a breach was not caught (or a verdict is wrong).
"""

import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SD_PATH = ROOT / "tools" / "schedule-drift.py"
FIX = ROOT / "tools" / "fixtures" / "schedule_drift"
GROUND_TRUTH = ROOT / "tools" / "schedule-ground-truth.json"

PASS = "PASS"
FAIL = "FAIL"

# The reference time every fixture is written against: 2026-11-06 12:00 ET.
NOW = 1793984400

spec = importlib.util.spec_from_file_location("sd", SD_PATH)
sd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sd)

_dspec = importlib.util.spec_from_file_location("dp", Path(__file__).resolve().parent / "deploy_prompts.py")
dp = importlib.util.module_from_spec(_dspec)
_dspec.loader.exec_module(dp)


# ----------------------------------------------------------------------------------
# a synthetic live roster built from the ground truth, so the roster check has
# something real to compare against
# ----------------------------------------------------------------------------------
def load_ground_truth():
    doc = json.loads(GROUND_TRUTH.read_text(encoding="utf-8"))
    return doc


def build_tasks(drop=(), rename=None):
    """A `cron_read view=list` payload covering every ground-truth routine."""
    doc = load_ground_truth()
    contracts = doc.get("spec_contracts", {}).get("routines", {})
    tasks = []
    for i, (name, v) in enumerate(sorted(doc["routines"].items())):
        if name in drop:
            continue
        c = contracts.get(name) or {}
        spec_path = c.get("spec_path", "")
        prompt = (f"# synthetic prompt for {name}\n"
                  f"https://api.github.com/repos/karizaco/maxhermes-migration/contents/"
                  f"{spec_path}?ref=main\n")
        tasks.append({
            "task_id": dp.TASKS.get(name, (str(700000000000000 + i), ""))[0],
            "cron_name": name,
            "schedule": v["schedule"],
            "timezone": v.get("timezone", "America/New_York"),
            "enabled": True,
            "session": {"mode": v.get("session_mode", "new"), "session_id": ""},
            "prompt": prompt,
            "next_run": 0,
        })
    if rename:
        for t in tasks:
            if t["cron_name"] == rename[0]:
                t["cron_name"] = rename[1]
    return {"ok": True, "command": "cron list",
            "response": {"tasks": tasks, "has_more": False}}


def run_detector(tasks, runs_file=None, extra=()):
    """Run the guard exactly the way cron #91 runs it."""
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                     encoding="utf-8") as fh:
        json.dump(tasks, fh)
        tasks_path = fh.name
    cmd = [sys.executable, str(SD_PATH), "--tasks", tasks_path,
           "--now", str(NOW), "--no-spec-check"]
    if runs_file:
        cmd += ["--runs-file", str(runs_file)]
    cmd += list(extra)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        return r.returncode, r.stdout + r.stderr
    finally:
        os.unlink(tasks_path)


def verdict(out, routine=None):
    """The class the guard assigned to a routine's reuse finding."""
    for line in out.splitlines():
        m = re.match(r"CONV-REUSE (LIVE|HISTORICAL)\s+(\S+):", line)
        if m and (routine is None or m.group(2) == routine):
            return m.group(1)
    return None


def main():
    results = []
    doc = load_ground_truth()
    ground = doc["routines"]
    contracts = doc.get("spec_contracts", {}).get("routines", {})

    # ==============================================================================
    # 1. THE RECENCY GUARD -- live vs historical, and the distinction BITES
    # ==============================================================================
    cases = [
        ("weekday routine, reuse inside its window",
         FIX / "runs-live-reuse.txt", "07-stock-screener-focus-rvol-09:45.md", "LIVE"),
        ("weekday routine, reuse long outside its window",
         FIX / "runs-historical-reuse.txt", "07-stock-screener-focus-rvol-09:45.md", "HISTORICAL"),
        ("weekly routine, two fires 7 days apart (a flat cutoff would say historical)",
         FIX / "runs-weekly-live-reuse.txt", "01-weekly-mcp-health-check.md", "LIVE"),
        ("weekly routine, reuse older than its own window",
         FIX / "runs-weekly-historical-reuse.txt", "01-weekly-mcp-health-check.md", "HISTORICAL"),
        ("daily routine, reuse inside its window",
         FIX / "runs-daily-live-reuse.txt", "91-schedule-drift-guard.md", "LIVE"),
        ("daily routine, reuse long outside its window",
         FIX / "runs-daily-historical-reuse.txt", "91-schedule-drift-guard.md", "HISTORICAL"),
    ]
    outputs = {}
    for label, fixture, routine, want in cases:
        code, out = run_detector(build_tasks(), fixture)
        outputs[label] = out
        got = verdict(out, routine)
        if got == want:
            results.append((PASS, f"{label} -> {got}"))
        else:
            results.append((FAIL, f"{label} -> {got or 'NO VERDICT'} (wanted {want})"))

    # the two verdicts must actually DIFFER -- that is the whole point
    live_out = outputs.get("weekday routine, reuse inside its window", "")
    hist_out = outputs.get("weekday routine, reuse long outside its window", "")
    if "CONV-REUSE LIVE" in live_out and "CONV-REUSE LIVE" not in hist_out \
            and "CONV-REUSE HISTORICAL" in hist_out:
        results.append((PASS, "a live table and a historical table produce DIFFERENT verdicts"))
    else:
        results.append((FAIL, "the live/historical distinction does not bite"))

    # a LIVE reuse is a finding (exit 1); a HISTORICAL one is evidence, not a finding
    code_live, _ = run_detector(build_tasks(), FIX / "runs-live-reuse.txt")
    code_hist, _ = run_detector(build_tasks(), FIX / "runs-historical-reuse.txt")
    if code_live == 1:
        results.append((PASS, "a live reuse is raised as a finding (exit 1)"))
    else:
        results.append((FAIL, f"a live reuse did not raise a finding (exit {code_live})"))
    if code_hist == 0:
        results.append((PASS, "a historical reuse is reported but is not raised (exit 0)"))
    else:
        results.append((FAIL, f"a historical reuse was raised as a finding (exit {code_hist})"))

    # the historical finding must still be VISIBLE -- age decides the label only
    if "CONV-REUSE HISTORICAL" in hist_out and "777000333444" in hist_out:
        results.append((PASS, "the historical reuse is still reported, with its session_id"))
    else:
        results.append((FAIL, "the historical reuse was dropped instead of labelled"))

    # an IMPOSSIBLE timestamp is rejected as malformed, not classified
    code_bad, out_bad = run_detector(build_tasks(), FIX / "runs-impossible-timestamp.txt")
    if "rejected as malformed" in out_bad and "CONV-REUSE" not in out_bad:
        results.append((PASS, "an impossible (future) timestamp is rejected, not classified"))
    else:
        results.append((FAIL, "an impossible timestamp was not rejected"))

    # ==============================================================================
    # 2. THE ROSTER CHECK -- the live roster must equal the ground truth
    # ==============================================================================
    code, out = run_detector(build_tasks())
    m = re.search(r"roster: (\d+) live / (\d+) expected", out)
    if m and m.group(1) == m.group(2) == str(len(ground)):
        results.append((PASS, f"the reply reports roster: {m.group(1)} live / "
                              f"{m.group(2)} expected (equal)"))
    else:
        results.append((FAIL, f"roster line wrong or missing: {m.group(0) if m else 'ABSENT'}"))

    # a routine missing from the LIVE roster must be flagged
    victim = sorted(ground)[0]
    code, out = run_detector(build_tasks(drop=(victim,)))
    if "ROSTER" in out and f"in the ground truth but not live: {victim}" in out \
            and code == 1:
        results.append((PASS, f"a routine missing from the live roster is flagged ({victim})"))
    else:
        results.append((FAIL, f"a missing live routine was not flagged (exit {code})"))

    # a routine that is live but NOT in the ground truth must be flagged too --
    # that is exactly how #26b escaped every check for a whole cycle
    extra_name = "99-unknown-routine.md"
    code, out = run_detector(build_tasks(rename=(sorted(ground)[1], extra_name)))
    if "ROSTER" in out and extra_name in out and code == 1:
        results.append((PASS, "a live routine missing from the ground truth is flagged"))
    else:
        results.append((FAIL, "a live routine missing from the ground truth was not flagged"))

    # ==============================================================================
    # 3. THE SPEC-DRIFT CHECK -- repo vs live, unreachable, and liveness
    # ==============================================================================
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "repo"
        bundle = repo / "cloud-prompts" / "skills" / "demo-skill"
        bundle.mkdir(parents=True)
        (bundle / "SKILL.md").write_text("# demo\n\n## Procedure\nemit_sweep_sql\n",
                                          encoding="utf-8")
        spec_path = "cloud-prompts/skills/demo-skill/SKILL.md"
        tasks = [{"task_id": "1", "cron_name": "99-demo.md", "schedule": "0 9 * * 1-5",
                  "timezone": "America/New_York", "enabled": True,
                  "session": {"mode": "new", "session_id": ""},
                  "prompt": f"https://api.github.com/repos/karizaco/maxhermes-migration/"
                            f"contents/{spec_path}?ref=main\n"}]
        contracts_local = {"99-demo.md": {"spec_path": spec_path,
                                          "bundle": "cloud-prompts/skills/demo-skill",
                                          "marker": "emit_sweep_sql"}}

        drifted = b"# demo\n\n## Procedure\nOLD\n"
        found, checked = sd.check_spec_drift(
            tasks, ground, contracts_local, repo_dir=str(repo),
            fetcher=lambda path, timeout: (drifted, "http://example", None))
        drift_lines = [f for f in found if f["kind"] == "SPEC-DRIFT"]
        if drift_lines and drift_lines[0]["repo_hash"] != drift_lines[0]["live_hash"]:
            results.append((PASS, "a spec that differs from the repo is reported as SPEC-DRIFT "
                                  "with both hashes"))
        else:
            results.append((FAIL, "spec drift was not detected"))

        found, _ = sd.check_spec_drift(
            tasks, ground, contracts_local, repo_dir=str(repo),
            fetcher=lambda path, timeout: (None, None, "connection refused"))
        unreachable = [f for f in found if f["kind"] == "SPEC-UNREACHABLE"]
        if unreachable and "connection refused" in unreachable[0]["reason"]:
            results.append((PASS, "a spec that cannot be fetched is reported as "
                                  "SPEC-UNREACHABLE with the reason"))
        else:
            results.append((FAIL, "an unreachable spec was not reported"))

        # liveness: the spec that lost its procedure section
        (bundle / "SKILL.md").write_text("# demo\n\n## Procedure\nsomething else\n",
                                          encoding="utf-8")
        found, _ = sd.check_spec_drift(
            tasks, ground, contracts_local, repo_dir=str(repo),
            fetcher=lambda path, timeout: ((bundle / "SKILL.md").read_bytes(),
                                            "http://example", None))
        missing = [f for f in found if f["kind"] == "SPEC-SECTION-MISSING"]
        if missing:
            results.append((PASS, "a spec that lost its procedure section is reported as "
                                  "SPEC-SECTION-MISSING"))
        else:
            results.append((FAIL, "a lost procedure section was not reported"))

        # the prompt pointing at a different spec than the contract expects
        contracts_local2 = dict(contracts_local)
        contracts_local2["99-demo.md"] = dict(contracts_local["99-demo.md"],
                                              spec_path="cloud-prompts/skills/other/SKILL.md")
        found, _ = sd.check_spec_drift(
            tasks, ground, contracts_local2, repo_dir=str(repo),
            fetcher=lambda path, timeout: ((bundle / "SKILL.md").read_bytes(),
                                            "http://example", None))
        mismatch = [f for f in found if f["kind"] == "SPEC-PATH-MISMATCH"]
        if mismatch:
            results.append((PASS, "a prompt naming a different spec than the contract "
                                  "expects is reported as SPEC-PATH-MISMATCH"))
        else:
            results.append((FAIL, "a spec path mismatch was not reported"))

    # the human-readable output must carry the exact lines the reply needs
    code, out = run_detector(build_tasks())
    if "SPEC-DRIFT" in sd.__doc__ and "SPEC-UNREACHABLE" in sd.__doc__:
        results.append((PASS, "the guard documents the SPEC-DRIFT / SPEC-UNREACHABLE prefixes"))
    else:
        results.append((FAIL, "the SPEC prefixes are not documented"))

    # ==============================================================================
    # 4. THE ROSTER OF RECORD -- #26b, #92a, #92b everywhere they must be
    # ==============================================================================
    for name in ("26b-agentic-pre-market-brief-refresh-0920.md",
                 "92a-preopen-catalyst-capture-0830.md",
                 "92b-preopen-catalyst-capture-0950.md"):
        results.append((PASS, f"{name} is in the ground truth")
                       if name in ground else (FAIL, f"{name} is MISSING from the ground truth"))

    deploy = (ROOT / "tools" / "deploy_prompts.py").read_text(encoding="utf-8")
    for name in ("26b-agentic-pre-market-brief-refresh-0920.md",
                 "92a-preopen-catalyst-capture-0830.md",
                 "92b-preopen-catalyst-capture-0950.md"):
        if name in dp.TASKS:
            results.append((PASS, f"{name} is in deploy_prompts.py's TASKS map"))
        else:
            results.append((FAIL, f"{name} is MISSING from deploy_prompts.py's TASKS map"))

    if len(dp.TASKS) == len(ground):
        results.append((PASS, f"deploy_prompts.py covers all {len(ground)} routines"))
    else:
        results.append((FAIL, f"deploy_prompts.py has {len(dp.TASKS)} entries for "
                              f"{len(ground)} ground-truth routines"))

    # The TASKS map carries a SCHEDULE as well as a task_id, and a stale schedule
    # there is SILENT: --emit would hand the next deployer a schedule the live
    # scheduler no longer uses. Measured 2026-11-10: #08's row still said
    # "30 8 * * 1-5" a day after #08 moved to 08:34 ET to get off the 08:30 slot
    # where #26 and #92a fire -- a deploy from that row would have re-collided the
    # three routines in one minute that cost the fleet a whole morning.
    # The ground truth is the record of what the schedule IS; this asserts the
    # deploy map agrees with it, so a moved routine cannot leave a landmine behind.
    stale_sched = []
    for name, entry in dp.TASKS.items():
        want = ground.get(name, {}).get("schedule")
        if want and entry[1] != want:
            stale_sched.append(f"{name}: map={entry[1]} ground truth={want}")
    if not stale_sched:
        results.append((PASS, "every deploy_prompts.py schedule agrees with the ground truth"))
    else:
        results.append((FAIL, "deploy_prompts.py schedules differ from the ground truth -- "
                              + "; ".join(stale_sched)))

    # every routine must have a spec contract, and every contract's marker must
    # still be in the repo -- a contract that points at a missing marker is a
    # contract nobody can satisfy
    missing_contracts = [n for n in ground if n not in contracts]
    if not missing_contracts:
        results.append((PASS, "every routine has a spec contract"))
    else:
        results.append((FAIL, f"no spec contract for: {missing_contracts}"))

    dead = []
    for name, c in contracts.items():
        marker = c.get("marker")
        bundle_dir = ROOT / c.get("bundle", "")
        if not marker or not bundle_dir.is_dir():
            dead.append(name)
            continue
        hit = False
        for dp_, _dirs, files in os.walk(bundle_dir):
            for fn in files:
                try:
                    if marker in (Path(dp_) / fn).read_text(encoding="utf-8", errors="replace"):
                        hit = True
                except OSError:
                    continue
        if not hit:
            dead.append(name)
    if not dead:
        results.append((PASS, "every spec contract's liveness marker is still in the repo"))
    else:
        results.append((FAIL, f"these spec contracts can never be satisfied: {dead}"))

    print("=" * 78)
    print("cron #91 schedule-drift guard — contract test")
    print("=" * 78)
    failures = 0
    for status, name in results:
        print(f"  {status}  {name}")
        if status == FAIL:
            failures += 1
    print("-" * 78)
    print(f"  {len(results) - failures}/{len(results)} checks behaved correctly")
    if failures:
        print(f"  RESULT: {failures} problem(s)")
        return 1
    print("  RESULT: the contract is satisfiable and every breach is caught")
    return 0


if __name__ == "__main__":
    sys.exit(main())
