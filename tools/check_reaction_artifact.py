#!/usr/bin/env python3
"""
check_reaction_artifact.py — independent verifier for cron #15's artifact.

The pipeline renders the artifact; this checks that the artifact on disk obeys
the ARTIFACT FORMAT CONTRACT v2 (REACTION_ARTIFACT_V2) in
`cloud-prompts/skills/earnings-reaction-scanner/SKILL.md`. It is deliberately
a SEPARATE implementation: the pipeline is the producer, this is the verifier,
and neither imports the other.

Checks (each one exits 1 with a named failure):

  SECTIONS   the section skeleton, in order, with no `## Catalysts` section
  COLUMNS    every published row carries ref_close_source, ref_close_asof and
             us_tradeable, and a move_vs_avg_daily cell
  REFCLOSE   no published row's reference close is older than the previous
             session of that venue
  UNIQUENAME each name appears exactly once in the markdown
  DEGRADED   the reply's `errors:` count equals the number of degraded sources
             listed in the artifact's source health
  COUNTS     rows_dropped_stale_ref is present and non-negative

Usage:
    python3 tools/check_reaction_artifact.py earnings/2026-11-05-reactions.md
    python3 tools/check_reaction_artifact.py --artifact <path> [--reply <path>]
    python3 tools/check_reaction_artifact.py --artifact <path> --reply -   (stdin)

Exit codes: 0 = conforms, 1 = a check failed, 2 = the artifact could not be read.
"""
import argparse
import datetime
import os
import re
import sys

CONTRACT = "REACTION_ARTIFACT_V2"

# The section skeleton, in order. `## Catalysts` is deliberately absent: the
# catalyst rides in the row's last column, so a name can never appear twice.
REQUIRED_SECTIONS = [
    "TL;DR",
    "Actionable read",
    "US — Headline table",
    "US — QUIET one-liners",
    "EU/UK — Headline table",
    "AU (ASX) — Headline table",
    "Source health",
    "Audit line",
]
FORBIDDEN_SECTIONS = ["Catalysts"]

REQUIRED_COLUMNS = ["ref_close_source", "ref_close_asof", "us_tradeable",
                    "move_vs_avg_daily"]

# Column headers as they appear in the artifact. The header cell is matched
# loosely so a renderer may pad it ("Ref asof", "ref_close_asof", ...).
COLUMN_PATTERNS = {
    "ref_close_source": r"^ref source$|^ref_close_source$|^ref source \(.*\)$",
    "ref_close_asof": r"^ref asof$|^ref_close_asof$|^ref asof \(.*\)$",
    "us_tradeable": r"^us tradeable$|^us_tradeable$|^us tradeable \(.*\)$",
    "move_vs_avg_daily": r"^move vs avg daily$|^move_vs_avg_daily$",
}

# The NYSE holidays, the only exchange calendar carried here: the US
# reference close is the one that must never be older than the previous
# session. EU/UK/AU use the weekday rule.
NYSE_HOLIDAYS_2026 = {
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25",
    "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25",
}

# Which venue a table belongs to, for the prior-session test.
TABLE_VENUE = {
    "US — Headline table": "US",
    "US — QUIET one-liners": "US",
    "EU/UK — Headline table": "EU",
    "AU (ASX) — Headline table": "AU",
}


def split_row(line):
    """Split a markdown table row on UNESCAPED pipes only."""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in re.split(r"(?<!\\)\|", s)]


def is_table_row(line):
    s = line.strip()
    return s.startswith("|") and s.count("|") >= 2


def prior_session_date(date_str, venue="US"):
    """The session immediately before date_str for the venue, or None."""
    try:
        d = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
    except Exception:
        return None
    cur = d - datetime.timedelta(days=1)
    for _ in range(12):
        if cur.weekday() < 5:
            if venue != "US" or cur.isoformat() not in NYSE_HOLIDAYS_2026:
                return cur.isoformat()
        cur -= datetime.timedelta(days=1)
    return None


def min_ref_date(scan_date, venue):
    """The oldest reference-close date a published row may carry.

    The reference close must be the IMMEDIATELY prior session, so it can never
    be older than the session before the one the row reports.

      US  the reported session is the last completed US session before the
          scan date, so the base is the session before THAT one
      EU  the EU session is live at the 08:00 ET fire, so the base is the
          session before the scan date
      AU  an ASX bar is dated by its session OPEN (19:00 ET the previous
          day), so the session that closed at 02:00 ET on the scan date is
          dated D-1 and its base is the session before D-1
    """
    if not scan_date:
        return None
    if venue == "US":
        s1 = prior_session_date(scan_date, "US")
        return prior_session_date(s1, "US") if s1 else None
    if venue == "AU":
        try:
            d = (datetime.datetime.strptime(scan_date, "%Y-%m-%d").date()
                 - datetime.timedelta(days=1)).isoformat()
        except Exception:
            return None
        return prior_session_date(d, "AU")
    return prior_session_date(scan_date, venue)


def scan_date_of(text):
    """The artifact's own date, from the H1."""
    m = re.search(r"^#\s+Earnings reaction scanner\s*[—-]\s*(\d{4}-\d{2}-\d{2})",
                  text, re.M)
    return m.group(1) if m else None


def parse_sections(text):
    """{section title: [lines]} for every '## ' heading."""
    sections, cur = {}, None
    for line in text.split("\n"):
        m = re.match(r"^##\s+(.*?)\s*$", line)
        if m:
            cur = m.group(1)
            sections.setdefault(cur, [])
        elif cur is not None:
            sections[cur].append(line)
    return sections


def parse_tables(lines):
    """[(header_cells, [row_cells...])] for each markdown table in a block."""
    tables, header, rows = [], None, []
    for line in lines:
        if is_table_row(line):
            cells = split_row(line)
            if all(set(c) <= set("-: ") for c in cells if c):
                continue                      # the |---| separator
            if header is None:
                header = cells
            else:
                rows.append(cells)
        else:
            if header is not None:
                tables.append((header, rows))
            header, rows = None, []
    if header is not None:
        tables.append((header, rows))
    return tables


def column_index(header, key):
    """Index of the column matching `key`, or None."""
    pat = re.compile(COLUMN_PATTERNS[key], re.I)
    for i, cell in enumerate(header):
        if pat.match(cell.strip()):
            return i
    return None


def check(path, reply_text=None):
    failures = []
    if not os.path.exists(path):
        return [f"ARTIFACT: {path} does not exist"]
    with open(path, encoding="utf-8") as fh:
        text = fh.read()

    # ---- SECTIONS ------------------------------------------------------
    sections = parse_sections(text)
    order = [s for s in sections if s not in FORBIDDEN_SECTIONS]
    missing = [s for s in REQUIRED_SECTIONS if s not in sections]
    if missing:
        failures.append(f"SECTIONS: missing {missing}")
    present = [s for s in REQUIRED_SECTIONS if s in sections]
    if present != sorted(present, key=lambda s: order.index(s) if s in order else 0):
        failures.append(f"SECTIONS: out of order (found {present})")
    for bad in FORBIDDEN_SECTIONS:
        if bad in sections:
            failures.append(
                f"SECTIONS: a separate `## {bad}` section exists - the catalyst belongs "
                f"in the row's last column (one-table rule)")
    if CONTRACT not in text:
        failures.append(f"SECTIONS: the artifact does not carry the capability marker "
                        f"`{CONTRACT}`")

    # ---- every published row ------------------------------------------
    published = []          # (section, table_index, header, row_cells)
    for title in REQUIRED_SECTIONS:
        if title not in sections or title not in TABLE_VENUE:
            continue
        for ti, (header, rows) in enumerate(parse_tables(sections[title])):
            for ri, cells in enumerate(rows):
                published.append((title, ti, header, cells, ri))

    if not published:
        failures.append("COLUMNS: no published table rows were found at all")

    for title, ti, header, cells, ri in published:
        tag = f"{title} row {ri}"
        for key in REQUIRED_COLUMNS:
            idx = column_index(header, key)
            if idx is None:
                failures.append(f"COLUMNS: {tag} — the table has no `{key}` column")
                continue
            val = cells[idx].strip() if idx < len(cells) else ""
            if not val:
                failures.append(f"COLUMNS: {tag} — `{key}` is empty")
        # the ticker cell must not be empty
        if not cells or not cells[0].strip():
            failures.append(f"COLUMNS: {tag} — the ticker cell is empty")

    # ---- REFCLOSE ------------------------------------------------------
    scan_d = scan_date_of(text)
    if not scan_d:
        failures.append("REFCLOSE: the artifact's H1 does not carry its scan date "
                        "(`# Earnings reaction scanner — YYYY-MM-DD`)")
    for title, ti, header, cells, ri in published:
        idx = column_index(header, "ref_close_asof")
        if idx is None:
            continue
        asof = (cells[idx].strip() if idx < len(cells) else "")
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", asof):
            failures.append(f"REFCLOSE: {title} row {ri} — ref_close_asof is not a date "
                            f"({asof!r})")
            continue
        venue = TABLE_VENUE.get(title, "US")
        floor = min_ref_date(scan_d, venue)
        if floor and asof < floor:
            failures.append(f"REFCLOSE: {title} row {ri} — the reference close {asof} is "
                            f"older than the previous session {floor}")

    # ---- UNIQUENAME ----------------------------------------------------
    names = []
    for title, ti, header, cells, ri in published:
        if not cells:
            continue
        n = cells[0].strip()
        if n and n != "—":
            names.append((n, title))
    seen = {}
    for n, title in names:
        seen.setdefault(n, []).append(title)
    dups = {n: t for n, t in seen.items() if len(t) > 1}
    if dups:
        failures.append(f"UNIQUENAME: {len(dups)} name(s) appear more than once: "
                        f"{ {k: v for k, v in list(dups.items())[:10]} }")

    # ---- DEGRADED ------------------------------------------------------
    sh = "\n".join(sections.get("Source health", []))
    m = re.search(r"^-?\s*degraded_sources:\s*(\d+)\s*$", sh, re.M)
    if not m:
        failures.append("DEGRADED: the source health section has no "
                        "`degraded_sources: <n>` line")
    else:
        declared = int(m.group(1))
        listed = re.findall(r"^\s{2,}\d+\.\s+(\S+)", sh, re.M)
        if len(listed) != declared:
            failures.append(f"DEGRADED: degraded_sources says {declared} but "
                            f"{len(listed)} degraded source(s) are listed")
        if reply_text is not None:
            rm = re.search(r"^\s*[-*]?\s*errors:\s*(\d+)\s*$", reply_text, re.M)
            if not rm:
                failures.append("DEGRADED: the reply has no `errors: <n>` line")
            elif int(rm.group(1)) != declared:
                failures.append(f"DEGRADED: the reply's errors: {rm.group(1)} does not "
                                f"equal the artifact's degraded_sources: {declared}")

    # ---- COUNTS --------------------------------------------------------
    if "rows_dropped_stale_ref" not in sh:
        failures.append("COUNTS: the source health section does not publish "
                        "`rows_dropped_stale_ref`")
    else:
        cm = re.search(r"rows_dropped_stale_ref:\s*(\d+)", sh)
        if not cm:
            failures.append("COUNTS: `rows_dropped_stale_ref` is not a number")

    # ---- the audit line must name the drops ---------------------------
    if "rows_dropped_stale_ref" not in "\n".join(sections.get("Audit line", [])):
        failures.append("COUNTS: the audit line does not carry rows_dropped_stale_ref")

    return failures


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("artifact", nargs="?", help="path to the artifact markdown")
    ap.add_argument("--artifact", dest="artifact_opt", help="path to the artifact markdown")
    ap.add_argument("--reply", help="path to the chat reply (or - for stdin); when given, "
                                     "its `errors:` count is checked against "
                                     "`degraded_sources`")
    args = ap.parse_args()
    path = args.artifact_opt or args.artifact
    if not path:
        ap.error("an artifact path is required")
    reply_text = None
    if args.reply:
        if args.reply == "-":
            reply_text = sys.stdin.read()
        elif os.path.exists(args.reply):
            with open(args.reply, encoding="utf-8") as fh:
                reply_text = fh.read()
        else:
            print(f"CHECK: reply file {args.reply} not found", file=sys.stderr)
            return 2
    failures = check(path, reply_text)
    if failures:
        print(f"FAIL: {len(failures)} contract violation(s) in {path}")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"OK: {path} conforms to {CONTRACT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
