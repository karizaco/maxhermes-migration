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


## When

- Cron: `30 8 * * 1-5` America/New_York (weekdays, 08:30 ET — 60 min before the US open).
- Manual: user asks "give me today's pre-market brief" / "run the pre-market brief".

## DELAYED REPLAY — the platform resumed this fire in place

A replay happens when the platform resumes a crashed cron conversation IN PLACE, hours or days
later. `session.created_at` identifies the ORIGINAL fire, so the brief is rebuilt for the FIRE's
date — but the live screen has moved on and cannot be re-pulled for that date.

**The rule: a replay NEVER pulls the live scanner for the screen.** The TradingView `premarket_*`
columns are the replay day's pre-market, and `close`/`change` are the replay day's settled
session. Pulling them publishes the wrong day's tape under the fire's date. Every source for a
replay is a DATED fleet artifact:

| Field | Source for a replayed fire |
|---|---|
| pre-market last, gap %, name | `preopen-feed/{fire-date}-0830.jsonl` (cron #92a checkpoint) |
| pre-market volume, %ADV, market cap, sector | `daily-briefs/{fire-date}-pre-market-refresh.md` (cron #26b — the same pull) |
| pre-market high/low (PM range) | Yahoo chart bars for the fire date, `includePrePost=true` |
| prior close, prior session % | `us-eod/{fire-date-1}.csv` (cron #20, settled) |
| earnings roster | `earnings/{fire-date}-reactions.md` (cron #15) when cron #19's file is absent |
| overnight levels | Yahoo chart bars for the fire date, last bar ≤ 08:30 ET on the fire date |

Three traps, all measured on 2026-11-05:

- **Yahoo carries ZERO pre-market volume** (every pre/post bar's volume is 0). Yahoo can supply
  the pre-market RANGE and the last print; `%ADV` and Gate A can only come from the TradingView
  screen. Yahoo's last print can differ from TV's by a few cents — one source per field, and say
  which in Source health.
- **Gate A is only as good as the PUBLISHED volume.** A name whose cap clears Gate B but whose
  pre-market volume is not published is UNVERIFIABLE, not a pass. Publish it in a labelled block
  beside the headline table; never promote it and never hide it.
- **Market cap has a basis.** The screen publishes it on the PRIOR close's basis; `us-eod/{date}.csv`
  is on that date's close basis. A pre-market brief uses the prior-session file.

A replay also has no StockTwits trending list (the feed publishes no history), may have no
cron #19 roster for the date, and may find the watchlist file seeded AFTER the fire. Say so once
in Source health and publish the dated substitute instead of the live one.

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
  one row per name seen in the pre-market screens. The exact header is pinned in
  `## ARTIFACT FORMAT CONTRACT v2` (§C3) — **date-independent column names only** (a column
  named after a session date is a defect: the 2026-11-03 CSV shipped `nov_2_2026_close` and
  `nov_2_change_pct`, and the 2026-11-04 CSV carried `nov_2_change_pct` still holding the
  *Nov 3* move). The CSV is the same screen the tables are built from, so it must never
  contradict them, and the routine **asserts the header before pushing** (§C4).
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
| `close` | the **last completed regular session** close (yesterday) | the denominator of the pre-market gap; the **prior close** |
| `change` | that **same regular session's** % move vs the prior session | "yesterday's tape" context tables |
| `change_abs` | that session's absolute move | sanity check |
| `premarket_close` | the **live pre-market print** | the price you publish |
| `premarket_change` | the live pre-market % vs `close` | **the gap you publish** |
| `premarket_high` | the pre-market **high** so far | the top of the **pre-market range** |
| `premarket_low` | the pre-market **low** so far | the bottom of the **pre-market range** |
| `high` | the last completed session's high | breakout / prior-day-high key level |
| `low` | the last completed session's low | breakdown / prior-day-low key level |
| `premarket_volume` | running pre-market share counter | the liquidity gate |
| `average_volume_30d` | 30-day average daily volume | `%ADV` = `premarket_volume / average_volume_30d` |
| `halted` | halt flag | the halts table |

> **The pre-market range is part of the price, not a nicety.** `premarket_high`/`premarket_low`
> are measured live and verified against the `america` scanner on 2026-11-06 (AAPL
> `premarket_low` 349.79 / `premarket_high` 355.35 for the 2026-11-05 session, against a
> `close` of 344.17). A reader needs to know whether the gap is **holding** or already
> half-filled — the last price alone cannot say.

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
            "premarket_close","premarket_change","premarket_high","premarket_low",
            "premarket_volume","market_cap_basic","sector",
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

### Step 3b — Read the sibling artifacts before you pull your own

Two other routines publish files on the outputs repo **before** this one fires, and this brief
should not re-derive what they already computed:

| File | Cron | Fires | What it gives you |
|---|---|---|---|
| `earnings/{date}-reminders.md` | #19 | 06:00 ET | the earnings roster, BMO/AMC split, per-name EPS/revenue estimates |
| `earnings/{date}-reactions.md` | #15 | 08:00 ET | the pre-market gap table with a `last earnings` tag and `PRE_GAP`/`POST_GAP` flags, cross-checked against Yahoo |
| `daily-screens/{date}/breadth-snapshot.md` | #10 | 09:45 ET* | session breadth over a 902-name $10B+ universe |

```
https://raw.githubusercontent.com/karizaco/minimax-cloud-outputs/main/earnings/{date}-reactions.md
https://raw.githubusercontent.com/karizaco/minimax-cloud-outputs/main/daily-screens/{date}/breadth-snapshot.md
```

*#10 fires at 09:45 ET — after this routine — so its file is usually the PREVIOUS session's.
Read it for the breadth context and say which session it describes.

Use #15's file to **cross-check** your pre-market screen and to enrich your clusters (a name
already flagged `PRE_GAP` is a gap that is happening, not one that is about to). Do NOT replace
your own screen with it: #15 screens a top-200-mcap universe with a 10,000-volume floor, while
this brief screens the whole market. If the two disagree on a name, say so and take the
**broader** screen.

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

**Front matter first.** The artifact opens with a machine-readable block, so the auditor and any
downstream routine can read it without parsing markdown (cron #19 and #15 already do this):

```
---
date: <YYYY-MM-DD>
cron: 26-agentic-pre-market-brief
contract: premarket-brief-artifact-v2
fire_time_et: <YYYY-MM-DD HH:MM>
snapshot_et: <HH:MM>          # when the pre-market tape was pulled
source: TradingView america scanner + MCP-bridge market-recap
status: ok
themes: <n>
up_3pct: <n>
down_3pct: <n>
---
```

**The order below is load-bearing — do NOT re-order, and do NOT renumber §1–§11.** The two
unnumbered blocks (`## Bottom line`, `## Yesterday's brief — what happened`) sit ABOVE §1; the
numbered sections keep their numbers because other routines and the user reference them by
number.

1. **`## Bottom line`** — exactly three lines, the decision. See §C1.
2. **`## Yesterday's brief — what happened`** — the scorecard on yesterday's calls. See §C5.
3. **`## 1. TL;DR`** — clustered, theme-first. ≥ 4 named themes from Step 4 with their tickers and magnitudes in bullet form. Single-sentence "watchlist" line at the bottom that says which watchlist names happen to align with the day's themes.
4. **`## 2. Theme clusters`** — one section per cluster with anchors, leader, corroborators, magnitudes, news URL. **Every name carries the §C2 level columns.**
5. **`## 3. Pre-market gaps — top 25 market-wide`** — from the Step 2 **gainer screen** (`premarket_*` columns), Gate A + Gate B, plus a "thin tape" block for the Gate A-only names. Add a **"yesterday's tape"** sub-table (`change`/`close` columns) for context — clearly labelled as the prior session. **Every name carries the §C2 level columns.**
6. **`## 4. Top losers — top 10 market-wide`** — from the Step 2 **loser screen** (`premarket_*` columns), same gates. **Every name carries the §C2 level columns.**
7. **`## 5. StockTwits lead read`** — trending list with thesis text shown inline, not buried. Truncate each thesis to ~300 characters and cap the column; a full-sentence dump makes the table unreadable.
8. **`## 6. Watchlist`** — quote + pre-market gap, sorted. **Omit the whole section if there is no published watchlist** (Step 7).
9. **`## 7. Overnight / futures / index / crypto`** — compact block.
10. **`## 8. Macro calendar`** — ≤ 5 lines.
11. **`## 9. Earnings today`** — only if anything material, split BMO / AMC.
12. **`## 10. Source health`** — every source that succeeded/failed.
13. **`## 11. Open research queue`** — ≤ 5 carry-forwards.

Cap top news to **10 items**, **all theme-anchored** (no per-ticker news for non-theme watchlist names).

**Before rendering, prove the brief is internally consistent.** One pull of the tape feeds the
whole brief — if two pulls disagree (the tape moves), the older pull wins and the prose must match
it — and **the CSV must be built from the very same merged table the markdown uses**, not from a
second merge order. On 2026-11-03 the CSV took a later per-ticker fetch for some names while the
markdown took the earlier bulk screen, so AEHR read +18.5% in a table and +18.8% in the CSV.

There is a linter for this. Run it and fix what it reports:

```bash
python3 https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/tools/check_brief_consistency.py \
  --md /workspace/daily-briefs/{date}-pre-market.md \
  --csv /workspace/daily-briefs/{date}-pre-market.csv
```

It exits non-zero when the prose, the tables and the CSV disagree, when a section is missing or out
of order, or when an unfinished placeholder is left in the file. **A non-zero exit means the
artifact is not ready to push.** (Fetch it to a file first; `python3 <url>` does not work.)

**Then run the CONTRACT gate** — the one that asserts §C1–§C5 of this spec:

```bash
mkdir -p /workspace/tools
curl -sL --max-time 30 -A "Mozilla/5.0" -o /workspace/tools/check_premarket_brief.py \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/tools/check_premarket_brief.py"
python3 /workspace/tools/check_premarket_brief.py \
  --md /workspace/daily-briefs/{date}-pre-market.md \
  --csv /workspace/daily-briefs/{date}-pre-market.csv
```

**Both checkers must exit 0 before the push.** A non-zero exit from either means the artifact is
not ready to push.

### Step 10 — Audit + chat summary

- Append: `2026-MM-DDTHH:MM:SSZ action=brief_rendered target=pre_market:<date> session=me sources=<csv> model=… skill=agentic-pre-market-brief themes=<count>` to `research\logs\audit.log`.
- Return a compact ≤ 60-line chat summary, **theme-first**. Do NOT paste the full markdown.

---

## ARTIFACT FORMAT CONTRACT v2 — `premarket-brief-artifact-v2`

This section IS the contract. It is fetched at RUN time, so an edit here changes the next fire
with no prompt edit and no prompt drift. `tools/check_premarket_brief.py` asserts every clause
below and prints each violation; `tools/test_premarket_brief_contract.py` proves the contract is
satisfiable AND that the checker bites. **An artifact that fails the gate MUST NOT be pushed.**

### C1 — `## Bottom line`: three lines, above the theme TL;DR

The 2026-11-03 brief was a 44 KB map of the day with no decision in it: six themes, excellent
analysis, no call. The trader's first fifteen seconds need a decision, so the brief opens with
one. **The six-theme clustering stays exactly where it is, below this block** — the contract is
additive, and the clustering is what makes a 44 KB artifact navigable.

```
## Bottom line

1. **The one setup** — <NAME or theme> — <level> is the trigger; <invalidation> kills it.
2. **The one risk** — <what breaks it> — <catalyst time | level | macro event>.
3. **The one thing to watch** — <name or level> — <condition>.
```

- **EXACTLY three lines.** Not two, not four.
- The three labels are literal, capitalised and in this order: `The one setup`, `The one risk`,
  `The one thing to watch`.
- Line 1 MUST carry a level and its invalidation: it contains a digit **and** the word
  `invalidat*`. "AMD is the referee tonight" is not a setup. "AMD above 161.30, invalidated by a
  trade back under 159.00" is.
- Lines 2 and 3 each name a thing and a condition. "The market is fragile" is neither.
- The block sits above `## 1. TL;DR`, directly under the title/front-matter block. No prose
  between the heading and the first line.

### C2 — Every published name carries its levels

Every name published in **§2 (theme clusters)**, **§3 (pre-market gaps)** and **§4 (top losers)**
carries these columns. A setup without a level is an opinion.

| Column | What it is | Source |
|---|---|---|
| `Prior close` | the last completed regular session's close | scanner `close` |
| `Pre-market last` | the live pre-market print | scanner `premarket_close` |
| `Gap %` | the pre-market move vs the prior close | scanner `premarket_change` |
| `PM range` | the pre-market low–high — is the gap holding? | scanner `premarket_low` / `premarket_high` |
| `Key level` | the price that decides the setup | derived, see below |
| `Invalidation` | the level or event that kills the thesis | derived, see below |

**`Key level` — deterministic ladder, first match wins:**

1. The **prior close** — the gap-fill level. The question a gap raises is "does it hold", and the
   prior close is the level that answers it.
2. A level published by the **sourced catalyst** (an all-stock deal's implied value for the other
   leg, an offering price, a 52-week high) replaces the above — with the source named in the cell.

**`Invalidation` — the level that kills the setup, always a DOWNSIDE trigger:**

- gap-up: **back to or below the prior close** — the gap filled, the move failed.
- gap-down: **below the pre-market low** — the pre-market seller won.
- where the catalyst publishes a number that decides it instead ("if the 16:00 ET guide is below
  $1.95"), that number and its side.

The setup the brief publishes is a LONG in both cases — buy the gap, or buy the flush — so the
invalidation is always the downside level that says the long is wrong. That is the convention the
2026-11-06 artifact shipped, and it is the one this contract pins.

> **Write the side into the cell, not just the number.** `back to/below prior close 404.40`,
> `below PM low 29.14` — not `404.40`. The next morning's review is a mechanical test on this
> cell, and a bare number does not say which side of the level breaks the thesis: the reviewer has
> to infer it, and an inference that is right for one convention is silently wrong for another.
> The 2026-11-05 brief published `478.69` with no side and the 2026-11-06 brief published
> `back to/below prior close 404.40` — two briefs, two readings, and the review can only be
> correct for one of them. Carry the side and the loop stops guessing.
>
> Every `Invalidation` cell MUST contain a digit **and** a side word (`above`, `below`, `under`,
> `over`, `back to`) and must not be a placeholder. A vague cell ("if momentum fades") is a broken
> cell, not a soft one.

The pre-market range is published, not just the last price: a reader needs to know whether the gap
is holding or already half-filled, and the last price alone cannot say.

### C3 — The CSV schema (date-independent column names)

The companion CSV ships with exactly this header, in this order:

```
ticker,name,premarket_last,premarket_high,premarket_low,prior_close,gap_pct,prior_session_change_pct,premarket_volume,avg_volume_30d,pct_of_adv,market_cap,sector,exchange,liquid_screen,quality_screen,has_news,key_level,invalidation,setup_theme,setup_published
```

- **No column name may contain a date.** The 2026-11-03 CSV shipped `nov_2_2026_close` and
  `nov_2_change_pct`; the 2026-11-04 CSV then carried `nov_2_change_pct` while it actually held
  the *Nov 3* move. A date-named column is a lie waiting for the next session.
- `prior_close` = the last completed regular session's close. `gap_pct` = the pre-market move
  vs it. `prior_session_change_pct` = that session's own % move (the "yesterday's tape" number).
- `key_level` and `invalidation` carry the §C2 values for every name, so the next morning's
  review (§C5) can test them mechanically. **`invalidation` carries the SIDE as well as the
  level** (`back to/below prior close 404.40`, `below PM low 29.14`) — the review is a mechanical
  test on that cell, and a bare number leaves the direction to be inferred.
- `setup_published` = `yes` for every name published as a setup in §2 (the theme clusters) and
  `no` otherwise. **This column is what makes the next run's review possible.**
- `setup_theme` = the cluster label for that name (empty for names not in a cluster).
- `has_news` = `yes` **only** where a catalyst is sourced in this run. On 2026-11-03 exactly 35 of
  1,491 rows had one, and the count is meaningful precisely because it is small. Never fill it
  from a theme's existence — only from a source.
- Round what you publish: prices to 2 dp, percentages to 2 dp. The 2026-11-04 CSV shipped
  `3.06406685236769` for a gap of 3.06%.

### C4 — The header assertion (before the push, not after)

The spec promised columns the CSV did not have — that is how a shipped artifact contradicts its
own contract. So the routine **reads the CSV's own header and asserts every column §C3 promises,
before pushing**. The check is mechanical:

```bash
python3 - <<'PY'
import csv, sys
want = "ticker,name,premarket_last,premarket_high,premarket_low,prior_close,gap_pct,prior_session_change_pct,premarket_volume,avg_volume_30d,pct_of_adv,market_cap,sector,exchange,liquid_screen,quality_screen,has_news,key_level,invalidation,setup_theme,setup_published".split(",")
with open("/workspace/daily-briefs/{date}-pre-market.csv", newline="", encoding="utf-8") as fh:
    got = csv.DictReader(fh).fieldnames or []
missing = [c for c in want if c not in got]
extra = [c for c in got if c not in want]
print("csv columns:", len(got))
if missing:
    print("CSV HEADER MISSING:", missing); sys.exit(1)
if extra:
    print("CSV HEADER HAS UNPROMISED COLUMNS:", extra); sys.exit(1)
print("csv header OK")
PY
```

A non-zero exit means **do not push** — fix the CSV, then push.

> **A wording slip must not cost the day's brief.** The common failure is the invalidation
> column published as a bare level (`478.69`) instead of a level with its side
> (`below PM low 29.14`). The checker names the offending row and the expected form, and the CSV
> is one edit away: repair the cell per §C2's ladder, then re-run the checker. Repair the cell and
> push; do not abandon the artifact over a missing word. But do not publish a cell that leaves the
> next morning's review guessing which side of the level breaks the thesis.

The same gate covers the commit subject: the push subject must carry the routine number, i.e.
the string `cron 26` must appear in the subject of the commit that last touched the artifact.
`push_artifact.sh` derives it from the artifact path, and `verify_delivery.sh --nn 26` fails with
exit 4 when it is missing. The path→number table in `push_artifact.sh` covers BOTH
`daily-briefs/*-pre-market.md` and `daily-briefs/*-pre-market.csv` — the CSV row was added on
2026-11-03 after a CSV pushed with the subject `cron daily-briefs 2026-11-03` (no number) was
reported MISSING by cron #90's triage.

### C5 — `## Yesterday's brief — what happened`

The brief's last section is `## 11. Open research queue` — good, and it stays. But nothing
records what happened to yesterday's calls, so the routine cannot learn. This section closes the
loop. **It is the highest-leverage addition in the fleet: it is what turns a daily brief into a
trackable process.**

It appears in EVERY run, directly under `## Bottom line`, and carries exactly this table:

```
| Name | Setup (yesterday) | Yesterday's close | Today's move | Thesis held? |
```

**How to build it (do not improvise):**

1. **Pick the reviewed brief.** Walk back from the fire date to the most recent earlier date that
   has a DAILY brief at `daily-briefs/{date}-pre-market.md` on the outputs repo (`main`). Read it
   with the **GitHub contents API** (authoritative, not CDN-cached). Skip the
   `-pre-market-refresh.md` file — it is a different routine (#26b). **A day with no brief is
   skipped, and the artifact says so** (e.g. "the 2026-11-05 fire published nothing — quota
   wall — so this reviews the 2026-11-04 brief").
2. **Take the setups from that brief's own CSV** — the rows with `setup_published = yes` — and
   their `key_level` / `invalidation` values. If that CSV predates the column, fall back to the
   tickers in the reviewed brief's §2 theme-cluster tables.
3. **Get the outcome.** Use the helper, which does the pulls and the arithmetic:

   ```bash
   mkdir -p /workspace/tools
   curl -sL --max-time 30 -A "Mozilla/5.0" -o /workspace/tools/yesterday_review.py \
     "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/tools/yesterday_review.py"
   python3 /workspace/tools/yesterday_review.py --date {date} \
     --out-md /workspace/daily-briefs/{date}-pre-market.md
   ```

   It reads the reviewed brief and the previous evening's post-market brief (cron #23,
   `daily-briefs/{date}-post-market.md`), pulls the session bars for the setup names through the
   MCP bridge (`market-recap price_history`) and the Yahoo chart API for the intraday extremes,
   and prints the table plus a JSON sidecar. It prints the legend line too — paste it above the
   table.

   **The trigger side comes from the reviewed brief's own cell.** `invalidation` reads
   `below PM low 29.14` / `back to/below prior close 404.40`, so the direction is stated rather
   than inferred; a brief published before the side existed falls back to the gap's sign, and the
   row says the side was assumed. Either way the verdict is a mechanical test on the level the
   brief published.
4. **The legend defines the columns, in one line**, because "yesterday" is ambiguous when a
   session was missed:
   - `Yesterday's close` = the close of the **last completed regular session** at the time of
     writing.
   - `Today's move` = **that session's** % change vs its own prior close.
   - `Thesis held?` = judged against the invalidation the reviewed brief published: `HELD`
     (the invalidation was not touched and the move ran with the thesis), `BROKE` (the
     invalidation level was traded through in the adverse direction), `PARTIAL` (the invalidation
     held but the move ran against the thesis), `UNJUDGED` (no invalidation level was published,
     or there is no price for the name — say which).
5. **The section always exists.** If the reviewed brief is missing, if the helper cannot reach a
   source, or if there are no setups to review, the section still ships, with one line naming the
   reason (`no prior brief available`, `the reviewed brief's CSV carries no setup rows`, …). A
   section that silently disappears is how a loop dies.

**Cross-check, don't assume:** the previous evening's post-market brief is the narrative
cross-check for the session's closes; when it names a setup name in its movers tables, its close
must agree with the helper's. If it does not, the section says so rather than publishing two
numbers.

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
| **A 44 KB brief with no decision in it** | The TL;DR was a *map* of the brief (six themes) rather than a call. The trader had to do the synthesis. | §C1: `## Bottom line`, exactly three lines, above the theme TL;DR. |
| **Setups with no prices** | The 2026-11-03 brief named "AMD is the referee tonight", Oracle's $20B capex and the Marvell/Lumentum spread — and published no level for any of them. A trader cannot act on a name without a number. | §C2: `Prior close`, `Pre-market last`, `Gap %`, `PM range`, `Key level`, `Invalidation` on every published name. |
| **The CSV contradicted the spec** | The spec promised columns the CSV did not have, and the CSV carried date-named columns (`nov_2_2026_close`) that silently went stale. | §C3: a pinned, date-independent header; §C4: assert the header before the push. |
| **The brief had no follow-up** | Nothing recorded what happened to yesterday's calls, so the routine could not learn. | §C5: `## Yesterday's brief — what happened`, every run, with a `Thesis held?` column. |
| **A stale shared helper** | `push_artifact.sh` was fetched with `[ -s file ] || curl`, so an old local copy kept using the old path→number table, and raw.githubusercontent served a stale blob for >17 min after a push. | Fetch-ladder rule below: contents API first, then raw, then jsDelivr, reject a 404 body, **refresh every run**. |

## The fetch-ladder rule (every shared helper, every run)

The contents API is authoritative and is **not** CDN-cached; the two CDNs cache `main`
independently (measured 2026-11-04: raw.githubusercontent served a stale blob for >17 minutes after
a push while jsDelivr was fresh). So:

1. Try the **GitHub contents API** first, then raw, then jsDelivr.
2. Reject a response whose **body** is a 404 JSON (`{"message": "Not Found", ...}`) — on its body,
   not on its byte count.
3. **Refresh on every run.** Never skip the fetch because the file already exists: a stale local
   copy of a shared helper silently keeps using the old table.
4. When the helper carries a capability marker (a version string), require it — an older copy
   that silently ignores new flags is worse than no copy.

```bash
S=/workspace/push_artifact.sh
for U in \
  "https://api.github.com/repos/karizaco/maxhermes-migration/contents/cloud-prompts/_shared/push_artifact.sh?ref=main" \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/push_artifact.sh" \
  "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/push_artifact.sh" ; do
  curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" \
    -H "Authorization: Bearer ${GITHUB_TOKEN}" -o "$S.tmp" "$U" 2>/dev/null
  if [ -s "$S.tmp" ] && ! head -c 200 "$S.tmp" | grep -q '"message"'; then
    mv -f "$S.tmp" "$S"; break
  fi
  rm -f "$S.tmp"
done
[ -s "$S" ] || echo "push script UNAVAILABLE — use the inline fallback"
```

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
- **The `mcp__*` tool names do not exist in this runtime.** Do not call them and do not spend turns proving they are absent.
- **Both checkers exit 0 before the push** (§Step 9): `check_brief_consistency.py` (prose ≡ tables ≡ CSV) and `check_premarket_brief.py` (the §C1–§C5 contract).
- **The commit subject carries the routine number** — `cron 26 <name> <date>`. `verify_delivery.sh --nn 26` exits 4 when it does not, and cron #90's triage greps subjects for `cron (#)?26 `.

## Out of scope

- Do not run the old `python agentic.py` CLI.
- Do not generate post-market or weekly briefs from this skill (their own files live alongside this one).
- Do not extend the user's watchlist unilaterally — surface missing-file lines and move on.
