#!/usr/bin/env python3
"""Hermetic regression test for cron #09's scanner PAGINATION KEY.

Measured 2026-11-20: `tools/daily_sweep_engines.py::fetch_universe()` paged the
TradingView scanner sorted by `description` -- the COMPANY NAME, which is NOT
unique (GOOG/GOOGL, BBD/BBDC and ~30 other pairs share one). The server's
tie-break is unstable BETWEEN requests, so a row sitting on a page boundary
came back twice, the dedupe dropped the repeat, and the universe landed on
3710 unique rows against `totalCount` 3711.

The completeness assertion did its job -- the run FAILED CLOSED rather than
publishing a one-row-short book. This test pins the fix so the key cannot
silently go back to `description`.

Checks (offline, no network):
  1. the paged pull sorts by `name` (a stable, unique key)
  2. a stable-key server yields a COMPLETE universe
  3. an unstable-key server is CAUGHT -- `fetch_universe` raises rather than
     returning a short book
  4. the source no longer contains the `description` sort in the paged pull

Run:  python3 tools/test_sweep_engine_pagination.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import daily_sweep_engines as E  # noqa: E402


# --------------------------------------------------------------- the fake server

class FakeScanner:
    """A TradingView scanner stand-in.

    `unstable=True` reproduces the measured server behaviour: the tie-break
    among rows that share a sort key is NOT stable between two requests, so a
    row on the page boundary is served twice (and the row that should have
    been in that window never arrives).
    """

    def __init__(self, names, descriptions, unstable):
        self.names = list(names)
        self.descriptions = descriptions
        self.unstable = unstable
        self.calls = []

    def __call__(self, filters, columns, rng=(0, 2000), sort=None):
        key = (sort or {}).get("sortBy")
        self.calls.append(key)
        if key == "name":
            order = sorted(self.names)
        else:
            order = sorted(self.names, key=lambda n: self.descriptions[n])
        lo, hi = rng
        window = order[lo:hi]
        if self.unstable and lo > 0 and hi < len(order):
            # The boundary row is served AGAIN and the window's tail is short.
            window = [order[lo - 1]] + window[:-1]
        total = len(order)
        data = []
        for n in window:
            row = [self.descriptions[n]] + [0.0] * (len(columns) - 1)
            data.append({"s": f"NYSE:{n}", "d": row})
        return {"totalCount": total, "data": data}


def _universe(n=40, dup_pairs=10):
    names, descriptions = [], {}
    for i in range(n):
        nm = f"NAME{i:03d}"
        names.append(nm)
        descriptions[nm] = f"Company {i // (1 + dup_pairs)} Inc."
    return names, descriptions


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


def check_sort_key_is_stable():
    """1. the paged pull sorts by `name`."""
    names, descriptions = _universe()
    server = FakeScanner(names, descriptions, unstable=False)
    original = E.tv_scan
    E.tv_scan = server
    try:
        E.fetch_universe(300_000_000, page=10)
    finally:
        E.tv_scan = original
    assert server.calls, "the fake scanner was never called"
    assert all(k == "name" for k in server.calls), (
        f"the paged pull must sort by the stable key 'name'; got {sorted(set(server.calls))}"
    )


def check_stable_key_completes():
    """2. a stable-key server yields a COMPLETE universe."""
    names, descriptions = _universe()
    server = FakeScanner(names, descriptions, unstable=False)
    original = E.tv_scan
    E.tv_scan = server
    try:
        rows, total = E.fetch_universe(300_000_000, page=10)
    finally:
        E.tv_scan = original
    assert total == len(names), f"totalCount {total} != universe {len(names)}"
    assert len(rows) == total, f"fetched {len(rows)} rows against totalCount {total}"
    assert len({r["_ticker"] for r in rows}) == total, "the universe carries a duplicate ticker"


def check_unstable_key_is_caught():
    """3. an unstable-key server is CAUGHT, not published."""
    names, descriptions = _universe()
    server = FakeScanner(names, descriptions, unstable=True)
    original = E.tv_scan
    E.tv_scan = server
    try:
        raised = None
        try:
            E.fetch_universe(300_000_000, page=10)
        except E.EngineError as exc:
            raised = exc
    finally:
        E.tv_scan = original
    assert raised is not None, (
        "an unstable sort key produced a short universe and fetch_universe "
        "RETURNED it -- the completeness assertion must fail closed"
    )
    assert "TRUNCATED SCAN" in str(raised), f"unexpected failure text: {raised}"


def check_source_has_no_description_sort():
    """4. the source no longer sorts the paged pull by `description`."""
    src = Path(E.__file__).resolve().read_text(encoding="utf-8")
    assert '"sortBy": "description"' not in src, (
        "daily_sweep_engines.py sorts a PAGED pull by 'description' again -- "
        "the company name is not a unique key and the page boundary shifts"
    )


def main() -> int:
    print("test_sweep_engine_pagination — cron #09's scanner pagination key")
    results = [
        _check("the paged pull sorts by the stable key 'name'", check_sort_key_is_stable),
        _check("a stable-key server yields a complete universe", check_stable_key_completes),
        _check("an unstable-key server fails closed", check_unstable_key_is_caught),
        _check("the source carries no description-sorted paged pull",
               check_source_has_no_description_sort),
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
