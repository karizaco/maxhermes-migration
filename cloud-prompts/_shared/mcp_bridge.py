#!/usr/bin/env python3
"""
mcp_bridge.py — call a remote MCP server over streamable-http JSON-RPC.

WHY THIS EXISTS
---------------
The `mcp__yahoo_finance__*` / `mcp__tradingview__*` tools referenced by the original
cron prompts were registered on the LOCAL Windows Mavis, not in agent.minimax.io.
In the cloud runtime the connector catalog holds only media/email tools, so those
tool names do not exist — a prompt that calls them gets a guaranteed tool-not-found.

This script needs NO MCP registration in agent.minimax.io. It speaks JSON-RPC
directly to a public MCP endpoint over HTTPS from the cron sandbox using curl.
Verified working 2026-10-28 from the sandbox:
  stocktwits -> https://gateway.pipeworx.io/stocktwits/mcp
  shibui     -> https://mcp.shibui.finance/mcp

USAGE
  mcp_bridge.py <server> <tool> [args-json-file]
  mcp_bridge.py stocktwits chart_data
  mcp_bridge.py shibui stock_data_query /path/to/args.json

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
}

TIMEOUT = 90


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


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    server, tool = sys.argv[1], sys.argv[2]
    if server not in SERVERS:
        print(json.dumps({"error": f"unknown server: {server}",
                          "known": list(SERVERS)}))
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

    resp = rpc(SERVERS[server], "tools/call",
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
