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

## Run budget and fetch discipline (added 2026-11-13, after the 2026-11-12 fire)

This routine exists to feed cron #26, the 08:30 ET pre-market brief. It is a SCREEN: a brief that
arrives on time with the names that matter beats a complete one that arrives at 09:15. The
2026-11-12 fire took **3h12m** and landed **42 minutes after the brief it feeds**, with a
publishable draft already on disk at 07:17 ET.

- **06:45 ET is the discovery cutoff.** Every candidate you intend to publish must have its report
  date confirmed by 06:45 ET. After 06:45 ET you do not start a new investigation, you do not chase
  a rabbit hole, and you do not re-pull a universe. You publish what you have.
- **07:15 ET is the ship deadline.** Write the file, run the checker, push. If a check is still
  open at 07:15 ET, publish without it and say what was not checked.
- **Two fetches per candidate, then drop.** A candidate gets at most TWO issuer fetches. If the
  date is still unconfirmed, drop it, count it in the notes, and move on. Measured 2026-11-12:
  Mitsubishi UFJ consumed 19 minutes and seven files (six of them the same JS-rendered IR page)
  and produced NO published row — the issuer confirms the date but publishes no release hour, so
  the ET day cannot be fixed and the name could not be published anyway.
- **Never construct an issuer URL.** Guessed IR paths die on 404: measured 2026-11-12, four of six
  guessed paths 404'd (`/investors/financial-results`, `.../quarterly-results`,
  `.../results-reports-and-presentations`, `.../financial-information/financial-results`) and one
  host did not resolve at all. Resolve the canonical URL from the issuer's own newsroom or from a
  search result, and keep the fetched page under `.cache/` so it is never fetched twice.
- **Do not fetch a host that is blocked from this egress.** Each of these cost a dead call on
  2026-11-12: `stockanalysis.com` (Cloudflare 403 — use Yahoo chart metadata
  `meta.exchangeName` / `meta.currency` plus TradingView's `exchange` / `type` columns),
  `marketbeat.com` (403 — read the indexed page, or use the declared primary source instead),
  `vara-services.com` (403 / timeout — take the consensus figure from the press item that names
  the vendor).
- **One universe pull, not three.** The TradingView sweep is one POST with `range: [0, 30000]`
  sorted by `market_cap desc`. On 2026-11-12 three successive pulls (`tv_universe`, `tv_bycap`,
  `tv_full`) burned ten minutes and the first two were throwaway.
- **Write every measurement to disk as you take it** — one JSON file per candidate under
  `.cache/rows/<KEY>.json` (KEY = a slug, e.g. `MRK.DE`), written temp-file-then-rename so a
  concurrent writer can never corrupt it. Fields: `key, ticker, report_time_et, actual, consensus,
  source_url, source_type, cap_usd, notes`. The artifact's numbers come from that ledger, not from
  the conversation: on 2026-11-12 a context compaction cost roughly an hour of re-verification
  because six confirmed issuer results existed only in prose.

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
   - **`stockanalysis.com` is Cloudflare-walled from the Cloud runtime — do not retry it.**
     Measured 2026-11-12: four fetches (three quote pages and one search) returned 403 and
     produced nothing. The working substitute is the Yahoo chart call below plus TradingView's
     `exchange` and `type` columns, and every line published on 2026-11-12 was resolved without it.
     Keep stockanalysis in the ladder only as "if reachable".
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
      says whether the results are already out, with an EST timestamp. **This source is blocked from
      the Cloud runtime (403); when it does not answer, Yahoo chart metadata + TradingView's
      exchange/type columns replace it and the artifact says so.**
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
     # 2026-11-13: the marker is the Nasdaq prior-result fallback token, so a CACHED OLD COPY
     # (one without the fallback) cannot win the race and serve a name with no prior result.
     if grep -q 'REACTION_STATS_NASDAQ_PRIOR_RESULT' "$S.tmp" 2>/dev/null &&
        grep -q 'REACTION_STATS_VERSION' "$S.tmp" 2>/dev/null; then mv -f "$S.tmp" "$S"; break; fi
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
   - **Yahoo's `earningsHistory` is EMPTY for some names, and the Nasdaq table already answers the
     question.** Measured 2026-11-12: Brookfield Corporation has no Yahoo `earningsHistory` AND no
     Yahoo `earningsTrend`, so the prior result had to be read by hand from Nasdaq and typed into
     the artifact. The helper now falls back automatically to the SAME Nasdaq
     `earnings-surprise` call it already makes for the past report dates — that table carries `eps`
     (actual), `consensusForecast` (estimate), `percentageSurprise` and `dateReported` (M/D/YYYY),
     so the fallback costs no extra request. **The artifact names the source per row**
     (`prior_report_source`: `yahoo_earningsHistory` or `nasdaq_earnings_surprise`); a prior result
     with no source named is a defect, not a convenience.
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
    7. **A batch calendar beats per-issuer fetching.** One page that lists many issuers' release
       slots — a wire-service results calendar, an exchange's disclosure calendar, the issuer's own
       events feed — resolves a whole evening's European wave in ONE request. Measured 2026-11-12:
       a single dpa-AFX results-calendar page gave the local release slot for six European issuers
       that then each had to be confirmed individually. Use the batch page to FIND candidates; every
       published row is still confirmed on its issuer-owned page.
    8. **A date without a release hour is an undetermined ET day, so it is not published.** If the
       issuer confirms the DATE but publishes no local announcement TIME, the ET day cannot be
       fixed — a JST-morning release lands on the previous ET day, an after-close release on the
       next. Measured 2026-11-12: MUFG, SMFG and Mizuho each confirm Nov 13 in their own calendars
       and publish no hour. They are NOT published, and the notes say how many were dropped for
       that reason. (A Japanese issuer's release HOUR comes from the TDnet/TSE disclosure
       timestamp, not from its IR PDF.)

11. **The $50B floor is a cliff — publish what it excludes.** A hard floor decided by rounding is
    invisible to the reader. Publish the band just under it.

    - **Band:** market cap in `[$40B, $50B)` — the names the floor excluded. `band_low_usd` in the
      front-matter carries the exact number used.
    - **Candidates:** the largest COMMON shares in that band that are NOT S&P 500 members (an S&P
      500 member is already in the roster, whatever its cap) and that are **US-listed** — a foreign
      issuer's OTC ordinary line belongs to Pass B, not to the US band. Measured 2026-11-12: the
      literal reading of the rule put ten FOREIGN ordinary lines on top of the band (PICC Property
      & Casualty Class H $49.9B, DSV $49.9B, Holcim $49.9B, Swiss Re $49.2B, Commerzbank,
      Danone, ArcelorMittal, Reckitt, Nokia, Jiangsu Hengrui) — none of them a US name.
    - **The non-common filter is MECHANICAL, and its denylist is longer than it looks.** The
      TradingView scanner types several non-common lines as `stock` and gives them plain symbols, so
      the filter is on the DESCRIPTION, not on the symbol. Exclude a row whose description contains
      ANY of: `Preferred`, `Pref`, `Pfd`, `Notes`, `Bond`, `Subordinated`, `Subord`, `Depositary`,
      `Deposit Shs`, `Perp`, `Warrant`, `Right`, `Unit`, `ADR`, `Sponsored`, `Unsponsored`, `LP`,
      `Trust`, `Income`. Measured 2026-11-12: `Preferred|Notes|Subordinated|Depositary|Warrant|
      Right|Unit` ALONE let through four junk lines — Fifth Third's `FITB/PI` ("…Non-Cum Perp")
      and `FITB/PM` ("…Non-Cum Pfd Shs -M") at $49.16B, State Street's `STT/PG` ("Deposit Shs Repr
      1/4000th Non Cum Perp Pfd") at $47.39B and Prudential's `PRS` ("5.625 % Bonds") at $42.20B.
      That last one is the very line the 2026-11-05 note below warns about. Filter in code, never
      by hand.
    - **ONE source for the whole band table, and it is TradingView's ISSUER-LEVEL market cap.**
      The candidate set comes from the scanner, so the caps and the ORDER come from the same
      scanner row — mixing a TradingView candidate set with Yahoo caps is how a $44.5B row and a
      $41.8B row end up in the wrong order. Yahoo is the cross-check; any spread beyond 5% between
      the two is flagged in the notes. Measured 2026-11-12: Rocket Lab is $44.5B on Yahoo and
      $41.81B on TradingView (a 6.4% spread, unflagged in the published artifact) and the two
      sources rank it three places apart.
    - **A multi-class issuer gets ONE row, at the issuer-level cap.** TradingView computes the
      company cap for both classes (HEI and HEI.A both $41.34B); Yahoo computes each class's cap
      as TOTAL SHARES x THAT class's price, so neither Yahoo figure is the company cap. Measured
      2026-11-12: HEICO's Yahoo caps read HEI $48.8B and HEI-A $36.5B against a company cap of
      ~$41.3B — the band table therefore published NEITHER and dropped a legitimate $41.3B NYSE
      common share (HEICO is not in the S&P 500; it is in the band). **Publish the issuer-level cap
      and name the other class in the notes — a broken per-symbol cap is a reason to say so, never a
      reason to drop the row.**
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
    From 2026-11-13 add two more keys:
    - `contract: EARNINGS_REMINDER_V3` — the contract version this artifact was written to.
    - `coverage_receipt: calendar_rows=<n> s_and_p_500_hits=<n> bigcap_hits=<n>
      us_roster_rows=<n> band_rows=<n>` — the artifact's own completeness basis:
      `calendar_rows` = calendar rows scanned on the fire date, `s_and_p_500_hits` = how many of
      them were S&P 500 constituents, `bigcap_hits` = how many were at or above the $50B floor,
      `us_roster_rows` = rows published in the US roster, `band_rows` = rows published in the band.
      **Every hit that is not published is named in the notes with its reason** (a non-US ADR line
      covered in the non-US tables, an issuer-confirmed date that falls outside the fire day, a name
      excluded on Rule B). Measured 2026-11-12: the calendar carried 377 rows, 2 of them S&P 500
      members and 8 at or above the floor, and the roster published 4 — completeness that was
      re-derived by hand after the run, because the artifact only said "47 standing candidates
      checked".
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
| Infineon Technologies | `IFX.DE` | XETRA | IFNNY (OTC) | ADR (OTC) |
| SoftBank Group | `9984.T` | Tokyo Stock Exchange | SFTBY (OTC) | ADR (OTC) |
| Sea Limited | `SE.SI` | Singapore Exchange | SE (NYSE ADR) | ADR (US-listed) |

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

## ARTIFACT FORMAT CONTRACT v3 (EARNINGS_REMINDER_V3)

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
   excluded. Columns: `Ticker | Company | Mkt cap | Reports today`. US-listed common shares only,
   one row per ISSUER at the issuer-level market cap, ONE source for the whole table (the
   scanner's issuer-level cap; the other source is the cross-check and a spread beyond 5% is
   flagged in the notes). A broken per-symbol cap is a reason to publish the issuer-level cap and
   say so — never a reason to drop the row.
4. **`## Already reported (before 06:00 ET)`** — only when a name printed before the fire.
   Columns:

   `Ticker | Company | Released | Actual | vs consensus | us_tradeable`

   The `Ticker` cell is the PRIMARY listing with the US line in parentheses
   (`SIE.DE (SIEGY)`, `015760.KS (KEP)`) — never an OTC headline. `us_tradeable` says what the US
   line actually is, from the same vocabulary as the non-US table. Measured 2026-11-12: 17 of the
   18 overnight prints were OTC-only lines and only one was a NYSE ADR, so without this column
   the reader cannot tell which of them are tradeable in the session the brief is written for.
5. **`## Notes`**, **`## Source health`**, **`## Rules applied`**.

**The three tables must not overlap.** A non-US issuer is published in ONE of them, never in two.
The US roster keeps its own scope (every S&P 500 constituent, whatever its cap); the non-US table
is a separate universe, not an extension of the roster.

The front-matter carries `date`, `cron`, `fire_time_et`, `snapshot_et`, `source`,
`primary_source`, `status`, `pending_count`, `already_reported_count`, `non_us_count`,
`reaction_ranked: true` and `band_low_usd`; add `reaction_degraded: <n>` when a reaction column
could not be computed for exactly `n` rows. **From 2026-11-13 also carry `contract:
EARNINGS_REMINDER_V3` and a `coverage_receipt`** (step 12) — the artifact states its own
completeness basis and the checker proves the receipt matches the published tables.

**Versioning.** Artifacts published before 2026-11-13 are checked under v2 and stay valid — a
contract change must not retroactively fail an artifact that was legal when it was written. The
checker applies the v3 rules (the coverage receipt, the already-reported tradeability column) to
any artifact dated 2026-11-13 or later, or to any artifact that declares the contract key.

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
contract: EARNINGS_REMINDER_V3
coverage_receipt: calendar_rows=147 s_and_p_500_hits=3 bigcap_hits=7 us_roster_rows=3 band_rows=2
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

| Ticker | Company | Released | Actual | vs consensus | us_tradeable |
|---|---|---|---|---|---|
| NOVO-B.CO (NVO) | Novo Nordisk A/S | ~01:00 ET | Q3 rev $12.19B, adj EPS $0.89 | beat | ADR (US-listed) |

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
- **The band is US-listed, one row per issuer, one source.** Foreign ordinary lines belong to Pass
  B, non-common lines are filtered mechanically on the description, and the caps and the order come
  from the same scanner row. A broken per-symbol cap is published as an issuer-level cap with a
  note — never a dropped row.
- **Every already-reported row carries its US line's tradeability** (`us_tradeable`). A reader must
  be able to tell which overnight prints are tradeable in the session the brief is written for.
- **The artifact states its own completeness basis.** The `coverage_receipt` names how many calendar
  rows were scanned, how many were index members, how many cleared the floor, and how many rows
  each table publishes — and every hit that is not published is named in the notes with its reason.
- **A candidate gets two fetches, and the brief ships by 07:15 ET.** A brief that arrives on time
  with the names that matter beats a complete one that arrives at 09:15.

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

## Traps measured on the 2026-11-10 fire — re-verify, but they are not opinions

- **The TradingView scanner's `range` CAP silently truncates a sweep, and the truncation HIDES the
  biggest names.** Measured 2026-11-10: a `range: [0, 5000]` scan of the US universe returned exactly
  5000 rows and never said it was truncated; the $40B+ names it missed were **Infineon ($72B),
  SoftBank Group ($136B) and Petrobras ($112B)** — i.e. the sweep that was supposed to prove the
  roster complete would have missed two of the four non-US issuers published that day. **Always
  cross-check the sweep with a market-cap-filtered second call** (`market_cap_basic greater 20e9`
  plus the earnings-date window, `range [0, 300]`) and treat the two as a pair: the filtered call is
  the completeness check, the wide call is only the name list.
- **`total_count` is `null` on this scanner** — there is no "did I get everything" signal. The
  filtered call is the only guard.
- **The EarningsWhispers calendar's two lists are delimited by the SECTION HEADINGS, and
  `cal-section` after the AMC heading SKIPS the AMC list.** Measured 2026-11-10: searching for the
  next `class="cal-section"` after `Reporting After the Close` lands on the section AFTER the AMC
  list, so the AMC roster parses as EMPTY (0 rows) while the page plainly has 89. **Slice the HTML
  from `Reporting Before the Open` to `Reporting After the Close` for BMO and from the AMC heading
  to the END for AMC**, and assert both counts against the page's own headline ("58 before the open
  and 89 after the close").
- **The `ewc` cookie token is NOT in the calendar page.** The token lives in the wall's HTML on a
  COMPANY page. The static token documented above works for company pages without extracting
  anything (`s="d6tQpU0uwhHW_cBwCjsT5Aey.EEA6F080F89DC140.9322836971"`, reversed, sent as `ewc`) —
  verified 2026-11-10 on TDG, SE and PBR (161 KB pages, not the 2 KB cookie wall). Grep the calendar
  page for the token and you will not find it; do not treat that as a failure.
- **An issuer can publish BEFORE the ET day it belongs to, and a company page may have already
  MOVED ON to the next quarter.** Measured 2026-11-10: EarningsWhispers' IFNNY page read "expected
  to report earnings on November 18, 2026" — Infineon had already published its FY2026 Q4 on
  10 November (its own press release, 07:30 CET), so the aggregator had rolled forward. **A company
  page showing a LATER date than the fire date is evidence the issuer ALREADY reported**, not a
  wrong date; confirm against the issuer's IR page before publishing either way.
- **The implied-move expiry can be later than the report date, and that is not a bug.** Measured
  2026-11-10: TDG has NO expiry before 2026-11-20 (its listed expiries were 261120, 261218, 270219,
  270521, 271217), so for a 10 November event the first expiry that straddles it is 20 November.
  The column definition ("ATM straddle cost at the first expiry that straddles the event") governs,
  not "the expiry on the report date". The Cboe chain's option symbol lives under `data.options[].option`
  (NOT `option_symbol`), the key is `option`, and the expiry is `symbol[3:9]` with the strike in
  `symbol[-8:]` and the side in `symbol[-9]`.
- **Yahoo does not quote every primary listing, and that is not a reason to drop the issuer.** Sea
  Limited's SGX line (`SE.SI`) returns no quote from Yahoo's `v7/finance/quote` (it comes back
  `type=NONE, marketCap 0`) and `stockanalysis.com` is behind a Cloudflare challenge. Sea's primary
  listing was confirmed instead from Wikipedia (SGX ordinary shares primary, NYSE ADS secondary) plus
  the issuer's own 27 October 2026 release. Publish the primary listing with the standard exchange
  suffix and say in the notes that the quote source has no coverage for that line — do not publish a
  US ADR as the headline and do not drop the issuer.
- **Yahoo's quote page prints "S&P 500" as a BENCHMARK LABEL, not as a membership statement.**
  Measured 2026-11-10: the Yahoo quote pages for HEI and WCN both show "S&P 500 (^GSPC)" next to
  the price, and neither company is a constituent. Membership must come from the live Wikipedia
  constituent list (or an index-membership database) — `HEI` and `WCN` are both OUT of the index
  (the latter confirmed twice, by the Wikipedia list and by an index-membership database dated
  23 October 2026) and both belong in the band table.

## Traps measured on the 2026-11-12 fire — re-verify, but they are not opinions

- **A US issuer's release time can be a GENERIC after-close stamp on TradingView.** Measured
  2026-11-12: AMAT carried 16:01 ET and NU carried 16:00 ET, while EarningsWhispers carried 16:00
  and 17:40. Both TradingView stamps are placeholders (16:00/16:05 ET for every US name), and both
  were wrong. **TradingView is a DISCOVERY instrument: every published time comes from
  EarningsWhispers (US names) or the issuer (everything else), and the artifact says which.**
- **A TradingView next-release stamp can be STALE, and a name can drop out of the roster because
  of it.** Measured 2026-11-12: BN's `earnings_release_next_date` read 2027-02-11 while Brookfield's
  own IR page confirmed a Nov 12 print at about 7:00 a.m. ET. A roster built on TradingView stamps
  alone would have MISSED Brookfield. Cross-check every published name against the issuer.
- **A TV scan of 20,000 rows can come back short, and the missing rows are the cap-0 tail.**
  Measured 2026-11-12: the `america` sweep returned 20,186 of 20,345 rows, and every missing row
  sat in the cap-0 tail of the market-cap-sorted response — below every threshold the band and the
  floor tests use, so no threshold test was affected. Say so in the source-health notes rather than
  implying a clean full-universe pull.
- **A company page can carry a DIFFERENT report time from the calendar page.** Measured
  2026-11-12: NU and BN are not on EarningsWhispers' Nov 12 calendar page at all, but their
  company pages carry a Nov 12 slot. A roster built only from the calendar page loses them.
- **A "not measured" consensus cell is a feature.** Measured 2026-11-12: five of the eighteen
  overnight prints had a real like-for-like consensus comparison (Hon Hai, Merck KGaA, Sonova,
  Telefonica, KEPCO) and each names its source; the rest read "not measured" rather than carrying
  a number borrowed from a different quarter.
- **The second source's number is often the one the reader should see.** Measured 2026-11-12:
  Telefonica cut its revenue-growth target while raising three others, and KEPCO missed the
  Yonhap Infomax consensus by 47% — a headline that a single "revenue grew" cell would have lost.

## Out of scope

- Detailed model / DCF revisions — read-only reminder only.
- Earnings reactions (covered by post-market brief).
- Crypto / forex earnings — equities only.
