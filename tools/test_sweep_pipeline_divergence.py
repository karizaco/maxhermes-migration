#!/usr/bin/env python3
"""Hermetic regression test for cron #09's DIVERGENCE PROSE.

Measured 2026-11-20: the sentence printed under the breadth-divergence band
was unconditional — it read "the average large cap is materially healthier
than the index" under EVERY band. The 2026-11-20 artifact published
"band MATCHED" over a +14.94 pp divergence and the sentence directly
underneath contradicted its own label; a NARROW divergence (the average name
WEAKER than the index) would have been described with the opposite sentence.

The band itself is a published rule and is NOT changed here: BROAD at or above
+15 pp, NARROW at or below -15 pp, MATCHED in between. Only the EXPLANATION
now follows the band it is attached to — the same house pattern as
`_size_cut_note()` (a cell states a derived fact, never a hardcoded one).

Checks (offline, no network):
  1. BROAD says the average large cap is healthier, and never says WEAKER
  2. NARROW says the average large cap is WEAKER
  3. MATCHED says the two are in the same posture, and names the threshold
  4. the renderer no longer carries the unconditional sentence

Run:  python3 tools/test_sweep_pipeline_divergence.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import sweep_pipeline as P  # noqa: E402


def _check(label, fn):
    try:
        fn()
    except AssertionError as exc:
        print(f"  FAIL  {label}: {exc}")
        return False
    except Exception as exc:  # noqa: BLE001
        print(f"  FAIL  {label}: unexpected {type(exc).__name__}: {exc}")
        return False
    print(f"  PASS  {label}")
    return True


def check_broad():
    note = P._divergence_note("BROAD", 21.0)
    assert "healthier" in note, f"BROAD must say the average cap is healthier: {note}"
    assert "WEAKER" not in note, f"BROAD must not carry the NARROW wording: {note}"


def check_narrow():
    note = P._divergence_note("NARROW", -18.0)
    assert "WEAKER" in note, f"NARROW must say the average cap is weaker: {note}"
    assert "healthier" not in note, f"NARROW must not carry the BROAD wording: {note}"


def check_matched():
    note = P._divergence_note("MATCHED", 14.94)
    assert "same posture" in note, f"MATCHED must state the matched posture: {note}"
    assert "15 pp" in note, f"MATCHED must name the threshold it sits inside: {note}"
    assert "healthier" not in note and "WEAKER" not in note, (
        f"MATCHED must not claim either direction: {note}"
    )


def check_renderer_has_no_unconditional_prose():
    src = Path(P.__file__).resolve().read_text(encoding="utf-8")
    bad = ("means the average large cap is materially healthier than the index"
           in src)
    assert not bad, (
        "the renderer still carries the unconditional divergence sentence - the "
        "explanation must be derived from the band"
    )


def main() -> int:
    print("test_sweep_pipeline_divergence — cron #09's divergence prose")
    results = [
        _check("BROAD says the average cap is healthier", check_broad),
        _check("NARROW says the average cap is weaker", check_narrow),
        _check("MATCHED states the matched posture and the threshold",
               check_matched),
        _check("the renderer carries no unconditional divergence sentence",
               check_renderer_has_no_unconditional_prose),
    ]
    passed = sum(results)
    print(f"\n{passed}/{len(results)} checks passed")
    if passed != len(results):
        print("FAILED")
        return 1
    print("All checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
