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
    return fails


def check_reply(path):
    fails = 0
    print(f"--- {path} (reply)")
    with open(path, encoding="utf-8") as fh:
        lines = [ln.rstrip() for ln in fh.read().splitlines()]
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
    for p in paths:
        fails += check_md(p)
    if args.reply:
        fails += check_reply(args.reply)

    print()
    if fails:
        print(f"FAILED: {fails} check(s) failed.")
        sys.exit(1)
    print(f"PASS: contract satisfied for {len(paths)} artifact(s).")
    sys.exit(0)


if __name__ == "__main__":
    main()
