# IMPROVEMENTS — cron #14 `macro-calendar-week-ahead`: two silent-offset traps in the macro-calendar sources

**Date:** 2026-11-15
**Scope:** the data path of cron #14 (Sunday 15:00 ET fire), written up because both findings are **silent** — neither source errors, neither returns an empty body, and a run that publishes either trap ships a calendar that is wrong by five hours or by one week without any visible symptom.

**Evidence base:** the 2026-11-15 fire of cron #14 in the Cloud runtime, producing `macro-calendar/2026-11-15-week-ahead.md` (ISO week 2026-W47). Every measurement below was taken on that run.

---

## 1. The economic-calendar aggregators print GMT times under an "ET" label

**The problem.** `themarketmonitors.com/economic-calendar/` and `metacap.si/calendar/economic/` both label every timestamp **"ET"** while the timestamps are actually **UTC/GMT**. The offset is a full five hours in November (EST = UTC-5), and it is not detectable from the page itself. A run that copies the printed clock publishes every release five hours late.

**The evidence (three independent anchors, all confirming −5h):**

| Release | Aggregator's printed "ET" | True ET | Anchor |
|---|---|---|---|
| Empire State Manufacturing | `13:30 ET` | **08:30** | NY Fed release time, and every other calendar |
| Retail Sales (Oct) | `13:30 ET` | **08:30** | Census release time |
| Initial Jobless Claims | `13:30 ET` | **08:30** | DOL release time |
| FOMC Minutes | `19:00 ET` | **14:00** | Fed's own calendar |
| Fed Chair Warsh speaks | `17:00 ET` | **12:00** | federalreserve.gov/newsevents |
| Barr speaks (Milan) | `10:00 ET` | **05:00** | federalreserve.gov/newsevents |

**The fix.**

1. **Never copy the aggregator's clock.** Convert by subtracting 5h (ET = GMT − 5 during EST; recompute the offset from the DST rule, do not hard-code it).
2. **Validate the conversion against anchors that cannot move.** Three checks are enough to catch a wrong-offset run: (a) the 08:30 ET data cluster (retail sales, jobless claims, Empire State) must land on 08:30; (b) the 14:00 ET FOMC minutes must land on 14:00; (c) Fed speech times must agree with `federalreserve.gov/newsevents/2026-MM-November.htm`, which prints **ET** and is the source of record for the Fed calendar.
3. **Use the aggregators for `forecast` and `previous` only.** Their forecast/prior pairs are useful and their clocks are not. MetaCap's tables carry the same +5h offset and are a good *value* cross-check, never a clock.

**A subtler trap inside the same two sites: the two aggregators disagree on the consensus for four of the week's prints** (Empire State 17.6 vs 19.4; retail control group +0.4% vs +0.1%; housing starts 1.23M vs 1.25M; initial claims 199K vs 200K). These are different consensus surveys, not errors — but they must not be blended. Publish **one source per field**, name it in Source health, and flag the divergence in the artifact rather than averaging or silently picking the convenient one.

## 2. Treasury's auction schedule carries announcement, auction and settlement in three different columns — reading the wrong one moves a $70B auction a week

**The problem.** `TentativeAuctionScheduleQ42026.pdf` / `.xml` print several dates per security. Positioned naively, they read as "auction, settlement, maturity, …" and the schedule looks like it puts the **2-year note, 5-year note and 7-year note inside 16–20 Nov**. It does not.

**The column semantics (measured on the Q4 2026 schedule):**

| Security | Row as printed | Announcement | **AUCTION** | Settlement |
|---|---|---|---|---|
| 3-Year Note | `Wed Nov 04 \| Mon Nov 09 \| Mon Nov 16` | Nov 4 | **Nov 9** | Nov 16 |
| 10-Year Note | `Wed Nov 04 \| Tue Nov 10 \| Mon Nov 16` | Nov 4 | **Nov 10** | Nov 16 |
| 30-Year Bond | `Wed Nov 04 \| Thu Nov 12 \| Mon Nov 16` | Nov 4 | **Nov 12** | Nov 16 |
| 20-Year Bond (R) | `Thu Nov 12 \| Wed Nov 18 \| Mon Nov 30 \| Thu Nov 15 2046` | Nov 12 | **Nov 18** | Nov 30 |
| 10-Year TIPS (R) | `Thu Nov 12 \| Thu Nov 19 \| Mon Nov 30 \| Wed Jul 15 2036` | Nov 12 | **Nov 19** | Nov 30 |
| 2-Year Note (new) | `Thu Nov 19 \| Mon Nov 23 \| Mon Nov 30 \| Sun Nov 30 2028` | Nov 19 | **Nov 23** | Nov 30 |
| 5-Year Note | `Thu Nov 19 \| Tue Nov 24 \| Mon Nov 30 \| Sun Nov 30 2031` | Nov 19 | **Nov 24** | Nov 30 |
| 7-Year Note | `Thu Nov 19 \| Wed Nov 25 \| Mon Nov 30 \| Wed Nov 30 2033` | Nov 19 | **Nov 25** | Nov 30 |

**The rule:** the **first** date in each security's row is the **announcement** (the Monday/Tuesday/Thursday when Treasury announces the auction), the **second** is the **auction date**, and the **third** is the **settlement date**. The trailing dates are maturity and, for reopened issues, the original issue date. A row can therefore print a date inside the target week that is only the *announcement* — the 7-year note's `Nov 19` is an announcement for a **Nov 25** auction.

**Why this matters for this routine.** The 2-year ($69B) and 5-year ($70B) notes are the largest coupon auctions of the month after the refunding, and reading the announcement column puts them inside the week. Published wrong, a calendar sends the reader to the wrong Tuesday for two of the biggest supply events of the month.

**The fix.**

1. **Take the auction schedule from Treasury's own schedule**, not from a calendar aggregator. The aggregators dropped the 6-week, 17-week and 2-year FRN entries for this window entirely.
2. **Cross-check against the refunding statement's own prose**, which states the auction dates in sentences: *"The 3-year note will be auctioned at 1:00 p.m. ET on Monday, November 9, 2026 … All these auctions … settle on Monday, November 16, 2026."* That prose is the tie-breaker whenever a row's column layout is ambiguous.
3. **A reopening's size is the new-issue amount, announced 1:00 p.m. ET the business day before.** The refunding statement publishes the *quarter's* coupon size, not the reopening's. Publish the refunding size labelled as such, or `—`. Do not present it as the auction's size.
4. **Bills have no published size before auction** — only a prior yield. `—` is the honest value.

## 3. Smaller notes from the same run

- **`web_fetch` timed out (15 s) on two calendar pages that curl retrieved in under a second.** The two are not equivalent transports: `web_fetch` uses a different egress. When a fetch fails, retry the **same URL** with the other transport before calling the source unavailable (the fleet rule about TLS/cert failures applies to timeouts too).
- **`probe_mcp.py` reported `catalog_ok total=135 finance_tools=0`** — the catalog is healthy, the FRED MCP simply does not exist in this runtime. The MCP-over-HTTP bridge answered `bridge_ok packs=tradier,fmp,market-recap` but carries **no macro release schedule**, so for this routine the documented `web_fallback` path is the only path. Recording the probe result in Source health is enough; the absent FRED MCP is not a degraded source and must not be counted as an error.
- **`thriveinmarkets.com/calendar/2026-11-16/` is the only per-day URL that resolves**; `…/2026-11-17/` through `…/2026-11-20/` all return a 404 page with a 200 status and an identical body length (73,588 bytes) — a byte-count check would treat them as successful fetches. The week page carries only Monday's detail; the other days' detail is not retrievable from that site.
- **The Michigan final has no separate consensus.** Published "consensus" for Friday's final sentiment was the *preliminary* reading (51.0) carried forward. Say so, or print `—`.

## What was NOT changed

The skill spec (`cloud-prompts/skills/macro-calendar-week/SKILL.md`) was **not** edited and no `cron_update` was issued. Nothing here changes how cron #14 behaves on its next fire; these are source facts the run had to discover for itself. The skill's fallback path (web_search on Investing.com / ForexFactory) is also stale in practice: Investing.com was unreachable from this egress, and the working set was Scotiabank Economics + Treasury + federalreserve.gov + themarketmonitors.com. Pinning that source set in the skill is a decision for the team, not a side effect of this run.
