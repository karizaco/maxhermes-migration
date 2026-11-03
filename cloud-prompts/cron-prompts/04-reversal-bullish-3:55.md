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

**The signal bar is TODAY's candle, not yesterday's settled bar.** This routine fires at 15:55 ET,
when the US session is ~99% complete, so today's open/high/low/close are live and readable NOW.
Bonde's process is a SAME-DAY scan - *"run the scan between 3.30 and 3.55 PM"*, *"enter between
3.58 to 4PM or using Market On Close order (MOC)"* - so the signal bar is today's candle and the
entry is today's close.

**Do NOT resolve the screen date as "shibui's latest settled date".** shibui is end-of-day, so at
15:55 ET its newest bar is YESTERDAY's. A shibui-only scan measures the previous session's candle
and points at an entry one session after the signal - and the D-day bar can invalidate the setup
before the entry ever happens. That one-session lag is a migration artifact, not the playbook:
the 2026-10-30 run measured Thursday's candle on a Friday and reported DOCU, whose Friday candle
was a weak close (DCR 0.24). **A screen that reports yesterday's candle as today's signal is
WRONG, however well-formed its output looks.**

Every run must PROVE which session it is looking at, before computing anything:

```
implied_previous_close = live_close / (1 + change_pct / 100)
```

must equal the latest settled close the history source holds for the same symbol. If it does, the
scanner is on today's live session. If instead the scanner's `close` equals the latest settled
close, there is NO session to scan (weekend / holiday / pre-open). Anything else is a degraded run
that must not be traded. Anchor the check to the session SEQUENCE, never to calendar arithmetic.

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
          sh "$S" --out daily-screens --name reversal_bullish_3_55 \
             --label "Cron #04 reversal-bullish-3:55" \
             --reason "US market holiday ($DATE)" \
             --nn 04 --date "$DATE" || \
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
file: no artifact (holiday skip — daily-screens/$DATE.md is intentionally absent)
push: marker pushed (refs/skipped-markers/$DATE_SKIPPED_reversal_bullish_3_55.md) | marker push FAILED | marker push skipped (push script unavailable)
errors: 0
```

## SKILL SPEC (FETCH ONCE)
The skill's procedure body lives here:
  https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/skills/stock-screener-suite/SKILL.md

**FIRST tool call:** `curl -s https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/skills/stock-screener-suite/SKILL.md` (or `web_fetch` if available). Read the procedure in full. Do NOT skip this step.
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

The **stop** is the body low, except on a near-doji body (under 15% of the range) where the signal
bar's **low** is used — a body-low stop on a doji sits inside the bar's own noise (0.07% wide on
the 2026-10-26 CBRE bar) and produces false exits. The 2.5% maximum-loss cap is enforced either way.

## LIVE SESSION SCAN + HOW TO RUN IT

The screen is implemented as a **cloud-native script in the repo**, and it MUST be executed rather
than re-implemented by hand - it carries the day-alignment assertion and all twelve gates, and a
hand-rolled version of it is what produced the wrong-day bug in the first place:

```bash
mkdir -p /workspace/tools
curl -sL -o /workspace/tools/reversal_bullish.py \
  https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/tools/reversal_bullish.py
wc -c /workspace/tools/reversal_bullish.py          # must be non-zero

# pass the fire's SCHEDULED date (see the OUTPUT section below)
python3 /workspace/tools/reversal_bullish.py --date "$(TZ=America/New_York date +%F)"
```

It writes `reversal-bullish-3:55.{md,csv}` into `/workspace/daily-screens/{date}/` and prints a
JSON report. **Read that report** - `mode` is `LIVE`, `NO_SESSION`, `DEGRADED` or
`SETTLED_REPLAY`; `passing` is the candidate count; `history_source` says whether history came
from shibui or the Nasdaq fallback. Exit code 3 means "no US session today", which is a clean
outcome, not a failure.

This is the same pattern cron #91 uses with `tools/schedule-drift.py`. The legacy Windows helpers
under `scripts/` still do not exist on Cloud and must not be executed - this is the one exception.

**Where the data comes from** (the live path needs all three):

| Role | Source |
|---|---|
| Live session OHLC for the whole universe + the universe gates | TradingView public scanner, `POST https://scanner.tradingview.com/america/scan`, columns `name, description, close, open, high, low, change, change_abs, volume, average_volume_10d_calc, market_cap_basic, exchange, type, sector` |
| Settled history (5-day low, ADR, prior closes, average volume) | shibui over the MCP-over-HTTP bridge - one `stock_data_query` per 6 tickers, `QUALIFY ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) <= 30` |
| History fallback | Nasdaq `GET https://api.nasdaq.com/api/quote/{SYM}/historical?assetclass=stocks&fromdate=…&todate=…&limit=40` (browser `User-Agent`; some cells are the string `N/A`) |
| Entry quote / session state | `market-recap get_quotes` - `price, day_high, day_low, as_of, market_state` |

**TradingView paging trap - measured 2026-11-03:** `range` paging WITHOUT an explicit `sort`
returns OVERLAPPING pages - 1500 rows fetched but only 1212 unique, silently losing 288 names.
Always send `"sort": {"sortBy": "name", "sortOrder": "asc"}`, fetch the whole filtered universe in
ONE call with `range: [0, 2000]`, and de-duplicate by ticker. The filter key is **`filter`**, not
`filters`. `type == "stock"` INCLUDES REITs - do not re-filter to common stock.

**shibui's `tools/call` endpoint is NOT always up** - measured 2026-11-03, `tools/list` answered
while every `tools/call` returned an empty body. The Nasdaq history fallback is not optional.

**This routine's reply must state the session-alignment verdict.** In the shared DELIVERY
structure, item 3 (`### Method & caveats`) must carry the verdict - `LIVE`, `NO_SESSION`,
`DEGRADED` or `SETTLED_REPLAY` - and say that the signal is TODAY's live candle. The shared
`## DELIVERY` block in PROMPT-BLOCKS.md is fleet-wide and is NOT edited by this routine.

**The Finviz fallback cannot serve this scan.** `finviz_reversal_bullish` encodes "today down +
above SMA50 + liquid + large-cap" and none of Bonde's candle gates, and it returns no candle
geometry. If the live path is unavailable, report the run as degraded - do not publish a Finviz
list as today's signal.

Then do the two things the screen cannot do:

- **Reduce to 1-3 ideas** the way Bonde does - "the reversal bar has to jump off the chart",
  "no catalyst, no trade". A floor-exact DCR or a stop-distance tie-breaker is **not** a reason to
  promote a name. Every candidate in the chat reply needs a named catalyst.
- **On a delayed replay only** (the scheduled date is not today), resolve each candidate against
  that session's close and report a *noise breach* (a close a few cents below a doji body stop)
  separately from a *structural failure* (the session undercut the signal bar's low). Never report
  both as "stop hit".


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
  `/workspace/daily-screens/{date}/reversal-bullish-3:55.md`
  `/workspace/daily-screens/{date}/reversal-bullish-3:55.csv`

The `{date}` placeholder is the fire's **scheduled** date in US/Eastern, `YYYY-MM-DD`. Resolve it
from the run's `scheduled_at_ms` (`cron_read view=runs` → `run.scheduled_at_ms`), not from `date`
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
sh /workspace/push_artifact.sh --out daily-screens --add daily-screens/{date}/reversal-bullish-3:55.md --branch main
sh /workspace/verify_delivery.sh --path daily-screens/{date}/reversal-bullish-3:55.md --branch main
```

**If the push script cannot be fetched**, use the inline fallback in
`cloud-prompts/_shared/push_artifact.sh` — but never `git add -A`, and never
`git push … | head -3` (that returns head's exit status and reports a rejected push as success).

## DELIVERY VERIFICATION (MANDATORY - do this after the push block)

The push above already verifies its own delivery: `push_artifact.sh` calls `verify_delivery.sh`
and only reports `push: ok` when the path is present on the remote branch.
Run it again if you need to re-check:

```bash
sh /workspace/verify_delivery.sh --path daily-screens/{date}/reversal-bullish-3:55.md --branch main
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