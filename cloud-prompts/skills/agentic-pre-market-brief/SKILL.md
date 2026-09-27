---
name: Agentic pre-market brief
description: >-
  Generate the daily pre-market research brief. Watches the *entire*
  US equity market — watchlist is one section, not the spine. Theme-
  clusters the day's action. Replaces the paused `agentic-research-
  brief-paused` Grok routine. Uses MCPs (no per-call cost), writes to
  the local research vault. Runs on cron at 07:37 ET weekdays.
---

# Agentic pre-market brief (market-wide, theme-clustered)

> **Scope rule (load-bearing).** The pre-market brief watches the
> *entire* US-listed public equity universe. The user-supplied watchlist
> is a personal tracker and appears as a **section** of the brief, never
> as the spine. StockTwits trending + a market-wide %change screen drive
> what gets written; the watchlist is read *after* the clustering, in
> parallel. Missing the day's actual tape (last revision: missed the
> Greenland/rare-earth complex because we scoped to the watchlist) is a
> hard failure mode — see "Failure modes" below.

## When

- Cron: `37 7 * * 1-5` America/New_York (weekdays, 07:37 ET).
- Manual: user asks "give me today's pre-market brief" / "run the pre-market brief".

## Output

- `C:\Users\admin\.minimax\projects\coding-shared\research\briefs\YYYY-MM-DD-pre_market.md`
- Compact ≤ 60-line chat summary on top of the markdown.
- Audit log line on `research\logs\audit.log`: `action=brief_rendered target=pre_market:<date>`.

## Steps (market-wide → cluster → watchlist, NOT watchlist-first)

### Step 1 — StockTwits trending (LEAD indicator, not sidebar)

Call `mcp__stocktwits__trending_symbols` with `limit=15`. **Each row is a price-check trigger, not a footnote.** For every ticker in the trending list that is NOT on the watchlist (and especially those with a one-paragraph "trends.summary" thesis text), fetch a price + pre-market gap immediately:

  ```
  mcp__tradingview__lookup_symbols (resolve once)
  mcp__tradingview-advanced__stock_extended_hours (per ticker)
  mcp__tradingview-advanced__stock_prices (batched, exchange-prefixed)
  ```

Already on the watchlist? Skip the price fetch and reuse the Step 6 quote, but **quote the trending list at the top of the TL;DR**.

### Step 2 — Market-wide gap-up screen (PRIMARY data source)

`mcp__tradingview__screen_stocks`:

  ```
  filters=[change > 3%, typespecs has common, volume > 500000]
  markets=[america]
  sort_by=change, sort_order=desc
  limit=25
  ```

Same tool with `change < -3%` sorted asc, limit=25, for the gap-down side. **These 50 names are the day's actual tape** — well above the 12-name watchlist in signal-to-noise for "what is happening this morning."

### Step 3 — Halts / halts-broken / unusual volume

Run an additional `mcp__tradingview__screen_stocks` with `volume > 50_000_000` and `change > 0` (or absolute) sorted by `(volume × |change|)` to surface the day's genuine outsized activity (squeeze candidates, halted/resumed names, M&A spike).

### Step 4 — Cluster by catalyst (the load-bearing step)

Before writing any prose, **group every gap name from steps 1–3 by catalyst**. One pass. Examples of clusters:

  - *Trump-X Greenland / rare-earths* (CRML, GRML, GLND, USDE, NUAI, …)
  - *AI custom silicon* (AVGO, MRVL, AMD, NVDA, META, GOOGL, AMZN, …)
  - *Crypto-leg equities* (MSTR, COIN, RIOT, CLSK, …)
  - *Single-name idiosyncratic* (each isolated move flagged by StockTwits thesis)

Write the cluster list down before composing prose — don't discover the clusters while writing.

### Step 5 — For each cluster, fetch anchor + verify

For each cluster:
  - Identify the **cluster leader** (highest change% and/or highest volume).
  - Pull `mcp__yahoo-finance__get_market_news` for the leader and 1–2 corroborators.
  - `web_search "<<theme>> <YYYY-MM-DD>"` for the news anchor (e.g. "Trump Greenland rare earth September 21 2026"). One search per cluster, max 5 clusters total.
  - If the theme is a single StockTwits thesis with no corroboration: label it "single-name idiosyncratic" and skip the news pull.

### Step 6 — Overnight context (parallel)

Run these in one assistant turn:

  - `mcp__tradingview-advanced__market_snapshot` (indices, crypto, FX, ETFs)
  - `mcp__yahoo-finance__get_market_status` (region=US, for cash-open countdown)
  - `mcp__tradingview-advanced__futures_category_snapshot` (category=equity_index, for ES/NQ/YM/RTY front-month)
  - **Fallback if futures query returns <4 contracts:** read the cash index levels from `market_snapshot` and surface that the front-month futures look-up failed. **Do not chain to web_search on individual futures tickers** — that's not what the playbook says and burns calls.

### Step 7 — Watchlist section (parallel to steps 1–6, NOT the spine)

Read `C:\Users\admin\.minimax\projects\coding-shared\research\watchlist.yaml`. **In parallel** with steps 1–5, batch-pull quotes:

  - `mcp__yahoo-finance__get_stock_quote` per ticker (12 names → 12 calls, fine; do not slow us down).
  - `mcp__tradingview-advanced__stock_extended_hours` per ticker for pre-market gap.
  - **Compute pre-market % vs Friday close explicitly** (the MCP's `change_vs_previous_close_pct` is vs *Thursday* close — do not use it directly; show vs Friday close).

The watchlist section is one bucket in the brief, ranked by absolute pre-market move. Skip news for any watchlist ticker that is not also in the day's themes (a watchlist name outside the themes gets a one-line "flat, no theme today" and that's it).

If the watchlist file is missing, **do not create a default and proceed** — write the brief without a watchlist section and surface the missing-file line in `Source health`.

### Step 8 — Earnings + Macro calendar

  - **Earnings:** `mcp__yahoo-finance__get_market_news` search-by-ticker for any watchlist name reporting today + watchlist file says "earnings flag"; otherwise a hardcoded mega-cap earnings list. **Don't scan every watchlist name** — earnings is a sub-section, not the spine.
  - **Macro:** web_search `economic calendar <YYYY-MM-DD> FRED` or read `research\macro-calendar\YYYY-Wnn-week.md` if it exists in this week's folder. One search, ≤ 3 lines summary.

### Step 9 — Write the brief

Order (load-bearing — do NOT re-order):

  1. **TL;DR** — clustered, theme-first. ≥ 4 named themes from Step 4 with their tickers and magnitudes in bullet form. Single-sentence "watchlist" line at the bottom that says which watchlist names happen to align with the day's themes.
  2. **Theme clusters** — one section per cluster with anchors, leader, corroborators, magnitudes, news URL.
  3. **Pre-market gaps — top 25 market-wide** — table from Step 2 / Step 3.
  4. **Top losers — top 10 market-wide** — table.
  5. **StockTwits lead read** — trending list with thesis text shown inline, not buried.
  6. **Watchlist** — quote + pre-market gap, sorted.
  7. **Overnight / futures / index / crypto** — compact block.
  8. **Macro calendar** — ≤ 5 lines.
  9. **Earnings today** — only if anything material.
  10. **Source health** — every MCP that succeeded/failed.
  11. **Open research queue** — ≤ 5 carry-forwards.

Cap top news to **10 items**, **all theme-anchored** (no per-ticker news for non-theme watchlist names).

### Step 10 — Audit + chat summary

- Append: `2026-MM-DDTHH:MM:SSZ action=brief_rendered target=pre_market:<date> session=me sources=<csv> model=… skill=agentic-pre-market-brief themes=<count>` to `research\logs\audit.log`.
- Return a compact ≤ 60-line chat summary, **theme-first**. Do NOT paste the full markdown.

## Failure modes (these are real, learned from prior runs)

| Failure | Why it happened | Required fix |
|---|---|---|
| **Watchlist-only scoping** | SKILL v1 made the watchlist the spine. Step 4 said "screener for gap-ups" but it was an OR with web_search, easy to skip. | Steps 1–3 are now mandatory and run *before* the watchlist. |
| **StockTwits trending → footnote** | Treated as a "social mood" sidebar. Result: CRML #3 trending was quoted without a price. | Step 1: each trending row is a price-check trigger. |
| **No theme clustering** | Watchlist sections (Top-down by ticker) actively discouraged clustering. | Step 4 is mandatory. Clusters appear above the watchlist in the brief. |
| **Fallback loops** | When a tier-2 source returned 0, agent chained to a tier-3 (e.g. per-ticker yahoo) and burned tokens. | See "Fallback discipline" below. |

## Fallback discipline (required on every step)

Every fallback tier ends with **"accept those rows as-is, write `_source=<fallback>`, and stop"**. Examples:

  - Step 2 screener HTTP 429 → fall back to `mcp__tradingview-advanced__top_gainers(exchange=NASDAQ)` for the same filter. Accept those 25 rows with `_source=tv_top_gainers` and **stop**.
  - Step 5 news search returns 0 → write the cluster with the StockTwits thesis text only. Mark "no corroborating news". **Stop.**
  - Step 6 futures category snapshot returns < 4 contracts → use `market_snapshot` indices only and note that front-month futures are missing. **Stop.**
  - Step 8 macro search returns 0 → write "no macro releases today" and move on. **Stop.**

Do NOT chain a third MCP after a fallback. The Playbook's day-window has its own time cost.

## Hard rules

- Never place trades. Read-only by design.
- Use only MCPs and `web_search`/`web_fetch`. No browser automation, no new network endpoints without user approval.
- **Citation required:** every cluster leader has ≥ 1 source (URL or file path).
- If the brief is short of themes (≤ 2), surface "thin tape" in the TL;DR — do not pad.
- If MCP `financial_news` (`MARKETAUX_API_TOKEN not configured`) fails, fall back to `yahoo-finance get_market_news` + `web_search` and note in `Source health`.

## Out of scope

- Do not run the old `python agentic.py` CLI.
- Do not generate post-market or weekly briefs from this skill (their own files live alongside this one).
- Do not extend the user's watchlist unilaterally — surface missing-file lines and move on.
