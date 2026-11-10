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

AND THE COLUMN MUST NOT BE THE CAPTURE CLOCK AT ALL. `ts` is when the SCRIPT RAN, not
when the news broke, so publishing it in "When it broke" asserts that the catalyst broke
when the script ran. Measured on the 2026-11-09 09:50 checkpoint: ARWR (-16.59%) carried
Arrowhead's 2026-01-06 press release — "stock surging 17.81% to a new 52-week high", a
story about the opposite move from ten months earlier — and the board printed "09:53:48"
for it. The column now reads the tape's `news_date`, then the trending snapshot's own
stamp, and otherwise prints an em-dash: an unknown break time is the truth, a clock
would be a lie.

This test:
  1. builds a synthetic tape carrying BOTH timestamp shapes and a dated catalyst,
  2. renders the digest and requires every displayed time to be the ET wall clock,
  3. requires the dated catalyst to show its NEWS date and the undated one to show an
     em-dash — never the capture clock,
  4. requires the render to be REPRODUCIBLE from the tape (the board never disagrees
     with the data cron #17 reads),
  5. then MUTATES the renderer back to the string-slice behaviour, and back to the
     capture-clock fallback, and requires the test to FAIL each time — a test that
     cannot fail is not a test.

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
    # A GROUNDED catalyst with a date: the board must show THAT date, in ET.
    {"ts": "2026-11-10T09:57:44" + ET_OFFSET, "ticker": "AAON", "name": "AAON Inc",
     "pct": 24.07, "price": 78.0, "src": "pipeworx", "cat": "earnings",
     "why": "AAON reported Q3 earnings beating the consensus estimate",
     "conf": "high", "trending_ts": None, "trending_score": None,
     "volume": 900000, "exchange": "NASDAQ", "ref": "http://example.test/x",
     "news_date": "2026-11-10T11:30:00Z", "news_url": "http://example.test/aaon",
     "halted": None},
    # A GROUNDED catalyst with NO date: the board must show an em-dash, and must NOT
    # fall back to the capture clock. This is the ARWR row.
    {"ts": "2026-11-10T09:57:44" + ET_OFFSET, "ticker": "ZZZZ", "name": "Undated Inc",
     "pct": -12.5, "price": 31.0, "src": "pipeworx", "cat": "other",
     "why": "an undated cause, which is a weaker claim and not a false one",
     "conf": "low", "trending_ts": None, "trending_score": None,
     "volume": 800000, "exchange": "NASDAQ", "ref": None,
     "news_date": None, "news_url": None,
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

    # The DATED catalyst shows its NEWS date, in ET: 11:30:00Z is 06:30:00 ET.
    check("06:30:00" in board, "the dated catalyst shows its news date in ET")
    check("11:30:00" not in board, "the news date is NOT published as if it were ET")

    # The UNDATED catalyst shows an em-dash — and NEVER the capture clock.
    check("09:57:44" not in board,
          "the capture clock is NEVER published as the break time")
    undated_row = [ln for ln in board.splitlines() if ln.startswith("| ZZZZ |")]
    check(bool(undated_row), "the undated catalyst appears in the table")
    if undated_row:
        cells = [c.strip() for c in undated_row[0].strip("|").split("|")]
        check(cells[4] == "\u2014",
              f"the undated catalyst shows an em-dash, not a clock (got {cells[4]!r})")

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

    # The OTHER mutation: the renderer falls back to the capture clock again. That is
    # the ARWR defect - a January press release dated 09:53:48.
    mutated2 = Path(td) / "mutated_digest2.py"
    mutated2.write_text(
        DG_PATH.read_text(encoding="utf-8").replace(
            'broke = r.get("news_date") or r.get("trending_ts") or ""',
            'broke = r.get("news_date") or r.get("trending_ts") or r.get("ts")'),
        encoding="utf-8")
    if mutated2.read_text(encoding="utf-8") == DG_PATH.read_text(encoding="utf-8"):
        check(False, "the capture-clock mutation actually changed the renderer")
    else:
        check(True, "the capture-clock mutation actually changed the renderer")
        with tempfile.TemporaryDirectory() as td2:
            t2 = Path(td2) / "2026-11-10-0950.jsonl"
            o2 = Path(td2) / "2026-11-10-0950.md"
            with t2.open("w", encoding="utf-8") as fh:
                for r in ROWS:
                    fh.write(json.dumps(r) + "\n")
            subprocess.run(
                [sys.executable, str(mutated2), "--tape", str(t2), "--out", str(o2),
                 "--date", "2026-11-10", "--slot", "0950"],
                capture_output=True, text=True)
            b2 = o2.read_text(encoding="utf-8")
            # The guard's own condition, evaluated against the mutated board.
            # It PASSES on the real board (asserted above) and must be VIOLATED here,
            # which is what makes it a guard rather than a decoration.
            guard_ok = ("09:57:44" not in b2)
            check(not guard_ok,
                  "the guard's no-capture-clock condition is VIOLATED by the mutated "
                  "renderer — the guard bites")
            check("09:57:44" in b2,
                  "the mutated renderer reproduces the capture-clock defect verbatim")

print()
if FAILURES:
    print(f"FAILED ({len(FAILURES)}):")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("PASS — the digest renders ET for both timestamp shapes, and the guard bites.")
