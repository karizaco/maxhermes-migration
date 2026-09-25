---
name: Cross-asset correlation snapshot
description: >-
  Weekly correlation matrix of the major asset proxies: SPY, QQQ, IWM, TLT,
  GLD, DXY (via UUP), VIX (when available), EEM. Used to spot regime shifts
  (risk-on/off, growth-value, commodity-Dollar coupling) that inform sector
  positioning for the week. Runs Sunday 16:30 ET, between macro calendar and
  the weekly brief.
---

# Cross-asset correlation — weekly snapshot

Single-purpose: produce a Pearson correlation matrix across the core asset proxies so the weekly brief can spot regime changes (stocks-bond decoupling, growth-value rotation, USD-gold rotation) and frame the week ahead.

## When
- Cron: `30 16 * * 0` America/New_York (Sundays, 16:30 ET — 17 min after macro-calendar, ~77 min before weekly brief)
- Manual: user asks "show me the cross-asset correlation" or "how correlated are bonds and stocks right now?"

## Output
- `C:\Users\admin\.minimax\projects\coding-shared\research\correlations\YYYY-Wnn-snapshot.md`
- Compact ≤ 10-line summary in chat reply.

## Universe (hardcoded 8 proxies)

| Proxy | Ticker | What it measures |
|---|---|---|
| S&P 500 | SPY | US large-cap equity |
| Nasdaq-100 | QQQ | US large-cap growth/tech |
| Russell 2000 | IWM | US small-cap |
| 20+ Year Treasury | TLT | Long-duration US rates |
| Gold | GLD | Precious metals / real rates |
| US Dollar | UUP | Broad USD vs basket |
| Emerging Markets | EEM | EM equity |
| VIX | ^VIX | Implied vol (skip if N/A — see step 4) |

Quarterly review for additions (e.g. XLE for energy, HYG for credit) — note in audit line if universe changes.

## Steps

1. **Compute window.** Default `period = 6mo` (6 months of daily closes). Valid options per `mcp__financekit__correlation_matrix`: `3mo`, `6mo`, `1y`, `2y`. Use `6mo` unless the user explicitly asks for a longer window.
2. **Single batched call.** `mcp__financekit__correlation_matrix(symbols="SPY,QQQ,IWM,TLT,GLD,UUP,EEM,^VIX", period="6mo")`. One call covers everything.
3. **Parse response** into a symmetric matrix (handle VIX specially — see step 4).
4. **VIX handling.** VIX often drops from correlation_matrix output (different scale, intermittent). If absent: log under Source health, drop ^VIX column from the matrix, continue.
5. **Read the matrix:**
   - Identify pairs with |corr| > 0.7 (strong relationship) — note regime signal
   - Identify pairs with |corr| < 0.2 (effectively uncorrelated) — diversification value
   - Watch for week-over-week delta (compare current snapshot file with prior week): if any pair moved >0.2 absolute, flag as `REGIME_SHIFT`
6. **Write markdown:**
   1. TL;DR (≤3 lines): regime tag (e.g. "stocks/bonds still negatively correlated, USD/Gold positively correlated — risk-off tone persists")
   2. Full correlation matrix as a markdown table
   3. Highlight pairs: top 3 strongest |corr|, top 3 weakest |corr|
   4. Week-over-week delta (if prior week exists)
   5. Source health (VIX included/dropped, any call failure)
7. **Append audit line:** `correlation-snapshot target=correlations:<iso_week> universe=<n> regime=<tag> regime_shift=<yes|no>`.

## Hard rules
- Use only `financekit.correlation_matrix`. Do not compute correlations manually from `price_history` calls — that's redundant and slower.
- If the call fails, write a 1-line stub with the error and skip.
- Don't over-interpret correlation as causation. Tag it "regime context only" in the brief.
- 6-month window default. Don't switch to 1y or 2y unless the user asks.

## Out of scope
- Forward return forecasts or factor regression.
- Sector-level correlations (XLF/XLE/XLK etc.) — separate skill if needed later.
- International market correlations (EFA, EEM) — EEM only here.