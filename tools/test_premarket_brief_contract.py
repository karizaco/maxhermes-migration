#!/usr/bin/env python3
"""
test_premarket_brief_contract.py — prove the cron #26 brief contract is SATISFIABLE
and that `check_premarket_brief.py` actually catches a breach.

WHY
---
A checker that only ever fails is a checker nobody trusts, and a contract nobody can
satisfy is a contract that gets skipped ("the checker is broken" is how a gate becomes
decoration). This test does both:

  1. builds a synthetic brief + CSV in the shape of the 2026-11-03 artifact — the
     Bottom line, the level columns, the date-independent CSV header, the yesterday
     loop — and requires the checker to exit 0;
  2. then MUTATES that artifact sixteen different ways, one per contract clause, and
     requires the checker to fail EVERY time.

USAGE
    python3 tools/test_premarket_brief_contract.py

EXIT CODES
    0 = the contract is satisfiable and the checker bites on every mutation
    1 = a breach was not caught, or a contract cannot be met
"""
from __future__ import annotations

import csv
import io
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CK = ROOT / "tools" / "check_premarket_brief.py"

CSV_COLUMNS = [
    "ticker", "name", "premarket_last", "premarket_high", "premarket_low",
    "prior_close", "gap_pct", "prior_session_change_pct", "premarket_volume",
    "avg_volume_30d", "pct_of_adv", "market_cap", "sector", "exchange",
    "liquid_screen", "quality_screen", "has_news", "key_level", "invalidation",
    "setup_theme", "setup_published",
]

ROWS = [
    # ticker, name, pm_last, pm_high, pm_low, prior_close, gap_pct, sess_chg,
    # pm_vol, adv, pct_adv, cap, sector, exchange, liquid, quality, news,
    # key_level, invalidation, theme, published
    ["AMD", "Advanced Micro Devices", 452.02, 477.77, 450.10, 404.40, 11.78,
     -17.26, 1282734, 23659987, 5.42, 660172878478, "Technology", "NASDAQ",
     "pass", "pass", "yes", "477.77",
     "below 450.10 - the gap filled", "C1 Semis", "yes"],
    ["MRVL", "Marvell Technology", 151.32, 156.70, 150.00, 133.55, 13.31,
     -16.43, 1005470, 25582543, 3.93, 117110000496, "Technology", "NASDAQ",
     "pass", "pass", "yes", "156.70",
     "below 150.00 - the gap filled", "C1 Semis", "yes"],
    ["INTC", "Intel", 62.20, 63.10, 61.40, 59.97, 3.72, -8.81, 990000,
     25582543, 3.87, 317008000000, "Technology", "NASDAQ", "pass", "pass", "no",
     "59.97", "a trade back to or below 59.97 - the gap filled", "", "no"],
]

buf = io.StringIO()
w = csv.writer(buf, lineterminator="\n")
w.writerow(CSV_COLUMNS)
for row in ROWS:
    w.writerow(row)
CSV_TEXT = buf.getvalue()

MD = """# Agentic Pre-Market Brief — 2026-11-06 (Friday)

---
date: 2026-11-06
cron: 26-agentic-pre-market-brief
contract: premarket-brief-artifact-v2
fire_time_et: 2026-11-06 08:30
snapshot_et: 08:42
source: TradingView america scanner + MCP-bridge market-recap
status: ok
themes: 1
up_3pct: 1
down_3pct: 1
---

## Bottom line

1. **The one setup** — AMD above 452.02 pre-market, invalidated by a trade back below 450.10.
2. **The one risk** — the 08:30 ET print is the last one before the 09:30 ET cash open, so a gap that fades costs the fill.
3. **The one thing to watch** — 404.40, the prior close: AMD holds above it and the gap is real.

## Yesterday's brief — what happened

Reviewed the **2026-11-05** pre-market brief. "Yesterday's close" is the close of the last
completed regular session (**2026-11-05**); "Today's move" is that session's % change vs its own
prior close.

| Name | Setup (yesterday) | Yesterday's close | Today's move | Thesis held? |
|---|---|---|---|---|
| NVDA | C5 AI complex | 181.60 | -9.26% | BROKE (the level 206.69 was traded through on 2026-11-05) |
| MRVL | C1 Semis | 133.55 | -16.43% | HELD (the level 133.55 held) |

## 1. TL;DR — one theme, clustered

1. **The AI complex sold off again.** **AMD -17.26%** Monday, **MRVL -16.43%**.

## 2. Theme clusters

### C1 — Semis

| Ticker | Prior close | Pre-market last | Gap % | PM range | Key level | Invalidation |
|---|---|---|---|---|---|---|
| AMD | 404.40 | 452.02 | +11.78% | 450.10 - 477.77 | 477.77 | below 450.10 - the gap filled |
| MRVL | 133.55 | 151.32 | +13.31% | 150.00 - 156.70 | 156.70 | below 150.00 - the gap filled |

## 3. Pre-market gaps — top 25 market-wide

| Ticker | Name | Prior close | Pre-market last | Gap % | PM range | Key level | Invalidation | Pm vol | %ADV | Mkt cap |
|---|---|---|---|---|---|---|---|---|---|---|
| **MRVL** | Marvell Technology | 133.55 | 151.32 | +13.31% | 150.00 - 156.70 | 156.70 | below 150.00 - the gap filled | 1,005,470 | 3.9% | 117,110M |

## 4. Top losers — top 10 market-wide

| Ticker | Name | Prior close | Pre-market last | Gap % | PM range | Key level | Invalidation | Pm vol | %ADV | Mkt cap |
|---|---|---|---|---|---|---|---|---|---|---|
| **INTC** | Intel | 59.97 | 62.20 | +3.72% | 61.40 - 63.10 | 63.10 | below 61.40 - the gap filled | 990,000 | 3.9% | 317,008M |

## 5. StockTwits lead read

| Ticker | Trending | Thesis |
|---|---|---|
| AMD | #3 | the referee tonight |

## 7. Overnight — futures, indices, FX, crypto

SPX futures +0.2%.

## 8. Macro calendar

- 10:00 ET, no major releases.

## 9. Earnings today

Nothing material.

## 10. Source health

- TradingView america scanner: ok
- MCP bridge market-recap: ok
- companion CSV: `daily-briefs/2026-11-06-pre-market.csv` (21 columns, 3 rows)

## 11. Open research queue

- Nothing carried.
"""


def run_checker(md_text: str, csv_text: str) -> tuple[int, str]:
    with tempfile.TemporaryDirectory() as td:
        md = os.path.join(td, "b.md")
        csvp = os.path.join(td, "b.csv")
        with open(md, "w", encoding="utf-8") as fh:
            fh.write(md_text)
        with open(csvp, "w", encoding="utf-8") as fh:
            fh.write(csv_text)
        proc = subprocess.run([sys.executable, str(CK), "--md", md, "--csv", csvp],
                              capture_output=True, text=True)
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def md_without_bottom_line(text: str) -> str:
    out, skip = [], False
    for ln in text.split("\n"):
        if ln.startswith("## Bottom line"):
            skip = True
            continue
        if skip and ln.startswith("## "):
            skip = False
        if not skip:
            out.append(ln)
    return "\n".join(out)


def md_with_bottom_line_after_tldr(text: str) -> str:
    """Move the whole `## Bottom line` block to just after the `## 1. TL;DR` heading."""
    lines = text.split("\n")
    block, rest, skip = [], [], False
    for ln in lines:
        if ln.startswith("## Bottom line"):
            skip = True
            block.append(ln)
            continue
        if skip:
            if ln.startswith("## "):
                skip = False
            else:
                block.append(ln)
                continue
        rest.append(ln)
    out = []
    for ln in rest:
        out.append(ln)
        if ln.startswith("## 1. TL;DR"):
            out.append("")
            out.extend(block)
            out.append("")
    return "\n".join(out)


MUTATIONS = []


def mutation(name):
    def deco(fn):
        MUTATIONS.append((name, fn))
        return fn
    return deco


@mutation("the Bottom line section is deleted")
def m1(t, c):
    return md_without_bottom_line(t), c


@mutation("the Bottom line has only two lines")
def m2(t, c):
    return t.replace("3. **The one thing to watch** — 404.40, the prior close: AMD holds "
                      "above it and the gap is real.\n", ""), c


@mutation("the Bottom line labels are not the contract's")
def m3(t, c):
    return t.replace("**The one setup**", "**The best idea**"), c


@mutation("the Bottom line sits below the theme TL;DR")
def m4(t, c):
    return md_with_bottom_line_after_tldr(t), c


@mutation("the setup line carries no level and no invalidation")
def m5(t, c):
    return t.replace("1. **The one setup** — AMD above 452.02 pre-market, invalidated by a "
                      "trade back below 450.10.",
                      "1. **The one setup** — AMD is the referee tonight."), c


@mutation("a level column is missing from the theme-cluster table")
def m6(t, c):
    return t.replace("| Ticker | Prior close | Pre-market last | Gap % | PM range | Key level "
                      "| Invalidation |\n|---|---|---|---|---|---|---|",
                      "| Ticker | Prior close | Pre-market last | Gap % | PM range |\n"
                      "|---|---|---|---|---|"), c


@mutation("a published name has an empty invalidation")
def m7(t, c):
    return t.replace("| AMD | 404.40 | 452.02 | +11.78% | 450.10 - 477.77 | 477.77 | below "
                      "450.10 - the gap filled |",
                      "| AMD | 404.40 | 452.02 | +11.78% | 450.10 - 477.77 | 477.77 |  |"), c


@mutation("a published gap disagrees with the CSV")
def m8(t, c):
    return t.replace("| AMD | 404.40 | 452.02 | +11.78% |", "| AMD | 404.40 | 452.02 | "
                      "+99.99% |"), c


@mutation("a published name is not in the CSV")
def m9(t, c):
    return t.replace("| MRVL | 133.55 | 151.32 | +13.31% | 150.00 - 156.70 | 156.70 | below "
                      "150.00 - the gap filled |",
                      "| ZZZZ | 133.55 | 151.32 | +13.31% | 150.00 - 156.70 | 156.70 | below "
                      "150.00 - the gap filled |"), c


@mutation("the CSV header is missing a promised column")
def m10(t, c):
    head = ",".join(CSV_COLUMNS) + "\n"
    return t, c.replace(head, head.replace("key_level,", ""), 1)


@mutation("the CSV header carries a date-named column")
def m11(t, c):
    # appended at the END so the other columns stay aligned — this isolates the
    # date-named-column rule instead of shifting every value.
    lines = c.split("\n")
    out = [lines[0] + ",nov_2_change_pct"]
    for ln in lines[1:]:
        out.append(ln + "," if ln.strip() else ln)
    return t, "\n".join(out)


@mutation("a setup row has an empty key_level")
def m12(t, c):
    lines = c.split("\n")
    for i, ln in enumerate(lines):
        if ln.startswith("AMD,"):
            cells = ln.split(",")
            cells[CSV_COLUMNS.index("key_level")] = ""
            lines[i] = ",".join(cells)
            break
    return t, "\n".join(lines)


@mutation("the yesterday section is missing")
def m13(t, c):
    out, skip = [], False
    for ln in t.split("\n"):
        if ln.startswith("## Yesterday's brief"):
            skip = True
            continue
        if skip and ln.startswith("## "):
            skip = False
        if not skip:
            out.append(ln)
    return "\n".join(out), c


@mutation("the yesterday table has no Thesis held? column")
def m14(t, c):
    return t.replace("| Name | Setup (yesterday) | Yesterday's close | Today's move | "
                      "Thesis held? |",
                      "| Name | Setup (yesterday) | Yesterday's close | Today's move | Note |"), c


@mutation("a yesterday verdict is outside the vocabulary")
def m15(t, c):
    return t.replace("| HELD (the level 133.55 held) |", "| PROBABLY |"), c


@mutation("a published invalidation carries a level but no side")
def m17(t, c):
    lines = c.split("\n")
    for i, ln in enumerate(lines):
        if ln.startswith("AMD,"):
            cells = ln.split(",")
            cells[CSV_COLUMNS.index("invalidation")] = "450.10"
            lines[i] = ",".join(cells)
            break
    return t, "\n".join(lines)


@mutation("the contract marker is missing")
def m16(t, c):
    return t.replace("contract: premarket-brief-artifact-v2\n", ""), c


def main() -> int:
    if not CK.exists():
        print(f"FAIL missing checker: {CK}")
        return 1

    rc, out = run_checker(MD, CSV_TEXT)
    if rc != 0:
        print("FAIL the synthetic compliant artifact does NOT pass the checker:")
        print(out)
        return 1
    print("ok   the synthetic compliant artifact passes the checker")

    failures = []
    for name, fn in MUTATIONS:
        m_md, m_csv = fn(MD, CSV_TEXT)
        rc, out = run_checker(m_md, m_csv)
        if rc == 0:
            failures.append(name)
            print(f"  FAIL not caught: {name}")
        else:
            first = ""
            for ln in out.split("\n"):
                if ln.strip().startswith("- ["):
                    first = ln.strip()[:150]
                    break
            print(f"  ok   caught: {name}  -> {first}")

    print()
    if failures:
        print(f"CONTRACT TEST FAILED — {len(failures)} breach(es) not caught:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"CONTRACT TEST OK — the contract is satisfiable and {len(MUTATIONS)} breaches "
          f"were all caught.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
