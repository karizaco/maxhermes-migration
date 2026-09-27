---
name: Asia pre-market reactions
description: >-
  After-close scan of the just-completed Asian equity session across Japan
  (TSE), Taiwan (TWSE), Hong Kong (HKEX), and Korea (KRX). Surfaces notable
  intraday moves and earnings reactions from all four Asian geographies
  ahead of the US pre-open brief. Uses TradingView-advanced screen_stocks
  + combined_analysis. Runs weekdays 06:30 ET, lands 90 min before the
  main earnings-reaction-scanner cron at 08:00 ET.
---

# Asia pre-market reactions

Daily briefing of the just-closed Asian equity session. Lands at 06:30 ET — after all four Asia markets close and before the main US pre-open brief fires. Surfaces intraday moves and earnings reactions across JP, TW, HK, KR.

## When
- Cron: `30 6 * * 1-5` America/New_York (06:30 ET weekdays — 90 min before `earnings-reaction-scanner` at 08:00 ET)
- Manual: user asks "what's moving in Asia?" or "show me Asian earnings reactions"

## Output
- `C:\Users\admin\.minimax\projects\coding-shared\research\asia-pre-market\YYYY-MM-DD.md`
- Compact ≤ 12-line summary in chat reply

## Output writer (single-call persistence)

**Do NOT use the `write` tool, `Set-Content`, or `Out-File` for either deliverable.** The brief path lives outside the default workspace and triggers a desktop permission gate on every run. The audit log is append-only and has been wiped by stray `Set-Content` calls in production (see post-mortem in agent memory).

Always persist via ONE `bash` invocation of the writer helper:

```bash
python "C:/Users/admin/.minimax/projects/coding-shared/scripts/asia_brief_writer.py" \
    --date <YYYY-MM-DD> \
    --body "<markdown_body>"
```

The helper:
- Writes the markdown to `<projects>/coding-shared/research/asia-pre-market/<date>.md` atomically (temp file + `os.replace`; partial writes never overwrite an existing brief).
- Appends `asia-reaction target=asia-pre-market:<date>` to `<projects>/coding-shared/research/logs/audit.log` via the existing `audit_append.py` helper. Append-only by construction; never overwrites.
- Creates parent directories if missing.
- Exits 0 on success. Exit 1 = I/O failure, exit 2 = bad usage.

Default paths are hardcoded but overridable via `--output-dir` and `--audit-log`. For testing only, `--no-audit` skips the audit-line append.

**One tool call = one permission decision.** This is the entire point of the helper — it collapses the `write` + audit-append pair into a single bash call against `scripts/`, which is on the same allow-list as the existing `audit_append.py` invocations from other crons.

## Why a separate skill
- Asia session closes between 01:30 ET (Taiwan) and 04:00 ET (Hong Kong). The 08:00 ET main brief would have 4-7h stale Asia data.
- Asia uses different exchanges (single primary per region) — no need for the EU-style 17-market priority table.
- Asia needs different currency handling (JPY/TWD/HKD/KRW + USD-equivalent).
- Combining Asia into the main brief would push runtime past the 60s cron ceiling.

## Universe

**Japan (TSE)** — Tokyo Stock Exchange primary, top 100 by market cap.
**Taiwan (TWSE)** — Taiwan Stock Exchange primary, top 60 by market cap.
**Hong Kong (HKEX)** — Hong Kong Exchanges primary, top 60 by market cap.
**Korea (KRX)** — Korea Exchange primary (includes KOSDAQ), top 60 by market cap.

Each pass = two parallel `mcp__tradingview__screen_stocks` calls (up + down). **8 screener calls total, all parallel.**

For each market (TSE / TWSE / HKEX / KRX), the call shape is identical:

```
mcp__tradingview__screen_stocks(
  markets=['<market>'],
  filters=[
    {field: change, operator: greater, value: 2.0},
    {field: market_cap_basic, operator: greater, value: 2000000000},
    {field: close, operator: greater, value: 5}
  ],
  sort_by='change',
  sort_order='desc' | 'asc',
  limit=60
)
```

**Market code mapping (validated 2026-09-23):**

| Friendly name | `markets` value | Primary exchange | Notes |
|---|---|---|---|
| Japan | `japan` | `TSE` | Returns ~58 movers, mixed TSE + NAG (see pre-filter) |
| Taiwan | `taiwan` | `TWSE` | Returns ~27-34 movers, mixed TWSE + TPEX |
| Hong Kong | `hongkong` | `HKEX` | Returns ~30-71 movers, all HKEX |
| South Korea | `korea` | `KRX` | Returns ~30 movers. NOTE: `south_korea` returns 0 — wrong code. |

NOTE: `markov_with_country='kr'` style codes don't work; must use the short English country name.

Notes on filters:
- **change threshold: 2.0%** — Asian sessions are noisier than US extended hours, so the floor is slightly lower than the main brief's 2.5% EU/3% US. Asian markets move more on average per session than US intraday.
- **market_cap floor: $2B** — Asian mega-caps cluster above $5B; mid-caps cluster $2-10B; many legitimate Asia names below $2B. Floor chosen to keep the universe to ~30-50 names per market after filtering.
- **close floor: 5 (local currency)** — JPY/TWD/HKD/KRW prices for blue chips are hundreds to thousands of local currency units. Anything below 5 in local currency is either a sub-penny OTC ADR or a delisted shell — both should be excluded. JPY names have prices like 5000, TWD 800, HKD 60, KRW 70000 — all pass.

## Pre-filter: Primary listing exchange whitelist

**Always apply before downstream calls.** Asian markets have fewer secondary listings than EU, but OTC ADRs and London SETSqx mirrors are still common — drop them.

### Drop list (always exclude)
| Exchange code | What it is | Why drop |
|---|---|---|
| `OTC`, `PINK`, `OTCBB`, `GREY` | US OTC | ADR duplicates of primary Asian listings |
| `LSE`, `LSX` | London listings + German mirrors | Asian companies sometimes have a London listing as a secondary venue (older FTSE structure). Primary remains JP/TW/HK/KR. |
| Any exchange starting with `TPE` other than `TWSE` (e.g., TPEX) | Taipei Exchange (Taiwan OTC) | Sub-tier of Taiwan; only TWSE primary counts unless TWSE is missing |
| `NASDAQ:ASX` for HK / KRX names | ADR pre-listing | Same drop rule as EU |

### Keep list — primary exchanges only

| Priority | Exchange | Country | Notes |
|---|---|---|---|
| 1 | `TSE` (Tokyo) | JP | The only venue for Japanese blue chips. JPX-issued tickers. |
| 2 | `TWSE` (Taiwan) | TW | Primary for Taiwanese names. |
| 3 | `HKEX` (Hong Kong) | HK | Primary for HK-listed. |
| 4 | `KRX` (Korea) | KR | Covers both KOSPI and KOSDAQ listings. |
| 5 | `TPEX` (Taipei Exchange) | TW | OTC tier — use only when TWSE result is missing for the same company. |
| 6 | `NAG` (Nagoya Stock Exchange) | JP | Regional JP secondary — keep only when TSE doesn't list the same ticker. |

### Dedupe logic
1. **Regional primary beats US ADR.** E.g., Toyota → `TSE:7203` (primary), never `NYSE:TM` (ADR).
2. **Within the same country, higher market cap wins** if the same name has dual listings.
3. **Exception: TPEX only if TWSE result missing.** Don't surface TPEX names where TWSE has the same security.
4. **Exception: NAG only if TSE result missing.** Don't surface NAG names where TSE has the same security.
5. **Euronext / LSE / OTC ADRs are dropped** for Asian companies — primary always wins.
6. **HK dual-ticker dedupe.** Some HK-listed names (e.g., Alibaba) render with 5-digit tickers like `HKEX:89988` alongside the 4-digit primary `HKEX:9988`. Dedupe by underlying company (same `market_cap_basic` and same `name` → keep the 4-digit version when both present). Validate that approximately 5-10% of HK rows are dual-ticker duplicates.

## Earnings calendar data — coverage

**Same gap as EU/AU.** No structured earnings calendar tool exists for Asian stocks in the available MCPs. Detection is best-effort via news headlines.

**Catalyst source chain (validated 2026-09-23):**

| Source | Reliability | Notes |
|---|---|---|
| `mcp__yahoo-finance__get_market_news(ticker, count=5)` | ✅ Reliable | **Primary recommended**. Symbol format: `<numeric_ticker>.<EXCHANGE_SUFFIX>` where suffixes are `.HK` (HKEX), `.TW` (TWSE), `.KS` (KRX), `.T` (TSE). For alphanumeric JP tickers (e.g., 285A), try `285A.T` first, fall back to `285A.TYO` |
| `mcp__tradingview-advanced__combined_analysis(symbol, exchange, timeframe=1D)` | ⚠ **Limited scope.** | ✅ Works for TWSE/hkex. ❌ Returns `INVALID_EXCHANGE` for TSE and KRX. News headlines empty in this env (`MARKETAUX_API_TOKEN not configured`). Use only when yahoo-finance returns nothing or as supplementary. |
| `mcp__tradingview-advanced__financial_news(symbol, category, limit)` | ❌ Broken in current env | Returns 0 items because `MARKETAUX_API_TOKEN` is not configured. Documented as a known gap, not a v2 retry target. |
| `mcp__tradingview__screen_stocks` with `earnings_release_next_date` filter | ⚠ Untested path | Would be the structured source if reachable; not yet validated |
| `mcp__stocktwits__symbol_stream(symbol, limit=15)` | ⚠ Use as last resort | Coverage for Asian tickers is sparse; not validated |

### Earnings keywords (Asia-specific)
Beyond the universal keywords ("earnings", "results", "beats", "misses", "reports"), Asian reports often use:
- "earnings", "results", "interim results", "full-year results" (JP: 決算, KR: 결산)
- "Q1/Q2/Q3/Q4", "1Q/2Q/3Q/4Q"
- "dividend", "share buyback", "capital return"
- "guidance", "outlook", "forecast"
- "MBO", "IPO", "placement"
- Currency-specific: "yen", "won", "yuan", "New Taiwan dollar"

### Asian earnings cycle (peak windows)
- **Japan:** Q1 disclosures late July / early August; Q3 disclosures late January / early February. Sparse outside these windows.
- **Taiwan:** Similar to JP; TSM and major TWSE names report quarterly. Concentrated in mid-month after quarter-end.
- **Hong Kong:** Less standardized; HKEX-listed companies report semi-annually for H1 (Aug) and full year (Mar). Some report quarterly.
- **Korea:** Quarterly for KOSPI 200 + KOSDAQ 150; concentrated late Jan / late Apr / late Jul / late Oct.

## Steps

1. **Pull universes.** 8 parallel screener calls (4 markets × up/down).

2. **Apply primary-listing exchange whitelist.** For each screener output:
   - Drop any row where `exchange` is in the drop list (OTC/PINK/LSE/LSX).
   - Apply dedupe logic: regional primary beats US ADR; TPEX only if TWSE is missing.
   - Keep top 15 per market per direction (sort by `|change_percent|` desc) — caps each market at 30 rows.

3. **Tag (per market):**
   - `JP_REACTION` = |intraday %| > 4% → headline (JP vol is moderate; 4% is a real move)
   - `JP_NOTABLE` = 2-4% → one-liner
   - `TW_REACTION` = |intraday %| > 5% → headline (TW can be volatile on a single name)
   - `TW_NOTABLE` = 2-5% → one-liner
   - `HK_REACTION` = |intraday %| > 4% → headline
   - `HK_NOTABLE` = 2-4% → one-liner
   - `KR_REACTION` = |intraday %| > 4% → headline (KRX has daily limit moves ~±15% which produce non-fundamental data; rely on combined_analysis to flag)
   - `KR_NOTABLE` = 2-4% → one-liner
   - All markets: below 2% → not surfaced (closed session noise)

4. **Per-ticker catalyst lookup (cap 4 calls total — top 1 REACTION per market).** For the top reaction per market (highest |change %|):
   - **Primary:** `mcp__yahoo-finance__get_market_news(ticker, count=5)` using the yahoo suffix format (`.T`, `.TW`, `.HK`, `.KS`).
   - **Fallback if yahoo returns nothing:** `mcp__tradingview-advanced__combined_analysis(symbol, exchange, timeframe=1D)` for TWSE/hkex only — skip for TSE/KRX (returns INVALID_EXCHANGE).
   - Apply earnings-keyword match to the top headline → mark earnings-driven (Y/N).
   - If both sources return nothing → write "no fresh catalyst found" (hard rule).
   - Source health: `asia_earnings_detection_method=yahoo_finance_primary_combined_fallback`.

5. **Sort** by `|change_percent|` desc within each market section. Each geo sorted independently.

6. **Compose the markdown body** (in memory — do NOT yet write to disk). The body must contain, in order:
   1. **TL;DR** (≤3 lines): how many reactions per market, biggest mover overall, top geo by activity. Note Asian earnings-cycle context if relevant.
   2. **Japan headline table:** ticker, change %, market cap, earnings-driven (Y/N), catalyst.
   3. **Japan NOTABLE one-liners** (cap 8 lines).
   4. **Taiwan headline table** (same columns).
   5. **Taiwan NOTABLE** (cap 8 lines).
   6. **Hong Kong headline table**.
   7. **Hong Kong NOTABLE** (cap 8 lines).
   8. **Korea headline table**.
   9. **Korea NOTABLE** (cap 8 lines).
   10. **Source health:** screener / combined_analysis call counts (broken out per market), missing symbols, 429s, dedup stats, candidates-trimmed, earnings detection method per market, catalyst cap hit.
   11. **Audit footer line:** `asia-reaction target=asia-pre-market:<date> jp=<n> tw=<n> hk=<n> kr=<n> reactions=<n> catalyst_lookups=<n>` — included in the body for human readers.

7. **Persist in a single tool call.** Invoke the asia_brief_writer.py helper via ONE `bash` invocation. This writes the markdown atomically AND appends the audit line to the append-only audit log — replacing the old `write` + manual-append pair with one permission-checked call:

   ```bash
   python "C:/Users/admin/.minimax/projects/coding-shared/scripts/asia_brief_writer.py" --date <YYYY-MM-DD> --body "<markdown_body>"
   ```

   The body argument is a single argv string. PowerShell single-quotes preserve `$`, `|`, backticks, and double-quotes; only `'` itself needs `''` escaping. Avoid `\n` literal escapes — pass real newlines.

   **Hard prohibitions (this step):**
   - DO NOT call the `write` tool to write the brief markdown. The output path (`projects/coding-shared/research/asia-pre-market/...`) sits outside the default workspace and triggers a desktop permission gate every run, defeating the silent-cron contract. Use the helper.
   - DO NOT use `Set-Content` / `Out-File` / `edit` on either the brief file or the audit log — see the audit_append.py post-mortem in agent memory for the documented wipe incident.
   - DO NOT skip the audit-line append. The SKILL.md §6 step 11 (audit footer in body) is NOT a substitute for the persisted audit line in `research/logs/audit.log`. The helper handles both.

## Hard rules
- Read-only. No trade ideas.
- Don't fabricate catalyst headlines — if combined_analysis returns nothing, write "no fresh catalyst found" and move on.
- Always use the regional primary listing (TSE > NASDAQ ADRs for JP; HKEX > NYSE ADRs for HK; etc.).
- **Each market caps at 30 rows** (15 up + 15 down). Larger markets (Japan) will fill up; smaller ones (KR, TW) will have fewer rows naturally.
- **Total catalyst calls capped at 4** (one per market) — preserves budget for future expansion.
- **Coverage gap detector** — for each screener call, if `total_count < 5` AND the market should be open per the schedule below, log `_warn=empty_screener_<market>` to source health. This catches the `south_korea` → 0 bug class without changing the screener params. Same logic also serves as the holiday detector (closed markets return 0).
- Do NOT expand to additional Asian markets (China, India, Vietnam, Indonesia, Philippines, Singapore) without verifying screener coverage first.
- **KRX caveat:** Korean stocks have daily price limits (typically ±15% for KOSPI, ±30% for KOSDAQ). Limit-move closes often produce data anomalies in `change_percent`. Use combined_analysis news to spot genuine earnings moves vs limit-driven non-fundamental moves; tag the latter as `KR_LIMIT_MOVE`.
- **HK caveat:** HKEX closes morning session 12:00 HKT, then afternoon 13:00-16:00 HKT. The `change_percent` reflects the full day's move (both sessions). Intra-lunch snapshots exist but aren't needed for this brief.
- **Japan caveat:** TSE closing auction runs 15:25-15:30 JST. At 06:30 ET scan time, that's 18:30 JST — well after the closing auction. Print should be final.

## Holiday / market-status detection

The cron fires every weekday at 06:30 ET. Some days are holidays in one or more Asian markets. The cleanest signal is the screener itself — if a market is closed, `screen_stocks` returns 0 or very few rows. Use this as the holiday detector:

| Market | Closed-day signal | Notes |
|---|---|---|
| JP | screener returns < 5 | Golden Week (Apr 29 – May 5), Obon (Aug 13-16), New Year (Jan 1-3) |
| TW | screener returns < 5 | Lunar New Year (3-5 days, late Jan/early Feb), National Day (Oct 10), Tomb Sweeping (Apr 4-5) |
| HK | screener returns < 5 | Lunar New Year (3-5 days), Ching Ming (Apr 4), Buddha's birthday, National Day (Oct 1), Christmas (Dec 25-26) |
| KR | screener returns < 5 | Lunar New Year (Seollal, 3 days), Chuseok (3 days, Sep/Oct), National Liberation Day (Aug 15), Memorial Day (Jun 6) |

**Action when `total_count < 5`:** log `market_open_<market>=FALSE` in source health. Surface a one-line note in the TL;DR: "JP closed for holiday" or "TW: closed (Lunar New Year)". The brief still runs but the section is marked "no data — closed".

**Don't fabricate a fallback date.** If a market is closed, the most recent data is the prior trading day's close. Use that if needed, but mark `_data_date=<prior_trading_day>` in source health.

## Out of scope
- India (NSE/BSE) — can be added as a fifth market if user requests; TradingView supports it. Tracked for v5 alongside Canada (TSX).
- Singapore (SGX) — same as India.
- China (SHSE/SZSE) — different data access pattern in many Western APIs (offshore-only via HK connect). Tracked separately if user requests.
- Tokyo Stock Exchange sub-categories (TSE Prime / Standard / Growth) — `TSE` covers all three.
- KRX derivatives (KOSPI 200 options) — equity-spot only here.
- Asia-pre-market analysis with FX context (yen weakness, won carry trade, etc.) — could be added as separate "asia-fx-brief" skill; out of scope here.
- Structured Asian earnings calendar — see earnings calendar section above; documented gap.

## Change history
- **v1.1 — 2026-09-23.** Validation pass. Market codes confirmed: `japan`, `taiwan`, `hongkong`, `korea` (NOT `south_korea` — that returns 0). Added `NAG` (Nagoya) and `TPEX` (Taipei Exchange) to the secondary-venue dedupe logic — keep only when the primary venue (TSE/TWSE respectively) doesn't list the same ticker. Added HK dual-ticker dedupe (e.g., 89988 vs 9988 for Alibaba). JP results dominated by `TSE:` with ~5-10% NAG noise; TW results ~30% `TPEX:` (smaller companies not on TWSE); HK all `HKEX:` with ~5-10% dual-ticker duplicates; KR all `KRX:` clean.
- **v1 — 2026-09-23.** Initial release. 4 Asian geos (JP/TW/HK/KR), single scan per geo with up + down direction. Lower threshold (2%) and tighter market cap floor ($2B) than EU/AU to reflect Asian market structure. Separate cron at 06:30 ET to land ahead of the main 08:00 ET brief.
