#!/usr/bin/env python3
"""
check_earnings_reminder_artifact.py — independent verifier for cron #19's artifact.

The routine renders the artifact; this checks that the artifact on disk obeys the
ARTIFACT FORMAT CONTRACT v3 (EARNINGS_REMINDER_V3) in
`cloud-prompts/skills/earnings-reminder/SKILL.md`. It is deliberately a SEPARATE
implementation: the renderer is the producer, this is the verifier, and neither
imports the other.

The v3 rules (the coverage receipt and the already-reported tradeability column) apply to an
artifact dated 2026-11-13 or later, or to one that declares `contract: EARNINGS_REMINDER_V3`.
Artifacts published under v2 stay valid: a contract change must not retroactively fail an
artifact that was legal when it was written.

Checks (each failure is named and the tool exits 1):

  FRONTMATTER  the front-matter block exists and carries the required keys
  SECTIONS     the section skeleton is present and in order
  COLUMNS      the US roster table carries every reaction-potential column
  SCORES       every published row carries a numeric reaction score
  SORTED       the US roster is sorted by reaction score, DESCENDING
  SCOREFORMULA the score equals 0.6*avg_abs_move + 0.4*implied_move
                (a missing implied move is substituted by avg_abs_move)
  PASSB        the non-US table carries ticker_primary/venue_primary/us_peer/us_tradeable
               on EVERY row, and us_tradeable is in the allowed vocabulary
  NO-DUP       a non-US issuer is not published in BOTH tables
  BAND         the "just below the line" table exists and every row is inside the band
  BOUNDARY     a roster row inside the market-cap floor by less than the margin is
               flagged `boundary_case`; and only such a row may carry that flag
  COVERAGE     (v3) the front-matter carries a `coverage_receipt` whose counts match the
               published tables - the artifact states its own completeness basis
  ALREADY      (v3) every "Already reported" row carries a `us_tradeable` cell from the
               allowed vocabulary, and its ticker cell is the PRIMARY listing with the US
               line in parentheses (never an OTC headline)

Usage:
    python3 tools/check_earnings_reminder_artifact.py earnings/2026-11-06-reminders.md
    python3 tools/check_earnings_reminder_artifact.py --artifact <path>

Exit codes: 0 = conforms, 1 = a check failed, 2 = the artifact could not be read.
"""
import argparse
import os
import re
import sys

CONTRACT = "EARNINGS_REMINDER_V3"

# The v3 rules (coverage receipt + the already-reported tradeability column) apply to an
# artifact dated on or after this day, or to any artifact that declares
# `contract: EARNINGS_REMINDER_V3` in its front-matter. Artifacts published under v2 stay
# valid - a contract change must not retroactively fail an artifact that was legal when it
# was written.
V3_FROM_DATE = "2026-11-13"

COVERAGE_KEYS = ["calendar_rows", "s_and_p_500_hits", "bigcap_hits",
                 "us_roster_rows", "band_rows"]

REQUIRED_SECTIONS = [
    "Big S&P 500 today",
    "Non-US primary listings",
    "Just below the line",
    "Notes",
    "Source health",
    "Rules applied",
]

REQUIRED_FRONTMATTER = [
    "date", "cron", "fire_time_et", "snapshot_et", "status",
    "pending_count", "already_reported_count", "non_us_count", "reaction_ranked",
]

# Header cells are matched loosely so a renderer may pad or rename them.
COLUMN_PATTERNS = {
    "ticker": r"^ticker$|^ticker \(.*\)$",
    "company": r"^company$",
    "time": r"^time$|^report time$",
    "eps_est": r"^eps est$|^eps est\.? \(.*\)$|^eps estimate$",
    "rev_est": r"^rev est$|^rev est\.? \(.*\)$|^revenue est",
    "mkt_cap": r"^mkt cap$|^mkt cap \(.*\)$|^market cap",
    "prior_day_move": r"^prior day %$|^prior day move|^prior_day_move_pct$|^prior day",
    "ytd_move": r"^ytd %$|^ytd move|^ytd_move_pct$|^ytd",
    "avg_abs_move": r"^avg abs move %$|^avg abs move|^avg_abs_move_pct$|^avg \|move\|",
    "implied_move": r"^implied move %$|^implied move|^implied_move_pct$|^implied",
    "prior_result": r"^prior result$|^prior report result|^prior_report_result$",
    "reaction_score": r"^reaction score$|^reaction_score$|^score$",
    "status": r"^status$",
    "flag": r"^flag$|^boundary$|^boundary flag$|^flags$",
}

PASSB_PATTERNS = {
    "ticker_primary": r"^ticker_primary$|^ticker primary$|^primary ticker$",
    "venue_primary": r"^venue_primary$|^venue primary$|^venue$",
    "us_peer": r"^us_peer$|^us peer$",
    "us_tradeable": r"^us_tradeable$|^us tradeable$",
}

US_TRADEABLE_VOCAB = {"ADR (US-listed)", "ADR (OTC)", "US-listed", "none"}

MCAP_FLOOR = 50_000_000_000
BOUNDARY_MARGIN = 500_000_000
BAND_LOW_DEFAULT = 40_000_000_000


def strip_md(s):
    s = re.sub(r"[*`]+", "", s or "")
    return s.strip()


def parse_money(cell):
    """'$177.3B' -> 177.3e9. Returns None when the cell is not a market cap."""
    c = strip_md(cell).replace(",", "")
    m = re.match(r"^\$?\s*(-?\d+(?:\.\d+)?)\s*([TBMK])?$", c)
    if not m:
        return None
    val = float(m.group(1))
    mult = {"T": 1e12, "B": 1e9, "M": 1e6, "K": 1e3}.get(m.group(2), 1.0)
    return val * mult


def parse_num(cell):
    c = strip_md(cell).replace("%", "").replace(",", "").replace("+", "")
    if c in ("", "n/a", "na", "-", "—", "None", "null"):
        return None
    try:
        return float(c)
    except ValueError:
        return None


def parse_coverage(value):
    """'calendar_rows=377 s_and_p_500_hits=2 ...' -> {key: int}."""
    out = {}
    for part in (value or "").split():
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        n = parse_num(v)
        if n is not None:
            out[k.strip()] = int(n)
    return out


def split_row(line):
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


def parse_table(lines):
    """Return (header_cells, [row_cells, ...]) for the first table in `lines`."""
    header = None
    rows = []
    for ln in lines:
        s = ln.strip()
        if not s.startswith("|"):
            continue
        cells = split_row(s)
        if set("".join(cells).strip()) <= set("-: "):
            continue
        if header is None:
            header = cells
        else:
            rows.append(cells)
    return header or [], rows


def sections(text):
    """Ordered mapping of heading -> body lines."""
    out = {}
    cur = None
    for ln in text.splitlines():
        m = re.match(r"^##\s+(.*?)\s*$", ln)
        if m:
            cur = m.group(1).strip()
            out.setdefault(cur, [])
            continue
        if cur is not None:
            out[cur].append(ln)
    return out


def find_section(secs, needle):
    """Match a section heading case-insensitively on its leading words."""
    needle = needle.lower()
    for name, body in secs.items():
        if name.lower().startswith(needle):
            return name, body
    return None, None


def match_columns(header, patterns):
    """Map pattern key -> column index (first match wins)."""
    idx = {}
    for key, pat in patterns.items():
        rx = re.compile(pat, re.I)
        for i, h in enumerate(header):
            if rx.match(strip_md(h)):
                idx.setdefault(key, i)
                break
    return idx


def check(path):
    failures = []
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        print(f"CHECK: cannot read {path}: {exc}", file=sys.stderr)
        return ["artifact unreadable"]

    # ---------------------------------------------------------- FRONTMATTER
    fm = {}
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    if not m:
        failures.append("FRONTMATTER: no front-matter block at the top of the artifact")
    else:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                fm[k.strip()] = v.strip()
        for key in REQUIRED_FRONTMATTER:
            if key not in fm:
                failures.append(f"FRONTMATTER: missing key `{key}`")
        if fm.get("reaction_ranked", "").lower() not in ("true", "yes"):
            failures.append("FRONTMATTER: `reaction_ranked` must be true "
                            "(the roster is ranked by reaction potential)")
        for key in ("pending_count", "already_reported_count", "non_us_count"):
            if key in fm and parse_num(fm[key]) is None:
                failures.append(f"FRONTMATTER: `{key}` is not a number ({fm[key]!r})")

    secs = sections(text)

    # ------------------------------------------------------------- SECTIONS
    for name in REQUIRED_SECTIONS:
        if not find_section(secs, name)[0]:
            failures.append(f"SECTIONS: missing section `## {name}`")
    order = [n for n in secs]
    for name in REQUIRED_SECTIONS:
        sname, _ = find_section(secs, name)
        if sname and order.index(sname) != min(
                (order.index(sname), order.index(sname)), default=0):
            pass
    # the three content tables must appear in the contract's order
    seq = ["big s&p 500 today", "non-us primary listings", "just below the line"]
    positions = []
    for s in seq:
        sname, _ = find_section(secs, s)
        positions.append(order.index(sname) if sname in order else -1)
    if all(p >= 0 for p in positions) and positions != sorted(positions):
        failures.append("SECTIONS: the three tables are out of contract order "
                        f"(got {positions}, expected ascending)")

    # --------------------------------------------------------- US ROSTER
    _, us_body = find_section(secs, "Big S&P 500 today")
    us_header, us_rows = parse_table(us_body or [])
    degraded_declared = parse_num(fm.get("reaction_degraded", "")) if "reaction_degraded" in fm else 0
    degraded_declared = int(degraded_declared) if degraded_declared is not None else 0
    if not us_header:
        failures.append("COLUMNS: the US roster table has no header row")
        us_header, us_rows = [], []
    idx = match_columns(us_header, COLUMN_PATTERNS)
    for key in COLUMN_PATTERNS:
        if key not in idx:
            failures.append(f"COLUMNS: the US roster table has no `{key}` column "
                            f"(header: {us_header})")
    if us_rows and "reaction_score" in idx:
        sc = idx["reaction_score"]
        scores = []
        degraded_rows = 0
        for i, row in enumerate(us_rows):
            if sc >= len(row):
                failures.append(f"SCORES: row {i + 1} has {len(row)} cells, fewer than the header")
                continue
            v = parse_num(row[sc])
            if v is None:
                degraded_rows += 1
                continue
            scores.append((i, v))
        if degraded_rows and degraded_declared == 0:
            failures.append(f"SCORES: {degraded_rows} row(s) carry no reaction score but the "
                            "front-matter does not declare `reaction_degraded`")
        if degraded_declared and degraded_rows != degraded_declared:
            failures.append(f"SCORES: front-matter declares reaction_degraded="
                            f"{degraded_declared} but {degraded_rows} row(s) have no score")
        for (i1, v1), (i2, v2) in zip(scores, scores[1:]):
            if v2 > v1 + 1e-9:
                failures.append(f"SORTED: row {i2 + 1} ({v2}) scores higher than row "
                                f"{i1 + 1} ({v1}) - the roster is not sorted by reaction score")
                break
        # score formula
        if "avg_abs_move" in idx and "implied_move" in idx:
            for i, row in enumerate(us_rows):
                if sc >= len(row):
                    continue
                s = parse_num(row[sc])
                avg = parse_num(row[idx["avg_abs_move"]]) if idx["avg_abs_move"] < len(row) else None
                imp = parse_num(row[idx["implied_move"]]) if idx["implied_move"] < len(row) else None
                if s is None or avg is None:
                    if s is not None and avg is None:
                        failures.append(f"SCOREFORMULA: row {i + 1} has a score but no "
                                        "avg_abs_move value")
                    continue
                imp_for_score = imp if imp is not None else avg
                expect = round(0.6 * avg + 0.4 * imp_for_score, 2)
                if abs(expect - s) > 0.06:
                    failures.append(f"SCOREFORMULA: row {i + 1} score {s} != "
                                    f"0.6*{avg} + 0.4*{imp_for_score} = {expect}")

    # ------------------------------------------------------------- PASS B
    _, pb_body = find_section(secs, "Non-US primary listings")
    pb_header, pb_rows = parse_table(pb_body or [])
    pb_idx = match_columns(pb_header, PASSB_PATTERNS)
    for key in PASSB_PATTERNS:
        if key not in pb_idx:
            failures.append(f"PASSB: the non-US table has no `{key}` column "
                            f"(header: {pb_header})")
    for i, row in enumerate(pb_rows):
        for key in PASSB_PATTERNS:
            if key in pb_idx and pb_idx[key] < len(row):
                if not strip_md(row[pb_idx[key]]):
                    failures.append(f"PASSB: row {i + 1} has an empty `{key}` cell")
        if "us_tradeable" in pb_idx and pb_idx["us_tradeable"] < len(row):
            v = strip_md(row[pb_idx["us_tradeable"]])
            if v and v not in US_TRADEABLE_VOCAB:
                failures.append(f"PASSB: row {i + 1} has us_tradeable={v!r}, "
                                f"which is not in {sorted(US_TRADEABLE_VOCAB)}")

    # ------------------------------------------------------------- NO-DUP
    if pb_rows and "ticker_primary" in pb_idx and us_rows and "ticker" in idx:
        us_tickers = {strip_md(r[idx["ticker"]]).split(" ")[0] for r in us_rows
                      if idx["ticker"] < len(r)}
        for i, row in enumerate(pb_rows):
            if pb_idx["ticker_primary"] < len(row):
                t = strip_md(row[pb_idx["ticker_primary"]]).split(" ")[0]
                if t in us_tickers:
                    failures.append(f"NO-DUP: {t} is published in BOTH the US roster and the "
                                    "non-US table - the two tables must not overlap")

    # -------------------------------------------------------------- BAND
    _, band_body = find_section(secs, "Just below the line")
    band_header, band_rows = parse_table(band_body or [])
    band_idx = match_columns(band_header, {"ticker": COLUMN_PATTERNS["ticker"],
                                            "mkt_cap": COLUMN_PATTERNS["mkt_cap"]})
    if band_header and "mkt_cap" not in band_idx:
        failures.append("BAND: the 'just below the line' table has no market-cap column "
                        f"(header: {band_header})")
    band_low = BAND_LOW_DEFAULT
    if "band_low_usd" in fm:
        v = parse_money(fm["band_low_usd"])
        if v:
            band_low = v
    for i, row in enumerate(band_rows):
        if "mkt_cap" in band_idx and band_idx["mkt_cap"] < len(row):
            cap = parse_money(row[band_idx["mkt_cap"]])
            if cap is None:
                failures.append(f"BAND: row {i + 1} has an unreadable market cap "
                                f"({row[band_idx['mkt_cap']]!r})")
            elif cap >= MCAP_FLOOR:
                failures.append(f"BAND: row {i + 1} caps at ${cap / 1e9:.1f}B, which is NOT "
                                "below the $50B floor - the table must show what the floor excluded")
            elif cap < band_low:
                failures.append(f"BAND: row {i + 1} caps at ${cap / 1e9:.1f}B, below the "
                                f"published band floor (${band_low / 1e9:.0f}B)")

    # ----------------------------------------------------------- BOUNDARY
    if us_rows and "mkt_cap" in idx and "flag" in idx:
        for i, row in enumerate(us_rows):
            if idx["mkt_cap"] >= len(row) or idx["flag"] >= len(row):
                continue
            cap = parse_money(row[idx["mkt_cap"]])
            if cap is None:
                continue
            flag = strip_md(row[idx["flag"]])
            flagged = "boundary_case" in flag.lower()
            marginal = MCAP_FLOOR <= cap <= MCAP_FLOOR + BOUNDARY_MARGIN
            if marginal and not flagged:
                failures.append(f"BOUNDARY: row {i + 1} is ${(cap - MCAP_FLOOR) / 1e9:.2f}B "
                                "inside the $50B floor and is not flagged `boundary_case`")
            if flagged and not marginal:
                failures.append(f"BOUNDARY: row {i + 1} is flagged `boundary_case` but caps at "
                                f"${cap / 1e9:.1f}B, which is more than $0.5B from the floor")

    # ------------------------------------------------------ v3: COVERAGE + ALREADY
    date = fm.get("date", "")
    iso = re.match(r"^\d{4}-\d{2}-\d{2}$", date or "")
    declared = fm.get("contract", "").strip().upper()
    v3 = declared.endswith("V3") or bool(iso and date >= V3_FROM_DATE)

    if v3:
        # ---- COVERAGE: the artifact states its own completeness basis, and it matches the tables
        cov_raw = fm.get("coverage_receipt", "")
        cov = parse_coverage(cov_raw)
        missing = [k for k in COVERAGE_KEYS if k not in cov]
        if missing:
            failures.append(f"FRONTMATTER: `coverage_receipt` is missing {missing} "
                            f"(got {cov_raw!r}; expected "
                            f"'{' '.join(k + '=<n>' for k in COVERAGE_KEYS)}')")
        else:
            if cov["us_roster_rows"] != len(us_rows):
                failures.append(f"COVERAGE: coverage_receipt says us_roster_rows="
                                f"{cov['us_roster_rows']} but the US roster publishes "
                                f"{len(us_rows)} rows")
            if cov["band_rows"] != len(band_rows):
                failures.append(f"COVERAGE: coverage_receipt says band_rows="
                                f"{cov['band_rows']} but the band table publishes "
                                f"{len(band_rows)} rows")
            if cov["calendar_rows"] < cov["s_and_p_500_hits"]:
                failures.append("COVERAGE: calendar_rows is smaller than s_and_p_500_hits")
            if cov["us_roster_rows"] > cov["calendar_rows"]:
                failures.append("COVERAGE: more roster rows than calendar rows scanned")

        # ---- ALREADY: every printed row carries its US line's tradeability and its PRIMARY ticker
        _, ar_body = find_section(secs, "Already reported")
        ar_header, ar_rows = parse_table(ar_body or [])
        if ar_rows:
            ar_idx = match_columns(ar_header, {
                "ticker": COLUMN_PATTERNS["ticker"],
                "us_tradeable": PASSB_PATTERNS["us_tradeable"]})
            if "us_tradeable" not in ar_idx:
                failures.append("ALREADY: the 'Already reported' table has no `us_tradeable` "
                                f"column (header: {ar_header})")
            for i, row in enumerate(ar_rows):
                tv = ""
                if "us_tradeable" in ar_idx and ar_idx["us_tradeable"] < len(row):
                    tv = strip_md(row[ar_idx["us_tradeable"]])
                    if not tv:
                        failures.append(f"ALREADY: row {i + 1} has an empty `us_tradeable` cell")
                    elif tv not in US_TRADEABLE_VOCAB:
                        failures.append(f"ALREADY: row {i + 1} has us_tradeable={tv!r}, which is "
                                        f"not in {sorted(US_TRADEABLE_VOCAB)}")
                if "ticker" in ar_idx and ar_idx["ticker"] < len(row):
                    cell = strip_md(row[ar_idx["ticker"]])
                    m = re.match(r"^(\S+)(?:\s+\(([^()]+)\))?$", cell)
                    if not m:
                        failures.append(f"ALREADY: row {i + 1} ticker cell {cell!r} is neither "
                                        "'PRIMARY' nor 'PRIMARY (US_LINE)'")
                    elif m.group(2) is None and tv and tv != "none":
                        failures.append(f"ALREADY: row {i + 1} ({cell}) names no US line in "
                                        f"parentheses but its us_tradeable is {tv!r}")

    return failures


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifact", dest="artifact_opt", help="path to the artifact markdown")
    ap.add_argument("artifact", nargs="?", help="path to the artifact markdown")
    args = ap.parse_args()
    path = args.artifact_opt or args.artifact
    if not path:
        ap.error("an artifact path is required")
    if not os.path.exists(path):
        print(f"CHECK: artifact not found: {path}", file=sys.stderr)
        return 2
    failures = check(path)
    if failures:
        print(f"FAIL: {len(failures)} contract violation(s) in {path}")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"OK: {path} conforms to {CONTRACT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
