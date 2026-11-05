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
