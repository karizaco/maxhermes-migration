#!/usr/bin/env python3
"""
check_earnings_reminder_artifact.py — independent verifier for cron #19's artifact.

The routine renders the artifact; this checks that the artifact on disk obeys the
ARTIFACT FORMAT CONTRACT v4 (EARNINGS_REMINDER_V4) in
`cloud-prompts/skills/earnings-reminder/SKILL.md`. It is deliberately a SEPARATE
implementation: the renderer is the producer, this is the verifier, and neither
imports the other.

The rule set is decided by the CONTRACT MARKER, not by the calendar:

  EARNINGS_REMINDER_V4 (or an artifact dated 2026-11-16 or later) -> the v4 rules
  EARNINGS_REMINDER_V3                                         -> the v3 rules
  an older artifact with no marker                             -> the v2 rules

Artifacts published under an older contract stay valid: a contract change must not retroactively
fail an artifact that was legal when it was written. The applied rule set is printed on every run,
so a grandfathered artifact is visible as grandfathered and not as silently unchecked.

Checks (each failure is named and the tool exits 1; EVERY check also reports on its PASS path):

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
  TLDR         (v4) the `## TL;DR` section exists and opens with the coverage floor, in
               words, with the floor and the band named and the consequence stated
  FLOORKEY     (v4) the front matter carries a `coverage_floor` whose arithmetic adds up
               (us_population = below_band + band + at_or_above_floor + no_cap) and whose
               constants match the ones the band and the floor are applied with
  FLOORSRC     (v4) the `## Source health` table carries the coverage floor as a row of
               its own, naming the scanner column and the constant

Usage:
    python3 tools/check_earnings_reminder_artifact.py earnings/2026-11-06-reminders.md
    python3 tools/check_earnings_reminder_artifact.py --artifact <path>

Exit codes: 0 = conforms, 1 = a check failed, 2 = the artifact could not be read.
"""
import argparse
import os
import re
import sys

CONTRACT = "EARNINGS_REMINDER_V4"

# The CONTRACT MARKER decides which rule set applies to a given artifact. v3 (the coverage
# receipt + the already-reported tradeability column) is GRANDFATHERED: an artifact that declares
# it was written under the v3 contract and is checked against the rules that were in force then.
# A checker that fails a historical artifact for a rule that post-dates it is a false alarm, and
# the fleet's auditors treat those as findings.
CONTRACT_VERSION = "EARNINGS_REMINDER_V4"
LEGACY_CONTRACT_VERSIONS = ("EARNINGS_REMINDER_V3",)

# Backstops for artifacts that carry no marker at all: a v4 artifact is dated 2026-11-16 or
# later, a v3 artifact 2026-11-13 or later, and anything older is v2.
V4_FROM_DATE = "2026-11-16"
V3_FROM_DATE = "2026-11-13"

# Every check reports on its PASS path too - a check that only speaks on failure is not a gate.
CHECK_CODES = [
    ("FRONTMATTER", "the front-matter block is present and carries every required key"),
    ("SECTIONS", "the section skeleton is present and in contract order"),
    ("COLUMNS", "the US roster table carries every reaction-potential column"),
    ("SCORES", "every published row carries a numeric reaction score"),
    ("SORTED", "the US roster is sorted by reaction score, descending"),
    ("SCOREFORMULA", "every reaction score equals 0.6*avg_abs_move + 0.4*implied_move"),
    ("PASSB", "every non-US row carries its ticker, venue, peer and tradeability"),
    ("NO-DUP", "no issuer is published in both the US roster and the non-US table"),
    ("BAND", "the 'just below the line' table exists and every row is inside the band"),
    ("BOUNDARY", "a roster row inside the floor by less than the margin carries `boundary_case`"),
    ("COVERAGE", "(v3) the coverage receipt matches the published tables"),
    ("ALREADY", "(v3) every already-reported row carries its tradeability and its primary ticker"),
    ("TLDR", "(v4) the `## TL;DR` section opens with the coverage-floor disclosure"),
    ("FLOORKEY", "(v4) the front matter carries a `coverage_floor` whose arithmetic adds up"),
    ("FLOORSRC", "(v4) the `## Source health` table carries the coverage floor as its own row"),
]

COVERAGE_KEYS = ["calendar_rows", "s_and_p_500_hits", "bigcap_hits",
                 "us_roster_rows", "band_rows"]

# The v4 coverage-floor key: the constants and the measured decomposition of the scanner's
# US population.
FLOOR_KEYS = ["floor_usd", "band_low_usd", "us_population", "below_band_us",
              "band_us", "at_or_above_floor_us", "no_cap_us", "source"]

# The words that make the disclosure a disclosure. A floor that is only implied is a floor that
# reads as a missing company.
SCOPE_TOKENS = ("out of scope", "not on this list")
SCANNER_TOKENS = ("tradingview", "scanner")
CAP_COLUMN_RE = re.compile(r"market[\s_-]?cap", re.I)

REQUIRED_SECTIONS = [
    "Big S&P 500 today",
    "Non-US primary listings",
    "Just below the line",
    "Notes",
    "Source health",
    "Rules applied",
]

# v4 puts the TL;DR first, before the three tables.
V4_SECTIONS = ["TL;DR"] + REQUIRED_SECTIONS

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


def parse_kv(value):
    """'floor_usd=50000000000 band_low_usd=40000000000 ...' -> {key: raw value}.

    A token WITHOUT an '=' continues the previous key's value, so a free-text source
    ('source=TradingView america scanner (market_cap_basic, issuer-level USD)') stays with its
    key instead of being shredded into separate tokens.
    """
    out = {}
    last = None
    for part in (value or "").split():
        if "=" in part:
            k, v = part.split("=", 1)
            k = k.strip()
            if not k:
                continue
            out[k] = v
            last = k
        elif last is not None:
            out[last] = (out[last] + " " + part).strip()
    return out


def amount_regex(value):
    """A regex that matches this money amount in any rendering a writer would use.

    '$50B', '50B', '$50 billion', '50000000000' and '50,000,000,000' all name 50_000_000_000.
    The leading look-behind stops '$150B' from matching '$50B'.
    """
    if not value:
        return None
    alts = []
    for mult, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
        if value % mult == 0:
            n = value / mult
            alts.append(re.escape(f"{n:g}{suffix}"))
            alts.append(re.escape(f"{n:,.0f}{suffix}"))
            alts.append(rf"{n:g}\s*billion")
    alts.append(re.escape(f"{value:,}"))
    alts.append(re.escape(str(value)))
    pat = "|".join(alts)
    return re.compile(r"(?<![\d.,])(" + pat + r")", re.I)


def mentions_amount(text, value):
    """Does `text` name this money amount?"""
    rx = amount_regex(value)
    return bool(rx and rx.search(text or ""))


def resolve_contract(fm, date):
    """Which rule set applies to this artifact? The MARKER decides.

    Returns (version, reason). `version` is 'v4', 'v3' or 'v2'.
    """
    declared = (fm.get("contract") or "").strip().upper()
    if declared == CONTRACT_VERSION:
        return "v4", f"the artifact declares the current contract marker ({CONTRACT_VERSION})"
    if declared in LEGACY_CONTRACT_VERSIONS:
        return "v3", (f"the artifact declares the LEGACY contract marker ({declared}) - it is "
                      "checked against the rules that were in force when it was written")
    if not declared and date:
        if date >= V4_FROM_DATE:
            return "v4", (f"the artifact is dated {date} (on or after {V4_FROM_DATE}) and "
                          "declares no contract marker, so it is checked as v4")
        if date >= V3_FROM_DATE:
            return "v3", (f"the artifact is dated {date} (on or after {V3_FROM_DATE}) and "
                          "declares no contract marker, so it is checked as v3")
    return "v2", (f"the artifact predates the {V3_FROM_DATE} contract and declares no marker, "
                  "so it is checked as v2")


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
    notes = []          # (check code, text) - a check that had NOTHING to verify
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        print(f"CHECK: cannot read {path}: {exc}", file=sys.stderr)
        return ["artifact unreadable"], [], "v2", "the artifact could not be read"

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

    # ------------------------------------------------- CONTRACT RESOLUTION
    # The marker decides which rule set applies. A grandfathered artifact is REPORTED as
    # grandfathered, never silently unchecked.
    date = fm.get("date", "")
    iso = re.match(r"^\d{4}-\d{2}-\d{2}$", date or "")
    date = date if iso else ""
    version, version_reason = resolve_contract(fm, date)
    required_sections = V4_SECTIONS if version == "v4" else REQUIRED_SECTIONS

    # ------------------------------------------------------------- SECTIONS
    for name in required_sections:
        if not find_section(secs, name)[0]:
            failures.append(f"SECTIONS: missing section `## {name}`")
    order = [n for n in secs]
    for name in required_sections:
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
    # v4 puts the TL;DR FIRST: the reader meets the scope limit before the tables.
    if version == "v4":
        tldr_name, _ = find_section(secs, "TL;DR")
        if tldr_name and tldr_name in order:
            first_table = next((order.index(n) for n in ("Big S&P 500 today",)
                                if n in order), None)
            if first_table is not None and order.index(tldr_name) > first_table:
                failures.append("SECTIONS: the `## TL;DR` section must come BEFORE the tables "
                                "- the scope limit is what the reader meets first")

    # --------------------------------------------------------- US ROSTER
    _, us_body = find_section(secs, "Big S&P 500 today")
    us_header, us_rows = parse_table(us_body or [])
    degraded_declared = parse_num(fm.get("reaction_degraded", "")) if "reaction_degraded" in fm else 0
    degraded_declared = int(degraded_declared) if degraded_declared is not None else 0
    if not us_header:
        failures.append("COLUMNS: the US roster table has no header row")
        us_header, us_rows = [], []
    if not us_rows:
        notes.append(("SCORES", "the US roster is empty - there is no row to score"))
        notes.append(("SORTED", "the US roster is empty - there is nothing to sort"))
        notes.append(("SCOREFORMULA", "the US roster is empty - there is no score to re-derive"))
        notes.append(("BOUNDARY", "the US roster is empty - there is no cap to test"))
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
    if not pb_rows:
        notes.append(("PASSB", "the non-US table is empty - there is no row to check"))
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
    if not band_rows:
        notes.append(("BAND", "the band table is empty - there is no row to check against the "
                              "band"))
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
    if version in ("v3", "v4"):
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
        if not ar_rows:
            notes.append(("ALREADY", "the 'Already reported' table is empty - there is no row "
                                     "to check"))
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

    # ------------------------------------------------- v4: THE PUBLISHED FLOOR
    # A floor that is not published reads as a missing company. v4 requires the artifact to
    # SAY that a floor exists, where it comes from, and how many names it removes - in the
    # front matter, in the TL;DR and in the source-health table.
    if version == "v4":
        floor_usd = MCAP_FLOOR
        band_low_v = BAND_LOW_DEFAULT
        if "band_low_usd" in fm:
            v = parse_money(fm["band_low_usd"])
            if v:
                band_low_v = v

        # ---- TLDR: the floor, in words, where the reader meets it
        tldr_name, tldr_body = find_section(secs, "TL;DR")
        if not tldr_name:
            failures.append("TLDR: the artifact has no `## TL;DR` section - under "
                            f"{CONTRACT_VERSION} the coverage floor is stated in the first "
                            "section of the file, before the tables")
        else:
            text = "\n".join(tldr_body or [])
            low = text.lower()
            for tok in SCOPE_TOKENS:
                if tok not in low:
                    failures.append(f"TLDR: the `## TL;DR` section does not say {tok!r} - a "
                                    "reader must be able to tell a scope limit from a missing "
                                    "company")
            if not mentions_amount(text, floor_usd):
                failures.append(f"TLDR: the `## TL;DR` section does not name the market-cap floor "
                                f"(${floor_usd / 1e9:.0f}B) - the band that bounds the list must "
                                "be stated")
            if not mentions_amount(text, band_low_v):
                failures.append(f"TLDR: the `## TL;DR` section does not name the band floor "
                                f"(${band_low_v / 1e9:.0f}B) - the consequence ('a US reporter "
                                f"below ${band_low_v / 1e9:.0f}B is out of scope') is stated "
                                "against that number")
            if not any(tok in low for tok in SCANNER_TOKENS):
                failures.append("TLDR: the `## TL;DR` section does not name the source of the "
                                "floor (the TradingView scanner) - the floor must be auditable")

        # ---- FLOORKEY: the machine-readable floor, with its arithmetic
        raw_floor = fm.get("coverage_floor", "")
        if not raw_floor:
            failures.append("FLOORKEY: the front matter carries no `coverage_floor` - under "
                            f"{CONTRACT_VERSION} the floor, the band it bounds and the counts "
                            "that bound the list are machine-readable")
        else:
            kv = parse_kv(raw_floor)
            missing = [k for k in FLOOR_KEYS if k not in kv]
            if missing:
                failures.append(f"FLOORKEY: `coverage_floor` is missing {missing} (got "
                                f"{raw_floor!r}; expected "
                                f"'{' '.join(k + '=<n>' for k in FLOOR_KEYS)}')")
            else:
                nums = {k: parse_num(kv[k]) for k in FLOOR_KEYS if k != "source"}
                bad_nums = [k for k, v in nums.items() if v is None]
                if bad_nums:
                    failures.append(f"FLOORKEY: `coverage_floor` has non-numeric values for "
                                    f"{bad_nums} (got {raw_floor!r})")
                else:
                    if nums["floor_usd"] != floor_usd:
                        failures.append(f"FLOORKEY: `coverage_floor` says floor_usd="
                                        f"{nums['floor_usd']:.0f} but the market-cap floor is "
                                        f"${floor_usd:.0f}")
                    if nums["band_low_usd"] != band_low_v:
                        failures.append(f"FLOORKEY: `coverage_floor` says band_low_usd="
                                        f"{nums['band_low_usd']:.0f} but the band floor is "
                                        f"${band_low_v:.0f}")
                    if "band_low_usd" in fm:
                        top = parse_money(fm["band_low_usd"])
                        if top and top != nums["band_low_usd"]:
                            failures.append(f"FLOORKEY: `coverage_floor` says band_low_usd="
                                            f"{nums['band_low_usd']:.0f} but the front matter's "
                                            f"`band_low_usd` says {top:.0f} - the two must agree")
                    total = (nums["below_band_us"] + nums["band_us"]
                             + nums["at_or_above_floor_us"] + nums["no_cap_us"])
                    if total != nums["us_population"]:
                        failures.append(f"FLOORKEY: `coverage_floor` does not add up - "
                                        f"us_population={nums['us_population']:.0f} but "
                                        f"below_band_us + band_us + at_or_above_floor_us + "
                                        f"no_cap_us = {total:.0f}")
                    if nums["below_band_us"] <= 0:
                        failures.append("FLOORKEY: `coverage_floor` says below_band_us="
                                        f"{nums['below_band_us']:.0f} - the count of names the "
                                        "floor removed from scope must be positive")
                    if nums["below_band_us"] >= nums["us_population"]:
                        failures.append("FLOORKEY: `coverage_floor` says below_band_us="
                                        f"{nums['below_band_us']:.0f} of us_population="
                                        f"{nums['us_population']:.0f} - the whole population "
                                        "cannot be below the band")
                    if nums["band_us"] < len(band_rows):
                        failures.append(f"FLOORKEY: `coverage_floor` says band_us="
                                        f"{nums['band_us']:.0f} but the band table publishes "
                                        f"{len(band_rows)} rows")
                    if "coverage_receipt" in fm:
                        cov_floor = parse_coverage(fm["coverage_receipt"])
                        if "bigcap_hits" in cov_floor:
                            if cov_floor["bigcap_hits"] > nums["at_or_above_floor_us"]:
                                failures.append(f"FLOORKEY: the coverage receipt says "
                                                f"bigcap_hits={cov_floor['bigcap_hits']} but "
                                                "`coverage_floor` says only "
                                                f"{nums['at_or_above_floor_us']:.0f} US names "
                                                "are at or above the floor")
                src = kv.get("source", "")
                if not any(tok in src.lower() for tok in SCANNER_TOKENS):
                    failures.append("FLOORKEY: `coverage_floor` does not name the source of the "
                                    f"floor (got {src!r})")
                if not CAP_COLUMN_RE.search(src):
                    failures.append("FLOORKEY: `coverage_floor` does not name the scanner COLUMN "
                                    f"the floor is applied to (got {src!r}) - the market-cap "
                                    "column is what makes the floor auditable")

        # ---- FLOORSRC: the floor as a row of the source-health table
        _, sh_body = find_section(secs, "Source health")
        sh_header, sh_rows = parse_table(sh_body or [])
        floor_rows = []
        for i, row in enumerate(sh_rows):
            if row and re.search(r"floor|scope", row[0], re.I):
                floor_rows.append((i, row))
        if not floor_rows:
            failures.append("FLOORSRC: the `## Source health` table has no row for the coverage "
                            "floor - the floor is a scope limit and belongs next to the sources "
                            "it rests on")
        else:
            i, row = floor_rows[0]
            cell = " | ".join(row)
            low = cell.lower()
            for tok in SCOPE_TOKENS:
                if tok not in low:
                    failures.append(f"FLOORSRC: the coverage-floor row of `## Source health` "
                                    f"does not say {tok!r} (row {i + 1}: {row[0]!r})")
            if not any(tok in low for tok in SCANNER_TOKENS):
                failures.append(f"FLOORSRC: the coverage-floor row of `## Source health` does "
                                f"not name the source of the floor (row {i + 1}: {row[0]!r})")
            if not CAP_COLUMN_RE.search(cell):
                failures.append(f"FLOORSRC: the coverage-floor row of `## Source health` does "
                                f"not name the scanner COLUMN the floor is applied to (row "
                                f"{i + 1}: {row[0]!r}) - the market-cap column is what makes the "
                                "floor auditable")
            if not mentions_amount(cell, floor_usd):
                failures.append(f"FLOORSRC: the coverage-floor row of `## Source health` does "
                                f"not name the floor (${floor_usd / 1e9:.0f}B) - row {i + 1}: "
                                f"{row[0]!r}")
            if not mentions_amount(cell, band_low_v):
                failures.append(f"FLOORSRC: the coverage-floor row of `## Source health` does "
                                f"not name the band floor (${band_low_v / 1e9:.0f}B) - row "
                                f"{i + 1}: {row[0]!r}")

    return failures, notes, version, version_reason


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
    failures, notes, version, version_reason = check(path)
    print(f"CHECK: {path}")
    print(f"  rule set: {version} - {version_reason}")
    # EVERY check reports on its PASS path too: a check that only speaks on failure is not a gate.
    failed_codes = {f.split(":", 1)[0] for f in failures}
    note_map = {}
    for code, text in notes:
        note_map.setdefault(code, text)
    for code, desc in CHECK_CODES:
        if code in failed_codes:
            continue
        if code in ("COVERAGE", "ALREADY") and version == "v2":
            print(f"  note  {code} is not enforced on a v2 artifact (the rule post-dates it)")
            continue
        if code in ("TLDR", "FLOORKEY", "FLOORSRC") and version != "v4":
            print(f"  note  {code} is not enforced on a {version} artifact "
                  f"(the rule post-dates it)")
            continue
        if code in note_map:
            print(f"  note  {code}: {note_map[code]}")
            continue
        print(f"  ok    {code}: {desc}")
    if failures:
        print(f"FAIL: {len(failures)} contract violation(s) in {path}")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"OK: {path} conforms to {CONTRACT} ({version} rules applied)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
