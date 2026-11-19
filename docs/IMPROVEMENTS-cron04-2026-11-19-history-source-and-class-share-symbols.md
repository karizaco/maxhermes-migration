# IMPROVEMENTS-cron04-2026-11-19 — the source-health line that lied, and the class-share symbols

**Routine:** cron #04, Bonde reversal-bullish, 15:55 ET.
**Date:** 2026-11-19 (the 16:31 ET settled re-read of the same session).
**Where the fix lives:** `tools/reversal_bullish.py` (the run-time-fetched screen) and
`tools/test_bonde_history_source.py` (the fault-injection test that pins it).

---

## 1. What the artifact said, and why it was wrong

The 2026-11-19 screen published five mechanical passers (LW, MOS, JBS, WCN, TMUS) and closed
with this source-health table:

```
| shibui-finance (bridge) | settled history, latest close | **degraded** — the bridge
  call failed on this run, so settled history came from the documented **nasdaq** fallback;
  the day-alignment check still resolved against those closes |

degraded_sources: 1 (shibui-finance settled history — the documented nasdaq fallback was used)
```

**The bridge did not fail.** It answered every call. The measured facts:

| Fact | Evidence |
|---|---|
| shibui returned history for **31 of 32** history-gate survivors | the run's own stderr: `note: shibui returned no history for 1 ticker(s); falling back to Nasdaq for those` |
| the ONE ticker it could not serve was **BRK.B** | `shibui_history(['BRK.B','BF.B','AAPL'])` → `BRK.B: 0 bars`, `AAPL: 30 bars` |
| **all five PUBLISHED candidates** got their settled history from shibui | every one of LW / MOS / JBS / WCN / TMUS reconciles row-for-row with shibui's own bars (e.g. LW's prior close 52.25, 3-session drop, 30-session mean volume 2,099,306 and ADR 3.19% are shibui's numbers, not Nasdaq's) |
| BRK.B never reached the artifact | it failed gate 6 (ADR ≥ 3%): its ADR is **1.71%**, so it was excluded before publication |

So the artifact published a degraded-source line for a run with **no degraded source**, and —
because the shared reply format requires the reply's `errors:` count to equal the artifact's
`degraded_sources:` count — that false line would have forced a false error count onto the reply
as well.

## 2. The root cause: a class-share symbol-format mismatch

shibui and the TradingView scanner disagree on how to spell a US class share:

| Company | TradingView scanner (the universe's spelling) | shibui (the history's spelling) |
|---|---|---|
| Berkshire Hathaway class B | `BRK.B` (DOT) | `BRK-B` (HYPHEN) |
| Brown-Forman class B | `BF.B` (DOT) | `BF-B` (HYPHEN) |

shibui also carries `BRK-A`, `BRKC`, `BRKH`, `BRKR`, `BRKU` — every Berkshire line is hyphenated.
A dotted scanner symbol simply does not exist in shibui, so the lookup returned nothing and the
name was silently dropped onto the Nasdaq fallback.

**Both dotted names are in the universe.** The TV pull for 2026-11-19 returned exactly two dotted
tickers: `BF.B` and `BRK.B`. So this was not a rare edge — it is a standing condition that will
re-fire on every session where either class-share name survives the candle gates.

## 3. Why one fallback relabelled the whole run

`fetch_history` returned a single run-level string:

```python
src = "shibui" if (prefer_shibui and len(hist) == len(tickers) and not missing) else "nasdaq"
```

One missing ticker ⇒ `missing` non-empty ⇒ the label is `"nasdaq"` for the entire run, and
`write_md` rendered that as *"the bridge call failed on this run"*. The label described the
WEAKEST ticker, not the published set. Two independent things had to be true for the artifact to
lie, and both were structural:

1. the run-level label (fixed below), and
2. the wording, which asserted a bridge failure rather than a per-ticker fallback.

## 4. The fix (in the repo, so the next fire inherits it)

`tools/reversal_bullish.py`:

1. **`shibui_symbol()`** — maps the scanner's dotted class-share form to shibui's hyphenated
   form, and **only** the dotted form (a hyphenated symbol is left alone). The result is keyed
   back by the SCANNER's symbol, so no caller ever sees a renamed ticker.
2. **`fetch_history` now returns a per-ticker source map** (`{ticker: "shibui" | "nasdaq"}`)
   instead of one run-level string.
3. **The run's `history_source` is derived from the PUBLISHED candidates.** If every published
   name's history came from shibui, the run is `shibui`. A fallback that reached no published
   name is still **disclosed** (a `_history note:` line naming the tickers) but does not
   manufacture a degradation.
4. **`degraded_sources:` is published only when a PUBLISHED candidate used the fallback** —
   which is what the reply's `errors:` count is required to mirror.

`tools/test_bonde_history_source.py` (new, 19 checks) pins all of it, including the two
fault-injection cases: a fallback that reached no published name must NOT be reported as a
degraded source, and a published name on the fallback MUST be.

## 5. The measured result after the fix

Re-running the same session with the fixed screen:

```
"history_source": "shibui",
"history_fallback_tickers": [],
"published_from_fallback": [],
"passing": 5
```

The candidate set is **unchanged** (LW, MOS, JBS, WCN, TMUS) — the fix changes the honesty of the
source-health line, not the screen. The artifact now says `ok` for shibui, and publishes **no**
`degraded_sources:` line, so the reply's `errors:` count is **0**.

## 6. Why this belongs in the repo and not in agent memory

Per `AGENTS.md` §1: a defect in a shared script goes in **the script**, plus a line in the
matching doc. `tools/reversal_bullish.py` is fetched at RUN time, so this fix changes the next
fire of cron #04 with no `cron_update` and no prompt drift. The prompt was not touched.

## 7. The transferable lesson

**A source-health line must describe the DATA THAT WAS PUBLISHED, not the weakest input in the
run.** The run-level label was a summary of the worst case; the artifact is about the published
set. Whenever a report's source-health line drives an `errors:` count that the reply must
mirror, the line must be computed from the same subset the report publishes — otherwise a single
unrelated fallback becomes a fleet-visible error on a clean run.
