# Cloud Mavis cron: preopen-catalyst-capture (cron #92)
<!-- PROCEDURE_VERSION: 2026-11-04.3 -->

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

Also report the MEASURED cost of the Grok call from step 3c — `model`, the dollar cost, the
web/x call counts and the token counts — folded into the records line. That is the real per-fire
cost signal; the estimates in the plan document are stale. If the call failed, say so and write
nothing.

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
