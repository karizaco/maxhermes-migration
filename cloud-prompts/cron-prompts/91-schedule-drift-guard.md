# Cloud Mavis cron: schedule-drift-guard (cron #91)

You are running as a Cloud Mavis cron. No local filesystem, no PowerShell, no Windows paths.
Output directory on this sandbox: `/workspace/` (Linux-style paths only; if /workspace/ does not
exist, run `mkdir -p /workspace` first).

## WHAT THIS CRON IS FOR

The web GUI at agent.minimax.io **silently corrupts the day-of-week field** of a weekday
scheduled task when you save it. Measured 2026-10-31, two independent times:

1. A routine with the live schedule `30 8 * * 1-5` (Mon-Fri) came back as `30 8 * * 1`
   (Mondays only) after a GUI save that changed **only the model effort** — nothing about the
   schedule was touched.
2. The same corruption hit **fourteen** routines in a sequential sweep between 05:40 and 09:08
   ET, all collapsing to exactly `1`.

The corruption is silent. `next_run` does NOT change (both `1` and `1-5` next-fire on the
coming Monday), so neither the GUI nor a next_run check reveals it. The damage only shows up on
Tuesday, when a Monday-only routine quietly does not fire — the routine then looks "healthy"
because it fires every Monday and simply skips four days a week.

This cron is the detector and the repairer. It compares the LIVE scheduler against the
ground truth and fixes any mismatch, then tells the user.

## SCHEDULE
- Deployed schedule: `5 4 * * *` America/New_York — 04:05 ET daily.
- It runs early and daily on purpose: a corruption must be found and fixed **before** the
  weekday routines fire. #19 fires at 06:00 ET, so a 04:05 check has almost two hours of
  headroom.
- Session mode: `new` — every fire starts a clean conversation.
- The schedule field above is a DAILY cron (`* * *`), so this routine is immune to the very
  bug it hunts: a GUI save cannot collapse `* * *` into a narrower day set.

## THE GROUND TRUTH

`tools/schedule-ground-truth.json` in `karizaco/maxhermes-migration` is the ground truth.

**Never derive the expected schedule from the live scheduler, and never from the GUI.** The
live scheduler IS the thing that gets corrupted, and the GUI is the thing that corrupts it.
The ground truth was reconstructed from `migration-state.json` (the 2026-09-25 snapshot of the
source `mavis cron list` — the ORIGINAL local Windows crons of record) plus the deliberate
post-migration changes. Every weekday routine in it is `1-5`; only genuinely weekly routines
carry a single day.

## STEP 1 — GET THE LIVE SCHEDULER STATE

The whole fleet comes back in ONE call:

```bash
mkdir -p /workspace/guard
```

Then, as your FIRST tool call, run:

```
mcp_invoke  tool_name=cron_read  arguments={"view":"list","limit":100}
```

**The response is large (~450 KB) and the tool output is TRUNCATED.** Do not try to read the
schedule out of the inline preview — you will read the wrong task. The full JSON is persisted
to a file on disk. Find it and parse it:

```bash
# the newest tool-result chunk file holds the raw JSON of the cron_read above
CHUNK=$(ls -t /workspace/.mavis/tool-results/*/*/chunks/*.txt 2>/dev/null | head -1)
if [ -z "$CHUNK" ]; then
  echo "ERROR: cron_read output not found on disk"
else
  echo "chunk: $CHUNK"
  wc -c "$CHUNK"
fi
```

If `.mavis/tool-results` is not present in this sandbox, fall back to calling `cron_read` with
`view:"detail"` and one `task_id` per routine (see the task list in the ground-truth file) and
assemble the result by hand. That is slower but equivalent. **Never guess a schedule — read it.**

## STEP 2 — RUN THE DETECTOR

The detector lives in the same repo and is the authoritative implementation. Fetch it and run
it:

```bash
cd /workspace/guard
for U in \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/tools/schedule-drift.py" \
  "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/tools/schedule-drift.py" \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/tools/schedule-ground-truth.json" ; do
  case "$U" in
    *.py)   [ -s schedule-drift.py ]        || curl -sL --max-time 30 -o schedule-drift.py "$U" ;;
    *.json) [ -s schedule-ground-truth.json ] || curl -sL --max-time 30 -o schedule-ground-truth.json "$U" ;;
  esac
done
ls -l schedule-drift.py schedule-ground-truth.json
```

Then run it against the saved `cron_read` output:

```bash
# $CHUNK is the raw JSON of the cron_read view=list call from STEP 1
python3 schedule-drift.py --tasks "$CHUNK" ; echo "exit=$?"
```

Exit codes: `0` = no drift, `1` = drift found, `2` = input error.

**The script may need the list envelope unwrapped.** It accepts the raw response object, a
bare list of tasks, or the tool-result chunk file. If it exits 2, print the file's first 400
characters and adapt — do not skip the check.

## STEP 3 — REPAIR ANY DRIFT

For each routine the detector reports as DRIFT, call:

```
mcp_invoke  tool_name=cron_update  arguments={"task_id":"<id>","schedule":"<expected>","timezone":"America/New_York"}
```

Rules that matter:

- **Send ONLY `task_id`, `schedule` and `timezone`.** Never send `enabled` (the transport
  coerces it to the string `"true"` and validation fails) and never send `model` (the MCP tool
  has no such field). A partial update preserves everything else — verified 2026-10-31 on cron
  #26: repairing the schedule left `thinking.effort: high` and the prompt bytes untouched, and
  preserved `task_id`, `created_at`, `project_id` and the session binding.
- **Always send `timezone`.** Omitting it silently resets the timezone to `Etc/GMT-7`, which
  in POSIX means **UTC+7** — an 11-hour error that fires routines after market close.
- The repair is safe and idempotent: it rewrites only the scheduler's `schedule` and
  `timezone` fields. It does not touch the prompt, the model, the project, the session mode,
  or the run history.

After repairing, VERIFY — a successful `{"ok": true}` only means the write landed:

```
mcp_invoke  tool_name=cron_read  arguments={"view":"detail","task_id":"<id>"}
```

Confirm the returned `schedule` equals the expected value and `timezone` is
`America/New_York`. If it still differs, retry ONCE. If it still differs, report the failure
and stop — do not loop.

## STEP 4 — NOTIFY THE USER (only when something happened)

The reply is delivered to the user's chat. **Stay silent-ish when there is nothing to say** —
a daily "everything is fine" message trains the user to ignore this routine, which is exactly
how the #14 gap stayed invisible for a cycle.

- **No drift:** reply with exactly two lines:
  ```
  schedule guard: OK — 22 routines match the ground truth
  drift: 0
  ```
- **Drift found and repaired:** report it properly, because it is a real finding:
  ```
  schedule guard: DRIFT REPAIRED — <n> routine(s) had a corrupted day-of-week field
  repaired: <name> (<live> -> <expected>)
  cause: a web-GUI save collapses the day-of-week field to a single day; this routine restored it
  next check: daily 04:05 ET
  ```
  If more than one routine drifted, list every one.
- **Drift found but NOT repaired:** say so plainly and name each routine:
  ```
  schedule guard: DRIFT NOT REPAIRED — <n> routine(s) still wrong
  <name>: live <live> expected <expected> (task_id <id>)
  ```
  and state the likely cause (a GUI save) plus the fact that these routines will NOT fire on
  their other weekdays until fixed.

## WHAT TO TELL THE USER ABOUT THE ROOT CAUSE

If you repaired anything, add ONE line naming the mechanism, because the user needs to know
that saving in the web GUI is unsafe:

```
note: web-GUI saves corrupt the day-of-week field of weekday routines — change model/effort via this cron or ask me, not via the GUI
```

## CRITICAL REMINDERS
1. **The ground truth is the ground truth.** Never regenerate the expected schedule from the
   live scheduler — that would make the check agree with the corruption and report "OK" while
   fourteen routines are Monday-only.
2. **Read the schedules from the persisted JSON, not the inline preview.** The inline
   `cron_read` output is truncated and the truncation drops the middle of the list.
3. **Never send `enabled` or `model` to `cron_update`.** `enabled` is coerced to the string
   `"true"` and fails validation; `model` does not exist on the tool.
4. **Always send `timezone: America/New_York` together with `schedule`.** Omitting it resets
   the timezone to `Etc/GMT-7` (UTC+7).
5. **A partial update preserves the model.** This is what makes the GUI workaround possible:
   the user changes the effort in the GUI, then this cron repairs the schedule without
   disturbing the new effort.
6. **Do not repair a routine whose ground-truth entry you cannot read.** If the ground-truth
   file is missing or a routine is UNKNOWN, report it and stop — do not guess a schedule.
7. **If the detector itself cannot run** (fetch failed, parse error), fall back to comparing
   each routine's live schedule against the ground-truth JSON by hand with python, and say in
   the reply that you did it manually.
8. **This routine is read-only with respect to artifacts.** It writes nothing to the outputs
   repo and pushes nothing. It only reads the scheduler and writes the scheduler's own
   schedule field.

================================================================
END OF CRON PROMPT
================================================================