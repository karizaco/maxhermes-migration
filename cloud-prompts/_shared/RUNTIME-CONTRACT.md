# Cloud Runtime Data-Source Contract

**Status:** authoritative. Last measured 2026-10-31 against the live agent.minimax.io Cloud
sandbox. Every cron prompt in `cloud-prompts/cron-prompts/` embeds a condensed version of this
file; this is the full reference.

## 1. What actually exists in this runtime

The connector catalog exposed **15 tools (media/email only)** when this file was first written on
2026-10-28. **As of 2026-10-31 it exposes 133 tools: 118 GitHub, 13 media, 2 email.** Re-verify
with `probe_mcp.py` rather than trusting this paragraph — the catalog changes without notice.

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
| `stocktwits` | `https://gateway.pipeworx.io/stocktwits/mcp` | 53 tools. **Pack-specific**: `chart_data` (OHLCV), `trending`, `discover_tools`. **No `sentiment` tool** (the earlier contract row claiming one was wrong). |
| `shibui` | `https://mcp.shibui.finance/mcp` | 12 tools — `stock_data_query` (history to 1962, fundamentals, screeners, EDGAR), `get_database_schema`, `load_*_workflow`, `export_to_excel`. **No `get_quotes`.** |
| **`market-recap`** | `https://gateway.pipeworx.io/market-recap/mcp` | **48 tools. `get_quotes` (batch quotes), `top_movers`, `market_snapshot`, `price_history`.** Yahoo-sourced prices. Data is not rate-limited; the **gateway quota is** — see §1e. |
| `cftc-cot` | `https://gateway.pipeworx.io/cftc-cot/mcp` | CFTC Commitments of Traders positioning |
| `tradier` | `https://gateway.pipeworx.io/tradier/mcp` | `tradier_quote` |
| `fmp` | `https://gateway.pipeworx.io/fmp/mcp` | `stock_screener` — **requires the user's own FMP API key** as `_apiKey` |

Any pack name resolves without a code change — `mcp_bridge.py` falls back to
`https://gateway.pipeworx.io/{pack}/mcp`.

#### `--list-packs` is SEMANTIC DISCOVERY, not an inventory

`python3 mcp_bridge.py --list-packs` sends a **discovery query** ("market data quotes screener
movers") to the gateway's `discover_tools` and returns the packs whose **tools** match that query.
It is **not** a list of everything reachable, and its output is misleading in two specific ways:

- The default query returns only `tradier`, `fmp`, `market-recap`.
- **`stocktwits` and `shibui` do NOT appear** — but both work perfectly when called **by name**
  (`mcp_bridge.py stocktwits chart_data …` → real OHLCV; `mcp_bridge.py shibui stock_data_query …` →
  real closes). `shibui` can *never* appear in discovery because it is a different host, not a
  gateway pack.

**Never conclude from the `--list-packs` output that a pack is gone.** Call it by name.

#### The gateway resolves by TOOL NAME, not by pack name

`mcp_bridge.py <pack> <tool>` resolves the *tool* across the gateway's pack set, so two different
pack names can return the **same server**. Verified 2026-11-02:

```
stocktwits   get_quotes  →  {"requested":2,"found":2,"retrieved_at":"2026-11-02T05:39:36.317Z", …}
market-recap get_quotes  →  {"requested":2,"found":2,"retrieved_at":"2026-11-02T05:39:36.317Z", …}
```

Identical payload, identical timestamp — one server reached under two names. `stocktwits top_movers`
also works. **So "two packs agreed" is not two independent sources agreeing.**

A genuinely independent cross-check needs two different **tools** on two different **hosts**:

| Purpose | Tool | Host |
|---|---|---|
| OHLCV / history | `stocktwits chart_data` | `gateway.pipeworx.io/stocktwits/mcp` |
| SQL history / fundamentals | `shibui stock_data_query` | `mcp.shibui.finance/mcp` |

Verified 2026-11-02: both returned SPY close 755.72 from their own hosts.

## 1e. The Pipeworx gateway quota — and the two fixes (verified 2026-11-03)

The gateway's **data** is not rate-limited; the **gateway** is. Every tool call is metered.

### The quota, measured from the response headers

Every gateway response carries the counter:
`X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Used`, `X-RateLimit-Reset`,
`X-RateLimit-Tier`.

| Tier | Limit | How to get it |
|---|---|---|
| `anonymous` | **50 tool calls / day** | nothing — the default |
| `byo` | **200 tool calls / day** | `X-API-Key: <key>` header **or** `?apikey=<key>` query param |

- **The pool is PER EGRESS IP and shared with every other caller on that IP.** The Cloud sandbox
  egress rotates across ~2 IPs, so the fleet effectively has ~2 counters and a call can succeed
  on one IP and fail on the next.
- The counter **resets at 00:00 UTC** (`X-RateLimit-Reset`), not at local midnight — an evening
  ET fleet can exhaust the pool before its last routine runs.
- **`Authorization: Bearer` does NOT raise the tier.** Only `X-API-Key` and `?apikey=` do.
- Most tools cost **one quota unit per call regardless of symbol count**
  (`credits: 50, usd: $0.005, basis: list`). **Batch size, not symbol count, is what matters.**
- The **free key is a GitHub signup** at https://pipeworx.io/signup. Store it as
  `PIPEWORX_API_KEY` in the platform secret store — the secret store IS the env-injection path.
  `_shared/mcp_bridge.py` now reads it from the environment and sends the header automatically.
- **The failure mode is confusing**: calls succeed for hours, then one arbitrary call returns
  `{"error":"rpc_failed", ..., "Today's 50 free anonymous calls are used up"}`. The counter is
  only visible in headers the bridge previously discarded. **Read the headers when a call fails**
  and report `failed:gateway_quota(resets=<ts>)`, not "no data available".

### Fix A — `polygon-io grouped_daily`: the whole market's OHLCV in ONE call

`{"date":"YYYY-MM-DD"}` → OHLCV for **every** US symbol for one date (12,600+ names, ~1.8 MB) in
**one call**. **Ten calls give a trailing-10-session volume denominator for the entire market**,
replacing one `chart_data` call per ticker.

Verified 2026-11-03: the trailing-10 average computed from `grouped_daily` reproduces the
`stocktwits chart_data` denominator to **max 0.000075%** across 209 names — the same series, so
RVol stays comparable with previously published digests.

```bash
python3 /workspace/rvol_fetch.py --date 2026-11-02 --sessions 10 --out avg10.json
```

**Serialize the calls** — Massive (upstream) allows **5 requests/minute on a key shared across
ALL Pipeworx callers**, so space them ~13 s apart. `rvol_fetch.py` does this and backs off on
HTTP 429.

### Fix B — the same calls expose a SETTLED-VOLUME bug (read this before publishing a pre-close digest)

`get_quotes` / `chart_data` session volume read at ~16:01 ET is **not final**: the closing-auction
volume consolidates later. Measured on 2026-11-02, published volumes ran **0.7%–30.2% low**
(median ~8%) versus the settled figure, with **shibui** (`mcp.shibui.finance` — a different host)
and **`polygon-io grouped_daily`** independently agreeing on the higher number.

Because RVol = session volume ÷ trailing-10 average, an understated numerator **understates RVol**.
On 2026-11-02 that moved **7 names across the Tier-A RVol ≥ 2.0 threshold** (EL 1.96→2.32,
NXT 1.85→2.26, VG 1.73→2.16, CRH 1.47→2.11, FROG 1.82→2.07, VLTO 1.56→2.05, ABNB 1.51→2.03).
Dollar volume is understated by the same factor, which also shifts the within-tier ranking.

**Rules for a pre-close digest:**
1. Take the session-volume numerator from a **settled** source — `polygon-io grouped_daily` (1 call
   for the whole market) or shibui — not from a 16:01 ET bridge snapshot.
2. If a live snapshot volume is published, **say so in the artifact** ("session volume as of
   16:01 ET, pre-consolidation") and treat its RVol as a floor.
3. `grouped_daily` also returns `o/h/l/c` per symbol, so it cross-checks a day's settled close in
   **one call** instead of 40.


## 2. Measured endpoint status

### 2a. Re-measured 2026-10-31 (current)

> **Read this before trusting any row below.** These are *measurements*, not guarantees. Two of them
> vary between cron sessions on the same day, and the table is dated — it says what was true when
> it was taken, not what is true now. The Yahoo rows in particular are **egress-dependent**: see
> the note under the table. Re-probe what you depend on; never hard-code a status as a standing
> fact.

| Source | Endpoint | Status |
|---|---|---|
| **bridge `market-recap`** | `https://gateway.pipeworx.io/market-recap/mcp` → `get_quotes` | **200 OK — batch quotes with `previous_close`, `change_pct`, `volume`, `day_high/low`, `as_of`, `market_state`.** The **data** is not rate-limited; the **gateway** is — see §1e. Now the preferred quote source. |
| **bridge `market-recap`** | → `top_movers` | **200 OK** — ranked movers with price/change/volume/exchange. Replaces the Finviz movers screener. |
| **bridge `market-recap`** | → `market_snapshot` | **200 OK** — multi-region snapshot (indices, yields, FX, futures) in one call. |
| bridge `stocktwits` | `https://gateway.pipeworx.io/stocktwits/mcp` | **200 OK** — `chart_data` returned SPY OHLCV, trending. **Pack-specific**: `chart_data`, `trending`, `discover_tools`. **No `sentiment` tool.** |
| bridge `shibui` | `https://mcp.shibui.finance/mcp` | **200 OK** — `stock_data_query` returned SPY closes. **Different host from the gateway packs — it does NOT appear in `--list-packs` discovery.** |
| **TradingView scanner** | `POST https://scanner.tradingview.com/america/scan` | **200 OK** — movers, `relative_volume_10d_calc` (RVol), `market_cap_basic`, **`halted`**, **`premarket_change`/`premarket_volume`/`premarket_close`** |
| **Yahoo chart** | `https://query1.finance.yahoo.com/v8/finance/chart/{SYM}?period1=..&period2=..&interval=1d` | **200 OK** on 2026-10-31 and on one session on 2026-11-02 — but **429 on another session the same day**. Availability varies by egress; see the note below. |
| **Yahoo chart (5m)** | same + `&interval=5m&includePrePost=true` | **200 OK** where Yahoo answers at all — 5-minute bars retained for ~60 days. **Pre-market bars carry ZERO volume** (measured 2026-11-05: every pre/post bar's `volume` is 0 for every symbol tested) ⇒ Yahoo can supply a pre-market HIGH/LOW and a last print, but **never a pre-market volume**: `%ADV` and any liquidity gate must come from the TradingView scanner's `premarket_volume`. |
| **Yahoo screener** | `https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved?scrIds=day_gainers&count=100` | **200 OK** where Yahoo answers — `day_gainers`, `day_losers`, `most_actives`, `small_cap_gainers`, `aggressive_small_caps` |
| **Yahoo quoteSummary** | `https://query1.finance.yahoo.com/v10/finance/quoteSummary/{SYM}?modules=defaultKeyStatistics,summaryDetail&crumb={CRUMB}` | **200 OK with the crumb** — `floatShares`, `sharesOutstanding`, `shortRatio`, 52-week range. **Without the crumb: 401** (this holds regardless of egress). |
| **Yahoo options** | `https://query2.finance.yahoo.com/v7/finance/options/{SYM}?crumb={CRUMB}` | **200 OK with the crumb** — IV / implied move |
| **Nasdaq market movers** | `https://api.nasdaq.com/api/marketmovers?market=stocks` | **200 OK** — most-active / gainers / losers tables |
| **SEC EDGAR full-text** | `https://efts.sec.gov/LATEST/search-index?q={Q}&forms=8-K&startdt=..&enddt=..` | **200 OK** — 8-K hits with date/form/CIK/accession |
| **SEC EDGAR ticker→CIK** | `https://www.sec.gov/files/company_tickers.json` | **200 OK — requires a contact-style User-Agent** (e.g. `mavis@example.com`); a plain curl / browser / `Mavis` UA gets **403** |
| **SEC EDGAR 8-K Atom** | `https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={10DIGITS}&type=8-K&output=atom` | **200 OK** — CIK must be zero-padded to 10 digits. **Also requires the contact-style User-Agent** (403 otherwise). |
| `connector__github__*` | GitHub connector | **200 OK** — authorized as `karizaco` |

#### Secondary sources — re-measured 2026-11-02

These are the tier-3/4 endpoints the source ladder in every prompt relies on. They were carried in a
section headed *superseded* until 2026-11-02, which meant an agent reading only the "current" table
could not verify the ladder it was told to use. Re-measured and promoted here.

| Source | Endpoint | Status (2026-11-02) |
|---|---|---|
| Nasdaq quote API | `https://api.nasdaq.com/api/quote/{SYM}/info?assetclass=etf` | **200 OK** — needs a browser User-Agent |
| Yahoo HTML page | `https://finance.yahoo.com/quote/{SYM}/` | **200 OK** (~949 KB) — scrape last close. Answers **independently of the JSON rate limit**. |
| CoinGecko | `https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum&vs_currencies=usd` | **200 OK** |
| Frankfurter FX | `https://api.frankfurter.dev/v1/latest?from=USD&to=EUR,JPY` | **200 OK** — **use the `.dev` host**; `api.frankfurter.app` now **301s** to it, and `curl -s` without `-L` silently returns an HTML 301 body |
| ECB FX | `https://data-api.ecb.europa.eu/service/data/EXR/D.USD.EUR.SP00.A?format=csvdata` | **200 OK** |
| US Treasury yield curve | `https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/{YEAR}/all?type=daily_treasury_yield_curve&field_tdr_date_value={YEAR}&page&_format=csv` | **200 OK** — yield curve |
| AlphaVantage | `https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol={SYM}&apikey=demo` | **200 OK**, but the `demo` key only serves IBM |

**Negative measurements (2026-11-02):**

| Source | Endpoint | Status |
|---|---|---|
| Stooq CSV (quote form) | `https://stooq.com/q/l/?s={SYM}.us&f=sd2t2ohlcv&h&e=csv` | **404** (271 B HTML) or **000** (connection dropped) — **blocked** |
| Stooq CSV (daily download form) | `https://stooq.com/q/d/l/?s={SYM}.us&i=d` | **200 with a JavaScript proof-of-work challenge**, not CSV — **also unusable**. Because this path returns 200, a status-code-only check would wrongly believe it succeeded. |
| NASDAQ halt RSS | `https://www.nasdaqtrader.com/rss.aspx?feed=HALTS` | **302** → `/Trader.aspx?id=http404`. The feed no longer exists. `api.nasdaq.com/api/quote-list/halt-directory` → 404. `Trader.aspx?id=TradeHalts` → 200 but JS-rendered, 0 table rows. **Use the TradingView scanner's `halted` column instead.** |
| `www.sec.gov` (browser / `Mavis` UA) | `https://www.sec.gov/files/company_tickers.json` | **403** — SEC requires a **contact-style User-Agent** (e.g. `mavis@example.com`); with that UA it is **200** |

**Sanity-check the RESPONSE BODY, not just the HTTP status.** Stooq's daily-download path returns
200 with an HTML challenge, and a status-only check would then parse that HTML as CSV.

#### Yahoo availability is per-egress — it is NOT a standing fact

Measured **2026-11-02**, the same day, from two different cron sessions:

| Session | chart | screener | quoteSummary | options | crumb handshake |
|---|---|---|---|---|---|
| A | **429** | **429** | **429** | **429** | blocked (`crumb='Too Many Requests'`) |
| B | 200 | 200 | 200 | 200 | 200 |

Six spaced attempts in session A were all `429 Too Many Requests` (19 B body), on both `query1` and
`query2`, with and without a browser User-Agent. Yahoo's rate limiting is **per egress IP**, and
Cloud cron sessions land on different egresses.

**So: try it, and on 429/401 treat it as *not available from this session* and fall through.** Do
not report "Yahoo is blocked", and do not report "Yahoo works" — neither is true fleet-wide. The
`quoteSummary`/`options` crumb requirement is the one Yahoo fact that holds regardless of egress.

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

### 2b. Browser-backed sources (2026-10-31)

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

### 2c. `uv` / `uvx` — two MORE MCP servers now run natively in the sandbox

`uv` and `uvx` 0.12.17 are **already installed** at `/usr/local/bin/`. That unlocks the two local
MCPs previously marked `needs_linux_uv_binary` / `needs_linux_uvx_binary`. Both were verified
working on 2026-10-31.

**Blocker and fix.** The sandbox points `UV_INDEX_URL`, `UV_DEFAULT_INDEX`, `PIP_INDEX_URL` and
`PIP_TRUSTED_HOST` at `mirrors.cloud.aliyuncs.com`, which is unreachable (connection reset).
Override **both** uv variables and drop the pip ones:

```bash
env -u PIP_INDEX_URL -u UV_INDEX_URL -u PIP_TRUSTED_HOST \
    UV_DEFAULT_INDEX="https://pypi.org/simple" UV_INDEX_URL="https://pypi.org/simple" \
    uvx --quiet --from financekit-mcp financekit
```

**The console-script name is not the package name.** `financekit-mcp` installs a script called
**`financekit`** (entry point `financekit.server:main`). Running `financekit-mcp` as the command
fails.

| Package | Command | Tools | Verified |
|---|---|---|---|
| `financekit-mcp` 1.2.0 | `financekit` | **17** — `stock_quote`, `company_info`, `multi_quote`, `crypto_price`, `crypto_trending`, `crypto_search`, `crypto_top_coins`, `technical_analysis`, `price_history`, `compare_assets`, `portfolio_analysis`, `market_overview`, `risk_metrics`, **`correlation_matrix`**, **`earnings_calendar`**, `options_chain`, **`sector_rotation`** | ✅ stdio handshake OK; `market_overview` returned live indices (S&P 500 7580.07 −1.82%, Nasdaq 25437.0 −2.86%); `correlation_matrix` returned SPY/QQQ 0.924, QQQ/XLE −0.284 over 250 points |
| `tradingview-mcp` 0.9.1 | `tradingview-mcp` | **73** — `top_gainers`, `top_losers`, `bollinger_scan`, `rating_filter`, `coin_analysis`, `consecutive_candles_scan`, `advanced_candle_pattern`, `volume_breakout_scanner`, `volume_confirmation_analysis`, `smart_volume_scanner`, `multi_agent_analysis`, `egx_market_overview`, `egx_sector_scan`, `egx_sector_scanner`, `egx_index_analysis`, **`egx_stock_screener`**, `egx_trade_plan`, `egx_fibonacci_retracement`, `multi_timeframe_analysis`, `market_sentiment`, … | ✅ stdio handshake OK **only with `mcp<2` pinned** |

**`tradingview-mcp` needs `mcp<2`.** It bundles `mcp` 2.x, where `FastMCP` was renamed to
`MCPServer`; the server dies with
`ModuleNotFoundError: No module named 'mcp.server.fastmcp'`. The fix is a version constraint:

```bash
uv pip install --python python3.11 --target <dir> "mcp<2" tradingview-mcp   # resolves to mcp 1.30.0
# or, for uvx: uvx --quiet --from "tradingview-mcp" --with "mcp<2" tradingview-mcp
```

**Argument shapes are strict.** `financekit.correlation_matrix` takes `symbols` as a
**comma-joined string** (`"SPY,QQY,IWM,XLE"`), not a list — a list returns a pydantic
validation error.

### 2d. Built-in GitHub connector

The connector catalog exposes **133 tools**: 118 `connector__github__*` (authorized as `karizaco`),
13 `connector__matrix__*`, 2 `connector__email_workbench_credentials__*`. Still **zero financial
MCPs** — but the GitHub connector replaces the `git`+PAT push block in every cron prompt:
`mcode-tools connector call connector__github__create_or_update_file --args-file <file>`.
No token in the sandbox, no CA-bundle wrangling, and file-level writes cannot stage deletions.
It has **no equivalent of the push block's 3-attempt race-retry**, so routines that share a fire
minute with a partner should keep the git block.


### 2e. Finviz — exact diagnosis, and when an n8n relay is worth building (2026-10-31)

**Measured, not assumed.** Cloudflare blocks **every** Finviz path from this sandbox
(`/`, `/quote.ashx`, `/screener.ashx`, `/news.ashx`, `/api/screener.ashx`) with HTTP 403,
`cf-mitigated: challenge`, `server: cloudflare`, edge `cf-ray: …-IAD`.

**It is the egress IP, not the browser.** Evidence, all on 2026-10-31:

| Test | Result |
|---|---|
| curl with 4 different UAs (Chrome / Safari / iPhone / bare curl) | byte-identical challenge |
| headless chromium + `navigator.webdriver` masked + `chrome.runtime` + plugins/languages/hardwareConcurrency patched | still 403 |
| **headed** chromium under Xvfb, persistent profile, full stealth patch, waited 30 s | still 403, "Just a moment…" |
| sandbox egress | `47.253.4.207` = **AS45102 Alibaba (US) Technology**, Virginia Beach — a datacenter ASN with poor Cloudflare bot score |

A headed browser with a real profile and a persistent cookie jar **would** clear a
fingerprint challenge. It did not clear this one. That rules out fingerprinting and points at
IP reputation.

**When is an n8n relay worth it?** Only if the n8n host can egress from a **residential or
otherwise clean** IP. Another datacenter VPS (AWS/GCP/Azure/DO/Hetzner) will almost certainly
hit the same challenge — Cloudflare penalises datacenter ASNs broadly.

**Cheap decision test — one n8n HTTP Request node, no build:**
fetch `https://finviz.com/screener.ashx?v=111`, POST back the status code and whether the body
contains `cf-mitigated`. `200` → build the relay. `403` + challenge → your egress is still
flagged and no orchestration will fix it without a residential proxy.

**But first check the alternatives — Finviz's function is already covered:**
movers → `market-recap.top_movers`; screener/filtering → the TradingView scanner
(`market_cap_basic`, `relative_volume_10d_calc`, `price`, `change`, `volume`, `exchange`,
`halted`, `premarket_*`) and `financekit`/`tradingview-mcp` screeners; quotes, float and short
ratio → Yahoo `quoteSummary` with the crumb; premarket → the scanner's `premarket_*` columns and
Barchart via headless chromium; halts → the scanner's `halted` column; news and filings →
`web_search` + SEC EDGAR full-text.

**The only Finviz-unique content left is its preset filter sets, the insider-trading tab and the
analyst-ratings tab.** If that is worth having, the boring route is Finviz's **official paid API**
(`finviz.com/api`) — no scraping, no challenge, no proxy, no n8n.

**Note:** `xvfb` is installable in this sandbox (`apt-get install -y xvfb` works), so a *headed*
browser is available to any routine that wants one. It does not help with Finviz.


### 2f. Cboe endpoints — the options tape (measured 2026-11-04)

Cboe was missing from this contract entirely while already being the primary tape for cron #16.
Three endpoints, all measured on 2026-11-04 from the Cloud sandbox:

| Endpoint | Status | Notes |
|---|---|---|
| `https://cdn.cboe.com/api/global/delayed_quotes/options/{SYM}.json` | **200 OK** — 1.1–3.2 MB per symbol | The option-chain tape. `volume`, `open_interest`, `iv` (**a decimal fraction** — 0.3715 = 37.15%), `bid`/`ask`, `theo`, `delta`, `last_trade_time`; the underlying block carries `close`, `prev_day_close`, `price_change_percent`, `volume`. **No expiry field** — parse the OCC symbol `{ROOT}{YYMMDD}{C|P}{strike×1000}`. The top-level `timestamp` is **UTC**, the per-contract `last_trade_time` is **ET**. A symbol with no listed options series answers **HTTP 403 with an XML `AccessDenied` body** — that is NOT a source failure, record it and move on (CHSN, CRIS, DKI, OMH on 2026-11-04). |
| `https://www.cboe.com/us/options/market_statistics/historical_data/download/all_symbols/?reportType=volume&month=<M>&year=<Y>&volumeType=sum&volumeAggType=daily&exchanges=CBOE&exchanges=BATS&exchanges=C2&exchanges=EDGX` | **200 OK** — 6.5 MB for October 2026, 219,701 rows, ~3,815 symbols/day | **Every underlying's daily options volume for a whole month in ONE call.** CSV `Trade Date, Options Class, Underlying, Product Type, Exchange, Volume` — group by **(date, underlying)** and sum across classes and venues; the corporate-action-adjusted series live in the *Options Class* column (`2AAL`), not in the underlying name. Two monthly files (previous + current) cover a 10-session average. **Lags the live session by about a day**, and covers **only the four Cboe-operated venues** — so the ratio is internally consistent but the absolute volumes are a different universe from the chain. |
| `https://www.cboe.com/us/options/market_statistics/historical_data/download/class/?reportType=volume&volumeType=sum&volumeAggType=daily&symbolType=underlying&symbol=<SYM>&startDate=..&endDate=..&exchanges=...` | **200 OK** | The same data for ONE symbol over a date range. Needs a browser `User-Agent` **and** `Referer: https://www.cboe.com/us/options/market_statistics/historical_data/`, or the request is refused. The `all_symbols` variant reproduces it exactly (verified 7/7 on 2026-11-04) — prefer `all_symbols` for a multi-name baseline. |
| `https://cdn.cboe.com/api/global/delayed_quotes/quotes/_VIX.json` (and `_SPX`, `_NDX`, `_RUT`, `_DJX`, `_VIX3M`) | **200 OK** | Index quotes from the same CDN. **Needs `-L`.** `_DJX` is the Dow ÷ 100. |

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

### 5a. Never `git rebase` inside a `--depth 1` clone — it replays the shallow boundary

Measured 2026-11-06 while publishing a skill-spec fix to this repo. A `--depth 1` clone was
re-based onto a moved `origin/main`, and because the shallow boundary has no parent objects, git
tried to **replay the clone's own base commit** onto the new tip. The result was a long
"both added" conflict list (`AGENTS.md`, `PROMPT-BLOCKS.md`, `RUNTIME-CONTRACT.md`, …) for files
nobody had actually touched, and the `push` then printed **"Everything up-to-date"** — because the
in-progress rebase had already moved `HEAD` onto the fetched tip. **The commit was silently
absent from the remote**, and only the contents API showed it.

**Rule: never rebase a shallow clone.** Either deepen it first (`git fetch --unshallow`, or
`--depth 200`) or skip the rebase entirely:

```bash
git fetch origin "+refs/heads/main:refs/remotes/origin/main"
git reset --hard origin/main          # discard the local commits, keep the tree
# re-apply ONLY your own change as a patch, then commit and push
git diff <your-base-commit> -- <your files> > /tmp/my_delta.patch
git apply --3way /tmp/my_delta.patch
```

**"Everything up-to-date" on a push you believe landed is a red flag, not a success.** It means
`HEAD` already equals the remote — which, mid-rebase, can be true while your commit is nowhere.
**Verify every publish against the GitHub contents API**, never against the push output and never
against a local ref (`git cat-file -e origin/main:<path>` reads a stale ref in a shallow clone):

```bash
curl -sL -H "Accept: application/vnd.github.raw" -H "Authorization: Bearer ${GITHUB_TOKEN}" \
  "https://api.github.com/repos/<owner>/<repo>/contents/<path>?ref=main" -o /tmp/remote
grep -c "<your marker>" /tmp/remote     # a marker string, not just the file's existence
```

Put a **marker string** in the change you are publishing (a section heading, a version token) so
this check is a `grep -c` and not a byte-diff against something you are unsure about.

### 5b. Another session may be editing the same file — resolve by content, not by base

The same 2026-11-06 push hit a conflict on `docs/IMPROVEMENTS-cron05-eod-international.md`,
because another session had appended ~132 lines to it between my base commit and the new tip.
**Do not resolve such a conflict by taking one side wholesale** — that silently drops the other
session's work. Take the **tip's** version of the file and **append your own section** to it,
then check that every section heading is still present exactly once:

```bash
git checkout origin/main -- <the file>          # tip's version, their content intact
# append your new section to it
grep -c "^## 11\. " <the file>                    # yours, exactly once
grep -c "^## 10\. " <the file>                    # theirs, still intact
```

This is the same "anchor edits by content, never by line number" rule the rest of the fleet
already follows for prompt files, applied to shared docs.

