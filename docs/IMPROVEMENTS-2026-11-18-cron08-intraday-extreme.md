# IMPROVEMENTS — cron #08 (pre-market gapper): the intraday-extreme flag line

**Date:** 2026-11-18 · **routine:** `#08-pre-market-gapper` · **fire:** 2026-11-18 08:34 ET
**Files changed:** `cloud-prompts/skills/stock-screener-suite/scripts/render_premarket_artifact.py`,
`cloud-prompts/skills/stock-screener-suite/scripts/premarket_pull.py`,
`cloud-prompts/skills/stock-screener-suite/SKILL.md`,
`tools/test_premarket_intraday_extreme.py` (new)

## What was wrong

The `BORDERLINE_INTRADAY` flag line published the **current pre-market range** as the
crossing fact:

```
- **MOH** — crossed the bar intraday and gave it back (pre-market high n/a / low n/a → -0.10% at the snapshot).
- **FENC** — crossed the bar intraday and gave it back (pre-market high +0.52% / low +0.52% → +0.52% at the snapshot).
```

Two defects in one line:

1. **It contradicted the verdict it was flagging.** A reader sees "crossed the bar intraday"
   next to a high of +0.52% — which does not cross a 4% bar. `pm_high_gap_pct` and
   `pm_low_gap_pct` are the CURRENT range; the extreme that crossed the bar is a different
   quantity.
2. **The extreme itself was published nowhere in the markdown.** It existed only as
   `max_tape_gap_pct` in the pull JSON — an **absolute** value, so even the CSV's
   `flag_reason` could not say which side the name crossed. MOH's overnight extreme was
   **−6.98%**, a DOWNWARD cross; the artifact could only say "reached 6.98%".

Measured on the 2026-11-18 fire: 4 of 12 Focus names carried the verdict
(FENC +6.55%, MOH −6.98%, ULCC +6.08%, URGN −6.26%), and 2 of the 4 were downward crosses
whose direction was lost.

## The fix

- `premarket_pull.py` now publishes `max_tape_gap_signed_pct` — the signed extreme of the
  tape's own print list, alongside the existing absolute `max_tape_gap_pct`.
- `render_premarket_artifact.py` publishes the **signed** extreme in the Flags line and in
  the CSV's `flag_reason`. The renderer's fallback chain is
  `max_tape_gap_signed_pct` → the tape's own `tape_print_gaps` → the old wording, so a pull
  JSON that predates the new field still renders correctly.

After the fix, the same four rows read:

```
- **MOH** — crossed the bar intraday and gave it back (the pre-market tape reached -6.98% → -0.10% at the snapshot).
- **FENC** — crossed the bar intraday and gave it back (the pre-market tape reached +6.55% → +0.52% at the snapshot).
```

## The gate

`tools/test_premarket_intraday_extreme.py` (marker `premarket-intraday-extreme-v1`)
renders FIXTURES and pins 5 checks: T1 the signed extreme is published, T2 the current range
is no longer quoted as the crossing fact, T3 the CSV `flag_reason` carries the same signed
extreme, T4 a pull JSON without the new field still renders it (the fallback), T5 a record
with neither falls back to the old wording instead of crashing.

**The test was observed FAILING against the old renderer** (4 of 5 checks fail) before it
was accepted — a gate that has never been seen failing is a claim.

## The other finding from this fire (NOT fixed here)

**The crypto proxy is fetched only when a Focus record is crypto**
(`premarket_pull.py`: `crypto = _fetch_crypto_proxy() if (set(CRYPTO_BASKET) & set(records))`).
The Focus book of a momentum screen rarely holds a crypto name, so on this fire the proxy
was never fetched and the crypto-linked names in the MARKET LADDER (BLSH, CORZ, WULF) were
published `IDIOSYNCRATIC` — not from a measured comparison but for want of a reading.

For the record, BTC was ~−1.3% overnight (Yahoo daily bars, 11/17 close 64,894 vs the live
11/18 bar 64,020), so those names were **not** trading as crypto beta and the published class
was materially right — but it was right by luck, not by measurement. **Suggested fix:** fetch
the crypto proxy whenever the ladder contains a crypto-basket name, not only when a Focus
record does.

Left in place deliberately: changing the proxy's fetch condition changes the published
`driver_class` of ladder rows, and that belongs in its own change with its own contract
review, not inside a live fire.
