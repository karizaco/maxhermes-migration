# IMPROVEMENTS — 2026-11-17 — the auditor's roster check compared NAMES, and its gap lines could not be published

Two findings came out of the **2026-11-14** delivery audit (cron #90, audited 2026-11-15):

| finding | label | cause | what it said |
|---|---|---|---|
| `13-macro-calendar-midweek` — `macro-calendar/2026-11-11-midweek.md` | `MISSING` | `connection_error` | the Wed 14:00 ET fire died at the platform level and never wrote the artifact |
| `25-ntrt-gap-brief-daily` — `cloud-prompts/_shared/auditor-procedure.md` | `roster_desync` | `cron_update_failed` | the auditor's own roster table carried the wrong schedule for #25 |

The second was **already fixed upstream** (commit `7210498`, 2026-11-16 07:10 ET — the table row
is now `45 8 * * 1-5`, and the same commit fixed a `KeyError: 7` that crashed every Sunday
audit). The table is right. **The checks that would have caught it were not.** This document
records what was wrong with them, because "we fixed the table" is not the same as "the next
stale table will be caught".

---

## 1. The roster check compared NAMES, not TIMES

`tools/auditor_roster_check.py::copy_drift()` asked one question of each copy of the roster:
**is this routine in this copy?** It never asked **does this copy say the same TIME?**

**Evidence (fault injection).** The exact 2026-11-15 defect — the table row
`| 25-ntrt-gap-brief-daily | \`0 9 * * 1-5\` |` injected into a copy of the procedure — returned:

```
roster_copy_drift_count = 0
```

A copy that named the right routine at the wrong hour was indistinguishable from a correct copy.
The consequence is the same class of blind spot the check was written for: the auditor would look
for `ntrt/{date}.md` at the wrong time, and the routine's real slot would never be checked.

**The fix.** Schedules are now compared as **slot sets** — `(minute, hour, weekday)` triples,
weekday 7 folded into 0 — so:

- the procedure's STEP 4 table is compared **per routine id over the UNION of that id's rows**,
  because #17 fires twice and is written as two rows (`50 9 * * 1-5` + `50 15 * * 1-5`) against
  a one-row ground truth (`50 9,15 * * 1-5`). A row-by-row check would flag the legitimate first
  row and would miss a copy that **drops** the second slot — the dropped slot is a routine that is
  never checked at all;
- `tools/deploy_prompts.py` is compared **per task**. It is the copy a `cron_update` is handed, so
  a stale schedule there fires a routine at the wrong time, and **nothing had ever compared its
  schedules**;
- `tools/gen_roster.py`'s `ARTIFACTS` map stays a presence check — it carries paths, not schedules.

`auditor_metrics.py` carried its own copy of the cron parsing and `auditor_roster_check.py` grew
a second. There is **one** module now (`auditor_roster_check.py` owns the semantics, the engine
imports them), so "when does this schedule fire" cannot mean two things in one audit.

**Evidence (the fix bites).** `tools/test_auditor_roster_check.py` — 13/13:

| injected | caught |
|---|---|
| the 2026-11-15 table row (`0 9 * * 1-5` for `45 8 * * 1-5`) | yes |
| a stale schedule in `deploy_prompts.py` | yes |
| a **dropped** #17 slot row | yes (a row-level check cannot see this) |
| #17 stated as TWO rows | **no** — that is correct, and must not be drift |

## 2. The detector's own gap line could not be published

STEP 4e-2 said **"publish each line VERBATIM"**, and the line the detector printed was:

```
gap: 25-ntrt-gap-brief-daily ROSTER_DESYNC cloud-prompts/_shared/auditor-procedure.md STEP 4 — cause=cron_update_failed age_h=0 — …
```

Two gate violations in one line:

- **C04** — `ROSTER_DESYNC` is not in the contract's `gap_labels`; the contract's spelling is
  lowercase `roster_desync`;
- **D04** — the gate's own gap regex (`^gap:\s+(\S+)\s+(\S+)\s+(\S+)\s+—\s+cause=…`) needs the
  path to be ONE whitespace-free token, and `… STEP 4` made the line unparseable.

Following the procedure verbatim **failed the audit's own gate**. The procedure's other template
(4c-0: `gap: <routine> ROSTER_DESYNC <ground truth> (table says <table schedule>)`) had no
`cause=`/`age_h=` at all, so it could not parse either.

**The fix.** The line is now built from the contract's exact form — lowercase label, the stale
copy's **file path** as one token (`cloud-prompts/_shared/auditor-procedure.md`,
`tools/deploy_prompts.py`, `tools/gen_roster.py`), `cause=cron_update_failed age_h=0`, and the
routine named the way the auditor's roster table names it (which is what the status file's
`routines` map is keyed by). Both procedure templates were rewritten to match, and the gate now
**checks the procedure's templates** (P04): every `gap:` template the procedure prints must be in
the contract's shape, with a legal label and a legal cause for that label.

**Evidence.** `tools/test_auditor_contract.py` — 41/41, including the shipped procedure passing
P04 and a procedure with the old template failing it.

## 3. A carried-forward gap was never re-checked

`macro-calendar/2026-11-11-midweek.md` was carried across five audits — age 17 h → 41 → 65 → 89
→ **113** — with `streak` frozen at 1, because #13 fires only on Wednesdays and nothing ever
asked whether the path had appeared. And the routine writes `macro-calendar/<fire-date>-midweek.md`,
so **no later fire could ever produce that path**: the gap was structurally permanent, and the
audit had no way to say so.

**The fix.**

- the engine measures every prior gap's path against `origin/main` (`path_present`) and whether
  the artifact declares itself a reconstruction (`reconstruction` — `(RECONSTRUCTION)` in the
  title, or "this is a RECONSTRUCTION" in its section 0);
- the procedure (4c-3a) retires such a gap: `reconstructed` if the artifact was rebuilt, a
  delivery if it simply landed, and it is **not** carried forward again once reported as
  `reconstructed`;
- the gate fails an audit that publishes a `MISSING` gap whose artifact the engine measured as
  present (**C20**) or a `reconstructed` gap whose artifact is absent (**C21**). The measurement
  and the claim come from the SAME snapshot of `origin/main`, so the check has no race.

**Evidence (the rehearsal).** The engine run against the real outputs repo with the real prior
status:

```
{"routine": "13-macro-calendar-midweek", "path": "macro-calendar/2026-11-11-midweek.md",
 "label": "MISSING", "cause": "connection_error", "gap_age_hours": 113.2, "streak": 1,
 "path_present": true, "reconstruction": true}
```

and the gate on the two possible audits:

| the status file says | the gate says |
|---|---|
| the gap retired as `reconstructed` (cause `connection_error`) | `CONTRACT: ok (54 checks)` |
| the gap carried forward as `MISSING` | `FAIL C20 … the engine measured that path as PRESENT on origin/main - the gap should have been retired` |

## 4. The contract

`connection_error` and `never_fired` are now legal causes for a `reconstructed` gap. Without them
the **honest** cause of the 2026-11-11 loss would have failed C05 on the very re-label that
retires it — the contract would have forced the audit to keep a false `MISSING` rather than let it
tell the truth.

## 5. The instance: the artifact itself

`macro-calendar/2026-11-11-midweek.md` was **rebuilt on 2026-11-17** from two artifacts that
already exist in the outputs repo — the 2026-11-08 week-ahead (every Nov 11/12/13 row with its
prior and consensus, the Fed speakers table, the Treasury calendar) and the 2026-11-10 briefs
(the October CPI actual and the Nov 10 close) — and pushed to `origin/main`
(`28e0897`, byte-verified). It follows the fleet's own reconstruction precedent
(`options-flow/2026-10-19.md`, `options-flow/2026-10-26.md`): the title carries
`(RECONSTRUCTION)`, section 0 states what was lost, what is here instead, and the two ways it
differs from a live run (the consensus figures are the Nov 8 estimates carried forward; the
Nov 12–13 rows carry no ACTUAL tags). The routine's machinery is healthy — task `457174550757502`,
enabled, `0 14 * * 3`, skill fetch and window check both pass — so the fix for the loss is a
re-run, not a code change.

## 6. What changed where

| file | change |
|---|---|
| `tools/auditor_roster_check.py` | the canonical cron semantics; schedule-aware copy drift; a contract-exact gap line; the `/workspace` fallback now applies only when the detector itself runs there |
| `tools/auditor_metrics.py` | imports the detector's cron semantics; the roster verdict moved to the detector; `path_presence` / `path_present` / `reconstruction` |
| `tools/auditor-contract.json` | `connection_error` and `never_fired` added to `label_causes["reconstructed"]` |
| `tools/check_auditor_contract.py` | `--metrics`; C20 / C21 (the gap lifecycle); P04 (the procedure's gap templates) |
| `cloud-prompts/_shared/auditor-procedure.md` | 4c-0 and 4e-2 templates rewritten; 4c-3a (the retirement rule); the engine's field table; the reconstructed-artifact list; `PROCEDURE_VERSION: 2026-11-17.1` |
| `tools/test_auditor_roster_check.py` | 13/13 — four schedule-drift injections, the two-row #17 non-drift, and every printed line parsed under the gate's own regex |
| `tools/test_auditor_contract.py` | 41/41 — C20, C21 and P04 each observed failing |

Everything here is fetched at RUN time, so it lands on the next 07:00 ET fire with **no
`cron_update`** and no prompt drift.
