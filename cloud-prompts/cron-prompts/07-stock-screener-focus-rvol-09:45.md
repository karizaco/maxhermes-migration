# Cloud Mavis cron: stock-screener-focus-rvol-09:45 (cron #07) — repaired 2026-10-24

You are running as a Cloud Mavis cron on Mavis. Linux sandbox: no PowerShell, no Windows paths.
Output root: /workspace/ (mkdir -p it if missing).

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
Deployed schedule: `45 9 * * 1-5` America/New_York — 09:45 ET, Mon-Fri only.
- The day-of-week field is set in the SCHEDULER, so this routine does not fire
  at all on weekends: no agent invocation is spent discovering it is a weekend,
  and no weekend SKIPPED file is written. The in-prompt weekend branch below is
  kept as a belt-and-braces guard (it costs one line) and is what still handles
  US market holidays, which no cron expression can express.
The timezone was Etc/GMT-7 (= UTC+7) on the local machine, which fired this 11h off and
after market close; it is now America/New_York, so live intraday bars exist. Do not skip a run
because you think the market is closed — check the clock.

## STEP 1 — WINDOW CHECK (run this first)
mkdir -p /workspace
NOW_ET=$(TZ=America/New_York date '+%Y-%m-%d %H:%M %u')
DOW=$(TZ=America/New_York date +%u)
HOUR=$(TZ=America/New_York date +%H)
SKIP_REASON=
if [ "$DOW" -ge 6 ]; then SKIP_REASON="weekend (day=$DOW, expected Mon-Fri)"; fi
if [ "$HOUR" -lt 9 ] || [ "$HOUR" -ge 17 ]; then SKIP_REASON="outside market hours (hour=$HOUR ET, expected 09-16)"; fi
if [ -n "$SKIP_REASON" ]; then
  DATE=$(TZ=America/New_York date +%Y-%m-%d)
  mkdir -p /workspace/$DATE
  printf '# Cron #7 focus-rvol-09:45 - SKIPPED\n- Date (ET): %s\n- Time (ET): %s\n- Reason: %s\n' "$DATE" "$(TZ=America/New_York date +%H:%M)" "$SKIP_REASON" > /workspace/$DATE/SKIPPED_stock_screener_focus_rvol_09:45.md
  echo "out-of-window: $SKIP_REASON"
  echo "no artifact; no push"
  exit 0
fi
echo "window-check: OK ($NOW_ET)"

If this exits with out-of-window the run is DONE. The SKIPPED file IS the artifact. Do not fetch the
skill, do not sync, do not push.

## STEP 2 — SKILL SPEC (fetch once)
curl -sS -w 'HTTP=%{http_code}\n' https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/skills/stock-screener-suite/SKILL.md -o /tmp/skill.md
If that fails, retry once with -k (the GitHub cert has expired intermittently). Read the file in full
and follow the procedure with the Cloud adaptations below. If both attempts fail: write a stub
artifact with _source: skill_fetch_failed, report errors: 1, stop. Never improvise from memory.

## STEP 3 — SYNC UPSTREAM OUTPUTS (this was the blocking bug)
The upstream daily-sweep cron (#9, task 446554052374600) runs 18:30 ET and writes the Focus list to
the karizaco/minimax-cloud-outputs git remote. This cron sandbox does NOT share a filesystem with
it. You MUST pull before looking for the focus list:
cd /workspace
git init -q 2>/dev/null || true
git remote remove origin 2>/dev/null || true
git remote add origin https://x-access-token:${GITHUB_TOKEN}@github.com/karizaco/minimax-cloud-outputs.git 2>/dev/null || true
git config user.email maxhermes-cloud@local
git config user.name 'MaxHermes Cloud Cron'
GIT_SSL_NO_VERIFY=true git fetch -q origin main 2>&1 | head -3
git checkout origin/main -- daily-screens 2>/dev/null || true
If GITHUB_TOKEN is unset, skip the sync and record upstream: unavailable (no token). Do NOT fabricate
a focus list.

## STEP 4 — LOCATE THE FOCUS LIST
DATE=$(TZ=America/New_York date +%Y-%m-%d)
YDAY=$(TZ=America/New_York date -d yesterday +%Y-%m-%d)
for d in /workspace/daily-screens/$DATE /workspace/daily-screens/$YDAY; do
  if [ -f $d/focus.md ]; then echo FOUND $d/focus.md; fi
done
ls -1t /workspace/daily-screens/*/focus.md 2>/dev/null | head -3
Also check master.md in the same dirs for the wider universe.
If no focus.md exists the run FAILED, it is not 'degraded but fine'. Write the artifact with
status: failed_no_upstream_focus_list, upstream: missing, list what you did find under
daily-screens/, report errors: 1, and stop. Do not push an empty snapshot as if it were a screen.
If a focus.md is found, report its path AND the data-date in its header. The sweep data date can lag
the fire date; that lag must appear in your artifact header.

## STEP 5 — RVOL PER FOCUS TICKER
Do NOT use mcp__tradingview_advanced__*, mcp__tradingview__* or mcp__yahoo_finance__*. They are
provably absent in Cloud sessions: mcode-tools connector tools returns partial=false,
provider_failures=[], with only connector__matrix__* and connector__email_workbench_credentials__*,
and tool_search returns 0 hits for every finance keyword. Do not burn turns re-testing them.

Working path, in order:
1. Intraday RVOL (preferred, matches the skill step 7): Yahoo chart API, ONE symbol per call:
   https://query1.finance.yahoo.com/v8/finance/chart/SYMBOL?interval=5m&range=1d
   RVOL = cumulative volume today / average daily volume over 10 days. Take the denominator from the
   TV scanner column average_volume_10d_calc. Yahoo does NOT accept comma-separated symbols (404)
   and rate-limits (429) under load: sleep 1s between calls, retry once on 429.
2. Fallback, daily relative volume proxy: TradingView public scanner
   POST https://scanner.tradingview.com/america/scan with verified TLS, column
   relative_volume_10d_calc. If you use this, label the metric rvol_proxy_daily in the artifact.
   It is NOT intraday RVOL and the artifact must say so.

Record the data timestamp for every symbol from the payload. A symbol with no intraday bars yet gets
no_intraday_bars - never silently substitute a daily value. ETFs and overnight-traded symbols can
carry an in-progress bar: drop bars dated after the session date and note that you did.

## STEP 6 — BUCKETS AND ALERT
Sort focus tickers by RVOL desc. RVOL Required = RVOL >= 3. Liquid = the rest.
If any ticker crossed from below 1 to above 3, emit one chat alert naming it.
An empty bucket is a real result. Report it as an empty bucket with counts, not as a failure.

## STEP 7 — WRITE THE ARTIFACT
Write /workspace/daily-screens/DATE/focus-rvol-snapshot.md (create the dir; DATE = today ET).
Front-matter: date, cron, fire_time_et, data_date, source, method, status, upstream focus.md path.
Then a table: symbol | close | RVOL | bucket | data timestamp.
Then counts, the method actually used, and any degradation.
status must be exactly one of: ok, degraded_daily_rvol_proxy, failed_no_upstream_focus_list,
failed_no_data.

## RUNTIME DATA-SOURCE CONTRACT (read before fetching any data)

**The `mcp__*` tools named above DO NOT EXIST in this runtime.** They are listed for provenance
only. Verified 2026-10-28: the connector catalog exposes 15 tools, ALL media/email
(`connector__matrix__*`, `connector__email_workbench_credentials__*`). There is **no**
`mcp__yahoo_finance__*`, `mcp__tradingview__*`, `mcp__shibui_finance__*`, `mcp__stocktwits__*`,
`mcp__financekit__*` or `mcp__web_search__*`, and no `extract_content_from_websites`.
**Do not attempt an MCP call and do not wait for one to appear** — a tool-not-found error
converts into an early abort with no artifact, via the zero-fallback policy.

Use instead: `web_search` (search; returns page content), `web_fetch` (fetch a URL, incl. a raw
JSON endpoint), and `bash` (curl, python3). `web_search` uses a DIFFERENT egress than curl, so it
survives when curl is blocked. **Try `web_search` FIRST for any single-symbol quote.**

**Measured 2026-10-28 from this sandbox — Yahoo's JSON endpoints return HTTP 429** (spark,
chart, and screener alike), with and without a browser User-Agent and after a 60 s pause: it is
persistent rate limiting, not a transient burst. Yahoo's *HTML* pages still work, and `web_search`
still returns live data (SPY 769.66 close, 2026-10-27, while Yahoo JSON was 429).

Ladder for bulk data: Yahoo JSON → (on 429) Nasdaq API `https://api.nasdaq.com/api/quote/{SYM}/info?assetclass=etf`
→ Yahoo HTML `https://finance.yahoo.com/quote/{SYM}/` → `web_search` per symbol. Also confirmed
working: CoinGecko (crypto), Frankfurter (FX), SEC EDGAR (fundamentals, needs User-Agent),
US Treasury daily yield-curve CSV. Stooq CSV is blocked (404).
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
# Routine pairs share a fire minute and push to the SAME branch (16:30 #05+#16,
# 08:30 #08+#26, 14:00 #10+#13, 15:00 #06+#14). The loser's push is REJECTED and its
# artifact is LOST - while the old block still reported success, because
# `git push ... | head -3` takes head's exit status, always 0. Measured 2026-10-28:
# a concurrent push lost options-flow/<date>.md and reported exit 0.
# This loop re-fetches origin/main, rebuilds the worktree from the NEW tip, re-copies
# and re-commits, so the loser lands on the next attempt.
PUSH_OK=0
for attempt in 1 2 3; do
  git fetch -q origin main
  git worktree prune
  WT=/workspace/.wt.$(date +%s)$$
  rm -rf "$WT"
  git worktree add -f "$WT" origin/main >/dev/null 2>&1
  mkdir -p "$WT/daily-screens"
  cp -r "/workspace/daily-screens/." "$WT/daily-screens/" 2>/dev/null || true
  cd "$WT"
  git add daily-screens                 # ONLY this cron's output directory
  STAGED=$(git status --short)
  if [ -z "$STAGED" ]; then
    echo "push: ABORTED (nothing staged - the artifact was not copied into the worktree)"
    break
  fi
  if echo "$STAGED" | grep -q '^\s*D'; then
    echo "push: ABORTED (staged deletions detected - refusing to push)"
    break
  fi
  git commit -q -m "cron 07 07-stock-screener-focus-rvol-09%3A45.md $DATE" || echo "nothing to commit"
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
if git cat-file -e "origin/main:daily-screens/$DATE/focus-rvol-snapshot.md" 2>/dev/null; then
  echo "DELIVERY: ok (origin/main:daily-screens/$DATE/focus-rvol-snapshot.md present)"
else
  echo "DELIVERY: FAILED (origin/main:daily-screens/$DATE/focus-rvol-snapshot.md NOT found)"
  echo "  the artifact is still in the sandbox at daily-screens/ - report this, do not silently continue"
fi
```

`daily-screens/$DATE/focus-rvol-snapshot.md` is the repo-relative path of the artifact you just wrote, with `{{date}}`
replaced by `$DATE` (the shell variable above). If the cron writes several files, check the
primary one and list the rest.
- If DELIVERY is `ok` -> the reply line is `push: ok (verified)`.
- If DELIVERY is `FAILED` -> the reply line is `push: FAILED (artifact absent on origin/main)`.
  Say so plainly. Do NOT claim success. The artifact still exists in the sandbox, so also
  state the local path so the run is not lost.
- If the push was skipped (no token) -> `push: skipped (token unset)`.
- If all 3 push attempts were rejected, say so explicitly - a missing artifact is a real
  failure, not a warning.

## DELIVERY (the only thing delivered to the chat)
Six lines, no preamble:
focus-rvol-09:45 (cron #07) - DATE TIME_ET
window: passed | skipped (reason)
upstream: FOCUS_MD_PATH | missing
tickers: N | RVOL Required: N | Liquid: N | method: METHOD
file: PATH (BYTES B, written) | no artifact
push: ok | skipped (token unset) | failed (reason)
errors: N