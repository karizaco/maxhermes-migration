"""
Dump the mavis cron list to a JSON cache file.

Tries three strategies in order:
  1. `MAVIS_CRON_LIST` env var (set by the cron agent right before invoking this).
     Useful for large lists — env vars avoid 32KB command-line limits on Windows.
  2. `--cron-list <json_string>` argument (small payloads only).
  3. `mavis cron list` subprocess (when the mavis CLI is on PATH; the cron agent
     already populates the cache, so this is mostly for manual testing).

Writes the inner `response` object (tasks/count/hasMore) — the same shape
export_mavis_runtime.py's --cron-json expects.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--out", required=True, help="Path to write the cron-list JSON.")
    p.add_argument("--cron-list", default=None,
                   help="Raw JSON string (small payloads). Prefer the env var for large lists.")
    args = p.parse_args()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    payload: dict | None = None

    # 1. env var
    env_json = os.environ.get("MAVIS_CRON_LIST")
    if env_json:
        try:
            payload = json.loads(env_json)
        except json.JSONDecodeError as e:
            print(f"ERROR: MAVIS_CRON_LIST is not valid JSON: {e}", file=sys.stderr)
            return 2

    # 2. CLI arg
    if payload is None and args.cron_list:
        try:
            payload = json.loads(args.cron_list)
        except json.JSONDecodeError as e:
            print(f"ERROR: --cron-list is not valid JSON: {e}", file=sys.stderr)
            return 2

    # 3. mavis CLI fallback (manual testing)
    if payload is None:
        if shutil.which("mavis") is None:
            print("ERROR: no payload source available (no env var, no --cron-list, mavis CLI not on PATH).",
                  file=sys.stderr)
            return 2
        result = subprocess.run(["mavis", "cron", "list"], capture_output=True, text=True, check=False)
        if result.returncode != 0:
            print(f"ERROR: mavis cron list failed: {result.stderr}", file=sys.stderr)
            return 1
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            print(f"ERROR: mavis cron list output not JSON: {e}", file=sys.stderr)
            return 1

    # Normalize: extract `response` if wrapper is present (native mavis tool shape).
    inner = payload.get("response", payload) if isinstance(payload, dict) else payload
    tasks = inner.get("tasks", []) if isinstance(inner, dict) else []

    with open(out, "w", encoding="utf-8") as f:
        json.dump(inner, f, indent=2, ensure_ascii=False)

    print(f"saved {len(tasks)} tasks, {(out.stat().st_size)} bytes -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
