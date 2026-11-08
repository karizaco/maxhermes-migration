# Deploy handoff — after Windows-safe filename merge (2026-11-08)

`maxhermes-migration` `main` now includes:
- `push_artifact.sh` **2026-11-08.1** (sanitizes illegal basenames)
- #04 generators/skill/prompt OUTPUT → `reversal-bullish-3_55.*`
- `archive/` for the 2026-09-25 local Mavis snapshot

`minimax-cloud-outputs` `main`/`master` @ `6569109` renamed **76** historical colon paths (`:` → `_`).

## Still required on MiniMax Cloud (cannot be done from this Windows agent)

```text
1. Confirm runtime fetch of push_artifact.sh shows PUSH_ARTIFACT_VERSION: 2026-11-08.1
2. python3 tools/deploy_prompts.py --emit 04
3. cron_update task_id + schedule "55 15 * * 1-5" + timezone "America/New_York" + exact prompt bytes
4. SHA-256 verify read-back vs repo; do not send enabled or model
5. Expect brief #91 PROMPT-DRIFT until step 4 succeeds
```

Task id (from deploy_prompts.TASKS at merge time): `457170140713209` — re-resolve from live `cron_read` before update.