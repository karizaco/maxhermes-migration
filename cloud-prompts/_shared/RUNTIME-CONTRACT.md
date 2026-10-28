# Cloud Runtime Data-Source Contract

**Status:** authoritative. Last measured 2026-10-28 against the live agent.minimax.io Cloud
sandbox. Every cron prompt in `cloud-prompts/cron-prompts/` embeds a condensed version of this
file; this is the full reference.

## 1. What actually exists in this runtime

The connector catalog exposes **15 tools, all of them media/email**:

```
connector__matrix__audios_understand          connector__matrix__generate_image
connector__matrix__batch_text_to_audio         connector__matrix__get_voice_list
connector__matrix__batch_text_to_music         connector__matrix__listen_audio
connector__matrix__describe_images             connector__matrix__query_video_generation
connector__matrix__reverse_image_search        connector__matrix__search_images
connector__matrix__submit_video_generation     connector__matrix__synthesize_speech
connector__matrix__videos_understand           connector__email_workbench_credentials__exchange
connector__email_workbench_credentials__session
```

**None of these are financial.** There is **no** `mcp__yahoo_finance__*`,
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

## 2. Measured endpoint status (2026-10-28)

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
| **Yahoo spark** | `https://query1.finance.yahoo.com/v7/finance/spark?symbols=...&range=1d&interval=1m&includePrePost=true` | **429** |
| **Yahoo chart** | `https://query2.finance.yahoo.com/v8/finance/chart/{SYM}?range=5d&interval=1d` | **429** |
| **Yahoo screener** | `https://query2.finance.yahoo.com/v1/finance/screener/predefined/saved?scrIds=day_gainers&count=25&start=0` | **429** |
| Stooq CSV | `https://stooq.com/q/l/?s={SYM}.us&f=sd2t2ohlcv&h&e=csv` | **404 / 000** |

**Yahoo JSON returns HTTP 429 "Edge: Too Many Requests" from this egress.** Verified across three
separate requests, two different User-Agents (including a browser UA), and a 60-second pause
between them — it is persistent rate limiting, not a transient burst from probing. Yahoo's
*HTML* pages are unaffected, and `web_search` is unaffected because it egresses differently.

**Yahoo spark batch limit** (from the original cron #26 notes): max 12 symbols per request;
larger batches return HTTP 400 on URL length. Pre-market gap = last 1m-bar close vs
`regularMarketPrice`. Do **not** use `chartPreviousClose` (that is the prior session).

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
