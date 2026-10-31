# Bug report — web GUI save silently corrupts a scheduled task's day-of-week field

**Submit via:** the app's **Feedback** dialog (user menu → Help, or a task's top bar, or a
session in the sidebar — it auto-attaches task context and diagnostics), or email
**MiniMaxCode@minimax.io** (per the MiniMax AI App and Web Terms of Service).

**Title:** Saving a scheduled task in the web GUI silently changes its cron day-of-week from
`1-5` (Mon–Fri) to `1` (Mondays only), even when the schedule is not edited

**Severity:** High — silent data loss of schedule. A weekday routine stops firing on four of
its five days with no error, no visible change in the GUI, and no change in `next_run`.

---

## Summary

Editing a scheduled task at `https://agent.minimax.io` and clicking **Save** rewrites the
task's cron expression's **day-of-week field** from a range to a single day. The task's
minute, hour, timezone, prompt, model and other fields are unaffected, and the schedule
control is not the field the user touched.

The web UI's day-of-week control appears to be a **single-select dropdown** that cannot
represent a range. When the form is loaded for a task whose schedule is `1-5`, the control
holds only one day (Monday), and the save writes that single day back as the task's
day-of-week field.

## Steps to reproduce

1. Create (or migrate in) a scheduled task with a weekday schedule, e.g. `30 8 * * 1-5`
   (08:30, Mon–Fri), timezone `America/New_York`.
2. Open the task in the web GUI and click **Edit**.
3. Change **only** the model or the model effort (e.g. `thinking.effort` medium → high).
   Do **not** touch the schedule.
4. Click **Save**.
5. Read the task back (`cron_read`, `view:"list"`): `schedule` is now `30 8 * * 1`.

## Expected behaviour

Saving a task must not modify fields the user did not change. A task whose schedule is
`1-5` must keep `1-5` after an edit to its model.

## Actual behaviour

`schedule` changes from `30 8 * * 1-5` to `30 8 * * 1`. The task now fires **Mondays only**.

## Why it is silent — this is the worst part

- **`next_run` does not change.** Both `* * 1` and `* * 1-5` next-fire on the coming Monday,
  so `next_run` still reads `2026-11-02 08:30 ET`. Any health check that compares
  `next_run`, or that reads the GUI's "next run" line, sees a healthy task.
- **The GUI shows a plausible schedule** after the save — a single day, which looks like a
  deliberate weekly schedule rather than a corrupted one.
- **The task still fires.** It fires every Monday, so it keeps producing artifacts and looks
  alive. The gap only appears on Tuesday, when it silently does not fire, and it is
  indistinguishable from a routine that was "supposed" to run weekly.
- **The agent's own prompt still says `1-5`.** The prompt, the roster and the auditor's
  contract all say Mon–Fri while the scheduler says Monday, so every downstream check
  disagrees with reality.

## Observed occurrences (2026-10-31)

**Single occurrence, controlled test** — cron `#26-agentic-pre-market-brief.md`,
`task_id 457175063601252`:

| Field | Before | After GUI save |
|---|---|---|
| `schedule` | `30 8 * * 1-5` | **`30 8 * * 1`** |
| `model.thinking.effort` | `medium` | `high` (the intended change) |
| `model.thinking_effort` | `medium` | `high` |
| `timezone` | `America/New_York` | `America/New_York` |
| `enabled` | `true` | `true` |
| `project_id` | `10645` | `10645` |
| `task_id` | `457175063601252` | `457175063601252` |
| `created_at` | `2026-10-28 02:10:44 ET` | `2026-10-28 02:10:44 ET` |
| `next_run` | `2026-11-02 08:30 ET` | `2026-11-02 08:30 ET` (unchanged) |
| `prompt` (SHA-256) | `0452762f…d07001` | `0452762f…d07001` (unchanged) |
| `updated_at` | `2026-10-31 09:26:27 ET` | `2026-10-31 10:07:24 ET` |

**Fleet-wide occurrence** — between **05:40 and 09:08 ET on 2026-10-31**, the same corruption
was applied to **fourteen** weekday routines in a sequential sweep, each collapsing to exactly
`1`:

`#02` `30 6` · `#04` `55 15` · `#07` `45 9` · `#08` `30 8` · `#09` `30 18` · `#10` `0 14` ·
`#12` `0 10` · `#16` `35 16` · `#17` `50 15` · `#19` `0 6` · `#20` `0 16` · `#23` `30 22` ·
`#25` `0 9` · `#26` `30 8`

Unaffected: `#05` and `#15` (both already `1-5` at the time), and the weekly routines
`#01` (Sun), `#06` (Sat), `#13` (Wed), `#14` (Sun), `#22` (Sun) and the daily `#90` — their
single-day fields were already single, so a single-select control had nothing to truncate.
This is consistent with the "the control can only hold one day" hypothesis: every task whose
field was a range lost days; every task whose field was already a single day was untouched.

## Additional observation — the same corruption was seen earlier

On **2026-10-29** two routines (`#15-earnings-reaction-scanner`, `#19-earnings-reminder-daily`)
were also found as `0 8 * * 1` and `0 6 * * 1` (Mondays only) while their prompts, the roster
and the delivery history all said Mon–Fri. They were corrected to `1-5`. That history was
recorded as an unexplained one-off at the time; the controlled reproduction above shows it is
this bug.

## Requested fix

Any one of these would prevent the corruption:

1. **Preserve unmodified fields on save.** The PATCH should only write fields the form
   actually changed — the same partial-update semantics the MCP `cron_update` tool has.
2. **Support multi-day selection** in the schedule control (checkboxes for Mon–Sun), and
   round-trip `1-5` faithfully.
3. **At minimum, validate on save**: if the submitted day-of-week is a single day but the
   stored value was a range covering more days, and the user did not touch the schedule
   field, keep the stored range — or prompt the user to confirm the narrowing.

Also worth fixing: the GUI should not present a corrupted `1` schedule as an ordinary weekly
schedule, and `next_run` should be recomputed from the saved value so a narrowed schedule
becomes visible immediately (it currently reads the same Monday for both `1` and `1-5`).

## Workaround in use

Schedules are edited through the MCP `cron_update` tool (partial update: `task_id`,
`schedule`, `timezone` only). That path preserves the model, the prompt, the project, the
session binding and the run history, and it accepts `1-5` correctly. A daily checker compares
every live schedule against a stored ground truth and repairs any drift automatically.

## Environment

- Product: MiniMax Agent / MiniMax Code Cloud (`agent.minimax.io`)
- Component: Scheduled Tasks (web GUI)
- Date observed: 2026-10-31
- Schedule field format: standard 5-field cron (`m h dom mon dow`), timezone `America/New_York`
- Affected routine count observed: 14
