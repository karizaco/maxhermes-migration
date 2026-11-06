#!/usr/bin/env python3
"""
test_in_play_contract.py — prove the cron #17 artifact contract is satisfiable AND
that the checker catches every breach.

Why
---
A checker that only ever fails is a checker nobody trusts, and a contract nobody can
satisfy is a contract that gets skipped. This test does both:

  1. renders a contract-shaped OPEN artifact + its CSV,
  2. runs `check_in_play_artifact.py` over it and requires exit 0,
  3. MUTATES that artifact eleven different ways and requires the checker to fail
     each time.

Every mutation is a REGEX on the field name, and the test asserts the text actually
CHANGED before running the checker — a mutation that does not apply would otherwise
report a false "NOT CAUGHT" and hide a real hole.

USAGE
    python3 tools/test_in_play_contract.py
Exit codes: 0 = all good; 1 = a breach was not caught (or the contract cannot be met).
"""

import csv
import io
import importlib.util
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CK_PATH = ROOT / "tools" / "check_in_play_artifact.py"

PASS = "PASS"
FAIL = "FAIL"


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ck = _load(CK_PATH, "ck")

CONTRACT = "in-play-artifact-v1"


# ---------------------------------------------------------------------------
# the synthetic OPEN artifact
# ---------------------------------------------------------------------------
def render_md():
    return f"""# US stocks in play — 2026-11-06 (open digest)

- **Contract:** {CONTRACT} · slot `open` · fire 2026-11-06 09:50 ET
- **Run time:** 2026-11-06 09:50 ET.
- **Slot:** `open`. The deployed schedule (`50 9,15 * * 1-5`) determines the slot, so the
  open floors apply: session $ volume ≥ ~$0.5m to 09:50, and the **pace** measure.
- **Pace basis:** `pace = (session volume to 09:50 ÷ trailing-10 FULL-session average
  volume) ÷ {ck.PACE_CONSTANT}`. The {ck.PACE_CONSTANT} constant is measured, not exact: the
  ten daily medians span **10.77% – 16.49%**, so a pace of 1.9× is really 1.8×–2.3×
  depending on the session's opening-share regime. **Treat pace as a screen, not a
  measurement.** `pace` and the pre-close slot's `RVol` are different quantities on
  different denominators and are never comparable.

---

## The headline

The tape gapped and held. Three names matter into the open.

---

## What changed since the 2026-11-05 open digest

**Delta source:** `us-stocks-in-play/2026-11-05-open.md` (the previous day's OPEN board — not
the newest file in the directory, which is the pre-close board).

| Ticker | Tier | Yesterday | Today | Change | Why |
|---|---|---|---|---|---|
| **ABC** | A → A | +1.2% | +6.4% | +5.2pp | Q3 beat, guidance raised |
| **DEF** | B → A | -3.0% | -1.1% | +1.9pp | no same-session item |

---

## Market context (09:50 ET snapshot)

| Instrument | 09:50 ET | Prior close |
|---|---|---|
| S&P 500 | 7,600.10 (-1.10%) | 7,688.62 |

---

## Overnight → open — the carry handoff from the 2026-11-05 pre-close board

**Annex source:** `us-stocks-in-play/2026-11-05.md` (the previous day's PRE-close board).

| Carry item | In play at 09:50 ET? | This morning's tape |
|---|---|---|
| **ABC** — Q3 results due | **YES** | +6.4%, pace 2.1 |

---

## What to watch at the open

| Name | Prior close | Current price | Invalidation |
|---|---|---|---|
| **ABC** | $41.20 | $43.90 | below $41.20 |
| **DEF** | $88.10 | $86.10 | below $86.50 |
| **GHI** | $12.40 | $13.02 | below $12.10 |

---

## Tier A — liquidity floor + elevated pace + material same-session catalyst (2 names)

| Ticker | 09:50 chg | Gap | $ vol to 09:50 | pace | 20-min verdict | Catalyst |
|---|---|---|---|---|---|---|
| **ABC** | +6.40% | +5.10% | 610m | 2.10 | held | Q3 beat, guidance raised |
| **DEF** | -1.10% | -2.00% | 540m | 1.90 | held | no same-session catalyst found |

---

## Soft-A — material catalyst, pace below the Tier A bar (1 name)

| Ticker | 09:50 chg | Gap | $ vol to 09:50 | pace | 20-min verdict | Catalyst |
|---|---|---|---|---|---|---|
| **GHI** | +5.00% | +4.00% | 320m | 1.20 | held | guidance reiterated |

---

## Gap annex — the first twenty minutes (09:30 → 09:50 ET)

`held` here means "the gap held for 20 minutes", NOT "held into the bell".

| Ticker | 09:50 chg | Gap | $ vol to 09:50 | pace | 20-min verdict | Catalyst |
|---|---|---|---|---|---|---|
| **ABC** | +6.40% | +5.10% | 610m | 2.10 | held | Q3 beat |
| **DEF** | -1.10% | -2.00% | 540m | 1.90 | held | no catalyst |

---

## TECH_WATCH — strong turnover, no same-session company catalyst (610 names; the top 30 by turnover are published)

| Ticker | 09:50 chg | Gap | $ vol to 09:50 | pace | 20-min verdict | Catalyst |
|---|---|---|---|---|---|---|
| **JKL** | +2.00% | +1.00% | 210m | 1.40 | held | no catalyst |

---

## Tier B — liquidity + move, no same-session catalyst (313 names; the top 25 by turnover are published)

| Ticker | 09:50 chg | Gap | $ vol to 09:50 | pace | 20-min verdict | Catalyst |
|---|---|---|---|---|---|---|
| **MNO** | +3.10% | +2.00% | 190m | 1.10 | held | no catalyst |

---

## Tier C — deal, capital-structure and no-catalyst watch (1 name)

| Ticker | 09:50 chg | Gap | $ vol to 09:50 | pace | 20-min verdict | Catalyst |
|---|---|---|---|---|---|---|
| **PQR** | +9.00% | +8.00% | 120m | 1.60 | held | merger spread widening |

---

## Source health

| Source | Status | Notes |
|---|---|---|
| TradingView scanner | ok | `halted` is null on every row → **the halt state is not measurable this session** |

---

## Method and caveats

- The pace measure is a screening measure, not a measurement. The {ck.PACE_CONSTANT}
  opening-share constant is regime-dependent (the daily median spans 10.77% and 16.49%),
  and **pace is not comparable with the pre-close slot's RVol**.

---

## Files

- `us-stocks-in-play/2026-11-06-open.md` — this digest.
- `us-stocks-in-play/2026-11-06-open-candidates.csv` — all priced and tiered names.
"""


def render_csv():
    header = ["ticker", "name", "tier", "close_0950", "chg_pct_0950", "gap_pct",
              "open_gap_pct", "session_vol_to_0950", "vol_basis_factor", "avg_vol_10d",
              "pace", "pace_basis", "session_dollar_vol_0950", "market_cap",
              "gap_verdict_20min", "chg_pct_at_run_time", "catalyst", "catalyst_materiality",
              "price_source", "has_catalyst_timestamp", "reason_without_timestamp"]
    # pace = (session_vol / avg_vol_10d) / 0.125  — exactly, so the checker reconciles it
    rows = [
        ["ABC", "Alpha Inc", "A", 43.90, 6.40, 5.10, 5.10, 13900000, 0.8912, 27053867.85,
         4.1146, f"pace = (session vol to 09:50 / trailing-10 full-session avg) / {ck.PACE_CONSTANT}",
         610230000.0, 806387935966.31, "held", 7.10, "Q3 beat, guidance raised", "A",
         "yahoo_chart_5m_0950ET", "no", "Q3 beat, guidance raised"],
        ["DEF", "Delta Co", "A", 86.10, -1.10, -2.00, -2.00, 12500000, 0.8912, 27053867.85,
         3.7008, f"pace = (session vol to 09:50 / trailing-10 full-session avg) / {ck.PACE_CONSTANT}",
         540225000.0, 806387935966.31, "held", -1.40, "no same-session catalyst found", "S",
         "yahoo_chart_5m_0950ET", "no", "no same-session catalyst found"],
        ["GHI", "Gamma Ltd", "SOFT_A", 13.02, 5.00, 4.00, 4.00, 4000000, 0.8912, 27053867.85,
         1.1826, f"pace = (session vol to 09:50 / trailing-10 full-session avg) / {ck.PACE_CONSTANT}",
         52080000.0, 806387935966.31, "held", 5.20, "guidance reiterated", "S",
         "yahoo_chart_5m_0950ET", "yes", "guidance reiterated"],
        ["JKL", "Jota Inc", "TECH_WATCH", 22.10, 2.00, 1.00, 1.00, 9000000, 0.8912, 27053867.85,
         2.6617, f"pace = (session vol to 09:50 / trailing-10 full-session avg) / {ck.PACE_CONSTANT}",
         198900000.0, 806387935966.31, "held", 2.30, "no catalyst", "T",
         "yahoo_chart_5m_0950ET", "no", "no catalyst"],
        ["MNO", "Mu Inc", "B", 15.40, 3.10, 2.00, 2.00, 12000000, 0.8912, 27053867.85,
         3.5483, f"pace = (session vol to 09:50 / trailing-10 full-session avg) / {ck.PACE_CONSTANT}",
         184800000.0, 806387935966.31, "held", 3.30, "no catalyst", "B",
         "yahoo_chart_5m_0950ET", "no", "no catalyst"],
        ["PQR", "Pi Ltd", "C", 9.80, 9.00, 8.00, 8.00, 6000000, 0.8912, 27053867.85,
         1.7743, f"pace = (session vol to 09:50 / trailing-10 full-session avg) / {ck.PACE_CONSTANT}",
         58800000.0, 806387935966.31, "held", 9.40, "merger spread widening", "T",
         "yahoo_chart_5m_0950ET", "no", "merger spread widening"],
    ]
    return header, rows


def render_preclose_md():
    return f"""# US stocks in play — 2026-11-06 (pre-close digest)

- **Contract:** {CONTRACT} · slot `preclose` · fire 2026-11-06 15:50 ET
- **Run time:** 2026-11-06 15:50 ET (settled phase re-priced after the 16:00 bell).
- **Slot:** `preclose`. The pre-close floors apply: session $ volume ≥ ~$2m, and the
  **RVol** measure on the trailing-10 full-session denominator.

---

## The headline

The board turned over into a de-rate. Twelve names matter into the close.

---

## What changed since the 2026-11-05 pre-close digest

**Delta source:** `us-stocks-in-play/2026-11-05.md` (the previous day's pre-close board).

| Ticker | Tier | Yesterday | Today | Change | Why |
|---|---|---|---|---|---|
| **ABC** | A → A | +1.2% | +6.4% | +5.2pp | Q3 beat, guidance raised |
| **DEF** | B → A | -3.0% | -1.1% | +1.9pp | no same-session item |

---

## Market context (settled, 16:00 ET)

| Instrument | Close | Prior close |
|---|---|---|
| S&P 500 | 7,600.10 (-1.10%) | 7,688.62 |

---

## Tier A — liquidity floor + elevated RVol + material same-session catalyst (1 name)

| Ticker | chg | Gap | $ vol | RVol | gap verdict | Catalyst |
|---|---|---|---|---|---|---|
| **ABC** | +6.40% | +5.10% | 610m | 2.10 | held | Q3 beat, guidance raised |

---

## Soft-A — material same-session catalyst, RVol below the Tier A bar (1 name)

| Ticker | chg | Gap | $ vol | RVol | gap verdict | Catalyst |
|---|---|---|---|---|---|---|
| **GHI** | +5.00% | +4.00% | 320m | 1.20 | held | guidance reiterated |

---

## Gap annex — what held into the bell and what faded

| Ticker | chg | Gap | $ vol | RVol | gap verdict | Catalyst |
|---|---|---|---|---|---|---|
| **ABC** | +6.40% | +5.10% | 610m | 2.10 | held | Q3 beat |

---

## TECH_WATCH — liquid technical, no same-session catalyst, trading on size (610 names; the top 30 by turnover are published)

| Ticker | chg | Gap | $ vol | RVol | gap verdict | Catalyst |
|---|---|---|---|---|---|---|
| **JKL** | +2.00% | +1.00% | 210m | 1.40 | held | no catalyst |

---

## Tier B — liquidity + move, no or weak same-session catalyst (313 names; the top 25 by turnover are published)

| Ticker | chg | Gap | $ vol | RVol | gap verdict | Catalyst |
|---|---|---|---|---|---|---|
| **MNO** | +3.10% | +2.00% | 190m | 1.10 | held | no catalyst |

---

## Tier C — deal, capital-structure and no-chase watch (1 name)

| Ticker | chg | Gap | $ vol | RVol | gap verdict | Catalyst |
|---|---|---|---|---|---|---|
| **PQR** | +9.00% | +8.00% | 120m | 1.60 | held | merger spread widening |

---

## Overnight → pre-close — the carry handoff from the 2026-11-05 pre-close board

| Carry item | In play at 15:50 ET? | This afternoon's tape |
|---|---|---|
| **ABC** — Q3 results due | **YES** | +6.4%, RVol 2.1 |

---

## Overnight carry — into Friday 2026-11-07

| Name / item | Event | When | Why it matters |
|---|---|---|---|
| **ABC** | Q3 results — after the close tonight | tonight | the name already ran +6.4% |

---

## Source health

| Source | Status | Notes |
|---|---|---|
| TradingView scanner | ok | `halted` is null on every row → **no halt count is published** |

---

## Method and caveats

- The pre-close slot's measure is **RVol** on the trailing-10 full-session denominator.
  It is a different quantity from the open slot's `pace` and the two are never comparable.

---

## Files

- `us-stocks-in-play/2026-11-06.md` — this digest.
- `us-stocks-in-play/2026-11-06-candidates.csv` — all priced and tiered names.
"""


def render_preclose_csv():
    header = ["ticker", "name", "tier", "close", "chg_pct", "open_gap_pct", "session_vol",
              "avg_vol_10d", "rvol", "rvol_basis", "session_dollar_vol", "market_cap",
              "gap_verdict", "price_source", "prior_chg_pct", "prior_tier", "delta_pp",
              "catalyst_materiality", "has_catalyst_timestamp", "reason_without_timestamp"]
    rows = [
        ["ABC", "Alpha Inc", "A", 43.90, 6.40, 5.10, 13900000, 27053867.85, 2.10,
         "session_vol / trailing-10 full-session avg", 610230000.0, 806387935966.31,
         "held", "tradingview_settled", 1.20, "B", 5.20, "A", "no",
         "Q3 beat, guidance raised"],
        ["GHI", "Gamma Ltd", "SOFT_A", 13.02, 5.00, 4.00, 4000000, 27053867.85, 1.20,
         "session_vol / trailing-10 full-session avg", 52080000.0, 806387935966.31,
         "held", "tradingview_settled", 2.00, "SOFT_A", 3.00, "S", "yes",
         "guidance reiterated"],
        ["JKL", "Jota Inc", "TECH_WATCH", 22.10, 2.00, 1.00, 9000000, 27053867.85, 2.66,
         "session_vol / trailing-10 full-session avg", 198900000.0, 806387935966.31,
         "held", "tradingview_settled", 1.10, "TECH_WATCH", 0.90, "T", "no", "no catalyst"],
        ["MNO", "Mu Inc", "B", 15.40, 3.10, 2.00, 12000000, 27053867.85, 3.55,
         "session_vol / trailing-10 full-session avg", 184800000.0, 806387935966.31,
         "held", "tradingview_settled", 1.90, "B", 1.20, "B", "no", "no catalyst"],
        ["PQR", "Pi Ltd", "C", 9.80, 9.00, 8.00, 6000000, 27053867.85, 1.77,
         "session_vol / trailing-10 full-session avg", 58800000.0, 806387935966.31,
         "held", "tradingview_settled", 0.40, "C", 8.60, "T", "no", "merger spread widening"],
    ]
    return header, rows


def write_preclose_fixture(tmpdir):
    md = os.path.join(tmpdir, "2026-11-06.md")
    csvp = os.path.join(tmpdir, "2026-11-06-candidates.csv")
    with open(md, "w", encoding="utf-8") as fh:
        fh.write(render_preclose_md())
    header, rows = render_preclose_csv()
    with open(csvp, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)
    return md, csvp


def write_fixture(tmpdir):
    md = os.path.join(tmpdir, "2026-11-06-open.md")
    csvp = os.path.join(tmpdir, "2026-11-06-open-candidates.csv")
    with open(md, "w", encoding="utf-8") as fh:
        fh.write(render_md())
    header, rows = render_csv()
    with open(csvp, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)
    return md, csvp


def run_checker(md, csvp, reply=None, slot="open"):
    cmd = [sys.executable, str(CK_PATH), "--md", md, "--csv", csvp, "--slot", slot]
    if reply:
        cmd += ["--reply", reply]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def mutate(md_text, csv_text, pattern, repl, count=0):
    """Apply a regex mutation to BOTH files. count=0 replaces every occurrence.

    Returns (new_md, new_csv) or None when the pattern matched nothing — a no-op
    mutation must be reported, never silently counted as a caught breach.
    """
    md_new, n1 = re.subn(pattern, repl, md_text, count=count, flags=re.S)
    csv_new, n2 = re.subn(pattern, repl, csv_text, count=count, flags=re.S)
    if n1 + n2 == 0:
        return None
    return md_new, csv_new


def mutate_csv(csv_text, fn):
    """Apply a row-level mutation to the CSV via the csv module (so a value that
    contains a comma or a quote is handled correctly).

    `fn(header, body)` returns (new_header, new_body)."""
    rows = list(csv.reader(io.StringIO(csv_text)))
    if not rows:
        return None
    header, body = rows[0], rows[1:]
    new_header, new_body = fn(header, body)
    if new_body == body and new_header == header:
        return None
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(new_header)
    w.writerows(new_body)
    return out.getvalue()


# ---------------------------------------------------------------------------
# the mutations: each one MUST be caught, and each one MUST actually land
# ---------------------------------------------------------------------------
def mut_no_watch_block(md, csv_text):
    res = mutate(md, csv_text,
                 r"## What to watch at the open.*?(?=## Tier A)", "")
    if res is None:
        return None
    m_md, m_csv = res
    return m_md, m_csv, lambda a, b: "## What to watch at the open" not in a


def mut_no_band(md, csv_text):
    res = mutate(md, csv_text, r"10\.77", "11.00")
    if res is None:
        return None
    m_md, m_csv = res
    return m_md, m_csv, lambda a, b: "10.77" not in a


def mut_band_one_endpoint(md, csv_text):
    """Keep only ONE endpoint of the band — the reader cannot see a spread."""
    res = mutate(md, csv_text, r"16\.49", "11.00")
    if res is None:
        return None
    m_md, m_csv = res
    return m_md, m_csv, lambda a, b: "16.49" not in a and "10.77" in a


def mut_no_constant(md, csv_text):
    res = mutate(md, csv_text, rf"\b{re.escape(str(ck.PACE_CONSTANT))}\b", "0.500")
    if res is None:
        return None
    m_md, m_csv = res
    return m_md, m_csv, lambda a, b: str(ck.PACE_CONSTANT) not in a


def mut_rvol_column_label(md, csv_text):
    """The open board labels its volume column RVol — the other slot's measure."""
    res = mutate(md, csv_text, r"\| pace \|", "| RVol |")
    if res is None:
        return None
    m_md, m_csv = res
    return m_md, m_csv, lambda a, b: "| RVol |" in a


def mut_delta_no_why(md, csv_text):
    res = mutate(md, csv_text, r"\| Why \|", "| Notes |")
    if res is None:
        return None
    m_md, m_csv = res
    return m_md, m_csv, lambda a, b: "| Why |" not in a


def mut_delta_not_a_table(md, csv_text):
    res = mutate(md, csv_text,
                 r"\| Ticker \| Tier \| Yesterday \| Today \| Change \| Why \|.*?\| \*\*DEF\*\*.*?\n",
                 "The board turned over.\n")
    if res is None:
        return None
    m_md, m_csv = res
    return m_md, m_csv, lambda a, b: "| Ticker |" not in a.split(
        "## What changed since the 2026-11-05 open digest", 1)[-1].split(
        "## Market context", 1)[0]


def mut_halt_count(md, csv_text):
    res = mutate(md, csv_text, r"the halt state is not measurable this session",
                 "halted: 0")
    if res is None:
        return None
    m_md, m_csv = res
    return m_md, m_csv, lambda a, b: "halted: 0" in a


def mut_halt_count_zero_halts(md, csv_text):
    res = mutate(md, csv_text, r"\*\*the halt state is not measurable this session\*\*",
                 "**0 halts**")
    if res is None:
        return None
    m_md, m_csv = res
    return m_md, m_csv, lambda a, b: "0 halts" in a


def mut_missing_timestamp_field(md, csv_text):
    """The CSV loses the has_catalyst_timestamp column entirely."""
    def _fn(header, body):
        if "has_catalyst_timestamp" not in header:
            return header, body
        i = header.index("has_catalyst_timestamp")
        nh = [h for j, h in enumerate(header) if j != i]
        nb = [[c for j, c in enumerate(r) if j != i] for r in body]
        return nh, nb
    new_csv = mutate_csv(csv_text, _fn)
    if new_csv is None:
        return None
    return md, new_csv, lambda a, b: "has_catalyst_timestamp" not in b


def mut_missing_reason_field(md, csv_text):
    """The CSV loses the reason_without_timestamp column entirely."""
    def _fn(header, body):
        if "reason_without_timestamp" not in header:
            return header, body
        i = header.index("reason_without_timestamp")
        nh = [h for j, h in enumerate(header) if j != i]
        nb = [[c for j, c in enumerate(r) if j != i] for r in body]
        return nh, nb
    new_csv = mutate_csv(csv_text, _fn)
    if new_csv is None:
        return None
    return md, new_csv, lambda a, b: "reason_without_timestamp" not in b


def mut_empty_reason_cell(md, csv_text):
    """A row's reason_without_timestamp is emptied — the timestamp is missing, but
    the REASON is not."""
    def _fn(header, body):
        if "reason_without_timestamp" not in header:
            return header, body
        i = header.index("reason_without_timestamp")
        nb = []
        for n, r in enumerate(body):
            r = list(r)
            if n == 0:
                r[i] = ""
            nb.append(r)
        return header, nb
    new_csv = mutate_csv(csv_text, _fn)
    if new_csv is None:
        return None
    return md, new_csv, lambda a, b: True


def mut_raw_pace(md, csv_text):
    """Publish the RAW session/avg ratio instead of the pace-adjusted number."""
    def _fn(header, body):
        if "pace" not in header or "session_vol_to_0950" not in header:
            return header, body
        pi = header.index("pace")
        si = header.index("session_vol_to_0950")
        ai = header.index("avg_vol_10d")
        nb = []
        for r in body:
            r = list(r)
            try:
                sv = float(r[si]); av = float(r[ai])
            except (ValueError, IndexError):
                nb.append(r)
                continue
            if av:
                r[pi] = f"{sv / av:.4f}"
            nb.append(r)
        return header, nb
    new_csv = mutate_csv(csv_text, _fn)
    if new_csv is None:
        return None
    return md, new_csv, lambda a, b: True


def mut_no_tier_count(md, csv_text):
    res = mutate(md, csv_text, r"\(610 names; the top 30 by turnover are published\)", "")
    if res is None:
        return None
    m_md, m_csv = res
    return m_md, m_csv, lambda a, b: "610 names" not in a


def mut_stale_contract_marker(md, csv_text):
    res = mutate(md, csv_text, r"in-play-artifact-v1", "in-play-artifact-v0")
    if res is None:
        return None
    m_md, m_csv = res
    return m_md, m_csv, lambda a, b: "in-play-artifact-v0" in a


def mut_watch_block_one_name(md, csv_text):
    """The watch block drops to two names. GHI also appears in the Soft-A table, so
    the post-condition must look at the WATCH BLOCK specifically, not the whole file."""
    res = mutate(md, csv_text,
                 r"\| \*\*GHI\*\* \| \$12\.40 \| \$13\.02 \| below \$12\.10 \|\n", "")
    if res is None:
        return None
    m_md, m_csv = res

    def _post(a, b):
        body = a.split("## What to watch at the open", 1)[-1].split("## Tier A", 1)[0]
        return "**GHI**" not in body
    return m_md, m_csv, _post


def mut_delta_names_wrong_board(md, csv_text):
    """The delta names the PRE-close board instead of the prior OPEN board — the exact
    mix-up the open slot's two-file read rule exists to prevent."""
    res = mutate(md, csv_text, r"us-stocks-in-play/2026-11-05-open\.md",
                 "us-stocks-in-play/2026-11-05.md")
    if res is None:
        return None
    m_md, m_csv = res
    return m_md, m_csv, lambda a, b: "2026-11-05-open.md" not in a


def mut_annex_names_wrong_board(md, csv_text):
    """The overnight annex no longer names the prior pre-close board it read — the
    heading AND the body statement are both removed, so nothing names the source."""
    res = mutate(md, csv_text,
                 r"\*\*Annex source:\*\* `us-stocks-in-play/2026-11-05\.md` "
                 r"\(the previous day's PRE-close board\)\.\n", "")
    if res is None:
        return None
    m_md, m_csv = res
    # the heading must stop naming it too
    m_md = m_md.replace(
        "## Overnight → open — the carry handoff from the 2026-11-05 pre-close board",
        "## Overnight → open — the carry handoff")
    if "2026-11-05 pre-close board" in m_md:
        return None
    return m_md, m_csv, lambda a, b: "2026-11-05 pre-close board" not in a


def mut_preclose_delta_names_an_open_board(md, csv_text):
    """The pre-close board must not diff against an OPEN board."""
    return None


def mut_open_delta_wrong_source(md, csv_text):
    res = mutate(md, csv_text,
                 r"\*\*Delta source:\*\* `us-stocks-in-play/2026-11-05-open\.md`",
                 "**Delta source:** `us-stocks-in-play/2026-11-05.md`")
    if res is None:
        return None
    m_md, m_csv = res
    return m_md, m_csv, lambda a, b: "2026-11-05-open.md" not in a


MUTATIONS = [
    ("the open board has no 'What to watch at the open' block", mut_no_watch_block),
    ("the pace regime band is not published", mut_no_band),
    ("only one endpoint of the pace band is published", mut_band_one_endpoint),
    ("the pace constant is not published", mut_no_constant),
    ("the open board labels a column RVol", mut_rvol_column_label),
    ("the delta table has no 'why' column", mut_delta_no_why),
    ("the delta section is not a table", mut_delta_not_a_table),
    ("the delta names the PRE-close board, not the prior OPEN board",
     mut_delta_names_wrong_board),
    ("the overnight annex does not name the prior pre-close board",
     mut_annex_names_wrong_board),
    ("the artifact states a halt count ('halted: 0')", mut_halt_count),
    ("the artifact states a halt count ('0 halts')", mut_halt_count_zero_halts),
    ("the CSV loses has_catalyst_timestamp", mut_missing_timestamp_field),
    ("the CSV loses reason_without_timestamp", mut_missing_reason_field),
    ("a row's reason_without_timestamp is empty", mut_empty_reason_cell),
    ("the published pace is the RAW ratio, not pace-adjusted", mut_raw_pace),
    ("the TECH_WATCH heading states no tier count", mut_no_tier_count),
    ("the artifact carries a stale contract marker", mut_stale_contract_marker),
    ("the watch block names fewer than 3 names", mut_watch_block_one_name),
]


def main():
    print("cron #17 artifact contract — regression test")
    print("=" * 60)
    tmpdir = tempfile.mkdtemp(prefix="inplay-contract-")
    md, csvp = write_fixture(tmpdir)
    md_text = open(md, encoding="utf-8").read()
    csv_text = open(csvp, encoding="utf-8").read()

    # --- 1. the contract MUST be satisfiable ---------------------------------
    rc, out = run_checker(md, csvp)
    if rc == 0:
        print(f"{PASS} the contract is satisfiable — a conforming artifact passes "
              f"({ck.__name__})")
    else:
        print(f"{FAIL} the contract CANNOT be met — a conforming artifact fails:")
        print(out)
        return 1

    # --- 1b. the PRE-CLOSE slot's contract must also be satisfiable -----------
    pmd, pcsv = write_preclose_fixture(tmpdir)
    rc, out = run_checker(pmd, pcsv, slot="preclose")
    if rc == 0:
        print(f"{PASS} the pre-close contract is satisfiable — a conforming pre-close "
              f"artifact passes")
    else:
        print(f"{FAIL} the pre-close contract CANNOT be met — a conforming artifact fails:")
        print(out)
        return 1

    # --- 2b. the pre-close slot's own source-naming rule must bite ------------
    pmut = [
        ("the pre-close board names an OPEN board as its delta source",
         lambda m: m.replace("`us-stocks-in-play/2026-11-05.md`",
                             "`us-stocks-in-play/2026-11-05-open.md`", 1)),
        ("the pre-close board names no source file at all",
         lambda m: re.sub(r"\*\*Delta source:\*\*[^\n]*\n", "", m, count=1)),
    ]
    p_md_text = render_preclose_md()
    puncaught = []
    for name, fn in pmut:
        m_md = fn(p_md_text)
        if m_md == p_md_text:
            print(f"{FAIL} MUTATION IS A NO-OP: {name}")
            puncaught.append(name)
            continue
        p_md = os.path.join(tmpdir, "pmut.md")
        with open(p_md, "w", encoding="utf-8") as fh:
            fh.write(m_md)
        rc, out = run_checker(p_md, pcsv, slot="preclose")
        if rc != 0:
            print(f"{PASS} caught: {name}")
        else:
            print(f"{FAIL} NOT CAUGHT: {name}")
            puncaught.append(name)
    if puncaught:
        print(f"{FAIL} {len(puncaught)} pre-close breaches were NOT caught:")
        for u in puncaught:
            print(f"  - {u}")
        return 1

    # --- 3. every mutation MUST be caught -------------------------------------
    uncaught = []
    for name, fn in MUTATIONS:
        res = fn(md_text, csv_text)
        if res is None:
            print(f"{FAIL} MUTATION DOES NOT APPLY: {name} — the pattern matched nothing, "
                  "so the checker would be wrongly blamed")
            uncaught.append(name)
            continue
        m_md, m_csv, post = res
        if m_md == md_text and m_csv == csv_text:
            print(f"{FAIL} MUTATION IS A NO-OP: {name}")
            uncaught.append(name)
            continue
        # The mutation MUST have actually changed the thing it claims to change,
        # otherwise a "caught" result could be an accident.
        if not post(m_md, m_csv):
            print(f"{FAIL} MUTATION DID NOT LAND: {name} — the post-condition is false, so "
                  "the checker would be credited with catching a breach that is not there")
            uncaught.append(name)
            continue
        p_md = os.path.join(tmpdir, "mut.md")
        p_csv = os.path.join(tmpdir, "mut.csv")
        with open(p_md, "w", encoding="utf-8") as fh:
            fh.write(m_md)
        with open(p_csv, "w", newline="", encoding="utf-8") as fh:
            fh.write(m_csv)
        rc, out = run_checker(p_md, p_csv)
        if rc != 0:
            first = ""
            for ln in out.split("\n"):
                if "FAIL" in ln:
                    first = ln.strip()
                    break
            print(f"{PASS} caught: {name}")
            if first:
                print(f"       {first[:150]}")
        else:
            print(f"{FAIL} NOT CAUGHT: {name}")
            uncaught.append(name)

    print("=" * 60)
    if uncaught:
        print(f"{FAIL} {len(uncaught)} of {len(MUTATIONS)} breaches were NOT caught:")
        for u in uncaught:
            print(f"  - {u}")
        return 1
    print(f"{PASS} all {len(MUTATIONS)} breaches caught; the contract is satisfiable.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
