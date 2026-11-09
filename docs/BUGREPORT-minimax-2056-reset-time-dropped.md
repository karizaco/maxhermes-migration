# Bug report — the Token Plan 2056 error drops the window's reset time, so a blocked fire cannot say when it recovers

**Submit via:** the app's **Feedback** dialog (user menu → Help, or a task's top bar, or a
session in the sidebar — it auto-attaches task context and diagnostics), or email
**MiniMaxCode@minimax.io** (per the MiniMax AI App and Web Terms of Service).

**Title:** API error 2056 (Token Plan 5-hour usage limit) is surfaced without the window's reset
time, so a blocked scheduled fire cannot report when it will recover

**Severity:** Medium — the platform's own error is accurate but incomplete, and the missing
field is the one an automated agent needs to schedule around it

---

## Summary

When the Token Plan 5-hour usage window is exhausted, the MiniMax API returns HTTP 429 with
error code **2056** and a body that includes the moment the window frees:

```
HTTP 429: usage limit exceeded, 5-hour usage limit reached for Token Plan Starter
(0/0 used), resets at 2026-05-15T15:00:00Z (2056)
```

The agent platform surfaces that error to the session as a flat, reformatted string:

```
42212: Token Plan usage limit reached: Upgrade your Token Plan or purchase Credits
for more usage. (2056)
```

**The reset timestamp is dropped.** So does any remaining-quota percentage, if the API returned
one. The surfaced message tells the agent that it is blocked and nothing about when the block
ends.

## Why it matters

A scheduled agent that is blocked cannot plan around the block, because the one field that
would let it plan — "the window frees at 14:35 ET" — is discarded before the agent sees it.
The practical consequence is that the only way to learn when quota returns is to watch which
sessions resume, which on 2026-11-05 took a full morning to establish.

Measured on 2026-11-05 (a Token Plan account running a 21-routine cron fleet):

| Fire (ET) | Routine | Outcome |
|---|---|---|
| 08:30 | #26 morning brief, #92a pre-open checkpoint, #08 pre-market gapper | Turn rejected at its first model call; #26 and #08 were resumed in place and published 21.4 h later |
| 09:00 | #25 ntrt gap brief | Resumed 10:08 ET, published 10:15 ET |
| 09:20 | #26b pre-market refresh | Resumed 10:08 ET, published 10:15 ET |
| 09:45 | #07 focus-rvol, #10 breadth snapshot | Resumed 10:44 ET / 14:06 ET |
| 09:50 | #92b pre-open checkpoint | Resumed ~10:13 ET, published 10:14 ET |

The window's actual release time was therefore knowable at 08:30 ET and was not available to
any of the blocked routines.

## Steps to reproduce

1. Fill a Token Plan account's 5-hour usage window (or wait for one that is exhausted).
2. Let a scheduled task fire.
3. Read the session's last message: `session_messages` on the session the cron run created.
4. Observe that the message carries the code (`2056`) and the marketing text, and no reset time.

## Expected behaviour

The surfaced error should preserve the reset time from the API body, e.g.

```
42212: Token Plan usage limit reached: Upgrade your Token Plan or purchase Credits
for more usage. (2056) — the 5-hour window frees at 2026-11-05T14:35:00Z (10:35 ET)
```

Ideally the remaining-quota percentage for the 5-hour and weekly windows would survive too, so
an agent can decide to trim its work rather than merely report that it is blocked.

## Suggested remedy

Whatever layer rewrites the provider's error into the `42212: …` form should carry the upstream
`resets at <timestamp>` clause through unchanged. The information is already in the API
response; it is lost in formatting, not in retrieval.
