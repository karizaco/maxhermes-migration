# IMPROVEMENTS — 2026-11-17: a market cap was inflated by the ADR basis, and a macro print had no primary source

- **Date:** 2026-11-17
- **Scope:** cron #26 `agentic-pre-market-brief` (the 08:30 ET fire) — the market-cap
  reconciliation in `cloud-prompts/_shared/brief26_pull.py` and the macro read in
  `cloud-prompts/skills/agentic-pre-market-brief/SKILL.md`. Both files are fetched at RUN
  time, so the next fire picks this up with **no `cron_update` and no prompt drift**.
- **Trigger:** the 2026-11-16 brief's own `## Source health` published **two degraded
  sources** — the market-cap source and the macro calendar — and the cap degradation was
  worse than the brief said.

---

## 1. The cap: "stockanalysis always wins" is not a tiebreak, it is an unverified multiplier

### 1.1 What the rule was

`_shared/brief26_pull.py` reconciled the market cap for every flagged name (109 of them on
2026-11-16) and ended with this:

```python
cands = [x for x in (sa.get(t), sc_sh, s_sh, n_sh) if x]
if sa.get(t):
    shares = sa[t]                      # <- wins unconditionally, no test
    r["cap_source"] = "stockanalysis_shares x close"
```

`sa` is stockanalysis.com's `id:"sharesout"` field. The skill's own words were "it is the
only uncorroborated tiebreak". Nothing checked it.

### 1.2 Why that is wrong

For an ADR, that field is sometimes the **ordinary** share count while the price it is
multiplied by is **per ADS**. The product is then inflated by the ADS ratio. The 2026-11-13
brief had already found this by hand (ADXN, from its SEC 20-F: 1 ADS = 120 ordinary shares)
and the helper was never fixed.

Measured on the 2026-11-16 pull (five of the 109 flagged names carried a count on the wrong
basis):

| Name | Old published cap | Correct cap | Inflation | Gate B (old → new) |
|---|---|---|---|---|
| BLRX | $3,407,270,347 | $7,139,394 | **477x** | pass → **fail** |
| RADX | $3,296,537,613 | $10,637,398 | **310x** | pass → **fail** |
| ADXN | $517,287,986 | $4,889,103 | **106x** | pass → **fail** |
| IMOS | $34,453,163,260 | $1,789,737,950 | **19x** | pass → pass |
| ZBAO | $7,209,074 | $1,863,393 | 3.9x | fail → fail |

**Three names passed the $100M quality gate on an inflated cap.** RADX was the near-miss
that proves the exposure was live rather than theoretical: a ~$10.6M company sitting in the
published CSV with a **$3.30bn** market cap, **0.5 percentage points** outside the top-10
losers table. One more tick and a $3.3bn "company" heads a headline table.

### 1.3 The trap in the obvious fix: "the site disagrees with itself" is NOT a discriminator

The first fix was to ask stockanalysis whether the share count it publishes is the count
behind the market cap it publishes — `sharesout × its own price` against its own
`marketcap`, both from the same page. It works mechanically (the page carries a quote blob
with the site's own price, and the `marketcap` hover value), and it is how the four names
were found.

**But it is wrong, and SKHY is why.** SK hynix's ADR ratio is unusual: **each ADS
represents one-tenth of one common share** (its own investor-relations pages), so its
ADS-equivalent count is legitimately **smaller** than the ordinary count every other vendor
carries:

| Source | SKHY count | Basis |
|---|---|---|
| stockanalysis `sharesout` | 722,000,000 | **ADS** (1 ADS = 1/10 common) |
| stockanalysis's own market cap ÷ its own price | 5.00bn | ordinary |
| TradingView `market_cap_basic` ÷ close | 5.00bn | ordinary |
| Nasdaq `/summary` ÷ previous close | 6.86bn | ordinary |
| shibui `valuation` ÷ close | 7.11bn | ordinary |
| SK hynix's own FY2025 weighted-average count | 6.90bn | ordinary |

So the site's count disagrees with its own market cap by 6.9x — and the site's count is the
**right** one. SK hynix's US listing is worth ~$88–95bn on 722M ADS × $122–132, and
$95.15bn is what the old rule published. The self-consistency test would have thrown it
away and published $904bn.

ADXN is the exact mirror image: the site's count is the ordinary one (106x the ADS-basis
counts) and the site's own market cap is on the ADS basis. Same signature, opposite
conclusion. **A test that cannot tell these two apart is not a fix.**

### 1.4 The rule that works — and why the asymmetry is principled

An ADS-equivalent count **can never exceed the ordinary count** (1 ADS = N ordinary, N ≥ 1).
So:

> **The site's count is rejected iff it is more than 2x the median of the ADS-basis implied
> counts (scanner / Nasdaq / shibui) AND it disagrees with EVERY one of them by more than
> 2x** — an uncorroborated outlier, and on the wrong side of them. Then the ADS-basis
> implied counts are published (their median; the mean of the two middle values when there
> are two), the name is flagged in `cap_meta["basis_mismatch"]`, and the reason goes into
> its `cap_source`.

Every clause is needed:

- **the direction** (too big, not too small) — SKHY's count is legitimately smaller and is
  kept;
- **"every one of them"** (uncorroborated) — WETO's count agrees with Nasdaq's implied
  count and is right, so it is kept even though it is 14x the median;
- **the site page could not be read** is **unavailable, not wrong** — it falls back to the
  median implied count and is NOT flagged as a mismatch ("we could not ask" is not "the
  source disagrees");
- **the median of an even-length list is the mean of the two middle values** — taking the
  upper one (what the code used to do) biases every two-source name towards the higher
  share count, hence the higher cap, hence an easier pass on the $100M gate.

**Net effect on the 2026-11-16 pull: 5 of the 109 flagged names change** (the table in
§1.2), and SKHY, SHFS and WETO are untouched.

### 1.5 What is in the code now

`cloud-prompts/_shared/brief26_pull.py` (marker bumped `brief26-pull-v1` → **`brief26-pull-v2`**,
and the skill's fetch block now DEMANDS that marker so a cached old copy cannot win):

- `stockanalysis_shares()` now returns the site's count **and its own market cap and price**,
  plus a `status` of `ok` / `mismatch` / `untestable`, and the site's own implied count.
- `reconcile_caps()` applies the rule above and records `cap_basis_mismatch` per row and
  `cap_meta["basis_mismatch"]` for the names whose cap was rebuilt.
- The skill publishes every name in `cap_meta["basis_mismatch"]` in `## Source health` — a
  silently rebuilt cap is a hidden edit to a gate input.

`tools/test_brief26_cap_basis.py` proves the guard bites: it drives the real
`reconcile_caps()` with the network stubbed, asserts the published cap in four shapes
(coherent site, basis mismatch, ADS-count-below (SKHY), corroborated-by-one-source (WETO),
unreadable site), and **mutates the guard** — removing the rejection test — to show the
same row comes back inflated at $517,287,986. 17 assertions, all green.

## 2. The macro print: a value with no date anchor is a value you cannot publish

### 2.1 What happened on 2026-11-16

The NY Empire State Manufacturing Index was released at **08:30 ET — the minute cron #26
fires**. At the 08:43 ET pull the calendar aggregators the skill used (tradingcharts /
sigmanomics / crtlab / tradingeconomics) carried the schedule, the consensus (17.6) and the
previous (25.5) but **no actual**, so the brief published none. The actual was **7.8** — a
~10-point miss that the tape was already trading.

The 2026-11-06 fire hit the same wall on the Employment Situation (two searches returned
only previews), and `docs/IMPROVEMENTS-2026-11-06-macro-print-source-and-mechanical-gaps.md`
already established the rule: **a macro print has a primary source that does not depend on
the news index**. The skill had never been updated to use it.

### 2.2 The part the aggregators cannot give you: a DATE

The NY Fed's own release page (`https://www.newyorkfed.org/survey/empire/empiresurvey_overview`
— note `/research/calendars/empire/...` 404s) carries the value **and** the "Latest Report"
link, whose path encodes the release month:

```
/medialibrary/media/survey/empire/empire2026/2026_11_empire-state-manufacturing-survey.pdf
```

→ `2026-11`. A bare value cannot be dated (the page shows the latest release and nothing
else), so the helper anchors every read to that month: if it is not the fire's month, the
status is `not_yet_posted` — a FACT about a named source, not "no source" and not a zero.

### 2.3 The code

`cloud-prompts/_shared/macro_actual.py` (new, marker `macro-actual-v1`):

- `--release empire` (default) reads the Empire State from the NY Fed: the release month
  from the PDF path, the headline index from the narrative, the new-orders and shipments
  sub-indices from the same page;
- `--release bls` reads the Employment Situation from the BLS public API v2 in ONE call
  (the keyless tier has a daily threshold, so it never probes), with the headline as the
  DIFFERENCE between the two newest levels;
- the statuses are `ok` / `not_yet_posted` / `unavailable`, and `unavailable` always carries
  the reason in `note`. It never returns a fabricated zero;
- FRED is not a source for a same-day print (it serves the previous vintage).

The skill's Step 8 now fetches the helper with the ladder, **fetches it LATE in the run**
(it is a different source from the tape, so a second fetch of it never creates a second
version of a tape number), and publishes what it returns. `tools/test_macro_actual.py`
proves it fails closed: a page with no date anchor publishes nothing, an unreadable headline
publishes nothing, and a mutation that synthesises the release month shows the assertions
bite. 15 assertions, all green.

## 3. What a reader should be able to see next time

- every name whose market cap was **rebuilt** rather than taken, by name, in `## Source health`;
- the macro print with its **release month**, its **source** and its **fetch clock**, or the
  statement that the source has not posted it yet.
