# Cloud Mavis cron: earnings-reminder-daily (cron #19) — hardened 2026-10-25

You are running as a Cloud Mavis cron. No local filesystem, no PowerShell, no Windows paths.
Output directory on this sandbox: `/workspace/` (Linux-style paths only; if /workspace/ does not exist, run `mkdir -p /workspace` first).

## SCHEDULE
- Original local schedule: `0 6 * * 1-5` America/New_York — 06:00 ET, Mon-Fri.
- Deployed schedule: `0 6 * * 1-5` America/New_York — 06:00 ET, Mon-Fri.
- The skill pairs with the pre-market brief, cron #26, which fires 08:30 ET (`30 8 * * 1-5`) —
  2h30m after this routine. This artifact must land on disk BEFORE that brief reads it.
  (#26 originally fired 07:37 ET; it was moved to 08:30 ET on 2026-10-31.)
- This routine previously fired 11:30 ET, i.e. after the brief and after the US open — that was a
  bug, now fixed.

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
case "$DATE" in
    2026-01-01|2026-01-19|2026-02-16|2026-04-03|2026-05-25|2026-06-19|2026-07-03|2026-09-07|2026-11-26|2026-12-25)
        S=/workspace/skip_marker.sh
        for U in \
          "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/skip_marker.sh" \
          "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/skip_marker.sh" ; do
          curl -sL --max-time 30 -o "$S.tmp" "$U" 2>/dev/null
          # A 404 page is a non-empty body that is NOT a script - never run one.
          if head -1 "$S.tmp" 2>/dev/null | grep -q '^#!'; then
            mv -f "$S.tmp" "$S"; break
          fi
          rm -f "$S.tmp"
        done
        if [ -s "$S" ] && head -1 "$S" 2>/dev/null | grep -q '^#!'; then
          sh "$S" --out earnings --name earnings_reminder_daily \
             --label "Cron #19 earnings-reminder-daily" \
             --reason "US market holiday ($DATE)" \
             --nn 19 --date "$DATE" || \
             echo "skip-marker push: FAILED (the marker is still in the sandbox)"
        else
          echo "skip-marker push: SKIPPED (skip_marker.sh unavailable - the marker could not be written)"
        fi
        echo "out-of-window: US market holiday ($DATE)"
        echo "no artifact; no push"
        exit 0
        ;;
esac
echo "window-check: OK ($DATE)"
```

## SKILL SPEC (FETCH ONCE)

The skill's procedure body lives here:
  https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/skills/earnings-reminder/SKILL.md

**FIRST tool call:** `curl -s https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/skills/earnings-reminder/SKILL.md`
Read the procedure in full. Do NOT skip this step.

If curl fails with a certificate/TLS error (the sandbox egress proxy rotates its leaf cert and has
expired mid-session before), fall back to `web_fetch` on the SAME url. If both fail: write a stub
artifact with `_source=skill_fetch_failed`, report `errors: 1`, and stop. Never improvise from memory.

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


## DATA SOURCE — read this before spending turns on MCPs

There is NO Yahoo MCP and NO shibui MCP in Cloud sessions. `mcode-tools connector tools` returns
`partial=false, provider_failures=[]` with only `connector__matrix__*` and
`connector__email_workbench_credentials__*`; `tool_search` returns 0 hits for every finance keyword.
Do not probe for them, do not report their absence as an error, and do not count it as a fallback.

**PRIMARY = `web_search` / `web_fetch`.** That is the intended path, not a degraded fallback.
Working sources for the daily calendar, in priority order:
1. `web_fetch` on the Yahoo Finance earnings calendar for the date (JS-rendered; the `?day=YYYY-MM-DD`
   URL renders the first ~25 rows server-side).
2. `web_fetch` on earningswhispers.com/calendar/YYYYMMDD — returns a full before-open/after-close
   ticker list with no JS dependency. Best single source for a complete roster.
3. `web_fetch`/`web_search` on investing.com earnings calendar, MarketBeat, TradingView, Newsquawk.


## FILTER — the two rules that decide the roster

**Rule A — S&P 500 membership must be verified against a live constituent list, never from memory.**
Fetch the MediaWiki API wikitext:
  curl -s "https://en.wikipedia.org/w/api.php?action=parse&page=List_of_S%26P_500_companies&prop=wikitext&format=json"
Parse ALL THREE symbol templates — `{{NyseSymbol|X}}`, `{{NasdaqSymbol|X}}` AND `{{BZX link|X}}`:
  re.findall(r'\{\{(?:NyseSymbol|NasdaqSymbol|BZX link)\|([A-Z.\-]{1,6})\}\}', wikitext)
**Why the third template matters:** Cboe Global Markets is written `{{BZX link|CBOE}}` in the
wikitext. A NyseSymbol/NasdaqSymbol-only regex yields 502 symbols and silently DROPS CBOE — a
real S&P 500 constituent — which then gets wrongly excluded from the roster. Verified 2026-10-30.
You must get **503** symbols, not 502.
CONTROL CHECK before trusting the parse: `BRK.B`, `GOOGL`, `GOOG`, `FOX` AND `CBOE` must all be
present. If any control is missing the parse is broken — stop and fix it rather than shipping a
truncated roster.
Do NOT parse the rendered HTML table — it yields a handful of symbols and silently corrupts the roster.
Do NOT treat the `datasets/s-and-p-500-companies` CSV as the authority: it is STALE (still lists
MMM, which left the index in 2024). Wikipedia is authoritative; the CSV is a cross-check only.
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

The `{date}` placeholder is the fire's **scheduled** date in US/Eastern, `YYYY-MM-DD`. Resolve it
from the run's `scheduled_at_ms` (`cron_read view=runs` → `run.scheduled_at_ms`), not from `date`
at execution time. If they differ, this is a **delayed replay**: rebuild for the scheduled date,
do NOT write a SKIPPED marker, and say in the artifact that it is a reconstruction produced late.
A replay is normal, not an error.

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

```bash
B=https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared
for U in "$B/push_artifact.sh" "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/push_artifact.sh"; do
  [ -s /workspace/push_artifact.sh ] || curl -sL -o /workspace/push_artifact.sh "$U"
done
sh /workspace/push_artifact.sh --out earnings --add earnings/{date}-reminders.md --branch main
sh /workspace/verify_delivery.sh --path earnings/{date}-reminders.md --branch main
```

**If the push script cannot be fetched**, use the inline fallback in
`cloud-prompts/_shared/push_artifact.sh` — but never `git add -A`, and never
`git push … | head -3` (that returns head's exit status and reports a rejected push as success).

## DELIVERY VERIFICATION (MANDATORY - do this after the push block)

The push above already verifies its own delivery: `push_artifact.sh` calls
`verify_delivery.sh` and only reports `push: ok` when the path is present on the remote branch.
Run it again if you need to re-check:

```bash
sh /workspace/verify_delivery.sh --path earnings/{date}-reminders.md --branch main
```

A `git push` that exits 0 is **not** proof of delivery — a push piped into `head` returns head's
exit status (always 0) and reports a rejected push as a success. That is why the delivery check
exists, and why the push script must never be run with `git push … | head -3`.


## CRITICAL REMINDERS
1. Skill URL above MUST be fetched first. If the fetch fails, write a stub artifact with
   `_source=skill_fetch_failed` and reply with the failure. Do NOT improvise the procedure from memory.
2. There is no Yahoo MCP and no shibui MCP here. Do not probe for them and do not report their
   absence as an error. web_search / web_fetch IS the primary path.
3. Verify S&P 500 membership against the live constituent list (Rule A) and confirm report dates
   against company sources (Rule B). Never recall either from memory.
4. The cron session is fresh each time — there is no shared state. Treat every artifact as ephemeral
   unless pushed.
5. If the cron fires outside its intended window (a US market holiday — the scheduler owns the
   day-of-week, so a weekend fire cannot happen), exit cleanly with "out-of-window: <reason>".
   Do NOT run a degraded version.

================================================================
END OF CRON PROMPT
================================================================