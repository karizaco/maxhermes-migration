# Cloud Mavis cron: agentic-pre-market-brief (cron #26)

You are running as a Cloud Mavis cron. No local filesystem, no PowerShell, no Windows paths.
Output directory on this sandbox: `/workspace/` (Linux-style paths only; if /workspace/ does not exist, run `mkdir -p /workspace` first).

## SCHEDULE
- Original local schedule: 08:30 ET weekdays
- Fires 08:30 ET DAILY (schedule `30 8 * * *`, timezone America/New_York). The scheduler cannot
  express "weekdays at 08:30", so the weekday/weekend distinction is handled by the window check
  below — NOT by the schedule.
- **Do not skip the run because it is a weekend.** Run it every day. On weekends you produce a
  scoped WEEKEND brief (see WEEKEND MODE below). On weekdays you produce the full brief.

## WINDOW CHECK (RUN FIRST, BEFORE FETCHING THE SKILL)

```bash
mkdir -p /workspace
NOW_ET=$(TZ=America/New_York date '+%Y-%m-%d %H:%M %u')
DOW=$(TZ=America/New_York date +%u)
HOUR=$(TZ=America/New_York date +%H)
IS_WEEKEND=false
if [ "$DOW" -ge 6 ]; then IS_WEEKEND=true; fi
echo "window-check: OK ($NOW_ET) weekend=$IS_WEEKEND"
export IS_WEEKEND
```

**The window check never skips this cron.** It only records whether it is a weekend so the rest of
the run knows which mode it is in. Do NOT exit on a weekend. Do NOT write a SKIPPED file. The
artifact is always written.

## WEEKEND MODE (Sat/Sun)

On a weekend there is no live US pre-market session: cash equity closed Friday 16:00 ET, the
pre-market session does not open until Monday 04:00 ET, and index/commodity futures are closed
until Sunday 18:00 ET. **Only crypto trades live over the weekend.**

A weekend brief is therefore SHORTER and scoped to what actually exists. It MUST:

1. State prominently and at the top that it is a **weekend brief**, that the last completed US
   session was **Friday 2026-10-23** (i.e. the most recent Friday), and that the pre-market
   columns are **Friday's closing prints, not live weekend prices**. Never present a frozen
   Friday print as if it were a live pre-market gap.
2. Cover the **weekend-only live data**: crypto (BTC, ETH and the crypto-equity complex
   MSTR/COIN/MARA/RIOT/CLSK) — this IS live on weekends and is the most valuable weekend content.
3. Carry a **Monday-open setup** section: what closed Friday, what is scheduled for Monday
   (earnings before the open, macro releases), and what the weekend crypto tape implies for the
   Monday pre-market.
4. Include the Friday full-session screen (gainer/loser tables) as **"last session (Fri)"** context,
   clearly labelled as Friday's data — NOT as a pre-market table.
5. Still include: theme clusters, StockTwits lead read, macro calendar, source health, research
   queue. Keep the same section order as the weekday brief so downstream readers can rely on it.

**Do not fabricate a pre-market gap table on a weekend.** If Yahoo returns a stale/empty pre-market
print, say so and label the column "Fri close" instead of "Pre-mkt".

## SKILL SPEC (FETCH ONCE)
The skill's procedure body lives here:
  https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/skills/agentic-pre-market-brief/SKILL.md

**FIRST tool call:** `curl -s https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/skills/agentic-pre-market-brief/SKILL.md` (or `web_fetch` if available). Read the procedure in full. Do NOT skip this step.
Then follow the procedure verbatim, with these Cloud adaptations below.

## MCP TOOLS AVAILABLE
- `mcp__yahoo_finance__*`, `mcp__tradingview_advanced__*`, `mcp__web_search__*`
- `web_search`, `extract_content_from_websites` for catalyst/news research.

**Cloud reality (verified 2026-10-23/24):** all `mcp__yahoo_finance__*` / `mcp__tradingview*`
tools are NOT registered in this runtime. Replace at source with the equivalent live public APIs
and say so in Source health. Working replacements:
- Market/equity quotes + pre-market: Yahoo `https://query1.finance.yahoo.com/v7/finance/spark?symbols=A,B&range=1d&interval=1m&includePrePost=true` — **batches of 12 max** (larger batches return HTTP 400 on URL length).
- US screen: Yahoo `https://query2.finance.yahoo.com/v1/finance/screener/predefined/saved?scrIds=<id>&count=100&start=<n>` with ids `day_gainers` / `day_losers` / `most_actives`. **This tier needs no cookie/crumb.** The custom-POST screener tier (`v1/finance/screener` + getcrumb) is DOWN — `getcrumb` returns `Invalid Cookie` and POSTs return 401 `Invalid Crumb`. Do not retry it. Response shape: `finance.result` is a LIST — unwrap `result[0]`.
- Client-side US filter: `exchange ∈ {NMS,NYQ,PCX,ASE,NCM,NGM,NGS,AMX,PNK,OQB,OQX,BTS}`; drop warrants (symbol suffix W/U/WS/WT, or containing `=` or `^`); price>$10, mktcap>$3e8, vol>500k, |chg|>3.
- Sector rotation: pull the 11 SPDR ETFs (XLK XLP XLE XLF XLV XLI XLU XLY XLB XLRE XLC) as normal symbols. This is the fastest way to characterise a rotation and costs one batch.
- **Always pull the 11 sector ETFs.** They decided the 10/22 and 10/23 briefs.
- Pre-market gap = last 1m-bar close vs `regularMarketPrice`. **Do NOT use `chartPreviousClose`** (that is the prior session).
- Catalyst research: `web_search` (separate egress path from curl; stays up even if curl TLS breaks).

Full endpoint list + measured status: `https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/RUNTIME-CONTRACT.md`

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

**Transport:** the sandbox egress proxy issues 24h leaf certs and has expired mid-window before. At run start check `openssl s_client -connect query1.finance.yahoo.com:443 -servername query1.finance.yahoo.com </dev/null 2>/dev/null | openssl x509 -noout -dates`. If the leaf is expired, use `curl -k` and **disclose the unverified transport in Source health**. If valid, use `--cacert /etc/ssl/certs/agent-identity/sandbox-gateway-ca.crt` for verified TLS. **Always sanity-check response BODIES, not just status codes** — the proxy can return HTTP 200 carrying a plain-text error page.

## ZERO-FALLBACK POLICY
The skill procedure uses a fallback chain (PRIMARY → FALLBACK → skip).
**Every fallback MUST terminate with:**
  "accept the partial result, write the artifact, and STOP. Do NOT chain <deeper MCP>."
Do NOT loop on MCP errors. Do NOT retry indefinitely. Do NOT re-raise.

## HELPER SCRIPTS (PYTHON)
Local Mavis called Python helpers like `python screen.py emit-sql ...` to do file I/O, parsing, and atomic writes.
**On Cloud, do NOT call those helpers — they don't exist here.** Re-implement the helper's job inline using tool calls.

## AUDIT LOG
Local Mavis wrote an audit line to a Windows audit file after every run.
**On Cloud, skip audit log writes.** Audit is not needed here. If something goes wrong, the failure is in the chat reply and the (missing) artifact.

## OUTPUT
Write the artifact to:
  `/workspace/daily-briefs/{date}-pre-market.md`

The `{date}` placeholder is today in US/Eastern, `YYYY-MM-DD`. Resolve it as the first step.
(Literal text "{date}" in this template — replace it with the actual date.)

If the skill produces multiple outputs (e.g. .md + .csv, or per-region files), write all of them in the same `/workspace/daily-briefs/` subdirectory, with `{date}` as part of each filename.

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
  mkdir -p "$WT/daily-briefs"
  cp -r "/workspace/daily-briefs/." "$WT/daily-briefs/" 2>/dev/null || true
  cd "$WT"
  git add daily-briefs                 # ONLY this cron's output directory
  STAGED=$(git status --short)
  if [ -z "$STAGED" ]; then
    echo "push: ABORTED (nothing staged - the artifact was not copied into the worktree)"
    break
  fi
  if echo "$STAGED" | grep -q '^\s*D'; then
    echo "push: ABORTED (staged deletions detected - refusing to push)"
    break
  fi
  git commit -q -m "cron 26 26-agentic-pre-market-brief.md $DATE" || echo "nothing to commit"
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
if git cat-file -e "origin/main:daily-briefs/$DATE-pre-market.md" 2>/dev/null; then
  echo "DELIVERY: ok (origin/main:daily-briefs/$DATE-pre-market.md present)"
else
  echo "DELIVERY: FAILED (origin/main:daily-briefs/$DATE-pre-market.md NOT found)"
  echo "  the artifact is still in the sandbox at daily-briefs/ - report this, do not silently continue"
fi
```

`daily-briefs/$DATE-pre-market.md` is the repo-relative path of the artifact you just wrote, with `{{date}}`
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
The final reply (the only thing delivered to the chat) MUST be:
  - ≤ 10 lines.
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
4. **NEVER skip this run.** Weekends included — produce the scoped weekend brief described above. A skipped fire is a failure, not a graceful outcome.
5. Every percentage in the brief must trace to a fetched value or a cited source. Do not invent numbers. Audit before rendering.

================================================================
END OF CRON PROMPT
================================================================