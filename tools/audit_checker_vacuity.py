#!/usr/bin/env python3
"""
audit_checker_vacuity.py — find the CONTRACT GATES that cannot fail.

WHY
---
On 2026-11-19 cron #06's own truncation guard was found to be VACUOUS: the contract
asserted `rows_passing == rows_kept`, but the PRODUCER wrote `rows_passing = len(rows)`,
so the comparison was a number against itself and a truncated branch would have shipped
claiming completeness. Two days later the same routine's cross-check was found to have no
coverage floor — a cross-check of 10 of 138 names passed every clause.

A gate that cannot fail is not a gate, and it is invisible in review: the clause LOOKS
like a measurement. Three of the defects found in #06 were of this kind, so the class is
worth looking for fleet-wide rather than routine by routine.

WHAT IT FINDS (mechanically, offline, no network)
-------------------------------------------------
A. FIXED COLUMN INDEX — a parsed table row read at a literal index (`cells[5]`,
   `r[6]`). Indexes 0 and 1 are excluded: they are the row-number and ticker convention
   that every table in the fleet uses. Index 2 and beyond is a CONTENT column, and a
   content column moves when a column is added — the check then silently reads the WRONG
   CELLS. The fix is to look the column up by header name.
B. SELF-COMPARISON — a clause comparing two fields that the same producer fills from the
   same place (`rows_passing` vs `rows_kept`, `coverage` vs `total`). It can only fail if
   the producer deliberately lies; it cannot catch a truncated pull.
C. NO TEST — a checker with no fault-injection test beside it. A checker nobody observes
   failing is a claim, not a guard.

WHAT IT CANNOT FIND
-------------------
A clause that compares two genuinely independent measurements is indistinguishable from a
self-comparison by reading alone. This tool narrows the list; a human still decides. It
reports CANDIDATES, never verdicts.

USAGE
    python3 tools/audit_checker_vacuity.py [--repo .] [--json out.json] [--strict]

EXIT CODES
    0 = the audit ran (findings are printed; with --strict, 1 when anything was found)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

# A parsed markdown table row is a LIST; reading it at a literal index is the pattern.
FIXED_INDEX = re.compile(
    r"\b(?:cells|row|rows|r|x|_row|_cells)\s*\[\s*(\d+)\s*\]"
)
# two field names that a producer fills from the same source
SELF_COMPARE_FIELDS = [
    ("rows_passing", "rows_kept"),
    ("rows_passing", "rows_kept_total"),
    ("coverage_pct", "coverage_total"),
    ("short_float_delta_pp", "short_float_delta_pp"),
]
# a clause that compares the two fields above
COMPARE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*!=\s*([A-Za-z_][A-Za-z0-9_]*)")
EQ = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*==\s*([A-Za-z_][A-Za-z0-9_]*)")

SKIP_DIRS = {".git", "__pycache__", ".venv", "node_modules", ".mavis"}


def checkers(repo: str):
    tools = os.path.join(repo, "tools")
    if not os.path.isdir(tools):
        return []
    return sorted(f for f in os.listdir(tools) if f.startswith("check_") and f.endswith(".py"))


def tests_for(repo: str, checker: str):
    """A fault-injection test for `checker`: a test file that names it, or a sibling
    with the same stem."""
    tools = os.path.join(repo, "tools")
    stem = checker[len("check_"):-len(".py")]
    out = []
    for f in os.listdir(tools):
        if not (f.startswith("test_") and f.endswith(".py")):
            continue
        path = os.path.join(tools, f)
        try:
            txt = open(path, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        if checker in txt or stem in f:
            out.append(f)
    return out


def audit_file(path: str):
    try:
        txt = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return []
    lines = txt.splitlines()
    findings = []
    for i, line in enumerate(lines, 1):
        if line.lstrip().startswith("#"):
            continue
        for m in FIXED_INDEX.finditer(line):
            # Indexes 0 and 1 are the table's convention (the row number and the
            # ticker) and every table in the fleet uses them that way. Index 2 and
            # beyond is a CONTENT column, and a content column moves when a column
            # is added — that is the defect.
            if int(m.group(1)) < 2:
                continue
            findings.append({
                "kind": "FIXED_INDEX",
                "file": path, "line": i,
                "detail": f"{m.group(0)} — a table row read at a literal index; adding a "
                          f"column moves every cell to its right",
                "snippet": line.strip()[:160],
            })
        # a self-comparison shows up as the two FIELD NAMES being fetched close
        # together and then compared (the #06 case: `rp = c.get("rows_passing")`,
        # `rk = c.get("rows_kept")`, then `rp != rk`).
        for a, b in SELF_COMPARE_FIELDS:
            if a == b:
                continue
            for other in (a, b):
                if other in line:
                    near = [j for j in range(max(0, i - 6), min(len(lines), i + 6))
                            if (a in lines[j]) and (b in lines[j])]
                    if near:
                        findings.append({
                            "kind": "SELF_COMPARISON",
                            "file": path, "line": i,
                            "detail": f"{a} vs {b} — if the producer fills both from the same "
                                      f"place, this clause cannot fail",
                            "snippet": line.strip()[:160],
                        })
                    break
    return findings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--json", default=None, help="write the findings as JSON")
    ap.add_argument("--strict", action="store_true", help="exit 1 when anything was found")
    args = ap.parse_args()

    repo = os.path.abspath(args.repo)
    cks = checkers(repo)
    report = {"repo": repo, "checkers": len(cks), "findings": [], "no_test": []}

    for c in cks:
        path = os.path.join(repo, "tools", c)
        report["findings"].extend(audit_file(path))
        if not tests_for(repo, c):
            report["no_test"].append(c)

    by_kind = {}
    for f in report["findings"]:
        by_kind.setdefault(f["kind"], []).append(f)

    print(f"audit_checker_vacuity: {len(cks)} checkers in {repo}")
    for kind in sorted(by_kind):
        print(f"  {kind}: {len(by_kind[kind])}")
    print(f"  NO_TEST: {len(report['no_test'])}")
    for c in report["no_test"]:
        print(f"    - {c} has no fault-injection test beside it")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=1)
        print(f"  findings JSON: {args.json}")

    total = len(report["findings"]) + len(report["no_test"])
    if args.strict and total:
        print(f"audit_checker_vacuity: {total} finding(s) — FAIL")
        sys.exit(1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
