#!/usr/bin/env python3
"""Fault-injection test for the prior-result selection in earnings_reaction_stats.py.

WHY THIS FILE EXISTS (measured 2026-11-06)
--------------------------------------------
Yahoo's `earningsHistory` array is ordered OLDEST-FIRST. The helper's `prior_report_result()`
took the FIRST element, so every published `Prior result` was a YEAR-OLD verdict:

    MRNA  helper said  beat +76.6%  (quarter ended 2025-09-30)
          the latest  beat  +4.3%   (quarter ended 2026-06-30, reported 2026-07-31)
    CHTR  helper said  miss -10.3%  (quarter ended 2025-09-30)
          the latest  beat  +5.9%   (quarter ended 2026-06-30, reported 2026-07-24)

A reader would have been told Charter missed when it beat, and that the verdict was about a
quarter that is four reports old. The fix is `select_latest_report()`.

This test is the guard: it must FAIL against the old behaviour (first element wins) and PASS
against the fix. Every case below is a fault injection, not a smoke test.

Usage:  python3 tools/test_earnings_reaction_prior_result.py
Exit:   0 = every case passed, 1 = at least one case failed.
"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    "ers", os.path.join(HERE, "earnings_reaction_stats.py"))
ers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ers)

# Yahoo's real payload shape, oldest-first (MRNA, verified 2026-11-06).
OLDEST_FIRST = [
    {"quarter": {"fmt": "2025-09-30"}, "epsActual": {"raw": -0.51},
     "epsEstimate": {"raw": -2.17919}, "surprisePercent": {"raw": 0.766}},
    {"quarter": {"fmt": "2025-12-31"}, "epsActual": {"raw": -2.11},
     "epsEstimate": {"raw": -2.60104}, "surprisePercent": {"raw": 0.1888}},
    {"quarter": {"fmt": "2026-03-31"}, "epsActual": {"raw": -3.40},
     "epsEstimate": {"raw": -3.87993}, "surprisePercent": {"raw": 0.1237}},
    {"quarter": {"fmt": "2026-06-30"}, "epsActual": {"raw": -1.97},
     "epsEstimate": {"raw": -2.05918}, "surprisePercent": {"raw": 0.0433}},
]

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))


def quarter_of(entry):
    return (entry or {}).get("quarter", {}).get("fmt")


# 1. the latest quarter wins, not the first element
sel = ers.select_latest_report(OLDEST_FIRST)
check("latest quarter is selected",
      quarter_of(sel) == "2026-06-30", f"got {quarter_of(sel)}")
check("the OLD behaviour (first element) is NOT returned",
      quarter_of(sel) != "2025-09-30", f"got {quarter_of(sel)}")

# 2. the selection does not depend on the array order
shuffled = [OLDEST_FIRST[2], OLDEST_FIRST[0], OLDEST_FIRST[3], OLDEST_FIRST[1]]
sel2 = ers.select_latest_report(shuffled)
check("selection is order-independent",
      quarter_of(sel2) == "2026-06-30", f"got {quarter_of(sel2)}")

# 3. the published verdict follows the latest quarter (CHTR: beat, not miss)
chtr = [
    {"quarter": {"fmt": "2025-09-30"}, "epsActual": {"raw": 8.34},
     "epsEstimate": {"raw": 9.29485}, "surprisePercent": {"raw": -0.1027}},
    {"quarter": {"fmt": "2026-06-30"}, "epsActual": {"raw": 10.66},
     "epsEstimate": {"raw": 10.06264}, "surprisePercent": {"raw": 0.0594}},
]
sel3 = ers.select_latest_report(chtr)
sp = (sel3.get("surprisePercent") or {}).get("raw")
check("verdict follows the latest quarter (CHTR beat)",
      (sp >= 0) and abs(sp * 100 - 5.94) < 0.01, f"surprise {sp}")

# 4. a payload with no usable entry returns None instead of raising
check("empty history -> None", ers.select_latest_report([]) is None)
check("history without epsActual -> None",
      ers.select_latest_report([{"quarter": {"fmt": "2026-06-30"}}]) is None)

# 5. entries without a parseable quarter fall back to the first usable one
noquarter = [
    {"epsActual": {"raw": 1.0}, "epsEstimate": {"raw": 1.0},
     "surprisePercent": {"raw": 0.0}},
    {"epsActual": {"raw": 2.0}, "epsEstimate": {"raw": 2.0},
     "surprisePercent": {"raw": 0.0}},
]
sel5 = ers.select_latest_report(noquarter)
check("unparseable quarters fall back without raising", sel5 is not None)

# 6. a malformed quarter does not kill the selection
mixed = [
    {"quarter": {"fmt": "not-a-date"}, "epsActual": {"raw": 1.0},
     "epsEstimate": {"raw": 1.0}, "surprisePercent": {"raw": 0.0}},
    {"quarter": {"fmt": "2026-06-30"}, "epsActual": {"raw": 1.97},
     "epsEstimate": {"raw": 2.06}, "surprisePercent": {"raw": 0.0433}},
]
sel6 = ers.select_latest_report(mixed)
check("a malformed quarter does not shadow a dated one",
      quarter_of(sel6) == "2026-06-30", f"got {quarter_of(sel6)}")

failed = [(n, d) for n, ok, d in results if not ok]
for name, ok, detail in results:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if not ok else ""))
print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
if failed:
    sys.exit(1)
sys.exit(0)
