Before improvising a YouTube transcript workflow, check the `youtube-transcripts` topic memory. It has the canonical procedure (yt-dlp vs urllib fallback for 429s, VTT cleanup for YouTube's auto-aligned captions, language-detection ordering) and the failure modes that already cost time once.
## Accuracy: never invent acronym expansions or backronyms

Rule: When asked what an abbreviation, file pattern, or identifier "stands for",
ALWAYS open the source file (or grep for the literal text) before stating any
expansion.

Apply when:
- Asked "what does X mean?" / "what does X stand for?"
- Asked about a filename pattern that looks like a project acronym
- Asked to explain any identifier whose expansion is not literally in source
- Asked to recall a definition of an unfamiliar abbreviation from memory

If a search finds no expansion in source, say "I don't know" or "I can't find
an authoritative expansion — please confirm" rather than constructing a
plausible one. A plausible-sounding wrong answer is worse than "I don't know".

Evidence: 2026-09-21 session — I told the user SPRB in `SPRB_Equity_Research_Sep2026.md`
stood for "Senior Priced Research Brief". It actually stood for Spruce Biosciences
(NASDAQ: SPRB), the ticker of the company being researched. I pattern-matched
"SPRB" as a backronym instead of opening the source file. The user's project
AGENTS.md has an explicit "Accuracy Mandate: Triple-check every figure" rule
that I broke with a single sentence.

## Accuracy: never cite numbers/names/identifiers without source verification

Rule: When stating a specific number, name, ticker, or identifier — even one
that feels "obviously correct" — verify against ≥1 source file in the workspace
or an authoritative external reference before writing it.

Plausibility != correctness. "It sounds right" is exactly when verification is
most important, not least. The pattern that produces confident-sounding
fabrications is the same pattern that produces fluent-looking work — the only
defense is to actually read the source.
## Pipeworx hosted MCP gateway — first stop for blocked/restricted data sources

Rule: When a popular data source's direct REST API returns 403/Cloudflare
geo-block from this machine (or from a common Linux/Windows datacenter IP),
check Pipeworx MCP gateway as a hosted-MCP shortcut before writing a custom
scraper or wrapper MCP.

Verified pattern (2026-09-20):
- URL convention: `https://gateway.pipeworx.io/<source>/mcp`
- Transport: streamable-http / SSE (some endpoints reject GET — must POST JSON-RPC)
- Verify alive by POSTing:
  `{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"smoke","version":"1.0"}}}`
  with `Accept: application/json, text/event-stream` header. Expect 200 +
  `text/event-stream` body that starts with `event: message\ndata: {…}`.
- After confirmed, add via `mavis mcp create --transport streamable-http --url <url>`.

Known working packs (verified):
- `stocktwits` — 9 tools (symbol_stream, user_stream, trending_symbols,
  trending_messages, suggested_symbols, symbol_search, chart_data,
  watchlists, watchlist). Keyless public read endpoints via the gateway;
  200 req/hr/IP rate limit. Direct `api.stocktwits.com` returns 403 from
  this host; the gateway bypasses via Cloudflare-fronted egress.

Pattern, not exhaustive — many other sources are hosted the same way at
the gateway (`https://gateway.pipeworx.io/<source>/mcp`). Keyless when
the source has public read endpoints; may require API keys for paid
sources. Always verify with the JSON-RPC initialize handshake before
committing to a config.

Apply when:
- Asked to add an MCP for a data source whose direct API is 403'd from here
- Asked to "wire up X data via MCP" and a Pipeworx pack exists for X
- Investigating whether a hosted MCP exists before writing a local stdio wrapper
## Cron / scheduled-task prompts must be directive, not exploratory

Rule: When writing a cron prompt for an Agent (or any scheduled Agent
task), every fallback branch must end with an explicit "accept the
fallback result, write the artifact, and stop" instruction. Never leave
"filter for X shape" / "confirm with Y" type tasks without saying what
to do if the deeper confirmation is impossible or expensive.

The Agent will otherwise correctly identify that the fallback doesn't
fully satisfy the requirement — and then enter a decision loop trying
to decide whether to chain deeper MCP calls, burn tokens for 10+
minutes, and end up in a permanent `active-turn` zombie session.

Evidence: 2026-09-21 reversal-bullish cron
(`b5187e5c-b93a-47a9-9783-2dc77dd4deb7`). Prompt said "filter for the
3-candle shape (long lower shadow, small body, prior decline)" but the
Tier-2 Finviz URL only returns daily % change, not OHLC shape. Agent
correctly identified the contradiction and then spent 14+ min in
`active-turn` deciding whether to chain per-ticker yahoo-finance for
OHLC. Session never produced any output file. Runtime did not
time it out. The Agent was not stuck on a tool call — it was stuck
*thinking* between two valid options with no tiebreaker in the prompt.

Apply when:
- Writing any cron / scheduled Agent prompt
- Designing a multi-tier MCP fallback chain
- The prompt contains "filter for X" / "confirm with Y" / "verify
  the shape" instructions that depend on data the fallback tier
  doesn't provide

Pattern: "If <fallback tier> is used, accept those rows as-is with
`_source=<fallback>`, write the artifact, and stop. Do NOT chain
<deeper MCP> — that's not what the playbook says and it burns N+
calls per row."

Also: `cron sessions` reports `delivered` for any session the Agent
runtime has begun processing, even if the Agent is stuck in a thinking
loop. `session messages` (with `limit`) is the actual liveness check.
## Pre/post-market briefs MUST watch the entire US market, not the watchlist

Rule: A time-bounded market brief (pre-market, post-market, mid-day,
weekly recap, earnings reaction) is a **market-wide report** that
mentions the user's watchlist. It is NEVER a watchlist report that
mentions the market. The user's `watchlist.yaml` is a personal tracker
and appears as **one section** of the brief — it is not the spine.

The market-wide spine is built every time:
1. `mcp__stocktwits__trending_symbols` (limit=15). Each row is a LEAD
   INDICATOR, not a footnote. For every trending ticker outside the
   watchlist (especially any with a non-trivial `trends.summary`
   thesis text), pull price + pre-market gap immediately via
   `mcp__tradingview__lookup_symbols` + `mcp__tradingview-advanced__stock_extended_hours`
   (or batched `stock_prices` if multiple).
2. `mcp__tradingview__screen_stocks` for gainers (filters: `change > 3%,
   typespecs has common, volume > 500_000`, sorted by `change desc`,
   limit=25, markets=['america']).
3. Same tool with `change < -3%` sorted asc, limit=25.
4. **Cluster ALL gap names from steps 1–3 by catalyst** BEFORE writing
   any prose (Greenland/REE, AI silicon, crypto-leg, single-name, etc.).
   The TL;DR is theme-first; the watchlist is one bucket inside the brief.
5. THEN in parallel: read research/watchlist.yaml and pull quotes +
   extended-hours for the watchlist names (12 calls, no big deal).

If `<= 2` themes surface from the clustering, write "thin tape" in
the TL;DR — do not pad with watchlist filler. If `watchlist.yaml` is
missing, write the brief WITHOUT a watchlist section and surface the
missing-file line in Source health. NEVER create a default watchlist
unilaterally.

Evidence: 2026-09-22 user feedback on the 2026-09-21 pre-market brief
(watchlist of 12 names; ~16 KB output). The day's dominant theme was
Trump's US–Denmark–Greenland security pact → entire rare-earth /
critical-minerals complex lit up pre-market. 17+ names traded up ≥30%
(GRML +230%, GLND +140%, BTTC +117%, VEEE +100%, VRME +73%, AVAT +73%,
INV +47%, CRML +38%, NCPL +36%, …). The original brief mentioned exactly
*zero* of these — it had CRML as a "footnote" because StockTwits ranked
it #3 trending, but the Agent never pulled the price. SKILL.md for
`agentic-pre-market-brief` v1 had step 4 say "*use TradingView screener
for any halted or gap-up names*" but as an OR with `web_search`, so the
Agent substituted watchlist-only news. Result: a ~13 KB brief that
listed the watchlist faithfully but missed the actual day's tape. User
verdict: *"this is completely useless. you cannot work from a 12-name
watchlist. nonsense. the premarket brief must watch everything - all
existing publicly listed US companies."*

Apply when:
- Generating any pre/post-market, mid-day, weekly, or earnings reaction brief
- Building a screener-driven watchlist or universe filter
- The user's task mentions "market today", "what's moving", "the day's
  tape", "pre-market gaps", "post-market movers"

DO NOT apply when:
- The user explicitly asks for a watchlist-only check
  ("how is my watchlist doing?"). That's a different task and the
  spine correctly is the watchlist.

Cross-check: every `stocktwits trending_symbols` row carries
`trends.summary` (a one-paragraph thesis). Treat that as a **lead
indicator** that triggers a price check, not as a footnote. Pull
`stock_extended_hours` for any trending row not on the user's
watchlist before deciding it's noise.

Three-question test scope: this is Agent memory — it's a methodology
lesson valid across any market brief in any user's research vault, not
a project file (no project-wide meaning) and not user-specific (applies
to any pre-market brief regardless of the user).
## mavis cron tool quirks — `cron update` silently drops `cron_name`; `cron create` requires explicit `agent_name`

Rule: Two known gaps in the mavis cron tool surface, both hit in this session:

1. `cron update --cron_name X` is accepted by the argument schema but the runtime silently drops the field. `ok: true` returns, the cron task body shows the OLD `cronName`. The only reliable way to rename a cron is `cron delete` + `cron create`.

2. `cron create` rejects `session.mode=new` without an explicit `agent_name`, despite the tool doc saying it defaults to `"me"`. Always pass `agent_name: "me"`.

Evidence: 2026-09-22 session on karizaco/mavis, renaming "Stock-screener cron watchdog (every 15m)" → "(hourly)". Two consecutive `cron update --cron_name '...'` calls returned `ok:true` but `cronName` was unchanged in the response object both times (confirmed with `cron get` between calls). The first `cron create` failed validation with `agent_name is required when creating a new target session`; retry with `agent_name: "me"` succeeded.

Apply when:
- Renaming any cron
- Running any `cron create` — always include `agent_name: "me"` upfront, do not rely on the default
- Debugging "I updated the name but it didn't stick" reports
- Wrapping mavis cron calls in any rename/migration UX

Pattern (rename):
1. Confirm the user understands the side effect: the new cron_id is fresh, so anything hard-coding the old UUID (e.g. `watchdog.log` audit lines, downstream scripts filtering by `cron_id`, other cron prompts that reference the watchlist) breaks.
2. `cron delete --cron_id <old>` → `cron create --cron_name <new> --schedule <s> --prompt <p> --agent_name "me" --session '{"mode":"new"}' --model <m>`. Schedule + prompt + model + project carry over automatically; only `cron_id` and run history are lost.
3. Verify with `cron list` (or `cron get --cron_id <new>`) that the new name is in the response. If it's NOT, you've hit the same gap recursively — escalate, do not retry blindly.

Pattern (don't do):
- Do NOT loop retrying `cron update --cron_name X` — every retry silently drops the same way. One retry is a useful diagnostic ("is this me or a runtime gap?"); more is wasteful.
- Do NOT trust `ok:true` on `cron update` as proof the name changed — always re-`cron get` to confirm.
## Don't `⚠ low-float` a real catalyst-driven small-cap move

Rule: Reserve `⚠ low-float` for when shares-outstanding data shows <10–20M.
A small-cap that is +30–40% on a real catalyst (REE/Greenland theme, AI
silicon, FDA, halt-resume) is NOT a low-float artifact — that's the
catalyst doing the work, and tagging it `⚠ low-float` buries the tradeable
information. Default: do NOT tag.

Evidence: 2026-09-22 — CRML (Critical Metals Corp., +39.67%) tagged
`⚠ low-float` in the open-slot chat. User pushback: "I do not think CRML
is exactly low float btw." CRML was riding the Greenland/REE theme
(per 2026-09-22 pre-market memory entry on the Trump-Greenland security
pact). The flag actively mis-classified the move.

Apply when:
- Writing any `*-stocks-in-play` chat or file tier table
- Deciding whether to add `⚠ low-float` to a small/micro-cap row
- Cross-checking Tier C gap watch or Tier B sympathy names

Pattern:
1. Ask: do I have evidence of low float (shares-outstanding <10–20M)?
2. If yes → flag.
3. If no → do NOT flag, even if the % move is large.
4. The catalyst / theme is what makes the name in-play. Surface that,
   not a default small-cap caution tag.
## Pattern-study backlogs need an "is it live now?" split, not just history

Rule: When a recurring weekly cron appends to a long-running pattern-study
backlog (peoplewish 1000%-in-10y, multi-year RS leaders, decade-window
breakouts, etc.), the file needs an active-vs-historical split, not just
"every ticker that ever matched the math." Two columns make this work:

1. `peak_date` — when did the qualifying move actually happen?
2. `is_current` — boolean: did this ticker ALSO appear in the most recent
   live scan / today's Focus list / this week's gainers?

Without these, the backlog silently conflates "ran in 2018 and crashed" with
"running right now" — and any downstream consumer that reads the file as a
watchlist picks up ghosts. With them, the file splits cleanly into
`active:` (last 90 days AND in current live scan) and `archive:` (older
peaks OR no longer passing the filter).

Also: append an `added_on` column on first sighting for retrospective review.
"What did the backlog look like 6 months ago?" is otherwise unrecoverable.

Evidence: 2026-09-22 pattern-study backlog test run. Wrote 200 tickers to
`peoplewish-1000pct-backlog.md` from a single `MAX(close/close_252_ago - 1)`
SQL. Same SQL next Saturday returns largely the same 200 (deterministic on
fixed 10y window) — growth only happens on a genuinely new 10x event. The
audit line `backlog_added=N backlog_total=200` correctly reports it but the
file itself gives no signal which of the 200 are *live* peoplewish
candidates vs historical reference. Without the split, the file looks
identical week after week and any routine that reads it for "what's peoplewish
running this week?" pulls stale data.

Apply when:
- Designing any weekly/monthly pattern-study backlog file
- A cron prompt says "append newly-tagged names to X.md" where X.md is a
  long-running file (not a daily snapshot)
- Writing SQL that finds "any ticker matching Y in the last N years" —
  always include the date of the matching event, not just the count
- The user asks "improve this scanner / this routine" — these two columns
  are the most common ask

Pattern (SQL):
```sql
WITH lagged AS (
  SELECT symbol, date, close,
    LAG(close, 252) OVER (PARTITION BY symbol ORDER BY date) AS close_252_ago
  FROM shibui.stock_quotes
  WHERE date >= '2016-01-01' AND exchange IN ('NYSE','NASDAQ','AMEX')
)
SELECT
  symbol,
  MAX((close / NULLIF(close_252_ago, 0) - 1) * 100) AS peak_gain_pct,
  COUNT(*) FILTER (WHERE (close / NULLIF(close_252_ago, 0) - 1) >= 10) AS n_1000pct_windows,
  arg_max(date, (close / NULLIF(close_252_ago, 0) - 1)) AS peak_date
FROM lagged
WHERE close_252_ago IS NOT NULL AND close_252_ago >= 1.00
GROUP BY symbol
HAVING peak_gain_pct >= 1000
```

Then in the file: split rows into `## Active (peak_date >= today-180d)`
and `## Archive (peak_date < today-180d OR peak_date IS NULL)`. Promote
to `## High-conviction` any ticker that ALSO appears in the daily Focus list
for the current sweep — that's the peoplewish-current signal the user
actually wants.
## shibui is T+1; same-day SQL needs the LATEST available date, not today

Rule: `mcp__shibui-finance__stock_quotes` is end-of-day with a 1-trading-day
lag. Today in ET is rarely in shibui before ~06:00 ET the next morning. Any
cron / scan that filters SQL on `q.date = '<cron_date>'` will silently
return 0 rows on the cron day itself.

Always:
1. Resolve the latest available date first via
   `python screen.py emit-sql resolve_date <cron_date>` and a shibui query.
2. Substitute `latest_date` (NOT `cron_date`) into the rest of the SQL.
3. If `latest_date < cron_date`, tag rows `_source=mcp_T+1_latest` and
   surface the lag in the markdown + audit line so the reader sees it.
4. The default `emit-sql reversal_bullish <date>` has a SECOND bug: the CTE
   filters `WHERE q.date = '<date>'` BEFORE the LAG window, so the window
   has only one row per symbol and `LAG(close, 2)` returns NULL for
   everyone — the 2-day-decline filter then drops the entire result set
   even when shibui DOES have prior data. Always use a windowed CTE with
   `ROW_NUMBER() = 1` to pick the latest per symbol, NOT the single-date
   CTE the script emits.

Evidence: 2026-09-22 reversal-bullish cron retry (mvs_3bf45ff501074e36942b18468be6987d).
At 22:38 ET Sep 22 the cron fired with the canonical `screen.py reversal-bullish 2026-09-22`
SQL. Two failures stacked:
- (a) shibui had no rows for 2026-09-22 → CTE was empty → 0 results.
- (b) After substituting latest_date=2026-09-21, the SQL still returned 0
  because the CTE filtered to one date before the LAG, so LAG(close, 2)
  was NULL for every symbol. The 2-day-decline filter then rejected all
  286 candidates that otherwise matched the lower-shadow + body shape.
Fixed by switching to a windowed CTE (`date BETWEEN '<cron_date-7d>' AND
'<latest_date>'` with `ROW_NUMBER() = 1`) — that produced 10 valid
candidates (**EXE**, **SMFG**, **XPEV**, **JBHT**, **ERIC**, **INTU**,
**TFII**, **EQT**, **WPP**, **STE**).

Apply when:
- Writing or reviewing ANY shibui SQL that filters on a date literal
  (`q.date = '<date>'`, `date BETWEEN ... AND ...`)
- Building a daily cron that uses shibui as the data source
- Reviewing the reversal-bullish, breadth, or pre-market-gap SQL
- Debugging "shibui returns empty results on the cron day" / "LAG / window
  function returns NULL on the same-day filter"

Pattern (T+1-safe reversal-bullish):
```sql
WITH ranked AS (
  SELECT q.symbol, q.date, q.open, q.high, q.low, q.close,
         v.market_cap,
         ROW_NUMBER() OVER (PARTITION BY q.symbol ORDER BY q.date DESC) AS rn,
         LAG(q.close)    OVER (PARTITION BY q.symbol ORDER BY q.date) AS prev_close,
         LAG(q.close, 2) OVER (PARTITION BY q.symbol ORDER BY q.date) AS close_2d_ago
  FROM shibui.stock_quotes q
  JOIN shibui.valuation v ON q.symbol = v.symbol AND q.date = v.date
  WHERE q.date BETWEEN '<cron_date-7d>' AND '<latest_date>'
    AND q.exchange IN ('NYSE','NASDAQ','AMEX')
    AND v.market_cap > 5000000000
)
SELECT symbol, close AS entry_price, ...
FROM ranked
WHERE rn = 1 AND close < open * 1.02 AND ...
ORDER BY ... DESC LIMIT 10
```

The cron prompt `b5187e5c-b93a-47a9-9783-2dc77dd4deb7` and the
`stock-screener-suite` SKILL.md §5 were updated to encode this.
## Pradeep Bonde / Stockbee Reversal-Bullish — the 8 canonical SQL filters

Rule: A correct Bonde reversal-bullish scan needs all 8 of these. The
loose-filter version (lower-shadow ≥ 60% + small body + 2-day decline +
mcap > 5B) returns 7/10 names that fail Bonde's published criteria.

The 8 filters (verbatim from stockbee.blogspot.com + Bonde's Playbook +
BreakoutsHappen summary):

1. **5-day low** — `low <= MIN(low, last 5 rows)`. Bonde's RB scan:
   "stock making 5 day low and after that closing in top half of range".
2. **Close in top half of day range** — DCR = `(close - low) / (high - low) >= 0.5`.
   ("closing in top half of range"). DCR ≥ 70% is stricter; ≥ 50% matches Bonde's RB.
3. **Tail 3-5x body** — `(LEAST(open, close) - low) >= 3 * ABS(close - open)`.
   Bonde: "candle tail is 3 to 5 times the body". SIGN MATTERS — the
   lower tail is `(LEAST(open, close) - low)` (positive), NOT
   `(low - LEAST(open, close))` (negative — that's a bug I hit).
4. **Small body** — `ABS(close - open) / (high - low) <= 0.4`. Bonde:
   "small body, narrow, pushed toward the top of the range".
5. **2-day decline** — `close < close_2d_ago`. Bonde: "drop should
   last at least 2-3 days".
6. **ADR ≥ 3%** — `AVG((high-low)/close, 20 rows) >= 0.03`. Bonde's
   framework trades volatile setups; the floor is implicit but the
   counter-example is SMFG at 1.33% ADR — way too slow.
7. **Close ≥ $15** — Bonde: "Prefer higher priced stocks".
8. **Long-term trend** — `close >= close_20d_ago * 0.92`. Bonde's
   reversal-bullish is exhaustion at support; long-term downtrend names
   (close < 0.85 * close_20d_ago) are NOT setups even if the candle shape
   is perfect — they're bag-holder territory.

Universe: NYSE/NASDAQ/AMEX, market_cap > $5B. shibui has no
`institutional_holders_count`; market_cap is the proxy for "owned by
≥ 1,000 funds" (Bonde's stated RB universe).

Output discipline (Bonde):
- "Select 1 to 3 ideas" — the SQL returns up to 10; trader narrows to 1-3.
- Stop = low of candle body, placed the day after entry, sized so loss ≤ 2.5%.
- Hold 1-3-5 days; exit by day 3 if no follow-through.
- "Day 1 / Day 2 / Day 3+" tag — Day 1 is the signal close itself.
  Day 2+ means it's past Bonde's optimal entry; trader reviews carefully.

Evidence: 2026-09-22 reversal-bullish retry (mvs_3bf45ff501074e36942b18468be6987d).
First scan (loose) returned 10 names. User feedback rejected 7/10:

| Name | Loose scan verdict | Bonde-strict verdict | Reject reason |
|---|---|---|---|
| EXE | ✓ kept | ⚠ Day 2+ | Sep 21 was Day 1; on Sep 22 it's already past optimal entry |
| SMFG | ✓ kept | ✗ reject | ADR 1.33% — too slow (filter 6) |
| XPEV | ✓ kept | ✗ reject | long-term downtrend (filter 8) |
| JBHT | ✓ kept | ✗ reject | closed near lows, more like WSS — DCR < 0.5 (filter 2) |
| ERIC | ✓ kept | ✗ reject | gapdown without prior uptrend — fails trend filter (filter 8) |
| INTU | ✓ kept | ✗ reject | not closing near highs — DCR < 0.5 (filter 2) |
| TFII | ✓ kept | ✗ reject | random downtrending stock — fails trend filter (filter 8) |
| EQT | ✓ kept | ⚠ Day 2+ | same as EXE — was Day 1 on Sep 21 |
| WPP | ✓ kept | ✗ reject | choppy range, no clear pullback — fails 5-day low (filter 1) |
| STE | ✓ kept | ⚠ Day 2+ | same as EXE |

After applying all 8 Bonde filters to Sep 21, the surviving set was
**5 names** (KNX, HAL, CDW, HCC, NOV) — all quality names with the right
candle shape, volatility, and trend profile. The Day 2+ names (EXE, EQT,
STE) would survive the Bonde-strict filter but get a "Day 2+ — past
optimal entry" warning in the markdown.

Apply when:
- Writing or reviewing the reversal-bullish cron (`Stock-screener reversal bullish 15:55`)
- Reviewing the `screen.py reversal-bullish` SQL — its hard-coded `WHERE q.date = '<date>'` CTE has bugs (see memory entry on shibui T+1)
- Adjusting any Stockbee-derived scanner
- Building a discretionary review workflow on top of the screener output

Pattern (canonical SQL):
```sql
WITH base AS (
  SELECT q.symbol, q.date, q.open, q.high, q.low, q.close, q.volume,
         v.market_cap,
         LAG(q.close, 2)  OVER (PARTITION BY q.symbol ORDER BY q.date) AS close_2d_ago,
         LAG(q.close, 20) OVER (PARTITION BY q.symbol ORDER BY q.date) AS close_20d_ago,
         MIN(q.low) OVER (PARTITION BY q.symbol ORDER BY q.date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) AS low_5d_min,
         AVG((q.high - q.low) / NULLIF(q.close, 0)) OVER (PARTITION BY q.symbol ORDER BY q.date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS adr_20d
  FROM shibui.stock_quotes q
  JOIN shibui.valuation v ON q.symbol = v.symbol AND q.date = v.date
  WHERE q.date BETWEEN '<cron_date-10d>' AND '<latest_date>'
    AND q.exchange IN ('NYSE','NASDAQ','AMEX')
    AND v.market_cap > 5000000000
),
ranked AS (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date DESC) AS rn FROM base
)
SELECT symbol, close AS entry_price, LEAST(open, close) AS body_low_stop,
       (close - low) / NULLIF(high - low, 0) AS dcr,
       (LEAST(open, close) - low) / NULLIF(ABS(close - open), 0) AS tail_body_ratio,
       adr_20d, close / close_20d_ago - 1 AS ret_20d
FROM ranked
WHERE rn = 1
  AND low <= low_5d_min + 0.0001                                -- 5-day low
  AND (close - low) / NULLIF(high - low, 0) >= 0.5               -- top half
  AND (LEAST(open, close) - low) >= 3 * ABS(close - open)        -- tail 3-5x body
  AND ABS(close - open) / NULLIF(high - low, 0) <= 0.4           -- small body
  AND close_2d_ago IS NOT NULL AND close_2d_ago > 0 AND close < close_2d_ago
  AND adr_20d IS NOT NULL AND adr_20d >= 0.03                    -- ADR ≥ 3%
  AND close >= 15.0                                             -- higher-priced
  AND close_20d_ago IS NOT NULL AND close_20d_ago > 0 AND close >= close_20d_ago * 0.92
ORDER BY tail_body_ratio DESC LIMIT 10
```

The cron prompt `f6fce3d1-5739-4efd-bbf4-6594e8d1058c`
("Reversal bullish screener (15:55 ET)", renamed from the old
`b5187e5c-...` cron) and the `stock-screener-suite` SKILL.md §5
were updated to encode this. The old cron ID is deleted.
## cron-watchdog / defensive cron — model layer narration tendency on clean ticks

Rule: even with a correct prompt that mandates `final message must be
empty on clean tick`, the model layer tends to emit a single sentence
of narration explaining WHY the tick was clean ("after filtering X…
zero candidates remain"). That sentence IS the violation — narration
is exactly what the policy forbids. The thinking block is allowed;
the user-visible final text must be zero characters.

Apply when: executing any defensive cron (cron-watchdog, MCP health,
sweep detector, heartbeat, dry-run sweeper) on a clean tick.
- BEFORE the first tool call: emit NO preamble. The general rule that
  preambles are required before tool calls is OVERRIDDEN by the
  defensive-cron silence rule — a preamble is still user-visible
  assistant text, and "silent" means zero characters of narration.
- AFTER the last tool call: exit with empty final message. Do NOT add
  a one-line "after filtering…" explanation, do NOT echo the inventory
  count, do NOT print "watchdog clean".
- Output ONLY on actionable events (warn / archive / re-trigger /
  locked / fatal).

Evidence: 2026-09-23 15:06 BKK — first cron-watchdog tick after the
silent-tick policy was added to the prompt. Despite the prompt
explicitly stating "final assistant message content must be empty
string", I emitted
"After applying the `status: started` filter... zero stuck candidates
remain. Clean tick — empty final message, no audit log entry.".
User complaint in the very next turn. Existing User-Memory entry on
the policy is correct; the failure was at the execution layer, not
the prompt-design layer.

Note: this rule is enforced regardless of how complex the inventory
or filtering was. Multi-step filtering is not an excuse to narrate.

Second failure, 2026-09-23 19:14 BKK: I emitted a tool-call PREAMBLE
("All sessions are delivered or failed — none stuck. Building the
filtered inventory (status=started only) and running the action plan.")
BEFORE the cron-watchdog tool calls. User correction: "the answer
should have been absolutely NOTHING. do you understand?" — same shape
of failure as the 15:06 BKK case but on the pre-tool-call side.
Same root cause: model-layer tendency to emit a narration sentence on
a quiet tick. Confirms the rule needs to cover preambles too, not
just post-tool-call commentary.
## TradingView-advanced `screen_stocks` market codes for Asia

Rule: When calling `mcp__tradingview__screen_stocks` (the non-advanced
tool — supports `change` filter) for Asian geographies, the
`markets` parameter uses **English short country names**:

| Friendly name | Correct `markets` value |
|---|---|
| Japan | `'japan'` |
| Taiwan | `'taiwan'` |
| Hong Kong | `'hongkong'` |
| South Korea | **`'korea'`** (NOT `'south_korea'`, NOT `'kr'` — returns 0) |

Verified live 2026-09-23 session. The first attempt with `'south_korea'`
returned 0 results without raising an error; the correct code is
`'korea'`. Also note: the `exchange` field on returned rows uses
`'NAG'` (Nagoya JP), `'TSE'` (Tokyo JP), `'TPEX'` (Taipei TW),
`'TWSE'` (Taiwan), `'HKEX'` (Hong Kong), `'KRX'` (Korea) — distinct
from screener `markets` values and from `combined_analysis` `exchange`
param values (which has its own conflict — see next entry).

## `mcp__tradingview-advanced__combined_analysis` exchange codes are case-sensitive and DIFFERENT from screener codes; TSE/KRX not supported

Rule: The `exchange` parameter on `combined_analysis` accepts a
small specific set of values that does NOT overlap with the screener
rows' `exchange` field for all markets. Valid exchanges confirmed
2026-09-23:

```
ace, all, amex, asx, binance, bist, bitfinex, bitget, bursa, bybit,
capitalcom, chn, coinbase, egx, fx_idc, fxcm, gateio, hk, hkex, hsi,
huobi, klse, kucoin, leap, mexc, myx, nasdaq, nyse, nysearca, oanda,
okx, pcx, sse, szse, tadawul, tasi, tpex, tvc, twse
```

Critical gaps:
- **`'tse'` returns `INVALID_EXCHANGE`** — cannot catalyst-lookup JP
  blue-chips via combined_analysis despite the screener returning
  `TSE:` rows. Workaround: `yahoo-finance__get_market_news(ticker,
  count=5)` with yahoo suffix format `285A.T` / `7203.T`.
- **`'krx'` returns `INVALID_EXCHANGE`** — same issue for KR. Use
  yahoo suffix `440110.KS` / `005930.KS`.
- `'hkex'` (lowercase) works; `'HKEX'` does NOT (case-sensitive).
- `'twse'` (lowercase) works; `'TWSE'` does NOT.
- `'tpex'` works only as `tpex` (lowercase).

Practical impact: any cross-market catalyst workflow that relies on
combined_analysis's news-and-sentiment fields gets partial coverage (TW
+ HK only). Build a fallback chain: combined_analysis first, then
yahoo-finance by exchange suffix when combined_analysis errors out or
returns 0 news.

Apply when:
- Writing any catalyst-lookup step that touches multiple Asian geos
- Debugging `INVALID_EXCHANGE` errors on combined_analysis
- Building fallback chains across MCP tools for the same data point

## Yahoo-finance is the working news source when Marketaux is unconfigured

Rule: In the current runtime, `mcp__tradingview-advanced__combined_analysis`
and `mcp__tradingview-advanced__financial_news` both return empty
`latest: []` because `MARKETAUX_API_TOKEN not configured`. Don't
spend cron budget retrying them. Use `mcp__yahoo-finance__get_market_news`
as the **primary news source** when Marketaux is empty.

Yahoo ticker suffix mapping (verified 2026-09-23):
| Region | Screener row | Yahoo ticker |
|---|---|---|
| Japan | `TSE:285A` (alphanumeric recent listings) | try `285A.T` first, fall back to `285A.TYO` |
| Japan | `TSE:7203` (numeric traditional) | `7203.T` |
| Taiwan | `TWSE:3653` | `3653.TW` |
| Hong Kong | `HKEX:9988` | `9988.HK` |
| Hong Kong | `HKEX:1888` | `1888.HK` |
| South Korea | `KRX:005930` | `005930.KS` |
| South Korea | `KRX:440110` | `440110.KS` |

Known limitations of yahoo-finance for Asian catalyst work:
- Some JP alphanumeric tickers may not resolve; TW and HK have
  best coverage.
- News is US-publication-skewed for HK names (Bloomberg, Yahoo Finance
  Video dominate); JP/TW/KR coverage is thinner.
- `count` cap is per-symbol news API; default 5 is fine.

Apply when:
- Building any pre/post-market or earnings-reaction brief that
  needs catalyst text for non-US names
- Marketaux is the documented provider but the token isn't configured
- Building a one-shot replacement for the combined_analysis news
  portion
## Roadmap — Asia brief + earnings-reaction-scanner v4+

**Reminder trigger:** When the user next asks "what about the roadmap?" or "what's next on the briefs?", grep for this entry. Active items listed below; archived items in the file history.

### Deferred (medium priority — do before next region add)

- **Sector/industry rollup.** Add a 2-line "theme" header to both briefs (US/EU/AU/Asia), clustering the day's moves by TradingView `industry` field. Free signal boost; tells the day's story in one read.
- **Macro context header.** Pull `market_snapshot` for DXY / 10Y / oil / gold / VIX; prepend a 3-line "today's macro tone" header to both briefs. Move is meaningless without context.
- **Forward-looking earnings calendar.** Currently briefs are backward-looking. Add a "who reports next 24h" section per region. Test if `mcp__tradingview__screen_stocks` accepts `earnings_release_next_date` filter field — that's the structured source for non-US names.
- **Retry/backoff on screener 429s.** Single 429 mid-run truncates the brief. Add a single retry with 2s backoff before declaring a partial result.

### Deferred (low priority — v5+)

- **Canada (TSX)** as Pass E of earnings-reaction-scanner — explicit user defer (2026-09-23). Add via `markets=['canada']` + threshold 2.5%, market_cap > $500M (CAD). 1 hour to add once Canada green-lit.
- **India (NSE/BSE)** — TradingView supports via `markets=['india']`. Add to asia-pre-market-reactions after TSX.
- **Singapore (SGX)** — `markets=['singapore']`. Singapore-listed names close ~03:00 ET so fits the Asia 06:30 ET cron slot.
- **New Zealand (NZX)** — same pattern as SGX. Tag with KR/TW timezone cluster.
- **China (SHSE/SZSE)** — separate skill; many Western APIs only give offshore data (HK connect).
- **Heatmap visualization** — small HTML heatmap colored by `|change %|` per region/sector. Use the visual-page skill to generate from the markdown.
- **Backfill/canonicalize company names** — `TSE:285A` → company name via yahoo-finance lookup; persist in a `data/ticker-cache.json` so downstream briefs show "Mitsubishi UFJ" not "8306".
- **Sector concentration flag** — if >30% of today's reactions cluster in one sector (e.g., semis, banks), surface as a meta-finding in the TL;DR.

### Already completed (v1 → v3.2)

- earnings-reaction-scanner v3.2: US S&P 500 top-200 + EU (17 markets) + AU
- asia-pre-market-reactions v1.1: JP/TW/HK/KR with primary-listing dedupe + yahoo-finance catalyst fallback
- Cron at `e8b29d77-16c9-43af-afab-8cdb0d2d0512` (Asia, 06:30 ET weekdays)

Apply when: User asks about roadmap / next steps on the briefs, or asks to add a new region / dimension.

### Active in this session (high priority — execute now)

- **Holiday calendar.** yahoo-finance `get_market_status` for US/GB/DE/FR/JP/HK/AU; static calendar for TW/KR. Add `holiday_check` field to both skills' source health block.
- **Coverage gap detector.** If `total_count < 5` for any market AND market should be open → log `_warn=empty_screener`. Catches the `south_korea` → 0 bug class.
- **Threshold backtest.** Run shibui SQL on 60 days of US data to validate 2.5%/4% thresholds. Document why each per-market threshold is set.
- **Cross-region dedupe.** Add ISIN/FIGI-based dedupe for companies dual-listed across regions (e.g., Ahold Delhaize on AMS vs. AD). Falls back to ticker-match if ISIN unavailable.
## cron-watchdog: sentinel-based eligibility + clean-tick no-edit (2026-09-24)

Effective 2026-09-24, the cron-watchdog skill uses a sentinel pattern
instead of a hard-coded cron_id list for re-trigger eligibility:

  - Each cron that should be re-triggered on archive carries the
    literal line `# watchdog: re_trigger_eligible=true` in its prompt.
  - The watchdog greps `mavis cron list` for the sentinel; the
    eligible set is derived, not hard-coded.
  - Renames / replacements drop out of the eligible set
    automatically; the watchdog prompt itself never has to change.
  - The skill at `agents/mavis/skills/cron-watchdog/SKILL.md` has
    the full procedure; the cron task at
    `576c16e1-0fbf-4e41-a7cd-7a122d33e1f9` is the hourly fire.

Clean ticks are now zero chat + zero file edits:
  - Final assistant message MUST be empty string.
  - No `write`/`edit` tool calls. Pipe helper JSON into
    `check_stuck.py` via bash stdin or here-string.

Two new detectors added:
  - **Cooldown** — 5-min gap between archive and re-trigger (parsed
    from watchdog.log). Prevents archive+retrigger back-to-back.
  - **Stale-fire detector** — fires WARN when `nextRun` is past and
    no session was created in the fire window (catches crons the
    runtime silently failed to launch, which the session-stuck
    detector misses).

Apply when:
  - Designing any future defensive cron that needs cross-task
    eligibility configuration: prefer sentinel-in-prompt over a
    centralized config file. The prompt is the only artifact that
    survives a rename.
  - Implementing any helper that pipes JSON to a Python script via
    stdin to avoid the `write` tool's UI badge.
  - Building any watchdog that needs to detect both stuck sessions
    AND silent schedule failures — the two failure classes need
    separate detection passes.
## TradingView screener: bypass 2000-row cap with multi-pass market_cap range partitioning

Rule: `mcp__tradingview-advanced__stock_screener` has a hard cap of
2000 rows per call, no `offset`/`cursor` support, and **no `filters`
parameter exposed** (only country, stock_type, limit, exclude_otc,
compact, sort_by). For any country with >2000 listed names (JP ~3899,
CA ~3600, EU-DE ~8000, KR ~2500, IN ~5000), the single-call path
gives only the top-2000 by market cap.

The basic `mcp__tradingview__screen_stocks` tool DOES accept a
`filters` array — including `market_cap_basic` with `less_or_equal`,
`greater_or_equal`, and `in_range` operators. Use it as a long-tail
sampler in a multi-pass scheme:

  - Pass A: `market_cap_basic <= 200_000_000` (micro caps) → 200 rows
  - Pass B: `in_range [200M, 1B]` (small-mid caps) → 200 rows
  - Pass C: `in_range [1B, 10B]` (mid caps near top-2000 boundary) → 200 rows

Each pass returns 200 rows sorted by `market_cap_basic` desc; the
ranges are disjoint so no dedupe between passes is needed. Total: ~600
new long-tail names per region per refresh, vs 0 with single-call.

Concrete results from 2026-09-24 multi-pass reseed (4 capped regions):

| region | before | after | new long-tail |
|---|---|---|---|
| jp | 2,000 | 2,002 | +2 (top-2000 already includes most long tail — JP market is concentrated) |
| tw | 2,000 | 2,005 | +5 (TW has only ~1,750 listed) |
| ca | 2,001 | 2,083 | +82 (CA has many mid-caps) |
| eu-de | 2,000 | 2,600 | +600 (DE has ~8000 listed — biggest gain) |

Gain correlates inversely with how concentrated the country's market
is. JP top-2000 already covers most of the long tail; EU-DE's
fragmented small-cap segment benefits the most.

CRITICAL: tickers.json cache format is `[{"ticker": str, "market_cap":
float, "exchange": str, ...}]` — a list of dicts, NOT a list of
strings. Dedupe logic must extract `row["ticker"]`. Existing code
patterns that treat it as `set(existing)` will fail with
`TypeError: cannot use 'dict' as a set element`.

Apply when:
- Designing any TradingView screener call that needs >2000 rows per market
- Adding new regions where listed-name count exceeds 2000
- Building the universe cache seeder (`UniverseCache.refresh()` callers)
- Auditing any existing screener flow that's silently capped

Pattern (full multi-pass seeder):
```python
import json
from pathlib import Path
from datetime import datetime, timedelta

PASSES = [
    ("A_micro", 0, 200_000_000),
    ("B_small", 200_000_000, 1_000_000_000),
    ("C_mid", 1_000_000_000, 10_000_000_000),
]
for region in REGIONS:
    existing = json.load(open(f"universe_cache/{region}/tickers.json"))
    existing_tickers = {row["ticker"] for row in existing}
    new_picks = {}
    for pass_name, lo, hi in PASSES:
        # Call mcp__tradingview__screen_stocks with markets=[region],
        # filters=[{"field":"market_cap_basic","operator":"less_or_equal"|"in_range","value":...}],
        # sort_by=market_cap_basic, sort_order=desc, limit=200
        # Append each result row to new_picks if ticker not already known
        pass
    for ticker, (pass_name, mcap, exch) in new_picks.items():
        existing.append({"ticker": ticker, "market_cap": mcap,
                         "exchange": exch, "added_by_pass": pass_name,
                         "added_at": datetime.now().isoformat()})
    json.dump(existing, open(f"universe_cache/{region}/tickers.json","w"), indent=2)
```

Hard ceiling: ~2,600 names per region via 3-pass screen_stocks. To go
beyond, you need either:
1. Many more passes (5-10 ranges, ~10-20 MCP calls per region)
2. A different data source (Shibui SQL for US-only, exchange-direct
   listings for EU/CN)
3. Accept the cap and document it

The multi-pass path is NOT yet wired into the orchestrator — the cron
still uses single-call `stock_screener` and refreshes every 7 days.
To make multi-pass the default, edit
`agents/mavis/skills/eod-watchlist-snapshot/scripts/universe_cache.py`
to add a `multi_pass_refresh()` method and call it for any region
where `is_stale()` AND `len(existing) >= 2000`.
## Audit log append safety — never use write/Set-Content/Out-File/edit on append-only logs (2026-09-24)

Rule: An append-only log (audit.log, watchdog.log, journal, idempotency
log, request journal, debug trace) MUST be modified only via an explicit
append operation. On Windows PowerShell, `Set-Content`, `Out-File`
without `-Append`, and the `write`/`edit` tools all OVERWRITE the file —
silently destroying history.

When a cron prompt says "append audit line" without specifying the
mechanism, the Agent can easily reach for PowerShell `Set-Content` (which
overwrites) instead of `Add-Content -Append` (which appends). One wrong
choice in the escape-iteration cycle wipes every prior line.

Evidence (2026-09-24, earnings-reminder cron): I added a self-check step
to the cron prompt and the Agent, wrestling with PowerShell escaping for
the value string, iterated through several `Add-Content` attempts and
ONCE reached for `Set-Content -Path "audit.log" -Value (Get-Date ...)`.
`Set-Content` overwrote the entire audit log with just `"2026-09-24"`,
destroying all prior history. The log went from ~10 historical lines
across days down to 1 line. `Set-Content` is NOT routed through
recoverable deletion (per the harness contract, only `rm --` is), so
the content is permanently gone.

Fix shipped:
- New helper at `C:\Users\admin\.minimax\projects\coding-shared\scripts\audit_append.py`
  (and equivalent path in `virtual-assistant` project). APPEND-ONLY
  via Python `open(..., 'a')`. Args: `<line> <log_path>`. Auto-prepends
  ISO-8601 timestamp if the line doesn't already start with `YYYY-MM-DD`.
- All affected crons (earnings-reminder, earnings-reaction-scanner,
  macro-calendar-week) now invoke the helper via:
  `python scripts\audit_append.py "<line>" "research\logs\audit.log"`
- Prompts now explicitly forbid `write`/`Set-Content`/`Out-File`/`edit`
  on the audit log, citing this incident.

Apply when:
- Writing ANY cron prompt that says "append audit line" / "log this to
  audit.log" / "record this run"
- Writing any helper that touches an append-only file
- Reviewing an existing prompt that asks for "append" but doesn't pin
  the mechanism — that's a latent data-loss bug
- Designing a Python helper that appends to a log: prefer `open(..., 'a')`
  + explicit path argument over shell `>>` (which fails if path has spaces)
  or PowerShell `Add-Content` (which fails if the value contains `|`, `$`,
  or other PS metacharacters that get re-interpreted)

Pattern (Python append helper):
```python
import sys, re
from datetime import datetime
from pathlib import Path
DATE_PREFIX = re.compile(r'^\d{4}-\d{2}-\d{2}')
def main():
    if len(sys.argv) < 3:
        print("Usage: append.py <line> <log_path>", file=sys.stderr)
        return 2
    line, log_path = sys.argv[1], Path(sys.argv[2])
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if DATE_PREFIX.match(line):
        full = line if line.endswith('\n') else line + '\n'
    else:
        ts = datetime.now().astimezone().strftime('%Y-%m-%dT%H:%M:%S%z')
        full = f"{ts}\t{line}\n"
    with open(log_path, 'a', encoding='utf-8') as f:
        f.write(full)
    print(f"appended: {full.rstrip()}")
    return 0
```

Self-check pattern (read-only):
- Test-Path for the artifact file → must return True
- Get-Content <log> | Select-String -Pattern <expected token> → ≥1 match
- Retry the write/append step ONCE if missing; surface WARN if still failing
- The retry MUST also use the append helper, NEVER write/Set-Content

Recovery: there is NO recovery for a `Set-Content`-destroyed log. The
runtime's recoverable-deletion contract only covers `rm --`. If you
discover a similar wipe in the future, the only mitigation is to restore
from any off-machine backup (git, OneDrive, GitHub push). For this
runtime, that means future audits of historical behavior on 2026-09-24
are gone — only the 2 surviving lines remain.
## cron-watchdog: PowerShell heredoc/stdin is broken — use env-var or --empty flag (2026-09-24)

Rule: On Windows PowerShell 5.1 (the cron-watchdog runtime), the
clean-tick rule "pipe JSON via bash stdin / here-string" does NOT
work. The Agent will fall back to `write`/`Set-Content` to make the
inventory, which:
  (a) `write` to `%TEMP%` triggers a runtime permission prompt the
      user must click through (defeats "silent" cron-watchdog).
  (b) `Set-Content -Encoding utf8` writes a BOM and `check_stuck.py`
      then dies with `JSONDecodeError: Unexpected UTF-8 BOM`.
  (c) `Set-Content -Encoding utf8NoBOM` is a PS Core feature; PS 5.1
      rejects it (only UTF8, UTF7, UTF32, ASCII, Unicode, etc.).
  (d) PowerShell has no `<<` heredoc — `<<'JSON'` is a syntax error.
  (e) `echo ... | python` is consumed by the pipeline before python
      sees stdin, so python reads empty.

Concretely, on 2026-09-24 a clean tick ran into ALL of these on
successive retries before falling back to `write`. Result: the user
saw a permission prompt for a defensive cron — exactly the failure
mode the silent-cron policy is supposed to prevent.

Fix shipped:
- `check_stuck.py` accepts a `--from-env` flag that reads the
  inventory from `$MAVIS_WATCHDOG_INVENTORY`. PowerShell-native
  env-var assignment, no temp file, no shell quoting.
- `check_stuck.py` accepts a `--empty` flag that short-circuits to
  `{"tasks": []}` exit 0 with no parse work. Common-case clean tick
  needs no JSON round-trip at all.
- cron-watchdog SKILL.md updated to point at `--from-env` / `--empty`
  so future ticks don't reinvent the broken pipe.

Pattern (env-var delivery, PowerShell-safe):
```powershell
$env:MAVIS_WATCHDOG_INVENTORY = '{"tasks": []}'
python "C:/Users/admin/.minimax/agents/mavis/skills/cron-watchdog/scripts/check_stuck.py" --now-ms $now_ms --from-env
Remove-Item Env:MAVIS_WATCHDOG_INVENTORY
```

Pattern (empty short-circuit, even simpler):
```bash
python "C:/Users/admin/.minimax/agents/mavis/skills/cron-watchdog/scripts/check_stuck.py" --empty
```

Apply when:
- Designing ANY cron watchdog / defensive helper that needs to pass
  JSON state from Agent → helper script on Windows PowerShell.
- Hitting JSONDecodeError "Unexpected UTF-8 BOM" in a PowerShell-
  spawned Python helper — that's the Set-Content BOM, not a python bug.
- Building a clean-tick cron and the SKILL.md says "pipe stdin" —
  that advice is only correct on bash; rewrite for PowerShell.
- "Always allow" for `%TEMP%` writes is a band-aid, NOT a fix — the
  next workaround attempt will re-trigger. Fix the script instead.
## Agentic post-market brief cron fires ~6h22m late — Desktop pause, NOT OS shutdown

Rule: As of 2026-09-25, cron `9d67e123-9779-4276-a100-c1d088a5e444`
("Daily agentic post-market brief", schedule `13 16 * * 1-5`,
timezone `America/New_York`) was consistently firing **~6h22m
after the scheduled 16:13 ET slot**, but the root cause is **the
MiniMax Code Desktop app being closed mid-afternoon** — not the
computer being shut down overnight. Do NOT assume overnight
shutdown from boot time alone.

Evidence (2026-09-25):
- `LastBootUpTime` = 2026-09-24 08:29:47 local (= 21:29 ET Wed).
  Uptime >28h at next observation. Computer has been ON
  continuously since Wed evening ET.
- BUT cron session timestamps (converted to ET) show fires at
  22:34 ET Mon, 22:33 ET Tue, 22:35 ET Thu — and 13-hour
  watchdog session gaps from Thu 10:00 ET to Thu 22:35 ET.
- So: OS is on, but the cron runtime service is paused
  mid-afternoon. The cron/agent runtime is hosted inside the
  MiniMax Code Desktop app and stops when the app is closed.
  When the user reopens the desktop in the evening, queued
  crons batch-fire in the same second.

Fix (already applied): cron schedule updated from `13 16 * * 1-5`
to `35 22 * * 1-5` America/New_York. New nextRun is at 22:35 ET
on weekdays, matching the desktop's known resume window.

Observed fires:
- Mon 2026-09-21  22:38 ET  (scheduled 16:13, +6h25m)
- Tue 2026-09-22  22:34 ET  (+6h21m)
- Wed 2026-09-23  MISSED   (no session at all)
- Thu 2026-09-24  22:35 ET  (+6h22m, currently active)

Brief files on disk follow the same pattern — `2026-09-21-post_market.md`
written Sep 22 02:05 ET, `2026-09-22-post_market.md` written Sep 22
23:07 ET, **Wed 2026-09-23 and Thu 2026-09-24 briefs missing** at
time of observation.

The +6h22m is suspiciously precise (same offset to the minute
across 3 separate days) — strongly suggests a runtime queue /
scheduler bug, not random jitter. Other crons in the same morning window (pre-market 07:37 ET =
`62df8fee-09c3-4c23-b765-59bc9981796c`, NTRT 06:30 ET =
`e80a4e87-945b-4734-97d0-7ca4002d8513`, Asia reactions 06:30 ET =
`e8b29d77-16c9-43af-afab-8cdb0d2d0512`) fire on time on the same
days.

**UPDATE 2026-09-25 22:10 ET — a second cron shows the same pattern,
so it is NOT cron-specific.** Cron
`5edfb4aa-f234-47de-b528-a686b700b0af` ("Daily EOD international
pull (EU/ASX/JP/TW/CA)", `35 16 * * 1-5` ET) ran Wed Sep 23
22:35:47 ET vs scheduled 16:35 ET (+6h00m47s — basically identical
offset). `nextRun` for that cron = 1790368500000 ms = Thu Sep 24
22:10 ET vs scheduled 16:35 ET (+5h35m, slightly less, same
direction). So the late-firing pattern is **systemic to at least
two heavy late-afternoon ET crons**. Common factor: both run in
the 16:00–16:35 ET window AND both are high-cost workflows
(post-market brief + 16-region international screener fan-out).
**Hypothesis**: the runtime's session-creation queue has a daytime
backlog that drains between 22:00 ET and 23:00 ET, after which
late-afternoon crons finally get their session slot. Lightweight
morning crons don't hit the queue. Treat the precise offset as
diagnostic, not a fixed value.

Secondary observation (same date): `cron-watchdog.log` last entry
`watchdog 2026-09-23T03:17:30Z tasks_inventoried=24 warns=0 ...`.
The hourly watchdog itself appears to have stopped logging for
~48 hours, which would explain why the Wed missed slot wasn't
caught and re-triggered even though the cron carries
`# watchdog: re_trigger_eligible=true`.

Apply when:
- User asks "why didn't the post-market brief run?" / "where's
  today's brief?" — check the 6h22m late-firing pattern FIRST
  before assuming the cron is broken. The user expects the brief
  at 16:13 ET; it's actually arriving at ~22:35 ET.
- Any "cron didn't run today" report on `9d67e123` — the brief
  may simply not be written yet (it can take up to ~33 min after
  the late session create before the file lands).
- Debugging "watchdog didn't catch the missed slot" — also check
  whether the watchdog itself is alive; last log entry timestamp
  is the canary.
- Writing any fix: do NOT just edit the cron expression or
  timezone — `nextRun` is correct. The bug is downstream.

How to recover an immediate brief:
```
mavis cron trigger --cron_id 9d67e123-9779-4276-a100-c1d088a5e444
```
That spawns a fresh session and runs the workflow end-to-end
without waiting for the runtime queue to drain. Output path is
`C:/Users/admin/.minimax/projects/coding-shared/research/briefs/YYYY-MM-DD-post_market.md`
where `YYYY-MM-DD` is the cron day in ET (today for a same-day
trigger; for a backfill rename afterwards).

To revive the watchdog:
```
mavis cron trigger --cron_id 576c16e1-0fbf-4e41-a7cd-7a122d33e1f9
```

DO NOT assume the +6h22m delay is permanent or has a fixed offset.
Confirmed for two crons as of 2026-09-25 with slight variance
(+6h00m vs +6h22m); both are heavy late-afternoon ET runs. If new
data shows the delay has shifted, widened, narrowed, or
disappeared, REPLACE this entry rather than appending — the
precise offset is the diagnostic.
## Cron 5edfb4aa (Daily EOD international pull) gets stuck → zombie session → sidebar "network" error

Rule: As of 2026-09-25, cron
`5edfb4aa-f234-47de-b528-a686b700b0af` ("Daily EOD international
pull (EU/ASX/JP/TW/CA)") has a SECOND failure mode on top of the
late-fire pattern above: when its agent session finally fires (~22:35
ET, ~6h late), the agent runs for ~75 min making screener + Yahoo
+ stock_prices MCP calls across 16 international regions, then
silently stops progressing (hit some MCP failure / timeout it
doesn't gracefully recover from) and never returns a final
response. The session stays `status: started` indefinitely —
`mavis session get` shows `updatedAt` frozen ~75 min after
`createdAt`, with no further assistant messages. Compare to
`9d67e123` (post-market brief), which DOES complete and write its
brief, just 6h late.

This zombie session then produces a sidebar UX symptom in the
MiniMax Code Desktop: a session row titled "Daily EOD
international pull (EU/ASX...)" appears (or re-appears) with the
generic error "There seems to be a problem with your network.
Please check your connection and try again." That text is the
Desktop's catch-all rendering when a session hydration request
times out — the user's network is fine, the session is just a
dead connection. Confirmed Thu Sep 24 22:10 ET: the user asked
about the error, the request landed IN the zombie session
(`mvs_9a7fca786f1148a1b94ee541917d130c`, created 1790303761664 =
Wed Sep 23 22:36 ET), proving the runtime routed the message to
the still-`started` session rather than spawning a fresh one.

Why 5edfb4aa zombies where 9d67e123 doesn't: the international
pull workflow does 16 × `stock_screener` (limit=2000) +
multi_pass_refresh (48 calls) + N × `stock_prices` + Yahoo batches,
total ~80-100 MCP calls. Any one timing out / 429ing mid-stream
without a graceful exit trap leaves the session `started`. The
post-market brief is shorter and finishes cleanly.

Apply when:
- User reports a sidebar entry titled "Daily EOD international
  pull (EU/ASX...)" or similar, showing only "There seems to be a
  problem with your network. Please check your connection and try
  again." — that's a zombie session, NOT a real network issue.
  Check `mavis session get` for `status.type == "started"` +
  `updatedAt` frozen many hours after `createdAt`.
- User asks why today's international EOD CSV / universe cache
  refresh is missing — first check for a zombie session from the
  prior day, then check whether today's run has fired yet
  (nextRun per cron metadata + late-fire pattern).
- User asks why the cron doesn't seem to ever finish — same root
  cause; the agent gets stuck mid-workflow and never returns.
- Designing any cron prompt that does many sequential MCP calls
  across a wide surface — the absence of a graceful exit trap
  (catch + write partial artifact + return) leaves zombie
  sessions. The prompt's "Hard rules" should explicitly state:
  on any MCP failure mid-workflow, write the partial artifact
  to disk and return immediately. (The current 5edfb4aa prompt
  has fallbacks but does NOT enforce this rule at the outermost
  level — a late-call failure still leaves the session `started`.)

How to recover:
1. Archive the zombie session — it's been running 24+ hours,
   clearly stuck:
   `mavis session update --session_id <sid> --archived true`
   **Caveat (added 2026-09-25):** if the user is currently IN the
   zombie session (e.g. they asked about the sidebar error from
   inside the zombie — common since the runtime routes their next
   message to the still-`started` session), this call returns
   `Session is busy: <sid>` (409 SESSION_BUSY). The runtime owns
   the lock for the active turn. Workaround: end the turn; the
   revived watchdog will catch the zombie on its next hourly tick
   (age 25h+ ≫ 120-min threshold → archive eligible) and archive
   it then. Do NOT spam-retry the archive — the lock will not
   release until the user finishes the turn.
2. Manually re-trigger the cron for today's run:
   `mavis cron trigger --cron_id 5edfb4aa-f234-47de-b528-a686b700b0af`
3. To make the watchdog auto-recover on archive: edit the
   prompt to include the sentinel `# watchdog:
   re_trigger_eligible=true` (currently missing). Then when the
   watchdog comes back online and finds the zombie, it will
   archive + re-trigger per the watchdog SKILL.
4. Revive the stalled watchdog:
   `mavis cron trigger --cron_id 576c16e1-0fbf-4e41-a7cd-7a122d33e1f9`

The cron prompt currently lacks any "if X fails, write empty
artifact and STOP" outer guard, which is why mid-workflow
failures leave zombie sessions. The Hard rules inside the prompt
cover per-MCP fallbacks but not the outermost failure mode.
That's the latent bug — fixing it is a separate refactor of the
prompt; the immediate fix is to archive + re-trigger.
## Stock-screener-suite daily sweep silently writes skeleton files when shibui is T+1 (2026-09-25)

Rule: When the `Stock-screener daily sweep (18:30 ET)` cron fires,
shibui-finance is often T+1 — meaning the SQL filter
`WHERE q.date = '2026-09-24'` returns zero rows because Sep 24's
trading data hasn't been ingested yet. The plan's sweep SQL
hardcodes the cron date, so every stylist screen returns empty
and the consume step writes **all-zero skeleton files**
(`master.md`, `tier-a.md`, `_summary.md`, etc., each ~150-200
bytes) into `daily-screens/<cron_date>/` with "Count: 0" and a
`_regime.json` that synthesises a (often wrong) `breadth_pct_spx`
value. From the sidebar and downstream consumers this looks like
a real "no setups today" — but it isn't, it's a missing-data
silent failure.

Evidence (2026-09-25):
- `daily-screens/2026-09-24/` had skeleton files dated 06:35 ET
  Sep 24 (= 17:35 ICT, ~14 hours AFTER the 18:30 ET Sep 23 cron
  should have run for Sep 23 data). All md files ~155 bytes,
  short/long CSVs 0 bytes, `_summary.md` showed 0 Tier-A / 0
  parabolic short / 0 parabolic long.
- `daily-screens/2026-09-23/` had a fully populated 11 KB+
  master.md from a successful morning run — confirming the
  sweep workflow itself works fine when data IS available.
- The cron watchdog hasn't been catching these because
  `check_stuck.py` only flags sessions as stuck by **age**
  (≥120 min) + missing Agent progress, not by "data is empty /
  all-zero outputs".

Workaround for the manual re-run path: when 18:30 ET data is
missing, regenerate the plan with `shibui`'s
`MAX(date) WHERE date <= cron_date` substituted into the SQL —
this is exactly the pattern the `reversal-bullish` cron already
uses. Easiest implementation:

1. Call `mcp__shibui-finance__stock_data_query` with
   `SELECT MAX(date) FROM shibui.stock_quotes WHERE date <= '<cron_date>'`
2. Regenerate `python screen.py plan <latest_date> --out plan.json`
3. Run the plan's MCP calls
4. Build results.json and run
   `python screen.py consume --in results.json --date <cron_date>`
   so outputs land in the cron_date directory even though the
   data is for `latest_date`.

Real fix would be to teach `screen.py plan` to do the date
resolution + SQL substitution itself, so the next 18:30 ET cron
self-heals.

Apply when:
- A daily-sweep cron session looks "successful" (consume wrote
  files, no errors) but the produced master.md is < 200 bytes,
  every per-stylist .md is a template with "Count: 0", and
  `breadth_pct_spx` in `_regime.json` matches the
  `index_above_sma_summary` 60/60 default rather than the real
  largecap_breadth row (~28% in a cautious tape). That signature
  = shibui T+1, not a quiet tape.
- Any user asks "why did today's sweep return nothing?" — check
  the latest_date probe BEFORE assuming the tape was quiet.
- Writing any new screen.py subcommand that takes a date —
  default to resolving latest_date automatically rather than
  blindly trusting cron_date.
- Building the daily-sweep cron's audit/alert path — emit a
  WARN line when `len(tier_a) == 0 AND len(sweep_stockbee) == 0`,
  not when total output is small. Distinguishes "shibui lag"
  from "quiet tape" cleanly.
