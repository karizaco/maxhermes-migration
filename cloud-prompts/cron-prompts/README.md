# Cloud Mavis Cron Prompts — index and operating notes

**20 routines**, all owned by `Mavis`, all `America/New_York`, all `MiniMax-M3.1-Flash`,
all `session.mode=new`. Day-of-week lives in the **scheduler** expression, so weekend fires cost
nothing — no agent invocation is spent discovering it is a weekend.

> This index is generated from live scheduler state. See `cron-prompts/ROSTER.md` for the
> machine-generated roster with last-delivered dates, and `tools/gen_roster.py` to rebuild it.

## Cron index

| ID | Routine | Schedule (ET) | Fires on | Project | Output |
|---|---|---|---|---|---|
| 19 | earnings-reminder-daily | `0 6 * * 1` | Mon | 13835 | `earnings/{date}-reminders.md` |
| 02 | asia-pre-market-reactions | `30 6 * * 1-5` | Mon-Fri | 10645 | `asia-pre-market/{date}.md` |
| 15 | earnings-reaction-scanner | `0 8 * * 1` | Mon | 13835 | `earnings/{date}-reactions.md` |
| 08 | stock-screener-pre-market-gapper | `30 8 * * 1-5` | Mon-Fri | 10635 | `daily-screens/{date}/pre-market-gapper.md` |
| 26 | agentic-pre-market-brief | `30 8 * * *` | every day | 10645 | `daily-briefs/{date}-pre-market.md` |
| 25 | ntrt-gap-brief-daily | `0 9 * * 1-5` | Mon-Fri | 10635 | `ntrt/{date}.md` |
| 07 | stock-screener-focus-rvol-09:45 | `45 9 * * *` | every day | 10635 | `daily-screens/{date}/focus-rvol-snapshot.md` |
| 12 | cross-asset-correlation-snapshot | `0 10 * * *` | every day | 10636 | `cross-asset/{date}.md` |
| 10 | stock-screener-breadth-snapshot | `0 14 * * *` | every day | 10635 | `daily-screens/{date}/breadth-snapshot.md` |
| 13 | macro-calendar-midweek | `0 14 * * 3` | Wed | 10636 | `macro-calendar/{date}-midweek.md` |
| 06 | stock-screener-pattern-study-backlog | `0 15 * * 6` | Sat | 10635 | `daily-screens/{date}/weekly-ipo.md` |
| 14 | macro-calendar-week-ahead | `0 15 * * 0` | Sun | 10636 | `macro-calendar/{date}-week-ahead.md` |
| 17 | us-stocks-in-play | `50 15 * * *` | every day | 10645 | `us-stocks-in-play/{date}.md` |
| 04 | reversal-bullish-3:55 | `55 15 * * 1-5` | Mon-Fri | 10635 | `daily-screens/{date}/reversal-bullish-3:55.md` |
| 20 | eod-watchlist-csv-snapshot | `0 16 * * 1-5` | Mon-Fri | 10638 | `us-eod/{date}.csv` |
| 05 | eod-international-daily | `30 16 * * 1-5` | Mon-Fri | 10635 | `international-eod/{date}/` |
| 16 | unusual-options-flow-daily | `35 16 * * 1-5` | Mon-Fri | 13832 | `options-flow/{date}.md` |
| 22 | weekly-market-recap-preview | `47 17 * * 0` | Sun | 10638 | `weekly/{date}-preview.md` |
| 09 | stock-screener-daily-sweep-18:30 | `30 18 * * 1-5` | Mon-Fri | 10635 | `daily-screens/{date}/daily-sweep.md` |
| 23 | agentic-post-market-brief | `30 22 * * 1-5` | Mon-Fri | 10635 | `daily-briefs/{date}-post-market.md` |

## Common contract (every prompt)

- **Credential handling**: `${GITHUB_TOKEN}` only; never a literal PAT. Token unset → skip the push,
  write the artifact, reply.
- **Data sources**: the `mcp__*` tool names are NOT registered in this runtime. The MCP *servers* are
  reachable over plain HTTPS JSON-RPC via `_shared/mcp_bridge.py`. Yahoo JSON endpoints return
  persistent 429; `web_search` (separate egress) and the Nasdaq API work. Full endpoint list and
  measured status: `_shared/RUNTIME-CONTRACT.md`.
- **Zero-fallback policy**: every fallback terminates with stop-and-write. No deeper MCP chains.
- **Helper scripts**: local Windows Python helpers do not exist on Cloud. Re-implement inline; fetch
  the helper source for reference only.
- **Output**: `/workspace/<path>` (Linux paths, no backslashes).
- **Git push**: worktree at `origin/main`, `git add <own-dir>` only, 3-attempt race retry, then a
  mandatory `git cat-file` delivery check. A push that reports success but lands nothing is worse
  than a push that fails loudly.

## Reply format (no line cap)

The reply is a short, readable digest, not a wall of text. There is **no line cap**: cap by NAMES
SHOWN (top ~8 per tier), not by lines, and let the artifact file hold the long detail.

```
2-4 sentence prose opener (headline finding + the caveat that changes how it should be read)

### Signal
tiered bullets, one ticker per line, each a short clause naming the catalyst

### Method & caveats
2-4 bullets: source(s), lag, screen size, degraded/blocked sources

### Files
one line per file written

### Push / errors
push: ok (verified) | skipped (token unset) | FAILED (<reason>)
errors: <n>
```

## Repository rules (read before pushing)

- **Push to `main`, never `master`.** `origin/HEAD` points at `master`, so a plain `git clone` lands
  on the wrong branch — always `git fetch origin main` explicitly.
- **Never `git add -A`.** In a fresh sandbox the working tree lacks the rest of the repo, so a blanket
  add stages every other file as DELETED. Cron #12 did exactly that on 2026-10-25 (commit
  `1356a03`) and deleted 283 files belonging to eight other crons.
- **Never `git push --force`.**
- **One owner per output directory.** `_regime.json` was written by both #10 and #09 and silently
  clobbered; #10 now writes `_regime-intraday.json`.
- **Auditor #90 writes to the `audit/status` branch**, never `main`.

## Known hazards

- **Push collisions.** Routines that share a fire minute push to the same branch; the loser is
  rejected and its artifact is lost. Staggered pairs are 16:30 #05 / 16:35 #16 (moved 2026-10-29),
  08:30 #08 / #26, 14:00 #10 / #13, 15:00 #06 / #14. The retry loop is the safety net, not the fix.
- **The auditor is blind to a routine that never fires** — it compared only against the audited
  day. STEP 4b (added 2026-10-29) does an absolute last-delivered check, which is what catches
  the #22 class of failure.
- **Quota.** Runs die with `Token Plan usage limit reached (2067)` when the account plan is
  exhausted. No prompt edit fixes that.

