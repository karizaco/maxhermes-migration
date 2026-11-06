---
name: Unusual options flow daily
description: >-
  Daily scan of unusual options activity ranked by RELATIVE volume — how unusual each
  contract is against its own chain, its own expiry, its own name's option-volume history
  and the name's cash turnover — so a $1.8B name can outrank a $5.2T one. Uses the Cboe
  delayed-quote option-chain CDN, the Cboe historical options-volume service and the
  TradingView america scanner. Runs weekdays 16:35 ET, just after the close.
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

# Unusual options flow — daily, ranked by RELATIVE volume

## What changed on 2026-11-06, and why

**Three defects were fixed on 2026-11-06, all of them "the number was right, its MEANING was not".**

1. **Every published ratio now names its population.** The routine publishes three books and they
   describe three different universes: the **relative screen** (top ~60 US names by cash volume),
   the **series book** (the 8 Pass-B mega-caps) and **Pass A** (the published watchlist). Until now
   only the first two existed and neither said so in the front matter, so a reader saw "put/call
   0.74 → CALL" with no way to know it described 8 mega-caps while the headline screen described 60
   names. **A put/call ratio without its universe is not interpretable.** The front matter now
   carries one `*_universe:` line per published ratio, and every ratio row names its population.

2. **The bias tag is now self-checked before the file is written.** The 2026-11-02 artifact
   published `bias: PUT` on a put/call ratio of 0.84, which the fixed thresholds (`< 0.85 → CALL`)
   make a CALL — a tag that contradicted its own number, published into the series. The engine now
   re-derives every published tag from its own rows and **aborts the write** on a contradiction
   (exit 3, no artifact, no push). A tag that contradicts its own ratio is a hard error and is never
   published.

3. **Pass A is a real pass.** The watchlist was a local file on the Mavis host
   (`research/watchlist.yaml`), unreachable from the Cloud runtime, so this leg never ran here and
   every artifact since 2026-10-14 carried the same "not published" line. The watchlist is now a
   **published file** (`refs/watchlist.yaml` in the outputs repo), fetched at run time, and Pass A
   is scanned and published with its own ratios.

**A fourth book was added for the population question:** the **wide book** — the *same* legacy
absolute method as the series book, applied to the relative screen's whole ~60-name universe. The
series book answers "what did the 8 mega-caps do", the wide book answers "what did the market's
most-traded names do", and only the population differs between them. The series book is NOT
replaced: it carries the published put/call series since 2026-10-16.

## What changed on 2026-11-05, and why

**This routine now ranks by relative volume, not absolute volume.** The old headline ranked
contracts by V/OI across a fixed 8-name mega-cap universe, so the top of the book was
structurally the largest names — NVDA, TSLA, AAPL, AMZN, IWM — regardless of what was actually
unusual. Measured on the 2026-11-04 session: the absolute top 10 and the relative top 10 shared
**1 name of 10**, and the names that scream on absolute volume were *below their own baselines*
(TSLA 0.44×, AMZN 0.52×, NVDA 0.75× of their own 10-session options-volume average) while the
quiet-looking mid-caps were 2-8× their own history (ARRY 8.16×, FIS 7.38×, GRAB 3.79×, CLSK 2.62×).

The **relative screen is now the headline**. The legacy absolute book is still computed and
published, on the legacy universe and the legacy method, so the put/call series published since
2026-10-16 stays comparable — but it is the secondary section.

**The universe changed.** The 8-name Pass-B universe is all mega-caps, so a relative screen over
it cannot surface a mid-cap: there are none in it. The relative screen runs over the **top ~60 US
names by cash volume** from the TradingView america scanner, plus the routine's 8.

**The published artifacts change shape.** Every artifact from 2026-11-05 onward leads with the
relative screen and carries the legacy book as a secondary section. The put/call series numbers
themselves are unchanged in method, so the series continues.

**The transition day is 2026-11-04, and it stays the transition day.** That artifact is the one
on which the screen was *introduced* — over the 8-name Pass-B universe, because the wider universe
and the engine landed together on 11-05 — and it published it as a supplementary section. Its
section title used to read "supplementary — not the headline metric", which read as a contradiction
of the rule above; it now says plainly what is true: the screen was introduced on that date, it
became the headline on 2026-11-05 when the universe widened, and **the reason it had to widen is
the reason the 8-name screen could not be one** — a relative screen over an 8-name mega-cap
universe cannot surface a mid-cap, because there are none in it.

**What the reply must say about this, every time.** The headline of the reply is the relative
screen, never the legacy put/call tag. When the reply quotes ANY ratio, its first line names the
population behind it: "put/call 0.74 → CALL **on the 8 Pass-B mega-caps**" is readable;
"put/call 0.74 → CALL" is not, because a trader who does not know the universe widened is reading
the wrong number. If the reply leads with the series book's ratio, it must also say that the
headline screen covers a wider population and why.

## When
- Cron: `35 16 * * 1-5` America/New_York (weekdays, 16:35 ET — just after the cash close, so the day's volume is settled)
- Manual: user asks "any unusual options activity today?" or "show me unusual options flow"

**Why post-close — do not "restore" the original hour.** The original local skill targeted
`55 9 * * 1-5` (09:55 ET, ~25 min after the open). The deployed time is 16:35 ET and that is
deliberate, not drift. V/OI divides *volume* by *open interest*: a 25-minute post-open volume
sample measured against a full prior-day open interest is mechanically depressed and unstable,
whereas after the close the day's volume is settled and the ratio is reproducible day to day.
A migration that trusts the original 09:55 hour would break the comparison with the published
series and re-introduce the pre-close instability. Keep 16:35 ET.

**A relative screen is also the robust one on a partial day.** Peer ratios, expiry shares, chain
shares and cash-turnover ratios are all computed *within one snapshot*, so a partial session
scales every contract together; only V/OI is distorted (Cboe's open interest is the prior
session's settled figure, so intraday V/OI is an upper bound). The routine still runs post-close.

## Output
- `C:\Users\admin\.minimax\projects\coding-shared\research\options-flow\YYYY-MM-DD.md`
  _(In Cloud this path does not exist — it is the local Mavis host's location. In Cloud, write to the `## OUTPUT` path in the cron prompt.)_
- Chat reply: in Cloud the format is the `## DELIVERY` block in the shared `PROMPT-BLOCKS.md`
  (prose opener → `### Signal` → `### Method & caveats` → `### Files` → `### Push / errors`).
  There is **no line cap**; long-form detail belongs in the artifact file. The
  "compact summary, top 5 only" rule is the local Mavis host's chat format, not Cloud's.

## THE ENGINE — fetch once, run it, do not re-implement it

The relative screen needs ~60 chains and ~150k contracts. That is far past what can be parsed in
context, so it is a **published script**, not a procedure:

`cloud-prompts/_shared/relvol_screen.py` (marker `RELVOL_SCREEN_V1`)

```bash
S=/workspace/relvol_screen.py
for U in \
  "https://api.github.com/repos/karizaco/maxhermes-migration/contents/cloud-prompts/_shared/relvol_screen.py?ref=main" \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/relvol_screen.py" \
  "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/relvol_screen.py" ; do
  curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" -o "$S.tmp" "$U" 2>/dev/null
  # a 404 body is non-empty JSON, and an OLD copy silently lacks the new sections
  # BOTH markers are required: RELVOL_SCREEN_V1 (the engine family) AND ENGINE_REV=2 (the rev
  # that adds the universe-labelled front matter, the bias-tag self-check, the wide book and
  # Pass A). The rev marker is what stops a pre-2026-11-06 copy from winning the ladder — the
  # old copy carries RELVOL_SCREEN_V1 too, so one marker cannot tell them apart.
  if head -1 "$S.tmp" 2>/dev/null | grep -q '^#!' && grep -q 'RELVOL_SCREEN_V1' "$S.tmp" 2>/dev/null \
     && grep -q 'ENGINE_REV=2' "$S.tmp" 2>/dev/null; then
    mv -f "$S.tmp" "$S"; break
  fi
  rm -f "$S.tmp"
done
```

If the copy you fetched carries `RELVOL_SCREEN_V1` but NOT `ENGINE_REV=2`, you have a pre-2026-11-06
engine: re-fetch with the ladder above (the contents API is tried first and is authoritative), and
if it still will not serve rev 2, fall back to the legacy method below and say so in the header.
**Do not publish an artifact from a pre-rev-2 engine and call it current** — it has no
universe-labelled front matter and no bias-tag self-check.

**Run it with the FIRE's scheduled date**, not `date` at execution time:

```bash
python3 "$S" --date "$FIRE_DATE" --out /workspace/options-flow/$FIRE_DATE.md --universe 60 --jobs 8
```

`$FIRE_DATE` is the `fire-date:` printed by the shared window check (the prompt's `## WINDOW
CHECK` block) — the same date the artifact path uses, so the gate and the artifact can never
disagree. The script prints a JSON summary on stdout (counts, the top relative names, the
series-book bias tag, the source errors) — **read that summary and quote its numbers in the chat
reply rather than re-deriving them by hand.** The script exits non-zero only if it could not
fetch a universe at all; per-name failures are recorded in the artifact's `## Source health` and
in the JSON `errors` list.

**If the engine cannot be fetched or fails to run:** fall back to the **legacy method** — the
8-name Pass-B universe, per-underlying top-10 by volume, the legacy filters, the bias tag — and
write the artifact with `method: legacy_fallback (relvol engine unavailable: <reason>)` in the
header. Partial data beats no data: a delivered legacy artifact is far better than a failed run.

**Runtime:** ~25 s for 60 names (chains are fetched 8-way in parallel; the own-history baseline
is 2 monthly files). The legacy guidance of "< 90 s" applied to 8 names and no baseline fetch;
the current figure is measured, not estimated.

## Universe

**Relative screen (headline):** the **top 60 US names by cash volume** from the TradingView
america scanner, filtered `type in (stock,dr)` + `exchange in_range [NASDAQ,NYSE,AMEX]` +
`close > 1`, plus the routine's 8 Pass-B names. This is deliberately NOT a mega-cap list: the
top-60-by-cash-volume list on a live session is roughly 80% mid/small-caps (crypto miners,
AI-infra, power names), which is where relative anomalies live. Cap at 60.

The Pass-B ETFs (IWM, GLD, TLT) are funds and the stock scan misses them — ask for them by name
in a second scan and take their cash volume from there. A name the Cboe chain refuses (HTTP 403,
no listed options series) is **not a failure**: record it as `no listed options series` and carry
on. Measured 2026-11-04: CHSN, CRIS, DKI, OMH.

**Series book (secondary):** the 8 Pass-B names, unchanged — IWM, GLD, TLT, AAPL, MSFT, NVDA,
GOOGL, AMZN.

**Wide book (secondary, population-matched):** the **same legacy absolute method** as the series
book, applied to every name in the relative screen's universe (the ~60 names with a chain). Only
the population differs, so the two books are directly comparable. It answers "what did the market's
most-traded names do" next to the series book's "what did the 8 mega-caps do". It does **not**
replace the series book, which carries the published put/call series since 2026-10-16.

**Pass A — the published watchlist:** the user's watchlist is a **published file**, fetched at run
time:

```
https://api.github.com/repos/karizaco/minimax-cloud-outputs/contents/refs/watchlist.yaml?ref=main
https://raw.githubusercontent.com/karizaco/minimax-cloud-outputs/main/refs/watchlist.yaml
```

- **Present (HTTP 200):** parse the tickers, scan their chains with the legacy method, and publish
  the Pass A section with its own ratios and its own universe line. A watchlist name outside the
  relative screen's universe gets its chain fetched separately; it does **not** join the relative
  screen (that screen's universe is fixed — top ~60 by cash volume — and adding names to it would
  change what the headline measures).
- **Absent (HTTP 404 everywhere):** omit Pass A and say so ONCE in `## Source health`. Never ship
  an empty Pass A section and never invent a watchlist.
- A watchlist name the Cboe chain refuses is recorded as `no listed options series`, not an error.

**Exclusion list (do NOT scan — see Hard rules)**
- Broad-index mega-cap ETFs: SPY, QQQ (their chains are dominated by dealer-gamma and 0DTE market-maker hedging; V/OI gets inflated and the daily put/call bias tag becomes "PUT" on every red day for structural reasons, not positioning).
- Levered / thematic ETFs: SOXL, SOXS, SMH, TQQQ, SQQQ, UVXY, VXX. Same structural-noise problem, plus single-stock levered ETFs already violate the existing "no naked single-stock levered ETFs" rule.

## The five relative measures

Each measure normalises against a different size bias. The composite needs all five.

| Measure | Normalised against | What it catches |
|---|---|---|
| **Peer ratio** | the median volume of the other *meaningfully-traded* strikes (volume ≥ 50) in the same underlier + expiry + side | a strike trading 30-100× its own chain's typical strike |
| **Share of expiry** | that expiry+side's total volume in the chain | one strike taking 60-90% of its own expiry's flow — a concentrated bet |
| **Share of chain** | the underlier's whole options tape | how much of the name's flow sits on one strike |
| **Opt % of cash vol** | the underlier's share volume | cross-name normaliser: options contracts vs the shares that actually traded |
| **Own-history** | the name's own 10-session average options volume | the only measure independent of the contract's chain size — is today's options activity unusual *for this name*? |

**The peer median must be over strikes with volume ≥ 50.** Over *all* active strikes the median
collapses into the near-dead tail and the ratio inflates 5-15× (measured 2026-11-04: RIOT 24C
read 13.1× on the volume≥50 median vs 207× on the all-active one). Publish the group median and
the group size on every row so the ratio is auditable.

**The own-history baseline is the single most important column.** A ratio on a trivial number is
still a trivial number — publish the ratio *and* the volume beside it, always.

**The composite score:**

```
z(peer_ratio) + z(expiry_share) + z(opt_pct_cash) + z(V/OI) + 1.5 * z(own_history)
```

z-scores are computed across all eligible contracts. The own-history term carries the highest
weight because it is the only component independent of the contract's own chain size. **Publish
every component on every row** so the ranking can be re-derived or re-weighted; a single-metric
view is a sort away.

## Filters (relative screen)

- volume ≥ 1,000 contracts
- theoretical value (theo) ≥ $0.05 — real contracts, real premium dollars
- V/OI ≥ 1.0
- DTE ≤ 60
- window: the **4 earliest LISTED expiries** per name, parsed from the OCC contract symbol

**No absolute pre-cut.** The relative screen scores every contract in the window. The legacy
top-10-by-volume pre-cut is a *series* rule and stays in the series book only — it is what makes
the published series comparable, and it must not leak into the relative screen.

## Artifact sections (in this order)

1. Header block: date, method, engine version, universe, counts, filters, composite formula, the three sources, the baseline session, the series-book bias tag, status.
2. **Relative-volume leaders — multi-day book (DTE ≥ 1)** — the headline.
3. Relative-volume leaders — all expiries (0DTE included), with the 0DTE IV caveat.
4. **Name level — options activity vs the name's own 10-session baseline**, plus the *quiet* names (the ones that look loud on absolute volume but are below their own history).
5. Name level — options contracts vs cash shares traded.
6. Contrast — the absolute screen's top 10 next to the relative screen's top 10, and the overlap count.
7. **Series book (legacy absolute method)** — bias tag, the three slices, the premium-dollar read, the top 10 strikes by V/OI.
8. **Wide book** — the same legacy method over the relative screen's whole universe, next to the series book, so the two populations can be read against each other.
9. **Pass A — the published watchlist** — its own ratios, its own universe line, or an explicit statement that it was omitted and why.
10. `## Source health` — per source: URL/query, status, result; every degraded or blocked source named.
11. `## Caveats`.
12. Audit line: `unusual-options-flow target=options-flow:<date> underlyings=<n> strikes_kept=<n> bias=<call|put|mixed> method=relative`.

### The front matter names the population of every ratio

The header block must carry one `*_universe:` line for each book, so a reader never has to guess
which population a number describes:

```
headline_metric: the relative-volume screen … — NOT a put/call ratio
relative_screen_universe: top 60 US names by cash volume … — 60 underlyings with a chain, 2 without
series_book_universe: the 8 Pass-B mega-caps (IWM, GLD, TLT, AAPL, MSFT, NVDA, GOOGL, AMZN)
series_book_bias: CALL (put/call 0.74) — contract-count ratio on series_book_universe
series_book_economic_bias: PUT (put/call 1.44) — theo >= $0.05 slice on series_book_universe
series_book_premium_ratio: 3.47 — premium-dollar ratio on series_book_universe
wide_book_universe: the 60-name relative-screen universe — the SAME legacy method applied to it
wide_book_bias: PUT (put/call 1.02) — contract-count ratio on wide_book_universe
pass_a_universe: the published watchlist (refs/watchlist.yaml) — 8 tickers …
bias_tag_thresholds: put/call < 0.85 -> CALL, > 1.20 -> PUT, else MIXED (the tag names the DOMINATING side)
```

A ratio whose population is not named in the front matter is a defect, not a style issue.


## Hard rules
- Read-only. Never suggest a trade or sizing.
- **Never include mega-cap index ETFs or high-volume levered ETFs** (SPY, QQQ, SOXL, SOXS, SMH, TQQQ, SQQQ, UVXY, VXX). Their option chains are dominated by dealer-gamma and 0DTE market-maker hedging, which inflates V/OI ratios artificially and biases the daily put/call tag toward "PUT" on every red day for structural reasons. Surface single-name positioning instead. IWM/GLD/TLT are kept — their directional signal is more interpretable.
- Never include naked single-stock levered ETFs (same as `us-stocks-in-play` exclusion).
- **A relative screen over a fixed universe can only find anomalies inside that universe.** Say how many names were screened and how many had no listed options series.
- The headline of this routine is the **relative** screen. The legacy book is continuity, not the headline — never lead the chat reply with the legacy bias tag.
- **Every published ratio names its population.** The front matter carries one `*_universe:` line per book, and every ratio row names its universe. A put/call ratio without its universe is not interpretable, and the reply's **first line** names the population behind any ratio it leads with.
- **A bias tag that contradicts its own ratio is never published.** The engine re-derives every published tag from its own rows and **aborts the write** (exit 3, no artifact, no push) on a contradiction. If you are running the engine by hand, `python3 relvol_screen.py --self-test` proves the guard bites before you trust it.
- No trade, no sizing, no direction on any name.


## Cloud data conventions

These are the conventions the Cloud runtime actually needs. Each one was found by a run that
got it wrong first, so each carries the evidence that established it. **Follow them exactly** —
they are not style preferences, and several of them silently produce a plausible-looking wrong
answer if you ignore them.

1. **Take the expiry date from the OCC contract symbol, never from a timestamp.** Yahoo's
   `expirationDate` epoch is 00:00 **UTC** of the expiry day, so rendering it in US/Eastern
   returns the *previous* calendar day. The contract symbol encodes the date unambiguously
   (`AAPL261028C00345000` → expiry 2026-10-28). Key every expiry, DTE and cross-source join on
   the symbol. The chain carries **no expiry field at all** — parse it:
   `strike = int(s[-8:]) / 1000`, `side = s[-9]`, `date = s[-15:-9]`, and **cast all three date
   parts to int** or the exception is swallowed and the run reports "0 contracts" with no error.
   Root regex is `[A-Z]{1,6}` (class B/C/D/F/I roots exist). *(Established 2026-10-27.)*

2. **ITM/OTM is side-aware.** A call is ITM when `strike < spot`; a put is ITM when
   `strike > spot`. Labelling from the sign of `(strike − spot)` alone inverts **every** call row
   — a GOOGL 400 call with spot at 320.21 is 25% *out* of the money, not in. Validate against
   Yahoo's own `inTheMoney` field (1,037/1,037 rows agreed once the rule was side-aware).
   *(Established 2026-10-27; re-validated 2026-11-04, 73/73.)*

3. **Yahoo drops the session-date 0DTE after the close.** Hours after the 16:00 ET close the
   just-expired session expiry is gone from Yahoo's `expirationDates`, yet those contracts traded
   heavily (IWM 0DTE alone was 778,086 contracts on 2026-10-27). Use Cboe to fill the session-date
   expiry, and reconstruct the expiry window as the **4 earliest expiries** across
   {Yahoo's list} ∪ {the session date}. *(Established 2026-10-27.)*

4. **Cboe's `iv` is a decimal fraction, not a percentage.** `iv: 0.3` means 30%, not 0.3%.
   Read literally, the IV column is out by 100×. Confirm the unit by inverting Black-Scholes
   against the contract's mid-quote before trusting the column. *(Established 2026-10-29.)*

5. **Cboe reports open interest of exactly zero on some contracts**, because they are series
   opened during the current session. V/OI is then *undefined*, not huge — a zero denominator
   puts those rows at the top of a naive ranking with no meaning attached. Report them as `n/a`
   and exclude them from the V/OI ranking. *(Established 2026-10-30.)*

6. **Cboe's IV is unreliable on deep-ITM, near-worthless contracts.** On the same contract
   (AAPL 350 call, last $0.01) Cboe reported IV 94.9% against Yahoo's 14.8% — an artifact of
   pricing a near-worthless option off a $0.01 print. Where both exist, prefer Yahoo's IV on
   deep-ITM contracts and quote Cboe's only as a divergence note. *(Established 2026-10-28.)*

7. **Contract count is not economic size.** Roughly half the kept volume can sit in contracts
   whose theoretical value is below $0.05 — real contracts, trivial premium dollars. Report the
   share of kept volume in sub-$0.05 contracts alongside the headline, and give the
   economically meaningful read alongside it. *(Established 2026-10-30: 49.5% of kept volume.)*

8. **A lost day is only partly recoverable — the aggregate layer is archival, the strike layer is
   not.** If a scheduled run produces no artifact, the strike-level book for that date is
   **gone for good**: Yahoo's options endpoint returns HTTP 200 with an *empty* contract list for
   every expired expiry (verified 2026-11-03 for the 2026-10-19 and 2026-10-23 expiries), and
   Cboe's delayed-quote service serves only the live session. Per-strike volume, open interest,
   IV and moneyness cannot be recovered for a past date by any reachable source.

   The **aggregate** layer *can* be recovered, and it is exact — Cboe's historical options-data
   service returns per-underlying daily volume for any past date, split by venue:

   ```
   https://www.cboe.com/us/options/market_statistics/historical_data/download/class/
     ?reportType=volume&volumeType=sum&volumeAggType=daily
     &symbolType=underlying&symbol=<SYM>
     &startDate=<YYYY-MM-DD>&endDate=<YYYY-MM-DD>
     &exchanges=CBOE&exchanges=BATS&exchanges=C2&exchanges=EDGX
   ```

   It returns CSV: `Trade Date, Underlying, Product Type, Exchange, Volume`. Send
   `Referer: https://www.cboe.com/us/options/market_statistics/historical_data/` and a browser
   `User-Agent`, or the request is refused.

   **The `all_symbols` variant is the one to use for the own-history baseline** — it returns
   every underlying for a whole month in ONE call (6.5 MB for October 2026, 219,701 rows,
   3,815 symbols on a typical day), which replaces 60 per-symbol calls with 2 (previous month +
   current month, so the 10-session average can span the month boundary):

   ```
   https://www.cboe.com/us/options/market_statistics/historical_data/download/all_symbols/
     ?reportType=volume&month=<M>&year=<Y>&volumeType=sum&volumeAggType=daily
     &exchanges=CBOE&exchanges=BATS&exchanges=C2&exchanges=EDGX
   ```

   Its CSV is `Trade Date, Options Class, Underlying, Product Type, Exchange, Volume` — group by
   **(date, underlying)** and sum across classes and venues; the corporate-action-adjusted series
   live in the *Options Class* column (`2AAL`), not in the underlying name. Verified 2026-11-04:
   the merged monthly file reproduces the per-symbol endpoint **exactly** on base volume, 10-session
   average and ratio for 7/7 names checked.

   Two caveats on that number. It is **unfiltered** — every strike and every expiry, not the
   V/OI survivors — and it covers **only the four Cboe-operated venues**, whereas the chain spans
   every US venue. The *ratio* is internally consistent (4-venue vs 4-venue), but the absolute
   volumes are a different universe from the chain column beside them. It also **lags the live
   session by about a day**, so the own-history baseline is measured on the last session the
   service has published, one behind the contract screen — label that date on every row.

   Market-wide call/put volume and open interest for a past date come from Cboe's daily market
   statistics, `https://www.cboe.com/us/options/market_statistics/daily/?mkt=cone&dt=<DATE>`.
   The page is client-rendered, so read it with a headless browser; it yields the call/put
   volume and OI split per product class, and Cboe's own published put/call ratios.

   **When you rebuild a lost day, label it a RECONSTRUCTION in the title and lead section 0 with
   that fact**, state what the file cannot contain and why, and put the run's actual cause in
   the file. Do not present a reconstruction as if the original run had produced it, and do not
   publish a V/OI figure for a date where none can be computed. The reference reconstructions
   are `options-flow/2026-10-19.md` and `options-flow/2026-10-26.md`.
   *(Established 2026-11-03, rebuilding the two lost sessions.)*

9. **The economic read is premium dollars, not contract counts.** A contract count weights every
   contract equally, and on a busy session most of them are penny prints: on 2026-11-04, **57.1%** of
   the kept set's volume sat in contracts with `theo` < $0.05. That set's headline put/call was
   **0.74 (CALL)** while the same set weighted by `volume x theo` was **3.47 to puts**, and **82.3% of
   all premium changed hands in ITM contracts**. Publish **both** numbers: the contract-count ratio is
   the series' comparable figure, the premium-dollar ratio is the economically meaningful one. Never
   publish the contract-count tag alone on a day when the two disagree - that is how the 2026-11-02
   artifact shipped a tag that contradicted its own prose.
   *(Established 2026-11-04.)*

10. **IV is degenerate on a 0DTE row after the close.** A same-day option has essentially no time
    value left once the cash session ends, so Cboe's IV on those rows is an artifact of the closing
    print rather than a volatility estimate. Measured 2026-11-04: on the 12 economically real rows with
    DTE > 0 the Cboe-vs-Yahoo IV gap is a median **4.2 vol points** (max 8.9), but on same-day rows it
    reaches **206 vol points** (NVDA 210C: Cboe 243.6% vs Yahoo 37.5%, `theo` $0.0000, `delta` 0.0000,
    last trade $0.01 after a -99.3% session). Flag every 0DTE row's IV as not interpretable rather than
    quoting it bare, and quote Yahoo's IV where both exist and the contract still has time value.
    *(Established 2026-11-04.)*

11. **Yahoo's `impliedVolatility` is a decimal fraction too** (raw `0.2618` = 26.18%), and reading it
    as an already-scaled percentage is a **100× error**. Verified by inverting Black-Scholes against
    the contract's own mid-quote (r ≈ 3.85%, q = 0.5%, side-aware branch, no-arbitrage clamp): Yahoo × 100
    correlates **0.988** with the inverted vol, while the Cboe column correlates 0.072 on the same rows.
    *(Established 2026-11-04.)*

12. **Cboe's IV column is an artifact on 0DTE ETF contracts priced at a penny.** Measured 2026-11-04
    across 70 invertible kept rows: the median gap to the inverted vol is 0.8 vol points, but **15 rows
    diverge by more than 10 vol points and every one is a 0DTE IWM/GLD contract with a wide bid-ask**
    (worst: IWM 284C, Cboe 123.6% vs inverted 13.0%, on a $0.005 theoretical value). On liquid
    single-name rows Cboe is fine (AAPL 332.5C: 37.1% vs 36.8%). Quote the inverted vol on the 0DTE ETF
    rows. *(Established 2026-11-04.)*

13. **Yahoo's `chartPreviousClose` on a multi-day daily chart is the close before the RANGE, not
    yesterday's.** Using it to verify a "day move" gives a wrong number with no error. Take the last
    two daily bars from `timestamp`/`close` instead — then it matched Cboe's `prev_day_close` exactly on
    6/6 names. *(Established 2026-11-04.)*

14. **A name with no listed options series is not a source failure.** The Cboe chain CDN answers
    HTTP 403 with an XML `AccessDenied` body for symbols it does not cover (CHSN, CRIS, DKI, OMH on
    2026-11-04). Record it as `no listed options series`, keep it out of the error count, and say how
    many names were affected. Only a real failure (timeout, malformed body, 5xx) counts as an error.
    *(Established 2026-11-04.)*

## Method of record

### The relative screen (headline)

| Element | Rule |
|---|---|
| Chain source | Cboe delayed-quote option-chain CDN, one JSON per underlying (~1-3 MB each), fetched 8-way in parallel |
| Universe | TradingView america scanner, top 60 US names by cash volume (`type in (stock,dr)`, `exchange in_range [NASDAQ,NYSE,AMEX]`, `close > 1`) + the routine's 8 |
| Cash volume | TradingView scanner `volume` column (post-close this is the settled session volume) |
| Own-history baseline | Cboe historical options volume, `all_symbols` monthly files (previous + current month), baseline session = the last session the service has published |
| Window | 4 earliest **listed** expiries per name, keyed on the OCC symbol |
| Filters | volume ≥ 1,000, theo ≥ $0.05, V/OI ≥ 1.0, DTE ≤ 60; **no absolute pre-cut** |
| Peer group | same underlier + expiry + side, strikes with volume ≥ 50; the group's median volume is published on every row |
| Composite | z(peer ratio) + z(expiry share) + z(opt % of cash vol) + z(V/OI) + 1.5 × z(own-history) |

### The series book (secondary, continuity)

Unchanged from the published series: the 8 Pass-B names, per-underlying **top-10 by volume**
(`min_volume=100`), 4 earliest listed expiries, V/OI ≥ 1.0, volume ≥ 200, DTE ≤ 60; ranked by
V/OI, top 25 published, top 10 headlined; bias tag from the put/call volume ratio.

**Bias tag thresholds (fixed — re-derive from the 10-28/29/30 files, never from the previous
artifact).** Put/call volume ratio **< 0.85 -> CALL**, **> 1.20 -> PUT**, otherwise **MIXED**. The tag
names the side that *dominates* the ratio, so a low ratio is a CALL tag. The 2026-11-02 artifact
inverted both tags (0.84 tagged `PUT`, 2.69 tagged `CALL`), which contradicted its own prose and the
10-28/29/30 files; its numbers were fine, only the tag strings read reversed. State the thresholds
inside every artifact so the tag is auditable without the history.

**That inversion was CORRECTED ON DISK on 2026-11-06.** `options-flow/2026-11-02.md` now reads
`bias: CALL` (its ratio is 0.84) and its audit line reads `bias=CALL`; every number in the file is
unchanged, and the file carries a dated correction note. Do not "re-fix" it from a previous run's
artifact — and do not re-tag it back to PUT. **The self-check above exists so this class cannot
recur**: the tag is re-derived from the rows and the write is aborted on a contradiction, so a
future artifact cannot ship a tag that disagrees with its own ratio.

### The wide book (secondary, population-matched)

| Element | Rule |
|---|---|
| Method | the series book's legacy method, unchanged — per-underlying top-10 by volume, 4 earliest listed expiries, V/OI ≥ 1.0, volume ≥ 200, DTE ≤ 60 |
| Universe | every name in the relative screen's universe that has a chain (~60 names) |
| Purpose | a population-matched read: the series book says what the 8 mega-caps did, the wide book says what the market's most-traded names did, and only the population differs |
| Not | a replacement for the series book, which carries the published put/call series since 2026-10-16 |

### Pass A (secondary, the user's watchlist)

| Element | Rule |
|---|---|
| Source | the PUBLISHED watchlist, `refs/watchlist.yaml` in `karizaco/minimax-cloud-outputs`, fetched at run time (the local `research/watchlist.yaml` on the Mavis host is unreachable from the Cloud runtime) |
| Method | the legacy method, unchanged — the same method as the series book, so the three books differ only in population |
| Universe | the watchlist's tickers, named in the front matter and in the section |
| A name outside the relative universe | its chain is fetched separately; it does NOT join the relative screen (that screen's universe is fixed) |
| Absent file | Pass A is omitted and `## Source health` says so once — never an empty section, never an invented list |
| Until the user edits the file | the published watchlist holds the routine's own 8 names, so Pass A's book coincides with the series book — the section says so |


**Declare the method in every artifact.** Each file must state, in its header, the primary chain
source, the cross-check source, the pre-cut rule, the expiry-window rule, and a
methodology-change log naming anything that differs from the previous run. A reader must be able
to tell a genuine change in flow from a change in method, and the two are easy to confuse: the
2026-11-29 → 2026-11-30 tag change (CALL 0.75 → MIXED 1.05) came alongside a source change.

**A reconstruction is not a run.** A rebuilt day carries the aggregate volume layer and the
market-wide call/put picture, and it says plainly that it is a reconstruction. It must never
carry a V/OI figure, and it must never be counted as an original run when comparing series. The
two reference cases are `options-flow/2026-10-19.md` (run failed at the platform level) and
`options-flow/2026-10-26.md` (ran and self-skipped outside its own market-hours gate).

## Out of scope
- Backtesting options strategies.
- Greeks (delta/gamma) — not exposed by the TradingView-advanced MCP today.
- Earnings-specific plays — that's `earnings-reaction-scanner`.
- Any trade, direction or sizing suggestion.
