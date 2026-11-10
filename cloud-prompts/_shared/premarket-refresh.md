# Pre-market refresh — 09:20 ET checkpoint for cron #26

The morning brief (cron #26, 08:30 ET) publishes a tape that is already 50+ minutes old by the
time the market opens, and the most actionable moment for a pre-market brief is the last twenty
minutes before the open. This procedure publishes a REFRESH, not a second brief.

**It does not re-research anything.** No news searches, no clustering, no rewriting. It re-pulls
the same screen and reports what moved.

---

## STEP 0 — THE WINDOW CHECK (run FIRST, before anything else)

The scheduler owns the day-of-week and the hour, so this gate exists for ONE reason: a cron
expression cannot express a **market holiday**, and the scheduler fires Mon-Fri *including*
them. On a holiday the market is closed and there is nothing to report.

**Resolve the fire's scheduled instant FIRST, then judge the gate against it — never against
the wall clock.** The platform resumes a crashed cron conversation IN PLACE, hours or days
later, so on a replay "now" names the resume day, not the fire day.

Resolve it with ONE call, no cron_read needed:

```
mcp_invoke  tool_name=session_get  arguments={"session_id":"me"}
```

Take `session.created_at` (epoch milliseconds) — the instant the platform dispatched THIS
fire — and pass it as `--scheduled-at-ms`. The script prints `fire-date:`; use THAT for the
artifact path, so the gate and the artifact can never disagree about which day they are.

```bash
# --- fetch the ONE shared window check (run-time fetch: fixes land with no redeploy) ---
# The CAPABILITY check below is mandatory, not decoration. An OLDER copy of this script is
# still published, and it silently IGNORES unknown flags - so without the check you would
# run a gate that never fires, and a holiday fire would publish a brief for a closed
# market. The CDNs also cache independently, so one of them can serve stale bytes for
# hours. The contents API is authoritative and is not CDN-cached, so it is tried FIRST.
S=/workspace/window_check.sh
for U in \
  "https://api.github.com/repos/karizaco/maxhermes-migration/contents/cloud-prompts/_shared/window_check.sh?ref=main" \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/window_check.sh" \
  "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/window_check.sh" ; do
  curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" -o "$S.tmp" "$U" 2>/dev/null
  # A 404 page is a non-empty body that is NOT a script, and an older script silently
  # ignores the flags below. Require BOTH: a real script AND the capability marker.
  if head -1 "$S.tmp" 2>/dev/null | grep -q '^#!' && grep -q 'WINDOW_CHECK_V2' "$S.tmp" 2>/dev/null; then
    mv -f "$S.tmp" "$S"; break
  fi
  rm -f "$S.tmp"
done
if [ ! -s "$S" ] || ! grep -q 'WINDOW_CHECK_V2' "$S" 2>/dev/null; then
  echo "window-check: UNAVAILABLE (no version of the shared script with the replay-aware gate)"
  echo "no artifact; no push"
  exit 1
fi

# SCHEDULED_AT_MS = session.created_at from the session_get call above (epoch ms).
sh "$S" --scheduled-at-ms "$SCHEDULED_AT_MS" \
   --out daily-briefs --name agentic_pre_market_brief_refresh \
   --label "Cron #26b agentic-pre-market-brief-refresh" \
   --nn 26b

If the script exits non-zero the fire is OUT OF WINDOW: write nothing, push nothing, and
reply:

```
out-of-window: <reason printed by the script>
file: no artifact (holiday skip — daily-briefs/$DATE-pre-market-refresh.md is intentionally absent)
push: marker pushed (refs/skipped-markers/$DATE_SKIPPED_agentic_pre_market_brief_refresh.md) | marker push FAILED | marker push skipped (push script unavailable)
errors: 0
```

---

## What this produces

`daily-briefs/{date}-pre-market-refresh.md` — a short addendum:

1. **Front matter** (machine-readable, like the morning brief):

   ```
   ---
   date: <YYYY-MM-DD>
   cron: 26-agentic-pre-market-brief-refresh
   fire_time_et: <YYYY-MM-DD HH:MM>
   snapshot_et: <HH:MM>
   source: TradingView america scanner
   status: ok
   changes_since_morning: <n>
   ---
   ```

2. **Refreshed top-of-book** — the same screen the morning brief used (the universe, the
   liquidity gate and the quality floor are defined in
   `cloud-prompts/skills/agentic-pre-market-brief/SKILL.md`, Step 2 and Step 2b — read them, do
   not re-invent them):

   | Ticker | Name | Pre-market | % | Pm vol | %ADV | Mkt cap | Sector |
   |---|---|---|---|---|---|---|---|

   Top 15 gainers and top 10 decliners, with a note of the snapshot time on every row.

3. **What changed since the morning brief** — the names whose pre-market gap moved most, read
   against the morning brief's own CSV (`daily-briefs/{date}-pre-market.csv` on the outputs
   repo, branch `main`). Sort by the size of the change, not by the size of the gap.

4. **A one-line verdict** — is the tape more or less directional than it was at 08:30 ET?

5. **A machine-readable companion CSV** — `daily-briefs/{date}-pre-market-refresh.csv`, the same
   screen the tables were built from, so a DOWNSTREAM routine can consume the numbers without
   parsing markdown tables. See `## The companion CSV` below for the pinned header.

Two more blocks are published, both unnumbered so that NO existing section number changes.
They sit directly under the front matter, because this file is read twenty minutes before the
open and the reader needs the decision first.

### `## Bottom line` — exactly three lines, the decision

```
## Bottom line

1. **The one setup** — <TICKER> — <level> is the trigger; invalidated by <side> <level>.
2. **The one risk** — <TICKER or group> — <what breaks it> — <level>.
3. **The one thing to watch at the open** — <TICKER> — <condition>.
```

- **EXACTLY three lines.** Not two, not four.
- The three labels are literal, capitalised, and in this order: `The one setup`, `The one risk`,
  `The one thing to watch at the open`.
- Line 1 MUST carry a digit **and** the word `invalidat*`. "ALIT is running" is not a setup.
  "ALIT above 8.04, invalidated by a trade back to/below prior close 5.97" is.
- Line 1 MUST name a name whose **Driver is anchored** — `CASH-OUT`, `CASH-IN`,
  `LIABILITY-RESOLVED`, `ASSET-VALUE` or `EARNINGS-RAISE`, carrying the `+ANCHORED` suffix.
  Those are the classes with measured evidence: on 2026-11-04 every name whose gap ran carried a
  hard number in its catalyst (a $37.00 offer, a $0.70 special dividend, a $7.35B settlement,
  $409.5M of loans resolved) and every name whose gap faded did not.
- **The setup slot has a LADDER — take the first rung that is satisfiable.** The gate's purpose is
  to promote a gap **anchored to a hard number** and never an unanchored one; the class list is
  the set of classes that have carried such an anchor, not a second gate.
  1. **Anchored + one of the five classes** → name it and print the class.
  2. **Anchored + any other class + the gap is still HOLDING (Hold % ≥ 80)** → name it, print
     the class, and state the deviation in one clause of line 1 and once in Source health.
     Measured 2026-11-09: four of the 25 headline names carried an anchor (DCTH, IMVT —
     `EARNINGS-RECONFIRM`; ZURA, IBRX — `EARNINGS-CUT`) and **none** was in the five classes, so
     rung 1 was empty. DCTH took the slot because it was the only anchored name whose gap was
     still holding (Hold 96%).
  3. **Nothing anchored at all** → say so honestly — "no name carries an anchored catalyst this
     morning — the setup is cash" — rather than promoting a name that does not.
  **Never promote an unanchored name to fill the slot, and never publish "no anchored catalyst"
  when an anchored name exists.** Both errors are live: the first promotes a narrative gap, the
  second is a false statement about the tape.
  **A gate may not be tightened without a second session.** Measured 2026-11-09: the five-class
  list was written from ONE session's evidence (2026-11-04). A name class may be ADDED to the
  eligible set when a second session shows an anchored gap of that class running — but a class
  may not be REMOVED, and no class may be invented at run time to fill the slot.
- Line 1's trigger level is the name's **PM high** (the level that must break for the gap to
  extend) and its invalidation is the name's prior close, written with its side.
- The pm %ADV band is NOT part of this gate. It is a descriptor of the print, not a predictor —
  see §`Gap quality`.

### `## What to watch at the open` — three names, their levels, and the two rules

A short table of the three names the bottom line refers to, then the rules that turn this file
into a plan rather than a list:

| Name | Prior close | PM last | PM low | PM high | Trigger | Invalidation |
|---|---|---|---|---|---|---|

- **Rule 1 — the open is the verdict on the gap.** An open BELOW the last pre-market print means
  the gap is being sold, not bought. Measured 2026-11-04: every name that gave back its gap
  opened below its last pre-market print (FTCI −0.48%, BRKR −1.67%, FTK −1.57%), and every name
  that ran opened at or above it. **This refresh fires at 09:20, so it cannot apply Rule 1 — it
  publishes the last pre-market print and the PM low so the reader can apply it at 09:31.**
- **Rule 2 — the 30-minute candle is the breakout test.** If, thirty minutes after the open, the
  session high is STILL the opening-range high, the gap is a fade, not a breakout; the levels in
  this file are then exit levels, not entry levels. A name that breaks its opening range and
  holds above it is a breakout. This is a 10:00 check, not a 09:45 one.

### `## Gap quality — can this gap hold?`

The ranking that justifies the bottom line. One row per headline name (the top 15 gainers and
the top 10 decliners), all from the SAME single pull:

| Ticker | Name | Gap % | PM range | Hold % | pm %ADV | Print | Driver | Key level | Invalidation |
|---|---|---|---|---|---|---|---|---|---|

- **PM range** = `premarket_low` – `premarket_high` (the scanner publishes both; a gap that has
  already been half-filled shows up here and nowhere else).
- **Hold %** = `(premarket_close - premarket_low) / (premarket_high - premarket_low) × 100`,
  rounded to 0 dp. 100 = the last print is AT the top of its pre-market range (the gap is
  holding); 0 = it is at the bottom (the gap is gone). `n/a` if the range is zero.
- **pm %ADV** = `premarket_volume / average_volume_30d_calc × 100`.
- **Print** — two independent DESCRIPTORS of the tape, joined with `+`. **They are not filters.
  Do not rank on them and do not gate the bottom line on them.** Measured counter-evidence, both
  days:
  - the auction flag, on pm %ADV: **`AUCTION`** if 2 ≤ pm %ADV ≤ 30; **`QUOTE`** if pm %ADV < 2
    (a print on almost no volume — it can gap further, or vanish, for free); **`CHURN`** if
    pm %ADV > 30 (the float is turning over; that is churn, not sponsorship).
  - the holding flag, on Hold %: **`holding`** if ≥ 80; **`half-filled`** if < 50; **`mid`**
    otherwise.
  - **Why they are not filters.** On 2026-11-04 CRCT (+49.8%) and MMM (+9.0%) both printed on
    `QUOTE`-thin volume and both ran, while FSLR and BRKR printed on `AUCTION` volume and both
    faded. On 2026-11-06 **zero of the 25 headline names** cleared `AUCTION+holding`, so gating
    on it would have published an empty bottom line on a day when the tape was fine. Read these
    two columns to understand HOW the gap was made and whether it is still holding — the
    **Driver** column is what ranks.
- **Driver** — the catalyst class, from the fixed vocabulary below.
- **Key level** — the **prior close**, the gap-fill level. (A level published by a sourced
  catalyst replaces it, with the source named in the cell.)
- **Invalidation** — always a DOWNSIDE trigger, always with its side:
  gap-up → `back to/below prior close <close>`; gap-down → `below PM low <premarket_low>`.

**The Driver vocabulary — fixed, and applied to the morning brief's OWN sourced catalyst:**

The refresh does **not** search for news and does **not** invent a reason. It reads the
catalyst the 08:30 brief already sourced (the morning brief's §2 theme clusters and their news
URLs) and classifies it. One vocabulary, applied the same way every day:

| Driver | Meaning |
|---|---|
| `CASH-OUT` | cash comes TO the holder — a dividend (incl. a special one), a buyback, a redemption |
| `CASH-IN` | an acquirer puts cash IN — a takeover offer, a merger at a price |
| `LIABILITY-RESOLVED` | a contingent liability is capped or settled — a litigation settlement, a provision taken |
| `ASSET-VALUE` | previously-impaired value is crystallised — loan resolutions, a NAV/discount-to-NAV event |
| `EARNINGS-RAISE` | a beat AND a guidance raise |
| `EARNINGS-RECONFIRM` | a beat with guidance unchanged |
| `EARNINGS-CUT` | a miss, a loss, or a guidance cut |
| `CORPORATE-EVENT` | a company-specific event that is not cash, liability or a reported result — a governance, legal or regulatory shock |
| `SECTOR-BETA` | a group move — policy, macro or a sector theme; no company-specific news |
| `NONE` | no sourced catalyst for this name |

**Scope of the `EARNINGS-*` classes.** They describe the DIRECTION of a company-reported
RESULT, not the instrument that produced it: an earnings print, a clinical readout, a regulatory
decision or a trial outcome are all "a beat" or "a miss". Measured 2026-11-09: IMVT's fiscal-Q2
release met its primary endpoint (ACR20 92.5% vs 75.6% placebo, p=0.0139, cash $722.3M) — a beat
with no guidance change, so `EARNINGS-RECONFIRM`; ZURA's Phase 2 missed its primary endpoint and
the company discontinued the indication — a miss, so `EARNINGS-CUT`. Do **not** stretch
`ASSET-VALUE` to cover a readout: that class means previously-impaired value was crystallised.

**`CORPORATE-EVENT` exists because the tape produces them.** Measured 2026-11-09: NVDA's board
opened an independent investigation into its CEO — a sourced catalyst with `has_news = yes` that
no cash, liability or reported-result class describes. A run that has to bend a class to fit it
will bend a different one tomorrow; this is the class for that case.

- **`ANCHORED` suffix.** Append `+ANCHORED` when the catalyst carries a **hard number** — a
  price, a per-share amount, a settlement figure, a balance-sheet total. Measured 2026-11-04:
  every name whose gap ran carried one (a $37.00 offer, a $0.70 dividend, a $7.35B settlement,
  $409.5M of loans resolved) and every name whose gap faded did not (revenue doubled, "path to
  profitability", a policy hope). A narrative gap has to be built entirely by trading, and it is
  fragile.
- **The vocabulary is CLOSED.** A run may not invent a class, or stretch one, to make a name fit.
  If the catalyst genuinely has no class, use `unclassified` and say so once in Source health.
- If the morning brief is missing, every Driver is `unclassified` and Source health says so once.
- **`has_news = no` in the morning CSV ⇒ `NONE`, whatever the cluster.** A name can sit in a
  cluster's TABLE without having a catalyst in that cluster's PROSE (2026-11-09: FTH, NKTX and
  ABEO were in the biotech table with no per-name catalyst). **That is a finding, not a blank**:
  a gap with no sourced catalyst is the profile that faded.


## The companion CSV — the screen, machine-readable

The markdown is for a reader; the CSV is for the next routine. On 2026-11-05 cron #26 was
rebuilt 21 hours after its fire, and it had to recover its screen by PARSING THIS FILE'S
MARKDOWN TABLES — which is how a routine ends up with 702 of the 779 names it should have
had. A pinned CSV makes that chain exact.

Write `daily-briefs/{date}-pre-market-refresh.csv` beside the markdown, one row per name in
the screen, with this header and this order:

```
ticker,name,premarket_close,premarket_change_pct,premarket_volume,avg_volume_30d,pct_of_adv,prior_close,prior_session_change_pct,live_close,live_change_pct,live_volume,market_cap,sector,exchange,screen_complete
```

- **`prior_close` is DERIVED, never taken from the screener's `close` column.** Once the
  regular session is open that column carries the LIVE intraday price, so a prior close taken
  from it is wrong by exactly the day's move. Derive it:
  `prior_close = premarket_close / (1 + premarket_change_pct / 100)`. (Verified 2026-11-05:
  SPY 766.81, QQQ 691.95, APP 271.75 — all three exact against an independent quote source.)
- **Derive it from the values THIS CSV publishes, not from the raw pull.** Publish
  `premarket_close` at 4 dp and `premarket_change_pct` at 2 dp, and compute
  `prior_close = round(premarket_close / (1 + premarket_change_pct / 100), 4)` **from those
  published values**, so every row reproduces its own prior close and a reader can check it:
  `467.25 / (1 + 4.06/100) = 449.0198`. Deriving from the raw pull instead leaves rows that do
  NOT reconcile — the published price and change are rounded, so the row's own numbers give a
  different close than the row publishes (24 of the 693 rows in the 2026-11-09 CSV: a ≤4.5¢
  difference, and half a cent on the one headline name affected). The checker asserts this
  reconciliation on every row.
- **`live_*` are the LIVE regular session at the pull, not pre-market.** They are in the CSV
  so a downstream routine can say how a gap actually behaved after the open. They are never
  pre-market numbers, and the column names say so.
- **At the normal 09:20 ET pull the session has NOT opened, so `live_*` are BLANK.** The regular
  session opens at 09:30; a 09:20 pull has no live regular-session price, change or volume to
  publish. **Write them empty — never 0** (a zero is a number, and a downstream routine that
  divides by it will divide by a lie). Say it once in Source health. The columns become
  meaningful only on a post-open pull (the late-pull branch above), where they carry the live
  values and the front matter says `market_open_at_pull: true`.
- **`premarket_time` is NOT published per row.** It is the pre-market session START (04:00 ET),
  not the last trade time, so a row stamped with it carries a 5-hour-old "snapshot". Publish the
  pull's own clock (`snapshot_et`) instead.
- **`screen_complete`** is `true` when `len(rows) == totalCount` held for BOTH screens, `false`
  when the ±3% band exceeded the row cap. On `false` the markdown's counts are FLOORS, not
  exact counts, and the markdown must say so.
- **One pull, one table.** The CSV and the markdown are built from the SAME merged table. If
  they disagree, the artifact is broken — and the numbers must trace to the pull.

The push stages the whole output tree, so the CSV rides along in the same commit as the
markdown. Pass `--add` ONCE (the markdown); the CSV comes with it.

## Inputs

| What | Where |
|---|---|
| the morning brief | `https://raw.githubusercontent.com/karizaco/minimax-cloud-outputs/main/daily-briefs/{date}-pre-market.md` |
| the morning screen (CSV) | `https://raw.githubusercontent.com/karizaco/minimax-cloud-outputs/main/daily-briefs/{date}-pre-market.csv` |
| the live screen | `POST https://scanner.tradingview.com/america/scan` — see the skill spec for the exact body |
| the morning brief's spec | `https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/skills/agentic-pre-market-brief/SKILL.md` |

**The pull MUST carry `premarket_high` and `premarket_low`.** The skill spec's Step 2 column list
includes them; a pull without them cannot compute the PM range, the Hold % or the `half-filled`
flag, and the gap-quality table would be silently blank. If either column comes back missing or
null for every row, the gap-quality table is published as `n/a` with that stated once in Source
health — it is never quietly omitted.

**The morning brief's MD is read for the Driver column**, because the catalyst the refresh
classifies is the one the 08:30 brief already sourced (its §2 theme clusters and their news
URLs). That is a read of a published file, not a news search.

The morning brief's CSV is the reference: same rows, same screen, one pull earlier. If the live
screen and the CSV disagree on a name by more than 0.2 percentage points, the market moved —
that is the point of this file.

## The pull is a CONTRACT, not a suggestion

**Pull with `range:[0,1000]` and ASSERT `len(rows) == totalCount` on BOTH screens.** The scanner
returns `totalCount` next to `data`, so the assert costs nothing. The ±3% band is routinely
larger than one page, and the scanner honours a range SILENTLY — HTTP 200, no warning, no
truncation flag. Measured 2026-11-05: `range:[0,400]` returned 400 of 547 decliners and the
147 omitted rows were the least negative ones, so the headline table looked complete while
`down_3pct` was published as a count when it was a FLOOR.

**If the assert fails**, the band is larger than the cap: publish the rows you have, set
`screen_complete: false` in the front matter and in every CSV row, and say in Source health that
the published counts are FLOORS, not exact counts. Never publish a truncated count as if it were
the whole band. A count that is known to be a floor is fine; a count that LOOKS exact and is not
is the defect.

**Gate A and Gate B are decided on a RECONCILED market cap** (the brief skill's Step 2b). The
scener's `market_cap_basic` is `close × shares outstanding`, and it does not refresh the share
count for corporate actions: measured 2026-11-09 it reported **$143,016,256** for **NWGL** after a
one-for-80 ADS reverse split and an ADS ratio change, pairing the POST-split price with the
PRE-split share count — **87× too high**; the real cap sat in the $0.5M–$1.9M range, so a
sub-$2M shell topped the headline gap table over Gate B. The error runs BOTH ways (a count that
predates a later issuance makes the cap too LOW). **Reconcile the cap for every name whose
scanner cap is near a gate boundary ($100M for Gate B, $200M for Gate A) before it tops a
headline table**, and publish the reconciled figure.

**`premarket_time` is the pre-market session START (04:00 ET), not the last trade time.** It is
unusable as a per-row snapshot stamp. **Publish the pull's own clock** as `snapshot_et` and on
every row.

---

## The artifact skeleton — PINNED

Two days of the current spec (2026-11-09, 2026-11-10) published **different skeletons**: 7
front-matter keys versus 11, unnumbered sections versus `## 1.` … `## 5.`, and the gap-quality
block before the top-of-book versus after it. A reader and a checker cannot both work with a
skeleton that moves. **Publish exactly this, in this order:**

```
---
date: <YYYY-MM-DD>
cron: 26-agentic-pre-market-brief-refresh
fire_time_et: <YYYY-MM-DD HH:MM>
snapshot_et: <HH:MM>
source: TradingView america scanner
status: ok
changes_since_morning: <n>
up_3pct: <n>
down_3pct: <n>
screen_complete: true
---

## Bottom line
## What to watch at the open
## 1. Refreshed top-of-book
### Top 15 gainers
### Top 10 decliners
### Thin tape
## 2. Gap quality — can this gap hold?
## 3. What changed since the morning brief
## 4. Verdict
## 5. Source health
```

- `cron:` is the literal string `26-agentic-pre-market-brief-refresh`.
- **`changes_since_morning`** = the number of names present in BOTH the live screen and the
  morning CSV whose gap moved by **more than 0.2 percentage points**. Define it that way in the
  front matter so two runs mean the same thing and the auditor can check it.
- `up_3pct` / `down_3pct` = the band counts **from this pull**; `screen_complete` = `true` when
  the assert held on both screens.
- `## 5. Source health` is where every caveat lives. A caveat that lives only in prose above it
  is a caveat the reader has to find.

---

## Rules

- **One pull.** Pull the screen ONCE and use it for every table and every number, including the
  prose. The morning brief shipped an artifact that contradicted itself because two pulls fed
  two sections; do not repeat that.
- **The fade and entrant counts are computed on the BAND, not on the CSV.** The morning brief's
  CSV carries its band PLUS the thin-tape names PLUS individually fetched names — 931 rows on
  2026-11-09 against a 598-name band. Comparing "morning CSV rows" against the live band rows
  counts names that were never in the band: the raw base gave **394** fades on 2026-11-09, the
  true figure is **90**. **Filter the morning CSV to `abs(gap_pct) >= 3` first.**
- **A cross-pull count inherits the baseline's completeness.** The morning brief's published band
  counts are FLOORS unless its front matter carries `screen_complete: true` (2026-11-05 and
  2026-11-06 were pulled with the `range:[0,400]` cap: the 2026-11-06 brief published **403
  gainers** while the band actually held **650**). When the baseline is a floor, the fade and
  entrant counts are floors too, and the comparison base must be named in Source health.
- **Thin tape is published IN FULL.** The Gate-A-passing, Gate-B-failing names are published, all
  of them, with the count of each side. On 2026-11-06 the block claimed "22 gainers and 22
  decliners qualify" and showed **18 rows**; on 2026-11-09 it claimed 48 and showed 20. A
  truncated block with an unstated truncation reads as a complete one. If you must truncate, the
  line has to say "showing N of M".
- **Never invent a number.** Every price and percentage comes from the screen or from the
  morning CSV.
- **No catalyst SEARCH.** This file does not look for news and does not write a reason. It
  **carries** the catalyst the 08:30 brief already sourced and labels it with the fixed Driver
  vocabulary. A name with no sourced catalyst is `NONE`, and `NONE` is a finding.
- **The Driver is never a guess.** If the morning brief does not source a catalyst for a name,
  the Driver is `NONE` (or `unclassified` when the brief itself is missing) — never inferred
  from the price action. A gap that rose 40% because it rose 40% is not a driver.
- **The Driver's SOURCE is the morning CSV, not prose you re-mine.** The morning brief already
  publishes, per name: `setup_theme` (the theme cluster the name belongs to), `has_news` (whether
  a catalyst was sourced for it) and `setup_published`. **Read them:**

  | Morning CSV says | Driver |
  |---|---|
  | `has_news = no` | `NONE` — no sourced catalyst. This is a finding, not a blank. |
  | `has_news = yes` + a `setup_theme` cluster | classify that cluster's catalyst with the fixed vocabulary below |
  | `has_news = yes` + no `setup_theme` | classify the name's own catalyst from the brief's §9 earnings table |
  | the name is in no cluster and has no row in the morning CSV | `NONE` (it is new to the screen since the brief) |

  **A name in a cluster's TABLE is not the same as a name with a catalyst in that cluster's
  PROSE.** On 2026-11-09 FTH, NKTX and ABEO sat in the biotech cluster's table with
  `has_news = no` and no per-name catalyst in its narrative — they are `NONE`. Reading the
  clusters by eye is how a run ends up publishing a class it invented; reading two columns is
  how it ends up reproducible.
- **The `+ANCHORED` suffix is decided by the catalyst, not by the name.** See the vocabulary
  below for the test; the rule that matters here is that a run may not invent a new class to
  make a name fit.
- **If no name carries an anchored catalyst, publish that.** An empty bottom line is a
  legitimate result on a bad tape. Do not promote an unanchored name to fill the slot.
- **If the morning brief is missing**, say so in one line and publish the refreshed screen
  alone, with no "changed since" section. **Name WHICH kind of missing it is** — the three
  cases need different reactions, and the first is not "it failed":

  | Case | How to recognise it | What to publish |
  |---|---|---|
  | **Never ran** | `cron_read view=runs` has no run for the 08:30 fire, or the session's last message is a platform error (`CRON_EXECUTION_FAILED`, HTTP 500) | The refresh alone, with no "changed since" section. Name the cause. |
  | **Quota-killed and MAY STILL BE RESUMED** | The session's last message is `42212: Token Plan usage limit reached … (2056)` | The refresh alone — but say the upstream fire was **quota-killed and may be resumed in place**, so this file is PROVISIONAL, and say what a resumed upstream would change (it would supply the missing baseline). Do NOT write the upstream off as dead. |
  | **Genuinely dead** | A run exists, the session ended without a quota error and without a platform error, and no artifact appeared | The refresh alone, with the upstream named as dead. |

  The distinction matters because a resumed upstream is a REPLAY: on 2026-11-05 cron #26's
  08:30 fire was quota-killed, and it published the 11-05 brief 21.4 hours later — rebuilt
  for the 11-05 fire, and citing THIS refresh's screen. A refresh that wrote "the morning
  brief failed" was wrong by the next morning; one that wrote "the 08:30 fire was
  quota-killed and may still be resumed" was right.
- **A thin tape is a valid result.** If the screen returns fewer names than expected, publish
  what it has and say so.
- **A LATE PULL — the platform stalled and the pull landed after the 09:30 open.** This has
  happened (2026-11-05: a 49-minute stall put the pull at 10:10 ET with the market open). The
  columns then mean something different, and the file has to say so:
  - the `premarket_*` columns are the **completed** pre-market session — the final prints before
    the bell, which is later than intended but not less complete;
  - the regular-session columns (`close`, `change`, `volume`) are **live**, and are published in
    their own clearly labelled block, never mixed into a pre-market table and never presented as
    "yesterday's tape";
  - the front matter carries `pull_late: true` and `market_open_at_pull: true`, and the intro
    states the stall, the pull time and the open time;
  - **Rule 1 cannot be applied** (the open has happened); publish the pre-market prints and the
    live session separately.
- **When the upstream brief lands AFTER this file — AMEND, do not rewrite.** The 08:30 fire can
  be quota-killed and then resumed in place, hours later (2026-11-05: it was resumed and the
  brief published the next morning at 05:52 ET). This file is then the **baseline** the brief
  was rebuilt against, and it must say so. **Add a dated amendment block at the TOP of the
  file**, under the title, in this form — never rewrite the original numbers:

  ```
  > **UPDATE — <YYYY-MM-DD HH:MM ET>: the baseline resolved.** Cron #26's 08:30 ET fire was
  > <quota-killed / stalled>, not dead: the platform resumed that conversation IN PLACE on
  > <date> and the morning brief was published at <time> (<commit>), rebuilt for the <date>
  > fire and citing THIS artifact as its screen source. The note below describes the state as
  > it stood at this file's pull (<pull time>).
  ```

  The same convention applies to any later correction: the original numbers stay, and the
  correction is dated and attributed.

---

## Output and push

Write to `/workspace/daily-briefs/{date}-pre-market-refresh.md`, then push with the shared
helper, staging only `daily-briefs/`:

```bash
sh /workspace/push_artifact.sh --out daily-briefs --add daily-briefs/{date}-pre-market-refresh.md --branch main --nn 26b
sh /workspace/verify_delivery.sh --path daily-briefs/{date}-pre-market-refresh.md --branch main --nn 26b
```

`--nn 26b` is MANDATORY on the push. The push script derives the commit subject's routine
number from a path table, and that table did not have a row for `*-pre-market-refresh.md`, so
the subject came out as `cron daily-briefs <date>` with no number — and cron #90's triage
greps subjects for `cron (#)?26b `, so it reported a delivered artifact as MISSING. Passing
`--nn` puts the number in the subject regardless of what the table knows.

`verify_delivery.sh` is a SEPARATE helper: it is not shipped inside `push_artifact.sh` and
`push_artifact.sh` does not fetch it. If the prompt's fetch block only downloads
`push_artifact.sh`, the verification step is a silent no-op. Fetch both.

`--add` is passed ONCE. The script stages the routine's whole output tree, so the morning brief
and its CSV are not re-staged (they are already on the branch), and a second `--add` would
overwrite the first and wipe the routine number out of the commit subject.

## Reply

Under 12 lines: the snapshot time; the one setup and its invalidation; how many names cleared
how many headline names carry an anchored catalyst; how many names moved since the morning
brief; the
three biggest changes; the name to watch at the open and the level; one line for push status;
one line for `errors: <n>`.

**The push line carries the DELIVERY LATENCY, and a platform stall counts in `errors:`.** The
platform's run record measures the DISPATCH of the prompt to the agent (~1 s), not the work: on
2026-11-05 this routine's own run record closed in 1.008 s with `status: 1` and its first tool
call did not execute until 49.8 minutes later. `window_check.sh` prints `stall_min:` — the
platform's delay before the turn actually started — and the window check is this routine's first
action, so read it.

- `push: ok (verified) — delivered 10:15 ET, 55 min after the 09:20 fire` — the latency is the
  wall clock at the push minus this routine's own scheduled fire time (09:20 ET).
- `stall_min` over 5 ⇒ the fire was BLOCKED. Count ONE error for it, name it, and add a
  `stalled:` line. To name the cause, read your OWN session's previous turn
  (`session_messages` on your own session id) and quote the error it ended on — e.g.
  `42212: Token Plan usage limit reached … (2056)` — or say
  `stalled: the fire was blocked <n> min before its first tool call (no error recorded)`.
  `errors: 0` on a stalled fire is a lie: the artifact may be perfect and the schedule was not.
