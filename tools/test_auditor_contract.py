#!/usr/bin/env python3
"""
test_auditor_contract.py - prove cron #90's audit contract is satisfiable AND
that the gate actually catches a breach.

WHY
---
A checker that only ever fails is a checker nobody trusts, and a contract nobody
can satisfy is a contract that gets skipped. This test does both:

  1. builds a synthetic audit (a status file + the digest that would be
     published) in the shape of a real 2026-11-03 run,
  2. runs `check_auditor_contract.py` over it and requires exit 0,
  3. then MUTATES that status file and that digest a dozen different ways and
     requires the gate to fail each time,
  4. and proves the standing roster self-check catches the EXACT bug it was
     written for: a live routine that is missing from the ground truth. The
     fixture is cron #26b - the routine that really was unmonitored on
     2026-11-03 while the audit reported `roster_desync: 0`.

USAGE
    python3 tools/test_auditor_contract.py

EXIT CODES
    0  all good
    1  a breach was not caught, or the contract cannot be met
"""

import copy
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CK = ROOT / "tools" / "check_auditor_contract.py"
RC = ROOT / "tools" / "auditor_roster_check.py"
GT = ROOT / "tools" / "schedule-ground-truth.json"

PASS, FAIL = "PASS", "FAIL"

# ----------------------------------------------------------------------------------
# a contract-shaped audit: one MISSING gap, one reconstructed artifact, one
# deliberate skip, and one routine on a three-fire streak.
# ----------------------------------------------------------------------------------
STATUS = {
    "audit_date_et": "2026-11-03",
    "audit_run_et": "2026-11-04T07:00:00-04:00",
    "origin_main_sha": "3a8c868",
    "due": 25,
    "delivered": 23,
    "missing": 1,
    "skipped_by_design_count": 1,
    "not_yet_fired": ["91-schedule-drift-guard"],
    "written_off": ["14-macro-calendar-week-ahead:2026-10-25"],
    "roster_gap": [],
    "skipped_by_design": [
        {"routine": "92a-preopen-catalyst-capture",
         "reason": "XAI_API_KEY unset - nothing written",
         "marker": "refs/skipped-markers/2026-11-03_SKIPPED_preopen_capture_0830.md"}
    ],
    "gaps": [
        {"routine": "25-ntrt-gap-brief-daily", "path": "ntrt/2026-11-02.md",
         "label": "MISSING", "cause": "platform_500", "gap_age_hours": 18.4, "streak": 1},
        {"routine": "20-eod-watchlist-csv-snapshot", "path": "us-eod/2026-11-02.csv",
         "label": "reconstructed", "cause": "delayed_replay", "gap_age_hours": 20.2,
         "streak": 1},
        {"routine": "26b-agentic-pre-market-brief-refresh",
         "path": "daily-briefs/2026-11-02-pre-market-refresh.md",
         "label": "stalled", "cause": "quota_2056", "gap_age_hours": 26.1, "streak": 0},
    ],
    "routines": {
        "25-ntrt-gap-brief-daily": {"routine": "25-ntrt-gap-brief-daily",
                                     "state": "missing", "streak": 1,
                                     "delivery_latency_min": None},
        "20-eod-watchlist-csv-snapshot": {"routine": "20-eod-watchlist-csv-snapshot",
                                           "state": "missing", "streak": 1,
                                           "delivery_latency_min": None},
        "92a-preopen-catalyst-capture": {"routine": "92a-preopen-catalyst-capture",
                                          "state": "skipped_by_design", "streak": 0,
                                          "delivery_latency_min": None},
        "16-unusual-options-flow-daily": {"routine": "16-unusual-options-flow-daily",
                                          "state": "missing", "streak": 3,
                                          "delivery_latency_min": None},
        "26b-agentic-pre-market-brief-refresh": {"routine": "26b-agentic-pre-market-brief-refresh",
                                              "state": "delivered_late", "streak": 0,
                                              "delivery_latency_min": 1284.0},
        "15-earnings-reaction-scanner": {"routine": "15-earnings-reaction-scanner",
                                           "state": "delivered", "streak": 0,
                                           "delivery_latency_min": 28.4},
    },
    "audit_status": "gaps_found",
}

DIGEST = """audit: 2026-11-03 due=25 delivered=23 missing=1
gap: 25-ntrt-gap-brief-daily MISSING ntrt/2026-11-02.md — cause=platform_500 age_h=18.4 — the 09:00 ET fire died with a platform 500 before writing; rebuilt 2026-11-03 03:21 ET
gap: 20-eod-watchlist-csv-snapshot reconstructed us-eod/2026-11-02.csv — cause=delayed_replay age_h=20.2 — delayed replay, rebuilt 2026-11-03 03:48 ET from the TradingView scanner
gap: 26b-agentic-pre-market-brief-refresh stalled daily-briefs/2026-11-02-pre-market-refresh.md — cause=quota_2056 age_h=26.1 — the 09:20 ET fire was rejected on the Token Plan 5-hour window (2056) and resumed in place; the artifact landed 1284 min after its schedule
skipped: 92a-preopen-catalyst-capture XAI_API_KEY unset - nothing written — refs/skipped-markers/2026-11-03_SKIPPED_preopen_capture_0830.md
streak: 16-unusual-options-flow-daily 3 consecutive missed fires
push: ok (verified)
errors: 0
"""

# The SAME audit, on the state of the world on 2026-11-03: #26b was live on the
# scheduler but absent from the ground truth, so the auditor could not see it.
STATUS_ROSTER_GAP = copy.deepcopy(STATUS)
STATUS_ROSTER_GAP["roster_gap"] = [
    {"name": "26b-agentic-pre-market-brief-refresh-0920.md", "task_id": "459637559267655"}
]
DIGEST_ROSTER_GAP = DIGEST.replace(
    "streak: 16-unusual-options-flow-daily 3 consecutive missed fires",
    "roster_gap: 26b-agentic-pre-market-brief-refresh-0920.md (task 459637559267655) "
    "is live but not in schedule-ground-truth.json\n"
    "streak: 16-unusual-options-flow-daily 3 consecutive missed fires")

# A saved `cron_read view=list` payload with the live fleet shape. 26b IS live
# here - that is the bug the roster check exists to catch.
TASKS = {
    "response": {
        "tasks": [
            {"task_id": "457172664209604", "cron_name": "06-stock-screener-pattern-study-backlog.md",
             "schedule": "0 15 * * 6", "timezone": "America/New_York", "enabled": True},
            {"task_id": "457957802930526", "cron_name": "90-delivery-auditor.md",
             "schedule": "0 7 * * *", "timezone": "America/New_York", "enabled": True},
            {"task_id": "459637559267655",
             "cron_name": "26b-agentic-pre-market-brief-refresh-0920.md",
             "schedule": "20 9 * * 1-5", "timezone": "America/New_York", "enabled": True},
            {"task_id": "460347811242340",
             "cron_name": "@self-reminder/47324930516ac460be184774e9643c3ebdf9809f883aced257cbe54a0e0e4ded",
             "schedule": "", "timezone": "", "enabled": True},
            {"task_id": "459969348174190", "cron_name": "verify-cron12-window-roll-2026-11-05",
             "schedule": "", "timezone": "America/New_York", "enabled": True},
        ],
        "has_more": False,
    }
}

RESULTS = []


def record(ok, name, detail=""):
    RESULTS.append((PASS if ok else FAIL, name, detail))
    return ok


def run_checker(tmp, status, digest, tasks=None, prompt=None, ground_truth=None,
                procedure=None, contract=None):
    s = tmp / "status.json"
    s.write_text(json.dumps(status, indent=1), encoding="utf-8")
    d = tmp / "digest.txt"
    d.write_text(digest[0] if isinstance(digest, list) else digest, encoding="utf-8")
    cmd = [sys.executable, str(CK), "--status", str(s), "--reply", str(d)]
    if tasks is not None:
        t = tmp / "tasks.json"
        t.write_text(json.dumps(tasks), encoding="utf-8")
        cmd += ["--tasks", str(t)]
    if ground_truth is not None:
        cmd += ["--ground-truth", str(ground_truth)]
    if prompt is not None:
        cmd += ["--prompt", str(prompt)]
    if procedure is not None:
        cmd += ["--procedure", str(procedure)]
    if contract is not None:
        cmd += ["--contract", str(contract)]
    p = subprocess.run(cmd, capture_output=True, text=True)
    first = ""
    for line in p.stdout.splitlines():
        if line.startswith("FAIL "):
            first = line.strip()
            break
    return p.returncode, first or (p.stdout.strip().splitlines() or [""])[-1]


def expect_catch(tmp, name, mutate, cid=None):
    """Mutate the fixture and require the gate to fail (with one of `cid`)."""
    status = copy.deepcopy(STATUS)
    digest = [DIGEST]
    tasks = copy.deepcopy(TASKS)
    mutate(status, digest, tasks)
    rc, detail = run_checker(tmp, status, digest, tasks=tasks)
    if rc == 0:
        return record(False, name, "the gate returned exit 0")
    if cid:
        wanted = (cid,) if isinstance(cid, str) else tuple(cid)
        if not any(c in detail for c in wanted):
            return record(False, name, f"failed with '{detail}', expected one of {wanted}")
    return record(True, name, detail)


def main():
    tmpdir = tempfile.mkdtemp(prefix="auditor-contract-")
    tmp = Path(tmpdir)

    print("=" * 78)
    print("cron #90 delivery-auditor contract — regression test")
    print("=" * 78)

    # --- 1. the contract is satisfiable -----------------------------------------
    rc, detail = run_checker(tmp, copy.deepcopy(STATUS), DIGEST, tasks=copy.deepcopy(TASKS))
    record(rc == 0, "the contract-shaped audit passes the gate", detail)

    # --- 2. every breach must be caught ------------------------------------------
    def drop_cause(s, digest, t):
        s["gaps"][0]["cause"] = ""
    expect_catch(tmp, "a gap with an EMPTY cause is caught", drop_cause, "C04")

    def bad_cause(s, digest, t):
        s["gaps"][0]["cause"] = "the_weather_was_bad"
    expect_catch(tmp, "a gap with a cause outside the vocabulary is caught", bad_cause, "C04")

    def wrong_pair(s, digest, t):
        s["gaps"][0]["cause"] = "skipped_by_design"
    expect_catch(tmp, "a MISSING gap caused by skipped_by_design is caught", wrong_pair, "C05")

    def skip_and_missing(s, digest, t):
        s["gaps"].append({"routine": "92a-preopen-catalyst-capture",
                          "path": "preopen-feed/2026-11-03-0830.jsonl",
                          "label": "MISSING", "cause": "never_fired",
                          "gap_age_hours": 6.5, "streak": 1})
        s["missing"] = 2
        digest[0] = digest[0].replace("missing=1", "missing=2")
    expect_catch(tmp, "a routine that skipped by design is never MISSING is caught",
                 skip_and_missing, "C09")

    def skip_no_reason(s, digest, t):
        s["skipped_by_design"][0]["reason"] = "   "
    expect_catch(tmp, "a skipped_by_design without a reason is caught", skip_no_reason, "C08")

    def no_age(s, digest, t):
        del s["gaps"][0]["gap_age_hours"]
    expect_catch(tmp, "a gap without gap_age_hours is caught", no_age, "C03")

    def no_streak(s, digest, t):
        del s["gaps"][0]["streak"]
    expect_catch(tmp, "a gap without streak is caught", no_streak, "C03")

    def bad_streak(s, digest, t):
        s["gaps"][0]["streak"] = "two"
    expect_catch(tmp, "a gap with a non-integer streak is caught", bad_streak, "C07")

    def bad_count(s, digest, t):
        s["missing"] = 5
    expect_catch(tmp, "a missing count that disagrees with the gaps is caught",
                 bad_count, "C10")

    def digest_no_cause(s, digest, t):
        digest[0] = digest[0].replace("cause=platform_500 age_h=18.4",
                                       "the fire died with a platform 500")
    expect_catch(tmp, "a digest gap line without a cause is caught", digest_no_cause, "D04")

    # --- 2b. the 2026-11-12 additions: connection_error, the per-routine
    #        allowance (C17) and the degraded-artifact pairing (C18) ---------------

    # a MISSING whose fire produced NO model call at all is `connection_error`
    st = copy.deepcopy(STATUS)
    dg = copy.deepcopy(DIGEST)
    st["gaps"][0]["cause"] = "connection_error"
    dg = dg.replace("cause=platform_500 age_h=18.4", "cause=connection_error age_h=18.4")
    rc, detail = run_checker(tmp, st, dg, tasks=copy.deepcopy(TASKS))
    record(rc == 0, "a MISSING caused by connection_error passes the gate", detail)

    # C17: a routine over the allowance cannot be published as plain `delivered`
    def over_but_delivered(s, digest, t):
        s["routines"]["15-earnings-reaction-scanner"]["delivery_latency_min"] = 500.0
    expect_catch(tmp, "a delivery over the allowance published as 'delivered' is caught",
                 over_but_delivered, "C17")

    # C17: a routine UNDER the allowance cannot be published as `delivered_late`
    def under_but_late(s, digest, t):
        s["routines"]["26b-agentic-pre-market-brief-refresh"]["delivery_latency_min"] = 10.0
    expect_catch(tmp, "a delivery under the allowance published as 'delivered_late' is caught",
                 under_but_late, "C17")

    # C18: a degraded artifact is a failing delivery, published exactly once
    st = copy.deepcopy(STATUS)
    dg = copy.deepcopy(DIGEST)
    st["gaps"].append({"routine": "15-earnings-reaction-scanner",
                       "path": "earnings/2026-11-02-reactions.md",
                       "label": "present_but_empty", "cause": "push_failure",
                       "gap_age_hours": 18.4, "streak": 0})
    dg = dg.replace("push: ok (verified)",
                    "gap: 15-earnings-reaction-scanner present_but_empty "
                    "earnings/2026-11-02-reactions.md — cause=push_failure age_h=18.4 — "
                    "the push landed a stub\npush: ok (verified)")
    rc, detail = run_checker(tmp, st, dg, tasks=copy.deepcopy(TASKS))
    record(rc == 0, "a degraded artifact published as present_but_empty passes the gate",
           detail)

    def stub_on_a_missing_routine(s, digest, t):
        s["gaps"].append({"routine": "25-ntrt-gap-brief-daily",
                          "path": "ntrt/2026-11-02.md",
                          "label": "present_but_empty", "cause": "push_failure",
                          "gap_age_hours": 18.4, "streak": 1})
    expect_catch(tmp, "a degraded artifact on a MISSING routine is caught",
                 stub_on_a_missing_routine, "C18")

    def stub_double_reported(s, digest, t):
        # 25-ntrt already carries a MISSING gap. Make its state consistent with a
        # delivered file (so C14/C16/C17 stay quiet) and then publish a STUB for the
        # SAME routine: a routine cannot be both missing and degraded.
        s["routines"]["25-ntrt-gap-brief-daily"]["state"] = "delivered"
        s["routines"]["25-ntrt-gap-brief-daily"]["delivery_latency_min"] = 12.0
        s["gaps"].append({"routine": "25-ntrt-gap-brief-daily",
                          "path": "ntrt/2026-11-02.md",
                          "label": "present_but_empty", "cause": "push_failure",
                          "gap_age_hours": 18.4, "streak": 1})
    expect_catch(tmp, "a routine published as both present_but_empty and MISSING is caught",
                 stub_double_reported, "C18")

    def digest_bad_cause(s, digest, t):
        digest[0] = digest[0].replace("cause=platform_500", "cause=it_broke")
    expect_catch(tmp, "a digest gap line with a cause outside the vocabulary is caught",
                 digest_bad_cause, "D04")

    def digest_count(s, digest, t):
        digest[0] = digest[0].replace("missing=1", "missing=2")
    expect_catch(tmp, "a digest whose counts disagree with the status file is caught",
                 digest_count, "D01")

    def digest_no_errors(s, digest, t):
        digest[0] = "\n".join(l for l in digest[0].splitlines()
                              if not l.startswith("errors:")) + "\n"
    expect_catch(tmp, "a digest without an errors line is caught", digest_no_errors, "D03")

    def digest_no_streak(s, digest, t):
        digest[0] = "\n".join(l for l in digest[0].splitlines()
                              if not l.startswith("streak:")) + "\n"
    expect_catch(tmp, "a routine with a three-fire streak that is not surfaced is caught",
                 digest_no_streak, "D10")

    def digest_skipped_as_gap(s, digest, t):
        digest[0] = digest[0].replace(
            "skipped: 92a-preopen-catalyst-capture XAI_API_KEY unset - nothing "
            "written — refs/skipped-markers/2026-11-03_SKIPPED_preopen_capture_0830.md",
            "gap: 92a-preopen-catalyst-capture MISSING "
            "preopen-feed/2026-11-03-0830.jsonl — cause=never_fired age_h=6.5")
    expect_catch(tmp, "a deliberate skip published as a MISSING gap is caught",
                 digest_skipped_as_gap, ("D06", "D08"))

    # --- 2b. the LATENCY dimension: a late delivery must be visible ------------------
    def late_without_gap(s, digest, t):
        # the audit measured the latency but published no 'stalled' line for it
        s["gaps"] = [g for g in s["gaps"] if g.get("label") != "stalled"]
        digest[0] = "\n".join(l for l in digest[0].splitlines()
                              if not l.startswith("gap: 26b-agentic")) + "\n"
    expect_catch(tmp, "a delivered_late routine with no 'stalled' gap line is caught",
                 late_without_gap, "C14")

    def stalled_not_late(s, digest, t):
        s["routines"]["26b-agentic-pre-market-brief-refresh"]["state"] = "delivered"
    expect_catch(tmp, "a 'stalled' gap line for a routine that is not delivered_late is caught",
                 stalled_not_late, "C14")

    def stalled_hidden_as_ok(s, digest, t):
        s["gaps"] = [g for g in s["gaps"]
                     if g.get("label") not in ("MISSING", "reconstructed")]
        digest[0] = "\n".join(l for l in digest[0].splitlines()
                              if not l.startswith("gap: 25-ntrt")
                              and not l.startswith("gap: 20-eod")) + "\n"
        digest[0] = digest[0].replace("missing=1", "missing=0")
        s["missing"] = 0
        s["audit_status"] = "ok"
    expect_catch(tmp, "a stalled delivery hidden behind audit_status ok is caught",
                 stalled_hidden_as_ok, "C13")

    def no_latency(s, digest, t):
        s["routines"]["26b-agentic-pre-market-brief-refresh"]["delivery_latency_min"] = None
    expect_catch(tmp, "a delivered routine with no delivery_latency_min is caught",
                 no_latency, "C16")

    def stalled_wrong_cause(s, digest, t):
        s["gaps"][2]["cause"] = "skipped_by_design"
    expect_catch(tmp, "a 'stalled' gap paired with a cause the label does not accept is caught",
                 stalled_wrong_cause, "C05")

    # --- 3. the roster self-check must catch the bug it was written for ----------
    tasks_path = tmp / "tasks.json"
    tasks_path.write_text(json.dumps(TASKS), encoding="utf-8")

    # With #26b in the real ground truth the check is clean.
    p = subprocess.run([sys.executable, str(RC), "--tasks", str(tasks_path),
                        "--ground-truth", str(GT)], capture_output=True, text=True)
    record(p.returncode == 0, "with #26b in the ground truth the roster check is clean",
           p.stdout.strip().splitlines()[-1] if p.stdout.strip() else "")

    # Take #26b OUT of the ground truth - the state of the world on 2026-11-03 -
    # and the check must catch it, by name and by task id.
    gt = json.loads(GT.read_text(encoding="utf-8"))
    gt["routines"].pop("26b-agentic-pre-market-brief-refresh-0920.md", None)
    gt_path = tmp / "ground-truth-without-26b.json"
    gt_path.write_text(json.dumps(gt, indent=1), encoding="utf-8")
    p = subprocess.run([sys.executable, str(RC), "--tasks", str(tasks_path),
                        "--ground-truth", str(gt_path)], capture_output=True, text=True)
    caught = (p.returncode == 1
              and "26b-agentic-pre-market-brief-refresh-0920.md" in p.stdout
              and "459637559267655" in p.stdout)
    record(caught, "the roster check catches #26b when it is missing from the ground truth",
           p.stdout.strip().splitlines()[-1] if p.stdout.strip() else "")

    # The audit that DID see the gap passes the gate.
    rc, detail = run_checker(tmp, copy.deepcopy(STATUS_ROSTER_GAP), DIGEST_ROSTER_GAP,
                              tasks=copy.deepcopy(TASKS), ground_truth=gt_path)
    record(rc == 0, "an audit that names the live-but-unrostered routine passes the gate",
           detail)

    # The same audit with the roster gap NOT named must fail.
    digest = [DIGEST_ROSTER_GAP.replace(
        "roster_gap: 26b-agentic-pre-market-brief-refresh-0920.md (task 459637559267655) "
        "is live but not in schedule-ground-truth.json\n", "")]
    rc, detail = run_checker(tmp, copy.deepcopy(STATUS_ROSTER_GAP), digest,
                              tasks=copy.deepcopy(TASKS), ground_truth=gt_path)
    record(rc != 0, "the gate fails when a live-but-unrostered routine is not named", detail)

    # And the same audit against the CLEAN ground truth must also fail: the status
    # file claims a roster gap the live fleet does not have.
    rc, detail = run_checker(tmp, copy.deepcopy(STATUS_ROSTER_GAP), DIGEST_ROSTER_GAP,
                              tasks=copy.deepcopy(TASKS))
    record(rc != 0, "the gate fails when the status file claims a roster gap that is not real",
           detail)

    # --- 4. the deployed surfaces must still agree with the contract ------------
    # The PROMPT owns the reply format; the PROCEDURE file (fetched at run time)
    # owns the method and carries the inline fallback copy of the contract.
    prompt = ROOT / "cloud-prompts" / "cron-prompts" / "90-delivery-auditor.md"
    procedure = ROOT / "cloud-prompts" / "_shared" / "auditor-procedure.md"
    if prompt.exists() and procedure.exists():
        ptext = prompt.read_text(encoding="utf-8")
        proc_text = procedure.read_text(encoding="utf-8")
        p2 = tmp / "prompt.md"
        p2.write_text(ptext, encoding="utf-8")
        pr2 = tmp / "procedure.md"
        pr2.write_text(proc_text, encoding="utf-8")
        rc, detail = run_checker(tmp, copy.deepcopy(STATUS), DIGEST,
                                 tasks=copy.deepcopy(TASKS), prompt=str(p2),
                                 procedure=str(pr2))
        record(rc == 0, "the deployed prompt and procedure agree with the contract", detail)

        # anchor on the inline contract block itself (a bare line), not on the first
        # mention of the token anywhere in the prose
        # anchor on the inline causes LINE itself, so the test survives the vocabulary
        # growing (connection_error was added to it on 2026-11-13)
        broken = re.sub(r"\nplatform_500(\s|\n)", r"\nplatform_500X\1", proc_text, count=1)
        p3 = tmp / "procedure-broken.md"
        p3.write_text(broken, encoding="utf-8")
        rc, detail = run_checker(tmp, copy.deepcopy(STATUS), DIGEST,
                                 tasks=copy.deepcopy(TASKS), prompt=str(p2),
                                 procedure=str(p3))
        record(rc != 0, "a drifted inline contract copy in the procedure is caught", detail)

        broken_prompt = ptext.replace("audit: <AUDIT_DATE> due=<n> delivered=<n> missing=<n>",
                                       "audit: <AUDIT_DATE> due=<n> delivered=<n> missing=<x>")
        p4 = tmp / "prompt-broken.md"
        p4.write_text(broken_prompt, encoding="utf-8")
        rc, detail = run_checker(tmp, copy.deepcopy(STATUS), DIGEST,
                                 tasks=copy.deepcopy(TASKS), prompt=str(p4),
                                 procedure=str(pr2))
        record(rc != 0, "a reply template that drifted in the prompt is caught", detail)

        no_marker = proc_text.replace("AUDITOR_PROCEDURE_V1\n", "", 1)
        p5 = tmp / "procedure-nomarker.md"
        p5.write_text(no_marker, encoding="utf-8")
        rc, detail = run_checker(tmp, copy.deepcopy(STATUS), DIGEST,
                                 tasks=copy.deepcopy(TASKS), prompt=str(p2),
                                 procedure=str(p5))
        record(rc != 0, "a procedure file with no capability marker is caught", detail)
    else:
        record(False, "the deployed prompt and the procedure file both exist",
               f"{prompt} / {procedure}")

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
    print("  RESULT: the contract is satisfiable and every breach is caught")
    return 0


if __name__ == "__main__":
    sys.exit(main())
