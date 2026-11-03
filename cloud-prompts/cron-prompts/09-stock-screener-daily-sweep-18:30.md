# Cloud Mavis cron: stock-screener-daily-sweep-18:30 (cron #09)

You are running as a Cloud Mavis cron. No local filesystem, no PowerShell, no Windows paths.
Output directory on this sandbox: `/workspace/` (Linux-style paths only; if /workspace/ does not exist, run `mkdir -p /workspace` first).

## SCHEDULE
- Original local schedule: 18:30 ET weekdays
- Deployed schedule: `30 18 * * 1-5` America/New_York — 18:30 ET, Mon-Fri.
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
          sh "$S" --out daily-screens --name stock_screener_daily_sweep_18_30 \
             --label "Cron #09 stock-screener-daily-sweep-18:30" \
             --reason "US market holiday ($DATE)" \
             --nn 09 --date "$DATE" || \
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

## SKILL SPEC (FETCH ONCE)
The skill's procedure body lives here:
  https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/skills/stock-screener-suite/SKILL.md

**FIRST tool call:** `curl -s https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/skills/stock-screener-suite/SKILL.md` (or `web_fetch` if available). Read the procedure in full. Do NOT skip this step.
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
  `/workspace/daily-screens/{date}/daily-sweep.md`

The `{date}` placeholder is the fire's **scheduled** date in US/Eastern, `YYYY-MM-DD`. Resolve it
from the run's `scheduled_at_ms` (`cron_read view=runs` → `run.scheduled_at_ms`), not from `date`
at execution time. If they differ, this is a **delayed replay**: rebuild for the scheduled date,
do NOT write a SKIPPED marker, and say in the artifact that it is a reconstruction produced late.
A replay is normal, not an error.
(Literal text "{date}" in this template — replace it with the actual date.)

If the skill produces multiple outputs (e.g. .md + .csv, or per-region files), write all of them in the same `/workspace/daily-screens/{date}/` subdirectory, with `{date}` as part of each filename.

This cron is the END-OF-DAY breadth read (fires 18:30 ET, from the settled daily close). Cron #10
(breadth-snapshot, 14:00 ET) runs the SAME skill into the SAME dated directory, so the two crons
must never share a filename. Therefore:

- Write `daily-sweep.md` as the primary artifact, plus the skill's other outputs, including
  `breadth.md` and the regime payload. `breadth.md` and `_regime.json` are THIS cron's paths.
- Do NOT write `breadth-snapshot.md`, `breadth-snapshot.csv` or `breadth-snapshot.json` - those
  belong to cron #10, which fired 4.5 h earlier and already pushed them. If the skill leaves a
  `breadth-snapshot.*` file in your output directory, DELETE it before the push step and say so
  in the reply; otherwise your copy would overwrite #10's intraday read on the branch.
- Do NOT rename this cron's regime payload to `_regime-intraday.json`. That name belongs to
  cron #10. `_regime.json` is yours AND is the canonical slot: the stock-screener-suite
  contract has the pre-market brief read `daily-screens/<date>/_regime.json`, and the
  end-of-day sweep is the authoritative writer of it. If the skill emits the regime payload
  under another name (it has been writing `_regime-screener.json`), RENAME it to
  `_regime.json` before the push step. You may ALSO write `_regime-screener.json` as an alias
  for anything already reading it, but the alias alone is not enough - it leaves
  `_regime.json` stale or missing, and a missing `_regime.json` is a real gap, not a naming
  preference.
- Never delete `breadth-snapshot.md` from the branch. #10's intraday read and this cron's
  end-of-day read are meant to sit side by side in `daily-screens/<date>/`.

## SELF-DESCRIPTION (mandatory — front-matter of `breadth.md`)
This cron is the END-OF-DAY breadth read (fires 18:30 ET, from the settled daily close).
Cron #10's `breadth-snapshot.md` is the INTRADAY read (14:00 ET, live tape). The two are SUPPOSED
to differ and they will — different VIX quote times, and historically a different breadth
universe. The front-matter of `breadth.md` must therefore state all of the following, so a reader
never has to guess which of the two files is authoritative:

- `fire_time_et` — the exact time this cron fired.
- `data_date` — the session date the breadth numbers describe, and whether the feed is T+1.
- `breadth_universe` — the EXACT population and filter used, e.g. "S&P 500 constituents, 502
  names" or "NYSE/NASDAQ/AMEX, market cap > $10B, 905 names". Not "the market". Not "S&P 500"
  unless it is.
- `vix_quote_time` — the timestamp of the VIX/VIX3M pair, and the source feed used for it.
- `cross_reference` — "intraday counterpart: daily-screens/<date>/breadth-snapshot.md (cron #10,
  14:00 ET)".
- Exactly ONE VIX/VIX3M pair, used everywhere in the document. Never quote two different
  volatility readings in one artifact, and never silently mix a mid-session print with a settled
  close.

## GIT PUSH (OPTIONAL)

```bash
B=https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared
for U in "$B/push_artifact.sh" "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/push_artifact.sh"; do
  [ -s /workspace/push_artifact.sh ] || curl -sL -o /workspace/push_artifact.sh "$U"
done
sh /workspace/push_artifact.sh --out daily-screens --add daily-screens/{date}/daily-sweep.md --branch main
sh /workspace/verify_delivery.sh --path daily-screens/{date}/daily-sweep.md --branch main
```

**If the push script cannot be fetched**, use the inline fallback in
`cloud-prompts/_shared/push_artifact.sh` — but never `git add -A`, and never
`git push … | head -3` (that returns head's exit status and reports a rejected push as success).

## DELIVERY VERIFICATION (MANDATORY - do this after the push block)

The push above already verifies its own delivery: `push_artifact.sh` calls
`verify_delivery.sh` and only reports `push: ok` when the path is present on the remote branch.
Run it again if you need to re-check:

```bash
sh /workspace/verify_delivery.sh --path daily-screens/{date}/daily-sweep.md --branch main
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