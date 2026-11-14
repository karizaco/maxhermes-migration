#!/usr/bin/env python3
"""
check_premarket_brief.py — the contract gate for the cron #26 pre-market brief.

WHY
---
The 2026-11-03 pre-market brief was the most substantial artifact the fleet produces
(43,999 B, 1,491 CSV rows, 11 numbered sections) and it was still unusable for the
one thing a trader buys a brief for:

  * the TL;DR was a MAP of the brief (six themes) instead of a decision — no setup,
    no risk, no thing-to-watch, so the reader did the synthesis the brief exists to do;
  * the brief named setups all day (Oracle's $20B capex template, the Marvell/Lumentum
    $115B all-stock spread, "AMD is the referee tonight") and published NO level for
    any of them — a trader cannot act on a name without a price;
  * the CSV contradicted its own spec, and carried date-named columns
    (`nov_2_2026_close`, `nov_2_change_pct`) that silently went stale;
  * the pushed CSV once went out with the subject `cron daily-briefs 2026-11-03` — no
    routine number — so cron #90's triage reported a DELIVERED artifact as MISSING;
  * nothing recorded what happened to yesterday's calls, so the routine could not learn.

This script turns the spec's ARTIFACT FORMAT CONTRACT v2 into machine assertions, so a
run that breaks the contract FAILS instead of shipping. It is deliberately separate
from `check_brief_consistency.py`, which owns "the prose equals the tables equals the
CSV"; this one owns the CONTRACT (the decision, the levels, the header, the loop).

USAGE
    python3 check_premarket_brief.py --md daily-briefs/2026-11-06-pre-market.md \
                                     --csv daily-briefs/2026-11-06-pre-market.csv

EXIT CODES
    0 = contract satisfied
    1 = at least one check FAILED (every failure is printed)
    2 = bad arguments / unreadable files
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys

CONTRACT_VERSION = "premarket-brief-artifact-v2"

# --- C3: the pinned CSV header (date-independent column names, exact order) --------
CSV_COLUMNS = [
    "ticker", "name", "premarket_last", "premarket_high", "premarket_low",
    "prior_close", "gap_pct", "prior_session_change_pct", "premarket_volume",
    "avg_volume_30d", "pct_of_adv", "market_cap", "sector", "exchange",
    "liquid_screen", "quality_screen", "has_news", "key_level", "invalidation",
    "setup_theme", "setup_published",
]

# --- C2: the level columns every published name must carry ------------------------
# Each entry: (contract id, accepted normalised header patterns, human label)
LEVEL_COLUMNS = [
    ("prior_close",  (r"^priorclose$", r"^prevclose$", r"^lastclose$", r"^close$"),
     "Prior close"),
    ("premarket_last", (r"^premarketlast$", r"^premarketclose$", r"^premarketprice$",
                        r"^premarket$", r"^last$"),
     "Pre-market last"),
    ("gap_pct", (r"^gap$", r"^gappct$", r"^gappercent$", r"^premarketgap$",
                 r"^premarketpct$", r"^premarketpercent$"),
     "Gap %"),
    ("pm_range", (r"^pmrange$", r"^premarketrange$", r"^premarketlowhigh$",
                  r"^lowhigh$", r"^pmlowhigh$"),
     "PM range"),
    ("key_level", (r"^keylevel$", r"^decidelevel$", r"^level$"), "Key level"),
    ("invalidation", (r"^invalidation$", r"^invalidations$", r"^invalidate$"),
     "Invalidation"),
]
# The five the user's acceptance criteria name (the range is extra but promised).
REQUIRED_LEVELS = ("prior_close", "premarket_last", "gap_pct", "key_level",
                   "invalidation")

# --- C1: the Bottom line labels, literal and ordered --------------------------------
BOTTOM_LINE_LABELS = ("the one setup", "the one risk", "the one thing to watch")

# --- C5: the verdict vocabulary -----------------------------------------------------
THESIS_VERDICTS = ("WORKED", "HELD", "SURVIVED", "BROKE", "PARTIAL", "UNJUDGED")
NO_DATA_MARKERS = (
    "no prior brief", "not available", "no setups", "nothing to review",
    "unavailable", "no data", "could not be", "couldn't be", "no reviewed brief",
)

TICKER_RE = re.compile(r"^\*?\*?([A-Z][A-Z0-9.\-]{0,6})\*?\*?$")

# A column whose NAME carries a date goes stale the moment the next session lands:
# `nov_2_2026_close` (2026-11-03) and `nov_2_change_pct` (2026-11-04, still holding the
# Nov 3 move). Both an ISO date and a month-day token count.
DATE_COLUMN_RE = re.compile(
    r"\d{4}[-_]\d{2}[-_]\d{2}"
    r"|\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[_-]?\d{1,2}(?![0-9])"
)

# The SIDE of an invalidation. Without it the next run's review has to infer the direction
# from the gap's sign — right for one convention, silently wrong for another.
SIDE_WORD_RE = re.compile(r"\b(above|below|under|over|beneath|through)\b", re.I)

# An EVENT invalidation ("if the 16:00 ET guide is below $1.95") has no price side to
# publish — the event IS the trigger — so it is allowed to name one instead.
EVENT_RE = re.compile(r"\b(event|if)\b", re.I)

PROBLEMS: list[str] = []
CHECKS = 0


def record(name: str, problems: list[str], ok_msg: str) -> None:
    """One contract clause -> one ok/fail line."""
    global CHECKS
    CHECKS += 1
    if problems:
        for p in problems:
            PROBLEMS.append(f"[{name}] {p}")
        print(f"  FAIL {name}")
        for p in problems:
            print(f"       - {p}")
    else:
        print(f"  ok   {name}: {ok_msg}")


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def num(v):
    if v is None:
        return None
    s = str(v).strip().replace("$", "").replace(",", "").replace("%", "")
    s = s.replace("+", "").replace("x", "")
    try:
        return float(s)
    except ValueError:
        return None


def headings(lines):
    """[(index, level, text)] for every markdown heading."""
    out = []
    for i, ln in enumerate(lines):
        m = re.match(r"^(#{2,4})\s+(.*?)\s*$", ln)
        if m:
            out.append((i, len(m.group(1)), m.group(2).strip()))
    return out


def section_span(lines, key):
    """(start, end) of the FIRST section whose normalised heading starts with `key`.

    Matched BY HEADING, never by a bare substring search: a prose mention of
    "## 1. TL;DR" inside the Bottom line block would otherwise be read as the section.
    The section ends at the next heading of the SAME OR A HIGHER level — a `## 2.
    Theme clusters` section contains `### Cluster A` sub-headings, and stopping at the
    first of them would hide every table inside it.
    """
    hs = headings(lines)
    for n, (i, lvl, text) in enumerate(hs):
        if norm(text).startswith(key):
            end = len(lines)
            for (j, lvl2, _t) in hs[n + 1:]:
                if lvl2 <= lvl:
                    end = j
                    break
            return i, end
    return None


def body_of(lines, span):
    return lines[span[0] + 1:span[1]] if span else []


def strip_fences(lines):
    out, inside = [], False
    for ln in lines:
        if ln.strip().startswith("```"):
            inside = not inside
            continue
        if not inside:
            out.append(ln)
    return out


def tables(body):
    """[(header_cells, [row_cells])] for every markdown table in `body`."""
    out = []
    i = 0
    while i < len(body):
        if (body[i].strip().startswith("|") and i + 1 < len(body)
                and re.match(r"^\|[\s:|-]+\|$", body[i + 1].strip())):
            header = [c.strip() for c in body[i].strip().strip("|").split("|")]
            rows = []
            j = i + 2
            while j < len(body) and body[j].strip().startswith("|"):
                rows.append([c.strip() for c in body[j].strip().strip("|").split("|")])
                j += 1
            out.append((header, rows))
            i = j
        else:
            i += 1
    return out


def col_index(header, patterns):
    for i, h in enumerate(header):
        n = norm(h)
        for p in patterns:
            if re.match(p, n):
                return i
    return None


def ticker_of(cells):
    for c in cells[:2]:
        m = TICKER_RE.match(c.strip())
        if m:
            return m.group(1)
    return None


# ----------------------------------------------------------------------------------
# C0 — the contract marker
# ----------------------------------------------------------------------------------
def check_marker(raw):
    problems = []
    head = "\n".join(raw.split("\n")[:40])
    if CONTRACT_VERSION not in head:
        problems.append(
            f"the artifact carries no `{CONTRACT_VERSION}` marker in its first 40 lines "
            f"— it was produced from an older spec. Re-read the skill spec and rebuild it.")
    return problems


# ----------------------------------------------------------------------------------
# C1 — the Bottom line block
# ----------------------------------------------------------------------------------
def check_bottom_line(lines):
    problems = []
    span = section_span(lines, "bottomline")
    if not span:
        return ["there is NO `## Bottom line` section — the brief opens with a 44 KB map "
                "and no decision. The block belongs above `## 1. TL;DR`."]

    tl = section_span(lines, "1tldr")
    if tl and span[0] > tl[0]:
        problems.append("`## Bottom line` sits BELOW `## 1. TL;DR` — it must be above it; "
                        "the theme clustering stays below the decision.")

    body = strip_fences(body_of(lines, span))
    bullets = [ln.strip() for ln in body
               if re.match(r"^\s*(?:[-*]|\d+[.)])\s+\S", ln)]
    if len(bullets) != 3:
        problems.append(f"the Bottom line has {len(bullets)} line(s), not exactly 3 — the "
                        f"contract fixes it at three: the setup, the risk, the thing to watch")
    for n, label in enumerate(BOTTOM_LINE_LABELS):
        if n >= len(bullets):
            problems.append(f"the Bottom line has no `{label.capitalize()}` line")
            continue
        if label not in bullets[n].lower():
            problems.append(f"Bottom line line {n + 1} does not start with the label "
                            f"`{label.capitalize()}` — the labels are literal and ordered")
    if bullets:
        first = bullets[0]
        if not re.search(r"\d", first):
            problems.append("the 'one setup' line carries no number — a setup without a "
                            "level is an opinion")
        if not re.search(r"invalidat", first, re.I):
            problems.append("the 'one setup' line does not state its invalidation — "
                            "the contract requires the level AND what kills it")
        for n in (1, 2):
            if n < len(bullets) and len(bullets[n]) < 40:
                problems.append(f"Bottom line line {n + 1} is too thin to act on "
                                f"({len(bullets[n])} chars)")
    return problems


# ----------------------------------------------------------------------------------
# C2 — the levels on every published name
# ----------------------------------------------------------------------------------
def check_levels(lines, csv_rows):
    problems = []
    seen_names = 0
    for key, label in (("2themeclusters", "the theme clusters"),
                       ("3premarketgaps", "the pre-market gaps table"),
                       ("4toplosers", "the top-losers table")):
        span = section_span(lines, key)
        if not span:
            problems.append(f"missing section for {label}")
            continue
        body = strip_fences(body_of(lines, span))
        found_any = False
        for header, rows in tables(body):
            ti = col_index(header, (r"^ticker$", r"^symbol$", r"^name$"))
            if ti is None:
                continue  # a context table (no ticker column) — not a name table
            found_any = True
            missing_cols = []
            for cid, patterns, human in LEVEL_COLUMNS:
                if col_index(header, patterns) is None:
                    missing_cols.append(human)
            if missing_cols:
                problems.append(f"{label}: the table is missing the level column(s) "
                                f"{missing_cols} — every published name carries "
                                f"prior close, pre-market last, gap %, PM range, key level "
                                f"and invalidation")
                continue
            idx = {cid: col_index(header, pats) for cid, pats, _h in LEVEL_COLUMNS}
            for r in rows:
                t = ticker_of(r)
                if not t:
                    continue
                seen_names += 1
                for cid in REQUIRED_LEVELS:
                    i = idx[cid]
                    val = r[i].strip() if i < len(r) else ""
                    if not val:
                        problems.append(f"{label}: {t} has an EMPTY `{cid}` cell")
                    elif cid == "invalidation" and not re.search(r"\d", val):
                        problems.append(f"{label}: {t} has a non-numeric invalidation "
                                        f"({val!r}) — it must name a level or a timed event")
                # the numbers must be the CSV's numbers
                ref = csv_rows.get(t)
                if not ref:
                    problems.append(f"{label}: {t} is published but is NOT in the CSV — "
                                    f"a published name must exist in the companion file")
                    continue
                for cid, keyc in (("prior_close", "prior_close"),
                                  ("premarket_last", "premarket_last"),
                                  ("gap_pct", "gap_pct")):
                    mv = num(r[idx[cid]]) if idx[cid] < len(r) else None
                    cv = ref.get(keyc)
                    if mv is None or cv is None:
                        continue
                    if cid == "gap_pct":
                        if abs(cv - mv) > 0.15:
                            problems.append(f"{label}: {t} gap {mv:+.2f}% in the table vs "
                                            f"{cv:+.4f}% in the CSV")
                    elif abs(cv - mv) > max(0.011, abs(cv) * 0.001):
                        problems.append(f"{label}: {t} {cid} {mv} in the table vs {cv} in the CSV")
        if not found_any:
            problems.append(f"{label}: no table with a ticker column was found — the "
                            f"section must publish names with their levels")
    if not problems and seen_names == 0:
        problems.append("no published name carries the level columns")
    return problems, seen_names


# ----------------------------------------------------------------------------------
# C3 — the CSV header
# ----------------------------------------------------------------------------------
def check_csv_header(cols):
    problems = []
    missing = [c for c in CSV_COLUMNS if c not in cols]
    extra = [c for c in cols if c not in CSV_COLUMNS]
    if missing:
        problems.append(f"the CSV header is missing {missing}")
    if extra:
        problems.append(f"the CSV header carries unpromised columns {extra}")
    dated = [c for c in cols if DATE_COLUMN_RE.search(c)]
    if dated:
        problems.append(f"the CSV header carries DATE-NAMED column(s) {dated} — a date-named "
                        f"column silently goes stale on the next session (the 2026-11-03 CSV "
                        f"shipped `nov_2_2026_close`, and the 2026-11-04 CSV carried "
                        f"`nov_2_change_pct` while it actually held the Nov 3 move)")
    return problems


def check_csv_rows(rows):
    problems = []
    for n, r in enumerate(rows, 1):
        t = (r.get("ticker") or "").strip()
        if not t:
            problems.append(f"CSV row {n} has no ticker")
            continue
        if (r.get("setup_published") or "").strip().lower() == "yes":
            for c in ("key_level", "invalidation"):
                if not (r.get(c) or "").strip():
                    problems.append(f"CSV row {n} ({t}) is published as a setup but its "
                                    f"`{c}` is empty — the next run's review tests that level")
            inv = (r.get("invalidation") or "").strip()
            if inv and not (SIDE_WORD_RE.search(inv) or EVENT_RE.search(inv)):
                problems.append(f"CSV row {n} ({t}) has an invalidation with no SIDE "
                                f"({inv!r}) — it must read `above 478.69` / `below 11.87`, "
                                f"not a bare number: the next run's review is a mechanical test "
                                f"on that cell and a bare number leaves the direction to be "
                                f"inferred")
            if inv and not re.search(r"\d", inv):
                problems.append(f"CSV row {n} ({t}) has an invalidation with no level: {inv!r}")
        for c in ("prior_close", "premarket_last"):
            if not (r.get(c) or "").strip():
                problems.append(f"CSV row {n} ({t}) has an empty `{c}`")
        hn = (r.get("has_news") or "").strip().lower()
        if hn not in ("yes", "no", ""):
            problems.append(f"CSV row {n} ({t}) has has_news={hn!r} — the vocabulary is "
                            f"yes/no")
    return problems


# ----------------------------------------------------------------------------------
# C5 — the yesterday loop
# ----------------------------------------------------------------------------------
def check_yesterday(lines):
    problems = []
    span = section_span(lines, "yesterdaysbrief")
    if not span:
        return ["there is NO `## Yesterday's brief — what happened` section — nothing "
                "records what happened to yesterday's calls, so the routine cannot learn. "
                "The section ships on every run."]
    body = strip_fences(body_of(lines, span))
    tbls = tables(body)
    if not tbls:
        text = "\n".join(body)
        if not any(m in text.lower() for m in NO_DATA_MARKERS):
            problems.append("the 'Yesterday's brief' section has no table AND no stated "
                            "reason — a section that silently disappears is how a loop dies")
        return problems
    header, rows = tbls[0]
    if col_index(header, (r"^thesisheld", r"^thesis", r"^theldf", r"^verdict",
                          r"^thesisdiditwork")) is None:
        problems.append("the 'Yesterday's brief' table has no `Thesis held?` column — "
                        "the verdict is the whole point of the section")
    for r in rows:
        if not any(c.strip() for c in r):
            continue
        verdict = ""
        for c in reversed(r):
            if c.strip():
                verdict = c.strip()
                break
        if not any(verdict.upper().startswith(v) for v in THESIS_VERDICTS):
            problems.append(f"a row's verdict {verdict!r} is not one of "
                            f"{', '.join(THESIS_VERDICTS)}")
    return problems


# ----------------------------------------------------------------------------------
# --- C6: the screen's completeness is a PUBLISHED field ---------------------------
# The ±3% band is pulled with a row cap. On 2026-11-05 the cap (400) was smaller than the
# band (547 decliners), so `down_3pct` was a FLOOR and read as a count. The routine must
# assert `len(rows) == totalCount` at pull time and publish the outcome; when the assert
# failed the artifact must SAY the counts are floors.
FRONT_MATTER_FIELDS = ("up_3pct", "down_3pct", "screen_complete", "tail_rows")


def front_matter(raw):
    """The machine-readable block, as a dict.

    It is a `---` fenced block. It is NOT always the first thing in the file - a
    title may precede it - so find the FIRST fence rather than assuming offset 0.
    """
    lines = raw.split("\n")
    start = None
    for i, ln in enumerate(lines):
        if ln.strip() == "---":
            start = i
            break
    if start is None:
        return {}
    out = {}
    for line in lines[start + 1:]:
        if line.strip() == "---":
            break
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        out[k.strip()] = v.split("#", 1)[0].strip()
    return out


# --- C7: the tail tier (added 2026-11-14) ---------------------------------------
# The measurement behind it (seven sessions, 2026-11-02..2026-11-10, 175 top
# regular-session gainers): 58 of them (33%) FAILED at least one gate, and the
# gate-failing movers' median session move was +26.75% against the gate-passing
# names' +26.05%. The gates were not excluding junk - they were excluding a third
# of the day's best movers. The tail tier publishes them.
TAIL_MARKER = "premarket-brief-tail-v1"
TAIL_COHORTS = ("gate-fail", "flat-print", "unranked")
COHORT_COLS = (r"^cohort$", r"^tailcohort$", r"^group$", r"^cohortlabel$")


def check_tail_tier(lines, csv_rows, raw):
    """C7 - the tail tier: the names the gates and the top-25 cap left out.

    Ranked by |gap|, NOT by gap: a name that gapped DOWN and then ran (GOGO on
    2026-11-06 was -1.10% pre-market and closed +71.52%) is filed under "losers"
    by a gap-sorted table, which misfiles the day's single biggest winner.
    """
    problems = []
    fm = front_matter(raw)
    if fm.get("tail_tier") != TAIL_MARKER:
        problems.append(
            "the front matter does not carry `tail_tier: %s` - the tail tier is part of "
            "the contract, and the marker is how a reader knows it was published" % TAIL_MARKER)

    span = section_span(lines, "tail")
    if not span:
        problems.append(
            "there is NO tail section - a third of the day's movers failed a gate and "
            "moved just as far as the ones that passed (+26.75% vs +26.05% median over "
            "seven sessions), and the tail tier is where they are published")
        return problems
    body = strip_fences(body_of(lines, span))
    tbls = tables(body)
    if not tbls:
        problems.append("the tail section has no table - a heading with no names is a "
                        "section that silently disappears")
        return problems
    header, rows = tbls[0]
    if col_index(header, (r"^ticker$", r"^symbol$", r"^name$")) is None:
        problems.append("the tail table has no ticker column")
        return problems
    missing = [human for _cid, pats, human in LEVEL_COLUMNS
               if col_index(header, pats) is None]
    if missing:
        problems.append("the tail table is missing the level column(s) %s - a published name "
                        "carries its levels or it is not a name" % missing)
        return problems
    coh = col_index(header, COHORT_COLS)
    if coh is None:
        problems.append("the tail table has no 'Cohort' column - every tail row says which "
                        "cohort it is (%s)" % ", ".join(TAIL_COHORTS))
        return problems

    idx = {cid: col_index(header, pats) for cid, pats, _h in LEVEL_COLUMNS}
    gaps = []
    for r in rows:
        t = ticker_of(r)
        if not t:
            continue
        label = (r[coh] if coh < len(r) else "").strip().lower()
        if label not in TAIL_COHORTS:
            problems.append("the tail row for %s carries the cohort '%s', which is not one "
                            "of %s" % (t, label, ", ".join(TAIL_COHORTS)))
        ref = csv_rows.get(t)
        if not ref:
            problems.append("the tail row for %s is not in the companion CSV - a published "
                            "name must exist in the artifact" % t)
            continue
        for cid in ("prior_close", "premarket_last", "gap_pct"):
            i = idx[cid]
            mv = num(r[i]) if i < len(r) else None
            cv = ref.get(cid)
            if mv is None or cv is None:
                continue
            if cid == "gap_pct":
                if abs(cv - mv) > 0.15:
                    problems.append("the tail row for %s reads %+.2f%% against the CSV's "
                                    "%+.4f%%" % (t, mv, cv))
                gaps.append((t, abs(mv)))
            elif abs(cv - mv) > max(0.011, abs(cv) * 0.001):
                problems.append("the tail row for %s has %s %s against the CSV's %s"
                                % (t, cid, mv, cv))
    for (t1, g1), (t2, g2) in zip(gaps, gaps[1:]):
        if g2 > g1 + 0.01:
            problems.append(
                "the tail table is not ordered by |gap| descending: %s (%.2f) comes before "
                "%s (%.2f) - a gap-sorted table files a name that gapped DOWN and then ran "
                "under 'losers'" % (t1, g1, t2, g2))
            break

    tl = section_span(lines, "1tldr")
    tlb = strip_fences(body_of(lines, tl)) if tl else []
    if not any("post-open" in ln.lower() for ln in tlb):
        problems.append(
            "the TL;DR does not state the post-open limit - 71% of every session's 20%+ "
            "moves happen after 09:30, and a brief that does not say so reads as a promise "
            "it cannot keep")
    return problems


def check_screen_complete(raw):
    problems = []
    fm = front_matter(raw)
    for field in FRONT_MATTER_FIELDS:
        if field not in fm:
            problems.append(f"the front matter has no '{field}' - the screen's "
                            f"completeness must be a published field")
    for name in ("up_3pct", "down_3pct"):
        val = fm.get(name)
        if val is not None and not re.fullmatch(r"\d+", val):
            problems.append(f"front matter '{name}' is '{val}', not a whole number")
    sc = fm.get("screen_complete")
    if sc is not None and sc not in ("true", "false"):
        problems.append(f"front matter 'screen_complete' is '{sc}', not true|false")
    if sc == "false" and "floor" not in raw.lower():
        problems.append("front matter says screen_complete: false but the artifact never "
                        "says the counts are floors - a truncated screen must say so")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", required=True)
    ap.add_argument("--csv", required=True)
    args = ap.parse_args()

    for p in (args.md, args.csv):
        if not os.path.exists(p):
            print(f"FAIL missing file: {p}")
            return 2

    raw = open(args.md, encoding="utf-8", errors="replace").read()
    lines = raw.split("\n")

    with open(args.csv, newline="", encoding="utf-8") as fh:
        rdr = csv.DictReader(fh)
        cols = rdr.fieldnames or []
        rows = list(rdr)

    csv_rows = {}
    for r in rows:
        t = (r.get("ticker") or "").strip()
        if not t:
            continue
        csv_rows[t] = {
            "prior_close": num(r.get("prior_close")),
            "premarket_last": num(r.get("premarket_last")),
            "gap_pct": num(r.get("gap_pct")),
        }

    print(f"check-premarket-brief: {args.md}")
    print(f"  csv columns: {len(cols)} | csv rows: {len(rows)}")

    record("C0_MARKER", check_marker(raw), f"the artifact carries {CONTRACT_VERSION}")
    record("C1_BOTTOM_LINE", check_bottom_line(lines),
           "3 lines, the three labels, above the theme TL;DR")

    lvl_problems, seen = check_levels(lines, csv_rows)
    record("C2_LEVELS", lvl_problems,
           f"{seen} published names carry prior close, pre-market last, gap %, PM range, "
           f"key level and invalidation")

    record("C3_CSV_HEADER", check_csv_header(cols),
           f"the header is the pinned {len(CSV_COLUMNS)} date-independent columns")
    record("C3_CSV_ROWS", check_csv_rows(rows),
           "every row carries its prices and every published setup carries its levels")

    record("C5_YESTERDAY", check_yesterday(lines),
           "the section exists and every row's verdict is in the vocabulary")

    record("C6_SCREEN_COMPLETE", check_screen_complete(raw),
           "the front matter publishes the ±3% counts and whether they are exact")

    record("C7_TAIL_TIER", check_tail_tier(lines, csv_rows, raw),
           "the tail tier is published, carries levels and a cohort, and is ranked by |gap|")

    print()
    if PROBLEMS:
        print(f"CONTRACT FAILED — {len(PROBLEMS)} problem(s) in {CHECKS} checks:")
        for p in PROBLEMS:
            print(f"  - {p}")
        return 1
    print(f"CONTRACT OK — {CHECKS} checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
