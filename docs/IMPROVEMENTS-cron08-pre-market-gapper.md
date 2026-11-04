# Improvements — cron #08 `stock-screener-pre-market-gapper`

- **Audited:** 2026-11-04 (the 08:30 ET fire, `2026-11-04`)
- **Scope:** the pre-market gapper's price selection, its volume source and its cross-checks.
- **Artifact under review:** `daily-screens/2026-11-04/pre-market-gapper.md` (outputs repo, cron #08)

## Summary

The routine ran clean (12/12 Focus names priced, zero flags, correct gap denominator) but exposed
**two defects in the skill spec's §6 data path** and **one overstated source claim**. None of them
changed today's published numbers — the widest gap on any source was 3.82pp against a 4.00pp
trigger, so the "no flags" verdict is robust to all three — but each one would silently corrupt a
name on a day when the gap does cross the trigger.

---

## 1. `Nasdaq /info` `primaryData` can carry the PRIOR CLOSE instead of a pre-market print

**The spec says** (`SKILL.md` §6, rule 2):

> Take the **price** from `/info` `primaryData` (live); use the tape for *which prints actually
> traded*, the pre-market high/low, and the cumulative volume.

**What the data shows.** On the 08:35 ET snapshot, `KOD` and `HTFL` came back as:

```json
"primaryData": {"lastSalePrice": "$98.89", "netChange": "", "percentageChange": "",
                "deltaIndicator": "unch", "lastTradeTimestamp": "Nov 4, 2026 8:32 AM ET"}
```

`$98.89` is KOD's **2026-11-03 close**, not a pre-market print — `netChange` is empty,
`percentageChange` is empty, and `deltaIndicator` is `unch`. The same pull's `secondaryData` confirms
it: `"Closed at Nov 3, 2026 4:00 PM ET"`. Meanwhile the extended-trading tape for the same symbol in
the same run held executed pre-market prints at **$100.75** and the venue's own consolidated line
read `"$100.75 +1.86 (+1.88%)"`.

**Why it matters.** `/info` only registers a pre-market print once Nasdaq decides it qualifies.
Until then `primaryData.lastSalePrice` is the previous close carried forward with a **live-looking
timestamp** (8:32 AM ET) — so a naive read produces a gap of **0.00%** on a name that is actually
trading **+1.9%**. HTFL showed the same shape (close 54.40, tape 54.65). Two of twelve names, on the
same run — this is not a rare edge.

**The fix (the spec's rule 2 needs a precondition).** Use `/info` `primaryData` **only when it
carries a pre-market change** — i.e. `netChange` is non-empty **and** `deltaIndicator != "unch"`.
Otherwise fall back to the **tape's `infoTable.consolidated` price** (the venue's pre-market
consolidated print, which carries its own `+x.xx (+y.yy%)` change), and label the source.

Do **not** use `lastTradeTimestamp` as the liveness test for *price*: it advances on every pull even
when the price is still yesterday's close. It is a liveness test for the **field**, not for a print.

## 2. TradingView's `premarket_change` is NOT a last print — it is often a pre-market EXTREME

**What the data shows.** For the same 12 names, TV's `premarket_change` equals the change of the
pre-market **high** or **low** on some names and a last print on others:

| Name | TV `premarket_change` | implied price | TV `premarket_high` / `low` | what it equals |
|---|---:|---:|---|---|
| KOD | +2.6595% | 101.52 | 101.52 / 98.30 | **exactly `premarket_high`** |
| WING | +2.1229% | 165.00 | 165.00 / 164.40 | **exactly `premarket_high`** |
| MRNA | +3.5151% | 236.47 | 236.47 / 229.26 | **exactly `premarket_high`** |
| FIGS | −0.3360% | 20.75 | 21.30 / 20.75 | **exactly `premarket_low`** |
| KVYO | +0.7969% | 21.50 | 21.7418 / 21.50 | **exactly `premarket_low`** |
| CLF | +1.9801% | 14.42 | 14.68 / 14.20 | neither extreme — a last print |

`premarket_last` was **null for all 12 names**, so the field that sounds like the last print is
empty, and the field that is populated is not one.

**Why it matters.** Publishing TV's `premarket_change` as "the gap" would publish the pre-market
**high** for any name that gapped up — overstating the gap by up to 1.7pp on this run (KOD: TV
+2.66% vs the live Nasdaq print +1.12%; CAI: TV +2.74% vs live +2.10%).

**The fix.** TV's pre-market fields are a **range cross-check only**: report `premarket_volume`,
`premarket_high` and `premarket_low` in the CSV, never `premarket_change` as the gap. The published
gap must come from a last-print source.

## 3. The Cboe delayed-quote CDN is NOT a pre-market source — the spec overstates it

**The spec says** (§6, rule 3):

> Prefer the Cboe delayed-quote CDN as the independent price cross-check … it returns an explicit
> `last_trade_time` and `timestamp`, so its freshness is verifiable from the payload.

**What the data shows.** On all 12 names, `last_trade_time` was `2026-11-03T15:59:59` — the prior
session's closing print — and the payload `timestamp` ranged from `2026-11-04 01:04:10` (MRNA) to
`08:18:05` (KOD). Cboe served **no pre-market print at all**; `current_price` was an 11-03 print
(KOD `98.7334` against an 11-03 close of `98.89`, MRNA `227.00` against a close of `228.44`).

The freshness field is therefore real but **it proves the quote is stale** — which is the useful
part. Cboe's `close` field (`161.57` for WING, `98.89` for KOD, `228.44` for MRNA) matched the prior
sweep's `focus.csv` closes on all 12 names, which makes Cboe a **reliable prior-close confirmation**
and nothing more.

**The fix.** Use Cboe to confirm the **denominator**, not to price the pre-market. State the
`last_trade_time` in the artifact so a reader can see it is the prior session.

---

## Also observed (no spec change needed, recorded for the next run)

- **The stale-cache defence works and is not optional.** Every tape pull carried a `cache-hit` header
  (`3001` / `3002`), and TEM returned **two different internal vintages in the same run**
  (`08:17:08` and `08:18:04`). Pulling 4× and keeping the max-newest-timestamp payload is what
  makes the tape usable at all.
- **The Nasdaq tape lags `/info` by minutes and moves fast.** Across three snapshots MRNA went
  $234.33 → $235.63 → $235.97 and KOD went $100.00 → $96.11. The tape's newest print trailed
  `/info` by 4–15 minutes on most names — consistent with a periodically-refreshed cache, and the
  reason the price must come from `/info` and the **volume** from the tape.
- **Pre-market volume is negligible across the board.** As a share of each name's 30-day average
  volume the twelve names ran 0.01% – 1.84% (TEM 1.84%, MRNA 1.38%, CVNA 0.54%, nine names under
  0.6%). Spreads ran to ±2.3% (KOD bid $98.30 / ask $103.00). A gap on that volume is a quote, not
  a market — the artifact now says so and reports each name's volume as a % of its 30-day average.
- **The counter-vs-tape arbitration rule was not exercised.** No name needed the complete-tape
  override in the final snapshot; VSEC published no cumulative counter at all, so its 4-print tape
  sum (32 shares) was used as a lower bound and labelled as such.

## Recommended spec edits (NOT applied by this run — the skill spec is shared by cron #04, #07,
## #08, #09 and #10, so the change needs a deliberate decision, not a cron firing)

1. §6 rule 2 — add the `/info` precondition (`netChange` non-empty **and**
   `deltaIndicator != "unch"`) and the tape-consolidated fallback.
2. §6 rule 3 — re-label the Cboe CDN as a **prior-close** confirmation, not a pre-market
   price cross-check.
3. §6 — add "TV `premarket_change` is a range/extreme measure, not a last print; publish
   `premarket_volume`/`_high`/`_low` only".
4. §6 — require a `% of 30-day average volume` column so a thin gap cannot be read as a real move.
