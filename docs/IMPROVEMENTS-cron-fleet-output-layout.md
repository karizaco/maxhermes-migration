# IMPROVEMENTS — 2026-11-12: the fleet's output layout, and a roster that had drifted in FOUR places

**Date:** 2026-11-12 · **Scope:** the whole fleet's output layout in `karizaco/minimax-cloud-outputs`,
and the four copies of the routine list that keep it honest · **Reviewed by:** a layout audit of every
deployed routine, driven from the artifact tree rather than from the prompts

---

## 1. Why this audit happened

The question was simple: **do all the routines put their output in a similar folder structure, or
do some not follow the rules?** The honest answer needed the artifact tree, not the prompt set —
because a prompt states an intention and a tree shows what actually happened.

**Evidence base.** The complete `minimax-cloud-outputs` tree was read at `master` on 2026-11-12 via
the GitHub git-tree API: **2,089 entries, 1,935 blobs, not truncated** (`"truncated": false`). Each
routine was then matched against its **declared** output path — the authoritative roster in
`cloud-prompts/cron-prompts/README.md` and `tools/gen_roster.py`'s `ARTIFACTS` map — and every file
in every artifact directory was classified against the family it belongs to.

---

## 2. The answer: there are THREE conventions, and each family uses exactly one of them

This is the headline, and it is not a defect. The fleet does not have one layout rule; it has
**one layout rule per artifact family**, applied consistently within that family.

| Layout | Shape | Families | Files |
|---|---|---|---|
| **A — dated folder** | `<dir>/YYYY-MM-DD/<files>` | `daily-screens/` (34 dated dirs, 718 files — six routines share each one), `international-eod/` (15 dated dirs, 252 files) | **970** |
| **B — dated file** | `<dir>/YYYY-MM-DD[-suffix].<ext>` | 11 families: `asia-pre-market/` 25 · `cross-asset/` 12 · `daily-briefs/` 52 · `earnings/` 42 · `macro-calendar/` 6 · `ntrt/` 27 · `options-flow/` 19 · `preopen-feed/` 20 · `us-eod/` 42 · `us-stocks-in-play/` 49 · `weekly/` 5 | **299** |
| **B′ — dated file in a sub-directory** | `<dir>/<market>/YYYY-MM-DD.csv` | `us-eod/<market>/` 97 · `ntrt/` companions 7 | **104** |
| **C — ISO week / no date** | `2026-Wnn.md` | `mcp-health/` 3 (its ledger `ledger.md` is a true ledger) | **3** |
| **D — ledger, code, docs, scratch** | no date in the name | `derived/`, `refs/`, `scripts/`, `archive/`, `catalog/`, `data_cross/`, `data2/`, `research/`, `cron-prompts/`, `pattern-study/` | **559** |

14 directories hold per-session artifacts; the remaining 663 blobs are ledgers, code and
documentation. Two of the anomalies below (D7, D8) are files that sit *inside* an artifact family
but do not belong to its layout — a sub-directory shape, and code in an artifact bus.

**Layout A is the one worth keeping and the one worth copying.** `daily-screens/2026-11-11/` holds
34 files from six different routines in one directory, so "what did the fleet produce on the 11th"
is one folder open. Under layout B the same question means opening twelve directories and matching
dates by hand. Layout C is correct for ledgers, which are cumulative by definition.

**Practical rule for a new routine: if it produces a per-session artifact, put it in a dated
folder if its family already does, and give it a distinct filename if it shares one.** The
`daily-screens/` family is the model: six routines, one dated directory, one filename each.

---

## 3. What holds up — and these are the checks that were worth running

| Check | Result |
|---|---|
| Paths with Windows-illegal characters (`: < > " \| ? *`) | **0** across all 1,935 files. The `3:55` → `3_55` cleanup held. |
| Segments ending in a dot or a space | **0** |
| Files at the repo root | **0** — only `AGENTS.md`, `ARTIFACT-INDEX.md`, `.gitignore` |
| Two routines writing the same filename in a shared directory | **0** across all 14 artifact directories — 5 of them shared by more than one routine (`daily-screens/` ×6, `earnings/` ×3, `daily-briefs/` ×3, `macro-calendar/` ×2, `preopen-feed/` ×2) and 9 holding one routine each. The `_regime.json` / `_regime-intraday.json` split holds. |
| Routines in the roster with no artifact at all | **0** — every one of the 27 has delivered |

The `_regime.json` clobber between #09 and #10 — the reason the "one owner per output directory"
rule exists — is still correctly resolved.

---

## 4. The defects

### D1 — the generated index published a FALSE statement about two live routines

`tools/gen_roster.py`'s `ARTIFACTS` map — the source the cron index and `ROSTER.md` are generated
from — **had no entry for cron #92's two pre-open slots**. The consequence was not cosmetic: the
generated `cloud-prompts/cron-prompts/README.md` rendered their Output column as **`—`**, i.e.
"this routine writes no artifact", while the auditor's own roster table and the ground truth both
knew they write `preopen-feed/{date}-0830.jsonl` and `-0950.jsonl`.

**Fixed:** both entries added to `ARTIFACTS`, with the `SKIPPED` marker in the suffix tuple so a
checkpoint that declines to run still counts as a trace — otherwise the staleness check would cry
wolf on a routine that is behaving exactly as designed.

> **A correction to this audit's own first report.** The initial read of this defect was *"#92a/#92b
> are invisible to cron #90, the auditor cannot see them."* **That was wrong**, and reading the
> auditor's procedure rather than inferring it is what caught it: `cloud-prompts/_shared/
> auditor-procedure.md` STEP 4 carries both slots in its own roster table, with its own artifact
> regexes. The auditor never lost sight of them. The defect was narrower and more interesting — see D3.

### D2 — the generated index was stale, and nothing ran the staleness check

The index said **26 routines**; the fleet has **27**. `#15b-earnings-reaction-settlement`
(schedule `15 12 * * 1-5`, project 13835) has a prompt file, an entry in `gen_roster.py`, an entry
in the ground truth, a row in the deploy harness, a row in the auditor's table — and it delivered on
2026-11-11. It was simply missing from the index table.

**This was machine-proven, not eyeballed.** `tools/gen_index.py --check` exited **1** with
`STALE: README index does not match the ground truth` before the fix, and exits **0** after it.

**Fixed:** the README is now regenerated from the ground truth (`gen_index.py`), and it publishes
**27 routines (25 producers + the #90 auditor + the #91 drift guard)**, with a `#15b` row and the
real output paths for `#92a` / `#92b`.

### D3 — the routine list is copied FOUR times, and NOTHING compared the copies

This is the finding that matters, and it is the generalisation of D1 and D2.

| # | Copy | What it is for | Had all 27? |
|---|---|---|---|
| 1 | `tools/schedule-ground-truth.json` | the schedules of record | yes |
| 2 | `cloud-prompts/_shared/auditor-procedure.md` STEP 4 | the auditor's roster table | yes |
| 3 | `tools/deploy_prompts.py` | the deploy harness's task map | yes |
| 4 | `tools/gen_roster.py` `ARTIFACTS` | the roster/index generator | **NO — #92a, #92b** |

The auditor procedure's own STEP 4e says it: *"The roster table in STEP 4 and
`tools/schedule-ground-truth.json` are COPIES of what should be one source."* It names three places
a routine must be added to — and **does not know a fourth exists**, which is precisely how copy 4
could drift without anything noticing.

`tools/auditor_roster_check.py` compared copy 1 against the **live scheduler** only. Copies 2, 3
and 4 were compared against nothing.

**Fixed — the guard.** `tools/auditor_roster_check.py` gained a copy-drift check: it compares the
ground truth against copies 2, 3 and 4 and reports every disagreement. The findings are published
in the auditor's **own** `gap:` line format with the label and cause that
`tools/auditor-contract.json` already defines:

```
gap: 92a-preopen-catalyst-capture-0830.md ROSTER_DESYNC tools/gen_roster.py ARTIFACTS — cause=cron_update_failed age_h=0 — the generated README index and ROSTER.md cannot show its output path
```

`roster_desync` and `cron_update_failed` are already in the contract's `label_causes`, so this
needs **no new vocabulary, no change to the deployed prompt, and no redeploy** — the check lands in
a file cron #90 fetches at RUN time, exactly like every other fix in this fleet.

The detector's exit code for drift is **3**, deliberately different from **1** (a live routine
absent from the ground truth), so nothing that reads "1 = a live routine is unmonitored" changes
meaning. `tools/test_auditor_roster_check.py` proves all of it hermetically: a repo whose four
copies agree is clean; removing a routine from **any one** of the three copies is caught and names
the right copy; the original 2026-11-12 defect is reproduced and caught; and the live-vs-ground-truth
check still returns 1, not 3.

> **A bug the first version of this check shipped, caught by running it the way the auditor runs it.**
> The audit executes in a **bare sandbox that holds only the files it fetched** — there is no repo
> checkout. The first version of the check treated a copy it could not open as a *disagreement*, so
> on every audit it would have published **three false drift findings** for `gen_roster.py`,
> `deploy_prompts.py` and the auditor procedure — a check that cries wolf on every run is worse than
> no check. The end-to-end run (fetch the six files into an empty directory, run the detector from
> there) caught it; the fix is that a copy which cannot be **located** is reported as
> `roster_copy_not_checked`, never as drift, and never raises the exit code. The procedure now
> fetches `gen_roster.py` and `deploy_prompts.py` alongside the other four, so the check can run at
> all. The sandbox layout is now a regression case in the test: **8 checks, including "the sandbox
> layout raises NO false drift" and "an absent copy is not_checked, never drift"**.

### D4 — `preopen-feed/`: two sessions shipped half the artifact set

Cron #92's prompt is explicit — *"**Two files, one fire.** Every successful checkpoint writes the
tape (`preopen-feed/{date}-{HHMM}.jsonl`) AND a companion **digest** at
`preopen-feed/{date}-{HHMM}.md`"* — and *"never leave a checkpoint with no trace at all."*

| Date | 08:30 checkpoint | 09:50 checkpoint |
|---|---|---|
| 2026-11-04 | tape only — **no digest** | tape only — **no digest** |
| 2026-11-05 | tape only — **no digest** | tape only — **no digest** |
| 2026-11-06 → 11-11 | tape + digest | tape + digest |

The first two sessions landed the tape without the digest. Not recorded anywhere.

### D5 — `weekly/`: a companion file stopped landing

`weekly/2026-11-01-preview.md` · `-preview-tldr.md` · `-preview-movers.csv` — three files.
`weekly/2026-11-08-preview.md` · `-preview-tldr.md` — two. The movers CSV did not ship with the
newer edition.

### D6 — `macro-calendar/2026-W44-week-mid.md`

An **ISO-week** filename in a family that otherwise uses calendar dates. It matches no declared
pattern, sorts beside `2026-11-04-midweek.md` in a way no reader expects, and is the only file of
its shape in the repo. It is also not the name of either of #13 or #14.

### D7 — `us-eod/` carries two shapes at once

6 fossil `<date>.meta.md` files beside the current `<date>.md`, and **97 per-market CSVs** in
market subdirectories (`us-eod/au/2026-10-20.csv`) under a flat `<date>.csv` contract. The routine's
declared path is `us-eod/{date}.csv`; the subdirectory shape is undocumented in the roster.

### D8 — `ntrt/` holds code and scratch inside the artifact bus

`ntrt/_pipeline/` contains **7 Python scripts** and `ntrt/_raw/` holds **~30 raw JSON pulls and
log files**. The artifact bus is meant to hold artifacts; `scripts/` is the place for code.

### D9 — `ARTIFACT-INDEX.md` is hand-written and says so

Its own header declares it: *"This is a hand-written map, not a generated one. No build script
regenerates it, so it will go stale."* It claims ~500 files in `daily-screens/` (now 718) and
covers artifacts only to 2026-11-06. It also flags D5 on its own ("the second lacks the movers CSV
that the first carries") — so the index knew about a defect it could not fix.

---

## 5. What changed, file by file

| File | Change |
|---|---|
| `tools/gen_roster.py` | `ARTIFACTS` gains `92a-preopen-catalyst-capture-0830` and `92b-preopen-catalyst-capture-0950`; a new `NO_ARTIFACT` set declares the artifact-less routine (#91) |
| `tools/auditor_roster_check.py` | new **copy-drift check** comparing the ground truth against the auditor procedure, the deploy harness and the roster generator; new `roster_copy_drift` output; new exit code 3 |
| `tools/test_auditor_roster_check.py` | **new** — hermetic proof that drift in any copy is caught, that a clean repo is not cried up, that the SANDBOX layout (no repo checkout) raises no false drift, and that the exit-1 roster-gap semantics are unchanged |
| `cloud-prompts/_shared/auditor-procedure.md` | STEP 4e gains 4e-2: the four copies, the drift line format, and the exit-code distinction. **Fetched at RUN time — no prompt edit, no redeploy** |
| `cloud-prompts/cron-prompts/README.md` | **regenerated** by `tools/gen_index.py`: 26 → 27 routines, the `#15b` row, and the real output paths for `#92a` / `#92b` |
| `docs/README.md` | **regenerated** by `tools/gen_docs_index.py` |

## 6. Not changed, deliberately

- **The three layout conventions.** They are per-family and internally consistent. Collapsing them
  into one would mean moving every artifact in the outputs repo — a large, irreversible change to
  a published ledger for no reader benefit. The fix is a documented rule for new routines, not a
  migration.
- **`daily-screens/` sharing one dated folder across six routines.** That is the pattern worth
  copying, not correcting.
- **No routine prompt was edited.** Every fix lands in a file fetched at RUN time, so the next fire
  inherits it with no redeploy and no byte-drift risk. `cron #90` was **not** redeployed.

## 7. How to verify this landed

```bash
# the index is no longer stale (exits 1 before the fix, 0 after)
python3 tools/gen_index.py --tasks <cron_read view=list json> --check

# the four copies agree (exits 3 on drift, naming the copy)
python3 tools/auditor_roster_check.py --tasks <cron_read view=list json>

# the guard is proven
python3 tools/test_auditor_roster_check.py
```

## 8. Still open

D4, D5, D6, D7, D8 and D9 are **recorded, not fixed**. Each needs a decision that is not the
auditor's to make:

- **D4** — the pre-open digest stopped landing on 2026-11-04/05. Whether that was a procedure
  version bump or a silent failure needs the two sessions' run records; the fix belongs in
  `cloud-prompts/_shared/preopen-capture.md`, whose `PROCEDURE_VERSION` marker the next fire reads.
- **D5** — whether `weekly/` is supposed to ship a movers CSV every week or only when there are
  movers is a question about #22's contract.
- **D6** — `2026-W44-week-mid.md` is an orphan; it matches no routine and should either be
  renamed to its date or archived.
- **D7** — the `us-eod/` per-market subdirectories need a declared path in the roster, or removal.
- **D8** — `ntrt/_pipeline/` and `ntrt/_raw/` belong in `scripts/` (code) and a scratch area
  (intermediates), not in the artifact bus.
- **D9** — `ARTIFACT-INDEX.md` needs a generator, the way `gen_index.py` and `gen_docs_index.py`
  exist for the other two generated indexes.

---

_Generated 2026-11-12 by a fleet-wide layout audit of `karizaco/minimax-cloud-outputs` at `master`
(2,089 tree entries, 1,935 blobs, not truncated). Every claim above is reproducible from the
commands in section 7._
