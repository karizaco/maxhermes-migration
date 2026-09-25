---
name: MCP / API health check
description: >-
  Weekly silent health check of every MCP and external API in the runtime
  profile. Logs response time + success. Surfaces anything broken before
  Monday's pre-market brief fires.
---

# MCP / API health check

Walks every external service the runtime depends on, pings it with a no-op query, and records the result. Read-only and quiet unless something is broken.

## When

- Cron: `0 2 * * 0` America/New_York (Sunday 02:00 ET — way before any market activity)
- Manual: user asks "are all the MCPs working" or "health check the MCPs"

## Output

- `C:\Users\admin\.minimax\projects\coding-shared\research\mcp-health\YYYY-Wnn.md`
- Compact ≤ 10-line summary in reply.
- If any service is down or unusually slow, the reply highlights that — otherwise stays terse.

## Steps

### Built-in / shell services

1. **`gh` CLI**: `gh auth status 2>&1` — capture exit code + a one-line parsed `Logged in to github.com account <user>` or error.
2. **`git`**: `git --version` — sanity check the binary is on PATH.
3. **`web_search` / `web_fetch`**: a single cheap `web_fetch` to `https://example.com` — should return the IANA page. Capture status + bytes.
4. **`uv` / `uvx`**: `uv --version` and `uvx --version`.

### Financial MCPs (5)

For each MCP, make a single cheap call to verify it's still spawning + responding. Record: latency_ms (start-to-result), ok (bool), error (string or null).

5. **`tradingview`** (npx/cmd): `lookup_symbols` on `["NASDAQ:SPY"]`. Expect ≤ 5 s.
6. **`yahoo-finance`** (npx/cmd): `get_stock_quote` on `"AAPL"`. Expect ≤ 5 s.
7. **`tradingview-advanced`** (uv tool): `yahoo_price` on `AAPL` (or `ES=F`). First call after a uv cache cold-start may be slower — record but don't alarm.
8. **`financekit`** (uvx): `stock_quote` for `AAPL`. Same cold-start caveat.
9. **`shibui-finance`** (HTTP): a JSON-RPC `initialize` POST with `Accept: application/json, text/event-stream`. Expect ≤ 5 s.

### Compose the report

10. Markdown table with columns: service | transport | latency_ms | status | error
11. Top section: any service with status != ok gets a 🚨 prefix.
12. Bottom: trend (compare latency to last 4 weeks if `mcp-health/` has prior files; otherwise write "no trend baseline yet").
13. Append audit line: `mcp_health_check target=mcp-health:<isoweek> ok=<n> fail=<n>`.

## Hard rules

- Read-only. Never make a state-changing call (no orders, no commits, no writes).
- Never spend >10 s on any single ping — bail with "timeout" if it exceeds that.
- Never retry a failing service in the same run — just record the failure.
- Never auto-disable a failing MCP. Report and stop; let the user decide.

## Out of scope

- Fixing the MCPs themselves — that's a debugging session.
- Benchmarking — just liveness + latency.
- Running any data fetches beyond the no-op ping (no quotes, no screenshots).
