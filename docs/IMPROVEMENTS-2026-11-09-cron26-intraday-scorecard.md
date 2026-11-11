# IMPROVEMENTS — 2026-11-09: cron #26's screen scored against the Nov 6 regular session

**Date:** 2026-11-09
**Scope:** cron #26 `agentic-pre-market-brief`, scored against its own published artifact after the fact. This is a **measurement**, not a change: nothing in the routine was modified, no prompt was changed, no skill spec was edited, and the 2026-11-06 artifact was not overwritten.

---

## The question

The 2026-11-06 brief published **eight names** in its chat signal, drawn from an 08:36 ET pre-market gap screen. A fair scorecard asks: **who actually led the regular session on 2026-11-06**, and were they the same names?

## How it was measured

| | |
|---|---|
| **Universe** | 6,094 US-listed stocks and ADRs on NASDAQ/NYSE/AMEX (TradingView `america` scanner, `type in [stock, dr]`) |
| **Pull** | 2026-11-09 00:22 ET — the market was closed, so the scanner's live `close`/`change`/`open`/`high`/`low` columns still carried the **settled 2026-11-06 session** (`totalCount` 6,094 == rows returned, so no truncation) |
| **Cross-check** | cron #20's settled `us-eod/2026-11-06.csv` (4,892 names). The two sources agree **exactly** on every name they share (FLY, FROG, GOGO, SKIN, OBX, KRMN, SERV, CABR, KDK, DKNG, TEAM, NTRA, AXON, HIMS, ASTS, SITC…) |
| **The screen being scored** | the 08:36 ET pull published in `daily-briefs/2026-11-06-pre-market.csv` (696 names) |
| **Definitions** | *pre-market gap* = open vs prior close; *close-to-close* = the session's move; *open-to-close* = the move that happened **strictly after the bell**; *range* = (high−low) / prior close |

**No `mcp__*` finance tool is registered in this runtime, and the 135 connected App tools are GitHub (118), Matrix (15) and email (2) — none carry market data.** The scanner and the fleet's own artifacts carried this analysis.

---

## The scorecard

| Pick | Pre-market | Close-to-close | Market rank | Rank among $1B+ | Cap | Move after the open |
|---|---|---|---|---|---|---|
| **FLY** | +11.04% | **+36.80%** | **#14** | **#2** | $3.48B | +21.37% |
| **FROG** | +23.04% | **+35.33%** | **#16** | **#3** | $12.45B | +6.31% |
| IREN | +15.86% | +20.02% | #70 | #11 | $8.76B | +2.32% |
| ASTS | −3.01% | +7.05% | #606 | #198 | $12.58B | +5.86% |
| NET | +18.60% | +9.91% | #344 | #102 | $95.70B | **−6.35%** |
| HIMS | +8.39% | +8.06% | #492 | #152 | $6.07B | +0.85% |
| DKNG | −24.15% | −21.30% | #6058 | #2794 | $9.19B | +6.75% |
| SITC | −82.35% | −81.29% | #6093 | — | $0.20B | +9.51% |

**Two of eight** were genuine top performers, and inside the cap band the screen targeted they were the **#2 and #3 names over $1B** (FROG was **#1 over $10B**). IREN was a solid #70. NET, HIMS and ASTS closed mid-pack; NET's gap **faded 6.35%** from the open. DKNG closed near the bottom of the market. SITC's −81% is the **ex-distribution** the brief already flagged — on the adjusted basis it was +9.51% from the open.

**One pick was wrong in the brief itself.** ASTS was published at **−3.01%** with the story "the payer is down because it is funding the deal in stock." The final pre-market print was **+1.19%** and it closed **+7.05%**. The 08:36 snapshot caught the move mid-reversal and the brief presented a 54-minute-old read as the state of the tape.

## The cross-check

### The data was in the artifact. The gate moved it out of view.

Of the day's **top 25 regular-session gainers**:

- **17 were already rows** in the published 696-name CSV.
- **10 of those 17 were demoted** into the "thin tape" block by the **$100M market-cap Gate B**. The median cap of the day's top 25 gainers is **$38M**.
- Only **FLY and FROG** passed both gates into a headline table — and both were right.
- **8 were invisible to the screen entirely**, for three separate structural reasons (below).

### The three blind spots

| Reason | Names | Evidence |
|---|---|---|
| **The ±3% gap floor** | GOGO, SDA, RDGT, MTVA | GOGO was **−1.10%** pre-market and closed **+71.52%**; SDA **+0.78%** → **+144.80%**; RDGT **−0.00%** → +34.08%; MTVA +2.61% → +31.19% |
| **No pre-market print at all** | SKIN, GIBO | neither traded pre-market; both gapped at the open (SKIN +48% at the bell) |
| **Pulled too early** | CDT, OBX | CDT finished pre-market **+61.94% on 5.16m shares**, OBX +8.44% on 1,900 shares — **both after the 08:36 pull**. SKIN and GIBO printed nothing at all until the open |

### What the two cohorts share

| Median of the cohort | Day's top 25 gainers | The brief's 8 picks |
|---|---|---|
| Market cap | **$0.04B** | **$8.97B** |
| Relative volume | **5.45x** | 3.09x |
| Pre-market gap | +11.87% | +9.93% |
| **Move after the open** | **+22.43%** | **+6.08%** |

**The screen read the small half of the move.** Of the **114 names that moved ≥20%**, **71% did it after the open** — median |pre-market gap| **5.54%** against a median |open-to-close| of **21.45%**.

### The asymmetry: a gap screen is a warning, not a forecast

Correlation of the pre-market gap with what followed, across the 693 published names resolvable in the settled session:

| | → close-to-close | → move after the open |
|---|---|---|
| **Gap-up names** (n=414) | **+0.151** | **−0.292** |
| **Gap-down names** (n=278) | **+0.563** | +0.081 |

A pre-market gap predicts the **downside** far better than the upside, and on the upside it is *negatively* related to what happens after the bell. **The downside screen was good**: 19 of the day's 25 biggest losers were in the CSV, and four of the brief's ten promoted losers were in the market's top 25. The blind spot was one-sided.

### The day itself was a small-cap explosion

1,433 names up ≥3%, 338 up ≥10%, **71 up ≥20%**, 27 up ≥30%. The move decayed monotonically with size — median |session move| of **2.88%** under $50M versus **0.78%** over $1T; the share moving ≥20% was **4.5%** under $50M and **0.0%** over $1T. **The screen was pointed at the quiet end of the tape.** And the day's biggest carnage was in **biotech and health tech** (Health Technology = 8 of the top 25 losers), which an AI-and-earnings framing never pointed at.

---

## Candidate fixes — proposals, NOT changes

Each traces to a specific miss above. **Nothing has been applied.**

1. **Rank on relative volume, not on the gap.** The top 25 gainers ran at a median 5.45x average volume; the brief's eight ran at 3.09x, with the leader (SDA) at 29x. Relative volume is the one pre-market variable that survived into the session — and the screen ignored it.
2. **Demote Gate B to a label instead of a filter.** Ten of the top 25 gainers were in the CSV and were pushed into "thin tape" by a $100M floor whose cohort median is $38M.
3. **Drop the ±3% gap filter, or keep the names that fail it.** GOGO, SDA, RDGT and MTVA were pre-market non-events and became the day's #3, #1, #20 and #24 gainers.
4. **Pull the screen twice — 08:36 and 09:25.** CDT and OBX printed after the snapshot; SKIN and GIBO printed nothing at all until the open.
5. **Keep the gap screen for the downside; stop using it as an upside forecast.** +0.563 correlation on gap-down names versus +0.151 on gap-up names.

## The measurement itself has a trap worth recording

**A pre-market snapshot ages badly in the last hour.** Across the 693 published names, the drift from the 08:36 print to the settled 09:30 open had a median of **+0.24 points** — but a median **absolute** drift of **2.46 points**, with outliers of **+103 points** (VIVK) and **−51.8 points** (DBGI). A pre-market print published as "the price" is a timestamp, and the brief should say so.

**Also:** cron #20's settled `us-eod` file covers **4,892 of the 6,094** names the scanner sees — SDA, STAK, CIIT, VSA, SNT, RCT, GIBO and SMX are absent from it. Any "market-wide" ranking built on that file alone is a ranking over a *different, smaller* universe than the screener sees. Both files agree exactly on the names they share, so the difference is universe shape, not data.

## A trap in `tools/gen_docs_index.py` (hit while filing this doc)

`docs/README.md` is committed with **CRLF** line endings. `gen_docs_index.py` writes the file with **LF**, so regenerating the index after adding one document produces a **39-line whole-file diff** for what should be a one-row insertion. That noise is exactly the kind of diff that gets mistaken for a sibling session's work being clobbered. Two ways out:

- restore the committed file and insert the single row with the file's existing line endings, or
- normalise the file to LF in a dedicated commit **before** anyone regenerates it.

Either way, check `git diff --stat` after regenerating before committing — a one-row addition that shows "39 insertions, 38 deletions" is a line-ending flip, not a content change.


---

## CORRECTION — 2026-11-11

**Superseded in part by [`IMPROVEMENTS-2026-11-11-cron26-seven-session-scorecard.md`](IMPROVEMENTS-2026-11-11-cron26-seven-session-scorecard.md).**

Scored across seven sessions (2026-11-02 to 2026-11-10), the claim in this document that **Gate B** was the filter burying the day's movers does not hold: Gate B excluded only 0-1 names per session. The binding filter was the **+/-3% pre-market scan floor** (45 of the 74 absent names had a pre-market gap inside +/-3%; a +/-15% floor catches 84% of them), followed by the **top-25 table cap** (59 of 175 top gainers were in the CSV and never named).

The other correction: the proposal to **rank by relative volume** is **retracted**. Tested across seven sessions it produced a worse median session move than the gap ranking on 6 of 7 sessions, and ordering the residual un-named pool by %ADV gives -4.05% against +4.63% for ordering the same pool by gap.
