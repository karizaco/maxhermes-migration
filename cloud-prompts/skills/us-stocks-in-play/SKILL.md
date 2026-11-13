---
name: US stocks in play
description: >-
  Weekday US (NYSE/NASDAQ/AMEX + liquid OTC + major ETFs) in-play scanner:
  open (~09:50 ET) and pre-close (~15:50 ET) digests, plus a midday (~12:30)
  slot. Uses TradingView-advanced + Yahoo Finance MCPs, falls back to
  Finviz/Barchart browser only on block. Tier A → Soft-A → TECH_WATCH → B → C,
  USD session $ volume sort. Quiet chat unless actionable. Cron weekdays
  09:50 and 15:50 ET.
---

# US stocks in play

Scan US equities that are actionable right now (gaps, unusual volume, breakouts, material news, halts) — weekday **open (~09:50)** and **pre-close (~15:50)** America/New_York digests, with a midday (~12:30) slot defined but not deployed. Uses the shared `stocks-in-play-pipeline` skill for normalize→merge, Soft-A, TECH_WATCH, holiday skip, source-health table, and chat rules.

**Finviz Elite is optional.** Free Finviz (~1 minute delayed) is enough for digests. Barchart is never required paid.

## Shared pipeline

Always run `stocks-in-play-pipeline` **after** gathering sources and **before** writing the dated digest. That pipeline covers Soft-A tiering, holiday skip, source health table, overnight carry, fetch→browser fallback, and stricter chat rules.

## Prior-digest continuity and research scoping (required)

This routine fires twice a day into a repo that already holds the previous digest. **Read it
before researching anything.**

1. **Read the prior digest for YOUR OWN SLOT**, not merely the newest file in the directory. The
   two slots have different floors and different session fractions, so a pre-close board and an
   open board are **not comparable**:

| Slot | Prior digest to read | Path |
|---|---|---|
| `preclose` (15:50) | the previous day's `preclose` board | `us-stocks-in-play/<date>.md` |
| `open` (09:50) | the previous day's `open` board | `us-stocks-in-play/<date>-open.md` |

   From a shallow clone, `git show origin/main:us-stocks-in-play/<file>` is enough.

   **The `open` slot reads two files**: its own prior board for the delta (point 2), AND the
   previous day's `preclose` board for the **Overnight → open** annex (below). Reading the
   preclose board for the *delta* would compare a 20-minute-in screen against a full-session
   screen and the turnover delta would be pure noise.
2. **Build a `changed_since` list**: names new to the screen, plus names whose move changed by
   ≥ 3pp since the prior pull, plus any name whose tier moved.
3. **Scope catalyst research to that list.** Do **not** re-verify a catalyst the prior digest
   already documented with figures — cite it and move on. Re-verifying Intel or Reddit when
   yesterday's digest already carries the guidance and the consensus numbers is the single
   largest waste of a slot, and it crowds out the names that actually changed.
4. **Publish the delta.** The digest must carry a "what changed since the <prior slot> digest"
   section: the `changed_since` list with the move at each pull, and the names that were new.
   This section is usually more useful to a reader than the full board. It is a **table**
   (ticker, tier, yesterday, today, the change, and why) — see the artifact contract below —
   and it must **name the file it was read from**. Naming the file is the proof the right
   board was read: the newest file in the directory is usually the *other* slot's board.

5. **The `open` slot also carries an Overnight → open annex.** Load the previous day's
   `preclose` board's `overnight_carry` — the watch list it named *before* that evening's prints
   — and report which of those names are in play **this morning**, with this morning's own tape
   and verdict. **Do not re-tell last night's earnings reactions**: the fleet's post-market brief
   (#23, 22:30 ET) owns those. The open board's job is to hand the watch list forward into the
   live tape, not to duplicate the brief. Name the pre-close board file this annex was read from.

## TradingView-advanced MCP rate-limit

When calling `mcp__tradingview-advanced__run_screener` / `get_symbol_data` / `get_news` / `get_symbol_data_batch`, follow pipeline §2b:

1. **One** US `run_screener` for core movers, OR HTML movers seed with **no** screener at all.
2. On HTTP 429 or empty screener: **STOP** further screener retries.
3. Quotes: **one** `get_symbol_data_batch` (≤50, `NASDAQ:`/`NYSE:`/`AMEX:` prefixed) on the merged candidate set → serial `get_symbol_data` only for batch `missing` (cap ≤10); prefer Yahoo/local confirm.
4. `get_news` only for top floor-cleared candidates (cap ~5–8); local catalysts first.
5. Soft target ≤12–15 TV MCP calls per slot. Log 429 once in Source health.

## Universe

**Include:**
- Common stock on NYSE, NASDAQ, AMEX / NYSE American
- OTC / pink sheets only when they clear a hard $ volume gate (e.g. FNMA, liquid cannabis)
- Major ETFs (SPY, QQQ, IWM, DIA, sector SPDRs, GLD, TLT, similar broad/sector/commodity/bond ETFs)

**Exclude:**
- Leveraged / inverse / single-stock leveraged ETFs (2x/3x, Ultra, Direxion, ProShares single-name levered)
- Warrants, rights, units (suffix / name heuristics: `W`, `WS`, `.W`, `U`)
- Preferreds
- Blank-check SPACs (pre-deal); post-deal operating cos OK if liquid
- Illiquid OTC that fails the $ volume gate

**Dedupe:**
- Dual-class: one line (more liquid class)
- Canadian interlisted: US line only
- ADRs: include if liquid; tag as ADR

## Noise filters

- Prefer session USD volume for ranking (not share count alone).
- Strip warrants/units from halt feeds.
- Low float (<10–20M): flag, don't auto-promote.
- Reverse-split artifacts: down-rank ~5–10 sessions.
- Dilution / ATM / registered direct: tag and down-rank long-bias chase.
- Premarket % with token volume: ignore until PM $ vol clears.

## Definition

A name is **in play** when there is a fresh, tradeable reason to look **now**: price/volume dislocation and/or material catalyst — not hype alone.

### Liquidity floor (required)

| Filter | Open ~09:50 ET (deployed) | Pre-close ~15:50 ET (deployed) | Midday ~12:30 ET |
|---|---|---|---|
| Price | ≥ $1 | ≥ $1 | ≥ $1 |
| Market cap | ≥ $50m soft | ≥ $50m soft | same |
| Session $ volume | **≥ ~$0.5–1m (to 09:50)** | ≥ ~$2–5m (full session) | ≥ ~$2–5m (full session) |
| OTC / pink | Session $ vol ≥ ~$0.5–1m | ≥ ~$1–2m | same spirit |
| RVol / pace | **pace ≥ ~1.5×** (see below) | Soft preference ≥ ~1.5–2× if available | same |

`preclose` and `midday` share the same dollar-volume bar because both read a **full session's**
turnover. The `open` slot bar is lower (~$0.5–1m) because it runs only 20 minutes into the
session, so a full-session turnover floor would empty the board. **That number must never be
applied at pre-close**, where it admits every micro-float that printed a few million dollars on
a quiet tape.

### Slot resolution (required)

The **fire time determines the slot** — not the slot a previous run used, and not the slot the
last fire used. Map the fire time to the nearest defined slot and apply that slot's floors and
triggers.

| Fire time (ET) | Slot | Session $ volume floor |
|---|---|---|
| ~09:50 (deployed) | `open` | ≥ ~$0.5–1m (partial session) |
| ~12:30 | `midday` (not deployed) | ≥ ~$2–5m (full session) |
| ~15:50 (deployed) | `preclose` | ≥ ~$2–5m (full session) |

This routine fires **twice a day from one task** (`50 9,15 * * 1-5` America/New_York). **Resolve
the slot from the FIRE INSTANT, never from the wall clock** — the platform resumes a crashed
conversation in place, hours or days later, so on a replay "now" names the resume day, not the
fire day. Take the fire instant from `session_get` → `session.created_at` (epoch ms), convert it
to US/Eastern, and read the slot off the hour: **09 → `open`, 15 → `preclose`**.

**Pre-close timing caveat:** the `preclose` slot fires ~10 minutes **before** the 16:00 ET bell,
so the regular-session close is **not final at fire time**. Take the settled close from the
post-bell print — the cloud RUNTIME-CONTRACT documents the source whose `primaryData` field flips
to the after-hours print at 16:00 — and state in the artifact whether the numbers are live
intraday or settled.

### The `open` slot (09:50 ET) — pace instead of RVol (required)

**The preclose slot's RVol cannot be used at 09:50.** Session volume at 09:50 is a fraction of a
full session, so dividing it by the trailing-10 *full-session* average gives every name ~0.1x, and
a Tier-A gate of "RVol ≥ 2.0" could never be met — the open board would be structurally empty.

The fix is to normalise by the **elapsed-session share**: the share of a normal session's volume
that has printed by 09:50.

**MEASURED (2026-11-05, Yahoo 5-minute bars, 49 symbols × the last 10 completed sessions,
480 symbol-sessions; the 5-minute series was reconciled against the daily bar for every
symbol-session):**

| Measure | Value |
|---|---|
| Opening share — **median** | **12.56%** |
| Opening share — mean | 12.97% |
| Opening share — p10 / p90 | 4.93% / 21.60% |
| Opening share — **median of the 10 daily medians** | 11.91% |
| Spread of the 10 daily medians | **10.77% – 16.49%** |
| 5-min series total ÷ daily-bar volume | 0.856 |

**The published constant is `0.125` (12.5%).** Compute the open slot's pace measure as:

```
pace = (session volume to 09:50 ÷ trailing-10 FULL-session average volume) ÷ 0.125
```

- pace **1.0** = this name has done exactly a normal pace of its volume by 09:50.
- pace **2.0** = twice the normal pace — 25% of a normal day in the first 20 minutes.
- **Tier A (open slot) = pace ≥ 1.5**; **Soft-A = pace < 1.5**. The bar is **1.5×, not 2.0×**,
  because the measure carries regime noise (below) that the full-session RVol does not.

**The numerator is the 5-minute volume through the 09:50 bar — NOT the scanner's running
volume.** The scanner's `volume` field is the running session total AT THE MOMENT THE SCANNER
IS PULLED; if the pull happens at 10:04 it already carries the 09:50 → 10:04 volume, so a
"volume to 09:50" built from it is wrong by exactly that increment, and the error lands on
the largest movers. Rebuild it from the 5-minute bars instead: a bar's timestamp is the
START of its 5-minute interval, so **the price at 09:50 is the close of the bar stamped
09:45** and **the session volume to 09:50 is the sum of the bars stamped 09:30, 09:35,
09:40 and 09:45**.

**The volume-basis factor comes from `polygon-io grouped_daily` — there is NO second price
pull.** The Yahoo 5-minute series is a fraction of the true session volume, so the 09:50
numerator has to be put on the daily-bar basis before it can be divided by the trailing-10
average. **That fraction is NOT a constant**: it measured **0.856** on 2026-11-05 (480
symbol-sessions) and **0.9168** on 2026-11-09 (1,163 symbols), and it moves by symbol and
by session — which is why the factor is measured **per symbol on the prior session**
instead of taken from a table. Measured 2026-11-10: the Yahoo daily bar and the polygon
daily bar are the **same series** (per-session volume ratio median **1.0002**, p10 1.0000,
p90 1.0053 over 1,162 names), so the factor can be built from the polygon call the run
**already makes**:

```
vol_basis_factor    = yahoo_5m_total(prior session) ÷ polygon_daily_volume(prior session)
session_vol_to_0950 = yahoo_5m_volume_through_09:50 ÷ vol_basis_factor      # daily basis
pace                = session_vol_to_0950 ÷ avg_vol_10d ÷ 0.125
```

`_shared/rvol_fetch.py` returns the prior session's own daily volume in its
`prior_session` block (`"capability": "RVOL_FETCH_V2"`) — that data is already in the
helper's hands, so **no extra Yahoo request is needed**. Fetch the 5-minute series with
**`range=10d`, not `1d`**, so the prior session's 5-minute total is in the same response:
the payload grows from ~5KB to ~38KB per symbol, but the per-request time is flat
(0.11s → 0.14s measured) and the throughput ceiling is unchanged.

**A symbol whose prior session falls outside the 10-day window uses the GLOBAL MEDIAN
factor** — and the artifact says so, because the factor is the only thing holding the
numerator and the denominator on one basis.

**The 5-minute VOLUME field is corrupt on a minority of names — repair it before the pace
is computed (measured 2026-11-12).** The factor above is measured on the PRIOR session, so
it cannot repair a corrupt bar in the CURRENT session. On 2026-11-12 Nvidia's 09:30 bar
carried **167,140,999** shares and its 09:40 bar **260,594,722**, against a daily-bar
session volume of 310,068,313; unrepaired that published a **pace of 23.29** and a
**$107.9bn** turnover to 09:50 on the largest name on the board, where the repaired
figures are a **pace of 2.89** and **$13.4bn**. The error lands on the largest movers.

1. **Cap every 5-minute bar at 8x the symbol's own median RTH 5-minute bar volume** across
   the 10-day window. A 5-minute bar cannot plausibly carry 8x the symbol's typical
   5-minute volume. (The 09:30 bar is legitimately larger — it carries the opening auction
   and some pre-market flow — so the test must be a multiple of the symbol's own median,
   not an absolute number.)
2. **Cross-check every survivor against Yahoo's own `interval=1d` bar** — one request per
   name, 527 survivors in 35 seconds. The daily bar is the physical bound: the volume to
   09:50 cannot exceed the session volume at pull time. If the 5-minute sum still exceeds
   it, rescale the session's bars and flag the name.
3. **Take the prior close from the daily bar**, not from the 5-minute reconstruction — on
   2026-11-12 that corrected 21 of the 527 survivors by more than 0.5%.
4. **Flag the repaired names in the candidates CSV** (`volume_prints_repaired`,
   `volume_rescaled`) and name the defect in `## Source health`.

**Do NOT use the TradingView scanner's live `volume` column as the session-volume bound.**
It is stale against the consolidated tape — on 2026-11-12 it read 183.5m for NVDA at
10:03 ET while the daily bar read 310.1m at 10:35 ET — and it flags 3,153 of 4,572 names
as impossible. The daily bar is the arbiter.

The full evidence, and the measurement that the shared helper's 09:30 reconstruction agrees
with the board's gap column to a median of 0.02pp, is in
`docs/IMPROVEMENTS-cron17-us-stocks-in-play.md` (2026-11-12).

**Publish these caveats with the pace numbers, every time:**
- The opening share is **not stable** — its daily median moved between **10.77% and 16.49%** over
  the ten measured sessions. A pace reading of 2.0 is therefore roughly 1.8–2.3 on a different
  session's regime. **The pace is a screening measure, not a measurement.**
- **`pace` and the preclose slot's `RVol` are different quantities on different denominators.
  They are NOT comparable, and a pace number must never be compared against an RVol number.**
  Label the open-slot column `pace` (never `RVol`) in the artifact and in the CSV.
- The 10.77%–16.49% spread is the tolerance band. A pace between 1.5 and 2.0 on a high-share
  session is a name whose pace is really ~1.2; treat it as Soft-A, not Tier A.

**Everything else about the open slot is the same procedure** — the same trigger screen, the same
tiers, the same gap annex, the same catalyst rules, the same buyout rule. Only the floors and the
volume measure change.

**The gap verdict at 09:50 covers only the first ~20 minutes.** The shared helper rebuilds the
path from 5-minute bars, so at 09:50 the later path points (10:00, 12:00, 15:50) are simply not
there yet and the verdict is computed over a 20-minute window. `held` at the open slot means
**"the gap held for 20 minutes"**, NOT "held into the bell" — say so in the artifact, and never
reuse the preclose phrasing ("held into the bell") in an open-slot artifact.

### The 09:50 pull engine (run-time fetched — required)

The open slot's universe, the 5-minute pull, the 09:50 reconstruction, the floors and the publish
gate are **one engine**: `tools/open_0950_pull.py`. Fetch it at RUN time — the fixes land on the
next fire with no `cron_update` and no prompt drift.

```bash
mkdir -p /workspace/tools
E=/workspace/tools/open_0950_pull.py
for U in \
  "https://api.github.com/repos/karizaco/maxhermes-migration/contents/tools/open_0950_pull.py?ref=main" \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/tools/open_0950_pull.py" \
  "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/tools/open_0950_pull.py" ; do
  curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" \
    -H "Authorization: Bearer ${GITHUB_TOKEN}" -o "$E.tmp" "$U" 2>/dev/null
  if [ -s "$E.tmp" ] && grep -q 'OPEN_0950_PULL_V1' "$E.tmp" 2>/dev/null; then
    mv -f "$E.tmp" "$E"; break
  fi
  rm -f "$E.tmp"
done
[ -s "$E" ] || { echo "open_0950_pull.py: UNAVAILABLE — do NOT hand-roll the pull; say so and stop"; exit 1; }
```

```bash
# the whole open-slot data spine, in one call
python3 "$E" run --date <YYYY-MM-DD> --prior <YYYY-MM-DD> \
  --out /workspace/open_0950 --avg10 /workspace/avg10.json \
  --index-live "SPY=<live move>,QQQ=<live move>"
```

`<live move>` is the **live** index move the MCP bridge returns (`market-recap get_quotes`) —
the gate compares the reconstructed 09:50 move against it. Run the engine **before** the catalog
work: it is the long pole and it is resumable.

**What the engine owns, and why each rule exists** (every one was a measured, SILENT defect):

| Rule | The defect it removes |
|---|---|
| the prior close is the **prior session's last non-null bar close**; `chartPreviousClose` is used only for `range=1d` | in a multi-day range that field is the close *before the window* ⇒ every move became a TEN-DAY move (2026-11-10: NVDA −21.50% instead of −4.10%, QQQ −6.55% instead of −0.26%) |
| the price is the **last non-null close** at or before the cut, and a null-close bar's **volume still counts** | 1,276 of 7,857 names were silently dropped; a null bar's volume was under-counted |
| **no cookie** on chart calls, and `Edge: Too Many Requests` / 429 is a **THROTTLE** (pause, back off, resume) | the cookie'd session is throttled by the egress edge; the `Edge:` prefix used to defeat the error check, so the pull kept hammering a throttled endpoint |
| one **JSONL line per symbol** as it lands | a kill used to destroy ~3,945 completed fetches; now a retry resumes |
| the **venue prefix is stripped** and `/` maps to `-` | `NASDAQ:NVDA` 404s on Yahoo |
| **one keep-alive connection per worker** | one process per symbol ran at 12.4 req/s; the same requests run at 62–101 req/s (measured 2026-11-13) |

**The PUBLISHED prior close is the OFFICIAL daily close, and the engine re-bases it.** The 5-minute
series' last bar close is only an APPROXIMATION of the session close — the closing auction print
does not always land in the bar series. Measured 2026-11-13 on the 2026-11-12 session: **26 of 646
published names** had a 5-minute-derived prior close more than 0.5% away from Yahoo's own daily
close (up to **1.4%** on a $1.39 name). The gap and the move are measured against the official
close, so the engine re-bases every published name on it, **re-applies the trigger and the floors
afterwards**, and publishes **how many names were re-based and how many left the set as a
result** (measured on the 2026-11-12 session: 524 re-based, 11 dropped). The same defect is
present in the published 2026-11-10 board (26 of 531 names) — it moves no Tier A/Soft-A name,
but it is a real reference-price error and the artifact says so.

**The PUBLISH GATE is not optional.** The engine exits non-zero when it fails; **a failed gate
means NO open artifact is published** — say so and stop, do not publish a board on a broken
reconstruction. The gate asserts:

- **G1 index** — the reconstructed 09:50 move for SPY/QQQ is within **0.75pp** of the live index
  move (the 09:50→quote drift is ~0.1–0.2pp; the ten-day-basis defect was 6.3pp on QQQ);
- **G2 prior close (exact)** — every **published** name's reconstructed prior close equals Yahoo's
  **own daily close** for the prior session within **0.5%** (measured 39 of 39 live names: SPY
  759.79 vs 759.81);
- **G3 completeness** — every published name carries a price, a prior close, a pace and a verdict,
  and the published count equals the floor-cleared count. **A truncated pull is a FAILURE, never a
  shorter board**;
- **G4 basis sanity** — the median |reconstructed move − the scanner's change| over the published
  set is under **12pp** (the correct basis reads 3.16pp; the scanner's own `change` column LAGS,
  so this band is deliberately loose).

The engine writes `universe.json`, `records.jsonl`, `published.txt` and `summary.json` into
`--out`. **The candidates CSV is built from `published.txt`** — those are the names that cleared
the open slot's floors and the 09:50 trigger, priced and tiered, with no unpriced tail.

**Both pace bases are published, and only one is the contract's.** `pace` stays the published
column (the current basis). `pace_live_basis` is published alongside it for the settled-session
comparison below.

#### The pace-basis validation (2026-11-13) — the OPEN slot publishes, the PRE-close slot arbitrates

The published basis divides a **live** numerator by a factor measured on the **archived**
prior session's 5-minute series, which sums to only ~79–99% of its own official daily volume.
On the published 2026-11-10 board that inflated the pace by **~12%** (factor median 0.8918):
no Tier A or Soft-A name changed tier, but ~30 names moved between TECH_WATCH and Tier B.

The engine computes the alternative basis on the **live** feed —
`vol_to_0950_official = daily_volume_live_today × (vol_to_0950 ÷ y5m_total_to_pull)` — and
publishes it as `pace_live_basis`. **The basis does not change on the open slot.** The
**pre-close** slot of the SAME session is the arbiter: its settled session volume is the ground
truth, so the pre-close board publishes, for the open board's top-30 names, the open board's
`pace`, the open board's `pace_live_basis`, and the settled RVol — side by side. **The published
pace column stays as it is until that comparison has been made.**

### Pre-close two-phase procedure (required)

The `preclose` slot straddles the bell, so run it in two phases and publish **one** digest:

- **Phase 1 (~15:52, live intraday):** discovery, the universe and the floors, the intraday path
  (open → high → low → where it trades now), the gap annex, and catalyst research. Record the
  live price and its timestamp.
- **Phase 2 (after the 16:00 bell, ~16:02):** re-price the tiered names for the **settled**
  regular-session close and the settled session volume, recompute RVol on the settled volume, and
  take the close from the source's post-bell, field-flip-safe field. Re-check any name whose tier
  moved on the settled numbers.

The artifact must state that the numbers are **settled**, and the gap annex must separate a gap
that **held into the bell** from one that faded. Never publish an intraday price labelled as a
close. Do not wait for the after-close earnings slate — the fleet's post-market brief owns that;
the carry hands off to it.

#### The pre-close slot ARBITRATES the open slot's pace basis (required, from 2026-11-13)

The open slot publishes **two** pace bases for every name: `pace` (the published column, on the
archived-prior-session factor) and `pace_live_basis` (on the live feed). **The pre-close slot of
the SAME session is the arbiter**, because its settled session volume is the ground truth.

**Required in the pre-close artifact**, for the open board's top-30 names by turnover: the open
board's `pace`, the open board's `pace_live_basis`, and the settled RVol, **side by side in one
table**. Read it against the opening-share band (10.77%–16.49%): if the settled RVol agrees with
`pace_live_basis` and misses `pace` by roughly the measured bias, the live basis is the right one
— and the basis change is then landed as its OWN commit, with the comparison published. **Do not
change the published pace column in the same commit that publishes the comparison.**

#### The settled close has TWO sources, and they disagree — pick one and cross-check (measured 2026-11-10)

The settled close is available from **two** post-bell sources, and on a small set of names they
**disagree by more than 0.6%**:

| Source | Field | Note |
|---|---|---|
| **Nasdaq official quote API** `/quote/<sym>/info` | after 16:00 ET, **`secondaryData.lastSalePrice`** | its `primaryData` has already flipped to the after-hours print — that is the documented field flip. Sweep it in parallel over the whole screened set |
| **Bridge `market-recap get_quotes`** | `price` + `previous_close` + `volume` | `market_state: "post"`, `as_of` ≈ 21:00Z. **The bridge caps a call at 40 symbols** — a 100-symbol request silently returns only 40, so batch at 40 (24 calls priced 943 names on 2026-11-10) |

Measured 2026-11-10 over 943 names: **13 names disagreed by >0.6%** (BWET, CTEV, HYLN, SSK,
GDMN, AZUL, NEHI, MTA, GCTS, NEWP, XTND, COOK, SJT). **Yahoo's own daily bar corroborated the
bridge on all 13** and contradicted Nasdaq's `secondaryData` — so the **bridge is the one to
publish**, and the disagreement must be **disclosed in Source health**, never silently resolved.
**Recompute the change % from the SAME source's close and previous_close**, or a row mixes a
close from one source with a percentage from another.

**The cheap tiebreak is one Yahoo `interval=1d` call per disputed symbol** — pull it only for the
names that disagree, never for the whole universe. A **class-share ticker** (`BH.A`, `LEN.B`) is
not carried by the bridge at all; its price comes from the Nasdaq API and its RVol from the
scanner volume.

### Gap provenance — the missing mechanism (required)

The gap rules above **mandate a computation that nothing else in the fleet performs**: whether a
gap held into the bell or faded, and what the catalyst was *at the open*. Compute it with the
shared helper, which rebuilds the intraday path from 5-minute bars and joins an optional
catalyst feed:

```bash
python3 /workspace/preopen_feed.py merge --date <YYYY-MM-DD> --symbols <A,B,C>
```

| verdict | meaning | treatment |
|---|---|---|
| `reverse` | the opening move flipped sign | strongest in-play signal; the gap and the tape disagree |
| `faded` | the opening move was substantially given back | in play, but the open buyer is gone |
| `held` | the move is largely intact | a trend, not a squeeze-and-fade |
| `no_move` | the open was inside the noise band | no gap to read; judge on the catalyst alone |

- The **catalyst feed is optional**. Without it the path and the verdict still stand — the verdict
  comes from 5-minute bars, not from the feed.
- Feed **prices are never trusted**: >2pp disagreement with the bars or the scanner ⇒ `unverified`.
- The helper's **premarket columns are LIVE ONLY** and come back blank for a past date. The
  09:30 / 10:00 / 12:00 path from 5-minute bars is historical and always valid.
- Tag affected names in the artifact and in chat: `GAP_FADED`, `REVERSED`.
- Self-test: `python3 /workspace/preopen_feed.py selftest` runs four known sessions and must
  print 4 PASS.

#### The pre-close verdict must be computed AT THE BELL, not at 15:50 (measured 2026-11-10)

**The helper's `now` column prefers the 15:50 bar** (it falls back to 16:00 only when 15:50 is
absent). At the `preclose` slot the question is whether a gap **held into the bell**, so the
published verdicts are recomputed at the **16:00 regular-session close** from the same Yahoo
5-minute series: pull `interval=5m` for the session date, take the **last bar at or before
16:00** as the bell, and keep the open / 10:00 / 12:00 / 15:50 points for the path. The helper
still supplies the path and the verdict bands — it just does not supply the bell.

This is not a cosmetic difference. On 2026-11-10 it changed two published verdicts:

- **GEV** — the 15:50 read said `held` (the gap had recovered from -8.90% to -4.59% by 15:50),
  but it finished only **-3.89%**, so it gave the open move back: **`faded`**.
- **PAYS** — the 15:50 read said `held`, but the gap **flipped sign** from **+4.72%** at the open
  to **-18.94%** at the bell: **`reverse`**.

A 15:50 verdict would have published both wrong, and the pre-close board's whole claim — that a
gap which **held into the bell** is the signal — rests on the bell.

The reconstruction's **open** agrees with the TradingView scanner's native `gap` column to a
**median 0.003pp, p90 0.43pp** across 911 names, so the scanner's gap may be published directly.

### Triggers (≥1 after the floor)

| Trigger | Guidance |
|---|---|
| Gap | ≥ ~3–5% vs prior close; prefer PM $ vol ≥ ~$200k when PM data exists. At pre-close, a gap that **held into the bell** is the signal; a gap that faded is not |
| Day move | |chg%| ≥ 5% large/liquid; ≥ 8% smaller (soft 3–5% with strong tape OK) |
| Unusual volume | When RVol is available and meaningful — bonus, not a must |
| Breakout / breakdown | Day high/low vs prior range with volume |
| Catalyst | Material 8-K / PR / major news (see include/exclude) |
| Halt / resume | LULD or news halt — candidate on resume if liquid |
| Buyout / deal | Special rule below — not automatic in-play |

### Catalyst include

Earnings / guidance surprises; M&A / strategic review (non-arb); material contracts; FDA/regulatory when confirmed; officer/governance shocks; halt news; price-sensitive 8-K items (1.01, 2.01, 5.02, 7.01, 8.01).

### Catalyst exclude / down-rank

Routine admin; empty IR calendar; chat/Stocktwits as sole source; near-offer buyout arb; pure ATM/offering dumps without a tradeable bounce thesis.

### Buyout / near-offer rule

| Situation | Treatment |
|---|---|
| Trading near stated cash deal / tight collar | Exclude / down-rank — sideways arb, not chase |
| Fresh deal with wide gap to terms | Tier C gap/halt watch only — not Tier A / Soft-A / B momentum |
| Contested / raised bid with real non-arb tape | C, or B only if independent liquidity + move |

Never promote solely because a buyout was announced.

## Artifact contract (required, both slots)

The digest is the deliverable. A board that is mechanically correct and reader-hostile is
still a failed run, so the acceptance criteria below are **machine-checked** — run the
checker before you push, and fix the artifact if it fails.

#### The contract marker

Both boards carry a marker line near the top:

```
- **Contract:** `in-play-artifact-v1` · slot `open` · fire 2026-11-06 09:50 ET
```

The marker tells the checker (and the next run) which contract the artifact was built
against. A missing or stale marker means an older copy of this spec produced it — re-read
the skill and rebuild.

#### Section order

The two boards are read every session, so the shape must be predictable. Sections are
matched by their normalized heading, so the exact wording is yours.

**Open slot (`{date}-open.md`):**

`The headline` → `What changed since the … open digest` → `Market context` →
`Overnight → open` → **`What to watch at the open`** → `Tier A` → `Soft-A` →
`Gap annex` → `TECH_WATCH` → `Tier B` → `Tier C` → `Source health` →
`Method and caveats` → `Files`

**Pre-close slot (`{date}.md`):**

`The headline` → `What changed since the … pre-close digest` → `Market context` →
`Tier A` → `Soft-A` → `Gap annex` → `TECH_WATCH` → `Tier B` → `Tier C` →
`Overnight → pre-close` → `Overnight carry` → `Source health` →
`Method and caveats` → `Files`

Two rules make the order matter:

- **The tradeable tiers come first, and the gap annex is the centrepiece.** The gap
  annex is the part that says *which gaps held*; burying it under a 610-name TECH_WATCH
  table hides the board's actual finding. Tier A → Soft-A → gap annex → TECH_WATCH →
  Tier B → Tier C.
  **The order is enforced by the checker.** The 2026-11-05 open board placed its gap annex
  *after* Tier C and would have failed the order check; the gap annex belongs **between
  Soft-A and TECH_WATCH**.
- **`TECH_WATCH` is capped at 30 published rows and `Tier B` at 25**, but the heading
  must still state the **full** tier count (`610 names; the top 30 by turnover are
  published`). The count is what makes the tradeable-vs-technical imbalance visible —
  a 610-vs-14 imbalance that only exists in a heading nobody reads is invisible.

#### The "what changed" section is a table

It must be a **table**, not prose, with these columns:

| Ticker | Tier | Yesterday | Today | Change | Why |
|---|---|---|---|---|---|

The **Tier** column says what moved *into* the tradeable set, and the **why** column is not
optional: a reader diffing two sessions needs to know *what caused* the move, not just that it
happened. The `Change` column may be headed `Change`, `Δ` or a date pair such as `11-04 → 11-05`.

**The open slot's delta is computed against the previous day's OPEN board, and the
overnight annex is sourced from the previous day's PRE-close board.** These are two
different files and the open slot reads both. Say which file you read for each, by name:

```
**Delta source:** `us-stocks-in-play/2026-11-05-open.md` (the previous day's OPEN board —
not the newest file in the directory, which is the pre-close board).
**Annex source:** `us-stocks-in-play/2026-11-05.md` (the previous day's PRE-close board).
```

The **pre-close** slot's delta compares a full session against a full session, so it names
the previous day's **pre-close** board (`us-stocks-in-play/2026-11-05.md`) — not an open
board. A slot that diffs against the other slot's board compares a 20-minute screen to a
full session and the numbers are meaningless.

On the **first** fire of the open slot there is no prior open board. Say so plainly
("no prior open board — this is the first link in the open-board chain") and publish no
delta table. Do not silently omit the section.

#### The open slot's payoff block

The pre-close board has an overnight carry; **the open board has the payoff**. Add a
`## What to watch at the open` section with **three names**, drawn from the overnight →
open annex, each with:

| Name | Prior close | Current price | Invalidation |
|---|---|---|---|
| **ABC** | $41.20 | $43.90 | below $41.20 |

The **invalidation level** is the point: a name without one is a story, not a trade. The
open board's job is to hand the watch list forward into the live tape, not to duplicate
cron #23's after-close reactions.

#### The pace measure publishes its own uncertainty

The `0.125` opening-share constant is **measured, not exact** — the ten daily medians span
**10.77% – 16.49%**. So a published pace of 1.9× is really 1.8×–2.3× depending on the
session's regime. **Publish the band with the pace numbers**, not only in the Method
section where a reader will not look:

> pace 1.9× — measured against the 0.125 constant; the daily median spans 10.77%–16.49%,
> so treat this as a screen, not a measurement.

**`pace` and the pre-close slot's `RVol` are never comparable.** They are different
quantities on different denominators. The open board labels its volume column `pace` and
never `RVol`; the pre-close board labels its column `RVol` and never `pace`. The CSV must
not carry the other slot's column.

#### Catalyst provenance: every published row carries two fields

| Field | Meaning |
|---|---|
| `has_catalyst_timestamp` | `yes` / `no` — did the catalyst carry a verified timestamp? |
| `reason_without_timestamp` | the catalyst REASON, present even when there is no timestamp |

**The missing tape costs the timestamp, not the reason.** The pre-open feed's catalyst
column is often unusable ("no catalyst captured at this checkpoint"), but the routine
researches catalysts itself via `web_search` against issuer IR and EDGAR filings — so a
row with `has_catalyst_timestamp = no` still owes the reader the reason. A blank reason
is a silent failure: it reads like "nothing happened" when in fact the reason exists and
was simply never timestamped.

**This applies to EVERY row of the candidates CSV, not only the published tier tables.**
The checker asserts it on all rows (measured 2026-11-10: **921 of 943 rows carried a blank
reason and failed the contract**, while the board itself read fine). The convention the
prior boards use for a name where a search was run and found nothing is the literal string
**`no same-session company catalyst located`** — set it as the **default** in the tiering
step, so a re-tier can never wipe the reasons that were researched.

**Generate the tier tables from the data, never hand-type them.** On 2026-11-10 the
hand-written tables drifted from the settled dataset on several rows (a stale close, a stale
RVol) while the CSV was correct — and the checker, which validates structure and not the
numbers, passed it. The board's tables must be **rendered from the same dataset the CSV is
written from**, so a number cannot be wrong in one file and right in the other.

#### No halt counts, ever

The TradingView scanner's `halted` column is **null on every row**, so the halt state is
**not measurable**. Publish that — "the halt state is not measurable this session" — and
never a number. The strings `halted: 0`, `0 halts` and `no halts` must appear nowhere in
the artifact or the reply.

#### Run the checker before you push

```bash
C=/workspace/tools/check_in_play_artifact.py
for U in \
  "https://api.github.com/repos/karizaco/maxhermes-migration/contents/tools/check_in_play_artifact.py?ref=main" \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/tools/check_in_play_artifact.py" \
  "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/tools/check_in_play_artifact.py" ; do
  curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" \
    -H "Authorization: Bearer ${GITHUB_TOKEN}" -o "$C.tmp" "$U" 2>/dev/null
  if [ -s "$C.tmp" ] && grep -q 'in-play-artifact-v1' "$C.tmp" 2>/dev/null; then
    mv -f "$C.tmp" "$C"; break
  fi
  rm -f "$C.tmp"
done
python3 "$C" --md /workspace/us-stocks-in-play/$ARTIFACT_NAME \
              --csv /workspace/us-stocks-in-play/$CSV_NAME \
              --slot "$SLOT"
```

`$ARTIFACT_NAME` and `$SLOT` come from the prompt's `## OUTPUT` block. The candidates CSV is
written next to the board with the slot suffix applied to the DATE, not to the filename:

| Slot | Board | Candidates CSV |
|---|---|---|
| `preclose` | `<date>.md` | `<date>-candidates.csv` |
| `open` | `<date>-open.md` | `<date>-open-candidates.csv` |

so `$CSV_NAME` is `<date>-candidates.csv` for the preclose slot and `<date>-open-candidates.csv`
for the open slot — the same suffix rule as the board. If the routine wrote a differently-named
CSV, point the checker at the file it actually wrote; the check is on the content, not the name.
**Push the CSV too.** `push_artifact.sh` stages the whole output tree, so the CSV reaches the
outputs repo with the board — but the delivery check names only the board, so verify the CSV's
presence on the remote branch yourself.

It asserts the section skeleton and its order, the contract marker, the pace band and the
pace scale (every pace row must reconcile with `(session_vol / avg_vol_10d) / 0.125`),
the slot's own measure label, the tier counts and caps, the delta table and the two
source files it names, the watch block's three names and their levels, the two
catalyst-provenance fields on every row, and the absence of any halt count. It exits 1
and prints each failure.

**If it fails, fix the artifact and run it again — do not report a clean run over a
failing check.** Do not eyeball these things; the 2026-11-05 open board looked fine and
failed six of them.

## Ranking and sort

1. Tier A → Soft-A → TECH_WATCH → B → C.
2. Within tier: USD session $ volume descending.
3. Cap ~8–10 names (+ short halt/gap annex). Tag ETF, OTC, ADR, DILUTION, BUYOUT_GAP, SOFT_A, halt reason when relevant.

## TECH_WATCH tier (technical Soft-B)

Between Soft-A and B. For liquid technical setups that fail a hard pure-technical RVol bar but clearly trade on size (continuation / episodic pivot, bottom bounce, HTF breakout, unusual strength without fresh catalyst).

**Eligibility (all required):**
- Liquidity floors for the slot
- Day-move or gap meets soft guidance
- Session turnover ≥ slot floor — prefer USD dollar volume
- Soft / missing RVol or roughly 1.0–2.0×
- No same-session catalyst required
- Tag `TECH_WATCH`

**Sort:** after Soft-A, before B, by session turnover descending.

**Chat:** include material TECH_WATCH on midday / manual when turnover clearly clears the midday-scale floor; at the deployed pre-close slot, only if turnover already clears the midday-scale floor (~$2–5m); **at the deployed `open` slot, only if turnover already clears the open-scale floor (~$0.5–1m)** — a name that has printed $1m in 20 minutes is a real signal, one that has printed $200k is not.

## Persistence

Save every run to:

`C:\Users\admin\.minimax\projects\coding-shared\research\us-in-play\YYYY-MM-DD-<slot>.md`

- `<slot>` = `open` (~09:50, deployed), `preclose` (~15:50, deployed), `midday` (~12:30, not
  deployed), or `manual`
- **The on-disk path is slot-qualified for `open` only**, and the `preclose` path is unchanged so
  the historical chain and the auditor's existing roster row keep working:

| Slot | Path in `us-stocks-in-play/` |
|---|---|
| `preclose` | `<date>.md` — **canonical, unchanged** |
| `open` | `<date>-open.md` |

  The two can never collide: the `open` fire writes `-open.md`, the `preclose` fire writes the
  bare path. **Never publish the `open` board to `<date>.md`** — that is the preclose board's
  path, and writing there destroys the previous day's preclose chain.
- Include: run time ET, session state, sort note, tier tables, PM gap annex, halt watch, source health table, sources
- When after-close / AH 8-K / PR material catalysts exist, require an `overnight_carry` section
- **The `preclose` carry is written before tonight's prints.** Name the watch list — the scheduled
  reporters that intersect with today's tape — and say plainly that the results land after the
  carry is written. Do not guess the results and do not list every reporter: the fleet's
  post-market brief owns the after-close earnings reactions, so the carry's job is to hand off,
  not to duplicate.
- Include the fuel-log line in `us-stocks-in-play/logs.jsonl` in the digest's file list
- On the pre-close slot: load prior digest's `overnight_carry` into the Overnight → pre-close annex
- **On the open slot: load the PREVIOUS DAY's `preclose` board's `overnight_carry` into the
  Overnight → open annex**, and report which of those names are in play this morning. Do not
  re-tell last night's reactions — the post-market brief owns those.
- **Chat only if** any Tier A or Soft-A, material TECH_WATCH, or material Tier C

## Source stack

For each source: try HTTP fetch / API first; **if fetch blocked → open that URL only in the headed desktop browser**, scrape what you need, continue.

### Pass 1 — Movers (RTH)

1. **Yahoo** predefined JSON: `day_gainers`, `day_losers`, `most_actives`, `small_cap_gainers` (primary discovery).
2. **Finviz screener** (when HTML table renders): top gainers / losers / unusual volume / most active.
3. **TradingView-advanced MCP** — optional corroboration, under pipeline §2b budget.
4. **MCP-over-HTTP bridge** (see the cloud RUNTIME-CONTRACT): `market-recap` pack `get_quotes` / `top_movers` / `market_snapshot`, plus `stocktwits` and `shibui`. Reachable over plain HTTPS JSON-RPC with no agent.minimax.io registration — preferred over raw Yahoo because it is not rate-limited and returns `as_of` + `market_state` with every quote.
5. **TradingView scanner API** `POST https://scanner.tradingview.com/america/scan` — movers, `relative_volume_10d_calc` (RVol), `market_cap_basic`, `halted`, and `premarket_change`/`premarket_volume`/`premarket_close` in one call.

### Pass 1 screening rule (required)

Discover on the **trigger**, not on the close-to-close move. A name that gapped +4% and closed
+3.5% on heavy volume is in play; a name that closed flat after gapping +9% and fading is not.

1. Screen the universe for `(|change| >= 3%) OR (|gap| >= 3%)`. Do **not** screen on
   `|change| >= 5%` alone — that silently drops every gap-and-fade and every gap-that-held.
2. Apply the slot's floors (price, market cap, session $ volume) to the survivors.
3. **Price every survivor.** Do not cap the screen at "the top N by dollar volume": a mid-cap
   with a real 8-K routinely sits below that cap, and a silent cap is an invisible hole in the
   digest. If a cap is genuinely unavoidable, state it in the artifact along with the
   **priced / unpriced counts** and which candidates the cap dropped.
4. Record in the artifact: universe size, survivors after the trigger, survivors after the
   floors, number priced, number tiered. **In the open slot, also record the universe size
   AFTER the pre-filter and state the pre-filter itself** — the trigger was evaluated on
   that subset, and the reader has to know it.
5. Compute RVol as session volume ÷ the **trailing 10 settled sessions from the same series**
   and state that denominator. A screener's own RVol column uses a different denominator and is
   not comparable across sources.

#### Pulling the TradingView universe: ONE unpaginated call (2026-11-06)

**`range` pagination returns DUPLICATE rows and MISSES others — never page a fast-moving
filter.** Measured 2026-11-06: a 9-page offset pull of the US cash universe
(`type` in (stock, dr), 13,203 rows requested at 1,500 per page) returned **13,500 rows
containing only 8,689 unique symbols** — 3,876 symbols appeared more than once, with
identical name, description, exchange and type. The same universe pulled in **one** call
with `range [0, 6093]` returned **6,093 rows / 6,093 unique** — clean.

The failure is silent: the response looks healthy (rows ≥ `totalCount`), so no row-count
check catches it, and the duplicated names are then counted twice in every tier count and
every dollar-volume ranking. The full evidence and reasoning is in
`docs/IMPROVEMENTS-cron17-us-stocks-in-play.md` §1.

**Rule:** pull the universe — and any filter on a fast-moving column (`change`, `gap`,
`premarket_change`) — in **ONE** scan call with `range [0, totalCount]`, and assert
`len(rows) == totalCount` **and** `len(unique(symbols)) == totalCount`. If either fails the
pull is corrupt: discard it and re-pull in one call. Paging is only safe on a static filter.

**The scanner has a native `gap` filter and column** — the gap leg of the trigger set
needs no local computation. `{"left": "gap", "operation": "greater", "right": 2}` is a valid
filter (measured 2026-11-06: `gap > 2` → 3,461 names). The `gap` column on a row is the
open-vs-prior-close gap, and it agrees with a 5-minute-bar reconstruction to a
**median 0.000pp** (p90 0.50pp) across 644 names — so it can be published directly.

#### The 09:50 universe pull is PRE-FILTERED — and the pre-filter is a UNION (2026-11-10)

**The 5-minute pull does not need every symbol in the universe.** On 2026-11-09 the open
slot pulled 5-minute bars for **10,696 symbols** and kept **767** of them; that pull was
**11m49s of a 25-minute run**. It is the single largest block in the routine, and the source
is **throughput-capped at ~17 requests per second** — measured 2026-11-10 with 260 symbols
per round: **12 workers → 17.1 req/s, 24 → 16.7, 48 → 16.7, zero failures.** Raising the
worker count buys **nothing**, so the only way to make the pull faster is to make **fewer
requests**.

So the universe is cut before the pull, by a **union** of tests, all computed from the ONE
unpaginated scanner call above:

| Leg | Test | What it catches |
|---|---|---|
| **turnover** | `close × volume ≥ $100k` | the names whose 09:50 turnover could clear the slot's $500k floor — including the big movers that had FADED by the time the scanner was pulled |
| **move** | `abs(change) ≥ 2pp` OR `abs(gap) ≥ 2pp` | the thin names the scanner prices correctly but whose turnover product is small |
| **no price** | the scanner cannot price the symbol | always pull these (dead, unlisted, OTC) |

Pull a symbol if **ANY** leg is true. Measured 2026-11-10 against the 2026-11-09 board's
full **767-name** ground truth: **7,517 symbols pulled, 0 board names missed.**

**Both legs are needed, and the measurements say why — each one alone is wrong:**

- **The turnover leg ALONE at $250k LOSES 27 of the 767** board names, 7 of them moving
  ≥ 5% (**MPAA −20.5%, LU −11.4%, EDU, MBC, ALKT, TBLA**). At $100k it loses 3.
- **The move leg ALONE loses 110 of the 767**, 11 of them moving ≥ 5%: the scanner's live
  quote is a **poor proxy for the 09:50 state** precisely because the 09:50 → 10:00 drift is
  largest for the biggest movers — **SKHY +3.11% at 09:50 vs +0.84% at 10:00, NBIS +7.41%
  vs +1.64%, CRWV +6.34% vs −0.37%, MRNA +3.46% vs +1.01%**.
- **$100k is not a tuned number.** It is 5× headroom below the $500k floor, and the measured
  miss count goes **9 → 0** between the $250k and $100k boundaries.

**The pre-filter is a disclosed hole, never a silent one.** The artifact MUST state the
universe size before and after the pre-filter, and say that the 09:50 trigger was evaluated
on the pre-filtered subset. A reader who knows a name was skipped can weigh it; a reader who
does not cannot.

**This applies to the OPEN slot only.** The pre-close slot reads the settled session, and its
universe comes from the settled bars rather than an intraday pull.

#### RVol and session volume: use the market-wide feed, not per-symbol history (2026-11-03)

**Do NOT pull one `chart_data` call per ticker.** Each is one metered gateway call and the
anonymous Pipeworx allowance is **50 calls/day shared across the whole fleet** — a 209-name RVol
denominator alone burned 245 calls and exhausted the pool mid-run.

Use the shared helper `_shared/rvol_fetch.py` (polygon-io `grouped_daily`): **one call returns
OHLCV for every US symbol for one date**, so ten calls give a trailing-10-session volume
denominator for the whole market. It reproduces the `chart_data` denominator to **0.000075%**
across 209 names, so RVol stays comparable with previously published digests.

**The helper is a separate file and is NOT on disk in a fresh sandbox — fetch it first:**

```bash
D=/workspace/rvol_fetch.py
for U in \
  "https://api.github.com/repos/karizaco/maxhermes-migration/contents/cloud-prompts/_shared/rvol_fetch.py?ref=main" \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/rvol_fetch.py" \
  "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/rvol_fetch.py" ; do
  curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" \
    -H "Authorization: Bearer ${GITHUB_TOKEN}" -o "$D.tmp" "$U" 2>/dev/null
  # The capability marker is MANDATORY, not decoration: an OLDER copy of this helper has
  # no `prior_session` block, and the symptom is a silent fallback to a second,
  # per-symbol price pull that costs ~3 minutes of a 15-minute budget. The CDNs also
  # cache `main` independently, so one of them can serve stale bytes for hours.
  if [ -s "$D.tmp" ] && ! head -c 200 "$D.tmp" | grep -q '"message"' \
     && head -1 "$D.tmp" 2>/dev/null | grep -q '^#!' \
     && grep -q 'RVOL_FETCH_V2' "$D.tmp" 2>/dev/null; then
    mv -f "$D.tmp" "$D"; break
  fi
  rm -f "$D.tmp"
done
[ -s "$D" ] || echo "rvol_fetch.py fetch FAILED (no RVOL_FETCH_V2 copy) - fall back to the caller's own denominator source"
python3 "$RF" --date <YYYY-MM-DD> --sessions 10 --out /workspace/avg10.json
```

It is serialized internally (~13 s between calls — Massive's shared key allows 5 req/min) and
retries on HTTP 429, so a 10-session pull takes ~2.5 minutes.

**The session-volume numerator must be SETTLED.** A volume read from the quote bridge at
~16:01 ET is **not final** — the closing auction consolidates later. **`grouped_daily` may not have
published the bar for the session you are running** (measured 2026-11-03: six attempts over ~10
minutes, upstream had not consolidated it) — the denominator is unaffected because it excludes
today by construction, but the numerator needs a settled fallback (shibui, or Yahoo's daily bar
with a `ts >= 20:00Z` settle test). Measured 2026-11-02:
published volumes ran **0.7%–30.2% low** (median ~8%) versus the settled figure, and because
RVol divides by a fixed denominator, **RVol is understated too** — 7 names crossed the Tier-A
RVol ≥ 2.0 threshold once settled (EL 1.96→2.32, NXT 1.85→2.26, VG 1.73→2.16, CRH 1.47→2.11,
FROG 1.82→2.07, VLTO 1.56→2.05, ABNB 1.51→2.03). Dollar volume is understated by the same
factor, which also shifts the within-tier ranking.

So: take the numerator from `polygon-io grouped_daily` (which also returns `o/h/l/c`, so one call
cross-checks the whole day's settled close) or from shibui — **not** from a 16:01 ET bridge
snapshot. If a live snapshot volume is published, label it as such in the artifact and treat its
RVol as a floor. See `_shared/RUNTIME-CONTRACT.md` §1e.

### Pass 1b — Premarket / gap annex (also relevant at 15:50 — gaps that held into the close)

1. **TheStockCatalyst** `https://www.thestockcatalyst.com/NYSEPMMovers` — primary PM annex.
2. **Barchart** — plain curl is WAF-blocked (HTTP 202 challenge). Use the shared helper
   `_shared/barchart_fetch.py` (headless chromium) instead: `--symbols A,B` or `--list top-gainers`.
3. **Perplexity Finance** — browser catalyst Q&A.

### Pass 2 — Confirm

Yahoo chart API for last, % chg, volume → USD $ volume. **Finviz is egress-IP blocked** (403 on every
path, Cloudflare challenge) — use the TradingView scanner and `market-recap` instead. OTC: confirm
venue + $ vol gate.

### Pass 3 — Catalysts / halts

- SEC EDGAR 8-K Atom (descriptive User-Agent): items 1.01, 2.01, 5.02, 7.01, 8.01
- Halts: the TradingView scanner's `halted` column (the NASDAQ Trade Halt RSS returns an empty
  HTML shell every time) — strip warrants
- Finviz news + PR Newswire RSS — headline glue
- Apply buyout near-offer rule

### Pass 4 — Narrative (optional)

Perplexity Finance or major wires for large-cap colour only.

**Do not depend on:** MarketWatch (often blocked), CNBC movers URL, free Finviz CSV export (Elite), Benzinga Squawk, Unusual Whales as core, Barchart without browser, any paid Finviz Elite / paid Barchart RT as a gate.

## Timing emphasis

- **~09:50 ET (`open`, the deployed slot):** the first read on the day's tape — the gap, the
  catalyst that caused it, and the names already running ahead of pace. Pace measure, ~$0.5–1m
  floor, 20-minute gap window, Overnight → open annex from the prior day's preclose carry.
- **~15:50 ET (`preclose`, the deployed slot):** gaps that held into the close, late tape, halt resumes; PM gap annex; pull prior `overnight_carry`.
- **~12:30 ET (`midday`, not deployed):** continuation vs fade; raise $ volume bar; RVol soft preference; write `overnight_carry` for AH-relevant names.

RTH: 09:30–16:00 ET.

## When

- Cron: `50 9,15 * * 1-5` America/New_York (weekdays, **09:50 ET `open` slot** and **15:50 ET `preclose` slot**, 10 min before the cash close) — one task, two fires a day
- Manual: user asks "what's in play today" or "run US stocks in play"
- For midday digest, run manually or as a separate cron (not added by default).

## Output

1. Write `C:\Users\admin\.minimax\projects\coding-shared\research\us-in-play\YYYY-MM-DD-<slot>.md`
2. Chat only if Tier A / Soft-A / material TECH_WATCH / material Tier C
3. Append **one** line to `us-stocks-in-play/logs.jsonl` in the output repo, per pipeline §7 —
   fetch the existing file first, then append; never overwrite it. The line carries `tier_a`,
   `soft_a`, `tech_watch`, `tier_c` and `chat`, so the fuel log and the digest's audit line
   always agree.
4. The Windows audit-file line is **skipped on Cloud** — the cron prompt says to skip audit log
   writes. The fuel-log line in (3) carries the same fields.

## Anti-patterns

- Treating Finviz delay as "broken" or requiring Finviz Elite
- Requiring paid Barchart / paid RT for a routine digest
- Hard-requiring RVol in the deployed slot
- Forcing Soft-A merely because RVol is unavailable (vs known soft)
- Including levered / single-stock levered ETFs
- Including illiquid pinks without $ vol gate
- Treating every buyout as Tier A / Soft-A / B chase
- Burying high-catalyst known-soft-RVol names only in Tier B when Soft-A fits
- Ranking separate source lists without normalize→merge
- Chat-only delivery with a Source health **line** instead of a **table**
- Silent empty catalysts when Barchart / blocked wires need a browser
- Marking Finviz `blocked` on an empty HTTP 200 shell without a **headed** browser attempt
- Using headless Chrome/curl alone as the "browser" fallback for Finviz/Barchart
- Burning `get_symbol_data_batch` immediately after a US `run_screener` 429 instead of Yahoo confirms
- Retrying TradingView `run_screener` after HTTP 429
- Serial `get_symbol_data` for dozens of names when one batch (≤50) would cover them
- `get_news` on every mover instead of top floor-cleared candidates only
- Forgetting overnight carry at the start of a slot after a big AH 8-K print
- Scanning through a full NYSE/NASDAQ holiday without the pipeline skip
- Dropping liquid technicals (soft RVol, large turnover) with no TECH_WATCH home