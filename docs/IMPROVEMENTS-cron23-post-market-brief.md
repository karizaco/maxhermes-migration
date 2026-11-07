# Improvements — cron #23 (agentic-post-market-brief): the brief is named POST-MARKET, so tomorrow's setup is the product

Four reader-hostile defects in the post-market brief, fixed in the routine's **skill spec**
(fetched at run time) plus a machine checker that fails a run which breaks the contract.
**The prompt was not touched** — a skill-spec change needs no `cron_update` and carries no
byte-drift risk.

Evidence: the 2026-11-03 and 2026-11-04 artifacts and replies, the 2026-11-05 artifact, and
the three data paths, all re-measured on 2026-11-06.

---

## 1. What was wrong

### 1.1 "Tomorrow's setup" was at section 9 of 10

The 2026-11-03 artifact's most valuable content was its last third — `## Tomorrow's setup —
Wednesday 2026-11-04` with the futures/overnight read, the economic calendar, the earnings
calendar and the news-to-watch list. The brief is named **post-market**: its job is to set up
**tomorrow**, and tomorrow was buried.

Measured section positions (H2 order):

| artifact | position of `## Tomorrow's setup` |
|---|---|
| 2026-11-03 | **9 of 10** (after Day's tape, sector rotation, the EOD review, both after-hours sections) |
| 2026-11-04 | 8 of 9 |
| 2026-11-05 | 8 of 9 |

### 1.2 The after-hours movers had no LEVEL

The 2026-11-03 reply gave DOX −44.61%, SWKS −17.35%, ANET +9.47% with their catalysts and
nothing else. A reader cannot act on "ANET +9.47% AH" without knowing where the 16:00 close,
the after-hours high/low and the gap threshold sit. The after-hours table carried
`ticker | after-hours | regular | AH volume | catalyst` — a percentage, not a level.

### 1.3 The participation read was a mid-paragraph statistic

The best sentence in the 2026-11-03 brief was: *"the index was green but the median stock was
not… 2,489 of 4,896 names closed lower, and the liquid set ran 689 up / 921 down, 0.75:1. SPY
+0.30% vs RSP −0.33% is a 63bp cap-weight penalty — a semiconductor squeeze inside a flat
tape."* It sat in the second paragraph, unnamed, with no history: a reader could not tell
whether a 63bp divergence was a regime or a wobble.

### 1.4 The reply had no "tomorrow" line

The reply formatting defects were already fixed (the `### Signal` header is no longer jammed
onto the first bullet, and every bullet carries one ticker — verified on the 2026-11-04 and
2026-11-05 replies). The **content** gap was not: neither the 2026-11-03 nor the 2026-11-04
reply had a "tomorrow" line, so a reader had to open the artifact to learn what tomorrow looks
like. The 2026-11-05 run improvised one *inside the artifact* (`### Tomorrow's setup, in three
lines`) but did not put it in the reply.

## 2. What changed

### 2.1 The contract lives in the skill spec — `§5` of
`cloud-prompts/skills/agentic-post-market-brief/SKILL.md`

- **§5.3 the spine.** Nine `##` sections in a fixed order, with `## Tomorrow's setup` as
  **section 2, right after the TL;DR**. Sections that used to be separate H2s (the universe /
  watchlist EOD review, the day's movers, the breadth block) are folded into the nearest H2 as
  **H3 subsections** — content is never dropped, only headings are reorganised. The checker
  fails an unexpected `##`.
- **§5.4 "Tomorrow's three things to watch"** — exactly three bullets, one name each, each
  with a **level** (the §5.7 gap-fill level, or the 16:00 close) and a **catalyst**. It appears
  in the artifact *and* in the reply.
- **§5.5 the participation read** — six **named metrics** as rows of a `### Market read` table:
  `advancers`, `decliners`, `unchanged`, `median_name_move_pct`, `cap_weight_penalty_bp`
  (signed), `liquid_adv_dec_ratio`. The TL;DR must name them too.
- **§5.6 the cap-weight penalty with its 5-day history** — one table, five dated sessions.
- **§5.7 the after-hours level set** — every row carries `prior_close`, `ah_last`, `ah_high`,
  `ah_low`, `ah_volume`, `gap_pct`, `ah_range_pct`, `gap_fill_level`, with a deterministic
  gap-fill rule and a per-row self-verification identity.
- **§5.8 the reply contract** — `### Signal` alone on its line followed by a blank line
  (the emitted string contains `### Signal\n\n`), one ticker per bullet, the three-things
  section, and the top item of the open research queue carried into the reply.
- **§5.9 the checker** — fetched at run time with a capability marker so a stale copy cannot
  win the ladder.

### 2.2 The checker — `tools/check_postmarket_brief.py` (new)

`python3 tools/check_postmarket_brief.py --artifact <md> [--reply <txt>]` — exit 1 and one
printed line per failure. It asserts the marker, the spine and its order, the five setup H3s,
the three-things bullets, the six market-read rows, the 5-session history, the after-hours
columns and every row's cells, the open research queue, and the four reply rules.

### 2.3 The regression test — `tools/test_postmarket_contract.py` (new)

Builds a contract-shaped artifact and reply, requires exit 0, then mutates them twelve ways and
requires the checker to fail each time.

```
13/13 checks behaved correctly
RESULT: the contract is satisfiable and every breach is caught
```

### 2.4 What did NOT change

- **The source ladder.** bridge `market-recap` for closes/movers/macro/history, the TradingView
  scanner for breadth and extended hours, cron #20's CSV for the universe, web for catalysts
  and calendars. The put/call **component split is still never invented** — the total was
  sourced (0.87 on 2026-11-03), the components disagreed (0.56 vs 0.67), and the 2026-11-03
  run correctly refused to invent one. §5.10 keeps that rule.
- **`## Open research queue` stays**, with its top item carried into the reply.
- **The prompt** (`cloud-prompts/cron-prompts/23-agentic-post-market-brief.md`) is byte-for-byte
  unchanged — it fetches the skill spec at run time, so the contract lands on the next fire
  with no `cron_update` and no drift risk.

## 3. The evidence

### 3.1 The checker bites on the three real pre-contract artifacts

| artifact | failures |
|---|---|
| `daily-briefs/2026-11-03-post-market.md` | **28** — wrong marker, spine out of order, `Tomorrow's setup` after `Day's tape`, no `### Market read`, no cap-weight history, after-hours table missing `prior_close` … |
| `daily-briefs/2026-11-04-post-market.md` | **38** — same, plus `## Breadth & volatility` / `## Universe EOD review` as unexpected `##` |
| `daily-briefs/2026-11-05-post-market.md` | **36** — same, plus `## Day's movers` / `## Watchlist EOD review` as unexpected `##`, and no `## Method notes` |

These artifacts *looked* fine. That is the point.

### 3.2 The participation metrics are computable from the published universe

From cron #20's `us-eod/2026-11-05.csv` (4,896 names), measured 2026-11-06:

| metric | value |
|---|---|
| `advancers` / `decliners` / `unchanged` | 666 / 4,145 / 29 |
| `median_name_move_pct` | −3.018% |
| `liquid_adv_dec_ratio` (cap > $2B, n = 1,627) | 218 : 1,406 = **0.155 : 1** |

### 3.3 The cap-weight penalty reproduces the published number, and its history is one call

`market-recap price_history` for `["SPY","RSP"]`, 2026-10-28 → 2026-11-05, measured
2026-11-06:

| session | SPY % | RSP % | `cap_weight_penalty_bp` |
|---|---|---|---|
| 2026-10-29 | −0.382 | +1.200 | −158 |
| 2026-10-30 | −1.773 | −0.786 | −99 |
| 2026-11-02 | −0.479 | +0.765 | −124 |
| 2026-11-03 | +0.299 | −0.327 | **+63** ← the published 2026-11-03 figure, reproduced |
| 2026-11-04 | +1.652 | +1.856 | −20 |
| 2026-11-05 | −4.409 | −2.893 | −152 |

### 3.4 The after-hours level set is one scanner call, and each row self-verifies

The TradingView `america` scanner exposes `postmarket_close`, `postmarket_high`,
`postmarket_low`, `postmarket_volume` and `postmarket_change`. Measured 2026-11-06 on a live
row (LGO): `close` 0.3241, `postmarket_close` 0.35, `postmarket_change` +7.99136% — and

```
(0.35 − 0.3241) / 0.3241 × 100 = 7.99136%      ✓ identity holds
```

so a row that disagrees with itself is dropped rather than published.

### 3.5 The next fire

The 2026-11-06 22:30 ET fire is the first under the new contract. Its artifact must carry the
marker `postmkt-artifact-v2`, the spine, the six named participation metrics, the 5-session
cap-weight history and the after-hours level columns — and its reply must carry
`### Signal\n\n`, one ticker per bullet, three things to watch with levels, and the top research
question. The checker is the gate.

---

## 4. The 2026-11-06 fire under the new contract — what it caught, and what the data path hid

The 2026-11-06 22:30 ET fire was the first run under `postmkt-artifact-v2`. It shipped
(`daily-briefs/2026-11-06-post-market.md`, byte-verified on `origin/main`) and the checker
passed after one fix. Four findings below are new; three of them changed the routine's **skill
spec**, so the next fire inherits them with no `cron_update`.

### 4.1 The contract caught exactly one thing, and it was a word

The checker failed with a single finding: a `### Signal` bullet naming GOGO and the FCC
carried **two** tickers. The checker's `NON_TICKERS` list is two-letter exchange/short-word
vocabulary plus a handful of three-letter abbreviations (`AMC`, `EPS`, `CPI`, `ETF`, `VIX`…) —
`FCC` is not on it, so the rule fired on an ordinary word. Rewritten as "the spectrum regulator",
the artifact and the reply passed: `CONTRACT postmkt-artifact-v2: ok`.

The lesson is mechanical and worth stating plainly: **the one-ticker rule is lexical, not
semantic.** Any second capitalised token in a bullet is a failure, including a regulator, an
agency or an acronym the writer never thought of as a ticker. The skill spec's §5.8 rule 2 now
says so and gives the workaround (name the organisation in words).

### 4.2 The futures quotes were frozen at the 16:59:59 ET settlement — the "overnight" was not published

Every futures row the bridge returned (ES=F, NQ=F, YM=F, RTY=F, ZN=F, and CL=F, GC=F, DX-Y.NYB)
carried `as_of` **16:59:59 ET** when read at the 22:30 ET fire — five and a half hours stale, and
the exact timestamp of the cash-close settlement. `market_state` still read `open`, so nothing in
the payload says "stale"; only the timestamp does.

At a 22:30 ET fire the contract's step 7 asks for "the overnight move … the setup, not the cash
close" — and the source of record cannot supply it. Publishing that table as *the overnight*
would have been a fabricated setup. The 2026-11-06 artifact publishes it as **Friday's
settlement**, says the post-18:00 ET Globex/Asia move is absent, and counts it in
`degraded_sources:` (2, alongside the CBOE page).

**Skill-spec change:** step 7 now requires reading `as_of` on every futures row and, if it is
more than ~30 minutes older than the fire, relabelling the table as the prior session's
settlement with the overnight explicitly declared unpublished.

### 4.3 The $1B screen floor hid the session's biggest after-hours movers

The contract's extended-hours screen keeps names above $1B of market cap. On 2026-11-06 the
screen's top gainer printed **+9.77%** (MCHPP); the session's actual after-hours leader printed
**+110%** (OMH, 420x relative volume), then TGE +71% (a 6-K at 17:14 ET transferring four hotel
assets for 198,630,381 newly issued shares, after which AMTD Group held 96.7% of the voting
power), PARA +18%, FTH +10% — and on the other side SDA −19% (566M shares) and VIVK −16%. A
reader who saw only the table would have believed the biggest movers of the night were +9.8% and
−7.0%.

**Skill-spec change:** §5.7 now requires one extra pull of the same screen *without* the
market-cap floor, published in `## Source health`, so the table is never mistaken for the whole
after-hours tape. The published table itself stays on the contract's screen.

### 4.4 The CBOE daily statistics page carries no session date stamp

The put/call page's embedded payload (`optionsData.ratios`) gives TOTAL 1.06, INDEX 1.07, ETP
1.25, EQUITY 0.89, VIX 0.70 and the volume split (11,225,416 puts / 10,589,764 calls,
21,815,180 contracts) — and no date anywhere in the data. The value was published as read, with
the session declared undatable, and counted as the second degraded source.

**Skill-spec change:** step 8 now says to publish the total as read, say the session cannot be
dated with certainty, and count it in `degraded_sources:` rather than asserting a session.

### 4.5 The cap-weighted sector column gave a non-index member index-like weight

The universe's cap-weighted Industrials return printed **+2.38%** while XLI printed **+0.12%**.
The gap is SpaceX: a $1.82T cap on a +8.6% day, which is **+1.82pp** of the sector number
(ex-SpaceX the sector is +0.71%, in line with its +0.84% median). Every other sector row
reconciled with its ETF within a few tenths.

The generalisable lesson is not about SpaceX: **a cap-weighted sector return computed over the
whole listed universe silently assigns index-like weight to a company that is not in the index**,
and the `cap_weight_penalty_bp` metric the TL;DR leans on inherits exactly the same
concentration. The artifact therefore names the constituent, publishes the sector with and
without it, and makes it the first item of the open research queue — which the reply carries, as
the contract requires.

**Skill-spec change:** step 3 now requires (a) de-duplicating share classes by
`cap_source_symbol` and dropping `EX_DISTRIBUTION` rows before weighting (cron #20's rule),
and (b) cross-checking each sector row against its ETF and publishing any >0.5pp gap.

### 4.6 What the participation read looked like, for the next run's baseline

| metric | 2026-11-06 |
|---|---|
| `advancers` / `decliners` / `unchanged` | 2,667 / 2,030 / 28 (4,725 usable names) |
| `median_name_move_pct` | +0.236% |
| `cap_weight_penalty_bp` | **+69** |
| `liquid_adv_dec_ratio` (cap > $2B, n = 1,785) | 868 : 910 = **0.954** |

The `cap_weight_penalty_bp` series continues across runs: −124, **+63**, −20, −152, **+69** for
2026-11-02 → 2026-11-06, with the +63 reproducing the published 2026-11-03 figure from the same
source and method.

### 4.7 The next fire

Fetch the spec; the 2026-11-06 rules (futures `as_of` assertion, the no-floor disclosure pull,
the CBOE date caveat, the sector de-duplication and ETF cross-check, the one-ticker wording
trap) are already in it. The checker is still the gate — and on 2026-11-06 it caught a single
word, which is the argument for keeping it.
