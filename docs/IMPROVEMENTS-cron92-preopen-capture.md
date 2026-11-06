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
