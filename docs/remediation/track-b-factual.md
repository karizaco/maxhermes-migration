# Track B — Factual accuracy of runtime/data-source claims (read-only audit)

**Audit date:** 2026-11-02, from the live cloud sandbox `/workspace` (Agent "Analyst").
**Revision:** 2 — rewritten after the independent verification report
(`/workspace/.mavis/plans/plan_9bd4fa95/outputs/track-factual/verification.md`) returned FAIL on
four defects (D1 drift-table totals, D2 the shipped Barchart helper, D3 SEC User-Agent + nasdaqtrader
RSS status, D4 the `pip install playwright` recommendation). Every defect below was **re-verified
from scratch** by me before being written up; the corrections are marked **[D1]**–**[D4]** inline.
**Scope:** METAINFORMATION + INSTRUCTIONS of the 23 cloud cron prompts (everything before
`### PRIMARY SOURCE: the MCP-over-HTTP bridge (use this FIRST)` and everything from
`## CRITICAL REMINDERS` to EOF), plus `_shared/RUNTIME-CONTRACT.md`, `_shared/mcp_bridge.py`,
`_shared/probe_mcp.py`, `_shared/barchart_fetch.py`.
**Read-only:** nothing in `/workspace/mig` was modified (`git status --porcelain` → empty, HEAD
`24baf07`); no git remote was contacted. Scratch lives in `/workspace/audit/scratch/`.

---

## Summary

The repository's runtime contract is *mostly* accurate — I re-measured 37 endpoints and every status
it asserts (Yahoo 200, Stooq 404, Finviz 403, Barchart 202-by-curl-but-works-in-chromium,
TradingView 200 with all nine claimed columns, SEC/CoinGecko/Frankfurter/Treasury 200, all five
MCP-over-HTTP packs answering) reproduced, **with two documented exceptions**: `www.sec.gov` returns
a deterministic **403** for any browser or curl User-Agent and needs a *contact-style* UA that the
contract never specifies (**B13**), and the nasdaqtrader halts "RSS" is really a **302** to
`/Trader.aspx?id=http404` (**B14**). The four headline accuracy problems are therefore: (1) **the
shipped Barchart helper cannot run at all** — `_shared/barchart_fetch.py` has two independent
blockers (a legacy chromium glob and a hard dependency on the *Python* `playwright` package in an
image that ships only the *Node* one), so the only sanctioned Barchart path for routines 02/04/05 is
dead even though Barchart itself works fine (**B8**, HIGH); (2) **`--list-packs` is semantic
discovery, not an inventory**, but 21 prompts label it "enumerate available packs", inviting the
false conclusion that `stocktwits` and `shibui` are gone — they answer perfectly, and `shibui` can
never appear in a discovery result because it lives on a different host (**B1**, HIGH); (3) **three
mutually inconsistent finance-detection regexes** exist in the fleet, and **none of the 23 deployed
prompts contains the `probe_mcp.py` fast lane** (**B4**, **B5**, HIGH) — the repo prompt is
byte-identical to the deployed prompt for only **2 of 23** routines, with 18 deployed copies still
asserting "the connector catalog exposes 15 tools" and "Yahoo's JSON endpoints return HTTP 429",
both false today.

---

## VERIFIED ENDPOINT TABLE

All tests run from this sandbox with `curl -s -A "Mozilla/5.0" --max-time 25..40` unless a different
UA is stated (script: `/workspace/audit/scratch/ep_test.py`; raw results: `endpoint_results.json`).
**Note:** rows marked `⚠` were re-tested in revision 2 — either because the contract
**under-specifies a requirement** there (16, 20, 21) or because revision 1's verdict there was
**wrong** (33, 34, 36) or **missing a working alternative** (37).

| # | Endpoint | Prompt's claim | Actual result today (HTTP / shape) | Verdict | Source of truth for the correction |
|---|---|---|---|---|---|
| 1 | Yahoo chart `query1…/v8/finance/chart/SPY?range=5d&interval=1d` | 200 (contract §2a); deployed copies say 429 | **200**, 1764 B, JSON `chart.result[0]` | repo **accurate** / deployed **stale** | contract §2a |
| 2 | Yahoo chart 5m `&interval=5m&includePrePost=true` | 200, 5-min bars ~60d | **200**, 59 343 B | accurate | contract §2a |
| 3 | Yahoo screener `predefined/saved?scrIds=day_gainers&count=100` | 200 | **200**, 270 808 B, JSON `finance.result` | accurate | contract §2a |
| 4 | Yahoo screener `most_actives` | 200 | **200**, 69 793 B | accurate | contract §2a |
| 5 | Yahoo spark, 12 symbols | 200; max 12/batch | **200**, 154 860 B | accurate | contract §2b |
| 6 | Yahoo spark, 21 symbols | "max 12 symbols; larger batches return HTTP 400" | **400**, 127 B, body `Number of symbols needs to be less than or equal to 20` | accurate | contract §2b |
| 7 | Yahoo quoteSummary **without** crumb | **401** | **401**, 89 B | accurate | contract §2a |
| 8 | Yahoo quoteSummary **with** crumb | 200 (`floatShares`, `shortRatio`, 52-wk) | **200**, 5 088 B, `floatShares=116514000`, `shortRatio=2.86` | accurate | contract §2a |
| 9 | Yahoo options **with** crumb (`query2…/v7/finance/options/SPY`) | 200 | **200**, 71 274 B, JSON `optionChain` | accurate | contract §2a |
| 10 | `fc.yahoo.com` cookie request | 404 expected, still sets cookies | **404** (crumb then retrieved OK) | accurate | contract §2a |
| 11 | Yahoo HTML `finance.yahoo.com/quote/SPY/` | 200 (959 KB) | **200**, 937 231 B | accurate | contract §2b |
| 12 | Nasdaq quote API `api.nasdaq.com/api/quote/SPY/info?assetclass=etf` | 200 | **200**, 624 B, JSON `data/message/status` | accurate | contract §2b |
| 13 | Nasdaq quote API (stock, `assetclass=stocks`) | 200 | **200**, 1 353 B | accurate | contract §2b |
| 14 | Nasdaq market movers `api.nasdaq.com/api/marketmovers?market=stocks` | 200 | **200**, 18 484 B | accurate | contract §2a |
| 15 | Nasdaq halt-directory `api.nasdaq.com/api/quote-list/halt-directory` | 404 | **404**, 0 B | accurate | contract §2b |
| 16 ⚠ | `nasdaqtrader.com/rss.aspx?feed=HALTS` | "**HTTP 200 with 0 RSS items** — serves an HTML shell" | raw request (no `-L`): **302**, 931 B, `location: /Trader.aspx?id=http404`. With `-L`: **200**, 42 894 B, `<item>` count = **0**, title `Page Not Available` | **partly wrong** — status is **302**, not 200 (**B14**) | contract §2b row 117 |
| 17 | `nasdaqtrader.com/Trader.aspx?id=TradeHalts` | 200 but JS-rendered, 0 table rows | **200**, 47 425 B, `haltSymbol` occurrences = **0** | accurate | contract §2b |
| 18 | TradingView scanner `POST scanner.tradingview.com/america/scan` | 200 + `halted`, `premarket_change/volume/close`, `relative_volume_10d_calc`, `market_cap_basic` | **200**, `totalCount=11723`; response is positional `{"s","d"}`; `len(d)==len(columns)` (13/13); **all 9 claimed columns present** (`halted`=null, `premarket_change`=55.28652138821633, `premarket_volume`=195306359, `premarket_close`=0.5772, `relative_volume_10d_calc`=4.830487991652844, `market_cap_basic`=3940701) | accurate | contract §2a |
| 19 | SEC EDGAR full-text `efts.sec.gov/LATEST/search-index?q=…&forms=8-K` | 200 | **200**, 65 764 B, JSON `hits/aggregations` — **200 with a plain browser UA**, no contact UA needed | accurate | contract §2a row 80 |
| 20 ⚠ | SEC `www.sec.gov/files/company_tickers.json` | "**200 OK**" (no UA stated) | with `Mozilla/5.0` → **403** (1925 B); with `curl/8.14.1` → **403**; with the contract's own Chrome UA → **403**; with `Mavis Audit Bot mavis@example.com` → **200**, 797 604 B | **under-specified** — **B13** | contract §2a row 81 |
| 21 ⚠ | SEC 8-K Atom `browse-edgar?action=getcompany&CIK=0000320193&type=8-K&output=atom` | "**200 OK** — CIK must be zero-padded to 10 digits" | with `Mozilla/5.0` → **403**; with `Mavis Audit Bot mavis@example.com` → **200**, 65 954 B, `<feed>` | **under-specified** — **B13** | contract §2a row 82 |
| 22 | SEC `data.sec.gov/submissions/CIK0000320193.json` | 200, needs User-Agent | **200**, 163 586 B — **200 with a plain browser UA** | accurate | contract §2b row 108 |
| 23 | CoinGecko `simple/price?ids=bitcoin,ethereum` | 200 | **200**, 52 B | accurate | contract §2b |
| 24 | Frankfurter `api.frankfurter.app/latest?from=USD&to=EUR,JPY` | 200 | **200**, 84 B | accurate | contract §2b |
| 25 | ECB FX `data-api.ecb.europa.eu/…/D.USD.EUR.SP00.A?format=csvdata` | 200 | **200**, 1 489 403 B CSV | accurate | contract §2b |
| 26 | US Treasury daily yield-curve CSV | 200 | **200**, 17 039 B, CSV header `Date,"1 Mo","1.5 Month","2 Mo",…` | accurate | contract §2b |
| 27 | AlphaVantage `GLOBAL_QUOTE&symbol=IBM&apikey=demo` | 200, demo key serves IBM only | **200**, 385 B, `Global Quote` | accurate | contract §2b |
| 28 | Stooq CSV `stooq.com/q/l/?s=spy.us&f=sd2t2ohlcv&h&e=csv` | "**404 / 000**", "Stooq CSV is blocked (404)" | **404**, 271 B error page | accurate | contract §2b |
| 29 | Finviz, all paths (curl) | 403 site-wide, `cf-mitigated: challenge`, edge `cf-ray: …-IAD` | **403** on `/`, `/screener.ashx`, `/api/screener.ashx`; `cf-mitigated: challenge`, `server: cloudflare` | accurate | contract §2b/§2f |
| 30 | Finviz via headless chromium | "**still 403** ('Just a moment…') even with `navigator.webdriver` masked" | **403**, title `"Just a moment..."`, 0 cookies | accurate | contract §2c |
| 31 | Barchart, plain curl | "HTTP 202 AWS-WAF challenge, no cookies"; `core-api` → 403 | **202**, `x-amzn-waf-action: challenge`, `content-length: 0`, CloudFront IAD12; `core-api` → **403** | accurate | contract §2b/§2c |
| 32 | Barchart via headless chromium (**hand-written Node script**) | "**WORKS** — page renders, and the in-page `core-api` call returns real data"; movers list `count:12, total:200` | default headless UA → **403** "Request blocked", 0 cookies. Realistic Chrome UA + 1700×1200 viewport → page **202**, title `SPY - SPDR S&P 500 ETF Price - Barchart.com`, **20 cookies** incl. `aws-waf-token`; `core-api` **200** `{"count":3,"total":3,"data":[{"symbol":"SPY","lastPrice":"755.72","volume":"77,696,400"},…]}`; movers **200** `{"count":12,"total":200,"data":[{"symbol":"CHOW","percentChange":"+106.57%"},…]}` | accurate, **but the sanctioned helper cannot deliver it** (**B8**) | contract §2c rows 139, 156, 157 |
| 33 ⚠ | `_shared/barchart_fetch.py --symbols SPY,QQQ,AAPL` (the path the prompts actually run) | "**WORKS**" per contract §2c; prompts run it verbatim | **EXIT 2** `{"error": "no_chromium", "detail": "playwright chromium not found; set PLAYWRIGHT_BROWSERS_PATH"}`. With the glob patched: **EXIT 2** `{"error": "no_playwright", "detail": "No module named 'playwright'"}` | **WRONG** — **B8** | — |
| 34 ⚠ | `mcode-tools connector tools` | "catalog exposes **133 tools**: 118 GitHub, 13 media, 2 email" | **binary not installed** → `catalog_unreachable` (`[Errno 2] No such file or directory: 'mcode-tools'`) | **UNVERIFIED** (see **B6**) | — |
| 35 | `uv` / `uvx` at `/usr/local/bin/` | "**already installed** at `/usr/local/bin/`", 0.12.17 | **NOT INSTALLED** (`ls /usr/local/bin \| grep ^uv` → empty) | **WRONG** in this sandbox (**B7**) | — |
| 36 ⚠ | Python `playwright` + `/root/.cache/ms-playwright/chromium-1243/chrome-linux/chrome` | "**already installed** … **No install step needed**" | python `playwright` → `ModuleNotFoundError`; `/root/.cache/ms-playwright` → absent; `pip`/`ensurepip` → absent (so it cannot be installed); browser had to be installed by hand into `/workspace/.home/.cache/ms-playwright/chromium-1217/chrome-linux64/chrome` (build **1217/Chrome 147**, not 1243) | **WRONG** in this sandbox (**B7**, **B8**) | — |
| 37 ⚠ | **Node** Playwright | *not mentioned anywhere in the contract* | **PREINSTALLED**: `/app/node_modules/playwright`, `Version 1.59.1`, binary `/app/node_modules/.bin/playwright` | **MISSING FROM THE CONTRACT** — this is the only browser path that works here (**B7**, **B8**) | — |

---

## DEPLOYED-vs-REPO DRIFT TABLE

Source of truth for "deployed": `mcp_invoke cron_read {"view":"list","limit":100}`, raw JSON persisted at
`/workspace/.mavis/tool-results/458676653531358/call_01a196fdb3f37774aef04a72/chunks/000000.txt`
(466 798 B, 23 tasks, all `agent_name=Mavis`, `has_more=False`). Parsed to
`/workspace/audit/scratch/deployed_tasks.json`. "deployed == repo?" compares the **deployed prompt**
with the **repo prompt block** (the fenced `### Prompt (paste this verbatim …)` block for #01; the
whole file for the digest-style prompts), whitespace-normalised; the 2/23 identity split was
independently re-confirmed by SHA-256 of the raw prompt bytes.
**Lengths below are CHARACTER counts** (not bytes on disk).

| # | Routine | deployed == repo? | Stale fact in the DEPLOYED copy? | Which line / sentence |
|---|---|---|---|---|
| 1 | `01-weekly-mcp-health-check.md` | **NO** (repo 6 789 B → prompt block 955 B; deployed 4 254 B) | No stale *fact*, but the deployed copy is a **condensed rewrite**: the repo's "Purpose" paragraph, the 4-item "Changes vs. the 2026-10-28 original" preamble and the Appendix ("why the three-state distinction matters") are absent. Both copies carry the same 13-keyword regex and the same `head -40` on `--list-packs`; the pack loop truncates at `head -c 180` (deployed) vs `head -c 200` (repo) | deployed §"Steps — IN ORDER" vs repo `01-weekly-mcp-health-check.md:6-25` and `:141-155` |
| 2 | `02-asia-pre-market-reactions.md` | **NO** (20 227 → 18 114 B) | **YES ×3** — "exposes 15 tools, ALL media/email"; "Yahoo's JSON endpoints return HTTP 429"; no `market-recap`, no `probe_mcp.py`, no Barchart | deployed §"RUNTIME DATA-SOURCE CONTRACT": "Verified 2026-10-28: the connector catalog exposes 15 tools, ALL media/email"; "Measured 2026-10-28 from this sandbox — Yahoo's JSON endpoints return HTTP 429" |
| 3 | `04-reversal-bullish-3:55.md` | **NO** (20 324 → 18 211 B) | **YES ×3** — same three as #02 | same sentences as #02 |
| 4 | `05-eod-international-daily.md` | **NO** (20 276 → 18 163 B) | **YES ×3** — same as #02 | same |
| 5 | `06-stock-screener-pattern-study-backlog.md` | **NO** (19 929 → 17 816 B) | **YES ×3** — same as #02 | same |
| 6 | `07-stock-screener-focus-rvol-09:45.md` | **NO** (20 160 → 18 047 B) | **YES ×3** — same as #02 | same |
| 7 | `08-stock-screener-pre-market-gapper.md` | **NO** (20 497 → 18 384 B) | **YES ×3** — same as #02 | same |
| 8 | `09-stock-screener-daily-sweep-18:30.md` | **NO** (23 608 → 21 495 B) | **YES ×3** — same as #02 | same |
| 9 | `10-stock-screener-breadth-snapshot.md` | **NO** (24 283 → 22 170 B) | **YES ×3** — same as #02 | same |
| 10 | `12-cross-asset-correlation-snapshot.md` | **NO** (23 544 → 21 252 B) | **YES ×3** — same as #02 | same |
| 11 | `13-macro-calendar-midweek.md` | **NO** (19 844 → 17 731 B) | **YES ×3** — same as #02 | same |
| 12 | `14-macro-calendar-week-ahead.md` | **NO** (19 868 → 17 755 B) | **YES ×3** — same as #02 | same |
| 13 | `15-earnings-reaction-scanner.md` | **NO** (23 260 → 21 147 B) | **YES ×3** — same as #02 | same |
| 14 | `16-unusual-options-flow-daily.md` | **NO** (20 325 → 18 212 B) | **YES ×3** — same as #02 | same |
| 15 | `17-us-stocks-in-play.md` | **YES — byte-identical** (22 197 B) | **YES ×1** — the repo copy itself still carries "the connector catalog exposed 15 tools, ALL media/email" and the 9-keyword finance regex | `cron-prompts/17-us-stocks-in-play.md:110` and `:201` (see **B3**, **B4**) |
| 16 | `19-earnings-reminder-daily.md` | **NO** (24 302 → 22 190 B) | **YES ×3** — same as #02 | same |
| 17 | `20-eod-watchlist-csv-snapshot.md` | **NO** (20 129 → 18 016 B) | **YES ×3** — same as #02 | same |
| 18 | `22-weekly-market-recap-preview.md` | **NO** (20 218 → 18 105 B) | **YES ×2** — "15 tools" + "Yahoo 429" (this one *does* contain `market-recap`, 3 occurrences) | same two sentences |
| 19 | `23-agentic-post-market-brief.md` | **NO** (21 098 → 18 985 B) | **YES ×3** — same as #02 | same |
| 20 | `25-ntrt-gap-brief-daily.md` | **NO** (24 567 → 18 110 B) | **YES ×3** — same as #02 (largest gap: 6 457 B) | same |
| 21 | `26-agentic-pre-market-brief.md` | **NO** (20 628 → 18 959 B) | **YES ×1** — *older* generation: deployed copy is dated "verified 2026-10-23/24", still routes quotes through Yahoo `spark`, asserts "The custom-POST screener tier … is DOWN — `getcrumb` returns `Invalid Cookie` and POSTs return 401 `Invalid Crumb`" | deployed §"Cloud reality (verified 2026-10-23/24)" |
| 22 | `90-delivery-auditor.md` | **YES — byte-identical** (32 304 B) | none | — |
| 23 | `91-schedule-drift-guard.md` | **NO** (15 512 → 10 174 B) | **YES (capability drift, not a stale fact)** — deployed copy has **no** `## CONVERSATION TITLE` step, **no** STEP 2b (conversation hygiene), and the older exit-code legend `0 = no drift, 1 = drift found` | deployed §"Exit codes: `0` = no drift, `1` = drift found, `2` = input error." vs repo `cron-prompts/91-schedule-drift-guard.md:129` + `:139` |

### Totals (corrected — [D1])

Each count below was recomputed by an independent per-routine pass over the deployed prompts
(`re.search` on each `prompt` string) and cross-checked against the verifier's independent SHA-256
pass; the two agree exactly.

| Metric | Value | Where the block lives |
|---|---|---|
| Repo prompt **byte-identical** to deployed | **2 / 23** (#17, #90) | — |
| Deployed copies asserting "the connector catalog exposes 15 tools" | **18 / 23** | #02,04,05,06,07,08,09,10,12,13,14,15,16,19,20,22,23,25 |
| Deployed copies asserting "Yahoo's JSON endpoints return HTTP 429" (present tense) | **18 / 23** | same 18 |
| Deployed copies **missing** the `market-recap` primary-quote block | **19 / 23** | present only in #01, #17, #22, #90 |
| Deployed copies **missing** the Barchart path | **21 / 23** | present only in #01, #17 |
| Deployed copies **missing** the `probe_mcp.py` fast lane | **23 / 23** | **present in NONE** |

**[D1] correction.** Revision 1 of this report published 20 / 22 / 19 for the last three rows. Those
numbers were a transcription error: the per-routine evidence file `drift_final.json` had them right at
**19 / 21 / 23**, and the verifier's independent recount agreed with the data file, not the prose. The
material error was the third one — revision 1 implied **four** deployed routines already carried the
`probe_mcp.py` fast lane; in fact **zero** do, so the "a repo-only fix reaches 2 of 23" framing
understated the gap. The corrected statement: **the repo-only fix reaches 2 of 23 routines on the
prompt text, and 0 of 23 on the fast-lane probe.**

---

## Findings

### B1 — `--list-packs` is semantic discovery, but 21 prompts label it "enumerate available packs"
- **Severity:** high
- **Routines affected:** all 21 digest prompts that carry the bridge block (02, 04, 05, 06, 07, 08,
  09, 10, 12, 13, 14, 15, 16, 17, 19, 20, 22, 23, 25, 26) + #01
- **Evidence:**
  - `/workspace/mig/cloud-prompts/cron-prompts/02-asia-pre-market-reactions.md:165` (and the same
    line in 04:165, 05:165, 06:160, 07:199, 08:169, 09:165, 10:182, 12:198, 13:160, 14:160, 15:220,
    16:165, 17:168, 19:184, 20:165, 22:166, 23:165, 25:201, 26:122):
    `python3 /workspace/mcp_bridge.py --list-packs                   # enumerate available packs`
  - `/workspace/mig/cloud-prompts/_shared/RUNTIME-CONTRACT.md:58-60`:
    `Any pack name resolves without a code change — mcp_bridge.py falls back to … . python3 mcp_bridge.py --list-packs enumerates them via the gateway's own discover_tools.`
  - `/workspace/mig/cloud-prompts/cron-prompts/17-us-stocks-in-play.md:176` (live, byte-identical):
    `` `--list-packs` enumerated `tradier`, `fmp` and `market-recap` ``
  - **Observed** (`python3 mcp_bridge.py --list-packs`, default query
    `"market data quotes screener movers"`):
    `{"query":"market data quotes screener movers","packs":{"tradier":["tradier_quote"],"fmp":["stock_screener"],"market-recap":["get_quotes","price_history","top_movers","market_snapshot"]}}`
    — **no `stocktwits`, no `shibui`, no `cftc-cot`**.
  - **Observed, same session, by name:** `python3 mcp_bridge.py stocktwits chart_data a.json` →
    `{"symbol":"SPY","period":"1M","count":23,"first_close":762.63,"last_close":755.72,"change_pct":-0.91,"bars":[…],"source":"StockTwits chart feed (ql.stocktwits.com)"}` (exit 0);
    `python3 mcp_bridge.py shibui stock_data_query b.json` →
    `[{"ticker":"SPY","close":755.72},{"ticker":"SPY","close":769.36},{"ticker":"SPY","close":772.31}]` (exit 0).
  - **Observed, `tools/list` per pack:** `market-recap` → **48** tools, `stocktwits` → **53**,
    `cftc-cot` → **47** (`search_markets`, `latest_report`, `report_history`), `tradier` → **47**,
    `fmp` → **68**, `shibui` (direct host `https://mcp.shibui.finance/mcp`) → **12**.
  - **Observed, discovery is query-sensitive:** `--list-packs "chart_data sentiment trending symbols"`
    → `{stocktwits, twelvedata, gdelt, market-recap}`; `--list-packs "shibui screeners EDGAR"`
    → `{edgar, market-recap}` — **`shibui` never appears**, because it is a separate host and is not
    in the gateway's index.
  - **Observed, unknown pack is distinguishable:** `POST https://gateway.pipeworx.io/nonexistent-pack-zzz/mcp`
    → `{"error":{"code":-32602,"message":"Unknown pack \"nonexistent-pack-zzz\". …"}}`.
- **Why it matters:** the prompt text invites the reader to read a *semantic search result* as a
  *capability inventory*. An agent that runs `--list-packs`, sees only `tradier/fmp/market-recap`,
  and concludes `stocktwits` and `shibui` are gone will **drop two working primary sources** — and in
  the digest prompts that means falling back to a Yahoo path that #17's own copy says is broken.
  It is worse than useless: `shibui` (history to 1962, fundamentals, screeners, EDGAR) and
  `stocktwits` (OHLCV + sentiment/trending) are the two packs with capabilities no other source in
  the fleet provides. The #01 ledger's `<packs OK>` column is fed from this output, so the weekly
  ledger will carry a **false negative for the life of the routine**.
- **Recommended fix:** in every prompt's bridge block, replace
  `python3 /workspace/mcp_bridge.py --list-packs                   # enumerate available packs`
  with
  ```
  # SEMANTIC DISCOVERY, not an inventory — the default query returns only packs whose
  # tools match the query. A pack missing from this output may still be fully reachable.
  # Authoritative per-pack tool list:
  #   curl -s -X POST "https://gateway.pipeworx.io/<pack>/mcp" -H 'Content-Type: application/json' \
  #     -H 'Accept: application/json, text/event-stream' \
  #     -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
  # KNOWN REACHABLE (all verified 2026-11-02): stocktwits (53 tools, gateway), shibui (12 tools,
  # https://mcp.shibui.finance/mcp — NOT in the gateway index, so discovery can never show it),
  # market-recap (48), cftc-cot (47), tradier (47), fmp (68), plus any gateway pack name.
  python3 /workspace/mcp_bridge.py --list-packs "chart_data sentiment trending quotes"  # discovery only
  ```
  and in `_shared/RUNTIME-CONTRACT.md:58-60` replace the "enumerates them" sentence with:
  > `python3 mcp_bridge.py --list-packs` runs a **semantic search** over the gateway's tool
  > catalogue and returns only packs whose tools match the query string. It is **not** an
  > inventory of reachable packs: `stocktwits` is absent from the default query's result and
  > `shibui` (a different host) can never appear in it. For the authoritative per-pack tool list use
  > `tools/list` against the pack's endpoint.
- **Confidence:** high (every claim above is a command output in this session).

### B2 — #01's bridge-packs probe calls `get_quotes` on `shibui`, which has no such tool → permanent false "degradation"
- **Severity:** medium
- **Routines affected:** `01-weekly-mcp-health-check.md` (deployed copy = live copy)
- **Evidence:**
  - `/workspace/mig/cloud-prompts/01-weekly-mcp-health-check.md:99-113`:
    ```
    for p in stocktwits shibui market-recap; do
      printf '%s' '{"symbols":"SPY,QQQ"}' > /tmp/probe.json
      python3 "$BR" "$p" get_quotes /tmp/probe.json 2>&1 | head -c 200; echo
    done
    ```
    followed by: `Record which packs answer and which error. A pack that errors is a **degradation**, not a failure of the routine.`
  - **Observed, running that loop verbatim:**
    - `stocktwits get_quotes` → `{"requested":2,"found":2,"retrieved_at":"2026-11-02T05:43:33.490Z","quotes":[{"symbol":"SPY",…}]}` (**succeeds** — the gateway resolves the tool across the pack set)
    - `shibui get_quotes` → `{"error":"tool_error","detail":[{"text":"Unknown tool: 'get_quotes'","type":"text"}]}` (**errors**)
    - `market-recap get_quotes` → succeeds, same payload
  - **Observed, `tools/list` on `https://mcp.shibui.finance/mcp`** → 12 tools:
    `stock_data_query, get_database_schema, get_query_patterns, load_fundamental_workflow,
    load_technical_workflow, load_screening_workflow, load_comparison_workflow,
    load_earnings_workflow, load_backtesting_workflow, load_filing_workflow,
    load_insider_workflow, export_to_excel` — **no `get_quotes`, by design**.
- **Why it matters:** `shibui` is healthy and will report as "errored" in **every** weekly ledger
  row from now on. The prompt's own wording — "A pack that errors is a degradation" — turns that
  into a permanent false alarm in the one report whose entire purpose is to say what changed. A
  reader learns to ignore the pack table, which is exactly when a real degradation would be missed.
- **Recommended fix:** replace the loop in `01-weekly-mcp-health-check.md:99-113` with a per-pack
  **tool-correct** probe:
  ```bash
  printf '%s' '{"symbols":"SPY,QQQ"}' > /tmp/probe.json
  printf '%s' '{"symbol":"SPY","period":"1m"}' > /tmp/sw.json
  printf '%s' '{"query":"SELECT ticker, close FROM shibui.stock_quotes WHERE ticker = '"'"'SPY'"'"' ORDER BY date DESC LIMIT 3","user_prompt":"latest SPY close"}' > /tmp/sh.json
  printf '%-14s ' stocktwits;  python3 "$BR" stocktwits chart_data       /tmp/sw.json 2>&1 | head -c 120; echo
  printf '%-14s ' shibui;      python3 "$BR" shibui     stock_data_query /tmp/sh.json 2>&1 | head -c 120; echo
  printf '%-14s ' market-recap; python3 "$BR" market-recap get_quotes     /tmp/probe.json 2>&1 | head -c 120; echo
  printf '%-14s ' cftc-cot;    python3 "$BR" cftc-cot    latest_report   /tmp/probe.json 2>&1 | head -c 120; echo
  ```
  and change the recording line to:
  > `Record which packs answer and which error. A pack that errors with "Unknown tool" is a PROBE
  > BUG, not a degradation — re-probe that pack with one of its own tool names before recording it.
  > A pack that errors with a transport error (timeout, 5xx, connection reset) IS a degradation.`
  **The set `stocktwits / shibui / market-recap` is still the right set** — add `cftc-cot` — but the
  tool must match the pack.
- **Confidence:** high.

### B3 — #17's live prompt still states the catalog "exposed 15 tools, ALL media/email" and carries a 9-keyword finance regex
- **Severity:** medium
- **Routines affected:** `17-us-stocks-in-play.md` (repo copy **is** the deployed copy — this text is live now)
- **Evidence:**
  - `/workspace/mig/cloud-prompts/cron-prompts/17-us-stocks-in-play.md:109-113`:
    ```
    only. Verified 2026-10-28: the connector catalog exposed 15 tools, ALL media/email
    (`connector__matrix__*`, `connector__email_workbench_credentials__*`). **Re-verified 2026-10-31:
    the catalog now exposes 133 tools — 118 `connector__github__*` (NEW), 13 media, 2 email.** There is
    ```
    The two sentences sit four lines apart and contradict each other; the stale one is first.
  - `/workspace/mig/cloud-prompts/cron-prompts/17-us-stocks-in-play.md:201` (inline probe regex):
    `re.search(r'yahoo|tradingview|shibui|stocktwits|financekit|finviz|barchart|market|quote',n,re.I)`
  - **Observed:** the deployed prompt for `17-us-stocks-in-play.md` is **byte-identical** to the repo
    file (both 22 197 B) — so lines 110 and 201 are executing on the platform today.
- **Why it matters:** (a) a reader who stops at line 110 concludes there is no GitHub connector, so
  the `#17` routine falls back to a `git`+PAT push path the contract says is unnecessary and
  fragile; (b) the 9-keyword regex at line 201 misses `alpha_vantage`, `fmp`, `polygon` and
  `tiingo` — all financial providers — so if any of those connectors lands, **#17's in-run probe
  will report `finance_tools=0` and #17 will never switch to it.** See **B4**.
- **Recommended fix:** in `17-us-stocks-in-play.md:110-111`, delete the stale clause and keep only
  the current measurement:
  > only. **Re-verified 2026-10-31: the connector catalog exposes 133 tools — 118
  > `connector__github__*` (a built-in GitHub connector, authorized as `karizaco`), 13
  > `connector__matrix__*` (media) and 2 `connector__email_workbench_credentials__*`.** There is
  and at line 201 replace the regex with the fleet-wide canonical one (see **B4**).
- **Confidence:** high.

### B4 — Three different finance-detection regexes in the fleet; `probe_mcp.py`'s `sec_?edgar` keyword is dead code
- **Severity:** medium
- **Routines affected:** `_shared/probe_mcp.py` (used by 19 digest prompts), `01`, `17`
- **Evidence:**
  - `/workspace/mig/cloud-prompts/_shared/probe_mcp.py:42-45` — `FINANCE_RE` has **16** keywords:
    `yahoo|tradingview|shibui|stocktwits|financekit|finviz|barchart|market|quote|alpha_vantage|fmp|polygon|tiingo|tipranks|nasdaq|sec_?edgar`
  - `/workspace/mig/cloud-prompts/_shared/probe_mcp.py:80` — `fin = [n for n in names if any(k in n.lower() for k in FINANCE_RE.split("|"))]`
    → this is a **plain substring test** (`k in n.lower()`), *not* a regex, so the keyword
    `sec_?edgar` is compared as the **literal 10-character string** `"sec_?edgar"`. It can never
    match a tool named `connector__sec_edgar__…` or `mcp__sec_edgar__…`.
  - `/workspace/mig/cloud-prompts/01-weekly-mcp-health-check.md:79` — inline regex, **13** keywords
    (`…|alpha_vantage|fmp|polygon|tiingo`), used with `re.search(..., re.I)` so its `?` would work
    if the keyword were present — it is not.
  - `/workspace/mig/cloud-prompts/cron-prompts/17-us-stocks-in-play.md:201` — inline regex, **9** keywords.
  - **Observed, keyword-set diff:** only in `probe_mcp.py` = `{nasdaq, sec_?edgar, tipranks}`;
    only in #01 = `{}`; only in #17 = `{}` (i.e. #17 ⊂ #01 ⊂ probe_mcp.py).
  - **Observed, behaviour on synthetic tool names** (probe = substring, #01 = regex):
    | tool_name | probe_mcp.py | #01 inline | #17 inline | divergence |
    |---|---|---|---|---|
    | `connector__nasdaq__get_quote` | True | True | True | — |
    | `connector__tipranks__analyst_ratings` | True | **False** | **False** | #01/#17 miss a financial connector |
    | `connector__sec_edgar__full_text_search` | **False** (dead `?`) | **False** | **False** | nobody catches it |
    | `connector__matrix__generate_image` | False | False | False | — |
- **Why it matters:** the two probes are the **fast lane** and the **slow lane** for the one question
  the fleet cares about ("has a financial MCP landed yet?"). They disagree about the answer, and
  #17's narrower copy would miss a `tipranks` connector outright. The `sec_?edgar` dead keyword
  means nobody — not even the widest probe — would ever notice a `sec_edgar` connector landing.
  `probe_mcp.py` is also the file the digest prompts fetch and run on **every** fire — and, per
  **B5**, it is in **0 of 23** deployed prompts today.
- **Recommended fix:** make the keyword list a single shared constant and use one matching
  semantic everywhere.
  1. In `/workspace/mig/cloud-prompts/_shared/probe_mcp.py`, replace the literal `sec_?edgar` with
     `sec_edgar` **and** change line 80 from substring matching to regex matching so the `?`
     pattern works:
     ```python
     FINANCE_RE = re.compile(
         r"yahoo|tradingview|shibui|stocktwits|financekit|finviz|barchart|market|quote|"
         r"alpha_vantage|fmp|polygon|tiingo|tipranks|nasdaq|sec_?edgar", re.I)
     ...
     fin = [n for n in names if FINANCE_RE.search(n)]
     ```
  2. Point the inline probes in `01-weekly-mcp-health-check.md:79` and
     `17-us-stocks-in-play.md:201` at the **same** keyword list — best by having both call
     `python3 /workspace/probe_mcp.py --no-bridge --json` instead of duplicating the regex inline,
     and if an inline copy must stay, paste the identical 16-keyword string into all three places
     with a comment `# KEEP IN SYNC with _shared/probe_mcp.py FINANCE_RE`.
- **Confidence:** high.

### B5 — The deployed copies of 18 routines assert a dead catalog composition and a dead Yahoo-429 condition; a repo fix reaches 2 of 23
- **Severity:** high
- **Routines affected:** 02, 04, 05, 06, 07, 08, 09, 10, 12, 13, 14, 15, 16, 19, 20, 22, 23, 25
  (18 routines; #26 has an older variant; #17, #90 are identical to repo; #01, #91 differ in other ways)
- **Evidence:**
  - **Deployed, live** (from `cron_read view=list`, chunk
    `call_01a196fdb3f37774aef04a72/chunks/000000.txt`), e.g. for `02-asia-pre-market-reactions.md`:
    > `only. Verified 2026-10-28: the connector catalog exposes 15 tools, ALL media/email`
    > `(**connector__matrix__**, **connector__email_workbench_credentials__**). There is **no** …`
    and
    > `**Measured 2026-10-28 from this sandbox — Yahoo's JSON endpoints return HTTP 429** (spark,`
    > `chart, and screener alike), with and without a browser User-Agent and after a 60 s pause: it is`
    > `persistent rate limiting, not a transient burst.`
  - **Repo, live** (`cron-prompts/02-asia-pre-market-reactions.md:93-99, 106-110`) says 133 tools and
    "Yahoo's JSON endpoints are working again".
  - **Observed today, contradicting the deployed text:**
    - Yahoo chart 5d → **200**; Yahoo chart 5m → **200**; Yahoo screener `day_gainers` → **200**
      (270 808 B); Yahoo screener `most_actives` → **200**; Yahoo spark 12 syms → **200**;
      Yahoo quoteSummary + crumb → **200** (5 088 B); Yahoo options + crumb → **200** (71 274 B).
    - Yahoo quoteSummary **without** crumb → **401** (so the crumb is still required — the deployed
      text is right that Yahoo JSON is not unconditionally open, wrong that it is *rate-limited*).
    - The catalog itself cannot be enumerated here: `mcode-tools` is not installed (see **B6**),
      so "15 tools" is not merely stale, it is **unfalsifiable from the runtime that would run it**.
  - **Observed, diff magnitude** (repo → deployed, `difflib.unified_diff`): `#02` 78 diff lines; the
    deployed copy is missing the entire `### MCP AVAILABILITY PROBE` block, the entire `market-recap`
    bridge block, the entire Barchart block, and the `connector__github__*` push guidance.
    `#25` shows the largest gap: 24 567 B repo → 18 110 B deployed (**6 457 B**, the whole
    market-recap + Barchart + probe_mcp addition).
  - **Observed, per-routine presence in the deployed prompts** (corrected totals, see the table
    above): `market-recap` missing in **19/23**; Barchart missing in **21/23**; **`probe_mcp` missing
    in 23/23 — it appears in no deployed prompt at all.**
- **Why it matters:** the deployed copies are what actually runs. They tell 18 routines to (a)
  believe there is no GitHub connector, so they take the fragile `git`+PAT push path instead of
  `connector__github__create_or_update_file`; (b) skip Yahoo JSON entirely and start at the Nasdaq
  API / Yahoo HTML / `web_search` rungs — **3–4 extra HTTP calls per symbol** on the bulk path,
  which is the single largest token/latency cost in the fleet; (c) never call `market-recap`,
  the one source that returns `previous_close`, `change_pct`, `as_of` and `market_state` in a
  single call, so `change_pct` has to be recomputed by hand; and (d) run **no in-run MCP
  availability probe whatsoever**, so the fleet has no fast lane at all. And critically: **editing
  the repo file changes nothing**, because the platform copy is a separate artifact — so a reviewer
  who reads the repo, sees it corrected, and ships will believe the fleet is fixed when it is not.
- **Recommended fix:** treat the repo file as the **source** and the platform prompt as a **deployed
  artifact that must be re-applied**, with a hash check. Two concrete steps:
  1. Adopt the same triple-match discipline the repo already uses for `#91`:
     `git source == local backup == platform copy`, one SHA-256 per routine, checked after every
     write (a `cron_update` returning `{"ok": true}` says the write landed, not that the bytes are
     right — this is a known failure mode in this fleet).
  2. Add to `_shared/RUNTIME-CONTRACT.md` a new section:
     > ### 2g. Repo ≠ deployed
     > The 23 cron prompts exist in two places: `cloud-prompts/cron-prompts/*.md` in this repo, and
     > the **live scheduled tasks on agent.minimax.io**. They are separate artifacts and they
     > drift. As of 2026-11-02 only **2 of 23** were byte-identical; 18 deployed copies still
     > asserted "the connector catalog exposes 15 tools" and "Yahoo's JSON endpoints return HTTP
     > 429"; the `probe_mcp.py` fast lane was present in **0 of 23** deployed prompts. A repo edit
     > does **not** reach the fleet. After any repo prompt edit, re-apply it to the scheduled task
     > and verify with `cron_read view=list` → `response.tasks[task_id].prompt` → SHA-256 against
     > the repo file.
- **Confidence:** high.

### B6 — `mcode-tools` is not installed in this sandbox, so *both* the catalog probe and the connector-write path are structurally unavailable
- **Severity:** high
- **Routines affected:** `01` (Step 1), `02/04/05/06/07/08/09/10/12/13/14/15/16/17/19/20/22/23/25/26`
  (in-run `probe_mcp.py` fast lane + `connector__github__*` writes), `cron-ops.md`
- **Evidence:**
  - `/workspace/mig/cloud-prompts/01-weekly-mcp-health-check.md:71`:
    `mcode-tools connector tools 2>/dev/null | python3 -c "…"`
  - `/workspace/mig/cloud-prompts/_shared/RUNTIME-CONTRACT.md:207`:
    `mcode-tools connector call connector__github__create_or_update_file --args-file <file>`
  - **Observed:** `command -v mcode-tools` → *not found*; `mcode-tools connector tools` →
    `/bin/bash: line 1: mcode-tools: command not found` (exit 127). `find / -name 'mcode*' -type f`
    returns only TypeScript sources under `/app/packages/` — no CLI entry point.
  - **Observed, the three-state design behaves correctly:**
    `probe_mcp.py` `probe_catalog()` → `{'state': 'catalog_unreachable', 'detail': "[Errno 2] No such file or directory: 'mcode-tools'"}`
    and #01's inline pipeline prints exactly `catalog_unreachable`.
    → **the three-state distinction is doing its job**; the fleet will not record a false "no MCPs exist".
  - **Observed, the direct API is also closed:** `https://agent.minimax.io/minimax-cloud/api/v1/connectors/connected-tools/list`
    → **404**; `/api/v1/connectors/connected-tools/list` → **404**.
  - **Observed, `tool_search` exposes no connector tools:** queries `connector tools catalog list`,
    `github`, `file contents repository read list`, and regex
    `connector|mcode|github|finance|stock` → **0 hits, total=0** in every case.
- **Why it matters:** the fast lane and the slow lane of the MCP-availability check **cannot run at
  all** in this runtime — not because the catalog is empty, but because the probe binary is absent.
  The contract's "133 tools: 118 GitHub, 13 media, 2 email" is therefore **unverifiable from the
  cron sandbox**, and any routine that depends on `connector__github__*` for its push is depending
  on a path this sandbox does not expose. `cron-ops.md:80` documents
  `mcode-tools connector call <tool> --args-file <file>` as *the* replacement for the PAT push.
- **Recommended fix:** (1) Add a **preflight** to the contract and to #01 Step 1:
  > ```bash
  > command -v mcode-tools >/dev/null 2>&1 || { echo "PROBE_UNAVAILABLE: mcode-tools not on PATH"; exit 3; }
  > ```
  > and add a **fourth** catalog state, `probe_unavailable`, distinct from `catalog_unreachable`:
  > a missing binary is a broken probe, and must never be recorded as "no MCPs exist".
  (2) Make the connector path **optional** with a declared fallback — the git+PAT block is already
  > in every prompt, so the GitHub connector should be documented as *"use if `mcode-tools` is
  > present, otherwise use the git block"*, not as a replacement. (3) Re-measure the catalog count
  > and record the measurement date in the same file that asserts it, so the next reader knows how
  > old the number is.
- **Confidence:** high for "not installed in this sandbox"; **medium** for "not installed in the
  cron-fire sandbox" (the two sandboxes may differ — this audit ran in the workspace sandbox, not a
  scheduled-task fire).

### B7 — "Playwright and the chromium build are already installed … No install step needed" and "`uv`/`uvx` are already installed at `/usr/local/bin/`" are false in this sandbox
- **Severity:** medium
- **Routines affected:** 02, 04, 05 (and any routine using `barchart_fetch.py`); 12 (`financekit` via `uvx`)
- **Evidence:**
  - `/workspace/mig/cloud-prompts/_shared/RUNTIME-CONTRACT.md:133-135`:
    > `playwright` and the chromium build are **already installed** in the cloud sandbox:
    > `/usr/local/lib/python3.11/dist-packages/playwright/` and
    > `/root/.cache/ms-playwright/chromium-1243/chrome-linux/chrome`. No install step needed.
  - `/workspace/mig/cloud-prompts/_shared/RUNTIME-CONTRACT.md:166-167`:
    > `uv` and `uvx` 0.12.17 are **already installed** at `/usr/local/bin/`.
  - `/workspace/mig/cloud-prompts/cron-prompts/12-cross-asset-correlation-snapshot.md:109`:
    > `financekit.correlation_matrix` (which is not bound as a TOOL in this runtime but **IS reachable** — `uvx --from financekit-mcp financekit` installs and speaks MCP over stdio …)`
  - **Observed:**
    - `ls /usr/local/lib/python3.11/dist-packages/playwright/` → *No such file or directory*;
      `python3 -c "import playwright"` → `ModuleNotFoundError: No module named 'playwright'`;
      `ls /root/.cache/ms-playwright` → *No such file or directory*; no `chromium`/`chrome`/`headless_shell`
      on `PATH`; `find / -name 'chrome-linux' -type d` → empty.
    - `ls /usr/local/bin/ | grep -E '^uv'` → **empty**; `command -v uv uvx` → not found.
    - **The browser is not installable from Python here:** `python3 -m pip` → `No module named pip`;
      `python3 -m ensurepip` → `No module named ensurepip`; `command -v pip pip3` → not found;
      `find / -name 'playwright*.whl'` → **no cached wheel**. So the contract's Python-playwright
      path cannot be repaired by installing a package in this runtime.
    - **The real browser had to be installed by hand:**
      `/app/node_modules/.bin/playwright install chromium` downloaded 112 MiB to
      `/workspace/.home/.cache/ms-playwright/chromium-1217/chrome-linux64/chrome` — note the path is
      **not** `/root/.cache/ms-playwright` and the build is **1217 / Chrome 147**, not the claimed
      `1243`. The first launch then failed with
      `error while loading shared libraries: libnspr4.so: cannot open shared object file` until
      `apt-get install libnspr4 libnss3 …` was run — **a system-library install step the contract
      does not mention at all**.
    - **What IS preinstalled and works:** **Node Playwright 1.59.1** at `/app/node_modules/playwright`
      (binary `/app/node_modules/.bin/playwright`), which is what I used to reach Barchart.
      **The contract never mentions the Node package at all** — see **B8**.
- **Why it matters:** #12 tells the agent that `financekit.correlation_matrix` "IS reachable" via
  `uvx`, with no install step and no fallback. In this runtime `uvx` does not exist, so the agent
  burns a turn discovering that and then has to improvise a correlation matrix from Yahoo chart
  data — which is precisely the "improvise the procedure" failure the prompts warn against.
  For Barchart, the missing browser **and** the missing system libs mean a routine that follows
  the contract literally produces `no_chromium` and drops a listed primary source.
- **Recommended fix:** replace `_shared/RUNTIME-CONTRACT.md:133-135` with:
  > ### 2c-0. Browser-backed sources — PREFLIGHT FIRST
  > Chromium is **not** guaranteed to be present, and the **Node** Playwright package is the one
  > that ships (`/app/node_modules/playwright`, v1.59.1). The **Python** package does **not** ship
  > and cannot be installed here — `pip` and `ensurepip` are both absent and no wheel is cached.
  > Run this before any Barchart step:
  > ```bash
  > command -v mcode-tools >/dev/null || echo "NO mcode-tools"
  > node -e "require('/app/node_modules/playwright')" 2>/dev/null \
  >   && echo "node playwright OK" || echo "NO node playwright"
  > ls "${PLAYWRIGHT_BROWSERS_PATH:-/root/.cache/ms-playwright}"/*/*/chrome 2>/dev/null \
  >   || ls /workspace/.home/.cache/ms-playwright/*/*/chrome 2>/dev/null \
  >   || echo "NO chromium build"
  > ```
  > If the browser is missing, **skip Barchart and say so in `## Source health`** — do not improvise
  > a price. A `libnspr4.so` load failure means the system libraries are missing too:
  > `apt-get install -y libnspr4 libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2
  > libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 libpango-1.0-0
  > libcairo2 libasound2`.
  And change `_shared/RUNTIME-CONTRACT.md:166` to:
  > `uv`/`uvx` may or may not be present. Check `command -v uvx` first. If absent, the
  > `financekit` / `tradingview-mcp` MCPs are **unavailable in this run** — record
  > `failed:uvx_absent` in Source health and fall back to the Yahoo-chart correlation the prompt
  > already describes. Do not claim the MCP is reachable without running it.
- **Confidence:** high for the state of this sandbox; **medium** for whether the cron-fire sandbox
  image differs (the contract's own 2026-10-31 measurement was taken in a different session).

### B8 — The shipped `_shared/barchart_fetch.py` cannot run in this runtime: two independent blockers, so the only sanctioned Barchart path for routines 02/04/05 is dead
- **Severity:** high
- **Routines affected:** 02, 04, 05 (and every prompt that names `_shared/barchart_fetch.py`)
- **Evidence:**
  - The prompts run this and only this:
    - `/workspace/mig/cloud-prompts/cron-prompts/02-asia-pre-market-reactions.md:167-171`:
      ```
      # --- Barchart (AWS-WAF blocked for plain curl; works via headless chromium) ---
      curl -s -o /workspace/barchart_fetch.py \
        https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/barchart_fetch.py
      python3 /workspace/barchart_fetch.py --symbols SPY,QQQ,AAPL    # batch quotes
      python3 /workspace/barchart_fetch.py --list top-gainers --limit 20
      ```
    (same block at 04:167-171, 05:167-171; the raw URL returns **200**, 7 500 B — the file downloads
    fine, it just cannot run.)
  - **Blocker 1 — a legacy chromium glob.** `/workspace/mig/cloud-prompts/_shared/barchart_fetch.py:75`:
    ```python
    hits = sorted(glob.glob(os.path.join(root, "chromium-*/chrome-linux/chrome")))
    ```
    **Observed:**
    ```
    root=/root/.cache/ms-playwright          script glob 'chromium-*/chrome-linux/chrome' -> []
    root=/workspace/.home/.cache/ms-playwright  script glob 'chromium-*/chrome-linux/chrome' -> []
                                             real   glob 'chromium-*/*/chrome' -> ['chrome-linux64/chrome']
    with PLAYWRIGHT_BROWSERS_PATH=/workspace/.home/.cache/ms-playwright -> script glob = []  (EMPTY => no_chromium)
    ```
    The real layout is `chromium-1217/chrome-linux64/chrome`; the script only knows the pre-1.49
    `chrome-linux/chrome`. The script's own `roots` list already contains
    `/workspace/.home/.cache/ms-playwright` (line 71) — so the path was right and the **glob pattern**
    was wrong.
  - **Blocker 2 — a hard dependency on the *Python* `playwright` package.**
    `/workspace/mig/cloud-prompts/_shared/barchart_fetch.py:131`:
    ```python
    from playwright.sync_api import sync_playwright
    ```
    **Observed:** `python3 -c "from playwright.sync_api import sync_playwright"` →
    `ModuleNotFoundError: No module named 'playwright'`. The image ships **Node** Playwright only.
  - **Observed, the two blockers fail sequentially** (glob patched in a copy, blocker 2 still active):
    ```
    $ python3 barchart_fetch.py --symbols SPY,QQQ,AAPL
    {"error": "no_chromium", "detail": "playwright chromium not found; set PLAYWRIGHT_BROWSERS_PATH"}   EXIT=2
    $ PLAYWRIGHT_BROWSERS_PATH=/workspace/.home/.cache/ms-playwright python3 barchart_fetch_patched.py --symbols SPY,QQQ,AAPL
    {"error": "no_playwright", "detail": "No module named 'playwright'"}                                 EXIT=2
    ```
  - **Observed, the same false claim is in the helper's own docstring**,
    `/workspace/mig/cloud-prompts/_shared/barchart_fetch.py:12-17`:
    > `The fix is to let a real browser engine solve the challenge. Playwright and the`
    > `chromium build are already installed in the cloud sandbox, so this script needs no`
    > `install step:`
    > `    /usr/local/lib/python3.11/dist-packages/playwright/`
    > `    /root/.cache/ms-playwright/chromium-1243/chrome-linux/chrome`
    → the same two non-existent paths as the contract (**B7**), plus the same false "no install step".
  - **Observed, Barchart itself is fine** — proven with a Node script that bypasses the helper:
    realistic Chrome UA + 1700×1200 viewport → page **202**, title
    `SPY - SPDR S&P 500 ETF Price - Barchart.com`, **20 cookies** incl. `aws-waf-token`;
    `core-api` → **200** `{"count":3,"total":3,"data":[{"symbol":"SPY","lastPrice":"755.72","volume":"77,696,400"},…]}`;
    movers list → **200** `{"count":20,"total":200,"data":[{"symbol":"CHOW","percentChange":"+106.57%"},…]}`.
    With Playwright's **default** headless-shell UA the same call returns **403** "Request blocked"
    with **0 cookies** — so the UA matters and is undocumented.
- **Why it matters:** the helper is the **only** sanctioned Barchart path in routines 02/04/05, and
  it exits 2 on every run. A routine following the prompt literally drops Barchart — the listed
  Finviz replacement for movers/screens — and the failure looks like "Barchart is blocked" (which is
  true for curl) rather than "our helper is broken". Because **no** deployed prompt contains the
  Barchart block (**B5**: missing in 21/23, present only in #01 and #17), the live fleet currently
  loses this source anyway — but the repo fix that would *restore* it ships a helper that still
  cannot run. Fixing the prompt without fixing the helper would look successful and stay broken.
- **Recommended fix:** replace the Python helper with a **Node** implementation (Node Playwright is
  what actually ships), keeping the CLI contract identical. A tested drop-in is at
  `/workspace/audit/scratch/barchart_fetch.js` — it reproduces the same `--symbols` / `--list` /
  `--discover` interface, the same `LIST_MAP`, the same `UA`, the same `core-api` call from the page
  context, and the same exit-code semantics (0 = success JSON, 1 = API error, 2 = no browser).
  Verified:
  ```
  $ node barchart_fetch.js --symbols SPY,QQQ,AAPL
  {"count":3,"total":3,"data":[{"symbol":"SPY","lastPrice":"755.72","volume":"77,696,400"},…]}
  $ node barchart_fetch.js --list top-gainers --limit 20
  {"count":20,"total":200,"data":[{"symbol":"CHOW","symbolName":"Chowchow Cloud International Holdings Ltd","percentChange":"+106.57%",…},…]}
  ```
  Publish it as `cloud-prompts/_shared/barchart_fetch.js` and change the prompt block in 02/04/05 to:
  ```bash
  curl -s -o /workspace/barchart_fetch.js \
    https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/barchart_fetch.js
  node /workspace/barchart_fetch.js --symbols SPY,QQQ,AAPL
  node /workspace/barchart_fetch.js --list top-gainers --limit 20
  ```
  If the Python helper is kept instead, it needs **both**: the glob at line 75 changed to
  `chromium-*/*/chrome` (and `chromium_headless_shell-*/*/chrome-headless-shell`), **and** the
  Python `playwright` package — which cannot be installed here (no `pip`, no `ensurepip`, no cached
  wheel), so that route is not viable in this runtime.
- **Confidence:** high (both blockers reproduced directly and in sequence).

### B9 — #91's STEP 1 chunk-discovery command can select the wrong tool-result file and abort the detector
- **Severity:** medium
- **Routines affected:** `91-schedule-drift-guard.md`
- **Evidence:**
  - `/workspace/mig/cloud-prompts/cron-prompts/91-schedule-drift-guard.md:88-93`:
    ```bash
    # the newest tool-result chunk file holds the raw JSON of the cron_read above
    CHUNK=$(ls -t /workspace/.mavis/tool-results/*/*/chunks/*.txt 2>/dev/null | head -1)
    ```
  - **Observed, live in this session:**
    ```
    $ ls -lt --time-style=+%H:%M:%S /workspace/.mavis/tool-results/*/*/chunks/*.txt
    -rw-r--r-- 1 root root  60007 12:03:27 .../call_01a196fe39ea746791453f1d/chunks/000000.txt   <- session list
    -rw-r--r-- 1 root root 466798 12:02:51 .../call_01a196fdb3f37774aef04a72/chunks/000000.txt   <- cron_read
    $ python3 schedule-drift.py --tasks "$CHUNK"
    ERROR: no task list found in the JSON
    EXIT=2
    ```
    With the **correct** chunk (the `cron_read` one, 466 798 B):
    ```
    checked 23 routines against the ground truth
    OK: no schedule drift
    RESULT: schedule_drift=0 unknown=0 missing=0 session_mode=0 conv_reuse=0 routines_with_runs=0
    EXIT=0
    ```
    → the detector and the ground truth are correct (23/23, no drift, no unknown, no missing);
    only the **chunk-selection command** is fragile, because `ls -t | head -1` picks whatever was
    written last, and any later `mcp_invoke` (the `tool_search` fallback, a `session_update` title
    call, a `cron_read view=runs` call from the repo's own STEP 2b) writes a newer chunk.
- **Why it matters:** #91 is the routine that repairs the other 22. A `ls -t` that lands on a
  non-`cron_read` chunk exits 2 and the prompt's fallback ("print the file's first 400 characters
  and adapt") puts the agent into manual mode on the most critical check in the fleet. Note the
  repo's own STEP 2b (not deployed — see **B10**) makes this materially more likely, because it
  issues 23 additional `cron_read view=runs` calls.
- **Recommended fix:** replace `91-schedule-drift-guard.md:88-93` with a content-aware selector:
  ```bash
  CHUNK=""
  for f in $(ls -t /workspace/.mavis/tool-results/*/*/chunks/*.txt 2>/dev/null | head -20); do
    if grep -q '"tasks"' "$f" 2>/dev/null; then CHUNK="$f"; break; fi
  done
  [ -n "$CHUNK" ] || { echo "ERROR: no cron_read chunk with a tasks array"; exit 2; }
  echo "chunk: $CHUNK"; wc -c "$CHUNK"
  ```
  and, in STEP 2, re-run the selector immediately before the detector so the two steps cannot
  disagree.
- **Confidence:** high (reproduced end-to-end in this session).

### B10 — The deployed #91 lacks the conversation-hygiene capability the repo detector already implements
- **Severity:** medium
- **Routines affected:** `91-schedule-drift-guard.md` (deployed copy)
- **Evidence:**
  - **Deployed (live):** `Exit codes: 0 = no drift, 1 = drift found, 2 = input error.` — and no
    `## CONVERSATION TITLE` step, no STEP 2b.
  - **Repo:** `cron-prompts/91-schedule-drift-guard.md:129` —
    `Exit codes: 0 = no drift and no conversation findings, 1 = findings, 2 = input error.`
    plus `:133` "see STEP 2b", `:139` `## STEP 2b — CONVERSATION HYGIENE`, and `:7`
    `## CONVERSATION TITLE (do this FIRST, before anything else)`.
  - **Observed, the deployed detector itself emits the extra finding classes**
    (`/workspace/mig/tools/schedule-drift.py:75-77`):
    ```
    DRIFT        schedule/timezone drift -- repairable with cron_update
    SESSION-MODE live session mode != ground truth -- REPORT, never auto-repair
    CONV-REUSE   two runs of one routine share a session_id -- REUSE CONFIRMED
    ```
    and it accepts `--runs-file` (`tools/schedule-drift.py:279`) and `--run-chunks` (`:277`).
    `raw.githubusercontent.com/…/main/tools/schedule-drift.py` → **200**, 19 753 B — i.e. the
    detector the deployed prompt fetches **is the new one**; only the prompt is old.
  - **Observed, the detector runs clean against today's live scheduler** with the correct chunk:
    `checked 23 routines against the ground truth / OK: no schedule drift / RESULT: schedule_drift=0
    unknown=0 missing=0 session_mode=0 conv_reuse=0 routines_with_runs=0` (exit 0).
- **Why it matters:** the deployed #91 tells the agent that exit 1 means "drift found" and nothing
  else. The detector it runs can also exit 1 on `SESSION-MODE` and `CONV-REUSE` — findings that
  must be **reported but never auto-repaired**, and that in a `SESSION-MODE` case would otherwise be
  misread as schedule drift and "repaired" with a `cron_update` that rewrites a deliberately fixed
  conversation binding (the repo's own CRITICAL REMINDER 9: "Never repair a session binding").
  The whole second job of #91 (conversation hygiene) is simply absent from the deployed copy.
- **Recommended fix:** re-apply the repo's `91-schedule-drift-guard.md` to the scheduled task
  (see **B5** for the hash-check discipline), and add the missing detector vocabulary to the
  deployed copy's exit-code legend:
  > Exit codes: `0` = no drift and no conversation findings, `1` = findings, `2` = input error.
  > **Read the prefixes, not just the exit code.** `DRIFT` is schedule drift (repairable with
  > `cron_update` — send only `task_id`, `schedule`, `timezone`). `SESSION-MODE` is a
  > conversation-binding violation: REPORT, never repair. `CONV-REUSE` is a reused conversation:
  > report only, and only after confirming it with a fresh `view=runs` call.
- **Confidence:** high.

### B11 — The contract's `stocktwits` row advertises a "sentiment" tool that does not exist
- **Severity:** low
- **Routines affected:** all prompts carrying the bridge block (02, 04, 05, 06, 07, 08, 09, 10, 12,
  13, 14, 15, 16, 17, 19, 20, 22, 23, 25, 26)
- **Evidence:**
  - `/workspace/mig/cloud-prompts/_shared/RUNTIME-CONTRACT.md:51`:
    > | `stocktwits` | `https://gateway.pipeworx.io/stocktwits/mcp` | 53 tools — chart_data, sentiment, trending |
  - Every prompt's bridge block, e.g. `cron-prompts/02-asia-pre-market-reactions.md:155`:
    `python3 /workspace/mcp_bridge.py stocktwits chart_data a.json      # OHLCV, sentiment, trending`
  - **Observed, `tools/list` on the stocktwits pack (53 tools):** the pack-specific names are
    `symbol_stream, user_stream, trending_symbols, trending_messages, suggested_symbols,
    symbol_search, chart_data, watchlists, watchlist` — **there is no `sentiment` tool**, and no
    tool whose name contains "trending" other than `trending_symbols` / `trending_messages`.
  - **Observed, `chart_data` output keys:** `['symbol','period','count','first_close','last_close',
    'change_pct','bars','source']` — **no sentiment field**, and no trending either.
    (Example: `{"symbol":"SPY","period":"1M","count":23,"first_close":762.63,"last_close":755.72,
    "change_pct":-0.91,"source":"StockTwits chart feed (ql.stocktwits.com)"}`.)
- **Why it matters:** low — the pack really does expose sentiment data, but under the tool names
  `trending_messages` / `symbol_stream` / `user_stream`, not `sentiment`, and `chart_data` returns
  only OHLCV. An agent that trusts the comment calls `chart_data` expecting sentiment and trending
  and finds neither, then either reports "no sentiment available" (wrong — it is) or spends turns
  hunting for a `sentiment` tool that does not exist.
- **Recommended fix:** in `_shared/RUNTIME-CONTRACT.md:51` change the row to:
  > | `stocktwits` | `https://gateway.pipeworx.io/stocktwits/mcp` | 53 tools. Pack-specific: `chart_data` (OHLCV only — keys `symbol, period, count, first_close, last_close, change_pct, bars, source`; **no sentiment field**), `trending_symbols`, `trending_messages` (sentiment lives here), `symbol_stream`, `user_stream`, `symbol_search`, `watchlists`. |
  and in every prompt's bridge block change the comment to
  `python3 /workspace/mcp_bridge.py stocktwits chart_data a.json      # OHLCV only (no sentiment)`
  plus one added line
  `python3 /workspace/mcp_bridge.py stocktwits trending_messages a.json   # sentiment + trending`.
- **Confidence:** high.

### B12 — Two repo prompts still assert the old 15-tool catalogue internally, contradicting their own corrected section
- **Severity:** low
- **Routines affected:** `07-stock-screener-focus-rvol-09:45.md`, `19-earnings-reminder-daily.md`
  (and `15-earnings-reaction-scanner.md` in the same "old-composition" family)
- **Evidence:**
  - `/workspace/mig/cloud-prompts/cron-prompts/07-stock-screener-focus-rvol-09:45.md:91-93`:
    > `provably absent in Cloud sessions: mcode-tools connector tools returns partial=false,`
    > `provider_failures=[], with only connector__matrix__* and connector__email_workbench_credentials__*,`
    > `and tool_search returns 0 hits for every finance keyword.`
    …but the same file at `:128-131` says `the connector catalog exposes **133 tools** — 118
    `connector__github__*` …, 13 `connector__matrix__*` (media) and 2
    `connector__email_workbench_credentials__*``. Both are in the region of interest (before
    `### PRIMARY SOURCE` at `:169`).
  - `/workspace/mig/cloud-prompts/cron-prompts/19-earnings-reminder-daily.md:96-98`:
    > `` `mcode-tools connector tools` returns `partial=false, provider_failures=[]` with only
    > `connector__matrix__*` and `connector__email_workbench_credentials__*` ``
    …against `:113-116` ("133 tools").
  - `/workspace/mig/cloud-prompts/cron-prompts/15-earnings-reaction-scanner.md:61-63`:
    > `` `mcode-tools connector tools` holds only media + credential tools `` (2026-10-24).
  - **Observed:** `grep -c` per file — both #07 and #19 contain `provider_failures` **1×** and
    `133 tools` **1×**. So the contradiction is live in the repo, and #07/#19's deployed copies
    also carry the old sentence (their deployed copies still say "15 tools").
- **Why it matters:** low-to-medium. These are *internal* contradictions inside the metainstructions
  a routine reads top-to-bottom: the same document tells the agent both "the catalog holds only
  media + email" and "the catalog holds 118 GitHub tools". A routine that reads STEP 5 first is
  told to "not burn turns re-testing" the MCPs — correct — but is also left believing the GitHub
  connector does not exist, which contradicts the push guidance later in the same file.
- **Recommended fix:** in #07 `:91-93`, #19 `:96-98` and #15 `:61-63`, replace the catalogue
  composition with the current one and move the "don't re-test these MCPs" instruction to stand on
  its own:
  > `mcp__tradingview_advanced__*`, `mcp__tradingview__*` and `mcp__yahoo_finance__*` are
  > provably absent in Cloud sessions — `tool_search` returns 0 hits for every finance keyword.
  > Do not burn turns re-testing them. (The connector catalog now holds 133 tools: 118
  > `connector__github__*`, 13 media, 2 email — and still **no** financial MCP.)
- **Confidence:** high.

### B13 — `www.sec.gov` needs a *contact-style* User-Agent; the contract states "200 OK" with no UA requirement, and the prompts' wording ("needs a User-Agent header") is satisfied by a browser UA that gets a deterministic 403
- **Severity:** medium
- **Routines affected:** every routine that uses SEC EDGAR — 02, 04, 05, 06, 07, 08, 09, 10, 12, 13,
  14, 15, 16, 17, 19, 20, 22, 23, 25, 26 (all of them name SEC EDGAR in the data-source contract);
  plus `_shared/RUNTIME-CONTRACT.md` §2a rows 81–82 and §2b row 108
- **Evidence:**
  - `/workspace/mig/cloud-prompts/_shared/RUNTIME-CONTRACT.md:80-82`:
    > `| **SEC EDGAR full-text** | https://efts.sec.gov/… | **200 OK** — 8-K hits with date/form/CIK/accession |`
    > `| **SEC EDGAR ticker→CIK** | https://www.sec.gov/files/company_tickers.json | **200 OK** |`
    > `| **SEC EDGAR 8-K Atom** | https://www.sec.gov/cgi-bin/browse-edgar?… | **200 OK** — CIK must be zero-padded to 10 digits |`
    and `:108` `| SEC EDGAR | https://data.sec.gov/submissions/CIK{10DIGITS}.json | **200 OK** — needs a User-Agent header |`
    → **no User-Agent is specified for the `www.sec.gov` rows**, and the only UA shown anywhere in
    the contract is a *browser* UA, in the Yahoo crumb recipe (§2a).
  - The prompts repeat the weaker wording 20 times, e.g.
    `/workspace/mig/cloud-prompts/cron-prompts/02-asia-pre-market-reactions.md:117`:
    `EDGAR full-text + per-company 8-K Atom (needs a User-Agent header), CoinGecko (crypto),`
    → a browser UA satisfies "needs a User-Agent header" and still fails.
  - **Observed, a full User-Agent matrix on the two `www.sec.gov` endpoints** (3 tries each, all
    identical):
    ```
    https://www.sec.gov/files/company_tickers.json
      curl/8.14.1                                          -> 403  403  403
      Mozilla/5.0                                          -> 403  403  403
      Mozilla/5.0 (Windows NT 10.0; Win64; x64) …Chrome/120… -> 403  403  403   <- the UA the contract itself shows
      Mavis                                                -> 403  403  403
      Mavis Audit Bot mavis@example.com                    -> 200  200  200
    https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0000320193&type=8-K&output=atom
      Mozilla/5.0                                          -> 403
      Mavis Audit Bot mavis@example.com                    -> 200   (65 954 B, <feed>)
    ```
    **Observed, the other two SEC hosts do NOT need it:**
    ```
    https://efts.sec.gov/LATEST/search-index?q=…&forms=8-K   Mozilla/5.0 -> 200 | contact UA -> 200
    https://data.sec.gov/submissions/CIK0000320193.json       Mozilla/5.0 -> 200 | contact UA -> 200
    ```
  - The 403 body is SEC's standard 1 925 B "Request Rate Threshold Exceeded"-style block page, not a
    rate limit — the block is **deterministic across 3 tries and 5 distinct UAs**.
- **Why it matters:** the earnings and filings routines (15, 19, 23, 25) fetch 8-K Atom feeds and
  ticker→CIK mappings from `www.sec.gov`. A routine that does what the prompt says — send a
  User-Agent, because the prompt says "needs a User-Agent header" — will most naturally send
  `Mozilla/5.0` and get a **403 on every call**. The failure looks like "SEC is down" or "we are
  rate-limited", so the routine silently drops the filings section of its artifact, or falls back to
  `web_search` and burns turns. `efts.sec.gov` full-text works either way, which makes the failure
  look intermittent and *source-specific*.
- **Recommended fix:** state the UA requirement explicitly in the contract and in every prompt that
  names EDGAR. In `_shared/RUNTIME-CONTRACT.md:80-82`, change the two `www.sec.gov` rows to:
  > | **SEC EDGAR ticker→CIK** | `https://www.sec.gov/files/company_tickers.json` | **200 OK — but only with a CONTACT User-Agent.** SEC's declared form is `Company Name AdminContact@domain.com`, e.g. `-H 'User-Agent: Mavis Audit Bot mavis@example.com'`. A browser UA or bare `Mozilla/5.0` returns **403** deterministically. |
  > | **SEC EDGAR 8-K Atom** | `https://www.sec.gov/cgi-bin/browse-edgar?…` | **200 OK — contact User-Agent required (see above); CIK must be zero-padded to 10 digits** |
  and add a third line:
  > | **SEC EDGAR full-text / submissions** | `efts.sec.gov`, `data.sec.gov` | **200 OK with any User-Agent** — these two hosts do not enforce the contact form. |
  In each prompt's data-source contract, replace "needs a User-Agent header" with
  "`www.sec.gov` needs a **contact** User-Agent (`Name contact@example.com`) — a browser UA gets 403".
- **Confidence:** high (5 UAs × 3 tries × 2 endpoints, all deterministic).

### B14 — The nasdaqtrader halts "RSS" is a 302 to a 404 page, not a 200 with empty items
- **Severity:** low
- **Routines affected:** none directly (no routine depends on it — the contract already says to use
  the TradingView `halted` column instead); the defect is in `_shared/RUNTIME-CONTRACT.md:117`
- **Evidence:**
  - `/workspace/mig/cloud-prompts/_shared/RUNTIME-CONTRACT.md:117`:
    > `| NASDAQ halt RSS | https://www.nasdaqtrader.com/rss.aspx?feed=HALTS | **HTTP 200 with 0 RSS items** — serves an HTML shell. api.nasdaq.com/api/quote-list/halt-directory → 404. Trader.aspx?id=TradeHalts → 200 but JS-rendered, 0 table rows. **Use the TradingView scanner's halted column instead.** |`
  - **Observed, with and without redirect-following, two UAs:**
    ```
    no -L, UA='Mozilla/5.0'                      -> HTTP 302  size=931    <item>=0  title=' Object moved'
    no -L, UA='Mavis Audit Bot mavis@example.com' -> HTTP 302  size=898    <item>=0  title=' Object moved'
    -L,    UA='Mozilla/5.0'                      -> HTTP 200  size=42894  <item>=0  title=' Page Not Available'
    -L,    UA='Mavis Audit Bot mavis@example.com' -> HTTP 200  size=42995  <item>=0  title=' Page Not Available'
    $ curl -s -D - -o /dev/null -A 'Mozilla/5.0' 'https://www.nasdaqtrader.com/rss.aspx?feed=HALTS'
    HTTP/2 302
    location: /Trader.aspx?id=http404
    ```
  - The redirect target is literally **`http404`** — the feed is *gone*, not merely empty.
- **Why it matters:** low. No routine depends on this endpoint, and the contract already routes
  halts to the TradingView `halted` column (verified present, row 18 of the endpoint table). The
  defect matters only because the contract reports the **post-redirect** status while calling it a
  "200": a reader who probes it with a status-checking client (no `-L`) sees a **302** and may
  conclude the URL is broken and go looking for a replacement. Revision 1 of this report also
  reported "200, 898 B" for this row, conflating the un-followed 302 body with the followed 200.
- **Recommended fix:** in `_shared/RUNTIME-CONTRACT.md:117`, change the row to:
  > | NASDAQ halt RSS | `https://www.nasdaqtrader.com/rss.aspx?feed=HALTS` | **302** → `/Trader.aspx?id=http404` (the feed no longer exists). Following the redirect gives **200** with an HTML "Page Not Available" body and **0** `<item>`s — there is no RSS document to parse. `api.nasdaq.com/api/quote-list/halt-directory` → 404. `Trader.aspx?id=TradeHalts` → 200 but JS-rendered, 0 table rows. **Use the TradingView scanner's `halted` column instead.** |
- **Confidence:** high.

---

## Claims I could NOT test (explicitly unverified, not guessed)

| Claim | Where | Why unverified |
|---|---|---|
| "the connector catalog exposes **133 tools**: 118 GitHub, 13 media, 2 email" | `_shared/RUNTIME-CONTRACT.md:9-14`, §2e, all digest prompts | `mcode-tools` is not installed here (**B6**); `tool_search` returns 0 connector tools; the direct API path 404s. **No measurement of the real catalog was possible.** |
| "`connector__github__*` … authorized as `karizaco`" / "only `connector__github__*` is authorised" | contract §1 table, §2e | Same as above — authorisation is an account property, not observable without the connector. |
| "`web_search` uses a DIFFERENT egress than curl, so it survives when curl is blocked" | contract §1, §3 rule 1, 19 prompt occurrences | `web_search` is not exposed to this agent (`tool_search` → 0 hits). Consistent with the observations (Yahoo answers curl fine today) but **not directly testable**. |
| "`uvx --from financekit-mcp financekit` … 17 tools … `correlation_matrix` returned SPY/QQQ 0.924" | contract §2d | `uv`/`uvx` absent (**B7**). |
| "`tradingview-mcp` … 73 tools … needs `mcp<2`" | contract §2d | Same. |
| "Finviz … headed chromium under Xvfb with a persistent profile … still 403" | contract §2f | I reproduced the **headless** 403 (title "Just a moment…", 0 cookies). I did not run the headed/Xvfb variant — the *conclusion* matches, the specific test is unverified. |
| "the sandbox egress is `47.253.4.207` = AS45102 Alibaba (US) Technology" | contract §2f | Not re-derived; my egress was not independently identified. |
| Whether the **cron-fire** sandbox image differs from this workspace sandbox (`mcode-tools`, `uv`, python `playwright`, chromium present or not) | — | The audit ran in the workspace sandbox, not in a scheduled-task fire. **B6** and **B7** state this caveat explicitly. |

---

## Things I checked that turned out to be **accurate** (no action needed)

Re-measured in revision 2. Every status below reproduced exactly, including byte counts.

- The `RUNTIME-CONTRACT.md` §2a/§2b endpoint table reproduced **row for row, with two documented
  exceptions**: the two `www.sec.gov` rows need a contact-style User-Agent the contract never
  specifies (**B13**), and the nasdaqtrader RSS row reports the post-redirect status instead of the
  raw **302** (**B14**). All other rows — Yahoo chart/5m/screener/spark/quoteSummary/options/HTML,
  Nasdaq quote API + market movers + halt-directory, TradingView scanner, SEC full-text and
  `data.sec.gov`, CoinGecko, Frankfurter, ECB, Treasury, AlphaVantage, Stooq 404, Finviz 403
  (curl and chromium), Barchart 202/403 by curl — reproduced unchanged.
- The Yahoo crumb recipe: `fc.yahoo.com` → 404, crumb retrieved → quoteSummary **200** with
  `floatShares=116514000` / `shortRatio=2.86`; quoteSummary without a crumb → **401**.
- The TradingView scanner is **positional** (`{"s": "EXCH:SYM", "d": [...]}`), `d` ordered by the
  `columns` array; `len(d) == len(columns)` held (13/13). All nine claimed columns present.
- Barchart via a headless browser: the movers list returned `count:12, total:200` (and `count:20`
  at `--limit 20`), and the `symbols=` quote path returned real prices — the contract's
  `count:12, total:200` claim is **exactly right**.
- "Yahoo does NOT accept comma-separated symbols (404)" (`#07:100`) — **confirmed**:
  `…/chart/SPY,AAPL?interval=5m&range=1d` → **404**,
  `{"chart":{"result":null,"error":{"code":"Not Found","description":"No data found, symbol may be delisted"}}}`.
  (Minor caveat worth a footnote: Yahoo's 404 body says "symbol may be delisted", which is a
  misleading message when the real cause is the comma.)
- Pack tool counts: `shibui` = **12**, `market-recap` = **48**, `stocktwits` = **53**, `cftc-cot` =
  **47**, `tradier` = **47**, `fmp` = **68** — every count the contract states is exact.
- `barchart_fetch.py` exits **2** with a JSON error object on failure — it cannot be mistaken for
  data (its *paths* are wrong, but its error semantics are right).
- The three-state catalog design in `probe_mcp.py` and #01 is **correct**: with `mcode-tools`
  missing it reports `catalog_unreachable`, not "0 financial tools".
- `tools/schedule-drift.py`, `tools/schedule-ground-truth.json`, `tools/gen_roster.py`,
  `tools/gen_index.py` **all exist in the repo** (`/workspace/mig/tools/`) **and** are fetchable at
  the exact URLs #91 and the README use — `raw.githubusercontent.com/karizaco/maxhermes-migration/main/tools/<file>`
  → **200** for all four (19 753 / 5 278 / 10 666 / 5 611 B), and also on `master`.
  `schedule-ground-truth.json` covers **23** routines and matches the live scheduler exactly
  (`schedule_drift=0 unknown=0 missing=0`). **No missing tool — #91's dependency set is complete.**

---

## Reproduction commands (all read-only; scratch in `/workspace/audit/scratch/`)

```bash
# 1. connector catalog (fails here — see B6)
mcode-tools connector tools

# 2. bridge packs, by name
python3 mcp_bridge.py stocktwits  chart_data     a.json   # SPY OHLCV  -> works
python3 mcp_bridge.py shibui      stock_data_query b.json # SPY closes -> works
python3 mcp_bridge.py market-recap get_quotes     c.json   # 8 quotes   -> works
python3 mcp_bridge.py --list-packs                          # SEMANTIC discovery -> tradier/fmp/market-recap ONLY

# 3. per-pack tool lists (authoritative inventory)
curl -s -X POST "https://gateway.pipeworx.io/<pack>/mcp" -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
curl -s -X POST "https://mcp.shibui.finance/mcp" … same payload

# 4. endpoints (37 tested; script + raw results)
python3 /workspace/audit/scratch/ep_test.py        # -> endpoint_results.json

# 5. SEC User-Agent matrix  (B13)
for ua in "curl/8.14.1" "Mozilla/5.0" "Mavis" "Mavis Audit Bot mavis@example.com"; do
  curl -s -o /dev/null -w "%{http_code}  $ua\n" -A "$ua" \
    https://www.sec.gov/files/company_tickers.json
done

# 6. nasdaqtrader RSS, with and without -L  (B14)
curl -s -D - -o /dev/null -A "Mozilla/5.0" 'https://www.nasdaqtrader.com/rss.aspx?feed=HALTS'

# 7. the shipped Barchart helper — the two blockers, in sequence  (B8)
python3 barchart_fetch.py --symbols SPY,QQQ,AAPL          # -> no_chromium, exit 2
sed 's|chromium-\*/chrome-linux/chrome|chromium-*/*/chrome|' barchart_fetch.py > patched.py
PLAYWRIGHT_BROWSERS_PATH=/workspace/.home/.cache/ms-playwright python3 patched.py --symbols SPY,QQQ,AAPL
                                                            # -> no_playwright, exit 2
node barchart_fetch.js --symbols SPY,QQQ,AAPL              # -> real data, exit 0

# 8. deployed vs repo
#    chunk: /workspace/.mavis/tool-results/458676653531358/call_01a196fdb3f37774aef04a72/chunks/000000.txt
python3 /workspace/audit/scratch/drift.py          # -> drift_summary.json, drift_final.json

# 9. #91 detector against the live scheduler
CHUNK=/workspace/.mavis/tool-results/458676653531358/call_01a196fdb3f37774aef04a72/chunks/000000.txt
python3 schedule-drift.py --tasks "$CHUNK"         # exit 0, no drift
```
