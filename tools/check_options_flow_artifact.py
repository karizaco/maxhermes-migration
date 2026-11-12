#!/usr/bin/env python3
"""
check_options_flow_artifact.py — assert the cron #16 artifact contract. Do not eyeball it.

Three defects motivated this checker (all found 2026-11-06):

  1. The 2026-11-02 artifact published `bias: PUT` on a put/call ratio of 0.84, which the fixed
     thresholds (< 0.85 -> CALL) make a CALL. The numbers were right, the tag was reversed, and
     anyone charting the put/call series across days read a false flip.
  2. The routine publishes three books over three different populations (the relative screen's
     ~60 names, the series book's 8 mega-caps, the published watchlist) and a ratio without its
     population is not interpretable.
  3. The spec's claim about the relative screen (headline) and the artifact's own section title
     (supplementary) contradicted each other.

USAGE
    python3 check_options_flow_artifact.py --md options-flow/<date>.md [--reply <reply.txt>]
    python3 check_options_flow_artifact.py --dir options-flow

Exit codes: 0 = contract satisfied; 1 = at least one FAIL (each is printed).

WHAT IT ASSERTS
    A. Every published bias tag equals the tag derived from its own ratio (the 2026-11-02 class).
    B. The audit line's tag equals the front matter's tag.
    C. A rev-2 artifact (relative_screen_universe present) names the universe of EVERY published
       ratio: relative screen, series book, wide book, Pass A.
    D. A rev-2 artifact leads with the relative screen — its section comes before the series book.
    E. With --reply: the reply's first line names the universe behind any ratio it quotes.
    F. THE COLUMN CONTRACT (2026-11-12): the expiry date gets its OWN column. A contract table
       must have an `Expiry` column, no cell may pack side + strike + date, and a contract
       artifact must declare `column_contract: expiry-column-v1` in its front matter.
"""

import argparse
import os
import re
import sys

BIAS_CALL_BELOW, BIAS_PUT_ABOVE = 0.85, 1.20
TAGS = ("CALL", "PUT", "MIXED")

# The contract date. Artifacts published before it are checked for the things that were ALWAYS
# true (a headline tag must not contradict its own ratio; the audit line must match the front
# matter) but not for the things the contract introduced (a universe line in the front matter,
# per-slice tags). Rewriting the October files is not this checker's job, and the October files
# used a legacy convention: every slice row carried the OVERALL tag, not its own.
CONTRACT_DATE = "2026-11-06"

# The COLUMN CONTRACT date. From this date the artifact declares the column contract in its front
# matter and every contract table gives the expiry date its own column. Artifacts published
# before it are reported, not enforced — the 2026-11-11 contrast table packs side + strike + date
# and stays on the record as it was published.
COLUMN_CONTRACT_DATE = "2026-11-12"
COLUMN_CONTRACT_ID = "expiry-column-v1"

# A cell that packs the side, the strike and the date into one string. Two shapes are caught:
# the middot form used in chat replies ("C 16.5 · 11-20") and the space form used in the old
# contrast table ("NVDA P 175 2026-11-11"). A table cell only — prose may name a contract inline.
PACKED_CONTRACT = re.compile(
    r"\b[CP]\s+\d+(?:\.\d+)?\s*(?:[·•]|\|)\s*\d{2}-\d{2}"
    r"|\b[CP]\s+\d+(?:\.\d+)?\s+\d{4}-\d{2}-\d{2}"
)

# front-matter keys that carry a (tag, ratio) pair
FM_TAG_KEYS = ("bias", "series_book_bias", "series_book_economic_bias",
               "wide_book_bias", "wide_book_econ_bias", "wide_book_economic_bias",
               "pass_a_bias", "pass_a_economic_bias")

# front-matter keys that must exist on a rev-2 artifact (universe-labelled front matter)
FM_UNIVERSE_KEYS = ("relative_screen_universe", "series_book_universe",
                    "wide_book_universe", "pass_a_universe")

# a ratio-bearing front-matter line must point at a universe
FM_RATIO_KEYS = ("bias", "series_book_bias", "series_book_economic_bias",
                 "series_book_premium_ratio", "wide_book_bias", "wide_book_econ_bias",
                 "wide_book_economic_bias", "pass_a_bias", "pass_a_economic_bias",
                 "pass_a_premium_ratio")

UNIVERSE_MARKERS = ("universe", "pass-b", "pass b", "mega-cap", "megacap",
                     "watchlist", "relative screen", "relative-screen", "top-60", "top 60",
                     "8 names", "60 names")


def tag_from_ratio(ratio):
    if ratio is None:
        return "MIXED"
    if ratio < BIAS_CALL_BELOW:
        return "CALL"
    if ratio > BIAS_PUT_ABOVE:
        return "PUT"
    return "MIXED"


def ok(msg):
    print(f"  ok    {msg}")


def bad(msg):
    print(f"  FAIL  {msg}")
    return 1


def note(msg):
    """A pre-contract observation: reported, never a failure."""
    print(f"  note  {msg}")
    return 0


def front_matter(text):
    """The first ``` fenced block, as an ordered list of (key, value)."""
    m = re.search(r"```[a-zA-Z]*\n(.*?)```", text, re.S)
    if not m:
        return []
    out = []
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        out.append((k.strip(), v.strip()))
    return out


def fm_get(fm, key):
    for k, v in fm:
        if k == key:
            return v
    return None


def ratio_tag_pairs(text):
    """Every (tag, ratio) pair the artifact publishes.

    Only the shapes a tag is actually PUBLISHED in are matched — a loose "put/call ... CALL"
    scan also matches the THRESHOLD line ("put/call < 0.85 -> CALL") and a date
    ("put/call series since 2026-10-16"), which is how a checker starts crying wolf.
      1. "Bias tag: PUT (put/call 1.33)"
      2. "series_book_bias: PUT (put/call 1.33)"
      3. a table row whose last cell is the bolded tag and whose 3rd-from-last cell is a number
    """
    pairs = []
    pats = [
        r"Bias tag:\s*\**\s*(CALL|PUT|MIXED)\s*\**\s*\(?\s*(?:put\s*/\s*call|P/C)\s*(\d+(?:\.\d+)?)",
        r"^[a-z_]+:\s*\**\s*(CALL|PUT|MIXED)\s*\**\s*\(?\s*(?:put\s*/\s*call|P/C)"
        r"(?:\s+(?:volume|contract|contract\s+ratio|ratio))*\s*(\d+(?:\.\d+)?)",
        # "Headline read: PUT ... the put/call contract ratio is 0.84"
        r"(?:Headline read|read|bias):\s*\**\s*(CALL|PUT|MIXED)\s*\**[^.\n]{0,140}?"
        r"put\s*/\s*call[^.\n]{0,40}?(\d+(?:\.\d+)?)",
        # "the put/call ratio would read 2.69 — a CALL tag instead of PUT"
        r"put\s*/\s*call[^.\n]{0,40}?(\d+(?:\.\d+)?)[^.\n]{0,40}?\b(CALL|PUT|MIXED)\b\s+tag",
    ]
    for pat in pats:
        for m in re.finditer(pat, text, re.I | re.M):
            if m.re.groups == 2:
                pairs.append((m.group(1).upper(), float(m.group(2)), m.group(0)[:90]))
            else:
                pairs.append((m.group(2).upper(), float(m.group(1)), m.group(0)[:90]))
    for m in re.finditer(r"\|\s*(\d+(?:\.\d+)?)\s*\|\s*\*\*(CALL|PUT|MIXED)\*\*\s*\|", text):
        pairs.append((m.group(2).upper(), float(m.group(1)), m.group(0)[:90]))
    return pairs



def artifact_date(text, path):
    """The artifact's session date: the front matter's `date:` key, else the filename."""
    d = fm_get(front_matter(text), "date")
    if d and re.match(r"\d{4}-\d{2}-\d{2}", d):
        return d[:10]
    m = re.search(r"(\d{4}-\d{2}-\d{2})", os.path.basename(path))
    return m.group(1) if m else ""


def declares_thresholds(text):
    """Does the artifact state the thresholds? Only then is every slice row's tag required to
    agree with its own ratio."""
    return bool(re.search(r"bias_tag_thresholds|Bias tag rule|bias thresholds", text, re.I))


# A cell that is exactly side + strike ("C 16.5"). The DATE is what the user asked to have in its
# own column; side + strike in one cell is a presentation choice, so this is the shape that makes
# a table a CONTRACT table when it carries no separate Side column.
CONTRACT_CELL = re.compile(r"^\s*[CP]\s+\d+(?:\.\d+)?\s*$")


def split_row(line):
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


def md_tables(text):
    """Every markdown table in the text: (section_title, header_cells, [row_cells, ...])."""
    out = []
    section = ""
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("#"):
            section = ln.lstrip("# ").strip()
        if (ln.strip().startswith("|") and i + 1 < len(lines)
                and re.match(r"^\s*\|[\s:|-]+\|\s*$", lines[i + 1])):
            header = split_row(ln)
            rows = []
            j = i + 2
            while j < len(lines) and lines[j].strip().startswith("|"):
                rows.append(split_row(lines[j]))
                j += 1
            out.append((section, header, rows))
            i = j
            continue
        i += 1
    return out


def check_column_contract(text, strict, label):
    """F. The expiry date gets its OWN column.

    A contract table must carry an `Expiry` column, no cell may pack side + strike + date, and
    every row must have the same number of cells as its header (a packed cell is the usual way a
    table silently loses its shape).
    """
    fails = 0
    for section, header, rows in md_tables(text):
        hdr = [h.lower() for h in header]
        flat = [c for r in rows for c in r]
        packed = [c for c in flat if PACKED_CONTRACT.search(c)]
        contract_cells = [c for c in flat if CONTRACT_CELL.match(c)]
        is_contract = ("side" in hdr) or bool(contract_cells)
        is_contrast = section.lower().startswith("contrast")

        if (is_contract or is_contrast) and "expiry" not in hdr:
            msg = (f"{label}: the contract table in section {section!r} has no 'Expiry' column "
                   f"(header: {header}) — the expiry date must have its own column")
            fails += bad(msg) if strict else note(msg + " (pre-column-contract artifact)")
        elif is_contract or is_contrast:
            ok(f"{label}: {section!r} carries its own Expiry column")

        for c in packed:
            msg = (f"{label}: a cell packs side + strike + date: {c!r} — the expiry date must "
                   f"have its own column")
            fails += bad(msg) if strict else note(msg + " (pre-column-contract artifact)")

        for r in rows:
            if len(r) != len(header):
                msg = (f"{label}: a row in section {section!r} has {len(r)} cells but the header "
                       f"has {len(header)}: {r}")
                fails += bad(msg) if strict else note(msg + " (pre-column-contract artifact)")
    return fails


def check_md(path):
    fails = 0
    print(f"--- {path}")
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    fm = front_matter(text)
    date = artifact_date(text, path)
    legacy = bool(date) and date < CONTRACT_DATE
    if legacy:
        print(f"  note  artifact date {date} predates the {CONTRACT_DATE} contract — the "
              f"structure checks are reported, not enforced")

    # ---- A. every published tag agrees with its own ratio ----
    # Table rows are only per-slice tags when the artifact declares the thresholds; before the
    # contract every slice row carried the overall tag.
    strict_rows = declares_thresholds(text) or not legacy
    seen = set()
    for tag, ratio, ctx in ratio_tag_pairs(text):
        key = (tag, ratio, ctx[:40])
        if key in seen:
            continue
        seen.add(key)
        expected = tag_from_ratio(ratio)
        if expected != tag:
            msg = (f"bias tag contradicts its own ratio: {ctx!r} — the thresholds "
                   f"(<{BIAS_CALL_BELOW} CALL, >{BIAS_PUT_ABOVE} PUT) make this {expected}")
            if strict_rows:
                fails += bad(msg)
            else:
                print(f"  note  {msg} (legacy slice convention — not enforced)")
        else:
            ok(f"tag/ratio agree: {tag} on {ratio}")

    # ---- A2. front matter tag lines, checked explicitly ----
    for k, v in fm:
        if k in FM_TAG_KEYS:
            m = re.search(r"\b(CALL|PUT|MIXED)\b", v)
            r = re.search(r"put/call[^0-9]*(\d+(?:\.\d+)?)", v, re.I)
            if not m:
                continue
            if not r:
                fails += bad(f"front matter '{k}' carries a tag but no ratio: {v!r}")
                continue
            expected = tag_from_ratio(float(r.group(1)))
            if m.group(1).upper() != expected:
                fails += bad(f"front matter '{k}' = {m.group(1).upper()} contradicts ratio "
                             f"{r.group(1)} (should be {expected})")
            else:
                ok(f"front matter '{k}' tag/ratio agree ({m.group(1).upper()} on {r.group(1)})")

    # ---- B. the audit line's tag equals the front matter's tag ----
    am = re.search(r"bias=(\w+)", text)
    if am:
        audit = am.group(1).upper()
        fm_tags = []
        for k in ("bias", "series_book_bias"):
            v = fm_get(fm, k)
            if v:
                m = re.search(r"\b(CALL|PUT|MIXED)\b", v)
                if m:
                    fm_tags.append(m.group(1).upper())
        if fm_tags and audit not in fm_tags:
            fails += bad(f"audit line bias={audit} disagrees with the front matter tag "
                         f"{fm_tags[0]}")
        elif fm_tags:
            ok(f"audit line bias={audit} matches the front matter")

    # ---- C. rev-2 artifacts name the universe of every ratio ----
    if fm_get(fm, "relative_screen_universe"):
        for key in FM_UNIVERSE_KEYS:
            if not fm_get(fm, key):
                fails += bad(f"front matter is missing '{key}' — every published ratio must "
                             f"name its population")
            else:
                ok(f"front matter names '{key}'")
        for k, v in fm:
            if k in FM_RATIO_KEYS and not any(mk in v.lower() for mk in UNIVERSE_MARKERS):
                fails += bad(f"front matter '{k}' publishes a ratio without naming its universe: "
                             f"{v!r}")
        # ---- D. the relative screen leads ----
        h_rel = re.search(r"^## .*relative-volume leaders", text, re.M | re.I)
        h_ser = re.search(r"^## .*series book", text, re.M | re.I)
        if h_rel and h_ser and h_rel.start() > h_ser.start():
            fails += bad("the series book appears before the relative screen — the relative "
                         "screen is the headline")
        elif h_rel and h_ser:
            ok("the relative screen leads the artifact")
        else:
            fails += bad("could not locate both the relative-screen and series-book sections")
    else:
        # A legacy artifact has no ``` front matter: its front matter is the "Method declaration"
        # table at the top. Either form counts, as long as the universe is named.
        uni_evidence = []
        if fm_get(fm, "universe"):
            uni_evidence.append(fm_get(fm, "universe"))
        head = text.splitlines()[:60]
        for ln in head:
            if ln.lstrip().startswith("|"):
                cells = [c.strip() for c in ln.strip().strip("|").split("|")]
                if cells and "universe" in cells[0].lower():
                    uni_evidence.append(" / ".join(cells[:2]))
        if uni_evidence:
            ok(f"front matter names the universe: {uni_evidence[0][:80]}")
        elif legacy:
            print(f"  note  front matter does not name the universe (legacy artifact, "
                  f"pre-{CONTRACT_DATE}) — not enforced")
        else:
            fails += bad("front matter does not name the universe of the ratios it publishes")

    # ---- F. the column contract ----
    col_strict = bool(date) and date >= COLUMN_CONTRACT_DATE
    if col_strict:
        cc = fm_get(fm, "column_contract") or ""
        if not cc.split()[0:1] == [COLUMN_CONTRACT_ID]:
            fails += bad(f"front matter must declare 'column_contract: {COLUMN_CONTRACT_ID}' — "
                         f"the engine that produced this artifact may predate the column contract")
        else:
            ok("front matter declares the column contract")
    else:
        print(f"  note  artifact date {date} predates the {COLUMN_CONTRACT_DATE} column contract — "
              f"the column checks are reported, not enforced")
    fails += check_column_contract(text, col_strict, path)
    return fails


def check_reply(path, col_strict=True):
    fails = 0
    print(f"--- {path} (reply)")
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    lines = [ln.rstrip() for ln in text.splitlines()]
    first = next((ln for ln in lines if ln.strip()), "")
    if not first:
        return bad("the reply is empty")
    low = first.lower()
    if not any(mk in low for mk in UNIVERSE_MARKERS):
        fails += bad(f"the reply's first line does not name a universe: {first[:100]!r}")
    else:
        ok("the reply's first line names a universe")
    if re.search(r"put\s*/\s*call|\bP/C\b", first, re.I) and not any(mk in low for mk in UNIVERSE_MARKERS):
        fails += bad("the reply's first line quotes a ratio without naming its universe")

    # ---- F. the reply's contract table gives the expiry date its own column ----
    fails += check_column_contract(text, col_strict, "reply")
    return fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", action="append", help="artifact path (repeatable)")
    ap.add_argument("--dir", help="check every .md in this directory")
    ap.add_argument("--reply", help="optional reply text to check")
    args = ap.parse_args()

    paths = list(args.md or [])
    if args.dir:
        paths += sorted(os.path.join(args.dir, f) for f in os.listdir(args.dir)
                        if f.endswith(".md"))
    if not paths:
        print("usage: check_options_flow_artifact.py --md <file> [--md <file>...] | --dir <dir> "
              "[--reply <file>]", file=sys.stderr)
        sys.exit(2)

    fails = 0
    dates = []
    for p in paths:
        fails += check_md(p)
        try:
            with open(p, encoding="utf-8") as fh:
                dates.append(artifact_date(fh.read(), p))
        except OSError:
            pass
    if args.reply:
        # The reply is checked against the SAME column contract as the artifact it describes.
        # Its date is the artifact's date; with no artifact, the reply is treated as current.
        col_strict = True
        for d in dates:
            if d:
                col_strict = d >= COLUMN_CONTRACT_DATE
                break
        fails += check_reply(args.reply, col_strict=col_strict)

    print()
    if fails:
        print(f"FAILED: {fails} check(s) failed.")
        sys.exit(1)
    print(f"PASS: contract satisfied for {len(paths)} artifact(s).")
    sys.exit(0)


if __name__ == "__main__":
    main()
