#!/usr/bin/env python3
"""
verify_prompts.py — prove that the DEPLOYED prompt of every routine is byte-identical to the
repo's prompt file. The deploy harness (`tools/deploy_prompts.py`) points at this file, and it
was MISSING (2026-11-13): the harness could emit the exact bytes but nothing could prove what
actually landed.

WHY IT EXISTS
--------------
A prompt hash cannot see behaviour, and a LENGTH check is not a BYTE check: hand-pasted
prompts have landed byte-exact-in-length and wrong-in-content. The only proof is SHA-256 over
the raw bytes of what the scheduler holds, compared with the repo file.

WHERE THE DEPLOYED BYTES COME FROM
----------------------------------
`cron_read view=list` returns every task with its full prompt. The runtime writes a LARGE
response to disk as an artifact (`<session>/.mavis/tool-results/<call>/chunks/*.txt`), so the
deployed bytes can be hashed from a FILE - no transcription, no chance of a false MATCH.

USAGE
    python3 tools/verify_prompts.py --list <cron-list.json>
    python3 tools/verify_prompts.py --list <cron-list.json> --only 07

The input is either the raw `cron list` response, or the artifact chunk file that holds it.
Exit codes: 0 = every routine MATCHES; 1 = at least one DRIFT (each is printed).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from urllib.parse import unquote

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROMPTS = os.path.join(REPO, "cloud-prompts", "cron-prompts")


def load_tasks(path: str) -> dict:
    """The task map from a cron-list response (raw JSON or the artifact chunk holding it)."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        raw = fh.read()
    try:
        d = json.loads(raw)
    except json.JSONDecodeError:
        # the artifact chunk may carry the response wrapped in a tool-result envelope
        i = raw.find('{"ok"')
        if i < 0:
            raise
        d = json.loads(raw[i:])
    tasks = (d.get("response") or {}).get("tasks") or d.get("tasks") or []
    # The scheduler URL-encodes the routine name (`09%3A45.md` for `09:45.md`), so the name
    # has to be decoded before it can be matched against a repo FILE NAME.
    out = {}
    for t in tasks:
        n = t.get("cron_name")
        if not n:
            continue
        out[unquote(n)] = t
        out[n] = t
    return out


def repo_prompt(name: str) -> bytes | None:
    p = os.path.join(PROMPTS, name)
    if not os.path.exists(p):
        return None
    with open(p, "rb") as fh:
        return fh.read()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", required=True, help="the cron list response (or its artifact chunk)")
    ap.add_argument("--only", default="", help="restrict to one routine number, e.g. 07")
    a = ap.parse_args()

    tasks = load_tasks(a.list)
    drift, missing, checked = [], [], 0
    for name, t in sorted(tasks.items()):
        if name.startswith("@") or "/" in name:
            continue                       # self-reminders and ad-hoc tasks are not routines
        if a.only and not name.startswith(a.only + "-") and not name.startswith(a.only):
            continue
        rp = repo_prompt(name)
        if rp is None:
            missing.append(name)
            continue
        checked += 1
        dp = (t.get("prompt") or "").encode()
        if dp == rp:
            print(f"  MATCH  {name}")
            continue
        rs, ds = hashlib.sha256(rp).hexdigest()[:12], hashlib.sha256(dp).hexdigest()[:12]
        drift.append(f"{name}: deployed {len(dp)}B sha {ds} != repo {len(rp)}B sha {rs}")

    for m in missing:
        print(f"  NO REPO FILE  {m}")
    print()
    if drift:
        print(f"PROMPT DRIFT — {len(drift)} of {checked} routines differ from the repo:")
        for d in drift:
            print(f"  - {d}")
        return 1
    print(f"PROMPT BYTES OK — {checked} routines are byte-identical to the repo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
