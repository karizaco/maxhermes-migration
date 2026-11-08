# BUGREPORT — Windows-invalid filenames in the outputs repo

**Date:** 2026-11-08  
**Scope:** stop the Cloud cron fleet from writing or committing paths that are illegal on Windows NTFS.

## Evidence

- A plain Windows checkout of `karizaco/minimax-cloud-outputs` cannot materialize basenames containing `:`.
- Live generator of colon artifact names: cron **#04** (`tools/reversal_bullish.py`, screener `screen.py` companion CSV, prompt OUTPUT paths, skill §5).
- The agent also *improvised* colon names not present in code (`…-3:55-near-misses.csv`, `…-CORRECTION.md`, date-prefixed copies) — measured in outputs history.
- This migration repo itself carries three **prompt** filenames with `:` (`04-…-3:55.md`, `07-…-09:45.md`, `09-…-18:30.md`). Those are scheduler `cron_name`s and are **not** renamed in this change (separate ergonomics risk).

## Fix (this change)

| Layer | Change |
|---|---|
| `cloud-prompts/_shared/push_artifact.sh` | **Chokepoint:** sanitize `--add` paths and every basename under the staged tree (`:` and other NTFS-illegal chars → `_`). Version `2026-11-08.1`. |
| `cloud-prompts/_shared/verify_delivery.sh` | Sanitize `--path`; fall back to historical colon path if still on the remote. |
| `tools/reversal_bullish.py` | Write `reversal-bullish-3_55.{md,csv}` via `ARTIFACT_STEM`. |
| `cloud-prompts/skills/stock-screener-suite/scripts/screen.py` | Companion CSV uses `3_55`. |
| Skill / prompt #04 / crons.md | OUTPUT and push paths use `3_55`. |
| `PROMPT-BLOCKS.md` | Fleet rule: never put clock times in filenames. |
| `tools/gen_roster.py`, auditor procedure, `check_bonde_artifact.py` | Accept **both** `3_55` and historical `3:55` during transition. |

## Out of scope

- Renaming the ~76 historical colon files in `minimax-cloud-outputs`.
- Renaming the three prompt files / live `cron_name`s.
- `skills-original/` archive copies.

## Deploy handoff (MiniMax only)

Prompt #04 is deploy-bound. After this lands on `main`:

1. `python3 tools/deploy_prompts.py --emit 04`
2. `cron_update` with `task_id`, `schedule=55 15 * * 1-5`, `timezone=America/New_York`, prompt bytes exactly as emitted. Never send `enabled` or `model`.
3. SHA-256 verify read-back vs repo file.
4. Expect brief `#91` PROMPT-DRIFT until redeploy completes.

Shared scripts and the skill go live on the **next fire** after push (runtime fetch). Prefer pushing the push-guard **before** or **with** generator changes so an old prompt that still says `3:55` is rewritten at push time.

## Convention

Safe stem: `reversal-bullish-3_55` (underscore, matching `skip_marker.sh`'s `tr ':' '_'`).