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
   - **One row per ISSUER.** Two rows that are different share classes of the same company are one
     name: publish the class the S&P 500 list carries (or, absent that, the more liquid one) and
     note the other in the notes. Measured 2026-11-05: Berkshire's Class A and Class B both carry
     a ~$1.22T cap and the same reaction history, and publishing both is noise.
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
   · Johannesburg `.JO` · ASX `.AX` · Taiwan `.TW` · Korea `.KS` (KOSDAQ `.KQ`).
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
9. **Reaction potential — rank the roster by what can MOVE, not by size.**
   A roster where every name is equally weighted is a list, not a screen. At 06:00 ET the reader
   wants to know which of today's names is capable of moving and by how much. Every published row
   therefore carries five extra columns, and the table is sorted by their composite.

   **Run the helper.** It is fetched at RUN time, so a fix lands with no redeploy, and it is the
   only way to compute these columns consistently:

   ```bash
   mkdir -p /workspace/tools
   S=/workspace/tools/earnings_reaction_stats.py
   for U in \
     "https://api.github.com/repos/karizaco/maxhermes-migration/contents/tools/earnings_reaction_stats.py?ref=main" \
     "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/tools/earnings_reaction_stats.py" \
     "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/tools/earnings_reaction_stats.py" ; do
     curl -sL --max-time 30 -A "Mozilla/5.0" -o "$S.tmp" "$U" 2>/dev/null
     # Require the CAPABILITY marker: an older copy silently lacks the columns.
     if grep -q 'REACTION_STATS_VERSION' "$S.tmp" 2>/dev/null; then mv -f "$S.tmp" "$S"; break; fi
     rm -f "$S.tmp"
   done
   if [ ! -s "$S" ]; then echo "reaction-stats: UNAVAILABLE"; else
     python3 "$S" --tickers-file /workspace/.cache/roster.txt \
                 --timing-file /workspace/.cache/timing.txt \
                 --earnings-date "$DATE" --out /workspace/.cache/reaction.json \
                 --csv /workspace/.cache/reaction.csv
   fi
   ```

   `--tickers-file` is the published roster (one US ticker per line, in the order the roster will
   be published); `--timing-file` is the matching `BMO`/`AMC` list. **The helper NEVER writes the
   artifact** — it returns the columns; you merge them into the rows.

   **Column definitions** (these are the contract — do not improvise them):

   | Column | Definition | Source |
   |---|---|---|
   | `Prior day %` | last COMPLETED session's close-to-close % move | Yahoo chart daily bars |
   | `YTD %` | last close vs the first bar of the current calendar year | Yahoo chart daily bars |
   | `Avg abs move %` | mean ABSOLUTE reaction over the name's last 4 past reports | Nasdaq `earnings-surprise` report dates + Yahoo chart bars |
   | `Implied move %` | ATM straddle cost at the first expiry that straddles the event, as % of spot | Cboe delayed-quote option chain |
   | `Prior result` | **the MOST RECENT** reported quarter: `beat` / `miss` vs consensus EPS | Yahoo `earningsHistory` |
   | `Reaction score` | `0.6 x avg_abs_move + 0.4 x implied_move` | derived |

   - **Reaction window.** BMO report on day D -> `close(D-1) -> close(D)`. AMC report on day D ->
     `close(D) -> close(D+1)`. The name's CURRENT release convention is applied to its historical
     reports; if a name switched convention between reports, say so in the notes rather than mixing
     the two windows silently.
   - **Implied-move expiry.** BMO -> the expiry ON the report date (the event lands before that
     expiry's close). AMC -> the first expiry AFTER the report date. Use the ATM strike nearest the
     spot and the mid of the call and the put at that strike.
   - **A missing implied move is substituted by `avg_abs_move`**, so a name with no derivable implied
     move scores exactly its `avg_abs_move`. Never leave the score blank while the inputs exist.
   - **`Prior result` is the LATEST quarter, and Yahoo's array is OLDEST-FIRST.** Measured
     2026-11-06: MRNA's `earningsHistory` starts at the quarter ended 2025-09-30 and ends at
     2026-06-30. Taking the FIRST element publishes a YEAR-OLD verdict — it called CHTR a miss
     when the latest quarter (ended 2026-06-30, reported 2026-07-24) was a beat of +5.9%.
     **Always select the entry with the latest quarter-end date.** `earnings_reaction_stats.py`
     does this in `select_latest_report()` and `tools/test_earnings_reaction_prior_result.py`
     guards it (it fails against the old behaviour).
   - **`reaction_score` is rounded to 2 decimals and the table is sorted by it DESCENDING.** Ties
     break by market cap descending. A name whose score could not be computed sorts last with
     `n/a` — it is NOT dropped from the roster.
   - **A degraded column is declared, never hidden.** If the helper could not compute a row, publish
     `n/a` in the derived cells, set `reaction_degraded: <n>` in the front-matter with the exact
     number of degraded rows, and name the cause in the notes. A name with `n/a` and a name with a
     number are not the same thing; the reader must be able to tell them apart.

   **Fallback when the helper is unavailable** (fetch failed, or it errored): compute the columns
   yourself from the same four sources — Yahoo chart API for the bars, Yahoo `quoteSummary`
   (`modules=earningsHistory`) for the prior result, Nasdaq
   `api.nasdaq.com/api/company/<SYM>/earnings-surprise` for the past report dates (its
   `dateReported` is `M/D/YYYY`, NOT ISO), and the Cboe chain for the implied move. Publish what
   you measured and declare the rest as degraded. **Never estimate a reaction column from the
   market cap or from a similar name.**

10. **Pass B — the non-US primary listings table.** The roster above is US-calendar-shaped, so a
    non-US issuer only appears when a US-listed name happens to report. That is a LOOKUP, not a
    universe. This step builds the universe: a standing candidate list of non-US issuers with
    US-market relevance, checked against each issuer's OWN IR calendar.

    1. **Candidate list** — the issuers in `## Pass B candidate universe` below. It is a STANDING
       list, not a per-day discovery: every candidate is checked every day, so an issuer that
       reports is never missed because no US calendar carried it.
    2. **Date resolution (Rule B, step 8's ladder)** — the issuer's IR financial calendar or results
       press release gives the DATE and the LOCAL announcement time. Convert the local time to ET
       with `zoneinfo` (never a hardcoded offset) and compare it with the FIRE's instant. A date
       confirmed only by an aggregator is **not** published.
    3. **Publish a row only for an issuer whose results fall on the fire date.** Every row carries
       `ticker_primary`, `venue_primary`, `us_peer` and `us_tradeable`:
       - `ticker_primary` — the issuer's PRIMARY listing with its exchange suffix (`7203.T`,
         `005930.KS`, `NESN.SW`).
       - `venue_primary` — the exchange name.
       - `us_peer` — the US-listed security a US trader would actually trade for this issuer: its
         own US ADR/ADS line when one exists (`TM (NYSE ADR)`, `ASML (Nasdaq ADR)`), otherwise the
         closest US-listed name that tracks it.
       - `us_tradeable` — exactly one of `ADR (US-listed)`, `ADR (OTC)`, `US-listed`, `none`.
    4. **No duplicates.** If an issuer is ALREADY published in the US roster that day, do not repeat
       it here — record the skip in the notes with the count. The two tables must not overlap.
    5. **Do not merge the two tables.** The US roster's "every S&P 500 constituent" contract is
       useful precisely because it is scoped; the non-US table is a second, clearly-titled table.
    6. **A covered issuer whose date cannot be confirmed from an issuer-owned page is not
       published.** Say in the notes how many candidates were checked and how many had no
       issuer-confirmed date.

11. **The $50B floor is a cliff — publish what it excludes.** A hard floor decided by rounding is
    invisible to the reader. Publish the band just under it.

    - **Band:** market cap in `[$40B, $50B)` — the names the floor excluded. `band_low_usd` in the
      front-matter carries the exact number used.
    - **Candidates:** the largest COMMON shares in that band that are NOT S&P 500 members (an S&P
      500 member is already in the roster, whatever its cap). **Filter out every non-common line**:
      preferreds, notes, depositary receipts, warrants, rights and units. The TradingView scanner
      types several of them as `stock` and gives them plain symbols, so the filter is on the
      DESCRIPTION, not on the symbol: exclude any name whose description contains
      `Preferred`, `Notes`, `Subordinated`, `Depositary`, `Warrant`, `Right` or `Unit`. Measured
      2026-11-05: Prudential's "5.625% Junior Subordinated Notes due 2058" and four sibling
      preferred lines all carry a ~$43.7B cap and would otherwise fill the whole band table with
      four rows of the same company.
    - **Columns:** `Ticker | Company | Mkt cap | Reports today` — the last column answers the
      question the reader actually has ("does this one matter today?"). Sort by market cap
      descending. Publish 5-10 rows; if fewer exist in the band, publish what exists and say so.
    - **The band is a LOWER BOUND on the excluded set**: names below $40B are excluded by the band,
      not by the floor, and the notes must say so.
    - **Boundary case:** a roster row whose cap is inside the floor by less than **$0.5B** carries
      `boundary_case` in its `Flag` cell (`-` otherwise). The reader can then see that the
      inclusion is marginal instead of having to compute it.

12. **Write the markdown file** with a front-matter header (`date`, `cron`, `fire_time_et`,
    `snapshot_et`, `source`, `primary_source`, `status`, `pending_count`, `already_reported_count`,
    `non_us_count`, `reaction_ranked`, `band_low_usd`) so downstream consumers can parse it without
    guessing. `reaction_ranked` is `true`. If any reaction column was degraded, add
    `reaction_degraded: <n>`.
13. **Append audit line** (local Mavis only — skip on Cloud):
   `earnings_reminder target=earnings:{date} watchlist_hits={n} bigcap_hits={n}`

## Pass B candidate universe — the STANDING list (measured 2026-11-05/06, re-verify before relying on it)

This is the candidate list for step 10. It is **standing**, not per-day: every candidate is checked
every day against its own IR calendar, so an issuer that reports is never missed because no US
calendar carried it. Add to it when a large non-US issuer becomes US-market-relevant; remove a row
only when the issuer is delisted.

Every `ticker_primary` below was resolved live on 2026-11-05 and **re-fetched on Yahoo's chart API
to prove it resolves** (venue + local currency + name). `us_peer` is the US-listed line, and
`us_tradeable` says what kind of line it is — TradingView's `type` column separates a genuine ADR
(`dr`) from an ordinary share (`stock`) and is the source for that field.

| issuer | ticker_primary | venue_primary | us_peer | us_tradeable |
|---|---|---|---|---|
| ASML Holding | `ASML.AS` | Euronext Amsterdam | ASML (Nasdaq) | ADR (US-listed) |
| TSMC | `2330.TW` | Taiwan Stock Exchange | TSM (NYSE) | ADR (US-listed) |
| Samsung Electronics | `005930.KS` | Korea Exchange | SSNLF (OTC) | ADR (OTC) |
| SK hynix | `000660.KS` | Korea Exchange | SKHY (Nasdaq) | ADR (US-listed) |
| Toyota Motor | `7203.T` | Tokyo Stock Exchange | TM (NYSE) | ADR (US-listed) |
| Sony Group | `6758.T` | Tokyo Stock Exchange | SONY (NYSE) | ADR (US-listed) |
| Hitachi | `6501.T` | Tokyo Stock Exchange | HTHIF (OTC) | ADR (OTC) |
| Fujitsu | `6702.T` | Tokyo Stock Exchange | FJTSY (OTC) | ADR (OTC) |
| Nissan Motor | `7201.T` | Tokyo Stock Exchange | NSANY (OTC) | ADR (OTC) |
| Mitsubishi UFJ | `8306.T` | Tokyo Stock Exchange | MUFG (NYSE) | ADR (US-listed) |
| Mitsubishi Electric | `6503.T` | Tokyo Stock Exchange | MIELF (OTC) | ADR (OTC) |
| Mitsubishi Heavy Industries | `7011.T` | Tokyo Stock Exchange | MHVYF (OTC) | ADR (OTC) |
| Nintendo | `7974.T` | Tokyo Stock Exchange | NTDOY (OTC) | ADR (OTC) |
| Takeda Pharmaceutical | `4502.T` | Tokyo Stock Exchange | TAK (NYSE) | ADR (US-listed) |
| Nomura Holdings | `8604.T` | Tokyo Stock Exchange | NMR (NYSE) | ADR (US-listed) |
| Daiichi Sankyo | `4568.T` | Tokyo Stock Exchange | DSNKY (OTC) | ADR (OTC) |
| KDDI | `9433.T` | Tokyo Stock Exchange | KDDIY (OTC) | ADR (OTC) |
| Tokyo Electron | `8035.T` | Tokyo Stock Exchange | TOELY (OTC) | ADR (OTC) |
| Advantest | `6857.T` | Tokyo Stock Exchange | ATEYY (OTC) | ADR (OTC) |
| Nestle | `NESN.SW` | SIX Swiss Exchange | NSRGY (OTC) | ADR (OTC) |
| Roche | `ROG.SW` | SIX Swiss Exchange | RHHBY (OTC) | ADR (OTC) |
| Novartis | `NOVN.SW` | SIX Swiss Exchange | NVS (NYSE) | ADR (US-listed) |
| Novo Nordisk | `NOVO-B.CO` | Nasdaq Copenhagen | NVO (NYSE) | ADR (US-listed) |
| Unilever | `ULVR.L` | London Stock Exchange | UL (NYSE) | ADR (US-listed) |
| Shell | `SHEL.L` | London Stock Exchange | SHEL (NYSE) | ADR (US-listed) |
| HSBC | `HSBA.L` | London Stock Exchange | HSBC (NYSE) | ADR (US-listed) |
| BP | `BP.L` | London Stock Exchange | BP (NYSE) | ADR (US-listed) |
| Rio Tinto | `RIO.L` | London Stock Exchange | RIO (NYSE) | ADR (US-listed) |
| Airbus | `AIR.PA` | Euronext Paris | EADSY (OTC) | ADR (OTC) |
| TotalEnergies | `TTE.PA` | Euronext Paris | TTE (NYSE) | US-listed |
| LVMH | `MC.PA` | Euronext Paris | LVMUY (OTC) | ADR (OTC) |
| Siemens | `SIE.DE` | XETRA | SIEGY (OTC) | ADR (OTC) |
| SAP | `SAP.DE` | XETRA | SAP (NYSE) | ADR (US-listed) |
| Bayer | `BAYN.DE` | XETRA | BAYRY (OTC) | ADR (OTC) |
| Banco Santander | `SAN.MC` | Bolsa de Madrid | SAN (NYSE) | ADR (US-listed) |
| Alibaba Group | `9988.HK` | Hong Kong | BABA (NYSE) | ADR (US-listed) |
| Tencent | `0700.HK` | Hong Kong | TCEHY (OTC) | ADR (OTC) |
| Hong Kong Exchanges & Clearing | `0388.HK` | Hong Kong Stock Exchange | HKXCY (OTC) | ADR (OTC) |
| BHP | `BHP.AX` | ASX | BHP (NYSE) | ADR (US-listed) |
| Commonwealth Bank of Australia | `CBA.AX` | ASX | CBAUF (OTC) | ADR (OTC) |
| Macquarie Group | `MQG.AX` | ASX | MQBKY (OTC) | ADR (OTC) |
| Vale | `VALE3.SA` | B3 (Brazil) | VALE (NYSE) | ADR (US-listed) |
| Petrobras | `PETR4.SA` | B3 (Brazil) | PBR (NYSE) | ADR (US-listed) |
| Constellation Software | `CSU.TO` | Toronto Stock Exchange | CNSWF (OTC) | ADR (OTC) |

### ADR-ticker traps — every one of these cost a wrong row

The US line of a non-US issuer is NOT guessable from the company name. Measured 2026-11-05:

- **`AIRYY` is Air China, NOT Airbus.** Airbus' OTC line is `EADSY` (Yahoo also serves `EADSF`;
  TradingView serves both). A name-to-ticker guess publishes the wrong company.
- **`HTHTF`, `MEELY`, `TELLY`, `SSNNF` and `ROG.SW` do not resolve on Yahoo** — the working symbols
  are `HTHIF`, `MIELF`, `TOELY`, `SSNLF` and (`RO.SW` / `ROP.SW`). Always prove the US line with one
  chart call (`https://query1.finance.yahoo.com/v8/finance/chart/<SYM>?interval=1d&range=5d`)
  and read `meta.shortName` + `meta.exchangeName` before it goes in the table.
- **Roche's SIX bearer line is `ROG.SW`** (Yahoo carries `RO.SW` for it and `ROP.SW` for the
  participation certificate) — note it so the reader is not stuck.
- **`TTE` is an ordinary-share line, not an ADR** — TradingView types it `stock`, so
  `us_tradeable` is `US-listed`, not `ADR (US-listed)`.
- **Added 2026-11-06, all three proven on Yahoo's chart API (venue + currency + name):**
  `HKXCY` (also served as `HKXCF`) → Hong Kong Exchanges & Clearing, OTC/USD;
  `MQBKY` → Macquarie Group, OTC/USD; `CNSWF` → Constellation Software, OTC/USD, a 1:1
  depositary line for `CSU.TO` (whose own quote is CAD on Toronto).

### Which day does a non-US print belong to?

The issuer announces on ITS OWN local schedule, so the ET day is often not the local calendar day:

- A **Japanese** issuer that publishes at 15:00-16:00 JST on Nov 6 lands at **01:00-02:00 ET on
  Nov 6** — already published when a 06:00 ET reader opens the brief (`Status: reported`).
- A **Japanese** issuer that publishes at 07:00 JST on Nov 6 lands at **17:00 ET on Nov 5** —
  the previous ET day.
- A **European** issuer that publishes at 07:00 CET on Nov 6 lands at **01:00 ET on Nov 6**.
- Convert with `zoneinfo`, never a hardcoded offset, and compare with the FIRE's instant.

Measured on this universe for 2026-11-05/06: the IR-confirmed dates near the window are **KDDI
Nov 6, 2026** (issuer IR calendar + issuer newsroom: results announced Nov 6, webcast 16:00 JST =
02:00 ET), **Siemens Nov 12** (issuer press page: 07:00 CET = 01:00 ET), **Mitsubishi UFJ Nov 13**
(issuer page), **Tencent Nov 18** (issuer page: 20:00 ET). **TSMC, Samsung, Toyota and Alibaba had
NO date published on their own IR pages** — an aggregator estimate is not a publishable date, so
those candidates stay unpublished until the issuer posts one.

**Two more IR-confirmed dates measured on the 2026-11-06 fire, both on the PREVIOUS ET day:**
**Mitsubishi Heavy Industries** disclosed its H1 FY2026 results on 6 Nov JST at 13:30 (TDnet
timestamp) = **5 Nov 23:30 ET**, and **Macquarie Group** announced its 2027 half-year result on
6 Nov at 07:00 AEDT = **5 Nov 15:00 ET**. Both are announced ON 6 November locally and both land on
**5 November** in ET — a brief dated 6 November must NOT carry them. Conversely **HKEX** announced
its Q3 2026 results on 6 November HKT (issuer financial calendar; released after the Hong Kong
close, so already public at 06:00 ET) and **Constellation Software** released its Q3 results after
the TSX close on 6 November (16:00 ET, issuer press release) — both belong to the 6 November ET
day. The local announcement date is never the ET date; convert it.

## ARTIFACT FORMAT CONTRACT v2 (EARNINGS_REMINDER_V2)

The artifact is a SCREEN, not a list. Three tables, in this order, then the notes.

1. **`## Big S&P 500 today`** — the US roster: S&P 500 constituents plus US-listed names above the
   market-cap floor. Columns, in this order:

   `Ticker | Company | Time | EPS est | Rev est | Mkt cap | Prior day % | YTD % | Avg abs move % | Implied move % | Prior result | Reaction score | Status | Flag`

   Sorted by `Reaction score` **DESCENDING** (ties break by market cap descending). `Status` is
   `pending` or `reported`. `Flag` is `boundary_case` for a name inside the floor by less than
   $0.5B, otherwise `-`.
2. **`## Non-US primary listings`** — Pass B. Columns:

   `ticker_primary | venue_primary | Company | Report time (local) | us_peer | us_tradeable | Status`

   Rows only for issuers whose results fall on the fire date, with the date confirmed on an
   issuer-owned page. `us_tradeable` is one of `ADR (US-listed)` / `ADR (OTC)` / `US-listed` /
   `none`.
3. **`## Just below the line`** — the band just under the market-cap floor that the floor
   excluded. Columns: `Ticker | Company | Mkt cap | Reports today`.
4. **`## Already reported (before 06:00 ET)`** — only when a name printed before the fire.
5. **`## Notes`**, **`## Source health`**, **`## Rules applied`**.

**The three tables must not overlap.** A non-US issuer is published in ONE of them, never in two.
The US roster keeps its own scope (every S&P 500 constituent, whatever its cap); the non-US table
is a separate universe, not an extension of the roster.

The front-matter carries `date`, `cron`, `fire_time_et`, `snapshot_et`, `source`,
`primary_source`, `status`, `pending_count`, `already_reported_count`, `non_us_count`,
`reaction_ranked: true` and `band_low_usd`; add `reaction_degraded: <n>` when a reaction column
could not be computed for exactly `n` rows.

**Verify the artifact before pushing.** The checker is a separate implementation of this contract:

```bash
curl -sL --max-time 30 -A "Mozilla/5.0" -o /workspace/tools/check_earnings_reminder_artifact.py \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/tools/check_earnings_reminder_artifact.py"
python3 /workspace/tools/check_earnings_reminder_artifact.py /workspace/earnings/{date}-reminders.md
```

It exits 1 and names every violation — a missing column, a roster that is not sorted by reaction
score, a score that does not match its inputs, an empty `us_peer`, a name published in two
tables, a band row that is not actually below the floor, a missing `boundary_case` flag. **Do not
push an artifact the checker rejects.**

## Sample output

```markdown
---
date: 2026-11-06
cron: 19-earnings-reminder-daily
fire_time_et: 06:00
snapshot_et: 06:04
source: EarningsWhispers earnings calendar + Yahoo Finance + Nasdaq earnings API
primary_source: Yahoo Finance (market cap) | EarningsWhispers (EPS est, revenue est, release time)
status: ok
pending_count: 12
already_reported_count: 3
non_us_count: 2
reaction_ranked: true
band_low_usd: 40000000000
---

# Earnings - Fri 2026-11-06

## Big S&P 500 today

| Ticker | Company | Time | EPS est | Rev est | Mkt cap | Prior day % | YTD % | Avg abs move % | Implied move % | Prior result | Reaction score | Status | Flag |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ARM | Arm Holdings plc | AMC 4:05 PM | 0.48 | $1.37B | $216.3B | -13.08 | 45.32 | 9.07 | 12.34 | beat | 10.38 | pending | - |
| QCOM | Qualcomm Incorporated | AMC 4:00 PM | 1.46 | $10.15B | $175.6B | -9.49 | -9.38 | 8.92 | 8.58 | beat | 8.78 | pending | - |
| KDP | Keurig Dr Pepper Inc. | BMO 6:30 AM | 1.02 | $4.60B | $50.1B | +0.40 | -3.10 | 3.10 | n/a | beat | 3.10 | pending | boundary_case |

## Non-US primary listings

| ticker_primary | venue_primary | Company | Report time (local) | us_peer | us_tradeable | Status |
|---|---|---|---|---|---|---|
| 7203.T | Tokyo Stock Exchange | Toyota Motor Corp | Nov 6, 07:00 JST | TM (NYSE ADR) | ADR (US-listed) | pending |
| 005930.KS | Korea Exchange | Samsung Electronics | Nov 6, 08:00 KST | SSNLF (OTC) | ADR (OTC) | pending |

## Just below the line - excluded by the $50B floor

| Ticker | Company | Mkt cap | Reports today |
|---|---|---|---|
| MDLN | Medline Industries | $45.9B | no |
| SLF | Sun Life Financial | $44.8B | no |

## Already reported (before 06:00 ET)

| Ticker | Company | Released | Actual | vs consensus |
|---|---|---|---|---|
| NOVO-B.CO (NVO) | Novo Nordisk A/S | ~01:00 ET | Q3 rev $12.19B, adj EPS $0.89 | beat |

## Notes

- **Ranked by reaction potential**, not by market cap: ARM and QCOM lead on their typical and
  implied reaction size, not on size.
- **KDP is $0.1B inside the $50B floor** and is flagged `boundary_case`; the band below the floor
  is a lower bound, so names under $40B are excluded by the band and not by the floor.
- **Ticker convention (primary listing first):** ADR and OTC lines are shown on the issuer's
  PRIMARY listing with its exchange suffix, with the US line in parentheses - `8001.T (ITOCY)`,
  `NOVO-B.CO (NVO)`.
- **No watchlist section.** `research/watchlist.yaml` does not exist in this runtime, so the
  `## Your watchlist` section is omitted rather than shipped empty.

## Source health

| Source | URL / query | Status | Notes |
|---|---|---|---|
| EarningsWhispers calendar | `https://www.earningswhispers.com/calendar/20261106` | ok | server-rendered |
| Yahoo chart API | `query1.finance.yahoo.com/v8/finance/chart/<SYM>` | ok | daily bars for the reaction columns |

## Rules applied

- S&P 500 membership verified against the live constituent list - never from memory.
- Report dates confirmed against issuer sources for every name near the inclusion boundary.
- Reaction columns computed from measured bars, past report dates and option chains; a value that
  could not be measured is published as `n/a` and counted in `reaction_degraded`.
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
- **The roster is ranked by reaction potential, not by market cap.** Every published row carries the
  reaction columns, and the table is sorted by `Reaction score` descending.
- **A reaction column that was not measured is `n/a` and is counted in `reaction_degraded`.** Never
  estimate one from the market cap, a peer name, or a guess.
- **The non-US table is a separate table, and it never overlaps the US roster.** A name published in
  one is not repeated in the other.
- **The market-cap floor is published with what it excludes.** The band table names the names the
  floor kept out, and a row inside the floor by less than $0.5B is flagged `boundary_case`.

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

## Source facts (measured 2026-11-05/06 for the reaction layer — re-verify before relying on them)

- **Yahoo chart API needs NO crumb.** `query1.finance.yahoo.com/v8/finance/chart/<SYM>?interval=1d&range=2y`
  answers with the crumb-less request (AAPL: 501 daily bars over 2y). The rows carry a close per
  session; `prior_day_move_pct` and `ytd_move_pct` come straight from it.
- **Yahoo `quoteSummary` DOES need the cookie+crumb handshake, and the jar must be SEEDED.** The
  handshake is: `curl -c jar https://fc.yahoo.com` FIRST, then
  `curl -b jar -c jar https://query1.finance.yahoo.com/v1/test/getcrumb`. Skipping the seed makes
  `getcrumb` answer with the literal body `{"finance":{"result":null,"error":{"code":"Unauthorized"}}}`
  and every `quoteSummary` call then returns an EMPTY body (not an error). `modules=earningsHistory`
  gives the prior beat/miss; `modules=calendarEvents` gives only the NEXT date, never history.
- **Nasdaq `api.nasdaq.com/api/company/<SYM>/earnings-surprise` is the past-REPORT-date source.**
  Its `dateReported` is `M/D/YYYY` ("11/2/2026"), NOT ISO — an ISO regex silently returns zero dates
  and every `Avg abs move %` becomes `n/a`. It carries four quarters at most, so the reaction
  average is a 4-event mean and the sample size is published with it.
- **Cboe's delayed-quote chain works and is current**: `cdn.cboe.com/api/global/delayed_quotes/options/<SYM>.json`
  (AAPL: 3,432 contracts). The underlying block's `close` is the settled close and `prev_day_close`
  the prior close. **The chain carries NO expiry field** — parse the OCC symbol
  `{ROOT}{YYMMDD}{C|P}{strike*1000 padded to 8}`: `strike = int(s[-8:])/1000`, `side = s[-9]`,
  `expiry = s[-15:-9]`. Cast every date part to `int` or the parse throws.
- **TradingView scanner**: the payload key is `filter` (SINGULAR) — `filters` is silently ignored
  and returns the whole universe. Numeric ops are `greater` / `less` (not `egreater`). `market_cap_basic`
  is USD. Use `type in (stock, dr)` so ADRs are not dropped.
- **Scanner filter traps measured 2026-11-06:** `{"left":"type","operation":"in","right":[...]}` is
  rejected with **HTTP 400** — filter the type in python after the call instead of in the payload.
  `in_range` needs BOTH `right` and `second_right` (a single value is a 400). To select a DATE
  column, use `greater` / `less` with **epoch seconds** (the value must be a whole hour boundary:
  `1793959200` works, `1793959199` returns HTTP 400). A date-column sweep is the cheapest
  completeness check for a roster: filter every US name whose `earnings_release_next_date` falls on
  the fire date and compare that set with the calendar-derived roster.

## Out of scope

- Detailed model / DCF revisions — read-only reminder only.
- Earnings reactions (covered by post-market brief).
- Crypto / forex earnings — equities only.
