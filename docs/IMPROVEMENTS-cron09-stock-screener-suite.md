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

## 7. Open items

- **Live re-validation against shibui is deferred.** The server was rate-limited for the
  whole session (HTTP 429, `retry-after: 2177`). The SQL was validated offline and by
  construction; the live run is queued behind the quota wall.
- `references/crons.md` still carries the local-Mavis schedule table; it should note the
  Cloud runtime's slot.
- The `finviz-url` builders remain in `screen.py` although Finviz is unreachable from the
  Cloud egress. They are still correct for the local runtime, so they stay — but the
  fallbacks doc now says plainly that tier 2 is unavailable in the Cloud.
- The Sunday-only IPO and high-short-float refreshes have no shibui equivalent and no
  reachable Finviz fallback. They need a source or an explicit "not available" state.

---

## 8. Reverting

```
git revert b6d711e          # the repair + guard
git checkout 9db5860 -- cloud-prompts/skills/stock-screener-suite/   # previous skill state
```

The change is one commit touching only `cloud-prompts/skills/stock-screener-suite/`, so
reverting it cannot affect any other routine's prompt or artifact.
