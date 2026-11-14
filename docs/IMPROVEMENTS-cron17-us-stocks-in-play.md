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

## 2026-11-12 (open slot) — Yahoo's 5-minute VOLUME field is corrupt on a minority of names, and it silently inflates `pace` by an order of magnitude

**The defect.** The open slot's pace measure is the session volume to 09:50 divided by the trailing-10
average. The numerator is built from Yahoo's 5-minute bars, and on a minority of names the intraday
**volume** field carries impossible prints. Measured on the 2026-11-12 open fire:

| Bar | Yahoo 5-minute volume | What it should be |
|---|---|---|
| NVDA 09:30 | **167,140,999** shares | ~3-4m |
| NVDA 09:40 | **260,594,722** shares | ~3-4m |
| NVDA 09:50 | **292,013,829** shares | ~3-4m |

NVDA's **entire** session volume on Yahoo's own daily bar was 310,068,313 shares at 10:35 ET, and the
scanner's live volume field said 183,522,926 at the pull. The four corrupt bars alone summed to
786m shares — more than twice the whole session. Unrepaired, this published a **pace of 23.29** and a
**$107.9bn** turnover to 09:50 for the largest name on the board. The true figure is a pace of
**2.89** and **$13.4bn**. The error lands on the largest movers, which is exactly the set the board
is about.

**It is not only inflation.** On the prior session the same series summed to **243.9m** against a
daily bar of **313.4m** for NVDA — a 0.78 factor against a measured population median of **0.866**
(3,898 symbols measured, p10 0.713, p90 0.980). So the per-symbol volume-basis factor, which is
measured on the PRIOR session, cannot repair a corrupt bar in the CURRENT session: the factor and the
numerator come from different sessions.

**Two other traps measured at the same time, both of which look like a working cross-check:**

1. **The TradingView scanner's live `volume` column is STALE against the consolidated tape.** It said
   183.5m for NVDA at 10:03 ET while Yahoo's daily bar read 310.1m at 10:35 ET, and it said 3.78m
   for MU at 10:05 ET when the 5-minute series had already printed 6.85m by 09:57. Using it as the
   session-volume bound flags 3,153 of 4,572 names as impossible. It is not a session total.
2. **The 09:30 bar is systematically larger than the others** (it carries the opening-auction and
   some pre-market flow): NVDA 40.7m on 2026-11-11 against 3.6-8.8m on every other bar. It is not
   necessarily corrupt — but a bar carrying more than 8x the symbol's own median 5-minute bar volume
   is, and that test catches the genuine corruption (NVDA 167m and 261m).

**The repair (applied on the 2026-11-12 open board, and the rule for every future open fire):**

1. Cap every 5-minute bar at **8x the symbol's own median RTH 5-minute bar volume** across the 10-day
   window. A 5-minute bar cannot plausibly carry 8x the symbol's typical 5-minute volume.
2. Put the session on the daily-bar basis with the per-symbol factor measured on the prior session
   (polygon `grouped_daily`), exactly as the spec already requires.
3. **Cross-check the survivors against Yahoo's own `interval=1d` bar** (one request per name — cheap:
   527 survivors in 35 seconds). The daily bar is the physical bound: the volume to 09:50 cannot
   exceed the session volume at pull time. If the 5-minute sum still exceeds it, rescale the session's
   bars and flag the name.
4. Use the daily bar's **official prior close** rather than the 5-minute reconstruction. On
   2026-11-12 that corrected 21 of the 527 survivors by more than 0.5%.
5. Publish the repaired names with a flag in the candidates CSV (`volume_prints_repaired`,
   `volume_rescaled`) and name the defect in `## Source health`.

**Why this matters for the contract.** The pace is published as a *screen*, but a 6x error on the
board's largest name is not a screen error — it is a wrong number in the head of the table. The
checker reconciles the pace against the published columns, so it cannot catch this: every published
column was internally consistent and the arithmetic was wrong at the source.

**Cross-check that worked and should stay:** the shared helper `_shared/preopen_feed.py`
(`merge` mode) rebuilds the 09:30 open from the same bars and its gap agreed with this board's gap
column to a **median of 0.02pp** across the 12 names cross-checked (NVDA -14.07 vs -14.07, NBIS -22.50
vs -22.50, CRWV -16.25 vs -16.25, TWST -18.76 vs -18.76). The helper's `selftest` still prints 4 PASS.

## 2026-11-12 (open slot, post-run analysis) — the pace basis MIXES an archived factor with a live numerator, and the published pace is inflated by ~10-25%

**The defect.** The open slot's pace is

```
vol_basis_factor    = yahoo_5m_total(PRIOR session) ÷ polygon_daily_volume(PRIOR session)
session_vol_to_0950 = yahoo_5m_volume_through_09:50 ÷ vol_basis_factor
pace                = session_vol_to_0950 ÷ avg_vol_10d ÷ 0.125
```

The numerator is a **live** 5-minute pull (09:30-09:50 on the day being published). The factor is
measured on the **PRIOR session's 5-minute series**, and that series comes from Yahoo's *archive*.
The two are not on the same basis.

**Measured on 2026-11-12 (14 names, 2026-11-11 session, complete 78-bar series):**

| Measure | Value |
|---|---|
| polygon daily ÷ Yahoo 1d daily, 2026-11-11 | **1.000 – 1.017** (median 1.005) — the same series |
| **Yahoo 5m sum ÷ Yahoo 1d daily**, 2026-11-11 | **0.654 – 0.996** (median ~0.79) — the archive is SHORT |
| Yahoo 5m sum ÷ Yahoo 1d daily, 2026-11-12 through 11:35 ET | **0.999** — the LIVE feed matches the live daily bar |

So: **a completed session's 5-minute archive sums to only ~79% of its own official daily volume,
while the live session's 5-minute series matches its live daily bar.** Applying an archived
factor (≈0.79) to a live numerator overstates the daily-basis volume by roughly **1/0.79 ÷ 1/1.0
≈ 25%**, and by 10-25% for the names measured. The published pace is **too high**, and the error
is invisible to the checker: every published column is internally consistent.

**What it costs.** Re-tiering the 2026-11-12 board with the pace scaled down by the measured
bias:

| Bias | Tier A | Soft-A | TECH_WATCH | Tier B | tier flips |
|---|---|---|---|---|---|
| published | 22 | 1 | 178 | 322 | — |
| pace ÷ 1.10 | 17 | 6 | 146 | 354 | 37 |
| pace ÷ 1.15 | 16 | 7 | 130 | 370 | 54 |
| pace ÷ 1.25 | 16 | 7 | 112 | 388 | 72 |

The names that move are exactly the ones the reader acts on: **MSTR (published 1.51)** drops out
of Tier A, and the TECH_WATCH→B flips are the "moved but on no volume" names — AMAT, VRT, RKLB,
IONQ, CRCL, ILMN, SMTC, QBTS, MU, TSM, MRVL, LITE, SKHY, COHR, APH, BMNR, CLS.

**The proposed fix (NOT yet landed — it needs a same-session validation first).** At run time the
1d bar for TODAY is already being pulled for the survivors (the official prior close and the
volume bound). Use it as the anchor instead of the prior session:

```
vol_to_0950_official = 1d_volume_live_at_pull × (5m_sum_through_09:50 ÷ 5m_sum_through_pull_time)
pace                = vol_to_0950_official ÷ avg_vol_10d ÷ 0.125
```

Both terms are then on the same live feed, and the factor disappears — no cross-session
extrapolation, no archived series in the numerator's basis. **Validate before landing:** publish
the old and the new pace side by side for the top 30 names on the next fire and compare both
against the 15:50 SETTLED RVol for the same names (the settled session is the ground truth). If
the new basis is right, the open pace and the settled RVol must agree inside the 10.77%-16.49%
opening-share band; the old basis should miss it by roughly the bias measured above.

**A note on the 5-minute archive's shortfall.** It is not a missing-bar truncation (the
completed session has all 78 bars); the individual bars carry less volume than the official
daily bar. Whatever the cause, the ARCHIVE and the LIVE feed are different bases, and a
procedure that mixes them must reconcile them explicitly.


---

## 2026-11-13 (open slot) — the 09:50 pull engine: three discarded pulls, one wrong board, and the gate that stops both

**The run.** The 2026-11-10 open fire took **46m52s** from the fire instant (09:50:36 ET) to the
push (10:37:28 ET). The board itself was correct — 531 names, every tier priced, 31/31 contract
checks green — but **~20 minutes of the 48 were two discarded pulls and one wrong pull**, and
another ~9 minutes were available from the pull's own request pattern. The defects below are
**SILENT**: nothing crashed, nothing was empty, and each one published plausible numbers.

### 1. The three pulls

| Pull | What it was | What it cost |
|---|---|---|
| **#1** | the venue-prefixed symbol (`NASDAQ:NVDA`) sent to Yahoo | **100% 404.** ~2 min, nothing usable |
| **#2** | the cookie'd session; the edge throttled it at ~3,750 processed | **~3,945 completed fetches (~7 min) destroyed** — the script wrote its output file only on completion, so killing it lost everything |
| **#3** | cookie-less, `range=10d`, **wrong prior close** | **11m18s** to produce a board where NVDA read **−21.50%** (really −4.10%) and QQQ **−6.55%** (really ≈−0.26%) — the whole market looked like a crash while the index was −0.30% |
| **#4** | cookie-less, `range=2d`, prior close rebuilt from the prior session's bars | **the good one** — 7,857 of 7,889 symbols in 632s (12.4 req/s) |

### 2. The five measured defects

1. **`chartPreviousClose` in a MULTI-DAY range is the close BEFORE the range starts.** With
   `range=10d` it is ~10 sessions old, so every move became a **ten-day move**. Nothing failed:
   the arithmetic was flawless, it just answered the wrong question. **Fix: the prior close is the
   last non-null close of the PRIOR SESSION's own bars** (already in the same response — zero extra
   requests). `chartPreviousClose` is used ONLY for `range=1d`.
2. **Some 5-minute bars carry a NULL close.** A picker that reads the 09:45 bar's close drops
   those names **silently** — **1,276 of 7,857** in one pull. Worse, the bar's *volume* is real
   even when its close is null, and dropping it under-counted the window. **Fix: the price is the
   last NON-NULL close at or before the cut, and every bar's volume counts.**
3. **The COOKIE'd chart session is throttled by the egress edge; the COOKIE-LESS one is not.**
   The throttled body is `Edge: Too Many Requests` — the **`Edge:` prefix defeats a
   `startswith("Too Many")` check**, so it was logged as a JSON parse error and the pull kept
   hammering a throttled endpoint with no backoff. **Fix: no cookie, no crumb, and `Edge:`/429 is
   classified as a THROTTLE — pause, back off, resume.**
4. **No checkpointing.** The pull accumulated everything in memory and wrote its file only on
   completion. **Fix: one JSONL line per symbol as it lands; a retry resumes.** A truncated pull is
   a FAILURE, never a shorter board.
5. **The venue prefix 404s.** `NASDAQ:NVDA` is not a Yahoo symbol; `SNUS/PH` must be `SNUS-PH`.

### 3. The pull was REQUEST-bound, not source-bound

| Mechanism | Cold throughput | 7,857 symbols |
|---|---|---|
| one `curl` process per symbol (what the 2026-11-10 run did) | **12.4 req/s** | 10m32s |
| one keep-alive connection per worker (12 workers × 20 URLs) | **101.3 req/s** | **~1m20s** |

Measured 2026-11-13 on 240 fresh (cold-cache) symbols, and confirmed live: 40 real symbols in
**0.6s** with 8 workers, with **39 of 39** reconstructed prior closes within 0.5% of Yahoo's own
daily bar (SPY 759.79 vs 759.81; QQQ 690.38 vs 690.38). The fleet's own 2026-11-10 measurement
("12 workers → 17.1 req/s, 24 → 16.7, 48 → 16.7 — more workers buy nothing") is the same
symptom seen from the other side: the ceiling was **per-request overhead** (fork/exec + TLS
handshake), so raising concurrency could never fix it. Reusing the connection does.

### 4. What landed: `tools/open_0950_pull.py` (capability `OPEN_0950_PULL_V1`)

The engine owns the universe (three unpaginated scanner calls, each verified against its own
`totalCount`), the pre-filter union, the pull, the 09:50 reconstruction, the floors and the gate.
It is fetched at RUN time by the skill, so **the fixes land on the next fire with no `cron_update`
and no prompt drift**. `tools/test_open_0950_pull.py` asserts every rule offline and requires the
gate to CATCH six distinct breaches (24 checks).

**The PUBLISH GATE** — a failed gate exits non-zero and **no open artifact is published**:

| | check | tolerance | the defect it catches |
|---|---|---|---|
| **G1** | the reconstructed 09:50 move for SPY/QQQ vs the live index move | 0.75pp (the 09:50→quote drift is 0.1–0.2pp) | a broken basis (the ten-day defect was **6.3pp** on QQQ) |
| **G2** | every **published** name's reconstructed prior close vs **Yahoo's own daily close** | **0.5%** (39 of 39 live names) | the ten-day prior close **outright** |
| **G3** | every published name carries a price, a prior close, a pace and a verdict; the published count equals the floor-cleared count | exact | a truncated pull |
| **G4** | the median \|reconstructed move − the scanner's change\| over the published set | 12pp (the correct basis reads 3.16pp) | a systematically wrong cross-section |

G2 is the exact check and it is cheap: the 1-day bar the survivors need for the live pace basis
carries the prior session's official close too. **G4 is deliberately loose** — the scanner's own
`change` column LAGS, so it is a last-resort detector, not a precision check (a word-boundary
gate on it would have produced false failures: the median drift on the published set is 3.16pp and
the p90 is 11.4pp).

### 5. The pace basis — published on BOTH, arbitrated by the pre-close slot

The section above (2026-11-12) proposed the live-feed basis and asked for a same-session
validation before landing it. **That validation is now instrumented, not landed**: the engine
publishes `pace` (the current, contract column) **and** `pace_live_basis` for every name, and the
**pre-close slot of the same session** publishes the open board's `pace`, the open board's
`pace_live_basis` and the **settled RVol** side by side for the open board's top-30 names. The
settled session is the ground truth. **The published pace column does not change until that
comparison exists, and the basis change lands as its own commit.**

Measured on the published 2026-11-10 board: the archived-factor basis inflated the pace by
**~12%** (factor median 0.8918). **No Tier A or Soft-A name changes tier** (the lowest Tier A
pace is 2.01, and even a 1.25 bias leaves it above 1.5) — but **~30 names move between
TECH_WATCH and Tier B** (270/231 → 240/261 at a 1.12 bias), and the pace column itself is
published on all 531 rows.

### 7. A SIXTH defect, found by the new gate: the published prior close was NOT the official close

The gate's **G2** check (the reconstructed prior close vs **Yahoo's own daily close** for the
prior session, tolerance 0.5%) fired on the FIRST full-scale run of the new engine — on the
2026-11-12 session, **26 of 646 published names** were more than 0.5% away, up to **1.4%** on a
$1.39 name (ABR 1.4099 vs 1.3900; GLAS 1.8950 vs 1.8700; BGS 3.6450 vs 3.6700; TWN 85.9450 vs
86.3800).

**The cause:** the 5-minute series' last bar close is only an APPROXIMATION of the session close
— the closing auction print does not always land in the bar series, and on a thin name the last
bar can carry a stale print. The gap and the move are measured against the prior session's
**official** close, so the engine now **re-bases every published name on the official daily
close**, re-applies the trigger and the floors afterwards, and publishes the two counts
(**524 re-based, 11 dropped** on that session). The same defect is in the published 2026-11-10
board (**26 of 531** names): it moves no Tier A or Soft-A name, but it is a real reference-price
error and the artifact must say so.

**The lesson for the fleet:** a reconstructed reference price is a reconstruction, not the price.
Where the source publishes the official price, **use it** — and gate the reconstruction against
it rather than trusting it.

### 8. The engine's measured throughput (full scale, live, 2026-11-13)

| Measure | Value |
|---|---|
| the pull (8,627 symbols, cookie-less, keep-alive, 12 workers) | **42.7 s** ≈ **202 symbols/s** |
| the same pull with one `curl` process per symbol (2026-11-10) | 632 s ≈ **12.4 symbols/s** |
| the universe (3 unpaginated scanner calls, each verified against its own `totalCount`) | ~10 s |
| the 1-day pass for the published names (the official prior close + the live volume) | ~8 s |
| **the whole open-slot data spine** | **~60 s**, against **10m32s** for the price pull alone |
| the gate | 4 checks, 635 published names, **prior_close_off = 0**, index deltas 0.12pp / 0.17pp, basis-sanity median 1.49pp |

### 6. The rest of the 46m52s

| block | time | verdict |
|---|---|---|
| the two discarded pulls + the wrong pull | ~20m | the defects above |
| the pull's own request pattern | ~9m available | keep-alive connections |
| the news fetch running CONCURRENTLY with the price pull | ~2m + it halved the pull's rate | fetch the news AFTER the pull, for the published names only |
| the checker read end-to-end (754 lines, 4 reads) before first use | ~2m30s | run the checker on a stub and let it name its own requirements |
| the Yahoo connectivity probing (4 calls to find a working UA/cookie) | ~1m | the recipe is now known and is in the engine |
| three render/check cycles (a hardcoded claim about which names were on the board) | ~1m30s | every prose claim must be derived from the data |

**The irreducible core** — the catalyst research, the curation, the prose and the push — is about
**11 minutes**. Everything else was scheduling or a defect.

## 2026-11-13 — contract v2: Tier B is selected by MOVE, and the tier counts must match the CSV

**Why.** Tier B is the demotion bin — a name that moved 3% or more with **no same-session
catalyst** and **below-normal volume** — and it is the LARGEST tier on the board. Measured on the
2026-11-12 open board: **322 of the 527 published names (61%)** were Tier B. It was ranked by
turnover, so the table published the least informative names in the screen:

| The published Tier B table (2026-11-12, top 25 by turnover) | |
|---|---|
| biggest move in the table | **-7.20%** (TEM) |
| rows below 5% | **23 of 25** |
| what those rows were | mega-caps drifting 2-3% — INTC -2.94%, ORCL -2.64%, LRCX -1.81% |

and the names that had actually moved hard **without a volume behind them** — the only Tier B rows
with information in them — sat far below them in a turnover ranking:

| name | move | $ vol to 09:50 | pace |
|---|---|---|---|
| SMX | -44.59% | $2.3m | 0.66 |
| AGLT | -14.80% | $6.6m | n/a |
| STAK | -11.97% | $0.9m | 0.56 |
| FMC | -11.59% | $4.2m | 0.82 |
| ERAS | -9.29% | $7.8m | 0.77 |

**The rule (contract `in-play-artifact-v2`).** Tier B publishes the names with **|move| ≥ 5%**,
**biggest move first**, **max 10 rows**. If fewer than 10 clear 5%, publish them all; if none
clears it, publish no rows and one line saying so. The heading still states the FULL tier count,
and the CSV still carries every Tier B name, so nothing is hidden. The 5% floor is the routine's
own trigger line ("|chg%| ≥ 5% large/liquid"), and the selection is pace-independent, so it does
not move with the pace measure's known bias. **The same rule applies to the pre-close slot.**

**Two more rules came with v2:**

1. **The tier count in the heading must EQUAL the count in the candidates CSV.** The table and the
   dataset describe the same set; a heading that claims 610 while the CSV carries one row is a
   board lying about its own size.
2. **Grandfathering.** A board published under `in-play-artifact-v1` is checked against the rules
   in force when it was written. Failing a historical board for a rule that post-dates it is a
   FALSE ALARM, and the fleet's auditors treat false alarms as findings. The marker decides which
   rule set applies.

**The checker now asserts all of it** (`tools/check_in_play_artifact.py`, 40 open-slot checks /
29 pre-close): the Tier B cap of 10, the 5% floor on every published Tier B row, that the
published Tier B set is EXACTLY the rule's selection (not merely a valid-looking set), and the
count match on every tier heading. Each new rule is fault-injection tested, and the repo's
regression harness (`tools/test_in_play_contract.py`) carries the four new breach cases.

**A self-inflicted defect this work exposed.** The `in-play-artifact-v1` checker change landed on
2026-11-12 with two new assertions (the Python-repr checks) — and the repo's regression harness
was NOT re-run. It pins the exact number of checks each slot reports (31 / 20), so that commit
silently broke `tools/test_in_play_contract.py` for every session that ran it since. It is fixed
here (40 / 29), and the lesson is the fleet's own rule: **a checker change is not landed until the
repo's regression harness passes on it.**
>>>>>>> e47065f (cron 17: contract v2 - Tier B is selected by move (>=5%, max 10), tier counts must match the CSV, legacy boards grandfathered)

## 2026-11-13 (open slot) — the first `in-play-artifact-v2` board, and a ONE-SIDED correction to the daily-bar bound

**The v2 board passed.** The 2026-11-13 open fire (dispatched 09:50:10 ET, board pushed 10:02:09
ET — **12 minutes**, against 23 minutes on 2026-11-12) produced the first board under contract
`in-play-artifact-v2`: the marker says v2, the Tier B table published exactly the rule's
selection (10 names, every one of them ≥5%, biggest move first, out of a 190-name tier), every
tier heading's count equalled its CSV count, and the repo checker reported **40 checks,
CONTRACT OK**. The delta section named `2026-11-12-open.md` and the `open` fuel-log line landed.

**The Tier B rule did what it was built for.** The 190-name tier's biggest moves were published
(WYFI -8.27%, BTDR -8.22%, PEPG -8.13%, BW -7.53%, CIFR -7.48%, AEVA -7.46%, IAM -7.41%,
HUT -7.37%, RXT -7.31%, ASTS -7.10%) — every one of them a name that moved hard with no
catalyst of its own and no volume behind it, which is exactly the information a turnover-ranked
table had buried under mega-caps drifting 2%.

**The correction: the daily-bar bound is ONE-SIDED.** The 2026-11-12 fix added a physical-bound
cross-check — "the volume to 09:50 cannot exceed the session volume at pull time" — and
instructed the run to rescale the bars if the 5-minute sum exceeded the daily bar. On 2026-11-13
the run found the opposite: **Yahoo's in-progress daily bar for 2026-11-13 read BELOW the
5-minute series' own sum for the same session** (measured on MRVL at about 10:00 ET). The daily
bar lags; the intraday series does not.

So the bound is usable **only when the daily bar reads ≥ the 5-minute sum**. When it reads
lower, the bound is **not available** — and the run reported it as a **degraded source**, which
it is not: nothing in the board was degraded (the 8×-median cap in step 1 is what protects the
pace, and it needed **0 repairs** that morning), but `degraded_sources:` and `errors:` each
carried one entry for a check that was inapplicable. The fleet's own principle is that the audit
line carries no false alarms. The spec now says so explicitly.

**A second thing the 2026-11-13 board measured:** the official prior close re-based **324 of the
374 published names** (against 21 of 527 on 2026-11-12) — the 5-minute series' last bar close is
only an approximation of the session close, and on a day when the tape gapped hard the
approximation was poor enough to move more than four-fifths of the board's prior closes onto the
official daily close.

---

## 2026-11-14 — the published prior close was NOT the official close: two boards corrected

**The defect.** The open slot's reference price was the 5-minute series' **last bar close**. That
is an approximation of the session close — **the closing auction does not always land in the bar
series** — so for many names the published gap and move were measured against a pre-auction print
instead of the settled close. The engine's **G2** gate (the reconstructed prior close vs Yahoo's
OWN daily close for the prior session) found it on the first full-scale run.

**Measured against Yahoo's own daily bars (2026-11-14):**

| board | prior close off (>0.05%) | move >0.5pp | gap >0.5pp | gap verdicts flip | names wrongly on the board | Tier A affected |
|---|---|---|---|---|---|---|
| **2026-11-10 open** | 302/531 | 23 (max **1.77pp**) | 25 | **17** | **15 off, 0 missing** | 0 |
| **2026-11-11 open** | 287/516 | 40 | 39 | 7 | **6 off, 0 missing** | 2 (GEVO +42.76→+43.88%; **SATL's verdict `faded`→`held`**) |
| 2026-11-12 open | **0/527** | 0 | 0 | 0 | 0 | 0 |
| 2026-11-13 open | **0/374** | 0 | 0 | 0 | 0 | 0 |

The 2026-11-12 and 2026-11-13 boards were already clean — **the fix landed and works end-to-end in
production** (the 11-13 board ran on the new engine).

**What was corrected.** Both affected boards were re-published on 2026-11-14 with every name's move,
gap and 20-minute gap verdict recomputed on the official prior close, the tier tables and the
gap-annex buckets rebuilt, the tier counts and the audit lines updated, and the watch block's
invalidation levels corrected. **The correction is subtraction-only: no name joins either board**, so
no new tier, reason or catalyst was invented. **The published `pace` column is unaffected** — it
never used the prior close. Each corrected board carries a dated correction block at the top, and
the original bytes stay in the git history.

**The rule used for membership.** A name leaves the board when the corrected trigger fails AND the
published reference price was materially wrong (more than the gate's own 0.5% tolerance). Every
one of the 15 (11-10) and 6 (11-11) removals cleared the 3% trigger by 0.01–0.4pp on a price that
was wrong — MOD's published gap was -3.064% and its corrected gap is under 3%; SPAI's published move
was -4.46% and its corrected move is -3.00%.

**The chain was corrected too.** The 11-11 board's delta table read the (uncorrected) 11-10 board
and the 11-12 board's read the (uncorrected) 11-11 board, so both delta tables now read the
corrected base: the yesterday column, today's column and the Δ are recomputed, and the rows that
no longer move 3pp are dropped. **The corrected top-18 set is the SAME set as published** in both
boards (only the order moves), so no row was invented.

**A by-product finding, NOT corrected here.** On the 2026-11-12 board, **5 published names do not
meet the board's own published trigger** (MRVI's published gap is 2.987%, WIX's move -2.897%, and
three more) — that board's trigger was evaluated on the SCANNER's live quote while its published
numbers are the 09:50 reconstruction, i.e. **a mixed basis** ("one instant" per row). It is a
different defect from the prior close, it does not move a tradeable name, and it is left as-is
rather than rewritten on a late correction.

**The guard.** `tools/open_0950_pull.py` now re-bases every published name on the official daily
close, re-applies the trigger and the floors afterwards, and publishes both counts (measured on the
2026-11-12 session: **524 re-based, 11 dropped**). G2 fails the run if a published name's prior
close is more than 0.5% from Yahoo's own daily bar.
