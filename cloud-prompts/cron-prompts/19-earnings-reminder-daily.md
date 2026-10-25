# Cloud Mavis cron: earnings-reminder-daily (cron #19) — hardened 2026-10-25

You are running as a Cloud Mavis cron. No local filesystem, no PowerShell, no Windows paths.
Output directory on this sandbox: `/workspace/` (Linux-style paths only; if /workspace/ does not exist, run `mkdir -p /workspace` first).

## SCHEDULE
- Cron expression: `0 6 * * 1-5`, timezone `America/New_York` — 06:00 ET, Monday to Friday.
- The day-of-week field is now set in the SCHEDULER, so weekends never fire and no weekend
  SKIPPED file is produced. The weekend branch in the window check below is retained as a
  belt-and-braces guard (it costs one line) and is correct if the schedule is ever widened.
- The skill pairs with the 07:37 ET pre-market brief (cron #26 fires 08:30 ET). This artifact must
  land on disk BEFORE that brief reads it. It previously fired 11:30 ET on ALL days, i.e. after
  the brief and after the US open — that was a bug, now fixed.
- Session mode: `new` — every fire starts a clean conversation. The task was previously bound to a
  single long-lived session, which contradicts this prompt's own "the cron session is fresh each
  time" rule and let one run's context bleed into the next.

## WINDOW CHECK (RUN FIRST, BEFORE FETCHING THE SKILL)

The agent.minimax.io cron scheduler only supports coarse schedule types (daily, weekly, every X minutes).
It cannot express "weekdays at 09:45" or "every market hour". To work around this, this prompt
includes a window-check preamble. Run it as the FIRST step — before fetching the skill URL.

```bash
# Window flags for THIS cron (set by migration):
WEEKDAYS_ONLY=true
WEEKEND_ONLY=false
MARKET_HOURS_ONLY=false
DAY_OF_WEEK=0   # 1=Mon ... 7=Sun; 0=no constraint

# Resolve current time in US/Eastern
NOW_ET=$(TZ=America/New_York date +"%Y-%m-%d %H:%M %u")
DOW=$(TZ=America/New_York date +%u)
HOUR=$(TZ=America/New_York date +%H)
DATE=$(TZ=America/New_York date +%Y-%m-%d)

SKIP_REASON=""

if [ "$WEEKDAYS_ONLY" = "true" ] && [ "$DOW" -ge 6 ]; then
    SKIP_REASON="weekend (day=$DOW, expected Mon-Fri)"
fi
if [ "$WEEKEND_ONLY" = "true" ] && [ "$DOW" -lt 6 ]; then
    SKIP_REASON="weekday (day=$DOW, expected Sat-Sun)"
fi
if [ "$DAY_OF_WEEK" -gt 0 ] && [ "$DOW" -ne "$DAY_OF_WEEK" ]; then
    case $DAY_OF_WEEK in
        1) DAY_NAME="Monday";;
        2) DAY_NAME="Tuesday";;
        3) DAY_NAME="Wednesday";;
        4) DAY_NAME="Thursday";;
        5) DAY_NAME="Friday";;
        6) DAY_NAME="Saturday";;
        7) DAY_NAME="Sunday";;
    esac
    SKIP_REASON="wrong day (today=$DOW, expected $DAY_NAME=$DAY_OF_WEEK)"
fi

# US MARKET HOLIDAYS — the weekend test above is not sufficient. On a market holiday the market
# is closed and there is no "today's earnings" to report. 2026 NYSE closures (non-weekend):
#   2026-01-01 2026-01-19 2026-02-16 2026-04-03 2026-05-25 2026-06-19 2026-07-03
#   2026-09-07 2026-11-26 2026-12-25
# Half-days (07:00 13:00 ET) are trading days and still report — do NOT skip them.
case "$DATE" in
    2026-01-01|2026-01-19|2026-02-16|2026-04-03|2026-05-25|2026-06-19|2026-07-03|2026-09-07|2026-11-26|2026-12-25)
        SKIP_REASON="US market holiday ($DATE)"
        ;;
esac

if [ -n "$SKIP_REASON" ]; then
    mkdir -p /workspace/$DATE
    cat > /workspace/$DATE/SKIPPED_earnings_reminder_daily.md <<EOF
# Cron #19 earnings-reminder-daily — SKIPPED
- Date (ET): $DATE
- Time (ET): $(TZ=America/New_York date +%H:%M)
- Reason: $SKIP_REASON
- No artifact produced.
EOF
    echo "out-of-window: $SKIP_REASON"
    echo "no artifact; no push"
    exit 0
fi

echo "window-check: OK ($NOW_ET)"
```

If the window check exits cleanly with "out-of-window: <reason>", the cron is DONE. Do not fetch the skill, do not call MCPs, do not write any other artifact, do not push. The `SKIPPED_*.md` file IS the artifact for this run — it's the audit trail for skipped fires.

## SKILL SPEC (FETCH ONCE)

The skill's procedure body lives here:
  https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/skills/earnings-reminder/SKILL.md

**FIRST tool call:** `curl -s https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/skills/earnings-reminder/SKILL.md`
Read the procedure in full. Do NOT skip this step.

If curl fails with a certificate/TLS error (the sandbox egress proxy rotates its leaf cert and has
expired mid-session before), fall back to `web_fetch` on the SAME url. If both fail: write a stub
artifact with `_source=skill_fetch_failed`, report `errors: 1`, and stop. Never improvise from memory.

## DATA SOURCE — read this before spending turns on MCPs

There is NO Yahoo MCP and NO shibui MCP in Cloud sessions. `mcode-tools connector tools` returns
`partial=false, provider_failures=[]` with only `connector__matrix__*` and
`connector__email_workbench_credentials__*`; `tool_search` returns 0 hits for every finance keyword.
Do not probe for them, do not report their absence as an error, and do not count it as a fallback.

**PRIMARY = `web_search` / `web_fetch`.** That is the intended path, not a degraded fallback.
Working sources for the Oct-style daily calendar, in priority order:
1. `web_fetch` on the Yahoo Finance earnings calendar for the date (JS-rendered; the `?day=YYYY-MM-DD`
   URL renders the first ~25 rows server-side).
2. `web_fetch` on earningswhispers.com/calendar/YYYYMMDD — returns a full before-open/after-close
   ticker list with no JS dependency. Best single source for a complete roster.
3. `web_fetch`/`web_search` on investing.com earnings calendar, MarketBeat, TradingView, Newsquawk.

## ZERO-FALLBACK POLICY
Every fallback MUST terminate with: "accept the partial result, write the artifact, and STOP.
Do NOT chain <deeper source>." Do NOT loop on source errors. Do NOT retry indefinitely.

## HELPER SCRIPTS (PYTHON)
Local Mavis called Python helpers for file I/O, parsing, and atomic writes.
**On Cloud, do NOT call those helpers — they don't exist here.** Re-implement inline using tool calls.
If the skill spec references a helper under `scripts/`, fetch its URL for reference only:
  https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/skills/earnings-reminder/scripts/<name>.py
Read it, do NOT execute it.

## AUDIT LOG
Local Mavis wrote an audit line to a Windows audit file after every run.
**On Cloud, skip audit log writes.** If something goes wrong, the failure is in the chat reply and the
(missing) artifact.

## FILTER — the two rules that decide the roster

**Rule A — S&P 500 membership must be verified against a live constituent list, never from memory.**
Fetch the MediaWiki API wikitext and parse the symbol templates:
  curl -s "https://en.wikipedia.org/w/api.php?action=parse&page=List_of_S%26P_500_companies&prop=wikitext&format=json"
Parse `{{NyseSymbol|X}}` and `{{NasdaqSymbol|X}}`. You must get ~502 symbols.
CONTROL CHECK before trusting the parse: `BRK.B`, `GOOGL`, `GOOG` and `FOX` must all be present.
Do NOT parse the rendered HTML table — it yields a handful of symbols and silently corrupts the roster.
Cache the result to /workspace/.cache/sp500.txt and reuse it within the run.

**Rule B — confirm every report date against a company source before including a name.**
Aggregator calendars carry wrong dates. Verified examples: OMC (Oct 21→22), NEM (Oct 21→22),
ITW (Oct 23→27), NXPI (Oct 23→27), HCA (Oct 23→27), CHGCY (Oct 23→27), NWG (Oct 23→30),
INTC (Oct 22→29), SLB (Oct 22→23). For every name near the inclusion boundary, confirm the date
against the company IR page, press release or filing. Record each date-confirmed exclusion in the
artifact so the next run can see the pattern.

**Rule C — conflicting estimates.** Pick ONE primary source per field and say which: Yahoo for
market cap and EPS estimate, Investing.com/MarketBeat/Newsquawk for consensus revenue. When sources
disagree beyond tolerance (market cap >5%, EPS >2%), note the spread in the artifact. Observed
examples: AXP mcap $203.7B-$219.6B across five providers; INFY mcap $43.7B-$53.6B (straddles the
$50B threshold); META EPS 5.54 GAAP vs 6.35-6.67 adjusted.

## OUTPUT
Write the artifact to:
  `/workspace/earnings/{date}-reminders.md`

`{date}` = today in US/Eastern, `YYYY-MM-DD`. Resolve it as the FIRST step.
(Do not use the skill's local Windows path; the skill spec still names it and is wrong here.)

The artifact MUST start with a front-matter block so downstream consumers (cron #26 pre-market brief)
can parse it without guessing:

```
---
date: {date}
cron: 19-earnings-reminder-daily
fire_time_et: {HH:MM}
snapshot_et: {HH:MM}
source: Yahoo Finance earnings calendar
primary_source: Yahoo (market cap, EPS) | Investing.com (revenue)
status: ok | degraded_no_company_source | failed_no_calendar
pending_count: N
already_reported_count: N
---
```

Then: a `## Your watchlist` section ONLY IF a watchlist is actually available, then a
`## Big S&P 500 today` table with one row per name and a `Status` column:
`| Ticker | Company | Time | EPS est | Rev est | Mkt cap | Status |`
`Status` is `pending` or `reported` — on many days European/Indian names have already printed
before this cron fires, and the reader needs that distinction.

If no watchlist exists, omit the section entirely and say so once in the notes. Do not ship an
empty table every day. If the calendar cannot be reached at all, write a stub with
`_source=calendar_unavailable` and `status: failed_no_calendar`, and report `errors: 1`.

## GIT PUSH (OPTIONAL)

**Do NOT use the old `git init` + `git add -A` recipe.** In a fresh sandbox `git add -A` stages
every file on the branch as DELETED. Cron #12's push on 2026-10-25 (commit 1356a03) deleted 283
files that way, including all of cron #19's artifacts and the repo .gitignore. It has been repaired,
but do not reintroduce it.

Use a worktree at origin/main and add ONLY the artifact directory:

```bash
cd /workspace
export GIT_SSL_CAINFO=/etc/ssl/certs/agent-identity/sandbox-gateway-ca.crt
export SSL_CERT_FILE="$GIT_SSL_CAINFO"
export CURL_CA_BUNDLE="$GIT_SSL_CAINFO"
export HOME=/workspace/.home; mkdir -p "$HOME"
git config --global http.sslCAInfo "$GIT_SSL_CAINFO"
git config --global user.email "maxhermes-cloud@local"
git config --global user.name "MaxHermes Cloud Cron"
git init -q 2>/dev/null || true
git remote add origin "https://x-access-token:${GITHUB_TOKEN}@github.com/karizaco/minimax-cloud-outputs.git" 2>/dev/null || \
  git remote set-url origin "https://x-access-token:${GITHUB_TOKEN}@github.com/karizaco/minimax-cloud-outputs.git"
git fetch -q origin main
rm -rf /workspace/.wt
git worktree add -f /workspace/.wt origin/main
cp /workspace/earnings/{date}-reminders.md /workspace/.wt/earnings/
cd /workspace/.wt
git add earnings/{date}-reminders.md          # ONLY the artifact file
git status --short                            # MUST show no 'D' entries
git commit -q -m "cron #19 earnings-reminder-daily {date}" || echo "nothing to commit"
git push origin HEAD:main
```

If `git status --short` shows any `D` (deleted) entry, ABORT the commit and report the push as
failed — that is the exact condition that destroyed 283 files on 2026-10-25.
Never `git push --force`. The remote branch is `main`; a fresh `git init` creates local `master`.

**If `${GITHUB_TOKEN}` is empty/unset:** skip the push entirely. Do NOT try `gh auth` or any
fallback. Just write the artifact and reply.

## DELIVERY
The final reply (the only thing delivered to the chat) MUST be:
  - ≤ 8 lines.
  - Headline: count of names, source, and how many are still pending vs already reported.
  - One line per output file written.
  - One line: "push: ok" / "push: skipped (token unset)" / "push: failed (<reason>)".
  - One line: "errors: <n>" — count of SOURCE failures that degraded the artifact.
    0 = clean run. The absent Yahoo MCP is NOT an error and must not be counted.

No preamble. Tool call → result → write → push → reply.

## CRITICAL REMINDERS
1. Skill URL above MUST be fetched first. If the fetch fails, write a stub artifact with
   `_source=skill_fetch_failed` and reply with the failure. Do NOT improvise the procedure from memory.
2. There is no Yahoo MCP and no shibui MCP here. Do not probe for them and do not report their
   absence as an error. web_search / web_fetch IS the primary path.
3. Verify S&P 500 membership against the live constituent list (Rule A) and confirm report dates
   against company sources (Rule B). Never recall either from memory.
4. The cron session is fresh each time — there is no shared state. Treat every artifact as ephemeral
   unless pushed.
5. If the cron fires outside its intended window (weekend, US market holiday), exit cleanly with
   "out-of-window: <reason>". Do NOT run a degraded version.

================================================================
END OF CRON PROMPT
================================================================
