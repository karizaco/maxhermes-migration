# Cloud Mavis cron: us-stocks-in-play (cron #17)

You are running as a Cloud Mavis cron. No local filesystem, no PowerShell, no Windows paths.
Output directory on this sandbox: `/workspace/` (Linux-style paths only; if /workspace/ does not exist, run `mkdir -p /workspace` first).

## CONVERSATION TITLE (do this FIRST, before anything else)

Every scheduled run gets its own conversation — one conversation per fire, never appended to an
earlier run's conversation. Give this conversation a title that says which day this run belongs
to, so the conversation list stays scannable.

1. Resolve today's date in US/Eastern: `TZ=America/New_York date +%d-%m` (day-month, no year).
2. Build the title: `[<DD-MM>] <NN>-<routine name>`. Take `<NN>` and `<routine name>` from the
   first line of this prompt (`# Cloud Mavis cron: <routine name> (cron #NN)`).
   Example: `[31-10] 12-cross-asset-correlation-snapshot`.
3. Set it with one call: `mcp_invoke` with tool_name `session_update` and arguments
   `{"session_id": "me", "title": "<the title>"}`. `me` means THIS conversation.
   If `mcp_invoke` reports that the tool is unknown, call `tool_search` with the query
   "session title update", then retry the same `mcp_invoke` call.
4. If the title cannot be set for any reason, carry on with the routine. This step must never
   block, delay, or fail the artifact.

## SCHEDULE
- Original local schedule: intraday
- Deployed schedule: `50 15 * * 1-5` America/New_York — 15:50 ET, Mon-Fri only.
- The day-of-week field is set in the SCHEDULER, so this routine does not fire at all on
  weekends: no agent invocation is spent discovering it is a weekend, and no weekend SKIPPED
  file is written. The WINDOW CHECK below keeps the one guard a cron expression cannot
  express — the market-holiday list.


## WINDOW CHECK (RUN FIRST, BEFORE FETCHING THE SKILL)

The scheduler owns the day-of-week and the hour, so this block exists for ONE reason: a cron
expression cannot express a **market holiday**, and the scheduler fires Mon-Fri *including* them.
On a holiday the market is closed and there is nothing to report.

```bash
# US MARKET HOLIDAYS — 2026 NYSE closures (non-weekend):
#   2026-01-01 2026-01-19 2026-02-16 2026-04-03 2026-05-25 2026-06-19 2026-07-03
#   2026-09-07 2026-11-26 2026-12-25
# Half-days (07:00 13:00 ET) are trading days and still report — do NOT skip them.
DATE=$(TZ=America/New_York date +%Y-%m-%d)
case "$DATE" in
    2026-01-01|2026-01-19|2026-02-16|2026-04-03|2026-05-25|2026-06-19|2026-07-03|2026-09-07|2026-11-26|2026-12-25)
        mkdir -p /workspace/$DATE
        cat > /workspace/$DATE/SKIPPED_us_stocks_in_play.md <<EOF
# Cron #17 us_stocks_in_play — SKIPPED
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

## SKILL SPEC (FETCH ONCE)
The skill's procedure body lives here:
  https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/skills/us-stocks-in-play/SKILL.md

**FIRST tool call:** `curl -s https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/skills/us-stocks-in-play/SKILL.md` (or `web_fetch` if available). Read the procedure in full. Do NOT skip this step.
Then follow the procedure verbatim, with these Cloud adaptations below.

## MCP TOOLS AVAILABLE

The **MCP-over-HTTP bridge** (`_shared/mcp_bridge.py` — see PRIMARY SOURCE) is the market-data
source. Then `web_search`, `web_fetch`, `bash` (curl, python3), `connector__github__*` (repo
writes). **No `mcp__*` finance tool is registered in this runtime** — do not call one and do not
invent tool names.

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

# --- market-recap: the primary quote + movers source (added 2026-10-31) ---
printf '%s' '{"symbols":"SPY,QQQ,IWM,DIA,XLK,XLF,SMH,XBI"}' > c.json
python3 /workspace/mcp_bridge.py market-recap get_quotes c.json  # price, previous_close, change_pct, volume, day_high/low, as_of, market_state
printf '%s' '{}' > d.json
python3 /workspace/mcp_bridge.py market-recap top_movers d.json  # ranked gainers/losers/most-active
python3 /workspace/mcp_bridge.py market-recap market_snapshot d.json # indices, yields, FX, futures
python3 /workspace/mcp_bridge.py --list-packs                   # SEMANTIC DISCOVERY, not an inventory
```

**Verified 2026-10-28:** both servers answer, 6/6 identical values over 6 calls (median 204 ms),
returning the same close web_search gave (SPY 769.66, 2026-10-27) while Yahoo JSON was 429.
**Verified 2026-10-31:** `market-recap` added and answering — `get_quotes` returned SPY 755.72,
QQQ 690.49, AAPL 344.63 with full `previous_close`/`change_pct`/`volume`/`as_of`/`market_state`,
`top_movers` returned the ranked US gainers table, `market_snapshot` returned a multi-region
market recap. `--list-packs` enumerated `tradier`, `fmp` and `market-recap`; `fmp` needs the
user's own FMP API key as `_apiKey`.
Fetch the bridge with the 3-URL ladder above - a freshly pushed file can 404 on the raw CDN
for a few minutes. The bridge returns `{"error": ...}` and a non-zero exit on failure, so a
failed call can never be mistaken for data. **Pass tool args as a FILE, not inline** - shell
quoting corrupts the JSON. Server/tool reference: the RUNTIME-CONTRACT.md URL above.

**Order of attack: MCP bridge -> `web_search` -> curl ladder.** The bridge is the richest
source and is not rate-limited, so try it before Yahoo. If it fails, fall through.

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


## ZERO-FALLBACK POLICY
The skill procedure uses a fallback chain (PRIMARY → FALLBACK → skip).
**Every fallback MUST terminate with:**
  "accept the partial result, write the artifact, and STOP. Do NOT chain <deeper MCP>."
Do NOT loop on MCP errors. Do NOT retry indefinitely. Do NOT re-raise.

## HELPER SCRIPTS (PYTHON)
Local Mavis called Python helpers like `python screen.py emit-sql ...` to do file I/O, parsing, and atomic writes.
**On Cloud, do NOT call those helpers — they don't exist here.** Re-implement the helper's job inline using tool calls:
  - SQL generation → emit SQL directly (see skill's reference docs if attached).
  - Finviz URL building → construct URL inline (see skill's filter spec).
  - Finviz HTML parsing → parse with regex/text extraction in agent context.
  - Atomic file write → `write_file(path, content)` (already atomic).
  - Deduplication → do it in agent reasoning before writing.

If the skill spec references a helper under `scripts/`, fetch the helper's URL too:
  https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/skills/us-stocks-in-play/scripts/<name>.py
Read it for reference, but do NOT execute it. Re-implement its logic.

## AUDIT LOG
Local Mavis wrote an audit line to a Windows audit file after every run.
**On Cloud, skip audit log writes.** Audit is not needed here. If something goes wrong, the failure is in the chat reply and the (missing) artifact.

## OUTPUT
Write the artifact to:
  `/workspace/us-stocks-in-play/{date}.md`

The `{date}` placeholder is the fire's **scheduled** date in US/Eastern, `YYYY-MM-DD`. Resolve it
from the run's `scheduled_at_ms` (`cron_read view=runs` → `run.scheduled_at_ms`), not from `date`
at execution time. If they differ, this is a **delayed replay**: rebuild for the scheduled date,
do NOT write a SKIPPED marker, and say in the artifact that it is a reconstruction produced late.
A replay is normal, not an error.
(Literal text "{date}" in this template — replace it with the actual date.)

If the skill produces multiple outputs (e.g. .md + .csv, or per-region files), write all of them in the same `/workspace/us-stocks-in-play/` subdirectory, with `{date}` as part of each filename.

## GIT PUSH (OPTIONAL)

```bash
B=https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared
for U in "$B/push_artifact.sh" "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/push_artifact.sh"; do
  [ -s /workspace/push_artifact.sh ] || curl -sL -o /workspace/push_artifact.sh "$U"
done
sh /workspace/push_artifact.sh --out us-stocks-in-play --add us-stocks-in-play/{date}.md --branch main
sh /workspace/verify_delivery.sh --path us-stocks-in-play/{date}.md --branch main
```

**If the push script cannot be fetched**, use the inline fallback in
`cloud-prompts/_shared/push_artifact.sh` — but never `git add -A`, and never
`git push … | head -3` (that returns head's exit status and reports a rejected push as success).


## DELIVERY VERIFICATION (MANDATORY - do this after the push block)

```bash
B=https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared
for U in "$B/push_artifact.sh" "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/push_artifact.sh"; do
  [ -s /workspace/push_artifact.sh ] || curl -sL -o /workspace/push_artifact.sh "$U"
done
sh /workspace/push_artifact.sh --out us-stocks-in-play --add us-stocks-in-play/{date}.md --branch main
sh /workspace/verify_delivery.sh --path us-stocks-in-play/{date}.md --branch main
```

**If the push script cannot be fetched**, use the inline fallback in
`cloud-prompts/_shared/push_artifact.sh` — but never `git add -A`, and never
`git push … | head -3` (that returns head's exit status and reports a rejected push as success).


## DELIVERY
The final reply (the only thing delivered to the chat) MUST use this structure. There is **no
line cap** — cap by NAMES SHOWN (top ~8 per tier), not by lines. Long-form detail belongs in
the artifact file, not in the chat.

1. **Prose opener** — 2-4 sentences: the headline finding of the run, then the caveat that most
   changes how it should be read. Complete sentences; no label lists, no clipped fragments.
2. **`### Signal`** — tiered bullets, ONE ticker per line, each line a short clause naming the
   catalyst or setup (e.g. `- BA -10.8% — Q3 adj EPS -$0.34 vs -$0.21 est; 737 Max ramp pushed
   to H2-27`). Follow the skill's chat rules for tier order, flags and the audit line.
   Lead with the top movers and the count of names, and give the source and any lag.
   State how many further names are in the artifact file.
3. **`### Method & caveats`** — 2-4 bullets: source(s), lag, universe/screen size, and every
   degraded or blocked source. Name what could not be verified.
4. **`### Files`** — one line per file written, with its sandbox path.
5. **`### Push / errors`** — one line for push status (`push: ok (verified)` /
   `push: skipped (token unset)` / `push: FAILED (<reason>)`) and one line for
   `errors: <n>` — count of **SOURCE** failures that degraded the artifact.
   0 = clean run. The absent `mcp__*` tools are NOT an error and must not be
   counted.

Do not narrate tool calls. Tool call → result → write → push → reply.

## CRITICAL REMINDERS
1. Skill URL above MUST be fetched first. If the fetch fails, write a stub artifact with `_source=skill_fetch_failed` and reply with the failure. Do NOT improvise the procedure from memory.
2. Use ONLY the tools named in the RUNTIME DATA-SOURCE CONTRACT above (`web_search`, `web_fetch`,
   `bash`, the MCP-over-HTTP bridge, and `connector__github__*` for repo writes). Do NOT call the
   `mcp__*` tools — they are not registered in this runtime — and do not invent tool names.
3. The cron session is fresh each time — there is no shared state. Treat every artifact as ephemeral unless pushed.
4. If the cron fires outside its intended window (a US market holiday — the scheduler owns the day-of-week, so a weekend fire cannot happen), exit cleanly with "out-of-window: <reason>". Do NOT run a degraded version.

================================================================
END OF CRON PROMPT
================================================================