---
name: EOD market snapshot (CSV, full universe)
description: >-
  Save a daily CSV of OHLCV + change% + market cap for the entire US-listed
  universe and 16 international markets (AU, JP, TW, CA, EU-DE/FR/IT/ES/NL/BE/AT/PT/IE/FI/DK/GR),
  after the US close. Feeds shibui-finance for ad-hoc historical queries and
  gives you a backtest-friendly archive. Two crons: US 16:00 ET (shibui SQL),
  international 16:30 ET (TradingView stock_prices + Yahoo + helper).
---

> **Policy change 2026-09-22** — the watchlist is no longer the universe.
> This skill now pulls the full US + international universe. The 12-name
> `research/watchlist.yaml` is reserved for personal trade tracking and is
> NOT used as a market-data universe anywhere in this workflow.

> **Compute-optimization pass 2026-09-22** — three compute levers added
> (enrichment cache, holiday skip, movers-default Tue-Fri). Yahoo call cost
> remains ~800/day with default cache TTLs; raising `volume` TTL to 5+ days
> cuts Yahoo calls by ~80% (see "Cache TTL tuning" below).

## Scheduled-run conversation title (FIRST ACTION)

If this session was started by a scheduled cron run — the first message begins with
`# Cloud Mavis cron:` — set this conversation's title before doing anything else. Every scheduled
run gets its own conversation; it is never appended to an earlier run's conversation.

1. Resolve today's date in US/Eastern: `TZ=America/New_York date +%d-%m` (day-month, no year).
2. Build the title: `[<DD-MM>] <NN>-<routine name>`. Take `<NN>` and `<routine name>` from the
   first line of that cron prompt (`# Cloud Mavis cron: <routine name> (cron #NN)`).
   Example: `[31-10] 12-cross-asset-correlation-snapshot`.
3. Set it with one call: `mcp_invoke` with tool_name `session_update` and arguments
   `{"session_id": "me", "title": "<the title>"}`. `me` means THIS conversation.
   If `mcp_invoke` reports that the tool is unknown, call `tool_search` with the query
   "session title update", then retry the same `mcp_invoke` call.
4. If the title cannot be set for any reason, carry on with the routine. This step must never
   block, delay, or fail the artifact.

If this session was NOT started by a scheduled cron run, ignore this section.

# EOD market snapshot (CSV)

Produces per-day CSVs covering the **full US-listed universe** plus **16 international markets** (EU/ASX/JP/TW/CA), written the moment each market's cash close settles.

## Two crons (do not merge — different timing)

| Cron ID | Schedule | Markets | Source |
|---|---|---|---|
| `0a87adbe-1f83-4c7c-9253-38a6aaf985aa` | `30 16 * * 1-5` ET | US (4935 rows, same-day) | `shibui-finance` SQL |
| `5edfb4aa-f234-47de-b528-a686b700b0af` | `35 16 * * 1-5` ET | EU/ASX/JP/TW/CA (16 regions) | `tradingview-advanced` + `yahoo-finance` via `run_intl_cron.py` |

Manual trigger: user asks "snapshot today" or "save today's EOD" — invoke the matching cron logic.

## Output

- US: `C:\Users\admin\.minimax\projects\coding-shared\research\historical_eod\YYYY-MM-DD.csv`
- International: `…\historical_eod\<region>\YYYY-MM-DD.csv` where `<region>` ∈ `au, jp, tw, ca, eu-de, eu-fr, eu-it, eu-es, eu-nl, eu-be, eu-at, eu-pt, eu-ie, eu-fi, eu-dk, eu-gr`
- Audit lines to `research\logs\audit.log`
- Side-effect caches:
  - `research\universe_cache\<region>\meta.json` + `tickers.json` (ticker universe, 7-day TTL)
  - `research\enrichment_cache\cache.json` (per-ticker volume/pe/sector, 1d/30d/30d TTL)

## Schema (CSV header)

```
date,ticker,name,open,high,low,close,volume,change_pct,market_cap,pe_ratio,sector,currency,exchange,cap_source_symbol,share_class,us_listing,price_conflict
```

Numeric columns formatted to 4 sig figs; empty cell if data missing (don't write `"N/A"`).

For non-top-N tickers, `volume` / `pe_ratio` / `sector` may be blank (TradingView screener strips them). The enrichment cache fills them in for the top-N per region (default 500).

The last four columns are the **provenance columns**, and they are what make a cap, a listing and
a price auditable after the fact. Every row carries all four; an empty cell means "no conflict"
or "no US listing", never "unknown":

| column | value | meaning |
|---|---|---|
| `cap_source_symbol` | the ticker of the line the cap was taken from | the issuer's **primary** line — see the market-cap carrier contract below. Equals the row's own `ticker` when the row IS the primary line. |
| `share_class` | `common` / `preferred` / `unit` / `other` | the line's class. `common` is the issuer's primary line. |
| `us_listing` | `NYSE` / `NASDAQ` / `ADR` / `OTC` / `none` | whether a US trader can reach this issuer, and how. |
| `price_conflict` | `official=… source=… third_party=… delta=…` | non-empty ONLY when the venue's official print differed from the third-party quote and the official price was published. |

**The header grew from 14 columns to 18 in this revision, and a consumer that reads by position
breaks.** State the column count in `## Method` whenever it differs from the previous session,
the same way the units contract requires for a unit change.

## Units, floors and the market-cap contract (READ BEFORE WRITING ANY CSV)

**`market_cap` is written in USD. `open`/`high`/`low`/`close` stay in the listing currency**, and
the `currency` column says which. This is a hard rule: the same column has been written two ways
in this archive, and a consumer cannot tell from the file which one it is holding.

- **TradingView's `market_cap_basic` is in the LISTING CURRENCY, not USD.** Verified 2026-11-03:
  a server-side filter of `market_cap_basic > 300000000` on the Japan endpoint still returns names
  whose market cap is ¥385m — the field is compared as a JPY number, so a "¥300m" floor keeps
  essentially every listed Japanese company. Share-count reconciliation settles the unit directly:
  `market_cap_basic / close` returns the issuer's real share count for SAP (1.1626bn), Toyota
  (11.900bn), TSMC (25.770bn) and Genmab (59.11m) — all in local currency.
- **So the per-region USD floors CANNOT be handed to the screener as server-side filters.**
  `scripts/screener_filters.py` describes the field as USD; that comment is wrong. Convert first,
  then filter locally:

      usd_cap = market_cap_basic * FX[listing_currency]
      keep the row iff usd_cap >= floor_usd[region]   (and volume >= min_volume, where the region has one)

  `screener_filters.usd_floor_for_region(region)` returns the `(floor_usd, min_volume)` pair.
  Treat `filters_for_region()` as a filter over the **local-currency** number, never as the USD floor.
- **THE CONVERSION DIRECTION IS NOT OPTIONAL — read the unit of your FX table.** The formula above
  multiplies by `FX[listing_currency]`, which is only correct when `FX` is **USD per one unit of the
  listing currency**. Every FX table this fleet actually fetches is the OTHER kind — **local units
  per 1 USD** (Frankfurter and open.er-api both publish `JPY 158.25`, `TWD 32.77`, `EUR 0.8876`,
  `CAD 1.3935` per USD) — and with those tables the conversion is a **DIVISION**:

      usd_cap = market_cap_basic / FX_per_USD[listing_currency]

  **Multiplying by a local-per-USD rate is a silent 100–200x error that still produces a
  plausible-looking file.** Measured 2026-11-04 (cron #05): multiplying by 158.4 instead of
  dividing made Japan write **3,756 rows instead of 1,380** and left the $300M floor binding on
  almost nothing, while every other region came out 3–8x too fat. The archive comparison against
  the previous session's file is what caught it (the correct run lands within ~1–3% of the prior
  day's per-region row counts; the multiplied run lands 3x over). **Settle the direction before you
  write anything:** `market_cap_local / close` must return the issuer's real share count, and one
  row must satisfy `usd_cap * FX_per_USD == market_cap_local`. If your FX table is labelled "per
  1 USD", divide.
- **The floors, in USD, applied AFTER conversion:**

  | region | floor (USD) | extra volume gate |
  |---|---|---|
  | `au` | $300M | ≥ 100,000 |
  | `jp` | $300M | — |
  | `tw` | $200M | — |
  | `ca` | $200M | — |
  | `eu-de` | $300M | ≥ 50,000 |
  | `eu-fr` `eu-it` `eu-es` `eu-nl` `eu-be` `eu-at` | $100M | — |
  | `eu-ie` | $200M | — |
  | `eu-fi` `eu-dk` | $100M | — |
  | `eu-pt` `eu-gr` | $50M | — |

- **A row whose market cap the source does not report is EXCLUDED, not written blank.** A row with
  no cap cannot be tested against a floor, so writing it puts an unscreenable row in a screened
  file. Publish the excluded count per region in the Coverage table.
- **Every excluded row carries a `reason` from this closed set, and the Coverage table counts
  them per reason.** A reader must be able to tell "no market cap at all" from "below the
  floor" from "a carry-over" from "a stale venue print" — the 2026-11-03 run excluded 243
  no-cap rows into `_excluded.json` and, without a reason column, none of that was legible.

  | reason | meaning |
  |---|---|
  | `no_market_cap` | the source reports no market cap for the row |
  | `below_cap_floor` | the row has a cap, but below the region's USD floor — these are the names published under `## Below the gate` |
  | `below_volume` | the row has a cap but fails the region's volume gate |
  | `issuer_unresolved` | the row's cap could not be resolved to a primary listing line |
  | `cap_issuer_mismatch` | a carried cap failed the same-issuer assertion — the group was dropped |
  | `stale_venue_print` | the row's print is not this session's (off-official venue row) |

  The Coverage table publishes the per-reason counts for every region, and `_excluded.json`
  carries the same reasons on every row. A row with an empty or unknown reason is a defect in
  the build, not a row to publish.
- **Never change the unit of this column silently.** If a run writes it differently from the
  previous session, say so in the artifact and in `## Source health`, and restate the earlier
  session. A series that switches unit mid-stream reads as a market event that never happened.
- **Check any change to this contract with a share-count reconciliation**, not with a length or a
  spot check: `market_cap_basic / close` must land on the issuer's real share count.

## The market-cap carrier contract (READ BEFORE WRITING ANY CSV)

**The cap belongs to the ISSUER, and the source's cap is denominated in the currency of the
LINE that carries it — not in one currency for the whole issuer.** That single fact is the
carrier defect, and it is live in the archive.

Measured 2026-11-04 against the TradingView per-country scanner — one issuer, three lines:

| line | class | `market_cap_basic` | `currency` | published `market_cap` (USD) |
|---|---|---|---|---|
| `TSX:ENB` | common | 155,521,863,830 | CAD | $111.1bn |
| `TSX:ENB.PR.B` | preferred | 155,521,863,830 | CAD | $111.1bn |
| `TSX:ENB.PF.V` | preferred, **quoted in USD** | 155,521,884,141 | **USD** | **$155.5bn** |

One issuer, one company-level cap, the same integer — but because the third line trades in USD,
converting it with its OWN currency leaves it at $155.5bn while the common line converts to
$111.1bn. **The same issuer then carries two "USD" caps that differ by 1.4x**, the preferred
line clears the cap floor because of it, and a preferred outranks the common line on a
company-level cap. Seventeen Enbridge preferred lines are affected in the 2026-11-04 Canada file
alone, and the two numbers are both "USD" in the CSV, so a consumer cannot tell they disagree.

**So the cap is resolved to the issuer's PRIMARY line, converted ONCE, and every line of that
issuer carries that one USD figure.** The rule, in four parts:

1. **Resolve the primary line.** Group the region's rows into issuers with the company key the
   venue-collapse rule already uses (`(description, ticker root)`; German rows dedupe by company
   description). The primary line is the group's `common` line — the one whose ticker carries no
   share-class suffix and whose description carries no preferred/unit marker. **A group with no
   `common` line has no primary**: its cap cannot be resolved to a primary listing, so its names
   are DROPPED from the cap-filtered table and recorded in `_excluded.json` with reason
   `issuer_unresolved`. They are never published with a borrowed cap.
2. **Carry the cap, and record the carry.** Every row publishes `cap_source_symbol`: the ticker
   of the line whose `market_cap_basic` the published USD cap was taken from. For the primary
   line it is the row's own ticker; for every other line of the issuer it is the primary's
   ticker. **The conversion is applied ONCE, to the primary's `market_cap_basic`, using the
   PRIMARY's currency** — never to each line's own number.
   **Order matters: resolve the issuer groups and assign the primary's cap BEFORE the floor is
   applied.** A group then either survives the floor entirely or is excluded entirely, so a
   published row never points at a `cap_source_symbol` that is not in the file — and a preferred
   line of a below-floor issuer is below the floor too, instead of inheriting a cap its own
   issuer never earned.
3. **Assert the carry is issuer-preserving.** For every row whose `cap_source_symbol` differs
   from its own ticker, the two symbols MUST resolve to the same issuer group. This is a
   build-time assertion, not a note: a mismatch means a cap was carried across issuers, so the
   group is dropped and recorded with reason `cap_issuer_mismatch`. A carried cap whose issuer
   cannot be resolved is never published.
4. **Flag the non-common lines, and never let one outrank the common line.** `share_class` is
   `common` / `preferred` / `unit` / `other`, derived from the ticker suffix and the description
   — **NOT from the scanner's `type` column, which reads `stock` for common AND preferred lines
   alike** (verified 2026-11-05: `TSX:ENB` and `TSX:ENB.PR.B` both return `type=stock`; only
   the US scanner's `dr` distinguishes a depositary receipt). A preferred line carries the
   issuer's company-level cap, so **in any cap-ranked table the issuer's `common` line sorts
   ABOVE it, always** — a preferred never wins on a borrowed cap. Where a cap-ranked table would
   otherwise be led by a non-common line, publish the common line instead and list the
   preferred lines beneath it, flagged.

### The cross-venue cap check — the ADR line is a second opinion on a cap

The issuer's US line is an independent reading of the same company-level cap, and it is cheap:
`POST https://scanner.tradingview.com/america/scan` with `symbols.query.types = ["stock","dr"]`
returns **13,376** rows in three calls (`range` caps at 6,000 per call), of which **737** are
`type=dr` depositary receipts, and the OTC lines (`OTC:BCMXY`, `OTC:MURGY`, …) come back with
them.

**Where an issuer has a US ADR line, compare the two caps after conversion. They must agree
within 10%.** A disagreement is a cap finding: publish the primary line's cap, record the
delta, and flag the row.

This check is what settles the BHP question, and it is why the check exists. On 2026-11-04
`ASX:BHP` published $199,978,375,677 (A$286.81bn ÷ 1.434205) and the ADR line `NYSE:BHP` reads
$199,731,606,351 — **agreement within 0.12%** — and `market_cap_basic / close` returns ≈5.16bn
shares on both, which is BHP Group Ltd's ordinary share count. The implied count is also stable
across all eight archived sessions (5.08–5.16bn). **The 2026-11-03 run's note that "BHP's cap
still reads ~$202bn vs a real ~$86bn" is a bad lookup in that run's notes, not a defect in the
data** — nothing in the archive supports $86bn, and two independent venues agree the cap is
~$200bn.

Publish that finding the way the check publishes anything else: as a number with a source and a
delta. A run asserting a cap is 2.3x wrong with no second source behind it is how a wrong
number survives for eight sessions, so **a cap claim without a cross-venue or share-count
second reading is not publishable.**

The ADR line is ALSO the source for `us_listing` (below) — it is a per-issuer second reading of
the cap and a per-issuer US listing, in one pull.

### `us_listing` — which of these a US trader can actually reach

Every published row carries `us_listing`: `NYSE` | `NASDAQ` | `ADR` | `OTC` | `none`.

- `ADR` — the issuer has a US line that is a depositary receipt (the America scanner's `type` is
  `dr`). This is the normal case for a foreign issuer.
- `NYSE` / `NASDAQ` — the issuer has its own US listing on that exchange, not a depositary
  receipt.
- `OTC` — the US line is an OTC quotation (`OTC:` prefixed).
- `none` — no US listing.

**Do not source this from `us-eod/{date}.csv`.** That file is shibui's `country_iso='US'`
universe and it does NOT contain the ADRs: on 2026-11-04 `BHP`, `RIO`, `SAP` and `TSM` are all
absent from it, because shibui's US universe carries only 10 ADR lines out of ~5,000 rows. The
America scanner is the source — one pull, three calls, and it returns the OTC lines too.

**Match on the issuer, not on the ticker.** The America scanner describes the US line as "BHP
Group Ltd Sponsored American Depositary Receipt Repr 2 Shs" against the AU line's "BHP Group
Ltd", so strip the depositary/class suffix and compare the issuer name. A name that matches no
US line is `none`.

## The venue-official price rule — the exchange's own print wins

**Where an exchange's own official auction/close price is available and differs from the
third-party quote, the official price IS the price.** The third-party number is not averaged,
not hedged, and not left as a prose note in `## Caveats` — it is published beside the official
one, in the row, with the delta.

Measured 2026-11-03, Vienna: AT&S (`VIE:ATS`) closed €138.00 (+5.67%) on the scanner while the
Vienna official auction printed €139.60 (+6.89%) — and every other checked close on that session
matched its official price to the cent. Measured 2026-11-03, Athens: the ATHEX official close was
2,616.12 (euro2day, 17:25) while TradingEconomics' CFD read 2,617.5 — a 1.4-point difference.
Both sat in the 11-03 report as prose notes, which is exactly how a price conflict survives into
the archive as an unflagged row.

**The rule, in three parts:**

1. **Prefer the venue's own auction/close.** The official close is the number the market settled
   on; a CFD, a broker quote or a scanner's last trade is a derivative of it. Publish the
   official close in `close` and `change_pct`, and derive `change_pct` from the official close
   against the same session's prior close.
2. **Publish the conflict, in the row.** A row whose close was resolved to an official price
   carries `price_conflict`: `official=<price> source=<where> third_party=<price>
   delta=<abs> (<pct>)`. A row with no conflict carries an EMPTY `price_conflict` cell — never
   `"N/A"`.
3. **The same rule applies to the index row.** The `## Market context` index table publishes the
   official index close with its SESSION DATE and source; where a CFD differs, the delta is
   published there too, not only in the caveats.

**What counts as venue-official:** the exchange's own end-of-day auction print (the exchange's
site or its licensed data feed), the local press wire that reports the official close, and the
index provider's own closing level. **A CFD is NOT venue-official** — it is a third-party quote
of an index, it trades continuously, and it can and does print a different level at the same
instant. Where the only available quote for an index is a CFD (there is no Yahoo index symbol for
the ATHEX), the official close comes from the press and the CFD is the third-party value recorded
in `price_conflict`.

**Where no official price can be obtained, the third-party close stands and the row carries no
`price_conflict`** — an unverified conflict is not a conflict. Say which one it was in
`## Source health`.

## The close of record — a SETTLEMENT STAMP is not a PRICE (2026-11-05)

**Never publish a close that has not been checked against an independent reading.** A vendor's
close field can carry the stamp *"Closed at <date> 4:00 PM ET"* and still hold a **pre-auction
print** — on 2026-11-05 the exchange's `/info` `secondaryData.lastSalePrice` read AAPL
345.1551 / MSFT 537.705 / NVDA 182.29 against true closes of **344.17 / 535.93 / 181.60**
(+0.29% / +0.33% / +0.38%), for every name checked, while still stamping the cell as the
close. The 2026-11-04 file had taken the same field and been right — so the field is not
trustworthy *in general*, only on the sessions where it is checked.

**The close of record is the consolidated 16:00 ET auction print.** Two cheap checks:

1. **The Yahoo regular-session final bar** — `chart/{SYM}?interval=1m&range=1d` (NO
   `includePrePost`) ends with a synthetic bar whose `O=H=L=C` and volume is 0; that single
   price IS the official close. The daily bar's close agrees with it.
2. **An independent quote service** — CNBC/CTA (`quote.cnbc.com/quote-html-webservice/…`)
   stamps `last_time` at exactly `16:00:00-05:00` and matched 36/41 sampled closes exactly on
   2026-11-05 (the misses: 4 penny names under 0.1%, and one preferred where CNBC resolved the
   COMMON line because of its own symbol form).

**The tell:** if the vendor's close is ABOVE the last minute's traded price by more than a tick
on a session that fell into the close, the vendor is serving a pre-auction snapshot. Report the
disagreement count; publish one number.

**Also settle the session with a bar-timestamp test, never a hardcoded offset:** the daily bar
is settled when its timestamp is at or after the 16:00 ET close **for that date's UTC offset**
(`ts >= 21:00Z` on an EST date, `>= 20:00Z` on an EDT date). On 2026-11-05, 993 of 4,896
symbols were still serving the PRIOR session's bar at 17:00 ET and 288 more settled on a later
pass — **re-sweep the unsettled rows** rather than publishing the prior session.

**Class-share symbol maps are per vendor, and a plain-base fallback publishes another
security's price.** `ABR-P-D` → Yahoo `ABR-PD`, Nasdaq `ABR^D`; `USB-P-H` → Nasdaq `USB^H`.
Never fall back to the plain base (`LEN-B` → `LEN` is the Class A COMMON line).

**shibui's `LIMIT/OFFSET` pagination needs a unique `ORDER BY`** (`ORDER BY symbol`), or pages
overlap and rows go missing; **keyset pagination** (`WHERE symbol > :last ORDER BY symbol LIMIT
200`, sequential) is the safe form — concurrency makes shibui throttle.

**The numeric formatter must be regression-tested every run:** re-format every numeric string
of the PREVIOUS published file and compare byte-for-byte (35,802/35,802 exact on 2026-11-05).
US rule: 4 significant figures with trailing zeros stripped, **except values >= 100000, which
keep full precision**; `volume` and `market_cap` integers; `change_pct` / `pe_ratio` 4 sig figs.
A plain `%.4g` renders 830500 as `8.305e+05`.

The full run log for 2026-11-05 is in `docs/IMPROVEMENTS-cron20-eod-watchlist.md`.

## Steps — US universe (cron `0a87adbe…`)

1. Paginate `mcp__shibui-finance__stock_data_query` 25 times: `LIMIT 200 OFFSET 0, 200, …, 4800`, filter `country_iso='US'`, join `stock_quotes` for OHLCV on the target date, join `valuation` (market_cap) and `fundamentals_derived_daily` (trailing_pe).
2. Run `C:\Users\admin\AppData\Local\Temp\assemble_eod_csv.py` (or equivalent) to read all 24 externalized artifacts + 1 inline batch, dedupe by first-prefix, parse JSON, write CSV.
3. Append audit: `eod_snapshot target=historical_eod:YYYY-MM-DD rows=4935 source=shibui_sql_universe_corrected_overwrite`.

**Why shibui, not TradingView, for US?** The international TradingView screener response strips `volume` / `pe_ratio` / `sector`. The shibui JOIN schema (`stock_quotes` + `valuation` + `fundamentals_derived_daily`) gives the full CSV row in one query. Swapping US to TradingView would lose three columns.

---

# The US fact table — schema v2, derived columns, quality flags (2026-11-06)

**The US file is the fleet's shared end-of-day fact table.** Before this revision it was a
data dump: a session snapshot with 14 columns, and every downstream routine re-derived
relative volume, the moving averages, the ATR and the gap on its own, from whatever it
happened to have. Two routines then disagreed about what "relative volume" meant, and a
consumer could not tell an empty cell from a failed fetch.

**This section is the contract for the US file.** It is fetched at RUN time, so an edit here
lands with the next fire and needs no prompt redeploy.

## 1. The schema — 30 columns, the first 14 unchanged

```
date,ticker,name,open,high,low,close,volume,change_pct,market_cap,pe_ratio,sector,currency,exchange,
rel_volume,pct_from_52w_high,pct_from_52w_low,sma_20,sma_50,sma_200,pct_vs_sma_50,pct_vs_sma_200,
atr_14,atr_pct,gap_pct,avg_daily_dollar_volume,float_shares,market_cap_usd,cap_source_symbol,data_quality
```

- **The first 14 columns are the original session columns, in the original order.** A
  consumer that reads by position keeps working; the new columns are appended.
- **State the column count in `## Method` whenever it differs from the previous session** —
  the archive now holds 14-column and 30-column files, and a consumer must be able to tell
  them apart without parsing the header.
- The numeric rule is unchanged: 4 significant figures with the fractional trailing zeros
  stripped, except values ≥ 100000 which keep full precision; `volume`, `market_cap`,
  `market_cap_usd`, `avg_daily_dollar_volume` and `float_shares` are integers.
  **Regression-test the formatter every run**: re-format every numeric string of the
  PREVIOUS published file and compare byte-for-byte.

## 2. The derived columns — computed ONCE, here

Every routine in this fleet used to re-derive these. Now the routine derives them once,
from ONE price-history pull, and every consumer reads the same number. The definitions are
the contract:

| column | definition |
|---|---|
| `rel_volume` | session volume ÷ mean volume of the **30 sessions before** the session |
| `avg_daily_dollar_volume` | mean(`close` × `volume`) over those same 30 prior sessions |
| `sma_20` / `sma_50` / `sma_200` | mean close over the last 20 / 50 / 200 bars **ending at** the session bar |
| `pct_vs_sma_50` / `pct_vs_sma_200` | (`close` ÷ `sma` − 1) × 100 |
| `atr_14` | mean true range over the last 14 bars ending at the session bar; TR = max(h−l, \|h−prev_close\|, \|l−prev_close\|) |
| `atr_pct` | `atr_14` ÷ `close` × 100 — the stop-distance measure |
| `pct_from_52w_high` / `pct_from_52w_low` | (`close` − the 252-bar high/low) ÷ that extreme × 100 |
| `gap_pct` | (published `open` − prior close) ÷ prior close × 100 |
| `float_shares` | the vendor's public float (`ownership_stats.shares_float`) |
| `market_cap_usd` | equal to `market_cap` on this file — see the currency rule below |

**One history pull serves both the session and the derived columns.** Ask the daily-bar
feed for a YEAR of daily bars, not one day: the session bar is the last bar, and the
moving averages, the ATR, the 52-week extremes and the 30-session averages all come out
of the same response. A second pull is a second chance to disagree with itself.

**The price history is split-adjusted**, so the averages and the extremes sit on the same
basis as the session close. A reverse split inside the window is not a data error.

**Class-share symbol forms are per vendor, and the plain base is never a fallback**
(`LEN-B` → `LEN` would publish the Class A COMMON line's price under the Class B ticker):
`ABR-P-E` → Yahoo `ABR-PE`, `USB-P-H` → `USB-PH`, `BRK-A` → `BRK-A`.

## 3. `data_quality` — a per-row flag, so a consumer can trust a row

**A row is published with empty cells and NO marker only when the marker is `OK`.** An
empty cell with no flag is the defect this column exists to remove: a consumer cannot
distinguish "not applicable" from "the fetch failed".

The vocabulary is closed. A cell may carry several flags joined with `|`, in this fixed
precedence (most severe first):

| flag | meaning |
|---|---|
| `NO_CAP` | the row's issuer cap could not be resolved — the cell is empty, **never zero** |
| `CAP_CARRIED` | the cap was resolved from another line of the same issuer — see `cap_source_symbol` |
| `HIGH_LOW_UNAVAILABLE` | high/low left empty on purpose: no range bracketed the close |
| `RANGE_ADJUSTED` | high/low came from the vendor's day range, not the daily bar |
| `NO_HISTORY` | no session bar in the price history, so no derived column exists |
| `NO_PE` | no trailing P/E for the row |
| `NO_SECTOR` | no GICS sector for the row |
| `OK` | none of the above — and it appears only alone |

**The Coverage table publishes BOTH the populated counts and the per-flag counts.**
"Populated" alone is not a coverage statement: 4,840 populated closes out of 4,896 rows
reads as 98.8% coverage when 65 of those rows carry a range that had to be abandoned.

## 4. The market-cap carrier rule — one issuer, one cap

**The cap belongs to the ISSUER, and the carrier is the VENDOR'S OWN row** — never a
volume heuristic. The vendor stamps a company-level cap on one class row per company and
leaves the siblings null; LILA carries its cap over LILAK despite 4× the volume. Pull the
vendor's `valuation` rows, take the rows that carry a non-null cap, and that IS the carrier
map.

**Every line of that issuer publishes the issuer's cap, and every non-carrier line says
which row it came from.** `cap_source_symbol` is the carrier's ticker; it equals the row's
own ticker on the carrier row. This is the same contract the international file already
uses, and it is what makes a preferred line's cap correct: every quote service reports the
ISSUER's common-share count on a preferred line, so a per-line cap on a preferred row is
the wrong number, while the issuer's cap is right.

**The consequence must be stated in the artifact: one issuer now appears on more than one
row, so a cap-weighted aggregate MUST deduplicate on `cap_source_symbol` first.** The file
still does not support cap-weighted sector aggregates (the vendor's caps are coarse and
the sector ETFs disagree with them) — the flag makes the double count visible instead of
silent.

- The carrier map is resolved **before** the floor or any cap filter, so a published row
  never points at a `cap_source_symbol` that is not in the file.
- A cap that cannot be resolved is left **empty with `NO_CAP`**. Never zero.
- The `market_cap / close` implied share count must be plausible (order 10³–10¹³) on every
  capped row. That is the guard that catches a cap carried across issuers.

## 5. The currency rule — the `currency` column must do its job

**Every row of the US file is USD.** `market_cap` is USD, `open`/`high`/`low`/`close` are
USD, and the `currency` column says `USD` on every row.

- **Publish `market_cap_usd` explicitly.** It equals `market_cap` on this file, and a
  consumer that re-derives a USD cap must never have to guess.
- **State the conversion direction in `## Method`**: *no FX conversion is applied to this
  file*. The identity to assert downstream is `cap_usd × 1.0 == cap_local`. On the
  international file the identity is `usd_cap × FX_per_USD == market_cap_local` — a
  MULTIPLY against a local-per-USD rate, and the direction that produced cron #05's
  100–200× error on 2026-11-04.
- **The guard that catches that class of bug is cheap**: `market_cap / close` must return a
  plausible share count, and one row must satisfy the identity above. On the US file it is
  a no-op guard. Run it anyway.

## 6. The markdown skeleton (fixed order)

```
# EOD US market snapshot — <session>
## TL;DR
## Coverage
## Market read
## Top movers
## Source health
## Method & caveats
```

- **`## TL;DR` — exactly three bullets**: what the session did (with the counts), the one
  most consequential move, and the caveat that changes how to read the numbers. A fourth
  bullet is a defect.
- **`## Coverage`** — the populated count AND the basis of every column, then the
  per-flag counts of `data_quality`.
- **`## Market read`** — a **table**, never prose: the index proxies with their closes and
  changes, the advance/decline counts, and the sector table (sector, average move, median
  move, names, up, down, the sector ETF and its move). At least six numeric rows.
- **`## Top movers`** — the liquid names (volume ≥ 100,000), gainers and losers, with the
  relative volume and the ATR% so the row carries its own context.
- **`## Method & caveats`** — the column count, the market-cap currency and the conversion
  direction, the carrier rule and the dedupe warning, the `data_quality` vocabulary, every
  derived-column definition, the range rule and the never-zero rule.

## 7. The run-time fetch — the scripts, and the marker that keeps a stale copy out

The derive stage is a **script**, not prose, so the numbers cannot drift between runs:

```bash
# --- fetch the derive-stage scripts (run-time fetch: fixes land with no redeploy) ---
# The CAPABILITY marker is mandatory: an OLDER copy of these scripts is still published
# and it would silently write the 14-column file. The contents API is authoritative and
# is NOT CDN-cached, so it is tried first.
mkdir -p /workspace/eod_scripts
for F in fetch_eod_history.py fetch_eod_vendor_refs.py eod_derive.py build_eod_report.py; do
  S=/workspace/eod_scripts/$F
  for U in \
    "https://api.github.com/repos/karizaco/maxhermes-migration/contents/cloud-prompts/skills/eod-watchlist-snapshot/scripts/$F?ref=main" \
    "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/skills/eod-watchlist-snapshot/scripts/$F" \
    "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/skills/eod-watchlist-snapshot/scripts/$F" ; do
    curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" -o "$S.tmp" "$U" 2>/dev/null
    if [ -s "$S.tmp" ] && grep -q 'EOD_DERIVE_V2' "$S.tmp" 2>/dev/null; then
      mv -f "$S.tmp" "$S"; break
    fi
    rm -f "$S.tmp"
  done
  if [ ! -s "$S" ] || ! grep -q 'EOD_DERIVE_V2' "$S" 2>/dev/null; then
    echo "eod-derive: UNAVAILABLE ($F has no version carrying the EOD_DERIVE_V2 marker)"
    echo "no derived columns; no push"
    exit 1
  fi
done
```

**A missing script is a FAILURE, not a degraded run.** Publishing the old 14-column file
after the fleet has started reading `rel_volume` and `data_quality` is worse than
publishing nothing: the consumer cannot tell which shape it is holding.

Then, in order:

```bash
# 1. the universe + the vendor's carrier rows and public floats (keyset, sequential)
python3 /workspace/eod_scripts/fetch_eod_vendor_refs.py <universe.json> /workspace/work/vendor_refs.json

# 2. ONE history pull per symbol (a year of daily bars serves the session AND the derived columns)
python3 /workspace/eod_scripts/fetch_eod_history.py --symbols <symbols.csv> \
    --out /workspace/work/history.jsonl --session <YYYY-MM-DD> --threads 24

# 3. derive the columns, the flags, the carrier map and the manifest
python3 /workspace/eod_scripts/eod_derive.py --base <base.csv> \
    --history /workspace/work/history.jsonl --vendor /workspace/work/vendor_refs.json \
    --session <YYYY-MM-DD> --out us-eod/<YYYY-MM-DD>.csv --manifest /workspace/work/manifest.json

# 4. build the report FROM the published CSV (never hand-written)
python3 /workspace/eod_scripts/build_eod_report.py --csv us-eod/<YYYY-MM-DD>.csv \
    --manifest /workspace/work/manifest.json --history /workspace/work/history.jsonl \
    --session <YYYY-MM-DD> --out us-eod/<YYYY-MM-DD>.md --source-health <source_health.json>

# 5. the assertions — the artifact is not finished until they pass
python3 tools/check_eod_artifact.py --csv us-eod/<YYYY-MM-DD>.csv --md us-eod/<YYYY-MM-DD>.md
```

**The checker is INDEPENDENT of the builder** — it re-implements the issuer-grouping rule
instead of importing `eod_derive.py`, because a checker that shares code with the thing it
checks cannot catch a bug in that code. It asserts: every required column is present;
`data_quality` is never empty and never off-vocabulary; every `CAP_CARRIED` row names a
row of the SAME issuer; no `HIGH_LOW_UNAVAILABLE` row has a populated high/low; no close
sits outside its own range; no missing value is written as zero; `market_cap_usd` equals
`market_cap`; the implied share count is plausible; the TL;DR has exactly three bullets;
the Market read is a table with ≥ 6 numeric rows; the Coverage table reports both
populated and per-flag counts; and the Method section states the cap currency and the
conversion direction.

## 8. What did NOT change (do not re-litigate these)

- **The universe and the floor.** The ~4,900-row US set with a settlement-stamped close is
  the right shape.
- **A close is never published outside its own range.** Where the daily bar cannot bracket
  it, the vendor's day range is used and the row is flagged `RANGE_ADJUSTED`; where neither
  brackets it, high/low are left empty and the row is flagged `HIGH_LOW_UNAVAILABLE`.
- **A missing value is empty, never zero.**
- **The base session fields are not restated by the derive stage.** It adds columns and the
  carrier rule; it does not change a price, a volume, a P/E, a sector or a name. The only
  base value that changes is `market_cap` on a row that now carries its issuer's cap.

## Steps — International (cron `5edfb4aa…`) — v2 + compute-opt flow

### The summary.md skeleton (fixed order — load-bearing)

The summary's structure is **fixed**. The section list has been stable since 2026-10-30, so the
defect was never the section list — it was what the movers table **contained**: one flat list
that mixed regions, mixed in below-the-cap names, and mixed in names with no catalyst, under a
report with no TL;DR. Follow the order below exactly. Do not add, drop or reorder sections. If a
section has nothing in it, say so in one line — do not delete the heading.

```
# Cron #05 eod-international-daily — <Weekday, DD Month YYYY>
## TL;DR
## Market context
## Top movers
## Below the gate
## No catalyst
## Method, source health & caveats
```

- **Title** — `# Cron #05 eod-international-daily — Wednesday, 04 November 2026`. Weekday spelled
  out; it tells the reader which session this is without a lookup.
- **`## TL;DR`** — **exactly 3 bullets**, each one line:
  1. What global markets did (the shape), with the name count.
  2. **The one most consequential move** — the single name or sector that changed the tape.
  3. **The caveat that changes how to read it** — the one thing that makes the numbers mean
     something other than what they look like.

  A fourth bullet is a defect. **One of the three names the foreign moves that have a US-listed
  line** — a US trader needs to know which of these are reachable.
- **`## Market context`** — three tables, in this order:
  1. **Coverage** — `Region | Venues | Universe | Unique instruments | Written | Floor (USD) |
     Excluded: no cap | Excluded: below floor | Excluded: below volume | Excluded: issuer
     unresolved | Excluded: cap mismatch | Carry-over rows | Off-official rows`, with a totals
     row. The per-reason counts come straight from `_excluded.json`; they are not estimates.
  2. **Index levels** — `Region | Index | Close | Change | Session date | Source`, one row per
     region. The session date is the trading day the close belongs to, not the run's date. Where
     an official close and a third-party quote disagree, the official close is published and the
     delta appears in the cell (venue-official price rule).
  3. **Regional breadth** — `Region | Rows | Median | Up / down / flat | Min | Max`, computed
     from the written rows. An index move and the typical name regularly disagree; publish both.
- **`## Top movers`** — **one table per region**, one row per name, largest absolute move first
  within the region. Every row carries `us_listing`, the cap, and the **catalyst in the row**:
  what was actually sourced, with its source and its date. A name with **no sourced driver** does
  not appear here — it goes to `## No catalyst`. A mover table with a no-catalyst row in it is
  diluting the actionable half of the file.
- **`## Below the gate`** — the names that moved and would have been published **but for the cap
  floor alone**: they clear the volume gate and the move threshold, and their cap is below the
  movers table's floor. Published, because a −24.72% move is not noise. One row per name, with
  its move and its cap, and the reason it is here stated.
- **`## No catalyst`** — the names that moved with **no sourced driver**: no company release, no
  filing, no analyst action, and no sourced sector or macro move behind them. Separate, so they
  do not dilute the mover table. One row per name, with its move and its cap.
- **`## Method, source health & caveats`** — three subsections, in this order:
  1. **Method** — the universe rules, the per-region floors, the FX table with its source and
     its date, the venue-collapse rule, the **cap carrier rule** (primary line,
     `cap_source_symbol`, the cross-venue check) and the **venue-official price rule**. State the
     CSV column count when it differs from the previous session, and list the files written.
  2. **Source health** — one table: `Source | Query / URL | Status | Result`. Mandatory, even
     when every source was healthy.
  3. **Caveats** — every structural caveat that changes how the numbers read, including rows
     whose close is a carry-over from an earlier session.

**Sector rotation** (mean and median `change_pct` per sector over the liquid subset) is not a
section of its own — it goes under `## Method, source health & caveats` as a short paragraph. It
explains the tape better than any index level and it costs nothing, because it uses the same
rows.

### The assertions — run them, do not eyeball them

Four checks, and the artifact is not finished until they pass:

1. **No unaccounted cap.** Every row's `market_cap` either comes from its own line or from a
   `cap_source_symbol` that resolves to the same issuer. Assert it row by row — a carried cap
   with an unresolved issuer is a defect, not a row to publish.
2. **Every excluded row has a reason**, and the Coverage table's per-reason counts equal the
   counts in `_excluded.json`.
3. **The summary's tables and the CSVs agree.** The number of names published in each region's
   mover table, `## Below the gate` and `## No catalyst` tables equals the number the builder
   marked for publication, and every ticker in those tables exists in that region's CSV. Assert
   it — a summary row for a ticker the CSV does not contain is a fabricated row.
4. **Every mover row carries `us_listing`**, and every non-empty `price_conflict` cell parses as
   `official=… source=… third_party=… delta=…`.

`scripts/intl_assert.py` performs all four against a built directory. Run it before the push.

### The machine-readable companions

Three machine-readable files ship beside the CSVs. The cron prompt points at this section for
their contract, so **this section is the source of truth** for them.

**`_manifest.json`** — the per-day facts a consumer reconciles against:

```json
{
  "date": "YYYY-MM-DD",
  "generated_at": "<iso8601 UTC>",
  "provenance": "<one sentence: source, region count, FX provider and rate date>",
  "market_cap_unit": "USD",
  "price_currency": "listing (the `currency` column)",
  "change_pct_unit": "percent",
  "csv_columns": 18,
  "fx_source": { "provider": "<provider>", "updated_utc": "<ts>", "per_usd": { "EUR": 0.0 } },
  "floors_usd": { "<region>": { "floor_usd": 0, "min_volume": null } },
  "regions": {
    "<region>": {
      "universe_rows": 0,
      "unique_instruments": 0,
      "written": 0,
      "excluded": {
        "no_market_cap": 0,
        "below_cap_floor": 0,
        "below_volume": 0,
        "issuer_unresolved": 0,
        "cap_issuer_mismatch": 0,
        "stale_venue_print": 0
      },
      "carryover_rows": 0,
      "off_official_rows": 0,
      "mover_rows": 0,
      "below_gate_rows": 0,
      "no_catalyst_rows": 0,
      "floor_usd": 0,
      "min_volume": null,
      "file": "<region>.csv",
      "venues": ["<exchange>"]
    }
  },
  "totals": { "written": 0, "excluded": 0 }
}
```

- **`excluded` is the PER-REASON count**, and it is the source of the Coverage table's exclusion
  columns — the two must be equal, and `scripts/intl_assert.py` asserts it. The flat
  `excluded_no_market_cap` / `excluded_below_floor` keys are gone: a closed reason set with a
  fixed home per reason cannot grow a sixth reason without another flat key.
- **`mover_rows`, `below_gate_rows` and `no_catalyst_rows`** are the counts the summary
  publishes. The summary's tables must match them exactly, per region.
- **`csv_columns`** states the schema width, so a consumer reading a mixed archive can tell
  which days are 14-column and which are 18-column without guessing from the header.
- **The reconciliation identity holds per region:**
  `unique_instruments == written + sum(excluded.values())`. A region that fails it has lost or
  double-counted rows.

**`_excluded.json`** — one key per region, each a list of the rows that did not make the CSV.
**Every row carries a non-empty `reason` from the closed set above**, plus `ticker`, `name`,
`exchange`, `close` and `volume`. A row with an empty reason is a build defect, not a row to
publish.

**`_carryover.json`** — the instruments that did not trade, with each one's `last_trade_date`.
`last_trade_date` walks BACK through the prior files, never forward.

**Carry-over rows (instruments that did not trade) are disclosed, not hidden.** The screener
returns the last session's close and change for a row that did not trade today, which is true of
the instrument but false as a statement about the day. Keep the rows as the source returned them
(the schema is fixed at 18 columns), list the affected tickers in `_carryover.json` with each
instrument's last trade date, state the count in the report, and exclude them from every movers
list.

**How to DETECT a carry-over (2026-11-04, cron #05) — compare the close EXACTLY, never with a
tolerance.** A row is a carry-over when its close equals the close in the **prior session's file**
AND either the row's volume is zero (no print at all) or the row's `change_pct` is non-zero
(the scanner's `change` field is a stale leftover from an earlier session). Resolve the prior
session's file per region — for a market that was shut the day before, that is the last file it
actually has, not yesterday's date.

  - **Use exact string equality on the stored representation** (compare the value as it is written
    to the CSV). An absolute tolerance is a false-positive generator: with a 0.005 tolerance,
    Bellevue Gold's A$1.31 close was flagged "unchanged" against the prior session's A$1.315 —
    which is a **0.4% real move**, and it is exactly the kind of half-cent print the tolerance was
    supposed to catch. On 2026-11-04 that one rule produced **4 phantom carry-overs in Australia
    alone**; with exact matching the count dropped to the true 89.
  - **The prior session's close is the right anchor**, because a row that did not trade today
    still carries the last session's close. The scanner's own `change_abs` is not a substitute: it
    is relative to the instrument's own previous close, which for a stale row is an even earlier
    session.
  - **`last_trade_date` walks back**, not forward: keep walking the prior files until a row with
    non-zero volume or a different close is found, and report that date. A Spanish name that has
    not printed since 28 October must not be stamped with yesterday's date.

The cron prompt is intentionally short (~1.5KB). All orchestration logic lives in `run_intl_cron.py` with two CLI subcommands:

### `run_intl_cron.py plan` — pure planning, no MCP calls

```
python run_intl_cron.py plan --today YYYY-MM-DD \
  --csv-root "research\historical_eod" \
  --universe-cache-root "research\universe_cache" \
  --enrichment-cache-root "research\enrichment_cache"
```

Returns a JSON plan with:
- `skip_regions` — holiday/weekend hits (no MCP, no CSV write)
- `screener_refresh` — regions whose universe cache is stale (>7 days)
- `stock_prices` — `{region: [tickers...]}` for regions to refresh
- `yahoo_batches` — `[[(tv, yt), ...]]` of ≤10 pairs each
- `movers_regions` — Tue-Thu default; forward-fill non-movers from yesterday
- `audit` — call counts (skip_count, screener_refresh_count, stock_prices_regions, yahoo_batch_count, yahoo_call_count)

### `run_intl_cron.py finalize` — assembles CSVs from MCP responses

```
python run_intl_cron.py finalize --today YYYY-MM-DD \
  --csv-root "research\historical_eod" \
  --universe-cache-root "research\universe_cache" \
  --enrichment-cache-root "research\enrichment_cache" \
  --responses <path-to-mcp-responses.json> \
  --audit-log "research\logs\audit.log"
```

Reads MCP responses, writes per-region CSVs, refreshes the enrichment cache for next time, appends audit lines, runs regression detection against the 7-day median row count per region.

### Cache layer

Three cache files, all under `research\`:

- **`universe_cache\<region>\tickers.json`** — ticker universe per region, TTL=7 days. Refreshed by `pull_international.py` running the screener; consumed by `stock_prices` daily.
- **`enrichment_cache\cache.json`** — per-ticker `{volume, pe_ratio, sector}` with field-level TTLs (default 1d/30d/30d). Refreshed by `finalize` after Yahoo calls; consulted by `plan` to decide what to enrich.
- **`holiday_calendar`** — in-process per-exchange holidays for 2025-27 (`holiday_calendar.py`). 16 regions × 3 years, used by `plan` to skip non-trading days. **It is a hint, not a fact** — see the calendar guard above; `scripts/market_session_probe.py` is what decides.

## Holiday calendars are a HINT — verify the session before skipping a region (international run)

This section applies to the **international** run (cron #05), the only one that skips regions.
`holiday_calendar.py` is a hand-maintained table of 16 exchanges x 3 years, and it **has been
wrong in a way that deleted a real trading session**: Greece's Ochi Day was listed as 2026-10-27
instead of 10-28, and the ATHEX was open and traded on 10-27 (Yahoo daily bars for ALPHA.AT,
EUROB.AT, TPEIR.AT, GEKTERNA.AT, MOH.AT and ETE.AT all carry a 10-27 session). Six dates in the
Greek list were wrong, all of the same class of error — a mis-derived Orthodox date or a shifted
national holiday. The Greece list was corrected on 2026-11-03 against Euronext Athens' own
holiday table, but **the same class of error can exist in any of the sixteen tables, and none of
them is machine-verified.**

**So never skip a region on the calendar alone.** `scripts/market_session_probe.py` answers the
question the calendar only guesses at — *did this market actually trade on this date?* — from
the exchange's own session bars:

```bash
python3 market_session_probe.py --region eu-gr --date 2026-10-27
# VERDICT region=eu-gr date=2026-10-27 traded=yes source=ALPHA.AT last_bar=2026-10-27
```

The rules:

- **`traded=yes` → INCLUDE the region.** The market traded. A calendar that says otherwise is
  wrong: include the region, and report the calendar error in the artifact's `## Caveats` and in
  the reply. This is exactly the 2026-10-27 Greece case.
- **`traded=no` → the market did not trade.** Skip it, and say so in `## Source health`.
- **`traded=unknown` → you do not know.** A source that could not be reached, a date outside the
  fetched window, or a date after the last session. **Unknown is never a licence to skip.** Treat
  it as a trading day, write the region, and note the uncertainty. Only a confirmed `no` may
  remove a region from the artifact.
- Run the probe for **every** region the calendar would skip, not just the ones that look
  doubtful. A skip is a deletion from the historical record and it needs a positive
  confirmation.

The probe covers the 16 regions of this skill. There is no Yahoo index symbol for the ATHEX, so
Greece probes a liquid ATHEX constituent (`ALPHA.AT`) instead. Use `--audit --from … --to …` to
sweep a whole date range across every region at once.

## Compute optimization summary

| Lever | Mechanism | Cost impact |
|---|---|---|
| **Universe cache** | stock_screener runs only when stale (>7d) | 16/day → ~2/day average |
| **Holiday skip** | `plan` returns `skip_regions`; cron does nothing | ~10 wasted runs/year → 0 |
| **Movers default (Tue-Thu)** | forward-fill non-movers from yesterday's CSV | stock_prices 16 → 4/day Tue-Thu (75% off) |
| **Enrichment cache (foundation)** | per-ticker TTL on volume/pe/sector | Yahoo 800/day unchanged with default TTLs; see "Cache TTL tuning" |
| **Drop shibui cross-listed** | removed from default flow | 30 shibui/day → 0 (was opt #7) |
| **Shorter cron prompt** | orchestration in helper script | agent runtime ~60% off; 4KB → 1.5KB prompt |

## Cache TTL tuning

The enrichment cache is in place but its default TTLs don't actually reduce Yahoo call volume:

- `volume` TTL = 1 day → "stale" every cron run → refresh every day for top-N
- `pe_ratio` TTL = 30 days → refresh once per month
- `sector` TTL = 30 days → refresh once per month

Yahoo's `compare_stocks` returns ALL 3 fields per call. So a ticker with `volume` stale triggers a full refresh, even if `pe` and `sector` are still fresh. With default TTLs, the cache effectively gates only the 1-in-30 day where `pe`/`sector` alone need refresh — saving ~3% of calls, not 80%.

**To actually cut Yahoo calls, raise `volume` TTL** by passing `--volume-ttl-days 5` (or higher) to the helper. At TTL=5 days, only every 5th cron run refreshes volume; the other 4 days return cached data. Trade-off: volume in the daily CSV is up to 4 days stale for non-mover tickers. For backtest/append-only use this is fine; for live screening use yesterday's CSV.

```
# Conservative (default — no real Yahoo savings)
python run_intl_cron.py plan --volume-ttl-days 1 ...

# Aggressive (80% Yahoo reduction, 4-day-stale volume for non-movers)
python run_intl_cron.py plan --volume-ttl-days 5 ...
```

The orchestrator already pairs this with movers-mode default Mon-Thu — movers always get fresh volume regardless of TTL.

## Parallelization

| Stage | Calls | Recommended batch size | Notes |
|---|---|---|---|
| `stock_screener` (cache refresh) | ≤16/week per region | 5 | Independent per region |
| `stock_prices` (daily refresh) | 16 (or 4 in movers mode) | 4 | One per region, batches if >2000 |
| `compare_stocks` (Yahoo) | depends on cache hit rate | 6 | ≤10 pairs per batch |
| `stock_data_query` (shibui cross-listed) | 0 by default (opt-in) | n/a | Was opt #7 |

All four stages can run in parallel — the only dependency is that Yahoo enrichment needs the `stock_prices` output to know which tickers to translate.

## Hard rules

- **Never use `research/watchlist.yaml` as the universe** — that's personal trade tracking.
- Never overwrite an existing day's file.
- Never include position data, P&L, or anything account-specific — pure market data only.
- If a data source fails for a ticker, write the row with empty numeric fields (do NOT write `"N/A"`).
- Do not invent values for missing fields.
- `market_cap` is USD and the prices are in the listing currency — see the units contract above.
  Do not change either without restating the affected sessions.
- Every cron fallback branch must **accept the partial result, write the artifact, and stop** — never chain deeper MCP calls.

## Out of scope

- Pre-market data (use pre-market brief skill for that).
- Per-second intraday ticks — daily OHLCV only.
- Multi-day history — shibui-finance owns that; this skill just appends today's row.

## Known limitations

- **Cross-listed tickers** (CA:RY, JP:8306, TW:2330, AU:BHP, DE:SAP) appear in both US and intl CSVs with potentially different `change_pct` (different close times). No dedupe yet. (Pending improvement.)
- **CSVs are uncompressed** — ~14MB/day × 250 trading days = ~3.5GB/year. (Pending improvement: gzip.)
- **Top-N coverage gap** — non-top-500 tickers have blank volume/pe/sector. Raising top-N to 1500 cuts schema coverage from ~5% to ~15% of rows but triples Yahoo call cost. (Pending: enable once volume TTL is raised.)
