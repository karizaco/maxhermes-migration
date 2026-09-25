---
name: Agentic weekly brief
description: >-
  Generate the weekly recap and forward-looking preview: week's tape across
  indices and sectors, watchlist weekly performance, next week's macro + earnings
  + Fed speakers, themes for the week ahead. Uses MCPs (no per-call cost),
  writes to the local research vault. Runs on cron Sunday 17:47 ET.
---

# Agentic weekly brief

Generates a weekly recap + forward-looking preview. Companion to the pre/post-market briefs. The "Sunday evening sit-down" brief.

## When

- Cron: `47 17 * * 0` America/New_York (Sunday 17:47 ET)
- Manual: user asks "give me the weekly brief" or "what's the week ahead"

## Output

- `C:\Users\admin\.minimax\projects\coding-shared\research\briefs\YYYY-Wnn-weekly.md` (ISO week format, e.g. `2026-W38-weekly.md`)
- Companion 1-page TL;DR at `research/briefs/YYYY-Wnn-weekly-tldr.md` (≤ 80 lines, phone-readable)
- Compact ≤60-line summary in the reply / cron report.

## Steps

### Recap section

1. **Index week-over-week.** TradingView `lookup_symbols` for `^GSPC, ^IXIC, ^DJI, ^RUT, ^VIX`. Compute % change from prior Friday close to this Friday close via Yahoo MCP `get_historical_prices` for each (range=`5d`, interval=`1d`).
2. **Sector weekly performance.** TradingView `screen_stocks` with `sector` filter, `change` desc — rank top 3 / bottom 3 sectors.
3. **Watchlist weekly performance.** For each ticker in `research/watchlist.yaml`, pull `get_historical_prices` (5d, 1d) and compute week % change. Highlight top-3 winners and bottom-3 losers.
4. **Themes of the week.** `web_search` `<ISOWEEK> week recap <year>` from 2-3 sources (Reuters / WSJ / Bloomberg headlines). Synthesize 3-5 dominant themes.
5. **Macro events recap.** This week's FOMC / CPI / PPI / NFP / Treasury auctions (whatever actually happened). `web_search` confirmation.

### Forward preview section

6. **Next week's macro calendar.** `web_search` `economic calendar next week <day-after>` — list major releases with date/time.
7. **Next week's earnings calendar.** TradingView MCP earnings filter or `web_search` `<next-week-iso> earnings calendar` — list all watchlist tickers + 3-5 biggest market-cap names not on watchlist.
8. **Fed speakers.** `web_search` `Fed speakers next week <day-after>` — list speakers + topics.
9. **Forward themes.** `web_search` `next week outlook <day-after>` — synthesize 2-3 themes traders are positioning for. Cross-check against prior week's themes.
10. **Watchlist action items.** Highlight any earnings dates, ex-div dates, or known events for the watchlist tickers in the next 5 trading days.

### Composition

11. **Write full weekly brief** following template (TL;DR → Recap → Indexes → Sectors → Watchlist → Themes → Macro events → Forward preview → Earnings → Fed speakers → Themes → Watchlist action items → Open research queue → Source health).
12. **Write 1-page TL;DR companion** at `*-tldr.md` (Top 5 bullets only, ≤ 80 lines).
13. **Append audit line** to `research/logs/audit.log` with timestamp, action=`brief_rendered`, target=`weekly:<isoweek>`.

## Hard rules

- Never place trades. Read-only by design.
- Use only MCPs and `web_search`/`web_fetch`. No browser automation.
- Recap data must be cited (MCP source + date).
- If week is short (holiday), note "shortened week, X trading sessions" at the top.
- Always cite sources (URL or file path) for factual claims.

## Out of scope

- Tax-loss harvesting / position-sizing advice — read-only recap.
- Intraday analysis — that's the daily briefs' job.
- Cross-asset class (FX/commodities/crypto) deep dives — only index-level context.
