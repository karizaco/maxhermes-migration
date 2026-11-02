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
for U in \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/mcp_bridge.py" \
  "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/mcp_bridge.py" ; do
  [ -s "$BR" ] || curl -sL -o "$BR" "$U" 2>/dev/null
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

## 3. Local stdio MCP servers — the install-on-demand surface

Two finance MCPs are NOT registered on the platform and are NOT on the Pipeworx gateway, but they
ARE pip-installable and they work as local stdio servers. They are invisible to every other probe
in this routine, so probe them here.

```bash
DIR=/workspace/mcpprobe
mkdir -p "$DIR"
if command -v uv >/dev/null 2>&1; then
  for P in tradingview-mcp financekit-mcp; do
    env -u PIP_INDEX_URL -u UV_INDEX_URL \
      UV_DEFAULT_INDEX="https://pypi.org/simple" UV_INDEX_URL="https://pypi.org/simple" \
      uv pip install --python python3.11 --target "$DIR" "mcp<2" "$P" >/dev/null 2>&1 \
      || echo "install_failed:$P"
  done
fi
```

Then count the tools each server exposes. The `mcp<2` pin is MANDATORY — the packages bundle mcp
2.x, where `FastMCP` was renamed `MCPServer`, and without the pin the server dies with
`No module named 'mcp.server.fastmcp'`. The console script is `financekit`, NOT `financekit-mcp`.

```bash
python3 - <<'PYEOF'
import json, os, subprocess, time

def probe(cmd):
    try:
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, text=True, bufsize=1,
                             env={**os.environ, "PYTHONPATH": "/workspace/mcpprobe"})
        def send(o):
            p.stdin.write(json.dumps(o) + "\n"); p.stdin.flush()
        def recv(t=45):
            end = time.time() + t
            while time.time() < end:
                line = p.stdout.readline()
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    return json.loads(line)
                except Exception:
                    pass
            return {}
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
              "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                         "clientInfo": {"name": "probe", "version": "1"}}})
        recv()
        send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        r = recv()
        n = len((r or {}).get("result", {}).get("tools", []))
        p.kill()
        return n
    except Exception as exc:
        return "probe_failed:%s" % exc

for name, cmd in (("tradingview-mcp", ["/workspace/mcpprobe/bin/tradingview-mcp"]),
                  ("financekit-mcp", ["/workspace/mcpprobe/bin/financekit"])):
    print("%s: tools=%s" % (name, probe(cmd)))
PYEOF
```

Record both counts. A count of `0` means the install or the handshake failed — record it as
`probe_failed:<reason>`, NEVER as "no tools exist". Measured 2026-11-01: `tradingview-mcp` = 73
tools, `financekit-mcp` = 17 tools.

**If either count CHANGED, lead the reply with it.** A finance MCP appearing — or gaining or
losing tools — changes how every digest routine should be run. That is the single most important
thing this weekly routine can tell you.

## 4. Ledger row
Append to `mcp-health/ledger.md` on `main`:
`| <YYYY-MM-DD> | <catalog state> | <packs OK> | <endpoint statuses> | <what changed> |

The `what changed` cell MUST name the stdio counts when they moved, e.g.
`tradingview-mcp 73 tools (NEW), financekit-mcp 17 tools (NEW)`. A row saying "no change" is the
expected outcome most weeks — that is how the diff becomes readable.`
"What changed" must say `no change` or name the specific delta. A row saying "no change" is the
expected outcome most weeks — that is how the diff becomes readable.

## 5. Weekly report
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