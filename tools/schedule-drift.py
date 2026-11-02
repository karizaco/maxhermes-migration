#!/usr/bin/env python3
"""
Compare the LIVE scheduler's cron expressions against the ground truth and report drift.

WHY THIS EXISTS
---------------
Saving a scheduled task in the agent.minimax.io WEB GUI silently corrupts the
day-of-week field of a weekday routine. Measured 2026-10-31: a routine whose live
schedule was `30 8 * * 1-5` (Mon-Fri) came back as `30 8 * * 1` (Mondays only)
after a GUI save that changed NOTHING about the schedule -- only the model effort.
The day-of-week dropdown in the web UI holds a single day and cannot express a range,
so it collapses `1-5` to `1`. The corruption is silent: `next_run` does not change
(it was already the next Monday), and the GUI still shows a plausible schedule.

THE TRAP
--------
`next_run` cannot detect this. A Monday-only routine and a Mon-Fri routine that
was just saved have the SAME next_run (the coming Monday). The difference only
becomes visible on Tuesday, when the Monday-only routine silently does not fire.

THE GROUND TRUTH
----------------
`tools/schedule-ground-truth.json` (next to this script) is the ground truth -- NOT the
live scheduler and NOT the GUI. It was reconstructed from `migration-state.json` (the
2026-09-25 snapshot of the source `mavis cron list`, i.e. the ORIGINAL local Windows
crons of record) plus the intentional post-migration changes recorded in
`cloud-prompts/cron-prompts/README.md` and the `## SCHEDULE` block of each routine's
prompt.

Every weekday routine in `migration-state.json` is `1-5`. Only genuinely weekly
routines carry a single day. That is the invariant the ground truth encodes.

CONVERSATION HYGIENE (second job, added 2026-11-02)
---------------------------------------------------
Every routine in this fleet must run in `session.mode: "new"` -- a FRESH conversation
per fire. A routine bound to a fixed conversation piles every run into one thread,
which breaks the "fresh session, ephemeral artifact" contract the artifact routines
depend on, and it makes the sidebar unreadable.

Two checks:

  L1 (static, free): every routine's live `session.mode` must equal the ground truth
     (`new`). A GUI save can flip this the same way it collapses a day-of-week field.

  L2 (runtime, exact): the run history. `cron_read {"view":"runs"}` returns the recent
     runs of a task, each with its own `session_id`. If two runs of the SAME task
     share one `session_id`, that routine did NOT create a new conversation -- the
     conversation was reused. This is the exact proof; the conversation LIST is not,
     because the platform prunes old conversations (measured 2026-11-02: only 86
     conversations survived for hundreds of fires, so counting conversations proves
     nothing).

USAGE
-----
  python3 schedule-drift.py --tasks tasks.json                    # schedule + session mode
  python3 schedule-drift.py --tasks tasks.json --run-chunks GLOB  # + reuse proof (from tool-result chunks)
  python3 schedule-drift.py --tasks tasks.json --runs-file runs.txt # + reuse proof (from a run table)
  python3 schedule-drift.py --tasks tasks.json --repair           # report + fix via API
  python3 schedule-drift.py --tasks tasks.json --json              # machine-readable

`tasks.json` is the raw JSON of `cron_read {"view":"list","limit":100}`, saved
verbatim to a file. Never re-type it -- dump it to disk and hash it.
`--run-chunks` points at the directory holding the persisted tool-result chunks of
the per-task `cron_read view=runs` calls (default: the sandbox tool-result dir).
The script scans every chunk, picks up the ones that carry a "runs" array and groups
them by task_id.

EXIT CODES
----------
  0  no drift, no conversation findings
  1  findings (schedule drift and/or conversation reuse) -- read the prefixes
  2  usage / input error

  Prefixes in the human-readable output:
     DRIFT        schedule/timezone drift -- repairable with cron_update
     SESSION-MODE live session mode != ground truth -- REPORT, never auto-repair
     CONV-REUSE   two runs of one routine share a session_id -- REUSE CONFIRMED
"""
import argparse, glob, json, os, re, sys, urllib.parse
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# GROUND TRUTH is loaded from tools/schedule-ground-truth.json, never from the
# live scheduler. Regenerating it from the live state would make this check
# agree with the corruption, which is the one thing it must never do.
# ---------------------------------------------------------------------------
GROUND_TRUTH_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "schedule-ground-truth.json")
EXPECTED_TZ = "America/New_York"
SESSION_MODE_DEFAULT = "new"
DEFAULT_RUN_CHUNKS = "/workspace/.mavis/tool-results/*/*/chunks/*.txt"


def _et_tz():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(EXPECTED_TZ)
    except Exception:                                   # noqa: BLE001
        return timezone(timedelta(hours=-5), "EST")


def load_ground_truth(path=GROUND_TRUTH_PATH):
    """Load {cron_name: {schedule, timezone, session_mode}} from the ground truth."""
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    default_mode = (doc.get("session_mode_invariant") or {}).get("mode",
                                                                SESSION_MODE_DEFAULT)
    out = {}
    for name, v in doc.get("routines", {}).items():
        out[name] = {
            "schedule": v["schedule"],
            "timezone": v.get("timezone", EXPECTED_TZ),
            "session_mode": v.get("session_mode", default_mode),
        }
    return out


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
    """Parse the saved `cron_read view=list` JSON.

    Accepts either the raw response envelope or a bare list of tasks, and also
    tolerates the tool-result artifact shape where the JSON is embedded in a
    larger document.
    """
    doc = _read_json(path)
    if isinstance(doc, dict):
        if "response" in doc and isinstance(doc["response"], dict):
            doc = doc["response"]
        if isinstance(doc, dict) and "tasks" in doc:
            return doc["tasks"]
    if isinstance(doc, list):
        return doc
    raise ValueError("no task list found in the JSON")


def scan_run_chunks(pattern):
    """Collect every `cron_read view=runs` result from the persisted chunks.

    A chunk is a tool-result artifact file. It counts as a run record when it
    parses as JSON and carries a "runs" array under "response".
    """
    runs_by_task, files = {}, 0
    for path in sorted(glob.glob(pattern)):
        try:
            doc = _read_json(path)
        except Exception:                               # noqa: BLE001
            continue
        if not isinstance(doc, dict):
            continue
        resp = doc.get("response")
        if not isinstance(resp, dict):
            continue
        runs = resp.get("runs")
        if not isinstance(runs, list):
            continue
        files += 1
        for run in runs:
            if not isinstance(run, dict):
                continue
            tid = run.get("task_id")
            if tid is None:
                continue
            runs_by_task.setdefault(str(tid), []).append(run)
    return runs_by_task, files


def parse_runs_file(path):
    """Parse the agent-written run table: one run per line.

    Format (all three values copied verbatim from `cron_read view=runs`):
        <task_id> <session_id> <scheduled_at_ms>

    A line whose session_id or timestamp is not a plausible integer, or whose
    timestamp is far outside the recent past, is REJECTED with a warning -- a
    mis-transcribed digit must never turn into a false "reuse" finding.
    """
    runs_by_task, rejected = {}, 0
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) != 3:
                rejected += 1
                continue
            task_id, session_id, sched = parts
            if not (task_id.isdigit() and session_id.isdigit() and sched.isdigit()):
                rejected += 1
                continue
            runs_by_task.setdefault(task_id, []).append({
                "task_id": task_id,
                "session_id": session_id,
                "scheduled_at_ms": int(sched),
                "run_id": None,
            })
    return runs_by_task, rejected


def check_session_modes(tasks, EXPECTED):
    """L1: live session.mode vs the ground truth."""
    findings = []
    for t in tasks:
        name = urllib.parse.unquote(t.get("cron_name", ""))
        if not name.endswith(".md") or name not in EXPECTED:
            continue
        want = EXPECTED[name].get("session_mode", SESSION_MODE_DEFAULT)
        sess = t.get("session") or {}
        live_mode = sess.get("mode") or ""
        live_sid = sess.get("session_id") or ""
        if live_mode != want:
            findings.append({
                "task_id": t.get("task_id"),
                "cron_name": name,
                "live_session_mode": live_mode,
                "expected_session_mode": want,
                "live_session_id": live_sid,
            })
    return findings


def check_conversation_reuse(tasks, runs_by_task):
    """L2: two runs of one task sharing a session_id == the conversation was reused."""
    findings, checked = [], []
    for t in tasks:
        name = urllib.parse.unquote(t.get("cron_name", ""))
        if not name.endswith(".md"):
            continue
        tid = str(t.get("task_id"))
        runs = sorted(runs_by_task.get(tid, []),
                      key=lambda r: r.get("scheduled_at_ms") or 0)
        if not runs:
            continue
        sids = [r.get("session_id") for r in runs]
        distinct = sorted({s for s in sids if s})
        checked.append({
            "cron_name": name,
            "task_id": t.get("task_id"),
            "runs": len(runs),
            "distinct_conversations": len(distinct),
        })
        for sid in distinct:
            same = [r for r in runs if r.get("session_id") == sid]
            if len(same) > 1:
                findings.append({
                    "task_id": t.get("task_id"),
                    "cron_name": name,
                    "session_id": sid,
                    "runs": len(runs),
                    "distinct_conversations": len(distinct),
                    "reused_in_runs": [
                        {"scheduled_at_ms": r.get("scheduled_at_ms"),
                         "run_id": r.get("run_id")} for r in same
                    ],
                })
                break
    return findings, checked


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tasks", required=True, help="saved cron_read view=list JSON")
    ap.add_argument("--run-chunks", default=DEFAULT_RUN_CHUNKS,
                    help="glob for the persisted cron_read view=runs tool results")
    ap.add_argument("--runs-file", help="agent-written run table: '<task_id> <session_id> <scheduled_at_ms>' per line")
    ap.add_argument("--no-run-chunks", action="store_true",
                    help="skip the conversation-reuse proof (schedule check only)")
    ap.add_argument("--repair", action="store_true",
                    help="repair drift via cron_update (needs the MCP tools)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--now", help="epoch seconds for the reference time (testing)")
    ap.add_argument("--ground-truth", default=GROUND_TRUTH_PATH,
                    help="ground-truth JSON (default: tools/schedule-ground-truth.json)")
    args = ap.parse_args()

    if not os.path.exists(args.tasks):
        print(f"ERROR: no such file: {args.tasks}")
        return 2

    try:
        tasks = load_tasks(args.tasks)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 2
    try:
        EXPECTED = load_ground_truth(args.ground_truth)
    except FileNotFoundError:
        print(f"ERROR: ground truth not found: {args.ground_truth}")
        return 2

    now = datetime.now(_et_tz())
    if args.now:
        try:
            now = datetime.fromtimestamp(float(args.now), _et_tz())
        except ValueError:
            print("ERROR: --now must be epoch seconds")
            return 2

    drift, unknown, missing = [], [], []
    seen = set()
    for t in tasks:
        # The platform URL-encodes the cron_name, so cron #07 arrives as
        # "07-stock-screener-focus-rvol-09%3A45.md" while the repo file is
        # "...-09:45.md". Decode before matching, or the routine silently
        # reports as UNKNOWN + MISSING instead of being checked.
        name = urllib.parse.unquote(t.get("cron_name", ""))
        if name.startswith("@"):
            continue                      # self-reminders are not fleet routines
        if not name.endswith(".md"):
            continue
        seen.add(name)
        if name not in EXPECTED:
            unknown.append(name)
            continue
        want_sched = EXPECTED[name]["schedule"]
        want_tz = EXPECTED[name]["timezone"]
        live_sched = (t.get("schedule") or "").strip()
        live_tz = (t.get("timezone") or "").strip()
        if live_sched != want_sched or live_tz != want_tz:
            drift.append({
                "task_id": t.get("task_id"),
                "cron_name": name,
                "live_schedule": live_sched,
                "expected_schedule": want_sched,
                "live_timezone": live_tz,
                "expected_timezone": want_tz,
                "next_run": t.get("next_run"),
                "model": t.get("model"),
            })

    for name in EXPECTED:
        if name not in seen:
            missing.append(name)

    mode_findings = check_session_modes(tasks, EXPECTED)

    reuse_findings, conv_checked = [], []
    run_files = 0
    rejected = 0
    runs_by_task = {}
    if args.runs_file:
        if not os.path.exists(args.runs_file):
            print(f"ERROR: no such file: {args.runs_file}")
            return 2
        runs_by_task, rejected = parse_runs_file(args.runs_file)
    elif not args.no_run_chunks:
        runs_by_task, run_files = scan_run_chunks(args.run_chunks)
    reuse_findings, conv_checked = check_conversation_reuse(tasks, runs_by_task)

    report = {"drift": drift, "unknown_routines": unknown, "missing_routines": missing,
              "session_mode_findings": mode_findings,
              "conversation_reuse_findings": reuse_findings,
              "conversation_checked": conv_checked,
              "run_chunk_files": run_files,
              "checked": len(seen), "repaired": []}

    if args.repair and drift:
        report["repaired"] = repair(drift)

    findings = bool(drift or unknown or missing or mode_findings or reuse_findings)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"checked {len(seen)} routines against the ground truth")
        if not findings:
            print("OK: no schedule drift")
        for d in drift:
            print(f"DRIFT  {d['cron_name']}")
            print(f"         live    {d['live_schedule']}  tz={d['live_timezone']}")
            print(f"         expected {d['expected_schedule']}  tz={d['expected_timezone']}")
            print(f"         task_id {d['task_id']}")
        for n in unknown:
            print(f"UNKNOWN  {n}  (not in the ground truth -- add it or ignore)")
        for n in missing:
            print(f"MISSING  {n}  (in the ground truth but not on the scheduler)")
        for r in report["repaired"]:
            print(f"REPAIRED  {r['cron_name']} -> {r['schedule']} (verified)")
        for r in report.get("failed", []):
            print(f"REPAIR-FAILED  {r['cron_name']}: {r['error']}")
        for m in mode_findings:
            print(f"SESSION-MODE  {m['cron_name']}: live mode='{m['live_session_mode']}' "
                  f"expected '{m['expected_session_mode']}' "
                  f"(task_id {m['task_id']}, session_id {m['live_session_id'] or '-'})")
        if rejected:
            print(f"WARNING: {rejected} run-table line(s) rejected as malformed "
                  f"-- a mis-copied digit cannot create a false reuse finding")
        fires = sum(c["runs"] for c in conv_checked)
        convos = sum(c["distinct_conversations"] for c in conv_checked)
        print(f"CONVERSATIONS  {len(conv_checked)} routines checked, {fires} recent run(s), "
              f"{convos} distinct conversation(s)")
        for r in reuse_findings:
            print(f"CONV-REUSE  {r['cron_name']}: conversation {r['session_id']} was used by "
                  f"{len(r['reused_in_runs'])} runs (task_id {r['task_id']})")
            for rr in r["reused_in_runs"]:
                when = ""
                if rr.get("scheduled_at_ms"):
                    when = datetime.fromtimestamp(rr["scheduled_at_ms"] / 1000,
                                                  _et_tz()).strftime("%Y-%m-%d %H:%M ET")
                print(f"           run_id {rr.get('run_id')} scheduled {when}")
        print(f"RESULT: schedule_drift={len(drift)} unknown={len(unknown)} "
              f"missing={len(missing)} session_mode={len(mode_findings)} "
              f"conv_reuse={len(reuse_findings)} routines_with_runs={len(conv_checked)}")

    return 1 if findings else 0


def repair(drift):
    """Repair each drifted routine with cron_update.

    Only `schedule` and `timezone` are sent. NEVER send `model` (the MCP tool has
    no such field) and never send `enabled` (the transport coerces it to the
    string "true" and validation fails). A partial update preserves the model
    config, the prompt, the session binding, the project and the task_id --
    verified 2026-10-31 on cron #26: repairing the schedule left the model's
    `thinking.effort: high` untouched.

    Session-mode and conversation-reuse findings are NEVER repaired here. A
    fixed-conversation binding can be a deliberate choice, and the only safe
    response is to report it.
    """
    import subprocess
    repaired, failed = [], []
    for d in drift:
        payload = json.dumps({
            "task_id": d["task_id"],
            "schedule": d["expected_schedule"],
            "timezone": d["expected_timezone"],
        })
        try:
            res = subprocess.run(
                ["mcp_invoke", "--tool", "cron_update", "--args", payload],
                capture_output=True, text=True, timeout=120)
            out = (res.stdout or "") + (res.stderr or "")
            if res.returncode == 0 and '"ok": true' in out:
                repaired.append({"cron_name": d["cron_name"],
                                "schedule": d["expected_schedule"],
                                "task_id": d["task_id"]})
            else:
                failed.append({"cron_name": d["cron_name"], "error": out.strip()[:400]})
        except Exception as exc:                     # noqa: BLE001
            failed.append({"cron_name": d["cron_name"], "error": repr(exc)[:400]})
    return repaired


if __name__ == "__main__":
    sys.exit(main())
