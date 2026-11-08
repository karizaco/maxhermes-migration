---
name: Stocks in play pipeline (shared)
description: >-
  Shared normalize→merge→rank pipeline used by every regional stocks-in-play
  digest (US, ASX, Europe, Tokyo, Taiwan). Soft-A tiering, TECH_WATCH tier,
  holiday skip, fetch→browser fallback, TradingView MCP request budget,
  overnight carry, source-health table, chat-only-if-actionable rules.
---

# Stocks in play — shared pipeline

Use this whenever running any regional stocks-in-play digest (ASX, Tokyo, Europe, US, Taiwan). **TECH_WATCH** applies to ASX / US / Tokyo / Taiwan skills. Apply **after** the market-specific skill's universe/floors, and **before** writing the dated digest.

## 0) Exchange holiday skip (required first)

Before scanning, check whether the **target venue(s) for this slot** are closed for a full holiday.

| Market | Skip when | Early-close days |
|---|---|---|
| **US** | NYSE/NASDAQ closed | Still run (note early close) |
| **ASX** | ASX cash market closed | Still run (note early close) |
| **Tokyo** | JPX cash equities closed | Still run |
| **Europe `open`** | **LSE** closed | Still run |
| **Europe `midday`** | **Xetra** closed (primary continent tape) | Still run |
| **Taiwan** | **TWSE / TPEx** cash equities closed | Still run (note if any early close) |

On a full holiday skip:
1. Write a short file `C:\Users\admin\.minimax\projects\coding-shared\research\<market>-in-play\YYYY-MM-DD-<slot>.md` noting **holiday — skipped**.
2. **Do not chat** (unless the user manually asked for a test).
3. Stop — no movers scrape.

### 2026 full-closure dates (verify yearly; subject to exchange updates)

**NYSE/NASDAQ:** 2026-01-01, 01-19, 02-16, 04-03, 05-25, 06-19, 07-03, 09-07, 11-26, 12-25. Early: 11-27, 12-24 (~13:00 ET).

**ASX:** 2026-01-01, 01-26, 04-03, 04-06, 04-25 (Sat), 06-08, 12-25, 12-28. Early: 12-24, 12-31.

**JPX:** 2026-01-01..01-03, 01-12, 02-11, 02-23, 03-20, 04-29, 05-03..05-06, 07-20, 08-11, 09-21..09-23, 10-12, 11-03, 11-23, 12-31.

**LSE (Europe open):** 2026-01-01, 04-03, 04-06, 05-04, 05-25, 08-31, 12-25, 12-28. Early: 12-24, 12-31 (~12:30 London).

**Xetra / DE (Europe midday):** treat German public holidays that close Xetra as skip for `midday` (incl. Good Friday / Easter Monday / Christmas / New Year aligned with DE; also Labour Day 05-01 when Xetra closed).

**TWSE / TPEx (Taiwan):** 2026-01-01; 02-12..02-20 (Lunar New Year cluster); 02-27; 04-03..04-06; 05-01; 06-19; 09-25; 09-28; 10-09..10-10; 10-25..10-26; 12-25.

Also skip weekends for all. Re-check official calendars each January.

## 1) Normalize → merge → rank (required)

Every source has a different shape. **Never** publish separate per-site lists as the digest.

### Common candidate row

```
ticker, venue, instrument_type, last, chg_pct, dollar_vol, rvol,
catalyst, catalyst_time, flags, source, asof, tier
```

`flags` examples: `LIMIT_UP`, `TOB_GAP`, `BUYOUT_NEAR`, `DILUTION`, `HALT`, `ADR`, `ETF`, `SOFT_A`, `TECH_WATCH`.

### Steps

1. Ingest → 2. Dedupe → 3. Classify (market skill) → 4. Attach catalysts → 5. Floors + special rules → 6. **Tier** → 7. Sort by market dollar-vol desc → 8. Emit one digest + annexes.

### Tiers (including Soft-A)

| Tier | Meaning |
|---|---|
| **A** | Liquidity floors + elevated RVol + material same-session catalyst |
| **Soft-A** | Liquidity floors + high-material same-session catalyst + soft / missing RVol. Tag `SOFT_A`. Sort after hard A, before TECH_WATCH, by dollar-vol within Soft-A. |
| **TECH_WATCH** | Liquidity floors + day-move/gap soft trigger + strong absolute turnover, soft RVol (~1–2×) and no same-session catalyst. Tag `TECH_WATCH`. Sort after Soft-A, before B. Used on ASX / US / Tokyo / Taiwan (not Europe). |
| **B** | Liquidity + move / unusual volume; no (or weak) same-session PS |
| **C** | Halt / stop / SQ / fresh wide-spread deal / overnight gap watch |

Markets that **omit RVol as a hard gate** (e.g. US open): treat strong catalyst + liquidity as **A** (not Soft-A) when RVol is simply unavailable; use Soft-A when RVol is **known soft** but catalyst is high.

## 2) Fetch-fail → headed browser fallback

**Order:** prefer **TradingView MCP + HTTP** first. Headed browser only for a **blocked / empty-shell** URL. **Do not** browser-retry (or open headed browser) when HTTP already returned usable content for that URL.

1. Try HTTP fetch / API (and TradingView MCP where the market skill says).
2. On 403 / 409 / 422 / CF / WAF / empty shell / tiny JS-only shell / CAPTCHA → headed browser for **that URL only**.
3. Empty or tiny JS shells count as fail — browser is **required** before marking `blocked`.
4. Never block the whole digest on one source — record in Source health.
5. Known-fragile sources still get HTTP first; escalate to headed browser only when that HTTP attempt is blocked or empty.

## 2b) TradingView MCP request budget (shared)

Working budget: ~20 MCP calls/min, ~200/hour. Every `run_screener`, `get_symbol_data`, `get_symbol_data_batch`, `get_news`, `get_ohlcv`, `search_symbols` counts as **one** call.

### Merge first (required)

| Need | Do this | Not this |
|---|---|---|
| Movers discovery | **One** `run_screener` for the slot's **primary** market *or* HTML movers seed (no MCP). | Per-country screener storm |
| Quotes / RVol / turnover | **One** `get_symbol_data_batch` (≤50 symbols, `EXCHANGE:TICKER`, deduped) | Serial `get_symbol_data` for each ticker |
| Catalysts from TV | `get_news` only for **top floor-cleared** candidates (cap ~5–8); prefer local RNS/OAM/8-K/TDnet/MOPS first | `get_news` on every mover |
| Screener empty / 429 | Stop screener; HTML ticker seed → **one** batch quote call | Retry screener or fan out per-symbol quotes |

### Slot budget (soft targets)

Aim for ≤12–15 TradingView MCP calls per SIP digest slot:
1. 0–1× `run_screener` (primary market only).
2. 1× `get_symbol_data_batch` for the merged candidate set.
3. 0–8× `get_news` (tier A/Soft-A / material C candidates only).
4. 0–N× `get_symbol_data` only for symbols missing from batch — cap ≤10 serial.

### On HTTP 429

1. **STOP** all further `run_screener`.
2. Do not retry the failing tool in a tight loop.
3. Continue digest: HTML movers + batch/quotes already in hand + local catalysts.
4. Log once in Source health. Remaining calls may still be tried sparingly if 429 was screener-only.

## 3) After-close → next-open annex

- Midday/manual/EOD: after-close / AH / PTS high-material → Tier C + **`overnight_carry`**.
- Next `open`: load prior `overnight_carry` into Overnight → open annex; re-check; promote only if floors + tape clear.
- TOB/buyout near-offer rules still win (no chase).

## 4) Source health (required table)

Every digest file **must** include:

```markdown
## Source health
| Source | Status | Notes |
|---|---|---|
| … | ok / blocked / browser / skipped | e.g. HTTP 403, WAF, empty table |
```

Status values: `ok` | `blocked` | `browser` | `skipped`. One row per attempted source.

## 5) Chat vs file (stricter)

**Always** write the dated digest file (including holiday skips and empty runs).

**Chat only when actionable:**
- Any Tier A or Soft-A name, **or**
- Material TECH_WATCH (midday/manual when turnover clears midday-scale floor; open only if already midday-scale), **or**
- Material Tier C gap/halt watch (fresh wide-spread deal, LIMIT_UP/DOWN with size, halt resume risk, overnight_carry that still matters)

Otherwise: **quiet in chat** (no "nothing in play" filler).

Manual user-requested test runs may always chat a short summary even if empty.

### Chat summary format (one ticker per line)

When the chat summary is warranted, format the ticker list as **one ticker per line**, not prose lines that combine multiple names.

- Lead with **one context line**: slot, time (ET), broad market tone (e.g. `US stocks in play — 2026-09-21 open slot · 09:56 ET · SPX +0.70% · NDX +1.18% · BTC +5.44%`).
- Use concise tier headers on their own line (`Tier A:`, `Tier B:`, `Tier C:`).
- Each ticker on its own bullet line: `- TICKER +x.xx% — why-in-play / catalyst / theme` (e.g. `- MSTR +7.81% — BTC proxy; BTC +5.44% on the tape`). Append `⚠ low-float`, `⚠ gap watch`, `⚠ halt`, `⚠ SOFT_A`, `⚠ TECH_WATCH` inline when relevant.
- **Default to the why, not the price.** Skip the `@ $price` column unless the price level materially adds context (key technical level, earnings reaction print, halt reference). For routine sector-strength or theme-driven moves, the catalyst is what makes the name actionable.
- **Reserve `⚠ low-float` for evidence-based calls.** Only flag when shares-outstanding data shows <10–20M shares outstanding. A real catalyst-driven move in a small-cap (REE theme, AI silicon, FDA, halt-resume) is NOT a low-float tag — that's the catalyst doing the work.
- Close with the audit line: `Audit: tier_a=N soft_a=N tech_watch=N chat=yes|no`.
- Do **not** combine multiple tickers on one prose line (e.g. `ARM +9% · MSTR +8% · RKLB +8% ...`); that is paragraph-shaped and not bullet-shaped.
- Digests and source-health tables still go in the dated markdown file; chat is the bullet list.

## 6) Realtime data (optional polish)

- **Finviz free (~1 min delay)** is enough for digests — do **not** require Finviz Elite.
- **Barchart** / other RT feeds: use when available (often browser); never block the digest on paid RT.

## 7) Fuel log (required after every digest run)

Before ending the run, append **one** JSONL line to `C:\Users\admin\.minimax\projects\coding-shared\research\logs\jobs.jsonl` (create parent dirs if needed). Do not start a new turn just to log; do not message other agents about it.

```json
{"ts_bkk":"YYYY-MM-DDTHH:MM:SS+07:00","agent":"mavis","kind":"routine","name":"<market> stocks in play <slot>","class":"L","notes":"optional"}
```

Use Asia/Bangkok timestamp. `class` is usually **L** for these digests; **M** only if it was a short file-only holiday stub. `kind` is `routine` for scheduled fires, `manual` for user-requested re-runs.

## Anti-patterns

- Ranking per-site lists without merge
- Silent empty catalysts / OAM when a browser would unblock
- Browser-retrying or browser-first when HTTP already returned usable content for that URL
- Retrying TradingView `run_screener` after HTTP 429
- Fan-out `run_screener` once per country (Europe multi-market)
- Serial `get_symbol_data` for dozens of names when batch would cover them
- `get_news` on every HTML mover instead of top floor-cleared candidates
- Forgetting overnight carry after a big AH print
- Chatting empty holiday / empty-tape noise
- Requiring Elite/paid RT for a routine digest
- Burying high-catalyst soft-RVol names only in Tier B when Soft-A fits