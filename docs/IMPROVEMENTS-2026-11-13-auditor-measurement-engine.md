# IMPROVEMENTS — 2026-11-13 — cron #90's measurement engine, the cause vocabulary and the byte-level delivery check

**Why this document exists:** the 2026-11-12 07:00 ET audit (of 2026-11-11) was measured
after the fact and found to be carrying ~70 s of avoidable work and ~90 KB of avoidable
context, while missing two findings it could have made for free. This note records what
changed and why, so the next reader does not have to re-derive it.

**How it lands:** every change below is in a file that is fetched at RUN time — the
procedure, the contract, the gate, the new engine, the shared verify helper. So all of it
reaches the next 07:00 ET fire with **NO `cron_update` and NO prompt drift**. The deployed
prompt (the reply format's owner) is untouched.

---

## 1. What the 2026-11-12 run actually cost

| slice | time | avoidable? |
|---|---|---|
| dispatch → first tool call | 54.4 s | no — platform-side prefill of 32.6k tokens + first token |
| model thinking (43 assistant turns) | 72.7 s | partly — much of it spent re-reading |
| clone + **full checkout of 1,936 files** | 23.9 s | **yes** — the audit never reads a file from disk |
| the tools fetch (8 files × 3 URLs) | 5.7 s | no |
| path checks + the staleness loop (27 `git ls-tree` walks) | 12.6 s | **yes** — one walk does it |
| recovering the 462 KB `cron_read` payload by exploration | 11.8 s | **yes** — one documented command |
| reading the gate's own 27 KB source | 21 s | **yes** — the gate prints its failures |
| the push + delivery verification | 10.8 s | no |

Total 245 s wall, ~44 tool calls, ~142k tokens of context for a fully deterministic
comparison.

## 2. `tools/auditor_metrics.py` — the measurement engine (NEW)

The audit's *measurements* are arithmetic over the git history: is the artifact there, when
was it first added, how stale is the newest one, is the file real or a stub. The audit's
*judgements* need evidence a script cannot see: session status messages, skip markers,
platform run records.

**The engine measures; the agent judges.** It does ONE tree walk and ONE history walk for
the whole audit, and prints a table with `state_hint`, `present`, `near_miss`,
`delivery_latency_min`, `last_delivered`/`age_days`/`stale`, `health`, `market_closed`,
`notes` and the prior audit's streaks/latencies.

**No new copy of the roster:** the paths, tolerances and first-fire dates come from
`tools/gen_roster.py` (`ARTIFACTS`/`TOLERANCE`/`NOT_YET_FIRED`/`SLOTS`), the schedules from
`tools/schedule-ground-truth.json`, and the row names from the procedure's own STEP 4
table — the same three sources the roster check already compares.

**It cross-checks them.** A table row whose schedule disagrees with the ground truth is
reported as `ROSTER_DESYNC` in the notes. The rule is deliberately strict: a slot row of a
twice-daily task is compatible, a Wednesday-only row for a Mon-Fri task is NOT — that
desync would make the audit call four days of fires `not_due` and never look for them.

**Validated against two published audits:** for 2026-11-11 it reproduces every published
latency (14.8 / 14.4 / 26.4 / 15.2 / 5.6 / 27.2 / 26.6 / 13.0 / 9.9 / 7.2 / 18.0 / 3.9 /
3.3 / 5.7 / 33.3 / 37.5 / 46.1 / 14.8 / 1.4 / 11.4 / 10.7), the same `due=22`, the same
single MISSING, and the same `delivered_late` on #20 — with no false `ROSTER_DESYNC`.

## 3. The cause vocabulary gains `connection_error`

On 2026-11-11 at 14:00 ET, cron #13's fire ended with the session's last message
`[Error] Connection error.`, `finish_reason: "error"` and **`usage.total_tokens == 0`** —
the model call never completed, so the routine did no work at all: no title set, no
artifact, no commit, on any ref. The audit reported that as `platform_500`, which implies
an HTTP 500 and is not what happened.

`connection_error` is now a first-class cause (contract + procedure's inline copy + the
glossary), allowed on `MISSING`, `stalled` and `present_but_empty`. The diagnosis it
enables: a fire with zero tokens is a **re-run candidate**, not a code fix.

## 4. Two free signals that turn "MISSING" into a diagnosis

- **The title.** Every fleet routine titles its session `[<DD-MM>] NN-<name>` as its first
  action; `[cron] <file>.md` is the platform's fallback, meaning the routine never
  executed its first step. On 2026-11-11, 11 of 12 routine sessions carried the fleet
  title and the one that did not was the fire that died with zero tokens.
- **The token count.** `usage.total_tokens == 0` on the failing turn means the model call
  never produced output.

Both come from data the audit already collects. They separate "the fire never started"
from "the fire ran and the push lost the race" — different fixes.

## 5. The delivery-latency allowance is per routine

A single 45-minute default makes a chronically slow routine flap between `delivered` and
`delivered_late` on noise. Cron #20 ran **42.7 → 50.5 → 46.1** minutes over 11-09/10/11.

`latency.per_routine_allowed_minutes` now exists in the contract: a routine named there
uses ITS value, everyone else uses the default. The **gate (C17)** checks the published
state against the same map, so the status file and the gate cannot disagree. The auditor
**reports** the chronic condition and recommends a value — it never widens the allowance
itself; that is the operator's call.

## 6. A stub is not a delivery

`present_but_empty` now has a defined trigger: the artifact landed but carries a degraded
marker (`fetch_failed`, `PROCEDURE_FETCH_FAILED`, `skill_fetch_failed`,
`prompt_blocks_fetch_failed`). It is published as a `present_but_empty` gap with
`cause=push_failure` (the push landed a stub, not the artifact) while the routine's state
stays `delivered` — the file DID land, so the headline `missing` count is untouched. The
gate (C18) catches a stub published on a missing routine, and a routine published as both
degraded and missing.

## 7. `verify_delivery.sh --verify-bytes` (B3)

The procedure claimed this helper "compares the SHA-256 of the remote blob against the
local file". It did not — it only checked PRESENCE, so every routine that trusted the
wording had a weaker guarantee than it believed it had. The helper now has an **opt-in**
`--verify-bytes`: it reads the blob through the git blob API for the sha the contents API
names (the contents API is CDN-cached) and compares sha256 with the local file. Exit 5 on a
mismatch, `unverified` when it cannot answer.

**The default is unchanged** — the other 21 routines keep the presence-only behaviour, and
only cron #90 opts in. Measured today: correct bytes → `BYTES: ok`, a deliberately
different local file → `BYTES: FAILED` (exit 5).

## 8. The session id must be UNQUOTED (B1)

`session_get` / `session_messages` reject a snowflake id passed as a JSON **string** with
`/session_id: Expected string` — the host parses the numeric-looking string into a number
and then fails its own type check. Passing the id **unquoted** works, for both tools. The
procedure's STEP 4c said "pass the id as a quoted string (verified working 2026-11-02)";
that instruction is now inverted, and following it cost three failed calls per gap on the
2026-11-12 fire. Only cron #90 was affected: the other routines call `session_get` with
`"me"`.

## 9. Smaller procedure-level wins

- **No checkout** in STEP 2 (`git worktree add --no-checkout`): the audit only ever asks
  git for trees, logs and blobs.
- **One tree listing** for the staleness loop (27 walks → 1).
- **The 462 KB `cron_read` payload** is recovered from the tool-result chunk directory with
  one documented command instead of by exploration, and it never enters the context.
- **Bounded reads**: the procedure is ~73 KB and the read tool truncates at ~50 KB,
  dropping the middle. The procedure now says to read it in two bounded chunks — a
  truncated read can alter a character, and a path in that table decides a MISSING verdict.
- **Do not read the gate's source**: the gate prints one `FAIL <id> <message>` per
  violation; reading its 27 KB cost 21 s and taught nothing.

## 10. What did NOT change

The deployed prompt, the reply format, the status schema's required fields, the states,
the labels, and the other 21 routines' behaviour. `check_auditor_contract.py` grew two
checks (C17, C18) and the contract grew one cause token; both are additive, and the
existing published audit for 2026-11-11 still passes the gate unchanged (299 checks).

## 11. The tests

- `tools/test_auditor_contract.py` — 36 checks: the contract is satisfiable AND every
  breach is caught, including the new `connection_error` cause, the C17 allowance and the
  C18 stub pairing.
- `tools/test_auditor_metrics.py` (NEW) — 30 checks against a purpose-built fixture repo
  with known commit times: the pure helpers, the end-to-end measurements, and the four
  cases that broke the first version of the engine (a multi-fire routine's slot timing, a
  routine that publishes a directory, a self-check routine with no artifact, a stub that
  is not a real artifact).
