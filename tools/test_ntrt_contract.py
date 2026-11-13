#!/usr/bin/env python3
"""
test_ntrt_contract.py — regression test for cron #25's artifact contract.

Three parts:

  A. THE CHECKER ACCEPTS A CONFORMING ARTIFACT
     A synthetic brief that follows the ARTIFACT FORMAT CONTRACT must pass
     every check and print `contract: 17/17`.

  B. FAULT INJECTION — THE CHECKER MUST BITE
     Every one of the seventeen checks has at least one fixture that fails it.
     A mutation that does not change the file is itself a FAILURE (a no-op
     mutation silently "passes" and reports a false NOT CAUGHT).

  C. THE REPLY LINE
     The reply must publish `contract: 17/17`; a wrong count is caught.

Offline and dependency-free: the Cloud sandbox has no PyPI access.

Usage:  python3 tools/test_ntrt_contract.py
Exit:   0 = all checks passed, 1 = a check failed.
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
CHECKER = os.path.join(HERE, "check_ntrt_artifact.py")

FAILURES = []
PASSED = []


def ok(name):
    PASSED.append(name)
    print(f"  PASS  {name}")


def bad(name, detail):
    FAILURES.append(f"{name}: {detail}")
    print(f"  FAIL  {name}: {detail}")


# ------------------------------------------------------------------ fixtures
CSV_HEADER = ("ticker,premarket_change_pct,premarket_close,prev_close,premarket_volume,"
              "avg_volume_30d,pct_of_adv,mkt_cap_usd,sector,exchange,catalyst,noise\n")

CSV_ROWS = [
    # ticker, gap,   pm,   prev,  vol,   avg,      pct,    cap,        sector, exchange,
    # catalyst, noise
    "AAAA,12.50,25.00,22.22,500000,1000000,50.000,4940000000000,Technology Services,NASDAQ,"
    "\"Q3 revenue $412M vs $389M est; FY guide raised\",false",
    "BBBB,-8.25,10.00,10.90,300000,2000000,15.000,1500000000,Health Technology,NASDAQ,"
    "\"Guidance cut; Q3 EPS $0.21 vs $0.30 est\",false",
    "CCCC,5.10,7.50,7.14,250000,1250000,20.000,450000000,Commercial Services,NYSE,,false",
    "DDDD,-4.40,12.00,12.55,60000,1000000,6.000,600000000,Producer Manufacturing,NYSE,"
    "\"Q3 miss; Q4 guide lowered to $180-190M\",false",
    "EEEE,9.90,5.00,4.55,5000,1000000,0.500,300000000,Consumer Durables,NASDAQ,,true",
    "FFFF,-6.20,20.00,21.32,8000,1000000,0.800,900000000,Technology Services,NASDAQ,"
    "\"Secondary offering announced\",true",
    "GGGG,3.20,8.00,7.75,12000,,,200000000,Health Technology,NASDAQ,,true",
    "HHHH,-3.50,4.00,4.14,40000,2000000,2.000,500000000,Energy Minerals,NYSE,,false",
    "ZZZZ,3.90,1.50,1.44,2000,1000000,0.200,80000000,Retail Trade,NYSE,,true",
    "YYYY,-3.60,3.00,3.11,3000,1000000,0.300,250000000,Finance,NYSE,,true",
    # a name BELOW the $200M universe floor: it gaps hardest of all, and the
    # brief must publish it in the watchlist rather than let the floor hide it
    "IIII,-55.00,4.50,10.00,1200000,500000,240.000,2000000,Health Technology,NASDAQ,,false",
    # a gate-passing name that the actionable table's per-direction cap leaves out
    "JJJJ,7.00,12.00,11.22,500000,1000000,50.000,900000000,Technology Services,NASDAQ,,false",
]

MD = """# NTRT gap brief — Friday, 06 November 2026
**Mode B — screener fallback.** TradingView public scanner; the ntrt backend was unreachable (`GET /health` -> HTTP 000). Snapshot 09:22 ET, 8 min before the open.

## TL;DR
- **The tape is a rotation, not a sell-off:** 12 US stocks printed a >=3% pre-market gap; 5 cleared the actionable gate (|gap| >=3% AND >=5% of the session-normalised 30-day ADV AND market cap >= $200M AND pre-market print >= 25,000 shares) — 3 down, 2 up.
- **The %ADV reality check:** of the 12 gap names, only 5 cleared 5% of 30-day ADV and just 2 cleared 20%; 6 are quotes on essentially no volume. The screen is not 12 tradeable names.
- **The most consequential name is IIII -55.0%** — below the $200M floor, so it is in the watchlist, not the table.

## Market backdrop
- **Futures are flat.** ES -0.1%, NQ -0.2% at 08:45 ET; the tape is idiosyncratic, not macro.
- **No macro release today**; CPI lands tomorrow.

## Yesterday's short list
Prior board: `2026-11-05`. Each name was looked up in this morning's full screen. A blank is not a zero: `not in the feed` means the screen did not quote the name.

| Ticker | This morning | Status |
|---|---|---|
| ZZZZ | — | not in the feed |
| YYYY | +1.1 | under the line |

## Worth your attention
Actionable set: 4 names (|gap| >=3% AND >=5% of the session-normalised 30-day ADV AND market cap >= $200M AND pre-market print >= 25,000 shares), sorted by absolute gap within each direction, capped at 20 per direction.

### Gap down
| Ticker | Gap % | PM print | Prev close | % of 30d ADV | Mkt cap | Why |
|---|---|---|---|---|---|---|
| BBBB | -8.3 | 10.00 | 10.90 | 15.0 | $1.50B | Guidance cut; Q3 EPS $0.21 vs $0.30 est |
| DDDD | -4.4 | 12.00 | 12.55 | 6.0 | $600M | Q3 miss; Q4 guide lowered to $180-190M |

### Gap up
| Ticker | Gap % | PM print | Prev close | % of 30d ADV | Mkt cap | Why |
|---|---|---|---|---|---|---|
| AAAA | +12.5 | 25.00 | 22.22 | 50.0 | $4.94T | Q3 revenue $412M vs $389M est; FY guide raised |
| CCCC | +5.1 | 7.50 | 7.14 | 20.0 | $450M | No catalyst confirmed: no company news matched the move |

### Also cleared the gate
Gate-passing names not in the table above: 1.
No catalyst was looked up for them — they are listed so that a cap never silently drops a name: JJJJ

### Gap vs catalyst
Universe: the 8 names checked for a catalyst (4 actionable + 4 wider screen) out of 12 screen names.

| | Catalyst sourced | No catalyst |
|---|---|---|
| **Passes the actionable gate** | 3 — e.g. AAAA | 1 — e.g. CCCC |
| **Fails the gate** | 1 — e.g. FFFF | 3 — e.g. EEEE |

## Wider screen
The names NOT already listed above — top 2 per direction by absolute gap. These failed the actionable gate, so they are thin-book prints; no catalyst column.

### Gap down (not actionable)
| Ticker | Gap % | % of 30d ADV | Sector |
|---|---|---|---|
| FFFF | -6.2 | 0.8 | Technology Services |
| HHHH | -3.5 | 2.0 | Energy Minerals |

### Gap up (not actionable)
| Ticker | Gap % | % of 30d ADV | Sector |
|---|---|---|---|
| EEEE | +9.9 | 0.5 | Consumer Durables |
| GGGG | +3.2 | — | Health Technology |

### Below the $200M floor
The names the universe floor EXCLUDED. Watchlist only — no catalyst was looked up, and these rows are not part of the asymmetry table above.

| Ticker | Gap % | % of 30d ADV | Mkt cap | Note |
|---|---|---|---|---|
| IIII | -55.0 | 240.0 | $2M | Below the floor; the biggest mover of the day |

## Flags
- **AAAA +12.5% on 50.0% of ADV is the one gap-up with a genuinely heavy book**; every other name in the brief traded a fraction of a normal day.
- **One catalyst could not be confirmed: CCCC +5.1%.** A targeted news search found no company event matching the move, so the Why cell is left unconfirmed rather than filled with a guess.
- **The $200M floor hid IIII -55.0%**, so the watchlist publishes it; the actionable table's cap left JJJJ out, so it is listed under 'Also cleared the gate'.

## Method, source health & caveats
- **Primary screen — TradingView public scanner, HTTP 200.** One scan of `POST https://scanner.tradingview.com/america/scan`, `premarket_change` in [3,1000] and [-1000,-3], with the $200M market-cap floor applied AFTER the scan. 12 unique names at >=3% gap.
- **ntrt backend — failed.** `GET http://127.0.0.1:8000/health` -> HTTP 000 (connection refused), so this is Mode B (screener fallback).
- **The CSV carries the full screen (12 rows); the markdown carries the 8 names published above, plus the watchlist.**
brief_rendered target=ntrt-premarket:2026-11-06 mode=B
"""

REPLY = """Pre-market gap brief for 06 Nov is written and pushed.

### Signal
- AAAA +12.5% — Q3 revenue $412M vs $389M est; FY guide raised; 50.0% of ADV.
- BBBB -8.3% — guidance cut; Q3 EPS $0.21 vs $0.30 est.

### Method & caveats
- TradingView public screener (Mode B), snapshot 09:22 ET; 12 names at >=3% gap, 5 clear the gate.

### Files
- /workspace/ntrt/2026-11-06.md
- /workspace/ntrt/2026-11-06.csv
contract: 17/17

### Push / errors
push: ok (verified)
errors: 0
"""


def write_fixture(d):
    md = os.path.join(d, "2026-11-06.md")
    csv_path = os.path.join(d, "2026-11-06.csv")
    reply = os.path.join(d, "reply.txt")
    with open(md, "w", encoding="utf-8") as fh:
        fh.write(MD)
    with open(csv_path, "w", encoding="utf-8") as fh:
        fh.write(CSV_HEADER + "\n".join(CSV_ROWS) + "\n")
    with open(reply, "w", encoding="utf-8") as fh:
        fh.write(REPLY)
    return md, csv_path, reply


def run_checker(md, csv_path, reply=None):
    cmd = [sys.executable, CHECKER, "--md", md, "--csv", csv_path]
    if reply:
        cmd += ["--reply", reply]
    p = subprocess.run(cmd, capture_output=True, text=True)
    failed = []
    for line in p.stdout.split("\n"):
        line = line.strip()
        if line.startswith("FAIL [") or line.startswith("  FAIL ["):
            name = line.split("[", 2)[1].split("]", 1)[0]
            if name not in failed:
                failed.append(name)
    return p.returncode, p.stdout, failed


def replace_once(text, old, new):
    """Replace exactly one occurrence, or raise — a no-op mutation must not pass."""
    n = text.count(old)
    if n != 1:
        raise AssertionError(f"the fixture does not contain exactly one {old!r} (found {n})")
    return text.replace(old, new, 1)


# ------------------------------------------------------------------ the test
def main():
    tmp = tempfile.mkdtemp(prefix="ntrt-contract-")
    try:
        md, csv_path, reply = write_fixture(tmp)

        # --- A. the checker accepts a conforming artifact --------------------
        code, out, failed = run_checker(md, csv_path)
        if code == 0 and not failed and "contract: 17/17" in out:
            ok("A. a conforming artifact passes every check and prints contract: 17/17")
        else:
            bad("A. a conforming artifact passes every check (16/16)",
                f"exit={code} failing={failed}\n{out}")

        # the reply line
        code, out, failed = run_checker(md, csv_path, reply)
        if code == 0 and "[REPLY] the reply publishes contract: 17/17" in out:
            ok("C1. a reply publishing contract: 17/17 is accepted")
        else:
            bad("C1. a reply publishing contract: 17/17 is accepted", f"exit={code}\n{out}")

        wrong = os.path.join(tmp, "wrong.txt")
        with open(wrong, "w", encoding="utf-8") as fh:
            fh.write(REPLY.replace("contract: 17/17", "contract: 12/12"))
        code, out, failed = run_checker(md, csv_path, wrong)
        if code != 0 and "[REPLY]" in out:
            ok("C2. a reply publishing the wrong count is rejected")
        else:
            bad("C2. a reply publishing the wrong count is rejected", f"exit={code}\n{out}")

        # --- B. fault injection ------------------------------------------------
        MUTATIONS = [
            ("SECTIONS", "the Flags heading is removed",
             lambda md, csv: (replace_once(md, "## Flags\n", ""), csv)),
            ("SECTION_EMPTY", "the Flags section is emptied",
             lambda md, csv: (replace_once(
                 md, "- **AAAA +12.5% on 50.0% of ADV is the one gap-up with a genuinely heavy "
                 "book**; every other name in the brief traded a fraction of a normal day.\n"
                 "- **One catalyst could not be confirmed: CCCC +5.1%.** A targeted news search "
                 "found no company event matching the move, so the Why cell is left unconfirmed "
                 "rather than filled with a guess.\n", ""), csv)),
            ("NO_CATALYSTS", "a separate ## Catalysts section is added",
             lambda md, csv: (replace_once(
                 md, "## Wider screen\n",
                 "## Catalysts\n\n- AAAA — Q3 beat and a raised guide.\n\n## Wider screen\n"),
                 csv)),
            ("ONE_NAME_ONCE", "AAAA is listed twice in the same table",
             lambda md, csv: (replace_once(
                 md, "| AAAA | +12.5 | 25.00 | 22.22 | 50.0 | $4.94T | Q3 revenue $412M vs $389M "
                 "est; FY guide raised |\n",
                 "| AAAA | +12.5 | 25.00 | 22.22 | 50.0 | $4.94T | Q3 revenue $412M vs $389M "
                 "est; FY guide raised |\n"
                 "| AAAA | +12.5 | 25.00 | 22.22 | 50.0 | $4.94T | Q3 revenue $412M vs $389M "
                 "est; FY guide raised |\n"), csv)),
            ("MD_CSV_AGREE", "a published gap % disagrees with the CSV",
             lambda md, csv: (replace_once(
                 md, "| AAAA | +12.5 | 25.00 | 22.22 | 50.0 | $4.94T |",
                 "| AAAA | +12.9 | 25.00 | 22.22 | 50.0 | $4.94T |"), csv)),
            ("CSV_CONTRACT", "two CSV columns are swapped in the header",
             lambda md, csv: (md, replace_once(
                 csv, "sector,exchange,catalyst,noise", "exchange,sector,catalyst,noise"))),
            ("PCT_ADV_EMPTY", "pct_of_adv is 0 where there is no ADV history",
             lambda md, csv: (md, replace_once(
                 csv, "GGGG,3.20,8.00,7.75,12000,,,200000000",
                 "GGGG,3.20,8.00,7.75,12000,,0,200000000"))),
            ("MKTCAP_FORMAT", "a trillion cap is published in billions",
             lambda md, csv: (replace_once(md, "$4.94T", "$4937.50B"), csv)),
            ("NOISE_FLAG", "a noise flag is wrong",
             lambda md, csv: (md, replace_once(
                 csv, "4940000000000,Technology Services,NASDAQ,\"Q3 revenue $412M vs $389M est; "
                 "FY guide raised\",false",
                 "4940000000000,Technology Services,NASDAQ,\"Q3 revenue $412M vs $389M est; "
                 "FY guide raised\",true"))),
            ("TLDR_BULLETS", "the TL;DR loses a bullet",
             lambda md, csv: (replace_once(
                 md, "- **The most consequential name is IIII -55.0%** — below the $200M floor, "
                 "so it is in the watchlist, not the table.\n", ""), csv)),
            ("TLDR_ADV_CHECK", "no TL;DR bullet is the %ADV reality check",
             lambda md, csv: (replace_once(
                 md, "- **The %ADV reality check:** of the 12 gap names, only 5 cleared 5% of "
                 "30-day ADV and just 2 cleared 20%; 6 are quotes on essentially no volume. The "
                 "screen is not 12 tradeable names.",
                 "- **Volume context:** of the 12 gap names, 5 cleared the bar and 2 cleared the "
                 "top of it; the rest are quotes."), csv)),
            ("GATE", "an actionable name no longer clears the gate",
             lambda md, csv: (replace_once(
                 md, "| BBBB | -8.3 | 10.00 | 10.90 | 15.0 | $1.50B |",
                 "| BBBB | -8.3 | 10.00 | 10.90 | 4.0 | $1.50B |"),
                 replace_once(
                     csv, "BBBB,-8.25,10.00,10.90,300000,2000000,15.000",
                     "BBBB,-8.25,10.00,10.90,80000,2000000,4.000"))),
            ("GATE", "an actionable name's pre-market print is only 6,000 shares",
             # The share floor bites: DDDD still clears |gap|, %ADV and the cap,
             # but 6,000 shares is a quote. The ADV is scaled with the volume so
             # pct_of_adv stays exactly 6.000 and NO other check can fire.
             lambda md, csv: (md, replace_once(
                 csv, "DDDD,-4.40,12.00,12.55,60000,1000000,6.000,600000000",
                 "DDDD,-4.40,12.00,12.55,6000,100000,6.000,600000000"))),
            ("GATE", "a name at 4.94% of ADV clears the session-normalised bar but is not published",
             # The session-normalised bar is 5.0% x 322/330 = 4.8788% of the RAW
             # 30-day ADV. YYYY at 4.940% clears it (and is clear of the 0.05
             # boundary band) and must therefore be published.
             lambda md, csv: (md, replace_once(
                 csv, "YYYY,-3.60,3.00,3.11,3000,1000000,0.300,250000000,Finance,NYSE,,true",
                 "YYYY,-3.60,3.00,3.11,49400,1000000,4.940,250000000,Finance,NYSE,,false"))),
            ("FOURCELL", "a published four-cell count is wrong",
             lambda md, csv: (replace_once(
                 md, "| **Passes the actionable gate** | 3 — e.g. AAAA |",
                 "| **Passes the actionable gate** | 4 — e.g. AAAA |"), csv)),
            ("FOURCELL_EX", "a cell quotes an example that is not in it",
             lambda md, csv: (replace_once(
                 md, "| **Passes the actionable gate** | 3 — e.g. AAAA |",
                 "| **Passes the actionable gate** | 3 — e.g. ZZZZ |"), csv)),
            ("SUBFLOOR", "the below-the-floor watchlist publishes a gap the CSV disagrees with",
             lambda md, csv: (replace_once(
                 md, "| IIII | -55.0 | 240.0 | $2M |",
                 "| IIII | -50.0 | 240.0 | $2M |"), csv)),
            ("SUBFLOOR", "the watchlist is deleted while the floor hides the day's biggest mover",
             lambda md, csv: (replace_once(
                 md,
                 "### Below the $200M floor\n"
                 "The names the universe floor EXCLUDED. Watchlist only — no catalyst was looked "
                 "up, and these rows are not part of the asymmetry table above.\n\n"
                 "| Ticker | Gap % | % of 30d ADV | Mkt cap | Note |\n"
                 "|---|---|---|---|---|\n"
                 "| IIII | -55.0 | 240.0 | $2M | Below the floor; the biggest mover of the day |\n\n",
                 ""), csv)),
            ("ALSO_CLEARED", "a gate-passing name is silently dropped from the list",
             lambda md, csv: (replace_once(
                 md,
                 "No catalyst was looked up for them — they are listed so that a cap never "
                 "silently drops a name: JJJJ",
                 "No catalyst was looked up for them — they are listed so that a cap never "
                 "silently drops a name."), csv)),
            ("ALSO_CLEARED", "the list declares a count it does not carry",
             lambda md, csv: (replace_once(
                 md, "Gate-passing names not in the table above: 1.",
                 "Gate-passing names not in the table above: 2."), csv)),
            ("YESTERDAY", "a yesterday-list status is not one of the three words",
             lambda md, csv: (replace_once(md, "| not in the feed |", "| unknown |"), csv)),
        ]

        for name, why, mutate in MUTATIONS:
            d = tempfile.mkdtemp(prefix="ntrt-mut-")
            try:
                m, c, _r = write_fixture(d)
                with open(m, encoding="utf-8") as fh:
                    md_before = fh.read()
                with open(c, encoding="utf-8") as fh:
                    csv_before = fh.read()
                try:
                    new_md, new_csv = mutate(md_before, csv_before)
                except AssertionError as exc:
                    bad(f"B. {name} — {why}", f"the mutation could not be applied: {exc}")
                    continue
                if new_md == md_before and new_csv == csv_before:
                    bad(f"B. {name} — {why}", "the mutation changed nothing — a no-op mutation "
                                             "silently passes")
                    continue
                with open(m, "w", encoding="utf-8") as fh:
                    fh.write(new_md)
                with open(c, "w", encoding="utf-8") as fh:
                    fh.write(new_csv)
                code, out, failed = run_checker(m, c)
                if code != 0 and name in failed:
                    extra = [f for f in failed if f != name]
                    ok(f"B. {name} — {why}"
                       + (f"  (also caught: {', '.join(extra)})" if extra else ""))
                else:
                    bad(f"B. {name} — {why}",
                        f"exit={code} failing={failed} — the checker did not bite")
            finally:
                shutil.rmtree(d, ignore_errors=True)

        # a missing file is a clean error, not a crash
        p = subprocess.run([sys.executable, CHECKER, "--md", "/nonexistent.md",
                            "--csv", "/nonexistent.csv"], capture_output=True, text=True)
        if p.returncode == 2:
            ok("B. a missing artifact exits 2 (unreadable) instead of crashing")
        else:
            bad("B. a missing artifact exits 2 (unreadable) instead of crashing",
                f"exit={p.returncode}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILURES:
        print(f"FAILED — {len(FAILURES)} of {len(PASSED) + len(FAILURES)} checks failed:")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    print(f"OK — {len(PASSED)} checks passed.")
    sys.exit(0)


if __name__ == "__main__":
    main()
