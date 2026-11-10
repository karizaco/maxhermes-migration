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
