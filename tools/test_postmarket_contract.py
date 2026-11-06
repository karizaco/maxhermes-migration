#!/usr/bin/env python3
"""
test_postmarket_contract.py — prove the cron #23 post-market brief contract is
satisfiable AND that the checker actually catches a breach.

Why
---
A checker that only ever fails is a checker nobody trusts, and a contract nobody can
satisfy is a contract that gets skipped. This test does both:

  1. builds a synthetic artifact in the shape of the real 2026-11-05 brief (a violent
     down day, a real participation read, a real cap-weight penalty history, a real
     after-hours tape with levels),
  2. runs `check_postmarket_brief.py` over it and over a matching reply, and requires
     exit 0,
  3. then MUTATES that artifact and that reply a dozen different ways and requires the
     checker to fail each time.

USAGE
    python3 tools/test_postmarket_contract.py
Exit codes: 0 = all good; 1 = a breach was not caught (or the contract cannot be met).
"""

import importlib.util
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CK_PATH = ROOT / "tools" / "check_postmarket_brief.py"

PASS = "PASS"
FAIL = "FAIL"

spec = importlib.util.spec_from_file_location("ck", CK_PATH)
ck = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ck)


# ----------------------------------------------------------------------------------
# the contract-shaped artifact (the shape of the real 2026-11-05 brief)
# ----------------------------------------------------------------------------------
ARTIFACT = """---
date: 2026-11-05
cron: 23-agentic-post-market-brief
contract: postmkt-artifact-v2
fire_time_et: 22:30
snapshot_et: 22:30-22:50
session: 460320794116301
scheduled_at_ms: 1793935800000
status: ok
source: bridge market-recap + TradingView scanner + us-eod CSV + web
primary_source: bridge market-recap for closes/movers/history
universe: 4,896 US-listed names (cron #20 us-eod/2026-11-05.csv)
---

# Post-market brief — Thursday, 5 November 2026

## TL;DR

**Participation was the story.** 666 advancers, 4,145 decliners and 29 unchanged in the
4,896-name universe; `median_name_move_pct` -3.02%. The cap-weighted index fell further
than the equal-weight index — `cap_weight_penalty_bp` -152 — and the liquid set ran
`liquid_adv_dec_ratio` 0.16:1. The index was carried by a handful of mega-caps and the
median stock was not.

## Tomorrow's setup — Friday, 6 November 2026

### Futures and the overnight setup

| Contract | Level | % |
|---|---|---|
| ES=F | 7,395.50 | +0.17% |
| NQ=F | 27,015.25 | +0.95% |

### Economic calendar

| Time | Event | Consensus | Prior |
|---|---|---|---|
| 08:30 | Employment Situation (Oct payrolls) | +65K | +29K |

### Earnings calendar

Before the close: MRVL, QCOM, NET.

### News to watch for the top movers

- **NVDA** — the heaviest index drag; watch whether it holds the 200-day.

### Tomorrow's three things to watch

- MRVL — 168.40 gap-fill, 171.20 prior close — reports before the open; the guide is the tell.
- QCOM — 171.20 — reports AMC, EPS est 2.20; guidance decides the open.
- NET — 120.55 — Q4 guide 845.00m vs 798.00m cons; the first AI-adjacent print of the week.

## Day's tape

### Market read

| Metric | Value | Read |
|---|---|---|
| advancers | 666 | names closing higher |
| decliners | 4,145 | names closing lower |
| unchanged | 29 | names closing flat |
| median_name_move_pct | -3.02% | the median move of the universe |
| cap_weight_penalty_bp | -152 | SPY -4.41% vs RSP -2.89% |
| liquid_adv_dec_ratio | 0.16 : 1 | cap > $2B, 1,627 names |

### Cap-weight penalty — 5-day history

| Session | SPY % | RSP % | cap_weight_penalty_bp |
|---|---|---|---|
| 2026-10-29 | -0.38 | +1.20 | -158 |
| 2026-10-30 | -1.77 | -0.79 | -99 |
| 2026-11-02 | -0.48 | +0.77 | -124 |
| 2026-11-03 | +0.30 | -0.33 | +63 |
| 2026-11-04 | +1.65 | +1.86 | -20 |

### Index, ETF and volatility levels

| Instrument | Close | Change |
|---|---|---|
| S&P 500 | 7,353.73 | -4.36% |

## Sector rotation

| Rank | Sector | Cap-weighted | Median | n |
|---|---|---|---|---|
| 1 | Communication Services | -0.59% | -0.41% | 96 |

## After-hours movers

TradingView scanner extended-hours prints, captured ~22:50 ET. Levels in the after-hours
session.

| ticker | prior_close | ah_last | ah_high | ah_low | ah_volume | gap_pct | ah_range_pct | gap_fill_level | Catalyst |
|---|---|---|---|---|---|---|---|---|---|
| ETON | 12.40 | 15.25 | 15.40 | 12.30 | 1.21M | +23.01% | 25.00% | 13.85 | Q3 results |
| DKNG | 36.20 | 28.15 | 29.00 | 27.90 | 4.02M | -22.24% | 3.04% | 36.20 | FY26 EBITDA cut |

## After-hours earnings reactions

- **ETON +23.01% AH** — Q3 revenue above the high end of guidance.

## Open research queue

1. **Is the AI repricing political or fundamental?** It hangs on one assumption. What would
   resolve it: the Nov 10 CPI and the 9-13 November hyperscaler earnings run.

## Source health

| Source | Status |
|---|---|
| bridge market-recap | ok |
| TradingView scanner | ok |

## Method notes

After-hours prints are the settled 20:00 ET tape. Session volumes are post-close snapshots.
"""

REPLY = """Thursday was the worst US session since the April 2025 tariff crash: the S&P 500 fell
4.36% to 7,353.73 and the Philadelphia Semiconductor Index lost 12.2%. The participation read
is the story — 666 advancers against 4,145 decliners, with a -152bp cap-weight penalty.

### Signal

| Instrument | Close | Change |
|---|---:|---:|
| S&P 500 | 7,353.73 | **-4.36%** |

- APP +31.04% — record Q3, revenue 2.18bn versus 2.07bn consensus.
- NVDA -9.26% — the heaviest index drag; closed on its session low.
- VCYT -54.30% — Decipher Prostate volume miss; revenue guidance trimmed.

### Tomorrow's three things to watch

- MRVL — 168.40 gap-fill, 171.20 prior close — reports before the open; the guide is the tell.
- QCOM — 171.20 — reports AMC, EPS est 2.20; guidance decides the open.
- NET — 120.55 — Q4 guide 845.00m vs 798.00m cons.

### Method & caveats

- Open research queue: is the AI repricing political or fundamental? What would resolve it —
  the Nov 10 CPI and the 9-13 November hyperscaler earnings run.
- Sources: bridge market-recap, TradingView scanner, the published watchlist file, CBOE.

### Files

- /workspace/daily-briefs/2026-11-05-post-market.md

### Push / errors

push: ok (verified)
errors: 0
"""


# ----------------------------------------------------------------------------------
# mutations — each must be CAUGHT
# ----------------------------------------------------------------------------------
def m_setup_after_tape(txt):
    """'Tomorrow's setup' buried under 'Day's tape' again (the 2026-11-03 defect).

    The two H2 titles are swapped in place, so every section still exists — only the
    ORDER breaks, which is exactly the defect the contract is about.
    """
    return (txt.replace("## Tomorrow's setup", "@@A@@")
               .replace("## Day's tape", "## Tomorrow's setup")
               .replace("@@A@@", "## Day's tape"))


def m_drop_ah_column(txt):
    """The after-hours table loses its `ah_high` column."""
    return txt.replace("| ah_high |", "| — |")


def m_blank_ah_cell(txt):
    """An after-hours row ships with a blank level cell."""
    return txt.replace("| ETON | 12.40 | 15.25 | 15.40 |", "| ETON | 12.40 | 15.25 |  |")


def m_drop_metric_row(txt):
    """The participation read loses its cap-weight penalty row."""
    return re.sub(r"\| cap_weight_penalty_bp \|[^\n]*\n", "", txt, count=1)


def m_short_history(txt):
    """The cap-weight penalty ships without its 5-day history."""
    lines = txt.splitlines()
    out, dropped = [], 0
    for line in lines:
        if line.startswith("| 2026-") and dropped < 2:
            dropped += 1
            continue
        out.append(line)
    return "\n".join(out) + "\n"


def m_tldr_loses_metric(txt):
    """The TL;DR stops naming the cap-weight penalty."""
    return txt.replace("`cap_weight_penalty_bp` -152", "a 152bp penalty")


def m_extra_h2(txt):
    """A stray top-level section reappears."""
    return txt.replace("## Sector rotation", "## Breadth & volatility\n\nstale\n\n## Sector rotation")


def m_two_things(txt):
    """'Tomorrow's three things to watch' ships with only two items."""
    return txt.replace(
        "- NET — 120.55 — Q4 guide 845.00m vs 798.00m cons; the first AI-adjacent print of the week.\n",
        "")


def m_reply_signal_bolted(txt):
    """`### Signal` jammed onto the first bullet (the 2026-11-03 reply defect)."""
    return txt.replace("### Signal\n\n| Instrument", "### Signal- **APP +31.04%**\n| Instrument")


def m_reply_three_tickers(txt):
    """Three tickers crammed onto one Signal bullet."""
    return txt.replace(
        "- VCYT -54.30% — Decipher Prostate volume miss; revenue guidance trimmed.",
        "- VCYT -54.30% — Decipher Prostate volume miss; AMD and MU read-across too.")


def m_reply_no_tomorrow(txt):
    """The reply has no 'tomorrow' line at all (the 2026-11-04 reply defect)."""
    start = txt.index("### Tomorrow's three things to watch")
    end = txt.index("### Method & caveats")
    return txt[:start] + txt[end:]


def m_reply_no_level(txt):
    """A 'three things to watch' bullet has a name and a catalyst but no level."""
    return txt.replace(
        "- QCOM — 171.20 — reports AMC, EPS est 2.20; guidance decides the open.",
        "- QCOM — reports AMC; guidance decides the open.")


def m_split_ah_tables(txt):
    """The movers are split into a gainers table and a losers table, and the losers
    table loses a level column. The FIRST table still complies."""
    old = """| ticker | prior_close | ah_last | ah_high | ah_low | ah_volume | gap_pct | ah_range_pct | gap_fill_level | Catalyst |
|---|---|---|---|---|---|---|---|---|---|
| ETON | 12.40 | 15.25 | 15.40 | 12.30 | 1.21M | +23.01% | 25.00% | 13.85 | Q3 results |
| DKNG | 36.20 | 28.15 | 29.00 | 27.90 | 4.02M | -22.24% | 3.04% | 36.20 | FY26 EBITDA cut |"""
    new = """| ticker | prior_close | ah_last | ah_high | ah_low | ah_volume | gap_pct | ah_range_pct | gap_fill_level | Catalyst |
|---|---|---|---|---|---|---|---|---|---|
| ETON | 12.40 | 15.25 | 15.40 | 12.30 | 1.21M | +23.01% | 25.00% | 13.85 | Q3 results |

| ticker | prior_close | ah_last | ah_high | ah_volume | gap_pct | ah_range_pct | gap_fill_level |
|---|---|---|---|---|---|---|---|
| DKNG | 36.20 | 28.15 | 29.00 | 4.02M | -22.24% | 3.04% | 36.20 |"""
    assert old in txt
    return txt.replace(old, new)


def v_extra_table_in_market_read(txt):
    """A legal variation: the market-read section carries an extra table before the
    metrics table. It must STILL PASS."""
    return txt.replace("""### Market read

| Metric | Value | Read |""", """### Market read

| Session | Index | Close |
|---|---|---|
| 2026-11-05 | S&P 500 | 7,353.73 |

| Metric | Value | Read |""")


MUTATIONS = [
    ("artifact: Tomorrow's setup buried under Day's tape", m_setup_after_tape, False),
    ("artifact: after-hours table loses ah_high", m_drop_ah_column, False),
    ("artifact: after-hours row with a blank level cell", m_blank_ah_cell, False),
    ("artifact: market-read table loses cap_weight_penalty_bp", m_drop_metric_row, False),
    ("artifact: cap-weight history shorter than 5 sessions", m_short_history, False),
    ("artifact: TL;DR stops naming the metric", m_tldr_loses_metric, False),
    ("artifact: an unexpected ## section", m_extra_h2, False),
    ("artifact: only two things to watch", m_two_things, False),
    ("artifact: a split losers table loses a level column", m_split_ah_tables, False),
    ("reply: ### Signal jammed onto the first bullet", m_reply_signal_bolted, True),
    ("reply: three tickers on one Signal bullet", m_reply_three_tickers, True),
    ("reply: no 'tomorrow' section", m_reply_no_tomorrow, True),
    ("reply: a 'three things' bullet with no level", m_reply_no_level, True),
]


def run_checker(artifact, reply):
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(artifact)
        a_path = fh.name
    r_path = None
    if reply is not None:
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False,
                                         encoding="utf-8") as fh:
            fh.write(reply)
            r_path = fh.name
    try:
        cmd = [sys.executable, str(CK_PATH), "--artifact", a_path]
        if r_path:
            cmd += ["--reply", r_path]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    finally:
        os_unlink(a_path)
        if r_path:
            os_unlink(r_path)


def os_unlink(path):
    import os
    try:
        os.unlink(path)
    except OSError:
        pass


def main():
    results = []

    # --- the contract must be satisfiable -----------------------------------------
    code, out = run_checker(ARTIFACT, REPLY)
    if code == 0:
        results.append((PASS, "the contract-shaped artifact and reply pass", ""))
    else:
        results.append((FAIL, "a contract-shaped artifact FAILS the checker", out.strip()[:400]))

    # --- a legal variation must still PASS ------------------------------------------
    code, out = run_checker(v_extra_table_in_market_read(ARTIFACT), REPLY)
    if code == 0:
        results.append((PASS, "an extra table in the market-read section still passes", ""))
    else:
        results.append((FAIL, "a legal variation FAILS the checker", out.strip()[:400]))

    # --- every breach must be caught ------------------------------------------------
    for name, mutate, is_reply in MUTATIONS:
        if is_reply:
            art, rep = ARTIFACT, mutate(REPLY)
        else:
            art, rep = mutate(ARTIFACT), REPLY
        code, out = run_checker(art, rep)
        if code != 0:
            first = ""
            for line in out.splitlines():
                if "FAIL:" in line:
                    first = line.strip()
                    break
            results.append((PASS, f"caught: {name}", first))
        else:
            results.append((FAIL, f"NOT caught: {name}", "the checker returned exit 0"))

    print("=" * 78)
    print("cron #23 post-market brief artifact contract — regression test")
    print("=" * 78)
    failures = 0
    for status, name, detail in results:
        print(f"  {status}  {name}")
        if detail:
            print(f"        {detail[:160]}")
        if status == FAIL:
            failures += 1
    print("-" * 78)
    print(f"  {len(results) - failures}/{len(results)} checks behaved correctly")
    if failures:
        print(f"  RESULT: {failures} problem(s)")
        return 1
    print("  RESULT: the contract is satisfiable and every breach is caught")
    return 0


if __name__ == "__main__":
    sys.exit(main())
