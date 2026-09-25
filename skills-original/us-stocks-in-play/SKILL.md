---
name: US stocks in play
description: >-
  Weekday US (NYSE/NASDAQ/AMEX + liquid OTC + major ETFs) in-play scanner:
  post-open (~09:50 ET) and midday (~12:30 ET) digests. Uses
  TradingView-advanced + Yahoo Finance MCPs, falls back to Finviz/Barchart
  browser only on block. Tier A → Soft-A → TECH_WATCH → B → C, USD session
  $ volume sort. Quiet chat unless actionable. Cron weekdays 09:50 ET.
---

# US stocks in play

Scan US equities that are actionable right now (gaps, unusual volume, breakouts, material news, halts) — weekday post-open (~09:50) and midday (~12:30) America/New_York digests. Uses the shared `stocks-in-play-pipeline` skill for normalize→merge, Soft-A, TECH_WATCH, holiday skip, source-health table, and chat rules.

**Finviz Elite is optional.** Free Finviz (~1 minute delayed) is enough for digests. Barchart is never required paid.

## Shared pipeline

Always run `stocks-in-play-pipeline` **after** gathering sources and **before** writing the dated digest. That pipeline covers Soft-A tiering, holiday skip, source health table, overnight carry, fetch→browser fallback, and stricter chat rules.

## TradingView-advanced MCP rate-limit

When calling `mcp__tradingview-advanced__run_screener` / `get_symbol_data` / `get_news` / `get_symbol_data_batch`, follow pipeline §2b:

1. **One** US `run_screener` for core movers, OR HTML movers seed with **no** screener at all.
2. On HTTP 429 or empty screener: **STOP** further screener retries.
3. Quotes: **one** `get_symbol_data_batch` (≤50, `NASDAQ:`/`NYSE:`/`AMEX:` prefixed) on the merged candidate set → serial `get_symbol_data` only for batch `missing` (cap ≤10); prefer Yahoo/local confirm.
4. `get_news` only for top floor-cleared candidates (cap ~5–8); local catalysts first.
5. Soft target ≤12–15 TV MCP calls per slot. Log 429 once in Source health.

## Universe

**Include:**
- Common stock on NYSE, NASDAQ, AMEX / NYSE American
- OTC / pink sheets only when they clear a hard $ volume gate (e.g. FNMA, liquid cannabis)
- Major ETFs (SPY, QQQ, IWM, DIA, sector SPDRs, GLD, TLT, similar broad/sector/commodity/bond ETFs)

**Exclude:**
- Leveraged / inverse / single-stock leveraged ETFs (2x/3x, Ultra, Direxion, ProShares single-name levered)
- Warrants, rights, units (suffix / name heuristics: `W`, `WS`, `.W`, `U`)
- Preferreds
- Blank-check SPACs (pre-deal); post-deal operating cos OK if liquid
- Illiquid OTC that fails the $ volume gate

**Dedupe:**
- Dual-class: one line (more liquid class)
- Canadian interlisted: US line only
- ADRs: include if liquid; tag as ADR

## Noise filters

- Prefer session USD volume for ranking (not share count alone).
- Strip warrants/units from halt feeds.
- Low float (<10–20M): flag, don't auto-promote.
- Reverse-split artifacts: down-rank ~5–10 sessions.
- Dilution / ATM / registered direct: tag and down-rank long-bias chase.
- Premarket % with token volume: ignore until PM $ vol clears.

## Definition

A name is **in play** when there is a fresh, tradeable reason to look **now**: price/volume dislocation and/or material catalyst — not hype alone.

### Liquidity floor (required)

| Filter | Open ~09:50 ET | Midday ~12:30 ET |
|---|---|---|
| Price | ≥ $1 | ≥ $1 |
| Market cap | ≥ $50m soft | same |
| Session $ volume | ≥ ~$0.5–1m | ≥ ~$2–5m |
| OTC / pink | Session or PM $ vol ≥ ~$1–2m | same spirit |
| RVol | Not a hard gate at the open | Soft preference ≥ ~1.5–2× if available |

### Triggers (≥1 after the floor)

| Trigger | Guidance |
|---|---|
| Gap | ≥ ~3–5% vs prior close; for 09:50 prefer PM $ vol ≥ ~$200k when PM data exists |
| Day move | |chg%| ≥ 5% large/liquid; ≥ 8% smaller (soft 3–5% with strong tape OK) |
| Unusual volume | When RVol is available and meaningful — bonus, not a must |
| Breakout / breakdown | Day high/low vs prior range with volume |
| Catalyst | Material 8-K / PR / major news (see include/exclude) |
| Halt / resume | LULD or news halt — candidate on resume if liquid |
| Buyout / deal | Special rule below — not automatic in-play |

### Catalyst include

Earnings / guidance surprises; M&A / strategic review (non-arb); material contracts; FDA/regulatory when confirmed; officer/governance shocks; halt news; price-sensitive 8-K items (1.01, 2.01, 5.02, 7.01, 8.01).

### Catalyst exclude / down-rank

Routine admin; empty IR calendar; chat/Stocktwits as sole source; near-offer buyout arb; pure ATM/offering dumps without a tradeable bounce thesis.

### Buyout / near-offer rule

| Situation | Treatment |
|---|---|
| Trading near stated cash deal / tight collar | Exclude / down-rank — sideways arb, not chase |
| Fresh deal with wide gap to terms | Tier C gap/halt watch only — not Tier A / Soft-A / B momentum |
| Contested / raised bid with real non-arb tape | C, or B only if independent liquidity + move |

Never promote solely because a buyout was announced.

### Ranking and sort

1. Tier A → Soft-A → TECH_WATCH → B → C.
2. Within tier: USD session $ volume descending.
3. Cap ~8–10 names (+ short halt/gap annex). Tag ETF, OTC, ADR, DILUTION, BUYOUT_GAP, SOFT_A, halt reason when relevant.

## TECH_WATCH tier (technical Soft-B)

Between Soft-A and B. For liquid technical setups that fail a hard pure-technical RVol bar but clearly trade on size (continuation / episodic pivot, bottom bounce, HTF breakout, unusual strength without fresh catalyst).

**Eligibility (all required):**
- Liquidity floors for the slot
- Day-move or gap meets soft guidance
- Session turnover ≥ slot floor — prefer USD dollar volume
- Soft / missing RVol or roughly 1.0–2.0×
- No same-session catalyst required
- Tag `TECH_WATCH`

**Sort:** after Soft-A, before B, by session turnover descending.

**Chat:** include material TECH_WATCH on midday / manual when turnover clearly clears the midday-scale floor; on open, only if turnover already looks midday-scale.

## Persistence

Save every run to:

`C:\Users\admin\.minimax\projects\coding-shared\research\us-in-play\YYYY-MM-DD-<slot>.md`

- `<slot>` = `open` (~09:50), `midday` (~12:30), or `manual`
- Include: run time ET, session state, sort note, tier tables, PM gap annex (open slot), halt watch, source health table, sources
- When after-close / AH 8-K / PR material catalysts exist, require an `overnight_carry` section
- On open slot: load prior digest's `overnight_carry` into Overnight → open annex
- **Chat only if** any Tier A or Soft-A, material TECH_WATCH, or material Tier C

## Source stack

For each source: try HTTP fetch / API first; **if fetch blocked → open that URL only in the headed desktop browser**, scrape what you need, continue.

### Pass 1 — Movers (RTH)

1. **Yahoo** predefined JSON: `day_gainers`, `day_losers`, `most_actives`, `small_cap_gainers` (primary discovery).
2. **Finviz screener** (when HTML table renders): top gainers / losers / unusual volume / most active.
3. **TradingView-advanced MCP** — optional corroboration, under pipeline §2b budget.

### Pass 1b — Premarket / gap annex (especially 09:50)

1. **TheStockCatalyst** `https://www.thestockcatalyst.com/NYSEPMMovers` — primary PM annex.
2. **Barchart** `https://www.barchart.com/stocks/pre-market-trading` — WAF-blocked often; browser fallback.
3. **Perplexity Finance** — browser catalyst Q&A.

### Pass 2 — Confirm

Yahoo charts / Finviz quotes for last, % chg, volume → USD $ volume. OTC: confirm venue + $ vol gate.

### Pass 3 — Catalysts / halts

- SEC EDGAR 8-K Atom (descriptive User-Agent): items 1.01, 2.01, 5.02, 7.01, 8.01
- NASDAQ Trade Halt RSS + NYSE trading-halts page — strip warrants
- Finviz news + PR Newswire RSS — headline glue
- Apply buyout near-offer rule

### Pass 4 — Narrative (optional)

Perplexity Finance or major wires for large-cap colour only.

**Do not depend on:** MarketWatch (often blocked), CNBC movers URL, free Finviz CSV export (Elite), Benzinga Squawk, Unusual Whales as core, Barchart without browser, any paid Finviz Elite / paid Barchart RT as a gate.

## Timing emphasis

- **~09:50 ET (`open`):** post-open gaps that held, early tape, halt resumes; PM gap annex; pull prior `overnight_carry`.
- **~12:30 ET (`midday`):** continuation vs fade; raise $ volume bar; RVol soft preference; write `overnight_carry` for AH-relevant names.

RTH: 09:30–16:00 ET.

## When

- Cron: `50 9 * * 1-5` America/New_York (weekdays, 09:50 ET — open slot)
- Manual: user asks "what's in play today" or "run US stocks in play"
- For midday digest, run manually or as a separate cron (not added by default).

## Output

1. Write `C:\Users\admin\.minimax\projects\coding-shared\research\us-in-play\YYYY-MM-DD-<slot>.md`
2. Chat only if Tier A / Soft-A / material TECH_WATCH / material Tier C
3. Append `C:\Users\admin\.minimax\projects\coding-shared\research\logs\jobs.jsonl` per pipeline §7
4. Append audit log: `us-stocks-in-play target=us-in-play:<date>:<slot> tier_a=<n> soft_a=<n> tech_watch=<n> chat=<yes|no>`

## Anti-patterns

- Treating Finviz delay as "broken" or requiring Finviz Elite
- Requiring paid Barchart / paid RT for a routine digest
- Hard-requiring RVol at 09:50
- Forcing Soft-A merely because RVol is unavailable (vs known soft)
- Including levered / single-stock levered ETFs
- Including illiquid pinks without $ vol gate
- Treating every buyout as Tier A / Soft-A / B chase
- Burying high-catalyst known-soft-RVol names only in Tier B when Soft-A fits
- Ranking separate source lists without normalize→merge
- Chat-only delivery with a Source health **line** instead of a **table**
- Silent empty catalysts when Barchart / blocked wires need a browser
- Marking Finviz `blocked` on an empty HTTP 200 shell without a **headed** browser attempt
- Using headless Chrome/curl alone as the "browser" fallback for Finviz/Barchart
- Burning `get_symbol_data_batch` immediately after a US `run_screener` 429 instead of Yahoo confirms
- Retrying TradingView `run_screener` after HTTP 429
- Serial `get_symbol_data` for dozens of names when one batch (≤50) would cover them
- `get_news` on every mover instead of top floor-cleared candidates only
- Forgetting overnight carry on the morning open after a big AH 8-K print
- Scanning through a full NYSE/NASDAQ holiday without the pipeline skip
- Dropping liquid technicals (soft RVol, large turnover) with no TECH_WATCH home