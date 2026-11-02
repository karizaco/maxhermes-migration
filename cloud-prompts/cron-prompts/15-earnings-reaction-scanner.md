# Cloud Mavis cron: earnings-reaction-scanner (cron #15) — REPAIRED 2026-10-24

You are running as a Cloud Mavis cron on Mavis. Linux sandbox: no PowerShell, no Windows paths.
Output root: /workspace/ (mkdir -p it if missing).

## SCHEDULE
Fires 08:00 ET on weekdays: cron `0 8 * * 1-5`, timezone America/New_York.
This matches the skill's own spec (`0 8 * * 1-5` ET) — 23 min after the pre-market brief,
~90 min before the US open, ~5h into the EU session, ~6h after the ASX close.

**REPAIR NOTE (2026-10-24):** this task used to fire at 14:30 Europe/Berlin = 08:30 ET while its
window check demanded 09:00-16:00 ET, so it skipped itself every single day and has never
produced an artifact. The schedule is now `0 8 * * 1-5` America/New_York and the window check
below accepts the 08:00 ET fire. Do not "fix" a skip by assuming the market is closed — check
the clock and read the reason string.

## WINDOW CHECK (RUN FIRST, BEFORE FETCHING THE SKILL)

The scheduler owns the day-of-week and the hour, so this block exists for ONE reason: a cron
expression cannot express a **market holiday**, and the scheduler fires Mon-Fri *including* them.
On a holiday the market is closed and there is nothing to report.

```bash
# US MARKET HOLIDAYS — 2026 NYSE closures (non-weekend):
#   2026-01-01 2026-01-19 2026-02-16 2026-04-03 2026-05-25 2026-06-19 2026-07-03
#   2026-09-07 2026-11-26 2026-12-25
# Half-days (07:00 13:00 ET) are trading days and still report — do NOT skip them.
# The date is the fire's SCHEDULED date, not the execution date. If this is a
# delayed replay (the platform re-dispatches a session whose quota was exhausted),
# rebuild for the scheduled date and say so in the artifact - do not skip.
DATE=$(TZ=America/New_York date +%Y-%m-%d)
case "$DATE" in
    2026-01-01|2026-01-19|2026-02-16|2026-04-03|2026-05-25|2026-06-19|2026-07-03|2026-09-07|2026-11-26|2026-12-25)
        mkdir -p /workspace/$DATE
        cat > /workspace/$DATE/SKIPPED_earnings_reaction_scanner.md <<EOF
# Cron #15 earnings_reaction_scanner — SKIPPED
- Date (ET): $DATE
- Time (ET): $(TZ=America/New_York date +%H:%M)
- Reason: US market holiday ($DATE)
- No artifact produced.
EOF
        echo "out-of-window: US market holiday ($DATE)"
        echo "no artifact; no push"
        exit 0
        ;;
esac
echo "window-check: OK ($DATE)"
```

## STEP 2 — FETCH THE PIPELINE (the skill's MCP tools do not exist in Cloud)

The skill spec at
`https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/skills/earnings-reaction-scanner/SKILL.md`
is the authoritative *procedure* (passes, thresholds, tags, caps, artifact sections). Read it once
for reference.

But every MCP tool it calls is **absent in Cloud sessions** — verified 2026-10-24:
`mcp__tradingview-advanced__*`, `mcp__tradingview__*`, `mcp__financekit__*`, `mcp__stocktwits__*`
return 0 hits from `tool_search`, and `mcode-tools connector tools` holds only media + credential
tools. Do NOT burn turns re-testing them. A validated replacement pipeline is committed to the
shared output repo. Fetch and run it:

```bash
cd /workspace
mkdir -p scripts
curl -sS -w 'HTTP=%{http_code}\n' --max-time 60 \
  https://raw.githubusercontent.com/karizaco/minimax-cloud-outputs/main/scripts/earnings_reaction_scanner.py \
  -o scripts/earnings_reaction_scanner.py
head -5 scripts/earnings_reaction_scanner.py
```

If that fetch fails, retry once with `-k` (the GitHub cert expires intermittently). If both
attempts fail, write a stub artifact with `_source=skill_fetch_failed`, report `errors: 1`, stop.
Never improvise the procedure from memory.

## STEP 3 — RUN THE PIPELINE

```bash
cd /workspace
python3 scripts/earnings_reaction_scanner.py
```

It writes `/workspace/earnings/<date>-reactions.md` and
`/workspace/earnings/<date>-catalyst-targets.json`. It is self-timing: it takes ~4-6 minutes
because it cross-checks reported movers against Yahoo. **Give it a generous timeout** (at least
560s). If it exceeds that, capture the partial state and report the failure — do not silently
ship a half-written artifact.

What the pipeline does, and why (read this before changing any of it):

* Source is the TradingView **public screener** (`https://scanner.tradingview.com/<market>/scan`),
  which replaces the absent MCP screener. One POST per market per direction, JSON in, JSON out.
* **Stale-reference rows.** On illiquid rows the screener's `change` is computed against a stale
  reference close, producing absurd prints (MRNA on SIX showed +71.77% on 25 shares while the US
  line moved -1.25%). The tell: `change` == `Perf.W` exactly, and `Perf.1D` is always null.
  A **volume floor of 10,000** removes these rows. Do not lower it.
* **Venue codes differ from the skill's priority table.** The public scanner returns EURONEXT for
  FR/NL/BE/PT/IE, EUROTLX for IT, BX for CH, OMXCOP for DK, OMXHEX for FI, GPW for PL, VIE for
  AT, ATHEX for GR, XETR-family for DE, LSE for UK, ASX for AU. The skill's table (AMS/BRU/PAR/
  LIS/DUB/MC/HE/CO/VI/AT/SW/WA) is for the MCP screener. The pipeline maps them explicitly.
* **`country` is the reliable primary-listing filter** — it correctly excludes US ADRs listing on
  EU venues (97 of 200 Swiss rows were `country=United States`).
* **`earnings_release_date` = most recent FULL report date** (WDC 2026-10-22 matches the press),
  `earnings_release_next_date` = next scheduled. These replace the absent financekit calendar.
  **Caveat: this field does NOT capture preliminary, guidance or restructuring releases.** On
  2026-10-23 LKQ fell 22.47% on a preliminary Q3 miss while the field still read 2026-07-30.
  The field is a screen, never a verdict — confirm against the headline.
* **Yahoo cross-check.** Yahoo's ASX feed appends a trailing live-stamp bar at a different
  time-of-day than the completed daily bars; naive last-two-bar math makes every ASX move read
  0.00%. The pipeline keeps only bars stamped at the modal time-of-day before differencing.
  Verified 2026-10-24: **27 cross-checks agreed, 0 mismatched.**
* BOD rows (no extended-hours data) go to source health only, not the headline table, per the
  skill. US preferred shares (slash tickers like JPM/PC) are excluded.

## STEP 4 — CATALYSTS (the one step the pipeline cannot do)

The skill caps catalysts at 5 US + 3 EU + 2 AU = 10 per run. Read
`/workspace/earnings/<date>-catalyst-targets.json` for the ticker list, then use `web_search` to
find the headline for each (cap 10 searches; 1-2 per ticker). For US names, the earnings-driven
test is: did `earnings_release_date` land within 7 days of today? If yes, mark `Y` and use the
earnings headline as the catalyst. If not, mark `N` and find a non-earnings catalyst. For EU/AU
names apply the skill's keyword test (earnings / results / Q1-Q4 / beats / misses / reports /
guidance; plus interim, half-year, full-year, dividend, ASIC, iron ore, lithium, gold for AU).

**Then write the catalyst table to `/workspace/catalog/catalysts/<date>.md`** (mkdir -p first)
and re-run the pipeline, which splices that file into the artifact's `## Catalysts` section.
Doing it this way means a re-run never wipes your work. You may also edit the table in place
instead, but then do not re-run the pipeline afterwards.

**Never fabricate a headline.** If a search returns nothing usable, write "no fresh catalyst found".

## STEP 5 — WRITE THE ARTIFACT

The pipeline writes `/workspace/earnings/<date>-reactions.md` with the TL;DR, the US headline
table, US QUIET one-liners, the EU/UK table, the ASX table, source health and the audit line.
Keep every other section as the pipeline wrote it — it carries the row counts, the cross-check
result and the freshness stamps.

If the script failed and no artifact exists, write a stub with `_source=skill_fetch_failed` and
report the error. Never improvise the tables from memory.

## RUNTIME DATA-SOURCE CONTRACT (read before fetching any data)

**The `mcp__*` tools named above DO NOT EXIST in this runtime.** Do not attempt an MCP call and do
not wait for one to appear — a tool-not-found error converts into an early abort with no artifact.
Use instead: `web_search`, `web_fetch`, `bash` (curl, python3), and `connector__github__*` for repo
writes.

**Source ladder — try in this order, fall through on a real failure:**

1. bridge `market-recap` → `get_quotes` (batch quotes, `previous_close`, `change_pct`, `volume`,
   `as_of`, `market_state`). Not rate-limited. **This is the quote source of record.**
2. TradingView scanner `POST https://scanner.tradingview.com/america/scan` — movers, RVol,
   `premarket_volume`, `halted`, `market_cap_basic`.
3. Yahoo JSON — **availability varies by egress** (429 from one cron session, 200 from another on
   the same day). Try it; on 429/401 fall through. `quoteSummary`/`options` need the crumb.
4. Nasdaq API, SEC EDGAR (needs a contact-style User-Agent), CoinGecko, Frankfurter, Treasury CSV.

**A 429/403 is a RATE LIMIT, not a missing symbol.** Never report "no data" for a symbol you never
successfully queried. Retry once after a short sleep, then fall through.

**Sanity-check the RESPONSE BODY, not just the HTTP status.** Stooq returns 200 with a JavaScript
challenge, not CSV.

Full endpoint list + measured status:
`https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/RUNTIME-CONTRACT.md`


### MCP AVAILABILITY PROBE (non-blocking, one cheap call)

```bash
B=https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared
[ -s /workspace/probe_mcp.py ] || curl -sL -o /workspace/probe_mcp.py "$B/probe_mcp.py"
python3 /workspace/probe_mcp.py
```

Record the result in this run's `## Source health`. It prints exactly one of:
- `catalog_ok total=N finance_tools=0` — catalog healthy, no financial MCP registered.
- `catalog_ok total=N finance_tools=K` — **a financial MCP has LANDED. Switch to it this run.**
- `catalog_unreachable` — the probe failed. **NOT** evidence that no MCPs exist.
- `probe_unavailable` — the probe binary is absent. **NOT a finding**; use the source ladder.


### PRIMARY SOURCE: the MCP-over-HTTP bridge (use this FIRST)

The `mcp__*` tool names above are NOT registered here, but the MCP SERVERS are reachable
over plain HTTPS JSON-RPC from the sandbox. A ready-made bridge is published with the set:

  https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/mcp_bridge.py

```bash
BR=/workspace/mcp_bridge.py
for U in \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/mcp_bridge.py" \
  "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/mcp_bridge.py" \
  "https://api.github.com/repos/karizaco/maxhermes-migration/contents/cloud-prompts/_shared/mcp_bridge.py?ref=main" ; do
  [ -s "$BR" ] || curl -sL -H "Accept: application/vnd.github.raw" -o "$BR" "$U" 2>/dev/null
done
[ -s "$BR" ] || echo "bridge fetch FAILED - fall back to web_search, then the curl ladder"
mkdir -p /workspace/_mcp && cd /workspace/_mcp
printf '%s' '{"symbol":"SPY","period":"1m"}' > a.json
python3 /workspace/mcp_bridge.py stocktwits chart_data a.json      # OHLCV, sentiment, trending
printf '%s' "SELECT ticker, strftime(date, '%Y-%m-%d') AS d, close, volume FROM shibui.stock_quotes WHERE ticker = 'SPY' ORDER BY date DESC LIMIT 3" > q.txt
printf '%s' "SELECT ticker, close FROM shibui.stock_quotes WHERE ticker = 'SPY' ORDER BY date DESC LIMIT 3" > q.txt
python3 -c "import json,sys;print(json.dumps({'query':open('q.txt').read(),'user_prompt':'latest SPY close'}))" > b.json
python3 /workspace/mcp_bridge.py shibui stock_data_query b.json   # history to 1962, fundamentals, screeners, EDGAR

# --- market-recap: the primary quote + movers source (verified 2026-10-31) ---
printf '%s' '{"symbols":"SPY,QQQ,IWM,DIA,XLK,XLF,SMH,XBI"}' > c.json
python3 /workspace/mcp_bridge.py market-recap get_quotes c.json  # price, previous_close, change_pct, volume, day_high/low, as_of, market_state
printf '%s' '{}' > d.json
python3 /workspace/mcp_bridge.py market-recap top_movers d.json  # ranked gainers/losers/most-active
python3 /workspace/mcp_bridge.py market-recap market_snapshot d.json # indices, yields, FX, futures
python3 /workspace/mcp_bridge.py --list-packs                   # SEMANTIC DISCOVERY, not an inventory

# --- Barchart (AWS-WAF blocked for plain curl; works via headless chromium) ---
curl -s -o /workspace/barchart_fetch.py \
  https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/barchart_fetch.py
python3 /workspace/barchart_fetch.py --symbols SPY,QQQ,AAPL    # batch quotes
python3 /workspace/barchart_fetch.py --list top-gainers --limit 20
```

**Verified 2026-10-28:** both servers answer, 6/6 identical values over 6 calls (median 204 ms),
returning the same close web_search gave (SPY 769.66, 2026-10-27) while Yahoo JSON was 429.
Fetch the bridge with the 3-URL ladder above - a freshly pushed file can 404 on the raw CDN
for a few minutes. The bridge returns `{"error": ...}` and a non-zero exit on failure, so a
failed call can never be mistaken for data. **Pass tool args as a FILE, not inline** - shell
quoting corrupts the JSON. Server/tool reference: the RUNTIME-CONTRACT.md URL above.

**Order of attack: MCP bridge -> `web_search` -> curl ladder.** The bridge is the richest
source and is not rate-limited, so try it before Yahoo. If it fails, fall through.

### Rules

1. **A 429/403 is a RATE LIMIT, not a missing symbol.** Never report "no data" for a symbol you
   never successfully queried. Retry once after a short sleep, then fall through the ladder.
2. **Sanity-check the RESPONSE BODY, not just the HTTP status.** The proxy can return HTTP 200
   carrying a plain-text error page. Confirm the body parses as the JSON/CSV you expect.
3. **Never fabricate a number.** If every source for a symbol failed, omit that symbol and say so.
   A missing row is recoverable; an invented price is not.
4. **Distinguish "no data" from "no source".** No print today (pre-market, weekend, holiday) is
   `no_data`. A symbol you could not fetch is `fetch_failed` — name the reason and HTTP status.
5. **Every artifact carries a `## Source health` section**: per source, the URL/query used, the
   HTTP status, and `ok` / `failed:<reason>`. If a source was rate-limited, say `429 rate-limited`
   and which fallback you used. Never hide a degraded run.
6. **Partial data beats no data.** If some symbols resolved and others did not, WRITE the
   artifact with the symbols you have, mark the gaps, and report `errors: <n>`. Do not abort the
   whole run because one source was blocked. The zero-fallback policy governs the *fallback
   chain*, not whether the artifact gets written.
7. **One number per field, one source per field.** When two sources give different
   values for the same field, pick ONE and say which in `## Source health`: the bridge's
   `market-recap` for prices and movers (it is Yahoo-sourced and not rate-limited), the TradingView
   scanner for pre-market and RVol, Yahoo JSON for history. When they disagree by more than 0.6 %,
   prefer the bridge, say so, and **do not publish both**. Never report "no source available" when
   a source is reachable — a 429 is a rate limit, not an absence.


## GIT PUSH (OPTIONAL)

```bash
B=https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared
for U in "$B/push_artifact.sh" "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/push_artifact.sh"; do
  [ -s /workspace/push_artifact.sh ] || curl -sL -o /workspace/push_artifact.sh "$U"
done
sh /workspace/push_artifact.sh --out earnings --add earnings/{date}-reactions.md --branch main
sh /workspace/verify_delivery.sh --path earnings/{date}-reactions.md --branch main
```

**If the push script cannot be fetched**, use the inline fallback in
`cloud-prompts/_shared/push_artifact.sh` — but never `git add -A`, and never
`git push … | head -3` (that returns head's exit status and reports a rejected push as success).

## DELIVERY VERIFICATION (MANDATORY - do this after the push block)

The push above already verifies its own delivery: `push_artifact.sh` calls
`verify_delivery.sh` and only reports `push: ok` when the path is present on the remote branch.
Run it again if you need to re-check:

```bash
sh /workspace/verify_delivery.sh --path earnings/{date}-reactions.md --branch main
```

A `git push` that exits 0 is **not** proof of delivery — a push piped into `head` returns head's
exit status (always 0) and reports a rejected push as a success. That is why the delivery check
exists, and why the push script must never be run with `git push … | head -3`.

## DELIVERY
The final reply (the only thing delivered to the chat) MUST use this structure. There is **no
line cap** — cap by NAMES SHOWN (top ~8 per tier), not by lines. Long-form detail
belongs in the artifact file, not in the chat.

1. **Prose opener** — 2-4 sentences: the headline finding of the run, then the caveat
   that most changes how it should be read. Complete sentences; no label lists, no clipped
   fragments.
2. **`### Signal`** — tiered bullets, ONE ticker per line, each line a short clause
   naming the catalyst or setup (e.g. `- BA -10.8% — Q3 adj EPS -$0.34 vs -$0.21 est;
   737 Max ramp pushed to H2-27`). Follow the skill's chat rules for tier order, flags and the
   audit line. For THIS scanner the tiers are: US pre-market gaps (PRE_GAP), EU/UK movers,
   ASX movers, and the catalyst table — name the top movers in each tier with their
   move and the catalyst. Lead with the top movers and the count of names, and give the source
   and any lag. State how many further names are in the artifact file.
3. **`### Method & caveats`** — 2-4 bullets: source(s), lag, universe/screen size, and
   every degraded or blocked source. Name what could not be verified.
4. **`### Files`** — one line per file written, with its sandbox path.
5. **`### Push / errors`** — one line for push status (`push: ok (verified)` /
   `push: skipped (token unset)` / `push: FAILED (<reason>)`) and one line for
   `errors: <n>` — count of **SOURCE** failures that degraded the artifact.
   0 = clean run. The absent `mcp__*` tools are NOT an error and must not be
   counted.

Do not narrate tool calls. Tool call → result → write → push → reply.

## CRITICAL REMINDERS
1. Window check first. If it says out-of-window, exit cleanly — the SKIPPED file is the artifact.
2. The MCP tools in the skill spec do not exist in Cloud. Use the pipeline from the shared repo.
3. Do not lower the volume floor of 10,000. Without it, illiquid rows report 30-90% phantom moves.
4. Read-only. No trade ideas. Never fabricate a catalyst headline or a data value.
5. Every number in the artifact must come from a payload you actually received. If a pass returned
   too few rows to be credible, report the row count rather than padding the table.
6. If the cross-check reports any mismatch, say so in the chat reply. A mismatch means the
   screener and Yahoo disagree on a move you are about to publish — investigate before shipping.