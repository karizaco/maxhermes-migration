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
- The day-of-week field lives in the SCHEDULER, so this routine does not fire at all on weekends.

## SHARED PROCEDURE (fetch once — this is the whole routine)

The procedure lives in ONE shared file, not in this prompt. It contains the window check, the
inputs, the screen to pull, the output format and the push.

```bash
B=https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared
# --- fetch cloud-prompts/_shared/premarket-refresh.md ---
# The CONTENTS API is authoritative and is NOT CDN-cached. The two CDNs cache `main`
# independently: measured 2026-11-04, raw.githubusercontent served a STALE blob for >17
# minutes after a push while jsDelivr was fresh. The OLD `[ -s file ] || curl` loop could
# NEVER reach its fallback - the first successful download satisfied the guard, so the
# second URL was DEAD CODE. Now all three are tried, and a 404 body (non-empty JSON) is
# rejected on its BODY, not on its byte count.
S=/workspace/premarket-refresh.md
for U in \
  "https://api.github.com/repos/karizaco/maxhermes-migration/contents/cloud-prompts/_shared/premarket-refresh.md?ref=main" \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/premarket-refresh.md" \
  "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/premarket-refresh.md" ; do
  curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" \
    -H "Authorization: Bearer ${GITHUB_TOKEN}" -o "$S.tmp" "$U" 2>/dev/null
  if [ -s "$S.tmp" ] && ! head -c 200 "$S.tmp" | grep -q '"message"'; then
    mv -f "$S.tmp" "$S"; break
  fi
  rm -f "$S.tmp"
done
```

Then follow `/workspace/premarket-refresh.md` in full, starting with its STEP 0 window check.

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
sh /workspace/verify_delivery.sh --path daily-briefs/{date}-pre-market-refresh.md --branch main --nn 26b
```

## DELIVERY VERIFICATION (MANDATORY)

A `git push` that exits 0 is **not** proof of delivery — a push piped into `head` returns head's
exit status (always 0) and reports a rejected push as a success. `--nn 26b` also checks that the
commit subject carries the routine number; exit 4 means the file is on the branch but not
attributable to this routine, which cron #90's triage would report as MISSING. Fix forward with
another commit; never force-push `main` — `master` mirrors it fast-forward.

## CRITICAL REMINDERS

1. The procedure file above MUST be fetched first, and its STEP 0 window check runs before
   anything else. If the fetch fails, write a stub artifact with
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
