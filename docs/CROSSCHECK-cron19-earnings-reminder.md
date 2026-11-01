# Cross-check — cron #19 earnings-reminder-daily

Reviewed 2026-11-01 against the deployed task and the artifacts it actually produced during the
week the hardening was live (2026-10-26 → 2026-10-30).

**Method:** read the deployed task with `cron_read`, diff the live prompt against the repo
source-of-truth, then test each of the ten improvements against evidence in the artifacts the
hardened prompt produced — not against the prompt's own claims.

---

## Verdict per improvement

| # | Improvement | Verdict | Evidence |
|---|---|---|---|
| 1 | Stop advertising MCPs that don't exist | **Verified** | Live prompt says the `mcp__*` tools "DO NOT EXIST in this runtime". All three artifacts report `status: ok` with no MCP probing and no phantom `errors:` count. |
| 2 | Fix the destructive `git add -A` push | **Verified, with one repeat** | Live prompt: 0 occurrences of `git add -A`, scoped `git add <dir>`, a 3-attempt race-retry loop, and a staged-deletion abort guard. **But** cron #12's *old* task still had the old recipe and deleted 498 files again on 2026-10-26. |
| 3 | Never push from a stale base | **Verified** | The race-retry loop re-fetches `origin/main` and rebuilds the worktree from the new tip on every attempt. Delivery-verification block added to the fleet and present in the live prompt. |
| 4 | Resolve the watchlist leg | **Verified** | 10-26 states the omission once in prose and ships no empty table; 10-29 and 10-30 drop the section entirely. No artifact carries an empty watchlist table any more. |
| 5 | Fix the schedule | **Verified** | `fire_time_et` is 06:00 / 06:00 / 06:02 on 10-26, 10-29, 10-30. Deployed `0 6 * * 1-5` America/New_York. |
| 6 | Add a market-holiday gate | **Verified** | Live prompt carries the 10 NYSE 2026 closures, checked against nyse.com. Half-days explicitly excluded from the skip. |
| 7 | Verify dates against company sources | **Verified** | 10-29 confirmed 32 of 74 names against company releases / IR pages / 8-K filings on EDGAR and recorded three tight checks (ARES, EPD, XEL — pre-filed embargoed 8-Ks that an EDGAR timestamp alone would misread as Oct 28). 10-30 excluded **Bayer** (Q3 dated 3 Nov, confirmed on bayer.com) and checked Standard Chartered. |
| 8 | Verify S&P 500 membership against a live list | **Verified, but my rule had a hole** | All three runs parse the MediaWiki wikitext, not the rendered HTML, and cross-check controls. **The 10-30 run found a real defect in my own Rule A** — see below. |
| 9 | Reconcile conflicting market caps/EPS | **Verified** | All three artifacts carry a `Rule C` conflicts section with a per-ticker source/spread/resolution table, and the prose flags what it changes about how to read the roster. |
| 10 | Make the artifact self-describing | **Verified** | All three carry front matter (`date`, `fire_time_et`, `snapshot_et`, `source`, `primary_source`, `status`, `pending_count`, `already_reported_count`) and a `Status` column with `pending` / `reported`. |

Nine of ten were working as designed on live data. The tenth was working but was carrying a defect
in the rule I wrote, which the 10-30 run caught on its own.

---

## Defect found in my own Rule A — fixed 2026-11-01

The 10-30 run independently discovered that the constituent parse I specified was **wrong**.

Cboe Global Markets is written `{{BZX link|CBOE}}` in the Wikipedia wikitext, not
`{{NyseSymbol|…}}` or `{{NasdaqSymbol|…}}`. My regex therefore matched 502 symbols and silently
**dropped CBOE** — a genuine S&P 500 constituent, which the run then wrongly excluded from the
roster. The run caught it by cross-checking against an independent CSV, noticed the CSV still
listed MMM (3M, which left the index in 2024), and reported both.

Re-verified directly against the wikitext today:

| Parse | Symbols | CBOE present? |
|---|---|---|
| `NyseSymbol\|NasdaqSymbol` (my original Rule A) | 502 | **no** |
| `NyseSymbol\|NasdaqSymbol\|BZX link` (corrected) | **503** | yes |

The corrected parse matches the independent CSV exactly (zero differences either way) and all five
control tickers — `BRK.B`, `GOOGL`, `GOOG`, `FOX`, `CBOE` — are present. The template inventory
confirms `BZX link` is the only other symbol-carrying template (1 use); `cite web`, `Short
description`, `for`, `Use American English`, `Use mdy dates`, `portal` are the only other
templates and none carries a ticker.

**Applied:** corrected Rule A is now in the live deployed task, the repo cron prompt, and the
skill's `SKILL.md`, each with the 503-symbol expectation, the five-ticker control check, and a
warning that the `datasets/s-and-p-500-companies` CSV is stale and is a cross-check only, never
the authority.

---

## Two things that were wrong outside this routine

### Cron #12 deleted 498 files again on 2026-10-26

Commit `7730357` (cron #12, 2026-10-26) used the old unscoped `git add -A` recipe and deleted 498
files — the same failure mode as `1356a03` five days earlier. My repo fix did not reach cron #12's
*deployed* task, which still held the old prompt.

The fleet has since recreated cron #12 (task `457172664209609`), and its live prompt now carries
the safe worktree recipe with the deletion guard. **The failure mode is closed going forward**, but
it is worth stating that a repo-side prompt fix does not by itself change a deployed task — each
`cron_update` is a separate deployment step.

Recovered: 10 `SKIPPED_*` audit records (cron #5, #16, #17, #19 across 2026-10-03/04/11/18/24) in
commit `e651b82`. The remaining "missing" files are sandbox scratch (`.plugin-cache/`,
`.skills/`) that a later commit deliberately untracked, plus one-off helper scripts and zips.

### Cron #19 missed 2026-10-27 and 2026-10-28 entirely

The task was deleted from the scheduler and recreated on 2026-10-29 under a new id
(`457569978294401`), so no fire happened on those two trading days. Every other routine produced
output on both dates — the gap was cron #19-specific, caused by the task replacement rather than
by a data or push failure.

**Backfilled.** `earnings/2026-10-27-reminders.md` (38 names) and
`earnings/2026-10-28-reminders.md` (34 names) are reconstructed from published calendars and
labelled `status: backfilled_missed_run`. Both carry an explicit retrospective framing: they are
after-the-fact records, so `Status` is `reported` throughout and the pre-open state is not
recoverable. Missing estimate cells are left blank rather than invented.

---

## Fleet state after the incident — healthy

Every artifact directory is well above its pre-incident size, and no cron-19 artifact has been
lost since the restore:

| Directory | Pre-incident (2026-10-25) | Now |
|---|---|---|
| `daily-screens/` | 109 | 385 |
| `us-eod/` | 72 | 114 |
| `earnings/` | 8 | 18 |
| `international-eod/` | 13 | 98 |
| `daily-briefs/` | 6 | 19 |
| `ntrt/` | 6 | 50 |
| `us-stocks-in-play/` | 9 | 23 |
| `options-flow/` | 5 | 9 |
| `refs/` | 5 | 7 |

## Config now in force for cron #19

- **Task** `457569978294401` (agent Mavis, project 13835)
- **Schedule** `0 6 * * 1-5`, timezone `America/New_York` — 06:00 ET, Mon–Fri
- **Session** `new` — one clean conversation per fire
- **Next fire** 2026-11-02 06:00 Mon ET (EST — DST ends 2026-11-01, so the local fire time is
  unchanged)
- **Prompt** carries: holiday gate, the runtime data-source contract with the MCP bridge as the
  primary path, corrected Rule A, Rule B date verification, Rule C conflict reconciliation,
  front-matter + `Status` output spec, worktree push with race retry and deletion guard, and
  mandatory delivery verification.

## Still open

- **The watchlist itself.** No watchlist file exists in any reachable location, so the cron reports
  the omission rather than populating it. Publishing one to the outputs repo would close
  improvement #4 properly; I could not find a source to publish.
- **Task-id churn.** The fleet recreates tasks regularly (`roster.json` is the current map, and it
  warns not to hard-code ids). The 10-27/10-28 hole was caused by exactly this. The repo's
  `cron-prompts/roster.json` is regenerated from the live scheduler, which is the right mitigation,
  but the gap between a task disappearing and being replaced is still unguarded.
