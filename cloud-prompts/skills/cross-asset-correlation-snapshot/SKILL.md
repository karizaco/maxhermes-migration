---
name: Cross-asset correlation snapshot
description: >-
  Weekly correlation matrix of the major asset proxies: SPY, QQQ, IWM, TLT,
  GLD, DXY (via UUP), VIX (when available), EEM. Used to spot regime shifts
  (risk-on/off, growth-value, commodity-Dollar coupling) that inform sector
  positioning for the week. Runs 10:00 ET on weekdays, intraday.
  the weekly brief. On Cloud the matrix is computed SERVER-SIDE by DuckDB
  `corr()` over the MCP bridge — see "Cloud adaptation" below.
---

# Cross-asset correlation — weekly snapshot

Single-purpose: produce a Pearson correlation matrix across the core asset proxies so the weekly brief can spot regime changes (stocks-bond decoupling, growth-value rotation, USD-gold rotation) and frame the week ahead.

## When
- Cron: `0 10 * * 1-5` America/New_York (weekdays, 10:00 ET — intraday, one hour after the US open)
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
   **On Cloud this tool does not exist — see "Cloud adaptation" below and use the server-side
   `corr()` call there instead.** The INTENT of this step — one batched call that computes the
   whole matrix — is preserved by the Cloud path.
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

## Cloud adaptation (agent.minimax.io) — READ THIS ON CLOUD

`mcp__financekit__correlation_matrix` is **not bound in Cloud sessions**, and neither is any
`mcp__*` tool. There is no financekit MCP *server* either — the only reachable MCP servers are
`stocktwits` and `shibui` (verified 2026-10-28). So step 2's hard rule cannot be satisfied
as literally written.

**But the rule's intent can be satisfied exactly: compute the matrix SERVER-SIDE, in one call.**

`shibui.stock_data_query` runs DuckDB SQL server-side, and DuckDB's `corr()` aggregate computes
the entire matrix in a single round trip. This is the closest available equivalent of
`correlation_matrix`, and it is what the helper script does.

### Use the helper script — it is the primary path

```bash
BR=/workspace/mcp_bridge.py
for U in \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/mcp_bridge.py" \
  "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/mcp_bridge.py" \
  "https://api.github.com/repos/karizaco/maxhermes-migration/contents/cloud-prompts/_shared/mcp_bridge.py?ref=main" ; do
  [ -s "$BR" ] || curl -sL -H "Accept: application/vnd.github.raw" -o "$BR" "$U" 2>/dev/null
done
[ -s "$BR" ] || echo "bridge fetch FAILED - fall back to web_search, then the curl ladder"

SKILL=https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/skills/cross-asset-correlation-snapshot/scripts
curl -s -o /workspace/correlation_matrix.py "$SKILL/correlation_matrix.py"

# window-end = the last COMPLETED session (see "partial session" rule below)
python3 /workspace/correlation_matrix.py \
  --symbols 'SPY,QQQ,IWM,TLT,GLD,UUP,EEM,^VIX' \
  --window-start <YYYY-MM-DD> --window-end <YYYY-MM-DD> \
  --basis adjclose --cross-check \
  --out /workspace/data_cross/mats.json
```

Add `--rolled-end <YYYY-MM-DD>` for a week-rolled comparison window.
The helper prints a JSON summary and writes `mats.json` with
`matrix_returns`, `window`, `sources`, and (with `--cross-check`) `crosscheck_shibui_raw`.

**Price source:** Yahoo Finance Chart API `/v8/finance/chart/{sym}?range=1y&interval=1d`, short
`User-Agent: Mozilla/5.0` (a long Chrome UA is 429'd by Yahoo's edge). The aligned series are
injected into the SQL as inline VALUES and DuckDB computes the matrix server-side.
**shibui's own `stock_quotes` table is an independent cross-check, never the primary source.**

### What the helper enforces (measured constraints, not folklore)

- **shibui's tool caps result rows at 200.** An AGGREGATE query returns one row, so the matrix
  call is unaffected. Never pull raw series for 8 symbols out of it (889 rows -> tool error);
  pull per-ticker (127 rows each) or aggregate in SQL.
- **^VIX is NOT in shibui** — `general_info` has no index rows and no ticker matches `%VIX%`.
  VIX comes from Yahoo and is injected alongside the ETF series.
- **Returns must span consecutive COMMON dates.** VIX carries sessions the ETFs lack
  (2026-05-25, 2026-09-07). Compute the common date set FIRST, then take `lag()` over it.
  Otherwise VIX returns span a different interval and VIX correlations drift by ~0.002.
- **`^VIX` is not a valid SQL identifier** — the helper maps it to `VIX`.

### Adjustment basis — state it, never leave it implicit

`--basis adjclose` (default) uses Yahoo's split/dividend-adjusted closes; `--basis close` uses
raw closes. They differ materially for distributing ETFs (SPY–TLT was +0.33 on adjclose vs +0.32
on raw close over the same 6-month window), because a raw ex-dividend drop is a price move but
not a total loss. **Publish the basis in the artifact** and keep it consistent with the prior
snapshot when computing a week-over-week delta.

### Partial session rule (this cron fires intraday)

The deployed cron fires at 10:00 ET, so the current session is usually **in progress**. A
partial bar is not a close. Use the last COMPLETED session as `window-end` and report the
excluded date. If the partial bar's effect is quantified, say so.

### Fallback chain (if the bridge is unavailable)

`shibui` server-side matrix -> local Pearson on Yahoo closes -> `web_search` per symbol.
**Record which path produced the published matrix in Source health.** Do not silently ship a
locally-computed matrix while implying the server-side one was used.

## Hard rules
- Use only `financekit.correlation_matrix`. Do not compute correlations manually from `price_history` calls — that's redundant and slower.
  **On Cloud:** the equivalent is the server-side DuckDB `corr()` call via the MCP bridge
  (see "Cloud adaptation"). A local Pearson computed in the agent IS the manual computation the
  rule forbids — it is a fallback, and the artifact must say so.
- If the call fails, write a 1-line stub with the error and skip.
- Don't over-interpret correlation as causation. Tag it "regime context only" in the brief.
- 6-month window default. Don't switch to 1y or 2y unless the user asks.

## Out of scope
- Forward return forecasts or factor regression.
- Sector-level correlations (XLF/XLE/XLK etc.) — separate skill if needed later.
- International market correlations (EFA, EEM) — EEM only here.