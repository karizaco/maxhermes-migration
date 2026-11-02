# Filter expressions — one canonical definition per sub-screen

All SQL is `shibui-finance` SQL (see `mcp__shibui-finance__get_database_schema` for
table names). `screen_stocks` and `screen_etf` live in the base `mcp__tradingview__`
namespace; `coin_analysis` and `volume_breakout_scanner` live in `mcp__tradingview-advanced__`.
There is NO `mcp__tradingview-advanced__screen_etf` — using that name returns "Tool not found".

Pre-filter applied to every sub-screen unless noted:

```sql
WHERE close > 3
  AND market_cap > 300_000_000
  AND avg_volume_30d > 100_000
  AND exchange IN ('NYSE','NASDAQ','AMEX')
```

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

One combined query:

```sql
WITH rs AS (
  SELECT
    symbol,
    (close / NULLIF(close_252, 0) - 1) * 100 AS rs_12m,
    (close / NULLIF(close_126, 0) - 1) * 100 AS rs_6m,
    (close / NULLIF(close_63, 0) - 1) * 100 AS rs_3m,
    (close / NULLIF(close_21, 0) - 1) * 100 AS rs_1m,
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
LIMIT 50
```

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
LIMIT 50
```

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
LIMIT 100
```

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

Step 3 — fundamentals overlay, **one batched** `mcp__yahoo-finance__get_financial_statements`
call per candidate (yahoo-finance accepts only one ticker per call, so this is N calls
— cap at top 30 candidates).

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
LIMIT 50
```

## L. Bonde — Reversal Bullish (3:55 PM)

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

The canonical SQL for all of this is emitted by
`scripts/screen.py emit-sql reversal_bullish <YYYY-MM-DD>` (T+1-safe: the inner CTE is windowed
over 60 calendar days so `LAG()` and the 5-day/20-day windows see full history, and the outer
query takes `rn = 1` per symbol; `shibui.valuation` is de-duplicated to each symbol's most recent
row so a stale market cap cannot qualify a symbol).

**Discretionary step is mandatory.** The mechanical screen returns candidates; Bonde's actual
process then reduces them to **1–3 ideas**: *"reducing down your list to just that 1 or 2 ideas"*,
*"the reversal bar has to jump off the chart"*, *"no catalyst, no trade"*, and the exit rule
*"if it does not work on 3rd day"*. A floor-exact DCR or a stop-distance tie-breaker is **not** a
reason to promote a name — the 2026-10-26 bar had three passers, of which only one (CELH) was a
clean qualifier.

**Resolve every candidate against the next session's close before it is called actionable.**
The SQL's `entry_price` is the signal-bar close; the tradeable entry is the next session's
close. A candidate whose next-session close is below its stop has failed the setup, not been
stopped out — and a candidate that *undercut the signal bar's low* has failed structurally, which
is a different statement from a close a few cents below a doji body stop. Report both.

## M. Bonde — NTRT / EP continuation (overnight news)

Use `mcp__tradingview-advanced__stock_extended_hours` for each Focus ticker. Flag if
post-market move > 4% with > 50k volume. One call per ticker, capped at Focus list (≤ 12).

## N. Sun — IPO weekly refresh

```sql
SELECT symbol, ipo_date, market_cap, sector
FROM shibui.reference
WHERE ipo_date > CURRENT_DATE - INTERVAL '365 days'
  AND market_cap > 1_000_000_000
ORDER BY ipo_date DESC
LIMIT 50
```

Run only on Sundays.

## O. Sun — High Short Float weekly refresh

```sql
SELECT symbol, short_interest_pct_float, days_to_cover
FROM shibui.reference
WHERE short_interest_pct_float > 20
  AND adv_dollar_20d > 50_000_000
ORDER BY short_interest_pct_float DESC
LIMIT 30
```

Run only on Sundays. shibui may not have `days_to_cover` directly — drop it if not
present, sort by `short_interest_pct_float`.

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
vxv = mcp__tradingview-advanced__yahoo_price('^VXV')['price']
ratio = vix / vxv
# ratio > 1.0 => uncertainty, caution
```
