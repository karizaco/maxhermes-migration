# Thresholds — rationale and tuning

| Age | Action | Why |
|---|---|---|
| 0-30 min | none | Normal. Daily-sweep tops out around 12 min, weekly brief 5 min, breadth 3 min. |
| 30-120 min | WARN only | Suspicious. Could be a legit long task (backtest, deep research brief) or a zombie. Log it, don't touch it. |
| 120+ min | AUTO-ARCHIVE | Almost certainly a zombie. Even the slowest 2026-09 cron task took <30 min end-to-end. Anything past 2 h is hung. |

## Why 30 min for WARN?

Daily-sweep (`1fe85f1b…`) makes 11 MCP calls + consume + 13 file writes.
Observed runtime on 2026-09-21: 12 min from `cron trigger` to `idle`. The
`started` status stayed on longer (timer started at session creation, not
at Agent turn start), so a 25-30 min `started` is always either deep
work or a hang. 30 min gives headroom for slower networks.

## Why 120 min for AUTO-ARCHIVE?

Conservative — leaves room for:
- A user manually running the smoke-test script via `agent` mode (~60-90 min)
- A weekly brief with chart rendering (~30-45 min)
- A future addition (pattern-study full backfill could be 1-2 hours)

Past 120 min, the cost of a false positive (killing a real task) is
outweighed by the cost of a false negative (zombie consumes runtime
memory and confuses future `session list` queries).

## What if a cron legitimately needs >2 hours?

Two options:
1. **Don't use cron for it** — switch to a manual / on-demand Agent run.
2. **Edit the threshold in this file** — bump the archive age up before
   triggering that cron next time. The thresholds live in the SKILL.md
   "Steps" section for the watchdog Agent to read; no code is involved.

## Re-trigger policy

Re-trigger only fires AFTER a successful archive (not after WARN). The
rationale: if the watchdog couldn't archive (because of 409
SESSION_BUSY), the zombie is still consuming the runtime slot —
re-triggering would just create another zombie on top of it. Wait for
the runtime to garbage-collect the original, then the next natural cron
fire will run cleanly. Manual user trigger is the only safe re-trigger
while a zombie is locked.
