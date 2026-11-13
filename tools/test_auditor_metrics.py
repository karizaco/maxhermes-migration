#!/usr/bin/env python3
"""
test_auditor_metrics.py - prove cron #90's MEASUREMENT engine measures.

WHY
---
The engine (`tools/auditor_metrics.py`) exists because the audit used to compute its
measurements by hand, in bash loops: one `git ls-tree` per routine, one `git log` per
artifact. A measurement engine that is wrong is worse than no engine - it would replace
eyeballs with a machine and the machine would be confidently wrong.

So the engine is tested against a FIXTURE repo whose contents are known exactly:

  1. the pure helpers (dow matching, schedule compatibility, ISO week, fire times),
  2. an end-to-end run over a purpose-built git repo with KNOWN commit times, where
     the expected latency of every artifact is computable by hand,
  3. the cases that bit the first version: a multi-fire routine's slot timing, a
     routine that publishes a DIRECTORY, a self-check routine that has no artifact,
     and a stub that is not a real artifact.

USAGE
    python3 tools/test_auditor_metrics.py

EXIT CODES
    0  all good
    1  a measurement was wrong
"""
import datetime
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))

import auditor_metrics as AM  # noqa: E402

PASS, FAIL = "PASS", "FAIL"
RESULTS = []


def record(ok, name, detail=""):
    RESULTS.append((PASS if ok else FAIL, name, detail))
    return ok


def check(ok, name, detail=""):
    return record(bool(ok), name, detail)


# ----------------------------------------------------------------------------------
# the fixture: a git repo whose every commit time is known
# ----------------------------------------------------------------------------------
AUDIT_DATE = "2026-11-11"          # a Wednesday
ET = AM.ET


def et_epoch(y, m, d, hh, mm):
    return int(datetime.datetime(y, m, d, hh, mm, tzinfo=ET).timestamp())


def build_fixture(root):
    """A repo with origin/main carrying four artifacts, all at known times."""
    repo = root / "outputs"
    repo.mkdir()
    env = dict(os.environ)
    env.update({
        "GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "f@local",
        "GIT_COMMITTER_NAME": "fixture", "GIT_COMMITTER_EMAIL": "f@local",
    })

    def commit(paths, when):
        e = dict(env)
        stamp = datetime.datetime.fromtimestamp(when, ET).strftime("%Y-%m-%d %H:%M:%S %z")
        e["GIT_AUTHOR_DATE"] = stamp
        e["GIT_COMMITTER_DATE"] = stamp
        for p in paths:
            full = repo / p
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text("fixture artifact for %s\n" % p, encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, env=e,
                       capture_output=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "fixture"],
                       check=True, env=e, capture_output=True)

    subprocess.run(["git", "-C", str(repo), "init", "-q", "-b", "main"],
                   check=True, capture_output=True)
    # #19 at 06:00, landing 14.8 min later
    commit(["earnings/2026-11-11-reminders.md"], et_epoch(2026, 11, 11, 6, 14) + 48)
    # #04 at 15:55, landing 37.5 min later
    commit(["daily-screens/2026-11-11/reversal-bullish-3_55.md"],
           et_epoch(2026, 11, 11, 15, 55) + 37 * 60 + 30)
    # #05 publishes a DIRECTORY of per-region CSVs
    commit(["international-eod/2026-11-11/eu-de.csv",
            "international-eod/2026-11-11/jp.csv"],
           et_epoch(2026, 11, 11, 16, 30) + 14 * 60 + 48)
    # a STUB: the marker that says "this artifact is degraded"
    commit(["ntrt/2026-11-11.md"], et_epoch(2026, 11, 11, 9, 0) + 26 * 60 + 36)
    (repo / "ntrt" / "2026-11-11.md").write_text(
        "# ntrt\n\n_source=skill_fetch_failed\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, env=env,
                   capture_output=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "fixture stub"],
                   check=True, env=env, capture_output=True)
    # #13's artifact is deliberately ABSENT
    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()
    subprocess.run(["git", "-C", str(repo), "update-ref", "refs/remotes/origin/main", head],
                   check=True, capture_output=True)
    return repo


PROCEDURE = """# fixture procedure

AUDITOR_PROCEDURE_V1
PROCEDURE_VERSION: 2026-11-13.1

## STEP 4 — CHECK EVERY ROUTINE

| Routine | Schedule (ET) | Expected artifact on origin/main | Fires on |
|---|---|---|---|
| 19-earnings-reminder-daily | `0 6 * * 1-5` | `earnings/{date}-reminders.md` | Mon-Fri |
| 13-macro-calendar-midweek | `0 14 * * 3` | `macro-calendar/{date}-midweek.md` | Wed |
| 04-reversal-bullish-3:55 | `55 15 * * 1-5` | `daily-screens/{date}/reversal-bullish-3_55.md` | Mon-Fri |
| 05-eod-international-daily | `30 16 * * 1-5` | `international-eod/{date}` | Mon-Fri |
| 25-ntrt-gap-brief-daily | `0 9 * * 1-5` | `ntrt/{date}.md` | Mon-Fri |
| 01-weekly-mcp-health-check | `0 2 * * 0` | `mcp-health/{ISO-week}.md` | Sun |
| 90-delivery-auditor | `0 7 * * *` | (no artifact — this cron) | every day |

## NEXT SECTION
"""


def main():
    print("=" * 78)
    print("cron #90 delivery-auditor — measurement engine test")
    print("=" * 78)

    # --- 1. the pure helpers ----------------------------------------------------
    check(AM.dow_matches("1-5", 1), "a weekday schedule fires on Monday")
    check(AM.dow_matches("1-5", 5), "a weekday schedule fires on Friday")
    check(not AM.dow_matches("1-5", 6), "a weekday schedule does not fire on Saturday")
    check(not AM.dow_matches("1-5", 7), "a weekday schedule does not fire on Sunday")
    check(AM.dow_matches("0", 7), "a Sunday schedule fires on Sunday")
    check(AM.dow_matches("3", 3), "a Wednesday schedule fires on Wednesday")
    check(not AM.dow_matches("3", 4), "a Wednesday schedule does not fire on Thursday")

    check(AM.fire_times("0 7 * * *") == [(7, 0)], "a daily schedule has one fire time")
    check(AM.fire_times("50 9,15 * * 1-5") == [(9, 50), (15, 50)],
          "a two-fire routine has two fire times")

    check(AM.iso_week_of("2026-11-08") == "2026-W45",
          "the ISO week of 2026-11-08 is 2026-W45",
          AM.iso_week_of("2026-11-08"))
    # Sunday 2026-11-08 ends ISO week 45; Monday 2026-11-09 starts week 46, so the
    # Wednesday of the same calendar week is 2026-W46.
    check(AM.iso_week_of("2026-11-11") == "2026-W46",
          "the ISO week of 2026-11-11 is 2026-W46",
          AM.iso_week_of("2026-11-11"))

    # the schedule-compatibility rule: a table row may name ONE SLOT of a task
    check(AM.schedule_compatible("50 9 * * 1-5", "50 9,15 * * 1-5"),
          "a slot's schedule is compatible with its task's schedule")
    check(not AM.schedule_compatible("0 14 * * 3", "0 14 * * 1-5"),
          "a Wednesday-only row is NOT compatible with a Mon-Fri task "
          "(it would hide four days of fires)")
    check(AM.schedule_compatible("50 9 * * 1-5", "50 9,15 * * 1-5"),
          "one slot of a twice-daily task IS compatible with the task")
    check(AM.schedule_compatible("0 14 * * 3", "0 14 * * 3"),
          "an identical schedule is compatible")

    # --- 2. the end-to-end run --------------------------------------------------
    tmp = Path(tempfile.mkdtemp(prefix="auditor-metrics-"))
    repo = build_fixture(tmp)
    procedure = tmp / "procedure.md"
    procedure.write_text(PROCEDURE, encoding="utf-8")
    holidays = tmp / "holidays.txt"
    holidays.write_text("# none\n", encoding="utf-8")

    report = AM.measure(AUDIT_DATE, str(repo), str(procedure),
                         str(HERE / "schedule-ground-truth.json"), str(holidays))
    rows = {r["routine"]: r for r in report["rows"]}

    r19 = rows.get("19-earnings-reminder-daily", {})
    check(r19.get("state_hint") == "due", "#19 is due on a Wednesday", r19.get("state_hint"))
    check(r19.get("present") is True, "#19's artifact is present", r19.get("present"))
    check(abs((r19.get("delivery_latency_min") or 0) - 14.8) < 0.2,
          "#19's latency is 14.8 min", r19.get("delivery_latency_min"))

    r13 = rows.get("13-macro-calendar-midweek", {})
    check(r13.get("state_hint") == "due", "#13 is due on a Wednesday", r13.get("state_hint"))
    check(r13.get("present") is False, "#13's ABSENT artifact is reported missing",
          r13.get("present"))
    check(r13.get("delivery_latency_min") is None,
          "#13 has no latency when it never delivered", r13.get("delivery_latency_min"))

    r04 = rows.get("04-reversal-bullish-3:55", {})
    check(abs((r04.get("delivery_latency_min") or 0) - 37.5) < 0.2,
          "#04's latency is 37.5 min", r04.get("delivery_latency_min"))

    r05 = rows.get("05-eod-international-daily", {})
    check(r05.get("present") is True,
          "a routine that publishes a DIRECTORY is present", r05.get("present"))
    check(abs((r05.get("delivery_latency_min") or 0) - 14.8) < 0.2,
          "a directory artifact's latency is its EARLIEST file's", r05.get("delivery_latency_min"))

    r25 = rows.get("25-ntrt-gap-brief-daily", {})
    check(r25.get("health") == "degraded",
          "a stub carrying a fetch_failed marker is reported degraded", r25.get("health"))

    r01 = rows.get("01-weekly-mcp-health-check", {})
    check(r01.get("state_hint") == "not_due",
          "a Sunday routine is not_due on a Wednesday", r01.get("state_hint"))

    r90 = rows.get("90-delivery-auditor", {})
    check(r90.get("state_hint") == "self_check",
          "a self-check routine is never 'due with no artifact'",
          r90.get("state_hint"))

    check(report.get("audit_date_dow") == "Wed", "the audited weekday is Wednesday",
          report.get("audit_date_dow"))

    # --- 3. the JSON output ------------------------------------------------------
    out = tmp / "metrics.json"
    rc = subprocess.run([sys.executable, str(HERE / "auditor_metrics.py"),
                         "--date", AUDIT_DATE, "--repo", str(repo),
                         "--procedure", str(procedure),
                         "--ground-truth", str(HERE / "schedule-ground-truth.json"),
                         "--holidays", str(holidays),
                         "--json", str(out), "--quiet"],
                        capture_output=True, text=True)
    check(rc.returncode == 0, "the engine runs end to end", rc.stderr[-200:])
    if out.exists():
        data = json.loads(out.read_text(encoding="utf-8"))
        check(isinstance(data.get("rows"), list) and len(data["rows"]) == 7,
              "the JSON carries one row per roster row", len(data.get("rows") or []))
    else:
        check(False, "the JSON output is written", "no file")

    print("-" * 78)
    failures = 0
    for status, name, detail in RESULTS:
        print(f"  {status}  {name}")
        if detail:
            print(f"        {str(detail)[:160]}")
        if status == FAIL:
            failures += 1
    print("-" * 78)
    print(f"  {len(RESULTS) - failures}/{len(RESULTS)} checks behaved correctly")
    if failures:
        print(f"  RESULT: {failures} problem(s)")
        return 1
    print("  RESULT: the engine measures what it claims to measure")
    return 0


if __name__ == "__main__":
    sys.exit(main())
