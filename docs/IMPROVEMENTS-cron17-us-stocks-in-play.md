# IMPROVEMENTS — cron #17 `us-stocks-in-play`

Findings from the 2026-11-04 pre-close fire (settled session, 15:50 ET).
Two are reusable by any routine that uses the TradingView scanner or the
`market-recap` bridge, and both cost a wrong board if missed.

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
