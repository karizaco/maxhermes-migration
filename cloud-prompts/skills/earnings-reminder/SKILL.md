---
name: Earnings reminder
description: >-
  Quick morning reminder of who's reporting earnings today, filtered to the
  watchlist plus any S&P 500 names. Pairs with the 07:37 ET pre-market brief.
  Runs weekdays 06:00 ET.
---

# Earnings reminder

Lightweight morning reminder — just what's on the earnings calendar today, filtered to things the user cares about.

## When

- Cron: `0 6 * * 1-5` America/New_York (weekdays, 06:00 ET — ~90 min before pre-market brief)
- Manual: user asks "who reports earnings today" or "today's earnings"

## Output

- `C:\Users\admin\.minimax\projects\coding-shared\research\earnings\YYYY-MM-DD-today.md` (≤ 10 lines)
- Compact ≤ 5-line summary in chat reply.

## Steps

1. **Watchlist earnings**: cross-reference `research/watchlist.yaml` against today's earnings calendar via Yahoo MCP `get_earnings_calendar` (or `web_search` "earnings calendar today" fallback).
2. **Big S&P 500 names**: `web_search` "today earnings S&P 500" or scan a TradingView earnings calendar endpoint if available.
3. **Filter**:
   - Show any watchlist ticker that reports today.
   - Show any S&P 500 / mega-cap name (>$50B mcap) reporting today.
   - Skip everything else (no mid/small-cap noise).
4. **Per name**: ticker, company, report time (BMO/AMC/unknown), consensus EPS, consensus revenue, market cap.
5. **Write** the short markdown file with date header and a table.
6. **Append audit line**: `earnings_reminder target=earnings:<date> watchlist_hits=<n> bigcap_hits=<n>`.

## Sample output

```markdown
# Earnings — Tue 2026-09-22

## Your watchlist
| Ticker | Company | Time | EPS est | Rev est |
|---|---|---|---|---|
| COST | Costco | TBD | — | — (reports Thu 9/24 actually) |

## Big S&P 500 today
| Ticker | Company | Time | EPS est | Rev est |
|---|---|---|---|---|
| MU | Micron | TBD | — | — |
| AZO | AutoZone | — | 54.30 | 6.71B |
```

## Hard rules

- Never auto-act on earnings data — read-only reminder.
- If data is sparse (Sunday/holiday), write a 1-line "no earnings today" file. Don't fabricate.
- Consensus estimates from web search only — note source.
- Don't pull analyst price targets (that's a different skill's job).

## Out of scope

- Detailed model / DCF revisions — read-only reminder only.
- Earnings reactions (covered by post-market brief).
- Crypto / forex earnings — equities only.
