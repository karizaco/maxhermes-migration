# Track C — Stale, dead and orphaned content across prompts, skills and shared docs

**Audit date:** 2026-11-02 (UTC) · **Repo:** `karizaco/maxhermes-migration` @ `24baf07` (read-only) ·
**Outputs repo:** `karizaco/minimax-cloud-outputs` @ `origin/main` `a109ce6` / `origin/master` `8bdb2d0` (cloned read-only, never pushed)

**All byte figures in this document are true UTF-8 bytes on disk** (`os.path.getsize` for files,
`len(text.encode('utf-8'))` for extracted blocks), not character counts. Line counts are
`len(text.splitlines())`. Where a table shows two size columns they are labelled.

---

## Summary

The fleet is **not** uniformly stale — it is stale in a specific, describable way: **the migration left two
generations of content side by side, and the newer generation is only partly wired in.** The day-of-week
constraint was successfully moved into the scheduler, but the old in-prompt window-check machinery was
never removed, so **all 20 window-check blocks (32,921 bytes, of which 17,546 are weekend-specific) are
unreachable code** — I resolved each prompt's deployed schedule from `roster.json`, enumerated every
day-of-week that schedule can fire, and **not one skip branch can trigger**. The same two-generations
pattern appears in the shared docs: the `RUNTIME-CONTRACT.md` §2b correction is present and correct, the
prompts carry the corrected Yahoo text, and yet **`cron-prompts/README.md` still tells the reader "Yahoo
JSON endpoints return persistent 429"** — the most-read doc in the repo still asserts the claim that was
explicitly retracted on 2026-10-31. In the outputs repo the fossil record is intact: **31 `SKIPPED_*.md`
markers** (the exact artifacts the dead branch would have written) sit on `main`, alongside **119 files in
11 groups that no live routine writes** — 111 of them dead or superseded, including `ntrt/_raw/` (30 `.json`
+ 4 `.log`) and `ntrt/_pipeline/` (9 `.py`), i.e. executable code published into an artifact repo. Seven of
the 20 skill directories are **orphans** with no live routine pointing at them — **113,325 bytes** across
the whole directories, **51,422 bytes** of which is the `SKILL.md` file itself — and six of the seven are
byte-identical to the Windows-era `skills-original/` capture; one of the orphans is a **dangling pointer
inside a live skill** (`stocks-in-play-pipeline`, named by `us-stocks-in-play/SKILL.md` with no URL, so
routine #17 is told to run a skill it cannot fetch). Five skills — owned by #16, #19, #22, **#23** and #26 —
require reading `research/watchlist.yaml`, which does not exist in Cloud. And the outputs repo's **default
branch `master` is 25 commits / 86 files behind `main` *and has diverged*** (it holds one commit `main`
lacks), while the README describes it as "a fast-forward mirror of `main` … the auditor advances it
daily". The good news, and it is real: the **three sources of truth (README index, ROSTER.md,
roster.json) are all present, all list 23 routines, and agree with each other on every schedule, project
id and artifact path** — the only divergence is the staleness of the snapshot, not inconsistency of the
data.

---

## Quantified table of dead / superseded content

| # | Item | Location | Size (bytes / lines) | Why it is dead | Disposition |
|---|---|---|---|---|---|
| 1 | Legacy window-check block (flag preamble + DOW tests + SKIPPED writer) | `cloud-prompts/cron-prompts/{02,04,05,06,08,09,10,12,13,14,15,16,17,19,20,22,23,25}-*.md` | **29,977 B / 18 prompts** (52 lines each, 28 for #15, 59 for #19) | Every branch is unreachable at its own deployed schedule (proved by simulation, C1) | **rewrite** (replace with a holiday-only guard) |
| 2 | New-style window-check block (hardcoded DOW + SKIPPED writer) | `07-stock-screener-focus-rvol-09:45.md` (29 lines), `26-agentic-pre-market-brief.md` (15 lines) | **2,944 B / 2 prompts** | Same — `07` fires 09:45 ET (inside its own 09–16 market-hours gate), `26` fires 08:30 ET Mon–Fri | **rewrite** |
| 3 | Weekend-specific subset of the above (DOW lines + `SKIPPED_*` writer + trailing prose) | 20 prompts | **17,546 B** (~4,387 tokens) | Day-of-week lives in the scheduler; `1-5` cannot produce a Saturday run | **delete** |
| 4 | "belt-and-braces guard … still handles US market holidays" prose | 13 prompts (02,04,05,07,08,09,10,12,17,20,23,25,26) | **4,927 B / 13 prompts** | A day-of-week test **cannot** detect a market holiday — the claim is false in all 13 copies | **rewrite** |
| 5 | `## WEEKEND MODE (RETIRED 2026-10-31)` tombstone | `26-agentic-pre-market-brief.md:59-66` | **435 B / 8 lines** | The procedure it refers to is already gone; the section warns against nothing anyone would do | **delete** (or move to history) |
| 6 | "Yahoo JSON endpoints return persistent 429" | `cloud-prompts/cron-prompts/README.md:54-55` | **192 B / 2 lines** | Retracted by `RUNTIME-CONTRACT.md:119-125` and by the prompts' own corrected text (20 prompts) | **rewrite** |
| 7 | "Open findings (2026-10-30)" table | `cron-prompts/README.md:119-133` | **3,657 B** | Presents as current: #22 "**Has never delivered.** No `weekly/` directory exists" — `weekly/2026-11-01-preview.md` now exists on `main` | **move to history** |
| 8 | `## MCP TOOLS AVAILABLE` block listing 4 non-existent tools | 17 prompts | **11,618 B / 17 prompts** | `mcp__yahoo_finance__*`, `mcp__tradingview_advanced__*`, `mcp__web_search__*`, `extract_content_from_websites` are all unregistered — and the next section says so | **delete** (keep provenance list, drop the tool list) |
| 9 | `## RUNTIME-CONTRACT` §2b — superseded 2026-10-28 measurement | `cloud-prompts/_shared/RUNTIME-CONTRACT.md:98-129` | **3,497 B / 32 lines** | Correctly labelled and corrected 6 lines below — **but** it is the *only* place the Nasdaq quote API, Yahoo HTML page, CoinGecko, Frankfurter, ECB FX, US Treasury and AlphaVantage are documented, and the **live ladder in all 20 prompts cites those endpoints** | **rewrite** (split: history → history file; endpoints → §2a) |
| 10 | 7 orphan skill directories | `cloud-prompts/skills/{agent-ops-sync,cron-watchdog,discord-channel-summarizer,mavis-runtime-export,mcp-api-health-check,stocks-in-play-pipeline,x-following-audit}` | **113,325 B total dir bytes** (51,422 B of which is `SKILL.md` only) — see C7 for the per-skill split | No live routine fetches them; 6 of 7 are byte-identical to the Windows-era `skills-original/` capture | **move to history** |
| 11 | `_classification.md` | `cloud-prompts/_classification.md` | **6,360 B** (file size) | Describes the pre-cloud mechanism (Finviz MCP, local Windows helpers, `secret create --name=GITHUB_TOKEN`) as if operative; 4 of its 26 original crons have no live routine | **move to history** |
| 12 | `SKIPPED_*.md` marker artifacts | `minimax-cloud-outputs` `origin/main` | **31 files** (20 in 7 top-level date dirs + 11 in `international-eod/*`) | The exact artifacts the dead weekend branch wrote | **move to history** (one dated `refs/` file) |
| 13 | Top-level date dirs | `minimax-cloud-outputs` `2026-09-27/ … 2026-10-24/` | **7 dirs / 20 files** (100% `SKIPPED_*`) | No routine writes a top-level date dir any more (all write to a named output dir) | **delete** |
| 14 | `catalog/` | `minimax-cloud-outputs` `catalog/catalysts/{2026-10-24,2026-10-26}.md` | **2 files** | No routine pushes to `catalog/` (verified: the `git add` list in all 22 prompts contains no `catalog`) | **delete** |
| 15 | `cron-prompts/*.HARDENED.md` | `minimax-cloud-outputs` `cron-prompts/` | **3 files** | Prompt copies pushed as artifacts; no routine writes there; they are stale snapshots of the prompt text | **delete** |
| 16 | `data2/` + `data_cross/` | `minimax-cloud-outputs` | **37 files** (3 + 34; incl. `compute.py`, `compute_qc.py`, `mats.json`, `raw_*.json`) | Scratch/intermediate from #12's earlier era; #12's contract is `cross-asset/{date}.md` and its push block stages only `cross-asset` | **delete** (or move to history) |
| 17 | `pattern-study/`, `research/` | `minimax-cloud-outputs` | **2 files** | #06 now writes `daily-screens/{date}/weekly-ipo.md`; `research/` is the Windows tree | **delete** |
| 18 | `scripts/` (4 of 5 unreferenced) | `minimax-cloud-outputs` `scripts/` | **4 files** (`build_weekly_artifacts.py`, `parse_focus_rvol.py`, `pull_weekly_data.py`, `shibui_mcp.py`) | Referenced by no live prompt (only `earnings_reaction_scanner.py` is, by #15) | **delete** |
| 19 | `refs/` — 5 legacy pre-cloud docs | `minimax-cloud-outputs` `refs/{crons,fallbacks,filters,tiering,sources-us-stocks-in-play}.md` | **8 files in `refs/` total** (5 legacy = 39,976 B; 3 current = `cron-ops.md`, `cron19-earnings-reminder-review.md`, `plan-sources-and-mcp-tracking.md`) | `crons.md` has Windows paths; `fallbacks.md` makes blocked Finviz tier-2; `filters.md` uses unregistered `mcp__shibui-finance__*`; `tiering.md` cites a non-existent `scripts/screen.py` | **delete** the 5 legacy (superseded by `_shared/RUNTIME-CONTRACT.md`); keep the 3 current |
| 20 | `ntrt/_pipeline/` + `ntrt/_raw/` | `minimax-cloud-outputs` | **43 files** — `_pipeline/` = 9 `.py`; `_raw/` = **30 `.json` + 4 `.log`** (34 files) | Executable code and raw dumps published into an artifact repo; the repo's own skill ships only `ntrt_probe.py` | **move to history** |
| 21 | `skills/README.md` "Maintenance" section | `cloud-prompts/skills/README.md:25-31` | **~420 B** | Says "Until cron #11 is migrated to Cloud, manual is the only path" — #11 was never migrated (it is one of the 4 dead originals) | **rewrite** |
| 22 | Default-branch mirror gap | `minimax-cloud-outputs` `origin/master` | **25 commits / 86 files behind `main`** (and 1 file `main` lacks) | README says `master` is "a fast-forward mirror of `main` … the auditor advances it daily" — it is neither, and it has **diverged** | **rewrite** (README claim) + **advance the mirror** |

**Reconciliation check on the table:** rows 1+2 = 29,977 + 2,944 = **32,921 B**, which is the total
window-check block size reported in C1. Row 12 = 20 + 11 = **31** `SKIPPED_*` files. Rows 13-18 + row 20
= 20 + 2 + 3 + 37 + 2 + 4 + 43 = **111 files** of dead or superseded artifacts, plus row 19's 8 `refs/`
files = **119 files** in trees no live routine writes (of the 8 `refs/` files, 5 are superseded pre-cloud
docs and 3 are current hand-maintained notes — so the count of genuinely dead artifacts is **111**, not
119).

---

### C1 — Every window-check block in the fleet is unreachable code

- **Severity:** medium
- **Scope:** 20 of 22 producer prompts (all except #90 auditor and #91 drift guard, which have no window check)
- **Evidence:** `cloud-prompts/cron-prompts/02-asia-pre-market-reactions.md:16-77` — the legacy 52-line block:

  ```bash
  # Window flags for THIS cron (set by migration):
  WEEKDAYS_ONLY=true
  WEEKEND_ONLY=false
  MARKET_HOURS_ONLY=false
  DAY_OF_WEEK=0   # 1=Mon ... 7=Sun; 0=no constraint
  ...
  if [ "$WEEKDAYS_ONLY" = "true" ] && [ "$DOW" -ge 6 ]; then
      SKIP_REASON="weekend (day=$DOW, expected Mon-Fri)"
  fi
  ```

  The proof that it is dead: I resolved each prompt's deployed schedule from `roster.json` and enumerated
  every day-of-week that schedule can actually fire, then checked whether any skip branch can be true on
  any of those days.

  ```
  id   schedule       firesOn  branches                             canfire@nominal   blkB  blkL
  02   30 6 * * 1-5   1-5      weekend(DOW>=6)                      NO                 1677    52
  04   55 15 * * 1-5  1-5      weekend(DOW>=6)                      NO                 1669    52
  05   30 16 * * 1-5  1-5      weekend(DOW>=6)                      NO                 1673    52
  06   0 15 * * 6     6        weekday(DOW<6)                       NO                 1699    52
  07   45 9 * * 1-5   1-5      weekend(DOW>=6)[hardcoded]           NO                 2262    29
  08   30 8 * * 1-5   1-5      weekend(DOW>=6)                      NO                 1691    52
  09   30 18 * * 1-5  1-5      weekend(DOW>=6)                      NO                 1691    52
  10   0 14 * * 1-5   1-5      weekend(DOW>=6),HOUR!9..16           NO                 1689    52
  12   0 10 * * 1-5   1-5      weekend(DOW>=6),HOUR!9..16           NO                 1691    52
  13   0 14 * * 3     3        DOW!=3                               NO                 1673    52
  14   0 15 * * 0     0        DOW!=7                               NO                 1679    52
  15   0 8 * * 1-5    1-5      weekend(DOW>=6)                      NO                 1066    28
  16   35 16 * * 1-5  1-5      HOUR!9..16                           NO                 1680    52
  17   50 15 * * 1-5  1-5      weekend(DOW>=6),HOUR!9..16           NO                 1661    52
  19   0 6 * * 1-5    1-5      weekend(DOW>=6)                      NO                 2029    59
  20   0 16 * * 1-5   1-5      weekend(DOW>=6)                      NO                 1680    52
  22   47 17 * * 0    0        DOW!=7                               NO                 1683    52
  23   30 22 * * 1-5  1-5      weekend(DOW>=6)                      NO                 1678    52
  25   0 9 * * 1-5    1-5      weekend(DOW>=6)                      NO                 1668    52
  26   30 8 * * 1-5   1-5      weekend(DOW>=6)[hardcoded]           NO                  682    15
  --------------------------------------------------------------------------------------------------
  TOTAL 20 prompts                                                                             32921
  ```

  The `MARKET_HOURS_ONLY` branches in #10/#12/#16/#17 are also dead at nominal time: #10 fires 14:00 ET
  (`9 ≤ 14 < 17` → passes), #12 fires 10:00 ET (passes), #16 fires 16:35 ET (`HOUR=16 < 17` → passes),
  #17 fires 15:50 ET (passes). #16 additionally has `WEEKDAYS_ONLY=false`, so its only remaining branch
  is the market-hours gate, which also passes.

- **Cost of leaving it:** **32,921 bytes of prompt text (≈8,230 tokens) loaded on every single fire of 20
  routines** — and the weekend-specific slice is **17,546 B (≈4,387 tokens)** of it. Worse than token cost:
  the block is a *false safety net*. An agent reading it believes it has a holiday guard and a skip
  mechanism; neither exists. The 31 `SKIPPED_*.md` files in the outputs repo are the fossil record of
  when the branch *did* fire, and the auditor's rules still have to reason about a marker format that can
  no longer be produced.
- **Recommended fix:** delete the `WEEKDAYS_ONLY` / `WEEKEND_ONLY` / `DAY_OF_WEEK` branches and the
  `SKIPPED_*` writer from all 20 prompts, and replace the whole 52-line block with a **market-holiday
  guard** — the one thing the scheduler genuinely cannot express. Concretely, in each prompt replace the
  window-check section with:

  ```bash
  # Market-holiday guard. The scheduler's day-of-week field already handles weekends.
  HOLIDAY=$(python3 - <<'EOF'
  import datetime; d=datetime.date.today()
  print("1" if (d.month==1 and d.day==1) or (d.month==7 and d.day==4) or (d.weekday()==4 and d.day==26) else "0")
  EOF
  )
  if [ "$HOLIDAY" = "1" ]; then
    echo "out-of-window: US market holiday"
    exit 0
  fi
  echo "window-check: OK"
  ```

  and update the trailing prose from *"The `SKIPPED_*.md` file IS the artifact for this run"* to
  *"Do not write an artifact on a market holiday; exit cleanly."* (also delete the `SKIPPED_*.md` mention
  from `CRITICAL REMINDERS` #4 in all 20 prompts, and from the auditor's marker vocabulary in #90).
- **Confidence:** high

---

### C2 — "Kept as a belt-and-braces guard … still handles US market holidays" is false in 13 prompts

- **Severity:** medium
- **Scope:** prompts 02, 04, 05, 07, 08, 09, 10, 12, 17, 20, 23, 25, 26
- **Evidence:** `cloud-prompts/cron-prompts/02-asia-pre-market-reactions.md:9-13`

  ```
  - The day-of-week field is set in the SCHEDULER, so this routine does not fire
    at all on weekends: no agent invocation is spent discovering it is a weekend,
    and no weekend SKIPPED file is written. The in-prompt weekend branch below is
    kept as a belt-and-braces guard (it costs one line) and is what still handles
    US market holidays, which no cron expression can express.
  ```

  Three false statements in five lines: (a) the branch is **not** "one line" — the block it lives in is
  52 lines and 1,677 bytes in #02 alone; (b) a **day-of-week** test cannot detect a **market holiday** —
  Christmas, Thanksgiving and July 4th are all weekdays and all pass the `$DOW -ge 6` test, so the branch
  that supposedly handles them does nothing; (c) it cannot handle them, because no cron expression *can*
  express a holiday, which is exactly why the branch exists — and it still doesn't.
- **Cost of leaving it:** **4,927 bytes** across 13 prompts that will be read on every fire of 13 routines,
  teaching the agent to believe it has holiday protection it does not have. The real risk is on the next
  US market holiday: the routine fires, sees `$DOW = 1`, passes the guard, and publishes an artifact
  built from a half-session tape with no marker saying so.
- **Recommended fix:** delete the sentence "The in-prompt weekend branch below is kept as a belt-and-braces
  guard (it costs one line) and is what still handles US market holidays, which no cron expression can
  express." Replace with the C1 holiday guard. Do not reword it — the current wording asserts a capability
  the code does not have.
- **Confidence:** high

---

### C3 — The #26 `## WEEKEND MODE (RETIRED 2026-10-31)` tombstone: correctly marked, but it is a 435-byte warning against nothing

- **Severity:** low
- **Scope:** prompt #26 only (`cloud-prompts/cron-prompts/26-agentic-pre-market-brief.md:59-66`)
- **Evidence:** `cloud-prompts/cron-prompts/26-agentic-pre-market-brief.md:59-66` — the section in full (435 bytes, 8 lines):

  ```
  ## WEEKEND MODE (RETIRED 2026-10-31)

  This routine no longer fires on weekends. The deployed schedule `30 8 * * 1-5` restricts it to
  Mon-Fri, so the scheduler never starts a Saturday or Sunday run — there is no weekend brief
  to produce and no weekend mode to enter. The weekend procedure that used to live here is
  RETIRED: do not write a weekend brief, do not label a column "Fri close", and do not treat a
  weekend run as expected.
  ```

  **Is it still needed?** No. The weekend *procedure* it refers to is already gone — the section is a
  tombstone describing its own absence. **Is the retirement clearly marked?** Yes — the heading carries
  `(RETIRED 2026-10-31)`, the first sentence restates the retirement, and the second forbids three
  concrete wrong actions. That marking is good practice; the problem is that it is **the only prompt in
  the fleet with such a marker** (19 other weekday prompts carry the same retired weekend behaviour with
  no marker at all), and the tombstone's content is 100% restatement of the `## SCHEDULE` block four
  lines above it.
- **Cost of leaving it:** 435 bytes per fire of #26, and it creates a false asymmetry — a reader
  auditing "which prompts still have weekend logic?" finds it in 20 prompts and sees a clear marker on
  exactly one of them, which invites the conclusion that the other 19 are live.
- **Recommended fix:** delete lines 59-66 of `26-agentic-pre-market-brief.md`. If a marker is wanted, keep
  the whole fleet symmetric: delete the weekend branch from all 20 prompts (C1) and leave no tombstones.
  A retirement marker is only useful while the retired thing is still there.
- **Confidence:** high

---

### C4 — 31 `SKIPPED_*.md` marker artifacts survive in the outputs repo

- **Severity:** medium
- **Scope:** `karizaco/minimax-cloud-outputs` `origin/main` (and `origin/master`)
- **Evidence:**

  ```
  $ git ls-tree -r --name-only origin/main | grep -ci skipped
  31
  ```

  20 of them sit at the top level of the repo, in **7 dated directories whose entire contents are
  `SKIPPED_*` markers**:

  ```
  2026-09-27/SKIPPED_asia_pre_market_reactions.md
  2026-10-03/SKIPPED_asia_pre_market_reactions.md
  2026-10-03/SKIPPED_eod_international_daily.md
  2026-10-03/SKIPPED_stock_screener_focus_rvol_09:45.md
  ... (20 files across 2026-09-27, 10-03, 10-04, 10-10, 10-11, 10-18, 10-24)
  ```

  and 11 more under `international-eod/{2026-09-28 … 2026-10-21}/SKIPPED_pre_market_fire.md` — a marker
  filename that **no prompt in the repo produces** (it is not in any of the 20 `SKIPPED_*` write targets),
  so those 11 came from an even older generation of the code.

  These were preserved deliberately: commit `96c696c` (2026-10-30) — *"outputs: preserve the 9 weekend-skip
  artifacts that only lived on the master branch"* — so the "skip" behaviour was treated as live output
  worth preserving one day after the scheduler took over the day-of-week.
- **Cost of leaving it:** the auditor (#90) and `tools/gen_roster.py` both key off artifact filenames, and
  a `SKIPPED_*.md` marker at the top level of the repo is indistinguishable from a delivered artifact to
  any path-substring check. Any routine that globs the outputs repo, or any human checking "did this
  routine deliver?", sees a marker with a routine name in it and has to know the branch is dead to
  interpret it. It is also the only thing making the seven top-level date dirs look legitimate.
- **Recommended fix:** (a) delete the 7 top-level date directories from `main` — 20 files, all markers, no
  routine writes that path any more; (b) move the 11 `international-eod/*/SKIPPED_pre_market_fire.md`
  markers and the remaining markers into a single dated `refs/skipped-markers-archive.md` with a
  one-line provenance note; (c) after the C1 fix, remove `SKIPPED_*` from the auditor's marker vocabulary
  in `90-delivery-auditor.md` and from `tools/gen_roster.py`.
- **Confidence:** high

---

### C5 — The README's "Common contract" still says Yahoo returns a persistent 429

- **Severity:** high
- **Scope:** `cloud-prompts/cron-prompts/README.md:54-55` — the section every routine and every new agent
  is pointed at
- **Evidence:** `cloud-prompts/cron-prompts/README.md:54-55` — the live text (192 bytes):

  ```
  - **Data sources**: the `mcp__*` tool names are NOT registered in this runtime. The MCP *servers* are
    reachable over plain HTTPS JSON-RPC via `_shared/mcp_bridge.py`. Yahoo JSON endpoints return
    persistent 429; `web_search` (separate egress) and the Nasdaq API work. Full endpoint list and
    measured status: `_shared/RUNTIME-CONTRACT.md`.
  ```

  **Contradicted by three places in the same repo:**
  1. `cloud-prompts/_shared/RUNTIME-CONTRACT.md:119-125` — *"**CORRECTION (2026-10-31):** the 2026-10-28
     note below claimed Yahoo JSON returns a *persistent* 429 from this egress. **That is no longer true.**
     Yahoo's chart, screener, quoteSummary and options endpoints all returned 200 on 2026-10-31 … **Do
     not hard-code a Yahoo-avoidance path.**"*
  2. **All 20 prompts** already carry the corrected text — `02-asia-pre-market-reactions.md:106-111`:
     *"**Measured 2026-10-31 from this sandbox — Yahoo's JSON endpoints are working again** … The earlier
     'persistent 429' was an egress-side condition that has cleared. **Do not hard-code a
     Yahoo-avoidance path.**"* (10,912 bytes of 429-mentioning lines fleet-wide, all in the corrected
     framing).
  3. The README's own "Known hazards" section already treats Yahoo as working.

  **Does any prompt or doc still tell the reader Yahoo returns a persistent 429?** Yes — this one, and it
  is the index document the fleet is generated from. Everything else was updated; this file was not.
- **Cost of leaving it:** the README is the entry point for the whole fleet and is explicitly the file
  `tools/gen_index.py` rewrites. An agent that reads the README (rather than the prompt it is executing)
  will build a Yahoo-avoiding source ladder, skip the cheapest and most reliable source for most symbols,
  and burn the `market-recap` bridge / Nasdaq / `web_search` fallbacks on every run — the exact behaviour
  `RUNTIME-CONTRACT.md:119` says to stop. It is also a 192-byte correction that anyone can verify in
  10 seconds, so leaving it is pure reputational cost for the repo.
- **Recommended fix:** replace the two lines with:

  ```
    reachable over plain HTTPS JSON-RPC via `_shared/mcp_bridge.py`. Yahoo JSON endpoints were
    returning a persistent 429 on 2026-10-28 and were working again on 2026-10-31 — that was an
    egress-side condition, not a property of the endpoints. Do not hard-code a Yahoo-avoidance path;
    try the ladder in cost order and fall through on a real failure. `web_search` (separate egress)
    and the Nasdaq API work. Full endpoint list and measured status: `_shared/RUNTIME-CONTRACT.md`.
  ```
- **Confidence:** high

---

### C6 — RUNTIME-CONTRACT §2b: the "superseded" section is partly load-bearing, so it cannot simply be deleted

- **Severity:** medium
- **Scope:** `cloud-prompts/_shared/RUNTIME-CONTRACT.md:98-129` (3,497 B / 32 lines) and the source ladder
  in all 20 prompts
- **Evidence:** §2b is headed `### 2b. Original measurement 2026-10-28 (superseded for Yahoo)` and carries
  a `**CORRECTION (2026-10-31):**` paragraph six lines after its table. **Is keeping it useful history or
  a trap?** As *history*, it is fine and correctly marked. The trap is structural and in the other
  direction: **§2a (the current table, lines 60-97) does not contain seven of the endpoints the live
  prompts' ladder relies on.**

  Current §2a contains: `market-recap` bridge (3 tools), `stocktwits`, `shibui`, TradingView scanner,
  Yahoo chart, Yahoo chart 5m, Yahoo screener, Yahoo quoteSummary, Yahoo options, Nasdaq market movers,
  SEC EDGAR ×3, GitHub connector.

  The ladder in all 20 prompts (`02-asia-pre-market-reactions.md:112-115`) is:

  ```
  Ladder for bulk data: bridge `market-recap` → Yahoo JSON → (on 429) Nasdaq API
  `https://api.nasdaq.com/api/quote/{SYM}/info?assetclass=etf` → Yahoo HTML
  `https://finance.yahoo.com/quote/{SYM}/` → `web_search` per symbol.
  ```

  `api.nasdaq.com/api/quote/{SYM}/info` and `finance.yahoo.com/quote/{SYM}/` appear **only in §2b** —
  the section labelled *superseded*. Same for CoinGecko, Frankfurter, ECB FX, US Treasury and
  AlphaVantage (all listed as live in §2b, and the prompts name CoinGecko / Frankfurter / US Treasury as
  "confirmed working"). The Stooq entry in §2b (`404 / 000`) is the only *negative* measurement, and the
  prompts repeat it ("Stooq CSV is blocked (404)") — again citing a superseded section.
- **Cost of leaving it:** an agent that reads only §2a (the section marked "current") cannot verify the
  ladder's tiers 3-4, and an agent that reads §2b sees a table headed *superseded* and has to decide
  whether to trust its rows. Both readings cost a round-trip at best and a wrong source choice at worst.
  Today the harm is bounded because §2b also contains the correction and the other live endpoints; but the
  arrangement is exactly the kind of thing that rots further.
- **Recommended fix:** split the file rather than pick a side. (a) Move §2b wholesale to
  `cloud-prompts/_shared/RUNTIME-CONTRACT-HISTORY.md` with a one-line header
  *"Historical measurement, 2026-10-28. Superseded for Yahoo on 2026-10-31 — see the CORRECTION below.
  Retained for the endpoints that were never re-measured."*; (b) promote the **seven still-cited but
  un-re-measured endpoints** (Nasdaq quote API, Yahoo HTML page, CoinGecko, Frankfurter, ECB FX, US
  Treasury, AlphaVantage) into a new §2a row group titled *"Secondary sources — not re-measured since
  2026-10-28"*, and add Stooq as an explicit negative; (c) re-measure those seven in one `curl` sweep and
  date them, then the §2a/§2b split becomes moot.
- **Confidence:** high

---

### C7 — Seven orphan skill directories (113,325 B of dir bytes / 51,422 B of `SKILL.md`), six of them byte-identical to the Windows capture

- **Severity:** medium
- **Scope:** `cloud-prompts/skills/` — 20 directories (21 entries including `README.md`); 13 referenced by
  a live prompt, **7 not**
- **Evidence:** `cloud-prompts/skills/` — the full map (live routine → skill → status), with both size columns stated explicitly:

  | Skill dir | Fetched by | `SKILL.md` bytes | Full dir bytes | Files in dir | vs `skills-original/` |
  |---|---|---|---|---|---|
  | `eod-watchlist-snapshot` | #05, #20 | 10,900 | 189,290 | 18 | edited |
  | `stock-screener-suite` | #04, #06, #07, #08, #09, #10 | 20,953 | 135,839 | 10 | edited |
  | `cross-asset-correlation-snapshot` | #12 | 8,667 | 24,613 | 2 | edited |
  | `earnings-reaction-scanner` | #15 | 25,007 | 25,007 | 1 | edited |
  | `us-stocks-in-play` | #17 | 16,565 | 16,565 | 1 | edited |
  | `asia-pre-market-reactions` | #02 | 19,916 | 19,916 | 1 | edited |
  | `agentic-pre-market-brief` | #26 | 10,078 | 10,078 | 1 | edited |
  | `ntrt-gap-brief` | #25 | 7,970 | 11,166 | 2 | edited |
  | `earnings-reminder` | #19 | 6,939 | 6,939 | 1 | edited |
  | `unusual-options-flow-daily` | #16 | 5,955 | 5,955 | 1 | edited |
  | `macro-calendar-week` | #13, #14 | 5,292 | 5,292 | 1 | edited |
  | `agentic-weekly-brief` | #22 | 4,838 | 4,838 | 1 | edited |
  | `agentic-post-market-brief` | #23 | 4,512 | 4,512 | 1 | edited |
  | **`agent-ops-sync`** | — | **3,502** | **3,502** | 1 | **IDENTICAL** |
  | **`cron-watchdog`** | — | **14,724** | **33,801** | 4 | **IDENTICAL** |
  | **`discord-channel-summarizer`** | — | **7,845** | **7,845** | 1 | **IDENTICAL** |
  | **`mavis-runtime-export`** | — | **5,274** | **48,100** | 6 | **IDENTICAL** |
  | **`mcp-api-health-check`** | — | **2,903** | **2,903** | 1 | **IDENTICAL** |
  | **`stocks-in-play-pipeline`** | — | **13,152** | **13,152** | 1 | edited |
  | **`x-following-audit`** | — | **4,022** | **4,022** | 1 | **IDENTICAL** |
  | **SUBTOTAL — 13 live dirs** | — | 147,592 | 460,010 | 41 | 0 IDENTICAL |
  | **TOTAL — 7 orphans** | — | **51,422** | **113,325** | 15 | 6 of 7 IDENTICAL |
  | **TOTAL — all 20 dirs** | — | 199,014 | **573,335** | 56 | — |

  *Column definitions: `SKILL.md` bytes = size of that one file (`os.path.getsize`); **Full dir bytes** =
  every file under the skill directory (`SKILL.md` + `scripts/` + `references/` + `inventory.json`). The
  orphan headline of **113,325 B** is the full-dir figure; **51,422 B** is the `SKILL.md`-only figure.
  They are two different measurements of the same 7 directories and must not be added together.
  Reconciliation: 51,422 + 147,592 = 199,014 (`SKILL.md` column) and 113,325 + 460,010 = 573,335
  (full-dir column); 15 + 41 = 56 files.*

  **The `stocks-in-play-pipeline` orphan is a live problem, not just a loose end.** The *live* skill
  `us-stocks-in-play/SKILL.md:13,19` points at it by name with no URL:

  ```
  Uses the shared `stocks-in-play-pipeline` skill for normalize→merge, Soft-A, TECH_WATCH, holiday skip…
  Always run `stocks-in-play-pipeline` **after** gathering sources and **before** writing the dated digest.
  ```

  There is **no fetchable URL** for it anywhere in the repo (`grep -rn "stocks-in-play-pipeline/SKILL.md"`
  returns nothing), so routine #17 — which *is* live and *does* fetch `us-stocks-in-play/SKILL.md` — is
  instructed to run a skill it cannot obtain. The Soft-A tiering and holiday-skip rules #17's own prompt
  depends on live only in that unreachable file.

  **Routines whose skill is missing:** none by name — all 20 producer prompts point at a `SKILL.md` that
  exists on disk. The gap is the one dangling pointer above.
- **Cost of leaving it:** **113,325 bytes** of Windows-era content in the directory the fleet treats as its
  skill source — that is **19.8% of the 573,335 B skill corpus** (and **25.8%** of the `SKILL.md`-only
  199,014 B). For calibration: the orphans are *smaller* than the two largest **live** dirs
  (`eod-watchlist-snapshot` 189,290 B and `stock-screener-suite` 135,839 B), so the orphan bytes are
  real but are not where the bulk of the corpus sits. The concrete cost is `stocks-in-play-pipeline`
  (13,152 B): #17 runs with an unreachable dependency, so the Soft-A tier thresholds and holiday skip
  that #17's output depends on are whatever the agent improvises that day — a **silent, per-run variance
  in the published artifact**. The other six orphans are maintenance debt only.
- **Recommended fix:** (a) add the fetch URL to `us-stocks-in-play/SKILL.md` line 13 and 19 —
  `https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/skills/stocks-in-play-pipeline/SKILL.md`
  — and add the same fetch instruction to `17-us-stocks-in-play.md`; (b) move the other six orphan
  directories to `skills-original/` (where their Windows-era content already lives and belongs) rather
  than deleting them — `mcp-api-health-check` and `cron-watchdog` are the specs for original crons #18
  and #3, which have a migration history worth keeping.
- **Confidence:** high

---

### C8 — The skill specs still describe the pre-cloud Windows workflow

- **Severity:** medium
- **Scope:** 20 skill directories in `cloud-prompts/skills/`
- **Evidence:** the skills were partially ported — 14 of 20 differ from `skills-original/`, 6 are
  byte-identical — but the port was not finished. Across the 20 `SKILL.md` files there are **82 occurrences
  of Windows/local-path references** (regex `[A-Za-z]:[\\/]|mavisHome|research/[\w./-]+`) and **71
  occurrences of `mcp__*` tool names** that are not registered. Per-skill:

  ```
  skill                            winPathOcc  mcp__Occ  watchlist.yaml
  agent-ops-sync                           4         0               0
  agentic-post-market-brief                3         0               1
  agentic-pre-market-brief                 2        14               1
  agentic-weekly-brief                     4         0               1
  asia-pre-market-reactions                7         9               0
  cron-watchdog                            9         0               0
  cross-asset-correlation-snapshot         5         4               0
  discord-channel-summarizer               7         9               0
  earnings-reaction-scanner                1        18               0
  earnings-reminder                        3         0               1
  eod-watchlist-snapshot                    4         1               2
  macro-calendar-week                       1         3               0
  mavis-runtime-export                      6         0               0
  mcp-api-health-check                      2         0               0
  ntrt-gap-brief                            6         1               0
  stock-screener-suite                      3         8               0
  stocks-in-play-pipeline                   1         0               0
  unusual-options-flow-daily                3         3               3
  us-stocks-in-play                         5         1               0
  x-following-audit                         6         0               0
  TOTAL                                    82        71
  ```

  Examples:

  ```
  cloud-prompts/skills/agent-ops-sync/SKILL.md:22:   python "C:\Users\admin\.minimax\projects\coding-shared\scripts\agent_ops_sync.py"
  cloud-prompts/skills/agentic-post-market-brief/SKILL.md:40:- `C:\Users\admin\.minimax\projects\coding-shared\research\briefs\YYYY-MM-DD-post_market.md`
  cloud-prompts/skills/agentic-post-market-brief/SKILL.md:45:1. **Read the watchlist.** Same as pre-market: `C:\Users\admin\.minimax\projects\coding-shared\research\watchlist.yaml`.
  cloud-prompts/skills/agentic-pre-market-brief/SKILL.md:94:Read `C:\Users\admin\.minimax\projects\coding-shared\research\watchlist.yaml`.
  cloud-prompts/skills/asia-pre-market-reactions/SKILL.md:50:python "C:/Users/admin/.minimax/projects/coding-shared/scripts/asia_brief_writer.py" \
  cloud-prompts/skills/cron-watchdog/SKILL.md:96:python "C:/Users/admin/.minimax/agents/mavis/skills/cron-watchdog/scripts/check_stuck.py" --empty
  cloud-prompts/skills/discord-channel-summarizer/SKILL.md:26:2. **fmarcac/discord-mcp** launched via `C:\Users\admin\.minimax\bin\discord-launch.ps1`
  ```

  **Five skills require reading `research/watchlist.yaml`, which does not exist in Cloud** — and they are
  owned by five different routines:

  | Skill | Reads `research/watchlist.yaml` | Owner routine |
  |---|---|---|
  | `agentic-post-market-brief` | `:45` — *"**Read the watchlist.** Same as pre-market"* | **#23** |
  | `agentic-pre-market-brief` | `:94` — *"Read `C:\Users\admin\...\research\watchlist.yaml`"* | #26 |
  | `agentic-weekly-brief` | `:50` — *"For each ticker in `research/watchlist.yaml`, pull …"* | #22 |
  | `earnings-reminder` | `:47` — *"**Watchlist earnings**: cross-reference `research/watchlist.yaml`"* | #19 |
  | `unusual-options-flow-daily` | `:45, :62` — *"Parse `research/watchlist.yaml` → `tickers: [...]`"* | #16 |

  (A sixth skill, `eod-watchlist-snapshot` — owned by #05 and #20 — names the file only to **forbid** it:
  `:13` *"The 12-name `research/watchlist.yaml` is reserved for personal trade tracking"* and `:168`
  *"**Never use `research/watchlist.yaml` as the universe**"*. That one needs no behavioural patch, but
  its text still points at a Windows path.) The repo's own
  `docs/IMPROVEMENTS-cron19-earnings-reminder.md:52` already records the collision:
  *"Skill step 1 requires `research/watchlist.yaml`. It does not exist in the Cloud sandbox, does not…"*

  The prompts mitigate the OUTPUT path, but the **procedure body** — which the prompt orders the agent to
  *"follow the procedure verbatim"* — still says to read a file that isn't there.
- **Cost of leaving it:** every one of the 20 producer routines fetches its `SKILL.md` on every fire
  (≈180 KB of skill text per fleet-day across the 20 fetches) and receives instructions to execute
  Windows paths and unregistered MCP tools. The overrides live in the prompt, so the failure mode is not a
  crash but a **partial application of the override**: an agent that reads `earnings-reminder/SKILL.md`
  and hits "read `research/watchlist.yaml`" has to decide whether the prompt's OUTPUT override also
  overrides the *input*. Five skills currently leave that ambiguity live, one of them (#23) being the
  **post-market brief**, whose entire step 1 is "Read the watchlist".
- **Recommended fix:** for each of the **five** watchlist-reading skills, add one line to the
  `Cloud adaptations` block of its owning prompt — #16, #19, #22, **#23** and #26:

  ```
  The skill's `research/watchlist.yaml` does not exist in Cloud. Substitute the deployed universe for the
  skill's "watchlist" inputs, and state the substitution in `## Source health`.
  ```

  For #23 specifically the substitution also has to cover step 1 of the skill body (the post-market
  brief's step 1 *is* the watchlist read), so for #23 add:
  *"Step 1 of the skill is replaced in full: there is no watchlist file. Use the deployed universe."*
  For #05/#20 (`eod-watchlist-snapshot`) no behavioural patch is needed — the skill already forbids using
  the file as the universe — but the Windows path string in `:13` should be changed to a neutral
  `research/watchlist.yaml` so the reference no longer implies a local filesystem. For the six
  byte-identical orphan skills, C7's move-to-`skills-original/` resolves them. Do not try to port the
  Windows body of the 14 partially-edited skills in one pass — rewrite each on the `stocks-in-play-pipeline`
  pattern (procedure + explicit Cloud adaptations + explicit output path).
- **Confidence:** high

---

### C9 — Dead file references: every reference that resolves to nothing

- **Severity:** medium
- **Scope:** prompts, skills and the shared docs
- **Evidence:** I extracted every path-like reference from the 22 prompts, the 20 `SKILL.md` files, the
  shared docs and the top-level `cloud-prompts/*.md`, and tested each against the repo tree.
  **76 distinct references: 31 resolve, 45 do not.** Of the 45, **34 are Windows/local-path-shaped**
  (inside a Windows-era skill — C8) and **11 are other dead references**, listed here:

  | Reference | Referenced from | Resolves to | Note |
  |---|---|---|---|
  | `scripts/screen.py` | `skills/stock-screener-suite/SKILL.md`, and `outputs-repo refs/tiering.md` | **nothing** | `refs/tiering.md` names `FOCUS_THRESHOLD_STYLISTS` / `TIER_A_THRESHOLD_STYLISTS` as living in it — the tier thresholds #09's output depends on are only documented against a file that does not exist |
  | `research/watchlist.yaml` | 5 live skills (C8) | **nothing** | see C8 |
  | `cloud-prompts/_shared/preopen_feed.py` | `cloud-prompts/preopen-feed-plan.md` | **nothing** | the plan's own helper is not in the repo |
  | `cloud-prompts/n8n/README.md` | `cloud-prompts/preopen-feed-plan.md` | **nothing** | the `n8n/` directory does not exist at all |
  | `cloud-prompts/n8n/workflow-preopen-feed.json` | `cloud-prompts/preopen-feed-plan.md` | **nothing** | ditto — the plan references a workflow file it does not ship |
  | `tools/list` | `cloud-prompts/01-weekly-mcp-health-check.md` | **nothing** | likely meant `tools/` as a directory listing |
  | `skills/<name>/scripts/` for 7 skills | 8 prompts — `02`, `13`, `14`, `16`, `17`, `19`, `22`, `23` | **nothing** | the prompts instruct "If the skill spec references a helper under `scripts/`, fetch the helper's URL too: `.../skills/<name>/scripts/<name>.py`" for skill dirs that have no `scripts/` directory at all |
  | `mcp__yahoo_finance__*`, `mcp__tradingview_advanced__*`, `mcp__web_search__*`, `extract_content_from_websites` | `## MCP TOOLS AVAILABLE` in 17 prompts | **nothing** | see C10 |

  **Verified-good references** (no action): all 13 `skills/<name>/SKILL.md` URLs resolve to files on disk;
  `_shared/mcp_bridge.py`, `_shared/probe_mcp.py`, `_shared/barchart_fetch.py` all exist; `tools/gen_index.py`,
  `tools/gen_roster.py`, `tools/schedule-drift.py`, `tools/schedule-ground-truth.json` all exist.
  Two references that look local but resolve elsewhere and are therefore **not** defects:
  `scripts/earnings_reaction_scanner.py` (fetched from the **outputs** repo by #15 — exists there) and
  `scripts/correlation_matrix.py` (#12 sets `$SKILL` to `.../cross-asset-correlation-snapshot/scripts` —
  correct).
- **Cost of leaving it:** the `refs/tiering.md` case is the expensive one — the Tier-A thresholds are
  load-bearing for #09's published artifact and they are documented only against a missing file, so a
  reader either reimplements them from the prose (which gives 2/3 stylists, not the code) or improvises.
  The `scripts/<name>/scripts/` template lines are harmless but teach the agent to expect a `scripts/`
  directory that is not there for 7 of the 13 skills.
- **Recommended fix:** (a) rewrite `refs/tiering.md` to state the thresholds inline (the prose already
  gives them: Master 200 / Stalk 50 / Focus 12 / Tier-A 8, 2 and 3 stylists) and delete the
  `scripts/screen.py:_STYLIST_FROM_ORIGIN` reference; (b) delete the two `n8n/` references and the
  `preopen_feed.py` reference from `preopen-feed-plan.md` (the plan is a *proposal* awaiting approval —
  either ship the files or mark the references "to be created"); (c) change `tools/list` to `tools/`;
  (d) change the `scripts/<name>.py` fetch instruction to be conditional on the skill actually having one,
  which the agent can tell from the fetched SKILL.md.
- **Confidence:** high

---

### C10 — `## MCP TOOLS AVAILABLE` lists four tools that do not exist, in 17 prompts

- **Severity:** medium
- **Scope:** 17 prompts (all producers except #07, #15, #26, which use a different shape)
- **Evidence:** `cloud-prompts/cron-prompts/02-asia-pre-market-reactions.md:86-89` — the whole block:

  ```
  ## MCP TOOLS AVAILABLE
  - `mcp__yahoo_finance__*`, `mcp__tradingview_advanced__*`
  - `web_search`, `extract_content_from_websites` for catalyst/news research.
  ```

  **11,618 bytes** fleet-wide. The very next section, `## RUNTIME DATA-SOURCE CONTRACT`, opens:
  *"**The `mcp__*` tools named above DO NOT EXIST in this runtime.** They are listed for provenance
  only."* — so the prompt contradicts itself within 400 bytes. The four names are all dead:
  `mcp__yahoo_finance__*`, `mcp__tradingview_advanced__*` and `mcp__web_search__*` are unregistered
  (`RUNTIME-CONTRACT.md:14-17`), and `extract_content_from_websites` is likewise unregistered
  (`RUNTIME-CONTRACT.md:21`) — it appears in **39 places** across the repo. The genuinely working
  `web_search` and `web_fetch` are already listed in the `RUNTIME DATA-SOURCE CONTRACT` section, so the
  block adds nothing but a trap.
- **Cost of leaving it:** 11,618 bytes of prompt text naming tools that, if called, return
  tool-not-found and — per the zero-fallback policy in the same prompt — convert into an **early abort
  with no artifact written**. The RUNTIME-CONTRACT explains this exact failure mode: *"Calling one returns
  a tool-not-found error, which the zero-fallback policy then converts into an early abort with **no
  artifact written**. The prompt's own CRITICAL REMINDER originally said 'use the EXACT MCP tool names
  listed above', which pushed the agent straight into that trap; that line has been rewritten."* — the
  CRITICAL REMINDER was fixed; **the list it refers to was not.**
- **Recommended fix:** replace the block in all 17 prompts with:

  ```
  ## TOOLS AVAILABLE IN THIS RUNTIME
  - `web_search`, `web_fetch`, `bash`, `mcp_invoke` + `tool_search`.
  - `connector__github__*` (118 tools) for repo writes.
  - The `mcp__yahoo_finance__*` / `mcp__tradingview_advanced__*` names this skill was written against
    are **not registered here** — they are kept only as provenance. See the RUNTIME DATA-SOURCE CONTRACT
    below for the live endpoints, and `cloud-prompts/_shared/RUNTIME-CONTRACT.md` for the full list.
  ```

  That keeps the provenance trail (which the contract explicitly values) while removing the four callable
  names that look like instructions.
- **Confidence:** high

---

### C11 — `_classification.md`: 4 of its 26 original crons are dead, and the file describes a mechanism that no longer exists

- **Severity:** medium
- **Scope:** `cloud-prompts/_classification.md` (6,360 B)
- **Evidence:** `cloud-prompts/_classification.md` — which original cron numbers have no live cloud routine:

  ```
  originals listed in _classification.md: [1..26]  (26)
  live cloud routine numbers: [1,2,4,5,6,7,8,9,10,12,13,14,15,16,17,19,20,22,23,25,26,90,91]  (23)

  originals with no live cloud routine of the same number:
     #3   (Watchdog Stock-screener, hourly)
     #11  (Daily mavis-runtime backup)
     #18  (Weekly MCP and API health check)  -> RENUMBERED: this is live as cloud routine #01
     #21  (Daily agent-ops sync)
     #24  (Weekly X following audit)
  ```

  **#18 is not dead** — it became cloud routine **#01** (`01-weekly-mcp-health-check.md`, Sun 02:00 ET),
  exactly as `_classification.md`'s own "Step 1 — Pilot (cron #18, Sun 02:00 ET)" predicted. So the
  genuinely dead originals are **4: #3, #11, #21, #24** — and each maps to one of the orphan skills:
  #3→`cron-watchdog`, #11→`mavis-runtime-export`, #21→`agent-ops-sync`, #24→`x-following-audit`.

  **Is the file operative guidance or a historical artifact that now misleads?** It is a historical
  artifact that still reads as operative, and it misleads in four specific ways:
  1. *"Finviz MCP + python helper. Note: Finviz needs Playwright"* (#6) — there is no Finviz MCP, Finviz
     is **403-blocked egress-IP-wide** (`RUNTIME-CONTRACT.md` §2f), and Playwright works *against*
     Finviz, not for it.
  2. *"**For Cloud: rewrite prompt to … No git push required.** If `${GITHUB_TOKEN}` is set via the secret
     tool, push … as bonus; if not, chat-only is fine."* — **every** deployed routine pushes, and the
     push is **mandatory** with a delivery-verification step, not a bonus.
  3. *"install `GITHUB_TOKEN` via the secret tool (`secret create --name=GITHUB_TOKEN --value=<PAT>`)"* —
     there is no secret tool, and the PAT must never be a literal (`README.md` "Common contract":
     *"${GITHUB_TOKEN} only; never a literal PAT"*).
  4. *"## Skill hosting decision (still pending)"* with three options — the decision was made long ago;
     all 20 prompts fetch from `raw.githubusercontent.com`. The file's last line still says *"Recommend:
     Option 2 (raw.githubusercontent.com) for now … Switch to Option 1 once we know the sandbox is
     persistent."* — Option 2 was adopted fleet-wide and Option 1 was never taken.
- **Cost of leaving it:** 6,360 bytes of a plan that reads like a spec. The specific risk is a future
  agent or human reading it to answer *"what happened to crons #3, #11, #21, #24?"* — the file says
  "DESIGN QUESTION", "KEEP LOCAL", "PILOT", i.e. that they are pending, when in fact they were dropped.
  The orphan skills (C7) are the same four crons' specs, so the file and the orphan skills agree with
  each other and disagree with reality.
- **Recommended fix:** **move it to history, do not rewrite it** — it is a correct snapshot of the
  2026-09-25 triage, and rewriting it would destroy the provenance the 4-dropped crons need. Move
  `cloud-prompts/_classification.md` → `cloud-prompts/history/_classification-2026-09-25.md`, and put a
  6-line header on it:

  ```
  # HISTORICAL — 2026-09-25 triage of the 26 original local Windows crons.
  # NOT operative guidance. The live fleet is 23 routines described by
  # cloud-prompts/cron-prompts/README.md. Originals #3, #11, #21 and #24 were DROPPED
  # (no live routine); original #18 became cloud routine #01. Finviz, the `secret`
  # tool and the local python helpers no longer exist — see _shared/RUNTIME-CONTRACT.md.
  ```

  Add a matching 4-line "Status" block to `cloud-prompts/_classification_memo.json` (1,543 B, also
  historical) or move it alongside.
- **Confidence:** high

---

### C12 — The three sources of truth are consistent; the *snapshot* is what has gone stale

- **Severity:** high
- **Scope:** `cron-prompts/README.md` (11,128 B), `cron-prompts/ROSTER.md` (3,772 B),
  `cron-prompts/roster.json` (10,479 B)
- **Evidence:** `cloud-prompts/cron-prompts/{README.md,ROSTER.md,roster.json}` — all three are present and all three list 23 routines:

  ```
  README rows=23  ROSTER.md rows=23  roster.json=23

  id    inRM  inRO  inRJ  divergence
  01    Y     Y     Y    ok
  02    Y     Y     Y    ok
  ...   (all 23)
  26    Y     Y     Y    ok
  90    Y     Y     Y    ok
  91    Y     Y     Y    ok
  ```

  A field-by-field cross-check of **schedule, day-of-week, project id and artifact path** across all
  three, for all 23 routines, found **zero substantive divergences** — the only mismatches are backtick
  and wording artifacts of the README's `none (writes no artifact)` cell for #91 and #90's
  `_audit/status.json (audit/status branch)`. **The generator scripts still exist and are wired**:
  `tools/gen_index.py` rebuilds the README table from `tools/schedule-ground-truth.json` + the live
  scheduler + `tools/gen_roster.py`'s ARTIFACTS map, and `tools/gen_roster.py` writes both `ROSTER.md`
  and `roster.json` from the scheduler + `origin/main`. `tools/schedule-ground-truth.json` (5,278 B) is
  intact and is explicitly *"GROUND TRUTH … Never regenerate this from the live scheduler."*

  **What is stale is the content, not the structure:**
  1. `roster.json` carries `"as_of_et": "2026-10-31"` and `ROSTER.md` says *"As of **2026-10-31 ET**"*.
     Today is **2026-11-02**. Both are 2-day-old snapshots with no expiry marker on the *content* (the
     date is in a header a reader may skip).
  2. `ROSTER.md`'s health summary says: *"**2 routine(s) have not fired yet under their current schedule**
     — expected, NOT a finding: `14-macro-calendar-week-ahead` — first fire 2026-11-01;
     `22-weekly-market-recap-preview` — first fire 2026-11-01."* **Both have now fired** — `origin/main`
     carries `8467fee cron 14 14-macro-calendar-week-ahead.md 2026-11-01` and
     `a109ce6 cron 22 22-weekly-market-recap-preview.md 2026-11-01`, and `weekly/` now contains
     `2026-11-01-preview.md`, `2026-11-01-preview-tldr.md`, `2026-11-01-preview-movers.csv`. The roster
     still classifies them as "?" and "not yet fired", and its summary still says *"No routine is outside
     its delivery tolerance."*
  3. `README.md:119` — `## Open findings (2026-10-30)` — still states for #22:
     *"**Has never delivered.** No `weekly/` directory exists on `origin/main` at all."* That is now
     false: `git ls-tree -r --name-only origin/main -- weekly` returns **3 files**. The table is dated
     2026-10-30 in its heading but has no "superseded" marker on the rows, and it sits at the end of the
     README where it reads as the current state.
- **Cost of leaving it:** this is the **highest-traffic stale claim in the repo**. The README is what a
  human or agent opens to answer "is the fleet healthy?" — and it tells them #22 has never delivered,
  which is false. The ROSTER's "not yet fired / expected, NOT a finding" classification is worse in kind:
  it is a **self-exempting** verdict. The auditor's job is to catch a routine that did not deliver, and
  the roster pre-declares two of them as expected — if the roster is not regenerated after the deadline
  passes, the exemption becomes permanent and the auditor inherits it. Both #14 and #22 delivered this
  time; the exemption did not catch anything, it just waited.
- **Recommended fix:** (a) regenerate `ROSTER.md` + `roster.json` today (`cron_read view=list > tasks.json;
  python3 tools/gen_roster.py --tasks tasks.json --repo ./outputs-clone --out .`) — the machinery is
  there and works; (b) make the roster **expire**: have `gen_roster.py` stamp `as_of_et` and have
  `gen_index.py` or a CI check fail if `as_of_et` is older than 48 h, so a stale roster is loud rather
  than authoritative; (c) change the "not yet fired — expected, NOT a finding" rule to **expire at
  `first_fire + 24 h`**: after that, an undelivered routine must be reported as `MISSING`, not exempt;
  (d) move the README's `## Open findings (2026-10-30)` table to `## Historical findings (2026-10-30)` and
  replace the #22 row with its resolution
  (*"#22 delivered 2026-11-01 — `weekly/2026-11-01-preview.md`."*).
- **Confidence:** high

---

### C13 — The outputs repo's default branch is 25 commits behind, and the README says it is a mirror

- **Severity:** high
- **Scope:** `karizaco/minimax-cloud-outputs` — `origin/master` vs `origin/main`
- **Evidence:**

  ```
  $ git rev-list --count origin/master..origin/main
  25
  $ git merge-base --is-ancestor origin/master origin/main && echo "fast-forwardable"
  master is NOT an ancestor of main
  $ git ls-tree -r --name-only origin/master | wc -l   -> 746
  $ git ls-tree -r --name-only origin/main   | wc -l   -> 831
  ```

  **`master` is not behind `main` — it has diverged.** `main` has 25 commits `master` lacks, and
  `master` has **1 commit `main` lacks**: `1094edc refs: point to cron #19 review docs in the migration
  repo; drop them from the artifact sink` — a **staged deletion** of `earnings/IMPROVEMENTS-cron19.md`
  that exists on `master` and not on `main`. That is exactly the `git add -A` hazard the README warns
  about, realised on `main`.

  **86 files exist on `main` and not on `master`**, including every artifact delivered since 2026-10-30:
  `weekly/2026-11-01-preview.md` (+2 more), `macro-calendar/2026-11-01-week-ahead.md`,
  `ntrt/2026-10-29.md`, `ntrt/2026-10-30.md`, `daily-screens/2026-10-30/` (25 files),
  `daily-screens/2026-10-31/` (4), `daily-briefs/2026-10-30-post-market.md`, `earnings/2026-10-27-reminders.md`,
  `earnings/2026-10-28-reminders.md`, `options-flow/2026-10-30.md`, `us-eod/2026-10-30.{csv,md}`,
  `international-eod/2026-10-30/` (18), `us-stocks-in-play/2026-10-30-{close-candidates.csv,midday.md}`,
  `mcp-health/ledger.md`, `mcp-health/2026-W44.md`, `AGENTS.md`, `refs/cron-ops.md`,
  `refs/cron19-earnings-reminder-review.md`, `refs/plan-sources-and-mcp-tracking.md`, and **11
  `SKIPPED_*` markers**.

  **The README's claim is now false** (`cron-prompts/README.md`, "Repository rules"):
  > *"`master` is kept as a **fast-forward mirror of `main`** — the auditor (`#90`) advances it daily, and
  > it holds the same commits, so a clone still sees current artifacts."*

  It holds neither: not the same commits (25 apart), and not a fast-forward mirror (diverged). The
  auditor did run — `origin/audit/status` has `47e8044 audit 2026-10-31` — but the mirror step did not
  land.
- **Cost of leaving it:** `master` is the repo's **`default_branch`** (GitHub's `default_branch` cannot be
  changed without Administration scope, which the PAT does not have). **A plain `git clone` of the outputs
  repo lands on `master` and shows an artifact repo that is 86 files stale and missing every delivery
  since 2026-10-30** — including the `weekly/` tree the README says a reviewer would look for, and
  including `ntrt/2026-10-29.md`, which was the subject of a correction on 2026-11-01. Every reader who
  clones instead of fetching `main` sees a different repository from the one the fleet publishes to.
- **Recommended fix:** (a) advance the mirror —
  `git fetch origin main && git push origin origin/main:master` — but first resolve the divergence:
  `main` has a deletion that `master` does not, so push `main` to `master` as a **non-fast-forward** with
  `--force-with-lease` (this repo's own rules forbid `--force` for routine pushes; this is a manual
  operator action, not a routine push, and it is the only way to make `master` equal `main`);
  (b) until the mirror is fixed, **change the README wording** from "a fast-forward mirror of `main`" to
  the truth: *"`master` is the default branch and may lag `main` by up to one auditor cycle; always
  `git fetch origin main && git checkout main` before reading artifacts."*; (c) re-check why the auditor's
  mirror step did not run on 2026-11-01 — the auditor's own status branch shows it fired.
- **Confidence:** high

---

### C14 — Stale artifact trees in the outputs repo that no live routine writes

- **Severity:** medium
- **Scope:** `karizaco/minimax-cloud-outputs` `origin/main` — **119 files across 11 groups** sit in trees
  no live routine writes; **111** of them are dead or superseded artifacts (the other 8 are the `refs/`
  tree — 5 superseded pre-cloud docs, 3 current notes)
- **Evidence:** `minimax-cloud-outputs` `origin/main` — every top-level tree mapped against the live routines' declared artifact paths (from `roster.json`):

  | Tree | Files on `main` | Newest content | Live routine writes it? |
  |---|---|---|---|
  | `daily-screens/` | 386 | 2026-10-31 | **yes** (#04,#06,#07,#08,#09,#10) |
  | `us-eod/` | 114 | 2026-10-30 | **yes** (#20) |
  | `international-eod/` | 98 | 2026-10-30 | **yes** (#05) |
  | `ntrt/` | 55 | 2026-10-30 | partly — `_pipeline/` (9 `.py`) and `_raw/` (34 files = 30 `.json` + 4 `.log`) are **scratch** |
  | `data_cross/` | 34 | 2026-10-27 | **no** — #12's contract is `cross-asset/{date}.md` and its push stages only `cross-asset` |
  | `us-stocks-in-play/` | 23 | 2026-10-30 | **yes** (#17) |
  | `daily-briefs/` | 19 | 2026-10-30 | **yes** (#23,#26) |
  | `earnings/` | 17 | 2026-10-30 | **yes** (#15,#19) |
  | `asia-pre-market/` | 17 | 2026-10-30 | **yes** (#02) |
  | `options-flow/` | 9 | 2026-10-30 | **yes** (#16) |
  | `refs/` | **8** | — | **no** (see C15) |
  | `2026-09-27 … 2026-10-24/` | **20** | 2026-10-24 | **no** — 100% `SKIPPED_*` (C4) |
  | `scripts/` | 5 | — | **1 of 5** — only `earnings_reaction_scanner.py` is fetched, by #15 |
  | `macro-calendar/` | 5 | 2026-W44 | **yes** (#13,#14) |
  | `cross-asset/` | 4 | 2026-10-28 | **yes** (#12) |
  | `weekly/` | 3 | 2026-11-01 | **yes** (#22) |
  | `data2/` | 3 | 2026-10-21 | **no** |
  | `cron-prompts/` | 3 | — | **no** — `*.HARDENED.md` prompt copies |
  | `catalog/` | 2 | 2026-10-26 | **no** |
  | `mcp-health/` | 2 | 2026-W44 | **yes** (#01) |
  | `pattern-study/` | 1 | — | **no** — #06 writes `daily-screens/{date}/weekly-ipo.md` |
  | `research/` | 1 | — | **no** — the Windows `research/` tree |

  **Dead-file total: 119 files** in trees no live routine writes = 20 (date dirs) + 2 (`catalog/`) + 3
  (`cron-prompts/`) + 3 (`data2/`) + 34 (`data_cross/`) + 1 (`pattern-study/`) + 1 (`research/`) +
  4 (`scripts/`, unreferenced only) + 8 (`refs/`) + 9 (`ntrt/_pipeline/`) + 34 (`ntrt/_raw/`) = **119**.
  Of those 119, **5** are the superseded pre-cloud `refs/` docs (C15) and **3** are current
  hand-maintained notes in the same tree, leaving **111 genuinely dead or superseded artifacts**.

  **`ntrt/_pipeline/` (9 `.py`) and `ntrt/_raw/` (30 `.json` + 4 `.log`)** are the largest single win: an
  artifact repository is publishing **executable Python and raw API dumps**. The repo's own skill ships
  only `ntrt_probe.py`, so the pipeline in `ntrt/_pipeline/` is a **second, unfrozen copy** of #25's logic
  that no prompt references and nobody reviews. That is the same class of problem as the `refs/`
  duplication in C15 — a second source of truth that can drift silently.

  Two further oddities: `macro-calendar/2026-W44-week-mid.md` does not match either declared pattern
  (`{date}-midweek.md` for #13, `{date}-week-ahead.md` for #14) — it is a **third naming scheme**; and
  `us-eod/2026-10-30.md` sits next to `us-eod/2026-10-30.csv` although #20's contract is the CSV only.
- **Cost of leaving it:** **119 files of 831 on `main` (≈14%)** sit in trees that no live routine writes
  — 111 of them dead or superseded, 8 the `refs/` notes tree. They are not inert: `ntrt/_pipeline/` is a
  second copy of #25's logic, `refs/` is a second copy of the runtime contract (C15), and the `SKIPPED_*`
  markers are a second copy of the window-check vocabulary (C4). Every one of them can be mistaken for
  the live thing by a reader — or by an agent that reads the outputs repo as evidence of current
  behaviour. `data_cross/` at 34 files is the largest single dead tree after the date dirs, and it
  contains **two copies** of `compute.py`, `mats.json` and `prior_*.md` at both the root and inside
  `2026-10-27/`.
- **Recommended fix:** delete the dead trees from `main` in one additive commit (do **not** use
  `git add -A` — the repo's own rule; stage the exact paths, and note that deleting `earnings/IMPROVEMENTS-cron19.md`
  already happened on `main`, so the staging discipline matters here). Delete:
  `2026-09-27/`, `2026-10-03/`, `2026-10-04/`, `2026-10-10/`, `2026-10-11/`, `2026-10-18/`, `2026-10-24/`,
  `catalog/`, `cron-prompts/`, `data2/`, `data_cross/`, `pattern-study/`, `research/`,
  `scripts/{build_weekly_artifacts,parse_focus_rvol,pull_weekly_data,shibui_mcp}.py`,
  `ntrt/_raw/`, `ntrt/_pipeline/`. Move `ntrt/_pipeline/*.py` into
  `cloud-prompts/skills/ntrt-gap-brief/scripts/` in the migration repo first — they are the real
  implementation and they belong under version control next to the skill that calls them, not in an
  artifact sink. Re-point `macro-calendar/2026-W44-week-mid.md` to the `{date}-midweek.md` naming.
  Leave `refs/cron-ops.md`, `refs/cron19-earnings-reminder-review.md` and
  `refs/plan-sources-and-mcp-tracking.md` in place — those three are current.
- **Confidence:** high

---

### C15 — `refs/` in the outputs repo is a stale, pre-cloud copy of the runtime contract

- **Severity:** medium
- **Scope:** `minimax-cloud-outputs` `origin/main` `refs/` — **8 files total**, of which **5 are legacy
  pre-cloud** (39,976 B) and **3 are current**
- **Evidence:** `minimax-cloud-outputs` `origin/main` `refs/` — the 8 files, and what makes the 5 legacy ones wrong:

  | File | Bytes | Problem |
  |---|---|---|
  | `refs/crons.md` | 6,461 | Every routine is described with Windows paths: *"Produce the daily-screens directory under `C:/Users/admin/<user>/research/markets/daily-screens/<YYYY-MM-DD>/`"* — a path that exists nowhere. Also says *"Each prompt loads the `stock-screener-suite` skill automatically because the trigger phrase matches the skill description"* — a skill-loading mechanism the Cloud prompts do not use (they fetch `SKILL.md` by URL). |
  | `refs/fallbacks.md` | 9,943 | Defines the fallback chain as *"**MCP → Finviz URL (web_fetch) → TradingView public JSON → Yahoo Finance URL**"*, with **Finviz as tier 2** and a whole section *"Tier 2 — Finviz URL builders"* teaching `finviz.com/screener.ashx?v=111` construction. Finviz is **403 site-wide from this egress** (`RUNTIME-CONTRACT.md` §2f: egress-IP reputation, proven across 4 UAs, headless chromium, and headed chromium under Xvfb). Tier 1 is an MCP tool that is not registered. **Two of the first three tiers are dead.** |
  | `refs/filters.md` | 10,719 | *"All SQL is `shibui-finance` SQL (see `mcp__shibui-finance__get_database_schema` for table names). `screen_stocks` and `screen_etf` live in the base `mcp__tradingview__` namespace"* — three unregistered tool namespaces. The SQL itself is still the right shape (it is what the `shibui` bridge pack answers), but the *call* is wrong: it is now `python3 mcp_bridge.py shibui …`, and it is capped at **200 rows** and is **T+1**. |
  | `refs/tiering.md` | 4,316 | *"see `scripts/screen.py:_STYLIST_FROM_ORIGIN` for the mapping"* and *"`FOCUS_THRESHOLD_STYLISTS` and `TIER_A_THRESHOLD_STYLISTS` constants in `scripts/screen.py`"* — **that file does not exist in either repo**. The thresholds this doc governs (#09's Tier-A output) are documented only against a missing file. |
  | `refs/sources-us-stocks-in-play.md` | 8,537 | Contains a **repo gotcha that is no longer true**: *"The cloud sandbox `.gitignore` excludes `refs/` (line 4), so a plain `git add -A` silently skips anything written here … The existing `refs/*.md` were force-added. `git add -f refs/<file>.md`"*. The current `.gitignore` on `main` **does not mention `refs/` at all** — it excludes `.plugin-cache/`, `.cache/`, `.skills/`, `.skill_cache/`, `.scratch/`, `.home/`, `.tmp/`, `__pycache__/`, `*.pyc`, `helper_*.py`, `*.zip`, `*.log`, `sp.json`, `cron20_prompt_new.txt`. Following this doc today means `git add -f` on a path that needs no forcing, and worse, it implies `refs/` is an untracked side-channel when it is not. The doc's evidence base is also explicitly *"Tested from the cloud sandbox on 2026-10-25 (Saturday …)"*. |
  | **legacy subtotal** | **39,976** | |
  | `refs/cron-ops.md` | — | current — keep |
  | `refs/cron19-earnings-reminder-review.md` | — | current — keep |
  | `refs/plan-sources-and-mcp-tracking.md` | — | current — keep |
  | **`refs/` total** | **8 files** | |

  **Also note the duplication:** `refs/fallbacks.md` and `refs/filters.md` are a **second copy of the
  runtime contract** that is *older and wrong* where `_shared/RUNTIME-CONTRACT.md` is authoritative. Two
  documents, one subject, one correct and one not — and the wrong one is in the repo people read for
  artifacts.
- **Cost of leaving it:** 39,976 bytes (5 files) of a document set that is the *oldest* copy of the
  source-of-truth and contradicts it on every point that matters (Finviz reachable, MCP tools callable,
  `scripts/screen.py` present, `refs/` gitignored). The `refs/tiering.md` case is a live correctness risk
  for #09, not just clutter.
- **Recommended fix:** delete `refs/crons.md`, `refs/fallbacks.md`, `refs/filters.md`, `refs/tiering.md`
  from the outputs repo and replace `refs/sources-us-stocks-in-play.md` with a 3-line pointer
  (*"Source of truth for endpoint status: `cloud-prompts/_shared/RUNTIME-CONTRACT.md` in
  `karizaco/maxhermes-migration`. This file's 2026-10-25 endpoint table is superseded."*). Before deleting
  `refs/tiering.md`, **copy its threshold definitions (Master 200 / Stalk 50 / Focus 12 / Tier-A 8; 2 and 3
  stylists) into `cloud-prompts/skills/stock-screener-suite/SKILL.md`**, so #09's thresholds live with the
  code that applies them. Also fix the now-false `refs/` gitignore note in
  `sources-us-stocks-in-play.md` if you keep it.
- **Confidence:** high

---

### C16 — Smaller dead references and stale prose worth clearing

- **Severity:** low
- **Scope:** 8 items
- **Evidence:** 8 items across the prompts, skills and the outputs repo — each listed below with its fix:

  1. **`CRITICAL REMINDERS` #4 still describes the weekend skip path** in all 20 producer prompts —
     `02-asia-pre-market-reactions.md:357`: *"If the cron fires outside its intended window (e.g. holiday,
     **weekend when it should be weekday**), exit cleanly with 'out-of-window: <reason>'."* After C1, the
     weekend case cannot occur and the `SKIPPED_*` marker it implies no longer exists. **Fix:** drop
     "weekend when it should be weekday" and the `SKIPPED_*.md` reference.
  2. **`cloud-prompts/01-weekly-mcp-health-check.md` sits outside `cron-prompts/`** — it is the only prompt
     not in the directory the README indexes, and `tools/gen_index.py:34` hard-codes the filename
     `"01-weekly-mcp-health-check.md"` in its no-ARTIFACTS list, implying it belongs there. **Fix:** move it
     to `cloud-prompts/cron-prompts/01-weekly-mcp-health-check.md` and update the two paths that reference
     it (`README.md`'s generator note and `cloud-prompts/cron-prompts/91-schedule-drift-guard.md`, if it
     points at it).
  3. **`cloud-prompts/skills/README.md:25-31`** says *"Until cron #11 is migrated to Cloud, manual is the
     only path."* #11 was never migrated (it is one of the 4 dropped originals, C11). **Fix:** rewrite the
     Maintenance section to say the mirroring is manual and #11 will not be migrated.
  4. **`cloud-prompts/preopen-feed-plan.md` references three files that do not exist** —
     `cloud-prompts/_shared/preopen_feed.py`, `cloud-prompts/n8n/README.md`,
     `cloud-prompts/n8n/workflow-preopen-feed.json`. The plan is a proposal (11,196 B, "Status: proposal,
     awaiting owner approval"), so the references are forward-looking, but an auditor grepping for dead
     references hits them. **Fix:** either ship the two n8n files or mark the references
     "*(to be created — proposal not yet approved)*".
  5. **8 prompts fetch a `scripts/<name>.py` from a skill dir that has no `scripts/` directory** —
     `02`, `13`, `14`, `16`, `17`, `19`, `22`, `23`. **Fix:** make the instruction conditional
     ("*if the fetched SKILL.md references a helper under `scripts/`, fetch it from the same URL base*").
  6. **`cloud-prompts/cron-prompts/README.md`'s "Open findings (2026-10-30)" table** — see C12; the
     #22 row is false as of 2026-11-01.
  7. **`us-eod/2026-10-30.md`** exists next to `us-eod/2026-10-30.csv` although #20's contract is the CSV
     only; **`macro-calendar/2026-W44-week-mid.md`** matches neither declared filename pattern. **Fix:**
     bring both under the declared patterns.
  8. **`ntrt/2026-10-23-session.md`** and **`ntrt/2026-10-23.md`** both exist for the same date — two
     artifacts for one fire, one of them with a `-session` suffix that is not in the contract
     (`ntrt/{date}.md`). **Fix:** confirm which is canonical and delete or re-path the other.
- **Cost of leaving it:** individually small (~600 bytes of prompt prose + a handful of files), but they
  are the residue that makes the repo's "is this current?" question unanswerable without a full re-audit.
- **Recommended fix:** as listed, in one pass alongside C1/C5/C12.
- **Confidence:** medium

---

## Method and coverage

**Read-only throughout.** Nothing in `/workspace/mig` was created, modified or deleted; no push was made to
any remote. The outputs repo was cloned to `/workspace/.mavis/plans/plan_9bd4fa95/workspace/outputs-repo`
with `--filter=blob:none`; only `git ls-tree`, `git log`, `git cat-file`, `git show` and `git diff` were
run against it. Note for the next operator: the sandbox's `~/.gitconfig` sets
`http.sslCAInfo = /etc/ssl/certs/agent-identity/sandbox-gateway-ca.crt`, **which does not exist in this
sandbox** — the clone needs `-c http.sslCAInfo=/etc/ssl/certs/ca-certificates.crt`. `GITHUB_TOKEN` was not
set in the environment, but the outputs repo is public and clones without credentials.

**Byte-count convention:** every size in this document is a true UTF-8 byte count — `os.path.getsize()`
for files, `len(text.encode('utf-8'))` for extracted blocks, `git cat-file -s` for blobs in the outputs
repo. Character counts are never quoted as bytes.

**What was checked, and how:**

| Question | Method | Result |
|---|---|---|
| Dead weekend branches | Simulated every skip branch against every day-of-week its own scheduler expression can fire, for all 20 prompts | 20/20 unreachable (C1) |
| Byte cost | UTF-8 byte measurement of each block, each weekend subset, each prose section | 32,921 B window blocks; 17,546 B weekend subset; 4,927 B false-prose; 11,618 B dead tool list |
| Superseded runtime claims | Grepped `429` / `persistent` / `CORRECTION` across prompts, README, RUNTIME-CONTRACT; cross-checked the ladder's endpoints against §2a's table | 1 live false claim (README), 1 structural trap (§2a vs §2b) |
| Orphan skills | Mapped all 20 skill dirs → the prompts that fetch them by URL; sized `SKILL.md` and full dir separately | 7 orphans — 51,422 B `SKILL.md` / 113,325 B full dir (C7); 1 dangling pointer in a live skill |
| Dead file references | Extracted every path-like token from 22 prompts + 20 SKILL.md + shared docs + `cloud-prompts/*.md`, tested each against the tree | 76 distinct refs: 31 resolve, **45 unresolved** (34 Windows-shaped, 11 other) |
| Dead routine numbers | Diffed `_classification.md`'s 26 originals against `roster.json`'s 23 live routines | 4 genuinely dead (#3, #11, #21, #24); #18 renumbered to #01 |
| Sources of truth | Field-by-field diff of README table × ROSTER.md × roster.json on schedule / fires / project / artifact for all 23 | all three present, 23 each, **0 substantive divergences**; staleness only |
| Generator still exists | Read `tools/gen_index.py`, `tools/gen_roster.py`, `tools/schedule-ground-truth.json` | all present and wired |
| Historical artifacts in the outputs repo | Mapped every top-level tree on `main` against the 23 declared artifact paths; counted `SKIPPED_*`; counted file extensions inside `ntrt/_raw/` | **119 files in 11 groups** no live routine writes (**111** dead/superseded); 31 `SKIPPED_*`; default branch 86 files stale and diverged |
| Metainstructions region | Read the pre-`### PRIMARY SOURCE` and post-`## CRITICAL REMINDERS` regions of a representative prompt and diffed the blocks across the fleet | dead tool list (C10), false holiday claim (C2), stale weekend reminder (C16.1) |

**Skill-directory count reconciled against the brief:** `ls -d cloud-prompts/skills/*/` returns **20
directories** (plus `README.md`, i.e. 21 entries). The brief's "22 skill directories" counts the two
extra non-directory entries or a different snapshot; 20 is what is on disk today, and all 20 are mapped
in C7.

**Not verified:** the live scheduler state (`cron_read` is not reachable from this session), so the
deployed schedules were taken from `roster.json` (`as_of_et: 2026-10-31`) and cross-checked against the
README's generated table and the ground-truth file — all three agree, but if the scheduler changed since
2026-10-31, the C1 simulation should be re-run against it. The skill **bodies** were not executed; the
"unreachable" claims in C1/C7/C9 are about file and URL resolution and branch reachability, not runtime
behaviour.
