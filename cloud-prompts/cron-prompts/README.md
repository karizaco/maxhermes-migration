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
| 19 | earnings-reminder-daily | morning | yahoo, shibui | earnings/{date}-reminders.md |
| 20 | eod-watchlist-csv-snapshot | 16:00 ET weekdays | tradingview, yahoo | us-eod/{date}.csv |
| 22 | weekly-market-recap-preview | Friday | shibui, tradingview, yahoo | weekly/{date}-preview.md |
| 23 | agentic-post-market-brief | 16:30 ET weekdays | yahoo, tradingview, shibui, web_search | daily-briefs/{date}-post-market.md |
| 25 | ntrt-gap-brief-daily | morning | tradingview, yahoo | ntrt/{date}.md |
| 26 | agentic-pre-market-brief | 08:30 ET weekdays | yahoo, tradingview, web_search | daily-briefs/{date}-pre-market.md |

## Common header (every prompt has this)

- **Credential handling**: `${GITHUB_TOKEN}` only; never literal PAT. Token unset → skip push, write artifact, reply.
- **Zero-fallback policy**: every fallback MUST terminate with stop-and-write tiebreaker. No deeper MCP chains.
- **Helper scripts**: re-implement inline. Local Mavis Python helpers don't exist on Cloud. Fetch helper source for reference only.
- **Audit log**: skipped (not needed on Cloud).
- **Output**: `/workspace/<path>` (Linux-style, no backslashes).
- **Git push**: optional, to `minimax-cloud-outputs`.

## Common delivery format (≤ N lines)

```
top movers / counts / source / lag (if any)
file 1 written: /workspace/...
file 2 written: /workspace/...
push: ok | skipped | failed
errors: <count>
```

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
