#!/usr/bin/env python3
"""
focus_rvol_universe.py — build cron #07's candidate universe from what is ALREADY ON DISK.

CAPABILITY_MARKER: FOCUS_RVOL_UNIVERSE_V1

WHY
---
Cron #07's focus roster is a MOMENTUM screen built on the previous session's data, so it
structurally CANNOT contain a name whose move has not happened yet. Measured on 2026-11-09: the
focus roster carried 1 of the day's top 10 gainers, the previous session's `master.csv` carried
5, cron #17's boards carried 7, and the union of all three carried 10 of 10. Publishing only the
roster is publishing a screen that misses the day's movers.

The wider universe is therefore part of the screen — but it must be built from sources that
ALREADY EXIST, never by re-scanning the market: the previous session's `focus.csv`,
`master.csv` and cron #17's candidate CSVs were all published by earlier routines, before this
fire, and are already on disk.

This script does the union and writes two symbol files. It does NOT fetch prices or compute
anything — `tools/focus_rvol_score.py` does that.

WHAT IT WRITES
--------------
    /workspace/universe.txt   every candidate symbol, one per line, deduplicated
    /workspace/focus.txt      the focus roster's symbols only, one per line

It prints a one-line summary to stderr. A missing cron #17 board is NOT fatal — the union is
narrower, and the caller reports the narrower source.

USAGE
    python3 focus_rvol_universe.py --fire-date 2026-11-12 --screens-dir /workspace/daily-screens
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

CAPABILITY_MARKER = "FOCUS_RVOL_UNIVERSE_V1"
SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,6}$")


def prev_session_dir(screens_dir: str, fire_date: str) -> str | None:
    """The newest session directory EARLIER than the fire date that holds a focus.md.

    On a Monday that is Friday: the files are named for the SESSION, not for the day before.
    """
    cands = []
    for name in os.listdir(screens_dir):
        p = os.path.join(screens_dir, name)
        if not os.path.isdir(p) or name >= fire_date:
            continue
        if os.path.exists(os.path.join(p, "focus.md")):
            cands.append(name)
    if not cands:
        return None
    return os.path.join(screens_dir, sorted(cands)[-1])


def syms_from_csv(path: str) -> list[str]:
    """The first column of a CSV, skipping the header, if it looks like a symbol column."""
    out = []
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh):
                if i == 0:
                    continue
                s = line.split(",", 1)[0].strip().strip('"')
                if s:
                    out.append(s)
    except OSError:
        return []
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fire-date", required=True)
    ap.add_argument("--screens-dir", default="/workspace/daily-screens")
    ap.add_argument("--board-dir", default="/workspace/us-stocks-in-play")
    ap.add_argument("--repo", default="/workspace")
    ap.add_argument("--out-universe", default="/workspace/universe.txt")
    ap.add_argument("--out-focus", default="/workspace/focus.txt")
    a = ap.parse_args()

    prev = prev_session_dir(a.screens_dir, a.fire_date)
    if prev is None:
        print("focus_rvol_universe: no previous session with a focus.md — cannot build the "
              "universe; the caller must fall back to the focus roster only",
              file=sys.stderr)
        return 1
    prevdate = os.path.basename(prev)
    print(f"[prev session] {prevdate}", file=sys.stderr)

    focus_syms = syms_from_csv(os.path.join(prev, "focus.csv"))
    master_syms = syms_from_csv(os.path.join(prev, "master.csv"))

    # cron #17's boards for THAT session only — globbing *.csv would sweep in every
    # earlier session's board and inflate the universe with stale names.
    board_syms, board_files = [], []
    for fn in (f"{prevdate}-open-candidates.csv", f"{prevdate}-candidates.csv"):
        p = os.path.join(a.board_dir, fn)
        if not os.path.exists(p):
            # fetch it from the outputs repo
            os.makedirs(a.board_dir, exist_ok=True)
            try:
                r = subprocess.run(["git", "-C", a.repo, "show",
                                    f"origin/main:us-stocks-in-play/{fn}"],
                                   capture_output=True, text=True, timeout=60)
                if r.returncode == 0 and r.stdout.strip():
                    open(p, "w", encoding="utf-8").write(r.stdout)
            except Exception:
                pass
        if os.path.exists(p):
            board_files.append(fn)
            board_syms += syms_from_csv(p)

    universe = sorted({s for s in focus_syms + master_syms + board_syms if SYMBOL_RE.match(s)})
    focus = sorted({s for s in focus_syms if SYMBOL_RE.match(s)})

    with open(a.out_universe, "w", encoding="utf-8") as fh:
        fh.write("\n".join(universe) + ("\n" if universe else ""))
    with open(a.out_focus, "w", encoding="utf-8") as fh:
        fh.write("\n".join(focus) + ("\n" if focus else ""))

    src = "+".join(["focus"] + (["master"] if master_syms else []) + (["17"] if board_syms else []))
    print(f"[universe] {len(universe)} names (focus {len(focus)} + master {len(master_syms)} + "
          f"17 {len(board_syms)}) from {src} ({prevdate}) -> {a.out_universe}", file=sys.stderr)
    if not board_syms:
        print("[universe] the cron #17 boards were MISSING — the union is narrower than it "
              "should be; say so in the artifact", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
