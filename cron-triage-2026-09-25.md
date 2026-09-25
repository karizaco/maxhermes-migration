# Cron triage — 2026-09-25

Source: `migration-state.json` (16 of 26 captured; remaining 10 truncated by display limit).

## Decision matrix

Decision rules:
- **Minimax Cloud** = visible in sidebar, survives laptop sleep. Default for anything scheduled.
- **Local Mavis** = interactive use only. Stays here only if it needs Windows-only MCPs (TradingView-Advanced, FinanceKit, Discord, Finviz w/ Playwright) or local file access.
- **MaxHermes (me)** = backend work that's invisible to you. Useful when the work is heavy compute, parallelizable, or experimental/self-improving.

MCP cloud-portability (from `mcp-state.json`):
- `tradingview`, `yahoo-finance`, `shibui-finance`, `stocktwits` → fully portable
- `tradingview-advanced`, `financekit` → need Linux `uv`/`uvx` (portable with binary swap)
- `deepgram-stt` → portable IF Python + DEEPGRAM_API_KEY env available
- `finviz` → portable IF Playwright browser binaries installed
- `discord` → DO NOT PORT (requires local Discord desktop client)

## Per-cron triage

| # | Cron | Sched | TZ | Project | Skill | Recommendation | Notes |
|---|------|-------|----|---------|-------|----------------|-------|
| 1 | Audit log daily backup | `55 23 * * *` | America/New_York | coding-shared | (ad-hoc) | **Minimax Cloud** | Cheap, daily, local file write — doesn't need laptop at all. Output goes to its own storage. |
| 2 | Asia pre-market reactions | `30 6 * * 1-5` | America/New_York | virtual-assistant | asia-pre-market-reactions | **Minimax Cloud** | Time-sensitive (06:30 ET = 18:30 Bangkok). Desktop rarely awake that early in user's TZ. Must be Cloud. |
| 3 | Watchdog Stock-screener (hourly) | `0 * * * *` | UTC | virtual-assistant | cron-watchdog | **Minimax Cloud** | Critical defensive cron. Hourly cadence needs reliability. |
| 4 | Reversal bullish screener | `55 15 * * 1-5` | America/New_York | technical | stock-screener-suite | **Minimax Cloud** | Heavy compute (screener + ranking). Late-afternoon ET, hits the +6h22m bug locally. |
| 5 | Daily EOD international pull | `35 16 * * 1-5` | America/New_York | coding-shared | (uses shibui/stocktwits) | **Minimax Cloud** | **Known zombie** locally (75-min runs that hang). Cloud has clean timeout/retry. |
| 6 | Stock-screener pattern-study backlog (Saturday) | `0 10 * * 6` | America/New_York | (none) | stock-screener-suite | **Minimax Cloud** | Weekly batch, idle compute. Perfect for Cloud. |
| 7 | Weekly MCP and API health check | `0 2 * * 0` | America/New_York | coding-shared | mcp-api-health-check | **Minimax Cloud** | Sunday 2 AM ET. Should be invisible to user anyway. |
| 8 | Daily earnings reminder | `0 6 * * 1-5` | America/New_York | coding-shared | earnings-reminder | **Minimax Cloud** | 06:00 ET morning brief. Laptop asleep. |
| 9 | Daily EOD watchlist CSV snapshot | `30 16 * * 1-5` | America/New_York | coding-shared | eod-watchlist-snapshot | **Minimax Cloud** | Late-afternoon. Hits +6h22m bug. |
| 10 | Daily agent-ops sync | `0 18 * * 0-6` | Asia/Bangkok | coding-shared | agent-ops-sync | **Minimax Cloud** | 18:00 Bangkok = 07:00 ET (or 06:00 EST). Daily git push to repo. |
| 11 | Weekly market recap and preview | `47 17 * * 0` | America/New_York | coding-shared | agentic-weekly-brief | **Minimax Cloud** | Sunday 17:47 ET. |
| 12 | Daily agentic post-market brief | `35 22 * * 1-5` | UTC | coding-shared | agentic-post-market-brief | **Minimax Cloud** | **Known broken locally** (+6h22m late, Desktop pause bug). Cloud fixes it. |
| 13 | Weekly X following audit | `0 10 * * 0` | Asia/Bangkok | coding-shared | x-following-audit | **Minimax Cloud** | Sunday 10 AM Bangkok. |
| 14 | Daily NTRT gap brief | `30 6 * * 1-5` | America/New_York | coding-shared | ntrt-gap-brief | **Minimax Cloud** | Pre-market. Same pattern as #2. |
| 15 | Daily agentic pre-market brief | `37 7 * * 1-5` | America/New_York | coding-shared | agentic-pre-market-brief | **Minimax Cloud** | Pre-market. Watch whole US market, not watchlist (per MEMORY.md rule). |
| 16 | us-stocks-in-play open slot | `50 9 * * 1-5` | America/New_York | virtual-assistant | us-stocks-in-play | **Minimax Cloud** | 09:50 ET open. |

## Summary

- **Minimax Cloud: 16/16 captured crons** (all of them, assuming MCP portability fixed)
- **Local Mavis: 0 crons need to stay** (none captured rely on Windows-only MCPs)
- **MaxHermes: 0 of these captured crons** (none are well-suited to me — they're all scheduled market workflows that need visibility in your sidebar)

## Notes on the 10 truncated crons

The 10 truncated crons are visible in the harness only as a count, not as metadata. They'll be revealed when `mavis cron list --limit 100` is run locally. Expected to be similar patterns (more trading-related scheduled tasks).

## Self-improving candidates (for MaxHermes, if any)

None of the captured crons are good "self-improving loop" candidates because:
1. They produce daily market digests — the goalposts (market behavior) shift daily; can't optimize for "right answer"
2. They have specific time windows tied to market hours — no benefit from more frequent runs
3. They're time-sensitive: a "self-improving" run at the wrong time is useless

If you want me to do self-improving work, better candidates would be:
- A "skill quality audit" cron that periodically checks skill outputs against a rubric
- A "cron health dashboard" generator that aggregates output files and surfaces anomalies
- The agent-ops-sync skill itself, if you want me to take ownership of git pushes (currently cron #10)

## Redundancies spotted

- `Daily agentic pre-market brief` (#15) + `Daily NTRT gap brief` (#14) + `Daily earnings reminder` (#8) all fire in the 06:00–07:40 ET window. Likely significant overlap. Worth a manual review to see if they could be consolidated into a single morning brief.
- `Daily agentic post-market brief` (#12) + `Daily EOD international pull` (#5) + `Daily EOD watchlist CSV snapshot` (#9) all fire in the 16:30–16:35 ET window. Also likely overlap.

## Action items

1. **Confirm MCP portability** — can Minimax Cloud install `uv`/`uvx` and Playwright? If yes, all 16 captured crons port cleanly.
2. **Get the truncated 10 crons** — run `mavis cron list --limit 100` locally, append to `migration-state.json`, re-triage.
3. **Reconcile `agent-ops` vs `maxhermes-migration`** — `agent-ops` has 45 skills, `maxhermes-migration` has 20. Confirm the 20 in `skills-original/` are the canonical ones (they match cron names 1:1, so they probably are) and the other 25 are utility/admin/reference skills that don't run on cron.
4. **Build cron prompts on Minimax Cloud** — use the prompts in `skills-original/` as the source-of-truth. Apply MEMORY.md rules (directive not exploratory, watch whole market not just watchlist, etc.).
5. **Verify +6h22m fix on Cloud** — the Desktop pause bug is Mavis-specific, but Cloud has its own quirks. Run for 3–5 days and confirm ET-time firing.
