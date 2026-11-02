# Track D — Token cost and instruction-effectiveness: what to change in the prompts

**Scope:** read-only analysis of the 23 deployed cron prompts in `karizaco/maxhermes-migration`
(repo clone at `/workspace/mig`, platform copy read via a persisted `cron_read` artifact).
**Nothing in `/workspace/mig` was modified. No remote was pushed.**

> **Revision note (attempt 2).** This document supersedes the first submission. It is **not** the
> same work: every proposal's saving is now computed by **measuring the actual proposed
> replacement text** against the actual current block, instead of estimating a target size. That
> changed five numbers materially, and it exposed two real defects in the first submission, both
> corrected below. The corrections are itemised in
> [§ Corrections to the first submission](#corrections-to-the-first-submission).

---

## Summary

The deployed fleet carries **433,427 bytes ≈ 108,356 tokens** of prompt text (assumption: 4 chars
per token; the prompts are 29.8 % fenced code, which tokenises denser, so a mixed model — 3.3
chars/token inside fences, 4.0 outside — puts the true cost at **114,784 tokens**, ~6 % higher).
Per calendar day the fleet loads **1,692,595 bytes ≈ 423,148 tokens** across 39 scheduled fires.
The proposals below remove **150,467 bytes ≈ 37,616 tokens per full fleet-fire (34.7 %)** and
**614,047 bytes ≈ 153,511 tokens per fleet-day (36.3 %)** from the *deployed* prompts, plus a
further 3,499 bytes once the pending repo state is deployed. Three proposals deliberately **add**
text — the fleet-wide source-precedence rule (D5), the scheduled-date rule (D12) and the
capability-list rewrite (D6), together **−24,066 bytes ≈ −6,017 tokens per fleet-fire** — so the
**net** reduction is **130,579 bytes ≈ 32,644 tokens per fleet-fire (30.1 %)** and **531,199 bytes
≈ 132,799 tokens per fleet-day (31.4 %)**. After everything the deployed fleet-fire falls to
**302,848 bytes ≈ 75,712 tokens** and the fleet-day to **1,161,396 bytes ≈ 290,349 tokens**. The token saving is the smaller half of
the story: the measured quality defects are a **live `git push … | head -3` exit-status trap in
cron #90** (the one place it still runs, and it pushes to a branch the first submission's script
would have clobbered), a **live contradiction inside the data-source contract** (the deployed
prompts say Yahoo JSON returns 429; the contract those same prompts tell the agent to fetch says
Yahoo is 200 OK — 19 prompts carry both instructions at once), **no source-precedence rule in 18
of the 20 market-data routines**, and **21 of 23 deployed prompts that no longer match their own
repo file**. The artifacts show the consequence directly: a routine concluded "no market-data
source available … not fixable from inside the sandbox" while the very same prompt told it the
source was reachable, and published a pre-market gap built on a stale tape that had to be
corrected a day later.

### The one architectural fact that governs every proposal

Every cron fire is a **fresh session**. The prompt is loaded into context, and then whatever the
agent fetches is *also* loaded into context. Therefore:

| Move | Effect on context tokens |
|---|---|
| Inline block → **fetched `.md` that the agent reads** | **Zero saving.** The bytes relocate into the same context. Often a *loss*: a 21,809-byte contract read in place of a 1,827-byte inline summary is +5,000 tokens. |
| Inline block → **executable script the agent runs but never reads** | **Full saving.** The bytes never enter context. |
| Inline block that **duplicates something already fetched** | **Full saving.** The redundancy never enters context. |
| Inline block that is **never read anyway** (dead work, restatement) | **Full saving.** |

Most "extract the boilerplate into a shared file" advice fails the second row and saves nothing.
This document separates the two kinds and prices them differently — and every price below is
computed by measuring the **exact replacement text** proposed, not by estimating a target size.
That discipline is what turned three of the first submission's "savings" into a net cost.

---

## COST TABLE

Deployed bytes are the **platform** bytes, not the repo bytes. Method: `cron_read view=list`
output was persisted by the platform as a tool-result artifact
(`/workspace/.mavis/tool-results/458676653531358/call_01a196fdb3f37774aef04a72/chunks/000000.txt`,
466,798 bytes, `manifest.json` → `tool_name: "cron_read"`, `command: "cron list"`, captured
**2026-11-01T12:02:51Z**). All 23 `response.tasks[].prompt` strings were extracted verbatim,
written to `/workspace/audit/scratch/deployed/`, and measured with `len(prompt.encode())`.
(The `cron_read` tool is not exposed in *this* session's tool catalog — `tool_search` returns zero
hits for `cron`/`cron_list`/`scheduled task`, and `mcp_invoke` rejects both as unknown tool names
— so the persisted artifact from the 2026-11-01 read is the freshest available evidence; see
**Notes**.)

| prompt | deployed bytes | est. tokens @4 ch/tok | fires/day | largest block |
|---|---:|---:|---:|---|
| `90-delivery-auditor.md` | 32,454 | 8,113 | 1 | STEP 4b — STALE-ROUTINE CHECK (7,792 b) |
| `19-earnings-reminder-daily.md` | 22,286 | 5,571 | 5 | GIT PUSH (OPTIONAL) + DELIVERY VERIFICATION (4,690 b) |
| `17-us-stocks-in-play.md` | 22,285 | 5,571 | 5 | PRIMARY SOURCE (bridge) (3,388 b) |
| `10-stock-screener-breadth-snapshot.md` | 22,258 | 5,564 | 5 | GIT PUSH (OPTIONAL) + DELIVERY VERIFICATION (4,774 b) |
| `09-stock-screener-daily-sweep-18:30.md` | 21,577 | 5,394 | 5 | GIT PUSH (OPTIONAL) + DELIVERY VERIFICATION (4,774 b) |
| `12-cross-asset-correlation-snapshot.md` | 21,322 | 5,330 | 5 | GIT PUSH (OPTIONAL) + DELIVERY VERIFICATION (4,767 b) |
| `15-earnings-reaction-scanner.md` | 21,219 | 5,304 | 5 | GIT PUSH (OPTIONAL) + DELIVERY VERIFICATION (4,746 b) |
| `23-agentic-post-market-brief.md` | 19,057 | 4,764 | 5 | GIT PUSH (OPTIONAL) + DELIVERY VERIFICATION (4,712 b) |
| `26-agentic-pre-market-brief.md` | 19,021 | 4,755 | 5 | GIT PUSH (OPTIONAL) + DELIVERY VERIFICATION (4,872 b) |
| `08-stock-screener-pre-market-gapper.md` | 18,452 | 4,613 | 5 | GIT PUSH (OPTIONAL) + DELIVERY VERIFICATION (4,773 b) |
| `16-unusual-options-flow-daily.md` | 18,280 | 4,570 | 5 | GIT PUSH (OPTIONAL) + DELIVERY VERIFICATION (4,874 b) |
| `04-reversal-bullish-3:55.md` | 18,279 | 4,569 | 5 | GIT PUSH (OPTIONAL) + DELIVERY VERIFICATION (4,761 b) |
| `05-eod-international-daily.md` | 18,231 | 4,557 | 5 | GIT PUSH (OPTIONAL) + DELIVERY VERIFICATION (4,779 b) |
| `02-asia-pre-market-reactions.md` | 18,182 | 4,545 | 5 | GIT PUSH (OPTIONAL) + DELIVERY VERIFICATION (4,774 b) |
| `25-ntrt-gap-brief-daily.md` | 18,178 | 4,544 | 5 | GIT PUSH (OPTIONAL) + DELIVERY VERIFICATION (4,723 b) |
| `22-weekly-market-recap-preview.md` | 18,175 | 4,543 | 1 | GIT PUSH (OPTIONAL) + DELIVERY VERIFICATION (4,739 b) |
| `20-eod-watchlist-csv-snapshot.md` | 18,084 | 4,521 | 5 | GIT PUSH (OPTIONAL) + DELIVERY VERIFICATION (4,738 b) |
| `07-stock-screener-focus-rvol-09:45.md` | 18,081 | 4,520 | 5 | GIT PUSH (OPTIONAL) + DELIVERY VERIFICATION (4,773 b) |
| `06-stock-screener-pattern-study-backlog.md` | 17,884 | 4,471 | 1 | GIT PUSH (OPTIONAL) + DELIVERY VERIFICATION (4,776 b) |
| `14-macro-calendar-week-ahead.md` | 17,823 | 4,455 | 1 | GIT PUSH (OPTIONAL) + DELIVERY VERIFICATION (4,769 b) |
| `13-macro-calendar-midweek.md` | 17,799 | 4,449 | 1 | GIT PUSH (OPTIONAL) + DELIVERY VERIFICATION (4,766 b) |
| `91-schedule-drift-guard.md` | 10,228 | 2,557 | 1 | STEP 4 — NOTIFY THE USER (2,049 b) |
| `01-weekly-mcp-health-check.md` | 4,272 | 1,068 | 1 | 1. Connector-catalog probe (999 b) |
| **FLEET TOTAL (one fire of every routine)** | **433,427** | **108,356** | **39.0** | — |
| **FLEET-DAY (all scheduled fires in 24 h)** | **1,692,595** | **423,148** | — | — |

For comparison, the **repo state** (what the next deployment would install) is
**485,815 bytes ≈ 121,453 tokens** per fleet-fire and **1,888,843 bytes ≈ 472,210 tokens** per
fleet-day — the repo is **52,388 bytes larger** than what is deployed, because 21 of 23 deployed
prompts are stale (see D11).

---

## BLOCK-ANALYSIS TABLE

Method: each deployed prompt was split into sections by a fence-aware heading scan (`^#{1,3} `,
headings inside ```` ``` ```` blocks ignored), each section hashed (SHA-256 over raw bytes) to
count verbatim groups, and each section's fenced / unfenced bytes measured separately. Block
sizes are the **deployed** bytes.

| block | n prompts | bytes/prompt (avg) | ×fleet | median % of its prompt | code b | prose b | verbatim groups (largest) | move-to-shared-file saving |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| GIT PUSH (OPTIONAL) | 21 | 3,190 | 67,000 | 17.6 % | 47,240 | 19,781 | 21 (1) | **0 — must become a script, not a fetch** |
| PRIMARY SOURCE (bridge) | 20 | 2,411 | 48,228 | 12.9 % | 26,230 | 21,998 | 2 (19) | 0 — the bridge script is already fetched and run |
| WINDOW CHECK | 21 | 2,065 | 43,350 | 12.6 % | 30,986 | 12,385 | 21 (1) | **0 — must become a script, not a fetch** |
| RUNTIME DATA-SOURCE CONTRACT | 19 | 1,878 | 35,677 | 10.2 % | 0 | 35,677 | 2 (18) | **0 — a fetch would COST ~5,000 tokens/run; trim instead (D1)** |
| DELIVERY VERIFICATION | 21 | 1,468 | 30,841 | 7.8 % | 10,939 | 19,902 | 21 (1) | **0 — must become a script, not a fetch** |
| DELIVERY (reply format) | 20 | 1,469 | 29,399 | 7.7 % | 0 | 29,399 | 6 (9) | 0 — agent must read it; consolidate to 1 variant (D10) |
| RULES (source rules) | 21 | 1,304 | 27,400 | 7.2 % | 0 | 27,400 | 5 (10) | 0 — high value, keep |
| CRITICAL REMINDERS | 21 | 1,002 | 21,043 | 4.8 % | 0 | 21,043 | 9 (11) | 0 — trim restatements (D10) |
| HELPER SCRIPTS (PYTHON) | 18 | 903 | 16,249 | 5.1 % | 455 | 15,794 | 13 (4) | 0 — relocation into an already-read skill saves nothing; **delete where unneeded (D7)** |
| OUTPUT | 18 | 622 | 11,209 | 2.5 % | 314 | 10,895 | 18 (1) | 0 — routine-specific, keep |
| SCHEDULE | 22 | 485 | 10,688 | 2.8 % | 0 | 10,688 | 22 (1) | 0 — routine-specific, keep |
| SKILL SPEC | 19 | 530 | 10,077 | 2.7 % | 0 | 10,077 | 14 (4) | 0 — already a pointer |
| MCP TOOLS AVAILABLE | 17 | 324 | 5,492 | 0.9 % | 455 | 5,037 | 13 (3) | n/a — lists tools that do not exist; rewrite (D6) |
| ZERO-FALLBACK POLICY | 18 | 293 | 5,270 | 1.6 % | 0 | 5,270 | 3 (16) | 0 — merge into Rules (D9) |
| AUDIT LOG | 18 | 233 | 4,178 | 1.3 % | 0 | 4,178 | 4 (15) | n/a — delete (D8) |
| SELF-DESCRIPTION | 2 | 1,231 | 2,463 | 5.6 % | 0 | 2,463 | 2 (1) | 0 — routine-specific, keep |
| MCP AVAILABILITY PROBE | 1 deployed / 20 in repo | 1,580 / 681 | 14,519 (repo) | 7.1 % | 481 | 1,099 | 2 | n/a — script is fetched and run; trim prose (D4) |

**Sum of the six largest blocks** (GIT PUSH, PRIMARY SOURCE, WINDOW CHECK, RUNTIME CONTRACT,
DELIVERY VERIFICATION, RULES): **252,545 bytes = 63,136 tokens = 58.3 % of the fleet-fire.**

### Largest single contributors, with locations

| what | bytes | where |
|---|---:|---|
| `## STEP 4b — STALE-ROUTINE CHECK` | 7,792 | `deployed/90-delivery-auditor.md:250` (one prompt, but 8,113 tokens every single day) |
| `## STEP 3 — DECIDE WHAT SHOULD HAVE RUN` | 5,101 | `deployed/90-delivery-auditor.md:99` |
| `## STEP 4 — CHECK EVERY ROUTINE` | 4,641 | `deployed/90-delivery-auditor.md:176` |
| `## GIT PUSH + ## DELIVERY VERIFICATION` (combined) | 4,690–4,874 | 21 prompts; **#90 is only 2,178 b** (different target branch, one staged file) |
| `## FILTER — the two rules that decide the roster` | 2,394 | `deployed/19-earnings-reminder-daily.md` |
| `### PRIMARY SOURCE: the MCP-over-HTTP bridge` | 2,360 | 20 prompts, byte-identical in 19 |
| `## STEP 4c — DIAGNOSE A GAP` | 2,323 | `deployed/90-delivery-auditor.md` |
| git race-retry bash body | 2,281 | 20 prompts, **differs in exactly 3 lines** (the output dir and the `git add` path) |
| WINDOW CHECK bash body | 1,614 | 21 prompts, **differs only in the 4 flag lines** |

---

## PROPOSAL TABLE

Prioritised by (quality effect ÷ effort) ÷ risk. "Per run" = per single routine fire; "per
fleet-day" = weighted by each routine's actual fires/day, measured from the deployed cron
expressions (17 weekday routines = 5 fires/day; 6 weekly/daily routines = 1 fire/day). **Every
"saved" figure is measured by byte-comparing the exact proposed replacement text against the
actual current block** — no target sizes are estimated.

| id | proposal | target | tok saved / run | tok saved / fleet-day | quality effect | risk | effort |
|---|---|---|---:|---:|---|---|---|
| **D11** | Make the repo the single source of truth and deploy it — 21/23 deployed prompts are stale | repo + process | **0** | **0** | **HIGH** — the delayed-replay date rule, the corrected connector inventory and the 429→200 correction exist in the repo and are *not running* | push race while 21 prompts are re-written | M |
| **D5** | Add a fleet-wide **source-precedence rule** | plaintext | **−152** (cost) | **−12,831** | **HIGH** — removes "which source wins?" ambiguity in 18 of 20 market-data routines | a rule too rigid could suppress the right source | S |
| **D2** | `GIT PUSH` + `DELIVERY VERIFICATION` → `_shared/push_artifact.sh` + `_shared/verify_delivery.sh`, **with the push target as a parameter** | repo script + plaintext | **+918** | **+80,166** | **HIGH** — one place to fix the push; **fixes #90's live `\| head -3` exit-status trap** and its wrong-branch target | script fetch failure; CDN stale window | M |
| **D3** | `WINDOW CHECK` → `_shared/window_check.sh` with flags as env vars | repo script + plaintext | **+353** | **+30,781** | **MED-HIGH** — ends the 6-variant flag drift; makes the holiday and hour-gate cases first-class flags | script fetch failure; flags still per-prompt | M |
| **D1** | Trim the in-prompt `RUNTIME DATA-SOURCE CONTRACT` to a **regenerated** summary (fixes a live contradiction) | plaintext | **+255** | **+20,238** | **HIGH** — removes "Yahoo is 429" vs "Yahoo is 200 OK" from the same 19 prompts | over-trimming forces a contract fetch (+5,452 tok) | S |
| **D10** | `CRITICAL REMINDERS` → drop the restatements; `DELIVERY` reply format → 1 canonical variant | plaintext | **+151** | **+10,942** | **MED** — fewer, sharper reminders; reply format stops drifting | a dropped reminder that was load-bearing | S |
| **D7** | `HELPER SCRIPTS (PYTHON)` → delete from the 8 prompts whose skill references no helper; shorten in the other 10 | plaintext | **+156** | **+10,898** | **MED** — stops 8 prompts warning about Windows helpers they will never meet | a routine whose skill later adds a helper reference | S |
| **D4** | `MCP AVAILABILITY PROBE` prose → a pointer (the script is fetched and run anyway) | plaintext | **+43** | **+3,853** | **MED** — keeps the fast-lane detection, drops the essay | none; the probe still runs | S |
| **D8** | `AUDIT LOG` → delete | plaintext | **+58** | **+4,308** | **LOW-MED** — removes a Windows-only negative instruction from every run | negligible | XS |
| **D9** | `ZERO-FALLBACK POLICY` → merge into the `### Rules` block | plaintext | **−28** (cost) | **−2,151** | **MED** — the "write the artifact, then STOP" rule sits with the partial-data rule | negligible | XS |
| **D6** | `MCP TOOLS AVAILABLE` → one line naming the bridge first; #12/#26's operational appendix moves into their skill | plaintext | **−27** (cost) | **−1,673** | **MED-HIGH** — stops 15 prompts listing `mcp__*` tools that do not exist, and names the bridge that does | provenance listing wanted; the moved appendix still enters context | XS |
| **D12** | **Date-authority rule**: the artifact is dated to the fire's *scheduled* date, not the execution date | plaintext | **−106** (cost) | **−7,881** | **HIGH** — prevents a delayed replay from publishing under the wrong date | needs `cron_read view=runs`; adds one call | S |

**Net token change: −150,467 bytes (−37,616 tokens, −34.7 %) per fleet-fire,
−614,047 bytes (−153,511 tokens, −36.3 %) per fleet-day** for the token-reducing proposals, plus
3,499 bytes more once the pending repo state is deployed; **net of the three quality rules D5,
D12 and D6: −130,579 bytes (−32,644 tokens, −30.1 %) per fleet-fire and −531,199 bytes (−132,799
tokens, −31.4 %) per fleet-day.**

---

# DETAIL

### D11 — Make the repo the single source of truth, and deploy it

- **Target:** repo + process (not a prompt edit).
- **Current text/state:** `cron_read` reports 23 deployed prompts. Diffing each deployed `prompt`
  string against its repo file (`/workspace/mig/cloud-prompts/cron-prompts/*.md` plus
  `cloud-prompts/01-weekly-mcp-health-check.md`) by raw bytes: **2 identical**
  (`17-us-stocks-in-play.md`, `90-delivery-auditor.md`), **21 different**. The deployed copies are
  the *older* ones — the repo is ahead by 52,388 bytes (485,815 vs 433,427). Measured examples:

  | deployed | repo | difference |
  |---|---|---|
  | `09-…`: "connector catalog exposes **15 tools**, ALL media/email" | "exposes **133 tools** — 118 `connector__github__*` … **re-verified 2026-10-31**" | stale inventory |
  | `09-…`: "Yahoo's JSON endpoints return HTTP 429 … persistent rate limiting" | "Yahoo's JSON endpoints are **working again** … **Do not hard-code a Yahoo-avoidance path**" | stale, and it contradicts the fetched contract (see D1) |
  | `09-…`: no `MCP AVAILABILITY PROBE` | probe block present (681 b) | pending addition |
  | `25-…`: no "BEFORE honouring the weekend branch — check WHEN THIS FIRE WAS SCHEDULED" | 6,484-byte delayed-replay section present | the fix for a real mis-dated artifact is **not running** |
  | `91-…`: no `CONVERSATION TITLE` step, no "STEP 2b — CONVERSATION HYGIENE" | both present | pending addition |
  | `01-…`: 4,272 b, no purpose/changes preamble | 6,819 b with the "Three probe layers" rationale | pending addition |

- **Proposed state:** treat `cloud-prompts/cron-prompts/*.md` as the only artefact of record; add a
  check to the existing `91-schedule-drift-guard` cron — it already reads the live scheduler, so it
  already has the `cron_read` JSON:

  ```text
  ## STEP 2c — PROMPT DRIFT (repo vs deployed)
  For each task in $CHUNK: sha256(task.prompt) vs sha256(cloud-prompts/cron-prompts/<name>).
  Report `PROMPT-DRIFT` (repairable: re-push the repo blob) separately from schedule drift.
  ```

  and fix the drift by re-pushing, **not** by hand-editing the platform copy.

- **Token impact:** **0 tokens.** This is a correctness proposal.
- **Quality impact:** the highest-leverage change in the document, and it costs nothing. (a) The
  delayed-replay date rule exists in the repo for #25 and is **not deployed**, so a re-dispatched
  fire still publishes under the execution date — the exact failure the repo text was written to
  fix. (b) The 429-vs-200 contradiction persists because the *prompt* was updated but the
  *contract* was updated separately, and only one of them is in the running fleet. (c) The
  **#90 `| head -3` trap is live in both copies** — deploying alone does not fix it, but D11 is
  what makes the D2 script fix land on every routine.
- **Risk / migration note:** re-pushing 21 prompts is 21 `cron_update` calls, and a hand-pasted
  long prompt drifts (the platform copy is not byte-safe — the `read` tool truncated a 7.2 KB
  prompt in a prior session). Migrate in batches of 3–4, and verify each push by **SHA-256 over
  the raw `response.tasks[].prompt` string from the persisted `cron_read` chunk**, not by reading
  the rendered preview. `cron_update` resets `timezone` if `schedule` is not resent, and `model`
  cannot be changed by `cron_update` at all — resend `schedule` + `timezone` on every call and
  re-read `model` afterwards. Rollback: the repo blob is the rollback source; keep the previous
  prompt text in `/workspace/cron-backup/prompts-v2/` before the first update.
- **Confidence:** **high** — the drift is measured byte-for-byte on all 23 prompts.

---

### D2 — Move GIT PUSH and DELIVERY VERIFICATION into executable scripts

- **Target:** repo shared file (`_shared/push_artifact.sh`, `_shared/verify_delivery.sh`) + the
  plaintext metainstructions (replace **both** blocks with one fetch-and-call stub).

- **Current text/state:**
  - `## GIT PUSH (OPTIONAL)` — 21 prompts, **3,190 b/prompt**, 67,000 b fleet, median **17.6 %**
    of a prompt. Of one main-target prompt (repo
    `cloud-prompts/cron-prompts/09-stock-screener-daily-sweep-18:30.md:250`) the block is
    **3,255 b** = 2,281 b of bash + 974 b of prose.
  - `## DELIVERY VERIFICATION` — 21 prompts, **1,468 b/prompt**, 30,841 b fleet.
  - Combined, the two blocks cost **4,690–4,874 b in the 20 main-target prompts and 2,178 b in
    #90** (97,820 b fleet-wide).
  - The bash bodies are **byte-identical except for 3 lines**. Measured diff between #09 and #19
    after normalising the routine name:

    ```diff
    -  mkdir -p "$WT/daily-screens"
    -  cp -r "/workspace/daily-screens/." "$WT/daily-screens/" 2>/dev/null || true
    -  git add daily-screens                 # ONLY this cron's output directory
    +  mkdir -p "$WT/earnings"
    +  cp -r "/workspace/earnings/." "$WT/earnings/" 2>/dev/null || true
    +  git add earnings/$DATE-reminders.md                 # ONLY this cron's output directory
    ```

  - **#90 is structurally different and is where the bug is.** `cron-prompts/90-delivery-auditor.md:449`
    opens its own `## GIT PUSH (OPTIONAL)`, and at **line 482** it runs:

    ```bash
    git push -q origin HEAD:refs/heads/audit/status 2>&1 | head -3
    ```

    That is the `git push … | head -3` exit-status trap **live in code**: `head`'s exit status
    (always 0) is what the shell reports, so a **rejected push reports success**. It also pushes
    to **`refs/heads/audit/status`**, not `main`, and stages only `_audit/status.json`
    (`90-delivery-auditor.md:474`), with a hardcoded worktree `rm -rf /workspace/.wt` at `:469`.
    The remaining 20 prompts use the correct form
    (`if git push -q origin HEAD:main 2>/tmp/push.err; then`) and push to `main`. A fleet-wide
    scan of all deployed bash blocks for `| head` / `| tail` masking found **this as the only
    exit-status-masking instance**; the other five hits are benign output truncation
    (`#01` `| head -40`, `#90` `| head -5` / `| tail -1`, `#91` `ls -t … | head -1`).
  - The artifacts show the push procedure has cost real work: on `main`,
    `e651b82 restore: 10 SKIPPED audit records lost in cron #12's 2026-10-26 push`,
    `0b418c3 restore: AGENTS.md workspace conventions (deleted by cron #12 push 1356a03, …)`,
    `48d6175 cron #19: backfill: 2026-10-27 and 2026-10-28 artifacts (missed runs)`,
    `a25e0f7 cron 04 … backfill: undelivered 2026-09-28..2026-10-26 artifacts` — four separate
    recoveries from lost pushes.

- **Proposed state:** two scripts plus **one** stub replacing both blocks. The push **target must
  be a parameter**, because #90 does not push to `main`.

  `_shared/push_artifact.sh` — interface:
  `push_artifact.sh --out <output-dir> --add <repo-relative-path> [--branch <branch>]`;
  `--branch` defaults to `main`; `--add` is the single path to stage (never `.`). Exit codes:
  `0` = pushed and verified present on the remote branch; `3` = push rejected after 3 attempts;
  `4` = nothing staged (the artifact was never written); `5` = staged deletions detected;
  `6` = `GITHUB_TOKEN` unset (push skipped, artifact kept); `1` = usage/internal error.

  ```bash
  #!/usr/bin/env bash
  # push_artifact.sh --out <output-dir> --add <repo-relative-path> [--branch <branch>]
  #   --out    sandbox-relative directory this cron writes (e.g. daily-screens)
  #   --add    the ONE repo-relative path to stage (e.g. daily-screens/2026-11-02/daily-sweep.md)
  #   --branch target branch (default: main). Cron #90 uses audit/status.
  # Exit: 0 pushed+verified | 3 rejected after 3 attempts | 4 nothing staged
  #       | 5 staged deletions | 6 token unset (skipped) | 1 usage/internal error
  set -uo pipefail
  OUT=""; ADD=""; BR="main"
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --out)    OUT="${2:?--out needs a value}"; shift 2;;
      --add)    ADD="${2:?--add needs a value}"; shift 2;;
      --branch) BR="${2:?--branch needs a value}"; shift 2;;
      *) echo "push: usage error: $1" >&2; exit 1;;
    esac
  done
  [ -n "$OUT" ] && [ -n "$ADD" ] || { echo "push: usage error: --out and --add are required"; exit 1; }

  if [ -z "${GITHUB_TOKEN:-}" ]; then
    echo "push: skipped (token unset)"; exit 6
  fi

  export GIT_SSL_CAINFO=/etc/ssl/certs/agent-identity/sandbox-gateway-ca.crt
  [ -f "$GIT_SSL_CAINFO" ] || GIT_SSL_CAINFO=/etc/ssl/certs/ca-certificates.crt
  export SSL_CERT_FILE="$GIT_SSL_CAINFO" CURL_CA_BUNDLE="$GIT_SSL_CAINFO"
  export HOME=/workspace/.home; mkdir -p "$HOME"
  git config --global http.sslCAInfo "$GIT_SSL_CAINFO"
  git config --global user.email "maxhermes-cloud@local"
  git config --global user.name "MaxHermes Cloud Cron"
  cd /workspace
  git init -q 2>/dev/null || true
  git remote add origin "https://x-access-token:${GITHUB_TOKEN}@github.com/karizaco/minimax-cloud-outputs.git" 2>/dev/null || \
    git remote set-url origin "https://x-access-token:${GITHUB_TOKEN}@github.com/karizaco/minimax-cloud-outputs.git"

  for attempt in 1 2 3; do
    git fetch -q origin "$BR"
    git worktree prune
    WT="/workspace/.wt.push.$$"
    rm -rf "$WT"
    git worktree add -f "$WT" "origin/$BR" >/dev/null 2>&1 || { echo "push: worktree FAILED"; exit 1; }
    # copy ONLY this cron's output directory, never the whole workspace
    if [ -d "/workspace/$OUT" ]; then
      mkdir -p "$WT/$OUT"
      cp -r "/workspace/$OUT/." "$WT/$OUT/" 2>/dev/null || true
    fi
    cd "$WT"
    # NEVER `git add -A`: a fresh sandbox would stage the whole branch as deleted.
    git add -- "$ADD" || { echo "push: git add FAILED"; exit 1; }
    STAGED="$(git status --short)"
    if [ -z "$STAGED" ]; then
      echo "push: ABORTED (nothing staged - the artifact was not written to /workspace/$OUT)"
      exit 4
    fi
    if printf '%s\n' "$STAGED" | grep -qE '^ D|^\s?D'; then
      echo "push: ABORTED (staged deletions detected - refusing to push)"; exit 5
    fi
    git commit -q -m "cron ${CRON_ID:-??} ${ADD} ${DATE:-}" || echo "push: nothing to commit"
    # CRITICAL: never pipe git push into `head`/`tail` - that takes the PIPE's exit status,
    # always 0, so a rejected push reports success.  (Cron #90 hit exactly this bug.)
    if git push -q origin "HEAD:refs/heads/$BR" 2>/tmp/push.err; then
      cd /workspace; echo "push: ok (attempt $attempt)"; exit 0
    fi
    echo "push: attempt $attempt rejected: $(head -1 /tmp/push.err | tr -d '\r')"
    sleep 5
  done
  cd /workspace
  echo "push: FAILED (3 attempts rejected - artifact NOT delivered)"
  exit 3
  ```

  `_shared/verify_delivery.sh` — interface:
  `verify_delivery.sh [--branch <branch>] <repo-relative-path> [<path> …]`; exits `0` if **every**
  path is present on the remote branch, `7` if any is missing.

  ```bash
  #!/usr/bin/env bash
  # verify_delivery.sh [--branch <branch>] <path> [<path> ...]
  # Exit: 0 all present | 7 at least one missing
  set -uo pipefail
  BR="main"; PATHS=()
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --branch) BR="${2:?--branch needs a value}"; shift 2;;
      *) PATHS+=("$1"); shift;;
    esac
  done
  [ "${#PATHS[@]}" -ge 1 ] || { echo "usage: verify_delivery.sh [--branch b] <path> [...]"; exit 1; }
  export GIT_SSL_CAINFO=/etc/ssl/certs/agent-identity/sandbox-gateway-ca.crt
  [ -f "$GIT_SSL_CAINFO" ] || GIT_SSL_CAINFO=/etc/ssl/certs/ca-certificates.crt
  export SSL_CERT_FILE="$GIT_SSL_CAINFO"
  cd /workspace
  git init -q 2>/dev/null || true
  git remote add origin "https://x-access-token:${GITHUB_TOKEN:-}@github.com/karizaco/minimax-cloud-outputs.git" 2>/dev/null || \
    git remote set-url origin "https://x-access-token:${GITHUB_TOKEN:-}@github.com/karizaco/minimax-cloud-outputs.git"
  git fetch -q origin "$BR"
  RC=0
  for p in "${PATHS[@]}"; do
    if git cat-file -e "origin/$BR:$p" 2>/dev/null; then
      echo "DELIVERY: ok (origin/$BR:$p present)"
    else
      echo "DELIVERY: FAILED (origin/$BR:$p NOT found)"; RC=7
    fi
  done
  exit $RC
  ```

  The two prompt blocks become **one** stub. For the 20 main-target prompts:

  ````markdown
  ## GIT PUSH + DELIVERY VERIFICATION (one call each)

  Fetch these two scripts (do not read them into context - just run them):

  ```bash
  B=https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared
  curl -sL -o /workspace/push_artifact.sh   $B/push_artifact.sh
  curl -sL -o /workspace/verify_delivery.sh $B/verify_delivery.sh
  ```

  After the artifact is written:

  ```bash
  CRON_ID=09 DATE=$(TZ=America/New_York date +%Y-%m-%d) \
    bash /workspace/push_artifact.sh --out daily-screens --add "daily-screens/$DATE/daily-sweep.md" --branch main
  bash /workspace/verify_delivery.sh --branch main "daily-screens/$DATE/daily-sweep.md" "daily-screens/$DATE/breadth.md"
  ```

  `push_artifact.sh` exits 0 = pushed and verified, 6 = `GITHUB_TOKEN` unset (skip the push, keep
  the artifact), 3/4/5 = real failure. Report the exit code verbatim: `push: ok (verified)` only
  when `verify_delivery.sh` exits 0. A silently failed push is worse than a loud one - say so and
  give the sandbox path.
  ````

  and for **#90** (different branch, different staged path) — 679 b:

  ````markdown
  ## GIT PUSH + DELIVERY VERIFICATION (one call each)

  ```bash
  B=https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared
  curl -sL -o /workspace/push_artifact.sh   $B/push_artifact.sh
  curl -sL -o /workspace/verify_delivery.sh $B/verify_delivery.sh
  bash /workspace/push_artifact.sh   --out _audit --add _audit/status.json --branch audit/status
  bash /workspace/verify_delivery.sh --branch audit/status "_audit/status.json"
  ```

  `push_artifact.sh` exits 0 = pushed and verified, 6 = `GITHUB_TOKEN` unset (skip the push, keep
  the file), 3/4/5 = real failure. Report the exit code verbatim: `push: ok (verified)` only when
  `verify_delivery.sh` exits 0.
  ````

- **Token impact** (measured: old blocks summed per prompt, new stub measured as written above):
  - 20 main-target prompts: old **4,782 b** avg → new **1,000 b** = **−3,782 b/run = −945 tokens/run**.
  - #90: old **2,178 b** → new **679 b** = **−1,499 b/run = −375 tokens/run**.
  - Fleet-fire: **−77,141 b = −19,285 tokens**. Fleet-day: **−320,665 b = −80,166 tokens**.
  - The script bodies (≈2.4 KB + 0.6 KB) are **not** context tokens — the agent runs them without
    reading them. This is the only category of "move to a shared file" that actually saves.

- **Quality impact:** the agent no longer re-derives a race-sensitive git procedure from prose on
  every fire, and a fix to the push procedure becomes a **one-line commit** instead of 21
  hand-edits that drift apart. Concretely, this proposal **fixes two live defects**:
  (i) **#90's `git push … | head -3` at line 482** — the script uses `if git push … ; then`, so a
  rejected push to `audit/status` can no longer be reported as success; (ii) **#90's push target
  and staged path** become explicit parameters instead of a different hardcoded block, so a
  future script that assumed `main` cannot clobber the wrong branch. The exit-code contract
  (`0`/`3`/`4`/`5`/`6`) makes "the push silently failed" unrepresentable — the current prose has to
  *spell out* `push: ok (verified)` vs `push: FAILED`, and that spelling-out is exactly what the
  `| head -3` bug defeated in #90. `git add -- "$ADD"` also makes the `git add -A` deletion
  disaster structurally impossible rather than merely warned against in prose — the repo records
  that `git add -A` deleted 283 files on 2026-10-25.

- **Risk / migration note:** the agent must fetch the scripts. **If the fetch fails the run loses
  its push** — the stub must say what to do: keep the artifact in the sandbox and reply
  `push: FAILED (helper fetch failed)` rather than silently skipping. The `raw.githubusercontent`
  stale-bytes window (measured 2026-11-02: raw served a stale blob for ~8 minutes after a push
  while the GitHub API and `git` were instant) means a **script edited minutes earlier may not be
  the one that runs** — acceptable for a stable script, but it means the script must not be
  changed in the same 10-minute window as the prompt that starts calling it. Deploy the scripts
  first, wait for the CDN to settle, then update the prompts. `GIT_SSL_CAINFO` points at
  `/etc/ssl/certs/agent-identity/sandbox-gateway-ca.crt`, which **does not exist in every sandbox
  image** (it is absent in this analysis sandbox) — the script falls back to
  `/etc/ssl/certs/ca-certificates.crt`. Rollback: the scripts are additive; restoring the old
  prompt blocks restores the old behaviour. One migration caveat: #90's `rm -rf /workspace/.wt`
  at `:469` is a **hardcoded** worktree path while the other 20 use
  `/workspace/.wt.$(date +%s)$$`; the script uses a unique `$$` path for every caller, which
  removes that collision too.

- **Confidence:** **high** — the three-line variance and the single live `| head -3` instance were
  both measured by scanning all 21 deployed bash blocks.

---

### D3 — Move the WINDOW CHECK into a script with flags as arguments

- **Target:** repo shared file (`_shared/window_check.sh`) + plaintext metainstructions.

- **Current text/state:** `## WINDOW CHECK` — 21 prompts, **2,065 b/prompt**, 43,350 b fleet,
  median **12.6 %** of a prompt. Deployed `09-…md` block = 2,311 b = 1,678 b bash + 633 b prose.
  After normalising the routine name the bash body is **1,614 b and identical in 10 of 21
  prompts**; the rest differ only in the four flag lines. Measured flag sets across the 21:

  | WEEKDAYS_ONLY | WEEKEND_ONLY | MARKET_HOURS_ONLY | DAY_OF_WEEK | n |
  |---|---|---|---:|---:|
  | true | false | false | 0 | 10 |
  | — (no parseable flags) | — | — | — | 3 |
  | true | false | true | 0 | 3 |
  | false | false | false | 7 | 2 |
  | false | true | false | 0 | 1 |
  | false | false | false | 3 | 1 |
  | false | false | true | 0 | 1 |

  → **6 distinct, well-formed flag combinations + 3 that do not parse at all.** That is the drift
  the task asked about, and it is real: the three unparseable ones are prompts whose block is
  headed `## STEP 1 — WINDOW CHECK` with a different flag layout.

- **Proposed state:**

  `_shared/window_check.sh` — flags as environment variables, so the per-prompt configuration is
  four short tokens and cannot drift in shape:

  ```bash
  #!/usr/bin/env bash
  # window_check.sh — env: WEEKDAYS_ONLY, WEEKEND_ONLY, MARKET_HOURS_ONLY, DAY_OF_WEEK,
  #                   HOUR_MIN, HOUR_MAX (optional hour gate),
  #                   SKIP_DIR, SKIP_NAME, SKIP_LABEL.
  # Exit: 0 in-window (prints "window-check: OK (<ET now>)") | 2 out-of-window (marker written)
  set -uo pipefail
  DOW=$(TZ=America/New_York date +%u); HOUR=$(TZ=America/New_York date +%H)
  REASON=""
  [ "${WEEKDAYS_ONLY:-false}" = "true" ] && [ "$DOW" -ge 6 ] && REASON="weekend (day=$DOW, expected Mon-Fri)"
  [ "${WEEKEND_ONLY:-false}" = "true" ] && [ "$DOW" -lt 6 ] && REASON="weekday (day=$DOW, expected Sat-Sun)"
  if [ "${DAY_OF_WEEK:-0}" -gt 0 ] && [ "$DOW" -ne "${DAY_OF_WEEK:-0}" ]; then
    REASON="wrong day (today=$DOW, expected day=${DAY_OF_WEEK})"
  fi
  if [ "${MARKET_HOURS_ONLY:-false}" = "true" ] && { [ "$HOUR" -lt 9 ] || [ "$HOUR" -ge 17 ]; }; then
    REASON="outside market hours (hour=$HOUR, expected 09-16 ET)"
  fi
  # Optional hour gate for routines with a post-close fire time (see #05's 2026-10-23 stub):
  #   HOUR_MIN=<n> HOUR_MAX=<n>  ->  skip unless the ET hour is within [HOUR_MIN, HOUR_MAX]
  if [ -n "${HOUR_MIN:-}" ] && [ "$HOUR" -lt "$HOUR_MIN" ]; then
    REASON="too early (hour=$HOUR, need ET hour >= $HOUR_MIN)"
  fi
  if [ -n "${HOUR_MAX:-}" ] && [ "$HOUR" -gt "$HOUR_MAX" ]; then
    REASON="too late (hour=$HOUR, need ET hour <= $HOUR_MAX)"
  fi
  if [ -n "$REASON" ]; then
    D=/workspace/$(TZ=America/New_York date +%Y-%m-%d)/"${SKIP_DIR:-.}"
    mkdir -p "$D"
    cat > "$D/${SKIP_NAME:-SKIPPED.md}" <<EOF
  # ${SKIP_LABEL:-cron} — SKIPPED
  - Date (ET): $(TZ=America/New_York date +%Y-%m-%d)
  - Time (ET): $(TZ=America/New_York date +%H:%M)
  - Reason: $REASON
  - No artifact produced.
  EOF
    echo "out-of-window: $REASON"; echo "no artifact; no push"; exit 2
  fi
  echo "window-check: OK ($(TZ=America/New_York date +"%Y-%m-%d %H:%M %u"))"
  ```

  The prompt block becomes (650 b):

  ````markdown
  ## WINDOW CHECK (run FIRST, before fetching the skill)

  ```bash
  B=https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared
  curl -sL -o /workspace/window_check.sh $B/window_check.sh
  WEEKDAYS_ONLY=true WEEKEND_ONLY=false MARKET_HOURS_ONLY=false DAY_OF_WEEK=0 \
  SKIP_DIR=daily-screens SKIP_NAME=SKIPPED_stock_screener_daily_sweep_18:30.md \
    bash /workspace/window_check.sh
  ```

  Exit 2 = out-of-window: the `SKIPPED_*.md` marker IS that fire's artifact — do not fetch the
  skill, do not call MCPs, do not push. If the fetch fails, continue without the check and note
  `window-check: unavailable` in `## Source health`.
  ````

- **Token impact** (measured): 2,065 b → 650 b = **−1,414 b/run = −353 tokens/run**; ×21 =
  **−29,700 b = −7,425 tokens**/fleet-fire; **−123,124 b = −30,781 tokens**/fleet-day. The
  1,614 b script body never enters context.

- **Quality impact:** (1) The 6-variant drift disappears — the *shape* of the check becomes
  identical everywhere and only four values vary, so a fix lands once. (2) The current prose says
  different things about what a skip means in each of the 21 copies, including the one place
  where it matters most: the `#25-ntrt-gap-brief` repo text adds "A weekend/weekday mismatch is
  a signal to check the scheduled date, **not to skip**". In a script that rule is one `if`; in
  prose it is 6,484 bytes duplicated across the fleet — and in the deployed fleet it is **absent
  entirely** (D11). (3) The skip marker path/label become parameters, so the marker filename can
  no longer drift away from the routine name. (4) **The check currently fails in both directions,
  and the artifacts prove both.** It *over*-skips: every weekend up to 2026-10-24 produced a
  `SKIPPED_*` marker even though the scheduler already encoded the day-of-week. And it
  *under*-skips: `international-eod/2026-10-23/STUB_no_market_data_source.md` records *"Window
  check passed … because the preamble carries no hour-of-day gate (`MARKET_HOURS_ONLY=false`).
  Fire at 05:34 ET … ~11 h before the 16:35 ET target"* — a misfire the check waved through,
  costing 16 consecutive empty fires. The agent's own recommendation is *"add an hour gate (skip
  unless ET hour >= 16) to the preamble"*; a single script with a single flag vocabulary is where
  that gate goes.

- **Risk / migration note:** same fetch-failure exposure as D2 — if `window_check.sh` cannot be
  fetched, the safe default is to **continue** (the scheduler already guarantees the day; the
  check is a belt-and-braces guard, as the prompts themselves state) and say so in the reply, not
  to abort the run. The stub above says exactly that. This is a deliberate inversion of the
  current instruction, where a missing block means an unguarded run. Rollback: restore the old
  blocks.

- **Confidence:** **high** — flag variance measured across all 21 deployed prompts.

---

### D1 — Regenerate the in-prompt RUNTIME DATA-SOURCE CONTRACT instead of deleting it

- **Target:** plaintext metainstructions (and the shared contract, as the single source).

- **Current text/state:** `## RUNTIME DATA-SOURCE CONTRACT` — 19 prompts, **1,827 b** each
  (2,202 b in `17-us-stocks-in-play.md`), 35,677 b fleet, median **10.2 %** of a prompt.
  Deployed `09-…md` block, quoted in part:

  > **Measured 2026-10-28 from this sandbox — Yahoo's JSON endpoints return HTTP 429** (spark,
  > chart, and screener alike) … it is persistent rate limiting, not a transient burst.

  and

  > only. Verified 2026-10-28: the connector catalog exposes 15 tools, ALL media/email

  The block ends with a pointer:

  > Full endpoint list + measured status: `https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/RUNTIME-CONTRACT.md`

  **The contradiction.** The fetched contract (`cloud-prompts/_shared/RUNTIME-CONTRACT.md`,
  21,809 b) says the opposite about the same endpoint:

  > | **Yahoo chart** | `…/v8/finance/chart/{SYM}…` | **200 OK** — daily bars … |
  > | **Yahoo screener** | `…/v1/finance/screener/predefined/saved…` | **200 OK** … |
  > | **Yahoo quoteSummary** | `…/v10/finance/quoteSummary/…` | **200 OK with the crumb** … |

  and it describes a 48-tool `market-recap` MCP pack that the prompt does not mention. So 19
  running prompts simultaneously tell the agent "Yahoo is hard-blocked, use the bridge" and
  "Yahoo is 200 OK, and here is a richer bridge pack". Measured overlap: 6-gram overlap with the
  contract is 83–87 %, but a **line-level** check finds only **86 of 1,827 bytes** literally
  present in the contract — the block is a **stale fork**, not a copy.

- **Proposed state:** replace the block, in all 19 prompts, with this **857 b** version:

  ```markdown
  ## RUNTIME DATA-SOURCE CONTRACT (read before fetching any data)

  **The `mcp__*` tools named above DO NOT EXIST in this runtime.** Do not attempt an MCP call and do
  not wait for one to appear — a tool-not-found error converts into an early abort with no artifact.
  Use instead: `web_search`, `web_fetch`, `bash` (curl, python3), `connector__github__*`.
  `web_search` uses a DIFFERENT egress than curl, so it survives when curl is blocked.

  **Order of attack: MCP bridge -> `web_search` -> curl ladder.** Try the ladder in cost order and
  fall through on a real failure. A 429/403 is a RATE LIMIT, not a missing symbol: retry once, then
  fall through. Sanity-check the response BODY, not just the HTTP status.

  Full endpoint list + measured status:
  `https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/RUNTIME-CONTRACT.md`
  ```

  The three paragraphs that were removed (the connector-catalog inventory, the stale Yahoo-429
  narrative, the "also confirmed working" endpoint inventory) must first be **written into
  `_shared/RUNTIME-CONTRACT.md`** in their current, correct form — the contract already carries
  the 200-OK table and the `market-recap` pack, so the removal is a deletion of stale text, not a
  loss of information. The prompt keeps the *rules*; the contract keeps the *inventory*.

- **Token impact** (measured): 1,827 b → 857 b in 18 prompts and 2,202 b → 857 b in #17 =
  **−1,021 b/run = −255 tokens/run** on average; ×19 = **−19,394 b = −4,848 tokens**/fleet-fire;
  **−80,954 b = −20,238 tokens**/fleet-day. The contract itself grows by ≈0 (the content was
  already there, in a newer form).

- **Quality impact — this is the important one.** The saving is small; the correctness gain is
  not. Right now a routine that reads the prompt first tries the **bridge → web_search ladder**
  because "Yahoo is 429", and a routine that reads the contract first queries **Yahoo directly**
  because "Yahoo is 200 OK". Two routines in the same fleet can therefore reach different numbers
  for the same symbol on the same day, and neither is wrong on its own reading. The "pick one
  primary source per field" rule that exists in only **2 of 20** routines (see D5) is defeated when
  the prompt and the contract disagree about whether a source is even available. Fixing the fork
  restores a single source of truth, and lets D5's precedence rule actually hold.

  **Why this is NOT "move it to a fetched file".** A naive reading — replace the block with just
  the URL — is a **net loss of ~5,000 tokens per run**: the agent would have to read the 21,809 b
  contract (5,452 tokens) instead of a 1,827 b summary (457 tokens), and would have to do so on
  most runs because the summary is what lets it pick an endpoint without a fetch. That is the
  single most important thing this analysis found about "extract the shared boilerplate": **for
  anything the agent must read, a fetch is not a saving.** The prompt must keep a short, *correct*
  summary; the contract must hold the inventory; and a single mechanism must keep them in
  agreement.

- **Risk / migration note:** if the trim removes an endpoint the agent needed, it will fetch the
  contract and spend +5,452 tokens on that run — so the trimmed summary must retain the ladder's
  *order* and its most-used endpoints, not just the rules. The two "conflict" rules (the
  `market-recap` pack and the `mcp__*` non-existence) are the ones most likely to be lost in a
  careless trim; they are kept above. Rollback: the old block is in git history; and because this
  edit touches 19 prompts, deploy it with the same SHA-256 verification as D11.

- **Confidence:** **high** on the measurement, **medium** on the exact endpoint set the trimmed
  summary should keep — that set should be chosen from the routines' actual failure history, not
  guessed.

---

### D5 — Add a fleet-wide source-precedence rule

- **Target:** plaintext metainstructions (a new rule in the shared `### Rules` block).

- **Current text/state:** searching all 23 deployed prompts for
  `disagree|conflict|precedence|source of truth|which wins|contradict` returns matches in only
  **four** prompts, and only **two of them carry a usable precedence rule**:

  - `deployed/19-earnings-reminder-daily.md:229` — "**Rule C — conflicting estimates.** Pick ONE
    primary source per field and say which: Yahoo for … disagree beyond tolerance (market cap
    >5 %, EPS >2 %), note the spread in the artifact."
  - `deployed/15-earnings-reaction-scanner.md:365` — "screener and Yahoo disagree on a move you
    are about to publish — investigate before shipping."

  **20 deployed prompts carry a `### Rules` block** (the market-data routines); **18 of those 20
  define no precedence rule**. (The 21st Rules-titled section is `# Rules` in
  `01-weekly-mcp-health-check.md`, a probe checklist for the weekly diagnostic, not a source
  contract.) Yet every market-data routine pulls from the **same** overlapping source set (MCP
  bridge `market-recap`, Yahoo JSON, Yahoo HTML, `web_search`, TradingView scanner, Nasdaq API)
  and every one of them publishes prices. Two routines can publish different values for the same
  ticker on the same day with no rule saying which is authoritative — and the artifacts are read
  side by side.

  **The artifacts show this failing twice, in both directions:**
  - `4cf4239 cron 25: correct the oct-29 narrative — ADT is an OPENING gap lost to a stale
    pre-market tape, not a recovered pre-market gap`. A published gap was built on a stale
    pre-market print and had to be **corrected the next day**. A stale tape is a *source* problem,
    not a *fabrication* problem, so Rule 3 ("never fabricate a number") did not catch it — the
    number was real, just from the wrong snapshot.
  - `international-eod/2026-10-23/STUB_no_market_data_source.md`: a routine concluded there was
    "no market-data source available", on the basis that its declared `mcp__*` tools were not
    registered — while the same prompt's `### PRIMARY SOURCE` section says those same servers are
    reachable over plain HTTPS JSON-RPC.

- **Proposed state:** add to the shared `### Rules` block this **611 b** rule:

  ```markdown
  7. **One number per field, one source per field.** When two sources give different values for
     the same field, pick ONE and say which in `## Source health`: the bridge's `market-recap`
     for prices and movers (it is Yahoo-sourced and not rate-limited), the TradingView scanner
     for pre-market/RVol, Yahoo JSON for history and fundamentals. If they disagree beyond
     tolerance (price >0.6 %, volume >5 %), **investigate before shipping** — say which source you
     used, the spread, and why. Never publish two values for the same field, and never silently
     mix a mid-session print with a settled close.
  ```

- **Token impact:** **net cost of 611 b = 152 tokens per run** (×20 = 12,220 b = 3,055 tokens per
  fleet-fire; **51,324 b = 12,831 tokens** per fleet-day). This proposal **costs tokens on
  purpose.**
- **Quality impact:** it is the single highest-value change to the *output* of the fleet, and it
  is the reason the task brief put quality first. Without it the fleet's cross-routine numbers
  are not comparable, and the "Never fabricate a number" rule (Rule 3) protects against invented
  values but says nothing about *two real but different* values — which is exactly the ADT
  correction above. The tolerance figures are taken from the two rules that already exist in the
  fleet (0.6 % from the repo's #25 text, ">5 % / >2 %" from #19's Rule C) rather than invented.

  **A warning the artifacts give us.** Rule 5 already mandates that every artifact carry a
  `## Source health` section naming each source and its status — and it is present in only
  **90 of 256** migration-era artifacts (**35 %**). A rule buried inside a 1,304-byte block in a
  20 KB prompt is not self-executing. D5's precedence rule will be ignored at the same rate
  unless it is **short**, and unless the reply format asks for the source choice explicitly.
  So D5 should ship together with one line in the `### Method & caveats` bullet list: *"name the
  primary source per field and any spread between sources"* — a rule that is also checked by the
  delivery auditor is a rule that gets followed.
- **Risk / migration note:** the risk is over-rigidity — a rule that says "always prefer the
  bridge" could suppress a better source where the bridge is stale and Yahoo is fresh. That is
  why the rule names the source *per field type* and requires the agent to investigate and
  disclose a spread rather than silently pick. Since it must be identical across the fleet, put it
  in one place and propagate it (the `### Rules` block is already 10 of 21 byte-identical, so
  there is a natural template).
- **Confidence:** **medium** — the ambiguity is measured and the rule's shape follows two
  existing in-fleet precedents, but the per-field source assignment should be reviewed against
  what the sources actually returned in the last week of artifacts before fleet-wide rollout.

---

### D12 — Date the artifact to the fire's *scheduled* date, not the execution date

- **Target:** plaintext metainstructions (the `## OUTPUT` block, 18 prompts).

- **Current text/state:** `deployed/25-ntrt-gap-brief-daily.md`, `## OUTPUT`:

  > The `{date}` placeholder is today in US/Eastern, `YYYY-MM-DD`. Resolve it as the first step.

  The **repo** version of the same prompt adds a 6,484-byte section that is **not deployed**:

  > A weekday routine can execute on a **weekend**: the platform's Token Plan quota wall (error
  > 2067) kills the session at its scheduled time and the platform re-dispatches the SAME session
  > later … Measured 2026-11-01: this routine's 2026-10-30 09:00 ET fire … was re-dispatched and
  > executed on **Sunday 2026-11-01 01:51 ET**. The weekend guard fired on `DOW=7`, which would
  > have **discarded a real trading-day brief**.

- **Proposed state:** one **426 b** rule in the shared `## OUTPUT` block, replacing the "today in
  US/Eastern" clause:

  ```markdown
  The `{date}` placeholder is the fire's **scheduled** date in US/Eastern, `YYYY-MM-DD`. Resolve it
  from the run's `scheduled_at_ms` (`cron_read view=runs` -> `run.scheduled_at_ms`), not from
  `date` at execution time. If they differ, this is a **delayed replay**: rebuild for the
  scheduled date, do NOT write a SKIPPED marker, and say in the artifact that it is a
  reconstruction produced late. A replay is normal, not an error.
  ```

- **Token impact:** **net cost of 426 b = 106 tokens per run** (×18 = 7,668 b = 1,917 tokens per
  fleet-fire; **31,524 b = 7,881 tokens** per fleet-day). Deliberately a cost.
- **Quality impact:** this is a correctness rule, not a style rule. The repo text documents a
  real, measured incident: a 2026-10-30 brief was executed on 2026-11-01 and the weekend guard
  would have discarded it, writing a SKIPPED marker that falsely claimed a Sunday skip. Worse,
  the repo explains that dating the artifact to the execution day "lands it under a date the
  delivery auditor never expected, and its staleness check … reads it as 'routine is current' and
  **masks the real gap**". A mis-dated artifact is worse than a missing one, because it actively
  conceals a gap from the auditor. Hoisting the rule from #25 to all 18 OUTPUT-bearing prompts
  makes the behaviour uniform and, per D11, actually deployed.
- **Risk / migration note:** it needs one `cron_read view=runs` call, which the agent may not be
  able to make (the tool is absent in some sessions — see Notes). Make it best-effort with a
  documented fallback: if `scheduled_at_ms` cannot be read, use today's ET date and note
  `date_basis: execution` in the artifact. It must never block the artifact.
- **Confidence:** **medium-high** — the failure is documented in the repo with a run_id and a
  date; the mechanism (re-dispatch after a quota wall) is platform behaviour I could not
  re-observe from inside this sandbox.

---

### D10 — Trim CRITICAL REMINDERS to what is not already stated, and unify the reply format

- **Target:** plaintext metainstructions.

- **Current text/state:**
  - `## CRITICAL REMINDERS` — 21 prompts, **1,002 b/prompt**, 21,043 b fleet, median **4.8 %** of
    a prompt, in **9 verbatim variants** (the largest group is 11 identical prompts). Deployed
    `09-…md` tail:

    > 1. Skill URL above MUST be fetched first. If the fetch fails, write a stub artifact with
    >    `_source=skill_fetch_failed` and reply with the failure. Do NOT improvise the procedure
    >    from memory.
    > 2. Use ONLY the tools named in the RUNTIME DATA-SOURCE CONTRACT above (`web_search`,
    >    `web_fetch`, `bash`). Do NOT call the `mcp__*` tools — they are not registered in this
    >    runtime — and do not invent tool names.
    > 3. The cron session is fresh each time — there is no shared state. Treat every artifact as
    >    ephemeral unless pushed.
    > 4. If the cron fires outside its intended window … exit cleanly with "out-of-window:
    >    `<reason>`". Do NOT run a degraded version.

    Items 1, 2 and 4 are **restatements**: item 1 repeats the `## SKILL SPEC` block ("Do NOT skip
    this step"); item 2 repeats the `## MCP TOOLS AVAILABLE` block and the RUNTIME CONTRACT's
    "`mcp__*` tools … DO NOT EXIST"; item 4 repeats the `## WINDOW CHECK` block's
    "If the window check exits cleanly with 'out-of-window: <reason>', the cron is DONE". Only
    item 3 (fresh session) is new.
  - `## DELIVERY` (reply format) — 20 prompts, **1,469 b/prompt**, 29,399 b fleet, in **6
    variants**. The two dominant variants hold **16 of 20 prompts** and differ from each other by
    **exactly one newline** — i.e. they are the same text, copied 16 times with 4 outliers
    (704–2,455 b) drifting around it.

- **Proposed state:** a **395 b** CRITICAL REMINDERS containing only what is not stated elsewhere:

  ```markdown
  ## CRITICAL REMINDERS
  1. The cron session is fresh each time — there is no shared state. Treat every artifact as
     ephemeral unless pushed.
  2. If the skill fetch fails, write a stub artifact with `_source=skill_fetch_failed` and reply
     with the failure. Do NOT improvise the procedure from memory.
  3. Never call a tool that is not in the RUNTIME DATA-SOURCE CONTRACT, and never invent one.
  ```

  and one canonical reply format (`## DELIVERY`) used by all 20 — the existing 1,394-byte text
  promoted verbatim as the single version, with the four outliers' unique requirements folded in
  (not deleted):

  ```markdown
  ## DELIVERY
  The final reply (the only thing delivered to the chat) MUST use this structure. There is **no
  line cap** — cap by NAMES SHOWN (top ~8 per tier), not by lines. Long-form detail belongs in
  the artifact file, not in the chat.

  1. **Prose opener** — 2-4 sentences: the headline finding of the run, then the caveat that most
     changes how it should be read. Complete sentences; no label lists, no clipped fragments.
  2. **`### Signal`** — tiered bullets, ONE ticker per line, each line a short clause naming the
     catalyst or setup. Follow the skill's chat rules for tier order, flags and the audit line.
     Lead with the top movers and the count of names, and give the source and any lag. State how
     many further names are in the artifact file.
  3. **`### Method & caveats`** — 2-4 bullets: source(s), lag, universe/screen size, and every
     degraded or blocked source. Name what could not be verified.
  4. **`### Files`** — one line per file written, with its sandbox path.
  5. **`### Push / errors`** — one line for push status (`push: ok (verified)` /
     `push: skipped (token unset)` / `push: FAILED (<reason>)`) and one line for `errors: <n>` —
     count of MCP failures that triggered fallback. 0 = clean run.

  Do not narrate tool calls. Tool call → result → write → push → reply.
  ```

- **Token impact** (measured): CRITICAL REMINDERS 1,002 b → 395 b = **−607 b/run = −152
  tokens/run**; ×21 = **−12,748 b = −3,187 tokens**/fleet-fire; **−43,768 b = −10,942
  tokens**/fleet-day. The reply format 1,469 b → ~1,400 b (the outliers fold into the canonical
  text, so the fleet average barely moves; the win is that the next edit lands once) = **−69
  b/run**, and the *variance* collapses from 6 variants to 1.

- **Quality impact:** two effects, and the second is the one that matters. First, an agent that
  reads the same rule three times in one prompt spends attention on it three times and the tail
  becomes wallpaper — removing the restatements makes the remaining reminders land. Second,
  **the reply format is the artifact the user actually reads**, and it is currently the most
  duplicated block in the fleet (16 byte-identical copies of one text). The task asked whether the
  reply rules are "long and low-yield versus ones that change output quality" — measured answer:
  the reply spec is *not* the low-yield part. It is 1,394 bytes that define the only thing
  delivered to the chat, it delegates tier order to the skill rather than restating it
  ("Follow the skill's chat rules for tier order, flags and the audit line"), and it is already
  well-designed. The savings here are therefore small and come from deduplication, not from
  cutting quality rules. **I am not proposing to shorten the reply spec** — that would trade
  output quality for a few hundred bytes.

- **Risk / migration note:** the risk is dropping a reminder that was load-bearing in a specific
  failure. Item 2 in the current text ("write a stub artifact with `_source=skill_fetch_failed`")
  is load-bearing — the outputs repo contains
  `international-eod/2026-10-22/STUB_skill_fetch_failed.md`, so it has fired in the wild; it is
  retained above. Item 4 (out-of-window) is load-bearing and is **not** deleted here — it is
  deleted from CRITICAL REMINDERS because the WINDOW CHECK block already states it verbatim, but
  D3's script stub keeps it in the window block. After D3, re-check whether CRITICAL REMINDERS
  is needed at all.

- **Confidence:** **high** on the duplication measurement; **medium** on which reminders are
  load-bearing (item 3 — "the cron session is fresh" — has no observed failure attached to it
  either way, so it is kept as the one genuinely non-redundant line).

---

### D4 — Shrink the MCP AVAILABILITY PROBE to a pointer

- **Target:** plaintext metainstructions.

- **Current text/state:** the probe block exists in **1 deployed prompt** (`17-us-stocks-in-play.md`,
  **1,580 b**) and in **20 repo prompts** — where it is **681 b in 19 of them** and 1,580 b in
  #17. Measured with `re.search(r'### MCP AVAILABILITY PROBE.*?(?=\n## |\n### |\Z)')` over each
  file: repo total **14,519 b** across 20 prompts. Repo `09-…md:118`:

  > ### MCP AVAILABILITY PROBE (non-blocking, one cheap call)
  >
  > Run `python3 /workspace/probe_mcp.py` at the start of the run (fetch it from
  > `cloud-prompts/_shared/probe_mcp.py` if missing) and record the result in this run's
  > `## Source health`. It prints exactly one of three states:
  >
  > - `catalog_ok total=N finance_tools=0` — catalog healthy, no financial MCP registered yet.
  > - `catalog_ok total=N finance_tools=K` — **a financial MCP has LANDED. Switch to it this run.**
  > - `catalog_unreachable` — the probe itself failed. This is **NOT** evidence that no MCPs exist.
  >
  > The weekly `mcp-health/` routine does the same probe on a slower cadence; this in-run probe is
  > the fast path.

- **Proposed state:** the script is **already fetched and run** — it is not read into context —
  so only the prose costs tokens. Replace the block with this **551 b** version:

  ````markdown
  ### MCP AVAILABILITY PROBE (non-blocking, one cheap call)

  ```bash
  B=https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared
  [ -s /workspace/probe_mcp.py ] || curl -sL -o /workspace/probe_mcp.py $B/probe_mcp.py
  python3 /workspace/probe_mcp.py
  ```

  Record the printed state in `## Source health`. `finance_tools=K` with K>0 means a financial MCP
  has landed — switch to it this run. `catalog_unreachable` is NOT evidence that no MCPs exist.
  (The weekly `mcp-health/` routine runs the same probe on a slower cadence.)
  ````

  The three-state table moves into `_shared/probe_mcp.py`'s own docstring, where a developer who
  changes the probe will find it.

- **Token impact** (measured): 681 b → 551 b in 19 repo prompts and 1,580 b → 551 b in #17 =
  **−175 b/run = −44 tokens/run** on average; ×20 = **−3,499 b = −874 tokens**/fleet-fire;
  **−15,415 b = −3,853 tokens**/fleet-day. **This saving is against the repo state, not the
  deployed state** — the deployed fleet has the block in 1 prompt only (#17), so the deployed
  saving from D4 is 1,580 − 551 = **1,029 b = 257 tokens**.

- **Quality impact:** the probe earns its keep — it is the *fast lane* that detects a newly
  registered financial MCP days before the Sunday health check would. But the current cost is
  carried as **prose the agent must read every run to learn three strings that the script
  prints**. Putting the strings in the script's docstring and the behaviour in the prompt keeps
  100 % of the detection value at ~80 % of the context cost — and the prompt gets *more* robust:
  the current text requires the agent to fetch the script itself and to interpret three states
  from memory; the new text fetches and runs it, and the output is self-describing.

  One honest caveat: the weekly `mcp-health/` routine already runs the same probe and appends
  to `mcp-health/ledger.md` (the outputs repo shows `cron 93 mcp-health weekly 2026-11-01:
  catalog 133/0 finance, 6/6 bridge packs answer, 8/8 endpoints 200 - no change`). The in-run
  probe's value is the *latency* (mid-week vs Sunday), not the *information*. If that latency is
  not wanted, the probe can be dropped from the 18 routines that do not read finance MCPs, and
  kept only in the two whose output would change if a finance MCP appeared. That variant saves a
  further ~12,000 b/fleet-fire but loses a week of detection latency — I recommend the trim above
  rather than the removal.

- **Risk / migration note:** none material. If `probe_mcp.py` cannot be fetched, the probe is
  skipped — it is explicitly non-blocking, and `catalog_unreachable` already carries the right
  semantics.

- **Confidence:** **high** on the size measurement; **medium** on the "keep the probe" judgement,
  which is a policy call the user should make.

---

### D7 — Delete HELPER SCRIPTS (PYTHON) where the routine's skill references no helper

- **Target:** plaintext metainstructions.

- **Current text/state:** `## HELPER SCRIPTS (PYTHON)` — 18 prompts, **903 b/prompt**
  (16,249 b fleet), median **5.1 %** of a prompt, in **13 verbatim variants** (largest group 4).
  Deployed `09-…md`:

  > Local Mavis called Python helpers like `python screen.py emit-sql ...` to do file I/O, parsing,
  > and atomic writes.
  > **On Cloud, do NOT call those helpers — they don't exist here.** Re-implement the helper's job
  > inline using tool calls:
  >   - SQL generation → emit SQL directly (see skill's reference docs if attached).
  >   - Finviz URL building → construct URL inline (see skill's filter spec).
  >   - Finviz HTML parsing → parse with regex/text extraction in agent context.
  >   - Atomic file write → `write_file(path, content)` (already atomic).
  >   - Deduplication → do it in agent reasoning before writing.
  >
  > If the skill spec references a helper under `scripts/`, fetch the helper's URL too:
  > `…/skills/stock-screener-suite/scripts/<name>.py`
  > Read it for reference, but do NOT execute it. Re-implement its logic.

  **Which routines actually need this?** Classified by scanning each routine's own skill for any
  helper reference (`.py`, `scripts/`, `emit-sql`, `screen.py`, `helper`) — 20 skills reference at
  least one helper; 13 do not. Of the 18 deployed prompts that carry the block:

  | classification | n | prompts → skill |
  |---|---:|---|
  | **KEEP** (the skill references a helper) | 10 | 02 → asia-pre-market-reactions · 04, 06, 08, 09, 10 → stock-screener-suite · 05, 20 → eod-watchlist-snapshot · 12 → cross-asset-correlation-snapshot · 26 → agentic-pre-market-brief |
  | **DROP** (no helper anywhere in the skill) | 8 | 13, 14 → macro-calendar-week · 16 → unusual-options-flow-daily · 17 → us-stocks-in-play · 19 → earnings-reminder · 22 → agentic-weekly-brief · 23 → agentic-post-market-brief · 25 → ntrt-gap-brief |

  The borderline cases, resolved by reading the skills:
  - `eod-watchlist-snapshot/SKILL.md` (→ #05, #20) references `run_intl_cron.py` (`:82`,
    `plan`/`finalize` subcommands), `assemble_eod_csv.py` (`:75`),
    `pull_international.py` (`:118`), `holiday_calendar.py` (`:120`) and a `universe_cache/`
    tree — **by bare filename, not under `scripts/`**. A narrow `scripts/`-only test misses all of
    them, which is exactly how they were mis-binned the first time.
  - `cross-asset-correlation-snapshot/SKILL.md` (→ #12) and `agentic-pre-market-brief/SKILL.md`
    (→ #26) each reference a `.py` helper.
  - `macro-calendar-week`, `unusual-options-flow-daily`, `us-stocks-in-play`, `earnings-reminder`,
    `agentic-weekly-brief`, `agentic-post-market-brief`, `ntrt-gap-brief` reference **no** helper
    at all.
  - #07 fetches `stock-screener-suite` but carries **no** `## HELPER SCRIPTS` block in either the
    deployed or the repo copy — it was never a candidate.

- **Proposed state:** delete the block from the **8 DROP** prompts, and keep it — shortened to
  **498 b** — in the **10 KEEP** prompts:

  ```markdown
  ## HELPER SCRIPTS (PYTHON)
  Local Mavis called Python helpers (`python screen.py emit-sql …`). **They do not exist here** —
  do not call them. Re-implement inline: emit SQL directly, build Finviz URLs inline, parse
  Finviz HTML with regex in agent context, use `write_file(path, content)` for atomic writes, and
  do deduplication in agent reasoning before writing. If the skill references a helper under
  `scripts/`, fetch its URL, **read it for reference but do NOT execute it**, and re-implement.
  ```

- **Token impact** (measured): 8 prompts × 903 b (deleted) + 10 prompts × (903 − 498 = 405 b)
  = **11,269 b = 2,817 tokens** per fleet-fire; **43,593 b = 10,898 tokens** per fleet-day.
  Per run: **−626 b = −157 tokens** on average across the 18 prompts.
- **Quality impact:** the current block is **instructing the agent about a failure mode it cannot
  encounter** — in 8 of 18 routines there is no helper to avoid. That is the worst kind of
  instruction: it spends context on a non-existent hazard while diluting the prompt, and it
  trains the agent to look for helpers that are not there. The instruction is not merely long,
  it is **mis-scoped**, and scoping it to the routines that actually have helpers is a
  correctness fix. The block's own instruction to fetch a helper and "read it for reference but
  do NOT execute it" is a good instruction — worth keeping where it applies, and the shortened
  version above keeps it.
- **Risk / migration note:** the classification is derived from the *current* skill files. If a
  routine's skill later gains a `.py` reference, its prompt must regain the block. The cleanest
  guard is a check like D11's: for each prompt, assert that it carries a HELPER SCRIPTS block
  **iff** its skill references a helper — using the **broad** pattern (`.py` anywhere, not just
  `scripts/`), which is the pattern that failed in the first submission. Note also that putting
  the guidance *in the skill file* alone would save nothing, because the agent already reads the
  skill; the saving comes from the **deletion in the 8 routines that do not need it**.

- **Confidence:** **high** — the skill-to-helper mapping was re-measured per routine with a
  broad pattern and the borderline skills were read.

---

### D8 — Delete the AUDIT LOG block

- **Target:** plaintext metainstructions (18 prompts).

- **Current text/state:** `## AUDIT LOG` — 18 prompts, **233 b/prompt**, 4,178 b fleet, median
  **1.3 %** of a prompt, in 4 variants (15 identical). Deployed `09-…md`:

  > Local Mavis wrote an audit line to a Windows audit file after every run.
  > **On Cloud, skip audit log writes.** Audit is not needed here. If something goes wrong, the
  > failure is in the chat reply and the (missing) artifact.

- **Proposed state:** delete the block.
- **Token impact** (measured): **−233 b/run = −58 tokens/run**; ×18 = **−4,178 b = −1,048
  tokens**/fleet-fire; **−17,234 b = −4,308 tokens**/fleet-day.
- **Quality impact:** small, but the block is **purely negative** — it tells the agent not to do
  something that was never possible in this runtime, and it mentions "a Windows audit file",
  which is a fact about the *old* platform. The last sentence is the only load-bearing part and
  it is already covered: "the failure is in the chat reply and the (missing) artifact" is exactly
  what the `## DELIVERY` reply format requires (`### Push / errors`, `errors: <n>`). Once the
  Windows era is fully closed, keeping a rule about a Windows file is context spent defending
  against a hazard that cannot occur, and it nudges the agent to look for an audit trail it will
  never find.
- **Risk / migration note:** keep the block in the `01-weekly-mcp-health-check.md` and
  `90-delivery-auditor.md` prompts if either still references a local audit file — check those
  two individually. Otherwise delete. The one thing the block must never do is stop the agent
  reporting errors: that duty is already in the reply format.
- **Confidence:** **high** on the size; **low** on the residual risk — this is a pure-deletion
  proposal and the only question is whether any routine still writes a local audit file, which I
  could not verify from the sandbox.

---

### D9 — Merge ZERO-FALLBACK POLICY into the Rules block

- **Target:** plaintext metainstructions (18 prompts).

- **Current text/state:** `## ZERO-FALLBACK POLICY` — 18 prompts, **293 b/prompt**, 5,270 b fleet,
  in **3 variants** (16 of 18 byte-identical). Deployed `09-…md`:

  > The skill procedure uses a fallback chain (PRIMARY → FALLBACK → skip).
  > **Every fallback MUST terminate with:**
  >   "accept the partial result, write the artifact, and STOP. Do NOT chain `<deeper MCP>`."
  > Do NOT loop on MCP errors. Do NOT retry indefinitely. Do NOT re-raise.

  The task asked whether an agent reads "do not chain fallbacks" as "abort and write nothing".
  **Measured answer: the block is already protected against that**, and the protection is
  elsewhere. The Rules block, 300 bytes further down, ends with:

  > 6. **Partial data beats no data.** If some symbols resolved and others did not, WRITE the
  >    artifact with the symbols you have, mark the gaps, and report `errors: <n>`. Do not abort the
  >    whole run because one source was blocked. The zero-fallback policy governs the *fallback
  >    chain*, not whether the artifact gets written.

  That sentence is present in **20 of 20** deployed prompts that have the block (verified by
  grep) and in 20 of 20 repo prompts. So the literal "abort and write nothing" failure mode is
  **already mitigated fleet-wide** — but the artifacts show a **live variant** of it.
  `international-eod/2026-10-23/STUB_no_market_data_source.md` ends its run with:

  > Per the skill's hard rules and ZERO-FALLBACK POLICY, the run terminates here: no rows, no
  > invented values, no substitute source.

  The agent did write a stub, so it did not "write nothing" — but it wrote **zero data rows**,
  declared the problem "not fixable from inside the sandbox", and did so for **16 consecutive
  fires** (2026-09-28 → 2026-10-23) while a working HTTP path was documented in the same prompt.
  The remaining defect is also smaller and different: the phrase **"Do NOT re-raise"** is
  ambiguous. "Re-raise" is exception vocabulary; an agent can reasonably read it as "do not report
  the error" — the opposite of the intent, and the opposite of Rule 5 ("Never hide a degraded
  run") and of the reply format's mandatory `errors: <n>` line.

- **Proposed state:** delete the standalone block and fold it into `### Rules` as rule 6b, with
  the ambiguous clause fixed (this **408 b** rule):

  ```markdown
  6b. **One fallback, then stop.** The skill's chain is PRIMARY → FALLBACK → skip. Take at most
      one fallback step; do not chain deeper, do not loop on MCP errors, do not retry
      indefinitely. **Always report the failure** — a fallback that ends in `write the artifact,
      mark the gaps, report errors: <n>` is a good outcome. A failure you report is recoverable; a
      failure you swallow is not.
  ```

- **Token impact** (measured): the Rules block grows by 408 b while the 293 b block is deleted, so
  this is a **net cost of 115 b = 29 tokens per run**; ×18 = **−2,074 b = −519 tokens**/fleet-fire;
  **−8,602 b = −2,151 tokens**/fleet-day. The first submission claimed a saving here; measuring
  the real replacement text shows it is a small **cost**, because the rewrite has to spell out the
  reporting duty that the old block left implicit.
- **Quality impact:** the block's *behaviour* is right; its placement and its wording are not.
  Split across two headings 300 bytes apart, the agent has to hold the exception in one place and
  the rule in another, and the one genuinely ambiguous clause ("Do NOT re-raise") sits alone,
  unqualified, in the block that reads like "stop doing things". Folding it into the Rules list
  puts it next to "Never hide a degraded run" and next to "Partial data beats no data", which is
  the interpretation the fleet already implements in practice — and, on the evidence of the
  2026-10-23 stub, the interpretation it *fails* to apply when no source appears at all. The
  rewrite also replaces a prohibition with an instruction to *report*, which is what actually
  stops a silent failure, and it makes "try the next source in the ladder" explicit rather than
  leaving "do not chain" to do all the work.
- **Risk / migration note:** do not merge the block into the Rules list in a way that separates
  rule 6 and rule 6b — the whole point is adjacency. If the Rules list is generated, generate
  6 and 6b together. Rollback is trivial (it is a deletion plus an insertion).
- **Confidence:** **high** on the measurement; **medium** on the reading of "Do NOT re-raise" —
  that clause is ambiguous in English, and the fix is safe whichever way an agent read it.

---

### D6 — Replace MCP TOOLS AVAILABLE with one line naming the bridge first

- **Target:** plaintext metainstructions (17 prompts).

- **Current text/state:** `## MCP TOOLS AVAILABLE` — 17 prompts, **324 b/prompt**, 5,492 b fleet,
  in **13 variants**. Deployed `09-…md`:

  > - `mcp__tradingview_advanced__*`, `mcp__shibui_finance__*`
  > - `web_search`, `extract_content_from_websites` for catalyst/news research.

  and 90 bytes later, in the RUNTIME DATA-SOURCE CONTRACT:

  > **The `mcp__*` tools named above DO NOT EXIST in this runtime.** They are listed for provenance
  > only.

  So the fleet lists `mcp__tradingview_advanced__*`, `mcp__shibui_finance__*` and
  `extract_content_from_websites` — **three tools that are not registered** — and then immediately
  says they do not exist. The live catalog is 133 tools: 118 `connector__github__*`,
  13 `connector__matrix__*`, 2 `connector__email_workbench_credentials__*`.

- **Proposed state:** replace the **capability statement** with this **331 b** version, which
  names the bridge — the thing that actually works — first:

  ```markdown
  ## TOOLS AVAILABLE
  **The MCP-over-HTTP bridge** (`_shared/mcp_bridge.py` — see PRIMARY SOURCE) is the market-data
  source. Then `web_search`, `web_fetch`, `bash` (curl, python3), `connector__github__*` (repo
  writes). No `mcp__*` finance tools are registered in this runtime; `extract_content_from_websites`
  does not exist either.
  ```

  **#12 and #26 need a second step.** Their blocks are not just a tool list — they carry real,
  routine-specific operational guidance that must not be deleted:

  | prompt | block | the operational content inside it |
  |---|---:|---|
  | `12-cross-asset-correlation-snapshot.md` | 1,157 b | "**PRIMARY DATA PATH FOR THIS CRON:** the MCP bridge to the `shibui` server, which computes the correlation matrix SERVER-SIDE with DuckDB `corr()` in ONE call" + the `correlation_matrix.py` helper invocation |
  | `26-agentic-pre-market-brief.md` | 1,934 b | "**Cloud reality (verified 2026-10-23/24)**" — the Yahoo spark **batches of 12 max** limit, the working screener ids, the client-side filter (exchange list, price/mktcap/vol cuts), the **11 sector ETFs** to always pull, and the pre-market-gap formula (`last 1m-bar close` vs `regularMarketPrice`, **not** `chartPreviousClose`) |

  That guidance belongs in the **skill file** (it is endpoint/filter procedure, not a runtime
  capability statement), and the skill is already fetched and read on every run — so moving it
  there is **context-neutral**: the bytes still enter the run, they just stop masquerading as a
  tool list. Concretely: append #26's "Cloud reality" appendix to
  `cloud-prompts/skills/agentic-pre-market-brief/SKILL.md` and #12's "PRIMARY DATA PATH" block
  to `cloud-prompts/skills/cross-asset-correlation-snapshot/SKILL.md`, and give the prompt a
  one-line pointer.

- **Token impact** (measured, **including the skill side**):
  - 15 prompts whose block is only the 2-line tool list (115–205 b): 331 b replaces it, a cost of
    **+126 to +206 b each**.
  - #12: prompt −826 b, skill +826 b → **net 0**.
  - #26: prompt −1,603 b, skill +1,754 b (the appendix measured at `## MCP TOOLS AVAILABLE` →
    `## RUNTIME`) → **net +151 b**.
  - **Net context change: +1,889 b = +472 tokens per fleet-fire; +6,689 b = +1,673 tokens per
    fleet-day** — i.e. **+111 b = +27 tokens per run** on average across the 17 prompts. **D6 is a net token cost, not a saving.** The first submission reported a
    "+520 token fleet-day saving" for D6 by counting only the prompt side and ignoring that the
    moved content still enters the context; that was wrong, and it is corrected here.
- **Quality impact:** the current block is a **trap**, and the fleet has already fallen into it.
  It names three non-existent tools in the section an agent reads to learn what it may call, and
  the retraction ("they do not exist") is in a *different* section, several hundred bytes later.
  The RUNTIME CONTRACT says the reason out loud — "a tool-not-found error converts into an early
  abort with no artifact, via the zero-fallback policy" — i.e. the fleet already knows that
  calling one of these tools costs a whole run. And on 2026-10-23 it did exactly that: cron #5
  wrote `STUB_no_market_data_source.md` concluding there was no market-data source at all,
  because the tools listed in "MCP TOOLS AVAILABLE" were not registered — never reaching the
  bridge section that says the servers *are* reachable. **16 consecutive fires produced zero rows**
  (2026-09-28 → 2026-10-23) before that.
  Removing the names removes the temptation; naming the **bridge** first — the thing that
  actually works — makes the "no source" conclusion unreachable. The 13 variants are also 13
  different renderings of the same wrong list, so a future catalog change would have to be
  applied 13 times. And for #12/#26 the split is a genuine **organisation** win: a
  runtime-capability statement belongs in the prompt; endpoint and filter knowledge belongs in
  the skill — where the agent already looks for procedure.
- **Risk / migration note:** the prompt keeps a *provenance* mention, and the task's brief says the
  `mcp__*` names are "listed for provenance only". If provenance matters, keep it as a one-line
  parenthetical — `mcp__*` finance tools (previously provisioned; not currently registered) —
  rather than as a bulleted list of callable names. Do **not** list `extract_content_from_websites`
  as available; it is not in the 133-tool catalog.
- **Confidence:** **high** — the catalog inventory is verified in the outputs repo's own weekly
  report (`catalog 133/0 finance`).

---

## PRIORITISED CHANGE LIST

| # | id | what changes | where | tok/run | tok/fleet-day | quality effect | risk | effort |
|---|---|---|---|---:|---:|---|---|---|
| 1 | **D11** | Repo becomes the source of truth; deploy it; add a prompt-hash drift check to #91 | repo + process | 0 | 0 | **HIGH** — the delayed-replay date rule, the corrected catalog inventory and the 429→200 fix exist in the repo and are not running | push race during a 21-prompt re-deploy | M |
| 2 | **D5** | Add one source-precedence rule to the shared `### Rules` | plaintext | **−152** (cost) | −12,831 | **HIGH** — cross-routine numbers become comparable | over-rigid preference suppresses a better source | S |
| 3 | **D2** | `push_artifact.sh` + `verify_delivery.sh`, **push target as a parameter** | repo scripts + plaintext | +918 | +80,166 | **HIGH** — one place to fix the push; **fixes #90's live `\| head -3` trap and its wrong-branch target** | script fetch failure; CDN stale window | M |
| 4 | **D3** | `window_check.sh` with flags as env vars | repo script + plaintext | +353 | +30,781 | **MED-HIGH** — ends the 6-variant flag drift; adds the missing hour gate | script fetch failure | M |
| 5 | **D1** | Regenerate the RUNTIME CONTRACT summary; delete the stale fork | plaintext | +255 | +20,238 | **HIGH** — removes the live 429-vs-200 contradiction | over-trimming forces a contract fetch (+5,452 tok) | S |
| 6 | **D12** | Date the artifact to the fire's scheduled date | plaintext | **−106** (cost) | −7,881 | **HIGH** — a mis-dated artifact masks a real gap from the auditor | needs `cron_read view=runs`; best-effort fallback | S |
| 7 | **D10** | Trim CRITICAL REMINDERS to non-redundant lines; unify the reply format | plaintext | +151 | +10,942 | **MED** — fewer, sharper reminders; reply format stops drifting | dropping a load-bearing reminder | S |
| 8 | **D7** | Drop HELPER SCRIPTS from the 8 routines whose skill has no helper; shorten in the other 10 | plaintext | +156 | +10,898 | **MED** — stops warning about a hazard that cannot occur | skill later gains a helper reference | S |
| 9 | **D4** | MCP probe prose → pointer (repo-pending) | plaintext | +43 | +3,853 | **MED** — keeps detection, drops the essay | none | S |
| 10 | **D8** | Delete the AUDIT LOG block | plaintext | +58 | +4,308 | **LOW-MED** — removes a Windows-only rule | a routine still writing a local audit file | XS |
| 11 | **D6** | Replace the MCP TOOLS AVAILABLE list with one line; #12/#26's operational appendix moves into their skill | plaintext | **−27** (cost) | −1,673 | **MED-HIGH** — stops 15 prompts naming three non-existent tools | provenance listing wanted | XS |
| 12 | **D9** | Merge ZERO-FALLBACK into Rules; fix "Do NOT re-raise" | plaintext | −28 (cost) | −2,151 | **MED** — the failure-reporting rule sits with the degraded-run rule | negligible | XS |

**Cumulative effect on the deployed fleet:** 433,427 b → 282,960 b per fleet-fire
(**−34.7 %, −37,616 tokens**); 1,692,595 b → 1,078,548 b per fleet-day
(**−36.3 %, −153,511 tokens**). Net of the three quality rules D5, D12 and D6: **−30.1 % /
−31.4 %**. Adding D4 when the repo state is deployed: **−35.5 % / −37.2 %**.

**Sequencing.** Do D11 first (it is the reason several other fixes are not running), then D1 and
D5 (they are edits to the same shared text and must land together, or the fleet briefly has two
source-precedence rules), then D2/D3 (they add files, so they can be shipped and verified
independently of a prompt re-deploy — and D2 also fixes #90's live push bug, which is worth
doing early on its own), then D6–D10/D12 in one batch. Keep D11's SHA-256 verification for every
prompt update: a hand-pasted 20 KB prompt has silently drifted before.

---

## Corrections to the first submission

The first submission was rejected. Both named defects are real, and re-measuring the proposed
replacement texts exposed four more. Every one is corrected above.

| # | what the first submission said | what it is | where it is fixed |
|---|---|---|---|
| 1 | "D7: the block can be dropped from **12** prompts; only 6 need it" | **Wrong classification.** A narrow `scripts/`-only regex missed helpers referenced by bare filename. #05 and #20 (`eod-watchlist-snapshot`: `run_intl_cron.py`, `assemble_eod_csv.py`, `pull_international.py`, `holiday_calendar.py`), plus #12 and #26, **need** the block. The first submission also listed **#07**, which carries no HELPER SCRIPTS block at all in either the deployed or the repo copy. Correct split: **10 keep / 8 drop**. | D7, fully rewritten |
| 2 | "The `git push … \| head -3` exit-status trap is **already fixed** in the deployed and repo blocks … survives only in a comment" | **False, and the claim is retracted.** It is **live code** at `cron-prompts/90-delivery-auditor.md:482` — `git push -q origin HEAD:refs/heads/audit/status 2>&1 \| head -3`. #90 is the one routine that pushes to `refs/heads/audit/status` rather than `main`, so the first submission's script (hardcoded `HEAD:main`) would also have pushed to the wrong branch. | D2: the script now takes `--branch` and `--add`, and the `\| head -3` pattern is called out and replaced with `if git push …; then` |
| 3 | "D4 saves **27,220 bytes ≈ 6,805 tokens**" | **Over-stated ~8×.** The 1,581 b figure was **#17's** variant only; the repo's probe block is **681 b in 19 prompts** (repo total 14,519 b, not 31,620 b). Real saving: **3,499 b = 874 tokens**. | D4 |
| 4 | "D6 saves 194 b/run" | **A net cost, and larger than stated.** The replacement that removes the trap is 331 b against blocks of 115–205 b in 15 prompts (a cost of 126–206 b each). #12 (1,157 b) and #26 (1,934 b) carry real operational guidance that must **move into their skill files** — which is context-neutral, not a saving, because the skill is already read. Net context effect: **+1,889 b = +472 tokens** per fleet-fire, **+6,689 b = +1,673 tokens** per fleet-day. The first submission's "+520 token fleet-day saving" counted only the prompt side. | D6, now a labelled cost with the skill-side delta included |
| 5 | "D9 saves 173 b/run" | **A net cost of 115 b/run.** The merged rule must spell out the reporting duty the old block left implicit. | D9, now labelled a cost |
| 6 | D2 / D3 / D10 savings computed from **assumed** target sizes (380 b / 170 b / 330 b) | Every saving is now computed by **measuring the actual proposed replacement text** (1,000 b / 650 b / 395 b). D3 and D10 savings fell; D2 was recomputed as **one** stub replacing both blocks (not two stubs). | D2, D3, D10 |
| 7 | "**19 of 21** routines have no source-precedence rule" | **18 of 20.** 20 deployed prompts carry a `### Rules` block; the 21st Rules-titled section is `# Rules` in `01-weekly-mcp-health-check.md`, a probe checklist rather than a source contract. | D5, summary |
| 8 | — | The summary and proposal table now state **gross** (−34.7 %) and **net of D5/D12/D6** (−30.1 %) separately, so a cost-adding quality proposal is never disguised as a saving. | Summary, proposal table |
| 9 | — | **Every proposal's saving is now computed by measuring the actual proposed replacement text** against the actual current block, with the **skill side included** where content moves into a skill file. The first submission estimated target sizes (380 b / 170 b / 330 b / 194 b / 173 b); those estimates are what produced the over-claims above. | All proposals |

---

## NOTES ON METHOD, AND WHAT I COULD NOT VERIFY

**How the deployed bytes were measured.** The platform's `cron_read` tool is not exposed in this
session's tool catalog (`tool_search` returns zero hits for `cron`, `cron_read`, `cron_list` and
`scheduled task`; `mcp_invoke` rejects `cron_read` and `cron_list` as unknown tool names). The
freshest available copy is the tool-result artifact the platform persisted from a `cron_read`
call made in session `458676653531358`:
`/workspace/.mavis/tool-results/458676653531358/call_01a196fdb3f37774aef04a72/chunks/000000.txt`
(466,798 bytes, `manifest.json` → `tool_name: "cron_read"`, `command: "cron list"`,
`chunk_count: 1`, captured **2026-11-01T12:02:51Z**, ~17.5 h before this analysis). It is the
full, untruncated `response.tasks[]` array — all 23 tasks, each with a complete `prompt` string.
Each was written verbatim to `/workspace/audit/scratch/deployed/` and measured with
`len(prompt.encode())`. **If the platform has changed a prompt since 2026-11-01T12:02:51Z, the
byte counts here are of the 2026-11-01 copy.** Re-running `cron_read view=list` and re-parsing
the persisted chunk is a two-minute check; the analysis scripts are in `/workspace/audit/scratch/`.

**How each proposal's saving was measured (attempt-2 method).** For every proposal the *current*
block was located in the deployed text with a fence-aware regex and measured in bytes; the
*proposed* replacement text was written out in full, measured in bytes; the saving is the
difference, summed over the prompts that carry the block, and separately weighted by each
routine's fires/day for the fleet-day figure. The proposed texts are stored in
`/workspace/audit/scratch/corrected.py` so the arithmetic is reproducible. Nothing is estimated
from a target size.

**Token assumption.** 4 characters per token, as specified. Because the fleet's prompts are
**29.8 % fenced code** (measured: 128,964 code bytes of 433,427 total, across all 23 prompts)
and code tokenises denser than prose, I also computed a mixed estimate — 3.3 chars/token inside
fences, 4.0 outside — which gives **114,784 tokens**, ~6 % above the flat figure. The headline
numbers use the flat 4 chars/token as instructed.

**Repo state.** 485,815 bytes for the same 23 prompts (repo root `/workspace/mig/cloud-prompts`,
`cron-prompts/*.md` excluding README/ROSTER/roster.json, plus `01-weekly-mcp-health-check.md`).
The repo is 52,388 bytes **larger** than the deployed fleet and is ahead of it on 21 of 23
prompts. Measured byte-for-byte with `difflib` on the raw prompt strings.

**Artifacts checked.** `karizaco/minimax-cloud-outputs` was cloned read-only into
`/workspace/audit/scratch/outputs-main` (`git clone --depth 400 --branch main`, no branches
created, no push). **Branch note:** the repo's *default* branch is `master`, but every routine
pushes to `main`; a first clone that took the default branch landed on `master` and missed the
recent artifacts, so the analysis was redone against `main`. The sandbox CA path named in the
task brief (`/etc/ssl/certs/agent-identity/sandbox-gateway-ca.crt`) **does not exist in this
sandbox**, and `/workspace/.home/.gitconfig` points git at it, so the first clone attempt failed
with "Problem with the SSL CA cert". The clone succeeded with
`GIT_SSL_CAINFO=/etc/ssl/certs/ca-certificates.crt` and `GIT_CONFIG_GLOBAL=/dev/null`, using the
token already present in `/workspace/.git/config` (no `GITHUB_TOKEN` in the environment).

Findings from the `main` artifacts:

- **31 `SKIPPED_*` files exist and none is dated after 2026-10-24** — weekend skips exist for
  every weekend up to that date and then stop dead. That confirms the day-of-week moved into the
  scheduler and the prompts' weekend branch became near-dead work (it still covers **holidays**,
  which no cron expression can express).
- `international-eod/2026-10-22/STUB_skill_fetch_failed.md` — the skill-fetch stub path firing
  in the wild, exactly as CRITICAL REMINDER 1 specifies. Good: that rule is load-bearing.
- `international-eod/2026-10-23/STUB_no_market_data_source.md` — **the "no source" failure mode,
  documented by the agent itself.** It writes: *"Per the skill's hard rules and ZERO-FALLBACK
  POLICY, the run terminates here: no rows, no invented values, no substitute source"* and
  *"not fixable from inside the sandbox; requires registering the TradingView/Yahoo MCP servers
  for this agent"*. The deployed #05 prompt lists `mcp__tradingview_advanced__*`,
  `mcp__tradingview__*`, `mcp__yahoo_finance__*` under "MCP TOOLS AVAILABLE" and 500 bytes later
  says they "DO NOT EXIST"; the agent built its entire "no source" conclusion on their absence
  and never reached the `### PRIMARY SOURCE: the MCP-over-HTTP bridge (use this FIRST)` section.
  **This is the concrete cost of D6**, and the agent's own recommendation ("add an hour gate to
  the preamble") is a concrete input to D3.
- That stub also records *"This is the 16th consecutive non-producing fire (2026-09-28 →
  2026-10-23) … the cron has never written a single CSV row"*, and *"fire time 05:34 ET … ~11 h
  before the 16:35 ET target"* — a **misfire that the window check passed** because
  `MARKET_HOURS_ONLY=false`. #05 produced real rows again from 2026-10-26.
- The `## Source health` section that Rule 5 makes mandatory is present in **116 of 378** markdown
  artifacts (**31 %**), and in **90 of 256** (**35 %**) for the migration era (≥ 2026-10-22) —
  i.e. the rule is violated in roughly two thirds of artifacts.
- Race-loss evidence on `main`: `e651b82 restore: 10 SKIPPED audit records lost in cron #12's
  2026-10-26 push`, `0b418c3 restore: AGENTS.md workspace conventions (deleted by cron #12 push
  1356a03, then swept by cleanup f0a01e4)`, `48d6175 cron #19: backfill: 2026-10-27 and
  2026-10-28 artifacts (missed runs)`, `a25e0f7 cron 04 reversal-bullish-3:55 backfill:
  undelivered 2026-09-28..2026-10-26 artifacts`. Four separate recoveries from lost pushes.
- `4cf4239 cron 25: correct the oct-29 narrative — ADT is an OPENING gap lost to a stale
  pre-market tape, not a recovered pre-market gap` — a published artifact that had to be
  **corrected the next day** because it was built on a stale pre-market print. This is the
  concrete example for D5.
- `6bb9e04 cron 93 mcp-health weekly 2026-11-01: catalog 133/0 finance, 6/6 bridge packs answer,
  8/8 endpoints 200 - no change` — the weekly probe's own record of the current catalog
  (133 tools, 0 finance), which is the number D6 and D1 cite.

**Things I checked that did NOT support the hypothesis, reported so they are not re-litigated.**
(a) *Prompt↔skill duplication is small.* Shared 8-gram overlap between each prompt and the skill
it fetches totals ~20,544 bytes across the fleet (~5 %), and only three prompts exceed 4.8 %
(#07 and #10 at ~5 %, #19 at 7.2 %). The reply-format spec is **not** duplicated by
`skills/stock-screener-suite/references/agent-output-shape.md` — that file is the JSON contract
for `consume`, a different artefact. (b) *The zero-fallback policy does not cause aborted runs.*
The "accept the partial result, **write the artifact**, and STOP" clause is present in all 18
copies, and the "Partial data beats no data … the zero-fallback policy governs the *fallback
chain*, not whether the artifact gets written" clarification is present in 20 of 20. (c) *The
`git push … | head -3` trap is fixed in the 20 main-target routines* — but **not in #90**, which
is the single live instance (see Corrections). (d) *The WINDOW CHECK is not dead work in general*
— it is now redundant for weekends (the scheduler guarantees the day) but still load-bearing for
**market holidays**, which no cron expression can express, for the `MARKET_HOURS_ONLY` routines,
and for the missing hour gate.

**What I did not verify.** (i) The deployed bytes are from 2026-11-01T12:02:51Z, not live. (ii)
Whether `cron_read` is reachable from a routine's sandbox — `91-schedule-drift-guard.md` depends
on it (`cron_read view=list` → chunk file) and D12's date rule needs `cron_read view=runs`; I
could not exercise it from here. (iii) The actual token counts the platform bills for these
prompts; the figures here are estimates from byte counts under a stated assumption. (iv) Whether
any routine still writes a local Windows-style audit file (D8 assumes not). (v) The exact endpoint
set the trimmed D1 summary should retain — it should be chosen from the routines' real failure
history in the artifacts, not from this analysis. (vi) Whether #90's `audit/status` branch is
still the intended target for the auditor, or whether the auditor should now push to `main` like
the other 20 — that is a policy decision, and D2's `--branch` parameter makes either answer
cheap.

**Files written by this task.** `/workspace/audit/track-d-efficiency.md` (this document),
`/workspace/audit/track-d-efficiency.deliverable.md` and
`/workspace/.mavis/plans/plan_9bd4fa95/outputs/track-efficiency/deliverable.md` (same content
plus a delivery header), plus analysis scratch under `/workspace/audit/scratch/`. **Nothing under
`/workspace/mig` was created, modified or deleted; no remote was pushed.**
