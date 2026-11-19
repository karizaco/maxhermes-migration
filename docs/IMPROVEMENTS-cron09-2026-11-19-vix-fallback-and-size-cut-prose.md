# IMPROVEMENTS-cron09-2026-11-19 — the volatility pair had no fallback, and the size-cut cell contradicted its own flag

**Date:** 2026-11-19
**Routine:** cron #09 `stock-screener-daily-sweep-18:30` (the end-of-day sweep)
**Fire:** 2026-11-19 18:30 ET (dispatched 18:30:44 ET, `stall_min: 1` — not stalled)
**Artifact:** `daily-screens/2026-11-19/daily-sweep.md` + `breadth.md` in `karizaco/minimax-cloud-outputs@main`
**Found by:** the 2026-11-19 fire itself — the run died at the breadth stage and the fix had to land before the next fire.

---

## Finding 1 — the Cboe volatility CDN is blocked from the Cloud egress, and the pipeline had no fallback

**Evidence.** `cdn.cboe.com/api/global/delayed_quotes/quotes/_VIX.json` answers **HTTP 403** with a
Cloudflare "Attention Required" interstitial from this egress. It is not a transient error and not
User-Agent dependent — the same 403 came back for a browser-like UA, for a bare UA, and from both
`curl` and `urllib`:

```
403
<!DOCTYPE html>
<!--[if lt IE 7]> <html class="no-js ie6 oldie" lang="en-US"> <html>
<title>Attention Required! | Cloudflare</title>
```

`fetch_vix_pair()` had no `try/except` around the Cboe pull, so the exception propagated out of
`collect_breadth()` and **killed the pipeline**. The first 2026-11-19 attempt had already spent the
fresh book, the eight branches, the CANSLIM half, the enrichment pass and the overlay — and it
published **nothing**:

```
Traceback (most recent call last):
  ...
  File "tools/sweep_pipeline.py", line 2051, in cmd_run
    breadth = collect_breadth(bridge, t1_date, workers)
  ...
urllib.error.HTTPError: HTTP Error 403: Forbidden
```

**Why this is worse than a missing number.** The volatility pair is not decoration: the regime's
`uncertainty` flag is `(vix / vix3m) > 1.0`, and `breadth.md` publishes one pair everywhere. A run
that cannot read it has no regime read, so it either publishes an artifact with a regime section
hollowed out (unacceptable) or publishes nothing (what actually happened).

**The fix.** `fetch_vix_pair()` now falls back to Yahoo's chart API (`^VIX`, `^VIX3M`):

* **ONE source for BOTH symbols**, and both must resolve to the **same session bar**, pinned to the
  cron day — `session_date` is threaded from `cmd_run` through `collect_breadth` into the fetch.
  A replay on a later day is **refused**, not faked with a stale bar.
* The published `source` string names **the source that actually served the numbers**, and both
  hardcoded "Cboe delayed-quote CDN" strings in the renderer were replaced with `vix['source']` —
  so the artifact cannot claim a source it did not use.
* `cboe_fallback_reason` is carried in the payload for the source-health line.

**Cross-check.** The fallback's reading for 2026-11-19 was **VIX 28.44 / VIX3M 27.03**, which matches
the published session close for that day exactly (CNBC's live quote: "28.44 +3.88 (+15.80%), Last
4:15 PM EST"). The fallback is therefore the settled close, not an intraday or stale print.

**A second trap on the fallback — the UA carries the fleet's aggregate rate limit.** Yahoo answers
**HTTP 429** for the Chrome-like User-Agent that every fleet routine shares (the rate limit rides on
that string), while a plain `"Mozilla/5.0"` answers. The fallback therefore sends its own UA and
retries with backoff (4 attempts, 2/4/6 s). Measured: 6/6 sequential requests succeeded with the
plain UA; the shared UA failed on every attempt.

## Finding 2 — the size-cut cell contradicted the flag it was printed next to

`render_daily_sweep()` printed the size-cut explanation as a **literal**:

```python
f"| `size_cut_pct` | **{regime['size_cut_pct']}** (breadth {b['breadth_pct_20dma']:.2f}% is far above the 40% trigger) |",
```

The rule in `screen.py::compute_regime()` is `size_cut = 50` when **the index is below its 20-DMA
AND breadth < 40**. On 2026-11-19 the flag was **50** (index below its 20-DMA, breadth **21.20%** —
BELOW the trigger) and the literal said the breadth was "far above" it. The cell that is supposed to
explain the flag said the opposite of the flag, in the same cell, on the same line.

The mirror defect sat next to it: the `uncertainty` rule cell printed the ratio with a hardcoded
"≤ 1" while the flag fires **above** 1.0 (the ratio was 1.0522 and the flag was `true`).

**The fix.** `_size_cut_note(regime, breadth_pct)` derives the sentence from the flag, and the
`uncertainty` cell states the direction it actually tests. Both renderers (`daily-sweep.md` and
`breadth.md`) now agree with `_regime.json`.

## What landed

| File | Change |
|---|---|
| `tools/sweep_pipeline.py` | Yahoo fallback for the volatility pair (session-pinned, both symbols, one source, own UA + backoff); `_size_cut_note()`; computed `uncertainty` rule cell; `FETCH_MARKER` bumped **V2 → V3** |
| `cloud-prompts/skills/stock-screener-suite/SKILL.md` | fetch ladder now demands `SWEEP_PIPELINE_V3`; new §4.5.6 documents the fallback, the UA trap and the computed regime cells |
| `tools/test_sweep_pipeline_vix.py` | **new** — 17 offline checks (the fallback path, the Cboe path, the session refusal, and the size-cut truth table) |

**Why the marker was bumped.** The fetch ladder's marker is what stops a CDN-cached OLD copy from
winning the race. The V2 copy has no fallback, so if it won, every fire would die at the breadth
stage. V3 is the marker the old copy lacks.

## What the run published

The 2026-11-19 artifact was produced with the fixed pipeline and pushed to
`daily-screens/2026-11-19/` (24 files). It carries **one** volatility pair (VIX 28.44 / VIX3M 27.03),
`size_cut_pct: 50` with a sentence that agrees with it, and **1 degraded source** (the Cboe CDN)
disclosed in the source-health table.
