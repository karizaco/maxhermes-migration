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

# routine key -> (output path template, output dir on the outputs repo)
ARTIFACTS = {
 "02-asia-pre-market-reactions": ("asia-pre-market/{date}.md", "asia-pre-market"),
 "04-reversal-bullish-3:55": ("daily-screens/{date}/reversal-bullish-3:55.md", "daily-screens"),
 "05-eod-international-daily": ("international-eod/{date}/", "international-eod"),
 "06-stock-screener-pattern-study-backlog": ("daily-screens/{date}/weekly-ipo.md", "daily-screens"),
 "07-stock-screener-focus-rvol-09:45": ("daily-screens/{date}/focus-rvol-snapshot.md", "daily-screens"),
 "08-stock-screener-pre-market-gapper": ("daily-screens/{date}/pre-market-gapper.md", "daily-screens"),
 "09-stock-screener-daily-sweep-18:30": ("daily-screens/{date}/daily-sweep.md", "daily-screens"),
 "10-stock-screener-breadth-snapshot": ("daily-screens/{date}/breadth-snapshot.md", "daily-screens"),
 "12-cross-asset-correlation-snapshot": ("cross-asset/{date}.md", "cross-asset"),
 "13-macro-calendar-midweek": ("macro-calendar/{date}-midweek.md", "macro-calendar"),
 "14-macro-calendar-week-ahead": ("macro-calendar/{date}-week-ahead.md", "macro-calendar"),
 "15-earnings-reaction-scanner": ("earnings/{date}-reactions.md", "earnings"),
 "16-unusual-options-flow-daily": ("options-flow/{date}.md", "options-flow"),
 "17-us-stocks-in-play": ("us-stocks-in-play/{date}.md", "us-stocks-in-play"),
 "19-earnings-reminder-daily": ("earnings/{date}-reminders.md", "earnings"),
 "20-eod-watchlist-csv-snapshot": ("us-eod/{date}.csv", "us-eod"),
 "22-weekly-market-recap-preview": ("weekly/{date}-preview.md", "weekly"),
 "23-agentic-post-market-brief": ("daily-briefs/{date}-post-market.md", "daily-briefs"),
 "25-ntrt-gap-brief-daily": ("ntrt/{date}.md", "ntrt"),
 "26-agentic-pre-market-brief": ("daily-briefs/{date}-pre-market.md", "daily-briefs"),
 "90-delivery-auditor": ("_audit/status.json", "_audit"),
}
# weekly routines get a longer staleness tolerance
TOLERANCE = {"13-macro-calendar-midweek":9, "14-macro-calendar-week-ahead":9,
              "22-weekly-market-recap-preview":9, "06-stock-screener-pattern-study-backlog":9}
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
    tpl = ARTIFACTS.get(routine, (None,None))[1]
    if not tpl: return None
    best = None
    for f in files:
        if not f.startswith(tpl + "/"): continue
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
        last = last_delivered(files, routine) if files else None
        age = None
        if last:
            age = (datetime.date.fromisoformat(as_of) - datetime.date.fromisoformat(last)).days
        tol = TOLERANCE.get(routine, 5)
        stale = (age is None) or (age > tol) if files else None
        rows.append({
            "task_id": t.get("task_id"), "routine": routine, "schedule": sch,
            "fire_et": f"{int(hh):02d}:{parts[0].zfill(2)}" if hh!="?" else "?",
            "fires": fires, "tz": t.get("timezone"), "project": t.get("project_id"),
            "enabled": t.get("enabled"),
            "session_mode": (t.get("session") or {}).get("mode"),
            "artifact": ARTIFACTS.get(routine,("",""))[0],
            "last_delivered": last, "age_days": age, "tolerance_days": tol,
            "stale": stale,
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
