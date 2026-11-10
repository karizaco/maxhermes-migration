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
     ROSTER       the live roster and the ground truth disagree -- REPORT
     SPEC-DRIFT   the spec the routine would fetch != the repo's spec -- REPORT
     SPEC-UNREACHABLE  the spec could not be fetched at all -- REPORT
     SPEC-SECTION-MISSING  the spec lost the section it is supposed to produce

RECENCY, PER ROUTINE (not a flat date filter)
----------------------------------------------
A reused conversation is only a LIVE finding when the reuse involves a run inside the
routine's OWN recent window. The window is measured in FIRES of that routine, derived
from its schedule, never in flat days:

  daily   (`5 4 * * *`)        1 fire/day    -> window  3 fires (~3 days)
  weekday (`30 6 * * 1-5`)     5 fires/week -> window  7 fires (~10 days)
  weekly  (`0 2 * * 0`)       1 fire/week  -> window  3 fires (~21 days)

A flat "within N days" cutoff would drop one of a weekly routine's two fires and mask a
genuinely live binding, and would fire on a routine whose own cadence is slower. The
age of the OLDER run decides the LABEL only (LIVE vs HISTORICAL) -- it never decides
whether the finding exists. Historical reuse is kept as evidence and reported.

ROSTER COMPLETENESS (added 2026-11-06)
---------------------------------------
The ground truth used to hold 25 routines while the live scheduler ran 26. A task whose
name is not in the ground truth is appended to `unknown` and skipped, so it was never
schedule-checked, never prompt-drift-checked and never conversation-checked -- and every
count in the report ("25 routines match the ground truth") was true while silently
omitting a routine that fires every weekday. The number of live routines and the number
of ground-truth entries are now compared explicitly and printed as
`roster: <n> live / <m> expected`.

SKILL-SPEC DRIFT (added 2026-11-06)
-----------------------------------
Every routine fetches its PROCEDURE from this repo at RUN time, so a deployed prompt can
be byte-identical to the repo while the behaviour comes from a spec that differs from the
repo -- the exact failure that shipped cron #15's hardcoded UTC-4 offset and cron #09's
LIMIT caps. A prompt hash cannot see that. For every routine the spec URL its DEPLOYED
prompt names is fetched and compared, byte for byte, with the repo's file; and the spec
must still contain the section the routine is supposed to produce.
"""
import argparse, base64, glob, json, os, re, subprocess, sys, urllib.parse
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


def load_spec_contracts(path=GROUND_TRUTH_PATH):
    """Load {cron_name: {spec_path, bundle, marker}} from the ground-truth file.

    The contracts live in the SAME file as the ground truth on purpose: cron #91
    already fetches that one file at run time, so the contracts need no second fetch
    and no prompt change to take effect.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return {}
    return (doc.get("spec_contracts") or {}).get("routines") or {}


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


def parse_runs_file(path, now_ms=None):
    """Parse the agent-written run table: one run per line.

    Format (all three values copied verbatim from `cron_read view=runs`):
        <task_id> <session_id> <scheduled_at_ms>

    A line whose session_id or timestamp is not a plausible integer, or whose
    timestamp is IMPOSSIBLE (in the future, or before the platform existed), is
    REJECTED with a warning -- a mis-transcribed digit must never turn into a false
    "reuse" finding.

    WHAT IS *NOT* DONE HERE
    -----------------------
    An old run is NOT rejected. Age never decides whether a reuse finding exists; it
    only decides the LABEL (LIVE vs HISTORICAL), and that decision is made per routine
    in `classify_reuse`, from the routine's own schedule. A flat "within N days"
    filter here would drop one of a weekly routine's two fires and mask a genuinely
    live binding.
    """
    runs_by_task, rejected = {}, 0
    now_ms = now_ms if now_ms is not None else int(datetime.now(_et_tz()).timestamp() * 1000)
    # An IMPOSSIBLE timestamp is a transcription error, not an old run. The floor is
    # the platform's own epoch, not a recency window.
    floor_ms = int(datetime(2020, 1, 1, tzinfo=_et_tz()).timestamp() * 1000)
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
            ts = int(sched)
            if ts < floor_ms or ts > now_ms + 36 * 3600 * 1000:
                rejected += 1
                continue
            runs_by_task.setdefault(task_id, []).append({
                "task_id": task_id,
                "session_id": session_id,
                "scheduled_at_ms": ts,
                "run_id": None,
            })
    return runs_by_task, rejected


# ---------------------------------------------------------------------------
# THE RECENCY WINDOW -- derived from each routine's OWN schedule, measured in
# FIRES of that routine. Never a flat "within N days" filter.
# ---------------------------------------------------------------------------

def _expand_cron_field(field, lo, hi):
    """Expand one cron field ("*", "1-5", "9,15", "*/15") into a set of ints."""
    vals = set()
    for part in (field or "").split(","):
        part = part.strip()
        if not part:
            continue
        step = 1
        if "/" in part:
            part, _, st = part.partition("/")
            part = part.strip()
            try:
                step = int(st)
            except ValueError:
                continue
        if part in ("*", ""):
            a, b = lo, hi
        elif "-" in part:
            a_s, _, b_s = part.partition("-")
            try:
                a, b = int(a_s), int(b_s)
            except ValueError:
                continue
        else:
            try:
                a = b = int(part)
            except ValueError:
                continue
        if step > 1:
            vals.update(range(a, b + 1, step))
        else:
            vals.update(range(a, b + 1))
    return vals


def parse_cron(schedule):
    """Parse a five-field cron expression into the fields this checker needs."""
    parts = (schedule or "").strip().split()
    if len(parts) != 5:
        return None
    minute, hour, dom, month, dow = parts
    spec = {
        "minutes": sorted(_expand_cron_field(minute, 0, 59)),
        "hours": sorted(_expand_cron_field(hour, 0, 23)),
        "doms": sorted(_expand_cron_field(dom, 1, 31)),
        "months": sorted(_expand_cron_field(month, 1, 12)),
        "dows": sorted(_expand_cron_field(dow, 0, 7)),
        "raw": schedule.strip(),
    }
    if not spec["minutes"] or not spec["hours"]:
        return None
    if 7 in spec["dows"]:                       # cron dow 7 == Sunday
        spec["dows"].remove(7)
        spec["dows"].append(0)
        spec["dows"].sort()
    return spec


def _day_matches(spec, dt):
    """Standard cron day rule: dom and dow are OR-ed when both are restricted."""
    if dt.month not in spec["months"]:
        return False
    dow = (dt.weekday() + 1) % 7              # python Mon=0 -> cron Sun=0
    dom_star = spec["doms"] == list(range(1, 32))
    dow_star = spec["dows"] == list(range(0, 7))
    dom_ok = dt.day in spec["doms"]
    dow_ok = dow in spec["dows"]
    if dom_star and dow_star:
        return True
    if dom_star:
        return dow_ok
    if dow_star:
        return dom_ok
    return dom_ok or dow_ok


def cron_fires_between(spec, t0_ms, t1_ms, tz=None):
    """Count the fire instants of `spec` in the half-open interval (t0_ms, t1_ms]."""
    if not spec or t1_ms <= t0_ms:
        return 0
    tz = tz or _et_tz()
    start = datetime.fromtimestamp(t0_ms / 1000, tz)
    end = datetime.fromtimestamp(t1_ms / 1000, tz)
    day = start.date() - timedelta(days=1)
    last = end.date() + timedelta(days=1)
    if (last - day).days > 800:                # a routine idle for years
        day = last - timedelta(days=800)
    n = 0
    while day <= last:
        if _day_matches(spec, datetime(day.year, day.month, day.day, tzinfo=tz)):
            for h in spec["hours"]:
                for mi in spec["minutes"]:
                    fire = datetime(day.year, day.month, day.day, h, mi, tzinfo=tz)
                    ms = int(fire.timestamp() * 1000)
                    if t0_ms < ms <= t1_ms:
                        n += 1
        day += timedelta(days=1)
    return n


def routine_window(spec):
    """Return (cycle_days, window_fires) for a routine's own schedule.

    The window is measured in FIRES of that routine. A weekly routine gets a LONGER
    window than a daily one, so that its two fires are never compared against a
    cutoff that would drop one of them.
    """
    dows = spec["dows"]
    per_day = len(spec["hours"]) * len(spec["minutes"])
    if len(dows) >= 7:                         # every day
        cycle_days, fires = 1, per_day
    elif len(dows) == 1:                       # one day a week
        cycle_days, fires = 7, per_day
    else:                                      # a set of weekdays
        cycle_days, fires = 7, per_day * len(dows)
    return cycle_days, fires + 2               # + two fires of slack


def classify_reuse(spec, group_runs, now_ms, tz=None):
    """Classify one reused-conversation group as LIVE or HISTORICAL.

    The finding EXISTS whenever a session was used by more than one run. Its age only
    decides the label: LIVE when the reuse involves a run inside the routine's own
    recent window, HISTORICAL when every run of the group is older than that.
    """
    if not spec:
        return {"classification": "HISTORICAL", "window_fires": None, "fires_since": None,
                "cycle_days": None, "reason": "no ground-truth schedule for this routine"}
    cycle_days, window = routine_window(spec)
    ages = []
    for r in group_runs:
        ts = r.get("scheduled_at_ms")
        if ts:
            ages.append(cron_fires_between(spec, ts, now_ms, tz))
    if not ages:
        return {"classification": "HISTORICAL", "window_fires": window, "fires_since": None,
                "cycle_days": cycle_days, "reason": "no timestamps in the run table"}
    since = min(ages)                          # the fewest fires since ANY run of the group
    return {"classification": "LIVE" if since + 1 <= window else "HISTORICAL",
            "window_fires": window, "fires_since": since, "cycle_days": cycle_days,
            "reason": None}


# ---------------------------------------------------------------------------
# ROSTER COMPLETENESS -- the check that would have caught a live routine that
# was missing from the ground truth (and therefore never checked at all).
# ---------------------------------------------------------------------------

def check_roster(tasks, EXPECTED):
    """Compare the LIVE roster with the ground truth, by count and by name."""
    live = set()
    for t in tasks:
        name = urllib.parse.unquote(t.get("cron_name", ""))
        if name.startswith("@") or not name.endswith(".md"):
            continue                             # self-reminders and one-offs are not fleet routines
        live.add(name)
    expected = set(EXPECTED)
    return {
        "live": len(live),
        "expected": len(expected),
        "match": live == expected,
        "in_live_not_expected": sorted(live - expected),
        "in_expected_not_live": sorted(expected - live),
    }


# ---------------------------------------------------------------------------
# SKILL-SPEC DRIFT -- the check a prompt hash can never do.
# ---------------------------------------------------------------------------

REPO_SLUG = "karizaco/maxhermes-migration"


def extract_repo_paths(prompt):
    """Every repo-relative file a prompt names for a run-time fetch."""
    paths = []
    pats = [
        r"contents/([A-Za-z0-9_\-./]+)\?ref=main",
        r"raw\.githubusercontent\.com/karizaco/maxhermes-migration/main/([A-Za-z0-9_\-./]+)",
        r"cdn\.jsdelivr\.net/gh/karizaco/maxhermes-migration@main/([A-Za-z0-9_\-./]+)",
    ]
    for pat in pats:
        for m in re.finditer(pat, prompt or ""):
            p = m.group(1).strip().strip("\"'`,;")
            if p and p not in paths:
                paths.append(p)
    return paths


def pick_primary_spec(paths, repo_dir=None):
    """The procedure spec a routine fetches at run time, from the paths it names."""
    def exists(p):
        return bool(repo_dir) and os.path.isfile(os.path.join(repo_dir, p))

    known = [p for p in paths if exists(p)]
    for p in known:                                     # 1. the skill spec
        if p.startswith("cloud-prompts/skills/") and p.endswith("/SKILL.md"):
            return p
    for p in known:                                     # 2. a shared procedure document
        if (p.startswith("cloud-prompts/_shared/") and p.endswith(".md")
                and not p.endswith("PROMPT-BLOCKS.md")):
            return p
    for p in known:                                     # 3. a tool the prompt runs
        if p.startswith("tools/"):
            return p
    for p in known:                                     # 4. any shared file
        if p.startswith("cloud-prompts/_shared/"):
            return p
    return None


def spec_urls(path):
    """The ladder a routine uses to fetch a run-time file, most authoritative first."""
    return [
        f"https://api.github.com/repos/{REPO_SLUG}/contents/{path}?ref=main",
        f"https://raw.githubusercontent.com/{REPO_SLUG}/main/{path}",
        f"https://cdn.jsdelivr.net/gh/{REPO_SLUG}@main/{path}",
    ]


def fetch_spec_bytes(path, timeout=30):
    """Fetch a run-time spec the way a routine would. Returns (bytes, url, error)."""
    import urllib.request
    token = os.environ.get("GITHUB_TOKEN", "")
    headers = {"User-Agent": "schedule-drift-guard"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    last_err = None
    for url in spec_urls(path):
        try:
            req = urllib.request.Request(url, headers=headers)
            if "api.github.com" in url:
                req.add_header("Accept", "application/vnd.github.raw")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read()
            if body and b'"message"' not in body[:200]:
                return body, url, None
            last_err = f"{url} -> not a file (API error body)"
        except Exception as exc:                        # noqa: BLE001
            last_err = f"{url} -> {type(exc).__name__}: {exc}"
    return None, None, last_err or "no source reachable"


def find_repo_dir(explicit=None):
    """Locate the repo clone the spec comparison needs."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for cand in (explicit, "/workspace/guard/mig", "/workspace/mig", here,
                 "/workspace/repo"):
        if cand and os.path.isdir(os.path.join(cand, "cloud-prompts")):
            return cand
    return None


def clone_repo(dest="/workspace/guard/mig"):
    """Clone the repo if it is not on disk. The spec check needs a repo-side copy
    that came over a DIFFERENT transport than the live fetch, or the comparison
    would compare the contents API with itself.

    The token is NEVER put in the remote URL: `git clone` persists the URL into
    `.git/config`, so an embedded token would leave the secret on disk. Use the
    Basic extraheader instead (Bearer is rejected by git-over-HTTPS).
    """
    if os.path.isdir(os.path.join(dest, "cloud-prompts")):
        return dest
    try:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
    except OSError:
        pass
    cmd = ["git", "clone", "-q", "--depth", "1",
           f"https://github.com/{REPO_SLUG}.git", dest]
    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        b64 = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        cmd = ["git", "-c", f"http.extraheader=Authorization: Basic {b64}"] + cmd
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if r.returncode == 0 and os.path.isdir(os.path.join(dest, "cloud-prompts")):
            return dest
    except Exception:                                 # noqa: BLE001
        pass
    return None


def bundle_contains(repo_dir, bundle, marker):
    """Is the marker still present somewhere in the routine's spec bundle?"""
    if not repo_dir or not bundle or not marker:
        return None                                   # unknown -- not a finding
    root = os.path.join(repo_dir, bundle)
    if not os.path.isdir(root):
        return False
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            fp = os.path.join(dirpath, fn)
            try:
                with open(fp, encoding="utf-8", errors="replace") as fh:
                    if marker in fh.read():
                        return True
            except OSError:
                continue
    return False


def check_spec_drift(tasks, EXPECTED, contracts, repo_dir=None, timeout=30,
                     fetcher=None):
    """Compare the spec every routine would fetch with the repo's copy.

    For each routine: the DEPLOYED prompt names the spec URL -- that is the file the
    routine will fetch at run time. Fetch it, hash it, and compare with the repo's
    file. Then confirm the spec still contains the section the routine is supposed
    to produce.
    """
    import hashlib
    fetcher = fetcher or fetch_spec_bytes
    findings, checked = [], []
    for t in tasks:
        name = urllib.parse.unquote(t.get("cron_name", ""))
        if name.startswith("@") or not name.endswith(".md"):
            continue
        prompt = t.get("prompt") or ""
        paths = extract_repo_paths(prompt)
        spec_path = pick_primary_spec(paths, repo_dir)
        contract = contracts.get(name) or {}
        if not spec_path:
            findings.append({"kind": "SPEC-UNREACHABLE", "cron_name": name,
                             "task_id": t.get("task_id"),
                             "reason": "the deployed prompt names no run-time spec"})
            continue
        repo_file = os.path.join(repo_dir, spec_path) if repo_dir else None
        if repo_dir and not os.path.isfile(repo_file):
            findings.append({"kind": "SPEC-UNREACHABLE", "cron_name": name,
                             "task_id": t.get("task_id"), "path": spec_path,
                             "reason": f"{spec_path} is not in the repo"})
            continue
        body, url, err = fetcher(spec_path, timeout)
        if body is None:
            findings.append({"kind": "SPEC-UNREACHABLE", "cron_name": name,
                             "task_id": t.get("task_id"), "path": spec_path,
                             "reason": err})
            continue
        live_hash = hashlib.sha256(body).hexdigest()
        repo_hash = hashlib.sha256(open(repo_file, "rb").read()).hexdigest() if repo_file else None
        entry = {"kind": "SPEC-DRIFT" if repo_hash != live_hash else "SPEC-OK",
                 "cron_name": name, "task_id": t.get("task_id"), "path": spec_path,
                 "repo_hash": repo_hash, "live_hash": live_hash, "url": url}
        checked.append(entry)
        if repo_hash != live_hash:
            findings.append(entry)
        # the prompt must still point at the spec the contract expects
        want = contract.get("spec_path")
        if want and want != spec_path:
            findings.append({"kind": "SPEC-PATH-MISMATCH", "cron_name": name,
                             "task_id": t.get("task_id"), "path": spec_path,
                             "reason": f"prompt names {spec_path}, contract expects {want}"})
        # the spec must still CONTAIN the section it is supposed to produce
        marker = contract.get("marker")
        if marker:
            found = bundle_contains(repo_dir, contract.get("bundle"), marker)
            if found is False:
                findings.append({"kind": "SPEC-SECTION-MISSING", "cron_name": name,
                                 "task_id": t.get("task_id"), "path": spec_path,
                                 "reason": f"{marker!r} is gone from "
                                           f"{contract.get('bundle')}"})
    return findings, checked


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


def check_conversation_reuse(tasks, runs_by_task, EXPECTED=None, now_ms=None, tz=None):
    """L2: two runs of one task sharing a session_id == the conversation was reused.

    Every reuse is reported. Whether it is LIVE or HISTORICAL is decided per routine,
    from that routine's own schedule (see `classify_reuse`) -- never by a flat date
    filter, and never by the age of the older run alone.
    """
    EXPECTED = EXPECTED or {}
    if now_ms is None:
        now_ms = int(datetime.now(tz or _et_tz()).timestamp() * 1000)
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
        # The window comes from the GROUND TRUTH's schedule. The live schedule is the
        # thing that gets corrupted (the GUI collapses `1-5` to `1`), so deriving a
        # window from it would silently narrow the window of every weekday routine.
        schedule = (EXPECTED.get(name) or {}).get("schedule") or ""
        spec = parse_cron(schedule)
        for sid in distinct:
            same = [r for r in runs if r.get("session_id") == sid]
            if len(same) > 1:
                cls = classify_reuse(spec, same, now_ms, tz)
                findings.append({
                    "task_id": t.get("task_id"),
                    "cron_name": name,
                    "session_id": sid,
                    "runs": len(runs),
                    "distinct_conversations": len(distinct),
                    "schedule": schedule,
                    "classification": cls["classification"],
                    "window_fires": cls["window_fires"],
                    "fires_since": cls["fires_since"],
                    "cycle_days": cls["cycle_days"],
                    "reason": cls["reason"],
                    "reused_in_runs": [
                        {"scheduled_at_ms": r.get("scheduled_at_ms"),
                         "run_id": r.get("run_id")} for r in same
                    ],
                })
                break
    return findings, checked



def lint_shared_scripts(repo_dir=None):
    """Lint the shared scripts every routine fetches at run time.

    WHY
    ---
    cloud-prompts/_shared/*.sh is executed by every routine in the fleet, on every fire. A
    syntax error in one of them is not one routine's problem — it is all 27 of them, and it
    lands the next time any of them fires. Nothing checked them.

    This runs inside cron #91 (the schedule-drift guard), which fires at 04:05 ET daily —
    before the weekday routines — and which already clones this repo, so the scripts are on
    disk. Because #91 FETCHES this file at run time, adding the check needs no deployment:
    the next 04:05 ET fire picks it up.

    Returns a list of human-readable problems (empty = clean).
    """
    problems = []
    # The repo must come from the CALLER (--repo / the resolved clone), NOT from this file's
    # own location: #91 fetches the detector to a FLAT scratch dir (/workspace/guard/), so
    # resolving from __file__ yields /workspace, where cloud-prompts/_shared/ does not exist
    # ⇒ the sweeps ran against an EMPTY list and the two "must also RUN" scripts were
    # reported MISSING (measured 2026-11-07: the fleet's shared scripts were unlinted).
    repo = repo_dir or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    shared = os.path.join(repo, "cloud-prompts", "_shared")
    tools_dir = os.path.join(repo, "tools")
    if not os.path.isdir(shared):
        problems.append("LINT repo: cloud-prompts/_shared/ not found under %s — "
                        "the lint inspected ZERO files (pass --repo or run from the clone)" % repo)

    scripts = []
    if os.path.isdir(shared):
        scripts += [os.path.join(shared, f) for f in sorted(os.listdir(shared)) if f.endswith(".sh")]
    if os.path.isdir(tools_dir):
        scripts += [os.path.join(tools_dir, f) for f in sorted(os.listdir(tools_dir)) if f.endswith(".sh")]
    for sc in scripts:
        try:
            r = subprocess.run(["sh", "-n", sc], capture_output=True, text=True, timeout=30)
        except Exception as exc:
            problems.append(f"LINT {os.path.basename(sc)}: could not be checked ({exc})")
            continue
        if r.returncode != 0:
            problems.append(f"LINT {os.path.basename(sc)}: sh -n failed: "
                            f"{(r.stderr or '').strip().splitlines()[0] if (r.stderr or '').strip() else 'syntax error'}")

    pys = []
    for d in (shared, tools_dir):
        if os.path.isdir(d):
            pys += [os.path.join(d, f) for f in sorted(os.listdir(d)) if f.endswith(".py")]
    for py in pys:
        try:
            r = subprocess.run([sys.executable, "-m", "py_compile", py],
                               capture_output=True, text=True, timeout=60)
        except Exception as exc:
            problems.append(f"LINT {os.path.basename(py)}: could not be checked ({exc})")
            continue
        if r.returncode != 0:
            problems.append(f"LINT {os.path.basename(py)}: does not compile: "
                            f"{(r.stderr or '').strip().splitlines()[-1] if (r.stderr or '').strip() else 'syntax error'}")

    # The two scripts every routine executes: they must also RUN, not just parse.
    for name in ("verify_delivery.sh", "push_artifact.sh"):
        sc = os.path.join(shared, name)
        if not os.path.exists(sc):
            problems.append(f"LINT {name}: MISSING from cloud-prompts/_shared/")
            continue
        try:
            r = subprocess.run(["sh", sc, "--bogus-argument"], capture_output=True, text=True, timeout=30)
        except Exception as exc:
            problems.append(f"LINT {name}: does not execute ({exc})")
            continue
        if r.returncode == 0:
            problems.append(f"LINT {name}: accepted a bogus argument (should refuse)")
        if "unknown argument" not in (r.stderr or "").lower():
            problems.append(f"LINT {name}: did not report the bad argument clearly")

    return problems

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
    ap.add_argument("--repo", help="repo clone to compare the run-time specs against")
    ap.add_argument("--no-spec-check", action="store_true",
                    help="skip the skill-spec drift check (schedule + conversation only)")
    ap.add_argument("--spec-timeout", type=int, default=30,
                    help="per-URL timeout for the spec fetch (seconds)")
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
    try:
        CONTRACTS = load_spec_contracts(args.ground_truth)
    except Exception:                               # noqa: BLE001
        CONTRACTS = {}

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

    roster = check_roster(tasks, EXPECTED)

    reuse_findings, conv_checked = [], []
    run_files = 0
    rejected = 0
    runs_by_task = {}
    now_ms = int(now.timestamp() * 1000)
    if args.runs_file:
        if not os.path.exists(args.runs_file):
            print(f"ERROR: no such file: {args.runs_file}")
            return 2
        runs_by_task, rejected = parse_runs_file(args.runs_file, now_ms=now_ms)
    elif not args.no_run_chunks:
        runs_by_task, run_files = scan_run_chunks(args.run_chunks)
    reuse_findings, conv_checked = check_conversation_reuse(tasks, runs_by_task,
                                                            EXPECTED=EXPECTED, now_ms=now_ms)
    live_reuse = [r for r in reuse_findings if r.get("classification") == "LIVE"]
    hist_reuse = [r for r in reuse_findings if r.get("classification") != "LIVE"]

    # --- skill-spec drift -------------------------------------------------------
    spec_findings, spec_checked = [], []
    spec_error = None
    # Resolve the repo ONCE, OUTSIDE the spec-check block: resolving it inside left the
    # shared-script lint with no repo under --no-spec-check, i.e. a gate that only runs
    # on one path is not a gate.
    repo_dir = find_repo_dir(args.repo)
    if not repo_dir:
        repo_dir = clone_repo()
    if not args.no_spec_check:
        if not repo_dir:
            spec_error = "no repo clone available (clone failed and no --repo was given)"
        else:
            try:
                spec_findings, spec_checked = check_spec_drift(
                    tasks, EXPECTED, CONTRACTS, repo_dir=repo_dir,
                    timeout=args.spec_timeout)
            except Exception as exc:                 # noqa: BLE001
                spec_error = f"{type(exc).__name__}: {exc}"

    report = {"drift": drift, "unknown_routines": unknown, "missing_routines": missing,
              "roster": roster,
              "session_mode_findings": mode_findings,
              "conversation_reuse_findings": reuse_findings,
              "conversation_reuse_live": live_reuse,
              "conversation_reuse_historical": hist_reuse,
              "conversation_checked": conv_checked,
              "spec_findings": spec_findings,
              "spec_checked": len(spec_checked),
              "spec_error": spec_error,
              "run_chunk_files": run_files,
              "checked": len(seen), "repaired": []}

    if args.repair and drift:
        report["repaired"] = repair(drift)

    lint_problems = lint_shared_scripts(repo_dir=repo_dir)
    findings = bool(drift or unknown or missing or mode_findings or live_reuse
                     or lint_problems or spec_findings or spec_error
                     or not roster["match"])

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"checked {len(seen)} routines against the ground truth")
        print(f"linted {len(lint_problems)} problem(s) in the shared scripts")
        print(f"roster: {roster['live']} live / {roster['expected']} expected"
              + ("" if roster["match"] else "  -- MISMATCH"))
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
        if not roster["match"]:
            print(f"ROSTER  {roster['live']} live / {roster['expected']} expected -- the "
                  f"two must be equal or a routine is being checked by nothing")
            for n in roster["in_live_not_expected"]:
                print(f"         live but not in the ground truth: {n}")
            for n in roster["in_expected_not_live"]:
                print(f"         in the ground truth but not live: {n}")
        for r in report["repaired"]:
            print(f"REPAIRED  {r['cron_name']} -> {r['schedule']} (verified)")
        for r in report.get("failed", []):
            print(f"REPAIR-FAILED  {r['cron_name']}: {r['error']}")
        for lp in lint_problems:
            print(f"LINT  {lp}")
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
            cls = r.get("classification", "LIVE")
            print(f"CONV-REUSE {cls}  {r['cron_name']}: conversation {r['session_id']} was used by "
                  f"{len(r['reused_in_runs'])} runs (task_id {r['task_id']})")
            if r.get("window_fires") is not None:
                print(f"           window {r['window_fires']} fire(s) of `{r.get('schedule')}`"
                      f" -- {r.get('fires_since')} fire(s) ago")
            if r.get("reason"):
                print(f"           {r['reason']}")
            for rr in r["reused_in_runs"]:
                when = ""
                if rr.get("scheduled_at_ms"):
                    when = datetime.fromtimestamp(rr["scheduled_at_ms"] / 1000,
                                                  _et_tz()).strftime("%Y-%m-%d %H:%M ET")
                print(f"           run_id {rr.get('run_id')} scheduled {when}")
        print(f"conversation reuse: {len(live_reuse)} live, {len(hist_reuse)} historical")
        if args.no_spec_check:
            print("spec drift: NOT CHECKED (--no-spec-check)")
        elif spec_error:
            print(f"spec drift: NOT CHECKED -- {spec_error}")
        else:
            print(f"spec drift: {len(spec_checked)} routine(s) compared, "
                  f"{len([s for s in spec_findings if s['kind'] == 'SPEC-DRIFT'])} drifted")
        for s in spec_findings:
            if s["kind"] == "SPEC-DRIFT":
                print(f"SPEC-DRIFT  {s['cron_name']}: repo {s['repo_hash']} vs live {s['live_hash']}")
                print(f"             {s['path']} (task_id {s['task_id']})")
            elif s["kind"] == "SPEC-UNREACHABLE":
                print(f"SPEC-UNREACHABLE  {s['cron_name']}: {s['reason']}")
            elif s["kind"] == "SPEC-SECTION-MISSING":
                print(f"SPEC-SECTION-MISSING  {s['cron_name']}: {s['reason']}")
            elif s["kind"] == "SPEC-PATH-MISMATCH":
                print(f"SPEC-PATH-MISMATCH  {s['cron_name']}: {s['reason']}")
        print(f"RESULT: schedule_drift={len(drift)} unknown={len(unknown)} "
              f"missing={len(missing)} session_mode={len(mode_findings)} "
              f"conv_reuse_live={len(live_reuse)} conv_reuse_historical={len(hist_reuse)} "
              f"roster={roster['live']}/{roster['expected']} "
              f"spec_findings={len(spec_findings)} routines_with_runs={len(conv_checked)}")

        # A REPLY BLOCK, so the lines the reply must carry are not left to the
        # agent's initiative. Copy them verbatim.
        print("--- REPLY BLOCK (copy these lines into the reply verbatim) ---")
        print(f"roster: {roster['live']} live / {roster['expected']} expected")
        if not roster["match"]:
            print(f"ROSTER MISMATCH: {roster['live']} live / {roster['expected']} expected")
            for n in roster["in_live_not_expected"]:
                print(f"  live but not in the ground truth: {n}")
            for n in roster["in_expected_not_live"]:
                print(f"  in the ground truth but not live: {n}")
        for s in spec_findings:
            if s["kind"] == "SPEC-DRIFT":
                print(f"SPEC-DRIFT {s['cron_name']}: repo {s['repo_hash']} vs live {s['live_hash']}")
            elif s["kind"] == "SPEC-UNREACHABLE":
                print(f"SPEC-UNREACHABLE {s['cron_name']}: {s['reason']}")
            elif s["kind"] == "SPEC-SECTION-MISSING":
                print(f"SPEC-SECTION-MISSING {s['cron_name']}: {s['reason']}")
            elif s["kind"] == "SPEC-PATH-MISMATCH":
                print(f"SPEC-PATH-MISMATCH {s['cron_name']}: {s['reason']}")
        if spec_error:
            print(f"spec drift: NOT CHECKED -- {spec_error}")
        for r in live_reuse:
            print(f"CONV-REUSE LIVE {r['cron_name']}: conversation {r['session_id']} was used by "
                  f"{len(r['reused_in_runs'])} runs (task_id {r['task_id']})")
        print("--- END REPLY BLOCK ---")

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
