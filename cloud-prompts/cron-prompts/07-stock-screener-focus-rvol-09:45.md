# Cloud Mavis cron: stock-screener-focus-rvol-09:45 (cron #07) — repaired 2026-10-24

You are running as a Cloud Mavis cron on Mavis. Linux sandbox: no PowerShell, no Windows paths.
Output root: /workspace/ (mkdir -p it if missing).

## CONVERSATION TITLE (do this FIRST, before anything else)

Every scheduled run gets its own conversation — one conversation per fire, never appended to an
earlier run's conversation. Give this conversation a title that says which day this run belongs
to, so the conversation list stays scannable.

1. Resolve today's date in US/Eastern: `TZ=America/New_York date +%d-%m` (day-month, no year).
2. Build the title: `[<DD-MM>] <NN>-<routine name>`. Take `<NN>` and `<routine name>` from the
   first line of this prompt (`# Cloud Mavis cron: <routine name> (cron #NN)`).
   Example: `[31-10] 12-cross-asset-correlation-snapshot`.
3. Set it with one call: `mcp_invoke` with tool_name `session_update` and arguments
   `{'session_id': 'me', 'title': '<the title>'}`. `me` means THIS conversation.
   If `mcp_invoke` reports that the tool is unknown, call `tool_search` with the query
   'session title update', then retry the same `mcp_invoke` call.
4. If the title cannot be set for any reason, carry on with the routine. This step must never
   block, delay, or fail the artifact.

## SCHEDULE
Deployed schedule: `45 9 * * 1-5` America/New_York — 09:45 ET, Mon-Fri only.
- The day-of-week field is set in the SCHEDULER, so this routine does not fire
  at all on weekends: no agent invocation is spent discovering it is a weekend,
  and no weekend SKIPPED file is written. The in-prompt weekend branch below is
  kept as a belt-and-braces guard (it costs one line) and is what still handles
  US market holidays, which no cron expression can express.
The timezone was Etc/GMT-7 (= UTC+7) on the local machine, which fired this 11h off and
after market close; it is now America/New_York, so live intraday bars exist. Do not skip a run
because you think the market is closed — check the clock.

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
   --out daily-screens --name stock_screener_focus_rvol_09_45 \
   --label "Cron #07 stock-screener-focus-rvol-09:45" \
   --nn 07 \
   --market-hours 0930-1100
```

If the script exits non-zero, the fire is OUT OF WINDOW: do not fetch the skill, do not write
an artifact, do not push. The skip marker it wrote IS the audit trail for this run.

**Reply format for an out-of-window skip.** The `## DELIVERY` block expects a push line and
an errors line; a skipped fire has neither an artifact nor an error. Reply with these lines
and nothing else - do not narrate the tool calls and do not write an artifact:

```
out-of-window: <reason printed by the script>
file: no artifact (window check declined this fire - daily-screens/$DATE.md is intentionally absent)
push: marker pushed (refs/skipped-markers/$FIRE_DATE_SKIPPED_stock_screener_focus_rvol_09_45.md) | marker push FAILED | marker push skipped (push script unavailable)
errors: 0
```


## STEP 2 — SKILL SPEC (fetch once)
curl -sS -w 'HTTP=%{http_code}\n' https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/skills/stock-screener-suite/SKILL.md -o /workspace/skill.md
**Save it under /workspace, NOT /tmp.** The Cloud `read` tool cannot open /tmp — it returns
'workspace path escapes Cloud Host root' — so a spec that lands in /tmp is unreadable and the run
stalls on a file it already has. `cat`/`sed`/`grep` on /workspace files work fine.
If that fails, retry once with -k (the GitHub cert has expired intermittently). Read the file in full
and follow the procedure with the Cloud adaptations below. If both attempts fail: write a stub
artifact with _source: skill_fetch_failed, report errors: 1, stop. Never improvise from memory.

## SHARED INSTRUCTIONS (fetch once — these rules apply to every routine)

The fleet-wide instructions live in ONE file, not in every prompt. Fetch it in the same first
step as the skill spec below, then follow it in full:

```

bash
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
  'a 429 is a rate limit, not an absence' rule.
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


## STEP 3 — SYNC UPSTREAM OUTPUTS (this was the blocking bug)
The upstream daily-sweep cron (#9, task 446554052374600) runs 18:30 ET and writes the Focus list to
the karizaco/minimax-cloud-outputs git remote. This cron sandbox does NOT share a filesystem with
it. You MUST pull before looking for the focus list:
cd /workspace
git init -q 2>/dev/null || true
git remote remove origin 2>/dev/null || true
git remote add origin https://x-access-token:${GITHUB_TOKEN}@github.com/karizaco/minimax-cloud-outputs.git 2>/dev/null || true
git config user.email maxhermes-cloud@local
git config user.name 'MaxHermes Cloud Cron'
GIT_SSL_NO_VERIFY=true git fetch -q origin main 2>&1 | head -3
git checkout origin/main -- daily-screens 2>/dev/null || true
If GITHUB_TOKEN is unset, skip the sync and record upstream: unavailable (no token). Do NOT fabricate
a focus list.

## STEP 4 — LOCATE THE FOCUS LIST
DATE=$(TZ=America/New_York date +%Y-%m-%d)
YDAY=$(TZ=America/New_York date -d yesterday +%Y-%m-%d)
for d in /workspace/daily-screens/$DATE /workspace/daily-screens/$YDAY; do
  if [ -f $d/focus.md ]; then echo FOUND $d/focus.md; fi
done
ls -1t /workspace/daily-screens/*/focus.md 2>/dev/null | head -3
Also check master.md in the same dirs for the wider universe.

**THREE DATES, THREE FIELDS — never collapse them into one.**
- `fire_date` — this fire's date, resolved from the run's `scheduled_at_ms`.
- `focus_dir_date` — the date in the folder the focus list was found in.
- `screen_data_date` — the sweep's OWN header line `Screen data_date: <date> (shibui T+1)`.
  READ IT from the focus.md header. Never infer it from the folder name, and never infer it
  from the calendar gap: cron #09 fires on WEEKDAYS ONLY, so on a Monday the newest list is
  Friday's sweep — a ONE-session lag, which is normal, not a degradation. The degradation is
  the shibui ingestion lag inside `screen_data_date`, which reached 3 sessions on 2026-11-02.
- `lag_sessions` — the number of TRADING sessions between `screen_data_date` and `fire_date`.
  Report the count. A calendar-day difference is NOT a session count.

The roster also turns over almost completely between sweeps — the 10-30 and 11-02 focus lists
shared exactly ONE name — so a stale list is not a cosmetic problem.

**If no focus.md exists ANYWHERE, do not simply fail.** Build a FALLBACK UNIVERSE from the
TradingView scanner: US stocks with `relative_volume_10d_calc` >= 1.5 and market cap > $300M,
top 12 by that column. Set `universe_source: fallback_tv_screener`, publish the snapshot, and
say in the artifact that the universe is a fallback. A degraded screen beats no screen, and most
of October's fires had no focus list at all. Only if the scanner also fails: write the artifact
with status: failed_no_upstream_focus_list, upstream: missing, list what you did find under
daily-screens/, report errors: 1, and stop. Do not push an empty snapshot as if it were a screen.

If a focus.md IS found: report its path, `focus_dir_date`, `screen_data_date` and `lag_sessions`.
If `lag_sessions` > 1, set status: degraded_stale_focus_list (see the status list in STEP 7).

**THE WIDER UNIVERSE — the focus roster alone is not the screen.** The focus roster is a
momentum screen built on the previous session's data, so it structurally cannot contain a name
whose move has not happened yet. Measured on 2026-11-09: the roster carried 1 of the day's top 10
gainers, `master.csv` 5, cron #17's boards 7, and the union **10 of 10**. The wider union is part
of the screen, and it is built from what is ALREADY ON DISK — the PREVIOUS session's `focus.csv`,
`master.csv` and cron #17's candidate CSVs. Never re-scan the market to rebuild it. The rationale
and the sources table are in SKILL.md §7; the builder is `focus_rvol_universe.py`.

**Build the union from what is ALREADY ON DISK. Do NOT re-scan the market for it.** Three
sources, all published by earlier routines for the PREVIOUS session, so they exist before this
fire:

| source | path | names | why it is there |
|---|---|---:|---|
| the focus roster | `daily-screens/<prev>/focus.csv` | 12 | cron #09's momentum picks |
| the sweep's wider candidate list | `daily-screens/<prev>/master.csv` | ~200 | every name the sweep scored |
| cron #17's movers | `us-stocks-in-play/<prev>-open-candidates.csv` and `us-stocks-in-play/<prev>-candidates.csv` | ~1,250 | the names that actually MOVED, with their catalysts |

**The previous session is the last session before `fire_date`, whatever the calendar says.** On a
Monday that is Friday; the files are named for the SESSION, not for the day before.

**RUN THE UNIVERSE BUILDER — do not hand-assemble the union.** It resolves the previous session,
globs the cron #17 boards by THAT date (a `*.csv` glob would sweep in every earlier session's
board and inflate the universe with stale names), and writes `/workspace/universe.txt` and
`/workspace/focus.txt`. It is fetched by the STEP 5 block; run it as soon as that block has
fetched the helpers:

```bash
python3 /workspace/focus_rvol_universe.py --fire-date "$DATE" \
  --screens-dir /workspace/daily-screens \
  --board-dir /workspace/us-stocks-in-play --repo /workspace
wc -l /workspace/universe.txt /workspace/focus.txt
```

Its stderr line names the previous session and the sources unioned — **copy those names into the
artifact's `wider_universe_source`**. If it reports that the cron #17 boards were MISSING, the
union is narrower than it should be: say so in the artifact, and do not claim the full coverage.
A narrower union on disk is better than a fresh scan that does not finish. Never re-scan the whole
market to rebuild this.

**The universe is a CANDIDATE SET, not the table.** The published table is the TOP of it by
`rvol_now` — publishing 1,600 rows is not a screen. STEP 5 scores the whole union; STEP 7
publishes the focus roster in full plus the top of the wider set.

## STEP 5 — RVOL PER FOCUS TICKER
Do NOT use mcp__tradingview_advanced__*, mcp__tradingview__* or mcp__yahoo_finance__*. They are
provably absent in Cloud sessions: mcode-tools connector tools returns partial=false,
provider_failures=[], with only connector__matrix__* and connector__email_workbench_credentials__*,
and tool_search returns 0 hits for every finance keyword. Do not burn turns re-testing them.

**RUN THE ENGINE. Do not hand-compute this metric per name.** The universe is ~1,600 names,
and hand-computing the metric for each is what made the 2026-11-09 fire take 66 minutes. The
engine fetches and computes in parallel and RENDERS the artifact, so a number cannot be mistyped
between the JSON and the markdown. It also owns the metric definition, the daily-volume source
and the denominator — SKILL.md §7 and the script's docstring carry the detail.

**FETCH AND RUN IT.** `focus_rvol_run.py` fetches the three helpers it needs (each behind
its own capability marker), builds the universe, scores it, and renders the artifact:

```bash
R=/workspace/focus_rvol_run.py
for V in \
  "https://api.github.com/repos/karizaco/maxhermes-migration/contents/cloud-prompts/_shared/focus_rvol_run.py?ref=main" \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/focus_rvol_run.py" \
  "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/focus_rvol_run.py" ; do
  curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" \
    -H "Authorization: Bearer ${GITHUB_TOKEN}" -o "$R.tmp" "$V" 2>/dev/null
  if [ -s "$R.tmp" ] && ! head -c 200 "$R.tmp" | grep -q '"message"' \
     && grep -q 'FOCUS_RVOL_RUN_V1' "$R.tmp" 2>/dev/null; then
    mv -f "$R.tmp" "$R"; break
  fi
  rm -f "$R.tmp"
done
[ -s "$R" ] && grep -q 'FOCUS_RVOL_RUN_V1' "$R" || echo "focus_rvol_run.py: UNAVAILABLE"

python3 "$R" --fire-date "$DATE" \
  --screens-dir /workspace/daily-screens \
  --board-dir /workspace/us-stocks-in-play --repo /workspace \
  --md-out /workspace/focus-rvol-snapshot.md \
  --csv-out /workspace/focus-rvol-snapshot.csv \
  --out /workspace/focus-rvol-scores.json
```

It prints a one-line summary to stderr. **If the stderr line reports a scanner-pull PROBLEM, the
denominator set is incomplete** — the denominator is the TradingView 10-day average daily volume,
and a pull that dropped names silently produces a wrong `daily_factor` for exactly the names it
dropped. Report it, and fall back to the focus roster only (`universe_source: focus_roster_only`)
rather than publishing a metric built on a broken pull.

**The engine renders the artifact ITSELF** (`--md-out`, `--csv-out`) — it is the only thing that
touches the numbers. Do not retype a value into the markdown by hand: a transcribed number and
the CSV will disagree, and the CSV is what the next fire reads.

It prints a one-line summary to stderr (`N/M scored | focus … | wider table …`). **If the stderr
line reports a scanner-pull PROBLEM, the denominator set is incomplete**: the denominator is the
TradingView 10-day average daily volume, and a pull that dropped names silently produces a wrong
`daily_factor` for exactly the names it dropped. Report it, and fall back to the focus roster
only (`universe_source: focus_roster_only`) rather than publishing a metric built on a broken pull.

**If the engine scores ZERO rows, that is not a screen — it is a failure.** The session has no
bars yet (pre-open, or a halt), so there is nothing to publish: write the artifact with
`status: failed_no_data`, report `errors: 1`, and push it anyway so the gap is on the record. Do
NOT fall back to a stale session's bars and present them as today's.

**If the engine fails outright**, fall back to scoring the FOCUS ROSTER ONLY (12 names — the
behaviour before 2026-11-12) and set `universe_source: focus_roster_only` in the artifact. A
narrow screen beats no screen. Never re-implement the metric by hand to work around a script
failure.

**THE DAILY-VOLUME SOURCE — Yahoo 1d bars, not the Nasdaq historical endpoint.**
The prior-10 FULL-DAY volume comes from Yahoo `interval=1d` bars. Measured over 240
symbol-sessions across 40 names, the ratio Yahoo-1d / Nasdaq-consolidated is median **1.0000**,
mean 0.9997, max deviation **0.32%**, with ZERO comparisons outside +/-1% — while the Nasdaq
call is 16x slower per symbol (2.09s vs 0.13s) and returns empty for some symbols. That ratio
is far tighter than the vendor's own intraday revision band, so it does not move a crossing
verdict: the 2026-11-10 and 2026-11-11 crossing verdicts are identical under both sources.

**SOURCE OF RECORD — one field, one source. Never mix them.**
| field | source | note |
|---|---|---|
| last price / close | Yahoo chart 5m bars, the 09:40-stamped bar | `close` = the 09:45 print |
| session volume (cumulative) | Yahoo chart 5m bars, summed to the last COMPLETED bar | Yahoo `chartPreviousClose` is a cross-check |
| 10-day average daily volume (the denominator) | TV scanner `average_volume_10d_calc` | DENOMINATOR ONLY, one pull for the whole universe |
| full-day relative volume | TV scanner `relative_volume_10d_calc` | fallback proxy only — label it `rvol_proxy_daily` |

**TRAP — the TV scanner's LIVE columns lag the session. Never use them for a live field.**
Measured 2026-11-02: TV `volume` 1,144,478 vs Yahoo 2,615,246 (ADT) and 5,806 vs 58,577 (DFIN);
TV `close` 9.87 vs bridge 9.88. Minutes-to-hours stale. TV supplies the denominator here and
nothing else.

Working path, in order:
1. Intraday RVOL (preferred, matches the skill step 7): Yahoo chart API, ONE symbol per call:
   https://query1.finance.yahoo.com/v8/finance/chart/SYMBOL?interval=5m&range=1mo
   `range=1mo` returns about 21 sessions of 5-minute bars in one response, which is what the
   time-of-day-normalised metric needs (10 prior sessions plus today). Use `range=1d` only if you
   want today's bars alone and are NOT computing `rvol_tod_normalised`.
   Yahoo does NOT accept comma-separated symbols (404) and rate-limits (429) under load:
   sleep 1s between calls, retry once on 429.
2. Fallback, daily relative volume proxy: TradingView public scanner
   POST https://scanner.tradingview.com/america/scan with verified TLS, column
   relative_volume_10d_calc. If you use this, label the metric rvol_proxy_daily in the artifact.
   It is NOT intraday RVOL and the artifact must say so.

**TWO RECIPES THAT ARE ALREADY SOLVED — do not rediscover them.**
- TradingView scanner FILTER: a filter with left=name, operation=**in** and right=[ticker,...]
  returns HTTP 400 on this endpoint (verified 2026-11-02) — the `in` operation takes ONE value.
  **But `in_range` DOES take a LIST `right`** for a categorical column, so the roster is one
  targeted call: `{"columns": ["name","exchange","average_volume_10d_calc","market_cap_basic"],
  "filter": [{"left":"name","operation":"in_range","right":["BW","FRVO",...]}],
  "range":[0, len(names)+5], "sort": {"sortBy":"name","sortOrder":"asc"}}`. Measured 2026-11-12 on
  the 12-name roster: HTTP 200, `totalCount` 12, 12 rows, **one call** — against 20,155 rows for
  the universe pull. **Assert the coverage** (every roster name present) before you use it; a name
  that never comes back is an ERROR, not a quiet drop. `tv_scan.py pull --names` does this for you
  (see the fetch block below). Only pull the full universe if you genuinely need every name.
- Yahoo IN-PROGRESS BAR: the last bar of the day is stamped with the CURRENT wall-clock time and
  its volume is still 0. Keeping it UNDERSTATES session volume. Drop every bar whose timestamp is
  later than the last COMPLETED 5-minute bar, and say in the artifact that you did.

**A THIRD RECIPE, MEASURED 2026-11-11 — the TradingView scanner's `sort` SHAPE (this one bites hard).**
The scanner is healthy; what fails is the request SHAPE. There are three `sort` forms and only one
works, so do not reach for the shape you remember from TradingView's public docs:
- `"sort": [{"column": X, "order": "asc"}]` — an ARRAY — returns **HTTP 400**
  `{"totalCount":0,"error":"json parse error","data":null}`. Even `"sort": []` 400s. **Never send
  `sort` as an array.** Omit `sort` entirely if you do not need an order.
- `"sort": {"column": X, "order": "asc"}` — an object with the WRONG keys — returns **HTTP 200 and
  silently returns UNSORTED rows**. No error, wrong data — the worst outcome of the three.
- `"sort": {"sortBy": X, "sortOrder": "asc"}` — the repo's canonical keys — returns **HTTP 200 and
  sorts correctly**. Verified on /america, /japan, /korea, /taiwan, /hongkong and /crypto.
Column names are NOT the problem: `relative_volume_10d_calc`, `market_cap_basic`,
`premarket_volume` and `exchange` all return 200 together.
Also: **`range` is a page size and the API truncates SILENTLY.** `range:[0,20000]` returned 20,000
rows while `totalCount` read 20,271 — 271 names dropped with no error.
**AND the completeness check is a SET test, not a row count (measured 2026-11-11).**
`totalCount must equal the rows returned` is NECESSARY BUT NOT SUFFICIENT: with NO sort the
scanner's default row order is **not stable between two requests**, so a two-slice universe pull
returned 20,155 rows whose UNION held only **20,001** distinct names — **154 names missing, no
error**, and the row-count check passes that pull. The real invariants are: **the pages are
DISJOINT** and **their UNION equals `totalCount`**. To page at all, sort on a STABLE key
(`{"sortBy":"name","sortOrder":"asc"}`); a sort on a live column (volume, change) is not a stable
pagination key. Verified live 2026-11-12: sorted, paged, 2 pages, union 20,356 == `totalCount`
20,356, in 1.1 s.
**AND the row key is the BARE ticker, never the venue-prefixed `s`.** A response row is
`{"s": "NYSE:BW", "d": ["BW", "NYSE", ...]}`: the ticker is **`d[0]`**, while `s` carries the venue
(`NYSE:`, `NASDAQ:`, `AMEX:`, `OTC:`). Indexing by `s` makes **every US ticker look MISSING** —
indistinguishable from an empty universe, and a silent false negative. **Index by `d[0]`, keep
`d[1]` (the exchange) separate, and assert the roster coverage before you use the pull.**
Evidence: `docs/IMPROVEMENTS-cron07-focus-rvol.md` and `cloud-prompts/_shared/RUNTIME-CONTRACT.md`
section 2a-bis in karizaco/maxhermes-migration.

**FETCH THE VALIDATED SCANNER CLIENT FIRST — a helper that is only called is not on disk.**
`_shared/tv_scan.py` (capability marker `TV_SCAN_V2`) refuses a bad request shape BEFORE it is
sent, diagnoses a failure from its error string, and its `pull` mode does the work for you:
`pull --names "A,B,C"` = the ONE targeted call plus a coverage assertion; `pull --body` = paged on
a stable sort with the disjointness and union assertions (exit 4 on either defect). It writes rows
keyed by the BARE ticker. Fetch it in STEP 1 with the ladder below; if the fetch fails, fall back
to the hand-built body above and apply the same assertions yourself.

```bash
D=/workspace/tv_scan.py
for U in \
  "https://api.github.com/repos/karizaco/maxhermes-migration/contents/cloud-prompts/_shared/tv_scan.py?ref=main" \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/tv_scan.py" \
  "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/tv_scan.py" ; do
  curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" \
    -H "Authorization: Bearer ${GITHUB_TOKEN}" -o "$D.tmp" "$U" 2>/dev/null
  if [ -s "$D.tmp" ] && ! head -c 200 "$D.tmp" | grep -q '"message"' \
     && grep -q 'TV_SCAN_V2' "$D.tmp" 2>/dev/null; then
    mv -f "$D.tmp" "$D"; break
  fi
  rm -f "$D.tmp"
done
[ -s "$D" ] || echo "tv_scan.py fetch FAILED - hand-build the body with sortBy/sortOrder and assert coverage yourself"
```

Record the data timestamp for every symbol from the payload. A symbol with no intraday bars yet gets
no_intraday_bars - never silently substitute a daily value.

**THE METRIC — publish BOTH numbers, and name them differently.**
- `rvol_intraday_live` = cumulative session volume to the last completed bar / average daily
  volume over 10 days. This is the RAW ratio. At 09:45 ET only 15 of 390 session minutes have
  elapsed, so it is mechanically ~1/26 of the meaningful value and CANNOT reach 3 before the
  lunch bell for any name. Publish it for reference; NEVER bucket on it.
- `rvol_tod_normalised` = THE metric. How hot is this name right now versus its OWN 10-session
  norm for this same clock window:
  rvol_tod_normalised = (cumulative volume 09:30 -> the fire's bar, today)
                         / (mean cumulative volume over 09:30 -> the SAME clock window across the
                            prior 10 sessions)
                         x (mean full-day volume across those prior 10 sessions
                            / TV average_volume_10d_calc)
  The last factor puts the number in the same units as #09's completed-session relative volume,
  so the two are directly comparable. 1.0 = a normal morning for that name.
  One Yahoo call per symbol gives all of it: `interval=5m&range=1mo` returns about 21 sessions
  of bars in one response. If fewer than 10 prior sessions are present, re-fetch with
  `range=3mo` (Yahoo serves 5m history for 60 days). Sum each prior session's bars over the SAME
  09:30 -> fire-time window you used for today, not over its whole day.
- WHY NOT TIME-SCALED: dividing by elapsed TIME assumes volume accrues evenly across the session.
  It does not. Measured on 2026-11-02 and 2026-11-03, the first 15 minutes carried a MEDIAN 8.2%
  of the day's volume (5.7% to 18.1% across names) against 3.8% for time-even accrual, so a
  time-scaled projection over-states the session by roughly 2x. Across those two sessions it
  flagged 6 names and 4 of them ended the day BELOW a normal relative volume. The
  time-of-day-normalised metric had less than half the error (MAE 0.381 and 0.474 against 1.112
  and 1.199 for the time-scaled form).
- NAME CLASH: cron #09's `focus.csv` already publishes `rvol_<date>` = the COMPLETED session's
  relative volume. That is a different quantity from either number above. Refer to it as
  `rvol_session_eod` when you compare them.

**THE EARLIER CROSS-CHECK SNAPSHOT — you need a SECOND reading of the same window.**
One snapshot cannot show a trend, and a trend is the signal: a name whose pace is FALLING is a
different trade from one whose pace is RISING. So take TWO readings of the same metric per
ticker:
1. the FIRE'S SNAPSHOT — the last COMPLETED bar at the fire time, and
2. an EARLIER CROSS-CHECK SNAPSHOT — an independent reading at least 5 minutes before it.

Preferred source for the earlier reading: the CBOE delayed-quote CDN
(`cdn.cboe.com/api/global/delayed_quotes/quotes/{SYM}.json`), whose `volume` is regular-session
only and whose snapshot trails the live tape by ~15 minutes (at a 09:45 fire it reads ~09:38).
Use CBOE's OWN timestamp to define the earlier window — do not assume 09:38.
Fallback when CBOE is unreachable, or its snapshot is not earlier than the fire's: truncate the
SAME 5-minute bar series at the bar stamped 5 or more minutes before the fire's bar, and record
`cross_check_source: same_series_truncated` in the method.

Compute `rvol_prev` with the SAME formula as `rvol_now`, over the EARLIER window — the prior-10
mean for THAT window, not today's window. Compute `rvol_at_09_38` as the RAW cumulative ratio at
the earlier snapshot: (cumulative session volume at that snapshot) / (TV average_volume_10d_calc).
Publish it so the reader can CHECK the normalisation instead of trusting it.

**PRE-MARKET VOLUME — the subtraction must be auditable, and it depends on cron #08.**
Session volume MUST exclude pre-market prints. There are two ways to get that, and the artifact
must say which one was used:
- **The source excludes pre-market by construction** — Yahoo bars with `includePrePost=false`
  (regular session only). Then `pm_vol_source: not_subtracted` and `pm_vol: 0`. This is the
  PREFERRED route: it needs no cross-routine dependency at all.
- **The source includes pre-market** — a cumulative quote-volume feed (the bridge
  `market-recap get_quotes`). Then READ cron #08's published
  `daily-screens/<date>/pre-market-gapper.csv` and SUBTRACT its `pm_volume` per ticker.
  `pm_vol_source: subtracted_from_08`, and publish the subtracted volume per row so the
  arithmetic is checkable.

**When cron #08's file is missing, the subtraction silently does NOT happen — so say so.**
If the session-volume source includes pre-market AND #08's file is absent:
- set `pm_vol_source: no_08_file` on every affected row,
- mark those rows' `tier` `UNADJUSTED` — do NOT publish a number that looks adjusted,
- say it in the artifact (front matter `pm_source_status`, plus a line under Degradation) AND in
  the reply's `pm:` token.
`not_subtracted` is only honest when the source excludes pre-market by construction; state which
in the method. A row whose RVOL is UNADJUSTED is not a Required name and not an alert — it is an
unknown.

## STEP 6 — CONSTANTS, TREND, NEAR MISS AND ALERT

**THE CONSTANTS — define them ONCE, here, and use these values everywhere.** Every threshold
below is a NAMED CONSTANT. Publish both thresholds in the artifact's front matter, use the same
values in the reply, and never mix one for the other.

| constant | value | meaning |
|---|---:|---|
| `RVOL_REQUIRED_BUCKET` | **1.5** | the threshold that qualifies a name for the RVOL Required bucket |
| `RVOL_ALERT_THRESHOLD` | **1.5** | the threshold that triggers an alert line |
| `NEAR_MISS_FLOOR` | **1.275** | `RVOL_ALERT_THRESHOLD x 0.85` — the floor of the near-miss band |

`RVOL_REQUIRED_BUCKET` and `RVOL_ALERT_THRESHOLD` are currently EQUAL on purpose: the alert is
a name CROSSING UP through the bucket bar, not a name sitting above a second, higher bar. They
stay two constants so that a future "alert only above 2.0" change is ONE edit in THIS block
instead of a hunt through the artifact template, the reply format and the skill spec.
`rvol_tod_normalised` = 1.0 is that name's own normal morning, so 1.5 means 50% hotter than its
own 10-session norm at the same hour.

**THE ALERT RULE, in one sentence — state it this way in the artifact:**
> An alert fires for a name whose `rvol_now` is at or above `RVOL_ALERT_THRESHOLD` (1.5) AND
> whose `prev_session_rvol` is below `RVOL_ALERT_THRESHOLD` (1.5) — that is, the name crossed
> UP through the alert bar since the previous session's reading of the same metric.

`rvol_now >= RVOL_ALERT_THRESHOLD` on its own is a LEVEL, not an alert. A level with no prior
reading below the bar is not a crossing, and a crossing claimed without a prior reading is a
fabrication, not a signal. Name every crossing ticker in the chat — that is the one alert this
routine owes. **A prior reading that was never COMPUTED is not a prior reading** — so compute it
(STEP 6) rather than publishing `n/a` and silencing the tier.

**THE NEAR-MISS TIER — the tradable edge.**
A name is a **NEAR MISS** when `rvol_now >= NEAR_MISS_FLOOR` (1.275) and `rvol_now <
RVOL_ALERT_THRESHOLD` (1.5). Publish every near miss with BOTH its current value and its prior
value, and say what would turn it into an alert: `rvol_now` reaching 1.5 while `prev_session_rvol`
stays below 1.5. A near miss is the difference between a routine that reports what happened and
one that tells you what to watch.

**THE TREND — publish it, do not bury it in prose.**
For every name publish FOUR numbers, not one:
- `rvol_now` — the metric at the fire's snapshot.
- `rvol_prev` — the SAME metric at the EARLIER CROSS-CHECK SNAPSHOT (see STEP 5).
- `rvol_at_09_38` — the RAW (un-adjusted) cumulative ratio at that earlier snapshot, so the
  reader can verify the trend instead of trusting it.
- `rvol_trend` — `ACCELERATING` / `STABLE` / `DECELERATING`, plus the numeric delta
  (`rvol_now` - `rvol_prev`).

`rvol_trend` is a SORT KEY and a VISIBLE COLUMN, not a footnote. A name whose RVOL decays from
14.4x to 6.9x is a distribution, not an accumulation, and the reader must see that in the table
rather than read it out of a paragraph.
**SORT ORDER:** primary `rvol_now` desc; secondary `rvol_trend` (ACCELERATING first, then
STABLE, then DECELERATING) so that when two names print the same `rvol_now` the one that is
climbing leads. The `## Alerts` list is ordered by trend delta desc — among flagged names the
TREND is what decides the trade.

**A CROSSING NEEDS A PRIOR READING — and both sides must be on the SAME SCALE.**
A ticker CROSSED when `prev_session_rvol < RVOL_ALERT_THRESHOLD` and `rvol_now >=
RVOL_ALERT_THRESHOLD`.
The prior reading is the SAME metric for the PREVIOUS SESSION, computed the SAME way on the SAME
source, **with the SAME TradingView denominator as today's reading.**

**ALWAYS RECOMPUTE THE PRIOR READING. Never take it from the previous session's published CSV.**
The denominator is `TV average_volume_10d_calc`, a ROLLING average that moves between fetches, so
a published value is on THAT day's scale — and the drift FLIPS VERDICTS: a name whose prior sits
close to the bar flips on a tiny move (measured: LASR, prior 1.497, flips on a 0.2% denominator
move, while FROG, prior 0.921, holds through 38.6%). So the prior reading is recomputed with the
CURRENT run's denominator, and both sides of every crossing are then the same metric on one scale.
The published value is published alongside as `prev_session_rvol_published` plus
`denominator_drift_pct` — a CROSS-CHECK, never the baseline. SKILL.md §7 has the measurement.

**DO NOT publish `n/a` merely because the previous CSV lacks the ticker.** A missing ticker is a
MISSING ROSTER, not a missing prior reading — the tape was there, the routine simply never
measured that name on that day. Writing `n/a` because the roster rotated converts a computable
number into an absent one, and an absent prior reading silently disarms the alert tier: a name
sitting at 2.7x becomes a WATCH instead of an ALERT. **That is what killed this routine's alert
tier for five consecutive sessions (2026-11-05 through 2026-11-11): every one of them published
`alerts: none` while the tape was hot — 2026-11-10 alone had SEVEN names above the 1.5x bar and
not one could be shown to be a crossing.** Recompute instead. The roster rotates; the source does
not.

**Only publish `prev_session_rvol: n/a` when the recompute is genuinely impossible** — the symbol
has no previous-session bars in the fetched series, or fewer than 10 usable prior sessions for the
baseline. In that case set `prev_session_rvol_source: unavailable`, say so in the artifact, and
emit no alert for that ticker.

**Publish the provenance.** Every row carries `prev_session_rvol_source` —
`recomputed_same_feed` / `unavailable` — plus `prev_session_rvol_published` and
`denominator_drift_pct` where the previous CSV carried the ticker. The artifact's `## Alerts`
section states how many prior readings were recomputed and how many were unavailable. A reader
must be able to tell a recomputed prior reading from a published one without re-deriving it.

**THE CSV IS NOT OPTIONAL.** A run that publishes only the `.md` breaks the NEXT fire's published
cross-check: that is exactly what happened on 2026-11-03 (the `.md` shipped, the `.csv` did not).
Write BOTH files every time, and confirm the CSV exists before you push.

An empty bucket is a real result. Report it as an empty bucket with counts, not as a failure.

## STEP 7 — WRITE THE ARTIFACT
Write TWO files in /workspace/daily-screens/DATE/ (create the dir; DATE = today ET):
  focus-rvol-snapshot.md
  focus-rvol-snapshot.csv      <- one row per ticker, machine-readable. REQUIRED, not optional.

**THE SKELETON — follow this order exactly. A fixed skeleton is what makes two artifacts
comparable.**
1. Front matter (exact keys, in this order).
2. Title.
3. `## TL;DR` — 3-6 lines: how many names cleared, how many are near misses, the alert names,
   and THE CAVEAT THAT CHANGES HOW THEY SHOULD BE READ. The TL;DR is what a human actually
   reads; a caveat that only exists down in Degradation does not exist.
4. `## Universe` — where the focus list came from, the three dates, the lag, AND the wider
   universe: which on-disk sources were unioned, how many names they held, and how many were
   scored.
5. `## Focus table` — the focus roster, in full, every row.
6. `## Wider universe` — the top of the wider set by `rvol_now` (the engine's `wider_rows`).
7. `### Counts`.
8. `## Alerts` — the crossing names, each with a one-line `read`.
9. `## Near misses` — the watch list, with current and prior values.
10. `## Universe change` — names that entered or left the focus list vs the previous sweep.
11. `## Method` — the method actually used.
12. `## Source health`.
13. `## Degradation / caveats`.

**TWO TABLES — the focus roster, and the wider universe that carries the day's movers.** Publish
`## Focus table` (every focus-roster name, in full) AND `## Wider universe` (the engine's
`wider_rows` — the wider union's top names by `rvol_now`, 25 by default). A name in the focus
roster is NOT repeated in the wider table. SKILL.md §7 has why both are required.

**Each name appears ONCE within its table, with ALL of its numbers in that row.**
No second table for volume, no third table for the cross-check: the cross-check values ARE
columns (`rvol_prev`, `rvol_at_09_38`) and the volume detail IS columns. A reader must never
have to join two tables to learn one name's story. A name in the focus roster is NOT repeated in
the wider table.

Columns, in this order:
`symbol | close | rvol_intraday_live | rvol_now | rvol_prev | rvol_at_09_38 | rvol_trend |
prev_session_rvol | prev_session_rvol_source | prev_session_rvol_published |
denominator_drift_pct | bucket | tier | pm_vol | pm_vol_source | data timestamp`

- `rvol_intraday_live` — the RAW ratio (cumulative session volume / TV average_volume_10d_calc).
  It is mechanically tiny at 09:45 and is published for reference; NEVER bucket on it.
- `rvol_now` — the metric at the fire's snapshot.
- `rvol_prev` — the metric at the earlier cross-check snapshot.
- `rvol_at_09_38` — the RAW cumulative ratio at that earlier snapshot, so the trend is checkable.
- `rvol_trend` — `ACCELERATING` / `STABLE` / `DECELERATING` with the numeric delta.
- `prev_session_rvol` — the previous session's reading for this ticker, RECOMPUTED on the same
  feed with the same denominator as today's (see STEP 6), or `n/a` only when the recompute is
  genuinely impossible.
- `prev_session_rvol_source` — `recomputed_same_feed` / `unavailable`.
- `prev_session_rvol_published` — the previous session's PUBLISHED `rvol_now` for this ticker,
  where the previous CSV carried it; `n/a` otherwise. A CROSS-CHECK, never the baseline.
- `denominator_drift_pct` — how far the TV denominator moved between the previous session's pull
  and this one, where both are known. `n/a` otherwise.
- `bucket` — `RVOL Required` / `Liquid`, by `RVOL_REQUIRED_BUCKET`.
- `tier` — `ALERT` / `NEAR MISS` / `WATCH` / `UNADJUSTED` / `-`.
- `pm_vol` — the pre-market volume subtracted (0 when none was subtracted).
- `pm_vol_source` — `subtracted_from_08` / `no_08_file` / `not_subtracted`.
- `data timestamp` — when the volume/close reading was taken.

The CSV carries the SAME columns as the tables, one row per ticker, with a `universe` column
(`focus` / `wider`), plus the upstream `stylists` and `flags` columns when the focus list provided
them. Write the CSV even when the tables are empty or degraded — a missing CSV is what starves
the next fire's published cross-check.

Front-matter, exact keys in this order:
  date, cron, fire_time_et, fire_date, focus_dir_date, screen_data_date, lag_sessions,
  universe_source, universe_size, wider_universe_source, wider_universe_size, wider_shown,
  elapsed_minutes, session_fraction, source, method,
  metric_def, bucket_rule, rvol_required_bucket, rvol_alert_threshold, near_miss_floor,
  alert_rule, pm_source_status, cross_check_source, status, upstream, names_unpriced
`lag_sessions`, `elapsed_minutes`, `session_fraction`, `universe_size`, `wider_universe_size`,
`wider_shown`, `names_unpriced`,
`rvol_required_bucket`, `rvol_alert_threshold` and `near_miss_floor` are NUMBERS, not strings.
`universe_source` is `focus_plus_wider` / `focus_roster_only` / `fallback_tv_screener`.
`wider_universe_source` names the on-disk sources unioned (e.g. `focus+master+17`), or `none`.
`upstream` is the focus.md path, or `missing` / `fallback_tv_screener`.
`alert_rule` is the one-sentence rule from STEP 6, with the same numbers.
`pm_source_status` is `subtracted_from_08` / `no_08_file` / `not_subtracted` / `partial`.
`cross_check_source` is `cboe_delayed` / `same_series_truncated` / `none`.

`### Counts` must state: universe size, Required count, Liquid count, NEAR MISS count, alert
count, crossings, and the number of UNADJUSTED rows.
`## Alerts` names the crossing tickers (or writes 'none' and says why), and gives each flagged
name a ONE-LINE `read` that says what the number means — for example
`RVOL fading 14.4x -> 6.9x — distribution, not accumulation`. A name whose RVOL is decaying is
a different trade from one whose RVOL is climbing, and today only prose says so.
`## Near misses` names every near miss with its current and prior values and what would trigger
it.

status must be exactly one of: ok, degraded_stale_focus_list, degraded_daily_rvol_proxy,
degraded_universe_fallback, degraded_pm_unadjusted, failed_no_upstream_focus_list,
failed_no_data.


The `{date}` placeholder is the fire's **scheduled** date in US/Eastern, `YYYY-MM-DD`. Resolve it
from the run's `scheduled_at_ms` (`cron_read view:runs` → `run.scheduled_at_ms`), not from `date`
at execution time. If they differ, this is a **delayed replay**: rebuild for the scheduled date,
do NOT write a SKIPPED marker, and say in the artifact that it is a reconstruction produced late.
A replay is normal, not an error.

## GIT PUSH (OPTIONAL)

```bash
B=https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared
for U in $B/push_artifact.sh 'https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/push_artifact.sh'; do
  [ -s /workspace/push_artifact.sh ] || curl -sL -o /workspace/push_artifact.sh $U
done
sh /workspace/push_artifact.sh --out daily-screens \
  --add daily-screens/{date}/focus-rvol-snapshot.md \
  --add daily-screens/{date}/focus-rvol-snapshot.csv --branch main
sh /workspace/verify_delivery.sh --path daily-screens/{date}/focus-rvol-snapshot.md --branch main
sh /workspace/verify_delivery.sh --path daily-screens/{date}/focus-rvol-snapshot.csv --branch main
```

**If the push script cannot be fetched**, use the inline fallback in
`cloud-prompts/_shared/push_artifact.sh` — but never `git add -A`, and never
`git push … | head -3` (that returns head's exit status and reports a rejected push as success).

## DELIVERY VERIFICATION (MANDATORY - do this after the push block)

The push above already verifies its own delivery: `push_artifact.sh` calls `verify_delivery.sh`
and only reports `push: ok` when the path is present on the remote branch.
Run it again if you need to re-check:

```bash
sh /workspace/verify_delivery.sh --path daily-screens/{date}/focus-rvol-snapshot.md --branch main
```

A `git push` that exits 0 is **not** proof of delivery — a push piped into `head` returns head's
exit status (always 0) and reports a rejected push as a success. That is why the delivery check
exists, and why the push script must never be run with `git push … | head -3`.

## DELIVERY (the only thing delivered to the chat)
Eight lines, no preamble. **This format is a DOCUMENTED EXCEPTION** (see
`cron-prompts/README.md`): a fixed status line, machine-read rather than read by a human. Do NOT
convert it to the standard prose / `### Signal` format.

focus-rvol-09:45 (cron #07) - DATE TIME_ET
window: passed | skipped (reason)
upstream: FOCUS_MD_PATH (lag N session(s)) | missing | fallback_tv_screener
tickers: N | RVOL Required: N (>= 1.5x) | Liquid: N | NEAR MISS: N (>= 1.275x) | method: METHOD | pm: PM_SOURCE
universe: focus N + wider N (source SOURCE) | focus only (engine failed)
alerts: NAME (TREND), NAME (TREND) | none (no prior reading)
file: PATH (BYTES B, written) | no artifact
push: ok | skipped (token unset) | failed (reason)
errors: N

The `alerts:` line names EVERY crossing from BOTH tables — the focus roster's crossings first,
then the wider universe's. The `universe:` line states how many names the wider union held and
which on-disk sources were unioned, so a reader can tell a narrow screen from a wide one.