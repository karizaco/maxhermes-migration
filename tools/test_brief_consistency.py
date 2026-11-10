#!/usr/bin/env python3
"""
test_brief_consistency.py — regression test for the pre-market brief's consistency checker.

WHY
---
`check_brief_consistency.py` enforces that the prose, the tables and the CSV of
the pre-market brief agree. It did not enforce the CLAIMS the prose makes about
the screen, and two claims in the published 2026-11-09 brief passed it:

  * "every one ≥ +3.00%" over 35 metals names - one of them (UEC) printed
    +2.60%. No ticker is named in the claim, so the per-ticker checks never
    looked at it.
  * "the liquid expression moves a uniform +3.0% to +4.7%: GFR +38.39%, ..."
    - the name is listed INSIDE a band it is nowhere near. The name's own
    percentage was right; the band was wrong.

THREE PARTS

  A. THE CHECKER ACCEPTS A CONFORMING BRIEF
     A synthetic brief whose claims are all true, with the CSV they came from.

  B. FAULT INJECTION — THE CHECKER MUST BITE
     Every new check has a fixture that breaks it. A mutation that does not
     change the file is itself a FAILURE (a no-op mutation silently "passes"
     and reports a false NOT CAUGHT).

  C. THE EDGE CASES
     A claim whose set cannot be resolved is a NOTE, not a breach. A correction
     note that QUOTES an earlier claim is reporting, not claiming. Both are
     pinned here, because a checker that blocks on them would block the fleet.

Offline and dependency-free: the Cloud sandbox has no PyPI access.

Usage:  python3 tools/test_brief_consistency.py
Exit:   0 = all checks passed, 1 = a check failed.
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CHECKER = os.path.join(HERE, "check_brief_consistency.py")

FAILURES = []
PASSED = []


def ok(name):
    PASSED.append(name)
    print(f"  PASS  {name}")


def bad(name, detail):
    FAILURES.append(f"{name}: {detail}")
    print(f"  FAIL  {name}: {detail}")


# ------------------------------------------------------------------ fixtures
CSV_HEADER = ("ticker,name,gap_pct,premarket_last,prior_session_change_pct,"
              "premarket_volume,avg_volume_30d,pct_of_adv,market_cap,sector,"
              "exchange,liquid_screen,quality_screen,has_news\n")

CSV_ROWS = [
    # ticker, gap,   pm,    prior-session, sector,          liquid, quality
    # "Test Metals" is five rows. liquid+quality is exactly three of them, and
    # three is a size no other sector and gate combination produces, so a
    # claim of "3 Test Metals names" identifies one set in the whole screen.
    "AAA,Alpha Inc,5.00,10.50,1.20,1000000,900000,55.0,9000000000,Test Metals,"
    "NASDAQ,pass,pass,yes\n",
    "BBB,Bravo Inc,4.00,20.80,-0.40,500000,800000,30.0,4000000000,Test Metals,"
    "NYSE,pass,pass,yes\n",
    "CCC,Charlie Inc,2.50,15.25,0.90,300000,700000,22.0,1500000000,Test Metals,"
    "NASDAQ,pass,pass,no\n",
    "DDD,Delta Inc,1.00,8.10,-1.10,40000,600000,6.0,700000000,Test Metals,"
    "NYSE,no,pass,no\n",
    "EEE,Echo Inc,-2.00,7.90,0.30,200000,900000,12.0,600000000,Test Metals,"
    "NASDAQ,pass,no,no\n",
    # "Other Sector": five rows, every gate combination is five.
    "FFF,Foxtrot Inc,6.00,11.60,0.40,900000,900000,50.0,3000000000,Other Sector,"
    "NASDAQ,pass,pass,yes\n",
    "GGG,Golf Inc,3.50,21.70,-0.20,600000,800000,40.0,5000000000,Other Sector,"
    "NYSE,pass,pass,yes\n",
    "HHH,Hotel Inc,2.00,9.40,1.00,200000,700000,15.0,1200000000,Other Sector,"
    "NASDAQ,pass,pass,no\n",
    "III,India Inc,1.50,4.15,0.50,150000,600000,10.0,800000000,Other Sector,"
    "NYSE,pass,pass,no\n",
    "JJJ,Juliett Inc,0.50,5.05,-0.10,100000,500000,8.0,900000000,Other Sector,"
    "NASDAQ,pass,pass,no\n",
    # "Small Sector": two rows, every gate combination is two.
    "KKK,Kilo Inc,2.25,13.25,0.20,100000,400000,7.0,1100000000,Small Sector,"
    "NASDAQ,pass,pass,no\n",
    "LLL,Lima Inc,1.75,6.35,-0.30,80000,300000,6.0,600000000,Small Sector,"
    "NYSE,pass,pass,no\n",
]

MD = """# Pre-market brief — Monday, 09 November 2026

## 1. TL;DR

- **The metals bid is broad:** all 3 Test Metals names on the screen are up and not one is down.
- The leader is **AAA +5.00%**, up on the tape, and the rest of the complex follows.

## 2. Theme clusters

### C2 - Metals bid

The theme's own move is uniform, and the breadth is the point:

- **The liquid expression moves a uniform +2.5% to +4.0%: BBB +4.00%.** Breadth over beta.

| Ticker | Company | Prior close | Pre-market last | Gap % |
|---|---|---|---|---|
| AAA | Alpha Inc | 10.00 | 10.50 | +5.0 |

## 3. Pre-market gaps

| Ticker | Company | Prior close | Pre-market last | Gap % |
|---|---|---|---|---|
| AAA | Alpha Inc | 10.00 | 10.50 | +5.0 |
| FFF | Foxtrot Inc | 5.60 | 11.60 | +6.0 |

## 4. Top losers

| Ticker | Company | Prior close | Pre-market last | Gap % |
|---|---|---|---|---|
| EEE | Echo Inc | 8.00 | 7.90 | -2.0 |

## 5. StockTwits lead read

- **AAA** — the tape's most-discussed name, and the metal bid's leader.

## 7. Overnight / futures / index / crypto

- ES +0.40%, NQ +0.55%, VIX 19.20 - the futures are flat.

## 8. Macro calendar

- CPI lands tomorrow at 08:30 ET. No other release today.

## 9. Earnings today

- Nothing material.

## 10. Source health

- **TradingView america scanner** — the ±3% band, 931 names, screen complete.
- The machine-readable screen is `2026-11-09-pre-market.csv`; one pull feeds both.

## 11. Open research queue

- **AAA** — watch whether the metal bid holds into the close.
"""


def write_fixture(root):
    md = os.path.join(root, "2026-11-09-pre-market.md")
    csv_path = os.path.join(root, "2026-11-09-pre-market.csv")
    with open(md, "w", encoding="utf-8") as fh:
        fh.write(MD)
    with open(csv_path, "w", encoding="utf-8", newline="") as fh:
        fh.write(CSV_HEADER)
        for row in CSV_ROWS:
            fh.write(row)
    return md, csv_path


def run_checker(md, csv_path):
    p = subprocess.run([sys.executable, CHECKER, "--md", md, "--csv", csv_path],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode, p.stdout


def replace_once(text, old, new):
    """Replace exactly one occurrence, or raise — a no-op mutation must not pass."""
    n = text.count(old)
    if n != 1:
        raise AssertionError(f"the fixture does not contain exactly one {old!r} (found {n})")
    return text.replace(old, new, 1)


def replace_csv_once(text, old, new):
    n = text.count(old)
    if n != 1:
        raise AssertionError(f"the CSV does not contain exactly one {old!r} (found {n})")
    return text.replace(old, new, 1)


# ------------------------------------------------------------------ the test
def main():
    tmp = tempfile.mkdtemp(prefix="brief-consistency-")
    try:
        md, csv_path = write_fixture(tmp)

        # --- A. the checker accepts a conforming brief ------------------------
        code, out = run_checker(md, csv_path)
        if code == 0 and "RESULT: consistent" in out:
            ok("A. a conforming brief passes every check")
        else:
            bad("A. a conforming brief passes every check", f"exit={code}\n{out}")

        # the conforming brief raises no note: every claim in it is true
        if "note:" not in out:
            ok("A2. a conforming brief raises no note - its claims agree with the screen")
        else:
            bad("A2. a conforming brief raises no note - its claims agree with the screen", out)

        # --- B. fault injection ------------------------------------------------
        MUTATIONS = [
            ("band claim",
             "a name is listed inside a band it falls outside of",
             lambda md, csv: (
                 replace_once(md, "a uniform +2.5% to +4.0%: BBB +4.00%",
                              "a uniform +2.5% to +3.0%: BBB +4.00%"), csv)),
            ("at or above",
             "a universal claim asserts a floor one name is under",
             lambda md, csv: (
                 replace_once(md, "all 3 Test Metals names on the screen are up and not one is down",
                              "every one of the 3 Test Metals names on the screen is at or "
                              "above +3.00%"), csv)),
            ("every one is up",
             "one name in the claimed set is down",
             lambda md, csv: (
                 md, replace_csv_once(csv, "CCC,Charlie Inc,2.50,15.25",
                                      "CCC,Charlie Inc,-2.50,15.25"))),
            ("the markdown does not reference its CSV",
             "the brief stops naming its companion",
             lambda md, csv: (
                 replace_once(md, "- The machine-readable screen is `2026-11-09-pre-market.csv`; "
                                  "one pull feeds both.",
                              "- The machine-readable screen is in the repo; one pull feeds both."),
                 csv)),
            ("markdown says",
             "a published gap % disagrees with the CSV",
             lambda md, csv: (
                 replace_once(md, "| FFF | Foxtrot Inc | 5.60 | 11.60 | +6.0 |",
                              "| FFF | Foxtrot Inc | 5.60 | 11.60 | +6.9 |"), csv)),
        ]

        for needle, why, mutate in MUTATIONS:
            d = tempfile.mkdtemp(prefix="brief-mut-")
            try:
                m, c = write_fixture(d)
                with open(m, encoding="utf-8") as fh:
                    md_before = fh.read()
                with open(c, encoding="utf-8") as fh:
                    csv_before = fh.read()
                try:
                    new_md, new_csv = mutate(md_before, csv_before)
                except AssertionError as exc:
                    bad(f"B. {needle} — {why}", f"the mutation could not be applied: {exc}")
                    continue
                if new_md == md_before and new_csv == csv_before:
                    bad(f"B. {needle} — {why}",
                        "the mutation changed nothing — a no-op mutation silently passes")
                    continue
                with open(m, "w", encoding="utf-8") as fh:
                    fh.write(new_md)
                with open(c, "w", encoding="utf-8") as fh:
                    fh.write(new_csv)
                code, out = run_checker(m, c)
                if code != 0 and needle in out:
                    ok(f"B. {needle} — {why}")
                else:
                    bad(f"B. {needle} — {why}",
                        f"exit={code} — the checker did not bite\n{out}")
            finally:
                shutil.rmtree(d, ignore_errors=True)

        # --- C. the edge cases --------------------------------------------------
        # C1. a claim whose set the screen cannot resolve is a NOTE, not a breach.
        d = tempfile.mkdtemp(prefix="brief-edge-")
        try:
            m, c = write_fixture(d)
            with open(m, encoding="utf-8") as fh:
                text = fh.read()
            text = replace_once(
                text, "all 3 Test Metals names on the screen are up and not one is down",
                "all 3 Test Metals names on the screen are up and not one is down, and "
                "the 3 Theme Names are with them")
            with open(m, "w", encoding="utf-8") as fh:
                fh.write(text)
            code, out = run_checker(m, c)
            if code == 0:
                ok("C1. a claim that names no set in the screen is a note, not a breach")
            else:
                bad("C1. a claim that names no set in the screen is a note, not a breach",
                    f"exit={code}\n{out}")
        finally:
            shutil.rmtree(d, ignore_errors=True)

        # C2. a correction note that QUOTES an earlier claim is not a claim.
        d = tempfile.mkdtemp(prefix="brief-edge-")
        try:
            m, c = write_fixture(d)
            with open(m, encoding="utf-8") as fh:
                text = fh.read()
            text = replace_once(
                text, "## 1. TL;DR\n",
                "## 1. TL;DR\n\n"
                "> **Corrected 2026-11-10.** §1 still said every one of the 3 Test Metals "
                "names was at or above +3.00% — CCC printed +2.50% — and that is corrected "
                "here.\n")
            with open(m, "w", encoding="utf-8") as fh:
                fh.write(text)
            code, out = run_checker(m, c)
            if code == 0:
                ok("C2. a correction note quoting an earlier claim is not treated as a claim")
            else:
                bad("C2. a correction note quoting an earlier claim is not treated as a claim",
                    f"exit={code}\n{out}")
        finally:
            shutil.rmtree(d, ignore_errors=True)

        # C5. a count that disagrees with the gate the claim names is a NOTE.
        # This is the 2026-11-09 shape: "35 Non-Energy Minerals names that
        # cleared the liquidity gate" - the gate holds 36, the claim says 35.
        d = tempfile.mkdtemp(prefix="brief-edge-")
        try:
            m, c = write_fixture(d)
            with open(m, encoding="utf-8") as fh:
                text = fh.read()
            text = replace_once(
                text, "all 3 Test Metals names on the screen are up and not one is down",
                "all 3 Test Metals names that cleared the quality gate are up and not "
                "one is down")
            with open(m, "w", encoding="utf-8") as fh:
                fh.write(text)
            code, out = run_checker(m, c)
            if code == 0 and "claim says 3 names" in out and "4 row(s)" in out:
                ok("C5. a count that disagrees with the named gate is a note, not a breach")
            else:
                bad("C5. a count that disagrees with the named gate is a note, not a breach",
                    f"exit={code}\n{out}")
        finally:
            shutil.rmtree(d, ignore_errors=True)

        # C3. a missing artifact exits 2 (unreadable) instead of crashing.
        p = subprocess.run([sys.executable, CHECKER, "--md", "/nonexistent.md",
                            "--csv", "/nonexistent.csv"], capture_output=True, text=True)
        if p.returncode == 2:
            ok("C3. a missing artifact exits 2 (unreadable) instead of crashing")
        else:
            bad("C3. a missing artifact exits 2 (unreadable) instead of crashing",
                f"exit={p.returncode}")

        # C4. the checker must not print a claim it cannot resolve as a breach.
        # (A note is printed; a breach would say "uncheckable claim".)
        code, out = run_checker(md, csv_path)
        if "uncheckable claim" not in out:
            ok("C4. an unresolvable set is never reported as a breach")
        else:
            bad("C4. an unresolvable set is never reported as a breach", out)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    print(f"{len(PASSED)} passed, {len(FAILURES)} failed")
    for f in FAILURES:
        print(f"  FAIL  {f}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
