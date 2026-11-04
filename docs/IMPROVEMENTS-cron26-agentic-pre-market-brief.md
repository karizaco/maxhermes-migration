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
