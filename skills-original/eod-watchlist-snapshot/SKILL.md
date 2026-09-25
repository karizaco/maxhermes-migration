---
name: EOD market snapshot (CSV, full universe)
description: >-
  Save a daily CSV of OHLCV + change% + market cap for the entire US-listed
  universe and 16 international markets (AU, JP, TW, CA, EU-DE/FR/IT/ES/NL/BE/AT/PT/IE/FI/DK/GR),
  after the US close. Feeds shibui-finance for ad-hoc historical queries and
  gives you a backtest-friendly archive. Two crons: US 16:30 ET (shibui SQL),
  international 16:35 ET (TradingView stock_prices + Yahoo + helper).
---

> **Policy change 2026-09-22** — the watchlist is no longer the universe.
> This skill now pulls the full US + international universe. The 12-name
> `research/watchlist.yaml` is reserved for personal trade tracking and is
> NOT used as a market-data universe anywhere in this workflow.

> **Compute-optimization pass 2026-09-22** — three compute levers added
> (enrichment cache, holiday skip, movers-default Tue-Fri). Yahoo call cost
> remains ~800/day with default cache TTLs; raising `volume` TTL to 5+ days
> cuts Yahoo calls by ~80% (see "Cache TTL tuning" below).

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

## Steps — US universe (cron `0a87adbe…`)

1. Paginate `mcp__shibui-finance__stock_data_query` 25 times: `LIMIT 200 OFFSET 0, 200, …, 4800`, filter `country_iso='US'`, join `stock_quotes` for OHLCV on the target date, join `valuation` (market_cap) and `fundamentals_derived_daily` (trailing_pe).
2. Run `C:\Users\admin\AppData\Local\Temp\assemble_eod_csv.py` (or equivalent) to read all 24 externalized artifacts + 1 inline batch, dedupe by first-prefix, parse JSON, write CSV.
3. Append audit: `eod_snapshot target=historical_eod:YYYY-MM-DD rows=4935 source=shibui_sql_universe_corrected_overwrite`.

**Why shibui, not TradingView, for US?** The international TradingView screener response strips `volume` / `pe_ratio` / `sector`. The shibui JOIN schema (`stock_quotes` + `valuation` + `fundamentals_derived_daily`) gives the full CSV row in one query. Swapping US to TradingView would lose three columns.

## Steps — International (cron `5edfb4aa…`) — v2 + compute-opt flow

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
- If a data source fails for a ticker, write the row with empty numeric fields (do NOT write `"N/A"`).
- Do not invent values for missing fields.
- Every cron fallback branch must **accept the partial result, write the artifact, and stop** — never chain deeper MCP calls.

## Out of scope

- Pre-market data (use pre-market brief skill for that).
- Per-second intraday ticks — daily OHLCV only.
- Multi-day history — shibui-finance owns that; this skill just appends today's row.

## Known limitations

- **Cross-listed tickers** (CA:RY, JP:8306, TW:2330, AU:BHP, DE:SAP) appear in both US and intl CSVs with potentially different `change_pct` (different close times). No dedupe yet. (Pending improvement.)
- **CSVs are uncompressed** — ~14MB/day × 250 trading days = ~3.5GB/year. (Pending improvement: gzip.)
- **Top-N coverage gap** — non-top-500 tickers have blank volume/pe/sector. Raising top-N to 1500 cuts schema coverage from ~5% to ~15% of rows but triples Yahoo call cost. (Pending: enable once volume TTL is raised.)
