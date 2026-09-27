---
name: cron-watchdog
description: >-
  Detect and clean up stuck Mavis cron sessions (status=started, no Agent
  progress for ≥30 min) AND find dead crons whose scheduled fire was missed.
  Designed to fill the runtime-watchdog gap while the Mavis runtime ships
  its own per-session timeout. Run on cron every 15 min as a self-task.
---

# cron-watchdog

The Mavis local runtime (as of 2026-09) does **not** time out stuck Agent
sessions. A cron session that enters a decision loop or hangs on a tool
call can sit in `status: started` indefinitely with `active-turn` locked
and no Assistant output. These zombies:
- Block fresh `cron trigger` runs of the same task if the runtime has a
  concurrent-Active-turn cap on that slot
- Show up as "delivered" in `cron sessions` with no signal to the user
- Clutter `session list` until manually archived

A separate failure mode — a scheduled cron that never fires — is also
caught here. The runtime can fail to launch a session at `nextRun` time;
the session-stuck detector misses this because there is no session at all.

`cron-watchdog` is a defensive layer that runs on cron, detects both
classes of failure, and either alerts or auto-cleans them.

## When

- **Self-task (`cron self`)** every 15 min, 24/7: detects zombies and
  missed fires promptly.
- **Manual invocation** if you observe odd cron behavior in
  `cron list` or `cron sessions`.

## Thresholds (tunable in this SKILL.md)

| Age (createdAt) | Action |
|---|---|
| 0-30 min | No action (normal) |
| 30-120 min | WARN — log to `research/watchdog.log` with full session snapshot |
| 120+ min | AUTO-ARCHIVE — `session update --archived true`, log line "ARCHIVED" |

The 120-min hard cutoff is conservative — it triggers after the daily
Agent session has had plenty of time to complete any legitimate
long-running MCP task (daily-sweep tops out at ~12 min, weekly brief
~5 min, breadth-snapshot ~3 min). Anything past 2 hours is by definition
hung or forgotten.

## Hard output policy (no narration on clean ticks)

On a **clean tick** (no archive, no re-trigger, no warn, no fatal error):

- Final assistant message MUST be the empty string. Zero characters.
- Do NOT emit any preamble before the first tool call.
- Do NOT emit any post-tool-call narration, inventory counts,
  "watchdog clean", "no zombies", or one-sentence explanations of
  why the tick was clean.
- Do NOT call the `write` or `edit` tools. Pass the inventory to
  `check_stuck.py` via `--empty` (clean tick) or `--from-env` (action
  tick with content). See "Inventory delivery" below.
- This eliminates the "Edited N files" badge and the sidebar entry, AND
  avoids `%TEMP%` writes (which trigger a runtime permission prompt on
  Windows PowerShell).

On an **action tick** (warn / archive / re-trigger / locked / fatal /
missing-fire), use the chat templates at the bottom of this skill and
append one line to the audit log. `write`/`edit` calls are allowed for
legitimate artifacts (audit log append, cooldown file).

The cron output policy in user memory is the durable version of this
rule. The agent-memory entry on clean-tick narration tendency is the
specific failure mode this rule was designed to defeat — the model
layer tends to emit a single sentence even with the prompt forbidding
it; the rule must be restated in the prompt at the very top.

## Inventory delivery to check_stuck.py (PowerShell-safe)

The cron-watchdog runs on Windows PowerShell 5.1, where `bash`-style
heredoc and stdin pipes are broken:

- `<<'JSON'` is a syntax error in PowerShell (no heredoc operator).
- `echo ... | python` is consumed by the PowerShell pipeline before
  python sees stdin.
- `Set-Content -Encoding utf8` writes a BOM, which python rejects with
  `JSONDecodeError: Unexpected UTF-8 BOM`.
- `Set-Content -Encoding utf8NoBOM` is a PowerShell 7+ feature and is
  rejected by PS 5.1.
- `write` to `%TEMP%` triggers a runtime permission prompt that defeats
  the silent-cron goal.

Use one of the two flags `check_stuck.py` accepts:

### Clean tick (no candidates) — preferred

```powershell
python "C:/Users/admin/.minimax/agents/mavis/skills/cron-watchdog/scripts/check_stuck.py" --empty
```

Emits `{"tasks": []}` and exits 0. No JSON parsing, no env-var setup.

### Action tick (inventory has content) — PowerShell-safe

```powershell
$now_ms = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
$env:MAVIS_WATCHDOG_INVENTORY = '{"tasks": [<inventory>]}'
python "C:/Users/admin/.minimax/agents/mavis/skills/cron-watchdog/scripts/check_stuck.py" --now-ms $now_ms --from-env
Remove-Item Env:MAVIS_WATCHDOG_INVENTORY
```

`--from-env` reads the inventory from the `$MAVIS_WATCHDOG_INVENTORY`
env var. PowerShell-native env-var assignment, no temp file, no shell
quoting. The `Remove-Item Env:` cleanup un-sets the var for the next
process; omit it if you'd rather let it scope to the script's child.

### Legacy paths (still supported, prefer not to use)

- `--input FILE` — reads from a path on disk.
- stdin — only works on bash, NOT on PowerShell. Documented for
  cross-platform shells but not the cron-watchdog runtime.

**Always prefer `--empty` or `--from-env` on the cron-watchdog runtime.**

## Steps

1. **Inventory all cron tasks:**
   ```
   mavis cron list --limit 100
   ```
   Capture: list of `cronId` values, `cronName`, `nextRun`, `prompt`.

2. **Build the re-trigger watchlist.** Scan each task's `prompt` field
   for the literal line:
   ```
   # watchdog: re_trigger_eligible=true
   ```
   The eligible set = tasks whose prompt carries this sentinel. Do
   NOT use a hard-coded cron_id list — the sentinel is the single
   source of truth and survives renames automatically. New eligible
   crons are added by appending the sentinel to their prompt.
   If no tasks in the roster carry the sentinel, log FATAL once:
   "no crons carry the re-trigger sentinel; check that eligible
   crons have `# watchdog: re_trigger_eligible=true` in their prompt."

3. **For each `cronId`, pull recent runs:**
   ```
   mavis cron sessions --cron_id <id> --limit 3
   ```
   Filter to runs where `status == "started"` (delivered/failed/firing
   runs are NOT zombies — ignore them, even if older than 30 min).

4. **For each candidate, age-check:**
   ```
   age_minutes = (now_ms - createdAt) / 60000
   ```
   - `age_minutes < 30` → skip (normal)
   - `30 <= age_minutes < 120` → WARN, write line to log
   - `age_minutes >= 120` → AUTO-ARCHIVE attempt:
     ```
     mavis session get --session_id <sid>     # confirm still started
     mavis session update --session_id <sid> --archived true
     ```
     On 409 SESSION_BUSY: the session is truly locked — emit a
     `STUCK_LOCKED` line; do NOT retry; the runtime owns that lock.

   **DO NOT deep-read session messages.** `mavis session messages
   --session_id <sid> --limit 1` is enough to verify a session is alive.
   Reading more content wastes tokens, leads the Agent into rabbit
   holes on the stuck session's actual task, and risks the watchdog
   itself becoming a long-running zombie.

5. **Cooldown check before re-trigger.** Before re-triggering a cron
   after a successful archive, parse the most recent line in
   `C:/Users/admin/research/watchdog.log` that contains
   `archived=1` AND the cron_id. Skip re-trigger if
   `(now_ms - last_archive_ms) < 300_000` (5 minutes). This prevents
   archive + immediate re-trigger back-to-back, which makes the new
   run start before the user has noticed the old one died. The cron's
   own scheduled retry will pick up any skipped re-trigger.

6. **Re-trigger** (after successful archive AND cooldown clear AND
   cron is in the eligible set):
   ```
   mavis cron trigger --cron_id <id>
   ```
   Limit ONE re-trigger per watchdog tick per cron_id. Tag the
   re-trigger's audit log line with `_source=watchdog` so manual user
   fires can be distinguished from watchdog-auto-fires.

7. **Stale-fire detector** (separate pass over the full roster):
   A cron whose `nextRun` is in the past AND has no recent session
   within the fire window is a cron that the runtime silently failed
   to launch. The session-stuck detector does not catch this.
   For each enabled cron:
   ```
   if nextRun < (now_ms - 3_600_000) AND
      (no sessions OR most_recent_createdAt < (nextRun - 3_600_000)):
     emit: WARN missing-fire cron=<id> nextRun=<iso> age=<m>min
   ```
   Cap at 5 lines per tick. This counts as an action tick — append
   the audit log line with `missing_fires=N`.

8. **Append run summary to `C:/Users/admin/research/watchdog.log`** ONLY
   on action ticks. Clean ticks emit no log line.
   ```
   watchdog <iso-utc> tasks_inventoried=N warns=N archived=N retriggered=N locked=N missing_fires=N
   ```

9. **Chat reply** per the templates below. Clean ticks emit zero
   characters. Action ticks emit ≤10 lines.

## Re-trigger watchlist (sentinel)

The re-trigger watchlist is **sentinel-based**, NOT hard-coded. Each
cron that should be re-triggered on archive carries one line in its
prompt body:

```
# watchdog: re_trigger_eligible=true
```

When a cron is renamed or replaced, the old ID simply falls out of
the eligible set; the watchdog prompt itself never has to change.

To add a new eligible cron: edit the cron's prompt to include the
sentinel line. To remove eligibility: delete the sentinel line. There
is no central file to keep in sync.

## Auto-execute sentinel (convention)

A parallel marker declares that a cron's prompt has been designed to
run fully unattended — no permission-prompt UI, no human-in-the-loop
recovery step on clean ticks. Each eligible cron carries one line in
its prompt body:

```
# auto_execute=true
```

This is a declaration, not a runtime feature. It commits the author
to:

1. **All bash surface is pre-authorized** in
   `~/.minimax/permission.json` — either via a broad wildcard like
   `python:*`, via a `cd:*`-style literal token, or via exact-string
   matchers that survive every legitimate invocation the cron makes.
2. **All file writes use Python `open(..., 'a')` append, NOT
   `Set-Content` / `Out-File` / `write` / `edit`.** See the
   2026-09-24 audit-log post-mortem in
   `agents/mavis/memory/MEMORY.md`.
3. **Output policy follows the silent-defensive-cron rule.** Clean
   ticks emit zero characters to chat. Action ticks emit ≤10 lines
   per a fixed template. The cron-watchdog's `Output policy` block is
   the canonical example.
4. **Recovery commands are surfaced, NOT auto-executed.** If the cron
   can hit a recoverable failure (missing clone, missing config,
   network down), the prompt's action template prints the recovery
   command for the user but does NOT execute it — that would require
   permission pre-auth for that command, and the audit cost of
   broadening pre-auth without a real reason is too high.

The cron's companion helper script (e.g. `scripts/agent_ops_sync.py`,
`scripts/audit_append.py`, `cron-watchdog/scripts/check_stuck.py`) is
the natural home for any bash surface that would otherwise need many
allowlist entries — one `python:*` invocation beats ten literal
matchers. Mirroring the audit-append pattern (no Set-Content, no
shell heredoc on PowerShell, append-only `open(..., 'a')`) keeps each
new helper safe to pre-auth.

To audit a cron's auto-execute eligibility, walk its prompt + SKILL.md
and:

1. Enumerate every bash command the prompt's "Steps" section can issue.
2. For each, confirm the literal command (or its substring/wildcard
   prefix) exists in `permission.json.allow`, OR replace the inline
   bash with a Python helper that matches `python:*`.
3. Confirm the prompt's "Output policy" block matches the
   silent-defensive-cron shape (clean tick = empty final message).
4. Confirm the SKILL.md's "Hard rules" forbids `Set-Content` /
   `Out-File` / `write` / `edit` on append-only logs and any other
   safety-sensitive file.
5. Only THEN add `# auto_execute=true` to the prompt.

Cróns that have NOT been audited MUST NOT carry the sentinel — it
would be a false declaration and would mislead any future auditor
that uses the sentinel as a "this is safe" signal.

## Cooldown

5-minute cooldown between archive and re-trigger for the same cron_id.
The cooldown timestamp is the last `archived=1` line in
`watchdog.log` for that cron_id. Without this, archive + immediate
re-trigger fires the new run before the user notices the old one died.

## Hard rules

- **NEVER archive a session younger than 120 min** — even if it looks
  stuck. False positives (a real long-running task) are worse than
  missed zombies.
- **NEVER call `session send` to "nudge" a stuck session.** Nudging a
  decision-looping Agent gives it more tokens to burn and doesn't fix
  the loop. The cron prompt should have prevented the loop; nudging is
  not the fix.
- **Honor the runtime's session lock.** `session update` returns 409
  when active-turn is held; that's expected for truly-stuck sessions,
  not an error to retry on.
- **Re-trigger is opt-in** — only fire when the cron carries the
  sentinel AND a SUCCESSFUL archive has happened (not on WARN, not
  while locked) AND the cooldown has cleared.
- **Audit first, mutate second** — every action goes into the log
  before the mavis call. If a mavis call fails, the log line is still
  preserved.
- **Honor the 5-min cooldown** between archive and re-trigger.
- **No file writes on clean ticks.** Pass the inventory to
  `check_stuck.py` via `--empty` (clean) or `--from-env` (action with
  content). See "Inventory delivery" above.
- **Use `bash` directly with forward-slash paths.** Do NOT wrap python
  in `powershell -Command`.

## Chat templates

```
CLEAN (tasks==[] after filter):
  (final assistant message: empty string)

WARN (any task has action=="warn"):
  WARN: <cron_id> session=<sid> age=<Xm>
  (one line per warn, cap 5 lines, then nothing else)

ARCHIVE / RETRIGGER (archive ok, optionally re-trigger):
  archived <N> retriggered <N>
  cron=<id> sid=<sid>
  (≤10 lines total; one block per archive)

LOCKED (session update returned 409 SESSION_BUSY):
  STUCK_LOCKED cron=<id> sid=<sid> — runtime owns the lock
  (do NOT retry, do NOT re-trigger)

MISSING-FIRE (stale-fire detector hit):
  WARN missing-fire cron=<id> nextRun=<iso> age=<m>min
  (one line per hit, cap 5 lines)

FATAL (script exception, MCP failure, audit log write fail):
  FATAL: <reason>
  (≤5 lines, lead with the reason)
```

## Output

- Audit log: `C:/Users/admin/research/watchdog.log` (append-only)
- Chat reply: per templates above. Clean ticks = empty string.
- No file output to the vault (this skill never writes vault/ files
  other than the watchdog.log audit line on action ticks).
