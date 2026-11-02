# Cloud Runtime Data-Source Contract — historical measurements

**Historical measurement, 2026-10-28.** The Yahoo rows below were superseded on 2026-10-31 and
superseded again as a *standing* fact on 2026-11-02 (Yahoo's availability is per-egress — see the
"Yahoo availability is per-egress" note in `RUNTIME-CONTRACT.md` §2a). The **non-Yahoo** rows were
never re-measured at the time and were re-measured on 2026-11-02; those live rows now sit in §2a of
the current contract.

Retained because it documents that the 429 condition was **egress-side and transient**, not a
property of Yahoo — and because it is the record of what the fleet believed on 2026-10-28.

---

### 2b. Original measurement 2026-10-28 (superseded for Yahoo)

| Source | Endpoint | Status |
|---|---|---|
| `web_search` | tool | **OK** — returned SPY 769.66 close (2026-10-27) while Yahoo JSON was 429 |
| Nasdaq quote API | `https://api.nasdaq.com/api/quote/{SYM}/info?assetclass=etf` | **200 OK** |
| Yahoo HTML page | `https://finance.yahoo.com/quote/{SYM}/` | **200 OK** (959 KB) — scrape last close |
| CoinGecko | `https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum&vs_currencies=usd` | **200 OK** |
| Frankfurter FX | `https://api.frankfurter.app/latest?from=USD&to=EUR,JPY` | **200 OK** |
| ECB FX | `https://data-api.ecb.europa.eu/service/data/EXR/D.USD.EUR.SP00.A?format=csvdata` | **200 OK** |
| SEC EDGAR | `https://data.sec.gov/submissions/CIK{10DIGITS}.json` | **200 OK** — needs a User-Agent header |
| US Treasury | `https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/2026/all?type=daily_treasury_yield_curve&field_tdr_date_value=2026&page&_format=csv` | **200 OK** — yield curve |
| AlphaVantage | `https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol={SYM}&apikey=demo` | 200 OK, but the `demo` key only serves IBM |
| **Yahoo spark** | `https://query1.finance.yahoo.com/v7/finance/spark?symbols=...&range=1d&interval=1m&includePrePost=true` | **429** on 10-28; **200 OK** on 10-31 |
| **Yahoo chart** | `https://query2.finance.yahoo.com/v8/finance/chart/{SYM}?range=5d&interval=1d` | **429** on 10-28; **200 OK** on 10-31 |
| **Yahoo screener** | `https://query2.finance.yahoo.com/v1/finance/screener/predefined/saved?scrIds=day_gainers&count=25&start=0` | **429** on 10-28; **200 OK** on 10-31 |
| Stooq CSV | `https://stooq.com/q/l/?s={SYM}.us&f=sd2t2ohlcv&h&e=csv` | **404 / 000** |
| Finviz (ALL paths) | `https://finviz.com/` , `/quote.ashx`, `/screener.ashx`, `/news.ashx`, `/api/screener.ashx` | **403 site-wide** — Cloudflare `cf-mitigated: challenge`, edge `cf-ray: …-IAD`. **Root cause = egress IP reputation, not fingerprinting** (see §2f) |
| Barchart | `https://www.barchart.com/...` | **Blocked for plain curl** — HTTP 202 bot challenge, no cookies set, `core-api` → 403. **But it WORKS via headless chromium** — see §2c. |
| NASDAQ halt RSS | `https://www.nasdaqtrader.com/rss.aspx?feed=HALTS` | **HTTP 200 with 0 RSS items** — serves an HTML shell. `api.nasdaq.com/api/quote-list/halt-directory` → 404. `Trader.aspx?id=TradeHalts` → 200 but JS-rendered, 0 table rows. **Use the TradingView scanner's `halted` column instead.** |

**CORRECTION (2026-10-31):** the 2026-10-28 note below claimed Yahoo JSON returns a *persistent*
429 from this egress. **That is no longer true.** Yahoo's chart, screener, quoteSummary and
options endpoints all returned 200 on 2026-10-31, and Yahoo JSON worked on every cron #17 run
from 10-13 to 10-23 (hundreds of requests). The 429 was an egress-side condition that has since
cleared. **Do not hard-code a Yahoo-avoidance path.** Try the ladder in cost order and fall
through on a real failure. The `market-recap` bridge pack is still preferable as the primary quote
source because it is not rate-limited and returns `as_of` + `market_state` with every quote.

**Yahoo spark batch limit** (from the original cron #26 notes): max 12 symbols per request;
larger batches return HTTP 400 on URL length. Pre-market gap = last 1m-bar close vs
`regularMarketPrice`. Do **not** use `chartPreviousClose` (that is the prior session).
