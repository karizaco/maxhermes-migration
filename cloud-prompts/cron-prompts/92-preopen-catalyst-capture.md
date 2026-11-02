# Cloud Mavis cron: preopen-catalyst-capture (cron #92)

Captures the pre-open **catalyst tape**: for each US stock materially moving pre-market or at the
open, record WHO / WHAT / WHEN, with ground-truth prices from the TradingView scanner. Cron #17
(`us-stocks-in-play`, 15:50 ET) reads the tape to explain why a stock moved and when the news
broke — the one thing no price feed can tell it.

The procedure lives in ONE shared file, not in every prompt. Fetch it in the same first step as
the skill spec, then follow it in full:

```bash
B=https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared
for U in "$B/preopen-capture.md" "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/preopen-capture.md"; do
  [ -s /workspace/preopen-capture.md ] || curl -sL -o /workspace/preopen-capture.md "$U" 2>/dev/null
done
```

Then follow `/workspace/preopen-capture.md` in full. It contains the key check, the Grok call,
the TradingView ground-truth call, the merge/validation rules and the append-and-push steps.

## THIS FIRE

- **Checkpoint:** the capture writes `preopen-feed/{date}-{HHMM}.jsonl`, where `HHMM` is the ET
  fire time — so each checkpoint has its own file and no two crons can clobber each other.
- **The key check comes first.** If `${XAI_API_KEY}` is unset, write nothing and reply
  `preopen capture: XAI_API_KEY unset — nothing written`. Never fabricate a tape.
- **Order of attack:** Grok (narrative) → TradingView scanner (ground-truth prices) → merge →
  append → push. Prices always come from the scanner; Grok only explains.
- **Push** with the shared helper `cloud-prompts/_shared/push_artifact.sh`, staging only
  `preopen-feed/`. Never `git add -A`.

## REPLY

Under 6 lines: the checkpoint, the number of records written, how many names the scanner flagged
`halted`, one line for push status, one line for `errors: <n>`.
