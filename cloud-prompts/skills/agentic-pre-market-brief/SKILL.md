---
name: Agentic pre-market brief
description: >-
  Generate the daily pre-market research brief. Watches the *entire*
  US equity market — watchlist is one section, not the spine. Theme-
  clusters the day's action. Replaces the paused `agentic-research-
  brief-paused` Grok routine. Uses MCPs (no per-call cost), writes to the
  local research vault. Runs on cron at 08:30 ET weekdays.
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

- Cron: `30 8 * * 1-5` America/New_York (weekdays, 08:30 ET — 60 min before the US open).
- Manual: user asks "give me today's pre-market brief" / "run the pre-market brief".

## Tool mapping (Cloud runtime) — read once, do not re-probe

The `mcp__*` tool names below are **provenance from the local Windows Mavis and do not exist in
this runtime**. Do not call them and do not spend turns proving they are absent.

| What this skill calls | What actually works here |
|---|---|
| `mcp__stocktwits__trending_symbols` | MCP-over-HTTP bridge → `stocktwits trending_symbols` (args as a FILE) |
| `mcp__tradingview__screen_stocks` | `POST https://scanner.tradingview.com/america/scan` (see Step 2) |
| `mcp__tradingview-advanced__*` | the same `america` scanner, different columns |
| `mcp__yahoo-finance__*` | the bridge → `market-recap get_quotes` / `market_snapshot` / `top_movers` |
| `mcp__financial_news` | `web_search` + `web_fetch` |

The bridge (`cloud-prompts/_shared/mcp_bridge.py`) is the primary quote source; the TradingView
scanner is the primary screener. Full ladder and fallback rules: `cloud-prompts/_shared/PROMPT-BLOCKS.md`.

## Output

- `C:\Users\admin\.minimax\projects\coding-shared\research\briefs\YYYY-MM-DD-pre_market.md`
  _(In Cloud this path does not exist — it is the local Mavis host's location. In Cloud, write to the `## OUTPUT` path in the cron prompt.)_
- A machine-readable companion `YYYY-MM-DD-pre_market.csv` ships **alongside** the markdown:
  one row per name seen in the pre-market screens, columns
  `ticker,name,premarket_change_pct,premarket_close,prev_close,prev_change_pct,premarket_volume,avg_volume_30d,pct_of_adv,market_cap,sector,exchange,liquid_screen,quality_screen,has_news`.
  It is the same screen the tables are built from, so it must never contradict them.
- Compact ≤ 60-line chat summary on top of the markdown.
- Audit log line on `research\logs\audit.log`: `action=brief_rendered target=pre_market:<date>`.

## Steps (market-wide → cluster → watchlist, NOT watchlist-first)

### Step 1 — StockTwits trending (LEAD indicator, not sidebar)

Fetch via the MCP-over-HTTP bridge (args as a FILE, never inline):

```bash
printf '%s' '{"limit":15}' > /workspace/_mcp/st.json
python3 /workspace/mcp_bridge.py stocktwits trending_symbols /workspace/_mcp/st.json
```

**Each row is a price-check trigger, not a footnote.** For every ticker in the trending list that is
NOT on the watchlist (and especially those with a one-paragraph "trends.summary" thesis text), fetch a
price + pre-market gap immediately from the Step 2 scanner.

Already on the watchlist? Skip the price fetch and reuse the Step 6 quote, but **quote the trending list at the top of the TL;DR**.

### Step 2 — Market-wide pre-market screen (PRIMARY data source)

**Endpoint** (the `mcp__*` tool name in the original spec does not exist here):

```
POST https://scanner.tradingview.com/america/scan
Content-Type: application/json
User-Agent: Mozilla/5.0
Origin: https://www.tradingview.com
```

**COLUMN CONTRACT — read this before writing anything.** The screener serves TWO different sessions:

| Column | What it is | Use it for |
|---|---|---|
| `close` | the **last completed regular session** close (yesterday) | the denominator of the pre-market gap |
| `change` | that **same regular session's** % move vs the prior session | "yesterday's tape" context tables |
| `change_abs` | that session's absolute move | sanity check |
| `premarket_close` | the **live pre-market print** | the price you publish |
| `premarket_change` | the live pre-market % vs `close` | **the gap you publish** |
| `premarket_volume` | running pre-market share counter | the liquidity gate |
| `average_volume_30d` | 30-day average daily volume | `%ADV` = `premarket_volume / average_volume_30d` |
| `halted` | halt flag | the halts table |

> **Never label a `change` figure a pre-market gap.** They are different sessions and a brief that
> mixes them is wrong in a way that reads as plausible. If a section is titled "pre-market", every
> number in it comes from `premarket_*`. If a section is titled "yesterday's tape", every number
> comes from `change`/`close`.
>
> `change` is in **percent units**, not a fraction. Verify once per run with the identity
> `close - close/(1 + change/100) == change_abs` before publishing any of it.

**Gainers screen** (the day's actual tape — well above the watchlist in signal-to-noise):

```json
{"filter": [
   {"left":"type","operation":"in_range","right":["stock","dr"]},
   {"left":"exchange","operation":"in_range","right":["NASDAQ","NYSE","AMEX"]},
   {"left":"premarket_change","operation":"in_range","right":[3,1000]},
   {"left":"premarket_volume","operation":"greater","right":0}],
 "options":{"lang":"en"},"markets":["america"],
 "symbols":{"query":{"types":[]},"tickers":[]},
 "columns":["name","description","close","change","change_abs","volume","average_volume_30d_calc",
            "premarket_close","premarket_change","premarket_volume","market_cap_basic","sector",
            "exchange","type","halted","premarket_time","earnings_release_next_date"],
 "sort":{"sortBy":"premarket_change","sortOrder":"desc"},"range":[0,400]}
```

**Losers screen:** identical but `"premarket_change" in_range [-1000,-3]`, `sortOrder:"asc"`.

> **Filter-operator traps.** `in` is NOT a valid operator — it returns HTTP 400 and looks like a
> source outage. Use `equal`, `in_range`, `greater`, `less`. And `in_range` on the **string** column
> `name` is not a reliable multi-ticker selector: a 30-ticker request has been observed returning
> 14 rows, and a *different* 14 rows minutes later, with no error. To pull specific tickers, use a
> per-ticker `{"left":"name","operation":"equal","right":"<TICKER>"}` scan — exactly one row, every
> time. **A name missing from a bulk scan is a filter artefact, not a missing symbol.**
>
> **`type` must be `in_range ["stock","dr"]`.** `type=stock` silently drops ADRs; `type=fund` drops
> REITs. ADRs and REITs are US-listed securities and belong in the universe.

### Step 2b — The screen (pinned — do not reinvent this each run)

Universe: every US-listed common stock **and ADR** on NASDAQ/NYSE/AMEX. Do NOT re-filter to
"common stock" (drops ADRs) and do NOT filter on domicile.

**GATE A — liquidity.** Pre-market volume ≥ **100,000** shares, **or** market cap ≥ **$200M** with
≥ **10,000** pre-market shares. A ±20% print on 100 shares is not a market.

**GATE B — quality floor for the HEADLINE tables.** Market cap ≥ **$100M**.

- Names that pass Gate A but fail Gate B are still real moves: publish them in a compact
  **"thin tape" block** under the headline table (ticker, %, price, cap, pre-market volume) so
  nothing is hidden — but they never top a headline table.
- **Gate B applies to the screen-driven tables only.** §2's theme clusters are chosen by catalyst,
  not by screen, so an event-driven name of any size (an FDA approval, a take-private, a
  bankruptcy) belongs in its cluster with a sourced catalyst. Do not drop it for being sub-cap.
- Read the `%ADV` column: anything under ~5% is a thin tape, not a market.

The prior session's tables (yesterday's tape) are settled and real — apply Gate A, not Gate B.

### Step 3 — Halts / unusual volume

A second screen on `volume > 50_000_000` surfaces the day's genuine outsized activity (squeeze
candidates, halted/resumed names, M&A spikes). Surface `halted` names explicitly — a name that
prints no pre-market price because it is halted is a fact, not a gap.

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
- Pull market news for the leader and 1–2 corroborators.
- `web_search "<<theme>> <YYYY-MM-DD>"` for the news anchor (e.g. "Trump Greenland rare earth September 21 2026"). One search per cluster, max 5 clusters total.
- If the theme is a single StockTwits thesis with no corroboration: label it "single-name idiosyncratic" and skip the news pull.
- **Assert a catalyst only where it is sourced.** A name you cannot explain gets a move and no
  story — never a guess. Say "catalyst not sourced in this run" instead.

### Step 6 — Overnight context (parallel)

Run these in one assistant turn:

- `mcp__tradingview-advanced__market_snapshot` → bridge `market-recap market_snapshot` (indices, crypto, FX, ETFs)
- `mcp__yahoo-finance__get_market_status` → the `market_state` field on `market-recap get_quotes` (region=US, for cash-open countdown)
- `mcp__tradingview-advanced__futures_category_snapshot` (category=equity_index, for ES/NQ/YM/RTY front-month) → `market-recap get_quotes` with `ES=F,NQ=F,YM=F,RTY=F`
- **Fallback if futures query returns <4 contracts:** read the cash index levels from `market_snapshot` and surface that the front-month futures look-up failed. **Do not chain to web_search on individual futures tickers** — that's not what the playbook says and burns calls.
- **Label every quote with its `as_of` timestamp.** A futures print and a settled index close are
  different things; a reader cannot tell them apart without the timestamp.

### Step 7 — Watchlist section (parallel to steps 1–6, NOT the spine)

The watchlist is a **published file**, fetched at run time:

```
https://raw.githubusercontent.com/karizaco/minimax-cloud-outputs/main/refs/watchlist.yaml
```

- **If it exists (HTTP 200):** publish the watchlist section from it — quote + pre-market gap,
  sorted by absolute pre-market move, and compute the pre-market % **vs the previous session's
  close** explicitly.
- **If it does not exist (HTTP 404):** **omit the section entirely** and say so ONCE in
  `## Source health` (one line: which URL was tried and that it is absent). Do **not** ship an
  empty "Watchlist" section, and do **not** create a default watchlist with invented tickers.
  The publish path, schema and an example live at `research/watchlist.README.md` and
  `research/watchlist.example.yaml` in `karizaco/maxhermes-migration`.
- Skip news for any watchlist ticker that is not also in the day's themes (a watchlist name
  outside the themes gets a one-line "flat, no theme today" and that's it).

### Step 8 — Earnings + Macro calendar

**Earnings — READ CRON #19's FILE FIRST.** Cron #19 (`earnings-reminder-daily`) fires at 06:00 ET,
2.5 hours before this routine, and publishes a structured roster at `earnings/{date}-reminders.md`
on the outputs repo (branch `main`):

```
https://raw.githubusercontent.com/karizaco/minimax-cloud-outputs/main/earnings/{date}-reminders.md
```

It carries, per name: ticker, company, **BMO/AMC release time**, EPS estimate, revenue estimate and
market cap — cross-checked against MarketBeat, the Nasdaq earnings calendar and the TradingView
scanner. It is the best roster available and it is already on disk.

- **If the file is present:** take the roster, the BMO/AMC split and the per-name estimates from
  it. Split §9 into what is **already in the tape (BMO)** and what is **still ahead (AMC)** — that
  distinction is the whole point of a pre-market brief, and no search result gives it to you.
- **If the file is absent (404):** fall back to `web_search` / the Yahoo earnings calendar and say
  in `## Source health` that cron #19's roster was unavailable.
- **Never publish a range** like "79-122 reporters depending on the calendar source". Count from
  one named source, or say which source you counted.

**Macro:** web_search `economic calendar <YYYY-MM-DD> FRED` — and, on a US election or a
scheduled-central-bank day, search the event itself (`US midterm elections <date>`). One search,
≤ 3 lines summary. The macro calendar is not only releases: an election, a central-bank decision or
a war headline is the macro of the day, and a brief that lists only FRED releases misses it.

### Step 9 — Write the brief

Order (load-bearing — do NOT re-order):

1. **TL;DR** — clustered, theme-first. ≥ 4 named themes from Step 4 with their tickers and magnitudes in bullet form. Single-sentence "watchlist" line at the bottom that says which watchlist names happen to align with the day's themes.
2. **Theme clusters** — one section per cluster with anchors, leader, corroborators, magnitudes, news URL.
3. **Pre-market gaps — top 25 market-wide** — from the Step 2 **gainer screen** (`premarket_*` columns), Gate A + Gate B, plus a "thin tape" block for the Gate A-only names. Add a **"yesterday's tape"** sub-table (`change`/`close` columns) for context — clearly labelled as the prior session.
4. **Top losers — top 10 market-wide** — from the Step 2 **loser screen** (`premarket_*` columns), same gates.
5. **StockTwits lead read** — trending list with thesis text shown inline, not buried. Truncate each thesis to ~300 characters and cap the column; a full-sentence dump makes the table unreadable.
6. **Watchlist** — quote + pre-market gap, sorted. **Omit the whole section if there is no published watchlist** (Step 7).
7. **Overnight / futures / index / crypto** — compact block.
8. **Macro calendar** — ≤ 5 lines.
9. **Earnings today** — only if anything material, split BMO / AMC.
10. **Source health** — every source that succeeded/failed.
11. **Open research queue** — ≤ 5 carry-forwards.

Cap top news to **10 items**, **all theme-anchored** (no per-ticker news for non-theme watchlist names).

**Before rendering, prove the brief is internally consistent:** every percentage and price in the
prose must equal the value in the table it came from, and every table row must equal the value you
fetched. One pull of the tape feeds the whole brief — if two pulls disagree (the tape moves), the
older pull wins for the tables and the prose must match it. A brief that contradicts itself is worse
than a brief with less in it.

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
| **Two sessions labelled as one** | The screener's `change` (last regular session) was published under a "pre-market gaps" heading. | Step 2 column contract; `premarket_*` for the gap tables, `change`/`close` for yesterday's tape. |
| **Prose contradicting its own tables** | The live tape was pulled twice; the prose took one pull and the tables another, so the same ticker carried two different percentages. | One pull per brief; the Step 9 consistency check before rendering. |
| **A permanently empty section** | The watchlist file never existed in this runtime, yet the brief carried an explanatory "not published" block every day. | Step 7: omit the section; one line in Source health. |
| **A delivered artifact reported MISSING** | The push script derives the commit subject's routine number from `--add`, and `--add` overwrites — so passing a second path wiped the number and the auditor's `cron (#)?NN ` grep no longer matched. | Pass `--add` once, with the primary artifact path; verify the commit subject, not just the path. |

## Fallback discipline (required on every step)

Every fallback tier ends with **"accept those rows as-is, write `_source=<fallback>`, and stop"**. Examples:

- Step 2 screener HTTP 429 → fall back to the same endpoint's next-best screen (e.g. the session-mover screen) for the same filter. Accept those rows with `_source=tv_bulk_scan` and **stop**.
- Step 5 news search returns 0 → write the cluster with the StockTwits thesis text only. Mark "no corroborating news". **Stop.**
- Step 6 futures category snapshot returns < 4 contracts → use `market_snapshot` indices only and note that front-month futures are missing. **Stop.**
- Step 8 earnings roster (cron #19 file) returns 404 → fall back to `web_search`. Accept and mark it. **Stop.**
- Step 8 macro search returns 0 → write "no macro releases today" and move on. **Stop.**

Do NOT chain a third MCP after a fallback. The Playbook's day-window has its own time cost.

## Hard rules

- Never place trades. Read-only by design.
- Use only the tools named in the RUNTIME DATA-SOURCE CONTRACT (`web_search`, `web_fetch`, `bash` and the MCP-over-HTTP bridge). No browser automation, no new network endpoints without user approval.
- **Citation required:** every cluster leader has ≥ 1 source (URL or file path).
- **One pull per brief.** A live tape pulled twice yields two versions of the same number. Pick one pull and make every section agree with it.
- If the brief is short of themes (≤ 2), surface "thin tape" in the TL;DR — do not pad.
- If MCP `financial_news` (`MARKETAUX_API_TOKEN not configured`) fails, fall back to `web_search` + the bridge and note in `Source health`.

## Out of scope

- Do not run the old `python agentic.py` CLI.
- Do not generate post-market or weekly briefs from this skill (their own files live alongside this one).
- Do not extend the user's watchlist unilaterally — surface missing-file lines and move on.
