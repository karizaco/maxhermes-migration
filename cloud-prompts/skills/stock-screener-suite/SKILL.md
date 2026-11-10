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
lookback window, a missing `LIMIT`, a division without `NULLIF()`, date arithmetic on
a bare string literal, and — since 2026-11-05 — **a per-branch `LIMIT` smaller than the
outer cap (`L009`), which is the silent truncation that shipped twice**. `smoke_test.py`
additionally asserts that the linter still catches the historical defects (fixtures in
`scripts/testdata/`), so the guard cannot silently stop working.

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

**Batch 1 (slow, run in parallel):** the eight shibui sweep branches —
Bonde 4% breakout, EP9M, Anticipation (coil), Kullamägi RS leaders, Qullamägi EP,
Qullamägi 5-day gainers (parabolic short), Qullamägi 5-day losers (parabolic long),
and peoplewish ADR+velocity.

> **Fetch each branch ON ITS OWN. No branch may carry a `LIMIT` of its own.**
>
> The old shape was one `UNION ALL` per stylist group with a per-branch
> `LIMIT 50` / `30` / `60` inside each CTE. **That silently truncated every
> book** while the query still succeeded and every downstream count still
> looked plausible: the 2026-11-04 artifact published `A_stockbee_4pct 50` and
> `B_stockbee_ep9m 50`, which are the CAPS, not screen outcomes — the true
> passing counts that day were 233 and 236. The same defect shipped twice
> (2026-11-03, 2026-11-04) because nothing in the lint looked for it.
>
> The shape that works:
>
> 1. **One branch per query.** `scripts/screen.py emit-branch <branch> <date>`
>    emits it. The branch's filter is UNCAPED; the only `LIMIT` is the page
>    size, which is shibui's own 200-row ceiling.
> 2. **Every row carries `rows_passing`** — `COUNT(*) OVER ()` computed
>    INSIDE the branch, before any cap applies. It is the TRUE number of names
>    that passed that branch's filter, and it travels with the rows.
> 3. **Page it.** shibui returns at most 200 rows per query, so a branch whose
>    `rows_passing` is larger needs more pages:
>    `emit-branch <branch> <date> --offset 200`, `--offset 400`, … Keep going
>    until the rows collected equal `rows_passing`. The `ORDER BY` is always
>    total (the sort key plus `symbol`), so pages never overlap or drop a row.
> 4. **Assert.** `rows_kept == rows_passing` for every branch. When they
>    differ the book is INCOMPLETE and **must not be published** — see
>    §4 "The coverage assertion".
>
> A branch count that lands EXACTLY on 30 / 50 / 60 / 200 is a cap, not a
> screen outcome — that is the truncation fingerprint, and it must be reported
> as a failure, never as a result.

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

Output: `daily-screens/breadth/<YYYY-MM-DD>.md` plus `daily-screens/<date>/_regime.json`.

**The `_regime.json` schema is PINNED — one shape, one version. Do not re-invent it.**

```json
{
  "_schema": 2,
  "size_cut_pct": 50,     // when (index < 20-DMA) AND (breadth_pct < 40)
  "uncertainty": false,   // when vix_vix3m_ratio > 1
  "late_cycle": false,    // when any of the 5 index symbols is > 6% ABOVE its 50-DMA
  "breadth_pct_spx": 71.0,
  "index_below_20sma": true,
  "vix": 16.61,
  "vix3m": 18.8,
  "atr_extensions": {"QQQ": {"extension_pct": -4.37}}
}
```

- **FLAT.** The regime fields sit at the TOP LEVEL, next to `_schema` and
  `_note`. They are NEVER nested under a `regime` key.
- `_schema: 2` is the schema version and MUST be present.
- All eight regime keys MUST be present. A missing key is a failed run, not a
  default — `late_cycle` reading as `None` is indistinguishable from "not
  computed", which is exactly how the 2026-11-03 → 2026-11-04 break hid.

**The break that made this necessary:** on 2026-11-03 the payload was flat; on
2026-11-04 the same routine wrote it nested (`{"regime": {\u2026}}`). Every
consumer doing `d.get("late_cycle")` then read `None` instead of a boolean —
a silent contract break in the file the suite spec calls "the file downstream
routines should read", and the 2026-11-04 artifact's own `breadth.md` even
published the flat shape in its code block while the JSON on disk was nested.
`scripts/screen.py` validates the payload against the declared schema BEFORE
writing it, and `read_regime()` unwraps a legacy nested file so a consumer
never sees `None` where a regime field belongs.

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

#### ⚠ The `late_cycle` key trap — the flag that could never fire

`emit_breadth_sql()` selects the index identifier into a column named **`ticker`**:

```sql
SELECT 'index_atr_extension', ticker, close, sma_20, sma_50, atr_14, atr_252d_avg, ...
```

A consumer that reads only `row.get("symbol")` therefore gets an **empty** extension map, and
`late_cycle` — computed as `any(...)` over that empty map — is **always False**. It fails
silently and looks plausible on every single run.

**The rule:** read the key the PRODUCER emits, and read every alias the consumer accepts:
`row.get("symbol") or row.get("ticker") or row.get("etf")`. `scripts/screen.py::compute_regime()`
already does this, and `scripts/smoke_test.py` asserts that `late_cycle` CAN be `True` (a flag
that can only ever be `false` is not a flag).

**The runtime guard:** whenever the five index-ETF rows are present, `atr_extensions` MUST be
non-empty. An empty map is a failed run, not a quiet tape — publish it as
`probe_failed:atr_extensions_empty` and say so, rather than shipping `late_cycle = false`
as if it had been computed.

### 3.5. Breadth snapshot artifact contract (cron #10) — v1

**Scope: cron #10 only** — the 14:00 ET intraday read, `daily-screens/<date>/breadth-snapshot.md`.
Cron #09's `breadth.md` is the END-OF-DAY read and is **not** covered by this section; it keeps
its own shape. This section is fetched at RUN time, so an edit here lands on the next fire with
**no prompt edit and no byte-drift risk**. The checker (`tools/check_breadth_artifact.py`)
asserts everything below; a run that breaks the contract FAILS instead of shipping.

#### 3.5.1 WHAT THE 2026-11-03 ARTIFACT GOT WRONG — why this section exists

1. **No advance/decline tally.** The run disclosed the gap honestly ("No live advance/decline
   tally exists on any reachable feed") — but that is not true. The closes are already in the
   universe this routine scans, and the tally is one `LAG()` self-join away. This is the
   single most-watched breadth number in existence and the routine could not produce it.
2. **A level with no context.** "65.19% of the 902 large caps are above their 20-DMA" is
   unremarkable in one regime and alarming in another. A percentile fixes it.
3. **The divergence was buried in a bullet.** The run's genuinely new finding — the broad
   market healthy while the index posture stayed weak — is the highest-value output of a
   breadth read and it changes position sizing. It is now a named, first-class metric.
4. **The regime flags were one concatenated string** in the front matter, so comparing two
   days meant parsing prose.
5. **No TL;DR.**

#### 3.5.2 THE FILES AND THE MARKER

Four files, same directory:

| file | what it is |
|---|---|
| `breadth-snapshot.md` | the artifact |
| `breadth-snapshot.csv` | the contract CSV — one row per session, trailing window |
| `breadth-snapshot.json` | every computed metric + provenance (machine-readable) |
| `_regime-intraday.json` | the regime payload, **flat** schema v2 (cron #10 owns this name; cron #09 owns `_regime.json`) |

**The marker** — in the front matter (`contract: breadth-artifact-v1`) AND on the marker line
just under it:

```
_contract: breadth-artifact-v1 · data_date 2026-11-04 · universe 909 names · breadth 69.42% (pctile 94.3 · ABOVE_NORMAL) · divergence +29.42 pp (BROAD) · AD 658/250/1_
```

#### 3.5.3 THE HELPER — run it, it is the reference implementation

`scripts/breadth_metrics.py` computes the whole settled layer, writes the CSV, the metrics JSON
and the regime sidecar, and renders the contract-shaped markdown. **Fetch it at RUN time and
require the capability marker** — an OLD copy would write the OLD artifact shape, and the
checker would then fail the run for no visible reason:

```bash
mkdir -p /workspace/tools
S=/workspace/tools/breadth_metrics.py
for U in \
  "https://api.github.com/repos/karizaco/maxhermes-migration/contents/cloud-prompts/skills/stock-screener-suite/scripts/breadth_metrics.py?ref=main" \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/skills/stock-screener-suite/scripts/breadth_metrics.py" \
  "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/skills/stock-screener-suite/scripts/breadth_metrics.py" ; do
  curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" \
    -H "Authorization: Bearer ${GITHUB_TOKEN}" -o "$S.tmp" "$U" 2>/dev/null
  if [ -s "$S.tmp" ] && grep -q 'breadth-artifact-v1' "$S.tmp" 2>/dev/null; then
    mv -f "$S.tmp" "$S"; break
  fi
  rm -f "$S.tmp"
done
if [ ! -s "$S" ] || ! grep -q 'breadth-artifact-v1' "$S"; then
  echo "breadth_metrics.py: UNAVAILABLE (no copy carrying the current contract)"
  echo "no artifact; no push"
  exit 1
fi
```

Then fetch the live tape (Cboe delayed-quote CDN for the volatility pair and the index levels,
the `market-recap` bridge for the ETF tape), write the live-layer JSON, and run the helper ONCE
— it computes the settled metrics, writes the CSV / JSON / regime sidecar, and renders the
markdown:

```bash
python3 "$S" --date "$FIRE_DATE" --out-dir /workspace/daily-screens/$FIRE_DATE \
    --bridge /workspace/mcp_bridge.py \
    --render-md /workspace/daily-screens/$FIRE_DATE/breadth-snapshot.md \
    --live-json /workspace/live.json
```

The live-layer JSON carries the keys the renderer cannot know: `fire_time_et`, `live_date`,
`vix_quote_time`, `vix_pair`, `banner`, `tldr`, `tape_block`, `volatility_block`, `flags_block`,
`method_block`. **Any key you do not supply is rendered as a `<!-- FILL: ... -->` marker, and the
checker REJECTS an artifact that still carries one.** A stub cannot ship.

**If you re-implement the logic inline instead of running the helper, the artifact must carry
exactly the same fields — the checker verifies the artifact, not the route you took.**

#### 3.5.4 THE UNIVERSE — one population, and it is NOT frozen

```
NYSE/NASDAQ/AMEX · market cap > $10B · market_cap from the LATEST `valuation` row
```

- **The universe is NOT frozen.** The market-cap floor is applied to the latest `valuation` row,
  so the count moves as those rows refresh (904 → 902 → 905 → 909 across four sessions in
  November 2026). **Publish the count every run and say so when it moves.**
- **Do NOT change the universe** (venue list, $10B floor). Changing it makes the series
  non-comparable.
- **The advance/decline tally uses the SAME population as the breadth percentage** — the
  indicator-joined large-cap set, so `advancing + declining + unchanged` equals the published
  universe count. A quote-only universe is a DIFFERENT population (it runs ~4-7 names larger,
  because names without an indicator row that session are still trading) and mixing the two
  denominators in one artifact is exactly the kind of thing a reader cannot see.

#### 3.5.5 THE METRICS — definitions, bands, and what they mean

**`breadth_pct`** — % of the universe above its own 20-DMA, on the settled session.
**`breadth_pctile_1y`** — that level's rank in its own trailing 1-year distribution:
`100 × (sessions at or below the current value) ÷ sessions in the window`. **0..100, always.**
**`breadth_pct_band`** — `ABOVE_NORMAL` (pctile ≥ 80) · `NORMAL` (20 < pctile < 80) ·
`BELOW_NORMAL` (pctile ≤ 20). The same percentile and band apply to the 50-DMA split
(`breadth_pctile_1y_50dma`) and to the index-ETF count.

**The advance/decline family** — computed from `stock_quotes` with a `LAG()` self-join over the
same universe:

| field | meaning |
|---|---|
| `advancing` / `declining` / `unchanged` | the settled session's counts |
| `ad_ratio` | advancing ÷ declining |
| `ad_net` | advancing − declining |
| `ad_net_10d` | the net advances summed over the last 10 sessions (the ADL's CHANGE) |
| `adl_slope_10d` | the OLS slope of the cumulative ADL over the last 10 sessions, in **net advances per session** |
| `ad_ratio_10d` | Σ advancing ÷ Σ declining over the last 10 sessions |

The ADL is a LEVEL (cumulative net advances since `adl_base_date`, the first session of the
A/D series — ~60 sessions back, so the base is meaningful and not arbitrary) and the slope is
the RATE. Publish both, and publish the base date. A slope needs a FULL 10-session window: a
2-point slope off the start of the series is noise, and it is published blank instead.

**`breadth_divergence`** — the large-cap universe's share above its own 20-DMA **minus** the
index ETFs' share above their own 20-DMA, in percentage points:

```
breadth_divergence_pp = breadth_pct_above_sma_20_largecap − (index ETFs above their 20-DMA ÷ 5 × 100)
```

| band | condition | what it means |
|---|---|---|
| `BROAD` | ≥ +15 pp | the average large cap is materially healthier than the index — participation is broader than the headline index, and the index's own posture is the weak leg |
| `MATCHED` | −15 pp < x < +15 pp | the broad universe and the index ETFs agree |
| `NARROW` | ≤ −15 pp | the index is healthier than the average large cap — the cap-weighted index is carried by its biggest names while the average stock is not participating |

**Publish the last 5 sessions of the divergence** so the reader can see whether it is widening
or closing, and publish its own 1-year percentile.

> **A sign error to not repeat.** The 2026-11-03 artifact described a POSITIVE divergence
> (broad healthy, index weak) as "the signature of a megacap-led advance". It is the opposite:
> when the cap-weighted index is BELOW its 20-DMA while the broad universe is above it, the
> mega-caps are the WEAK leg. A positive divergence means the average stock is healthier than
> the index. The `NARROW` band is the "the index is carried by a handful of megacaps" case.

**The volatility pair** — ONE VIX/VIX3M pair, used everywhere, with its quote time and its
source. The Cboe CDN's field semantics depend on the clock: during regular hours
`close == current_price` (the live trade); **before 09:30 ET there is no live VIX print at all
and the CDN serves the PRIOR session's settle** — and it has been seen serving a transient
value for it minutes after the close (16.89 for a session that settled at 16.61). So the pair
is pulled **twice**, and a disagreement is published as `vix_stable: false` and flagged, rather
than hidden behind one number.

#### 3.5.6 THE FRONT MATTER — structured, never a concatenated string

```yaml
---
artifact: breadth-snapshot
contract: breadth-artifact-v1
cron: "#10 stock-screener-breadth-snapshot"
fire_time_et: "2026-11-05 14:00:54 ET"
data_date: "2026-11-04"          # the SETTLED session the breadth numbers describe
live_date: "2026-11-05"          # the LIVE tape session — a SEPARATE field, never blended
breadth_universe: "NYSE/NASDAQ/AMEX, market cap > $10B, 909 names"
vix_quote_time: "2026-11-05 13:49:31 ET (Cboe delayed-quote CDN)"
vix_pair: "VIX 16.61 / VIX3M 18.80 — single pair, used everywhere in this document"
cross_reference: "end-of-day counterpart: daily-screens/2026-11-04/breadth.md (cron #09, 18:30 ET)"
size_cut_pct: 0                  # STRUCTURED fields — one per line, machine-readable
uncertainty: false
late_cycle: false
---
```

**`data_date` and `live_date` are separate fields, and they are usually different.** The
breadth numbers are the SETTLED session (shibui is T+1); the tape and the volatility pair are
LIVE. Never blend them into one number, and never collapse the regime flags into one string —
`regime: "size_cut 0% · uncertainty false · late_cycle false"` is the shape this contract
replaces. The three flags are flat fields with the SAME names the `_regime-intraday.json`
payload uses, so a consumer can compare two days without parsing prose.

#### 3.5.7 THE MARKDOWN SKELETON — these sections, in this order

```
# Breadth & Regime Snapshot — <Weekday, DD Month YYYY> (intraday, cron #10)
<banner — the session, the snapshot clock, the source of record>
## TL;DR
## Breadth — <data_date> settled session (shibui)
## Participation — advance/decline and the 10-session ADL
## Breadth percentile — where today's level sits in its own history
## Breadth divergence — broad market versus index ETFs
## Index positioning — distance from the 50-DMA
## Live tape — <live_date>
## Volatility — single pair, live
## Regime
## Flags
## Method, source health & caveats
```

- **`## TL;DR`** — **exactly 3 bullets**: what breadth did · the one most important divergence ·
  the caveat that changes how to read it.
- **`## Breadth`** — the headline table. **The advance/decline counts live in THIS table**, in
  the first screen, not in a caveat. If a run ever falls back to the RSP-vs-SPY spread instead
  of a real tally, it is a **cap-weight participation proxy, not an advance/decline tally** and
  the table must say so in the same row.
- **`## Participation`** — the per-session advance/decline table and the ADL.
- **`## Breadth percentile`** — the percentile rows. The field names are mandatory:
  `breadth_pct`, `breadth_pctile_1y`, `breadth_pct_50dma`, `breadth_pctile_1y_50dma`,
  `index_etfs_above_20dma`.
- **`## Breadth divergence`** — the `breadth_divergence` row (value in **pp**, band, percentile)
  and the last 5 dated sessions.
- **`## Flags`** — per-SYMBOL suspect numbers: a reading that is arithmetically distorted, a
  source that disagreed with itself, an unstable volatility print. "Some data may be thin" is
  not a flag; "SPY's 20-DMA is 2.1% below its close while the tape says otherwise — flagging"
  is. Data-path caveats do NOT go here.
- **`## Method, source health & caveats`** — about the RUN: every source tried and its status,
  the universe and its drift, the settled-vs-live split, the percentile windows, the
  `atr_extensions` note, and any degraded probe (`probe_failed:<reason>`).

#### 3.5.8 THE CSV — one row per session

```
date, n_lc, pct_above_sma_20, pct_above_sma_50, n_etf_above_sma_20, n_etf_above_sma_50,
breadth_divergence_pp, advancing, declining, unchanged, ad_net, adl_cum, adl_slope_10d,
breadth_pctile_1y, divergence_pctile_1y, is_data_date
```

The trailing window (30 sessions by default). **Exactly one row carries `is_data_date=yes`** —
the settled session the artifact describes. The percentile columns are expanding (against every
session from the start of the window to that row).

#### 3.5.9 VERIFY THE ARTIFACT BEFORE YOU REPORT IT

```bash
C=/workspace/tools/check_breadth_artifact.py
for U in \
  "https://api.github.com/repos/karizaco/maxhermes-migration/contents/tools/check_breadth_artifact.py?ref=main" \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/tools/check_breadth_artifact.py" \
  "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/tools/check_breadth_artifact.py" ; do
  curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" \
    -H "Authorization: Bearer ${GITHUB_TOKEN}" -o "$C.tmp" "$U" 2>/dev/null
  if [ -s "$C.tmp" ] && head -5 "$C.tmp" | grep -q 'check_breadth_artifact.py'; then
    mv -f "$C.tmp" "$C"; break
  fi
  rm -f "$C.tmp"
done
python3 "$C" \
  --md     /workspace/daily-screens/$FIRE_DATE/breadth-snapshot.md \
  --csv    /workspace/daily-screens/$FIRE_DATE/breadth-snapshot.csv \
  --json   /workspace/daily-screens/$FIRE_DATE/breadth-snapshot.json \
  --regime /workspace/daily-screens/$FIRE_DATE/_regime-intraday.json \
  --reply  /workspace/reply.txt
```

Save the final chat reply to `/workspace/reply.txt` before running the checker — the `--reply`
check asserts that the reply's `### Signal` names the divergence and the advance/decline tally.

It asserts the section skeleton and its order, the contract marker, the **structured** regime
fields (and that no concatenated `regime:` string is present), the TL;DR's 3 bullets, the
advance/decline row in the headline table, `breadth_pctile_1y` inside 0..100 with its band,
`breadth_divergence` with its band and its 5-session history, the CSV's columns and its
agreement with the markdown, the regime payload's flat schema and its **non-empty**
`atr_extensions`, and the reply contract. It exits 1 and prints each failure. **If it fails,
fix the artifact and run it again — do not report a clean run over a failing check.** Do not
eyeball these things; the 2026-11-03 artifact looked fine and failed them.

**All four files ship.** `push_artifact.sh --out daily-screens` stages the whole output tree, so
the CSV and the JSON land with the markdown — but verify **every** path, because a companion
file that never lands starves the next fire's baseline:

```bash
for F in breadth-snapshot.md breadth-snapshot.csv breadth-snapshot.json _regime-intraday.json; do
  sh /workspace/verify_delivery.sh --path "daily-screens/$FIRE_DATE/$F" --branch main
done
```

**One push invocation, and `--add` the MARKDOWN path.** `push_artifact.sh` derives the routine
number from the `--add` path via its own table: `daily-screens/*/breadth-snapshot.md` → `NN=10`.
Adding the sidecars as extra `--add` flags is not needed (the whole tree is staged) and a path
that matches no row produces a commit subject with **no routine number**, which cron #90's
triage then reads as MISSING. Do not run the push once per file — that is the commit-storm
shape the auditor flags.

#### 3.5.10 THE REPLY

The shared reply format from `_shared/PROMPT-BLOCKS.md` (`## DELIVERY`) applies, plus:

- **`### Signal` names the divergence** — the metric that changes position sizing gets its own
  line, with the value, the band and what the band MEANS (not the direction of the spread
  alone).
- **`### Signal` names the advance/decline tally** — the counts and the ratio.
- **Never publish a live A/D figure you did not compute.** `probe_failed:<reason>` is correct;
  a fabricated tally is not.

#### 3.5.11 DO NOT

- **Do not blend the settled breadth with the live tape.** Two fields, two sections, two labels.
- **Do not change the universe.** (3.5.4)
- **Do not claim a live A/D figure if you did not compute it.** (3.5.10)
- **Do not publish a level without its percentile**, or a divergence without its band.
- **Do not collapse the regime flags into one string**, and do not ship an empty
  `atr_extensions` as a quiet `late_cycle = false`. (3.5.4 / the `late_cycle` key trap above)
- **Do not skip the checker.** An unchecked artifact is a claim, not a deliverable.

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
- `daily-screens/<date>/tier-a-fresh.md`      — Tier-A names that are NOT extended (the extension label, §4.6)
- `daily-screens/<date>/tier-a-extended.md`   — Tier-A names that ARE extended (published, never dropped)
- `daily-screens/<date>/_summary.md`          — human-readable digest
- `daily-screens/<date>/_regime.json`         — breadth/regime payload
- `daily-screens/<date>/_results.json`        — **machine-readable** companion: every candidate with its
                                               origins, stylist buckets, skip flags and metrics, plus the tier
                                               lists, the regime, and the counts. Downstream routines read
                                               this instead of re-parsing Markdown. It also carries
                                               `screen_coverage` — the per-branch `rows_passing` /
                                               `rows_kept` table — so a truncated book is visible to any
                                               consumer, not just to the run that produced it.
                                               **Since 2026-11-10 it also carries, per candidate,
                                               `data_as_of` and `source`** (`fresh` / `t1` / `fresh+t1`),
                                               the `fresh_origins`, the `extension` label and the
                                               `quality` verdict — so a consumer can never mistake a
                                               previous-session metric for today's, and the file
                                               publishes `fresh_data_as_of`, `t1_data_as_of`,
                                               `tier_a_fresh`, `tier_a_extended` and
                                               `fresh_branches` (the fresh book's own coverage table).
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

#### Three traps when the tiering is re-implemented inline (the Cloud runtime does not execute scripts/screen.py)

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
- **A per-branch `LIMIT` is a silent truncation.** See §2: no branch may carry its own
  `LIMIT`, every row must carry `rows_passing`, and every branch must be paged until the
  rows collected equal `rows_passing`. A book that was cut at 50 or 30 is not a small book
  — it is a wrong one, and it looks entirely plausible.

#### The coverage assertion — `rows_kept == rows_passing`, or the run fails

This is the guard that makes the truncation impossible to ship. It is cheap and it is
mandatory.

**For every branch, publish `rows_passing` and `rows_kept`:**

| Field | Meaning |
|---|---|
| `rows_passing` | The number of names that passed THAT branch's filter. Carried on every row as `COUNT(*) OVER ()` computed inside the branch, before any cap applies. |
| `rows_kept` | The number of rows for that branch actually published. |

- **`rows_kept` MUST equal `rows_passing` for every branch.** When they differ the book is
  INCOMPLETE: **fail loudly, do not publish it.** Re-fetch the short branch, page it until
  the counts agree, and rebuild.
- **A branch count that lands exactly on 30 / 50 / 60 / 200 is a CAP, not a result.**
  That is the truncation fingerprint — report it as a failure even if `rows_passing`
  happens to agree.
- **Publish the counts in `_results.json`** (under `screen_coverage`) **and in the
  artifact's method section.** A coverage table the reader cannot see is not a guard.

When the run genuinely cannot complete a branch, say so in the artifact — "branch
`A_stockbee_4pct`: 233 passed, 200 retrieved (shibui's per-query ceiling), 33 names not
published" — and mark the sweep INCOMPLETE. A truncated book presented as a complete
one is the worst outcome available.

### 4.5 The FRESH book — the cron day's OWN settled bar (cron #09)

**Why this section exists.** shibui is T+1, so at the 18:30 ET fire its newest
settled session is the PREVIOUS session. The 2026-11-09 run published a book
whose every screen metric described **2026-11-06** while the artifact was read
as "today's screen", and the freshness was a caveat sentence rather than a
field. Measured cost of that gap: running the same 4%-breakout + 2x-volume
gate on the 2026-11-09 settled bar returned **68 names, of which 25 were
absent from the published book entirely** (TLS +48.8%, DCTH +35.8%, LINC
+24.6%, UAMY +23.0%, INDI +21.6%).

**The rule: the TRIGGER branches are computed on the cron day's settled bar.**
The multi-session CONTEXT branches (5-day gainers/losers, 14-day velocity, the
coil, the 252-session RS window) stay on shibui and stay labelled T+1. A
trigger is "something happened today"; a context branch is "the name has been
doing this for a week", and one session of lag on a week-long construct is a
different problem from a one-session lag on today's trigger.

#### 4.5.1 The engine

```bash
# --- fetch the engine (run-time fetch: fixes land with no redeploy) ---
mkdir -p /workspace/tools
E=/workspace/tools/daily_sweep_engines.py
for U in \
  "https://api.github.com/repos/karizaco/maxhermes-migration/contents/tools/daily_sweep_engines.py?ref=main" \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/tools/daily_sweep_engines.py" \
  "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/tools/daily_sweep_engines.py" ; do
  curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" \
    -H "Authorization: Bearer ${GITHUB_TOKEN}" -o "$E.tmp" "$U" 2>/dev/null
  if [ -s "$E.tmp" ] && grep -q 'DAILY_SWEEP_ENGINES_V1' "$E.tmp" 2>/dev/null; then
    mv -f "$E.tmp" "$E"; break
  fi
  rm -f "$E.tmp"
done
if [ ! -s "$E" ] || ! grep -q 'DAILY_SWEEP_ENGINES_V1' "$E"; then
  echo "daily_sweep_engines.py: UNAVAILABLE (no copy carrying the current contract)"
  echo "fall back to the shibui-only book, label every row data_as_of=<shibui date>, and say so"
fi

# --- the fresh book + the extension metrics ---
python3 "$E" tv-sweep --date <CRON_DATE> --out /workspace/scratch/tv_sweep.json
python3 "$E" selftest          # offline; must be green before the book is published
```

The engine's output carries the universe (with `totalCount` asserted against
the rows fetched — a truncated scan is a FAILURE, never a shorter book), the
per-branch `rows_passing`, the per-symbol extension metrics, and the gates it
applied. **Publish the gates in the artifact** — they are part of the contract.

#### 4.5.2 THE FRESH GATES — published, not copied

| Branch | Gate | Relation to the shibui gate |
|---|---|---|
| `A_tv_breakout_4pct` | change ≥ 4%, close ≥ $3, session volume > the prior-NINE-session mean, avg volume ≥ 100k | **VARIANT**: shibui's gate is "volume > prev_session"; the scanner publishes no prior-session volume, so the expansion test is against the prior-nine mean — STRICTER, and published as its own gate |
| `B_tv_ep9m` | session volume ≥ 8,900,000 SHARES, close ≥ $3, avg volume ≥ 100k | exact mirror |
| `D_tv_gap_10pct` | open/prev_close ≥ +10%, prior-nine-session average dollar volume ≥ $50M, close ≥ $3 | **VARIANT**: the $50M floor is measured on the prior-nine-session mean dollar volume, because the scanner publishes no 20-day ADV |
| `TV_volume_breakout` | change ≥ 3%, relative volume ≥ 1.5 | unchanged from the suite's existing screen |

#### 4.5.3 WHY `Perf.W` IS NOT USED AS THE 5-SESSION MOVE

Measured 2026-11-09 against shibui's own history on 11 names: TradingView's
`Perf.W` correlates **r=0.997 (mean abs error 1.31 pp) with a SIX-session move**
and only r=0.924 (6.85 pp) with a five-session move. The parabolic gates
(+25% / −25% / −50% over five sessions) are therefore **NOT** re-expressed on
`Perf.W`: they stay on shibui and stay labelled T+1. Copying them onto a
six-session window would silently shift the parabolic books, which is the same
class of defect as the per-branch `LIMIT`.

**What IS reconstructed exactly:** the scanner's `average_volume_10d_calc` is
the mean of the last ten sessions **including today** (bias 0.00% against a
hand-computed reference on 11 names), so the prior-nine-session baseline is
recovered as `(10 × avg10 − volume_today) / 9` with no second data source.

#### 4.5.4 The dual book

Both books are published, and **every row carries `data_as_of` and `source`**:

| `source` | meaning |
|---|---|
| `fresh` | the cron day's settled bar only |
| `t1` | shibui's newest ingested session only (a context-branch name) |
| `fresh+t1` | both books carry the name |

The T+1 book is the **cross-check**, not the headline. The fresh book is
primary. When they disagree, the artifact says so with both lists — it never
substitutes one for the other.

#### 4.5.5 The run order for cron #09

1. `tv-sweep` → the fresh book + extension metrics (no auth, no rate limit).
2. The 8 shibui branches as before (the context branches + the T+1 cross-check).
3. The CANSLIM rebuild on shibui — **the growth inputs are quarterly, so T+1
   never applied to them**; only the price half was stale, and that is now
   fresh.
4. The overlay (§4.7) over the candidate symbols.
5. `screen.py consume --fresh-book ... --overlay ...` → the tiered book.

```bash
python3 scripts/screen.py consume \
  --in /workspace/scratch/results.json --date <CRON_DATE> --vault <vault> \
  --fresh-book /workspace/scratch/tv_sweep.json \
  --overlay     /workspace/scratch/overlay.json
```

### 4.6 The extension label — which names are ALREADY EXTENDED

The tiering has **no extension filter**, so Tier-A is structurally biased
toward names that have already run: six of the eight branches are momentum /
breakout / velocity screens, and "≥ 3 stylists agree" selects for maximum
agreement among them. Measured on the 2026-11-09 book: FLY +34.0% above its
20-DMA with ATR 8.03%, RHLD RSI 80.7, ARRY +33.8% above its 20-DMA.

**The label is published on every row. Nothing is ever dropped from the book
because it trips a rule** — dropping information is what made the parabolic
branch's own label read as a forward-looking signal when it is a state
detector.

| Rule | Threshold | Note |
|---|---|---|
| `atr_pct` | ATR / close > 5.0% | fires on 15.8% of the $10B+ names but on 36.0% of the $1–10B names — so the **percentile is published next to it** (`atr_pct_pctile`, and `atr_pct_pctile_lc` against the $10B+ sub-universe) |
| `rsi` | RSI > 75 | fires on ~3% of the universe |
| `pct_above_sma20` | > 15% above its own 20-DMA | fires on ~7% of the universe, 2.3% of the $10B+ names |
| `up_days_streak` | 3+ consecutive up sessions | from the shibui history, extended by the fresh session |

**Tier-A is published TWICE**: `tier-a-fresh.md` (not extended) and
`tier-a-extended.md` (extended), alongside the full `tier-a.md`. On the
2026-11-09 book that split was **0 fresh / 6 extended** — the whole Tier-A
list was extended, which is the honest answer to "why do these names always
look like they have already run".

### 4.7 The valuation / quality overlay (cron #09)

**The gap it closes.** The CANSLIM screen asks for growth and strength and
nothing else. It has never asked what the multiple is, because `shibui.valuation`
carries only `market_cap`, `price_to_book` and `enterprise_value` — no P/E at
all. But `shibui.fundamentals_derived_daily` carries `trailing_pe`,
`operating_pe`, `ev_ebit`, `price_to_sales`, `free_cash_flow_yield`,
`trailing_revenue_peg` and `earnings_quality_flags`, and the suite never
joined a table it already pays for. On 2026-11-09 KRMN carried **trailing P/E
120.6, operating P/E 55.8, EV/EBIT 62.7, FCF yield −0.12%, PEG 1.84,
debt/equity 2.28 and a `LOW_EARNINGS_QUALITY` flag** — and the book published
it with a `+` next to its name.

#### 4.7.1 The red flags

| Flag | Rule |
|---|---|
| `trailing_pe` | trailing P/E > 50 |
| `operating_pe` | operating P/E > 40 |
| `trailing_revenue_peg` | PEG > 3 (at 2 it fired on AAPL and did **not** catch KRMN — a rule that misses its own case is not a rule) |
| `free_cash_flow_yield` | negative free cash flow |
| `debt_to_equity` | > 1.5 |
| `earnings_quality_flags` | shibui's own flag list |

#### 4.7.2 A MISSING value is a DISCLOSURE, not a flag

A name with no trailing P/E is published as `earnings_data_missing: true` with
`valuation_gate: unknown` — **never a silent pass, and never counted as a red
flag**. Measured 2026-11-09: counting a null P/E as a red flag flagged 910 of
1,232 names (73%). A label that fires on three quarters of the book is as
useless as one that never fires.

`valuation_gate` is therefore one of:

| gate | meaning |
|---|---|
| `pass` | no red flag, and earnings data present |
| `unknown` | no red flag, but no trailing earnings either — **disclosed, not cleared** |
| `fail` | at least one red flag |

`quality_severity` is `clean` (0 flags) / `watch` (1) / `flagged` (2+).

#### 4.7.3 The run

```bash
python3 "$E" overlay --date <CRON_DATE> --t1-date <shibui date> \
  --symbols /workspace/scratch/book_symbols.txt \
  --out /workspace/scratch/overlay.json \
  --bridge /workspace/mcp_bridge.py --tv-json /workspace/scratch/tv_sweep.json
```

One shibui call per 200 symbols (the overlay joins the fundamentals and the
streak server-side so the result is one row per symbol). The overlay is
published per name in the artifact's table with the VALUES next to the flags —
a flag without its number is not actionable.

**The overlay is a LABEL, not a filter.** It never removes a name from the
book; it tells the reader that the growth screen says nothing about what the
price already assumes.

### 5. 3:55 PM ET Reversal Bullish (Bonde)

**Windows-safe basename:** artifact files are `reversal-bullish-3_55.{md,csv}` (underscore, never `:`). Historical outputs may still use `3:55`; readers and auditors accept both during transition. `push_artifact.sh` rewrites any illegal basename before commit.

Only run on weekdays between 15:30 and 16:00 ET. Output: `daily-screens/<cron_date>/reversal-bullish-3_55.{md,csv}` with the candidates that pass **all** of Pradeep Bonde's published criteria.

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
`reversal-bullish-3_55.{md,csv}` into the dated directory and prints a JSON report. **Read that
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
  --md /workspace/daily-screens/{date}/reversal-bullish-3_55.md \
  --csv /workspace/daily-screens/{date}/reversal-bullish-3_55.csv
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
sweep's own `focus.csv` — **the close column whose DATE is the denominator session** — and
cross-check it against **two other independent sources**. Two agreeing sources beat one drifting
one.

> **The close column is chosen BY DATE, never by name.** The sweep's CSV has carried TWO close
> columns since 2026-11-04:
>
> | column | what it is | valid denominator? |
> |---|---|---|
> | `today_close` | the sweep's OWN session close | **yes**, when the sweep's session IS the denominator session |
> | `close_<YYYY-MM-DD>` | that exact session (the pre-2026-11-04 schema) | **yes**, when the date matches |
> | `screen_close_resolved` | the screen's **T+1 data date** — the PREVIOUS session (shibui is a day behind) | **NEVER** |
>
> Picking `screen_close_resolved` shifts the gap by up to 10%: on the 2026-11-06 sweep APP carried
> `screen_close_resolved` 356.10 and `today_close` 391.22 — a 9.9pp error on one name. The
> pre-2026-11-04 helper looked only for `close_<date>` columns and for `prior_close` / `close` /
> `last_close`, **none of which exist in the current schema** — so it silently resolved NO
> reference close at all and fell through to a drifting source. `scripts/premarket_universe.py`
> (6.3a) is what makes that impossible.

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

#### 6.3a THE UNIVERSE DATE ASSERTION — the universe is never allowed to be for the wrong session

The universe is "the Focus list of the most recent completed 18:30 ET sweep". That sentence does
not say **which session** the Focus list belongs to, and every failure below produces an artifact
that looks completely normal:

1. **The sweep for the prior session never published** — it crashed, the platform stalled it, or
   it was skipped. A routine that fetches "the latest focus.csv" then silently scans an OLDER
   session's names and measures every gap against the wrong close.
2. **Two close columns** (6.3) — `screen_close_resolved` is the previous session's close and
   `today_close` is the sweep's own session. Choosing by name instead of by date is a gap error
   of up to 10% on a single name.
3. **The schema moved.** The pre-2026-11-04 CSV had `close_<YYYY-MM-DD>` columns; the current one
   does not. A helper that looks for the old names resolves nothing and falls back silently.

**THE RULE: resolve and prove the universe FIRST, with `scripts/premarket_universe.py`, before any
tape is pulled.** It resolves the expected prior session **FROM DATA** (the market's own session
history — never a hand-typed date, never a hardcoded calendar), fetches the Focus list for it,
picks the close column **by date**, cross-checks every reference close, and writes
`daily-screens/<date>/_universe.json`.

```bash
# --- fetch the resolver (run-time fetch: the fix lands with no prompt edit) ---
U=/workspace/tools/premarket_universe.py
for URL in \
  "https://api.github.com/repos/karizaco/maxhermes-migration/contents/cloud-prompts/skills/stock-screener-suite/scripts/premarket_universe.py?ref=main" \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/skills/stock-screener-suite/scripts/premarket_universe.py" \
  "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/skills/stock-screener-suite/scripts/premarket_universe.py" ; do
  curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" \
    -H "Authorization: Bearer ${GITHUB_TOKEN}" -o "$U.tmp" "$URL" 2>/dev/null
  if [ -s "$U.tmp" ] && grep -q 'premarket-universe-v1' "$U.tmp" 2>/dev/null; then
    mv -f "$U.tmp" "$U"; break
  fi
  rm -f "$U.tmp"
done
if [ ! -s "$U" ] || ! grep -q 'premarket-universe-v1' "$U"; then
  echo "premarket_universe.py: UNAVAILABLE - the universe cannot be proven, so there is no artifact"
  exit 1
fi

python3 "$U" --fire-date <the fire's scheduled date, YYYY-MM-DD> \
    --out-dir /workspace/daily-screens/<date>
```

**A manifest whose `status` is `FAIL` means THERE IS NO ARTIFACT.** The resolver exits **3** and
prints the failed assertion. The hard assertions:

| # | assertion | what it stops |
|---|---|---|
| H1 | the expected prior session is resolved FROM DATA | a hand-typed or stale calendar |
| H2 | a published Focus list exists for a session <= the expected prior session | a scan of a universe that was never published |
| H3 | the universe's own session == the expected prior session | **the wrong day's names** (a stale sweep) |
| H4 | every name has a reference close for the denominator session | a gap with no denominator |
| H5 | every reference close is confirmed by an independent source | a gap measured against a price nobody else saw |

**A stale universe is a FAIL, not a warning.** `--allow-stale-universe` downgrades H3 to a flag —
and then the reference close **must** come from the independent sources, because the stale CSV's
close belongs to the wrong session. Either way the artifact publishes the fact:
`universe_stale: the Focus list is from <date> but the denominator session is <date>`.

**The reference close is confirmed session-exactly.** TradingView's and Cboe's `close` are always
the LATEST session's close, so they can only confirm the denominator while the denominator IS the
latest session. On a replay (or when the live sources have rolled forward) the confirmation comes
from **Nasdaq's per-symbol history**, which is exact to the session. The resolver decides which is
valid and records it in the manifest's `flags`.

**The manifest is AUTHORITATIVE for the helper.** Pass it in:

```
python3 "$S" --from-csv <the focus.csv the resolver used> \
    --universe-manifest /workspace/daily-screens/<date>/_universe.json \
    --out-dir /workspace/daily-screens/<date> --pulls 4 \
    --gap-trigger 4 --volume-floor 50000 --min-exec 25
```

The helper **refuses to run** on a manifest whose status is `FAIL`. Every CSV row then carries
`universe_date`, `ref_close_date` and `universe_source`, and the checker asserts that the whole
artifact names ONE universe session and ONE denominator session, and that they agree.

**The regression test proves the guard bites:** `tools/test_premarket_universe.py` runs the
resolver offline against fixtures and pins 20 checks, including that a WRONG-session universe and
a MISSING sweep both exit 3. A gate that has never been observed failing is a claim.

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
  curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" \
    -H "Authorization: Bearer ${GITHUB_TOKEN}" -o "$S.tmp" "$U" 2>/dev/null
  if [ -s "$S.tmp" ] && grep -q 'premarket-artifact-v5' "$S.tmp" 2>/dev/null; then
    mv -f "$S.tmp" "$S"; break
  fi
  rm -f "$S.tmp"
done
if [ ! -s "$S" ] || ! grep -q 'premarket-artifact-v5' "$S"; then
  echo "premarket_pull.py: UNAVAILABLE (no copy carrying the current contract)"
  echo "no artifact; no push"
  exit 1
fi

# the universe is resolved and PROVEN first (6.3a) - the manifest is authoritative
python3 "$U" --fire-date <the fire's scheduled date> --out-dir /workspace/daily-screens/{date>
python3 "$S" --from-csv <the focus.csv the resolver used> \
    --universe-manifest /workspace/daily-screens/{date>/_universe.json} \
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

#### 6.7 ARTIFACT FORMAT CONTRACT v5

Two files, same directory: `daily-screens/<date>/pre-market-gapper.md` and
`daily-screens/<date>/pre-market-gapper.csv`. Never let a row exist in one and not the other.

**The marker line** — the first line of the markdown, or within the first 10:

```
_contract: premarket-artifact-v5 · flagged: N · scanned: M · gate: |gap|>=4.0% and pm_volume>=50,000 and exec_shares>=25 · reference close: <source> · universe: <session> · denominator session: <session>_
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
universe_date, ref_close_date, universe_source,
ticker, ref_close, ref_close_source, pm_price, pm_gap_pct, exec_shares, exec_notional,
pm_volume, pm_volume_source, quote_price, quote_gap_pct, bid, ask, pm_high, pm_low,
pm_high_gap_pct, pm_low_gap_pct, tv_pm_pct, tv_pm_volume, stylists, origins, verdict, flag_reason
```

`universe_date` is the session the Focus list belongs to; `ref_close_date` is the session the gap
is measured against. **They are the same date in a healthy run** — when they are not, the artifact
says so in `## Flags` and the checker FAILS it.

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
  curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" \
    -H "Authorization: Bearer ${GITHUB_TOKEN}" -o "$C.tmp" "$U" 2>/dev/null
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

#### 6.13 PUBLISHING MORE THAN THE FLAG — the five additions (v5)

The 4% / 50,000 / 25-share gate in 6.1 is the **FLAG** gate and it does not change. These five
additions change what the artifact **shows** around it, so a reader sees the near-misses, the
catalyst ahead, and the market outside the Focus list. Each one is measured on the 2026-11-04
pre-market universe (600 names, 459 of them ≥4%), where the Focus list contained **0** of the 459
and the biggest gappers of the day (DUOL +25.8%, KD +17.1%, HELE +18.1%, LMB +16.3%, YOU +7.6%)
were all **post-sweep catalysts** — earnings released at 16:30 and 18:07 ET on 11-03, earnings at
06:00 and 07:00 ET on 11-04, and an acquisition proposal.

**1 — A LADDER, not a single bar.** Keep the 4% gate as the flag. Publish the names below it as
their own ranked ladder, because a 3% gap on a real market is information and a 3% gap on a quote
is not:

| rung | what it means | published with |
|---|---|---|
| `≥8%` | exceptional — the day's real gappers | the full row |
| `4–8%` | at the bar | the full row |
| `2–4%` | **the near-miss band** — AZO printed 3200 → 3297 (+3.0%) and MELI 1662 → 1713 (+3.1%) on 2026-11-04 and BOTH are invisible under a 4% gate | gap, pm volume, volume as a % of the name's 30-day average, the pre-market range, and whether the gap was sustained |
| `<2%` | noise | nothing beyond the scan table |

**2 — "REPORTS TONIGHT" — the forward calendar.** A trader needs to know which names in the
universe print **after today's close** or before tomorrow's open: that is a position to hold INTO
the catalyst, and it is invisible in a pre-market price scan. Source it from the TradingView
scanner's `earnings_release_date` (it decodes to the exact release time: DUOL 2026-11-03 18:07 ET,
LMB 2026-11-03 16:30 ET, KD 2026-11-04 07:00 ET, YOU 2026-11-04 06:03 ET) and confirm it against
the issuer's IR press release. Publish it as a `## Catalyst ahead` block: ticker, the release time
in ET, whether it is before or after today's close, and the names' pre-market gap. **MELI on
2026-11-04 was exactly this case** — a +3.1% pre-market gap into a Q3 print that landed that
evening, and the flag-only artifact said nothing about it.

**3 — VOLUME AS A RATIO, with the absolute floor kept.** The 50,000-share floor is scale-blind:
LMB's 9,120 shares (4.3% of its own 30-day average) was a real market on a +16% gap and the floor
rejected it, while 694 shares is a quote on a $53B retailer. Publish `pm_volume_pct_30d` on every
row and use the ratio for the LIQUIDITY RANKING. The flag gate keeps the absolute floor (6.1); the
ratio tells the reader which flagged name is tradeable and which near-miss deserves a look.

**4 — THE MARKET'S EVENT BOOK, beside the Focus book.** The Focus universe is a momentum screen
built on the previous session's data, so it structurally cannot contain a name whose move has not
happened yet. Publish a second table: the market's pre-market gap leaders **with their catalysts**,
joined from the earnings calendar, SEC EDGAR's overnight 8-K/425 filings, cron #92's pre-open tape,
and the wire. Measured 2026-11-04: the pre-market gainers ≥4% had a median day change of +5.08%
and 80.8% closed green — the gap itself is a tradable prior; the names where cron #92's tape
actually identified the catalyst averaged **+32%**.

**5 — THE PRE-MARKET RANGE AND WHETHER THE GAP WAS SUSTAINED.** The contract already publishes
`pm_high` / `pm_low`; publish the **sustained** fact too — did the pre-market low stay above the
prior close? Measured 2026-11-04: sustained names closed +6.14% median and 90.1% green, faded
names +3.69% and 69.9% green. It costs nothing, it needs no new source, and it is the single
cheapest quality filter in the scan.

**Do not let the additions change the flag.** The ladder, the catalyst-ahead block, the volume
ratio, the event book and the sustained flag are CONTEXT. A name is `FLAGGED` only by 6.1.

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

### 8b. Cron #06 — the weekly refresh screens (IPO / high short float / pattern-study backlog)

Cron #06 (`06-stock-screener-pattern-study-backlog`) fires Saturday 15:00 ET and publishes
**three** artifacts plus a machine-readable companion, and maintains one durable ledger and
one state series. The file names are the DEPLOYED ones — do not write the suite's `ipo.md` /
`high-short-float.md` names:

| File | Content |
|---|---|
| `daily-screens/<fire-date>/weekly-ipo.md` | filter N — recent US common-stock IPOs, mcap > $1B |
| `daily-screens/<fire-date>/weekly-high-short-float.md` | filter O — common stock with `short_percent_float > 20%` |
| `daily-screens/<fire-date>/peoplewish-backlog.md` | the 1000%-in-10-years backlog ledger + this week's live re-score |
| `daily-screens/<fire-date>/peoplewish-backlog-run-full.json` | the machine-readable full 10y scan |
| `daily-screens/<fire-date>/cron06-refresh.json` | **the contract companion** — universes, intersections, verdicts, coverage |
| `pattern-study/peoplewish-1000pct-backlog.md` (outputs repo) | **the durable ledger** — read it FIRST, push it back every run |
| `pattern-study/cron06-state/short-float-<fire-date>.json` (outputs repo) | **the state series** — one snapshot per week, appended, never rewritten |

**The contract is `cron06-refresh-v2`.** The artifacts, the engine and the checker all carry
it. An artifact without the marker is from an older run and does not satisfy this contract.

#### 8b.1 — WHY the shape changed (read this before "improving" anything)

The 2026-11-07 run was mechanically correct and reader-hostile. Every screen published the
HEAD of its own ranking, so the names that mattered — the ones in TWO universes at once —
never appeared:

* 12 names were 1000%-in-10-years compounders AND >20% short float. All 12 sat at ranks
  57-335 of the 374-name short-float book, so the published top 30 contained NONE of them,
  and the enrichment (liquidity, close, 30-day change) was spent on ranks 1-40 of a list
  that has nothing to do with the join.
* 5 names were sub-2-year IPOs AND >20% short float — the broken-float squeeze setup.
* 58 of the 374 short-float names were already in the daily sweep's Master list, and 4 of
  those (ACHC, FUN, RUN, SEZL) were Tier-A: squeeze fuel that is also a setup.

**The join is the product. The per-screen lists are its inputs.** So the engine computes the
intersections, and the ENRICHMENT FOLLOWS THE INTERSECTION — every name in any intersection
is enriched whether or not it tops a screen.

#### 8b.2 — the engine (fetch it at run time; it is not on disk in a fresh sandbox)

```bash
D=/workspace/cron06_refresh.py
for U in \
  "https://api.github.com/repos/karizaco/maxhermes-migration/contents/cloud-prompts/_shared/cron06_refresh.py?ref=main" \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/cron06_refresh.py" \
  "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/cron06_refresh.py" ; do
  curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" -o "$D.tmp" "$U" 2>/dev/null
  if [ -s "$D.tmp" ] && head -1 "$D.tmp" 2>/dev/null | grep -q '^#!' \
     && grep -q 'CRON06_REFRESH_V1' "$D.tmp" 2>/dev/null; then
    mv -f "$D.tmp" "$D"; break
  fi
  rm -f "$D.tmp"
done
[ -s "$D" ] || { echo "cron06_refresh.py fetch FAILED - write a stub artifact with _source=cron06_engine_unavailable and reply with the failure"; exit 1; }
```

The capability marker `CRON06_REFRESH_V1` is mandatory: an OLD engine would render the OLD
artifact shape and the checker would then fail the run for no visible reason.

**The engine owns every number and renders the artifacts.** The Agent fetches the three
shibui screens and passes the raw rows in as JSON; it does NOT transcribe numbers into the
markdown. A hand-typed price is a defect, not a style choice.

#### 8b.3 — the run sequence

1. Resolve the data date: `SELECT MAX(date) FROM shibui.stock_quotes` (EOD, T+1).
2. Run the three screens with the shibui bridge (filters N, O and the 10-year scan in
   `references/filters.md`), **paging every branch**: shibui's ceiling is 200 rows PER
   QUERY, so a query that returns exactly 200 rows is TRUNCATED, not complete. Page with
   `LIMIT 200 OFFSET <n>` until the collected rows equal `rows_passing`.
3. `python3 cron06_refresh.py --intersections-only ...` → the enrichment symbol list. The
   intersection names are needed BEFORE the enrichment query can be built.
4. Enrich those symbols (30-bar average dollar volume, close, close 30 bars ago, market
   cap) in ONE query, plus the IPO names' liquidity.
5. Fetch the prior ledger (`pattern-study/peoplewish-1000pct-backlog.md`) and the most
   recent PRIOR state snapshot (`pattern-study/cron06-state/short-float-*.json` with a
   fire_date earlier than this one) from the outputs repo. Both are needed: the ledger
   for continuity, the state for the change in short float.
6. Run the engine → the three `.md` artifacts, `cron06-refresh.json` and the state file.
7. Run the checker: `python3 tools/check_cron06_artifact.py --md-dir <dir> --json <json>
   --state <state> --prior-backlog <ledger>`. **A non-zero exit means the run FAILS** —
   fix the artifact, do not publish it.
8. Push the `daily-screens` tree AND the `pattern-study` ledger + state file, then verify
   each path with `verify_delivery.sh`.

#### 8b.4 — the published fields (a field, never a sentence)

| Field | Vocabulary / rule |
|---|---|
| `tradeable_verdict` | `TRADEABLE` (30d ADVol >= $20M) / `THIN` ($5-20M) / `ILLIQUID` (< $5M) / `FLOAT_ARTIFACT` (short % of float > 100) / `NO_QUOTE` (no volume history). Precedence: FLOAT_ARTIFACT > NO_QUOTE > ILLIQUID > THIN > TRADEABLE. |
| `squeeze_candidate` | `YES` only when short > 50% AND the verdict is `TRADEABLE`. |
| `short_float_delta_pp` | the change in short % of float against the prior state snapshot, in percentage points; `NO_PRIOR_SNAPSHOT` when the name was not in it. |
| `chg_30d_pct` | the price change over the 30-bar window already pulled for the ADVol denominator — it costs NO extra call. |
| `mcap_verified` | `YES` when a `shibui.valuation` row exists within 14 days; `NO` means the name passed the $1B floor BY DEFAULT, not on a stamped number. |
| `days_since_ipo` / `post_lockup` | days since the IPO date; `post_lockup = YES` past 180 days (the standard lockup length, used as a calendar marker, not a filing fact). |
| `tag_change` | `NEW` / `UNCHANGED` / `ADDED` / `REMOVED` / `MIXED` — the live tag set against the ledger's frozen tags. |

A placeholder `—` in one of these fields is a SILENT FAILURE, not a missing value. The
checker rejects it.

#### 8b.5 — the three traps this routine walks into

* **The IPO week-over-week note needs the RECOMPUTED prior universe, not the prior
  published table.** The 2026-10-31 run published only its top 50 of a larger passing set,
  so diffing against that table produces a false "entered/left" story. Re-run the SAME
  query with the previous resolved date and diff the two universes.
* **Short float: separate "left the top 30" from "left the universe".**
  `ownership_stats` is a current snapshot with no `date` column, so names lose their row
  between runs — a name above the gate with a lower stamp is a RE-STAMP, a name with no
  row at all has LEFT the universe. Say which.
* **The backlog is a discovery ledger, not a quote sheet.** The carried-forward rows stay
  FROZEN at their first-tagging values, with their `First Tagged` date. The live re-score
  carries this week's tags. Freezing the TAGS too would hide the coil -> breakout
  transition, which is the signal.

#### 8b.6 — what the reply must carry

The reply's `### Signal` section names **every newly tagged ticker** and **every
intersection name**. The checker asserts it (clause C14) — a reply that names neither is a
failed run.

## Data sources — what actually lives where

**Two runtimes, two different tool sets.** The MCP tool names in the original spec are
registered on the *local* Mavis install (`~/.minimax/mcp.json`), not in the Cloud runtime
where these crons actually fire. "The tool name is not registered" is **not** "the source
is unavailable" — read the runtime contract before declaring a source dead.

| Source | Local Mavis (stdio MCP) | Cloud runtime (what the cron actually uses) |
|---|---|---|
| `shibui-finance` | `mcp__shibui-finance__stock_data_query` | Same server over HTTPS JSON-RPC via `cloud-prompts/_shared/mcp_bridge.py` — `python3 mcp_bridge.py shibui stock_data_query args.json` |
| `tradingview` | `mcp__tradingview__screen_stocks` / `screen_etf` | TradingView's per-country scanner HTTP API: `POST https://scanner.tradingview.com/america/scan` (no auth, no rate limit) — **the PRIMARY source for cron #09's fresh book** (§4.5): the settled `close` is the official 16:00 ET print, and the scanner carries the cron day's own bar, which shibui does not have yet |
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
| 2a. Sweep SQL | 8 + paging | **one query per branch**, uncapped, paged 200 rows at a time | per-style Finviz URL (one per style) |
| 2b. TV screens | 3 | one parallel batch (CANSLIM + sector ETF + volume breakout) | per-screen Finviz URL |
| 3. Breadth | 3 | one parallel batch (shibui SQL + VIX/VIX3M + sector RS) | Finviz groups + yahoo quote page |
| 2.5 Same-day prints | 1 batched | one Nasdaq `/info` request per candidate, 12 at a time | skip — the sweep stands without it |
| 4. Reversal bullish | 1 | shibui SQL inline with the 15:55 entry alert | `finviz_reversal_bullish()` |
| 5. Pre-market gapper | **1 (batched)** | `finviz_premarket_gap_url(tickers)` → one `web_fetch` | per-ticker `stock_extended_hours` |
| 6. Live RVOL rerank | **1 (batched)** | `stock_prices` with comma-separated `EXCHANGE:SYMBOL` list | per-ticker `coin_analysis` |
| **Base sweep + live** | **~16 + 2 live** (8 branch calls + ~1 page each) | | |

The sweep grew from 3 calls to 8 because a per-branch fetch is what makes the coverage
assertion satisfiable: shibui returns at most 200 rows per query, so a merged group whose
branches pass more than 200 rows in total is truncated at the outer cap exactly the way the
old per-branch caps truncated it. Eight branch calls (plus a second page for the branches
that need one) is the price of a book that is complete — and completeness is the whole
point of the coverage assertion.

Compare to naive approach (one screen call per stylist × 10 stylists × per-ticker live): ~40+
TV calls + 20 shibui calls + 24 per-ticker live = **~85 MCP calls vs ~18 here**.

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
