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
        cat > /workspace/$DATE/SKIPPED_stock_screener_focus_rvol_09_45.md <<EOF
# Cron #07 stock_screener_focus_rvol_09_45 — SKIPPED
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

## STEP 2 — SKILL SPEC (fetch once)
curl -sS -w 'HTTP=%{http_code}\n' https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/skills/stock-screener-suite/SKILL.md -o /tmp/skill.md
If that fails, retry once with -k (the GitHub cert has expired intermittently). Read the file in full
and follow the procedure with the Cloud adaptations below. If both attempts fail: write a stub
artifact with _source: skill_fetch_failed, report errors: 1, stop. Never improvise from memory.

## SHARED INSTRUCTIONS (fetch once — these rules apply to every routine)

The fleet-wide instructions live in ONE file, not in every prompt. Fetch it in the same first
step as the skill spec below, then follow it in full:

```bash
B=https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared
for U in "$B/PROMPT-BLOCKS.md" "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/PROMPT-BLOCKS.md"; do
  [ -s /workspace/PROMPT-BLOCKS.md ] || curl -sL -o /workspace/PROMPT-BLOCKS.md "$U" 2>/dev/null
done
```

It contains, and you must follow, all of these:

- `## MCP TOOLS AVAILABLE` — what actually exists in this runtime (the `mcp__*` names do NOT).
- `## RUNTIME DATA-SOURCE CONTRACT` — the source ladder (bridge `market-recap` → TradingView →
  Yahoo → Nasdaq/SEC/CoinGecko/Frankfurter/Treasury), the per-egress Yahoo caveat, and the
  "a 429 is a rate limit, not an absence" rule.
- `### MCP AVAILABILITY PROBE` — the one-call catalog probe and its four possible states.
- `### PRIMARY SOURCE` — the MCP-over-HTTP bridge: how to fetch it, how to call it, what
  `--list-packs` does and does not tell you.
- `### Rules` — the seven standing rules (rate limit vs missing, check the BODY not the status,
  never fabricate, no-data vs no-source, source health, partial data beats no data, one number per
  field one source per field).
- `## ZERO-FALLBACK POLICY`, `## HELPER SCRIPTS (PYTHON)`, `## AUDIT LOG` — how to handle a
  broken source, why the local Windows helpers do not exist, and why there is no audit log.
- `## DELIVERY` — the reply format your final chat message must use.

**If that fetch fails**, write a stub artifact with `_source=prompt_blocks_fetch_failed` and reply
with the failure. Do NOT improvise the source ladder, the fallback chain or the reply format from
memory — those are what keep a degraded run honest.


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


The `{date}` placeholder is the fire's **scheduled** date in US/Eastern, `YYYY-MM-DD`. Resolve it
from the run's `scheduled_at_ms` (`cron_read view=runs` → `run.scheduled_at_ms`), not from `date`
at execution time. If they differ, this is a **delayed replay**: rebuild for the scheduled date,
do NOT write a SKIPPED marker, and say in the artifact that it is a reconstruction produced late.
A replay is normal, not an error.

## GIT PUSH (OPTIONAL)

```bash
B=https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared
for U in "$B/push_artifact.sh" "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/push_artifact.sh"; do
  [ -s /workspace/push_artifact.sh ] || curl -sL -o /workspace/push_artifact.sh "$U"
done
sh /workspace/push_artifact.sh --out daily-screens --add daily-screens/{date}/focus-rvol-snapshot.md --branch main --msg "cron 07 stock-screener-focus-rvol-09:45 {date}" --nn 07
sh /workspace/verify_delivery.sh --path daily-screens/{date}/focus-rvol-snapshot.md --branch main
```

**If the push script cannot be fetched**, use the inline fallback in
`cloud-prompts/_shared/push_artifact.sh` — but never `git add -A`, and never
`git push … | head -3` (that returns head's exit status and reports a rejected push as success).

## DELIVERY VERIFICATION (MANDATORY - do this after the push block)

The push above already verifies its own delivery: `push_artifact.sh` calls
`verify_delivery.sh` and only reports `push: ok` when the path is present on the remote branch.
Run it again if you need to re-check:

```bash
sh /workspace/verify_delivery.sh --path daily-screens/{date}/focus-rvol-snapshot.md --branch main
```

A `git push` that exits 0 is **not** proof of delivery — a push piped into `head` returns head's
exit status (always 0) and reports a rejected push as a success. That is why the delivery check
exists, and why the push script must never be run with `git push … | head -3`.

## DELIVERY (the only thing delivered to the chat)
Six lines, no preamble:
focus-rvol-09:45 (cron #07) - DATE TIME_ET
window: passed | skipped (reason)
upstream: FOCUS_MD_PATH | missing
tickers: N | RVOL Required: N | Liquid: N | method: METHOD
file: PATH (BYTES B, written) | no artifact
push: ok | skipped (token unset) | failed (reason)
errors: N