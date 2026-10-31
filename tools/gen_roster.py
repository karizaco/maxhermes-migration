#!/usr/bin/env python3
"""
Generate the cloud cron roster from LIVE sources:
  - the scheduler (cron_read view=list)  -> supplied as JSON on stdin or --tasks FILE
  - the outputs repo (origin/main)       -> artifact presence + last-delivered date

Writes:
  <out>/ROSTER.md          human-readable roster
  <out>/roster.json        machine-readable roster

Usage:
  python3 gen_roster.py --tasks tasks.json --out /path --repo /path/to/clone
  python3 gen_roster.py --tasks tasks.json --out /path        # skips artifact columns
"""
import argparse, json, os, re, subprocess, sys, datetime, zoneinfo

ET = zoneinfo.ZoneInfo("America/New_York")

# routine key -> (output path template, output dir on the outputs repo, filename suffix)
#
# The artifact DIRECTORY is deliberately shared by several routines (earnings/ holds
# both -reminders.md and -reactions.md; macro-calendar/ holds both -midweek.md and
# -week-ahead.md; daily-screens/ holds seven different screens). Matching on the
# directory alone makes every routine in a shared directory report the NEWEST date
# any sibling produced. The third element is the filename suffix used to keep a
# routine to its OWN artifact.
ARTIFACTS = {
 "02-asia-pre-market-reactions": ("asia-pre-market/{date}.md", "asia-pre-market", ".md"),
 "04-reversal-bullish-3:55": ("daily-screens/{date}/reversal-bullish-3:55.md", "daily-screens", "reversal-bullish-3:55.md"),
 "05-eod-international-daily": ("international-eod/{date}/", "international-eod", ".csv"),
 "06-stock-screener-pattern-study-backlog": ("daily-screens/{date}/weekly-ipo.md", "daily-screens", "weekly-ipo.md"),
 "07-stock-screener-focus-rvol-09:45": ("daily-screens/{date}/focus-rvol-snapshot.md", "daily-screens", "focus-rvol-snapshot.md"),
 "08-stock-screener-pre-market-gapper": ("daily-screens/{date}/pre-market-gapper.md", "daily-screens", "pre-market-gapper.md"),
 "09-stock-screener-daily-sweep-18:30": ("daily-screens/{date}/daily-sweep.md", "daily-screens", "daily-sweep.md"),
 "10-stock-screener-breadth-snapshot": ("daily-screens/{date}/breadth-snapshot.md", "daily-screens", "breadth-snapshot.md"),
 "12-cross-asset-correlation-snapshot": ("cross-asset/{date}.md", "cross-asset", ".md"),
 "13-macro-calendar-midweek": ("macro-calendar/{date}-midweek.md", "macro-calendar", "-midweek.md"),
 "14-macro-calendar-week-ahead": ("macro-calendar/{date}-week-ahead.md", "macro-calendar", "-week-ahead.md"),
 "15-earnings-reaction-scanner": ("earnings/{date}-reactions.md", "earnings", "-reactions.md"),
 "16-unusual-options-flow-daily": ("options-flow/{date}.md", "options-flow", ".md"),
 "17-us-stocks-in-play": ("us-stocks-in-play/{date}.md", "us-stocks-in-play", ".md"),
 "19-earnings-reminder-daily": ("earnings/{date}-reminders.md", "earnings", "-reminders.md"),
 "20-eod-watchlist-csv-snapshot": ("us-eod/{date}.csv", "us-eod", ".csv"),
 "22-weekly-market-recap-preview": ("weekly/{date}-preview.md", "weekly", "-preview.md"),
 "23-agentic-post-market-brief": ("daily-briefs/{date}-post-market.md", "daily-briefs", "-post-market.md"),
 "25-ntrt-gap-brief-daily": ("ntrt/{date}.md", "ntrt", ".md"),
 "26-agentic-pre-market-brief": ("daily-briefs/{date}-pre-market.md", "daily-briefs", "-pre-market.md"),
 "90-delivery-auditor": ("_audit/status.json (audit/status branch)", "", "status.json"),
}
# weekly routines get a longer staleness tolerance
TOLERANCE = {"13-macro-calendar-midweek":9, "14-macro-calendar-week-ahead":9,
              "22-weekly-market-recap-preview":9, "06-stock-screener-pattern-study-backlog":9}
# A routine whose CURRENT schedule has not reached its first fire yet is EXPECTED to be
# absent — it has never had a scheduled chance to run. Reporting it as stale is a false
# positive. Keep this in sync with the NOT_YET_FIRED list in cron #90's prompt.
NOT_YET_FIRED = {"22-weekly-market-recap-preview": "2026-11-01"}
DATE_RE = re.compile(r"(20\d\d-\d\d-\d\d)")

def key_of(name):
    stem = name[:-3] if name.endswith(".md") else name
    return stem.replace("%3A", ":")

def git_files(repo):
    out = subprocess.run(["git","-C",repo,"ls-tree","-r","--name-only","origin/main"],
                         capture_output=True, text=True)
    if out.returncode != 0:
        sys.stderr.write("git ls-tree failed: %s\n" % out.stderr.strip())
        return []
    return out.stdout.split("\n")

def last_delivered(files, routine):
    """Newest date among the files that belong to THIS routine.

    Filters on directory AND filename suffix, because several routines share a
    directory (earnings/, macro-calendar/, daily-screens/). Without the suffix
    filter, #19 reports #15's newest date and every sibling looks fresh."""
    spec = ARTIFACTS.get(routine)
    if not spec: return None
    dirname, suffix = spec[1], spec[2]
    best = None
    for f in files:
        if not f.startswith(dirname + "/"): continue
        if not f.endswith(suffix): continue
        for d in DATE_RE.findall(f):
            if best is None or d > best: best = d
    return best

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", required=True, help="JSON: list of cron_read tasks, or {name: {...}}")
    ap.add_argument("--out", required=True)
    ap.add_argument("--repo", help="clone of the outputs repo (for artifact presence)")
    ap.add_argument("--as-of", default=None, help="ET date (default today in ET)")
    args = ap.parse_args()

    raw = json.load(open(args.tasks))
    tasks = raw["tasks"] if isinstance(raw, dict) and "tasks" in raw else raw
    if isinstance(tasks, dict):
        tasks = [{"cron_name": k, **v} for k, v in tasks.items()]

    files = git_files(args.repo) if args.repo and os.path.isdir(args.repo) else []
    as_of = args.as_of or datetime.datetime.now(ET).strftime("%Y-%m-%d")

    rows = []
    for t in tasks:
        name = t.get("cron_name","")
        if name.startswith("@self-reminder"): continue
        routine = key_of(name)
        sch = t.get("schedule","")
        parts = sch.split()
        dow = parts[4] if len(parts)==5 else "*"
        fires = {"*":"every day","1-5":"Mon-Fri","0":"Sun","1":"Mon","3":"Wed","6":"Sat"}.get(dow, dow)
        hh = parts[1] if len(parts)==5 else "?"
        spec = ARTIFACTS.get(routine)
        # A routine with no artifact dir on origin/main (e.g. the auditor, which
        # pushes to the audit/status branch) cannot be stale-tested against main.
        exempt = spec is None or not spec[1]
        last = last_delivered(files, routine) if files else None
        age = None
        if last:
            age = (datetime.date.fromisoformat(as_of) - datetime.date.fromisoformat(last)).days
        tol = TOLERANCE.get(routine, 5)
        first_fire = NOT_YET_FIRED.get(routine)
        not_yet_fired = bool(first_fire) and as_of < first_fire
        if exempt or not_yet_fired:
            stale = None
        else:
            stale = (age is None) or (age > tol) if files else None
        rows.append({
            "task_id": t.get("task_id"), "routine": routine, "schedule": sch,
            "fire_et": f"{int(hh):02d}:{parts[0].zfill(2)}" if hh!="?" else "?",
            "fires": fires, "tz": t.get("timezone"), "project": t.get("project_id"),
            "enabled": t.get("enabled"),
            "session_mode": (t.get("session") or {}).get("mode"),
            "artifact": ARTIFACTS.get(routine,("",""))[0],
            "last_delivered": last, "age_days": age, "tolerance_days": tol,
            "stale": stale, "not_yet_fired": not_yet_fired, "first_fire": first_fire,
        })

    os.makedirs(args.out, exist_ok=True)
    json.dump({"as_of_et": as_of, "routines": rows},
              open(os.path.join(args.out,"roster.json"),"w"), indent=1)

    L = []
    L.append("# Cloud cron roster")
    L.append("")
    L.append(f"Generated by `tools/gen_roster.py` from the live scheduler and `origin/main`. "
             f"As of **{as_of} ET**.")
    L.append("")
    L.append("Regenerate with:")
    L.append("")
    L.append("```bash")
    L.append("cron_read view=list > tasks.json      # scheduler state")
    L.append("python3 tools/gen_roster.py --tasks tasks.json --repo ./outputs-clone --out .")
    L.append("```")
    L.append("")
    L.append("| Routine | Fire (ET) | Fires on | Project | Artifact | Last delivered | Age | Stale? |")
    L.append("|---|---|---|---|---|---|---|---|")
    for r in sorted(rows, key=lambda x: (x["fire_et"], x["routine"])):
        last = r["last_delivered"] or "—"
        age = f"{r['age_days']}d" if r["age_days"] is not None else "—"
        if r["stale"] is None: flag="?"
        elif r["stale"]: flag="**YES**"
        else: flag="no"
        L.append(f"| {r['routine']} | {r['fire_et']} | {r['fires']} | {r['project']} | "
                 f"`{r['artifact']}` | {last} | {age} | {flag} |")
    L.append("")
    stale = [r for r in rows if r["stale"]]
    L.append("## Health summary")
    L.append("")
    L.append(f"- **{len(rows)} routines** tracked; all owner `Mavis`, all `America/New_York`.")
    nyf = [r for r in rows if r.get("not_yet_fired")]
    if nyf:
        L.append(f"- **{len(nyf)} routine(s) have not fired yet under their current schedule** — "
                 "expected, NOT a finding:")
        for r in nyf:
            L.append(f"  - `{r['routine']}` — first fire {r['first_fire']}")
    if stale:
        L.append(f"- **{len(stale)} routine(s) have not delivered within tolerance** — this is the check "
                 f"that would have caught cron #22:")
        for r in stale:
            last = r["last_delivered"] or "NEVER"
            age = f", {r['age_days']}d old" if r["age_days"] is not None else ""
            L.append(f"  - `{r['routine']}` — last delivered {last}{age} "
                     f"(tolerance {r['tolerance_days']}d)")
    else:
        L.append("- **No routine is outside its delivery tolerance.**")
    L.append("")
    L.append("## Known repository hazards")
    L.append("")
    L.append("- `origin/HEAD` points at `master`. All routines push to `main`. A plain `git clone` "
             "lands on the wrong branch unless `main` is fetched explicitly.")
    L.append("- The outputs repo holds artifacts only. Audit state lives on the `audit/status` branch.")
    L.append("- `_regime.json` was written by both #10 (14:00 ET) and #09 (18:30 ET) — #10 now writes "
             "`_regime-intraday.json` instead.")
    L.append("")
    open(os.path.join(args.out,"ROSTER.md"),"w").write("\n".join(L)+"\n")
    print(f"wrote ROSTER.md + roster.json ({len(rows)} routines, {len(stale)} stale)")

if __name__ == "__main__":
    main()
