# Cron prompt remediation — implementation record

**Branch:** `feature/cron-prompt-hygiene` in `karizaco/maxhermes-migration`, merged to `main`
and **deleted on 2026-11-03**. The branch carried nothing that `main` did not already have —
its tip `8642a99` is a strict ancestor of `main` — and that same commit is preserved by the tag
`pre-cron5-format-2026-11-03`, which remains the rollback point for the pre-cron5 format
change. Restoring the branch, if ever needed:
`git push origin 8642a99:refs/heads/feature/cron-prompt-hygiene`.
**Date:** 2026-11-02.
**Scope:** the 13 work packages of `IMPLEMENTATION-PLAN.md`.
**Final state:** commit `0dd8822` on `main`; all **23/23** prompts deployed to the live scheduler
and verified byte-identical (SHA-256) against their repo blobs, with **no non-prompt field
changed** on any task.

This is the record of what was actually changed, in what order, and what was verified. It is
written to be auditable: every claim below was checked against the files, and the checks are named.

---

## 1. Why this ran at all

The 2026-11-02 audit found that **the repo was not what the fleet was running**. 21 of 23
deployed prompts differed from their repo file; 18 still asserted a dead connector-catalog
composition ("the catalog exposes 15 tools") and a dead Yahoo condition ("returns HTTP 429") that
the repo had corrected on 2026-10-31.

That gap is why this work was sequenced the way it was: **the repo had to be fixed first, then
deployed, then a drift check added so the gap cannot silently reopen.** Editing the repo alone
would have changed nothing an agent reads.

---

## 2. What changed, by work package

### WP1 — the shared contract, the README, the probe script

The fleet's runtime facts were stated as absolutes and several were wrong. The contract now
states them conditionally and records *when* each was measured.

| Change | Why |
|---|---|
| Yahoo rows rewritten as "availability varies by egress" | Yahoo answered **429 from one cron session and 200 from another on the same day** (2026-11-02). "200 OK" and "persistent 429" were both true only on the day they were measured. |
| Added the measured per-session evidence table | A reader can see *why* the rule is conditional. |
| Seven ladder endpoints promoted out of the "superseded" section into the current table, re-measured | `api.nasdaq.com/api/quote/{SYM}/info` and `finance.yahoo.com/quote/{SYM}/` existed **only** in the section headed *superseded*, so an agent reading the current table could not verify ladder tiers 3–4. |
| Frankfurter → canonical host `api.frankfurter.dev/v1/latest` | `api.frankfurter.app` now 301s; `curl -s` without `-L` silently returns an HTML 301 body. 18 prompt examples use `curl -s`. |
| Stooq relabelled | It is **200 with a JavaScript proof-of-work challenge**, not a 404 — a status-code-only check would parse HTML as CSV. |
| SEC EDGAR UA requirement stated | `www.sec.gov` returns **403** with a browser UA and **200** with a contact-style UA. |
| NASDAQ halt RSS → 302 | It 302s to a 404 page, not "200 with 0 items". |
| `stocktwits` row: "sentiment" removed | It exports `chart_data`, `trending`, `discover_tools` — no `sentiment`. |
| `--list-packs` documented as semantic discovery | It returns only packs whose *tools* match the query, and **omits `stocktwits` and `shibui`**, which both work when called by name. |
| Gateway tool-name resolution documented | `stocktwits get_quotes` and `market-recap get_quotes` are **the same server** (identical payload and `retrieved_at`). Two pack names agreeing is not two sources agreeing. |
| §2b split into `RUNTIME-CONTRACT-HISTORY.md` | The superseded table is history, not a live reference — but it stays, because it documents *why* the 429 was transient. |
| `probe_mcp.py`: compiled regex | `FINANCE_RE.split("|")` + a literal `in` test compared `sec_?edgar` as 10 literal characters, so it **could never match `sec_edgar`**. Verified: the old test misses `mcp__sec_edgar__search`; the new one matches it. |
| `probe_mcp.py`: fourth state `probe_unavailable` | `mcode-tools` is present in some Cloud sandbox images and absent in others. A missing probe binary is **not a finding**. |
| `barchart_fetch.py`: `find_chrome()` glob widened | It matched only `chromium-*/chrome-linux/chrome`; the newer `chrome-linux64` layout and `headless_shell` were invisible. |
| README "Common contract" rewritten | It still said Yahoo returns a persistent 429 — and it is the section every routine and every new agent is pointed at. |

**Correction to the audit:** the audit reported that `_shared/barchart_fetch.py` "cannot run" and
that `pip` was unavailable. Direct measurement contradicted both — the helper returns real
Barchart data (SPY 755.72, QQQ 690.49, 3/3 runs) and `python3 -m pip` reports pip 23.0.1. **That
finding was not acted on.** The glob was widened as a robustness improvement, nothing more.

### WP2 — one push implementation, one delivery check, one window check

Three new POSIX-`sh` scripts under `cloud-prompts/_shared/`, tested under both `sh` and `bash`.

`push_artifact.sh` replaces a ~3.2 KB bash block duplicated in 21 prompts. The behaviours it
fixes were each verified, not assumed:

| Behaviour | Verification |
|---|---|
| The `git push … \| head -3` exit-status trap | The old form exits **0** on a non-fast-forward rejection; the new form exits **1**. Demonstrated side by side. |
| `git add -A` staging deletions | Only the named path is staged; a staged deletion aborts the push. |
| Shared-fire-minute race | On rejection it re-fetches, rebuilds the worktree from the new tip, re-copies and re-commits. |
| Delivery verification | `git cat-file -e` on the remote branch after a successful push — a push that exited 0 but landed nothing now fails loudly. |
| `#90`'s branch target | `--branch` is a parameter, so `audit/status` and `main` use one implementation. |
| Missing token | Exit 2, `push: skipped (token unset)`. |
| Portability | `set -o pipefail` and `$RANDOM` are bashisms that are fatal under dash — both removed. A nested-quote `$()` parse error was found by running the script, not by reading it. |

`verify_delivery.sh` answers one question: is the path present on the remote branch?

`window_check.sh` keeps **one** live gate — the market-holiday list — and drops the day-of-week
and hour branches, because the scheduler owns those. Tested: in-window, wrong day, market holiday
(marker written, correct reason), a non-matching holiday list, and the hour gate.

### WP3 — the shared skill text

- **The watchlist references (5 skills).** `research/watchlist.yaml` exists only on the local Mavis
  host. `#16`, `#22` and `#23` instructed a read of it with no fallback; each now says what to do
  when the file is absent. `#19` already handled it correctly and was left alone; so was
  `eod-watchlist-snapshot`, which already carries the 2026-09-22 policy that the watchlist is not
  the universe.
- **Windows paths.** Every executable `Read C:\Users\…` instruction is gone from the live skills.
  Where a skill lists the local path as its output location, a note now points at the cron
  prompt's `## OUTPUT` path.
- **Orphan skills.** Six moved to `cloud-prompts/history/skills-orphaned-2026-11-02/`.
  `stocks-in-play-pipeline` was **restored** — it is fetched by no prompt, but the *live*
  `us-stocks-in-play` skill depends on it. Counting intra-skill references, the remaining orphan
  list is empty.
- **`preopen-feed-plan.md`** now says explicitly that the files it names are specifications for
  work not yet built, and that an agent must not try to fetch them.

**Correction to the audit:** the audit listed `scripts/screen.py` as a dead reference. It is not —
it exists at `cloud-prompts/skills/stock-screener-suite/scripts/screen.py` and the prompt resolves
it via a fetch URL (verified HTTP 200, 60,569 B). **Not acted on.**

### WP4–WP7 — the in-prompt rewrite (19 prompts + `#90` + `#91`)

Applied by `tools/rewrite_prompts.py`, a deterministic, idempotent, self-verifying script: it
edits only the section between two known headings, asserts each section was found exactly once,
and fails loudly if a stale string survives or the code fences go unbalanced.

| Change | Routines | Effect |
|---|---|---|
| Window check → market-holiday guard | 20 | ~30 KB → ~1.2 KB. The day-of-week branches were unreachable — the scheduler owns the day — while 17 tails promised a holiday skip that only `#19` implemented. |
| `## MCP TOOLS AVAILABLE` → bridge-first | 19 | The block advertised `extract_content_from_websites` in 16 of the 17 blocks that carried it, plus four unregistered `mcp__*` names — and the next section said those names do not exist. |
| `## RUNTIME DATA-SOURCE CONTRACT` regenerated | 19 | Removes the absolute Yahoo claim and the 133-tools snapshot; states the ladder and the per-egress caveat. `#26` had the contract inlined inside the tools block and no `PRIMARY SOURCE` or `Rules` section — split back out. |
| Push + delivery → the shared script | 21 | Removes 21 copies of a ~3.2 KB bash block. The stale push-collision comment (18 prompts listed `#05`+`#16` at 16:30, but `#16` moved to 16:35 on 2026-10-29) is gone. |
| **Source-precedence rule** (new) | 20 | 18 of 20 market-data routines had no rule for which source wins. One concluded *"no market-data source available"* while its own prompt said the source was reachable. |
| **Scheduled-date rule** (new) | 19 | The quota wall kills a session and the platform re-dispatches it later — on 2026-11-01 a Friday brief was re-executed on Sunday 01:51 ET, where the weekend guard would have discarded a real trading-day brief. |
| **`errors:` redefinition** | 19 | Counts **source** failures, not the absent `mcp__*` tools (which are not failures). |
| `#90`'s own push block | 1 | It built its audit branch from `origin/main` while pushing to `refs/heads/audit/status`, and carried the live `\| head -3` trap. |
| `#90`'s master-mirror block | 1 | It pushed `FETCH_HEAD`, which `git ls-remote` never populates, so it always failed. Now an explicit `origin/main:master` refspec, gated on `master` being an ancestor of `main` so it fast-forwards only when safe. |
| `#91` STEP 2c — prompt-drift detection | 1 | Compares the SHA-256 of every deployed prompt against its repo file. Verified against the live fleet: it correctly reported all 23 as drifted. |
| `#91` STEP 1 chunk discovery | 1 | `ls -t \| head -1` could select another tool's output and abort the whole detector. Now searches for a chunk containing a `"tasks"` array. |

### WP8/WP9 — hygiene

- **Schedule fields.** `#06`, `#13`, `#14` named no cron expression at all, so their schedules
  could not be cross-checked against the scheduler. `#06`'s "Schedule is unchanged" was **false** —
  it moved from Saturday 10:00 to 15:00 ET on 2026-10-29. The "Original local schedule" was wrong in
  four routines; corrected against `migration-state.json`, the 2026-09-25 snapshot of the source
  crons of record.
- **The false weekend promise.** 17 tails said "if the cron fires outside its intended window
  (e.g. holiday, **weekend when it should be weekday**)". The weekend branch could not fire —
  the scheduler owns the day. The promise now names the one case that can: a market holiday.
- **Reply formats.** The README's "no line cap" is now documented with its three real exceptions
  (`#07` — a fixed six-line machine-readable status line, `#90` — a ≤ 8-line audit digest, `#01` —
  under 10 lines). All three are machine-read rather than human-read; forcing them onto the
  five-part form would be a regression. The point was that the README claimed a fleet-wide rule
  it did not have.
- **Tail variants.** `#08` and `#22` had item 1 wrapped across two lines; 13 prompts now share
  one tail. The 9 remaining variants each encode a real routine-specific constraint and were
  left alone.

### WP10 — the roster and index regenerated

From the live scheduler and `origin/main`, using the generators that already exist
(`tools/gen_roster.py`, `tools/gen_index.py`) — neither table is hand-edited. The three
fleet-description sources were consistent but the *snapshot* was stale.

Current state, 2026-11-02 ET: 23 routines, none outside tolerance. `#07`, `#08` and `#12` sit at
exactly 5 days since 2026-10-28 — the quota wall — and are the routines to watch.

### WP11 — the outputs repo

- The 31 `SKIPPED_*.md` markers moved to `refs/skipped-markers/` with a README explaining what
  they are. They are fossils of a branch that can no longer fire, but they are the audit trail of
  why a routine did not run on a given day — moved, not deleted.
- Four stale pre-cloud `refs/` docs deleted (`crons.md`, `fallbacks.md`, `filters.md`,
  `tiering.md`) — none referenced by any live prompt or skill; the fifth replaced with a pointer.
  All four are recoverable from git history.
- **The `master` branch re-aligned.** `master` had diverged: two merge commits `main` did not
  have, so it could not be fast-forwarded, and it was missing every artifact delivered since
  2026-10-30 — a plain `git clone` landed on a tree 86 files short.

  Verified before touching it: every file on `master` also existed on `main` (31 of 35
  byte-identical in the archive; the other 4 were the deliberately retired docs, recoverable from
  history), `main` was one file ahead, and the two extra commits were merges of `main` into
  `master` carrying no unique content. `master` was then advanced with `--force-with-lease`,
  keeping `backup/master-pre-tidy-2026-11-02` as a rollback point.

  A plain `git clone` now lands on the current commit.

---

## 3. Defects caught before anything shipped

Three defects were introduced by the rewrite itself and caught by **reading the rendered prompt
text** rather than trusting the script's own report:

1. **A dangling sentence.** The original read "The `{date}` placeholder is today in US/Eastern,
   `YYYY-MM-DD`. Resolve it as the first step." across two lines. Replacing the first sentence left
   ` Resolve it as the first step.` alone on its own line in 17 prompts.
2. **A mangled bullet.** The errors-rule replacement rewrote only the *tail* of the DELIVERY
   bullet, leaving the bullet's prefix and the rule's prefix interleaved:
   `…and one line for \`errors: <n>\` —` / `- \`errors: <n>\` — count of **SOURCE** failures …`
3. **A list starting at "7."** `#26` was given a *new* `### Rules` block containing only the
   source-precedence rule, so a prompt with no numbered rules ended up with a list beginning at 7.
4. **A stray backtick** in the source-health rule, and **`#06`'s output paths** pointing at the
   wrong directory.

All four are fixed, and the script's own checks were extended to catch them. The rewrite script
is committed, so the whole transformation is reproducible and auditable.

### Defects caught during deployment

The deployment surfaced three more problems that no static check on the repo would have found,
because each was a mismatch between the repo and the *live scheduler*:

5. **`#01` had no canonical prompt file at all.** Its prompt lived only as a code fence inside a
   wrapper document, so tooling that walks `cloud-prompts/cron-prompts/` could not see it and the
   byte-compare verification had nothing to compare against. The deployed prompt was promoted to
   `cloud-prompts/cron-prompts/01-weekly-mcp-health-check.md` (byte-identical to what was live),
   the wrapper's rationale moved to `history/`, and a pointer file left behind.
6. **`#25` differed from its deployment by one trailing newline.** The repo file was the odd one
   out — the other 22 carry none — so the newline was stripped in the repo rather than the prompt
   re-pasted. A re-paste is another chance to drift; changing the repo is not.
7. **`#91`'s prompt-drift check hardcoded `REPO=/workspace/mig`** — a path that exists only in the
   remediation sandbox, not in a fresh cron run, so the check would have failed every day. It now
   clones the repo into the sandbox first, with a CDN fallback.
8. **`#90`'s master-mirror comment asserted two SHAs** (`origin/master 2d5e9da`, `origin/main
   9666a41`) and the conclusion that the mirror was skipped. Both SHAs were already stale —
   `origin/master` had been fast-forwarded and *is* an ancestor of `main`, so the mirror does
   fire. The comment now states only what the ancestry gate does and tells the reader to let
   `git merge-base --is-ancestor` decide at run time.

---

## 4. Verification

| Check | How | Result |
|---|---|---|
| Every skill URL resolves | regex over all 20 URLs → `os.path.isfile` | 20/20 resolve, 0 broken |
| Code fences balanced | `count('```') % 2` over all 23 prompts + the contract | all balanced |
| No stale strings survive | grep for the flag block, the mislabel, the weekend promise, the push trap, the phantom tool | none |
| Rules blocks complete | numbered-list check, must start at 1 and include 7 | 20/20 prompts |
| Shared scripts parse | `sh -n` and `bash -n` | all pass under both |
| `push_artifact.sh` end-to-end | real push to a scratch branch in the outputs repo | `push: ok` + `DELIVERY: ok` |
| The exit-status trap is really fixed | divergent-history push, old vs new pattern | old exits 0, new exits 1 |
| The holiday guard really works | extracted the block from a prompt and ran it | skips on a holiday, passes otherwise |
| The drift check really works | ran the STEP 2c script against the live deployed prompts | correctly reported all 23 as drifted |
| Nothing else changed on the tasks | before/after snapshot of schedule, timezone, enabled, session.mode, project_id, model, created_at, run_count | see §5 |
| The outputs repo was not damaged | full clone before and after, file counts, tree comparison | `main` 830 files, `master` now identical |
| Every deployed prompt matches its repo blob | SHA-256 over raw bytes, deployed vs `cloud-prompts/cron-prompts/*.md` | 23 / 23 |
| The repo and the fleet agree from outside | fresh `git clone` of the repo vs the scheduler's `view=list` | 23 / 23 |
| The generated index still matches reality | `tools/gen_index.py --check` against the live scheduler | `OK: README index matches the ground truth` |
| The generated roster still matches reality | `tools/gen_roster.py` re-run against the live scheduler + `origin/main` | 23 routines, 0 stale |

---

## 5. The deployment (WP12)

The point of the whole exercise: a corrected repo changes nothing until it is deployed.

**Method**, and why each part is there:

- **Only `task_id` and `prompt` are sent.** `schedule` silently resets the timezone to `Etc/GMT-7`
  (UTC+7 — an 11-hour error that fires routines after market close). `enabled` is coerced to the
  string `"true"` and fails validation. `model` does not exist on the tool.
- **The prompt goes over as raw text with real newlines.** A `json.dumps()` dump escapes every
  newline into a literal `\n` and the agent receives one enormous line. This is the exact bug that
  broke a previous sync.
- **Every deployed prompt is verified by SHA-256 against the repo blob** after the write. A
  `cron_update` returning `{"ok": true}` proves the write landed, not that it landed correctly.
- **The non-prompt fields are snapshotted before and after** so the blast radius is provable:
  only the prompt may change.
- **A pilot first.** `#26` was deployed alone and verified byte-identical, with schedule, timezone,
  enabled, session mode, project, model, `created_at` and `run_count` all confirmed unchanged —
  before the rest were deployed.

**Result: all 23 prompts deployed and verified byte-identical to their repo files, with no
non-prompt field changed on any task.**

> **Post-deploy correction (2026-11-03).** The fleet is now **25 routines** — a concurrent
> agent added `#92a`/`#92b` (pre-open catalyst capture) and rewrote `#01`, `#91` and `#04`. The
> final state is **25/25 prompts byte-identical** to their repo blobs, all 25 on
> `America/New_York`, all `enabled`, all `session.mode=new`.
>
> Two defects were found only by the first post-deploy fires, and both are now fixed:
>
> 1. **The shared push script staged only the single `--add` path.** That is correct for the 18
>    single-file routines and wrong for the multi-file ones. `#09` produces 27 files, so only one
>    landed per push and the agent had to push 27 times: **61 commits on `origin/main` in 17
>    minutes** on 2026-11-02, each regenerating the artifact's `generated_et` timestamp so the
>    previous push was already stale by the next check — a push loop that ended only when the
>    agent stopped. The script now stages the routine's whole output tree, restoring the
>    pre-2026-11-02 `git add <own-dir>` behaviour: one commit per routine. Verified against a
>    local bare repo — 28 files in ONE commit, sibling routines' files untouched, zero deletions.
> 2. **The commit subject carried no routine number.** `#90`'s near-miss triage greps commits for
>    `cron (#)?NN ` to attribute a push to a routine, so a subject like `cron daily-screens
>    2026-11-02` makes a *delivered* artifact report as MISSING. The script now derives the
>    number from the artifact path (one table, checked against every live `--add` path) and the
>    date from the path too — the ARTIFACT's date, not the execution date, which differ on a
>    delayed replay.
>
> **A third defect was mine and is worth recording: a `cron_update` carrying only `task_id` +
> `prompt` reset the timezone to `Etc/GMT-7`** on two tasks — `#90` would have fired at 19:00
> ET instead of 07:00, and `#04` at 20:55 instead of 15:55. This is the UTC+7 landmine the
> project already knew about, but it fires on a *prompt* update too, not only on a `schedule`
> update. The fix is to send `timezone` in the same call, and to re-check it after every
> deploy. Both tasks were repaired and verified.
>
> **And a fourth, about the deploy method itself:** two hand-pastes were byte-exact in LENGTH
> but wrong in content — `#90` got `[01-11]` where the repo said `[31-10]`, and `#04` had one
> line reflowed. A length check is not a byte check; only SHA-256 over the raw bytes is proof.

Verified against a **fresh `cron_read view=list`** taken after the last write — not against the
read-back of the write itself, which would only prove the write landed where it was aimed:

| Check | Result |
|---|---|
| Prompts matching their repo blob (SHA-256, raw bytes) | **23 / 23 match, 0 drifted** |
| Non-prompt fields changed (`schedule`, `timezone`, `enabled`, `session.mode`, `model`, `project_id`, `task_id`, `created_at`, `run_count`) | **0 of 23** |
| `session.mode` | `new` on all 23 (no routine bound to a fixed conversation) |
| `timezone` | `America/New_York` on all 23 (no silent `Etc/GMT-7` reset) |
| A **fresh clone** of the repo matches the live scheduler | 25 / 25 (after the `#92` additions) |
| Commit subjects carry the routine number (`cron NN …`) | every live `--add` path resolved through the script's table | 23 / 23 |
| `timezone` after every deploy | `America/New_York` | 25 / 25 |
| `next_run` | unchanged on 22; `#15`'s advanced one day, because its 08:00 ET fire had passed |

The repo is now the single source of truth *and* the live fleet is running it. A fresh
`git clone` of `karizaco/maxhermes-migration` and the scheduler's own `view=list` agree on all
23 prompts, byte for byte — which is the state cron `#91` STEP 2c now checks for itself every day
at 04:05 ET.

### The deployment order

`#26` went first, alone, and was verified before anything else was touched. Then the rest in
roster order. `#01`, `#07`, `#15`, `#25`, `#26`, `#90` and `#91` were deployed last, after the
shared-block extraction (below) changed every prompt's shape.

### The shared-block extraction (the token win)

After the rewrite the 23 prompts totalled **408,994 B** (mean 17,782 B), and nine of them carried
**byte-identical** copies of the same four blocks — the MCP-tool list, the data-source contract,
the seven standing rules, and the delivery-verification block. Every future fix to those blocks
had to be made nine times, and each copy drifted independently.

Those blocks now live in one file, `cloud-prompts/_shared/PROMPT-BLOCKS.md` (11,992 B), fetched at
run time alongside the skill spec. **20 of 23** prompts reference it. The fleet went
**408,994 → 238,599 B (−41.7%)**, mean **17,782 → 10,373 B**.

`#90` (37,164 B) and `#91` (18,356 B) do not reference it, and are not expected to: they are the
auditor and the drift guard, they have no skill spec to fetch alongside, and their reply formats
are machine-read (see below).

### Reply-format exceptions, and one that nearly slipped

`#07`, `#90` and `#01` are **documented exceptions** to the five-part reply format, because their
output is machine-read. The extraction step removed `#90`'s `## DELIVERY` section on the
assumption that the shared `## DELIVERY` block covered it — it did not, and `#90` would have
silently started emitting the human-digest format that its consumer cannot parse. The section was
restored, with an explicit note in the prompt that it is an exception and why.

The README's "three documented exceptions" list is the contract that caught this.

---

## 6. What was deliberately not done

| Not done | Why |
|---|---|
| The audit's "barchart_fetch.py cannot run" fix | It was false — the helper works. Replacing a working script with a Node rewrite would have been a regression. |
| The audit's "scripts/screen.py is a dead reference" fix | It was false — the file exists and the prompt resolves it by URL. |
| Forcing `#07`/`#90`/`#01` onto the five-part reply format | They are machine-read, not human-read. The README now documents them as exceptions instead. |
| Repairing `#07`, `#08`, `#12`'s missing artifacts | Those routines are silent because of the Token Plan quota wall (error 2067), not a prompt problem. A prompt fix cannot fix a billing wall. |
| Deleting the 31 skip markers | They are the audit trail of why a routine did not run. Moved to `refs/skipped-markers/` with a README instead. |
| Changing `default_branch` | GitHub requires repo Administration scope and the PAT does not have it. The mirror is aligned instead. |

---

## 7. Two audit findings that were false

The audit produced 65 findings across 23 routines. Two of them were wrong, and acting on them
would have been a regression, so they were recorded as false rather than "fixed":

| Audit claim | Reality |
|---|---|
| `barchart_fetch.py` cannot run — it needs a Node rewrite | **False.** The helper works; `pip` is present. Rewriting a working script would have broken it. |
| `scripts/screen.py` is a dead reference | **False.** The file exists and the prompt resolves it by URL — HTTP 200. |

A third finding — that the outputs repo's `master` branch had diverged from `main` — was right
about the divergence but wrong about the cause: the divergence was a mirror/merge artifact, not a
lost push. The mirror is now aligned.

## 8. What still needs attention

1. **`#07`, `#08`, `#12` have not delivered since 2026-10-28** — the quota wall. They are at exactly
   the 5-day tolerance and will be flagged stale on 2026-11-03. This is a billing problem, not a
   prompt problem. Their prompts are now correct and deployed, so they should resume the moment
   the quota wall lifts — but nothing in the prompt fixes it, and the Token Plan usage limit
   (error 2067) has to be raised on the account.
2. **A first real fire on the new prompt has already landed for `#15`** — it delivered
   `earnings/2026-11-02-reactions.md` at 08:00 ET on 2026-11-02, its first fire on the slimmed
   prompt, and the artifact is on `origin/main`. The other 20 producers have not fired yet on the
   new text, so this is one data point, not a fleet-wide proof. The next ET trading day exercises
   the rest.
3. **The prompts now fetch `_shared/push_artifact.sh` over the network at run time.** That is a new
   runtime dependency: if the fetch fails the routine must fall back to the inline block, and the
   `raw.githubusercontent` CDN was measured serving a stale blob for ~8 minutes after a push. Push
   these scripts well ahead of a fire and consider pinning a version.
4. **The drift check runs once a day at 04:05 ET.** A prompt edited in the repo and not deployed
   can still drift silently for up to ~21 hours.
5. **`_classification.md` still describes 4 dead original cron numbers** and the pre-cloud
   mechanism. It should be moved to `history/` with a header.
6. **The outputs repo's `refs/` and `mcp-health/` will accumulate again.** The marker archive needs
   a policy — when a marker is old enough to move, and when it can be deleted.
