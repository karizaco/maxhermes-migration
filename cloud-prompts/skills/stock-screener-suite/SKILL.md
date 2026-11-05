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

> **The market-cap lookup is a single-date join, and it has to be.** `shibui.valuation`
> has a primary key on `(symbol, date)`, so one date yields exactly one row per symbol —
> and that date is `MAX(date) <= the resolved date`, so it self-adjusts if valuation lags.
> The obvious alternative — take the latest row per symbol with
> `QUALIFY ROW_NUMBER() ... = 1` over `date <= '<d>'` — scans all **18.9M** valuation rows
> and took every sweep past the 90-second bridge timeout. The single-date form is
> equivalent for the cap floor and is ~8× faster. It is also *safer*: filtering on the cap
> before picking the latest row admits stale rows whose cap was once above the threshold.

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

#### ⚠ An end-of-day read must use the SETTLED CLOSE of the cron day, not shibui's newest session

shibui is T+1, so at the 18:30 ET fire its newest settled session is **D-1**. The breadth
SQL above therefore measures the PRIOR session's breadth — wrong by definition for an
end-of-day artifact, which is supposed to describe the close the trader just saw.

For the 18:30 ET sweep (cron #09):

- Compute the breadth numbers for the **cron day's settled close** from TradingView's
  scanner: the same universe filter the SQL uses (`exchange in_range [NYSE,NASDAQ,AMEX]`,
  `type == stock`, `market_cap_basic > 10_000_000_000`), with columns
  `close, SMA20, SMA50, SMA200, ATR`. `% above 20-DMA`, `% above 50-DMA`,
  `% above 200-DMA`, advance/decline and the five index ETF rows (SPY/RSP/QQQ/QQQE/IWM)
  all come from that ONE call.
- Keep the shibui breadth SQL as the **T+1 cross-check**, not as the published number, and
  publish both. The two are NOT two readings of one series: the populations differ
  (1,001 TradingView names on 2026-11-04 vs 905 shibui names on 2026-11-03) because the
  market-cap sources differ (`market_cap_basic` vs `valuation.market_cap`).
- The VIX/VIX3M pair comes from the Cboe delayed-quote CDN and must be quoted as ONE pair
  with its `last_trade_time`, used everywhere in the artifact. Never mix a mid-session
  print with a settled close.
- The output path is `daily-screens/<date>/breadth.md` (plus `_regime.json` in the same
  dated directory). The path `daily-screens/breadth/<YYYY-MM-DD>.md` written above is
  stale — cron #09 and cron #10 both write into `daily-screens/<date>/`, and they must
  never share a filename.

#### The Nasdaq `/info` `primaryData` is NOT the official close after 16:00 ET

Verified 2026-11-04 on 15 Focus/Tier-A names: TradingView's `close` matched Nasdaq's
official 4:00 PM close (`secondaryData`) on **15 of 15**. Nasdaq's `primaryData` on the
same pulls was the **after-hours** print stamped 18:36 ET (MRNA `primaryData` 256.86 vs
`secondaryData` 258.38; ECG 81.43 vs 79.71; KVYO 19.79 vs 21.36).

- Use `secondaryData` for the official close — or TradingView's `close`, which equals it.
- `primaryData` is the live/after-hours last trade: correct for the intraday routines,
  wrong for an end-of-day artifact.
- Any same-day-print column must record WHICH of the two it used, or the reader cannot
  tell a settled close from an after-hours drift.

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

#### Two traps when the tiering is re-implemented inline (the Cloud runtime does not execute scripts/screen.py)

- **The per-stylist FILE names are slugs; the stylist BUCKET names are not.** The files are
  `stockbee.md`, `qullamaggie.md`, `jeff-sun.md`, `ariel-hernandez.md`, `peoplewish.md`, but
  the buckets are `stockbee`, `qullamaggie`, `jeff_sun`, `hernandez`, `peoplewish`. Split the
  candidates on the BUCKET and write them under the SLUG. Keying the split on the slug
  silently writes an EMPTY `jeff-sun.md` and an EMPTY `ariel-hernandez.md` while every
  downstream count still looks plausible. **Assert that every per-stylist file has ≥ 1 row**
  before publishing — an empty per-stylist file is exactly the "silent zero that reads like a
  quiet tape" failure class.
- **The Kullamägi 5-session move is the SQL column `m1`.** It is what makes the parabolic
  short/long lists mean anything. Export `m1` into the candidate CSV (and `m2`), or
  `short-candidates.csv` / `long-reversal-candidates.csv` ship with their defining metric
  missing.

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
# --- fetch the screen (run-time fetch: fixes land with no redeploy) ---
# The CONTENTS API is authoritative and is NOT CDN-cached; raw.githubusercontent has been
# measured serving a STALE blob for >17 minutes after a push. The marker is mandatory: an
# OLD copy of this script would write the OLD artifact shape, and the checker below would
# then fail the run for no visible reason.
mkdir -p /workspace/tools
S=/workspace/tools/reversal_bullish.py
for U in \
  "https://api.github.com/repos/karizaco/maxhermes-migration/contents/tools/reversal_bullish.py?ref=main" \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/tools/reversal_bullish.py" \
  "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/tools/reversal_bullish.py" ; do
  curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" -o "$S.tmp" "$U" 2>/dev/null
  if [ -s "$S.tmp" ] && grep -q 'bonde-artifact-v3' "$S.tmp" 2>/dev/null; then
    mv -f "$S.tmp" "$S"; break
  fi
  rm -f "$S.tmp"
done
if [ ! -s "$S" ] || ! grep -q 'bonde-artifact-v3' "$S"; then
  echo "reversal_bullish.py: UNAVAILABLE (no copy of the script carrying the current artifact contract)"
  echo "no artifact; no push"
  exit 1
fi
python3 /workspace/tools/reversal_bullish.py --date "$(TZ=America/New_York date +%F)"
```

It fetches the universe, runs the day-alignment assertion, applies every gate above, writes
`reversal-bullish-3:55.{md,csv}` into the dated directory and prints a JSON report. **Read that
report**: `mode` is `LIVE`, `NO_SESSION`, `DEGRADED` or `SETTLED_REPLAY`; `passing` is the
candidate count; `history_source` says whether history came from shibui or the Nasdaq fallback.
Exit code 3 means "no US session today" — a clean outcome, not a failure. Passing a date other
than today rebuilds that past session from settled bars and flags it as a reconstruction.

**The markdown the script writes is the ARTIFACT FORMAT CONTRACT's skeleton, with the
mechanical parts already filled in and three markers for your discretionary review** — see
the contract below. The sequence is: run the script → fill `## Promoted ideas` and
`## Not promoted` and set the TL;DR's promoted count → run `tools/check_bonde_artifact.py`
→ push. Do not restructure the file by hand; fill the slots the script left.

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

#### ARTIFACT FORMAT CONTRACT (v3 — load-bearing for cron #04)

The 2026-11-03 screen was mechanically **correct** and the document was **wrong**: the
stop-vs-bar-low conflict appeared only as a sentence under `Method & caveats`, the volume
conviction was a clause inside the review, no idea carried an invalidation test, and the
promoted/not-promoted verdict sat 100 lines down. A trader reading the Candidates table
could not tell that the published stop sat **inside the signal bar's own range** — the
difference between "a 2.5% risk trade" and "this stop is inside the noise band", which
changes the position size. The structure below is fixed. Do not add, drop or reorder
sections.

**The script writes the skeleton; you fill three slots.** `tools/reversal_bullish.py`
writes the markdown with every mechanical part already in place and three markers:

| marker | what you replace it with |
|---|---|
| `<!-- REVIEW:PROMOTED_COUNT -->` | the number of ✅ IDEA blocks, in the TL;DR's second bullet |
| `<!-- REVIEW:PROMOTED -->` | one `### ✅ IDEA n — TICKER …` block per promoted name |
| `<!-- REVIEW:NOT_PROMOTED -->` | one line per non-promoted candidate |

A marker left in the artifact **fails the run's verification** (see §7 below). The script
also writes the TL;DR's third bullet — the caveat that changes how the candidates must be
read — computed from the data, so you do not rewrite it.

##### 1. Section skeleton (fixed order)

```
# Bonde Reversal Bullish — <Weekday, DD Month YYYY>
## TL;DR             exactly 3 bullets
## Candidates        one table, one row per name, all gate + metric + stop columns
## Promoted ideas    full reasoning per promoted name
## Not promoted      one line each: the gate it passed, why it was not promoted, its invalidation test
## Bonde gate matrix
## Filter funnel
## Method, source health & caveats
```

If a section has nothing in it, say so in one line — do not delete the heading.

##### 2. The TL;DR — exactly 3 bullets

1. **How many mechanical passers** — of how many names scanned, the mode, the signal session
   and the entry window.
2. **How many were promoted, and which.** This is the verdict. It must be reachable in the
   **first 15 lines** — never at the bottom of the review.
3. **The caveat that changes how they must be read.** The script computes it (a stop conflict
   beats a capped stop beats missing capitulation beats the plain timing caveat). Do not bury
   it, do not soften it, and do not move it into `Method & caveats`.

##### 3. Stop geometry is a FIELD, not a caveat

Every candidate row — in the markdown table **and** in the CSV — carries:

| column | meaning |
|---|---|
| `bar_low` / `bar_high` | the signal bar's actual range |
| `stop_vs_bar_low_pct` | **signed**: negative = the stop is BELOW the bar low (survives the bar's noise); positive = the stop is ABOVE the bar low, i.e. inside the bar's range |
| `stop_class` | `STRUCTURAL` / `NOISE_BREACH` / `CAPPED` (see below) |
| `stop_capped` | `yes`/`no` — did the 2.5% max-loss cap bind the stop |
| `bar_low_vs_entry_pct` | the structural distance to the bar low — the real risk, uncapped |

The three classes, exactly one per candidate:

- **`STRUCTURAL`** — the published stop is the structural level itself (the bar's low on a
  near-doji body). A print through it is a genuine structural failure.
- **`NOISE_BREACH`** — the published stop sits **above** the signal bar's low, so the bar
  itself already traded through it. A print through the stop is **noise**, not a failure.
  The structural failure level is the bar low.
- **`CAPPED`** — the 2.5% cap bound the stop while the published stop is still at or below
  the bar low, so it survives the noise but is tighter than the structural level.

`stop_capped` and `stop_basis` carry the cap fact in every case, so no information is lost
when the class is not `CAPPED`.

> **Two notes on the classes, so nobody reads more into them than is there.**
> (1) A **body-low** stop on a non-doji bar is *also* `NOISE_BREACH`: the signal bar's washout
> low traded below it, so the structural failure level is the **bar low**, not the body low.
> That is the fact the row publishes, and it is why `bar_low` and `bar_low_vs_entry_pct`
> travel with every candidate.
> (2) `CAPPED` does **not** occur with today's stop rule: the 2.5% cap can only pull a stop
> *up* into the bar's range, which makes it a `NOISE_BREACH`. The class is computed, not
> hardcoded, and `stop_capped` / `stop_basis` say plainly when the cap bound the stop.

> **The rule that came out of the 2026-11-03 run:** when a promoted idea's
> `stop_class == NOISE_BREACH`, its risk line goes to the **TOP of the reply** — inside the
> `### Signal` line for that name — not into `### Method & caveats`. Say what the stop is
> and what it means: *"stop 216.55 is inside the signal bar's range (low 214.67) — a print
> through it is a noise breach, not a structural failure"*. A trader must be able to choose
> which risk they are taking before they size the position, not after reading a footnote.

##### 4. Volume conviction is a NUMBER, not a sentence

Every candidate row carries `vol_vs_30d_avg_pct` (the session's volume as a percentage of the
30-session mean) and `capitulation` (`CAPITULATION` at ≥ 150% of that mean, `LOW_VOLUME`
below it). Quote **the script's number** — do not recompute it from another source, and do
not repeat "there was no capitulation behind it" as a prose clause. A trader wants to know
the setup lacked conviction **before** sizing it. Caveat to state once in the method
section: the volume is a partial day at ~15:55 ET, so the ratio reads slightly low.

##### 5. Every idea carries an invalidation test

Each **promoted** idea ends with one line:

```
**Invalidated if** <price> closes below <level> / <named event> does not happen by <date>.
```

The price leg is usually the signal bar's low (published as `invalidation_level` on the row)
— that is the level at which the thesis is structurally dead. The event leg is the thing
that must actually happen (the catalyst, the re-underwriting date, the overhang that has to
be revisited). The 2026-11-03 promoted idea (CRM) gave entry, stop, catalyst and the candle
metrics and said nothing about what would make it wrong.

The **same field goes on every non-promoted candidate** in `## Not promoted`, so the
watchlist is actionable later: PATH's invalidation test is its structural overhang (DA
Davidson Underperform, $10 target, ~25% short float, ~$43.6M/90d insider selling), plus the
bar low. One line per candidate: the mechanical gate it passed, the reason it was not
promoted, and its invalidation test.

##### 6. The CSV column contract

The CSV is the machine-readable twin and must never contradict the markdown. Required
columns beyond the existing ones:

```
bar_low, bar_high, stop_vs_bar_low_pct, bar_low_vs_entry_pct, stop_class, stop_capped,
vol_vs_30d_avg_pct, capitulation, invalidation_level
```

`bar_low`/`bar_high` are the signal bar's range (the same numbers as `low`/`high`, named
explicitly so no consumer has to guess which low is meant). `capitulation` is
`CAPITULATION` / `LOW_VOLUME` / `UNKNOWN`; `stop_class` is `STRUCTURAL` / `NOISE_BREACH` /
`CAPPED`. Write both files in the same dated directory, and never let a row exist in one
and not the other.

##### 7. Verify the artifact before you report it

```bash
C=/workspace/tools/check_bonde_artifact.py
for U in \
  "https://api.github.com/repos/karizaco/maxhermes-migration/contents/tools/check_bonde_artifact.py?ref=main" \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/tools/check_bonde_artifact.py" \
  "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/tools/check_bonde_artifact.py" ; do
  curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" -o "$C.tmp" "$U" 2>/dev/null
  if [ -s "$C.tmp" ] && head -5 "$C.tmp" | grep -q 'check_bonde_artifact.py'; then
    mv -f "$C.tmp" "$C"; break
  fi
  rm -f "$C.tmp"
done
python3 "$C" \
  --md /workspace/daily-screens/{date}/reversal-bullish-3:55.md \
  --csv /workspace/daily-screens/{date}/reversal-bullish-3:55.csv
```

It asserts the skeleton, the 3-bullet TL;DR, the verdict in the first 15 lines, the
`Ideas promoted` count against the number of ✅ IDEA blocks, the required columns on every
row of both files, that every promoted idea states its stop class and its invalidation
test, that every non-promoted candidate is accounted for, that no marker survived, and that
the artifact carries the current contract marker (`bonde-artifact-v3` — a missing marker
means a stale copy of the script produced it; re-fetch and re-run). It exits 1 and prints
each failure. **If it fails, fix the artifact and run it again — do not report a clean run
over a failing check.** Do not eyeball these things; the 2026-11-03 artifact looked fine
and failed four of them.

#### REPLY DISCIPLINE for cron #04

The shared reply format from `_shared/PROMPT-BLOCKS.md` (`## DELIVERY`) applies — prose
opener, `### Signal`, `### Method & caveats`, `### Files`, `### Push / errors`. Three
routine-specific rules on top of it:

- **The prose opener names the risk.** Its second sentence is the caveat that most changes
  how the run should be read. When a promoted idea is `NOISE_BREACH`, that is the caveat:
  the published stop is inside the signal bar's range.
- **The `### Signal` line for a NOISE_BREACH name says so in the line itself.** One
  ticker per line, with the catalyst AND the stop's meaning. Do not move it into
  `### Method & caveats`.
- **Do not re-publish the artifact's tables in the chat.** The table, the gate matrix and
  the funnel live in the file; the chat carries the verdict, the risk and the counts.

### 6. Pre-market Gapper (Sun + Bonde)

Run at 08:30 ET weekdays only (the deployed `#08-pre-market-gapper` cron slot). The universe is
the **Focus list** of the most recent completed 18:30 ET sweep (cron #09) — at 08:30 ET today's
sweep has not run yet, so you read the PRIOR session's `focus.md` / `focus.csv`.

This section is the routine's **ARTIFACT FORMAT CONTRACT v4**. It is fetched at RUN time, so an
edit here lands on the next fire with no prompt edit and no byte-drift risk. The checker
(`tools/check_premarket_artifact.py`) asserts everything below; a run that breaks the contract
FAILS instead of shipping.

#### 6.1 THE CONSTANTS — publish these, never change them silently

```
GAP_TRIGGER_PCT      = 4.0      # the gap bar        (unchanged since the routine was written)
MIN_PM_VOLUME_SHARES = 50_000   # the liquidity bar  (unchanged)
MIN_EXECUTED_SHARES  = 25       # the SIZE bar — the print that carries the gap must have
                                # size behind it. A 1-share print is a rounding artifact.
```

**A name is `FLAGGED` only when all three hold:**

```
|gap| >= GAP_TRIGGER_PCT   AND   pm_volume >= MIN_PM_VOLUME_SHARES   AND   exec_shares >= MIN_EXECUTED_SHARES
```

The 4% / 50,000 gate is NOT to be changed — on 2026-11-03 the same rule fired on three phantom
gappers (CAI +5.53% on 10 shares, CVI −6.99% on 1 share, MTZ +3.93% on a series of 1-share
prints). That is the rule working. `MIN_EXECUTED_SHARES` is an ADDITIONAL gate, not a
replacement: the gap must be confirmed by an executed print with size behind it.

#### 6.2 THE VERDICT — a fixed vocabulary, published as a field

A reader must not have to infer the verdict from two numbers and a caveat. Every row carries a
`verdict` from this closed set, and the markdown table carries it as a column.

| verdict | meaning |
|---|---|
| `FLAGGED` | clears the gate on the tape AND size — see 6.1 |
| `BORDERLINE_THIN` | the bar was printed, but the market behind it is too thin to act on (`exec_shares` below `MIN_EXECUTED_SHARES`, or `pm_volume` below `MIN_PM_VOLUME_SHARES`) |
| `BORDERLINE_TAPE_ONLY` | the live quote clears the bar but the executed tape does not — *above the bar on a quote, below it on the market* |
| `BORDERLINE_INTRADAY` | it crossed the bar during the pre-market session and is not there at the snapshot |
| `NO_PRINT` | no executed print at all — the quote is not a market |
| `BELOW` | printed, and below the bar on every reading |

**Precedence (the order IS the meaning):**

```
NO_PRINT  >  FLAGGED  >  BORDERLINE_THIN  >  BORDERLINE_TAPE_ONLY  >  BORDERLINE_INTRADAY  >  BELOW
```

- `NO_PRINT` comes first: a name that printed nothing cannot be a borderline anything.
- `BORDERLINE_THIN` before `BORDERLINE_TAPE_ONLY`: when the tape itself printed across the bar
  (even on a rounding artifact), that is the more concrete fact.
- `BORDERLINE_TAPE_ONLY` is the PURR case (2026-11-03) and it is the reason the vocabulary
  exists. Publish **both numbers** with it, never one:

  > on the consolidated tape (+3.07%) → below the gate · on the live quote (+4.43%) → above the
  > gate · pre-market high (+5.87% at 09:02 ET) → it DID cross intraday

  The third leg lives in `pm_high_gap_pct` / `pm_low_gap_pct`, so a `BORDERLINE_TAPE_ONLY` name
  still carries the intraday fact.

#### 6.3 THE DENOMINATOR RULE — and the `ref_close_source` column

**The gap denominator is the SETTLED prior regular-session close.** Take it from the prior
sweep's own `focus.csv` — the **latest dated `close_<YYYY-MM-DD>` column** (that is the sweep's
session close) — and cross-check it against **two other independent sources**. Two agreeing
sources beat one drifting one.

| source | role |
|---|---|
| the prior sweep's own `focus.csv` (`close_<date>` column) | **primary** — it is the same denominator the screen used |
| TradingView america scanner `close` | cross-check 1 |
| Cboe delayed-quote CDN `close` | cross-check 2 |
| the bridge `market-recap` `price` | cross-check 3 (excellent for this, useless for a pre-market print) |
| Nasdaq `/info` `secondaryData` | **LAST RESORT ONLY** — it drifts and flips (see 6.4) |

**Publish which sources agreed in `ref_close_source`**, e.g. `focus.csv+tradingview+cboe`. If a
source disagrees, say so in the same cell (`focus.csv+tradingview (CONFLICT: nasdaq-secondaryData
206.0000 vs 207.6000)`) and in `## Flags`. Never publish a gap computed against a price that was
not an executed print.

#### 6.4 KNOWN NASDAQ FIELD DEFECTS — CHECK THESE FIRST (found 2026-11-03)

Do not rediscover these. Check each one first on every fire.

1. **`/info` `secondaryData.lastSalePrice` is not always the settled close.** For **QLYS** it
   read **$206.00** while the settled close was **$207.60** — Nasdaq's own `/historical`, the
   TradingView scanner, the bridge and the sweep's own `focus.csv` all agreed on 207.60. Using
   206.00 would have moved QLYS's gap from +0.53% to −0.01%.
2. **The same field flips mid-session.** For **KOD** it read $97.625 at 08:34 and $98.5764 at
   09:07 — the latter is a stale *pre-market* print, not a close.
3. **`/info` `primaryData.lastSalePrice` can be a trivial-size print.** **CAI** read $33.8747
   (+5.53%) on a **10-share** print while the consolidated tape was $32.50 (+1.25%); **CVI**
   printed −6.99% on **1 share**; **MTZ** printed +3.93% on a series of **1-share** prints. The
   rule that catches all three: *a gap is only real if a print with size behind it crossed it.*
4. **`/info` `primaryData.lastSalePrice` can be the ASK, not a trade.** **PURR** read $10.14 with
   a $10.04 × $10.14 band while the tape's last executed print was $10.0083. When
   `last == ask`, the reading is a quote.
5. **The bridge's `market_state: "pre"` serves the PRIOR REGULAR CLOSE**, not a pre-market print
   (`as_of` = the 16:00 ET close). Use it to CONFIRM reference closes; never as a print source.
6. **The TradingView scanner's `premarket_volume` undercounts** (PURR 320,722 vs Nasdaq 595,761;
   NOW 253,343 vs 1,107,335) and `premarket_price` is null for every US name. Use
   `premarket_change` + `premarket_high` / `premarket_low`; never run the 50,000-share test on
   TV volume alone.

#### 6.5 THE STALE-CACHE DEFENCE — unchanged, and still required

`api.nasdaq.com`'s `/extended-trading` endpoint sits behind a **shared HTTP cache** that can
return a snapshot captured much earlier. Measured 2026-11-03: the **same URL** returned a
4.5-hour-old vintage (AAPL pre-market 05:33:19) alongside a current one (09:30:01) in the same
second, and MSFT / GOOGL alternated between 05:31-05:33 and 09:30:01 across rapid pulls.
Responses carry a `cache-hit` header, and a unique query string does **not** reliably bypass it.

Rules for this scan:

1. **Never trust a single tape pull.** Pull the endpoint N times (N >= 4) and keep the payload
   with the **newest internal timestamp** (the latest `tradeDetailTable` clock time, after
   sorting — the table is served newest-first). A stale vintage can never win a max-timestamp
   comparison.
2. **The published gap comes from the tape's last EXECUTED print**, never from the live quote.
   The live quote is published as a separate column (`quote_price`, `quote_gap_pct`) and it is
   what makes `BORDERLINE_TAPE_ONLY` visible.
3. **Prefer the Cboe delayed-quote CDN** as the independent price cross-check:
   `https://cdn.cboe.com/api/global/delayed_quotes/quotes/{SYM}.json` returns an explicit
   `last_trade_time` and `timestamp`, so its freshness is verifiable from the payload rather
   than inferred. It is not subject to the Nasdaq cache.
4. **Volume:** the `infoTable` cumulative counter can itself be faulty (ADT jumped 6,500 ->
   606,500 mid-session while its complete 71-row tape stayed at 6,726). The trade-detail table
   is capped at 100 rows, so **when `tape_n < 100` the tape is complete** and can arbitrate a
   contradictory counter. Prefer the tape sum and record the rejection in `pm_volume_source`.
5. **Take multiple snapshots across the run** (e.g. 08:46 / 08:52 / 08:57 / a paired 09:00
   pull). They serve as the liveness proof, the max-timestamp source, and the divergence record.

Because a stale vintage can move an individual name's gap by ~2.4pp, publish the margin against
the trigger: if the widest gap on any source is well inside the 4% band, the flag decision is
immune to the cache and should be stated as such.

#### 6.6 THE HELPER — run it, it is the reference implementation

`scripts/premarket_pull.py` implements the whole defence (N tape pulls + max-newest-timestamp,
the live `/info` price, the complete-tape volume arbitration, the Cboe and TradingView
cross-checks, the focus.csv join, the verdict and the contract CSV). Fetch it at RUN time and
require the capability marker — an OLD copy would write the OLD artifact shape:

```bash
mkdir -p /workspace/tools
S=/workspace/tools/premarket_pull.py
for U in \
  "https://api.github.com/repos/karizaco/maxhermes-migration/contents/cloud-prompts/skills/stock-screener-suite/scripts/premarket_pull.py?ref=main" \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/skills/stock-screener-suite/scripts/premarket_pull.py" \
  "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/skills/stock-screener-suite/scripts/premarket_pull.py" ; do
  curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" -o "$S.tmp" "$U" 2>/dev/null
  if [ -s "$S.tmp" ] && grep -q 'premarket-artifact-v4' "$S.tmp" 2>/dev/null; then
    mv -f "$S.tmp" "$S"; break
  fi
  rm -f "$S.tmp"
done
if [ ! -s "$S" ] || ! grep -q 'premarket-artifact-v4' "$S"; then
  echo "premarket_pull.py: UNAVAILABLE (no copy carrying the current contract)"
  echo "no artifact; no push"
  exit 1
fi

python3 "$S" --from-csv /workspace/<prior-sweep>/focus.csv \
    --out-dir /workspace/daily-screens/{date} --pulls 4 \
    --gap-trigger 4 --volume-floor 50000 --min-exec 25
```

It writes `_premarket-pull.json` (full per-symbol provenance), `premarket-pull.md` (a helper
table) and **`pre-market-gapper.csv` — the contract CSV, one row per Focus name**. It also
prints the **marker line** the artifact must carry (§6.7).

The prior sweep's `focus.csv` is the input that carries three things at once: the tickers, the
**reference close** (the latest dated `close_<date>` column) and the **screen provenance**
(`stylists`, `origins`) — the last one is what lets you say "CDNA, five origins and three
stylists" instead of dropping a high-quality setup that went nowhere. Fetch it from
`karizaco/minimax-cloud-outputs` `main`, `daily-screens/<prior-date>/focus.csv`.

If you re-implement the logic inline instead of running the helper, the artifact must carry
exactly the same fields — the checker verifies the artifact, not the route you took.

#### 6.7 ARTIFACT FORMAT CONTRACT v4

Two files, same directory: `daily-screens/<date>/pre-market-gapper.md` and
`daily-screens/<date>/pre-market-gapper.csv`. Never let a row exist in one and not the other.

**The marker line** — the first line of the markdown, or within the first 10:

```
_contract: premarket-artifact-v4 · flagged: N · scanned: M · gate: |gap|>=4.0% and pm_volume>=50,000 and exec_shares>=25 · reference close: <source>_
```

`flagged` and `scanned` MUST match the CSV. The checker asserts both.

**The markdown skeleton — these sections, in this order:**

```
# Pre-Market Gapper — <Weekday, DD Month YYYY>
<banner: 2 lines — the session, the snapshot time(s), the source of record>
## TL;DR
## Focus scan — all names
## Focus names that did not qualify
## Flags
## Method, source health & caveats
```

- **`<banner>`** — two lines, before anything else: the session and the snapshot clock times
  (ET) and the source of record. The tape moves; the reader needs to know how live it is.
- **`## TL;DR`** — 3 bullets: the headline count, the most consequential name, and the caveat
  that most changes how the run should be read.
- **`## Focus scan — all names`** — one table, one row per Focus name, **sorted by absolute
  gap, largest first**. Columns: `Ticker | Ref close | PM price (last executed print) | Gap % |
  PM volume | Exec shares | Exec notional | PM high | PM low | Quote % | Verdict`. The
  `Verdict` column is mandatory. `Exec shares` and `Exec notional` are mandatory — the reader
  must see *why* a name did not qualify, numerically.
- **`## Focus names that did not qualify`** — see 6.8.
- **`## Flags`** — see 6.9.
- **`## Method, source health & caveats`** — about the RUN, not about names: every source
  tried and its status, the denominator and which sources agreed on it, the margin against the
  trigger, the Nasdaq defects you checked, the snapshot timestamps, the provenance. **Data
  caveats live here** — never in `## Flags`.

**The CSV columns** (the contract set — keep these names):

```
ticker, ref_close, ref_close_source, pm_price, pm_gap_pct, exec_shares, exec_notional,
pm_volume, pm_volume_source, quote_price, quote_gap_pct, bid, ask, pm_high, pm_low,
pm_high_gap_pct, pm_low_gap_pct, tv_pm_pct, tv_pm_volume, stylists, origins, verdict, flag_reason
```

Every row carries a **non-empty** `verdict`, `exec_shares` and `ref_close_source`. `verdict` is
one of the six values in 6.2. `exec_shares` is the size of the print that carried the published
gap; `exec_notional` is `exec_shares × pm_price`. `flag_reason` is one plain sentence saying
why the row got that verdict.

#### 6.8 `## Focus names that did not qualify` — what was in the scan but did not make the list

**The rule:** every scanned name whose verdict is not `FLAGGED` appears in this section, with
its **gap**, its **PM volume**, its **PM range**, its **screen provenance**, and **one line
saying whether it was a good setup that went nowhere or a bad setup**.

This is the feedback that makes the screen learnable. On 2026-11-03 the scan's best setup did
nothing — **CDNA** (Stockbee 4% breakout + Qullamägi RS + EP + 5-day gainers + peoplewish —
five origins, three stylists) moved +0.90% pre-market, and HTFL / KOD / QLYS / MRNA / LQDA all
sat under ±1%. Five of those six appeared nowhere in the chat reply.

One line per name, in this shape:

```
- **CDNA** — +0.90% · 3,350 shares · $85.75–$86.41 · 3 stylists, 5 origins
  (A_stockbee_4pct, C_qullamaggie_rs, D_qullamaggie_ep, E_qullamaggie_5d_gainers, G_peoplewish)
  · setup: good setup that went nowhere — five origins and three stylists, and it never moved.
```

- **The provenance comes from the prior sweep's `focus.csv`** — `stylists` and `origins`. Do not
  invent it, and do not omit it: a name without provenance is a name without a story.
- **The setup verdict is mandatory.** A name without "was this a good setup that did not move,
  or a bad setup?" is not in this section, it is just a row in a table.
- The names in this section are ordered by **setup quality, then by size of the miss**:
  `stylists` desc, then `origins` count desc, then `|gap|` desc.

#### 6.9 `## Flags` vs `Method & caveats` — two different jobs

Do not merge them. A caveat is about **the data**; a flag is about **a number a reader should
distrust**.

- **`## Flags`** — per-name, and only per-name:
  - a gap printed on trivial size (**CAI +5.53% on 10 shares = a quote, not a market**) — every
    name whose `exec_shares` is below `MIN_EXECUTED_SHARES` and whose gap touched the bar MUST
    be named here;
  - a live quote above the bar while the tape is below it (the `BORDERLINE_TAPE_ONLY` case) —
    name the tape gap, the quote gap and the bid/ask band;
  - a name that crossed the bar intraday and faded — say the gap it faded from and to;
  - a reference close the sources did **not** agree on;
  - a percentage that is arithmetically distorted (a big gap on a tiny absolute volume).
- **`## Method, source health & caveats`** — about the run, not about names.

Every flag names a ticker and states the number that makes it suspect. "Some names may be thin"
is not a flag; "CAI +5.53% on 10 shares = a quote, not a market" is.

#### 6.10 REPLY DISCIPLINE for cron #08

The shared reply format from `_shared/PROMPT-BLOCKS.md` (`## DELIVERY`) applies — prose
opener, `### Signal`, `### Method & caveats`, `### Files`, `### Push / errors`. Three
routine-specific rules on top of it:

- **`### Signal` names the top 2 non-qualifying names** — the best setups that did not qualify,
  ordered as in 6.8. **This applies even when zero names flag.** The old rule ("emit no chat
  lines when 0 names flag") is superseded: a trader who tracks this list needs to know CDNA was
  a high-quality setup that went nowhere, and that is the feedback that makes the screen
  learnable. One line each, with the gap, the size and the setup verdict.
- **Every `FLAGGED` name gets its own line** in `### Signal`, with the catalyst or the setup —
  and never with a catalyst you did not source.
- **The verdict carries the line, not a paragraph.** `PURR +3.07% tape / +4.43% quote —
  BORDERLINE_TAPE_ONLY` is the shape. The tables live in the file; the chat carries the verdict,
  the risk and the counts.

#### 6.11 VERIFY THE ARTIFACT BEFORE YOU REPORT IT

```bash
C=/workspace/tools/check_premarket_artifact.py
for U in \
  "https://api.github.com/repos/karizaco/maxhermes-migration/contents/tools/check_premarket_artifact.py?ref=main" \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/tools/check_premarket_artifact.py" \
  "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/tools/check_premarket_artifact.py" ; do
  curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" -o "$C.tmp" "$U" 2>/dev/null
  if [ -s "$C.tmp" ] && head -5 "$C.tmp" | grep -q 'check_premarket_artifact.py'; then
    mv -f "$C.tmp" "$C"; break
  fi
  rm -f "$C.tmp"
done
python3 "$C" \
  --md  /workspace/daily-screens/{date}/pre-market-gapper.md \
  --csv /workspace/daily-screens/{date}/pre-market-gapper.csv \
  --reply /workspace/reply.txt
```

Save the final chat reply to `/workspace/reply.txt` before running the checker — the
`--reply` check asserts that the reply's `### Signal` section names the top 2 non-qualifying
names and every `FLAGGED` name.

**Both files ship.** `push_artifact.sh --out daily-screens` stages the whole output tree, so the
CSV is pushed with the markdown — but verify BOTH paths, because a companion CSV that never
lands starves the next fire's baseline:

```bash
sh /workspace/verify_delivery.sh --path daily-screens/{date}/pre-market-gapper.md  --branch main
sh /workspace/verify_delivery.sh --path daily-screens/{date}/pre-market-gapper.csv --branch main
```

It asserts the section skeleton and its order, the contract marker, the `flagged`/`scanned`
counts against the CSV, the required columns on every row, the verdict vocabulary, that
`count(FLAGGED)` equals the number of rows meeting the gate, that **no row below
`MIN_EXECUTED_SHARES` is counted as a flag**, that every non-qualifying name appears in
`## Focus names that did not qualify` with its provenance and a setup verdict, that every thin
print is named in `## Flags`, and the reply contract. It exits 1 and prints each failure. **If
it fails, fix the artifact and run it again — do not report a clean run over a failing check.**
Do not eyeball these things; the 2026-11-03 artifact looked fine and failed them.

#### 6.12 DO NOT

- **Do not change the 4% gap / 50,000-share gate.** On 2026-11-03 the same rule fired on three
  phantom gappers — that is the rule working.
- **Do not publish a gap computed against a price that was not an executed print.** The
  published gap comes from the tape's last executed print; the live quote is a separate column.
- **Do not wait on `preopen-feed/`** — it did not exist by 09:15 ET on 2026-11-03 and catalysts
  had to come from the wire. Check the directory, fall back to `web_search`, and **report the
  substitution** in `## Method, source health & caveats`.
- **Do not re-filter the universe to "common stock only" and do not filter on domicile.** A
  shibui seed using `country_iso='US' AND type='Common Stock'` dropped 178 names on 2026-10-30,
  including ARI (−63.9%), the largest mover of that day.
- **Do not drop a name because it did not qualify.** The names that did not move are the
  feedback; they go in `## Focus names that did not qualify` and two of them go in the reply.

### 7. Live intraday RVOL re-rank (Sun)

Weekdays at 09:45, 10:15, 10:45, 11:15 ET — of those, only 09:45 ET is a deployed cron
(`#07-focus-rvol-09:45`); the other slots are manual runs. For each Focus ticker:

- The data path, the metric and the artifact contract live in cron #07's own prompt
  (`cloud-prompts/cron-prompts/07-stock-screener-focus-rvol-09:45.md`, STEP 5-7). Follow it;
  do not re-implement the screen here. Note the MCP tool `mcp__tradingview-advanced__*` is NOT
  registered in the Cloud runtime - the live path is the TradingView public scanner plus the
  bridge, as the prompt specifies.
- Sort Focus list by the metric desc.
- Output `focus-rvol-snapshot.md` **and** `focus-rvol-snapshot.csv` (one row per ticker) and
  split into **RVOL Required** vs **Liquid** buckets (Sun's published tier split). The CSV is
  the NEXT fire's crossing baseline - a run that ships only the `.md` starves it. That is
  exactly what happened on 2026-11-03.
- **The thresholds are named constants, defined once in cron #07's prompt (STEP 6) and
  reproduced here - keep the two in sync:** `RVOL_REQUIRED_BUCKET = 1.5`,
  `RVOL_ALERT_THRESHOLD = 1.5`, `NEAR_MISS_FLOOR = 1.275`.
- **The alert rule, in one sentence:** an alert fires for a name whose `rvol_now` is at or above
  `RVOL_ALERT_THRESHOLD` AND whose `prev_session_rvol` is below `RVOL_ALERT_THRESHOLD` - the
  name crossed UP through the alert bar since the previous session's published reading. A level
  with no prior reading below the bar is NOT a crossing.
- **Publish the NEAR MISSES too:** a name is a near miss when `rvol_now >= NEAR_MISS_FLOOR` and
  `rvol_now < RVOL_ALERT_THRESHOLD`, with both its current and its prior value.
- **Publish the TREND, not just the level:** every name carries `rvol_now`, `rvol_prev`,
  `rvol_at_09_38` and `rvol_trend` (ACCELERATING / STABLE / DECELERATING).
- **Do NOT write "crosses from < 1 to > 3".** That was the old time-scaled projection metric
  (`rvol_projected_eod`), retired on 2026-11-04 in favour of the time-of-day-normalised
  `rvol_tod_normalised`; the numbers are not comparable and the 3x bar no longer exists.

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
- **It DOES have `general_info.ipo_date`** (recent US IPOs, verified live 2026-11-03) and
  **`ownership_stats.short_percent_float`** (a decimal fraction — 0.15 means 15%; ~92%
  populated; the table is a current snapshot with no `date` column, so it cannot be
  replayed for a past date). The Sunday IPO and high-short-float refreshes therefore run
  from shibui, not from Finviz — the old note that they needed Finviz was stale, and
  Finviz is Cloudflare-403 from the Cloud runtime anyway.
- It has **no `institutional_holders_count`**, but `ownership_stats.percent_institutions`
  is the better proxy for "held by ≥ 1,000 funds" that the old spec asked for.
- `fundamentals_derived_quarterly` has `eps_growth_yoy` / `revenue_growth_yoy`
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
