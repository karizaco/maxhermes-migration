# Improvements — cron #25 ntrt-gap-brief-daily

Reviewed 2026-11-03, after the routine's own 09:00 ET fire on 2026-11-03; section 13 added
2026-11-05, after the 05 Nov fire (session `460121796727067`). (deployed cron task
`457578106761360`, run `459413987131500`, session `459413685592170`). Evidence base: the four
most recent briefs on the outputs repo (`ntrt/2026-10-29.md`, `ntrt/2026-10-30.md`,
`ntrt/2026-11-02.md`, `ntrt/2026-11-03.md`), the deployed prompt (byte-identical to
`cloud-prompts/cron-prompts/25-ntrt-gap-brief-daily.md`), the skill spec
`cloud-prompts/skills/ntrt-gap-brief/SKILL.md`, and the shared `## DELIVERY` block in
`cloud-prompts/_shared/PROMPT-BLOCKS.md`.

Base for every revert: commit `d2562b1d64cf1ae0742fabf8a1807f3dafa6e76a`, tag
`pre-ntrt-format-v2-2026-11-04`.

**What changed in the v2/v3 work:** `cloud-prompts/skills/ntrt-gap-brief/SKILL.md` only. The
deployed cron prompt was **not** touched — it already points at the skill spec URL and re-fetches
it at run time, so the new layout takes effect on the next fire with no prompt deployment and no
drift risk. The outputs repo is not touched either; `ntrt/2026-11-03.md` and
`ntrt/2026-11-03.csv` remain as delivered.

**What changed in the v4 work (sections 15–19, 2026-11-06):** the skill spec again, **plus the
deployed cron prompt**, plus the checker and its test. This is the first change to #25 that
touches the prompt, because the push block and the screener request live there (§15, §18) and a
rule that lives only in a run-time-fetched spec is a rule the run can miss. The prompt is
re-deployed **byte-exactly** and verified by SHA-256 against the repo blob. The outputs repo is
not touched: no published brief is rewritten by this work.

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

## 12. Three defects the contract itself had, found by rendering it against real data — HIGH

The v2 contract was written from the four prior briefs and the 2026-11-03 artifact. Rendering it
against the **real 2026-11-03 dataset** and diffing the output against the screen found three
defects in the contract that reading alone would not have caught:

- **CSV prices carried 4 decimals while the markdown rounded to 2** (`9.8719` vs `9.87`) — the
  same number in two files, so a reader could not match a row across them by eye. Fixed: prices
  are 2 dp in **both** files; the CSV keeps 3 dp only on `pct_of_adv`, which is a computed ratio
  rather than a quoted price.
- **RZAI has no 30-day ADV history** — `average_volume_30d_calc` is null, so the ratio is
  unmeasurable. The contract now says the value is **empty, never 0** (an unmeasurable
  denominator is not a zero-volume name), and `noise` is `true` when `pct_of_adv` is empty **or**
  below 1, so a name with no ADV history cannot slip through as "real" on an empty value.
- **A mega-cap's cap read as `$4937.50B`** — unreadable, and a trillion-cap company is read in
  trillions. The convention now scales to its own unit: `$M` under $1B, `$B` under $1T, `$T`
  above (`$4.94T` for AAPL), trailing zeros stripped.

This is the argument for rendering a contract against real data before shipping it: all three
are invisible on a page of prose and obvious the moment 261 rows run through it.

## 13. The screener's `close` column is the LIVE price, not the prior close — HIGH

Found on the 2026-11-05 fire (09:00 ET, session `460121796727067`). The v2 contract asks the CSV
to carry `prev_close`, and the screener request asks for a `close` column — but nothing said the
two are different things, and they are:

| name | screener `close` | prior regular close (independent quote source) |
|---|---|---|
| SPY | 754.64 | **766.81** (04 Nov) |
| QQQ | 667.905 | **691.95** (04 Nov) |
| APP | 271.75 | **271.75** (04 Nov close, matched by price after the move) |

Once the regular session is open, TradingView's `close` column carries the **live intraday
price**. A run that pulls the screen after the open and publishes `close` as `prev_close`
therefore publishes a wrong prior close for every name — a gap that is silently wrong by
exactly the day's move, i.e. it would have printed MNTN's "prior close" as today's intraday
level and made a −50.8% gap read as a fraction of a percent.

**Fix (in `SKILL.md` only — the deployed prompt is untouched).**

- The column table now has a `close` row that says, in one line, that it is NOT the prior close,
  with the SPY/QQQ numbers as the evidence.
- The §4 `prev_close` entry now says **derive it, never take it from `close`**, and gives the
  derivation: `premarket_close / (1 + premarket_change / 100)`.

**Verification.** The derivation was checked against an independent quote source on three names
and matched **exactly**: SPY 766.81, QQQ 691.95, APP 271.75. The 2026-11-05 artifact
(`ntrt/2026-11-05.md` and `ntrt/2026-11-05.csv`) publishes the derived prior close, and its
`## Method, source health & caveats` section states the rule and the check.

**Why this one matters more than its size.** The other eleven findings changed how a brief is
*laid out*. This one changes a *number*. A wrong `prev_close` does not look wrong: it is a
plausible price with two decimals in the right column, and the gap percentage in the next
column would still look right because `premarket_change` is computed by TradingView against the
true prior close. The artifact would have been internally consistent and wrong.

**Secondary finding — the pre-market tape and the live session must not be mixed.** The same run
published the pre-open screen at 10:12 ET, 72 minutes after the open, and the regular session
was already moving (QQQ −4.1%). The contract's one-pull rule (§7) covers two pulls of the
same screen; it did not cover "publish a pre-open screen while the regular session runs". The
2026-11-05 artifact handles it by labelling the mode banner with the snapshot time and by
flagging in `## Flags` that the gaps are pre-open prints and that several have been retraced in
the live session. The spec now carries the same instruction in the Mode B column block.

---

## 14. The v2 contract was prose, and the brief never published its asymmetry — HIGH (2026-11-06)

The v2 contract fixed the layout in prose. Prose is exactly what the 2026-11-04 work showed to be
insufficient: rendering v2 against the real 261-row dataset caught three defects that *reading*
the prose did not (CSV prices at 4 dp against markdown 2 dp, `RZAI`'s null ADV published as a
number, `$4937.50B` instead of `$4.94T`) — and the verification was **manual**. A rule nobody
executes is a rule that decays.

Two changes close the gap. Neither touches the section skeleton, the actionable gate, the
one-table rule or the CSV column contract.

### 14a. The contract is now a gate: `tools/check_ntrt_artifact.py`

Fourteen named checks, each exiting 1 with a specific failure:

```
SECTIONS · SECTION_EMPTY · NO_CATALYSTS · ONE_NAME_ONCE · MD_CSV_AGREE · CSV_CONTRACT ·
PCT_ADV_EMPTY · MKTCAP_FORMAT · NOISE_FLAG · TLDR_BULLETS · TLDR_ADV_CHECK · GATE ·
FOURCELL · FOURCELL_EX
```

The skill fetches the checker at RUN time (§9) and runs it **before the push**; the exit code is
the gate. The reply publishes `contract: 14/14` so a reader can see the artifact was **verified**
rather than assumed. The fetch demands the capability marker `NTRT_CONTRACT_CHECK_V1`, because an
older copy of the script is still published on the mirrors and checks fewer rules — a stale file
must not be able to win the ladder and report a clean artifact it never checked.

`tools/test_ntrt_contract.py` proves the checker bites: a synthetic conforming artifact must
pass, and **each of the fourteen checks has a fixture that fails it**. A mutation that changes
nothing is itself reported as a failure, so a no-op mutation cannot silently "pass".

### 14b. The brief now publishes the gap-vs-catalyst split

The screen is not the story; the asymmetry is. `## Worth your attention` ends with a
`### Gap vs catalyst` subsection — a 2×2 of the actionable gate against catalyst coverage, with
the four counts and one named example per populated cell:

```
| | Catalyst sourced | No catalyst |
|---|---|---|
| **Passes the actionable gate** | the tradeable set | a gap with no driver — a warning, not a trade |
| **Fails the gate** | a missed opportunity — there IS a driver, the book is too thin | noise |
```

The universe is the names the brief **checked** — the actionable set and the wider screen — and
the caption states it, because a table whose denominator is hidden is a table nobody can read.
The catalyst axis is the CSV's own `catalyst` column, so the counts are recomputable from the
artifact itself: the checker derives all four counts from the markdown's tables plus the CSV and
fails the run when they disagree.

This changes the catalyst lookup rule: the coverage is now **every published name** (actionable
set and wider screen), not the actionable set alone. The deep-dive cap of 5 is unchanged and does
not cap the lookups — a lookup is one search, a dossier is an investigation.

### The numbers the four cells actually hold (2026-11-05, the real screen)

89 names checked out of a 481-name screen:

| | Catalyst sourced | No catalyst |
|---|---|---|
| **Passes the actionable gate** | **69** — the tradeable set (e.g. MNTN) | **0** — none |
| **Fails the gate** | **19** — missed opportunities (e.g. ROCK) | **1** — noise (e.g. TXO) |

Read it as: 481 gap names were 69 trades and 412 warnings, and **19 of the warnings had a real
driver behind them** (four of them a Q3 print the pre-market book could not trade) while exactly
one — TXO — had neither a driver nor a book. That is the asymmetry the old brief published as a
bare count of 69.

### Two defects found while writing the checker

- **A published 1 dp number can read the other way of the gate.** RELY (%ADV 4.995) and ROOT
  (4.990) FAIL the raw gate but their published cells read `5.0` — a reader sees a name that
  appears to clear the floor sitting in the wider screen. The contract now says to classify on the
  **raw** CSV values and to flag it when the published number disagrees; the checker accepts
  either classification only within 0.05 of a threshold.
- **The market-cap rule contradicted the artifact.** The spec said "trailing zeros stripped"
  (`$200.97B`), but the 2026-11-05 artifact renders `$701.50B`. The rule is now exact — no
  decimals under $1B, two decimals from $1B to $1T and above — and the checker enforces that
  rendering, which is what catches `$4937.50B`.

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
- **14/14 automated checks pass** on that render: CSV rows equal the screen; every gap and price
  reconciles to the screener pull; the `noise` flag is consistent on every row (empty → true,
  below 1 → true); each name appears in exactly one table row; no actionable row has an empty
  `Why`; the markdown and CSV agree on every gap; no price carries more than 2 dp; the six
  pinned sections are present and in order; the TL;DR has exactly 3 bullets; the mode banner sits
  above the TL;DR.
- All 25 actionable names carry a catalyst sourced from the issuer's release, its IR page, its
  8-K, or a named wire. Two were resolved by identity rather than by price: **BNC** is BNB
  Standard (a BNB digital-asset treasury company, not Banc of California), and **VITL** is Vital
  Farms.
- **2026-11-06 (the v3 work):**
  - `tools/check_ntrt_artifact.py` was run against the **real 2026-11-05 artifact** (481 CSV rows,
    89 published names): **12 of 14 checks pass**, and the only two failures are the two NEW
    requirements the artifact predates (no `### Gap vs catalyst` table). The checker is therefore
    calibrated to the real artifact, not to a synthetic one.
  - The same artifact **plus** the §8 table and the 19 wider-screen catalyst lookups passes
    **14/14** — `CONTRACT OK — contract: 14/14 (ntrt-artifact-v3)`. The rendered table and the
    CSVs are kept as a fixture in `tools/fixtures/ntrt/2026-11-05/`.
  - `tools/test_ntrt_contract.py`: **17/17** — the conforming fixture passes, the reply's
    `contract: 14/14` line is accepted, a wrong count is rejected, a missing file exits 2, and
    **each of the fourteen checks has a fixture that fails it** (two mutations also trip a second
    check, which the test reports).
  - The 19 wider-screen catalysts were sourced from the issuer's release or a named wire (SEC
    EDGAR for ROCK, LZ and ENOV; IR pages for GRAL, ARQT, TPR, RPD; GlobeNewswire for CSV; Yahoo
    for RELY, ROOT, VERX). **TXO has no catalyst** and its cell is the honest `1 — e.g. TXO`.
  - The 2026-11-05 artifact in the outputs repo was **not** re-pushed or modified: the §8 render
    is a derived fixture, and the delivered brief stands as delivered.

## 15. The $200M universe floor was DELETING the day's most violent prints — HIGH

Found 2026-11-04, on the routine's own 09:00 ET fire, by re-pulling the screener **without** the
market-cap filter and comparing the two universes.

The screener request filtered on `market_cap_basic >= 200000000`, **inside the query**. A filter
in the query does not demote a name, it **deletes** it — and the column can be null, which
deletes a name the floor would have kept. Measured on the 2026-11-04 tape:

| name | gap | pre-market volume | % of ADV | market cap | in the brief? |
|---|---|---|---|---|---|
| PARA | **−88.6%** | 16,221,305 | 330.8 | $1.8M | **no** |
| CRIS | **+87.7%** | 83,959,887 | 1313.5 | $7.7M | **no** |
| CENN | −57.2% | 15,028,537 | 394.0 | $5.2M | **no** |
| DKI | +54.0% | 22,004,946 | 949.0 | $1.8M | **no** |
| FTCI | +44.8% | 31,232,906 | 985.8 | $29.2M | **no** |
| HPAI | +27.1% | 73,000,287 | 1401.2 | $11.8M | **no** |

The unfiltered universe carried **543 names** the brief never saw, and the single largest mover of
the day (−88.6%) was one of them. The brief's own TL;DR named **DOX −35.6%** as the headline. It
was not the headline. This is the same class of defect as the REITs (§2 of the contract): a
universe filter that silently removes the most consequential name.

**Fix (skill §10 + the prompt's screener block).**

- The request no longer filters on `market_cap_basic`. The $200M floor is applied **after** the
  scan, in post-processing, so no name is deleted by a filter on a nullable column.
- The floor becomes the **third leg of the gate** (|gap| ≥ 3% AND %ADV ≥ 5% AND cap ≥ $200M), so
  the excluded names are not gate-passers and can be published without corrupting the §8
  asymmetry table.
- `## Wider screen` ends with a **`### Below the $200M floor`** watchlist: the top 5 per
  direction among the names the floor excluded, columns `Ticker | Gap % | % of 30d ADV | Mkt cap |
  Note`. No catalyst lookup (it is a watchlist, not a triage), and its CSV rows carry
  `watchlist (not checked)` in the `catalyst` column so a consumer can tell "not found" from
  "not looked up".
- **The watchlist is MANDATORY when the floor hides the biggest mover**: if the largest |gap|
  among the below-floor names exceeds the largest |gap| in the actionable table, the watchlist
  must be published. The new `SUBFLOOR` check enforces it, so a run cannot pass by staying quiet.

### 15a. `range` is a page size, and the pull was one name away from being half a screen

The same re-pull exposed a second defect in the same request: `"range":[0,600]`. The
unfiltered gainers side returned **exactly 600** names on 2026-11-04 — the range limit, to the
name. That day `totalCount` also read 600, so nothing was lost; the API reports the TRUE total
(verified: `range [0,10]` against the 5,711-name US universe returns `totalCount 5711` with 10
rows), so the pull was complete by one name's luck. One more gainer and the pull would have
silently dropped it.

**Fix:** `range` is now `[0,2000]`, and §7 makes the pull's completeness a check: `totalCount`
must equal the rows returned on **both** sides; if they differ, the pull is truncated, the
missing slice is pulled, and a truncated pull is a failed pull that gets reported rather than
published.

---

## 16. The brief looked for catalysts with a dozen searches when a SOURCED tape already existed — HIGH

Cron #92 (`preopen-catalyst-capture`) publishes a catalyst tape for the same session:
`preopen-feed/{date}-{HHMM}.jsonl` in `karizaco/minimax-cloud-outputs`, one file per checkpoint.
**The 08:30 ET checkpoint is on disk before this brief is written** (09:00 ET).

Measured on the 2026-11-04 tape: **678 rows covering 63 of the 66 actionable names**, each with
the pre-market print, a one-line `why`, a `cat`, a `conf` and — the part that matters — a
**`ref` URL**. The 12 sourced catalysts included DOX (guidance-cut), NRIX (Sanofi), ALIT
(beat-and-raise), DUOL, DDOG, HELE (acquisition), RIOT and FSLR. And it covers **PARA, CRIS and
DKI** — the names the $200M floor hides (§15).

The 2026-11-04 brief spent roughly ten `web_search` calls re-deriving by hand what the tape
already carried with a URL attached, and still ended with **33 of 66 actionable rows carrying no
confirmed catalyst**.

**Fix (skill §11).** The tape is fetched first, and a tape row is used as the catalyst only
when it carries a `ref` and its `conf` is not `low`; `conf: unverified` rows are verified with
one fetch of the URL or left blank. The tape is optional and **fails closed** — cron #92 writes
nothing when its key is unusable — so an absent tape is `pre-open tape: absent` in the
source-health section and a `web_search` fallback, never an error and never an invented tape.
The tape's prices are a second opinion, not the price of record.

---

## 17. The actionable table had no cap, and a tape can put 40 names on one side — MEDIUM

The v2/v3 gate is `|gap| ≥ 3% AND %ADV ≥ 5%`, uncapped. On a normal day that is ~25 names; on the
2026-11-04 election tape it was **66** — a 66-row table, and 33 of those rows had no confirmable
catalyst because the run was chasing drivers for names that were never going to be read.

The contract's instinct was right: §8's asymmetry table wants every published name looked up, so
the fix is not "look up fewer names" but **publish fewer names and account for the rest**.

**Fix (skill §2).**

- The actionable table is **capped at 20 names per direction**, sorted by absolute gap.
- Everything the cap left out is published, not dropped: the `### Also cleared the gate`
  subsection lists every remaining gate-passing name and states the count, in a format the
  checker parses (`Gate-passing names not in the table above: <N>.`).
- Those names carry **no catalyst lookup** and are **not part of the §8 asymmetry universe**; the
  §8 caption states the checked universe and names both exclusions so the denominator is never
  hidden.
- The new `ALSO_CLEARED` check enforces it: a gate-passing name may not be missing from both the
  actionable table and the list. The sibling `GATE` check was relaxed the same way — a cap may
  shorten the table, never silently drop a name.

---

## 18. The prompt's push block never fetched `verify_delivery.sh` and never pushed the CSV — HIGH

The deployed prompt (14,976 chars, byte-identical to the repo file at that time) carried the old
push block:

```bash
for U in "$B/push_artifact.sh" "https://cdn.jsdelivr.net/.../push_artifact.sh"; do
  [ -s /workspace/push_artifact.sh ] || curl -sL -o /workspace/push_artifact.sh "$U"
done
sh /workspace/push_artifact.sh --out ntrt --add ntrt/{date}.md --branch main
sh /workspace/verify_delivery.sh --path ntrt/{date}.md --branch main
```

Three defects in six lines:

1. **The `[ -s file ] || curl` loop is dead** — the first successful download satisfies the guard,
   so the fallback URL is never reached, and a file already on disk is never refreshed. The CDNs
   cache `main` independently (measured 2026-11-04: raw.githubusercontent served a stale blob for
   >17 minutes after a push), and this loop tries the raw CDN FIRST and never the contents API.
   `PROMPT-BLOCKS.md` already carries the corrected three-URL ladder.
2. **`verify_delivery.sh` is called but never downloaded.** A helper that is only *called* is not
   on disk — the DELIVERY step silently had no verifier.
3. **The CSV companion was never pushed.** The skill's contract has mandated the CSV since v2,
   and the prompt's push block only ever added `{date}.md`. The 2026-11-04 run had to push and
   verify the CSV by hand, twice.

**Fix (the prompt's GIT PUSH block).** The helpers are fetched by PROMPT-BLOCKS'
`## SHARED HELPER FETCHES` block in step 1 (contents API first, capability marker); the push
carries both files and the routine number, and both paths are verified:

```bash
sh /workspace/push_artifact.sh --out ntrt --add ntrt/{date}.md --add ntrt/{date}.csv \
   --branch main --nn 25 --msg "cron 25 ntrt-gap-brief-daily {date}"
sh /workspace/verify_delivery.sh --path ntrt/{date}.md  --branch main
sh /workspace/verify_delivery.sh --path ntrt/{date}.csv --branch main
```

`--nn 25` is not decoration: the routine number travels with the call, so a commit carrying the
artifact can be attributed to cron #25 from its subject alone.

---

## 19. Two sources for one date, and the prompt's duplicated blocks — MEDIUM

The prompt resolved `{date}` in the OUTPUT section from `cron_read view:runs` →
`run.scheduled_at_ms`, while the WINDOW CHECK resolved it from `session.created_at` and the
script's printed `fire-date:`. **Two paths to the same fact**, and the prompt's own window-check
block argued for one: the gate and the artifact path must never disagree about which day they
belong to.

**Fix.** `{date}` comes from the window check's `fire-date:` line, and the prompt says so in the
OUTPUT section, in CRITICAL REMINDERS, and in the pushed commit message. `cron_read view=runs` is
no longer called for the date at all.

**The prompt was also slimmed.** The duplicated CONVERSATION TITLE block (~1.2 KB, verbatim from
PROMPT-BLOCKS) is now a pointer to PROMPT-BLOCKS with the skill spec as the backstop — the skill
also carries the title block, so a failed shared fetch still titles the conversation. The
window-check rationale was compressed without touching a single command line or marker check.
Net: the prompt went **15,037 → 16,862 bytes** — smaller than it would have been, but not
smaller than before, because two new data-path rules (no market-cap filter, pull completeness)
have to be stated in the prompt as well as the skill: a rule that lives only in a run-time-fetched
spec is a rule the run can miss at 09:00 with a truncated pull.

---

## What v4 changed, in one place

| File | Change | Effect |
|---|---|---|
| `cloud-prompts/skills/ntrt-gap-brief/SKILL.md` | contract v3 → **v4**: §10 the universe floor, §11 the pre-open tape, §12 the delta pull; §2 the gate's third leg + the per-direction cap; §4 the CSV carries the below-floor rows; §7 the pull must be complete; §9 the checker marker `NTRT_CONTRACT_CHECK_V2` | next fire, no redeploy |
| `tools/check_ntrt_artifact.py` | **16 checks** (was 14): `SUBFLOOR` + `ALSO_CLEARED`; the gate is cap-aware; the below-floor watchlist is excluded from the asymmetry universe | the contract is now a gate for the new rules too |
| `tools/test_ntrt_contract.py` | the conforming fixture now carries a below-floor watchlist and an also-cleared list; **4 new fault-injection cases** | the new checks are proven to bite |
| `cloud-prompts/cron-prompts/25-ntrt-gap-brief-daily.md` | the screener request loses the market-cap filter and gains `range [0,2000]`; the push block fetches the helpers properly, pushes and verifies BOTH files, and passes `--nn 25`; one date source; the duplicated title block becomes a pointer | **deployed byte-exactly** — this file IS the deployed prompt |
| `docs/IMPROVEMENTS-cron25-ntrt-gap-brief.md` | this section | the durable record |

## Verification performed (2026-11-06)

- `python3 tools/check_ntrt_artifact.py` against the **real 2026-11-05 artifact** (481 CSV rows,
  89 published names): **16/16 — `CONTRACT OK — contract: 16/16 (ntrt-artifact-v4)`**. The
  cap-aware gate does not reclassify a single one of its 69 actionable names (the 2026-11-05
  scan carried no name below the floor).
- `python3 tools/test_ntrt_contract.py`: **22/22** — the conforming v4 fixture passes, the reply's
  `contract: 16/16` line is accepted, a wrong count is rejected, a missing file exits 2, and
  **each of the sixteen checks has a fixture that fails it**. Two of the new mutations trip a
  second check as well, which the test reports (`ALSO_CLEARED` also trips `GATE`).
- The scanner's pagination semantics were **measured, not assumed**: `range [0,10]` against the
  5,711-name US universe returns `totalCount 5711` with 10 rows, so `totalCount` is the true
  total and the completeness rule detects truncation.
- The pre-open tape's coverage was measured against the 2026-11-04 screen (678 rows, 63 of 66
  actionable names covered, 12 sourced catalysts).
- The deployed prompt was verified **byte-exactly**: SHA-256 of the deployed `prompt` compared
  with the repo blob after a fresh `cron_read view=list`, with schedule, timezone, enabled,
  session mode, model, project_id and created_at unchanged.

## Revert

```bash
git revert <commit-sha>                    # the v4 change, as its own commit
# or, to restore the pre-change spec exactly:
git checkout pre-ntrt-format-v2-2026-11-04 -- cloud-prompts/skills/ntrt-gap-brief/SKILL.md
```

**The v4 revert is NOT prompt-free.** `git revert` restores the repo, but the DEPLOYED prompt
carries the v4 text until it is re-deployed. To roll the prompt back:

```bash
git show <pre-v4-commit>:cloud-prompts/cron-prompts/25-ntrt-gap-brief-daily.md > /tmp/p25.md
# then re-deploy /tmp/p25.md byte-exactly through cron_update and verify by SHA-256
```

Reverting the SKILL alone is enough for the contract changes (§10–§12, the cap, the tape): they
are re-fetched at RUN time, so they take effect on the next fire with no scheduler change. The
revert of the PROMPT (the screener request and the push block) needs the redeployment above.

The tag `pre-ntrt-format-v2-2026-11-04` points at the pre-change commit
`d2562b1d64cf1ae0742fabf8a1807f3dafa6e76a`.
