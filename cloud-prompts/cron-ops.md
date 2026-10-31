# Fleet cron operations — task IDs, scheduler API, and data capabilities

Reference for anyone touching the cloud cron fleet. Live source of truth for task IDs is
`cloud-prompts/cron-prompts/roster.json` (regenerated from the live scheduler by
`tools/gen_roster.py`). **Do not hard-code a task ID in a prompt or a doc** — see §1.

---

## 1. Task IDs

### Where they live

| What | Where | Freshness |
|---|---|---|
| All 21 live task IDs | `cloud-prompts/cron-prompts/roster.json` | regenerated from `cron_read view=list` |
| Human-readable map | `cloud-prompts/cron-prompts/ROSTER.md` | same generator |
| Live, on demand | `cron_read {view: list, agent_name: "<Mavis\|Analyst\|Scout>", limit: 100}` | live |

**Always resolve the ID at use time.** The fleet recreates tasks — `#05`, `#08`, `#17`, `#22`,
`#23`, `#25` were all recreated on 2026-10-29/30 with new IDs, and `#90` on 2026-10-30. An ID
hard-coded in a prompt or a runbook is stale the next time that happens. `roster.json` was
regenerated 2026-10-31 and carries all 21.

### The scheduler API coercion bug

The `cron_*` tools validate their arguments against a JSON schema **after** a coercion step that
turns numeric-looking strings into numbers. Consequences, all observed:

| Call | Result |
|---|---|
| `cron_read {view: runs, task_id: "<LIVE id>"}` | **works** |
| `cron_read {view: runs, task_id: "<DEAD id>"}` | **`task_id: Expected string`** — the dispatcher coerces the numeric string, the lookup fails, and the error surfaces as a type complaint, not "not found" |
| `cron_read {view: list, cursor: "20"}` | **`cursor: Expected string`** — same cause |
| `cron_create {..., enabled: true}` | **`enabled: Expected boolean`** |
| `cron_update {..., enabled: true}` | **`enabled: Expected boolean`** |

**Workarounds**
- **Omit `enabled` on `cron_update`.** It is preserved; passing it fails.
- **Never pass `cursor` as a numeric string.** Paginate by filtering `agent_name` instead — it
  returns every task for that agent with IDs, in one call.
- A type error on `task_id` usually means **the task is dead**, not that the argument is malformed.
  Re-read the roster before assuming a bug.

### `cron_update` rules

1. **Always resend `schedule` AND `timezone` together.** A bare update resets the timezone to the
   platform default (`Etc/GMT-7`), which silently shifts the fire time.
2. `cron_name` is immutable — a rename is a delete + recreate.
3. `agent_name` is immutable — re-owning means create-with-new-agent then delete the old.
4. `session.mode: "sessionId"` binds an existing session; `session.mode: "new"` creates a
   per-fire conversation. `"me"` is not a valid `session_id`.
5. `model` parity is not achievable via these tools — `cron_create` takes only `provider/model_id`
   and drops `variant`/`thinking_effort`; `cron_update` has no `model` field at all.

### Deploying a prompt change

The **repo is the source of truth**; the deployed prompt is a byte-for-byte mirror of
`cloud-prompts/cron-prompts/<name>.md`.

1. Edit the repo file, push it (via the GitHub connector — see §2).
2. `cron_update` the task with **exactly** the repo file's content.
3. Verify with `cron_read {view: detail, task_id}`.

A **concurrent session is also writing to these crons** (README "Known hazards"). Treat any fleet
change that is not in this repo's git history as unverified. The `git log` of
`maxhermes-migration` is the audit trail — make your change there first, then the scheduler.

---

## 2. Data capabilities available now (2026-10-31)

### Built-in connector catalog: 133 tools

`connector__github__*` — **118 tools**, authorized as `karizaco`. The other 15 are
`connector__matrix__*` (13, media) and `connector__email_workbench_credentials__*` (2). Still
**zero financial MCPs** registered.

**What the GitHub connector replaces:** the `git`+PAT push block in every cron prompt. Use
`connector__github__create_or_update_file` (single file) or `push_files` (batch) with
`mcode-tools connector call <tool> --args-file <file>`. It removes the PAT from the sandbox, the
CA-bundle wrangling, and — structurally — the `git add -A` deletion hazard that cost cron #12
283 files on 2026-10-25.

**Routine → GitHub-connector use**

| Use | Tools |
|---|---|
| Publish an artifact | `create_or_update_file`, `push_files` |
| Prompt/config change in `maxhermes-migration` | `create_or_update_file`, `create_branch`, `create_pull_request` |
| Auditor on the `audit/status` branch | `create_branch`, `push_files` |
| Fleet-wide archaeology | `list_commits`, `list_branches`, `get_file_contents`, `search_code`, `search_commits` |

Caveat: the connector has **no equivalent of the push block's 3-attempt race-retry**. Two crons
pushing the same branch in the same minute can still race. Keep the git block where a routine
shares a fire minute with a partner, and use the connector where it doesn't.

### MCP servers over plain HTTPS — no registration needed

The `mcp__*` tool names are provenance-only (they were local-Windows MCPs). The **servers** are
reachable via `cloud-prompts/_shared/mcp_bridge.py`. Packs confirmed live:

| Pack | Tools | Best for |
|---|---|---|
| **`market-recap`** | 48 | `get_quotes` (batch quotes + `as_of` + `market_state`), `top_movers`, `market_snapshot`, `price_history`. **Primary quote source.** |
| `stocktwits` | 53 | `chart_data`, sentiment, trending |
| `shibui` | 12 | history to 1962, fundamentals, screeners, EDGAR |
| `tradier` | 1+ | `tradier_quote` |
| `cftc-cot` | — | CFTC positioning |
| `fmp` | — | `stock_screener` — needs the user's own FMP key as `_apiKey` |

`python3 mcp_bridge.py --list-packs` enumerates them; any pack name resolves to
`gateway.pipeworx.io/{pack}/mcp` with no code change.

### Barchart and Finviz via a headless browser

`playwright` and the chromium build are **already installed** in the cloud sandbox:
`/usr/local/lib/python3.11/dist-packages/playwright/` and
`/root/.cache/ms-playwright/chromium-1243/chrome-linux/chrome`.

| Site | Plain curl | Headless chromium |
|---|---|---|
| **Barchart** | HTTP 202 bot challenge, no cookies | **WORKS** — page renders (48 table rows) and the in-page `core-api` call returns real data |
| **Finviz** | HTTP 403 Cloudflare | **still 403** — "Just a moment…", even with webdriver masked |

**Barchart recipe** (this is the Finviz replacement for movers/screens):

```python
# 1. load a barchart page in chromium (this clears the AWS WAF challenge and sets the cookies)
# 2. call core-api FROM the page context so the browser attaches the session cookies
#    and the X-XSRF-TOKEN header
```

| Endpoint | Verified |
|---|---|
| `/proxies/core-api/v1/quotes/get?symbols=SPY,QQQ,AAPL&fields=symbol,lastPrice,volume` | ✅ `count:5, total:5` with real prices |
| `/proxies/core-api/v1/quotes/get?lists=stocks.us.percent.advances.overall&orderDir=desc&fields=symbol,symbolName,lastPrice,priceChange,percentChange,volume&limit=12` | ✅ `count:12, total:200` — the top-advancers screener |

Note the field-name difference between the two: quotes use `lastChange`/`lastChangePercent`, the
movers list uses `priceChange`/`percentChange`. Capture the list name from the page's own network
calls (`page.on("response")`) — guessing `stocks.us.advances` returns `count:0` with HTTP 200, so
a wrong list name looks like an empty market rather than an error.

### `uv` / `uvx` — two more MCPs are installable

`uv` and `uvx` 0.12.17 are **already installed** at `/usr/local/bin/`. That unlocks the two local
MCPs previously marked `needs_linux_uv_binary` / `needs_linux_uvx_binary`:

| PyPI package | What | Serves |
|---|---|---|
| `financekit-mcp` 1.2.0 (command: **`financekit`**) | 17 tools: quotes, technical analysis (RSI/MACD/Bollinger/Golden-Death Cross), crypto via CoinGecko, VaR/Sharpe/Sortino/Beta, **correlation matrix**, options chains, **earnings calendar**, **sector rotation**, portfolio analysis. No API keys. | **#12** cross-asset-correlation, **#15** earnings-reaction-scanner, #09/#10 sector rotation, #16 options flow, #17 |
| `tradingview-mcp` 0.9.1 (needs `mcp<2` pinned) | live market intelligence, trade analytics, screeners | #07 focus-rvol, #08 pre-market gapper, #09 sweep, #10 breadth, #17 |

**Blocker:** the sandbox sets `UV_INDEX_URL`, `UV_DEFAULT_INDEX`, `PIP_INDEX_URL` and
`PIP_TRUSTED_HOST` to `mirrors.cloud.aliyuncs.com`, which is **unreachable** (connection reset).
Override both uv variables and drop the pip ones:

```bash
env -u PIP_INDEX_URL -u UV_INDEX_URL -u PIP_TRUSTED_HOST \
    UV_DEFAULT_INDEX="https://pypi.org/simple" UV_INDEX_URL="https://pypi.org/simple" \
    uvx --quiet --from financekit-mcp financekit
```

The **console script is not the package name**: `financekit-mcp` installs `financekit`.
`tradingview-mcp` additionally needs `mcp<2` (it bundles mcp 2.x, where `FastMCP` was renamed
`MCPServer`) — use `uvx --from "tradingview-mcp" --with "mcp<2" tradingview-mcp`.

**Verified tool counts (2026-10-31):** `financekit` = **17** tools (`correlation_matrix`,
`earnings_calendar`, `sector_rotation`, `options_chain`, `technical_analysis`, `market_overview`,
`risk_metrics`, …); `tradingview-mcp` = **73** tools (`top_gainers`, `top_losers`,
`egx_stock_screener`, `egx_sector_scan`, `egx_index_analysis`, `bollinger_scan`,
`volume_breakout_scanner`, `market_sentiment`, …).

**Argument shapes are strict:** `financekit.correlation_matrix` takes `symbols` as a
comma-joined **string** (`"SPY,QQY,IWM,XLE"`), not a list.

### Routine → capability map

| Routine | Best available source now |
|---|---|
| #02 asia-pre-market-reactions | `market-recap.market_snapshot`, `stocktwits` |
| #04 reversal-bullish | `shibui` screeners, `financekit` technicals |
| #05 eod-international | `shibui` (history to 1962), `market-recap.price_history` |
| #07 focus-rvol | `market-recap.top_movers`, TradingView scanner `relative_volume_10d_calc` |
| #08 pre-market-gapper | TradingView scanner `premarket_*`, Barchart-via-chromium |
| #09 daily-sweep | `financekit.stock_screener` (needs key) or `market-recap.top_movers` |
| #10 breadth | `financekit` sector rotation, TradingView scanner |
| #12 cross-asset-correlation | **`financekit` correlation matrix** — purpose-built for this |
| #13/#14 macro-calendar | FRED-equivalent HTTP + `market-recap.market_snapshot` |
| #15 earnings-reaction | **`financekit` earnings calendar** |
| #16 options-flow | `financekit` options chains, Yahoo options (crumb) |
| **#17 us-stocks-in-play** | `market-recap.get_quotes` + `top_movers` + `market_snapshot`, TradingView scanner (movers/RVol/`halted`/premarket), Barchart-via-chromium, SEC EDGAR full-text, Yahoo quoteSummary (float/short ratio) |
| #90 delivery-auditor | GitHub connector (`audit/status` branch) |

---

## 3. Source-of-truth rules

- **Prompts and skills:** `karizaco/maxhermes-migration`, `cloud-prompts/`. Every cron prompt
  embeds a condensed `RUNTIME-CONTRACT.md`.
- **Artifacts:** `karizaco/minimax-cloud-outputs`, branch `main`. `master` is a fast-forward mirror
  maintained by the auditor.
- **`refs/` in the outputs repo** is gitignored in the cloud sandbox — `git add -f refs/<file>.md`
  is required, and a plain `git add -A` silently skips it.
