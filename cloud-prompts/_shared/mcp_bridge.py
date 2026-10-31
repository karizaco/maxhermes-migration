#!/usr/bin/env python3
"""
mcp_bridge.py — call a remote MCP server over streamable-http JSON-RPC.

WHY THIS EXISTS
---------------
The `mcp__yahoo_finance__*` / `mcp__tradingview__*` tools referenced by the original
cron prompts were registered on the LOCAL Windows Mavis, not in agent.minimax.io.
In the cloud runtime the connector catalog holds only media/email/github tools, so
those tool names do not exist — a prompt that calls them gets a guaranteed
tool-not-found.

This script needs NO MCP registration in agent.minimax.io. It speaks JSON-RPC
directly to a public MCP endpoint over HTTPS from the cron sandbox using curl.
Verified working from the sandbox:
  stocktwits   -> https://gateway.pipeworx.io/stocktwits/mcp
  shibui       -> https://mcp.shibui.finance/mcp
  market-recap -> https://gateway.pipeworx.io/market-recap/mcp   (2026-10-31)
  cftc-cot     -> https://gateway.pipeworx.io/cftc-cot/mcp       (2026-10-31)

Any pack on the pipeworx gateway resolves without a code change — pass the pack
name and it falls back to https://gateway.pipeworx.io/{pack}/mcp.

USAGE
  mcp_bridge.py <server> <tool> [args-json-file]
  mcp_bridge.py market-recap get_quotes args.json
  mcp_bridge.py shibui stock_data_query /path/to/args.json
  mcp_bridge.py --list-packs ["discovery query"]

args-json-file may be omitted for tools that take no arguments.
Passing args via FILE avoids shell-quoting corruption of JSON.

EXIT CODES
  0 = tool call succeeded (stdout carries the tool's text content)
  1 = transport or tool error (stdout is a JSON error object)
  2 = usage / bad input
"""

import json
import subprocess
import sys

SERVERS = {
    "stocktwits": "https://gateway.pipeworx.io/stocktwits/mcp",
    "shibui": "https://mcp.shibui.finance/mcp",
    # gateway packs (2026-10-31):
    "market-recap": "https://gateway.pipeworx.io/market-recap/mcp",
    "cftc-cot": "https://gateway.pipeworx.io/cftc-cot/mcp",
}

# Any other pack name resolves through the gateway template.
GATEWAY_TEMPLATE = "https://gateway.pipeworx.io/{pack}/mcp"

TIMEOUT = 90

# Tool that can enumerate packs without being tied to one.
DISCOVERY_TOOL = "discover_tools"


def resolve(server):
    """Map a server/pack name to an endpoint URL."""
    if server in SERVERS:
        return SERVERS[server]
    if server and all(c.isalnum() or c in "-_" for c in server):
        return GATEWAY_TEMPLATE.format(pack=server)
    return None


def rpc(url, method, params=None, timeout=TIMEOUT):
    """One JSON-RPC round trip. Returns a parsed dict, or an error dict."""
    body = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        body["params"] = params
    try:
        p = subprocess.run(
            [
                "curl", "-s", "-N", "--max-time", str(timeout), "-X", "POST", url,
                "-H", "Content-Type: application/json",
                "-H", "Accept: application/json, text/event-stream",
                "-d", json.dumps(body),
            ],
            capture_output=True, text=True, timeout=timeout + 15,
        )
    except subprocess.TimeoutExpired:
        return {"error": "timeout", "detail": f"no response in {timeout}s"}
    out = p.stdout
    # Plain JSON response.
    try:
        return json.loads(out)
    except Exception:
        pass
    # Server-sent-events framing: take the last complete data: payload.
    for line in reversed(out.splitlines()):
        if line.startswith("data: "):
            try:
                return json.loads(line[6:])
            except Exception:
                continue
    return {"error": "unparseable_response", "raw": out[:400]}


def list_packs(query="market data quotes screener movers"):
    """Enumerate packs on the gateway via the discovery tool."""
    url = SERVERS["market-recap"]
    resp = rpc(url, "tools/call",
               {"name": DISCOVERY_TOOL, "arguments": {"query": query}})
    if not isinstance(resp, dict) or "result" not in resp:
        return {"error": "discovery_failed", "response": resp}
    chunks = [c.get("text", "") for c in resp["result"].get("content", [])
              if c.get("type") == "text"]
    text = "\n".join(chunks)
    try:
        data = json.loads(text)
    except Exception:
        return {"error": "discovery_unparseable", "raw": text[:400]}
    packs = {}
    for t in data.get("tools", []):
        pack = t.get("pack")
        if pack:
            packs.setdefault(pack, []).append(t.get("name"))
    return {"query": query, "packs": packs}


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "--list-packs":
        query = sys.argv[2] if len(sys.argv) > 2 else \
            "market data quotes screener movers"
        result = list_packs(query)
        print(json.dumps(result, indent=2))
        return 0 if "packs" in result else 1

    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    server, tool = sys.argv[1], sys.argv[2]
    url = resolve(server)
    if url is None:
        print(json.dumps({"error": f"unknown server: {server}",
                          "known": list(SERVERS),
                          "note": "any pack name resolves via "
                                  + GATEWAY_TEMPLATE}))
        return 2

    args = {}
    if len(sys.argv) > 3:
        try:
            with open(sys.argv[3], encoding="utf-8") as fh:
                args = json.load(fh)
        except Exception as exc:
            print(json.dumps({"error": f"cannot read args file: {exc}"}))
            return 2
    elif not sys.stdin.isatty():
        piped = sys.stdin.read().strip()
        if piped:
            try:
                args = json.loads(piped)
            except Exception as exc:
                print(json.dumps({"error": f"bad stdin json: {exc}"}))
                return 2

    resp = rpc(url, "tools/call",
               {"name": tool, "arguments": args})
    if not isinstance(resp, dict) or "result" not in resp:
        print(json.dumps({"error": "rpc_failed", "response": resp}))
        return 1
    result = resp["result"]
    if result.get("isError"):
        print(json.dumps({"error": "tool_error", "detail": result.get("content")}))
        return 1
    chunks = [c.get("text", "") for c in result.get("content", [])
              if c.get("type") == "text"]
    if not chunks:
        print(json.dumps({"error": "empty_content", "result": result}))
        return 1
    print("\n".join(chunks))
    return 0


if __name__ == "__main__":
    sys.exit(main())
