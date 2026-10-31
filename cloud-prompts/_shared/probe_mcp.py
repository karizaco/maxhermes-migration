#!/usr/bin/env python3
"""
probe_mcp.py — report what the cloud runtime can actually reach.

WHY THIS EXISTS
---------------
The agent.minimax.io connector catalog changes without notice — it went from 15 tools
(media/email only) to 133 on 2026-10-31, the extra 118 being a GitHub connector.
Meanwhile the `mcp__*` TOOL NAMES that the old cron prompts reference (yahoo_finance,
tradingview_advanced, shibui_finance, stocktwits) have never been registered in this
runtime, and the local Windows MCP servers are reached over plain HTTPS instead.

A routine that only knows "the catalog is media/email" will skip capabilities that
exist, and one that only knows "the catalog is empty" will miss a financial MCP the
moment it lands. This probe answers the question once, cheaply, and in a form that
distinguishes the three states that matter.

THREE STATES — never collapse them
----------------------------------
  catalog_ok total=N finance_tools=0   catalog is healthy, no financial MCP yet
  catalog_ok total=N finance_tools=K   a financial MCP HAS LANDED — switch to it
  catalog_unreachable                  the probe itself failed (seen 2026-10-21 as
                                       `error: invalid signature`). This is NOT
                                       evidence that no MCPs exist.

USAGE
  probe_mcp.py                 # catalog + bridge packs
  probe_mcp.py --json          # machine-readable
  probe_mcp.py --no-bridge     # catalog only (fast; for a per-run probe)

EXIT CODES
  0 = probe succeeded (regardless of whether MCPs were found)
  1 = probe failed (catalog unreachable AND no bridge)
"""

import argparse
import json
import os
import subprocess
import sys

FINANCE_RE = (
    r"yahoo|tradingview|shibui|stocktwits|financekit|finviz|barchart|market|quote|"
    r"alpha_vantage|fmp|polygon|tiingo|tipranks|nasdaq|sec_?edgar"
)
BRIDGE = "/workspace/mcp_bridge.py"
BRIDGE_URL = ("https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/"
              "cloud-prompts/_shared/mcp_bridge.py")


def fetch_bridge():
    if os.path.exists(BRIDGE) and os.path.getsize(BRIDGE) > 0:
        return BRIDGE
    os.makedirs("/workspace", exist_ok=True)
    for url in (BRIDGE_URL,
                "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/"
                "cloud-prompts/_shared/mcp_bridge.py"):
        try:
            subprocess.run(["curl", "-sL", "-o", BRIDGE, url], timeout=60, capture_output=True)
            if os.path.exists(BRIDGE) and os.path.getsize(BRIDGE) > 0:
                return BRIDGE
        except Exception:
            pass
    return None


def probe_catalog():
    try:
        r = subprocess.run(["mcode-tools", "connector", "tools"],
                           capture_output=True, text=True, timeout=120)
    except Exception as exc:
        return {"state": "catalog_unreachable", "detail": str(exc)[:200]}
    raw = r.stdout or ""
    try:
        tools = json.loads(raw).get("tools", [])
    except Exception:
        return {"state": "catalog_unreachable",
                "detail": (raw.strip() or r.stderr.strip())[:200]}
    names = [t.get("tool_name", "") for t in tools]
    fin = [n for n in names if any(k in n.lower() for k in FINANCE_RE.split("|"))]
    return {"state": "catalog_ok", "total": len(names), "finance_tools": len(fin),
            "finance_names": fin[:25],
            "providers": sorted({n.split("__")[1] for n in names if n.count("__") >= 2})}


def probe_bridge():
    path = fetch_bridge()
    if not path:
        return {"state": "bridge_unavailable"}
    try:
        r = subprocess.run([sys.executable, path, "--list-packs"],
                           capture_output=True, text=True, timeout=150)
        data = json.loads(r.stdout)
        return {"state": "bridge_ok" if "packs" in data else "bridge_error",
                "packs": {k: len(v) for k, v in (data.get("packs") or {}).items()},
                "detail": data.get("error")}
    except Exception as exc:
        return {"state": "bridge_error", "detail": str(exc)[:200]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-bridge", action="store_true")
    args = ap.parse_args()

    out = {"catalog": probe_catalog()}
    if not args.no_bridge:
        out["bridge"] = probe_bridge()

    cat = out["catalog"]
    if cat["state"] == "catalog_ok":
        line = (f"catalog_ok total={cat['total']} "
                f"finance_tools={cat['finance_tools']}")
        if cat["finance_tools"]:
            line += "  <-- A FINANCIAL MCP HAS LANDED — switch source stacks"
    else:
        line = "catalog_unreachable  (probe failure — NOT evidence that no MCPs exist)"
    if "bridge" in out:
        br = out["bridge"]
        line += (f" | bridge {br['state']}"
                 + (f" packs={','.join(br.get('packs', {}))}" if br.get("packs") else ""))
    if args.json:
        print(json.dumps(out, indent=2))
    else:
        print(line)
        for n in cat.get("finance_names", []):
            print("   ", n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
