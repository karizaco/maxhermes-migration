# Cloud Mavis cron: preopen-catalyst-capture (cron #92)

PROCEDURE_VERSION: 2026-11-28.1

Captures the pre-open **catalyst tape**: for each US stock materially moving pre-market or at the
open, record WHO / WHAT / WHEN, with ground-truth prices. Cron #17 (`us-stocks-in-play`,
15:50 ET) reads the tape to explain why a stock moved and when the news broke — the one thing no
price feed can tell it.

**The whole capture is one script.** Fetch it and run it; do not improvise the procedure.

## WHAT THIS IS FOR

At 15:50 the digest sees where a stock IS, not where it came from, and — the gap — not the
catalyst as it was understood at the open. By 15:50 the wire has moved on: the 09:12 headline is
buried, and a name that gapped +12% on an FDA approval and now trades +2% looks identical to one
that never moved. The skill requires the gap annex to separate a gap that **held into the bell**
from one that faded, and to attribute the move.

## STEPS — execute IN ORDER

### 0. THE FIRE'S INSTANT, THE SLOT, AND THE WINDOW CHECK

**THE WINDOW CHECK IS THE FIRST ACTION (2026-11-26).** This routine ran on
2026-11-26 — **Thanksgiving, with the NYSE closed** — and published a tape of
*invented* moves: 62% of its priced rows were wrong by more than a point, 15.3% had a
**flipped sign**, and the worst was off by **177 points**. The gate passed all 179 of
its checks on it, because every rule it had was about the tape's SHAPE and none of them
asked whether a MOVE was real. The four sibling routines that carry the shared window
check (#26, #02, #15, #19) all declined that same fire; this one had no window check at
all, and it was a template accident: this procedure's own REPLY said *"the window check
is the first action"*, the sentence inherited from `premarket-refresh.md` (#26's shared
procedure, which DOES wire it) — the sentence was copied, the step was not.

Two rules now stand between a closed market and a published tape:

* **the window check** (this step) — the same shared gate every other routine in the
  fleet runs. A holiday fire leaves a skip marker and **no artifact**.
* **the anchor guard** (inside the capture script, step 2) — it checks the tape's own
  moves against the scanner's own `close` column. It needs **no calendar**, so it also
  catches an unplanned closure, a half-day roll and a scanner anomaly: days a calendar
  calls "trading".

```bash
# ---- 0a. THE FIRE'S INSTANT. Read it ONCE; everything else derives from it. ------
#
# FIRE_MS is THIS conversation's session.created_at, in epoch milliseconds - the
# moment the fire was DISPATCHED FOR. It is NOT the wall clock: the platform can
# stall a fire by hours, and every value derived from the wall clock is then wrong.
# Measured 2026-11-05: the 08:30 slot's work began at 10:09 ET after a platform
# stall.
#
# Read it with the session_get tool (session_id "me"), or from the session record the
# platform printed. Set it below before running the block.
#
# The prompt points at "the procedure's step 2" for FIRE_MS; it is defined HERE, in
# step 0, because the window check needs the fire's instant before anything else runs.
FIRE_MS=${FIRE_MS:-0}

if [ "$FIRE_MS" -gt 0 ] 2>/dev/null; then
  export DATE=$(TZ=America/New_York date -d "@$((FIRE_MS / 1000))" +%Y-%m-%d)
  export FIRE_HHMM=$(TZ=America/New_York date -d "@$((FIRE_MS / 1000))" +%H%M)
else
  # No instant: fall back to the wall clock, which is right for an ON-TIME fire, and
  # the capture's own slot guard still refuses a slot outside {0830, 0920, 0950}.
  export DATE=$(TZ=America/New_York date +%Y-%m-%d)
  export FIRE_HHMM=$(TZ=America/New_York date +%H%M)
fi

# ---- 0b. THE SLOT. It is a property of the FIRE, not of the clock. ---------------
#
# This routine has TWO fires - 0830 and 0950 - and this procedure serves both, so the
# slot is mapped from the fire's own scheduled minute:
#
#     08*  ->  0830   (the 08:30 checkpoint, cron 92a)
#     09*  ->  0950   (the 09:50 checkpoint, cron 92b)
#
# A literal `date +%H%M` names an 08:35 execution "0835" - a slot cron #17 never
# reads, because it merges the checkpoints by slot name - and a phantom slot sorts
# AFTER 0950, so a consumer replaying the checkpoints oldest-first replays the 08:30
# tape LAST.
export CP=0830
case "$FIRE_HHMM" in
  09*) CP=0950 ;;
  08*) CP=0830 ;;
esac

# ---- 0c. THE WINDOW CHECK. -----------------------------------------------------
#
# The shared gate, the same one 21 of the 28 fleet prompts run. It is evaluated
# against the FIRE's own clock, so a fire scheduled on a holiday and replayed on a
# trading day is judged by the day it was DISPATCHED FOR, and the other way round.
#
# Require the CAPABILITY MARKER, not a non-empty body: an older script silently
# ignores the flags below, and a 404 page is a non-empty JSON blob, not a script. The
# contents API is authoritative and is NOT CDN-cached, so it is tried FIRST.
S=/workspace/window_check.sh
for U in \
  "https://api.github.com/repos/karizaco/maxhermes-migration/contents/cloud-prompts/_shared/window_check.sh?ref=main" \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/window_check.sh" \
  "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/window_check.sh" ; do
  if [ -n "${GITHUB_TOKEN:-}" ]; then
    curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" \
      -H "Authorization: Bearer ${GITHUB_TOKEN}" -o "$S.tmp" "$U" 2>/dev/null
  else
    curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" -o "$S.tmp" "$U" 2>/dev/null
  fi
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

sh "$S" --scheduled-at-ms "${FIRE_MS:-0}" \
   --out preopen-feed --name "preopen_catalyst_capture_$CP" \
   --label "Cron #92 preopen catalyst capture ($CP)" \
   --nn 92
WINDOW_RC=$?
```

**IF THE WINDOW CHECK EXITS NON-ZERO, THE FIRE IS OUT OF WINDOW.** Stop here: do not
fetch the skill, do not run the capture, do not write an artifact, do not render a
board. The skip marker the window check wrote IS the audit trail for this run, and it
is already pushed.

Reply with these lines and nothing else:

```
checkpoint: <DATE> <CP> — SKIPPED, no tape (the window check declined this fire)
records written: 0 — no tape; digest: none (preopen-feed/<DATE>-<CP>.md is intentionally absent)
mover coverage: n/a — no movers table published; catalyst coverage (whole tape): n/a
halt state: not measurable (no rows)
push: marker pushed (refs/skipped-markers/<DATE>_SKIPPED_preopen_catalyst_capture_<CP>.md)
errors: 0 — a deliberate skip is not a failed capture
```

`window_check.sh` also prints `stall_min:` — the platform's delay before this turn
actually started. **Over 5 means the fire was BLOCKED**: count ONE error for it and
add a `stalled:` line (see the REPLY section).

### 1. Fetch the capture script and the digest renderer

```bash
# The CONTENTS API is authoritative and is NOT CDN-cached; the two CDNs cache `main`
# independently (measured 2026-11-04: raw.githubusercontent served a stale blob for
# >17 minutes after a push while jsDelivr was fresh). Require the CAPABILITY MARKER,
# not just a non-empty body: an older script silently ignores the flags below, and a
# stale copy would run the gainers-only scan that misses the biggest decliners.
#
# AUTHENTICATE the fetch when a token is present. The unauthenticated contents API
# allows 60 requests/hour per egress IP, and this sandbox's egress is SHARED with
# every other routine - so an anonymous call to the AUTHORITATIVE source fails on
# rate limit, and the ladder silently falls through to the CDN copies that can be
# stale. Measured 2026-11-11 08:30 ET: the unauthenticated contents call returned no
# marker at all and the ladder only reached the fresh script through
# raw.githubusercontent. An empty token must NOT be sent (GitHub answers a malformed
# Authorization header with 401, which would break a fetch that worked anonymously),
# so the header is added only when the token is set.
S=/workspace/preopen_capture.py
for U in \
  "https://api.github.com/repos/karizaco/maxhermes-migration/contents/cloud-prompts/_shared/preopen_capture.py?ref=main" \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/preopen_capture.py" \
  "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/preopen_capture.py" ; do
  if [ -n "${GITHUB_TOKEN:-}" ]; then
    curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" \
      -H "Authorization: Bearer ${GITHUB_TOKEN}" -o "$S.tmp" "$U" 2>/dev/null
  else
    curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" -o "$S.tmp" "$U" 2>/dev/null
  fi
  # 2026-11-26.1 is the version that ADDS THE ANCHOR GUARD: it refuses to write a
  # tape when the scanner's pre-market anchor is stale, which is exactly what a
  # CLOSED MARKET looks like. Measured 2026-11-26: the 2026-11-17.2 build wrote a
  # tape of invented moves on Thanksgiving - 15.3% of the priced rows with a flipped
  # sign - and the 2026-11-20.1 gate PASSED all 179 of its checks on it.
  #
  # The CAPABILITY MARKER is demanded as well, so the rule is explicit in the ladder
  # and a later build that moves the version cannot silently drop the guard.
  # 2026-11-28.1 adds THE ROLL PROBE: the build that tells a SHUT market from an
  # OPEN one. Measured 2026-11-27 09:50 ET: the 2026-11-26.1 build called a LIVE
  # market "closed" (100 of 1142 priced rows agreed with the scanner's own close, 8.8%
  # against a 90% floor) because the 09:50 slot fires TWENTY MINUTES AFTER THE OPEN,
  # where the scanner's `close` column is a live price rather than the previous close.
  # The probe settles it with the scanner's own figures - a settled close does not
  # move, a live price does - so no calendar and no second source are involved.
  if grep -q 'CAPTURE_SCRIPT_VERSION: 2026-11-28.1' "$S.tmp" 2>/dev/null \
     && grep -q 'CAPTURE_ANCHOR_GUARD_V1' "$S.tmp" 2>/dev/null \
     && grep -q 'CAPTURE_ANCHOR_ROLL_V1' "$S.tmp" 2>/dev/null; then
    mv -f "$S.tmp" "$S"; break
  fi
  rm -f "$S.tmp"
done
[ -s "$S" ] || { echo "capture script fetch FAILED — write nothing"; exit 1; }

D=/workspace/preopen_digest.py
for U in \
  "https://api.github.com/repos/karizaco/maxhermes-migration/contents/cloud-prompts/_shared/preopen_digest.py?ref=main" \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/preopen_digest.py" \
  "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/preopen_digest.py" ; do
  if [ -n "${GITHUB_TOKEN:-}" ]; then
    curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" \
      -H "Authorization: Bearer ${GITHUB_TOKEN}" -o "$D.tmp" "$U" 2>/dev/null
  else
    curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" -o "$D.tmp" "$U" 2>/dev/null
  fi
  # PREOPEN_DIGEST_V2 is the version that renders the COVERAGE line and the
  # DEGRADED banner. A V1 renderer would pass a V1 grep and publish a board with no
  # coverage on it - the silent failure this version exists to stop - so the ladder
  # demands V2.
  #
  # PREOPEN_MOVER_COVERAGE_V1 is demanded as well, because the METRIC changed on
  # 2026-11-15: the board now gates the coverage of the MOVERS IT PUBLISHES (30%),
  # not the coverage of the whole tape (40%, which could never be cleared). A stale
  # V2 renderer publishes the old metric and the old floor, and it must not win the
  # ladder.
  #
  # PREOPEN_EDGAR_V1 and PREOPEN_SIZE_SPLIT_V1 (2026-11-17.2) are demanded too: they
  # mark the renderer that publishes the board's SIZE SPLIT and the DEGRADED banner
  # that names the real cause instead of blaming a budget that was never binding. A
  # stale renderer would publish the old, WRONG cause text and no split at all.
  #
  # PREOPEN_EDGAR_DATE_V1 (2026-11-17.3) is demanded for the SAME reason one step
  # further: the renderer changed how it prints a DATE. EDGAR hands back a filing date
  # with no time on it, and the old renderer formatted every stamp as a clock time, so
  # a filing dated 2026-11-16 printed "00:00:00" - a bare midnight with no date on the
  # row, and on three of the 2026-11-17 08:30 board's rows no date ANYWHERE. The
  # column's whole job is WHEN. A stale renderer must not win the ladder.
  #
  # PREOPEN_ANCHOR_MODE_V1 (2026-11-28) is demanded too: the renderer that publishes
  # the board's ANCHOR line, which names the state the capture was in. A tape taken
  # AFTER the open is not the same artifact as one taken before it, and a board that
  # does not say which it is is a silent context change.
  if grep -q 'PREOPEN_DIGEST_V2' "$D.tmp" 2>/dev/null \
     && grep -q 'PREOPEN_MOVER_COVERAGE_V1' "$D.tmp" 2>/dev/null \
     && grep -q 'PREOPEN_EDGAR_V1' "$D.tmp" 2>/dev/null \
     && grep -q 'PREOPEN_SIZE_SPLIT_V1' "$D.tmp" 2>/dev/null \
     && grep -q 'PREOPEN_EDGAR_DATE_V1' "$D.tmp" 2>/dev/null \
     && grep -q 'PREOPEN_ANCHOR_MODE_V1' "$D.tmp" 2>/dev/null; then
    mv -f "$D.tmp" "$D"; break
  fi
  rm -f "$D.tmp"
done
[ -s "$D" ] || { echo "digest renderer fetch FAILED — the board is part of the checkpoint"; exit 1; }
```

### 2. Run the capture — with the FIRE'S SLOT, never the wall clock

```bash
# DATE and CP were resolved in STEP 0, from the FIRE'S INSTANT. Do not recompute
# them here: `export DATE=$(date +%Y-%m-%d)` would name the day the agent HAPPENED to
# start, which is the wrong day for a fire that was dispatched yesterday, and a
# literal wall-clock slot names a phantom slot cron #17 never reads.
#
# The script ASSERTS the slot is one of 0830 / 0920 / 0950 and snaps a late dispatch
# DOWN onto the slot it belongs to (<= 90 min); past that it writes a
# .DEVIATION.slot.md marker and writes NO tape. Measured 2026-11-05: the 08:30 slot's
# work began at 10:09 ET after a platform stall, and a wall-clock slot would have
# named its file 1010 - a phantom slot that sorts AFTER 0950, so a consumer replaying
# oldest-first replays the 08:30 tape LAST.
python3 "$S" --date "$DATE" --checkpoint "$CP" --top 20
CAPTURE_RC=$?
```

The script prints one line: `preopen capture: wrote N records to <path> ...`.

- **It writes nothing and exits 0 if `PIPEWORX_API_KEY` is unset** — a missing key is not a
  failure, it is a missing tape. Never write an empty tape: the consumer would read it as
  "no news" for names that had a catalyst.
- **EXIT CODE 3 = THE MARKET-CLOSED TRAIL (2026-11-26).** The capture DECLINED: the
  scanner's pre-market anchor is stale, so every move it would have published was
  measured against the wrong close (measured 2026-11-26: 15.3% of the priced rows came
  out with a **flipped sign**). The script wrote its own marker at
  `preopen-feed/${DATE}-${CP}.SKIPPED.md` and **no tape**. Do NOT render a board and do
  NOT write a tape: push the marker, gate it with `--skipped`, and reply with the skip
  lines.
- The tape is written **atomically** (temp file + rename), so a slot's file holds exactly ONE
  snapshot. Appending was how two agents running the same slot against the same shared
  `/workspace` produced a 100-row tape for 53 tickers on 2026-11-09 — one row per ticker per
  run, which breaks the "one row per ticker" rule and makes cron #17 read a stale record as
  the latest one.

### 3. Render the digest — the board a trader reads before the open

```bash
python3 "$D" --tape /workspace/preopen-feed/${DATE}-${CP}.jsonl \
               --out  /workspace/preopen-feed/${DATE}-${CP}.md \
               --date "$DATE" --slot "$CP"
```

Every successful checkpoint writes **TWO files**: the tape (`.jsonl`) and the digest (`.md`).
The digest is rendered FROM the tape, never by hand, so the board can never disagree with the
data cron #17 reads at 15:50. It carries the record count, the provenance split, the
**mover coverage** of the table it publishes (see THE MOVER COVERAGE FLOOR below), the
whole-tape coverage as context, the top 15 movers by |%| with
their catalyst, their `conf` token and when the news broke, and the halt state —
`not measurable`, because the `halted` column is null on every row (never `0`).

### 4. GATE the artifact — fetch the CHECKER, or you are running a stale one

The gate is a run-time dependency exactly like the capture script and the renderer, so
it is FETCHED like them — and it is the one that was forgotten.

**Measured 2026-11-19:** this sandbox carried the **2026-11-16** gate. Run against a
**correct** board it failed 6 of 52 checks: five were "the repo file is missing" and one
was the date column — because that build's `_fmt_et` has no `dates` branch, so it
computed `00:00:00` for a date-only EDGAR stamp and demanded the bare midnight that the
2026-11-17.3 rule exists to remove. Worse, that gate also demanded the **2026-11-15.1
capture script** — the build with **zero** SEC EDGAR references (against the current
build's 52) — so *obeying* it would have forced a capture that cannot clear the
mover-coverage floor and turned a passing checkpoint into a degraded one.

**A gate older than the artifact it gates always finds a fault, and that fault will be a
real rule the artifact obeys.** So the gate is fetched with a capability marker, and the
marker is what makes a stale copy impossible to run.

```bash
K=/workspace/check_preopen_checkpoint.py
for U in \
  "https://api.github.com/repos/karizaco/maxhermes-migration/contents/tools/check_preopen_checkpoint.py?ref=main" \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/tools/check_preopen_checkpoint.py" \
  "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/tools/check_preopen_checkpoint.py" ; do
  if [ -n "${GITHUB_TOKEN:-}" ]; then
    curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" \
      -H "Authorization: Bearer ${GITHUB_TOKEN}" -o "$K.tmp" "$U" 2>/dev/null
  else
    curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" -o "$K.tmp" "$U" 2>/dev/null
  fi
  # The CAPABILITY MARKER, not a non-empty body: an older gate silently ignores the
  # date contract and the ANCHOR contract and fails a CORRECT board.
  #
  # 2026-11-26.1 adds THE ANCHOR RULE: a tape carries the close its moves were
  # measured against, and the gate checks the tape against it. Measured 2026-11-26:
  # the 2026-11-20.1 gate, run against the tape the capture wrote on Thanksgiving
  # with the NYSE closed, PASSED all 179 of its checks - on a tape where 15.3% of the
  # priced rows had a flipped sign. It verified the tape's SHAPE and never asked
  # whether its MOVES were real.
  #
  # 2026-11-28.1 adds THE ANCHOR MODE RULE on top of it: a tape states which state
  # the capture was in (`aligned` before the open, `rolled` after it) and carries the
  # scanner's published close beside its anchor, so a tape written after the open is
  # checked against evidence instead of being refused.
  if grep -q 'CHECKER_VERSION: 2026-11-28.1' "$K.tmp" 2>/dev/null; then
    mv -f "$K.tmp" "$K"; break
  fi
  rm -f "$K.tmp"
done
[ -s "$K" ] || { echo "gate fetch FAILED — do not publish an ungated artifact"; exit 1; }

# THE REPO CONTEXT. The gate is not hermetic: it reads the procedure, the capture
# script, the renderer and the two cron prompts out of the repo root, so it can check
# that what it is gating is what the fleet actually deploys. Check the BODY - a 404
# page is a non-empty JSON blob, not a file.
R=/workspace/_repo_ctx
mkdir -p "$R/cloud-prompts/_shared" "$R/cloud-prompts/cron-prompts"
for p in cloud-prompts/_shared/preopen-capture.md \
         cloud-prompts/_shared/preopen_capture.py \
         cloud-prompts/_shared/preopen_digest.py \
         cloud-prompts/cron-prompts/92a-preopen-catalyst-capture-0830.md \
         cloud-prompts/cron-prompts/92b-preopen-catalyst-capture-0950.md ; do
  if [ -n "${GITHUB_TOKEN:-}" ]; then
    curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" \
      -H "Authorization: Bearer ${GITHUB_TOKEN}" -o "$R/$p" \
      "https://api.github.com/repos/karizaco/maxhermes-migration/contents/$p?ref=main" 2>/dev/null
  else
    curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" -o "$R/$p" \
      "https://api.github.com/repos/karizaco/maxhermes-migration/contents/$p?ref=main" 2>/dev/null
  fi
done

python3 "$K" --repo "$R" \
   --tape /workspace/preopen-feed/${DATE}-${CP}.jsonl \
   --digest /workspace/preopen-feed/${DATE}-${CP}.md --slot "$CP"
```

**A SKIPPED CHECKPOINT IS GATED TOO.** The marker is the checkpoint's audit trail, so
the same gate checks it: it must name its reason and its slot, and **no tape may sit
beside it** (a tape beside a skip marker is the worst outcome — the consumer reads a
tape that has no catalyst in it as "no news").

```bash
python3 "$K" --repo "$R" \
   --skipped /workspace/preopen-feed/${DATE}-${CP}.SKIPPED.md --slot "$CP"
```

**The gate's exit code is a decision, not a note.**

- `0` — every check passed. Push.
- `1` — **the artifact** failed a check. Do **not** push it, and do **not** "fix" the
  artifact to satisfy a check you believe is wrong: read the failure, and if the
  checker is the thing that is wrong, fix the CHECKER in the repo (bumping its marker)
  and re-run. A gate you argued with is not a gate.
- `2` — **the gate could not be set up** (the repo context is incomplete). Fetch the
  files it names and re-run. Never treat this as a pass: the gate refuses to run a
  partial check set, because a run that silently executes 52 of its 151 checks looks
  exactly like a clean one.

### 5. Push

```bash
B=https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared
for U in "$B/push_artifact.sh" "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/push_artifact.sh"; do
  [ -s /workspace/push_artifact.sh ] || curl -sL -o /workspace/push_artifact.sh "$U"
done
sh /workspace/push_artifact.sh --out preopen-feed \
   --add preopen-feed/${DATE}-${CP}.jsonl \
   --add preopen-feed/${DATE}-${CP}.md \
   --branch main --nn 92
sh /workspace/verify_delivery.sh --path preopen-feed/${DATE}-${CP}.jsonl --branch main
```

**IN A SKIPPED CHECKPOINT, STAGE THE MARKER INSTEAD** — the tape and the board do not
exist, and pushing a path that does not exist is not a push:

```bash
sh /workspace/push_artifact.sh --out preopen-feed \
   --add preopen-feed/${DATE}-${CP}.SKIPPED.md \
   --branch main --nn 92
sh /workspace/verify_delivery.sh --path preopen-feed/${DATE}-${CP}.SKIPPED.md --branch main
```

**Stage only `preopen-feed/`. Never `git add -A`.**

## THE MARKET-CLOSED GUARD — A CLOSED MARKET IS NOT A QUIET ONE

**MEASURED 2026-11-26 08:30 ET. This checkpoint fired on THANKSGIVING, with the NYSE
closed, and it published a tape of INVENTED moves.** 379 records, and:

| measure on that tape | value |
|---|---|
| priced rows materially wrong (>1 point) | **227 / 365 (62%)** |
| rows whose **sign was flipped** | **56 / 365 (15.3%)** |
| rows wrong by more than 10 points | 56 (15.3%) |
| worst single error | **VWAV: published −5.84%, actually +171.84%** (177.68 points) |
| the band itself | **168 up / 951 down** — 85% decliners, where the documented band is roughly balanced |

And **the 2026-11-20.1 gate PASSED all 179 of its checks on it.** Every rule the gate
had was about the tape's SHAPE — one row per ticker, a price on every priced row,
movers on both sides, catalysts dated inside the window, coverage above the floor — and
**not one of them asked whether a MOVE was real.** A tape of invented moves looked
exactly like a clean one. That is the silent failure this whole file exists to prevent,
in a dimension nobody had looked at.

### WHY THE MOVES WERE WRONG

TradingView measures `premarket_change` against the **previous close**, and the
scanner publishes that same previous close in its own `close` column. So on a live
pre-market session:

```
implied_reference = premarket_close / (1 + premarket_change/100)   ==   close
```

and the tape's own numbers can be checked against the scanner's own `close` — **in the
same response, with no extra request, no second source and no calendar.**

When the market is SHUT, the scanner does not roll the pre-market session forward: it
keeps serving the PREVIOUS session's anchor, so the implied reference stays one session
behind the `close` column published beside it.

| | measured |
|---|---|
| **2026-11-25** (a live pre-market session) | **14 / 14** tickers' implied reference == close(2026-11-24), validated against Yahoo's daily closes — **0 / 14** matched close(2026-11-25) |
| **2026-11-26** (the NYSE closed) | **242 / 242** tickers shared the 2026-11-25 tape's implied reference (the 2026-11-24 close) while the last completed session had closed at the 2026-11-25 price |

So the invariant is **definitional, not heuristic**, and it needs no holiday calendar.
The band was 85% decliners for the same reason: a market that closed lower leaves the
stale anchor sitting ABOVE most names, so nearly everything reads as a decliner.

### THE TWO RULES THAT NOW STAND BETWEEN A CLOSED MARKET AND A PUBLISHED TAPE

1. **THE WINDOW CHECK** (step 0) — the same shared gate 21 of the 28 fleet prompts run.
   A holiday fire leaves a skip marker and **no artifact**. It is calendar-based, so it
   knows about **planned** closures.
2. **THE ANCHOR GUARD** (inside the capture script) — it checks the tape's own moves
   against the scanner's own close and **fails closed**: a marker, no tape, exit code 3.
   It is data-based, so it also catches an **unplanned** closure, a half-day roll and a
   scanner anomaly — all the days a calendar calls "trading".

The second is the durable one, and it lives in the **script**, not in the prompt: a
rule in a byte-pinned prompt is one deployment away from not running, and a rule in the
shared script protects every caller of it.

### THE TAPE CARRIES ITS ANCHOR

Every priced row now carries **`ref_close`** — the close the scanner published alongside
the move, so the gate can check the tape **against itself** afterwards, with no network
and no second source:

* the capture publishes `ref_close` on every priced row;
* `tools/check_preopen_checkpoint.py` rebuilds the implied reference from the row's own
  `(price, pct)` and requires it to agree with `ref_close` on **at least 90%** of the
  priced rows (a live session measures ~100%; a stale anchor measured **11%**);
* a tape dated on or after **2026-11-27** that does not carry the anchor, or whose
  moves disagree with it, **FAILS the gate** instead of being published.

The rule is **GRANDFATHERED** for tapes written before the capture started carrying the
anchor — a historical artifact is never failed for a rule that post-dates it. Same
shape as the date contract and the coverage floor.

`ref_close` is **additive**: cron #17's consumer reads the keys it knows and ignores
the rest, and the board's columns are unchanged. The board still shows the move, not
the anchor — the anchor is what the GATE reads, not what the reader needs.

---

## THE ANCHOR IS INSTANT-BOUND, AND THE 09:50 SLOT SITS PAST THAT INSTANT (2026-11-28)

**THE GUARD WAS RIGHT ABOUT THE CLOSED MARKET AND WRONG ABOUT A LIVE ONE.** The invariant it
checks —

```
implied_reference = premarket_close / (1 + premarket_change/100)  ==   close
```

— holds **while the PRE-MARKET session is live**, because then the scanner's `close` column IS
the previous close. At the **09:30 ET open** the scanner ROLLS that column: `close` becomes the
**LIVE regular-session price**, while `premarket_change` and `premarket_close` **freeze** at their
last pre-open values.

Measured 2026-11-27 09:50 ET, two scanner pulls 45 s apart:

| | pull A | pull B | implied reference |
|---|---|---|---|
| UFG `close` | 2.9612 | 2.9099 | **1.72** (frozen) |
| AAPL `close` | 356.7617 | 356.79 | **355.58** (frozen) |
| POM implied | — | — | **1.61** (frozen) |
| MNDR implied | — | — | **0.5048** (frozen) |

The implied reference stayed **frozen and CORRECT** — byte-identical to the 08:30 tape's
`ref_close` — while the scanner's `close` **ticked**. So the moves on that tape were real; the
guard's PREMISE was not. It fired (100 of 1142 priced rows agreed, 8.8% against a 90% floor) and
called a live, trading market *"closed"*.

**AND THE 09:50 SLOT IS SCHEDULED `50 9 * * 1-5` ET — TWENTY MINUTES AFTER THE OPEN.** So the
guard could not pass for it on any regular weekday. It was dead from the 2026-11-26.1 build
onward; 2026-11-26 was masked by Thanksgiving (the calendar window check declined that fire
first), so **2026-11-27 was the first weekday it bit.** The 08:30 slot was never affected:
pre-open, `close` IS the previous close, and it measured 295 of 296.

**THE DISCRIMINATOR IS PHYSICAL, NOT A CALENDAR: a SETTLED close does not move, and a LIVE price
does.** Measured on a closed market (2026-11-28): **0 of 40** sampled names changed their `close`
or their `volume` in 45 seconds. Measured on the live session (2026-11-27 09:50 ET): **4 of 4**
moved in 45 seconds, and the regular session's `volume` accumulates every second, which no
settled figure ever does.

So the capture now takes **its own second sample** of the same names and asks the scanner
whether its figures moved. **A SHUT MARKET IS STILL REFUSED** — the probe only decides which of
the two wrong-looking states the capture is standing in:

| the anchor says | the probe says | the capture does |
|---|---|---|
| agrees | — | publishes; `ref_mode: aligned`; the anchor IS the scanner's own close |
| disagrees | nothing moved | **SKIPS** — marker, no tape, exit 3 (the closed market) |
| disagrees | it is moving | publishes; `ref_mode: rolled`; the anchor is the provider's **implied reference** |

**WHY THE ROLLED ANCHOR IS THE IMPLIED REFERENCE.** `premarket_change` is the provider's own
measure against the previous close, so `premarket_close / (1 + premarket_change/100)` **is** that
close — and the tape already carries both numbers, so nothing is invented. It was confirmed
against the 08:30 tape of the same day: the implied reference on the 09:50 pull was byte-identical
to that tape's `ref_close` for every name checked.

**THE TAPE CARRIES THE EVIDENCE, SO THE GATE CAN CHECK IT OFFLINE.** Every priced row now
carries `ref_mode` (`aligned` | `rolled`) and `ref_scanner_close` — the scanner's published
close, beside the anchor. In the aligned state the two are the same figure; in the rolled state
the scanner's close is the live price and **the two must differ**. That difference IS the proof
that the session rolled, and it is on the tape, so the gate needs no network and no second
source to judge it — and a tape that merely *claims* to be rolled, while its own figures say
otherwise, fails the gate.

**A TAPE DATED BEFORE 2026-11-28 IS GRANDFATHERED** against this rule, like every other rule
here. The anchor rule itself (2026-11-27) is unchanged and still bites.

## WHAT THE SCRIPT DOES (for the reply, not for reimplementation)

Five Pipeworx gateway calls plus one TradingView scanner POST, each with one job:

| Call | Pack | Job |
|---|---|---|
| `trending_symbols` | `stocktwits` | candidates + a natural-language reason + a `summary_at` timestamp for each. Live retail/WSB chatter — the X signal. |
| `top_movers` (gainers) | `market-recap` | YESTERDAY's movers universe, in one direction — the names being watched before they gap. |
| `top_movers` (losers) | `market-recap` | the same universe for the other direction. |
| TradingView scanner — **the band** | direct POST | **TODAY's pre-market movers**: every US stock trading more than ±2.5% pre-market, in two DISJOINT halves. **This is the tape's candidate source.** |
| `polygon_io_news` | `polygon-io` | the article feed, straight from the provider: `published_utc`, `article_url`, title and description. **This is where the catalyst gets its DATE — and it is consulted FIRST.** |
| `ask_pipeworx_grounded` | `market-recap` | a per-name catalyst with evidence and confidence, spent ONLY on a name the article feed could not date. It does **not** say WHEN the news broke. |
| TradingView scanner | direct POST | **the PRICE**: this session's `premarket_change` and `premarket_close` for every name on the tape. |

**THE CANDIDATE SOURCE IS TODAY'S PRE-MARKET BAND, NOT YESTERDAY'S MOVERS.**

`top_movers` is Yahoo's predefined screener over the **last completed regular session**, so
before the open it names YESTERDAY's movers. A tape built from it cannot serve a brief about
today's movers, and it did not: on the 2026-11-10 fire the 08:30 checkpoint carried **49 rows**
and covered **6 of the 50 names the brief published**; on 2026-11-12 it covered **21 of 693**
screen names (3.0%) and **9 of 21** actionable names.

So the candidates come from the **TradingView scanner's pre-market band** — every US stock
trading more than **±2.5%** pre-market, pulled in **two DISJOINT halves** (the gainers sorted
descending and the decliners sorted ascending, so a name cannot be in both and no record can
hold two prices). The band IS today's tape.

Measured on 2026-11-13 at 07:57 ET: the band held **458 names** (271 up / 187 down) and the
tape carries **130 priced rows** — against 47 rows before. The band is the same width as the
historical "±2.5% movers-sorted snapshot" (849 rows on 2026-11-06), so a tape of 200–900 rows
is normal and only a tape under ~120 rows is a regression signature.

**THE QUOTE FLOOR: a pre-market print of fewer than 25,000 SHARES is not on the tape.**
That is the same number, and the same instrument, as cron #25's fourth gate leg — one rule
across the fleet: below 25,000 pre-market shares is a quote, not a market. It is a SHARE count
and not a dollar notional because a share count is monotone in time (a name that printed
25,000 shares by 08:30 has printed more by 09:22) while a notional floor is not (the price can
fall under it), and because a notional floor deletes real movers: measured on 2026-11-13 a
$100K-notional floor kept 72 of 458 band names and DROPPED **CRIS (-10.6% on 39,053 shares)**
— a real mover on a cheap share, and one of the names cron #25 has to publish.

**Both directions are mandatory.** The gainers and losers halves are DISJOINT (a name cannot be
both a top gainer and a top loser), so merging them can never put two prices on one record.
A gainers-only scan is not a pre-open tape: measured 2026-11-09 it missed IRTC -30.7%,
DKNG -21.3% and AXON -18.2% — the day's three worst decliners. The grounded-call budget is
spent on the biggest movers by |%|, so a decliner competes with a gainer for its catalyst.

**Prices come from the SCANNER, not from the movers scan — and this is not optional.**
`top_movers` is Yahoo's predefined screener over the LAST COMPLETED REGULAR SESSION, so
before the open it returns YESTERDAY's movers carrying YESTERDAY's closes. Measured on the
2026-11-09 08:30 tape, 14 of 14 testable priced rows were exactly the previous session's
close and move (IRTC -30.70% at 90.22, from 130.19 on Nov 5 to 90.22 on Nov 6), while
TradingView's own pre-market for IRTC that morning was +0.86% at 91.00. The tape was
publishing Friday's move as if it were Monday's pre-market.

So the **band** decides WHICH names are on the tape, and the scanner supplies the NUMBER that
belongs to the session the tape is about (the band rows are priced by the pull that chose
them; the few names the band did not cover are priced by a second scanner call). The movers
scan still contributes the names that have not moved yet. Two rules follow:
  * A name the scanner does not carry has **no pre-market print**. It keeps `pct`/`price`
    NULL and is published as a narrative row (`src: stocktwits`) — it did not trade
    pre-market, and the tape must not invent a number for it.
  * The grounded-call budget is spent on the biggest movers by **this session's** |%|.
    Ranked by the movers scan's move, the budget would buy catalysts for yesterday's
    movers and today's would never get one.

**Prices are never taken from the narrative calls.** The script also drops a grounded answer
that merely restates the price move, and drops one whose source was a filing index rather than
news — a name with no findable catalyst is left with no catalyst, which is the honest result.

**THE CATALYST PIPELINE — ARTICLE FIRST, THEN EDGAR, THEN THE ROUTER, ALL IN PARALLEL**

**The article feed goes FIRST.** It costs **0.21–0.24 s** per name and it answers directly,
with the publication stamp and the article URL; the router costs **15 s** when it answers and
**21 s** when it *refuses*. Measured 2026-11-13 at 22:49 ET on 8 large names: the direct feed
returned a dated article for **6 of 8**, while the router's own polygon path returned
`tool_error` on **4 of the same 8**. The router is 60–100× more expensive and less reliable
at the one thing it cannot do — say WHEN.

**SEC EDGAR IS THE SOURCE OF RECORD, AND IT SITS BETWEEN THE FEED AND THE ROUTER
(2026-11-17).** The news vendor's TICKER INDEX is the capture's only news path, and for a
nano-cap it is a hole. Measured 2026-11-17 on the thirteen movers the 2026-11-16
checkpoints could not explain: **eight of them have ZERO articles in the index ever**,
and the other five hold articles from 2024–2026-07 — **ZERO of the thirteen had an
in-window article**. The provider cannot cover this population, so the coverage floor
could not be cleared however the budget was spent.

EDGAR is free, dated and checkable: `company_tickers.json` maps a ticker to its CIK
(one fetch, cached per run), the full-text search endpoint queried **by CIK and by date**
returns the issuer's own filings with their filing date, form type and — for an 8-K —
the **ITEM NUMBERS**, which are a classification in themselves (1.01 material definitive
agreement, 2.02 results of operations, 3.01 failure to satisfy a continued listing rule,
3.02 unregistered sale of equity, 4.02 non-reliance on previously issued financials,
7.01 Regulation FD, usually a press release), and the filing's **EX-99.1 exhibit is the
press release**, whose first line is the catalyst headline.

**MEASURED YIELD on the same thirteen: EIGHT have a catalyst-bearing filing inside the
window, and the items ARE the causes** — DVLT 8-K item 3.01 on 2026-11-13 (*"Datavault
AI Receives Notice of Nasdaq Trading Suspension"*), CGON 8-K item 7.01 on 2026-11-16
(*"PIVOT-006 Phase 3 Registrational Trial Demonstrates Unprecedented Improvement in
Recurrence-Free Survival"*), LXEO 8-K item 2.02 on 2026-11-16, SHFS 8-K items 1.01 +
3.02 on 2026-11-12.

**WHAT EDGAR DOES NOT COVER: a press release that was never FILED.** GMM's Nov-16
Anthropic announcement was a GlobeNewswire release with no filing, and the vendor's
index does not hold it either — so GMM stays unexplained, which is the honest result.
EDGAR covers FILINGS; the vendor covers what it covers; a release that reaches neither
is a name with no findable cause.

**THE CATALYST IS THE ARTICLE'S TICKER-SCOPED INSIGHT, NOT ITS HEADLINE.** Every article
carries `insights`: a per-ticker entry with a `sentiment` and a one-clause
`sentiment_reasoning`. THAT entry is the catalyst. Measured 2026-11-13 23:14 ET: the newest
headline for **SST (System1, −38.92 %)** was *"NIQ Global Intelligence plc (NIQ) Q3 Earnings
and Revenues Surpass Estimates"* — a story about a **different company**, and a **positive** one,
on a row that fell 39 %. The provider tags that article to both tickers, so the article's
`tickers` list does **not** exclude it; but its `insights` carry a separate entry per ticker,
and the SST entry reads *"Expected to post a quarterly loss of $1.30 per share with a 43.5 %
year-over-year deterioration, and revenues projected to decline 50.7 % from the year-ago
quarter"* — at `sentiment: negative`, which is the direction of the move. The insight is the
ticker-scoped, direction-scoped explanation; the headline is neither. The insight is matched
**exactly**, so a `SST.WS` warrant entry cannot pass for `SST`.

**AND THE DIRECTION COMES FROM THE PROVIDER, NOT FROM A WORD LIST.** The `sentiment` field is
the provider's own judgement of that ticker, which is exact; a direction-word probe over prose
is a guess. So a row that carries a sentiment is judged by it, and the word probe is the
fallback for a router or a chatter catalyst that carries none.

So the pipeline is: **one article fetch per name in contention** → if the provider holds an
**in-window** article, that article's TITLE is the catalyst (dated, with its URL) and the
router is never called; only a name the feed **could not date** spends a router call. The
article that is published is the provider's **newest** one, so its stamp IS the provider's
freshest stamp — the ARWR/NOVT defect (a months-old article matched by text and published as
today's news) **cannot arise from this path at all**.

**Both phases run in parallel.** Measured 2026-11-13: 8 concurrent grounded calls in
**20.19 s** against **101.77 s** serial — 5.0× — with no rate limiting and no HTTP failure.
The sequential grounded calls had been ~264 s of the capture's 270 s: **98 % of the capture's
wall clock**, while the four feed calls took 2.6 s.

**THE RETRY BELONGS ON THE CHEAP LEG (2026-11-17).** The router's failure is INTERMITTENT and
the call is cheap; the feed's failure is the same and the call is metered at 200 credits.
Measured 2026-11-17 on the eight largest movers the 2026-11-16 08:30 checkpoint could not
explain, calling the router **one at a time**: it answered **4 of 5** calls for AKAN
(confidence 0.85–0.95) and **3 of 5** for GP (0.95) — while the same names, fired eight-wide
concurrently, were refused **7 of 8**. So the capability was there and the capture never used
it: `call_grounded` made exactly **ONE** call, and the 200-credit article feed was retried
**three** times. A name the feed could not date therefore had one chance at a $0.02 answer and
three chances at an index lookup that, for a nano-cap, answers with articles from 2024.

The capture now asks the router **three times** (`ROUTER_ATTEMPTS`), with backoff, and retries
**only the transport class** — a call that produced no usable answer (a tool error, a
refusal, an empty answer). A call that **did** answer is never asked again: if the capture's
own filters then blank that answer (it restates the price move, it is a filing-index entry,
its confidence is under 0.6), that is a quality decision, and asking again until one passes
would be fishing.

**AND THE ARTICLE FEED STOPS EARLY ON A REPEATED ERROR.** Two consecutive **identical** feed
errors are a dead index, not a blip — measured 2026-11-17: DVLT's feed answered `tool_error`
on 4 of 4 calls and a bare empty result on a fifth. The third metered attempt is spent only
when the error **changed**, so a persistent failure costs two calls instead of three and a
recovering one still gets its third chance.

**THE ROUTER'S FAILURES ARE COUNTED (2026-11-17).** They used to be invisible: a name the
router refused recorded the *article's* error, so the 2026-11-16 08:30 checkpoint — 10 article
errors and **13** router refusals — reported one distinct provider error, and thirteen
published movers lost their explanations to a provider hiccup while the reply's `errors:`
number did not move. The two legs now report separately (`article_errors=` and
`router_errors=`), and both enter the errors ledger, so a degraded run can name **which leg**
failed.

**THE CONFIDENCE TOKEN now means something.** `high`/`medium` is reserved for a catalyst that
is **DATED, in-window and checkable**; a retail-chatter reason — no publication stamp, no
article behind it — can never earn more than `low`. Measured on the 2026-11-12 tape: **10 of
the 12 `high` rows were chatter**, undated and uncheckable, while only 2 were dated grounded
catalysts. The old rule (`conf` was `high` whenever the row carried any reason at all) is
why.

**A CREDIT FAILURE IS NOT "NO NEWS".** The gateway answers an exhausted account with *"Insufficient
credits. This tool costs 200 credits"* — and to a caller that cannot tell that from an empty
result it looks exactly like a quiet news day. Measured 2026-11-13 23:40 ET, every pack
answered that way after the balance ran out mid-run: the tape published 193 rows with **no
catalysts at all** and would have reported **no error**. So the capture recognises the credit
failure, does not retry it, and **reports it** (`article_errors=`, `provider_errors=`,
`errors=`). A quiet tape with a loud error beats a loud-looking tape with a silent one.

**THE PROVIDER SPEND IS BOUNDED.** The pool of names put in contention for a cause **is** the
budget (`--top`), not twice it: every article call is a metered provider call (200 credits,
measured 2026-11-13) and the wallet is finite.

**THE SIGN PROBE.** A cause that points the **other way** from the move is not an explanation
of that move. The capture compares the catalyst's direction with the sign of the move; a row
that contradicts is demoted to `low` and flagged `sign_conflict: true` (the board marks it
`low ⚠`). With a provider sentiment the comparison is exact; otherwise it is a direction-word
probe, and that one reads only the text **before** the hedge clause (*"… though some question
whether backlog can convert"*), because the negative words in a debate belong to the bears and
not to the cause, and it stays silent unless the move is material (|%| ≥ 2.5 %). Measured
against every catalyst on the 2026-11-12 and 2026-11-13 tapes, the probe flags exactly the
rows whose published cause does not explain the move — DGII −20.50 % on *"beat Q4 2026
earnings expectations"*, GLW −5.93 % on *"strong Q3 results"*, ONDS −5.41 % on *"stronger
revenue outlook"* — and nothing else.

**A ROW WITH NEITHER A NUMBER NOR A CAUSE IS NOT A ROW** and is not published. Measured on the
2026-11-12 tape: 11 of its 45 rows were exactly this.

**`pm_notional`** — the pre-market dollar notional behind each print (shares × price) — rides
on every priced row, so a consumer can tell a real mover from a thin one. Measured on the
2026-11-13 tape: of the board's 15 rows, 10 sat on under $3M of pre-market notional.

## THE CATALYST IS DATED, AND AGE-CHECKED

A catalyst without a date is a claim with nothing behind it. Measured on the 2026-11-09 09:50
checkpoint, **ARWR (-16.59%)** carried Arrowhead's **2026-01-06** press release — *"announced
significant positive interim trial results … with stock surging 17.81% to a new 52-week
high"*, a story about the opposite move from ten months earlier — at `conf: high`, and the
board printed `09:53:48` in its **When it broke** column, because that column fell back to the
CAPTURE clock. The board therefore told a trader, in the one column that exists to date the
catalyst, that a January press release broke forty minutes ago.

So the tape now carries, on every row:

- `news_date` — the article's `published_utc` (ISO-8601), or null when no date could be
  resolved.
- `news_url` — the article the catalyst came from, so the claim can be checked.

and the capture applies two rules:

1. **STALE ⇒ DROPPED.** If the newest dated article the provider holds for that company is
   older than `CATALYST_MAX_AGE_DAYS` (four days — a Monday board still has to reach Friday's
   and the weekend's news), the catalyst is removed: `why` goes to null, the row reverts to
   `src: scanner` (its price, and nothing else) and the name is counted in the run's
   `stale_dropped=` figure. A cause that cannot be today's news is not a cause.
2. **UNDATED ⇒ DEMOTED, NOT DROPPED.** If no date could be resolved at all, the catalyst is
   kept but demoted to `conf: low` with `news_date: null`. An undated cause is a weaker
   claim, not a false one.
3. **A MATCH OUTSIDE THE WINDOW ⇒ THE STAMP IS DROPPED, THE CAUSE IS KEPT.** Rule 1 asks the
   provider for its NEWEST dated article and rule 2 asks whether ANY date resolved, but the
   tape publishes a third thing: the date of the article the answer TEXTUALLY matched. That
   match can land on a months-old article from the same company while the provider holds a
   fresh one — measured 2026-11-11 08:30 ET, NOVT carried a catalyst dated **2026-02-22**
   (262 days old) because the match picked that article, even though Novanta's feed held
   something newer. A published stamp outside the window is a cause dated to the wrong year,
   so the stamp (and its URL) is dropped and the row is demoted to `conf: low` with
   `news_date: null`; the cause itself survives, because the provider's fresh article makes
   it plausible. Never publish a `news_date` the checker would reject: `tools/check_preopen_checkpoint.py`
   asserts that no row's date is outside `CATALYST_MAX_AGE_DAYS`.

The gate reads the provider's newest article for the name rather than the article that best
matches the answer, because the router reads the same provider: if the newest thing it holds
for a name is old, the router cannot have found anything newer, however confident it sounds.

**Cost.** Call 5 is one provider call per grounded name (the same provider the grounded
router already calls internally), so the marginal cost is one extra article fetch per
catalyst — a few cents per checkpoint. The router alone is not enough: it returns a
summary with no date and no URL, which is exactly what makes the defect invisible.

**The board's "When it broke" now reads `news_date`, then the trending snapshot's own stamp,
and otherwise prints an em-dash.** It never falls back to the capture clock — that is the
clock when the script ran, not when the news broke. `tools/check_preopen_checkpoint.py`
enforces all of this, and the ARWR row is itself a fault-injection case in
`tools/test_preopen_checkpoint_contract.py`.

**A DATE-ONLY CATALYST IS PUBLISHED AS A DATE (2026-11-17.3).** EDGAR hands back a
**filing date** with no time on it — `2026-11-16` — and the renderer formatted every stamp
as a clock time, so a filing dated the day before the capture printed **`00:00:00`**: a
bare midnight that reads like an intraday print and carries no date at all. Measured on the
2026-11-17 08:30 board: **6 of the 9 dated catalysts** rendered `00:00:00`, and on three of
them (FRTT, FGL, GLAS) there was **no date anywhere on the row** — so a reader could not
tell whether the news broke today or yesterday. The column's whole job is WHEN, and the
tape's WHEN is a filing date.

So the renderer prints a date-only value **as the date**, and a full timestamp still prints
as the ET wall clock. The board carries a **`preopen-dates-v1`** contract marker, and
`tools/check_preopen_checkpoint.py` enforces it: a board published on or after **2026-11-17**
must carry the marker, and no row on it may print a date-only catalyst as a bare clock
time. A board published **before** that date is **GRANDFATHERED** — it was written under
the old rule and is not failed by a rule it never saw.

**xAI/Grok is NOT used.** The xAI chat API no longer serves live search (`search_parameters`
returns HTTP 410, "Live search is deprecated") and the Agent Tools API that replaces it is not
enabled on most keys. Pipeworx does the job on its own. If `XAI_API_KEY` is present it is
ignored, not used as a fallback. The measured Grok cost is therefore **$0.0000**.

The tape's `src` field is the row's PROVENANCE, not a vendor: `scanner` = the movers scan gave
this row its price; `pipeworx` = the grounded router gave this row its catalyst; `stocktwits` =
a narrative row with no ground truth.

## THE MOVER COVERAGE FLOOR — THE MOVERS THE BOARD PUBLISHES MUST BE EXPLAINED

The tape's whole job is **WHO / WHAT / WHEN** for every name materially moving pre-market. On
Friday 2026-11-13 it priced the movers and explained almost none of them, and **not one word
of the artifact or of the reply said so**:

| Checkpoint | Records | With a catalyst | Whole-tape coverage (CONTEXT) | **Published movers explained (GATED)** |
|---|---|---|---|---|
| 2026-11-13 08:30 | 164 | 16 | 16/164 (10%) | **4/15 (27%)** |
| 2026-11-13 09:50 | 218 | 20 | 20/218 (9%) | **6/15 (40%)** |

LFTO (+25.07% on a Q3 beat) and SBC (+9.6% on a Q3 print and an 8-K) sat on the 08:30 tape
with `cat: "other"`, `why: null`, `conf: "low"` and `news_date: null` — two names that needed
an explanation most, carrying none.

**A tape that is 90% unexplained reads exactly like a tape that found no news**, and that is a
SILENT failure. The fleet's own rule is that a degraded run must say it degraded; this run
did not, because nothing measured it.

### THE MEASUREMENT — THE READER-FACING ONE

```
mover_coverage = (published movers carrying a catalyst) / (published movers)
```

The **published movers** are the rows of the digest's **top-movers table** — the 15 rows the
board publishes, ranked by |%| — that carry a pre-market price. That is the table the reader
actually reads before the open, and it is the coverage they experience. A row with no price is
a catalyst without a move (the board sorts it last by design and says so in its own footer),
so it is not a mover and it is not in the denominator.

**The WHOLE-TAPE coverage is still measured and published, as CONTEXT.** It says how much of a
130–220 row band was explained — a fact about the band's width. It is **NOT** the gated number,
and the board labels it as context so the two can never be confused.

### THE FLOOR: 30% OF THE PUBLISHED MOVERS

`MOVER_COVERAGE_FLOOR = 0.30` — at least a third of the movers on the board must carry a cause.

**The arithmetic, so the floor's reachability is obvious and checkable:**

```
a 15-row movers table needs ceil(0.30 x 15) = 5 explained movers
  4/15 = 26.7%  -> BELOW the floor
  5/15 = 33.3%  -> CLEARS the floor
```

**Why the floor is REACHABLE.** The catalyst pool **is** the budget (`--top 20`, step 2) and the
pool is ranked by |%| — the same ranking the table is published in — so the pool (20) is
**wider** than the table (15). A run whose budget lands on the movers the board publishes can
explain up to 15 of them, and **8 of 15 clears the floor with room to spare**.

**Measured against the real thing.** On 2026-11-13 the two checkpoints came in at **4/15
(27%)** and **6/15 (40%)** — the floor sits BETWEEN them. That is where a floor belongs: it
fires when the provider answered for too few of the movers the board shows, and it stays
quiet when it answered for enough of them. A floor set above the measured answer rate (a
draft proposed 50%) fires on every checkpoint, and a label that is always on is a label the
reader learns to skip. A gate that
can never be cleared is not a gate: it is a ratchet, and a ratchet that fires on every
checkpoint trains the reader to ignore the label.

**Why the previous floor was wrong.** The 2026-11-13 floor gated the WHOLE TAPE at 40%: on a
164-row tape that needs **66 explained rows**, while the pool can supply at most ~20. It could
never be cleared, so **every** checkpoint would have been labelled DEGRADED, forever — alarm
fatigue, and a label the reader learns to skip.

**Read the arithmetic before the verdict.** On Friday the budget was already spent on the
movers the board publishes — the pool is the top 20 by |%| and the table is the top 15 — and
still only 4 of 15 (08:30) and 6 of 15 (09:50) came back with a cause, because the provider
held no in-window article for the rest and the router refused them. So Friday's failure is a
**provider-answer** failure, not a budget failure, and the board now says exactly that:
"4 of the 15 movers on this board carry a cause". Widening the catalyst pool is a **SPEND
DECISION for the fleet** (every article call is metered — 200 credits, measured 2026-11-13)
and it was **not taken**; the floor's job is to make the gap LOUD, not to spend the wallet.

### WHAT THE FLOOR DOES — AND WHAT IT NEVER DOES

**THE FLOOR NEVER SUPPRESSES THE CHECKPOINT.** The tape and the board are written either way.
The floor changes how the result is **LABELLED**, never whether it is produced. A capture that
FAILED is a different failure and keeps its own path (the errors ledger, the credit
recogniser, the skip marker).

When the mover coverage falls below the floor:

1. **the board says so, in the file a reader opens** — a `DEGRADED` banner above the table, in
   plain words (*the movers on this board are priced but unexplained*), naming the CAUSE (the
   grounded catalyst call did not explain them) and listing the **unexplained movers it
   publishes**;
2. **the reply says so** — a `degraded:` line naming it;
3. **the checkpoint's `errors:` count goes up by ONE** for it. The capture already counts the
   degradation in its OWN ledger (`errors=`), so the reply's number is measured, never
   remembered — and the degradation is never counted twice.

**IF THE BOARD PUBLISHES NO MOVERS TABLE, THE METRIC IS UNDEFINED.** A checkpoint that cannot
show an explained mover cannot claim coverage, so it is DEGRADED:
`mover coverage: n/a — the digest published no movers table`.

### THE LABELS (exact)

In the board's header block, next to the record count and the provenance split — the marker on
its own line (the house pattern, cron #17's `**Contract:**`), the gated measurement on the
next, and the whole-tape number on the line after that, clearly marked as context:

```
- **Coverage contract:** `preopen-coverage-v2`
- **mover coverage:** 4/15 (27%) · **floor:** 30% · **BELOW FLOOR** · published movers: 15 (8 up / 7 down)
- **catalyst coverage (whole tape):** 16/164 (10%) · **unexplained:** 148 records (138 price-only · 10 narrative-only) · CONTEXT ONLY — not the gated number
- **Size split of the published movers:** ≥$50M cap: 2/3 explained · <$50M cap: 2/12 explained · CONTEXT — a micro-cap-dominated board publishes the movers no news vendor indexes
```

and, only when the mover coverage is below the floor, the banner above the table:

```
> ⚠ **DEGRADED — mover coverage 27% is below the 30% floor.** The movers on this board are priced but unexplained: the catalyst pipeline could not resolve a dated cause for them. **11 of the 15 published movers carry no cause at all** — read those names as MOVERS, not as explained moves.
> **Cause:** the catalyst pool is sized to cover every mover this board publishes, so this is NOT a budget shortfall — the news provider held no in-window article for these names, and the grounded router could not date a cause for them either. The tape is complete; the EXPLANATION is not.
```

**THE BANNER MUST NOT BLAME THE BUDGET (2026-11-17).** It used to say *"the catalyst budget
did not reach them"*, and that was **false**: the pool is sized to cover every mover the board
publishes (the pool is the top N by |%|, the table is the top 15 of the same ranking), and on
2026-11-16 all fifteen had a router call. The real cause is the provider's **ticker index**:
measured 2026-11-17, it held NO in-window article for any of the 13 movers the board could not
explain — eight had zero articles ever, and AKAN's newest was from 2024. A board that names
the wrong cause sends the reader looking for a budget problem that does not exist.

**THE SIZE SPLIT IS CONTEXT, AND IT FAILS SOFT.** The board pulls the published movers'
market caps from the SAME scanner that priced them (one POST, `market_cap_basic`) and
publishes the explained/ published split at the $50M cut. It is CONTEXT, not a gate; and if the
pull fails the board says `unavailable (the market-cap pull failed)` rather than inventing a
split. **THE TAPE'S ROW SHAPE IS UNCHANGED** — this is a dimension the board adds, not a field
the tape grows, so cron #17's consumer is untouched and the board still cannot disagree with
the data cron #17 reads at 15:50.

The unexplained movers are listed in the header too, so a reader can look up the tickers the
board publishes and did not explain:

```
- **Unexplained movers in the published table (a price, no catalyst captured):** 11 of 15 published movers — ZBAO, OGEN, MRLN, …
```

In the reply, one line, ALWAYS:

```
mover coverage: 4/15 (27%) · floor 30% · BELOW FLOOR
```

the whole-tape context on the next line:

```
catalyst coverage (whole tape): 16/164 (10%)
```

and, only when the mover coverage is below the floor, one more line:

```
degraded: mover coverage 27% is below the 30% floor — 11 of the 15 published movers carry no cause; the movers this board publishes are priced but unexplained
```

At or above the floor the line reads `mover coverage: 8/15 (53%) · floor 30% · OK`, there
is NO `degraded:` line, and the error count does not move.

### THE FLOOR DOES NOT RETRO-FIRE

A digest published before this rule existed is not failed for it. The board carries a **coverage
contract marker** (`preopen-coverage-v2`), and a board that carries NO marker and predates the
floor's effective date — **2026-11-16**, the first checkpoint under the floor — is
**GRANDFATHERED**: it is checked against the rules in force when it was written. A board dated
on or after the effective date MUST carry the marker and the coverage line — otherwise the
checker fails it, because a board that quietly stopped publishing its coverage is exactly the
silent failure this rule exists to stop. A board carrying the **previous** marker
(`preopen-coverage-v1`, the whole-tape floor) and published on or after the effective date is
NOT grandfathered either: it must publish the current metric.

## REPLY

Under 6 lines: the checkpoint, the number of records written, the **mover coverage** line,
one line for push status, one line for `errors: <n>`. **EIGHT lines when the mover coverage is
below the floor** — the whole-tape context line and the `degraded:` line are not optional, and
the floor is not a footnote.

**A SKIPPED CHECKPOINT HAS ITS OWN REPLY (2026-11-26).** If the window check declined the
fire, or the capture exited 3 (the market is closed), there is no tape, no board, no
coverage and no digest — so the reply says so, names the marker, and counts **no error**
(a deliberate skip is not a failed capture). Both shapes are spelled out in step 0:

**A SKIP FROM THE ANCHOR GUARD NAMES THE PROBE'S EVIDENCE (2026-11-28).** The capture's
reason now ends with the roll probe's own numbers — *"the roll probe confirms it: 0/60
sampled names moved in 45s, and a settled close does not move"* — because the difference
between "the market is shut" and "the regular session is already open" is exactly what
that measurement decides. **A skip that names the probe is a DELIBERATE one**; a skip that
does not (an older capture, or the window check) is the same shape it always was.

```
checkpoint: 2026-11-26 0830 — SKIPPED, no tape (the window check declined this fire)
records written: 0 — no tape; digest: none (preopen-feed/2026-11-26-0830.md is intentionally absent)
mover coverage: n/a — no movers table published; catalyst coverage (whole tape): n/a
halt state: not measurable (no rows)
push: marker pushed (refs/skipped-markers/2026-11-26_SKIPPED_preopen_catalyst_capture_0830.md)
errors: 0 — a deliberate skip is not a failed capture
```

**A PUBLISHED CHECKPOINT MAY ALSO NAME ITS ANCHOR.** The capture prints
`anchor=<matched>/<checked>` — the priced rows whose move agrees with the close the
scanner published alongside it. It is the number that turns "the tape's moves" into "the
tape's moves, VERIFIED against the scanner's own close", and it belongs on the push line
when it is not 100%. A healthy live session measures ~100% (measured 2026-11-25: 14/14);
a stale anchor measured 11% — and that run wrote no tape at all.

**AND IT NAMES THE MODE (2026-11-28).** The capture also prints `anchor_mode=` — `aligned`
before the open, `rolled` after it — and `roll=<live>/<checked>`, the probe's own count.
**Read the mode before reading the ratio:** after the open the ratio is EXPECTED to be
low (the scanner's `close` is a live price, not the previous close), and a low ratio on a
`rolled` tape is the rule working, not the guard failing. On an `aligned` tape the ratio
is the verification. The board carries the same thing as an **Anchor:** line, and the tape
carries `ref_mode` and `ref_scanner_close` on every priced row.

**THE MOVER COVERAGE LINE REPLACES THE OLD "how many movers carry a catalyst" LINE.** It
carries the same count and the arithmetic around it, so it is the same line with the
measurement attached:

- `mover coverage: 4/15 (27%) · floor 30% · BELOW FLOOR` — the `4` is the number of the
  **published movers** that carry a cause, the `15` is the number of movers the board
  publishes, and the floor is 30%.
- `mover coverage: 8/15 (53%) · floor 30% · OK` — at or above the floor.

The whole-tape number travels on its own line, as context:

- `catalyst coverage (whole tape): 16/164 (10%)` — the band's coverage. It is NOT the gate.

**Read the coverage from the BOARD, not from the capture's stdout.** The board is rendered
FROM the tape, so it is the same measurement over the same rows; the capture's stdout carries
the same numbers plus the budget (`pool=`), which is what you need to name the CAUSE.

**When the mover coverage is below the floor, the reply says so in plain words and the error
count goes up by ONE.** The capture already counted the degradation in its own ledger
(`errors=`), so the number in the reply is the capture's `errors=` plus any stall error —
never plus a second copy of the degradation:

- `degraded: mover coverage 27% is below the 30% floor — 11 of the 15 published movers carry no cause; the movers this board publishes are priced but unexplained`
- Name the budget too when the capture printed it: `pool=20` is the size of the catalyst
  budget, and the capture's `mover_coverage=4/15` is the number of those movers the provider
  answered for. A degradation with no cause named is half a finding.

**The push line carries the DELIVERY LATENCY, and a platform stall counts in `errors:`.** The
platform's run record measures the DISPATCH of the prompt to the agent (~1 s), not the work: on
2026-11-05 cron #26b's run record closed in 1.008 s with `status: 1` and its first tool call
did not execute until 49.8 minutes later. `window_check.sh` prints `stall_min:` — the platform's
delay before the turn actually started — and the window check is the first action, so read it.

- `push: ok (verified) — delivered 10:15 ET, 55 min after the 09:20 fire` — the latency is the
  wall clock at the push minus this routine's own scheduled fire time.
- `stall_min` over 5 ⇒ the fire was BLOCKED. Count ONE error for it and add a `stalled:` line.
  To name the cause, read your OWN session's previous turn (`session_messages` on your own
  session id) and quote the error it ended on — e.g.
  `42212: Token Plan usage limit reached … (2056)` — or say
  `stalled: the fire was blocked <n> min before its first tool call (no error recorded)`.
  `errors: 0` on a stalled fire is a lie: the artifact may be perfect and the schedule was not.

**The halt state is `not measurable`** — the `halted` column is null on every row, so never
publish a halt count, and never publish `0`.
