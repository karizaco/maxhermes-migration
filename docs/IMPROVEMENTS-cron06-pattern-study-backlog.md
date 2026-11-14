# Improvements — cron #06 `stock-screener-pattern-study-backlog`

Date: 2026-11-09. Scope: the weekly refresh screens (IPO / high short float / 1000%-in-10-years)
as a *system* — what the routine publishes, how the numbers are derived, and how a future run
knows whether it complied.

Evidence base: the 2026-11-07 fire (Saturday 15:00 ET, data date 2026-11-06) and the artifacts
it published, re-rendered under the contract below. Four other routines' contracts were read
for the pattern (`tools/check_bonde_artifact.py`, `tools/check_premarket_brief.py`,
`tools/check_auditor_contract.py` and their fault-injection tests).

## 1. The finding: three correct lists, and the join between them was never published

The 2026-11-07 run produced three mechanically correct screens and a document that was close to
useless for a reader. Each screen published the **head of its own ranking**, so the names that
mattered — the ones in two universes at once — never appeared:

| Set | Size | Where it was published |
|---|---|---|
| 1000%-in-10-years compounders AND >20% short float | 12 | nowhere — all 12 sat at ranks **57-335** of the 374-name short-float book |
| sub-2-year IPOs AND >20% short float | 5 | nowhere |
| >20% short float AND already in the daily sweep's Master | 58 | nowhere (4 of them were Tier-A: ACHC, FUN, RUN, SEZL) |
| the short-float book's own top 30 | 30 | the whole published table |

The 30 names that were enriched (liquidity, close, 30-day change) were ranks 1-40 of the
short-float book — i.e. the enrichment budget was spent on a ranking that has nothing to do with
the interesting names. The join was computable **from data the run already held**, and it was
the product.

Two more defects surfaced while reading the same artifacts:

* **The IPO week-over-week note was false.** The 2026-10-31 run published its top 50 of a
  larger passing set, so diffing this week's list against that published table produced a
  "3 entered / 9 left" story that was mostly an artifact of the prior display cap. Recomputing
  the prior week with the SAME query (86 names) gave the real diff.
* **"Left the top 30" and "left the universe" were conflated.** `ownership_stats` is a current
  snapshot with no `date` column, so names lose their row between runs — OWLS (443.9% last
  week) simply vanished, while LENZ was re-stamped down to 47.6% and is still above the gate.

## 2. What changed

### 2.1 The engine: `_shared/cron06_refresh.py` (marker `CRON06_REFRESH_V1`)

A routine-specific engine, fetched at RUN time by the routine's own skill block — the same
pattern as cron #16's `relvol_screen.py`. It is not a fleet-wide helper because most routines
never call it.

The engine owns **every number and the rendering of the artifacts**. The Agent fetches the
three shibui screens and passes the raw rows in as JSON; it does not transcribe a price into
markdown. A hand-typed price is a defect, not a style choice.

What it computes:

* **the intersections** across the three universes, published in every artifact;
* **the enrichment follows the intersection** — every name in any intersection is enriched
  (30-bar average dollar volume, close, close 30 bars ago, market cap), plus the top 40 by
  short float and every IPO name;
* **`tradeable_verdict`** — a closed set: `TRADEABLE` (30d ADVol >= $20M) / `THIN` ($5-20M) /
  `ILLIQUID` (< $5M) / `FLOAT_ARTIFACT` (short % of float > 100) / `NO_QUOTE`. Precedence
  FLOAT_ARTIFACT > NO_QUOTE > ILLIQUID > THIN > TRADEABLE. A verdict is a FIELD, never a
  sentence — the previous artifact carried the same information in a prose bullet;
* **`squeeze_candidate`** — `YES` only when short > 50% AND the verdict is `TRADEABLE`;
* **`chg_30d_pct`** — the price change over the 30-bar window already pulled for the ADVol
  denominator. It costs NO extra call;
* **`mcap_verified` / `days_since_ipo` / `post_lockup`** on the IPO rows — a name with no
  valuation row passes the $1B floor BY DEFAULT and the reader must be able to see that;
* **the backlog's live re-score** — every tagged name with its FROZEN tags, its LIVE tags and a
  `tag_change` verdict (`NEW` / `UNCHANGED` / `ADDED` / `REMOVED` / `MIXED`). The ledger rows
  stay frozen, because that is what a ledger means; freezing the TAGS too hid the coil →
  breakout transition, which is the signal.

### 2.2 The state: `pattern-study/cron06-state/short-float-<fire-date>.json`

`ownership_stats` has no `date` column, so the short-float book cannot be replayed: this
week's snapshot is the FIRST sample of a series. Each run now writes one snapshot per week to
the outputs repo, and the next run publishes the change in short float
(`short_float_delta_pp`, in percentage points, `NO_PRIOR_SNAPSHOT` where there is no base).

Snapshots are one file per fire date, append-only, so two concurrent runs cannot conflict on a
single growing JSON and a diff shows exactly what changed between weeks.

### 2.3 The contract: `cron06-refresh-v2`

Named in the artifacts, the JSON companion, the state file and the spec, and asserted by
`tools/check_cron06_artifact.py` (14 clauses):

| Clause | What it refuses |
|---|---|
| C1 | a missing or stub artifact file |
| C2 | an artifact without the contract marker (i.e. an older run's shape) |
| C3 | a truncated branch (`rows_passing != rows_kept`) or an unpublished coverage line |
| C4 | an IPO row without a numeric `days_since_ipo`, a YES/NO `post_lockup`, a YES/NO `mcap_verified`, a closed-set verdict |
| C5 | a verdict outside the closed set, a squeeze flag that is not YES/NO, a delta that is neither a number nor `NO_PRIOR_SNAPSHOT`, or a row with `adv30` but no `chg_30d_pct` |
| C6 | an intersection that is INCOMPLETE — the checker recomputes the join from the universes and compares the sets, so a missing name is a failure, not a sample |
| C7 | a live re-score with the wrong row count, or a `tag_change` outside the closed set |
| C8 | a name silently dropped from the ledger, or a ledger size that does not equal prior + new |
| C9 | a missing or mis-numbered state snapshot |
| C10 | a float artifact published as tradeable, or a squeeze flag without its two preconditions |
| C11 | a placeholder `—` in a required field |
| C12 | an artifact that does not publish its fire date and data date |
| C13 | a missing source-health section |
| C14 | a reply that does not name every newly tagged ticker and every intersection name |

C6 and C8 are the two that would have caught the 2026-11-07 artifact.

### 2.4 The proof: `tools/test_cron06_contract.py`

A checker that only ever fails is a checker nobody trusts, and a contract nobody can satisfy is
a contract that gets skipped. The test feeds the engine synthetic screens, renders the
artifacts, requires the checker to exit 0, then MUTATES the artifact set fourteen ways — one
per clause — and requires the checker to fail every time.

The test earned its keep immediately: it caught a **percent-vs-fraction bug** in the engine
(thresholds in percent compared against fraction constants, which marked every short-float row
a `FLOAT_ARTIFACT`), a `type` lookup against the wrong table, and a `tag_change` that treated
"no tags yet" as "not in the ledger".

### 2.5 The spec: `cloud-prompts/skills/stock-screener-suite/SKILL.md` §8b

Rewritten as the contract: the engine fetch block with its capability marker, the run sequence
(the `--intersections-only` step exists because the intersection names are needed BEFORE the
enrichment query can be built), the published-field table with every vocabulary, and the three
traps the routine walks into.

Because the skill and the engine are fetched at RUN time, this lands on the next fire with **no
`cron_update` and no prompt drift**.

## 3. Deliberately NOT done

* **No fourth screen.** Three is enough; the missing value was in the joins.
* **No decision layer.** The routine stays a standalone research library: it publishes
  descriptions, verdicts and intersections, and it does not tell the reader what to trade.
* **The 2026-11-07 artifacts were re-rendered from the data AS CAPTURED on 2026-11-07**, not
  re-queried. `ownership_stats` is a live snapshot with no date column, so re-querying it on
  2026-11-09 would have produced a short-float book that was never measured on 2026-11-06 —
  a fabricated artifact. The only re-read data is date-pinned price history, which does not
  drift.

---

## 4. The 2026-11-14 fire: the week-over-week delta was silently empty

### 4.1 The defect

The 2026-11-14 fire (Saturday 15:00 ET, data date 2026-11-13) found a defect in the
ENGINE, not in the data. The short-float delta is computed against the PRIOR week's state
snapshot, whose `universe_pct` map is keyed by **ticker**:

```python
"universe_pct": {r["ticker"]: r["short_pct_float"] for r in sf_rows}
```

but the lookup used the **full symbol**:

```python
if sym in prior_pct:                 # sym == "VG.NYSE", prior_pct key == "VG"
    delta = round(sp - prior_pct[sym], 1)
else:
    delta = "NO_PRIOR_SNAPSHOT"
```

So the lookup never matched. **All 134 rows published `NO_PRIOR_SNAPSHOT`**, including the
128 names that WERE in the 2026-11-07 snapshot, and the artifact's note told the reader
that the delta was "the change against the 2026-11-07 state snapshot" — a claim the data
did not support. The whole point of the state series is that it answers "what changed this
week", and the answer was empty on its second run.

The 2026-11-07 fire could not catch it: that run wrote the FIRST snapshot, so
`prior_state_fire_date` was null and `NO_PRIOR_SNAPSHOT` was the correct answer for every
row. The bug was latent until a second sample existed.

### 4.2 The fix

* `cloud-prompts/_shared/cron06_refresh.py` — the lookup is keyed by `r["ticker"]`, and the
  delta is normalised with `or 0.0` so a published "-0.0 pp" does not read as a defect.
* `tools/check_cron06_artifact.py` — new clause **C15**: when `--prior-state` is supplied,
  the checker RECOMPUTES every delta from the prior snapshot and fails a row that says
  `NO_PRIOR_SNAPSHOT` while it was in that snapshot, a delta that does not match the
  recomputation, a name that was NOT in the snapshot but claims a delta, or a markdown
  cell that disagrees with the JSON companion. Without `--prior-state` it still fails an
  artifact that names a prior snapshot while no row carries a delta.
* `tools/test_cron06_contract.py` — the C15 mutation (blank every delta) is now in the
  fault-injection set, and the harness restores the REPLY file between mutations. Without
  that restore, the C14 mutation left a broken reply behind and every later mutation was
  "caught" by C14 instead of its own clause — a green run that proved nothing.
* `cloud-prompts/skills/stock-screener-suite/SKILL.md` §8b.3/§8b.5 — the enrichment now
  covers the WHOLE short-float universe, not just the intersection and the top 40, so
  `NO_QUOTE` means "no volume history" instead of "not measured this run".

### 4.3 What it changed in the numbers

The 2026-11-14 artifact now carries a real week-over-week delta on 128 of 134 names. The
largest moves: SOUN -4.2pp (37.7%), DKS +4.0pp (24.2%), AAP -3.3pp (25.6%), NUVB +1.8pp
(29.4%). Six names carry `NO_PRIOR_SNAPSHOT` because they were not in the 2026-11-07
snapshot — they entered the universe this week, which is a different fact from "the delta
is unavailable".

### 4.4 Deliberately NOT done

* The contract version stays `cron06-refresh-v2`. A defect fix that changes no published
  field, no vocabulary and no file set is not a new contract; bumping it would have made
  the 2026-11-07 artifacts look non-conforming.
* The 2026-11-07 artifacts were NOT re-rendered. They were built before the state series
  had a second sample, so their `NO_PRIOR_SNAPSHOT` was true at the time and re-rendering
  them from a later snapshot would publish numbers that were never measured.

### 4.5 The universe shrank 374 → 134 for a REASON THAT IS NOT THE MARKET

The 2026-11-07 run published a 374-name short-float universe. The 2026-11-14 run published 134,
and the naive reading — "the short-float book collapsed by 64% in a week" — is false.

The gate decomposition (measured on the same live `ownership_stats` snapshot, 2026-11-14):

| Gate set | Names |
|---|---|
| `short_percent_float > 20%` | 389 |
| + `type = 'Common Stock'` | 374 |
| + `volume > 1,000,000` on the resolved date | 219 |
| + `market_cap > $1B` (valuation row on the resolved date) | 130 (134 without the type filter) |

374 is EXACTLY the short-interest gate plus the type filter. The 2026-11-07 run therefore applied
only those two gates and **not** the liquidity and size floors that `references/filters.md` §O
specifies. Re-running the documented gate set on the PRIOR week's date (2026-11-06) gives 151
names, so the like-for-like move is **151 → 134**, and 23 of the 24 names that left last week's
top 30 are still above 20% short float — they fell off on the $1B market-cap floor (EROC $405M,
QMCO $605M, SHOE $390M) or on a single day's volume below 1M shares (RH, $2.45B cap but 463K
shares traded on 2026-11-13). Only ATYR genuinely left the universe (short interest fell to
10.5%).

Two lessons, both now written into the skill spec (§8b):

* **The gate set belongs in the artifact's coverage line.** A universe that changes because the
  SCREEN changed must be distinguishable from a universe that changed because the MARKET changed.
* **`ownership_stats` is a live snapshot**, so both weeks' screens read the SAME short-interest
  numbers — the prior week's table is not a replayable snapshot and the prior week's universe
  size cannot be re-derived from it. Only the price/volume history is date-pinned.
