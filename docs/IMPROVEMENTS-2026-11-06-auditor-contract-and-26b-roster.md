# Improvements — 2026-11-06: the auditor's contract, and #26b's roster

Cron #90 (delivery-auditor) is the fleet's external observer. It decides which routines
delivered, which are missing, and **why**. On 2026-11-03 it published
`audit: 2026-11-02 due=16 delivered=16 missing=0` plus two gap lines, and it was wrong in
three separate ways — each of them invisible in the digest.

This change fixes all three, and it fixes them in the **repo** so the fleet inherits them.

---

## 1. A fail-closed routine was classified as a missing routine

The 2026-11-03 digest reported `not_yet_fired: 91, 92a, 92b`. On 2026-11-03 #92a and #92b
**did fire** — and they correctly wrote nothing, because `XAI_API_KEY` was unset and the
capture procedure fails closed by design. The auditor had only three states
(`missing` / `not_yet_fired` / `delivered`) and no way to say *"ran, and correctly produced no
artifact"*. That is the failure the fleet had already recorded: *"a fail-closed run is not a
delivery failure."*

There is now a **fourth state**:

| State | Meaning | Counted in `missing`? | Published as a `gap:` line? |
|---|---|---|---|
| `delivered` | the artifact exists, byte-verified | no | no |
| `missing` | due, produced nothing, **and the reason is known** | **yes** | yes |
| `not_yet_fired` | the routine's own schedule has not reached its first fire | no | no |
| `skipped_by_design` | the routine RAN and correctly wrote no artifact | **no** | no — it gets its own `skipped:` line |

`skipped_by_design` **requires a reason**, quoted from evidence (the skip marker's `Reason:`
line, or the run's own reply), plus the marker's path where the routine wrote one. Three
things must all hold before a routine is called skipped: it ran on the audited date, its
session was healthy (`status_message` empty), and it declined on purpose. A skip you cannot
explain is not a skip — it stays MISSING with the evidence gap named.

`possible_holiday`, `weekend_no_us_session`, `not_due`, `not_yet_fired` and `written_off` are
now explicitly **non-findings**: they are recorded in their own arrays and never published as
a gap line. That matters because of fix 3 — a gap line without a cause is a failed audit, so
a non-finding must never become a gap line.

## 2. #26b was live and nobody was watching it

The auditor's roster came from `tools/schedule-ground-truth.json`, which held **25** entries.
The live scheduler has **26** routines: `26b-agentic-pre-market-brief-refresh-0920.md`
(09:20 ET, task `459637559267655`) was live and firing, but absent from the ground truth. So
the auditor never checked its artifact, cron #91's drift guard could not repair its schedule,
and the 2026-11-03 audit reported `roster_desync: 0` while a routine was unmonitored.

- #26b is now in `tools/schedule-ground-truth.json` (`20 9 * * 1-5`, `America/New_York`).
- It is in the auditor's roster table and its stale-check list, in `tools/deploy_prompts.py`
  (so the deploy harness can byte-verify it), in `tools/gen_roster.py`'s artifact map, and in
  the regenerated README index and ROSTER.md.

**And the class of bug cannot recur**, because the check is now a standing self-check: every
audit compares the live routine set against the ground truth and publishes

```
roster_gap: 26b-agentic-pre-market-brief-refresh-0920.md (task 459637559267655) is live but not in schedule-ground-truth.json
```

`tools/auditor_roster_check.py` implements it. The count is 0 today — but the check is what
matters, and it is proved to bite: `tools/test_auditor_contract.py` removes #26b from the
ground truth and requires the detector to catch it **by name and by task id**.

## 3. Gap lines with an empty reason were a clean audit

The gap lines that the fleet produced well were the standard: *cause, evidence, rebuild time,
what the rebuild changed*. The rest were not, and an empty reason counted as `errors: 0`.

- The cause is now a **token from a closed vocabulary**, published as `cause=<token>`:

  `platform_500` · `timeout` · `quota_2067` · `push_failure` · `delayed_replay` ·
  `not_yet_fired` · `skipped_by_design` · `cron_update_failed` · `never_fired`

  `never_fired` is the one addition: "the scheduler never dispatched it on a day it should
  have" is a real cause with a different fix from every other token.
- **A gap line without a cause is `errors: 1`, not `errors: 0`.**
- Every gap now carries **`gap_age_hours`** — hours from the routine's missed fire instant on
  the audited date to the audit run — so a three-day-old gap is distinguishable from a
  twenty-minute-old one.
- Every routine carries a **`streak`** — consecutive DUE fires missed. It is carried forward
  from the previous status file on the `audit/status` branch: `+1` when the routine is MISSING,
  `0` when it is delivered, and **unchanged when the routine was not due** (a routine that is
  not due must never reset its own streak). **A streak of 3 or more is surfaced on its own
  line** — a dead routine must never hide inside a count.

The gap line is now:

```
gap: <routine> <label> <path> — cause=<token> age_h=<n> — <detail>
```

---

## The contract, and the gate that enforces it

`tools/auditor-contract.json` is the single source of truth: the states, the cause
vocabulary, the label/cause pairs, the digest templates and the status-file schema. It is
**fetched at RUN time** by the auditor, so a change to it lands on the next fire with no
`cron_update` and no prompt drift. The prompt keeps a compact inline copy as the fallback for
a failed fetch, and the gate fails the audit if the two ever disagree.

`tools/check_auditor_contract.py` is the gate on the auditor's own output. It checks the
status file AND the digest that gets published:

| ID | What it enforces |
|---|---|
| C03–C07 | every gap carries its label, a cause, an age in hours and an integer streak |
| C08–C10 | a skip has a reason and is never `missing`; the counts agree with the gaps |
| C11–C12 | every routine carries a state and a streak; every roster gap carries a task id |
| C13 | `audit_status` agrees with the findings |
| D01–D07 | the digest's counts match the status file; every gap line carries a cause and an age |
| D08–D10 | skips, roster gaps and dead streaks are published, and a skip is never a MISSING |
| R01–R02 | every live-but-unrostered routine is named, and the status file does not invent one |
| P01–P02 | the prompt's inline contract copy agrees with the contract file |

`tools/test_auditor_contract.py` proves the gate is not a claim: it builds a contract-shaped
audit, requires it to PASS, then mutates it 18 ways and requires a FAIL each time — an empty
cause, a cause outside the vocabulary, an impossible label/cause pair, a skip published as a
MISSING, a missing age, a missing streak, a count that disagrees, a cause-less digest line, a
dead streak that is not surfaced, a roster gap that is not named, a drifted inline contract
copy. **23/23 checks behave correctly.**

The auditor now runs the gate itself (STEP 6b) against the exact bytes it is about to publish,
fixes what it reports, and — if it still fails — publishes anyway with `errors:` set to the
number of failures. A broken audit trail is worse than an imperfect one.

## The reply format is unchanged in shape

The digest stays machine-read, one line per item, no prose. The ≤ 8-line cap now covers the
**framing** (summary, push, errors); the per-item lines — one per gap, per skip, per roster
gap, per dead streak — are additional and are never merged, truncated or dropped. The summary
line `audit: <date> due=<n> delivered=<n> missing=<n>` is byte-for-byte what it was, and
`missing` still counts MISSING gaps only. This was the one place the brief's requirements
forced the cap to yield: the new states each need their own line, and a routine with a gap is
worth more than the line budget.

## Files

| File | Change |
|---|---|
| `cloud-prompts/cron-prompts/90-delivery-auditor.md` | STEP 4c-1/2/3 (cause vocabulary, age, streak), STEP 4d (`skipped_by_design`), STEP 4e (`roster_gap`), STEP 5 (states vs labels), STEP 6 (status schema v2), STEP 6b (the gate), the DELIVERY block, reminders 8–11 |
| `tools/auditor-contract.json` | **new** — the contract |
| `tools/auditor_roster_check.py` | **new** — the live-vs-ground-truth roster detector |
| `tools/check_auditor_contract.py` | **new** — the gate |
| `tools/test_auditor_contract.py` | **new** — 23 fault-injection checks |
| `tools/schedule-ground-truth.json` | + #26b (26 entries) |
| `tools/deploy_prompts.py` | + #26b (so the harness can deploy and byte-verify it) |
| `tools/gen_roster.py` | + #26b's artifact; accepts the raw `cron_read` envelope (it used to crash with `TypeError: 'bool' object is not a mapping`); only counts `.md` tasks as routines |
| `cloud-prompts/cron-prompts/README.md`, `ROSTER.md`, `roster.json` | regenerated (26 routines, #26b listed) |

## Verify

```bash
python3 tools/test_auditor_contract.py          # 23/23
python3 tools/auditor_roster_check.py --tasks tasks.json --ground-truth tools/schedule-ground-truth.json
python3 tools/check_auditor_contract.py --status _audit/status.json --reply digest.txt
python3 tools/schedule-drift.py --tasks tasks.json --no-run-chunks
```

The absent `mcp__*` tools are not errors — they are not registered and never were. The
auditor's status file goes to the `audit/status` branch; `origin/main` is never touched by it.
