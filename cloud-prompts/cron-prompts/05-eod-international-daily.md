# Cloud Mavis cron: eod-international-daily (cron #05)

You are running as a Cloud Mavis cron. No local filesystem, no PowerShell, no Windows paths.
Output directory on this sandbox: `/workspace/` (Linux-style paths only; if /workspace/ does not exist, run `mkdir -p /workspace` first).

## CONVERSATION TITLE (do this FIRST, before anything else)

Every scheduled run gets its own conversation — one conversation per fire, never appended to an
earlier run's conversation. Give this conversation a title that says which day this run belongs
to, so the conversation list stays scannable.

1. Resolve today's date in US/Eastern: `TZ=America/New_York date +%d-%m` (day-month, no year).
2. Build the title: `[<DD-MM>] <NN>-<routine name>`. Take `<NN>` and `<routine name>` from the
   first line of this prompt (`# Cloud Mavis cron: <routine name> (cron #NN)`).
   Example: `[01-11] 05-eod-international-daily`.
3. Set it with one call: `mcp_invoke` with tool_name `session_update` and arguments
   `{"session_id": "me", "title": "<the title>"}`. `me` means THIS conversation.
   If `mcp_invoke` reports that the tool is unknown, call `tool_search` with the query
   "session title update", then retry the same `mcp_invoke` call.
4. If the title cannot be set for any reason, carry on with the routine. This step must never
   block, delay, or fail the artifact.

## SCHEDULE
- Original local schedule: `35 16 * * 1-5` America/New_York — 16:35 ET weekdays
- Deployed schedule: `30 16 * * 1-5` America/New_York — 16:30 ET, Mon-Fri.
- The hour moved from 16:35 to 16:30 on 2026-10-29, when #16 took 16:35 to clear a push race
  on the same branch. **Keep the two in step:** if #16 moves again, move this one too.
- The day-of-week field is set in the SCHEDULER, so this routine does not fire at all on
  weekends: no agent invocation is spent discovering it is a weekend, and no weekend SKIPPED
  file is written. The WINDOW CHECK below keeps the one guard a cron expression cannot
  express — the market-holiday list.


## WINDOW CHECK (RUN FIRST, BEFORE FETCHING THE SKILL)

The scheduler owns the day-of-week and the hour, so this block exists for ONE reason: a cron
expression cannot express a **market holiday**, and the scheduler fires Mon-Fri *including* them.
On a holiday the market is closed and there is nothing to report.

```bash
# US MARKET HOLIDAYS — 2026 NYSE closures (non-weekend):
#   2026-01-01 2026-01-19 2026-02-16 2026-04-03 2026-05-25 2026-06-19 2026-07-03
#   2026-09-07 2026-11-26 2026-12-25
# Half-days (07:00 13:00 ET) are trading days and still report — do NOT skip them.
#
# The skip marker is written AND PUSHED by the shared script, so a deliberate
# skip leaves a trace on the outputs repo instead of dying in the sandbox. A
# marker that never leaves the sandbox is indistinguishable from a failed run.
# The marker lives in refs/skipped-markers/, outside every routine's output
# directory, so it can never be mistaken for a delivered artifact.
DATE=$(TZ=America/New_York date +%Y-%m-%d)
case "$DATE" in
    2026-01-01|2026-01-19|2026-02-16|2026-04-03|2026-05-25|2026-06-19|2026-07-03|2026-09-07|2026-11-26|2026-12-25)
        S=/workspace/skip_marker.sh
        for U in \
          "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/skip_marker.sh" \
          "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/skip_marker.sh" ; do
          curl -sL --max-time 30 -o "$S.tmp" "$U" 2>/dev/null
          # A 404 page is a non-empty body that is NOT a script - never run one.
          if head -1 "$S.tmp" 2>/dev/null | grep -q '^#!'; then
            mv -f "$S.tmp" "$S"; break
          fi
          rm -f "$S.tmp"
        done
        if [ -s "$S" ] && head -1 "$S" 2>/dev/null | grep -q '^#!'; then
          sh "$S" --out international-eod --name eod_international_daily \
             --label "Cron #05 eod-international-daily" \
             --reason "US market holiday ($DATE)" \
             --nn 05 --date "$DATE" || \
             echo "skip-marker push: FAILED (the marker is still in the sandbox)"
        else
          echo "skip-marker push: SKIPPED (skip_marker.sh unavailable - the marker could not be written)"
        fi
        echo "out-of-window: US market holiday ($DATE)"
        echo "no artifact; no push"
        exit 0
        ;;
esac
echo "window-check: OK ($DATE)"
```

**Reply format for a holiday skip.** The `## DELIVERY` block expects a push line and an errors
line; a skipped fire has neither an artifact nor an error. Reply with these lines and nothing
else — do not narrate the tool calls and do not write an artifact:

```
out-of-window: US market holiday ($DATE)
file: no artifact (holiday skip — international-eod/$DATE.md is intentionally absent)
push: marker pushed (refs/skipped-markers/$DATE_SKIPPED_eod_international_daily.md) | marker push FAILED | marker push skipped (push script unavailable)
errors: 0
```

## SKILL SPEC (FETCH ONCE)
The skill's procedure body lives here:
  https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/skills/eod-watchlist-snapshot/SKILL.md

**FIRST tool call:** `curl -s https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/skills/eod-watchlist-snapshot/SKILL.md` (or `web_fetch` if available). Read the procedure in full. Do NOT skip this step.
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

**If that fetch fails**, write a stub artifact with `_source=prompt_blocks_fetch_failed` and reply
with the failure. Do NOT improvise the source ladder, the fallback chain or the reply format from
memory — those are what keep a degraded run honest.


## OUTPUT
Write the artifact to:
  `/workspace/international-eod/{date}/<region>.csv (multi-region)`

The `{date}` placeholder is the fire's **scheduled** date in US/Eastern, `YYYY-MM-DD`. Resolve it
from the run's `scheduled_at_ms` (`cron_read view:runs` → `run.scheduled_at_ms`), not from `date`
at execution time. If they differ, this is a **delayed replay**: rebuild for the scheduled date,
do NOT write a SKIPPED marker, and say in the artifact that it is a reconstruction produced late.
A replay is normal, not an error.
(Literal text "{date}" in this template — replace it with the actual date.)

If the skill produces multiple outputs (e.g. .md + .csv, or per-region files), write all of them in the same `/workspace/international-eod/{date}/` subdirectory, with `{date}` as part of each filename.

## REPORT FORMAT (what this artifact must contain)

This routine's deliverable is a **directory**, not a single file:

    /workspace/international-eod/{date}/<region>.csv    one per region, 16 in all
    /workspace/international-eod/{date}/summary.md        the report
    /workspace/international-eod/{date}/_manifest.json    machine-readable per-day facts
    /workspace/international-eod/{date}/_excluded.json    rows excluded for a missing cap
    /workspace/international-eod/{date}/_carryover.json   rows that did not trade, machine-readable

`_manifest.json` and `_excluded.json` are specified in the skill's "The machine-readable
companions" section: the manifest carries the universe size, the floor, the `market_cap`
unit and the counts that let a consumer reconcile the session, and `_excluded.json` lists
the rows the source reports no market cap for so their exclusion stays recoverable.

`summary.md` carries these sections in this order. Do not rename them — cron #90's auditor and
the downstream briefs key on them.

1. **Title, then a "Read this first" blockquote.** Give the row count, the regions covered, and
   the two facts that change how the file reads: `market_cap` is written in **USD** while
   `open`/`high`/`low`/`close` stay in the **listing currency** (`currency` says which), and rows
   the source reports no market cap for are **excluded rather than written blank**.
2. **`## Coverage`** — one table: `Region | Venues | Universe | Unique instruments | Written |
   Floor (USD) | No cap | Off-official rows`, with a totals row. `Universe` is everything the
   source returns for that country; `Unique instruments` collapses multi-venue listings of the
   same instrument to one row; `Written` is what survives the floor.
3. **`## Market context`** — one table of index levels (`Index | Close | Change | Day | Source`),
   then one table of regional breadth computed from the snapshot itself
   (`Region | Rows | Median | Up / down / flat | Min | Max`). The breadth table is what shows that
   an index move and the typical name disagree — report both, never the index alone.
4. **`## Top movers`** — one consolidated table of the largest absolute moves among liquid names
   (`Region | Ticker | Name | Change | Close | Volume | Mkt cap (USD) | Catalyst`), then a second
   table with one row per region for the largest mover in that region. The `Catalyst` cell says
   what you actually sourced, or "no company-specific release found" — never an unattributed
   guess.
5. **`## Method`** — the universe rules, the per-region floors, the FX table with its source and
   its date, and the venue-collapse rule.
6. **`## Caveats`** — every structural caveat that changes how the numbers read, including rows
   whose close is a carry-over from an earlier session.
7. **`## Source health`** — one table: `Source | Query / URL | Status | Result`. Mandatory, even
   when every source was healthy.
8. **`## Files`** — the file list and the schema.

**The chat reply leads with a markdown table of all 16 region index levels**
(`region | index | close | change`) — sixteen comparable numeric rows is exactly the case a
table exists for — then the movers, one ticker per line, then the caveats and the push line.

## GIT PUSH (OPTIONAL)

```bash
B=https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared
for U in "$B/push_artifact.sh" "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/push_artifact.sh"; do
  [ -s /workspace/push_artifact.sh ] || curl -sL -o /workspace/push_artifact.sh "$U"
done
sh /workspace/push_artifact.sh --out international-eod --add international-eod/{date} --branch main
sh /workspace/verify_delivery.sh --path international-eod/{date} --branch main
```

**If the push script cannot be fetched**, use the inline fallback in
`cloud-prompts/_shared/push_artifact.sh` — but never `git add -A`, and never
`git push … | head -3` (that returns head's exit status and reports a rejected push as success).

## DELIVERY VERIFICATION (MANDATORY - do this after the push block)

The push above already verifies its own delivery: `push_artifact.sh` calls `verify_delivery.sh`
and only reports `push: ok` when the path is present on the remote branch.
Run it again if you need to re-check:

```bash
sh /workspace/verify_delivery.sh --path international-eod/{date} --branch main
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
