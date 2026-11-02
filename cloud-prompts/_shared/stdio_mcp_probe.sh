#!/bin/sh
# POSIX sh (dash-compatible) - runs identically under `sh` or `bash`.
# stdio_mcp_probe.sh — probe the locally installable stdio finance MCP servers.
#
# WHY THIS EXISTS
# ---------------
# Two finance MCPs are NOT registered on the platform and are NOT on the Pipeworx gateway, but
# they ARE pip-installable and they work as local stdio servers. That surface is invisible to
# every other probe the fleet runs, so cron #01 calls this and reports the tool counts.
#
# Measured 2026-11-01: tradingview-mcp = 73 tools, financekit-mcp = 17 tools.
#
# THE mcp<2 PIN IS MANDATORY
# ---------------------------
# Both packages bundle mcp 2.x, where FastMCP was renamed MCPServer. Without the pin the server
# dies with `ModuleNotFoundError: No module named 'mcp.server.fastmcp'`. `uv` resolves the pin
# to mcp 1.30.0. The console script is `financekit`, NOT `financekit-mcp`.
#
# USAGE
#   stdio_mcp_probe.sh
#
# OUTPUT (stdout) - one line per server:
#   tradingview-mcp: tools=73
#   financekit-mcp: tools=17
#   <name>: probe_failed:<reason>      <- the install or the handshake failed. NEVER "no tools".
set -u

DIR="${STDIO_MCP_DIR:-/workspace/mcpprobe}"

if command -v uv >/dev/null 2>&1; then
  mkdir -p "$DIR" 2>/dev/null || true
  for P in tradingview-mcp financekit-mcp; do
    if ! env -u PIP_INDEX_URL -u UV_INDEX_URL \
         UV_DEFAULT_INDEX="https://pypi.org/simple" UV_INDEX_URL="https://pypi.org/simple" \
         uv pip install --python python3.11 --target "$DIR" "mcp<2" "$P" >/dev/null 2>&1; then
      echo "$P: probe_failed:install_failed"
    fi
  done
else
  echo "uv not found - install_failed for both servers"
fi

python3 - "$DIR" <<'PYEOF'
import json, os, subprocess, sys, time

d = sys.argv[1]


def probe(cmd):
    try:
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, text=True, bufsize=1,
                             env={**os.environ, "PYTHONPATH": d})

        def send(o):
            p.stdin.write(json.dumps(o) + "\n")
            p.stdin.flush()

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


for name, rel in (("tradingview-mcp", "tradingview-mcp"), ("financekit-mcp", "financekit")):
    print("%s: tools=%s" % (name, probe([os.path.join(d, "bin", rel)])))
PYEOF
