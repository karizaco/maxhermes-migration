# Cron #09 — the checker's cron #10 path guard compared EXISTENCE instead of CONTENT

**Date:** 2026-11-13
**Routine:** #09 `stock-screener-daily-sweep-18:30`
**Where the fix lives:** `tools/sweep_pipeline.py` (fetched at RUN time) and
`cloud-prompts/skills/stock-screener-suite/SKILL.md` (also fetched at run time).
No `cron_update`, no prompt edit — the next fire picks it up.

## The symptom

The 2026-11-13 fire produced a complete, correct artifact and the pipeline's
own check refused it:

```
FAIL  breadth-snapshot.md is cron #10's path and must not be written by cron #09
FAIL  breadth-snapshot.csv is cron #10's path and must not be written by cron #09
FAIL  breadth-snapshot.json is cron #10's path and must not be written by cron #09
FAIL  _regime-intraday.json is cron #10's path and must not be written by cron #09
CHECK FAILED: 4 check(s). The artifact was written but MUST NOT be pushed.
```

Every other check passed: 9/9 branches complete, `rows_kept == rows_passing`
everywhere, `_regime.json` flat schema v2 with a non-empty `atr_extensions`,
no stub markers, every per-stylist book non-empty, `focus.csv` carrying the
dated close column.

## Why it happened

**Cron #10 and cron #09 write the SAME dated directory.**
`daily-screens/<date>/` holds cron #10's 14:00 ET intraday read
(`breadth-snapshot.{md,csv,json}`, `_regime-intraday.json`) and cron #09's
18:30 ET end-of-day read (`daily-sweep.md`, `breadth.md`, `_regime.json`).
Cron #10 always fires first, so **cron #10's files are ALWAYS present when
cron #09 runs** — the guard could never pass.

The guard was an EXISTENCE test:

```python
for f in ("breadth-snapshot.md", "breadth-snapshot.csv",
          "breadth-snapshot.json", "_regime-intraday.json"):
    need(not (out_dir / f).exists(),
         f"{f} is cron #10's path and must not be written by cron #09")
```

The INTENT was right — cron #09 must not clobber cron #10's published
intraday read — but the test measured the wrong thing. It asserted "these
files do not exist here", when the thing that actually matters is "these
files are byte-identical to what cron #10 published".

This was **not** a one-day fluke: it fires on every fire of every weekday,
because #10's 14:00 ET run always precedes #09's 18:30 ET run.

Measured on the 2026-11-13 fire: the four files had mtimes 19:06 UTC
(cron #10's run) and were **byte-identical to `origin/main`** — cron #09 had
not touched them. The check was failing on the very evidence that it was
supposed to produce.

## The fix

The guard now compares CONTENT, with two proofs, in order:

1. **The run-time baseline.** `cmd_run` snapshots the four paths *before* the
   run writes anything and records the snapshot in
   `daily-screens/<date>/_cron10_baseline.json` (existence + sha256 + mtime).
   The check then fails if the run CREATED, MODIFIED or DELETED one of them.
2. **The published copy on the branch.** For an artifact produced before the
   baseline existed (or checked outside a run), the check reads the file's
   blob from `origin/main` with `git cat-file` and compares the hash. The
   GIT BLOB API is used, never the contents API — the contents API is
   CDN-cached, so a stale blob looks exactly like a file that never changed.

If neither proof is available, the check **fails loudly** ("ownership cannot
be verified") rather than passing an unverified artifact.

The artifact's own `contract:` marker is deliberately **unchanged**
(`SWEEP_PIPELINE_V1`) — the published files and their shapes did not change.
The fetch ladder in the skill spec now demands a NEW fetch marker,
`SWEEP_PIPELINE_V2`, so a CDN-cached copy of the old script (with the broken
guard) cannot win the race for the next fire.

## Fault injection — the guard was observed failing

A checker nobody has seen failing is a claim, not a guard. Measured on the
patched script against a copy of the real dated directory:

| Injected fault | Result |
|---|---|
| honest baseline (nothing touched) | `CHECK OK — every artifact check passed` |
| cron #09 appends to `breadth-snapshot.md` | FAIL — *this run MODIFIED it* |
| cron #09 creates `_regime-intraday.json` | FAIL — *this run CREATED it* |
| cron #09 deletes `_regime-intraday.json` | FAIL — *this run DELETED it* |
| no baseline and no published copy | FAIL — *ownership cannot be verified* |

`selftest` stayed green (`SELFTEST OK — every derived quantity checks out`).

## The standing rule

**In a shared output directory, a guard must compare CONTENT, never
EXISTENCE.** Two routines writing the same dated directory is the normal case
in this fleet, not an edge case — the pre-market brief, the pre-open tape, the
breadth snapshot, the reversal-bullish list and the daily sweep all land in
`daily-screens/<date>/`. A presence check between two owners of the same
directory fails by construction.
