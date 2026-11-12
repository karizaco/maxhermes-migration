# IMPROVEMENTS — 2026-11-12: the scanner pull's completeness test is a SET test, and it now lives where every routine can see it

- **Date:** 2026-11-12
- **Scope:** every routine that builds a TradingView `america` scanner body at run time — #02, #04,
  #07, #20, #23 — and the shared files that carry the rule.
- **Evidence base:** the 2026-11-12 cron #07 fire (which found the defect), plus live measurements
  taken the same day against the live scanner.
- **Status:** fixed in run-time-fetched files only ⇒ **no `cron_update`, no prompt drift, no redeploy**
  of any deployed prompt. The deployed cron #07 prompt (sha256 `7e604382…`) was NOT touched by this
  work; the #07 changes landed separately.

---

## 1. The defect, measured on the live scanner

The scanner's page order is **not stable between two requests**. A pull that PAGES an unsorted (or
live-column-sorted) result set therefore **overlaps and misses names**, and the usual completeness
check cannot see it:

| pull | rows returned | distinct names | `totalCount` | verdict |
|---|---:|---:|---:|---|
| `range:[0,20000]` + `range:[20000,20155]`, **no sort** | 20,000 + 155 | **20,001** | 20,155 | **154 names missing, no error** |
| the same, `range:[0,10000]` + `[10000,20155]`, `sort {"sortBy":"name","sortOrder":"asc"}` | 10,000 + 10,155 | **20,155** | 20,155 | complete |
| cron #20's shape: `range:[off,off+6000]`, `sort {"sortBy":"close","sortOrder":"desc"}` | 4 pages | 20,342-20,345 | 20,347 | **2-5 names missing, and two IDENTICAL pulls returned DIFFERENT name sets** (IVRO, LYCA in one run only; AGCCF in the other) |

**`totalCount == rows returned` is NECESSARY BUT NOT SUFFICIENT.** It passes every one of the broken
pulls above. The real invariants are:

- **the pages are DISJOINT**, and
- **their UNION equals `totalCount`**.

Cron #17 measured the same defect at scale on 2026-11-06: a 9-page offset pull of the US cash
universe returned **13,500 rows containing only 8,689 unique symbols** — and *the response looks
healthy (rows ≥ `totalCount`), so no row-count check catches it*.

**The fix is a STABLE pagination key.** Sorted by `name`, the same pull returns `totalCount` exactly,
every time. A sort on a live column (`close`, `volume`, `change`) is NOT stable.

## 2. The second trap: the row key

A scanner row is `{"s": "NYSE:BW", "d": ["BW", "NYSE", …]}` — the **bare ticker is `d[0]`**, while
`s` carries the venue (`NYSE:`, `NASDAQ:`, `AMEX:`, `OTC:`). A pull indexed by `s` reports **every
US ticker as MISSING**, which is indistinguishable from an empty universe and is a silent false
negative.

## 3. The third lever: if you know the tickers, pull the tickers

The `in` operation rejects a list `right` (400 `Expected one value, passed 2`) — but the categorical
**`in_range` accepts a LIST**:

```json
{"columns": ["name","exchange","average_volume_10d_calc","market_cap_basic"],
 "filter": [{"left":"name","operation":"in_range","right":["BW","FRVO",…]}],
 "range": [0, len(names)+5], "sort": {"sortBy":"name","sortOrder":"asc"}}
```

Measured 2026-11-12 on a 12-name roster: **HTTP 200, `totalCount` 12, 12 rows, ONE call** — against
20,155 rows for the universe pull. `relvol_screen.py`, `premarket_universe.py`, `premarket_pull.py`,
`preopen_capture.py` and `preopen_feed.py` already do this.

## 4. Where the rule now lives (and why that moved)

The corrected rules were written on 2026-11-11 into **RUNTIME-CONTRACT §2a-bis** and into the suite
skill's §7 — but §7 is **cron #07's section**, and RUNTIME-CONTRACT is **not fetched by most
routines** (they fetch PROMPT-BLOCKS + their own skill). So the rule reached exactly one routine.

**PROMPT-BLOCKS is the one file every routine fetches**, and its `## RUNTIME DATA-SOURCE CONTRACT`
section is where the source ladder lives. The four rules (the one `sort` form, the SET completeness
test, the bare-name key, the targeted pull) are now there, with a pointer to the validated client.

`_shared/tv_scan.py` is now **`TV_SCAN_V2`** with a `pull` mode:
`pull --names` = the one targeted call plus a **coverage assertion** (a requested name that never
comes back is an ERROR), `pull --body` = a paged pull asserting disjointness and the union against
`totalCount` (exit 4 on either). Both write rows keyed by the **bare** ticker. Both markers are in
the file, so a fetch ladder demanding the old token resolves to the new file, and one demanding
`TV_SCAN_V2` cannot be satisfied by an older copy.

## 5. What changed, per routine

| routine | was | now |
|---|---|---|
| **#04** `tools/reversal_bullish.py` | `tv_scan()` did `json.load(fh).get("data", [])` — it **DROPPED `totalCount`**, so a truncated screen was undetectable | captures `totalCount`; the screen **refuses to publish a short book** (`TRUNCATED SCAN`). The filtered universe is 951 names against a 2,000 cap (49% headroom) ⇒ latent, now guarded |
| **#20** `fetch_eod_venue.py` | carried a **DEAD** TradingView universe pull (added 2026-11-12, never wired in) whose shape lost 2-5 names non-reproducibly; `--no-tv` was a **no-op flag** | the dead pull is **deleted** (TV corroborates the BAR, not the venue — 99.4% vs 67.8% — so it must not confirm the published close); `--no-tv` stays accepted but is documented as an honest no-op |
| **#20** `eod-watchlist-snapshot/SKILL.md` | the ADR/cross-venue universe pull was described as **"13,376 rows in three calls"** — a PAGED pull the agent builds at run time, with no completeness check | one call with `range [0,20000]` (the scanner's cap), sorted by `name`, and an assert that the distinct names equal `totalCount` — a failed pull is a failed pull |
| **#02** `asia-pre-market-reactions/SKILL.md` | the per-market pull used a **hardcoded `range:[0,600]`** while the row count is not — on a violent session the tail of the movers was silently cut | `range:[0,20000]`, and the merge block now **refuses** a truncated direction (`TRUNCATED PULL`) or a merged mismatch (`MERGED MISMATCH`) instead of publishing a short mover list |
| **#23** `agentic-post-market-brief/SKILL.md` | no completeness rule at all | the four rules, inline, next to the source table |
| **#07** | the hand-built universe pull (fixed and deployed on 2026-11-11) | unchanged by this work |

**#10 needs nothing** — its intraday breadth never queries the scanner (shibui SQL + CBOE + bridge;
its published artifact says "TradingView scanner — not attempted"), and the EOD breadth inside
cron #09's sweep goes through `daily_sweep_engines.py::fetch_universe()`, which already pages on a
stable key, DEDUPES through a `seen` set and asserts `len(rows) == totalCount` ("TRUNCATED SCAN …
Refusing to publish a short book"). **#92 needs nothing** — its movers come from the bridge's
`top_movers`, and the scanner is used only for a TARGETED enrichment pull.

## 6. The guard

`tools/test_tv_pull_completeness.py` (20 checks, hermetic — no network): cron #04 refuses a
truncated screen and screens a complete one; cron #20's dead pull is gone and `--no-tv` is still
accepted; cron #02's merge block compiles and carries both guards. It fails if any of those is
reverted.

**Also fixed in this pass:** the repo's own `tools/test_tv_scan_contract.py` was **RED on arrival**
(1-3 of 37 checks failed on 6 of 6 runs) because its HTTP stub never read the request body — the
close carried an RST and urllib intermittently got a `transport` error instead of a result. Fixed;
8 of 8 runs green. A guard that fails randomly trains the fleet to re-run it until it goes green.

## 7. Reproducing the measurement

`/workspace/tv-pull-measurement.py` pulls the US universe twice per sort and prints the missing
count, whether the two runs agree, and the stable-sort comparison. It is the evidence for §1.

---

## Cross-references

- `cloud-prompts/_shared/RUNTIME-CONTRACT.md` §2a-bis — the fleet contract (now carrying cron #17's
  13,500/8,689 evidence).
- `cloud-prompts/_shared/PROMPT-BLOCKS.md` → *The TradingView scanner's request shape* — the rules as
  every routine now sees them.
- `docs/IMPROVEMENTS-cron17-us-stocks-in-play.md` §1 — cron #17's original measurement.
- `docs/IMPROVEMENTS-cron07-focus-rvol.md` — cron #07's 2026-11-11/12 entries (the two traps and the
  TV_SCAN_V2 client).
- `docs/IMPROVEMENTS-cron20-eod-watchlist.md` — cron #20's own history.
