# Cron triage — 2026-09-25 (FULL, all 26)

Source: `user_input_files/cron-list-triage-2026-09-25.json` (26/26 captured from `mavis cron get`).

## Full inventory

| # | Cron | Sched | TZ | Project | Re-trig | Local-keep? | Cloud? |
|---|------|-------|----|---------|---------|-------------|--------|
| 1 | Audit log daily backup | `55 23 * * *` | America/New_York | coding-shared | ✓ | yes | **yes** |
| 2 | Asia pre-market reactions (06:30 ET) | `30 6 * * 1-5` | America/New_York | virtual-assistant | — | — | **yes** |
| 3 | [CRON] Watchdog Stock-screener (hourly) | `0 * * * *` | **(missing TZ — defaults UTC?)** | virtual-assistant | ✓ | — | **yes — but TZ bug matters on Cloud** |
| 4 | Reversal bullish screener (15:55 ET) | `55 15 * * 1-5` | America/New_York | technical | ✓ | — | **yes** |
| 5 | Daily EOD international pull | `35 16 * * 1-5` | America/New_York | coding-shared | — | — | **yes** |
| 6 | Stock-screener pattern-study backlog (Sat) | `0 10 * * 6` | America/New_York | technical | ✓ | — | **yes** |
| 7 | Stock-screener focus RVOL rerank 09:45 | `45 9 * * 1-5` | America/New_York | technical | ✓ | — | **yes** |
| 8 | Stock-screener pre-market gapper (09:00 ET) | `0 9 * * 1-5` | America/New_York | technical | ✓ | — | **yes** |
| 9 | Stock-screener daily sweep (18:30 ET) | `30 18 * * 1-5` | America/New_York | technical | ✓ | — | **yes** |
| 10 | Stock-screener breadth snapshot (06:30 ET) | `30 6 * * 1-5` | America/New_York | technical | ✓ | — | **yes** |
| 11 | Daily mavis-runtime backup | `5 18 * * *` | Asia/Bangkok | coding-shared | ✓ | **yes** | backup target = local Mavis state, not Cloud. **Keep local.** |
| 12 | Cross-asset correlation snapshot | `30 16 * * 0` | America/New_York | virtual-assistant | — | — | **yes** |
| 13 | Macro calendar — midweek refresh (Wed) | `0 13 * * 3` | America/New_York | virtual-assistant | — | — | **yes** |
| 14 | Macro calendar — week ahead (Sunday) | `0 16 * * 0` | America/New_York | virtual-assistant | — | — | **yes** |
| 15 | Earnings reaction scanner | `0 8 * * 1-5` | America/New_York | virtual-assistant | — | — | **yes** |
| 16 | Unusual options flow daily | `55 9 * * 1-5` | America/New_York | virtual-assistant | — | — | **yes** |
| 17 | US stocks in play — 09:50 ET open slot | `50 9 * * 1-5` | America/New_York | virtual-assistant | — | — | **yes** |
| 18 | Weekly MCP and API health check | `0 2 * * 0` | America/New_York | coding-shared | — | — | **yes (pilot)** |
| 19 | Daily earnings reminder | `0 6 * * 1-5` | America/New_York | coding-shared | ✓ | — | **yes** |
| 20 | Daily EOD watchlist CSV snapshot | `30 16 * * 1-5` | America/New_York | coding-shared | ✓ | — | **yes** |
| 21 | Daily agent-ops sync | `0 18 * * 0-6` | Asia/Bangkok | coding-shared | ✓ | — | **yes (this is repo sync)** |
| 22 | Weekly market recap and preview | `47 17 * * 0` | America/New_York | coding-shared | ✓ | — | **yes** |
| 23 | Daily agentic post-market brief | `35 22 * * 1-5` | **(missing TZ)** | coding-shared | ✓ | — | **yes — TZ bug must be fixed on Cloud** |
| 24 | Weekly X following audit | `0 10 * * 0` | Asia/Bangkok | coding-shared | — | — | **yes** |
| 25 | Daily NTRT gap brief | `30 6 * * 1-5` | America/New_York | coding-shared | ✓ | — | **yes** |
| 26 | Daily agentic pre-market brief | `37 7 * * 1-5` | America/New_York | coding-shared | ✓ | — | **yes** |

## What changed vs. earlier triage

Earlier I had only 16. The new 10 are:

- **5 stock-screener crons** (07, 08, 09, 10) — all in `technical` project, all marked re-trigger-eligible, all stock-screener-suite skill. These are the bulk of the "missing" 10.
- **Daily mavis-runtime backup** (11) — interesting one. This is a BACKUP of Mavis's own runtime state (the cron metadata, sessions, etc.). It needs to STAY LOCAL because its job is to back up local state. This is a local-only cron by design.
- **Cross-asset correlation** (12) — virtual-assistant
- **Macro calendar midweek + week-ahead** (13, 14) — virtual-assistant
- **Earnings reaction scanner** (15) — virtual-assistant, 08:00 ET
- **Unusual options flow** (16) — virtual-assistant, 09:55 ET

## Bugs spotted in the captured data

1. **Cron #3 (`[CRON] Watchdog Stock-screener (hourly)`) is missing `timezone` field**. Schedule is `0 * * * *` with no TZ. On the local Mavis runtime, this is presumably UTC (since `agent.minimax.io` defaults to UTC for unspecified TZ). On Cloud, that could matter — if Cloud defaults to UTC too, no change. **Flag for verification when staging.**
2. **Cron #23 (`Daily agentic post-market brief`) is also missing `timezone`**. Schedule is `35 22 * * 1-5` — 22:35 every weekday. If that's UTC, then it's 17:35 ET (4:35pm) which doesn't match the post-market timing. If it's "intended ET but field got dropped", then 22:35 ET is post-market close. **Either the prompt's intent is ET and the field got dropped (bug), or the runtime is interpreting it as UTC and it's actually 17:35 ET (early). Flag for verification.**
3. The 16 captured previously all matched these 26 perfectly — no drift in cron IDs, names, or schedules.

## Decisions per cron

### Local Mavis — STAY (1 cron)

- **#11 Daily mavis-runtime backup** — backups local Mavis state. The backup target itself IS local Mavis state. Has no meaning on Cloud.

### Minimax Cloud — MIGRATE (25 crons)

All others. Reasons:
- Daily market digests, scheduled jobs — need to fire whether or not laptop is asleep
- The 5 stock-screener crons in `technical` are the heaviest compute and would benefit most from Cloud's reliability
- The watchdog cron (#3) is hourly and is the most painful when missed — laptop sleep means hours of missed fires

### MaxHermes (me) — NONE of these

None of the 26 are well-suited to me specifically. They all need:
- Delivery to your sidebar (visible)
- Repeated fire at specific market times
- A consistent identity with the rest of your cron roster

If you want a "MaxHermes-special" cron later, candidates would be:
- A "skill quality auditor" that periodically runs each skill with a rubric
- A "cron health dashboard" that aggregates output files and surfaces anomalies
- A "self-improving experiment runner" that tries prompt variations and reports results

These aren't on the migration list. They're separate.

## Re-trigger sentinel coverage

Of the 26, **15 carry the `# watchdog: re_trigger_eligible=true` sentinel**. The 11 that don't are:
- #2 Asia pre-market reactions
- #5 Daily EOD international pull
- #12 Cross-asset correlation
- #13 Macro calendar midweek
- #14 Macro calendar week-ahead
- #15 Earnings reaction scanner
- #16 Unusual options flow
- #17 US stocks in play
- #18 Weekly MCP health check
- #24 Weekly X following audit
- #11 Daily mavis-runtime backup (correctly NOT eligible — it backs up Mavis itself)

This means: when the watchdog fires and a cron has gone zombie, it can re-trigger only 15 of the 26. The 11 are "stuck-archive-only" — if they die, they stay dead until the next scheduled run.

**Question for you**: do you want to add the sentinel to all 26? It's a one-line edit per cron. If yes, I'll batch that edit into the cloud-prompts staging so when you migrate, the new prompts have it.

## Action items now

1. **Verify Cloud TZ behavior for #3 and #23** — run a one-off test cron at `35 22 * * 1-5` with no TZ on Cloud, see what fires.
2. **Re-stake all 25 cloud cron prompts** — I have the source prompts in the JSON. I can build the cloud version directly from them, applying MEMORY.md rules (especially directive tiebreakers, silence-by-default where appropriate).
3. **Add the watchdog sentinel to the 11 crons that lack it** — confirm with you first.
4. **The pilot cron (#18) is still the right pilot** — simplest, lowest risk. But now I have richer material, so I'll stage the audit cron (#1) as a SECOND pilot right after, since it's also "silent-by-default" and tests the watchdog-sentinel pattern.

## Quick order to stage cloud prompts

Ranked by risk/reward (easiest first):

1. **#18 Weekly MCP health check** — already staged (pilot). ✅
2. **#1 Audit log daily backup** — silent-by-default, single bash call. Tests directive tiebreakers.
3. **#11 Daily mavis-runtime backup** — wait, this stays LOCAL. Skip.
4. **#19 Daily earnings reminder** — pure content producer, simple.
5. **#20 Daily EOD watchlist CSV snapshot** — content producer + watchdog sentinel.
6. **#21 Daily agent-ops sync** — git push + agent-ops file mgmt.
7. **#24 Weekly X following audit** — social audit, low stakes.
8. **#14, #13 Macro calendar** — content, midweek + weekly cadence.
9. **#25, #26, #15 Pre-market cluster** — overlapping briefs. May consolidate.
10. **#23, #12, #5 Post-market cluster** — TZ bug needs resolution.
11. **#2 Asia pre-market** — already has rich prompt body, lower rewrite effort.
12. **#22 Weekly market recap** — heaviest content brief.
13. **#4, #6, #7, #8, #9, #10 Stock-screener crons** — heaviest compute, hardest to reproduce on Cloud (TradingView-Advanced MCP needs uv/uvx binary swap; needs verification).
14. **#3 Watchdog** — should be LAST because the watchdog's job is to fix the others; you only want it on Cloud once the others are stable.
15. **#16, #17 Unusual options / US-stocks-in-play** — medium complexity, content producers.
