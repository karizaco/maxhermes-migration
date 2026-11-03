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
- **Check the cache first.** `python scripts/screen.py cache <cron_date>` prints whether
  this date's sweep already produced a complete output set. If it is complete and the
  resolved data date has not moved, stop — do not re-spend the ~20 MCP calls. A cache is
  only valid while `_cache.json`'s `data_as_of` still matches what shibui resolves to, so
  pass `--resolved-date` to `plan --use-cache` and the comparison is automatic.
- Otherwise create the lock file and run
  `python scripts/screen.py plan <cron_date> --resolve-latest --out <scratch>/plan.json`
  (T+1-safe flow — see 0.5). This makes the daily sweep self-heal when shibui's data
  ingestion lags the cron fire time. See "⚠ shibui is T+1 — daily sweep" below.

### 0.4. Validate the SQL before you run it (offline, no MCP)

Five defects shipped in this skill's own `scripts/screen.py` and were only found by
running the queries against the live database. Three failed loudly; **two were silent** —
a lookback window shorter than the `LAG` it needs (the whole RS book came back empty and
looked like a quiet tape) and a `UNION ALL` that published one metric under another
metric's column header.

`scripts/sql_lint.py` checks the SQL's shape with no database and no third-party
dependency, so it works even when shibui is unreachable or rate-limited:

```
python scripts/sql_lint.py --emitted --date <YYYY-MM-DD>   # lint this skill's own emitters
python scripts/smoke_test.py --date <YYYY-MM-DD>            # full offline check, < 5s
```

**Run `sql_lint.py` before every sweep.** It fails on: a missing CTE separator, UNION
branches with mismatched column counts, UNION branches with mismatched column NAMES, an
identifier that resolves to nothing, a `LAG`/`LEAD` offset wider than the query's own
lookback window, a missing `LIMIT`, a division without `NULLIF()`, and date arithmetic on
a bare string literal. `smoke_test.py` additionally asserts that the linter still
catches the five historical defects (fixtures in `scripts/testdata/`), so the guard
cannot silently stop working.

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

**The market-cap floor is now applied inside the sweep SQL too**, not only in this
pre-filter step. Each sweep query joins `shibui.valuation` latest-row-first and requires
`market_cap > 300_000_000`, so non-equities cannot reach the tiering stage at all.

That matters: 67 of 530 candidates in the 2026-10-28 run had no market-cap row — 52
ETFs (mostly 2×/3× leveraged products), 14 preferred shares and one microcap. Leveraged
ETFs clear momentum and volume screens purely through leverage, and two 2× TSLA ETFs
(TSLG, TSLL) had reached Tier-A before the floor was enforced. A name with no valuation
row cannot demonstrate the floor, so it is out of the equity universe.

> The market-cap lookup takes the **latest valuation row per symbol first** and only
> then applies the cap. `shibui.valuation` keeps several rows per symbol per date, so
> filtering on the cap first admits stale rows whose cap was once above the threshold.

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

### 2.5. Add the same-day print column (optional but recommended)

The screen is built on shibui's last **ingested** close, which is normally one session
behind the cron day. Every screen metric therefore describes yesterday's tape, while the
trader is acting on today. Close that gap with one batched step:

```
python scripts/same_day_prints.py --from-csv <scratch>/master.csv --out-dir <scratch>
```

It fetches the official 4:00 PM print for every candidate from the Nasdaq public quote
API and writes `_same-day-prints.json` + `same-day-prints.md`. The `Session` column
distinguishes the official close (`official_close`) from a merely last trade
(`last_trade`), and carries the print's date, so a stale print is visible rather than
silently presented as today's move. This step is best-effort: if it fails, the sweep
still stands — it adds context, it does not gate the run.

### 3. Compute breadth / regime snapshot (one shibui SQL + one TV call)

The breadth SQL is emitted by `scripts/screen.py emit-sql breadth <date>` (there is no
`scripts/breadth.py` — it was never published, and the 2026-11-03 sweep found it 404s).
It returns:

- `% of large caps above 20-DMA` (shibui SQL — the large-cap proxy, since shibui has no
  SPX-constituents table)
- ATR% extension from 50-MA on `SPY / RSP / QQQ / QQQE / IWM` (shibui SQL — five rows)
- VIX / VIX3M ratio (one delayed-quote call)
- Sector rotation (sector/industry ETF relative strength)

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
- `daily-screens/<date>/focus.md`             — Focus: Master ∩ (≥ **2** distinct stylists) ∪ top-5 velocity (≤ 12)
- `daily-screens/<date>/tier-a.md`            — Tier-A: Focus ∩ (≥ **3** distinct stylists) (≤ 8), with regime flag
- `daily-screens/<date>/_summary.md`          — human-readable digest
- `daily-screens/<date>/_regime.json`         — breadth/regime payload
- `daily-screens/<date>/_results.json`        — **machine-readable** companion: every candidate with its
                                               origins, stylist buckets, skip flags and metrics, plus the tier
                                               lists, the regime, and the counts. Downstream routines read
                                               this instead of re-parsing Markdown.
- `daily-screens/<date>/_cache.json`          — cache marker (cron date, resolved data date, counts) used by
                                               `screen.py cache` / `plan --use-cache` to avoid repeating a
                                               completed sweep.

**Stylist buckets — five of them.** `n_stylists` counts distinct *stylists*, not screen
hits: `stockbee`, `qullamaggie`, `jeff_sun`, `hernandez`, `peoplewish`. The
TradingView volume-breakout screen counts as **Jeff Sun** (it is his volume proxy), so
one stylist's two screens cannot masquerade as two independent opinions. A name hitting
Stockbee 4% *and* Stockbee EP9M is one stylist with two hits.

**Thresholds:** Focus ≥ 2 stylists (cap 12), Tier-A ≥ 3 stylists (cap 8). Tier-A is
derived from Focus; when more than 8 names clear the bar the list is truncated and
`_results.json` reports `tier_a_truncated: true` with the untruncated pool size.

### 5. 3:55 PM ET Reversal Bullish (Bonde)

Only run on weekdays between 15:30 and 16:00 ET. Output: `daily-screens/<cron_date>/reversal-bullish-3:55.{md,csv}` with the candidates that pass **all** of Pradeep Bonde's published criteria.

**Pradeep Bonde / Stockbee criteria** — the gate values are Bonde's **published** ones, from
`stockbee.blogspot.com` (2019-11-26, "Reversal Bullish Scan I use":
`l=minl5 and (o-l)>(c-o) and (c-l)/(h-l)>=.6 and v>=290000 and c>=5 and minv3.1>=100000`)
plus his Playbook and the BreakoutsHappen write-up of the same workflow:

| # | Criterion | SQL form |
|---|---|---|
| 1 | **5-day low** — "stock making 5 day low" | `low <= MIN(low, last 5 rows)` |
| 2 | **Close in the top 40% of the day's range** — published `(c-l)/(h-l) >= .6` | `DCR = (close - low) / (high - low) >= 0.60` |
| 3 | **Lower shadow longer than the body** — published `(o-l) > (c-o)` | `(open - low) > (close - open)` |
| 3b | **Hammer** — "a long, well-defined lower shadow and a small body" | `lower_shadow >= 2 * upper_shadow`, where `lower_shadow = LEAST(open,close) - low` and `upper_shadow = high - GREATEST(open,close)` |
| 3c | **Small body** — "small body, narrow, pushed toward the top of the range" | `ABS(close - open) / (high - low) <= 0.30` |
| 4 | Small body (house rule; non-binding given 3c) | `ABS(close - open) / (high - low) <= 0.40` |
| 5 | **Prior decline of 2–3 days, with a washout** — "the drop should last at least 2-3 days" / "there has to be some sort of a wash out" | `(low / close_1d_ago - 1) <= -0.015` **and** (`(close / close_3d_ago - 1) <= -0.03` **or** `(close / close_5d_ago - 1) <= -0.03`) |
| 6 | **ADR ≥ 3%** — exclude slow movers (counter-example: SMFG at 1.33% ADR was rejected) | `AVG((high-low)/close, 20 rows) >= 0.03` |
| 7 | **Close ≥ $5** — published `c >= 5`. "Prefer higher priced stocks" is a **ranking** preference, not a filter | `close >= 5.0` |
| 8 | **Long-term trend** — exhaustion at support, NOT long-term downtrend | `close >= close_20d_ago * 0.92` (20 sessions back, not 21) |
| S | **Stop** — body low, but the signal bar's LOW if the body is under 15% of the range; must be ≤ 2.5% from the entry | `CASE WHEN body_ratio < 0.15 THEN low ELSE LEAST(open, close) END` |
| U | **Universe** — NYSE/NASDAQ/AMEX, market_cap > $5B (proxy for institutional ownership ≥ 1,000 funds; shibui does not expose `institutional_holders_count`), avg_vol_30d > 1M | |

> **The tail:body ratio is NOT a gate.** The old criterion 3 (`(LEAST(open,close) - low) >= 3 * ABS(close - open)`)
> has no published ceiling and explodes on a near-doji body — the 2026-10-26 CBRE bar printed a 15× ratio
> off a 3.2% body, and the 2026-10-27 CELH bar a 17× ratio off a 5.2% body. Bonde's published expression is
> `(o-l) > (c-o)`; the "3 to 5 times the body" line is his prose description of a hammer, and the hammer test
> (3b) is the scale-free way to apply it. If a report quotes a tail:body ratio, quote it as a description,
> never as a pass/fail.

**Universe** is the **single biggest filter** for Bonde's RB scan. Per Bonde:
> "The universe we need is the set of stocks owned by at least 1,000 institutional funds."

shibui does not have `institutional_holders_count`. Two proxies:
- `market_cap > 5_000_000_000` (5B USD floor — used as default)
- `mcp__tradingview__screen_stocks` filter `institutional_holders_count >= 1000` (more accurate but adds an MCP call; only use when validating a short list, not as the primary universe gate)

**Bonde's output discipline** (do NOT skip these):
- "Select 1 to 3 ideas" — the screen returns the mechanical passers; the discretionary review narrows to 1-3. Do not pad with marginal setups.
- "Prefer higher priced stocks" — a **ranking** preference, applied when ordering the final list. It is not a filter (the published price floor is $5).
- "Run the Stockbee Reversal Bullish Scan between 3.30 to 3.55 PM" — cron at 15:55 ET is right at the end of Bonde's window.
- "Enter between 3.58 to 4PM or using Market On Close order (MOC)" — the cron is a screener, not an executor; entry is the trader's job.
- "Put stop of less than 2%" — Bonde places the stop at the **low of the candle body** next morning, sized so loss ≤ 2.5%. **On a near-doji body the body low sits inside the bar's own noise** (0.07% away on the 2026-10-26 CBRE bar) and produces false exits, so when `body_ratio < 0.15` the report uses the signal bar's low instead — Bonde sanctions this: *"If you prefer to place the stop at the low of the shadow instead, make sure that level does not exceed a 2.5% loss from your purchase price."*
- "Exit on stop hit if it does not work on 3rd day" — typical hold 1-3-5 days; report a "Day 1 / Day 2 / Day 3+" tag so the trader knows how stale the signal is.

**The entry is TODAY's close.** The signal bar is today's live candle, so `entry_price` is
that candle's live price and the tradeable entry is the 16:00 ET close (Bonde enters 3.58–4PM, or
MOC). The candle is read at ~15:55 ET, so the final print can still move the close, the DCR and
the stop — say so in the artifact. **There is no "resolve against the next session" step any
more**: the D-day bar IS the signal, which is the whole point of scanning the live session rather
than reading yesterday's settled file. A same-day signal is always **Day 1**.

Two caveats the artifact must state: `v >= 290000` is judged on a **partial day's volume**
(as of ~15:55 ET), so a name that only clears 290k after the close was wrongly excluded; and
ADR(20) is computed over the 20 **settled** sessions before today, not over a window that
includes the incomplete live bar.

On a **delayed replay** (the routine rebuilt for a past scheduled date) the signal bar is that
session's settled close and the entry was that session's close. Report the two failure modes
separately there, as before: a close a few cents below a doji body stop is a *noise breach*
(on 2026-10-26 CBRE closed below a body stop 0.07% wide and the stock returned +4.86% over three
sessions), while a close that **undercut the signal bar's low** is a *structural failure*
(CELH undercut the signal low by $0.26 and the setup was genuinely dead). Never report both as
"stop hit".

**THE SIGNAL IS TODAY'S LIVE SESSION — not yesterday's settled bar.** At 15:55 ET the US
session is ~99% complete, so today's open/high/low/close are readable NOW. Bonde's process is a
SAME-DAY scan — *"run the scan between 3.30 and 3.55 PM"*, *"enter between 3.58 to 4PM or using
Market On Close order (MOC)"* — so the signal bar is today's candle and the entry is today's close.

**Do NOT resolve the screen date as "the latest settled date in shibui".** shibui is end-of-day,
so at 15:55 ET its newest bar is YESTERDAY's. A shibui-only scan measures the previous session's
candle and points at an entry one session after the signal — and the D-day bar can invalidate the
setup before the entry ever happens. That one-session lag is an artifact of the data source, not
of the playbook. It is what the 2026-10-30 run did: it measured Thursday's candle on a Friday and
reported DOCU, whose Friday candle was a weak close (DCR 0.24). **A screen that reports
yesterday's candle as today's signal is WRONG, however well-formed its output looks.**

#### THE DAY-ALIGNMENT ASSERTION — the one thing that must never break

A screener that fires at 15:55 must prove WHICH session it is looking at, every run, before it
computes anything. The proof is arithmetic, not opinion:

```
implied_previous_close = live_close / (1 + change_pct / 100)
```

If the scanner is on today's live session, that implied previous close MUST equal the latest
settled close the history source holds for the same symbol.

| Verdict | Test | Action |
|---|---|---|
| **LIVE** | implied previous close == latest settled close, for ≥90% of a reference set | scan today's session |
| **NO_SESSION** | the scanner's `close` equals the latest settled close instead (weekend / holiday / pre-open) | there is no session to scan — write the no-session artifact and stop; **do not** substitute the previous session's scan |
| **DEGRADED** | neither | **do not trade it.** Write the artifact flagged `degraded=true`, with no candidates |

Anchor the assertion to the session **SEQUENCE**, never to calendar arithmetic: "one session ago"
means the previous *trading* session, so weekends and holidays need no special-casing.

#### DATA PATH

| Role | Source | Why |
|---|---|---|
| Live session OHLC for the whole universe | **TradingView public scanner** — `POST https://scanner.tradingview.com/america/scan`, columns `name, description, close, open, high, low, change, change_abs, volume, average_volume_10d_calc, market_cap_basic, exchange, type, sector` | during a session these are the CURRENT session's OHLC; `close` is the live price |
| Universe gates | the same call — `filter` on `market_cap_basic > 5e9`, `exchange in_range [NYSE,NASDAQ,AMEX]`, `type == stock`, `close > 5`, `average_volume_10d_calc > 1e6` | live market cap, so there is no stale-row problem (unlike `shibui.valuation`) |
| Settled history (5-day low, ADR, prior closes, average volume) | **shibui** over the MCP-over-HTTP bridge — one `stock_data_query` per 6 tickers with `QUALIFY ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) <= 30` | one server, 30 sessions per ticker |
| History fallback | **Nasdaq** — `GET https://api.nasdaq.com/api/quote/{SYM}/historical?assetclass=stocks&fromdate=…&todate=…&limit=40` | 1 call per ticker; use it when shibui's `tools/call` is unavailable. Needs a browser `User-Agent`; some cells come back as the string `N/A`; Nasdaq 404s on symbols it does not carry |
| Entry quote / session state | **`market-recap get_quotes`** (bridge) — `price, previous_close, change_pct, volume, day_high, day_low, as_of, market_state` | confirms the session and the entry print |

**TradingView paging trap — measured 2026-11-03:** `range` paging WITHOUT an explicit `sort`
returns OVERLAPPING pages — 1500 rows fetched but only 1212 unique, silently losing 288 names.
Always send `"sort": {"sortBy": "name", "sortOrder": "asc"}`, fetch the whole filtered universe in
ONE call with `range: [0, 2000]`, and de-duplicate by ticker. The filter key is **`filter`**, not
`filters`. `type == "stock"` INCLUDES REITs — do not re-filter to common stock, and do not filter
on domicile.

**shibui's `tools/call` endpoint is NOT always up** — measured 2026-11-03, `tools/list` answered
while every `tools/call` returned an empty body. The history fallback above is not optional.

#### IMPLEMENTATION

The screen is implemented as `tools/reversal_bullish.py` in `karizaco/maxhermes-migration` — the
same pattern cron #91 uses with `tools/schedule-drift.py`:

```bash
curl -sL -o /workspace/tools/reversal_bullish.py \
  https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/tools/reversal_bullish.py
python3 /workspace/tools/reversal_bullish.py --date "$(TZ=America/New_York date +%F)"
```

It fetches the universe, runs the day-alignment assertion, applies every gate above, writes
`reversal-bullish-3:55.{md,csv}` into the dated directory and prints a JSON report. **Read that
report**: `mode` is `LIVE`, `NO_SESSION`, `DEGRADED` or `SETTLED_REPLAY`; `passing` is the
candidate count; `history_source` says whether history came from shibui or the Nasdaq fallback.
Exit code 3 means "no US session today" — a clean outcome, not a failure. Passing a date other
than today rebuilds that past session from settled bars and flags it as a reconstruction.

**The Finviz fallback cannot serve this scan.** `finviz_reversal_bullish` encodes "today down +
above SMA50 + liquid + large-cap" and none of Bonde's candle gates; it also returns no candle
geometry. It is not a substitute for the live bar — if the live path is unavailable, report the
run as degraded rather than publishing a Finviz list as today's signal.

**Fallback when the live path is unavailable.** The settled-scan SQL
(`scripts/screen.py emit-sql reversal_bullish <date>`) remains the reference implementation of the
gates above, and is what a **delayed replay** or a **degraded** run uses — but a settled scan can
never produce a same-day entry, so an artifact built that way must say so explicitly and must not
be presented as today's signal.

- Resolve latest date first via `scripts/screen.py emit-sql resolve_date <date>`
  and substitute `latest_date` into the reversal-bullish SQL.
- **The canonical SQL is `scripts/screen.py emit-sql reversal_bullish <latest_date>`** (the
  `reversal-bullish` alias emits the same thing). It is already T+1-safe and Bonde-strict: the
  inner CTE is windowed over 60 calendar days so `LAG()` and the 5-day/20-day windows see full
  history, the outer query takes `rn = 1` per symbol, `shibui.valuation` is de-duplicated to each
  symbol's most recent row (a stale market cap must not qualify a symbol), and every gate above is
  applied in the query. It replaces the older loose form, which had three defects: the CTE
  filtered `WHERE date = '<date>'` before the LAG window (so `LAG(close,2)` was NULL for everyone
  and the 2-day-decline filter dropped the whole result set), it hard-coded `<date>` instead of
  `MAX(date) <= <date>`, and it carried none of the Bonde-quality filters.
- **A 15:55 ET scan on a T+1 feed cannot make a 15:58 ET entry.** The signal bar is the previous
  session, so every candidate is a *next-session* planning artifact — say so in the artifact.
  The routine's own 2026-10-29 run states it: *"Bonde's entry window has passed… a name taken
  today is a Day-2 entry by Bonde's 'first day of the swing' rule, which his own published
  process rejects."* When a live bar for the cron day IS available (Yahoo 5m with
  `includePrePost=true`, or a bridge source carrying the in-progress session), scan today's live
  bar and re-pull it after the 16:00 ET bell — that is the only way the same-day entry window can
  be honoured.

**Common rejections** — these all showed up in the loose scan on Sep 21 2026
and were rejected by Bonde's stricter criteria. Keep this list as a debugging
reference when the scan produces fewer than 5 names:

| Symptom | Reject criterion | Example (Sep 21 2026 loose scan) |
|---|---|---|
| Slow mover (ADR < 3%) | filter 6 | `SMFG` (1.33% ADR) |
| Long-term downtrend | filter 8 | `XPEV`, `TFII`, `ERIC` |
| Choppy / mid-range close | filter 2 (DCR < 0.60) | `INTU`, `JBHT` (closed near lows) |
| Random chop, no pullback pattern | filter 1 (no 5-day low) | `WPP` |
| Sideways drift — no prior decline | filter 5 (no washout) | `HIMS` on 2026-10-26: a −5.5% two-day slide, but a doji bar whose upper shadow exceeded its lower shadow (DCR 0.514) — the decline was real, the candle was not a hammer |
| Doji body, absurd tail ratio | filter 3b (hammer test) | `CBRE` on 2026-10-26: 15× tail on a 3.2% body, DCR 0.510, lower shadow 1.35 vs upper 1.39 |
| Day 2+ setup (already past entry window) | n/a — review timing tag | `EXE`, `EQT`, `STE` (Bonde's "first day of swing" rule) |

**Finviz fallback** — when shibui fails or times out:
- `screen.py finviz-url reversal_bullish` returns a URL with `ta_change_d, ta_sma50_pa, sh_avgvol_o1000k, cap_largeover` (today down + above SMA50 + liquid + large-cap). It does NOT encode Bonde's 5-day-low / tail-body / DCR filters.
- Accept rows as-is with `_source=finviz_fallback`, write the artifact, and **skip chat alerts** (per the cron prompt's "no chat on Finviz fallback" rule). The user reviews the markdown manually.

### 6. Pre-market Gapper (Sun + Bonde)

Run at 08:30 ET weekdays only (the deployed `#08-pre-market-gapper` cron slot). For each ticker
in `focus.md`:

- One `mcp__tradingview-advanced__stock_extended_hours(ticker)` call **per ticker**
  — cap at the 12 names in the Focus list, so this is ≤ 12 calls
- Flag names with `gap_pct > 4` AND `pre_market_volume > 50_000`
- One chat line per flagged name

### 7. Live intraday RVOL re-rank (Sun)

Weekdays at 09:45, 10:15, 10:45, 11:15 ET — of those, only 09:45 ET is a deployed cron
(`#07-focus-rvol-09:45`); the other slots are manual runs. For each Focus ticker:

- One `mcp__tradingview-advanced__coin_analysis(symbol, exchange=NASDAQ, timeframe=15)`
  call. Returns RVOL + indicators.
- Sort Focus list by intraday RVOL desc.
- Output `focus-rvol-snapshot.md` and split into **RVOL Required** vs **Liquid** buckets
  (Sun's published tier split).
- If any ticker's RVOL crosses from < 1 to > 3, emit one chat alert.

### 8. Hook into existing briefs

- 08:30 ET pre-market brief: prepend yesterday's `tier-a.md` + `regime.json`.
- Sunday 17:47 ET weekly brief: add sections for `ipo.md`, `high-short-float.md`,
  the theme-of-the-week (top-3 sector ETFs × tickers that appeared in daily Focus),
  the peoplewish 1000%-in-10-years backlog enrichment (run the `pattern-study` script).

## Data sources — what actually lives where

**Two runtimes, two different tool sets.** The MCP tool names in the original spec are
registered on the *local* Mavis install (`~/.minimax/mcp.json`), not in the Cloud runtime
where these crons actually fire. "The tool name is not registered" is **not** "the source
is unavailable" — read the runtime contract before declaring a source dead.

| Source | Local Mavis (stdio MCP) | Cloud runtime (what the cron actually uses) |
|---|---|---|
| `shibui-finance` | `mcp__shibui-finance__stock_data_query` | Same server over HTTPS JSON-RPC via `cloud-prompts/_shared/mcp_bridge.py` — `python3 mcp_bridge.py shibui stock_data_query args.json` |
| `tradingview` | `mcp__tradingview__screen_stocks` / `screen_etf` | TradingView's per-country scanner HTTP API: `POST https://scanner.tradingview.com/america/scan` (no auth, no rate limit) |
| `tradingview-advanced` | `mcp__tradingview-advanced__*` | Not reachable. The scanner API covers most of it; the CBOE delayed-quote CDN covers the index quotes |
| `yahoo-finance` | `mcp__yahoo-finance__*` | JSON endpoints return HTTP 429 from the Cloud egress; the quote *page* still renders |
| `financekit` | `mcp__financekit__sector_rotation` | Not reachable — sector rotation is computed from TradingView ETF relative strength instead |

**shibui specifics.** `https://mcp.shibui.finance/mcp` — DuckDB on their server, ~10,384
US securities, 31.7M daily bars, 61 technical indicators, quarterly fundamentals. The
call we make most is `stock_data_query`: submit a DuckDB SQL string, get JSON rows back.
The `user_prompt` argument is **mandatory** (stats only; never affects execution).

**Practical limits discovered in test runs:**
- Data is end-of-day, T+1 day. Today's bar appears next morning.
- 200-row LIMIT per query (server-enforced).
- **Rate limiting is real**: shibui answers `HTTP 429` with a `retry-after` header when
  the daily quota is spent (it was spent on 2026-11-03 by a morning sweep plus the other
  routines that share the server). A 429 is not a broken query — wait out the
  `retry-after` and re-run; do not rewrite the SQL.
- No `ipo_date`, no `short_interest_pct_float`, no `institutional_holders_count` columns.
  `fundamentals_derived_quarterly` DOES have `eps_growth_yoy` / `revenue_growth_yoy`
  (decimal fractions — 0.25 means 25%), which is where CANSLIM's growth criteria come
  from in the Cloud runtime.
- No SPX-constituents table. Use large-cap (mcap > $10B) proxy for breadth.
- `stock_quotes.symbol` is venue-suffixed (`AAPL.NASDAQ`); `stock_quotes.ticker` is bare
  (`AAPL`). An `IN` filter on the wrong column returns **zero rows silently**.

For full schema + SQL rules, see `references/filters.md`.

## MCP-call budget per run

| Stage | Primary MCP calls | Batched? | Tier-2 fallback |
|---|---|---|---|
| 0. Cache check | 0 | local file read | — |
| 0.4 SQL lint | 0 | offline, no MCP | — |
| 1. Pre-filter | 1 | shibui SQL | — |
| 2a. Sweep SQL | 3 | one `UNION ALL` per stylist group (Stockbee / Qullamägi / peoplewish) | per-style Finviz URL (one per style) |
| 2b. TV screens | 3 | one parallel batch (CANSLIM + sector ETF + volume breakout) | per-screen Finviz URL |
| 3. Breadth | 3 | one parallel batch (shibui SQL + VIX/VIX3M + sector RS) | Finviz groups + yahoo quote page |
| 2.5 Same-day prints | 1 batched | one Nasdaq `/info` request per candidate, 12 at a time | skip — the sweep stands without it |
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
   `finviz-url <kind>` subcommand. **In the Cloud runtime Finviz is behind a Cloudflare
   challenge (HTTP 403 from both `curl` and `web_fetch`), so this rung is unavailable
   there — go to rung 3.**
3. **TradingView scanner API** (`POST https://scanner.tradingview.com/america/scan`) —
   no auth, no rate limit, and one call returns every schema field the skill needs
   (close/open/high/low/volume/change/market_cap_basic/exchange/sector/Perf.1M/3M/6M).
   It is also *richer* than the MCP wrapper, adding `premarket_volume`,
   `average_volume_10d_calc` and `relative_volume_10d_calc`.
4. **Nasdaq public quote API** (`api.nasdaq.com/api/quote/{SYM}/info`) — the official
   4:00 PM close, the same-day print column and the market cap.
5. **CBOE delayed-quote CDN** (`cdn.cboe.com/api/global/delayed_quotes/quotes/_VIX.json`) —
   index levels for the regime read.
6. **Yahoo Finance quote page** (`web_fetch`) — last-resort HTML parse (the JSON
   endpoints are HTTP 429 from the Cloud egress).

The Agent logs `_source=mcp | finviz_fallback | tv_fallback | yahoo_fallback` per row so we
can see when the chain fires. Rule: try MCP first; fall back only on explicit
`error` / `rate_limited` / `timeout`. Don't fall back twice in a row — surface the issue.

## Caching rules

- Cache key: `(YYYY-MM-DD, screener_name)`.
- Re-run on same day only when `force=True` (manual) or when `market_state` changes
  (e.g. trade from pre-market to regular).
- Stalk/Focus output: invalidate at 18:30 ET every day, re-tier.
- Master list: invalidate Sunday 17:47 ET only.

**The implemented cache.** `scripts/screen.py cache <date>` reports the state of a date's
outputs; `scripts/screen.py plan <date> --use-cache [--resolved-date <d>]` short-circuits
a repeat fire. The marker is `_cache.json`, written by `consume`, and it records the
resolved data date. A cache is valid only while the resolved data date has not moved —
so a later shibui ingestion (the T+1 catch-up) correctly invalidates it rather than
serving a stale sweep. The check is a local file read: it costs nothing and it removes
~20 MCP calls from a repeat fire.

## Output contract

Each daily directory contains:
- one Markdown per stylist (named after the trader)
- merged `master.md`, `stalk.md`, `focus.md`, `tier-a.md`
- `_summary.md` digest + `_regime.json` payload
- `_results.json` machine-readable candidate set (tiers, origins, stylist buckets,
  skip flags, metrics) — **the file downstream routines should read**
- `_cache.json` cache marker
- one CSV per Markdown for downstream consumption
- optionally `same-day-prints.md` / `_same-day-prints.json` (the "what it did today"
  column) and `reconciliation.md` / `_reconciliation.json` (the outcome panel)

`_summary.md` is what the pre-market brief reads. Top of file has 4 bullet rows:
1. Regime state
2. Tier-A names (≥ 3 distinct stylists)
3. Today's parabolic short/long candidates
4. 3:55 PM reversal-bullish list (after 15:55 ET)

## Failure handling

- If shibui SQL times out: fall back to TV screens only, mark output `degraded=true`.
- If shibui answers **HTTP 429**: it is a quota wall, not a broken query. Honour the
  `retry-after` header and retry; do not rewrite the SQL and do not silently publish a
  partial sweep.
- If a sub-screen returns **zero rows**, treat it as a failure, not a quiet tape. The
  RS book came back empty for a month because its lookback window was shorter than the
  `LAG(close, 252)` it needed — a silent zero that reads exactly like "nothing passed".
  `sql_lint.py` catches that shape offline; at runtime, cross-check the row count against
  the previous session before publishing.
- If TV screen hits rate limit: skip that sub-screen, mark in summary, continue.
- If the growth columns come back null (as TradingView's do for US equities): rebuild
  CANSLIM on shibui's `fundamentals_derived_quarterly.eps_growth_yoy` /
  `revenue_growth_yoy` rather than publishing an empty screen.
- If the index quote fails for breadth: skip ATR-extension read, regime still computable
  from breadth + index-vs-MA alone.

## Scoring the book (optional, weekly)

`scripts/reconcile.py --date <signal-date> --from-csv <master.csv> --out-dir <dir>` pulls
the sessions *after* a signal date out of shibui and reports each candidate's 1/3/5
session forward return against the benchmark's return over the same window. Sessions
that have not happened yet are reported as pending, not as zero. Without this loop a
screen cannot be judged, only believed.

## References

- `references/filters.md` — exact filter expressions for each sub-screen
- `references/crons.md` — cron definitions (prompt + schedule + agent_name)
- `references/tiering.md` — Master / Stalk / Focus logic + skip-rule flags
- `references/fallbacks.md` — full fallback chain (MCP → Finviz → TV scanner → Nasdaq → CBOE → Yahoo HTML)
- `references/agent-output-shape.md` — the JSON shape `consume` expects
- `scripts/sql_lint.py` — offline structural lint for the SQL this skill emits
- `scripts/smoke_test.py` — the offline check to run before merging a change
