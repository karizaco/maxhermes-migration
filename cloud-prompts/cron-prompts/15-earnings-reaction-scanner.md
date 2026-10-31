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

## STEP 1 — WINDOW CHECK (run this first, before anything else)

```bash
WEEKDAYS_ONLY=true
WEEKEND_ONLY=false
MARKET_HOURS_ONLY=false
DAY_OF_WEEK=0   # 1=Mon ... 7=Sun; 0=no constraint
# This cron is a PRE-MARKET scan (08:00 ET), so it must NOT be gated on
# market hours. It IS gated on weekdays: there is no US session to react to.

NOW_ET=$(TZ=America/New_York date '+%Y-%m-%d %H:%M %u')
DOW=$(TZ=America/New_York date +%u)
HOUR=$(TZ=America/New_York date +%H)
SKIP_REASON=
if [ "$WEEKDAYS_ONLY" = "true" ] && [ "$DOW" -ge 6 ]; then
  SKIP_REASON="weekend (day=$DOW, expected Mon-Fri)"
fi
if [ "$HOUR" -ne 8 ]; then
  SKIP_REASON="off-schedule hour (hour=$HOUR ET, expected 08)"
fi
if [ -n "$SKIP_REASON" ]; then
  DATE=$(TZ=America/New_York date +%Y-%m-%d)
  mkdir -p /workspace/$DATE
  printf '# Cron #15 earnings-reaction-scanner - SKIPPED\n- Date (ET): %s\n- Time (ET): %s\n- Reason: %s\n' \
    "$DATE" "$(TZ=America/New_York date +%H:%M)" "$SKIP_REASON" \
    > /workspace/$DATE/SKIPPED_earnings_reaction_scanner.md
  echo "out-of-window: $SKIP_REASON"
  echo "no artifact; no push"
  exit 0
fi
echo "window-check: OK ($NOW_ET)"
```

If this exits with "out-of-window: <reason>", the run is DONE. Do not fetch the skill, do not
call APIs, do not write any other artifact, do not push. The `SKIPPED_*.md` file IS the artifact.

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

## RUNTIME DATA-SOURCE CONTRACT (read before fetching any data)

**The `mcp__*` tools named above DO NOT EXIST in this runtime.** They are listed for provenance
only. Verified 2026-10-28, **re-verified 2026-10-31**: the connector catalog exposes **133 tools** —
118 `connector__github__*` (a built-in GitHub connector, authorized as `karizaco`), 13
`connector__matrix__*` (media) and 2 `connector__email_workbench_credentials__*`. There is
still **no** `mcp__yahoo_finance__*`, `mcp__tradingview__*`, `mcp__shibui_finance__*`,
`mcp__stocktwits__*`, `mcp__financekit__*` or `mcp__web_search__*`, and no
`extract_content_from_websites`.
**Do not attempt an MCP call and do not wait for one to appear** — a tool-not-found error
converts into an early abort with no artifact, via the zero-fallback policy.

Use instead: `web_search` (search; returns page content), `web_fetch` (fetch a URL, incl. a raw
JSON endpoint), `bash` (curl, python3), and `connector__github__*` for repo writes. `web_search`
uses a DIFFERENT egress than curl, so it survives when curl is blocked.

**Measured 2026-10-31 from this sandbox — Yahoo's JSON endpoints are working again** (chart,
screener, quoteSummary and options all 200; they were 429 on 2026-10-28 and worked on every run
from 10-13 to 10-23). The earlier "persistent 429" was an egress-side condition that has
cleared. **Do not hard-code a Yahoo-avoidance path** — try the ladder in cost order and fall
through on a real failure.

Ladder for bulk data: bridge `market-recap` → Yahoo JSON → (on 429) Nasdaq API
`https://api.nasdaq.com/api/quote/{SYM}/info?assetclass=etf` → Yahoo HTML
`https://finance.yahoo.com/quote/{SYM}/` → `web_search` per symbol. Also confirmed working:
TradingView scanner `POST https://scanner.tradingview.com/america/scan` (movers, RVol, `halted`,
premarket), Nasdaq market movers `https://api.nasdaq.com/api/marketmovers?market=stocks`, SEC
EDGAR full-text + per-company 8-K Atom (needs a User-Agent header), CoinGecko (crypto),
Frankfurter (FX), US Treasury daily yield-curve CSV, and **Barchart via headless chromium**
(`_shared/barchart_fetch.py`). Stooq CSV is blocked (404).
Full endpoint list + measured status: `https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/RUNTIME-CONTRACT.md`

### MCP AVAILABILITY PROBE (non-blocking, one cheap call)

Run `python3 /workspace/probe_mcp.py` at the start of the run (fetch it from
`cloud-prompts/_shared/probe_mcp.py` if missing) and record the result in this run's
`## Source health`. It prints exactly one of three states:

- `catalog_ok total=N finance_tools=0` — catalog healthy, no financial MCP registered yet.
- `catalog_ok total=N finance_tools=K` — **a financial MCP has LANDED. Switch to it this run.**
- `catalog_unreachable` — the probe itself failed. This is **NOT** evidence that no MCPs exist.

The weekly `mcp-health/` routine does the same probe on a slower cadence; this in-run probe is
the fast path.

### PRIMARY SOURCE: the MCP-over-HTTP bridge (use this FIRST)

The `mcp__*` tool names above are NOT registered here, but the MCP SERVERS are reachable
over plain HTTPS JSON-RPC from the sandbox. A ready-made bridge is published with the set:

  https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/mcp_bridge.py

```bash
BR=/workspace/mcp_bridge.py
for U in \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/mcp_bridge.py" \
  "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/mcp_bridge.py" \
  "https://api.github.com/repos/karizaco/maxhermes-migration/contents/cloud-prompts/_shared/mcp_bridge.py?ref=main" ; do
  [ -s "$BR" ] || curl -sL -H "Accept: application/vnd.github.raw" -o "$BR" "$U" 2>/dev/null
done
[ -s "$BR" ] || echo "bridge fetch FAILED - fall back to web_search, then the curl ladder"
mkdir -p /workspace/_mcp && cd /workspace/_mcp
printf '%s' '{"symbol":"SPY","period":"1m"}' > a.json
python3 /workspace/mcp_bridge.py stocktwits chart_data a.json      # OHLCV, sentiment, trending
printf '%s' "SELECT ticker, strftime(date, '%Y-%m-%d') AS d, close, volume FROM shibui.stock_quotes WHERE ticker = 'SPY' ORDER BY date DESC LIMIT 3" > q.txt
printf '%s' "SELECT ticker, close FROM shibui.stock_quotes WHERE ticker = 'SPY' ORDER BY date DESC LIMIT 3" > q.txt
python3 -c "import json,sys;print(json.dumps({'query':open('q.txt').read(),'user_prompt':'latest SPY close'}))" > b.json
python3 /workspace/mcp_bridge.py shibui stock_data_query b.json   # history to 1962, fundamentals, screeners, EDGAR

# --- market-recap: the primary quote + movers source (verified 2026-10-31) ---
printf '%s' '{"symbols":"SPY,QQQ,IWM,DIA,XLK,XLF,SMH,XBI"}' > c.json
python3 /workspace/mcp_bridge.py market-recap get_quotes c.json  # price, previous_close, change_pct, volume, day_high/low, as_of, market_state
printf '%s' '{}' > d.json
python3 /workspace/mcp_bridge.py market-recap top_movers d.json  # ranked gainers/losers/most-active
python3 /workspace/mcp_bridge.py market-recap market_snapshot d.json # indices, yields, FX, futures
python3 /workspace/mcp_bridge.py --list-packs                   # enumerate available packs

# --- Barchart (AWS-WAF blocked for plain curl; works via headless chromium) ---
curl -s -o /workspace/barchart_fetch.py \
  https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/barchart_fetch.py
python3 /workspace/barchart_fetch.py --symbols SPY,QQQ,AAPL    # batch quotes
python3 /workspace/barchart_fetch.py --list top-gainers --limit 20
```

**Verified 2026-10-28:** both servers answer, 6/6 identical values over 6 calls (median 204 ms),
returning the same close web_search gave (SPY 769.66, 2026-10-27) while Yahoo JSON was 429.
Fetch the bridge with the 3-URL ladder above - a freshly pushed file can 404 on the raw CDN
for a few minutes. The bridge returns `{"error": ...}` and a non-zero exit on failure, so a
failed call can never be mistaken for data. **Pass tool args as a FILE, not inline** - shell
quoting corrupts the JSON. Server/tool reference: the RUNTIME-CONTRACT.md URL above.

**Order of attack: MCP bridge -> `web_search` -> curl ladder.** The bridge is the richest
source and is not rate-limited, so try it before Yahoo. If it fails, fall through.

### Rules

1. **A 429/403 is a RATE LIMIT, not a missing symbol.** Never report "no data" for a symbol you
   never successfully queried. Retry once after a short sleep, then fall through the ladder.
2. **Sanity-check the RESPONSE BODY, not just the HTTP status.** The proxy can return HTTP 200
   carrying a plain-text error page. Confirm the body parses as the JSON/CSV you expect.
3. **Never fabricate a number.** If every source for a symbol failed, omit that symbol and say so.
   A missing row is recoverable; an invented price is not.
4. **Distinguish "no data" from "no source".** No print today (pre-market, weekend, holiday) is
   `no_data`. A symbol you could not fetch is `fetch_failed` — name the reason and HTTP status.
5. **Every artifact carries a `## Source health` section**: per source, the URL/query used, the
   HTTP status, and `ok` / `failed:<reason>`. If a source was rate-limited, say `429 rate-limited`
   and which fallback you used. Never hide a degraded run.
6. **Partial data beats no data.** If some symbols resolved and others did not, WRITE the
   artifact with the symbols you have, mark the gaps, and report `errors: <n>`. Do not abort the
   whole run because one source was blocked. The zero-fallback policy governs the *fallback
   chain*, not whether the artifact gets written.

## GIT PUSH (OPTIONAL)
After writing the artifact, commit and push it to `karizaco/minimax-cloud-outputs` (branch `main`).

```bash
cd /workspace
export GIT_SSL_CAINFO=/etc/ssl/certs/agent-identity/sandbox-gateway-ca.crt
export SSL_CERT_FILE="$GIT_SSL_CAINFO"
export CURL_CA_BUNDLE="$GIT_SSL_CAINFO"
export HOME=/workspace/.home; mkdir -p "$HOME"
export DATE=$(TZ=America/New_York date +%Y-%m-%d)
git config --global http.sslCAInfo "$GIT_SSL_CAINFO"
git config --global user.email "maxhermes-cloud@local"
git config --global user.name "MaxHermes Cloud Cron"
git init -q 2>/dev/null || true
git remote add origin "https://x-access-token:${GITHUB_TOKEN}@github.com/karizaco/minimax-cloud-outputs.git" 2>/dev/null || \
  git remote set-url origin "https://x-access-token:${GITHUB_TOKEN}@github.com/karizaco/minimax-cloud-outputs.git"

# --- push with race retry ---
# Routine pairs share a fire minute and push to the SAME branch (16:30 #05+#16,
# 08:30 #08+#26, 14:00 #10+#13, 15:00 #06+#14). The loser's push is REJECTED and its
# artifact is LOST - while the old block still reported success, because
# `git push ... | head -3` takes head's exit status, always 0. Measured 2026-10-28:
# a concurrent push lost options-flow/<date>.md and reported exit 0.
# This loop re-fetches origin/main, rebuilds the worktree from the NEW tip, re-copies
# and re-commits, so the loser lands on the next attempt.
PUSH_OK=0
for attempt in 1 2 3; do
  git fetch -q origin main
  git worktree prune
  WT=/workspace/.wt.$(date +%s)$$
  rm -rf "$WT"
  git worktree add -f "$WT" origin/main >/dev/null 2>&1
  mkdir -p "$WT/earnings"
  cp -r "/workspace/earnings/." "$WT/earnings/" 2>/dev/null || true
  cd "$WT"
  git add earnings                 # ONLY this cron's output directory
  STAGED=$(git status --short)
  if [ -z "$STAGED" ]; then
    echo "push: ABORTED (nothing staged - the artifact was not copied into the worktree)"
    break
  fi
  if echo "$STAGED" | grep -q '^\s*D'; then
    echo "push: ABORTED (staged deletions detected - refusing to push)"
    break
  fi
  git commit -q -m "cron 15 15-earnings-reaction-scanner.md $DATE" || echo "nothing to commit"
  if git push -q origin HEAD:main 2>/tmp/push.err; then
    PUSH_OK=1
    echo "push: ok (attempt $attempt)"
    break
  fi
  echo "push: attempt $attempt rejected: $(head -1 /tmp/push.err | tr -d '\r')"
  sleep 5
done
cd /workspace
```

**CRITICAL - never use `git add -A` here.** In a fresh sandbox the working tree does not
contain the rest of the repo, so `git add -A` stages every other file on the branch as
DELETED. On 2026-10-25 cron #12's push (commit 1356a03) did exactly that and deleted 283
files, wiping the artifacts of cron #19 and seven other crons, plus the repo `.gitignore`.
If `git status --short` shows any `D` (deleted) entry, ABORT the commit and report the push
as failed.
Never `git push --force`. The remote branch is `main`; a fresh `git init` creates local
`master`, which is why the push target is `HEAD:main` and not `origin main`.
Never loop forever on a push failure - 3 attempts, then report the failure.
**If `${GITHUB_TOKEN}` is empty/unset:** skip the push entirely. Do NOT try `gh auth` or any
fallback. Just write the artifact and reply.

## DELIVERY VERIFICATION (MANDATORY - do this after the push block)
A successful `git push` is NOT proof of delivery. Verify the artifact is actually ON the remote
branch, and report the result truthfully. A push that silently failed is worse than a push that
failed loudly.

```bash
cd /workspace
export DATE=$(TZ=America/New_York date +%Y-%m-%d)
git fetch -q origin main
if git cat-file -e "origin/main:earnings/$DATE-reactions.md" 2>/dev/null; then
  echo "DELIVERY: ok (origin/main:earnings/$DATE-reactions.md present)"
else
  echo "DELIVERY: FAILED (origin/main:earnings/$DATE-reactions.md NOT found)"
  echo "  the artifact is still in the sandbox at earnings/ - report this, do not silently continue"
fi
```

`earnings/$DATE-reactions.md` is the repo-relative path of the artifact you just wrote, with `{{date}}`
replaced by `$DATE` (the shell variable above). If the cron writes several files, check the
primary one and list the rest.
- If DELIVERY is `ok` -> the reply line is `push: ok (verified)`.
- If DELIVERY is `FAILED` -> the reply line is `push: FAILED (artifact absent on origin/main)`.
  Say so plainly. Do NOT claim success. The artifact still exists in the sandbox, so also
  state the local path so the run is not lost.
- If the push was skipped (no token) -> `push: skipped (token unset)`.
- If all 3 push attempts were rejected, say so explicitly - a missing artifact is a real
  failure, not a warning.

## DELIVERY
The final reply (the only thing delivered to the chat) MUST use this structure. There is **no
line cap** — cap by NAMES SHOWN (top ~8 per tier), not by lines. Long-form detail
belongs in the artifact file, not in the chat.

1. **Prose opener** — 2-4 sentences: the headline finding of the run, then the caveat
   that most changes how it should be read. Complete sentences; no label lists, no clipped
   fragments.
2. **`### Signal`** — tiered bullets, ONE ticker per line, each line a short clause
   naming the catalyst or setup (e.g. `- BA -10.8% — Q3 adj EPS -$0.34 vs -$0.21 est;
   737 Max ramp pushed to H2-27`). Follow the skill's chat rules for tier order, flags and the
   audit line. For THIS scanner the tiers are: US pre-market gaps (PRE_GAP), EU/UK movers,
   ASX movers, and the catalyst table — name the top movers in each tier with their
   move and the catalyst. Lead with the top movers and the count of names, and give the source
   and any lag. State how many further names are in the artifact file.
3. **`### Method & caveats`** — 2-4 bullets: source(s), lag, universe/screen size, and
   every degraded or blocked source. Name what could not be verified.
4. **`### Files`** — one line per file written, with its sandbox path.
5. **`### Push / errors`** — one line for push status (`push: ok (verified)` /
   `push: skipped (token unset)` / `push: FAILED (<reason>)`) and one line for `errors: <n>` —
   count of source failures that triggered fallback, PLUS every cross-check mismatch that was
   dropped from the tables. 0 = clean run.

**Formatting rules — the reply is rendered in a chat client, not read as a diff.**
- Use a compact markdown **table** whenever there are 3+ comparable numeric rows (index
  levels, sector rotation, futures, breadth). Header row, `|---|` separator, numbers
  right-aligned. A table beats prose for anything the reader is going to compare.
- Keep every bullet to **one short line**. Never cram three facts into a 300-character
  line with two em-dashes and three numbers — split it into two bullets, or move the
  detail to the artifact file.
- Bold only the numbers that carry the story (the headline move, the level that matters),
  not every figure in the table.
- Blank line between the header and the first bullet under it, so the section renders as a
  heading rather than a run-on block.

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