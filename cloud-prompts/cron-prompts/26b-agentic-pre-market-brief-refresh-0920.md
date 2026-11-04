# Cloud Mavis cron: agentic-pre-market-brief-refresh (cron #26b)

You are running as a Cloud Mavis cron. No local filesystem, no PowerShell, no Windows paths.
Output directory on this sandbox: `/workspace/` (Linux-style paths only; if /workspace/ does not exist, run `mkdir -p /workspace` first).

## CONVERSATION TITLE (do this FIRST, before anything else)

Every scheduled run gets its own conversation — one conversation per fire, never appended to an
earlier run's conversation. Give this conversation a title that says which day this run belongs
to, so the conversation list stays scannable.

1. Resolve today's date in US/Eastern: `TZ=America/New_York date +%d-%m` (day-month, no year).
2. Build the title: `[<DD-MM>] 26b-agentic-pre-market-brief-refresh`.
3. Set it with one call: `mcp_invoke` with tool_name `session_update` and arguments
   `{"session_id": "me", "title": "<the title>"}`. `me` means THIS conversation.
   If `mcp_invoke` reports that the tool is unknown, call `tool_search` with the query
   "session title update", then retry the same `mcp_invoke` call.
4. If the title cannot be set for any reason, carry on with the routine. This step must never
   block, delay, or fail the artifact.

## SCHEDULE

- Deployed schedule: `20 9 * * 1-5` America/New_York — 09:20 ET, Mon-Fri only.
- This is the **09:20 ET refresh** of cron #26's 08:30 ET pre-market brief. It publishes an
  addendum — a refreshed top-of-book and what moved since the morning brief — NOT a second
  brief. It does no news searching, no clustering and no rewriting.
- The day-of-week field lives in the SCHEDULER, so this routine does not fire at all on
  weekends.

## WINDOW CHECK (RUN FIRST, BEFORE FETCHING THE SKILL)

The scheduler owns the day-of-week and the hour, so this block exists for ONE reason: a cron
expression cannot express a **market holiday**, and the scheduler fires Mon-Fri *including* them.
On a holiday the market is closed and there is nothing to report.

The gate below is the ONE shared implementation for the whole fleet - fetch it and run it.
Do not inline a holiday list here: a hand-typed copy is how 21 prompts drifted into
21 different versions of the same check.

**Resolve the fire's scheduled instant FIRST, then judge the gate against it - never against
the wall clock.** The platform resumes a crashed cron conversation IN PLACE, hours or days
later, so on a replay "now" names the resume day, not the fire day. Judging by the wall clock
both skips real briefs (a Friday fire replayed on a Saturday) and publishes briefs for a
closed market (a holiday fire replayed on a trading day).

Resolve it with ONE call, no cron_read needed:

```
mcp_invoke  tool_name=session_get  arguments={"session_id":"me"}
```

Take `session.created_at` (epoch milliseconds). That is the instant the platform dispatched
THIS fire, and a later resume does not change it - so it identifies the original fire even
when the work happens hours later. Pass it as `--scheduled-at-ms`. The script prints
`fire-date:` - use THAT for the artifact path in `## OUTPUT`, so the gate and the artifact
can never disagree about which day they belong to.

```bash
# --- fetch the ONE shared window check (run-time fetch: fixes land with no redeploy) ---
# The CAPABILITY check below is mandatory, not decoration. An OLDER copy of this script is
# still published, and it silently IGNORES unknown flags - so without the check you would
# run a gate that never fires, and a holiday fire would publish a brief for a closed
# market. The CDNs also cache independently, so one of them can serve stale bytes for
# hours. The contents API is authoritative and is not CDN-cached, so it is tried FIRST.
S=/workspace/window_check.sh
for U in \
  "https://api.github.com/repos/karizaco/maxhermes-migration/contents/cloud-prompts/_shared/window_check.sh?ref=main" \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/window_check.sh" \
  "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/window_check.sh" ; do
  curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" -o "$S.tmp" "$U" 2>/dev/null
  # A 404 page is a non-empty body that is NOT a script, and an older script silently
  # ignores the flags below. Require BOTH: a real script AND the capability marker.
  if head -1 "$S.tmp" 2>/dev/null | grep -q '^#!' && grep -q 'WINDOW_CHECK_V2' "$S.tmp" 2>/dev/null; then
    mv -f "$S.tmp" "$S"; break
  fi
  rm -f "$S.tmp"
done
if [ ! -s "$S" ] || ! grep -q 'WINDOW_CHECK_V2' "$S" 2>/dev/null; then
  echo "window-check: UNAVAILABLE (no version of the shared script with the replay-aware gate)"
  echo "no artifact; no push"
  exit 1
fi

# SCHEDULED_AT_MS = session.created_at from the session_get call above (epoch ms).
sh "$S" --scheduled-at-ms "$SCHEDULED_AT_MS" \
   --out daily-briefs --name agentic_pre_market_brief_refresh \
   --label "Cron #26b agentic-pre-market-brief-refresh" \
   --nn 26b
```

If the script exits non-zero, the fire is OUT OF WINDOW: do not fetch the skill, do not write
an artifact, do not push. The skip marker it wrote IS the audit trail for this run.

**Reply format for an out-of-window skip.** The `## DELIVERY` block expects a push line and
an errors line; a skipped fire has neither an artifact nor an error. Reply with these lines
and nothing else - do not narrate the tool calls and do not write an artifact:

```
out-of-window: <reason printed by the script>
file: no artifact (window check declined this fire - daily-briefs/$DATE-pre-market.md is intentionally absent)
push: marker pushed (refs/skipped-markers/$FIRE_DATE_SKIPPED_agentic_pre_market_brief_refresh.md) | marker push FAILED | marker push skipped (skip_marker.sh unavailable)
errors: 0
```

## SHARED PROCEDURE (fetch once — this is the whole routine)

The procedure lives in ONE shared file, not in this prompt:

```bash
B=https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared
for U in "$B/premarket-refresh.md"; do
  F=/workspace/$(basename "$U")
  [ -s "$F" ] || curl -sL --max-time 30 -o "$F" "$U" 2>/dev/null
done
```

Then follow `/workspace/premarket-refresh.md` in full. It contains the inputs, the exact screen
(the universe, the liquidity gate and the quality floor are defined in cron #26's skill spec —
read them there, do not re-invent them), the output format and the push.

If that fetch fails, write a stub artifact with `_source=procedure_fetch_failed` and reply with
the failure. Do NOT improvise the procedure from memory.

## OUTPUT

Write the artifact to:
  `/workspace/daily-briefs/{date}-pre-market-refresh.md`

The `{date}` placeholder is the fire's **scheduled** date in US/Eastern, `YYYY-MM-DD`. Resolve it
from the run's `scheduled_at_ms` (`cron_read view=runs` → `run.scheduled_at_ms`), not from `date`
at execution time. If they differ, this is a **delayed replay**: rebuild for the scheduled date,
do NOT write a SKIPPED marker, and say in the artifact that it is a reconstruction produced late.
A replay is normal, not an error.
(Literal text "{date}" in this template — replace it with the actual date.)

## GIT PUSH

```bash
B=https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared
for U in "$B/push_artifact.sh" "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/push_artifact.sh"; do
  [ -s /workspace/push_artifact.sh ] || curl -sL -o /workspace/push_artifact.sh "$U"
done
# ONE --add. The script stages the routine's whole output tree, and a second --add would
# overwrite the first and wipe the routine number out of the commit subject.
sh /workspace/push_artifact.sh --out daily-briefs --add daily-briefs/{date}-pre-market-refresh.md --branch main
sh /workspace/verify_delivery.sh --path daily-briefs/{date}-pre-market-refresh.md --branch main --nn 26
```

## DELIVERY VERIFICATION (MANDATORY)

A `git push` that exits 0 is **not** proof of delivery — a push piped into `head` returns head's
exit status (always 0) and reports a rejected push as a success. `--nn 26` also checks that the
commit subject carries the routine number; exit 4 means the file is on the branch but not
attributable to cron #26, which cron #90's triage would report as MISSING. Fix forward with
another commit; never force-push `main` — `master` mirrors it fast-forward.

## CRITICAL REMINDERS

1. The procedure file above MUST be fetched first. If the fetch fails, write a stub artifact with
   `_source=procedure_fetch_failed` and reply with the failure.
2. **One pull.** Pull the screen ONCE and use it for every table and every number, including the
   prose. Cron #26 shipped an artifact that contradicted itself because two pulls fed two
   sections; do not repeat that.
3. **Never invent a number.** Every price and percentage comes from the live screen or from the
   morning brief's CSV.
4. **No catalysts.** This file reports moves, not reasons. A name that needs explaining belongs
   in the next brief.
5. The cron session is fresh each time — there is no shared state. Treat every artifact as
   ephemeral unless pushed.
6. Every percentage must trace to a fetched value. Audit before rendering.
