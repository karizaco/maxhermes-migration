# IMPROVEMENTS — 2026-11-20 — every gate is fetched over the ladder AND demanded by its marker

**Date:** 2026-11-20 (Friday; the pass ran 10:00–13:00 ET on top of `origin/main` = `3c98666`)
**Scope:** the whole fleet's gate-fetch machinery — every procedure that verifies an artifact
with a checker, and the checker scripts themselves.
**Why this document exists:** the 2026-11-20 cron #92 landing fixed ONE routine's gate
(`6a3ba45`) and recorded that the same treatment was "still owed to the 3 markerless checkers
and the two local-path ones". This document is that pass, fleet-wide.

---

## 1. The defect class

Every routine publishes an artifact and verifies it with a CHECKER ("gate"). A checker is a
run-time dependency: the procedure fetches it, then runs it, and its exit code decides whether
the artifact is published.

The failure mode is **silent**. The CDNs cache `main` independently — measured 2026-11-04,
`raw.githubusercontent` served a stale blob for >17 minutes after a push while the contents API
was fresh — so a fetch that does not demand a CAPABILITY MARKER can hand back an OLDER
checker. An older checker checks fewer rules and still exits 0 on an artifact it never really
checked. The artifact ships, the report reads clean, and nothing in the transcript says the gate
was the wrong build.

Cron #92 measured it: a 2026-11-16 gate ran for three days and reported "FAILED 6 of 52"
against a board that was **correct** — 99 checks of coverage had vanished because a missing
input skipped whole sections. Worse, obeying that stale gate would have demanded a build with
**no EDGAR leg at all**, collapsing mover coverage from 53% toward 13%.

## 2. What was actually wrong, measured on `3c98666`

A sweep of every `tools/check_*.py` and every procedure that fetches one found:

| # | Site | Defect |
|---|---|---|
| 1 | `cron-prompts/19` | `check_earnings_reminder_artifact.py` fetched with a **bare single-URL curl** — no ladder, no marker |
| 2 | `cron-prompts/26` | `check_brief_consistency.py` and `check_premarket_brief.py` — same bare curl |
| 3 | `skills/agentic-pre-market-brief/SKILL.md` | `check_brief_consistency.py` **executed straight from a URL** (`python3 https://…`); `check_premarket_brief.py` bare curl |
| 4 | `skills/cross-asset-correlation-snapshot/SKILL.md` | ladder present but it **greps for the FILENAME** — every copy contains its own name, so a stale build walks in |
| 5 | `skills/stock-screener-suite/SKILL.md` | the same filename-grep on `check_breadth_artifact.py` and `check_bonde_artifact.py` |
| 6 | `skills/stock-screener-suite/SKILL.md` | `check_cron06_artifact.py` run from the **local relative path** `python3 tools/check_cron06_artifact.py` |
| 7 | `skills/unusual-options-flow-daily/SKILL.md` | `check_options_flow_artifact.py` — ladder with **no marker demand at all** |
| 8 | `skills/eod-watchlist-snapshot/SKILL.md` | `check_eod_artifact.py` run from the **local relative path** |
| 9 | `_shared/auditor-procedure.md` | the gate on the AUDITOR'S OWN OUTPUT fetched inside the shared 7-file loop, which demands **no marker** |
| 10 | `cron-prompts/07` | `check_focus_rvol_artifact.py` — **no procedure fetched it at all** |
| 11 | five checkers | **no capability marker of their own**: `check_auditor_contract.py`, `check_brief_consistency.py`, `check_options_flow_artifact.py`, `check_eod_artifact.py`, `check_reaction_artifact.py` |
| 12 | `cron-prompts/15`, `15b` | the reaction ladder demanded `REACTION_ARTIFACT_V2` — an **ARTIFACT** marker, which cannot tell two checker builds apart (the checker gained the Pass-B2 clause while the artifact format stayed the same) |

**Item 10 is the worst of them.** Cron #07 published `focus-rvol-snapshot.md` every session
while the checker written for it ran from nowhere. That checker is what asserts the RVol
definitions, the cross-check, the trend, where each prior reading came from, and the alert tier
— and the alert tier was structurally dead for five consecutive sessions (2026-11-05 ..
2026-11-11) with **nothing raising a failure**. A gate that is never fetched is not a gate.

**Items 6 and 8 are a second class of failure:** the cron sandbox's cwd is not a repo
checkout, so `python3 tools/check_x.py` may not exist at all — the gate may never have run even
once, and a missing file and a passing gate look the same in the transcript.

## 3. What changed

**The checkers (5).** Each of the five markerless checkers now carries its own capability
marker — `CHECKER_VERSION` plus the comment line the ladder greps:

| checker | marker |
|---|---|
| `check_auditor_contract.py` | `auditor-contract-2026-11-20.1` |
| `check_brief_consistency.py` | `brief-consistency-2026-11-20.1` |
| `check_options_flow_artifact.py` | `options-flow-2026-11-20.1` |
| `check_eod_artifact.py` | `eod-artifact-2026-11-20.1` |
| `check_reaction_artifact.py` | `reaction-checker-2026-11-20.1` |

**The markers are DISTINCT on purpose.** If every checker carried the same string, a copy of the
WRONG checker would satisfy the grep. `auditor-contract-2026-11-20.1` identifies one file and
one file only.

**The ladders (12 sites).** Every site now uses the house block: the contents API first, the
token added only when it is set (an empty `Authorization` header is a 401 and breaks a fetch that
worked anonymously), the acceptance test demanding the marker, and a fail-closed guard.

**Two checkers were promoted from "run it locally" to "fetch it, then run it":**
`check_cron06_artifact.py` (#06) and `check_eod_artifact.py` (#20).

**Cron #07 got its gate** — a new STEP 8 that fetches `check_focus_rvol_artifact.py` over the
ladder demanding `focus-rvol-alert-v1` and runs it on the artifact before the push. The
gate's exit code is the decision: 0 → push, 1 → fix and re-run, publish nothing. The
reply-level clauses (C15/C16) are **not** exercised in that slot — the chat reply is composed
after the push — and the prompt says so.

**The prose was made true.** #15 and #15b said "if the checker cannot be fetched, say so in
`### Method & caveats` and carry on"; the block now fails closed, so the prose says the run
publishes nothing. A procedure that contradicts its own block is a defect in its own right.

## 4. The two new gates (so this cannot silently rot again)

**`tools/audit_checker_ladders.py`** — the fleet-wide gate on HOW every gate is fetched. It
fails on: a missing ladder mirror, a ladder that does not start at the contents API, a ladder
whose acceptance test demands no marker (or demands a marker that is not in the checker), a
ladder that greps for its own filename, a ladder that does not fail closed, a gate executed
straight from a URL, a gate run from a local relative path, a checker that no procedure fetches,
and a checker that does not compile.

**`tools/test_checker_ladder.py`** — the fault injection, because **a checker never observed
failing is a claim, not a check**. Twelve cases: the ladder installs the copy that carries the
marker; it fails closed when none does; a stale copy already on disk is refused rather than
run; and the audit gate is shown to observe each of the six defect classes above. The ladder is
exercised with a stub `curl` on PATH — no network.

## 5. The lesson that bit during the pass

The first marker insertion put `CHECKER_VERSION` **above** the `from __future__ import
annotations` line in `check_eod_artifact.py`. That is a `SyntaxError`: the future import must
follow the docstring directly. The file still PARSED under `ast.parse` (which does not enforce
the placement rule) and `python3 -m py_compile` failed — and the **fault-injection suite
caught it** (`test_eod_settle_contract.py`: 8 cases failed with a SyntaxError).

That is why the audit gate now compiles every checker: a checker that does not compile is a
gate that cannot run, and the failure looks like a broken artifact.

The generalisable rule: **a marker is a change to the file, and a change to the file can break
it.** Every edit to a checker runs its own suite; a suite that was not run is a claim.

## 6. Deployment

| routine | changed file | needs a redeploy? |
|---|---|---|
| #07 | `cron-prompts/07-…md` (new STEP 8) | **yes** — the prompt file IS the deployed prompt |
| #15, #15b | `cron-prompts/15-…md`, `15b-…md` | **yes** |
| #19 | `cron-prompts/19-…md` | **yes** |
| #26 | `cron-prompts/26-…md` | **yes** |
| #90, #91 | `_shared/auditor-procedure.md` | no — the prompt fetches the procedure at RUN time |
| #06, #20, #12, #16 | the shared skill specs | no — fetched at run time |

A redeploy is `cron_update` + a **SHA-256 of the read-back** (`{"ok":true}` proves only that the
write landed), always resending `schedule` + `timezone` + `session`, because a prompt-only
update silently resets the timezone.

## 7. What is still open

- **The three markerless checkers are no longer markerless, but their RULE SETS are not
  versioned.** A checker that gains a clause must bump its marker, or a stale copy can still win
  the ladder. That is a discipline, not a mechanism: the audit gate can only see that a marker
  exists, not that it moved when the rules did.
- **`latency.per_routine_allowed_minutes` is still EMPTY** in the auditor's config, so three
  routines are chronically reported as late (`20-eod-watchlist-csv-snapshot`, `25-ntrt-gap-brief-daily`,
  `26b-agentic-pre-market-brief-refresh`). That is an OPERATOR decision, not a code fix.
- **The `ET_OFFSET_HOURS = -5` hardcode** in `tools/session_state.py` and
  `cloud-prompts/_shared/brief26_pull.py` is wrong for every summer date (the sandbox's
  `America/New_York` DOES observe DST: 2026-07-15 12:00 UTC → 08:00 EDT). Separate fix.
