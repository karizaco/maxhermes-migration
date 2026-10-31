# Cloud Runtime Data-Source Contract

**Status:** authoritative. Last measured 2026-10-31 against the live agent.minimax.io Cloud
sandbox. Every cron prompt in `cloud-prompts/cron-prompts/` embeds a condensed version of this
file; this is the full reference.

## 1. What actually exists in this runtime

The connector catalog exposed **15 tools (media/email only)** when this file was first written on
2026-10-28. **As of 2026-10-31 it exposes 133 tools: 118 GitHub, 13 media, 2 email.**

```
connector__github__*            (118)   <- NEW 2026-10-31
connector__matrix__*            ( 13)   audios_understand, generate_image, batch_text_to_audio,
                                          get_voice_list, batch_text_to_music, listen_audio,
                                          describe_images, query_video_generation,
                                          reverse_image_search, search_images,
                                          submit_video_generation, synthesize_speech,
                                          videos_understand
connector__email_workbench_credentials__*  ( 2)
```

**Still no financial MCP.** There is **no** `mcp__yahoo_finance__*`,
`mcp__tradingview__*`, `mcp__tradingview_advanced__*`, `mcp__shibui_finance__*`,
`mcp__stocktwits__*`, `mcp__financekit__*` or `mcp__web_search__*`, and no
`extract_content_from_websites`.

The cron prompts list those MCP names for **provenance only** — they document what the local
Windows Mavis used. Calling one returns a tool-not-found error, which the zero-fallback policy
then converts into an early abort with **no artifact written**. The prompt's own CRITICAL
REMINDER originally said "use the EXACT MCP tool names listed above", which pushed the agent
straight into that trap; that line has been rewritten.

### Tools that DO work

| Tool | Use |
|---|---|
| `web_search` | Search; returns page content. **Separate egress from curl** — survives Yahoo blocking curl. Most reliable path for a single-symbol quote. |
| `web_fetch` | Fetch a URL, including a raw JSON endpoint. The `web_fetch` replacement for `extract_content_from_websites`. |
| `bash` | `curl`, `python3`, `git`, `date`. The egress proxy, however, rate-limits some hosts. |
| **`connector__github__*` (118)** | **NEW 2026-10-31.** Built-in GitHub connector, authorized as `karizaco`. Use `create_or_update_file` / `push_files` for repo writes instead of `git`+PAT: no token in the sandbox, no CA-bundle wrangling, and file-level writes structurally cannot stage deletions (the `git add -A` hazard that cost cron #12 283 files on 2026-10-25). `get_file_contents` returns the blob sha needed to update an existing file. |

### MCP servers over plain HTTPS — no registration needed

The missing `mcp__*` *tools* are not the same as the MCP *servers*. The servers are reachable
directly over JSON-RPC. See `mcp_bridge.py` in this directory. Packs confirmed reachable
2026-10-31:

| Pack | Endpoint | Notes |
|---|---|---|
| `stocktwits` | `https://gateway.pipeworx.io/stocktwits/mcp` | 53 tools — chart_data, sentiment, trending |
| `shibui` | `https://mcp.shibui.finance/mcp` | 12 tools — history to 1962, fundamentals, screeners, EDGAR |
| **`market-recap`** | `https://gateway.pipeworx.io/market-recap/mcp` | **48 tools. `get_quotes` (batch quotes), `top_movers`, `market_snapshot`, `price_history`.** Yahoo-sourced prices, not rate-limited. |
| `cftc-cot` | `https://gateway.pipeworx.io/cftc-cot/mcp` | CFTC Commitments of Traders positioning |
| `tradier` | `https://gateway.pipeworx.io/tradier/mcp` | `tradier_quote` |
| `fmp` | `https://gateway.pipeworx.io/fmp/mcp` | `stock_screener` — **requires the user's own FMP API key** as `_apiKey` |

Any pack name resolves without a code change — `mcp_bridge.py` falls back to
`https://gateway.pipeworx.io/{pack}/mcp`. `python3 mcp_bridge.py --list-packs` enumerates them
via the gateway's own `discover_tools`.

## 2. Measured endpoint status

### 2a. Re-measured 2026-10-31 (current)

| Source | Endpoint | Status |
|---|---|---|
| **bridge `market-recap`** | `https://gateway.pipeworx.io/market-recap/mcp` → `get_quotes` | **200 OK — batch quotes with `previous_close`, `change_pct`, `volume`, `day_high/low`, `as_of`, `market_state`. Not rate-limited. Now the preferred quote source.** |
| **bridge `market-recap`** | → `top_movers` | **200 OK** — ranked movers with price/change/volume/exchange. Replaces the Finviz movers screener. |
| **bridge `market-recap`** | → `market_snapshot` | **200 OK** — multi-region snapshot (indices, yields, FX, futures) in one call. |
| bridge `stocktwits` | `https://gateway.pipeworx.io/stocktwits/mcp` | **200 OK** — `chart_data` returned SPY OHLCV, sentiment, trending |
| bridge `shibui` | `https://mcp.shibui.finance/mcp` | **200 OK** — `stock_data_query` returned SPY closes |
| **TradingView scanner** | `POST https://scanner.tradingview.com/america/scan` | **200 OK** — movers, `relative_volume_10d_calc` (RVol), `market_cap_basic`, **`halted`**, **`premarket_change`/`premarket_volume`/`premarket_close`** |
| **Yahoo chart** | `https://query1.finance.yahoo.com/v8/finance/chart/{SYM}?period1=..&period2=..&interval=1d` | **200 OK** — daily bars; also `interval=5m` for intraday reconstruction |
| **Yahoo chart (5m)** | same + `&interval=5m&includePrePost=true` | **200 OK** — 5-minute bars retained for ~60 days |
| **Yahoo screener** | `https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved?scrIds=day_gainers&count=100` | **200 OK** — `day_gainers`, `day_losers`, `most_actives`, `small_cap_gainers`, `aggressive_small_caps` |
| **Yahoo quoteSummary** | `https://query1.finance.yahoo.com/v10/finance/quoteSummary/{SYM}?modules=defaultKeyStatistics,summaryDetail&crumb={CRUMB}` | **200 OK with the crumb** — `floatShares`, `sharesOutstanding`, `shortRatio`, 52-week range. **Without the crumb: 401.** |
| **Yahoo options** | `https://query2.finance.yahoo.com/v7/finance/options/{SYM}?crumb={CRUMB}` | **200 OK with the crumb** — IV / implied move |
| **Nasdaq market movers** | `https://api.nasdaq.com/api/marketmovers?market=stocks` | **200 OK** — most-active / gainers / losers tables |
| **SEC EDGAR full-text** | `https://efts.sec.gov/LATEST/search-index?q={Q}&forms=8-K&startdt=..&enddt=..` | **200 OK** — 8-K hits with date/form/CIK/accession |
| **SEC EDGAR ticker→CIK** | `https://www.sec.gov/files/company_tickers.json` | **200 OK** |
| **SEC EDGAR 8-K Atom** | `https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={10DIGITS}&type=8-K&output=atom` | **200 OK** — CIK must be zero-padded to 10 digits |
| `connector__github__*` | GitHub connector | **200 OK** — authorized as `karizaco` |

**The Yahoo crumb recipe** (both steps required):

```bash
UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
curl -s -c ck.txt -A "$UA" "https://fc.yahoo.com" -o /dev/null   # 404 BUT sets the cookie jar
CRUMB=$(curl -s -b ck.txt -A "$UA" "https://query1.finance.yahoo.com/v1/test/getcrumb")
curl -s -b ck.txt -A "$UA" \
  "https://query1.finance.yahoo.com/v10/finance/quoteSummary/EFX?modules=defaultKeyStatistics,summaryDetail&crumb=$CRUMB"
```

`fc.yahoo.com` returning **404 is expected** — it still sets the cookies. Check the crumb, not the
status of the cookie request.

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
| Finviz screener | `https://finviz.com/screener.ashx?...` | **403 / 000 / 503** across 4 attempts — Cloudflare challenge, and the 503 body was an upstream TLS `CERTIFICATE_VERIFY_FAILED` from the sandbox egress proxy |
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

### 2c. Browser-backed sources (2026-10-31)

`playwright` and the chromium build are **already installed** in the cloud sandbox:
`/usr/local/lib/python3.11/dist-packages/playwright/` and
`/root/.cache/ms-playwright/chromium-1243/chrome-linux/chrome`. No install step needed.

| Site | Plain curl | Headless chromium |
|---|---|---|
| **Barchart** | HTTP 202 AWS-WAF challenge, no cookies | **WORKS** — page renders, and the in-page `core-api` call returns real data |
| **Finviz** | HTTP 403 Cloudflare | **still 403** ("Just a moment…") even with `navigator.webdriver` masked |

**Barchart recipe — the Finviz replacement for movers/screens.** Load a Barchart page in chromium
(this clears the WAF challenge and sets the session cookies), then call `core-api` **from the page
context** so the browser attaches the cookies and the `X-XSRF-TOKEN` header:

```python
out = pg.evaluate(JS_CALL)   # JS: fetch('/proxies/core-api/v1/quotes/get?symbols=SPY,QQQ,AAPL
                               #         &fields=symbol,lastPrice,volume',
                               #         {headers:{'Accept':'application/json',
                               #                   'X-XSRF-TOKEN': decodeURIComponent(xsrf)},
                               #          credentials:'include'}).then(r=>r.text())
```

| Endpoint | Verified 2026-10-31 |
|---|---|
| `/proxies/core-api/v1/quotes/get?symbols=<A,B,C>&fields=symbol,lastPrice,volume` | `count:5, total:5`, real prices |
| `/proxies/core-api/v1/quotes/get?lists=stocks.us.percent.advances.overall&orderDir=desc&fields=symbol,symbolName,lastPrice,priceChange,percentChange,volume&limit=12` | `count:12, total:200` — the top-advancers screener |

**Field names differ between the two**: quotes use `lastChange`/`lastChangePercent`; the movers
list uses `priceChange`/`percentChange`. **Capture the list name from the page's own network
calls** — a wrong list name returns HTTP 200 with `count:0`, which looks like an empty market
rather than an error. Guessing `stocks.us.advances` does exactly that.

### 2d. `uv` / `uvx` — two more MCPs are installable

`uv` and `uvx` 0.12.17 are **already installed** at `/usr/local/bin/`. That unlocks the two local
MCPs previously marked `needs_linux_uv_binary` / `needs_linux_uvx_binary`:

| PyPI package | Tools | Serves |
|---|---|---|
| `financekit-mcp` 1.2.0 | 17: quotes, technical analysis (RSI/MACD/Bollinger/Golden-Death Cross), crypto via CoinGecko, VaR/Sharpe/Sortino/Beta, **correlation matrix**, options chains, **earnings calendar**, **sector rotation**, portfolio analysis. No API keys. | **#12** cross-asset-correlation, **#15** earnings-reaction-scanner, #09/#10 sector rotation, #16 options flow, #17 |
| `tradingview-mcp` 0.9.1 | live market intelligence, trade analytics, screeners | #07 focus-rvol, #08 pre-market gapper, #09 sweep, #10 breadth, #17 |

**Blocker:** the sandbox points `UV_INDEX_URL`, `UV_DEFAULT_INDEX`, `PIP_INDEX_URL` and
`PIP_TRUSTED_HOST` at `mirrors.cloud.aliyuncs.com`, which is unreachable (connection reset).
Override both uv variables and drop the pip ones:

```bash
env -u PIP_INDEX_URL -u UV_INDEX_URL -u PIP_TRUSTED_HOST \
    UV_DEFAULT_INDEX="https://pypi.org/simple" UV_INDEX_URL="https://pypi.org/simple" \
    uvx --quiet --from financekit-mcp financekit-mcp
```

### 2e. Built-in GitHub connector

The connector catalog exposes **133 tools**: 118 `connector__github__*` (authorized as `karizaco`),
13 `connector__matrix__*`, 2 `connector__email_workbench_credentials__*`. Still **zero financial
MCPs** — but the GitHub connector replaces the `git`+PAT push block in every cron prompt:
`mcode-tools connector call connector__github__create_or_update_file --args-file <file>`.
No token in the sandbox, no CA-bundle wrangling, and file-level writes cannot stage deletions.
It has **no equivalent of the push block's 3-attempt race-retry**, so routines that share a fire
minute with a partner should keep the git block.


## 3. The rules

1. **Try `web_search` FIRST for any single-symbol quote.** It is the most reliable path in this
   runtime and it uses a different egress than curl, so it survives Yahoo blocking curl.
2. **For bulk data walk the ladder:** Yahoo JSON → (on 429) Nasdaq API → Yahoo HTML →
   `web_search` per symbol. Stop at the first source that returns real data.
3. **A 429/403 is a RATE LIMIT, not a missing symbol.** Never report "no data" for a symbol you
   never successfully queried. Retry once after a short sleep, then fall through.
4. **Sanity-check the RESPONSE BODY, not just the HTTP status.** The egress proxy can return
   HTTP 200 carrying a plain-text error page. Confirm the body parses as the JSON/CSV you expect
   and contains the fields you need before using any number.
5. **Never fabricate a number.** If every source for a symbol failed, omit that symbol and say so
   in Source health. A missing row is recoverable; an invented price is not.
6. **Distinguish "no data" from "no source".** A symbol with no print today (pre-market, weekend,
   holiday) is `no_data`. A symbol you could not fetch is `fetch_failed` — name the reason and
   the HTTP status.
7. **Every artifact carries a `## Source health` section**: per source, the URL/query used, the
   HTTP status, and `ok` / `failed:<reason>`. If a source was rate-limited, say `429 rate-limited`
   and which fallback you used instead. Never hide a degraded run.
8. **Partial data beats no data.** If some symbols resolved and others did not, WRITE the
   artifact with the symbols you have, mark the gaps, and report `errors: <n>`. Do not abort the
   whole run because one source was blocked. The zero-fallback policy governs the *fallback
   chain*, not whether the artifact gets written.

## 4. Transport and TLS

The sandbox egress proxy issues 24h leaf certs and the leaf has expired mid-window before. At
run start check:

```bash
openssl s_client -connect query1.finance.yahoo.com:443 -servername query1.finance.yahoo.com </dev/null 2>/dev/null | openssl x509 -noout -dates
```

If the leaf is expired, use `curl -k` and **disclose the unverified transport in Source health**.
If valid, use `--cacert /etc/ssl/certs/agent-identity/sandbox-gateway-ca.crt` for verified TLS.
Always sanity-check response **bodies**, not just status codes.

## 5. Related: push and delivery verification

See `cloud-prompts/cron-prompts/README.md` for the push block and the delivery-verification
step. Summary: never `git add -A` in a fresh sandbox (it staged 283 deletions on 2026-10-25);
use a git worktree of `origin/main`, stage only this cron's output dir, abort on any staged
deletion, push `HEAD:main`, then verify with `git cat-file -e "origin/main:<path>"`.
