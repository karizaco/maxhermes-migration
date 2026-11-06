# IMPROVEMENTS — 2026-11-06: a macro print has a primary source, and a screen gap can be a corporate action

**Date:** 2026-11-06
**Scope:** the data path of cron #26 `agentic-pre-market-brief` (the 08:30 ET fire), written up because four of the five findings below apply to every routine in the fleet that publishes a macro print, an overnight block, or a market-wide screen.

**Evidence base:** the 2026-11-06 08:30 ET fire of cron #26, in the Cloud runtime. Everything below was measured on that run; the commands are reproducible.

---

## 1. A macro print has a primary source that does not depend on the news index

**The problem.** The October Employment Situation was released at 08:30 ET on 2026-11-06 — the exact minute cron #26 fires. Two web searches run at 08:33 and 08:36 ET returned **only pre-release previews**: consensus `+65K`, unemployment `4.2%`, and no actual, from six different outlets. The actual print was not in the search index for at least fifteen minutes after release. A brief that reaches for `web_search` at that moment gets the *forecast*, and publishing a forecast as the actual is the worst possible failure mode for a macro number.

**The fix — the BLS public API v2, one call, no key:**

```bash
curl -sL --max-time 30 -H "Content-Type: application/json" -X POST \
  -d '{"seriesid":["CES0000000001","LNS14000000"],"startyear":"2026","endyear":"2026"}' \
  "https://api.bls.gov/publicAPI/v2/timeseries/data/"
```

**Read it like this, not like a table of values:**

| What | Series | Why |
|---|---|---|
| total nonfarm payrolls, thousands | `CES0000000001` | the headline |
| unemployment rate | `LNS14000000` | the second headline |
| private payrolls | `CES0500000003` | the breakdown |
| average hourly earnings, private | `CES0500000008` | the wages line |
| participation rate | `LNS11300000` | the labour-supply line |

- **The headline is the DIFFERENCE between the two newest levels, never the level.** On 2026-11-06: `M10 = 159293`, `M09 = 159128` ⇒ **+165K**. Quoting `159293` as "payrolls" would be wrong by two orders of magnitude.
- **`latest: true` plus a footnote code `P` (preliminary) marks the fresh release.** The months before it carry the **revisions** — September was revised from +29K to +60K and August from +133K to +186K in the same release. The revisions are as much of the story as the headline.
- **Ask for every series you need in ONE call.** The keyless tier has a **daily threshold**: the third call on 2026-11-06 returned `REQUEST_NOT_PROCESSED ... the daily threshold for total number of requests allocated to the user ... has been reached`. A run that burns the allowance on a probe has no allowance left for the number it actually needed.
- **Cross-check against a second source** — `nowflation.com` publishes actual-vs-consensus and agreed exactly: `+165,000 vs +65,000`, unemployment `4.1% vs 4.2%`.
- **FRED is the WRONG source for the same-day print.** `fredgraph.csv?id=PAYEMS` served the pre-release vintage on 2026-11-06 (Aug `159015`, Sep `159044`) while BLS already had the revised `159068` / `159128` / `159293`. FRED is useful to *confirm the revisions*, not to read the new print.
- **`bls.gov/news.release/empsit.nr0.htm` failed to load** through `web_fetch` on this run ("file load failed"). The API needs no such luck.

## 2. The Yahoo keyless futures/rates feed carries a STALE `as_of` stamp

**The problem.** `market-recap get_quotes` returned `ES=F`, `NQ=F`, `YM=F`, `RTY=F` stamped `2026-11-06T13:27:40Z` (**08:27 ET**) when the call itself ran at 08:37 ET. A second call twenty seconds later returned **the same 13:27:40Z stamps and the same levels**. `^TNX` and `^VIX` were stamped 13:21–13:22Z. The payrolls release was at 08:30 ET.

So the brief's "overnight / futures" block was **largely pre-payroll**, while the equity pre-market screen it was placed next to was post-payroll. Two blocks in one section, two different moments, no warning.

**The fix:**

1. **Label every quote with its `as_of`** — the skill spec already requires this, and it is what makes the staleness visible.
2. **Compare the `as_of` with the release time before claiming a post-release level.** If the stamp precedes the release, the level cannot answer the question the reader has.
3. **Use the TradingView pre-market screen as the post-release read.** It is live and stamped at the pull; the Yahoo keyless feed is not.
4. Say it once, plainly. On 2026-11-06 the 10-year at 4.874% sat above both the prior close (4.839%) and the 4.82% Asia-morning level, which is *consistent with* a hawkish payroll reaction — but it is an inference from a stale-stamped feed, and the brief labelled it as one rather than as a settled post-print level.

## 3. A screen "gap" can be a corporate action, not a move

**The problem.** The single largest move on the 2026-11-06 screen was `SITC` at **-82.35%**. It is not a crash: SITE Centers declared a **$3.00 per share special cash distribution**, payable 2026-11-05, and it **went ex on 2026-11-06**. SITE is also voluntarily delisting from the NYSE before 2026-12-04 and moving to OTCID Basic.

The arithmetic: `3.57` close − `$3.00` distribution = **`0.57`** adjusted basis. The pre-market print was `0.63` — about **+10.5% on the adjusted basis**, not −82%.

**The fix.** Before publishing the biggest screen move as a story, check the company's corporate actions: an ex-date special distribution, a split, a reverse split, a delisting. A special distribution going ex is the single most common cause of a −70% to −90% screen gap in a $100M–$500M-cap name, and it is mechanically invisible in the `premarket_change` column.

**Where it lands in the contract.** §C2's key-level ladder says "a level published by the sourced catalyst" wins over the prior close. For SITC the published level is the **$3.00 distribution**, so the key level became the adjusted basis `0.57 (ex-$3.00 special distribution, 2026-11-06)` — not the unadjusted `3.57` prior close, which is a level that no longer exists. The name still appears in the losers table with its levels, because hiding it would be worse than explaining it.

## 4. A fire scheduled at the minute of a release needs its pull timed, not just taken

**The problem.** Cron #26 fires at 08:30 ET, the exact time of the Employment Situation. The run's first screen pull landed at **08:32 ET** — two minutes after the release — on a tape that had not digested it. The brief was rebuilt from a single pull at **08:36 ET**.

**The fix.** The "one pull per brief" rule was kept by **discarding the earlier pull entirely**, not by merging two of them — merging is how a single ticker ends up with two different percentages in one artifact. When the routine's fire time coincides with a scheduled release, pull once, record the offset against the release time, and say so in Source health rather than implying the tape reflects the release.

## 5. The bulk screen and the per-ticker pull disagree by cents — one source per field

**The problem.** Within one run, `HIMS` read **+8.73%** on the per-ticker pull and **+8.39%** on the bulk gainers screen; `NVDA` read **189.47** and **189.55**. Both pulls were minutes apart and both are "the screen".

**The fix.** The **bulk screen is the pull of record**. The per-ticker re-read exists to fetch names the bulk screen does not carry (the watchlist and the StockTwits list), and it must not leak into published numbers for names the bulk screen already has. The brief published the bulk values in the tables, the prose and the CSV alike, and `check_brief_consistency.py` confirmed the artifact cannot contradict itself.

---

## Also observed

- **`daily-briefs/2026-11-06-pre-market-refresh.md` (cron #26b) returned 404.** This brief's screen is its own pull, so nothing was lost, but the two artifacts are not comparable and cron #90's roster check should see it.
- **No halted names** anywhere in the 2026-11-06 pre-market screen (checked across all three screens plus the watchlist and trending pulls, 696 names).
- The **gainer screen hit the scanner's 400-row range limit**, so any "number of names up 3%" derived from it is a floor, not a market total. The loser screen returned 263 rows, all of which still qualified. The brief said so instead of publishing 403 as a count of the market.

## What was NOT changed

The skill spec was not edited and no `cron_update` was issued. Nothing here changes how cron #26 behaves on its next fire; these are data-path facts that the run had to discover for itself, and the spec should carry them only if the team decides they are worth pinning.
