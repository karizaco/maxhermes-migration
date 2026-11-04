#!/usr/bin/env python3
"""
gen_docs_index.py — regenerate docs/README.md, the index of the improvement docs.

Why
---
docs/ holds the fleet's improvement write-ups (one per routine, plus cross-checks and bug
reports). They are the record of WHY the prompts look the way they do, and nothing pointed at
them. A hand-kept index goes stale the same way a hand-kept roster does — see the comment in
tools/gen_index.py — so this generates it from the files on disk.

USAGE
  python3 tools/gen_docs_index.py [--check]
"""
from __future__ import annotations

import argparse
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(REPO, "docs")


def title_of(path: str) -> str:
    head = open(path, encoding="utf-8", errors="replace").read(4096)
    m = re.search(r"^#\s+(.+)$", head, re.M)
    return m.group(1).strip() if m else os.path.basename(path)


def summary_of(path: str) -> str:
    """First non-empty, non-heading line after the title — the doc's one-line lede."""
    lines = open(path, encoding="utf-8", errors="replace").read().split("\n")
    started = False
    for l in lines:
        s = l.strip()
        if not started:
            if s.startswith("# "):
                started = True
            continue
        if not s or s.startswith("#") or s.startswith("---"):
            continue
        return s[:160]
    return ""


def build() -> str:
    files = sorted(f for f in os.listdir(DOCS)
                   if f.endswith(".md") and f.lower() != "readme.md"
                   and os.path.isdir(os.path.join(DOCS, f)) is False)
    out = ["# docs/ — the fleet's improvement record", "",
           "One file per routine (or per cross-check), written when a routine is reviewed and",
           "changed. They record the EVIDENCE for each change, not just what the change was —",
           "so the next person can check the finding rather than take it on trust.", "",
           "Regenerate this index with `python3 tools/gen_docs_index.py` after adding a file.",
           "",
           "| Document | What it is |", "|---|---|"]
    for f in files:
        t = title_of(os.path.join(DOCS, f))
        s = summary_of(os.path.join(DOCS, f)).replace("|", "/")
        out.append(f"| [`{f}`]({f}) | {t} — {s} |" if s else f"| [`{f}`]({f}) | {t} |")
    out += ["", "## Convention", "",
            "`IMPROVEMENTS-cronNN-<routine>.md` — a review of one routine and what changed.",
            "`CROSSCHECK-<topic>.md` — two routines checked against each other.",
            "`BUGREPORT-<topic>.md` — a defect found outside the routine-review flow.",
            "`remediation/` — the larger fleet-wide remediation records.", ""]
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="exit 1 if the index is stale")
    args = ap.parse_args()
    body = build()
    target = os.path.join(DOCS, "README.md")
    if args.check:
        cur = open(target, encoding="utf-8").read() if os.path.exists(target) else ""
        if cur != body:
            print("docs/README.md is STALE — run python3 tools/gen_docs_index.py")
            return 1
        print("docs/README.md is up to date")
        return 0
    open(target, "w", encoding="utf-8").write(body)
    print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
