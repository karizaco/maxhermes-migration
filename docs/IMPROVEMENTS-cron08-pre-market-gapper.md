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

---

# RETROSPECTIVE — 2026-11-04 evening: the seven names that gapped and never made the cut

Requested after the 2026-11-04 fire: *"DUOL, LMB, AZO, MELI, YOU, KD, HELE gapped and were not
in the list — why, and what rules would have caught them?"* This section is the retrospective, run
**after the 2026-11-04 close**, so it has the full-day outcome for every pre-market name — which
the 08:30 run could not have had. All numbers below are from the TradingView scanner (same source
as the routine), the prior sweep's own outputs, cron #92's pre-open catalyst tape, and shibui.

## 1. Why the seven did not make the cut

**The universe was the wrong universe.** The gapper only looks at the **prior sweep's Focus list**
(12 names, cron #09 at 2026-11-03 18:30 ET, screen data date 2026-11-02). All seven names were
absent from `focus.csv`, `stalk.csv`, `master.csv` **and** from the sweep's 868-name candidate
universe — they passed the pre-filter (close > 3, mcap > $300M, avg30 > 100k) and simply hit zero
of the ten screens. A momentum screen cannot rank a name whose move has not happened yet.

**Today the numbers were:** 379 US stocks gapped **≥4%** pre-market; 600 gapped ≥3%. The Focus
list's widest pre-market gap was **+3.8%** (WING). The Focus universe contained **0 of the 379**.

**They split into two populations, and only three of the seven were what people think they were:**

| Name | pm high | pm volume | day | what it actually was |
|---|---:|---:|---:|---|
| DUOL | +25.8% | 161,801 (15.5% of 30d) | +32.1% | **earnings** — Q4 beat + FY26 guidance raised, released 2026-11-03 **18:07 ET** |
| HELE | +18.1% | 41,252 (7.8% of 30d) | +24.9% | **acquisition proposal**, pre-market 11-04 |
| KD | +17.1% | 123,626 (2.9% of 30d) | +36.7% | **earnings** — Q2 FY27 at 07:00 ET (rev $3.65B beat, guidance reaffirmed) |
| LMB | +16.3% | 9,120 (4.3% of 30d) | +13.3% | **earnings** — Q3 beat, released 2026-11-03 **16:30 ET** |
| YOU | +7.6% | 68,370 (4.5% of 30d) | +33.4% | **earnings** — Q3 at 06:00 ET, rev +27.8%, EPS $0.53, FCF guidance raised |
| AZO | +2.5% | 694 (0.3% of 30d) | +3.8% | **not a gapper** — no pre-market gap; drifted intraday on 0.26 relative volume |
| MELI | +2.9% | 4,013 (0.7% of 30d) | +5.2% | **not a gapper** — same; no catalyst, 0.32 relative volume |

**Every one of the five real gappers had a catalyst that landed after the 18:30 sweep ran** (two at
16:30 and 18:07 on 11-03, two pre-market on 11-04) — or, for HELE, an M&A announcement that no
price-based screen can see. AZO and MELI were **not pre-market gappers at all**: their pre-market
ranges never cleared 4% and they rose during the regular session on light volume. No pre-market
gapper would have found them; they belong to cron #07 (09:45 RVOL re-rank) or #17 (15:50 in-play).

**Today's own rule would still have missed two of the five even with a market-wide universe.**
`gap > 4% AND pm_volume > 50,000` rejects **LMB** (9,120 shares = 4.3% of its normal volume) and
**HELE** (41,252 = 7.8%). The absolute 50,000-share floor is **scale-blind**: a $675M industrial
with 4.3% of its normal volume traded is a real market, while a $53B retailer with 694 shares is
not.

## 2. What actually separates the interesting gappers — measured, not guessed

Base rates from the full 2026-11-04 pre-market universe (459 names ≥4%). "med" = median day change,
"up" = % closing green, "c-o" = median (close − open), i.e. did the gap hold through the session.

| Rule (all knowable at 08:30) | n | med | up | c-o |
|---|---:|---:|---:|---:|
| all pre-market gainers ≥4% | 459 | +5.08% | 80.8% | +0.00% |
| + pre-market vol ≥1% of the name's 30-day average | 264 | +5.93% | 84.1% | +0.00% |
| + gap **sustained** (pre-market low above the prior close) | 191 | +6.14% | 90.1% | +0.25% |
| + market cap ≥ $1B | 80 | +6.74% | 95.0% | +0.80% |
| + prior **1-month** return >10% (continuation, measured to the 11-03 close) | 14 | **+22.02%** | 92.9% | **+6.99%** |
| earnings released between the prior close and today's open | 60 | **+10.91%** | 93.3% | +2.45% |
| earnings gap **and** pm volume >50k | 32 | +11.60% | 90.6% | +2.15% |
| catalyst captured (cron #92 tape, high/medium confidence) | 5 | **+32.06%** | 100% | +3.66% |
| …no catalyst captured | 454 | +4.92% | 80.6% | +0.00% |
| **fade side** — pm low ≤ −4% and pm vol ≥1% of 30d avg | 170 | **−8.80%** | 14.1% | −3.51% |

**The single most important line is the catalyst one**, and it needs the caveat that n = 5: when
cron #92's tape actually identified the catalyst, those names closed +32% on average; when it did
not, the universe still averaged +4.92%. And the tape's *coverage* is the real defect: only **5 of
459** qualifying names had a usable catalyst, **353 of 459** appeared in the tape at all, and the
106 names absent from the tape fell to a **+1.59%** median and 67% up.

**Two populations, and the filters are complementary, not substitutes.** Measured to the 11-03
close (no hindsight contamination):

| Name | prior 1-month | prior 1-week | caught by a momentum filter? | caught by an event filter? |
|---|---:|---:|---|---|
| DUOL | **−13.6%** | −5.3% | **no** | yes |
| LMB | −2.8% | −1.6% | **no** | yes |
| KD | +12.7% | −8.2% | yes | yes |
| YOU | +15.1% | +5.0% | yes | yes |
| HELE | +16.7% | +0.8% | yes | no (M&A) |

DUOL was a **3-week loser** into the print — the exact profile a momentum screen discards and the
exact profile an event screen catches. That is the argument for running **both** books.

## 3. Proposed rule set (replaces the current one)

**Universe:** the whole US pre-market (TradingView scanner), *not* the Focus list. The Focus list
stays what it is — a continuation watchlist — and today's outcome shows why it should not be mixed
in: its 12 names closed with a **~0% median** (6 up, 6 down) and all twelve traded **below** their
10-day average volume (0.19–0.71 relative volume).

**Long book**
1. `pm_high ≥ 4%` **and** `pm_volume ≥ 1% of the name's own 30-day average` **and** `pm_volume ≥ 20,000`
   — replace the absolute 50,000 floor with a ratio plus a small absolute floor.
2. **Overlay A (event):** a confirmed catalyst — earnings released between the prior close and
   today's open, an overnight EDGAR 8-K/425, FDA approval, M&A. → the five names of 11-04.
3. **Overlay B (continuation):** prior 1-month return >10% and prior 1-week return >3%
   (measured to the prior close) → n=9, median +17.78% on 2026-11-04.
4. **Quality overlay:** the pre-market **low** above the prior close (the gap never gave back) and
   market cap ≥ $1B → 95% green on 11-04.

**Fade book:** `pm_low ≤ −4%` and `pm_volume ≥ 1%` of 30-day average → median −8.80%, 85.9% red.

**One-session caveat:** this is a single day in a strong tape (SPY +1.42%, RSP +1.38%, DIA +2.47%),
so every base rate above is inflated. The rules are a hypothesis, not a verdict — which is why the
archive recommendation below matters more than any threshold here.

## 4. Sources worth adding

1. **The earnings calendar is already in the scanner** — `earnings_release_date` decodes to the exact
   release time (DUOL 11-03 18:07 ET, LMB 11-03 16:30 ET, KD 11-04 07:00 ET, YOU 11-04 06:00 ET).
   Zero new infrastructure, and it is the highest-value filter available (n=60, +10.91% median).
2. **cron #92's pre-open catalyst tape** — already built, already categorises (earnings /
   acquisition / trial). It caught DUOL, LMB and HELE but **missed KD and YOU**, both of them
   earnings, because Grok's 08:30 pass did not find a 07:00 ET press release. A deterministic
   earnings-calendar join fixes that class of miss. **Timing:** #92's first checkpoint actually ran
   at 08:35:10, so #08 at 08:30 cannot join it — move #92's first slot to ~08:10, or run #08 at 08:45.
3. **SEC EDGAR overnight filings** — verified working from this sandbox: `efts.sec.gov` full-text
   returns **430 8-K filings indexed for 2026-11-04** with issuer, CIK and accession. Deterministic
   for M&A (HELE) and material events, and free.
4. **Consensus and surprise magnitude** (MarketBeat / EarningsWhispers, per the earnings-calendar
   topic): the gap *size* relative to the surprise is what separates a gap that holds from one that
   fades — KD beat revenue but missed net income and still closed +36.7%.
5. **Options-implied move** (CBOE delayed option chain): gap vs expected move, plus IV crush — the
   classic edge and a natural severity gauge for position sizing.
6. **Short interest / borrow** (shibui `ownership_stats.short_percent_float`): squeeze gappers.
7. **FDA / clinical feeds** (openFDA): the CRIS-type names (+184% pre-market, trial catalyst).
8. **Your own archive — the highest-value addition.** Persist the *whole* pre-market universe plus
   the day's outcome every run (`premarket-archive/<date>.jsonl`). Today only one session could be
   measured; with 20–60 sessions stored, thresholds stop being opinions. This is what converts the
   rule set above from a hunch into a measured rule.

---

## RETROSPECTIVE — 2026-11-06: a REPLAYED 08:30 fire — the price path survives, the tape does not

The 2026-11-05 08:30:56 ET fire was resumed by the platform on 2026-11-06 at 05:26 ET, ~21 hours
later. `window_check.sh --scheduled-at-ms` judged the fire's **scheduled instant** and returned
`fire-date: 2026-11-05 · replay: yes`, so the artifact was rebuilt for 2026-11-05 and pushed with no
SKIPPED marker. This section records the recipe, because the next quota stall will produce the same
situation and the reconstruction is not obvious.

### What died

The routine's source of record is the Nasdaq `extended-trading` tape plus `/info`. **Both serve only
the LIVE session.** During the replay the live session was 2026-11-06, so the Nov 5 08:30 tape, its
volume counter and its per-print sizes are gone for good. The contract's gate has three legs
(`|gap| >= 4.0` AND `pm_volume >= 50,000` AND `exec_shares >= 25`); two of them are unrecoverable,
so **no name can be FLAGGED** — even though three names printed a gap at or beyond the bar
(AEHR -6.31%, FN -4.58%, CIFR -4.00%). "0 flagged" on a replay is a statement about missing evidence.

### The recipe (what survived, and where)

1. **The pre-market PRICE PATH survives in Yahoo's chart API.** `interval=1m&includePrePost=true`
   over the replayed session returns every pre-market print of that day, so the 08:30 snapshot print,
   the 04:00→08:30 range, the intraday crossings and the 09:30 opening print are all recoverable.
   **Extended-hours volume is reported as `0` — a non-report, not "no trading"** (the same for 5m).
   Sizes are therefore unrecoverable; prices are not.
2. **The denominator survives three ways.** The prior sweep's `focus.csv` `today_close` (the prior
   session close), Yahoo's `chartPreviousClose` on the replayed day's chart, and the bridge
   `market-recap` `previous_close` (`market_state: "pre"` serves the prior regular close) agreed to
   the cent on 12 of 12 names.
3. **Three IN-FLEET corroborations already exist for a replayed pre-market gap**, all published on
   the fire's own day — use them before declaring a price unverifiable:
   - cron #17's 09:50 board (`us-stocks-in-play/<date>-open-candidates.csv`) carries `gap_pct` and
     `open_gap_pct` per ticker; it matched this reconstruction to four decimals on 10 of 12 names.
   - cron #15's 08:22 artifact (`earnings/<date>-reactions.md`) carries a "Pre-mkt %" column; its
     AEHR -6.31% matched the 08:30 reading exactly.
   - `preopen-feed/<date>-0830.jsonl` carries TradingView's frozen FINAL pre-market print for the
     names in the scanner set (7 of 12 here) — but **no volume**.

### The traps

- **Leave `pm_volume` EMPTY on every row.** The checker tolerates it and an empty volume makes
  `row_flag` false, which is exactly what keeps the FLAGGED arithmetic honest. Do not write `0` —
  `0` reads as "traded, zero shares".
- **`exec_shares` must still be numeric and non-empty** (the checker rejects a non-numeric cell), so
  it is `0` with an explicit meaning: **unevidenced, not "no trade"**. Say that in `flag_reason` and
  in `## Flags`, or the next reader will read "0 shares" as "nothing traded".
- **Bar coverage is a first-class caveat.** Yahoo's pre-market series is sparse for illiquid names
  (here: AEIS 1 bar at or before 08:30, EVER 1, ECG 4, BETA 8). Publish `pm_bars_to_0830` and the
  last print's clock time: a name with one bar has no 08:30 reading at all, and its "no gap"
  verdict is materially weaker than a 146-bar name's.
- **Publish no quote leg.** The 08:30 bid/ask and the live quote are not archived anywhere; leave
  `quote_price` / `quote_gap_pct` empty rather than substituting a bar close.
- **Never publish a replayed gap from a live scanner.** TradingView's `premarket_*` had already
  rolled to the 2026-11-06 pre-market session (`premarket_time` = 2026-11-06 04:00 ET) at replay
  time — pulling it gives TODAY's pre-market, not the replayed session's.
- Nasdaq's `/info` `secondaryData` drifted again on the 11-05 close (48.91 for AEHR against 49.16
  from Yahoo, TradingView, the bridge, Nasdaq's own chart endpoint and Cboe). The documented defect,
  confirmed; the denominator was unaffected because three sources agreed on it.

### What was published

`daily-screens/2026-11-05/pre-market-gapper.md` + `.csv` + `_premarket-pull.json`, contract
`premarket-artifact-v4`, **29/29 checker checks passed**, flagged 0 / scanned 12,
`degraded_sources: 2` (Nasdaq's live tape + `/info`, and TradingView's pre-market fields).

### The recommendation that still stands

This run is a **fallback, not a substitute**: the size leg is unrecoverable by construction, so a
replayed gap can never be actionable. The durable fix is the one in item 8 of "Sources worth adding"
above — **persist the pre-market tape (volume + per-print sizes) on every run**
(`premarket-archive/<date>.jsonl`). With that archive the 2026-11-05 replay would have been a
one-line lookup with a real size behind every gap, instead of a price-only reconstruction with an
unevidenced size on every row.
