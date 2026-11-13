# Improvements — cron #07 `stock-screener-focus-rvol-09:45`

- **Audited:** 2026-11-12 (the 09:45 ET fires of `2026-11-09`, `2026-11-10` and `2026-11-11` —
  **the alert tier was structurally dead for five consecutive sessions**; see the 2026-11-12
  section at the end of this file) and 2026-11-10 (the 09:45 ET fire, `2026-11-10`)
- **Scope:** the intraday RVOL screen's data path — the live price, the session-volume window, the
  10-day denominator, the prior-10 same-window baseline, the cross-check snapshot and the
  pre-market exclusion — and, since 2026-11-12, **the crossing/alert rule and the baseline it
  reads** (prompt STEP 6).
- **Artifact under review:** `daily-screens/2026-11-10/focus-rvol-snapshot.md` + `.csv` (outputs repo,
  cron #07); also `2026-11-09` and `2026-11-11` for the alert-tier defect.

## Summary

The routine ran clean (12/12 names priced, 7 in the RVOL Required bucket, 0 alerts, 0 near misses,
0 UNADJUSTED rows, `status: ok`). The screen itself worked. What the run exposed is that **four of
the data-path steps in the prompt carry traps that produce plausible-looking wrong numbers rather
than obvious failures**, and that a fifth step — the independent price check — is available and
turns out to be exact.

Nothing here changed today's published numbers. All four traps were caught before publication; the
notes below are what to check next time, and they are the reusable parts.

---

## 1. Yahoo's chart API 429s a bare `curl` but serves a browser `User-Agent` immediately

**The trap.** `curl` with no `User-Agent` header against
`query1.finance.yahoo.com/v8/finance/chart/{SYM}?interval=5m&range=1mo&includePrePost=false`
returned HTTP **429 `Edge: Too Many Requests`** with a 23-byte body — a body that is not JSON and
not a chart. The same URL with a browser `User-Agent` returned **HTTP 200** with the full 146 KB
chart on the very next call, with no cookie, no crumb and no delay.

**Why it matters.** The 23-byte body parses as nothing and looks like an empty chart, so a parser
that does not check the body reports "no bars for this symbol" — which, under the prompt's
`no_intraday_bars` rule, silently drops the name from the screen instead of retrying.

**What to do.** Send a browser `User-Agent` on every Yahoo chart call. The prompt's
"`[ -s file ] || curl`" ladder does not cover this; it is a header, not a URL.

---

## 2. The TradingView scanner has THREE `sort` shapes, and only one of them works

**Corrected 2026-11-11.** The first version of this note claimed the scanner "400s when the body
carries a `sort` key" and that "any column the endpoint does not recognise also 400s the whole
request". **Both claims were wrong**, and this note replaces them. The columns are fine — all
eight returned 200. Only the *shape* of the `sort` value matters:

| `sort` value in the body | HTTP | what it actually does |
|---|---|---|
| `[{"column": "close", "order": "asc"}]` — **an array** | **400** `{"totalCount":0,"error":"json parse error","data":null}` | nothing — the request never runs. Even `"sort": []` 400s. |
| `{"column": "close", "order": "asc"}` — object, **wrong keys** | **200** | **silently IGNORED** — the rows come back unsorted, with no error and no warning. |
| `{"sortBy": "close", "sortOrder": "asc"}` — object, **the repo's keys** | **200** | **sorts correctly** (verified monotonic on `close` asc and desc) |

The array form is the shape published in TradingView's own public docs, so it is the one an agent
reaches for from memory. The repo's canonical form is `{"sortBy": …, "sortOrder": …}` — see
`relvol_screen.py:112`, `tools/daily_sweep_engines.py:157`,
`cloud-prompts/skills/stock-screener-suite/SKILL.md:1089`.

**Why it matters.** The middle row is the dangerous one: `{"column","order"}` is accepted with
HTTP 200 and produces **unsorted** data, so a routine that thinks it ordered by `volume` and reads
the first N rows as "the top N" is silently reading an arbitrary N. Cron #16's `relvol_screen.py`
and cron #09's fresh book both rely on the sort actually working — they are correct today **because
they use the `sortBy`/`sortOrder` keys**, and a well-meaning "cleanup" that rewrites that key pair
to the documented-looking `column`/`order` pair would break them invisibly.

**Verified across every market endpoint** — the array form is rejected identically on
`/america/scan`, `/japan/scan`, `/korea/scan`, `/taiwan/scan`, `/hongkong/scan` and `/crypto/scan`.

**The other scanner 400, with a different message.** A `filter` whose `right` is a list is
rejected: `{"left":"name","operation":"in","right":["AAPL","MSFT"]}` returns
**400 `Expected one value, passed 2`**. The `in` operation does not accept multiple values on this
endpoint — filter locally instead. (The repo already records this for `type`/`in` in
`cloud-prompts/skills/earnings-reminder/SKILL.md`, measured 2026-11-06, and cron #07's prompt has
carried the `name`/`in` version since 2026-11-02.) Note the **different error string**: "json parse
error" means a malformed request shape, "Expected one value" means a rejected filter value.

**`range` is a page size and the API truncates silently.** `range: [0, 20000]` against the US
universe returned exactly 20,000 rows while `totalCount` read **20,271** — **271 names were
dropped without any error**, and with no effective sort the dropped slice is arbitrary. The API
reports the true total in `totalCount`, so the completeness check is: **`totalCount` must equal the
rows returned**; if it does not, the pull is truncated and the missing slice must be pulled. This is
the same defect class as cron #25's `range:[0,600]` (one gainer away from a dropped name) and
cron #26's `range:[0,5000]` (which dropped Infineon, SoftBank and Petrobras).

**What to do.** Use `{"sortBy": …, "sortOrder": …}` or omit `sort` entirely; never send an array.
Do not filter server-side with `in` — pull and filter locally. Always compare `totalCount` with
the rows returned. And never "tidy" the `sortBy`/`sortOrder` keys into `column`/`order`.

---

## 3. Nasdaq `/chart` `z.value` is a **string**, and its `dateTime` marks the MINUTE — which makes it an exact price check

Two findings in one endpoint.

**3a. The value is a string.** Each chart entry is `{"z": {"dateTime": "9:45 AM ET", "value": "65.83"}, "x": ..., "y": 65.83}`.
Indexing it as a list (`z["value"][0]`) returns the **first character** — `'6'` → `6.0`. That parses
as a float and looks like a price, so the column ships 6.0, 4.0, 1.0 instead of 65.83, 41.71,
12.52. `float(z["value"])` is the read.

**3b. The 09:45 print is NOT the fire-time close — the 09:44 print is, and it matches EXACTLY.**
The Yahoo bar stamped 09:40 covers 09:40:00-09:45:00, and its `close` is the last trade in that
window, which Nasdaq stamps **09:44**. The Nasdaq 09:45 print is the *first trade after* the bar
closed. Comparing the published close against the 09:45 print therefore compares two different
instants and produces a spurious 0.05%-1.06% "disagreement" — QNT showed 1.06% this way.

Compare against the **09:44** print instead and the two independent feeds land on the same trade:

| symbol | Yahoo 09:40-bar close | Nasdaq 09:44 print | difference |
|---|---|---|---|
| ETON | 65.70 | 65.70 | **0.0000%** |
| QNT | 42.155 | 42.155 | **0.0000%** |
| RGTI | 12.47 | 12.47 | **0.0000%** |
| TMDX | 95.72 | 95.72 | **0.0000%** |
| FLY | 24.38 | 24.38 | **0.0000%** |
| FROG | 106.24 | 106.24 | **0.0000%** |
| LASR | 44.68 | 44.68 | **0.0000%** |
| OKLO | 25.70 | 25.70 | **0.0000%** |
| CYRX | 19.89 | 19.89 | **0.0000%** |
| IONQ | 34.86 | 34.86 | **0.0000%** |
| RHLD | 157.135 | 157.135 | **0.0000%** |
| KRMN | 45.75 | 45.75 | **0.0000%** |

**12 of 12 names, exact.** This is a far stronger validation of the published fire-time close than
the price comparison the 2026-11-09 artifact used, and it is free — the same response already
carries every minute.

**What to do.** Publish the 09:44 print as the close's independent corroboration and the 09:45
print as a *post-fire* reference. When checking the 09:45 print for a bad tick, require at least
two neighbouring prints and a materiality floor — RHLD printed only one neighbour, and with a
single neighbour the "outside the neighbours' range" test flags every move as an outlier.

---

## 4. CBOE's snapshot timestamp can be LATER than the fire, and the prompt's fallback then applies

The prompt makes CBOE the preferred source for the earlier cross-check snapshot, with
`same_series_truncated` as the fallback "when CBOE is unreachable, **or its snapshot is not earlier
than the fire**". On this run CBOE was reachable and healthy (12/12, HTTP 200) but its snapshot
response time was **09:48:02 ET — three minutes after the 09:45 fire**, because the fetch ran
after the fire, not at it.

**Why it matters.** A routine that treats "CBOE answered 200" as "CBOE gave me the earlier
snapshot" imports a *later* reading into the trend column and publishes a backwards-looking
"earlier" number. The CBOE payload still carries `last_trade_time` (09:32-09:33 ET here), so the
volume it reports IS an earlier reading — but the snapshot's own timestamp is what the prompt says
to judge by.

**What to do.** Read CBOE's own snapshot timestamp and compare it with the fire instant before
using it as the earlier reading. On this run it failed that test, so `cross_check_source` was
published as `same_series_truncated` and CBOE was published as corroboration only (`cboe_vol`,
`cboe_ts`, `cboe_last_trade`, `cboe_raw_ratio`). Note also that CBOE's count basis differs from
Yahoo's opening bar (its volume is a mid-bar, cross-feed count), so it should never be the
metric's numerator — the same conclusion the 2026-11-09 artifact reached.

---

## 5. A zero-volume opening bar in a prior session inflates the name's rvol — check which name it is

The baseline rule (a prior session enters only if its 09:30/09:35/09:40 bars are all present AND
non-zero AND a consolidated daily print exists) is correct and it fired today on exactly one
session: **RHLD 2026-11-09 has a zero-volume 09:30 bar**. RHLD's baseline therefore reaches back to
2026-10-19 instead of ending 2026-11-09.

Worth stating because the cost of getting it wrong is silent: using that session with a zero
deflates the baseline mean and multiplies the name's rvol by the share of the window it represents.
RHLD's tier does not change either way (0.82x, far below every threshold), so the rule was not
load-bearing today — but it would be on a name that was hot.

The published `baseline_first` / `baseline_last` columns are what make this auditable per row, and
they are the reason the caveat can be written without guessing.

---

## 6. Small, reusable things

- **TV's `average_volume_10d_calc` is a trailing-10 average that includes today's partial volume
  and drops the oldest completed session.** The prior-10-mean / TV-mean scale factor is therefore
  above 1.0 for most names (8 of 12 today: 1.04-1.11) and exactly 1.00 for three (IONQ, KRMN,
  OKLO, whose TV window coincides with their 10 completed sessions). Publishing the factor per row
  keeps the series honest and comparable across fires.
- **The pre-market exclusion is verifiable without cron #08.** Across 12 symbols and 22 sessions,
  19,716 Yahoo bars were examined and **not one** is stamped outside 09:30-15:55 ET, so with
  `includePrePost=false` a pre-market print cannot be inside a session bar. Nasdaq `/chart` carries
  its own pre-market prints (CYRX 08:30 20.50, 08:32 20.32, 09:23 20.32) and none of them appear
  in the Yahoo session bars — a direct, independent confirmation.
- **A Nasdaq `/chart` minute can simply be absent.** CYRX and KRMN have no 09:45 print at all
  (minutes with no trade are not emitted); RHLD has a 09:45 print but only one neighbouring print
  (09:44). Absent minutes must be "no print", never "price 0" — and a lone neighbour is not enough
  to run a bad-tick test against.

---

## 2026-11-11 — the TradingView scanner's pagination can OVERLAP and still lose names (cron #07, 09:45 ET)

Measured on the 2026-11-11 fire while pulling the `average_volume_10d_calc` denominator for the
12-name focus roster. Two new traps, both of which fail **silently**.

### 1. Two correct-looking slices can overlap, and `totalCount` will not catch it

The documented rule is "`totalCount` must equal the rows returned; if it does not, the pull is
truncated". That check passes a pull that is still missing names:

| pull | rows returned | distinct `s` | union of the two | `totalCount` |
|---|---:|---:|---:|---:|
| `range:[0,20000]` then `range:[20000,20155]`, **no sort** | 20,000 + 155 | 20,000 + 155 | **20,001** | **20,155** |
| `range:[0,10000]` then `range:[10000,20155]`, `sort {"sortBy":"name","sortOrder":"asc"}` | 10,000 + 10,155 | 10,000 + 10,155 | **20,155** | **20,155** |

Without a sort, the scanner's default row order is **not stable between two requests**: the second
slice returned 155 rows of which **154 were already in the first slice**, so the union covered only
20,001 of the 20,155 symbols — 154 names missing, no error, and `totalCount` (20,155) vs the
first slice's 20,000 was the only visible hint. The second pull in the table did not "fix" it
either; with `range:[0,20000]` + `range:[20000,40000]` the API returned 20,000 rows again for the
over-large end.

**Rule: the completeness test is `len(set(s1) | set(s2)) == totalCount`, not `totalCount ==
rows_returned`.** And the way to get disjoint pages is to **sort with the canonical keys** —
`"sort": {"sortBy": "name", "sortOrder": "asc"}` — which makes the order deterministic and the two
pages disjoint (0 overlap, union == `totalCount` == 20,155, verified). Note this is the SAME
`sort` shape that the 2026-11-11 entry above already documents; what is new is that a sort is
also the **pagination key**, not only an ordering convenience.

### 2. The row key `s` is VENUE-PREFIXED — keying by it makes every US ticker "not found"

The scanner's response row is `{"s": "NYSE:BW", "d": ["BW", "NYSE", avg10d, rvol, mcap]}`: the bare
ticker is `d[0]`, while `s` carries the venue (`NYSE:`, `NASDAQ:`, `AMEX:`, `OTC:`). A pull indexed
by `s` returns **12 of 12 US tickers missing** — and that looks exactly like "this ticker is not in
the universe", which is a false negative that would quietly fall through to the fallback universe.

**Rule: index the pull by `d[0]` (the bare name) and carry `d[1]` (the exchange) as a separate
field.** Verify with a positive control (the 12 roster names present) before using the pull.

### Both traps are invisible in the output

A missing `average_volume_10d_calc` does not fail loudly - it becomes a `KeyError`/null denominator
that either crashes the row or silently produces a wrong `daily_factor`. The 2026-11-11 run caught
both because the pull was checked against `totalCount` **and** against the roster by name before
the metric was computed. Keep both checks in the routine: they are cheap, and they are the only
thing standing between a truncated denominator and a plausible-looking artifact.

---

## 2026-11-12 — the ALERT TIER was structurally dead for five sessions (cron #07, 09:45 ET)

**Audited:** 2026-11-12, against the published artifacts for 2026-11-09, 2026-11-10 and
2026-11-11 (outputs repo, cron #07).
**Scope:** the crossing/alert rule (prompt STEP 6) and the baseline it reads.

### The symptom

`alerts: none` on 2026-11-05, 11-06, 11-09, 11-10 and 11-11 — **five consecutive sessions**.
The tape was not calm. On 2026-11-10 alone, **seven names sat above the 1.5x bar** (ETON 2.74x,
QNT 2.08x, RGTI 2.07x, TMDX 2.01x, FLY 1.93x, FROG 1.83x, LASR 1.81x) and **not one of them could
be shown to be a crossing.** On 2026-11-11 BW was at 4.08x. Every one of those names was published
as tier `WATCH` — a measurable level — because `prev_session_rvol` was `n/a` on every row.

The last session that fired alerts was 2026-11-04 (4 crossings). That run had **no baseline CSV
to read** (2026-11-03 shipped only the `.md`), so it recomputed every prior reading from the same
Yahoo series — and produced 4 sound alerts. Recompute = works. Read-the-CSV = dead.

### The cause is structural, not editorial

STEP 6 said the baseline is *"the previous SESSION's published value"*, read from
`daily-screens/<previous session>/focus-rvol-snapshot.csv`. That CSV is keyed on the **previous
sweep's roster**. The focus roster turns over almost completely between sweeps — measured overlap
between consecutive sweeps: **4/12, 0/12, 0/12, 2/12, 0/12** — so the published baseline covered
almost none of today's names:

| session | roster overlap with the previous sweep | names above 1.5x | alerts published |
|---|---:|---:|---:|
| 2026-11-04 | 0/12 | 4 | **4** (recomputed — no CSV existed) |
| 2026-11-05 | 0/12 | 7 | 0 |
| 2026-11-06 | 2/12 | 2 | 0 |
| 2026-11-09 | 0/12 | 1 | 0 |
| 2026-11-10 | 0/12 | **7** | 0 |
| 2026-11-11 | 1/12 | 1 (BW 4.08x) | 0 |

A missing ticker was published as `prev_session_rvol: n/a`, and **an absent prior reading silently
disarms the alert tier**. The routine reported a clean `alerts: none` on a hot tape for five
sessions, and nothing in the artifact said the tier was structurally unable to fire.

### What the fix changes

STEP 6 now has **two** ways to obtain the prior reading, and `n/a` is only legal when the
recompute is genuinely impossible:

1. `published_csv` — the previous session's CSV carries the ticker.
2. `recomputed_same_feed` — it does not; recompute that ticker's previous-session reading from the
   SAME Yahoo 5-minute series with the IDENTICAL formula (same clock window, that session's own
   prior-10 baseline, same daily-factor recipe). **Both sides of the comparison are the same
   metric computed the same way on the same source** — a real prior reading, not a fabrication.
   This is exactly what the 2026-11-04 run did, and it published that provenance in the artifact.

Every row now carries **`prev_session_rvol_source`** (`published_csv` / `recomputed_same_feed` /
`unavailable`), and the artifact states the split. The roster rotates; the source does not.

### What was missed, measured

Recomputing the prior reading for the two sessions that published a false "none", on the same
feed and the same formula:

**2026-11-10 (prior session 2026-11-09) — 2 crossings the artifact could not claim:**

| symbol | published `rvol_now` | recomputed prior | prior source | crossing |
|---|---:|---:|---|---|
| FROG | 1.8297 | 0.9218 | recomputed_same_feed | **YES** |
| LASR | 1.8069 | 1.4976 | recomputed_same_feed | **YES (marginal)** |
| ETON | 2.7432 | 2.3140 | recomputed_same_feed | no — already above the bar |
| QNT | 2.0793 | 1.8178 | recomputed_same_feed | no |
| RGTI | 2.0711 | 1.5515 | recomputed_same_feed | no |
| TMDX | 2.0079 | 1.5887 | recomputed_same_feed | no |
| FLY | 1.9335 | 2.4072 | recomputed_same_feed | no |
| OKLO / CYRX / IONQ / KRMN | — | computed | recomputed_same_feed | no — below the bar |

**2026-11-11 (prior session 2026-11-10) — 0 crossings.** Every name above the bar (BW 4.08x) was
already above it on 2026-11-10 (BW 6.89x), so there was genuinely nothing to alert. This session
published the right ANSWER for the wrong reason — the fix makes the reason honest rather than
changing the number.

### The one honest caveat: revision drift

Recomputing a session **after** it was published does not always reproduce the published value
exactly. Re-fetching the 2026-11-09 session on 2026-11-12 and comparing against what the 2026-11-09
run published at 09:45 that morning:

| | names | drift |
|---|---:|---|
| reproduced exactly (delta 0.0000) | 8 of 12 | 0.00% |
| revised by the vendor | 4 of 12 (FUN +6.8%, JOBY +5.4%, U +4.8%, WRBY +6.8%) | up to **+6.8%** |

Every denominator (prior-10 same-window mean, prior-10 full-day Nasdaq mean, TV `average_volume_10d_calc`)
matched the published run **to four decimals** — `daily_factor` 1.0371 for WRBY on both sides. The
whole difference is in the **numerator**: Yahoo revised the 09:30-09:45 bar volume of those four
symbols after the session published (WRBY 539,264 → 576,127 shares). So the recompute is
measurably the same metric, but the vendor's own intraday history is not immutable.

**Consequence for a marginal crossing.** FROG's prior (0.9218) sits far below the 1.5x bar, so the
crossing is **robust** to the whole measured drift band (-0.25% .. +4.12%). LASR's prior (1.4976)
sits 0.16% below the bar and the band **straddles it** — LASR is a genuine but marginal crossing.
A crossing this close to the bar should be published with its drift exposure stated, not silently
asserted. The recompute is still strictly better than `n/a`, which asserts nothing at all.

### The checker

`tools/check_focus_rvol_artifact.py` (16 clauses) + `tools/test_focus_rvol_contract.py`
(hermetic). **C6 is the regression clause**: a name above the alert bar whose prior reading is
missing and which does not declare `unavailable` fails the artifact. Verified by running it
against all three published sessions — each fails on exactly the clauses this defect produces:

```
2026-11-09  CONTRACT FAILED — 6 failure(s)   (C2 C3 C4 C6 C8)
2026-11-10  CONTRACT FAILED — 6 failure(s)   (C2 C3 C4 C6 C8)  <- 7 names silenced
2026-11-11  CONTRACT FAILED — 6 failure(s)   (C2 C3 C4 C6 C8)  <- BW 4.08x silenced
```

and the hermetic test proves the checker passes a compliant artifact and FAILS the broken shape,
including the C6 trip.

---

## 2026-11-12 — the fix, deployed: TV_SCAN_V2, a targeted one-call pull, and a SET-based completeness check

The two traps recorded above were fixed, not just documented. What changed, and where:

| what | where | how it is enforced |
|---|---|---|
| `pull --names` — ONE targeted call for a known ticker list | `cloud-prompts/_shared/tv_scan.py` (`TV_SCAN_V2`) | asserts the coverage: a requested name that never comes back is `name-missing` (exit 4) |
| `pull --body` — a universe pull, paged on a STABLE sort | same | asserts the pages are DISJOINT (`pages-overlap`) and their UNION equals `totalCount` (`pages-incomplete`), exit 4 |
| bare-name keying (`d[0]`, not the venue-prefixed `s`) | same | `index_by_bare_name()`; both `pull` modes write a JSON object keyed by the bare ticker |
| the fleet-wide completeness rule | `cloud-prompts/_shared/RUNTIME-CONTRACT.md` §2a-bis | rewritten: `totalCount == rows` is NECESSARY BUT NOT SUFFICIENT |
| the routine's own data path | `cloud-prompts/cron-prompts/07-stock-screener-focus-rvol-09:45.md` (deployed byte-exact, sha256 `7e60438291e1dfed…`, 40,221 B) | the prompt now teaches the targeted pull, the set test, the bare-name key and the `tv_scan.py` fetch |
| the skill's pre-flight | `cloud-prompts/skills/stock-screener-suite/SKILL.md` §7 | fetched at RUN time — the change landed with no redeploy of the skill |
| the regression guard | `tools/test_tv_scan_contract.py` | 40 checks (was 33): overlapping pages, an incomplete union, a missing name, the bare-name key, and the targeted body |

**MEASURED, LIVE, 2026-11-12:**

- **Targeted pull:** one POST with `filter [{"left":"name","operation":"in_range","right":[12 names]}]`
  and `range [0, 17]` → HTTP 200, `totalCount` **12**, 12 rows, **one call**, exit 0. The same
  roster through the universe pull costs 20,155 rows and 2 calls. `in_range` takes a LIST `right`
  for a categorical column; only the `in` operation 400s on a list.
- **Paged universe pull with a stable sort:** `range [0,20000]` then `[20000,40000]`, sorted by
  `{"sortBy":"name","sortOrder":"asc"}` → 2 pages, union **20,356** == `totalCount` **20,356**,
  1.07 s, exit 0. The same pull WITHOUT the sort returns 20,000 + 155 rows whose union is
  20,001 — the 154-name hole.
- **The prompt fetch:** the `TV_SCAN_V2` marker gates the download, so an older `tv_scan.py`
  cannot win the race. The old marker is still present in the file, so a caller that demands
  `TV_SCAN_V1` resolves to the NEW file; only a caller that demands `TV_SCAN_V2` is guaranteed
  the new behaviour.

**THE MCP QUESTION, ANSWERED.** No MCP-side change is warranted, and none was made. The bridge's
packs are `tradier`, `fmp` and `market-recap` — **there is no TradingView pack** — so the scanner
is reached over plain HTTPS and there is nothing to configure on the MCP side. The installable
`tradingview-mcp` stdio server (73 tools) filters on an opaque vendor `min_score`, so it can
never be a published criterion, and FMP's screener cannot supply `average_volume_10d_calc` with
the same semantics — swapping the denominator would break the comparability of every prior
artifact. The defect was never the MCP; it was the request shape, and the request shape now has
a validated client that every routine can fetch at run time.

**A NOTE FOR THE NEXT FIRE.** The deployed prompt now says to fetch `tv_scan.py` in STEP 1. If
that fetch fails, the fallback is the hand-built body in the same block — but the ASSERTIONS
(coverage, disjointness, union) are not optional. A pull that fails them is a failed pull:
report it, do not publish it.

---

## 2026-11-12 — the repo's OWN contract test was RED on arrival (a flaky guard, not a logic failure)

While extending `tools/test_tv_scan_contract.py` for TV_SCAN_V2, the suite failed
intermittently: **1-3 of 37 checks failed on 6 of 6 runs** — before any of this session's edits
(verified by running the pre-change file from git: `18c4ba1~1`). The failing pair was always
`a FULL pull with totalCount > rows is caught as TRUNCATED` and `the row count and totalCount are
both reported`.

**Cause — the HTTP stub never read the request body.** `Stub.do_POST` wrote the response and
closed the connection while the client's POST body was still unread in the socket, so the close
carried an RST and urllib intermittently failed to read the response at all. That is a
**`transport` error, not a result**: `tv.scan()` returned `status=None, rows=None`, so the
truncation logic (which is correct — `requested=20000 >= RANGE_PAGE_CAP=20000` ⇒
`pull-truncated`) was never reached. Measured 12 calls against the local stub: **9 clean,
3 transport failures**. `PagedStub` (added with TV_SCAN_V2) reads the body and never flaked —
which is why the NEW sections were stable and the OLD ones were not.

**Fix:** `Stub.do_POST` now consumes `Content-Length` bytes before responding. **8 of 8 runs
green** afterwards.

**Why this is worth a section.** A guard that fails *randomly* is worse than no guard: it
trains the fleet to re-run a failing test until it goes green, and it makes a real regression
look like noise. The same principle the fleet already applies to checkers applies here —
**"a checker never observed failing is a claim"** extends to **"a checker that flakes is not a
guard"**. Whenever a local HTTP stub is used, **the handler MUST read the request body.**

---

## 2026-11-12 — the alert tier was structurally dead for FIVE sessions; the fix, and a defect in the fix

**Audited:** 2026-11-12, against the published artifacts for 2026-11-09, 11-10 and 11-11.
**Scope:** cron #07's crossing/alert rule (STEP 6), its universe (STEP 4), and its data path (STEP 5).

### The symptom

`alerts: none` on 2026-11-05, 11-06, 11-09, 11-10 and 11-11 — **five consecutive sessions**. The
tape was not calm: on 2026-11-10 **seven names sat above the 1.5x bar** (ETON 2.74x, QNT 2.08x,
RGTI 2.07x, TMDX 2.01x, FLY 1.93x, FROG 1.83x, LASR 1.81x) and **not one could be shown to be a
crossing**. On 2026-11-11 BW was at 4.08x.

### Cause 1 — the baseline was read only from a CSV keyed on a roster that had rotated away

STEP 6 read the prior reading ONLY from the previous session's published CSV. That CSV is keyed on
the previous sweep's ROSTER, and the roster turns over almost completely between sweeps — measured
overlap: **4/12, 0/12, 0/12, 2/12, 0/12**. So the baseline covered almost none of today's names,
and a missing ticker was published as `prev_session_rvol: n/a`. **An absent prior reading silently
disarms the alert tier**: a name at 2.7x becomes a WATCH, not an ALERT. Nothing in the artifact
said the tier was structurally unable to fire.

The last session that fired alerts was 2026-11-04 — the one run with **no baseline CSV to read**,
so it recomputed every prior reading from the same Yahoo series and produced 4 sound alerts.
Recompute = works. Read-the-CSV = dead.

### Cause 2 — the published prior value is on a DIFFERENT SCALE from today's reading

`TV average_volume_10d_calc` is a **rolling** average and it moves between fetches: measured,
ETON's denominator went **550,859 (published 2026-11-10) -> 740,475 (two days later), a 34% swing**,
because the high-volume sessions it printed entered the window. The metric scales as 1/denominator,
so a published value compared against today's `rvol_now` compares two different scales.

**And the drift FLIPS VERDICTS.** The sensitivity is the distance of the PRIOR from the bar:

| name | prior | distance to 1.5 | denominator move that flips the verdict |
|---|---:|---:|---:|
| FROG | 0.921 | 38.6% below | **38.6%** — holds |
| LASR | 1.497 | 0.2% below | **0.2%** — flips |
| RGTI | 1.551 | 3.4% above | 3.4% |

On the 2026-11-10 roster, FROG and LASR crossed on the published denominator and **neither did**
on today's. So "read the published CSV" is not merely incomplete — where it applies at all, it can
be wrong.

### The fix

1. **Always recompute the prior reading**, on the same feed, with the **same denominator as
   today's reading** — both sides of every crossing are then the same metric on one scale. The
   published value is published alongside as `prev_session_rvol_published` plus
   `denominator_drift_pct`: a CROSS-CHECK, never the baseline.
2. **Publish the provenance** — `prev_session_rvol_source` is `recomputed_same_feed` or
   `unavailable` on every row, and `n/a` is legal ONLY when the recompute is genuinely impossible.

### Cause 3 — the focus roster was not the screen

The roster is a **momentum screen built on the previous session's data**, so it structurally cannot
contain a name whose move has not happened yet. Measured on 2026-11-09: the roster carried **1 of the
day's top 10 gainers**, the previous session's `master.csv` 5, cron #17's boards 7, and the union
**10 of 10**. And the routine cannot catch them by re-scanning — the move was already visible at
the fire time (all ten were up 2.56%-22.57% at 09:45 ET, per their own 09:40 bars), but the roster
was built on Friday's settled data.

**The fix: publish TWO tables** — the focus roster in full, and the top of a wider union — and build
the wider union from what is **already on disk** (the previous session's `focus.csv`, `master.csv`
and cron #17's candidate CSVs, ~1,250 names), never by re-scanning the market. The union is a
CANDIDATE SET; the published table is its top by `rvol_now`.

### Cause 4 — the per-name arithmetic was what made the run slow, not the fetching

The 2026-11-09 fire took 66 minutes. The HTTP fetches were never the problem: **the per-name
reasoning was**. Measured cost per source:

| source | per name | for 214 names |
|---|---:|---:|
| TV scanner (full universe, ONE POST) | — | 0.57s |
| Yahoo 5m (the metric) | 0.13s | 28s |
| **Nasdaq `/historical` (daily volume)** | **2.09s** | **419s** |
| Yahoo `interval=1d` instead | 0.13s | 28s |

The daily volume now comes from **Yahoo `interval=1d` bars**: over 240 symbol-sessions across 40
names the ratio Yahoo-1d / Nasdaq-consolidated is **median 1.0000, mean 0.9997, max deviation
0.32%**, with ZERO comparisons outside +/-1% — far tighter than the vendor's own intraday revision
band, and the 2026-11-10 and 11-11 crossing verdicts are identical under both sources. And the
whole per-name job moves into **`tools/focus_rvol_score.py`**, which fetches in parallel and
RENDERS the artifact, so a number cannot be mistyped between the JSON and the markdown. Measured
on 1,636 names: **1,307 scored in 4.5 min** (was 66 min).

### The checker

`tools/check_focus_rvol_artifact.py` (16 clauses) + `tools/test_focus_rvol_contract.py`
(hermetic). **C6 is the regression clause**: a name above the alert bar with no prior reading and
no `unavailable` explanation FAILS the artifact. It fails all three published sessions on exactly
the clauses this defect produces:

```
2026-11-09  CONTRACT FAILED — 6 failures  (C2 C3 C4 C6 C8)
2026-11-10  CONTRACT FAILED — 6 failures  (C2 C3 C4 C6 C8)   <- 7 names silenced
2026-11-11  CONTRACT FAILED — 6 failures  (C2 C3 C4 C6 C8)   <- BW 4.08x silenced
```

and the hermetic test proves it passes a compliant artifact and FAILS the shape that shipped.
C16 and C17 are new: the wider universe must be published, and the CSV must carry a `universe`
column.

### Two defects found in MY OWN first attempt — recorded because both were silent

**The TV column index was wrong.** `cols = [name, close, volume, average_volume_10d_calc, ...]`
— the denominator is `d[3]`, but the first version read `d[2]`, which is the LIVE volume column.
STBA's volume is 1, so its `daily_factor` became 217,200 and its rvol **377,751x**. It did not
crash; it published. Fixed, plus a guard: a denominator below 10,000 shares is refused as
`implausible_tv_denominator`, and a metric above 1000x is refused as `implausible_metric`.

**`close` was carrying volume, not price** (GDYN at 55612). The 5m series now carries both, and
the close is the 09:40 bar's CLOSE.

Both were caught only because the engine was validated against the published artifacts: with the
historical denominator the engine reproduces the published `rvol_now` to within 0.005 on 10 of 12
names. **A metric engine that is not checked against a known-good published run is a rumor.**

### The deploy drifted — twice — and the answer is to stop hand-pasting

The prompt was pasted by hand twice on 2026-11-12 and drifted both times: the first paste carried
a **stale copy of the older prompt** from context (four places, including the `view=runs` ->
`view:runs` swap the skill warns about); the second differed in **one paragraph's line-wrap** —
word-for-word identical, but a different SHA-256, which is exactly what cron #91 reports as drift.
The repo was aligned to the deployed bytes rather than re-pasting 48 KB to chase a wrap, because
re-pasting risks a real content change for a cosmetic one.

**The durable fix is the one already in this change: the procedure lives in run-time-fetched
helpers** (`focus_rvol_run.py` -> `focus_rvol_universe.py` + `focus_rvol_score.py` + the fleet's
validated `tv_scan.py`), each behind a capability marker, so the deployed prompt is the CONTRACT
and the recipe can change without a redeploy at all.


## 2026-11-12 — the ENGINE published three WRONG columns, and the checker could not see it (cron #07, 09:45 ET)

The 09:45 fire published through the engine (`focus_rvol_run.py` -> `focus_rvol_score.py`), and
the artifact passed `tools/check_focus_rvol_artifact.py` — **16 clauses, green** — while three of
its contract columns were wrong. The green gate was not a cover-up; the clauses for these three
columns simply did not exist. A checker that never asserts a column's SEMANTICS cannot find a
column that is semantically wrong.

### The three defects

1. **`rvol_intraday_live` was a RATIO divided by a SHARE COUNT.** The renderer wrote
   `rvol_now / tv_avg10d`, which printed values like `3.92e-07`. The contract wants the
   cumulative SESSION VOLUME over the 10-day average daily volume — a sane 0.04-2.5. A reader
   reading the published column as "the raw ratio" would have been reading a number seven orders
   of magnitude too small.
2. **`rvol_prev` was a literal `"n/a"`.** The earlier cross-check snapshot was never computed, so
   the artifact had no cross-check at all, and the published cross-check the prompt asks for
   (`rvol_at_09_38`) could not be checked against anything.
3. **`rvol_trend` was measured against the PREVIOUS SESSION** (`rvol_now - rvol_prev_session`),
   while the contract defines the trend as the EARLIER-SNAPSHOT delta (`rvol_now - rvol_prev`).
   The two are different questions: "is this name hot versus its own norm at 09:38?" versus "is it
   hotter than yesterday at the same hour?" The contract asks the first, and the trend column is
   what tells a reader whether a name is BUILDING or FADING inside the opening window.

All three are fixed in `tools/focus_rvol_score.py`. `rvol_prev` now reuses the fields
`eval_session()` was already computing for the cross-check (`early` = the 09:30 bar's volume,
`m_early` = the prior-10 mean of THAT bar), so the fix costs no extra fetch; the
session-over-session delta is kept as `rvol_vs_prev_session` so nothing is lost. The CSV now also
carries the audit columns `session_vol` and `tv_avg10d`, which make the raw ratio CHECKABLE.

### `slim()` is a PROJECTION, and it silently eats a field

`main()` projects each scored row through a fixed `keys` list before the CSV and the markdown are
rendered. **A field missing from that list is dropped without a warning** — it cost a whole
debugging round: `rvol_prev` and `session_vol` were computed correctly, and then vanished on the
way to the artifact, so the renderer printed `n/a` for values that existed in memory. The list
carries a comment saying so now. **When a computed value does not appear in the artifact, check
the projection before re-checking the computation.**

### Yahoo's opening window KEEPS SETTLING — two passes over one artifact must share ONE vintage

Two fetches of the SAME `interval=5m&range=1mo` 09:30-09:45 window returned DIFFERENT bytes
minutes apart on this fire: DPC +6.3%, BW +2%, and a thin name (IFNNY) **+42%** on the very same
window. Late prints keep filling it after the bar closes.

So the engine's fetch and a second pass's re-fetch computed the two halves of a published row on
**different data** — the same defect the contract warns about for the denominator ("both sides of
a crossing must share one denominator"), only with the NUMERATOR. The first attempt at this
artifact hit it head-on: 93 rows, and the recomputed `rvol_now` disagreed with the engine's on
many of them (worst case IFNNY, +42%).

**The fix that works: cache the raw chart responses BYTES** (wrap `focus_rvol_score._curl`, key on
the URL, write to a temp file and `os.replace` it) and let every pass read the cache. Then the
enrichment's recomputed `rvol_now` matches the engine's EXACTLY — 93 of 93 rows verified, zero
mismatch — and the artifact is ONE data vintage. **A cache mismatch means the passes did not share
bytes: never loosen the tolerance to hide it.** Re-scoring ~1,600 names takes ~275 s; with the
cache the second pass is free.

### The CBOE delayed quote is the better earlier snapshot, and it is live

`cdn.cboe.com/api/global/delayed_quotes/quotes/{SYM}.json` answers with its OWN
`data.last_trade_time` (e.g. `2026-11-12T09:38:22`) and a cumulative regular-session
`data.volume`. On CDNL it read 1,550,507 shares at 09:38:22 against the 09:30 bar's 1,569,552 —
**1.2% apart**, so it corroborates the truncated series and gives the earlier window a real clock
time instead of an assumption. `cross_check_source: cboe_delayed` is earned only when CBOE's own
timestamp is EARLIER than the fire; otherwise the series is truncated at the 09:30 bar
(`same_series_truncated`).

### The checker gained three clauses, and the repo's test gained a fault-injection shape

`tools/check_focus_rvol_artifact.py` now has 19 clauses:

- **C18** — `rvol_intraday_live` must equal `session_vol / tv_avg10d` (within 2%). This is the
  clause that would have caught defect 1.
- **C19** — a scored row must carry a COMPUTED `rvol_prev`. This would have caught defect 2.
- **C20** — `rvol_trend` must match `rvol_now - rvol_prev`. This would have caught defect 3.

`tools/test_focus_rvol_contract.py` gained a third shape — the one the engine actually shipped on
2026-11-12 (a mis-scaled raw ratio, an `n/a` cross-check, a trend that contradicts its own delta)
— and asserts the checker exits non-zero on it AND that C18, C19 and C20 each trip. **A checker
that has never been observed failing is a claim, not a check.**

### The engine's markdown was too narrow, and the front matter was missing the three dates

The rendered table carried 7 columns, so the reader had to leave the table to learn a name's
story; the front matter had `cron: 07`, no `focus_dir_date`, no `screen_data_date` and no
`lag_sessions`. The table now carries the contract's full column set, and the scorer reads the
sweep's own `Screen data_date:` line out of `focus.md` (`--focus-md`) so the three dates cannot
collapse into one. `lag_sessions` is a WEEKDAY count — a venue holiday inside the gap would add
one, so it is an upper bound, and the artifact says so.

### The 2026-11-12 result, for the record

The focus roster (12 names) was **quiet — 0 of 12 cleared the bar**, best name TNGX 1.19x — and
the wider union carried the day: **1,304 of 1,636 candidates scored, 182 above 1.5x and 133
crossings** across the scored set. The published rows were the 12 roster names, the top 25 of the
wider union and every name in the near-miss band (93 rows, 18 crossings). The alert list was
ordered by the trend delta: HP, NVDA and FRMI ACCELERATING, the rest fading — **21 of the 25
names above the bar were DECELERATING**, a broad opening burst being handed back. The 332
unpriced candidates (`no_session_bars`) were reported as unpriced, never as a zero.


## 2026-11-13 — five improvements to cron #07, from a post-mortem of the 2026-11-12 fire

The 2026-11-12 fire published its artifact 24 minutes after the 09:45 instant and the numbers
were right, but the post-mortem found three kinds of waste: duplicated compute, a screen that
could not say whether it was selective, and a missing dimension (the pre-market). All five
changes below are landed in the repo; the engine and the shared helpers are fetched at RUN time,
so they take effect on the next fire with no `cron_update`.

### 1. KEEP EVERY SCORED ROW, PUBLISH THE TOP (the near-miss tier was invisible)

`focus_rvol_score.py` truncated its output to `--top-n` (25 by default) BEFORE anything else
looked at it. The near-miss tier and the universe-wide counts are properties of the WHOLE
scored set, so they were not computable from a truncated list: **all 56 near misses of
2026-11-12 sat BELOW the top 25**. The JSON now retains every scored row; the markdown shows
the top `--top-n` of the wider union; the CSV carries the focus roster, the wider table and
EVERY near miss. The runner passes no `--top-n` on purpose (widening it would put 1,292 rows
in the markdown table).

### 2. ONE VINTAGE PER ARTIFACT

Yahoo's opening window keeps settling after the bar closes (2026-11-12: two fetches minutes
apart differed by +6.3% on DPC and +42% on a thin name), so a second pass over the same window
computes the two halves of a row on different data. The whole run is now ONE process: the
scoring pass, the near-miss selection and the pre-market pass all read the same series. The
2026-11-12 fire needed THREE engine passes (13.7 min of compute for a 4.6 min job) purely
because the passes were separate processes. **A cache mismatch means the passes did not share
bytes: never loosen the tolerance to hide it.**

### 3. THE PUSH COPIES AND STAGES ONE SLOT, NOT THE WHOLE OUTPUT TREE

`push_artifact.sh` copied `SRC_DIR` (default `/workspace/<OUT>`) into the worktree and staged
it. With `--out daily-screens` that is the ENTIRE output folder (2026-11-12: 773 files, 22 MB)
to publish two files. The script now derives the **SLOT** - the deepest directory holding every
`--add` path - and copies and stages only that. When the `--add` paths span different roots
there is no common slot and the old behaviour is kept.

### 4. THE CONTEXT, NOT JUST THE COUNTS

A screen that cannot tell a broad tape from a selective one is a false-positive machine.
Measured on 2026-11-12: **194 of 1,304 scored names (14.9%) cleared the 1.5x bar**, so "25 of 93
above the bar" read like a screen when the tape was broadly hot. The artifact now carries:

- the **scored universe's DISTRIBUTION** (median / p75 / p90 / p99 and the share of names at or
  above 1.275x / 1.5x / 2x / 3x) in `## Universe` and in the front matter;
- a **`selectivity` label** - `broad_tape` when >= 8% of the scored universe cleared the bar,
  `elevated` at >= 3%, else `selective`;
- the **counts for BOTH scopes** - the published rows AND the whole scored universe;
- the **near-miss tier ordered by the TREND DELTA**, so the names that are BUILDING come first.
  That band held 56 names and only 5 were building on 2026-11-12; ordered by level alone it
  published 51 dead names ahead of the live ones.

### 5. THE PRE-MARKET SHARE - the dimension the screen was missing

`pm_share_pct` = pre-market volume / (pre-market volume + session volume to the fire): the
share of everything published so far that arrived BEFORE the open. It separates a GAP
CONTINUATION (the move was priced in the pre-market) from FRESH OPENING ACTIVITY (the volume
arrived after 09:30). Measured live on one pre-market tape: **NVDA 95.5%, AAPL 13.5%,
CDNL 7.8%** - three completely different trades behind the same 09:45 snapshot.

**Yahoo cannot supply it.** With `includePrePost=true` it returns the extended-hours BARS, but
every pre-open bar carries volume 0 - on the live session AND on history (measured
2026-11-13). `includePrePost=true` also costs +64% bytes per response (161 KB -> 266 KB), so it
is fetched for the PUBLISHED ROWS ONLY, never for the whole universe.

**Nasdaq can**: `https://api.nasdaq.com/api/quote/{SYM}/extended-trading?assetclass=stocks&
markettype=pre` -> `data.infoTable.rows[0].volume` (a comma string). `assetclass` is REQUIRED
(without it the endpoint answers HTTP 200 with `data: null`) and so is a browser User-Agent.

**A REPLAY CANNOT MEASURE IT** - the endpoint serves TODAY's pre-market, which is a different
session. The engine refuses the value unless the fetch day IS the fire day, so a replayed fire
publishes `pm_vol_source: not_subtracted` and `pm_share_pct: n/a` rather than a wrong number.

### The checker grew a clause (C21) and the repo test grew a fault-injection shape

`tools/check_focus_rvol_artifact.py` now has 20 clauses; **C21** asserts that `pm_share_pct`
equals `pm_vol / (pm_vol + session_vol)` and that `pm_vol_source` is in the allowed set. The
repo's own test gained the pre-market share in its fixtures and a mis-scaled share in the
fault-injection shape - the test asserts the checker exits non-zero on it AND that C18, C19,
C20 and C21 each trip.
