# IMPROVEMENTS — 2026-11-24 — cron #08: the setup verdict mislabels a name that DID move

- **Date:** 2026-11-24 (Tuesday)
- **Routine:** cron #08 `#08-pre-market-gapper` (`stock-screener-pre-market-gapper`)
- **Fire:** 2026-11-24 08:34 ET · session `2026-11-24` · universe session `2026-11-23`
- **Artifact:** `daily-screens/2026-11-24/pre-market-gapper.md` (+ `.csv`)
- **Found by:** the 2026-11-24 08:34 ET fire, while reading back the artifact it had just rendered

## The defect

`cloud-prompts/skills/stock-screener-suite/scripts/render_premarket_artifact.py` writes the
`## Focus names that did not qualify` setup verdict from the **stylist count alone**, never
from the name's move:

```python
setup=("good setup that went nowhere" if len(r["_stylists"]) >= 3
       else "decent setup that went nowhere")
```

So the phrase is chosen for every name in that section, including a name whose published gap
is large. On this fire the section's **first** line read:

```
- **NVDA** — -5.35% · 21,596,737 shares · $165.05–$141.59 · 4 stylists, 7 origins
  (…) · setup: good setup that went nowhere.
```

NVDA **fell 5.35%**. It did not go nowhere — it fell more than the 4% bar the screen cares
about, and it is listed in the artifact's own gap ladder under `4–8%` ("at the bar") in the
same file. The artifact therefore contradicts itself: the ladder says NVDA is at the bar,
the setup line says the name went nowhere.

The other eight names in that section were under 2% and the phrase was harmless. **NVDA is
the only name on the list with four stylists**, so it is the one that trips the `>= 3`
branch — and "four stylists, seven origins" is exactly the profile §6.8 is built to
surface. The defect therefore fires on the best setup in the book, which is the name the
trader most wants to read about.

**Why it survived the checker.** `tools/check_premarket_artifact.py` asserts that every
non-qualifying name appears in the section **with its provenance and a setup verdict**, and
it reads the verdict as "the line contains a setup phrase". It never checks that the phrase
matches the name's own gap. The check passed on a line that misdescribed the move
(`CONTRACT OK — 33 checks passed` on this fire).

## Evidence

| item | value |
|---|---|
| published gap (NVDA, executed tape) | **-5.35%** vs the $165.05 2026-11-23 close |
| verdict | `BORDERLINE_THIN` (the print behind the gap was 2 shares) |
| driver | `SECTOR_BETA` — SMH -5.05% pre-market |
| setup quality | 4 stylists, 7 origins — the best on the book |
| rendered line | "setup: good setup that went nowhere" |
| artifact's own gap ladder | NVDA listed under `4–8%` — "at the bar" |
| checker | passed — it asserts the presence of a setup phrase, not its truth |

The same line is echoed in the **reply contract** (§6.10): the reply must name the top two
non-qualifying names, so the trader is pointed at NVDA first — and the setup verdict is the
one piece of prose attached to it.

## The fix (recommended — renderer-owned, marker bump required)

The verdict must be **derived from the name's own published gap**, not from the stylist
count. The renderer already computes `r["_gap"]` and `r["_sustained"]`; the setup phrase
should be a function of those, with the stylist count kept as a *quality* adjective rather
than the *whole* claim:

- `|gap| >= GAP_TRIGGER_PCT` → "**good setup that moved hard** — it cleared the bar and then some"
  (and name the direction, so a -5.35% is not read as a +5.35%)
- `0.5% <= |gap| < GAP_TRIGGER_PCT` → "good setup that went nowhere" / "decent setup that went nowhere"
- `|gap| < 0.5%` → "…that never moved"

Suggested shape, so the sentence keeps its current grammar:

```python
def setup_verdict(r):
    g = abs(r["_gap"]) if r["_gap"] is not None else 0.0
    quality = "good" if len(r["_stylists"]) >= 3 else "decent"
    if g >= GAP_TRIGGER_PCT:
        return "%s setup that moved hard — %s, at the bar" % (quality, pct(r["_gap"]))
    if g < 0.5:
        return "%s setup that never moved" % quality
    return "%s setup that went nowhere" % quality
```

**The marker must be bumped** — `premarket-render-v1` → `premarket-render-v2` — in the
renderer, in `cloud-prompts/skills/stock-screener-suite/SKILL.md` (§6.6 / §6.7) and in the
renderer's own acceptance. The skill's fetch ladder demands the marker, and a cached OLD
renderer must not be able to write the OLD sentence into a future artifact. The same
discipline as the 2026-11-13 v4→v6 contract change.

## The checker should also learn the lesson

`tools/check_premarket_artifact.py` asserts that a setup verdict is present. It should
additionally assert that a line whose published gap is at or beyond the 4% bar does **not**
carry a "went nowhere" / "never moved" verdict — the same "a published label must be derived
from the rows it describes" rule the fleet already applies to cron #07's front matter
(`PROMPT-BLOCKS.md` §Rules 9). A checker that cannot see the contradiction it has no clause
for will keep passing this artifact.

**Until the renderer is fixed**, the 2026-11-24 artifact carries a note in
`## Method, source health & caveats` stating that the setup verdict is mechanical and that
NVDA's "went nowhere" is wrong — the artifact's Method section is the sanctioned place for
a caveat about the run, and the flag decision itself is unaffected.

## Not a defect (checked and cleared on this fire)

- **The `screen_close_resolved` rejection** — the manifest flags it, the CSV's
  `ref_close_date` is the denominator session on every row, and the checker asserts both.
- **ANT at `BORDERLINE_THIN`** — the re-pull wave moved ANT from `FLAGGED` (100 shares) to
  `BORDERLINE_THIN` (11 shares) on a newer print. That is the `MIN_EXECUTED_SHARES` gate
  working as designed, not a defect.
- **The `Margin against the trigger` line reading "0.64x"** — cosmetic: the renderer prints
  `trigger / widest_gap`, so a margin above the bar reads as a fraction below 1. It is
  confusing but carries no wrong number; the widest gap and the trigger are both published.
