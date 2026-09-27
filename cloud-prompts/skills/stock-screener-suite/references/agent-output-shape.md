# Agent output shape — what the consume step expects

`scripts/screen.py consume` reads one JSON file at
`C:/Users/admin/AppData/Local/Temp/stock-screener-results-<DATE>.json`
and applies the tiering/regime logic to produce the per-stylist .md,
master/stalk/focus/tier-a .md, _regime.json, _summary.md, and the
parabolic-short + long-reversal CSVs.

This doc is the **canonical contract** for what shape the daily-sweep
Agent must emit. Anything that drifts from this contract means a manual
patch in `consume` is needed (and that's brittle). When in doubt,
follow this exactly.

---

## Top-level keys

| Key | Type | Required? | Notes |
|---|---|---|---|
| `date` | `YYYY-MM-DD` | yes | Logical data date (T+1 of shibui's MAX(date), so usually yesterday's close). |
| `data_as_of` | `YYYY-MM-DD` | yes | Same as `date` for our case — the most recent settled bar. |
| `run_at_utc` | ISO 8601 UTC | yes | When the Agent assembled this JSON. |
| `prefilter` | `list[dict]` | yes | shibui SQL `prefilter` output. Each row: `{symbol, exchange, market_cap, sector, close, volume, sma_20, sma_50, sma_200, rsi_14, atr_14, ...}`. |
| `sweep_stockbee` | `list[dict]` | yes | shibui SQL `sweep_stockbee` output (Stockbee 4%/volatility/breakout group). Each row: `{symbol, close, change_pct, volume, sma_50, rsi_14, atr_14, ...}`. |
| `sweep_qullamaggie` | `list[dict]` | yes | shibui SQL `sweep_qullamaggie` output. |
| `sweep_peoplewish` | `list[dict]` | yes | shibui SQL `sweep_peoplewish` output. |
| `jeff_sun_canslim` | `list[dict]` | optional | TV `screen_stocks` output (CANSLIM filters). Empty list is fine. |
| `ariel_sector_rs` | `list[dict]` | optional | TV `screen_etf` output (base namespace, NOT advanced). Empty list is fine. |
| `volume_breakout` | `list[dict]` | optional | TV-advanced `volume_breakout_scanner` output. Empty list is fine. |
| `breadth` | **list of row dicts** (not a pre-aggregated dict) | yes | The **raw** shibui SQL `breadth` output. `consume` then computes `index_below_20sma`, `atr_extensions`, etc. internally. **Do NOT pre-aggregate** — see "Three acceptable shapes" below. |
| `vix_price` | `number` | yes | Yahoo-finance `^VIX` last close. |
| `vix3m_price` | `number` | yes | Yahoo-finance `^VIX3M` last close. `^VXV` has no live data; use VIX3M as the long-end proxy. |
| `sector_rotation` | `list[dict]` | optional | financekit `sector_rotation` per-sector returns. |
| `reversal_bullish` | `list[dict]` | optional | shibui SQL `reversal_bullish` output; rows MUST carry a `_source` field (`mcp` / `finviz_fallback`). |
| `degraded` | `bool` | optional | Set `true` if any Tier-1 MCP rate-limited twice in one session — surfaces in `_summary.md`. |
| `degraded_notes` | `list[str]` | optional | One line per degraded MCP, human-readable. |

---

## Three acceptable shapes for `breadth`

`consume` does its own pre-aggregation in `compute_regime()` so any of
the following work. This is the lesson from the 2026-09-21 smoke-test
bug fix.

### Shape A — raw shibui SQL rows (preferred)

```json
"breadth": [
  {"metric": "largecap_breadth", "breadth_pct_largecap": 25.0547, "n_stocks": 500},
  {"metric": "index_above_sma_summary", "pct_above_sma_20": 0.2, "pct_above_sma_50": 0.4},
  {"metric": "index_atr_extension", "etf": "SPY",   "extension_pct": 0.26},
  {"metric": "index_atr_extension", "etf": "QQQ",   "extension_pct": 1.62},
  {"metric": "index_atr_extension", "etf": "IWM",   "extension_pct": -3.74},
  {"metric": "index_atr_extension", "etf": "QQQE",  "extension_pct": -1.66},
  {"metric": "index_atr_extension", "etf": "RSP",   "extension_pct": -2.28}
]
```

`compute_regime` finds the `largecap_breadth` row → `breadth_pct`, the
`index_above_sma_summary` row → `index_below_20sma = pct_above_sma_20 < 0.5`, and the per-ETF `index_atr_extension` rows → `atr_extensions`.

### Shape B — pre-aggregated dict (what the daily-sweep Agent
naturally emits when it summarises Shape A)

```json
"breadth": {
  "largecap_breadth_pct_above_sma_20": 25.05,
  "index_pct_above_sma_20": 20.0,
  "index_pct_above_sma_50": 40.0,
  "indices_atr_extension_pct": {
    "SPY": 0.26, "QQQ": 1.62, "IWM": -3.74, "QQQE": -1.66, "RSP": -2.28
  }
}
```

`compute_regime` parses `largecap_breadth_pct_above_sma_20` → `breadth_pct`,
`index_pct_above_sma_20 < 50` → `index_below_20sma`, and the dict of
`indices_atr_extension_pct` → `atr_extensions`.

### Shape C — old canonical dict (backwards compat)

```json
"breadth": {
  "breadth_pct_largecap": 25.05,
  "index_below_20sma": true,
  "atr_extensions": {
    "SPY.NYSE":  {"extension_pct": 0.26},
    "QQQ.NASDAQ": {"extension_pct": 1.62}
  }
}
```

`compute_regime` parses direct keys.

---

## Per-row `_source` on every CSV

Every CSV row written by `consume` (or by the Agent when running
reversal-bullish) must carry a `_source` field. Consumers (the next-day
Agent, audit reviewer) rely on it to see which MCP backed the row.

| Field value | When |
|---|---|
| `mcp` | Default. Tier-1 shibui-finance SQL returned the row. |
| `finviz_fallback` | Tier-2 web_fetch on a Finviz screener URL backed it. |
| `tv_fallback` | Tier-3 web_fetch on a TradingView public JSON. |
| `yahoo_fallback` | Tier-4 web_fetch on a finance.yahoo.com HTML. |

Agent-emitted rows that lack `_source` are treated as `_source=mcp` by
default in `tier_candidates`, but writing it explicitly is the
contract.

---

## Why this doc exists

On 2026-09-21 the daily-sweep Agent (a) pre-aggregated the breadth
SQL rows into Shape B and (b) split sweep results across per-stylist
keys (`sweep_stockbee`, etc.) instead of merging them into one `sweep`
array. Both shapes diverged from what `consume` was originally written
for. We patched `compute_regime()` and `cmd_consume()` to handle all
three shapes; this doc is the durable record so the next Agent
doesn't re-introduce the mismatch.
