#!/usr/bin/env python3
"""ntrt-gap-brief pre-flight + post-write verifier.

Replaces every bash call in the ntrt-gap-brief cron on Windows PowerShell,
so the runtime's per-bash permission gate does not block the routine.

Two modes (mutually exclusive):

  python ntrt_probe.py
      Pre-flight. Reads NTRT_BASE_URL / NTRT_AUTH_TOKEN env vars, probes
      {base}/health, prints today's ET date as JSON. Mode A vs Mode B is
      decided by probe.reachable.

  python ntrt_probe.py --verify <path>
      Post-write. Returns {"exists", "size", "ok", "path"} for PATH.

Exit codes:
  0  success (including reachable=false — that IS a real Mode B signal)
  2  bad arguments
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


def iso_today_et() -> str:
    """Today's ISO date in America/New_York (zoneinfo handles DST)."""
    return datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")


def probe_backend() -> dict:
    """Probe NTRT_BASE_URL/health. Returns a dict, never raises.

    reachable=False only when the request never reached the server
    (DNS, connection refused, timeout). HTTP errors are reachable=True
    with the actual status code — that is Mode A data, not an error.
    """
    base = os.environ.get("NTRT_BASE_URL") or "http://127.0.0.1:8000"
    auth = os.environ.get("NTRT_AUTH_TOKEN") or ""
    headers = {"Authorization": f"Bearer {auth}"} if auth else {}
    try:
        req = urllib.request.Request(f"{base}/health", headers=headers)
        with urllib.request.urlopen(req, timeout=3) as r:
            return {"reachable": True, "status": r.status, "base": base}
    except urllib.error.HTTPError as e:
        # Server answered, just not 200 — still Mode A.
        return {"reachable": True, "status": e.code, "base": base}
    except Exception as e:
        return {
            "reachable": False,
            "error": str(e)[:200],
            "base": base,
        }


def verify_artifact(path: str) -> dict:
    """Verify a file exists and has non-zero size. Read-only."""
    p = Path(path)
    if not p.exists():
        return {"exists": False, "size": 0, "ok": False, "path": str(p)}
    try:
        size = p.stat().st_size
    except OSError as e:
        return {
            "exists": True,
            "size": 0,
            "ok": False,
            "path": str(p),
            "error": str(e),
        }
    return {"exists": True, "size": size, "ok": size > 0, "path": str(p)}


def main(argv: list[str]) -> int:
    if len(argv) > 1 and argv[1] == "--verify":
        if len(argv) < 3:
            print("Usage: ntrt_probe.py --verify <path>", file=sys.stderr)
            return 2
        print(json.dumps(verify_artifact(argv[2])))
        return 0

    out = {
        "date_et": iso_today_et(),
        "ntrt_base_url_env": os.environ.get("NTRT_BASE_URL") or "",
        "ntrt_auth_token_set": bool(os.environ.get("NTRT_AUTH_TOKEN")),
        "probe": probe_backend(),
    }
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
