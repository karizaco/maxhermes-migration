#!/usr/bin/env python3
"""
check_in_play_artifact.py — assert the cron #17 `us-stocks-in-play` artifact contract.

Do not eyeball it. The 2026-11-05 open-slot fire produced a mechanically correct screen
and a reader-hostile document: the pace constant's 10.77%-16.49% regime band appeared
only in the Method section, never with the pace numbers a reader actually uses; there
was no "what to watch at the open" block, so the open board stopped at a snapshot and
handed the reader nothing to act on; the tradeable tiers were buried above a 610-name
TECH_WATCH table; and the published rows carried no `has_catalyst_timestamp` /
`reason_without_timestamp` fields, so a reader could not tell a catalyst the routine
researched from one it merely inherited.

This script turns the acceptance criteria into machine assertions, so a run that breaks
the contract FAILS instead of shipping.

USAGE
    python3 check_in_play_artifact.py --md us-stocks-in-play/<date>.md \
                                      --csv us-stocks-in-play/<date>-candidates.csv \
                                      [--slot open|preclose] \
                                      [--reply <reply.txt>]

Exit codes: 0 = contract satisfied; 1 = at least one FAIL (each is printed).
"""

import argparse
import csv
import os
import re
import sys

CONTRACT_VERSION = "in-play-artifact-v2"
# v1 boards (published before 2026-11-13) are GRANDFATHERED: they are checked against
# the rules that were in force when they were written. A checker that fails a historical
# board for a rule that post-dates it is a false alarm, and the fleet's auditors treat
# those as findings — so the marker decides which rule set applies.
LEGACY_CONTRACT_VERSIONS = ("in-play-artifact-v1",)
# The Tier B publication rule that v2 introduces.
TIER_B_MAX_ROWS = 10
TIER_B_MIN_MOVE_PCT = 5.0

# The two slots are different screens with different floors and different volume
# measures. The slot selects the floors, the pace/RVol label, the delta source and
# the required sections.
SLOTS = ("open", "preclose")

# --- the pace constant (measured 2026-11-05, 480 symbol-sessions) ---------------
# Published in the skill spec; keep the two in sync.
PACE_CONSTANT = 0.125
PACE_BAND_LOW = 0.1077          # 10.77% — the low end of the 10 daily medians
PACE_BAND_HIGH = 0.1649         # 16.49% — the high end
OPEN_DOLLAR_FLOOR = 500_000     # ~$0.5m session $ volume to 09:50
PRECLOSE_DOLLAR_FLOOR = 2_000_000  # ~$2m full-session

# The measured band is what makes a published pace number honest. A reader who sees
# "pace 3.06" with no band reads a measurement; the truth is a screen whose value
# moves with the session's opening-share regime.
PACE_BAND_TOKENS = ("0.1077", "0.1649", "10.77", "16.49")

# Required CSV columns, per slot. Each entry is a group of ALTERNATIVE header names —
# a slot may name its columns either way, but it must carry the field.
REQUIRED_CSV_COLS = {
    "open": [
        ("ticker",),
        ("tier",),
        ("close_0950", "close"),
        ("chg_pct_0950", "chg_pct"),
        ("session_vol_to_0950", "session_vol"),
        ("avg_vol_10d",),
        ("pace",),
        ("session_dollar_vol_0950", "session_dollar_vol"),
        ("gap_verdict_20min", "gap_verdict"),
        ("catalyst",),
        ("has_catalyst_timestamp",),
        ("reason_without_timestamp",),
    ],
    "preclose": [
        ("ticker",),
        ("tier",),
        ("close",),
        ("chg_pct",),
        ("session_vol",),
        ("avg_vol_10d",),
        ("rvol",),
        ("session_dollar_vol",),
        ("gap_verdict",),
        ("catalyst", "catalyst_materiality"),
        ("has_catalyst_timestamp",),
        ("reason_without_timestamp",),
    ],
}

# The open slot's volume measure is `pace`; the pre-close slot's is `RVol`. They are
# different quantities on different denominators and are never comparable, so a slot
# must not publish the other's label.
FORBIDDEN_COLS_BY_SLOT = {
    "open": ("rvol", "rvol_basis"),
    "preclose": ("pace", "pace_basis"),
}

# The sections every board carries, in order. The open board additionally carries the
# overnight annex and the "what to watch at the open" block; the pre-close board
# carries the overnight carry.
COMMON_SECTIONS = [
    "theheadline",
    "tiera",
    "softa",
    "gapann",
    "sourcehealth",
    "methodandcaveats",
    "files",
]

# The keys are matched against the NORMALIZED heading, which strips every
# non-alphanumeric character. So "Overnight → open" normalizes to "overnightopen"
# (the arrow and the spaces both vanish) and "What to watch at the open" to
# "whattowatchattheopen". Write the keys as they normalize, not as they read.
# The required sections, per slot, as ORDERED GROUPS rather than a strict list.
# The groups encode what the reader needs in what order: the tradeable tiers first,
# the gap annex (the centrepiece) next, then the bulk tiers whose tables are capped.
# Within a group the order is free — the published boards have placed Tier C before
# Tier B on some days, and pinning that would fail a run that is otherwise correct.
OPEN_SECTION_GROUPS = [
    ["theheadline"],
    ["whatchangedsincethe"],
    ["marketcontext"],
    ["overnightopen"],
    ["whattowatchattheopen"],
    ["tiera", "softa"],
    ["gapann"],
    ["techwatch", "tierb", "tierc"],
    ["sourcehealth"],
    ["methodandcaveats"],
    ["files"],
]

PRECLOSE_SECTION_GROUPS = [
    ["theheadline"],
    ["whatchangedsincethe"],
    ["marketcontext"],
    ["tiera", "softa"],
    ["gapann"],
    ["techwatch", "tierb", "tierc"],
    ["overnightpreclose", "overnightcarry"],
    ["sourcehealth"],
    ["methodandcaveats"],
    ["files"],
]

PRECLOSE_SECTIONS = [
    "theheadline",
    "whatchangedsincethe",
    "marketcontext",
    "tiera",
    "softa",
    "gapann",
    "techwatch",
    "tierb",
    "tierc",
    "overnightpreclose",
    "overnightcarry",
    "sourcehealth",
    "methodandcaveats",
    "files",
]


# The tier-count imbalance the reader must SEE, not infer: a TECH_WATCH count an order
# of magnitude above Tier A is the single most misleading number on a board whose
# tier tables are capped.
TIER_COUNT_SECTIONS = ("tiera", "softa", "techwatch", "tierb", "tierc")

# A tier table publishes at most this many rows; the FULL tier count must still be
# visible in the heading. (TECH_WATCH is capped at 30; Tier B at 25.)
MAX_TIER_ROWS = {"tiera": 25, "softa": 25, "techwatch": 30, "tierb": 25, "tierc": 25}
# Under v2 the Tier B table is selected by MOVE with a floor, not by turnover.
MAX_TIER_ROWS_V2 = dict(MAX_TIER_ROWS, tierb=TIER_B_MAX_ROWS)

# The open board's payoff block: three names, each with the prior close, the current
# price and an invalidation level.
WATCH_BLOCK_MIN_NAMES = 3

# A halt COUNT is not measurable: the TradingView `halted` column is null on every
# row. These patterns are the ways a run states a count anyway. The open artifact's
# "halts are not measurable this session" phrasing is ALLOWED and required.
HALT_COUNT_PATTERNS = [
    r"halted\s*[:=]\s*0\b",
    r"\b0\s+halts\b",
    r"\bzero\s+halts\b",
    r"\bno\s+halts\b",
    r"halt\s+count\s*[:=]\s*0\b",
    r"halts\s*[:=]\s*0\b",
]

FAILURES = []
CHECKS = 0


def ok(msg):
    global CHECKS
    CHECKS += 1
    print(f"  ok   {msg}")


def bad(msg):
    global CHECKS
    CHECKS += 1
    FAILURES.append(msg)
    print(f"  FAIL {msg}")


def norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def num(v):
    if v is None:
        return None
    s = str(v).strip().replace("$", "").replace(",", "").replace("%", "")
    s = s.replace("+", "")
    try:
        return float(s)
    except ValueError:
        return None


# A published cell that still looks like a Python repr means a data structure leaked
# into the artifact instead of the string it was meant to be. Measured 2026-11-12: a
# catalyst map whose values were (reason, has_timestamp) TUPLES was rendered as
# "['Q3 revenue of $980.8m ...', 'yes']" — in the delta table AND in the CSV — and the
# contract passed, because every assertion above tests only that the cell is NON-EMPTY.
# NB: no bare `None`/`True`/`False` word test here — a legitimate reason can contain
# "True Value" (Morningstar's fair-value measure). Only STRUCTURAL repr shapes count.
REPR_PATTERNS = (
    r"^\s*\[",                                        # a list repr
    r"^\s*\(\s*['\"]",                              # a tuple repr
    r"^\s*\{.*:.*\}\s*$",                           # a dict repr
    r"^\s*['\"][^'\"]*['\"]\s*,\s*['\"]",        # a flat two-string tuple repr
    r"\[\s*['\"][^\]]*['\"]\s*,\s*['\"][^\]]*\]",  # a pair of quoted strings in brackets
)


def looks_like_repr(value):
    v = str(value or "")
    if not v.strip():
        return False
    return any(re.search(pat, v) for pat in REPR_PATTERNS)


def sections(lines):
    """Map '## Heading' -> (start, end) over the whole document."""
    heads = []
    for i, ln in enumerate(lines):
        m = re.match(r"^#{1,3}\s+(.*?)\s*$", ln)
        if m:
            heads.append((i, m.group(1).strip()))
    out = {}
    for n, (i, name) in enumerate(heads):
        end = heads[n + 1][0] if n + 1 < len(heads) else len(lines)
        out.setdefault(name, (i, end))
    return out


def find_section(secs, key):
    """Return (name, (start, end)) for the first section whose normalized heading
    contains `key`, else None."""
    for name, span in secs.items():
        if key in norm(name):
            return name, span
    return None


def section_body(lines, secs, key):
    hit = find_section(secs, key)
    if not hit:
        return []
    i, j = hit[1]
    return lines[i + 1:j]


def strip_fences(lines):
    out, inside = [], False
    for ln in lines:
        if ln.strip().startswith("```"):
            inside = not inside
            continue
        if not inside:
            out.append(ln)
    return out


def md_tables(body):
    """Every markdown table in `body` -> list of (headers, rows)."""
    tables, headers, rows = [], None, []
    for ln in body:
        if not ln.strip().startswith("|"):
            if headers is not None:
                tables.append((headers, rows))
                headers, rows = None, []
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if headers is None:
            if all(set(c) <= set("-: ") and c for c in cells):
                continue
            headers = cells
            continue
        if all(set(c) <= set("-: ") and c for c in cells):
            continue
        rows.append(dict(zip(headers, cells)))
    if headers is not None:
        tables.append((headers, rows))
    return tables


def count_in_heading(name):
    """The tier's FULL count from its heading, e.g. 'TECH_WATCH — ... (610 names;
    the top 30 by turnover are published)' -> 610."""
    m = re.search(r"\(\s*(\d[\d,]*)\s+names?\b", name, re.I)
    if m:
        return int(m.group(1).replace(",", ""))
    m = re.search(r"—\s*(\d[\d,]*)\s+names?\b", name, re.I)
    if m:
        return int(m.group(1).replace(",", ""))
    m = re.search(r"\b(\d[\d,]*)\s+names?\b", name, re.I)
    if m:
        return int(m.group(1).replace(",", ""))
    return None


def check_md(path, slot, csv_rows=None):
    print(f"[markdown] {path}  (slot={slot})")
    with open(path, encoding="utf-8", errors="replace") as fh:
        raw = fh.read()
    lines = raw.split("\n")
    secs = sections(lines)
    body = strip_fences(lines)
    alltext = "\n".join(body)
    # the front matter — the bullet block before the first `##` heading, where the
    # routine records its slot, fire time and "Prior digest" lines.
    front = "\n".join(lines[:next((i for i, ln in enumerate(lines)
                                   if ln.startswith("## ")), len(lines))])

    # which contract the board was built against (the marker decides the rule set)
    contract_v2 = False
    for ln in raw.split("\n")[:40]:
        if "contract:" in ln.lower():
            mm = re.search(r"contract:\s*[*_`\s]*(in-play-artifact-v\d+)", ln, re.I)
            contract_v2 = bool(mm and mm.group(1) == CONTRACT_VERSION)
            break

    # --- 1. the required sections, in order -----------------------------------
    groups = OPEN_SECTION_GROUPS if slot == "open" else PRECLOSE_SECTION_GROUPS
    missing, group_positions = [], []
    for group in groups:
        hits = [find_section(secs, k) for k in group]
        hits = [h for h in hits if h]
        if not hits:
            missing.append(" / ".join(group))
            group_positions.append(None)
        else:
            # a group may carry several of its members (e.g. overnightpreclose AND
            # overnightcarry); the group's position is its FIRST member.
            group_positions.append(min(h[1][0] for h in hits))
    if missing:
        bad("the artifact is missing the required section(s): " + ", ".join(missing))
    present = [p for p in group_positions if p is not None]
    if len(present) == len(groups):
        if present == sorted(present):
            ok(f"the required sections are present and in order ({len(present)} groups)")
        else:
            bad("the required sections are present but OUT OF ORDER — the tradeable tiers "
                "come first, then the gap annex, then the capped bulk tiers. The contract's "
                "order is: " + " -> ".join(g[0] for g in groups))

    # --- 2. the contract marker ------------------------------------------------
    ml = None
    for ln in raw.split("\n")[:40]:
        if "contract:" in ln.lower():
            ml = ln
            break
    if not ml:
        bad("the artifact carries no contract marker line — expected a line containing "
            f"`contract: {CONTRACT_VERSION}`")
    else:
        # tolerate markdown emphasis and backticks around the value:
        # "**Contract:** `in-play-artifact-v1`" is as good as a bare one.
        m = re.search(r"contract:\s*[*_`\s]*(in-play-artifact-v\d+)", ml, re.I)
        got = m.group(1) if m else None
        if got == CONTRACT_VERSION:
            ok(f"the artifact carries the current contract marker ({got})")
        elif got in LEGACY_CONTRACT_VERSIONS:
            ok(f"the artifact carries the LEGACY contract marker ({got}) — it is checked "
               "against the rules in force when it was written")
        else:
            bad(f"the artifact carries contract '{got if got else '?'}', expected "
                f"'{CONTRACT_VERSION}' — it was produced by an older copy of the spec. "
                "Re-read the skill spec and rebuild it.")

    # --- 3. the pace band must be published WITH the pace numbers --------------
    # The pace measure belongs to the OPEN slot only. The pre-close board's measure
    # is RVol, and the band is a property of the opening-share regime, not of RVol.
    if slot == "open":
        band_tokens = [t for t in PACE_BAND_TOKENS if t in alltext]
        if len(band_tokens) >= 2:
            ok("the pace regime band is published in the artifact "
               f"({', '.join(sorted(set(band_tokens))[:2])})")
        else:
            bad("the pace regime band is NOT published — the 0.125 constant is measured, not "
                "exact (the 10 daily medians span 10.77%-16.49%), so a pace number without "
                "the band reads as a measurement when it is a screen. Publish the band "
                "alongside the pace numbers.")

        if str(PACE_CONSTANT) in alltext:
            ok(f"the pace constant ({PACE_CONSTANT}) is stated in the artifact")
        else:
            bad(f"the pace constant ({PACE_CONSTANT}) is not stated — the pace column's "
                "denominator must be published, not implied")

    # --- 4. the slot's own measure label, never the other's -------------------
    if slot == "open":
        # 'RVol' may be mentioned in prose (to say pace is NOT comparable to it), but
        # it must never be the LABEL of the volume column.
        labelled_rvol = False
        for name, (i, j) in secs.items():
            for ln in lines[i:j]:
                if not ln.strip().startswith("|"):
                    continue
                cells = [c.strip().lower() for c in ln.strip().strip("|").split("|")]
                if any(c in ("rvol", "rvol ", "relative volume", "relative volume 10d")
                       for c in cells):
                    labelled_rvol = True
        if labelled_rvol:
            bad("a table column on the OPEN board is labelled RVol — the open slot's measure "
                "is `pace` on the elapsed-session denominator. `pace` and `RVol` are "
                "different quantities on different denominators and are never comparable.")
        else:
            ok("no table column on the open board is labelled RVol (the measure is `pace`)")
        if re.search(r"\bpace\b", alltext, re.I):
            ok("the open board labels its volume measure `pace`")
        else:
            bad("the open board never uses the word `pace` — the open slot's measure must "
                "be labelled `pace`, never `RVol`")
    else:
        if re.search(r"\bRVol\b", alltext) or re.search(r"\brvol\b", alltext, re.I):
            ok("the pre-close board publishes RVol (its own measure)")
        else:
            bad("the pre-close board never mentions RVol — the pre-close slot's measure "
                "is RVol on the trailing-10 full-session denominator")

    # --- 5. tier counts visible, tier tables capped ---------------------------
    for key in TIER_COUNT_SECTIONS:
        hit = find_section(secs, key)
        if not hit:
            continue
        name = hit[0]
        full = count_in_heading(name)
        if full is None:
            bad(f"the '{name}' heading states no tier COUNT — a capped table whose full "
                "count is missing makes the tradeable/technical imbalance invisible")
            continue
        tb = strip_fences(lines[hit[1][0] + 1:hit[1][1]])
        rows = []
        for h, r in md_tables(tb):
            rows.extend(r)
        caps = MAX_TIER_ROWS_V2 if contract_v2 else MAX_TIER_ROWS
        cap = caps.get(key, 25)
        if len(rows) <= cap:
            ok(f"'{name}': full count {full} stated, {len(rows)} rows published (cap {cap})")
        else:
            bad(f"'{name}' publishes {len(rows)} rows — the cap is {cap}")
        if contract_v2 and key == "tierb":
            # v2: Tier B is selected by MOVE with a floor, never by turnover.
            for r in rows:
                mv = num(r.get("09:50 ET") or r.get("Change") or r.get("chg"))
                if mv is None:
                    cells = " ".join(str(v) for v in r.values())
                    mm = re.search(r"(-?\d+\.?\d*)%", cells)
                    mv = float(mm.group(1)) if mm else None
                if mv is None:
                    bad(f"a Tier B row carries no move to test against the 5% floor: "
                        f"{str(list(r.values()))[:90]}")
                    break
                if abs(mv) < TIER_B_MIN_MOVE_PCT:
                    bad(f"a Tier B row publishes a {mv:+.2f}% move — the Tier B table under "
                        f"contract v2 carries only names that moved {TIER_B_MIN_MOVE_PCT}% or "
                        "more (it is selected by MOVE, not by turnover)")
                    break
            else:
                ok(f"every published Tier B row moved {TIER_B_MIN_MOVE_PCT}% or more")

    # --- 6. the "what changed" section is a TABLE with the required columns ----
    hit = find_section(secs, "whatchangedsincethe")
    if hit:
        tb = strip_fences(lines[hit[1][0] + 1:hit[1][1]])
        tables = md_tables(tb)
        if not tables:
            # The only acceptable way to have no table is a documented first fire:
            # the open board's chain starts on the day the slot is deployed.
            if re.search(r"no prior open board|first link in the open-board chain|"
                         r"no prior .{0,12}board", "\n".join(tb), re.I):
                ok("the 'what changed' section documents that there is no prior open board "
                   "(a first fire) instead of publishing a delta")
            else:
                bad("the 'what changed since the prior digest' section has NO table — it must "
                    "be a table a reader can diff two sessions with (or state explicitly that "
                    "this is the first open board and there is no prior one)")
        else:
            raw_headers = list(tables[0][0])
            headers = [norm(h) for h in raw_headers]
            raws = [str(h).lower() for h in raw_headers]
            # The contract's columns: ticker, tier, yesterday, today, the change, why.
            # A date-labelled header (11-04) is a legitimate "yesterday" column, so the
            # day columns are satisfied by NAME or by DATE. The RAW header is used for
            # the date and Δ tests — normalization strips the dash out of "11-04" and
            # the delta symbol out of "Δ".
            date_cols = [i for i, raw in enumerate(raws)
                         if re.search(r"\d{1,2}\s*[-/]\s*\d{1,2}|\d{4}-\d{2}-\d{2}", raw)]
            two_days = len(date_cols) >= 2

            def _named(frags):
                return any(any(f in h for f in frags) for h in headers)

            def _day(named_frags):
                # a named column, or a date column when the table carries two days
                return _named(named_frags) or two_days

            def _change():
                if _named(("change", "delta", "diff")):
                    return True
                # the Greek delta capitalises to U+0394 and lowercases to U+03B4, so
                # match against the RAW header (not the lowercased one).
                return any(("Δ" in raw or "δ" in raw or "pp" in raw)
                           for raw in raw_headers)

            checks = (
                (_named(("ticker", "symbol")), "ticker"),
                (_named(("tier",)), "tier"),
                (_day(("yesterday", "prior")), "yesterday"),
                (_day(("today", "current")), "today"),
                (_change(), "the change"),
                (_named(("why", "reason", "cause")), "why"),
            )
            for good, what in checks:
                if good:
                    ok(f"the delta table has a '{what}' column")
                else:
                    bad(f"the delta table has NO '{what}' column — the contract's columns are "
                        "ticker, tier, yesterday, today, the change, and why, so a reader can "
                        "diff two sessions at a glance")

        # The delta must be computed against the PRIOR OPEN board, and the artifact
        # must NAME the file it read. Naming it is the proof the right file was read:
        # the newest file in the directory is often the pre-close board. The statement
        # may sit in the delta section or in the front matter, which is where the
        # routine records its "Prior digest" line.
        #
        # This is the OPEN slot's rule: the open board's delta compares a 20-minute
        # screen against the previous day's 20-minute screen. The pre-close board's
        # delta compares a full session against a full session, so it names the
        # pre-close board instead — and its own check is the section order above.
        if slot == "open":
            dtxt = "\n".join(tb)
            if re.search(r"\d{4}-\d{2}-\d{2}-open\.md", dtxt) or re.search(
                    r"\d{4}-\d{2}-\d{2}-open\.md", front):
                # EVERY check must report on its PASS path too. A check that only
                # speaks when it fails is indistinguishable from a check that never
                # ran, and the count of assertions silently drops below the contract.
                ok("the artifact names the prior OPEN board file it read "
                   "(the delta is computed against the previous day's `-open.md`)")
            elif re.search(r"no prior open board|first link in the open-board chain",
                           dtxt + front, re.I):
                ok("the artifact states there is no prior open board to diff against")
            else:
                bad("the artifact does NOT name the prior open board file it read — the "
                    "open board's delta is computed against the previous day's `-open.md`, "
                    "and the artifact must say which file that was (the newest file in "
                    "the directory is usually the PRE-close board)")
        else:
            # The pre-close slot diffs a full session against a full session, so it must
            # name the previous day's PRE-close board — never an open board. A slot that
            # diffs against the other slot's board compares a 20-minute screen to a full
            # session and the numbers are meaningless.
            dtxt = "\n".join(tb)
            if re.search(r"\d{4}-\d{2}-\d{2}-open\.md", dtxt):
                bad("the pre-close board names an OPEN board as its delta source — the "
                    "pre-close slot diffs a full session against a full session, so it must "
                    "name the previous day's pre-close board (`<date>.md`)")
            elif re.search(r"\d{4}-\d{2}-\d{2}\.md", dtxt) or re.search(
                    r"\d{4}-\d{2}-\d{2}\.md", front):
                ok("the artifact names the prior PRE-close board file it read")
            else:
                bad("the artifact does NOT name the prior pre-close board file it read — "
                    "say which `<date>.md` the delta was computed against")

    # --- 6b. the overnight annex names the prior PRE-CLOSE board ---------------
    if slot == "open":
        hit = find_section(secs, "overnightopen")
        if hit:
            # The heading is part of the statement ("... — the carry handoff from the
            # 2026-11-04 pre-close board"), so the heading counts.
            atxt = "\n".join(lines[hit[1][0]:hit[1][1]])
            m = re.search(r"\d{4}-\d{2}-\d{2}\.md", atxt)
            if m:
                ok(f"the Overnight → open annex names the prior PRE-close board it read "
                   f"({m.group(0)})")
            elif re.search(r"\d{4}-\d{2}-\d{2}[^|\n]{0,40}pre-close board", atxt, re.I):
                ok("the Overnight → open annex names the prior pre-close board it read")
            else:
                bad("the Overnight → open annex does NOT name the prior pre-close board file "
                    "it read — the annex is sourced from the previous day's pre-close board, "
                    "and the artifact must say which file that was")

    # --- 7. the open board's payoff block --------------------------------------
    if slot == "open":
        hit = find_section(secs, "whattowatchattheopen")
        if not hit:
            bad("the open board has NO '## What to watch at the open' block — the open board's "
                "job is to hand the watch list forward into the live tape, and a board that "
                "stops at a snapshot hands the reader nothing to act on. Publish 3 names "
                "with their prior close, current price and invalidation level.")
        else:
            tb = strip_fences(lines[hit[1][0] + 1:hit[1][1]])
            tables = md_tables(tb)
            if not tables:
                bad("the 'What to watch at the open' block has no table")
            else:
                headers, rows = tables[0]
                hnorm = [norm(h) for h in headers]
                # each requirement is a SET of acceptable column fragments — any one
                # of them satisfies it ("Name" and "Ticker" are the same column).
                for frags, what in (
                    (("name", "ticker"), "name"),
                    (("close",), "prior close"),
                    (("price", "last", "current"), "current price"),
                    (("invalid", "stop", "level"), "invalidation level"),
                ):
                    if any(any(f in h for f in frags) for h in hnorm):
                        ok(f"the watch block has a '{what}' column")
                    else:
                        bad(f"the watch block has NO '{what}' column "
                            f"(one of: {', '.join(frags)})")
                if len(rows) >= WATCH_BLOCK_MIN_NAMES:
                    ok(f"the watch block publishes {len(rows)} names (>= {WATCH_BLOCK_MIN_NAMES})")
                else:
                    bad(f"the watch block publishes {len(rows)} names — it must name at "
                        f"least {WATCH_BLOCK_MIN_NAMES}")
                # each name needs a LEVEL, not just a ticker
                for r in rows:
                    cells = " ".join(str(v) for v in r.values())
                    if not re.search(r"\d", cells):
                        bad(f"the watch block row {cells[:60]!r} carries no price level")
                        break
                else:
                    ok("every watch-block name carries a price level")

    # --- 7b. no Python repr leaked into the document --------------------------
    repr_lines = []
    for i, ln in enumerate(alltext.split("\n"), start=1):
        if ln.strip().startswith("|"):
            cells = [c.strip() for c in ln.strip().strip("|").split("|")]
            if any(looks_like_repr(c) for c in cells):
                repr_lines.append(f"table row {i}")
    if repr_lines:
        bad(f"{len(repr_lines)} table row(s) in the artifact still look like a Python repr "
            f"({'; '.join(repr_lines[:6])}) — a data structure leaked into the board instead "
            "of the string it was meant to be.")
    else:
        ok("no table row in the artifact looks like a Python repr")

    # --- 7c. the tier counts must MATCH the CSV, and the Tier B selection must
    # be the rule's selection (not just any set of rows) -------------------------
    if csv_rows:
        def csv_tier_counts():
            c = {}
            for r in csv_rows:
                t = str(r.get("tier") or "").strip().upper()
                c[t] = c.get(t, 0) + 1
            return c
        counts = csv_tier_counts()
        KEY_TO_CSV_TIER = {"tiera": "A", "softa": "SOFT_A", "techwatch": "TECH_WATCH",
                           "tierb": "B", "tierc": "C"}
        for key, ct in KEY_TO_CSV_TIER.items():
            hit = find_section(secs, key)
            if not hit:
                continue
            stated = count_in_heading(hit[0])
            actual = counts.get(ct, 0)
            if stated is None:
                continue
            if stated != actual:
                bad(f"the '{hit[0]}' heading states {stated} names but the candidates CSV "
                    f"carries {actual} rows with tier '{ct}' — the table and the dataset "
                    "must describe the same set")
            else:
                ok(f"'{hit[0]}': the stated count {stated} matches the CSV ({actual} rows)")

        if contract_v2:
            hit = find_section(secs, "tierb")
            if hit:
                tb = strip_fences(lines[hit[1][0] + 1:hit[1][1]])
                published = []
                for _headers, _rows in md_tables(tb):
                    for r in _rows:
                        for v in r.values():
                            mm = re.match(r"\*\*([A-Z0-9.\-]{1,10})\*\*", str(v).strip())
                            if mm:
                                published.append(mm.group(1))
                                break
                chg_col = ("chg_pct_0950" if slot == "open" else "chg_pct")
                expected = []
                for r in csv_rows:
                    if str(r.get("tier") or "").strip().upper() != "B":
                        continue
                    mv = num(r.get(chg_col))
                    if mv is not None and abs(mv) >= TIER_B_MIN_MOVE_PCT:
                        expected.append((abs(mv), str(r.get("ticker"))))
                expected = [t for _, t in sorted(expected, key=lambda x: -x[0])][:TIER_B_MAX_ROWS]
                if published == expected:
                    ok(f"the Tier B table publishes exactly the rule's selection "
                       f"({len(expected)} names: |move| >= {TIER_B_MIN_MOVE_PCT}%, biggest first)")
                else:
                    bad(f"the Tier B table does not match the rule's selection — the rule is "
                        f"the {expected} names with |move| >= {TIER_B_MIN_MOVE_PCT}% biggest "
                        f"first (max {TIER_B_MAX_ROWS}), the table publishes {published}")

    # --- 8. no halt COUNT anywhere ---------------------------------------------
    hits = []
    for pat in HALT_COUNT_PATTERNS:
        for m in re.finditer(pat, alltext, re.I):
            hits.append(m.group(0))
    if hits:
        bad(f"the artifact states a HALT COUNT ({sorted(set(hits))}) — the TradingView "
            "`halted` column is null on every row, so the halt state is NOT measurable. "
            "Publish 'not measurable', never a count.")
    else:
        ok("the artifact states no halt count (the halted column is null => not measurable)")
    if re.search(r"halt", alltext, re.I) and not re.search(
            r"not measurable|not confirm|cannot be confirmed|unmeasurable|"
            r"no halt count|null on every row|null for every row", alltext, re.I):
        bad("the artifact mentions halts but never says the halt state is NOT MEASURABLE — "
            "a reader must be told the column is null, not left to infer a count")
    else:
        ok("the artifact says the halt state is not measurable")

    return lines, secs


def check_csv(path, slot):
    print(f"[csv] {path}")
    with open(path, newline="", encoding="utf-8") as fh:
        rdr = csv.DictReader(fh)
        cols = [c.lower() for c in (rdr.fieldnames or [])]
        rows = list(rdr)
    missing = []
    for group in REQUIRED_CSV_COLS.get(slot, REQUIRED_CSV_COLS["open"]):
        if not any(c in cols for c in group):
            missing.append(" / ".join(group))
    if missing:
        bad("the CSV header is missing required column(s): " + ", ".join(missing))
    else:
        ok(f"the CSV header carries all required columns ({len(cols)} columns)")
    forbidden = FORBIDDEN_COLS_BY_SLOT.get(slot, ())
    for c in forbidden:
        if c in cols:
            bad(f"the {slot} CSV carries a `{c}` column — that is the OTHER slot's measure. "
                "The two are different quantities on different denominators and are never "
                "comparable.")
    if not rows:
        bad("the CSV has no data rows")
        return rows

    # every row carries the two catalyst-provenance fields
    n_has = n_reason = 0
    for r in rows:
        lv = {k.lower(): (v or "") for k, v in r.items() if k}
        has = str(lv.get("has_catalyst_timestamp", "")).strip().lower()
        reason = str(lv.get("reason_without_timestamp", "")).strip()
        if has in ("yes", "no", "true", "false", "1", "0"):
            n_has += 1
        else:
            reason_bad = True
        if reason:
            n_reason += 1
    if n_has == len(rows):
        ok(f"every one of the {len(rows)} rows carries a parseable "
           "`has_catalyst_timestamp`")
    else:
        bad(f"{len(rows) - n_has} of {len(rows)} rows have no parseable "
            "`has_catalyst_timestamp` (yes/no) — the reader must be able to tell a "
            "timestamped catalyst from an untimestamped one")
    if n_reason == len(rows):
        ok(f"every one of the {len(rows)} rows carries a `reason_without_timestamp`")
    else:
        bad(f"{len(rows) - n_reason} of {len(rows)} rows carry an empty "
            "`reason_without_timestamp` — a row with no timestamp still owes the reader "
            "the REASON, because the routine researches catalysts itself against issuer IR "
            "and EDGAR filings")

    # no published cell may still be a Python repr
    repr_rows = []
    for i, r in enumerate(rows, start=2):
        for k, v in r.items():
            if v and looks_like_repr(v):
                repr_rows.append(f"row {i} column '{k}'")
    if repr_rows:
        bad(f"{len(repr_rows)} published cell(s) still look like a Python repr "
            f"({'; '.join(repr_rows[:6])}) — a data structure leaked into the artifact "
            "instead of the string it was meant to be. Render the value, not the tuple.")
    else:
        ok(f"no published cell looks like a Python repr ({len(rows)} rows checked)")

    # the pace column must reconcile with its own stated denominator
    if slot == "open":
        checked = mismatched = 0
        for r in rows:
            lv = {k.lower(): (v or "") for k, v in r.items() if k}
            sv = num(lv.get("session_vol_to_0950"))
            av = num(lv.get("avg_vol_10d"))
            pc = num(lv.get("pace"))
            if not sv or not av or pc is None or av == 0:
                continue
            expect = (sv / av) / PACE_CONSTANT
            if abs(expect - pc) / max(abs(pc), 1e-9) > 0.02:
                mismatched += 1
            else:
                checked += 1
        if checked + mismatched:
            if mismatched == 0:
                ok(f"every pace row reconciles with (session_vol/avg_vol_10d)/{PACE_CONSTANT} "
                   f"({checked} rows checked)")
            else:
                bad(f"{mismatched} of {checked + mismatched} pace rows do NOT reconcile with "
                    f"(session_vol/avg_vol_10d)/{PACE_CONSTANT} — the published pace is "
                    "not on the pace-adjusted scale")
        else:
            bad("no CSV row has enough of (session_vol_to_0950, avg_vol_10d, pace) to check "
                "the pace scale")
    return rows


def check_reply(path):
    print(f"[reply] {path}")
    with open(path, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    hits = []
    for pat in HALT_COUNT_PATTERNS:
        for m in re.finditer(pat, text, re.I):
            hits.append(m.group(0))
    if hits:
        bad(f"the reply states a HALT COUNT ({sorted(set(hits))}) — the halt state is not "
            "measurable and a count must never be published")
    else:
        ok("the reply states no halt count")
    band = [t for t in PACE_BAND_TOKENS if t in text]
    if len(band) >= 2:
        ok("the reply publishes the pace regime band")
    else:
        bad("the reply does NOT publish the pace regime band — the reply says the pace is "
            "pace-adjusted, and the band is what makes that honest")
    if str(PACE_CONSTANT) in text:
        ok("the reply states the pace constant")
    else:
        bad(f"the reply does not state the pace constant ({PACE_CONSTANT})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", required=True)
    ap.add_argument("--csv", required=True)
    ap.add_argument("--slot", choices=SLOTS, default=None)
    ap.add_argument("--reply", default=None)
    args = ap.parse_args()

    for p in (args.md, args.csv):
        if not os.path.exists(p):
            print(f"FAIL missing file: {p}")
            sys.exit(1)

    slot = args.slot
    if slot is None:
        slot = "open" if args.md.endswith("-open.md") else "preclose"

    _csv_rows = []
    try:
        with open(args.csv, newline="", encoding="utf-8") as _fh:
            _csv_rows = list(csv.DictReader(_fh))
    except Exception:
        pass

    check_md(args.md, slot, _csv_rows)
    check_csv(args.csv, slot)
    if args.reply:
        if os.path.exists(args.reply):
            check_reply(args.reply)
        else:
            bad(f"reply file not found: {args.reply}")

    print()
    if FAILURES:
        print(f"CONTRACT FAILED — {len(FAILURES)} of {CHECKS} checks failed:")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    print(f"CONTRACT OK — {CHECKS} checks passed.")
    sys.exit(0)


if __name__ == "__main__":
    main()
