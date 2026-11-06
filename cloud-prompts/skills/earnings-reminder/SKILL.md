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

1. **Watchlist earnings**: cross-reference the **published watchlist** against today's earnings calendar.
   - The watchlist is a PUBLISHED FILE, fetched at run time (the local `research/watchlist.yaml` on
     the Mavis host is unreachable from the Cloud runtime — that is why this section was omitted
     from every artifact until 2026-11-06):

     ```
     https://api.github.com/repos/karizaco/minimax-cloud-outputs/contents/refs/watchlist.yaml?ref=main
     https://raw.githubusercontent.com/karizaco/minimax-cloud-outputs/main/refs/watchlist.yaml
     ```

     Use the contents API first (it is authoritative and not CDN-cached), then the raw URL.
   - **If it fetches (HTTP 200):** publish the "Your watchlist" section from it. `earnings_flag: true`
     marks a name to highlight.
   - **If it cannot be read (HTTP 404):** say so ONCE in the notes and omit the watchlist section.
     Do not ship an empty "Your watchlist" table every day, and never invent tickers.
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
   Fetch the MediaWiki API wikitext:
   `https://en.wikipedia.org/w/api.php?action=parse&page=List_of_S%26P_500_companies&prop=wikitext&format=json`
   Parse ALL THREE symbol templates — `{{NyseSymbol|X}}`, `{{NasdaqSymbol|X}}` AND `{{BZX link|X}}`.
   The third one matters: Cboe Global Markets is written `{{BZX link|CBOE}}`, so a
   NyseSymbol/NasdaqSymbol-only regex yields 502 symbols and silently DROPS CBOE — a real
   constituent that then gets wrongly excluded. Expect **503** symbols.
   Control check before trusting the parse: `BRK.B`, `GOOGL`, `GOOG`, `FOX` AND `CBOE` must all
   be present. Do NOT parse the rendered HTML table — it yields a handful of symbols and
   silently corrupts the roster. Do NOT use the `datasets/s-and-p-500-companies` CSV as the
   authority: it is stale (still lists MMM, which left the index in 2024).
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
   **The ticker you print is the issuer's PRIMARY listing.** For an ADR or an OTC line the headline
   ticker is the home-market line with its exchange suffix, and the US line goes in parentheses:
   `8001.T (ITOCY)`, `8031.T (MITSY)`, `NOVO-B.CO (NVO)`. An OTC ticker is never the headline — the
   reader cannot find the company by it, and it reads as a penny stock.
   Resolve the primary listing per name (one or two cheap calls):
   - **OTC line** → `https://stockanalysis.com/quote/otc/<TICKER>/` and read the **"Main Listing"**
     link. Verified 2026-11-04: ITOCY → `/quote/tyo/8001/`, MITSY → `/quote/tyo/8031/`,
     SMMNY → `/quote/etr/SHL/`.
   - **US-listed ADR of a non-US issuer** → `https://stockanalysis.com/api/search?q=<company name>`
     lists every line; the home-market line is the one on the issuer's domicile exchange
     (cph/NOVO.B for Novo, etr/SHL for Siemens Healthineers, tsx/CVE for Cenovus).
   - **Confirm the primary line with Yahoo**, which returns the venue and the LOCAL currency:
     `https://query1.finance.yahoo.com/v7/finance/quote?symbols=8001.T,8031.T,NOVO-B.CO,SHL.DE`
     → `exchange`/`fullExchangeName` (JPX/Tokyo, GER/XETRA, CPH/Copenhagen) + `currency`
     (JPY, EUR, DKK) + `marketCap` in that currency.
   - **If the US line IS the primary listing** (ARM on Nasdaq; CVE and MFC on NYSE, whose TSX lines
     are the secondary), keep the US ticker and name the other line:
     `ARM (Nasdaq, primary)`, `CVE (NYSE, primary; TSX: CVE.TO)`.
   Exchange suffixes: Tokyo `.T` · XETRA `.DE` · Frankfurt `.F` · SIX `.SW` · LSE `.L` · Paris `.PA`
   · Amsterdam `.AS` · Milan `.MI` · Madrid `.MC` · Lisbon `.LS` · Brussels `.BR` · Copenhagen `.CO`
   · Stockholm `.ST` · Oslo `.OL` · Helsinki `.HE` · Toronto `.TO` · Vancouver `.V` · Sao Paulo `.SA`
   · Mexico `.MX` · Hong Kong `.HK` · Taipei `.TW` · Seoul `.KS` · Singapore `.SI` · Bombay `.BO`
   · Johannesburg `.JO`.
8. **Non-US issuers — a different ladder, and the issuer's own IR calendar wins.**
   US-centric calendars (Yahoo, Nasdaq, EarningsWhispers) are organised around the US session, so
   for a European, Japanese or Canadian issuer they carry the WRONG release time and sometimes the
   WRONG DATE. Measured 2026-11-04: EarningsWhispers filed Novo Nordisk as "BMO 12:35 PM ET" when
   the 6-K was already out by 03:06 ET; it filed Mitsui under "after the close" when Mitsui's own
   financial calendar says the announcement is **Nov 4, 12:00 JST** (= Nov 3, 22:00 ET — already
   published before a 06:00 ET run); and both aggregators listed Siemens Healthineers for Nov 4
   when the company says **Nov 5, 07:00 CET**. For these names use, in order:
   1. **The issuer's IR financial calendar / results press release** — it gives the report DATE and
      the local announcement TIME, plus the securities codes with their exchanges. That local time
      is what decides `pending` vs `already reported`: convert it to ET with `zoneinfo` (never a
      hardcoded offset — JST is UTC+9, CET/CEST UTC+1/+2) and compare it with the FIRE's scheduled
      instant, not with the wall clock.
   2. **The stockanalysis.com primary-listing page** — `https://stockanalysis.com/quote/<exch>/<sym>/`
      carries `earningsDate` ("Nov 4, 2026"), `marketCap` in LOCAL currency, and a filings feed that
      says whether the results are already out, with an EST timestamp.
   3. **Yahoo quote for the PRIMARY listing** (step 7) for the venue, the local currency and the
      local-currency market cap.
   4. **Consensus**: EarningsWhispers' `Rev est` is already USD even for ADRs and is the cleanest
      revenue number (NVO $11.39B, matching the Zacks consensus); the issuer's own pre-results
      consensus PDF (Siemens Healthineers publishes one) or MarketScreener's calendar gives the
      local-currency EPS and revenue. State the currency on every foreign number.
   **Currency trap:** Yahoo's `earningsTrend` for an ADR comes back in the ISSUER's currency, not
   USD — NVO revenue 73.40B is DKK (≈$11.0B), ITOCY/MITSY 4,013B is JPY. Convert with a NAMED rate
   (Yahoo `DKK=X`, `JPY=X` close) and label the currency, or publish the local figure as-is. Never
   publish a converted EPS next to a US ADR EPS estimate without saying which currency it is in.
9. **Write the markdown file** with a front-matter header (`date`, `cron`, `fire_time_et`,
   `snapshot_et`, `source`, `primary_source`, `status`, `pending_count`, `already_reported_count`)
   so downstream consumers can parse it without guessing.
10. **Append audit line** (local Mavis only — skip on Cloud):
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
| 8001.T (ITOCY) | ITOCHU Corporation | BMO (reported 01:00 ET) | 0.23 | 25.3B | 99.3B | reported |
```

## Hard rules

- Never auto-act on earnings data — read-only reminder.
- If data is sparse (Sunday/holiday), write a 1-line "no earnings today" file. Don't fabricate.
- Consensus estimates from web search only — note source.
- Don't pull analyst price targets (that's a different skill's job).
- **Never print an OTC or ADR ticker as the headline ticker** — the primary listing goes first, the
  US line in parentheses.
- **For a non-US issuer the issuer's own IR calendar outranks every aggregator** — for the report
  date AND the report time.
- **A local-currency number without its currency label is a defect.** Local figures are fine when
  labelled; a converted figure must name the rate it was converted at.

## Source facts (measured 2026-11-04 — re-verify before relying on them)

- **EarningsWhispers is the best single roster source and it is server-rendered**:
  `https://www.earningswhispers.com/calendar/YYYYMMDD` returns the whole day in HTML
  (`Reporting Before the Open` / `Reporting After the Close` sections).
- **Its company pages need a JS cookie.** Without one you get a 2 KB "needs cookies" page instead of
  the ~160 KB page. The wall sets `ewc=<reversed token>` in JS and the token sits inside the wall's
  own HTML, so you can compute it and skip the browser:
  `s="d6tQpU0uwhHW_cBwCjsT5Aey.EEA6F080F89DC140.9322836971"; c=s[::-1]` → send it as cookie `ewc`.
  Check the page LENGTH, not the status code, and fetch company pages sequentially with ~0.3 s
  spacing — 8 parallel threads trip the wall.
- **Each company page carries**: the consensus EPS ("consensus earnings estimate is $X"), the
  revenue estimate ("Rev est $14.74B", in USD even for ADRs) and the expected release time in ET.
- **Yahoo's earnings-calendar JSON endpoint is retired**: `v1/finance/calendar/earnings` returns
  **404**. Use `https://query1.finance.yahoo.com/v10/finance/quoteSummary/<TICKER>?modules=earningsTrend`
  (period `0q` = the quarter being reported) for EPS + revenue, and
  `https://query1.finance.yahoo.com/v7/finance/quote?symbols=...` (batch 50) for market cap. Both
  need the cookie+crumb handshake.
- **Nasdaq's calendar API** (`api.nasdaq.com/api/calendar/earnings?date=...`) gives EPS consensus,
  BMO/AMC and the fiscal quarter, but **no revenue field**.
- **EPS basis differs by source**: EarningsWhispers and Nasdaq/Zacks are mostly adjusted, Yahoo's
  `earningsTrend` is often GAAP for the same name (DDOG 0.64 vs 0.18; QCOM 2.16 vs 1.46;
  FICO 10.89 vs 9.20; ARM 0.48 vs 0.22; HST 0.38 FFO vs 0.09). Publish one and note the other.
- **stockanalysis.com** (`/quote/<exch>/<sym>/`, `/api/search?q=`) is the best non-US source:
  local listing, local-currency market cap, earnings date, "Main Listing" link for OTC lines, and
  a filings feed that reports whether results are already published.

## Out of scope

- Detailed model / DCF revisions — read-only reminder only.
- Earnings reactions (covered by post-market brief).
- Crypto / forex earnings — equities only.
