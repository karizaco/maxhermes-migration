# Cloud Mavis cron: ntrt-gap-brief-daily (cron #25)

You are running as a Cloud Mavis cron. No local filesystem, no PowerShell, no Windows paths.
Output directory on this sandbox: `/workspace/` (Linux-style paths only; if /workspace/ does not exist, run `mkdir -p /workspace` first).

## CONVERSATION TITLE (do this FIRST, before anything else)

Every scheduled run gets its own conversation — one conversation per fire, never appended to an
earlier run's conversation. Set the title before anything else: follow the
`## CONVERSATION TITLE` block in `cloud-prompts/_shared/PROMPT-BLOCKS.md` and the
`## Scheduled-run conversation title` block in the skill spec (the skill is the backstop if the
shared fetch fails). In short: resolve the date in US/Eastern, build
`[<DD-MM>] 25-ntrt-gap-brief-daily`, and set it with ONE `session_update` call on `me`.
This step must never block, delay, or fail the artifact.

## SCHEDULE
- Original local schedule: morning
- Deployed schedule: `45 8 * * 1-5` America/New_York — 08:45 ET, Mon-Fri.
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
the wall clock.** The platform resumes a crashed cron conversation IN PLACE, so on a replay "now"
names the resume day, not the fire day: judging by the wall clock both skips real briefs (a
Friday fire replayed on a Saturday) and publishes briefs for a closed market.

Resolve it with ONE call, no cron_read needed:

```
mcp_invoke  tool_name=session_get  arguments={"session_id":"me"}
```

Take `session.created_at` (epoch milliseconds) and pass it as `--scheduled-at-ms`. The script
prints `fire-date:` - use THAT for the artifact path in `## OUTPUT`, so the gate and the artifact
can never disagree about which day they belong to.

```bash
# --- fetch the ONE shared window check (run-time fetch: fixes land with no redeploy) ---
# The CAPABILITY check is mandatory: an OLDER copy of this script is still published and it
# silently IGNORES unknown flags - without the check you would run a gate that never fires, and
# a holiday fire would publish a brief for a closed market. The contents API is authoritative
# and is not CDN-cached, so it is tried FIRST.
S=/workspace/window_check.sh
for U in \
  "https://api.github.com/repos/karizaco/maxhermes-migration/contents/cloud-prompts/_shared/window_check.sh?ref=main" \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/window_check.sh" \
  "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/window_check.sh" ; do
  curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" -o "$S.tmp" "$U" 2>/dev/null
  # A 404 page is a non-empty body that is NOT a script. Require BOTH: a real script AND the
  # capability marker.
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
   --out ntrt --name ntrt_gap_brief_daily \
   --label "Cron #25 ntrt-gap-brief-daily" \
   --nn 25
```

If the script exits non-zero, the fire is OUT OF WINDOW: do not fetch the skill, do not write
an artifact, do not push. The skip marker it wrote IS the audit trail for this run.

**Reply format for an out-of-window skip.** The `## DELIVERY` block expects a push line and
an errors line; a skipped fire has neither an artifact nor an error. Reply with these lines
and nothing else - do not narrate the tool calls and do not write an artifact:

```
out-of-window: <reason printed by the script>
file: no artifact (window check declined this fire - ntrt/$DATE.md is intentionally absent)
push: marker pushed (refs/skipped-markers/$FIRE_DATE_SKIPPED_ntrt_gap_brief_daily.md) | marker push FAILED | marker push skipped (push script unavailable)
errors: 0
```


## SKILL SPEC (FETCH ONCE)
The skill's procedure body lives here:
  https://api.github.com/repos/karizaco/maxhermes-migration/contents/cloud-prompts/skills/ntrt-gap-brief/SKILL.md?ref=main

**FIRST tool call:** `curl -sL -H "Accept: application/vnd.github.raw" -H "Authorization: Bearer ${GITHUB_TOKEN}" "https://api.github.com/repos/karizaco/maxhermes-migration/contents/cloud-prompts/skills/ntrt-gap-brief/SKILL.md?ref=main"` (or `web_fetch` if available).
Read the procedure in full. Do NOT skip this step.

If curl fails with a certificate/TLS error (the sandbox egress proxy rotates its leaf cert and has
expired mid-session before), fall back to `web_fetch` on the SAME url. If both fail: write a stub
artifact with `_source=skill_fetch_failed`, report `errors: 1`, and stop. Never improvise from memory.


### FOR THIS ROUTINE: the TradingView public screener is the primary data source

This brief is a **pre-market gap screen**, and the skill's Mode B screener is the one source that
returns **pre-market volume** alongside the pre-market print. Use the **public endpoint** — the
MCP tool `mcp__tradingview_advanced__screen_stocks` is usually not registered here (verified
2026-11-01: catalog 133 tools, 0 finance), while the public endpoint works:

`POST https://scanner.tradingview.com/america/scan` (headers: `Content-Type: application/json`,
`User-Agent: Mozilla/5.0`, `Origin: https://www.tradingview.com`)

```json
{"filter":[{"left":"type","operation":"equal","right":"stock"},
           {"left":"exchange","operation":"not_in_range","right":["OTC"]},
           {"left":"premarket_change","operation":"in_range","right":[3,1000]}],
 "options":{"lang":"en"},"markets":["america"],
 "symbols":{"query":{"types":[]},"tickers":[]},
 "columns":["name","close","premarket_close","premarket_change","premarket_volume",
            "market_cap_basic","average_volume_30d_calc","sector","exchange"],
 "sort":{"sortBy":"premarket_change","sortOrder":"desc"},"range":[0,2000]}
```

Run it **twice** — `premarket_change` in `[3,1000]` (desc) and in `[-1000,-3]` (asc) — so both sides
are carried, then rank by **absolute** `premarket_change`.

Six rules that decide whether this brief is right:

- **`type: "stock"` includes REITs.** Do not re-filter to common stock. On 2026-10-30 a universe
  seeded on common stock only hid **ARI (-63.9%)**, the largest mover of the day.
- **There is NO market-cap filter in the request.** The $200M floor is applied AFTER the scan.
  A filter on `market_cap_basic` deletes the name outright, and it deleted the day's most violent
  prints: on 2026-11-04 **PARA −88.6%**, **CRIS +87.7%**, **CENN −57.2%** and **DKI +54.0%** were
  all excluded by it. The skill publishes them in a `### Below the $200M floor` watchlist
  (skill §10) instead of losing them.
- **`range` is a page size, not a filter.** Use `[0,2000]` and CHECK the pull: `totalCount` must
  equal the number of rows returned, on both sides. A truncated pull is a failed pull — pull the
  missing slice or report the pull as failed (skill §7).
- **`premarket_volume` is the importance measure.** Divide by `average_volume_30d_calc` for % of
  ADV and publish it. A ±20% gap on 100 shares is a quote, not a market. **Yahoo has NO pre-market
  volume** (0 on every pre-market bar), so a Yahoo-only route cannot publish this column.
- **Yahoo's pre-market tape goes stale** on thinly-traded names — a flat print left from hours
  earlier. Never publish a Yahoo pre-market price or range without checking it against the
  screener, and drop any Yahoo range where the two disagree by more than ~0.6%.
- **TradingView's `premarket_*` columns hold only the most recent session.** For a session older
  than the last one they are gone — use `premarketprice.com/premarket-{gainers,losers}/<date>`
  and Chartmill's dated articles instead.


## SHARED INSTRUCTIONS (fetch once — these rules apply to every routine)

The fleet-wide instructions live in ONE file, not in every prompt. Fetch it in the same first
step as the skill spec below, then follow it in full — **including its
`## SHARED HELPER FETCHES` block**, which downloads `push_artifact.sh`, `verify_delivery.sh` and
`skip_marker.sh`. Run that block in step 1: a helper that is only *called* is not on disk, and
the DELIVERY step cannot verify a push with a script it never downloaded.

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
  `/workspace/ntrt/{date}.md`

The `{date}` placeholder is the fire's **scheduled** date in US/Eastern, `YYYY-MM-DD`. **Take it
from the `fire-date:` line the WINDOW CHECK printed above** — that is the one source of truth for
this fire's date, it is derived from the same `scheduled_at_ms` the gate judged, and the gate and
the artifact path can then never disagree. Do NOT take it from `date` at execution time and do NOT
call `cron_read view=runs` for it: on a replay the wall clock names the resume day, not the fire
day. If the fire date and the wall-clock date differ, this is a **delayed replay**: rebuild for
the scheduled date, do NOT write a SKIPPED marker, and say in the artifact that it is a
reconstruction produced late. A replay is normal, not an error.
(Literal text "{date}" in this template — replace it with the actual date.)

This routine ships **TWO** outputs: the markdown above and the **CSV companion** the skill's
contract mandates, at `/workspace/ntrt/{date}.csv`. Both are part of the deliverable and **both
are pushed and verified** (see the push block). The skill's contract checker runs on BOTH files
before the push (skill §9) — a brief without its CSV cannot pass the contract.

## GIT PUSH (MANDATORY - both files, both verified)

The shared helpers are fetched by the `## SHARED HELPER FETCHES` block in
`cloud-prompts/_shared/PROMPT-BLOCKS.md` (contents API first, then the two CDNs, with a
capability marker). Fetch them **in the first step, with the skill spec** — a helper that is
only *called* is not on disk, and `verify_delivery.sh` is called without being downloaded.

```bash
sh /workspace/push_artifact.sh --out ntrt --add ntrt/{date}.md --add ntrt/{date}.csv \
   --branch main --nn 25 --msg "cron 25 ntrt-gap-brief-daily {date}"
sh /workspace/verify_delivery.sh --path ntrt/{date}.md  --branch main
sh /workspace/verify_delivery.sh --path ntrt/{date}.csv --branch main
```

- **`--nn 25` is not decoration.** The routine number travels with the call, so a commit that
  carries the artifact can be attributed to cron #25 from its subject alone.
- **Both paths are verified.** The push script verifies its own `--add` path; the CSV is a second
  `--add` and needs its own `verify_delivery.sh` call. A push that reports ok while the CSV is
  missing is a half-delivery.
- **If the push script cannot be fetched**, use the inline fallback in
  `cloud-prompts/_shared/push_artifact.sh` — but never `git add -A`, and never
  `git push … | head -3` (that returns head's exit status and reports a rejected push as success).

## DELIVERY VERIFICATION (MANDATORY - do this after the push block)

The push above already verifies its own delivery: `push_artifact.sh` calls `verify_delivery.sh`
and only reports `push: ok` when the path is present on the remote branch. Run it again for the
CSV path — that one is not covered by the push script's own check:

```bash
sh /workspace/verify_delivery.sh --path ntrt/{date}.md  --branch main
sh /workspace/verify_delivery.sh --path ntrt/{date}.csv --branch main
```

A `git push` that exits 0 is **not** proof of delivery — a push piped into `head` returns head's
exit status (always 0) and reports a rejected push as a success. That is why the delivery check
exists, and why the push script must never be run with `git push … | head -3`.


## CRITICAL REMINDERS
1. Skill URL above MUST be fetched first. If the fetch fails, write a stub artifact with
   `_source=skill_fetch_failed` and reply with the failure. Do NOT improvise the procedure from memory.
2. Use ONLY the tools named in the RUNTIME DATA-SOURCE CONTRACT above (`web_search`, `web_fetch`, `bash`). Do NOT call the `mcp__*` tools — they are not
   registered in this runtime — and do not invent tool names.
3. The cron session is fresh each time — there is no shared state. Treat every artifact as ephemeral unless pushed.
4. If the cron fires outside its intended window (a US market holiday — the scheduler owns the day-of-week, so a weekend fire cannot happen), exit cleanly with "out-of-window: <reason>". Do NOT run a degraded version.
5. **TWO files ship: `{date}.md` and `{date}.csv`.** The contract checker runs on both (skill §9) and both are pushed and verified. A brief without its CSV is not a delivered brief.
6. **`{date}` comes from the WINDOW CHECK's `fire-date:` line**, not from the wall clock and not from `cron_read view=runs`.
7. **The screen is scanned WITHOUT the market-cap filter** and the pull must be complete (`totalCount` == rows returned). The $200M floor is applied after the scan, and the names it excludes are published in the skill's below-the-floor watchlist.

================================================================
END OF CRON PROMPT
================================================================