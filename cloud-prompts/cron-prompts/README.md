# Cloud Mavis Cron Prompts — index and operating notes

**26 routines** (24 producers + the #90 auditor + the #91 drift guard), all owned by `Mavis`, all `America/New_York`, all `MiniMax-M3.1-Flash`,
all `session.mode=new`. Day-of-week lives in the **scheduler** expression, so weekend fires cost
nothing — no agent invocation is spent discovering it is a weekend.

> **This index is GENERATED — do not hand-edit it.** `tools/gen_index.py` rebuilds both the
> table and the routine count from `tools/schedule-ground-truth.json` (the authoritative schedules)
> plus the live scheduler (project ids) and `tools/gen_roster.py`'s artifact map:
>
> ```bash
> python3 tools/gen_index.py --tasks <cron_read view=list json>   # rewrite
> python3 tools/gen_index.py --tasks <cron_read view=list json> --check   # exit 1 if stale
> ```
>
> A hand-kept table is a table that lies: it sat at "21 routines" while the fleet was 23, listed
> five Mon-Fri routines as "every day", and omitted #01 and #91 entirely until 2026-11-02. See
> `cron-prompts/ROSTER.md` for the machine-generated roster with last-delivered dates
> (`tools/gen_roster.py`).

## Cron index

| ID | Routine | Schedule (ET) | Fires on | Project | Output |
|---|---|---|---|---|---|
| 01 | weekly-mcp-health-check | `0 2 * * 0` | Sun | 14002 | `mcp-health/ledger.md` + `mcp-health/YYYY-Wnn.md` |
| 91 | schedule-drift-guard | `5 4 * * *` | every day | 14002 | none (writes no artifact) |
| 19 | earnings-reminder-daily | `0 6 * * 1-5` | Mon-Fri | 13835 | `earnings/{date}-reminders.md` |
| 02 | asia-pre-market-reactions | `30 6 * * 1-5` | Mon-Fri | 10645 | `asia-pre-market/{date}.md` |
| 90 | delivery-auditor | `0 7 * * *` | every day | 14002 | `_audit/status.json` (audit/status branch) |
| 15 | earnings-reaction-scanner | `0 8 * * 1-5` | Mon-Fri | 13835 | `earnings/{date}-reactions.md` |
| 26 | agentic-pre-market-brief | `30 8 * * 1-5` | Mon-Fri | 10645 | `daily-briefs/{date}-pre-market.md` |
| 92a | preopen-catalyst-capture-0830 | `30 8 * * 1-5` | Mon-Fri | 10645 | — |
| 08 | stock-screener-pre-market-gapper | `34 8 * * 1-5` | Mon-Fri | 10645 | `daily-screens/{date}/pre-market-gapper.md` |
| 25 | ntrt-gap-brief-daily | `0 9 * * 1-5` | Mon-Fri | 10645 | `ntrt/{date}.md` |
| 26b | agentic-pre-market-brief-refresh-0920 | `20 9 * * 1-5` | Mon-Fri | 10645 | `daily-briefs/{date}-pre-market-refresh.md` |
| 07 | stock-screener-focus-rvol-09:45 | `45 9 * * 1-5` | Mon-Fri | 10635 | `daily-screens/{date}/focus-rvol-snapshot.md` |
| 92b | preopen-catalyst-capture-0950 | `50 9 * * 1-5` | Mon-Fri | 10645 | — |
| 12 | cross-asset-correlation-snapshot | `0 10 * * 1-5` | Mon-Fri | 10636 | `cross-asset/{date}.md` |
| 10 | stock-screener-breadth-snapshot | `0 14 * * 1-5` | Mon-Fri | 10635 | `daily-screens/{date}/breadth-snapshot.md` |
| 13 | macro-calendar-midweek | `0 14 * * 3` | Wed | 10636 | `macro-calendar/{date}-midweek.md` |
| 06 | stock-screener-pattern-study-backlog | `0 15 * * 6` | Sat | 10635 | `daily-screens/{date}/weekly-ipo.md` |
| 14 | macro-calendar-week-ahead | `0 15 * * 0` | Sun | 10636 | `macro-calendar/{date}-week-ahead.md` |
| 04 | reversal-bullish-3:55 | `55 15 * * 1-5` | Mon-Fri | 10635 | `daily-screens/{date}/reversal-bullish-3_55.md` |
| 20 | eod-watchlist-csv-snapshot | `0 16 * * 1-5` | Mon-Fri | 10638 | `us-eod/{date}.csv` |
| 05 | eod-international-daily | `30 16 * * 1-5` | Mon-Fri | 10638 | `international-eod/{date}/` |
| 16 | unusual-options-flow-daily | `35 16 * * 1-5` | Mon-Fri | 13832 | `options-flow/{date}.md` |
| 22 | weekly-market-recap-preview | `47 17 * * 0` | Sun | 10636 | `weekly/{date}-preview.md` |
| 09 | stock-screener-daily-sweep-18:30 | `30 18 * * 1-5` | Mon-Fri | 10635 | `daily-screens/{date}/daily-sweep.md` |
| 23 | agentic-post-market-brief | `30 22 * * 1-5` | Mon-Fri | 10638 | `daily-briefs/{date}-post-market.md` |
| 17 | us-stocks-in-play | `50 9,15 * * 1-5` | Mon-Fri | 13832 | `us-stocks-in-play/{date}.md` |

## Common contract (every prompt)

- **Credential handling**: `${GITHUB_TOKEN}` only; never a literal PAT. Token unset → skip the push,
  write the artifact, reply.
- **Data sources**: the `mcp__*` tool names are NOT registered in this runtime. The MCP *servers* are
  reachable over plain HTTPS JSON-RPC via `_shared/mcp_bridge.py`. **Yahoo JSON availability varies
  by egress** — it was 429 on 2026-10-28 and 200 on 2026-10-31, and on 2026-11-02 one cron session
  got 429 while another got 200. Try it, fall through on 429/401, and never report it as a standing
  fact. The bridge's `market-recap`, the TradingView scanner, `web_search` (separate egress) and the
  Nasdaq API work reliably. Full endpoint list + measured status: `_shared/RUNTIME-CONTRACT.md`.
- **Zero-fallback policy**: every fallback terminates with stop-and-write. No deeper MCP chains.
- **Helper scripts**: local Windows Python helpers do not exist on Cloud. Re-implement inline; fetch
  the helper source for reference only.
- **Output**: `/workspace/<path>` (Linux paths, no backslashes).
- **Git push**: worktree at `origin/main`, `git add <own-dir>` only, 3-attempt race retry, then a
  mandatory `git cat-file` delivery check. A push that reports success but lands nothing is worse
  than a push that fails loudly.

## Reply format (no line cap)

The reply is a short, readable digest, not a wall of text. There is **no line cap**: cap by NAMES
SHOWN (top ~8 per tier), not by lines, and let the artifact file hold the long detail.

**Five routines are documented exceptions**, each because its output is machine-read rather than
read by a human — do not "fix" them to the standard form:
- `#07` — a fixed seven-line status line (window / upstream / tickers / alerts / file / push / errors).
- `#90` — a ≤ 8-line audit digest.
- `#01` — under 10 lines unless something changed.
- `#92a` / `#92b` — under 6 lines each (checkpoint, records written, push, errors).

This list is the single source of truth for the exceptions, and it is mirrored in
`cloud-prompts/_shared/PROMPT-BLOCKS.md` — which most routines download at run time. If you add
an exception here, add it there too, or the routine that reads only the shared file will
"normalise" itself back to the standard format.

**Five routines do NOT download `PROMPT-BLOCKS.md`** — `#01`, `#26b`, `#90`, `#92a`, `#92b` —
so for them the exception list above is the only place it is written, and they each carry their
own reply format in their own prompt. Two of those five (`#26b`, `#90`) also fetch the shared
helpers themselves rather than getting them from the shared block; see
`docs/IMPROVEMENTS-2026-11-04-fetch-ladder-and-memory-routing.md`.

```
2-4 sentence prose opener (headline finding + the caveat that changes how it should be read)

### Signal
tiered bullets, one ticker per line, each a short clause naming the catalyst

### Method & caveats
2-4 bullets: source(s), lag, screen size, degraded/blocked sources

### Files
one line per file written

### Push / errors
push: ok (verified) | skipped (token unset) | FAILED (<reason>)
errors: <n>
```

## Repository rules (read before pushing)

- **Push to `main`, never `master`.** `master` is the repo's **default branch** (GitHub's
  `default_branch` cannot be changed without repo Administration scope), so a plain `git clone`
  lands there. `master` is kept as a **fast-forward mirror of `main`** — the auditor
  (`#90`) advances it daily, and it holds the same commits, so a clone still sees current
  artifacts. Always `git fetch origin main` explicitly.
- **Never `git add -A`.** In a fresh sandbox the working tree lacks the rest of the repo, so a blanket
  add stages every other file as DELETED. Cron #12 did exactly that on 2026-10-25 (commit
  `1356a03`) and deleted 283 files belonging to eight other crons.
- **Never `git push --force`.**
- **One owner per output directory.** `_regime.json` was written by both #10 and #09 and silently
  clobbered; #10 now writes `_regime-intraday.json`.
- **Auditor #90 writes to the `audit/status` branch**, never `main`.

## Known hazards

- **Push collisions.** Routines that share a fire minute push to the same branch; the loser is
  rejected and its artifact is lost. As of 2026-10-29 the only pair that still shares a fire
  minute AND a weekday is **08:30 #08 / #26** and **14:00 #10 / #13 (Wednesdays only)**.
  #05/#16 were staggered to 16:30 / 16:35. The 15:00 pair (#06 Sat, #14 Sun) never collides —
  different days. The retry loop in every prompt is the safety net, not the fix.
- **The auditor is blind to a routine that never fires** — it compared only against the audited
  day. STEP 4b (added 2026-10-29) does an absolute last-delivered check, which is what catches
  the #22 class of failure.
- **Loose path matching silently reports healthy routines as broken.** A substring match on a
  shared directory (earnings/, macro-calendar/, daily-screens/) picks up a sibling routine's
  dates, or matches nothing and reports `NEVER_DELIVERED`. Both the auditor and
  `tools/gen_roster.py` now anchor on a per-routine filename suffix.
- **Quota.** Runs die with `Token Plan usage limit reached (2067)` when the account plan is
  exhausted. No prompt edit fixes that.

## Open findings (2026-10-30)

| Routine | Finding | Evidence |
|---|---|---|
| `22-weekly-market-recap-preview` | **Has never delivered.** No `weekly/` directory exists on `origin/main` at all. Under its current `47 17 * * 0` (Sun 17:47 ET) schedule its **first fire is 2026-11-01**, so an empty `weekly/` is expected until then — the auditor labels it `not_yet_fired`, not `MISSING`. | `git ls-tree -r --name-only origin/main -- weekly` returns 0 files |
| `14-macro-calendar-week-ahead` | **Missed its Sunday 2026-10-25 run.** Newest artifact is 2026-10-18; there is no `2026-10-25-week-ahead.md`. The auditor's weekend rule previously hid this by labelling it `weekend_no_us_session`; weekend-due routines are now audited as due. | `macro-calendar/2026-10-18-week-ahead.md` is the newest |
| `15` / `19` | Were scheduled Mondays-only (`0 8 * * 1`, `0 6 * * 1`) while their prompts and skill specs said weekdays. **Fixed 2026-10-29** to `1-5`. The auditor carries an effective-date rule so pre-change Tue-Fri gaps read as `not_due`, not `MISSING`. | their last artifact was 2026-10-26, a Monday |
| `#05` / `#17` / `#22` / `#23` | **Recreated by a concurrent session on 2026-10-30** with new task_ids and new project assignments, and the recreate was pasted from an **older prompt revision** — it dropped the `## Source health` bold-close fix, the "Audit is not needed here" clause, and (for #23) the helper-script detail. #05, #17 and #23 are restored from this repo; #22's platform text was semantically identical, so the repo follows the platform there. | task_id changed between two `cron_read` snapshots; SHA-256 differed from the repo |
| `#90` | **Recreated by the same concurrent session on 2026-10-30** — new task_id `457957802930526` and a **new project `14002`** (the auditor had been in 10638). The prompt text is byte-identical to this repo. The old task_id `457193486962916` is dead. | `cron_read` snapshots before/after the recreation |
| `#08` / `#25` | **Recreated by a concurrent session on 2026-10-29** (task_ids `457578163015913` / `457578106761360`) and partially reverted at 06:57, dropping the TLS-fallback hardening. Both restored from this repo. The old task_ids `457170128208215` / `457175059497201` are dead. | task_id changed between two `cron_read` snapshots |
| `07` | Two prompt files existed with identical content (`...-09:45.md` and `...-09%3A45.md`). **Resolved 2026-10-29** — the `%3A` twin was deleted; the decoded `...-09:45.md` is canonical and matches the README, the roster and the generator. | the repo now has one `07-` file |
| whole fleet | **A concurrent session is writing to the same crons.** It pushed repo commits of its own (an auditor weekend-blind-spot fix, a reply-format migration) and created a `Scout`-owned one-shot reminder asserting cron #04 had a stray 09:00 ET fire — **false**, #04 fires 15:55 ET and the 09:00 slot belongs to #25. Treat any fleet change that did not come from this repo's git history as unverified. | `cron_read` snapshots 05:19 vs 07:07 ET on 10-29 showed different task_ids and prompt bodies |

The outputs repo's `default_branch` is still `master`, because GitHub's `default_branch` cannot be
changed without repo Administration scope and the PAT does not have it. **This is now mitigated
rather than outstanding:** `master` is a fast-forward mirror of `main` (same commits), so a plain
`git clone` lands on current artifacts, and the auditor advances the mirror daily so it cannot
drift.

**Re-aligned 2026-11-02.** `master` had diverged: it carried two merge commits (`8bdb2d0`,
`2d5e9da`) that `main` did not, so it could not be fast-forwarded, and it was missing every
artifact delivered since 2026-10-30. Verified before touching it — every file on `master` also
existed on `main`, and `main` was one file ahead; the two extra commits were merges of `main` into
`master` and carried no unique content. `master` was then advanced to `main`
(`--force-with-lease`, with `backup/master-pre-tidy-2026-11-02` kept as a rollback point) and the
31 skip markers were archived to `refs/skipped-markers/` first. A plain `git clone` now lands on
the current commit instead of a tree 86 files short. Setting the default branch to `main` by hand (Settings → Branches → Default branch) would
still be tidier — and the auditor's mirror step becomes a no-op on its own.