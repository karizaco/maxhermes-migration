# Cron #15b — earnings-reaction-settlement: the slot's inputs, and the dates it publishes

**Date:** 2026-11-11 and 2026-11-16 (the 12:15 ET fires, sessions `2026-11-11` and `2026-11-16`)
**Scope:** cron #15b (`earnings-reaction-settlement`), the 12:15 ET EU/UK settlement pass.

Everything below was measured on the 2026-11-11 fire against live TradingView and Yahoo
data. The contract for this slot lives in the prompt
(`cloud-prompts/cron-prompts/15b-earnings-reaction-settlement.md`) and the executable in
`scripts/earnings_reaction_scanner.py` in `karizaco/minimax-cloud-outputs`
(`SCRIPT_VERSION 2026-11-11.2` after this change). Both are fetched at RUN time, so the
fix below lands on the next fire with **no `cron_update` and no prompt drift**.

---

## 1. The slot depended on two files that only existed in the 08:00 run's sandbox

### The finding

The deployed prompt says of the settlement pass:

> The settlement artifact reuses the morning's catalyst file
> (`/workspace/catalog/catalysts/<date>.md`), which the 08:00 ET run already filled in.

That was never true of a later fire. `/workspace` is a **per-session NAS mount**
(`/run/csi/mount-root/nas/<id>`), so the 08:00 run's local files are not visible to the
12:15 run. Measured on the 2026-11-11 fire, the 12:15 sandbox started with **neither**
file:

```
/workspace/earnings/2026-11-11-reactions.md          -> absent
/workspace/catalog/catalysts/2026-11-11.md           -> absent
```

Both are inputs the slot's own contract requires:

| Input | Read by | Consequence when absent |
|---|---|---|
| the morning artifact | `read_morning_eu()` | the `Move @08:00` and `Δ vs scan` columns read `—`, and **the slot's entire headline — the scan-to-close drift — is uncomputable** |
| the catalyst catalog | `parse_catalyst_file()` | the pipeline writes its own EMPTY skeleton (in settle mode the US/AU/APAC target lists are empty), so **every published row carries "no catalyst lookup (outside the per-run budget)"** — even for the names the morning had actually researched |

On 2026-11-11 the morning had researched **14** catalysts (BICO, FNM and ENR among them —
the three EU names this slot republishes with their catalysts). Without the catalog every
one of those rows would have published a placeholder instead of its researched catalyst.

### The fix — recover, do not re-research

The morning artifact **is** published to the outputs repo
(`earnings/2026-11-11-reactions.md`, 49,410 bytes, blob `dd68f784`), and the catalog's
content **is** the morning artifact's own catalyst column. So both inputs are recoverable
from what the morning run already published.

`scripts/earnings_reaction_scanner.py` v2026-11-11.2 now does this **in settle mode only**
(the 08:00 scan is untouched):

1. If the morning artifact is missing, it is fetched from the outputs repo — the
   contents API with the sandbox token, then the unauthenticated contents API, then the
   raw CDN. The body is validated (it must contain `Earnings reaction scanner` and a
   `## EU/UK` section) so a 404 page or an API error body can never be parsed as a scan.
2. If the catalyst catalog is missing, it is **rebuilt from that artifact's catalyst
   column** — the morning run's own researched text, copied verbatim, under a PROVENANCE
   note that says so. It is never overwritten when it already exists.
3. Both provenances are published in the artifact's `## Source health`:
   `morning_artifact: fetched from the outputs repo (api-token)` /
   `catalyst_catalog: rebuilt from the morning artifact (14 researched catalysts recovered)`.

When the fetch fails the run degrades **exactly** as it did before (empty `Move @08:00`,
honest placeholder catalyst), so the recovery can never make the artifact worse.

**Verified:** with both inputs deleted, the run recovered both and produced the same
result — 30 EU rows, 22 matched against the scan, max drift 6.86pp, 0 degraded sources.

---

## 2. A EU bar can still be finalising ~45 minutes after the close

AIXA (germany, SWB/Stuttgart) is the tell:

```
08:29 ET  scan (live)          close 33.97   change  +7.13
12:16 ET  settle read #1        close 34.25   change  +8.01
12:22 ET  settle read #2        close 34.35   change  +8.33
12:35 ET  scanner probe         close 34.35   change  +8.3254
Yahoo AIXA.DE daily bar         close 34.29   (this symbol mirrors XETR)
```

The venue's final bar was **still moving between the 12:16 and the 12:22 read** — 46 and
52 minutes after the 11:30 ET close. Nothing was stale: both settle reads were already
post-close refreshes of the 08:29 live print. But the `>1pp` drift count flipped from
**6 to 7 of 22** on that single row, which is exactly the number this slot exists to
report.

**Consequence:** the 12:15 ET read can still catch a bar mid-finalisation. The published
artifact must be the one produced by the last read, and the drift band should be quoted
with that caveat rather than as a fixed quantity.

### The multi-venue trap underneath it

AIXA trades on nine German venues in the keep-list, and their closes differ:

```
SWB 34.35/+8.33   TRADEGATE 34.36/+8.29   XETR 34.29/+8.00   FWB 34.26/+7.47
GETTEX 34.45/+7.39   DUS 33.86/+7.29   MUN 34.33/+5.86   HAM 34.01/+5.82   HAN 33.91/+2.94
```

The pipeline keeps the **first row the scanner returns** and the scanner sorts by
`change`, so the venue a multi-venue name lands on can change between two reads minutes
apart. The venue cell is published on every row, which is what makes this checkable — but
a re-run can legitimately differ on one row, and that must be reported rather than
silently overwritten.

---

## 3. The published "median" is an order statistic, not a median

`scan_to_settle` publishes `sorted(drifts)[len(drifts)//2]`. On 22 rows that is the 12th
smallest (0.71pp); the true median — the mean of the 11th and 12th — is **0.685pp**. The
gap is immaterial at this scale, but the artifact calls the number a median, so the code
should either compute one or stop calling it one.

---

## 4. What was checked and found clean

- **No stale republication.** Every published settle row was compared with its own 08:00
  live row: no row carried its live close forward as a "settled" close. The two rows that
  are identical between the two artifacts (GNS +12.23, DVL +5.00) were **already settled
  in the morning** — their venue's session-date label is a day behind (2026-11-10 for the
  2026-11-11 session), which is the known, tolerated one-session label ambiguity.
- **The cross-check is clean:** `agree=30 mismatch=0 unverified=0 stale_reference=0`,
  `rows_dropped_stale_ref=0`, `rows_dropped_unresolved_ref=0`, `degraded_sources=0`.
- **The contract check passes** on the published artifact
  (`tools/check_reaction_artifact.py`, marker `REACTION_ARTIFACT_V2`), and the published
  blob was verified byte-for-byte through the **git blob API** (not the CDN-cached
  contents API).

---

## 5. Recommendation for the next maintenance session

Two things are still open, and neither is worth changing from inside a fire:

1. **The settlement slot has no scheduler-side guard.** The recovery in the pipeline is
   correct, but the slot would still be silently degraded if the outputs repo were
   unreachable. A `source health` line that distinguishes "recovered" from "found locally"
   now makes that visible; the prompt could also be amended to require the recovery to be
   reported in the reply.
2. **Venue selection is order-dependent** for multi-venue names (finding 2). The
   deterministic fix is to keep the highest-**volume** venue row rather than the first
   row in a change-sorted scan — for AIXA that is XETR (volume 721,190), which is also the
   venue Yahoo mirrors. This changes row selection for #15's morning artifact as well, so
   it wants a tested change with both artifacts re-measured, not a same-day edit.

---

## 6. Two defects found on the 2026-11-16 fire (pipeline 2026-11-16.1 / 2026-11-16.2)

**Date:** 2026-11-16 (the 12:15 ET fire, session `2026-11-16`)
**Scope:** cron #15b again, but both findings live in `scripts/earnings_reaction_scanner.py`
(`karizaco/minimax-cloud-outputs`), which cron **#15** shares. The fixes are in the script,
so the next 08:00 fire inherits them too.

### 6.1 The settlement branch never rendered five disclosures the contract requires

**The finding.** `tools/check_reaction_artifact.py` gates five earnings-date provenance
disclosures on the **pipeline version**, not on the artifact kind:

| Gate | Requires |
|---|---|
| `QUALITY` | the `earnings_date_quality` table (per market) |
| `CENSUS` | the `earnings_dates:` line (catalog / calendar / asx / screener) |
| `CALENDAR` | `earnings_field_stale_rows` |
| `BUDGET` | the `catalyst_budget` split |
| `TIERS` | `earnings_tiers: fresh=<n> near=<n>` |

The **08:00 scan branch** has rendered all five since pipeline `2026-11-15.5`. The **12:15
settlement branch** rendered none of them. So every settlement artifact produced by that
pipeline failed five contract gates — the 2026-11-16 fire failed exactly those five:

```
FAIL: 5 contract violation(s) in earnings/2026-11-16-reactions-settled.md
  - QUALITY: ... does not publish the `earnings_date_quality` table
  - CENSUS: ... does not publish the `earnings_dates:` census
  - CALENDAR: ... does not publish `earnings_field_stale_rows`
  - BUDGET: ... does not publish the catalyst budget split
  - TIERS: ... does not publish `earnings_tiers`
```

**Why the checker was NOT relaxed.** The obvious "fix" is to scope the gates to the scan
artifact. That would have been the wrong trade: the gates say what they mean — *the reader
must see how good the published earnings dates are* — and a settlement artifact publishes
earnings dates exactly as much as a scan artifact does. Relaxing the gate would have left
the reader with an unprovable date and a checker that no longer says anything. **The
disclosures were rendered instead, from this pass's own data**, and the artifact passes
`check_reaction_artifact.py` with the gate untouched.

Two of them needed a settlement-scoped reading rather than a copy of the scan's line:

- `earnings_date_quality` — the settlement pass publishes **EU/UK rows only**, so `us` and
  `au` have **0 rows BY DESIGN** (the US session is open at 12:15 ET; the AU rows belong
  to the 08:00 scan). A zero row is the truth, and the line says so in words.
- `catalyst_budget` — the settlement pass performs **no new lookups** (no research happens
  in this slot), so the split is `0 US + 0 EU + 0 AU + 0 APAC/Gulf = 0 lookups`, with the
  morning's catalog named in the same line as the source of every published catalyst cell.
- `earnings_tiers` — measured over **this table's rows** (fresh = the event is dated on the
  session that just settled, near = the previous session), not over the US rows the scan
  ranks.

### 6.2 The date chain was region-blind, so an EU row inherited an Australian company's report date

**The finding.** `earnings_date_for()` consulted the **US** bulk calendar and the **AU**
announcements feed for **every** row, whatever its market. The catalyst merge was already
region-matched ("a ticker is not a company"), but the *date* chain was not.

Measured on the 2026-11-16 settlement pass, `PLT` (Oslo Børs, the **#2 mover at
+12.16%**) published:

```
| PLT | norway | OSL | 12.36 | +12.16 | ... | 2026-11-16 (0d ago) | ...
```

because an **ASX-listed company that happens to share the ticker `PLT`** reported on
2026-11-16. The Norwegian PLT's own screener field says **2026-08-06** (verified directly
against `scanner.tradingview.com/norway/scan`: `OSL:PLT` → `earnings_release_date`
`2026-08-06`, `earnings_release_next_date` `2027-02-24`). The published date was wrong, and
it was wrong in the worst direction: it made the row's earnings event look **hours old**
when it was over three months old — it also counted as "fresh" in `earnings_tiers`.

The 33 ASX codes with a results-classified announcement that day included `PLT`, `AEG`,
`AXI`, `CAM`, `HUM`, `NRL`, `SET`, `TRA`… — several of which are plausible ticker
collisions with a European venue, so this is a CLASS of defect, not a one-row typo. The
same blindness lets a US calendar date leak into a European row.

**The fix.** Each bulk feed is now consulted **only for a row in its own market**: the
Nasdaq calendar for `region == "US"`, the ASX announcements feed for `region == "AU"`.
Every other region falls through to the researched catalog entry (already region-matched)
or the screener's own field. The artifact's `earnings_dates:` census now reads
`catalog 1, calendar 0, asx 0, screener 28` — and a non-zero `asx` count in a EU-only
artifact is now itself a red flag that the gate would show.

### What was checked on the 2026-11-16 fire

- `check_reaction_artifact.py` → **OK** (`conforms to REACTION_ARTIFACT_V2`), gate
  untouched.
- The reference-close cross-check: `agree=29 mismatch=1 unverified=0 stale_reference=1`,
  `rows_dropped_stale_ref=1`, `degraded_sources=0`.
- The `scan_to_settle` measurement the slot exists for: **16** rows compared with the
  08:00 scan, **median drift 1.29pp**, **max 3.95pp**, **10 of 16** more than 1pp apart.

### Still open

- The settlement pass still calls the **US** bulk earnings calendar (8 calls) although it
  publishes no US row — a pure waste that also makes `earnings_dates: calendar 0` look
  accidental. It wants a `SETTLE_MODE` guard, measured separately from the date-chain fix.
- Finding 2 of the 2026-11-11 review (order-dependent venue selection) is still open.
