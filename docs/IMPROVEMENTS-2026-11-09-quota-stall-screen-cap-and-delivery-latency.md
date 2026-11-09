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
