#!/usr/bin/env python3
"""Standalone helper for the cron-watchdog Agent.

Reads the Mavis cron sessions via direct MCP (or via the
`mavis cron sessions --cron_id <id> --limit 3` shell, when the CLI is on
PATH), prints a per-task summary of suspect runs, and (optionally) emits
a JSON action plan the Agent can act on.

This script is read-only by design — it does NOT archive or re-trigger
anything. The Agent makes the actual mavis session update / cron trigger
calls based on the plan this script emits.

Usage:
    python check_stuck.py --now-ms 1790030000000
    python check_stuck.py --warn-min 30 --archive-min 120
    python check_stuck.py --empty                     # clean-tick short-circuit
    python check_stuck.py --from-env --now-ms 1790... # read inventory from $MAVIS_WATCHDOG_INVENTORY
    python check_stuck.py --input inventory.json      # read inventory from a file
    cat inventory.json | python check_stuck.py        # read inventory from stdin (bash only)

Output (JSON to stdout):
    {
      "now_ms": 1790030000000,
      "warn_min": 30,
      "archive_min": 120,
      "tasks": [
        {
          "cron_id": "b5187e5c-...",
          "name": "Stock-screener reversal bullish 15:55 entry alert",
          "candidates": [
            {
              "session_id": "mvs_8b04...",
              "age_min": 47.2,
              "createdAt": 1789990357332,
              "status_type": "started",
              "action": "warn"
            }
          ]
        }
      ]
    }

The cron-watchdog Agent reads this JSON and decides whether to call
`mavis session update --archived true` or `mavis cron trigger --cron_id ...`
for each entry.

Inventory delivery — three PowerShell-safe paths:
  1. `--empty` — no inventory needed (clean tick); emits `{"tasks": []}`.
  2. `--from-env` — reads JSON from the $MAVIS_WATCHDOG_INVENTORY env var.
     This is the recommended path on Windows PowerShell: it avoids both
     `%TEMP%` writes (which trigger a runtime permission prompt) AND the
     broken PowerShell stdin pipe.
  3. `--input FILE` — reads JSON from a path. (Legacy; prefer --from-env.)
  4. stdin — only works on bash; PowerShell 5.1 consumes the pipeline
     before python sees stdin and writes a BOM via Set-Content.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Compute watchdog action plan from cron sessions data")
    p.add_argument("--now-ms", type=int, default=None,
                   help="current time in epoch ms (default: time.time_ns()//1_000_000)")
    p.add_argument("--warn-min", type=int, default=30,
                   help="age threshold (minutes) for WARN (default 30)")
    p.add_argument("--archive-min", type=int, default=120,
                   help="age threshold (minutes) for AUTO-ARCHIVE plan entry (default 120)")
    p.add_argument("--input", default=None,
                   help="path to JSON file with cron sessions inventory (legacy)")
    p.add_argument("--from-env", action="store_true",
                   help="read inventory JSON from $MAVIS_WATCHDOG_INVENTORY env var "
                        "(PowerShell-safe; preferred over stdin on Windows)")
    p.add_argument("--empty", action="store_true",
                   help="short-circuit to empty inventory (clean tick); emits "
                        "{\"tasks\": []} and exits 0 without any JSON parsing")
    args = p.parse_args(argv)

    now_ms = args.now_ms or (time.time_ns() // 1_000_000)

    # Inventory delivery — order matters: --empty > --from-env > --input > stdin.
    if args.empty:
        plan: dict = {
            "now_ms": now_ms,
            "warn_min": args.warn_min,
            "archive_min": args.archive_min,
            "tasks": [],
        }
        json.dump(plan, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    if args.from_env:
        raw = os.environ.get("MAVIS_WATCHDOG_INVENTORY", "")
        if not raw:
            print("ERROR: --from-env set but $MAVIS_WATCHDOG_INVENTORY is empty.",
                  file=sys.stderr)
            return 2
        inventory = json.loads(raw)
    elif args.input:
        inventory = json.loads(Path(args.input).read_text(encoding="utf-8"))
    elif not sys.stdin.isatty():
        inventory = json.loads(sys.stdin.read())
    else:
        print("Pass inventory via --empty, --from-env, --input FILE, or stdin (JSON).",
              file=sys.stderr)
        print("  python check_stuck.py --empty",
              file=sys.stderr)
        print("  python check_stuck.py --from-env --now-ms <ms>",
              file=sys.stderr)
        return 2

    plan = {"now_ms": now_ms, "warn_min": args.warn_min, "archive_min": args.archive_min, "tasks": []}

    # Accept either {"tasks": [...]} (full cron list response) or a flat list
    tasks = inventory.get("tasks") if isinstance(inventory, dict) else inventory
    if not isinstance(tasks, list):
        print("Unrecognized inventory shape (expected list or dict with 'tasks' key)", file=sys.stderr)
        return 2

    for task in tasks:
        cron_id = task.get("cronId") or task.get("cron_id")
        name = task.get("cronName") or task.get("cron_name") or "<unnamed>"
        # The mavis cron sessions data lives behind `cron sessions --cron_id <id>`,
        # which the watchdog Agent calls. Here we accept an optional
        # `recent_sessions` list per task (already hydrated by the Agent).
        recent = task.get("recent_sessions") or []
        candidates = []
        for run in recent:
            age_min = (now_ms - run["createdAt"]) / 60_000
            if age_min < args.warn_min:
                continue
            if age_min >= args.archive_min:
                action = "archive"
            else:
                action = "warn"
            candidates.append({
                "session_id": run.get("sessionId") or run.get("session_id"),
                "run_id": run.get("runId") or run.get("run_id"),
                "age_min": round(age_min, 1),
                "createdAt": run["createdAt"],
                "status_type": (run.get("status") or "started"),
                "action": action,
            })
        if candidates:
            plan["tasks"].append({
                "cron_id": cron_id,
                "name": name,
                "candidates": candidates,
            })

    json.dump(plan, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
