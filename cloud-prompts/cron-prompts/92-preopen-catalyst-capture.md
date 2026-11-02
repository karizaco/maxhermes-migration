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
cat > /tmp/grok.json <<'EOF'
{"model":"grok-4","temperature":0.1,
 "search_parameters":{},
 "messages":[{"role":"user","content":"You are a US equity market catalyst feed. RIGHT NOW, list US-listed stocks (NYSE/NASDAQ/AMEX, ticker under 6 chars) that are moving materially pre-market or at the open. For each, return JSON ONLY, one object per line, no prose: {\"ticker\":\"\",\"name\":\"\",\"pct\":0.0,\"price\":0.0,\"cat\":\"acquisition|merger|earnings|guidance|fda|trial|offering|halt|downgrade|guidance-cut|spin|dividend|other\",\"why\":\"one clause, <=140 chars, stating the specific catalyst\",\"ref\":\"source URL\",\"conf\":\"high|medium|low\"}. Only include names with a move beyond roughly 3% pre-market or a genuinely material corporate catalyst. If there is no US pre-market session (weekend/holiday), return nothing. Do NOT include your own commentary."}]}
EOF
curl -s --max-time 90 https://api.x.ai/v1/chat/completions \
  -H "Authorization: Bearer ${XAI_API_KEY}" -H "Content-Type: application/json" \
  --data @/tmp/grok.json > /tmp/grok_out.json
```

`search_parameters` is what gives Grok live web + X access — that is the entire reason this
routine exists and the reason a plain `web_search` cannot replace it.

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

### 5. Merge and validate

- Parse Grok's reply into records; drop any line without a ticker.
- Join to the scanner by ticker. If a Grok `pct` disagrees with the scanner's `premarket_change`
  by more than 2 percentage points, set `"conf":"unverified"` and keep it (the consumer flags it).
- Keep the scanner rows for names Grok did not mention — a big premarket move with no reason yet
  is itself information, and the next checkpoint may explain it.
- Emit one JSON object per line. **Append only.** Never rewrite an earlier checkpoint's rows.

### 6. Write and push

```bash
mkdir -p /workspace/preopen-feed
python3 - <<'PY' > /workspace/preopen-feed/${DATE}.jsonl
# emit the merged JSONL here
PY
```

Then push with the shared helper:

```bash
bash /workspace/push_artifact.sh /workspace/preopen-feed/${DATE}.jsonl preopen-feed/${DATE}.jsonl
```

(If that helper is absent, fetch it from
`cloud-prompts/_shared/push_artifact.sh` in `karizaco/maxhermes-migration`.)

**Never `git add -A`.** Stage only `preopen-feed/`.

## REPLY

Under 6 lines. Name the checkpoint, the number of records written, how many names the scanner
flagged with `halted`, and one line for push status and `errors: <n>`.

## RULES

- **No key ⇒ no tape.** Say so plainly; never write an empty file that looks like "no news".
- **Never fabricate a ticker, a price or a catalyst.** A record with no source URL is `conf:low`.
- **A missing checkpoint is normal.** Do not backfill or interpolate.
- Prices come from the scanner. Grok only explains.
