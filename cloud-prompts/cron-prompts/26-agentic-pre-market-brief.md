# Cloud Mavis cron: agentic-pre-market-brief (cron #26)

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
- Original local schedule: 08:30 ET weekdays
- Deployed schedule: `30 8 * * 1-5` America/New_York — 08:30 ET, Mon-Fri only.
- The day-of-week field is set in the SCHEDULER, so this routine does not fire
  at all on weekends: no agent invocation is spent discovering it is a weekend,
  and no weekend SKIPPED file is written. The in-prompt weekend branch below is
  kept as a belt-and-braces guard (it costs one line) and is what still handles
  US market holidays, which no cron expression can express.
- There is no pre-market session on a weekend and this brief has no weekend edition, so it does
  not run on Saturday or Sunday at all. (Retired 2026-10-31 — it used to fire daily and produce a
  scoped WEEKEND brief; see WEEKEND MODE below, kept for reference only and NOT to be used.)

## WINDOW CHECK (RUN FIRST, BEFORE FETCHING THE SKILL)

```bash
mkdir -p /workspace
NOW_ET=$(TZ=America/New_York date '+%Y-%m-%d %H:%M %u')
DOW=$(TZ=America/New_York date +%u)
HOUR=$(TZ=America/New_York date +%H)
SKIP_REASON=
if [ "$DOW" -ge 6 ]; then SKIP_REASON="weekend (day=$DOW, expected Mon-Fri)"; fi
if [ -n "$SKIP_REASON" ]; then
  DATE=$(TZ=America/New_York date +%Y-%m-%d)
  mkdir -p /workspace/$DATE
  printf '# Cron #26 agentic-pre-market-brief - SKIPPED\n- Date (ET): %s\n- Time (ET): %s\n- Reason: %s\n' "$DATE" "$(TZ=America/New_York date +%H:%M)" "$SKIP_REASON" > /workspace/$DATE/SKIPPED_agentic_pre_market_brief.md
  echo "out-of-window: $SKIP_REASON"
  echo "no artifact; no push"
  exit 0
fi
echo "window-check: OK ($NOW_ET)"
```

If the window check exits cleanly with "out-of-window: <reason>", the cron is DONE. Do not fetch
the skill, do not call MCPs, do not write any other artifact, do not push. The `SKIPPED_*.md`
file IS the artifact for this run — it's the audit trail for skipped fires.

## WEEKEND MODE (RETIRED 2026-10-31)

This routine no longer fires on weekends. The deployed schedule `30 8 * * 1-5` restricts it to
Mon-Fri, so the scheduler never starts a Saturday or Sunday run — there is no weekend brief
to produce and no weekend mode to enter. The weekend procedure that used to live here is
RETIRED: do not write a weekend brief, do not label a column "Fri close", and do not treat a
weekend run as expected.


## SKILL SPEC (FETCH ONCE)
The skill's procedure body lives here:
  https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/skills/agentic-pre-market-brief/SKILL.md

**FIRST tool call:** `curl -s https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/skills/agentic-pre-market-brief/SKILL.md` (or `web_fetch` if available). Read the procedure in full. Do NOT skip this step.
Then follow the procedure verbatim, with these Cloud adaptations below.

## MCP TOOLS AVAILABLE
- `mcp__yahoo_finance__*`, `mcp__tradingview_advanced__*`, `mcp__web_search__*`
- `web_search`, `extract_content_from_websites` for catalyst/news research.

**Cloud reality (verified 2026-10-23/24):** all `mcp__yahoo_finance__*` / `mcp__tradingview*`
tools are NOT registered in this runtime. Replace at source with the equivalent live public APIs
and say so in Source health. Working replacements:
- Market/equity quotes + pre-market: Yahoo `https://query1.finance.yahoo.com/v7/finance/spark?symbols=A,B&range=1d&interval=1m&includePrePost=true` — **batches of 12 max** (larger batches return HTTP 400 on URL length).
- US screen: Yahoo `https://query2.finance.yahoo.com/v1/finance/screener/predefined/saved?scrIds=<id>&count=100&start=<n>` with ids `day_gainers` / `day_losers` / `most_actives`. **This tier needs no cookie/crumb.** The custom-POST screener tier (`v1/finance/screener` + getcrumb) is DOWN — `getcrumb` returns `Invalid Cookie` and POSTs return 401 `Invalid Crumb`. Do not retry it. Response shape: `finance.result` is a LIST — unwrap `result[0]`.
- Client-side US filter: `exchange ∈ {NMS,NYQ,PCX,ASE,NCM,NGM,NGS,AMX,PNK,OQB,OQX,BTS}`; drop warrants (symbol suffix W/U/WS/WT, or containing `=` or `^`); price>$10, mktcap>$3e8, vol>500k, |chg|>3.
- Sector rotation: pull the 11 SPDR ETFs (XLK XLP XLE XLF XLV XLI XLU XLY XLB XLRE XLC) as normal symbols. This is the fastest way to characterise a rotation and costs one batch.
- **Always pull the 11 sector ETFs.** They decided the 10/22 and 10/23 briefs.
- Pre-market gap = last 1m-bar close vs `regularMarketPrice`. **Do NOT use `chartPreviousClose`** (that is the prior session).
- Catalyst research: `web_search` (separate egress path from curl; stays up even if curl TLS breaks).

Full endpoint list + measured status: `https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/RUNTIME-CONTRACT.md`

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
python3 /workspace/mcp_bridge.py --list-packs                   # enumerate available packs

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


### MCP AVAILABILITY PROBE (non-blocking, one cheap call)

Run `python3 /workspace/probe_mcp.py` at the start of the run (fetch it from
`cloud-prompts/_shared/probe_mcp.py` if missing) and record the result in this run's
`## Source health`. It prints exactly one of three states:

- `catalog_ok total=N finance_tools=0` — catalog healthy, no financial MCP registered yet.
- `catalog_ok total=N finance_tools=K` — **a financial MCP has LANDED. Switch to it this run.**
- `catalog_unreachable` — the probe itself failed. This is **NOT** evidence that no MCPs exist.

The weekly `mcp-health/` routine does the same probe on a slower cadence; this in-run probe is
the fast path.

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

**Transport:** the sandbox egress proxy issues 24h leaf certs and has expired mid-window before. At run start check `openssl s_client -connect query1.finance.yahoo.com:443 -servername query1.finance.yahoo.com </dev/null 2>/dev/null | openssl x509 -noout -dates`. If the leaf is expired, use `curl -k` and **disclose the unverified transport in Source health**. If valid, use `--cacert /etc/ssl/certs/agent-identity/sandbox-gateway-ca.crt` for verified TLS. **Always sanity-check response BODIES, not just status codes** — the proxy can return HTTP 200 carrying a plain-text error page.

## ZERO-FALLBACK POLICY
The skill procedure uses a fallback chain (PRIMARY → FALLBACK → skip).
**Every fallback MUST terminate with:**
  "accept the partial result, write the artifact, and STOP. Do NOT chain <deeper MCP>."
Do NOT loop on MCP errors. Do NOT retry indefinitely. Do NOT re-raise.

## HELPER SCRIPTS (PYTHON)
Local Mavis called Python helpers like `python screen.py emit-sql ...` to do file I/O, parsing, and atomic writes.
**On Cloud, do NOT call those helpers — they don't exist here.** Re-implement the helper's job inline using tool calls.

## AUDIT LOG
Local Mavis wrote an audit line to a Windows audit file after every run.
**On Cloud, skip audit log writes.** Audit is not needed here. If something goes wrong, the failure is in the chat reply and the (missing) artifact.

## OUTPUT
Write the artifact to:
  `/workspace/daily-briefs/{date}-pre-market.md`

The `{date}` placeholder is today in US/Eastern, `YYYY-MM-DD`. Resolve it as the first step.
(Literal text "{date}" in this template — replace it with the actual date.)

If the skill produces multiple outputs (e.g. .md + .csv, or per-region files), write all of them in the same `/workspace/daily-briefs/` subdirectory, with `{date}` as part of each filename.

## GIT PUSH (OPTIONAL)
After writing the artifact, commit and push it to `karizaco/minimax-cloud-outputs` (branch `main`).

```bash
cd /workspace
export GIT_SSL_CAINFO=/etc/ssl/certs/agent-identity/sandbox-gateway-ca.crt
export SSL_CERT_FILE="$GIT_SSL_CAINFO"
export CURL_CA_BUNDLE="$GIT_SSL_CAINFO"
export HOME=/workspace/.home; mkdir -p "$HOME"
export DATE=$(TZ=America/New_York date +%Y-%m-%d)
git config --global http.sslCAInfo "$GIT_SSL_CAINFO"
git config --global user.email "maxhermes-cloud@local"
git config --global user.name "MaxHermes Cloud Cron"
git init -q 2>/dev/null || true
git remote add origin "https://x-access-token:${GITHUB_TOKEN}@github.com/karizaco/minimax-cloud-outputs.git" 2>/dev/null || \
  git remote set-url origin "https://x-access-token:${GITHUB_TOKEN}@github.com/karizaco/minimax-cloud-outputs.git"

# --- push with race retry ---
# Routines that share a fire minute push to the SAME branch (08:30 #08+#26;
# 14:00 #10+#13 on Wednesdays). The loser's push is REJECTED and its
# artifact is LOST - while the old block still reported success, because
# `git push ... | head -3` takes head's exit status, always 0. Measured 2026-10-28:
# a concurrent push lost options-flow/<date>.md and reported exit 0.
# (#16 was moved 16:30 -> 16:35 ET on 2026-10-29 to clear its 16:30 collision with #05.)
# The retry loop below is the real protection - it makes the loser land on a later attempt.
# This loop re-fetches origin/main, rebuilds the worktree from the NEW tip, re-copies
# and re-commits, so the loser lands on the next attempt.
PUSH_OK=0
for attempt in 1 2 3; do
  git fetch -q origin main
  git worktree prune
  WT=/workspace/.wt.$(date +%s)$$
  rm -rf "$WT"
  git worktree add -f "$WT" origin/main >/dev/null 2>&1
  mkdir -p "$WT/daily-briefs"
  cp -r "/workspace/daily-briefs/." "$WT/daily-briefs/" 2>/dev/null || true
  cd "$WT"
  git add daily-briefs                 # ONLY this cron's output directory
  STAGED=$(git status --short)
  if [ -z "$STAGED" ]; then
    echo "push: ABORTED (nothing staged - the artifact was not copied into the worktree)"
    break
  fi
  if echo "$STAGED" | grep -q '^\s*D'; then
    echo "push: ABORTED (staged deletions detected - refusing to push)"
    break
  fi
  git commit -q -m "cron 26 26-agentic-pre-market-brief.md $DATE" || echo "nothing to commit"
  if git push -q origin HEAD:main 2>/tmp/push.err; then
    PUSH_OK=1
    echo "push: ok (attempt $attempt)"
    break
  fi
  echo "push: attempt $attempt rejected: $(head -1 /tmp/push.err | tr -d '\r')"
  sleep 5
done
cd /workspace
```

**CRITICAL - never use `git add -A` here.** In a fresh sandbox the working tree does not
contain the rest of the repo, so `git add -A` stages every other file on the branch as
DELETED. On 2026-10-25 cron #12's push (commit 1356a03) did exactly that and deleted 283
files, wiping the artifacts of cron #19 and seven other crons, plus the repo `.gitignore`.
If `git status --short` shows any `D` (deleted) entry, ABORT the commit and report the push
as failed.
Never `git push --force`. The remote branch is `main`; a fresh `git init` creates local
`master`, which is why the push target is `HEAD:main` and not `origin main`.
Never loop forever on a push failure - 3 attempts, then report the failure.
**If `${GITHUB_TOKEN}` is empty/unset:** skip the push entirely. Do NOT try `gh auth` or any
fallback. Just write the artifact and reply.

## DELIVERY VERIFICATION (MANDATORY - do this after the push block)
A successful `git push` is NOT proof of delivery. Verify the artifact is actually ON the remote
branch, and report the result truthfully. A push that silently failed is worse than a push that
failed loudly.

```bash
cd /workspace
export DATE=$(TZ=America/New_York date +%Y-%m-%d)
git fetch -q origin main
if git cat-file -e "origin/main:daily-briefs/$DATE-pre-market.md" 2>/dev/null; then
  echo "DELIVERY: ok (origin/main:daily-briefs/$DATE-pre-market.md present)"
else
  echo "DELIVERY: FAILED (origin/main:daily-briefs/$DATE-pre-market.md NOT found)"
  echo "  the artifact is still in the sandbox at daily-briefs/ - report this, do not silently continue"
fi
```

`daily-briefs/$DATE-pre-market.md` is the repo-relative path of the artifact you just wrote, with `{{date}}`
replaced by `$DATE` (the shell variable above). If the cron writes several files, check the
primary one and list the rest.
- If DELIVERY is `ok` -> the reply line is `push: ok (verified)`.
- If DELIVERY is `FAILED` -> the reply line is `push: FAILED (artifact absent on origin/main)`.
  Say so plainly. Do NOT claim success. The artifact still exists in the sandbox, so also
  state the local path so the run is not lost.
- If the push was skipped (no token) -> `push: skipped (token unset)`.
- If all 3 push attempts were rejected, say so explicitly - a missing artifact is a real
  failure, not a warning.

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
   `push: skipped (token unset)` / `push: FAILED (<reason>)`) and one line for `errors: <n>` —
   count of MCP failures that triggered fallback. 0 = clean run.

Do not narrate tool calls. Tool call → result → write → push → reply.

## CRITICAL REMINDERS
1. Skill URL above MUST be fetched first. If the fetch fails, write a stub artifact with `_source=skill_fetch_failed` and reply with the failure. Do NOT improvise the procedure from memory.
2. Use ONLY the tools named in the RUNTIME DATA-SOURCE CONTRACT above (`web_search`, `web_fetch`, `bash`). Do NOT call the `mcp__*` tools — they are not
   registered in this runtime — and do not invent tool names.
3. The cron session is fresh each time — there is no shared state. Treat every artifact as ephemeral unless pushed.
4. **This routine runs on WEEKDAYS only** (`30 8 * * 1-5`). The scheduler never starts a weekend
   run, and there is no weekend brief to produce. If the window check skips (a US market
   holiday), exit cleanly with "out-of-window: <reason>" and write the SKIPPED file — on a
   holiday a skipped fire is correct behaviour, not a failure.
5. Every percentage in the brief must trace to a fetched value or a cited source. Do not invent numbers. Audit before rendering.

================================================================
END OF CRON PROMPT
================================================================