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
