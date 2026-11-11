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

The Nov 9 post-mortem blamed **Gate B** (the $100M market-cap floor). Across seven sessions Gate B was the **least** damaging of the three filters: only **0–1 names per session** failed it outright, because the day&rsquo;s top-25 median market cap ran **$19M–$793M** and the movers sit mostly below $100M but above nothing.

What actually cost the coverage:

| Filter | Damage | Why |
|---|---|---|
| **The ±3% scan floor** (`premarket_change in_range [3,1000]`) | **45 of the 74 absent names had a pre-market gap inside ±3%**; a **±15% floor would have swept up 62 of 74 (84%)** | the screen could only ever find names that had *already* moved — exactly the population that is not left to find |
| **The top-25 table cap** | **59 of 175** top gainers were in the CSV, un-named, every session | the data was published; the *table* was not |
| **Gate B** | 0–1 of 25 per session | Gate B&rsquo;s real damage was subtler: it pushed names into a thin-tape block that was itself **truncated to 12 rows**. On Nov 6 ten top-25 gainers failed the cap and **only one** of them was printed. |
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
| Gate B: demote from filter to label | barely cost coverage; stop truncating the thin-tape block | **refine** |
| **Re-rank by pre-market relative volume** | **worse on 6 of 7 sessions** (Nov 6: −8.65% vs +12.74%; Nov 4: +1.12% vs +16.07%). Residual pool ordered by %ADV = **−4.05%**; by raw pre-market volume = **−4.97%**; by gap = **+4.63%** | **RETRACTED** |
| Keep the gap screen for the downside only | corr(gap, close-to-close) positive every day (0.39–0.85); corr(gap, after-the-open) near zero or negative on 6 of 7 | **supported** |

**The retraction, in full.** The Nov 9 post-mortem proposed ranking on relative volume because "%ADV is the one pre-market variable that survived into the session." Tested twice, it does not hold. Pre-market %ADV measures how much a name traded *before* the bell — and a name that traded heavily before the bell has usually already priced its news. The gap ranking is not the problem. The **fetch floor** and the **table length** are.

## Also observed

- **The pre-market CSV schema evolved inside the week**: 14 columns on Nov 2 → 15 on Nov 3 → 16 on Nov 4 → the pinned 21 on Nov 5+. The Nov 2–4 files still carry the **date-named** close columns (`fri_2026_10_30_close`, `nov_2_2026_close`) that the v2 contract removed — the defect §C3 was written to kill was live for three sessions after the contract landed.
- **Cron #20&rsquo;s settled file carries ≈4,890 of the scanner&rsquo;s ≈6,094 names**, and it drops foreign-domiciled ADRs (TSM, ARM, IREN, NBIS were absent on Nov 5). Any "market-wide" ranking built on it alone is over a smaller universe than the screener sees.
- **The %ADV and gap cohorts differ in kind, not just degree.** The residual, un-named pool contains names the brief&rsquo;s own gates had *passed* — it is not a junk pool. It is the day&rsquo;s extreme tail that the table never printed.

## What is NOT changed

No prompt, no skill spec, no scanner filter, no gate, no table. The five items above are proposals with the measurement attached, for the team to decide.
