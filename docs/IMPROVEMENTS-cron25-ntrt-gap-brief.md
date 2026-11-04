# Improvements — cron #25 ntrt-gap-brief-daily

Reviewed 2026-11-03, after the routine's own 09:00 ET fire on 2026-11-03 (deployed cron task
`457578106761360`, run `459413987131500`, session `459413685592170`). Evidence base: the four
most recent briefs on the outputs repo (`ntrt/2026-10-29.md`, `ntrt/2026-10-30.md`,
`ntrt/2026-11-02.md`, `ntrt/2026-11-03.md`), the deployed prompt (byte-identical to
`cloud-prompts/cron-prompts/25-ntrt-gap-brief-daily.md`), the skill spec
`cloud-prompts/skills/ntrt-gap-brief/SKILL.md`, and the shared `## DELIVERY` block in
`cloud-prompts/_shared/PROMPT-BLOCKS.md`.

Base for every revert: commit `d2562b1d64cf1ae0742fabf8a1807f3dafa6e76a`, tag
`pre-ntrt-format-v2-2026-11-04`.

**What changed:** `cloud-prompts/skills/ntrt-gap-brief/SKILL.md` only. The deployed cron prompt
is **not** touched — it already points at the skill spec URL and re-fetches it at run time, so the
new layout takes effect on the next fire with no prompt deployment and no drift risk. The
outputs repo is not touched either; `ntrt/2026-11-03.md` and `ntrt/2026-11-03.csv` remain as
delivered.

---

## 1. The artifact layout was never specified, so it drifted every run — HIGH

`SKILL.md` said only:

> 6. Compose the brief:
>    - TL;DR (≤ 3 bullets)
>    - Top gappers table (ticker, gap%, importance/relative-vol, sector, one-line why)
>    - Catalysts
>    - Anything needing human eyes

Five bullets for a screen that routinely holds 260+ names. Everything else — section order,
table structure, where the catalyst went, whether there was a market backdrop at all — was
improvised per run. The result, from the four most recent briefs:

| Brief | Section skeleton |
|---|---|
| 2026-10-29 | TL;DR · Top gappers · Catalysts · **Themes** · Needs human eyes · Method · **Source health** |
| 2026-10-30 | identical to 10-29 |
| 2026-11-02 | TL;DR · **Catalysts** · **Pre-open tape** · **Wider screen** · **Market backdrop** · Needs human eyes · Source health · Method |
| 2026-11-03 | TL;DR · Top gappers · **Importance** · Catalysts · Needs human eyes · Method |

Three different skeletons in four briefs. A reader who learned Monday's layout had to re-learn
it Tuesday. Nothing was wrong with the content each run; the shape was simply never specified.

**Fix.** A new `## ARTIFACT FORMAT CONTRACT (v2 — load-bearing)` section in `SKILL.md` pins the
skeleton, the table rules, the numeric conventions, the CSV column contract, and the separation
of flags from caveats. It is marked load-bearing and the failure-modes table now carries
**"Layout drift — a run that invents its own structure is a failure, not a variation."**

The pinned skeleton:

```
# NTRT gap brief — <Weekday, DD Month YYYY>
<mode banner: 2 lines>
## TL;DR
## Market backdrop
## Worth your attention
## Wider screen
## Flags
## Method, source health & caveats
```

## 2. Every name was listed three or four times — HIGH

The 2026-11-03 brief put **SHOP in six sections and DT in five**. The cause: a "Top gappers"
table carrying a `Why` column, then an "Importance" table repeating the gap and %ADV for many of
the same names, then a "Catalysts" prose section re-stating the same facts again. The artifact
ran 193 lines, roughly 40% of it redundancy.

**Fix.** A hard one-table rule: **each name appears exactly once in the markdown, in exactly one
table.** The catalyst rides as the last column of that row, and there is no separate `## Catalysts`
section. The full screen moves to the CSV, where it belongs.

Rendered against the same 2026-11-03 data, the new layout shows 45 names with **zero** names
appearing in more than one table row, and the artifact drops from 193 lines to 110.

## 3. Gap % was published as if it were the ranking — HIGH

The screen's own advice — the same advice the 2026-11-02 brief gave ("Read the %ADV column, not
the gap") — was not written down anywhere, so the 2026-11-03 brief ranked a 261-name screen by
absolute gap and put a −16.3% move on **5,500 shares** in the top table and a −10.7% move on
**0.1% of ADV** in the "read this before acting" list.

**Fix.** An explicit actionable gate: a name reaches `## Worth your attention` when it has
`|gap| ≥ 3%` **AND** `% of 30d ADV ≥ 5`. The 5% ADV floor is stated as the market-vs-quote
line. The TL;DR is required to carry the %ADV reality check as one of its three bullets, so the
reader is told the shape of the screen before the tables.

## 4. No market backdrop section, and macro context demoted — MEDIUM

The 2026-11-03 brief had election day, futures and Friday's payrolls as **bullet 6 of "Needs
human eyes"**. Context that changes how every number in the brief should be read was filed
under caveats, where a reader triaging suspicious numbers would never look. The 2026-11-02 brief
had a proper `## Market backdrop` section; it was lost.

**Fix.** `## Market backdrop` is a required section in the pinned skeleton, positioned second.

## 5. "Needs human eyes" mixed four unrelated kinds of warning — MEDIUM

Six numbered items mixing: an unconfirmed catalyst (BRAI), thin-book prints (CWH, ACIC, DRUG),
an unexplained move (STVN), %ADV arithmetic artefacts (KMDA, MDGL), a data caveat (live tape),
and macro risk. Nothing distinguished "this number is suspect" from "this is about the data".

**Fix.** §5 splits them: `## Flags` is **per-name only** (unconfirmed catalyst, thin book, a move
that contradicts the fundamental, a name that left the screen, a distorted %ADV) and each flag
must name a ticker and the number that makes it suspect. Data caveats move to
`## Method, source health & caveats`.

## 6. Numeric conventions were undefined — MEDIUM

The same brief carried `9.8719`, `16.55`, `2.9794` (4-decimal prices), `18.9`, `18.913`, `4.975`
(mixed-precision percentages), and `$201B` next to `$4937503M`. Two runs were not comparable and
the markdown did not match the CSV's precision.

**Fix.** §3 pins price 2 dp, gap % 1 dp signed, %ADV 1 dp in markdown / 3 dp in CSV, volume as
an integer with thousands separators, market cap as `$M`/`$B`.

## 7. The CSV companion carried no catalyst and no noise flag — MEDIUM

`ntrt/2026-11-03.csv` was the **first** CSV in `ntrt/` (14 markdown files, 1 CSV). It had no
catalyst column and no flag, so a downstream consumer could not tell a real mover from a 350-share
print without re-deriving the threshold from scratch.

**Fix.** §4 pins the column contract:

```
ticker,premarket_change_pct,premarket_close,prev_close,premarket_volume,avg_volume_30d,pct_of_adv,mkt_cap_usd,sector,exchange,catalyst,noise
```

with `noise` = `true` when `pct_of_adv < 1`, and a `catalyst` column that is **empty when no
catalyst could be confirmed** — never a guess. The same section states that the CSV carries the
**full screen** and the markdown the actionable subset, and the two must never contradict.

## 8. The chat reply did not follow the fleet's own `## DELIVERY` block — MEDIUM

`PROMPT-BLOCKS.md` §DELIVERY mandates `### Signal` / `### Method & caveats` / `### Files` /
`### Push / errors`. The 2026-11-03 reply used prose and tables without those headings and
omitted `### Files` entirely, while the skill spec independently said "Return a short TL;DR + top
gappers table to chat" — a second, weaker, conflicting instruction.

**Fix.** `## Output` in the skill now points at the shared `## DELIVERY` block as the fleet
standard and explicitly forbids inventing a reply layout for this routine. The weaker sentence is
gone.

## 9. Source health was folded into Method and became optional — LOW

All three prior briefs have a `## Source health` section. The 2026-11-03 brief folded it into
Method and caveats. The fleet's shared blocks list source health as a standing rule.

**Fix.** §6 makes it mandatory: every source tried, with its status; a source that failed is
reported **with its status code**, never silently dropped and never called "unavailable" when it
returned an error nobody read.

## 10. Deep-dive cap could be misread as a cap on catalyst lookups — LOW

`SKILL.md` said "Hard cap deep dives at 5 per run" and separately "pull a one-line catalyst for
each top 5 by abs(premarket_gap)". The first is about dossier investigations; the second caps the
catalyst column at five names. Read together, they contradict the new format, which needs a
catalyst for **every** actionable name.

**Fix.** The hard-rules entry now defines a deep dive as a dossier / multi-source investigation
of one name, states explicitly that it is **not** the one-line catalyst lookup, and says not to
cap the catalyst column at 5.

## 11. A gap can cross the 3% filter band between pulls — NEW, from the 2026-11-03 run

**DOCN** was in the 09:05 bulk screen at **-3.11%** and was **absent** from the 09:07 screen; a
per-ticker re-check at 09:08 read **-2.54%**. It had faded out of the ≥3% band while still
trading 881,018 shares — the heaviest pre-market volume in the screen (34% of ADV). Two
consequences, both now written into the spec:

- Mode B notes that a name in one pull may be absent from the next, and that "the screen did not
  contain X" must never be said without a per-ticker `equal` re-check. If a notable name leaves
  the screen, that is a **Flag**, not a silence.
- §7 adds the one-pull rule: the **first pull wins** for the tables and the prose must match it.
  A brief that contradicts itself is worse than a brief with less in it.

---

## Verification performed

- Front matter parses; `name` and `description` keys preserved.
- No literal `|` inside a markdown table cell (the known cell-corruption trap).
- Code fences balanced (6 markers); the skeleton example's `##` headings are inside a fence, so
  they are a template rather than live headings.
- All pre-existing sections preserved: `## Steps`, `### Mode A`, `### Mode B`, `### Mode B2`,
  `### Always`, `## Failure modes`, `## Hard rules`, `## Out of scope`.
- Heading style matches the sibling skills: one top-level `#` per document.
- Trailing newline preserved (matches `origin/main` and two of three siblings).
- The new layout was rendered against the real 2026-11-03 dataset: 45 names, **zero** in more
  than one table row, 110 lines versus 193.

## Revert

```bash
git revert <commit-sha>                    # the SKILL.md change, as its own commit
# or, to restore the pre-change spec exactly:
git checkout pre-ntrt-format-v2-2026-11-04 -- cloud-prompts/skills/ntrt-gap-brief/SKILL.md
```

No cron redeployment is involved, so a revert takes effect on the next fire with no scheduler
change and no prompt drift to undo. The tag `pre-ntrt-format-v2-2026-11-04` points at the
pre-change commit `d2562b1d64cf1ae0742fabf8a1807f3dafa6e76a`.
