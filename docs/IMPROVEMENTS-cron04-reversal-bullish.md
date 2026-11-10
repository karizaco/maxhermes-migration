# Improvements — cron #04 `reversal-bullish-3:55`

- **Date:** 2026-11-10 (the 15:55 ET fire, session `2026-11-10`)
- **Scope:** the routine's **post-close** read path — `tools/reversal_bullish.py` and
  `cloud-prompts/skills/stock-screener-suite/SKILL.md` §5.
- **Found by:** the routine's own 2026-11-10 run, which had to re-read the screen four times
  before the bar it published was the one a trader could actually transact at.

## The finding

The skill's standing instruction was "re-run the screen after the close" (§5, the memory note
that a 15:55 read can publish a degenerate 0.00% risk line). **That is not sufficient.**
TradingView's daily bar does not carry the 16:00 close for the first ~20 minutes after the
bell, so a re-read at 16:02–16:10 ET can still be a **pre-auction print**. Measured on
2026-11-10, the same session was read four times:

| read (ET) | what the bar held | passers | what it would have published |
|---|---|---|---|
| 15:56 | partial session bar | 5 | EAT with a **0.00% stop line** (stop = entry) |
| 16:02 | pre-auction print, TV close still moving | 4 | EAT with a 0.00% stop; DOCU's stop = 75.56 (bar low) |
| 16:04 | pre-auction print | 5 | EAT with a 0.00% stop; TRI's stop = 108.50 (body low) |
| **16:23** | **the official 16:00 close** | **4** | EAT **and** EFX both fail the settled close |

The difference is not cosmetic:

- **EAT (Brinker)** on the pre-auction print: close 196.87, body low = 196.87 ⇒ published stop
  **196.87 = the entry**, a 0.00% risk line, `stop_class NOISE_BREACH` with the real structural
  level 3.62% below the entry (over Bonde's 2.5% cap). On the settled close (195.17) the DCR is
  0.512 < 0.60 and the body ratio is 0.455 > 0.30 — **the gate fails outright**.
- **EFX (Equifax)** on the pre-auction print: close 186.94 ⇒ DCR 0.718, body 0.080, a clean
  passer. On the settled close (188.30) the body ratio is **0.373 > 0.30** — the gate fails.
- **DOCU** on the settled close: the 2.5% cap binds, so the published stop is 75.72 — **0.21%
  ABOVE** the 75.56 bar low ⇒ `NOISE_BREACH`, structural risk 2.70% (over the cap).
- Cross-check that proves the settled closes: `market-recap get_quotes` (Yahoo) with
  `as_of 16:00:00 ET`, `market_state post` — DOCU 77.66, TRI 108.41, SYK 324.155, EFX 188.30,
  EAT 195.17. The scanner's pre-auction close for EFX (186.94) differed by **0.75%** — far
  outside the noise a same-feed rounding error could explain.

**Rule:** a post-close read is only a settled read after the daily bar has finalized. The
entry price published must be the official close, because that is the price the trader can
transact at (Bonde enters 3.58–4PM or MOC).

**This does not change the 15:55 fire.** A fire that publishes inside the entry window uses the
LIVE read and says so (the 16:00 print can still move the close). The rule applies only when the
artifact is published AFTER the bell — a resumed fire, a late re-read, or an explicit
post-close republication. The 2026-11-10 fire was published at 16:25 ET and hit exactly this.

## The changes

### `tools/reversal_bullish.py` (run-time fetched ⇒ the next fire picks them up)

1. **`session_is_settled(date_str)`** — True when the read happens after the 16:00 ET bell for
   the scanned session (and for a replay of a past session).
2. **`report["candle_settled"]`** — the flag is now in the JSON report, so a run can prove it
   read a settled bar.
3. **Post-close-accurate method bullets.** After the bell the volume caveats INVERT: `v >= 290000`
   and `vol_vs_30d_avg_pct` become FULL-day numbers, so the artifact must not carry the
   "partial day's volume" wording. The script now emits the correct variant (and the TL;DR's
   entry note becomes "entry = the settled 16:00 ET close"). A false method bullet is worse than
   a stale one.
4. **The history source is now stated truthfully.** The source table hardcoded
   "shibui-finance … ok" even when the run fell back to Nasdaq. It now names the fallback, and
   publishes `degraded_sources: 1` so the reply's `errors:` count can match it exactly.

### `cloud-prompts/skills/stock-screener-suite/SKILL.md` §5 (also run-time fetched)

New section **"THE DAILY BAR FINALIZES LATE — a post-close read is not automatically a settled
read"**: the four-read evidence table, and the procedure — read at ~16:20–16:25 ET, cross-check
the close against `market-recap get_quotes` and treat a **>0.3%** disagreement as "not settled
yet", never publish a pre-auction print, and re-derive the candidate set from the settled read
(the gate matrix, the stop class and the promoted set all change with the final print).

### Procedure only — no prompt change

The deployed prompt is untouched: the skill and the script are fetched at RUN time, so these
changes land on the next fire with no `cron_update` and no byte-drift risk.

## What the 2026-11-10 artifact published after the fix

Four passers on the settled bar (DOCU, SYK, ADBE, TRI) and **one** promoted idea — SYK, whose
stop (317.87) IS the signal bar's low, so it is the only candidate whose risk line is usable for
sizing. The other three publish a stop inside their own bar (DOCU capped at 75.72, ADBE 236.70
and TRI 108.41 each exactly the entry) and were left on the watchlist with invalidation levels.
