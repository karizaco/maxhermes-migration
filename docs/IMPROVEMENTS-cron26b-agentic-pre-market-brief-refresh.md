# IMPROVEMENTS — cron #26b, the 09:20 ET pre-market refresh

**Date:** 2026-11-10 · **Routine:** `26b-agentic-pre-market-brief-refresh-0920.md` ·
**Procedure:** `cloud-prompts/_shared/premarket-refresh.md` (run-time fetched) ·
**Checker:** `tools/check_premarket_refresh.py` + `tools/test_premarket_refresh_contract.py`

A review of every #26b fire to date, and the changes made to the routine's definition.

---

## 1. What was reviewed

| Fire | Artifact | Spec in force | Note |
|---|---|---|---|
| 2026-11-04 | `daily-briefs/2026-11-04-pre-market-refresh.md` (13,532 B) | pre-rewrite | the routine's first fire |
| 2026-11-05 | `…-2026-11-05-pre-market-refresh.md` (20,243 B) | pre-rewrite | 49-min platform stall; upstream quota-killed |
| 2026-11-06 | `…-2026-11-06-pre-market-refresh.md` (14,174 B) | pre-rewrite | the morning baseline was a truncated floor |
| 2026-11-09 | `…-2026-11-09-pre-market-refresh.md` (24,005 B) | **the rewrite** | first fire of the decision sections |
| 2026-11-10 | `…-2026-11-10-pre-market-refresh.md` (18,658 B) | the rewrite | second fire — 179/179 of the new checker's checks pass |

**Run coverage is clean:** four run records for 11-04 / 11-05 / 11-06 / 11-09 (all `status: 1`),
none on 11-07 / 11-08 (weekend), no replay, no window-check skip. The live #26b prompt is
**byte-identical** to its repo blob (`sha256 4c1b4fb4f81d6cde27c2d5f429ffcd4cdb98652ab1956adecf11fd5e7da083df`,
7,394 B) and it fetches the procedure at run time — so every change below lands on the next fire
with **no `cron_update` and no prompt drift**.

**The rewrite landed on 2026-11-07** (`b65d990ffb` "the refresh publishes a decision, levels and
the driver class"), so the decision-bearing sections — `## Bottom line`, `## What to watch at the
open`, `## Gap quality` and the Driver vocabulary — had **one** live fire before this change, and
the companion CSV clause (`ab9b680c6c`) landed on 2026-11-09, 2.5 h before that fire.

**#26b had NO machine gate.** The repo carried sixteen checkers; none for this routine. A local
checker written during the 2026-11-06 run caught 10/10 injected faults and was never committed.

---

## 2. The evidence for each change

### E1 — the thin-tape block silently truncates (→ the procedure: publish it in full)

| Fire | The claim | The rows published |
|---|---|---|
| 2026-11-04 | "(42 names)" | 42 — all of them |
| 2026-11-05 | "(17 gainers, 31 decliners)" | 48 — all of them |
| 2026-11-06 | "22 gainers and 22 decliners qualify; the largest are below" | **18 of 44** |
| 2026-11-09 | "23 gainers and 25 decliners qualify; the largest are below" | **20 of 48** |

The qualifier counts are right; a reader cannot tell how many rows the block carries, and a
truncated block reads as a complete one. **The checker now fails it** (`THIN-COMPLETE`).

### E2 — cross-pull band comparisons were made against a baseline that was a floor (→ read the baseline's completeness)

The 2026-11-05 and 2026-11-06 morning briefs were pulled with the screener's `range:[0,400]` cap,
so their published band counts were floors: on 2026-11-06 the brief published **403 gainers**
while the band actually held **650**. The refresh disclosed it in prose — correct instinct, but a
paragraph is not a machine-readable input, and the "faded out of the band" count inherited the
same truncation. The 2026-11-09 morning brief published `screen_complete: true` (598 exact), so
the 2026-11-09 comparison was sound — but the refresh had to infer that from a field the
procedure never named. **The procedure now requires the baseline's completeness to be read, and
the front matter publishes `up_3pct` / `down_3pct` / `screen_complete` of its own pull.**

### E3 — the morning CSV's row count is not the morning's band (→ pin the base)

The 2026-11-09 morning CSV carries **931 rows**; only **600** are inside the ±3% band (the brief
published 598). Comparing "morning CSV rows" against the live band rows counts names that were
never in the band: the raw base gives **394** fades; the true figure is **90**. The procedure now
says: filter the morning CSV to `abs(gap_pct) >= 3` first.

### E4 — no branch for a late pull (→ the late-pull branch)

On 2026-11-05 the platform stalled 49 minutes and the pull ran at **10:10 ET with the market
open**. The run invented its own §4 (a live-session block), three ad-hoc front-matter keys
(`pull_late`, `market_open_at_pull`, `changes_since_morning: n/a`) and its own explanation. The
procedure assumed a pre-open pull ("this refresh fires at 09:20, so it cannot apply Rule 1"), so
it did not cover a case the fleet has already hit. The procedure now carries the branch, and the
checker reads `market_open_at_pull` to decide whether `live_*` may be blank.

### E5 — the Driver's source was machine-readable and the procedure ignored it

The morning brief's CSV already publishes `setup_theme` (74 rows across C1–C5 on 2026-11-09),
`has_news` (17 rows `yes`) and `setup_published` (74 rows `yes` — exactly the theme-cluster set).
The mechanical rule

> `has_news = no` ⇒ `NONE`; otherwise classify the catalyst of the name's `setup_theme` cluster

reproduces the 2026-11-09 published Driver column **name for name** — including FTH, NKTX and
ABEO, which sat in the biotech cluster's TABLE with `has_news = no` and no per-name catalyst in
its PROSE. The 2026-11-09 run re-derived the clusters by hand from the prose instead. The
procedure now names the columns as the source.

### E6 — the Driver vocabulary had no class for two things the tape produces

- a **clinical readout** (IMVT met its primary endpoint: ACR20 92.5% vs 75.6% placebo, p=0.0139;
  VIR's Phase 1; ZURA's Phase 2 miss) — six of the ten headline decliners on 2026-11-09 were
  prints or readouts;
- a **company-specific adverse event** (NVDA's board investigation — `has_news = yes`, and no
  class in the vocabulary describes a governance shock).

A run that has to bend a class to fit it will bend a different one tomorrow. The vocabulary now
carries a scope line for `EARNINGS-*` (they describe the DIRECTION of a company-reported result,
not the instrument) and one new class, `CORPORATE-EVENT`. The procedure also says the vocabulary
is **closed**: a run may not invent a class, and `unclassified` (plus one line in Source health) is
the honest answer when nothing fits.

### E7 — the Bottom-line class gate was stricter than its own stated purpose

The gate required an anchored Driver **and** one of `CASH-OUT` / `CASH-IN` /
`LIABILITY-RESOLVED` / `ASSET-VALUE` / `EARNINGS-RAISE`. On 2026-11-09 four of the 25 headline
names carried an anchor (DCTH, IMVT — `EARNINGS-RECONFIRM`; ZURA, IBRX — `EARNINGS-CUT`) and
**none** was in the five classes. So publishing "no name carries an anchored catalyst" would have
been **false**, and promoting an unanchored name is forbidden. The procedure now carries a
**three-rung ladder** (anchored + one of the five → anchored + still holding, with the deviation
published → nothing anchored, say so), and a rule that a gate may be widened by evidence but
never tightened on one session.

### E8 — the pull's range and the completeness assert were not mandated here

The procedure pointed at the #26 skill for "the exact body" and required only that
`premarket_high` / `premarket_low` came back. The `screen_complete` CSV column implied the
assert but never required it. The procedure now mandates `range:[0,1000]` **and**
`assert len(rows) == totalCount` on BOTH screens, and says what to do when the assert fails.

### E9 — Gate B was decided on the scanner's unreconciled market cap

`market_cap_basic` is `close × shares outstanding`, and the scanner does not refresh the share
count for corporate actions. Measured 2026-11-09 it reported **$143,016,256** for **NWGL** after
a one-for-80 ADS reverse split and an ADS ratio change — **87× too high**; the real cap sat in
the $0.5M–$1.9M range, so a sub-$2M shell topped the headline gap table over Gate B. The #26
skill now carries the reconciled-cap rule (2026-11-10, `9cae8eebf4`), and the 2026-11-10 refresh
applied it (NWGL and PBK moved to the thin tape). The refresh's procedure now states the rule
explicitly instead of leaving it to a cross-reference, and requires the reconciled figure.

### E10 — the artifact skeleton moved between two consecutive fires

2026-11-09 published 7 front-matter keys and unnumbered sections with the gap-quality block
**before** the top-of-book; 2026-11-10 published 11 keys and numbered `## 1.` … `## 5.` with the
gap-quality block **after** it. A reader and a checker cannot both work with a skeleton that
moves. The procedure now pins the skeleton, and the checker asserts it.

### E11 — a published artifact is amended when a human notices, never by rule

The 2026-11-05 file carries a hand-written `> UPDATE — 2026-11-06 05:55 ET: the baseline
resolved.` block, added by a later session when the upstream was resumed in place. It is the
right thing to do and nothing asked for it, so it happened by luck. The procedure now carries the
amendment convention and its trigger.

---

## 3. What changed

### `cloud-prompts/_shared/premarket-refresh.md` (21,578 B → 33,231 B)

- **`## The pull is a CONTRACT, not a suggestion`** — `range:[0,1000]`, the assert on both screens,
  what to publish when it fails, Gate B on a reconciled cap, and `premarket_time` is the session
  start (publish the pull's own clock).
- **`## The artifact skeleton — PINNED`** — the front-matter keys, the literal `cron:` value, the
  definition of `changes_since_morning`, and the section order.
- **`## Bottom line`** — the three-rung setup ladder and the two-session rule for a gate.
- **The Driver vocabulary** — the `EARNINGS-*` scope line, the `CORPORATE-EVENT` class, the
  closed-vocabulary rule, and the mechanical source table (`setup_theme` / `has_news`).
- **`## Rules`** — the fade/entry base, the baseline's completeness, the thin tape in full, the
  late-pull branch, the AMENDED convention.
- **The companion CSV** — `live_*` are BLANK pre-open (never 0), and `premarket_time` is not
  published per row.

### `tools/check_premarket_refresh.py` (new) — the machine gate

179 checks: the front-matter keys and values, the section skeleton, the three-line bottom line
(including the anchored-Driver rule and the cash case), the watch table's levels and sides, the
25 gap-quality rows and their Driver vocabulary, the headline tables' sorting and the gap-quality
rows' agreement with them, the thin-tape count against the rows published, the CSV's pinned
header / uniqueness / non-empty prices / `live_*` / `screen_complete` / band count, the markdown's
numbers traced back to the CSV, the snapshot stamps, the placeholder tokens, and — with
`--morning-csv` — `changes_since_morning` recomputed from the two CSVs.

### `tools/test_premarket_refresh_contract.py` (new) — the proof

A synthetic golden artifact that satisfies the contract, then **17 mutations**, each of which must
be caught by a NAMED check: `17 mutations, 17 caught, 0 slipped through`.

**Dry run against the real artifacts** (the rule from the fleet's own history — a rule derived
from one session must survive a second):

| Artifact | Result |
|---|---|
| 2026-11-10 (real) | **179 checks, 179 passed, 0 failed** |
| 2026-11-09 (real) | 177 checks, 171 passed, **6 failed** — all six are the pre-pinning defects this change fixes: the three missing front-matter keys, the unpinned skeleton, and the thin-tape truncation (claims 48, publishes 20) |

The 2026-11-10 artifact passing 179/179 is the important line: **the contract is satisfiable by a
real run, not only by a synthetic fixture.**

### E12 — the CSV's `prior_close` did not reproduce from the row's own numbers (→ derive from the published values)

The 2026-11-10 fire (the other session's run) measured this class and fixed it there: deriving
`prior_close` from the RAW pull leaves rows that do not reconcile, because the published
`premarket_close` and `premarket_change_pct` are rounded — a reader who divides the row's own
price by its own change gets a different close than the row publishes. The **2026-11-09 CSV has
the defect**: 293 of its 693 rows fail to reproduce (24 differ by more than half a cent, the
largest by 4.5¢ on FIX; exactly one of the 25 headline names is affected — INO, by half a cent —
so the published gap-fill levels are materially correct). The convention the 2026-11-10 CSV
already follows, and which the procedure now states: publish `premarket_close` at 4 dp,
`premarket_change_pct` at 2 dp, and compute
`prior_close = round(premarket_close / (1 + premarket_change_pct / 100), 4)` **from those
published values**. The checker asserts it on every row (`PRIOR-CLOSE-RECONCILES`).

The 2026-11-09 artifact is **not** rewritten: the fleet's rule is that a published artifact's
numbers are not edited after the fact (the amendment convention above is for dated corrections
in prose). The gate now catches it, and the next fire publishes it right.

---

## 4. What was NOT changed here, and why

**Cron #26's CSV schema (`driver_class` / `driver_anchor`) is on a branch, not on `main`.**
Publishing the Driver class from the morning brief — where the catalysts and the clusters live —
is the mature end-state for this pair of routines: #26b's gap-quality table would JOIN it instead
of re-deriving it, and the run-time invention of a class (E6) would stop. But #26's skill spec was
changed **twice on 2026-11-10** (`9cae8eebf4` reconciled-cap Gate B, `4e665590c9` the claims
linter) by another session, and #26's contract gate is hard — a schema change that the brief's own
run cannot satisfy would cost the fleet its morning artifact. The change is therefore on
`feat/cron26-driver-class-columns`, built on top of that session's commits, **to be merged
later** rather than landed under an active editor.

`docs/IMPROVEMENTS-2026-11-10-cron26-market-cap-gate.md` and
`docs/IMPROVEMENTS-2026-11-10-cron26-claims-about-the-screen.md` are that session's evidence for
E9; this document does not repeat them.
