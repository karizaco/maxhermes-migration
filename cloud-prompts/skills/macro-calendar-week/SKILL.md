---
name: Macro calendar week
description: >-
  Forward-week macro release calendar for the US market: CPI, PPI, NFP, FOMC,
  ISM, retail sales, consumer sentiment, Treasury auctions, Fed speakers.
  Pulls from FRED MCP (release schedule) once added, falls back to web_search
  on Investing.com / ForexFactory. Runs Sunday 16:00 ET, ahead of the weekly
  brief. Optional Wednesday refresh at 13:00 ET.
---

# Macro calendar — week ahead

The forward-looking macro overlay for the weekly brief. Sunday edition feeds `agentic-weekly-brief` directly; Wednesday refresh updates the remaining week.

## When
- Sunday: `0 16 * * 0` America/New_York (16:00 ET Sun — ~105 min before weekly brief at 17:47)
- Wednesday refresh: `0 13 * * 3` America/New_York (13:00 ET Wed — refreshes Wed/Thu/Fri events)
- Manual: user asks "what's on the macro calendar this week?" or "any Fed speakers?"

## Output
- Sunday: `C:\Users\admin\.minimax\projects\coding-shared\research\macro-calendar\YYYY-Wnn-week.md`
- Wednesday: same path, overwrite only if file from current ISO week; else write `YYYY-Wnn-week-mid.md`
- Compact ≤ 12-line summary in chat reply.

## Source strategy

**Preferred (when FRED MCP is enabled):**
- `mcp__fred__get_release` / `mcp__fred__get_release_dates` for the canonical release calendar (CPI, PPI, NFP, FOMC, ISM, etc.).
- `mcp__fred__search_releases` to find series IDs.
- FRED release table is the authoritative macro schedule.

**Fallback (FRED MCP not enabled):**
- `web_search` "economic calendar week of <Mon-iso-date>" → Investing.com / ForexFactory / WSJ.
- Cross-check via `web_search` "<EVENT_NAME> release date <year>" for any ambiguity.

**Fed speakers:**
- `web_search` "Fed speakers this week <Mon-iso-date>" — fedcal.io or ForexFactory speakers tab.

## Steps

1. **Compute ISO week boundaries.** Today (Sunday) → upcoming Mon..Sun.
2. **List candidate events.** Hardcoded reference list:
   - **Tier 1 (always cover):** CPI, Core CPI, PPI, Core PPI, NFP, Unemployment Rate, Hourly Earnings, FOMC Rate Decision, FOMC Minutes, GDP (advance/prelim), PCE, Core PCE
   - **Tier 2 (include if in week):** ISM Mfg PMI, ISM Services PMI, Retail Sales, Industrial Production, Consumer Sentiment (UMich prelim/final), Consumer Confidence (CB), JOLTS, Jobless Claims (weekly Thu), Durable Goods, New Home Sales, Existing Home Sales, Pending Home Sales, Treasury auctions (2y/5y/7y/10y/20y/30y — note size when surfaced)
   - **Tier 3 (mention in summary only):** Regional Fed PMIs (NY, Philly, Dallas, Richmond, KC), Beige Book (FOMC Wed before FOMC), Treasury TIC data, NFIB
3. **Resolve dates/times.** For each event in the week, query FRED or web to confirm date, time (ET), prior value, consensus if surfaced. Record `as_of_utc` for staleness.
5. **Fed speakers.** Pull from web_search. Include name, role (voter/non-voter), topic (if announced), time.
6. **Risk-day tagging.** Any weekday with a Tier 1 release or FOMC minutes → mark `HIGH_IMPACT_DAY`. Treasury auction days → mark `AUCTION_DAY`.
7. **Write markdown:**
   1. TL;DR: count of Tier 1 events, any FOMC this week, biggest risk day(s)
   2. Table by date (ET): time, event, tier, prior, consensus (if surfaced), impact tag
   3. Fed speakers section (if any)
   4. Auction calendar (sizes if surfaced)
   5. Source health (FRED ok / fallback used, missing dates flagged)
8. **Append audit line:** `macro-calendar target=macro:<iso_week> tier1=<n> fed_speakers=<n> source=<fred|web_fallback>`.

## Hard rules
- Don't fabricate. If consensus/prior is unknown, write "—".
- Always double-check FOMC dates against fed.gov if uncertain (FOMC only meets 8x/year).
- Don't speculate on the rate decision — just list the date.
- Wednesday refresh must not clobber the Sunday file for the same ISO week — use `-mid` suffix if mid-week file exists.

## Out of scope
- Earnings calendar → `earnings-reminder`, `weekly-earnings-calendar` (in agent-ops).
- Intraday economic surprises → out of scope (real-time news feeds).
- International macro (ECB, BOJ) → out of scope; can be added later if needed.