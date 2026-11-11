# IMPROVEMENTS — 2026-11-11: cron #26 scored across seven sessions — and a correction to the Nov 9 post-mortem

**Date:** 2026-11-11
**Scope:** cron #26 `agentic-pre-market-brief`, scored against its own published artifacts over **seven sessions** (2026-11-02 → 2026-11-10). Measurement only — **nothing in the routine, its prompt or its skill spec was changed**, and no published artifact was overwritten.

**This document corrects [`IMPROVEMENTS-2026-11-09-cron26-intraday-scorecard.md`](IMPROVEMENTS-2026-11-09-cron26-intraday-scorecard.md)**, which attributed the misses to **Gate B**. Seven sessions of evidence say the binding filter was the **±3% pre-market scan floor**, and that one of the five proposed fixes — *rank by relative volume* — is **wrong** and is retracted below.

---

## Method

| | |
|---|---|
| **Sessions** | 7 published cron #26 briefs: 2026-11-02, 03, 04, 05, 06, 09, 10. (2026-11-11 had not published at the time of writing — the 08:30 ET fire had run 13 minutes earlier.) |
| **The screen** | each day's published `daily-briefs/{date}-pre-market.csv` (427–1,491 rows) |
| **What was NAMED** | each day's published `daily-briefs/{date}-pre-market.md`, parsed by heading so that a table binds to the heading it sits under. "Named" = §2 theme clusters, §3 top-gaps table, §4 top-losers table. "Secondary" = thin-tape block, §5 StockTwits, §6 watchlist, §9 earnings. **The §"Yesterday's brief" review table is excluded** — it lists yesterday's setups, not today's picks. |
| **The session** | cron #20's settled `us-eod/{date}.csv` (≈4,890 names). Close-to-close = `change_pct`; gap = open vs prior close; after-the-open = close vs open. Rows flagged ex-distribution/split are excluded as mechanical. |
| **Universe** | cron #23's post-market movers were unioned in to catch names cron #20 omits (it carries ≈4,890 of the scanner's ≈6,094 — **TSM, ARM, IREN and NBIS were missing on Nov 5**). |

The Nov 2–5 pre-market CSVs use the **legacy** column names (`premarket_change_pct`, plus the date-named close columns that the v2 contract removed); Nov 6 was recomputed under the same pipeline as a cross-check.

---

## The result: the pattern recurred on every session

Of each session's **top 25 regular-session gainers**:

| Session | Named | Secondary | CSV only | **Absent** | Moved after the open |
|---|---|---|---|---|---|
| 2026-11-02 | 4 | 0 | 5 | **16** | 77% |
| 2026-11-03 | 3 | 0 | 10 | **12** | 76% |
| 2026-11-04 | 5 | 1 | 8 | **11** | 63% |
| 2026-11-05 | 8 | 3 | 5 | **9** | 57% |
| 2026-11-06 | 5 | 1 | 10 | **9** | 63% |
| 2026-11-09 | 1 | 4 | 14 | **6** | 75% |
| 2026-11-10 | 7 | 0 | 7 | **11** | 71% |
| **7 sessions, 175 names** | **33 (19%)** | 9 (5%) | 59 (34%) | **74 (42%)** | median **71%** |

Losers, same test: **23 of 175 named (13%)**, 60 CSV-only, **81 absent (46%)**.

**Two facts hold on every single session:**

1. **The day&rsquo;s extremes were mostly not in the brief.** Only ~19% of the top-25 gainers and ~13% of the top-25 losers were named in a headline table. A third were in the CSV and never named. Roughly 42–46% never entered the artifact at all.
2. **The extremes moved after the open.** 57–77% (median **71%**) of every session&rsquo;s 20%+ moves happened *after* 09:30 rather than in the pre-market. For the names that moved post-open, the median pre-market gap was **5.54%** against a median after-the-open move of **21.45%**.

## Which filter did the damage — the correction

The Nov 9 post-mortem blamed **Gate B** (the $100M market-cap floor) for burying the movers. The scan floor and the table cap were the dominant filters &mdash; but **Gate B was not the innocent bystander it first appeared**, and the first version of this document understated it. Recomputing the gate flags directly from each published CSV (the first pass had an indentation bug in the tally that only tested the last row of each list) gives the true cost:

| Gate outcome, 175 top regular-session gainers | Names | Share |
|---|---|---|
| **failed both gates** | 21 | 12% |
| **failed Gate A only** (liquidity: pre-market volume < 100,000, or cap < $200m with < 10,000 shares) | 25 | 14% |
| **failed Gate B only** (market cap < $100m) | 12 | 7% |
| **passed both** | 43 | 25% |

**58 of the day's 175 top gainers (33%) failed at least one gate &mdash; and the gate-failing movers moved exactly as far as the gate-passing ones** (median session move **+26.75%** vs **+26.05%**). The gates were not excluding junk. They were excluding a third of the day's best movers, and then filing the rest in a thin-tape block that was itself truncated to 12 rows.

What actually cost the coverage:

What actually cost the coverage:

| Filter | Damage | Why |
|---|---|---|
| **The ±3% scan floor** (`premarket_change in_range [3,1000]`) | **45 of the 74 absent names had a pre-market gap inside ±3%**; a **±15% floor would have swept up 62 of 74 (84%)** | the screen could only ever find names that had *already* moved — exactly the population that is not left to find |
| **The top-25 table cap** | **59 of 175** top gainers were in the CSV, un-named, every session | the data was published; the *table* was not |
| **Gate A and Gate B together** | **58 of 175 (33%)** of the day's top gainers failed at least one gate | The gate-failing movers were as strong as the gate-passing ones (+26.75% vs +26.05% median), so the gates were excluding a third of the day's best movers. On Nov 6 ten top-25 gainers failed Gate B and **only one** of them reached the published thin-tape list. |
| **The 08:36 pull** | 2 of 74 absent names had **no pre-market print at all** | plus CDT on Nov 6, which finished pre-market **+61.94% on 5.16m shares after the 08:36 pull** |

## The picks were good

Median regular-session move of the names the brief **named**, against the market&rsquo;s median that day:

| Session | Named picks | Market median | Result |
|---|---|---|---|
| 2026-11-02 | −1.73% | +0.18% | miss |
| 2026-11-03 | +6.26% | −0.06% | beat |
| 2026-11-04 | +9.32% | +1.40% | beat |
| 2026-11-05 | +12.29% | −3.01% | beat |
| 2026-11-06 | +9.74% | +0.24% | beat |
| 2026-11-09 | +8.65% | +1.71% | beat |
| 2026-11-10 | +1.68% | −0.57% | beat |

**The brief&rsquo;s named picks beat the market&rsquo;s median move on 6 of 7 sessions.** The screen was not producing bad names. It was producing good, liquid, news-driven names while the day&rsquo;s extreme tail lived in a population the scan had excluded before it started. **The fix is therefore additive — widen what is fetched and publish more of it — not a re-ranking.**

## Scoring the candidate fixes against seven sessions

| Proposal | Measured result | Verdict |
|---|---|---|
| Widen the scan floor (±3% → ±15%) | catches 62 of 74 absent names (84%) | **supported** |
| Second pull at 09:25 ET, merged with the 08:36 pull | catches the 2-of-74 no-print cases plus the post-08:36 prints | **supported** |
| Publish the un-named residual pool | gap-ordered residual = **+4.63%** median (named picks +6.26%, market ~+0.2%) | **supported** |
| Gate A and Gate B: demote from filter to label (on a second tier) | 33% of the day's top movers failed a gate and moved just as far | **supported** |
| **Re-rank by pre-market relative volume** | **worse on 6 of 7 sessions** (Nov 6: −8.65% vs +12.74%; Nov 4: +1.12% vs +16.07%). Residual pool ordered by %ADV = **−4.05%**; by raw pre-market volume = **−4.97%**; by gap = **+4.63%** | **RETRACTED** |
| Keep the gap screen for the downside only | corr(gap, close-to-close) positive every day (0.39–0.85); corr(gap, after-the-open) near zero or negative on 6 of 7 | **supported** |

**The retraction, in full.** The Nov 9 post-mortem proposed ranking on relative volume because "%ADV is the one pre-market variable that survived into the session." Tested twice, it does not hold. Pre-market %ADV measures how much a name traded *before* the bell — and a name that traded heavily before the bell has usually already priced its news. The gap ranking is not the problem. The **fetch floor** and the **table length** are.

## Also observed

- **The pre-market CSV schema evolved inside the week**: 14 columns on Nov 2 → 15 on Nov 3 → 16 on Nov 4 → the pinned 21 on Nov 5+. The Nov 2–4 files still carry the **date-named** close columns (`fri_2026_10_30_close`, `nov_2_2026_close`) that the v2 contract removed — the defect §C3 was written to kill was live for three sessions after the contract landed.
- **Cron #20&rsquo;s settled file carries ≈4,890 of the scanner&rsquo;s ≈6,094 names**, and it drops foreign-domiciled ADRs (TSM, ARM, IREN, NBIS were absent on Nov 5). Any "market-wide" ranking built on it alone is over a smaller universe than the screener sees.
- **The %ADV and gap cohorts differ in kind, not just degree.** The residual, un-named pool contains names the brief&rsquo;s own gates had *passed* — it is not a junk pool. It is the day&rsquo;s extreme tail that the table never printed.

## The recommendation: keep the gates, but split the artifact in two

**Tier 1 - the setups. Keep the gates, keep the gap ranking, keep the levels.** This tier has measured alpha: the named picks beat the market's median move on 6 of 7 sessions, and Gate A is doing real work (it stops a +/-20% print on 100 shares from reaching a headline table). Nothing here should change.

**Tier 2 - the tail. Gates demoted to labels; a wider universe; a second pull; a direction-agnostic ranking.** Three requirements, each measured:

1. **Demote the gates to labels.** A name that failed Gate B is marked *sub-$100m / thin*, not dropped. 58 of 175 movers failed a gate and performed identically to the ones that passed.
2. **Merge the two pulls.** Cron #26b's 09:20 ET refresh already exists and it works: on Nov 9 it surfaced **TLS (+48.8%)** and on Nov 10 **SGLY (+25.4%)** - both absent from the 08:36 pull - and it added 18 and 5 names respectively that closed up >=10%. The refresh is a separate artifact today; it should feed the brief's coverage tier.
3. **Rank the tier by |gap|, not by gap.** A gap-ranked table files *gapped-down-then-ran* names under "losers" - GOGO was -1.10% pre-market and closed +71.52%. The tail tier must be direction-agnostic or it will systematically misfile the day's biggest winners.

### The honest limit on coverage - what widening the universe cannot buy

The 74 absent top-25 gainers were **not discoverable before the open by any signal a pre-market routine can read**:

- **45 of them had a pre-market gap inside +/-3%** - so a wider floor would have *fetched* them (a +/-15% floor catches 62 of 74, 84%).
- **Only 2 had any pre-market print at all**, and **none had a catalyst**: **0 of 74** appear in cron #19's earnings roster or cron #15's reactions file on any of the seven sessions. They were not earnings names - they were idiosyncratic squeezes with no pre-open footprint.

So expanding the universe is **necessary but not sufficient**. It fetches candidates; it does not identify winners, because the only pre-open signal these names had was "nothing". A pre-market brief cannot name them, and an artifact that implied it could would be lying. What the routine *can* do is fetch them, catch the ones that print late, and stop discarding the third of the movers its own gates reject.

A candidate ranking for the tail tier was tested and **does not work**: names with a pre-market print but a gap inside +/-3% ("quiet but printing") returned a median of **+1.82%** across the sessions - better than the market on three, negative on two - and it returns 140 names on some days, so it dilutes rather than identifies. It is a watchlist, not a signal.

## Cross-check against a sibling session's finding

A concurrent session found a real defect on the 2026-11-09 fire: for `VISN` the scanner's `close` was wrong while its `premarket_change` was right, so the published row carried a prior close that did not reconcile with its own gap (`docs/IMPROVEMENTS-2026-11-09-cron26-scanner-close-reconciliation.md`). The fix — reconciling the gap against its own denominator — landed in the skill spec on their commit.

**I ran that test against all seven published artifacts** (reconstruct the prior close from the pre-market print and the gap, compare with the published prior close, tolerance = the CSV's own 2dp rounding band):

| Session | Rows checked | Non-reconciling |
|---|---|---|
| 2026-11-02 | 427 | 1 (DMLP, 3.05% off) |
| 2026-11-03 | 1,230 | **0** |
| 2026-11-04 | 791 | **0** |
| 2026-11-05 | 708 | 5 (incl. XXII, a 5,700% mismatch worth a look) |
| 2026-11-06 | 696 | **0** |
| 2026-11-09 | 931 | **0** |
| 2026-11-10 | 506 | 1 (LICN, 7.26% off) |

**The 2026-11-06 artifact — the one the Nov 9 post-mortem was based on — carries none of it**, so that analysis stands. The failures elsewhere are 1–5 rows per session and are not what produced the misses analysed here: the misses are a *coverage* problem (names never fetched), not a *data-quality* problem (names fetched with a wrong prior close).

## What is NOT changed

No prompt, no skill spec, no scanner filter, no gate, no table. The five items above are proposals with the measurement attached, for the team to decide.
