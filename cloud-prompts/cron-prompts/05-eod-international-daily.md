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
   --out international-eod --name eod_international_daily \
   --label "Cron #05 eod-international-daily" \
   --nn 05
```

If the script exits non-zero, the fire is OUT OF WINDOW: do not fetch the skill, do not write
an artifact, do not push. The skip marker it wrote IS the audit trail for this run.

**Reply format for an out-of-window skip.** The `## DELIVERY` block expects a push line and
an errors line; a skipped fire has neither an artifact nor an error. Reply with these lines
and nothing else - do not narrate the tool calls and do not write an artifact:

```
out-of-window: <reason printed by the script>
file: no artifact (window check declined this fire - international-eod/$DATE.md is intentionally absent)
push: marker pushed (refs/skipped-markers/$FIRE_DATE_SKIPPED_eod_international_daily.md) | marker push FAILED | marker push skipped (push script unavailable)
errors: 0
```

## SKILL SPEC (FETCH ONCE)
The skill's procedure body lives here:
  https://api.github.com/repos/karizaco/maxhermes-migration/contents/cloud-prompts/skills/eod-watchlist-snapshot/SKILL.md?ref=main

**FIRST tool call:** `curl -sL -H "Accept: application/vnd.github.raw" -H "Authorization: Bearer ${GITHUB_TOKEN}" "https://api.github.com/repos/karizaco/maxhermes-migration/contents/cloud-prompts/skills/eod-watchlist-snapshot/SKILL.md?ref=main"` (or `web_fetch` if available). Read the procedure in full. Do NOT skip this step.
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
    /workspace/international-eod/{date}/_excluded.json    rows excluded, one reason per row
    /workspace/international-eod/{date}/_carryover.json   rows that did not trade, machine-readable

`_manifest.json`, `_excluded.json` and `_carryover.json` are specified in the skill's "The
machine-readable companions" section. Read that section with the skill spec: the manifest
carries the universe size, the floor, the `market_cap` unit, the **per-reason exclusion
counts** and the published table counts, and `_excluded.json` lists every row that did not make
the CSV **with a non-empty `reason`**.

### The CSV schema — 18 columns

    date,ticker,name,open,high,low,close,volume,change_pct,market_cap,pe_ratio,sector,currency,exchange,cap_source_symbol,share_class,us_listing,price_conflict

The last four columns are the provenance columns, and **every row carries all four**:

- `cap_source_symbol` — the ticker of the line the cap was taken from, which is the issuer's
  **primary** listing line. It equals the row's own ticker when the row IS the primary line. A
  cap carried from another line is published only when the two symbols resolve to the **same
  issuer**; otherwise the name is dropped from the cap-filtered table and recorded in
  `_excluded.json` with reason `issuer_unresolved` or `cap_issuer_mismatch`.
- `share_class` — `common` / `preferred` / `unit` / `other`. A preferred line carries the
  issuer's company-level cap, and **a preferred line must never outrank a common line on that
  company-level cap**.
- `us_listing` — `NYSE` / `NASDAQ` / `ADR` / `OTC` / `none`.
- `price_conflict` — `official=… source=… third_party=… delta=…`, and EMPTY when there is no
  conflict.

The header grew from 14 columns to 18. State the column count in `## Method` whenever it
differs from the previous session, the way a unit change is stated.

### summary.md — the fixed skeleton

`summary.md` carries these sections in this order. Do not add, drop, reorder or rename them.
(cron #90's auditor keys on the artifact **path**, not on these names — but the reader keys on
them, and a report that re-orders itself every morning is unreadable.)

```
# Cron #05 eod-international-daily — <Weekday, DD Month YYYY>
## TL;DR
## Market context
## Top movers
## Below the gate
## No catalyst
## Method, source health & caveats
```

1. **`## TL;DR`** — exactly **3 bullets**: what global markets did; the one most consequential
   move; the caveat that changes how to read it. One of the three names the foreign moves that
   have a US-listed line — a US trader needs to know which of these are reachable. The standing
   caveat here is the unit convention (`market_cap` is USD, the prices are in the listing
   currency), and it belongs in the third bullet.
2. **`## Market context`** — three tables, in this order. The **coverage** table
   (`Region | Venues | Universe | Unique instruments | Written | Floor (USD) | Excluded: no cap |
   Excluded: below floor | Excluded: below volume | Excluded: issuer unresolved | Excluded: cap
   mismatch | Carry-over rows | Off-official rows`, with a totals row; the per-reason counts come
   from `_excluded.json`, they are not estimates); the **index levels** table
   (`Region | Index | Close | Change | Session date | Source`); and the **regional breadth** table
   (`Region | Rows | Median | Up / down / flat | Min | Max`). The breadth table is what shows that
   an index move and the typical name disagree — report both, never the index alone.
3. **`## Top movers`** — **one table per region**, one row per name, largest absolute move first
   within the region. Every row carries `us_listing`, the cap, and the **catalyst in the row**:
   what was actually sourced, with its source and its date. A name with **no sourced driver** does
   not go here — it goes to `## No catalyst`.
4. **`## Below the gate`** — the names that moved and would have been published but for the cap
   floor alone. Published, because a −24.72% move is not noise.
5. **`## No catalyst`** — the names that moved with no sourced driver, kept separate so they do
   not dilute the mover table.
6. **`## Method, source health & caveats`** — **Method** (the universe rules, the per-region
   floors, the FX table with its source and its date, the venue-collapse rule, the cap carrier
   rule, the venue-official price rule, the CSV column count, and the files written), then
   **Source health** (`Source | Query / URL | Status | Result`, mandatory even when every source
   was healthy), then **Caveats** (every structural caveat that changes how the numbers read,
   including rows whose close is a carry-over from an earlier session).

The skill's "The summary.md skeleton" section carries the full contract for each of these — read
it with the skill spec and follow it.

### The assertions — run them before the push

The skill's `scripts/intl_assert.py` checks a built directory: no unaccounted cap, a reason on
every excluded row, the summary's tables reconciled against the CSVs, and `us_listing` on every
mover row. Fetch it, run it, and push only if it passes:

```bash
curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" -H "Authorization: Bearer ${GITHUB_TOKEN}" \
  -o /workspace/intl_assert.py \
  "https://api.github.com/repos/karizaco/maxhermes-migration/contents/cloud-prompts/skills/eod-watchlist-snapshot/scripts/intl_assert.py?ref=main"
python3 /workspace/intl_assert.py --dir /workspace/international-eod/{date} ; echo "exit=$?"
```

A non-zero exit means the artifact is not publishable. Fix the build; do not push.

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
