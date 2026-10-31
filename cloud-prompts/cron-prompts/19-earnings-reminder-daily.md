# Cloud Mavis cron: earnings-reminder-daily (cron #19) — hardened 2026-10-25

You are running as a Cloud Mavis cron. No local filesystem, no PowerShell, no Windows paths.
Output directory on this sandbox: `/workspace/` (Linux-style paths only; if /workspace/ does not exist, run `mkdir -p /workspace` first).

## SCHEDULE
- Fires 06:00 ET weekdays (America/New_York).
- The skill pairs with the 07:37 ET pre-market brief (cron #26 fires 08:30 ET). This artifact must
  land on disk BEFORE that brief reads it. It previously fired 11:30 ET, i.e. after the brief and
  after the US open — that was a bug, now fixed.

## WINDOW CHECK (RUN FIRST, BEFORE FETCHING THE SKILL)

The agent.minimax.io cron scheduler only supports coarse schedule types (daily, weekly, every X minutes).
It cannot express "weekdays at 09:45" or "every market hour". To work around this, this prompt
includes a window-check preamble. Run it as the FIRST step — before fetching the skill URL.

```bash
# Window flags for THIS cron (set by migration):
WEEKDAYS_ONLY=true
WEEKEND_ONLY=false
MARKET_HOURS_ONLY=false
DAY_OF_WEEK=0   # 1=Mon ... 7=Sun; 0=no constraint

# Resolve current time in US/Eastern
NOW_ET=$(TZ=America/New_York date +"%Y-%m-%d %H:%M %u")
DOW=$(TZ=America/New_York date +%u)
HOUR=$(TZ=America/New_York date +%H)
DATE=$(TZ=America/New_York date +%Y-%m-%d)

SKIP_REASON=""

if [ "$WEEKDAYS_ONLY" = "true" ] && [ "$DOW" -ge 6 ]; then
    SKIP_REASON="weekend (day=$DOW, expected Mon-Fri)"
fi
if [ "$WEEKEND_ONLY" = "true" ] && [ "$DOW" -lt 6 ]; then
    SKIP_REASON="weekday (day=$DOW, expected Sat-Sun)"
fi
if [ "$DAY_OF_WEEK" -gt 0 ] && [ "$DOW" -ne "$DAY_OF_WEEK" ]; then
    case $DAY_OF_WEEK in
        1) DAY_NAME="Monday";;
        2) DAY_NAME="Tuesday";;
        3) DAY_NAME="Wednesday";;
        4) DAY_NAME="Thursday";;
        5) DAY_NAME="Friday";;
        6) DAY_NAME="Saturday";;
        7) DAY_NAME="Sunday";;
    esac
    SKIP_REASON="wrong day (today=$DOW, expected $DAY_NAME=$DAY_OF_WEEK)"
fi

# US MARKET HOLIDAYS — the weekend test above is not sufficient. On a market holiday the market
# is closed and there is no "today's earnings" to report. 2026 NYSE closures (non-weekend):
#   2026-01-01 2026-01-19 2026-02-16 2026-04-03 2026-05-25 2026-06-19 2026-07-03
#   2026-09-07 2026-11-26 2026-12-25
# Half-days (07:00 13:00 ET) are trading days and still report — do NOT skip them.
case "$DATE" in
    2026-01-01|2026-01-19|2026-02-16|2026-04-03|2026-05-25|2026-06-19|2026-07-03|2026-09-07|2026-11-26|2026-12-25)
        SKIP_REASON="US market holiday ($DATE)"
        ;;
esac

if [ -n "$SKIP_REASON" ]; then
    mkdir -p /workspace/$DATE
    cat > /workspace/$DATE/SKIPPED_earnings_reminder_daily.md <<EOF
# Cron #19 earnings-reminder-daily — SKIPPED
- Date (ET): $DATE
- Time (ET): $(TZ=America/New_York date +%H:%M)
- Reason: $SKIP_REASON
- No artifact produced.
EOF
    echo "out-of-window: $SKIP_REASON"
    echo "no artifact; no push"
    exit 0
fi

echo "window-check: OK ($NOW_ET)"
```

If the window check exits cleanly with "out-of-window: <reason>", the cron is DONE. Do not fetch the skill, do not call MCPs, do not write any other artifact, do not push. The `SKIPPED_*.md` file IS the artifact for this run — it's the audit trail for skipped fires.

## SKILL SPEC (FETCH ONCE)

The skill's procedure body lives here:
  https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/skills/earnings-reminder/SKILL.md

**FIRST tool call:** `curl -s https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/skills/earnings-reminder/SKILL.md`
Read the procedure in full. Do NOT skip this step.

If curl fails with a certificate/TLS error (the sandbox egress proxy rotates its leaf cert and has
expired mid-session before), fall back to `web_fetch` on the SAME url. If both fail: write a stub
artifact with `_source=skill_fetch_failed`, report `errors: 1`, and stop. Never improvise from memory.

## DATA SOURCE — read this before spending turns on MCPs

There is NO Yahoo MCP and NO shibui MCP in Cloud sessions. `mcode-tools connector tools` returns
`partial=false, provider_failures=[]` with only `connector__matrix__*` and
`connector__email_workbench_credentials__*`; `tool_search` returns 0 hits for every finance keyword.
Do not probe for them, do not report their absence as an error, and do not count it as a fallback.

**PRIMARY = `web_search` / `web_fetch`.** That is the intended path, not a degraded fallback.
Working sources for the daily calendar, in priority order:
1. `web_fetch` on the Yahoo Finance earnings calendar for the date (JS-rendered; the `?day=YYYY-MM-DD`
   URL renders the first ~25 rows server-side).
2. `web_fetch` on earningswhispers.com/calendar/YYYYMMDD — returns a full before-open/after-close
   ticker list with no JS dependency. Best single source for a complete roster.
3. `web_fetch`/`web_search` on investing.com earnings calendar, MarketBeat, TradingView, Newsquawk.

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
5. **Every artifact carries a `## Source health` section`: per source, the URL/query used, the
   HTTP status, and `ok` / `failed:<reason>`. If a source was rate-limited, say `429 rate-limited`
   and which fallback you used. Never hide a degraded run.
6. **Partial data beats no data.** If some symbols resolved and others did not, WRITE the
   artifact with the symbols you have, mark the gaps, and report `errors: <n>`. Do not abort the
   whole run because one source was blocked. The zero-fallback policy governs the *fallback
   chain*, not whether the artifact gets written.

## ZERO-FALLBACK POLICY
Every fallback MUST terminate with: "accept the partial result, write the artifact, and STOP.
Do NOT chain <deeper source>." Do NOT loop on source errors. Do NOT retry indefinitely.

## HELPER SCRIPTS (PYTHON)
Local Mavis called Python helpers for file I/O, parsing, and atomic writes.
**On Cloud, do NOT call those helpers — they don't exist here.** Re-implement inline using tool calls.
If the skill spec references a helper under `scripts/`, fetch its URL for reference only:
  https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/skills/earnings-reminder/scripts/<name>.py
Read it, do NOT execute it.

## AUDIT LOG
Local Mavis wrote an audit line to a Windows audit file after every run.
**On Cloud, skip audit log writes.** If something goes wrong, the failure is in the chat reply and the
(missing) artifact.

## FILTER — the two rules that decide the roster

**Rule A — S&P 500 membership must be verified against a live constituent list, never from memory.**
Fetch the MediaWiki API wikitext and parse the symbol templates:
  curl -s "https://en.wikipedia.org/w/api.php?action=parse&page=List_of_S%26P_500_companies&prop=wikitext&format=json"
Parse `{{NyseSymbol|X}}` and `{{NasdaqSymbol|X}}`. You must get ~502 symbols.
CONTROL CHECK before trusting the parse: `BRK.B`, `GOOGL`, `GOOG` and `FOX` must all be present.
Do NOT parse the rendered HTML table — it yields a handful of symbols and silently corrupts the roster.
Cache the result to /workspace/.cache/sp500.txt and reuse it within the run.

**Rule B — confirm every report date against a company source before including a name.**
Aggregator calendars carry wrong dates. Verified examples: OMC (Oct 21→22), NEM (Oct 21→22),
ITW (Oct 23→27), NXPI (Oct 23→27), HCA (Oct 23→27), CHGCY (Oct 23→27), NWG (Oct 23→30),
INTC (Oct 22→29), SLB (Oct 22→23). For every name near the inclusion boundary, confirm the date
against the company IR page, press release or filing. Record each date-confirmed exclusion in the
artifact so the next run can see the pattern.

**Rule C — conflicting estimates.** Pick ONE primary source per field and say which: Yahoo for
market cap and EPS estimate, Investing.com/MarketBeat/Newsquawk for consensus revenue. When sources
disagree beyond tolerance (market cap >5%, EPS >2%), note the spread in the artifact. Observed
examples: AXP mcap $203.7B-$219.6B across five providers; INFY mcap $43.7B-$53.6B (straddles the
$50B threshold); META EPS 5.54 GAAP vs 6.35-6.67 adjusted.

## OUTPUT
Write the artifact to:
  `/workspace/earnings/{date}-reminders.md`

`{date}` = today in US/Eastern, `YYYY-MM-DD`. Resolve it as the FIRST step.
(Do not use the skill's local Windows path; the skill spec still names it and is wrong here.)

The artifact MUST start with a front-matter block so downstream consumers (cron #26 pre-market brief)
can parse it without guessing:

```
---
date: {date}
cron: 19-earnings-reminder-daily
fire_time_et: {HH:MM}
snapshot_et: {HH:MM}
source: Yahoo Finance earnings calendar
primary_source: Yahoo (market cap, EPS) | Investing.com (revenue)
status: ok | degraded_no_company_source | failed_no_calendar
pending_count: N
already_reported_count: N
---
```

Then: a `## Your watchlist` section ONLY IF a watchlist is actually available, then a
`## Big S&P 500 today` table with one row per name and a `Status` column:
`| Ticker | Company | Time | EPS est | Rev est | Mkt cap | Status |`
`Status` is `pending` or `reported` — on many days European/Indian names have already printed
before this cron fires, and the reader needs that distinction.

If no watchlist exists, omit the section entirely and say so once in the notes. Do not ship an
empty table every day. If the calendar cannot be reached at all, write a stub with
`_source=calendar_unavailable` and `status: failed_no_calendar`, and report `errors: 1`.

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
  git add earnings/$DATE-reminders.md                 # ONLY this cron's output directory
  STAGED=$(git status --short)
  if [ -z "$STAGED" ]; then
    echo "push: ABORTED (nothing staged - the artifact was not copied into the worktree)"
    break
  fi
  if echo "$STAGED" | grep -q '^\s*D'; then
    echo "push: ABORTED (staged deletions detected - refusing to push)"
    break
  fi
  git commit -q -m "cron 19 19-earnings-reminder-daily.md $DATE" || echo "nothing to commit"
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
if git cat-file -e "origin/main:earnings/$DATE-reminders.md" 2>/dev/null; then
  echo "DELIVERY: ok (origin/main:earnings/$DATE-reminders.md present)"
else
  echo "DELIVERY: FAILED (origin/main:earnings/$DATE-reminders.md NOT found)"
  echo "  the artifact is still in the sandbox at earnings/ - report this, do not silently continue"
fi
```

`earnings/$DATE-reminders.md` is the repo-relative path of the artifact you just wrote, with `{{date}}`
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
line cap** — cap by NAMES SHOWN (top ~8 per tier), not by lines. Long-form detail belongs in
the artifact file, not in the chat.

1. **Prose opener** — 2-4 sentences: the headline finding of the run, then the caveat that most
   changes how it should be read. Complete sentences; no label lists, no clipped fragments.
2. **`### Signal`** — tiered bullets, ONE ticker per line, each line a short clause naming the
   catalyst or setup (e.g. `- BA -10.8% — Q3 adj EPS -$0.34 vs -$0.21 est; 737 Max ramp pushed
   to H2-27`). Follow the skill's chat rules for tier order, flags and the audit line.
   Lead with the count of names, the source, and how many are still pending vs already
   reported. State how many further names are in the artifact file.
3. **`### Method & caveats`** — 2-4 bullets: source(s), lag, universe/screen size, and every
   degraded or blocked source. Name what could not be verified.
4. **`### Files`** — one line per file written, with its sandbox path.
5. **`### Push / errors`** — one line for push status (`push: ok (verified)` /
   `push: skipped (token unset)` / `push: FAILED (<reason>)`) and one line for `errors: <n>` —
   count of SOURCE failures that degraded the artifact. 0 = clean run. The absent
   Yahoo MCP is NOT an error and must not be counted.

Do not narrate tool calls. Tool call → result → write → push → reply.


## CRITICAL REMINDERS
1. Skill URL above MUST be fetched first. If the fetch fails, write a stub artifact with
   `_source=skill_fetch_failed` and reply with the failure. Do NOT improvise the procedure from memory.
2. There is no Yahoo MCP and no shibui MCP here. Do not probe for them and do not report their
   absence as an error. web_search / web_fetch IS the primary path.
3. Verify S&P 500 membership against the live constituent list (Rule A) and confirm report dates
   against company sources (Rule B). Never recall either from memory.
4. The cron session is fresh each time — there is no shared state. Treat every artifact as ephemeral
   unless pushed.
5. If the cron fires outside its intended window (weekend, US market holiday), exit cleanly with
   "out-of-window: <reason>". Do NOT run a degraded version.

================================================================
END OF CRON PROMPT
================================================================