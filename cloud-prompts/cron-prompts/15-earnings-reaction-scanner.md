# Cloud Mavis cron: earnings-reaction-scanner (cron #15) — REPAIRED 2026-10-24

You are running as a Cloud Mavis cron on Mavis. Linux sandbox: no PowerShell, no Windows paths.
Output root: /workspace/ (mkdir -p it if missing).

## SCHEDULE
Fires 08:00 ET on weekdays: cron `0 8 * * 1-5`, timezone America/New_York.
This matches the skill's own spec (`0 8 * * 1-5` ET) — 23 min after the pre-market brief,
~90 min before the US open, ~5h into the EU session, ~6h after the ASX close.

**REPAIR NOTE (2026-10-24):** this task used to fire at 14:30 Europe/Berlin = 08:30 ET while its
window check demanded 09:00-16:00 ET, so it skipped itself every single day and has never
produced an artifact. The schedule is now `0 8 * * 1-5` America/New_York and the window check
below accepts the 08:00 ET fire. Do not "fix" a skip by assuming the market is closed — check
the clock and read the reason string.

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
          sh "$S" --out earnings --name earnings_reaction_scanner \
             --label "Cron #15 earnings-reaction-scanner" \
             --reason "US market holiday ($DATE)" \
             --nn 15 --date "$DATE" || \
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
file: no artifact (holiday skip — earnings/$DATE.md is intentionally absent)
push: marker pushed (refs/skipped-markers/$DATE_SKIPPED_earnings_reaction_scanner.md) | marker push FAILED | marker push skipped (push script unavailable)
errors: 0
```


## STEP 2 — FETCH THE PIPELINE (the skill's MCP tools do not exist in Cloud)

The skill spec at
`https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/skills/earnings-reaction-scanner/SKILL.md`
is the authoritative *procedure* (passes, thresholds, tags, caps, artifact sections). Read it once
for reference.

But every MCP tool it calls is **absent in Cloud sessions** — verified 2026-10-24:
`mcp__tradingview-advanced__*`, `mcp__tradingview__*`, `mcp__financekit__*`, `mcp__stocktwits__*`
return 0 hits from `tool_search`, and `mcode-tools connector tools` holds only media + credential
tools. Do NOT burn turns re-testing them. A validated replacement pipeline is committed to the
shared output repo. Fetch and run it:

```bash
cd /workspace
mkdir -p scripts
curl -sS -w 'HTTP=%{http_code}\n' --max-time 60 \
  https://raw.githubusercontent.com/karizaco/minimax-cloud-outputs/main/scripts/earnings_reaction_scanner.py \
  -o scripts/earnings_reaction_scanner.py
head -5 scripts/earnings_reaction_scanner.py
```

If that fetch fails, retry once with `-k` (the GitHub cert expires intermittently). If both
attempts fail, write a stub artifact with `_source=skill_fetch_failed`, report `errors: 1`, stop.
Never improvise the procedure from memory.

## SHARED INSTRUCTIONS (fetch once — these rules apply to every routine)

The fleet-wide instructions live in ONE file, not in every prompt. Fetch it in the same first
step as the pipeline/skill fetch, then follow it in full:

```bash
B=https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared
for U in "$B/PROMPT-BLOCKS.md" "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/PROMPT-BLOCKS.md"; do
  [ -s /workspace/PROMPT-BLOCKS.md ] || curl -sL -o /workspace/PROMPT-BLOCKS.md "$U" 2>/dev/null
done
```

It contains, and you must follow, all of these:

- `## MCP TOOLS AVAILABLE` — what actually exists in this runtime (the `mcp__*` names do NOT).
- `## RUNTIME DATA-SOURCE CONTRACT` — the source ladder, the per-egress Yahoo caveat, and the
  "a 429 is a rate limit, not an absence" rule.
- `### MCP AVAILABILITY PROBE` — the one-call catalog probe and its four possible states.
- `### PRIMARY SOURCE` — the MCP-over-HTTP bridge: how to fetch it, how to call it, what
  `--list-packs` does and does not tell you.
- `### Rules` — the seven standing rules.
- `## ZERO-FALLBACK POLICY`, `## HELPER SCRIPTS (PYTHON)`, `## AUDIT LOG`.
- `## DELIVERY` — the reply format your final chat message must use.

**If that fetch fails**, write a stub artifact with `_source=prompt_blocks_fetch_failed` and reply
with the failure. Do NOT improvise the source ladder, the fallback chain or the reply format from
memory.


## STEP 3 — RUN THE PIPELINE

```bash
cd /workspace
python3 scripts/earnings_reaction_scanner.py
```

It writes `/workspace/earnings/<date>-reactions.md` and
`/workspace/earnings/<date>-catalyst-targets.json`. It is self-timing: it takes ~4-6 minutes
because it cross-checks reported movers against Yahoo. **Give it a generous timeout** (at least
560s). If it exceeds that, capture the partial state and report the failure — do not silently
ship a half-written artifact.

What the pipeline does, and why (read this before changing any of it):

* Source is the TradingView **public screener** (`https://scanner.tradingview.com/<market>/scan`),
  which replaces the absent MCP screener. One POST per market per direction, JSON in, JSON out.
* **Stale-reference rows.** On illiquid rows the screener's `change` is computed against a stale
  reference close, producing absurd prints (MRNA on SIX showed +71.77% on 25 shares while the US
  line moved -1.25%). The tell: `change` == `Perf.W` exactly, and `Perf.1D` is always null.
  A **volume floor of 10,000** removes these rows. Do not lower it.
* **Venue codes differ from the skill's priority table.** The public scanner returns EURONEXT for
  FR/NL/BE/PT/IE, EUROTLX for IT, BX for CH, OMXCOP for DK, OMXHEX for FI, GPW for PL, VIE for
  AT, ATHEX for GR, XETR-family for DE, LSE for UK, ASX for AU. The skill's table (AMS/BRU/PAR/
  LIS/DUB/MC/HE/CO/VI/AT/SW/WA) is for the MCP screener. The pipeline maps them explicitly.
* **`country` is the reliable primary-listing filter** — it correctly excludes US ADRs listing on
  EU venues (97 of 200 Swiss rows were `country=United States`).
* **`earnings_release_date` = most recent FULL report date** (WDC 2026-10-22 matches the press),
  `earnings_release_next_date` = next scheduled. These replace the absent financekit calendar.
  **Caveat: this field does NOT capture preliminary, guidance or restructuring releases.** On
  2026-10-23 LKQ fell 22.47% on a preliminary Q3 miss while the field still read 2026-07-30.
  The field is a screen, never a verdict — confirm against the headline.
* **Yahoo cross-check.** Yahoo's ASX feed appends a trailing live-stamp bar at a different
  time-of-day than the completed daily bars; naive last-two-bar math makes every ASX move read
  0.00%. The pipeline keeps only bars stamped at the modal time-of-day before differencing.
  Verified 2026-10-24: **27 cross-checks agreed, 0 mismatched.**
* BOD rows (no extended-hours data) go to source health only, not the headline table, per the
  skill. US preferred shares (slash tickers like JPM/PC) are excluded.

## STEP 4 — CATALYSTS (the one step the pipeline cannot do)

The skill caps catalysts at 5 US + 3 EU + 2 AU = 10 per run. Read
`/workspace/earnings/<date>-catalyst-targets.json` for the ticker list, then use `web_search` to
find the headline for each (cap 10 searches; 1-2 per ticker). For US names, the earnings-driven
test is: did `earnings_release_date` land within 7 days of today? If yes, mark `Y` and use the
earnings headline as the catalyst. If not, mark `N` and find a non-earnings catalyst. For EU/AU
names apply the skill's keyword test (earnings / results / Q1-Q4 / beats / misses / reports /
guidance; plus interim, half-year, full-year, dividend, ASIC, iron ore, lithium, gold for AU).

**Then write the catalyst table to `/workspace/catalog/catalysts/<date>.md`** (mkdir -p first)
and re-run the pipeline, which splices that file into the artifact's `## Catalysts` section.
Doing it this way means a re-run never wipes your work. You may also edit the table in place
instead, but then do not re-run the pipeline afterwards.

**Never fabricate a headline.** If a search returns nothing usable, write "no fresh catalyst found".

## STEP 5 — WRITE THE ARTIFACT

The pipeline writes `/workspace/earnings/<date>-reactions.md` with the TL;DR, the US headline
table, US QUIET one-liners, the EU/UK table, the ASX table, source health and the audit line.
Keep every other section as the pipeline wrote it — it carries the row counts, the cross-check
result and the freshness stamps.

If the script failed and no artifact exists, write a stub with `_source=skill_fetch_failed` and
report the error. Never improvise the tables from memory.


The pipeline dates the artifact from the **scheduled** date of this fire, not the execution date.
If this run is a delayed replay (the platform re-dispatches a session whose quota was exhausted),
the artifact must still carry the scheduled date, and it must say in the artifact that it is a
reconstruction produced late. A replay is normal, not an error — do not write a SKIPPED marker.

## GIT PUSH (OPTIONAL)

```bash
B=https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared
for U in "$B/push_artifact.sh" "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/push_artifact.sh"; do
  [ -s /workspace/push_artifact.sh ] || curl -sL -o /workspace/push_artifact.sh "$U"
done
sh /workspace/push_artifact.sh --out earnings --add earnings/{date}-reactions.md --branch main
sh /workspace/verify_delivery.sh --path earnings/{date}-reactions.md --branch main
```

**If the push script cannot be fetched**, use the inline fallback in
`cloud-prompts/_shared/push_artifact.sh` — but never `git add -A`, and never
`git push … | head -3` (that returns head's exit status and reports a rejected push as success).

## DELIVERY VERIFICATION (MANDATORY - do this after the push block)

The push above already verifies its own delivery: `push_artifact.sh` calls
`verify_delivery.sh` and only reports `push: ok` when the path is present on the remote branch.
Run it again if you need to re-check:

```bash
sh /workspace/verify_delivery.sh --path earnings/{date}-reactions.md --branch main
```

A `git push` that exits 0 is **not** proof of delivery — a push piped into `head` returns head's
exit status (always 0) and reports a rejected push as a success. That is why the delivery check
exists, and why the push script must never be run with `git push … | head -3`.

## DELIVERY
The final reply (the only thing delivered to the chat) MUST use this structure. There is **no
line cap** — cap by NAMES SHOWN (top ~8 per tier), not by lines. Long-form detail belongs in
the artifact file, not in the chat.

1. **Prose opener** — 2-4 sentences: the headline finding of the run, then the caveat that most
   changes how it should be read. Complete sentences; no label lists, no clipped fragments.
2. **`### Signal`** — tiered bullets, ONE ticker per line, each line a short clause naming the
   catalyst or setup. Follow the skill's chat rules for tier order, flags and the audit line.
   Lead with the top movers and the count of names, and give the source and any lag.
   State how many further names are in the artifact file.
3. **`### Method & caveats`** — 2-4 bullets: source(s), lag, universe/screen size, and every
   degraded or blocked source. Name what could not be verified.
4. **`### Files`** — one line per file written, with its sandbox path.
5. **`### Push / errors`** — one line for push status (`push: ok (verified)` /
   `push: skipped (token unset)` / `push: FAILED (<reason>)`) and one line for
   `errors: <n>` — count of **SOURCE** failures that degraded the artifact.
   0 = clean run. The absent `mcp__*` tools are NOT an error and must not be counted.

Do not narrate tool calls. Tool call → result → write → push → reply.

## CRITICAL REMINDERS
1. Window check first. If it says out-of-window, exit cleanly — the SKIPPED file is the artifact.
2. The MCP tools in the skill spec do not exist in Cloud. Use the pipeline from the shared repo.
3. Do not lower the volume floor of 10,000. Without it, illiquid rows report 30-90% phantom moves.
4. Read-only. No trade ideas. Never fabricate a catalyst headline or a data value.
5. Every number in the artifact must come from a payload you actually received. If a pass returned
   too few rows to be credible, report the row count rather than padding the table.
6. If the cross-check reports any mismatch, say so in the chat reply. A mismatch means the
   screener and Yahoo disagree on a move you are about to publish — investigate before shipping.