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
