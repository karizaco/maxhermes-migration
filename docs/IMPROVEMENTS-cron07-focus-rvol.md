# Improvements — cron #07 `stock-screener-focus-rvol-09:45`

- **Audited:** 2026-11-10 (the 09:45 ET fire, `2026-11-10`)
- **Scope:** the intraday RVOL screen's data path — the live price, the session-volume window, the
  10-day denominator, the prior-10 same-window baseline, the cross-check snapshot and the
  pre-market exclusion.
- **Artifact under review:** `daily-screens/2026-11-10/focus-rvol-snapshot.md` + `.csv` (outputs repo,
  cron #07)

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
