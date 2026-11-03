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
date,ticker,name,open,high,low,close,volume,change_pct,market_cap,pe_ratio,sector,currency,exchange
```

Numeric columns formatted to 4 sig figs; empty cell if data missing (don't write `"N/A"`).

For non-top-N tickers, `volume` / `pe_ratio` / `sector` may be blank (TradingView screener strips them). The enrichment cache fills them in for the top-N per region (default 500).

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
- **Never change the unit of this column silently.** If a run writes it differently from the
  previous session, say so in the artifact and in `## Source health`, and restate the earlier
  session. A series that switches unit mid-stream reads as a market event that never happened.
- **Check any change to this contract with a share-count reconciliation**, not with a length or a
  spot check: `market_cap_basic / close` must land on the issuer's real share count.

## Steps — US universe (cron `0a87adbe…`)

1. Paginate `mcp__shibui-finance__stock_data_query` 25 times: `LIMIT 200 OFFSET 0, 200, …, 4800`, filter `country_iso='US'`, join `stock_quotes` for OHLCV on the target date, join `valuation` (market_cap) and `fundamentals_derived_daily` (trailing_pe).
2. Run `C:\Users\admin\AppData\Local\Temp\assemble_eod_csv.py` (or equivalent) to read all 24 externalized artifacts + 1 inline batch, dedupe by first-prefix, parse JSON, write CSV.
3. Append audit: `eod_snapshot target=historical_eod:YYYY-MM-DD rows=4935 source=shibui_sql_universe_corrected_overwrite`.

**Why shibui, not TradingView, for US?** The international TradingView screener response strips `volume` / `pe_ratio` / `sector`. The shibui JOIN schema (`stock_quotes` + `valuation` + `fundamentals_derived_daily`) gives the full CSV row in one query. Swapping US to TradingView would lose three columns.

## Steps — International (cron `5edfb4aa…`) — v2 + compute-opt flow

### The tables an international artifact must carry

Beyond the CSVs, the international artifact ships a `summary.md` whose structure is specified in
the cron prompt. Three of its tables are computed from the written rows and are the ones that
make the file readable:

- **Coverage** — `Region | Venues | Universe | Unique instruments | Written | Floor (USD) |
  No cap | Off-official rows`. `Universe` is everything the source returns for that country;
  `Unique instruments` collapses multi-venue listings of one instrument to a single row;
  `Written` is what survives the floor. Totals row included.
- **Regional breadth** — `Region | Rows | Median | Up / down / flat | Min | Max`, computed from
  the written rows. An index move and the typical name regularly disagree; publish both.
- **Sector rotation** — mean and median `change_pct` per sector over the liquid subset. It
  explains the tape better than any index level, and it is cheap because it uses the same rows.
- **Top movers** — largest absolute moves among liquid names, with a `Catalyst` cell that says
  what was actually sourced, or "no company-specific release found". Never an unattributed guess.

**Carry-over rows (instruments that did not trade) are disclosed, not hidden.** The screener
returns the last session's close and change for a row that did not trade today, which is true of
the instrument but false as a statement about the day. Keep the rows as the source returned them
(the schema is fixed at 14 columns), list the affected tickers in `_carryover.json` with each
instrument's last trade date, state the count in the report, and exclude them from every movers
list.


### The machine-readable companions

`summary.md` is for a human. Three files beside it make the session queryable by
code, and the archive is not comparable across days without them.

**`_manifest.json` — required.** The CSVs alone cannot tell a consumer the
universe size, the floor that was applied, the unit of `market_cap`, or how many
rows did not trade. Those change between sessions, so they must be recorded
per session:

```json
{
  "date": "2026-11-03",
  "generated_at": "<ISO-8601 UTC>",
  "market_cap_unit": "USD",
  "price_currency": "listing (the `currency` column)",
  "fx": {"table": {"EUR": 1.1178, "JPY": 0.006348}, "source": "<url + date>"},
  "floors_usd": {"au": {"floor_usd": 300000000, "min_volume": 100000}},
  "regions": {
    "au": {"universe_rows": 1552, "unique_instruments": 1552, "written": 302,
           "excluded_no_market_cap": 4, "excluded_below_floor": 1246,
           "carryover_rows": 0, "off_official_rows": 0, "file": "au.csv"}
  },
  "totals": {"universe_rows": 0, "unique_instruments": 0, "written": 0,
             "excluded_no_market_cap": 0, "excluded_below_floor": 0,
             "carryover_rows": 0},
  "invariants": {"unique_instruments == written + excluded_no_market_cap + excluded_below_floor": true}
}
```

The invariant is the point of the file: **every unique instrument lands in
exactly one bucket** — written, excluded for a missing cap, or excluded by the
floor. If the three numbers do not reconcile, one of them is wrong; say so in
the report rather than publishing a manifest that does not add up. If a field
cannot be computed, **omit it — never guess it**.

**`_excluded.json` — the rows with no reported market cap.** The units contract
above excludes them from the CSV, because a row that cannot be screened against
a floor has no place in a screened file. Excluding is not deleting: list them
here with their fields, so the exclusion is recoverable without re-pulling the
universe.

```json
{"date": "2026-11-03",
 "regions": {"au": {"ASX:XXX": {"reason": "no_market_cap_reported",
                                "name": "...", "close": "1.23",
                                "volume": "5000", "change_pct": "0",
                                "currency": "AUD"}}}}
```

**How to build `_carryover.json`.** The requirement is stated above; the method
is what makes it repeatable.

1. Build a Yahoo symbol per row from the venue (`.AX`, `.T`, `.TO`, `.DE`,
   `.PA`, `.AS`, `.BR`, `.LS`, `.HE`, `.CO`, `.MC`, `.MI`, `.AT`; replace `_`
   with `-`). Skip class-suffixed symbols (`.PR`, `.P`) — no reliable mapping.
2. Fetch `v7/finance/spark` in batches of **12** (the URL-length limit) and read
   `meta.regularMarketTime`, converting with `meta.gmtoffset` — **Yahoo's own
   offset, never a hand-rolled exchange offset**.
3. `local_date != <DATE>` → the instrument had no session on the date.
4. `confirmed: true` when the screener's `volume` equals Yahoo's
   `meta.regularMarketVolume` for that last session — both feeds are carrying
   the same earlier session. When it is false the screener shows a non-zero
   volume but Yahoo has no bar for today: usually still a carry-over, sometimes
   a Yahoo coverage gap.

**Traps.** Yahoo appends a duplicate live bar for ASX and stamps ASX daily bars
at the session *open* in UTC — group bars by local session date, never by bar
index. Compare `change_pct` against Yahoo's `regularMarketChangePercent`; do
**not** reconstruct a prior close and compare that, because dividend and split
adjustments change the reference basis. The stale `change_pct` is **not** edited
in the CSV — it is the instrument's last session move, not a fabrication — but it
must be indexed, counted in the manifest, and called out in `## Caveats`.

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
- **`holiday_calendar`** — in-process per-exchange holidays for 2025-27 (`holiday_calendar.py`). 16 regions × 3 years, used by `plan` to skip non-trading days.

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
- If a data source fails for a ticker, write the row with empty numeric fields (do NOT write `"N/A"`). **Exception — the international artifact:** a row the source reports no market cap for is excluded rather than written blank (see the units contract above), and is listed in `_excluded.json` so the exclusion stays recoverable.
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
- **The 2026-10-26 international artifact was restated on 2026-11-03** into the house convention (USD `market_cap`, per-region USD floor applied after conversion, no-cap rows excluded, `summary.md` replacing `<date>.meta.md`). The original is preserved in git history at commit `9291938`. That restatement also corrected an inverted CAD rate in the original run's FX table, which had overstated every Canadian market cap by ~1.97x; the published CSVs carried listing-currency caps and were never affected, but the run's Canadian liquidity filter was too loose.
- **Top-N coverage gap** — non-top-500 tickers have blank volume/pe/sector. Raising top-N to 1500 cuts schema coverage from ~5% to ~15% of rows but triples Yahoo call cost. (Pending: enable once volume TTL is raised.)
