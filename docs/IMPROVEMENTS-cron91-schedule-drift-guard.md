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

---

## Follow-up (2026-11-15, later): the refresh inside that fix was itself unhardened

The tip-pinning above removed the FALSE DRIFT. Two things inside the refresh that
removes it were still unsafe, and **neither was exercised by any test** — the guard
proved only that a copy it CANNOT pin is refused.

### 1. `git reset --hard` destroyed local work

`ensure_repo_at_tip()` fast-forwarded a lagging copy with an unconditional
`reset --hard FETCH_HEAD`. The copy the guard reads is not always a throwaway
clone: `find_repo_dir()` searches `--repo`, `/workspace/guard/mig`, `/workspace/mig`,
the detector's own parent directory and `/workspace/repo`, and `/workspace` has been
a live checkout of the outputs repo with a whole tree staged. A refresh that found a
copy with tracked changes would have **destroyed them**.

**Fix:** a copy with tracked changes (`git status --porcelain --untracked-files=no`)
is **never reset**. It is left alone and the comparison is refused
(`... has LOCAL CHANGES, so it was NOT refreshed`). Untracked files are ignored on
purpose — `reset --hard` does not delete them, so they are not a reason to refuse.

### 2. A refresh could land on a commit other than the tip

The old code reset to whatever `FETCH_HEAD` named. When `main` moves between the tip
read and the fetch, `FETCH_HEAD` is a NEWER commit than the tip the caller asked for,
and the copy was moved onto it — a commit nobody asked for, which the comparison was
then made against.

**Fix:** the copy lands **ON the tip or on nothing**: the reset runs only when the
fetch succeeded AND `FETCH_HEAD` IS the tip.

> One hazard that turned out **not** to be real, recorded so it is not "fixed" again:
> a FAILED fetch truncates `FETCH_HEAD` to empty, so the old unconditional reset
> failed harmlessly. The hazard was the commit it *could* land on, not the one it
> could not.

## Proof: both new cases were observed FAILING

`tools/test_schedule_drift_contract.py` gains three cases (33 → 36 checks), and each
new guard was mutated to prove it bites:

| case | mutation | result |
|---|---|---|
| a copy that CAN be pinned to the tip is brought to it | — | PASS |
| a copy with local changes is refused, and the local work is NOT destroyed | drop the dirty-tree guard | **FAIL** — the local work was destroyed and the function still reported the copy as being at the tip |
| a refresh that cannot land ON the tip does not move the copy at all | reset to any `FETCH_HEAD` | **FAIL** — the copy moved from `27b4cf9` to `bff83a5`, a commit nobody asked for |

The fixtures are hermetic and offline: a local bare repo stands in for `origin` and
the tip is injected (`ensure_repo_at_tip(repo_dir, tip_sha=...)`), so the refresh path
is exercised without a network call.

**No `cron_update`, no prompt change:** `tools/schedule-drift.py` is fetched at run
time, and the deployed `#91` prompt already says to report `spec drift: NOT CHECKED --
<reason>` exactly as printed ("never claim the specs are clean when they were not
checked").
