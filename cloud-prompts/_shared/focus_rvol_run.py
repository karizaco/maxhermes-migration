#!/usr/bin/env python3
"""
focus_rvol_run.py — fetch the helpers, build the universe, score it, render the artifact.

CAPABILITY_MARKER: FOCUS_RVOL_RUN_V1

WHY
---
Cron #07's prompt used to carry three separate fetch ladders, and every ladder is a place a
copy can be stale, truncated, or absent. Hand-maintaining them in the prompt is also how the
prompt grew past 40 KB and became unsafe to paste: a stale copy of the older prompt sitting in
context contaminated a redeploy in four places on 2026-11-12.

This wrapper moves the whole run-time fetch into ONE script with ONE capability marker. The
prompt says: fetch this, run it, read its stderr, publish what it rendered.

WHAT IT DOES
------------
1. Fetches, each behind its capability marker (a copy without the marker is an OLD copy):
     FOCUS_RVOL_UNIVERSE_V1  focus_rvol_universe.py  builds the on-disk candidate union
     TV_SCAN_V2              tv_scan.py            the VALIDATED scanner client
     (no marker)            focus_rvol_score.py    the scoring engine
2. Builds the universe from the PREVIOUS session's on-disk sources.
3. Scores every candidate on the same feed with the same TradingView denominator, and renders
   the artifact (markdown + CSV) itself.

It prints a one-line summary to stderr. NOTHING here decides what to publish — the prompt does.

USAGE
    python3 focus_rvol_run.py --fire-date 2026-11-12 \
        --screens-dir /workspace/daily-screens \
        --md-out /workspace/focus-rvol-snapshot.md \
        --csv-out /workspace/focus-rvol-snapshot.csv
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

CAPABILITY_MARKER = "FOCUS_RVOL_RUN_V1"
REPO = "karizaco/maxhermes-migration"

HELPERS = [
    ("FOCUS_RVOL_UNIVERSE_V1", "focus_rvol_universe.py", "cloud-prompts/_shared/focus_rvol_universe.py"),
    ("TV_SCAN_V2", "tv_scan.py", "cloud-prompts/_shared/tv_scan.py"),
    ("-", "focus_rvol_score.py", "tools/focus_rvol_score.py"),
]


def fetch(marker: str, name: str, path: str, workdir: str) -> bool:
    """Fetch a helper, demanding its capability marker. Returns True on success."""
    dest = os.path.join(workdir, name)
    urls = [
        f"https://api.github.com/repos/{REPO}/contents/{path}?ref=main",
        f"https://raw.githubusercontent.com/{REPO}/main/{path}",
        f"https://cdn.jsdelivr.net/gh/{REPO}@main/{path}",
    ]
    for url in urls:
        tmp = dest + ".tmp"
        subprocess.run(["curl", "-sL", "--max-time", "30",
                        "-H", "Accept: application/vnd.github.raw",
                        "-H", f"Authorization: Bearer {os.environ.get('GITHUB_TOKEN','')}",
                        "-o", tmp, url], capture_output=True)
        ok = False
        try:
            if os.path.getsize(tmp) > 200:
                head = open(tmp, encoding="utf-8", errors="replace").read(200)
                if '"message"' not in head:
                    if marker == "-":
                        ok = True
                    else:
                        body = open(tmp, encoding="utf-8", errors="replace").read()
                        ok = marker in body
        except OSError:
            ok = False
        if ok:
            os.replace(tmp, dest)
            return True
        try:
            os.remove(tmp)
        except OSError:
            pass
    print(f"[run] {name}: FETCH FAILED", file=sys.stderr)
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fire-date", required=True)
    ap.add_argument("--screens-dir", default="/workspace/daily-screens")
    ap.add_argument("--board-dir", default="/workspace/us-stocks-in-play")
    ap.add_argument("--repo", default="/workspace")
    ap.add_argument("--work-dir", default="/workspace")
    ap.add_argument("--md-out", default="/workspace/focus-rvol-snapshot.md")
    ap.add_argument("--csv-out", default="/workspace/focus-rvol-snapshot.csv")
    ap.add_argument("--out", default="/workspace/focus-rvol-scores.json")
    ap.add_argument("--wider-source", default="focus+master+17")
    a = ap.parse_args()

    missing = [n for m, n, p in HELPERS if not fetch(m, n, p, a.work_dir)]
    if missing:
        print(f"[run] could not fetch: {', '.join(missing)} — the caller must fall back",
              file=sys.stderr)
        return 1

    env = dict(os.environ)
    prev = _prev_session_dir(a.screens_dir, a.fire_date)
    if prev is None:
        print("[run] no previous session with a focus.md — cannot build the universe", file=sys.stderr)
        return 1
    prevcsv = os.path.join(prev, "focus-rvol-snapshot.csv")

    # 1. build the universe
    r = subprocess.run([sys.executable, os.path.join(a.work_dir, "focus_rvol_universe.py"),
                        "--fire-date", a.fire_date, "--screens-dir", a.screens_dir,
                        "--board-dir", a.board_dir, "--repo", a.repo],
                       capture_output=True, text=True, env=env)
    sys.stderr.write(r.stderr)
    if r.returncode != 0:
        print("[run] the universe build failed", file=sys.stderr)
        return r.returncode

    # 2. score it and render the artifact
    # The upstream focus.md carries the sweep's OWN `Screen data_date:` (the shibui T+1 date).
    # It is NOT the folder date and it is NOT inferable from the calendar gap - the scorer
    # reads it so the artifact's three dates cannot collapse into one.
    focus_md = os.path.join(prev, "focus.md")
    focus_dir_date = os.path.basename(prev)
    r = subprocess.run([sys.executable, os.path.join(a.work_dir, "focus_rvol_score.py"),
                        "--fire-date", a.fire_date,
                        "--symbols", "/workspace/universe.txt",
                        "--focus", "/workspace/focus.txt",
                        "--prior-csv", prevcsv,
                        "--focus-md", focus_md,
                        "--focus-dir-date", focus_dir_date,
                        "--md-out", a.md_out, "--csv-out", a.csv_out,
                        "--wider-source", a.wider_source,
                        "--out", a.out],
                       capture_output=True, text=True, env=env)
    sys.stderr.write(r.stderr)
    return r.returncode


def _prev_session_dir(screens_dir: str, fire_date: str) -> str | None:
    cands = []
    try:
        for name in os.listdir(screens_dir):
            p = os.path.join(screens_dir, name)
            if os.path.isdir(p) and name < fire_date and \
               os.path.exists(os.path.join(p, "focus.md")):
                cands.append(name)
    except OSError:
        return None
    return os.path.join(screens_dir, sorted(cands)[-1]) if cands else None


if __name__ == "__main__":
    sys.exit(main())
