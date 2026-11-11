# IMPROVEMENTS — cron #17 `us-stocks-in-play`

Findings from the 2026-11-04 pre-close fire (settled session, 15:50 ET).
Two are reusable by any routine that uses the TradingView scanner or the
`market-recap` bridge, and both cost a wrong board if missed.

**§10–§12 were added 2026-11-10** from the 2026-11-09 open slot, which took 25m17s: the
09:50 universe pull is now **pre-filtered** (a union of three legs, 10,696 → 7,517
requests, **0 of the 767 board names missed**), the **volume-basis factor comes from the
polygon call the routine already makes** (−2,328 requests), and the spec's two
conflicting instructions for the same published field are reconciled. The source is
**throughput-capped at ~17 req/s**, so fewer requests is the only lever that exists.

---

## 1. NEVER paginate a volatile TradingView filter — pull it in ONE call

**Measured 2026-11-04.** The trigger screen needs two filter families:
`|chg| >= 3%` and `|gap| >= 3%`, over ~5,600 equities.

| Pull method | `totalCount` | rows returned | unique symbols |
|---|---|---|---|
| Paginated, `range` 999 at a time | 1,852 | 1,996 | **1,454 — 398 names MISSED** |
| Single call, `range [0,9000]` | 1,852 | 1,852 | **1,852 — complete** |

`range` may be set above `totalCount`; the scanner returns exactly the matched set.
The failure mode is silent: the response looks healthy (rows >= totalCount), and the
artifact's "names priced" count is simply short.

**Why:** the universe churns *while* you paginate. Names cross the ±3% line
continuously during the session, so rows shift between pages: you get duplicates
(rows > totalCount) and you skip rows entirely (unique < totalCount).

**Rule:** for any filter on a fast-moving column (`change`, `gap`, `premarket_change`),
issue **one** scan call with `range [0, 9000]` and assert `len(unique) == totalCount`.
Paging is only safe on a static filter. Always print both numbers and fail loudly on
a mismatch — a `totalCount`/row-count mismatch is the only detector.

Same family, same day: the `type=stock` universe paginated to 3,958 unique against a
`totalCount` of 5,597 — a 29% hole that no row-count check would have caught
(rows returned 5,994 > totalCount).

## 2. The bridge's `market-recap` `price` at `market_state: post` is the AFTER-HOURS MARK, not the settled close

**Measured 2026-11-04, 88 names compared side by side** (bridge vs the TradingView
settled regular-session close):

| Measure | Value |
|---|---|
| median absolute price difference | **0.375%** |
| maximum difference | **5.34%** (MOD, which bounced after the bell) |
| bridge volume vs TradingView regular-session volume | **median ~+12%** |
| bridge `as_of` / `market_state` | `2026-11-04T21:03–21:04Z`, `post` |

`get_quotes` returns `market_state: post` with `as_of` exactly on the 16:00 ET bell.
The `price` it carries is the first post-close print, and its `volume` includes
post-close prints — which is why it reads high against a regular-session volume.

**This cuts against PROMPT-BLOCKS rule 7** ("prefer the bridge when two sources
disagree by more than 0.6%"), which is right for *quotes* but wrong for a **close**:
publishing the bridge's post-close mark as "the close" is exactly the error the
pre-close slot warns against.

**Rule:** at a post-bell slot, take the **settled regular-session close and volume
from the TradingView scanner** (re-pull it ~2 minutes after the bell, so the closing
auction has consolidated), and use the bridge for the `as_of` / `market_state` stamp,
for index and macro levels, and as a sanity cross-check — never as the close itself.
State the disagreement in the artifact's Method section.

The two sources are close enough to be a good cross-check (median 0.375%) and far
enough apart to matter on the names that bounce after the bell (MOD 5.34%, KD 3.53%,
MRNA 3.02%, DUOL 1.93%, LITE 1.75%). A 0.6% tolerance would have flagged 6 of 88 names.

## 3. Minor: `polygon-io grouped_daily` for the session being published

Unchanged from 2026-11-03 — the session's own bar was still not published at run time
(six attempts across the run). The RVol **denominator** is unaffected because it
excludes today by construction; the **numerator** has to come from the TradingView
re-pull. Recording it here so nobody treats "the bar does not exist yet" as a bug.

---

## 4. The one-call rule was in the docs but NOT in the skill spec — and the universe pull is worse than §1 measured

**Audited 2026-11-06 (the 09:50 ET open fire).** §1 of this file already said *"NEVER
paginate a volatile TradingView filter — pull it in ONE call"*. That rule lived **only in
this file**. `cloud-prompts/skills/us-stocks-in-play/SKILL.md` — the file the routine
actually fetches at RUN time — had **no** mention of `totalCount`, of `range`, or of the
one-call rule, so every fire had to rediscover it. The rule is now in the skill spec
(`#### Pulling the TradingView universe: ONE unpaginated call (2026-11-06)`), which is the
lever that changes the next fire with **no `cron_update` and no prompt drift**.

**Today's measurement is worse than §1's.** §1 measured a *trigger* filter (1,852 names,
398 missed). Today's accident was the **universe** pull, and the corruption was
duplication-heavy:

| Pull method | `totalCount` | rows returned | unique symbols |
|---|---|---|---|
| 9-page offset pull, `type` in (stock, dr), 1,500/page | 13,203 | 13,500 | **8,689 — a 34% hole** |
| **One call, `range [0, 6093]`** (same filter, US venues only) | 6,093 | 6,093 | **6,093 — complete** |

3,876 symbols came back **more than once**, with identical name, description, exchange and
type. This is the dangerous shape of the failure: the row count (13,500) is *larger* than
`totalCount`, so the §1 detector ("rows ≥ totalCount looks healthy") would have passed it.
**The only detector that catches it is `len(unique(symbols)) == totalCount`** — which is
why the skill spec now asserts BOTH numbers.

**Second finding: the scanner has a native `gap` filter and column.** The trigger set's gap
leg does not need to be computed locally. `{"left": "gap", "operation": "greater", "right":
2}` is a valid filter (measured 2026-11-06: `gap > 2` → 3,461 names; `gap < -2` → 956).
The `gap` column on a row is the open-vs-prior-close gap, and it agrees with a
5-minute-bar reconstruction to a **median 0.000pp** (p90 0.50pp, max 5.47pp) across 644
names — so it is publishable directly, with the bar series kept for the 09:50 snapshot.

**Third finding, mechanical:** the checker's **section order** is enforced, and the
2026-11-05 open board placed its **gap annex after Tier C** — i.e. after the capped bulk
tiers — which violates the contract's own order (Tier A → Soft-A → **gap annex** →
TECH_WATCH → B → C). The spec already states that order; the 2026-11-06 board was written
to it, and the artifact contract section now says so explicitly.

---

## 5. The 1-day Yahoo range returns a LIVE bar, not a settled one — use the 5-day range

**Audited 2026-11-06 (the 15:50 ET pre-close fire).** The pre-close slot must publish the
**settled** regular-session close and volume, and the natural pull is
`range=1d&interval=1d`. **That range cannot carry a settle stamp at all**: Yahoo returns
exactly ONE bar, stamped at the **current moment** (`regularMarketTime`), not at the
session it contains. Two consequences, both silent:

1. **No settle test is possible.** A bar stamped `20:54Z` at 15:53 ET is the same bar that
   later reads `21:00Z`; the timestamp moves with the wall clock, so `ts >= 20:00Z` says
   nothing about whether the session has settled. The 2026-11-06 run's first settled sweep
   consequently stamped **0 of 2,064 names** as settled.
2. **A name that did not trade today silently returns the PRIOR session's bar** as if it
   were today's — so the "settled close" and the "settled volume" can both belong to
   2026-11-05. On 2026-11-06 that produced **166 names** whose Yahoo close disagreed with
   the Nasdaq official close by more than 0.6pp (max **11.7pp**), and **120 names** whose
   implied prior close disagreed by the same margin.

**The fix is `range=5d&interval=1d`.** In the 5-day series each bar is stamped at its
session OPEN (09:30 ET), so the bar whose ET date is the session date IS that session's
bar, and a name with no print that day carries `close=None` — the honest "no session"
answer. Measured on 2026-11-06 after the bell:

| Pull | Session close vs the Nasdaq official close | Session bar present |
|---|---|---|
| `range=1d&interval=1d` | live print; **166 names > 0.6pp off** | not identifiable |
| **`range=5d&interval=1d`** | **0.00pp median** on the sampled large caps (NVDA 186.64 = 186.64, AMD 449.04 = 449.04, MU 690.00 = 690.00) | **2,064 of 2,097** names |

**The settle test then becomes the SESSION DATE, not a clock threshold** — which also
removes the hardcoded-DST-offset trap the fleet already knows about: no `20:00Z`/`21:00Z`
constant is needed anywhere. **Never hardcode the offset.**

**Second, the volume must be pulled AFTER the closing auction consolidates.** A sweep run
at **16:22 ET** was already stale: the same names came back **0.1–0.3% higher** on a
**16:34 ET** re-pull, and one name was **20.03%** higher. Cross-checked against the Nasdaq
session volume the settled figure is **median ratio 1.0000** (p10 0.9968, p90 1.0000)
across 2,045 names. The prior board measured the same effect at up to 30.2% low. **Pull
the volume late, and if you pull it early, pull it again.**

**Third, use Nasdaq's OWN net change for the close-to-close move.** The scanner's
`percentageChange` and the implied prior close (`close − net`) reconcile to a **median
0.0028pp**, whereas Yahoo's prior bar is stale for ~120 illiquid names. One number per
field: **close + net + pct from Nasdaq, volume from Yahoo, denominator from polygon.**

## 6. `check_reply` asserts the OPEN slot's pace band on a PRE-close reply

`tools/check_in_play_artifact.py` is slot-aware for the markdown and the CSV — it switches
on `--slot` for the pace column, the band, the delta source and the watch block — **but
`check_reply()` is not.** It unconditionally requires the reply to publish the
**pace regime band** (`0.1077` / `0.1649` / `10.77` / `16.49`) and the **pace constant**
(`0.125`), which are the **open slot's** measure.

**This makes the checker's `--reply` mode unusable for the pre-close slot**: a correct
pre-close reply — which must publish **RVol** and must never publish `pace`, because the
two are different quantities on different denominators and are never comparable — **fails
the reply check for omitting the pace band.** The 2026-11-06 pre-close run therefore ran
the checker in its documented `--md`/`--csv`/`--slot` mode (20/20 checks passed) and did
**not** pass `--reply`.

**The fix belongs in the checker:** `check_reply()` should take the slot and assert the
pace band and the pace constant **only when `slot == "open"`**; for `preclose` it should
assert that the reply publishes **RVol** and carries no `pace` claim. Until that lands,
**do not pass `--reply` on the pre-close slot** — and do not "fix" a failing reply by
adding a pace band to a board that must not carry one.

## 7. Tier A requires a SOURCED catalyst — a high RVol is not a story

The 2026-11-06 first cut put **9 names in Tier A whose only attribute was a large RVol**
(`CIIT` 60×, `VSA` 4,301×, `SNT` 188×, `CDT` 13×, `STLN` 17×) with the reason *"no
same-session company catalyst verified"*. **That is a self-contradiction in the published
row**: Tier A is defined as *"liquidity floors + elevated RVol + **material same-session
catalyst**"*, and a name with no catalyst is a **Tier B** name by the pipeline's own
definition.

**Two distinct defects, both fixed in the run's own screen:**

1. **The tier must require the catalyst.** A name with no sourced catalyst now goes to
   **TECH_WATCH** (if its RVol is soft, 1.0–2.0×, and its turnover clears the
   TECH_WATCH floor) or **Tier B** — never to Tier A or Soft-A, whatever its RVol.
2. **A high RVol on a near-empty denominator is a number, not a signal.** `SNT 187.97×`
   and `CIIT 60.01×` are 10-session averages over a handful of shares. The published
   **RVol ≥ 2.0** bar plus the **$2M session-turnover floor** plus the **$50M market-cap
   floor** together keep a micro-float squeeze out of the tradeable tier; the artifact
   says so in its Method section.

**And the reasons must be researched, not asserted.** Ten of the eleven names whose
catalyst read *"no same-session company catalyst verified"* turned out to have a **sourced
same-session catalyst** once the routine actually looked: **CIIT** (FY results for the
year ended 31 July), **SNT** (Q3 2026 results before the open), **SERV** (Q3 revenue
+300%), **KRT** (missed Q3 sales), **PRAA** (lagged Q3 earnings and revenue), **BDSX**
(Q3 revenue growth offset by a sales-force change), **STLN** (Q3 loss, revenue beat),
**SKIN** (Q3 loss, topped revenue estimates), **GMED** (revenue $763.7m missed the $793m
consensus, **full-year revenue guidance cut** to $3.09bn from $3.18–3.22bn), **IRTC**
(revenue in line and adjusted EPS $0.82 beat, but full-year revenue guidance **1.5% below
consensus** and a $50m IP-litigation settlement charge), **SOLV** (Q3 EPS beat, the
separation nearing completion, three brokers raising targets). **Each of those is a
tradeable event; publishing the name with no reason was the run's own shortcut.**

**The rule this exposes: "no catalyst verified" means *the routine did not look*, not
*nothing happened*.** A name that moved 30–80% has a reason, and the reason is findable in
the issuer's own release. Research it, or say plainly that it could not be found.

## 8. A beta reason must match the SIGN of the move

The Tier B / TECH_WATCH rows carry a one-line reason. When the run classified the
no-catalyst names as *"the AI/beta reversal"*, the text was written once as *"rebound with
the software group"* — and then applied to **six names that FELL** (**TEAM -16.15%,
ADBE -2.90%, GH -1.67%, OKTA -1.44%, CRWD -0.14%, PANW -0.26%**). A published row that
says *"rebound"* next to **-16.15%** is a self-contradiction the reader has to resolve.

**The verb must be derived from the settled move, not hand-written.** The run now derives
it: a beta name that closed **up** reads *"rebounded with the … group"*, and one that
closed **down** reads *"sold with the … group"*. The reason text is a function of the
price, so it cannot drift from the price.

## 9. The $50M market-cap floor is a SCREEN, and the prior board already applied it that way

The 2026-11-05 board reported **0 names below the $50M soft floor** in its 1,933-name
tiered set — i.e. it applied the floor as a **screen before tiering**, not as a footnote.
The 2026-11-06 run's first cut left **21 names below $50M inside the tiered set**
(`CIIT $2.3m`, `CDT $0.5m`, `VSA $4.2m`, `STAK $14.3m`, `SNT $44.6m` …), several of them
in Tier A. **Applying it as a screen reproduces the prior board's chain** and keeps the
published board comparable across sessions — the same reasoning the skill already states
for the price and dollar-volume floors.

---

## 10. The 09:50 universe pull is PRE-FILTERED — and the pre-filter is a UNION (2026-11-10)

**Measured 2026-11-10, from the 2026-11-09 open slot (25m17s end to end).** The open
slot pulled 5-minute bars for **10,696 symbols** and kept **767** of them. That pull was
**11m49s — 46% of the whole run** — and it is pure overhead for the 93% of symbols that
cannot reach the board.

The first instinct is to raise the concurrency. **That was measured and it is worth
nothing.** 260 symbols per round, `range=5d`:

| Workers | Throughput | Failures |
|---|---|---|
| 12 | 17.1 req/s | 0 |
| 24 | 16.7 req/s | 0 |
| 48 | 16.7 req/s | 0 |

The Yahoo chart API is **throughput-capped at ~17 req/s per egress**, and the 2026-11-09
run was already at 15.1 req/s on 12 workers. The edge throttles; the worker pool does
not matter. **So the only way to make the pull faster is to make FEWER requests.**

The cut is a **union of three legs**, all computed from the ONE unpaginated scanner call
the routine already makes:

| Leg | Test | Catches |
|---|---|---|
| turnover | `close × volume ≥ $100k` | names whose 09:50 turnover could clear the $500k floor — including the big movers that had FADED by pull time |
| move | `abs(change) ≥ 2pp` OR `abs(gap) ≥ 2pp` | thin names the scanner prices correctly but whose turnover product is small |
| no price | the scanner cannot price the symbol | dead / unlisted / OTC — always pulled |

**Each leg alone is wrong, and the ground truth says so.** Tested against all **767** names
that made the 2026-11-09 board:

| Filter | Symbols pulled | Board names missed | of which ≥ 5% |
|---|---|---|---|
| turnover ≥ $500k | 3,407 | **100** | 14 |
| turnover ≥ $250k | 4,397 | **27** | 7 |
| turnover ≥ $100k | 5,839 | 3 | 0 |
| move band alone (≥ 2pp) | 3,192 | **110** | 11 |
| **move band OR turnover ≥ $100k OR no price** | **7,517** | **0** | **0** |

The move-leg failure is the interesting one, and it is a trap for anyone who assumes the
scanner's live quote is a proxy for the 09:50 state. **It is not** — the 09:50 → 10:00
drift is largest for the biggest movers: **SKHY +3.11% at 09:50 vs +0.84% at 10:00, NBIS
+7.41% vs +1.64%, CRWV +6.34% vs −0.37%, MRNA +3.46% vs +1.01%.** A band-only filter
misses exactly the names the routine exists to find.

**$100k is not a tuned number.** It is 5× headroom below the $500k floor, and the measured
miss count goes **9 → 0** between the $250k and $100k boundaries. The residual hole is
the symbol the scanner cannot price at all, and the artifact must disclose the pre-filter
and the universe size on both sides of it — a reader who knows a name was skipped can
weigh it; a reader who does not cannot.

**Net effect:** the pull drops from 10,696 to 7,517 requests (**−30%**), and with §11 below
the routine's total Yahoo traffic drops from 13,024 requests to 7,517 (**−42%**).

## 11. The volume-basis factor comes from polygon — there is NO second price pull (2026-11-10)

The 2026-11-09 open slot measured each symbol's own volume-basis factor by pulling a
**5-day 5-minute series and a 1-month daily series for 1,164 trigger survivors — 2,328
extra Yahoo requests, 3m00s.** That work was already done by the polygon call the routine
makes, and nobody noticed.

**Measured 2026-11-10: the Yahoo daily bar and the polygon daily bar are the SAME series.**
Yahoo trailing-10 mean ÷ polygon trailing-10 mean = **median 0.9996, p10 0.9966, p90
1.0000** across 1,158 symbols; the single-session volume ratio is **median 1.0002, p10
1.0000, p90 1.0053** across 1,162. Two consequences:

1. **The factor can be built from the polygon call that already happens.** `_shared/
   rvol_fetch.py` now returns the prior session's own daily volume in a `prior_session`
   block (`"capability": "RVOL_FETCH_V2"`), and the 5-minute series is fetched with
   `range=10d` so the prior session's 5-minute total arrives in the SAME response. The
   payload grows ~5KB → ~38KB per symbol, but the per-request time is flat (0.11s →
   0.14s measured) and the throughput ceiling is unchanged. **Net: −2,328 requests.**
2. **Today's board carried a small basis bias, and it is now gone.** The numerator was on
   the Yahoo daily basis while the denominator was on the polygon basis; the ~0.04%
   mismatch understated every published pace. Building the factor from polygon's own
   prior session puts numerator and denominator on one series.

The published CSV column `vol_basis_factor` keeps its meaning (< 1, the 5-minute series'
completeness against the daily bar), so published paces stay comparable with the boards
already on the branch.

**The helper's fetch now DEMANDS the capability marker.** An older copy of
`rvol_fetch.py` has no `prior_session` block, and the symptom of using it is silent: the
routine falls back to the second per-symbol pull and loses 3 minutes without saying so.
The CDNs cache `main` independently, so a marker check — not a file-exists check — is the
only way to be sure the fetched copy is the current one.

## 12. The skill spec told two routines to do the same thing differently (2026-11-10)

The open-slot section of the skill spec said **"Use the scanner's running session volume
as the numerator … so no correction is needed."** The pre-close board's practice — and the
2026-11-06 and 2026-11-09 open boards — used the **Yahoo 5-minute volume through the
09:50 bar** with a per-symbol factor instead.

The scanner's volume is the running total **at the moment the scanner is pulled**. If the
pull happens at 10:04 it already carries the 09:50 → 10:04 volume, so a "volume to 09:50"
built from it is wrong by exactly that increment — and the increment lands on the largest
movers. The spec now states the bar-based reconstruction explicitly (a bar's timestamp is
the START of its interval: the price at 09:50 is the close of the 09:45 bar, and the volume
to 09:50 is the sum of the 09:30, 09:35, 09:40 and 09:45 bars).

**The rule this exposes: a spec that carries two ways to compute the same published field
will have one of them used by half the fleet.** The open slot is the only routine that
publishes a "volume to 09:50", and it now says once, in the section that publishes it,
which reconstruction is correct and why.

**The change was verified by A/B, not by inspection.** The old script and the new script
were both run for the same date within minutes of each other, and the **`avg10` block came
out BYTE-IDENTICAL** (12,000 symbols, same ticker set, same values) — so the pre-close
slot's denominator is provably unaffected by the new field. The new `prior_session` block
returned the expected prior session (**2026-11-06**) with **12,570** volumes and
`"capability": "RVOL_FETCH_V2"`, and its volumes agree with the Yahoo daily bar to a
median of **1.0002**.

## 13. The trailing-10 denominator is a LIVE upstream series — it moves between boards (2026-11-10)

Found while A/B-testing the helper. Fetching the same ten sessions (2026-10-26 →
2026-11-06) on 2026-11-09 and again on 2026-11-10 returned **three symbols whose
10-session average changed materially**: **NCI −87.5%, JOB −96.7%, OFAL −90.0%**. The
changes are exact fractions (−7/8, −29/30, −9/10), which is the signature of **one
session's volume being restated upstream**, not of a drifting average.

**This is upstream drift, not a defect in the routine** — and it is invisible unless you
look, because the helper reports `n = 10` for every symbol either way: a symbol with one
session restated still has ten sessions, so it passes the completeness test and its
denominator silently changes.

**What it means for the fleet:** the pre-close board's `RVol` for a name can differ from
the previous board's for reasons that have nothing to do with the tape. That is inherent
to a market-wide denominator read from a live feed, and the published `avg_vol_10d` is the
honest value on the day it was read — but a board-to-board comparison of RVol for these
names should not be read as a change in the stock. **The rule: the denominator is dated,
and a published pace or RVol carries the date of the denominator it was computed against.**

**The same argument applies to the volume-basis factor**, and it is why the factor stays
per-symbol: it measured **0.856** on 2026-11-05 and **0.9168** on 2026-11-09, so a global
constant applied to either day would be wrong for a large part of the universe. A constant
is not a shortcut here; it is a wrong number.

## The open slot's tier boundaries are a CALIBRATION, and the 2026-11-10 board measures them exactly (2026-11-11)

Measured on the 2026-11-10 open board's own candidates CSV (531 rows) while rebuilding the
2026-11-11 open board. Four things the spec does not state outright, and one of them is a drift.

**1. The TECH_WATCH / Tier B boundary is `pace`, not turnover.** Every one of that board's 270
TECH_WATCH rows has `pace >= 1.00` (minimum exactly 1.00) and **0 of its 230 Tier B rows reaches
1.00** (maximum exactly 1.00). So TECH_WATCH = "traded on size" and Tier B = "the same move on
below-normal volume". Turnover does NOT separate them: TECH_WATCH runs all the way down to the
$0.5m floor and Tier B reaches $146m. The 2026-11-11 board reproduced this rule exactly and got
239 / 263, in the same proportion as 270 / 230.

**2. The Tier A pace bar drifted between the spec and the board.** The spec says the open slot's
Tier A bar is `pace >= 1.5` ("the bar is 1.5x, not 2.0x"), but the 2026-11-10 board's Tier A rows
have a **minimum pace of 2.01** and its Soft-A rows **top out at 1.49** — that board used 2.0.
On 2026-11-11 the board followed the SPEC (1.5), which moved **PBR and PBR.A from Soft-A to
Tier A**. A reader diffing the two boards sees a tier change that is a threshold change, not a
tape change. **Name the bar in the board's Method section** — 2026-11-11 does.

**3. A catalyst-free name does not belong in Soft-A.** Soft-A is a MATERIAL SAME-SESSION catalyst
with a soft pace. Three big catalyst-free names (ORCL, GEV, TTD) printed at pace 1.13-1.30 on
2026-11-11, which the rule above puts in TECH_WATCH (pace >= 1.0). The first draft of that board
put them in Soft-A and the published table then contradicted its own heading ("material
same-session catalyst" over three rows whose reason reads "no same-session company catalyst
located"). They were moved to TECH_WATCH and the tier published as **0 names** with the reason
stated. An empty tier is a legitimate outcome; a tier whose heading contradicts its rows is not.

**4. On a one-catalyst day, the concentration IS the finding.** 516 names cleared the 09:50
trigger and most of them were a single print (CoreWeave's Q3) expressed 516 ways. The board has
to say that in the headline — "the breadth is not 516 independent stories" — because 239
TECH_WATCH rows otherwise read as 239 separate calls.

**Also measured: the intraday gap reconstruction is looser than the settled one.** On 2026-11-11
the 5-minute reconstruction's gap agreed with the scanner's native `gap` column to a **median
0.12pp, p90 1.02pp** over 516 names (the spec quotes 0.003pp / p90 0.43pp for the settled
pre-close case). Publish the reconstructed gap alongside the reconstructed price so one row
describes one instant, and do not mix the scanner's gap with the rebuilt price.

**Also: the halts and shares-outstanding columns were null on EVERY row** of the 2026-11-11
scan (13,380 symbols), so the halt state was not measurable and the low-float rule could not be
evaluated at all. Both are disclosed as degraded sources; neither may be turned into a count or
a flag.
