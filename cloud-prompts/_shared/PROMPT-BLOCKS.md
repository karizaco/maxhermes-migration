# Shared prompt blocks — the fleet-wide instructions

Fetched at run time by every digest routine in `cloud-prompts/cron-prompts/`. These are the
instructions that are **identical across the fleet**, so they are written once here instead of
being copied into 20 prompts. Each prompt keeps only what is specific to its own routine
(schedule, window check, skill URL, output path, push target) and points here for the rest.

**This file is authoritative for the sections it contains.** If a routine's own prompt and this
file disagree on a rule here, this file wins — with ONE carve-out: `## DELIVERY` below is the
house STANDARD reply format, not an override. The routines listed in
`cloud-prompts/cron-prompts/README.md` as machine-read exceptions (#07, #90, #01, #92a, #92b)
keep their OWN reply format, and their own prompt wins for them. Do not "normalise" an
exception to the standard form — that is a regression, not a fix.

USAGE — fetch it in the same first step as the skill spec:

    B=https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared
    D=/workspace/PROMPT-BLOCKS.md
    for U in \
      "https://api.github.com/repos/karizaco/maxhermes-migration/contents/cloud-prompts/_shared/PROMPT-BLOCKS.md?ref=main" \
      "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/PROMPT-BLOCKS.md" \
      "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/PROMPT-BLOCKS.md" ; do
      curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" \
        -H "Authorization: Bearer ${GITHUB_TOKEN}" -o "$D.tmp" "$U" 2>/dev/null
      if [ -s "$D.tmp" ] && ! head -c 200 "$D.tmp" | grep -q '"message"'; then
        mv -f "$D.tmp" "$D"; break
      fi
      rm -f "$D.tmp"
    done
    [ -s "$D" ] || echo "PROMPT-BLOCKS.md fetch FAILED - write a stub artifact with `_source=prompt_blocks_fetch_failed`"

If the fetch fails, write a stub artifact with `_source=prompt_blocks_fetch_failed` and reply with
the failure. Do NOT improvise these rules from memory — the fallback chain, the source ladder and
the response format are what keep a degraded run honest.

---

## WHERE A FINDING GOES (never agent memory)

A routine's findings are **artifacts and repo documents**. Agent memory is the wrong home for
them, and writing them there is the single biggest cause of the hot layer outgrowing its budget.

| What you found | Where it goes |
|---|---|
| A data quirk, a trap, a corrected procedure | `docs/IMPROVEMENTS-cronNN-<routine>.md` in `karizaco/maxhermes-migration` (the convention is in `docs/README.md`) |
| A change to how THIS routine works | its own skill spec `cloud-prompts/skills/<name>/SKILL.md` — the next fire fetches it, so **no `cron_update` and no byte-drift risk** |
| A fleet-wide rule | this file, or `cloud-prompts/_shared/RUNTIME-CONTRACT.md` |
| A defect in a prompt or a shared script | the repo file itself, plus a line in the matching `docs/IMPROVEMENTS-*.md` |

**Do NOT write findings into agent memory.** The hot layer is a short list of rules that apply to
*every* future session. A routine-scoped finding does not belong there: it buries the
cross-session rules, and it goes stale the moment the routine changes.

**Do NOT append a dated section.** Notes that arrive as `### Untitled (YYYY-MM-DD)` headings are
the main reason the hot layer keeps growing — each one is a new heading that nothing ever merges
or retires. If a rule genuinely is cross-session, fold it into the existing section it belongs to.

**The repo is the durable record.** It is version-controlled, reviewable, and it is where the next
session will look. Agent memory is not a backup for the repo — it is the short index of what the
repo cannot tell you.

---

## SHARED HELPER FETCHES (run these in step 1, with the skill spec)

The shared helpers are downloaded from the repo at run time. **Fetch them with the ladder below** —
the **contents API first**, because the CDNs cache `main` independently and one of them WILL be
stale: measured 2026-11-04, `raw.githubusercontent.com` served a stale blob for >17 minutes after a
push while the contents API was fresh.

The old `[ -s file ] || curl` loop was **dead**: the first successful download satisfied the guard,
so the fallback URL was never reached and a file already on disk was never refreshed.

```bash
for F in push_artifact.sh verify_delivery.sh skip_marker.sh; do
  D=/workspace/$F
  for U in \
    "https://api.github.com/repos/karizaco/maxhermes-migration/contents/cloud-prompts/_shared/$F?ref=main" \
    "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/$F" \
    "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/$F" ; do
    curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" \
      -H "Authorization: Bearer ${GITHUB_TOKEN}" -o "$D.tmp" "$U" 2>/dev/null
    if [ -s "$D.tmp" ] && ! head -c 200 "$D.tmp" | grep -q '"message"' \
       && head -1 "$D.tmp" 2>/dev/null | grep -q '^#!'; then
      mv -f "$D.tmp" "$D"; break
    fi
    rm -f "$D.tmp"
  done
  [ -s "$D" ] || echo "$F fetch FAILED - the DELIVERY step cannot verify its own push"
done
```

**Do this in step 1.** A helper that is only *called* is not on disk: `verify_delivery.sh` and
`skip_marker.sh` are invoked by the routines, and nothing else downloads them. If you skip this
block, the DELIVERY step either finds no script or falls back to the prompt's own fetch, which
takes the first URL only — the raw CDN, which may be stale.

**A routine-specific engine is NOT in that list.** Cron #16 runs `_shared/relvol_screen.py`, which
is fetched by that routine's own prompt and skill spec with a capability-marker check
(`RELVOL_SCREEN_V1`) — because fetching it fleet-wide would download a file most routines never
call. The rule is the same, though: **a helper that is only *called* is not on disk**, so fetch
it or the run silently degrades.

---

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

## MCP TOOLS AVAILABLE

The **MCP-over-HTTP bridge** (`_shared/mcp_bridge.py` — see PRIMARY SOURCE) is the market-data
source. Then `web_search`, `web_fetch`, `bash` (curl, python3), `connector__github__*` (repo
writes). **No `mcp__*` finance tool is registered on this runtime** — do not call one and do not
invent tool names.

**Two finance MCPs are not registered but ARE installable, and they work.** They are local stdio
servers, not platform tools:

| Server | Tools | What it adds |
|---|---|---|
| `tradingview-mcp` | 73 | `egx_stock_screener`, `egx_market_overview`, `rating_filter`, `bollinger_scan`, `multi_timeframe_analysis`, `volume_breakout_scanner` |
| `financekit-mcp` | 17 | `stock_quote`, `multi_quote`, `correlation_matrix`, `options_chain`, `earnings_calendar`, `sector_rotation`, `market_overview` |

```bash
DIR=/workspace/tvmcp; mkdir -p "$DIR"
for P in tradingview-mcp financekit-mcp; do
  env -u PIP_INDEX_URL -u UV_INDEX_URL \
    UV_DEFAULT_INDEX="https://pypi.org/simple" UV_INDEX_URL="https://pypi.org/simple" \
    uv pip install --python python3.11 --target "$DIR" "mcp<2" "$P"
done
PYTHONPATH="$DIR" "$DIR/bin/tradingview-mcp"     # stdio server; console script is `financekit`
```

**The `mcp<2` pin is MANDATORY** — the packages bundle mcp 2.x, where `FastMCP` was renamed
`MCPServer`; without the pin the server dies with `No module named 'mcp.server.fastmcp'`. Note
that `egx_stock_screener` filters on an **opaque vendor `min_score`** — use it for discovery,
never as an artifact's published criteria, because a score you cannot explain is a criterion you
cannot defend. Full recipe, argument shapes and per-routine fit: topic `mcp-bridge-data-quirks`
and `cloud-prompts/_shared/RUNTIME-CONTRACT.md` section 2d.

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
D=/workspace/probe_mcp.py
for U in \
  "https://api.github.com/repos/karizaco/maxhermes-migration/contents/cloud-prompts/_shared/probe_mcp.py?ref=main" \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/probe_mcp.py" \
  "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/probe_mcp.py" ; do
  curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" \
    -H "Authorization: Bearer ${GITHUB_TOKEN}" -o "$D.tmp" "$U" 2>/dev/null
  if [ -s "$D.tmp" ] && ! head -c 200 "$D.tmp" | grep -q '"message"' \
     && head -1 "$D.tmp" 2>/dev/null | grep -q '^#!'; then
    mv -f "$D.tmp" "$D"; break
  fi
  rm -f "$D.tmp"
done
[ -s "$D" ] || echo "probe_mcp.py fetch FAILED - record `probe_unavailable` in `## Source health` - it is NOT a finding"
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
D=/workspace/mcp_bridge.py
for U in \
  "https://api.github.com/repos/karizaco/maxhermes-migration/contents/cloud-prompts/_shared/mcp_bridge.py?ref=main" \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/mcp_bridge.py" \
  "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/mcp_bridge.py" ; do
  curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" \
    -H "Authorization: Bearer ${GITHUB_TOKEN}" -o "$D.tmp" "$U" 2>/dev/null
  if [ -s "$D.tmp" ] && ! head -c 200 "$D.tmp" | grep -q '"message"' \
     && head -1 "$D.tmp" 2>/dev/null | grep -q '^#!'; then
    mv -f "$D.tmp" "$D"; break
  fi
  rm -f "$D.tmp"
done
[ -s "$D" ] || echo "mcp_bridge.py fetch FAILED - fall back to web_search, then the curl ladder"
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
source, so try it before Yahoo. If it fails, fall through.

**THE BRIDGE IS METERED — the data is not rate-limited, the gateway is.** The Pipeworx
allowance is **50 tool calls/day per egress IP, shared across the whole fleet** (200/day with a
free key: `X-API-Key` / `?apikey=`; store it as `PIPEWORX_API_KEY` and `_shared/mcp_bridge.py`
sends it automatically). Every call costs one unit **regardless of how many symbols it returns** —
so **batch size, not symbol count, is what matters**.

Two rules that follow from it:

- **Never pull per-symbol history in a loop.** Use `_shared/rvol_fetch.py` (polygon-io
  `grouped_daily`): **one call returns OHLCV for every US symbol for one date**, so ten calls give
  a trailing-10-session volume denominator for the whole market instead of one call per ticker.
  **Fetch the helper first** — it is a separate file and is NOT on disk in a fresh sandbox:

  ```bash
  D=/workspace/rvol_fetch.py
  for U in \
    "https://api.github.com/repos/karizaco/maxhermes-migration/contents/cloud-prompts/_shared/rvol_fetch.py?ref=main" \
    "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/rvol_fetch.py" \
    "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/rvol_fetch.py" ; do
    curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" \
      -H "Authorization: Bearer ${GITHUB_TOKEN}" -o "$D.tmp" "$U" 2>/dev/null
    if [ -s "$D.tmp" ] && ! head -c 200 "$D.tmp" | grep -q '"message"' \
       && head -1 "$D.tmp" 2>/dev/null | grep -q '^#!'; then
      mv -f "$D.tmp" "$D"; break
    fi
    rm -f "$D.tmp"
  done
  [ -s "$D" ] || echo "rvol_fetch.py fetch FAILED - fall back to the caller's own denominator source"
  python3 "$RF" --date <YYYY-MM-DD> --sessions 10 --out /workspace/avg10.json
  ```

- **A volume read minutes after the bell is NOT final** — the closing auction consolidates
  later, and an understated numerator understates RVol and dollar volume (measured 0.7-30.2% low
  on 2026-11-02). Take the session-volume numerator from a settled source (`grouped_daily` or
  shibui), or label it as a snapshot in the artifact. **The `grouped_daily` bar for the session
  being published may not exist yet when you run** (measured 2026-11-03: the day's bar never
  published upstream during the run, though the prior ten did) — the denominator is unaffected
  because it excludes today by construction, but the numerator needs a settled fallback.

Full detail, including the exact `X-RateLimit-*` headers to read on failure: RUNTIME-CONTRACT.md
section 1e.

### Rules

> **A certificate/TLS error is a FETCH failure, not a missing source.** The sandbox egress proxy
> rotates its leaf cert and it has expired mid-session before; `web_fetch` uses a different
> egress and still works. On a cert error, retry the SAME url with `web_fetch` before you
> conclude anything about the source. Only after BOTH fail is it a source failure.

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
  https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/skills/asia-pre-market-reactions/scripts/<name>.py
Read it for reference, but do NOT execute it. Re-implement its logic.

**That reference-only rule is about a skill's own `scripts/` directory (the local Windows helpers),
not about `_shared/`.** The `_shared/` helpers ARE published to be executed by the routine that
needs them: `push_artifact.sh`, `window_check.sh`, `skip_marker.sh`, `mcp_bridge.py`,
`probe_mcp.py`, `rvol_fetch.py`, `barchart_fetch.py` and `relvol_screen.py` (cron #16's
relative-volume engine). A routine that runs one fetches it in its OWN prompt or skill block with
a capability-marker check, because most routines do not need it and the fleet-wide list above
would fetch files nobody calls.

## AUDIT LOG
Local Mavis wrote an audit line to a Windows audit file after every run.
**On Cloud, skip audit log writes.** Audit is not needed here. If something goes wrong, the failure is in the chat reply and the (missing) artifact.

## DELIVERY
The final reply (the only thing delivered to the chat) MUST use this structure. There is **no
line cap** — cap by NAMES SHOWN (top ~8 per tier), not by lines. Long-form detail belongs in
the artifact file, not in the chat.

**This is the STANDARD format.** Five routines are documented exceptions because their output is
machine-read rather than read by a human: #07 (a fixed status line), #90 (an audit digest),
#01 (a health check), #92a and #92b (pre-open checkpoints). They keep their own reply format
from their own prompt — do not "fix" them to this one. The list, with the reason for each,
is in `cloud-prompts/cron-prompts/README.md`.

1. **Prose opener** — 2-4 sentences: the headline finding of the run, then the caveat that most
   changes how it should be read. Complete sentences; no label lists, no clipped fragments.
2. **`### Signal`** — tiered bullets, ONE ticker per line, each line a short clause naming the
   catalyst or setup (e.g. `- BA -10.8% — Q3 adj EPS -$0.34 vs -$0.21 est; 737 Max ramp pushed
   to H2-27`). Follow the skill's chat rules for tier order, flags and the audit line **where the
   skill defines them; where it does not, order by absolute move, biggest first, and say nothing
   about a catalyst you did not source**. Lead with the top movers and the count of names, and
   give the source and any lag. State how many further names are in the artifact file.
3. **`### Method & caveats`** — 2-4 bullets: source(s), lag, universe/screen size, and every
   degraded or blocked source. Name what could not be verified.
4. **`### Files`** — one line per file written, with its sandbox path. When a routine writes many
   files of one kind (16 per-region CSVs), group them on one line and name the pattern — do not
   spend twenty lines on a list the reader cannot use. The full list belongs in the artifact.
5. **`### Push / errors`** — one line for push status (`push: ok (verified)` /
   `push: skipped (token unset)` / `push: FAILED (<reason>)`) and one line for
   `errors: <n>` — count of **SOURCE** failures that degraded the artifact.
   0 = clean run. The absent `mcp__*` tools are NOT an error and must not be
   counted.

**Formatting rules — the reply is rendered in a chat client, not read as a diff.**
- Use a compact markdown **table** whenever there are 3+ comparable numeric rows (index
  levels, sector rotation, futures, breadth). Header row, `|---|` separator, numbers
  right-aligned. A table beats prose for anything the reader is going to compare.
- Keep every bullet to **one short line**. Never cram three facts into a 300-character
  line with two em-dashes and three numbers — split it into two bullets, or move the
  detail to the artifact file.
- Bold only the numbers that carry the story (the headline move, the level that matters),
  not every figure in the table.
- Blank line between the header and the first bullet under it, so the section renders as a
  heading rather than a run-on block.

Do not narrate tool calls. Tool call → result → write → push → reply.
