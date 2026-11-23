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

---

## 11. The cap carrier rule, the report skeleton, and the venue-official price rule

Date: 2026-11-05. Scope: cron #05's prompt (`05-eod-international-daily.md`), the
`eod-watchlist-snapshot` skill spec, a new build-time assertion helper, and this file. The
FX direction and the exact carry-over comparison were fixed on 2026-11-04 (sections 10.1 and
10.2); this round takes the three defects that survived that fire.

### 11.1 The market-cap carrier rule was wrong, and it is measurable in the archive

The 2026-11-03 run reported that "share-class market caps are company-level" and that a
preferred line can top its region's mover list. The rule that was supposed to prevent it did
not exist, and the underlying defect is sharper than the note says.

**TradingView's cap is company-level AND denominated in the currency of the LINE that carries
it.** One issuer, three lines, measured against the scanner on 2026-11-04:

| line | class | `market_cap_basic` | `currency` | published `market_cap` (USD) |
|---|---|---|---|---|
| `TSX:ENB` | common | 155,521,863,830 | CAD | $111.1bn |
| `TSX:ENB.PR.B` | preferred | 155,521,863,830 | CAD | $111.1bn |
| `TSX:ENB.PF.V` | preferred, **quoted in USD** | 155,521,884,141 | **USD** | **$155.5bn** |

The third line trades in USD, so converting it with its own currency leaves the raw number
alone — and the same issuer ends up with two "USD" caps that differ by **1.4x**, both written
as USD into the same CSV. Seventeen Enbridge preferred lines are affected in the 2026-11-04
Canada file. A consumer cannot tell from the file that the two disagree.

The fix resolves the cap to the issuer's **primary listing line** and converts it **once**, with
the primary's currency. Every row publishes `cap_source_symbol` (the line the cap came from),
`share_class` (`common`/`preferred`/`unit`/`other`), and a build-time assertion requires that a
carried cap lands on a `common` line of the **same ticker root**. The group resolution happens
**before** the floor is applied, so a group either survives the floor entirely or is excluded
entirely — a published preferred never points at a cap source that is not in the file.

Two traps are recorded in the spec because both fail silently:

- **`share_class` cannot come from the scanner's `type` column.** `TSX:ENB` and `TSX:ENB.PR.B`
  both return `type=stock`; only the US scanner's `dr` distinguishes a depositary receipt. The
  class comes from the ticker suffix and the description.
- **A preferred line must never outrank a common line on a company-level cap.** The preferred
  carries the issuer's cap, so the common line sorts above it in every cap-ranked table.

### 11.2 The BHP claim from 2026-11-03 does not survive a check — and the check is now built

The 2026-11-03 note said `ASX:BHP` "implies 5.11bn shares against a real count near 2.13bn, so
BHP's market cap reads ~$202bn instead of ~$86bn", and called it a repeat of the 2 November
anomaly. **Nothing in the archive supports $86bn.** The implied count is ≈5.16bn on every one
of the eight archived sessions, and BHP Group Ltd's ordinary share count is ≈5.16bn.

The new cross-venue check settles it with two independent readings of the same company-level
cap: `ASX:BHP` published $199,978,375,677 (A$286.81bn ÷ 1.434205) and the ADR line `NYSE:BHP`
reads $199,731,606,351 — **agreement within 0.12%**. The cap is right; the note was wrong.

The lesson is the reason the check is in the spec rather than a one-off: **a cap claim with no
second reading behind it is not publishable.** The America scanner
(`symbols.query.types = ["stock","dr"]`) returns 13,376 rows in three calls — 737 of them `dr`
— and the OTC lines come back with them, so the second reading is cheap. The same pull is the
source for `us_listing`, which is why the three fixes interlock.

### 11.3 `us_listing` — and the file that looks like the source but is not

`us_listing` (`NYSE` / `NASDAQ` / `ADR` / `OTC` / `none`) makes the foreign tape reachable for a
US trader, and the TL;DR names the moves that have a US-listed line.

**The source is the America scanner, not `us-eod/{date}.csv`.** That file is shibui's
`country_iso='US'` universe: on 2026-11-04 `BHP`, `RIO`, `SAP` and `TSM` are all absent from
it, because shibui's US universe carries 10 ADR lines out of ~5,000 rows. Matching is on the
issuer, not the ticker — the America scanner describes the US line as "BHP Group Ltd Sponsored
American Depositary Receipt Repr 2 Shs" against the AU line's "BHP Group Ltd".

### 11.4 The report skeleton, and what was actually wrong with it

`summary.md` now has a fixed skeleton: `## TL;DR` (exactly 3 bullets), `## Market context`
(coverage table, then index levels, then regional breadth), `## Top movers` (**one table per
region**), `## Below the gate`, `## No catalyst`, `## Method, source health & caveats`.

**The old section list was not the problem.** It had been stable since 2026-10-30. The defect
was what the movers table *contained*: one flat list that mixed regions, mixed in below-the-cap
names, and mixed in names with no catalyst, under a report with no TL;DR. `## Below the gate`
publishes the names that moved and would have been published but for the cap floor (a −24.72%
move is not noise); `## No catalyst` holds the names that moved with no sourced driver, so they
cannot dilute the mover table. The coverage table now counts exclusions **per reason**, from a
closed set: `no_market_cap`, `below_cap_floor`, `below_volume`, `issuer_unresolved`,
`cap_issuer_mismatch`, `stale_venue_print`.

One correction to the old prompt: it said cron #90's auditor and the downstream briefs key on
the section names. **They do not** — #90 keys on the artifact *path*
(`international-eod/{date}/<region>.csv`), which is unchanged, and nothing in the fleet reads
`summary.md`'s headings. The names are now pinned because the *reader* keys on them.

### 11.5 The venue-official price rule

Both open price discrepancies were prose notes in the 2026-11-03 report: Vienna's official
auction put AT&S at €139.60 (+6.89%) against the scanner's €138.00 (+5.67%), and the ATHEX
official close (2,616.12, euro2day) sat 1.4 points away from TradingEconomics' CFD (2,617.5).

The rule is now explicit: **the venue's own auction/close wins**, the row carries both values
and the delta in a `price_conflict` column (`official=… source=… third_party=… delta=…`), and
the index table publishes the same way. A CFD is never venue-official — it trades continuously
and prints a different level at the same instant. Where no official price can be obtained the
third-party close stands and the row carries no `price_conflict`: an unverified conflict is not
a conflict.

### 11.6 The assertions are code now

`scripts/intl_assert.py` performs the four assertions against a built directory — no
unaccounted cap, a reason on every excluded row plus the manifest's per-reason counts and the
`unique_instruments == written + sum(excluded)` identity, the summary's tables reconciled
against the CSVs and the manifest, and `us_listing` plus a parsable `price_conflict` on every
published row. 23 unit tests (`tests/test_intl_assert.py`), and the whole skill suite is 165
tests green.

Run against the 2026-11-04 artifact it reports **4,472 failures** — one per published row
missing the four provenance columns — with the message *"the artifact predates the 18-column
schema and must be rebuilt, not patched"*. That is the intended result: the old files are not
repairable by hand, and the next fire has to build them the new way.

The 14 → 18 column change is a schema change for the archive's consumers, so `## Method` must
state the column count whenever it differs from the previous session — the same way a unit
change is stated. A mixed archive is expected and is the reason `csv_columns` is now in
`_manifest.json`.

### 11.7 A dangling reference, found on the way

The prompt pointed at "the skill's *The machine-readable companions* section" for the contract
of `_manifest.json`, `_excluded.json` and `_carryover.json`. **That section did not exist.**
It now does, and it specifies the manifest's per-region `excluded` map (a nested map, because a
closed reason set cannot grow a sixth reason without another flat key), the published table
counts (`mover_rows`, `below_gate_rows`, `no_catalyst_rows`), and the `csv_columns` field.

## 11. Delegating the catalyst research did not pay off (2026-11-04)

The one genuinely open-ended part of this routine is attributing a dated catalyst to each of ~100
headline movers. On 2026-11-04 that work was split across **two background research subagents** —
one for the Canada/Australia/Japan/Taiwan cluster, one for the twelve EU venues.

**Outcome: neither returned a usable per-ticker result inside the run window.** At cancel time the
EU agent had produced a macro-driver summary and no ticker lines; the other had built a todo list
for the Canadian gold cohort and was still working through it. Both were canceled and **every
catalyst in the published artifact was sourced by the main session's own `web_search` calls** —
company IR releases, exchange wires, analyst actions, and index-level press. The delegation cost
roughly 25 minutes of wall clock and contributed nothing that reached the file.

**What the spec now says (`SKILL.md`, "Catalyst research: do it INLINE with `web_search`"):**

- Research catalysts inline in the main session; **batch two `web_search` calls per turn** and
  search per *cluster* (all the gold names together, all the bank names together), not per ticker.
- Use Yahoo's dated news API
  (`query2.finance.yahoo.com/v1/finance/search?q=<SYMBOL>&newsCount=12`, `providerPublishTime`
  gives the date) as the fastest per-ticker route — and always confirm the **year** before quoting
  a number.
- Keep index levels and per-ticker catalysts as separate steps; the first comes from the chart API
  and press, the second from the news path.
- Write "no company-specific release found" plus the sourced driver when nothing company-specific
  exists. Never publish an unattributed guess.
- **A subagent's output is a lead, not a source.** If you delegate, re-source every line
  independently and time-box it.

**The generalisable lesson for the fleet:** a delegated *research* step inside a scheduled, timed
routine is a liability when it cannot be verified inside the same window — the artifact has to ship
with whatever the main session can source itself. Delegation pays off for work whose output can be
re-checked at leisure; here it could not. The data half of this routine (scanner pull, FX, floors,
carry-over, verification) was never delegated and should not be: those steps produce the numbers,
and they are cheap.

---

## 12. The universe is the scanner's `country` field, and four build traps (2026-11-09)

Date: 2026-11-09. Scope: cron #05's build path. The 2026-11-09 fire published 4,308 rows across
16 regions and passed `scripts/intl_assert.py` with **0 failures** and 97 warnings — the same
warning count the 2026-11-06 artifact produces on the same check, so the warning profile is the
baseline, not a regression.

### 12.1 The universe definition, recovered from the archived row counts

The country scanner's `symbols.query.types = ["stock"]` pull returns **every instrument quoted in
that country**, including foreign issuers' local lines: `XETR:APC` and `VIE:AAPL` are Apple Inc.
on German and Austrian venues. A country pull therefore does NOT hold that country's own
issuers, and a file built from it would publish Apple and Nvidia as "German" and "Austrian"
names.

**The filter is the scanner's `country` column — the ISSUER's country — and the endpoint takes it
as `filter`, not `filters`.** The `filters` key (a list of `{"field", "operator", "value"}`
objects) is **silently ignored**: the response comes back with the unfiltered `totalCount` and
no error, which is how a run can believe it applied a cap filter when it applied nothing. The
key that works is `filter`: `[{"left": "country", "operation": "equal", "right": "Germany"}]`.

The recovered filter reproduces the 2026-11-06 session's universe counts **exactly** — at 65/65,
it 392/392, dk 134/134, ie 19/19, fi 188/188, jp 3905/3902, tw 2335/2334, de 4312/4307 — which is
how the definition was identified: a candidate filter is right when it reproduces the archived
counts, and every other candidate (a cap band, a volume band, a price band, an exchange list)
missed by 3x to 20x.

**So a region file holds that country's own issuers, and the foreign megacaps are gone.**

### 12.2 Four build traps, each of which produced a plausible file

1. **The ticker is `row["s"]`, not `row["d"][0]`.** The scanner's data array starts with the
   NAME, not the symbol: `d[0]` is `"ARL"`, while the symbol is the sibling key `s`
   (`"ASX:ARL"`). Reading the ticker from `d[0]` silently groups issuers by their first name
   token — the file still looks complete and every column is still right.
2. **Every preferred SERIES is its own line.** The line key must keep the share-class suffix
   (`TSX:IFC.PR.K` and `TSX:IFC.PR.L` are two lines of one issuer); collapsing on the root
   ticker alone merges them and drops ~17% of Canada's published rows.
3. **The carry-over test compares against the IMMEDIATE prior session only.** The walk-back is
   for finding `last_trade_date`, not for deciding that a row is a carry-over. Comparing the
   close against ANY earlier session's file raises the carry-over count from 92 to ~330 and
   flags real trades (XETR:BMW -0.84% on 9 Nov) as non-trading rows.
4. **The America scanner labels NYSE American `AMEX`** (and the pre-Nasdaq codes `NASDAQGS` /
   `NMS`). `AMEX` is not in the published `us_listing` vocabulary (`NYSE`/`NASDAQ`/`ADR`/`OTC`/
   `none`), so every row it touches is a hard assertion failure — 35 rows in the 2026-11-09
   build. Map `AMEX` to `NYSE` at the matcher, not in the vocabulary.

### 12.3 What the cross-session check caught this time

The per-region WRITTEN row counts landed within 4% of the 2026-11-06 archive in every region
(au 295 vs 297, jp 1358 vs 1375, tw 846 vs 882, ca 629 vs 633, de 108 vs 112, fr 258 vs 272,
it 180 vs 179, es 147 vs 147, nl 56 vs 62, be 77 vs 77, at 51 vs 50, pt 27 vs 27, ie 17 vs 17,
fi 100 vs 101, dk 75 vs 75, gr 84 vs 86) — which is the cheapest available proof that the FX
conversion direction, the floors and the cap-carrier rule all still hold.

### 12.4 The 97 warnings are the baseline

All 97 are the same heuristic: the checker reduces a description to its issuer by cutting at the
first class marker (`cum|pref|preferred|unit|class|non-voting|depositary|ads|gdr`), and Canadian
preferred descriptions put the COUPON before the marker (`"Enbridge Inc. 5.5 % Cum Red Pfd …"`
reduces to `"Enbridge Inc. 5.5 %"`, against the primary line's `"Enbridge Inc."`). The
issuer-preservation assertion itself passes — the ticker roots match on every carried cap.

## 13. The venue collapse must prefer the issuer's PRIMARY venue, and the change field must reconcile with the prior close (2026-11-13)

Date: 2026-11-13. Scope: cron #05's build path. Artifact: `international-eod/2026-11-13/` —
4,383 rows across 16 regions, `scripts/intl_assert.py` green with 0 failures and 97 warnings (the
documented baseline).

**The defect.** The collapse picked the busiest venue line per (symbol, share class). That
published `NEO:QBR.A` (Quebecor Class A, Cboe Canada) at C$74 with a **+105.56%** change, while
the issuer's primary line, `TSX:QBR.A`, closed at C$80, +2.83%. The NEO line's own arithmetic
implies a prior close of **C$36** — Quebecor had not traded there for months — so the line's
change field was stale and the stock never moved 105% that day. Nothing errored; the file was
well-formed and the row was the largest mover in its region.

**How it was caught.** The cross-session check (§12.3) did not catch it — the row counts were
within tolerance. What caught it was the **source's own arithmetic identity**: the implied prior
close `close / (1 + change/100)` must reconcile with the prior session's close for the same
instrument. That test is now built into the collapse (see the skill spec, "The venue-collapse
rule"), and the corrected rule publishes `TSX:QBR.A` at +2.83% and drops the stale NEO line,
counted in the manifest's `off_official_rows` (48 across the 16 regions) and disclosed in the
report's caveats.

**Two traps found while fixing it, both of which produced a plausible file.**
- **The prior-close lookup must be per SYMBOL, not per issuer root.** Comparing a preferred
  line's implied prior with the COMMON line's prior close flags every Canadian preferred as
  stale: 183 false exclusions, and the Canadian file fell from 621 to 475 written rows against a
  prior session of 631. `TSX:BCE.PR.B` is compared with `TSX:BCE.PR.B`'s own prior close.
- **A carried-over close is not a stale print.** A row whose close EQUALS the prior close is a
  carry-over (disclosed in `_carryover.json`) even when its change field is a leftover; the
  implied-prior test only applies to rows whose close has moved.

**The generalised lesson for the fleet.** A multi-venue source needs a **primary-venue
preference** and a **second reading of its own arithmetic**, not a "largest number wins" rule.
The busiest venue's line is often the stale one, and the move it reports can be off by a factor
of two. This is the same shape as the archive's other silent-defect classes — the FX direction,
the carry-over tolerance — and it is caught the same way: by reconciling the source against its
own prior reading, not by checking the output for plausibility.


## 14. The carrier line is the one with the SOURCE's own cap, and a contract adjustment can fake a 54% gain (2026-11-16)

Date: 2026-11-16. Scope: cron #05's build path. Artifact: `international-eod/2026-11-16/` - 4,381
rows across 16 regions, `scripts/intl_assert.py` green with **0 failures and 97 warnings** (the
documented baseline, unchanged from the 2026-11-13 artifact).

**Finding 1 - "which common line is the primary" was never written down, and the obvious answer is
wrong.** The skill says the issuer's primary line is the group's `common` line, but a root group can
hold several common lines (Bombardier `TSX:BBD.A` and `TSX:BBD.B`, Canadian Tire `TSX:CTC` and
`TSX:CTC.A`, DRI Healthcare `TSX:DHT.U` and `TSX:DHT.UN`), and the published `cap_source_symbol`
must pick one. The answer that fits the archive is **the line whose `market_cap_basic` carries the
source's own per-line cap**: the source computes that field as `close x share count` for one line per
instrument, so it arrives with a **fractional part**, while every sibling line of the same issuer
carries the company-level integer cap. On all 14 Canadian root groups with more than one common line
this picks the carrier, and it is the only rule that survives the three cases a volume tie-break gets
wrong - `TSX:DHT.U` (200 shares) beats `TSX:DHT.UN` (23,807), `TSX:FFH.U` (0) beats `TSX:FFH`
(49,304) and `TSX:SGR.U` (22,735) beats `TSX:SGR.UN` (123,436). Where no common line carries a
fractional cap, the most liquid common line is the primary. The rule is now in the skill spec.

**The issuer group is keyed on the VENUE as well as the ticker root.** `scripts/intl_assert.py`
compares the venue-qualified ticker root (`TSX:ENB` vs `TSXV:ENB`), so a cap carried across venues
is a hard failure. Keying the group on `(venue, root)` keeps every carry venue-consistent, and a
group whose common line sits on another venue is excluded as `issuer_unresolved` rather than
published with a borrowed cap.

**Finding 2 - the implied-prior test cannot catch a contract adjustment, and it produced a fake
+54% gain.** `TWSE:3714` (Ennostar) returned **+54.14%** on its first session back from a trading
suspension: TAIFEX contract adjustment suspended the stock from 5 to 13 November for a **NT$4.579508488
capital repayment and share consolidation**, effective 16 November (1,084.0983 ex-right shares per
contract). The stock closed at NT$87.40 against a pre-adjustment NT$56.70 - a real fall of about
**16%**, published as a **+54% gain**. The source's own arithmetic still reconciles (the implied
prior equals the unadjusted prior close), so the stale-print test passes it and the row looks clean:
the off-official test is blind to a change in the PRICE BASIS. The rule is now in the skill spec: a
`change` above ~20% is checked for a corporate action before it is published as a move, the `open`
column is the tell (`TWSE:3714` opened at NT$101 against a NT$87.40 close), the row stays in the CSV
with the source's own field, and it is **excluded from the mover tables and from the headline** with
the artefact disclosed in the caveats.

**What the cross-session check caught this time.** The per-region WRITTEN row counts landed within
1% of the 2026-11-13 archive in every region (au 299 vs 293, jp 1,383 vs 1,382, tw 879 vs 872,
ca 648 vs 658, de 115 vs 115, fr 257 vs 260, it 178 vs 179, es 136 vs 137, nl 56 vs 56, be 76 vs 76,
at 51 vs 50, pt 27 vs 28, ie 17 vs 17, fi 101 vs 101, dk 75 vs 75, gr 83 vs 84), and the numeric
formatter regression test reproduced **34,074 of 34,074** numeric cells byte-for-byte. The
2026-11-16 artifact also ran with **zero off-official rows** (the 13 November file dropped 48), so
the stale-print path stayed dormant - which is exactly why the contract-adjustment artefact had to
be caught by a different test.

---

## 15. The `us_listing` matcher was matching nothing (2026-11-19)

**Finding 1 - the America scanner appends " Ltd." WITH a trailing period, and the matcher did not
strip it, so every issuer with a " Ltd." US line was published as `us_listing=none`.** The
matcher reduced a description to an issuer key by dropping the corporate-form words from the END
of the token list; "Ltd." was not in the form-word list (only "ltd" was), so the trailing period
kept it alive and the key came out `accorsaltd` against the local `accor`. The key never matched,
the exact lookup missed, and the prefix bucket could not rescue it either. Measured on the
2026-11-19 fire: **186 issuers that DO have a US line were published as `none`** - Accor, Ampol,
Asics, Air Water, Amotiv, ASX Limited itself, Amundi-type funds, ChiNext-style small caps, all of
them. The archive has carried this false absence for every session so far.

The fix is one-directional, which is why it was safe to take: strip the trailing period from every
token before the form-word pop, and split the token list on ALL punctuation rather than only on
spaces and dots ("Co.Ltd." -> `Co`, `Ltd`; "T&D Holdings, Inc." -> `td`; "M3, Inc." -> `m3`). The
minimum-key-length guard came down from 3 to 2, because the shorter key is now the CORRECT one.

**Finding 2 - the same matcher paired DIFFERENT companies, and the fix's cost is now visible.**
Twelve rows lost a US listing, and in every case the old match was wrong: `Aegean Airlines SA`
(ATHEX) was paired with `Aegon Ltd` (Netherlands), `Challenger Limited` with `Challenger Gold`,
`Endeavour Group` with `Endeavour Silver`, `Perpetual Limited` with `Perpetuals.com`, `Banco
Santander, S.A.` with `Banco Santander - Chile`, `Capital B` with `Capital Bancorp`, `Iren S.p.A.`
with `IREN Limited` (an Australian issuer), `Mitsubishi Corporation` with `Mitsubishi Chemical`,
`Sumitomo Corporation` with `Sumitomo Chemical`, `Black Diamond Group` with `Black Diamond
Therapeutics` and `Integral Group` with `Integra LifeSciences`. No US line exists for any of the
twelve, so `none` is the correct answer and the loss is a correction.

**The remaining limitation is stated rather than hidden.** The matcher still compares NAMES, so two
same-named issuers in the same country can be paired - the cross-venue cap check is where that
shows up. On 2026-11-19 it flagged 47 pairs above 10%, of which the large ones are genuine cap
disagreements (Seabridge Gold C$2.76bn primary against US$1.95bn on its NYSE American line;
DEUTZ EUR2.01bn against US$2.71bn; GMO Internet US$0.74bn against US$1.89bn; freee US$1.23bn
against US$1.81bn) and the rest pair a local line with an unrelated same-named company. The
America scanner's `country` column IS the issuer's home country on a foreign line
(`NYSE:BHP` -> Australia, `NYSE:SA` -> Canada, `OTC:DEUZF` -> Germany) and is a far stronger
discriminator than the name; a country-guarded matcher was built and measured on this fire, and it
published correct `none` values for the twelve false matches - but it also produced about 50 false
NEGATIVES (Canada Goose, Wienerberger, UniCredit and a dozen genuinely ADR-listed Japanese names
came out `none`), because the guard is strict enough to reject a legitimate line whose country is
stamped differently. **The country guard is therefore NOT in the shipped matcher**; it is the next
step, and it needs a guard of its own (the issuer's distinctive-token subset) before it can be
trusted.

**Finding 3 - the contract-adjustment rule fired for real on 2026-11-19, and it fired on a row the
stale-print test cannot see.** `ASX:CMW` (Cromwell Property Group) returned **+422.86%** on its
first session after a **5-for-1 consolidation** of its stapled securities, approved by securityholders
at the AGM on 17 November (99.71% of votes cast), effective 17 November, with pre-consolidation
securities last trading on 18 November and post-consolidation trading opening on a deferred
settlement basis on 19 November. Securities on issue go from 2,618,866,699 to 523,773,340. The
source computed its own `change` on the SAME unadjusted basis, so the implied prior equals the
unadjusted prior close and **the stale-print test passes it** - exactly the blind spot the rule was
written for. The `open` column is the tell: A$1.74 open against an A$1.83 close, on a row whose
prior close was A$0.35. On the adjusted basis (A$0.35 x 5 = A$1.75) the real move is about
**+4.6%**. The row stays in `au.csv` with the source's own `change_pct`, and it is excluded from
every published table with the artefact disclosed in the caveats.

**Finding 4 - the contract gate is live, and it was proved by fault injection.** The
`intl_assert.py` reconciliation is not vacuous: a copy of the 2026-11-19 artifact with one mover
ticker replaced by a ticker the CSV does not contain FAILS ("a published row the CSV does not
contain is fabricated"), a tampered `mover_rows` counter FAILS ("ca publishes 14 names, the
manifest says 99"), and an `_excluded.json` row with an empty reason FAILS twice. The artifact
itself passes with **0 failures and 97 warnings**, the same 97 as every prior session, and all 97
are the one `cap-provenance` heuristic on Canadian preferred lines whose descriptions do not
reduce to the issuer name (the carrier IS the same issuer by venue-qualified ticker root).
The numeric formatter regression test reproduced **33,813 of 33,813** numeric strings of the
previous published file byte-for-byte.

**Finding 5 - the Dow Jones European close table carries the PREVIOUS session's level for seven
indices.** The 19 November close table lists CAC 40 at 8,147, AEX at 1,099, BEL 20 at 5,953, ATX
at 6,395, PSI 20 at 9,500, IBEX 35 at 19,373, OMX Helsinki at 6,109 and OMX Copenhagen at 1,637 -
every one of them is the **18 November** close from the previous session's archive, while the
change column on the same row is the 19 November change. The DAX row on the same table carries the
19 November close. A second source (elfolio's 19 November European close table) agrees with the
TradingView venue index on all eight (CAC 8,080.74, AEX 1,091.94, BEL 20 5,885.51, ATX 6,379.10,
PSI 20 9,410.29, IBEX 19,186.20, OMXH 6,090.06, OMXC 1,614.03), so the venue index was published and
the disagreement was noted rather than mixing the two.

**What the cross-session check caught this time.** The per-region written row counts landed within
1% of the 2026-11-18 archive in every region (au 297 vs 298, jp 1,368 vs 1,375, tw 849 vs 853, ca
610 vs 613, de 122 vs 123, fr 260 vs 260, it 178 vs 179, es 135 vs 136, nl 56 vs 56, be 76 vs 76, at
50 vs 51, pt 27 vs 27, ie 17 vs 17, fi 101 vs 101, dk 75 vs 75, gr 83 vs 83). The session was the
violent one: the TAIEX fell 4.40% with 128 limit-downs and the OTC board fell 7.22%, so Taiwan's
published set carried 144 liquid names down more than 5% against 6 the day before.

---

## 2026-11-23 — a closed market, two contract-adjustment rows, and an issuer whose country is outside the sixteen boards

**Finding 1 — the session probe's `traded=unknown` after the last session must be CONFIRMED, not
assumed in either direction.** On 23 November the probe answered `traded=unknown` for **Japan**,
reason `after_last_session (last bar 2026-11-20)`. That verdict is ambiguous on its face: the
market may have been shut, or the vendor may not have published the bar yet. **Ambiguity is not a
licence to skip and not a licence to publish a stale session.** The closure was confirmed three
ways before the region was removed:

1. **Per-instrument bars, not only the index.** Yahoo's daily bars for `^N225` **and** for TSE
   constituents (`9984.T`, `7203.T`, `6758.T`, `8306.T`) all stop at 2026-11-20. A missing index
   bar is lag; every constituent missing the same day is a closure.
2. **The venue's own holiday calendar.** JPX publishes its 2026-2027 market holidays and
   `Nov. 23 (Mon.) Labor Thanksgiving Day` is on it; the derivatives notice of 20 November adds
   that the JPX Group ran BCP testing from 21 to 23 November.
3. **The scanner's own staleness.** The Japan pull returned the 20 November session verbatim —
   `TSE:9984` close 3,025 with a -14.4755% change and volume 109,918,800, byte-identical to the
   20 November published row — and the index scan returned the same Nikkei close and the same
   -5.06% change as the 20 November session.

**⇒ A CONFIRMED closure removes the region from the artifact** (no `jp.csv`, no rows in any
movers table, a `closed_regions` block in `_manifest.json`, and the region's last-session index
levels published in the report's index table carrying THAT session's date). Building the closed
region from the scanner's stale pull would have written **1,347 Japanese rows dated 23 November, 1,333 of
them carrying the 20 November move** — SoftBank's -14.48% of 20 November among them — so the artifact
would have asserted a session that never happened. The per-instrument carry-over contract does not
apply to a whole market: carry-over rows are for an instrument that did not trade inside a market
that DID. `scripts/build_intl_eod.py` gained `--closed-regions` (capability marker `INTL_EOD_V2`,
2026-11-23) so this is a first-class path rather than a hand-edited build; the flag is opt-in and
the default behaviour is unchanged.

**Finding 2 — the contract-adjustment rule fired twice in one session, and one of the two is not a
consolidation.** `ASX:ZIP` (Zip Co) printed **+363.50%** on a **1-for-5 share consolidation**
effective 23 November (ASX Notice 1312.26.11; the ETO adjustment notice of 20 November): the
implied prior of A$1.685 equals the 20 November close exactly, so the source measured the change
on the **unadjusted** basis and the stale-print test passes it. On the adjusted basis
(A$1.685 × 5 = A$8.425) the real move is about **-7.3%**, which is what the ASX's own
sharpest-decliners table shows. `EURONEXT:ALAGR` (AgroGeneration) printed **+11,119.51%** against a
EUR0.041 prior close on a **210-share** print; the implied prior of EUR0.041 is the 20 November
close exactly, and the row's own market cap moved with the stale price (EUR9.8m to EUR996m), so
the row is a price-basis artefact rather than a consolidation. Both stay in their CSVs with the
source's own field, per the archive's convention, and are excluded from every published table.

**Finding 3 — three Taiwanese OTC rows printed OUTSIDE Taiwan's ±10% band, again.** `TPEX:3117`
closed NT$17.10 against a NT$12.90 prior close (+32.56%), `TPEX:7415` NT$227.50 against NT$187.00
(+21.66%) and `TPEX:7959` NT$60.10 against NT$51.00 (+17.84%), each opening at the prior close and
each reconciling arithmetically with it. This is the second session running that prints outside the
venue's limit band (2026-11-20 had three), and **all six are below the cap floor or unsourced** —
the limit-band class deserves its own automated screen, because the per-row test that catches
everything else cannot see it.

**Finding 4 — the issuer-country universe rule silently drops a $26bn AI name.**
`STMicroelectronics` — the day's biggest single European AI mover at **+8.96% to EUR40.01** — is
**not in the artifact at all**. The scanner files its country as **Switzerland**, and the universe
is the ISSUER's own country, so its Milan and Paris lines fall outside all sixteen boards. The same
rule excludes any other issuer the vendor files under a country this skill does not cover, and the
omission is invisible in the artifact (the name is simply absent). The session's Milan leader was
therefore Technoprobe, not STM.

**Finding 5 — a small two-source disagreement on a close, disclosed rather than hidden.**
`EURONEXT:GL9` (Glanbia) prints **EUR17.92, -6.91%** from the scanner while the Irish Times
reports **EUR18.09, -6.03%** at the close — a 0.95% difference on the same session. No
**venue-official** Euronext Dublin print was obtained, so the row carries an empty `price_conflict`
cell and the disagreement is disclosed in the row and in the caveats rather than asserted as an
official price.

**What the gate did this time.** The artifact passes `intl_assert.py` with **0 failures and 97
warnings** — the same 97 as the previous session and the one `cap-provenance` heuristic on Canadian
preferred lines whose descriptions do not reduce to the issuer name (the carrier IS the same issuer
by venue-qualified ticker root). The 2026-11-20 artifact passes the same gate with the same 97, so
the run is at parity with the archive's own standard and the warnings are not a new regression.
