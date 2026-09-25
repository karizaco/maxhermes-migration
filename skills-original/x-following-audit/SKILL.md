---
name: X following audit
description: >-
  Weekly audit of X (Twitter) following list via the `karizaco/x_unsub` extension.
  Reads the latest export, scores a short unfollow proposal, waits for explicit
  user approval before anything irreversible. Replaces the paused
  `x-following-weekly-audit-paused` Grok routine.
---

# X following audit via x_unsub

Weekly propose-only audit of the X following list using the **karizaco/x_unsub** extension. Replaces the paused `x-following-weekly-audit-paused` Grok routine.

## When

- Cron: `0 10 * * 0` Asia/Bangkok (Sunday 10:00 BKK = Sunday 03:00 UTC)
- Manual: user asks "audit my X follows" or "who should I unfollow?"

## Cost rule

Extension does the heavy scan. Mavis only babysits, reads the export, scores a **short** unfollow proposal, and waits for explicit user approval. Never deep-open hundreds of profiles in the browser.

## Output

- `C:\Users\admin\.minimax\projects\coding-shared\research\x-unsub\YYYY-MM-DD-audit.md` — proposal file
- Append audit line: `audit_run target=x-unsub:<date>` to `research/logs/audit.log`

## Steps

### 1. Locate the latest export

Look for files matching `research/x-unsub/*.json` or `*.csv` (any export the user or extension dropped there). Accept any of:

- `research/x-unsub/scan-YYYY-MM-DD-HHMM-*.json`
- `research/x-unsub/scan-YYYY-MM-DD-HHMM-*.csv`
- A path the user mentions in chat

If none found → write a short "no export found" file and ping the user:
- Reminder to start a scan in the x_unsub extension
- Save `YYYY-MM-DD-no-export.md` and stop.

### 2. Parse the export

Expected fields (based on x_unsub extension's known schema — verify against actual file):

- `handle` (or `username` or `screen_name`)
- `display_name` (optional)
- `followers`, `following`, `tweets_count`
- `last_post_date` or `last_tweet_at`
- `verified` (bool)
- `mutual` (bool, optional)
- `inactive` flag if extension provides one

Be defensive: missing fields → skip that account rather than crash.

### 3. Score

Default ranking (lower score = better unfollow candidate):

- `+100` if `last_post_date` is more than 365 days ago
- `+50` if more than 180 days ago
- `+20` if `followers < 100` AND not in user's standing watchlist
- `+30` if `tweets_count < 50` overall
- `-100` if `verified` AND matches keywords like `crypto|stock|trading|official|news|...` (likely a real account worth keeping — but also check activity)
- `-50` if `mutual == true` and last_post within 90 days
- `-200` if matches an explicit "always keep" list in `research/x-unsub/keepers.txt` (if file exists)

Sort ascending by score. Take top 20 (user can ask for more).

### 4. Deliver

Write `YYYY-MM-DD-audit.md` with:

- Header: scan timestamp, total scanned, time range of export
- Top 20 unfollow candidates (handle, score, reason)
- Optional: "keepers worth noting" — high-scoring follows the user might want to engage with more
- Footer: explicit ask for batch approval. **Never auto-execute.**

### 5. Optional assistance

If user confirms they're at their computer with x_unsub loaded:

- Open x.com in a Playwright session (if Playwright is installed; otherwise ask the user to drive).
- Confirm extension loaded and signed in.
- Trigger scan only if user explicitly says "start scan now".
- When scan completes, re-export and re-run scoring from step 2.

## Hard rules

- **Never auto-unfollow.** Propose a shortlist; unfollow only after user approves the batch.
- Stay on `x.com` / `twitter.com` following-audit UI only — no DMs, posts, likes, bookmarks, settings, or password changes.
- Soft-stop on CAPTCHA, login wall, rate-limit, unexpected navigation, or missing extension/session.
- Cap proposals at top 20 per run unless the user asks otherwise.
- Do not deep-open hundreds of profiles — use export-first, score-only on the dataset.

## Out of scope

- Circleboom or other API bulk unfollow tools.
- Replacing the extension with Playwright profile crawling.
- DMs, posts, replies, likes, bookmarks — read-only audit only.
