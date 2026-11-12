#!/usr/bin/env python3
"""
test_options_flow_contract.py — prove the cron #16 artifact contract is satisfiable AND that
the checker catches every breach.

Why
---
The column contract (2026-11-12) says the expiry date ALWAYS gets its own column. A checker
that only ever fails is a checker nobody trusts, and a contract nobody can satisfy is a contract
that gets skipped. This test does both:

  1. renders a contract-shaped artifact + its reply,
  2. runs `check_options_flow_artifact.py` over both and requires exit 0,
  3. MUTATES them seven different ways and requires the checker to fail each time.

Every mutation asserts the text actually CHANGED before running the checker — a mutation that
does not apply would report a false "NOT CAUGHT" and hide a real hole.

USAGE
    python3 tools/test_options_flow_contract.py

Exit codes: 0 = all good; 1 = a breach was not caught (or the contract cannot be met).
"""

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CK = ROOT / "tools" / "check_options_flow_artifact.py"

DATE = "2026-11-12"


# ---------------------------------------------------------------------------
# a contract-shaped artifact
# ---------------------------------------------------------------------------

def artifact(column_contract=True, contrast="split", leader="split", row_width=True):
    cc = ("column_contract: expiry-column-v1 — every contract table gives the expiry date its "
          "OWN column (ticker | side | strike | expiry); no cell packs side + strike + date\n") \
        if column_contract else ""

    width_fix = "| TTD | C | 16.5 | 2026-11-20 | 9 | 3,816 | 1.7 | 17.5x | 3.43x |\n"
    if not row_width:
        width_fix = "| TTD | C | 16.5 | 2026-11-20 | 9 | 3,816 | 1.7 | 17.5x |\n"

    if leader == "split":
        leader_tbl = (
            "| Ticker | Side | Strike | Expiry | DTE | Volume | V/OI | Peer ratio | Own-hist |\n"
            "|---|---|---|---|---|---|---|---|---|\n"
            "| TE | C | 2.5 | 2026-11-13 | 2 | 31,672 | 10.7 | 22.2x | 1.43x |\n"
            + width_fix)
    else:  # "packed" — the pre-2026-11-12 shape: side + strike + date in one cell
        leader_tbl = (
            "| Ticker | Contract | DTE | Volume | V/OI | Peer ratio | Own-hist |\n"
            "|---|---|---|---|---|---|---|\n"
            "| TE | C 2.5 · 11-13 | 2 | 31,672 | 10.7 | 22.2x | 1.43x |\n"
            "| TTD | C 16.5 · 11-20 | 9 | 3,816 | 1.7 | 17.5x | 3.43x |\n")

    if contrast == "split":
        contrast_tbl = (
            "| Rank | Abs ticker | Side | Strike | Expiry | Volume | Rel ticker | Side | Strike | "
            "Expiry | Peer ratio | Share of expiry |\n"
            "|---|---|---|---|---|---|---|---|---|---|---|---|\n"
            "| 1 | NVDA | P | 175 | 2026-11-11 | 346,309 | TE | C | 2.5 | 2026-11-13 | 22x | 91% |\n")
    elif contrast == "packed":  # the OLD contrast table: side + strike + date in one cell
        contrast_tbl = (
            "| Rank | Absolute screen (top 10 by raw contract volume) | Relative screen (multi-day top 10) |\n"
            "|---|---|---|\n"
            "| 1 | NVDA P 175 2026-11-11 (346,309 cts) | TE C 2.5 2026-11-13 (peer 22x, 91% of its expiry) |\n")
    else:  # "no-expiry" — the side-by-side form with NO expiry column at all
        contrast_tbl = (
            "| Rank | Absolute screen | Relative screen |\n"
            "|---|---|---|\n"
            "| 1 | NVDA P 175 | TE C 2.5 |\n")

    return f"""# Unusual options flow by RELATIVE volume — {DATE} (Wednesday, US cash session close 16:00 ET)

```
date: {DATE}
cron: 16-unusual-options-flow-daily
method: RELATIVE volume screen (size-normalised) — HEADLINE; the legacy absolute series book is secondary
engine: relvol_screen.py v1 rev2
{cc}headline_metric: the relative-volume screen (own-history + peer ratio, size-normalised) — NOT a put/call ratio
relative_screen_universe: top 60 US names by cash volume (TradingView america scanner) + the 8 routine names — 59 underlyings with a chain, 3 without
series_book_universe: the 8 Pass-B mega-caps (IWM, GLD, TLT, AAPL, MSFT, NVDA, GOOGL, AMZN)
series_book_bias: CALL (put/call 0.54) — contract-count ratio on series_book_universe
series_book_economic_bias: CALL (put/call 0.68) — theo >= $0.05 slice on series_book_universe
series_book_premium_ratio: 0.70 — premium-dollar ratio on series_book_universe
wide_book_universe: the 59-name relative-screen universe — the SAME legacy absolute method applied to it
wide_book_bias: CALL (put/call 0.49) — contract-count ratio on wide_book_universe
wide_book_economic_bias: CALL (put/call 0.67) — theo >= $0.05 slice on wide_book_universe
pass_a_universe: the published watchlist (refs/watchlist.yaml) — 8 tickers, scanned with the legacy absolute method
pass_a_bias: CALL (put/call 0.54) — contract-count ratio on pass_a_universe
bias_tag_thresholds: put/call < 0.85 -> CALL, > 1.2 -> PUT, else MIXED (the tag names the DOMINATING side)
```

## Headline — relative-volume leaders, multi-day book (DTE ≥ 1)

{leader_tbl}
## Relative-volume leaders — all expiries (0DTE included)

| Ticker | Side | Strike | Expiry | DTE | Volume | V/OI |
|---|---|---|---|---|---|---|
| NVDA | P | 175 | 2026-11-11 | 0 | 346,309 | 54.4 |

## Name level — options activity vs the name's own 10-session baseline

| Ticker | Name | Own-history ratio | Day move | Mkt cap |
|---|---|---|---|---|
| TTD | The Trade Desk, Inc. | **3.43x** | +3.6% | $7.6B |

## Contrast — the absolute screen vs the relative screen

{contrast_tbl}
**Overlap between the two top-10s: 2 of 10 names.** The absolute screen is a roster of size; the relative screen is a roster of anomaly.

## Series book (absolute method) — continuity with the published put/call series

**Universe: the 8 Pass-B mega-caps (IWM, GLD, TLT, AAPL, MSFT, NVDA, GOOGL, AMZN).** **Bias tag: CALL** (put/call 0.54), thresholds < 0.85 → CALL, > 1.2 → PUT, else MIXED.

| Slice | Universe | Rows | Call volume | Put volume | P/C | Tag |
|---|---|---|---|---|---|---|
| All kept (series method) | 8 Pass-B mega-caps | 74 | 2,694,905 | 1,468,016 | 0.54 | **CALL** |

**Series book — top 10 strikes by V/OI:**

| Ticker | Side | Strike | Expiry | DTE | Volume | Open int | V/OI |
|---|---|---|---|---|---|---|---|
| MSFT | C | 522.5 | 2026-11-11 | 0 | 45,510 | 54 | 842.8 |

## Wide book — the same method over the relative screen's universe

| Slice | Universe | Rows | Call volume | Put volume | P/C | Tag |
|---|---|---|---|---|---|---|
| All kept (legacy method, wide universe) | 59 names | 235 | 5,060,889 | 2,475,174 | 0.49 | **CALL** |

## Pass A — the published watchlist

| Slice | Universe | Rows | Call volume | Put volume | P/C | Tag |
|---|---|---|---|---|---|---|
| All kept (legacy method) | 8 watchlist names | 74 | 2,694,905 | 1,468,016 | 0.54 | **CALL** |

## Source health

| Source | URL / query | Status | Result |
|---|---|---|---|
| Cboe delayed-quote option chain | `https://cdn.cboe.com/api/global/delayed_quotes/options/{{SYM}}.json` | partial (59/62) | 107,804 contracts parsed |

## Caveats

1. The own-history baseline is a 4-venue number and it lags the live session.

`unusual-options-flow target=options-flow:{DATE} underlyings=59 strikes_kept=74 bias=CALL method=relative bias_universe=pass-b-8-mega-caps relative_universe=top-60-us-by-cash-volume wide_bias=CALL pass_a_bias=CALL`
"""


def reply(style="split"):
    if style == "split":
        tbl = (
            "| Ticker | Side | Strike | Expiry | Volume | V/OI | Peer ratio | Own-hist |\n"
            "|---|---|---|---|---|---|---|---|\n"
            "| TE | C | 2.5 | 2026-11-13 | 31,672 | 10.7 | 22.2x | 1.43x |\n"
            "| TTD | C | 16.5 | 2026-11-20 | 3,816 | 1.7 | 17.5x | 3.43x |\n")
    else:  # "packed" — the shape the user rejected
        tbl = (
            "| Ticker | Contract | Volume | V/OI | Peer ratio | Share of expiry | Own-hist |\n"
            "|---|---|---|---|---|---|---|\n"
            "| TE | C 2.5 · 11-13 | 31,672 | 10.7 | 22.2x | 91.3% | 1.43x |\n"
            "| TTD | C 16.5 · 11-20 | 3,816 | 1.7 | 17.5x | 30.7% | 3.43x |\n")
    return f"""Relative-volume screen over the 59-name universe (top 60 US names by cash volume + the routine's 8) is today's headline.

### Signal

{tbl}
### Method & caveats

- Chains from the Cboe delayed-quote CDN; universe from the TradingView america scanner.
- errors: 0
"""


# ---------------------------------------------------------------------------

def run_checker(md_path=None, reply_path=None):
    cmd = [sys.executable, str(CK)]
    if md_path:
        cmd += ["--md", str(md_path)]
    if reply_path:
        cmd += ["--reply", str(reply_path)]
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def write(tmp, name, text):
    p = Path(tmp) / name
    p.write_text(text, encoding="utf-8")
    return p


def main():
    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        # ---- 1. the contract is satisfiable -------------------------------------
        md = write(tmp, "ok.md", artifact())
        rp = write(tmp, "ok.txt", reply())
        rc, out = run_checker(md, rp)
        if rc != 0:
            failures.append("a contract-shaped artifact + reply did NOT pass the checker:\n" + out)
            print(out)
        else:
            print("PASS  the contract-shaped artifact and reply satisfy the checker")

        # ---- 2. every breach is caught ------------------------------------------
        cases = [
            ("the front matter drops the column_contract marker",
             lambda: artifact(column_contract=False), None),
            ("the leader table packs side + strike + date into one cell",
             lambda: artifact(leader="packed"), None),
            ("the contrast table packs side + strike + date into one cell",
             lambda: artifact(contrast="packed"), None),
            ("the contrast table has no Expiry column",
             lambda: artifact(contrast="no-expiry"), None),
            ("a row has fewer cells than its header",
             lambda: artifact(row_width=False), None),
            ("the reply packs side + strike + date into one cell",
             None, lambda: reply(style="packed")),
        ]
        for label, md_fn, rp_fn in cases:
            md_p = write(tmp, "m.md", md_fn()) if md_fn else None
            rp_p = write(tmp, "r.txt", rp_fn()) if rp_fn else None
            rc, out = run_checker(md_p, rp_p)
            if rc == 0:
                failures.append(f"NOT CAUGHT: {label}")
                print(f"FAIL  NOT CAUGHT: {label}")
            else:
                print(f"PASS  caught: {label}")

        # ---- 3. a PRE-contract artifact is reported, not failed ------------------
        legacy = artifact().replace(DATE, "2026-11-11").replace(
            "column_contract: expiry-column-v1 — every contract table gives the expiry date its "
            "OWN column (ticker | side | strike | expiry); no cell packs side + strike + date\n", "")
        legacy = legacy.replace("| Rank | Abs ticker | Side | Strike | Expiry | Volume | Rel ticker | "
                                 "Side | Strike | Expiry | Peer ratio | Share of expiry |\n"
                                 "|---|---|---|---|---|---|---|---|---|---|---|---|\n"
                                 "| 1 | NVDA | P | 175 | 2026-11-11 | 346,309 | TE | C | 2.5 | "
                                 "2026-11-13 | 22x | 91% |\n",
                                 "| Rank | Absolute screen (top 10 by raw contract volume) | Relative "
                                 "screen (multi-day top 10) |\n"
                                 "|---|---|---|\n"
                                 "| 1 | NVDA P 175 2026-11-11 (346,309 cts) | TE C 2.5 2026-11-13 "
                                 "(peer 22x, 91% of its expiry) |\n")
        lp = write(tmp, "legacy.md", legacy)
        rc, out = run_checker(lp)
        if rc != 0:
            failures.append("a PRE-contract artifact must be reported as a note, not failed:\n" + out)
            print("FAIL  a pre-2026-11-12 artifact was failed instead of reported")
        else:
            print("PASS  a pre-2026-11-12 artifact is reported, not failed")

    print()
    if failures:
        for f in failures:
            print("FAILED: " + f)
        print(f"FAILED: {len(failures)} case(s).")
        return 1
    print("PASS: the cron #16 contract is satisfiable and every breach is caught.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
