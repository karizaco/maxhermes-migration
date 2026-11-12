# Cloud Mavis cron: reversal-bullish-3:55 (cron #04)

You are running as a Cloud Mavis cron. No local filesystem, no PowerShell, no Windows paths.
Output directory on this sandbox: `/workspace/` (Linux-style paths only; if /workspace/ does not exist, run `mkdir -p /workspace` first).

## CONVERSATION TITLE (do this FIRST, before anything else)

Every scheduled run gets its own conversation — one conversation per fire, never appended to an
earlier run's conversation. Give this conversation a title that says which day this run belongs
to, so the conversation list stays scannable.

1. Resolve today's date in US/Eastern: `TZ=America/New_York date +%d-%m` (day-month, no year).
2. Build the title: `[<DD-MM>] <NN>-<routine name>`. Take `<NN>` and `<routine name>` from the
   first line of this prompt (`# Cloud Mavis cron: <routine name> (cron #NN)`).
   Example: `[01-11] 04-reversal-bullish-3:55`.
3. Set it with one call: `mcp_invoke` with tool_name `session_update` and arguments
   `{"session_id": "me", "title": "<the title>"}`. `me` means THIS conversation.
   If `mcp_invoke` reports that the tool is unknown, call `tool_search` with the query
   "session title update", then retry the same `mcp_invoke` call.
4. If the title cannot be set for any reason, carry on with the routine. This step must never
   block, delay, or fail the artifact.

## SCHEDULE
- Original local schedule: 15:55 ET weekdays
- Deployed schedule: `55 15 * * 1-5` America/New_York — 15:55 ET, Mon-Fri.
- The day-of-week field is set in the SCHEDULER, so this routine does not fire at all on
  weekends: no agent invocation is spent discovering it is a weekend, and no weekend SKIPPED
  file is written. The WINDOW CHECK below keeps the one guard a cron expression cannot
  express — the market-holiday list.


## SIGNAL DAY - THIS ROUTINE SCANS **TODAY'S LIVE SESSION**

**The signal bar is TODAY's live candle, not yesterday's settled bar.** At 15:55 ET the session
is ~99% complete, so today's OHLC is readable NOW, and Bonde's entry is today's close (he enters
3.58-4PM, or MOC).

**Never report yesterday's settled candle as today's signal.** shibui is end-of-day, so at 15:55 ET
"the latest settled date in shibui" is YESTERDAY. A scan built on it measures the previous
session's candle and points at an entry one session after the signal - and the D-day bar can
invalidate the setup before the entry happens. The 2026-10-30 run measured Thursday's candle on a
Friday and reported DOCU, whose Friday candle was a weak close (DCR 0.24).

**Run the screen - do not re-implement it.** The skill's §5 carries the whole procedure: the
day-alignment assertion that proves which session is being scanned, the data path, the gates and
the trading-view paging trap. Read §5, then:

```bash
mkdir -p /workspace/tools
S=/workspace/tools/reversal_bullish.py
for U in \
  "https://api.github.com/repos/karizaco/maxhermes-migration/contents/tools/reversal_bullish.py?ref=main" \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/tools/reversal_bullish.py" \
  "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/tools/reversal_bullish.py" ; do
  curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" -o "$S.tmp" "$U" 2>/dev/null
  # The CAPABILITY MARKER is mandatory. The raw CDN has been measured serving a stale blob
  # for >17 minutes after a push, and a copy of the OLD script would publish the OLD stop
  # rule and the OLD artifact shape - the run would look clean and be wrong. The contents
  # API is authoritative and is NOT CDN-cached, so it is tried FIRST.
  if [ -s "$S.tmp" ] && grep -q 'bonde-artifact-v4' "$S.tmp" 2>/dev/null; then
    mv -f "$S.tmp" "$S"; break
  fi
  rm -f "$S.tmp"
done
if [ ! -s "$S" ] || ! grep -q 'bonde-artifact-v4' "$S"; then
  echo "reversal_bullish.py: UNAVAILABLE (no copy carrying the current contract marker)"
  echo "no artifact; no push"
  exit 1
fi
python3 "$S" --date "$(TZ=America/New_York date +%F)"
```

Read its JSON report: `mode` is `LIVE` / `NO_SESSION` / `DEGRADED` / `SETTLED_REPLAY`, `passing` is
the candidate count, `history_source` is shibui or nasdaq. Exit code 3 means "no US session today"
- a clean outcome, not a failure.

- `NO_SESSION` -> write the no-session artifact, push it, and say so. **Do not substitute the
  previous session's scan.**
- `DEGRADED` -> the artifact is not tradeable. Say so plainly and promote no names.
- `LIVE` -> the signal is today's candle. The entry is today's close.

Then reduce to 1-3 ideas the way Bonde does - "the reversal bar has to jump off the chart", "no
catalyst, no trade" - and give every candidate in the reply a named catalyst.

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
   --out daily-screens --name reversal_bullish_3_55 \
   --label "Cron #04 reversal-bullish-3:55" \
   --nn 04
```

If the script exits non-zero, the fire is OUT OF WINDOW: do not fetch the skill, do not write
an artifact, do not push. The skip marker it wrote IS the audit trail for this run.

**Reply format for an out-of-window skip.** The `## DELIVERY` block expects a push line and
an errors line; a skipped fire has neither an artifact nor an error. Reply with these lines
and nothing else - do not narrate the tool calls and do not write an artifact:

```
out-of-window: <reason printed by the script>
file: no artifact (window check declined this fire - daily-screens/$DATE.md is intentionally absent)
push: marker pushed (refs/skipped-markers/$FIRE_DATE_SKIPPED_reversal_bullish_3_55.md) | marker push FAILED | marker push skipped (push script unavailable)
errors: 0
```

## SKILL SPEC (FETCH ONCE)
The skill's procedure body lives here:
  https://api.github.com/repos/karizaco/maxhermes-migration/contents/cloud-prompts/skills/stock-screener-suite/SKILL.md?ref=main

**FIRST tool call:** `curl -sL -H "Accept: application/vnd.github.raw" -H "Authorization: Bearer ${GITHUB_TOKEN}" "https://api.github.com/repos/karizaco/maxhermes-migration/contents/cloud-prompts/skills/stock-screener-suite/SKILL.md?ref=main"` (or `web_fetch` if available). Read the procedure in full. Do NOT skip this step.
Then follow the procedure verbatim, with these Cloud adaptations below.


## BONDE GATES (corrected 2026-11-02 — read together with the skill spec)

The gate values in the skill's §5 table are Bonde's **published** ones. Four of them changed on
2026-11-02 after an audit of the 2026-10-26 signal bar (full write-up:
`daily-screens/2026-10-27/reversal-bullish-3:55-CORRECTION.md` in karizaco/minimax-cloud-outputs):

1. **DCR ≥ 0.60, not 0.50** — Bonde's published `(c-l)/(h-l) >= .6`, i.e. the close sits in the top
   40% of the day's range. The old 0.50 floor let dojis with a dominating upper wick through.
2. **Prior decline = a real washout** — the bar must undercut the prior close by ≥ 1.5% intraday
   **and** the stock must be down ≥ 3% over the 3 preceding sessions (or ≥ 3% over 5). The old
   `close < close_2d_ago` was satisfied by a single marginal down day, so a sideways drift passed it.
3. **The hammer test replaces the tail:body ratio** — `(o-l) > (c-o)` plus lower shadow ≥ 2× upper
   shadow. The ratio explodes on a near-doji body (15×–17×) and is not a usable gate; quote it as a
   description, never as a pass/fail.
4. **Price floor $5, not $15** — Bonde's published `c >= 5`. "Prefer higher priced stocks" is a
   **ranking** preference applied when ordering the final list, not a filter.

The **stop** is Bonde's own rule (corrected 2026-11-12, contract v4): the **low of the candle
body** is the default and is used whenever it is a real level (more than 0.10% below the entry);
the signal bar's **low** is his explicitly sanctioned ALTERNATIVE, legal only when it is within
2.5% of the purchase price, and it is used when the body low is degenerate — i.e. when it sits on
the entry (0.07% wide on the 2026-10-26 CBRE bar, 0.00% on ADBE and TRI on 2026-11-10, where a
stop AT the entry is not a stop). A shadow low more than 2.5% from the entry is not a legal stop,
so the body low stands; if the body low is degenerate too, the row is `NO_LEGAL_STOP` and the
name is NOT a trade. The stop is placed the **next morning**, not at the entry: Bonde buys at
3.55-3.58 **without a stop**. Both levels, the body/shadow distances and the degeneracy flag are
published on every row, and `tools/check_bonde_artifact.py` asserts the rule.

**The gate values above are what the screen applies.** They are implemented in
`tools/reversal_bullish.py` - run it, per the SIGNAL DAY section above, rather than writing the
SQL by hand. The canonical reference SQL is `emit-sql reversal_bullish <date>` in the skill's
`scripts/screen.py` (60-day window, `rn = 1` per symbol, `shibui.valuation` reduced to each
symbol's most recent row); it is a **settled** scan, so it is for a delayed replay only - it can
never produce a same-day entry.

Two things the screen cannot do:

- **Reduce to 1-3 ideas** the way Bonde does - "the reversal bar has to jump off the chart", "no
  catalyst, no trade". A floor-exact DCR or a stop-distance tie-breaker is **not** a reason to
  promote a name, and every candidate in the reply needs a named catalyst.
- **On a delayed replay only** (the scheduled date is not today), resolve each candidate against
  that session's close and report a *noise breach* (a close a few cents below a doji body stop)
  separately from a *structural failure* (the session undercut the signal bar's low). Never report
  both as "stop hit".


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
Write the artifact to (Windows-safe basename — underscore, never colon):
  `/workspace/daily-screens/{date}/reversal-bullish-3_55.md`
  `/workspace/daily-screens/{date}/reversal-bullish-3_55.csv`

The `{date}` placeholder is the fire's **scheduled** date in US/Eastern, `YYYY-MM-DD`. Resolve it
from the run's `scheduled_at_ms` (`cron_read view:runs` → `run.scheduled_at_ms`), not from `date`
at execution time. If they differ, this is a **delayed replay**: rebuild for the scheduled date,
do NOT write a SKIPPED marker, and say in the artifact that it is a reconstruction produced late.
A replay is normal, not an error.
(Literal text "{date}" in this template — replace it with the actual date.)

If the skill produces multiple outputs (e.g. .md + .csv, or per-region files), write all of them in the same `/workspace/daily-screens/{date}/` subdirectory, with `{date}` as part of each filename.

## GIT PUSH (OPTIONAL)

```bash
B=https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared
for U in "$B/push_artifact.sh" "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/push_artifact.sh"; do
  [ -s /workspace/push_artifact.sh ] || curl -sL -o /workspace/push_artifact.sh "$U"
done
sh /workspace/push_artifact.sh --out daily-screens --add daily-screens/{date}/reversal-bullish-3_55.md --branch main
sh /workspace/verify_delivery.sh --path daily-screens/{date}/reversal-bullish-3_55.md --branch main
```

**If the push script cannot be fetched**, use the inline fallback in
`cloud-prompts/_shared/push_artifact.sh` — but never `git add -A`, and never
`git push … | head -3` (that returns head's exit status and reports a rejected push as success).

## DELIVERY VERIFICATION (MANDATORY - do this after the push block)

The push above already verifies its own delivery: `push_artifact.sh` calls `verify_delivery.sh`
and only reports `push: ok` when the path is present on the remote branch.
Run it again if you need to re-check:

```bash
sh /workspace/verify_delivery.sh --path daily-screens/{date}/reversal-bullish-3_55.md --branch main
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
5. **The signal is TODAY's live session.** Never report yesterday's settled candle as today's signal. If the tool prints `mode: NO_SESSION`, there was no US session - write the no-session artifact, push it, and say so; do NOT substitute the previous session's scan.
6. **If `mode: DEGRADED`, the artifact is not tradeable.** Say so plainly in the reply. Do not promote names from a degraded run.
7. **Run `tools/reversal_bullish.py`.** Do not re-implement the gates by hand - the day-alignment assertion is what keeps the signal on the right day.

================================================================
END OF CRON PROMPT
================================================================
