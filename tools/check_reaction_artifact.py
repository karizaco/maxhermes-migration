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
    "APAC/Gulf — Headline table",
    "Source health",
    "Audit line",
]
# The 12:15 ET settlement pass publishes a DIFFERENT artifact: the EU/UK
# session has closed, so the rows are republished with their settled close and
# move. It has no US section - at 12:15 ET the US session is OPEN, and
# publishing a live intraday price as a close would be a fabricated settle.
SETTLE_SECTIONS = [
    "TL;DR",
    "EU/UK — Settled table",
    "Source health",
    "Audit line",
]
FORBIDDEN_SECTIONS = ["Catalysts"]

REQUIRED_COLUMNS = ["ref_close_source", "ref_close_asof", "us_tradeable",
                    "move_vs_avg_daily"]

# Tables whose rows must carry a `Settle` cell (live | settled) - the row says
# whether its move is finished. A live row's move is a mid-session snapshot.
SETTLE_TABLES = {"EU/UK — Headline table", "AU (ASX) — Headline table",
                 "APAC/Gulf — Headline table", "EU/UK — Settled table"}
SETTLE_VALUES = {"live", "settled"}

# A catalyst cell that says the lookup was NOT performed. Such a row must
# carry NO verdict - the 2026-11-05 EU run published "N" beside "catalyst
# lookup not performed", a false verdict on 10% of that run's researched rows.
NO_RESEARCH_MARKERS = ("no catalyst lookup", "pending catalyst lookup",
                       "not performed", "outside the per-run budget",
                       "lookup not performed", "no lookup performed")

# Rows per market in the EU/UK and APAC/Gulf tables. Without the cap the EU
# table was 28% Sweden over nine runs while Belgium and Greece never appeared.
EU_MARKET_CAP = 4
APAC_MARKET_CAP = 3

# Column headers as they appear in the artifact. The header cell is matched
# loosely so a renderer may pad it ("Ref asof", "ref_close_asof", ...).
COLUMN_PATTERNS = {
    "ref_close_source": r"^ref source$|^ref_close_source$|^ref source \(.*\)$",
    "ref_close_asof": r"^ref asof$|^ref_close_asof$|^ref asof \(.*\)$",
    "us_tradeable": r"^us tradeable$|^us_tradeable$|^us tradeable \(.*\)$",
    "move_vs_avg_daily": r"^move vs avg daily$|^move_vs_avg_daily$",
    "settle": r"^settle$|^settle state$|^session state$",
    "move_at_scan": r"^move @08:00$|^move at 08:00$|^scan move$",
    "delta_vs_scan": r"^Δ vs scan$|^delta vs scan$|^vs scan$",
    "market": r"^market$|^market \(.*\)$",
    "session_asof": r"^session asof$|^session_asof$|^session \(.*\)$",
    "catalyst": r"^catalyst$|^catalyst \(.*\)$",
    "earn": r"^earn$|^earn \(.*\)$|^earnings-driven$|^earnings driven$",
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
    "APAC/Gulf — Headline table": "APAC",
    "EU/UK — Settled table": "EU",
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
          day, 18:00 ET after the ASX DST change), so the artifact's
          `ref_close_asof` for an AU row is the ET stamp of the base bar -
          one calendar day BEFORE the ASX session the bar carries. The base
          session is the ASX session immediately before the reported one, so
          the oldest label the artifact may carry is that session's date
          minus one day.
    """
    if not scan_date:
        return None
    if venue == "US":
        s1 = prior_session_date(scan_date, "US")
        return prior_session_date(s1, "US") if s1 else None
    if venue in ("AU", "APAC"):
        # BUG FIXED 2026-11-09. This used to be
        #   prior_session_date(scan_date - 1 day, "AU")
        # which walks the SESSION calendar but forgets the one-day stamp
        # shift. On a Tue-Fri scan the walk and the shift cancelled out (the
        # floor landed on the same label the pipeline emits), so the bug
        # stayed hidden for every artifact published 2026-11-04..11-06. On a
        # MONDAY scan, scan_date - 1 is a Sunday, the walk lands on the
        # Friday, and the floor came out one day NEWER than the label the
        # pipeline can emit - so a perfectly correct artifact was rejected:
        # 25 of 25 ASX rows failed on the 2026-11-09 run (VNT's base close
        # 5.73 is the Friday Nov 6 ASX close, labelled 2026-11-05 by its
        # 18:00 ET stamp - the value was right, the floor was wrong).
        # The base session is the ASX/APAC session before the scan date; its
        # label is one calendar day earlier. (India and Saudi Arabia are the
        # exceptions - their sessions open AFTER midnight ET, so their label
        # IS the session date; the looser floor covers both.)
        base = prior_session_date(scan_date, venue)
        if not base:
            return None
        try:
            d = datetime.datetime.strptime(base, "%Y-%m-%d").date()
            return (d - datetime.timedelta(days=1)).isoformat()
        except Exception:
            return None
    return prior_session_date(scan_date, venue)


def row_ref_floor(session_asof, venue):
    """The oldest base label a row with this session label may carry.

    A foreign row publishes the session it reports (`Session asof`) and the
    base it is measured against (`Ref asof`). The base must be the session
    IMMEDIATELY before the row's OWN session - not the session before the
    scan date. A venue whose screener feed lags a session (Poland on
    2026-11-11 reported the Nov 10 session while the rest of the world
    reported Nov 11) would otherwise be flagged as stale for carrying an
    honest base.

    THE LABEL CONVENTION DIFFERS BY VENUE, and it is the reason this is
    per-row. Yahoo stamps a daily bar at the session OPEN in the venue's local
    time, so:
      * EU/UK venues open AFTER midnight ET (London 03:00 ET), so the bar's
        ET date IS the session date;
      * ASX and the Asian venues open the EVENING BEFORE, 19:00-22:45 ET, so
        the bar's ET date is the session date MINUS one day;
      * and the MOST RECENT bar of a just-closed session is stamped at its
        actual close (00:13 ET for ASX), so its ET date is the session date.
    The floor therefore shifts by one day for AU/APAC. Measured 2026-11-11:
    an ASX row reported session 2026-11-11 with base 2026-11-09 (a 2-day
    label gap), an Indian row session 2026-11-10 with base 2026-11-08.
    """
    try:
        s = datetime.datetime.strptime(session_asof, "%Y-%m-%d").date()
    except Exception:
        return None
    prev = prior_session_date(s.isoformat(), venue)
    if not prev:
        return None
    if venue in ("AU", "APAC"):
        try:
            prev = (datetime.datetime.strptime(prev, "%Y-%m-%d").date()
                    - datetime.timedelta(days=1)).isoformat()
        except Exception:
            return None
    return prev


def scan_date_of(text):
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
    # The scan artifact and the 12:15 ET settlement artifact have different
    # skeletons; which one this is decides the required sections.
    is_settlement = "EU/UK — Settled table" in sections
    req_sections = SETTLE_SECTIONS if is_settlement else REQUIRED_SECTIONS
    order = [s for s in sections if s not in FORBIDDEN_SECTIONS]
    missing = [s for s in req_sections if s not in sections]
    if missing:
        failures.append(f"SECTIONS: missing {missing}")
    present = [s for s in req_sections if s in sections]
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
    if is_settlement:
        # The settlement pass publishes NO US rows: at 12:15 ET the US session
        # is open, and a live intraday price presented as a close would be a
        # fabricated settle.
        for s in ("US — Headline table", "US — QUIET one-liners"):
            if s in sections:
                failures.append(f"SECTIONS: the settlement artifact carries a `{s}` "
                                f"section - the US session is OPEN at 12:15 ET, so a "
                                f"live intraday price must never be published as a close")

    # ---- every published row ------------------------------------------
    published = []          # (section, table_index, header, row_cells)
    for title in req_sections:
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

    # ---- SETTLE — the row says whether its move is finished -------------
    for title, ti, header, cells, ri in published:
        if title not in SETTLE_TABLES:
            continue
        tag = f"{title} row {ri}"
        idx = column_index(header, "settle")
        if idx is None:
            failures.append(f"SETTLE: {tag} — the table has no `settle` column, so the "
                            f"row does not say whether its move is finished")
            continue
        val = cells[idx].strip().lower() if idx < len(cells) else ""
        if val not in SETTLE_VALUES:
            failures.append(f"SETTLE: {tag} — the `settle` cell is {val!r}, expected "
                            f"'live' or 'settled'")

    # ---- VERDICT — a verdict requires research --------------------------
    for title, ti, header, cells, ri in published:
        cat_idx = column_index(header, "catalyst")
        earn_idx = column_index(header, "earn")
        if cat_idx is None or earn_idx is None:
            continue
        cat = cells[cat_idx].strip() if cat_idx < len(cells) else ""
        earn = cells[earn_idx].strip() if earn_idx < len(cells) else ""
        if earn in ("Y", "N") and any(m in cat.lower() for m in NO_RESEARCH_MARKERS):
            failures.append(
                f"VERDICT: {title} row {ri} — the row publishes the verdict {earn!r} "
                f"beside a catalyst cell that says the lookup was not performed "
                f"({cat!r}); an unresearched row must carry no verdict")

    # ---- MARKETS — the per-market cap ----------------------------------
    for title, cap in (("EU/UK — Headline table", EU_MARKET_CAP),
                       ("APAC/Gulf — Headline table", APAC_MARKET_CAP)):
        if title not in sections:
            continue
        counts = {}
        for ti, (header, rows) in enumerate(parse_tables(sections[title])):
            mkt_idx = column_index(header, "market")
            if mkt_idx is None:
                continue
            for ri, cells in enumerate(rows):
                if mkt_idx < len(cells):
                    m = cells[mkt_idx].strip()
                    counts[m] = counts.get(m, 0) + 1
        for m, n in counts.items():
            if n > cap:
                failures.append(f"MARKETS: {title} — the market {m!r} has {n} rows, "
                                f"over the {cap}-row per-market cap (the table must be a "
                                f"market census, not one market's index)")

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
        if venue == "US":
            # The US passes always report the latest completed session, so the
            # table-level floor is the right test.
            floor = min_ref_date(scan_d, venue)
        else:
            # A FOREIGN row publishes the session it reports (`Session asof`),
            # so its base must be the session immediately before THAT session.
            # The table-level floor would flag an honest row whose venue feed
            # lags a session (Poland on 2026-11-11 reported the Nov 10 session
            # while the rest of the world reported Nov 11).
            sess_idx = column_index(header, "session_asof")
            sess = cells[sess_idx].strip() if (sess_idx is not None and sess_idx < len(cells)) else ""
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", sess):
                failures.append(f"REFCLOSE: {title} row {ri} — the row does not publish "
                                f"the session it reports (`Session asof` = {sess!r}), so "
                                f"its base cannot be checked")
                continue
            floor = row_ref_floor(sess, venue)
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
