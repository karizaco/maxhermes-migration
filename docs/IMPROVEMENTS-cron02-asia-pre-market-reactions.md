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
