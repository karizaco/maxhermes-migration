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
   `{'session_id': 'me', 'title': '<the title>'}`. `me` means THIS conversation.
   If `mcp_invoke` reports that the tool is unknown, call `tool_search` with the query
   'session title update', then retry the same `mcp_invoke` call.
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
#
# The skip marker is written AND PUSHED by the shared script, so a deliberate
# skip leaves a trace on the outputs repo instead of dying in the sandbox. A
# marker that never leaves the sandbox is indistinguishable from a failed run.
# The marker lives in refs/skipped-markers/, outside every routine's output
# directory, so it can never be mistaken for a delivered artifact.
DATE=$(TZ=America/New_York date +%Y-%m-%d)
case $DATE in
    2026-01-01|2026-01-19|2026-02-16|2026-04-03|2026-05-25|2026-06-19|2026-07-03|2026-09-07|2026-11-26|2026-12-25)
        S=/workspace/skip_marker.sh
        for U in \
          'https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/skip_marker.sh' \
          'https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/skip_marker.sh' ; do
          curl -sL --max-time 30 -o $S.tmp $U 2>/dev/null
          # A 404 page is a non-empty body that is NOT a script - never run one.
          if head -1 $S.tmp 2>/dev/null | grep -q '^#!'; then
            mv -f $S.tmp $S; break
          fi
          rm -f $S.tmp
        done
        if [ -s $S ] && head -1 $S 2>/dev/null | grep -q '^#!'; then
          sh $S --out daily-screens --name stock_screener_focus_rvol_09_45 \
             --label 'Cron #07 stock-screener-focus-rvol-09:45' \
             --reason 'US market holiday'-$DATE \
             --nn 07 --date $DATE || \
             echo 'skip-marker push: FAILED (the marker is still in the sandbox)'
        else
          echo 'skip-marker push: SKIPPED (skip_marker.sh unavailable - the marker could not be written)'
        fi
        echo 'out-of-window: US market holiday'-$DATE
        echo 'no artifact; no push'
        exit 0
        ;;
esac
echo 'window-check: OK'-$DATE
# CLOCK ASSERTION — this routine is worthless off-clock. Before the 2026-10-24 repair it
# fired at 22:45 ET for 13 consecutive days (timezone Etc/GMT-7 = UTC+7), and the old
# check silently wrote a SKIPPED file at 22:45 and called it a day. If the ET clock is
# outside the live session, STOP and say so instead of publishing a closed-tape snapshot.
HM=$(TZ=America/New_York date +%H%M)
if [ $HM -lt 0930 ] || [ $HM -gt 1100 ]; then
    printf 'out-of-window: off-clock fire (ET %s, expected 09:30-11:00)\n' $HM
    echo 'no artifact; no push'
    exit 0
fi
```
**Reply format for a holiday skip.** The `## DELIVERY` block expects a push line and an errors
line; a skipped fire has neither an artifact nor an error. Reply with these lines and nothing
else — do not narrate the tool calls and do not write an artifact:

```
out-of-window: US market holiday ($DATE)
file: no artifact (holiday skip — daily-screens/$DATE.md is intentionally absent)
push: marker pushed (refs/skipped-markers/$DATE_SKIPPED_stock_screener_focus_rvol_09_45.md) | marker push FAILED | marker push skipped (push script unavailable)
errors: 0
```


## STEP 2 — SKILL SPEC (fetch once)
curl -sS -w 'HTTP=%{http_code}\n' https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/skills/stock-screener-suite/SKILL.md -o /workspace/skill.md
**Save it under /workspace, NOT /tmp.** The Cloud `read` tool cannot open /tmp — it returns
'workspace path escapes Cloud Host root' — so a spec that lands in /tmp is unreadable and the run
stalls on a file it already has. `cat`/`sed`/`grep` on /workspace files work fine.
If that fails, retry once with -k (the GitHub cert has expired intermittently). Read the file in full
and follow the procedure with the Cloud adaptations below. If both attempts fail: write a stub
artifact with _source: skill_fetch_failed, report errors: 1, stop. Never improvise from memory.

## SHARED INSTRUCTIONS (fetch once — these rules apply to every routine)

The fleet-wide instructions live in ONE file, not in every prompt. Fetch it in the same first
step as the skill spec below, then follow it in full:

```

bash
B=https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared
for U in $B/PROMPT-BLOCKS.md 'https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/PROMPT-BLOCKS.md'; do
  [ -s /workspace/PROMPT-BLOCKS.md ] || curl -sL -o /workspace/PROMPT-BLOCKS.md $U 2>/dev/null
done
```

It contains, and you must follow, all of these:

- `## MCP TOOLS AVAILABLE` — what actually exists in this runtime (the `mcp__*` names do NOT).
- `## RUNTIME DATA-SOURCE CONTRACT` — the source ladder (bridge `market-recap` → TradingView →
  Yahoo → Nasdaq/SEC/CoinGecko/Frankfurter/Treasury), the per-egress Yahoo caveat, and the
  'a 429 is a rate limit, not an absence' rule.
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

**THREE DATES, THREE FIELDS — never collapse them into one.**
- `fire_date` — this fire's date, resolved from the run's `scheduled_at_ms`.
- `focus_dir_date` — the date in the folder the focus list was found in.
- `screen_data_date` — the sweep's OWN header line `Screen data_date: <date> (shibui T+1)`.
  READ IT from the focus.md header. Never infer it from the folder name, and never infer it
  from the calendar gap: cron #09 fires on WEEKDAYS ONLY, so on a Monday the newest list is
  Friday's sweep — a ONE-session lag, which is normal, not a degradation. The degradation is
  the shibui ingestion lag inside `screen_data_date`, which reached 3 sessions on 2026-11-02.
- `lag_sessions` — the number of TRADING sessions between `screen_data_date` and `fire_date`.
  Report the count. A calendar-day difference is NOT a session count.

The roster also turns over almost completely between sweeps — the 10-30 and 11-02 focus lists
shared exactly ONE name — so a stale list is not a cosmetic problem.

**If no focus.md exists ANYWHERE, do not simply fail.** Build a FALLBACK UNIVERSE from the
TradingView scanner: US stocks with `relative_volume_10d_calc` >= 1.5 and market cap > $300M,
top 12 by that column. Set `universe_source: fallback_tv_screener`, publish the snapshot, and
say in the artifact that the universe is a fallback. A degraded screen beats no screen, and most
of October's fires had no focus list at all. Only if the scanner also fails: write the artifact
with status: failed_no_upstream_focus_list, upstream: missing, list what you did find under
daily-screens/, report errors: 1, and stop. Do not push an empty snapshot as if it were a screen.

If a focus.md IS found: report its path, `focus_dir_date`, `screen_data_date` and `lag_sessions`.
If `lag_sessions` > 1, set status: degraded_stale_focus_list (see the status list in STEP 7).

## STEP 5 — RVOL PER FOCUS TICKER
Do NOT use mcp__tradingview_advanced__*, mcp__tradingview__* or mcp__yahoo_finance__*. They are
provably absent in Cloud sessions: mcode-tools connector tools returns partial=false,
provider_failures=[], with only connector__matrix__* and connector__email_workbench_credentials__*,
and tool_search returns 0 hits for every finance keyword. Do not burn turns re-testing them.

**SOURCE OF RECORD — one field, one source. Never mix them.**
| field | source | note |
|---|---|---|
| last price / close | bridge `market-recap get_quotes` | `market_state: open` proves a live session |
| session volume (cumulative) | Yahoo chart 5m bars, summed to the last COMPLETED bar | Yahoo `chartPreviousClose` is a cross-check |
| 10-day average daily volume (the denominator) | TV scanner `average_volume_10d_calc` | DENOMINATOR ONLY |
| full-day relative volume | TV scanner `relative_volume_10d_calc` | fallback proxy only — label it `rvol_proxy_daily` |

**TRAP — the TV scanner's LIVE columns lag the session. Never use them for a live field.**
Measured 2026-11-02: TV `volume` 1,144,478 vs Yahoo 2,615,246 (ADT) and 5,806 vs 58,577 (DFIN);
TV `close` 9.87 vs bridge 9.88. Minutes-to-hours stale. TV supplies the denominator here and
nothing else.

Working path, in order:
1. Intraday RVOL (preferred, matches the skill step 7): Yahoo chart API, ONE symbol per call:
   https://query1.finance.yahoo.com/v8/finance/chart/SYMBOL?interval=5m&range=1d
   Yahoo does NOT accept comma-separated symbols (404) and rate-limits (429) under load:
   sleep 1s between calls, retry once on 429.
2. Fallback, daily relative volume proxy: TradingView public scanner
   POST https://scanner.tradingview.com/america/scan with verified TLS, column
   relative_volume_10d_calc. If you use this, label the metric rvol_proxy_daily in the artifact.
   It is NOT intraday RVOL and the artifact must say so.

**TWO RECIPES THAT ARE ALREADY SOLVED — do not rediscover them.**
- TradingView scanner FILTER: a filter with left=name, operation=in and right=[ticker,...] returns
  HTTP 400 on this endpoint (verified 2026-11-02). Pull the full universe instead — body
  `columns` plus `range:[0,20000]`, ~19,900 rows — and filter locally for your tickers.
  One request, no filter.
- Yahoo IN-PROGRESS BAR: the last bar of the day is stamped with the CURRENT wall-clock time and
  its volume is still 0. Keeping it UNDERSTATES session volume. Drop every bar whose timestamp is
  later than the last COMPLETED 5-minute bar, and say in the artifact that you did.

Record the data timestamp for every symbol from the payload. A symbol with no intraday bars yet gets
no_intraday_bars - never silently substitute a daily value.

**THE METRIC — publish BOTH numbers, and name them differently.**
- `rvol_intraday_live` = cumulative session volume to the last completed bar / average daily
  volume over 10 days. This is the RAW ratio. At 09:45 ET only 15 of 390 session minutes have
  elapsed, so it is mechanically ~1/26 of the meaningful value and CANNOT reach 3 before the
  lunch bell for any name.
- `rvol_projected_eod` = `rvol_intraday_live` / (elapsed session minutes / 390). Pace-adjusted:
  if the name holds this pace it ends the session at that relative volume. THIS is the number the
  bucket threshold applies to. Never publish it as a bare 'RVOL'.
- NAME CLASH: cron #09's `focus.csv` already publishes `rvol_<date>` = the COMPLETED session's
  relative volume. That is a different quantity from either number above. Refer to it as
  `rvol_session_eod` when you compare them.

## STEP 6 — BUCKETS AND ALERT
Sort focus tickers by `rvol_projected_eod` desc.
- RVOL Required: `rvol_projected_eod` >= 3
- Liquid: everything else
Publish `rvol_intraday_live` beside it in the same table so the reader sees both numbers.

**A CROSSING NEEDS A PRIOR READING — read the previous session's artifact.**
`daily-screens/<previous session>/focus-rvol-snapshot.csv` (written by this routine, and by the
2026-10-28 run) carries the previous session's per-ticker RVOL. If it exists, compare per ticker:
a ticker CROSSED when its previous value was < 3 and today's `rvol_projected_eod` is >= 3.
Name every crossing ticker in the chat — that is the one alert this routine owes.
If no previous artifact exists there is no baseline: say so, publish no crossing alert, and write
`alerts: none (no prior reading available)` in the artifact. A crossing claimed without a prior
reading is a fabrication, not a signal.

An empty bucket is a real result. Report it as an empty bucket with counts, not as a failure.

## STEP 7 — WRITE THE ARTIFACT
Write TWO files in /workspace/daily-screens/DATE/ (create the dir; DATE = today ET):
  focus-rvol-snapshot.md
  focus-rvol-snapshot.csv      <- one row per ticker, machine-readable

Front-matter, exact keys in this order:
  date, cron, fire_time_et, fire_date, focus_dir_date, screen_data_date, lag_sessions,
  universe_source, universe_size, elapsed_minutes, session_fraction, source, method,
  metric_def, bucket_rule, status, upstream, names_unpriced
`lag_sessions`, `elapsed_minutes`, `session_fraction`, `universe_size` and `names_unpriced` are
numbers, not strings. `upstream` is the focus.md path, or `missing` / `fallback_tv_screener`.

Then a table — symbol | close | rvol_intraday_live | rvol_projected_eod | bucket | data
timestamp — sorted by `rvol_projected_eod` desc. Then a counts block (universe size, Required
count, Liquid count, crossings). Then `## Alerts` (name the crossing tickers, or write 'none' and
say why). Then `## Universe change` (names that entered or left the focus list vs the previous
sweep). Then the method actually used, then `## Source health`, then any degradation.
The CSV carries the same columns as the table, one row per ticker, plus the upstream `stylists`
and `flags` columns when the focus list provided them.

status must be exactly one of: ok, degraded_stale_focus_list, degraded_daily_rvol_proxy,
degraded_universe_fallback, failed_no_upstream_focus_list, failed_no_data.


The `{date}` placeholder is the fire's **scheduled** date in US/Eastern, `YYYY-MM-DD`. Resolve it
from the run's `scheduled_at_ms` (`cron_read view=runs` → `run.scheduled_at_ms`), not from `date`
at execution time. If they differ, this is a **delayed replay**: rebuild for the scheduled date,
do NOT write a SKIPPED marker, and say in the artifact that it is a reconstruction produced late.
A replay is normal, not an error.

## GIT PUSH (OPTIONAL)

```bash
B=https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared
for U in $B/push_artifact.sh 'https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/push_artifact.sh'; do
  [ -s /workspace/push_artifact.sh ] || curl -sL -o /workspace/push_artifact.sh $U
done
sh /workspace/push_artifact.sh --out daily-screens --add daily-screens/{date}/focus-rvol-snapshot.md --branch main
sh /workspace/verify_delivery.sh --path daily-screens/{date}/focus-rvol-snapshot.md --branch main
```

**If the push script cannot be fetched**, use the inline fallback in
`cloud-prompts/_shared/push_artifact.sh` — but never `git add -A`, and never
`git push … | head -3` (that returns head's exit status and reports a rejected push as success).

## DELIVERY VERIFICATION (MANDATORY - do this after the push block)

The push above already verifies its own delivery: `push_artifact.sh` calls `verify_delivery.sh`
and only reports `push: ok` when the path is present on the remote branch.
Run it again if you need to re-check:

```bash
sh /workspace/verify_delivery.sh --path daily-screens/{date}/focus-rvol-snapshot.md --branch main
```

A `git push` that exits 0 is **not** proof of delivery — a push piped into `head` returns head's
exit status (always 0) and reports a rejected push as a success. That is why the delivery check
exists, and why the push script must never be run with `git push … | head -3`.

## DELIVERY (the only thing delivered to the chat)
Seven lines, no preamble:
focus-rvol-09:45 (cron #07) - DATE TIME_ET
window: passed | skipped (reason)
upstream: FOCUS_MD_PATH (lag N session(s)) | missing | fallback_tv_screener
tickers: N | RVOL Required: N | Liquid: N | method: METHOD
alerts: NAME, NAME | none (no prior reading)
file: PATH (BYTES B, written) | no artifact
push: ok | skipped (token unset) | failed (reason)
errors: N