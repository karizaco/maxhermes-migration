# Cloud Mavis cron: schedule-drift-guard (cron #91)

You are running as a Cloud Mavis cron. No local filesystem, no PowerShell, no Windows paths.
Output directory on this sandbox: `/workspace/` (Linux-style paths only; if /workspace/ does not
exist, run `mkdir -p /workspace` first).

## CONVERSATION TITLE (do this FIRST, before anything else)

Every scheduled run gets its own conversation — one conversation per fire, never appended to an
earlier run's conversation. Give this conversation a title that says which day this run belongs
to, so the conversation list stays scannable.

1. Resolve today's date in US/Eastern: `TZ=America/New_York date +%d-%m` (day-month, no year).
2. Build the title: `[<DD-MM>] <NN>-<routine name>`. Take `<NN>` and `<routine name>` from the
   first line of this prompt (`# Cloud Mavis cron: <routine name> (cron #NN)`).
   Example: `[01-11] 91-schedule-drift-guard`.
3. Set it with one call: `mcp_invoke` with tool_name `session_update` and arguments
   `{"session_id": "me", "title": "<the title>"}`. `me` means THIS conversation.
   If `mcp_invoke` reports that the tool is unknown, call `tool_search` with the query
   "session title update", then retry the same `mcp_invoke` call.
4. If the title cannot be set for any reason, carry on with the routine. This step must never
   block, delay, or fail the artifact.

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

It has a SECOND job, added 2026-11-02: **every routine must create a NEW conversation
per fire.** A routine bound to a fixed conversation piles every run into one thread,
which breaks the "fresh session, ephemeral artifact" contract the artifact routines
depend on and makes the sidebar unreadable. Nothing else in the fleet checks this, and
a web-GUI save can flip the session binding the same way it collapses a day-of-week
field.

## FETCH FALLBACK (certificate / TLS)

Every `curl` in this routine goes to raw.githubusercontent.com or cdn.jsdelivr.net. If curl fails
with a certificate/TLS error — the sandbox egress proxy rotates its leaf cert and it has expired
mid-session before — retry the SAME url with `web_fetch`, which uses a different egress. If both
fail, say so in the reply and report `errors: 1`; do NOT report a status you did not measure.

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
# Pick the chunk that actually contains the cron_read output. `ls -t | head -1` is NOT safe:
# the newest tool-result file may belong to some other tool, and the detector then aborts on
# unparseable input. Search for a chunk containing a "tasks" array instead.
CHUNK=""
for f in $(ls -t /workspace/.mavis/tool-results/*/*/chunks/*.txt 2>/dev/null | head -20); do
  if grep -q '"tasks"' "$f" 2>/dev/null; then CHUNK="$f"; break; fi
done
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
# --- fetch tools/schedule-drift.py ---
# The CONTENTS API is authoritative and is NOT CDN-cached. The two CDNs cache `main`
# independently: measured 2026-11-04, raw.githubusercontent served a STALE blob for >17
# minutes after a push while jsDelivr was fresh. The OLD `[ -s file ] || curl` loop could
# NEVER reach its fallback - the first successful download satisfied the guard, so the
# second URL was DEAD CODE. Now all three are tried, and a 404 body (non-empty JSON) is
# rejected on its BODY, not on its byte count.
S=schedule-drift.py
for U in \
  "https://api.github.com/repos/karizaco/maxhermes-migration/contents/tools/schedule-drift.py?ref=main" \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/tools/schedule-drift.py" \
  "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/tools/schedule-drift.py" ; do
  curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" \
    -H "Authorization: Bearer ${GITHUB_TOKEN}" -o "$S.tmp" "$U" 2>/dev/null
  if [ -s "$S.tmp" ] && ! head -c 200 "$S.tmp" | grep -q '"message"'; then
    mv -f "$S.tmp" "$S"; break
  fi
  rm -f "$S.tmp"
done
# --- fetch tools/schedule-ground-truth.json ---
# The CONTENTS API is authoritative and is NOT CDN-cached. The two CDNs cache `main`
# independently: measured 2026-11-04, raw.githubusercontent served a STALE blob for >17
# minutes after a push while jsDelivr was fresh. The OLD `[ -s file ] || curl` loop could
# NEVER reach its fallback - the first successful download satisfied the guard, so the
# second URL was DEAD CODE. Now all three are tried, and a 404 body (non-empty JSON) is
# rejected on its BODY, not on its byte count.
S=schedule-ground-truth.json
for U in \
  "https://api.github.com/repos/karizaco/maxhermes-migration/contents/tools/schedule-ground-truth.json?ref=main" \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/tools/schedule-ground-truth.json" \
  "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/tools/schedule-ground-truth.json" ; do
  curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" \
    -H "Authorization: Bearer ${GITHUB_TOKEN}" -o "$S.tmp" "$U" 2>/dev/null
  if [ -s "$S.tmp" ] && ! head -c 200 "$S.tmp" | grep -q '"message"'; then
    mv -f "$S.tmp" "$S"; break
  fi
  rm -f "$S.tmp"
done
ls -l schedule-drift.py schedule-ground-truth.json
```

Then run it against the saved `cron_read` output:

```bash
# $CHUNK is the raw JSON of the cron_read view=list call from STEP 1
python3 schedule-drift.py --tasks "$CHUNK" ; echo "exit=$?"
```

Exit codes: `0` = no drift and no conversation findings, `1` = findings, `2` = input error.

**Read the prefixes, not just the exit code.** `DRIFT` is schedule drift (repairable),
`SESSION-MODE` is a conversation-binding violation (report only), `CONV-REUSE` is a
reused conversation (report only, after confirming it — see STEP 2b).

**The script may need the list envelope unwrapped.** It accepts the raw response object, a
bare list of tasks, or the tool-result chunk file. If it exits 2, print the file's first 400
characters and adapt — do not skip the check.

## STEP 2b — CONVERSATION HYGIENE (does every routine create a NEW conversation?)

Every routine must run in `session.mode: "new"` — a FRESH conversation per fire. A routine
bound to a fixed conversation piles every run into one thread, which breaks the fresh-
session contract the artifact routines depend on. Nothing else in the fleet checks this.

**2b.1 — static check (free).** The detector compares each routine's live `session.mode`
with the ground truth (expected `new`). Lines prefixed `SESSION-MODE` are violations.
**Never repair one** — a fixed-conversation binding can be deliberate. Report it.

**2b.2 — exact proof from the run history.** `cron_read {"view":"runs","task_id":"<id>"}`
returns a task's recent runs, each with its own `session_id`. Two runs of the SAME task
sharing one `session_id` means the conversation was reused. The conversation LIST cannot
prove this — the platform prunes old conversations (measured 2026-11-02: 86 conversations
survived for hundreds of fires).

Call it ONCE for EVERY routine in the list, taking the task_ids from the saved
`cron_read` list JSON (STEP 1) — never retype one from this prompt:

```
mcp_invoke  tool_name=cron_read  arguments={"view":"runs","task_id":"<task_id>"}
```

Then write ONE line per run into `/workspace/guard/runs.txt`:

```
<task_id> <session_id> <scheduled_at_ms>
```

Three values per line, copied VERBATIM from the tool output — no prose, no commas, one
run per line. Skip a routine whose call failed; never invent a line.

**2b.3 — run the detector with the table.**

```bash
cd /workspace/guard
python3 schedule-drift.py --tasks "$CHUNK" --runs-file runs.txt ; echo "exit=$?"
```

**2b.4 — CONFIRM before reporting.** A `CONV-REUSE` line rests on numbers you copied by
hand. Re-read that routine's runs with a FRESH `view=runs` call first: the same
`session_id` twice → REUSE CONFIRMED, report it with the session_id and the two
scheduled times. Different ids → your table had a typo; drop the finding and say
nothing. A false "reuse" accusation is worse than no check at all.

Carry the detector's count into the reply: `CONVERSATIONS <n> routines checked, <m> recent
run(s), <k> distinct conversation(s)`.

## STEP 2c — PROMPT DRIFT (repo vs deployed)

**Why this matters more than schedule drift.** A wrong schedule makes a routine fire on the wrong
day — loud, visible, and fixed within a day. A *stale prompt* makes the routine run perfectly on
the right day, with wrong instructions, producing plausible-looking wrong output — silent.

Measured 2026-11-02: **21 of 23 deployed prompts no longer matched their repo file**, and 18 still
asserted a dead connector-catalog composition and a dead Yahoo-429 condition that the repo had
already corrected three days earlier. The repo looked finished; the fleet was not running it.
That gap is exactly what this step makes visible.

```bash
# $CHUNK is the raw JSON of the cron_read view=list call from STEP 1
# The repo is NOT present in a fresh cron sandbox — clone it first.
mkdir -p /workspace/guard
if [ ! -d /workspace/guard/mig/.git ]; then
  git clone -q --depth 1 https://github.com/karizaco/maxhermes-migration.git /workspace/guard/mig 2>/dev/null \
    || git clone -q --depth 1 https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main /workspace/guard/mig 2>/dev/null \
    || echo "PROMPT-DRIFT-CHECK-FAILED: repo clone failed"
fi
REPO="${REPO:-/workspace/guard/mig}"
python3 - "$CHUNK" "$REPO" <<'PYEOF'
import hashlib, json, os, sys, urllib.parse
chunk, repo = sys.argv[1], sys.argv[2]
try:
    raw = open(chunk, encoding="utf-8", errors="replace").read()
    tasks = json.loads(raw).get("response", {}).get("tasks") or json.loads(raw).get("tasks") or []
except Exception as exc:
    print(f"PROMPT-DRIFT-CHECK-FAILED: {exc}"); raise SystemExit(0)

drift = 0
for t in tasks:
    name = urllib.parse.unquote(t.get("cron_name", ""))
    path = os.path.join(repo, "cloud-prompts", "cron-prompts", name)
    if not os.path.exists(path):
        path = os.path.join(repo, "cloud-prompts", name)
    if not os.path.exists(path):
        continue
    local = open(path, "rb").read()
    deployed = (t.get("prompt") or "").encode()
    if hashlib.sha256(local).hexdigest() != hashlib.sha256(deployed).hexdigest():
        drift += 1
        print(f"PROMPT-DRIFT {name}: repo {len(local)}B vs deployed {len(deployed)}B")
print(f"prompt drift: {drift} of {len(tasks)} deployed prompts differ from the repo")
PYEOF
```

Report every `PROMPT-DRIFT` line. A drift is NOT repaired here — the repo is the source of truth,
so the fix is to deploy the repo file, byte-exactly, and re-verify. Say which routines are
affected.

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

- **No drift and nothing else happened:** reply with exactly three lines:
  ```
  schedule guard: OK — <n> routines match the ground truth
  drift: 0
  conversation guard: OK — <routines checked> routines, <fires> recent runs, all created a new conversation
  ```
  `<n>` is the count the detector printed (`checked N routines against the ground truth`) — never a
  hardcoded fleet size, which goes stale whenever a routine is added, removed or recreated.
  The conversation line comes from the detector's `CONVERSATIONS ...` line. If the
  conversation check could not run (no run table, the fetch failed), say
  `conversation guard: NOT CHECKED — <reason>` instead of claiming OK.
- **Conversation findings (schedule is fine):** report them as their own block:
  ```
  schedule guard: OK — <n> routines match the ground truth
  conversation guard: <n> routine(s) are NOT creating a new conversation
  <name>: mode='<live>' expected 'new' (task_id <id>)
  <name>: conversation <session_id> used by 2 runs (scheduled <ts1> and <ts2>) — REUSE CONFIRMED
  ```
  Name the routine, the task_id, and the session_id. Say what it means in one clause:
  every run of that routine lands in the same thread instead of a fresh one.
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
- **No drift, but something else happened** — you changed this routine's own prompt, or you found a
  repo-level staleness that is NOT a schedule drift (a stale doc, a generator bug, a roster that
  contradicts the ground truth): report it in the rich format the user expects — a 2–4 sentence prose
  opener carrying the headline AND the caveat that changes how it should be read, then `### Signal`,
  `### Method & caveats`, `### Files`, `### Push / errors`. Cap by NAMES SHOWN, not by lines; the long
  detail belongs in the repo, not the chat. Do NOT pad a clean drift check into a report: if the only
  news is "no drift", use the two lines above.

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
9. **Never repair a session binding.** `cron_update` could rewrite `session.mode`, but a
   fixed-conversation routine can be a deliberate choice. Report it; let the user decide.
10. **Confirm every CONV-REUSE finding with a fresh `view=runs` call before reporting it.**
    The run table is copied by hand. A typo must not become a false accusation.
11. **Never invent a run-table line.** If a `view=runs` call fails, the routine simply has
    no evidence in this cycle — that is not a finding.

================================================================
END OF CRON PROMPT
================================================================