---
name: Agentic post-market brief
description: >-
  Generate the daily post-market brief: day's tape, watchlist EOD review,
  after-hours earnings reactions, tomorrow's setup. Uses MCPs (no per-call
  cost), writes to the local research vault. Runs on cron at 22:30 ET
  weekdays.
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

# Agentic post-market brief

Generates the daily post-market markdown brief using Mavis's financial MCPs. Companion to `agentic-pre-market-brief`.

## When

- Cron: `30 22 * * 1-5` America/New_York (weekdays, 22:30 ET — the evening post-market digest)
- Manual: user asks "give me today's post-market brief" or "run the post-market brief"

## Output

- `C:\Users\admin\.minimax\projects\coding-shared\research\briefs\YYYY-MM-DD-post_market.md`
- Compact ≤60-line summary in the reply / cron report.

## Steps

1. **Read the watchlist.** Same as pre-market: `C:\Users\admin\.minimax\projects\coding-shared\research\watchlist.yaml`.
2. **Day's tape.** Pull index closes via TradingView MCP `lookup_symbols` (`^GSPC, ^IXIC, ^DJI, ^RUT, ^VIX`) and ETF proxies via Yahoo MCP (`SPY, QQQ, IWM, DIA, GLD, TLT`).
3. **Sector rotation.** Use TradingView MCP `screen_stocks` with `sector` filters and `change` percent desc — rank top 3 / bottom 3 sectors. Cross-check via `compare_stocks` for 1-2 representative tickers per sector.
4. **Watchlist EOD review.** Pull post-close data for each watchlist ticker via Yahoo MCP `get_stock_quote`: price, day change, day range, after-hours activity, volume vs avg.
5. **After-hours earnings reactions.** Use `web_search` `<TICKER> after hours <today>` for any watchlist names that reported AMC. Also check broad mover list via `web_search` "after hours earnings <date>".
6. **Tomorrow's setup.**
   - Futures via Yahoo MCP `yahoo_price` (ES=F, NQ=F, YM=F, RTY=F) — note Asia session opens ~18:00 ET Sun–Thu.
   - Tomorrow's earnings: `web_search` `earnings calendar tomorrow <day> <ticker>` against watchlist.
   - Tomorrow's economic releases: `web_search` `economic calendar <tomorrow-iso-date>` (CPI, PPI, jobless claims, Fed speakers, Treasury auctions).
   - Watchlist-relevant news: `web_search` `<TICKER> news <date>` for the top 3 by day's % move.
7. **After-hours movers.** Yahoo MCP `get_stock_quote` for any tickers that gapped >5% in extended hours — surface a Top 5 table.
8. **Breadth & volatility.** VIX, VXN (via lookup_symbols), put/call ratio if obtainable via `web_search` CBOE summary.
9. **Write brief** following the agentic template (TL;DR → Day's tape → Sector rotation → Watchlist EOD → After-hours movers → After-hours earnings reactions → Tomorrow's setup → Open research queue).
10. **Append audit line** to `research/logs/audit.log` with timestamp, action=`brief_rendered`, target=`post_market:<date>`.

## Hard rules

- Never place trades. Read-only by design.
- Use only MCPs and `web_search`/`web_fetch`. No browser automation.
- If after-hours data is sparse, note it under `Source health` — do not invent.
- Cap after-hours movers at 10; cap sector list at top-3 / bottom-3 only.
- Always cite sources (URL or file path) for factual claims.

## Out of scope

- Portfolio P&L or position sizing — read-only summary only.
- Pre-market setups — those live in the pre-market skill.
- Weekly recaps — those live in the weekly brief skill.
