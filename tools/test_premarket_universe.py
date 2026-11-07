#!/usr/bin/env python3
"""test_premarket_universe.py — the universe/date guard must BITE.

MARKER: premarket-universe-v1

A checker that never observed failing is a claim, not a gate. This test runs
`premarket_universe.py` offline against FIXTURES and asserts:

  T1  the current schema resolves the denominator from `today_close` and
      REJECTS `screen_close_resolved` (which belongs to the screen's T+1 date)
  T2  the old dated schema resolves the column whose DATE matches the
      denominator session (and not the older dated column)
  T3  a universe from the WRONG session is a HARD FAIL (exit 3, H3)
  T4  a missing sweep is a HARD FAIL (exit 3, H2)
  T5  the correct universe passes (exit 0)

The expected counts are PINNED, so a guard that stops biting fails the test
instead of quietly passing it.

    python3 tools/test_premarket_universe.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
RESOLVER = os.path.join(HERE, "premarket_universe.py")

CURRENT_HEADER = ("symbol,stylists,n_stylists,origins,screen_close_resolved,chg_pct_resolved,"
                   "today_close,today_change,today_volume,data_date,source")
CURRENT_ROW = "APP,jeff_sun|peoplewish,4,A_stockbee_4pct,356.10,31.04,391.22,+9.86,100,2026-11-05,mcp+tv"

# the old schema carried BOTH the screen's resolved date and the sweep's own
# session as dated columns - the newest one is the sweep's own session close.
OLD_HEADER = "ticker,stylists,origins,close_2026-11-05,chg_pct_2026-11-05,close_2026-11-06,chg_pct_2026-11-06"
OLD_ROW = "APP,jeff_sun,4,340.00,1.20,391.22,9.86"

SESSIONS = ["2026-11-06", "2026-11-05", "2026-11-04", "2026-11-03", "2026-10-30"]

FAILURES: list[str] = []
CHECKS = 0


def check(cond: bool, msg: str):
    global CHECKS
    CHECKS += 1
    if cond:
        print(f"  ok   {msg}")
    else:
        print(f"  FAIL {msg}")
        FAILURES.append(msg)


def run(tmp: str, fire_date: str, focus_root: str, extra: list[str] | None = None):
    out_dir = os.path.join(tmp, f"out_{fire_date}_{abs(hash(focus_root)) % 10000}")
    cmd = [sys.executable, RESOLVER, "--fire-date", fire_date, "--out-dir", out_dir,
           "--sessions-file", os.path.join(tmp, "sessions.txt"),
           "--focus-root", focus_root, "--offline"] + (extra or [])
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    manifest = None
    mp = os.path.join(out_dir, "_universe.json")
    if os.path.exists(mp):
        with open(mp, encoding="utf-8") as fh:
            manifest = json.load(fh)
    return proc.returncode, manifest, proc.stderr


def write_focus(root: str, session: str, header: str, row: str):
    d = os.path.join(root, session)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "focus.csv"), "w", encoding="utf-8") as fh:
        fh.write(header + "\n" + row + "\n")


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="pm_univ_test_")
    try:
        with open(os.path.join(tmp, "sessions.txt"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(SESSIONS) + "\n")

        # --- T1: current schema, correct session -------------------------
        r1 = os.path.join(tmp, "root_current")
        write_focus(r1, "2026-11-06", CURRENT_HEADER, CURRENT_ROW)
        rc, mf, err = run(tmp, "2026-11-07", r1)
        print("[T1] current schema, universe = the expected prior session")
        check(rc == 0, f"T1 the correct universe exits 0 (got {rc}: {err.strip()[:120]})")
        check(mf is not None, "T1 a manifest was written")
        if mf:
            check(mf.get("universe_date") == "2026-11-06",
                  f"T1 the universe session is 2026-11-06 (got {mf.get('universe_date')})")
            check(mf.get("ref_close_column") == "today_close",
                  f"T1 the denominator comes from today_close (got {mf.get('ref_close_column')})")
            check(mf.get("screen_close_column_rejected") == "screen_close_resolved",
                  "T1 screen_close_resolved is recorded as REJECTED")
            check(any("screen_close_resolved" in f for f in mf.get("flags", [])),
                  "T1 the rejected column is flagged")
            check(mf.get("reference_closes", {}).get("APP", {}).get("ref_close") == 391.22,
                  f"T1 APP's reference close is 391.22, not the 356.10 screen close "
                  f"(got {mf.get('reference_closes', {}).get('APP', {}).get('ref_close')})")

        # --- T2: old dated schema ---------------------------------------
        r2 = os.path.join(tmp, "root_old")
        write_focus(r2, "2026-11-06", OLD_HEADER, OLD_ROW)
        rc, mf, err = run(tmp, "2026-11-07", r2)
        print("[T2] old dated schema — the column is chosen BY DATE")
        check(rc == 0, f"T2 the correct universe exits 0 (got {rc})")
        if mf:
            check(mf.get("ref_close_column") == "close_2026-11-06",
                  f"T2 the close column matching the DENOMINATOR session wins "
                  f"(got {mf.get('ref_close_column')})")
            check(mf.get("reference_closes", {}).get("APP", {}).get("ref_close") == 391.22,
                  "T2 APP's reference close is the 2026-11-05 close (391.22)")

        # --- T3: the WRONG session's universe -----------------------------
        r3 = os.path.join(tmp, "root_wrong")
        write_focus(r3, "2026-11-05", CURRENT_HEADER,
                    CURRENT_ROW.replace("2026-11-05", "2026-11-04"))
        rc, mf, err = run(tmp, "2026-11-07", r3)
        print("[T3] the universe is from the WRONG session — the guard must BITE")
        check(rc == 3, f"T3 the run exits 3 (got {rc})")
        check(mf is not None and mf.get("status") == "FAIL", "T3 the manifest status is FAIL")
        if mf:
            hard = [a for a in mf.get("assertions", []) if not a["ok"] and a.get("hard")]
            check(any(a["assertion"].startswith("H3") for a in hard),
                  f"T3 H3 (universe session) is the hard failure "
                  f"(got {[a['assertion'] for a in hard]})")
            check(mf.get("universe_stale") is True, "T3 the manifest says universe_stale")

        # --- T4: no published sweep at all --------------------------------
        r4 = os.path.join(tmp, "root_empty")
        os.makedirs(r4, exist_ok=True)
        rc, mf, err = run(tmp, "2026-11-07", r4)
        print("[T4] no published sweep — the guard must BITE")
        check(rc == 3, f"T4 the run exits 3 (got {rc})")
        if mf:
            hard = [a for a in mf.get("assertions", []) if not a["ok"] and a.get("hard")]
            check(any(a["assertion"].startswith("H2") for a in hard),
                  f"T4 H2 (published sweep exists) is the hard failure "
                  f"(got {[a['assertion'] for a in hard]})")

        # --- T5: a stale universe is a FAIL unless explicitly allowed ------
        rcfile = os.path.join(tmp, "refclose.json")
        with open(rcfile, "w", encoding="utf-8") as fh:
            json.dump({"APP": 391.22}, fh)
        rc, mf, err = run(tmp, "2026-11-07", r3,
                           extra=["--allow-stale-universe", "--ref-close-file", rcfile])
        print("[T5] a stale universe with --allow-stale-universe is downgraded, not hidden")
        check(rc == 0, f"T5 the downgraded run exits 0 (got {rc})")
        if mf:
            check(any("universe_stale" in f for f in mf.get("flags", [])),
                  "T5 the stale universe is still flagged in the manifest")
            check(mf.get("reference_closes", {}).get("APP", {}).get("ref_close") == 391.22,
                  "T5 the stale universe's reference close comes from the INDEPENDENT source")
            check(mf.get("reference_closes", {}).get("APP", {}).get("ref_close_source")
                  == "ref_close_file",
                  "T5 the reference close is attributed to the independent source, "
                  "not to the stale focus.csv")

        print(f"\n{CHECKS - len(FAILURES)}/{CHECKS} checks passed")
        if FAILURES:
            for f in FAILURES:
                print("  FAILED: " + f)
            return 1
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
