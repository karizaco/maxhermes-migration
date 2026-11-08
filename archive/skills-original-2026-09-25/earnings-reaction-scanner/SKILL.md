---
name: Earnings reaction scanner
description: >-
  Pre-market scan of overnight and after-hours price action across the S&P 500
  top-200 (by market cap) plus the prior session's biggest movers in the full
  US universe, plus EU/UK intraday movers (live session at 08:00 ET), plus
  Australia (ASX) prior-session movers (closed ~6h before scan). Surfaces
  pre-market gaps, AMC reactions, EU intraday reactions, ASX reactions, and
  catalysts. Uses TradingView screen_stocks + stock_screener +
  stock_extended_hours + combined_analysis + financekit earnings_calendar +
  stocktwits. Runs weekdays 08:00 ET, after the pre-market brief.
---

# Earnings reaction scanner

Surfaces the price action that the pre-market brief missed: every name in the S&P 500 top-200 with a meaningful pre-market or post-market move, the prior session's biggest movers across the full US universe, **EU/UK intraday movers during their live session** (started 03:00 ET, mid-session at scan time), and **Australia (ASX) prior-session movers** (ASX closed ~02:00 ET, 6h before scan). Four-pass design replaces the original watchlist-only Pass A and hardcoded 13-name Pass B.

## When
- Cron: `0 8 * * 1-5` America/New_York (weekdays, 08:00 ET — 23 min after pre-market brief, ~90 min before US open; ~5h into the EU session; ~6h after ASX close)
- Manual: user asks "what did names do overnight?" or "show me today's earnings reactions" or "what's moving in Europe?" or "what moved in Australia?"

## Output
- `C:\Users\admin\.minimax\projects\coding-shared\research\earnings-reactions\YYYY-MM-DD.md`
- Compact ≤ 12-line summary in chat reply.

## Universe

**Pass A — S&P 500 top-200 by market cap (broad US pre-market gap scan)**
- One `mcp__tradingview-advanced__stock_screener` call: country=america, stock_type=common, sort_by=market_cap, limit=2000, exclude_otc=true. Take top 200 by market cap.
- For each candidate, call `mcp__tradingview-advanced__stock_extended_hours(symbol)` to extract pre-market %, post-market %, previous close.
- Every row checked regardless of whether it reported — broad catch for US mega-caps.

**Pass B — Prior-session US full-universe top movers**
- Two parallel `mcp__tradingview__screen_stocks` calls:
  - Up: `markets=['america'], filters=[{field: change, operator: greater, value: 3}, {field: market_cap_basic, operator: greater, value: 1000000000}, {field: close, operator: greater, value: 5}], sort_by=change desc, limit=200`
  - Down: `markets=['america'], filters=[{field: change, operator: less, value: -3}, {field: market_cap_basic, operator: greater, value: 1000000000}, {field: close, operator: greater, value: 5}], sort_by=change asc, limit=200`
- Then `extended_hours` on each unique candidate to extract post-market vs regular close.
- Captures non-S&P-500 names that moved big in the prior session — the broadest "what moved" net for US.

**Pass C — EU/UK intraday movers (live session, especially for earnings reactions)**
- At 08:00 ET, EU exchanges are mid-session (started 03:00 ET). For these names, `change_percent` reflects today's intraday move vs previous close — i.e., overnight earnings reactions have already settled into the price.
- EU/UK market list (17 markets): `uk, germany, france, italy, spain, netherlands, belgium, austria, portugal, ireland, finland, denmark, greece, sweden, norway, switzerland, poland`.
- Two parallel `mcp__tradingview__screen_stocks` calls:
  - Up: `markets=[...17 EU markets], filters=[{field: change, operator: greater, value: 2.5}, {field: market_cap_basic, operator: greater, value: 1000000000}, {field: close, operator: greater, value: 5}], sort_by=change desc, limit=300`
  - Down: `markets=[...17 EU markets], filters=[{field: change, operator: less, value: -2.5}, {field: market_cap_basic, operator: greater, value: 1000000000}, {field: close, operator: greater, value: 5}], sort_by=change asc, limit=300`
- Note: EU threshold (2.5%) is slightly above US threshold (3% raw, 2% pre-market) because intraday moves during a live session are noisier than US extended-hours prints.
- Per-ticker catalyst (capped): `mcp__tradingview-advanced__combined_analysis(symbol, exchange, timeframe=1D)` returns TA + news sentiment + headlines in one call. Use the top headline as catalyst.
- Currency: report in local currency (from screener or quote response), note USD-equivalent via approximate FX from `mcp__tradingview-advanced__market_snapshot` (cached, single call).

**Pass D — Australia (ASX) prior-session movers (closed ~6h before scan)**
- ASX trades 10:00–16:00 AEST (UTC+10) = 20:00–02:00 ET (previous day). At 08:00 ET, ASX has been closed ~6h; `change_percent` reflects today's ASX session move vs the previous ASX close.
- ASX is the only Australian primary venue. Single exchange.
- Two parallel `mcp__tradingview__screen_stocks` calls:
  - Up: `markets=['australia'], filters=[{field: change, operator: greater, value: 2.5}, {field: market_cap_basic, operator: greater, value: 500000000}, {field: close, operator: greater, value: 1}], sort_by=change desc, limit=200`
  - Down: `markets=['australia'], filters=[{field: change, operator: less, value: -2.5}, {field: market_cap_basic, operator: greater, value: 500000000}, {field: close, operator: greater, value: 1}], sort_by=change asc, limit=200`
- Note: ASX market_cap floor dropped to $500M (vs $1B for EU/US) because the ASX 100–200 has fewer mega-caps than US/EU. ASX close floor dropped to $1 (vs $5) because ASX has many $2-5 names that US/EU would exclude — these are real, liquid ASX listings, not penny stocks.
- Per-ticker catalyst (capped): `mcp__tradingview-advanced__combined_analysis(symbol, exchange='ASX', timeframe=1D)` — same TA + news sentiment + headlines pattern as EU.
- Currency: AUD local + USD-equivalent from `market_snapshot`.

## Pre-filter: Primary listing exchange whitelist (mandatory)

**Critical:** Both `screen_stocks` and `stock_screener` return secondary/retail listings alongside primary listings. Without filtering, the brief is dominated by OTC ADRs, German retail broker mirrors (Lang & Schwarz), and off-exchange duplicates of primary-listed names. Always apply this filter before any downstream call.

### Drop list (always exclude)
These are secondary, retail-mirror, or off-exchange listings — never the canonical venue for a name. Drop them on sight.

| Exchange code | What it is | Why drop |
|---|---|---|
| `OTC`, `PINK`, `OTCBB`, `GREY` | US OTC / pink sheets | ADRs and shell names — secondary to a primary listing |
| `LS`, `LSX`, `LSIN` | Lang & Schwarz retail broker (Germany) | Mirror listings — same security also traded on FWB/XETR/SWB at primary venue |
| `CHIX` | Cboe Chi-X Australia | Secondary ASX venue; primary is ASX |
| `OTC MKTS`, `OTCM` | OTC Markets | Same as OTC |

### Keep list — primary exchanges only

A name's brief entry uses the **highest-priority primary venue** that appears in the screener output. If a company is listed on both AMS and NASDAQ (e.g., ASML), the primary regional venue (AMS) wins. If a company is dual-listed on LSE and NYSE (e.g., Shell), LSE wins because the company is European-headquartered.

| Priority | Exchange | Country | Notes |
|---|---|---|---|
| 1 | `AMS` (Euronext Amsterdam) | NL | Primary for Dutch names (e.g., AD = Ahold Delhaize, ASML) |
| 2 | `BRU` (Euronext Brussels) | BE | Primary for Belgian names |
| 3 | `PAR` (Euronext Paris) | FR | Primary for French names |
| 4 | `LIS` (Euronext Lisbon) | PT | Primary for Portuguese names |
| 5 | `DUB` (Euronext Dublin) | IE | Primary for Irish names |
| 6 | `XETR` (Xetra/Frankfurt) | DE | **Canonical German listing** — preferred over FWB/SWB/GETTEX/LSX for German names |
| 7 | `MIL` (Borsa Italiana) | IT | Primary for Italian names |
| 8 | `MC` (BME Madrid) | ES | Primary for Spanish names |
| 9 | `LSE` (London SE) | UK | Primary for UK names |
| 10 | `OMXSTO` (Nasdaq Stockholm) | SE | Primary for Swedish names |
| 11 | `OSL` (Oslo Børs) | NO | Primary for Norwegian names |
| 12 | `CO` (Nasdaq Copenhagen) | DK | Primary for Danish names |
| 13 | `HE` (Nasdaq Helsinki) | FI | Primary for Finnish names |
| 14 | `VI` (Wiener Börse) | AT | Primary for Austrian names |
| 15 | `AT` (Athens Exchange) | GR | Primary for Greek names |
| 16 | `SW` (SIX Swiss) | CH | Primary for Swiss names |
| 17 | `WA` (Warsaw SE) | PL | Primary for Polish names |
| 18 | `NASDAQ`, `NYSE`, `AMEX`, `NYSEArca`, `ARCA`, `PCX`, `BATS`, `IEX` | US | Primary for US names |
| 19 | `ASX` (Australian SE) | AU | Primary for Australian names — only venue in priority table without a country-level secondary venue above it |
| 20 | `EURONEXT` | pan-EU | Fallback for Euronext-listed names (used when AMS/BRU/PAR/LIS/DUB aren't listed individually) |

### Drop list — also acceptable to drop
For some passes, drop these too if the screener output is dominated by them:
- `FWB` (Frankfurt traditional floor), `SWB` (Stuttgart), `GETTEX` (Tradegate retail), `TRADEGATE`, `DUS` (Düsseldorf) — real German exchanges but secondary to XETR. Keep one if XETR is missing; otherwise drop the secondary German venue for any company that also appears on XETR.

### Dedupe logic (after applying keep list)
For each company, if it appears on multiple primary exchanges:
1. **Regional primary beats US ADR.** E.g., ASML Holdings shows as AMS:ASML (primary) and NASDAQ:ASML (ADR). Keep AMS, drop NASDAQ.
2. **Highest-priority primary venue wins** per the table above.
3. **Within the same region, highest market cap wins.** E.g., if ARM shows as LSE:0ADF and BME:0ADF, keep LSE (priority 9 > MC at 8).
4. **Exception for genuine US mega-caps** that have no non-US primary (e.g., AAPL, MSFT) — keep the US listing.
5. **Exception for genuinely US-headquartered companies dual-listed** (e.g., CRH plc is Irish-headquartered, so LSE:CRH wins; Coca-Cola is US-headquartered, keep NYSE:KO).
6. **ASX-only names get priority 19 with no dedupe needed** — there's no US ADR of BHP that's more relevant than ASX:BHP.

### Earnings calendar data — coverage and fallback

| Region | Earnings source | Reliability |
|---|---|---|
| US (Pass A + B) | `mcp__financekit__earnings_calendar(symbol)` | ✅ Reliable — primary tool for US earnings-driven tagging |
| EU primary listings | `mcp__tradingview-advanced__combined_analysis(symbol, exchange, timeframe=1D)` | ⚠ Partial — news headlines include earnings mentions but no structured calendar. Tag as earnings-driven (Y) only if the top headline clearly mentions "earnings", "results", "Q1/Q2/Q3/Q4", "beats", or "misses" |
| AU (ASX) | `mcp__tradingview-advanced__combined_analysis(symbol, exchange='ASX', timeframe=1D)` | ⚠ Partial — same as EU; ASX-listed companies typically report in their FY half (Feb/Aug) or quarterly for the largest names. Headline detection same keywords. |
| EU / AU (fallback) | `mcp__tradingview__screen_stocks` with `earnings_release_next_date` filter | ⚠ Try first; if the field is rejected by the tool, fall back to news-only |
| EU / AU (deeper fallback) | `mcp__stocktwits__symbol_stream(symbol, limit=15)` | ⚠ Use only when both above fail — community messages may surface earnings threads |

**Known gap:** TradingView's API exposes earnings calendar data in its web UI (you can see it on each stock page), but the underlying field is not confirmed to be reachable via the MCP `screen_stocks` filter syntax. Until that's tested end-to-end, EU and AU earnings-driven tagging is best-effort. The brief explicitly notes this gap in source health.

**AU-specific earnings cycle note:** ASX-listed companies report in two main windows:
- February (interim/H1 results) — for the Aug-Jan fiscal half
- August (full-year/FY results) — for the Feb-Jul fiscal year

Major ASX names with off-cycle quarterly reports (CSL, CBA, BHP, RIO, NAB) report quarterly. The ASX earnings calendar is denser in Feb and Aug than other months — keep this in mind when interpreting "what's moving in Australia?" briefs.

## Steps

1. **Pull universes.** Six parallel screener calls (Pass A, Pass B up/down, Pass C up/down, Pass D up/down).

2. **Apply primary-listing exchange whitelist** — for each screener output:
   - Drop any row where `exchange` is in the drop list (OTC/PINK/LS/LSX/LSIN/CHIX, depending on whether a primary venue is present for the same name).
   - Apply dedupe logic per the priority table above.
   - For US: drop rows where `exchange` is in `('OTC', 'PINK', 'OTCBB', 'GREY')`. Real US names come back with `exchange IN ('NASDAQ', 'NYSE', 'AMEX', 'NYSEArca', 'ARCA', 'PCX', 'BATS', 'IEX')`.
   - For EU: drop rows where `exchange` is in `('LS', 'LSX', 'LSIN', 'OTC', 'PINK')`. Keep only the priority-table exchanges.
   - For AU: drop rows where `exchange` is in `('CHIX', 'OTC', 'PINK')`. Keep only `ASX`.

3. **Per-ticker extended hours (US only).** `mcp__tradingview-advanced__stock_extended_hours(symbol)` for the deduped union of Pass A + Pass B. Concurrency: serial, ~3 calls/sec. **Cap at 60 US candidates total.** Prioritization if union exceeds 60: Pass B (regular-session big movers) first, then by `|pre-market change|` desc, then market cap desc. Extract pre-market %, post-market %, regular %, previous close, currency, exchange.

4. **Per-ticker EU quote + catalyst.** `mcp__tradingview-advanced__combined_analysis(symbol, exchange, timeframe=1D)` for the deduped Pass C union. **Cap at 30 EU candidates.** Prioritization: by `|change_percent|` desc. Extract current price, change %, currency, headline news item.

5. **Per-ticker AU quote + catalyst.** `mcp__tradingview-advanced__combined_analysis(symbol, exchange='ASX', timeframe=1D)` for the deduped Pass D union. **Cap at 25 AU candidates.** Prioritization: by `|change_percent|` desc. Extract current price, change %, currency, headline news item.

6. **Tag (US):**
   - `AMC_REACTION` = |post-market %| > 3% → headline
   - `PRE_GAP` = |pre-market %| > 2% → headline
   - `QUIET` = both within ±2% → one-liner only
   - `BOD` = no pre-market data yet → deferred to next scan, surface in source health

7. **Tag (EU):**
   - `EU_REACTION` = |intraday change %| > 3% → headline
   - `EU_NOTABLE` = |intraday change %| 2.5–3% → headline (one-liner if many)
   - `EU_QUIET` = within ±2.5% → not surfaced (live session noise)

8. **Tag (AU):**
   - `ASX_REACTION` = |intraday change %| > 3% → headline
   - `ASX_NOTABLE` = |intraday change %| 2.5–3% → headline (one-liner if many)
   - `ASX_QUIET` = within ±2.5% → not surfaced (closed session, less noise than EU but still no need to dump 50 names)

9. **Catalyst lookup — US (cap 5 calls):** for each AMC_REACTION + top 3 PRE_GAP by |pre-market %|:
   - `mcp__financekit__earnings_calendar(symbol)` → if most recent earnings date within 7d, mark earnings-driven (Y); else N.
   - If Y: `mcp__stocktwits__symbol_stream(symbol, limit=15)` → top message by likes = catalyst.
   - If N: write "non-earnings move", skip symbol_stream.
   - If both unclear: write "no fresh catalyst found" (hard rule).

10. **Catalyst lookup — EU (cap 3 calls):** for top 3 EU_REACTION by |change %|:
    - Step 4's `combined_analysis` already returned news_headlines. Reuse that field.
    - Apply earnings-keyword test: if top headline contains "earnings", "results", "Q1/Q2/Q3/Q4", "beats", "misses", "reports", "guidance" → mark earnings-driven (Y); else N.
    - Use the headline itself as the catalyst text.
    - Source health line: `eu_earnings_detection_method=combined_analysis_keywords`.

11. **Catalyst lookup — AU (cap 2 calls):** for top 2 ASX_REACTION by |change %|:
    - Step 5's `combined_analysis` already returned news_headlines. Reuse that field.
    - Same earnings-keyword test as EU.
    - ASX-specific keywords to add: "interim", "half-year", "full-year", "dividend", "ASIC" (regulator), "iron ore", "lithium", "gold" (commodity-driven moves).
    - Source health line: `au_earnings_detection_method=combined_analysis_keywords`.

12. **Sort** by max(|pre-market|, |post-market|) for US, by |intraday %| for EU and AU. Each section sorted independently.

13. **Write markdown:**
    1. **TL;DR** (≤3 lines): how many AMC reactions, pre-market gaps, EU reactions, ASX reactions, biggest mover across all sections. Note EU/AU earnings detection limitation.
    2. **US — Headline table:** ticker, primary exchange, pre-market %, post-market %, earnings-driven (Y/N), catalyst.
    3. **US — QUIET one-liners** (cap 15 lines).
    4. **EU — Headline table:** ticker, primary exchange, intraday %, local currency, USD-equiv, earnings-driven (Y/N), catalyst.
    5. **AU — Headline table:** ticker, primary exchange (always ASX), intraday %, local currency (AUD), USD-equiv, earnings-driven (Y/N), catalyst.
    6. **Source health:** screener / extended_hours / combined_analysis / earnings / stocktwits call counts (broken out by region), missing symbols, 429s, dedup stats (pre-filter dropped X rows by region), candidates-trimmed by region, EU/AU earnings detection method, catalyst cap hit.
    7. **Audit line:** `earnings-reaction target=earnings-reactions:<date> candidates=<n> amc_reactions=<n> pre_gaps=<n> eu_reactions=<n> asx_reactions=<n> catalyst_lookups=<n>`.

## Hard rules
- Read-only. No trade ideas.
- Don't fabricate catalyst headlines — if the relevant call returns nothing, write "no fresh catalyst found" and move on.
- Always show both pre- and post-market % for US when both present.
- EU threshold (2.5%) > US pre-market threshold (2%) — live session is noisier than extended hours.
- **Always apply the primary-listing exchange whitelist before downstream calls.** Without it, the brief is dominated by retail mirrors and OTC duplicates.
- **US candidates cap: 60** (Pass A + Pass B union). **EU candidates cap: 30** (Pass C union). **AU candidates cap: 25** (Pass D union). Total ~115.
- Catalyst calls: **5 US + 3 EU + 2 AU = 10/run**.
- **Coverage gap detector** — for each screener call, if `total_count < 5` AND the market should be open (per the holiday table below), log `_warn=empty_screener_<market>` to source health. This catches the `south_korea` → 0 bug class without changing the screener params. Same logic also serves as the holiday detector — closed markets return 0 or near-0 rows.
- Do NOT scan all 500 S&P 500 names — top-200 is the upper bound.
- Do NOT expand the EU/ASX list without verifying screener coverage first.
- For EU and AU names, prefer the primary regional venue over the US ADR — see dedupe logic.
- AU market_cap floor ($500M) and close floor ($1) are lower than EU/US because ASX has fewer mega-caps and more $2-5 names that are real, liquid listings — not penny stocks. Don't tighten these without confirming ASX universe shrinks dangerously.

## Holiday / market-status detection

The cron fires every weekday at 08:00 ET. Some days are holidays in one or more regions. The cleanest signal is the screener itself — if a market is closed, `screen_stocks` returns 0 or very few rows. Use this as the holiday detector.

| Region | Closed-day signal | Common holidays |
|---|---|---|
| US | screener returns < 5 | New Year's Day, MLK Day, Presidents Day, Good Friday, Memorial Day, Juneteenth, Independence Day, Labor Day, Thanksgiving, Christmas |
| UK / EU | screener returns < 5 | UK bank holidays, Easter Monday, May Day, Spring/Autumn bank holidays, Christmas, New Year, regional saints' days |
| AU | screener returns < 5 | Australia Day (Jan 26), ANZAC Day (Apr 25), Queen's Birthday, Christmas, Boxing Day |

**Action when `total_count < 5`:** log `market_open_<region>=FALSE` in source health. Surface a one-line note in the TL;DR: "EU closed for holiday" or similar. The brief still runs but the section is marked "no data — closed".

**Don't fabricate a fallback date.** If a market is closed, the most recent data is the prior trading day's close. Use that if needed, but mark `_data_date=<prior_trading_day>` in source health.

## Cross-region dedupe

Within a single brief run, dedupe happens primarily via the priority table (within-region). Cross-region dedupe is best-effort and uses these heuristics:

1. **A single screener call returns exchange-specific tickers.** EU Pass C queries `markets=['uk','germany',...]` and returns AMS:ASML, LSE:0ADF, etc. — no NASDAQ rows. US Pass A returns only US exchanges.
2. **Same company across regions.** A company dual-listed on AMS + NASDAQ (e.g., ASML) would appear in EU Pass C as `AMS:ASML` AND in US Pass A as `NASDAQ:ASML`. The current implementation does NOT dedupe these — they appear in separate sections.
3. **Workaround for v3.2:** sort by `market_cap` desc; the regional primary (AMS) is listed first and the US ADR (NASDAQ) appears later in a different section. Visually obvious but not deduped.
4. **Plan for v4:** add a name-match dedupe step that strips US ADR rows when the regional primary appears in any pass. Use yahoo-finance `get_company_info` to resolve primary ISIN, then dedupe by ISIN across passes.

For now, document the cross-region case in source health: `cross_region_dupes_known=2` (count of companies appearing in multiple sections).

## Out of scope
- Options flow on earnings names → `unusual-options-flow-daily`.
- Earnings reminder (same-day BMO/AMC calendar) → `earnings-reminder`.
- Detailed earnings analysis (EPS surprise, guidance diff) → out of scope.
- Asia (JP/TW/HK) coverage → different cron slot needed (their session close is before US pre-open, so we'd need a 23:00 ET slot). Tracked for v4.
- Canada (TSX) → trivial to add via `markets=['canada']` as Pass E; pending user confirmation.
- New Zealand (NZX) → can pair with ASX as a Pacific-region pass; pending.
- Structured EU/AU earnings calendar — TradingView's `earnings_release_next_date` screener field is a known untested path; documented above.

## Change history
- **v3.3 — 2026-09-23.** Added **coverage gap detector** — `total_count < 5` triggers `_warn=empty_screener_<market>`. Catches the `south_korea` → 0 bug class. Also serves as holiday detector. Added **Holiday / market-status detection** section documenting common holidays per region (US, UK/EU, AU) with the screener-as-signal pattern. Documented **cross-region dedupe** limitation (companies like ASML on AMS + NASDAQ appear in separate sections; v4 plan to dedupe via ISIN from yahoo-finance `get_company_info`).
- **v3.2 — 2026-09-23.** Added Pass D (Australia/ASX). 1 market (australia), threshold 2.5%, market_cap floor $500M (lower than EU/US because ASX has fewer mega-caps), close floor $1 (lower because ASX has many $2-5 real listings). ASX exchange added to priority table at #19. Catalyst budget 2 calls for AU (cap by |change %|). Earnings cycle note for ASX (Feb interim + Aug full-year reporting seasons). Out-of-scope: TSX (Pass E candidate) and NZX.
- **v3.1 — same day.** Added mandatory **primary-listing exchange whitelist** (step 2). Drops OTC/PINK/LS/LSX/LSIN retail mirrors and FWB/SWB/GETTEX secondary German venues when XETR is also present. Dedupe rule: European primary beats US ADR. Documents EU earnings calendar gap.
- v3 — same day. Added Pass C (EU/UK intraday movers). 15 markets. Used `combined_analysis` for EU catalyst. Did NOT have the primary-listing filter — output was dominated by retail mirrors.
- v2 — same day. Broadened US universe from watchlist(12) + hardcoded mega-cap(13) to S&P 500 top-200 + prior-session full-universe screener. Added stocktwits catalyst lookup for US earnings-driven headlines. Old watchlist-only Pass A and hardcoded 13-name Pass B both retired.
- v1 — original design: watchlist cross-referenced against earnings_calendar + hardcoded 13-name mega-cap list. Missed non-watchlist S&P 500 earnings reactions entirely.
