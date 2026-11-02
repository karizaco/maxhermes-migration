---
name: Agent-ops sync
description: >-
  Pull the latest `karizaco/agent-ops` Grok Bot backup so I always see fresh
  routines / skills / agents without you having to tell me. Runs daily after
  the 06:30 BKK push slot.
---

# Agent-ops sync

Just a pull. Keeps the local clone of `karizaco/agent-ops` fresh so any skill/routine/agent references I make reflect the latest Grok Bot state.

## When

- Cron: `0 18 * * 0-6` Asia/Bangkok (daily 18:00 BKK — gives Grok Bot's 06:30 BKK push plenty of time to land and propagate)
- Manual: user asks "sync agent-ops" or "refresh the Grok Bot backup"

## Steps

1. Run the helper script:
   ```
   python "C:\Users\admin\.minimax\projects\coding-shared\scripts\agent_ops_sync.py"
   ```
   - The helper handles cd-into-clone, before/after HEAD capture, `git pull --ff-only`, files-changed diff, log append, and result classification.
   - It uses Python `subprocess.run` + `open(..., 'a')` — NOT PowerShell `Add-Content` / `Set-Content` / `Out-File`. The agent's bash tool never touches the log directly.
   - Single command invocation: matches the broad `python:*` permission pattern; no first-run permission prompt.

2. Parse the JSON line on stdout. Helper exit codes:
   - `0` = `ok` or `no_change` (clean tick — silent per cron policy)
   - `2` = `conflict` (non-ff) — surface to user, do NOT force
   - `3` = `missing_clone` — run `gh repo clone karizaco/agent-ops "C:\Users\admin\.minimax\projects\coding-shared\repo-analysis\agent-ops"` to recreate, then re-run the helper
   - `4` = `network` error — surface
   - `5` = `other` git error — surface

3. On `result == "missing_clone"`: do NOT auto-recreate from the cron prompt. Recreate manually, then retry the helper. (Avoids permission prompts and unintended side-effects.)

4. If `result == "conflict"`: do NOT auto-merge. Append an error line to the sync.log via `python scripts\audit_append.py "<line>" "research\agent-ops\sync.log"` (the helper already wrote the conflict line, but if you need a richer note use the audit-append pattern). Surface in chat reply.

## Output

- Updates `C:\Users\admin\.minimax\projects\coding-shared\repo-analysis\agent-ops` in place.
- Append-only `research/agent-ops/sync.log`.

## Hard rules

- Never `git push` from this skill.
- Never `git reset --hard`, `git clean -fd`, or any destructive op.
- Never edit tracked files — this skill only updates the working tree via pull.
- If pull fails (network, auth, conflict), report and stop. Do not retry in a loop.
- NEVER touch the sync log with `write` / `Set-Content` / `Out-File` / `edit` — those overwrite. Use the helper or `scripts\audit_append.py`. (See 2026-09-24 audit-log post-mortem.)
- NEVER wrap `python` in `powershell -Command "..."`. Call python directly.
- NEVER set `$ErrorActionPreference='Stop'` when invoking git — git writes progress to stderr and that gets re-interpreted as an exception. `subprocess.run` in Python doesn't have this problem; this rule applies if you ever drop back to inline PowerShell.

## Out of scope

- Restoring excluded content (secrets, transcripts, store.db, chrome cookie seeds) — those are intentionally absent.
- Running any of the synced routines — that would be invoking Grok Bot, not me.

## Sentinel

This skill is a defensive sync. Add `# auto_execute=true` to any cron prompt that runs this skill unattended — see `agents/mavis/skills/cron-watchdog/SKILL.md` for the parallel `# watchdog: re_trigger_eligible=true` convention.
