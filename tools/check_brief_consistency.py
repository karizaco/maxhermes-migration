#!/usr/bin/env python3
"""
check_brief_consistency.py — enforce the pre-market brief's own consistency rules.

WHY
---
The brief's spec (cloud-prompts/skills/agentic-pre-market-brief/SKILL.md) promises three things
that nothing was checking:

  1. "the prose must equal the table it came from"
  2. "the CSV must never contradict the markdown"
  3. one pull of the tape feeds the whole brief, so the same ticker cannot carry two
     different pre-market percentages in two sections

On 2026-11-03 the artifact broke all three: the CSV took a later per-ticker fetch for some
names while the markdown took the earlier bulk screen, so AEHR read +18.5% in one table and
+18.8% in the CSV, and RDAC read +119.6% in a note and +118.0% in the table above it. Nothing
in the pipeline noticed — the file looked fine. This script is the check.

USAGE
  python3 tools/check_brief_consistency.py --md daily-briefs/2026-11-04-pre-market.md \
                                              --csv daily-briefs/2026-11-04-pre-market.csv

EXIT CODES
  0 = consistent
  1 = INCONSISTENT — read the report; do not publish the artifact
  2 = bad arguments / missing files
"""
from __future__ import annotations

import argparse
import csv
import re
import sys

# The sections the brief must contain, in order. Section 6 (the watchlist) is conditional —
# it is omitted when no watchlist is published — so it is not required here.
SECTIONS = [
    "## 1. TL;DR",
    "## 2. Theme clusters",
    "## 3. Pre-market gaps",
    "## 4. Top losers",
    "## 5. StockTwits lead read",
    "## 7. Overnight",
    "## 8. Macro calendar",
    "## 9. Earnings today",
    "## 10. Source health",
    "## 11. Open research queue",
]
PLACEHOLDERS = ("{date}", "@@", "TODO", "FIXME", "None%", "nan%", "None |")
TICKER_RE = re.compile(r"[A-Z][A-Z0-9.\-]{0,6}")
SEPARATOR_RE = re.compile(r"^\|[\s:|-]+\|$")


def cells(line: str) -> list:
    line = line.strip()
    if not line.startswith("|"):
        return []
    return [c.strip() for c in line.strip("|").split("|")]


def tables(md: str):
    """Yield (header_cells, [row_cells, ...]) for every markdown table."""
    lines = md.split("\n")
    i = 0
    while i < len(lines):
        if (lines[i].strip().startswith("|") and i + 1 < len(lines)
                and SEPARATOR_RE.match(lines[i + 1].strip())):
            header = cells(lines[i])
            rows = []
            j = i + 2
            while j < len(lines) and lines[j].strip().startswith("|"):
                rows.append(cells(lines[j]))
                j += 1
            yield header, rows
            i = j
        else:
            i += 1


def pre_market_cols(header: list):
    """(price_col, pct_col) for a table whose header names a pre-market column.

    Located BY HEADER, never by position: the brief has three table shapes and the columns move.
    A positional match silently read the prior-session columns of the cluster tables.
    """
    px = None
    for i, h in enumerate(header):
        hl = h.lower()
        if hl.startswith("pre-market") or hl == "pre %" or hl.startswith("pre-market)"):
            px = i
            break
    if px is None:
        return None
    pct = None
    for i in range(px + 1, len(header)):
        if header[i].endswith("%"):
            pct = i
            break
    return None if pct is None else (px, pct)


def load_csv(path: str) -> dict:
    """ticker -> {pct: today's pre-market %, session_pct: the prior session's %, px: price}.

    A bold "TICKER -12.3%" in the prose is EITHER a pre-market gap or a prior-session move (the
    brief deliberately reports both sessions), so the prose check accepts either column. The
    TABLE check is strict: a table row's price and gap must be the pre-market ones.
    """
    out = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            t = (row.get("ticker") or "").strip()
            if not t:
                continue

            def _f(k):
                try:
                    return float(row.get(k) or "")
                except ValueError:
                    return None

            out[t] = {"pct": _f("premarket_change_pct"),
                      "session_pct": _f("nov_2_change_pct"),
                      "px": _f("premarket_close")}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", required=True)
    ap.add_argument("--csv", required=True)
    ap.add_argument("--tolerance", type=float, default=0.15,
                    help="percentage points of slack (default 0.15)")
    args = ap.parse_args()

    try:
        md = open(args.md, encoding="utf-8").read()
        rows = load_csv(args.csv)
    except OSError as exc:
        print(f"check-brief-consistency: FAILED to read: {exc}", file=sys.stderr)
        return 2

    problems = []

    # --- 1. sections present and in order ---
    pos = -1
    for sec in SECTIONS:
        i = md.find(sec)
        if i < 0:
            problems.append(f"missing section: {sec}")
        elif i < pos:
            problems.append(f"section out of order: {sec}")
        else:
            pos = i

    # --- 2. unfinished-render tokens ---
    for ph in PLACEHOLDERS:
        if ph in md:
            problems.append(f"unfinished placeholder in the markdown: {ph!r}")

    # --- 3. every table row must agree with the CSV ---
    table_checked = 0
    for header, trows in tables(md):
        cols = pre_market_cols(header)
        if not cols:
            continue  # a context table (e.g. "yesterday's tape") — its columns are the prior session
        px_i, pct_i = cols
        for c in trows:
            if len(c) <= max(px_i, pct_i):
                continue
            t = c[0].strip().strip("*").strip()
            if not TICKER_RE.fullmatch(t):
                continue
            try:
                px = float(c[px_i].strip().strip("*"))
                pct = round(float(c[pct_i].strip().strip("*").rstrip("%")), 1)
            except ValueError:
                continue
            table_checked += 1
            ref = rows.get(t)
            if not ref:
                problems.append(f"table row {t}: not present in the CSV")
                continue
            if ref["pct"] is None or abs(ref["pct"] - pct) > args.tolerance:
                problems.append(f"table row {t}: markdown says {pct:+.1f}%, CSV says {ref['pct']}")
            if ref["px"] is not None and abs(ref["px"] - px) > max(0.011, abs(ref["px"]) * 0.001):
                problems.append(f"table row {t}: markdown price {px} != CSV price {ref['px']}")

    # --- 4. every bold ticker-% in the prose must agree with the CSV ---
    prose_checked = 0
    for m in re.finditer(r"\*\*([A-Z][A-Z0-9.\-]{0,6})\s+([+-][0-9.]+)%\*\*", md):
        t, pct = m.group(1), round(float(m.group(2)), 1)
        ref = rows.get(t)
        if not ref:
            continue  # a name that is not in the screen at all — not the linter's business
        prose_checked += 1
        cands = [v for v in (ref["pct"], ref["session_pct"]) if v is not None]
        if not cands or min(abs(v - pct) for v in cands) > args.tolerance:
            problems.append(f"prose {t}: says {pct:+.1f}%, the screen says "
                            f"pre-market {ref['pct']} / session {ref['session_pct']}")

    # --- 5. the markdown must name the CSV (they ship as a pair) ---
    if "pre-market.csv" not in md:
        problems.append("the markdown does not reference its CSV companion")

    print(f"check-brief-consistency: {args.md}")
    print(f"  table rows checked : {table_checked}")
    print(f"  prose ticks checked: {prose_checked}")
    print(f"  CSV names          : {len(rows)}")
    if problems:
        print(f"  RESULT: INCONSISTENT ({len(problems)} problem(s))")
        for p in problems:
            print(f"    - {p}")
        return 1
    print("  RESULT: consistent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
