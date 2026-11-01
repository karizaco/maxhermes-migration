---
name: NTRT gap brief
description: >-
  Produce a morning gapper brief from `karizaco/ntrt_mtrt` backend when it's
  reachable, or fall back to MCP-driven screener. Replaces the paused
  `ntrt-pre-market-brief-paused` Grok routine (paused pending URL).
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

# NTRT gap brief

Generates the weekday pre-market gapper brief. Replaces the paused `ntrt-pre-market-brief-paused` Grok routine.

## When

- Cron: `0 9 * * 1-5` America/New_York (weekdays, 09:00 ET — 30 min before the US open)
- Manual: user asks "run the ntrt brief" or "what's gapping today"

## Backend discovery

- If env var `NTRT_BASE_URL` is set (e.g. `http://127.0.0.1:8000` or VPS URL), use it.
- Otherwise default to `http://127.0.0.1:8000`.
- If env var `NTRT_AUTH_TOKEN` is set, send `Authorization: Bearer <token>`.
- Probe `GET {base}/health` first. If not 200, fall back to MCP mode.

## Output

- `C:\Users\admin\.minimax\projects\coding-shared\research\briefs\YYYY-MM-DD-ntrt-premarket.md`
- Return a short TL;DR + top gappers table to chat.

## Steps

### Mode A: backend up

1. `GET {base}/health` → confirm 200.
2. `GET {base}/api/agent/briefing` (or MCP tool `get_briefing`) — drop any huge `llm_briefing` blob; use structured sections only.
3. `GET {base}/api/gappers?min_pct=3&direction=both&limit=20` (or MCP `list_gappers` with `min_pct=3`, `limit=20`).
4. Optional: pull premarket catalyst endpoints if present, or MCP `list_premarket_catalysts` then `watchlist_premarket`.
5. Cap deep dives at top 5 by importance: `GET /api/dossier/{ticker}` or MCP `explain_gap` / `explain_premarket`.

### Mode B: backend down → TradingView screener fallback

**Prefer the PUBLIC screener endpoint over the MCP tool.** The MCP tool
`mcp__tradingview_advanced__screen_stocks` is frequently NOT registered in the Cloud runtime
(verified 2026-11-01: catalog 133 tools, 0 finance). The public HTTP endpoint returns the same
columns — **including `premarket_volume`, which the MCP tool and every other free source omit** —
so the endpoint is the better path even where the MCP tool exists.

`POST https://scanner.tradingview.com/america/scan` with `Content-Type: application/json`,
`User-Agent: Mozilla/5.0`, `Origin: https://www.tradingview.com`:

```json
{"filter":[{"left":"type","operation":"equal","right":"stock"},
           {"left":"exchange","operation":"not_in_range","right":["OTC"]},
           {"left":"market_cap_basic","operation":"egreater","right":200000000},
           {"left":"premarket_change","operation":"in_range","right":[3,1000]}],
 "options":{"lang":"en"},"markets":["america"],
 "symbols":{"query":{"types":[]},"tickers":[]},
 "columns":["name","close","premarket_close","premarket_change","premarket_volume",
            "market_cap_basic","average_volume_30d_calc","relative_volume_10d_calc",
            "sector","exchange"],
 "sort":{"sortBy":"premarket_change","sortOrder":"desc"},"range":[0,600]}
```

Run it **twice** — once with `premarket_change` in `[3,1000]` (desc) and once in `[-1000,-3]`
(asc) — so both sides are carried. A single descending sort publishes only gainers.

Critical filter notes:

- **`type: "stock"` INCLUDES REITs.** Do not re-filter the result to common stock. A universe
  seeded on common stock only silently drops REITs — on 2026-10-30 that hid **ARI (-63.9%)**, the
  largest mover of the day.
- `exchange != OTC` and `market_cap_basic >= 200000000` are the skill's stated floors. Keep them.
- `market_cap_basic` is USD-normalised for US listings.

Columns and what they are worth:

| column | use |
|---|---|
| `premarket_change` | the gap % vs the prior regular close — the brief's headline number |
| `premarket_close` | the pre-market print |
| `premarket_volume` | **pre-market shares — the importance measure.** Divide by `average_volume_30d_calc` for % of ADV. A ±20% gap on 100 shares is a quote, not a market. |
| `average_volume_30d_calc` | 30-session average daily volume (a daily proxy, not intraday) |
| `relative_volume_10d_calc` | TradingView's 10-day relative volume — also a daily proxy |

1. Screen with the filters above, then **rank by absolute `premarket_change`** and publish both
   sides. The skill sorts by `premarket_change` descending; a descending-only sort would hide the
   day's largest decliners.
2. For each top 5 by abs(premarket_gap), pull a one-line catalyst via `web_search` for
   `"<TICKER>" news catalyst <today>` (past 12 hours).
3. Surface what you have; clearly mark this as the screener fallback in the brief header.

### Mode B2: reconstructing a PAST session (a missed or delayed run)

If this brief is being rebuilt for a date that has already traded, TradingView's `premarket_*`
columns hold only the **most recent** session — so they are the right source for the last session
before today, and for anything older they are gone. For an older date:

- `premarketprice.com/premarket-gainers/<YYYY-MM-DD>` and `.../premarket-losers/<YYYY-MM-DD>`
  keep **date-stamped** archives with price, % change and RVOL. Use them to validate.
- Chartmill publishes dated articles (`Premarket Gainers and Losers on <date>`,
  `S&P 500 Premarket Movers: <date>`) with per-name pre-market prices and %.
- Yahoo `v8/finance/chart` / `v7/finance/spark` with `includePrePost=true` reconstruct the
  pre-market TAPE from 5-minute bars, but **`volume` is 0 on every pre-market bar** and the tape
  goes **stale** for thinly-traded names (a flat print left from hours earlier). Never publish a
  Yahoo pre-market price without checking it against the printed table, and never publish a
  Yahoo pre-market **range** for a name where the two sources disagree by more than ~0.6%.

### Always

6. Compose the brief:
   - TL;DR (≤ 3 bullets)
   - Top gappers table (ticker, gap%, importance/relative-vol, sector, one-line why)
   - Catalysts
   - Anything needing human eyes
7. Save under `research/briefs/YYYY-MM-DD-ntrt-premarket.md` (don't overwrite prior files).
8. Append audit line: `brief_rendered target=ntrt-premarket:<date> mode=<A|B>`.

## Failure modes

- Backend down / connection refused → automatically try Mode B (MCP fallback). If both fail, write a short file noting both unavailable, do not invent data.
- Empty results on weekend/holiday → one-line quiet note (still write the file).
- Rate limits → stop extra dossier calls; deliver what you have.
- Auth 401/403 → report, don't retry in a loop.

## Hard rules

- Never place trades.
- Do not scrape TipRanks/Yahoo in the browser when the API is up.
- Do not fan out to other trading agents unless the user explicitly asks.
- Hard cap deep dives at 5 per run.

## Out of scope

- Long-form analyst notes per ticker — only short, structured fields.
- Cross-broker or cross-asset class research — only US equities.
