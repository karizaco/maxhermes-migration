# Improvements — 2026-11-06: cron #92's pre-open capture gets a recipe, a digest, and an audit trail

Three defects in the pre-open catalyst capture (`cron #92`, checkpoints 08:30 and 09:50 ET),
all found by reviewing the 2026-11-03 / 2026-11-04 fires.

| # | defect | fix | where |
|---|---|---|---|
| 1 | the recipe lived in an agent's judgement | the movers-sorted recipe is IN the procedure | `cloud-prompts/_shared/preopen-capture.md` §4 |
| 2 | the tape was machine-only | a human-readable digest sits beside every tape | `cloud-prompts/_shared/preopen_checkpoint.py` (`digest`) |
| 3 | a fail-closed fire left nothing at all | a skip marker names the date, the slot and the reason | `preopen_checkpoint.py skipped` + the procedure's key check |

The procedure is fetched by the routine **at run time**, so these changes landed on the next
fire with no `cron_update` and no prompt drift — except for the three prompts whose own text
contradicted the new behaviour, which are deployed byte-exactly.

---

## 1. The recipe was an improvisation, so every fire re-derived it

The procedure's scanner call sorted by `premarket_volume`, which buries the biggest movers
under a wall of noise. The 2026-11-04 fire worked around it by adding movers-sorted calls in
both directions — which is why that tape is **678 rows, not 120**. An agent that has to
improvise the same fix every morning is a defect that has not been fixed.

The recipe is now in the procedure:

* **Two calls, movers-sorted in both directions** — `premarket_change` DESC for the gainers and
  ASC for the losers, on **disjoint** filters (`>= +2.5` vs `<= -2.5`). Disjointness is what
  makes the no-splice rule structural: no name can appear in both halves, so no record can hold
  a price from two different calls.
* **One snapshot.** The two calls are issued back to back in the same block. On 2026-11-04 four
  records drifted because the market moved between calls (CRIS +93.3 → +97.5,
  DKI +48.0 → +69.9) while seven stayed within 0.4pp — a drifting tape reads exactly like a
  Grok error when it is not one.
* **The ±2.5% floor is measured, not chosen.** It is the cutoff the 2026-11-05 movers-sorted
  tape actually had; the old volume-sorted call cut the movers off at ±0.2%.
* **The merge is CODE, not prose.** `preopen_checkpoint.py` does the merge, the digest and the
  marker in one script, so "one number per record", "prices never from Grok" and "one row per
  ticker" are enforced rather than remembered. The procedure fetches it behind
  `PREOPEN_CHECKPOINT_V1` **and** `CHECKPOINT_SCRIPT_VERSION` — a marker alone cannot detect a
  stale copy that already carries it (measured 2026-11-05: every mirror served the same stale
  blob and "highest version wins" picked it).

**The expected tape size is ≈678 rows** — the 2026-11-04 08:30 tape (406 gainers / 271 losers /
1 flat); the 2026-11-05 08:30 tape was 700. **A tape of ~120 rows is the REGRESSION SIGNATURE**
— it means the sort went back to `premarket_volume` — and the checker flags it rather than
letting a truncated board look complete.

### The merge rules, made unambiguous

The procedure carried two contradictory bullets about whose number wins. It now says one thing:

* **the scanner supplies the number, always** — for any name the snapshot contains, `pct` and
  `price` are the scanner's `premarket_change` and `premarket_close`;
* a Grok claim that disagrees with the scanner by more than **2pp** is written `conf:"unverified"`
  (that threshold is **not** lowered — it earned its keep on 2026-11-04, when Grok claimed AMD
  was +7.3% against the scanner's −0.94%);
* a Grok name the scanner cannot find at all keeps Grok's numbers and is `conf:"unverified"` —
  it has no ground truth, so it is never presented as a fact.

**The tape's JSONL schema does not change.** Ten keys, one row per ticker, unchanged — cron #17
merges on it.

---

## 2. The tape was machine-only, so nobody could read the checkpoint

`preopen-feed/{date}-{HHMM}.md` now sits beside every JSONL: the top 15 movers by |%| desc,
with the `conf` field visible and the catalyst and the time it broke in their own columns. Its
header carries the summary statistics — records written, Grok narratives vs scanner-only rows,
the unverified count, the MEASURED Grok cost, the scanner snapshot's directional counts, and the
tape size against its expected band.

**"When it broke" is honest about what it knows.** The tape records the *snapshot* instant, not
the news time — a price feed cannot know when the news broke. When Grok names a clock time in
the catalyst text it is quoted as the catalyst time; otherwise the cell reads
`08:35:10 ET (observed)`.

---

## 3. A fail-closed fire left nothing at all

On 2026-11-03 the routine correctly wrote nothing (`XAI_API_KEY` unset) — but **nothing at all**
was left behind: no tape, no marker, no file. Cron #90's audit had to report the absence with
an empty reason, and cron #17 had to reconstruct the cause from its own provenance table.

Now the key check writes the marker the `window_check.sh` holiday path writes:

```
preopen-feed/{date}-{HHMM}.SKIPPED.md
```

It names the date, the checkpoint slot, the reason and the fact that no tape was written — so
the auditor classifies it as **skipped by design, with a reason** instead of **missing, with an
empty reason**.

### Cron #17 now READS the marker

`preopen_feed.py` (the consumer cron #17 fetches at run time) checks each checkpoint's marker
when the tape is absent, and reports `skipped_by_design` with the reason instead of inferring
the cause. Two latent bugs fell out of that work:

* the local-path branch of `_get` was **dead code** — `urlopen` cannot open a bare filesystem
  path, so `FEED_LOCAL` / `MARKER_LOCAL` never resolved and every lookup paid for the network;
* the marker's `- **Reason:**` line parsed with a stray `**`.

A checkpoint that is skipped is now visible in #17's own output instead of disappearing.

---

## The checkpoint slot comes from the scheduled instant, and it is ASSERTED

The consumer merges on the **scheduled slot** (`0830 | 0920 | 0950`). The slot is resolved from
the fire's instant (`session.created_at`), snapped to the nearest checkpoint, and **refused**
when it is more than 90 minutes from any slot — in which case the routine writes a
`DEVIATION.slot.md` trail and stops rather than inventing a filename. A literal `date +%H%M` on
a fire that executes at 08:35 names its tape `0835` — a phantom slot the consumer never reads,
so the 08:30 tape silently disappears from the merge.

The assertion is explicit: the filename's slot must be one the consumer can find.

---

## The acceptance criteria are machine assertions

`tools/check_preopen_checkpoint.py` turns every criterion in the brief into a check, and
`tools/test_preopen_checkpoint_contract.py` proves the checker bites: it renders a
contract-shaped checkpoint (which must PASS) and then mutates it — deleting the digest, hiding
the unverified marker, un-ranking the table, growing the tape to eleven keys, duplicating a
ticker, re-sorting the scan by volume, deleting the slot assertion, falling back to the wall
clock, dropping the skip marker, publishing a halt count of 0, lowering the script version
guard — and requires the checker to fail each one. **29/29 contract cases behave correctly.**

> A checker that has never been observed failing is a claim, not a guard. The same discipline
> applied here caught a real hole in a second, independently written checker: its digest-table
> parser `break`ed on the header separator row, so every table check was vacuously true.

---

## What did NOT change

* the tape's JSONL schema (10 keys — cron #17 merges on it);
* the 2pp Grok-vs-scanner disagreement threshold;
* the rule that prices come from the scanner and Grok only explains;
* the halt state, which stays `not measurable` (the `halted` column is null on every row — a
  `0` there is a measurement that was never taken);
* the reply shape — this routine is one of five documented exceptions, under 6 lines.

## Deployment

| file | deployed? | note |
|---|---|---|
| `cloud-prompts/_shared/preopen-capture.md` | run-time fetch | `PROCEDURE_VERSION: 2026-11-06.2` |
| `cloud-prompts/_shared/preopen_checkpoint.py` | run-time fetch | `PREOPEN_CHECKPOINT_V1` + `CHECKPOINT_SCRIPT_VERSION: 2026-11-06.1` |
| `cloud-prompts/_shared/preopen_feed.py` | run-time fetch | #17's consumer reads the marker |
| `tools/check_preopen_checkpoint.py` | repo | the gate |
| `tools/test_preopen_checkpoint_contract.py` | repo | proves the gate bites |
| `cron-prompts/92*.md` | **deployed byte-exactly** | the old prompts said "write nothing" on a missing key |

The three prompts were the only thing that needed a `cron_update`: they said "If
`${XAI_API_KEY}` is unset, write nothing", which directly contradicts the skip marker. They are
deployed byte-exactly and hash-verified against the repo blobs.

---

## 2026-11-10 — the digest's "When it broke" column mixed two timezones

Found during the 2026-11-10 09:50 ET checkpoint (the fire that produced
`preopen-feed/2026-11-10-0950.{jsonl,md}`).

### The defect

`cloud-prompts/_shared/preopen_digest.py` → `fmt_ts()` sliced the timestamp STRING
(`s[11:19]`) and printed the result as if every timestamp were ET. But the tape carries
two different shapes, and they are not the same zone:

| field | shape | zone |
|---|---|---|
| `ts` | `2026-11-10T09:57:44-05:00` | ET (the capture clock, `_et()` aware) |
| `trending_ts` | `2026-11-10T14:38:21Z` | **UTC** (the stocktwits snapshot's own stamp) |

Slicing both printed the UTC stamp AS IF IT WERE ET — five hours late in November (EST
is UTC-5).

### Why it matters

That column is the **WHEN** of the tape — the whole reason the capture exists is WHO /
WHAT / WHEN, and cron #17 (`us-stocks-in-play`, 15:50 ET) reads it to date a catalyst.
The published 2026-11-10 09:50 board showed:

```
| HIMS | -9.65% | high | ... its Q3 report showed a surprise loss ... | 14:38:21 |
```

`14:38:21` is the UTC stamp of news that actually broke at **09:38:21 ET**. The error is
the dangerous kind: the value still *looks* like a time of day, and it lands in the
FUTURE relative to the capture that published it, so it survives a glance.

### The fix

`fmt_ts()` now PARSES the offset and CONVERTS to `America/New_York` instead of slicing
characters. A naive timestamp (no offset) is read as ET — that is the capture script's
own format — and never as UTC. `ZoneInfo` is used rather than a hardcoded `-5`, so it
stays correct across the DST boundary.

### Evidence

- Before: `fmt_ts("2026-11-10T14:38:21Z")` → `14:38:21` (wrong; ET is 09:38:21).
- After: `fmt_ts("2026-11-10T14:38:21Z")` → `09:38:21` (correct).
- The re-rendered 2026-11-10 09:50 board shows `09:38:21` for HIMS and contains **no**
  `1[4-9]:` clock time in the table.
- The tape `.jsonl` is byte-identical before and after the re-render
  (`46ea4a75cde57c37d2922beb71483b3d64143f5d5a3db098e734e3e3a7f3e998`) — only the
  rendering changed, which is the point: the board is derived from the tape, never
  hand-edited.
- Guard: `tools/test_preopen_digest_contract.py` renders a synthetic tape carrying BOTH
  shapes, asserts every displayed time is the ET wall clock, asserts the board agrees
  with the tape's row count and tickers, and **mutates the renderer back to the
  string-slice behaviour and requires the test to fail** — so the guard is proven to
  bite, not merely to pass.

### Deployment

| file | deployed? | note |
|---|---|---|
| `cloud-prompts/_shared/preopen_digest.py` | run-time fetch | **no `cron_update` needed** — the routine downloads it at fire time, so the NEXT fire uses it |
| `tools/test_preopen_digest_contract.py` | repo | the regression test |

No prompt file changed, so no prompt redeploy and no byte-drift risk.

---

## 2026-11-11 — the tape's `pct` changed MEANING: it is now the LAST COMPLETED SESSION's move, not a pre-market print

Found by cron #25 (the routine that CONSUMES this tape) on its 2026-11-09 fire, and confirmed
against cron #92's own 2026-11-10 fire.

**Symptom.** The 08:30 tape carries `pct` and `price` per row. On **2026-11-04 through
2026-11-06** those were a **same-session pre-market print**; from **2026-11-09 onward** they are
the **previous session's settled close and change**. Measured on the 2026-11-09 08:30 tape
(`preopen-feed/2026-11-09-0830.jsonl`, 50 rows, 20 of them priced):

| name | tape `pct` | tape `price` | Nov 5 close | Nov 6 close | tape `pct` = Nov 5→6 move? | tape `price` = Nov 6 close? |
|---|---|---|---|---|---|---|
| IRTC | -30.70 | 90.22 | 130.19 | 90.22 | **yes** | **yes** |
| DKNG | -21.30 | 18.51 | 23.52 | 18.51 | **yes** | **yes** |
| KRMN | 42.13 | 45.61 | 32.09 | 45.61 | **yes** | **yes** |
| IREN | 20.02 | 21.64 | 18.03 | 21.64 | **yes** | **yes** |
| FROG | 35.33 | 100.98 | 74.62 | 100.98 | **yes** | **yes** |
| AXON | -18.18 | 313.00 | 382.56 | 313.00 | **yes** | **yes** |
| TEAM | -16.15 | 153.68 | 183.29 | 153.68 | **yes** | **yes** |
| RGTI | 19.29 | 11.75 | 9.85 | 11.75 | **yes** | **yes** |

**14 of 14 testable rows were exact** (the other 6 have no shibui row). The `price` equals the
Nov 6 SETTLED CLOSE to the cent, and the `pct` equals the Nov 5 → Nov 6 SESSION move. Independent
confirmation: TradingView's own pre-market for IRTC on 2026-11-09 was `premarket_close 91.00`,
`premarket_change +0.86%` — the tape said -30.70%. The tape was reporting **Friday's** move as
if it were Monday's pre-market.

**This also explains the row-count collapse.** The 08:30 tape was **678 rows** on 2026-11-04,
**700** on 2026-11-05, **849** on 2026-11-06 — then **50** on 2026-11-09 and **49** on 2026-11-10.
The ~120-row band was documented as *the regression signature*; **~50 rows is a different failure
mode**, and it arrived at the same time as the semantic change. The 2026-11-08 commit
`d6e2ee2f2` ("3-call pipeworx capture") and `4604b8f72` (the `price >= 1, $vol >= 1m` liquidity
floor) sit exactly in that window, and the 2026-11-09 commit `6ede65b46` then read the tape's
numbers as "pre-open DECLINERS" (`IRTC -30.7%, DKNG -21.3%, AXON -18.2% -- the three worst
movers of the session`) — those are Friday's settled decliners, and IRTC was in fact **+0.86%**
in Monday's pre-market. **The tape's own fix commit was built on a misread of its own output.**

**Why it matters more than a stale number.** A consumer that trusts `pct` as a pre-market gap
publishes the wrong day. Cron #25 caught it only because it checked the tape against a live
TradingView print for the same ticker; a consumer that did not would have published Friday's
movers as Monday's gaps.

**Consumer-side mitigation (applied in cron #25, no change needed here).** From cron #25's
2026-11-10 fire onward, a tape row is used for **catalyst leads only**, never for a price or a
gap, and the tape is counted as a degraded source (`degraded_sources` / `errors`).

**Suggested producer-side check** (not applied here — cron #92 owns this script):
assert that the tape's `pct`/`price` are the CURRENT session's pre-market prints, e.g. by
comparing one priced row against the same ticker's `premarket_close` from the scanner, or by
refusing rows whose `price` equals the previous session's close. A cheap proxy: the capture
already knows the session date; a row whose `price` equals that session's settled close is a
stale row and should be dropped or relabelled.

**Do-not list (unchanged by this finding).**
- Do NOT edit `cloud-prompts/_shared/preopen_capture.py` or `preopen_checkpoint.py` from another
  routine — the capture is cron #92's and it has an active session.
- Do NOT change the tape's size band to accommodate a 50-row tape. The band describes what a
  HEALTHY tape looks like; a 50-row tape is a defect to fix at the producer, not a new baseline.
- Do NOT re-derive the historical 2026-11-04/05/06 tapes; they carried same-session prints and
  are unaffected.

---

## 2026-11-11 — the digest's "priced movers" line counts rows, not session-correct movers

`preopen_digest.py` reports `priced movers: N (G up / L down)` from rows that carry a `pct`.
On the 2026-11-09 and 2026-11-10 tapes that count is arithmetically fine but **semantically
misleading**: the `pct` values are prior-session moves, so the digest's "biggest movers" board
ranks Friday, not Monday. The digest should label the column it is sorting by
(`prior session` vs `pre-market`), so a reader cannot mistake one for the other.
