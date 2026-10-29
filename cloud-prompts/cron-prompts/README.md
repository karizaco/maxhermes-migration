# Cloud Mavis Cron Prompts — Bucket 1 (Pure MCP, chat-delivery)

20 cron prompts migrated from local Mavis to Cloud Mavis. Each prompt:
- Loads its skill spec via `https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/skills/<name>/SKILL.md`
- Runs the same MCP calls as the local version
- Re-implements any local Python helpers inline
- Writes artifact to `/workspace/...`
- Optionally pushes to `minimax-cloud-outputs` if `${GITHUB_TOKEN}` is set
- Skips audit log writes (not needed on Cloud)
- Falls back with a stop-and-write tiebreaker, never chains deeper

## Cron index

| ID | Name | Schedule | MCPs | Output |
|----|------|----------|------|--------|
| 2 | asia-pre-market-reactions | 06:30 ET weekdays | yahoo, tradingview | asia-pre-market/{date}.md |
| 4 | reversal-bullish-3:55 | 15:55 ET weekdays | shibui, tradingview, yahoo | daily-screens/{date}/reversal-bullish-3:55.{md,csv} |
| 5 | eod-international-daily | 16:30 ET weekdays | tradingview, tradingview-basic, yahoo | international-eod/{date}/<region>.csv |
| 6 | stock-screener-pattern-study-backlog | Saturday weekly | shibui | weekly-ipo.md, weekly-high-short-float.md, peoplewish backlog append |
| 7 | stock-screener-focus-rvol-09:45 | 09:45 ET weekdays | tradingview | daily-screens/{date}/focus-rvol-snapshot.md |
| 8 | stock-screener-pre-market-gapper | 08:30 ET weekdays | tradingview | daily-screens/{date}/pre-market-gapper.md |
| 9 | stock-screener-daily-sweep-18:30 | 18:30 ET weekdays | tradingview, shibui | daily-screens/{date}/daily-sweep.md |
| 10 | stock-screener-breadth-snapshot | intraday | tradingview | daily-screens/{date}/breadth-snapshot.md |
| 12 | cross-asset-correlation-snapshot | intraday | tradingview, yahoo | cross-asset/{date}.md |
| 13 | macro-calendar-midweek | Wednesday | web_search | macro-calendar/{date}-midweek.md |
| 14 | macro-calendar-week-ahead | Sunday | web_search | macro-calendar/{date}-week-ahead.md |
| 15 | earnings-reaction-scanner | intraday | yahoo, shibui | earnings/{date}-reactions.md |
| 16 | unusual-options-flow-daily | intraday | yahoo | options-flow/{date}.md |
| 17 | us-stocks-in-play | intraday | tradingview, yahoo | us-stocks-in-play/{date}.md |
| 19 | earnings-reminder-daily | 06:00 ET weekdays (`0 6 * * 1-5`) | web_search/web_fetch (no yahoo/shibui MCP in Cloud) | earnings/{date}-reminders.md |
| 20 | eod-watchlist-csv-snapshot | 16:00 ET weekdays | tradingview, yahoo | us-eod/{date}.csv |
| 22 | weekly-market-recap-preview | Friday | shibui, tradingview, yahoo | weekly/{date}-preview.md |
| 23 | agentic-post-market-brief | 16:30 ET weekdays | yahoo, tradingview, shibui, web_search | daily-briefs/{date}-post-market.md |
| 25 | ntrt-gap-brief-daily | morning | tradingview, yahoo | ntrt/{date}.md |
| 26 | agentic-pre-market-brief | 08:30 ET weekdays | yahoo, tradingview, web_search | daily-briefs/{date}-pre-market.md |
| 90 | delivery-auditor | 07:00 ET daily | (no MCP) | _audit/status.json → branch `audit/status` |

## Common header (every prompt has this)

- **Credential handling**: `${GITHUB_TOKEN}` only; never literal PAT. Token unset → skip push, write artifact, reply.
- **Zero-fallback policy**: every fallback MUST terminate with stop-and-write tiebreaker. No deeper MCP chains.
- **Helper scripts**: re-implement inline. Local Mavis Python helpers don't exist on Cloud. Fetch helper source for reference only.
- **Audit log**: skipped (not needed on Cloud).
- **Output**: `/workspace/<path>` (Linux-style, no backslashes).
- **Git push**: optional, to `minimax-cloud-outputs`.

## Common delivery format (no line cap)

The reply is a short, readable digest - not a wall of text. There is **no line cap**: cap by
NAMES SHOWN (top ~8 per tier), not by lines, and let the artifact file hold the long detail.

```
2-4 sentence prose opener (headline finding + the caveat that changes how it should be read)

### Signal
tiered bullets, one ticker per line, each line a short clause naming the catalyst

### Method & caveats
2-4 bullets: source(s), lag, screen size, degraded/blocked sources

### Files
one line per file written: /workspace/...

### Push / errors
push: ok | skipped | failed
errors: <count>
```

Three crons keep a fixed structured status reply by design (`07` focus-rvol twins,
`15` earnings-reaction-scanner, `90` delivery-auditor) - those are machine-readable status
blocks, not narrative digests, and are deliberately left alone.

## How to schedule

In agent.minimax.io (Cloud Mavis):
1. Open the crons UI (Schedules or Cron manager).
2. Create a new cron with the same schedule as the local version.
3. Paste the prompt body (or link to the file's `raw.githubusercontent.com` URL).
4. Set `deliver` to chat (default) or whatever the local equivalent was.
5. Test: run it once manually (skip the schedule, fire now), verify reply.

## Status

- [x] 20 prompts generated.
- [ ] Pasted into Cloud Mavis cron schedule (user action).
- [ ] Pilot #18 fires Sun 02:00 ET to verify env (sandbox persistence, /workspace/, MCPs, ${GITHUB_TOKEN} propagation).
- [ ] Each prompt run at least once for verification.
- [ ] Schedule timing adjusted to match Cloud cron session cadence (unknown until pilot replies).

## Dependencies on other buckets

- None. Bucket 1 crons are self-contained.
- Bucket 3 crons (#11, #21) handle backup/sync; once they're Cloud-ready, no further integration with Bucket 1 needed.
- Bucket 2 crons (none — see _classification.md) were a transient label.

## What's NOT in Bucket 1

- Local-only crons #1 (audit) and #3 (watchdog) — kept local.
- Cron #18 (pilot) — staged in `cloud-prompts/01-weekly-mcp-health-check.md` for Sun 02:00 ET.
- Crons #11, #21 (Bucket 3, git push) — staged once pilot confirms `${GITHUB_TOKEN}` works in cron sessions.
- Cron #24 (X audit) — redesign pending; see `cloud-prompts/24-x-following-audit-redesign-notes.md`.

## See also

- `../_classification.md` — bucket assignment rationale for all 26 crons
- `../01-weekly-mcp-health-check.md` — the pilot prompt (#18)
- `../skills/` — skill SKILL.md files mirrored from local Mavis


## Trigger conventions (applied 2026-10-25, extended 2026-10-28)

- **Put day-of-week in the cron expression**, not only in the prompt's window check. `0 6 * * 1-5`
  means the scheduler never fires on weekends, so no weekend SKIPPED file is written and no agent
  invocation is spent discovering it is a weekend. The in-prompt window check stays as a redundant
  guard and still handles US market holidays, which no cron expression can express.
  **Applied 2026-10-28 to crons #02, #04, #05, #08, #09, #20, #23, #25** (daily schedules that
  were weekday-only in intent). #16 was already `1-5` and is the template.
- **Use `session: new`** so each run starts a clean conversation. A task bound to one long-lived
  session (`sessionId`) contradicts the "fresh session each time" line every prompt carries, and
  leaks context between runs. All 20 are `new` as of 2026-10-28.
- **Always verify `timezone` after a `cron_update`.** An update that omits the timezone field can
  silently adopt the caller's local zone (observed: America/New_York -> Europe/Paris, which moved a
  06:00 ET job to 00:00 ET). Re-read the task after any schedule change.
- **Keep the cron expression's day-of-week and the prompt's `DAY_OF_WEEK` flag in step.** The cron
  field is `0=Sun..6=Sat`; the flag is compared against `date +%u`, which is `1=Mon..7=Sun`. They
  agree for Mon-Sat but **Sunday differs (cron 0 vs %u 7)**. A mismatch makes the routine skip
  every single fire. Cron #22 was exactly this bug (cron `* * 6` = Saturday, flag `5` = Friday)
  and has never produced an artifact.

## Runtime data-source contract (added 2026-10-28)

**The finance MCP tools named in these prompts do not exist in the Cloud runtime.** Verified on
the live sandbox: the connector catalog exposes 15 tools, all of them media/email
(`connector__matrix__*`, `connector__email_workbench_credentials__*`). There is no
`mcp__yahoo_finance__*`, `mcp__tradingview__*`, `mcp__shibui_finance__*`, `mcp__stocktwits__*`,
`mcp__financekit__*` or `mcp__web_search__*`, and no `extract_content_from_websites`.

Every prompt now carries a **RUNTIME DATA-SOURCE CONTRACT** section with a *tested* fallback
ladder (measured 2026-10-28 from the sandbox) and eight rules. Key findings:

- Yahoo's JSON endpoints (spark / chart / screener) return **HTTP 429** from this egress, with
  and without a browser User-Agent, and after a 60 s pause — persistent rate limiting, not a
  transient burst. Yahoo's *HTML* pages still work.
- `web_search` is the most reliable path and uses a **different egress** from curl, so it survives
  Yahoo blocking curl. It returned live SPY data (769.66 close, 2026-10-27) while Yahoo JSON was
  429. Try it FIRST.
- Working fallbacks measured 200: Nasdaq quote API, Yahoo HTML, CoinGecko, Frankfurter (FX),
  SEC EDGAR, US Treasury yield curve.
- A 429 is a **rate limit, not a missing symbol**. Never report "no data" for a symbol you never
  successfully queried.
- **Partial data beats no data.** Write the artifact with what resolved, mark the gaps, and
  report `errors: <n>`. The zero-fallback policy governs the fallback chain, not whether the
  artifact gets written.

## Push + delivery verification (rewritten 2026-10-28)

The old push block used `git add -A` in a fresh sandbox, which stages every other file on the
branch as DELETED. On 2026-10-25 cron #12's push (commit `1356a03`) did exactly that and deleted
283 files, wiping the artifacts of cron #19 and seven other crons plus the repo `.gitignore`.

The new block in all 20 prompts:
1. pins the sandbox CA cert and sets `HOME` before any git call;
2. fetches `origin/main` and creates a **git worktree** from it, so the full tree is present;
3. copies ONLY this cron's output dir into the worktree and stages ONLY that path;
4. **aborts** if `git status --short` shows any `D` entry, and **aborts** if nothing was staged
   (which is how a failed artifact copy is caught);
5. pushes `HEAD:main` — a fresh `git init` creates local `master`, so `origin main` is wrong;
6. then runs **DELIVERY VERIFICATION**: `git cat-file -e "origin/main:<path>"` to prove the
   artifact is actually on the remote, and reports `push: ok (verified)` or
   `push: FAILED (artifact absent on origin/main)`. A successful `git push` is not proof of
   delivery, and the old prompt could not tell the difference.

Validated end-to-end against the real repo on 2026-10-28: positive case reports `ok`, negative
case reports `FAILED`, and a real push left 1102 sibling files intact with no deletions.

## Cron #22 schedule correction (2026-10-28)

The original local cron of record was `47 17 * * 0` America/New_York — **Sunday 17:47 ET**, the
"Sunday evening sit-down" weekly brief (per `migration-state.json`, `cron-triage-full-2026-09-25.md`
and the skill's own `When` block). The Cloud deployment was `0 14 * * 6` (Saturday 14:00) while
the prompt's window check demanded Friday, so it skipped every fire and produced nothing.
Corrected to `47 17 * * 0` with `DAY_OF_WEEK=7`.
