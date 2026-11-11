# Cloud Mavis cron: earnings-reaction-settlement (cron #15b) — NEW 2026-11-11

You are running as a Cloud Mavis cron on Mavis. Linux sandbox: no PowerShell, no Windows paths.
Output root: /workspace/ (mkdir -p it if missing).

## WHAT THIS SLOT IS

The 08:00 ET scan (#15) publishes the EU/UK session **mid-flight** — the European cash session
closes at 11:30 ET in winter — so its EU move is a snapshot taken minutes after the reaction
started. Measured against each session's settled close over the 2026-11-05/06/09 runs: the median
EU row finished **0.9–2.1pp** away from its printed move, the worst **12.7pp**, and roughly
**half** the rows were more than 1pp off.

**This slot republishes the same rows with their SETTLED close and move**, and carries the
morning's move beside each one, so the reader can see how much of the reaction survived — and so
the routine measures its own live snapshot instead of asking the reader to trust it.

It publishes **no US rows**: at 12:15 ET the US cash session is OPEN, so the screener's `close`
and `change` for a US name are live intraday values. Publishing those as a session close would be
a fabricated settle.

## CONVERSATION TITLE (do this FIRST, before anything else)

Every scheduled run gets its own conversation. Give this one a title that says which day it
belongs to:

1. Resolve today's date in US/Eastern: `TZ=America/New_York date +%d-%m` (day-month, no year).
2. Build the title: `[<DD-MM>] 15b-earnings-reaction-settlement`.
3. Set it with one call: `mcp_invoke` with tool_name `session_update` and arguments
   `{"session_id": "me", "title": "<the title>"}`.
4. If the title cannot be set for any reason, carry on. This step must never block the artifact.

## SCHEDULE

Fires 12:15 ET on weekdays: cron `15 12 * * 1-5`, timezone America/New_York. That is 45 minutes
after the European close in winter (16:30 CET) and 1h45m after it in summer (16:30 CEST).

## WINDOW CHECK (RUN FIRST, BEFORE FETCHING THE PIPELINE)

The gate below is the ONE shared implementation for the whole fleet — fetch it and run it.

```bash
cd /workspace
S=/workspace/window_check.sh
for U in \
  "https://api.github.com/repos/karizaco/maxhermes-migration/contents/cloud-prompts/_shared/window_check.sh?ref=main" \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/window_check.sh" \
  "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/window_check.sh" ; do
  curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" \
    -H "Authorization: Bearer ${GITHUB_TOKEN}" -o "$S.tmp" "$U" 2>/dev/null
  if [ -s "$S.tmp" ] && grep -q 'WINDOW_CHECK_V2' "$S.tmp" 2>/dev/null; then
    mv -f "$S.tmp" "$S"; break
  fi
  rm -f "$S.tmp"
done
if [ ! -s "$S" ]; then echo "window-check: UNAVAILABLE - continue and say so"; fi

SCHEDULED_AT_MS=$(mcp_invoke --tool_name session_get --arguments '{"session_id":"me"}' \
  | python3 -c "import sys,json;b=json.load(sys.stdin);print(b['response']['session']['created_at'])")

sh "$S" --scheduled-at-ms "$SCHEDULED_AT_MS" \
   --out earnings --name earnings_reaction_settlement \
   --label "Cron #15b earnings-reaction-settlement" \
   --market-hours 1200-1300 --nn 15b
```

If the gate exits non-zero, the fire is OUT OF WINDOW: do not fetch the pipeline, do not write an
artifact. The skip marker the gate writes IS the artifact for that day.

## STEP 2 — FETCH THE PIPELINE

The pipeline is the same file cron #15 runs, in `--mode settle`. Fetch it from the AUTHORITATIVE
channels first (the CDNs cache independently and can serve stale bytes for minutes to hours):

1. the **GitHub connector** (`connector__github__get_file_contents`) — authenticated, never
   CDN-cached;
2. the **contents API** with the sandbox token;
3. the **CDN copies** — last resort only.

**Validate the BODY, never the status code.** The copy must carry the `SCRIPT_VERSION` marker,
the **`REACTION_ARTIFACT_V2` capability marker**, and compile cleanly.

```bash
cd /workspace
mkdir -p scripts
S=scripts/earnings_reaction_scanner.py
valid() { [ -s "$1" ] && grep -q 'SCRIPT_VERSION' "$1" 2>/dev/null \
          && grep -q 'REACTION_ARTIFACT_V2' "$1" 2>/dev/null \
          && python3 -c "import sys;compile(open(sys.argv[1]).read(),'x','exec')" "$1" 2>/dev/null; }

mcode-tools connector call connector__github__get_file_contents \
  --args '{"owner":"karizaco","repo":"minimax-cloud-outputs","path":"scripts/earnings_reaction_scanner.py","ref":"refs/heads/main"}' 2>/dev/null \
  | python3 -c "import sys,json;b=json.load(sys.stdin);sys.stdout.write(''.join((x.get('resource') or {}).get('text','') for x in b if isinstance(x,dict)))" > "$S.tmp" 2>/dev/null
valid "$S.tmp" && mv -f "$S.tmp" "$S"

[ -s "$S" ] || curl -sSL --max-time 30 -H "Accept: application/vnd.github.raw" \
  -H "Authorization: Bearer ${GITHUB_TOKEN}" \
  -o "$S.tmp" "https://api.github.com/repos/karizaco/minimax-cloud-outputs/contents/scripts/earnings_reaction_scanner.py?ref=main" 2>/dev/null
valid "$S.tmp" && mv -f "$S.tmp" "$S"

[ -s "$S" ] || curl -sSL --max-time 30 -o "$S.tmp" \
  "https://raw.githubusercontent.com/karizaco/minimax-cloud-outputs/main/scripts/earnings_reaction_scanner.py" 2>/dev/null
valid "$S.tmp" && mv -f "$S.tmp" "$S"
rm -f "$S.tmp"

if [ -s "$S" ]; then grep -m1 'SCRIPT_VERSION' "$S"; else echo "pipeline fetch FAILED"; fi
```

If no channel yields a valid script, report `errors: 1` and stop — never improvise the artifact.

## SHARED INSTRUCTIONS (fetch once — these rules apply to every routine)

```bash
B=https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared
for F in PROMPT-BLOCKS.md; do
  [ -s "/workspace/$F" ] || curl -sSL --max-time 30 -o "/workspace/$F" "$B/$F"
done
```

Read `/workspace/PROMPT-BLOCKS.md` and follow its `## DELIVERY` section.

## STEP 3 — RUN THE PIPELINE IN SETTLEMENT MODE

```bash
cd /workspace
python3 scripts/earnings_reaction_scanner.py --mode settle
```

It writes `/workspace/earnings/<date>-reactions-settled.md` and prints the settlement summary
(`mode: settle`, `eu_rows`, `scan_matched`, `scan_to_settle_max_pp`, `degraded_sources`).
**Give it a generous timeout** (at least 560s) — it cross-checks every published row against
Yahoo. It takes ~2-4 minutes: the US, ASX and APAC/Gulf passes are skipped in this mode.

**No catalyst research happens in this slot.** The settlement artifact reuses the morning's
catalyst file (`/workspace/catalog/catalysts/<date>.md`), which the 08:00 ET run already filled in.
Do **not** run web searches here, and do **not** rewrite the catalog file.

If the morning artifact is missing, the settlement artifact still runs — its `Move @08:00` and
`Δ vs scan` columns read `—` and the source health says the morning artifact was not found. Say
so in `### Method & caveats`.

## STEP 4 — VERIFY THE ARTIFACT AGAINST THE CONTRACT (before the push)

The pipeline renders the contract by construction, but fetch the independent checker and run it.
It exits 1 and names every violation.

```bash
C=/workspace/check_reaction_artifact.py
for U in \
  "https://api.github.com/repos/karizaco/maxhermes-migration/contents/tools/check_reaction_artifact.py?ref=main" \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/tools/check_reaction_artifact.py" \
  "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/tools/check_reaction_artifact.py" ; do
  curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" \
    -H "Authorization: Bearer ${GITHUB_TOKEN}" -o "$C.tmp" "$U" 2>/dev/null
  if [ -s "$C.tmp" ] && grep -q 'REACTION_ARTIFACT_V2' "$C.tmp" 2>/dev/null; then
    mv -f "$C.tmp" "$C"; break
  fi
  rm -f "$C.tmp"
done
if [ -s "$C" ]; then
  python3 "$C" /workspace/earnings/${DATE}-reactions-settled.md || echo "CONTRACT CHECK FAILED - fix the artifact before pushing"
fi
```

If the checker cannot be fetched, say so in `### Method & caveats` and carry on. If it RUNS and
fails, fix the artifact and run it again. **Do not push an artifact the checker rejected.**

## GIT PUSH

```bash
B=https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared
for U in "$B/push_artifact.sh" "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/push_artifact.sh"; do
  [ -s /workspace/push_artifact.sh ] || curl -sL -o /workspace/push_artifact.sh "$U"
done
sh /workspace/push_artifact.sh --out earnings --add earnings/{date}-reactions-settled.md --branch main --nn 15b
sh /workspace/verify_delivery.sh --path earnings/{date}-reactions-settled.md --branch main
```

**If the push script cannot be fetched**, use the inline fallback in
`cloud-prompts/_shared/push_artifact.sh` — but never `git add -A`, and never
`git push … | head -3` (that returns head's exit status and reports a rejected push as success).

## DELIVERY

The reply format is the house standard in `cloud-prompts/_shared/PROMPT-BLOCKS.md` — follow its
`## DELIVERY` section (prose opener, `### Signal`, `### Method & caveats`, `### Files`,
`### Push / errors`).

**What this reply must carry:** the settled EU/UK table's biggest movers, the
`scan_to_settle` measurement (how many rows matched the morning scan, the median and maximum
drift, how many moved more than 1pp) — that number is the point of this slot — and the delivery
latency. The reply's `errors:` count MUST equal the artifact's `degraded_sources:` count.

Do not narrate tool calls. Tool call → result → write → push → reply.

## CRITICAL REMINDERS
1. Window check first. If it says out-of-window, exit cleanly — the SKIPPED file is the artifact.
2. **No US rows in this slot.** The US session is open at 12:15 ET; a live intraday price must
   never be published as a close.
3. **No catalyst research in this slot** — the morning's catalog file already carries the
   catalysts. Do not run web searches here.
4. Read-only. No trade ideas. Never fabricate a value.
5. The `scan_to_settle` drift is the headline of this slot: report it as measured, even when it
   shows the morning snapshot was badly wrong.
6. If the cross-check reports any mismatch, say so in the chat reply.
