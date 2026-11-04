# Cloud Mavis cron: agentic-pre-market-brief (cron #26)

You are running as a Cloud Mavis cron. No local filesystem, no PowerShell, no Windows paths.
Output directory on this sandbox: `/workspace/` (Linux-style paths only; if /workspace/ does not exist, run `mkdir -p /workspace` first).

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

## SCHEDULE
- Original local schedule: `37 7 * * 1-5` America/New_York — 07:37 ET weekdays. The first Cloud
  deployment ran `30 7 * * 1-5` (07:30 ET); the run history for 2026-10-28 → 2026-10-30 shows
  07:30 ET.
- Deployed schedule: `30 8 * * 1-5` America/New_York — 08:30 ET, Mon-Fri only.
  Moved from 07:30 ET on 2026-10-31 so the artifact lands AFTER cron #19's 06:00 ET earnings
  reminder: cron #19 publishes `earnings/{date}-reminders.md` on the outputs repo and the skill
  spec reads that file for §9. The ordering is the point — do not move this fire earlier than
  06:30 ET, and do not move it back to 07:30 without re-checking that dependency.
- The day-of-week field is set in the SCHEDULER, so this routine does not fire at all on
  weekends: no agent invocation is spent discovering it is a weekend, and no weekend SKIPPED
  file is written. The WINDOW CHECK below keeps the one guard a cron expression cannot
  express — the market-holiday list.
- There is no pre-market session on a weekend and this brief has no weekend edition, so it does
  not run on Saturday or Sunday at all. The daily WEEKEND brief was retired on 2026-10-31; there
  is no weekend mode in this prompt.

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
   --out daily-briefs --name agentic_pre_market_brief \
   --label "Cron #26 agentic-pre-market-brief" \
   --nn 26
```

If the script exits non-zero, the fire is OUT OF WINDOW: do not fetch the skill, do not write
an artifact, do not push. The skip marker it wrote IS the audit trail for this run.

**Reply format for an out-of-window skip.** The `## DELIVERY` block expects a push line and
an errors line; a skipped fire has neither an artifact nor an error. Reply with these lines
and nothing else - do not narrate the tool calls and do not write an artifact:

```
out-of-window: <reason printed by the script>
file: no artifact (window check declined this fire - daily-briefs/$DATE-pre-market.md is intentionally absent)
push: marker pushed (refs/skipped-markers/$FIRE_DATE_SKIPPED_agentic_pre_market_brief.md) | marker push FAILED | marker push skipped (push script unavailable)
errors: 0
```


## SKILL SPEC (FETCH ONCE)
The skill's procedure body lives here:
  https://api.github.com/repos/karizaco/maxhermes-migration/contents/cloud-prompts/skills/agentic-pre-market-brief/SKILL.md?ref=main

**FIRST tool call:** `curl -sL -H "Accept: application/vnd.github.raw" -H "Authorization: Bearer ${GITHUB_TOKEN}" "https://api.github.com/repos/karizaco/maxhermes-migration/contents/cloud-prompts/skills/agentic-pre-market-brief/SKILL.md?ref=main"` (or `web_fetch` if available). Read the procedure in full. Do NOT skip this step.
Then follow the procedure verbatim, with these Cloud adaptations below.


## SHARED INSTRUCTIONS (fetch once — these rules apply to every routine)

The fleet-wide instructions live in ONE file, not in every prompt. Fetch it in the same first
step as the skill spec below, then follow it in full:

```bash
B=https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared
# --- fetch cloud-prompts/_shared/PROMPT-BLOCKS.md ---
# The CONTENTS API is authoritative and is NOT CDN-cached. The two CDNs cache `main`
# independently: measured 2026-11-04, raw.githubusercontent served a STALE blob for >17
# minutes after a push while jsDelivr was fresh. The OLD `[ -s file ] || curl` loop could
# NEVER reach its fallback - the first successful download satisfied the guard, so the
# second URL was DEAD CODE. Now all three are tried, and a 404 body (non-empty JSON) is
# rejected on its BODY, not on its byte count.
S=/workspace/PROMPT-BLOCKS.md
for U in \
  "https://api.github.com/repos/karizaco/maxhermes-migration/contents/cloud-prompts/_shared/PROMPT-BLOCKS.md?ref=main" \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/PROMPT-BLOCKS.md" \
  "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/PROMPT-BLOCKS.md" ; do
  curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" \
    -H "Authorization: Bearer ${GITHUB_TOKEN}" -o "$S.tmp" "$U" 2>/dev/null
  if [ -s "$S.tmp" ] && ! head -c 200 "$S.tmp" | grep -q '"message"'; then
    mv -f "$S.tmp" "$S"; break
  fi
  rm -f "$S.tmp"
done
```

It contains, and you must follow, all of these:

- `## MCP TOOLS AVAILABLE` — what actually exists in this runtime (the `mcp__*` names do NOT).
- `## RUNTIME DATA-SOURCE CONTRACT` — the source ladder (bridge `market-recap` → TradingView →
  Yahoo → Nasdaq/SEC/CoinGecko/Frankfurter/Treasury), the per-egress Yahoo caveat, and the
  "a 429 is a rate limit, not an absence" rule.
- `### MCP AVAILABILITY PROBE` — the one-call catalog probe and its four possible states.
- `### PRIMARY SOURCE` — the MCP-over-HTTP bridge: how to fetch it, how to call it, what
  `--list-packs` does and does not tell you.
- `### Rules` — the seven standing rules (rate limit vs missing, check the BODY not the status,
  never fabricate, no-data vs no-source, source health, partial data beats no data, one number per
  field one source per field).
- `## ZERO-FALLBACK POLICY`, `## HELPER SCRIPTS (PYTHON)`, `## AUDIT LOG` — how to handle a
  broken source, why the local Windows helpers do not exist, and why there is no audit log.
- `## DELIVERY` — the reply format your final chat message must use.

**If that fetch fails**, write a stub artifact with `_source=prompt_blocks_fetch_failed` and reply
with the failure. Do NOT improvise the source ladder, the fallback chain or the reply format from
memory — those are what keep a degraded run honest.


## OUTPUT
Write the artifact to:
  `/workspace/daily-briefs/{date}-pre-market.md`

The `{date}` placeholder is the fire's **scheduled** date in US/Eastern, `YYYY-MM-DD`. Resolve it
from the run's `scheduled_at_ms` (`cron_read view:runs` → `run.scheduled_at_ms`), not from `date`
at execution time. If they differ, this is a **delayed replay**: rebuild for the scheduled date,
do NOT write a SKIPPED marker, and say in the artifact that it is a reconstruction produced late.
A replay is normal, not an error.
(Literal text "{date}" in this template — replace it with the actual date.)

The skill ships TWO outputs and both are required:
  `/workspace/daily-briefs/{date}-pre-market.md`   — the brief
  `/workspace/daily-briefs/{date}-pre-market.csv`  — the machine-readable screen the tables are
                                                     built from (one row per name seen in the
                                                     pre-market screens). It must never contradict
                                                     the markdown.

## GIT PUSH (OPTIONAL)

```bash
B=https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared
for U in "$B/push_artifact.sh" "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/push_artifact.sh"; do
  [ -s /workspace/push_artifact.sh ] || curl -sL -o /workspace/push_artifact.sh "$U"
done
# ONE --add, and it is the .md. The script stages the routine's WHOLE output tree, so the
# companion CSV rides along in the same commit — you do NOT need a second --add, and passing
# one is actively harmful: --add OVERWRITES, so a second path wipes the routine number out of
# the commit subject, and cron #90 attributes a push by grepping subjects for "cron (#)?26 ".
# A delivered artifact would then be reported as MISSING.
sh /workspace/push_artifact.sh --out daily-briefs --add daily-briefs/{date}-pre-market.md --branch main
```

**If the push script cannot be fetched**, use the inline fallback in
`cloud-prompts/_shared/push_artifact.sh` — but never `git add -A`, and never
`git push … | head -3` (that returns head's exit status and reports a rejected push as success).

## DELIVERY VERIFICATION (MANDATORY - do this after the push block)

The push above already verifies its own delivery: `push_artifact.sh` calls `verify_delivery.sh`
and only reports `push: ok` when the path is present on the remote branch.
Run it again if you need to re-check:

```bash
sh /workspace/verify_delivery.sh --path daily-briefs/{date}-pre-market.md --branch main --nn 26
```

A `git push` that exits 0 is **not** proof of delivery — a push piped into `head` returns head's
exit status (always 0) and reports a rejected push as a success. That is why the delivery check
exists, and why the push script must never be run with `git push … | head -3`.

`--nn 26` also checks that the commit which last touched the path carries the routine number in
its subject. **Exit 4 means the file IS on the branch but the subject is not attributable** —
cron #90's triage greps subjects for `cron (#)?26 ` and will report that artifact as MISSING.
Fix FORWARD with another commit whose subject carries the number (re-push with the `.md` `--add`);
do NOT force-push `main` — `master` mirrors it fast-forward, and rewriting a `main` commit breaks
that mirror permanently.

**Confirm by API as well**, because the script's check reads a remote-tracking ref that can be
stale after a race with a sibling routine in the same minute (cron #08 shares this fire minute):

```bash
curl -s "https://api.github.com/repos/karizaco/minimax-cloud-outputs/contents/daily-briefs/{date}-pre-market.md?ref=main" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print('API:', d.get('size'), 'bytes' if d.get('size') else d.get('message'))"
```

If the API says the file is absent while the script said `DELIVERY: ok`, the push lost that race:
re-fetch, re-copy, re-commit on top of the new tip and push again (the script retries internally; a
final manual re-push is acceptable). Report the outcome honestly — an artifact that is not on the
branch is a FAILED delivery whatever the platform's run record says.

## CRITICAL REMINDERS
1. Skill URL above MUST be fetched first. If the fetch fails, write a stub artifact with `_source=skill_fetch_failed` and reply with the failure. Do NOT improvise the procedure from memory.
2. Use ONLY the tools named in the RUNTIME DATA-SOURCE CONTRACT above (`web_search`, `web_fetch`, `bash`). Do NOT call the `mcp__*` tools — they are not
   registered in this runtime — and do not invent tool names.
3. The cron session is fresh each time — there is no shared state. Treat every artifact as ephemeral unless pushed.
4. **This routine runs on WEEKDAYS only** (`30 8 * * 1-5`). The scheduler never starts a weekend
   run, and there is no weekend brief to produce. If the window check skips (a US market
   holiday), exit cleanly with "out-of-window: <reason>" and write the skip marker via
   `skip_marker.sh` — on a holiday a skipped fire is correct behaviour, not a failure.
5. Every percentage in the brief must trace to a fetched value or a cited source. Do not invent numbers. Audit before rendering.
6. The skill spec PINS the screen — the universe, the liquidity gate, the quality floor, and the
   column contract between `premarket_*` and the prior session's `change`. Do not re-derive or
   improvise them. Two runs have already published different screens, and one published
   yesterday's session moves under a "Pre-market gaps" heading.
7. Cron #19 publishes `earnings/{date}-reminders.md` on the outputs repo at 06:00 ET. READ IT for
   §9 — it carries the BMO/AMC split and per-name EPS/revenue estimates. Do not rebuild the
   earnings roster from search when that file is there.
8. The commit subject must carry the routine number — `cron 26 <name> <date>`. Pass `--add` ONCE
   (the `.md` path) and confirm the subject after the push. See DELIVERY VERIFICATION above.

================================================================
END OF CRON PROMPT
================================================================