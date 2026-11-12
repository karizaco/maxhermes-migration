---
name: Agentic post-market brief
description: >-
  Generate the daily post-market brief: tomorrow's setup first, then the day's tape,
  sector rotation, after-hours movers with tradable levels, after-hours earnings
  reactions, and the open research queue. Runs on cron at 22:30 ET weekdays.
---

## Scheduled-run conversation title (FIRST ACTION)

If this session was started by a scheduled cron run — the first message begins with
`# Cloud Mavis cron:` — set this conversation's title before doing anything else. Every scheduled
run gets its own conversation; it is never appended to an earlier run's conversation.

1. Resolve today's date in US/Eastern: `TZ=America/New_York date +%d-%m` (day-month, no year).
2. Build the title: `[<DD-MM>] <NN>-<routine name>`. Take `<NN>` and `<routine name>` from the
   first line of that cron prompt (`# Cloud Mavis cron: <routine name> (cron #NN)`).
   Example: `[31-10] 12-cross-asset-correlation-snapshot`.
3. Set it with one call: `mcp_invoke` with tool_name `session_update` and arguments
   `{"session_id": "me", "title": "<the title>"}`. `me` means THIS conversation.
   If `mcp_invoke` reports that the tool is unknown, call `tool_search` with the query
   "session title update", then retry the same `mcp_invoke` call.
4. If the title cannot be set for any reason, carry on with the routine. This step must never
   block, delay, or fail the artifact.

If this session was NOT started by a scheduled cron run, ignore this section.

# Agentic post-market brief

Generates the daily post-market markdown brief. Companion to `agentic-pre-market-brief`.

**This brief is named POST-MARKET because its job is to set up TOMORROW.** The session that just
closed is the raw material; tomorrow's setup is the product. §5 is the artifact contract and it
is not optional — read it before writing a single line.

## When

- Cron: `30 22 * * 1-5` America/New_York (weekdays, 22:30 ET — the evening post-market digest)
- Manual: user asks "give me today's post-market brief" or "run the post-market brief"

## Output

- `/workspace/daily-briefs/{date}-post-market.md` — the `{date}` is the fire's **scheduled** date
  in US/Eastern (`YYYY-MM-DD`), resolved from the run's `scheduled_at_ms`, not from the wall
  clock. The `## OUTPUT` block of the cron prompt names the path; in Cloud that is
  `/workspace/daily-briefs/{date}-post-market.md`.
- A compact summary in the reply / cron report, in the shape §5.8 requires.

## The data path (the Cloud runtime — there are no `mcp__*` finance tools here)

`mcp__tradingview__*`, `mcp__yahoo_finance__*` and friends are **not registered** on this
runtime. Do not call them and do not improvise their names. The three working paths are:

| Need | Path | Notes |
|---|---|---|
| Index / ETF / futures / cross-asset closes, movers, **daily history** | the MCP-over-HTTP bridge, pack `market-recap` (`_shared/mcp_bridge.py`) — tools `get_quotes`, `price_history`, `top_movers`, `market_snapshot` | keyless, Yahoo-sourced, not rate-limited. `price_history` takes up to 40 symbols and returns each session's close, previous close and `daily_return_pct` — that is the source for §5.6. |
| Breadth, universe, extended-hours prints | the **TradingView public scanner**, `POST https://scanner.tradingview.com/america/scan` | no auth. `market_cap_basic` is **USD** here. The `postmarket_*` columns carry the after-hours session: `postmarket_close`, `postmarket_high`, `postmarket_low`, `postmarket_volume`, `postmarket_change`. |
| The EOD universe (one population for the participation metrics) | cron #20's published CSV `us-eod/{fire_date}.csv` in `karizaco/minimax-cloud-outputs` (`main`) | 4,896 names with `change_pct`, `market_cap`, `sector`. Fetch it at run time. |
| Catalysts, economic calendar, earnings calendar, Asia/overnight | `web_search` / `web_fetch` | issuer IR and press first. |

The `## RUNTIME DATA-SOURCE CONTRACT` in `_shared/PROMPT-BLOCKS.md` is authoritative for the
ladder, the per-egress Yahoo caveat, and the seven standing rules. **Do not change the ladder.**

**When you build a TradingView scanner body, these four rules are not optional** (they are in
`_shared/PROMPT-BLOCKS.md` → *The TradingView scanner's request shape*, with the full evidence
in `RUNTIME-CONTRACT.md` §2a-bis):

1. `sort` must be `{"sortBy": X, "sortOrder": "asc|desc"}`. An ARRAY `sort` is HTTP 400; the
   `{"column","order"}` form is HTTP 200 and **silently unsorted**.
2. **The completeness test is a SET test.** `totalCount == rows returned` is necessary and NOT
   sufficient — the scanner's default page order is not stable between requests, so a paged
   pull overlaps and misses names while looking healthy (measured: 13,500 rows / 8,689 unique;
   and 20,155 rows / 20,001 unique). Assert the pages are DISJOINT and their UNION equals
   `totalCount`, and page on a STABLE key (`name`) if you must page at all.
3. **The row key is the BARE ticker `d[0]`** — `s` is venue-prefixed (`NYSE:BW`), and indexing by
   `s` makes every US ticker look missing.
4. **If you know the ticker list, pull it**: a categorical `in_range` filter takes a LIST
   (`{"left":"name","operation":"in_range","right":[...]}`) and returns exactly those rows in one
   call — no universe, no paging. Pull the universe only when you genuinely need every name.

A pull that fails any of these is a **FAILED pull**: report it, do not publish it. The validated
client `_shared/tv_scan.py` (marker `TV_SCAN_V2`, `pull --names` / `pull --body`) enforces all
four.

## Steps

1. **Read the watchlist.** It is a **PUBLISHED FILE**, fetched at run time (the local
   `research/watchlist.yaml` on the Mavis host is unreachable from the Cloud runtime — that is why
   this section was omitted from every brief until 2026-11-06):

   ```
   https://api.github.com/repos/karizaco/minimax-cloud-outputs/contents/refs/watchlist.yaml?ref=main
   https://raw.githubusercontent.com/karizaco/minimax-cloud-outputs/main/refs/watchlist.yaml
   ```

   Use the contents API first (it is authoritative and not CDN-cached), then the raw URL.

> **If it fetches (HTTP 200):** publish the watchlist section from it — the watchlist EOD review
> and any watchlist-relevant news. **If it cannot be read (HTTP 404):** say so ONCE in the notes
> and **omit the watchlist section**; never ship an empty "Your watchlist" table. Substitute the
> routine's deployed universe (per its `## OUTPUT` path) and label it as the universe, not as
> the watchlist.
2. **Day's tape.** Index closes via the bridge `market-recap` `get_quotes` (`^GSPC, ^IXIC, ^DJI,
   ^RUT, ^VIX, ^VXN, ^NDX, ^SOX`) and ETF proxies via the same call (`SPY, QQQ, IWM, DIA, RSP,
   SMH, GLD, TLT`). The **participation read** (§5.5) comes from cron #20's CSV; the
   **cap-weight penalty and its 5-day history** (§5.6) come from the bridge `price_history`.
   - **Assert `as_of` on EVERY index row, not only on the futures rows.** The stale-settlement
     trap below was measured on a FUTURES row, but the same failure exists on the indices:
     measured 2026-11-10, the bridge returned **^VXN with `as_of` 2026-11-09T21:00Z and a
     -14.84% change** while every other index row carried 2026-11-10. Publishing that as
     today's Nasdaq-volatility move would have been a fabricated statement — and the checker
     does not validate numbers, so it would have shipped clean. **A row whose `as_of` is not
     the fire date is the PRIOR session's reading.** Publish it as such, say so in the same
     table, and count it in `degraded_sources:`.
3. **Sector rotation.** Rank the top 3 / bottom 3 sectors from the universe's `sector` column
   (cap-weighted % change and the median), and cross-check 1–2 representative tickers per
   sector against the bridge `get_quotes`.
   - **De-duplicate share classes before you weight.** Compute the cap-weighted return on one
     row per `cap_source_symbol` (Alphabet A+C, Berkshire A+B and the JPMorgan preferred lines
     each carry a full parent cap), and drop rows flagged `EX_DISTRIBUTION` — cron #20's rule.
   - **The de-duplication rule is necessary but NOT sufficient — cron #20's CSV carries three
     more flags that each silently corrupt a cap-weighted column** (all measured 2026-11-10 on
     `us-eod/2026-11-10.csv`, 4,893 rows):
     - **`CAP_CARRIED` rows carry the PARENT's cap and their OWN share class's move.** GOOG and
       GOOGL both carry $3.515T (GOOG's own move -0.38%, GOOGL's -0.25%); BRK-A and BRK-B both
       carry $1.258T (BRK-A +2.60%, BRK-B +1.40%). **Which row you keep changes the sector's
       cap-weighted return**, so keep the row whose `data_quality` does NOT contain
       `CAP_CARRIED` (the primary listing, which carries that class's own move) and let the
       carrier row go.
     - **241 rows carry `NO_CAP`.** They cannot be cap-weighted — exclude them from every
       cap-weighted column and from the denominator (they still belong in the unweighted
       participation read).
     - **105 rows carry `NO_SECTOR`** (only 19 of them priced). They are a bucket, not a sector.
       If you rank sectors including that bucket it lands at -0.32% and **displaces Utilities
       (-0.24%) from the bottom three**. Exclude it and say so in the coverage note.
   - **Assert that every cap-weighted sector return is inside ±20% before you publish it.**
     De-duplicating on `cap_source_symbol` is what stops a **doubled parent cap** from
     inflating both the denominator and the move: with Berkshire counted twice, Financials'
     cap-weighted return printed **+28.2%** instead of +0.28% on 2026-11-10. That is not a
     subtle wrongness — and the checker does not validate numbers, so the artifact would have
     shipped clean. Assert the range; a cap-weighted sector return outside ±20% is a
     computation bug, not a market event.
   - **Cross-check each sector row against its ETF, and publish the gap.** When the cap-weighted
     return and the sector ETF disagree by more than ~0.5pp, the gap is a constituent effect and
     not a rotation: on 2026-11-06 SpaceX ($1.82T cap, +8.6%) was +1.82pp of Industrials' +2.38%
     while XLI printed +0.12% and the sector ex-SpaceX was +0.71%. Name the constituent, publish
     the sector with and without it, and record in `## Source health` that the cap-weighted column
     inherits that concentration.
4. **Watchlist EOD review.** For each watchlist ticker: price, day change, day range, volume vs
   average, and the after-hours print.
5. **After-hours earnings reactions.** `web_search` `<TICKER> after hours <today>` for any
   watchlist names that reported AMC; and a broad mover sweep via `web_search`
   "after hours earnings <date>".
6. **After-hours movers — with LEVELS.** Pull the extended-hours screen from the TradingView
   scanner with the `postmarket_*` columns and publish the full level set (§5.7). Cap the table
   at 10 names (5 gainers, 5 losers); every row carries the level columns, not just the %.
7. **Tomorrow's setup.**
   - Futures via the bridge `get_quotes` (ES=F, NQ=F, YM=F, RTY=F, ZN=F) — note Asia opens
     ~18:00 ET Sun–Thu, and the overnight move is the setup, not the cash close.
   - **Assert the futures timestamp before you call anything an overnight setup.** The bridge's
     futures rows can carry `as_of` at the 16:59:59 ET settlement for hours after the cash close
     (measured 2026-11-06: every futures row still read 16:59:59 ET at the 22:30 fire, five and a
     half hours stale). Read `as_of` on every futures row; if it is more than ~30 minutes older
     than the fire, the quote is the prior session's settlement and NOT the overnight. Publish it
     as such, say explicitly that the post-18:00 ET Globex/Asia move is not in the data, and count
     it in `degraded_sources:`. A stale settlement presented as the overnight setup is a
     fabricated setup, not a caveat.
   - Tomorrow's earnings: `web_search` `earnings calendar tomorrow <day>` against the watchlist
     and the top movers.
   - Tomorrow's economic releases: `web_search` `economic calendar <tomorrow-iso-date>` (payrolls,
     CPI, PPI, jobless claims, Fed speakers, Treasury auctions).
   - News to watch for the top movers: `web_search` `<TICKER> news <date>` for the top 3 by day's
     % move.
   - **Then write "Tomorrow's three things to watch"** (§5.4) — three names, each with its level
     and its catalyst.
8. **Breadth & volatility.** VIX, VXN, the participation metrics (§5.5), and the put/call ratio
   from the CBOE daily statistics page. **Publish the total put/call as sourced; never invent a
   component split the sources disagree on.**
   - **Read a volatility index from the DATED history, not from the quote row.** Measured
     2026-11-10, the bridge's `get_quotes` returned **^VXN with `as_of` 2026-11-09** — the prior
     session's close and its -14.84% move — while every other index row carried 2026-11-10. The
     correct 10 November VXN close was **28.57, -1.38%** (after a 30.22 intraday high), and it
     was available all along from two places: the bridge's own **`price_history`** for `^VXN`
     (which returns the dated row for the fire date) and **Cboe's own dated close file**,
     `https://cdn.cboe.com/api/global/us_indices/daily_prices/VXN_History.csv`
     (`DATE,OPEN,HIGH,LOW,CLOSE`, one row per session). The two agree to the cent. **Read the
     volatility indices from `price_history` and cross-check the close against CBOE's dated
     file** — and note that `get_quotes` can carry a prior session's row for a volatility index
     while carrying the right one for every other symbol in the same call.
   - **The CBOE daily statistics page DOES carry a session date stamp — read it from the
     payload.** The earlier claim that the embedded data carries no date (measured 2026-11-06)
     was an artefact of the EXTRACTION step, not of the source: `web_fetch` was asked to
     summarise the page and returned the ratios without the fields. Fetch the page and read
     them yourself — the payload carries `\"selectedDate\":\"YYYY-MM-DD\"` and
     `\"prevTradingDay\":\"YYYY-MM-DD\"` next to the volume and ratio blocks. **Publish the
     session date with the ratio, and assert it equals the fire date**; if it is an earlier
     session (a holiday, or a day CBOE published late), say which session the number belongs to
     and count it in `degraded_sources:`. The page always serves the LATEST session — a
     `?date=` query parameter does not change the server-rendered payload (measured
     2026-11-10: three parameter forms all returned the same `selectedDate`) — so the session
     it shows at the 22:30 fire is the one that just closed. It also carries more splits than a
     summary returns: total, index, equity, ETP, SPX+SPXW+SPXO and XSP.
9. **Write the brief** following §5.3's spine exactly, with the level columns and the
   participation metrics.
10. **Run the checker** (§5.9) on the artifact and on the saved reply, and fix whatever it
    reports before you push.
11. **Push** with `push_artifact.sh --out daily-briefs --add daily-briefs/{date}-post-market.md
    --branch main`, then verify delivery with `verify_delivery.sh`.

---

# §5 THE ARTIFACT CONTRACT — `postmkt-artifact-v2`

## 5.1 Why this section exists

The 2026-11-03 and 2026-11-04 artifacts were mechanically correct and reader-hostile. The most
valuable content in the 2026-11-03 brief was the **last third** of the document — "Tomorrow's
setup" was section **9 of 10** in a brief whose entire job is to set up tomorrow. The after-hours
movers were published as a percentage with no level, so a reader could not act on
"ANET +9.47% AH". The single best sentence in the brief — *the index was green but the median
stock was not, and SPY +0.30% vs RSP −0.33% is a 63bp cap-weight penalty* — was buried in the
second paragraph instead of being a named metric. And the chat reply had no "tomorrow" line at
all, so the reader had to open the artifact to learn what tomorrow looked like.

**Those four defects are the contract.** The acceptance criteria are machine checks in
`tools/check_postmarket_brief.py` (§5.9). The 2026-11-03 artifact looked fine and failed them.

## 5.2 The front matter and the marker

```yaml
---
date: <YYYY-MM-DD>
cron: 23-agentic-post-market-brief
contract: postmkt-artifact-v2
fire_time_et: 22:30
snapshot_et: <HH:MM-HH:MM>
session: <session id>
scheduled_at_ms: <ms>
status: ok
source: <the sources you used>
primary_source: <the quote source of record>
universe: <the EOD universe and its size>
---
```

`contract: postmkt-artifact-v2` is the marker. The checker requires it.

## 5.3 The section spine — these H2s, in this order

```
# Post-market brief — <Weekday, DD Month YYYY>
## TL;DR
## Tomorrow's setup — <next session date>
## Day's tape
## Sector rotation
## After-hours movers
## After-hours earnings reactions
## Open research queue
## Source health
## Method notes
```

**`## Tomorrow's setup` is section 2 of 10, right after the TL;DR.** Not at the bottom. If you
write it anywhere else, the checker fails.

Sections that used to be separate H2s (the universe/watchlist EOD review, the day's movers, the
breadth & volatility block) are folded into the nearest H2 as **H3 subsections** — content is
never dropped, only headings are reorganised. A typical `## Day's tape` carries:

```
### Market read                        <- the participation metrics (§5.5) — REQUIRED
### Cap-weight penalty — 5-day history <- (§5.6) — REQUIRED
### Index, ETF and volatility levels
### Cross-asset
### Day's movers
### Watchlist EOD review
```

`## Tomorrow's setup` carries these H3s, in this order:

```
### Futures and the overnight setup
### Economic calendar
### Earnings calendar
### News to watch for the top movers
### Tomorrow's three things to watch   <- REQUIRED, exactly three bullets (§5.4)
```

`## Open research queue` stays. It is the most original section in the fleet — three questions,
each with why it matters and what would resolve it. **Carry its top item into the reply** (§5.8).

## 5.4 "Tomorrow's three things to watch" — three names, a level, a catalyst

This is what a reader opens a 22:30 brief to get. It appears in the artifact (as the last H3 of
`## Tomorrow's setup`) **and** in the reply (§5.8).

Rules:

- **Exactly three bullets.**
- **One name per bullet.** Draw from tomorrow's earnings calendar and the news-to-watch list.
- **Each bullet carries a LEVEL** — the number a trader marks. Use the §5.7 level set when the
  name traded after hours (its `gap_fill_level`), otherwise its 16:00 ET close.
- **Each bullet carries a CATALYST** — what resolves it. If you could not source a catalyst,
  say what you *can* source ("reports before the open; guidance is the tell") rather than
  inventing one.
- Format: `- <TICKER> — <level> — <catalyst>`. Example:
  `- QCOM — 168.40 gap-fill, 171.20 prior close — reports AMC, EPS est 2.20; the Q4 guide is the tell.`

## 5.5 The participation read — a named metric, not a mid-paragraph statistic

Publish these **named metrics** in a table under `### Market read`, with these exact names as the
row labels:

| row label | what it is | where it comes from |
|---|---|---|
| `advancers` | names closing higher | cron #20's `us-eod/{date}.csv` |
| `decliners` | names closing lower | same |
| `unchanged` | names closing flat | same |
| `median_name_move_pct` | the median `%` move of the universe | same (`change_pct`) |
| `cap_weight_penalty_bp` | SPY return minus RSP return, in basis points | bridge `price_history` |
| `liquid_adv_dec_ratio` | advancers : decliners in the liquid set | same CSV, `market_cap` floor |

Use **one population** for the first four and the sixth — the cron #20 universe — and say which
one in the front matter (`universe:`). The liquid set is the names with `market_cap` above the
floor stated in the table (the 2026-11-03 brief used $2B; name whatever floor you used).

**The TL;DR must name these metrics too.** The TL;DR carries a participation line that contains
the literal tokens `cap_weight_penalty_bp`, `liquid_adv_dec_ratio`, `median_name_move_pct`, and
the words *advancers* and *decliners*, with today's values. The 2026-11-03 sentence — *"the index
was green but the median stock was not… SPY +0.30% vs RSP −0.33% is a 63bp cap-weight penalty"* —
is the model. Put it in the first paragraph, not the second.

`cap_weight_penalty_bp` is **signed**: positive = the cap-weighted index outperformed the
equal-weight index (a narrow, mega-cap-led tape); negative = the opposite.

## 5.6 The cap-weight penalty — with its 5-day history

One metric with no history is a wobble. Publish the last **five** sessions in a table under
`### Cap-weight penalty — 5-day history`, whose header carries `cap_weight_penalty_bp`:

| Session | SPY % | RSP % | cap_weight_penalty_bp |
|---|---|---|---|
| 2026-11-03 | +0.30 | -0.33 | +63 |
| … 4 more sessions, newest last … |

Fetch both ETFs' daily returns in **one** bridge call:

```bash
printf '%s' '{"symbols":["SPY","RSP"],"start_date":"<fire_date minus 12 calendar days>","end_date":"<fire_date>"}' > /workspace/_mcp/spyrsp.json
python3 /workspace/mcp_bridge.py market-recap price_history /workspace/_mcp/spyrsp.json
```

`price_history` returns each session's `close`, `previous_close` and `daily_return_pct` for both
symbols. `cap_weight_penalty_bp = (SPY daily_return_pct − RSP daily_return_pct) × 100`, rounded
to the nearest basis point. This is self-verifying: on 2026-11-03 it reproduces the published
+63bp exactly.

## 5.7 The after-hours movers — every row carries a LEVEL

A percentage without a level is not actionable. **Every row of the after-hours movers table**
carries these columns, with these exact header names:

| column | what it is |
|---|---|
| `ticker` | the symbol |
| `prior_close` | the 16:00 ET regular-session close |
| `ah_last` | the last after-hours print |
| `ah_high` | the after-hours high |
| `ah_low` | the after-hours low |
| `ah_volume` | after-hours shares traded |
| `gap_pct` | `ah_last` vs `prior_close`, in % |
| `ah_range_pct` | the after-hours high-to-low range as a % of `prior_close` |
| `gap_fill_level` | the level that fills the gap (see below) |

One scanner call produces all of it:

```json
{"filter":[{"left":"type","operation":"in_range","right":["stock","dr"]},
           {"left":"market_cap_basic","operation":"egreater","right":1000000000},
           {"left":"postmarket_volume","operation":"egreater","right":50000}],
 "options":{"lang":"en"},
 "symbols":{"query":{"types":[]},"tickers":[]},
 "columns":["name","description","close","postmarket_close","postmarket_change","postmarket_high",
            "postmarket_low","postmarket_volume","market_cap_basic","exchange"],
 "sort":{"sortBy":"postmarket_change","sortOrder":"desc"},"range":[0,200]}
```

**Send it through the shared validated client**, not raw curl — `_shared/tv_scan.py` checks the body
before it goes out and checks the pull for truncation afterwards:

```bash
python3 /workspace/tv_scan.py scan --body /workspace/_mcp/ah_up.json --out /workspace/_mcp/tv_up.json
```

(A list-valued `right` on `in_range` — the `type` filter above — is a VALUE SET, not a numeric
range, and the endpoint accepts it; the client was fixed to allow that form on 2026-11-11 after it
falsely rejected this body. A scalar `in_range` still needs `second_right`.)

Run it **twice** — `postmarket_change` descending for the gainers and ascending for the losers —
so both sides are carried, then rank by **absolute** `postmarket_change`. Cap the published table
at 10 names (5 gainers, 5 losers).

**The screen has a floor, and the floor hides the session.** The screen keeps names above $1B of
market cap, so the biggest after-hours moves of the night are usually *below* the table: on
2026-11-06 the screen's top gainer printed +9.77% while the session's actual leader printed
+110%. Pull the same screen once without the market-cap floor (or read one small-cap leaderboard)
and publish those names in `## Source health` with their percentages, so the table is never
mistaken for the whole after-hours tape. The table itself stays on the contract's screen.

**The `gap_fill_level` rule (deterministic — pick one, every time):**

- if `ah_low ≤ prior_close ≤ ah_high` → the 16:00 close traded through in the after-hours
  session, so **the gap fills at the prior close**: `gap_fill_level = prior_close`.
- otherwise the close was never reached, so the reference is the after-hours midpoint:
  `gap_fill_level = (ah_high + ah_low) / 2`.

**Verify each row before you publish it.** The scanner row is self-verifying:

```
postmarket_change  ==  (postmarket_close − close) / close × 100
```

`close` here is the settled 16:00 ET close and `postmarket_change` is measured against it. If a
row fails the identity, **drop that row** and say so in `## Source health` — do not publish a row
whose own numbers disagree.

**Do not publish a level you did not read.** If a field is unavailable for a name, publish `n/a`
in that cell and say which field is missing — never a zero and never a guess.

**The after-hours tape keeps moving after the fire — pick one vendor and date the print.** The
16:00 close is settled; the extended-hours print is not. On 2026-11-11 the same name carried three
different after-hours changes depending on the vendor and the minute: CRWV **-2.37%** (Public,
17:30 ET), **-7.12%** (MarketBeat, 18:10 ET) and **-6.37%** (the TradingView scanner, ~22:35 ET).
Publish the scanner's print as the source of record, state that it is a snapshot as of the fire,
and if another vendor's number is materially different, name it in `## Source health` rather than
blending the two into one figure.

## 5.8 The reply

The house format in `_shared/PROMPT-BLOCKS.md` (`## DELIVERY`) applies — prose opener,
`### Signal`, `### Method & caveats`, `### Files`, `### Push / errors` — **plus** the four
rules below. The checker asserts all four.

1. **`### Signal` stands alone.** The header on its own line, then a **blank line**, then the
   first bullet. The emitted string contains `### Signal\n\n`. (This defect was real in the
   2026-11-03 reply — `### Signal- **AEHR +26.50%**` — and is fixed; do not reintroduce it.)
2. **One ticker per bullet.** A bullet may carry one ticker or none; it may never carry two.
   The 2026-11-03 reply crammed three tickers onto one line. The rule is mechanical, so it also
   fires on words that merely LOOK like tickers: "FCC" is not on the checker's non-ticker list,
   so a bullet naming GOGO and the FCC is a two-ticker bullet and the run fails. On 2026-11-06
   that was the only check the contract caught. When a second capitalised token appears, name the
   organisation in words ("the spectrum regulator"), not in caps.
3. **A `### Tomorrow's three things to watch` section** with exactly three bullets, each naming
   one ticker and its level and catalyst (§5.4). This is the section the reply was missing.
4. **The top item of the open research queue is carried into the reply** — as the first bullet
   of `### Method & caveats`, or in the prose opener. Name it as a research question, with why it
   matters and what would resolve it.

The reply's `errors:` count MUST equal the artifact's `degraded_sources:` count exactly.

## 5.9 Verify the artifact before you report it

```bash
C=/workspace/tools/check_postmarket_brief.py
for U in \
  "https://api.github.com/repos/karizaco/maxhermes-migration/contents/tools/check_postmarket_brief.py?ref=main" \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/tools/check_postmarket_brief.py" \
  "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/tools/check_postmarket_brief.py" ; do
  curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" \
    -H "Authorization: Bearer ${GITHUB_TOKEN}" -o "$C.tmp" "$U" 2>/dev/null
  if [ -s "$C.tmp" ] && grep -q 'postmkt-artifact-v2' "$C.tmp" 2>/dev/null; then
    mv -f "$C.tmp" "$C"; break
  fi
  rm -f "$C.tmp"
done
if [ ! -s "$C" ] || ! grep -q 'postmkt-artifact-v2' "$C" 2>/dev/null; then
  echo "check_postmarket_brief.py: UNAVAILABLE (no copy carrying the current contract)"
  echo "the artifact still ships; say contract_check: unavailable in the reply"
else
  # save the FINAL reply text to /workspace/reply.txt first — the reply checks need it
  python3 "$C" --artifact /workspace/daily-briefs/{date}-post-market.md --reply /workspace/reply.txt
fi
```

The capability marker `postmkt-artifact-v2` is required so a **stale** copy of the checker cannot
win the ladder and fail a correct artifact (or pass a broken one).

The checker asserts: the contract marker; the §5.3 spine and its order (and
`## Tomorrow's setup` before `## Day's tape`); the five `### Tomorrow's three things to watch`
H3s with exactly three bullets; the six §5.5 metric rows in the market-read table; the §5.6
5-session history table with five dated rows; the §5.7 after-hours table's header and every
row's cells; the presence of `## Open research queue`; and the four §5.8 reply rules.

**If it fails, fix the artifact and run it again — do not report a clean run over a failing
check.** If a check cannot be satisfied because the data was genuinely unavailable, publish the
artifact anyway, state the gap in `## Source health` and `## Method notes`, and say
`contract_check: failed (<which check>)` in the reply. Do not fabricate a number to satisfy the
checker.

## 5.10 DO NOT

- **Do not bury tomorrow's setup.** It is section 2, not section 9.
- **Do not publish an after-hours percentage without its level columns.**
- **Do not publish a put/call component split.** The total was sourced (0.87 on 2026-11-03); the
  components disagreed (0.56 vs 0.67) and the 2026-11-03 run correctly refused to invent one.
  Publish both readings only if both are sourced, and say they differ. (Splits from ONE payload
  are fine — the 2026-11-11 page carried total 0.95, index 1.02 and equity 0.77, all from the
  same object and reconciling with the total.)
- **Do not publish a put/call without its session date.** The page carries `selectedDate`; read
  it and publish it. "The session cannot be dated" is only true if you did not look.
- **Do not publish a volatility index from a quote row you did not date-check.** `get_quotes`
  returned the prior session's ^VXN on 2026-11-10 and every other symbol in the same call was
  correct. Read ^VIX/^VXN from `price_history` and cross-check against CBOE's dated close file.
- **Do not describe an intraday move against the wrong denominator.** "The index went up 11%
  intraday" was the high-low RANGE against the prior close, not the move to the high (8.5%).
  State which one you mean.
- **Do not remove `## Open research queue`** — keep it, and carry its top item into the reply.
- **Do not change the source ladder.** The bridge `market-recap` for closes/movers/macro/history,
  the TradingView scanner for breadth and extended hours, cron #20's CSV for the universe, web for
  catalysts and calendars.
- **Do not call the `mcp__*` tools** — they are not registered here.
- **Do not eyeball the contract.** Run the checker.

## Hard rules

- Never place trades. Read-only by design.
- Use only the paths listed above plus `web_search` / `web_fetch`. No browser automation.
- If after-hours data is sparse, note it under `## Source health` — do not invent.
- Cap after-hours movers at 10; cap sector list at top-3 / bottom-3 only.
- Always cite sources (URL or file path) for factual claims.

## Out of scope

- Portfolio P&L or position sizing — read-only summary only.
- Pre-market setups — those live in the pre-market skill.
- Weekly recaps — those live in the weekly brief skill.
