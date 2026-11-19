# IMPROVEMENTS — cron #20 (eod-watchlist-csv-snapshot)

Running notes on what the routine's data path does in the Cloud runtime. Written by the
2026-11-05 fire. The routine's own skill spec is `cloud-prompts/skills/eod-watchlist-snapshot/SKILL.md`;
this file records the findings, the skill spec carries the rules.

---

## 1. The exchange's `/info` settlement stamp is NOT proof that its PRICE is the close (2026-11-05)

**The defect.** On the 2026-11-05 session, `GET api.nasdaq.com/api/quote/{SYM}/info` returned
`secondaryData.lastSalePrice` with the stamp **"Closed at Nov 5, 2026 4:00 PM ET"** — but the
VALUE was a **pre-auction print from roughly 15:57 ET**, for every name checked:

| name | Nasdaq `secondaryData.lastSalePrice` | true 16:00 ET close | gap |
|---|---|---|---|
| AAPL | $345.1551 | **344.17** | +0.29% |
| MSFT | $537.705 | **535.93** | +0.33% |
| NVDA | $182.29 | **181.60** | +0.38% |

Two independent reads agree on the lower number and one vendor disagrees with them, so the
**stamp is not the value**. The values also carry 3–4 decimals on names whose tick is a cent
(345.1551, 537.705) — the signature of a derived snapshot, not of a trade print — and each one
equals that name's ~15:55–15:57 ET intraday print.

**How it was caught.** The published close is the consolidated 16:00 ET auction print. It was
validated against an independent quote service (CNBC / CTA), which stamped `last_time`
`2026-11-05T16:00:00-0500` and matched exactly on 36 of 41 sampled names (the other 5: four
penny names differing by <0.1%, and one preferred line where CNBC resolved the COMMON line
because of its own symbol form).

**The rule.** A settlement STAMP is not a price. **A vendor's close is only publishable after it
has been checked against at least one independent reading** — the Yahoo regular-session final
bar (the synthetic last bar, `O=H=L=C`, volume 0, which carries the official close) and the
independent quote service are the two cheap checks. If the exchange's value disagrees with the
independent reading by more than ~0.6%, the exchange value is stale, whatever its stamp says.

**The tell, in one line:** if the vendor's close is ABOVE the last minute's traded price by more
than a tick and the session was falling into the close, the vendor is serving a pre-auction
snapshot.

**Why this matters more than one bad session.** The 2026-11-04 file published 4,839 closes from
that same field and Cboe confirmed 16/16 of the top movers — so the field was correct YESTERDAY
and wrong today. A routine that trusts it unconditionally will publish a wrong close for the
whole universe on exactly the sessions where the two disagree.

---

## 2. Two symbol-translation bugs, both silent, both class shares

Class-share tickers are the whole difficulty: `shibui` writes `ABR-P-D`, Yahoo serves `ABR-PD`,
and Nasdaq serves `ABR^D`. Two mappings in this run were wrong and BOTH produced silent
no-data, not errors:

- **Yahoo**: `base + "-P" + rest[1:]` turns `ABR-P-D` into `ABR-P-D` (the hyphen survives), so
  ~358 preferreds never resolved. Correct: `base + "-" + rest.replace("-","")` → `ABR-PD`.
- **Nasdaq**: `base + "^" + rest[1:]` turns `USB-P-H` into `USB^-H`, so ~339 symbols returned
  "Symbol not exists". Correct: `base + "^" + rest.replace("-","")[-1]` → `USB^H`.

**The rule.** Build one mapping table per vendor and TEST it against the vendor, and never let
a fallback silently substitute a different security: a plain-base fallback (`LEN-B` → `LEN`)
returns the CLASS A COMMON line's price, which is a different security's number, not a missing
one. A resolved-but-wrong symbol is worse than an unresolved one, because it is not visible.

---

## 3. The shibui bridge's `LIMIT/OFFSET` pagination is UNSTABLE without a unique `ORDER BY`

`SELECT ... LIMIT 200 OFFSET n` returned **duplicated and missing rows** across pages: 5,463
rows fetched in 28 pages produced only 2,972 distinct symbols. Adding `ORDER BY symbol` (a
unique key) fixed it — 5,463 rows, 5,463 distinct. Without `ORDER BY` the engine's row order is
not stable between queries, so page boundaries overlap.

**Second trap:** concurrent paging makes shibui throttle. At 6 concurrent workers it started
returning empty bodies mid-sweep; **keyset pagination** (`WHERE symbol > :last ORDER BY symbol
LIMIT 200`, sequential) fetched all three tables — universe 4,896, valuation 5,463, fundamentals
5,463 — with zero gaps.

---

## 4. The daily bar's settle stamp is a bar-timestamp test, and the bar can be the prior session

`chart/{SYM}?interval=1d&range=1d` returns ONE bar. On 2026-11-05, 993 of 4,896 symbols were
still serving the **prior** session's bar at 17:00 ET, and 288 more settled on a later pass
(a second `range=1mo` sweep at ~17:35 ET recovered them). The settle test is
`bar timestamp >= 21:00Z` on an EST date — **never a hardcoded offset**, derive it.

---

## 5. The numeric formatter (4 sig figs, integers >= 100000) — regression-tested, still exact

The US file's rule: prices to 4 significant figures with trailing zeros stripped, **except
values >= 100000, which keep full precision** (`869710.37`, not `869710`); `volume` and
`market_cap` are integers; `change_pct` and `pe_ratio` are 4 sig figs. A plain `%.4g` is the
trap — it renders 830500 as `8.305e+05`.

**The test that proves the formatter:** re-format every numeric string in the PREVIOUS
published file and compare byte-for-byte. On 2026-11-05 this reproduced **35,802 of 35,802**
strings from `us-eod/2026-11-04.csv`. Keep running it every fire — it is the only check that
catches a silently changed formatter.

---

## 6. The vendor's `LIMIT`-style pagination and the `general_info` universe are stable — but the
cap carrier is not a heuristic

The vendor (shibui `valuation`) stamps its company-level cap on ONE class row per company and
leaves the siblings null. **The carrier is the vendor's own row** — never re-derive it by volume
(LILA carries the cap over LILAK despite 4× the volume). On 2026-11-05 the vendor's rows were
dated 2026-11-04 (its EOD ingest lags a session), so each cap was **rescaled by today's
close-to-prior-close ratio**; preferred rows carry no cap at all, because every quote service
reports the ISSUER's common-share count on a preferred line.

The 3-way cap vote (vendor / quote service / exchange screener) resolved 4,506 populated caps:
3,810 kept the vendor's figure, 671 re-stated from the quote service, 25 from the exchange
screener, and 282 rows where two independent sources agreed with each other and not with the
vendor.

---

## 7. Run shape that worked (2026-11-05, 16:01 ET → ~19:00 ET)

window check → skill fetch → shibui universe/valuation/fundamentals (keyset, sequential) →
Nasdaq `/info` sweep 4,896 symbols (96 threads, ~6 min) + a 340-symbol class-share fix-up →
Yahoo `v7/finance/quote` batch (123 calls, ~80 s) → Yahoo chart daily-bar sweep (48 threads,
~7 min) → a second pass for 290 unsettled rows + a `range=1mo` re-sweep for 288 more →
TradingView america scanner (20,196 rows, 2 calls) → Nasdaq bulk screener (1 call) →
CNBC/CTA cross-check (54 names) → assemble → formatter regression test → report → push
(verified by SHA-256 against `origin/main`).

**Result:** 4,896 rows, 4,840 settled closes, 4,889 volumes, 4,506 caps, 2,781 trailing P/Es,
4,528 GICS sectors, 56 rows that did not trade.

## 8. The close drifts after the close, and the bar series is not dividend-adjusted (2026-11-06)

**Result:** 4,892 rows, 4,775 settled closes, 4,775 volumes, 4,738 caps, 2,626 trailing P/Es,
4,527 GICS sectors, 117 rows with no session close. The formatter reproduced **36,034/36,034**
numeric strings of the 2026-11-05 file byte-for-byte. The independent checker passed 27/27.

**Three findings, all of them silent.**

1. **The close is not settled at 16:0x — the volume is.** A history pull at 16:01 ET and one
   at 16:10 ET agreed on every session volume (median ratio 1.0000) but **disagreed on 150 of
   4,775 session closes**. So the close keeps moving for ~10 minutes after the volume has
   frozen, and a single early pull publishes 150 closes that are not the official close. The
   fix is a second pass with the LATER bar winning. The synthetic final 1-minute bar
   (O=H=L=C, volume 0) is the close of record; the vendor's `/info` "Closed at 4:00 PM ET"
   stamp is not (2026-11-05).

2. **The price history is SPLIT-adjusted but NOT dividend-adjusted, so the bar's prior close
   is the wrong denominator for `change_pct` on an ex-distribution date.** SITE Centers
   (SITC) went ex a $3.00 special distribution on 2026-11-06: the raw bar basis reads
   **-81.3%** (3.57 -> 0.6678) and the official move is **+17.2%** (0.57 -> 0.6678). The
   quote service's `previous close` is dividend-adjusted. 37 of 4,775 rows differ by more
   than 2% between the two bases; the published `change_pct` now uses the adjusted basis, and
   the derived columns stay on the split-adjusted series (so `gap_pct` and the 52-week
   extremes inherit the artefact on a distribution date — the artifact says so).

3. **"No session bar" is not "did not trade".** 117 rows had no bar: 43 last traded earlier,
   and **70 carry a sub-second CTA closing print** that the daily-bar feed does not publish
   and that Yahoo's own quote service timestamps to an earlier session. Where the two sources
   disagree on the price AND on whether a print occurred, no close is published.

**One builder defect, fixed here:** `build_eod_report.py` aggregated the sector move with
`statistics.mean()` over a list that could contain NaN, so **one row with a close and no
`change_pct` printed `+nan%` for its whole sector** (Financials, Utilities — 22 such rows
this session). The sector read now excludes non-numeric moves. Verified on the published
artifact: the Market read table carries no `nan`.

**Run shape that worked (2026-11-06, 16:00 ET -> ~16:30 ET):** window check -> skill fetch ->
shibui `general_info` universe (4,892 rows, keyset) -> shibui `valuation` + `ownership_stats`
(the vendor's own carrier map, 4,147 caps, 4,370 floats) -> Yahoo `v7/finance/quote` batch
(4,892/4,892 in 20 s) -> Yahoo chart daily history, **two passes** (4,892 symbols each,
~30/s) -> merge (later pass wins) -> base assembly -> `eod_derive.py` -> `build_eod_report.py`
-> the checker -> push (verified byte-identical against `origin/main` via the contents API).

---

## 9. The base assembly owns the numeric format, and the settle window is ~40 minutes (2026-11-09)

Written by the 2026-11-09 fire. The routine's own skill spec carries the rules
(`cloud-prompts/skills/eod-watchlist-snapshot/SKILL.md` §2c).

**The defect the checker did not catch.** `eod_derive.py` copies the base session fields
**verbatim** — it formats only what it computes. A base assembly that handed over raw floats
therefore published `close = 1.2400000095367432`, `high = 1.2649999856948853` and
`volume = 2167698.0` — and **every existing assertion still passed (28/28)**. The archive's
numeric rule (4 significant figures, trailing zeros stripped, values ≥ 100000 at full
precision, integers for volume/cap/float) is part of the published contract, and nothing
asserted it.

Fixed in the repo, not in the prompt:
- `tools/check_eod_artifact.py` re-implements the formatter independently and asserts every
  numeric cell byte-for-byte (101,066 cells on the 2026-11-09 file, 0 drift). Fault injection
  confirmed it bites: injecting the exact defect fails the checker and names the cell.
- The base assembly must widen the high/low **in formatted space**, so the published close can
  never sit outside the published range after rounding.

**The settle window is longer than 10 minutes, and the quote price is not the auction close.**
The first history pass (16:21–16:27 ET) was still drifting; a second pass (16:31–16:39 ET)
changed the close on **2,001 of 4,775** session bars. The 1-minute final bar (`O=H=L=C`,
volume 0) is the close of record and it agrees with the SECOND pass on 48/48 sampled names.
The quote service's `regularMarketPrice` disagrees on 3 of 4 spot-checked names (AGL 113.87 vs
the auction print 114.02; AP 5.955 vs 6.00; ALG 140.74 vs 140.97) — it is a last-trade quote,
not the 16:00 ET auction print. **Take the close from the settled daily bar, keep the later
history pass, cross-check against the 1-minute final bar.** The quote service still owns the
market cap, the trailing P/E and the dividend-adjusted prior close.

**The vendor's EOD tables lag the session.** `shibui` carried no `2026-11-09` row in
`stock_quotes` (latest `2026-11-06`), so session prices cannot come from the vendor; it
supplies the universe, the carrier caps, the floats and the GICS sectors.

**The universe moved by +3 net and it is published, not absorbed:** 4,895 rows this session
against 4,892 on 2026-11-06 — AGLT, BFH-P-C, BFS-P-D and INJC now carry the vendor's
`country_iso='US'` tag, ALDF no longer does.

**Run shape that worked (2026-11-09, 16:01 ET → ~17:00 ET):** window check → skill + shared
blocks + the four derive scripts (capability marker) → one joined keyset sweep of the vendor
(33 pages, universe + carrier caps + floats + trailing P/E + sector in ONE query per page,
which keeps the metered bridge inside its daily allowance) → Yahoo `v7/finance/quote` batch
(4,895/4,895 in 9 s, cookie + crumb) → Yahoo chart daily history, TWO passes (later wins) →
base assembly (formatted) → `eod_derive.py` → `build_eod_report.py` → the checker → push
(verified byte-identical against `origin/main` via the blob API).

**Result:** 4,895 rows, 4,775 settled closes, 4,774 verified changes, 4,739 caps, 2,927
trailing P/Es, 4,527 GICS sectors, 120 rows with no session bar, 29/29 assertions passed, and
the formatter reproduced 100,037 of 100,037 numeric strings of the 2026-11-06 file
byte-for-byte.

---

## 10. The close of record is the VENUE's settled print, not the vendor's daily bar (2026-11-11)

Written by the 2026-11-11 fire. The skill's §2c said "take the close from the settled daily
bar". That holds for LIQUID names and is wrong for thin ones, and the archive itself proves
which side is right.

**The evidence.**

1. **The archive is already on the venue's basis.** `us-eod/2026-11-10.csv` carries HAIN's
   11-10 close as **0.135**. Nasdaq's own consolidated record for that session
   (`/historical`) says **0.135** — and Yahoo's daily bar for the same session says **0.14**.
   Two independent reads say 0.135; only the vendor's bar dissents.
2. **The gap is material on today's tape.** The venue's settled print
   (`api.nasdaq.com/api/quote/{SYM}/info` → `secondaryData.lastSalePrice`, stamped
   "Closed at 4:00 PM ET") and Yahoo's settled daily bar agree within 0.01% on **2,652 of
   4,774** rows, within 0.1% on **3,847**, within 0.5% on **4,460**, and differ by **0.5% or
   more on 314 rows (14 above 5%)**: MDBH 1.51 vs 1.7195, APUS 2.11 vs 2.36, TVGN 5.47 vs
   6.00, VRM 6.45 vs 6.99.
3. **CNBC/CTA corroborates the venue**, not the bar: its `last`, stamped `16:00:00-05:00`,
   equals the venue's print on every sampled name with a material gap (MDBH 1.51, TVGN 5.47,
   VRM 6.45, HFBL 22.76). **CNBC's `last` is the last trade including the extended session** —
   it is the close only when the stamp is exactly 16:00:00 (the ETFs came back stamped
   16:10/16:15 = after-hours prints). That is the trap: read the stamp, not the price.
4. **Yahoo's 1-minute synthetic final bar is not the close on thin names.** It is `O=H=L=C`
   with volume 0, but on those names it carries the session's HIGH or LOW (TVGN 6.00 = the
   day's high, against a 5.47 close). It agrees with the published close on 3,847 of 4,762
   names — a cross-check, not a price source. (The skill's §2c claim that it agrees 48/48 was
   measured on liquid names, where the last trade before the bell ≈ the auction print.)

**The rule now in the skill.** The US file's close is the **venue's settled print**; the
vendor's daily bar is the cross-check and the SERIES for the derived columns. The session
bar's close is replaced by the venue's print before the derived columns are computed, so one
row carries one price. A row whose session bar the vendor does not publish still gets the
venue's close (72 rows on 2026-11-11); a row with no print anywhere keeps empty price cells
(45 rows) — never a borrowed price.

**Three traps this run also found.**

- **The range must be the range that brackets the published close.** With the venue's close
  as the price, the vendor's daily bar brackets it on only ~4,364 of 4,774 rows; 410 rows
  take their high/low from the venue's day range (`RANGE_ADJUSTED`) and 18 publish NO range
  at all (`HIGH_LOW_UNAVAILABLE`) because neither the bar nor the venue's range brackets
  their close. A close is never published outside its own range.
- **The base assembly owns the numeric format, and the derive stage copies it verbatim.**
  A base that hands over raw floats publishes `close = 1.2400000095367432` and every other
  assertion still passes. The published scripts now do the formatting, and
  `tools/check_eod_artifact.py` asserts every numeric cell byte-for-byte.
- **The bar drifts for ~40 minutes after the close.** The 16:05 ET pass and the 16:35 ET
  pass changed the session close on **1,957 of 4,907** names. Two passes, later wins.

**Result:** 4,891 rows, 4,846 settled closes (4,812 from the venue's print, 34 from the
settled bar), 4,828 published ranges, 4,735 populated caps, 2,920 trailing P/Es, 4,521 GICS
sectors, 117 rows with no session bar, 29/29 assertions passed, and the formatter reproduced
every numeric string of the 2026-11-10 file byte-for-byte.

**Also published in this session** (the base assembly had no repo script — it was
re-improvised at every fire):

- `scripts/build_eod_base.py` (marker `EOD_BASE_V1`) — the base assembly: the numeric
  format, the price source, the range rule, the carrier-cap rescale.
- `scripts/merge_eod_history.py` — merges the two history passes, the later winning.
- `scripts/patch_eod_session_closes.py` — puts the venue's settled print into the session bar
  before the derived columns are computed.


---

## 10. The settle wall, measured and replaced with a probe loop (2026-11-12)

**The wall is a data-latency wall, and it was measured twice before anything was changed.**

| measurement | result |
|---|---|
| 2026-11-10, a 16:05 ET pull vs a 16:42 ET pull | **1,531 of 4,794 session closes moved (31.9%)**, the largest by 8.45% |
| 2026-11-11, a 16:15 ET pull vs a 16:47 ET pull | **142 of the 443 names that already had a session bar at 16:15 still moved (32.1%)** — BGMS -5.62%, APUS +4.89%, CRD-B -3.06% |
| the drift rate across the whole 16:05→16:11 window | **FLAT at 29–35%** — pulling later inside that window bought nothing |
| the LIQUID core at 16:12 ET | already final (the daily bar matched the 1-minute final bar on 39/40) |
| the universe at 16:15 ET | 90.4% of a 490-name sample carried the session bar; the rest kept moving until ~16:45 |

**So the wall is a THIN-NAME wall, and a fixed sleep is a guess.** The old shape pulled the
whole universe twice, 40 minutes apart: 9,818 requests, half of them wasted, and the second
pass was blind — it re-fetched names that had already settled and still missed names that
had not. (The 2026-11-11 run's two passes changed the close on 1,957 of 4,907 names.)

**The fix is DETECTION, not a longer sleep.** `scripts/fetch_eod_settled.py` (marker
`EOD_SETTLE_V1`) pulls the universe once (pass 1, a year of daily bars — the derived columns
come out of it) and then **probes** until the feed stops moving: every `--probe-interval`
seconds it re-pulls a **stratified sample** — half from the LOWEST-liquidity names (the thin
names are where the drift and the big relative moves live), half at random, plus every name
that moved in an earlier round or still has no bar. The probe measures **two** things per
symbol: the vendor's session bar (`range=5d`: 1.6 KB against 24.1 KB) **and the venue's
settled print** — the thing that is actually published. The loop exits on **two consecutive
quiet rounds** with the residue size unchanged (the residue never empties: ~5% of the
universe never publishes a session bar, so an empty residue is not a thing that happens).

**INVARIANT:** every symbol that ever changed is re-pulled every round until it stops
changing, so the published close is the latest value the feed ever showed.

**The confirmation source was measured, and the obvious one is wrong.** The TradingView
America scanner (2 POST calls, ~20,350 lines, ~3 seconds) agrees with the **vendor's daily
bar** on **4,497 of 4,526** rows (99.4%) and with the **venue's print** on only **67.8%** —
TV corroborates the BAR, not the venue, so using it to confirm the published close would
flag 1,450 rows where the venue is right and the bar is wrong. (It also settles LATER than
the vendor's feed: at 16:12 ET on 2026-11-11 its close matched the settled close on only
10/40 liquid names against Yahoo's 39/40.) The confirmation is therefore **Yahoo's 1-minute
final bar** — a different feed — and where that bar carries the session's high or low
instead of the close (thin names) the row is published as **`UNCONFIRMED`**, never smoothed.

**CNBC/CTA is only usable inside the session window:** outside it `last_time` degrades to a
DATE (`"2026-11-11"`) and the "stamped exactly 16:00:00-05:00" test cannot be applied — and
its `last` then carries a later print (MDBH 1.72 against the venue's 1.51).

**The cap is now published on the session's price basis.** The vendor's cap table lags the
session (its rows are dated T+1), so the issuer's **share count** is taken from the vendor's
carrier row and multiplied by the published close; where a second reading (the quote
service's own market cap) disagrees with the vendor's share count by more than 25%, the
second reading wins — the vendor's cap is off by orders of magnitude for ~300 micro-caps.
`market_cap / close` is therefore exactly the issuer's share count on the published basis.

**New in the repo (procedure only — the prompt and the schedule are untouched):**

- `scripts/fetch_eod_universe.py` — ONE joined keyset sweep of the vendor: the universe,
  the carrier caps, the floats, the trailing P/E and the sector in one row per symbol, ~25
  bridge calls instead of ~66 (the bridge is metered per CALL, not per row).
- `scripts/fetch_eod_quotes.py` — the Yahoo `v7/finance/quote` batch (cookie + crumb). The
  handshake trap: `fc.yahoo.com` answers HTTP 404 **and still sets the cookie**, so
  `urllib` never sees it and the whole quote path gets abandoned.
- `scripts/fetch_eod_settled.py` — pass 1 + the settle probe loop → the history and the
  settle map.
- `scripts/fetch_eod_venue.py` — the venue's settled print (Nasdaq `/info`) + the
  independent confirmation → the settle map's `CONFIRMED` / `UNCONFIRMED` / `NO_BAR`.
- `scripts/build_eod_base.py` — now also carries the settle evidence and the cap's share
  count correction.
- `tools/test_eod_settle_contract.py` — the fault-injection test for the settle contract
  (8 cases; a checker never observed failing is a claim).
- `tools/check_eod_artifact.py` — five new assertions: the `settle_status` vocabulary, the
  `NO_BAR`/close rule, the `settle_round` format, at least one `CONFIRMED` row, and the
  report's settle evidence agreeing with the CSV.

**The published schema is 32 columns** (the base 14 + 16 derived/provenance + `settle_status`
+ `settle_round`); the first 14 are unchanged, so a consumer reading by position keeps
working. The archive now holds 14-, 30- and 32-column files.

---

## 2026-11-12 — a DEAD TradingView universe pull, removed rather than repaired

This file's `fetch_eod_venue.py` was created by the 2026-11-12 fire and shipped with a
**TradingView universe pull** (`fetch_tv()`) that **was never wired in** — nothing called it, and
the `--no-tv` flag ("skip the TradingView confirmation") controlled nothing at all. Two reasons it
had to go rather than be repaired:

1. **It was the wrong source.** Measured 2026-11-11, the TV America scanner agrees with the
   VENDOR'S DAILY BAR on 4,497 of 4,526 rows (99.4%) and with the VENUE's settled print on only
   **67.8%** — TV corroborates the BAR, not the venue, so it must not confirm the published close.
   The live confirmation is Yahoo's 1-minute FINAL bar (a different feed, so agreement is real
   corroboration). The pull was rejected on the merits and then left in the file anyway.
2. **Its shape lost names.** It paged the universe on `sort {"sortBy":"close"}` — a LIVE column, so
   the page order is not stable between requests. Measured 2026-11-12: **20,342-20,345 names
   against a `totalCount` of 20,347** (2-5 missing) and **two identical pulls returned different
   name sets** (IVRO, LYCA in one run only; AGCCF in the other). The stable sort (`{"sortBy":"name"}`)
   returned 20,347 == `totalCount`, every time. The `totalCount == rows returned` check cannot see
   this — it is a SET test.

**Landed:** the dead pull is deleted (with a module note recording both reasons and the
measurement), `--no-tv` is kept but documented as an honest **no-op** so an existing invocation
cannot fail on it, and `tv_candidates()` survives as the symbol-form helper it always was.

**The LIVE exposure was in the SKILL, not the script:** the cross-venue ADR pull was specified in
prose as "13,376 rows in three calls (`range` caps at 6,000 per call)" — a PAGED pull the agent
builds at run time, with no completeness check. It is now **one call with `range [0,20000]`** (the
scanner's page cap), sorted by `name`, with an assert that the distinct names equal `totalCount`:
a failed pull is a failed pull.

Full evidence and the fleet-wide rules: `docs/IMPROVEMENTS-2026-11-12-tv-scanner-pull-completeness.md`.
Guard: `tools/test_tv_pull_completeness.py`.

---

## 2026-11-12 fire — the venue's LIVE block was published as the close (fixed, and the
## probe loop's "drift" was this defect in disguise)

### What the run found

The 2026-11-12 fire published its first artifact from the venue's **LIVE** price block and
caught it in review. The venue's `/info` endpoint carries two price blocks, and the difference
between them is the difference between a close and a tape:

| block | stamp | what it is |
|---|---|---|
| `secondaryData.lastSalePrice` | **"Closed at Nov 12, 2026 4:00 PM ET"** | the official 16:00 ET **auction print** — the close of record |
| `primaryData.lastSalePrice` | "Nov 12, 2026 5:26 PM ET" | the **LIVE** print; after the close it carries an **extended-hours** trade |

Measured on a pull made at 18:15 ET:

- **AAPL** primary `$354.79` @ 5:26 PM ET vs secondary `$354.88` @ "Closed at 4:00 PM ET"
- **JPM** primary `$342.80` @ 5:26 PM ET vs secondary `$342.98` @ "Closed at 4:00 PM ET"
- **WMT** primary `$125.8152` @ 5:26 PM ET vs secondary `$126.19` @ "Closed at 4:00 PM ET"

**Yahoo's 1-minute FINAL bar corroborates the SECONDARY print** (AAPL 354.88) — a different feed,
so the agreement is real corroboration, and it is what proves the secondary block is the auction
close while the primary block is the live tape.

### Two consequences, both measured

1. **The published close was an after-hours price.** An after-hours price sits OUTSIDE the
   session's own range, so the range pass had to fall back to the venue's day range for **817
   rows** under the live print against **384** under the settled print. Correcting the source
   raised the independently `CONFIRMED` rows from **2,842 → 3,503** and moved `UNCONFIRMED` from
   **2,045 → 1,345**.
2. **The settle probe loop's "drift" was this defect in disguise.** The loop read the live block,
   so it measured the **after-hours tape ticking**, not the close settling: **122 symbols still
   "changed" in round 12 at 17:08 ET** (1,199 over the 12 rounds), the loop never reached two
   quiet rounds, and it hit its `--max-rounds` cap. The published close does not depend on the
   probe — it comes from the settled print — so the artifact was correct once the source was
   fixed, but the drift *measurement* was worthless until then.

### A third gap: the Market read had no index table

The vendor's `country_iso='US'` universe carries equities, not ETFs, so the index proxies and the
sector ETFs were never pulled — and the equity-only history produced a Market read with **no
index rows** and **all 11 sector-ETF columns at `n/a`**. `fetch_eod_settled.py` now fetches
`PROXY_SYMBOLS` (SPY, QQQ, IWM, DIA, RSP + the eleven sector ETFs) alongside the equities; the
2026-11-12 artifact's Market read carries SPY −0.35%, QQQ −0.32%, IWM −1.64%, DIA −0.38%,
RSP −0.87% and every sector ETF.

### Landed

- `fetch_eod_venue.py` — the close comes from the **settled** block; the primary print is used
  only when a symbol serves no settled print AND its primary stamp is still inside the regular
  session (a stamp after 16:00 ET is an extended-hours print, not a close). The record carries
  `close_source`, `primary_price` and `primary_stamp` so the choice is auditable.
- `fetch_eod_settled.py` — the probe loop measures the same settled block, so it is a drift
  measurement again; and it pulls `PROXY_SYMBOLS`.
- `build_eod_report.py` — takes `--prior-csv` and **states the column count when it differs from
  the prior session** (30 → 32 columns on 2026-11-12, adding `settle_status` and `settle_round`),
  and the settled-print rule is now in the artifact's `## Method & caveats`.
- The skill spec states the settled-vs-live rule with the measurements.

All three scripts are **fetched at RUN time**, so these fixes land on the next fire with **no
`cron_update` and no prompt drift**.

**Artifact:** `us-eod/2026-11-12.csv` (4,893 rows, 32 columns) + `us-eod/2026-11-12.md` +
`us-eod/2026-11-12.manifest.json` in `karizaco/minimax-cloud-outputs` (`main`, commit `cbbe8b5`).
Checker: 34/34 assertions pass; the settle fault-injection test 8/8; the numeric formatter
reproduces the prior session's 99,869 numeric cells with **0 drift**.

---

## 2026-11-14 — the venue stage's three pulls now run CONCURRENTLY (the ~19 minutes off the critical path)

### What was measured, and what it cost

The venue stage is three data pulls: the venue's **settled print** (`/info`, 4,890 symbols),
the venue's **own day range** for the rows no other range brackets (`/summary`, ~400-600
rows), and the **independent reading** (Yahoo's 1-minute final bar, 4,890 symbols). Run one
after the other they cost, measured on 2026-11-12:

| pull | measured |
|---|---|
| the venue's settled print | 255 s — and **777 s** on the second run of the same sweep (Nasdaq's throttle is 3x) |
| the venue's day range | ~10 min for 605 rows (**0.4 req/s** measured sequentially; ~1 row/s at 64 threads) |
| the independent reading | ~9 min for 4,890 (8.8 req/s, the Yahoo egress ceiling) |

**26-35 minutes after the probe exits** — and none of it was waiting for the market.

### What changed

- **OVERLAP A — the independent reading runs concurrently with the venue sweep.** The 1-minute
  final bar is a pure data pull that does not depend on the venue; only the COMPARISON does.
  It now runs in its own thread for the whole sweep.
- **OVERLAP B — the day-range pass STREAMS.** The candidate ranges (the vendor's bar range and
  the quote service's day range) are a PRE-PASS over the history and the quotes — no venue
  needed — so the moment a row's close arrives, the row's range need is decided and the
  venue's own day range is pulled for it **while the sweep is still running**. The range pass
  no longer follows the sweep; it interleaves with it. The row-selection rule is unchanged
  (a row needs the venue's range only when no candidate range brackets its close).

### Measured, on the 2026-11-13 session (a full re-run of the whole pipeline)

| stage | measured |
|---|---|
| the vendor sweep (25 bridge calls) | 63 s |
| the quote batch | 6 s |
| pass 1 (4,906 symbols, a year of bars) | 340 s |
| the probe loop (2 quiet rounds on settled data) | 4.8 min |
| **the venue stage — sweep + streamed range + independent reading, CONCURRENT** | **418 s = 7.0 min** |
| patch + base + derive + report + checker | ~1 min |

**The venue stage went from 26-35 minutes to 7.** The artifact is unchanged: **34/34**
assertions passed and **4,823 of 4,846 closes (99.53%) are identical to the fleet's published
2026-11-13 file** (23 differ, all thin names, the largest 4%).

### The wall clock, with the numbers

The publish time is now dominated by the SETTLE, not by the code:

```
16:00  start
16:02  the universe + the quote batch
16:05  pass 1 done (340 s)
16:45  the feed's quiet   <- the thin tail's last ingestion; NO source publishes it earlier
16:49  the probe exits (two quiet rounds, +4 min)
16:56  the venue stage (7 min, everything concurrent)
17:00  the artifact is built, pushed and verified
```

**The floor is the settle itself (~16:45).** The code removes the waste around it: the blind
second pull of 4,909 symbols is gone, the 27-minute idle is a measured wait, and the three
venue-stage pulls no longer queue behind each other.

### One window caveat the re-run made visible

The venue's day range is **only populated close to the session** — a Saturday-morning re-run
got `N/A` from `/summary` for the illiquid names, so 4,561 rows publish a range against the
in-window run's 4,842. Outside the window those rows publish an EMPTY range (flagged
`HIGH_LOW_UNAVAILABLE`), never an invented one.

---

## 2026-11-16 — the probe's detector is BATCHED, and the venue polls on its own cadence

### What the 2026-11-13 fire actually put on the wire

The settle probe loop is the only part of the routine that makes thousands of requests, and
it runs against the two sources that throttle. Measured on the 2026-11-13 fire:

| pull | requests |
|---|---|
| the vendor's session bar, one symbol per request | **5,593** (466 probe names x 12 rounds) |
| the venue's settled print, one symbol per request | **5,593** |
| the DUPLICATE chart re-pull after every bar movement | **765** |
| **total** | **~11,951** |

That is ~53 s of pure wait per round against a Yahoo egress measured at 8.8 req/s, and the
repo's own numbers record the Nasdaq endpoint taking **777 s on its second pass instead of
255 s** - the loop was throttling the very source the next stage depends on. The probe set
was 423-503 names per round, above its own `--probe-size 300`, because the residue held
every symbol that had **ever** changed (765 by the last round) and could never shrink.

### Three changes, none of which touches what is published

- **THE DETECTOR IS BATCHED.** Yahoo's `v7/finance/spark` carries **up to 20 symbols in ONE
  request** - measured 2026-11-16: 20/20 resolved, 10 back-to-back 20-symbol calls in 1.45 s
  (~138 symbols/second), no cookie and no crumb needed, and class shares resolve once the
  Yahoo form is used (`ABR-P-D` -> `ABR-PD`; `ABR-PD`, `USB-PH`, `AGM-PD`, `BRK-A`, `LEN-B`
  all resolved). The spark close is **ROUNDED** (2-3 dp) and carries no volume/open/high/low,
  so it is a **detector value only**: the movement tolerance is `max(0.005, |close| x
  0.0002)` and the rounding error is ~1e-5 - three orders of magnitude inside it, and
  measured on 15 names (AAPL, BRK-A, the class shares, the thin names) the spark and chart
  closes are indistinguishable to the movement test. **Any symbol the probe decides MOVED is
  re-read from the per-symbol chart**, which carries the full bar and the full-precision
  close - the same bytes as before - and a symbol spark cannot resolve falls back to the
  per-symbol chart, so the detector is never blind for any name.
- **THE VENUE POLLS ON ITS OWN CADENCE.** The venue's settled print is a **stamped** auction
  print; the vendor's daily bar is a series that keeps ingesting. The two do not settle at
  the same time, so the venue is polled **every round while it is still MOVING** and backs
  off to **every other round** once it has been quiet for two consecutive polls; any venue
  movement snaps it straight back to every round. The cadence is set by the EVIDENCE, not by
  a guess - and the run now **reports `bar_moved` and `venue_moved` separately per round**,
  so the next session's data can set it from measurement.
- **THE PROBE SET SHRINKS.** The residue is now the set of symbols that are **still moving**,
  not the set that ever changed. A symbol that moved is re-measured until it stops moving
  and then LEAVES. The invariant is unchanged: every symbol that ever changed is re-pulled
  until it stops changing.

The exit test is unchanged in strength and explicit about the venue: **a round can only be
called quiet when the venue was measured in it**, and the quiet streak counts consecutive
quiet **venue polls** - a round that skipped the venue neither advances nor resets it, so
two quiet polls 8 minutes apart still count as two.

### The contract test, and the bug it caught before it could ship

`tools/test_eod_settle_probe_contract.py` drives the REAL `main()` against a SYNTHETIC
feed - no network, no clock, no sleep - and asserts the invariants above, including the one
that matters most: **a rounded spark close is not a movement**. 15 cases.

**The test caught a bug in this change before it was pushed:** when the venue's print MOVED,
the new value was not stored, so the old value was compared against the new one on every
later round and the venue reported a movement on every round forever. It was caught because
the feed's venue settles while its bar keeps moving - the shape of the real problem.

Five fault injections are each observed to FAIL the test: the venue value not stored on a
move, the cadence never backing off, the spark fallback dropped, a skipped round advancing
the quiet streak, and the ever-changed residue restored (the probe set then grows
monotonically: 7, 7, 11, 15, 16, 20, 22, 26, 28, 30, 31, 32 instead of returning to 7).

### The equivalence evidence

A full re-run of the 2026-11-13 session against the new script, on settled data:

- **3,993 of 4,772 session closes (83.68%) are IDENTICAL** to the old probe's output;
- the probe set fell to **305 names** (from 423-503) and the loop **settled after 2 rounds**
  on data that had already settled;
- the 779 that differ are the names that were **still moving when the old probe hit its
  12-round cap** - the new run reads them settled.

### What this does NOT fix

The **floor** is the settle itself: the thin tail's last ingestion is ~16:45 ET and no
source publishes the auction print earlier, so the loop cannot exit before ~16:49 whatever
it does. The remaining wall clock is a measured wait, and the only way past it is to change
what is published (a two-part artifact), which is a product decision, not an optimisation.

**The capability marker moved to `EOD_SETTLE_V2` for `fetch_eod_settled.py`** and the skill's
fetch ladder demands it, so a stale copy of the script - which would silently put the old
request volume back on the wire - is rejected rather than run.

---

## 2026-11-17 — the published VOLUME is the auction's volume, and the tape keeps filling afterwards

The 2026-11-17 fire published the 32-column file (4,887 rows) on the standard path, and the
settle probe loop hit its `--max-rounds` cap for the second session running - **12 rounds,
758 symbols changed after pass 1, the loop stopped at 16:58 ET**, with 165 names still moving
in the last round. That is the known thin-name wall, not a new defect, and the artifact says
so in its provenance opener and in `## Source health`.

**The new measurement: the published `volume` is systematically BELOW a later consolidated
tape.** The post-close cross-check (40 of the most liquid names, re-quoted after the close
through the bridge's `market-recap`, a source that is not the venue's print) reads:

| measurement | result |
|---|---|
| published close vs the consolidated tape's print | **34 of 40 within 0.1%**; the other 6 differ by 1-2 ticks on sub-$3 names (BURU 0.2211 vs 0.233, SHFS 0.0148 vs 0.015, NIO 2.82 vs 2.81) |
| published volume vs the tape's volume | **the tape is higher on 40/40** - from **0.1% to 25.4%**, median **4.5%** |

Two different things are being measured and both are correct:

1. **The CLOSE differences are the documented thin-name behaviour, not an error.** The
   published close is the venue's 16:00 ET **auction print** (`secondaryData`, stamped
   "Closed at 4:00 PM ET"); the tape's `last` is a LATER off-auction print. On a $0.22 stock
   one penny is 4.5%. The published close is the contract's close of record, it sits inside
   the published range in every case, and 4 of the 6 rows are `UNCONFIRMED` - the file already
   says "no independent reading agreed for this line".
2. **The VOLUME difference is a source-lag fact that no artifact used to state.** The venue's
   settled volume is stamped at the auction; the consolidated tape keeps filling afterwards,
   so a reader comparing this file with a later feed sees a HIGHER volume on the same
   session - by a median of 4.5% and up to 25% on a name like SHFS. `rel_volume` and
   `avg_daily_dollar_volume` inherit the same basis, because they are computed from the same
   history pull.

**What changed:** the fire publishes the cross-check as an eighth `## Source health` row, with
the numbers measured by a script from the run's own artifacts (the published CSV and the
bridge's response) - never typed in by hand. The report is still built FROM the published CSV,
so the row is data, not prose.

**What did NOT change:** the CSV. No close, no volume, no derived column was edited; the
cross-check confirmed the published close and explained the volume basis. The 34 assertions
passed before and after the rebuild.

---

## 2026-11-18 — the probe's drift is the VENDOR'S BAR, not the published close; the max-rounds bound is a SERIES bound

The 2026-11-18 fire published the 32-column file (4,887 rows, 4,850 settled closes) on the standard
path, and the settle probe loop hit its `--max-rounds` cap again — **12 rounds, 773 symbols changed
after pass 1, the loop stopped at 17:01 ET with 158 symbols still moving.** The 2026-11-17 entry
already called this "the known thin-name wall"; this run measures WHAT was still moving, and the
answer changes how the bound should be read.

**The new measurement: `venue_moved` was 0 in every one of the 12 rounds, while `bar_moved` ran
41-104 per round throughout.**

| round | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `bar_moved` | 1 | 104 | 79 | 86 | 67 | 72 | 69 | 75 | 55 | 58 | 41 | 50 |
| `venue_moved` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `still_moving` | 125 | 228 | 187 | 194 | 175 | 180 | 177 | 183 | 163 | 166 | 149 | 158 |
| `no_close` | 124 | 108 | 108 | 108 | 108 | 108 | 108 | 108 | 108 | 108 | 108 | 108 |

The rounds run 16:11 ET -> 17:01 ET on a 4-5 minute cadence, with the venue polled on 7 of the 12
rounds (the back-off cadence the 2026-11-16 change introduced).

The published close is the **venue's settled print** (`secondaryData`, stamped "Closed at 4:00 PM
ET"), and that value did not move once in 55 minutes. What was still moving at the bound was
**Yahoo's daily-bar series** — the source of the derived columns (SMA, ATR, 52-week extremes),
and the input the probe uses to DETECT drift.

**So the `--max-rounds` bound is a SERIES bound, not a CLOSE bound.** Two consequences:

1. **The published close was never at risk from the bound.** The 4,742 rows whose close came from
   the venue were read from a value that was already stable; the probe's exit condition governs
   the vendor's series, which is a different quantity.
2. **"158 symbols still moving" is a statement about the bar, not about 158 unsettled closes.**
   The artifact's `## Source health` row says exactly that ("the residue is published as it stands",
   "the published close source moved 0 times across all 12 rounds"), because a reader who reads
   "still moving" as "still provisional" would distrust 158 closes that were already final.

**What changed:** the `## Source health` row for the probe loop now names the residue AND the
`venue_moved = 0` fact, measured from the run's own settle log. Nothing else moved: the CSV is the
standard 32-column file, 34/34 assertions pass, and the settle contract's 8 fault-injection cases
and the probe contract's cases all pass.

**A note on this run's delivery latency.** The build itself took ~1h20m of wall clock (16:03 ET
start, venue stage finished 17:14 ET). The session then sat **idle for ~8 hours** between the venue
stage and the build stage, and the push landed at **01:21 ET — 9h20m after the 16:00 ET fire.**
The artifact is unaffected (every source was read inside the session's own window), but a latency
figure of "9h20m" describes a PLATFORM HOLD, not a slow routine — the same distinction cron #90's
audit makes between a dispatch record and the real delivery time.
