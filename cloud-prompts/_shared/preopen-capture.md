# Cloud Mavis cron: preopen-catalyst-capture (cron #92)

Runs three times per session-day (08:30, 09:20, 09:50 ET). Writes an append-only **catalyst
tape** that cron #17 (`us-stocks-in-play`, 15:50 ET) reads to explain *why* a stock moved and
*when* the news broke — the thing no price feed can tell you.

## WHAT THIS IS FOR

At 15:50 the digest can see where a stock IS. It cannot see where it came from, and — this is the
gap — **it cannot see the catalyst as it was understood at the open.** By 15:50 the wire has moved
on: the 09:12 headline is buried, and a name that gapped +12% on an FDA approval and now trades
+2% looks identical to one that never moved.

This routine records the tape while it is still happening.

## OUTPUT

Append-only JSONL at `preopen-feed/{date}.jsonl` in `karizaco/minimax-cloud-outputs`, branch
`main`. One JSON object per line:

```json
{"ts":"2026-11-03T09:15:23-04:00","src":"grok","ticker":"BRZE","name":"Braze",
 "pct":51.2,"price":45.40,"cat":"acquisition","why":"Salesforce to acquire for $47.50/sh cash",
 "ref":"https://…","conf":"high"}
```

`cat` vocabulary: `acquisition | merger | earnings | guidance | fda | trial | offering | halt |
downgrade | guidance-cut | spin | dividend | other`.

## STEPS — execute IN ORDER

### 1. Key check (FIRST)

```bash
if [ -z "${XAI_API_KEY:-}" ]; then
  echo "preopen capture: XAI_API_KEY unset — nothing written"
  exit 0
fi
```

**If the key is unset, write nothing and exit.** A tape with no catalyst in it is worse than no
tape, because the consumer would report "no catalyst" for a name that had one.

### 2. Resolve the date and checkpoint

```bash
export DATE=$(TZ=America/New_York date +%Y-%m-%d)
export TS=$(TZ=America/New_York date +%Y-%m-%dT%H:%M:%S%:z)
```

### 3. Grok — the narrative half

```bash
export XAI_BASE=https://api.x.ai/v1

# 3a. RESOLVE THE MODEL ID FROM THE ACCOUNT'S OWN MODEL LIST — never hardcode a slug.
# xAI retires models: the 2026-05-15 retirement took grok-4-0709 and the grok-4-fast
# variants to grok-4.3 (the slugs still resolve, but they redirect and re-price).
# GET /v1/models is a listing call, not an inference call, so it is not billed.
MODEL=$(curl -s --max-time 25 "${XAI_BASE}/models" \
  -H "Authorization: Bearer ${XAI_API_KEY}" \
  | python3 -c '
import sys,json
try: ids=[m.get("id","") for m in json.load(sys.stdin).get("data",[])]
except Exception: ids=[]
pref=("grok-4.3","grok-4.7","grok-4.6","grok-4.5","grok-4")
hit=next((p for p in pref if p in ids), None)
print(hit or (ids[0] if ids else "grok-4"))
')
echo "grok model: ${MODEL}"

# 3b. Build and send. max_search_results BOUNDS the live-search fan-out; without it
# the call searches web AND X with no ceiling, and X is billed per POST fetched
# ($5/1k posts, $10/1k profiles) while web is $5/1k calls. 12 is the bounded default —
# the reply reports num_sources_used every fire, so it can be tuned from real numbers.
cat > /tmp/grok.json <<'EOF'
{"model":"__MODEL__","temperature":0.1,
 "search_parameters":{"max_search_results":12},
 "messages":[{"role":"user","content":"You are a US equity market catalyst feed. RIGHT NOW, list US-listed stocks (NYSE/NASDAQ/AMEX, ticker under 6 chars) that are moving materially pre-market or at the open. For each, return JSON ONLY, one object per line, no prose: {\"ticker\":\"\",\"name\":\"\",\"pct\":0.0,\"price\":0.0,\"cat\":\"acquisition|merger|earnings|guidance|fda|trial|offering|halt|downgrade|guidance-cut|spin|dividend|other\",\"why\":\"one clause, <=140 chars, stating the specific catalyst\",\"ref\":\"source URL\",\"conf\":\"high|medium|low\"}. Only include names with a move beyond roughly 3% pre-market or a genuinely material corporate catalyst. If there is no US pre-market session (weekend/holiday), return nothing. Do NOT include your own commentary."}]}
EOF
sed -i "s/__MODEL__/${MODEL}/" /tmp/grok.json

curl -s --max-time 90 "${XAI_BASE}/chat/completions" \
  -H "Authorization: Bearer ${XAI_API_KEY}" -H "Content-Type: application/json" \
  --data @/tmp/grok.json > /tmp/grok_out.json

# 3c. FAIL CLOSED, and measure the real cost of this call.
python3 - <<'PY'
import json,sys
ok=False
try:
    d=json.load(open("/tmp/grok_out.json"))
    if isinstance(d,dict) and d.get("error"):
        sys.stderr.write("GROK_ERROR "+json.dumps(d["error"])[:300]+"\n")
    else:
        txt=(d.get("choices") or [{}])[0].get("message",{}).get("content") or ""
        ok=bool(txt.strip())
        u=d.get("usage") or {}
        print("GROK_OK chars=%d num_sources_used=%s prompt_tokens=%s completion_tokens=%s"%(
            len(txt),u.get("num_sources_used"),u.get("prompt_tokens"),u.get("completion_tokens")))
except Exception as e:
    sys.stderr.write("GROK_PARSE_FAILED "+str(e)[:200]+"\n")
open("/tmp/grok_ok","w").write("1" if ok else "0")
PY
```

`search_parameters` is what gives Grok live web + X access — that is the entire reason this
routine exists and the reason a plain `web_search` cannot replace it.

**It is CURRENT, not legacy (verified 2026-11-04 against docs.x.ai).** `search_parameters` is
documented on BOTH `/v1/chat/completions` and `/v1/responses`, with `mode` (`off|on|auto`),
`sources`, `max_search_results`, `return_citations` and `from_date`/`to_date` filters. Chat
Completions is marked *Deprecated* in favour of the Responses API, but it still serves, and the
Responses API accepts the SAME `search_parameters` object — so the endpoint choice is a
recommendation, not a blocker. Do not "migrate" this routine off `search_parameters` on the
strength of a stale note; migrate only with a live call to prove the new shape.

**What the search actually costs.** The server-side tool path (`tools:[{type:web_search}]`) is
priced explicitly — web $5/1k calls, X $5/1k posts + $10/1k profiles, and a post returned by two
searches counts twice. The `search_parameters` path bills by `num_sources_used`, which the usage
block reports and step 3c prints. **That number is the per-fire cost signal** — the per-run
estimates in the plan document are stale and understate the bill by roughly 6x, because they
counted tokens only and ignored the per-source and per-post fees.

### 4. TradingView scanner — the ground-truth half

```bash
curl -s --max-time 30 -X POST https://scanner.tradingview.com/america/scan \
  -H "Content-Type: application/json" \
  -d '{"filter":[{"left":"type","operation":"equal","right":"stock"},{"left":"exchange","operation":"in_range","right":["NASDAQ","NYSE","AMEX"]},{"left":"volume","operation":"egreater","right":50000}],
       "columns":["name","description","close","change","volume","relative_volume_10d_calc","market_cap_basic","premarket_change","premarket_volume","premarket_close","halted","exchange"],
       "sort":{"sortBy":"premarket_volume","sortOrder":"desc"},"range":[0,120]}' > /tmp/tv.json
```

**This half is not optional.** Grok supplies the *reason*; the scanner supplies the *number*.
Never take a price from Grok.

**The `halted` column is NOT measurable — never report a halt count from it.** Measured
2026-11-03: `halted` is `null` for EVERY US row (120/120 in an unfiltered top-120-by-volume
scan, out of 20,149), and a scan filtered on `halted` matches nothing in EITHER direction
(`halted=true` → `totalCount: 0`; `halted=false` → `totalCount: 0`). So "0 halted" is not a
finding — it is the absence of a value. Cron #17 independently reports that LULD / limit status
is unverifiable ("both halt feeds are dead"). Report the halt state as **not measurable**; never
print a count that looks like a measurement.

### 5. Merge and validate

- Parse Grok's reply into records; drop any line without a ticker.
- Join to the scanner by ticker. If a Grok `pct` disagrees with the scanner's `premarket_change`
  by more than 2 percentage points, set `"conf":"unverified"` and keep it (the consumer flags it).
- Keep the scanner rows for names Grok did not mention — a big premarket move with no reason yet
  is itself information, and the next checkpoint may explain it.
- Emit one JSON object per line. **Append only.** Never rewrite an earlier checkpoint's rows.

**FAIL CLOSED — a failed Grok call must not produce a tape.** If step 3c wrote `0` to
`/tmp/grok_ok` (the call errored, timed out, or returned no text), write **nothing**: no file, no
push, and reply `errors: 1`. The scanner-only rows above are legitimate ONLY when Grok answered
successfully and simply did not mention a name. A scanner-only tape manufactured out of a FAILED
call is precisely the "no catalyst" fiction this routine exists to avoid — the same reason the
key check aborts rather than writing an empty file.

### 6. Write and push

```bash
mkdir -p /workspace/preopen-feed
export CP=$(TZ=America/New_York date +%H%M)     # 0830 | 0920 | 0950 ...
# ... emit the merged JSONL ...
# -> /workspace/preopen-feed/${DATE}-${CP}.jsonl
```

Each checkpoint writes its **own** file, so two captures can never clobber each other and the
consumer can merge them oldest-first.

Then push with the shared helper:

```bash
for U in \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/push_artifact.sh" \
  "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/push_artifact.sh" ; do
  [ -s /workspace/push_artifact.sh ] || curl -sL -o /workspace/push_artifact.sh "$U" 2>/dev/null
done
sh /workspace/push_artifact.sh --out preopen-feed --add preopen-feed/${DATE}-${CP}.jsonl \
   --branch main --msg "cron 92 preopen-catalyst-capture ${DATE}-${CP}" --nn 92
```

**The helper takes NAMED flags** (`--out`, `--add`, `--branch`, `--msg`, `--nn`) — it does not
accept positional arguments, and a call that omits them is refused. `--add` is the checkpoint file
this fire wrote; the helper stages the whole `preopen-feed/` tree, so the sibling checkpoints from
the other #92 fire land in the same commit without being clobbered.

(If that helper is absent, fetch it from
`cloud-prompts/_shared/push_artifact.sh` in `karizaco/maxhermes-migration`.)

**Never `git add -A`.** Stage only `preopen-feed/`.

## REPLY

Under 6 lines. Name the checkpoint, the number of records written, the scanner's halt state, and
one line for push status and `errors: <n>`.

Also report the MEASURED cost of the Grok call from step 3c — `model`, `num_sources_used`,
`prompt_tokens`, `completion_tokens` — folded into the records line. That is the real per-fire
cost signal; the estimates in the plan document are stale.

**The halt state is `not measurable`, never `0`.** The scanner's `halted` column is null for every
row (see step 4), so there is no count to report. Write
`halted: not measurable (TV halted column is null for every row)`. A `0` there reads as "no name
was halted" — a measurement that was never taken — and the consumer will carry it as a finding.

## RULES

- **A certificate/TLS error is a FETCH failure, not a missing source.** The sandbox egress proxy
  rotates its leaf cert and it has expired mid-session before; `web_fetch` uses a different egress
  and still works. On a cert error, retry the SAME url with `web_fetch` before you conclude
  anything about the source.

- **No key ⇒ no tape.** Say so plainly; never write an empty file that looks like "no news".
- **Never fabricate a ticker, a price or a catalyst.** A record with no source URL is `conf:low`.
- **A missing checkpoint is normal.** Do not backfill or interpolate.
- Prices come from the scanner. Grok only explains.
- **Never hardcode a Grok model slug.** Resolve it from `/v1/models` at run time (step 3a).
- **A failed Grok call writes nothing.** Fail closed — see step 5.
- **Bound the live search.** `max_search_results` is a cost ceiling, not a quality setting; if the
  tape starts missing obvious catalysts, raise it and say so in the reply.
