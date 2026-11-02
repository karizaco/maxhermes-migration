# Cloud Mavis cron: macro-calendar-midweek (cron #13)

You are running as a Cloud Mavis cron. No local filesystem, no PowerShell, no Windows paths.
Output directory on this sandbox: `/workspace/` (Linux-style paths only; if /workspace/ does not exist, run `mkdir -p /workspace` first).

## SCHEDULE
- Original local schedule: `0 14 * * 3` America/New_York — Wednesday 14:00 ET.
- Deployed schedule: `0 14 * * 3` America/New_York — Wednesday 14:00 ET.
  Unchanged; the scheduler owns the day-of-week, so this fires on Wednesdays only.


## WINDOW CHECK (RUN FIRST, BEFORE FETCHING THE SKILL)

The scheduler owns the day-of-week and the hour, so this block exists for ONE reason: a cron
expression cannot express a **market holiday**, and the scheduler fires Mon-Fri *including* them.
On a holiday the market is closed and there is nothing to report.

```bash
# US MARKET HOLIDAYS — 2026 NYSE closures (non-weekend):
#   2026-01-01 2026-01-19 2026-02-16 2026-04-03 2026-05-25 2026-06-19 2026-07-03
#   2026-09-07 2026-11-26 2026-12-25
# Half-days (07:00 13:00 ET) are trading days and still report — do NOT skip them.
DATE=$(TZ=America/New_York date +%Y-%m-%d)
case "$DATE" in
    2026-01-01|2026-01-19|2026-02-16|2026-04-03|2026-05-25|2026-06-19|2026-07-03|2026-09-07|2026-11-26|2026-12-25)
        mkdir -p /workspace/$DATE
        cat > /workspace/$DATE/SKIPPED_macro_calendar_midweek.md <<EOF
# Cron #13 macro_calendar_midweek — SKIPPED
- Date (ET): $DATE
- Time (ET): $(TZ=America/New_York date +%H:%M)
- Reason: US market holiday ($DATE)
- No artifact produced.
EOF
        echo "out-of-window: US market holiday ($DATE)"
        echo "no artifact; no push"
        exit 0
        ;;
esac
echo "window-check: OK ($DATE)"
```

## SKILL SPEC (FETCH ONCE)
The skill's procedure body lives here:
  https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/skills/macro-calendar-week/SKILL.md

**FIRST tool call:** `curl -s https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/skills/macro-calendar-week/SKILL.md` (or `web_fetch` if available). Read the procedure in full. Do NOT skip this step.
If curl fails with a certificate/TLS error (the sandbox egress proxy rotates its leaf cert and has
expired mid-session before), fall back to `web_fetch` on the SAME url. If both fail: write a stub
artifact with `_source=skill_fetch_failed`, report `errors: 1`, and stop. Never improvise from memory.

Then follow the procedure verbatim, with these Cloud adaptations below.


## SHARED INSTRUCTIONS (fetch once — these rules apply to every routine)

The fleet-wide instructions live in ONE file, not in every prompt. Fetch it in the same first
step as the skill spec below, then follow it in full:

```bash
B=https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared
for U in "$B/PROMPT-BLOCKS.md" "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/PROMPT-BLOCKS.md"; do
  [ -s /workspace/PROMPT-BLOCKS.md ] || curl -sL -o /workspace/PROMPT-BLOCKS.md "$U" 2>/dev/null
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

**If that fetch fails** — including a certificate/TLS error on curl, which the sandbox egress
proxy has produced mid-session before — retry the SAME url with `web_fetch` before giving up. Only
then write a stub artifact with `_source=prompt_blocks_fetch_failed` and reply with the failure. Do
NOT improvise the source ladder, the fallback chain or the reply format from memory — those are
what keep a degraded run honest.


## OUTPUT
Write the artifact to:
  `/workspace/macro-calendar/{date}-midweek.md`

The `{date}` placeholder is the fire's **scheduled** date in US/Eastern, `YYYY-MM-DD`. Resolve it
from the run's `scheduled_at_ms` (`cron_read view=runs` → `run.scheduled_at_ms`), not from `date`
at execution time. If they differ, this is a **delayed replay**: rebuild for the scheduled date,
do NOT write a SKIPPED marker, and say in the artifact that it is a reconstruction produced late.
A replay is normal, not an error.
(Literal text "{date}" in this template — replace it with the actual date.)

If the skill produces multiple outputs (e.g. .md + .csv, or per-region files), write all of them in the same `/workspace/macro-calendar/` subdirectory, with `{date}` as part of each filename.

## GIT PUSH (OPTIONAL)

```bash
B=https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared
for U in "$B/push_artifact.sh" "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/push_artifact.sh"; do
  [ -s /workspace/push_artifact.sh ] || curl -sL -o /workspace/push_artifact.sh "$U"
done
sh /workspace/push_artifact.sh --out macro-calendar --add macro-calendar/{date}-midweek.md --branch main
sh /workspace/verify_delivery.sh --path macro-calendar/{date}-midweek.md --branch main
```

**If the push script cannot be fetched**, use the inline fallback in
`cloud-prompts/_shared/push_artifact.sh` — but never `git add -A`, and never
`git push … | head -3` (that returns head's exit status and reports a rejected push as success).

## DELIVERY VERIFICATION (MANDATORY - do this after the push block)

The push above already verifies its own delivery: `push_artifact.sh` calls
`verify_delivery.sh` and only reports `push: ok` when the path is present on the remote branch.
Run it again if you need to re-check:

```bash
sh /workspace/verify_delivery.sh --path macro-calendar/{date}-midweek.md --branch main
```

A `git push` that exits 0 is **not** proof of delivery — a push piped into `head` returns head's
exit status (always 0) and reports a rejected push as a success. That is why the delivery check
exists, and why the push script must never be run with `git push … | head -3`.


## CRITICAL REMINDERS
1. Skill URL above MUST be fetched first. If the fetch fails, write a stub artifact with `_source=skill_fetch_failed` and reply with the failure. Do NOT improvise the procedure from memory.
2. Use ONLY the tools named in the RUNTIME DATA-SOURCE CONTRACT above (`web_search`, `web_fetch`, `bash`). Do NOT call the `mcp__*` tools — they are not
   registered in this runtime — and do not invent tool names.
3. The cron session is fresh each time — there is no shared state. Treat every artifact as ephemeral unless pushed.
4. If the cron fires outside its intended window (a US market holiday — the scheduler owns the day-of-week, so a weekend fire cannot happen), exit cleanly with "out-of-window: <reason>". Do NOT run a degraded version.

================================================================
END OF CRON PROMPT
================================================================