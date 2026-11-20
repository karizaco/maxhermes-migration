# IMPROVEMENTS-cron09-2026-11-20 — the paged scanner pull sorted by a NON-UNIQUE key, and the tiering sorted against `None`

**Date:** 2026-11-20
**Routine:** cron #09 `stock-screener-daily-sweep-18:30` (the end-of-day sweep)
**Fire:** 2026-11-20 18:30 ET (dispatched 18:30:04 ET, `stall_min: 0` — not stalled)
**Artifacts:** `daily-screens/2026-11-20/daily-sweep.md` + `breadth.md` in `karizaco/minimax-cloud-outputs@main`
**Found by:** the 2026-11-20 fire itself — it died twice on the way, once at the fresh book and once at the tiering.

---

## Finding 1 — the paged universe pull sorted by `description`, a key that is NOT unique

**Evidence.** `tools/daily_sweep_engines.py::fetch_universe()` walks the TradingView scanner in
pages of 2,000 and dedupes through a `seen` set, then asserts `len(rows) == totalCount`. On the
2026-11-20 fire it fetched **3,710 unique rows against `totalCount` 3,711** and refused to publish:

```
EngineError: TRUNCATED SCAN: fetched 3710 rows against totalCount 3711. Refusing to publish a short book.
```

**The cause is the sort key, not the network.** The pull sorted by `description` — the **company
name**. That column is not unique: `GOOG`/`GOOGL`, `BBD`/`BBDC` and ~30 other pairs share one. The
scanner's tie-break among equal keys is **not stable between two requests**, so a row sitting on a
page boundary is served twice; the dedupe drops the repeat and the universe comes up one name
short. Measured directly against the live scanner on 2026-11-20:

| pagination key | unique rows | `totalCount` | duplicate rows served |
|---|---|---|---|
| `sortBy: description` | **3,710** | 3,711 | **1** (`LEN.B` — "Lennar Corporation", tied with `LEN.A`) |
| `sortBy: name` | **3,711** | 3,711 | **0** |

**The fix.** The paged pull now sorts by `name` (the ticker, unique), and `tv_scan()`'s **default**
sort changed with it — a helper whose default is an unstable key is the trap that brings the defect
back through a new caller. `name` is what `_shared/tv_scan.py` already uses for its paged pull.

**Why this one matters more than the crash.** The completeness assertion caught it, so nothing
wrong was published — but the run died AFTER spending the fresh book, the eight branches, the
CANSLIM half, the enrichment pass and the overlay. The fix is in the repo, so the next fire
inherits it with no redeploy.

## Finding 2 — `select_focus()` sorted a `None` velocity against an `int`

**Evidence.** With the fresh book fixed, the run died at the tiering stage:

```
File "cloud-prompts/skills/stock-screener-suite/scripts/screen.py", line 1731, in select_focus
  by_velocity = sorted(
TypeError: '<' not supported between instances of 'NoneType' and 'int'
```

`dict.get("velocity_14d", 0)` substitutes the default **only when the key is absent**. A candidate
whose `velocity_14d` is explicitly `None` comes back as `None` and is then compared against an
`int`. The file's own `select_tier_a()` — the other half of the SAME tiering — already used the
None-safe idiom `data.get("velocity_14d") or 0`, so the two halves of one function disagreed.

**The fix.** `select_focus()` now ranks on a two-part key: names that **carry** a velocity reading
rank above names that do not, and among the carriers the order is descending. A missing reading is
a *disclosure*, not a zero velocity — the same rule the overlay follows for a missing P/E
(§4.7.2 of the skill spec).

## Finding 3 — the divergence sentence was printed under EVERY band

**Evidence.** The `breadth.md` renderer printed one fixed sentence under the
`breadth_divergence` band:

> A **MATCHED** divergence means the average large cap is materially healthier than the index —
> participation is broader than the headline index, and the index's own posture is the weak leg.

The 2026-11-20 artifact published `band: MATCHED` over a **+14.94 pp** divergence and the
sentence directly underneath contradicted its own label. Worse, the sentence was unconditional:
a **NARROW** divergence — the average large cap *weaker* than the index — would have been
described with the same "materially healthier" wording, i.e. the opposite of what it means.

**The fix.** `_divergence_note(band, divergence)` derives the sentence from the band it is
attached to, the same house pattern as `_size_cut_note()` (a cell states a derived fact, never
a hardcoded one). The **band itself is unchanged** — BROAD at or above +15 pp, NARROW at or below
−15 pp, MATCHED in between — because it is a published rule; only the explanation now follows
the band.

**The band still sits on its edge**, and the artifact says so: +14.94 pp is 0.06 pp below the
+15 pp BROAD threshold. The reader should use the number, not the band word.

## Finding 4 — a 2026-11-12 document made a claim about this engine that was WRONG

`docs/IMPROVEMENTS-2026-11-12-tv-scanner-pull-completeness.md` §5 states (the paragraph is
corrected in place below):

> **#10 needs nothing** — … the EOD breadth inside cron #09's sweep goes through
> `daily_sweep_engines.py::fetch_universe()`, which **already pages on a stable key**, DEDUPES
> through a `seen` set and asserts `len(rows) == totalCount`

Two of the three claims were true. The third — "already pages on a stable key" — was **not**: the
key was `description`. The document asserted the property without measuring it, and the claim
survived a month of fires because **a stable-looking key is not a stable key**: the engine looked
correct, and the failure only appears on a session where a tied pair lands on a page boundary.

**The rule this adds:** a claim about a pagination key is only true if the key is **unique**.
"Stable" and "sorted" are not the property — `name` is unique, `description` is not, and a
tie-break among equal keys is server-side and not reproducible between requests.

---

## What changed

| file | change |
|---|---|
| `tools/daily_sweep_engines.py` | the paged pull sorts by `name`; `tv_scan()`'s default sort is `name` too, with the reason in the docstring |
| `cloud-prompts/skills/stock-screener-suite/scripts/screen.py` | `select_focus()`'s velocity sort is None-safe and matches `select_tier_a()`'s idiom |
| `tools/sweep_pipeline.py` | the divergence sentence is derived from the band (`_divergence_note()`), not printed under every band |
| `tools/test_sweep_engine_pagination.py` | **NEW** — 4 hermetic checks (no network): the paged pull sorts by `name`; a stable-key server yields a complete universe; an unstable-key server **fails closed** instead of returning a short book; the source carries no `description`-sorted paged pull |
| `tools/test_sweep_pipeline_divergence.py` | **NEW** — 4 hermetic checks: BROAD says "healthier", NARROW says "WEAKER", MATCHED says "same posture" and names the ±15 pp threshold, and the renderer carries no unconditional sentence |
| `docs/IMPROVEMENTS-2026-11-12-tv-scanner-pull-completeness.md` | §5's claim about cron #09's engine is corrected in place |

**No capability marker changed.** `DAILY_SWEEP_ENGINES_V1` and `STOCK_SCREENER_SUITE_V1` still
describe the same contracts; both fixes make the existing contract hold rather than adding a
capability. A stale CDN copy of the old engine **fails loudly** (it refuses to publish a short
book) — it cannot publish a wrong artifact, so no marker bump is required.

**Two of the three defects were found by the 18:30 ET fire itself, on live data.** A rule
nobody measured until a session produced the boundary case is a rule nobody has tested — the
2026-11-12 document's own §5 made exactly that mistake about this file, and the mistake
survived a month of fires because a *sorted* key looks like a *stable* one.

**Why the fetch ladder still matters.** Both files are fetched at run time. `sweep_pipeline.py`
fetches `screen.py` over a ladder that demands `STOCK_SCREENER_SUITE_V1`; `daily_sweep_engines.py`
is fetched by the skill's §4.5.1 ladder demanding `DAILY_SWEEP_ENGINES_V1`. Neither marker
discriminates between the pre-fix and post-fix copy, so until this commit is on `main`, a fire can
still pick up the old copy from a CDN that has not refreshed. The fixes are therefore worth
landing even though the artifact they protect is produced by a run-time fetch.
