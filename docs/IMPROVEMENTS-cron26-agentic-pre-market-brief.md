# Improvements — cron #26 agentic-pre-market-brief

Reviewed 2026-11-03, after the routine's own 08:30 ET fire on 2026-11-03. Evidence base: the
deployed cron task `457175063601252` and its 5 recorded runs, the deployed prompt (SHA-256
`47390eb657af16280a0bbb0f7047b3f01fb3981abd65d886fcde5529a3ebcff5`, byte-identical to
`cloud-prompts/cron-prompts/26-agentic-pre-market-brief.md`), the skill spec, the shared scripts in
`cloud-prompts/_shared/`, the live `karizaco/minimax-cloud-outputs` remote, and the 2026-11-03
artifact this review is based on.

Base for every revert: commit `1610c1627d`, tag `pre-cron26-r1-r5-2026-11-03`.

---

## 1. The brief never read cron #19's earnings roster, although the schedule was moved so it could — HIGH

The prompt's own SCHEDULE block said the fire was moved from 07:30 ET to 08:30 ET on 2026-10-31
"so the artifact lands after cron #19's 06:00 ET earnings reminder, **which it reads**". Nothing in
`SKILL.md` told it to read it. Step 8 said only: *"search-by-ticker for any watchlist name reporting
today + watchlist file says 'earnings flag'; otherwise a hardcoded mega-cap earnings list."*

Cron #19's own review already states the intent from the other side — `docs/IMPROVEMENTS-cron19-earnings-reminder.md`
item 5: *"This puts the artifact on disk before cron #26 reads it."* Both routines assumed the other
would make the connection. Neither did.

What #19 publishes at 06:00 ET, on the outputs repo, `earnings/{date}-reminders.md`:

- 43 names for 2026-11-03 — every S&P 500 constituent reporting plus every non-index mega-cap
  above $50B;
- per name: ticker, company, **BMO/AMC release time**, EPS estimate, revenue estimate, market cap;
- cross-checked against MarketBeat, the Nasdaq earnings calendar and the TradingView scanner;
- a `pending_count` / `already_reported_count` / `snapshot_et` front-matter block.

What the 2026-11-03 brief published instead, in §9: "243 companies report today — 103 before the
open, 140 after the close (EarningsWhispers)", then AMD, AMGN, ANET, BKNG, MPC, APO, BRK-B, DELL,
ADI, ADSK, ZS, HPQ, BBY, DKS as bare tickers with no estimates and no release times. It missed ~20
S&P 500 reporters #19 had (ETN, RACE, SU, ITUB, MPLX, WAT, AIG, YUM, PRU, ADM, SMCI, SWKS …), it
could not say which names were *already in the tape* (BMO) versus *still ahead* (AMC), and it
published a range — "79-122 reporters … depending on the calendar source" in the 2026-11-02 brief —
where a single counted source would do.

**Fix:** `SKILL.md` Step 8 now reads
`https://raw.githubusercontent.com/karizaco/minimax-cloud-outputs/main/earnings/{date}-reminders.md`
first, takes the roster, the BMO/AMC split and the per-name estimates from it, and splits §9 into
"already in the tape" and "still ahead". On a 404 it falls back to search and says so in Source
health. The prompt gained reminder 7.

## 2. The screen was re-invented every run, and the spec's own filter is wrong — HIGH

`SKILL.md` Step 2 specified:

```
filters=[change > 3%, typespecs has common, volume > 500000]
```

Three problems, all confirmed on the 2026-11-03 run:

- **`change` is the wrong column.** On the `america` scanner `change` is the **last completed
  regular session**; the live pre-market gap is `premarket_change`. The section the filter fed is
  titled "Pre-market gaps — top 25 market-wide". A run that follows the spec literally publishes
  yesterday's session under a pre-market heading, and the two look identical on the page.
- **`typespecs has common` drops ADRs and REITs.** The 2026-11-02 brief said so explicitly in its
  own universe line — *"all US-listed `type=stock` … (REITs and ADRs included — no common-stock
  re-filter, no domicile filter)"* — i.e. the last two runs had already deviated from the spec
  because the spec was wrong.
- **The good screen lived only in the previous artifact's prose.** "pre-market volume ≥100k shares,
  or market cap ≥$200M with ≥10k pre-market shares … Read the `%ADV` column: anything under ~5% is
  a thin tape, not a market" was in the 2026-11-02 markdown and in no specification. The next run
  has to rediscover it.

Neither screen has a quality floor, so both runs topped their "top movers" tables with sub-$1
microcaps on single-digit-million caps: RDAC +119.6% on an $18M cap, MERC +86.3% on $8M, HUBC
+39.0% on under $1M — and the scanner's `premarket_volume` for those names is simply wrong
(MERC reported 118.8M pre-market shares on a $0.23 stock).

**Fix:** `SKILL.md` Step 2 now carries the column contract as a table and the exact request body;
Step 2b pins the screen — Gate A liquidity (≥100k pre-market shares, or ≥$200M cap with ≥10k) and
Gate B quality floor (market cap ≥$100M) for the headline tables, with the Gate A-only names in a
separate "thin tape" block so nothing is hidden. Gate B applies to the screen-driven tables only:
§2's clusters are chosen by catalyst, so an event-driven name of any size belongs there with a
sourced catalyst. `type` is `in_range ["stock","dr"]`.

## 3. Two pulls of a live tape put two different numbers in one brief — HIGH

The 2026-11-03 run pulled the pre-market tape twice: a bulk screen at 08:42 ET and a per-ticker
fetch a few minutes later. The bulk screen fed the §3/§4 tables; the per-ticker fetch fed the §2
cluster tables and the prose. The same ticker therefore carried two different pre-market
percentages in different sections of the same file — AEHR +18.0% in the cluster table and +18.5%
in the table below it; RDAC +119.6% in a note and +118.0% in the table it described.

The artifact as first rendered was not wrong in isolation; it was **self-contradictory**, which is
the harder defect to spot and the easier one for a reader to catch.

**Fix:** `SKILL.md` states the rule — one pull per brief, the tables and the prose from the same
pull, the older pull wins if they disagree — and Step 9 adds a consistency check before rendering.
`SKILL.md` also gained a "One pull per brief" hard rule and a failure-mode row.

## 4. A delivered artifact was reported MISSING because `--add` overwrites — HIGH

`push_artifact.sh` takes **one** `--add` path, not a list:

```sh
--add)    ADD="${2:-}";   shift 2 ;;
```

The 2026-11-03 run passed the `.md` and then the `.csv`, so `ADD` ended up holding the CSV. The
script stages the whole output tree (both files landed), but it derives the commit subject's
routine number from `$ADD` via its path→NN table, and the CSV path is not in that table. The
commit subject came out as:

```
cron daily-briefs 2026-11-03
```

Cron #90's near-miss triage attributes a push to a routine by grepping commit subjects for
`cron (#)?NN `, so a **delivered** artifact was reported as MISSING. It was caught only by reading
the commit subject back after the push — `push: ok` says nothing about the subject.

**Fix, in two parts:**

- `push_artifact.sh` now collects every `--add` path and derives the routine number from the
  **first** path that matches its table, instead of from `$ADD` alone. A single-`--add` caller is
  unaffected — one path, same answer as before — so all 27 routines keep their current behaviour.
  `ART_DATE` is derived the same way, from the first path that carries a date.
- `verify_delivery.sh` gained an opt-in `--nn <NN>` check: it resolves the commit that last touched
  the path (GitHub API first, `git log` as fallback — the routine's clone is shallow and
  `git log -- <path>` has no history to walk there) and verifies the subject matches
  `cron (#)?NN `. Exit 4 = present but not attributable. Without `--nn` the script behaves exactly as
  before.
- The #26 prompt now passes `--add` once, with the `.md`, and explains why a second one is harmful.

Tested against a throwaway local bare repo: single `--add`, `--add` md→csv, `--add` csv→md,
an unknown path, and explicit `--nn` all produce the expected subject; the old behaviour is
unchanged for the unknown-path case.

## 5. The watchlist section has shipped empty every day, and the file has no home — MEDIUM

`research/watchlist.yaml` is a local Windows path. It does not exist in the Cloud sandbox, in the
migration repo, or in the outputs repo. Every artifact since 2026-10-14 has carried the same
"not published" line, and the brief has carried a permanent explanatory section — in the
2026-11-03 artifact, six lines of it, on a day when the tape was otherwise dense.

Cron #19 reached the same conclusion (`docs/IMPROVEMENTS-cron19-earnings-reminder.md` item 4) and
proposed the fix: *"publish a watchlist to the outputs repo and fetch it at run time —
`https://raw.githubusercontent.com/karizaco/minimax-cloud-outputs/main/refs/watchlist.yaml`"* or
*"drop the step and the section entirely rather than carrying an empty table every day."* It was
never implemented, and the path it proposed does not exist yet (HTTP 404).

**Fix:** both routines now use one convention, the one #19 proposed.

- `SKILL.md` Step 7 fetches `refs/watchlist.yaml` on the outputs repo. Present → publish the
  section. Absent → **omit the section entirely**, say so once in Source health, and do not create
  a default watchlist with invented tickers.
- `research/watchlist.README.md` and `research/watchlist.example.yaml` (new) document the schema,
  the publish step and the rules. The example file is deliberately not named `watchlist.yaml` and
  is not published: a file with no real tickers would make the routine publish an empty section
  every morning.
- The user's actual tickers are not in this repo and were not invented. Publishing them is one
  file, one commit, and the section lights up on the next fire.

## 6. Smaller items, fixed in the same pass

- **A dangling reference.** The prompt said *"see WEEKEND MODE below"* — there is no WEEKEND MODE
  section; it was retired on 2026-10-31. The reference is removed and the retirement is stated
  inline.
- **A wrong path in the holiday skip reply.** It said `daily-briefs/$DATE.md`; the artifact is
  `daily-briefs/$DATE-pre-market.md`.
- **A misleading schedule history.** The prompt said the original was 07:37 ET and implied the
  Cloud deployment matched it; the run history shows 07:30 ET for 2026-10-28 → 2026-10-30. All
  three times are now distinguished.
- **The CSV is now deterministic.** The skill says the CSV ships alongside the markdown; the
  prompt's OUTPUT block says so explicitly, with its columns.
- **A silent delivery gap is still possible.** 2026-10-30 (Friday) has a post-market brief on the
  branch and no pre-market brief, although the platform recorded that fire as `status: 1`. The
  prompt's delivery verification now also confirms presence by API, because the script's own check
  reads a remote-tracking ref that can be stale after a race with a sibling routine in the same
  minute — cron #08 shares this fire minute with #26.

## Files changed

| File | Change |
|---|---|
| `cloud-prompts/skills/agentic-pre-market-brief/SKILL.md` | the column contract, the pinned screen, the #19 roster, the watchlist rule, the one-pull rule, the tool mapping, the CSV |
| `cloud-prompts/cron-prompts/26-agentic-pre-market-brief.md` | push guidance, delivery verification with `--nn`, the API backstop, reminders 6-8, the hygiene fixes |
| `cloud-prompts/_shared/verify_delivery.sh` | opt-in `--nn` subject check (additive) |
| `cloud-prompts/_shared/push_artifact.sh` | routine number derived from the first matching `--add` path (behaviour-identical for single-path callers) |
| `research/watchlist.README.md` | new — the watchlist contract and how to publish it |
| `research/watchlist.example.yaml` | new — the schema |

## Revert

```bash
git -C <repo> fetch origin main
git -C <repo> revert <commit>            # or reset --hard pre-cron26-r1-r5-2026-11-03
git -C <repo> push origin HEAD:main
```

The deployed prompt is reverted by `cron_update` with the original bytes and
`schedule` + `timezone` resent; the original file is kept at
`/workspace/rollback/2026-11-03-cron26-r1-r5/26-agentic-pre-market-brief.md` with its SHA-256.

---

# Round 2 — 2026-11-04 (the further improvements)

Base for this round: `546fc5f` (round 1). Revert point: the tag on this commit.

**A note on who did what.** While this round was being built, another agent landed a parallel
change to the SAME territory: a replay-aware `window_check.sh` (V2) and its own offline test
suite, with the window-check block already migrated in 20 prompts. That work is better than what
this round had drafted — it judges the gate against the FIRE's scheduled instant rather than the
wall clock, so a resumed replay is not mistaken for a different day — so **this round was rebuilt
on top of it rather than over it.** What follows is what is genuinely new here.

## 1. The holiday calendar was wrong in every copy (the one thing the parallel work did not fix)

The V2 script's `HOLIDAYS_DEFAULT` and the auditor's inline copy both carried the same ten dates,
with two live defects:

- **Good Friday (2026-04-03) was listed.** The NYSE is **OPEN** on Good Friday — it closes most
  European and Asian exchanges, which is where the bad copy came from. The fleet skipped a live
  session.
- **The list stopped at 2026.** On **2027-01-01**, a Friday, every weekday routine would have
  fired and published for a closed market.

**Fix:** the list is now the 2026-2028 NYSE closures — Good Friday excluded, Saturday holidays
not observed on the preceding Friday, half-days recorded separately as trading days — in
`cloud-prompts/_shared/nyse-holidays.txt`, in `window_check.sh`'s default, and in the auditor's
copy. `window_check.sh` also gained `--holidays-file`, so a caller can read the canonical file
instead of passing dates inline.

The parallel work's own test suite (`window_check_test.sh`) now passes 17/17 against the
corrected calendar, including its parity check between the script and the auditor's copy. It
caught a real defect in the first attempt at this fix: the auditor's list had been re-wrapped on
a fixed character count, which split a date across two lines and dropped three closures from the
comparison. The list now wraps on date boundaries.

## 2. The rules were stated but nothing enforced them

`tools/check_brief_consistency.py` checks the brief against its own CSV: table rows vs the CSV,
prose percentages vs the pre-market OR the prior-session column, section presence and order, and
unfinished placeholders. It is header-driven, so it reads all three table shapes correctly.

**It immediately found a real inconsistency in the artifact that shipped on 2026-11-03:** the CSV
had taken a later per-ticker fetch for some names while the markdown took the earlier bulk screen
(AEHR read +18.5% in a table and +18.8% in the CSV), and NVDA and NOK were missing from the CSV
altogether. The CSV was regenerated from the same merged table the markdown uses. Five break
classes are tested: prose %, table price, table %, missing section, placeholder — all five caught.

## 3. The shared scripts had no lint at all

Every routine executes `cloud-prompts/_shared/*.sh` on every fire, so a syntax error in one is all
27 routines, not one. `tools/schedule-drift.py` — which cron #91 runs at 04:05 ET, before the
weekday routines — now lints them: `sh -n` on every shared and tools script, `py_compile` on every
helper, and a smoke test that `verify_delivery.sh` and `push_artifact.sh` execute and refuse a
bogus argument. It also asserts that the three copies of the holiday list agree, so the defect
above cannot come back. **Because #91 fetches that script at run time, this needs no deployment.**

## 4. The brief ignored two sibling artifacts that had already computed what it re-derived

`earnings/{date}-reactions.md` (cron #15) fires at **08:00 ET**, half an hour before #26, and
already carries the pre-market gap table with a `last earnings` tag and `PRE_GAP`/`POST_GAP`
flags, cross-checked against Yahoo. `daily-screens/{date}/breadth-snapshot.md` (cron #10) carries
the breadth context. Step 3b of the skill spec now reads both, uses #15 to cross-check and
enrich the clusters, and says explicitly not to replace the broader screen with #15's narrower one.

## 5. The artifact had no machine-readable header

Cron #19 and #15 both publish YAML front matter; #26 published prose only. The spec now requires
it: `date`, `cron`, `fire_time_et`, `snapshot_et`, `source`, `status`, `themes`, and the up/down
counts — so "was this a replay" and "was the tape fresh" are machine-checkable.

## 6. The brief's tape was 50 minutes stale by the open

#26 fires at 08:30 ET; the open is 09:30. Cron #92 already runs its catalyst tape at 08:30, 09:20
and 09:50. New routine **#26b** fires at **09:20 ET** and publishes a short addendum — a
refreshed top-of-book and what moved since the morning brief — with no news searching, no
clustering and no rewriting. Its procedure is the shared file
`cloud-prompts/_shared/premarket-refresh.md`.

## 7. docs/ had no index

`tools/gen_docs_index.py` generates `docs/README.md` from the files on disk, the way
`tools/gen_index.py` generates the prompt roster.

## What was deliberately NOT done

- **A wall-clock holiday guard in the skill specs.** The first draft of this round injected one
  into all 15 skill specs, on the reasoning that skill specs are fetched at run time and so a
  fleet-wide fix needs no deployment. It was **removed**: the parallel V2 work judges the gate
  against the FIRE's scheduled instant, and a wall-clock guard would fire on the wrong day during
  a resumed replay — reintroducing exactly the bug V2 exists to prevent. Two holiday gates that
  can disagree are worse than one.
- **Migrating the remaining prompts.** The parallel work already migrated 20 of 28. The rest are
  #90 (the auditor, which needs the list for CLASSIFICATION rather than skipping) and #01/#91,
  which publish no market artifact.

---

# Round 2 — 2026-11-06: the brief gets a decision, levels, and a loop

Evidence base: the 2026-11-03 artifact (`daily-briefs/2026-11-03-pre-market.md`, 43,999 B, 1,491
CSV rows) and the 2026-11-04 artifact, the deployed cron task `457175063601252` (prompt
SHA-256 `3b530c820b467d2cda81f32a8b82c391f354dccb524f2e8fa3746b25580367ea`, 19,446 B, byte-identical
to `cloud-prompts/cron-prompts/26-agentic-pre-market-brief.md` after this round), and the live
`karizaco/minimax-cloud-outputs` remote.

The round-1 review (above) fixed how the brief is BUILT. This round fixes what a reader can DO
with it: the 2026-11-03 brief was the largest artifact the fleet produces and it still could not
be acted on.

## 8. The TL;DR was a map of the brief, not a decision — HIGH

`## 1. TL;DR — six themes, clustered` is good analysis and it is a *map*: it tells the reader what
the brief contains, and leaves the synthesis — which setup, which risk, which level — to them. The
ntrt routine (#25) already pins the answer: **exactly three bullets**. The pre-market brief did not.

**Fix:** `## ARTIFACT FORMAT CONTRACT v2` §C1 adds a `## Bottom line` block ABOVE §1 — exactly three
lines, the literal labels `The one setup` / `The one risk` / `The one thing to watch`, in that order,
and line 1 must carry a level AND its invalidation (a digit and the word `invalidat*`). The
six-cluster clustering is untouched: §1–§11 keep their numbers and their method.

## 9. Every setup was published without a price — HIGH

The brief names setups all day — Oracle's $20B AI capex template, the Marvell/Lumentum $115B
all-stock deal with a wide spread, "AMD is the referee tonight" — and publishes **no level for any
of them**. "AMD is the referee tonight" is untradeable without knowing where the decision is.

**Fix:** §C2. Every name in the theme clusters, the gaps table and the losers table now carries
`Prior close`, `Pre-market last`, `Gap %`, `PM range`, `Key level` and `Invalidation`, with a
**deterministic ladder** so the level is never a judgement call: a level published by the sourced
catalyst wins (a deal's implied value, an offering price), otherwise the prior close — the
gap-fill level, which is the level that answers "does the gap hold". The invalidation is a
downside trigger for a gap-up (a trade back to/below the prior close) and the pre-market low for a
gap-down, and every cell must contain a digit.

The pre-market **range** needed a source that was not in the spec: the `america` scanner does
carry `premarket_high` / `premarket_low` (verified live 2026-11-06: AAPL `premarket_low` 349.79 /
`premarket_high` 355.35 against a `close` of 344.17), plus `high`/`low` for the prior session's
extremes. The scanner's column list and the spec's column contract now say so.

## 10. The CSV contradicted its own spec, and carried columns named after a date — HIGH

The spec promised `prev_close,prev_change_pct`; the 2026-11-03 CSV shipped neither. It shipped
`nov_2_2026_close` and `nov_2_change_pct` — **date-named columns** — and the 2026-11-04 CSV then
carried `nov_2_change_pct` while it actually held the *Nov 3* move. A date-named column is a lie
waiting for the next session. The 2026-11-04 CSV also shipped `3.06406685236769` for a gap of 3.06%.

**Fix:** §C3 pins a 21-column, date-independent header
(`premarket_last,premarket_high,premarket_low,prior_close,gap_pct,prior_session_change_pct,…`) and
forbids a date in a column name; §C4 makes the routine **assert the header against the spec
before the push**, and `tools/check_premarket_brief.py` fails an artifact whose header is missing a
promised column, carries an unpromised one, or carries a date-named one.

The CSV also gained `setup_published` and `setup_theme` — the columns that make §11 possible.

## 11. The push subject lost the routine number, and the helper could be stale — HIGH

The 2026-11-03 CSV was pushed with the subject `cron daily-briefs 2026-11-03` — **no routine
number** — which is exactly what cron #90's triage greps for, so a delivered artifact was reported
as MISSING. The path→number table in `push_artifact.sh` now has a row for BOTH
`daily-briefs/*-pre-market.md` and `daily-briefs/*-pre-market.csv` (verified: the live commits read
`cron 26 agentic-pre-market-brief 2026-11-03` and `… 2026-11-04`).

The prompt's fetch block was `[ -s push_artifact.sh ] || curl …` over raw + jsDelivr. That guard
means the **fallback was dead code** — the first successful download satisfied it — so a stale local
copy of the helper kept using the old path→number table. Measured 2026-11-04: raw.githubusercontent
served a stale blob for >17 minutes after a push while jsDelivr was fresh.

**Fix:** the deployed prompt now uses the fleet's contents-API-first ladder, **refreshes the helper
on every run**, and rejects a response whose *body* is a 404 JSON. The same ladder is now written
into the skill spec, so it applies to every shared helper the routine fetches.

## 12. The brief had no follow-up — HIGH

The last section was `## 11. Open research queue`, and nothing anywhere recorded what happened to
yesterday's calls. A brief that cannot be scored is a brief nobody can trust, and the routine never
learns.

**Fix:** §C5 adds `## Yesterday's brief — what happened`, on EVERY run, directly under the Bottom
line, with the table the fleet already knows how to read:

```
| Name | Setup (yesterday) | Yesterday's close | Today's move | Thesis held? |
```

`tools/yesterday_review.py` builds it from real data: the reviewed brief (the most recent prior
DAILY brief — the 2026-11-05 fire published nothing on a quota wall, so the 2026-11-06 run reviews
the 2026-11-04 brief and SAYS so), its CSV's `setup_published` rows, the MCP bridge's
`market-recap price_history` for the closes and moves, the Yahoo chart API for the intraday extremes
that a "traded through the level" test needs, and the previous evening's post-market brief (cron
#23) as the cross-check on the closes.

The verdict is a TEST, not a re-judgement: `BROKE` = the invalidation level the reviewed brief
published was traded through; `HELD` = it held and the session moved with the setup; `PARTIAL` = it
held but the session moved against it; `UNJUDGED` = no level or no price, with the reason.

**Measured on the real 2026-11-04 brief (46 setups, session 2026-11-05):** AMD −17.26%, TBLA
−20.80%, NVDA −9.26%; NVDA `BROKE` (the 206.69 invalidation was traded through), FSLR / NXT / PLUG
/ ENPH / SEDG `BROKE`, ARRY / HL / SCZM / MUX / EXK `PARTIAL`, and the closes agreed with the
2026-11-05 post-market brief. The 2026-11-04 brief predates the invalidation column, so its rows
say the level was **derived** from that brief's own published prior close — derived, never faked.

## 13. The gate, and what it caught

`tools/check_premarket_brief.py` is the contract gate (6 clauses: C0 marker, C1 Bottom line, C2
levels, C3 CSV header + rows, C5 yesterday section). `tools/test_premarket_brief_contract.py`
proves the contract is SATISFIABLE (a synthetic compliant artifact passes) and that the checker
**bites** — 16 mutations, one per clause, all caught:

the Bottom line deleted · two lines instead of three · wrong labels · the block moved below §1 ·
the setup line with no level and no invalidation · a level column missing from the cluster table ·
an empty invalidation · a gap that disagrees with the CSV · a published name that is not in the CSV ·
a promised CSV column missing · a date-named CSV column · a setup row with an empty key_level · the
yesterday section deleted · no `Thesis held?` column · a verdict outside the vocabulary · the
contract marker missing.

`tools/check_brief_consistency.py` (the older linter: prose ≡ tables ≡ CSV) now reads the v2 column
names with LEGACY fallbacks, matches sections by HEADING rather than by a bare substring (the new
Bottom line block talks about `## 1. TL;DR`, and a substring search would have read that mention as
the section), and still passes on the legacy 2026-11-03 artifact.

## Files changed

- `cloud-prompts/skills/agentic-pre-market-brief/SKILL.md` — ARTIFACT FORMAT CONTRACT v2 (§C1–§C5),
  the scanner column contract, the fetch-ladder rule, the failure-mode table.
- `tools/check_premarket_brief.py` — NEW, the gate.
- `tools/test_premarket_brief_contract.py` — NEW, 16 mutations.
- `tools/yesterday_review.py` — NEW, the loop builder.
- `tools/check_brief_consistency.py` — v2 columns with legacy fallbacks; heading-anchored sections.
- `cloud-prompts/cron-prompts/26-agentic-pre-market-brief.md` — the push fetch ladder, the two
  checkers, two new CRITICAL REMINDERS. Deployed byte-exactly (19,446 B, SHA-256 `3b530c82…`);
  schedule `30 8 * * 1-5`, timezone `America/New_York`, model and session binding preserved.

## Revert

`git revert f4b5ca8` (or `git revert --no-commit f4b5ca8` to keep the prompt), and re-deploy the
previous prompt blob — the pre-round prompt was SHA-256
`e681545e9502e5c646b990fb41b9a43c9ebf108038b8225eda82f0550f88786d`, 16,334 B.

## 2026-11-06 — The delayed-replay path: what a replayed fire can and cannot re-pull

**Context.** Cron #26's 2026-11-05 08:30 ET fire failed on the platform (Token Plan quota 2056)
and published nothing. The platform resumed that conversation IN PLACE on 2026-11-06 05:22 ET —
21 hours later — so the window check reported `fire-date: 2026-11-05 / replay: yes`. The brief was
rebuilt for 2026-11-05 and pushed as `daily-briefs/2026-11-05-pre-market.{md,csv}`
(57,490 B + 94,047 B, commit `73d1c5aa5`, subject `cron 26 agentic-pre-market-brief 2026-11-05`).

**The trap.** A replay's live screen is the REPLAY day's screen. The TradingView scanner's
`premarket_*` columns are now the 2026-11-06 pre-market; pulling them would have published
another day's gaps under the fire's date. And `close`/`change` are Nov 5's settled session, which
is not what a Nov 5 08:30 brief needs either (it needs Nov 4's tape). **A replay must never
re-pull the live scanner for the screen.**

**What a replay uses instead — every source is a dated fleet artifact:**

| Field | Source for a replayed fire |
|---|---|
| pre-market last, gap %, name | `preopen-feed/{fire-date}-0830.jsonl` (cron #92a checkpoint: 700 rows of ts/src/ticker/name/pct/price/cat/why/ref/conf, pull 2026-11-05 10:10:24 ET) |
| pre-market volume, %ADV, market cap, sector | `daily-briefs/{fire-date}-pre-market-refresh.md` (cron #26b — the SAME pull, published with its liquidity columns for 86 names) |
| pre-market high/low (PM range) | Yahoo chart bars for the fire date, `includePrePost=true` |
| prior close, prior session % | `us-eod/{fire-date-1}.csv` (cron #20, settled) |
| earnings roster | `earnings/{fire-date}-reactions.md` (cron #15) when cron #19's file is absent |
| macro | `macro-calendar/{week}-midweek.md` |
| overnight levels | Yahoo chart bars for the fire date, last bar ≤ 08:30 ET on the fire date |

**Yahoo carries ZERO pre-market volume.** Every pre/post bar's `volume` is 0 for every symbol
tested (APP, AEHL, LABT on 2026-11-05), so Yahoo can supply the pre-market RANGE and the last
print but never the pre-market volume: `%ADV` and Gate A can only come from the TradingView screen.
Yahoo's pre-market last print also differs from TV's by a few cents (APP 349.58 vs 350.00) — pick
ONE source per field and say which in Source health.

**Gate A is only as good as the PUBLISHED volume.** On 2026-11-05 the fleet published a pre-market
volume for 86 names. Gate A has two published proofs: TV's own volume, or cron #15's 10,000-share
pre-market floor combined with a ≥ $200M market cap (the skill's OR-branch). Names that clear the
cap but have no published volume are UNVERIFIABLE, not pass. The 2026-11-05 brief published them
in a labelled "cleared the cap, but no published pre-market volume" block rather than promoting
them into the headline table or hiding them — which is also why the headline table carried 23
names and not 25: WW +19.46%, ACHC +16.25% and EWTX +14.58% gapped bigger than names in the table
and are still published, one block above it.

**Market cap has a basis and the two files disagree.** The screen publishes `market_cap_basic` on
the PRIOR close's basis (it was pulled before the close); `us-eod/{date}.csv` is on that date's
CLOSE basis. A pre-market brief must use the prior-session file, or the cap column mixes two
bases. MELI is absent from cron #20's settled file for both Nov 4 and Nov 5, so its cap is
published as not available rather than guessed.

**Three things a replay cannot have, and what to do instead.**
1. *The StockTwits trending list* — the feed publishes no history, and the `mcp__stocktwits__*`
   tools were unreachable in Cloud sessions on Nov 5 (cron #15's own source health says so). The
   replay published the substitute lead read — the ten names whose catalyst the checkpoint
   captured — and said the trending list was not recoverable.
2. *Cron #19's roster* — `earnings/2026-11-05-reminders.md` does not exist (the last file is
   2026-11-04), so §9 fell back to cron #15's reactions file and published no count it could not
   source.
3. *The watchlist* — `refs/watchlist.yaml` was seeded 2026-11-06, AFTER the fire, so the brief said
   the list did not exist on 2026-11-05 and priced the current list against the Nov 5 tape.

**The yesterday loop still works without levels.** The 2026-11-04 brief published no key level for
any of its 105 named calls, so the review tested GAP SURVIVAL instead: HELD if the close finished
on the far side of the prior close, BROKE if it closed back through it, PARTIAL within 0.5%,
UNJUDGED where cron #20's settled file has no row. That is the vocabulary `check_premarket_brief.py`
C5 accepts, and it needs no published level to run.

**Files changed**

- `cloud-prompts/skills/agentic-pre-market-brief/SKILL.md` — new `## DELAYED REPLAY` section: the
  replay path, the "never re-pull the live scanner" rule, and the per-field source table above.
- `docs/IMPROVEMENTS-cron26-agentic-pre-market-brief.md` — this section.

**Revert**

`git revert <the commit below>`.

---

# Round 3 — 2026-11-06, 14:30 UTC: the audit of the first v2 artifact, and the side it found

The 2026-11-06 08:30 ET fire was the first to run under ARTIFACT FORMAT CONTRACT v2. This round
audits that artifact and fixes the one real weakness it exposed.

## 14. The audit result — the contract holds

`daily-briefs/2026-11-06-pre-market.md` (50,273 B) + `.csv` (117,111 B, 696 rows) published at
13:45:02 UTC with the subject **`cron 26 agentic-pre-market-brief 2026-11-06`** — the routine
number is in the subject, as the contract requires.

Both gates, run against the REMOTE bytes (fetched through the contents API, not raw):

- `tools/check_premarket_brief.py` → **CONTRACT OK, 6/6 clauses** (C0 marker, C1 Bottom line,
  C2 levels on 90 published names, C3 the 21-column header + every row, C5 the yesterday section).
- `tools/check_brief_consistency.py` → **consistent** (113 table rows, 25 prose ticks, 696 CSV
  names).

The four promises, present in the published artifact: `## Bottom line` at line 15 with exactly
three lines (NVDA 189.55 / invalidation 181.60; the payrolls risk; IREN 20.89), `## Yesterday's
brief` at line 21, `## 1. TL;DR` at line 140; the level columns on every theme/gaps/losers row;
the CSV header exactly the 21 pinned columns; and a `Thesis held?` column with 112 scored rows
(67 HELD, 41 BROKE, 2 PARTIAL, 2 UNJUDGED).

The section's numbers were checked against a FRESH pull of the MCP bridge, not against the
artifact's own numbers: AMD 404.40 / −17.26%, ALNT 75.48 / −5.13%, ADMA 13.21 / +26.05%, NVDA
181.60 / −9.26% — all four agree to the cent.

## 15. The two briefs used DIFFERENT ladders — and the invalidation cell carried no side — HIGH

The 2026-11-05 brief (published 10:52 UTC today — the delayed replay of that day's fire, rebuilt
under v2) published, for AMD, `key_level = 450.1` (the pre-market low) and `invalidation = 478.69`
(the pre-market high) — **a bare number**. The 2026-11-06 brief published, for ASTS,
`key_level = 30.20` (the prior close) and `invalidation = below PM low 29.14` — **a phrase with
its side**.

Two briefs, two ladders, and in the Nov 5 brief the invalidation's SIDE is not stated anywhere in
the CSV: a bare `478.69` does not say which side of the level breaks the thesis. The review is a
mechanical test on that cell, so it has to infer the side — and an inference is right for one
convention and silently wrong for the other. Auditing the 113 classifiable rows of the Nov 5
brief: 62 took the pre-market HIGH as the invalidation on a gap-down name, 47 the pre-market LOW
on a gap-up name, 1 neither.

**Fix (three parts):**

1. **The spec pins ONE ladder** — the one the live routine actually shipped on 2026-11-06:
   `key_level` = the prior close (the gap-fill level); `invalidation` = always a DOWNSIDE trigger
   (`back to/below prior close X` for a gap-up, `below PM low Y` for a gap-down), because the setup
   the brief publishes is a long in both cases — buy the gap, or buy the flush.
2. **The invalidation cell must carry its side** — `back to/below prior close 404.40`, not
   `404.40`. The checker now fails a setup row whose invalidation has a level but no side word
   (`above`/`below`/`under`/`over`, or an `event`/`if` clause), and the contract test grew a 17th
   mutation for it. The 2026-11-06 artifact already passes this clause; the 2026-11-05 brief
   (bare numbers, published before the requirement) fails it, which is the correct outcome for a
   gate that is forward-looking.
3. **A wording slip must not cost the day's brief.** The checker is a hard gate before the push,
   so a missing side word would otherwise mean NO artifact. §C4 now says: repair the cell
   (`below`/`above` per the ladder), re-run the checker, push — do not abandon the artifact over a
   missing word.

The helper's legacy path (a reviewed brief whose cell has no side) keeps the gap-sign inference
that produced the 2026-11-06 artifact, and now says so in the row: *"the reviewed brief published
the level without its side, so the side was assumed from the gap's sign."* Re-running the helper
against the 2026-11-05 brief now reproduces **111 of 112** of the published verdicts; the one
difference (NWGL) is the run's own override, where it marked the name UNJUDGED because the
reviewed level did not reconcile with the scanner's price — the run being more careful than the
helper.

## 16. A partial, still-trading session bar leaked into the review — HIGH

The helper crashed with `KeyError: '2026-11-06'` on the 2026-11-06 run. Cause: Yahoo's chart had
already published a bar for the CURRENT session, and the helper took "the most recent bar
anywhere" as the last completed session — but the review runs pre-market, so the current session
is not a settled close. The helper now drops every bar dated on or after the review's own date
(the last COMPLETED regular session is the last one before it) and looks up the session bar
defensively.

## Files changed (round 3)

- `cloud-prompts/skills/agentic-pre-market-brief/SKILL.md` — §C2 pins the ladder and requires the
  side in the cell; §C3 says the CSV's invalidation carries the side; §C4 adds the repair path; §C5
  says where the trigger side comes from.
- `tools/check_premarket_brief.py` — a setup row's invalidation must carry a side word (or an
  event clause) as well as a level.
- `tools/yesterday_review.py` — the in-progress session bar is dropped; the legacy side inference
  says it is assumed.
- `tools/test_premarket_brief_contract.py` — the synthetic artifact follows the shipped ladder and
  carries the sides; a 17th mutation (a level with no side).

The contract is fetched at RUN time, so these land on the next fire (Monday 2026-11-09 08:30 ET)
with **no `cron_update`** and no prompt drift.
