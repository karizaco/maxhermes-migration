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

---

## 2026-11-12 — the stop rule becomes Bonde's rule (contract v4)

**Triggered by:** the user asked to make the stop rule reflect how Bonde actually behaves.
**Decision recorded:** the **universe gate is unchanged** — `market_cap > $5B` + `avg_vol(10d) > 1M`
stay exactly as they are, including the `close > $5` floor. No institutional-holder gate was
added.

### What was wrong

The screen used a HOUSE stop rule that is not Bonde's:

> body low, except on a near-doji body (under 15% of the range) where the signal bar's LOW is
> used — then tightened to the 2.5% cap.

Bonde's published workflow (BreakoutsHappen, steps 4–5) says:

- you buy at 15:55–15:58 **without a stop**;
- the stop goes in the **next morning**, at the **low of the candle body** of the signal day,
  sized so the loss never exceeds **2.5%**;
- *"If you prefer to place the stop at the low of the shadow instead, make sure that level does
  not exceed a 2.5% loss from your purchase price."*

So the **body low is the default** and the **shadow low is a sanctioned alternative, legal only
within 2.5%**. The house rule had it backwards in two ways:

1. it substituted the shadow low for a **usable** body low and then **tightened it to the 2.5%
   cap** — a stop Bonde would never take, and one that can land inside the bar's range. On
   2026-11-10's DOCU bar the shadow low was 2.70% away (illegal by Bonde's own sentence), and
   the house rule published a 2.50% capped stop at 75.72 where Bonde's default body low was
   77.50 (-0.21%);
2. it **kept a degenerate body low** (a body low that sits ON the entry) whenever the body was
   ≥ 15% of the range — publishing a **0.00% risk line**, i.e. a stop AT the entry, on ADBE
   (236.70) and TRI (108.41) on 2026-11-10.

### The rule now implemented (contract v4)

| Situation | Published stop | Class |
|---|---|---|
| body low more than 0.10% below the entry | **the body low** (Bonde's default), capped at 2.5% | `BODY_LOW` / `CAPPED` |
| body low degenerate (on the entry) and the shadow low ≤ 2.5% away | **the shadow (bar) low** | `STRUCTURAL` |
| body low degenerate and the shadow low more than 2.5% away | none — **not a trade** | `NO_LEGAL_STOP` |
| otherwise | the body low, capped at 2.5% | `BODY_LOW` / `CAPPED` |

Every row now publishes **both** levels: `body_low`, `body_stop_pct`, `shadow_stop_pct`,
`body_stop_degenerate`, `stop_placement` ("next morning, after the open"), plus `stop_class`
(`STRUCTURAL` / `BODY_LOW` / `CAPPED` / `NO_LEGAL_STOP`).

**The class vocabulary changed, and so did what it means.** The stop goes in the next morning,
so the signal bar's own low — printed *before* the stop existed — is not a breach of it. The old
`NOISE_BREACH` label ("the bar already traded through it") described a stop that did not exist
yet. The v4 classes are: `STRUCTURAL` = the stop IS the bar low (the structural death level);
`BODY_LOW` = Bonde's default, inside the bar's range and therefore *tighter* than the structural
level; `CAPPED` = the 2.5% cap bound it; `NO_LEGAL_STOP` = no stop Bonde's rule accepts, so the
name is not a trade and may not be promoted.

### Effect on the 2026-11-10 screen

| Name | house rule | Bonde's rule | change |
|---|---|---|---|
| DOCU | 75.72 (-2.50%) `NOISE_BREACH` | **77.50 (-0.21%)** `BODY_LOW` | the illegal shadow stop is gone |
| SYK | 317.87 (-1.98%) `STRUCTURAL` | 317.87 (-1.98%) `STRUCTURAL` | unchanged |
| ADBE | 236.70 (**0.00%**) `NOISE_BREACH` | **231.82 (-2.06%)** `STRUCTURAL` | a real risk line at last |
| TRI | 108.41 (**0.00%**) `NOISE_BREACH` | **106.47 (-1.79%)** `STRUCTURAL` | a real risk line at last |

### Changes landed

- `tools/reversal_bullish.py` — new `stop_profile`; `CONTRACT_VERSION` → `bonde-artifact-v4`;
  new CSV columns; the Candidates table gains "Stop basis" and "Body low"; the TL;DR caveat and
  the method bullets describe the new rule and the next-morning placement.
- `tools/check_bonde_artifact.py` — accepts `bonde-artifact-v4` (and legacy `v3`, whose v4
  assertions are skipped) and adds the **v4 stop-rule assertions**: the published stop must be
  below the entry (a 0.00% line fails), a degenerate body low must force the shadow low, a
  usable body low may NOT be displaced by the shadow, a shadow more than 2.5% away fails, and a
  promoted name may never be `NO_LEGAL_STOP`.
- `tools/test_bonde_stop_rule.py` — new hermetic test: the four real 2026-11-10 bars pinned to
  their stops and classes, the `NO_LEGAL_STOP` and `CAPPED` cases, and **fault injection** that
  proves the checker rejects (a) a stop at the entry, (b) a shadow substituted for a usable body
  low, (c) an over-cap shadow stop — and accepts a compliant artifact.
- `cloud-prompts/skills/stock-screener-suite/SKILL.md` §5 — the gate table, the class table, the
  CSV column contract, the reply discipline and the fetch marker (`bonde-artifact-v4`); plus a
  note that **the universe proxy is fixed** and must not be changed without the user.
- `cloud-prompts/cron-prompts/04-reversal-bullish-3:55.md` — the stop paragraph rewritten to
  match, and the prompt redeployed (the repo file IS the deployed prompt).

Verified: `tools/test_bonde_stop_rule.py` 39/39; the v4 checker 41/41 on a filled real artifact
(the 2026-11-11 settled replay, 7 passers — 4 `BODY_LOW`, 3 `STRUCTURAL`, no 0.00% line).

---

## 2026-11-12 — the screen could not see its own truncation (`totalCount` was being dropped)

`tools/reversal_bullish.py::tv_scan()` did `json.load(fh).get("data", [])` — it **threw the
response's `totalCount` away**, so the only proof that the pull was complete was never in hand. A
pull whose `range` is smaller than `totalCount` is a SILENT TRUNCATION, and without the field the
screen could not refuse a short book.

**Landed:** `tv_scan()` returns `(rows, totalCount)`, and the screen path asserts
`len(distinct names) == totalCount` and raises `TRUNCATED SCAN … Refusing to publish a short book`
otherwise. The filtered universe is **951 names against the 2,000 cap** (49% headroom, measured
2026-11-12), so this was a latent guard, not a daily event — but the filter is on live columns
(`close`, `market_cap_basic`, `average_volume_10d_calc`), so it moves with the market.

**The sort was already right, and the reason is worth keeping:** the pull sorts by
`{"sortBy":"name"}` — a STABLE key — because the scanner's default order is not stable between
requests, and a pull paged on an unstable key silently duplicates and drops names (this module's
own docstring records the 2026-11-03 measurement: "1500 rows fetched, only 1212 unique → 288 names
lost").

Guard: `tools/test_tv_pull_completeness.py` (20 checks, hermetic) — it proves a truncated pull is
refused and a complete one screens every name.
