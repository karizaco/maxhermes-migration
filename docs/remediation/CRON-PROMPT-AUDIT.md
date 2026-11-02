# Cloud cron instruction audit — 23 routines

**Scope:** the metainformation and instructions of all 23 cloud cron prompts in
`karizaco/maxhermes-migration` (repo HEAD `24baf07`) — everything from the start of each file up to
(but excluding) `### PRIMARY SOURCE: the MCP-over-HTTP bridge (use this FIRST)`, plus everything from
`## CRITICAL REMINDERS` to end of file. The middle body was examined for cross-references only.
The 23 routines are 21 digest producers plus `#90` (delivery auditor) and `#91` (schedule drift
guard); `#01` (weekly MCP health check) lives at the `cloud-prompts/` root rather than in
`cron-prompts/`.

**Method:** four parallel audits (structural consistency / factual accuracy against the live
sandbox / stale content / token cost and instruction quality), each independently re-derived and
cross-checked, plus an owner-side independent verification pass. 65 findings in total. Every
runtime claim was measured from the sandbox rather than read off the prompt; every number is a
byte count or a file:line.

**Read-only:** `/workspace/mig` was not modified (`git status --porcelain` empty, HEAD unchanged
before and after). No remote was pushed. The outputs repo was read only.

---

## Executive summary

1. **The fleet is structurally consistent but factually stale, and the repo is not what runs.** 20 of
   23 prompts share one template whose shared blocks agree byte-for-byte after normalising the
   routine's own slug, output dir, commit message and flag values. But **21 of 23 deployed prompts
   no longer match their own repo file**, and **18 still assert "the connector catalog exposes 15
   tools" and "Yahoo returns HTTP 429"** — both false. Only `#17` has the corrected contract
   deployed.
2. **A repo edit changes nothing until it is deployed.** The 2026-10-31 contract rewrite (133 tools,
   Yahoo working, `market-recap`, Barchart, `probe_mcp.py`) reached exactly **one** of 23 live
   routines. This is the single highest-leverage fix and it is a *deployment* fix, not a writing fix.
3. **Half the runtime facts are environment-dependent, so absolute claims are the wrong tool.**
   Yahoo JSON returned 429 from one cron session and 200 from another on the same day; `mcode-tools`
   is present in some sandbox images and absent in others. The instruction form must be
   "try it, fall through on failure" — not another absolute.
4. **The in-prompt contract contradicts the contract it tells the agent to fetch.** 19 running
   prompts say "Yahoo is hard-blocked"; the `_shared/RUNTIME-CONTRACT.md` they fetch says "Yahoo is
   200 OK, do not hard-code a Yahoo-avoidance path" and describes a 48-tool `market-recap` pack the
   prompt never mentions.
5. **≈30 KB of window-check code is unreachable.** The day-of-week now lives in the scheduler, so
   no weekday/weekend/`DAY_OF_WEEK` branch can ever fire — yet 17 tails promise a holiday skip that
   **only `#19` implements**. The scheduler fires Mon–Fri *including* market holidays.
6. **Cost:** the deployed fleet loads **433,427 bytes ≈ 108,356 tokens** per full fire-set and
   **≈423,148 tokens per calendar day** across 39 fires. The proposed changes remove **34.7 %** of
   that; net of three deliberately-added quality rules, **30.1 %**.
7. **Quality defects that cost real output:** no source-precedence rule in 18 of 20 market-data
   routines; a live `git push … | head -3` exit-status trap in `#90`; and an artifact-dating rule
   that would discard a real trading-day brief on a delayed replay.

---

## Coverage matrix

| Track | Question | Findings | Where they land |
|---|---|---|---|
| A — structural consistency | Q1 consistency | 23 (A1–A23) | §2, §7 |
| B — factual accuracy vs live sandbox | Q2 accuracy | 14 (B1–B14) | §3, §7 |
| C — stale / dead / orphaned content | Q3 staleness | 16 (C1–C16) | §4, §7 |
| D — token cost and effectiveness | Q4 what to change | 12 (D1–D12) | §5, §6 |
| Owner independent verification | cross-check | ENV-1…ENV-10 | §3.4, §8 |

Every finding appears in the body below or in the per-routine matrix (Appendix A). The only
findings deliberately excluded are listed in §9.

---

## 1. Q1 — How consistent is it?

**Structurally: highly consistent. Factually: not at all.**

The 20 template-shaped prompts share one skeleton. Canonical normalisation (replacing only the
routine's own slug, output directory, commit message and window-flag values) makes the four shared
blocks byte-identical across the fleet:

| Block | Prompts | Bytes each | Fleet | Verdict |
|---|---|---:|---:|---|
| `## RUNTIME DATA-SOURCE CONTRACT` | 19 | 1,827–2,202 | 35,677 B | identical |
| `## GIT PUSH (OPTIONAL)` | 21 | 3,190–3,255 | 67,000 B | identical except 3 lines |
| `## DELIVERY VERIFICATION` | 21 | 1,468 | 30,841 B | identical |
| `## CRITICAL REMINDERS` tail | 19 | 868–1,161 | — | 7 variants |
| `## WINDOW CHECK` | 20 | ~2,386 | 32,883 B | 16 canonical + flag drift |

The bash bodies of the push blocks differ in exactly three lines (`mkdir`, `cp`, `git add` target).
That consistency is the good news and the problem: a single defect replicated 20 times is 20
defects, and a single fix propagated to 20 prompts is 20 fixes.

### Where it drifts

**Section-presence drift (A1, A23).** `#07` has **no `## CRITICAL REMINDERS` at all** — it is the
only routine whose tail carries none of the four standing reminders, including "do not call the
`mcp__*` tools — they are not registered in this runtime". It relies on the reader of
`### PRIMARY SOURCE` instead, which is exactly the trap `RUNTIME-CONTRACT.md:30` warns about.
`#01` has no `CRITICAL REMINDERS`, no `SCHEDULE`, no `WINDOW CHECK`, no `SKILL SPEC`, no `OUTPUT`,
no `GIT PUSH`, no `DELIVERY VERIFICATION` and no `DELIVERY` — its prompt body is nested inside a
fence. `#26`, `#90`, `#91` have no `## RUNTIME DATA-SOURCE CONTRACT`.

**Flag drift (A3, A4, A5).** Six distinct window-flag variants. `#16` is the only weekday routine
with `WEEKDAYS_ONLY=false`; `#26` drops the flag triple entirely so its window check cannot be
parsed by the same convention; `#06` uses `WEEKEND_ONLY=true` + `DAY_OF_WEEK=0` where the two
Sunday routines use `DAY_OF_WEEK=7`. None of these is currently harmful — because the whole block
is unreachable (C1) — but they are the seed of the next real defect.

**Schedule fields that cannot be checked (A6, A7, A8).** `#06`, `#13` and `#14` name **no cron
expression at all**; `#06`'s prose says "Schedule is unchanged", which is false — it moved from
Saturday 10:00 (`migration-state.json:65`) to Saturday 15:00. Four routines carry a wrong "Original
local schedule" field. `#19`'s `## SCHEDULE` contradicts itself and drops the standard two-field
form.

**Reply-format contradiction (A14).** The shared README says "**no line cap** — cap by NAMES SHOWN".
Three routines impose a hard cap anyway: `#07` ("Six lines, no preamble:", and a completely
different schema with none of the five README headings), `#90` ("≤ 8 lines"), `#01` ("under 10
lines"). A consumer parsing replies by the README's structure gets nothing parseable from `#07`.

**Named but non-existent tools (A13, C10).** `## MCP TOOLS AVAILABLE` advertises
`extract_content_from_websites` in **16 of the 17 prompts** that carry the block — a tool the
shared contract says does not exist. Combined with the `mcp__*` names, **four tools are advertised
that are not registered** (C10).

**A dangling cross-reference (A2).** `#26`'s `## CRITICAL REMINDERS` points at a section that does
not exist in its own file.

**A path that is not a path (A21).** `#04`'s `## OUTPUT` says
`/workspace/daily-screens/{date}/reversal-bullish-3:55.{md,csv}` — shell brace-expansion syntax
embedded in a path literal. Its own delivery check verifies only the single `.md` path, and the
roster's filename-suffix anchor does not match `.{md,csv}`, so the `.csv` is untracked.

**Skill URLs: all good, but with a large blast radius (A18).** All 20 skill URLs resolve — zero
404s. But **10 of the 21 skill-fetching routines read only 8 distinct skill documents**:
`stock-screener-suite/SKILL.md` serves 6 routines (`#04 #06 #07 #08 #09 #10`),
`eod-watchlist-snapshot` serves 2 (`#05 #20`), `macro-calendar-week` serves 2 (`#13 #14`). One bad
skill edit breaks six routines at once.

---

## 2. Q2 — Are the instructions inaccurate or wrong? How would you fix them?

### 2.1 The deployment gap — the repo is not what runs (B5, high)

| Fact | Repo | Deployed |
|---|---|---|
| Prompts byte-identical to repo | — | **2 of 23** (`#17`, `#90`) |
| Carry "exposes 15 tools" | 0 | **18** |
| Carry the 2026-10-28 Yahoo-429 text | 0 | **18** |
| Carry `market-recap` | 19 | **4** |
| Carry Barchart | 19 | **2** |
| Carry `probe_mcp.py` | 19 | **0** |

`#26` carries an *older* generation ("verified 2026-10-23/24"); `#91` is missing the
conversation-hygiene capability the repo detector already implements (B10); `#01` is a condensed
rewrite that drops the `--list-packs` truncation warning.

**Fix.** Make the repo the single source of truth and deploy it byte-exactly, with SHA-256
verification of the deployed prompt against the repo blob — a `cron_update` returns `{"ok": true}`
for a write that landed, not for a write that landed *correctly*. Deploy 3–4 prompts per session
and diff every task's `schedule`/`timezone`/`enabled`/`session`/`model`/`project_id` before and
after to prove the blast radius.

### 2.2 The `--list-packs` mislabel (B1, high)

21 prompts print:

```
python3 /workspace/mcp_bridge.py --list-packs                   # enumerate available packs
```

and `_shared/RUNTIME-CONTRACT.md:58-60` says it "enumerates them via the gateway's own
`discover_tools`". It does not. `--list-packs` is **semantic discovery over a query string** — the
default query returns `tradier`, `fmp`, `market-recap` and nothing else, while `stocktwits` and
`shibui` answer perfectly when called by name, and `shibui` **can never appear** in discovery
because it is a different host.

**Why it matters:** an agent that reads the probe output concludes that `stocktwits` and `shibui`
are gone and abandons two working, independent data sources.

**Fix.** Rename the comment and the contract sentence to "semantic search — returns packs matching
the query, not an inventory", and add an explicit known-pack list with the note that discovery
omits non-gateway hosts.

### 2.3 A probe that manufactures a false failure every week (B2, medium)

`#01`'s bridge-packs probe loops `get_quotes` over `stocktwits shibui market-recap`. `shibui` has
**no `get_quotes` tool** (its 12 tools are `stock_data_query`, `get_database_schema`,
`load_*_workflow`, `export_to_excel`). So `shibui` errors every single week — and the prompt's own
wording, "A pack that errors is a **degradation**, not a failure of the routine", turns that into a
permanent false degradation row in `mcp-health/ledger.md`.

**Fix.** Probe each pack with a tool it actually exports — `shibui` → `stock_data_query`,
`market-recap` → `get_quotes` — and treat "Unknown tool" as *not applicable*, not *degraded*.

### 2.4 The gateway resolves by tool name, not pack name (owner ENV-3)

`stocktwits get_quotes` and `market-recap get_quotes` return the **same server** (identical
payload, identical `retrieved_at`). The cross-source check is only meaningful for tools that
genuinely differ: `stocktwits chart_data` (gateway host) and `shibui stock_data_query`
(`mcp.shibui.finance` host) are two different hosts and do agree independently (SPY 755.72 from
both). **Fix:** state which pairs are genuinely independent; do not present `get_quotes` reached
through two pack names as two sources.

### 2.5 Three different finance-detection regexes, and one that cannot match (B4, medium)

Three copies of the "has a financial MCP landed?" test exist, with three different keyword sets
and two different matching semantics:

| Implementation | Keywords | Matching |
|---|---|---|
| `_shared/probe_mcp.py:42` (`FINANCE_RE`) | **16** — adds `tipranks`, `nasdaq`, `sec_?edgar` | `any(k in n.lower() for k in FINANCE_RE.split("|"))` — **literal substring** |
| `#01` inline (`01-weekly-mcp-health-check.md:78`) | **13** | `re.search(r'…', n, re.I)` — **regex** |
| `#17` inline (`17-us-stocks-in-play.md:201`) | **9** — drops `alpha_vantage`, `fmp`, `polygon`, `tiingo` | `re.search(…)` |

Two consequences:

1. **`probe_mcp.py`'s `sec_?edgar` keyword can never match anything.** The code splits the regex
   on `|` and does a *literal* `in` test, so it compares the 10 characters `sec_?edgar` against
   tool names. Verified: `'sec_?edgar' in 'mcp__sec_edgar__search'` → **False**. The other 15
   keywords have no regex metacharacters and work fine.
2. **`#17` misses four providers the other two catch** — an `mcp__fmp__*`, `mcp__polygon__*`,
   `mcp__alpha_vantage__*` or `mcp__tiingo__*` tool would be reported by `#01` and by
   `probe_mcp.py` but missed by `#17`'s inline probe.

**Fix.** One regex, in one file, imported by everyone; the in-run probe should call
`probe_mcp.py` rather than re-implement the match. Use a compiled `re.search` (or drop the
metacharacter) so the keyword set and the matching semantics cannot diverge again.

### 2.6 Runtime facts that flip between sessions (B5, B6, owner ENV-1/ENV-2)

**Yahoo JSON.** The repo says "working again" (measured 2026-10-31); the deployed copies say
"persistent 429" (measured 2026-10-28). Measured **from two different sessions on 2026-11-02**:
one saw 200 on chart/screener/quoteSummary/options, the other saw **429 on all four**, both hosts,
six spaced attempts, and a blocked crumb handshake. Yahoo's rate limiting is **per egress IP**;
cron sessions land on different egresses. Both observations are true.

**`mcode-tools`.** In one sandbox image the binary is at `/usr/local/bin/mcode-tools`, `connector
tools` exits 0 and `probe_mcp.py` prints `catalog_ok total=133 finance_tools=0` — confirming the
repo's 133-tools claim. In another image it is absent and the probe reports
`catalog_unreachable`. The three-state probe design is *correct* (the prompts already say
`catalog_unreachable` is "NOT evidence that no MCPs exist"), but it does not distinguish "probe
binary missing" from "catalog unreachable".

**Fix — this is the important one.** Do **not** deploy another absolute claim. Write the rule
conditionally:

> Yahoo JSON availability varies by egress. Try it; on 429 or 401 treat it as *not available from
> this session* and fall through. Never record "Yahoo is blocked" or "Yahoo works" as a standing
> fact — neither is true fleet-wide.

Same for the catalog: *"if `mcode-tools` is absent, skip the probe and use the normal source
ladder; absence of the probe binary is not a finding."*

### 2.7 Endpoint facts that are wrong in the contract (B13, B14, B11, owner ENV-5/ENV-6)

| Claim | Reality |
|---|---|
| `www.sec.gov` "200 OK" | **403** unless a contact-style UA; the contract states no UA requirement |
| nasdaqtrader halts "RSS", 200 with empty items | **302** to a 404 page |
| `stocktwits` exports a "sentiment" tool | it does not |
| "Stooq CSV is blocked (404)" | **HTTP 200** with a JavaScript proof-of-work challenge — an agent that checks only the status code parses HTML as CSV |
| Frankfurter works | `api.frankfurter.app` now **301s** to `api.frankfurter.dev/v1/latest`; 18 prompt examples use `curl -s` without `-L` and silently get an HTML 301 body |

**Fix.** Correct the contract's endpoint table; name `api.frankfurter.dev/v1/latest` as the
canonical host (or mandate `-L`); restate Stooq as "200 + JS challenge, body is not CSV"; state the
SEC UA requirement explicitly.

### 2.8 A shipped helper that cannot run (B8, high)

`_shared/barchart_fetch.py` has two independent blockers: a legacy `chrome-linux/` glob and a hard
`python-playwright` import in a Node-only image. The prompt text asserts "Playwright and the
chromium build are already installed … **No install step needed**". The track found Node Playwright
1.59.1 *is* preinstalled and the Python path cannot even be installed (no `pip`). A tested Node
drop-in (`barchart_fetch.js`) returning real Barchart data was supplied.

**Fix.** Ship the Node version; fix the Python one's glob and import; correct the install note.

### 2.9 Other verified inaccuracies

- `#17` — the one prompt deployed byte-identically to its repo file — still says the catalog
  "exposed 15 tools, ALL media/email" **internally**, contradicting its own corrected contract
  (B3, B12). It is simultaneously the best-deployed and a still-wrong routine.
- `#91`'s STEP 1 chunk-discovery command can select the wrong tool-result file and abort the
  detection (B9).
- `#16`'s `MARKET_HOURS_ONLY=true` at 16:35 ET is a live near-miss: the gate passes only because
  `HOUR=16 < 17`, so it would skip at 17:00.

---

## 3. Q3 — Is there stale or unused content?

### 3.1 ~30 KB of unreachable window-check code (C1, medium)

**32,883 B across 20 prompts (≈8,220 tokens per fire-set)** of window-check block, of which
**17,476 B** is the weekend-specific slice. The day-of-week now lives in the scheduler, so:

| Routine | Schedule | Branches | Can fire? |
|---|---|---|---|
| `#02 #04 #05 #08 #09 #10 #12 #15 #17 #19 #20 #23 #25` | `* * 1-5` | weekend (DOW≥6) | **NO** |
| `#06` | `0 15 * * 6` | weekday (DOW<6) | **NO** |
| `#13` | `0 14 * * 3` | DOW≠3 | **NO** |
| `#14` | `0 15 * * 0` | DOW≠7 | **NO** |
| `#22` | `47 17 * * 0` | DOW≠7 | **NO** |
| `#16` | `35 16 * * 1-5` | hours only | NO (16<17) |
| `#10 #12 #17` | hours | HOUR∉9..16 | NO at nominal time |

Worse than the token cost: the block is a **false safety net**. An agent reading it believes it
has a skip mechanism; it has none. The **31 `SKIPPED_*.md` markers** in the outputs repo are the
fossil record of when it *did* fire.

### 3.2 The holiday promise 16 routines make and one keeps (A17, C2, medium)

17 tails promise a holiday/weekend skip. **Only `#19` implements one** — and its list is correct and
complete (all ten 2026 NYSE closure dates are real weekdays, none missing; half-days at 07:00/13:00
correctly still report). The other 16 promise a behaviour they cannot deliver, and their
`## SCHEDULE` prose says the window check "is what still handles US market holidays, which no cron
expression can express" — but the window check that follows contains **no holiday branch**.

**Consequence:** the scheduler fires Mon–Fri *including* market holidays. On 2026-01-19, 02-16,
05-25, 09-07 and 11-26 the weekday routines will fire and write a normal artifact on a closed
market. (`#06` Sat, `#14`/`#22` Sun never fire on a weekday holiday, so the promise is vacuous for
them; 14 of the 17 are weekday routines that would misfire.)

**Fix.** Delete the dead day-of-week and market-hours branches — they are the scheduler's job — and
**promote `#19`'s holiday guard to every market-facing routine**, because that is the one branch a
cron expression genuinely cannot express.

### 3.3 A README that contradicts the repo it indexes (C5, high)

`cron-prompts/README.md:54-55` — the section every routine and every new agent is pointed at —
still says *"Yahoo JSON endpoints return persistent 429"*. Contradicted by three places in the same
repo: `_shared/RUNTIME-CONTRACT.md:119-125` ("**That is no longer true** … Do not hard-code a
Yahoo-avoidance path"), all 20 prompts' corrected text, and the measured reality.

**Fix.** Correct the README to the conditional form (§2.6) and regenerate it from the contract
rather than hand-editing.

### 3.4 The fleet's three sources of truth are consistent; the *snapshot* is stale (C12, high)

README.md, ROSTER.md and roster.json all list **23** routines and a field-by-field cross-check of
schedule, day-of-week, project id and artifact path found **zero substantive divergences**. The
generators still exist and are wired (`tools/gen_index.py`, `tools/gen_roster.py`,
`tools/schedule-ground-truth.json`).

What is stale is the *content*: the roster's last-delivered dates and the README's schedule table
are snapshots of an earlier scheduler state. The README even documents its own prior failure — "a
hand-kept table is a table that lies: it sat at '21 routines' while the fleet was 23, listed five
Mon-Fri routines as 'every day', and omitted #01 and #91 entirely until 2026-11-02" — and then
hand-kept another one.

**Fix.** Regenerate both from the scheduler; never hand-edit.

### 3.5 The outputs repo's default branch has diverged (C13, high)

```
git rev-list --count origin/master..origin/main   ->  25
git rev-list --count origin/main..origin/master   ->   1
git merge-base --is-ancestor origin/master origin/main  ->  NOT an ancestor
files on master: 746      files on main: 831
```

`master` was last merged from `main` on **2026-10-30 16:46** (merge commit `8bdb2d0`, the only
commit `main` lacks) and has not been touched since; `main` has moved 25 commits ahead. The
divergence is not corruption — it is **staleness on a branch that is the clone default**:
`origin/HEAD → origin/master`.

**86 files** exist on `main` and not on `master`, including every artifact delivered since
2026-10-30: `weekly/2026-11-01-preview.md` (+2 more), `macro-calendar/2026-11-01-week-ahead.md`,
`ntrt/2026-10-29.md`, `ntrt/2026-10-30.md`, `daily-screens/2026-10-30/` (25 files),
`daily-screens/2026-10-31/` (4), `daily-briefs/2026-10-30-post-market.md`,
`earnings/2026-10-27-reminders.md`, `earnings/2026-10-28-reminders.md`,
`options-flow/2026-10-30.md`, `us-eod/2026-10-30.{csv,md}`, `international-eod/2026-10-30/` (18).

One file is the reverse: `earnings/IMPROVEMENTS-cron19.md` exists on `master` and not on `main`.
This is **not** a stray staged deletion on `main` — `main` dropped it deliberately in `1094edc`
(2026-11-01 04:39, *"refs: point to cron #19 review docs in the migration repo; drop them from
the artifact sink"*), and `master` simply predates that decision. `master` also predates the
routine that produced it being the only consumer of that file.

**Fix.** Decide the branch policy. `master` is GitHub's default branch and cannot be changed
without Administration scope; a plain `git clone` therefore lands on a tree that is 25 commits
stale and 86 files short. Either fast-forward `master` to `main` (the divergence is a single
merge commit, so this is a one-line operation), or state plainly in the README that `main` is the
artifact branch and `master` is **not** a mirror — and stop calling it one. Two dated backup
branches (`backup/main-2026-10-30`, `backup/master-2026-10-30`) already exist, so a fast-forward is
reversible.

### 3.6 Seven orphan skill directories (C7, medium)

`cloud-prompts/skills/` holds 20 directories; **13 are referenced by a live prompt, 7 are not**
(113,325 B of dir bytes / 51,422 B of `SKILL.md`), six of them byte-identical to the Windows-era
capture in `skills-original/`.

**Fix.** Delete or move to an archive directory; keep the seven referenced ones.

### 3.7 Skill specs that still describe the pre-cloud Windows workflow (C8, medium)

**76 distinct path references across the prompts, skills and shared docs; 31 resolve, 45 do not.**
34 of the dead ones are Windows/local-path-shaped inside a Windows-era skill; 11 are other dead
references, including:

| Dead reference | Referenced from | Note |
|---|---|---|
| `scripts/screen.py` | `stock-screener-suite/SKILL.md`, `refs/tiering.md` | the tier thresholds `#09`'s output depends on are documented against a file that does not exist |
| `research/watchlist.yaml` | 5 live skills | absent from the workspace, the migration repo and the outputs repo — the watchlist pass is skipped by hard rule, so 5 skills document a data source that cannot exist |
| `cloud-prompts/_shared/preopen_feed.py` | `preopen-feed-plan.md` | the plan's own helper is not in the repo |
| `cloud-prompts/n8n/README.md`, `cloud-prompts/n8n/workflow-preopen-feed.json` | `preopen-feed-plan.md` | the `n8n/` directory does not exist at all |

**Fix.** Rewrite the 5 skills that read a watchlist to state the hard rule instead of the fiction;
delete the rest or mark them archival.

### 3.8 The migration map that outlived its mechanism (C11, medium)

`_classification.md` maps 26 *original local* crons. **4 of those 26 numbers no longer have a live
cloud routine**, and the file describes local Windows helpers and the Finviz MCP as if they were
the current mechanism.

**Fix.** Move to a clearly-labelled history file; it is not operative guidance.

### 3.9 Stale artifacts in the outputs repo (C14, C15, low/medium)

31 `SKIPPED_*.md` markers, plus trees no live routine writes (`refs/` holds a stale pre-cloud copy
of the runtime contract — `crons.md` has Windows paths, `fallbacks.md` makes blocked Finviz a
tier-2 source, `filters.md` uses unregistered `mcp__shibui-finance__*`).

**Fix.** Delete the 5 legacy `refs/` docs (superseded by `_shared/RUNTIME-CONTRACT.md`); keep the 3
current ones.

### 3.10 A completion check that produces false zeroes (owner ENV-7)

19 prompts mandate "Every artifact carries a `## Source health` section". A literal grep over the
outputs repo gives `options-flow 0/9` and `weekly 0/2` — yet `options-flow/2026-10-30.md` opens
with a `_source=cboe delayed-quote CDN option chains (8/8 underlyings, HTTP 200) · nasdaq public
quote API …` line and a "Read this first — data-quality caveat" section naming every degraded
source. **The information is disclosed; the heading is not.** The agents are disclosing more than
most routines that do match.

**Fix.** Say "disclose per-source health (a `## Source health` section **or** an equivalent
`_source=` line)" and make any audit match either form. A literal-heading check is measuring the
wrong thing.

---

## 4. Q4 — What would you change?

### 4.1 The cost, measured

| Measure | Value | Method |
|---|---:|---|
| Deployed fleet prompt text | **433,427 B** | sum of the 23 `prompt` fields from `cron_read view=list` |
| ≈ tokens per full fire-set | **108,356** | 4 chars/token |
| ≈ tokens per full fire-set, mixed model | **114,784** | 3.3 chars/token inside fences (29.8 % of bytes), 4.0 outside |
| Bytes loaded per calendar day | **1,692,595 B** | 39 fires/day weighted by each routine's cron expression |
| ≈ tokens per calendar day | **423,148** | 4 chars/token |

Independent owner-side measurement agrees: 431,791 B / ~107,947 tokens per fire-set, ~485 K
tokens/week of prompt loading at 5×/week for weekday routines.

### 4.2 The prioritised change list

Every "saved" figure is a **byte-comparison of the actual proposed replacement text against the
actual current block** — no target sizes estimated.

| id | change | target | tok/run | tok/fleet-day | quality effect | risk | effort |
|---|---|---|---:|---:|---|---|---|
| **D11** | Make the repo the single source of truth and deploy it byte-exactly with SHA-256 verification | repo + process | **0** | **0** | **HIGH** — the delayed-replay date rule, the corrected inventory and the 429→200 correction exist in the repo and are *not running* | push race while 21 prompts are rewritten | M |
| **D5** | Add a fleet-wide **source-precedence rule** | plaintext | −152 (cost) | −12,831 | **HIGH** — removes "which source wins?" ambiguity in 18 of 20 market-data routines | too rigid could suppress the right source | S |
| **D2** | `GIT PUSH` + `DELIVERY VERIFICATION` → `_shared/push_artifact.sh` + `_shared/verify_delivery.sh`, **push target as a parameter** | repo script + plaintext | **+918** | **+80,166** | **HIGH** — one place to fix the push; **fixes `#90`'s live `\| head -3` exit-status trap** and its wrong-branch target | script fetch failure; CDN stale window | M |
| **D3** | `WINDOW CHECK` → `_shared/window_check.sh`, flags as env vars | repo script + plaintext | **+353** | **+30,781** | **MED-HIGH** — ends the flag drift; makes holiday and hour gates first-class flags | script fetch failure | M |
| **D1** | Trim the in-prompt `RUNTIME DATA-SOURCE CONTRACT` to a **regenerated** summary | plaintext | **+255** | **+20,238** | **HIGH** — removes "Yahoo is 429" vs "Yahoo is 200 OK" from the same 19 prompts | over-trimming forces a contract fetch | S |
| **D10** | Trim `CRITICAL REMINDERS` to what is not already stated; one canonical reply format | plaintext | **+151** | **+10,942** | **MED** — fewer, sharper reminders; reply format stops drifting | a dropped reminder was load-bearing | S |
| **D7** | Delete `HELPER SCRIPTS (PYTHON)` from the 8 prompts whose skill references no helper; shorten in the other 10 | plaintext | **+156** | **+10,898** | **MED** — stops 8 prompts warning about Windows helpers they will never meet | a skill later adds a helper reference | S |
| **D4** | `MCP AVAILABILITY PROBE` prose → a pointer (the script is fetched and run anyway) | plaintext | **+43** | **+3,853** | **MED** — keeps fast-lane detection, drops the essay | none | S |
| **D8** | `AUDIT LOG` → delete | plaintext | **+58** | **+4,308** | **LOW-MED** — removes a Windows-only negative instruction | negligible | XS |
| **D9** | `ZERO-FALLBACK POLICY` → merge into `### Rules` | plaintext | −28 (cost) | −2,151 | **MED** — "write the artifact, then STOP" sits with the partial-data rule | negligible | XS |
| **D6** | `MCP TOOLS AVAILABLE` → one line naming the bridge first; `#12`/`#26`'s appendix moves into their skill | plaintext | −27 (cost) | −1,673 | **MED-HIGH** — stops 15 prompts listing `mcp__*` tools that do not exist | provenance listing wanted | XS |
| **D12** | **Date the artifact to the fire's *scheduled* date**, not the execution date | plaintext | −106 (cost) | −7,881 | **HIGH** — prevents a delayed replay publishing under the wrong date | needs `cron_read view=runs` | S |

**Net:** token-reducing proposals alone remove **150,467 B ≈ 37,616 tokens per fire-set (−34.7 %)** and
**614,047 B ≈ 153,511 tokens per fleet-day (−36.3 %)**. Three proposals deliberately *add* text
(D5, D12, D6: −24,066 B ≈ −6,017 tokens per fire-set), so the **net** reduction is
**130,579 B ≈ 32,644 tokens per fire-set (−30.1 %)** and **531,199 B ≈ 132,799 tokens per fleet-day
(−31.4 %)**. The fleet-fire falls to **302,848 B ≈ 75,712 tokens**.

### 4.3 The three proposals that buy quality, not just tokens

**D5 — a fleet-wide source-precedence rule.** 18 of 20 market-data routines have no rule for which
source wins when two disagree. The artifacts show the consequence: a routine concluded *"no
market-data source available … not fixable from inside the sandbox"* while the very same prompt
told it the source was reachable, and published a pre-market gap built on a stale tape that had to
be corrected a day later. A rule of the form *"the bridge's `market-recap` is the quote source of
record; Yahoo is a cross-check; when they disagree by >0.6 % prefer the bridge and say so"* removes
the guess.

**D12 — date the artifact to the scheduled fire, not the execution.** The quota wall (error 2067)
kills a session at its scheduled time and the platform re-dispatches the *same session* later.
Measured 2026-11-01: `#25`'s 2026-10-30 09:00 ET fire was re-dispatched and executed on **Sunday
2026-11-01 01:51 ET** — and the weekend guard fired on `DOW=7`, which would have **discarded a real
trading-day brief**. The repo already carries a 6,484-byte section for this; it is not deployed.
The proposed rule is 426 bytes:

```markdown
The `{date}` placeholder is the fire's **scheduled** date in US/Eastern, `YYYY-MM-DD`. Resolve it
from the run's `scheduled_at_ms` (`cron_read view=runs` → `run.scheduled_at_ms`), not from `date`
at execution time. If they differ, this is a **delayed replay**: rebuild for the scheduled date,
do NOT write a SKIPPED marker, and say in the artifact that it is a reconstruction produced late.
A replay is normal, not an error.
```

**D2 — one push implementation instead of 20 copies.** The push block is 3,190–3,255 B × 21 =
67,000 B, and its bash bodies differ in three lines. It has already produced a real bug class:
`git push … | head -3` returns **head's** exit status (always 0), so a rejected push reports
success. `#90` is the **only** place that trap still runs live
(`cron-prompts/90-delivery-auditor.md:482`) — and it pushes to `refs/heads/audit/status` while
building its worktree from `origin/main`, which is both the wrong branch and the reason its own
status push fails. The script must take `--branch` and `--add` as parameters, capture `$?`
directly, never `git add -A`, and re-fetch/rebuild/re-copy on a shared-fire-minute rejection.

### 4.4 The proposed scripts

`_shared/push_artifact.sh` — interface and the failure modes it must handle:

```bash
# usage: push_artifact.sh --dir <output-dir> --add <path> [--branch main] [--msg "<commit msg>"]
#   --dir    the routine's output directory relative to the repo root (e.g. daily-screens)
#   --add    the exact path to stage (default: --dir) — NEVER a wildcard
#   --branch target branch (default: main)
set -uo pipefail
# 1. token unset -> echo "push: skipped (token unset)"; exit 0
# 2. worktree from origin/<branch>, never from a local branch
# 3. stage ONLY --add; if `git status --short` shows any D, ABORT
# 4. commit
# 5. push; capture $? DIRECTLY (never `push ... | head -3`, which returns head's status)
# 6. on rejection: re-fetch, rebuild worktree from the NEW tip, re-copy, re-commit, retry (3x)
# 7. verify: git cat-file -e origin/<branch>:<path> -> "push: ok (verified)" else "push: FAILED"
```

`_shared/window_check.sh` — flags as environment variables, so the flag block stops being
copy-pasted prose:

```bash
# env: WEEKDAYS_ONLY, WEEKEND_ONLY, MARKET_HOURS_ONLY, DAY_OF_WEEK, HOLIDAYS
# resolves now in America/New_York, sets SKIP_REASON, exits 0 with the reason on stdout
# DAY_OF_WEEK: 0 = no constraint, 1=Mon .. 7=Sun
# HOLIDAYS: newline-separated YYYY-MM-DD list of market closure dates
```

**Honest trade-off on both scripts:** a run-time fetch can fail, and `raw.githubusercontent.com`
served a **stale blob for ~8 minutes** after a push on 2026-11-02 while the GitHub API and `git`
were instant. A run must therefore not silently execute yesterday's contract — the fetch should be
verified (or sourced from jsdelivr/the API), and a failed fetch must degrade to the prompt's
inlined fallback, not to "no data". Push these scripts hours before a fire, never inside the stale
window.

---

## 5. Implementation order

The dependencies are real; the order matters.

| # | Step | Depends on | Why |
|---|---|---|---|
| 1 | **Fix the repo content** — contract, README, skill specs, orphan skills, dead references | — | Nothing else can consume a wrong repo |
| 2 | **Land `_shared/push_artifact.sh`, `_shared/verify_delivery.sh`, `_shared/window_check.sh`** | 1 | The prompts must point at files that exist |
| 3 | **Land the shared contract as the single source**, regenerate README/ROSTER/roster.json | 1 | One truth, machine-generated |
| 4 | **Rewrite the 23 prompts** to point at the shared files, adopt D5/D12/D6, trim D1/D7/D8/D9/D10 | 2, 3 | The prompts are the only thing that is actually loaded |
| 5 | **Deploy byte-exactly, 3–4 per session**, SHA-256 the read-back against the repo blob, diff every task's fields before/after | 4 | This is the step that has been missing for 18 routines |
| 6 | **Resolve the `master` divergence** — decide the policy, then fast-forward or stop calling it a mirror | 1 | A plain clone must not land on a stale tree |
| 7 | **Delete the orphan skills and stale artifact trees** | 1 | Cleanup last, so nothing references them mid-migration |

Steps 1–4 are repo work and can proceed in parallel with step 6. Step 5 is the one that must not
be skipped or rushed: it is the difference between a fixed repo and a fixed fleet.

---

## 6. The highest-leverage single change

**Make the repo the single source of truth and deploy it byte-exactly, with SHA-256 verification.**

It costs zero tokens. It is not cosmetic: the delayed-replay date rule, the corrected connector
inventory, the 429→200 correction, the `market-recap` primary source and the `probe_mcp.py` fast
lane **all exist in the repo today and are not running on 21 of 23 routines**. Until the deployment
path exists, every other prompt edit is a local improvement to a file that no agent reads.

It is also the change that fixes the class of bug this audit found most often: a repo that is
correct and a fleet that is not is worse than a repo that is obviously wrong, because it looks done.

---

## 7. Per-routine matrix

Severity: **H** high · **M** medium · **L** low.

| Routine | Findings | Highest impact |
|---|---|---|
| **01** weekly MCP health check | B2, B4, C9, A1, A20, A14, A16 | probe manufactures a weekly false degradation for `shibui` |
| **02** asia pre-market reactions | B1, B5, C1, C2, C9, C10, A9, A13, A17 | stale contract deployed |
| **04** reversal bullish 3:55 | B5, C1, C2, C7, C8, A9, A21 | `## OUTPUT` names a path that is not a path |
| **05** EOD international | B5, C1, C2, C7, C8, A9, A18 | shares `eod-watchlist-snapshot` with #20 |
| **06** pattern-study backlog | B5, C1, C5, A6, A13, A17 | "Schedule is unchanged" is false (10:00 → 15:00) |
| **07** focus RVOL 09:45 | A1, A22, A14, C1, C2, A18 | **no `## CRITICAL REMINDERS` at all**; different reply schema |
| **08** pre-market gapper | B5, C1, C2, C9, C10, A9, A13, A17 | stale contract deployed |
| **09** daily sweep 18:30 | B5, C1, C2, C7, C8, C9, A9, A14 | `refs/tiering.md` cites a non-existent `scripts/screen.py` for its tier thresholds |
| **10** breadth snapshot | B5, C1, C2, C10, A9, A13, A17 | `MARKET_HOURS_ONLY` block shared with #12/#16/#17 |
| **12** cross-asset correlation | B1, B4, C1, C2, C10, A9 | the only routine whose `MCP TOOLS AVAILABLE` block omits the phantom tool |
| **13** macro calendar midweek | B1, B5, C1, C2, A6, A18 | names no cron expression |
| **14** macro calendar week-ahead | B1, B5, C1, A6, A17, A18 | first fire 2026-11-01 — verification deadline |
| **15** earnings reaction scanner | A1, A18, C1, C2 | bespoke; skill fetch is under a different heading |
| **16** unusual options flow | B1, C3, A3, C1, C2 | only weekday routine with `WEEKDAYS_ONLY=false`; hours gate is a near-miss |
| **17** us stocks in play | B1, B3, B11, B12, C1, C2 | **byte-identical to repo and still wrong internally** |
| **19** earnings reminder daily | A8, C1, C2, C8, C9, A17 | **the only routine with a real holiday guard** — the model to copy |
| **20** EOD watchlist CSV | B5, C1, C2, C7, C8, A18 | shares `eod-watchlist-snapshot` with #05 |
| **22** weekly market recap preview | B1, B5, C1, C2, C9, A18 | no `## RUNTIME DATA-SOURCE CONTRACT` |
| **23** agentic post-market brief | B5, C1, C2, C8, C9 | its skill reads a watchlist that cannot exist |
| **25** ntrt gap brief daily | B5, C1, C2, A17, C8 | the delayed-replay case that lost a Friday brief |
| **26** agentic pre-market brief | A2, A4, C3, C10, C1 | `## CRITICAL REMINDERS` points at a section that does not exist |
| **90** delivery auditor | A10, A11, A14, A22, A23, B5, C13 | **live `git push … \| head -3` trap** + wrong branch target |
| **91** schedule drift guard | B9, B10, A23 | chunk discovery can select the wrong file and abort detection |

---

## 8. Open questions and contradictions

1. **Yahoo's true status.** Two sessions on 2026-11-02 disagree (200 vs 429). This is almost
   certainly per-egress rate limiting, but it has not been confirmed against the platform's egress
   pool. Until it is, **no standing claim about Yahoo should be deployed in either direction**.
2. **`mcode-tools` availability.** Present in some sandbox images, absent in others. Whether the
   cron sandbox and the interactive sandbox share an image is not established.
3. **`master` vs `main`.** `master` is 25 commits stale and diverged by one merge commit. The
   single file it retains (`earnings/IMPROVEMENTS-cron19.md`) was dropped from `main` deliberately
   in `1094edc`. Whether to fast-forward `master` or to re-declare `main` as the artifact branch
   is the operator's call — the divergence itself is benign.
4. **Which is authoritative for the four skills that read `research/watchlist.yaml`?** The watchlist
   exists only on the Windows workstation and is not published. The skills currently document a
   source that cannot exist in the cloud runtime; whether the watchlist should be published or the
   skills rewritten is a product decision, not an editing one.
5. **The `#07` reply schema.** `#07` uses a six-line format with none of the README's five
   headings. Whether the README should adopt it or `#07` should adopt the README is a design
   choice; the current state — both present, neither marked canonical — is the defect.
6. **Whether the 7 orphan skill directories are worth archiving.** Six are byte-identical to the
   Windows capture and may be the only surviving record of the original procedures.

---

## 9. Deliberately excluded from the body

| Finding | Where it is carried | Why excluded from the body |
|---|---|---|
| B6 — `mcode-tools` absent in one sandbox image | §2.6 | carried as the weaker, correct version (probe-binary-absent is not a finding) rather than the track's original framing |
| B7 — Playwright/`uv` install notes | §2.8 | folded into B8; the actionable part is the helper that cannot run |
| B11 — phantom `sentiment` tool | §2.7 | one row of the endpoint table |
| B14 — nasdaqtrader 302 | §2.7 | one row of the endpoint table |
| C3 — the `#26` retirement tombstone | §4 | correctly marked; it is a 435-byte cleanup item, not a finding |
| C6 — RUNTIME-CONTRACT §2b retained history | §2.6 | partly load-bearing; the recommendation is to mark it, not delete it |
| C16 — smaller dead references | §3.7 | folded into the 45-reference table |
| A16 — tail variant count | §1 | folded into the structural summary |
| A19 — `SKIPPED_*.md` filenames containing a colon | §3.1 | folded into the marker discussion |
| A20 — `#01` missing from ROSTER.md | §3.4 | folded into the sources-of-truth finding |

---

## Appendix A — source index

**Repo:** `karizaco/maxhermes-migration` @ `24baf07`
- `cloud-prompts/cron-prompts/*.md` — 22 prompts (02, 04–10, 12–17, 19, 20, 22, 23, 25, 26, 90, 91)
- `cloud-prompts/01-weekly-mcp-health-check.md` — the 23rd routine
- `cloud-prompts/_shared/{RUNTIME-CONTRACT.md, mcp_bridge.py, probe_mcp.py, barchart_fetch.py}`
- `cloud-prompts/cron-prompts/{README.md, ROSTER.md, roster.json}`
- `cloud-prompts/_classification.md`, `cloud-prompts/preopen-feed-plan.md`
- `tools/{gen_index.py, gen_roster.py, schedule-drift.py, schedule-ground-truth.json}`

**Deployed prompts:** `cron_read view=list` (23 tasks), full JSON persisted at
`.mavis/tool-results/458676653531358/call_01a196fdb3f37774aef04a72/chunks/000000.txt` (466,798 B).
All deployed-vs-repo comparisons were made against that file, not the truncated preview.

**Outputs repo:** `karizaco/minimax-cloud-outputs` @ `b95d0ae` — read-only clone; 831 files on
`main`, 746 on `master`.

**Live measurements** (sandbox, 2026-11-02):

| Check | Result |
|---|---|
| `mcode-tools connector tools` | exit 0, `catalog_ok total=133 finance_tools=0` (root session) |
| `probe_mcp.py` | `catalog_ok total=133 finance_tools=0 \| bridge bridge_ok packs=tradier,fmp,market-recap` |
| Yahoo chart / screener / quoteSummary / options | **429** (root session, 6 spaced attempts, both hosts); **200** (track-b session) |
| Yahoo quoteSummary without crumb | 401 — the crumb is still required |
| Yahoo HTML page | 200 |
| Nasdaq quote API / market movers | 200 / 200 |
| SEC EDGAR full-text | 200 (with a UA) |
| TradingView scanner | 200, returns `premarket_volume`, `average_volume_30d_calc`, `market_cap_basic` |
| Stooq CSV | **200** with a JS proof-of-work challenge — not CSV |
| Frankfurter | `api.frankfurter.app` → **301** → `api.frankfurter.dev/v1/latest` (200) |
| CoinGecko / Treasury yield-curve CSV | 200 / 200 |
| `mcp_bridge.py --list-packs` | `tradier, fmp, market-recap` — **no `stocktwits`, no `shibui`** |
| `mcp_bridge.py stocktwits get_quotes` | identical payload to `market-recap get_quotes` (same `retrieved_at`) |
| `mcp_bridge.py shibui get_quotes` | `Unknown tool: 'get_quotes'` — shibui has no such tool |
| `mcp_bridge.py stocktwits chart_data` vs `shibui stock_data_query` | SPY 755.72 from both, different hosts — genuinely independent |
| `mcp_bridge.py some-random-pack-xyz` | `Unknown pack` — no silent fallback |
| `## Source health` in outputs | 79 of 309 artifacts; `options-flow` 0/9 but discloses via `_source=` frontmatter |

**Underlying track documents** (each independently cross-checked):
`audit/track-a-consistency.md` (23 findings) · `audit/track-b-factual.md` (14) ·
`audit/track-c-stale.md` (16) · `audit/track-d-efficiency.md` (12) ·
`audit/owner-independent-verification.md` (ENV-1…ENV-10).
