# Tiering — Master / Stalk / Focus

Reference for how the 5-stylist outputs collapse into a single actionable watchlist.

## Definitions

| Tier | Size cap | Selection rule |
|---|---|---|
| **Master** | 200 | Union of all 5 stylists, deduped by ticker |
| **Stalk** | 50 | Master ∩ (price within 2% of 10/20-DMA) ∩ (setup-confirming pattern tag in {compression, gap-up ready, MACD cross-up}) |
| **Focus** | 12 | Master ∩ (appears in ≥ **2** distinct stylists) ∪ (top-5 velocity names) ∪ (passes full 2LYNCH + EP criteria) |
| **Tier-A** | 8 | Focus ∩ (appears in ≥ **3** distinct stylists) |

**Why 2 / 3 instead of the original 3 / 4:** the original thresholds counted
`convergence_score` (UNIQUE ORIGIN LABELS), not UNIQUE STYLISTS. With 5
stylists × 2-3 origin labels each = 10-15 origins, `convergence ≥ 4`
divorced from the trader-facing notion of "convergence". After the
2026-09-21 back-test: original thresholds produced Tier-A = {USDE.NASDAQ}
(3 stylists × 4 origin labels — misleadingly labelled "convergence 4").
The new thresholds count UNIQUE STYLISTS (`n_stylists` field on the
`Candidate` dataclass) — see `scripts/screen.py:_STYLIST_FROM_ORIGIN` for
the mapping. Expected Tier-A size in a normal regime: 3-8 names. Tunable
in one place: `FOCUS_THRESHOLD_STYLISTS` and `TIER_A_THRESHOLD_STYLISTS`
constants in `scripts/screen.py`.

## Setup-confirming pattern tags

## Setup-confirming pattern tags

A name gets a tag if at least one of these matches:

- **compression** — `(atr_10 / atr_50) < 0.6` AND `close > sma20`
- **gap-up ready** — `(open - prev_close) / prev_close > 0.04` AND `(volume / avg_volume_20d) > 2`
- **MACD cross-up** — `MACD_hist > 0` AND `MACD_hist[1] <= 0`
- **higher-low base** — `low > low_5d_ago` AND `(high_5d - low_5d) / close < 0.08`

## Skip-rule flag attachment

Every Master / Stalk / Focus / Tier-A row carries these flags (booleans) computed from
the daily OHLC:

| Flag | True means | Practical effect |
|---|---|---|
| `atr_shrink` | ATR(14) < 60% of 3-month median | Setup "too quiet" — flag but don't drop |
| `wicky_breakout` | Breakout candle wick > body AND close RVOL < 1.2 | Abandon-setup signal |
| `ma_shrink_5d` | 5-day range < 50% of 20-day range | "Get tight" watchlist sub-list |
| `day2_no_follow` | Day-2 close below day-1 midpoint | Reconsider if holding from day 1 |
| `no_reclaim_15m` | Post-open: did not reclaim VWAP within 15 min | Stand-down signal |
| `second_bite_d2` | Day-2 didn't hold above day-1 midpoint by noon | Skip "second bite" entries |

## Regime flag (from Layer 5)

One regime payload per day, attached to every Tier-A row:

```json
{
  "size_cut_pct": 50,     // (index < 20-DMA) AND (breadth_pct < 40)  [Ariel]
  "uncertainty": false,   // vix_vxv_ratio > 1  [Sun]
  "late_cycle": false     // any of {SPY,QQQ,RSP,QQQE,IWM} atr_extension > 6× historical median
}
```

`size_cut_pct > 0` means the trader should reduce every Tier-A position by that % today.
`uncertainty=true` adds a header-level note but no size cut. `late_cycle=true` warns the
trader to tighten stops.

## Convergence weighting

Two distinct counters live on each `Candidate` in the script:

| Counter | Counts | Used for |
|---|---|---|
| `n_stylists` | UNIQUE stylists (collapse Stockbee A/B into one) | Tier selection (Focus / Tier-A thresholds) |
| `convergence_score` | UNIQUE origin labels (sub-screens from same stylist still count separately) | Chat-priority on the pre-market brief, multi-timeframe alignment flags |

A name that hits Stockbee 4% + Stockbee EP9m + Qullamägi + peoplewish has
`n_stylists = 3` (Stockbee, Qullamägi, peoplewish) and
`convergence_score = 4` (two Stockbee origins + one Qullamägi + one
peoplewish). Both numbers are surfaced in the markdown table column
"Stylists / Origins".

## Per-stylist origin tag

Every row in master.md / focus.md / tier-a.md carries a `stylist_origin` array listing
which of the 5 stylists' screens it appeared in. Examples:

```json
"stylist_origin": ["stockbee_4pct_breakout", "stockbee_ep9m", "peoplewish_adr", "qullamaggie_1m_leaders"]
```

This is what gets persisted into the `setup-journal` when a trade is opened on the name
— so we can later analyze "did names flagged by peoplewish + Qullamàgi outperform
names only flagged by Stockbee?"
