---
name: Unusual options flow daily
description: >-
  Daily scan of unusual options activity on watchlist + mega-cap tickers using
  TradingView-advanced `stock_options_unusual_activity`. Surfaces strikes where
  today's volume exceeds open interest (V/OI > 1) — classic institutional
  positioning signal. Runs weekdays 09:55 ET, just after the open.
---

# Unusual options flow — daily

Lightweight daily scan: where is the smart money positioning today on options? Built on `mcp__tradingview-advanced__stock_options_unusual_activity`, no LLM cost.

## When
- Cron: `55 9 * * 1-5` America/New_York (weekdays, 09:55 ET — ~25 min after open so vol settles)
- Manual: user asks "any unusual options activity today?" or "show me NVDA options flow"

## Output
- `C:\Users\admin\.minimax\projects\coding-shared\research\options-flow\YYYY-MM-DD.md`
- Compact ≤ 15-line summary in chat reply (top 5 only).

## Universe
Two passes:

**Pass A — Watchlist core**
Read `C:\Users\admin\.minimax\projects\coding-shared\research\watchlist.yaml` (top-level `tickers:` list). Call `stock_options_unusual_activity` per ticker (cap 30 — split if larger watchlist).

**Pass B — Mega-cap sweep (optional, weekdays only)**
IWM, GLD, TLT, plus the top 5 S&P 500 names by market cap (AAPL, MSFT, NVDA, GOOGL, AMZN as of 2026 — refresh quarterly). Capped at 12 total to stay inside minute budget.

**Exclusion list (do NOT scan — see Hard rules)**
- Broad-index mega-cap ETFs: SPY, QQQ (their chains are dominated by dealer-gamma and 0DTE market-maker hedging; V/OI gets inflated and the daily put/call bias tag becomes "PUT" on every red day for structural reasons, not positioning).
- Levered / thematic ETFs: SOXL, SOXS, SMH, TQQQ, SQQQ, UVXY, VXX. Same structural-noise problem, plus single-stock levered ETFs already violate the existing "no naked single-stock levered ETFs" rule.
- If a manual run wants to include any of these anyway, pass `--include-noisy-etfs` flag and tag every row `_source=noisy_etf_override` so the bias calculation can optionally exclude them after the fact.

## Call budget (soft targets)
- ≤ 42 underlying calls per run (30 watchlist + 12 mega-cap).
- Each call returns up to 10 strikes → ≤ 420 rows in raw output. Down-rank in `Steps 3`.
- If `tradingview-advanced` returns HTTP 429: log under Source health, skip the rest, write the partial file.

## Steps

1. **Read watchlist.** Parse `research/watchlist.yaml` → `tickers: [...]`. Cap at 30.
2. **Build mega-cap list.** Hardcoded 11 names (above). Pulled from `mcp__financekit__stock_quote` for mcap validation if available; otherwise trust the hardcode.
3. **Call per underlying.** `mcp__tradingview-advanced__stock_options_unusual_activity(symbol, top_n=10, min_volume=100, expiries=4)` for each. Concurrency: serial, ~3 calls/sec.
4. **Aggregate per-ticker** into rows:
   - ticker, underlying_price, side (call|put), strike, expiry, volume, open_interest, v_oi_ratio, last_price, iv, in_the_money, moneyness_pct, expires_in_days
5. **Rank** by V/OI descending across all underlyings. Keep top 25.
6. **Filter:**
   - drop `v_oi_ratio < 1.0`
   - drop `volume < 200`
   - keep `expiries_within_days <= 60` (short-dated institutional bias)
7. **Bias call:** sum call_volume vs put_volume across the kept set. Compute put/call volume ratio. Tag overall bias.
8. **Write markdown** with sections:
   1. Top 10 strikes table (ticker, side, strike, expiry, vol, OI, V/OI, IV, moneyness)
   2. Per-ticker notable (top 2 per ticker)
   3. Bias summary (calls vs puts, put/call ratio, theme if obvious)
   4. Source health (call counts, 429s)
9. **Append audit line:** `unusual-options-flow target=options-flow:<date> underlyings=<n> strikes_kept=<n> bias=<call|put|mixed>`.

## Hard rules
- Read-only. Never suggest a trade or sizing.
- If watchlist.yaml is missing, fall back to Pass B only.
- Cap mega-cap list at 12 names to keep cron runtime < 90s.
- Never include naked single-stock levered ETFs (same as `us-stocks-in-play` exclusion).
- **Never include mega-cap index ETFs or high-volume levered ETFs in Pass B** (SPY, QQQ, SOXL, SOXS, SMH, TQQQ, SQQQ, UVXY, VXX). Their option chains are dominated by dealer-gamma and 0DTE market-maker hedging, which inflates V/OI ratios artificially and biases the daily put/call tag toward "PUT" on every red day for structural reasons. Surface single-name positioning instead. IWM/GLD/TLT are kept — their directional signal is more interpretable.
- V/OI > 1 is the headline metric; everything else is context.

## Out of scope
- Backtesting options strategies.
- Greeks (delta/gamma) — not exposed by the TradingView-advanced MCP today.
- Earnings-specific plays — that's `earnings-reaction-scanner`.