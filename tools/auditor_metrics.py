#!/usr/bin/env python3
"""
auditor_metrics.py - cron #90's MEASUREMENT engine.

WHY
---
The auditor's job is to compare what SHOULD have run against what DID land. Almost
all of that comparison is arithmetic over the git history of the outputs repo:
which artifact exists, when it was first added, how stale the newest artifact of a
routine is, whether the file that landed is a real artifact or a degraded stub.

The procedure used to ask the agent to do that arithmetic by hand, in bash loops:
one `git ls-tree -r` PER ROUTINE in the staleness loop (27 full tree walks), one
`git log --diff-filter=A` per artifact for the latency (21 history walks), and one
`git cat-file -e` per expected path. Measured on the 2026-11-12 fire: the whole
audit took 245 s, and the redundant git work was ~9 s of it, with ~44 tool calls
and ~142k tokens of context for what is a deterministic computation.

This script does the deterministic part ONCE - one tree walk, one history walk -
and prints a measurement table. The agent still does the JUDGEMENT (is this gap a
MISSING, a skip by design, a late delivery?), because that needs evidence the
script cannot see (session status messages, skip markers, the platform's run
records). Judgement stays with the model; measurement moves to a script.

WHAT IT MEASURES (per roster row)
----------------------------------
  due            does this routine's own schedule fire on the audited weekday?
  present        is the expected artifact on origin/main right now?
  near_miss      did the routine publish a VARIANT path instead (the near-miss triage)?
  latency_min    minutes between the routine's scheduled fire and the commit that
                 FIRST added its artifact (the honest delivery measure)
  last_delivered newest artifact date this routine ever published, and its age
  stale          older than the routine's own tolerance (a routine that never fires)
  health         size, lines and degraded markers of the artifact that landed
  market_closed  the audited date is an NYSE closure (so a gap is probably a skip)

ROSTER SOURCES - NO NEW COPY
----------------------------
  schedule        tools/schedule-ground-truth.json   (the schedules of record)
  paths/tolerances tools/gen_roster.py ARTIFACTS/TOLERANCE/NOT_YET_FIRED/SLOTS
  names + table   the auditor procedure's own STEP 4 table (the human contract)
The script CROSS-CHECKS those three against each other and reports a
ROSTER_DESYNC for any disagreement, so the copies cannot drift silently.

USAGE
-----
    python3 tools/auditor_metrics.py --date 2026-11-11 --repo /workspace/.audit \
        [--procedure cloud-prompts/_shared/auditor-procedure.md] \
        [--ground-truth tools/schedule-ground-truth.json] \
        [--holidays cloud-prompts/_shared/nyse-holidays.txt] \
        [--prior /path/to/previous/status.json] [--json out.json] [--quiet]

EXIT CODES
----------
    0  measurements taken
    1  an input was missing or unreadable (nothing is guessed)
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except Exception:                                            # pragma: no cover
    ET = None

try:
    import gen_roster as GR
except Exception as exc:                                     # noqa: BLE001
    sys.stderr.write("auditor_metrics: cannot import gen_roster: %s\n" % exc)
    sys.exit(1)

DOW_NAMES = {0: "Sun", 1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat"}
ID_RE = re.compile(r"^([0-9]+[a-z]?)")
DEGRADED_MARKERS = (
    "fetch_failed", "PROCEDURE_FETCH_FAILED", "skill_fetch_failed",
    "prompt_blocks_fetch_failed",
)


# ---------------------------------------------------------------------------
# schedule helpers
# ---------------------------------------------------------------------------
def parse_schedule(schedule):
    """'30 9,15 * * 1-5' -> the five cron fields."""
    parts = (schedule or "").split()
    if len(parts) != 5:
        return None
    return parts


def cron_dow_matches(field, cron_dow):
    """Does a cron day-of-week field fire on this cron weekday (0=Sun..6=Sat)?"""
    if field == "*":
        return True
    for chunk in field.split(","):
        chunk = chunk.strip()
        if "-" in chunk:
            lo, hi = chunk.split("-", 1)
            if lo.isdigit() and hi.isdigit() and int(lo) <= cron_dow <= int(hi):
                return True
        elif chunk.isdigit() and int(chunk) == cron_dow:
            return True
    return False


def dow_matches(field, iso_dow):
    """Does a cron day-of-week field fire on this ISO weekday (1=Mon..7=Sun)?"""
    return cron_dow_matches(field, iso_dow % 7)


def fire_times(schedule):
    """The ET clock times a schedule fires -> [(hour, minute)]."""
    parts = parse_schedule(schedule)
    if not parts:
        return []
    minute_f, hour_f = parts[0], parts[1]
    hours = []
    if hour_f == "*":
        hours = [0]
    else:
        for h in hour_f.split(","):
            if "-" in h:
                lo, hi = h.split("-", 1)
                if lo.isdigit() and hi.isdigit():
                    hours.extend(range(int(lo), int(hi) + 1))
            elif h.isdigit():
                hours.append(int(h))
    minutes = []
    if minute_f == "*":
        minutes = [0]
    else:
        for m in minute_f.split(","):
            if "-" in m:
                lo, hi = m.split("-", 1)
                if lo.isdigit() and hi.isdigit():
                    minutes.extend(range(int(lo), int(hi) + 1))
            elif m.isdigit():
                minutes.append(int(m))
    return [(h, m) for h in hours for m in minutes]


def schedule_compatible(table_sched, gt_sched):
    """Is the TABLE's schedule a COMPATIBLE view of the task's schedule?

    Two shapes are compatible:
      * the table row names ONE SLOT of a task that fires MORE THAN ONCE a day
        (#17's open slot is `50 9 * * 1-5` while the task itself is `50 9,15 * * 1-5`);
      * the table row names the task exactly.

    Everything else is a desync, and it is a MEANINGFUL one: a Mon-Fri task listed as
    Wednesday-only would make the audit call four days of fires `not_due`, and those
    missing artifacts would never be looked for. That is the same class of blind spot as
    an unmonitored routine, so it is reported, not tolerated.
    """
    t, g = parse_schedule(table_sched), parse_schedule(gt_sched)
    if not t or not g:
        return table_sched == gt_sched
    if t[0] != g[0] and t[0] != "*":
        return False                                  # the minute must match
    t_hours = {h for h in t[1].split(",") if h.isdigit()}
    g_hours = {h for h in g[1].split(",") if h.isdigit()}
    if t[1] != "*" and not t_hours <= g_hours:
        return False                                  # the hour must be one of the task's
    if t[4] != g[4]:
        if len(g_hours) <= 1:
            return False                              # a single-fire task must match exactly
        for dow in range(0, 8):                      # a slot row may narrow the days
            if cron_dow_matches(t[4], dow) and not cron_dow_matches(g[4], dow):
                return False
    return True


def iso_week_of(date_str):
    """'2026-11-08' -> '2026-W45' (the ISO week that Sunday ends)."""
    d = datetime.strptime(date_str, "%Y-%m-%d")
    y, w, _ = d.isocalendar()
    return "%04d-W%02d" % (y, w)


def scheduled_epoch(date_str, hour, minute):
    d = datetime.strptime(date_str, "%Y-%m-%d").replace(hour=hour, minute=minute)
    return int(d.replace(tzinfo=ET).timestamp())


# ---------------------------------------------------------------------------
# git access - ONE tree walk, ONE history walk
# ---------------------------------------------------------------------------
def git(repo, *args):
    out = subprocess.run(["git", "-C", repo] + list(args),
                         capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError("git %s failed: %s" % (" ".join(args), out.stderr.strip()))
    return out.stdout


def tree_snapshot(repo):
    """One walk: every path on origin/main with its size in bytes."""
    raw = git(repo, "ls-tree", "-r", "-l", "origin/main")
    files = {}
    for line in raw.splitlines():
        if "\t" not in line:
            continue
        meta, path = line.split("\t", 1)
        parts = meta.split()
        if len(parts) < 4:
            continue
        try:
            size = int(parts[3])
        except ValueError:
            size = -1
        files[path] = size
    return files


def add_times(repo):
    """One walk: the timestamp of the FIRST commit that added each path.

    `git log --diff-filter=A --name-only` over the whole history; the earliest add per
    path is that path's FIRST delivery (a later fix-forward does not change when the
    routine first published).
    """
    raw = git(repo, "log", "--diff-filter=A", "--name-only",
              "--format=@@%ct", "origin/main")
    first = {}
    ts = None
    for line in raw.splitlines():
        if line.startswith("@@"):
            try:
                ts = int(line[2:])
            except ValueError:
                ts = None
            continue
        path = line.strip()
        if not path or ts is None:
            continue
        if path not in first or ts < first[path]:
            first[path] = ts
    return first


def blob_text(repo, path, limit=None):
    """The content of a blob on origin/main (None when it is not there)."""
    try:
        out = subprocess.run(["git", "-C", repo, "show", "origin/main:" + path],
                             capture_output=True, text=True, timeout=60)
    except Exception:                                         # noqa: BLE001
        return None
    if out.returncode != 0:
        return None
    return out.stdout if limit is None else out.stdout[:limit]


# ---------------------------------------------------------------------------
# the procedure's own STEP 4 roster table
# ---------------------------------------------------------------------------
def procedure_rows(procedure_path):
    """The auditor's roster rows: [(name, schedule, path_cell, fires_on)]."""
    with open(procedure_path, encoding="utf-8") as fh:
        src = fh.read()
    m = re.search(r"##\s*STEP 4\b(.*?)(?=\n###\s*4a|\n##\s|\Z)", src, re.S)
    if not m:
        raise ValueError("no STEP 4 section in %s" % procedure_path)
    rows = []
    for line in m.group(1).splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 4:
            continue
        name = cells[0].strip("` ")
        if not name or name == "Routine" or set(name) <= set("- "):
            continue
        rows.append((name, cells[1].strip("` "), cells[2], cells[3].strip()))
    return rows


def routine_id(name):
    m = ID_RE.match(name)
    return m.group(1) if m else name


def artifacts_for(name):
    """The machine-readable path template(s) for a routine id, from gen_roster.

    Returns (templates, suffixes) for the routine whose ARTIFACTS key matches the
    leading id of `name` (the same normalization the roster check uses).
    """
    want = None
    for key in GR.ARTIFACTS:
        if routine_id(key) == routine_id(name):
            want = key
            break
    if want is None:
        return [], []
    spec = GR.ARTIFACTS[want]
    return [spec[0]], (spec[2] if isinstance(spec[2], tuple) else (spec[2],))


def slot_spec(name):
    """For a multi-fire routine, the (path template, regex) of one slot."""
    for _routine, slots in GR.SLOTS.items():
        for _hour, (label, path, rx) in slots.items():
            if label == name:
                return path, rx
    return None, None


def slot_hour_of(name):
    """The hour a SLOT fires at (#17: 09:50 open, 15:50 preclose)."""
    for _routine, slots in GR.SLOTS.items():
        for hour, (label, _path, _rx) in slots.items():
            if label == name:
                return int(hour)
    return None


def tolerance_of(name):
    """A routine's own staleness tolerance in days (gen_roster's map)."""
    if name in GR.TOLERANCE:
        return GR.TOLERANCE[name]
    for key, val in GR.TOLERANCE.items():
        if routine_id(key) == routine_id(name):
            return val
    return None


def first_fire_of(name):
    """A routine's first fire date, or None."""
    if name in GR.NOT_YET_FIRED:
        return GR.NOT_YET_FIRED[name]
    for key, val in GR.NOT_YET_FIRED.items():
        if routine_id(key) == routine_id(name):
            return val
    return None


def last_delivered(files, suffix_set, name_re=None):
    """Newest date among the files that belong to THIS routine (not a sibling's)."""
    best = None
    for path in files:
        base = path.rsplit("/", 1)[-1]
        if name_re:
            if not re.match(name_re, base):
                continue
        elif not any(base.endswith(s) for s in suffix_set):
            continue
        for d in GR.DATE_RE.findall(path):
            if best is None or d > best:
                best = d
    return best


# ---------------------------------------------------------------------------
# the measurement itself
# ---------------------------------------------------------------------------
def measure(date_str, repo, procedure, ground_truth_path, holidays_path, prior=None):
    with open(ground_truth_path, encoding="utf-8") as fh:
        gt = json.load(fh)
    gt_by_id = {}
    for key, spec in (gt.get("routines") or {}).items():
        gt_by_id[routine_id(key)] = (key, spec)

    holidays = set()
    if holidays_path and os.path.exists(holidays_path):
        with open(holidays_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#"):
                    holidays.add(line)

    audit_date = datetime.strptime(date_str, "%Y-%m-%d")
    iso_dow = audit_date.isoweekday()                    # 1=Mon..7=Sun

    files = tree_snapshot(repo)
    adds = add_times(repo)

    prior_routines, prior_gaps = {}, []
    if prior and os.path.exists(prior):
        try:
            with open(prior, encoding="utf-8") as fh:
                pd = json.load(fh)
            prior_routines = pd.get("routines") or {}
            prior_gaps = pd.get("gaps") or []
        except Exception:                                 # noqa: BLE001
            prior_routines, prior_gaps = {}, []

    rows = []
    for name, table_sched, path_cell, fires_on in procedure_rows(procedure):
        rid = routine_id(name)
        row = {
            "routine": name,
            "id": rid,
            "table_schedule": table_sched,
            "fires_on": fires_on,
            "self_check": ("no artifact" in path_cell.lower()),
            "notes": [],
        }

        gt_entry = gt_by_id.get(rid)
        gt_sched = gt_entry[1].get("schedule") if gt_entry else None
        row["ground_truth_schedule"] = gt_sched
        if (gt_sched and table_sched
                and not schedule_compatible(table_sched, gt_sched)):
            row["notes"].append(
                "ROSTER_DESYNC: the table says %s, the ground truth says %s"
                % (table_sched, gt_sched))

        # --- expected paths -------------------------------------------------
        templates, suffixes = artifacts_for(name)
        slot_path, slot_rx = slot_spec(name)
        slot_hour = slot_hour_of(name)
        expected = None
        if slot_path:
            expected = slot_path.replace("{date}", date_str)
            row["slot_regex"] = slot_rx
        elif templates:
            tpl = templates[0]
            if "YYYY-Wnn" in tpl:
                expected = "mcp-health/%s.md" % iso_week_of(date_str)
            else:
                expected = tpl.replace("{date}", date_str).rstrip("/")
        row["expected_path"] = expected
        row["alternates"] = sorted(
            p for p in files
            if suffixes and date_str in p
            and p.rsplit("/", 1)[-1].endswith(tuple(suffixes))
        )[:12]

        # --- due-ness -------------------------------------------------------
        if gt_sched and parse_schedule(gt_sched):
            sched = parse_schedule(gt_sched)
            fires_today = dow_matches(sched[4], iso_dow)
            times = fire_times(gt_sched)
            row["scheduled_times"] = ["%02d:%02d" % (h, m) for h, m in times]
            first_fire = first_fire_of(name)
            row["first_fire"] = first_fire
            if row["self_check"]:
                row["state_hint"] = "self_check"
            elif not fires_today:
                row["state_hint"] = "not_due"
            elif first_fire and date_str < first_fire:
                row["state_hint"] = "not_yet_fired"
            else:
                row["state_hint"] = "due"
        else:
            row["state_hint"] = "unknown"

        row["market_closed"] = date_str in holidays

        # --- presence -------------------------------------------------------
        is_dir = bool(expected) and any(p.startswith(expected + "/") for p in files)
        present = bool(expected) and (expected in files or is_dir)
        row["present"] = present
        row["is_directory"] = is_dir
        if is_dir:
            row["files_under"] = sorted(p for p in files
                                        if p.startswith(expected + "/"))[:12]
            row["size_bytes"] = sum(files.get(p, 0) for p in files
                                    if p.startswith(expected + "/"))
        else:
            row["size_bytes"] = files.get(expected)

        if not present:
            near = []
            if expected:
                base_dir = expected.rsplit("/", 1)[0]
                stem = expected.rsplit("/", 1)[-1].rsplit(".", 1)[0]
                # ONLY the same artifact under another name counts: `daily-sweep.csv` when
                # `daily-sweep.md` is missing is a near-miss; a sibling routine's file in
                # the same shared directory (daily-screens/ holds six routines) is NOT.
                near = sorted(p for p in files
                              if p.startswith(base_dir + "/") and date_str in p
                              and p != expected
                              and p.rsplit("/", 1)[-1].startswith(stem))
            row["near_miss"] = near[:6]

        # --- latency --------------------------------------------------------
        sched_epoch = None
        times = row.get("scheduled_times") or []
        if slot_hour is not None and times:
            times = ["%02d:%s" % (slot_hour, t.split(":")[1]) for t in times]
        if times and row["state_hint"] == "due":
            hh, mm = times[0].split(":")
            sched_epoch = scheduled_epoch(date_str, int(hh), int(mm))
            ts = None
            if expected and expected in adds:
                ts = adds[expected]
            elif expected and is_dir:
                under = [adds[p] for p in files
                         if p.startswith(expected + "/") and p in adds]
                ts = min(under) if under else None
            if ts is not None:
                row["delivery_latency_min"] = round((ts - sched_epoch) / 60.0, 1)
                row["added_epoch"] = ts
                row["added_et"] = datetime.fromtimestamp(ts, ET).strftime("%H:%M:%S")

        # --- staleness ------------------------------------------------------
        name_re = slot_rx
        last = None
        if suffixes:
            last = last_delivered(files, suffixes, name_re)
        if last is None and name_re:
            last = last_delivered(files, (), name_re)
        row["last_delivered"] = last
        if last:
            age = (audit_date - datetime.strptime(last, "%Y-%m-%d")).days
            row["age_days"] = age
            tol = tolerance_of(name)
            row["tolerance_days"] = tol
            if tol is not None and age > tol:
                row["stale"] = True
                row["notes"].append("STALE: last delivered %s (%d days, tolerance %d)"
                                    % (last, age, tol))

        # --- health ---------------------------------------------------------
        if present and expected and not is_dir:
            text = blob_text(repo, expected, limit=200000)
            if text is None:
                row["health"] = "unreadable"
            else:
                hits = [m for m in DEGRADED_MARKERS if m in text]
                row["health"] = "degraded" if hits else "ok"
                if hits:
                    row["degraded_markers"] = hits
                row["lines"] = text.count("\n") + 1
        elif present:
            row["health"] = "ok"

        # --- the previous audit (streaks, chronic lateness) ------------------
        pr = prior_routines.get(name) or {}
        row["prior_state"] = pr.get("state")
        row["prior_streak"] = pr.get("streak", 0)
        row["prior_latency_min"] = pr.get("delivery_latency_min")
        rows.append(row)

    return {
        "audit_date_et": date_str,
        "audit_date_dow": DOW_NAMES[iso_dow],
        "market_closed": date_str in holidays,
        "origin_main_sha": git(repo, "rev-parse", "--short", "origin/main").strip(),
        "prior_gaps": prior_gaps,
        "rows": rows,
    }


def render(report):
    out = []
    out.append("audit date      : %s (%s)%s" % (
        report["audit_date_et"], report["audit_date_dow"],
        "  MARKET CLOSED" if report["market_closed"] else ""))
    out.append("origin/main     : %s" % report["origin_main_sha"])
    out.append("")
    hdr = ("%-38s %-13s %-6s %-8s %-6s %s" % (
        "routine", "due?", "present", "lat_min", "stale", "notes"))
    out.append(hdr)
    out.append("-" * len(hdr))
    for r in report["rows"]:
        out.append("%-38s %-13s %-6s %-8s %-6s %s" % (
            r["routine"][:38],
            r.get("state_hint") or "?",
            "yes" if r.get("present") else "no",
            ("%.1f" % r["delivery_latency_min"])
            if r.get("delivery_latency_min") is not None else "-",
            "YES" if r.get("stale") else "-",
            "; ".join(r.get("notes") or [])[:70]))
        if r.get("near_miss"):
            out.append("    near-miss: %s" % ", ".join(r["near_miss"][:3]))
        if r.get("health") and r.get("health") != "ok":
            out.append("    health: %s %s" % (r["health"], r.get("degraded_markers", "")))
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", required=True, help="the audited date, YYYY-MM-DD")
    ap.add_argument("--repo", required=True, help="the outputs-repo checkout (read-only)")
    ap.add_argument("--procedure", default=os.path.join(
        REPO, "cloud-prompts", "_shared", "auditor-procedure.md"))
    ap.add_argument("--ground-truth", default=os.path.join(HERE, "schedule-ground-truth.json"))
    ap.add_argument("--holidays", default=os.path.join(
        REPO, "cloud-prompts", "_shared", "nyse-holidays.txt"))
    ap.add_argument("--prior", help="the previous status.json (for the streak carry-forward)")
    ap.add_argument("--json", help="write the measurements here as JSON")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    try:
        report = measure(args.date, args.repo, args.procedure, args.ground_truth,
                         args.holidays, args.prior)
    except Exception as exc:                                # noqa: BLE001
        sys.stderr.write("auditor_metrics: %s\n" % exc)
        return 1

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=1)
    if not args.quiet:
        print(render(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
