# BUGREPORT — cron #92 published a tape of invented moves on a closed market (2026-11-26)

**Status:** fixed on `main` — 2026-11-26.1 (procedure, capture script, gate).
**Routine:** cron #92 `preopen-catalyst-capture` (slots 0830 / 0950).
**First seen:** 2026-11-26 08:30 ET — Thanksgiving, with the NYSE closed.
**Severity:** the fleet's own 179-check gate passed the artifact. Nothing downstream could
have caught it.

---

## 1. What happened

The 08:30 checkpoint fired on **Thursday 2026-11-26 — Thanksgiving Day, a full NYSE
closure** — and published a tape of **379 records** as if the market were open.

| measure on the published tape | value |
|---|---|
| priced rows materially wrong (>1 point vs the real last close) | **227 / 365 (62%)** |
| rows whose **sign was flipped** | **56 / 365 (15.3%)** |
| rows wrong by more than 10 points | 56 (15.3%) |
| worst single error | **VWAV: published −5.84%, actually +171.84%** (177.68 points) |
| the band itself | **168 up / 951 down** — 85% decliners, where the documented band is roughly balanced |
| NRSN | published **+93.64%**, true **+21.02%** |
| RAYA | published **+85.93%**, true **+20.61%** |
| ABCL | published **−3.11%**, true **+0.19%** — the sign was wrong |

**The gate passed it.** Run against that tape and its board with the correct file names,
the 2026-11-20.1 checker returned **PASSED all 179 of its checks**.

The artifact was **not** published: the operator recognised the closure, and the tape was
rejected in favour of a skip marker. The tape is retained as the regression fixture at
`preopen-feed/2026-11-26-0830.jsonl` (never pushed).

---

## 2. Why the moves were wrong — the stale anchor

TradingView measures `premarket_change` against the **previous close**, and the scanner
publishes that same previous close in its own `close` column. On a live pre-market session:

```
implied_reference = premarket_close / (1 + premarket_change/100)  ==  close
```

**When the market is shut, the scanner does not roll the pre-market session forward.** It
keeps serving the PREVIOUS session's anchor, so the implied reference sits one session
behind the `close` column published beside it.

Measured, both sides:

| | evidence |
|---|---|
| **2026-11-26 (NYSE closed)** | **242 / 242** tickers shared the 2026-11-25 tape's implied reference — the **2026-11-24** close — while the last completed session had closed at the 2026-11-25 price. Live re-measurement: **124 / 1128** priced rows match the scanner's own `close` (11%). |
| **2026-11-25 (live session)** | **14 / 14** tickers' implied reference == close(2026-11-24), validated against Yahoo's daily closes; **0 / 14** matched close(2026-11-25). |

The band was 85% decliners for the same reason: a market that closed lower leaves the stale
anchor **above** most names, so nearly everything reads as a decliner.

This is a **data** defect, not a calendar one, and that is the point: it fires on any
closure the calendar knows nothing about — an unplanned halt, a half-day roll, a scanner
anomaly.

---

## 3. Why nothing caught it

Three gaps, in increasing severity.

### 3a. The #92 family had no window check — and it was an accident

21 of the 28 fleet prompts run the shared `window_check.sh`. The #92 family (92, 92a, 92b)
did not, and `26b` did not either.

It was a template accident, not a design choice: `preopen-capture.md`'s own REPLY section
says *"the window check is the first action, so read it"* — the sentence inherited from
`premarket-refresh.md` (#26's shared procedure), which **does** wire the check as step 0.
The sentence was copied; the step was not. The four sibling routines that do carry the
check — #26, #02, #15, #19 — all declined this same fire with "US market holiday".

The roster schedule is `30 8 * * 1-5` / `50 9 * * 1-5`: Mon–Fri with no holiday awareness,
so the platform fires this routine on holidays **by design** and the routine has to decline
the closure itself.

### 3b. The gate had no notion of whether a MOVE was real

Every rule the 2026-11-20.1 gate had was about the tape's **shape**: one row per ticker, a
price on every priced row, movers on both sides, catalysts dated inside the window,
coverage above the floor, the board's arithmetic matching the tape. Not one of them asked
whether the tape's numbers were real. A tape of invented moves looked exactly like a clean
one.

### 3c. The gate rejected the fleet's own marker

`check_skipped()` demanded the literal `**Reason:**` and the token `-0830`. The shared
window check writes `- Reason:` and names the slot on its own. So on 2026-11-26 the gate
**rejected the marker the window check had just written for this very checkpoint** — the
fail-closed trail was rejected by the gate that exists to validate it.

---

## 4. The fix — three layers

### Layer 1 — the window check (procedure)

`cloud-prompts/_shared/preopen-capture.md` gains a **step 0** that runs the shared
`window_check.sh` against the **fire's own instant**, before anything else is fetched or
spent. A holiday fire leaves a skip marker and **no artifact**.

The same step resolves the fire's context properly: `FIRE_MS` (this conversation's
`session.created_at`) → `DATE` and the slot. The procedure previously took `DATE` from the
**wall clock** and the slot from a **literal `export CP=0830`**, while the prompt states
both must come from `session.created_at`; that is now true, and the slot maps from the
fire's own scheduled minute (`08*` → 0830, `09*` → 0950).

The gate's `check_skipped()` was relaxed to accept **both** marker shapes and to match the
slot as a token — while still catching a marker that names the wrong slot.

### Layer 2 — the anchor guard, in the capture script (the durable one)

`preopen_capture.py` pulls the scanner's `close` column **in the same request it already
makes** (no extra call, no second source) and checks the invariant. Below a 90% match rate
on at least 25 priced rows it **fails closed**: a marker at
`preopen-feed/{date}-{slot}.SKIPPED.md`, **no tape**, exit code **3**.

It lives in the **script**, not the prompt, because a rule in a byte-pinned prompt is one
deployment away from not running, and a rule in the shared script protects every caller.

### Layer 3 — the anchor on the tape, and the gate rule

Every priced row carries **`ref_close`** — the close the scanner published alongside the
move. The gate rebuilds the implied reference from the row's own `(price, pct)` and
requires it to agree with `ref_close` on at least **90%** of the priced rows. A
stale-anchored tape now **fails the gate** instead of being published.

`ref_close` is additive: cron #17's consumer reads the keys it knows, and the board's
columns are unchanged. The rule is **grandfathered** for tapes dated before 2026-11-27.

---

## 5. Verification

```
$ python3 tools/check_preopen_checkpoint.py --repo . --slot 0830
PASSED all 144 checks

$ python3 tools/test_preopen_checkpoint_contract.py
66/66 cases behaved as required
```

New cases, each proved to bite:

| case | expected | result |
|---|---|---|
| a tape whose moves disagree with its own anchor | caught | checker exit 1 |
| a tape that carries no anchor at all | caught | checker exit 1 |
| a tape dated **before** the anchor rule | grandfathered, passes | checker exit 0 |
| a skip marker in the **fleet's** shape | accepted | checker exit 0 |
| a skip marker naming another slot | caught | checker exit 1 |

Live run against the real scanner on the closed market:

```
$ python3 cloud-prompts/_shared/preopen_capture.py --date 2026-11-26 --checkpoint 0830 --top 20
preopen capture: MARKET CLOSED — the market is closed - the scanner's pre-market anchor is
stale: 124/1128 priced rows match the scanner's own close (floor 90%) [NRSN: implied
1.1000 vs close 1.7600; RAYA: implied 0.4249 vs close 0.6550; ...]
(marker: /tmp/e2e/preopen-feed/2026-11-26-0830.SKIPPED.md)
EXIT=3        # 2.8 s — no metered catalyst call was spent
```

The gate then passed all 144 checks on that marker.

---

## 6. The rule that generalises

**A gate that verifies an artifact's SHAPE has not verified its CONTENT.** The mover
coverage floor made the fleet measure *how much of the board was explained*; nothing ever
measured *whether the board's numbers were true*. The anchor rule is that measurement, and
it is the shape the next silent failure will take.

Two smaller lessons, both from the same fire:

* **a shared helper is only live if something fetches it.** The #92 procedure referenced
  `window_check.sh` in its REPLY and never fetched it — the same class of hole the house
  already found in the checker itself on 2026-11-19.
* **the fail-closed trail needs its own gate.** A marker rejected by the gate that exists
  to validate it is an audit trail nobody can rely on.

---

## 7. Files changed

| file | change |
|---|---|
| `cloud-prompts/_shared/preopen-capture.md` | step 0 (window check + fire's instant + slot); version → 2026-11-26.1; the market-closed guard section; the skip reply; the capture/gate ladders demand the new versions and the anchor marker |
| `cloud-prompts/_shared/preopen_capture.py` | `CAPTURE_SCRIPT_VERSION` → 2026-11-26.1 + `CAPTURE_ANCHOR_GUARD_V1`; the `close` column in both scanner pulls; `anchor_health()`; the guard in `build()`; `ref_close` on every row; the market-closed marker and exit code 3 |
| `tools/check_preopen_checkpoint.py` | `CHECKER_VERSION` → 2026-11-26.1; `CAPTURE_VERSION` → 2026-11-26.1; `ref_close` allowed; the anchor rule in `check_tape`; `check_skipped()` accepts both marker shapes; static assertions for the new guards |
| `tools/test_preopen_checkpoint_contract.py` | the anchored fixtures; the three anchor cases; the two skip-marker cases |
| `cloud-prompts/_shared/RUNTIME-CONTRACT.md` | the scanner's stale pre-market anchor, measured both ways |
