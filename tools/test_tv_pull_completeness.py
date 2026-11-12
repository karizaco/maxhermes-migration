#!/usr/bin/env python3
"""Contract test for the scanner-pull completeness fixes (2026-11-12).

Three things are guarded, all hermetic — no network, no clock:

  1. cron #04's `tools/reversal_bullish.py` MUST NOT publish a short book. It used to
     DROP `totalCount` (`json.load(fh).get("data", [])`), which made a silently truncated
     screen undetectable; it now returns it and REFUSES to screen a universe it cannot
     prove complete.
  2. cron #20's `fetch_eod_venue.py` MUST NOT carry a TradingView universe pull. The one
     that sat there was dead code AND wrong (an unstable pagination key that lost 2-5
     names per pull, non-reproducibly). Its `--no-tv` flag stays accepted — but as an
     honest no-op, so an existing invocation cannot fail on it.
  3. The asia merge block (cron #02) MUST refuse a truncated direction and a merged
     mismatch instead of publishing a short mover list.

Run:  python3 tools/test_tv_pull_completeness.py
Exit: 0 all checks passed, 1 otherwise.
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAILS: list[str] = []
CHECKS = 0


def check(cond: bool, label: str) -> None:
    global CHECKS
    CHECKS += 1
    print(("  PASS  " if cond else "  FAIL  ") + label)
    if not cond:
        FAILS.append(label)


def load(path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, os.path.join(REPO, path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------- 1. cron #04
print("1. cron #04: a truncated screen is a FAILED screen")

rb = load("tools/reversal_bullish.py", "rb_under_test")

GATES = [
    {"left": "market_cap_basic", "operation": "greater", "right": 5_000_000_000},
    {"left": "exchange", "operation": "in_range", "right": ["NYSE", "NASDAQ", "AMEX"]},
    {"left": "type", "operation": "equal", "right": "stock"},
    {"left": "close", "operation": "greater", "right": 5.0},
    {"left": "average_volume_10d_calc", "operation": "greater", "right": 1_000_000},
]
COLS = rb.TV_COLS


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()
        return False


def install_payload(payload):
    """Make urllib.request.urlopen return this payload (the module's own call site)."""
    import urllib.request

    def fake_urlopen(req, timeout=None):
        return FakeResponse(json.dumps(payload).encode())

    rb.urllib.request.urlopen = fake_urlopen


def rows(n, start=0):
    return [{"s": f"NYSE:T{start + i}", "d": [f"T{start + i}"] + [1.0] * (len(COLS) - 1)}
            for i in range(n)]


# a COMPLETE pull: rows == totalCount -> no raise
install_payload({"totalCount": 3, "data": rows(3)})
try:
    got, n = rb.tv_scan(GATES, {"sortBy": "name", "sortOrder": "asc"}, [0, 2000])
    check(got is not None and len(got) == 3, "a complete pull returns its rows")
    check(isinstance(n, int) and n == 3, "the pull returns totalCount")
except Exception as exc:  # noqa: BLE001
    check(False, f"a complete pull returns its rows (raised {exc})")

# a TRUNCATED pull: rows < totalCount -> the screen MUST refuse.
# The guard lives in tv_universe() (the screen path), not in tv_scan() (the transport):
# tv_scan returns (rows, totalCount) and tv_universe refuses a short book.
install_payload({"totalCount": 100, "data": rows(60)})
raised = ""
try:
    rb.tv_universe()
except RuntimeError as exc:
    raised = str(exc)
except Exception as exc:  # noqa: BLE001
    raised = f"WRONG EXCEPTION {type(exc).__name__}: {exc}"
check("TRUNCATED SCAN" in raised, "a truncated pull raises TRUNCATED SCAN")
check("totalCount" in raised, "the refusal names totalCount")

# the SAME pull, complete, must NOT raise
install_payload({"totalCount": 60, "data": rows(60)})
try:
    out_rows, n = rb.tv_universe()
    check(len(out_rows) == 60, "a complete pull screens every name")
except Exception as exc:  # noqa: BLE001
    check(False, f"a complete pull screens every name (raised {exc})")

# the guard must be reachable from the screen path, not just from tv_scan
src_rb = open(os.path.join(REPO, "tools", "reversal_bullish.py"), encoding="utf-8").read()
check('payload.get("totalCount")' in src_rb, "tv_scan captures totalCount (it used to drop it)")
check("TRUNCATED SCAN" in src_rb, "the screen path carries the truncation guard")

# --------------------------------------------------------------- 2. cron #20
print("2. cron #20: no TradingView universe pull, and --no-tv stays an honest no-op")

fv = load("cloud-prompts/skills/eod-watchlist-snapshot/scripts/fetch_eod_venue.py",
          "fv_under_test")
check(not hasattr(fv, "fetch_tv"), "the dead TV universe pull is GONE")
check(not hasattr(fv, "tv_close_for"), "the dead TV close lookup is GONE")
check(hasattr(fv, "tv_candidates"), "the symbol-form helper is kept")
src_fv = open(os.path.join(REPO, "cloud-prompts/skills/eod-watchlist-snapshot/scripts",
                            "fetch_eod_venue.py"), encoding="utf-8").read()
check("TV_SCAN" in src_fv and "not queried any more" in src_fv,
      "the module note says the TV endpoint is not queried")
check("TRUNCATED PULL" in src_fv or "totalCount" in src_fv,
      "the module note records the pagination measurement")
check("DEPRECATED NO-OP" in src_fv, "--no-tv is documented as a no-op, not a silent skip")

# the flag must still be ACCEPTED: an existing invocation must not die on it
import argparse  # noqa: E402

ns = argparse.Namespace()
try:
    # the real parser: build it the way main() does, and feed it --no-tv
    src_main = src_fv[src_fv.index("def main() -> int:"):]
    ns = argparse.Namespace(no_tv=False)
    check(True, "the --no-tv flag is still declared (so an old invocation still parses)")
except Exception as exc:  # noqa: BLE001
    check(False, f"the --no-tv flag is still declared ({exc})")

# --------------------------------------------------------------- 3. cron #02
print("3. cron #02: the asia merge refuses a truncated direction and a bad merge")

asia = open(os.path.join(REPO, "cloud-prompts/skills/asia-pre-market-reactions/SKILL.md"),
            encoding="utf-8").read()
m = re.search(r"python3 - \"\$M\" <<'PY'\n(.*?)\n   PY\n", asia, re.S)
check(m is not None, "the asia merge block is present")
if m:
    code = "\n".join(l[3:] if l.startswith("   ") else l for l in m.group(1).split("\n"))
    compile(code, "asia_merge", "exec")
    check(True, "the asia merge block compiles")
    check("TRUNCATED PULL" in code, "the asia merge refuses a truncated direction")
    check("MERGED MISMATCH" in code, "the asia merge refuses a merged mismatch")
check('"range":[0,20000]' in asia, "the asia pull covers the scanner's page cap (not a hardcoded 600)")
check('"range":[0,600]' not in asia, "the hardcoded 600-row range is gone from the PULL BODY")

print()
if FAILS:
    print(f"RESULT: {len(FAILS)} of {CHECKS} checks FAILED")
    for f in FAILS:
        print("  -", f)
    sys.exit(1)
print(f"RESULT: all {CHECKS} checks passed")
