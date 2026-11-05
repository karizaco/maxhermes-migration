# Filter expressions — one canonical definition per sub-screen

All SQL is `shibui-finance` SQL (see `mcp__shibui-finance__get_database_schema` for
table names). `screen_stocks` and `screen_etf` live in the base `mcp__tradingview__`
namespace; `coin_analysis` and `volume_breakout_scanner` live in `mcp__tradingview-advanced__`.
There is NO `mcp__tradingview-advanced__screen_etf` — using that name returns "Tool not found".

## ⚠ The canonical SQL is in `scripts/screen.py` — not in this file

This page states each screen's *intent*. The **runnable** SQL is emitted by the skill's
own emitters, and those are the copy to use:

```
python scripts/screen.py emit-sql sweep_stockbee   2026-10-27
python scripts/screen.py emit-sql sweep_qullamaggie 2026-10-27
python scripts/screen.py emit-sql sweep_peoplewish  2026-10-27
python scripts/screen.py emit-sql prefilter         2026-10-27
python scripts/screen.py emit-sql breadth           2026-10-27
```

The snippets below are written against a shorthand table (`shibui.daily`) and use
conceptual column names (`close_252`, `avg_volume_30d`, `sma150`). **shibui has no
`shibui.daily` table** and none of those columns exist. The real schema is:

| Concept used below | Real shibui expression |
|---|---|
| `shibui.daily` | `shibui.stock_quotes` joined to `shibui.technical_indicators` on `(symbol, date)` |
| `prev_close` | `LAG(q.close) OVER (PARTITION BY q.symbol ORDER BY q.date)` |
| `close_252` | `LAG(q.close, 252) OVER w` — and the alias is `close_252d_ago` |
| `avg_volume_30d` | `AVG(q.volume) OVER (... ROWS BETWEEN 19 PRECEDING AND CURRENT ROW)` |
| `sma200` / `sma150` | `sma_200` exists; **`sma_150` does not** |
| `date = CURRENT_DATE` | `date = '<resolved_date>'` — shibui is T+1, so resolve the date first |
| `market_cap` | `shibui.valuation.market_cap`, latest row per symbol first |

**Five defects in the published emitters were repaired on 2026-11-03** — three hard
failures (a missing CTE comma, alias names that did not match their definitions, a
`UNION ALL` whose branches had different column counts) and two silent ones (a lookback
window shorter than the `LAG(close, 252)` it needed, which returned an **empty** RS book
that read like a quiet tape; and a `UNION ALL` publishing one metric under another
metric's column header). `scripts/sql_lint.py` now checks all of that offline — run it
before you run a sweep.

### ⚠ A per-branch `LIMIT` is a SILENT TRUNCATION — never write one

**A branch (a sub-screen) must never carry a `LIMIT` smaller than the server's row
ceiling.** It is not a "sensible top-N": it is a cap that silently deletes names from the
book while the query still SUCCEEDS, so nothing goes red and every downstream count still
looks plausible.

The published emitters carried exactly that until 2026-11-05: `LIMIT 50` / `50` / `30` in
the Stockbee group, `LIMIT 60` / `30` × 3 in the Qullamägi group, `LIMIT 50` / `30` in
the weekly refresh. The 2026-11-04 artifact published `A_stockbee_4pct 50` and
`B_stockbee_ep9m 50` — those are the CAPS, not screen outcomes. The true passing
counts on 2026-11-03 were **233** for the 4% breakout, **236** for EP9M, **150** for
anticipation and **243** for peoplewish.

The rules:

1. **No branch carries a `LIMIT`.** The only `LIMIT` is the outer one, which is shibui's
   200-row per-query ceiling. `scripts/sql_lint.py` enforces this as **L009** — a CTE
   carrying a `LIMIT` smaller than the outer cap is an ERROR.
2. **Every branch reports `rows_passing`** — `COUNT(*) OVER ()` computed inside the
   branch, before any cap applies. It is the TRUE number of names that passed the
   filter, and it travels with the rows.
3. **Page instead of cap.** shibui returns at most 200 rows per query, so a branch whose
   `rows_passing` exceeds 200 needs another page (`--offset 200`, `--offset 400`, …).
   The `ORDER BY` must be TOTAL (sort key plus `symbol`) so pages never overlap or drop
   a row.
4. **Assert `rows_kept == rows_passing`** for every branch, and publish both numbers. If
   they differ the book is INCOMPLETE and must not be published.

A published branch count that lands EXACTLY on 30 / 50 / 60 / 200 is the truncation
fingerprint — report it as a failure, never as a result.

Pre-filter applied to every sub-screen unless noted:

```sql
WHERE close > 3
  AND market_cap > 300_000_000
  AND avg_volume_30d > 100_000
  AND exchange IN ('NYSE','NASDAQ','AMEX')
```

The market-cap floor is applied **inside** the sweep SQL as well (each sweep joins
`shibui.valuation` latest-row-first and requires `market_cap > 300_000_000`), so ETFs,
preferreds and other non-equities without a valuation row cannot reach the tiering
stage. See `SKILL.md` §1 for why that matters.

## A. Stockbee — Bonde 4% Breakout

```sql
SELECT symbol, close, volume, (close / prev_close - 1) * 100 AS chg_pct
FROM shibui.daily
WHERE date = CURRENT_DATE
  AND close / prev_close >= 1.04
  AND volume > prev_volume
  AND volume >= 100000
  AND close >= 3
```

## B. Stockbee — EP9 Million

```sql
SELECT symbol, close, volume, close / prev_close - 1 AS chg_pct
FROM shibui.daily
WHERE date = CURRENT_DATE
  AND volume >= 8900000
  AND close >= 3
```

Plus the trigger-candle validation columns (`range_pct`, `dcr_pct`, `trend_intensity`):

```sql
SELECT
  symbol,
  (high - low) / close * 100 AS range_pct,
  (close - low) / NULLIF(high - low, 0) * 100 AS dcr_pct,
  avg(close, 7) / avg(close, 65) AS trend_intensity
FROM shibui.daily
WHERE symbol IN (<ep9m candidates>)
GROUP BY symbol
```

## C. Qullamägi — Multi-timeframe RS leaders

One combined query. **The runnable form is `emit-sql sweep_qullamaggie`** — it carries
two corrections this sketch does not:

- the aliases are `close_252d_ago` / `close_126d_ago` / `close_63d_ago` / `close_21d_ago`
  (the sketch used `close_252` etc., which binds to nothing);
- the lookback window must cover **252 trading sessions**. A window of ~9 months is only
  ~231 sessions, which leaves `close_252d_ago` NULL and returns an **empty** result set
  with no error at all. The emitter uses a relative 430-calendar-day window, which is
  ~296 sessions — comfortably more than 252.

```sql
WITH rs AS (
  SELECT
    symbol,
    (close / NULLIF(close_252d_ago, 0) - 1) * 100 AS rs_12m,
    (close / NULLIF(close_126d_ago, 0) - 1) * 100 AS rs_6m,
    (close / NULLIF(close_63d_ago, 0) - 1) * 100 AS rs_3m,
    (close / NULLIF(close_21d_ago, 0) - 1) * 100 AS rs_1m,
    avg((high - low) / close, 20) * 100 AS adr_pct,
    avg(close * volume, 20) AS adv_dollar
  FROM shibui.daily
  WHERE date = CURRENT_DATE
)
SELECT *
FROM rs
WHERE (
    rs_1m >= 25 OR rs_3m >= 50 OR rs_6m >= 150
  )
  AND adr_pct >= 4.5
  AND adv_dollar >= 20_000_000
  AND close > sma200
  AND sma50 > sma150
  AND sma150 > sma200
ORDER BY rs_3m DESC
LIMIT 200
```

## D. Qullamägi — EP (10%+ gap)

Use `stock_extended_hours` for the Focus list. Pre-filter via shibui SQL on the
*previous close vs open* gap:

```sql
SELECT symbol, (open / prev_close - 1) * 100 AS gap_pct, volume / avg_volume_20d AS vol_ratio
FROM shibui.daily
WHERE date = CURRENT_DATE
  AND (open / prev_close - 1) >= 0.10
  AND volume / avg_volume_20d >= 10
  AND avg_dollar_volume_20d >= 50_000_000
```

Then verify catalyst via `mcp__yahoo-finance__get_market_news(ticker)` (one call per
ticker, batched into ≤ 12 calls for the Focus list).

## E. Qullamägi — 5-day gainers (parabolic short)

```sql
SELECT symbol, (close / close_5d_ago - 1) * 100 AS gain_5d, adr_pct
FROM shibui.daily
WHERE date = CURRENT_DATE
  AND close / close_5d_ago - 1 >= 0.25
  AND adv_dollar_20d >= 50_000_000
  AND adr_pct >= 5
ORDER BY gain_5d DESC
LIMIT 200
```

`LIMIT 200` is shibui's row ceiling, not a top-N. Never write a smaller cap on a branch
— see "A per-branch `LIMIT` is a SILENT TRUNCATION" above.

## F. Qullamägi — 5-day losers (parabolic long / mean-reversion)

```sql
SELECT symbol, (close / close_5d_ago - 1) * 100 AS loss_5d, distance_to_sma200_pct
FROM shibui.daily
WHERE date = CURRENT_DATE
  AND close / close_5d_ago - 1 <= -0.25
  AND close / close_5d_ago - 1 >= -0.50
  AND adv_dollar_20d >= 50_000_000
  AND ABS(distance_to_sma200_pct) < 25
ORDER BY loss_5d ASC
LIMIT 200
```

`LIMIT 200` is shibui's row ceiling, not a top-N. Never write a smaller cap on a branch
— see "A per-branch `LIMIT` is a SILENT TRUNCATION" above.

## G. peoplewish — ADR% + Dollar Volume + Velocity

```sql
SELECT
  symbol,
  avg((high - low) / NULLIF(close, 0), 20) * 100 AS adr_pct,
  avg(close * volume, 20) AS adv_dollar,
  (close / close_14d_ago - 1) * 100 AS velocity_14d
FROM shibui.daily
WHERE date = CURRENT_DATE
  AND avg((high - low) / NULLIF(close, 0), 20) * 100 >= 5
  AND avg(close * volume, 20) >= 50_000_000
ORDER BY velocity_14d DESC
LIMIT 200
```

`LIMIT 200` is shibui's row ceiling, not a top-N. Never write a smaller cap on a branch
— see "A per-branch `LIMIT` is a SILENT TRUNCATION" above.

Velocity sort is the primary sort (per peoplewish's own December 29, 2024 post). Account-
scaled `$vol` floor: replace `50_000_000` with `account_size × 10` (peoplewish's lower
bound) or `account_size × 200` (his upper bound) — config knob.

## H. Jeff Sun — CANSLIM-calibrated (TV native)

Use `mcp__tradingview__screen_stocks` with this filter set in **one** call:

```json
{
  "markets": ["america"],
  "filters": [
    {"field": "market_cap_basic", "operator": "greater", "value": 1_000_000_000},
    {"field": "earnings_growth_quarterly_yoy", "operator": "greater", "value": 25},
    {"field": "sales_growth_quarterly_yoy", "operator": "greater", "value": 25},
    {"field": "price", "operator": "greater", "value": 5},
    {"field": "change", "operator": "greater", "value": 0},
    {"field": "RSI", "operator": "less_or_equal", "value": 80},
    {"field": "RSI", "operator": "greater_or_equal", "value": 40},
    {"field": "exchange", "operator": "in_range", "value": ["NASDAQ","NYSE","AMEX"]}
  ],
  "sort_by": "change",
  "sort_order": "desc",
  "limit": 200
}
```

This is one MCP call that covers Jeff Sun's "Strongest Mover" + CANSLIM-style screen
single-handedly.

### ⚠ The two growth columns are null for every US name — rebuild on shibui

TradingView's scanner accepts `earnings_growth_quarterly_yoy` and
`sales_growth_quarterly_yoy` without error but returns **null** for them on every US
equity, so this filter set matches **zero rows** on any given day. Measured across the
2,623 US names above $1B market cap: 0 matches. `earnings_growth_yoy` and
`sales_growth_yoy` are equally empty. The other columns are fine.

The equivalent screen is built on shibui's quarterly fundamentals instead — the growth
fields there are **decimal fractions** (0.25 means 25%), and they are NULL when the
prior-year base is non-positive:

```sql
WITH mc AS (
  SELECT symbol, market_cap FROM shibui.valuation
  WHERE date = (SELECT MAX(date) FROM shibui.valuation WHERE date <= '<resolved_date>')
),
fq AS (
  SELECT symbol, date AS fq_date, eps_growth_yoy, revenue_growth_yoy
  FROM shibui.fundamentals_derived_quarterly
  WHERE date <= '<resolved_date>'
  QUALIFY ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date DESC) = 1
),
qd AS (
  SELECT q.symbol, q.date, q.close, t.rsi_14,
         LAG(q.close) OVER (PARTITION BY q.symbol ORDER BY q.date) AS prev_close
  FROM shibui.stock_quotes q
  JOIN shibui.technical_indicators t ON q.symbol = t.symbol AND q.date = t.date
  WHERE q.date BETWEEN DATE '<resolved_date>' - INTERVAL '14 days' AND '<resolved_date>'
    AND q.exchange IN ('NYSE','NASDAQ','AMEX')
)
SELECT qd.symbol, qd.close, (qd.close/NULLIF(qd.prev_close,0)-1)*100 AS chg_pct, qd.rsi_14,
       fq.eps_growth_yoy, fq.revenue_growth_yoy, fq.fq_date, mc.market_cap
FROM qd
JOIN mc ON mc.symbol = qd.symbol
JOIN fq ON fq.symbol = qd.symbol
WHERE qd.date = '<resolved_date>'
  AND mc.market_cap > 1000000000 AND qd.close > 5
  AND qd.prev_close IS NOT NULL AND qd.close/NULLIF(qd.prev_close,0) > 1
  AND qd.rsi_14 BETWEEN 40 AND 80
  AND fq.eps_growth_yoy > 0.25 AND fq.revenue_growth_yoy > 0.25
ORDER BY (qd.close/NULLIF(qd.prev_close,0)-1) DESC LIMIT 200
```

Note the `LAG` window spans a **date range**, not a single date. Filtering the CTE to one
date before the window leaves `prev_close` NULL for every row and the query returns
nothing.

For **relative volume**, prefer shibui's `technical_indicators.volume_ma_20` over
TradingView's `average_volume_10d_calc`: the latter runs 6-16% tighter than a true
trailing-10 average, so TradingView relative volumes are overstated. Treat TV's number
as a ranking, not a ratio.

## I. Hernandez — Theme → Group → Leaders (ETF RS first)

Step 1 — one base-namespace MCP call (ETF screener lives in `tradingview__`, NOT `tradingview-advanced__`):

```python
mcp__tradingview__screen_etf(
    filters=[
        {"field":"Perf.1M","operator":"greater","value":5},
        {"field":"Perf.3M","operator":"greater","value":10},
        {"field":"Perf.6M","operator":"greater","value":15}
    ],
    sort_by="Perf.1M",
    sort_order="desc",
    limit=20
)
```

Step 2 — within the top 3 sector ETFs, pull stocks via shibui SQL filtered by sector
tag. Sector mapping via `mcp__tradingview__lookup_symbols(["XLF","XLK","XLE",...])`
once, then cached.

**In the Cloud runtime, shibui's `general_info` carries the GICS mapping directly** —
no `lookup_symbols` call and no sector cache needed:

| Column | Meaning |
|---|---|
| `gics_sector` | the sector bucket (Energy, Health Care, Information Technology, …) |
| `gics_industry_group` | the industry group inside it (Software & Services, Biotechnology, Energy, …) |
| `gics_industry` / `gics_sub_industry` | finer still |

So the theme → group funnel becomes: rank the sector/industry ETFs by composite
1M/3M/6M relative strength, map the top three to their GICS bucket, then select the
leaders inside that bucket with a shibui query joining `shibui.general_info`. The
2026-10-28 run's themes were IGV (software), IBB (biotechnology) and XLE (energy).

Step 3 — fundamentals overlay, **one batched** `mcp__yahoo-finance__get_financial_statements`
call per candidate (yahoo-finance accepts only one ticker per call, so this is N calls
— cap at top 30 candidates). In the Cloud runtime, Yahoo's JSON endpoints are HTTP 429 —
use shibui's `fundamentals_derived_quarterly` / `fundamentals_derived_daily` instead, or
skip the overlay and say so in the artifact.

## J. Sun — compression / VCP screen

Apply VCP-style compression test **on top of** the Master list:

```sql
WITH compression AS (
  SELECT
    symbol,
    avg((high - low) / close, 10) / NULLIF(avg((high - low) / close, 50), 0) AS contraction_ratio
  FROM shibui.daily
  WHERE date BETWEEN CURRENT_DATE - INTERVAL '60 days' AND CURRENT_DATE
    AND symbol IN (<master list>)
  GROUP BY symbol
)
SELECT * FROM compression
WHERE contraction_ratio < 0.6
```

This is the "screen within a screen" — runs on top of any other list, not as a primary.

## K. Bonde — Anticipation (coil)

```sql
SELECT
  symbol,
  avg(close, 7) / avg(close, 65) AS trend_intensity,
  (max(high, 10) - min(low, 10)) / close AS base_width_pct,
  (close - min(low, 10)) / NULLIF(max(high, 10) - min(low, 10), 0) AS close_loc_in_base
FROM shibui.daily
WHERE date = CURRENT_DATE
  AND avg(close, 7) / avg(close, 65) >= 1.05
  AND (max(high, 10) - min(low, 10)) / close <= 0.08
  AND (close - min(low, 10)) / NULLIF(max(high, 10) - min(low, 10), 0) >= 0.5
  AND (close / prev_close - 1) < 0.04
ORDER BY trend_intensity DESC
LIMIT 200
```

`LIMIT 200` is shibui's row ceiling, not a top-N. Never write a smaller cap on a branch
— see "A per-branch `LIMIT` is a SILENT TRUNCATION" above.

## L. Bonde — Reversal Bullish (3:55 PM)

**This is a SAME-DAY scan of the LIVE session.** At 15:55 ET the US session is ~99% complete, so
today's open/high/low/close are live, and Bonde's own window (*"run the scan between 3.30 and
3.55 PM"*, *"enter between 3.58 to 4PM or using Market On Close order (MOC)"*) is achievable
same-day. **The signal bar IS today's candle and the entry is today's close.**

**Never resolve the screen date as "the latest settled date in shibui".** shibui is end-of-day,
so at 15:55 ET its newest bar is YESTERDAY's; a shibui-only scan measures the previous session's
candle and points at an entry one session after the signal — by which time the D-day bar may
already have invalidated the setup. That one-session lag is an artifact of the data source, not of
the playbook, and it is what the 2026-10-30 run did: it measured Thursday's candle on a Friday and
reported DOCU, whose Friday candle was a weak close (DCR 0.24).

**Live candle:** the TradingView public scanner (`POST https://scanner.tradingview.com/america/scan`)
returns the CURRENT session's `open/high/low/close` for every symbol. **Settled history** (the
5-day low, ADR, prior closes, average volume) comes from shibui over the MCP bridge, or from
Nasdaq's `GET https://api.nasdaq.com/api/quote/{SYM}/historical?assetclass=stocks&fromdate=…&todate=…&limit=40`
when shibui's `tools/call` is unavailable. **Universe gates** come from the same live scanner call
— live `market_cap_basic` has no stale-row problem, whereas `shibui.valuation` stores multiple rows
per symbol and can admit a phantom name if the cap filter is applied before the latest-row pick.

**Every run must prove WHICH session it is looking at** (the day-alignment assertion): the
scanner's implied previous close, `close / (1 + change_pct/100)`, must equal the latest settled
close the history source holds for the same symbol. If instead the scanner's `close` equals the
latest settled close, there is no session to scan (weekend / holiday / pre-open). Anchor the
assertion to the session **SEQUENCE**, never to calendar arithmetic.

**Gate values are Bonde's PUBLISHED ones**, taken from Pradeep Bonde, *stockbee.blogspot.com*
(2019-11-26), "Reversal Bullish Scan I use":

```
l = minl5 and (o-l) > (c-o) and (c-l)/(h-l) >= .6 and v >= 290000 and c >= 5 and minv3.1 >= 100000
```

plus the prose rules from the same source and from the BreakoutsHappen write-up of the same
workflow: *"the drop should last at least **two to three days**"*, *"there has to be some sort of
a **wash out**"*, the candle must be a **hammer** — *"a long, well-defined lower shadow and a
small body"* — and *"the reversal bar has to **jump off the chart**… if it could pass for one more
bar in a range, or an ordinary pause inside a decline — it is not the signal."*

| # | Criterion | SQL form | Source |
|---|---|---|---|
| 1 | **5-day low** | `low <= MIN(low, last 5 rows)` | published (`l = minl5`) |
| 2 | **Close in the top 40% of the day's range** | `DCR = (close - low) / (high - low) >= 0.60` | published (`>= .6`) |
| 3 | **Lower shadow longer than the body** | `(open - low) > (close - open)` | published |
| 3b | **Hammer** — long lower wick, short upper wick | `lower_shadow >= 2 * upper_shadow` where `lower_shadow = LEAST(open,close) - low`, `upper_shadow = high - GREATEST(open,close)` | published prose; replaces the tail:body ratio, which explodes on doji bodies (a 3% body makes it 15–17×) and is not a usable gate |
| 3c | **Small body** | `ABS(close - open) / (high - low) <= 0.30` | published "small body — squat, or narrow and pushed toward the top of the range" |
| 4 | Small body (house rule, non-binding given 3c) | `<= 0.40` | house |
| 5 | **Prior decline of 2–3 days, with a washout** | `(low / close_1d_ago - 1) <= -0.015` **and** (`(close / close_3d_ago - 1) <= -0.03` **or** `(close / close_5d_ago - 1) <= -0.03`) | published "the drop should last at least two to three days" + "there has to be some sort of a wash out". The old `close < close_2d_ago` is satisfied by a single marginal down day, so a sideways range passed it. |
| 6 | **ADR ≥ 3%** | `AVG((high-low)/close, 20 rows) >= 0.03` | house (SMFG counter-example) |
| 7 | **Close ≥ $5** | `close >= 5.0` | published (`c >= 5`). "Prefer higher priced stocks" is a **ranking** preference, not a filter — use it to order the list, not to cut it. |
| 8 | **Long-term trend intact** | `close >= close_20d_ago * 0.92` — 20 sessions back, not 21 | house; exhaustion at support, not a falling knife |
| S | **Stop** | body low `LEAST(open, close)`, **but** if `body_ratio < 0.15` use the signal bar's **low**; the stop must be `<= 2.5%` from the entry | published: *"If you prefer to place the stop at the low of the shadow instead, make sure that level does not exceed a 2.5% loss from your purchase price."* A body-low stop on a near-doji sits inside the bar's own noise (0.07% away on the 2026-10-26 CBRE bar) and produces false exits. |
| U | **Universe** | NYSE/NASDAQ/AMEX, `market_cap > $5B` (proxy for ≥ 1,000 institutional funds), `avg_volume_30d > 1M` | proxy; shibui has no `institutional_holders_count` |

The implementation is `tools/reversal_bullish.py` in `karizaco/maxhermes-migration` — the same
pattern cron #91 uses with `tools/schedule-drift.py`. It fetches the live universe, runs the
day-alignment assertion, applies every gate in this section, and writes the artifact:

```bash
curl -sL -o /workspace/tools/reversal_bullish.py \
  https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/tools/reversal_bullish.py
python3 /workspace/tools/reversal_bullish.py --date "$(TZ=America/New_York date +%F)"
```

`scripts/screen.py emit-sql reversal_bullish <date>` remains the reference SQL for the gates (the
inner CTE is windowed over 60 calendar days so `LAG()` and the 5-day/20-day windows see full
history, the outer query takes `rn = 1` per symbol; `shibui.valuation` is de-duplicated to each
symbol's most recent row so a stale market cap cannot qualify a symbol). It is a **settled** scan:
use it for a delayed replay, not for the live entry window.

**TradingView paging trap:** `range` paging WITHOUT an explicit `sort` returns overlapping
pages — measured 2026-11-03, 1500 rows fetched but only 1212 unique, silently losing 288 names.
Always send `"sort": {"sortBy": "name", "sortOrder": "asc"}`, fetch the whole filtered universe
in ONE call with `range: [0, 2000]`, and de-duplicate by ticker. `type == "stock"` includes
REITs — do not re-filter to common stock.

**Discretionary step is mandatory.** The mechanical screen returns candidates; Bonde's actual
process then reduces them to **1–3 ideas**: *"reducing down your list to just that 1 or 2 ideas"*,
*"the reversal bar has to jump off the chart"*, *"no catalyst, no trade"*, and the exit rule
*"if it does not work on 3rd day"*. A floor-exact DCR or a stop-distance tie-breaker is **not** a
reason to promote a name — the 2026-10-26 bar had three passers, of which only one (CELH) was a
clean qualifier.

**The entry is TODAY's close.** The signal bar is today's live candle, so `entry_price` is that
candle's live price and the tradeable entry is the 16:00 ET close (Bonde enters 3.58–4PM, or
MOC). The candle is read at ~15:55 ET, so the final print can still move the close, the DCR and
the stop — say so in the artifact. **There is no "next session" step any more**: the D-day bar is
the signal itself, which is the whole point of scanning live rather than reading yesterday's
settled file.

Two caveats the artifact must state: `v >= 290000` is judged on a **partial day's volume**
(as of ~15:55 ET), so a name that only clears 290k after the close was wrongly excluded; and
ADR(20) is computed over the 20 **settled** sessions before today, not over a window that
includes the incomplete live bar.

On a **delayed replay** the signal bar is that session's settled close and the entry was that
session's close. Report the two failure modes separately there: a close a few cents below a doji
body stop is a *noise breach*, and a close that *undercut the signal bar's low* is a *structural
failure*. Report both.

**The artifact's shape and columns are fixed — read `../SKILL.md` §5 "ARTIFACT FORMAT
CONTRACT (v3)".** The stop-vs-bar-low conflict (`bar_low`, `bar_high`,
`stop_vs_bar_low_pct`, `stop_class` = `STRUCTURAL` / `NOISE_BREACH` / `CAPPED`) and the volume
conviction (`vol_vs_30d_avg_pct`, `capitulation`) are **published fields on every candidate
row**, in the markdown table and in the CSV — not prose in a caveat section. Every promoted
idea and every non-promoted candidate carries an invalidation test, and the artifact is
verified by `tools/check_bonde_artifact.py` before the run reports success.

## M. Bonde — NTRT / EP continuation (overnight news)

Use `mcp__tradingview-advanced__stock_extended_hours` for each Focus ticker. Flag if
post-market move > 4% with > 50k volume. One call per ticker, capped at Focus list (≤ 12).

## N. Sun — IPO weekly refresh

**shibui DOES have the IPO date** — `shibui.general_info.ipo_date` (verified live
2026-11-03). The old note that shibui has no IPO date, and that this screen must fall back
to Finviz, was stale: the schema has grown since the skill was written, and Finviz is
Cloudflare-403 from the Cloud runtime anyway.

```sql
-- Recent US IPOs, common stock only, above a $1B market cap
SELECT g.symbol, g.name, g.ipo_date, g.exchange, g.type,
       v.market_cap, g.gics_sector, g.gics_industry
FROM shibui.general_info g
JOIN (
  SELECT symbol, market_cap FROM shibui.valuation
  WHERE date = (SELECT MAX(date) FROM shibui.valuation WHERE date <= '{resolved_date}')
) v ON v.symbol = g.symbol
WHERE g.ipo_date >= DATE '{resolved_date}' - INTERVAL '365 days'
  AND g.type = 'Common Stock'
  AND v.market_cap > 1000000000
ORDER BY g.ipo_date DESC
LIMIT 200
```

`LIMIT 200` is shibui's row ceiling, not a top-N. Never write a smaller cap on a branch
— see "A per-branch `LIMIT` is a SILENT TRUNCATION" above.

Run only on Sundays. Note `general_info.type` — filter to `Common Stock` or the list fills
with ETFs and SPACs that also have an `ipo_date`.

## O. Sun — High Short Float weekly refresh

**shibui DOES have short interest** — `shibui.ownership_stats.short_percent_float`
(verified live 2026-11-03: 5,388 of 5,868 rows populated, ~92%). It is a **decimal
fraction** (0.15 means 15%), and values above 1.0 occur.

```sql
-- Highest short interest as a share of float, with liquidity and size gates
SELECT o.symbol, o.short_percent_float, o.shares_float, o.percent_institutions,
       v.market_cap, q.volume
FROM shibui.ownership_stats o
JOIN (
  SELECT symbol, market_cap FROM shibui.valuation
  WHERE date = (SELECT MAX(date) FROM shibui.valuation WHERE date <= '{resolved_date}')
) v ON v.symbol = o.symbol
JOIN shibui.stock_quotes q
  ON q.symbol = o.symbol AND q.date = '{resolved_date}'
WHERE o.short_percent_float > 0.20
  AND v.market_cap > 1000000000
  AND q.volume > 1000000
ORDER BY o.short_percent_float DESC
LIMIT 200
```

`LIMIT 200` is shibui's row ceiling, not a top-N. Never write a smaller cap on a branch
— see "A per-branch `LIMIT` is a SILENT TRUNCATION" above.

Run only on Sundays. Two caveats worth knowing:

- `ownership_stats` is a **current snapshot** — it has no `date` column, so this screen
  cannot be replayed for a past date. There is no `days_to_cover` either; drop it.
- `percent_institutions` can exceed 100% on the same rows (RH 105.2%, WOLF 139.0%), so do
  not use it as a sanity filter without a tolerance.

**TradingView cannot serve this screen** — every short-interest column it exposes
(`short_ratio`, `short_percentage_of_shares_outstanding`, `short_float`, `short_interest`,
`days_to_cover`) comes back **null for every US name**, exactly like its earnings-growth
columns. shibui is the source.

## P. Skip-rule flag columns (post-process every result)

Attach these flags to every candidate row (computed from shibui daily OHLC):

| Flag | Source | Definition |
|---|---|---|
| `atr_shrink` | Hernandez | `atr_14 < 0.6 × median(atr_14, 63d)` |
| `wicky_breakout` | Hernandez | breakout day candle + `close_rvol < 1.2` |
| `ma_shrink_5d` | peoplewish | `(max(high,5) - min(low,5)) / close < 0.5 × (max(high,20) - min(low,20)) / close` |
| `day2_no_follow` | Bonde | day-2 close below day-1 midpoint AND no follow-through |
| `no_reclaim_15m` | Hernandez | post-open: stock didn't reclaim VWAP within 15 min (live only) |
| `second_bite_d2` | Hernandez | day-2 didn't hold above day-1 midpoint by noon (live only) |

## Q. Velocity sort (peoplewish)

```sql
(close / close_14d_ago - 1) * 100
```

Used as primary sort on the peoplewish scan. When two names tie on velocity, secondary
sort is `volume / avg_volume_20d`.

## R. Sector ETF RS (Hernandez top-down)

```python
mcp__tradingview__screen_etf(   # base MCP, NOT tradingview-advanced
    filters=[],
    sort_by="Perf.1M",
    sort_order="desc",
    limit=30
)
```

Then re-sort by composite of Perf.1M + Perf.3M + Perf.6M (equal weight). The top 3 are
the "themes of the week."

## S. ATR% extension from 50-MA (Sun situational awareness)

```sql
SELECT
  symbol,
  (close - sma_50) / sma_50 * 100 AS extension_pct,
  atr_pct,
  atr_pct / median(atr_pct, 252) AS extension_multiple
FROM shibui.daily
WHERE symbol IN ('SPY','RSP','QQQ','QQQE','IWM')
  AND date = CURRENT_DATE
```

Flag `late_cycle` when any of these is > 6×.

## T. VIX / VXVCLS ratio (Sun uncertainty band)

```python
vix = mcp__tradingview-advanced__yahoo_price('^VIX')['price']
vxv = mcp__tradingview-advanced__yahoo_price('^VIX3M')['price']
ratio = vix / vxv
# ratio > 1.0 => uncertainty, caution
```

**Use `^VIX3M`, not `^VXX`/`^VXV`** — the long-end VIX has no live data, so a ratio
built on it is not computable. `scripts/screen.py compute_regime()` implements the
comparison as `VIX / VIX3M`.

In the Cloud runtime, `mcp__tradingview-advanced__yahoo_price` does not exist and
Yahoo's JSON endpoints are HTTP 429. Use the CBOE delayed-quote CDN instead — it
answers without auth:

```bash
curl -s https://cdn.cboe.com/api/global/delayed_quotes/quotes/_VIX.json    # -> data.close
curl -s https://cdn.cboe.com/api/global/delayed_quotes/quotes/_VIX3M.json  # -> data.close
```

The regime payload's `uncertainty` flag is `VIX / VIX3M > 1.0`. A reading of 0.88 means
the front end carries no stress premium over the long end.
