# IMPROVEMENTS — 2026-11-09: cron #26's screen must be RECONCILED before it is published

- **Date:** 2026-11-09
- **Scope:** cron #26 `agentic-pre-market-brief` (the 08:30 ET fire), and by extension every routine
  that publishes a TradingView `america` screen with a `close` and a `premarket_*` gap.
- **Evidence base:** the 2026-11-09 fire — 392 gainers / 206 decliners, 931 CSV rows, 166 published
  names with levels.
- **Status:** fixed in the routine's own skill spec (`cloud-prompts/skills/agentic-pre-market-brief/SKILL.md`,
  §Step 2). The skill is fetched at RUN time, so the next fire picks this up with **no `cron_update`
  and no prompt drift**. The deployed cron #26 prompt was NOT touched.

---

## 1. The headline: the scanner's `close` was wrong for one name, and the gap was right

`VISN` (Vistance Networks) came back from the `america` scanner as:

| field | value | what it implies |
|---|---|---|
| `close` | 3.995 | the prior session closed at 3.995 |
| `premarket_close` | 4.14 | it is printing at 4.14 pre-market |
| `premarket_high` / `premarket_low` | 4.43 / 4.11 | the whole pre-market range sits ABOVE 3.995 |
| `premarket_change` | -24.66% | the gap is -24.66% |

**Those four fields cannot all be true.** A prior close of 3.995 with a pre-market print of 4.14 is a
gap of **+3.5%**, not -24.66%, and a pre-market range sitting entirely above the prior close is a
gap UP. The row is internally contradictory.

An independent quote from the MCP bridge (`market-recap get_quotes`) resolved it:

```
VISN    price=5.495 prev_close=5.405 chg%=1.67   as_of=2026-11-06T21:00:00Z
```

The real Friday close was **5.495** (up 1.67% on the day), not 3.995. And with 5.495 as the
denominator:

```
(4.14 - 5.495) / 5.495 * 100 = -24.66%   <- exactly the scanner's premarket_change
```

**So the defect was in `close`, not in the gap.** The scanner's `premarket_change` was measuring
against a reference (5.495) that the `close` column was not reporting.

### Why this matters more than one row

The brief publishes `Prior close`, `Pre-market last` and `Gap %` **in the same row**, and the CSV
carries the same numbers. Publishing the scanner's `close` unchallenged would have put a prior close
of 4.00 next to a pre-market print of 4.14 in one line of the top-losers table — a contradiction the
reader can catch with a glance — and a wrong `prior_close` in the CSV for a machine to consume. The
routine's own §C2 contract says `Prior close` is the "denominator of the pre-market gap"; when the
denominator and the gap disagree, at least one is wrong, and the routine had no check for it.

### The sweep that finds it

The skill spec already told the routine to verify `close - close/(1 + change/100) == change_abs` once
per run. That identity holds for a wrong `close` (it is an identity between `close`, `change` and
`change_abs`, so all three can be wrong together) — it does NOT catch this defect. The check that
catches it compares the gap against its own denominator:

```python
bad = [r for r in rows if r["close"] and r["premarket_close"] is not None
       and abs((r["premarket_close"] - r["close"]) / r["close"] * 100 - r["premarket_change"]) > 0.25]
```

A sweep of all **598** screened rows on 2026-11-09 flagged **exactly one**: VISN. The same run
cross-checked **15** headline names against the bridge and the scanner agreed with the bridge on
every other one (ZURA, SOC, IONS, IBRX, CEVA, OCUL, NKTX, ABEO, FTH, NWGL, CECO, DCTH, IMVT, NVDA).
So this is a rare single-row defect, not a systemic one — which is exactly why a sweep beats spot
checking: a spot check on the top of the screen would have missed it, and VISN sat in the TOP-10
LOSERS table where it would have been published as a -24.66% gap against a prior close of 4.00.

### The fix (in the skill spec, fetched at run time)

- Run the reconciliation sweep over every row before publishing.
- When it flags a row, pull that ONE name from the bridge, publish the bridge's `prior_close` with
  the scanner's pre-market print and gap, and say so in `## Source health`.
- Never "fix" a gap by trusting one field over another without an independent source.

## 2. The ±3% band moves between pulls — so publish ONE pull's counts

The same run pulled the band twice and measured the drift:

| pull time (ET) | gainers | decliners | why it differs |
|---|---|---|---|
| 08:37 | 382 | 199 | the first pull of the fire |
| 08:44 | 392 | 206 | names grew their pre-market volume past the `premarket_volume > 0` filter and crossed INTO the band |

Seven minutes moved the gainer count by 10 and the decliner count by 7. The final pull was used for
BOTH the published counts (`up_3pct: 392`, `down_3pct: 206`) and every table, so the artifact is
internally consistent — but the discipline was arrived at by accident, and a routine that pulled the
band early for the tables and re-pulled it late for the count would publish a count and a table
that disagree by construction, with nothing to catch it.

**Now pinned in the skill spec:** pull the band once, at the END of the data work, and take both the
counts and the tables from that pull. Earlier pulls are context only.

## 3. A row with no pre-market print is not a row with a blank price

`MLTX` (MoonLake) was StockTwits-trending rank 8 and had **no pre-market print at all**:
`premarket_close`, `premarket_high`, `premarket_low` and `premarket_volume` were all null. The
`premarket_change` was null too.

`check_premarket_brief.py` asserts a non-empty `prior_close` AND `premarket_last` on **every** CSV
row, so a null-print row cannot go into the CSV as a blank. It was published in §5 in prose instead,
with its trending reason and an explicit "no pre-market print has published for this name". That is
the honest treatment: the fact that a trending name has not printed yet IS the information.

**Now pinned in the skill spec:** exclude null-print rows from the CSV; publish the name in prose
without a price.

## 4. What did NOT need changing

- **The `close`/`change`/`change_abs` identity check** is still worth running and still passed on all
  598 rows — it is simply not sufficient on its own, because it holds for a wrong `close`.
- **The row-cap assert** (`len(rows) == totalCount`) held on both screens on both pulls: 392/392 and
  206/206, so `screen_complete: true` is honest.
- **The contract checkers** caught nothing here, and could not have: both were green on the artifact
  BEFORE the reconciliation sweep found VISN, because the markdown and the CSV agreed with each
  other — they were simply both wrong in the same way. A checker that only compares the artifact to
  itself cannot find a source defect. The sweep has to compare the artifact to the SOURCE.

## 5. Files touched

| File | Change |
|---|---|
| `cloud-prompts/skills/agentic-pre-market-brief/SKILL.md` | §Step 2 — three new traps: the `close` reconciliation sweep, the one-pull band discipline, the null-print row rule |
| `docs/IMPROVEMENTS-2026-11-09-cron26-scanner-close-reconciliation.md` | this record |

The deployed cron #26 prompt was **not** touched: the skill is fetched at run time, so the next fire
inherits the fix.
