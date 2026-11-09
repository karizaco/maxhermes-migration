# Cloud cron: Weekly MCP and API health check

READ-ONLY diagnostic. The user only cares if something BROKE or CHANGED. If nothing changed, reply
in under 10 lines.

## CONVERSATION TITLE (do this FIRST, before anything else)

Every scheduled run gets its own conversation — one conversation per fire. Give this conversation a
title that says which day this run belongs to, so the conversation list stays scannable.

1. Resolve today's date in US/Eastern: `TZ=America/New_York date +%d-%m` (day-month, no year).
2. Build the title: `[<DD-MM>] 01-weekly-mcp-health-check`.
3. Set it with one call: `mcp_invoke` with tool_name `session_update` and arguments
   `{"session_id": "me", "title": "<the title>"}`. `me` means THIS conversation.
   If `mcp_invoke` reports that the tool is unknown, call `tool_search` with the query
   "session title update", then retry the same `mcp_invoke` call.
4. If the title cannot be set for any reason, carry on with the routine. This step must never
   block, delay, or fail the report.

# When
Sunday 02:00 America/New_York.

# Output target
1. APPEND one row to `mcp-health/ledger.md` in `https://github.com/karizaco/minimax-cloud-outputs`
   (branch `main`). Create the file with a header row if it does not exist.
2. Also write a full report to `mcp-health/YYYY-Wnn.md` (e.g. `mcp-health/2026-W44.md`).
Single commit. Do NOT open a PR. Do NOT touch any other repo or file.
If the push fails: write the report to your session sandbox and reply with the path. Retry once at most.

Every `curl` in this routine goes to raw.githubusercontent.com or cdn.jsdelivr.net. If curl fails with
a certificate/TLS error — the sandbox egress proxy rotates its leaf cert and it has expired
mid-session before — retry the SAME url with `web_fetch`, which uses a different egress. If both
fail, report it as `probe_failed:<reason>` and carry on; never report a status you did not measure.

# Steps — IN ORDER

## 0. Env probe (first)
```
echo "GITHUB_TOKEN=${GITHUB_TOKEN:-<unset>}"
echo "Token length: ${#GITHUB_TOKEN}"
echo "All env var names: $(env | cut -d= -f1 | sort | tr '\n' ' ')"
```

## 0. Token Plan quota probe — the account's own headroom (advisory)

Run `cloud-prompts/_shared/quota_check.sh` first (fetch it the same way as `mcp_bridge.py` below).
It is ADVISORY and fails open: with no `MINIMAX_API_KEY` it says the probe is unavailable and
exits 0, and that is NOT an error and NOT a reason to skip the check. With a key it reports how
much of the Token Plan 5-hour window is left and when it frees.

A weekly check is the natural place to see the window's headroom, because the 5-hour window is
what takes a whole morning block down when it runs out — on 2026-11-05 the 08:30 ET slot fired
three routines in one minute and the window was exhausted by 08:30, which cost the fleet every
fire from 08:30 to 09:50. Report the window state in the ledger row and in the reply when it is
low; a 5-hour window that is nearly gone is a billing problem the operator needs to hear about
before the next morning, not after it.

## 1. Connector-catalog probe — THE POINT OF THIS ROUTINE
```bash
mcode-tools connector tools 2>/dev/null | python3 -c "
import sys,json,re
raw=sys.stdin.read()
try: ts=json.loads(raw).get('tools',[])
except Exception:
    print('catalog_unreachable'); raise SystemExit
names=[t.get('tool_name','') for t in ts]
fin=[n for n in names if re.search(r'yahoo|tradingview|shibui|stocktwits|financekit|finviz|barchart|market|quote|alpha_vantage|fmp|polygon|tiingo',n,re.I)]
print(f'catalog_ok total={len(names)} finance_tools={len(fin)}')
for n in fin[:40]: print('   ',n)
"
```
**Report exactly one of three states — they are NOT interchangeable:**
- `catalog_ok total=N finance_tools=0` — healthy, no financial MCP registered yet.
- `catalog_ok total=N finance_tools=K` — A FINANCIAL MCP HAS LANDED. Lead the reply with this.
- `catalog_unreachable` — the probe failed (seen 2026-10-21 as `error: invalid signature`).
  This is NOT "no MCPs exist". Record it as a probe failure and carry on.

## 2. Bridge-packs probe
```bash
BR=/workspace/mcp_bridge.py
# --- fetch cloud-prompts/_shared/mcp_bridge.py ---
# The CONTENTS API is authoritative and is NOT CDN-cached. The two CDNs cache `main`
# independently: measured 2026-11-04, raw.githubusercontent served a STALE blob for >17
# minutes after a push while jsDelivr was fresh. The OLD `[ -s file ] || curl` loop could
# NEVER reach its fallback - the first successful download satisfied the guard, so the
# second URL was DEAD CODE. Now all three are tried, and a 404 body (non-empty JSON) is
# rejected on its BODY, not on its byte count.
S=/workspace/mcp_bridge.py
for U in \
  "https://api.github.com/repos/karizaco/maxhermes-migration/contents/cloud-prompts/_shared/mcp_bridge.py?ref=main" \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/mcp_bridge.py" \
  "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/mcp_bridge.py" ; do
  curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" \
    -H "Authorization: Bearer ${GITHUB_TOKEN}" -o "$S.tmp" "$U" 2>/dev/null
  if [ -s "$S.tmp" ] && ! head -c 200 "$S.tmp" | grep -q '"message"'; then
    mv -f "$S.tmp" "$S"; break
  fi
  rm -f "$S.tmp"
done
if [ -s "$BR" ]; then
  python3 "$BR" --list-packs 2>&1 | head -40
  printf '%s' '{"symbols":"SPY,QQQ"}' > /tmp/probe.json
  for p in stocktwits shibui market-recap; do
    python3 "$BR" "$p" get_quotes /tmp/probe.json 2>&1 | head -c 180; echo
  done
else
  echo "bridge fetch FAILED"
fi
```
Record which packs answer. A pack that errors is a degradation, not a failure of the routine.

## 3. HTTP endpoint probe
One cheap request each; never retry a failure more than once:
bridge `market-recap` `get_quotes`; Yahoo chart; Yahoo screener; TradingView scanner
(`POST https://scanner.tradingview.com/america/scan`); Nasdaq market movers
(`https://api.nasdaq.com/api/marketmovers?market=stocks`); SEC EDGAR full-text
(`https://efts.sec.gov/LATEST/search-index?q=%22definitive%20agreement%22&forms=8-K`); CoinGecko;
US Treasury yield-curve CSV. The authoritative endpoint list and measured status is in
`cloud-prompts/_shared/RUNTIME-CONTRACT.md` section 2a in karizaco/maxhermes-migration.

## 4. Local stdio MCP servers — the install-on-demand surface

Two finance MCPs are NOT registered on the platform and are NOT on the Pipeworx gateway, but they
ARE pip-installable and they work as local stdio servers. They are invisible to every other probe
in this routine, so probe them here. The script installs them — the `mcp<2` pin is MANDATORY,
because the packages bundle mcp 2.x where `FastMCP` was renamed `MCPServer` — and prints one line
per server with its tool count:

```bash
S=/workspace/stdio_mcp_probe.sh
# --- fetch cloud-prompts/_shared/stdio_mcp_probe.sh ---
# The CONTENTS API is authoritative and is NOT CDN-cached. The two CDNs cache `main`
# independently: measured 2026-11-04, raw.githubusercontent served a STALE blob for >17
# minutes after a push while jsDelivr was fresh. The OLD `[ -s file ] || curl` loop could
# NEVER reach its fallback - the first successful download satisfied the guard, so the
# second URL was DEAD CODE. Now all three are tried, and a 404 body (non-empty JSON) is
# rejected on its BODY, not on its byte count.
S=/workspace/stdio_mcp_probe.sh
for U in \
  "https://api.github.com/repos/karizaco/maxhermes-migration/contents/cloud-prompts/_shared/stdio_mcp_probe.sh?ref=main" \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/stdio_mcp_probe.sh" \
  "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/stdio_mcp_probe.sh" ; do
  curl -sL --max-time 30 -H "Accept: application/vnd.github.raw" \
    -H "Authorization: Bearer ${GITHUB_TOKEN}" -o "$S.tmp" "$U" 2>/dev/null
  if [ -s "$S.tmp" ] && ! head -c 200 "$S.tmp" | grep -q '"message"'; then
    mv -f "$S.tmp" "$S"; break
  fi
  rm -f "$S.tmp"
done
sh "$S" 2>&1 | head -10
```

The install takes about a minute. Record both counts. A count of `0` means the install or the
handshake failed — record it as `probe_failed:<reason>`, NEVER as "no tools exist". Measured
2026-11-01: `tradingview-mcp` = 73 tools, `financekit-mcp` = 17 tools.

**If either count CHANGED, lead the reply with it.** A finance MCP appearing — or gaining or
losing tools — changes how every digest routine should be run. That is the single most important
thing this weekly routine can tell you.

## 5. Ledger row
Append to `mcp-health/ledger.md` on `main` — one row per run, in this shape:

| <YYYY-MM-DD> | <catalog state> | <packs OK> | <endpoint statuses> | <what changed> |

The `what changed` cell MUST name the stdio counts when they moved, e.g.
`tradingview-mcp 73 tools (NEW), financekit-mcp 17 tools (NEW)`. A row saying "no change" is the
expected outcome most weeks — that is how the diff becomes readable.

## 6. Weekly report
`mcp-health/YYYY-Wnn.md`: the three catalog states, the pack table, the endpoint table, the
**stdio server table** (server name, tool count, install ok/failed), and a short "changed since
last week" section.

# Rules
- Never fabricate a status. A failed probe is `probe_failed:<reason>`.
- A `catalog_unreachable` week must NEVER be recorded as "no MCPs exist".
- If a financial MCP appeared, the reply leads with that fact — it changes how every digest
  routine should be run.
- If a contract endpoint is down, the reply names it — the digests fall back to it silently.
- Do not modify any other file in any other repo.

# Reply
Under 10 lines unless something changed. Lead with the delta, not with what is still fine.
One line for push status, one line for `errors: <n>` (count of probe failures).

The push line ALSO carries this check's own DELIVERY LATENCY, and a platform stall counts in
`errors:`. The platform's run record measures the DISPATCH of the prompt to the agent (~1 s), not
the work: on 2026-11-05 cron #26's 08:30 ET fire closed in 1.288 s with `status: 1` and its
artifact did not appear for 21.4 hours. A weekly health check that arrived 20 hours late is
itself a finding, so report it.

- `push: ok (verified) - delivered 03:07 ET, 67 min after the 02:00 fire` - the latency is the
  wall clock at the push minus this check's own scheduled fire time (02:00 ET).
- If the fire was BLOCKED before its first tool call (the platform's delay between the dispatch
  and the turn actually starting), count ONE error for it and add a `stalled:` line naming the
  cause - read your OWN session's previous turn (`session_messages` on your own session id) and
  quote the error it ended on, e.g. `42212: Token Plan usage limit reached ... (2056)`, or say
  `stalled: the fire was blocked <n> min before its first tool call (no error recorded)`.
  `errors: 0` on a stalled fire is a lie: the report may be clean and the schedule was not.