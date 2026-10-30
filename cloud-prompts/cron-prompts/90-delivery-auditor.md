# Cloud Mavis cron: delivery-auditor (cron #90)

You are running as a Cloud Mavis cron. No local filesystem, no PowerShell, no Windows paths.
Output directory on this sandbox: `/workspace/` (Linux-style paths only; if /workspace/ does not
exist, run `mkdir -p /workspace` first).

## SCHEDULE
- Deployed schedule: `0 7 * * *` America/New_York — 07:00 ET daily.
- Runs at 07:00 ET, which is AFTER every routine that fires before it (the earliest is 06:00 ET,
  #19) and BEFORE the routines that fire later in the day. It therefore catches the whole
  previous US trading day's early-morning artifacts, and the routines that fire between 07:00
  and 22:30 are audited by the NEXT day's run.
- Session mode: `new` — every fire starts a clean conversation.

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

**Weekend audit dates — audit the routines that ARE due on that weekend.**
If `$AUDIT_DATE` was a **Saturday or Sunday** (`$AUDIT_DOW` 6 or 7), there is no US *weekday*
session: the Mon-Fri routines (`1-5`) correctly did not run, and their gaps are
`weekend_no_us_session` (NOT `MISSING`).

But a routine whose OWN schedule fires on that weekend day IS due and MUST be audited on it —
its absence is `MISSING`, not `weekend_no_us_session`:

| Audited day | Routine that IS due | Schedule |
|---|---|---|
| Saturday (`$AUDIT_DOW` 6) | 06-pattern-study-backlog | `0 15 * * 6` |
| Sunday (`$AUDIT_DOW` 7) | 14-macro-calendar-week-ahead | `0 15 * * 0` |
| Sunday (`$AUDIT_DOW` 7) | 22-weekly-market-recap-preview | `47 17 * * 0` |

**This is the failure mode that hid #14 for a whole cycle.** #14 skipped its Sunday 2026-10-25
fire; `macro-calendar/2026-10-25-week-ahead.md` was never on `origin/main`; and the Monday
audit of Sunday 2026-10-25 labelled it `weekend_no_us_session` — "expected, not a failure" —
so the gap stayed invisible. `weekend_no_us_session` applies ONLY to routines that were NOT
scheduled to fire on that weekday. Check the "Fires on" column before labelling anything.

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
| 19-earnings-reminder-daily | `0 6 * * 1-5` | `earnings/{date}-reminders.md` | Mon-Fri |
| 02-asia-pre-market-reactions | `30 6 * * 1-5` | `asia-pre-market/{date}.md` | Mon-Fri |
| 90-delivery-auditor | `0 7 * * *` | (no artifact — this cron) | every day |
| 15-earnings-reaction-scanner | `0 8 * * 1-5` | `earnings/{date}-reactions.md` | Mon-Fri |
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
#            7 = weekly routine (06 Sat, 13 Wed, 14 Sun, 22 Sun)
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
NOT_YET_FIRED="22-weekly-market-recap-preview:2026-11-01"
for entry in \
  "02-asia-pre-market-reactions|^asia-pre-market/[0-9]{4}-[0-9]{2}-[0-9]{2}\.md$|5" \
  "19-earnings-reminder-daily|^earnings/[0-9]{4}-[0-9]{2}-[0-9]{2}-reminders\.md$|5" \
  "15-earnings-reaction-scanner|^earnings/[0-9]{4}-[0-9]{2}-[0-9]{2}-reactions\.md$|5" \
  "26-agentic-pre-market-brief|^daily-briefs/[0-9]{4}-[0-9]{2}-[0-9]{2}-pre-market\.md$|5" \
  "08-pre-market-gapper|^daily-screens/[0-9]{4}-[0-9]{2}-[0-9]{2}/pre-market-gapper\.md$|5" \
  "25-ntrt-gap-brief-daily|^ntrt/[0-9]{4}-[0-9]{2}-[0-9]{2}\.md$|5" \
  "07-focus-rvol-09:45|^daily-screens/[0-9]{4}-[0-9]{2}-[0-9]{2}/focus-rvol-snapshot\.md$|5" \
  "12-cross-asset-correlation|^cross-asset/[0-9]{4}-[0-9]{2}-[0-9]{2}\.md$|5" \
  "10-breadth-snapshot|^daily-screens/[0-9]{4}-[0-9]{2}-[0-9]{2}/breadth-snapshot\.md$|5" \
  "13-macro-calendar-midweek|^macro-calendar/[0-9]{4}-[0-9]{2}-[0-9]{2}-midweek\.md$|7" \
  "14-macro-calendar-week-ahead|^macro-calendar/[0-9]{4}-[0-9]{2}-[0-9]{2}-week-ahead\.md$|7" \
  "06-pattern-study-backlog|^daily-screens/[0-9]{4}-[0-9]{2}-[0-9]{2}/weekly-ipo\.md$|7" \
  "17-us-stocks-in-play|^us-stocks-in-play/[0-9]{4}-[0-9]{2}-[0-9]{2}\.md$|5" \
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
         | grep -oE '[0-9]{4}-[0-9]{2}-[0-9]{2}' | sort -u | tail -1)
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
  first fire yet. Expected, NOT a finding, and not a gap. (#22 before 2026-11-01.)
- `NEVER_DELIVERED` — the routine has produced nothing at all, ever, AND its first fire date
  has already passed. **Report it as `MISSING`**, not as a separate label: a routine that has
  had its chance and produced no artifact IS missing.
- `last=... age=Nd` — the routine produced something once, then stopped. Also report as `MISSING`
  with the last date included, so the operator can see *when* it went quiet.
- Nothing printed — the routine is within tolerance. Not a finding.

**Cadence:** the threshold is PER ROUTINE and is carried in the third field of each entry above
(`routine|path-regex|tolerance`). Daily and Mon-Fri routines use **5** (which covers a Fri->Mon
weekend gap); the weekly routines (06 Sat, 13 Wed, 14 Sun, 22 Sun) use **7** — a healthy weekly
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
  "gaps": [
    {"routine": "12-cross-asset-correlation", "path": "cross-asset/2026-10-27.md", "label": "MISSING"}
  ],
  "audit_status": "ok" | "gaps_found" | "failed_no_repo"
}
```

`not_yet_fired` lists routines whose first fire date has not arrived yet. They are NOT gaps:
they never appear in `gaps` and never affect `audit_status`.
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
   Check the "Fires on" column and the holiday list before labelling anything. For audit dates
   before 2026-10-29, #15 and #19 were Mondays-only — see the SCHEDULE CHANGES block above.
4. **Do not fabricate a status.** If the repo could not be cloned, the status is
   `failed_no_repo` and `errors: 1`. If the token is missing, `skipped_no_token`.
5. **Run the STEP 4b stale check every time.** A routine that is `not_due` on the audited
   day may still be permanently broken — that is exactly how cron #22 went unnoticed for
   months. `NEVER_DELIVERED` is a MISSING finding, not a footnote — unless the routine's
   first fire date has not arrived yet (`not_yet_fired`), which is not a finding at all.
6. **A `MISSING` artifact on a day when the routine ran and reported success means the push
   silently failed** — the old `git add -A` block could stage deletions and abort, or the
   `|| echo` could mask the error. Name it clearly; that is the whole point of this cron.

================================================================
END OF CRON PROMPT
================================================================