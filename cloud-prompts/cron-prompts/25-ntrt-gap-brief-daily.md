# Cloud Mavis cron: ntrt-gap-brief-daily (cron #25)

You are running as a Cloud Mavis cron. No local filesystem, no PowerShell, no Windows paths.
Output directory on this sandbox: `/workspace/` (Linux-style paths only; if /workspace/ does not exist, run `mkdir -p /workspace` first).

## SCHEDULE
- Original local schedule: morning
- Deployed schedule: `0 9 * * 1-5` America/New_York — 09:00 ET, Mon-Fri.
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
DATE=$(TZ=America/New_York date +%Y-%m-%d)
case "$DATE" in
    2026-01-01|2026-01-19|2026-02-16|2026-04-03|2026-05-25|2026-06-19|2026-07-03|2026-09-07|2026-11-26|2026-12-25)
        mkdir -p /workspace/$DATE
        cat > /workspace/$DATE/SKIPPED_ntrt_gap_brief_daily.md <<EOF
# Cron #25 ntrt_gap_brief_daily — SKIPPED
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
  https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/skills/ntrt-gap-brief/SKILL.md

**FIRST tool call:** `curl -s https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/skills/ntrt-gap-brief/SKILL.md` (or `web_fetch` if available).
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
           {"left":"market_cap_basic","operation":"egreater","right":200000000},
           {"left":"premarket_change","operation":"in_range","right":[3,1000]}],
 "options":{"lang":"en"},"markets":["america"],
 "symbols":{"query":{"types":[]},"tickers":[]},
 "columns":["name","close","premarket_close","premarket_change","premarket_volume",
            "market_cap_basic","average_volume_30d_calc","sector","exchange"],
 "sort":{"sortBy":"premarket_change","sortOrder":"desc"},"range":[0,600]}
```

Run it **twice** — `premarket_change` in `[3,1000]` (desc) and in `[-1000,-3]` (asc) — so both sides
are carried, then rank by **absolute** `premarket_change`.

Four rules that decide whether this brief is right:

- **`type: "stock"` includes REITs.** Do not re-filter to common stock. On 2026-10-30 a universe
  seeded on common stock only hid **ARI (-63.9%)**, the largest mover of the day.
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
  `/workspace/ntrt/{date}.md`

The `{date}` placeholder is the fire's **scheduled** date in US/Eastern, `YYYY-MM-DD`. Resolve it
from the run's `scheduled_at_ms` (`cron_read view=runs` → `run.scheduled_at_ms`), not from `date`
at execution time. If they differ, this is a **delayed replay**: rebuild for the scheduled date,
do NOT write a SKIPPED marker, and say in the artifact that it is a reconstruction produced late.
A replay is normal, not an error.
(Literal text "{date}" in this template — replace it with the actual date.)

If the skill produces multiple outputs (e.g. .md + .csv, or per-region files), write all of them in the same `/workspace/ntrt/` subdirectory, with `{date}` as part of each filename.

## GIT PUSH (OPTIONAL)

```bash
B=https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared
for U in "$B/push_artifact.sh" "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/push_artifact.sh"; do
  [ -s /workspace/push_artifact.sh ] || curl -sL -o /workspace/push_artifact.sh "$U"
done
sh /workspace/push_artifact.sh --out ntrt --add ntrt/{date}.md --branch main --msg "cron 25 ntrt-gap-brief-daily {date}" --nn 25
sh /workspace/verify_delivery.sh --path ntrt/{date}.md --branch main
```

**If the push script cannot be fetched**, use the inline fallback in
`cloud-prompts/_shared/push_artifact.sh` — but never `git add -A`, and never
`git push … | head -3` (that returns head's exit status and reports a rejected push as success).

## DELIVERY VERIFICATION (MANDATORY - do this after the push block)

The push above already verifies its own delivery: `push_artifact.sh` calls
`verify_delivery.sh` and only reports `push: ok` when the path is present on the remote branch.
Run it again if you need to re-check:

```bash
sh /workspace/verify_delivery.sh --path ntrt/{date}.md --branch main
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

================================================================
END OF CRON PROMPT
================================================================