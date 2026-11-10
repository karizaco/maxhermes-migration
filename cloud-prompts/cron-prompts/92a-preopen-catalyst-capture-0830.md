# Cloud Mavis cron: preopen-catalyst-capture (cron #92)

Captures the pre-open **catalyst tape**: for each US stock materially moving pre-market or at the
open, record WHO / WHAT / WHEN, with ground-truth prices from the movers scan — a gainers half
and a losers half, so the decliners are on the tape too. Cron #17
(`us-stocks-in-play`, 15:50 ET) reads the tape to explain why a stock moved and when the news
broke — the one thing no price feed can tell it.

The procedure lives in ONE shared file, not in every prompt. Fetch it in the same first step as
the skill spec, then follow it in full:

```bash
# Fetch FOUR sources and take the one carrying the HIGHEST PROCEDURE_VERSION marker.
# The CONTENTS API is tried first: it is authoritative and is NOT CDN-cached. The two CDNs
# cache `main` independently — measured 2026-11-04, raw.githubusercontent served a stale blob
# for >17 minutes after a push while jsDelivr was fresh — and the old single-pass loop could
# NEVER reach its fallback, because the first successful download satisfied the file-exists
# guard. A version marker, not an exit code, decides which copy is current.
#
# A version marker alone is NOT enough. Measured 2026-11-05: ALL THREE mirrors served the
# SAME stale blob (v2026-11-04.3, 13,271 B) while the repo's current blob was v2026-11-05.1
# (16,452 B) — "highest version wins" picked a stale file precisely because EVERY copy was
# stale. So add a FOURTH source: the git blob API for the sha the contents API's METADATA
# names. That blob IS the tip of `main`, so its version is never lower than any mirror's and
# the existing "highest version wins" rule then selects it automatically.
rm -f /tmp/pc_a.md /tmp/pc_b.md /tmp/pc_c.md /tmp/pc_d.md
PC_SHA=$(curl -sL --max-time 30 -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer ${GITHUB_TOKEN}" \
  "https://api.github.com/repos/karizaco/maxhermes-migration/contents/cloud-prompts/_shared/preopen-capture.md?ref=main" 2>/dev/null \
  | python3 -c "import json,sys; print(json.load(sys.stdin).get('sha',''))" 2>/dev/null)
if [ -n "$PC_SHA" ]; then
  curl -sL --max-time 30 -H "Accept: application/vnd.github+json" \
    -H "Authorization: Bearer ${GITHUB_TOKEN}" \
    "https://api.github.com/repos/karizaco/maxhermes-migration/git/blobs/$PC_SHA" 2>/dev/null \
    | python3 -c "import json,sys,base64; sys.stdout.write(base64.b64decode(json.load(sys.stdin)['content']).decode('utf-8','replace'))" \
    > /tmp/pc_d.md 2>/dev/null
fi
curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" \
  -H "Authorization: Bearer ${GITHUB_TOKEN}" \
  -o /tmp/pc_c.md \
  "https://api.github.com/repos/karizaco/maxhermes-migration/contents/cloud-prompts/_shared/preopen-capture.md?ref=main" 2>/dev/null
curl -sL --max-time 30 -o /tmp/pc_a.md \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/preopen-capture.md" 2>/dev/null
curl -sL --max-time 30 -o /tmp/pc_b.md \
  "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/preopen-capture.md" 2>/dev/null
python3 - <<'PYEOF'
import re
best=None;bv=None
for f in ("/tmp/pc_d.md","/tmp/pc_c.md","/tmp/pc_a.md","/tmp/pc_b.md"):
    try: t=open(f,encoding="utf-8",errors="replace").read()
    except Exception: continue
    if not t.strip() or t.lstrip()[:200].find('"message"')>=0: continue
    m=re.search(r"PROCEDURE_VERSION:\s*(\d{4})-(\d{2})-(\d{2})\.(\d+)",t)
    v=(int(m.group(1)+m.group(2)+m.group(3)),int(m.group(4))) if m else (-1,-1)
    if bv is None or v>bv: bv=v;best=f
if best:
    # read+write, NOT os.replace: /tmp and /workspace are on DIFFERENT filesystems and
    # rename(2) across them fails with EXDEV (caught by test 2026-11-04).
    open("/workspace/preopen-capture.md","w",encoding="utf-8").write(
        open(best,encoding="utf-8",errors="replace").read())
    print("procedure: version %s.%s from %s"%(bv[0],bv[1],best))
else:
    open("/workspace/preopen-capture.md","w").write(
        "PROCEDURE_FETCH_FAILED: no copy of preopen-capture.md could be fetched from the "
        "GitHub contents API, raw.githubusercontent or jsDelivr.\nStop here. Report "
        "`probe_failed:procedure_fetch` and write NOTHING.\n")
    print("procedure: FETCH FAILED")
PYEOF
```

Then follow `/workspace/preopen-capture.md` in full. It contains the key check, the capture
script fetch, the movers scan in BOTH directions, the board renderer and the push steps.

**If this prompt and the procedure file ever disagree, THE PROCEDURE FILE WINS.** It carries a
`PROCEDURE_VERSION` marker and is fetched at run time, so it is the newer of the two — this
prompt's summary is only a summary, and a stale copy of this prompt must never override it.

If curl fails with a certificate/TLS error (the sandbox egress proxy rotates its leaf cert and has
expired mid-session before), fall back to `web_fetch` on the SAME url. If both fail, report
`probe_failed:<reason>` and stop — never improvise the procedure from memory.

## CONVERSATION TITLE (do this FIRST, before anything else)

Every scheduled run gets its own conversation — one conversation per fire, never appended to an
earlier run's conversation. Give this conversation a title that says which day this run belongs
to, so the conversation list stays scannable.

1. Resolve today's date in US/Eastern: `TZ=America/New_York date +%d-%m` (day-month, no year).
2. Build the title: `[<DD-MM>] 92a-preopen-catalyst-capture-0830` — substitute the date you just resolved.
3. Set it with one call: `mcp_invoke` with tool_name `session_update` and arguments
   `{"session_id": "me", "title": "<the title>"}`. `me` means THIS conversation.
   If `mcp_invoke` reports that the tool is unknown, call `tool_search` with the query
   "session title update", then retry the same `mcp_invoke` call.
4. If the title cannot be set for any reason, carry on with the routine. This step must never
   block, delay, or fail the artifact.

## THIS FIRE

- **Checkpoint:** the capture writes `preopen-feed/{date}-{HHMM}.jsonl`, where `{HHMM}` is the
  fire's **scheduled ET SLOT** and `{date}` is the fire's date — NEVER the wall clock at write
  time. Derive both from `session.created_at` (the procedure's step 2 calls it `FIRE_MS`): the
  platform can stall a fire by hours, so a late run must still be named for the slot it was
  dispatched for. Measured 2026-11-05: a slot's work began at 10:09 ET after a
  platform stall, and a wall-clock slot would have named its file `1010` — a phantom slot that
  sorts AFTER the real checkpoint, so a consumer merging the checkpoints oldest-first replays
  that tape LAST. Each checkpoint still writes its own file, so two captures can never
  clobber each other. The procedure now ASSERTS the slot is one of `0830` / `0920` / `0950` and
  snaps a late dispatch onto the slot it belongs to, because cron #17 merges the checkpoints by
  slot name and a `0835` file is invisible to it.
- **Two files, one fire.** Every successful checkpoint writes the tape
  (`preopen-feed/{date}-{HHMM}.jsonl`) AND a companion **digest** at `preopen-feed/{date}-{HHMM}.md`
  — the top 15 movers with their catalyst, their `conf` token, the record count, the provenance
  split (scanner / stocktwits / pipeworx) and the measured cost ($0.0000 — xAI's live search is
  retired, so Grok is not used). The 08:30 checkpoint is the one a trader can act on before
  the open.
- **The key check comes first.** If `${PIPEWORX_API_KEY}` is unset, write NO tape and write
  `preopen-feed/{date}-{HHMM}.SKIPPED.md` naming the reason, then push that marker. That is the
  key the capture script actually uses: **xAI is not used at all** (its chat API no longer serves
  live search), so `${XAI_API_KEY}` says nothing about whether this checkpoint can run. The
  procedure does it; do not improvise it. Never fabricate a tape, and never leave a checkpoint
  with no trace at all.
- **Order of attack:** ONE capture script (`preopen_capture.py`) → the tape → the board
  (`preopen_digest.py`) → push. The script makes four calls: a trending snapshot for the
  narrative, a movers scan in BOTH directions for the ground truth, and a grounded catalyst call
  for the movers the trending call did not explain. **Prices always come from the movers scan; a
  narrative call explains and never prices.** **Do not hand-build the tape:** the rules that
  matter — one snapshot per record, one row per ticker, no price from a narrative call — are
  enforced in the script, and a hand-built tape breaks them silently. The tape is written
  ATOMICALLY, so a slot's file holds exactly ONE snapshot; if you find a second run's rows in
  that file, discard them rather than merging them in.
- **Push** with the shared helper `cloud-prompts/_shared/push_artifact.sh`, staging only
  `preopen-feed/`. Never `git add -A`.

## REPLY

Under 6 lines: the checkpoint slot, the number of records written, the halt state
(`not measurable` — the column is null on every row, never `0`), one line for push status, one
line for `errors: <n>`. Name the digest file. Say `tape_size_deviation` only when the tape is
ONE-SIDED (no decliners on it) — a small tape is not a deviation any more (it is the movers
scan plus the trending snapshot), and a tape that breaks the one-row-per-ticker rule is a
concurrency fault, not a quiet market.
