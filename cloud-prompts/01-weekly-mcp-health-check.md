# Cloud cron prompt — Weekly MCP and API health check

**Purpose:** detect, as soon as possible, that Minimax Cloud has gained a financial MCP — or that
any data source in the fleet's source stack has broken. This is the **slow lane**; each routine's
in-run MCP-availability probe is the fast lane.

**Changes vs. the 2026-10-28 original:**
1. **Three probe layers**, not one. The original probed env vars and HTTP endpoints only. It now
   also probes the **agent.minimax.io connector catalog** (for newly registered financial MCPs)
   and the **MCP-over-HTTP bridge** (for newly published packs).
2. **Three-state catalog reporting.** `catalog_ok total=N finance_tools=0` (healthy, none yet),
   `catalog_ok total=N finance_tools=K` (one landed), and `catalog_unreachable` (the probe failed
   — seen 2026-10-21 as `error: invalid signature`). The third is NOT evidence that no MCPs exist.
3. **Appends to a running ledger** (`mcp-health/ledger.md`), because a weekly file only shows
   Sunday's state — the *diff* is the answer to "has it landed yet?"
4. **Names the GitHub connector**, which arrived 2026-10-31 and makes the repo push independent of
   `GITHUB_TOKEN`.

## Cron form fields (paste these into agent.minimax.io)

### Name
```
Weekly MCP and API health check
```

### Schedule
```
0 2 * * 0
```

### Timezone
```
America/New_York
```

### Prompt (paste this verbatim into the cron form)

```
You are running the weekly MCP / API health check.

This is a READ-ONLY, SILENT diagnostic. The user only cares if something is broken or something
changed. A successful run with everything unchanged should be terse — under 10 lines of reply.

# When
Sunday 02:00 America/New_York.

# Output target
1. Append one row to `mcp-health/ledger.md` in `https://github.com/karizaco/minimax-cloud-outputs`
   (branch `main`). Create the file if it does not exist, with a header row.
2. Also write a full Markdown report to `mcp-health/YYYY-Wnn.md` (e.g. `mcp-health/2026-W44.md`).
Use a single commit. Do NOT open a PR. Do NOT touch any other repo or file.

If the push fails for any reason (network, auth, missing repo): write the report to your session
sandbox and reply with the file path so the user can recover it manually. Do NOT retry more than
once.

# Steps — execute IN ORDER.

## 0. Env-var probe (FIRST)
Run and include the EXACT output in your reply:
```
echo "GITHUB_TOKEN=${GITHUB_TOKEN:-<unset>}"
echo "Token length: ${#GITHUB_TOKEN}"
echo "All env var names: $(env | cut -d= -f1 | sort | tr '\n' ' ')"
```

## 1. Connector-catalog probe (NEW — this is the point of the routine)
Enumerate the agent.minimax.io connector catalog and look for financial MCPs:

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

**Report exactly one of three states.** They are not interchangeable:
- `catalog_ok total=N finance_tools=0` — healthy, no financial MCP registered yet.
- `catalog_ok total=N finance_tools=K` — **a financial MCP has landed.** Say so prominently in the
  reply, and in the ledger's notes column.
- `catalog_unreachable` — the probe itself failed. This is NOT "no MCPs exist". Record it as a
  probe failure and carry on.

## 2. Bridge-packs probe (NEW)
Fetch the bridge and enumerate the packs it can reach:

```bash
BR=/workspace/mcp_bridge.py
for U in \
  "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/mcp_bridge.py" \
  "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/mcp_bridge.py" ; do
  [ -s "$BR" ] || curl -sL -o "$BR" "$U" 2>/dev/null
done
if [ -s "$BR" ]; then
  python3 "$BR" --list-packs 2>&1 | head -40
  for p in stocktwits shibui market-recap; do
    printf '%s' '{"symbols":"SPY,QQQ"}' > /tmp/probe.json
    python3 "$BR" "$p" get_quotes /tmp/probe.json 2>&1 | head -c 200; echo
  done
else
  echo "bridge fetch FAILED"
fi
```

Record which packs answer and which error. A pack that errors is a **degradation**, not a
failure of the routine.

## 3. HTTP endpoint probe
For each endpoint in `_shared/RUNTIME-CONTRACT.md` section 2a, make ONE cheap request and record
the HTTP status. Do not retry a failure more than once. Keep the list short — the point is
regression detection, not exhaustive probing.

Minimum set: bridge `market-recap` `get_quotes`, Yahoo chart, Yahoo screener, TradingView scanner,
Nasdaq market movers, SEC EDGAR full-text, CoinGecko, US Treasury yield-curve CSV.

## 4. Write the ledger row
Append to `mcp-health/ledger.md` on `main`:

```
| <YYYY-MM-DD> | <catalog state> | <packs OK> | <endpoint statuses> | <what changed> |
```

`## What changed` must say either `no change` or name the specific delta. **A row that says
"no change" is the expected outcome most weeks** — that is how the diff becomes readable.

## 5. Write the weekly report
`mcp-health/YYYY-Wnn.md` with: the three catalog states, the pack table, the endpoint table, and
a short "changed since last week" section.

# Rules
- Never fabricate a status. If a probe failed, write `probe_failed:<reason>`.
- A `catalog_unreachable` week must NOT be recorded as "no MCPs exist".
- If a financial MCP appeared, the reply must lead with that fact, because it changes how every
  digest routine should be run.
- If a source in the RUNTIME-CONTRACT is down, the reply must name it, because the digests fall
  back to it silently.
- Do not modify any other file in any other repo.

# Reply format
Under 10 lines unless something changed. Lead with the delta, not with the status of everything
that is fine. Include one line for push status and one line for `errors: <n>`.
```

---

## Appendix — why the three-state distinction matters

On 2026-10-21 the catalog call failed with `error: invalid signature
(path=/minimax-cloud/api/v1/connectors/connected-tools/list)`. A naive probe would record that as
"0 financial tools — confirmed still absent" and the ledger would carry a false negative for
weeks. The distinction between *catalog healthy and empty* and *catalog unreachable* is the whole
reason this section exists.

On 2026-10-31 the catalog returned **133 tools**: 118 `connector__github__*` (new), 13
`connector__matrix__*`, 2 `connector__email_workbench_credentials__*`. Still **zero** financial
MCPs — but a GitHub connector, which is why the fleet can now write to its repos without a PAT in
the sandbox.
