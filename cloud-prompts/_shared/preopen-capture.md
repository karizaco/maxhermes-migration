# Cloud Mavis cron: preopen-catalyst-capture (cron #92)
<!-- PROCEDURE_VERSION: 2026-11-06.2 -->

Runs three times per session-day (08:30, 09:20, 09:50 ET). Writes an append-only **catalyst
tape** that cron #17 (`us-stocks-in-play`, 15:50 ET) reads to explain *why* a stock moved and
*when* the news broke — the thing no price feed can tell you.

Every checkpoint also writes a **human-readable digest** beside its tape. The tape is JSONL and
is read by a machine; the 08:30 checkpoint is the one a trader can act on before the open.

## WHAT THIS IS FOR

At 15:50 the digest can see where a stock IS. It cannot see where it came from, and — this is the
gap — **it cannot see the catalyst as it was understood at the open.** By 15:50 the wire has moved
on: the 09:12 headline is buried, and a name that gapped +12% on an FDA approval and now trades
+2% looks identical to one that never moved.

This routine records the tape while it is still happening.

## OUTPUT

Three files per checkpoint, all in `preopen-feed/` in `karizaco/minimax-cloud-outputs`, branch
`main`, where `{HHMM}` is the FIRE's scheduled ET slot:

| File | What it is | When |
|---|---|---|
| `{date}-{HHMM}.jsonl` | the tape — append-only, one JSON object per line | every successful checkpoint |
| `{date}-{HHMM}.md` | the digest — the top movers a human can read | every successful checkpoint |
| `{date}-{HHMM}.SKIPPED.md` | the trail a fail-closed checkpoint leaves behind | when the key is unset |

The JSONL row shape is a **contract with cron #17** (it merges on it) — ten keys, unchanged:

```json
{"ts":"2026-11-03T09:15:23-04:00","src":"grok","ticker":"BRZE","name":"Braze",
 "pct":51.2,"price":45.40,"cat":"acquisition","why":"Salesforce to acquire for $47.50/sh cash",
 "ref":"https://…","conf":"high"}
```

`cat` vocabulary: `acquisition | merger | earnings | guidance | fda | trial | offering | halt |
downgrade | guidance-cut | spin | dividend | other`.

## STEPS — execute IN ORDER

### 0. Fetch the checkpoint script (FIRST — it does the merge, the digest and the marker)

The merge, the digest and the skip marker are CODE, not prose. Three rules are easy to state and
easy to break by hand (one snapshot per record; prices never from Grok; one row per ticker), so
they live in one script that every checkpoint runs.

```bash
S=/workspace/preopen_checkpoint.py
for U in \
  "https://api.github.com/repos/karizaco/maxhermes-migration/contents/cloud-prompts/_shared/preopen_checkpoint.py?ref=main" \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/preopen_checkpoint.py" \
  "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/preopen_checkpoint.py" ; do
  curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" -o "$S.tmp" "$U" 2>/dev/null
  # The capability marker AND the script version are what decide, NOT the byte count:
  # a 404 body is non-empty JSON, and an OLD copy of this script has no marker. The
  # version is demanded TOO, because a marker alone cannot detect a stale copy that
  # already carries it (measured 2026-11-05: every mirror served the same stale blob
  # and "highest version wins" picked it).
  if [ -s "$S.tmp" ] && grep -q 'PREOPEN_CHECKPOINT_V1' "$S.tmp" 2>/dev/null \
     && grep -q 'CHECKPOINT_SCRIPT_VERSION: 2026-11-06.1' "$S.tmp" 2>/dev/null; then
    mv -f "$S.tmp" "$S"; break
  fi
  rm -f "$S.tmp"
done
if [ ! -s "$S" ] || ! grep -q 'PREOPEN_CHECKPOINT_V1' "$S" 2>/dev/null \
   || ! grep -q 'CHECKPOINT_SCRIPT_VERSION: 2026-11-06.1' "$S" 2>/dev/null; then
  echo "preopen checkpoint: UNAVAILABLE (no copy carrying PREOPEN_CHECKPOINT_V1 + version 2026-11-06.1)"
  echo "no tape; no digest; report probe_failed:checkpoint_script"
  exit 1
fi
```

If that fetch fails, report `probe_failed:checkpoint_script` and write NOTHING. Never improvise
the merge from memory — the merge is what enforces the no-splice and no-Grok-price rules.

### 1. Key check (FIRST)

```bash
if [ -z "${XAI_API_KEY:-}" ]; then
  echo "preopen capture: XAI_API_KEY unset — no tape, writing the skip marker"
fi
```

**If the key is unset, write NO tape — but leave a trail.** A tape with no catalyst in it is
worse than no tape, because the consumer would report "no catalyst" for a name that had one. But
*silence* is worse still: on 2026-11-03 the checkpoint wrote nothing, cron #90 reported the
absence with an empty reason, and cron #17 had to reconstruct the cause from its own provenance
table. So a fail-closed checkpoint writes a marker naming the reason:

```bash
# (only when XAI_API_KEY is unset; requires DATE and CP from step 2)
python3 /workspace/preopen_checkpoint.py skipped \
  --out "/workspace/preopen-feed/${DATE}-${CP}.SKIPPED.md" \
  --reason "XAI_API_KEY is unset — the Grok catalyst half could not run, so no tape was written" \
  --date "$DATE" --slot "$CP" --fire-instant "$FIRE_INSTANT"
```

Then push the marker (§6, `SKIPPED` variant) and reply `preopen capture: XAI_API_KEY unset —
no tape; skip marker pushed`. **No JSONL is written in this path.**

### 2. Resolve the FIRE's instant, then the date and the checkpoint slot

**Resolve the fire's scheduled instant FIRST, then derive the date and the checkpoint slot from
it — never from the wall clock.** The platform resumes a crashed cron conversation IN PLACE, so
"now" can be hours or days after the fire; and a fire that runs late must still be named for the
slot it was dispatched for.

```
mcp_invoke  tool_name=session_get  arguments={"session_id":"me"}
```

Take `session.created_at` (epoch milliseconds) — that is the instant the platform dispatched THIS
fire. Then:

```bash
export FIRE_MS=<session.created_at from the call above>
export DATE=$(TZ=America/New_York date -d "@$((FIRE_MS/1000))" +%Y-%m-%d)   # the FIRE's date
export TS=$(TZ=America/New_York date +%Y-%m-%dT%H:%M:%S%:z)                 # the CAPTURE time
export FIRE_INSTANT=$(TZ=America/New_York date -d "@$((FIRE_MS/1000))" +%Y-%m-%dT%H:%M:%S%:z)
```

`DATE` is the fire's date; `TS` is the real capture time, because the `ts` field says when the
tape was actually taken. If `session_get` cannot be reached, STOP and report
`probe_failed:fire_instant` — do not fall back to the wall clock.

**The checkpoint slot comes from the SCHEDULED instant, and it is ASSERTED.** The consumer merges
the checkpoints by slot name, so only `0830`, `0920` and `0950` are real filenames. A literal
`date +%H%M` on a fire that executes at 08:35 names its tape `0835` — a phantom slot the
consumer never reads, so the 08:30 tape silently disappears from the merge.

```bash
# The checkpoint slot comes from the FIRE'S SCHEDULED INSTANT, never from the wall clock.
ALLOWED="0830 0920 0950"
CP_RAW=$(TZ=America/New_York date -d "@$((FIRE_MS/1000))" +%H%M)
_mins() { awk -v t="$1" 'BEGIN{printf "%d", substr(t,1,2)*60 + substr(t,3,2)}'; }
CP=""
for s in $ALLOWED; do
  if [ "$s" = "$CP_RAW" ] || [ "$s" \< "$CP_RAW" ]; then CP="$s"; fi   # greatest slot <= instant
done
if [ -z "$CP" ]; then
  for s in $ALLOWED; do
    if [ "$s" \> "$CP_RAW" ]; then CP="$s"; break; fi                    # earliest slot >= instant
  done
fi
DIFF=$(( $(_mins "$CP_RAW") - $(_mins "$CP") )); [ "$DIFF" -lt 0 ] && DIFF=$(( -DIFF ))
if [ "$DIFF" -gt 90 ]; then
  echo "slot: UNRESOLVABLE (fire instant ${CP_RAW} ET is >90 min from any checkpoint slot)"
  # Do NOT invent a filename. Leave a trail and stop.
  python3 /workspace/preopen_checkpoint.py skipped \
    --out "/workspace/preopen-feed/${DATE}-DEVIATION.slot.md" \
    --reason "checkpoint slot could not be resolved: the fire instant ${CP_RAW} ET is more than 90 minutes from 0830/0920/0950, so no filename was invented" \
    --date "$DATE" --slot "${CP_RAW}" --fire-instant "$FIRE_INSTANT"
  echo "no tape; no digest; report probe_failed:slot_unresolvable"
  exit 1
fi
export CP
# THE ASSERTION: the filename's slot must be one the consumer can find.
if ! printf '%s\n' $ALLOWED | grep -qx "$CP"; then
  echo "slot assertion FAILED: CP='$CP' is not in {0830,0920,0950}"; exit 1
fi
[ "$CP" = "$CP_RAW" ] && echo "slot: $CP (from the fire instant)" \
                       || echo "slot: $CP (snapped from $CP_RAW — late dispatch)"
```

Measured 2026-11-05: the 08:30 slot's work began at 10:10 ET (the platform stalled) and its tape
was still named `0830`, because the slot comes from the fire's instant, not from the clock.
Snapping only ever fires when the platform itself dispatched the fire late.

### 3. Grok — the narrative half

```bash
export XAI_BASE=https://api.x.ai/v1

# 3a. RESOLVE THE MODEL ID FROM THE ACCOUNT'S OWN MODEL LIST — never hardcode a slug.
# Measured 2026-11-04: this account reaches 13 models and plain `grok-4` is NOT among
# them (the retired slugs redirect and re-price). GET /v1/models is a listing call, not
# an inference call, so it is not billed.
curl -s --max-time 25 "${XAI_BASE}/models" -H "Authorization: Bearer ${XAI_API_KEY}" -o /tmp/grok_models.json
python3 - <<'PYMODEL'
import json
try: ids=[m.get("id","") for m in json.load(open("/tmp/grok_models.json")).get("data",[])]
except Exception: ids=[]
pref=("grok-4.3","grok-4.7","grok-4.6","grok-4.5")
hit=next((p for p in pref if p in ids), None)
open("/tmp/grok_model.txt","w").write(hit or (ids[0] if ids else "grok-4.3"))
PYMODEL
MODEL=$(cat /tmp/grok_model.txt)
echo "grok model: ${MODEL}"

# 3b. THE LEGACY LIVE-SEARCH PATH IS DEAD. `search_parameters` on /v1/chat/completions
# still appears in the REST reference, but the API REJECTS it (measured 2026-11-04):
#   {"error":"Live search is deprecated. Please switch to the Agent Tools API"}
# The working path is the Responses API with server-side tools:
#   max_tool_calls    = the COST CEILING on the search fan-out (12 measured $0.05/checkpoint)
#   max_output_tokens = bounds the reply
#   reasoning_effort  = "low" — this is extraction, not deep reasoning
cat > /tmp/grok_prompt.txt <<'EOF'
You are a US equity market catalyst feed. RIGHT NOW, list US-listed stocks (NYSE/NASDAQ/AMEX, ticker under 6 chars) that are moving materially pre-market or at the open. For each, return JSON ONLY, one object per line, no prose: {"ticker":"","name":"","pct":0.0,"price":0.0,"cat":"acquisition|merger|earnings|guidance|fda|trial|offering|halt|downgrade|guidance-cut|spin|dividend|other","why":"one clause, <=140 chars, stating the specific catalyst","ref":"source URL","conf":"high|medium|low"}. Only include names with a move beyond roughly 3% pre-market or a genuinely material corporate catalyst. If there is no US pre-market session (weekend/holiday), return nothing. Do NOT include your own commentary.
EOF
python3 - <<'PYPAYLOAD'
import json
payload={"model":open("/tmp/grok_model.txt").read().strip(),
 "reasoning_effort":"low",
 "input":[{"role":"user","content":open("/tmp/grok_prompt.txt",encoding="utf-8").read().strip()}],
 "tools":[{"type":"web_search"},{"type":"x_search"}],
 "max_output_tokens":4000,"max_tool_calls":12}
json.dump(payload,open("/tmp/grok_payload.json","w"))
PYPAYLOAD

curl -s --max-time 120 "${XAI_BASE}/responses" \
  -H "Authorization: Bearer ${XAI_API_KEY}" -H "Content-Type: application/json" \
  --data @/tmp/grok_payload.json > /tmp/grok_out.json

# 3c. FAIL CLOSED, and report the EXACT cost — the API returns it.
python3 - <<'PYUSE'
import json,sys
ok=False
try:
    d=json.load(open("/tmp/grok_out.json"))
    err=d.get("error")
    if err:
        sys.stderr.write("GROK_ERROR "+json.dumps(err)[:300]+"\n")
    else:
        txt="".join(c.get("text","") for it in (d.get("output") or [])
                    for c in (it.get("content") or []) if c.get("type")=="output_text")
        ok=bool(txt.strip())
        u=d.get("usage") or {}
        st=u.get("server_side_tool_usage_details") or {}
        print("GROK_OK status=%s chars=%d cost=$%.4f in_tok=%s out_tok=%s web=%s x_calls=%s x_posts=%s"%(
            d.get("status"), len(txt), (u.get("cost_in_usd_ticks") or 0)/1e10,
            u.get("input_tokens"), u.get("output_tokens"),
            st.get("web_search_calls"), st.get("x_search_calls"), st.get("x_posts_fetched")))
        open("/tmp/grok_reply.txt","w").write(txt)
        # The MEASURED cost travels into the digest header. Ticks are 1e-10 of a dollar.
        json.dump({"model":open("/tmp/grok_model.txt").read().strip(),
                   "cost_usd":(u.get("cost_in_usd_ticks") or 0)/1e10,
                   "web_search_calls":st.get("web_search_calls"),
                   "x_search_calls":st.get("x_search_calls"),
                   "input_tokens":u.get("input_tokens"),
                   "output_tokens":u.get("output_tokens")},
                  open("/tmp/grok_meta.json","w"))
except Exception as e:
    sys.stderr.write("GROK_PARSE_FAILED "+str(e)[:200]+"\n")
open("/tmp/grok_ok","w").write("1" if ok else "0")
PYUSE
```

**The legacy live-search path is dead — verified by a live call 2026-11-04.**
`search_parameters` on `/v1/chat/completions` is still printed in the REST reference, but the API
answers `{"error":"Live search is deprecated. Please switch to the Agent Tools API"}`. The
Responses API with server-side tools (`web_search`, `x_search`) is the working path. **A doc page
that still lists a parameter is not evidence the backend honours it — probe the endpoint.**

**The two-source split.** Grok can hallucinate a ticker or a percentage. The scanner gives
ground truth on prices. Therefore: **prices are only ever taken from the scanner; Grok supplies
the reason, never the number.** A Grok record whose `pct` disagrees with the scanner by more than
2pp is written with `"conf":"unverified"` and the consumer prints it as unconfirmed.

**What the search actually costs.** Measured 2026-11-04 on `grok-4.3`: **$0.0476 and $0.0514
per checkpoint** (3 web searches each, ~25k input / ~2k output tokens, 21-24 s) — about
**$0.10/day at two checkpoints, ~$2.20/month** at 21 sessions, and materially more on a day
when the model leans on X ($5/1k posts). The API returns the exact figure in
`usage.cost_in_usd_ticks` (10,000,000,000 ticks = $1), so the per-fire cost is a MEASUREMENT,
not an estimate. Published rates: web $5/1k calls, X $5/1k posts + $10/1k profiles, grok-4.3
$1.25/$2.50 per 1M tokens. `max_tool_calls` is the ceiling that keeps it bounded.

### 4. TradingView scanner — ONE snapshot, movers-sorted in BOTH directions

**The scan is movers-sorted, not volume-sorted.** The old procedure sorted by `premarket_volume`
and capped at 120 rows, which buries the biggest movers under a wall of noise — and the 08:30
checkpoint is the pre-open tape, where the biggest movers are the entire point. Measured
2026-11-05: that shape produced a 123-row tape (43 gainers / 79 losers) with the moves cut off at
±0.2%, while a movers-sorted tape on the same day produced 700 rows with the cutoff at ±2.5%.

```bash
# ONE SNAPSHOT: two directional halves, issued back to back in the SAME block, with
# DISJOINT filters (change >= +2.5 vs change <= -2.5). Disjointness is what makes the
# no-splice rule structural: no name can appear in both halves, so no record can hold
# a price from two different calls.
#
# Use the SAME column list in BOTH calls, in the same order, and zip by NAME.
COLS='"name","description","close","change","volume","relative_volume_10d_calc","market_cap_basic","premarket_change","premarket_volume","premarket_close","halted","exchange"'
BASE='{"left":"type","operation":"equal","right":"stock"},{"left":"exchange","operation":"in_range","right":["NASDAQ","NYSE","AMEX"]},{"left":"volume","operation":"egreater","right":50000},{"left":"premarket_volume","operation":"egreater","right":0}'

# gains, biggest first
curl -s --max-time 30 -X POST https://scanner.tradingview.com/america/scan \
  -H "Content-Type: application/json" \
  -d "{\"filter\":[${BASE},{\"left\":\"premarket_change\",\"operation\":\"egreater\",\"right\":2.5}],\"columns\":[${COLS}],\"sort\":{\"sortBy\":\"premarket_change\",\"sortOrder\":\"desc\"},\"range\":[0,1000]}" > /tmp/tv_gain.json

# losses, worst first
curl -s --max-time 30 -X POST https://scanner.tradingview.com/america/scan \
  -H "Content-Type: application/json" \
  -d "{\"filter\":[${BASE},{\"left\":\"premarket_change\",\"operation\":\"eless\",\"right\":-2.5}],\"columns\":[${COLS}],\"sort\":{\"sortBy\":\"premarket_change\",\"sortOrder\":\"asc\"},\"range\":[0,1000]}" > /tmp/tv_loss.json
```

**This half is not optional.** Grok supplies the *reason*; the scanner supplies the *number*.
Never take a price from Grok.

**The expected tape size is ≈678 rows** — the 2026-11-04 08:30 tape (406 gainers / 271 losers /
1 flat). The 2026-11-05 08:30 tape was 700 (250 / 450). A quiet session lands lower; a violent
one lands higher. **A tape of ~120 rows is the REGRESSION SIGNATURE**: it means the sort went
back to `premarket_volume`, and the biggest movers are missing. Say so — `tape_size_deviation` —
rather than publishing a board that looks complete.

**The `halted` column is NOT measurable — never report a halt count from it.** Measured
2026-11-03: `halted` is `null` for EVERY US row (120/120 in an unfiltered top-120-by-volume
scan, out of 20,149), and a scan filtered on `halted` matches nothing in EITHER direction
(`halted=true` → `totalCount: 0`; `halted=false` → `totalCount: 0`). So "0 halted" is not a
finding — it is the absence of a value. Cron #17 independently reports that LULD / limit status
is unverifiable ("both halt feeds are dead"). Report the halt state as **not measurable**; never
print a count that looks like a measurement.

### 5. Merge — one snapshot, one number per record, one row per ticker

```bash
python3 /workspace/preopen_checkpoint.py merge \
  --grok-reply /tmp/grok_reply.txt --tv-gain /tmp/tv_gain.json --tv-loss /tmp/tv_loss.json \
  --out "/workspace/preopen-feed/${DATE}-${CP}.jsonl" --ts "$TS"
```

The script enforces the three rules that are easy to break by hand:

- **One snapshot, one number per record.** Every price in the tape comes from the step-4
  snapshot. There is no second scanner call anywhere in the merge. Measured 2026-11-04: four
  records drifted (CRIS +93.3 → +97.5, DKI +48.0 → +69.9) purely because the tape moved between
  two calls taken minutes apart. **Never splice scanner calls taken minutes apart.**
- **A Grok name the scanner did not see gets NO number** — `pct: null`, `price: null`,
  `conf: "unverified"`, with the reason kept. Grok supplies the reason; the scanner supplies the
  number. A name with no scanner row has no number, and Grok's number is not a substitute.
- **One row per ticker.** A ticker Grok named gets ONE record, `src:"grok"`, carrying the
  scanner's `pct`/`price`; it does NOT also get a `src:"scanner"` row. The scanner's rows are
  for the names Grok did not mention — a big pre-market move with no reason yet is itself
  information, and the next checkpoint may explain it.

**FAIL CLOSED — a failed Grok call must not produce a tape.** If step 3c wrote `0` to
`/tmp/grok_ok` (the call errored, timed out, or returned no text), write **nothing**: no file, no
push, and reply `errors: 1`. The scanner-only rows above are legitimate ONLY when Grok answered
successfully and simply did not mention a name. A scanner-only tape manufactured out of a FAILED
call is precisely the "no catalyst" fiction this routine exists to avoid — the same reason the
key check aborts rather than writing an empty file.

### 6. Digest, then push

```bash
# 6a. The human-readable board, beside the tape.
python3 /workspace/preopen_checkpoint.py digest \
  --tape "/workspace/preopen-feed/${DATE}-${CP}.jsonl" \
  --out "/workspace/preopen-feed/${DATE}-${CP}.md" \
  --meta /tmp/grok_meta.json --date "$DATE" --slot "$CP"

# 6b. Push both files.
D=/workspace/push_artifact.sh
for U in \
  "https://api.github.com/repos/karizaco/maxhermes-migration/contents/cloud-prompts/_shared/push_artifact.sh?ref=main" \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/push_artifact.sh" \
  "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/push_artifact.sh" ; do
  curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" \
    -H "Authorization: Bearer ${GITHUB_TOKEN}" -o "$D.tmp" "$U" 2>/dev/null
  if [ -s "$D.tmp" ] && ! head -c 200 "$D.tmp" | grep -q '"message"' \
     && head -1 "$D.tmp" 2>/dev/null | grep -q '^#!'; then
    mv -f "$D.tmp" "$D"; break
  fi
  rm -f "$D.tmp"
done
[ -s "$D" ] || echo "push_artifact.sh fetch FAILED - the DELIVERY step cannot push its artifact"
sh /workspace/push_artifact.sh --out preopen-feed --add preopen-feed/${DATE}-${CP}.jsonl \
   --branch main --msg "cron 92 preopen-catalyst-capture ${DATE}-${CP}" --nn 92
```

The digest's header carries the record count, the Grok-vs-scanner split, the `unverified` count
and the measured Grok cost; the table lists the top 15 movers by `|%|` descending with the
`conf` token on every row, so an `unverified` row is obvious at a glance.

**The helper takes NAMED flags** (`--out`, `--add`, `--branch`, `--msg`, `--nn`) — it does not
accept positional arguments, and a call that omits them is refused. `--add` is the checkpoint file
this fire wrote; the helper stages the whole `preopen-feed/` tree, so the sibling checkpoints from
the other #92 fire land in the same commit without being clobbered — and so does the `.md`
digest written beside this fire's tape.

(If that helper is absent, fetch it from
`cloud-prompts/_shared/push_artifact.sh` in `karizaco/maxhermes-migration`.)

**Never `git add -A`.** Stage only `preopen-feed/`.

### 6c. The fail-closed push (key unset)

```bash
sh /workspace/push_artifact.sh --out preopen-feed --add preopen-feed/${DATE}-${CP}.SKIPPED.md \
   --branch main --msg "cron 92 preopen-catalyst-capture SKIPPED ${DATE}-${CP}" --nn 92
```

The marker is pushed, so the checkpoint's absence on the outputs repo is explained rather than
blank. **No JSONL is written in this path** — a `.SKIPPED.md` beside no tape is the correct
state, and a tape of any size would be worse.

## REPLY

Under 6 lines. Name the checkpoint, the number of records written, the scanner's halt state, and
one line for push status and `errors: <n>`.

Also report the MEASURED cost of the Grok call from step 3c — `model`, the dollar cost, the
web/x call counts and the token counts — folded into the records line. That is the real per-fire
cost signal; the estimates in the plan document are stale. If the call failed, say so and write
nothing.

**The halt state is `not measurable`, never `0`.** The scanner's `halted` column is null for every
row (see step 4), so there is no count to report. Write
`halted: not measurable (TV halted column is null for every row)`. A `0` there reads as "no name
was halted" — a measurement that was never taken — and the consumer will carry it as a finding.

**If the tape came out at ≈120 rows, say so.** `tape_size_deviation` — the scanner sort
regressed to `premarket_volume` and the board is missing its biggest movers. Do not report a
120-row tape as a quiet market.

## RULES

- **A certificate/TLS error is a FETCH failure, not a missing source.** The sandbox egress proxy
  rotates its leaf cert and it has expired mid-session before; `web_fetch` uses a different egress
  and still works. On a cert error, retry the SAME url with `web_fetch` before you conclude
  anything about the source.

- **No key ⇒ no tape, but a trail.** Write the `.SKIPPED.md` marker naming the reason and push
  it; write no JSONL.
- **Never fabricate a ticker, a price or a catalyst.** A record with no source URL is `conf:low`.
- **A missing checkpoint is normal.** Do not backfill or interpolate.
- Prices come from the scanner. Grok only explains.
- **One snapshot per checkpoint.** Every number in a tape comes from the same scanner snapshot.
- **Never hardcode a Grok model slug.** Resolve it from `/v1/models` at run time (step 3a).
- **A failed Grok call writes nothing.** Fail closed — see step 5.
- **Bound the live search.** `max_search_results` is a cost ceiling, not a quality setting; if the
  tape starts missing obvious catalysts, raise it and say so in the reply.
