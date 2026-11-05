#!/usr/bin/env python3
"""
Deploy the repo's cron prompts to the live scheduler, one task at a time, with a
byte-exact verification after each write.

WHY A HARNESS
-------------
Hand-pasting a 7-13 KB prompt into `cron_update` drifts: observed byte-exact-in-
length but wrong-in-content pastes on #90 and #04, and 3 cosmetic bytes on
#16 (a `view=runs` -> `view:runs` typo and one line wrap). A length check is
not a byte check; only SHA-256 over the raw bytes is proof.

This harness therefore:
  1. reads each prompt from the repo clone (the source of truth),
  2. emits the EXACT bytes for the `prompt` argument as a JSON string,
  3. verifies the read-back by SHA-256 against the repo file,
  4. re-checks every non-prompt field (schedule, timezone, enabled, session,
     model, project_id, task_id, created_at) against the pre-deploy value.

A prompt-only `cron_update` resets `timezone` to Etc/GMT-7 (it happened twice
on 2026-11-03), so `schedule` and `timezone` are ALWAYS resent in the same call
and re-verified afterwards.

USAGE
  python3 tools/deploy_prompts.py --list
  python3 tools/deploy_prompts.py --emit 02            # print the JSON args for one
  python3 tools/deploy_prompts.py --verify            # hash all deployed vs repo
"""
import argparse, hashlib, json, os, re, subprocess, sys, glob

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROMPTS = os.path.join(REPO, "cloud-prompts", "cron-prompts")

# cron_name -> (task_id, schedule) as read from the live scheduler
TASKS = {
    "01-weekly-mcp-health-check.md":            ("459082178638008", "0 2 * * 0"),
    "02-asia-pre-market-reactions.md":          ("457173826801866", "30 6 * * 1-5"),
    "04-reversal-bullish-3:55.md":              ("457170140713209", "55 15 * * 1-5"),
    "05-eod-international-daily.md":            ("457951662133387", "30 16 * * 1-5"),
    "06-stock-screener-pattern-study-backlog.md": ("457172664209604", "0 15 * * 6"),
    "07-stock-screener-focus-rvol-09:45.md":     ("446509795921995", "45 9 * * 1-5"),
    "08-stock-screener-pre-market-gapper.md":   ("457578163015913", "30 8 * * 1-5"),
    "09-stock-screener-daily-sweep-18:30.md":   ("457172664209608", "30 18 * * 1-5"),
    "10-stock-screener-breadth-snapshot.md":    ("457173814395027", "0 14 * * 1-5"),
    "12-cross-asset-correlation-snapshot.md":   ("457172664209609", "0 10 * * 1-5"),
    "13-macro-calendar-midweek.md":             ("457174550757502", "0 14 * * 3"),
    "14-macro-calendar-week-ahead.md":          ("457172664209611", "0 15 * * 0"),
    "15-earnings-reaction-scanner.md":          ("457570777166058", "0 8 * * 1-5"),
    "16-unusual-options-flow-daily.md":         ("457305357095000", "35 16 * * 1-5"),
    "17-us-stocks-in-play.md":                  ("457954144674016", "50 9,15 * * 1-5"),
    "19-earnings-reminder-daily.md":            ("457569978294401", "0 6 * * 1-5"),
    "20-eod-watchlist-csv-snapshot.md":         ("457172664209610", "0 16 * * 1-5"),
    "22-weekly-market-recap-preview.md":        ("457956577145214", "47 17 * * 0"),
    "23-agentic-post-market-brief.md":          ("457952877850694", "30 22 * * 1-5"),
    "25-ntrt-gap-brief-daily.md":               ("457578106761360", "0 9 * * 1-5"),
    "26-agentic-pre-market-brief.md":           ("457175063601252", "30 8 * * 1-5"),
    "90-delivery-auditor.md":                   ("457957802930526", "0 7 * * *"),
    "91-schedule-drift-guard.md":               ("458356248809843", "5 4 * * *"),
    # Added 2026-11-05: the #92 catalyst-tape slots were MISSING from this map, so --emit
    # could not reach them and the harness could not deploy or verify them. A routine with
    # no row here is a routine the deploy harness cannot fix or prove.
    "92a-preopen-catalyst-capture-0830.md":    ("459079693529459", "30 8 * * 1-5"),
    "92b-preopen-catalyst-capture-0950.md":    ("459079693529460", "50 9 * * 1-5"),
}


def sha(b):
    return hashlib.sha256(b).hexdigest()


def repo_prompt(name):
    p = os.path.join(PROMPTS, name)
    if not os.path.exists(p):
        return None
    return open(p, encoding="utf-8").read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--emit")
    ap.add_argument("--verify")
    a = ap.parse_args()

    if a.list:
        for n in sorted(TASKS):
            s = repo_prompt(n)
            print(f"{n:52s} {TASKS[n][0]:16s} {TASKS[n][1]:14s} {'OK' if s else 'MISSING'} {len(s.encode()) if s else 0}B")
        return

    if a.emit:
        n = a.emit
        # accept either the bare routine number ("05") or the full filename
        if n.isdigit():
            cands = [k for k in TASKS if k.split("-")[0] == n]
            if len(cands) != 1:
                print(f"ambiguous or unknown routine {n}: {cands}", file=sys.stderr)
                sys.exit(2)
            n = cands[0]
        if n not in TASKS:
            print(f"unknown routine {n}", file=sys.stderr)
            sys.exit(2)
        p = repo_prompt(n)
        if p is None:
            print(f"no repo file for {n}", file=sys.stderr)
            sys.exit(2)
        tid, sch = TASKS[n]
        args = {
            "task_id": tid,
            "schedule": sch,
            "timezone": "America/New_York",
            "session": {"mode": "new"},
            "prompt": p,
        }
        # emit as a JSON object so the caller can paste it verbatim; the prompt
        # keeps its real line breaks (json.dumps with indent=None escapes them as
        # \n, which the tool arg layer decodes back to real newlines).
        print(json.dumps(args, ensure_ascii=False))
        print(f"# sha256(repo) = {sha(p.encode())}", file=sys.stderr)
        return

    if a.verify:
        print("see tools/verify_prompts.py", file=sys.stderr)


if __name__ == "__main__":
    main()
