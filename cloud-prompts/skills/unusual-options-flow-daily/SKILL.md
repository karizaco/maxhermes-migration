---
name: Unusual options flow daily
description: >-
  Daily scan of unusual options activity on watchlist + mega-cap tickers using
  TradingView-advanced `stock_options_unusual_activity`. Surfaces strikes where
  today's volume exceeds open interest (V/OI > 1) — classic institutional
  positioning signal. Runs weekdays 16:35 ET, just after the close.
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

# Unusual options flow — daily

Lightweight daily scan: where is the smart money positioning today on options? Built on `mcp__tradingview-advanced__stock_options_unusual_activity`, no LLM cost.

## When
- Cron: `35 16 * * 1-5` America/New_York (weekdays, 16:35 ET — just after the cash close, so the day's volume is settled)
- Manual: user asks "any unusual options activity today?" or "show me NVDA options flow"

**Why post-close — do not "restore" the original hour.** The original local skill targeted
`55 9 * * 1-5` (09:55 ET, ~25 min after the open). The deployed time is 16:35 ET and that is
deliberate, not drift. V/OI divides *volume* by *open interest*: a 25-minute post-open volume
sample measured against a full prior-day open interest is mechanically depressed and unstable,
whereas after the close the day's volume is settled and the ratio is reproducible day to day.
A migration that trusts the original 09:55 hour would break the comparison with the published
series and re-introduce the pre-close instability. Keep 16:35 ET.

## Output
- `C:\Users\admin\.minimax\projects\coding-shared\research\options-flow\YYYY-MM-DD.md`
  _(In Cloud this path does not exist — it is the local Mavis host's location. In Cloud, write to the `## OUTPUT` path in the cron prompt.)_)
- Chat reply: in Cloud the format is the `## DELIVERY` block in the shared `PROMPT-BLOCKS.md`
  (prose opener → `### Signal` → `### Method & caveats` → `### Files` → `### Push / errors`).
  There is **no line cap**; long-form detail belongs in the artifact file. The
  "compact summary, top 5 only" rule is the local Mavis host's chat format, not Cloud's.

## Universe
Two passes:

**Pass A — Watchlist core**
Read the watchlist if it is present — see the Cloud adaptation note below for what to do when it is not. (top-level `tickers:` list). Call `stock_options_unusual_activity` per ticker (cap 30 — split if larger watchlist).

**Pass B — Mega-cap sweep (optional, weekdays only)**
IWM, GLD, TLT, plus the top 5 S&P 500 names by market cap (AAPL, MSFT, NVDA, GOOGL, AMZN as of 2026 — refresh quarterly). Capped at 12 total to stay inside minute budget.

**Exclusion list (do NOT scan — see Hard rules)**
- Broad-index mega-cap ETFs: SPY, QQQ (their chains are dominated by dealer-gamma and 0DTE market-maker hedging; V/OI gets inflated and the daily put/call bias tag becomes "PUT" on every red day for structural reasons, not positioning).
- Levered / thematic ETFs: SOXL, SOXS, SMH, TQQQ, SQQQ, UVXY, VXX. Same structural-noise problem, plus single-stock levered ETFs already violate the existing "no naked single-stock levered ETFs" rule.
- If a manual run wants to include any of these anyway, pass `--include-noisy-etfs` flag and tag every row `_source=noisy_etf_override` so the bias calculation can optionally exclude them after the fact.

## Call budget (soft targets)
- ≤ 42 underlying calls per run (30 watchlist + 12 mega-cap).
- Each call returns up to 10 strikes → ≤ 420 rows in raw output. Down-rank in `Steps 3`.
- If `tradingview-advanced` returns HTTP 429: log under Source health, skip the rest, write the partial file.

## Steps

1. **Read watchlist.** Parse `research/watchlist.yaml` → `tickers: [...]`. Cap at 30.

> **Cloud adaptation.** `research/watchlist.yaml` does **not** exist in the Cloud runtime — it
> lives only on the local Mavis host. If the file cannot be read, say so ONCE in the notes and
> **omit the watchlist section**; never ship an empty "Your watchlist" table. Substitute the
> routine's deployed universe (per its `## OUTPUT` path) and label it as the universe, not as
> the watchlist.
2. **Build mega-cap list.** Hardcoded 11 names (above). Pulled from `mcp__financekit__stock_quote` for mcap validation if available; otherwise trust the hardcode.
3. **Call per underlying.** `mcp__tradingview-advanced__stock_options_unusual_activity(symbol, top_n=10, min_volume=100, expiries=4)` for each. Concurrency: serial, ~3 calls/sec.
   > **Cloud adaptation.** That MCP tool does **not** exist in the Cloud runtime — see
   > `## MCP TOOLS AVAILABLE` in the shared `PROMPT-BLOCKS.md`. In Cloud, take the chain from the
   > sources named in `## Method of record` below and reproduce the same semantics locally:
   > `top_n=10` per underlying (ranked by **volume**), `min_volume=100`, 4 expiries per underlying.
4. **Aggregate per-ticker** into rows:
   - ticker, underlying_price, side (call|put), strike, expiry, volume, open_interest, v_oi_ratio, last_price, iv, in_the_money, moneyness_pct, expires_in_days
5. **Rank** by V/OI descending across all underlyings. Keep top 25.
6. **Filter:**
   - drop `v_oi_ratio < 1.0`
   - drop `volume < 200`
   - keep `expiries_within_days <= 60` (short-dated institutional bias)
7. **Bias call:** sum call_volume vs put_volume across the kept set. Compute put/call volume ratio. Tag overall bias.
8. **Write markdown** with sections:
   1. Top 10 strikes table (ticker, side, strike, expiry, vol, OI, V/OI, IV, moneyness)
   2. Per-ticker notable (top 2 per ticker)
   3. Bias summary (calls vs puts, put/call ratio, theme if obvious)
   4. Source health (call counts, 429s)
9. **Append audit line:** `unusual-options-flow target=options-flow:<date> underlyings=<n> strikes_kept=<n> bias=<call|put|mixed>`.

## Hard rules
- Read-only. Never suggest a trade or sizing.
- If watchlist.yaml is missing, fall back to Pass B only.
- Cap mega-cap list at 12 names to keep cron runtime < 90s.
- Never include naked single-stock levered ETFs (same as `us-stocks-in-play` exclusion).
- **Never include mega-cap index ETFs or high-volume levered ETFs in Pass B** (SPY, QQQ, SOXL, SOXS, SMH, TQQQ, SQQQ, UVXY, VXX). Their option chains are dominated by dealer-gamma and 0DTE market-maker hedging, which inflates V/OI ratios artificially and biases the daily put/call tag toward "PUT" on every red day for structural reasons. Surface single-name positioning instead. IWM/GLD/TLT are kept — their directional signal is more interpretable.
- V/OI > 1 is the headline metric; everything else is context.

## Cloud data conventions

These are the conventions the Cloud runtime actually needs. Each one was found by a run that
got it wrong first, so each carries the evidence that established it. **Follow them exactly** —
they are not style preferences, and several of them silently produce a plausible-looking wrong
answer if you ignore them.

1. **Take the expiry date from the OCC contract symbol, never from a timestamp.** Yahoo's
   `expirationDate` epoch is 00:00 **UTC** of the expiry day, so rendering it in US/Eastern
   returns the *previous* calendar day. The contract symbol encodes the date unambiguously
   (`AAPL261028C00345000` → expiry 2026-10-28). Key every expiry, DTE and cross-source join on
   the symbol. *(Established 2026-10-27: a first pass rendered the epoch in ET and shifted every
   expiry in the file back by one day.)*

2. **ITM/OTM is side-aware.** A call is ITM when `strike < spot`; a put is ITM when
   `strike > spot`. Labelling from the sign of `(strike − spot)` alone inverts **every** call row
   — a GOOGL 400 call with spot at 320.21 is 25% *out* of the money, not in. Validate against
   Yahoo's own `inTheMoney` field (1,037/1,037 rows agreed once the rule was side-aware).
   *(Established 2026-10-27: the earlier files in this series had the labels inverted on all
   579 call rows. Their volume, V/OI and bias figures were unaffected.)*

3. **Yahoo drops the session-date 0DTE after the close.** Hours after the 16:00 ET close the
   just-expired session expiry is gone from Yahoo's `expirationDates`, yet those contracts traded
   heavily (IWM 0DTE alone was 778,086 contracts on 2026-10-27). Use Cboe to fill the session-date
   expiry, and reconstruct the expiry window as the **4 earliest expiries** across
   {Yahoo's list} ∪ {the session date}. *(Established 2026-10-27; re-verified 2026-10-28, where
   Yahoo happened to keep it for 6 of 8 underlyings while MSFT and GOOGL genuinely had no
   session-date expiry on either tape.)*

4. **Cboe's `iv` is a decimal fraction, not a percentage.** `iv: 0.3` means 30%, not 0.3%.
   Read literally, the IV column is out by 100×. Confirm the unit by inverting Black-Scholes
   against the contract's mid-quote before trusting the column. *(Established 2026-10-29.)*

5. **Cboe reports open interest of exactly zero on some contracts**, because they are series
   opened during the current session. V/OI is then *undefined*, not huge — a zero denominator
   puts those rows at the top of a naive ranking with no meaning attached. Report them as `n/a`
   and exclude them from the V/OI ranking. *(Established 2026-10-30: three contracts traded 84,629
   contracts against OI 0.)*

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

   The **aggregate** layer *can* be recovered, and it is exact. Cboe's historical options-data
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
   `User-Agent`, or the request is refused. The `all_symbols` variant of the same endpoint
   (`.../download/all_symbols/?reportType=volume&month=<M>&year=<Y>&volumeType=sum&volumeAggType=daily&exchanges=...`)
   returns every underlying for a month at once and is the faster way to confirm a total.

   Two caveats on that number. It is **unfiltered** — every strike and every expiry, not the
   V/OI survivors — and it covers **only the four Cboe-operated venues**, whereas this series
   reads Yahoo's chain, which spans every US venue. The ratio between the archival total and
   the published artifacts' kept-contract count therefore mixes a venue scope with a filter and
   ranges 0.38–1.50 across the dates where both exist. It is a sanity range, not a conversion
   factor. The total also includes corporate-action-adjusted series (Cboe class names prefixed
   with a digit, e.g. `2IWM`); disclose the adjusted share rather than silently folding it in.

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

## Method of record

The headline metric is a put/call volume ratio. That number is only comparable across days if
the method is identical, and three things changed underneath this series between 2026-10-16 and
2026-10-30 — the chain source, the pre-cut rule and the expiry window. Each is now fixed.

**Chain source — Cboe primary, Nasdaq cross-check.** Use the Cboe delayed-quote CDN chain as the
primary tape and Nasdaq's public option-chain endpoint as the independent second tape. Yahoo's
JSON endpoints return HTTP 429 from this egress (measured 2026-10-28), which is why the
2026-10-29 and 2026-10-30 runs had to run on Cboe alone. Yahoo remains useful for underlying
prices and for the deep-ITM IV in convention 6. **If the primary source changes, that is a
methodology change and must be logged in the artifact** — a different tape carries a different
open-interest denominator, so the ratio is not comparable across it.

**Pre-cut rule — volume, not V/OI.** The skill calls each underlying with `top_n=10` but does not
state what the ten are ranked by, and the choice changes the answer: the V/OI cut is
self-referential (it keeps the rows with the smallest open interest, which is what inflates V/OI)
and it discards the largest lines — it dropped 62.5% of kept volume on 2026-10-30. **Rank the
per-underlying ten by volume**, and publish the V/OI-cut numbers alongside so the difference is
visible rather than buried. The 2026-10-16, 2026-10-20 and 2026-10-21 artifacts were built on
the V/OI cut and are therefore **not** comparable with the rest of the series; their tags are
provisional and cannot be recomputed, because raw chains are not retained between runs.

**Expiry window — 4 earliest expiries.** See convention 3. The window's calendar dates differ per
underlying and per run; reconstruct it from the contract symbols rather than from a listed date.

**A reconstruction is not a run.** A rebuilt day carries the aggregate volume layer and the
market-wide call/put picture, and it says plainly that it is a reconstruction. It must never
carry a V/OI figure, and it must never be counted as an original run when comparing series. The
two reference cases are `options-flow/2026-10-19.md` (run failed at the platform level) and
`options-flow/2026-10-26.md` (ran and self-skipped outside its own market-hours gate).

**Declare the method in every artifact.** Each file must state, in its header, the primary chain
source, the cross-check source, the pre-cut rule, the expiry-window rule, and a
methodology-change log naming anything that differs from the previous run. A reader must be able
to tell a genuine change in flow from a change in method, and the two are easy to confuse: the
2026-10-29 → 2026-10-30 tag change (CALL 0.75 → MIXED 1.05) came alongside a source change.

## Out of scope
- Backtesting options strategies.
- Greeks (delta/gamma) — not exposed by the TradingView-advanced MCP today.
- Earnings-specific plays — that's `earnings-reaction-scanner`.