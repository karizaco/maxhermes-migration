---
name: Earnings reaction scanner
description: >-
  Pre-market scan of overnight and after-hours price action across the S&P 500
  top-200 (by market cap) plus the prior session's biggest movers in the full
  US universe, plus the pre-market gap leaders of the full US universe (a name
  that gapped today after being flat yesterday), plus EU/UK intraday movers
  (live session at 08:00 ET), plus Australia (ASX) prior-session movers
  (closed ~6h before scan). Surfaces pre-market gaps, AMC reactions, EU
  intraday reactions, ASX reactions, and catalysts. Uses TradingView
  screen_stocks + stock_screener + stock_extended_hours + combined_analysis +
  financekit earnings_calendar + stocktwits. Runs weekdays 08:00 ET, after the
  pre-market brief.
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

# Earnings reaction scanner

Surfaces the price action that the pre-market brief missed: every name in the S&P 500 top-200 with a meaningful pre-market or post-market move, the prior session's biggest movers across the full US universe, the **US pre-market gap leaders of the full US universe** (a name that gaps today after being flat yesterday), **EU/UK intraday movers during their live session** (started 03:00 ET, mid-session at scan time), and **Australia (ASX) prior-session movers** (ASX closed ~02:00 ET, 6h before scan). Six-pass design replaces the original watchlist-only Pass A and hardcoded 13-name Pass B.

## ARTIFACT FORMAT CONTRACT v2 — `REACTION_ARTIFACT_V2` (authoritative)

**This section is the contract. The pipeline that renders the artifact is
`scripts/earnings_reaction_scanner.py` in `karizaco/minimax-cloud-outputs`
(`SCRIPT_VERSION` + the marker `REACTION_ARTIFACT_V2`); the rest of this file
is the procedure it implements.** A fetch of the pipeline that does not carry
the marker `REACTION_ARTIFACT_V2` is a STALE copy and must not be run — the
marker is the capability check, exactly as `WINDOW_CHECK_V2` is for the shared
window check.

**The contract lives here, not in the cron prompt, because the cron prompt
fetches this file at RUN time. A change here lands on the next fire with no
`cron_update` and no prompt drift.**

### The skeleton (sections, in this order)

```
# Earnings reaction scanner — YYYY-MM-DD
<front matter: cron, fire time, run type, source, method, artifact_contract,
 ref_close_source, settlement_state, status>
## TL;DR
## Actionable read
## US — Headline table
## US — QUIET one-liners
## EU/UK — Headline table
## AU (ASX) — Headline table
## APAC/Gulf — Headline table
## Source health
## Audit line
```

**There is no `## Catalysts` section.** The catalyst rides in the last column of
its row (the one-table rule, below). A separate catalysts section duplicates the
tables and lets a name appear twice.

**The settlement pass is a DIFFERENT artifact** (a second slot, 12:15 ET) with
its own skeleton — see "The settlement pass" below.

### The one-table rule — each name appears EXACTLY ONCE

Each name appears exactly once in the markdown, in exactly one table, with its
catalyst in that row's last column. This is the rule from
`ntrt-gap-brief/SKILL.md` §2 and it exists because the 2026-11-03 artifact put
names in both a table and a catalysts section.

- A symbol that appears on a US venue **and** a foreign venue keeps the **US
  row** — it carries the extended-hours columns and it is the line a US reader
  can trade. The dropped foreign row is listed in source health
  (`cross_region_rows_dropped`), so nothing is hidden.
- The checker parses the tables and asserts `len(names) == len(set(names))`.

### The required columns — every published row carries them

Every published row of every table (including the QUIET one-liners) carries:

| Column | Meaning |
|---|---|
| `Ref close` | the close the move is measured against |
| `Ref source` | where that close came from (`yahoo_chart_daily`) |
| `Ref asof` | the DATE of that close |
| `US tradeable` | `US-listed` / `US-listed (ADR)` / `US line (VENUE:TICKER)` / `ADR (VENUE:TICKER)` / `none` |
| `Last earnings` | the date of the name's LAST report — **the bulk earnings calendar is the source of record** (the section below); the screener's field is the fallback |
| `Move vs avg daily` | the reaction ÷ the name's own mean absolute daily move over its last 20 completed sessions (`n/a` when it cannot be derived) |
| `Settle` | `live` or `settled` — **on every foreign row** (EU/UK, AU, APAC/Gulf) |

`Move vs avg daily` is the point of the actionable layer: a −27% move in a name
that averages ±3% is a different event from a −8% move in a name that averages
±7%. `US tradeable` is what makes a foreign row actionable: a Euronext or
Swedish ticker a US reader cannot buy is `none`, and a US line carries its US
ticker.

**THE INSTRUMENT FORM COMES FROM THE SECURITY, NEVER FROM THE ISSUER'S
COUNTRY.** `(ADR)` is published only when the security itself says it is a
depositary form — the scanner's `type` column (`dr`), or a description naming
a depositary. The old rule ("country ≠ United States ⇒ ADR") called 16 of the
115 US rows on 2026-11-12 ADRs, and most of them were not: NBIS (Nebius
Group N.V.) lists its Class A **ordinary shares** directly on Nasdaq, as do AEM,
TSEM, NVMI, FN, IREN and DPC. A security with no evidence either way is
published as `US-listed`, never as an ADR.

### The bulk earnings calendar — the source of record for the earnings date

**One call to Nasdaq's public earnings calendar answers "did this name report,
and when" for the WHOLE US market.** It is fetched once per run — the scan date
and the 7 prior calendar days — and it is the source of record for the
published `Last earnings` date.

**Why it replaces the screener's field.** TradingView's
`earnings_release_date` is refreshed per company and ASYNCHRONOUSLY. At the
08:03 ET scan on 2026-11-12, NBIS — which had reported PRE-OPEN that morning —
still carried `2026-08-12`, the previous quarter. A verdict built on that field
is not a missing verdict but a **false** one: the old test ("did
`earnings_release_date` land within 7 days of today?") would have marked NBIS
`N` — not earnings-driven — on the very morning it reported.

**Every disagreement is published, never silently corrected**:
`earnings_field_stale_rows: <n>` in source health, with the rows listed in
`earnings_field_stale_detail`.

**The calendar's `time` field is NOT usable** for the pre-open / after-close
split (measured 2026-11-12: 444 of 448 rows read `time-not-supplied`), so
freshness comes from the REPORT DATE and the artifact's own `AMC`/`PRE_GAP`
tag.

### The published `Last earnings` — ONE chain, in this order

1. the **researched** date from the catalyst catalog (the issuer's own
   release, read while fetching the headline);
2. the **bulk calendar** (US);
3. the **ASX announcements feed** (AU);
4. the **screener's field** — the fallback, and the one that lags.

Source health publishes the census (`earnings_dates: catalog <n>, calendar
<n>, asx <n>, screener <n>`), so a reader can see how much of the table rests
on the lagging source on any given day.

**AND THE PER-MARKET QUALITY TABLE** (`earnings_date_quality`): each market's
rows, the rows with **no date at all**, the median age of the published date,
and the rows within 7 and 30 days. The point is that a WRONG date and a
RIGHT date must be distinguishable by the reader: measured on the 2026-11-12
artifact, india, indonesia and ksa published no date at all, while uk,
switzerland, denmark and thailand were fresh — so the defect is PER-MARKET,
not "foreign = bad", and only the table says so. The checker requires the
table and requires it to cover every market that publishes rows.

**The bulk calendar reaches the US markets only.** EarningsWhispers answers
(`?d=YYYY-MM-DD`, no block) but carries no ASX / STO / XETR names, so the
foreign rows still use the screener's field and still carry its lag — a known
gap, not a silent one.

### The ASX announcements feed — the AU answer to the stale earnings date

**One call to the ASX announcements feed returns every announcement the
exchange published for its last completed session, each with its date — and
the announcement date IS the report date.** The screener's field had a 78-day
median age on the ASX rows of the 2026-11-12 artifact; this feed closes that
gap for AU at the cost of one HTTP call.

The feed also tells the pipeline WHICH ASX names REPORTED in that session, so
an AU row whose results landed overnight is the freshest event on that market
— the same role the bulk calendar plays for the US, and the same rule: a fresh
event outranks a name that is merely due to report soonest.

**The classifier is POSITIVE and the noise is EXCLUDED.** One ASX day carried
37 headlines with "results" in them, and 51 rows were meeting/AGM results
("Results of Meeting", "2026 AGM Results"), plus an assay result and an
entitlement-offer result. Matching "results" loosely dates every AGM as a
report. The shipped classifier matches the REPORT FORMS (Appendix 4E/4D/4F,
`Q3 … results`, `First Quarter Results Presentation`, `financial results`)
and excludes meetings, AGMs, offers, assays and remuneration reports.

### The venue calendars — a venue holiday moves the base back one session

A row's reference close must be the VENUE's previous session, and a venue
that was **closed** on the intervening day has a base one session older than a
plain weekday walk suggests. The weekday walk does not know that, so an honest
row gets flagged — and because the checker blocks the push, a false flag
STOPS the routine from publishing.

**The calendars are DERIVED FROM THE DATA, not typed** (measured 2026-11-16):
for each venue, two liquid reference symbols' Yahoo daily bars were compared
and a date counts as a closure only if **both** missed it, so a
company-specific halt can never fake a venue-wide closure. Dates after the
derivation date are not closures, and a weekday missing in *every* week is
the venue's non-session weekday, not a holiday.

**A calendar is a LOWER BOUND** — Yahoo sometimes carries a bar on a national
holiday (Euronext Paris on 8 May), so a real closure can be missing from the
table. Therefore the floor is the **OLDEST** of (the weekday walk, the
calendar walk): the calendar may only **relax** a floor, never tighten one. A
missing closure can then never make an honest row fail, and a known closure
still catches a base that is one session too old.

AU is deliberately absent (Yahoo's ASX bars are labelled inconsistently — some
by the session open, some by the close — so its missing-Friday pattern is a
labelling artefact, not a closure); ireland and greece are absent (no Yahoo
coverage for `.IR`/`.AT` lines). The APAC calendars are published for
reference only: their bar labels do not share the EU convention, so they never
tighten a floor.

**THE CALENDAR IS A CHECKER-SIDE ASSET.** The pipeline's own foreign
reference-close test is deliberately LOOSE (it tolerates a base up to four days
back), so it never false-drops a row — and a LOWER-BOUND calendar must not be
used to DROP rows, because a missing closure would then drop an honest row.
The calendar's job is the opposite: it stops the checker from FALSE-FLAGGING
an honest row, and a false flag BLOCKS the push. So the table lives in the
checker, the floor is the OLDEST of (the weekday walk, the calendar walk), and
`tools/test_reaction_earnings_tier.py` executes the checker's own floor
function against the Polish and German cases.

### `Settle` — the row says whether its move is finished

`Settle` is `live` when the row's session bar is an **in-progress** bar and
`settled` when it is a **completed** session. It is derived from the same
Yahoo bar resolution that validates the reference close, so it is a
**measurement, not an assumption**.

**Why it exists.** The 08:00 ET fire happens while the EU/UK cash session is
still open (it closes 11:30 ET in winter, 10:30 ET in summer), so the EU/UK
`Close` and `Chg %` are a **mid-session snapshot**, not the session's result.
Measured against each session's settled close over the 2026-11-05/06/09 runs:
the median EU row finished **0.9–2.1pp** away from its printed move, the worst
**12.7pp**, and roughly **half** the rows were more than 1pp off. The row now
says so, and the 12:15 ET settlement pass publishes where those moves closed.

The AU and APAC/Gulf rows read `settled` — those sessions close before the
08:00 ET fire (ASX 00:00 ET, India 05:00, Thailand 04:30, Indonesia 04:00,
Singapore 04:00, China 02:00, New Zealand 22:45 the previous day, Saudi
Arabia 07:00).

### The reference close is resolved FIRST, and it is a hard gate

The reference close is resolved **before any table is built**, from one
authoritative source (Yahoo's daily chart bars), and the candidate universe is
filtered against it:

1. The screener's implied reference close (`close / (1 + change/100)`) is
   compared with Yahoo's reference close. A disagreement above 0.5% means the
   screener row was measured against a **stale** close — a phantom move — and
   the row is **dropped**.
2. A row whose reference close is **older than the previous session** is
   **dropped**. The drop is COUNTED and published as
   `rows_dropped_stale_ref` — never silently filtered.
3. Every surviving row publishes `Ref close`, `Ref source` and `Ref asof`, so a
   reader can see whether the row was checked against today's close or an older
   one.

**Session selection is by DATE and ORDER, never by a modal time-of-day.** Yahoo
stamps a daily bar at the session open in the venue's local time, so the ET
stamp of the SAME session moves by an hour across a DST boundary (a US bar:
09:30 ET in summer, 10:30 ET in winter; an ASX bar: 19:00 ET before the change,
18:00 ET after). A modal time-of-day filter keeps the OLDER bars and discards
the NEWEST ones — it rolled the base back to the prior-prior session and cost
66 US rows + 21 ASX rows on 2026-11-03 and 24 of 25 ASX rows on 2026-11-04.

### `## Actionable read` — the actionable layer, above the tables

Three things, in this order:

1. **Move vs this name's own history** — how to read the `Move vs avg daily`
   column.
2. **US-listed and tradeable vs foreign-only** — how many published reactions
   are on a US venue, how many foreign reactions have a US ADR line, and how
   many are foreign-only.
3. **Not yet fully priced — one name per region (US, EU/UK, AU)** — a
   HYPOTHESIS with its evidence, never a recommendation. The hypothesis is
   stated as: the move is still extending beyond the move it follows (for a US
   row, the extended-hours print exceeds the regular session's move; for a
   live EU session or a closed ASX session, the move exceeds the previous
   session's move), and it is large relative to the name's own average daily
   move. The evidence is published with it: the move, the average daily move,
   the multiple, the reference close and its date, and the US access.
   **No direction, no trade, no recommendation.** If no row in a region carries
   the average daily move needed to judge it, say so and name no candidate.

### `## Source health` — and the reply's `errors:` count

Source health publishes `degraded_sources: <n>` followed by **one numbered
entry per degraded source**, each naming which source and what happened. The
chat reply's `errors:` count **must equal that number** — one entry per
degraded source, not one per run. The 2026-11-03 reply reported `errors: 1` for
two unverified rows plus a stale TradingEconomics table: three degraded sources
counted as one.

A degraded source is a source that did not answer: a rate-limited or failing
Yahoo endpoint, a reference close that could not be resolved, a scanner call
that failed, the US-line index that could not be built, the earnings calendar
that did not answer. A market returning few rows is **not** a degraded source
(it is a coverage note), and a row dropped by the reference-close gate is
**not** a degraded source either — it is counted in `rows_dropped_stale_ref`.

Source health also publishes the catalyst machinery, so a reader can see how
the catalyst cells were allocated: `catalyst_budget:` (the split and the cap),
`earnings_calendar:` (the calls, the errors and the symbols), `earnings_tiers:`
(`fresh=` the reports dated on the scan date, `near=` the previous session),
and `earnings_field_stale_rows:` with its detail line.

### The audit line

`earnings-reaction target=earnings-reactions:<date> candidates=<n>
amc_reactions=<n> pre_gaps=<n> eu_reactions=<n> asx_reactions=<n>
catalyst_lookups=<n> bod=<n> earnings_calendar_rows=<n>
earnings_tiers_fresh=<n> earnings_tiers_near=<n>
earnings_field_stale_rows=<n> rows_dropped_stale_ref=<n>
degraded_sources=<n>`

### The catalyst catalog file

The catalog file is the agent's input; the pipeline READS it and MERGES each
ticker into that row's last column. It is never overwritten by a re-run, so a
re-run never wipes the research.

| Column | Rule |
|---|---|
| `Ticker` | the ticker, exactly as the artifact prints it |
| `Region` | `US` / `EU` / `AU` / `APAC/Gulf` |
| `Catalyst` | the sourced headline, or `no fresh catalyst found` |
| `Earnings-driven` | `Y`, `N`, or **empty** |
| `Report date` | `YYYY-MM-DD` — the date of the report, **when the research found an earnings event**; empty otherwise |

**THE REPORT DATE IS THE SECOND THING THE LOOKUP READS.** The lookup already
opens the issuer's own release to get the headline — the release carries its
own date, so the date costs NOTHING extra, and it is the only source that is
right for a same-morning reporter. Put it in the `Report date` column, and
put the SAME date in the catalyst cell in the canonical form
`<quarter> <FY> results (reported YYYY-MM-DD): <what happened>`. The pipeline
publishes the `Report date` as the row's `Last earnings`, and the checker
compares the two — so a headline that says "reported 2026-11-12" beside a
`Last earnings` of 2026-08-12 FAILS the contract.

**A researched report date BEATS every other source** for that row: it is
first-hand, and it is the date the market actually reacted to.

**The verdict follows the RESEARCH.** Fill `Y`/`N` ONLY for a ticker you
actually researched, and fill `N` only when the research found a cause that is
NOT earnings. **A ticker you did not research leaves the cell EMPTY** — the
pipeline publishes `—` for it, and the checker rejects a published `N` beside a
catalyst cell that says the lookup was not performed. The 2026-11-05 EU run
published `N` next to "catalyst lookup not performed": a false verdict on 10%
of that run's researched EU rows.

**`no fresh catalyst found` IS a verdict** — it means the lookup ran and found
nothing earnings-related, so `N` is correct there.

**The lookup targets are chosen by the pipeline, and they are chosen BY THE
EVIDENCE GAP — not by the size of the move alone.**

**The US rows are tiered by the bulk earnings calendar:**

| Tier | Meaning | Rank |
|---|---|---|
| `fresh` | the report is dated on the SCAN DATE — hours old, and the only thing that can explain today's pre-market gap | 1st |
| `near` | the report is dated on the PREVIOUS session — the reaction may already be in yesterday's close | 2nd |
| `none` | no report inside the window | 3rd |

Within a tier the order is by the size of the move, and an `AMC_REACTION` row
is always first.

**Why freshness ranks above size.** On 2026-11-12 the biggest movers were ALL
earnings names, so ranking by `|gap|` could not tell them apart — and it left
NBIS, which had reported THAT MORNING, outside the budget while a name whose
report was a day old took a slot. A report that is hours old has had minutes to
be priced; a report from yesterday has had a whole session.

**The foreign rows are chosen from the NEXT-report date.** The screener's
`earnings_release_date` (the LAST report) lags badly — on 2026-11-05 it read
2025-02-13 for a name that reported the previous day, and 2026-08-06 for a
name that reported that morning — so "last earnings within 7 days" is **not**
a usable earnings test on a foreign row. `earnings_release_next_date` (the
NEXT scheduled report) is the reliable half of the field, so for EU/UK, AU and
APAC/Gulf the pipeline aims the lookups at the names **due to report soonest**
(within 14 days), breaking ties by the size of the move.

**The budget is allocated by the evidence gap and capped at 16 lookups per
run** (from 5 US + 3 EU + 2 AU + 3 APAC/Gulf before allocation):

* the **US slice** covers every `fresh` row plus the next freshest ones, up to
  the ceiling;
* the **EU / AU / APAC floors are never squeezed** — no bulk calendar reaches
  those markets, so a search is the only way to know;
* whatever the US slice does not need goes to the region with the most
  unexplained rows.

The pipeline writes the resulting split into the catalog file's header, into
source health (`catalyst_budget:`) and into the targets JSON (`budget`,
`budget_total`, `budget_cap`) — **the agent reads the split from those files,
never from a number in a prompt.** The cap exists because of the clock, not the
coverage: one search is ~30–40 s, and 16 of them keep the 08:00 ET fire inside
~20 minutes.

**A row the calendar covers but that is NOT researched keeps a calendar event
line and carries NO verdict.** The cell reads, for example, `Q3 2026 results,
report date today (Nasdaq earnings calendar; no headline lookup), consensus EPS
($0.61)` — the FACT, with its source, and no invented headline. The verdict
follows the research, never the other way round.

The agent writes `catalog/catalysts/<date>.md` — one markdown table,
`| Ticker | Region | Catalyst | Earnings-driven |`. The pipeline **merges each
row into that ticker's row in the artifact** and never emits a separate
catalysts section, so a re-run cannot duplicate a name. The file is never
overwritten, so a re-run never wipes the agent's research. A row whose catalyst
is missing says so honestly: `pending catalyst lookup` (it is inside the
per-run budget) or `no catalyst lookup (outside the per-run budget)`.
**Never fabricate a catalyst** — `no fresh catalyst found` is a valid cell.

The per-run budget is **allocated, not fixed** — read the split from
`earnings/<date>-catalyst-targets.json` (`budget`, `budget_total`,
`budget_cap`), which is where the pipeline publishes it. The ticker list is in
the same file.

### The per-market cap

The EU/UK table (and the APAC/Gulf table) carry **at most 4 rows per market**
(3 for APAC/Gulf). Without it the table was not a market census: over nine runs
Sweden supplied **73 of 264 EU rows (28%)** while **Belgium and Greece never
appeared once**, and a 2.6% mover in Spain, Italy or Portugal never reached the
page. The per-market count is published in source health
(`rows_per_market`), so the thinness of the coverage is visible rather than
implied.

### The APAC/Gulf section

Pass E covers the markets that close BEFORE the 08:00 ET fire, so their
rows are settled and need no live-session caveat: **India, Thailand,
Indonesia, China, Singapore, New Zealand, Saudi Arabia**. The UAE is **not**
included — its session closes at 08:00–09:00 ET, i.e. live at the fire.

The screener market slugs are `india`, `thailand`, `indonesia`, `china`,
`singapore`, `newzealand` and **`ksa`** (NOT `saudiarabia` — that slug 404s).
The Yahoo suffix follows the **venue**, not the market: `.NS`/`.BO` (NSE/BSE),
`.SS`/`.SZ` (Shanghai/Shenzhen), `.BK`, `.JK`, `.SI`, `.NZ`, `.SR`. One suffix
per market would silently resolve half the rows — and a row whose reference
close cannot be resolved is DROPPED by the hard gate.

The market-cap floor is the ASX floor (**$500M**), not the EU $1B one: most
APAC earnings action sits below $1B. The section is capped at 25 rows and 3
rows per market.

**Japan, Taiwan, Hong Kong and Korea are NOT added here.** The `asia-pre-market-reactions`
routine (06:30 ET) already owns those four; publishing them twice creates two
truths for the same name.

### The settlement pass — the second slot (12:15 ET)

The 08:00 ET scan publishes the EU/UK session **mid-flight**, so its EU move is
a snapshot taken minutes after the reaction started. The settlement pass
republishes the same rows with their **settled** close and move, and carries the
morning's move beside each row, so the routine measures its own live snapshot
instead of asking the reader to trust it.

| | |
|---|---|
| Slot | `15 12 * * 1-5` America/New_York (12:15 ET — 45 min after the winter close, 1h45m after the summer close) |
| Task | `15b-earnings-reaction-settlement` |
| Artifact | `earnings/<date>-reactions-settled.md` |
| Pipeline | the same file, run with `--mode settle` |

**Skeleton** (its own shape — the checker accepts both):

```
# Earnings reaction scanner — YYYY-MM-DD (EU settlement pass)
<front matter: cron, fire time, run type: settlement_pass, source, method,
 artifact_contract, morning_artifact, status>
## TL;DR
## EU/UK — Settled table
## Source health
## Audit line
```

**The settled table** carries: Ticker, Market, Venue, Close, Chg %, **Move
@08:00**, **Δ vs scan**, Currency, Move vs avg daily, Ref close, Ref source,
Ref asof, Settle, US tradeable, Last earnings, Earn, Catalyst.

**No US rows.** At 12:15 ET the US cash session is OPEN, so the screener's
`close` and `change` for a US name are live intraday values — publishing them
as a session close would be a fabricated settle. The US passes are skipped
entirely in settlement mode.

**The `scan_to_settle` line in source health is the point of the whole pass**:
how many rows matched the morning scan, the median and maximum drift between
the scan move and the settled move, and how many moved more than 1pp. That is
the routine's own measurement of how much a mid-session snapshot can be
trusted.

### The checker

`tools/check_reaction_artifact.py` in `karizaco/maxhermes-migration` verifies a
rendered artifact against this contract: the skeleton, the required columns on
every published row, the reference-close floor, the one-table rule, the
`errors:` ↔ `degraded_sources:` agreement, and — **from pipeline
2026-11-15.2** — the **Pass B2 coverage**: the artifact must publish
`pass_b2: candidates=<n> deduped_against_pass_a_b=<n> published=<n>` in source
health and its `Method:` line must name the six passes. A pass that is not
published is a pass that did not happen, so the gate is version-gated: an
artifact published before Pass B2 existed is not judged retroactively.
`tools/test_reaction_contract.py` is its regression test (the ET window on a
winter AND a summer date, the base close against the exact bar fixtures that
broke 2026-11-03 and 2026-11-04, and a fault-injection pass that proves the
checker bites — including the Pass B2 gate, whose PASS path is asserted as
well as its failure path).

## When
- Cron: `0 8 * * 1-5` America/New_York (weekdays, 08:00 ET — 23 min after pre-market brief, ~90 min before US open; ~5h into the EU session; ~6h after ASX close)
- Manual: user asks "what did names do overnight?" or "show me today's earnings reactions" or "what's moving in Europe?" or "what moved in Australia?"

## Output
- `C:\Users\admin\.minimax\projects\coding-shared\research\earnings-reactions\YYYY-MM-DD.md`
  _(In Cloud this path does not exist — it is the local Mavis host's location. In Cloud, write to the `## OUTPUT` path in the cron prompt.)_)
- Compact ≤ 12-line summary in chat reply.

## Universe

**Pass A — S&P 500 top-200 by market cap (broad US pre-market gap scan)**
- One `mcp__tradingview-advanced__stock_screener` call: country=america, stock_type=common, sort_by=market_cap, limit=2000, exclude_otc=true. Take top 200 by market cap.
- For each candidate, call `mcp__tradingview-advanced__stock_extended_hours(symbol)` to extract pre-market %, post-market %, previous close.
- Every row checked regardless of whether it reported — broad catch for US mega-caps.

**Pass B — Prior-session US full-universe top movers**
- Two parallel `mcp__tradingview__screen_stocks` calls:
  - Up: `markets=['america'], filters=[{field: change, operator: greater, value: 3}, {field: market_cap_basic, operator: greater, value: 1000000000}, {field: close, operator: greater, value: 5}], sort_by=change desc, limit=200`
  - Down: `markets=['america'], filters=[{field: change, operator: less, value: -3}, {field: market_cap_basic, operator: greater, value: 1000000000}, {field: close, operator: greater, value: 5}], sort_by=change asc, limit=200`
- Then `extended_hours` on each unique candidate to extract post-market vs regular close.
- Captures non-S&P-500 names that moved big in the prior session — the broadest "what moved" net for US.

**Pass B2 — US pre-market gap scan ("gapped today, flat yesterday")**
- The gap this pass closes is **measured, not hypothetical**. On Friday 2026-11-13 the US universe was Pass A (the top-250 US names above $20bn) plus Pass B (the PRIOR session's movers: |change| ≥ 3%, market cap > $1bn, close > $5). A name that was **flat in the prior session** and is **not a $20bn mega-cap** falls through both. That dropped two of the day's biggest same-session earnings movers: **LFTO** (Liftoff Mobile, ~$3.9bn, +25% pre-market on a Q3 beat, closed **+30.63%**) and **SBC** (SBC Medical Group, ~$549m, +9.6% pre-market on a Q3 print and an 8-K, closed **+37.64%**) — from the routine that exists to catch same-session earnings reactions.
- Pass B2 scans the **PRE-MARKET tape of the full US universe** instead of the prior session's regular-hours tape, so "gapped today, flat yesterday" is a hit rather than a hole.
- **Two scans** (up and down), because a scanner filter is AND-ed and one call cannot express "|move| ≥ 5%":
  - Up: `POST https://scanner.tradingview.com/america/scan`, filters `[{left: type, operation: equal, right: stock}, {left: exchange, operation: in_range, right: [NASDAQ, NYSE, AMEX, NYSEArca, ARCA, PCX, BATS, IEX]}, {left: market_cap_basic, operation: egreater, right: 200000000}, {left: close, operation: egreater, right: 2}, {left: premarket_change, operation: egreater, right: 5}, {left: premarket_volume, operation: egreater, right: 10000}]`, `sort={sortBy: premarket_change, sortOrder: desc}`, range 0–200.
  - Down: the same filters with `{left: premarket_change, operation: less, right: -5}` and `sortOrder: asc`.
- **Floors and why each one is there**: market cap **> $200M** (the mid-cap floor — the miss was a $549m name and a $3.9bn name, both below Pass A's $20bn); close **> $2** (the pre-market print of a sub-$2 name is a penny-stock move, not an earnings reaction); pre-market volume **more than 10,000 shares** (the filter is `egreater`, i.e. strictly greater — the prose must not say "≥", because a name with exactly 10,000 shares does NOT qualify); |pre-market move| **at least 5%** (`egreater 5` is strictly greater than 5.00%) (the PRE_GAP tag fires at 2%, so 5% is the bar at which a pre-market gap is the day's story rather than noise).
- **NO session-volume filter on this pass.** At the 08:00 ET fire the regular session has not opened, so `volume` is 0 for every candidate and a session-volume floor would empty the pass. The pre-market volume floor is a different measure from the `volume > 10000` floor the other passes carry.
- **THE COLUMNS ARE MEASURED, NOT ASSUMED** (probed live on the `america` market, US stocks, 2026-11-15):
  - `premarket_change` — available as **both a column and a filter**. `premarket_change >= 5` returns 136 US names, so the filter is real and not silently ignored (a filter on an unknown field returns HTTP 200 with **zero** rows, so the count is the proof). Measured values: LFTO `+26.510%`, SBC `+18.071%` on the 2026-11-13 snapshot.
  - `premarket_volume` — available as **both a column and a filter** (`egreater 10000` returns 601 US names). Measured: LFTO `210,468`, SBC `43,956`.
  - `gap` — exists as a column and a filter, but it is the **REGULAR SESSION OPEN gap**, not the pre-market move: on the same snapshot LFTO's `gap` is `+27.098%` = (open 23.78 − prior close 18.71) / 18.71, while its `premarket_change` is `+26.510%` = (pre-market 23.67 − 18.71) / 18.71. At the 08:00 ET fire the session has not opened, so `gap` is not knowable yet. **Pass B2 uses `premarket_change`.**
  - `premarket_change_abs` exists but does **not** mean "the absolute pre-market move" (LFTO reads `4.96` against a `premarket_change` of `26.51`) — it is not used.
- Cron #08's pre-market gapper filters the **same two fields on the same scanner** (`cloud-prompts/skills/stock-screener-suite/scripts/premarket_pull.py`: `premarket_change` / `premarket_volume`), which is why the field names above are the house ones.
- **The rows obey the one-table rule**: a Pass B2 name that is already a Pass A or Pass B row keeps that row, and the Pass B2 hit is recorded as a **dedupe**, not as a second row. The pass publishes its coverage in source health — `pass_b2: candidates=<n> deduped_against_pass_a_b=<n> published=<n>` — so the reader can see how much the pass actually added.

**The pipeline you run MUST carry Pass B2 — and the coverage line is keyed to the DATE**

**The pipeline that renders the artifact is fetched by the prompt, and a STALE copy can win that
fetch.** Measured 2026-11-04: `raw.githubusercontent` served a blob more than 17 minutes stale, and
the CDN copies cache `main` independently of each other. The pre-Pass-B2 pipeline carries
`SCRIPT_VERSION = "2026-11-15.1"` and `REACTION_ARTIFACT_V2` — **both markers the prompt's own
`valid()` accepts** — and has no `pass_b2` in it at all.

**So: after fetching the pipeline, check it.** It must carry `SCRIPT_VERSION >= 2026-11-15.2` and
the string `pass_b2`. If it does not, **re-fetch it** (the contents API first — it is authoritative
and is not CDN-cached — then raw, then jsDelivr) and check again. If no copy carries the pass,
**say so and publish nothing**: a board with no `pass_b2:` coverage line is a board that missed
the day's pre-market gappers, silently, which is the exact failure this pass exists to prevent.

**The checker's gate is keyed to the DATE (2026-11-16), not to the version the artifact reports
about itself.** A stale pipeline reports the old version of itself, so a version-keyed assertion
would simply not run. The date is the one thing a producer cannot back-date.

**Pass C — EU/UK intraday movers (live session, especially for earnings reactions)**
- At 08:00 ET, EU exchanges are mid-session (started 03:00 ET). For these names, `change_percent` reflects today's intraday move vs previous close — i.e., overnight earnings reactions have already settled into the price.
- EU/UK market list (17 markets): `uk, germany, france, italy, spain, netherlands, belgium, austria, portugal, ireland, finland, denmark, greece, sweden, norway, switzerland, poland`.
- Two parallel `mcp__tradingview__screen_stocks` calls:
  - Up: `markets=[...17 EU markets], filters=[{field: change, operator: greater, value: 2.5}, {field: market_cap_basic, operator: greater, value: 1000000000}, {field: close, operator: greater, value: 5}], sort_by=change desc, limit=300`
  - Down: `markets=[...17 EU markets], filters=[{field: change, operator: less, value: -2.5}, {field: market_cap_basic, operator: greater, value: 1000000000}, {field: close, operator: greater, value: 5}], sort_by=change asc, limit=300`
- Note: EU threshold (2.5%) is slightly above US threshold (3% raw, 2% pre-market) because intraday moves during a live session are noisier than US extended-hours prints.
- Per-ticker catalyst (capped): `mcp__tradingview-advanced__combined_analysis(symbol, exchange, timeframe=1D)` returns TA + news sentiment + headlines in one call. Use the top headline as catalyst.
- Currency: report in local currency (from screener or quote response), note USD-equivalent via approximate FX from `mcp__tradingview-advanced__market_snapshot` (cached, single call).

**Pass D — Australia (ASX) prior-session movers (closed ~6h before scan)**
- ASX trades 10:00–16:00 AEST (UTC+10) = 20:00–02:00 ET (previous day). At 08:00 ET, ASX has been closed ~6h; `change_percent` reflects today's ASX session move vs the previous ASX close.
- ASX is the only Australian primary venue. Single exchange.
- Two parallel `mcp__tradingview__screen_stocks` calls:
  - Up: `markets=['australia'], filters=[{field: change, operator: greater, value: 2.5}, {field: market_cap_basic, operator: greater, value: 500000000}, {field: close, operator: greater, value: 1}], sort_by=change desc, limit=200`
  - Down: `markets=['australia'], filters=[{field: change, operator: less, value: -2.5}, {field: market_cap_basic, operator: greater, value: 500000000}, {field: close, operator: greater, value: 1}], sort_by=change asc, limit=200`
- Note: ASX market_cap floor dropped to $500M (vs $1B for EU/US) because the ASX 100–200 has fewer mega-caps than US/EU. ASX close floor dropped to $1 (vs $5) because ASX has many $2-5 names that US/EU would exclude — these are real, liquid ASX listings, not penny stocks.
- Per-ticker catalyst (capped): `mcp__tradingview-advanced__combined_analysis(symbol, exchange='ASX', timeframe=1D)` — same TA + news sentiment + headlines pattern as EU.
- Currency: AUD local + USD-equivalent from `market_snapshot`.

**Pass E — APAC/Gulf prior-session movers (closed before the scan)**
- India, Thailand, Indonesia, China, Singapore, New Zealand, Saudi Arabia. The UAE is **not** included — its session closes at 08:00–09:00 ET, i.e. live at the fire.
- The full filter, the screener slugs and the venue-driven Yahoo suffixes are in "The APAC/Gulf section" above.

**The six passes, in scan order:** A (US mega-caps) → B (US prior-session movers) → **B2 (US pre-market gap scan)** → C (EU/UK intraday) → D (ASX) → E (APAC/Gulf). The artifact's `Method:` line names all six, and source health publishes each pass's coverage.

## Pre-filter: Primary listing exchange whitelist (mandatory)

**Critical:** Both `screen_stocks` and `stock_screener` return secondary/retail listings alongside primary listings. Without filtering, the brief is dominated by OTC ADRs, German retail broker mirrors (Lang & Schwarz), and off-exchange duplicates of primary-listed names. Always apply this filter before any downstream call.

### Drop list (always exclude)
These are secondary, retail-mirror, or off-exchange listings — never the canonical venue for a name. Drop them on sight.

| Exchange code | What it is | Why drop |
|---|---|---|
| `OTC`, `PINK`, `OTCBB`, `GREY` | US OTC / pink sheets | ADRs and shell names — secondary to a primary listing |
| `LS`, `LSX`, `LSIN` | Lang & Schwarz retail broker (Germany) | Mirror listings — same security also traded on FWB/XETR/SWB at primary venue |
| `CHIX` | Cboe Chi-X Australia | Secondary ASX venue; primary is ASX |
| `OTC MKTS`, `OTCM` | OTC Markets | Same as OTC |

### Keep list — primary exchanges only

A name's brief entry uses the **highest-priority primary venue** that appears in the screener output. If a company is listed on both AMS and NASDAQ (e.g., ASML), the primary regional venue (AMS) wins. If a company is dual-listed on LSE and NYSE (e.g., Shell), LSE wins because the company is European-headquartered.

| Priority | Exchange | Country | Notes |
|---|---|---|---|
| 1 | `AMS` (Euronext Amsterdam) | NL | Primary for Dutch names (e.g., AD = Ahold Delhaize, ASML) |
| 2 | `BRU` (Euronext Brussels) | BE | Primary for Belgian names |
| 3 | `PAR` (Euronext Paris) | FR | Primary for French names |
| 4 | `LIS` (Euronext Lisbon) | PT | Primary for Portuguese names |
| 5 | `DUB` (Euronext Dublin) | IE | Primary for Irish names |
| 6 | `XETR` (Xetra/Frankfurt) | DE | **Canonical German listing** — preferred over FWB/SWB/GETTEX/LSX for German names |
| 7 | `MIL` (Borsa Italiana) | IT | Primary for Italian names |
| 8 | `MC` (BME Madrid) | ES | Primary for Spanish names |
| 9 | `LSE` (London SE) | UK | Primary for UK names |
| 10 | `OMXSTO` (Nasdaq Stockholm) | SE | Primary for Swedish names |
| 11 | `OSL` (Oslo Børs) | NO | Primary for Norwegian names |
| 12 | `CO` (Nasdaq Copenhagen) | DK | Primary for Danish names |
| 13 | `HE` (Nasdaq Helsinki) | FI | Primary for Finnish names |
| 14 | `VI` (Wiener Börse) | AT | Primary for Austrian names |
| 15 | `AT` (Athens Exchange) | GR | Primary for Greek names |
| 16 | `SW` (SIX Swiss) | CH | Primary for Swiss names |
| 17 | `WA` (Warsaw SE) | PL | Primary for Polish names |
| 18 | `NASDAQ`, `NYSE`, `AMEX`, `NYSEArca`, `ARCA`, `PCX`, `BATS`, `IEX` | US | Primary for US names |
| 19 | `ASX` (Australian SE) | AU | Primary for Australian names — only venue in priority table without a country-level secondary venue above it |
| 20 | `EURONEXT` | pan-EU | Fallback for Euronext-listed names (used when AMS/BRU/PAR/LIS/DUB aren't listed individually) |

### Drop list — also acceptable to drop
For some passes, drop these too if the screener output is dominated by them:
- `FWB` (Frankfurt traditional floor), `SWB` (Stuttgart), `GETTEX` (Tradegate retail), `TRADEGATE`, `DUS` (Düsseldorf) — real German exchanges but secondary to XETR. Keep one if XETR is missing; otherwise drop the secondary German venue for any company that also appears on XETR.

### Dedupe logic (after applying keep list)
For each company, if it appears on multiple primary exchanges:
1. **Regional primary beats US ADR.** E.g., ASML Holdings shows as AMS:ASML (primary) and NASDAQ:ASML (ADR). Keep AMS, drop NASDAQ.
2. **Highest-priority primary venue wins** per the table above.
3. **Within the same region, highest market cap wins.** E.g., if ARM shows as LSE:0ADF and BME:0ADF, keep LSE (priority 9 > MC at 8).
4. **Exception for genuine US mega-caps** that have no non-US primary (e.g., AAPL, MSFT) — keep the US listing.
5. **Exception for genuinely US-headquartered companies dual-listed** (e.g., CRH plc is Irish-headquartered, so LSE:CRH wins; Coca-Cola is US-headquartered, keep NYSE:KO).
6. **ASX-only names get priority 19 with no dedupe needed** — there's no US ADR of BHP that's more relevant than ASX:BHP.

### Earnings calendar data — coverage and fallback

| Region | Earnings source | Reliability |
|---|---|---|
| US (Pass A + B) | `mcp__financekit__earnings_calendar(symbol)` | ✅ Reliable — primary tool for US earnings-driven tagging |
| EU primary listings | `mcp__tradingview-advanced__combined_analysis(symbol, exchange, timeframe=1D)` | ⚠ Partial — news headlines include earnings mentions but no structured calendar. Tag as earnings-driven (Y) only if the top headline clearly mentions "earnings", "results", "Q1/Q2/Q3/Q4", "beats", or "misses" |
| AU (ASX) | `mcp__tradingview-advanced__combined_analysis(symbol, exchange='ASX', timeframe=1D)` | ⚠ Partial — same as EU; ASX-listed companies typically report in their FY half (Feb/Aug) or quarterly for the largest names. Headline detection same keywords. |
| EU / AU (fallback) | `mcp__tradingview__screen_stocks` with `earnings_release_next_date` filter | ⚠ Try first; if the field is rejected by the tool, fall back to news-only |
| EU / AU (deeper fallback) | `mcp__stocktwits__symbol_stream(symbol, limit=15)` | ⚠ Use only when both above fail — community messages may surface earnings threads |

**Known gap:** TradingView's API exposes earnings calendar data in its web UI (you can see it on each stock page), but the underlying field is not confirmed to be reachable via the MCP `screen_stocks` filter syntax. Until that's tested end-to-end, EU and AU earnings-driven tagging is best-effort. The brief explicitly notes this gap in source health.

**AU-specific earnings cycle note:** ASX-listed companies report in two main windows:
- February (interim/H1 results) — for the Aug-Jan fiscal half
- August (full-year/FY results) — for the Feb-Jul fiscal year

Major ASX names with off-cycle quarterly reports (CSL, CBA, BHP, RIO, NAB) report quarterly. The ASX earnings calendar is denser in Feb and Aug than other months — keep this in mind when interpreting "what's moving in Australia?" briefs.

## Steps

1. **Pull universes.** Eight parallel screener calls (Pass A, Pass B up/down, Pass B2 up/down, Pass C up/down, Pass D up/down).

2. **Apply primary-listing exchange whitelist** — for each screener output:
   - Drop any row where `exchange` is in the drop list (OTC/PINK/LS/LSX/LSIN/CHIX, depending on whether a primary venue is present for the same name).
   - Apply dedupe logic per the priority table above.
   - For US: drop rows where `exchange` is in `('OTC', 'PINK', 'OTCBB', 'GREY')`. Real US names come back with `exchange IN ('NASDAQ', 'NYSE', 'AMEX', 'NYSEArca', 'ARCA', 'PCX', 'BATS', 'IEX')`.
   - For EU: drop rows where `exchange` is in `('LS', 'LSX', 'LSIN', 'OTC', 'PINK')`. Keep only the priority-table exchanges.
   - For AU: drop rows where `exchange` is in `('CHIX', 'OTC', 'PINK')`. Keep only `ASX`.

3. **Per-ticker extended hours (US only).** `mcp__tradingview-advanced__stock_extended_hours(symbol)` for the deduped union of Pass A + Pass B. Concurrency: serial, ~3 calls/sec. **Cap at 60 US candidates total.** Prioritization if union exceeds 60: Pass B (regular-session big movers) first, then by `|pre-market change|` desc, then market cap desc. Extract pre-market %, post-market %, regular %, previous close, currency, exchange.

4. **Per-ticker EU quote + catalyst.** `mcp__tradingview-advanced__combined_analysis(symbol, exchange, timeframe=1D)` for the deduped Pass C union. **Cap at 30 EU candidates.** Prioritization: by `|change_percent|` desc. Extract current price, change %, currency, headline news item.

5. **Per-ticker AU quote + catalyst.** `mcp__tradingview-advanced__combined_analysis(symbol, exchange='ASX', timeframe=1D)` for the deduped Pass D union. **Cap at 25 AU candidates.** Prioritization: by `|change_percent|` desc. Extract current price, change %, currency, headline news item.

6. **Tag (US):**
   - `AMC_REACTION` = |post-market %| > 3% → headline
   - `PRE_GAP` = |pre-market %| > 2% → headline
   - `QUIET` = both within ±2% → one-liner only
   - `BOD` = no pre-market data yet → deferred to next scan, surface in source health

7. **Tag (EU):**
   - `EU_REACTION` = |intraday change %| > 3% → headline
   - `EU_NOTABLE` = |intraday change %| 2.5–3% → headline (one-liner if many)
   - `EU_QUIET` = within ±2.5% → not surfaced (live session noise)

8. **Tag (AU):**
   - `ASX_REACTION` = |intraday change %| > 3% → headline
   - `ASX_NOTABLE` = |intraday change %| 2.5–3% → headline (one-liner if many)
   - `ASX_QUIET` = within ±2.5% → not surfaced (closed session, less noise than EU but still no need to dump 50 names)

9. **Catalyst lookup — US (cap 5 calls):** for each AMC_REACTION + top 3 PRE_GAP by |pre-market %|:
   - `mcp__financekit__earnings_calendar(symbol)` → if most recent earnings date within 7d, mark earnings-driven (Y); else N.
   - If Y: `mcp__stocktwits__symbol_stream(symbol, limit=15)` → top message by likes = catalyst.
   - If N: write "non-earnings move", skip symbol_stream.
   - If both unclear: write "no fresh catalyst found" (hard rule).

10. **Catalyst lookup — EU (cap 3 calls):** for top 3 EU_REACTION by |change %|:
    - Step 4's `combined_analysis` already returned news_headlines. Reuse that field.
    - Apply earnings-keyword test: if top headline contains "earnings", "results", "Q1/Q2/Q3/Q4", "beats", "misses", "reports", "guidance" → mark earnings-driven (Y); else N.
    - Use the headline itself as the catalyst text.
    - Source health line: `eu_earnings_detection_method=combined_analysis_keywords`.

11. **Catalyst lookup — AU (cap 2 calls):** for top 2 ASX_REACTION by |change %|:
    - Step 5's `combined_analysis` already returned news_headlines. Reuse that field.
    - Same earnings-keyword test as EU.
    - ASX-specific keywords to add: "interim", "half-year", "full-year", "dividend", "ASIC" (regulator), "iron ore", "lithium", "gold" (commodity-driven moves).
    - Source health line: `au_earnings_detection_method=combined_analysis_keywords`.

12. **Sort** by max(|pre-market|, |post-market|) for US, by |intraday %| for EU and AU. Each section sorted independently.

13. **Write markdown** — the **ARTIFACT FORMAT CONTRACT v2** above is
    authoritative; the skeleton is fixed:
    1. **TL;DR** (≤5 lines): how many AMC reactions, pre-market gaps, EU reactions, ASX reactions, APAC/Gulf reactions, biggest mover across all sections, and how many EU rows are live vs settled. Note the EU/AU/APAC earnings-detection limitation.
    2. **Actionable read**: move vs the name's own history, US-listed vs foreign-only, and the one not-yet-fully-priced hypothesis per region.
    3. **US — Headline table:** ticker, venue, close, change %, pre-market %, post-market %, move vs avg daily, ref close, ref source, ref asof, US tradeable, last earnings, tag, earnings-driven, catalyst.
    4. **US — QUIET one-liners** (cap 15 lines), same required columns.
    5. **EU/UK — Headline table:** ticker, market, venue, close, change %, currency, move vs avg daily, ref close, ref source, ref asof, **settle**, US tradeable, last earnings, earnings-driven, catalyst.
    6. **AU (ASX) — Headline table:** same, without the market column.
    7. **APAC/Gulf — Headline table:** same as the EU/UK table (with the market column).
    8. **Source health:** call counts, the reference-close result, `rows_dropped_stale_ref`, the pre-market check, dedup stats, the settlement-state summary, the per-market row counts, `degraded_sources: <n>` with one numbered entry per degraded source.
    9. **Audit line:** the fixed `earnings-reaction target=…` line, including `apac_reactions`, `rows_dropped_stale_ref` and `degraded_sources`.
    **No `## Catalysts` section** — the catalyst is the last column of its row.

14. **The settlement pass (12:15 ET, second slot).** Run the same pipeline with
    `--mode settle`. It republishes the EU/UK rows with their settled close and
    move, adds `Move @08:00` and `Δ vs scan` from the morning artifact, and
    publishes the `scan_to_settle` drift summary. It publishes **no US rows**
    (the US session is open at 12:15 ET). See "The settlement pass" above.

## Hard rules
- Read-only. No trade ideas.
- **One name, one table, one row.** Never a separate `## Catalysts` section — the catalyst is the last column of its row.
- **The reference close is a hard gate**, resolved before the tables are built. A row that fails it is dropped AND counted (`rows_dropped_stale_ref`).
- **Session selection is by DATE and order, never by a modal time-of-day** — a DST boundary shifts the ET stamp of the same session by an hour.
- **The reply's `errors:` count equals the artifact's `degraded_sources` count** — one entry per degraded source.
- **A row says whether its move is finished** (`Settle`). A live EU/UK move is a mid-session snapshot; the settlement pass publishes where it closed.
- **A verdict requires research.** `Y`/`N` only for a researched row; an unresearched row publishes `—`.
- **Never publish a live intraday price as a close** — that is why the settlement pass skips the US.
- Don't fabricate catalyst headlines — if the relevant call returns nothing, write "no fresh catalyst found" and move on.
- Always show both pre- and post-market % for US when both present.
- EU threshold (2.5%) > US pre-market threshold (2%) — live session is noisier than extended hours.
- **Always apply the primary-listing exchange whitelist before downstream calls.** Without it, the brief is dominated by retail mirrors and OTC duplicates.
- **Published-row caps: EU 30, AU 25.** The US tables are NOT capped at 60: the reference-close cross-check is cheap (one Yahoo daily-chart call per row) and it must cover **every** row that reaches a table — a stale-reference row can hide anywhere, so a top-N subset would leave unvalidated rows published. The US ceiling is therefore the screener passes themselves (Pass A top-250 by market cap, Pass B top-200 each way, Pass B2 top-200 each way). **The cap that matters is the CATALYST budget: 16 lookups per run, allocated by the evidence gap (the US slice covers the fresh earnings events, the EU/AU/APAC floors are never squeezed, and the leftover goes to the region with the most unexplained rows).**
- **Every published row is validated**, including the US QUIET one-liners — that is why they carry the reference-close columns too.
- Catalyst calls: **up to 16/run**, allocated by the evidence gap — read the split from `earnings/<date>-catalyst-targets.json`.
- **Coverage gap detector** — for each screener call, if `total_count < 5` AND the market should be open (per the holiday table below), log `_warn=empty_screener_<market>` to source health. This catches the `south_korea` → 0 bug class without changing the screener params. Same logic also serves as the holiday detector — closed markets return 0 or near-0 rows.
- Do NOT scan all 500 S&P 500 names — top-200 is the upper bound.
- Do NOT expand the EU/ASX list without verifying screener coverage first.
- For EU and AU names, prefer the primary regional venue over the US ADR — see dedupe logic.
- AU market_cap floor ($500M) and close floor ($1) are lower than EU/US because ASX has fewer mega-caps and more $2-5 names that are real, liquid listings — not penny stocks. Don't tighten these without confirming ASX universe shrinks dangerously.

## Holiday / market-status detection

The cron fires every weekday at 08:00 ET. Some days are holidays in one or more regions. The cleanest signal is the screener itself — if a market is closed, `screen_stocks` returns 0 or very few rows. Use this as the holiday detector.

| Region | Closed-day signal | Common holidays |
|---|---|---|
| US | screener returns < 5 | New Year's Day, MLK Day, Presidents Day, Good Friday, Memorial Day, Juneteenth, Independence Day, Labor Day, Thanksgiving, Christmas |
| UK / EU | screener returns < 5 | UK bank holidays, Easter Monday, May Day, Spring/Autumn bank holidays, Christmas, New Year, regional saints' days |
| AU | screener returns < 5 | Australia Day (Jan 26), ANZAC Day (Apr 25), Queen's Birthday, Christmas, Boxing Day |

**Action when `total_count < 5`:** log `market_open_<region>=FALSE` in source health. Surface a one-line note in the TL;DR: "EU closed for holiday" or similar. The brief still runs but the section is marked "no data — closed".

**Don't fabricate a fallback date.** If a market is closed, the most recent data is the prior trading day's close. Use that if needed, but mark `_data_date=<prior_trading_day>` in source health.

## Cross-region dedupe

Within a single brief run, dedupe happens primarily via the priority table (within-region). Cross-region dedupe is best-effort and uses these heuristics:

1. **A single screener call returns exchange-specific tickers.** EU Pass C queries `markets=['uk','germany',...]` and returns AMS:ASML, LSE:0ADF, etc. — no NASDAQ rows. US Pass A returns only US exchanges.
2. **Same company across regions.** A company dual-listed on AMS + NASDAQ (e.g., ASML) would appear in EU Pass C as `AMS:ASML` AND in US Pass A as `NASDAQ:ASML`. The current implementation does NOT dedupe these — they appear in separate sections.
3. **Workaround for v3.2:** sort by `market_cap` desc; the regional primary (AMS) is listed first and the US ADR (NASDAQ) appears later in a different section. Visually obvious but not deduped.
4. **Plan for v4:** add a name-match dedupe step that strips US ADR rows when the regional primary appears in any pass. Use yahoo-finance `get_company_info` to resolve primary ISIN, then dedupe by ISIN across passes.

For now, document the cross-region case in source health: `cross_region_dupes_known=2` (count of companies appearing in multiple sections).

## Out of scope
- Options flow on earnings names → `unusual-options-flow-daily`.
- Earnings reminder (same-day BMO/AMC calendar) → `earnings-reminder`.
- Detailed earnings analysis (EPS surprise, guidance diff) → out of scope.
- Asia (JP/TW/HK) coverage → different cron slot needed (their session close is before US pre-open, so we'd need a 23:00 ET slot). Tracked for v4.
- Canada (TSX) → trivial to add via `markets=['canada']` as Pass E; pending user confirmation.
- New Zealand (NZX) → can pair with ASX as a Pacific-region pass; pending.
- Structured EU/AU earnings calendar — TradingView's `earnings_release_next_date` screener field is a known untested path; documented above.

## Change history
- **v6 — 2026-11-15.** **Pass B2 — the US pre-market gap scan ("gapped today, flat yesterday")**, added after a measured miss. (1) On Friday 2026-11-13 the US universe was Pass A (the top-250 US names above $20bn) plus Pass B (the PRIOR session's movers: |change| ≥ 3%, market cap > $1bn, close > $5), so a name that was FLAT in the prior session and is not a $20bn mega-cap fell through both: **LFTO** (Liftoff Mobile, ~$3.9bn, +25% pre-market, closed **+30.63%**) and **SBC** (SBC Medical Group, ~$549m, +9.6% pre-market, closed **+37.64%**) were both missed by the routine that exists to catch same-session earnings reactions. Pass B2 scans the **pre-market tape of the full US universe** instead of the prior session's regular-hours tape. (2) The filter, on the same `america` scanner and the same two fields cron #08's gapper uses: US venues, `market_cap_basic > $200M`, `close > $2`, `|premarket_change| >= 5%`, `premarket_volume >= 10,000` shares; two scans (up and down) because a scanner filter is AND-ed; **no session-volume floor**, because at the 08:00 ET fire the regular session has not opened and `volume` is 0 for every candidate. (3) **The columns were measured, not assumed**: on 2026-11-15 `premarket_change` and `premarket_volume` are available as BOTH a column and a filter on the `america` market for US stocks (`premarket_change >= 5` returns 136 names, `premarket_volume >= 10000` returns 601 — a filter on an unknown field returns 200 with ZERO rows, so the counts are the proof). The `gap` column also exists, but it is the **REGULAR SESSION OPEN gap**, not the pre-market move (measured: LFTO's `gap` is +27.098% = (open 23.78 − prior close 18.71) / 18.71, while its `premarket_change` is +26.510% = (pre-market 23.67 − 18.71) / 18.71) and the session has not opened at 08:00 ET, so **`premarket_change` is the column used**; `premarket_change_abs` does NOT mean "absolute pre-market move" (LFTO reads 4.96 against a `premarket_change` of 26.51) and is not used. (4) The rows obey the one-table rule — a Pass B2 name that is already a Pass A or Pass B row keeps that row and the hit is recorded as a **dedupe** — and the pass publishes its coverage (`pass_b2: candidates= deduped_against_pass_a_b= published=`), so the artifact's `Method:` line names **six** passes. Measured on the 2026-11-13 data: **28 candidates (22 up, 6 down), 7 deduped against Pass A/B, 21 published — with LFTO and SBC both among the 21.** (5) The artifact **format** did not change, so the capability marker `REACTION_ARTIFACT_V2` does NOT change; only the coverage grew. (6) The checker (`tools/check_reaction_artifact.py`) now ASSERTS the new coverage rather than describing it, version-gated from pipeline 2026-11-15.2 so an artifact published before Pass B2 existed is not judged retroactively; `tools/test_reaction_contract.py` proves the gate bites on both the PASS and the FAILURE path.
- **v5 — 2026-11-15.** The **bulk earnings calendar** becomes the source of record for the US earnings date and the ranking key for the catalyst budget. (1) `Last earnings` now comes from Nasdaq's public earnings calendar (scan date + 7 prior days, one call each); the screener's `earnings_release_date` is the fallback and every disagreement is published as `earnings_field_stale_rows` + `earnings_field_stale_detail`. Measured 2026-11-12: NBIS published `2026-08-12 (92d ago)` although it had reported PRE-OPEN that morning — a FALSE-verdict trap, not a missing one, and the replay also caught ANAB and FLO. (2) The catalyst budget is **allocated by the evidence gap** and capped at 16: the US slice covers the `fresh` rows (the reports dated on the scan date) plus the next freshest, the EU/AU/APAC floors are never squeezed, and the leftover goes to the region with the most unexplained rows; the split is published in the catalog file header, in source health and in the targets JSON, never pinned in a prompt. (3) The instrument form comes from the SECURITY, not the issuer's country: `(ADR)` only when the scanner's `type` is `dr` (or the description names a depositary), so NBIS/AEM/TSEM/NVMI/FN/IREN/DPC are no longer mislabelled ADRs (16 rows on 2026-11-12), and a foreign row's US line reads `US line (VENUE:TICKER)` unless it really is a depositary form. (4) A calendar-covered row that was NOT researched keeps an event line (`Q3 2026 results, report date today (Nasdaq earnings calendar; no headline lookup), consensus EPS ($0.61)`) and carries NO verdict.
- **v4 — 2026-11-05.** The **ARTIFACT FORMAT CONTRACT v2** (`REACTION_ARTIFACT_V2`) above. Four fixes: (1) the pre-market checker's Eastern-time handling — the ET window is now 04:00-09:30 ET resolved with `zoneinfo` on a WINTER and a SUMMER date, the base close is the IMMEDIATELY prior session, and the pipeline is fetched only when it carries the capability marker, so a stale CDN blob cannot run the old procedure; (2) the reference close is resolved FIRST from one authoritative source and is a hard gate — every published row carries `Ref close` / `Ref source` / `Ref asof`, and a row whose base is older than the previous session is dropped and counted in `rows_dropped_stale_ref`; (3) a new `## Actionable read` section with the `Move vs avg daily` and `US tradeable` columns and one not-yet-fully-priced hypothesis per region; (4) the one-table rule — the separate `## Catalysts` section is gone and the catalyst rides in the row. `degraded_sources` counts each degraded source separately and the reply's `errors:` must match it. Checker `tools/check_reaction_artifact.py`, regression test `tools/test_reaction_contract.py`.
- **v3.3 — 2026-09-23.** Added **coverage gap detector** — `total_count < 5` triggers `_warn=empty_screener_<market>`. Catches the `south_korea` → 0 bug class. Also serves as holiday detector. Added **Holiday / market-status detection** section documenting common holidays per region (US, UK/EU, AU) with the screener-as-signal pattern. Documented **cross-region dedupe** limitation (companies like ASML on AMS + NASDAQ appear in separate sections; v4 plan to dedupe via ISIN from yahoo-finance `get_company_info`).
- **v3.2 — 2026-09-23.** Added Pass D (Australia/ASX). 1 market (australia), threshold 2.5%, market_cap floor $500M (lower than EU/US because ASX has fewer mega-caps), close floor $1 (lower because ASX has many $2-5 real listings). ASX exchange added to priority table at #19. Catalyst budget 2 calls for AU (cap by |change %|). Earnings cycle note for ASX (Feb interim + Aug full-year reporting seasons). Out-of-scope: TSX (Pass E candidate) and NZX.
- **v3.1 — same day.** Added mandatory **primary-listing exchange whitelist** (step 2). Drops OTC/PINK/LS/LSX/LSIN retail mirrors and FWB/SWB/GETTEX secondary German venues when XETR is also present. Dedupe rule: European primary beats US ADR. Documents EU earnings calendar gap.
- v3 — same day. Added Pass C (EU/UK intraday movers). 15 markets. Used `combined_analysis` for EU catalyst. Did NOT have the primary-listing filter — output was dominated by retail mirrors.
- v2 — same day. Broadened US universe from watchlist(12) + hardcoded mega-cap(13) to S&P 500 top-200 + prior-session full-universe screener. Added stocktwits catalyst lookup for US earnings-driven headlines. Old watchlist-only Pass A and hardcoded 13-name Pass B both retired.
- v1 — original design: watchlist cross-referenced against earnings_calendar + hardcoded 13-name mega-cap list. Missed non-watchlist S&P 500 earnings reactions entirely.
