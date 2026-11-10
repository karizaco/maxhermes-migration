# IMPROVEMENTS — 2026-11-10: cron #26's brief made CLAIMS about the screen that nothing checked

- **Date:** 2026-11-10 (the 2026-11-09 08:30 ET fire's artifact, corrected and republished)
- **Scope:** cron #26 `agentic-pre-market-brief` — the `check_brief_consistency.py` linter and
  the skill spec's writing rules.
- **Trigger:** a review of the 2026-11-09/10 commits found three published claims that the
  brief's own machine-readable companion contradicts. One of them had been published, corrected
  and republished, and survived the correction.
- **Status:** fixed in the skill spec (fetched at RUN time — **no `cron_update`, no prompt
  drift**) and in `tools/check_brief_consistency.py` (also fetched at run time). The deployed
  cron #26 prompt was NOT touched. **No published price, gap or table row was wrong** — only
  the claims the prose made about them.

---

## 1. What the reader found

The 2026-11-09 pre-market brief made three claims about its own screen. All three are false,
and each one contradicts `daily-briefs/2026-11-09-pre-market.csv`.

### 1.1 A universal claim one name was under

§1 of the brief said:

> **Metals are the broadest bid on the board (35 names, every one ≥ +3.00%, none down).**

The companion CSV's `Non-Energy Minerals` rows, with both screen gates passed, are **35 rows**,
and one of them is not at or above +3.00%:

| ticker | company | gap % | liquid_screen | quality_screen |
|---|---|---|---|---|
| UEC | Uranium Energy Corp. | **+2.60** | pass | pass |
| (the other 34) | | +3.01 and up | | |

The set is small enough to be unique: `Non-Energy Minerals` × `liquid_screen=pass` ×
`quality_screen=pass` is **35 rows**, and no other sector-and-gate combination in the 931-row
screen produces 35.

### 1.2 A name listed inside a band it is nowhere near

§1 also said:

> The liquid expression moves a uniform +3.0% to +4.7%: **GFR +38.39%**, TECK +4.63%, …

GFR moved **+38.39%**. Its own percentage was correct — the **band** was not. The same
sentence in §2 listed the band correctly, without GFR.

### 1.3 A superlative that is not true of the set it names

§2 called GFR "**the largest name left in the theme**, at a $1.35B market cap". The theme's
members by cap, from the same CSV:

| ticker | market cap |
|---|---|
| BHP | $200.99B |
| FCX | $85.33B |
| AU | $46.96B |
| TECK | $29.69B |
| KGC | $26.20B |
| HL | $9.90B |
| AG | $7.47B |
| **GFR** | **$1.35B** |

GFR is one of the **smallest** names in the theme. The sentence was true before the 2026-11-10
market-cap correction ("the two biggest movers"), which said *movers*; the rewrite said *name*
and changed what it claimed from a ranking of percentage moves to a ranking of size.

## 2. Why nothing caught them

`check_brief_consistency.py` enforces four things about the brief: the sections are present and
in order, no placeholder is left, every table row agrees with the CSV, and every **bold
`ticker +X%`** in the prose agrees with the CSV.

**Every claim above names no ticker.** The per-ticker checks never looked at them, and nothing
compared them to the screen. The band claim is the clearest case: GFR's +38.39% was checked
against the CSV, found correct, and the sentence was published anyway — because the sentence
also contained a band, and the band was the false part.

A universal claim is a different kind of statement from a published one. The linter had no
notion of either.

## 3. What changed

### 3.1 `tools/check_brief_consistency.py` — the claims are now checked

Two new checks, both resolved against the screen rather than against the prose:

- **A band claim.** Every name listed after a stated band must fall inside that band.
- **A universal claim.** A sentence with a universal quantifier ("every one", "all N", "none is
  down") and a threshold ("at or above +3.00%") is resolved to a set of rows and checked
  against it. The set is found by a `sector` value named in the sentence; failing that, by the
  claim's own count, when exactly one sector-and-gate combination of that size exists in the
  screen.

Two deliberate design decisions, both pinned by the regression test:

- **A claim the screen cannot resolve is a `note:`, not a breach.** A claim that names no set
  ("the metals complex") cannot be proved false by a linter, and blocking the fleet on it
  would be worse than surfacing it. The note says how to make it checkable.
- **A correction note that QUOTES an earlier claim is not a claim.** The 2026-11-10 amendment
  says "§1 still said every one of the 35 ... was at or above +3.00%". That is true about the
  old text and false about the screen, and a linter cannot tell the difference without being
  told. Sentences that report what a text said are skipped.

### 3.2 `tools/test_brief_consistency.py` — a new regression test

The linter had **no** test at all, which is why this shipped. The new test has three parts, in
the house style of the other `tools/test_*_contract.py`:

- **A** — a conforming synthetic brief passes, and raises no note.
- **B** — fault injection: each new check has a fixture that breaks it, and a mutation that
  changes nothing is itself reported as a failure.
- **C** — the edge cases: an unresolvable set is a note; a correction note quoting an earlier
  claim is not a claim; a missing artifact exits 2 rather than crashing.

The test was verified to fail when the checker it covers is broken — removing the band check
or no-op'ing the threshold check each drops it to `11 passed, 1 failed`.

### 3.3 `cloud-prompts/skills/agentic-pre-market-brief/SKILL.md` — the writing rules

Three rows in the **Failure modes** table (the table of "these are real, learned from prior
runs"), one new **Hard rule**, and the §Step 9 description of what the linter now enforces.
The skill spec is fetched at run time, so the next fire uses it with no deploy.

## 4. Evidence

The linter run against the **pre-fix** artifact (the one published before the amendment) and
against the **current** one, same CSV:

```
$ python3 tools/check_brief_consistency.py --md prefix.md --csv screen.csv
  band names checked : 16
  set claims checked : 3
  RESULT: INCONSISTENT (2 problem(s))
    - claim says every one is at or above +3.00%; 35 row(s) of the screen, Non-Energy Minerals, liquid + quality the lowest is +2.60%
    - band claim: GFR +38.39% is listed inside the stated +3.00% to +4.70% band
```

```
$ python3 tools/check_brief_consistency.py --md current.md --csv screen.csv
  band names checked : 16
  set claims checked : 3
  note: claim says 35 names; 36 row(s) of the screen, Non-Energy Minerals, liquid match the set as stated (+2.60% to +50.99%)
  RESULT: consistent
```

Both published errors are caught. The current artifact passes, and the remaining note is the
**35 vs 36** count: §2 says "35 Non-Energy Minerals names … that cleared the liquidity gate",
and the liquidity gate holds **36** of them (the 36th is NWGL, which fails the market-cap
gate). The claim is true of the set it names; the count and the gate disagree. That note is
the correct reading and the fix is to say "both gates".

The regression test:

```
$ python3 tools/test_brief_consistency.py
12 passed, 0 failed
```

and, with the checker mutated:

```
band check removed      -> 11 passed, 1 failed
threshold check no-op'd -> 11 passed, 1 failed
restored                -> 12 passed, 0 failed
```

## 5. What is still open

- **The deployed cron #26 prompt was not touched and does not need to be.** The skill spec and
  the linter are both fetched at run time; a push to `main` is enough. This is the cheapest
  edit path in this repo, per AGENTS.md §2.
- **The superlative (1.3) is a writing rule, not a mechanical check.** "The largest name left
  in the theme" needs a machine-readable notion of "the theme", which the CSV does not carry.
  The rule now says to rank by the thing claimed — a move for a percentage, a name for a
  market cap — and to check it against the `market_cap` column before writing it.
- **The published artifact was amended in the outputs repo**, not here. This repo holds the
  procedure; `karizaco/minimax-cloud-outputs` holds the artifacts.
