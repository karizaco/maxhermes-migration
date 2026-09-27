"""
run_pattern_study.py — single-command wrapper for the Saturday pattern-study backlog cron.

Wraps the bash-side of the workflow:
  1. Print Finviz URLs (ipo_recent + high_short_float) for the agent to web_fetch
  2. Append audit log line via audit_append.py
  3. Self-check: verify both URLs were generated (Finviz subcommand exited 0)

The agent's job is reduced to: load skill, web_fetch the printed URLs, parse,
run shibui SQL, build markdown bodies, write the dated files. The bash parts
(file outputs + audit) all happen inside this one subprocess.

Args:
  --date YYYY-MM-DD                (required)
  --backlog-added N                (required)
  --backlog-total N                (required)
  --ipo-added N                    (required)
  --hsf-added N                    (required)

Exit 0 on success, non-zero on any failure (with a one-line stderr message).
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(r"C:\Users\admin\.minimax\projects\coding-shared")
SCREEN_PY = Path(r"C:\Users\admin\.minimax\agents\mavis\skills\stock-screener-suite\scripts\screen.py")
AUDIT_LOG = PROJECT_ROOT / "research" / "logs" / "audit.log"
AUDIT_APPEND = PROJECT_ROOT / "scripts" / "audit_append.py"


def die(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(5)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--backlog-added", type=int, required=True)
    p.add_argument("--backlog-total", type=int, required=True)
    p.add_argument("--ipo-added", type=int, required=True)
    p.add_argument("--hsf-added", type=int, required=True)
    args = p.parse_args()

    if not re.match(r"^\d{4}-\d{2}-\d{2}$", args.date):
        die(f"invalid --date format: {args.date} (expected YYYY-MM-DD)")

    # 1. Generate Finviz URLs (so the agent can web_fetch + parse)
    if not SCREEN_PY.exists():
        die(f"screen.py missing at {SCREEN_PY}")
    print("=== FINVIZ URLS ===")
    print("[ipo_recent]")
    ipo = subprocess.run(
        [sys.executable, str(SCREEN_PY), "finviz-url", "ipo_recent"],
        capture_output=True, text=True, check=False,
    )
    if ipo.returncode != 0:
        die(f"screen.py finviz-url ipo_recent failed (exit {ipo.returncode}): {ipo.stderr.strip()}")
    print(ipo.stdout.strip())

    print()
    print("[high_short_float]")
    hsf = subprocess.run(
        [sys.executable, str(SCREEN_PY), "finviz-url", "high_short_float"],
        capture_output=True, text=True, check=False,
    )
    if hsf.returncode != 0:
        die(f"screen.py finviz-url high_short_float failed (exit {hsf.returncode}): {hsf.stderr.strip()}")
    print(hsf.stdout.strip())

    # 2. Append audit log via audit_append.py
    if not AUDIT_APPEND.exists():
        die(f"audit_append.py missing at {AUDIT_APPEND}")
    audit_line = (
        f"stock-screener-pattern-study target=pattern-study "
        f"backlog_added={args.backlog_added} backlog_total={args.backlog_total} "
        f"ipo_added={args.ipo_added} hsf_added={args.hsf_added}"
    )
    audit_proc = subprocess.run(
        [sys.executable, str(AUDIT_APPEND), audit_line, str(AUDIT_LOG)],
        capture_output=True, text=True, check=False,
    )
    if audit_proc.returncode != 0:
        die(f"audit_append failed (exit {audit_proc.returncode}): {audit_proc.stderr.strip()}")
    print()
    print("=== AUDIT ===")
    print(audit_proc.stdout.strip())

    # 3. Self-check: verify both Finviz URLs printed (we already know via the
    #    subprocess return codes, but also check the audit log got the new line)
    audit_text = AUDIT_LOG.read_text(encoding="utf-8") if AUDIT_LOG.exists() else ""
    if audit_line not in audit_text:
        die(f"self-check FAILED: audit line missing ({audit_line[:60]}...)")

    print()
    print("=== SUMMARY ===")
    print(f"date:            {args.date}")
    print(f"backlog_added:   {args.backlog_added}")
    print(f"backlog_total:   {args.backlog_total}")
    print(f"ipo_added:       {args.ipo_added}")
    print(f"hsf_added:       {args.hsf_added}")
    print(f"audit_line:      {audit_line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
