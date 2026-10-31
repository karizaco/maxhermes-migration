---
name: Earnings reminder
description: >
  Quick morning reminder of who's reporting earnings today, filtered to the
  watchlist plus any S&P 500 names. Pairs with the 08:30 ET pre-market brief.
  Runs weekdays 06:00 ET.
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

# Earnings reminder

Lightweight morning reminder — just what's on the earnings calendar today, filtered to things the user cares about.

## When

- Cron: `0 6 * * 1-5` America/New_York (weekdays, 06:00 ET — ~2.5 h before the 08:30 ET pre-market brief)
- Manual: user asks "who reports earnings today" or "today's earnings"

## Output

- Local Mavis: `C:\Users\admin\.minimax\projects\coding-shared\research\earnings\YYYY-MM-DD-today.md`
- Cloud Mavis: `/workspace/earnings/{date}-reminders.md` (Linux path; the Windows path above does not exist there)
- The table is one row per name, so the file is longer than 10 lines on a heavy day — that is expected
  and correct. Do not truncate the roster to hit a line count.
- Compact summary in the chat reply.

## Steps

1. **Watchlist earnings**: cross-reference `research/watchlist.yaml` against today's earnings calendar.
   - The watchlist file may not exist in every runtime (it is a local-only file on the Mavis host).
     If it cannot be read, say so ONCE in the notes and omit the watchlist section. Do not ship an
     empty "Your watchlist" table every day.
2. **Big S&P 500 names**: fetch today's earnings calendar. On Cloud Mavis the working path is
   `web_search` / `web_fetch` — there is no Yahoo MCP and no shibui MCP in Cloud sessions
   (`mcode-tools connector tools` returns only `connector__matrix__*` and
   `connector__email_workbench_credentials__*`; `tool_search` returns 0 hits for finance keywords).
   Treat web search as the PRIMARY source there, not a degraded fallback. `web_fetch` on
   `earningswhispers.com/calendar/YYYYMMDD` returns a full before-open/after-close roster with no
   JS dependency and is the best single source; the Yahoo `?day=YYYY-MM-DD` calendar renders its
   first ~25 rows server-side.
3. **Filter**:
   - Show any watchlist ticker that reports today.
   - Show any S&P 500 / mega-cap name (>$50B mcap) reporting today.
   - Skip everything else (no mid/small-cap noise).
4. **Verify S&P 500 membership against a live constituent list — never from memory.**
   Fetch the MediaWiki API wikitext and parse the symbol templates:
   `https://en.wikipedia.org/w/api.php?action=parse&page=List_of_S%26P_500_companies&prop=wikitext&format=json`
   Parse `{{NyseSymbol|X}}` and `{{NasdaqSymbol|X}}`; expect ~502 symbols. Control check before
   trusting the parse: `BRK.B`, `GOOGL`, `GOOG` and `FOX` must all be present. Do NOT parse the
   rendered HTML table — it yields a handful of symbols and silently corrupts the roster.
5. **Confirm every report date against a company source before including a name.** Aggregator
   calendars carry wrong dates. Verified examples: OMC (Oct 21→22), NEM (Oct 21→22), ITW (Oct 23→27),
   NXPI (Oct 23→27), HCA (Oct 23→27), CHGCY (Oct 23→27), NWG (Oct 23→30), INTC (Oct 22→29),
   SLB (Oct 22→23). Check the company IR page, press release or filing for names near the
   inclusion boundary, and record each exclusion in the artifact.
6. **Reconcile conflicting estimates.** Pick one primary source per field and state it: Yahoo for
   market cap and EPS estimate, Investing.com / MarketBeat / Newsquawk for consensus revenue. When
   sources disagree beyond tolerance (market cap >5%, EPS >2%), note the spread. Observed examples:
   AXP mcap $203.7B-$219.6B across five providers; INFY mcap $43.7B-$53.6B (straddles the $50B
   threshold); META EPS 5.54 GAAP vs 6.35-6.67 adjusted.
7. **Per name**: ticker, company, report time (BMO/AMC/unknown), consensus EPS, consensus revenue,
   market cap, and status (`pending` vs `already reported` — European and Indian names often print
   before the US open, and the reader needs to know which).
8. **Write the markdown file** with a front-matter header (`date`, `cron`, `fire_time_et`,
   `snapshot_et`, `source`, `primary_source`, `status`, `pending_count`, `already_reported_count`)
   so downstream consumers can parse it without guessing.
9. **Append audit line** (local Mavis only — skip on Cloud):
   `earnings_reminder target=earnings:{date} watchlist_hits={n} bigcap_hits={n}`

## Sample output

```markdown
---
date: 2026-09-22
cron: 19-earnings-reminder-daily
fire_time_et: 06:00
snapshot_et: 06:00
source: Yahoo Finance earnings calendar
primary_source: Yahoo (market cap, EPS) | Investing.com (revenue)
status: ok
pending_count: 2
already_reported_count: 0
---

# Earnings — Tue 2026-09-22

## Big S&P 500 today
| Ticker | Company | Time | EPS est | Rev est | Mkt cap | Status |
|---|---|---|---|---|---|---|
| MU | Micron | AMC | 1.24 | 9.10B | 186.2B | pending |
| AZO | AutoZone | BMO | 34.12 | 18.90B | 65.4B | pending |
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
