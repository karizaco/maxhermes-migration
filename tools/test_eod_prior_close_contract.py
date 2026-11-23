#!/usr/bin/env python3
"""Fault-injection test for the cron #20 PRIOR-CLOSE anchor contract (EOD_DERIVE_V3).

A rule that has never been observed FAILING is a claim, not a rule. This test drives the
REAL derive stage against a synthetic fixture, proves the three anchor cases behave as the
contract says, then MUTATES the rule twice and proves the test catches each mutation.

  python3 tools/test_eod_prior_close_contract.py

Exit code 0 = every case behaved as expected.

THE RULE UNDER TEST (2026-11-23)
--------------------------------
A gap BELOW the prior session's published close has two possible causes and they are not the
same fact:

  * an EX-DISTRIBUTION - the quote service's prior close is dividend-adjusted, so it sits
    below the published raw basis. The price change stands on the published basis and the
    row is flagged EX_DISTRIBUTION.
  * a DEFECTIVE PUBLISHED PRIOR CLOSE - the prior session's file published a close the
    exchange's own record contradicts. Then the price change against the archive's own
    number is not the session's price change at all.

The discriminator needs no new source: the quote service's prior close is dividend- AND
split-adjusted, the bar series' prior close is split-adjusted only. When the two AGREE
(within 0.5%), no distribution can be in play, so the published prior close is the outlier:
the corroborated close becomes the anchor and the row is flagged PRIOR_CLOSE_SUPERSEDED.
"""

from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DERIVE = os.path.join(REPO, "cloud-prompts", "skills", "eod-watchlist-snapshot", "scripts",
                       "eod_derive.py")

SESSION = "2026-11-23"
PRIOR = "2026-11-20"
BASE_COLUMNS = ["date", "ticker", "name", "open", "high", "low", "close", "volume",
                "change_pct", "market_cap", "pe_ratio", "sector", "currency", "exchange"]

# ticker -> (name, published prior close, quote prior close, bar prior close,
#            session close, expected flag, expected change_pct)
CASES = {
    # the archive's prior close is WRONG: the quote and the bar agree with each other and
    # with the exchange's record, and both disagree with the published close.
    "SUPA": ("Superseded Corp", 128.1, 125.53, 125.53, 165.05, "PRIOR_CLOSE_SUPERSEDED",
             (165.05 - 125.53) / 125.53 * 100.0),
    # a real distribution: the quote is dividend-adjusted, so it sits BELOW the bar.
    "EXDI": ("Ex Distribution Corp", 34.90, 34.02, 34.90, 33.90, "EX_DISTRIBUTION",
             (33.90 - 34.90) / 34.90 * 100.0),
    # the control: no gap at all, the published basis stands.
    "NORM": ("Normal Corp", 100.0, 99.80, 100.0, 101.0, "",
             (101.0 - 100.0) / 100.0 * 100.0),
}

DAY = 86400
TS_PRIOR = 1795208400    # 2026-11-20 21:00 UTC
TS_SESSION = 1795467600  # 2026-11-23 21:00 UTC


def day_of(ts: int) -> str:
    return __import__("datetime").datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d")


def build_fixture(d: str) -> tuple[str, str, str, str]:
    base = os.path.join(d, "base.csv")
    hist = os.path.join(d, "history.jsonl")
    vendor = os.path.join(d, "vendor.json")
    prior = os.path.join(d, "prior.csv")
    qprev = os.path.join(d, "quote_prev.json")

    with open(base, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=BASE_COLUMNS)
        w.writeheader()
        for t, (name, _pub, _q, _bar, close, _flag, _chg) in CASES.items():
            w.writerow({"date": SESSION, "ticker": t, "name": name, "open": close,
                        "high": close, "low": close, "close": close, "volume": "1000000",
                        "change_pct": "", "market_cap": "", "pe_ratio": "",
                        "sector": "Information Technology", "currency": "USD",
                        "exchange": "NASDAQ"})

    with open(hist, "w") as fh:
        for t, (_n, _pub, _q, bar, close, _f, _c) in CASES.items():
            fh.write(json.dumps({"ticker": t, "bars": [
                [TS_PRIOR, bar, bar, bar, bar, 1000000],
                [TS_SESSION, close, close, close, close, 1000000]]}) + "\n")

    with open(vendor, "w") as fh:
        json.dump({"rows": [{"ticker": t, "name": CASES[t][0], "exchange": "NASDAQ",
                             "currency": "USD", "gics_sector": "Information Technology"}
                            for t in CASES],
                   "vendor_caps": {}, "floats": {}}, fh)

    with open(prior, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["date", "ticker", "close"])
        w.writeheader()
        for t, (name, pub, _q, _bar, _c, _f, _chg) in CASES.items():
            w.writerow({"date": PRIOR, "ticker": t, "close": pub})

    with open(qprev, "w") as fh:
        json.dump({t: CASES[t][2] for t in CASES}, fh)
    return base, hist, vendor, prior, qprev


def run_derive(script: str, d: str) -> dict[str, dict]:
    base, hist, vendor, prior, qprev = build_fixture(d)
    out = os.path.join(d, "out.csv")
    manifest = os.path.join(d, "manifest.json")
    p = subprocess.run([sys.executable, script, "--base", base, "--history", hist,
                        "--vendor", vendor, "--session", SESSION, "--out", out,
                        "--manifest", manifest, "--prior-csv", prior,
                        "--quote-prev", qprev],
                       capture_output=True, text=True)
    if p.returncode != 0:
        raise SystemExit(f"derive stage failed:\n{p.stdout}\n{p.stderr}")
    with open(out, newline="") as fh:
        return {r["ticker"]: r for r in csv.DictReader(fh)}


def close_enough(a: str, b: float) -> bool:
    try:
        return abs(float(a) - b) < 0.01
    except (TypeError, ValueError):
        return False


def check(rows: dict[str, dict], label: str) -> list[str]:
    fails = []
    for t, (_n, _pub, _q, _bar, _close, flag, chg) in CASES.items():
        r = rows.get(t)
        if r is None:
            fails.append(f"{label}: {t} missing from the output")
            continue
        dq = (r.get("data_quality") or "").split("|")
        if flag:
            if flag not in dq:
                fails.append(f"{label}: {t} expected flag {flag}, got {r.get('data_quality')}")
            for other in ("EX_DISTRIBUTION", "PRIOR_CLOSE_SUPERSEDED", "SPLIT_ADJUSTED"):
                if other != flag and other in dq:
                    fails.append(f"{label}: {t} carries {other} as well as {flag}")
        else:
            for other in ("EX_DISTRIBUTION", "PRIOR_CLOSE_SUPERSEDED", "SPLIT_ADJUSTED"):
                if other in dq:
                    fails.append(f"{label}: {t} expected no anchor flag, got {other}")
        if not close_enough(r.get("change_pct", ""), chg):
            fails.append(f"{label}: {t} change_pct {r.get('change_pct')!r} != {chg:.4f}")
    return fails


MUTATIONS = [
    ("M1: the discriminator removed - every gap below the published close is read as a "
     "distribution again",
     """                if bar_prior is not None and bar_asserted and \\
                        abs(qp - bar_prior) / max(abs(bar_prior), 1e-9) <= 0.005:""",
     """                if False:"""),
    ("M2: the superseded row keeps the published prior close as its anchor (the flag stays, "
     "the number does not move)",
     """                    anchor, anchor_source = bar_prior, "bar_superseded_prior\"""",
     """                    anchor, anchor_source = published_prior, "prior_published\""""),
]


def main() -> int:
    fails: list[str] = []
    with tempfile.TemporaryDirectory() as d:
        rows = run_derive(DERIVE, d)
        f = check(rows, "valid artifact")
        if f:
            fails.extend(f)
            print("FAIL the valid fixture did not behave as the contract says:")
            for x in f:
                print("   ", x)
            return 1
        print("ok   the valid fixture behaves as the contract says "
              "(superseded / ex-distribution / control)")

    for label, old, new in MUTATIONS:
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "mutated.py")
            text = open(DERIVE).read()
            if old not in text:
                print(f"FAIL {label}: the mutation target is not in the source "
                      f"(the rule changed shape - update this test)")
                fails.append(label)
                continue
            open(src, "w").write(text.replace(old, new, 1))
            try:
                rows = run_derive(src, d)
            except SystemExit as e:
                print(f"ok   {label} -> the mutated build FAILED loudly")
                continue
            mf = check(rows, label)
            if mf:
                # the mutated build no longer satisfies the contract -> the mutation WAS
                # caught, which is what this test is for
                print(f"ok   {label} -> caught: " + mf[0].split(": ", 1)[-1])
            else:
                print(f"FAIL {label} -> the mutation was NOT caught (the mutated build "
                      f"still satisfies the contract)")
                fails.append(label)

    if fails:
        print(f"\n{len(fails)} case(s) failed")
        return 1
    print("\nall cases passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
