# Improvements — 2026-11-09: the quota stall, the silently truncated screen, and the invisible delivery latency

**Date:** 2026-11-09 · **Scope:** the fleet's whole morning block, via two routine contracts
(`26-agentic-pre-market-brief` and `90-delivery-auditor`) · **Trigger:** the 2026-11-05 fire

---

## The event

On 2026-11-05 the MiniMax Token Plan 5-hour usage window was exhausted. Cron #26's 08:30 ET
fire recorded `42212: Token Plan usage limit reached … (2056)` 13 seconds after dispatch, and
every fire between 08:30 and 09:50 ET died the same way. They were not lost — the platform
RESUMES a crashed cron conversation IN PLACE — so cron #26 and cron #08 published on 2026-11-06
at 05:52 and 05:47 ET, 21.4 hours after their scheduled fires, while cron #26b's 09:20 ET fire
resumed at ~10:08 ET and pulled its screen 40 minutes AFTER the open.

Two defects in the fleet's own contracts were exposed by that morning. Both are fixed here.

---

## 1. The ±3% screen was silently truncated, and the artifact published a FLOOR as a COUNT

**Evidence.** The pre-market screen pinned `range:[0,400]`. On 2026-11-05 the band held 379
gainers and **547** decliners. The gainer screen returned all 379; the decliner screen returned
**400 of 547** — with HTTP 200 and no warning, because the scanner honours a range silently. The
147 omitted rows were the LEAST negative decliners, so the published top-10 table was complete
but `down_3pct` read as a count when it was a floor. The same truncation silently floored cron
#26's `down_3pct` and cron #26b's decliner counts.

**Fix (in `SKILL.md` only — the deployed cron #26 prompt is NOT touched).**

- The screen is pulled with `range:[0,1000]`, and the spec now REQUIRES the pull-time assertion
  `len(rows) == totalCount` on both screens. The scanner returns `totalCount` beside `data`, so
  the assertion costs nothing.
- If the assertion fails, the routine publishes the rows it has, sets `screen_complete: false`
  in the front matter, and says in §Source health that the counts are FLOORS.
- The front matter gains `screen_complete: <true|false>` — the completeness is a PUBLISHED
  FIELD, not prose.
- **New clause C6** in `tools/check_premarket_brief.py`: the front matter must carry `up_3pct`,
  `down_3pct` and `screen_complete`; `screen_complete: false` is only legal if the artifact says
  the counts are floors.

**Verification.** `range:[0,1000]` was measured against the live scanner before the change:
689 gainers and 342 decliners returned, `len(rows) == totalCount` on both sides.
`tools/test_premarket_brief_contract.py` gained three fault injections (the field is missing, a
truncated screen whose counts are not called floors, a malformed value) and a positive case (a
truncated screen that DOES say "floor" passes). 20/20 breaches caught.

**Why the marker did not move.** The deployed cron #26 prompt names
`premarket-brief-artifact-v2` in its front matter. Bumping the marker would have required
redeploying a 19 KB prompt for one word; the addition is additive and changes no existing
clause's meaning, so the marker stays `v2` and the revision is recorded in the SKILL.

---

## 2. A cron run record's duration is the DISPATCH, not the work

**Evidence.** Cron #26's 08:30 ET fire closed in **1.288 s** with `status: 1` — and its artifact
did not appear for 21.4 hours. Cron #25's 09:00 fire: 1.403 s. Cron #26b's 09:20 fire: 1.008 s,
with a **49.8-minute gap** before its first tool call. The same fire on 2026-11-04 and
2026-11-06 also shows ~1.1 s and ran normally.

`started_at_ms` and `finished_at_ms` measure the platform DISPATCHING the prompt to the agent.
They say nothing about when the work happened. So cron #90's auditor, which classifies a routine
by whether its artifact is on the branch, saw a fire that was blocked for 21 hours as
**delivered** — exactly like a healthy one. The 2026-11-05 morning was invisible to the audit.

**Fix (in the run-time-fetched procedure, the contract and the gate — no prompt change).**

- `tools/auditor-contract.json` → **v2**: a new state `delivered_late`, a new gap label
  `stalled`, a new cause `quota_2056` (the code actually observed; the vocabulary previously
  only knew `quota_2067`), and a new cause `slow_run` for "the turn finished normally but late,
  and no platform failure is evidenced" — because "the platform blocked it" and "the routine is
  slow" need different fixes.
- Every routine's status entry now carries `delivery_latency_min`: the commit that ADDED the
  artifact (the FIRST delivery — a later fix-forward does not change when a routine first
  published) minus the fire's scheduled time.
- The procedure gains **STEP 4a**, which measures that latency from the clone STEP 2 already
  makes, and classifies: ≤ 45 min → `delivered`; > 45 min → `delivered_late` PLUS a `stalled`
  gap line naming the cause. The 45-minute default is measured across 2026-11-04 → 2026-11-08:
  the slowest HEALTHY routine landed 32 minutes after its schedule, and #10 — which fires at
  14:00 ET — landed at 14:07. A routine that is chronically slower gets its own named value; the
  global number is never widened to hide one slow routine.
- **New clauses in `tools/check_auditor_contract.py`**: C14 — a `delivered_late` routine MUST
  have a `stalled` gap line and a `stalled` gap line MUST name a `delivered_late` routine, so a
  late delivery cannot be swallowed; C16 — a delivered routine MUST carry a numeric
  `delivery_latency_min`, and only a delivered routine may carry one. `stalled` joins the
  finding labels, so `audit_status: ok` is refused when a stalled delivery is present.
- `delayed_replay` already existed as a cause; the new state is what lets a fire that WAS
  resumed and DID publish be reported as late rather than as a clean delivery.

**Verification.** `tools/test_auditor_contract.py` gained five fault injections (a
`delivered_late` with no `stalled` line; a `stalled` line for a routine that is not
`delivered_late`; a stalled delivery hidden behind `audit_status: ok`; a delivered routine with
no latency; a `stalled` gap paired with a cause the label does not accept). 30/30 checks
behave correctly, and the pre-existing inline-contract parity check (P01/P02) proves the
procedure's fallback copy still agrees with the contract file.

---

## What this does NOT fix

- **The quota itself.** The 5-hour window is a billing limit; the fix is credits and a lower
  context budget (M3.1-Flash's own guidance is 512K, not the 1M the cron prompts pin), not
  anything in this repo. The 08:30 slot still fires three routines in one minute.
- **The platform's error text.** MiniMax's 2056 carries a reset timestamp; the platform
  reformats it into "Token Plan usage limit reached" and drops the clock. A future request to
  the platform should ask for the reset time to survive into the session's last message.
- **Old artifacts.** Artifacts published before 2026-11-09 do not carry `screen_complete` and
  will not satisfy C6. Nothing re-checks them; if it is ever needed, that is the moment to
  revisit the marker.

## Revert

```bash
git revert <commit-sha>            # each change is its own commit
```

No cron redeployment is involved in either change: the pre-market screen spec and the auditor's
procedure, contract and gate are all fetched at RUN time.

---

# Part 2 — the follow-through (2026-11-09, later the same day)

The two fixes above close the gaps that the 2026-11-05 morning exposed. Five more changes make
the fleet resilient to the next one, and they were approved as a set.

## 3. A routine's reply now carries its own delivery latency, and a platform stall counts in `errors:`

**The gap.** My own reply that night said `push: ok` and `errors: 0` — while the fire had been
blocked for 49 minutes and the upstream baseline was missing. The platform's run record says
"ok" in ~1 s either way, so nothing in the routine's own accounting could have told me. The
operator saw a clean run.

**The fix.**

- `cloud-prompts/_shared/window_check.sh` now prints `stall_min:` — the platform's delay between
  the fire's dispatch and the turn actually starting. The window check is a routine's first
  action, so every routine that runs it gets the number for free.
- The shared `## DELIVERY` block in `PROMPT-BLOCKS.md` (fetched at RUN time, so every routine
  that downloads it gets it with no redeploy): the push line carries
  `delivered_at … latency N min`, and **`stall_min` over 5 counts ONE error** with a `stalled:`
  line naming the cause. The cause is read from the routine's OWN previous turn via
  `session_messages`, so it is quoted, not guessed.
- The five routines that do NOT download `PROMPT-BLOCKS.md` carry the same rule where they
  already fetch something: `#26b` in `_shared/premarket-refresh.md`, `#92a`/`#92b` in
  `_shared/preopen-capture.md`, `#90` in `_shared/auditor-procedure.md`, and `#01` in its own
  prompt (deployed with this change).

**The rule that keeps it honest.** If the artifact publishes a `degraded_sources:` count, the
reply's `errors:` must equal it exactly — so a stall must be INCLUDED in the artifact's count.
The artifact and the reply cannot disagree about how many things went wrong.

## 4. The advisory quota probe — and why it cannot prevent the stall

`cloud-prompts/_shared/quota_check.sh` (new) asks the documented Token Plan endpoint
(`GET /v1/token_plan/remains`) how much of the 5-hour window is left and when it frees. It is
ADVISORY and it FAILS OPEN: no key, an unreachable endpoint or an unparseable body prints one
line and exits 0, because a missing key must never be counted as an error and must never stop a
routine.

**It cannot prevent the stall, and the file says so.** A routine cannot probe its way out of a
block: the model call that runs the probe is the very call that gets rejected. What it buys is
(a) a running routine knows to TRIM — fetch the skill once, pull the screen once, skip the
optional sections — and (b) the operator learns, through the routine's reply, that the window is
nearly gone. `#01`, the weekly check, now runs it first, because a weekly check is the natural
place to see headroom BEFORE the next morning.

**It needs a key.** With `MINIMAX_API_KEY` unset the probe says so and everything else behaves
exactly as before.

## 5. Cron #26b now publishes its screen as a CSV

**The gap.** On 2026-11-05 cron #26 was rebuilt 21.4 hours after its fire and had to recover its
screen by PARSING `#26b`'s MARKDOWN TABLES — which is how it ended up with 702 of the 779 names
it should have had. The `#26` spec even named the refresh's `.md` as a source for
"pre-market volume, %ADV, market cap, sector", which is a markdown table being used as a data
source.

**The fix.** `_shared/premarket-refresh.md` now writes
`daily-briefs/{date}-pre-market-refresh.csv` beside the markdown, with a pinned header:

```
ticker,name,premarket_close,premarket_change_pct,premarket_volume,avg_volume_30d,pct_of_adv,prior_close,prior_session_change_pct,live_close,live_change_pct,live_volume,market_cap,sector,exchange,screen_complete
```

`prior_close` is DERIVED (`premarket_close / (1 + premarket_change_pct / 100)`), never taken from
the screener's `close` column, which is the LIVE intraday price once the session is open. The
`live_*` columns are named so nobody can mistake them for pre-market. The push stages the whole
output tree, so the CSV rides along in the same commit with one `--add`.

The `#26` skill spec now reads the CSV and falls back to the markdown only if the CSV is absent.

## 6. The 08:30 slot no longer fires three routines in one minute

**The gap.** The 08:30 ET slot fired `#26`, `#08` and `#92a` simultaneously, each carrying a
~300–520k-token context. That collision is what exhausted the 5-hour window and cost the fleet
every fire from 08:30 to 09:50.

**The fix.** `#08` moves to **08:34 ET**. Its artifact path
(`daily-screens/{date}/pre-market-gapper.md`) carries no slot in its name, so it moved without
touching a single path, and a gapper screen loses nothing to four minutes.

**`#92a` stays at 08:30, deliberately.** Its slot name `preopen-feed/{date}-0830.jsonl` is
load-bearing in five places: the checkpoint path itself, the feed's slot list
(`FEED_CHECKPOINTS`), the procedure's slot assertion, the auditor's stale-check regex, and the
skip-marker name. Moving it is a bigger change than the collision is worth, and the residual
two-way collision at 08:30 is accepted. The real lever is context size and credits, not the
minute.

The ground truth (`tools/schedule-ground-truth.json`) and the auditor's roster table moved with
the schedule, and `#08`'s deployed prompt was updated so nothing in it lies about its own slot.

## 7. The "no baseline" vocabulary — three kinds of missing, not one

**The gap.** My refresh said cron #26's morning brief "failed". The truth was that the 08:30 fire
was **quota-killed and later resumed in place**, and it published the 11-05 brief 21.4 hours
later. A refresh that writes "failed" is wrong by the next morning.

**The fix.** `_shared/premarket-refresh.md` now distinguishes three cases, each with a
recognised signature and its own consequence:

| Case | Signature | What to publish |
|---|---|---|
| never ran | no run for the fire, or the session's last message is a platform error | the refresh alone; name the cause |
| **quota-killed, may still be resumed** | the session's last message is `42212: Token Plan usage limit reached … (2056)` | the refresh alone, marked **provisional**, saying the upstream may be resumed in place and what a resumed upstream would change |
| genuinely dead | a run exists, no quota error, no platform error, no artifact | the refresh alone; name the upstream as dead |

## 8. The platform request — a legible 2056

`docs/BUGREPORT-minimax-2056-reset-time-dropped.md` asks the platform to preserve the reset
timestamp that MiniMax's own error body already carries. It is a BUGREPORT because it is a
defect outside the repo: the provider's message says `resets at 2026-05-15T15:00:00Z (2056)` and
the platform's reformat drops the clock. With it, a blocked fire could report when it recovers;
without it, the fleet can only observe recovery after the fact.

**Submit it via the app's Feedback dialog, or email MiniMaxCode@minimax.io.**

## What this still does not fix

- **The quota itself.** Credits must be bought, and the context budget is still pinned at 1M
  where M3.1-Flash's own guidance is 512K. Both are settings, not repo changes.
- **The residual 08:30 two-way collision** (`#26` and `#92a`), for the reason above.

---

## 9. Deploying a prompt: what a 13 KB paste actually costs

Cron #08's prompt had to be redeployed, because its stated schedule changed. A 2-line probe came
first — the transport round-trips newlines, backslashes, `$`, backticks and quotes losslessly —
but a 13.4 KB paste still introduced **three slips in prose**: `and has` → `and it has`,
`as success` → `as a success`, and `view:runs` → `view=runs`. None of them is inside a shell
block, so the deployed prompt's fetch chain is byte-identical to the repo's and the routine is
unaffected.

**The rule that came out of it: when the platform's copy is mechanically fine, sync the REPO to
the PLATFORM; never re-paste.** Re-pasting a *working* 13 KB prompt to correct three cosmetic
tokens would have risked dropping a backslash inside a fetch block — a failure that costs the
routine its whole run — to fix prose that costs nothing. The repo now carries the platform's
three tokens, so cron #91 sees no drift. Two are cosmetic; the third (`view=runs`) reads
ambiguously but is not wrong.

**How a deployment is verified.** `cron_read view=detail` returns the stored prompt as a JSON
string. Copying that escaped string into a file and `json.loads`-ing it reproduces the
platform's exact bytes; diffing those against the repo file localises every difference to a
line. The byte arithmetic is what settles attribution. For #08 the deltas were −4 (`also`) −1
(`$`) +3 (` it`) +1 (` a`) = −1 byte, matching the observed 13,396 → 13,395 exactly — and the
two `-` deltas are slips in MY COPY (the platform's read-back carries them), while the two `+`
deltas are slips in the PASTE. For #01 the paste was byte-perfect (10,967 = 10,967) and its only
delta was a same-length letter substitution in my copy, confirmed by a second read-back: the
deployed prompt and the repo file are identical.

**Two operational rules that follow.**

- A prompt paste is verified by DIFF against the platform's own read-back, not by eye. Copying
  13 KB by eye is exactly how three slips survive a review.
- Never leave the repo and the platform disagreeing. If a paste cannot be made clean, the repo
  is synced to the platform and the residual defect is documented here, so cron #91's drift
  guard stays quiet and the next reviewer inherits a known state instead of a mystery.

**Still open for the next prompt revision of #08:** the boilerplate in #08 now reads
`cron_read view=runs` and `as a success`, while its eighteen sibling prompts read `view:runs`
and `as success`. Harmonising them means re-pasting nineteen prompts, which is not worth a
13 KB paste's slip rate for two words; it should ride the next revision of those prompts, which
the fleet already rewrites in batches.
