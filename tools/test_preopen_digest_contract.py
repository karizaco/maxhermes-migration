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
  5. requires the board to PUBLISH the GATED MOVER COVERAGE (the published movers that
     carry a catalyst / the published movers / percent) — the number the READER's table
     is judged by — with the whole-tape coverage published separately as CONTEXT, and to
     DEGRADE loudly when the gated number falls below the 50% floor,
  6. then MUTATES the renderer back to the string-slice behaviour, and back to the
     capture-clock fallback, and back to a renderer that drops the coverage, and requires
     the test to FAIL each time — a test that cannot fail is not a test.

USAGE
    python3 tools/test_preopen_digest_contract.py
Exit codes: 0 = all good; 1 = the renderer mis-renders a time, or the guard cannot bite.
"""

import importlib.util
import json
import re
import shutil
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

    # 5. The MOVER COVERAGE FLOOR: the board measures the coverage of the MOVERS IT
    #    PUBLISHES, publishes it, and DEGRADES loudly when it is below the floor.
    #
    #    The reader does not read 164 tape records; the reader reads the table on the
    #    board. Measured on Friday 2026-11-13 under this metric: 4 of the 15 published
    #    movers carried a catalyst at 08:30 (27%) and 6 of 15 at 09:50 (40%) — both
    #    below the floor. A board that measures its coverage and stays quiet is the
    #    same failure with a number attached.
    print("\n5. the board publishes the GATED mover coverage")
    m_mv = re.search(r"\*\*mover coverage:\*\*\s*(\d+)\s*/\s*(\d+)\s*\((\d+)%\)", board)
    check(m_mv is not None, "the board publishes the gated mover-coverage line")
    if m_mv is not None:
        pub = [r for r in ROWS if r.get("pct") is not None]
        named = sum(1 for r in pub if r.get("why"))
        check(m_mv.group(1) == str(named) and m_mv.group(2) == str(len(pub)),
              f"the gated line's arithmetic is read from the PUBLISHED MOVERS "
              f"(got {m_mv.group(1)}/{m_mv.group(2)}, expected {named}/{len(pub)})")
        check(m_mv.group(3) == "100",
              f"the gated percentage is published (got {m_mv.group(3)}%)")
    # THE WHOLE-TAPE COVERAGE IS CONTEXT, and it is published separately.
    m_ctx = re.search(r"\*\*catalyst coverage \(whole tape\):\*\*\s*(\d+)\s*/\s*"
                       r"(\d+)\s*\((\d+)%\)", board)
    check(m_ctx is not None, "the board publishes the whole-tape coverage as CONTEXT")
    if m_ctx is not None:
        whole_named = sum(1 for r in ROWS if r.get("why"))
        check(m_ctx.group(1) == str(whole_named) and m_ctx.group(2) == str(len(ROWS)),
              f"the whole-tape context line's arithmetic matches the tape "
              f"(got {m_ctx.group(1)}/{m_ctx.group(2)}, expected {whole_named}/{len(ROWS)})")
        check("CONTEXT ONLY" in board,
              "the board says the whole-tape number is CONTEXT, not the gate")
    check("preopen-coverage-v2" in board,
          "the board carries the coverage contract marker")
    check("**floor:** 50%" in board, "the board publishes the floor it was measured against")
    check("DEGRADED" not in board,
          "a board AT the floor carries NO degradation banner")

    # A board BELOW the floor: 10 priced rows, 1 explained, 2 narrative rows that do
    # carry a reason -> 3 of 12 records named (25%), well under the 40% floor.
    LOW_ROWS = []
    for i in range(10):
        pct = round(20.0 - i * 1.5, 2) if i % 2 == 0 else round(-(20.0 - i * 1.5), 2)
        LOW_ROWS.append({
            "ts": "2026-11-13T08:47:31-05:00", "src": "pipeworx" if i == 0 else "scanner",
            "ticker": f"L{i:02d}", "name": f"Low {i} Inc", "pct": pct, "price": 10.0 + i,
            "cat": "earnings" if i == 0 else "other",
            "why": "reported Q3 results, beat and raised" if i == 0 else None,
            "ref": "https://example.test/x" if i == 0 else None,
            "conf": "high" if i == 0 else "low",
            "trending_ts": None, "trending_score": None, "volume": 1234567,
            "exchange": "NASDAQ",
            "news_date": "2026-11-13T11:30:00Z" if i == 0 else None,
            "news_url": "https://news.example.test/l0" if i == 0 else None,
            "pm_notional": 1234567.0, "sign_conflict": False,
        })
    for i in range(2):
        LOW_ROWS.append({
            "ts": "2026-11-13T08:47:31-05:00", "src": "stocktwits", "ticker": f"N{i:02d}",
            "name": f"Narrative {i} Inc", "pct": None, "price": None, "cat": "other",
            "why": f"retail chatter about a catalyst ({i})", "ref": None, "conf": "low",
            "trending_ts": "2026-11-13T08:17:43-05:00", "trending_score": 5.2,
            "volume": None, "exchange": None, "news_date": None, "news_url": None,
            "pm_notional": None, "sign_conflict": False,
        })
    with tempfile.TemporaryDirectory() as td3:
        t3 = Path(td3) / "2026-11-13-0830.jsonl"
        o3 = Path(td3) / "2026-11-13-0830.md"
        with t3.open("w", encoding="utf-8") as fh:
            for r in LOW_ROWS:
                fh.write(json.dumps(r) + "\n")
        subprocess.run(
            [sys.executable, str(DG_PATH), "--tape", str(t3), "--out", str(o3),
             "--date", "2026-11-13", "--slot", "0830"],
            capture_output=True, text=True)
        low = o3.read_text(encoding="utf-8")

        print("\n6. a board BELOW the floor says so, in the file a reader opens")
        # 10 published movers, 1 explained -> 1/10 = 10%, and the 2 narrative rows
        # (which are not movers) are NOT in the denominator.
        m_low = re.search(r"\*\*mover coverage:\*\*\s*(\d+)\s*/\s*(\d+)\s*\((\d+)%\)", low)
        check(m_low is not None, "the low-coverage board publishes its gated coverage")
        if m_low is not None:
            check(m_low.group(1) == "1" and m_low.group(2) == "10",
                  f"the low-coverage arithmetic is right (got {m_low.group(1)}/"
                  f"{m_low.group(2)}, expected 1/10)")
            check(m_low.group(3) == "10", f"the low-coverage percentage is right "
                                          f"(got {m_low.group(3)}%)")
        # The WHOLE-TAPE context is still published - 3 of 12 records named - and it
        # is NOT the gate: 25% of the tape and 10% of the published movers.
        m_low_ctx = re.search(r"\*\*catalyst coverage \(whole tape\):\*\*\s*(\d+)\s*/\s*"
                              r"(\d+)\s*\((\d+)%\)", low)
        check(m_low_ctx is not None,
              "the low-coverage board still publishes the whole-tape coverage as CONTEXT")
        if m_low_ctx is not None:
            check(m_low_ctx.group(1) == "3" and m_low_ctx.group(2) == "12",
                  f"the whole-tape context arithmetic is right (got {m_low_ctx.group(1)}/"
                  f"{m_low_ctx.group(2)}, expected 3/12)")
        check("DEGRADED" in low,
              "a board BELOW the floor carries the DEGRADED banner")
        check(re.search(r"below the 50% floor", low) is not None,
              "the banner says WHICH floor it fell below")
        check(re.search(r"priced but unexplained", low) is not None,
              "the banner says it in plain words (priced but unexplained)")
        check(re.search(r"grounded catalyst call", low) is not None,
              "the banner NAMES THE CAUSE")
        check("Unexplained movers in the published table" in low,
              "the banner names the UNEXPLAINED MOVERS it publishes")
        unexplained_line = next((ln for ln in low.splitlines()
                                 if "Unexplained movers in the published table" in ln), "")
        check(bool(unexplained_line), "the board LISTS the unexplained published movers")
        if unexplained_line:
            missing = [r["ticker"] for r in LOW_ROWS
                       if not r.get("why") and r.get("pct") is not None
                       and r["ticker"] not in unexplained_line]
            check(not missing,
                  f"every unexplained published mover is in the list (missing {missing[:5]})")
        check("**BELOW FLOOR**" in low,
              "the coverage line states the floor verdict")

        # 7. The guards must bite: a renderer that stops publishing the coverage,
        #    and one that stops DEGRADING.
        print("\n7. the coverage guards bite (fault injection)")
        for label, old, new, guard in (
            ("the renderer stops publishing the coverage line",
             "**mover coverage:**", "**mover pct:**",
             lambda b: "**mover coverage:**" not in b),
            ("the renderer stops degrading a below-floor board",
             "**DEGRADED — mover coverage", "**NOTE — mover coverage",
             lambda b: "DEGRADED" not in b),
        ):
            src = DG_PATH.read_text(encoding="utf-8")
            if old not in src:
                check(False, f"the mutation target for '{label}' is missing")
                continue
            mpath = Path(td3) / "mutated_cov.py"
            mpath.write_text(src.replace(old, new), encoding="utf-8")
            mt = Path(td3) / "mutated_tape.jsonl"
            mo = Path(td3) / "mutated_out.md"
            shutil.copyfile(t3, mt)
            subprocess.run(
                [sys.executable, str(mpath), "--tape", str(mt), "--out", str(mo),
                 "--date", "2026-11-13", "--slot", "0830"],
                capture_output=True, text=True)
            mb = mo.read_text(encoding="utf-8")
            check(guard(mb),
                  f"the guard is VIOLATED by {label} — the guard bites")

print()
if FAILURES:
    print(f"FAILED ({len(FAILURES)}):")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("PASS — the digest renders ET for both timestamp shapes, and the guard bites.")
