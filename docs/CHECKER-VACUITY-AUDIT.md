# The checker-vacuity audit — which gates cannot fail

Date: 2026-11-21. Scope: every `tools/check_*.py` in this repo (18 checkers).
Tool: `tools/audit_checker_vacuity.py` (offline, no network, deterministic).

## Why this document exists

On 2026-11-19 cron #06's own truncation guard was found to be **vacuous**: the contract
asserted `rows_passing == rows_kept`, but the producer wrote `rows_passing = len(rows)`,
so the clause compared a number with itself and a truncated branch would have shipped
claiming completeness. Two days later the same routine's cross-check turned out to have
**no coverage floor** — a cross-check covering 10 of 138 names passed every clause.

A gate that cannot fail is invisible in review: it *looks* like a measurement. Four of the
defects found in #06 in three days were of this kind, which is enough to justify looking
for the class fleet-wide instead of routine by routine.

## What the audit found

| Pattern | Meaning | Candidates |
|---|---|---|
| **FIXED_INDEX** | a parsed table row read at a literal index (`r[6]`, `cells[5]`) — adding a column moves every cell to its right and the check silently reads the WRONG CELLS | **33**, in 2 checkers |
| **SELF_COMPARISON** | a clause comparing two fields the same producer fills from the same place | **5**, all in #06 (now addressed — see below) |
| **NO_TEST** | a checker with no fault-injection test beside it | **0** — every one of the 18 checkers has one |

Indexes 0 and 1 are excluded by the tool: they are the row-number and ticker convention
that every table in the fleet uses. Index 2 and beyond is a content column, and a content
column moves.

### The two remaining hot spots

| Checker | Fixed-index candidates | Why it matters |
|---|---|---|
| `tools/check_premarket_refresh.py` | **29** | The refresh artifact's tables are the widest in the fleet, and 29 content columns are read by position. The 2026-11-19 lesson applies directly: the day a column is added to that table, up to 29 checks start reading the wrong cells — and they will still PASS, because a placeholder in the wrong column is still a placeholder. |
| `tools/check_preopen_checkpoint.py` | 4 | Same class, much smaller surface. |

### What is already fixed

Cron #06's checker was the pilot: every content column is now looked up **by header
name** (`col_map()`), so the artifact can add a column without moving a check. The
`Src %Float` column added on 2026-11-19 moved every cell to its right and C11/C15 were
reading the wrong cells for a full day before it was caught.

The five SELF_COMPARISON candidates in #06 are the `rows_passing` / `rows_kept` clause.
It is no longer a self-comparison: `rows_passing` now comes from the screen query's own
`COUNT(*) OVER ()` — a window count measured by the same execution that produced the rows
— while `rows_kept` is the number of rows the engine actually collected. The two are
independent measurements, and the engine refuses to publish when they disagree.

## The recommended order

1. **`check_premarket_refresh.py` (29)** — convert the content-column reads to header-name
   lookups, and add a fault-injection case that INSERTS a column into the rendered table
   and requires the checker to fail (the mutation that proves the checker reads the right
   cells, rather than the one that proves it reads the wrong ones).
2. **`check_preopen_checkpoint.py` (4)** — same conversion.
3. **A per-routine "vacuity review"** — for each of the 18 checkers, answer one question
   per clause: *is the thing compared against the thing measured, or is one of them a
   number the producer wrote next to the other?* The tool narrows the list; a human
   decides.
4. **Keep the audit in CI** — `python3 tools/audit_checker_vacuity.py --strict` fails the
   build when a new fixed-index read appears. A check that cannot fail is a gate in
   appearance only, and this makes the appearance expensive.

## What this tool cannot find

A clause that compares two genuinely independent measurements is indistinguishable from a
self-comparison by reading alone, and a clause that is wrong in a way no regex sees is
invisible to it. The tool reports **candidates, never verdicts** — it narrows the list a
human has to read. It has already paid for itself once: it found #06's 15 remaining
fixed-index reads (all since converted) in one run.
