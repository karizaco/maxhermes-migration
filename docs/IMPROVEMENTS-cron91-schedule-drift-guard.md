# Cron #91 — schedule-drift guard: the stale-clone phantom drift

**Date:** 2026-11-15. **Scope:** cron #91 (`91-schedule-drift-guard`), the fleet's
schedule / roster / conversation / spec guard.

## What was measured

A fresh `--depth 1` clone of `karizaco/maxhermes-migration`, taken one minute after
a push to `main`, landed on the PREVIOUS commit (`65c3825` instead of `bccab154`).
The cause was a push race — another session pushed to `main` while the clone was in
flight — not GitHub staleness.

The guard compared that stale copy against the live contents API and reported
**10 phantom `SPEC-DRIFT` lines covering 10 routines and 4 spec files**:
`04, 05, 06, 07, 08, 09, 10, 15, 15b, 20` — every one of them a routine whose
spec had not moved. Six of them shared one file
(`skills/stock-screener-suite/SKILL.md`), two shared another
(`skills/eod-watchlist-snapshot/SKILL.md`), and the rest were
`skills/earnings-reaction-scanner/SKILL.md` and `tools/check_reaction_artifact.py`.

The prompt comparison in the cron prompt was exposed to the same race, in the
opposite direction: a stale copy makes a REAL drift disappear.

## The fix (repo side, so it lands with no `cron_update`)

- `tools/schedule-drift.py::ensure_repo_at_tip()` — reads the tip sha from
  `GET /repos/<owner>/<repo>/commits/main`, fast-forwards a lagging checkout, and
  **refuses to compare a copy it cannot pin** (`spec drift: NOT CHECKED -- ... STALE ...`).
  An unchecked comparison is honest; a wrong one is not.
- The **prompt-drift check moved INTO the detector** (it was inline in the cron
  prompt) ⇒ it now runs against the tip-pinned copy and prints
  `prompt drift: N of M deployed prompts differ from the repo (tip-verified)`.
  `tools/schedule-drift.py` is fetched at RUN time, so this needed no `cron_update`
  and no 26 KB paste (AGENTS.md: procedure changes belong in a fetched file).
- `tools/schedule-ground-truth.json` — two contract entries were wrong on their own
  terms: `#19`'s marker said `EARNINGS_REMINDER_V2` while the repo SKILL and checker
  are on V3 (the contract could never be satisfied — the repo's own contract test was
  FAILING on it), and `#15b`'s contract named the shared settlement SKILL that the
  routine never fetches (it is script-driven).
- `tools/test_schedule_drift_contract.py` — four new cases: a repo copy that cannot be
  pinned is refused; it produces NO `SPEC-DRIFT` line; a matching deployed prompt is not
  drift; a differing one is. The test went from **28/29 with a FAIL** to **33/33 green**.

## Proof

The new tip-verified prompt-drift check earned its place immediately: on its first run
it caught the drift the same commit was fixing (the repo's `#91` prompt at 26,784 B vs
the deployed one at 24,747 B) — the routine that checks prompt drift was itself
drifted, and the old inline check could not see it.
