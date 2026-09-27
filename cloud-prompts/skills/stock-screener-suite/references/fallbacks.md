# Fallback chain — when MCPs rate-limit or fail

**Rule of thumb:** try MCP first; only fall back when the MCP response is explicitly an error, a timeout, or contains a `rate_limited` / `429` marker. The fallback chain always runs **MCP → Finviz URL (web_fetch) → TradingView public JSON → Yahoo Finance URL**, in that order, stopping at the first tier that returns usable data.

| Tier | What | When it works | Cost (per call) | Notes |
|---|---|---|---|---|
| 1 | MCP (shibui-finance / tradingview / yahoo-finance) | Always first; usually fastest | 1 MCP call | Most structured data, lowest parse cost |
| 2 | Finviz GET screener (`finviz.com/screener.ashx?...`) | Free, no auth, GET-only, ~200 rows per query | 1 `web_fetch` | HTML table parse — see `finviz_url()` below |
| 3 | TradingView public symbol-search (`symbol-search.tradingview.com/symbol_search/?text=`) | Free JSON, no auth; symbol metadata + last price | 1 `web_fetch` | Per-symbol lookup, not a screener |
| 4 | Yahoo Finance quote page (`finance.yahoo.com/quote/<TICKER>`) | Free HTML; current price, key stats, OHLC table | 1 `web_fetch` per ticker | Heavy HTML; use as last resort |

## Tier 2 — Finviz URL builders

Finviz's screener is query-string driven and returns a server-rendered HTML table. We can construct URLs from the filter set we use in the MCP screens.

Base URL: `https://finviz.com/screener.ashx`

Common params:
- `v=111` — overview view (most fields visible)
- `v=121` — full valuation view
- `v=131` — full financial view
- `v=141` — full technical view
- `f=<comma_separated_filters>` — filter expressions
- `o=<order_field>` — sort
- `t=<csv_or_all>` — ticker scope
- `r=<row_offset>` — pagination

### Filter codes (subset, by use)

| Code | Field | Operator |
|---|---|---|
| `cap_midover` | market cap mid-cap+ | inclusive |
| `cap_largeover` | market cap large-cap+ | inclusive |
| `sh_avgvol_o100k` | avg volume > 100k | |
| `sh_avgvol_o500k` | avg volume > 500k | |
| `sh_avgvol_o1000k` | avg volume > 1M | |
| `sh_price_o5` | price > $5 | |
| `sh_price_o10` | price > $10 | |
| `fa_epsqoq_o25` | EPS QoQ growth > 25% | |
| `fa_salesqoq_o25` | sales QoQ growth > 25% | |
| `ta_sma20_pa` | price above SMA20 | |
| `ta_sma50_pa` | price above SMA50 | |
| `ta_sma200_pa` | price above SMA200 | |
| `ta_rsi_nob40` | RSI not below 40 | |
| `ta_rsi_nob80` | RSI not overbought 80 | |
| `ta_highlow52w_b0to10pct` | within 0-10% of 52w-high | |
| `ta_change_u` | today's change up | |
| `ta_change_o4` | today's change > +4% | |
| `ta_volatility_wo5` | weekly volatility > 5% | |
| `sh_short_o15` | short interest > 15% | |
| `sh_short_o20` | short interest > 20% | |
| `ipodate_l5y` | IPO in last 5 years | |

### Pre-built screens

```python
def finviz_url(filters: list[str], order: str = "-change", limit: int = 200) -> str:
    """Build a Finviz screener URL from a filter list."""
    f = ",".join(filters)
    return f"https://finviz.com/screener.ashx?v=111&f={f}&o={order}&r=0"

# Bonde 4% breakout
def finviz_bonde_4pct() -> str:
    return finviz_url(["ta_change_o4", "sh_avgvol_o100k", "sh_price_o5"])

# Peoplewish (ADR% > 5%, $vol > $50M)
def finviz_peoplewish() -> str:
    return finviz_url(["ta_volatility_wo5", "sh_avgvol_o1000k", "cap_midover"])

# Kullamägi RS leaders (1M > 25%)
def finviz_qullamaggie_1m() -> str:
    return finviz_url(["ta_perf1mup25", "sh_avgvol_o1000k", "ta_sma200_pa", "cap_midover"])

# Jeff Sun CANSLIM-style
def finviz_jeff_sun_canslim() -> str:
    return finviz_url([
        "cap_midover", "fa_epsqoq_o25", "fa_salesqoq_o25",
        "sh_price_o5", "ta_sma50_pa", "ta_rsi_nob40", "ta_rsi_nob80"
    ])

# 5-day gainers (parabolic short)
def finviz_5d_gainers() -> str:
    return finviz_url(["ta_perf5dup25", "sh_avgvol_o1000k"])

# 5-day losers (parabolic long)
def finviz_5d_losers() -> str:
    return finviz_url(["ta_perf5ddown25", "sh_avgvol_o1000k"])

# Reversal bullish (3-candle shape — closest Finviz equivalent)
def finviz_reversal_bullish() -> str:
    return finviz_url(["ta_change_d", "ta_sma50_pa", "sh_avgvol_o1000k", "cap_largeover"])

# High short float
def finviz_high_short_float() -> str:
    return finviz_url(["sh_short_o20", "sh_avgvol_o500k"])

# IPO recent
def finviz_ipo_recent() -> str:
    return finviz_url(["ipodate_l5y", "cap_midover"])

# Pre-market gapper (Finviz pre-market requires the "v=111&p=pre" variant)
def finviz_premarket_gap_url(tickers: list[str], gap_pct_min: float = 4.0, pm_vol_min: int = 50000) -> str:
    """Pre-market gap scan on Finviz — returns the screener URL."""
    # Finviz pre-market: v=170 view, f=geo_usa|..., o=-gap (sort descending)
    ticker_filter = ",".join(f"t_{t.upper()}" for t in tickers)
    return (
        f"https://finviz.com/screener.ashx?v=170&f={ticker_filter}"
        f"&o=-change&t=cap,ta_change,ta_volume&c=0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19"
    )
```

### Parsing Finviz HTML

The HTML table is well-structured. The relevant column index depends on the `c=` parameter (column visibility). For the default `v=111` view with all columns, the row schema is:

```html
<tr>
  <td><a href="quote.ashx?t=AAPL">AAPL</a></td>   <!-- ticker -->
  <td>Apple Inc.</td>                              <!-- company -->
  <td>...</td>                                     <!-- sector -->
  <td class="...">...</td>                         <!-- market cap -->
  <td>P/E</td>
  ...
</tr>
```

A simple parser:
```python
import re
from html import unescape

def parse_finviz_table(html: str) -> list[dict]:
    """Parse a Finviz screener HTML page into a list of ticker dicts."""
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL)
    out = []
    for row in rows:
        ticker_match = re.search(r'quote\.ashx\?t=([A-Z.]+)', row)
        if not ticker_match:
            continue
        ticker = unescape(ticker_match.group(1))
        # Extract all <td> cells
        cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
        cells = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]
        out.append({"ticker": ticker, "cells": cells})
    return out
```

(The actual cell-to-field mapping depends on the `c=` parameter in the URL. For `v=111`, the standard order is: Ticker, Company, Sector, Industry, Country, Market Cap, P/E, EPS, EPS Growth, Sales Growth, Dividend, Float, Insider Own, Insider Trans, Institutional Own, Institutional Trans, Short Float, Short Ratio, RSI, Change, Volume, Price, Target Price, 52W High, 52W Low, etc.)

## Tier 3 — TradingView symbol-search JSON

```python
def tv_symbol_search_url(query: str) -> str:
    return f"https://symbol-search.tradingview.com/symbol_search/?text={query}&type=stocks&hl=en"

# Returns JSON like:
# [{"symbol":"AAPL","description":"Apple Inc.","type":"stock","exchange":"NASDAQ","country":"us","prefix":"NASDAQ"},
#  ...]
```

Useful for resolving tickers → exchange prefix (NASDAQ / NYSE / AMEX) when constructing `EXCHANGE:SYMBOL` strings for `stock_prices` calls.

## Tier 4 — Yahoo Finance quote page

```python
def yahoo_quote_url(ticker: str) -> str:
    return f"https://finance.yahoo.com/quote/{ticker.upper()}"

# Heavy HTML; only use as last resort. Better to retry the yahoo-finance MCP first.
```

## Decision matrix — when to fall back

| Stage | Primary MCP | Tier 2 fallback | Tier 3 fallback |
|---|---|---|---|
| Pre-filter universe | `shibui-finance SQL` | skip — fallback is more expensive | skip |
| Stockbee 4% breakout | `shibui-finance SQL` | `finviz_bonde_4pct()` | skip |
| Qullamägi RS leaders | `shibui-finance SQL` | `finviz_qullamaggie_1m()` | skip |
| Peoplewish | `shibui-finance SQL` | `finviz_peoplewish()` | skip |
| Sun CANSLIM-calibrated | `tradingview.screen_stocks` | `finviz_jeff_sun_canslim()` | skip |
| ETF RS (Hernandez theme) | `tradingview.screen_etf` (base MCP, NOT advanced) | `web_fetch("https://finviz.com/groups.ashx?...")` | skip |
| Volume breakout | `tradingview-advanced.volume_breakout_scanner` | `finviz_url(["ta_change_o4","sh_avgvol_o1000k"])` | skip |
| Breadth % > 20-DMA | `shibui-finance SQL` | `finviz_url(["ta_sma20_pa","cap_midover"])` | skip |
| VIX / VXV | `tradingview-advanced.yahoo_price` | `web_fetch("https://finance.yahoo.com/quote/^VIX")` then parse | `tv_symbol_search_url("VIX")` |
| Sector rotation | `financekit.sector_rotation` | `finviz_groups_url("sector")` | skip |
| Pre-market gapper | (was per-ticker TV) | `finviz_premarket_gap_url()` (BATCHED) | skip |
| Live RVOL rerank | `tradingview-advanced.stock_prices` (batched, 1 call) | per-ticker `coin_analysis` | `web_fetch` yahoo quote |
| Reversal bullish (3:55) | `shibui-finance SQL` | `finviz_reversal_bullish()` | skip |

## Cost & risk notes

- **Finviz's free tier** is sufficient for daily screens but may rate-limit if hit too hard (>50 calls/hour). The fallback chain is designed for "rare degradation," not sustained heavy use. If we fall back twice in a day, the next cron should `degraded=true` and surface the issue.
- **TradingView public JSON** (`symbol-search.tradingview.com`) is undocumented and may break without notice. Treat as Tier 3.
- **Yahoo Finance HTML** is rate-limited per-IP. 1 call/ticker, no parallel.
- **Agent should log `_source=mcp | finviz_fallback | tv_fallback | yahoo_fallback`** per row in the output CSV so we can see when the fallback chain fires.

## When NOT to fall back

- The daily sweep base plan is broken if shibui-finance is down for >1 hour. **Don't fall back** — let the sweep fail visibly and surface the issue in chat.
- During market hours, the live RVOL rerank may fall back per-ticker, but if `stock_prices` returns 429, **postpone the rerank** (don't spam with per-ticker calls). Defer to the next tick.
- Pre-market gapper: if Finviz returns 0 results, **don't** auto-fall back to per-ticker TV — that will burn 12 MCP calls for nothing. Just log "no pre-market gappers found" and quiet.
