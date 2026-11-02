# n8n — pre-open catalyst capture

Optional deployment of the capture cron (cron #92) on your own n8n. The **platform cron already
covers the two key checkpoints** (08:30 and 09:50 ET) with no n8n at all; run this only if you
want a denser cadence (the 09:20 gap checkpoint, or every 10 minutes through the open).

## Why n8n is optional, not required

The platform scheduler now fires `92a` (08:30 ET) and `92b` (09:50 ET) itself, using the same
shared body. Both need exactly one credential: `XAI_API_KEY`. **No GitHub PAT is required for
that path** — the platform cron already has `GITHUB_TOKEN`.

If you deploy this workflow to n8n, n8n needs **its own** GitHub PAT (see §3).

## 1. Credentials

| Name | Where it lives | Scope |
|---|---|---|
| `XAI_API_KEY` | n8n (and the platform secret store) | xAI API key. Get one from https://console.x.ai. Confirm the model id your key can reach with `GET https://api.x.ai/v1/models` — the workflow assumes `grok-4`. |
| GitHub PAT | n8n only | `contents:write` on `karizaco/minimax-cloud-outputs`. A fine-grained PAT scoped to that one repo. Do NOT reuse a token with wider scope. |

In n8n: **Credentials → New → Header Auth** for the Grok call, and **Credentials → New → GitHub**
for the push. Replace the `{{$env.XAI_API_KEY}}` reference in the HTTP node with your credential
reference if you prefer n8n's credential store over environment variables.

## 2. Import

`workflow-preopen-catalyst-capture.json` in this directory. Import it via **Workflows → Import
from File**, then fix up the credentials.

**It is a template, not a finished deploy.** The three nodes you get are real and tested in
isolation (Grok → scanner → merge/validate). The final "append to the feed" node is a placeholder:
the robust way to append is to let a **GitHub API request node** do a raw `PUT` to the file
endpoint, but GitHub's contents API is put-overwrite, not append — so the correct implementation
needs either the GitHub node's "create or update file" with the previous content read first, or a
tiny helper of your own.

**Recommended implementation of the append step:**

1. Read the existing file (if any) with `GET https://api.github.com/repos/karizaco/minimax-cloud-outputs/contents/preopen-feed/{date}-{HHMM}.jsonl`
2. Concatenate the existing body with the new lines
3. `PUT` the concatenation back with the `sha` from step 1
4. If step 1 returns 404, `PUT` the new lines with no `sha`

Because each checkpoint writes its own `{date}-{HHMM}.jsonl`, you never need to read another
checkpoint's file — the "one owner per output directory" rule holds and no two runs can clobber
each other.

## 3. The merge node — what it guarantees

The Grok branch supplies **the reason**; the TradingView branch supplies **the price**. The merge
node enforces that split:

- A Grok percentage that disagrees with the scanner by more than **2pp** is rewritten to
  `"conf": "unverified"`.
- Scanner-only names with a premarket move ≥3% are emitted as `"src":"tv"`, `"conf":"low"`,
  `why: null` — a big move with no explanation *yet* is itself information, and the next
  checkpoint may explain it.
- Any row without a ticker is dropped.

Do not "fix" this by trusting Grok for prices. The whole point of the two branches is that Grok
can hallucinate a ticker or a percentage and the scanner cannot.

## 4. Schedule

The template's schedule expression is `30 8,9,14,15 * * 1-5` (hour 8 and 9 at :30, hour 14 and 15
at :30 — edit to taste). For the dense pre-open cadence use `*/10 8-9 * * 1-5`. Note the workflow
fetches the ET hour itself, so the checkpoint suffix always matches the fire time.

**Guard on cost:** each Grok call is a paid API call. The dense cadence is ~12 calls; the platform
cron's two checkpoints are 2. If you run both, the platform cron is redundant — pick one.

## 5. Verify a single run

1. Run the workflow manually.
2. Check the reply: it should name the checkpoint, the record count, and the halted count.
3. Confirm the file exists on `main`:
   `GET https://api.github.com/repos/karizaco/minimax-cloud-outputs/contents/preopen-feed/`
4. Confirm cron #17 can read it:
   `python3 /workspace/preopen_feed.py feed --date <YYYY-MM-DD>`

## 6. If it does not work

- **No records written** — the key check probably fired (`XAI_API_KEY` unset). The capture writes
  nothing rather than writing an empty tape, so "no file" is the expected symptom.
- **Records with `conf: unverified`** — Grok and the scanner disagree. Usually a stale Grok price;
  the consumer drops or flags them. This is the mechanism working, not a bug.
- **`pre-open catalyst feed: absent` in cron #17's Source health** — the feed is optional. The
  digest still runs and the gap-verdict table is still produced from 5-minute bars.
