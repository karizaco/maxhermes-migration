#!/usr/bin/env python3
"""
test_preopen_capture_coverage.py — prove the MOVER COVERAGE FLOOR can be CLEARED.

WHY THIS FILE EXISTS
--------------------
The floor that shipped on 2026-11-13 gated the WHOLE TAPE at 40%. On a 164-row tape
that needed 66 explained rows while the catalyst pool could supply at most ~20, so the
floor could NEVER be cleared: every checkpoint would have been labelled DEGRADED,
forever. A gate that can only fail is not a gate - it is a ratchet, and a ratchet that
fires on every fire trains the reader to ignore the label.

So the metric is now the READER-FACING one - the coverage of the MOVERS THE BOARD
PUBLISHES - with a floor of 50%: a 15-row movers table needs 8 explained movers
(7/15 = 46.7% is below it, 8/15 = 53.3% clears it).

THIS FILE PROVES THE FLOOR IS REACHABLE, by driving the REAL capture code with the
PROVIDER CALLS STUBBED:

  1. THE HEALTHY CASE - a day where the catalyst budget lands on the movers the board
     publishes. The gated metric clears 50%, the capture counts NO degradation error,
     and the rendered board carries NO banner. A gate that can only fail is a wish.
  2. THE DEGRADED CASE - Friday's shape (the movers priced, most of them unexplained).
     The gated metric falls below the floor, the capture counts the degradation EXACTLY
     ONCE, and the board carries the DEGRADED banner with the unexplained movers named.
  3. THE NO-MOVERS CASE - a tape with nothing priced in it. The metric is UNDEFINED
     (there is no movers table), so the checkpoint is degraded: a checkpoint that cannot
     show an explained mover cannot claim coverage.

Nothing here touches the network: every provider call is stubbed, and the capture's own
build() / main() and the digest's own render() do the work.

USAGE
    python3 tools/test_preopen_capture_coverage.py

EXIT CODES
    0 = the floor clears on a healthy day, fires on a bad one, and is counted once
    1 = any of those is false
"""

import datetime
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CAP_PATH = ROOT / "cloud-prompts" / "_shared" / "preopen_capture.py"
DG_PATH = ROOT / "cloud-prompts" / "_shared" / "preopen_digest.py"

FAILURES = []


def check(cond, msg):
    if cond:
        print(f"  ok   {msg}")
    else:
        print(f"  FAIL {msg}")
        FAILURES.append(msg)
    return bool(cond)


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# THE STUBBED PROVIDER CALLS. The shapes mirror what the real ones return.
# ---------------------------------------------------------------------------

def stub_band(rows):
    """call_scanner_band() -> the pre-market band: today's movers, priced."""
    up = sum(1 for r in rows.values() if (r.get("pct") or 0) > 0)
    down = sum(1 for r in rows.values() if (r.get("pct") or 0) < 0)
    return {"rows": rows, "up": up, "down": down, "total": len(rows), "truncated": []}


def band_rows(n, top_pct=30.0, step=1.7):
    """n movers, |pct| descending - so the top 15 by |%| are the first 15."""
    out = {}
    for i in range(n):
        pct = round(top_pct - i * step, 2) if i % 2 == 0 else round(-(top_pct - i * step), 2)
        out[f"M{i:02d}"] = {"pct": pct, "price": round(10.0 + i, 2),
                             "volume": 1_000_000, "name": f"Mover {i} Inc",
                             "exchange": "NASDAQ"}
    return out


def catalyst_set(tickers, cutoff):
    """A dated, in-window, checkable catalyst for each of `tickers`."""
    out = {}
    for tk in tickers:
        out[tk] = {"why": "the company issued a press release today",
                   "date": cutoff.astimezone(datetime.timezone.utc)
                            .isoformat().replace("+00:00", "Z"),
                   "url": f"https://news.example.test/{tk}",
                   "conf": "high", "src": "pipeworx", "tool": "polygon_io_news",
                   "origin": "article", "ref": f"https://news.example.test/{tk}",
                   "error": None, "sentiment": None}
    return out


def install_stubs(cap, band, explained):
    """Point every provider call at a stub. `explained` = the tickers that get a cause."""
    cap.call_trending = lambda: {"rows": []}
    cap.call_top_movers = lambda category="gainers": {"movers": {}, "as_of": None,
                                                       "total": 0}
    cap.call_scanner_band = lambda *a, **k: stub_band(band)
    cap.call_scanner_premarket = lambda syms: {"rows": {}, "total": 0,
                                               "requested": len(syms)}

    def fake_resolve(pool, cutoff, budget, names=None, pcts=None):
        # The provider answers for the names it has news about; the rest come back
        # empty. The POOL is the budget, and it is ranked by |%| - the same order the
        # board publishes its table in.
        want = [t for t in pool if t in explained]
        return catalyst_set(want, cutoff)

    cap.resolve_catalysts = fake_resolve
    return cap


def run_capture(cap, tmp, band, explained, date_str):
    """Run the REAL main() with the stubs installed. Returns (tape, board, stdout)."""
    install_stubs(cap, band, explained)
    feed = os.path.join(tmp, "preopen-feed")
    os.makedirs(feed, exist_ok=True)
    tape = os.path.join(feed, f"{date_str}-0830.jsonl")
    board = os.path.join(feed, f"{date_str}-0830.md")
    argv = sys.argv
    env_key = os.environ.get("PIPEWORX_API_KEY")
    sys.argv = ["preopen_capture.py", "--date", date_str, "--checkpoint", "0830",
                "--out", tape, "--top", "20"]
    os.environ["PIPEWORX_API_KEY"] = "stub-key"
    try:
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cap.main()
    finally:
        sys.argv = argv
        if env_key is None:
            os.environ.pop("PIPEWORX_API_KEY", None)
        else:
            os.environ["PIPEWORX_API_KEY"] = env_key
    out = buf.getvalue()
    proc = subprocess.run(
        [sys.executable, str(DG_PATH), "--tape", tape, "--out", board,
         "--date", date_str, "--slot", "0830"], capture_output=True, text=True)
    return tape, board, out, rc, proc


def coverage_errors(errors):
    return [e for e in errors if "mover_coverage_below_floor" in str(e)]


def main():
    cap = _load(CAP_PATH, "cap")
    today = datetime.datetime.now().strftime("%Y-%m-%d")

    # ------------------------------------------------------------------
    # 1. THE HEALTHY CASE - the floor CAN be cleared.
    # ------------------------------------------------------------------
    print("1. the healthy case: the budget lands on the movers the board publishes")
    # 25 movers on the tape, the 10 biggest explained. The board publishes the top 15,
    # so the gated metric is 10/15 = 67% - and the WHOLE TAPE is 10/25 = 40%, BELOW
    # the floor. The gate is on the READER'S TABLE, and this proves it.
    band = band_rows(25)
    explained = {f"M{i:02d}" for i in range(10)}      # the 10 biggest movers
    with tempfile.TemporaryDirectory() as td:
        tape, board_path, out, rc, proc = run_capture(cap, td, band, explained, today)
        check(rc == 0, f"the capture's main() exits 0 (got {rc})")
        check(os.path.exists(tape), "the capture wrote the tape")
        board = open(board_path, encoding="utf-8").read() if os.path.exists(board_path) else ""
        rows = [json.loads(l) for l in open(tape, encoding="utf-8").read().splitlines()
                if l.strip()]
        # the metric, recomputed from what the capture wrote
        from_cap = None
        m = re.search(r"mover_coverage=(\d+)/(\d+)\s+\((\d+)%", out)
        if m:
            from_cap = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
        check(from_cap is not None, "the capture prints the gated mover coverage")
        if from_cap:
            check(from_cap[0] == 10 and from_cap[1] == 15,
                  f"the healthy case explains 10 of the 15 published movers "
                  f"(got {from_cap[0]}/{from_cap[1]})")
            check(from_cap[2] >= 50,
                  f"the healthy case CLEARS the 50% floor (got {from_cap[2]}%)")
        check("mover_coverage_degraded=no" in out,
              "the capture does NOT report a degradation on a healthy run")
        m_line = re.search(r"\*\*mover coverage:\*\*\s*(\d+)\s*/\s*(\d+)\s*\((\d+)%\)", board)
        check(m_line is not None, "the board publishes the gated mover coverage")
        if m_line:
            check((int(m_line.group(1)), int(m_line.group(2))) == (10, 15),
                  f"the board's gated line matches the capture's "
                  f"({m_line.group(1)}/{m_line.group(2)} vs 10/15)")
        check("DEGRADED" not in board,
              "a healthy board carries NO degradation banner")
        check("AT OR ABOVE THE FLOOR" in board,
              "the healthy board states its verdict")
        # THE WHOLE TAPE is below the floor here, and it does not matter: the gate is
        # on the movers the board publishes.
        m_ctx = re.search(r"\*\*catalyst coverage \(whole tape\):\*\*\s*(\d+)\s*/\s*"
                           r"(\d+)\s*\((\d+)%\)", board)
        check(m_ctx is not None, "the healthy board publishes the whole-tape context")
        if m_ctx:
            check(int(m_ctx.group(3)) < 50,
                  f"the whole-tape coverage is BELOW the floor in the healthy case "
                  f"(got {m_ctx.group(3)}%) - the gate is NOT the whole tape")
            check("DEGRADED" not in board,
                  "and the board still carries NO banner: the gate is the reader's table")

    # ------------------------------------------------------------------
    # 2. THE DEGRADED CASE - Friday's shape. The floor FIRES.
    # ------------------------------------------------------------------
    print("\n2. the degraded case: the movers are priced and mostly unexplained")
    band = band_rows(20)
    explained = {f"M{i:02d}" for i in range(4)}       # only the top 4 explained
    with tempfile.TemporaryDirectory() as td:
        tape, board_path, out, rc, proc = run_capture(cap, td, band, explained, today)
        check(rc == 0, f"the capture's main() exits 0 - the floor NEVER suppresses the "
                       f"checkpoint (got {rc})")
        board = open(board_path, encoding="utf-8").read() if os.path.exists(board_path) else ""
        m = re.search(r"mover_coverage=(\d+)/(\d+)\s+\((\d+)%", out)
        check(m is not None, "the capture prints the gated mover coverage")
        if m:
            check((int(m.group(1)), int(m.group(2))) == (4, 15),
                  f"the degraded case explains 4 of the 15 published movers "
                  f"(got {m.group(1)}/{m.group(2)})")
            check(int(m.group(3)) < 50,
                  f"the degraded case is BELOW the 50% floor (got {m.group(3)}%)")
        check("mover_coverage_degraded=yes" in out,
              "the capture reports the degradation")
        check("**BELOW FLOOR**" in board,
              "the board states the floor verdict")
        check("DEGRADED" in board,
              "the degraded board carries the DEGRADED banner")
        check("Unexplained movers in the published table" in board,
              "the degraded board NAMES the unexplained movers it publishes")
        # THE DEGRADATION IS COUNTED EXACTLY ONCE, in the capture's OWN ledger.
        err_line = re.search(r"errors=(\d+)", out)
        check(err_line is not None, "the capture prints its error count")
        # and the ledger itself, through build()
        install_stubs(cap, band, explained)
        res = cap.build(today, "0830", 20)
        cov_errs = coverage_errors(res.get("errors") or [])
        check(len(cov_errs) == 1,
              f"the capture counts the coverage degradation EXACTLY ONCE "
              f"(got {len(cov_errs)})")
        check(res.get("mover_coverage_below_floor") is True,
              "the capture's own ledger marks the run as degraded")
        check(res.get("mover_coverage") is not None
              and abs(res["mover_coverage"] - 4 / 15) < 1e-3,
              f"the capture measures the gated metric "
              f"(got {res.get('mover_coverage')})")
        check(res.get("catalyst_coverage") is not None,
              "the capture still measures the whole-tape coverage - it is CONTEXT")

    # ------------------------------------------------------------------
    # 3. THE NO-MOVERS CASE - the metric is undefined, so the run is degraded.
    # ------------------------------------------------------------------
    print("\n3. the no-movers case: nothing traded pre-market, so there is no table")
    with tempfile.TemporaryDirectory() as td:
        cap2 = _load(CAP_PATH, "cap2")
        install_stubs(cap2, {}, set())
        # a trending-only tape: names with a reason, and NO pre-market print
        cap2.call_trending = lambda: {"rows": [
            {"ticker": f"N{i}", "name": f"Narrative {i}", "why": "retail chatter",
             "ts": "2026-11-13T08:17:43-05:00", "score": 5.0} for i in range(5)]}
        feed = os.path.join(td, "preopen-feed")
        os.makedirs(feed, exist_ok=True)
        tape = os.path.join(feed, f"{today}-0830.jsonl")
        board_path = os.path.join(feed, f"{today}-0830.md")
        argv = sys.argv
        sys.argv = ["preopen_capture.py", "--date", today, "--checkpoint", "0830",
                    "--out", tape, "--top", "20"]
        os.environ["PIPEWORX_API_KEY"] = "stub-key"
        try:
            import io
            import contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = cap2.main()
        finally:
            sys.argv = argv
        out = buf.getvalue()
        check(rc == 0, f"the capture's main() exits 0 (got {rc})")
        proc = subprocess.run(
            [sys.executable, str(DG_PATH), "--tape", tape, "--out", board_path,
             "--date", today, "--slot", "0830"], capture_output=True, text=True)
        res = cap2.build(today, "0830", 20)
        check(res.get("mover_coverage") is None,
              "the gated metric is UNDEFINED when the board publishes no movers table")
        check(res.get("mover_coverage_below_floor") is True,
              "an undefined metric is DEGRADED - a checkpoint that cannot show an "
              "explained mover cannot claim coverage")
        cov_errs = coverage_errors(res.get("errors") or [])
        check(len(cov_errs) == 1,
              f"the undefined metric is counted EXACTLY ONCE (got {len(cov_errs)})")
        if os.path.exists(tape) and os.path.exists(board_path):
            board = open(board_path, encoding="utf-8").read()
            check("**mover coverage:** n/a" in board,
                  "the board publishes 'mover coverage: n/a'")
            check("DEGRADED" in board,
                  "the no-movers board carries the DEGRADED banner")
        else:
            check(False, "the no-movers case produced a tape and a board")

    print()
    if FAILURES:
        print(f"FAILED ({len(FAILURES)}):")
        for f in FAILURES:
            print("  -", f)
        return 1
    print("PASS — the floor CLEARS on a healthy day, FIRES on a bad one, and is counted "
          "exactly once.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
