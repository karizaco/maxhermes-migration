# Cloud Mavis cron: delivery-auditor (cron #90)

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
   Example: `[31-10] 12-cross-asset-correlation-snapshot`.
3. Set it with one call: `mcp_invoke` with tool_name `session_update` and arguments
   `{"session_id": "me", "title": "<the title>"}`. `me` means THIS conversation.
   If `mcp_invoke` reports that the tool is unknown, call `tool_search` with the query
   "session title update", then retry the same `mcp_invoke` call.
4. If the title cannot be set for any reason, carry on with the routine. This step must never
   block, delay, or fail the artifact.

## FETCH FALLBACK (certificate / TLS)

Every `curl` in this routine goes to the GitHub **contents API** first — it is the only source
that is not CDN-cached — with raw.githubusercontent.com and cdn.jsdelivr.net as fallbacks. If curl
fails with a certificate/TLS error — the sandbox egress proxy rotates its leaf cert and it has
expired mid-session before — retry the SAME url with `web_fetch`, which uses a different egress.
If both fail, say so in the reply and report `errors: 1`; do NOT report a status you did not
measure.

## SCHEDULE
- Deployed schedule: `0 7 * * *` America/New_York — 07:00 ET daily.
- Runs at 07:00 ET, which is AFTER every routine that fires before it (the earliest is 06:00 ET,
  #19) and BEFORE the routines that fire later in the day. It therefore catches the whole
  previous US trading day's early-morning artifacts, and the routines that fire between 07:00
  and 22:30 are audited by the NEXT day's run.
- Session mode: `new` — every fire starts a clean conversation, and the run sets that
  conversation's title to `[DD-MM] NN-<routine name>` so the list shows which day it belongs to.

## THE PROCEDURE (fetch once — this is the whole routine)

The procedure lives in ONE file, not in this prompt. Fetch it and follow it in full. It
carries everything else: the roster table, the stale check, the gap diagnosis, the
`skipped_by_design` and `roster_gap` checks, the cause vocabulary, the status schema and
the contract gate.

```bash
# --- fetch cloud-prompts/_shared/auditor-procedure.md ---
# FOUR sources, and the MARKER is mandatory, not decoration.
#
# An OLDER copy of the procedure is still published, and the two CDNs cache `main`
# INDEPENDENTLY - measured 2026-11-04, raw.githubusercontent served a stale blob for
# >17 minutes after a push while jsDelivr was fresh. Without the marker check you would
# silently run the OLD procedure and believe it was the new one.
#
# The contents API is authoritative and is NOT CDN-cached, so it is tried FIRST. The git
# blob API for the sha the contents API's metadata names is tried SECOND: that blob IS
# the tip of `main`, so its version is never lower than any mirror's. Only then the two
# CDNs. If every copy carries the marker, the HIGHEST PROCEDURE_VERSION wins.
rm -f /tmp/ap_a.md /tmp/ap_b.md /tmp/ap_c.md /tmp/ap_d.md
AP_SHA=$(curl -sL --max-time 30 -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer ${GITHUB_TOKEN}" \
  "https://api.github.com/repos/karizaco/maxhermes-migration/contents/cloud-prompts/_shared/auditor-procedure.md?ref=main" 2>/dev/null \
  | python3 -c "import json,sys; print(json.load(sys.stdin).get('sha',''))" 2>/dev/null)
if [ -n "$AP_SHA" ]; then
  curl -sL --max-time 30 -H "Accept: application/vnd.github+json" \
    -H "Authorization: Bearer ${GITHUB_TOKEN}" \
    "https://api.github.com/repos/karizaco/maxhermes-migration/git/blobs/$AP_SHA" 2>/dev/null \
    | python3 -c "import json,sys,base64; sys.stdout.write(base64.b64decode(json.load(sys.stdin)['content']).decode('utf-8','replace'))" \
    > /tmp/ap_d.md 2>/dev/null
fi
curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" \
  -H "Authorization: Bearer ${GITHUB_TOKEN}" \
  -o /tmp/ap_c.md \
  "https://api.github.com/repos/karizaco/maxhermes-migration/contents/cloud-prompts/_shared/auditor-procedure.md?ref=main" 2>/dev/null
curl -sL --max-time 30 -o /tmp/ap_a.md \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/auditor-procedure.md" 2>/dev/null
curl -sL --max-time 30 -o /tmp/ap_b.md \
  "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/auditor-procedure.md" 2>/dev/null
python3 - <<'PYEOF'
import re
best=None;bv=None
for f in ("/tmp/ap_d.md","/tmp/ap_c.md","/tmp/ap_a.md","/tmp/ap_b.md"):
    try: t=open(f,encoding="utf-8",errors="replace").read()
    except Exception: continue
    if not t.strip() or t.lstrip()[:200].find('"message"')>=0: continue
    if "AUDITOR_PROCEDURE_V" not in t: continue
    m=re.search(r"PROCEDURE_VERSION:\s*(\d{4})-(\d{2})-(\d{2})\.(\d+)",t)
    v=(int(m.group(1)+m.group(2)+m.group(3)),int(m.group(4))) if m else (0,0)
    if bv is None or v>bv: bv=v;best=f
if best:
    # read+write, NOT os.replace: /tmp and /workspace can be DIFFERENT filesystems and
    # rename(2) across them fails with EXDEV (caught 2026-11-04).
    open("/workspace/auditor-procedure.md","w",encoding="utf-8").write(
        open(best,encoding="utf-8",errors="replace").read())
    print("procedure: version %s.%s from %s"%(bv[0],bv[1],best))
else:
    open("/workspace/auditor-procedure.md","w").write("PROCEDURE_FETCH_FAILED\n")
    print("procedure: FETCH FAILED")
PYEOF
```

Then read `/workspace/auditor-procedure.md` and follow it in full. Do NOT improvise any part
of it from memory — the roster, the states, the cause vocabulary and the status schema are
all in there, and the gate (STEP 6b) checks the audit against them.

**If the fetch failed** (`PROCEDURE_FETCH_FAILED`, or the file carries no
`AUDITOR_PROCEDURE_V` marker): you cannot audit safely. Do NOT publish a status file, do
NOT guess a roster, do NOT reuse yesterday's classifications. Reply with exactly:

```
audit: <AUDIT_DATE> due=0 delivered=0 missing=0
push: skipped (procedure fetch failed)
errors: 1
```

and stop. A missing audit is visible; a wrong audit is not.


## DELIVERY

**This routine is one of the five documented reply-format exceptions** (see
`cloud-prompts/cron-prompts/README.md`): its output is machine-read, so it does NOT use the
standard prose-opener / `### Signal` / `### Method & caveats` format. It MUST be:

  - **≤ 8 lines of FRAMING** — the summary, the push line and the errors line. The per-item
    lines below are additional, one line each, and are NEVER merged, truncated or dropped: a
    routine with a gap is worth more than the line budget. The cap that matters is "no prose
    padding".
  - One line: `audit: <AUDIT_DATE> due=<n> delivered=<n> missing=<n>` — **unchanged**. `missing`
    counts MISSING gaps only: a routine that skipped by design is NOT missing.
  - One line per gap: `gap: <routine> <label> <path> — cause=<token> age_h=<n> — <detail>`
    (the cause comes from STEP 4c-1 and is ALWAYS one of the vocabulary tokens; the age in
    hours comes from STEP 4c-2. The detail is the evidence — what happened, and what the
    rebuild changed. Omit the detail only when there is nothing to add.)
  - One line per deliberate skip: `skipped: <routine> <reason> — <marker path>` (the reason is mandatory; the marker path is there when the routine wrote one).
  - One line per unmonitored routine: `roster_gap: <name> (task <id>) is live but not in schedule-ground-truth.json`
  - One line per dead routine (streak ≥ 3): `streak: <routine> <n> consecutive missed fires`
  - One line: `push: ok (verified)` / `push: skipped (token unset)` / `push: FAILED (<reason>)`
  - One line: `errors: <n>` — count of audit errors. 0 = clean audit. **A gap line with no
    cause is `errors: 1`, not `errors: 0`.**

**If there are no gaps, say so in one line and stop.** Do not pad the reply with counts of
routines that are `not_due` — those are working as designed, not news. A routine that skipped
by design is also not news UNLESS it is one of the failures the operator has been told about
before; it gets its `skipped:` line, not a paragraph.

No preamble. Tool call → result → write → gate → push → reply.

## CRITICAL REMINDERS
1. **This cron is read-only with respect to the artifacts.** It clones, checks, writes a local
   status file, and optionally pushes to the `audit/status` branch. It never modifies, deletes
   or re-pushes any routine's artifact, and it never pushes to `main`. Its ONLY write to the
   repo is a fast-forward of the `master` branch pointer to `main` (see STEP 2 in the procedure) - that moves
   a ref, it does not touch a file.
2. **A gap is a finding, not a failure of this run.** Do not attempt to re-run, re-create, or
   repair the missing artifact. Report it precisely — routine, label, exact path — and stop.
   The user decides what to do about it.
3. **Never report a routine as `MISSING` when its schedule does not fire on that weekday.**
   Check the "Fires on" column and the holiday list before labelling anything. For audit dates
   before 2026-10-29, #15 and #19 were Mondays-only, and before 2026-10-31, #07/#10/#12/#17/#26
   were daily — see the SCHEDULE CHANGES block in the procedure. The roster table there is the contract for
   every date from 2026-10-31 onward.
4. **Name the cause of every gap** (STEP 4c-1 in the procedure). "MISSING" alone is not an answer; "quota
   exhausted (2067)" and "push failed" need different fixes.
5. **Do not fabricate a status.** If the repo could not be cloned, the status is
   `failed_no_repo` and `errors: 1`. If the token is missing, `skipped_no_token`.
6. **Run the STEP 4b stale check every time.** A routine that is `not_due` on the audited
   day may still be permanently broken — that is exactly how cron #22 went unnoticed for
   months. `NEVER_DELIVERED` is a MISSING finding, not a footnote — unless the routine's
   first fire date has not arrived yet (`not_yet_fired`), which is not a finding at all.
7. **A `MISSING` artifact on a day when the routine ran and reported success means the push
   silently failed** — the old `git add -A` block could stage deletions and abort, or the
   `|| echo` could mask the error. Name it clearly; that is the whole point of this cron.
8. **A routine that RAN and correctly wrote NOTHING is `skipped_by_design`, never `missing`**
   (STEP 4d in the procedure). This is the exact mis-classification this routine exists to prevent: the
   2026-11-03 audit reported #92a and #92b as `not_yet_fired` on a day they had fired and had
   correctly produced no artifact. It needs a reason, quoted from the evidence — never invented.
9. **Run the STEP 4e roster check (in the procedure) every time.** A live routine that is missing from
   `tools/schedule-ground-truth.json` is UNMONITORED: this audit never checks it, cron #91's
   drift guard cannot repair it, and both report a clean fleet. #26b was in exactly that state
   on 2026-11-03. The check now exists and must run on every audit, even when it finds
   nothing.
10. **A gap line without a cause from the vocabulary is `errors: 1`, not `errors: 0`** (STEP
    4c-1). "MISSING" alone is not an answer, and a gap with an empty reason is a failed audit.
11. **Run the STEP 6b gate (in the procedure) before the push.** The gate checks the very bytes that get
    published. Fix what it reports; if it still fails, publish anyway with `errors:` set to
    the number of failures — a broken audit trail is worse than an imperfect one.

================================================================
END OF CRON PROMPT
================================================================
