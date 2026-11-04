# Improvements — cron #05 `eod-international-daily`

Date: 2026-11-03. Scope: the reply format for the whole fleet (via the shared block), cron #05's
own artifact contract, the `eod-watchlist-snapshot` data contract, and two data defects found
while reviewing the 2026-10-27 → 2026-10-30 series.

## 1. The "Formatting rules" paragraph was lost fleet-wide, and is restored

The 2026-11-02 consolidation (`31ce91b`, "the fleet-wide instructions live in one fetched file,
not 20 copies") moved every routine's DELIVERY block into
`cloud-prompts/_shared/PROMPT-BLOCKS.md` — but it did not carry the **Formatting rules**
paragraph across. That paragraph had been added to cron #23 (`a169c05`) and cron #15
(`3778ced`) and existed nowhere else after the rewrite. All 22 shared-block routines lost it in
one commit.

Restored verbatim into `PROMPT-BLOCKS.md` § DELIVERY. It is the difference between a reply that
reads as a table and a reply that reads as a paragraph, and it is the single highest-leverage
formatting rule in the fleet.

Two smaller changes in the same block:

- **§ Signal** — the tier-order sentence pointed at "the skill's chat rules for tier order, flags
  and the audit line", but several skills (including `eod-watchlist-snapshot`) define no chat
  rules at all. It now says to use the skill's rules *where they exist* and, where they do not,
  to order by absolute move and to claim no catalyst that was not sourced.
- **§ Files** — "one line per file written" becomes "one line per file **or file group**". A
  16-region routine otherwise spends twenty lines on a list the reader cannot use.

Because the fleet fetches `PROMPT-BLOCKS.md` at run time, this propagates to all 22 routines from
one commit, with no `cron_update` and no re-deployment.

## 2. Cron #05's artifact contract

`05-eod-international-daily.md` gained a **REPORT FORMAT** section naming the deliverable
directory (`<region>.csv` ×16, `summary.md`, `_carryover.json`) and the eight sections
`summary.md` must carry, in order: title + "Read this first", `## Coverage`, `## Market context`
(index table + regional breadth table), `## Top movers` (consolidated + one per region),
`## Method`, `## Caveats`, `## Source health`, `## Files`. It also states that the chat reply
leads with a markdown table of all 16 region index levels.

The SCHEDULE block gained one line recording that the 16:35 → 16:30 move on 2026-10-29 was
deliberate (cron #16 took 16:35 to clear a push race) and that the two must move together. The
"Original local schedule: `35 16`" line was **not** a copy-paste error and was left alone.

## 3. The `market_cap` unit contract — the defect that broke the series

`market_cap` was written in **listing currency** on 2026-10-27 and in **USD** from 2026-10-28
onward. Same 14-column header, same directory, consecutive sessions.

Proof, by share-count reconciliation (`market_cap / close` against the issuer's real shares):

| session | ASX:BHP | TSE:7203 | XETR:SAP | unit |
|---|---|---|---|---|
| 2026-10-27 | 1.0001 | 0.9999 | 1.0000 | listing currency |
| 2026-10-28 | 0.7324 | 0.0064 | 1.1293 | USD |
| 2026-10-29 | 0.7411 | 0.0062 | 1.1316 | USD |
| 2026-10-30 | 0.7324 | 0.0063 | 1.1084 | USD |

A ratio of ≈1.0 means listing currency; a ratio equal to that currency's USD rate means USD.
BHP reads `282,743,205,400` on 10-27 and `205,503,023,824` on 10-30 while the price moved
A$57.99 → A$57.56 — a naive concatenation sees BHP's market cap fall 27% on a flat tape.

Root cause, found while checking the floors: **TradingView's `market_cap_basic` is denominated
in the listing currency, not USD.** `scripts/screener_filters.py` documented the field as USD.
A server-side filter of `market_cap_basic > 300000000` on the Japan endpoint still returns names
whose market cap is ¥385m, so a "$300M" floor sent to the screener behaves as a ¥300m floor
(~$1.9M) and filters nothing.

Fixes:

- `SKILL.md` gained **Units, floors and the market-cap contract**: the unit proof, the per-region
  USD floor table, the instruction to convert first and filter client-side, the rule that a row
  with no reported market cap is **excluded rather than written blank**, and the rule that a unit
  change must never be silent — restate the affected sessions.
- `screener_filters.py` — corrected the field documentation, added a module-level warning, and
  added `usd_floor_for_region(region) -> (floor_usd, min_volume)`, the pair to apply after
  conversion. `filters_for_region()` is unchanged and still works; it is now documented as a
  filter over the local-currency number.

## 4. The 2026-10-30 summary publishes a false claim about BHP

`international-eod/2026-10-30/summary.md` says BHP "implies 5.08bn shares against a real count
near 2.13bn, so BHP's market cap reads ~$205bn instead of ~$86bn". The real count is ~5.08bn:

- FCA RNS: "The total number of Shares in issue as of 19 August 2026 is 5,084,182,410".
- ASX Appendix 3H (2025-07-10): `BHP : ORDINARY FULLY PAID — 5,075,992,235`.
- BHP's Unification release (2022-01-31): post-unification total 5,062,323,190, of which
  *2,112,071,796 (≈42%)* were the new Limited Shares.

2.13bn is the 2022 **component** count, not the total, so the "materially overstated" caveat is a
false positive and BHP's ~$205bn cap on 2026-10-30 is essentially right. The 10-27 run's
reconciliation, which used the real count, reached the correct answer on both unit and magnitude.

## 5. 2026-10-27 restated into the house convention

The 2026-10-27 files were written before the house convention existed (local-currency
`market_cap`, no floor, `<date>.meta.md`). They are restated to match 2026-10-28..30:

- `market_cap` in USD, converted with the 2026-10-27 rate table.
- The per-region USD floors applied after conversion; rows the source reports no cap for are
  excluded, not written blank. 4,467 rows written, against the 2026-10-30 reference of 4,486 —
  seven regions identical to the row.
- `2026-10-27.meta.md` → `summary.md`, carrying the eight sections above, including the regional
  breadth table and the sector-rotation table.
- `_carryover.json` and `_calendar_correction.json` are carried over unchanged.

The previous version stays in git history at commit `6b26a0b`, and a local copy of the original
files is in the sandbox backup.

## 6. The FX source note

The 2026-10-30 artifact used `open.er-api`, whose free tier serves only the current day's table
(`/v6/historical/...` returns 404). The 2026-10-27 restatement therefore uses the **Yahoo**
rate table measured at 2026-10-27 16:33 ET — EUR 1.1130, JPY 0.0063312, AUD 0.7026913,
CAD 0.7117944, DKK 0.1488804, TWD 0.0308604 — and says so in `## Source health`. Cross-checked
against `frankfurter.dev` for 2026-10-27: the five currencies it carries agree within 0.2%.
`frankfurter.dev` does not carry TWD.

## 8. The 2026-10-26 artifact was restated (2026-11-03)

`2026-10-26` was the last international session still in the pre-house convention:
listing-currency `market_cap`, the full universe, and `<date>.meta.md`. It is now
restated the same way §5 restated `2026-10-27`:

- `market_cap` in USD, converted with the 2026-10-26 rate table measured at 16:33 ET.
- The per-region USD floors applied after conversion; rows the source reports no cap
  for are excluded, not written blank — 187 of them, listed in `_excluded.json`.
- `2026-10-26.meta.md` → `summary.md`, carrying the eight house sections.
- 3,469 rows written across 13 regions (tw, eu-at and eu-ie were closed that day),
  within ±5 rows per region of the 2026-10-27 session on the same floors.

**A defect in the original run's FX table was found during the restatement.** CAD was
stored as 1.402160 — the `USDCAD=X` quote, which is CAD per USD — without inverting
it, so every Canadian market cap was overstated by ~1.97x and the run's Canadian
liquidity filter was ~2x too loose. The published CSVs are unaffected (they carry
listing-currency `market_cap` and no conversion at all), but the restatement uses the
corrected rate (CAD 0.713222). Share-count reconciliation settles the direction:
`market_cap_basic / close` returns Royal Bank 1,374m, Toronto-Dominion 1,677m,
BMO 689m and Shopify 1,288m — the real share counts, which means the screener's cap
is in the listing currency and the conversion must use USD-per-CAD.

`USDCAD=X` and `USDDKK=X` quote local-per-USD and must be inverted; `EURUSD=X`,
`AUDUSD=X` and `USDJPY=X` do not need inverting (the JPY one is inverted for the
opposite reason — it quotes JPY per USD).

Two new files now ship with the international artifact:

- `_manifest.json` — the universe size, the floor, the `market_cap` unit, the FX
  table, and per-region counts, with the invariant
  `unique_instruments == written + excluded_no_market_cap + excluded_below_floor`.
  Without it the archive is not comparable across sessions: the universe size and
  the unit are not derivable from the CSVs alone.
- `_excluded.json` — the rows with no reported market cap, so an exclusion that is
  invisible in the CSV is still recoverable.

## 9. What was NOT changed

- No other routine's deployed prompt was touched. The 18-prompt repo → platform sync is a
  separate task and is not approved.
- No scheduled time, timezone, model or session binding was changed.
- The `holiday_calendar.py` defect (Greece's Ochi Day listed as 2026-10-27 instead of 10-28) is
  **still open** — it is in the shared skill scripts, so the fix belongs in a separate change
  with its own verification, not inside a formatting pass.
- `push_artifact.sh`'s **connector** fallback now handles a directory deliverable (it used to
  give up on one, which meant cron #05 had no fallback at all when the git path failed). The git
  path is unchanged and remains primary; the connector has no race-retry, so it is still the
  fallback of last resort.

## 10. Two defects found and fixed in the 2026-11-04 fire (spec updated 2026-11-04)

**Date:** 2026-11-04 · **Scope:** cron #05 `eod-international-daily`, 16:30 ET fire ·
**Artifact:** `international-eod/2026-11-04/` — 4,440 rows, 16/16 regions traded.

Both defects were caught by the **cross-session comparison against the previous day's archived
files**, not by any internal check, and both produced a file that looked entirely plausible.
The skill spec (`cloud-prompts/skills/eod-watchlist-snapshot/SKILL.md`) is updated in this same
commit, so the next fire reads the corrected procedure.

### 10.1 The FX conversion direction was applied backwards (caught, 3x error)

The spec's formula is `usd_cap = market_cap_basic * FX[listing_currency]`, which is only correct
when `FX` is **USD per unit of the listing currency**. The FX tables this fleet actually fetches —
Frankfurter and open.er-api — publish **local units per 1 USD** (`JPY 158.25`, `TWD 32.77`,
`EUR 0.8876`, `CAD 1.3935`). The first implementation of the 2026-11-04 run multiplied by that
number.

**Effect:** `usd_cap` came out ~158x too large for Japan, so the $300M floor bound on almost
nothing. Japan wrote **3,756 rows instead of 1,380**, and every other region was 3–8x too fat.
Nothing errored; the file was well-formed, correctly sorted and internally consistent.

**How it was caught:** the per-region row counts were compared with the previous session's
archived files. The correct run lands within ~1–3% of the prior day's counts per region (au 303 vs
300, tw 891 vs 920, eu-de 126 vs 121, eu-fr 262 vs 261, eu-it 179 vs 181, eu-es 147 vs 146,
eu-dk 76 vs 77, eu-gr 86 vs 86); the multiplied run was 3x over. **This cross-session row-count
comparison is the only check that catches this class of error, and it should be run on every
international fire.** The spec now states the direction explicitly, names the local-per-USD
convention of both FX providers, and gives the share-count reconciliation
(`market_cap_local / close` = the issuer's real share count) as the tie-breaker.

### 10.2 The carry-over detector used a tolerance and produced phantom carry-overs

Carry-over detection compares today's close with the prior session's file. The first implementation
compared the two with an absolute tolerance of 0.005 price units to absorb float noise. On
2026-11-04 that flagged **4 phantom carry-overs in Australia alone** — Bellevue Gold closed A$1.31
against the prior session's A$1.315, which is a real 0.4% move that the tolerance swallowed, and the
same pattern hit three other ASX names. The run reported 93 carry-over rows instead of the true 89.

The correct rule is **exact equality on the stored representation** (the value as written to the
CSV). The spec now states it, together with the two carry-over signatures (zero volume, or a
non-zero `change_pct` beside an unchanged close — the scanner's stale-leftover change field) and the
requirement that `last_trade_date` walks **back** through the prior files rather than stamping
yesterday's date.

**Neither defect was visible in the output.** Both produced clean files. The rule generalises:
**for a derived archive, the cheapest integrity check is the previous session's file, and the
second cheapest is the source's own arithmetic identity** (here `close − close/(1 + change/100) ==
change_abs`, which passed over all 18,319 priced rows with a worst-case error of 6.8e-13 and proved
the `change` column's percent unit at the same time).

### 10.3 What else this fire added to the routine's evidence

- **28 of 28 spot-checked closes matched Yahoo to the cent**, across all 16 regions — including the
  five Asian names, which were verified on Yahoo's 5-minute bars because the *daily* bars for
  Japan and Taiwan lag the session by up to two days (`7203.T` still served the 2 November row).
- **All 16 regions traded** (16/16 `traded=yes` from `market_session_probe.py`), where the previous
  fire had skipped Japan for Culture Day. The prior-session anchor for Japan is therefore the
  **2 November** file, not the 3 November one — the same walk-back rule the carry-over detector
  needs.
- The ATHEX General Index has no Yahoo symbol; its close (2,662.45, +1.77%) was taken from
  **Euronext Athens' own historical data** and cross-checked against Greek press, and the
  constituent closes it implies (Alpha Bank €4.736 +5.01%, NBG €16.60 +4.50%, Eurobank €4.602
  +1.50%, Optima €13.48 +3.06%) match the snapshot exactly.
- **The DAX is quoted two ways.** The Xetra closing price is 26,437.67 (+2.22%); one outlet quotes
  the later auction value 26,479.33 (+2.38%). The file uses Xetra and says so.
