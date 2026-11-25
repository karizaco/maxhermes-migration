# IMPROVEMENTS-cron09-2026-11-25 — the truncation fingerprint fired on a complete book, and the two-pass driver could not read its own output

**Date:** 2026-11-25
**Routine:** cron #09 `stock-screener-daily-sweep-18:30` (the end-of-day sweep)
**Fire:** 2026-11-25 18:30 ET (dispatched 18:30:00 ET, `stall_min: 0` — not stalled, window check OK, `fire-date: 2026-11-25`)
**Artifacts:** `daily-screens/2026-11-25/daily-sweep.md` + `breadth.md` + `_regime.json` in `karizaco/minimax-cloud-outputs@main`
**Found by:** the 2026-11-25 fire itself, in phase 1 of the two-pass driver.

Both findings are in `tools/` — the files every fire fetches at RUN time — so
the fix lands with **no prompt edit and no `cron_update`**.

---

## Finding 1 — the truncation fingerprint is a NUMBER, not evidence, and it fired on a complete book

**The symptom.** The 2026-11-25 phase-1 fetch died with:

```
sweep_pipeline.PipelineError: TRUNCATION FINGERPRINT:
  ['B_stockbee_ep9m', 'C_qullamaggie_rs'] landed exactly on a cap (30/50/60/200).
```

**What was actually true.** Both branches were COMPLETE. Measured on the
2026-11-24 screen session:

| Branch | `rows_passing` | `rows_kept` | pages | branch SQL carries an inner `LIMIT`? |
|---|---|---|---|---|
| `B_stockbee_ep9m` | **200** | **200** | 2 (page 2 empty) | no |
| `C_qullamaggie_rs` | **60** | **60** | 1 | no |

`rows_passing` is `COUNT(*) OVER ()` computed **inside** the branch CTE, and
`screen.emit_sweep_sql_branch` emits exactly ONE `LIMIT` — the outer page size
(`LIMIT 200 OFFSET n`). The branch CTE itself is uncapped. So
`rows_passing == rows_kept` is the true passing count, and the coverage
assertion (`rows_kept == rows_passing`, the guard that makes the book
publishable) HOLDS. Both books were complete.

**Why the fingerprint existed.** It was written for the OLD shape, where each
branch CTE carried its own `LIMIT 50 / 30 / 60` (the defect that shipped on
2026-11-03 and 2026-11-04). Under that shape a count of exactly 30/50/60 was
necessarily the cap. That shape is gone — §2 of the skill spec now says "one
branch per query, uncapped, and page it" — but the numeric rule stayed, and it
now fires on **any** session where a branch's true passing count happens to
equal one of four numbers.

**Why this is worse than a false alarm.** The run **fails closed**: nothing is
published, no artifact exists, and the fire produces no deliverable. A
probability of about 1-in-12 per branch per session (four target values, two
branches with volatile counts) is enough to block the routine's output on
several sessions a year. And the failure message is actively misleading — it
says "truncation" when the book is provably whole, which invites the next
operator to go looking for a truncation that does not exist.

**The fix — the fingerprint is now EVIDENCE-BASED.**

- `tools/sweep_pipeline.py` gains `has_inner_limit(sql)`: it strips the comment
  header and counts the `LIMIT` occurrences in the emitted branch SQL. One
  `LIMIT` = the outer page size (legitimate). Two or more = the branch CTE
  caps its own book (the historical defect).
- `collect_branches` records `inner_limit` and `legacy_cap_collision` on every
  coverage row, and raises **only** when a branch that carries an inner LIMIT
  lands on a cap value. `rows_kept != rows_passing` still fails as before.
- `cmd_check` asserts `not coverage.inner_limit` instead of asserting the
  number is not in `(30, 50, 60, 200)`.
- The artifact's coverage table publishes the collision instead of hiding it:
  a branch that lands on a legacy cap value is rendered as
  *"complete — count lands on a legacy cap value, verified: no per-branch
  LIMIT, rows_passing == rows_kept"*, and the prose says how many branches
  landed on such a value and that each was verified. The rule in the skill
  spec (§2 and §4) is updated to the same evidence-based form.
- `tools/test_sweep_pipeline.py` now proves BOTH directions: a branch with an
  inner LIMIT that lands on 50 **is** caught, and a complete book that lands
  on 200 **is not** flagged. A gate that can only fail in one direction is not
  a gate.

The general lesson, which belongs to every routine that has a "that number
looks wrong" heuristic: **a shape heuristic is a claim about the DATA, and a
claim must be derived from the thing it describes.** The truncation
fingerprint described a property of the SQL, so it must be read from the SQL.

---

## Finding 2 — the two-pass driver's phase 2 could not read phase 1's own output

**The symptom.** With the fingerprint fixed, phase 1 completed and persisted
`scratch/pass1/branches.json`. Phase 2 then died:

```
File "tools/sweep_two_pass.py", line 144, in <module>
  sp.collect_branches = lambda *ar, **kw: (b["rows"], b["coverage"])
TypeError: list indices must be integers or slices, not str
```

**The cause.** `collect_branches()` returns the PAIR `(rows_by_branch,
coverage)`. Phase 1's wrapper persists that value verbatim, so the file on
disk is a **2-element array**. Phase 2 read it as a dict (`b["rows"]`). The
driver could not replay its own capture.

**How long this has been broken.** `scratch/pass1/branches.json` in the
2026-11-23 workspace is also a 2-element array — the same shape — so the
defect was present for the previous fire too. It is only visible when a run
actually reaches phase 2 with a persisted branches file, which is why it
survived: the failure is a `TypeError` on the last step of a run that has
already spent its metered bridge allowance, and the run before it was
abandoned mid-way (a replay with a fresh `scratch/`).

**The fix.** Phase 2 now accepts BOTH shapes — a dict with `rows`/`coverage`
keys, or the 2-element array the collector actually returns — and keeps the
REAL coverage either way (the pipeline's own `--branches-json` replay path
rebuilds it with `pages: 1`, which loses the page count).

---

## What changed

| File | Change |
|---|---|
| `tools/sweep_pipeline.py` | `has_inner_limit()`; `coverage.inner_limit` / `coverage.legacy_cap_collision`; the fingerprint raise and the checker assertion are now evidence-based; the coverage table publishes the collision |
| `tools/sweep_two_pass.py` | phase 2 reads the branches capture in either shape |
| `tools/test_sweep_pipeline.py` | the cap case now carries an inner LIMIT; a new case proves a complete book landing on 200 is **not** flagged |
| `cloud-prompts/skills/stock-screener-suite/SKILL.md` | §2 and §4: the fingerprint is a cap only when the SQL could have produced it |

**Verified offline:** `tools/test_sweep_pipeline.py` 14/14, `test_sweep_pipeline_vix.py` 17/17,
`test_sweep_pipeline_divergence.py` 4/4, `test_sweep_replay.py` 6/6,
`test_sweep_engine_pagination.py` 4/4, `test_daily_sweep_engines.py` 9/9,
`test_breadth_contract.py` 14/14, `test_checker_ladder.py` 12/12.

**Verified live:** the 2026-11-25 fire ran phase 1 → phase 2 → `check` (exit 0,
no stub markers), and `daily-screens/2026-11-25/{daily-sweep.md, breadth.md,
_regime.json}` are present on `minimax-cloud-outputs@main`.

---

## The 2026-11-25 book, for the record

- **Breadth (settled close, 1,086 names > $10B):** 41.07% above the 20-DMA,
  775 advances / 294 declines (ratio 2.64), divergence **+41.07 pp BROAD** —
  0 of 5 index ETFs above their 20-DMA while the average large cap is not.
- **Volatility:** VIX **28.29** / VIX3M **26.29** (ratio 1.0761) → `uncertainty:
  true`. The Cboe CDN answered **HTTP 403**; the documented Yahoo chart-API
  fallback served the pair, and the artifact names the source.
- **Book:** 1,366 candidates, 12 Focus, 7 Tier-A — and Tier-A is **1 fresh / 6
  extended**, which is the honest answer to "why do these names always look
  like they have already run".
