# Cloud Mavis cron: earnings-reaction-scanner (cron #15) — REPAIRED 2026-10-24

You are running as a Cloud Mavis cron on Mavis. Linux sandbox: no PowerShell, no Windows paths.
Output root: /workspace/ (mkdir -p it if missing).

## CONVERSATION TITLE (do this FIRST, before anything else)

Every scheduled run gets its own conversation — one conversation per fire, never appended to an
earlier run's conversation. Give this conversation a title that says which day this run belongs
to, so the conversation list stays scannable.

1. Resolve today's date in US/Eastern: `TZ=America/New_York date +%d-%m` (day-month, no year).
2. Build the title: `[<DD-MM>] 15-earnings-reaction-scanner` — substitute the date you just resolved.
3. Set it with one call: `mcp_invoke` with tool_name `session_update` and arguments
   `{"session_id": "me", "title": "<the title>"}`. `me` means THIS conversation.
   If `mcp_invoke` reports that the tool is unknown, call `tool_search` with the query
   "session title update", then retry the same `mcp_invoke` call.
4. If the title cannot be set for any reason, carry on with the routine. This step must never
   block, delay, or fail the artifact.

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
   --out earnings --name earnings_reaction_scanner \
   --label "Cron #15 earnings-reaction-scanner" \
   --nn 15
```

If the script exits non-zero, the fire is OUT OF WINDOW: do not fetch the skill, do not write
an artifact, do not push. The skip marker it wrote IS the audit trail for this run.

**Reply format for an out-of-window skip.** The `## DELIVERY` block expects a push line and
an errors line; a skipped fire has neither an artifact nor an error. Reply with these lines
and nothing else - do not narrate the tool calls and do not write an artifact:

```
out-of-window: <reason printed by the script>
file: no artifact (window check declined this fire - earnings/$DATE.md is intentionally absent)
push: marker pushed (refs/skipped-markers/$FIRE_DATE_SKIPPED_earnings_reaction_scanner.md) | marker push FAILED | marker push skipped (push script unavailable)
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

**Fetch it from the AUTHORITATIVE channels first.** The CDNs cache independently and can serve
STALE bytes for minutes to hours — measured 2026-11-04: `raw.githubusercontent.com` was **284s**
behind on a same-path edit, and `cdn.jsdelivr.net` was still serving the pre-fix copy of a shared
file **15 hours** after the fix was pushed. A stale pipeline silently runs the old code, so the
ladder below is ordered by AUTHORITATIVENESS, not speed:

1. the **GitHub connector** (`connector__github__get_file_contents`) — authenticated, reads through
   the API, never CDN-cached; measured 1s behind;
2. the **contents API with the sandbox token** — authoritative, and the token lifts the shared
   60/hr unauthenticated limit (measured 403 on 8 of 20 unauthenticated calls from this egress IP);
3. the **CDN copies** — last resort only.

**Validate the BODY, never the status code.** A 403/404 body is NOT empty: the unauthenticated
API returns `{"message":"API rate limit exceeded ...", ...}`, and saving that as the script breaks
the run. The `valid()` check below requires a real script — the `SCRIPT_VERSION` marker, the
**`REACTION_ARTIFACT_V2` capability marker**, and a clean Python compile.

**The capability marker is mandatory, not decoration.** An OLDER copy of the pipeline carries
`SCRIPT_VERSION` and compiles perfectly, so `SCRIPT_VERSION` alone cannot tell a stale blob from
the current one — and a stale pipeline silently runs the OLD procedure (the 2026-11-03 build
rolled every reference close back to the prior-prior session because of it). The marker names the
contract the copy implements, so only a copy that carries it may run.

```bash
cd /workspace
mkdir -p scripts
S=scripts/earnings_reaction_scanner.py
valid() { [ -s "$1" ] && grep -q 'SCRIPT_VERSION' "$1" 2>/dev/null \
          && grep -q 'REACTION_ARTIFACT_V2' "$1" 2>/dev/null \
          && python3 -c "import sys;compile(open(sys.argv[1]).read(),'x','exec')" "$1" 2>/dev/null; }

# 1) GitHub connector - authoritative, not CDN-cached
mcode-tools connector call connector__github__get_file_contents \
  --args '{"owner":"karizaco","repo":"minimax-cloud-outputs","path":"scripts/earnings_reaction_scanner.py","ref":"refs/heads/main"}' 2>/dev/null \
  | python3 -c "import sys,json;b=json.load(sys.stdin);sys.stdout.write(''.join((x.get('resource') or {}).get('text','') for x in b if isinstance(x,dict)))" > "$S.tmp" 2>/dev/null
valid "$S.tmp" && mv -f "$S.tmp" "$S"

# 2) contents API with the sandbox token
[ -s "$S" ] || curl -sSL --max-time 30 -H "Accept: application/vnd.github.raw" \
  -H "Authorization: Bearer ${GITHUB_TOKEN}" \
  -o "$S.tmp" "https://api.github.com/repos/karizaco/minimax-cloud-outputs/contents/scripts/earnings_reaction_scanner.py?ref=main" 2>/dev/null
valid "$S.tmp" && mv -f "$S.tmp" "$S"

# 3) CDN copies - last resort, they can be stale
[ -s "$S" ] || curl -sSL --max-time 30 -o "$S.tmp" \
  "https://raw.githubusercontent.com/karizaco/minimax-cloud-outputs/main/scripts/earnings_reaction_scanner.py" 2>/dev/null
valid "$S.tmp" && mv -f "$S.tmp" "$S"
rm -f "$S.tmp"

if [ -s "$S" ]; then grep -m1 'SCRIPT_VERSION' "$S"; else echo "pipeline fetch FAILED"; fi
```

If a `curl` step fails with a certificate/TLS error (the sandbox egress proxy rotates its leaf
cert), retry that same URL once with `-k`. If no channel yields a valid script, write a stub
artifact with `_source=skill_fetch_failed`, report `errors: 1`, stop. Never improvise the
procedure from memory.

**The pipeline also re-checks the shared-repo copy at startup and replaces itself if the fetch
was stale** (it compares byte-for-byte and re-execs on a newer copy). So even the CDN path in
step 3 cannot leave you running old code for long.

## SHARED INSTRUCTIONS (fetch once — these rules apply to every routine)

The fleet-wide instructions live in ONE file, not in every prompt. Fetch it in the same first
step as the pipeline/skill fetch, then follow it in full:

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
and re-run the pipeline, which **merges each row into that ticker's row in the artifact**. The
artifact has NO separate `## Catalysts` section — the catalyst is the last column of its row, so
a name can never appear twice in the markdown. Doing it this way means a re-run never wipes your
work. You may also edit the table in place instead, but then do not re-run the pipeline afterwards.

The file's format is one markdown table — `| Ticker | Region | Catalyst | Earnings-driven |` —
with the tickers from `/workspace/earnings/<date>-catalyst-targets.json` (5 US + 3 EU + 2 AU).
The pipeline writes a starter skeleton if the file is missing; fill it in and re-run.

**Never fabricate a headline.** If a search returns nothing usable, write "no fresh catalyst found".

## STEP 5 — WRITE THE ARTIFACT

The pipeline writes `/workspace/earnings/<date>-reactions.md` with the TL;DR, the **Actionable
read** section, the US headline table, US QUIET one-liners, the EU/UK table, the ASX table,
source health and the audit line. The artifact's skeleton, its required columns and the
one-table rule are the **ARTIFACT FORMAT CONTRACT v2** in the skill spec — read it there, not
from memory. Keep every section as the pipeline wrote it — it carries the row counts, the
cross-check result and the freshness stamps.

**Every published row carries `Ref close`, `Ref source`, `Ref asof`, `US tradeable` and
`Move vs avg daily`**, and the source-health section publishes `rows_dropped_stale_ref` and
`degraded_sources: <n>`. **The reply's `errors:` count MUST equal that `degraded_sources`
number** — one entry per degraded source, not one per run.

If the script failed and no artifact exists, write a stub with `_source=skill_fetch_failed` and
report the error. Never improvise the tables from memory.


The pipeline dates the artifact from the **scheduled** date of this fire, not the execution date.
If this run is a delayed replay (the platform re-dispatches a session whose quota was exhausted),
the artifact must still carry the scheduled date, and it must say in the artifact that it is a
reconstruction produced late. A replay is normal, not an error — do not write a SKIPPED marker.

## STEP 5b — VERIFY THE ARTIFACT AGAINST THE CONTRACT (before the push)

The pipeline renders the contract by construction, but a manual edit can break it — and the
contract is the thing the reader relies on. Fetch the independent checker and run it on the
artifact. It exits 1 and names every violation.

```bash
C=/workspace/check_reaction_artifact.py
for U in \
  "https://api.github.com/repos/karizaco/maxhermes-migration/contents/tools/check_reaction_artifact.py?ref=main" \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/tools/check_reaction_artifact.py" \
  "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/tools/check_reaction_artifact.py" ; do
  curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" \
    -H "Authorization: Bearer ${GITHUB_TOKEN}" -o "$C.tmp" "$U" 2>/dev/null
  if [ -s "$C.tmp" ] && grep -q 'REACTION_ARTIFACT_V2' "$C.tmp" 2>/dev/null; then
    mv -f "$C.tmp" "$C"; break
  fi
  rm -f "$C.tmp"
done
if [ -s "$C" ]; then
  python3 "$C" /workspace/earnings/${DATE}-reactions.md || echo "CONTRACT CHECK FAILED - fix the artifact before pushing"
fi
```

If the checker cannot be fetched, say so in `### Method & caveats` and carry on — do not fail the
run over a missing verifier. If it RUNS and fails, fix the artifact (or re-run the pipeline) and
run it again. Do not push an artifact the checker rejected.

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

The push above already verifies its own delivery: `push_artifact.sh` calls `verify_delivery.sh`
and only reports `push: ok` when the path is present on the remote branch.
Run it again if you need to re-check:

```bash
sh /workspace/verify_delivery.sh --path earnings/{date}-reactions.md --branch main
```

A `git push` that exits 0 is **not** proof of delivery — a push piped into `head` returns head's
exit status (always 0) and reports a rejected push as a success. That is why the delivery check
exists, and why the push script must never be run with `git push … | head -3`.

## DELIVERY
The reply format is the house standard in `cloud-prompts/_shared/PROMPT-BLOCKS.md` — fetch that
file with the shared-instructions block above and follow its `## DELIVERY` section (prose opener,
`### Signal`, `### Method & caveats`, `### Files`, `### Push / errors`).

Do NOT keep a local copy of the reply format here. This prompt used to carry one, and it had
already drifted from the shared file — two copies of one standard is exactly how a routine ends
up answering in a format nobody else expects. The shared file is fetched at run time, so a fix
to the standard lands on the next fire with no redeploy.

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