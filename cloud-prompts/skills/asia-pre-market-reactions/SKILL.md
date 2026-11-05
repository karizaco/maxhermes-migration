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

# Asia pre-market reactions

Daily briefing of the just-closed Asian equity session. Lands at 06:30 ET — after all four Asia markets close and before the main US pre-open brief fires. Surfaces intraday moves and earnings reactions across JP, TW, HK, KR.

## When
- Cron: `30 6 * * 1-5` America/New_York (06:30 ET weekdays — 90 min before `earnings-reaction-scanner` at 08:00 ET)
- Manual: user asks "what's moving in Asia?" or "show me Asian earnings reactions"

## Output
- `C:\Users\admin\.minimax\projects\coding-shared\research\asia-pre-market\YYYY-MM-DD.md`
  _(In Cloud this path does not exist — it is the local Mavis host's location. In Cloud, write to the `## OUTPUT` path in the cron prompt.)_)
- The chat reply follows the fleet's standard `## DELIVERY` structure (see
  `_shared/PROMPT-BLOCKS.md`) and carries **one contiguous block per country** — see
  *Chat reply (country blocks, in order, with session dates)*. The reply is capped by NAMES SHOWN
  (top ~8 per tier), not by lines; the artifact carries the rest.

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

## Output ordering (group by country, then by move size)

**Country order is fixed: Japan, Korea, Taiwan, Hong Kong.** The brief is grouped by country in
that order — every Japan row together, then every Korea row, then Taiwan, then Hong Kong.

**Inside each country, sort every row by `|change %|` descending** — the REACTION table first, then
the NOTABLE one-liners, which together form one continuous descending stream (REACTION rows are
all larger moves than NOTABLE rows, so the concatenation is already sorted).

**Country blocks are contiguous.** Never interleave a name from another country into a block, and
never split one country across two blocks. The chat reply follows the same country order as the
artifact.

## Steps

1. **Resolve the fire date.** Use the `fire-date:` printed by the shared window check — the fire's
   scheduled date in US/Eastern, `YYYY-MM-DD`. Every date comparison below is against THIS date,
   never against `date +%F` at execution time: a delayed replay must still be judged against the
   session it was supposed to cover.

2. **Pull the universes AND the index quotes** — 8 screener calls (4 markets × up/down) plus 4
   index fetches, in parallel:

   ```bash
   # --- 8 screener calls (unchanged shape) ---
   for M in japan taiwan hongkong korea; do
     for D in desc asc; do
       curl -sS --max-time 30 -X POST "https://scanner.tradingview.com/$M/scan" \
         -H "Content-Type: application/json" -H "User-Agent: Mozilla/5.0" \
         -H "Origin: https://www.tradingview.com" -d '{
           "filter":[{"left":"type","operation":"equal","right":"stock"},
                     {"left":"country","operation":"equal","right":"<Country>"},
                     {"left":"change","operation":"greater","right":2},
                     {"left":"market_cap_basic","operation":"greater","right":<local_cap_floor>},
                     {"left":"close","operation":"greater","right":5}],
           "options":{"lang":"en"},
           "columns":["name","description","close","change","change_abs","volume",
                      "market_cap_basic","exchange","currency","sector","type",
                      "earnings_release_next_date","update_mode"],
           "sort":{"sortBy":"change","sortOrder":"desc"},
           "range":[0,600]}' -o "/workspace/_asia_${M}_${D}.json" &
     done
   done
   wait

   # --- 4 index charts: session date + level (the date-provenance source) ---
   for S in '%5EN225' '%5ETWII' '%5EHSI' '%5EKS11'; do
     curl -sL --max-time 25 -A "Mozilla/5.0" \
       "https://query1.finance.yahoo.com/v8/finance/chart/$S?range=10d&interval=1d" \
       -o "/workspace/_asia_idx_${S}.json" &
   done
   wait
   ```

   `change` is read as **percent units** (Trap 13 — never multiply by 100). `market_cap_basic` is
   **local currency** — convert the $2bn floor with FX before filtering. The `range` must cover the
   market's row count or the tail is silently cut.

   Merge the two directions into the per-country file that Test B reads:

   ```bash
   for M in japan taiwan hongkong korea; do
     python3 - "$M" <<'PY'
   import json, sys
   M = sys.argv[1]; data = []; total = 0
   for d in ("desc", "asc"):
       j = json.load(open(f"/workspace/_asia_{M}_{d}.json"))
       total = max(total, j.get("totalCount", 0)); data += j.get("data", [])
   json.dump({"totalCount": total, "data": data}, open(f"/workspace/_asia_{M}.json", "w"))
   print(M, "merged rows:", len(data), "totalCount:", total)
   PY
   done
   ```

3. **Market-status detection (Tests A / B / C) — BEFORE composing anything.** See
   *Market-status detection — DATE PROVENANCE*. A market that comes back closed gets **no
   table**, so do not spend the effort polishing its rows. Run this before step 4 so the closed
   markets are excluded from the universe work entirely.

4. **Apply primary-listing exchange whitelist.** For each screener output:
   - Drop any row where `exchange` is in the drop list (OTC/PINK/LSE/LSX).
   - Apply dedupe logic: regional primary beats US ADR; TPEX only if TWSE is missing.
   - Resolve every regional JP row (NAG/FSE) against its TSE line — a stale regional print is the
     single biggest data-integrity risk on the JP scan.
   - Drop HK rows whose `currency` is not `HKD` (the CNY counters quote off the liquid line).
   - Keep top 15 per market per direction (sort by `|change_percent|` desc) — caps each market at 30 rows.

5. **Tag (per market, in the output order Japan → Korea → Taiwan → Hong Kong):**
   - `JP_REACTION` = |intraday %| > 4% → headline (JP vol is moderate; 4% is a real move)
   - `JP_NOTABLE` = 2-4% → one-liner
   - `KR_REACTION` = |intraday %| > 4% → headline (KRX has daily limit moves ~±15% which produce non-fundamental data; rely on combined_analysis to flag)
   - `KR_NOTABLE` = 2-4% → one-liner
   - `TW_REACTION` = |intraday %| > 5% → headline (TW can be volatile on a single name)
   - `TW_NOTABLE` = 2-5% → one-liner
   - `HK_REACTION` = |intraday %| > 4% → headline
   - `HK_NOTABLE` = 2-4% → one-liner
   - All markets: below 2% → not surfaced (closed session noise)

6. **Per-ticker catalyst lookup (cap 4 calls total — top 1 REACTION per market).** For the top reaction per market (highest |change %|):
   - **Primary:** `mcp__yahoo-finance__get_market_news(ticker, count=5)` using the yahoo suffix format (`.T`, `.TW`, `.HK`, `.KS`).
   - **Fallback if yahoo returns nothing:** `mcp__tradingview-advanced__combined_analysis(symbol, exchange, timeframe=1D)` for TWSE/hkex only — skip for TSE/KRX (returns INVALID_EXCHANGE).
   - Apply earnings-keyword match to the top headline → mark earnings-driven (Y/N).
   - If both sources return nothing → write "no fresh catalyst found" (hard rule).
   - Source health: `asia_earnings_detection_method=yahoo_finance_primary_combined_fallback`.

   **In the Cloud runtime the `mcp__*` names do not exist** — take catalysts from the primary press
   named in the runtime source ladder (as the 2026-11-03 and 2026-11-04 runs did) and record
   `asia_earnings_detection_method=press_catalyst_lookup`. Never invent a catalyst: an explicit
   "no company-specific catalyst identified in the sources checked" is a valid, publishable cell.

7. **US read-across.** See *US read-across (the "what does this mean at 09:30 ET" paragraph)*. One
   america-scan call returns the whole US-listed ADR universe; match the day's Asian movers
   against it and build the three bullets. This is what turns "what happened in Asia" into "what
   does this mean for me at the US open".

8. **Sort** by `|change_percent|` desc within each market section. Each geo sorted independently,
   and the market sections appear in the fixed country order Japan → Korea → Taiwan → Hong Kong
   (see *Output ordering*).

9. **Compose the markdown body** (in memory — do NOT yet write to disk). The body uses this fixed
   skeleton, in this order. No extra top-level sections, and no missing ones: a section that does
   not apply becomes a "no data — closed" block, never a dropped heading.

   ```markdown
   ---
   date: <YYYY-MM-DD>
   cron: 02-asia-pre-market-reactions
   fire_time_et: 06:30
   status: ok | ok_degraded_<market> | late_replay
   primary_source: TradingView per-country scanner (movers, closes, local-currency caps)
   market_open_jp: TRUE|FALSE|UNKNOWN
   market_session_date_jp: <YYYY-MM-DD>
   market_open_tw: TRUE|FALSE|UNKNOWN
   market_session_date_tw: <YYYY-MM-DD>
   market_open_hk: TRUE|FALSE|UNKNOWN
   market_session_date_hk: <YYYY-MM-DD>
   market_open_kr: TRUE|FALSE|UNKNOWN
   market_session_date_kr: <YYYY-MM-DD>
   ---

   # Asia pre-market reactions — <Weekday, DD Month YYYY>

   ## TL;DR
   - exactly 3 bullets: (1) what Asia did, (2) the one most consequential market, (3) the caveat
     that changes how to read it.
   - plus the US read-across block: one short paragraph and at most 3 bullets.

   ## Market backdrop
   | Market | Index | Close | Chg | Session date | Source |

   ## Japan (JP) — session <YYYY-MM-DD>
   ### REACTION tier
   ### NOTABLE one-liners (2-4%)

   ## Korea (KR) — session <YYYY-MM-DD>
   ### REACTION tier
   ### NOTABLE one-liners (2-4%)

   ## Taiwan (TW) — session <YYYY-MM-DD>
   ### REACTION tier
   ### NOTABLE one-liners (2-5%)

   ## Hong Kong (HK) — session <YYYY-MM-DD>
   ### REACTION tier
   ### NOTABLE one-liners (2-4%)

   ## Flags
   ## Method, source health & caveats
   ```

   - The title's weekday comes from the **fire date**, not the wall clock:
     `Wednesday, 05 November 2026`.
   - `## TL;DR` carries **exactly 3 bullets** plus the read-across block. A fourth bullet is a
     defect, not a style choice.
   - `## Market backdrop` carries each market's index level **with that market's session date** —
     the reader must be able to see in one table that a market is stale.
   - A country whose market is closed replaces its whole section with the "no data — closed"
     block; that country's `###` tiers are then absent.
   - `## Flags` is the "numbers a human should distrust" section — thin prints, limit moves,
     source conflicts, unverified catalysts, stale or closed markets, prior-session rows.
   - `## Method, source health & caveats` = the method note + the source-health table (per source:
     URL/query, HTTP status, `ok` / `failed:<reason>`) + the caveats + the audit footer line
     `asia-reaction target=asia-pre-market:<date> jp=<n> tw=<n> hk=<n> kr=<n> reactions=<n> catalyst_lookups=<n>`.

10. **Run the pre-publish assertions.** Park the composed body in a scratch file
    (`/workspace/_asia_body.md` — NOT the deliverable), then run the assertions in
    *Pre-publish assertions* against it. A failed assertion is fixed in the body, not
    explained away in prose. Only a passing body is written to the deliverable path.

11. **Persist in a single tool call.** Invoke the asia_brief_writer.py helper via ONE `bash` invocation. This writes the markdown atomically AND appends the audit line to the append-only audit log — replacing the old `write` + manual-append pair with one permission-checked call:

    ```bash
    python "C:/Users/admin/.minimax/projects/coding-shared/scripts/asia_brief_writer.py" --date <YYYY-MM-DD> --body "<markdown_body>"
    ```

    The body argument is a single argv string. PowerShell single-quotes preserve `$`, `|`, backticks, and double-quotes; only `'` itself needs `''` escaping. Avoid `\n` literal escapes — pass real newlines.

    **In the Cloud runtime there is no local writer helper and no audit log** — write the file with
    the `write` tool to the `## OUTPUT` path in the cron prompt
    (`/workspace/asia-pre-market/<date>.md`) and let the prompt's push block ship it. The audit
    footer line travels INSIDE the artifact body.

    **Hard prohibitions (this step):**
    - DO NOT call the `write` tool to write the brief markdown on the LOCAL host — the output path (`projects/coding-shared/research/asia-pre-market/...`) sits outside the default workspace and triggers a desktop permission gate every run, defeating the silent-cron contract. Use the helper there.
    - DO NOT use `Set-Content` / `Out-File` / `edit` on either the brief file or the audit log — see the audit_append.py post-mortem in agent memory for the documented wipe incident.
    - DO NOT skip the audit-line append on the local host. The SKILL.md §6 step 11 (audit footer in body) is NOT a substitute for the persisted audit line in `research/logs/audit.log`. The helper handles both.

12. **Push, then reply.** Ship the artifact with the prompt's push block, verify the delivery
    (`verify_delivery.sh --path asia-pre-market/<date>.md`), and only then write the chat reply.
    The reply follows the fleet's `## DELIVERY` structure and the country-block rules in
    *Chat reply (country blocks, in order, with session dates)* — run the reply-order assertion
    before sending.

## US read-across (the "what does this mean at 09:30 ET" paragraph)

The brief answers "what happened in Asia". A US trader also needs "what does this do to me at the
open?" — put that in the TL;DR as a **US read-across block: one short paragraph and at most three
bullets**.

**Method — one call, then local matching:**

```bash
curl -sS --max-time 40 -X POST "https://scanner.tradingview.com/america/scan" \
  -H "Content-Type: application/json" -H "User-Agent: Mozilla/5.0" \
  -H "Origin: https://www.tradingview.com" \
  -d '{"filter":[{"left":"type","operation":"equal","right":"dr"}],
       "options":{"lang":"en"},
       "columns":["name","description","close","change","market_cap_basic","sector",
                  "exchange","premarket_change","premarket_volume"],
       "range":[0,1700],"sort":{"sortBy":"market_cap_basic","sortOrder":"desc"}}' \
  -o /workspace/_asia_adr.json
```

1,611 US-listed ADRs come back in one call (`type=dr`; `totalCount` 1611 — set `range` to cover it
or the tail is silently cut). `description` is the **underlying company's own name**, so it is the
join key: match it against the day's Asian movers, normalising case and dropping corporate
suffixes (`Ltd`, `Co`, `Corporation`, `Inc`, `Holdings`) before comparing.

**What to publish — three bullets maximum:**

1. **Exposed US names / ADRs.** The US-listed line for each of the day's most consequential Asian
   movers: US ticker, US sector, and the US pre-market move. Quote a pre-market % only when
   `premarket_volume` is material (≥ 50,000 shares); below that write "no material US pre-market
   print yet" — a thin 06:30 ET pre-market quote is a print, not a market.
2. **Exposed US sectors.** The US sectors that carry the exposure (an Asian chip rout maps to
   Electronic Technology / Semiconductor; an oil rout to Energy Minerals), with the names.
3. **The overnight implication.** One line: what the US pre-market has already priced, what it
   has NOT (an Asian session's move with no US ADR behind it), and which US session carries the risk.

**Rules.** The read-across is a mapping, not a forecast — the hard rule "read-only, no trade ideas"
still applies; no price targets. A US name with neither an ADR nor a direct peer is **not** a US
exposure: write "no direct US-listed proxy" instead of stretching the link. Two real names beat
three invented ones.

## Chat reply (country blocks, in order, with session dates)

The chat reply uses the fleet's standard `## DELIVERY` structure (see
`_shared/PROMPT-BLOCKS.md`). Inside it, `### Signal` carries **one block per country, contiguous,
in the fixed order Japan → Korea → Taiwan → Hong Kong** — the same order as the artifact.

**Each country's block heading carries that market's session date**, because with a market closed
the reader cannot otherwise tell which numbers are today's:

```markdown
### Japan (JP) — session 2026-11-05
- TSE:6370 +15.06% — Kurita Water; no sourced catalyst, prints Q2 on 5 Nov.

### Korea (KR) — session 2026-11-05
- KRX:028300 -17.69% — HLB; FDA Class 2 review, not the Class 1 the market expected.

### Taiwan (TW) — no data — closed
- TW market closed; last session 2026-11-04.

### Hong Kong (HK) — session 2026-11-05
- HKEX:3330 +17.04% — Lingbao Gold; spot gold broke above US$4,000/oz.
```

- **Never interleave a name from another country into a block, and never split one country across
  two blocks.** The 2026-11-03 reply interleaved (KRX, HKEX, KRX, TWSE, TWSE…) — that is the
  defect this section exists to prevent.
- Inside a block, sort by `|change %|` descending — the same order as the artifact.
- A closed market gets a one-line block: `### <Country> (<CC>) — no data — closed` plus the last
  session date. It never gets a movers list.
- The reply shows fewer names than the artifact (top movers per tier); the artifact carries the
  rest. Say how many further names are in the file.
- **Assert the order before sending** — see *Pre-publish assertions*.

## Pre-publish assertions (run them; do not eyeball)

These are cheap and they catch the failure classes this routine has actually hit. Run them on the
artifact body BEFORE writing it, and on the reply body BEFORE sending it. A failed assertion is
fixed in the body, not explained away in prose.

```bash
# step 10a: park the composed body in a SCRATCH file (not the deliverable) so the
# assertions below have something to read. The deliverable is written after they pass.
python3 - /workspace/_asia_body.md <<'PY'
import re, sys

body = open(sys.argv[1], encoding="utf-8").read()
TICKER = re.compile(r"\b(?:TSE|TWSE|TPEX|HKEX|KRX|NAG|FSE):[0-9A-Z]+")

# 1. every PUBLISHED name appears EXACTLY once.
#    Scope = the four country sections (tables + NOTABLE one-liners). Prose
#    cross-references in Flags / Method / source health are NOT rows.
COUNTRY = re.compile(r"^## (?:Japan|Korea|Taiwan|Hong Kong)[^\n]*$", re.M)
published = []
for m in COUNTRY.finditer(body):
    nxt = re.search(r"^## ", body[m.end():], re.M)
    end = m.end() + (nxt.start() if nxt else len(body) - m.end())
    published.append(body[m.start():end])
names = TICKER.findall("\n".join(published))
dupes = sorted({n for n in names if names.count(n) > 1})
print("published name occurrences:", len(names), "| distinct:", len(set(names)),
      "| duplicates:", dupes or "none")
assert not dupes, "DUPLICATE NAMES: %s" % dupes

# 2. a market judged closed publishes no prices and no table
for m, cc in (("jp", "JP"), ("tw", "TW"), ("hk", "HK"), ("kr", "KR")):
    flag = re.search(r"^market_open_%s:\s*(TRUE|FALSE|UNKNOWN)\b.*$" % m, body, re.M)
    if flag and flag.group(1) == "FALSE":
        head = re.search(r"^## [^\n]*\((?:%s|JP|TSE|TW|TWSE|HK|HKEX|KR|KRX)\)[^\n]*$" % cc, body, re.M)
        assert head, "no section found for closed market %s" % cc
        assert "no data — closed" in head.group(0), \
            "%s is closed but its heading is not 'no data — closed'" % cc
        nxt = re.search(r"^## ", body[head.end():], re.M)
        blk = body[head.end():head.end() + (nxt.start() if nxt else len(body))]
        tbl = [l for l in blk.splitlines() if l.startswith("|")]
        assert not tbl, "%s is closed but its section still has a table" % cc
        print("closed market %s: section clean (no table)" % cc)

# 3. every published row carries a catalyst cell
empty = []
for ln in body.splitlines():
    if not ln.startswith("|"):
        continue
    if re.fullmatch(r"\|[\s\-:|]+\|?", ln.strip()):     # table separator
        continue
    cells = [c.strip() for c in ln.strip().strip("|").split("|")]
    if len(cells) < 7:                                       # not a data table
        continue
    if not re.search(r"[A-Za-z]{3}", cells[-1]):
        empty.append(cells[0])
assert not empty, "EMPTY CATALYST CELL on: %s" % empty[:5]

print("ASSERTIONS OK")
PY
```

- **1 — Name uniqueness.** `count(names in the published rows) == count(distinct names)`. The
  count is scoped to the **four country sections** (tables + NOTABLE one-liners): a name that
  appears in two countries' blocks, or twice in one, is a copy-paste error and a wrong row count.
  Prose cross-references are NOT rows — `## Flags` re-mentions a flagged name on purpose, and the
  source-health narrative contrasts a stale regional print with its real line (e.g.
  `FSE:7011` vs `TSE:7011`). Those are narrative, so they sit outside the count. A "beyond the
  pool cap" note inside a country section DOES count — if it re-lists a name already in that
  country's table, that is a duplicate row and the assertion will fail it.
- **2 — Closed markets publish no prices.** For every `market_open_<m>=FALSE` in the front-matter,
  the matching section must say "no data — closed" and must contain **no price column and no
  mover rows**. The 2026-11-03 artifact failed exactly this, and the failure was invisible to a
  row-count check.
- **3 — Every row carries a catalyst** — a sourced one, or the explicit "no company-specific
  catalyst identified in the sources checked" (or "not separately sourced (catalyst cap)"). An
  empty catalyst cell is a defect, and so is a bare `—` in the CATALYST column: `—` is acceptable
  only in the earnings-driven column, where it means "not determined".
- **4 — Reply country order.** The reply is checked with the same discipline as the artifact, and
  it is checked **separately from the artifact** — the artifact can be right while the reply
  interleaves countries (that is exactly what happened on 2026-11-03). Park the reply body in a
  scratch file and run:

  ```bash
  python3 - /workspace/_asia_reply.md <<'PY'
  import re, sys
  reply = open(sys.argv[1], encoding="utf-8").read()
  ORDER = ["Japan", "Korea", "Taiwan", "Hong Kong"]
  heads = re.findall(r"^###\s+(Japan|Korea|Taiwan|Hong Kong)\b([^\n]*)$", reply, re.M)
  seq = [h[0] for h in heads]
  assert seq, "no country blocks found in the reply"
  assert len(seq) == len(set(seq)), "a country block appears twice: %s" % seq
  idx = [ORDER.index(c) for c in seq]
  assert idx == sorted(idx), "country blocks are out of order: %s" % seq
  for country, tail in heads:
      assert re.search(r"(session \d{4}-\d{2}-\d{2}|no data — closed)", tail), \
          "%s block carries no session date: %s" % (country, tail.strip())
  print("reply order OK:", " -> ".join(seq))
  PY
  ```

  A reply may legitimately omit a country whose market was closed and had nothing to say — but if
  the country IS mentioned, its block must be in the fixed order and carry a session date. Never
  interleave a name from another country into a block, and never split one country across two
  blocks.
- **5 — Session dates are consistent.** Every market block (artifact and reply) states its session
  date, and the `## Market backdrop` session dates match the detector's verdicts and the
  `market_session_date_<m>` front-matter keys.

## Hard rules
- Read-only. No trade ideas.
- Don't fabricate catalyst headlines — if combined_analysis returns nothing, write "no fresh catalyst found" and move on.
- **Never publish a prior session's prices for a market that did not trade.** A market judged closed gets a "no data — closed" section — never a table, never a price, never a movers list, even when it is labelled as context.
- **Every name appears exactly once in the artifact.** Assert it (`count(names) == count(distinct names)`); a name in two country blocks is a copy-paste error.
- **Every published row carries a catalyst** — a sourced one, or the explicit "no company-specific catalyst identified in the sources checked". An empty catalyst cell is a defect.
- **The chat reply's country blocks are contiguous** and in the order Japan, Korea, Taiwan, Hong Kong, each with its session date. Never interleave countries.
- Always use the regional primary listing (TSE > NASDAQ ADRs for JP; HKEX > NYSE ADRs for HK; etc.).
- **Each market caps at 30 rows** (15 up + 15 down). Larger markets (Japan) will fill up; smaller ones (KR, TW) will have fewer rows naturally.
- **Total catalyst calls capped at 4** (one per market) — preserves budget for future expansion.
- **Coverage gap detector (SECONDARY)** — for each screener call, if `total_count < 5` AND the market should be open, log `_warn=empty_screener_<market>` to source health. This catches the `south_korea` → 0 bug class without changing the screener params. **It is NOT the holiday detector** — a closed market returns the PRIOR session's rows, not zero. Market status comes from the index session date; see *Market-status detection — DATE PROVENANCE*.
- Do NOT expand to additional Asian markets (China, India, Vietnam, Indonesia, Philippines, Singapore) without verifying screener coverage first.
- **KRX caveat:** Korean stocks have daily price limits (typically ±15% for KOSPI, ±30% for KOSDAQ). Limit-move closes often produce data anomalies in `change_percent`. Use combined_analysis news to spot genuine earnings moves vs limit-driven non-fundamental moves; tag the latter as `KR_LIMIT_MOVE`.
- **HK caveat:** HKEX closes morning session 12:00 HKT, then afternoon 13:00-16:00 HKT. The `change_percent` reflects the full day's move (both sessions). Intra-lunch snapshots exist but aren't needed for this brief.
- **Japan caveat:** TSE closing auction runs 15:25-15:30 JST. At 06:30 ET scan time, that's 18:30 JST — well after the closing auction. Print should be final.

## Market-status detection — DATE PROVENANCE (the primary test)

**A closed market returns the PRIOR session's rows, not zero.** The old row-count heuristic
("screener returns < 5", "closed markets return 0") was false at its premise: on 2026-11-03 the
screener handed back a healthy-looking **128-row Japan universe that was really the 2 November
session**, because Tokyo was shut for Culture Day. The screener cannot settle the question —
its payload carries `name, description, close, change, change_abs, volume, market_cap_basic,
exchange, currency, sector, type, earnings_release_next_date, update_mode` and **no date at all**
(`update_mode` is a staleness flag, not a session date). So the session date comes from the index,
and the row count is demoted to a secondary signal.

### Test A — index session date (PRIMARY)

For each market, fetch the index's own quote and read **the date of its last daily bar**:

| Market | Index | Yahoo symbol | Close (local) |
|---|---|---|---|
| Japan | Nikkei 225 | `^N225` | 15:30 JST |
| Taiwan | TAIEX | `^TWII` | 13:30 TST |
| Hong Kong | Hang Seng | `^HSI` | 16:00 HKT |
| Korea | KOSPI | `^KS11` | 15:30 KST |

```bash
curl -sL --max-time 25 -A "Mozilla/5.0" \
  "https://query1.finance.yahoo.com/v8/finance/chart/%5EN225?range=10d&interval=1d"
```

The body is `{"chart":{"result":[{"timestamp":[...],"indicators":{"quote":[{"close":[...]}]}},
"meta":{...}}]}}`. **The last bar's timestamp IS the session date** — there is no separate date
field, and this endpoint needs no cookie/crumb handshake (measured 2026-11-05: 5/5 indices HTTP
200, and the missing 2026-11-03 bar is visible directly in `^N225`'s series). Convert the timestamp
with the exchange timezone in `meta.exchangeTimezoneName` (`Asia/Tokyo`, `Asia/Taipei`,
`Asia/Hong_Kong`, `Asia/Seoul`); the bar's UTC date equals its local date for all four markets, so
either is acceptable — but say which one was used.

`query1` and `query2` are interchangeable — try `query2` if `query1` fails. A 429/403 is a **rate
limit, not an absence**: retry once after a short sleep, then fall through to `web_fetch` on
`https://finance.yahoo.com/quote/%5EN225/` (the quote page prints the session date too), then to
the bridge. If NO source yields a session date for a market, that market's status is `UNKNOWN` —
never silently publish its rows.

**Cross-check (cheap, optional):** the MCP-over-HTTP bridge returns `as_of` and `market_state` per
symbol, and one batched call covers all four indices:

```bash
printf '%s' '{"symbols":"^N225,^TWII,^HSI,^KS11"}' > /workspace/_mcp/idx.json
python3 /workspace/mcp_bridge.py market-recap get_quotes /workspace/_mcp/idx.json
```

`as_of` is the timestamp of the last trade the price reflects, so its date is the session date;
`market_state` reads `closed` after the close. **Do NOT take the bridge's `previous_close` /
`change_pct` for index levels** — measured 2026-11-05, `^TWII` and `^HSI` carried a
**one-session-stale `previous_close`**, which would have published the wrong index % move. Take
index levels and their % change from the chart API's **two consecutive bars** (`close[-1]` vs
`close[-2]`); use the bridge for `as_of` / `market_state` corroboration only.

### Test B — archive comparison (the second, independent proof)

Test A asks the index "when did you last trade?". Test B asks the previous run "what did you
publish?" — a screener still serving yesterday's data reproduces yesterday's numbers.

**Fetch the previous artifact** (the newest `.md` whose date is **strictly before the fire date**):

```bash
curl -sL --max-time 25 \
  "https://api.github.com/repos/karizaco/minimax-cloud-outputs/contents/asia-pre-market?ref=main" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print('\n'.join(sorted(x['name'] for x in d if x['name'].endswith('.md'))))"
# then fetch that one file (contents API with ?ref=main first, then raw.githubusercontent.com)
curl -sL --max-time 25 -H "Accept: application/vnd.github.raw" \
  "https://api.github.com/repos/karizaco/minimax-cloud-outputs/contents/asia-pre-market/<PREV>.md?ref=main" \
  -o /workspace/_asia_prev.md
```

**Then compare, per market.** The comparison is on **`|change %|`, not just on the names**: if a
name that the previous artifact published still carries the *same* percentage in today's screener
rows, today's scan is the same session, re-served. The tickers must be normalised first —
**previous artifacts are not all in the same format** (2026-11-02 used bare tickers like
`7735 SCREEN Holdings`; 2026-11-03 and 11-04 used `TSE:7735`; the TL;DR sometimes uses Yahoo
style `3774.HK`), so a raw string comparison silently fails.

```bash
# previous artifact vs today's screener rows (the 4 JSON files from step 2)
python3 - /workspace/_asia_prev.md \
  /workspace/_asia_japan.json /workspace/_asia_taiwan.json \
  /workspace/_asia_hongkong.json /workspace/_asia_korea.json <<'PY'
import io, json, re, sys

VENUE = re.compile(r"\b(?:TSE|TWSE|TPEX|HKEX|KRX|NAG|FSE):([0-9A-Z]{1,6})\b")
YAHOO = re.compile(r"\b([0-9]{3,6})\.(?:HK|TW|T|KS|KQ)\b")
BARE  = re.compile(r"(?:^|\|)\s*([0-9]{3,6})\s+[A-Za-z]")
CHG   = re.compile(r"([+-]?\d+(?:\.\d+)?)\s*%")
CC    = {"JAPAN":"JP","KOREA":"KR","TAIWAN":"TW","HONG KONG":"HK"}
norm  = lambda c: (c.strip().upper().lstrip("0") or "0")

def blocks(text):
    heads = list(re.finditer(r"^##\s+(Japan|Korea|Taiwan|Hong Kong)\b[^\n]*$", text, re.M))
    for i, m in enumerate(heads):
        end = heads[i+1].start() if i+1 < len(heads) else len(text)
        nxt = re.search(r"^##\s+(?!Japan|Korea|Taiwan|Hong Kong)[^\n]*$", text[m.end():], re.M)
        if nxt: end = min(end, m.end() + nxt.start())
        yield CC[m.group(1).upper()], text[m.start():end]

def md_rows(block):                      # published rows of a previous artifact
    rows = {}
    for ln in block.splitlines():
        ln = ln.strip()
        if ln.startswith("|"):
            if re.fullmatch(r"\|[\s\-:|]+\|?", ln): continue
            cells = [c.strip() for c in ln.strip().strip("|").split("|")]
            if len(cells) < 2: continue
            mv = VENUE.search(cells[0]) or YAHOO.search(cells[0])
            code = norm(mv.group(1)) if mv else None
            if not code:
                mb = BARE.match("|" + cells[0])
                code = norm(mb.group(1)) if mb else None
            if not code: continue
            for c in cells[1:]:
                m = CHG.search(c)
                if m: rows.setdefault(code, abs(float(m.group(1)))); break
        elif ln.startswith("- ") or ln.startswith("• "):
            mv = VENUE.search(ln) or YAHOO.search(ln)
            m = CHG.search(ln)
            if mv and m: rows.setdefault(norm(mv.group(1)), abs(float(m.group(1))))
    return rows

def scan_rows(path, cc):                 # today's screener rows
    d = json.load(io.open(path, encoding="utf-8")); rows = {}
    for it in d.get("data", []):
        v = it.get("d", [])
        if len(v) < 9: continue
        name, change, exch, cur = v[0], v[3], v[7], v[8]
        if cc == "TW" and cur != "TWD": continue
        if cc == "HK" and cur != "HKD": continue
        if exch in ("NAG", "FSE"): continue
        if name in (None, ""): continue
        try: rows.setdefault(norm(str(name)), abs(float(change)))
        except (TypeError, ValueError): pass
    return rows

prev = dict(blocks(io.open(sys.argv[1], encoding="utf-8").read()))
files = {"JP": sys.argv[2], "TW": sys.argv[3], "HK": sys.argv[4], "KR": sys.argv[5]}
for cc, f in files.items():
    if cc not in prev:
        print("  %s: archive_compare_%s=unavailable" % (cc, cc.lower())); continue
    pr, tr = md_rows(prev[cc]), scan_rows(f, cc)
    if len(pr) < 3:
        print("  %s: archive_compare_%s=unavailable (fewer than 3 rows parsed)" % (cc, cc.lower())); continue
    same = [c for c, x in pr.items() if c in tr and abs(tr[c] - x) <= 0.05]
    pct = 100.0 * len(same) / len(pr)
    top5 = sorted(pr, key=lambda c: -pr[c])[:5]
    t5 = sum(1 for c in top5 if c in tr and abs(tr[c] - pr[c]) <= 0.05)
    v = "stale" if (pct >= 80.0 and t5 >= 4) else "fresh"
    print("  %s: archive_compare_%s=%s  unchanged %d/%d rows (%.1f%%), top-5 match %d/5"
          % (cc, cc.lower(), v, len(same), len(pr), pct, t5))
PY
```

**Thresholds.** `stale` requires **both** signals: ≥ 80% of the previous artifact's published rows
for that market carry the **same `|change %|`** (± 0.05pp) in today's screener rows, **and** ≥ 4 of
the previous artifact's **top-5** names match on both name and value. Fewer than 3 parsable
previous rows, or no country block in the previous artifact, ⇒ `unavailable`.

**Measured on the real artifacts** (2026-11-05, this script): for the 2026-11-03 fire against the
2026-11-02 artifact it returns `JP=stale` (9/10 rows unchanged, top-5 match 4/5) and
`TW/HK/KR=fresh` (0% unchanged) — it catches the exact failure it exists for. For the 2026-11-04
fire it returns `fresh` for all four (0% unchanged): no false positives.

If the previous artifact cannot be parsed for a market, record
`archive_compare_<market>=unavailable` and **do not use it as a verdict** — it is a proof, not a
veto. Same when there is no previous artifact (first run).

### Test C — row count (SECONDARY ONLY)

`screener returns < 5 rows` for a market that should have traded is a **secondary** signal. It can
corroborate a closure; it can never establish one on its own.

### The decision table

| Index session date (Test A) | Archive compare (Test B) | Verdict |
|---|---|---|
| `== fire_date` | fresh | `market_open_<m>=TRUE` — publish the rows |
| `== fire_date` | stale | `market_open_<m>=FALSE` — the screener is serving the prior session; publish nothing |
| `< fire_date` | stale / fresh / unavailable | `market_open_<m>=FALSE` — the market did not trade (holiday), or the source is stale |
| `> fire_date` | any | **late replay** — the scanner only ever serves its LATEST session, so today's rows belong to a later session than the fire date. Publish them only with the actual session date stated, and mark the artifact a reconstruction |
| unavailable | unavailable | `market_open_<m>=UNKNOWN` — say so in source health; publish nothing for that market |

**Fail safe.** When Test A says "closed" and Test B says "fresh", the market is still **CLOSED**
(`market_open_<m>=FALSE`) and the disagreement is logged as `market_open_conflict_<m>=TRUE` in
source health. A false closure costs one market's table; a false "open" publishes yesterday's
prices as today's — which is exactly the 2026-11-03 failure.

### What a closed market's section looks like

**A closed market's section is NOT a table.** It is one block:

```markdown
## Japan (JP) — no data — closed

`market_open_jp=FALSE` — Tokyo was shut (Culture Day; confirmed by <source>). Last session:
2026-11-02 (`^N225` session date 2026-11-02). No 2026-11-05 prices are published for Japan.
```

- **Never publish a prior session's prices for a market that did not trade** — no table, no price
  column, no movers list, not even labelled as context. The 2026-11-03 artifact did exactly that
  and it is the defect this section exists to prevent.
- The TL;DR carries one line per closed market: `JP closed (Culture Day); last session 2026-11-02`.
- Name the holiday **only** if a source confirms it (press, exchange calendar). Otherwise write
  `market holiday (name unconfirmed)` — never guess a holiday name.
- Log `market_open_<m>=FALSE` and `market_session_date_<m>=<last session date>` in source health
  and in the front-matter.
- If **all four** markets are closed, still write the artifact: every section says "no data —
  closed". A brief with no data is a result, not a reason to skip the run.

## Out of scope
- India (NSE/BSE) — can be added as a fifth market if user requests; TradingView supports it. Tracked for v5 alongside Canada (TSX).
- Singapore (SGX) — same as India.
- China (SHSE/SZSE) — different data access pattern in many Western APIs (offshore-only via HK connect). Tracked separately if user requests.
- Tokyo Stock Exchange sub-categories (TSE Prime / Standard / Growth) — `TSE` covers all three.
- KRX derivatives (KOSPI 200 options) — equity-spot only here.
- Asia-pre-market analysis with FX context (yen weakness, won carry trade, etc.) — could be added as separate "asia-fx-brief" skill; out of scope here.
- Structured Asian earnings calendar — see earnings calendar section above; documented gap.

## Change history
- **v1.3 — 2026-11-05.** The holiday detector was rebuilt on **date provenance**: a closed market returns the prior session's rows, not zero, so the row-count heuristic could never see a closure (it missed 2026-11-03's Japan, which served the 2 Nov session as a healthy 128-row universe). The index's own session date (`^N225`/`^TWII`/`^HSI`/`^KS11`, last daily bar) is now the primary test, the previous run's artifact is the second independent proof, and the row count is a secondary signal only. A closed market now gets a "no data — closed" section with **no prices published**. Also added: the US read-across block and its 3-bullet TL;DR, the fixed artifact skeleton (TL;DR / Market backdrop / country sections / Flags / Method, source health & caveats), per-country session dates in both the artifact and the chat reply, the contiguous country-block rule for the reply, and the runnable pre-publish assertions (name uniqueness, closed-market purity, catalyst cells, reply order).
- **v1.2 — 2026-11-04.** Output ordering made explicit: the brief is grouped **by country in the fixed order Japan → Korea → Taiwan → Hong Kong**, and inside each country every row (REACTION table + NOTABLE one-liners) is sorted by `|change %|` descending, with contiguous country blocks. The chat reply follows the same country order as the artifact.
- **v1.1 — 2026-09-23.** Validation pass. Market codes confirmed: `japan`, `taiwan`, `hongkong`, `korea` (NOT `south_korea` — that returns 0). Added `NAG` (Nagoya) and `TPEX` (Taipei Exchange) to the secondary-venue dedupe logic — keep only when the primary venue (TSE/TWSE respectively) doesn't list the same ticker. Added HK dual-ticker dedupe (e.g., 89988 vs 9988 for Alibaba). JP results dominated by `TSE:` with ~5-10% NAG noise; TW results ~30% `TPEX:` (smaller companies not on TWSE); HK all `HKEX:` with ~5-10% dual-ticker duplicates; KR all `KRX:` clean.
- **v1 — 2026-09-23.** Initial release. 4 Asian geos (JP/TW/HK/KR), single scan per geo with up + down direction. Lower threshold (2%) and tighter market cap floor ($2B) than EU/AU to reflect Asian market structure. Separate cron at 06:30 ET to land ahead of the main 08:00 ET brief.
