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

---

## RETROSPECTIVE — 2026-11-06: the 08:30 ET fire — the tape ran 15 minutes behind, and a 1-share print decided a flag

**Date:** 2026-11-06 · **Scope:** cron #08 `stock-screener-pre-market-gapper`, the 08:30 ET fire
(`window_check.sh` → `fire-date: 2026-11-06 · replay: no`, a fresh fire, not a reconstruction).
**Artifact:** `daily-screens/2026-11-06/pre-market-gapper.md` + `.csv` + `_premarket-pull.json`,
contract `premarket-artifact-v4`, **25/25 checker checks passed**, flagged 1 / scanned 12,
`degraded_sources: 2`.

This is a **live** run — the opposite of the 2026-11-05 retrospective above, where the tape was
gone. That makes it the cleanest measurement yet of what the tape does to a live pre-market, and it
surfaced four defects. **None of them is a gate change, and none of them is applied here** — per the
convention already set in this file, the skill spec is shared by cron #04, #07, #08, #09 and #10, so
the procedure changes need a deliberate decision, not a cron firing.

### Finding 1 — the tape's cache lag was ~15 MINUTES, and the max-newest-timestamp defence cannot close it

The Nasdaq `extended-trading` tape is served from a shared HTTP cache. The defence in §6.5 (pull N
times, keep the payload with the newest internal clock time) works — it advances the vintage — but
it can only advance as fast as the cache does. Measured today, across three pull rounds:

| Round | Wall clock | Freshest tape vintage (newest print) | Lag |
|---|---|---|---|
| A (4 pulls) | 08:34–08:36 ET | 08:19:17 | ~15 min |
| B (6 pulls) | 08:38–08:41 ET | 08:22:06 | ~16 min |
| C (8 pulls) | 08:41–08:42 ET | 08:26:43 | ~15 min |
| Independent (5 cache-busted pulls) | 08:43–08:46 ET | 08:28:32 | ~15 min |
| Final (6 cache-busted pulls, second resolution) | 08:47 ET | **08:32:12** | ~15 min |

`cache-hit: 3001/3002` headers came back on most pulls, and a cache-buster (`&u=<ns>`) did **not**
reliably bypass the stale vintage — but the best-of-N rule still gained ~4 minutes of freshness per
round. Nasdaq `/info` was live throughout (`lastTradeTimestamp` tracked wall clock to the minute;
at 08:47 ET it read 08:47).

**What this costs:** the published gap for a name can be 15 minutes stale, and for a fast mover that
is the difference between the bar and no bar. The artifact now publishes the tape vintage per name
and the lag in its Method section; the reader can see it. **Recommendation:** have the helper
publish a `tape_lag_seconds` column (wall clock − newest tape print) for every name, so the
staleness of each row is a published number rather than prose. Also worth considering: the routine
could take a *final* pull immediately before it writes, rather than at the start of the pull round —
today's final round at 08:47 was the most valuable measurement of the run.

### Finding 2 — `premarket_pull.py` cannot order two prints inside the same second, and it picks the OLDEST of the final minute

`_pull_tape` builds `_clock_to_min(t) = HH*60 + MM` — **the seconds are dropped** — and then sorts
`prints` by that key. Two consequences, both live today:

1. Prints inside the same second cannot be ordered. OUST printed several times per second for most
   of the pre-market, so its final second (08:32:12) carried two prints: **$31.75 on 512 shares**
   and **$31.78 on 1 share**.
2. The Nasdaq table is served **newest-first** (rows[0] = newest). A *stable* sort by a key that
   collapses seconds leaves each same-minute group in newest-first order, so `prints[-1]` — the
   "last print" the whole gate depends on — is actually the **OLDEST print of the final minute**,
   not the newest.

**Measured consequence — the verdict of the run's only flag flipped on the order of two prints in
one second, across pull rounds of the same session:**

| Round | OUST published gap | exec_shares | helper verdict |
|---|---|---|---|
| A (08:34 ET) | +3.211% | 25 | BORDERLINE_TAPE_ONLY |
| B (08:38 ET) | +4.456% | 162 | **FLAGGED** |
| C (08:41 ET) | +4.243% | 3 | **BORDERLINE_THIN** |
| Final (08:47 ET, second resolution) | +4.030% | 512 | **FLAGGED** (published) |

**Fix (pure defect, no policy content):** order at second resolution AND reverse the API's
newest-first order inside a second. The sort key must be `(seconds, -api_index)`: ascending in
time, and within one second the *later* API row (smaller index) must come **last** in the list,
because it is the newer print. With the current key, the helper publishes the wrong print as "the
last print" for every name that prints more than once a second.

**Note for whoever applies it:** with the ordering fixed, the helper picks the 1-share $31.78
(+4.128%) as the last print and publishes `BORDERLINE_THIN` — which is the contract's *literal*
reading and contradicts what today's artifact published. Finding 3 is why.

### Finding 3 — "the print that carries the gap" is undefined when the final print is a rounding artifact — and the two readings disagree on a 122k-share name

This is the substantive one, and it is a **procedure decision for the routine's owner**, not a
defect.

OUST at the 08:47 ET snapshot:

- last executed print: **$31.78 on 1 share** → +4.128% (above the bar, no size behind it)
- the print one second earlier: **$31.75 on 512 shares** → +4.030% (above the bar, with size)
- the live quote at 08:47 ET: **$31.98 (+4.78%)**, **bid $31.76 (+4.06%)** — the *bid* is above the bar
- pre-market volume: **122,288** (tape counter) / **122,594** (`/info`)
- and OUST traded above the bar with size all morning: +4.85% on 100 shares (07:51:11), +4.19% on
  272 shares (07:54:13), +4.46% on 162 shares (08:22:06), +4.03% on 512 shares (08:32:12)

**Reading A (literal, what the helper implements):** the published gap comes from the last executed
print; that print carried 1 share; the size leg fails; the verdict is `BORDERLINE_THIN` — whose
definition is "the bar was printed, but **the market behind it is too thin to act on**". For a name
whose pre-market volume is 122,288 shares and whose bid sits 4.06% above the reference close, that
definition is **false**. This is the pattern the 25-share bar was built for on 2026-11-03 (CAI
+5.53% on 10 shares, CVI −6.99% on 1 share, MTZ +3.93% on 1-share prints) — but in those cases the
*real tape* was below the bar and only the trivial print claimed the gap. OUST is the mirror image:
the real tape supports the gap, and the trivial print is merely last.

**Reading B (purpose):** the gap is carried by the 512-share print; `exec_shares` = 512; the gate
passes; the verdict is `FLAGGED`. The rule's own words — "**a gap is only real if a print with size
behind it crossed it**" — are satisfied many times over.

**What was published:** Reading B, with the entire evidence disclosed — the 1-share final print, the
512-share print one second earlier, the 0.03pp margin on the published print, the 0.78pp margin on
the quote, the 15-minute tape lag, and the fact that the freshest vintage came from an
independent hand-ordered pull rather than from the helper. The artifact says plainly that the
helper's own output for the same state was `BORDERLINE_THIN`.

**Recommendation (a procedure change, for the owner):** make the gate evaluate the last
**substantive** print — the last print whose size is ≥ `MIN_EXECUTED_SHARES` — and publish the
*final* print's size and gap as their own columns, so a 1-share rounding print can neither create
nor destroy a flag. Under that rule:

- OUST → gap +4.03% (512 shares) → `FLAGGED`, with the final 1-share print published beside it;
- LIVN (every print above the bar was 1 share) → no substantive print exists → the last print is
  published with its thin size → `BORDERLINE_INTRADAY`, unchanged;
- HELE (−4.66% on 1 share) and VRDN (−5.43% on 1 share) → unchanged, thin;
- CRCT (+5.30% on 104 shares, +5.84% on 28 shares, then faded to −0.54%) → the substantive print
  crossed the bar and the name is not there at the snapshot → `BORDERLINE_INTRADAY`, unchanged;
- KD (+4.94% on a 5-share print inside a $14.50/$18.43 band, volume 15,266 under the floor) →
  `BORDERLINE_TAPE_ONLY`, unchanged.

So the proposed rule changes **one** verdict (OUST) and leaves every other name exactly as it is.
The gate's numbers are untouched — 4.0% / 50,000 / 25 — which is the one thing §6.12 forbids
changing.

### Finding 4 — `push_artifact.sh --nn` WITHOUT `--msg` silently drops the routine name from the commit subject

Today I called the shared script with `--nn 08` and no `--msg`. The subject came out
`cron 08 daily-screens 2026-11-06` instead of `cron 08 stock-screener-pre-market-gapper
2026-11-06`. The cause is in the script: the name table (`NN=08; NM=stock-screener-pre-market-gapper`
for `daily-screens/*/pre-market-gapper.md`) is consulted **only when `NN` is empty**, and the
subject is then built as `cron $NN ${NM:-$OUT} $ART_DATE` — so passing `--nn` alone leaves `NM`
empty and the output directory name becomes the "routine name".

The script's own comment says "a caller should still pass `--nn` explicitly", which contradicts
its own subject derivation: **the flag that is supposed to make attribution more reliable is the
one that makes it less.** The deployed cron #08 prompt does not pass `--nn` (it lets the table
derive both), so this is a trap for whoever adds the flag by hand — as I did.

**Fix (shared script, `_shared/push_artifact.sh`):** look up `NM` by `NN` in the same table when
`--nn` is given without `--msg`, and fail loudly if `NN` is not in the table. **Until then: pass
`--msg` explicitly.** The artifact itself was unaffected — only the commit subject — and it was
corrected with an empty attribution commit (`cron commit --allow-empty`), which is safe: it moves no
file and stages no deletion. All three delivered files were byte-verified against the remote after
it.

### Also observed (recorded, no spec change)

- **The denominator held.** `focus.csv` (`today_close`) + TradingView `close` + the Cboe CDN `close`
  agree to the cent on **12/12**, and the MCP bridge `market-recap` `get_quotes` confirmed **12/12**
  (`price` = the 2026-11-05 close, `as_of` 2026-11-05T21:00Z). Nasdaq `/info` `secondaryData`
  **disagreed on 10 of 12** (OUST 30.5850 vs 30.52; KD 16.2750 vs 16.18; ARRY 5.2450 vs 5.30;
  DUOL 157.3400 vs 157.02; CRCT 9.2550 vs 9.25; ENOV 28.4400 vs 28.62; HELE 37.6700 vs 37.77;
  LIVN 91.3000 vs 91.14; XNCR 34.0961 vs 34.05; YOU 56.3700 vs 56.50) and was used for nothing.
- **TradingView was degraded on this run** and it is a NEW degradation, not the known volume
  undercount: it returned **no pre-market row at all** for 2 of the 12 names (YOU, XNCR), and its
  OUST `premarket_change` read **+3.87%** against the tape's +4.03% and the live quote's +4.78%.
  It is still a valid denominator cross-check (12/12) and a valid `premarket_high`/`low` source.
- **The fleet's 08:30 pre-open feed existed today** (`preopen-feed/2026-11-06-0830.jsonl`, captured
  08:32:58 ET) — no substitution was needed — but it carried only **2 of these 12 names** (OUST
  +3.571% at $31.61, CRCT −2.703% at $9.00) and **no catalyst** for either. Cron #15's 08:22 ET
  artifact independently published CRCT's pre-open gap as −2.70%. **No catalyst was sourced for any
  of the twelve**, so none is asserted in the artifact.
- **The pre-open feed's OUST number (+3.571%) is the same TradingView-derived figure the scanner
  serves** — it is not an independent confirmation of the tape, and a reader should not count it as
  one.

### The recommendation that still stands, plus the one that is new

The 2026-11-05 retrospective's recommendation stands unchanged: **persist the pre-market tape
(volume + per-print sizes) on every run** (`premarket-archive/<date>.jsonl`). Today's run is the
second argument for it — the tape's 15-minute lag (Finding 1) and the same-second ordering defect
(Finding 2) both stem from re-reading a live, cached endpoint instead of recording it once.

The **new** recommendation is Finding 3's rule change, and it needs a decision from the routine's
owner before any helper change lands, because the helper's current output contradicts the
published artifact. Finding 2's ordering fix can be applied independently of it; Finding 3's rule
cannot.

---

# v5 — 2026-11-07: the universe-date assertion, and a correction about AZO and MELI

Reviewed after the 2026-11-06 fire. Two things: a defect in how the routine resolves its
**universe**, and a **correction** to the 2026-11-04 retrospective in this document.

## 1. THE CORRECTION — AZO and MELI DID gap pre-market on 2026-11-04

The retrospective above said AZO and MELI were "**not a gapper** — no pre-market gap". **That was
wrong.** Both gapped:

| name | 11-03 close | pre-market range | gap | what the retrospective said |
|---|---:|---|---:|---|
| AZO | 3200.90 | 3219.74 – 3283.00 (a broker feed shows 3200 → 3297) | **+0.6% … +2.6%** (≈ +3.0% on the wider range) | "not a gapper" |
| MELI | 1662.06 | 1655.00 – 1710.00 (the user's feed: 1662 → 1713) | **−0.4% … +2.9%** (≈ +3.1% on the wider range) | "not a gapper" |

What was actually true is narrower: their gaps were **below the 4% flag bar** and their
pre-market **volume** was negligible (694 and 4,013 shares — 0.3% and 0.7% of their own 30-day
average). The gap was real; the market behind it was not. **A flag-only artifact had no way to say
that**, which is a presentation defect, not a data defect. It is now a published rung: §6.13's
ladder publishes the 2–4% near-miss band with its volume ratio and range, instead of silence.

**MELI also carried a forward catalyst that no routine was looking for.** MercadoLibre's IR
calendar carried *"Q3'27 Results — provisional date November 4th"*; the print actually landed
**Thursday 2026-11-05 pre-market** — EPS **$8.83 vs $9.41 consensus (a miss)** — and the stock
fell **−13.9% pre-bell**. At 08:30 on Wednesday 11-04, a gapper that publishes **"reports tonight
/ before tomorrow's open"** would have flagged a +3.1% pre-market gain INTO a print. That is the
single most valuable addition in §6.13, and it is now specified (the scanner's
`earnings_release_date` decodes to the exact release time: DUOL 2026-11-03 18:07 ET, LMB 2026-11-03
16:30 ET, KD 2026-11-04 07:00 ET, YOU 2026-11-04 06:03 ET).

AZO's gap had news flow the artifact never captured (a CFO resignation effective 25 Nov; BofA
dropping the name from its "Value 10" list at 14:01 ET). No cause is asserted here — the point is
that a 3% gap is invisible to a 4%-only artifact whether or not a cause exists.

## 2. THE DEFECT — the universe was never asserted to be for the RIGHT session

The universe is "the Focus list of the most recent completed 18:30 ET sweep". Nothing asserted
**which session** that Focus list belongs to, and three defects sat behind it:

1. **TWO close columns.** Since 2026-11-04 the sweep's CSV carries `screen_close_resolved` (the
   screen's **T+1 data date** — the PREVIOUS session, because shibui is a day behind) and
   `today_close` (the sweep's **own** session). Choosing by name instead of by date is a gap error
   of up to 10%: the 2026-11-06 sweep carries APP at `screen_close_resolved` 356.10 and
   `today_close` 391.22 — **9.9pp** apart.
2. **The shipped helper could not read the current schema at all.** `premarket_pull.py` looked for
   `close_<YYYY-MM-DD>` columns and for `prior_close` / `close` / `last_close` — **none of which
   exist** in the current CSV — so it resolved **no reference close** for any name and fell
   through to a drifting source, while the artifact still claimed a `focus.csv` denominator.
3. **A stale sweep is silent.** If the prior session's sweep never published, "the latest
   focus.csv" is an OLDER session's names, and the gaps are measured against the wrong close.
   Nothing failed.

The 2026-11-05 fire shows how real the consequence is: that run was a **late reconstruction** whose
tape was unrecoverable, and its `exec_shares` had to be published as `0 = unevidenced` for every
name — a whole artifact of gaps whose evidence did not exist.

## 3. WHAT WAS IMPLEMENTED (contract v5)

| file | what it does |
|---|---|
| `cloud-prompts/skills/stock-screener-suite/scripts/premarket_universe.py` (new, marker `premarket-universe-v1`) | resolves the expected prior session **from data**, fetches the Focus list for it, picks the close column **by date**, rejects `screen_close_resolved`, cross-checks every reference close (session-exact Nasdaq history when the live sources have rolled forward), and writes `_universe.json`. **Exit 3 on a hard failure.** |
| `cloud-prompts/skills/stock-screener-suite/scripts/premarket_pull.py` (v4 → v5) | `--universe-manifest` is authoritative and **a FAIL manifest aborts the run**; the close column is chosen by date; the CSV carries `universe_date`, `ref_close_date`, `universe_source` on every row |
| `cloud-prompts/skills/stock-screener-suite/SKILL.md` §6.3a / §6.7 / §6.13 | the universe-date assertion, contract v5, and the five presentation additions |
| `tools/check_premarket_artifact.py` (v5) | asserts the artifact names ONE universe session and ONE denominator session and that they agree — and is **version-aware**, so a v4 artifact is not failed by a v5 checker |
| `tools/test_premarket_universe.py` (new) | the regression test: **20 pinned checks**, including that a WRONG-session universe and a MISSING sweep both **exit 3**. The guard is observed failing, which is the only way a gate is a gate |

Hard assertions: **H1** the prior session is resolved from data · **H2** a published sweep exists ·
**H3** the universe's session == the expected prior session · **H4** every name has a reference
close for that session · **H5** every reference close is confirmed by an independent source.

Measured on the real repo: for the **2026-11-06** fire the resolver picks the **2026-11-05**
sweep (not the 11-06 one, which did not exist yet at 08:30), resolves the denominator from
`today_close` = 2026-11-05, records `screen_close_resolved` (data_date 2026-11-04) as **rejected**,
and confirms all 12 reference closes against the session-exact Nasdaq history.

## 4. A NOTE ON THE FIRE LOG

There was **no missing fire** on 2026-11-07: that was a **Saturday**, and the routine is
`30 8 * * 1-5`. The last fire was Friday 2026-11-06. (The Nasdaq `market-info` endpoint settles
this question in one call — it returns `preMarketOpeningTime` for the NEXT session.)

---

## 5. 2026-11-10 — A SWEEP THAT PUBLISHED `focus.md` AND NO `focus.csv`

**Evidence (the 2026-11-10 fire, 08:34 ET).** The 18:30 ET sweep of **2026-11-09** published
`daily-screens/2026-11-09/focus.md` — 12 Focus names with their provenance — and **no
`focus.csv`**. Its own `_manifest.json` records the `focus` screen as *"no .csv for this screen"*
(alongside `master`, `peoplewish`, `qullamaggie`, `ariel-hernandez`, `jeff-sun`, `breadth`).

Two defects met in one fire:

1. **The resolver aborted the run on the 404.** `_github_raw()` let `HTTPError` escape, so the
   session walk died instead of reading the missing file as "not published". The fire died before
   a universe was proved — no artifact at all.
2. **Had it survived, it would have scanned the WRONG session's names.** The walk looks for
   `focus.csv`; with the 2026-11-09 CSV absent it would have walked back to the **2026-11-06**
   sweep and measured today's gaps against the 2026-11-06 universe — the exact failure H3 exists
   to catch, arriving through a door H3 does not guard.

A third, quieter defect: `premarket_pull.py` labelled the reference close **`focus.csv`** in
`ref_close_source` no matter where it came from. With no CSV close available, the published
source string named a file that does not exist.

**What changed**

| file | change |
|---|---|
| `scripts/premarket_universe.py` (marker `premarket-universe-v1` → **v2**) | a missing path is **"not published"**, not an exception; the Focus list is read from `focus.md` when the CSV is absent; the stylist **names** are recovered from the sweep's canonical `_results.json`; a universe with no close column takes the denominator from the **independent sources only** and is flagged; `universe_kind` is published in the manifest. `--offline` now never touches the network. |
| `scripts/premarket_pull.py` | the published `ref_close_source` names the source the close ACTUALLY came from (the manifest's `ref_close_source`), and the manifest's independent confirmations are carried into it — no more `focus.csv` for a close that no focus.csv provided. |
| `tools/test_premarket_universe.py` | the test could not run at all: it looked for the resolver in `tools/`, but the resolver lives in the skill's `scripts/`. Now it resolves the real path (**20/20 → 31/31 pinned checks**), including **T6** (a markdown-only universe resolves the right session, takes the close from the independent source and does NOT attribute it to a `focus.csv`) and **T7** (a markdown universe for the wrong session still **exits 3**). |
| `SKILL.md` §6.3a | the fetch ladder now demands `premarket-universe-v2`, so a cached OLD copy cannot win; the markdown-universe path is documented. |

**Measured on the live repo.** The resolver now resolves the expected prior session **2026-11-09**
from Nasdaq's own session history, finds the 2026-11-09 sweep's **markdown** Focus list (12 names:
CYRX, ETON, FLY, FROG, IONQ, KRMN, LASR, OKLO, QNT, RGTI, RHLD, TMDX), and confirms **12/12**
reference closes on TradingView + Cboe + Nasdaq's session-exact per-symbol history — the settled
2026-11-09 close, which is what the gap must be measured against.

**The upstream half of the defect is cron #09's — and it has ALREADY hit another routine.** The
sweep should publish `focus.csv` again; a markdown-only Focus list is a degraded publish.
Measured: `daily-screens/2026-11-09/focus-rvol-snapshot.csv` (cron #07, 09:45 ET on 9 Nov) opens
with **WRBY and XERS** — the **2026-11-06** Focus names — because the 2026-11-09 sweep published no
`focus.csv` for it to read. So the missing companion file has already silently degraded a second
routine's universe for that session: it re-ranked the 6 Nov book instead of the 9 Nov one.

---

## 2026-11-12 (08:34 ET fire) — the contract CSV's price fields are STRINGS, and the event book is 95% penny stocks

**The fire.** 1 of 12 Focus names flagged (MARA −5.74%, bitcoin beta), universe **2026-11-11**,
6/6 hard assertions passed, `check_premarket_artifact.py` **27/27**. Two things about the data
model cost real time and would have cost the next consumer a wrong number.

### 1. `pm_high` / `pm_low` carry a PRICE **PLUS A CLOCK TIME**, and `exec_notional` carries a `$` and thousands separators

The contract CSV (SKILL.md §6.7) names `pm_high`, `pm_low`, `exec_notional` as columns but never
says they are **strings**:

```
AAON, ...,exec_notional = "1,380.00"   pm_high = "$75.51 (04:00:05 AM)"   pm_low = "$73.6658 (08:30:29 AM)"
```

`float()` raises on every one of them, and `pm_high`/`pm_low` cannot even be compared numerically.
The checker's `num()` tolerates `$`, `,` and `%`, so the contract check passes — **the artifact
looks healthy while a downstream parser breaks on it.** A consumer that wants "the pre-market
high" gets a timestamp for free, which is genuinely useful — but only if the contract says so.

**Recommended fix (not applied from a cron fire — it touches a script other routines read).**
Either (a) publish `pm_high` / `pm_low` as bare numbers and move the clock into new columns
`pm_high_time` / `pm_low_time`, keeping the column set additive; or (b) state in SKILL.md §6.7
that these three fields are **formatted strings** (`$` + thousands separators, and a trailing
` HH:MM:SS AM/PM` on `pm_high`/`pm_low`) and that a consumer must strip them. (a) is cleaner for
the next consumer; (b) is a one-line change to the spec. Whichever lands, the spec and the
checker must agree — the checker must not be the only place that knows the format.

### 2. The raw pre-market gap-leader list is almost entirely penny stocks and LEVERAGED ETFs

SKILL.md §6.13 §4 asks for "the market's pre-market gap leaders with their catalysts". Pulled
literally (TV scanner, `premarket_change >= 4`), the list is **79 up / 313 down** — and the top of
it is **PLCE +489%** ($0.1985), PARA +62.8%, plus a wall of single-stock ETFs (`Tradr 2X Short
NBIS Daily ETF`, `Defiance Daily Target 2X Long LUNR ETF`, `Leverage Shares 2X Long CRWV…`) whose
move is a DERIVATIVE of the underlying, not a gap anyone can trade.

Adding `type = stock` and `market_cap_basic > 200000000` cuts it to **9 up / 81 down** of real
companies, and the leaders become readable: LUNR +11.5% (pre-open Q3 beat), TTEK +11.1% (post-close
Q4 beat), NBIS −13.5% and CRWV −10.0% (Nvidia's CEO news dragging the AI complex down).

**The filter belongs in the spec, not in each run's judgement:** the event book's population is
defined by the universe, and an unfiltered pull publishes a list that looks like a market and is
not one.

### 3. TradingView `earnings_release_date` is NOT a catalyst — it can be stale, and it can be mid-session

NBIS gapped **−13.5%** on its Q3 print (a much-smaller-than-expected loss and a revenue beat) and
TV still carried `earnings_release_date = 2026-08-12` for it. Several names carry a **10:30 ET**
stamp, which is neither a before-the-open nor an after-the-close slot. Treating the field as the
catalyst would have published a false cause for the largest mover in the book.

**Rule to add to §6.13 §2:** `earnings_release_date` is a **candidate** catalyst, published with
its source and its ET timestamp; it is asserted as a catalyst only when the issuer's release or
the wire confirms it. Where nothing is confirmed, the artifact says **"no catalyst confirmed in
this run"** — which is what today's event book does for 8 of the 21 names.

---

## 2026-11-12 — RUN ANALYSIS: where the 5 minutes went, and what a better run looks like

Measured from the 2026-11-12 08:34 ET fire (dispatch 08:34:11 ET, pushed 08:39:25 ET, 5.2 min
end-to-end; `window_check.sh` `stall_min: 1`; 1 of 12 flagged — MARA −5.74%; checker 27/27).

### The timeline (measured, not estimated)

| phase | measured | notes |
|---|---|---|
| platform stall before the first tool call | **1 min** | `stall_min: 1` — under the 5-min threshold, so no stall error |
| fetch ladder — 12 files, 177 KB of instruction | **~40 s** | `SKILL.md` 144,913 B + `PROMPT-BLOCKS.md` 31,782 B + 10 helpers; ~130 HTTP requests in the whole run, **48 of them tape pulls** |
| MCP probe | ~10 s | `catalog_ok total=135 finance_tools=0`, `bridge_ok` |
| universe resolver (`premarket-universe-v2`) | **~40 s** | 6/6 hard assertions OK, 12/12 closes confirmed |
| tape pull (`premarket-artifact-v5`) | **41 s** | 48 tape pulls + 12 `/info` + 12 Cboe + 1 TV, 6-way parallel |
| TradingView pulls (focus + event book) | ~20 s | 5 scans, **2 of them mine and wasted** (unfiltered) |
| 5 web searches + 2 CoinGecko | **~70 s** | ~30 KB of page text ≈ 8k tokens — **more expensive than all the market data** |
| artifact build | ~50 s | `build_artifact.py`, **19 KB of Python hand-written in the sandbox** |
| checker + push + verify | ~60 s | worktree build copies the whole `daily-screens` tree (723 files) |

### 1. The four-pull tape policy is 48 requests where 24 would do — and it is INERT against a stable cache

Every one of the 48 tape responses carried a **cache-hit**, and **10 of the 12 symbols returned a
SINGLE vintage across all four pulls** — the "newest internal timestamp wins" rule had nothing to
choose from. Only PEPG served two vintages (08:19:13, 08:21:03) and the rule correctly took the
newer one. Measured latency: **1.2–3.3 s per tape request** (2.2 s average), so 48 pulls ≈ 17.5 s
of tape wall clock at 6-way parallelism; cutting to "pull while the vintage is still changing
(min 2, max 4)" saves ~24 requests ≈ 9 s with **identical output**.

Worse: the defence cannot see staleness, because here staleness is "**no new prints**", not "an old
cached copy". The newest print at the moment of the pull was **14–24 minutes old** for 11 names and
**86 minutes old for TNGX** (last print 07:09:31 ET). The artifact did not publish that lag.

### 2. There is NO artifact renderer — the contract markdown is hand-written on every fire

`premarket_pull.py` writes `_premarket-pull.json`, `premarket-pull.md` and the contract **CSV**,
but **not** `pre-market-gapper.md`. SKILL.md §6.7's markdown skeleton is therefore authored by the
agent, by hand, every fire. This run wrote a **19 KB builder** (`build_artifact.py`) that exists
only in the sandbox and will be re-invented, differently, next time — the exact class of drift the
contract exists to prevent, and the reason a hand-typed number is always a defect.

**The fix (highest value in this document):** land `tools/render_premarket_artifact.py` in the
repo, fetched at RUN time behind a capability marker (`premarket-render-v1`), fed by
`_premarket-pull.json` + `_universe.json`. It owns the markdown, so the artifact becomes
byte-reproducible, every number stays engine-owned, and ~50–90 s of agent authoring disappears
from every fire.

### 3. The Focus book structurally cannot contain the day's gappers — the event book must lead

The Focus list is a **prior-day momentum screen**. On 2026-11-12 it contained **0** of the day's
real movers (LUNR +11.5% on a pre-open Q3 beat, TTEK +11.1% on a post-close Q4 beat, NBIS −13.5%
and CRWV −10.0% on Nvidia's CEO news) and produced **no positive gappers at all**. The artifact
published the market-wide event book as an **appendix**; its headline was "1 of 12 flagged" while
the tradable gap of the morning was LUNR +11.5%.

**Fix:** make the market-wide ladder (≥8% / 4–8% / 2–4%) with catalysts the **primary** table and
the Focus book the second table. Zero extra cost — the data was already pulled.

### 4. Two fields that would have removed today's false positives and stale reads

| field | why | cost |
|---|---|---|
| `driver_class` — `IDIOSYNCRATIC` / `CRYPTO_BETA` / `SECTOR_BETA` / `MARKET_BETA` | **MARA cleared the gate but is bitcoin beta** (BTC $72,574, −1.51%), and NBIS/CRWV are an index/news drag. A gap with a named driver is not a setup. | one rule per row + the driver already sourced from the wire |
| `tape_lag_min` | the print behind each published gap was **14–24 min old** (TNGX: 86 min) and nothing in the artifact said so | zero extra calls (the timestamp is already in the record) |

Also free: the sweep's own `focus.csv` carries `today_change` / `chg_pct_resolved` — **prior-session
change** on every row tells the reader whether a gap is a continuation (AAON was +19.3% into the
prior session) or a reversal. Zero extra calls.

### 5. The instruction payload is the largest single lever

The routine fetches **177 KB of instruction** (145 KB `SKILL.md` + 32 KB `PROMPT-BLOCKS.md`) to
read **§6**. This run mitigated it by reading selectively (lines 1–1,380 were never read), but
every fire rediscovers the section offsets by grep. **Fix:** publish
`cloud-prompts/skills/stock-screener-suite/specs/premarket.md` (~15 KB: §6 + the constants + the
checker's assertions) and point the prompt at it. 177 KB → ~50 KB, with no behaviour change.

### 6. Smaller wins

- **Cboe is fetched twice** (resolver + pull), 12 requests ≈ 4–5 s. The resolver's confirmation
  data can ride along in the manifest, which the pull already reads.
- **The searches cost more than the data**: 5 searches ≈ 70 s and ~8k tokens for 8 catalysts.
  Three targeted queries (earnings-driven gainers / the AI complex / the crypto name) would do,
  and any name whose only "catalyst" is a TV timestamp should be skipped.
- **Two of the four TV scans were wasted** (mine, unfiltered): 79 up / 313 down, almost all penny
  stocks and single-stock leveraged ETFs. The `type=stock` + `market_cap_basic > 200000000` filter
  belongs in the spec (see the section above).

### B. Errors, quality issues and connection problems on this fire

1. **The 30-second tool timeout killed a bundled call.** `probe_mcp.py` + the resolver were run in
   ONE bash call; the probe alone exceeds 30 s, so the call was killed and the resolver never ran.
   The probe is healthy — `catalog_ok total=135 finance_tools=0` — when given 120 s. **A killed
   call is a timeout, not a missing source**, and no two steps should share a 30 s call.
2. **The tape endpoint is slow (1.2–3.3 s/request) and header-sensitive.** A bare request with
   minimal headers returned **143 bytes** — an error envelope, HTTP 200 — while the helper's full
   browser header set worked. The fleet rule "sanity-check the body, not the status" holds here.
3. **The shared HTTP cache served all 48 pulls** (cache-hit on every one) and was stable, so the
   fixed-N defence was inert on 10 of 12 names and could not see the 14–86 min print lag.
4. **The known Nasdaq defects all fired and all were handled**: `secondaryData.lastSalePrice`
   disagreed with the settled close on **3 of 12** names (BW 4.82 vs 4.84, TNGX 25.70 vs 25.73,
   ZETA 37.76 vs 37.74) — rejected, and named in `## Flags`; GDYN's `primaryData` was a **quote**
   (+8.46%) against a −0.58% tape — published as separate columns; TradingView's
   `premarket_volume` **undercounted** (MARA 497,399 vs 732,319) — cross-check only.
5. **TradingView `earnings_release_date` is a candidate catalyst, not a catalyst** (NBIS carried
   2026-08-12 on a −13.5% earnings gap; several names carry a 10:30 ET stamp that is neither a
   pre-open nor a post-close slot). 8 of the 21 event-book names were published as "no catalyst
   confirmed in this run" — correct, but it must be a spec rule, not per-run judgement.
6. **The contract CSV's `pm_high` / `pm_low` / `exec_notional` are formatted STRINGS** — a naive
   `float()` raises while the checker passes (see the section above).
7. **My own reply inaccuracy, caught:** the first draft said "delivered 08:56 ET, 22 min after the
   08:34 fire". The pushed commit's `committer.date` is **13:39:25Z = 08:39:25 ET, 5 min**. Read
   the push time from the pushed commit, never from the clock while writing.
8. **No finance-source connection failures.** The MCP bridge answered (`bridge_ok`,
`packs=tradier,fmp,market-recap`), and Nasdaq / Cboe / TradingView / CoinGecko all served. The
only failures were (1) the tool timeout and (2) my own thin-header curl.

### The five changes, in order of value

1. Land **`tools/render_premarket_artifact.py`** — the contract markdown becomes engine-owned.
2. Add **`tape_lag_min`**, **`driver_class`** and **`prior_session_change`** to the contract CSV,
   and make the **market-wide ladder the primary table**.
3. Replace the fixed 4-pull with **"pull while the vintage changes (min 2, max 4)"** + one
   **spread re-pull** at ~09:15 ET (the spec's "across the run" intent), and publish the lag.
4. Split §6 into **`specs/premarket.md`** so the routine fetches ~50 KB of instruction, not 177 KB.
5. Put the **event-book filters** (`type=stock`, cap > $200M) and the **catalyst-confirmation rule**
   in the spec, so neither depends on a run's judgement.

---

## 2026-11-13 — the v6 PIPELINE: the markdown is engine-owned, the ladder leads, the lag is published

The run analysis above ended with five changes. **Three of them are landed here** (the ones
approved on 2026-11-13): the renderer, the new published fields, and the adaptive pull with the
re-pull wave. The other two (splitting §6 into its own spec file, and the search budget) are
noted below as the remaining work.

### 1. THE CONTRACT MARKDOWN IS NOW ENGINE-OWNED

`scripts/render_premarket_artifact.py` (marker **`premarket-render-v1`**) writes BOTH contract
files — `pre-market-gapper.md` and `pre-market-gapper.csv` — from the pull's
`_premarket-pull.json` plus the universe manifest. The pull (marker **`premarket-pull-v2`**)
owns the NUMBERS and no longer writes the CSV, so **there is one owner per output file** and
the two can never disagree about a column set.

Until now the markdown was typed into the chat context on every fire (~140 lines, every number
a transcription, the builder living only in one sandbox). The renderer is fetched at RUN time
behind its marker, and the skill says plainly: **never hand-write the markdown; if the renderer
is unavailable there is no artifact.**

### 2. THE MARKET LADDER IS THE PRIMARY TABLE

The renderer publishes `## Market ladder — the day's pre-market gaps` **before** the Focus
scan, from the engine's own `market_ladder` (TradingView, `type=stock`, market cap > $200M,
pre-market volume > 20,000, `|gap| >= 4%`). The Focus book follows. The checker asserts the
section exists, that it comes first, and — with `--pull-json` — that its rows ARE the engine's
rows.

### 3. THREE NEW PUBLISHED FIELDS

| field | why |
|---|---|
| `tape_lag_min` | the newest print's age against the wall clock. Measured 2026-11-12: 14–24 min for 11 of 12 names and **86 min** for one, and the v5 artifact said nothing. A lag over 30 min is named in `## Flags`. |
| `driver_class` | `CATALYST` / `CRYPTO_BETA` / `MARKET_BETA` / `SECTOR_BETA` / `IDIOSYNCRATIC` / `NO_MOVE`. **A gap that clears the bar is not automatically a setup** — MARA cleared the gate on 2026-11-12 and was a bitcoin gap. The class is the STRUCTURAL driver; a confirmed catalyst is appended to `driver_basis` rather than overriding it. |
| `prior_session_change` | the denominator session's own move, from the sweep's `focus.csv` — costs no extra call and separates a continuation from a reversal. |

`pm_volume_pct_30d`, `sustained` and `catalyst` ride along in the same contract.

The driver is measured against the index proxy (SPY), the sector proxy and bitcoin **on the
same TradingView snapshot as the name**, so the two numbers are comparable; the published gap
stays the Nasdaq tape's.

### 4. THE PULL STOPS EARLY, AND A SECOND WAVE IS SPREAD ACROSS THE RUN

- **Adaptive pulls:** the loop stops when two consecutive pulls carry the same vintage (min 2,
  max 4) and keeps going while the vintage rotates. Measured 2026-11-12: 36 of the 48 requests
  were redundant (~9 s of wall clock at 6-way parallelism) — with identical output.
- **The re-pull wave** (`--re-pull`) re-pulls only the **decision-relevant** names (`|gap| >= 2%`
  or a lag over 45 min), merges a newer print when it finds one, recomputes the verdict, and
  records the wave. It is the divergence record the spec asked for in §6.5 rule 5 and the burst
  of pulls could never produce.

### 5. THE CHECKER, THE TEST AND THE CONTEXT FILE

- `tools/check_premarket_artifact.py` is now `PREMARKET_CHECK_V2`: it asserts the two
  capability markers in the marker line, the v6 fields on every row, the driver vocabulary, the
  ladder's presence, its position and its agreement with the engine, and that the reply names
  the market's top 3 gaps. The v5 clauses still apply to a v5 artifact — the version comparison
  is explicit so that bumping the contract never silently DISABLES a clause.
- `tools/test_premarket_pipeline.py` — **20 offline checks**, and it caught two of my own bugs
  while it was being written (a fixture that met the gate but was not marked FLAGGED, and a
  driver precedence that was not what the spec said). It pins the adaptive pull, the lag and the
  driver classes, and it renders an artifact and asserts the checker ACCEPTS it.
- `premarket-context.json` is the only channel for what a machine cannot derive — the
  **confirmed** catalysts. A TradingView `earnings_release_date` is a candidate, not a
  catalyst; a name with none is published as "no catalyst confirmed in this run".

### STILL TO DO (not landed here)

- **Split §6 into `specs/premarket.md`** (~15 KB) so the routine fetches ~50 KB of instruction
  instead of 177 KB. The run analysis measured the instruction payload as the largest single
  lever on the routine's wall clock.
- **Cap the searches** at 4 and skip any name whose only "catalyst" is a TV timestamp.

### THE CHANGE A FIRE MUST MAKE

```bash
python3 "$U" --fire-date <date> --out-dir "$D"                       # prove the universe
python3 "$S" --from-csv <focus.csv> --universe-manifest "$D/_universe.json" --out-dir "$D"
python3 "$S" --re-pull --out-dir "$D" --re-pull-min-gap 2 --max-lag-min 45
python3 "$R" --pull-json "$D/_premarket-pull.json" --universe-manifest "$D/_universe.json" \
    --context "$D/premarket-context.json" --out-dir "$D" --date <date>
python3 "$C" --md "$D/pre-market-gapper.md" --csv "$D/pre-market-gapper.csv" \
    --pull-json "$D/_premarket-pull.json" --reply /workspace/reply.txt
```

---

## 2026-11-13 08:34 ET — a MISSING SWEEP is a DEGRADED READ, not a missing board

**The incident.** Cron #09's 2026-11-12 18:30 ET sweep died on a transport error and
published nothing (see `IMPROVEMENTS-cron09-stock-screener-suite.md`). Cron #08's strict
universe resolver therefore failed H3 — *"universe session 2026-11-11 vs expected prior
session 2026-11-12 — the sweep for the prior session has not published"* — and exited 3.
**Measured, not assumed:** the strict resolver for the 2026-11-13 fire was run against the
live sources and exited 3 with that exact assertion. Without a change, the routine would
have produced **no artifact at all** for 2026-11-13.

**The fix, and why it is safe.** The resolver's escape hatch (`--allow-stale-universe`)
already existed; what was missing was the ROUTINE that uses it, and a contract that says
what a degraded run owes the reader.

| rule | landed in | why |
|---|---|---|
| the run sequence retries the resolver with `--allow-stale-universe` when the strict run fails on **H2/H3** (the expected session's sweep has not published) | SKILL §6.6 | a missing sweep must not cost the whole morning |
| the reference close comes from the **INDEPENDENT sources only** | the resolver's degraded mode | the stale CSV's close belongs to a different session — that is the wrong-number bug H3 exists to prevent. Measured on the degraded run: AAON's close came from `tradingview:close` = 78.80, confirmed by Cboe (last trade 2026-11-12T15:59:59) and Nasdaq's session-exact history — all three agreeing |
| the artifact **publishes** `universe_stale` in `## Flags` and names it in the TL;DR caveat | the renderer | an unflagged stale universe is a hidden degradation |
| the checker FAILS an unflagged universe/denominator mismatch, and FAILS a close taken from the stale file | `check_premarket_artifact.py` | the guard keeps its teeth: only the **declared** degradation passes |
| the resolver's failure message now names the fallback when the cause is a missing sweep, and says there is NO fallback when the close itself is wrong | `premarket_universe.py` | a fire that reads the failure must not stop at "there is no run" when a documented path exists |

**Verified end-to-end on the real 2026-11-13 inputs** (degraded resolver → pull → renderer
→ checker): **30/30 contract checks passed**, with the CSV carrying
`universe_date = 2026-11-11`, `ref_close_date = 2026-11-12` and
`universe_source = tradingview:close` on every row.

**Two smaller defects the degraded run exposed, both fixed:**

1. **`universe_source` was EMPTY on every row of the degraded CSV.** The renderer read it
   from the manifest, which has no such key in the degraded mode. The pull now carries
   `universe_date` / `ref_close_date` / `universe_source` **per record**, so the renderer
   never guesses them.
2. **A failed ladder scan sank the whole artifact.** The checker failed the run because the
   Market ladder section had no table — but the ladder is CONTEXT, and a failed TV scan
   must not sink the Focus book. The rule is now: the engine's `market_ladder` decides
   (an empty ladder on both sides is fine; rows on one side and not the other is a
   failure).

## 2026-11-13 — the re-pull wave crashed on an undefined attribute, so the mandatory second wave never ran

**Symptom.** `python3 tools/premarket_pull.py --re-pull --out-dir <D> --re-pull-min-gap 2 --max-lag-min 45`
died with `AttributeError: 'Namespace' object has no attribute 'no_ladder'` at
`premarket_pull.py:1155`:

```python
if args.ladder and not args.no_ladder:      # args.no_ladder does not exist
```

`--no-ladder` is declared with `dest="ladder"`, so `args.ladder` is the only attribute that
exists. The `AttributeError` fired **before** the wave merged a single tape, so the mandatory
RE-PULL WAVE (SKILL §6.6) was silently skipped on every fire — the run still produced an
artifact, which is exactly how a broken step stays invisible.

**Fix (landed).** One line — `if args.ladder:` — in
`cloud-prompts/skills/stock-screener-suite/scripts/premarket_pull.py`
(commit `fd4f13c`, run-time fetched, so the next fire has it with no `cron_update`).

**Why it is not cosmetic.** The burst of pulls protects against a ROTATING cache; only a wave
spread across the run protects against a tape that is simply OLD (a stable cache returns the
same vintage however many times it is asked). On this fire the wave moved **AAON +2.27% →
+1.84%** and **HROW +6.01% → +3.50%** — two verdicts changed because the wave ran at all
(HROW went from `BORDERLINE_THIN` on a 6% print to `BORDERLINE_INTRADAY` on a 3.5% tape that
had faded).

**The general rule.** The run-time fetch checks a **capability marker** (`premarket-pull-v2`),
which proves the script is the right generation — it does not prove that every *path* in it
runs. A path that was never exercised by a fire is a path that can be broken. The re-pull wave
is the path most exposed to this, because on most fires it re-pulls nothing and the defect
never changes an outcome.

**Also checked on this fire (no action needed).** `_fetch_tv()` returns a **2-tuple**
(`stocks, proxies`) and the call site unpacks **2** targets — the earlier report of a 7-key
dict on `main` did not reproduce on the file fetched on 2026-11-13; the call site is
`tv_rows, proxies = (_fetch_tv(syms) if args.tv else ({}, {}))`.

**This fire's verified result.** Strict resolver failed on H3 (cron #09's 2026-11-12 sweep never
published) → degraded resolver → pull → re-pull wave → renderer → checker:
**34/34 contract checks passed**, `flagged: 0`, `scanned: 12`, `universe_date = 2026-11-11`,
`ref_close_date = 2026-11-12`, `universe_stale` published in `## Flags` and in the TL;DR caveat.

---

## 2026-11-13 08:34 ET — the v6 pipeline FIRED: 32/32, and the live artifact exposed three defects

**The fire.** Cron #08 fired at 08:34 ET and pushed at **08:41:38 ET** (7.6 min). The
published artifact passes the **current** checker (fetched from the repo at the time of this
check) **32/32**, and every v6 clause holds:

| clause | result |
|---|---|
| the marker line | `premarket-artifact-v6 … pull: premarket-pull-v2 · renderer: premarket-render-v1` ✓ |
| `## Market ladder` **before** `## Focus scan` | ✓ (line 13 vs line 47) |
| the CSV's v6 fields | `tape_lag_min` / `driver_class` / `prior_session_change` / `pm_volume_pct_30d` / `sustained` ✓ |
| the degraded universe | `universe_stale` published in `## Flags`; every row's `ref_close_source` = `tradingview+cboe+nasdaq-secondaryData+nasdaq_historical` (never `focus.csv`); `universe_date` 2026-11-11, `ref_close_date` 2026-11-12, `universe_source` `tradingview:close` ✓ |

**The headline worked.** 0 of 12 Focus names flagged (the book is a session stale and the tape
was thin), and the TL;DR leads with the MARKET's gaps — **NPCE −40.9%** (Q3 revenue $23.1M vs
$27.05M consensus, FY26 guidance cut), **MOD +37.7%** (Samsung in talks to acquire Modine,
~$5.6B), **CADL −33.7%** (BLA filing pushed to mid-2027), **LFTO +27.0%** (Q3 beat, guidance
raised). On 2026-11-12 the same artifact's headline was "1 of 12 flagged" and the flagged name
was a bitcoin-beta gap on a thin print. **That is the v6 change paying for itself on the first
live fire.**

**Three defects, all visible only in the LIVE artifact** (the offline replay could not see
them — it used a hand-built fixture):

1. **`pm_volume_pct_30d` published `n/a` on EVERY row.** The renderer computed the ratio into
   `r["_volpct"]` and wrote a differently named key (`pm_volume_pct_30d`) into the CSV. The
   30-day average volume was in the record all along (`tv_avg_volume_30d`). **A column that is
   a placeholder on every row is a silent failure, not a missing value** — the checker now
   fails it explicitly.
2. **The marker named a close source that did not provide it.** It said
   `reference close: prior sweep focus.csv` while the close came from the independent
   sources (the stale universe's whole point). The marker now names the source the rows
   actually used.
3. **A NAMED context file that was not on disk published "no catalyst confirmed in this run"
   for every name, silently.** Found by re-rendering: the renderer ignored a `--context` path
   that did not exist, and the artifact looked complete with every catalyst gone. It now
   **fails loudly** (exit 3) when the context file is missing or carries no `catalysts`.

**Correction pushed.** The 2026-11-13 artifact was re-rendered from the **published**
`_premarket-pull.json` and `premarket-context.json` — so every number is the fire's own —
and the diff against the published artifact is **exactly two fields**: the marker's
reference-close label and the `pm_volume_pct_30d` column. Pushed as a labelled correction
commit (`cron 08 … 2026-11-13: correction`), both paths verified.

**Also resolved: cron #09's 11-12 sweep.** The platform **resumed the crashed turn in place**
and it published at **08:52 ET** — `daily-screens/2026-11-12/focus.csv` and `focus.md` are
now on `main`. So the universe that today's fire had to run degraded is complete, and tonight's
18:30 ET sweep will publish the 2026-11-13 Focus list for tomorrow's fresh fire.
