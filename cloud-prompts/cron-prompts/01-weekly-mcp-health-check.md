# Cloud cron: Weekly MCP and API health check

READ-ONLY diagnostic. The user only cares if something BROKE or CHANGED. If nothing changed, reply
in under 10 lines.

# When
Sunday 02:00 America/New_York.

# Output target
1. APPEND one row to `mcp-health/ledger.md` in `https://github.com/karizaco/minimax-cloud-outputs`
   (branch `main`). Create the file with a header row if it does not exist.
2. Also write a full report to `mcp-health/YYYY-Wnn.md` (e.g. `mcp-health/2026-W44.md`).
Single commit. Do NOT open a PR. Do NOT touch any other repo or file.
If the push fails: write the report to your session sandbox and reply with the path. Retry once at most.

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

## 4. Ledger row
Append to `mcp-health/ledger.md` on `main`:
`| <YYYY-MM-DD> | <catalog state> | <packs OK> | <endpoint statuses> | <what changed> |`
"What changed" must say `no change` or name the specific delta. A row saying "no change" is the
expected outcome most weeks — that is how the diff becomes readable.

## 5. Weekly report
`mcp-health/YYYY-Wnn.md`: the three catalog states, the pack table, the endpoint table, and a
short "changed since last week" section.

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