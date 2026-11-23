#!/usr/bin/env python3
"""Offline test for the volatility pair's provenance label.

The bug this guards (measured on cron #10, 2026-11-23): `breadth_metrics.py` labelled the
pinned volatility pair a "replay — the live print is no longer available" whenever a fire
clock was supplied — including on an ON-TIME LIVE fire, where the pinned bar WAS the live
print. The published artifact would have told the reader the tape was a reconstruction
when it was not.

The label is now derived from the feed: the pair is a replay only when the feed carries a
LATER bar for that session than the pinned one. This test asserts all three branches, with
no network access.

Usage:  python scripts/test_breadth_session_mode.py
Exit:   0 = all passed, 1 = a failure.
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))

import breadth_metrics as bm  # noqa: E402

PASS = "PASS"
FAIL = "FAIL"


def main() -> int:
    failures = 0

    def check(ok: bool, label: str, detail: str = "") -> None:
        nonlocal failures
        if not ok:
            failures += 1
        line = f"  {PASS if ok else FAIL}  {label}"
        if detail:
            line += f"   {detail}"
        print(line)

    clock = datetime.time(14, 0, 5)
    pinned = datetime.datetime(2026, 11, 23, 13, 45)
    later = datetime.datetime(2026, 11, 23, 13, 50)

    live = bm._vix_session_mode("5m", clock, pinned, pinned)
    check(live.startswith("regular hours"),
          "an on-time live fire is NOT labelled a replay", live)
    check("no longer" not in live,
          "a live pull does not claim the print is unavailable", live)

    replay = bm._vix_session_mode("5m", clock, pinned, later)
    check(replay.startswith("replay"),
          "a fire whose pinned bar has later bars in the feed IS a replay", replay)

    daily = bm._vix_session_mode("1d", clock, pinned, pinned)
    check(daily.startswith("daily bar"),
          "the daily-bar fallback says so instead of claiming a replay", daily)

    unpinned = bm._vix_session_mode("5m", None, pinned, later)
    check(unpinned.startswith("regular hours"),
          "no fire clock means a plain live print", unpinned)

    print(f"\n{'PASS' if failures == 0 else 'FAIL'}: {4 - failures}/4 session-mode checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
