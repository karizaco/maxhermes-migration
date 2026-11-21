# The short-float source: a measured disagreement, and what to ask the vendor for

Date: 2026-11-21. Measured by cron #06 (`06-stock-screener-pattern-study-backlog`) against
an independent source, over the full published universe.

## The claim being checked

`shibui.ownership_stats.short_percent_float` is the field cron #06's "high short float"
screen ranks on. It is published as a **decimal fraction** (`0.20` = 20% of float) and
joined to `shares_float` from the same table.

## What was compared, and why a percentage cannot be compared directly

Two sources rarely count "the float" the same way, so the **percentage** is not
comparable across vendors. The **short interest in shares** is:

```
shibui's implied short-interest shares = short_percent_float × shares_float
```

and that number is comparable with any other vendor's short-interest share count.

**Sources used**
* *shibui* (the primary): `shibui.ownership_stats` over the MCP bridge.
* *independent*: `https://stockanalysis.com/stocks/<ticker>/statistics/` — publishes the
  exact short-interest share count (`shortInterest`), the short % of float (`shortFloat`),
  the prior month's figure and the short ratio, and it covers NYSE as well as Nasdaq.
  Nasdaq's own table (`api.nasdaq.com/api/quote/<SYM>/short-interest`) agrees with it
  where both exist, but returns `"data": null` for every NYSE name.

## The result (2026-11-14 screen, 134 names; repeated 2026-11-16, 138 names)

| | |
|---|---|
| short-interest share counts agree within 0.67–1.50× | **106 of 133** (median ratio 1.11) |
| disagree | **27** (25 read HIGH in shibui, 2 read LOW) |
| **published as >20% of float where the independent source says ≤20%** | **50 of 133** |

The worst cases:

| Name | shibui | independent | share ratio | reading |
|---|---|---|---|---|
| MMED | 72.6% (204,198,772 sh) | **3.49%** (9,813,734 sh) | 20.8× | position ~20× smaller than published |
| VG | 83.8% (437,137,985 sh) | **9.37%** (48,857,305 sh) | 8.95× | position ~9× smaller than published |
| NMAX | 63.5% | 16.15% | 3.93× | |
| CHTR | 43.9% | 16.16% | 2.72× | |
| WOLF | 51.7% (16,444,084 sh) | **90.42%** (28,999,815 sh) | 0.57× | position ~1.8× **larger** than published |

**The float is not the problem.** In every one of the divergent rows the two sources'
floats agree to 4–5 significant figures (VG 521,644,373 vs 521,645,366; MMED 281,265,526 vs
281,276,412). The disputed side is the **short-interest share count**.

## A second property: the table is LIVE and it moves intraday

`ownership_stats` has **no date column**. Measured on 2026-11-19, the same screen query
with the same data date, run 40 minutes apart, returned **132 names instead of 138** — 11
names fell below the 20% gate and 5 rose above it, with their volume and market cap
unchanged; only `short_percent_float` moved. The vendor refreshes the snapshot
underneath the screen.

## What to ask the vendor for

1. **The definition and the as-of date of `short_percent_float`** — which settlement date
   it reflects, and the float definition (free float vs shares outstanding) used for the
   denominator. Every divergence above is consistent with the denominator or the
   settlement being different from what the field name implies.
2. **The short-interest SHARE COUNT behind the ratio** — not the percentage. If shibui
   publishes the numerator, the cross-check above becomes a direct comparison instead of
   an inference, and the 27 divergences would be explainable.
3. **The refresh cadence of the table**, and whether a historical series can be queried.
   A screen that can only see "now" cannot be replayed, and every weekly run's numbers
   are a fact about the pull instant rather than about the week.
4. **Which names carry a stale or re-stamped short position.** Between the 2026-11-14 and
   2026-11-16 pulls, 20 of 134 published names moved — MMED from 72.6% to 34.4% with an
   **unchanged** share count (281,265,526), which is a vendor correction, not a market
   event.

## What cron #06 does about it meanwhile

The routine publishes the independent figure beside shibui's on every row, ranks the table
by the figure that survives the cross-check, marks a disputed squeeze candidate as
`CONTESTED`, and publishes the cross-check's coverage (with an 80% floor) so a partial
verification cannot read as a complete one. The numbers it publishes are now checkable
against a second source — which is the point.
