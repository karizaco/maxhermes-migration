# Cloud Mavis cron: preopen-catalyst-capture (cron #92)

Captures the pre-open **catalyst tape**: for each US stock materially moving pre-market or at the
open, record WHO / WHAT / WHEN, with ground-truth prices. Cron #17 (`us-stocks-in-play`,
15:50 ET) reads the tape to explain why a stock moved and when the news broke — the one thing no
price feed can tell it.

**The whole procedure is one script.** Fetch it and run it; do not improvise the procedure.

## WHAT THIS IS FOR

At 15:50 the digest sees where a stock IS, not where it came from, and — this is the gap — not the
catalyst as it was understood at the open. By 15:50 the wire has moved on: the 09:12 headline is
buried, and a name that gapped +12% on an FDA approval and now trades +2% looks identical to one
that never moved. The skill requires the gap annex to separate a gap that **held into the bell**
from one that faded, and to attribute the move.

## STEPS — execute IN ORDER

### 1. Fetch the capture script

```bash
S=/workspace/preopen_capture.py
for U in \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/preopen_capture.py" \
  "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/preopen_capture.py" ; do
  [ -s "$S" ] || curl -sL --max-time 30 -o "$S" "$U" 2>/dev/null
done
[ -s "$S" ] || echo "capture script fetch FAILED — write nothing"
```

### 2. Run it

```bash
export DATE=$(TZ=America/New_York date +%Y-%m-%d)
export CP=$(TZ=America/New_York date +%H%M)          # 0830 | 0920 | 0950 ...
python3 "$S" --date "$DATE" --checkpoint "$CP"
```

The script prints one line: `preopen capture: wrote N records to <path> ...`.

- **It writes nothing and exits 0 if `PIPEWORX_API_KEY` is unset** — a missing key is not a
  failure, it is a missing tape. Never write an empty tape: the consumer would read it as
  "no news" for names that had a catalyst.
- Each checkpoint writes its **own** file `preopen-feed/{date}-{CP}.jsonl`, so two captures can
  never clobber each other and the consumer merges them oldest-first.

### 3. Push

```bash
B=https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared
for U in "$B/push_artifact.sh" "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/push_artifact.sh"; do
  [ -s /workspace/push_artifact.sh ] || curl -sL -o /workspace/push_artifact.sh "$U"
done
sh /workspace/push_artifact.sh --out preopen-feed --add preopen-feed/${DATE}-${CP}.jsonl --branch main
sh /workspace/verify_delivery.sh --path preopen-feed/${DATE}-${CP}.jsonl --branch main
```

**Stage only `preopen-feed/`. Never `git add -A`.**

## WHAT THE SCRIPT DOES (for the reply, not for reimplementation)

Three Pipeworx gateway calls, each with one job:

| Call | Pack | Job |
|---|---|---|
| `trending_symbols` | `stocktwits` | candidates + a natural-language reason + a `summary_at` timestamp for each. Live retail/WSB chatter — the X signal. |
| `top_movers` | `market-recap` | **ground truth**: price, %chg, volume. Prices always come from here. |
| `ask_pipeworx_grounded` | `market-recap` | a per-name catalyst with evidence, source and confidence, for movers the first call did not cover. |

**Prices are never taken from the narrative calls.** A percentage that disagrees with
`top_movers` by more than 2pp is marked `unverified`. The script also drops a grounded answer
that merely restates the price move, and drops one whose source was a filing index rather than
news — a name with no findable catalyst is left with no catalyst, which is the honest result.

**xAI/Grok is NOT used.** The xAI chat API no longer serves live search (`search_parameters`
returns HTTP 410, "Live search is deprecated") and the Agent Tools API that replaces it is not
enabled on most keys. Pipeworx does the job on its own. If `XAI_API_KEY` is present it is
ignored, not used as a fallback.

## REPLY

Under 6 lines: the checkpoint, the number of records written, how many movers carry a catalyst,
one line for push status, one line for `errors: <n>`.
