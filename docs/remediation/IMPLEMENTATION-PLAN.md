# Implementation plan — 23 cloud cron prompt instructions

Companion to `CRON-PROMPT-AUDIT.md`. This is the **actionable** document: every change below is
listed once, with the exact replacement text, the files it touches, and its dependency.

**Scope of this plan:** the 65 findings from Tracks A–D plus the owner-side verification, collapsed
into **13 work packages**. Findings that are the same underlying edit are merged; every finding ID
is carried so nothing is lost.

**Verified against:** `karizaco/maxhermes-migration` @ `b1d12a6` (the audit ran against `24baf07`).
The only commit since was cron #90's **own status write**, which rewrote `90-delivery-auditor.md` —
so the push-block line numbers here are current for `b1d12a6`, but **anchor on the quoted text, not
the line number**, because the auditor rewrites itself. No other finding is affected: the
`cloud-prompts/` subtree was otherwise unchanged.
Deployed prompts read from `cron_read view=list`.

**Ground rules for every change below:**
- **Never** `git add -A`. Stage exact paths. A blanket add staged 283 deletions on 2026-10-25 and
  wiped seven routines' artifacts.
- **Never** `git push … | head -3`. It returns *head's* exit status, so a rejected push reports
  success. Capture `$?` directly.
- **Never** write a runtime fact as an absolute. Yahoo answers 429 from one cron egress and 200 from
  another on the same day. Write the conditional form.
- Every deploy is **byte-exact**: SHA-256 the deployed prompt against the repo blob. A
  `cron_update` returning `{"ok": true}` proves the write landed, not that it landed correctly.

---

## Dependency graph

```
WP1  shared contract + README + probe script   (no deps)
WP2  _shared/ scripts: push_artifact, verify_delivery, window_check  (no deps)
WP3  shared skill/contract text fixes            (depends on WP1)
WP4  in-prompt window check rewrite              (depends on WP2 — window_check.sh must exist)
WP5  in-prompt contract/tool-list rewrite        (depends on WP1)
WP6  in-prompt push + delivery rewrite          (depends on WP2)
WP7  quality rules: precedence, dating, errors  (depends on WP1)
WP8  prompt hygiene: flags, schedules, paths    (no deps)
WP9  reminder-tail alignment + reply formats     (depends on WP8)
WP10 repo doc regeneration (roster/index)        (depends on WP8 — roster needs #01 in the map)
WP11 outputs-repo cleanup + master branch policy (no deps)
WP12 repo→deployed sync                          (depends on WP1-WP10)
WP13 verification + drift guard                  (depends on WP12)
```

**WP12 is the one that matters.** Everything before it is a local improvement to a file no agent
reads. 21 of 23 deployed prompts currently differ from their repo file.

---

## WP1 — The shared contract, the README, and the probe script

**Findings:** B4, B5, B6, B7, B8, B11, B13, B14, C5, C6, ENV-1, ENV-2, ENV-5, ENV-6

### WP1.1 — `_shared/RUNTIME-CONTRACT.md`: fix the endpoint table

Replace the Yahoo rows (§2a, `:64-97`) with a conditional statement rather than a status:

```markdown
| **Yahoo chart / screener / quoteSummary / options** | `query1|query2.finance.yahoo.com/...` |
  **Availability varies by egress.** 200 on 2026-10-31 and again on 2026-11-02 from one cron
  session; **429 from another on the same day** (chart, screener, quoteSummary and options all
  affected; the cookie+crumb handshake was blocked too). This is **per-egress rate limiting**, not
  a property of Yahoo. Try it; on 429/401 treat it as *not available from this session* and fall
  through. **Never record "Yahoo is blocked" or "Yahoo works" as a standing fact.**
  `quoteSummary` and `options` require the **crumb** even when Yahoo answers (401 without it, 200
  with it). Yahoo **HTML** pages answer 200 independently of the JSON limit. |
```

Fix the three other wrong rows:

| Row | Replace with |
|---|---|
| `:51` `stocktwits` | `` 53 tools. **Pack-specific**: `chart_data` (OHLCV only — keys `symbol, period, count, first_close, last_close, change_pct, bars, source`), `trending`, `discover_tools`. **No `sentiment` tool.** `` |
| `:80-82` `www.sec.gov` | Add the UA requirement: `**Requires a contact-style User-Agent** (e.g. `mavis@example.com`) — plain curl / browser / Mavis UAs get **403**.`` |
| `:117` NASDAQ halt RSS | `**302** → `/Trader.aspx?id=http404` — the feed no longer exists. Following the redirect gives 200 with an HTML "Page not found" body, not an empty RSS item list.` |

### WP1.2 — `_shared/RUNTIME-CONTRACT.md`: split the superseded section

**Finding C6.** Move §2b (`:98-130`, the 2026-10-28 measurement) wholesale to a new file
`_shared/RUNTIME-CONTRACT-HISTORY.md` with a one-line header:

> Historical measurement, 2026-10-28. Superseded for Yahoo on 2026-10-31 — see the current table
> below. Retained because it documents that the 429 condition was **egress-side and transient**,
> not a property of Yahoo.

Keep the `CORRECTION (2026-10-31)` note where the live table is, but rewrite it so it does not
assert a standing fact:

```markdown
> **CORRECTION (2026-10-31).** The 2026-10-28 note claimed Yahoo JSON returns a *persistent* 429
> from this egress. That did not hold on 2026-10-31 — and on 2026-11-02 the same endpoint returned
> 429 from one cron session and 200 from another. **Treat Yahoo as conditionally available and
> fall through on 429.** Do not hard-code a Yahoo-avoidance path.
```

### WP1.3 — `_shared/probe_mcp.py`: one regex, one matching semantic

**Finding B4.** The file currently does:

```python
fin = [n for n in names if any(k in n.lower() for k in FINANCE_RE.split("|"))]
```

which compares each keyword as a **literal**, so `sec_?edgar` can never match `sec_edgar`
(verified: `'sec_?edgar' in 'mcp__sec_edgar__search'` → `False`).

Replace `FINANCE_RE` and the match with a compiled regex, and make it the single shared source:

```python
FINANCE_RE = re.compile(
    r"yahoo|tradingview|shibui|stocktwits|financekit|finviz|barchart|market|quote|"
    r"alpha_vantage|fmp|polygon|tiingo|tipranks|nasdaq|sec_?edgar",
    re.I,
)
...
fin = [n for n in names if FINANCE_RE.search(n)]
```

Then have `#01` and `#17` **import or fetch this file** instead of carrying inline copies. Today
there are three divergent copies: `probe_mcp.py` (16 keywords), `#01` inline (13), `#17` inline
(9 — missing `alpha_vantage`, `fmp`, `polygon`, `tiingo`).

### WP1.4 — `_shared/probe_mcp.py`: add a fourth state for a missing binary

**Finding B6.** `mcode-tools` is present in some Cloud sandbox images and **absent in others**
(verified: present at `/usr/local/bin/mcode-tools`, `connector tools` exits 0, probe prints
`catalog_ok total=133 finance_tools=0` — in another image the binary is simply not there).

Add a preflight and a fourth state, so "probe binary missing" is never recorded as a finding:

```python
def probe_catalog():
    if shutil.which("mcode-tools") is None:
        return {"state": "probe_unavailable",
                "detail": "mcode-tools not on PATH — absence of the probe binary is NOT a finding"}
    ...
```

And document it in the contract and in `#01`:

```markdown
- `probe_unavailable` — the probe binary itself is absent. **Not a finding.** Degrade to the
  normal source ladder; a session without `mcode-tools` says nothing about the catalog.
```

### WP1.5 — `_shared/barchart_fetch.py`: replace the Python implementation

**Finding B8.** The shipped helper cannot run: it globs the legacy `chrome-linux/` path and hard-imports
`python-playwright` in a Node-only image. **Node Playwright 1.59.1 is what actually ships** (at
`/app/node_modules/playwright`), and `pip` is unavailable so the Python path cannot even be installed.

Ship `barchart_fetch.js` with the same CLI contract (`--symbols`, `--list`), and update the contract
text at `:133-135`:

```markdown
### 2c-0. Browser-backed sources — PREFLIGHT FIRST
Chromium is **not** guaranteed to be present, and the **Node** Playwright package is the one that
ships (`/app/node_modules/playwright`, v1.59.1). Preflight before use:
`node -e "require('/app/node_modules/playwright')"` — if that fails, report the browser source as
unavailable and fall back. **Do not** `pip install playwright`: there is no `pip` in this image.
```

### WP1.6 — `cron-prompts/README.md`: the "Common contract" line

**Finding C5.** `README.md:54-55` still says Yahoo returns a persistent 429 — and this is the section
every routine and every new agent is pointed at. It is contradicted by three places in the same repo.

Replace the two lines with:

```markdown
- **Data sources**: the `mcp__*` tool names are NOT registered in this runtime. The MCP *servers* are
  reachable over plain HTTPS JSON-RPC via `_shared/mcp_bridge.py`. **Yahoo JSON availability varies
  by egress** — it was 429 on 2026-10-28 and 200 on 2026-10-31, and on 2026-11-02 one cron session
  got 429 and another got 200. Try it, fall through on 429/401, and never report it as a standing
  fact. `web_search` (separate egress), the Nasdaq API and the TradingView scanner always work.
  Full endpoint list + measured status: `_shared/RUNTIME-CONTRACT.md`.
```

### WP1.7 — Stooq and Frankfurter labels

**Findings ENV-5, ENV-6.** Correct the two labels wherever they appear:

- Stooq is **not** a 404. It returns **HTTP 200 with a JavaScript proof-of-work challenge** (796 B of
  HTML). An agent that checks only the status code will parse HTML as CSV. Correct label:
  `200 + JS challenge — body is not CSV`.
- Frankfurter's `api.frankfurter.app` now **301s** to `api.frankfurter.dev/v1/latest`. 18 prompt
  curl examples use `curl -s` without `-L` and silently get an HTML 301 body. Name the canonical host
  `api.frankfurter.dev/v1/latest` in the contract and in any prompt that uses it.

---

## WP2 — The three shared scripts

**Findings:** D2, D3, A10, A11, A19

### WP2.1 — `_shared/push_artifact.sh`

**Findings D2, A10, A11.** The push block is 3,190–3,255 B × 21 = **67,000 B** of near-identical
bash, and it has already produced a real bug class. `#90` is the only place the
`git push … | head -3` trap still runs live — **anchor on the text**, not the line number:
`git push -q origin HEAD:refs/heads/audit/status 2>&1 | head -3` (line 528 as of commit
`b1d12a6`; it was 482 before #90 rewrote its own prompt on 2026-11-02) *and* it builds its
worktree from `origin/main` while pushing to `refs/heads/audit/status` — both wrong.

```bash
#!/usr/bin/env bash
# push_artifact.sh — the ONE push implementation for the fleet.
#
# usage: push_artifact.sh --out <output-dir> --add <repo-relative-path> [--branch <branch>] [--msg <text>]
#   --out     the routine's output directory, relative to the repo root (e.g. daily-screens)
#   --add     the exact repo-relative path to stage. NEVER '.', NEVER a wildcard.
#   --branch  target branch (default: main). #90 pushes to audit/status.
#   --msg     commit message (default: "cron <dir> <date>")
#
# exit 0  = pushed and verified present on origin/<branch>
# exit 1  = push failed after 3 attempts (artifact still in the sandbox)
# exit 2  = no GITHUB_TOKEN (push skipped; caller writes the artifact and replies)
# exit 3  = refused to push (staged deletions detected, or --add was not a plain path)
set -uo pipefail

OUT=""; ADD=""; BRANCH="main"; MSG=""
while [ $# -gt 0 ]; do
  case "$1" in
    --out) OUT="$2"; shift 2;;
    --add) ADD="$2"; shift 2;;
    --branch) BRANCH="$2"; shift 2;;
    --msg) MSG="$2"; shift 2;;
    *) echo "push_artifact.sh: unknown arg $1" >&2; exit 3;;
  esac
done
[ -n "$OUT" ] && [ -n "$ADD" ] || { echo "push_artifact.sh: --out and --add are required" >&2; exit 3; }
case "$ADD" in *'*'*|.|/*) echo "push_artifact.sh: --add must be a plain relative path" >&2; exit 3;; esac

if [ -z "${GITHUB_TOKEN:-}" ]; then
  echo "push: skipped (token unset)"; exit 2
fi

export GIT_SSL_CAINFO=/etc/ssl/certs/agent-identity/sandbox-gateway-ca.crt
export SSL_CERT_FILE="$GIT_SSL_CAINFO"; export CURL_CA_BUNDLE="$GIT_SSL_CAINFO"
export HOME=/workspace/.home; mkdir -p "$HOME"
git config --global http.sslCAInfo "$GIT_SSL_CAINFO"
git config --global user.email "maxhermes-cloud@local"
git config --global user.name "MaxHermes Cloud Cron"
cd /workspace || exit 1
git init -q 2>/dev/null || true
git remote add origin "https://x-access-token:${GITHUB_TOKEN}@github.com/karizaco/minimax-cloud-outputs.git" 2>/dev/null \
  || git remote set-url origin "https://x-access-token:${GITHUB_TOKEN}@github.com/karizaco/minimax-cloud-outputs.git"

for attempt in 1 2 3; do
  git fetch -q origin "$BRANCH"
  git worktree prune
  WT="/workspace/.wt.$$.$RANDOM"
  rm -rf "$WT"
  git worktree add -f "$WT" "origin/$BRANCH" >/dev/null 2>&1
  mkdir -p "$WT/$(dirname "$ADD")"
  cp -r "/workspace/$OUT/." "$WT/$OUT/" 2>/dev/null || true
  cd "$WT" || continue
  git add -- "$ADD"                  # ONLY the named path. Never `git add -A`.
  STAGED="$(git status --short)"
  if [ -z "$STAGED" ]; then
    echo "push: ABORTED (nothing staged - the artifact was not copied into the worktree)"
    cd /workspace; rm -rf "$WT"; exit 1
  fi
  if echo "$STAGED" | grep -q '^ D'; then
    echo "push: ABORTED (staged deletions detected - refusing to push)"
    cd /workspace; rm -rf "$WT"; exit 3
  fi
  git commit -q -m "${MSG:-cron $OUT $(TZ=America/New_York date +%Y-%m-%d)}" || true
  # NOTE: capture the exit status DIRECTLY. `git push ... | head -3` returns head's status (always 0)
  # and reports a REJECTED push as a success. That trap shipped in this fleet until 2026-11-02.
  if git push -q origin "HEAD:refs/heads/$BRANCH" 2>/tmp/push_artifact.err; then
    echo "push: ok (attempt $attempt)"
    cd /workspace; rm -rf "$WT"
    exit 0
  fi
  echo "push: attempt $attempt rejected: $(head -1 /tmp/push_artifact.err | tr -d '\r')"
  cd /workspace; rm -rf "$WT"
  sleep 5
done
echo "push: FAILED (3 attempts rejected - the artifact is still in the sandbox at $OUT/)"
exit 1
```

### WP2.2 — `_shared/verify_delivery.sh`

```bash
#!/usr/bin/env bash
# verify_delivery.sh — confirm the artifact is ON the remote, not merely that the push exited 0.
# usage: verify_delivery.sh --path <repo-relative-path> [--branch <branch>]
# exit 0 = present on origin/<branch>;  exit 1 = absent.
set -uo pipefail
PATH_=""; BRANCH="main"
while [ $# -gt 0 ]; do
  case "$1" in
    --path) PATH_="$2"; shift 2;;
    --branch) BRANCH="$2"; shift 2;;
    *) exit 3;;
  esac
done
[ -n "$PATH_" ] || exit 3
cd /workspace || exit 1
git fetch -q origin "$BRANCH" 2>/dev/null
if git cat-file -e "origin/$BRANCH:$PATH_" 2>/dev/null; then
  echo "DELIVERY: ok (origin/$BRANCH:$PATH_ present)"; exit 0
fi
echo "DELIVERY: FAILED (origin/$BRANCH:$PATH_ NOT found)"; exit 1
```

### WP2.3 — `_shared/window_check.sh`

**Finding D3.** Six flag-block variants exist today; this makes the per-prompt configuration four
short tokens that cannot drift in shape.

```bash
#!/usr/bin/env bash
# window_check.sh — the ONE window check for the fleet.
#
# env: WEEKDAYS_ONLY, WEEKEND_ONLY, MARKET_HOURS_ONLY, DAY_OF_WEEK
#      HOUR_MIN, HOUR_MAX  (optional hour gate)
#      SKIP_DIR, SKIP_NAME, SKIP_LABEL
#      HOLIDAYS             (newline- or space-separated YYYY-MM-DD list)
#
# NOTE: the day-of-week now lives in the SCHEDULER, so the weekday/weekend/DAY_OF_WEEK branches
# below are a SAFETY NET, not the primary gate — a cron expression cannot express holidays, which
# is why HOLIDAYS exists.
#
# exit 0 = in-window (prints "window-check: OK (<now ET>)")
# exit 1 = out of window (prints "out-of-window: <reason>"; writes the SKIPPED marker)
set -uo pipefail
WEEKDAYS_ONLY="${WEEKDAYS_ONLY:-true}"
WEEKEND_ONLY="${WEEKEND_ONLY:-false}"
MARKET_HOURS_ONLY="${MARKET_HOURS_ONLY:-false}"
DAY_OF_WEEK="${DAY_OF_WEEK:-0}"
HOUR_MIN="${HOUR_MIN:-9}"; HOUR_MAX="${HOUR_MAX:-17}"

NOW_ET=$(TZ=America/New_York date +"%Y-%m-%d %H:%M %u")
DOW=$(TZ=America/New_York date +%u)
HOUR=$(TZ=America/New_York date +%H)
DATE=$(TZ=America/New_York date +%Y-%m-%d)
SKIP_REASON=""

[ "$WEEKDAYS_ONLY" = "true" ] && [ "$DOW" -ge 6 ] && SKIP_REASON="weekend (day=$DOW, expected Mon-Fri)"
[ "$WEEKEND_ONLY" = "true" ] && [ "$DOW" -lt 6 ] && SKIP_REASON="weekday (day=$DOW, expected Sat-Sun)"
if [ "$DAY_OF_WEEK" -gt 0 ] && [ "$DOW" -ne "$DAY_OF_WEEK" ]; then
  case $DAY_OF_WEEK in
    1) DAY_NAME=Monday;; 2) DAY_NAME=Tuesday;; 3) DAY_NAME=Wednesday;; 4) DAY_NAME=Thursday;;
    5) DAY_NAME=Friday;; 6) DAY_NAME=Saturday;; 7) DAY_NAME=Sunday;;
  esac
  SKIP_REASON="wrong day (today=$DOW, expected $DAY_NAME=$DAY_OF_WEEK)"
fi
[ "$MARKET_HOURS_ONLY" = "true" ] && { [ "$HOUR" -lt "$HOUR_MIN" ] || [ "$HOUR" -ge "$HOUR_MAX" ]; } \
  && SKIP_REASON="outside market hours (hour=$HOUR, expected $HOUR_MIN-$((HOUR_MAX-1)) ET)"
# HOLIDAYS: the one gate a cron expression cannot express. Half-days are trading days — do NOT skip.
if [ -n "${HOLIDAYS:-}" ]; then
  for h in $HOLIDAYS; do [ "$h" = "$DATE" ] && SKIP_REASON="US market holiday ($DATE)"; done
fi

if [ -n "$SKIP_REASON" ]; then
  if [ -n "${SKIP_DIR:-}" ]; then
    mkdir -p "$SKIP_DIR"
    cat > "$SKIP_DIR/SKIPPED_${SKIP_NAME:-this_routine}.md" <<EOF
# ${SKIP_LABEL:-Cron} — SKIPPED
- Date (ET): $DATE
- Time (ET): $(TZ=America/New_York date +%H:%M)
- Reason: $SKIP_REASON
- No artifact produced.
EOF
  fi
  echo "out-of-window: $SKIP_REASON"; echo "no artifact; no push"; exit 1
fi
echo "window-check: OK ($NOW_ET)"; exit 0
```

**A19 note:** the marker filename must not contain a colon. Rename the three that do
(`SKIPPED_reversal_bullish_3_55.md`, `SKIPPED_stock_screener_daily_sweep_18_30.md`,
`SKIPPED_stock_screener_focus_rvol_09_45.md`) and write the marker **into the routine's own
artifact directory** so it is auditable — but only if the skip is reachable at all, which after
WP4 it is not, for weekday routines. See WP4.

---

## WP3 — Shared skill and contract text

**Findings:** C7, C8, C9, C11, C15, D11

### WP3.1 — the five watchlist-reading skills

**Finding C8.** `research/watchlist.yaml` exists only on the Windows workstation. It is absent from
the workspace, the migration repo and the outputs repo. Five skills instruct a read of it: **#16,
#19, #22, #23, #26** (note `#23`'s `agentic-post-market-brief/SKILL.md:45` — *"**Read the
watchlist.** Same as pre-market"* — is a live reference that the earlier count missed).

Add one line to the `Cloud adaptations` block of each owning prompt:

```markdown
The skill's `research/watchlist.yaml` does not exist in Cloud. Substitute the deployed universe
(per the `## OUTPUT` path below) and say in `## Source health` that the watchlist pass was skipped
by hard rule — do not silently drop it.
```

### WP3.2 — the orphan skill directories

**Finding C7.** `cloud-prompts/skills/` holds 20 directories; **13 are referenced by a live prompt,
7 are not** (113,325 B of dir bytes / 51,422 B of `SKILL.md`), six byte-identical to the Windows
capture in `skills-original/`.

Move the 7 orphans to `cloud-prompts/history/skills-orphaned-2026-11-02/` (or delete them). Keep
`stock-screener-suite`, `eod-watchlist-snapshot` and `macro-calendar-week` — those are shared.

### WP3.3 — `skills/us-stocks-in-play/SKILL.md` fetch URL

**Finding C7.** The skill references `stocks-in-play-pipeline/SKILL.md`; the live directory is
`us-stocks-in-play/`. Add the fetch URL to `SKILL.md` lines 13 and 19:

```
https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/skills/stocks-in-play-pipeline/SKILL.md
```

and the same instruction to `17-us-stocks-in-play.md`.

### WP3.4 — dead references

**Finding C9.** 76 distinct path references across prompts, skills and shared docs; **31 resolve, 45
do not** — 34 Windows-shaped, 11 other. Fix the non-Windows ones:

| Dead reference | Fix |
|---|---|
| `scripts/screen.py` (`stock-screener-suite/SKILL.md`, `refs/tiering.md`) | State the tier thresholds inline in `refs/tiering.md` (the prose already gives them: Master 200 / Stalk 50 / Focus 12 / Tier-A 8, 2 and 3 stylists) and delete the `scripts/screen.py:_STYLIST_FROM_ORIGIN` reference. |
| `cloud-prompts/_shared/preopen_feed.py` (`preopen-feed-plan.md`) | Either ship the helper or delete the reference. |
| `cloud-prompts/n8n/README.md`, `cloud-prompts/n8n/workflow-preopen-feed.json` | Delete both references — the `n8n/` directory does not exist. |

### WP3.5 — `_classification.md` → history

**Finding C11.** It maps 26 *original local* crons; **4 of those numbers have no live cloud routine**,
and it describes local Windows helpers and the Finviz MCP as if they were the current mechanism.

**Move it, don't rewrite it** — it is a correct snapshot of the 2026-09-25 triage and rewriting it
would destroy the provenance the dropped-cron IDs need:

```
cloud-prompts/_classification.md → cloud-prompts/history/_classification-2026-09-25.md
```

Add a one-line header: *"Snapshot of the 2026-09-25 local→cloud triage. Historical: 4 of the 26
original cron numbers have no live Cloud routine, and the mechanism described here (Windows
helpers, Finviz MCP) is not the current one. See `cron-prompts/ROSTER.md` for the live fleet."*

### WP3.6 — the outputs repo `refs/` directory

**Finding C15.** `refs/` holds 8 files, 5 of them a stale pre-cloud copy of the runtime contract
(`crons.md` has Windows paths; `fallbacks.md` makes blocked Finviz a tier-2 source; `filters.md`
uses unregistered `mcp__shibui-finance__*`; `tiering.md` cites a non-existent `scripts/screen.py`).

Delete `refs/crons.md`, `refs/fallbacks.md`, `refs/filters.md`, `refs/tiering.md`. Keep
`cron-ops.md`, `cron19-earnings-reminder-review.md`, `plan-sources-and-mcp-tracking.md`. Replace
`refs/sources-us-stocks-in-play.md` with a 3-line pointer to `_shared/RUNTIME-CONTRACT.md`.

---

## WP4 — The in-prompt window check (the biggest single edit)

**Findings:** C1, C2, A3, A4, A5, A17, A19, D3, ENV-8

**What changes, and why.** The day-of-week now lives in the **scheduler**, so every weekday/weekend
/`DAY_OF_WEEK` branch is unreachable — proven for all 20 prompts by enumerating the days each
schedule can fire. But 17 tails *promise* a holiday skip, and the scheduler fires Mon–Fri
**including** market holidays.

**So: delete the dead branches, and replace the block with the one gate a cron expression genuinely
cannot express — the holiday guard.** Copy `#19`'s (which is correct: all ten 2026 NYSE dates are
real weekdays, none missing, half-days at 07:00/13:00 correctly still report).

Replace the whole 52-line `## WINDOW CHECK` block in each of the 20 prompts with:

```markdown
## WINDOW CHECK (RUN FIRST, BEFORE FETCHING THE SKILL)

The scheduler owns the day-of-week and the hour, so this block exists for ONE reason: a cron
expression cannot express a **market holiday**, and the scheduler fires Mon–Fri *including* them.
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
        cat > /workspace/$DATE/SKIPPED_<routine_name>.md <<EOF
# Cron #<n> <routine_name> — SKIPPED
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
```

**Net effect:** ~30 KB → ~1.2 KB across the fleet, and the promise in 17 tails becomes true instead
of false. (Note the trade-off: the marker is no longer produced on weekends — it never was, because
the scheduler doesn't fire weekday routines on weekends. The 31 existing markers are fossils of the
pre-scheduler era; see WP11.)

**Per-routine specifics:**
- `#16` (`:24`): `WEEKDAYS_ONLY=false` → `true` — it is the only weekday routine with the flag off. (A3)
- `#06` (`:19-22`): `WEEKEND_ONLY=true` + `DAY_OF_WEEK=0` → `DAY_OF_WEEK=6` (Saturday, `%u`
  convention), matching the `#14`/`#22` model. (A5)
- `#26` (`:38`): it drops the flag triple entirely and hard-codes `if [ "$DOW" -ge 6 ]`. With the
  block above that hard-coded line goes too. (A4)
- `#07` (`:34`–`:52`): its window-check block is **not fenced** unlike every other routine — add the
  ` ```bash ` / ` ``` ` fences. (A22)
- `#26` (`:59-66`): delete the `## WEEKEND MODE (RETIRED 2026-10-31)` tombstone — a retirement
  marker is only useful while the retired thing is still there. (C3)

---

## WP5 — The in-prompt contract and tool list

**Findings:** A13, B1, B3, B12, C10, D1, D4, D6, ENV-7

### WP5.1 — replace `## MCP TOOLS AVAILABLE` (17 prompts)

**Findings A13, C10, D6.** The block advertises `extract_content_from_websites` (16 of the 17 blocks
that carry it) and four `mcp__*` names that are not registered — and the very next section says
*"The `mcp__*` tools named above DO NOT EXIST in this runtime."* The prompt contradicts itself
within 400 bytes. Per the zero-fallback policy, calling one of these converts into an early abort
with no artifact written.

Replace with (331 B):

```markdown
## TOOLS AVAILABLE

The **MCP-over-HTTP bridge** (`_shared/mcp_bridge.py` — see PRIMARY SOURCE) is the market-data
source. Then `web_search`, `web_fetch`, `bash` (curl, python3), `connector__github__*` (repo
writes). **No `mcp__*` finance tool is registered in this runtime** — do not call one and do not
invent tool names.
```

### WP5.2 — replace `## RUNTIME DATA-SOURCE CONTRACT` (19 prompts)

**Findings D1, B5.** The block is **2,217–2,969 B each in the repo** (55,659 B across 19 prompts,
mean 2,929 B) and **1,848–1,867 B in the deployed copies** (35,481 B, mean 1,867 B) — the deployed
copies are the *older, shorter* text, which is exactly why the repo looks fixed while the fleet
still carries the stale wording. The repo block's Yahoo statement also contradicts the contract it
tells the agent to fetch. Replace with this 857 B version:

```markdown
## RUNTIME DATA-SOURCE CONTRACT (read before fetching any data)

**The `mcp__*` tools named above DO NOT EXIST in this runtime.** Do not attempt an MCP call and do
not wait for one to appear — a tool-not-found error converts into an early abort with no artifact.
Use instead: `web_search`, `web_fetch`, `bash` (curl, python3), and `connector__github__*` for repo
writes.

**Source ladder — try in this order, fall through on a real failure:**
1. bridge `market-recap` → `get_quotes` (batch quotes, `previous_close`, `change_pct`, `volume`,
   `as_of`, `market_state`). Not rate-limited. **This is the quote source of record.**
2. TradingView scanner `POST https://scanner.tradingview.com/america/scan` — movers, RVol,
   `premarket_volume`, `halted`, `market_cap_basic`.
3. Yahoo JSON — **availability varies by egress** (429 from one cron session, 200 from another on
   the same day). Try it; on 429/401 fall through. `quoteSummary`/`options` need the crumb.
4. Nasdaq API, SEC EDGAR (needs a contact-style UA), CoinGecko, Frankfurter, Treasury CSV.

**A 429/403 is a RATE LIMIT, not a missing symbol.** Never report "no data" for a symbol you never
successfully queried. Retry once after a short sleep, then fall through.

**Sanity-check the RESPONSE BODY, not just the HTTP status.** Stooq returns **200 with a
JavaScript challenge**, not CSV.

Full endpoint list + measured status:
`https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/RUNTIME-CONTRACT.md`
```

### WP5.3 — the `--list-packs` comment (21 prompts)

**Finding B1.** 21 prompts print `# enumerate available packs`. That is wrong — it is **semantic
discovery over a query**, and its output omits `stocktwits` and `shibui`, which both work by name.
`shibui` can never appear in discovery (different host).

Replace the trailing comment with:

```bash
python3 /workspace/mcp_bridge.py --list-packs   # SEMANTIC DISCOVERY, not an inventory —
                                                # returns packs whose TOOLS match the query.
                                                # stocktwits and shibui work by name but do
                                                # not appear here (shibui is a different host).
```

### WP5.4 — `#17`'s internal contradiction (B3, B12)

**Finding B3.** `#17` is byte-identical to its repo file *and* still says at `:110`:

> only. Verified 2026-10-28: the connector catalog exposed 15 tools, ALL media/email

Delete that clause and keep only the current measurement:

> only. **Re-verified 2026-10-31: the connector catalog exposes 133 tools — 118 `connector__github__*`
> (a built-in GitHub connector, authorized as `karizaco`), 13 `connector__matrix__*` (media) and 2
> `connector__email_workbench_credentials__*`.** There is still **no** `mcp__yahoo_finance__*`,
> `mcp__tradingview__*`, `mcp__shibui_finance__*`, `mcp__stocktwits__*`, `mcp__financekit__*` or
> `mcp__web_search__*`, and no `extract_content_from_websites`.

Apply the same correction to `#07` `:91-93`, `#19` `:96-98`, `#15` `:61-63`, and move the
"don't re-test these MCPs" instruction to stand on its own.

### WP5.5 — shrink `### MCP AVAILABILITY PROBE` (D4)

The script is **already fetched and run** — only the prose costs tokens. Replace with 551 B:

````markdown
### MCP AVAILABILITY PROBE (non-blocking, one cheap call)

```bash
B=https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared
[ -s /workspace/probe_mcp.py ] || curl -sL -o /workspace/probe_mcp.py "$B/probe_mcp.py"
python3 /workspace/probe_mcp.py
```

Record the result in this run's `## Source health`. It prints exactly one of:
- `catalog_ok total=N finance_tools=0` — catalog healthy, no financial MCP registered.
- `catalog_ok total=N finance_tools=K` — **a financial MCP has LANDED. Switch to it this run.**
- `catalog_unreachable` — the probe failed. **NOT** evidence that no MCPs exist.
- `probe_unavailable` — the probe binary is absent. **NOT a finding**; use the source ladder.
````

---

## WP6 — The in-prompt push and delivery blocks

**Findings:** A9, A10, A11, A12, D2

### WP6.1 — replace both blocks with a fetch-and-call stub (21 prompts)

```markdown
## PUSH THE ARTIFACT

```bash
B=https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared
for U in "$B/push_artifact.sh" "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/push_artifact.sh"; do
  [ -s /workspace/push_artifact.sh ] || curl -sL -o /workspace/push_artifact.sh "$U"
done
sh /workspace/push_artifact.sh --out <output-dir> --add <repo-relative-path> --branch main
```

Then run `sh /workspace/verify_delivery.sh --path <repo-relative-path>`.

**If the push script cannot be fetched**, use the inline fallback in
`cloud-prompts/_shared/push_artifact.sh` — but never `git add -A`, and never
`git push … | head -3` (that returns head's exit status and reports a rejected push as success).
```

### WP6.2 — `#90` needs its own branch target

**Findings A10, A11.** `#90` pushes to `refs/heads/audit/status` and **builds its worktree from
`origin/main`** — which is why its own status push fails (the base is a branch with no
`_audit/status.json`). It also has no retry loop and a truncated delivery check.

> **Line numbers drift.** Cron #90 rewrote its own prompt on 2026-11-02 (commit `b1d12a6`), moving
> the push block from `:482` to `:528`. Anchor on the **text**:
> - trap: `git push -q origin HEAD:refs/heads/audit/status 2>&1 | head -3`
> - wrong base: `git worktree add -f /workspace/.wt origin/main` (must be `origin/audit/status`)

Give it:

```bash
sh /workspace/push_artifact.sh --out _audit --add _audit/status.json --branch audit/status
sh /workspace/verify_delivery.sh --path _audit/status.json --branch audit/status
```

and extend the reply contract to define the two missing cases — `push: skipped (token unset)` and
the rejected-attempts case.

### WP6.3 — fix the stale collision comment (18 prompts)

**Finding A9.** 18 of the 21 prompts with a push block carry a **stale** fire-minute list
(`16:30 #05+#16, 08:30 #08+#26, 14:00 #10+#13, 15:00 #06+#14`). `#16` moved to 16:35 on 2026-10-29
to clear the 16:30 collision with `#05`, so that pair no longer collides.

Replace in all 18 with the correct text already used at `16-unusual-options-flow-daily.md:252-253`:

```bash
# Routines that share a fire minute push to the SAME branch (08:30 #08+#26;
# 14:00 #10+#13 on Wednesdays). The loser's push is REJECTED and its
# artifact is LOST - while the old block still reported success, because
# `git push ... | head -3` takes head's exit status, always 0. Measured 2026-10-28:
# a concurrent push lost options-flow/<date>.md and reported exit 0.
# This loop re-fetches origin/main, rebuilds the worktree from the NEW tip, re-copies
# and re-commits, so the loser lands on the next attempt.
```

### WP6.4 — file-scoped staging (A12)

Staging granularity is inconsistent across routines that share an output directory. Make every
`git add` file-scoped, matching `#19`:

```
#04: git add daily-screens/$DATE/reversal-bullish-3:55.md daily-screens/$DATE/reversal-bullish-3:55.csv
#08: git add daily-screens/$DATE/pre-market-gapper.md
#09: git add daily-screens/$DATE/daily-sweep.md daily-screens/$DATE/breadth.md daily-screens/$DATE/_regime.json
#10: git add daily-screens/$DATE/breadth-snapshot.md
```

---

## WP7 — The three quality rules

**Findings:** D5, D12, A15, ENV-7

These are the changes that make the artifacts *better*, not smaller. They deliberately **add** ~6,000
tokens per fleet-fire.

### WP7.1 — source-precedence rule (D5)

**Finding D5.** 18 of 20 market-data routines have no rule for which source wins when two disagree.
The artifacts show the consequence: a routine concluded *"no market-data source available … not
fixable from inside the sandbox"* while its own prompt said the source was reachable, and published a
pre-market gap built on a stale tape that had to be corrected a day later.

Add as rule 7 to the shared `### Rules` block (611 B):

```markdown
7. **One number per field, one source per field.** When two sources give different values for the
   same field, pick ONE and say which in `## Source health`: the bridge's `market-recap` for prices
   and movers (Yahoo-sourced, not rate-limited), the TradingView scanner for pre-market and RVol,
   Yahoo JSON for history. When they disagree by more than 0.6 %, prefer the bridge, say so, and
   **do not publish both**. Never report "no source available" when a source is reachable —
   a 429 is a rate limit, not an absence.
```

### WP7.2 — the dated-replay rule (D12)

**Finding D12.** The quota wall (error 2067) kills a session at its scheduled time and the platform
re-dispatches the *same session* later. Measured 2026-11-01: `#25`'s 2026-10-30 09:00 ET fire was
re-dispatched and executed on **Sunday 2026-11-01 01:51 ET** — and the weekend guard fired on
`DOW=7`, which would have **discarded a real trading-day brief**. The repo already carries a
6,484-byte section for this; it is not deployed.

Replace the "today in US/Eastern" clause in the shared `## OUTPUT` block with (426 B):

```markdown
The `{date}` placeholder is the fire's **scheduled** date in US/Eastern, `YYYY-MM-DD`. Resolve it
from the run's `scheduled_at_ms` (`cron_read view=runs` → `run.scheduled_at_ms`), not from `date`
at execution time. If they differ, this is a **delayed replay**: rebuild for the scheduled date,
do NOT write a SKIPPED marker, and say in the artifact that it is a reconstruction produced late.
A replay is normal, not an error.
```

### WP7.3 — the `errors: <n>` definition (A15)

17 of 19 prompts define `errors:` as "count of MCP failures". That is misleading: the absent
`mcp__*` tools are **not** failures, and counting them as such trains the reader to ignore the
field. Replace with the wording already used at `19-earnings-reminder-daily.md:417-418`:

```markdown
- `errors: <n>` — count of **SOURCE** failures that degraded the artifact. 0 = clean run. The
  absent `mcp__*` tools are NOT an error and must not be counted.
```

### WP7.4 — the `## Source health` heading (ENV-7)

19 prompts mandate a literal `## Source health` heading, but a literal grep over the outputs repo
gives `options-flow 0/9` and `weekly 0/2` — while `options-flow/2026-10-30.md` opens with a
`_source=cboe delayed-quote CDN option chains (8/8 underlyings, HTTP 200) · nasdaq public quote
API …` line plus a data-quality caveat naming every degraded source. The agents disclose *more*
than most routines that do match the heading.

Change the instruction and any audit to accept either form:

```markdown
- Every artifact discloses per-source health: a `## Source health` section **or** an equivalent
  `_source=` front-matter line — per source, the URL/query used, the HTTP status, and `ok` /
  `failed:<reason>`. If a source was rate-limited, say `429 rate-limited` and which fallback you
  used. Never hide a degraded run.
```

---

## WP8 — Prompt hygiene

**Findings:** A1, A2, A4, A5, A6, A7, A8, A13, A19, A21, A22, A23

| ID | File:line | Change |
|---|---|---|
| A1 | `07-…-09:45.md` after `:341` | Append a `## CRITICAL REMINDERS` section with the four standing items (skill-fetch-first, tools-only-from-the-contract, fresh-session, out-of-window exit) plus the `### PRIMARY SOURCE` bridge rule. `#07` is currently the only routine whose tail carries none of them — including "do not call the `mcp__*` tools". |
| A1 | `01-weekly-mcp-health-check.md` | Either promote it to a first-class routine prompt with the standard sections, or add a `## CRITICAL REMINDERS` / `## DELIVERY` pair. Its prompt body is currently nested inside a fence at `:42`. |
| A2 | `26-…-pre-market-brief.md:78` | Split the file: keep the two provenance lines in `## MCP TOOLS AVAILABLE`, re-open the text from `:79` as `## RUNTIME DATA-SOURCE CONTRACT (read before fetching any data)`, and insert `### PRIMARY SOURCE: the MCP-over-HTTP bridge (use this FIRST)` at the same relative position the other 20 use (immediately before the bridge bash block at `:92`). `#26`'s `## CRITICAL REMINDERS` at `:320` says *"Use ONLY the tools named in the RUNTIME DATA-SOURCE CONTRACT above"* — but `#26` has **no** such section (its only hit for that string is that very reference), so the instruction points at nothing. |
| A6 | `#06`, `#13`, `#14` `:7-8` | Replace with the standard two-field form. `#06`: `- Original local schedule: \`0 10 * * 6\` America/New_York — Saturday 10:00 ET.` / `- Deployed schedule: \`0 15 * * 6\` America/New_York — Saturday 15:00 ET. Moved from 10:00 ET on 2026-10-29 to clear the 15:00 push slot.` `#06`'s current "Schedule is unchanged" claim is **false**. |
| A7 | `#05`, `#20`, `#23`, `#26` | The "Original local schedule" is wrong in four routines — `#05` → 16:35 ET weekdays, `#20` → 16:30 ET weekdays, `#23` → 22:35 ET weekdays, `#26` → 07:37 ET weekdays. |
| A8 | `#19` `:6-9` | Replace with the standard two-field form plus the pairing note: `- Original local schedule: \`0 6 * * 1-5\` America/New_York — 06:00 ET, Mon-Fri.` / `- Deployed schedule: \`0 6 * * 1-5\` America/New_York — 06:00 ET, Mon-Fri.` / `- The skill pairs with the pre-market brief, cron #26, which fires 08:30 ET (\`30 8 * * 1-5\`) — 2h30m after this routine. This artifact must land on disk BEFORE that brief reads it. (#26 originally fired 07:37 ET; it was moved to 08:30 ET.)` |
| A21 | `#04` `:227` | `/workspace/daily-screens/{date}/reversal-bullish-3:55.{md,csv}` is brace-expansion syntax, not a path. Use two explicit paths: `...reversal-bullish-3:55.md` and `...reversal-bullish-3:55.csv`. |
| A22 | `#07` `:34`–`:52` | Its window-check block is not fenced unlike every other routine — add the ` ```bash ` / ` ``` ` fences. |
| A23 | `#91` `:50-58` | Move `## WHAT THIS CRON IS FOR` to sit after `## SCHEDULE`, matching `#90`. |

### WP8.1 — one more: `#26`'s flag triple

**Finding A4.** `#26` drops the flag triple entirely, so its window check cannot be parsed by the same
convention as the other 19. With WP4's rewrite this is resolved, but if the flags are kept, insert:

```bash
WEEKDAYS_ONLY=true
WEEKEND_ONLY=false
MARKET_HOURS_ONLY=false
DAY_OF_WEEK=0   # 1=Mon ... 7=Sun; 0=no constraint
```

---

## WP9 — Reminder tails and reply formats

**Findings:** A14, A16, A17, D10

### WP9.1 — the CRITICAL REMINDERS tail

**Finding A16.** There are 7 variants across the 19 template prompts. Forms 3–7 each encode a real
routine-specific constraint — **leave them**. Align form 2 to form 1 by re-joining item 1 in
`#08` `:359-360`, `#22` `:354-355` and `#25` `:429-430` into the single line used at `#02` `:353`.
Add the standing "do not invent tool names" item to `#15`'s tail.

### WP9.2 — trim to what isn't stated elsewhere (D10)

Replace the tail with a 395 B version containing only what is *not* said elsewhere:

```markdown
## CRITICAL REMINDERS
1. The cron session is fresh each time — there is no shared state. Treat every artifact as
   ephemeral unless pushed.
2. If the skill fetch fails, write a stub artifact with `_source=skill_fetch_failed` and reply
   with the failure. Do NOT improvise the procedure from memory.
3. Do NOT call the `mcp__*` tools — they are not registered in this runtime — and do not invent
   tool names.
4. If the cron fires outside its intended window, exit cleanly with "out-of-window: <reason>".
   Do NOT run a degraded version.
```

### WP9.3 — the reply format

**Finding A14.** The shared README says "**no line cap**", but three routines impose one: `#07`
("Six lines, no preamble:", and a completely different schema with none of the five README
headings), `#90` ("≤ 8 lines"), `#01` ("under 10 lines").

Recommended: bring `#07` onto the five-part structure (`### Signal` / `### Method & caveats` /
`### Files` / `### Push / errors`) so a consumer parsing by the README gets something parseable, and
keep `#90`'s and `#01`'s caps but **state them in the README as documented exceptions** — an audit
digest and a weekly health report legitimately want a different shape.

### WP9.4 — the false-degradation wording (A17)

**Finding A17.** `#26`'s tail asserts a behaviour its own window check does not have. After WP4 the
holiday guard is real, so the assertion becomes true — but it must be asserted **once**, in the
shared guard, not repeated in 17 tails with three different numbers (12 / 13 / 17).

---

## WP10 — Regenerate the fleet docs

**Findings:** A20, C12, ENV-8

**Finding C12.** README.md, ROSTER.md and roster.json all list 23 routines and a field-by-field
cross-check found **zero substantive divergences** — the *structure* is fine. What is stale is the
**snapshot**: the last-delivered dates and the schedule table.

**Finding A20.** `#01`'s artifact is missing from ROSTER.md, and the two generated docs are two days
apart — a hand-kept table is a table that lies.

1. Add `#01` to the artifact map in `tools/gen_roster.py` with the pattern `mcp-health/{date}-Wnn.md`
   (and the ledger).
2. Regenerate both from the same run:
   ```bash
   cron_read view=list > tasks.json
   python3 tools/gen_roster.py --tasks tasks.json --repo ./outputs-clone --out .
   python3 tools/gen_index.py --tasks tasks.json   # rewrites the README table
   ```
3. Make the roster **expire**: have `gen_roster.py` stamp the generation time and have `#91`
   flag a roster older than 48 h.

---

## WP11 — Outputs-repo cleanup and the master branch

**Findings:** C4, C13, C14, C13

### WP11.1 — the `master` branch policy (C13)

`master` is the clone default and is **25 commits behind + 1 merge commit diverged** (746 vs 831
files). The one file it retains (`earnings/IMPROVEMENTS-cron19.md`) was dropped from `main`
**deliberately** in `1094edc` — so this is staleness, not corruption.

Either:
- **fast-forward `master` to `main`** — the divergence is a single merge commit, so:
  ```bash
  git fetch origin main master
  git push origin origin/main:master          # non-fast-forward; use --force-with-lease
  ```
  (Two dated backup branches already exist — `backup/main-2026-10-30` and `backup/master-2026-10-30`
  — so this is reversible.) **Note:** the PAT has no repo-admin scope, so `default_branch` cannot be
  flipped; the branch pointer is the only lever.
- **or** state in the README that `main` is the artifact branch and `master` is **not** a mirror —
  and stop calling it one.

Either way, a plain `git clone` must land on a tree that is not 86 files short.

### WP11.2 — the stale artifact trees (C4, C14)

- Delete the 7 top-level date directories from `main` (20 files, all `SKIPPED_*.md` markers, no
  routine writes that path any more).
- Move the 11 `international-eod/*/SKIPPED_pre_market_fire.md` markers and the remaining markers
  into a single dated `refs/skipped-markers/` directory.
- Delete the dead trees in **one additive commit** — stage exact paths, never `git add -A`.

---

## WP12 — Deploy the repo to the fleet

**Findings:** B5, B10, D11

**This is the step that has been missing.** 21 of 23 deployed prompts currently differ from their
repo file; 18 carry a dead catalog composition and a dead Yahoo condition.

1. **Fix the repo first** (WP1–WP11). Nothing to deploy until then.
2. **Deploy byte-exactly, 3–4 prompts per session.** For each: `cron_update` with the full repo
   prompt text, then `cron_read view=detail` for that task and **SHA-256 the read-back against the
   repo blob**. A `{"ok": true}` proves the write landed, not that it landed correctly.
3. **Prove the blast radius.** Snapshot `cron_read view=list` before and after and compare every
   task's prompt hash, `schedule`, `timezone`, `enabled`, `session`, `model`, `project_id` and
   `next_run`. Exactly the tasks you intended must change.
4. **Never send `enabled` or `model` to `cron_update`** — `enabled` is coerced to the string
   `"true"` and fails validation; `model` does not exist on the tool. A partial update preserves
   everything else, including `thinking.effort`.
5. **Always send `timezone`** with `schedule` — omitting it silently resets to `Etc/GMT-7` (UTC+7,
   an 11-hour error that fires routines after market close).
6. `#90` also needs the deployed `#91` re-applied with its conversation-hygiene vocabulary and the
   corrected exit-code legend (B10).

**Verification after deploy:** the deployed prompt must be byte-identical to the repo file. Assert
it in CI, not by eye — see WP13.

---

## WP13 — Make the drift detectable

**Findings:** D11, B9, C12

### WP13.1 — prompt-drift detection in the existing drift guard

`#91` already reads the live scheduler, so it already has the `cron_read` JSON. Add:

```markdown
## STEP 2c — PROMPT DRIFT (repo vs deployed)

For each task in $CHUNK: sha256(task.prompt) vs sha256(cloud-prompts/cron-prompts/<cron_name>).
Report `PROMPT-DRIFT` (repo) when they differ, with the byte delta and the first differing line.
A repo fix that has not been deployed is the single highest-cost silent failure in this fleet:
18 of 23 routines carried a dead catalog composition and a dead Yahoo condition for three days
because the repo was correct and the deployed copy was not.
```

### WP13.2 — fix `#91`'s chunk discovery (B9)

`#91`'s STEP 1 chunk-discovery command can select the wrong tool-result file and abort the detector.
Replace with a content-aware selector:

```bash
CHUNK=""
for f in $(ls -t /workspace/.mavis/tool-results/*/*/chunks/*.txt 2>/dev/null | head -20); do
  if grep -q '"tasks"' "$f" 2>/dev/null; then CHUNK="$f"; break; fi
done
[ -n "$CHUNK" ] || { echo "ERROR: cron_read output not found on disk"; exit 1; }
```

---

## Consolidated impact

| Metric | Today | After | Change |
|---|---:|---:|---:|
| Deployed fleet prompt bytes | 433,427 B | ≈302,848 B | **−30.1 %** |
| ≈ tokens per full fire-set | 108,356 | ≈75,712 | **−32,644 tok** |
| ≈ tokens per calendar day | 423,148 | ≈290,349 | **−132,799 tok** |
| Unreachable window-check code | ~30 KB | ~1.2 KB | **−29 KB** |
| Deployed prompts matching their repo file | 2 / 23 | 23 / 23 | **+21** |
| Routines with a real holiday guard | 1 / 23 | 23 / 23 | **+22** |
| Prompts naming tools that are not registered | 17 | 0 | **−17** |
| Push implementations | 21 copies + 1 broken | 1 script | **−21** |
| Finance-detection regex copies | 3 (one broken) | 1 | **−2** |

**Order of work:** WP1 + WP2 (shared truth and scripts) → WP3–WP9 (rewrite the 23 prompts against
them) → WP10 + WP11 (docs and repo hygiene) → **WP12 (deploy)** → WP13 (make drift detectable).

Do not skip WP12. A corrected repo with a stale deployment is the exact failure this audit spent its
time documenting.
