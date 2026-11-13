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

It also checks what the brief CLAIMS about the screen, which is a different thing from what it
publishes. Two claims in the published 2026-11-09 brief named no ticker and so passed every
per-ticker check above:

  * "every one of the 35 ... names is at or above +3.00%" - UEC printed +2.60%
  * "the liquid expression moves a uniform +3.0% to +4.7%: GFR +38.39%, ..." - the name is
    nowhere near the band it is listed inside

A universal claim is resolved against the screen (a `sector` value, or a count that identifies
one set of rows) and checked against it. A claim whose set cannot be resolved is printed as a
`note:` rather than believed.

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
# it is omitted when no watchlist is published — so it is not required here. The two
# unnumbered blocks (`## Bottom line`, `## Yesterday's brief — what happened`) are
# optional here and owned by check_premarket_brief.py.
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


def section_positions(md: str):
    """{section title -> (start, end)} for every `##` heading.

    Heading-ANCHORED, not a bare `md.find()`: the brief's new `## Bottom line` block
    talks about `## 1. TL;DR`, and a substring search would read that mention as the
    section and reorder everything after it.
    """
    lines = md.split("\n")
    heads = []
    for i, ln in enumerate(lines):
        m = re.match(r"^##\s+(.*?)\s*$", ln)
        if m:
            heads.append((i, m.group(1).strip()))
    out = {}
    for n, (i, title) in enumerate(heads):
        end = heads[n + 1][0] if n + 1 < len(heads) else len(lines)
        out[title] = (i, end)
    return out


def find_section(secs, needle: str):
    """The first section whose heading starts with `needle` (case-insensitive)."""
    key = needle.lower().lstrip("#").strip()
    for title, span in secs.items():
        if title.lower().lstrip("#").strip().startswith(key):
            return span
    return None


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

    The column names are read with FALLBACKS, so the linter works on a v2 CSV
    (`gap_pct` / `premarket_last` / `prior_session_change_pct`) and on a legacy one
    (`premarket_change_pct` / `premarket_close` / `nov_2_change_pct`) alike. The legacy
    date-named column is exactly why v2 renamed them: `nov_2_change_pct` sat in the
    2026-11-04 CSV holding the *Nov 3* move, so a date-pinned reader silently compares
    the wrong session.

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

            def _f(*keys):
                for k in keys:
                    try:
                        v = float(row.get(k) or "")
                        return v
                    except ValueError:
                        continue
                return None

            out[t] = {"pct": _f("gap_pct", "premarket_change_pct"),
                      "session_pct": _f("prior_session_change_pct", "prev_change_pct",
                                        "nov_2_change_pct"),
                      "px": _f("premarket_last", "premarket_close"),
                      "sector": (row.get("sector") or "").strip(),
                      "raw": row}
    return out


BAND_RE = re.compile(
    r"([+-]?\d+(?:\.\d+)?)\s*%\s*(?:to|through|–|—)\s*([+-]?\d+(?:\.\d+)?)\s*%")
PAIR_RE = re.compile(r"\b([A-Z][A-Z0-9.\-]{0,6})\s+([+-]?\d+(?:\.\d+)?)\s*%")
UNIVERSAL_RE = re.compile(
    r"\b(every one|every name|every single|each name|all (?:of )?the \d+"
    r"|all \d+|all of them|all|not one|none)\b", re.I)
THRESHOLD_RE = re.compile(
    r"(?:at or above|at least|no less than|≥|>=|>)\s*([+-]?\d+(?:\.\d+)?)\s*%", re.I)
COUNT_RE = re.compile(r"\b(\d+)\s+(?:[\w\-]+\s+){0,4}?names?\b", re.I)
UP_OR_DOWN_RE = re.compile(
    r"\b(not one is down|none (?:is )?down|all (?:are |were )?up|every one.*up)\b", re.I)


def sentences(text: str) -> list:
    """One sentence per item, so a claim and the set it names stay together."""
    out = []
    for line in text.splitlines():
        for s in re.split(r"(?<=[.!?])\s+", line):
            s = s.strip()
            if s:
                out.append(s)
    return out


GATE_WORDS = ("liquid", "quality")
GATE_COMBOS = ((), ("liquid",), ("quality",), GATE_WORDS)
REPORTING_RE = re.compile(
    r"\b(said|says|wrote|written|claimed|claims|published|states|stated|quoted|"
    r"quotes|reads|earlier|previously|used to|no longer|corrected|amended|"
    r"amendment|correction|did not survive|instead of)\b", re.I)


def _passes(r, col):
    """Whether a screen's gate flag says this row passed."""
    return str(r["raw"].get(col, "")).strip().lower() in ("pass", "yes", "true")


def resolve_set(sent: str, rows: dict, sentence_lower: str, want_count=None):
    """The CSV rows a claim is about, or None when the claim names no set.

    A claim about "35 names on the screen" is checkable when the count
    identifies a set: the screen's own sector and gate columns produce exactly
    one set of that size often enough, and a claim that fits one set is a
    claim about it. A sector named in the sentence settles it outright. The
    gate words in the claim narrow it the way the screen's flags do; with no
    gate word, the count decides which combination it meant.
    """
    sectors = sorted({r["sector"] for r in rows.values() if r["sector"]})
    sector = None
    for s in sectors:                      # longest first, so "Non-Energy
        if s.lower() in sentence_lower:    # Minerals" beats "Energy Minerals"
            if sector is None or len(s) > len(sector):
                sector = s

    def _apply(base, gates):
        picked = dict(base)
        for g in gates:
            cols = [c for c in list(picked.values())[0]["raw"]
                    if c.startswith(g)] if picked else []
            if cols:
                picked = {t: r for t, r in picked.items() if _passes(r, cols[0])}
        return picked

    stated = [g for g in GATE_WORDS if g in sentence_lower]
    if sector:
        base = {t: r for t, r in rows.items() if r["sector"] == sector}
        if stated:
            return _apply(base, stated), sectors, "%s, %s" % (sector, " + ".join(stated))
        if want_count is not None:
            for gates in GATE_COMBOS:
                picked = _apply(base, gates)
                if len(picked) == want_count:
                    return picked, sectors, "%s, %s" % (
                        sector, " + ".join(gates) if gates else "no gate")
            return None, sectors, None
        return base, sectors, sector

    # No sector named. The count may still identify one set in the screen.
    if want_count is not None:
        matches = []
        for s in sectors:
            base = {t: r for t, r in rows.items() if r["sector"] == s}
            for gates in GATE_COMBOS:
                picked = _apply(base, gates)
                if len(picked) == want_count:
                    matches.append((picked, "%s, %s" % (
                        s, " + ".join(gates) if gates else "no gate")))
        if len(matches) == 1:
            return matches[0][0], sectors, matches[0][1]
    return None, sectors, None


def check_claims(md: str, rows: dict) -> tuple:
    """Prose claims about the screen's names, against the screen itself.

    Two shapes misled a reader on 2026-11-09 and both passed the per-ticker
    checks above, because neither names a ticker in the claim:

      * "every one of the 35 ... names is at or above +3.00%" - one of them
        printed +2.60%. A universal numeric claim is either checkable against
        the screen or it must not be made.
      * "the liquid expression moves a uniform +3.0% to +4.7%: GFR +38.39%, ..."
        - the name is listed INSIDE a band it is nowhere near.

    Returns (problems, notes). A note is printed and is not a breach: a claim
    whose set cannot be resolved is surfaced, not silently believed.
    """
    problems, notes = [], []
    band_checked = claim_checked = 0

    for sent in sentences(md):
        # --- a name listed inside a stated band must be inside that band ---
        bm = BAND_RE.search(sent)
        if bm:
            lo, hi = float(bm.group(1)), float(bm.group(2))
            if lo > hi:
                lo, hi = hi, lo
            for t, p in PAIR_RE.findall(sent[bm.end():]):
                pct = float(p)
                band_checked += 1
                if pct < lo - 0.05 or pct > hi + 0.05:
                    problems.append(
                        f"band claim: {t} {pct:+.2f}% is listed inside the stated "
                        f"{lo:+.2f}% to {hi:+.2f}% band")

        # --- a universal claim about the screen's names ---
        um = UNIVERSAL_RE.search(sent)
        if not um or not re.search(r"\bnames?\b", sent, re.I):
            continue
        if REPORTING_RE.search(sent):
            # A correction note that QUOTES an earlier claim is reporting, not
            # claiming. "§1 still said every one of the 35 ... was at or above
            # +3.00%" is true about the old text and false about the screen.
            continue
        thr = THRESHOLD_RE.search(sent)
        updown = UP_OR_DOWN_RE.search(sent)
        if not thr and not updown:
            continue
        low = sent.lower()
        cm = COUNT_RE.search(sent)
        want = int(cm.group(1)) if cm else None
        picked, sectors, gates = resolve_set(sent, rows, low, want_count=want)
        claim_checked += 1
        if picked is None:
            # The claim names a set the screen's own columns cannot resolve -
            # "Metals" is not a sector value, so no row can be checked against
            # it. That is not a breach (the claim may well be true), but it is
            # exactly how a false number got through: a universal claim that
            # nothing can check. It is surfaced, with the fix.
            why = ("a universal claim about the screen's names must name its set "
                   "by a sector value of the screen (%s)" % ", ".join(sectors[:6]))
            if want is not None:
                why += (" - no gate combination of those rows produces the %d names "
                        "the claim states" % want)
            notes.append(f"unverifiable claim (not a breach): {sent[:70]}... - {why}")
            continue
        pcts = [r["pct"] for r in picked.values() if r["pct"] is not None]
        where = "%d row(s) of the screen, %s" % (len(picked), gates)
        if not pcts:
            continue
        if thr:
            floor = float(thr.group(1))
            if min(pcts) < floor - 0.05:
                problems.append(
                    f"claim says every one is at or above {floor:+.2f}%; "
                    f"{where} the lowest is {min(pcts):+.2f}%")
        if updown and min(pcts) <= 0:
            problems.append(
                f"claim says every one is up and none is down; {where} "
                f"the lowest is {min(pcts):+.2f}%")
        if cm and int(cm.group(1)) != len(picked):
            notes.append(
                f"claim says {cm.group(1)} names; {where} match the set as stated "
                f"({min(pcts):+.2f}% to {max(pcts):+.2f}%)")
    return problems, notes, band_checked, claim_checked


def main() -> int:
    # A message can carry `≥` or an em-dash. On a Windows console that is
    # cp1252 and the print would raise, which hides the finding the checker
    # exists to report.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

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
    secs = section_positions(md)
    pos = -1
    for sec in SECTIONS:
        span = find_section(secs, sec)
        if span is None:
            problems.append(f"missing section: {sec}")
        elif span[0] < pos:
            problems.append(f"section out of order: {sec}")
        else:
            pos = span[0]

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

    # --- 4. every ticker-% in the prose must agree with the CSV ---
    # THREE prose forms carry a ticker and a percentage, and ALL THREE must be
    # checked. Before 2026-11-13 only the first was recognised, so an artifact
    # written as "NVDA **-8.42%**" reported `prose ticks checked: 0` and every prose
    # figure went unverified — the 2026-11-12 brief shipped a stale MSTR number for
    # exactly this reason, and the linter had passed it.
    PROSE_TICK_PATTERNS = (
        r"\*\*([A-Z][A-Z0-9.\-]{0,6})\s+([+-][0-9.]+)%\*\*",           # **NVDA -8.42%**
        r"(?<![\*\w])([A-Z][A-Z0-9.\-]{0,6})\s+\*\*([+-][0-9.]+)%\*\*",  # NVDA **-8.42%**
    )
    prose_checked = 0
    prose_seen = set()
    for _pat in PROSE_TICK_PATTERNS:
        for m in re.finditer(_pat, md):
            t, pct = m.group(1), round(float(m.group(2)), 1)
            key = (t, pct, m.start())
            if key in prose_seen:
                continue
            prose_seen.add(key)
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

    # --- 6. prose claims about the screen's names, against the screen ---
    claim_problems, notes, band_checked, claim_checked = check_claims(md, rows)
    problems.extend(claim_problems)

    print(f"check-brief-consistency: {args.md}")
    print(f"  table rows checked : {table_checked}")
    print(f"  prose ticks checked: {prose_checked}")
    if prose_checked == 0:
        notes.append("NO PROSE FIGURES WERE MACHINE-CHECKED — this artifact carries bolded "
                     "percentages but none of them carry a ticker the linter can resolve. "
                     "Write a prose figure as **TICKER -8.42%** (the ticker INSIDE the bold) "
                     "so it can be verified against the CSV.")
    print(f"  band names checked : {band_checked}")
    print(f"  set claims checked : {claim_checked}")
    print(f"  CSV names          : {len(rows)}")
    for n in notes:
        print(f"  note: {n}")
    if problems:
        print(f"  RESULT: INCONSISTENT ({len(problems)} problem(s))")
        for p in problems:
            print(f"    - {p}")
        return 1
    print("  RESULT: consistent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
