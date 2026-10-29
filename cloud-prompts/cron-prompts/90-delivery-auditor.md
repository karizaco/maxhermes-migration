# Cloud Mavis cron: delivery-auditor (cron #90)

You are running as a Cloud Mavis cron. No local filesystem, no PowerShell, no Windows paths.
Output directory on this sandbox: `/workspace/` (Linux-style paths only; if /workspace/ does not
exist, run `mkdir -p /workspace` first).

## SCHEDULE
- Deployed schedule: `0 7 * * *` America/New_York — 07:00 ET daily.
- Runs at 07:00 ET, which is AFTER every routine that fires before it (the earliest is 06:00 ET,
  #02) and BEFORE the routines that fire later in the day. It therefore catches the whole
  previous US trading day's early-morning artifacts, and the routines that fire between 07:00
  and 22:30 are audited by the NEXT day's run.
- Session mode: `new` — every fire starts a clean conversation.

## WHAT THIS CRON IS FOR

Every other routine verifies **its own** delivery (`git cat-file -e "origin/main:<path>"`).
That is necessary but not sufficient: **a routine that never fires cannot verify itself.**
Cron #22 ran for months with a schedule that contradicted its own window check — it skipped
every single fire and never produced a single artifact, and nothing noticed. The per-run check
is blind to exactly that failure mode.

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
# NOTE: origin/HEAD points at the stale `master` branch. Always fetch `main` explicitly.
rm -rf /workspace/.audit
git worktree add -f /workspace/.audit origin/main
cd /workspace/.audit
git rev-parse --short origin/main | sed 's/^/  origin\/main = /'
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

If `$AUDIT_DATE` was a **Saturday or Sunday** (`AUDIT_DOW` 6 or 7), there is no US session to
audit — the weekday-only routines (`1-5`) correctly did not run, and #26/#12/#07/#17/#10/#22
may or may not have run. Still report, but expect gaps and label them
`weekend_no_us_session` rather than `MISSING`.

**Holiday note:** on a US market holiday the weekday-only routines still fire (the scheduler
knows nothing about holidays) but may legitimately skip inside their own window check. A missing
artifact on a holiday is `possible_holiday`, not a failure. The 2026 NYSE closures are in the
list below — check it before reporting a gap as a failure.

```
2026-01-01  2026-01-19  2026-02-16  2026-04-03  2026-05-25  2026-06-19
2026-07-03  2026-09-07  2026-11-26  2026-12-25
```
(Half-days 07:00/13:00 ET are trading days and still report — do not skip them.)

## STEP 4 — CHECK EVERY ROUTINE

The roster below is the contract. For each routine, the expected artifact path is given with
`{date}` = `$AUDIT_DATE`. A routine is DUE if its schedule should have fired on `$AUDIT_DOW`
before this run; otherwise it is `not_due` and is not a gap.

| Routine | Schedule (ET) | Expected artifact on origin/main | Fires on |
|---|---|---|---|
| 02-asia-pre-market-reactions | `30 6 * * 1-5` | `asia-pre-market/{date}.md` | Mon-Fri |
| 19-earnings-reminder-daily | `0 6 * * 1` | `earnings/{date}-reminders.md` | Mon |
| 15-earnings-reaction-scanner | `0 8 * * 1` | `earnings/{date}-reactions.md` | Mon |
| 26-agentic-pre-market-brief | `30 8 * * *` | `daily-briefs/{date}-pre-market.md` | every day |
| 08-pre-market-gapper | `30 8 * * 1-5` | `daily-screens/{date}/pre-market-gapper.md` | Mon-Fri |
| 25-ntrt-gap-brief-daily | `0 9 * * 1-5` | `ntrt/{date}.md` | Mon-Fri |
| 07-focus-rvol-09:45 | `45 9 * * *` | `daily-screens/{date}/focus-rvol-snapshot.md` | every day |
| 12-cross-asset-correlation | `0 10 * * *` | `cross-asset/{date}.md` | every day |
| 10-breadth-snapshot | `0 14 * * *` | `daily-screens/{date}/breadth-snapshot.md` | every day |
| 13-macro-calendar-midweek | `0 14 * * 3` | `macro-calendar/{date}-midweek.md` | Wed |
| 14-macro-calendar-week-ahead | `0 15 * * 0` | `macro-calendar/{date}-week-ahead.md` | Sun |
| 06-pattern-study-backlog | `0 15 * * 6` | `daily-screens/{date}/weekly-ipo.md` | Sat |
| 17-us-stocks-in-play | `50 15 * * *` | `us-stocks-in-play/{date}.md` | every day |
| 04-reversal-bullish-3:55 | `55 15 * * 1-5` | `daily-screens/{date}/reversal-bullish-3:55.md` | Mon-Fri |
| 20-eod-watchlist-csv | `0 16 * * 1-5` | `us-eod/{date}.csv` | Mon-Fri |
| 05-eod-international-daily | `30 16 * * 1-5` | `international-eod/{date}` | Mon-Fri |
| 16-unusual-options-flow | `35 16 * * 1-5` | `options-flow/{date}.md` | Mon-Fri |
| 22-weekly-market-recap-preview | `47 17 * * 0` | `weekly/{date}-preview.md` | Sun |
| 09-daily-sweep-18:30 | `30 18 * * 1-5` | `daily-screens/{date}/daily-sweep.md` | Mon-Fri |
| 23-agentic-post-market-brief | `30 22 * * 1-5` | `daily-briefs/{date}-post-market.md` | Mon-Fri |

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

## STEP 4b — STALE-ROUTINE CHECK (catches routines that never fire)

The check in STEP 4 is **relative to the audited day**. It answers "did today's due routines
land?" and is therefore blind to a routine whose schedule is wrong in a way that makes it *never*
due on the days the auditor looks. Cron #22 ran for months with a schedule that contradicted its
own window check: it skipped every single fire and produced no artifact, and the auditor never
flagged it because on the audited day it was simply `not_due`.

This step closes that hole. It is **absolute**, not relative: for every routine in the roster,
find the most recent artifact that exists on `origin/main`, and compare its date against the
routine's own schedule. A routine that should have produced something in the last N days but whose
newest artifact is older than that is **stale** — regardless of whether it was due on
`$AUDIT_DATE`.

```bash
cd /workspace/.audit
# STALE_DAYS = how long a routine may go without producing an artifact.
# 5 covers a weekend (Fri->Mon) for a weekday-only routine; 9 covers a weekly routine's gap.
STALE_DAYS=5
for entry in \
  "02-asia-pre-market-reactions|asia-pre-market" \
  "19-earnings-reminder-daily|earnings-reminders" \
  "15-earnings-reaction-scanner|earnings-reactions" \
  "26-agentic-pre-market-brief|daily-briefs-pre-market" \
  "08-pre-market-gapper|daily-screens-pre-market-gapper" \
  "25-ntrt-gap-brief-daily|ntrt" \
  "07-focus-rvol-09:45|focus-rvol-snapshot" \
  "12-cross-asset-correlation|cross-asset" \
  "10-breadth-snapshot|breadth-snapshot" \
  "13-macro-calendar-midweek|macro-calendar-midweek" \
  "14-macro-calendar-week-ahead|macro-calendar-week-ahead" \
  "06-pattern-study-backlog|weekly-ipo" \
  "17-us-stocks-in-play|us-stocks-in-play" \
  "04-reversal-bullish-3:55|reversal-bullish" \
  "20-eod-watchlist-csv|us-eod" \
  "05-eod-international-daily|international-eod" \
  "16-unusual-options-flow|options-flow" \
  "22-weekly-market-recap-preview|weekly-preview" \
  "09-daily-sweep-18:30|daily-sweep" \
  "23-agentic-post-market-brief|daily-briefs-post-market" ; do
  routine="${entry%%|*}"; pat="${entry##*|}"
  last=$(git ls-tree -r --name-only origin/main \
         | grep -E "/${pat}[^/]*\.(md|csv|json)$|^${pat}[^/]*\.(md|csv|json)$" \
         | grep -oE '[0-9]{4}-[0-9]{2}-[0-9]{2}' | sort -u | tail -1)
  if [ -z "$last" ]; then
    echo "STALE  $routine  NEVER_DELIVERED  (no artifact matching '$pat' on origin/main)"
  else
    age=$(( ( $(date -d "$AUDIT_DATE" +%s) - $(date -d "$last" +%s) ) / 86400 ))
    if [ "$age" -gt "$STALE_DAYS" ]; then
      echo "STALE  $routine  last=$last  age=${age}d  (>$STALE_DAYS)"
    fi
  fi
done
```

**How to read the output:**
- `NEVER_DELIVERED` — the routine has produced nothing at all, ever. This is the #22 failure
  mode. **Report it as `MISSING`**, not as a separate label: a routine that has never produced an
  artifact IS missing.
- `last=... age=Nd` — the routine produced something once, then stopped. Also report as `MISSING`
  with the last date included, so the operator can see *when* it went quiet.
- Nothing printed — the routine is within tolerance. Not a finding.

**Cadence:** apply this to routines whose "Fires on" is Mon-Fri with `STALE_DAYS=5`; for the
weekly routines (06 Sat, 13 Wed, 14 Sun, 22 Sun) use `STALE_DAYS=9` so a legitimate weekly gap is
not reported. Compute the threshold per routine from its "Fires on" column, not one global value.

**Interaction with STEP 4:** the two checks are complementary, not redundant. STEP 4 finds
"due today, did not land" (a delivery or push failure). STEP 4b finds "not landing for days"
(a schedule or window-check failure). A routine can fail either way independently. Report both.

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
| `never_delivered` | STEP 4b: the routine has produced no artifact **at all**, ever. Equivalent to MISSING — report it as MISSING with this detail in the reason. |
| `partial` | The artifact exists for the right date but a second expected file for that routine is absent. |

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
  "gaps": [
    {"routine": "12-cross-asset-correlation", "path": "cross-asset/2026-10-27.md", "label": "MISSING"}
  ],
  "audit_status": "ok" | "gaps_found" | "failed_no_repo"
}
```

`audit_status` is `gaps_found` when any gap has label `MISSING` or `present_but_empty`, and
`ok` otherwise. A `MISSING` gap is a genuine, actionable finding — name the routine and the
exact path so it can be reproduced.

## GIT PUSH (OPTIONAL)

Push the status file to a SEPARATE branch so the audit trail is preserved without polluting the
artifact branch. **Never push to `main`** — that is the artifact branch, and this cron has no
artifact to contribute to it.

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
mkdir -p /workspace/.wt/_audit
cp /workspace/_audit/status.json /workspace/.wt/_audit/status.json
cd /workspace/.wt
git add _audit/status.json
STAGED=$(git status --short)
if [ -z "$STAGED" ]; then
  echo "push: ABORTED (nothing staged)"
elif echo "$STAGED" | grep -q '^\s*D'; then
  echo "push: ABORTED (staged deletions detected — refusing to push)"
else
  git commit -q -m "audit $AUDIT_DATE" || echo "nothing to commit"
  git push -q origin HEAD:refs/heads/audit/status 2>&1 | head -3
fi
```

**CRITICAL — never use `git add -A` here.** Stage ONLY `_audit/status.json`. A blanket add
stages every other file on the branch as DELETED.
**Never `git push --force`.** The push target is the `audit/status` branch, not `main`.

## DELIVERY VERIFICATION (MANDATORY)

```bash
cd /workspace/.wt 2>/dev/null || cd /workspace
export DATE=$(TZ=America/New_York date +%Y-%m-%d)
git fetch -q origin audit/status
if git cat-file -e "origin/audit/status:_audit/status.json" 2>/dev/null; then
  echo "DELIVERY: ok (audit/status:_audit/status.json present)"
else
  echo "DELIVERY: FAILED (audit/status:_audit/status.json NOT found)"
fi
```

## DELIVERY
The final reply (the only thing delivered to the chat) MUST be:
  - ≤ 8 lines.
  - One line: `audit: <AUDIT_DATE> due=<n> delivered=<n> missing=<n>`
  - One line per gap: `gap: <routine> <label> <path>`
  - One line: `push: ok (verified)` / `push: skipped (token unset)` / `push: FAILED (<reason>)`
  - One line: `errors: <n>` — count of audit errors. 0 = clean audit.

**If there are no gaps, say so in one line and stop.** Do not pad the reply with counts of
routines that are `not_due` — those are working as designed, not news.

No preamble. Tool call → result → write → push → reply.

## CRITICAL REMINDERS
1. **This cron is read-only with respect to the artifacts.** It clones, checks, writes a local
   status file, and optionally pushes to the `audit/status` branch. It never modifies, deletes
   or re-pushes any routine's artifact, and it never pushes to `main`.
2. **A gap is a finding, not a failure of this run.** Do not attempt to re-run, re-create, or
   repair the missing artifact. Report it precisely — routine, label, exact path — and stop.
   The user decides what to do about it.
3. **Never report a routine as `MISSING` when its schedule does not fire on that weekday.**
   Check the "Fires on" column and the holiday list before labelling anything.
4. **Do not fabricate a status.** If the repo could not be cloned, the status is
   `failed_no_repo` and `errors: 1`. If the token is missing, `skipped_no_token`.
5. **Run the STEP 4b stale check every time.** A routine that is `not_due` on the audited
   day may still be permanently broken — that is exactly how cron #22 went unnoticed for
   months. `NEVER_DELIVERED` is a MISSING finding, not a footnote.
6. **A `MISSING` artifact on a day when the routine ran and reported success means the push
   silently failed** — the old `git add -A` block could stage deletions and abort, or the
   `|| echo` could mask the error. Name it clearly; that is the whole point of this cron.

================================================================
END OF CRON PROMPT
================================================================
