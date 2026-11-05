# Cloud Mavis cron: delivery-auditor (cron #90)

You are running as a Cloud Mavis cron. No local filesystem, no PowerShell, no Windows paths.
Output directory on this sandbox: `/workspace/` (Linux-style paths only; if /workspace/ does not
exist, run `mkdir -p /workspace` first).

## CONVERSATION TITLE (do this FIRST, before anything else)

Every scheduled run gets its own conversation — one conversation per fire, never appended to an
earlier run's conversation. Give this conversation a title that says which day this run belongs
to, so the conversation list stays scannable.

1. Resolve today's date in US/Eastern: `TZ=America/New_York date +%d-%m` (day-month, no year).
2. Build the title: `[<DD-MM>] <NN>-<routine name>`. Take `<NN>` and `<routine name>` from the
   first line of this prompt (`# Cloud Mavis cron: <routine name> (cron #NN)`).
   Example: `[31-10] 12-cross-asset-correlation-snapshot`.
3. Set it with one call: `mcp_invoke` with tool_name `session_update` and arguments
   `{"session_id": "me", "title": "<the title>"}`. `me` means THIS conversation.
   If `mcp_invoke` reports that the tool is unknown, call `tool_search` with the query
   "session title update", then retry the same `mcp_invoke` call.
4. If the title cannot be set for any reason, carry on with the routine. This step must never
   block, delay, or fail the artifact.

## FETCH FALLBACK (certificate / TLS)

Every `curl` in this routine goes to the GitHub **contents API** first — it is the only source
that is not CDN-cached — with raw.githubusercontent.com and cdn.jsdelivr.net as fallbacks. If curl
fails with a certificate/TLS error — the sandbox egress proxy rotates its leaf cert and it has
expired mid-session before — retry the SAME url with `web_fetch`, which uses a different egress.
If both fail, say so in the reply and report `errors: 1`; do NOT report a status you did not
measure.

## SCHEDULE
- Deployed schedule: `0 7 * * *` America/New_York — 07:00 ET daily.
- Runs at 07:00 ET, which is AFTER every routine that fires before it (the earliest is 06:00 ET,
  #19) and BEFORE the routines that fire later in the day. It therefore catches the whole
  previous US trading day's early-morning artifacts, and the routines that fire between 07:00
  and 22:30 are audited by the NEXT day's run.
- Session mode: `new` — every fire starts a clean conversation, and the run sets that
  conversation's title to `[DD-MM] NN-<routine name>` so the list shows which day it belongs to.

## WHAT THIS CRON IS FOR

Every other routine verifies **its own** delivery (`git cat-file -e "origin/main:<path>"`).
That is necessary but not sufficient: **a routine that never fires cannot verify itself.**
Cron #22 ran for months with a schedule that contradicted its own window check — it skipped
every single fire and never produced a single artifact, and nothing noticed. The per-run check
is blind to exactly that failure mode. (That schedule has since been fixed; the failure mode it
exposed is the reason this cron exists.)

This cron is the external observer. It reads the cron roster, works out what SHOULD have run
against what actually landed on `origin/main`, and reports the difference. It writes no artifact
to the outputs repo and it changes nothing — it is read-only auditing plus one small status file.

## STEP 1 — WINDOW CHECK

```bash
NOW_ET=$(TZ=America/New_York date +"%Y-%m-%d %H:%M %u")
echo "audit start: $NOW_ET (dow %u, 1=Mon..7=Sun)"
```

Never skip. This cron must run every day, including weekends and holidays, because a missing
artifact on a Saturday is exactly the kind of thing that goes unnoticed otherwise.

## STEP 2 — CLONE THE OUTPUTS REPO (read-only)

```bash
cd /workspace
export GIT_SSL_CAINFO=/etc/ssl/certs/agent-identity/sandbox-gateway-ca.crt
export SSL_CERT_FILE="$GIT_SSL_CAINFO"
export CURL_CA_BUNDLE="$GIT_SSL_CAINFO"
export HOME=/workspace/.home; mkdir -p "$HOME"
git config --global http.sslCAInfo "$GIT_SSL_CAINFO"
git config --global user.email "maxhermes-cloud@local"
git config --global user.name "MaxHermes Cloud Cron"
git init -q 2>/dev/null || true
git remote add origin "https://x-access-token:${GITHUB_TOKEN}@github.com/karizaco/minimax-cloud-outputs.git" 2>/dev/null || \
  git remote set-url origin "https://x-access-token:${GITHUB_TOKEN}@github.com/karizaco/minimax-cloud-outputs.git"
git fetch -q origin main
# `master` is the repo's DEFAULT branch (GitHub's default_branch cannot be changed
# without repo Administration scope), but every routine pushes to `main`. So `master`
# is kept as a fast-forward MIRROR of `main` - the same commits, so a plain `git clone`
# lands on current artifacts. Always fetch `main` explicitly.
rm -rf /workspace/.audit
git worktree add -f /workspace/.audit origin/main
cd /workspace/.audit
git rev-parse --short origin/main | sed 's/^/  origin\/main = /'

# --- keep the default branch in step with main ---
# `master` is the default branch and every routine pushes to `main`. Fast-forward
# `master` to `main` so a plain `git clone` never lands on a stale tree. This moves a
# branch POINTER only - it never writes, deletes or rewrites an artifact, and it is
# fast-forward-only, so it can never lose a commit.
#
# NOTE the explicit refspec `origin/main:master`. The earlier form used
# `git push origin FETCH_HEAD:master`, but `git ls-remote` does NOT populate
# FETCH_HEAD (only `git fetch` does), so that push always failed with
# "src refspec FETCH_HEAD does not match any".
#
# The ancestry gate is what makes it safe: if `master` carries a commit `main` does not
# (it did on 2026-11-02, from a merge commit dated 2026-10-30), master is NOT an ancestor of
# main and the mirror is skipped rather than force-pushed. Whether master is behind or ahead
# changes as other routines push, so NEVER hardcode the comparison here - let
# `git merge-base --is-ancestor` decide at run time.
if git rev-parse --verify --quiet origin/master >/dev/null 2>&1; then
  if git merge-base --is-ancestor origin/master origin/main; then
    if git push -q origin origin/main:master 2>/tmp/master.err; then
      echo "  master mirror: fast-forwarded to main ($(git rev-parse --short origin/main))"
    else
      echo "  master mirror: skipped (push rejected: $(head -1 /tmp/master.err | tr -d '\r'))"
    fi
  else
    echo "  master mirror: skipped (origin/master has commits main does not - not a fast-forward; resolve the divergence before mirroring)"
  fi
else
  echo "  master mirror: skipped (master has been retired)"
fi
```

If `${GITHUB_TOKEN}` is unset, you cannot audit. In that case write the status file with
`audit_status: skipped_no_token`, report `errors: 1`, and stop. Do not guess.

## STEP 3 — DECIDE WHAT SHOULD HAVE RUN

The audit covers the **previous US trading day**. Compute it in ET:

```bash
TODAY=$(TZ=America/New_York date +%Y-%m-%d)
# the day whose artifacts should have landed before this run
AUDIT_DATE=$(TZ=America/New_York date -d "yesterday" +%Y-%m-%d)
AUDIT_DOW=$(TZ=America/New_York date -d "yesterday" +%u)   # 1=Mon..7=Sun
echo "auditing $AUDIT_DATE (dow $AUDIT_DOW)"
```

**Weekend audit dates — audit the routines that ARE due on that weekend.**
If `$AUDIT_DATE` was a **Saturday or Sunday** (`$AUDIT_DOW` 6 or 7), there is no US *weekday*
session: the Mon-Fri routines (`1-5`) correctly did not run, and their gaps are
`weekend_no_us_session` (NOT `MISSING`).

But a routine whose OWN schedule fires on that weekend day IS due and MUST be audited on it —
its absence is `MISSING`, not `weekend_no_us_session`:

| Audited day | Routine that IS due | Schedule |
|---|---|---|
| Saturday (`$AUDIT_DOW` 6) | 06-pattern-study-backlog | `0 15 * * 6` |
| Sunday (`$AUDIT_DOW` 7) | 01-weekly-mcp-health-check | `0 2 * * 0` |
| Sunday (`$AUDIT_DOW` 7) | 14-macro-calendar-week-ahead | `0 15 * * 0` |
| Sunday (`$AUDIT_DOW` 7) | 22-weekly-market-recap-preview | `47 17 * * 0` |

**This is the failure mode that hid #14 for a whole cycle.** On Sunday 2026-10-25 the EU DST
end moved #14's Europe/Berlin `0 15 * * 0` slot from 13:00 UTC to **14:00 UTC** — the exact
minute cron #12's `0 10 * * 1-5` ET slot fired (10:00 ET = 14:00 UTC). Both routines live in
project 10636, push to the SAME `main` branch, and at that time #14's push block still used
`git init` + `git add -A` with **no fetch and no retry** and `git push ... | head -3`, which
takes `head`'s exit status (always 0) — so a REJECTED push reported success. #12's push
landed first (commit `1356a03`, 14:07:33 UTC); #14's push was rejected as non-fast-forward
and its artifact was never written to `origin/main`. `macro-calendar/2026-10-25-week-ahead.md`
exists in NO commit on ANY ref. Two lessons: (1) `weekend_no_us_session` applies ONLY to
routines that were NOT scheduled to fire on that weekday — check the "Fires on" column before
labelling anything; (2) a routine can fire, build its artifact, and still deliver nothing
because the push lost a race — a MISSING with no git ADD event anywhere is a push loss, not
a skip.

**SCHEDULE CHANGES IN EFFECT (apply the OLD schedule to older audit dates):**
- **2026-10-29** — #15 (earnings-reaction-scanner) and #19 (earnings-reminder-daily) changed
  from `0 8 * * 1` / `0 6 * * 1` (Mondays only) to `0 8 * * 1-5` / `0 6 * * 1-5` (Mon-Fri).
  For `$AUDIT_DATE` **before 2026-10-29** those two were due ONLY on Mondays. A Tue-Fri gap
  before 2026-10-29 is `not_due`, NOT `MISSING`. From 2026-10-29 onward they are due Mon-Fri.
- **2026-10-29** — #16 (unusual-options-flow) moved from `30 16` to `35 16` (16:30 -> 16:35 ET)
  to clear a push race with #05. Same firing days, so due-ness is unchanged.
- **2026-10-29** — #22 (weekly-market-recap-preview) moved from `0 14 * * 6` (Sat) to
  `47 17 * * 0` (Sun 17:47 ET). Its **first fire under the new schedule is 2026-11-01**.
  Until 2026-11-01 it has never had a scheduled chance to run, so an empty `weekly/` is
  EXPECTED: report #22 as `not_yet_fired`, NOT `MISSING`. From 2026-11-02 onward a missing
  `weekly/2026-11-01-preview.md` IS `MISSING`.
- **2026-10-30 23:06 ET** — #07 (focus-rvol-09:45), #10 (breadth-snapshot), #12 (cross-asset-correlation),
  #17 (us-stocks-in-play) and #26 (agentic-pre-market-brief) moved from a daily schedule to
  weekday-only: `45 9 * * *` -> `45 9 * * 1-5`, `0 14 * * *` -> `0 14 * * 1-5`,
  `0 10 * * *` -> `0 10 * * 1-5`, `50 15 * * *` -> `50 15 * * 1-5`, `30 8 * * *` -> `30 8 * * 1-5`.
  They had no useful output on a closed weekend market. For `$AUDIT_DATE` **before 2026-10-31**
  those five were due EVERY day, so a weekend gap back then (2026-10-24, 2026-10-25) is `MISSING`,
  not `not_due`. From 2026-10-31 onward they are due Mon-Fri only and their weekend gaps are `not_due`.
- **2026-10-31, 05:40-09:08 ET** — a faulty fleet edit briefly set the day-of-week field of
  **fourteen** weekday routines to `1` (Mondays only) instead of `1-5`, while their prompts and
  this roster still said Mon-Fri. It was repaired the same day, **before Monday 2026-11-02**, so
  **no routine missed a fire** and no audit-date exception applies: every `$AUDIT_DATE` from
  2026-11-02 onward is judged against the roster table below. If a prompt's SCHEDULE block says
  `1-5` but the scheduler field says `1`, the SCHEDULE block and this roster are the contract.

- **2026-10-31 / 2026-11-02** — three routines were ADDED, so they cannot be audited for
  earlier dates. **#91 (schedule-drift-guard, `5 4 * * *`, daily)** was created 2026-10-31 and
  has **no artifact** — it is a self-check like #90, so list its schedule but never check a path
  for it. **#92a (preopen-catalyst-capture, 08:30)** and **#92b (the 09:50 checkpoint)** were
  created 2026-11-02; both write `preopen-feed/{date}-{HHMM}.jsonl`, so the expected paths are
  `preopen-feed/{date}-0830.jsonl` and `preopen-feed/{date}-0950.jsonl` — **the time is part of
  the filename**, and a missing file at the wrong checkpoint time is a near-miss, not a gap.
  All three have **first fire 2026-11-03**. For `$AUDIT_DATE` before 2026-11-03 they are
  `not_yet_fired`, NOT `MISSING`.

- **2026-11-05** — **#17 (us-stocks-in-play) moved from ONE fire a day to TWO**: its schedule
  changed from `50 15 * * 1-5` to `50 9,15 * * 1-5` America/New_York, so the same task now fires
  at **09:50 ET** (the `open` slot) and **15:50 ET** (the `preclose` slot). **The two slots write
  DIFFERENT files** and both rows are in the roster table below:
  - `us-stocks-in-play/{date}-open.md` — the `open` slot (09:50 ET)
  - `us-stocks-in-play/{date}.md` — the `preclose` slot (15:50 ET), **unchanged**

  **The `open` slot's FIRST FIRE is 2026-11-05.** For `$AUDIT_DATE` **before 2026-11-05** the
  open artifact is `not_yet_fired`, NOT `MISSING` — nothing was ever supposed to write it.
  From 2026-11-05 onward a missing `us-stocks-in-play/<date>-open.md` IS `MISSING`.

  **Both slots push with the SAME commit subject**, `cron 17 us-stocks-in-play <date>` (it is
  derived from the artifact path, and the path prefix is the same for both). That is deliberate:
  the near-miss triage greps `grep -E "^[0-9a-f]+ cron (#)?17 "`, so a MISSING open artifact is
  triaged as "routine ran, wrote `<other path>` instead" rather than "routine never ran" — which
  is the correct reading. **Do not "fix" this by giving the open slot a custom `--msg`.**

  The two path patterns are DISJOINT: the preclose regex requires the date to be followed
  immediately by `.md`, so `<date>-open.md` does not satisfy it, and vice versa.

**Holiday note:** on a US market holiday the weekday-only routines still fire (the scheduler
knows nothing about holidays) but may legitimately skip inside their own window check. A missing
artifact on a holiday is `possible_holiday`, not a failure. The 2026 NYSE closures are in the
list below — check it before reporting a gap as a failure.

```
2025-01-01  2025-01-20  2025-02-17  2025-05-26
2025-06-19  2025-07-04  2025-09-01  2025-11-27
2025-12-25  2026-01-01  2026-01-19  2026-02-16
2026-05-25  2026-06-19  2026-07-03  2026-09-07
2026-11-26  2026-12-25  2027-01-01  2027-01-18
2027-02-15  2027-05-31  2027-06-18  2027-07-05
2027-09-06  2027-11-25  2027-12-24  2028-01-17
2028-02-21  2028-05-29  2028-06-19  2028-07-04
2028-09-04  2028-11-23  2028-12-25
```
(Half-days 07:00/13:00 ET are trading days and still report — do not skip them.)

## STEP 4 — CHECK EVERY ROUTINE

The roster below is the contract. For each routine, the expected artifact path is given with
`{date}` = `$AUDIT_DATE`. A routine is DUE if its schedule should have fired on `$AUDIT_DOW`
before this run; otherwise it is `not_due` and is not a gap.

| Routine | Schedule (ET) | Expected artifact on origin/main | Fires on |
|---|---|---|---|
| 01-weekly-mcp-health-check | `0 2 * * 0` | `mcp-health/{ISO-week}.md` | Sun |
| 19-earnings-reminder-daily | `0 6 * * 1-5` | `earnings/{date}-reminders.md` | Mon-Fri |
| 02-asia-pre-market-reactions | `30 6 * * 1-5` | `asia-pre-market/{date}.md` | Mon-Fri |
| 91-schedule-drift-guard | `5 4 * * *` | (no artifact — self-check routine) | every day |
| 90-delivery-auditor | `0 7 * * *` | (no artifact — this cron) | every day |
| 15-earnings-reaction-scanner | `0 8 * * 1-5` | `earnings/{date}-reactions.md` | Mon-Fri |
| 26-agentic-pre-market-brief | `30 8 * * 1-5` | `daily-briefs/{date}-pre-market.md` | Mon-Fri |
| 08-pre-market-gapper | `30 8 * * 1-5` | `daily-screens/{date}/pre-market-gapper.md` | Mon-Fri |
| 92a-preopen-catalyst-capture | `30 8 * * 1-5` | `preopen-feed/{date}-0830.jsonl` | Mon-Fri |
| 25-ntrt-gap-brief-daily | `0 9 * * 1-5` | `ntrt/{date}.md` | Mon-Fri |
| 07-focus-rvol-09:45 | `45 9 * * 1-5` | `daily-screens/{date}/focus-rvol-snapshot.md` | Mon-Fri |
| 92b-preopen-catalyst-capture | `50 9 * * 1-5` | `preopen-feed/{date}-0950.jsonl` | Mon-Fri |
| 17-us-stocks-in-play-open | `50 9 * * 1-5` | `us-stocks-in-play/{date}-open.md` | Mon-Fri |
| 12-cross-asset-correlation | `0 10 * * 1-5` | `cross-asset/{date}.md` | Mon-Fri |
| 10-breadth-snapshot | `0 14 * * 1-5` | `daily-screens/{date}/breadth-snapshot.md` | Mon-Fri |
| 13-macro-calendar-midweek | `0 14 * * 3` | `macro-calendar/{date}-midweek.md` | Wed |
| 14-macro-calendar-week-ahead | `0 15 * * 0` | `macro-calendar/{date}-week-ahead.md` | Sun |
| 06-pattern-study-backlog | `0 15 * * 6` | `daily-screens/{date}/weekly-ipo.md` | Sat |
| 17-us-stocks-in-play | `50 15 * * 1-5` | `us-stocks-in-play/{date}.md` | Mon-Fri |
| 04-reversal-bullish-3:55 | `55 15 * * 1-5` | `daily-screens/{date}/reversal-bullish-3:55.md` | Mon-Fri |
| 20-eod-watchlist-csv | `0 16 * * 1-5` | `us-eod/{date}.csv` | Mon-Fri |
| 05-eod-international-daily | `30 16 * * 1-5` | `international-eod/{date}` | Mon-Fri |
| 16-unusual-options-flow | `35 16 * * 1-5` | `options-flow/{date}.md` | Mon-Fri |
| 22-weekly-market-recap-preview | `47 17 * * 0` | `weekly/{date}-preview.md` | Sun |
| 09-daily-sweep-18:30 | `30 18 * * 1-5` | `daily-screens/{date}/daily-sweep.md` | Mon-Fri |
| 23-agentic-post-market-brief | `30 22 * * 1-5` | `daily-briefs/{date}-post-market.md` | Mon-Fri |

**#17 has TWO rows** because it fires twice a day from one task: the `open` row (09:50 ET,
`us-stocks-in-play/{date}-open.md`) and the `preclose` row (15:50 ET, `us-stocks-in-play/{date}.md`).
Check **both** paths on a Mon-Fri audit date from 2026-11-05 onward, and judge each on its own
schedule. A routine with two rows is still ONE routine for near-miss triage: both slots push with
the subject `cron 17 us-stocks-in-play <date>`.

**Two rows have no path and must never be checked for one:** `90-delivery-auditor` and
`91-schedule-drift-guard` are self-checks — they report in the chat and push nothing to the
artifact branch. Their rows are in the table so their schedules stay tracked, and that is all.
Checking `origin/main:(no artifact …)` would report a false `MISSING` every single day.

For `01-weekly-mcp-health-check` the path uses the **ISO week** of `$AUDIT_DATE`, not the date:
`mcp-health/$(date -d "$AUDIT_DATE" +%G-W%V).md`. It also appends a row to
`mcp-health/ledger.md`; the weekly report file is the one to check. #01's push commit carries no
`cron <NN>` prefix (its deployed prompt does not specify a commit title), so when you need its
commit match `mcp-health` in the subject instead of the NN prefix. It writes those two files and
nothing else, so there is no near-miss variant to hunt for: if the weekly report is absent,
#01 did not deliver.

**RECONSTRUCTED ARTIFACTS — a file that exists but was not produced by that date's run.**
`options-flow/2026-10-19.md` and `options-flow/2026-10-26.md` are reconstructions, not runs.
Both dates were due and both lost their scheduled run:

- **2026-10-19** — the 16:30 ET fire FAILED at the platform level: status 2,
  `CRON_EXECUTION_FAILED`, `[1406010011]:explicit model is not registered. cause: <nil>`. No
  session ever started.
- **2026-10-26** — the fire ran and the routine declined it. The task's schedule was 22:30 ET
  while its own `MARKET_HOURS_ONLY=true` window check demanded 09:00–16:00 ET, so the prompt
  exited `out-of-window: outside market hours (hour=22, expected 09-16 ET)` at 22:33 ET and
  pushed nothing. The same schedule-versus-gate contradiction was repaired on 2026-10-27 by
  moving the task to 16:35 ET.

Each file carries the **aggregate** layer (per-underlying option volume from Cboe's historical
options-data service, market-wide call/put and open interest from Cboe's daily market
statistics, underlying closes from Yahoo) and **no strike-level V/OI table at all** — expired
chains are not served by any reachable source. When either date falls in an audit window, label
it `reconstructed` and state the cause. Do not report either as `MISSING`: the path exists.

**WRITTEN_OFF — gaps the operator has accepted. Do NOT report these again.**
`WRITTEN_OFF="14-macro-calendar-week-ahead:2026-10-25"`
Format is `<routine>:<date>`. A gap whose routine AND date both match an entry here is **not a
finding**: record it in the top-level `written_off` array and move on. The operator accepted
this one deliberately. `WRITTEN_OFF` is a specific accepted gap; `not_yet_fired` (below) is a
routine whose current task has not yet had a fire opportunity. They are different things.

Check each expected path with `git cat-file -e`:

```bash
cd /workspace/.audit
for p in "asia-pre-market/$AUDIT_DATE.md" "earnings/$AUDIT_DATE-reminders.md"; do
  if git cat-file -e "origin/main:$p" 2>/dev/null; then echo "ok      $p"; else echo "MISSING $p"; fi
done
```

The `international-eod/{date}` path is a DIRECTORY of per-region CSVs — check that the
directory exists and contains at least one `.csv`; if it exists but is empty, that is
`present_but_empty` (a degraded run wrote a stub), which still needs reporting.

**Near-miss triage — do this for every `MISSING`.** A `MISSING` path does not always mean the
routine did not run: it may have written its artifact under a slightly different name (cron #10
wrote `breadth.md` while this table expected `breadth-snapshot.md`, and the routine looked
"broken" for days). Before reporting `MISSING`, establish whether **that routine** pushed
anything for `$AUDIT_DATE` — attribute by COMMIT, never by directory.

**Do NOT hunt for a near-miss by listing the output directory.** Several routines share one
directory: `daily-screens/{date}/` holds files from #04, #06, #07, #09 and #10. On 2026-10-29
#07's `focus-rvol-snapshot.md` was missing while #09's `focus.md` sat in the same directory — a
directory listing would have reported "routine ran, wrote focus.md instead", which is false: #07
pushed nothing that day. Attribute by the routine's OWN commit instead:

```bash
cd /workspace/.audit
# usage: triage.sh <NN> <AUDIT_DATE>
# NN = the two digits at the start of the routine's name in the roster table (07, 25, 09, ...)
NN="$1"; AUDIT_DATE="$2"
git log --format="%h %s" origin/main --grep="$AUDIT_DATE" \
  | grep -E "^[0-9a-f]+ cron (#)?$NN " | head -5
```

Every routine's push commit is titled `cron <NN> <name> <date>` (a couple use `cron #<NN>`), so
this returns the commits that routine made on the audited date — and only those.

- **The routine pushed something for `$AUDIT_DATE`** → it ran and wrote to a different path.
  Report the gap with that near-miss named — "routine ran, wrote `<path>` instead of `<path>`" —
  because the fix is a path correction, not a re-run. List what it actually wrote with
  `git show --stat <sha>`.
- **The routine pushed nothing for `$AUDIT_DATE`** → it genuinely did not deliver. Say exactly
  that, and never name another routine's file as a near-miss.

## STEP 4b — STALE-ROUTINE CHECK (catches routines that never fire)

The check in STEP 4 is **relative to the audited day**. It answers "did today's due routines
land?" and is therefore blind to a routine whose schedule is wrong in a way that makes it *never*
due on the days the auditor looks. Cron #22 ran for months with a schedule that contradicted its
own window check: it skipped every single fire and produced no artifact, and the auditor never
flagged it because on the audited day it was simply `not_due`. (#22's schedule has since been
fixed to `47 17 * * 0`; its first fire under the new schedule is 2026-11-01 — see the SCHEDULE
CHANGES block. Before that date an empty `weekly/` is expected, not a finding.)

This step closes that hole. It is **absolute**, not relative: for every routine in the roster,
find the most recent artifact that exists on `origin/main`, and compare its date against the
routine's own schedule. A routine that should have produced something in the last N days but whose
newest artifact is older than that is **stale** — regardless of whether it was due on
`$AUDIT_DATE`.

```bash
cd /workspace/.audit
# Each entry is: routine|path-regex|tolerance-days
# The path regex is ANCHORED to the real artifact layout on origin/main - a loose
# substring match silently matches nothing and reports a healthy routine as NEVER_DELIVERED.
# tolerance: 5 = daily or Mon-Fri routine (covers a Fri->Mon weekend gap)
#            7 = weekly routine (01 Sun, 06 Sat, 13 Wed, 14 Sun, 22 Sun)
# Why 7 and not 9: a weekly routine fires every 7 days and this audit runs DAILY, so a
# healthy weekly routine's age oscillates 0,1,2,3,4,5,6 and NEVER exceeds 6. A tolerance of
# 7 therefore cannot false-positive on a healthy weekly routine, while a MISSED fire shows
# up as age 8 one day later. A tolerance of 9 delayed every weekly finding by 3 days - that
# is how #14's missed Sunday 2026-10-25 stayed invisible for a whole cycle.
# Do NOT collapse this to one global tolerance: a single global 5 flags every weekly
# routine as stale on the sixth day after its last run - a guaranteed false positive.
# A routine whose CURRENT schedule has not reached its first fire yet is EXPECTED to be
# absent. That is `not_yet_fired`, not a finding. Keep this list in sync with the
# SCHEDULE CHANGES block above; it is empty for every routine that has already fired.
# 14-macro-calendar-week-ahead is here for the same reason as 22: its live task
# (457172664209611) was created 2026-10-28 02:09 ET, AFTER the last Sunday (2026-10-25),
# so it has had ZERO scheduled fire opportunities and cron_read view=runs returns 0 runs.
# Its first fire is 2026-11-01 15:00 ET. The 2026-10-25 miss under the PRIOR task
# instance is a SEPARATE historical gap (a lost push race) and is not a stale finding.
# VERIFICATION DEADLINE: if macro-calendar/2026-11-01-week-ahead.md is absent after
# 2026-11-01 16:00 ET, that IS this failure mode recurring and must be escalated.
NOT_YET_FIRED="22-weekly-market-recap-preview:2026-11-01 14-macro-calendar-week-ahead:2026-11-01 91-schedule-drift-guard:2026-11-03 92a-preopen-catalyst-capture:2026-11-03 92b-preopen-catalyst-capture:2026-11-03 17-us-stocks-in-play-open:2026-11-05"
for entry in \
  "01-weekly-mcp-health-check|^mcp-health/[0-9]{4}-W[0-9]{2}\.md$|7" \
  "02-asia-pre-market-reactions|^asia-pre-market/[0-9]{4}-[0-9]{2}-[0-9]{2}\.md$|5" \
  "19-earnings-reminder-daily|^earnings/[0-9]{4}-[0-9]{2}-[0-9]{2}-reminders\.md$|5" \
  "15-earnings-reaction-scanner|^earnings/[0-9]{4}-[0-9]{2}-[0-9]{2}-reactions\.md$|5" \
  "26-agentic-pre-market-brief|^daily-briefs/[0-9]{4}-[0-9]{2}-[0-9]{2}-pre-market\.md$|5" \
  "08-pre-market-gapper|^daily-screens/[0-9]{4}-[0-9]{2}-[0-9]{2}/pre-market-gapper\.md$|5" \
  "25-ntrt-gap-brief-daily|^ntrt/[0-9]{4}-[0-9]{2}-[0-9]{2}\.md$|5" \
  "07-focus-rvol-09:45|^daily-screens/[0-9]{4}-[0-9]{2}-[0-9]{2}/focus-rvol-snapshot\.md$|5" \
  "92a-preopen-catalyst-capture|^preopen-feed/[0-9]{4}-[0-9]{2}-[0-9]{2}-0830\.jsonl$|5" \
  "92b-preopen-catalyst-capture|^preopen-feed/[0-9]{4}-[0-9]{2}-[0-9]{2}-0950\.jsonl$|5" \
  "12-cross-asset-correlation|^cross-asset/[0-9]{4}-[0-9]{2}-[0-9]{2}\.md$|5" \
  "10-breadth-snapshot|^daily-screens/[0-9]{4}-[0-9]{2}-[0-9]{2}/breadth-snapshot\.md$|5" \
  "13-macro-calendar-midweek|^macro-calendar/[0-9]{4}-[0-9]{2}-[0-9]{2}-midweek\.md$|7" \
  "14-macro-calendar-week-ahead|^macro-calendar/[0-9]{4}-[0-9]{2}-[0-9]{2}-week-ahead\.md$|7" \
  "06-pattern-study-backlog|^daily-screens/[0-9]{4}-[0-9]{2}-[0-9]{2}/weekly-ipo\.md$|7" \
  "17-us-stocks-in-play|^us-stocks-in-play/[0-9]{4}-[0-9]{2}-[0-9]{2}\.md$|5" \
  "17-us-stocks-in-play-open|^us-stocks-in-play/[0-9]{4}-[0-9]{2}-[0-9]{2}-open\.md$|5" \
  "04-reversal-bullish-3:55|^daily-screens/[0-9]{4}-[0-9]{2}-[0-9]{2}/reversal-bullish-3:55\.md$|5" \
  "20-eod-watchlist-csv|^us-eod/[0-9]{4}-[0-9]{2}-[0-9]{2}\.csv$|5" \
  "05-eod-international-daily|^international-eod/[0-9]{4}-[0-9]{2}-[0-9]{2}/[a-z]{2}(-[a-z]{2})?\.csv$|5" \
  "16-unusual-options-flow|^options-flow/[0-9]{4}-[0-9]{2}-[0-9]{2}\.md$|5" \
  "22-weekly-market-recap-preview|^weekly/[0-9]{4}-[0-9]{2}-[0-9]{2}-preview\.md$|7" \
  "09-daily-sweep-18:30|^daily-screens/[0-9]{4}-[0-9]{2}-[0-9]{2}/daily-sweep\.md$|5" \
  "23-agentic-post-market-brief|^daily-briefs/[0-9]{4}-[0-9]{2}-[0-9]{2}-post-market\.md$|5" ; do
  routine="${entry%%|*}"; rest="${entry#*|}"; pat="${rest%%|*}"; tol="${rest##*|}"
  firstfire=""
  for nf in $NOT_YET_FIRED; do
    if [ "${nf%%:*}" = "$routine" ]; then firstfire="${nf##*:}"; fi
  done
  if [ -n "$firstfire" ] && [ "$(date -d "$AUDIT_DATE" +%s)" -lt "$(date -d "$firstfire" +%s)" ]; then
    echo "ok     $routine  not_yet_fired (first fire $firstfire - not a finding)"
    continue
  fi
  last=$(git ls-tree -r --name-only origin/main \
         | grep -E "$pat" \
         | grep -oE '[0-9]{4}-[0-9]{2}-[0-9]{2}|[0-9]{4}-W[0-9]{2}' | sort -u | tail -1)
  # A WEEK token names the ISO week of the Sunday the routine ran. Jan 4 of a year always falls
  # in ISO week 1, so the Sunday of week w is Jan 4 + (w-1)*7 days. Plain date arithmetic only:
  # `date -d "2026-W44"` is not portable and fails on some coreutils builds.
  case "$last" in
    *-W*) last=$(date -d "$(date -d "${last%%-W*}-01-04" +%F) +$(( (${last##*-W} - 1) * 7 )) days" +%F) ;;
  esac
  if [ -z "$last" ]; then
    echo "STALE  $routine  NEVER_DELIVERED  (no artifact matching '$pat' on origin/main)"
  else
    age=$(( ( $(date -d "$AUDIT_DATE" +%s) - $(date -d "$last" +%s) ) / 86400 ))
    if [ "$age" -gt "$tol" ]; then
      echo "STALE  $routine  last=$last  age=${age}d  (>$tol)"
    fi
  fi
done
```

**How to read the output:**
- `not_yet_fired (first fire <date>)` — the routine's current schedule has not reached its
  first fire yet. Expected, NOT a finding, and not a gap. (#22 and #14 before 2026-11-01.)
- `NEVER_DELIVERED` — the routine has produced nothing at all, ever, AND its first fire date
  has already passed. **Report it as `MISSING`**, not as a separate label: a routine that
  has had its chance and produced no artifact IS missing.
- `last=... age=Nd` — the routine produced something once, then stopped. Also report as `MISSING`
  with the last date included, so the operator can see *when* it went quiet.
- Nothing printed — the routine is within tolerance. Not a finding.

**Cadence:** the threshold is PER ROUTINE and is carried in the third field of each entry above
(`routine|path-regex|tolerance`). Daily and Mon-Fri routines use **5** (which covers a Fri->Mon
weekend gap); the weekly routines (01 Sun, 06 Sat, 13 Wed, 14 Sun, 22 Sun) use **7** — a healthy weekly
routine's age oscillates 0..6 because this audit runs daily, so 7 can never false-positive and a
missed fire appears as age 8 one day later. A routine listed as "every day" uses **5** — it
fires seven days a week, so a gap of more than 5 days is never legitimate.
**Do not collapse this back to one global tolerance value.** A single global 5 flags every
weekly routine as stale on the sixth day after its last run — a guaranteed false positive that
would train the operator to ignore this check.
The path regexes are ANCHORED to the real layout on `origin/main`, because a loose substring
match matches nothing and reports a healthy routine as `NEVER_DELIVERED`. If a routine starts
writing somewhere new, fix the regex in this prompt rather than loosening it to a substring.

**Interaction with STEP 4:** the two checks are complementary, not redundant. STEP 4 finds
"due today, did not land" (a delivery or push failure). STEP 4b finds "not landing for days"
(a schedule or window-check failure). A routine can fail either way independently. Report both.

## STEP 4c — DIAGNOSE A GAP (why did the routine not deliver?)

A `MISSING` artifact has at least three very different causes, and the operator needs the right
one. Do NOT stop at "MISSING" — name the cause in the gap's reason.

**How to get it:**

```bash
# 1. the run that was supposed to fire for $AUDIT_DATE, and the session it created
#    (cron_read view=runs needs the task_id; cron_read view=list gives the task_id map)
# 2. that session's status_message:
session_list agent_name="Mavis" limit=100
```

`session_list` returns every recent conversation with its `title`, `status` and `status_message`.
A healthy run has `status_message: ""`. A run killed by the billing quota carries
`"The Token Plan usage limit has been reached ... (2067)"`.

**Two ways to read a session's `status_message`.** `session_list agent_name="Mavis" limit=100`
returns every recent conversation with its `title`, `status` and `status_message` in ONE call —
use it to scan several routines at once. `session_get session_id="<id>"` reads ONE session
directly and is the precise path when you already have the id from `cron_read view=runs`; pass
the id as a **quoted string** (verified working 2026-11-02 on six sessions). `session_update` and
`session_messages` still reject a numeric id. (`cron_read`'s `task_id` is not affected — numeric
task ids pass fine.)

### 4c-0 — IS THE ROSTER TABLE STILL TRUE?

The roster table below is a **copy**, and it is this auditor's only statement of what should have
run. The live scheduler is NOT the reference — a web-GUI save can collapse its day-of-week field
(cron #91 `schedule-drift-guard` repairs that at 04:05 ET, before this audit runs). **The ground
truth is the reference:** `tools/schedule-ground-truth.json` in `karizaco/maxhermes-migration`,
rebuilt from `migration-state.json` (the original local cron list).

```bash
# --- fetch tools/schedule-ground-truth.json ---
# The CONTENTS API is authoritative and is NOT CDN-cached. The two CDNs cache `main`
# independently: measured 2026-11-04, raw.githubusercontent served a STALE blob for >17
# minutes after a push while jsDelivr was fresh. The OLD `[ -s file ] || curl` loop could
# NEVER reach its fallback - the first successful download satisfied the guard, so the
# second URL was DEAD CODE. Now all three are tried, and a 404 body (non-empty JSON) is
# rejected on its BODY, not on its byte count.
S=/workspace/schedule-ground-truth.json
for U in \
  "https://api.github.com/repos/karizaco/maxhermes-migration/contents/tools/schedule-ground-truth.json?ref=main" \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/tools/schedule-ground-truth.json" \
  "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/tools/schedule-ground-truth.json" ; do
  curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" \
    -H "Authorization: Bearer ${GITHUB_TOKEN}" -o "$S.tmp" "$U" 2>/dev/null
  if [ -s "$S.tmp" ] && ! head -c 200 "$S.tmp" | grep -q '"message"'; then
    mv -f "$S.tmp" "$S"; break
  fi
  rm -f "$S.tmp"
done
```

Compare each roster row's `Schedule (ET)` column with the ground-truth entry for the same
routine. If they differ, the TABLE is stale — report it:

    gap: <routine> ROSTER_DESYNC <ground truth> (table says <table schedule>)

A `ROSTER_DESYNC` is a finding even when no artifact is missing: every due/not_due decision made
from a stale table is suspect. If the ground truth cannot be fetched, say so once (`errors: 1`)
and carry on with the table — never guess a schedule.

Also remember: `status: 1` on a run in `cron_read view=runs` is only the TRIGGER outcome — it
means the run was dispatched, not that the session succeeded. `status: 2` on a session means the
session ended in an error; `status: 0` is a healthy session.

Classify every gap with its cause:

| Evidence | Cause | Report as |
|---|---|---|
| No run at all for that routine on `$AUDIT_DATE`, and no session with that routine's title | it never fired | `MISSING` — reason: never fired |
| A session for that routine on `$AUDIT_DATE` whose `status_message` contains `2067` | the Token Plan quota wall | `MISSING` — reason: quota exhausted (2067) |
| A session for that routine on `$AUDIT_DATE` with a different non-empty `status_message` | the run failed | `MISSING` — reason: <that message> |
| A healthy session, but the routine's own commit is absent for `$AUDIT_DATE` | the push silently failed | `MISSING` — reason: push failed (session healthy) |

Only the third and fourth cases are a bug in the routine itself. A quota death is a billing
problem, and a routine that never fired is usually a scheduler problem — say which, because the
fix is different.

## STEP 5 — CLASSIFY EVERY GAP

For each gap, pick exactly one label:

| Label | Meaning |
|---|---|
| `MISSING` | Due, expected, and the artifact is not on `origin/main`. **This is the important one.** |
| `possible_holiday` | Due, expected, and `$AUDIT_DATE` is a US market holiday. |
| `weekend_no_us_session` | Due, expected, and `$AUDIT_DATE` was a weekend. |
| `not_due` | The schedule does not fire on `$AUDIT_DOW`. Not a gap. |
| `present_but_empty` | The path exists but carries no data (a stub was pushed). |
| `stale` | The artifact exists but is from an older date than expected. |
| `never_delivered` | STEP 4b: the routine has produced no artifact **at all**, ever, and its first fire date has already passed. Equivalent to MISSING — report it as MISSING with this detail in the reason. |
| `not_yet_fired` | The routine's current schedule has not reached its first fire date yet (see the SCHEDULE CHANGES block). Expected, not a failure. NOT a gap — record it in the top-level `not_yet_fired` array, never in `gaps`. |
| `partial` | The artifact exists for the right date but a second expected file for that routine is absent. |
| `written_off` | The operator accepted this gap (see `WRITTEN_OFF`). NOT a finding — record it in the top-level `written_off` array, never in `gaps`. |
| `roster_desync` | The roster table's schedule differs from the GROUND TRUTH (STEP 4c-0). The ground truth wins. |
| `reconstructed` | The artifact exists at the expected path but was rebuilt after the fact from archival sources, not produced by that date's scheduled run. The file says so in its title and its section 0. NOT a MISSING — but NOT a clean delivery either: report it, name the date and the cause of the original loss, and say which layer (aggregate vs strike-level) the file carries. Currently `options-flow/2026-10-19.md` and `options-flow/2026-10-26.md` are the only two. |

## STEP 6 — WRITE THE STATUS FILE

Write `/workspace/_audit/status.json` (create the dir) — NOT into the outputs repo. This is a
local status file; it must not be pushed to `karizaco/minimax-cloud-outputs`, because the
outputs repo holds artifacts, not audit state.

```json
{
  "audit_date_et": "2026-10-27",
  "audit_run_et": "2026-10-28T07:00:00-04:00",
  "origin_main_sha": "abc1234",
  "due": 18,
  "delivered": 16,
  "missing": 1,
  "stale_routines": 0,
  "never_delivered": [],
  "not_yet_fired": [],
  "written_off": [],
  "gaps": [
    {"routine": "12-cross-asset-correlation", "path": "cross-asset/2026-10-27.md", "label": "MISSING", "cause": "quota exhausted (2067)"}
  ],
  "audit_status": "ok" | "gaps_found" | "failed_no_repo"
}
```

`not_yet_fired` lists routines whose first fire date has not arrived yet. They are NOT gaps:
they never appear in `gaps` and never affect `audit_status`.
`written_off` lists gaps the operator accepted — NOT findings; they never affect `audit_status`.
`roster_desync` IS a finding: it means the roster table is wrong, so report it even when no
artifact is missing.
`audit_status` is `gaps_found` when any gap has label `MISSING`, `present_but_empty` or
`roster_desync`, and `ok` otherwise. A `reconstructed` gap does **not** change `audit_status` — the
path exists and the date is covered — but it is always reported in `gaps` and named in the reply,
so a rebuilt file is never mistaken for a clean run. A `MISSING` gap is a genuine, actionable finding — name the routine and the
exact path so it can be reproduced.

## GIT PUSH (OPTIONAL)

Push the status file to a SEPARATE branch so the audit trail is preserved without polluting the
artifact branch. **Never push to `main`** — that is the artifact branch, and this cron has no
artifact to contribute to it.

```bash
B=https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared
for F in push_artifact.sh verify_delivery.sh; do
  D=/workspace/$F
  for U in \
    "https://api.github.com/repos/karizaco/maxhermes-migration/contents/cloud-prompts/_shared/$F?ref=main" \
    "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/$F" \
    "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/$F" ; do
    curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" \
      -H "Authorization: Bearer ${GITHUB_TOKEN}" -o "$D.tmp" "$U" 2>/dev/null
    if [ -s "$D.tmp" ] && ! head -c 200 "$D.tmp" | grep -q '"message"' \
       && head -1 "$D.tmp" 2>/dev/null | grep -q '^#!'; then
      mv -f "$D.tmp" "$D"; break
    fi
    rm -f "$D.tmp"
  done
  [ -s "$D" ] || echo "$F fetch FAILED - the DELIVERY step cannot verify its own push"
done
# Recompute AUDIT_DATE HERE: this is a separate shell from the one that set it in STEP 3, so a
# variable set there does not survive into this block.
AUDIT_DATE=$(TZ=America/New_York date -d "yesterday" +%Y-%m-%d)
sh /workspace/push_artifact.sh --out _audit --add _audit/status.json --branch audit/status \
   --msg "cron 90 delivery-auditor $AUDIT_DATE"
sh /workspace/verify_delivery.sh --path _audit/status.json --branch audit/status
```

**The target branch is `audit/status`, not `main`** — the status file lives on its own branch so
the audit trail does not pollute the artifact branch. The shared script takes the branch as a
parameter, which is why one implementation serves both this routine and the 21 that push to
`main`.

**CRITICAL — never use `git add -A` here.** Stage ONLY `_audit/status.json`. A blanket add
stages every other file on the branch as DELETED (measured 2026-10-25: 283 files wiped).
**Never `git push --force`.** The push target is the `audit/status` branch, not `main`.

## DELIVERY VERIFICATION (MANDATORY - do this after the push block)

`push_artifact.sh` reports `push: ok` when the path is **present** on the remote branch — that is
an **existence** check. The stronger check is `verify_delivery.sh`, which compares the SHA-256 of
the remote blob against the local file — and it is **fetched by the block above**, because a
helper that is only *called* is not on disk. Always run it:

```bash
sh /workspace/verify_delivery.sh --path _audit/status.json --branch audit/status
```

A `git push` that exits 0 is **not** proof of delivery — a push piped into `head` returns head's
exit status (always 0) and reports a rejected push as a success. That is why the delivery check
exists, and why the push script must never be run with `git push … | head -3`.

## DELIVERY

**This routine is one of the three documented reply-format exceptions** (see
`cloud-prompts/cron-prompts/README.md`): its output is machine-read, so it does NOT use the
standard prose-opener / `### Signal` / `### Method & caveats` format. It MUST be:

  - ≤ 8 lines.
  - One line: `audit: <AUDIT_DATE> due=<n> delivered=<n> missing=<n>`
  - One line per gap: `gap: <routine> <label> <path> — <cause>` (the cause comes from STEP 4c;
    omit the cause only when it could not be determined)
  - One line: `push: ok (verified)` / `push: skipped (token unset)` / `push: FAILED (<reason>)`
  - One line: `errors: <n>` — count of audit errors. 0 = clean audit.

**If there are no gaps, say so in one line and stop.** Do not pad the reply with counts of
routines that are `not_due` — those are working as designed, not news.

No preamble. Tool call → result → write → push → reply.

## CRITICAL REMINDERS
1. **This cron is read-only with respect to the artifacts.** It clones, checks, writes a local
   status file, and optionally pushes to the `audit/status` branch. It never modifies, deletes
   or re-pushes any routine's artifact, and it never pushes to `main`. Its ONLY write to the
   repo is a fast-forward of the `master` branch pointer to `main` (see STEP 2) - that moves
   a ref, it does not touch a file.
2. **A gap is a finding, not a failure of this run.** Do not attempt to re-run, re-create, or
   repair the missing artifact. Report it precisely — routine, label, exact path — and stop.
   The user decides what to do about it.
3. **Never report a routine as `MISSING` when its schedule does not fire on that weekday.**
   Check the "Fires on" column and the holiday list before labelling anything. For audit dates
   before 2026-10-29, #15 and #19 were Mondays-only, and before 2026-10-31, #07/#10/#12/#17/#26
   were daily — see the SCHEDULE CHANGES block above. The roster table below is the contract for
   every date from 2026-10-31 onward.
4. **Name the cause of every gap** (STEP 4c). "MISSING" alone is not an answer; "quota
   exhausted (2067)" and "push failed" need different fixes.
5. **Do not fabricate a status.** If the repo could not be cloned, the status is
   `failed_no_repo` and `errors: 1`. If the token is missing, `skipped_no_token`.
6. **Run the STEP 4b stale check every time.** A routine that is `not_due` on the audited
   day may still be permanently broken — that is exactly how cron #22 went unnoticed for
   months. `NEVER_DELIVERED` is a MISSING finding, not a footnote — unless the routine's
   first fire date has not arrived yet (`not_yet_fired`), which is not a finding at all.
7. **A `MISSING` artifact on a day when the routine ran and reported success means the push
   silently failed** — the old `git add -A` block could stage deletions and abort, or the
   `|| echo` could mask the error. Name it clearly; that is the whole point of this cron.

================================================================
END OF CRON PROMPT
================================================================