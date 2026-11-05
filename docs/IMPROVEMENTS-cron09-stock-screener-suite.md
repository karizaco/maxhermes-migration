# Cron #09 `stock-screener-daily-sweep-18:30` — General Improvement Audit

**Audited:** 2026-11-03. Scope: the routine as a *system* — the skill spec, its SQL, its data
paths, its tiering contract, its output contract and its guard rails — not any single date.

**Verdict:** the routine *ran*, and produced a usable Tier-A list on 2026-10-28, but only
after the skill's own published SQL was repaired by hand at run time. Five defects sat in the
emitters; two of them were silent and had been hiding for weeks. The single highest-value
improvement was to fix the method **in the skill spec**, so every future run inherits it —
that is what this commit does.

---

## 1. Current state (verified 2026-11-03)

| Item | Value | Verified how |
|---|---|---|
| Fire time | 18:30 ET, weekdays | cron prompt |
| Data date (last run) | 2026-10-27 — shibui is T+1, so the screen describes the *previous* session | `SELECT MAX(date)` preflight |
| Candidates | 530 raw → 426 after the $300M floor → Master 200 / Stalk 13 / Focus 12 / **Tier-A 8** | run log |
| Tier-A (2026-10-28) | NTSK, DXC, TENB, QLYS, IOVA, KNSA, PRME, SOFI | `daily-sweep.md` |
| Regime | size cut 0%, uncertainty false, late cycle false; 65.9% of 905 large caps above the 20-DMA; VIX/VIX3M 16.91/19.22 | `_regime.json` |
| Themes of the week | IGV (software), IBB (biotech), XLE (energy) | sector RS composite |
| Prompt ↔ spec | the spec is fetched at run time, so a spec fix needs no `cron_update` | `raw.githubusercontent.com/.../main` |

---

## 2. What is genuinely good now

Credit where due:

- **The tiering contract is sound.** Counting *distinct stylists* rather than screen hits is
  the right abstraction, and the back-test that produced the 2/3 thresholds is documented.
- **The T+1 self-heal works.** `--resolve-latest` plus the preflight means a late ingestion
  does not write zero-hit skeleton files.
- **The screen logic itself is right.** Every defect below was a *transport* defect — a
  missing comma, an alias that did not match its definition, a window that was too short.
  The published criteria themselves were fine and needed no change.
- **The per-stylist decomposition is the asset.** Five traders' recipes over the full
  universe, merged into tiers, is a genuinely differentiated book.

---

## 3. The core problem: five defects in the skill's own SQL, two of them silent

Found on the 2026-10-28 run, when the emitted SQL could not be executed as published.

| # | Where | Symptom | Loud? |
|---|---|---|---|
| 1 | `emit_sweep_sql_stockbee` | CTE list missing a comma → `syntax error at or near A_stockbee_4pct` | yes |
| 2 | `emit_sweep_sql_qullamaggie` | CTE aliases `close_252d_ago` but the query references `close_252` → Binder Error | yes |
| 3 | `emit_sweep_sql_qullamaggie` | `UNION ALL` mixes branches of 9/5/5/4 columns → "Set operations can only apply…" | yes |
| 4 | `emit_sweep_sql_qullamaggie` | lookback ~231 sessions vs the `LAG(close, 252)` it needs → **the whole RS book empty** | **no** |
| 5 | `emit_sweep_sql_stockbee` | a `UNION ALL` takes its column names from the first branch → one metric published under another's header | **no** |

Defect 5 is the worst. SMCI surfaced as a **+93.94%** move; it was really a **93.9%
close-location-in-range** — its true session move was **+7.34%** ($32.69 → $35.09). The
Anticipation rows were worse: their `trend_intensity` was published under the header
`volume`. A screen that cannot be trusted about *what a number means* is worse than one
that returns nothing.

Defect 4 is the most dangerous, because an empty book is indistinguishable from a quiet
tape. A reader seeing "no RS leaders today" would have concluded the market was flat.

**Fixes applied** (this commit): the lookback is now *relative* to the target date
(430 calendar days ≈ 296 sessions) instead of hardcoded, so it cannot silently rot again;
every `UNION ALL` branch emits an identical, explicitly named column set; every division
carries `NULLIF()`; the market-cap floor is applied *inside* each sweep query.

---

## 4. The guard that was missing

A guard that only runs when the database is reachable is a guard that does not always run.
shibui answered **HTTP 429 with `retry-after: 2177`** for the whole session from 08:47 UTC
on 2026-11-03 — a daily quota wall, shared with the other routines that query it.

So the new `scripts/sql_lint.py` checks the SQL's **shape** offline: no database, no
third-party dependency, under a second. It fails on

| Code | Check |
|---|---|
| L001 | CTE list separator missing |
| L002 | UNION branches with different column counts |
| L003 | UNION branches with different column NAMES |
| L004 | an identifier that resolves to nothing |
| L005 | a `LAG`/`LEAD` offset wider than the query's own lookback window |
| L006 | a missing `LIMIT` |
| L007 | a division without `NULLIF()` |
| L008 | date arithmetic on a bare string literal |

**It was validated by running it against the pre-fix emitters**, where it catches 10
errors spanning all five defect classes. `scripts/testdata/broken_sweep_sql.py` keeps that
SQL as a fixture and `smoke_test.py` *asserts* the linter still finds every class — so the
guard cannot silently stop working either.

---

## 5. Everything else that changed

| Change | Why |
|---|---|
| `same_day_prints.py` | The screen describes yesterday's tape; the trader acts on today's. Adds the official 4:00 PM print, labelled `official_close` vs `last_trade` with the print's date, so a stale print is visible. |
| `reconcile.py` | A screen that is never scored becomes a screen nobody trusts. 1/3/5-session forward returns vs the benchmark, with sessions that have not happened reported as pending, not zero. |
| `_results.json` | Downstream routines were parsing prose. Now they parse a schema. |
| `screen.py cache` / `plan --use-cache` | A repeat fire no longer spends ~20 MCP calls. The cache invalidates itself when shibui's resolved data date moves. |
| Five stylist buckets, explicit | The TradingView volume-breakout screen counts as **Jeff Sun** (his volume proxy), so one stylist's two screens cannot read as two independent opinions. |
| Tier-A capped at 8, truncation reported | `references/tiering.md` said 8; the code did not cap. Now it does, and `_results.json` reports the untruncated pool. |
| Cloud runtime data paths documented | The spec's data-source table named five stdio MCPs that do not exist in the Cloud runtime, and its tier-2 fallback chain was entirely unreachable: Finviz is Cloudflare-403 and Yahoo's JSON is 429. |
| CANSLIM rebuilt on shibui | TradingView's `earnings_growth_quarterly_yoy` / `sales_growth_quarterly_yoy` are null for **every** US name — the spec's filter matched 0 of 2,623 names above $1B. Rebuilt on `fundamentals_derived_quarterly.eps_growth_yoy` / `revenue_growth_yoy`. |
| `references/filters.md` corrected | It documented SQL against a fictional `shibui.daily` table with columns that do not exist (`close_252`, `sma_150`, `institutional_holders_count`, `avg_volume_30d`). It now points at the emitters as canonical and carries a concept→real-expression table. |
| `scripts/breadth.py` reference removed | The spec pointed at a script that is **not in the repository** (404). The breadth SQL lives in `screen.py`. |
| Stale tier thresholds fixed | The spec's §4 said Focus ≥3 / Tier-A ≥4 while the code and `references/tiering.md` both said ≥2 / ≥3. |

---

## 6. The pre-filter leak (a finding worth its own note)

The market-cap floor was applied *after* the merge, so names with no valuation row
survived as "unknown". On 2026-10-28 that was 67 of 530 candidates: **52 ETFs** (mostly 2×
and 3× leveraged products), **14 preferred shares** and one microcap.

Leveraged ETFs clear a momentum screen purely through leverage. Two 2× TSLA ETFs
(TSLG, TSLL) had reached **Tier-A** before the floor was enforced — and TSLG/TSLL were
still on the platform's Tier-A board when the run finished. The floor is now inside the
sweep SQL, so non-equities cannot reach the tiering stage at all.

---

## 7. Live validation — done, and it caught a regression the offline lint could not

The shibui quota wall (HTTP 429, `retry-after: 2177`) cleared at 09:28 UTC, and every
emitter was then executed live against the real server for data date 2026-10-27:

| Emitter | Rows | Time | Result |
|---|---|---|---|
| `prefilter` | 200 | 1.3 s | ok |
| `sweep_stockbee` | 130 | 10.9 s | ok |
| `sweep_qullamaggie` | 69 | 15.1 s | ok — **RS book 55 rows, non-empty** |
| `sweep_peoplewish` | 200 | 2.7 s | ok |
| `breadth` | 7 | 3.8 s | ok |

Every per-origin column set was checked for **name** uniformity and **value** semantics:
the A-branch `chg_pct` is a real ≥4% move, the B-branch `dcr_pct` is a real 0-100
close-location (and its `chg_pct` is NULL — the defect-5 collision is gone), the K-branch
`trend_intensity` ≥ 1.05 with `base_width_pct` ≤ 8% and `volume` NULL, the Qullamägi
branches carry gap_pct / gain_5d / loss_5d in their own slots, and `atr_252d_avg` is a
genuine trailing average instead of a copy of `atr_14`. All 336 sweep candidates have a
valuation row and clear the $300M floor — the non-equity exclusion holds end to end.

**The live run caught a regression the offline lint could not.** The market-cap floor
moved *into* the sweep SQL, and the `mc` CTE I wrote for it took the latest valuation row
per symbol with `QUALIFY ROW_NUMBER() ... = 1` over `date <= '<d>'` — which scans all
**18.9M** valuation rows on every sweep. Stockbee and Qullamägi blew past the bridge's
90-second timeout. Two changes fixed it:

- `mc` now joins a **single date**, `MAX(date) <= '<resolved>'`. `valuation` has a primary
  key on `(symbol, date)`, so one date is one row per symbol; the lookup is ~8× cheaper and
  is also *safer*, because it cannot admit a stale cap.
- The Qullamägi sweep joined `technical_indicators` for an `atr_14` that **no branch used** —
  a 3M-row join for a column that was thrown away. Dropped.

**The lesson worth keeping:** an offline linter proves the SQL's *shape*, not its *cost*.
A query can be perfectly well-formed and still be too slow to run — and here the slowness
was invisible until the database was reachable. The lint now checks the shape; only a live
run checks the clock. Note too that the linter earned its keep during this very fix: it
caught the dangling `t.` alias left behind by the join removal, before it could reach the
server.
- `references/crons.md` still carries the local-Mavis schedule table; it should note the
  Cloud runtime's slot.
- The `finviz-url` builders remain in `screen.py` although Finviz is unreachable from the
  Cloud egress. They are still correct for the local runtime, so they stay — but the
  fallbacks doc now says plainly that tier 2 is unavailable in the Cloud.
- ~~The Sunday-only IPO and high-short-float refreshes have no shibui equivalent and no
  reachable Finviz fallback.~~ **Wrong, and now fixed** — see §8.

---

## 8. A stale note, corrected: the IPO and short-float refreshes DO have a shibui source

This audit originally recorded that the Sunday-only IPO and high-short-float refreshes had
"no reachable source in the Cloud runtime". That was **wrong**, and the way it was wrong is
worth recording.

The claim came from the skill's own §N/§O, which said shibui has no IPO-date or
short-interest columns and routed both screens to Finviz. I had verified that **Finviz was
403** and then concluded the screens had no source — without ever testing whether shibui
actually had the data. The note was stale; shibui's schema has grown since the skill was
written. Verified live on 2026-11-03:

| Screen | shibui source | Verified |
|---|---|---|
| Recent IPOs | `shibui.general_info.ipo_date` | 20 recent IPOs returned (MSGR 2026-10-21, VYLR 2026-10-01, ACCV 2026-09-30 …) |
| High short float | `shibui.ownership_stats.short_percent_float` | 5,388 of 5,868 rows populated (~92%); 384 names over 20%; top of list VG 83.8%, MMED 63.8%, LCID 57.2% |

`emit_weekly_sql` was a stub that returned the literal string `fallback_to_finviz`. It now
emits real SQL for both screens in one call — 80 rows in 1.7 s — and the IPO and
short-float branches carry the same explicit column set, ordered IPOs newest-first and
short float highest-first.

**TradingView genuinely cannot serve the short-float screen**, so it was never the answer:
every short column it exposes (`short_ratio`, `short_percentage_of_shares_outstanding`,
`short_float`, `short_interest`, `days_to_cover`) comes back **null for every US name** —
the same failure class as its earnings-growth columns.

Two caveats carried into the spec: `ownership_stats` is a **current snapshot** with no
`date` column, so the short-float screen cannot be replayed for a past date and there is no
`days_to_cover`; and `percent_institutions` can exceed 100% on the same rows (RH 105.2%,
WOLF 139.0%), so it is not usable as a sanity filter without a tolerance.

**The lesson is the one this whole audit is about:** a note in a spec is a *claim*, not
evidence. The 2026-10-28 run proved the spec wrong five times about its own SQL; this
proved it wrong twice more about its own data sources. Neither would have surfaced without
running the query — the same discipline that caught the five SQL defects caught these two
false claims.

---

## 9. Reverting

```
git revert <this commit>   # the live-validation performance fix
git revert b6d711e          # the repair + guard
git checkout 9db5860 -- cloud-prompts/skills/stock-screener-suite/   # previous skill state
```

The change is one commit touching only `cloud-prompts/skills/stock-screener-suite/`, so
reverting it cannot affect any other routine's prompt or artifact.


---

## 10. Run note — the 2026-11-04 18:30 ET fire: the Nasdaq `/info` after-hours flip, and what an end-of-day breadth read must measure

**Date:** 2026-11-04 · **Fire:** cron #09, 18:30:54 ET · **Artifact:** `daily-screens/2026-11-04/daily-sweep.md`, `breadth.md`, `_regime.json`

Two findings came out of the run, both about which number an end-of-day artifact is allowed
to publish. The skill spec was amended in the same commit (additive, no behaviour removed),
so the next fire picks them up with no `cron_update` and no prompt-drift risk.

### 10.1 The Nasdaq `/info` `primaryData` is the after-hours print, not the official close

`same_day_prints.py` (§2.5) fetches the official 4:00 PM print from Nasdaq's `/info`. The
routine assumed `primaryData.lastSalePrice` is that print. Measured on 15 Focus/Tier-A
names on 2026-11-04, after the close:

| Name | Nasdaq `primaryData` | Nasdaq `secondaryData` | TradingView `close` | Official close is |
|---|---|---|---|---|
| MRNA | $256.86 | $258.38 | 258.38 | `secondaryData` |
| ECG | $81.43 | $79.71 | 79.71 | `secondaryData` |
| KVYO | $19.79 | $21.36 | 21.36 | `secondaryData` |
| FTAI | $182.24 | $179.58 | 179.58 | `secondaryData` |
| GKOS | $250.80 | $246.71 | 246.70 | `secondaryData` |

`primaryData.lastTradeTimestamp` read **"Nov 4, 2026 6:36 PM ET"** on every pull — that is
the after-hours tape, not the 16:00 close. `secondaryData` is the official close, and
TradingView's `close` equals it on **15 of 15** names (the one-cent GKOS gap is rounding).

So: for an end-of-day artifact, `primaryData` is the wrong field. Use `secondaryData`, or
TradingView's `close`, which agrees with it and costs no per-name HTTP call — the bulk of
the "today" columns can come from the single TradingView call and Nasdaq becomes the
verification pass rather than the data pass. Any same-day-print column must state which
field it used, or a reader cannot distinguish a settled close from after-hours drift.

### 10.2 An 18:30 ET breadth read cannot be measured by shibui's breadth SQL

The skill spec's §3 says breadth comes from the shibui SQL. At 18:30 ET that SQL resolves
to the **prior** session (`SELECT MAX(date) ... WHERE date <= '<cron_date>'` →
`2026-11-03` on the 2026-11-04 fire), because shibui is T+1. An end-of-day artifact is
supposed to describe the close the trader just saw, so the published breadth has to come
from the settled close of the cron day — which the TradingView scanner has, along with
`SMA20 / SMA50 / SMA200 / ATR` for the same universe filter.

The two feeds disagree in a way that is easy to misread as a contradiction:

| | shibui 2026-11-03 | TradingView 2026-11-04 |
|---|---|---|
| Large-cap population | 905 | 1,001 |
| % above 20-DMA | 63.98% | 71.00% |
| Index ETFs above 20-DMA | 40% (2 of 5) | 40% (2 of 5) |

They are two different series (different populations AND different sessions), not two
readings of one series. The spec now requires the settled-close number to be the published
one and the shibui number to be published as the T+1 cross-check.

### 10.3 Two small defects caught in the run itself

- The per-stylist writer keyed on the *slug* (`jeff-sun`, `ariel-hernandez`) while the
  stylist buckets are `jeff_sun` and `hernandez`, so those two files were written EMPTY
  while every count looked plausible. Silent zero rows are exactly the failure class §5 of
  this audit warns about; the guard belongs with the writer, not with the eye.
- The 5-day parabolic move (`m1`) was computed by the SQL but never exported into the
  candidate CSV, so `short-candidates.csv` / `long-reversal-candidates.csv` shipped with
  the move column missing.

- A contradiction with an existing docstring: `premarket_pull.py` states that
  "`secondaryData` holds the official close ONLY while the regular session is running; once
  the market is Closed it comes back null". Measured on 2026-11-04 at 18:36 ET — AFTER the
  close — `secondaryData` returned the official close on 15/15 names (MRNA 258.38, ECG 79.71,
  KVYO 21.36, FTAI 179.58) while `primaryData` carried the after-hours print. The docstring
  is wrong about the closed-market case. It is NOT patched here: `premarket_pull.py` belongs
  to cron #08, which runs pre-market where the primaryData/secondaryData relationship is
  different, and changing another routine's data path blind is exactly the move this audit
  warns against. Flagged for cron #08's owner.

---

## 11. Second pass (2026-11-05): the four plumbing defects the 2026-11-04 run re-shipped

**Scope:** the same routine, reviewed again after the 2026-11-04 fire. The *screening* is
fine — 2026-11-04 produced a coherent Tier-A list (8 of a 13-name pool, `tier_a_truncated:
true` recorded). The **plumbing** was broken in four ways, three of them silent. All four
are fixed here, and all four now have a guard that makes them impossible to ship again.

### 11.1 The per-branch `LIMIT` was still capping every book

**Evidence.** The 2026-11-04 artifact publishes its own screen-origin counts:

```
TV_volume_breakout 462 · G_peoplewish 200 · jeff_sun_canslim 85 · A_stockbee_4pct 50
B_stockbee_ep9m 50 · C_qullamaggie_rs 44 · K_stockbee_anticipation 30 · H_hernandez_theme 30
```

`A_stockbee_4pct` and `B_stockbee_ep9m` are **exactly 50**, and `K_stockbee_anticipation` is
**exactly 30** — those are the caps in the emitters (`LIMIT 50` at L391/L403, `LIMIT 30` at
L417, `LIMIT 60`/`LIMIT 30`×3 at L479/L493/L506/L520), not screen outcomes. The 2026-11-03
run had already measured the real numbers: **233** names pass the 4% breakout and the cap
kept 50; **236** pass EP9M and the cap kept 50. The 2026-11-03 artifact says so in its own
method section: *"All four branches were re-run uncapped (in two batches each where needed)
so the published books are complete; the Tier-A list differs from a limit-capped run."*
The 2026-11-04 run went back to the capped emitters. The fix had never landed.

**Why it shipped twice.** `sql_lint.py` had `L006` (a top-level SELECT *without* a LIMIT)
and **nothing** against a per-branch one. The gap was in the lint, not only in the SQL.

**Fix.** No branch carries a `LIMIT` any more. The outer `LIMIT 200` stays — shibui rejects
a query returning more than 200 rows. Every branch now carries `rows_passing`
(`COUNT(*) OVER ()` computed *inside* the branch, before any cap applies), which is the
true number of names that passed that branch's filter. `consume` asserts
`rows_kept == rows_passing` per branch and **writes nothing at all** when they differ.

Because shibui returns at most 200 rows per query, a branch that passes more than 200
names has to be **paged**, not capped: `scripts/screen.py emit-branch <branch> <date>
--offset 200` and so on, until the rows collected equal `rows_passing`. The `ORDER BY` is
always total (sort key + `symbol`), so pages never overlap or drop a row.

This also removed two caps the audit brief did not mention: the weekly refresh's `ipo`
(`LIMIT 50`) and `hsf` (`LIMIT 30`) CTEs.

**New lint rule `L009`** — *a CTE carrying a per-branch `LIMIT` smaller than the outer cap
is a silent truncation risk.* Run against the OLD emitters it reports **9** issues — three
in Stockbee, four in Qullamägi, two in the weekly refresh. Run against the new emitters it
reports zero.

### 11.2 `compute_regime()` read the wrong key — `late_cycle` could never fire

**Evidence.** The breadth SQL emits the index identifier as **`ticker`**:

```sql
SELECT 'index_atr_extension', ticker, close, sma_20, sma_50, atr_14, atr_252d_avg, …
```

`compute_regime()` read `row.get("symbol")` (L1310) — and only that. Executed against the
exact row shape the SQL returns, `atr_extensions` came back `{}` and `late_cycle` came back
`false` for an input where QQQ was **14.2% above its 50-DMA**, against the flag's own 6%
threshold. The sibling `tier_candidates` already read `row.get("symbol") or
row.get("ticker")`; `compute_regime` was never given the same fallback.

The 2026-11-04 run published `late_cycle: false` with `atr_extensions` populated (SPY
−0.03%, QQQ −4.37%, RSP +3.88%, IWM +0.29%) — that run took the **TradingView** path
rather than the shibui SQL path, so the flag was merely *correct by luck*. **The shibui
path still could not fire it.**

**Fix.** The key chain is now `symbol or ticker or etf` (the last one covers the documented
pre-aggregated shape in `references/agent-output-shape.md`). A regression test feeds
`compute_regime()` a row with `extension_pct > 6` and asserts `late_cycle is True` — *a
flag that can only ever be `false` must have a test that proves it can be `true`.*

### 11.3 `_regime.json` changed shape between 2026-11-03 and 2026-11-04 — a silent contract break

**Evidence.**

| File | Shape |
|---|---|
| `daily-screens/2026-11-03/_regime.json` | **flat** — `{"size_cut_pct": 0, "uncertainty": false, "late_cycle": false, "breadth_pct_spx": 65.19, "index_below_20sma": true, "vix": 20.83, …}` |
| `daily-screens/2026-11-04/_regime.json` | **nested** — `{"regime": {"size_cut_pct": 0, …, "atr_extensions": {…}, "_note": "…"}}` |

Any consumer reading `d["late_cycle"]` now gets a **KeyError**; any consumer doing
`d.get("late_cycle")` gets `None` — indistinguishable from "not computed". The 2026-11-04
artifact's own `breadth.md` publishes the *flat* shape in its code block while the JSON on
disk is nested: the two disagree inside the same routine.

**Fix.** One shape, pinned: **FLAT**, with `_schema: 2` and `_note` as *siblings* of the
regime fields (never parents). All eight regime keys are required. `scripts/screen.py`
validates the payload against the declared schema **before** writing it, rejects the
nested shape explicitly, and ships `read_regime()` so a consumer reading a legacy nested
file still gets a flat object. The schema is published in `SKILL.md` §3 and the consumer
directive in `references/crons.md` was updated in the same change.

### 11.4 The guards, and proof they bite

`scripts/smoke_test.py` gained six guards:

1. **no per-branch `LIMIT` in any emitted SQL** (`L009`), across the group emitters *and*
   every per-branch emitter;
2. **every sweep branch reports `rows_passing`**;
3. **`compute_regime()` returns `late_cycle=True`** for an index 6%+ above its 50-DMA, and
   reads the `symbol`/`ticker`/`etf` key chain;
4. **`_regime.json` has one declared shape**, a schema version, a writer that refuses a
   nested payload, and a reader that unwraps a legacy one;
5. **the coverage assertion** is silent when a branch is complete and fails loudly when it
   is short;
6. **the cap signature** — a kept count landing exactly on 30 / 50 / 60 / 200 — is
   recognisable.

**Proof the guards bite** (fault injection into a throwaway copy, then discarded):

| Reintroduced defect | Result |
|---|---|
| `row.get("symbol")` only | **3 checks go red** — `late_cycle` returns `False`, `atr_extensions` is `{}` |
| `LIMIT 50` back inside `A_stockbee_4pct` | **3 checks go red** — two lint checks + the L009 guard |
| the nested `{"regime": {…}}` payload | **1 check goes red** — the schema guard |

### 11.5 What did NOT change

- **No gate value and no stylist definition.** The screening is fine; only the plumbing was
  broken.
- **The outer `LIMIT 200` stays.** shibui rejects a query returning more than 200 rows.
- **The 2026-11-04 settled-close breadth change stays** (TradingView's settled close for the
  EOD read, shibui as the T+1 cross-check). It is correct and it is published in the spec.
- **No dated file is written to `daily-screens/breadth/`** — that path stays forbidden for
  #09 and #10, and the spec's stale sentence pointing at it stays corrected.
- **The slug-vs-bucket split stays fixed** — the files are slugs (`jeff-sun.md`,
  `ariel-hernandez.md`), the buckets are not (`jeff_sun`, `hernandez`).
- **The cron #09 PROMPT was not touched.** Every change above is a *procedure* change, and
  the prompt fetches the skill spec at run time — so the next fire inherits all of it with
  no `cron_update` and no byte-drift risk.

---

## 12. A MISSING INPUT WAS RENDERING AS A POSITIVE SKIP-FLAG (2026-11-05)

**Found during the 2026-11-05 end-of-day sweep.** Every one of the 1,407 candidates in
`_results.json` carried `flag_ma_shrink_5d: true`, and the per-stylist markdown printed that
flag on every row. It was not a signal — it was an artefact of the defaults in
`scripts/screen.py::_compute_skip_flags`:

```python
rng5 = d.get("range_5d", 0)        # missing key -> 0
rng20 = d.get("range_20d", 1e-9)   # missing key -> 1e-9
if rng20 > 0:
    flags["ma_shrink_5d"] = rng5 < 0.5 * rng20     # 0 < 5e-10 -> TRUE
```

A row that carries **no** range data evaluated to `True`. The same shape applied to
`wicky_breakout` (`body = abs(close - open)` used `0` for a missing `open`, so the body
became the whole close price) and to `atr_shrink` (missing inputs defaulted to `False`, i.e.
a flag that could never fire).

### The fix

A flag is now **True / False / None**, and `None` means *not computable from this row's
fields* — a third state that is never rendered as a positive signal:

- `atr_shrink` → `None` unless BOTH `atr_14` and `atr_63_median` are present.
- `wicky_breakout` → `None` unless `open`, `high` and `low` are all present AND a
  `rvol_close` exists; `None` rather than a body computed from a missing `open`.
- `ma_shrink_5d` → `None` unless BOTH `range_5d` and `range_20d` are present.
- `day2_no_follow`, `no_reclaim_15m`, `second_bite_d2` → `None` (they need day-2 data and
  a live tape; `False` would claim a clean signal that was never measured).

`_results.json` and every markdown writer publish only **truthy** flags, so a `None` flag
simply does not appear — it is never shown as `False` either.

### Why it matters beyond the one artifact

A flag that fires on every row is indistinguishable from a broken pipeline, and it is
exactly the "silent zero that reads like a quiet tape" failure class this suite keeps
guarding against — in mirror image: a **silent TRUE**. A reader who saw `ma_shrink_5d` on
all 1,407 rows could not tell a real screen output from a default, and the flag column
carried no information at all.

`scripts/smoke_test.py` passes against the patched script (all guards green), and the
2026-11-05 artifact was regenerated with it: no candidate carries a skip-flag, and the
tier lists carry only the two flags that are genuinely computable from the 2026-11-04 OHLC
(`wicky_breakout`, `ma_shrink_5d`).
