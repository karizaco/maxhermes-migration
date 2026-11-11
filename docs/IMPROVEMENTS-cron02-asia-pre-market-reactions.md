# Improvements — cron #02 `asia-pre-market-reactions`

Date: 2026-11-10. Scope: cron #02's skill spec (`cloud-prompts/skills/asia-pre-market-reactions/SKILL.md`),
found while running the 2026-11-10 fire. Both defects are in the **procedure the skill executes**,
so both are fixed in the skill spec — which is fetched at RUN time, so they land on the next fire
with no `cron_update` and no prompt drift.

## 1. The down-leg screener filter silently dropped every loser row

The step-2 snippet built the eight screener calls from ONE template:

```bash
for M in japan taiwan hongkong korea; do
  for D in desc asc; do
     ... "filter":[..., {"left":"change","operation":"greater","right":2}, ...],
         "sort":{"sortBy":"change","sortOrder":"desc"} ...
```

`sortOrder` was the only thing that differed between the legs, and the `change` filter was
`greater`/`2` on **both**. Re-sorting a gainer list ascending does not return losers — it returns
**the same gainers, sorted the other way**. The down leg therefore returned the gainers again and
the brief lost every decliner.

Measured on the 2026-11-10 fire with the corrected filter:

| Market | up leg (`change > 2`) | down leg (`change < -2`) |
|---|---|---|
| Japan | 216 | 28 |
| Taiwan | 79 | 15 |
| Hong Kong | 17 | 6 |
| Korea | 105 | 8 |

The two legs are now built with a matching filter AND a matching sort order (`greater`/`2`+`desc`
versus `less`/`-2`+`asc`), with the trap stated in the skill so the next fire cannot reintroduce it.

## 2. THE JP REGIONAL-PRINT RULE — all 13 regional JP prints were wrong

The skill already said to "resolve every regional JP row (NAG/FSE) against its TSE line", but it
listed only `NAG` and `FSE`, and it did not say what to DO when the two venues disagree.

On 2026-11-10 the Japan scan returned **13 regional-venue rows** (`NAG` ×12, `SAPSE` ×1) and
**every one of them diverged from its TSE line** — some catastrophically:

| Ticker | Regional print | TSE line (correct) |
|---|---|---|
| 4502 Takeda | `SAPSE` **+23.26%** | `TSE` 6,593, **-1.20%** |
| 5333 NGK Corp | `NAG` **-33.40%** | `TSE` **+6.33%** |
| 4063 Shin-Etsu Chemical | `NAG` -3.33% | `TSE` +3.99% |
| 7011 Mitsubishi Heavy | `NAG` -5.23% | `TSE` +2.87% |
| 8306 MUFG | `NAG` +10.83% | `TSE` +2.05% |
| 5802 Sumitomo Electric | `NAG` +13.48% | `TSE` +4.04% |
| 1893 Penta-Ocean | `NAG` -16.26% | `TSE` +7.87% |

The Takeda case is the sharpest: the `SAPSE:4502` print was **byte-identical to the 2026-11-09
artifact** (+23.26% both days) while the TSE line closed -1.20% — a frozen regional quote, not a
live print. It would have taken the top slot of the Japan REACTION tier and displaced the real
headline (Modec +15.86%, an actual earnings release).

Two changes:

1. **`SAPSE` (Sapporo) and `SSEO` (Osaka)** join `NAG`/`FSE` in the drop-and-resolve list, in both
   the drop table and the keep-priority table.
2. **THE JP REGIONAL-PRINT RULE** (new named section) states the resolution procedure: query the
   scanner for the same ticker name (it answers with both venues), **substitute the TSE close and
   change** when a TSE line exists, and **drop the row entirely** when none does. It also states
   that this happens **before** the 15-up/15-down cap, because a bogus +23.26% row otherwise takes
   the top slot and pushes a real mover out of the published set.

## 3. Also carried into the skill (this run)

- The **bridge `previous_close` is one session stale for `^TWII` and `^HSI`** — it would have
  published TAIEX +7.58% and HSI +0.31% instead of +2.52% and +0.44%. The skill already warns
  against it; the 2026-11-10 run measured it again and the artifact's source-health table now
  records it explicitly.
- **Taiwan's TPEX rows need a COMPANY-level twin check, not a ticker-level one.** Six published
  TPEX names (MPI, eMemory, CO-TECH, LandMark, Chunghwa Precision Test, Universal Microwave) were
  each checked by company description across the whole Taiwan universe and have no TWSE twin.
  A ticker-level check alone would have been enough here, but the company-level check is the one
  that is correct, because TWSE and TPEX tickers can differ for the same issuer.

No change was made to the deployed cron prompt.

## 4. The format now front-loads the six items that carry the day (v1.5)

The brief publishes ~100 names a run, and on most days 90+ of them carry no sourced catalyst —
the movers list is breadth, not events. Meanwhile the numbers a reader is most likely to misquote
(limit-locked prints, stale venue prints) were buried in `## Flags`, and the backdrop table
published only a ONE-session move, which on a volatile day inverts the story.

Two changes to the artifact contract:

### `## What matters today` - two lists of three, directly under the TL;DR

- **Top 3 real events** = published rows whose CATALYST cell carries a **sourced,
  company-specific** catalyst (earnings/guidance, buyback or capital action, M&A, a named
  broker action on that company), ranked by `|change %|`. **Never padded**: if fewer than three
  rows are sourced, the artifact says `only <n> sourced catalysts today`. A macro driver (crude,
  the Wall Street tape, a sidecar trigger, a limit-lock cluster) is **not** a company event and
  belongs in the TL;DR or the traps list. Every ticker in the list must already be a published
  row in its country section **with the same percentage** — the block is a pointer, never a
  second source of truth.
- **Top 3 artifact traps** = the published numbers a reader is most likely to quote and be wrong
  about. The test is *"does this change how the HEADLINE is read?"* — a trap that only matters
  to the method stays in `## Flags`. Each entry names the misleading number, why it is wrong, and
  the published number instead.

### `## Market backdrop` gains a 5-session chg column

`| Chg |` is the one-session move; `| 5-session chg |` is `close[-1]` against `close[-6]` of the
same chart fetch — five **sessions**, not five calendar days, so a holiday inside the window
shifts the base bar correctly. If a market returns fewer than 6 bars, the cell prints `n/a` and
the caveat line says so; the cell is never empty and the 1-session move is never substituted.

This is not a cosmetic column. Measured on the 2026-11-10 fire:

| Index | 1-session | 5-session | What the one-day column alone would have said |
|---|---|---|---|
| KOSPI | **+4.39%** | **-7.25%** | strongest market of the four — it was the deepest drawdown |
| Nikkei 225 | **+2.87%** | **-4.16%** | a solid up day — a bounce inside a 4% fall |
| TAIEX | **+2.52%** | **-1.38%** | second strongest — still below the pre-selloff base |
| Hang Seng | **+0.44%** | **+4.38%** | the weakest — the only index actually up over the window |

### Two new machine assertions

Assertion 5 proves the What-matters block exists, carries exactly three items per list, and that
every event ticker is a published row whose percentage matches the country table. Assertion 6
proves the backdrop's 5-session cell is present, non-empty and numeric for all four markets. Both
are the kind of check that a prose summary does not satisfy: they exit non-zero on the first
violation.

The skill is fetched at RUN time, so the next fire picks up the new format with no `cron_update`
and no prompt drift. The deployed cron prompt was not touched.


## 3. The 4-call catalyst cap contradicts the v1.5 sourced-events block

The skill's hard rules say **"Total catalyst calls capped at 4 (one per market)"**. The v1.5
`## What matters today` block says the `Top 3 real events` list may **never be padded with unsourced
rows**, and the machine assertion for that block requires **exactly three items**. A day with only
two sourced catalysts therefore has no legal composition: honour the cap and publish a list that
cannot be filled, or fill it and break the cap.

On the 2026-11-11 fire this was live: four per-market top-REACTION lookups produced **Dai-Dan**,
**ISU Petasys** and (for the trap list) **Holy Stone / Korean Air preferred**, but the third
*company event* the assertion demands — a third sourced, company-specific catalyst — needed one
more lookup (Hamamatsu Photonics, TSE:6965 +14.66%, FY2026 results released 10 Nov 14:30 JST).

**Resolution (in the skill, not the prompt):** the cap now carries one explicit exception — a
single additional lookup is permitted when the sourced-events block cannot otherwise carry three
sourced catalysts, and the run must disclose the deviation in `## Method, source health & caveats`
and in the audit footer's `catalyst_lookups=`. Padding the events list with unsourced rows to stay
inside the cap is worse than one extra lookup. The 2026-11-11 artifact published
`catalyst_lookups=5` and said so in the caveats.

## 4. Tier boundaries must be evaluated on the PUBLISHED (rounded) percentage

`TSE:2222` (Kotobuki Spirits) carries a raw scanner change of `-4.003938299967181`. Tested as a
float, `abs(change) > 4` is **true**, so the row tiers into `JP_REACTION` — while the published
cell reads `-4.00%`, which the reader reads as a NOTABLE name by the skill's own 2-4% band. The
tier and the printed number disagreed.

The skill now requires the threshold test to run on `round(abs(change), 2)`, so the tier always
matches the number that is actually printed. On the 2026-11-11 fire this moved one Japan row from
the REACTION table to NOTABLE one-liners (reactions 74 → 73 of 93 published names).

## 5. Index % conflicts: a stale bridge AND a wrong third-party quote page

The skill already warned that the bridge's `previous_close` is one session stale for `^TWII` and
`^HSI`. Measured again on 2026-11-11, the bridge printed `^TWII` **+6.23%** and `^HSI` **-0.54%**
against the chart bars' **+3.62%** and **-0.98%**.

New in this fire: a **third-party quote page can be wrong too**. Investing.com printed the TAIEX
at **+3.11%** while six same-day Taiwanese sources — Focus Taiwan (CNA), Taiwan News, ETtoday,
NOWnews, FTNN and Capital Futures — all printed the close as **44,257.15** and the move as
**+3.62%** (a 1,545.23-point day, the sixth-largest single-day closing point gain in the index's
history). The chart API was right; the bridge and Investing.com were both wrong, in opposite
directions.

The skill now says what to do when a secondary source disagrees with the chart bars by more than
0.6%: check the close LEVEL against at least two independent same-day press closes before
publishing, publish the chart-derived number, and record the conflict in `## Flags`. A conflict on
a headline index number is a trap the reader will hit — it belongs in `### Top 3 artifact traps`
(the 2026-11-11 artifact published it there), not buried in a caveat.

### A note on the two numbers most likely to be misquoted

The same fire produced the day's best trap material, and it is worth recording what made it
misquotable:

- **Korea's preferred lines.** `KRX:003495` (Korean Air preferred) traded **+24.51% early** and
  closed **-24.77%** at KRW28,700 — a ~49pp intraday reversal after six limit-riding sessions,
  driven by a stake/control contest (Hoban Group reached a 20.69% stake in Hanjin KAL's common)
  and a KRX investment-warning designation that suspended trading on 10 Nov. `KRX:18064K`
  (Hanjin KAL preferred) hit the daily limit early and closed -2.67%. **A preferred line and its
  common line are separate securities** (`KRX:003495` vs `KRX:003490`, `KRX:18064K` vs
  `KRX:180640`) — publishing both is correct, but a reader who adds them up double-counts one
  issuer.
- **Taiwan's limit cluster.** 14 of the 15 published Taiwan gainers closed at or within 0.24pp of
  the +10% TWSE daily cap (only Asia Vital Components, +8.96%, was not limit-locked), and 6 of the
  15 are TPEX listings rather than TWSE primary names. The percentage is the exchange's limit
  price, not an independent re-rating.

Both are published as `### Top 3 artifact traps` with the published number stated, so a reader
who quotes the headline has the trap in front of them.

---

All three findings are in the **procedure the skill executes**, so they are fixed in the skill
spec — which is fetched at RUN time, so they land on the next fire with no `cron_update` and no
prompt drift. The deployed cron prompt was not touched.
