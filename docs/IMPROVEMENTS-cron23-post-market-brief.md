# Improvements — cron #23 (agentic-post-market-brief): the brief is named POST-MARKET, so tomorrow's setup is the product

Four reader-hostile defects in the post-market brief, fixed in the routine's **skill spec**
(fetched at run time) plus a machine checker that fails a run which breaks the contract.
**The prompt was not touched** — a skill-spec change needs no `cron_update` and carries no
byte-drift risk.

Evidence: the 2026-11-03 and 2026-11-04 artifacts and replies, the 2026-11-05 artifact, and
the three data paths, all re-measured on 2026-11-06.

---

## 1. What was wrong

### 1.1 "Tomorrow's setup" was at section 9 of 10

The 2026-11-03 artifact's most valuable content was its last third — `## Tomorrow's setup —
Wednesday 2026-11-04` with the futures/overnight read, the economic calendar, the earnings
calendar and the news-to-watch list. The brief is named **post-market**: its job is to set up
**tomorrow**, and tomorrow was buried.

Measured section positions (H2 order):

| artifact | position of `## Tomorrow's setup` |
|---|---|
| 2026-11-03 | **9 of 10** (after Day's tape, sector rotation, the EOD review, both after-hours sections) |
| 2026-11-04 | 8 of 9 |
| 2026-11-05 | 8 of 9 |

### 1.2 The after-hours movers had no LEVEL

The 2026-11-03 reply gave DOX −44.61%, SWKS −17.35%, ANET +9.47% with their catalysts and
nothing else. A reader cannot act on "ANET +9.47% AH" without knowing where the 16:00 close,
the after-hours high/low and the gap threshold sit. The after-hours table carried
`ticker | after-hours | regular | AH volume | catalyst` — a percentage, not a level.

### 1.3 The participation read was a mid-paragraph statistic

The best sentence in the 2026-11-03 brief was: *"the index was green but the median stock was
not… 2,489 of 4,896 names closed lower, and the liquid set ran 689 up / 921 down, 0.75:1. SPY
+0.30% vs RSP −0.33% is a 63bp cap-weight penalty — a semiconductor squeeze inside a flat
tape."* It sat in the second paragraph, unnamed, with no history: a reader could not tell
whether a 63bp divergence was a regime or a wobble.

### 1.4 The reply had no "tomorrow" line

The reply formatting defects were already fixed (the `### Signal` header is no longer jammed
onto the first bullet, and every bullet carries one ticker — verified on the 2026-11-04 and
2026-11-05 replies). The **content** gap was not: neither the 2026-11-03 nor the 2026-11-04
reply had a "tomorrow" line, so a reader had to open the artifact to learn what tomorrow looks
like. The 2026-11-05 run improvised one *inside the artifact* (`### Tomorrow's setup, in three
lines`) but did not put it in the reply.

## 2. What changed

### 2.1 The contract lives in the skill spec — `§5` of
`cloud-prompts/skills/agentic-post-market-brief/SKILL.md`

- **§5.3 the spine.** Nine `##` sections in a fixed order, with `## Tomorrow's setup` as
  **section 2, right after the TL;DR**. Sections that used to be separate H2s (the universe /
  watchlist EOD review, the day's movers, the breadth block) are folded into the nearest H2 as
  **H3 subsections** — content is never dropped, only headings are reorganised. The checker
  fails an unexpected `##`.
- **§5.4 "Tomorrow's three things to watch"** — exactly three bullets, one name each, each
  with a **level** (the §5.7 gap-fill level, or the 16:00 close) and a **catalyst**. It appears
  in the artifact *and* in the reply.
- **§5.5 the participation read** — six **named metrics** as rows of a `### Market read` table:
  `advancers`, `decliners`, `unchanged`, `median_name_move_pct`, `cap_weight_penalty_bp`
  (signed), `liquid_adv_dec_ratio`. The TL;DR must name them too.
- **§5.6 the cap-weight penalty with its 5-day history** — one table, five dated sessions.
- **§5.7 the after-hours level set** — every row carries `prior_close`, `ah_last`, `ah_high`,
  `ah_low`, `ah_volume`, `gap_pct`, `ah_range_pct`, `gap_fill_level`, with a deterministic
  gap-fill rule and a per-row self-verification identity.
- **§5.8 the reply contract** — `### Signal` alone on its line followed by a blank line
  (the emitted string contains `### Signal\n\n`), one ticker per bullet, the three-things
  section, and the top item of the open research queue carried into the reply.
- **§5.9 the checker** — fetched at run time with a capability marker so a stale copy cannot
  win the ladder.

### 2.2 The checker — `tools/check_postmarket_brief.py` (new)

`python3 tools/check_postmarket_brief.py --artifact <md> [--reply <txt>]` — exit 1 and one
printed line per failure. It asserts the marker, the spine and its order, the five setup H3s,
the three-things bullets, the six market-read rows, the 5-session history, the after-hours
columns and every row's cells, the open research queue, and the four reply rules.

### 2.3 The regression test — `tools/test_postmarket_contract.py` (new)

Builds a contract-shaped artifact and reply, requires exit 0, then mutates them twelve ways and
requires the checker to fail each time.

```
13/13 checks behaved correctly
RESULT: the contract is satisfiable and every breach is caught
```

### 2.4 What did NOT change

- **The source ladder.** bridge `market-recap` for closes/movers/macro/history, the TradingView
  scanner for breadth and extended hours, cron #20's CSV for the universe, web for catalysts
  and calendars. The put/call **component split is still never invented** — the total was
  sourced (0.87 on 2026-11-03), the components disagreed (0.56 vs 0.67), and the 2026-11-03
  run correctly refused to invent one. §5.10 keeps that rule.
- **`## Open research queue` stays**, with its top item carried into the reply.
- **The prompt** (`cloud-prompts/cron-prompts/23-agentic-post-market-brief.md`) is byte-for-byte
  unchanged — it fetches the skill spec at run time, so the contract lands on the next fire
  with no `cron_update` and no drift risk.

## 3. The evidence

### 3.1 The checker bites on the three real pre-contract artifacts

| artifact | failures |
|---|---|
| `daily-briefs/2026-11-03-post-market.md` | **28** — wrong marker, spine out of order, `Tomorrow's setup` after `Day's tape`, no `### Market read`, no cap-weight history, after-hours table missing `prior_close` … |
| `daily-briefs/2026-11-04-post-market.md` | **38** — same, plus `## Breadth & volatility` / `## Universe EOD review` as unexpected `##` |
| `daily-briefs/2026-11-05-post-market.md` | **36** — same, plus `## Day's movers` / `## Watchlist EOD review` as unexpected `##`, and no `## Method notes` |

These artifacts *looked* fine. That is the point.

### 3.2 The participation metrics are computable from the published universe

From cron #20's `us-eod/2026-11-05.csv` (4,896 names), measured 2026-11-06:

| metric | value |
|---|---|
| `advancers` / `decliners` / `unchanged` | 666 / 4,145 / 29 |
| `median_name_move_pct` | −3.018% |
| `liquid_adv_dec_ratio` (cap > $2B, n = 1,627) | 218 : 1,406 = **0.155 : 1** |

### 3.3 The cap-weight penalty reproduces the published number, and its history is one call

`market-recap price_history` for `["SPY","RSP"]`, 2026-10-28 → 2026-11-05, measured
2026-11-06:

| session | SPY % | RSP % | `cap_weight_penalty_bp` |
|---|---|---|---|
| 2026-10-29 | −0.382 | +1.200 | −158 |
| 2026-10-30 | −1.773 | −0.786 | −99 |
| 2026-11-02 | −0.479 | +0.765 | −124 |
| 2026-11-03 | +0.299 | −0.327 | **+63** ← the published 2026-11-03 figure, reproduced |
| 2026-11-04 | +1.652 | +1.856 | −20 |
| 2026-11-05 | −4.409 | −2.893 | −152 |

### 3.4 The after-hours level set is one scanner call, and each row self-verifies

The TradingView `america` scanner exposes `postmarket_close`, `postmarket_high`,
`postmarket_low`, `postmarket_volume` and `postmarket_change`. Measured 2026-11-06 on a live
row (LGO): `close` 0.3241, `postmarket_close` 0.35, `postmarket_change` +7.99136% — and

```
(0.35 − 0.3241) / 0.3241 × 100 = 7.99136%      ✓ identity holds
```

so a row that disagrees with itself is dropped rather than published.

### 3.5 The next fire

The 2026-11-06 22:30 ET fire is the first under the new contract. Its artifact must carry the
marker `postmkt-artifact-v2`, the spine, the six named participation metrics, the 5-session
cap-weight history and the after-hours level columns — and its reply must carry
`### Signal\n\n`, one ticker per bullet, three things to watch with levels, and the top research
question. The checker is the gate.

---

## 4. The 2026-11-06 fire under the new contract — what it caught, and what the data path hid

The 2026-11-06 22:30 ET fire was the first run under `postmkt-artifact-v2`. It shipped
(`daily-briefs/2026-11-06-post-market.md`, byte-verified on `origin/main`) and the checker
passed after one fix. Four findings below are new; three of them changed the routine's **skill
spec**, so the next fire inherits them with no `cron_update`.

### 4.1 The contract caught exactly one thing, and it was a word

The checker failed with a single finding: a `### Signal` bullet naming GOGO and the FCC
carried **two** tickers. The checker's `NON_TICKERS` list is two-letter exchange/short-word
vocabulary plus a handful of three-letter abbreviations (`AMC`, `EPS`, `CPI`, `ETF`, `VIX`…) —
`FCC` is not on it, so the rule fired on an ordinary word. Rewritten as "the spectrum regulator",
the artifact and the reply passed: `CONTRACT postmkt-artifact-v2: ok`.

The lesson is mechanical and worth stating plainly: **the one-ticker rule is lexical, not
semantic.** Any second capitalised token in a bullet is a failure, including a regulator, an
agency or an acronym the writer never thought of as a ticker. The skill spec's §5.8 rule 2 now
says so and gives the workaround (name the organisation in words).

### 4.2 The futures quotes were frozen at the 16:59:59 ET settlement — the "overnight" was not published

Every futures row the bridge returned (ES=F, NQ=F, YM=F, RTY=F, ZN=F, and CL=F, GC=F, DX-Y.NYB)
carried `as_of` **16:59:59 ET** when read at the 22:30 ET fire — five and a half hours stale, and
the exact timestamp of the cash-close settlement. `market_state` still read `open`, so nothing in
the payload says "stale"; only the timestamp does.

At a 22:30 ET fire the contract's step 7 asks for "the overnight move … the setup, not the cash
close" — and the source of record cannot supply it. Publishing that table as *the overnight*
would have been a fabricated setup. The 2026-11-06 artifact publishes it as **Friday's
settlement**, says the post-18:00 ET Globex/Asia move is absent, and counts it in
`degraded_sources:` (2, alongside the CBOE page).

**Skill-spec change:** step 7 now requires reading `as_of` on every futures row and, if it is
more than ~30 minutes older than the fire, relabelling the table as the prior session's
settlement with the overnight explicitly declared unpublished.

### 4.3 The $1B screen floor hid the session's biggest after-hours movers

The contract's extended-hours screen keeps names above $1B of market cap. On 2026-11-06 the
screen's top gainer printed **+9.77%** (MCHPP); the session's actual after-hours leader printed
**+110%** (OMH, 420x relative volume), then TGE +71% (a 6-K at 17:14 ET transferring four hotel
assets for 198,630,381 newly issued shares, after which AMTD Group held 96.7% of the voting
power), PARA +18%, FTH +10% — and on the other side SDA −19% (566M shares) and VIVK −16%. A
reader who saw only the table would have believed the biggest movers of the night were +9.8% and
−7.0%.

**Skill-spec change:** §5.7 now requires one extra pull of the same screen *without* the
market-cap floor, published in `## Source health`, so the table is never mistaken for the whole
after-hours tape. The published table itself stays on the contract's screen.

### 4.4 The CBOE daily statistics page carries no session date stamp

The put/call page's embedded payload (`optionsData.ratios`) gives TOTAL 1.06, INDEX 1.07, ETP
1.25, EQUITY 0.89, VIX 0.70 and the volume split (11,225,416 puts / 10,589,764 calls,
21,815,180 contracts) — and no date anywhere in the data. The value was published as read, with
the session declared undatable, and counted as the second degraded source.

**Skill-spec change:** step 8 now says to publish the total as read, say the session cannot be
dated with certainty, and count it in `degraded_sources:` rather than asserting a session.

### 4.5 The cap-weighted sector column gave a non-index member index-like weight

The universe's cap-weighted Industrials return printed **+2.38%** while XLI printed **+0.12%**.
The gap is SpaceX: a $1.82T cap on a +8.6% day, which is **+1.82pp** of the sector number
(ex-SpaceX the sector is +0.71%, in line with its +0.84% median). Every other sector row
reconciled with its ETF within a few tenths.

The generalisable lesson is not about SpaceX: **a cap-weighted sector return computed over the
whole listed universe silently assigns index-like weight to a company that is not in the index**,
and the `cap_weight_penalty_bp` metric the TL;DR leans on inherits exactly the same
concentration. The artifact therefore names the constituent, publishes the sector with and
without it, and makes it the first item of the open research queue — which the reply carries, as
the contract requires.

**Skill-spec change:** step 3 now requires (a) de-duplicating share classes by
`cap_source_symbol` and dropping `EX_DISTRIBUTION` rows before weighting (cron #20's rule),
and (b) cross-checking each sector row against its ETF and publishing any >0.5pp gap.

### 4.6 What the participation read looked like, for the next run's baseline

| metric | 2026-11-06 |
|---|---|
| `advancers` / `decliners` / `unchanged` | 2,667 / 2,030 / 28 (4,725 usable names) |
| `median_name_move_pct` | +0.236% |
| `cap_weight_penalty_bp` | **+69** |
| `liquid_adv_dec_ratio` (cap > $2B, n = 1,785) | 868 : 910 = **0.954** |

The `cap_weight_penalty_bp` series continues across runs: −124, **+63**, −20, −152, **+69** for
2026-11-02 → 2026-11-06, with the +63 reproducing the published 2026-11-03 figure from the same
source and method.

### 4.7 The next fire

Fetch the spec; the 2026-11-06 rules (futures `as_of` assertion, the no-floor disclosure pull,
the CBOE date caveat, the sector de-duplication and ETF cross-check, the one-ticker wording
trap) are already in it. The checker is still the gate — and on 2026-11-06 it caught a single
word, which is the argument for keeping it.

---

## 5.0 The 2026-11-10 fire — a stale index row and three more universe flags

Fire date 2026-11-10, 22:30 ET, artifact `daily-briefs/2026-11-10-post-market.md`. Two findings
this run would have shipped clean without a human reading the numbers.

### 5.1 ^VXN came back as the PRIOR session — the stale-settlement trap is not futures-only

The skill tells you to assert `as_of` on every **futures** row (measured 2026-11-06: the rows
carried the 16:59:59 ET settlement five and a half hours after the close). The same failure
exists on the **indices** and nothing warned about it. Measured 2026-11-10, one bridge
`get_quotes` call returned:

| symbol | as_of | change |
|---|---|---|
| ^GSPC, ^IXIC, ^DJI, ^RUT, ^VIX, ^NDX, ^SOX, SPY, QQQ, IWM, DIA, RSP, SMH, GLD, TLT | 2026-11-10 | correct for the session |
| **^VXN** | **2026-11-09T21:00:00Z** | **-14.84%** |

The VXN row was the 9 November close. Published as "Nasdaq volatility fell 14.84%" it would
have been a fabricated statement about a day in which the Nasdaq fell 0.74%. **The checker does
not validate numbers** — `check_postmarket_brief.py` asserts structure, labels and level cells,
so an impossible number sails through it.

The rule, now in the skill spec: **read `as_of` on every row of every quote batch, indices
included. A row whose `as_of` is not the fire date is the prior session's reading — publish it
as such, mark it in the same table, and count it in `degraded_sources:`.** This run published
VXN 28.97 as the 9 November close with the stale stamp visible in the table, and counted it as
degraded source #2.

### 5.2 De-duplicating share classes is necessary but NOT sufficient — cron #20's CSV has three more flags

The 2026-11-06 rule (drop `EX_DISTRIBUTION`, one row per `cap_source_symbol`) is not enough on
its own. `us-eod/2026-11-10.csv` (4,893 rows, 4,521 after de-duplication) carries three further
`data_quality` flags that each corrupt a cap-weighted column in a way the checker cannot see:

- **`CAP_CARRIED` — the parent's cap, the class's own move.** GOOG and GOOGL each carry
  $3.515T; GOOG's own move was -0.3776% and GOOGL's -0.2499%. BRK-A and BRK-B each carry
  $1.258T; BRK-A +2.596% and BRK-B +1.398%. **Which row you keep changes the sector number.**
  This run kept the primary listing (the row without `CAP_CARRIED`), so Financials carried
  Berkshire at +1.398% (+0.17pp of contribution) rather than BRK-A's +2.596%.
- **`NO_CAP` — 241 rows.** They cannot be cap-weighted; exclude them from every cap-weighted
  column and from its denominator. They still belong in the unweighted participation read.
- **`NO_SECTOR` — 105 rows, 19 of them priced.** A bucket, not a sector. Ranking it alongside
  the sectors puts it at -0.316% and **displaces Utilities (-0.244%) from the bottom three** —
  a silently different top/bottom-three table.

### 5.3 The bug that is invisible because it is absurd: a doubled parent cap

With Berkshire counted twice, Financials' cap-weighted return prints **+28.2%** instead of
+0.28% — the parent's $1.258T is in the denominator twice AND its move is counted twice. The
same run, with the no-sector bucket left in, would have printed Utilities in the wrong place.

The generalisable rule, now in the skill spec: **assert that every cap-weighted sector return
is inside ±20% before publishing it.** Outside that range it is a computation bug, not a market
event — and it is exactly the class of error that passes the checker clean, because the checker
asserts structure, not numbers. (The same sanity instinct caught a stray `x100` in the
contribution formula on this fire, which would have printed Information Technology at -130.6%
instead of -1.31%.)

### 5.4 The participation read, for the next run's baseline

| metric | 2026-11-06 | 2026-11-10 |
|---|---|---|
| `advancers` / `decliners` / `unchanged` | 2,667 / 2,030 / 28 (4,725 usable) | **1,608 / 2,818 / 6** (4,432 usable) |
| `median_name_move_pct` | +0.236% | **-0.53%** |
| `cap_weight_penalty_bp` | +69 | **-34** |
| `liquid_adv_dec_ratio` (cap > $2B) | 868 : 910 = 0.954 | **702 : 909 = 0.772** (n = 1,611) |

The `cap_weight_penalty_bp` series continues: -124, +63, -20, -152, +69, **-34** for
2026-11-02 → 2026-11-10. A NEGATIVE reading means the cap-weighted index LAGGED the
equal-weight one — a mega-cap-led SELL-OFF, the mirror image of the +63 case on 2026-11-03.
The sign must be published, not just the magnitude.

### 5.5 The next fire

Fetch the spec. The 2026-11-06 rules (futures `as_of`, the no-floor disclosure pull, the CBOE
date caveat, the ETF cross-check, the one-ticker wording trap) and the 2026-11-10 rules (the
`as_of` assertion on EVERY index row, the `CAP_CARRIED` / `NO_CAP` / `NO_SECTOR` handling, the
±20% assertion on cap-weighted sector returns) are all in it. The checker is still the gate —
and it is not a number check, so the ±20% assertion is the run's own arithmetic self-test.

### 5.6 The 2026-11-10 artifact was CORRECTED after delivery — both "degraded sources" were mine

The 2026-11-10 brief shipped at 22:45 ET with `degraded_sources: 2`: the CBOE put/call read as
"a session that cannot be dated", and the ^VXN row flagged as a stale 9 November session. Both
turned out to be recoverable — and re-checking them on 2026-11-11 also surfaced a third error
that no degraded-source label could have covered.

**The CBOE page carries the date; the EXTRACTION dropped it.** The 2026-11-06 finding ("the
embedded data carries no session date stamp") was an artefact of asking `web_fetch` to
summarise the page: it returned the ratios and the volumes and silently omitted the fields.
Fetched raw, the payload carries, next to the volume and ratio blocks:

```
"selectedDate":"2026-11-10","minDate":"2019-10-07","prevTradingDay":"2026-11-10"
```

`selectedDate` **is** the session stamp, and on 2026-11-10 it equals the fire date — so the
published total put/call 0.95 (equity 0.77, index 1.02) was the 10 November session all along.
The page also carries splits a summary never returned: ETP 1.04, SPX+SPXW+SPXO 1.11, XSP 0.98.
Three parameter forms (`?date=`, `?selectedDate=`, a path segment) all returned the same
server-rendered payload, so the page always serves the LATEST session — the one that just
closed at the 22:30 fire.

**^VXN was available from two dated places all along.** The bridge's `price_history` for `^VXN`
returns the dated row for the fire date (2026-11-10 close 28.57, previous_close 28.97,
daily_return_pct -1.381), and Cboe's own dated close file
(`https://cdn.cboe.com/api/global/us_indices/daily_prices/VXN_History.csv`, columns
`DATE,OPEN,HIGH,LOW,CLOSE`) gives the same 28.57 for 11/10/2026 and 28.97 for 11/09/2026 — two
independent sources agreeing to the cent, plus the intraday high of 30.22 that the quote row
never carried. The `get_quotes` row was the 9 November close **and** the 9 November move
(-14.844% in `price_history` is exactly the -14.84% it carried), which is what identified it.

**The third error was neither a source problem nor a stale row — it was arithmetic.** The brief
said the VIX "went up 11% intraday". The VIX high of 21.61 is **+8.5%** against the 19.92 prior
close; 11% was the high-low RANGE expressed against the prior close (21.61 → 19.29). Same
number family, different denominator, and the sentence as written was false.

**What the correction did.** The artifact was re-pushed in place at 01:47 ET on 2026-11-11 with
the VXN row corrected to 28.57 / -1.38% (day high 30.22), the VIX sentence corrected to 8.5%,
a correction note carrying the reason next to the corrected numbers, `degraded_sources:` set to
0, and the reply's `errors:` set to 0 to match. The reading itself did not change: volatility
spiked intraday and faded while the index fell — and with the true VXN in hand, that is now a
statement about BOTH volatility indices instead of one plus a stale footnote.

**The generalisable lesson, now in the skill spec.** A degraded source is often a **broken
extraction**, not a broken source, and the fastest way to find out is to fetch the payload
yourself and look for the fields a summariser would drop. The second lesson is that
`get_quotes` is not uniformly dated **within one call**: on 2026-11-10 it returned the prior
session's ^VXN while every other symbol in the same call was correct — so a per-row `as_of`
assertion, and a dated read for the volatility indices, are not optional. The third is that a
published percentage needs its denominator named: an intraday move against the prior close and
an intraday range against the prior close are different claims, and the artifact's own numbers
made the difference visible (21.61 high, 19.92 previous close, 19.46 close).

---

## 2026-11-11 — the scanner validator rejected the routine's OWN body, and the after-hours tape moved between vendors

**Evidence from the 2026-11-11 fire (session `2026-11-11`, 22:30 ET).**

**1. The fleet's validated scanner client refused the body that this routine's own skill spec
§5.7 documents.** §5.7 publishes the after-hours screen body with
`{"left":"type","operation":"in_range","right":["stock","dr"]}`. `_shared/tv_scan.py` refused it:

```
[error] filter-in_range-no-second-right: filter[0] uses in_range but carries no second_right
        - a single value is a 400
        FIX: add "second_right"
```

The validator's rule was written for the NUMERIC form of `in_range` (a scalar `right` plus a
`second_right`). But the endpoint accepts a LIST-valued `right` on a categorical column as a
VALUE SET. Verified directly against the endpoint on 2026-11-11 with the skill spec's body
verbatim:

```
POST https://scanner.tradingview.com/america/scan  (skill spec §5.7 body, unmodified)
HTTP 200  totalCount=2045  first rows: AVEX, TTEK, VERX ...
```

So the body was correct and the **validator** was wrong. The 2026-11-11 run had to work around it
by dropping the `type` filter and filtering the returned rows on the `type` column locally — which
returned the same top three gainers (AVEX +11.29%, TTEK +8.48%, VERX +5.05%). A future fire that
trusted the validator would either abandon the validated client (losing its truncation check) or
drop the `type` filter without a replacement, silently letting funds into a screen the contract
defines as stocks.

**The fix is in the shared helper, so it lands fleet-wide with no `cron_update`.**
`cloud-prompts/_shared/tv_scan.py` now requires `second_right` only when `in_range`'s `right` is a
SCALAR; a list-valued `right` is accepted as a value set. Two selftest cases were added (list-valued
`right` alone, and list-valued `right` with a `second_right`): `selftest: 13/13 validator cases
passed`. The skill spec §5.7 now also says to send the body through the validated client rather
than raw curl.

**2. The after-hours print is not a settled number, and vendors disagree.** The same name, the same
session, three different extended-hours changes:

| Vendor / minute (ET) | CRWV after-hours change |
|---|---|
| Public, 17:30 | -2.37% ($59.33) |
| MarketBeat, 18:10 | -7.12% ($56.45) |
| TradingView scanner, ~22:35 | -6.37% ($56.90) |

The 16:00 close is settled; the extended-hours print keeps moving. The skill spec §5.7 now says to
publish the scanner as the source of record, state that the print is a snapshot as of the fire, and
name a materially different vendor number in `## Source health` rather than blending the two. The
2026-11-11 artifact does exactly that, in the news-to-watch bullet for CRWV and in Method notes.

**3. A cross-source previous-close convention, worth knowing before mixing the two files.**
Cron #20's `us-eod` CSV and the bridge's `get_quotes` can disagree on the SAME name's day change by
up to ~0.1pp, because they use different previous closes — the CSV's official venue close against the
bridge's Yahoo reference print. On 2026-11-11: NVDA's CSV row reads `change_pct 2.842` off a close of
`173.7` (implying a previous close of ~168.89) while the bridge reads `+2.92%` off `173.73` with a
`previous_close` of `168.796`. Every price and change published in the 2026-11-11 brief is the
bridge's; the CSV is used only for participation counts, the median name move and the sector weights,
and the two are never mixed in one cell. That rule is now in the artifact's Method notes.

**Also carried forward from this run:** the artifact passed `check_postmarket_brief.py` (with
`--reply`) on the FIRST attempt, and the two `degraded_sources` were both real and both published —
the sub-$1B after-hours leaderboard was pulled 400 of 2,950 names per direction (not paged to the
end), and cron #20's universe covers common stocks only, so the three funds on the watchlist have no
volume-versus-average.

---

## 2026-11-12 fire — the one-ticker rule again, this time on a trial name

**Date:** 2026-11-12 (the 22:30 ET fire, session `462797923590223`) · **Scope:** cron #23's skill spec
§5.8 rule 2 and the reply's `### Signal` bullets.

The 2026-11-12 artifact passed `check_postmarket_brief.py` on its own; the REPLY failed the
one-ticker rule on its first run:

```
FAIL: reply: a `### Signal` bullet carries 2 tickers (SLS, REGAL) — ONE ticker per line
```

The bullet was `- SLS +20.13% after hours — the Phase 3 REGAL trial hit its prespecified 80th
event; topline expected in November.` — one real ticker (SLS) and one TRIAL NAME. `REGAL` is not on
the checker's `NON_TICKERS` list, and the checker's ticker regex is mechanical, so a caps trial name
reads as a second ticker.

This is the same defect class the skill already warns about with "FCC", and it is the RECURRING
case for this routine: after-hours earnings reactions are full of named clinical programmes (the
SELLAS REGAL trial on 2026-11-12, Cerebras' own named cloud wins on the same night), and a brief
that names them in caps will fail this check on a growing share of fires.

**The fix is in the skill spec** (`cloud-prompts/skills/agentic-post-market-brief/SKILL.md` §5.8
rule 2), which is fetched at RUN time — so it lands on the next fire with NO `cron_update` and no
prompt drift: the rule now names the trial-name case explicitly and says to write the trial in
words ("the Phase 3 trial"), keeping the caps token for the ticker alone. The checker was NOT
weakened: "REGAL" was deliberately NOT added to `NON_TICKERS`, because the correct fix is to write
the bullet correctly, not to teach the checker that a trial name is a ticker.

**Also carried forward from this run.** The artifact and the reply were consistent on
`degraded_sources: 3` / `errors: 3`, and all three were real and published: cron #20's universe
CSV carries 370 rows with no sector (excluded from the sector ranking) and 52 rows with no price
(excluded from the participation read); the watchlist's three ETFs are not in the equity universe so
their volume-versus-average is `n/a`; and the extended-hours print is a single-vendor snapshot of a
moving tape (CBRS read +18.34% on the scanner against +12% to +18.41% elsewhere for the same
session). The `### Signal` bullet count, the ten-row after-hours table's level set and the three
"tomorrow's things" bullets all passed on the second run.
