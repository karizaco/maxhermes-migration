# Runtime watchdog — known gap

**TL;DR:** Today's Mavis local runtime has **no per-session timeout**. A cron
session that hangs (e.g., an Agent entering a decision loop) will sit in
`status: started, active-turn` indefinitely. The runtime returns `delivered`
in `cron sessions` even though the Agent has produced no output and never
will recover.

This is a known limitation of the runtime, not a bug in any single cron
or skill. Filed in MEMORY.md so future-me doesn't waste cycles
diagnosing it.

## How to detect a stuck session

The misleading signals:

| Signal | Meaning | What it tells you |
|---|---|---|
| `session get` returns `status: { type: "started" }` | Session framework accepted the prompt | Nothing about whether the Agent is actually doing work |
| `cron sessions` returns `status: "delivered"` | The framework handed the message to the Agent slot | Does NOT mean the Agent produced any output |
| `session send` returns `409 SESSION_BUSY` | `active-turn` is locked | The session is "in progress" — but if `active-turn` is held with no assistant message for >5 min, it's almost certainly stuck |

The only live check that actually reflects progress:

```
mavis session messages --session_id <sid> --limit 5
```

If the latest assistant message timestamp is >5 min old and `status`
is still `started`, the session is hung. The runtime has no
`SEND_INTERRUPT` or "kill stuck session" call in the current API.

## Workaround (until the runtime ships a watchdog)

1. **Prevent the hang at the prompt level.** Every cron prompt must end
   each fallback branch with an explicit "accept-and-stop" instruction.
   See `references/crons.md` reversal-bullish step 4 for the canonical
   example. This is the single highest-leverage fix; a directive prompt
   keeps the Agent from entering the decision loop in the first place.

2. **Manual cleanup of stuck sessions.** When a hung session is detected:
   ```
   mavis session send --session_id <sid> --content "stop and archive"
   ```
   will fail with `409 SESSION_BUSY` (the session is locked). There is no
   current way to force-terminate from the CLI. The session will eventually
   time out on the runtime's own schedule (unknown — observed ~hours).

3. **Use `cron trigger` to fire a fresh manual run.** This creates a new
   session. The runtime does not prevent new sessions from running even
   while an old one is locked. Verified 2026-09-21: fired reversal-bullish
   (`b5187e5c-…`) while the predecessor session was still in `active-turn`;
   the new run proceeded immediately on its own timeline. Older pre-2026
   runs reported runtime "queue caps" that blocked new triggers — that
   pattern has not been observed since, so it may have been a one-off.

4. **For enterprise-grade recovery:** file a feature request with the
   Mavis runtime team for `cron update --max-runtime-minutes <N>` or
   `session stop --session_id <sid>`. Both are needed for production
   safety; neither exists today.

## Concrete reminders

- 2026-09-21 reversal-bullish cron (`b5187e5c-…`): Agent entered a
  decision loop trying to decide between accepting the Finviz fallback
  vs chaining per-ticker yahoo-finance for OHLC. The decision logic
  itself was correct (Finviz doesn't have OHLC); the prompt was ambiguous.
  Lesson is in MEMORY.md as "Cron prompts must be directive".

- 2026-09-21 daily-sweep (`1fe85f1b-…`): ran fine end-to-end; observed
  `status: started` for ~12 min before `idle` appeared. THIS IS NORMAL —
  ~12 min is the expected runtime for ~12 MCP calls + consume. Don't
  intervene unless the session has been `started` >30 min with the same
  `updatedAt` and no new assistant message.

## What "normal" looks like

A healthy cron session timeline:

| Stage | Expected elapsed time | Status |
|---|---|---|
| `cron trigger` → session created | <5 s | `pending` → `delivered` |
| Skill loaded + plan emit | 5-30 s | `started` |
| MCP batch 1 (3 shibui calls parallel) | 5-15 s | `started` |
| MCP batch 2 (3 shibui calls parallel) | 5-15 s | `started` |
| MCP batch 3 (3 TV calls parallel) | 5-15 s | `started` |
| MCP batch 4 (4 parallel breadth + VIX + sector) | 5-15 s | `started` |
| Consume + write 13 files | 2-5 s | `started` |
| Return summary | <1 s | `idle` |
| **Total** | **~60-120 s for normal daily-sweep** | |

Reversal-bullish is shorter (~30-60 s). Anything >5 min with the same
`started` updatedAt is suspicious; >15 min is virtually always hung.
