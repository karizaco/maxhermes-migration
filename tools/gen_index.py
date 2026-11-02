#!/usr/bin/env python3
"""
Regenerate the cron INDEX in cloud-prompts/cron-prompts/README.md.

Why this exists
---------------
The README index used to be hand-maintained, and it silently went stale: it said
"21 routines" while the fleet was 23, it listed #07/#10/#12/#17/#26 as "every
day" after they became Mon-Fri, and it omitted #01 and #91 entirely. A hand-kept
table is a table that lies.

This script builds the index from the AUTHORITATIVE sources:
  * tools/schedule-ground-truth.json  -> schedule + timezone (the contract)
  * the live cron_read view=list JSON -> project_id
  * tools/gen_roster.py ARTIFACTS     -> the output path of each routine

The ground truth wins for the schedule. If the live scheduler and the ground
truth disagree, the guard (#91) reports the drift; this script does not silently
paper over it.

Usage:
  python3 tools/gen_index.py --tasks tasks.json [--readme PATH] [--check]
"""
import argparse, json, os, re, sys, importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

FIRES_ON = {"*": "every day", "1-5": "Mon-Fri", "0": "Sun", "1": "Mon",
            "3": "Wed", "6": "Sat", "2": "Tue", "4": "Thu", "5": "Fri"}

# Routines that legitimately have no ARTIFACTS entry in gen_roster.py.
NO_ARTIFACT = {
    "01-weekly-mcp-health-check.md": "`mcp-health/ledger.md` + `mcp-health/YYYY-Wnn.md`",
    "90-delivery-auditor.md": "`_audit/status.json` (audit/status branch)",
    "91-schedule-drift-guard.md": "none (writes no artifact)",
}


def load_artifacts():
    """Reuse gen_roster.py's ARTIFACTS map instead of duplicating it."""
    path = os.path.join(HERE, "gen_roster.py")
    spec = importlib.util.spec_from_file_location("gen_roster", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.ARTIFACTS


def fires_on(schedule):
    parts = schedule.split()
    dow = parts[4] if len(parts) == 5 else "*"
    return FIRES_ON.get(dow, dow)


def build_rows(gt_routines, live_tasks, artifacts):
    projects = {}
    for t in live_tasks:
        name = t.get("cron_name", "").replace("%3A", ":")
        if name.startswith("@self-reminder"):
            continue
        projects[name] = str(t.get("project_id", "—"))

    rows = []
    for fname, spec in gt_routines.items():
        base = fname.replace("%3A", ":").replace(".md", "")
        num, _, routine = base.partition("-")
        sched = spec["schedule"]
        parts = sched.split()
        # cron field order is MINUTE HOUR DOM MON DOW
        mm, hh = (parts[0], parts[1]) if len(parts) == 5 else ("?", "?")
        art = artifacts.get(base)
        out = NO_ARTIFACT.get(fname) or (f"`{art[0]}`" if art else "—")
        rows.append({
            "id": num, "routine": routine, "schedule": sched,
            "fires": fires_on(sched), "project": projects.get(fname, "—"),
            "output": out, "sort": (int(hh) if hh.isdigit() else 99,
                                     int(mm) if mm.isdigit() else 99, num),
        })
    rows.sort(key=lambda r: r["sort"])
    return rows


def render_table(rows):
    out = ["| ID | Routine | Schedule (ET) | Fires on | Project | Output |",
           "|---|---|---|---|---|---|"]
    for r in rows:
        out.append(f"| {r['id']} | {r['routine']} | `{r['schedule']}` | {r['fires']} | "
                   f"{r['project']} | {r['output']} |")
    return "\n".join(out)


def render_count(rows):
    n = len(rows)
    special = sorted([r for r in rows if r["id"] in ("90", "91")], key=lambda r: r["id"])
    producers = n - len(special)
    tail = " + ".join(f"the #{r['id']} {'auditor' if r['id'] == '90' else 'drift guard'}"
                       for r in special)
    return (f"**{n} routines** ({producers} producers + {tail}), all owned by `Mavis`, "
            f"all `America/New_York`, all `MiniMax-M3.1-Flash`,\n"
            f"all `session.mode=new`. Day-of-week lives in the **scheduler** expression, so "
            f"weekend fires cost\nnothing — no agent invocation is spent discovering it is a "
            f"weekend.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", required=True, help="cron_read view=list JSON")
    ap.add_argument("--ground-truth", default=os.path.join(HERE, "schedule-ground-truth.json"))
    ap.add_argument("--readme", default=os.path.join(REPO, "cloud-prompts", "cron-prompts", "README.md"))
    ap.add_argument("--check", action="store_true", help="fail if the README is stale, write nothing")
    args = ap.parse_args()

    raw = json.load(open(args.tasks))
    tasks = raw["tasks"] if isinstance(raw, dict) and "tasks" in raw else \
            raw["response"]["tasks"] if isinstance(raw, dict) and "response" in raw else raw
    gt = json.load(open(args.ground_truth))["routines"]
    rows = build_rows(gt, tasks, load_artifacts())

    readme = open(args.readme).read()
    new_table = render_table(rows)
    new_count = render_count(rows)

    out = re.sub(r"\| ID \| Routine \| Schedule \(ET\) \| Fires on \| Project \| Output \|.*?\n\n",
                 new_table + "\n\n", readme, flags=re.S)
    out = re.sub(r"\*\*\d+ routines\*\* \(.*?\n.*?weekend fires cost\nnothing[^\n]*",
                 new_count, out, flags=re.S)

    if args.check:
        if out != readme:
            print("STALE: README index does not match the ground truth")
            sys.exit(1)
        print("OK: README index matches the ground truth")
        return

    open(args.readme, "w").write(out)
    print(f"wrote {args.readme}: {len(rows)} routines")


if __name__ == "__main__":
    main()
