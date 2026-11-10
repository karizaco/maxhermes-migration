#!/usr/bin/env python3
"""
test_preopen_digest_contract.py — prove the cron #92 digest renders the right clock.

Why
---
The pre-open digest's "When it broke" column is the field cron #17 reads at 15:50 to
date a catalyst: the whole point of the tape is WHO / WHAT / WHEN. Two different
timestamp shapes feed that column and they are NOT the same timezone:

    ts          the capture clock, ET-aware   2026-11-10T09:57:44-05:00
    trending_ts the stocktwits snapshot, UTC   2026-11-10T14:38:21Z

The renderer used to slice [11:19] off both, which printed the UTC stamp as if it were
ET. Measured on the 2026-11-10 09:50 checkpoint: HIMS showed "14:38:21" for news that
actually broke at 09:38:21 ET — five hours late, and stamped in the FUTURE relative to
the capture. A wrong clock here is invisible to a glance, because the number still looks
like a time of day.

This test:
  1. builds a synthetic tape carrying BOTH timestamp shapes,
  2. renders the digest and requires every displayed time to be the ET wall clock,
  3. requires the render to be REPRODUCIBLE from the tape (the board never disagrees
     with the data cron #17 reads),
  4. then MUTATES the renderer back to the string-slice behaviour and requires the
     test to FAIL — a test that cannot fail is not a test.

USAGE
    python3 tools/test_preopen_digest_contract.py
Exit codes: 0 = all good; 1 = the renderer mis-renders a time, or the guard cannot bite.
"""

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DG_PATH = ROOT / "cloud-prompts" / "_shared" / "preopen_digest.py"

ET_OFFSET = "-05:00"  # November = EST


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


dg = _load(DG_PATH, "dg")

FAILURES = []


def check(cond, msg):
    if cond:
        print(f"  ok   {msg}")
    else:
        print(f"  FAIL {msg}")
        FAILURES.append(msg)


# ----------------------------------------------------------------------------------
# 1. The unit under test: a UTC stamp must render as the ET wall clock.
# ----------------------------------------------------------------------------------
print("1. fmt_ts normalises to ET")
check(dg.fmt_ts("2026-11-10T14:38:21Z") == "09:38:21",
      "UTC stamp 14:38:21Z renders as 09:38:21 ET")
check(dg.fmt_ts("2026-11-10T09:57:44" + ET_OFFSET) == "09:57:44",
      "ET-aware capture stamp renders unchanged")
check(dg.fmt_ts("2026-11-10T09:57:44") == "09:57:44",
      "naive stamp is read as ET, never as UTC")
check(dg.fmt_ts(None) == "—", "a missing time renders the em-dash, not a crash")
check(dg.fmt_ts("") == "—", "an empty time renders the em-dash")
check(dg.fmt_ts("not-a-time") == "not-a-time",
      "an unparseable stamp is passed through rather than mangled")

# ----------------------------------------------------------------------------------
# 2. End to end: a tape carrying both shapes must render ET times in the board.
# ----------------------------------------------------------------------------------
print("\n2. the board renders ET for both timestamp shapes")
ROWS = [
    {"ts": "2026-11-10T09:57:44" + ET_OFFSET, "ticker": "HIMS", "name": "Hims & Hers",
     "pct": -9.65, "price": 20.72, "src": "scanner", "cat": "earnings",
     "why": "Hims & Hers shares are under pressure after its Q3 report",
     "conf": "high", "trending_ts": "2026-11-10T14:38:21Z",
     "trending_score": 90.0, "trending_ts_note": None, "volume": 1000000,
     "exchange": "NASDAQ", "ref": None, "halted": None},
    {"ts": "2026-11-10T09:57:44" + ET_OFFSET, "ticker": "AAON", "name": "AAON Inc",
     "pct": 24.07, "price": 78.0, "src": "pipeworx", "cat": "earnings",
     "why": "AAON reported Q3 earnings beating the consensus estimate",
     "conf": "high", "trending_ts": None, "trending_score": None,
     "volume": 900000, "exchange": "NASDAQ", "ref": "http://example.test/x",
     "halted": None},
]

with tempfile.TemporaryDirectory() as td:
    tape = Path(td) / "2026-11-10-0950.jsonl"
    out = Path(td) / "2026-11-10-0950.md"
    with tape.open("w", encoding="utf-8") as fh:
        for r in ROWS:
            fh.write(json.dumps(r) + "\n")
    proc = subprocess.run(
        [sys.executable, str(DG_PATH), "--tape", str(tape), "--out", str(out),
         "--date", "2026-11-10", "--slot", "0950"],
        capture_output=True, text=True)
    check(proc.returncode == 0, f"the renderer exits 0 (got {proc.returncode})")
    board = out.read_text(encoding="utf-8")

    check("09:38:21" in board, "the UTC-sourced row shows its ET break time")
    check("14:38:21" not in board, "the UTC clock is NOT published as if it were ET")
    check("not measurable" in board, "the halt state reads 'not measurable'")
    check("never `0`" in board or "never 0" in board,
          "the halt state is documented as never 0")
    # the capture-clock row
    check("09:57:44" in board, "the ET-aware capture stamp renders unchanged")

    # 3. The board must agree with the tape it was rendered from.
    print("\n3. the board agrees with the tape")
    n = len(ROWS)
    check(f"**records:** {n}" in board,
          "the record count on the board equals the tape's row count")
    for r in ROWS:
        check(f"| {r['ticker']} |" in board, f"{r['ticker']} appears in the table")

    # 4. The guard must bite: mutate the renderer back to the string-slice bug.
    print("\n4. the guard bites (fault injection)")
    mutated = Path(td) / "mutated_digest.py"
    mutated.write_text(
        DG_PATH.read_text(encoding="utf-8").replace(
            'return dt.strftime("%H:%M:%S")',
            'return str(v)[11:19]'), encoding="utf-8")
    m = _load(mutated, "dg_mutated")
    check(m.fmt_ts("2026-11-10T14:38:21Z") != "09:38:21",
          "the mutated (buggy) renderer FAILS the ET assertion — the guard bites")
    check(m.fmt_ts("2026-11-10T14:38:21Z") == "14:38:21",
          "the mutated renderer reproduces the original 5-hour error")

print()
if FAILURES:
    print(f"FAILED ({len(FAILURES)}):")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("PASS — the digest renders ET for both timestamp shapes, and the guard bites.")
