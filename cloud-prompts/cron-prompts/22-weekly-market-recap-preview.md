# Cloud Mavis cron: weekly-market-recap-preview (cron #22)

You are running as a Cloud Mavis cron. No local filesystem, no PowerShell, no Windows paths.
Output directory on this sandbox: `/workspace/` (Linux-style paths only; if /workspace/ does not exist, run `mkdir -p /workspace` first).

## SCHEDULE
- Original local schedule: Friday weekly
- Schedule is unchanged — only the runtime environment changed.


## WINDOW CHECK (RUN FIRST, BEFORE FETCHING THE SKILL)

The agent.minimax.io cron scheduler only supports coarse schedule types (daily, weekly, every X minutes).
It cannot express "weekdays at 09:45" or "every market hour". To work around this, this prompt
includes a window-check preamble. Run it as the FIRST step — before fetching the skill URL.

```bash
# Window flags for THIS cron (set by migration):
WEEKDAYS_ONLY=false
WEEKEND_ONLY=false
MARKET_HOURS_ONLY=false
DAY_OF_WEEK=5   # 1=Mon ... 7=Sun; 0=no constraint

# Resolve current time in US/Eastern
NOW_ET=$(TZ=America/New_York date +"%Y-%m-%d %H:%M %u")
DOW=$(TZ=America/New_York date +%u)
HOUR=$(TZ=America/New_York date +%H)

SKIP_REASON=""

if [ "$WEEKDAYS_ONLY" = "true" ] && [ "$DOW" -ge 6 ]; then
    SKIP_REASON="weekend (day=$DOW, expected Mon-Fri)"
fi
if [ "$WEEKEND_ONLY" = "true" ] && [ "$DOW" -lt 6 ]; then
    SKIP_REASON="weekday (day=$DOW, expected Sat-Sun)"
fi
if [ "$DAY_OF_WEEK" -gt 0 ] && [ "$DOW" -ne "$DAY_OF_WEEK" ]; then
    case $DAY_OF_WEEK in
        1) DAY_NAME="Monday";;
        2) DAY_NAME="Tuesday";;
        3) DAY_NAME="Wednesday";;
        4) DAY_NAME="Thursday";;
        5) DAY_NAME="Friday";;
        6) DAY_NAME="Saturday";;
        7) DAY_NAME="Sunday";;
    esac
    SKIP_REASON="wrong day (today=$DOW, expected $DAY_NAME=$DAY_OF_WEEK)"
fi
if [ "$MARKET_HOURS_ONLY" = "true" ]; then
    if [ "$HOUR" -lt 9 ] || [ "$HOUR" -ge 17 ]; then
        SKIP_REASON="outside market hours (hour=$HOUR, expected 09-16 ET)"
    fi
fi

if [ -n "$SKIP_REASON" ]; then
    mkdir -p /workspace/$(TZ=America/New_York date +%Y-%m-%d)
    cat > /workspace/$(TZ=America/New_York date +%Y-%m-%d)/SKIPPED_weekly_market_recap_preview.md <<EOF
# Cron #22 weekly-market-recap-preview — SKIPPED
- Date (ET): $(TZ=America/New_York date +%Y-%m-%d)
- Time (ET): $(TZ=America/New_York date +%H:%M)
- Reason: $SKIP_REASON
- No artifact produced.
EOF
    echo "out-of-window: $SKIP_REASON"
    echo "no artifact; no push"
    exit 0
fi

echo "window-check: OK ($NOW_ET)"
```

If the window check exits cleanly with "out-of-window: <reason>", the cron is DONE. Do not fetch the skill, do not call MCPs, do not write any other artifact, do not push. The `SKIPPED_*.md` file IS the artifact for this run — it's the audit trail for skipped fires.

## SKILL SPEC (FETCH ONCE)
The skill's procedure body lives here:
  https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/skills/agentic-weekly-brief/SKILL.md

**FIRST tool call:** `curl -s https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/skills/agentic-weekly-brief/SKILL.md` (or `web_fetch` if available). Read the procedure in full. Do NOT skip this step.
Then follow the procedure verbatim, with these Cloud adaptations below.

## MCP TOOLS AVAILABLE
- `mcp__shibui_finance__*`, `mcp__tradingview_advanced__*`, `mcp__yahoo_finance__*`
- `web_search`, `extract_content_from_websites` for catalyst/news research.

## ZERO-FALLBACK POLICY
The skill procedure uses a fallback chain (PRIMARY → FALLBACK → skip).
**Every fallback MUST terminate with:**
  "accept the partial result, write the artifact, and STOP. Do NOT chain <deeper MCP>."
Do NOT loop on MCP errors. Do NOT retry indefinitely. Do NOT re-raise.

## HELPER SCRIPTS (PYTHON)
Local Mavis called Python helpers like `python screen.py emit-sql ...` to do file I/O, parsing, and atomic writes.
**On Cloud, do NOT call those helpers — they don't exist here.** Re-implement the helper's job inline using tool calls:
  - SQL generation → emit SQL directly (see skill's reference docs if attached).
  - Finviz URL building → construct URL inline (see skill's filter spec).
  - Finviz HTML parsing → parse with regex/text extraction in agent context.
  - Atomic file write → `write_file(path, content)` (already atomic).
  - Deduplication → do it in agent reasoning before writing.

If the skill spec references a helper under `scripts/`, fetch the helper's URL too:
  https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/skills/agentic-weekly-brief/scripts/<name>.py
Read it for reference, but do NOT execute it. Re-implement its logic.

## AUDIT LOG
Local Mavis wrote an audit line to a Windows audit file after every run.
**On Cloud, skip audit log writes.** Audit is not needed here. If something goes wrong, the failure is in the chat reply and the (missing) artifact.

## OUTPUT
Write the artifact to:
  `/workspace/weekly/{date}-preview.md`

The `{date}` placeholder is today in US/Eastern, `YYYY-MM-DD`. Resolve it as the first step.
(Literal text "{date}" in this template — replace it with the actual date.)

If the skill produces multiple outputs (e.g. .md + .csv, or per-region files), write all of them in the same `/workspace/weekly/` subdirectory, with `{date}` as part of each filename.

## GIT PUSH (OPTIONAL)
After writing the artifact, optionally commit it to `karizaco/minimax-cloud-outputs`:

```bash
cd /workspace
git init -q 2>/dev/null || true
git remote add origin https://x-access-token:${GITHUB_TOKEN}@github.com/karizaco/minimax-cloud-outputs.git 2>/dev/null || true
git config user.email "maxhermes-cloud@local"
git config user.name "MaxHermes Cloud Cron"
mkdir -p $(dirname "weekly/{date}-preview.md")
git add -A
git commit -q -m "cron #22 weekly-market-recap-preview ${DATE}" || echo "nothing to commit"
git push -q origin main 2>&1 | head -3 || echo "push failed (token unset? sandbox non-persistent?)"
```

**If `${GITHUB_TOKEN}` is empty/unset:** skip the push entirely. Do NOT try `gh auth` or any fallback. Just write the artifact and reply.

## DELIVERY
The final reply (the only thing delivered to the chat) MUST be:
  - ≤ 10 lines.
  - Top movers / count / source / lag if any.
  - One line per output file written.
  - One line: "push: ok" / "push: skipped (token unset)" / "push: failed (<reason>)".
  - One line: "errors: <n>" — count of MCP failures that triggered fallback. 0 = clean run.

No preamble. Tool call → result → write → push → reply.

## CRITICAL REMINDERS
1. Skill URL above MUST be fetched first. If the fetch fails, write a stub artifact with `_source=skill_fetch_failed` and reply with the failure. Do NOT improvise the procedure from memory.
2. Use the EXACT MCP tool names listed above. Do NOT invent tool names.
3. The cron session is fresh each time — there is no shared state. Treat every artifact as ephemeral unless pushed.
4. If the cron fires outside its intended window (e.g. holiday, weekend when it should be weekday), exit cleanly with "out-of-window: <reason>". Do NOT run a degraded version.

================================================================
END OF CRON PROMPT
================================================================
