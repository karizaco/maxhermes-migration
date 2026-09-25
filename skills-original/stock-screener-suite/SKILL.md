---
name: stock-screener-suite
description: |
  Run the daily multi-stylist stock screening sweep that mirrors the published processes of
  Pradeep Bonde (Stockbee), Kristjan Kullamägi (Qullamaggie), Jeff Sun (CFTe), Ariel
  Hernandez (Real Simple Ariel), and Alec Riffle (peoplewish). Use when the user asks for
  today's screener output, the focus watchlist, the breadth/regime snapshot, the 3:55 PM
  reversal-bullish list, the parabolic short/long candidates, the pre-market gapper list,
  the IPO or high-short-float weekly refresh, or any "what should I be watching today"
  variant. Output is per-stylist Markdown + a tiered (Master/Stalk/Focus) merged list
  written to the local research vault. Triggers include: "screener", "screen", "stock
  scan", "focus list", "stalk list", "watchlist", "premarket", "pre-market", "reversal
  bullish", "parabolic short", "ADR scan", "RS scan", "EP scan", "Stockbee", "Qullamaggie",
  "peoplewish", "Real Simple Ariel", "Jeff Sun", "VCP", "compression", "setup journal",
  "trade journal". Do NOT use for options-chain analysis, single-ticker deep TA,
  crypto-specific scans, or executing trades.
---

# Stock Screener Suite

Daily multi-stylist screening pipeline. Five stock-screening veterans each get their own
lens, then results merge into a tiered watchlist. Built around MCP-call efficiency — every
TradingView / shibui / Yahoo call is batched and the daily result is cached in the local
vault.

## Procedure

### 0. Resolve the run parameters (cheap, no MCP)

- Today's date (US/Eastern). If Saturday/Sunday, jump straight to weekly refresh.
- Account size from `$env:ACCOUNT_SIZE_USD` (fallback: `50000`). Used for peoplewish's
  account-relative $vol floor.
- Check vault for today's cache file
  `C:/Users/admin/<user>/research/markets/daily-screens/<YYYY-MM-DD>/_summary.md`.
  If present and `force=False`, short-circuit: load the cached CSV and report. Otherwise
  create the lock file.
- **Run `scripts/screen.py plan <cron_date> --resolve-latest --out <scratch>/plan.json`**
  (T+1-safe flow — see 0.5). This makes the daily sweep self-heal when shibui's data
  ingestion lags the cron fire time. See "⚠ shibui is T+1 — daily sweep" below.

### 0.5. Resolve the latest available date (T+1 handling — daily sweep only)

**⚠ shibui is T+1 — daily sweep.** At 18:30 ET on the cron day, today's close is usually
NOT yet ingested into shibui. The old `plan <date>` flow hardcoded `<cron_date>` into every
sweep SQL, so a late ingestion produced all-zero skeleton files that looked like a quiet
day. The new `--resolve-latest` flag fixes this:

1. Run `python scripts/screen.py plan <cron_date> --resolve-latest --out plan.json`.
   The plan now has **5 batches** (was 4): a new preflight batch
   `preflight_resolve_date` at position 0 plus the original 4 sweep batches.
   Every sweep SQL has `__RESOLVED_DATE__` as a placeholder where the date goes.
   The plan's `cron_date` field is set to the original cron_date; the Agent must
   pass that to `consume --date` so outputs land in `daily-screens/<cron_date>/`
   regardless of which data date the SQL actually targeted.
2. Run the **preflight batch FIRST**. It is a single shibui SQL:
   `SELECT MAX(date) FROM shibui.stock_quotes WHERE date <= '<cron_date>'`
   Extract the `latest_date` value from the response.
3. **String-substitute** the placeholder: read `plan.json`, replace every occurrence
   of `__RESOLVED_DATE__` with `latest_date`, write the substituted plan back.
   Use a simple JSON round-trip (e.g. `json.loads` → str.replace → `json.dumps`)
   to preserve structure. Do NOT touch the literal `cron_date` field — only the
   `query` strings inside the shibui call args.
4. Run the remaining 4 batches in parallel (prefilter is sequential-after-preflight;
   sweep_sql / tradingview_screens / breadth can fan out together).
5. **Pass `--date <cron_date>` (NOT `latest_date`) to `consume`** so the output files
   land in `daily-screens/<cron_date>/` — that is the directory the rest of the
   workflow (pre-market brief, weekly recap) looks at.

If `latest_date == cron_date`: tag rows `_source=mcp`.
If `latest_date < cron_date` (T+1 — the normal case on cron day itself): note the lag
in `_summary.md` ("shibui T+1: this sweep is for `<latest_date>`, cron fired
`<cron_date>`") and proceed. The signal is still valid for next-day execution.

**Backwards compat:** old `plan <date>` (no `--resolve-latest`) still works and emits
the original 4-batch plan with literal `<date>` in every SQL. Existing crons that
haven't been updated keep their old behavior. The reversal-bullish cron (`f6fce3d1`)
already does manual T+1 resolution inline — it does NOT use `--resolve-latest` and
should not be changed.

### 1. Pre-filter universe with **one** shibui-finance SQL call

Run `scripts/screen.py prefilter --out <scratch>/prefilter.csv` which executes **one**
SQL against shibui-finance that returns the universe matching the union of:

- `close > 3` (Bonde floor)
- `market_cap > 300_000_000` (Kullamägi floor)
- `avg_volume_30d > 100_000` (Bonde)
- Trading on NYSE / NASDAQ / AMEX (Finviz-equivalent exchange filter)

This cuts ~9,500 tickers to a few thousand in a single MCP call. The screen recipes in
`references/filters.md` all assume this pre-filtered universe.

### 2. Run the 10 sub-screens in **two parallel batches**

Run `scripts/screen.py sweep --date <YYYY-MM-DD>` which executes:

**Batch 1 (slow, run in parallel):**
- shibui SQL for Bonde 4% breakout, EP9M, Anticipation (coil), Kullamägi 1M/3M/6M
  leaders, Qullamàgi EP, Kullamägi 5-day gainers (parabolic short), Kullamägi
  5-day losers (parabolic long), peoplewish ADR+velocity, Sun compression.
- All in **one** `mcp__shibui-finance__stock_data_query` call using `UNION ALL`.

**Batch 2 (parallel):**
- One `mcp__tradingview__screen_stocks` call with the **Jeff Sun CANSLIM-calibrated**
  filter set (his highest-trafficked screener).
- One `mcp__tradingview__screen_etf` (base namespace) call for sector/industry-group RS over
  1M/3M/6M (Hernandez "theme → group" funnel). Note: ETF screener lives in base
  `tradingview__`, NOT in `tradingview-advanced__` — the latter has no ETF tool.
- One `mcp__tradingview-advanced__volume_breakout_scanner` for KSE-style "momentum
  + volume" cross-check on the USA list.

### 3. Compute breadth / regime snapshot (one shibui SQL + one TV call)

`scripts/breadth.py --date <YYYY-MM-DD>` returns:

- `% S&P 500 above 20-DMA` (shibui SQL — one query for all 500 names)
- ATR% extension from 50-MA on `SPY / RSP / QQQ / QQQE / IWM` (shibui SQL — five rows)
- VIX / VXVCLS ratio (one `tradingview-advanced yahoo_price` call)
- Sector rotation (one `financekit sector_rotation` call)

Output: `daily-screens/breadth/<YYYY-MM-DD>.md` plus a `regime.json`:
```json
{
  "size_cut_pct": 50,     // when (index < 20-DMA) AND (breadth_pct < 40)
  "uncertainty": false,   // when vix_vxv_ratio > 1
  "late_cycle": false     // when any of the 5 index symbols is > 6× historical ATR extension
}
```

### 4. Tier and merge (in-memory, zero MCP)

`scripts/screen.py tier --date <YYYY-MM-DD>` produces:

- `daily-screens/<date>/stockbee.md`           — Bonde per-stylist CSV + Markdown
- `daily-screens/<date>/qullamaggie.md`
- `daily-screens/<date>/jeff-sun.md`
- `daily-screens/<date>/ariel-hernandez.md`
- `daily-screens/<date>/peoplewish.md`
- `daily-screens/<date>/short-candidates.md`   — Kullamägi parabolic short
- `daily-screens/<date>/long-reversal-candidates.md`
- `daily-screens/<date>/ipo.md`               — Sun weekly refresh (run Sundays only)
- `daily-screens/<date>/high-short-float.md`   — Sun weekly refresh (Sundays only)
- `daily-screens/<date>/master.md`            — deduped union (≤ 200 tickers)
- `daily-screens/<date>/stalk.md`             — Master ∩ (price within 2% of 10/20-DMA)
- `daily-screens/<date>/focus.md`             — Master ∩ (≥3 stylist flags OR top-5 velocity)
- `daily-screens/<date>/tier-a.md`            — Master ∩ (≥4 stylist flags), with regime flag
- `daily-screens/<date>/_summary.md`          — human-readable digest
- `daily-screens/<date>/_regime.json`         — breadth/regime payload

### 5. 3:55 PM ET Reversal Bullish (Bonde)

Only run on weekdays between 15:30 and 16:00 ET. Output: `daily-screens/<cron_date>/reversal-bullish-3:55.{md,csv}` with the candidates that pass **all** of Pradeep Bonde's published criteria.

**Pradeep Bonde / Stockbee criteria** (verbatim, from stockbee.blogspot.com + Bonde's Playbook + BreakoutsHappen summary):

| # | Criterion | SQL form |
|---|---|---|
| 1 | **5-day low** — "stock making 5 day low" | `low <= MIN(low, last 5 rows)` |
| 2 | **Close in top half of day range** — "closing in top half of range" | `DCR = (close - low) / (high - low) >= 0.5` |
| 3 | **Tail 3-5x body** — "tail is 3 to 5 times the body" | `(LEAST(open, close) - low) >= 3 * ABS(close - open)` |
| 4 | **Small body** — "small body, narrow, pushed toward the top of the range" | `ABS(close - open) / (high - low) <= 0.4` |
| 5 | **Prior decline (2-3 days)** — "drop should last at least 2-3 days" | `close < close_2d_ago` |
| 6 | **ADR ≥ 3%** — exclude slow movers (counter-example: SMFG at 1.33% ADR was rejected) | `AVG((high-low)/close, 20 rows) >= 0.03` |
| 7 | **Close ≥ $15** — Bonde: "Prefer higher priced stocks" | `close >= 15.0` |
| 8 | **Long-term trend** — exhaustion at support, NOT long-term downtrend | `close >= close_20d_ago * 0.92` |
| U | **Universe** — NYSE/NASDAQ/AMEX, market_cap > $5B (proxy for institutional ownership ≥ 1,000 funds; shibui does not expose `institutional_holders_count`) | |

**Universe** is the **single biggest filter** for Bonde's RB scan. Per Bonde:
> "The universe we need is the set of stocks owned by at least 1,000 institutional funds."

shibui does not have `institutional_holders_count`. Two proxies:
- `market_cap > 5_000_000_000` (5B USD floor — used as default)
- `mcp__tradingview__screen_stocks` filter `institutional_holders_count >= 1000` (more accurate but adds an MCP call; only use when validating a short list, not as the primary universe gate)

**Bonde's output discipline** (do NOT skip these):
- "Select 1 to 3 ideas" — the SQL returns up to 10 names; the discretionary review narrows to 1-3. Do not pad with marginal setups.
- "Prefer higher priced stocks" — already in the price filter.
- "Run the Stockbee Reversal Bullish Scan between 3.30 to 3.55 PM" — cron at 15:55 ET is right at the end of Bonde's window.
- "Enter between 3.58 to 4PM or using Market On Close order (MOC)" — the cron is a screener, not an executor; entry is the trader's job.
- "Put stop of less than 2%" — Bonde places stop at the **low of the candle body** next morning, sized so loss ≤ 2.5%. The report's `body_low_stop` column is the body-low (when `open == close` it equals `close`).
- "Exit on stop hit if it does not work on 3rd day" — typical hold 1-3-5 days; report a "Day 1 / Day 2 / Day 3+" tag so the trader knows how stale the signal is.

**⚠ shibui is T+1** — at 15:55 ET on the cron day, today's close is usually
not yet ingested. The SQL must therefore be run against the LATEST available
date in shibui (`< MAX(date) WHERE date <= today`), not literally today.

- Resolve latest date first via `scripts/screen.py emit-sql resolve_date <date>`
  and substitute `latest_date` into the reversal-bullish SQL.
- The default `emit_reversal_bullish_sql(<date>)` SQL has **three known bugs**
  that surface on T+1 days:
  1. The CTE filters `WHERE q.date = '<date>'` BEFORE the LAG window — the
     window then has only one row per symbol, so `LAG(close, 2)` returns NULL
     for everyone and the 2-day-decline filter drops the entire result set.
  2. The SQL hard-codes `<date>` instead of using `MAX(date) <= <date>`, so
     on the cron-day itself (when shibui has not yet ingested today), the
     CTE is empty regardless.
  3. The SQL has no Bonde-quality filters (5-day low, tail:body ≥ 3, ADR,
     price, trend). It returns 10 names that mostly fail Bonde's published
     criteria — see "Common rejections" below.
- For the cron at 15:55 ET, the Agent MUST run the **T+1-safe + Bonde-strict
  SQL**: window the inner CTE over `date BETWEEN '<cron_date-10d>' AND
  '<latest_date>'`, pick `rn=1` (latest row per symbol) in the outer WHERE,
  AND apply all 8 Bonde filters. See the cron prompt for the canonical form.

**Common rejections** — these all showed up in the loose scan on Sep 21 2026
and were rejected by Bonde's stricter criteria. Keep this list as a debugging
reference when the scan produces fewer than 5 names:

| Symptom | Reject criterion | Example (Sep 21 2026 loose scan) |
|---|---|---|
| Slow mover (ADR < 3%) | filter 6 | `SMFG` (1.33% ADR) |
| Long-term downtrend | filter 8 | `XPEV`, `TFII`, `ERIC` |
| Choppy / mid-range close | filter 2 (DCR < 0.5) | `INTU`, `JBHT` (closed near lows) |
| Random chop, no pullback pattern | filter 1 (no 5-day low) | `WPP` |
| Day 2+ setup (already past entry window) | n/a — review timing tag | `EXE`, `EQT`, `STE` (Bonde's "first day of swing" rule) |

**Finviz fallback** — when shibui fails or times out:
- `screen.py finviz-url reversal_bullish` returns a URL with `ta_change_d, ta_sma50_pa, sh_avgvol_o1000k, cap_largeover` (today down + above SMA50 + liquid + large-cap). It does NOT encode Bonde's 5-day-low / tail-body / DCR filters.
- Accept rows as-is with `_source=finviz_fallback`, write the artifact, and **skip chat alerts** (per the cron prompt's "no chat on Finviz fallback" rule). The user reviews the markdown manually.

### 6. Pre-market Gapper (Sun + Bonde)

Run at 09:00 ET weekdays only. For each ticker in `focus.md`:

- One `mcp__tradingview-advanced__stock_extended_hours(ticker)` call **per ticker**
  — cap at the 12 names in the Focus list, so this is ≤ 12 calls
- Flag names with `gap_pct > 4` AND `pre_market_volume > 50_000`
- One chat line per flagged name

### 7. Live intraday RVOL re-rank (Sun)

Weekdays at 09:45, 10:15, 10:45, 11:15 ET. For each Focus ticker:

- One `mcp__tradingview-advanced__coin_analysis(symbol, exchange=NASDAQ, timeframe=15)`
  call. Returns RVOL + indicators.
- Sort Focus list by intraday RVOL desc.
- Output `focus-rvol-snapshot.md` and split into **RVOL Required** vs **Liquid** buckets
  (Sun's published tier split).
- If any ticker's RVOL crosses from < 1 to > 3, emit one chat alert.

### 8. Hook into existing briefs

- 07:37 ET pre-market brief: prepend yesterday's `tier-a.md` + `regime.json`.
- Sunday 17:47 ET weekly brief: add sections for `ipo.md`, `high-short-float.md`,
  the theme-of-the-week (top-3 sector ETFs × tickers that appeared in daily Focus),
  the peoplewish 1000%-in-10-years backlog enrichment (run the `pattern-study` script).

## Data sources — what actually lives where

The five financial MCPs we use are registered in `~/.minimax/mcp.json`. **None are local files.** Before assuming any architecture, read the config:

| MCP | Transport | Where it lives |
|---|---|---|
| `tradingview` | stdio (npx) | Local npx subprocess — Unofficial TradingView screener |
| `tradingview-advanced` | stdio (uv) | Local uv subprocess — 30+ tools |
| `yahoo-finance` | stdio (npx) | Local npx subprocess — Yahoo API wrapper |
| `financekit` | stdio (uvx) | Local uvx subprocess — indicators, sector rotation |
| **`shibui-finance`** | **streamable-http** | **Remote: `https://mcp.shibui.finance/mcp`. DuckDB on their server, 9,900+ US equities, 31M+ daily bars, 56 indicators.** |

**The shibui-finance call we make most:** `mcp__shibui-finance__stock_data_query` — submits a DuckDB SQL string, gets JSON rows back. The 64-year dataset lives on their server, not ours.

**Practical limits discovered in test runs:**
- Data is end-of-day, T+1 day. Today's bar appears next morning.
- 200-row LIMIT per query (server-enforced).
- No `ipo_date`, no `short_interest_pct_float`, no `institutional_holders_count` columns. Fall back to Finviz for those.
- No SPX-constituents table. Use large-cap (mcap > $10B) proxy for breadth.

For full schema + SQL rules, see `references/filters.md`.

## MCP-call budget per run

| Stage | Primary MCP calls | Batched? | Tier-2 fallback |
|---|---|---|---|
| 0. Cache check | 0 | local vault | — |
| 1. Pre-filter | 1 | shibui SQL | — |
| 2a. Sweep SQL | 1 | shibui SQL with 8 CTEs `UNION ALL` | per-style Finviz URL (one per style) |
| 2b. TV screens | 3 | one parallel batch (CANSLIM + sector ETF + volume breakout) | per-screen Finviz URL |
| 3. Breadth | 4 | one parallel batch (shibui SQL + VIX/VXV yahoo_price + sector_rotation) | Finviz groups + yahoo quote page |
| 4. Reversal bullish | 1 | shibui SQL inline with the 15:55 entry alert | `finviz_reversal_bullish()` |
| 5. Pre-market gapper | **1 (batched)** | `finviz_premarket_gap_url(tickers)` → one `web_fetch` | per-ticker `stock_extended_hours` |
| 6. Live RVOL rerank | **1 (batched)** | `stock_prices` with comma-separated `EXCHANGE:SYMBOL` list | per-ticker `coin_analysis` |
| **Base sweep + live** | **~11 + 2 live** | | |

Compare to naive approach (one screen call per stylist × 10 stylists × per-ticker live): ~40+
TV calls + 20 shibui calls + 24 per-ticker live = **~85 MCP calls vs ~13 here**.

## Fallback chain (when MCP rate-limits)

See `references/fallbacks.md` for the full decision matrix. Short version:

1. **MCP** — primary, fastest, most structured.
2. **Finviz GET screener** (`web_fetch`) — free, no auth, ~200 rows per query. URL builders
   in `scripts/screen.py` (`finviz_bonde_4pct()`, `finviz_peoplewish()`, …) and the
   `finviz-url <kind>` subcommand.
3. **TradingView public symbol-search JSON** (`web_fetch`) — symbol metadata + last price.
4. **Yahoo Finance quote page** (`web_fetch`) — last-resort HTML parse.

The Agent logs `_source=mcp | finviz_fallback | tv_fallback | yahoo_fallback` per row so we
can see when the chain fires. Rule: try MCP first; fall back only on explicit
`error` / `rate_limited` / `timeout`. Don't fall back twice in a row — surface the issue.

## Caching rules

- Cache key: `(YYYY-MM-DD, screener_name)`.
- Re-run on same day only when `force=True` (manual) or when `market_state` changes
  (e.g. trade from pre-market to regular).
- Stalk/Focus output: invalidate at 18:30 ET every day, re-tier.
- Master list: invalidate Sunday 17:47 ET only.

## Output contract

Each daily directory contains:
- one Markdown per stylist (named after the trader)
- merged `master.md`, `stalk.md`, `focus.md`, `tier-a.md`
- `_summary.md` digest + `_regime.json` payload
- one CSV per Markdown for downstream consumption

`_summary.md` is what the pre-market brief reads. Top of file has 4 bullet rows:
1. Regime state
2. Tier-A names (convergence ≥ 4)
3. Today's parabolic short/long candidates
4. 3:55 PM reversal-bullish list (after 15:55 ET)

## Failure handling

- If shibui SQL times out: fall back to TV screens only, mark output `degraded=true`.
- If TV screen hits rate limit: skip that sub-screen, mark in summary, continue.
- If yahoo-price fails for breadth index: skip ATR-extension read, regime still computable
  from breadth + index-vs-MA alone.

## References

- `references/filters.md` — exact filter expressions for each sub-screen
- `references/crons.md` — cron definitions (prompt + schedule + agent_name)
- `references/tiering.md` — Master / Stalk / Focus logic + skip-rule flags
- `references/fallbacks.md` — full fallback chain (MCP → Finviz → TV public → Yahoo HTML)
