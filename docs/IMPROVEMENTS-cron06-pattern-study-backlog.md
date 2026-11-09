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
