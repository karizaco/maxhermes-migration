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


# --------------------------------------------------------------------------
# THE CANONICAL CRON SEMANTICS
# --------------------------------------------------------------------------
# These helpers are the ONE place the fleet's idea of "when does this schedule
# fire" is written down. `auditor_metrics.py` imports them (it needs the same
# answer the detector needs), and the auditor's own procedure quotes their
# meaning. A SECOND copy of this logic is how the roster drifted in the first
# place: the detector compared only routine NAMES, so a schedule that said the
# wrong TIME looked identical to one that said the right time.
#
# A "slot" is one (minute, hour, weekday) triple - the three fields that decide
# when a routine actually fires. Two schedules are equivalent when their slot
# sets are equal. Expanding the day-of-week field is what lets a copy that
# splits a two-slot routine into two rows ("50 9 * * 1-5" and "50 15 * * 1-5")
# be compared against a ground truth that states it once ("50 9,15 * * 1-5").
#
# The day-of-month and month fields are NOT expanded: every schedule in this
# fleet uses "*" for both. A schedule that pins a date is left as an opaque
# token so it can never be silently compared as if it were a daily rule.

def parse_schedule(schedule):
    """'30 9,15 * * 1-5' -> the five cron fields, or None."""
    parts = (schedule or "").split()
    if len(parts) != 5:
        return None
    return parts


def _expand_field(field, lo, hi):
    """Expand one cron field into the set of values it covers."""
    field = field.strip()
    if field == "*":
        return set(range(lo, hi + 1))
    out = set()
    for chunk in field.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "/" in chunk:                      # */n and a-b/n
            base, _, step = chunk.partition("/")
            try:
                step = int(step)
            except ValueError:
                return None
            if step <= 0:
                return None
            if base == "*":
                out |= set(range(lo, hi + 1, step))
            elif "-" in base:
                a, _, b = base.partition("-")
                try:
                    a, b = int(a), int(b)
                except ValueError:
                    return None
                out |= set(range(a, b + 1, step))
            else:
                return None
        elif "-" in chunk:
            a, _, b = chunk.partition("-")
            if not (a.isdigit() and b.isdigit()):
                return None
            a, b = int(a), int(b)
            if b < a:
                return None
            out |= set(range(a, b + 1))
        elif chunk.isdigit():
            out.add(int(chunk))
        else:
            return None
    return {v for v in out if lo <= v <= hi}


def schedule_slots(schedule):
    """The set of (minute, hour, weekday) slots a cron schedule fires at.

    Weekday 0 is Sunday and 7 is also Sunday, so 7 is folded into 0 - a copy
    that says "0" and a copy that says "7" fire at the same time and must not
    be reported as drift.

    Returns None when the schedule cannot be expanded into slots (a pinned
    day-of-month or month, or an unparseable field). None is NOT "equal" and
    NOT "different": the caller compares the raw schedule text in that case,
    so an unusual schedule can never be reported as a false difference.
    """
    parts = parse_schedule(schedule)
    if not parts:
        return None
    minute_f, hour_f, dom_f, mon_f, dow_f = parts
    if dom_f.strip() != "*" or mon_f.strip() != "*":
        return None                            # not a recurring rule
    minutes = _expand_field(minute_f, 0, 59)
    hours = _expand_field(hour_f, 0, 23)
    dows = _expand_field(dow_f, 0, 7)
    if minutes is None or hours is None or dows is None:
        return None
    dows = {0 if d == 7 else d for d in dows}
    return frozenset((m, h, d) for m in minutes for h in hours for d in dows)


def schedules_equivalent(a, b):
    """Do two cron schedules fire at exactly the same times?

    Slot-set equality is the test, so a two-row copy of a two-slot routine
    matches a one-row ground truth. When either side cannot be expanded, the
    normalised text is compared instead - conservative, never a false positive.
    """
    sa, sb = schedule_slots(a), schedule_slots(b)
    if sa is None or sb is None:
        return " ".join((a or "").split()) == " ".join((b or "").split())
    return sa == sb


def slots_set_text(slots):
    """A human-readable summary of a slot set: '09:50 Mon-Fri; 15:50 Mon-Fri'."""
    dow_names = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")
    by_slot = {}
    for minute, hour, dow in slots:
        by_slot.setdefault((hour, minute), set()).add(dow)
    out = []
    for (hour, minute) in sorted(by_slot):
        dows = sorted(by_slot[(hour, minute)])
        if len(dows) == 7:
            runs = ["daily"]
        elif dows == [1, 2, 3, 4, 5]:
            runs = ["Mon-Fri"]
        elif dows == [0]:
            runs = ["Sun"]
        elif dows == [6]:
            runs = ["Sat"]
        else:
            runs = [dow_names[d] for d in dows]
        out.append("%02d:%02d %s" % (hour, minute, ", ".join(runs)))
    return "; ".join(out)


def slots_text(schedule):
    """A human-readable slot summary: '09:50 Mon-Fri; 15:50 Mon-Fri'."""
    slots = schedule_slots(schedule)
    if not slots:
        return " ".join((schedule or "").split()) or "(unparseable)"
    return slots_set_text(slots)


def cron_dow_matches(field, cron_dow):
    """Does a cron day-of-week field fire on this cron weekday (0=Sun..6=Sat)?"""
    dows = _expand_field(field, 0, 7)
    if dows is None:
        return False
    return cron_dow in {0 if d == 7 else d for d in dows}


def dow_matches(field, iso_dow):
    """Does a cron day-of-week field fire on this ISO weekday (1=Mon..7=Sun)?"""
    return cron_dow_matches(field, iso_dow % 7)


def fire_times(schedule):
    """The ET clock times a schedule fires -> [(hour, minute)]."""
    parts = parse_schedule(schedule)
    if not parts:
        return []
    minutes = _expand_field(parts[0], 0, 59)
    hours = _expand_field(parts[1], 0, 23)
    if minutes is None or hours is None:
        return []
    return [(h, m) for h in sorted(hours) for m in sorted(minutes)]


def schedule_compatible(copy_sched, gt_sched):
    """Is the COPY's schedule a COMPATIBLE view of the task's schedule?

    Two shapes are compatible:
      * the copy names ONE SLOT of a task that fires MORE THAN ONCE a day
        (#17's open slot is `50 9 * * 1-5` while the task itself is
        `50 9,15 * * 1-5`);
      * the copy names the task exactly.

    Everything else is a desync, and it is a MEANINGFUL one: a Mon-Fri task listed
    as Wednesday-only would make the audit call four days of fires `not_due`, and
    those missing artifacts would never be looked for. That is the same class of
    blind spot as an unmonitored routine, so it is reported, not tolerated.

    This is the ROW-level rule. The COPY-level rule is `schedule_sets_agree`,
    which also catches a copy that simply DROPS one of the task's slots.
    """
    t, g = parse_schedule(copy_sched), parse_schedule(gt_sched)
    if not t or not g:
        return copy_sched == gt_sched
    if t[0] != g[0] and t[0] != "*":
        return False                                  # the minute must match
    t_hours = _expand_field(t[1], 0, 23)
    g_hours = _expand_field(g[1], 0, 23)
    if t[1] != "*" and (t_hours is None or g_hours is None
                        or not t_hours <= g_hours):
        return False                                  # the hour must be one of the task's
    if t[4] != g[4]:
        if g_hours is None or len(g_hours) <= 1:
            return False                              # a single-fire task must match exactly
        for dow in range(0, 8):                      # a slot row may narrow the days
            if cron_dow_matches(t[4], dow) and not cron_dow_matches(g[4], dow):
                return False
    return True


def slots_union(schedules):
    """The union of the fire slots of several schedules.

    None when any of them cannot be expanded - the caller then falls back to the
    row-level rule, so an unusual schedule is never a false difference.
    """
    out = None
    for s in schedules:
        sl = schedule_slots(s)
        if sl is None:
            return None
        out = sl if out is None else (out | sl)
    return out


def schedule_sets_agree(schedules, gt_schedule):
    """Do the copy's rows, taken TOGETHER, fire exactly when the ground truth says?

    This is the COPY-level rule and it is stricter than the row-level one: a copy
    that states a two-slot task as two rows agrees with a ground truth that states
    it once ("50 9,15 * * 1-5"), but a copy that DROPS one of the slots does not -
    and a dropped slot means the routine is never checked for that slot at all.

    Returns (agrees, detail) where detail describes what the copy says, so the
    finding can name both sides.
    """
    union = slots_union(schedules)
    gsl = schedule_slots(gt_schedule)
    if union is None or gsl is None:
        # Cannot expand one side: fall back to the row-level rule per row.
        agrees = all(schedule_compatible(s, gt_schedule) for s in schedules)
        return agrees, "; ".join(s for s in schedules)
    return union == gsl, slots_set_text(union)


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
    cands = [
        explicit,
        os.path.join(repo, rel),
        os.path.join(here, os.path.basename(rel)),
    ]
    if os.path.abspath(here) == "/workspace":
        # The audit's own sandbox: the fetched copies sit next to the detector.
        # The fallback is NOT used from anywhere else - a /workspace on some other
        # machine is a DIFFERENT environment, and reading it would turn another
        # environment's copies into findings here (measured 2026-11-17: the
        # regression test picked up the audit's own fetched deploy_prompts.py and
        # reported four phantom drifts).
        cands.append(os.path.join("/workspace", os.path.basename(rel)))
    return cands


def _step4_rows(src):
    """[(routine name, schedule)] from the auditor procedure's STEP 4 roster table.

    The table is the auditor's own copy of the roster, so its Schedule column is
    compared against the ground truth as carefully as its Routine column is.
    """
    m = re.search(r"##\s*STEP 4\b(.*?)(?=\n##\s|\Z)", src, re.S)
    if not m:
        return []
    rows = []
    for line in m.group(1).splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        nm = cells[0].strip("` ")
        if not nm or nm == "Routine" or set(nm) <= set("- "):
            continue
        if not ID_RE.match(nm):
            continue
        rows.append((nm, cells[1].strip("` ").strip()))
    return rows


def copy_drift(ground_truth, repo=REPO, procedure=None,
               gen_roster_path=None, deploy_prompts_path=None):
    """Compare the ground truth against the other three copies of the roster.

    A copy that cannot be LOCATED is NOT a drift - the audit runs from a fetched-file
    sandbox with no repo checkout, so a missing copy is a missing input, not a
    disagreement. It is reported under `roster_copy_not_checked` instead, and it never
    raises the exit code: a check that cries wolf on every audit is worse than no
    check at all.

    A copy that DISAGREES is drift, in two ways:

      * the routine is MISSING from the copy (the original check), and
      * the routine is PRESENT but its SCHEDULE disagrees with the ground truth.

    The second one is what the 2026-11-15 audit missed: the STEP 4 roster table
    carried `0 9 * * 1-5` for #25 while the ground truth said `45 8 * * 1-5`, and a
    check that compared only routine NAMES could not see it. Schedules are compared
    as SLOT SETS, so a copy that splits a two-slot routine over two rows
    ("50 9 * * 1-5" + "50 15 * * 1-5") still matches a ground truth that states it
    once ("50 9,15 * * 1-5"), while a copy that DROPS one of the slots is drift -
    the routine would simply never be checked.
    """
    drift = []
    not_checked = []

    gt_sched = {}
    for n, spec in ground_truth.items():
        gt_sched[routine_id(n)] = (spec.get("schedule") or "").strip()

    display = {}          # routine id -> the name the auditor's roster table uses

    def display_name(name):
        rid = routine_id(name)
        if rid in display:
            return display[rid]
        return name[:-3] if name.endswith(".md") else name

    def note(copy, missing, why, path=None, gt_schedule=None, copy_schedule=None,
             routine=None):
        for name in sorted(missing):
            detail = " ".join(why.split())
            gap_path = path or copy
            pub = routine or display_name(name)
            entry = {
                "name": name,
                "routine": pub,
                "routine_id": routine_id(name),
                "copy": copy,
                "path": gap_path,
                "why": detail,
                "label": "roster_desync",
                "cause": "cron_update_failed",
                # The line is the auditor's own gap format, VERBATIM:
                #   gap: <routine> <label> <path> — cause=<token> age_h=<n> — <detail>
                # The label is LOWERCASE (the contract's spelling) and the path is the
                # FILE that disagrees - one whitespace-free token, so the line parses
                # under the checker's gap regex. An earlier version printed
                # `ROSTER_DESYNC` and a multi-word copy description, which the gate
                # rejects (C04: unknown label; D04: unparseable gap).
                "line": f"gap: {pub} roster_desync {gap_path} — "
                        f"cause=cron_update_failed age_h=0 — {detail}",
            }
            if gt_schedule is not None:
                entry["ground_truth_schedule"] = gt_schedule
            if copy_schedule is not None:
                entry["copy_schedule"] = copy_schedule
            drift.append(entry)

    # ---- (4) the roster/index generator's ARTIFACTS map --------------------
    # The map carries artifact paths, not schedules, so this copy is a PRESENCE
    # check only - there is nothing in it to disagree about a time.
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
                 "the generated README index and ROSTER.md cannot show its output path",
                 path="tools/gen_roster.py")
        except (OSError, ValueError, AttributeError) as exc:
            not_checked.append({
                "copy": "tools/gen_roster.py ARTIFACTS",
                "why": f"unreadable: {exc}",
            })

    # ---- (3) the deploy harness's task map ---------------------------------
    # This is the DEPLOYMENT-critical copy: it is what a cron_update is handed, so a
    # stale schedule here fires the routine at the wrong time. Nobody compared its
    # schedules before 2026-11-17.
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
            dep = {}
            for mm in re.finditer(r'"([^"]+\.md)"\s*:\s*\(\s*"[^"]*"\s*,\s*"([^"]*)"\s*\)',
                                  m.group(1)):
                dep[mm.group(1)] = mm.group(2).strip()
            missing = {n for n in ground_truth if n not in dep}
            note("tools/deploy_prompts.py", missing,
                 "the deploy harness cannot deploy or byte-verify it",
                 path="tools/deploy_prompts.py")
            for n in sorted(ground_truth):
                cp = dep.get(n)
                if cp is None:
                    cands = [v for k, v in dep.items() if routine_id(k) == routine_id(n)]
                    cp = cands[0] if len(cands) == 1 else None
                if cp is None:
                    continue
                gt = gt_sched[routine_id(n)]
                if schedules_equivalent(gt, cp):
                    continue
                note("tools/deploy_prompts.py", {n},
                     f"the deploy harness would fire it at {slots_text(cp)}, "
                     f"the ground truth says {slots_text(gt)}",
                     path="tools/deploy_prompts.py", gt_schedule=gt, copy_schedule=cp)
        except (OSError, ValueError, AttributeError) as exc:
            not_checked.append({
                "copy": "tools/deploy_prompts.py",
                "why": f"unreadable: {exc}",
            })

    # ---- (2) the auditor procedure's own STEP 4 roster table ----------------
    ap_path = _resolve(_copy_candidates("auditor_procedure", repo, procedure))
    if not ap_path:
        not_checked.append({
            "copy": "cloud-prompts/_shared/auditor-procedure.md STEP 4",
            "why": "the auditor procedure was not available in this sandbox",
        })
    else:
        try:
            src = open(ap_path, encoding="utf-8").read()
            rows = _step4_rows(src)
            ids = set()
            by_id = {}
            for nm, sched in rows:
                ids.add(routine_id(nm))
                by_id.setdefault(routine_id(nm), []).append((nm, sched))
                display.setdefault(routine_id(nm), nm)
            missing = {n for n in ground_truth if routine_id(n) not in ids}
            note("cloud-prompts/_shared/auditor-procedure.md STEP 4", missing,
                 "the auditor never checks its artifact",
                 path="cloud-prompts/_shared/auditor-procedure.md")
            # The table's schedules, compared per routine id over the UNION of that
            # id's rows. The union is the point: #17 fires twice and is written as
            # two rows, and a check that compared row-by-row would either miss the
            # dropped second slot or flag the legitimate first one.
            for rid, gt in sorted(gt_sched.items()):
                entries = by_id.get(rid)
                if not entries:
                    continue
                # ONE finding per routine, never one per row: the gap line is keyed
                # on (routine, label, path), so two lines for the same table would
                # be two gaps for one defect.
                problems = []
                named = entries[0][0]
                for nm, sched in entries:
                    if not schedule_compatible(sched, gt):
                        problems.append(f"the row for {nm} says {slots_text(sched)}")
                        named = nm
                agrees, cp_txt = schedule_sets_agree([s for _, s in entries], gt)
                if not agrees:
                    problems.append(f"the table fires at {cp_txt}, the ground truth says "
                                    f"{slots_text(gt)}")
                if not problems:
                    continue
                n = next((gn for gn in ground_truth if routine_id(gn) == rid), rid)
                note("cloud-prompts/_shared/auditor-procedure.md STEP 4", {n},
                     "; ".join(problems),
                     path="cloud-prompts/_shared/auditor-procedure.md",
                     gt_schedule=gt, copy_schedule=cp_txt, routine=named)
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
