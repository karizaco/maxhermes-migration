# Cloud Mavis cron: cross-asset-correlation-snapshot (cron #12)

You are running as a Cloud Mavis cron. No local filesystem, no PowerShell, no Windows paths.
Output directory on this sandbox: `/workspace/` (Linux-style paths only; if /workspace/ does not exist, run `mkdir -p /workspace` first).

## SCHEDULE
- Original local schedule: intraday
- Schedule is unchanged — only the runtime environment changed.


## WINDOW CHECK (RUN FIRST, BEFORE FETCHING THE SKILL)

The agent.minimax.io cron scheduler only supports coarse schedule types (daily, weekly, every X minutes).
It cannot express "weekdays at 09:45" or "every market hour". To work around this, this prompt
includes a window-check preamble. Run it as the FIRST step — before fetching the skill URL.

```bash
# Window flags for THIS cron (set by migration):
WEEKDAYS_ONLY=false
WEEKEND_ONLY=false
MARKET_HOURS_ONLY=true
DAY_OF_WEEK=0   # 1=Mon ... 7=Sun; 0=no constraint

# Resolve current time in US/Eastern
NOW_ET=$(TZ=America/New_York date +"%Y-%m-%d %H:%M %u")
DOW=$(TZ=America/New_York date +%u)
HOUR=$(TZ=America/New_York date +%H)

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
if [ "$MARKET_HOURS_ONLY" = "true" ]; then
    if [ "$HOUR" -lt 9 ] || [ "$HOUR" -ge 17 ]; then
        SKIP_REASON="outside market hours (hour=$HOUR, expected 09-16 ET)"
    fi
fi

if [ -n "$SKIP_REASON" ]; then
    mkdir -p /workspace/$(TZ=America/New_York date +%Y-%m-%d)
    cat > /workspace/$(TZ=America/New_York date +%Y-%m-%d)/SKIPPED_cross_asset_correlation_snapshot.md <<EOF
# Cron #12 cross-asset-correlation-snapshot — SKIPPED
- Date (ET): $(TZ=America/New_York date +%Y-%m-%d)
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
  https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/skills/cross-asset-correlation-snapshot/SKILL.md

**FIRST tool call:** `curl -s https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/skills/cross-asset-correlation-snapshot/SKILL.md` (or `web_fetch` if available). Read the procedure in full. Do NOT skip this step.
Then follow the procedure verbatim, with these Cloud adaptations below.

## MCP TOOLS AVAILABLE
- `mcp__tradingview_advanced__*`, `mcp__yahoo_finance__*`
- `web_search`, `extract_content_from_websites` for catalyst/news research.

## RUNTIME DATA-SOURCE CONTRACT (read before fetching any data)

**The MCP tools named above do not exist in this runtime.** They are listed for provenance only.
Verified 2026-10-28: the connector catalog exposes 15 tools, ALL media/email
(`connector__matrix__*`, `connector__email_workbench_credentials__*`). There is **no**
`mcp__yahoo_finance__*`, `mcp__tradingview__*`, `mcp__shibui_finance__*`, `mcp__stocktwits__*`,
`mcp__financekit__*` or `mcp__web_search__*`. `extract_content_from_websites` is also absent.
**Do not attempt an MCP call and do not wait for one to appear** — a tool-not-found error
converts into an early abort with no artifact, via the zero-fallback policy.

Use instead: `web_fetch` (fetch a URL, incl. a raw JSON endpoint), `web_search` (search; returns
page content), and `bash` (curl, python3). `web_search` uses a DIFFERENT egress than curl, so it
survives when curl is blocked.

### Tested data-source ladder (measured from this sandbox, 2026-10-28)

| Source | Endpoint | Status |
|---|---|---|
| `web_search` (tool) | — | **OK** — most reliable; separate egress |
| Nasdaq API | `https://api.nasdaq.com/api/quote/{SYM}/info?assetclass=etf` | **OK** |
| Yahoo page (HTML) | `https://finance.yahoo.com/quote/{SYM}/` | **OK** — scrape last close |
| CoinGecko | `https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum&vs_currencies=usd` | **OK** — crypto |
| Frankfurter FX | `https://api.frankfurter.app/latest?from=USD&to=EUR,JPY` | **OK** — FX |
| SEC EDGAR | `https://data.sec.gov/submissions/CIK{10DIGITS}.json` | **OK** — needs User-Agent |
| US Treasury | `https://home.treasury.gov/.../daily-treasury-rates.csv/2026/all?...` | **OK** — yield curve |
| Yahoo spark | `https://query1.finance.yahoo.com/v7/finance/spark?symbols=...` | **429** |
| Yahoo chart | `https://query2.finance.yahoo.com/v8/finance/chart/{SYM}?range=5d&interval=1d` | **429** |
| Yahoo screener | `https://query2.finance.yahoo.com/v1/finance/screener/predefined/saved?scrIds=day_gainers&count=25&start=0` | **429** |
| Stooq CSV | `https://stooq.com/q/l/?s={SYM}.us&f=sd2t2ohlcv&h&e=csv` | **404** |

**Yahoo's JSON endpoints return HTTP 429 "Edge: Too Many Requests" from this egress** — with and
without a browser User-Agent, and after a 60 s pause, so it is persistent rate limiting, not a
transient burst. Yahoo's *HTML* pages still work, and `web_search` still returns live data
(it returned SPY 769.66 close for 2026-10-27 while Yahoo JSON was 429).

### Rules

1. **Try `web_search` FIRST for any single-symbol quote.** It is the most reliable path here and
   it uses a different egress than curl, so it survives Yahoo blocking curl.
2. **For bulk data walk the ladder:** Yahoo JSON → (on 429) Nasdaq API → Yahoo HTML →
   `web_search` per symbol. Stop at the first source that returns real data.
3. **A 429/403 is a RATE LIMIT, not a missing symbol.** Never report "no data" for a symbol you
   never successfully queried. Retry once after a short sleep, then fall through.
4. **Sanity-check the RESPONSE BODY, not just the HTTP status.** The proxy can return HTTP 200
   carrying a plain-text error page. Confirm the body parses as the JSON/CSV you expect and has
   the fields you need before using any number.
5. **Never fabricate a number.** If every source for a symbol failed, omit that symbol and say
   so. A missing row is recoverable; an invented price is not.
6. **Distinguish "no data" from "no source".** A symbol with no print today (pre-market, weekend,
   holiday) is `no_data`. A symbol you could not fetch is `fetch_failed` — name the reason and
   the HTTP status.
7. **Every artifact carries a `## Source health` section**: per source, the URL/query used, the
   HTTP status, and `ok` / `failed:<reason>`. If a source was rate-limited, say `429 rate-limited`
   and which fallback you used. Never hide a degraded run.
8. **Partial data beats no data.** If some symbols resolved and others did not, WRITE the
   artifact with the symbols you have, mark the gaps, and report `errors: <n>`. Do not abort the
   whole run because one source was blocked. The zero-fallback policy governs the *fallback
   chain*, not whether the artifact gets written.

## ZERO-FALLBACK POLICY
The skill procedure uses a fallback chain (PRIMARY → FALLBACK → skip).
**Every fallback MUST terminate with:**
  "accept the partial result, write the artifact, and STOP. Do NOT chain <deeper MCP>."
Do NOT loop on MCP errors. Do NOT retry indefinitely. Do NOT re-raise.

## HELPER SCRIPTS (PYTHON)
Local Mavis called Python helpers like `python screen.py emit-sql ...` to do file I/O, parsing, and atomic writes.
**On Cloud, do NOT call those helpers — they don't exist here.** Re-implement the helper's job inline using tool calls:
  - SQL generation → emit SQL directly (see skill's reference docs if attached).
  - Finviz URL building → construct URL inline (see skill's filter spec).
  - Finviz HTML parsing → parse with regex/text extraction in agent context.
  - Atomic file write → `write_file(path, content)` (already atomic).
  - Deduplication → do it in agent reasoning before writing.

If the skill spec references a helper under `scripts/`, fetch the helper's URL too:
  https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/skills/cross-asset-correlation-snapshot/scripts/<name>.py
Read it for reference, but do NOT execute it. Re-implement its logic.

## AUDIT LOG
Local Mavis wrote an audit line to a Windows audit file after every run.
**On Cloud, skip audit log writes.** Audit is not needed here. If something goes wrong, the failure is in the chat reply and the (missing) artifact.

## OUTPUT
Write the artifact to:
  `/workspace/cross-asset/{date}.md`

The `{date}` placeholder is today in US/Eastern, `YYYY-MM-DD`. Resolve it as the first step.
(Literal text "{date}" in this template — replace it with the actual date.)

If the skill produces multiple outputs (e.g. .md + .csv, or per-region files), write all of them in the same `/workspace/cross-asset/` subdirectory, with `{date}` as part of each filename.

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
git fetch -q origin main
rm -rf /workspace/.wt
git worktree add -f /workspace/.wt origin/main
# copy THIS cron's artifact(s) into the worktree, then stage ONLY that path
mkdir -p "/workspace/.wt/cross-asset"
cp -r "/workspace/cross-asset/." "/workspace/.wt/cross-asset/" 2>/dev/null || true
cd /workspace/.wt
git add cross-asset                  # ONLY this cron's output
STAGED=$(git status --short)
if [ -z "$STAGED" ]; then
  echo "push: ABORTED (nothing staged — the artifact was not copied into the worktree)"
elif echo "$STAGED" | grep -q '^\s*D'; then
  echo "push: ABORTED (staged deletions detected — refusing to push)"
else
  echo "$STAGED"
  git commit -q -m "cron 12 12-cross-asset-correlation-snapshot.md $DATE" || echo "nothing to commit"
  git push -q origin HEAD:main 2>&1 | head -3
fi
```

**CRITICAL — never use `git add -A` here.** In a fresh sandbox the working tree does not contain
the rest of the repo, so `git add -A` stages every other file on the branch as DELETED. On
2026-10-25 cron #12's push (commit 1356a03) did exactly that and deleted 283 files, wiping the
artifacts of cron #19 and seven other crons, plus the repo `.gitignore`. If `git status --short`
shows any `D` (deleted) entry, ABORT the commit and report the push as failed.
Never `git push --force`. The remote branch is `main`; a fresh `git init` creates local `master`,
which is why the push target is `HEAD:main` and not `origin main`.
**If `${GITHUB_TOKEN}` is empty/unset:** skip the push entirely. Do NOT try `gh auth` or any fallback. Just write the artifact and reply.

## DELIVERY VERIFICATION (MANDATORY — do this after the push block)
A successful `git push` is NOT proof of delivery. Verify the artifact is actually ON the remote
branch, and report the result truthfully. A push that silently failed is worse than a push that
failed loudly.

```bash
cd /workspace/.wt 2>/dev/null || cd /workspace
export DATE=$(TZ=America/New_York date +%Y-%m-%d)
git fetch -q origin main
if git cat-file -e "origin/main:cross-asset/$DATE.md" 2>/dev/null; then
  echo "DELIVERY: ok (origin/main:cross-asset/$DATE.md present)"
else
  echo "DELIVERY: FAILED (origin/main:cross-asset/$DATE.md NOT found)"
fi
```

`cross-asset/$DATE.md` is the repo-relative path of the artifact you just wrote, with `{date}` replaced
by `$DATE` (the shell variable above). If the cron writes several files, check the primary one
and list the rest.
- If DELIVERY is `ok` → the reply line is `push: ok (verified)`.
- If DELIVERY is `FAILED` → the reply line is `push: FAILED (artifact absent on origin/main)`.
  Say so plainly. Do NOT claim success. The artifact still exists in the sandbox, so also
  state the local path so the run is not lost.
- If the push was skipped (no token) → `push: skipped (token unset)`.

## DELIVERY
The final reply (the only thing delivered to the chat) MUST be:
  - ≤ 8 lines.
  - Top movers / count / source / lag if any.
  - One line per output file written.
  - One line: "push: ok" / "push: skipped (token unset)" / "push: failed (<reason>)".
  - One line: "errors: <n>" — count of MCP failures that triggered fallback. 0 = clean run.

No preamble. Tool call → result → write → push → reply.

## CRITICAL REMINDERS
1. Skill URL above MUST be fetched first. If the fetch fails, write a stub artifact with `_source=skill_fetch_failed` and reply with the failure. Do NOT improvise the procedure from memory.
2. Use ONLY the tools named in the RUNTIME DATA-SOURCE CONTRACT above (`web_search`, `web_fetch`, `bash`). Do NOT call the `mcp__*` tools — they are not
   registered in this runtime — and do not invent tool names.
3. The cron session is fresh each time — there is no shared state. Treat every artifact as ephemeral unless pushed.
4. If the cron fires outside its intended window (e.g. holiday, weekend when it should be weekday), exit cleanly with "out-of-window: <reason>". Do NOT run a degraded version.

================================================================
END OF CRON PROMPT
================================================================