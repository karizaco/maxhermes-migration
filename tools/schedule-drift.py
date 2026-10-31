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

USAGE
-----
  python3 schedule-drift.py --tasks tasks.json                # report only
  python3 schedule-drift.py --tasks tasks.json --repair       # report + fix via API
  python3 schedule-drift.py --tasks tasks.json --json         # machine-readable

`tasks.json` is the raw JSON of `cron_read {"view":"list","limit":100}`, saved
verbatim to a file. Never re-type it -- dump it to disk and hash it.

EXIT CODES
----------
  0  no drift
  1  drift found (and, with --repair, repaired)
  2  usage / input error
"""
import argparse, json, os, sys, urllib.parse

# ---------------------------------------------------------------------------
# GROUND TRUTH is loaded from tools/schedule-ground-truth.json, never from the
# live scheduler. Regenerating it from the live state would make this check
# agree with the corruption, which is the one thing it must never do.
# ---------------------------------------------------------------------------
GROUND_TRUTH_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "schedule-ground-truth.json")
EXPECTED_TZ = "America/New_York"


def load_ground_truth(path=GROUND_TRUTH_PATH):
    """Load {cron_name: {schedule, timezone}} from the ground-truth file."""
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    return {k: (v["schedule"], v.get("timezone", EXPECTED_TZ))
            for k, v in doc["routines"].items()}


def load_tasks(path):
    """Parse the saved `cron_read view=list` JSON.

    Accepts either the raw response envelope or a bare list of tasks, and also
    tolerates the tool-result artifact shape where the JSON is embedded in a
    larger document.
    """
    with open(path, encoding="utf-8") as fh:
        raw = fh.read()
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError:
        # The chunk file may be wrapped; find the outermost JSON object.
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start < 0 or end <= start:
            raise SystemExit("cannot parse tasks JSON")
        doc = json.loads(raw[start:end])
    if isinstance(doc, dict):
        if "response" in doc and isinstance(doc["response"], dict):
            doc = doc["response"]
        if isinstance(doc, dict) and "tasks" in doc:
            return doc["tasks"]
    if isinstance(doc, list):
        return doc
    raise SystemExit("no task list found in the JSON")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tasks", required=True, help="saved cron_read view=list JSON")
    ap.add_argument("--repair", action="store_true",
                    help="repair drift via cron_update (needs the MCP tools)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--ground-truth", default=GROUND_TRUTH_PATH,
                    help="ground-truth JSON (default: tools/schedule-ground-truth.json)")
    args = ap.parse_args()

    if not os.path.exists(args.tasks):
        print(f"ERROR: no such file: {args.tasks}")
        return 2

    tasks = load_tasks(args.tasks)
    try:
        EXPECTED = load_ground_truth(args.ground_truth)
    except FileNotFoundError:
        print(f"ERROR: ground truth not found: {args.ground_truth}")
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
        want_sched, want_tz = EXPECTED[name]
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

    report = {"drift": drift, "unknown_routines": unknown, "missing_routines": missing,
              "checked": len(seen), "repaired": []}

    if args.repair and drift:
        report["repaired"] = repair(drift)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"checked {len(seen)} routines against the ground truth")
        if not drift and not unknown and not missing:
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

    return 1 if (drift or unknown or missing) else 0


def repair(drift):
    """Repair each drifted routine with cron_update.

    Only `schedule` and `timezone` are sent. NEVER send `model` (the MCP tool has
    no such field) and never send `enabled` (the transport coerces it to the
    string "true" and validation fails). A partial update preserves the model
    config, the prompt, the session binding, the project and the task_id --
    verified 2026-10-31 on cron #26: repairing the schedule left the model's
    `thinking.effort: high` untouched.
    """
    import subprocess, tempfile
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
