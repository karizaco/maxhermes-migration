#!/usr/bin/env python3
"""
test_brief26_pull_band.py — prove the band-truncation guard actually fires.

The 2026-11-05 incident: the +/-3% band was pulled with `range:[0,400]`, the scanner returned
400 of 547 decliners SILENTLY (HTTP 200, no truncation flag), and the counts were published as
exact when they were floors. The `len(rows) == totalCount` assert exists to catch that.

Until 2026-11-13 the guard did not: `pull_band` set `band["complete"] = False` on a truncated
screen and then an unconditional `band["complete"] = True` overwrote it before the function
returned. A truncated band was published as complete.

This test stubs the scanner, returns a truncated screen, and asserts the flag survives. A text
grep cannot prove that — the string `band["complete"] = True` also appears in the comment that
documents the fix, so only the behaviour settles it.

USAGE
    python3 test_brief26_pull_band.py
"""

import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SHARED = os.path.join(os.path.dirname(HERE), "cloud-prompts", "_shared")
sys.path.insert(0, SHARED)

RESULTS = []


def check(ok, name, detail=""):
    RESULTS.append((bool(ok), name, detail))
    print("%s %-38s %s" % ("PASS" if ok else "FAIL", name, detail))
    return bool(ok)


def load_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "brief26_pull", os.path.join(SHARED, "brief26_pull.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def stub_scanner(mod, total_count, rows_returned, tmp):
    """Make tv_scan return `rows_returned` rows against a `totalCount` of `total_count`."""
    def fake_run_tv(mode, body=None, names=None, out=None):
        payload = {"totalCount": total_count,
                   "data": [{"s": "NASDAQ:T%03d" % i, "d": [None] * len(mod.COLS)}
                            for i in range(rows_returned)]}
        with open(out, "w") as fh:
            json.dump(payload, fh)
        return out, ""
    mod.run_tv = fake_run_tv
    return tmp


def main():
    if not os.path.exists(os.path.join(SHARED, "brief26_pull.py")):
        print("FAIL — brief26_pull.py is not at %s" % SHARED)
        return 1
    mod = load_module()
    tmp = tempfile.mkdtemp(prefix="band_guard_test_")

    # ---------- a COMPLETE screen ----------
    stub_scanner(mod, total_count=10, rows_returned=10, tmp=tmp)
    band = mod.pull_band(tmp, {})
    check(band["complete"] is True, "a complete screen is complete",
          "complete=%s gainers=%d decliners=%d" % (band["complete"], len(band["gainers"]),
                                                   len(band["decliners"])))

    # ---------- a TRUNCATED screen: 400 rows against a totalCount of 547 ----------
    stub_scanner(mod, total_count=547, rows_returned=400, tmp=tmp)
    band = mod.pull_band(tmp, {})
    check(band["complete"] is False,
          "a truncated screen stays INCOMPLETE", "complete=%s" % band["complete"])
    check(len(band["gainers"]) == 400 and len(band["decliners"]) == 400,
          "the truncated rows are still returned",
          "%d + %d" % (len(band["gainers"]), len(band["decliners"])))

    # ---------- ONE side truncated ----------
    calls = {"n": 0}

    def fake_run_tv(mode, body=None, names=None, out=None):
        calls["n"] += 1
        total, n = (10, 10) if calls["n"] == 1 else (547, 400)
        payload = {"totalCount": total,
                   "data": [{"s": "NASDAQ:T%03d" % i, "d": [None] * len(mod.COLS)}
                            for i in range(n)]}
        with open(out, "w") as fh:
            json.dump(payload, fh)
        return out, ""
    mod.run_tv = fake_run_tv
    band = mod.pull_band(tmp, {})
    check(band["complete"] is False, "one truncated side fails the whole band",
          "complete=%s" % band["complete"])

    shutil.rmtree(tmp, ignore_errors=True)
    failed = [n for ok, n, _ in RESULTS if not ok]
    print("\n%d tests, %d passed, %d failed" % (len(RESULTS), len(RESULTS) - len(failed), len(failed)))
    for n in failed:
        print("  FAILED: %s" % n)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
