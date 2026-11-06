#!/usr/bin/env python3
"""
check_ntrt_artifact.py — the machine gate for cron #25's NTRT gap brief.

MARKER: NTRT_CONTRACT_CHECK_V2

The ARTIFACT FORMAT CONTRACT in `cloud-prompts/skills/ntrt-gap-brief/SKILL.md`
used to be prose, and prose is what four briefs read three different ways.
This script turns the contract into a GATE: it reads the published markdown and
its CSV companion and asserts the sixteen rules the contract states. A run
that breaks the contract FAILS here instead of shipping.

It is deliberately a SEPARATE implementation of the contract — the routine
renders the artifact, this verifies it, and neither imports the other.

THE SIXTEEN CHECKS

   1 SECTIONS       the section skeleton is present, in order, none missing,
                    with the title line and the mode banner
   2 SECTION_EMPTY  a section with nothing in it says so in one line
   3 NO_CATALYSTS   there is no `## Catalysts` section (the catalyst rides in
                    the row's last column, so a name can never appear twice)
   4 ONE_NAME_ONCE  every name appears in exactly ONE of the published tables,
                    and the actionable and wider-screen sets do not overlap
   5 MD_CSV_AGREE   the markdown and the CSV agree on every shared field, to
                    the precision each one publishes
   6 CSV_CONTRACT   the CSV header is the contract's 12 columns, in order
   7 PCT_ADV_EMPTY  `pct_of_adv` is EMPTY (never 0) when there is no ADV
                    history, and equals volume/ADV*100 to 3 dp when there is
   8 MKTCAP_FORMAT  market caps are scaled M / B / T — never `$4937.50B`
   9 NOISE_FLAG     `noise` is true exactly when `pct_of_adv` is empty or < 1
  10 TLDR_BULLETS   the TL;DR has exactly 3 bullets
  11 TLDR_ADV_CHECK one of those 3 bullets is the %ADV reality check
  12 GATE          the actionable table holds the gate-passing names and the
                    wider screen the names that fail it — no silent drop
  13 FOURCELL      the gap-vs-catalyst 2x2 exists, its four counts are the
                    counts the artifact's own tables imply, and it states the
                    universe it counts
  14 FOURCELL_EX   every populated cell names an example that really sits in
                    that cell; an empty cell says none
  15 SUBFLOOR      the `Below the $200M floor` block is real: every name in it
                    is below the floor, in the CSV, published nowhere else, and
                    the floor never hides the day's biggest mover
  16 ALSO_CLEARED  every gate-passing name that is not in the actionable table
                    is listed under `Also cleared the gate` — a cap may
                    shorten the table, never silently drop a name

USAGE
    python3 tools/check_ntrt_artifact.py --md ntrt/2026-11-05.md \
                                         --csv ntrt/2026-11-05.csv
    python3 tools/check_ntrt_artifact.py --md ... --csv ... --reply reply.txt

Exit codes: 0 = contract satisfied; 1 = at least one check failed; 2 = the
artifact could not be read.
"""
import argparse
import csv
import os
import re
import sys

CONTRACT_VERSION = "ntrt-artifact-v4"
CONTRACT_CHECKS = 16

# The capability marker the run-time fetch demands. An OLDER copy of this script
# is still published on the mirrors, and it checks fewer rules - so a fetch that
# does not demand this marker can win a stale file and report a clean artifact
# it never checked.
MARKER = "NTRT_CONTRACT_CHECK_V2"

# ---- the published constants (they live in the skill spec; keep them in sync) ----
GATE_GAP_PCT = 3.0        # |gap| >= 3%
GATE_PCT_ADV = 5.0        # AND >= 5% of 30-day ADV
GATE_MKT_CAP = 200000000  # AND market cap >= $200M (the universe floor)
NOISE_PCT_ADV = 1.0       # noise when pct_of_adv is empty or < 1

# The section skeleton, in order. Matched by normalised PREFIX so a dated or
# annotated heading ("## Flags - 2026-11-05") still satisfies the contract.
REQUIRED_SECTIONS = [
    ("tldr", "TL;DR"),
    ("marketbackdrop", "Market backdrop"),
    ("worthyourattention", "Worth your attention"),
    ("widerscreen", "Wider screen"),
    ("flags", "Flags"),
    ("methodsourcehealthcaveats", "Method, source health & caveats"),
]

FORBIDDEN_SECTION_WORDS = ["catalyst"]

# The CSV column contract, in order.
CSV_COLUMNS = ["ticker", "premarket_change_pct", "premarket_close", "prev_close",
               "premarket_volume", "avg_volume_30d", "pct_of_adv", "mkt_cap_usd",
               "sector", "exchange", "catalyst", "noise"]

# How far two published numbers may differ and still be "the same number":
# half a unit of the MARKDOWN's last published digit.
TOL_1DP = 0.05 + 1e-9
TOL_2DP = 0.005 + 1e-9

# A name whose raw value sits this close to a gate threshold is a BOUNDARY
# case: the published 1 dp number can read the other way, so either
# classification is accepted. The classification itself is still made on the
# RAW value.
BOUNDARY = 0.05 + 1e-9

RESULTS = []
FAILURES = []


def record(name, problems, success_msg):
    """One RESULT per named check, so the published count is deterministic."""
    if problems:
        RESULTS.append((name, False))
        FAILURES.append(f"[{name}] " + problems[0] +
                        (f"  (+{len(problems) - 1} more)" if len(problems) > 1 else ""))
        print(f"  FAIL [{name}] {problems[0]}"
              + (f"  (+{len(problems) - 1} more)" if len(problems) > 1 else ""))
        for extra in problems[1:]:
            print(f"         - {extra}")
    else:
        RESULTS.append((name, True))
        print(f"  ok   [{name}] {success_msg}")


# ------------------------------------------------------------------ helpers
def norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def num(v):
    if v is None:
        return None
    s = str(v).strip().replace("$", "").replace(",", "").replace("%", "")
    s = s.replace("+", "").replace("−", "-").replace("–", "-")
    if s in ("", "-", "—", "n/a", "N/A"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


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


def is_separator(cells):
    return bool(cells) and all(c and set(c) <= set("-: ") for c in cells)


def fmt_mktcap(raw):
    """The contract's market-cap rendering: $XM under $1B, $X.XXB under $1T,
    $X.XXT above. `$4937.50B` is unreadable and is a contract breach."""
    if raw is None:
        return None
    if raw >= 1e12:
        return f"${raw / 1e12:.2f}T"
    if raw >= 1e9:
        return f"${raw / 1e9:.2f}B"
    return f"${raw / 1e6:.0f}M"


# ------------------------------------------------------------------ markdown
def parse_markdown(lines):
    """-> (sections, subsections, tables)

    sections   {normalised heading: (start, end, raw heading)}
    subsections {normalised heading: (start, end, raw heading)}
    tables     list of dicts: section, subsection, headers, rows, start
    """
    heads, subheads = [], []
    for i, ln in enumerate(lines):
        m = re.match(r"^##\s+(.*?)\s*$", ln)
        if m:
            heads.append((i, m.group(1).strip()))
            continue
        m = re.match(r"^###\s+(.*?)\s*$", ln)
        if m:
            subheads.append((i, m.group(1).strip()))

    def spans(hs):
        out = {}
        for n, (i, name) in enumerate(hs):
            end = hs[n + 1][0] if n + 1 < len(hs) else len(lines)
            out.setdefault(norm(name), (i, end, name))
        return out

    sections = spans(heads)
    subsections = spans(subheads)

    raw_tables = []
    cur = None
    for i, ln in enumerate(lines):
        if is_table_row(ln):
            if cur is None:
                cur = []
            cur.append((i, ln))
            continue
        if cur is not None:
            raw_tables.append(cur)
            cur = None
    if cur is not None:
        raw_tables.append(cur)

    parsed = []
    for t in raw_tables:
        hdr = split_row(t[0][1])
        if is_separator(hdr):
            continue
        rows = []
        for _, ln in t[1:]:
            cells = split_row(ln)
            if is_separator(cells):
                continue
            rows.append(dict(zip(hdr, cells)))
        if not rows:
            continue
        start = t[0][0]
        section = ""
        subsection = ""
        for j, (hi, hname) in enumerate(heads):
            end = heads[j + 1][0] if j + 1 < len(heads) else len(lines)
            if hi <= start < end:
                section = norm(hname)
                break
        for j, (hi, hname) in enumerate(subheads):
            end = subheads[j + 1][0] if j + 1 < len(subheads) else len(lines)
            if hi <= start < end:
                subsection = norm(hname)
                break
        parsed.append({"section": section, "subsection": subsection,
                       "headers": hdr, "rows": rows, "start": start})
    return sections, subsections, parsed


def find_span(spans, key):
    for name, span in spans.items():
        if name.startswith(key):
            return span
    return None


def body_of(lines, span):
    if not span:
        return []
    return lines[span[0] + 1:span[1]]


def strip_fences(lines):
    out, inside = [], False
    for ln in lines:
        if ln.strip().startswith("```"):
            inside = not inside
            continue
        if not inside:
            out.append(ln)
    return out


def header_index(headers, key):
    """Index of the column whose normalised header CONTAINS `key`."""
    for i, h in enumerate(headers):
        if key in norm(h):
            return i
    return None


# The same field is headed differently in different places: the actionable table
# says "% of 30d ADV", a CSV-style table says "pct_of_adv". Every lookup goes
# through the alias list, so a header rename cannot silently SKIP a comparison.
COL_ALIASES = {
    "pctofadv": ("pctofadv", "of30dadv", "of30dayadv", "adv"),
    "gap": ("gap",),
    "pmprint": ("pmprint", "premarketclose", "print"),
    "prevclose": ("prevclose",),
    "mktcap": ("mktcap", "marketcap"),
    "why": ("why",),
    "sector": ("sector",),
}


def col(row, headers, key):
    i = None
    for alias in COL_ALIASES.get(key, (key,)):
        i = header_index(headers, alias)
        if i is not None:
            break
    if i is None:
        return None
    vals = list(row.values())
    if i >= len(vals):
        return None
    return vals[i]


def is_not_listing(subsection):
    """True for a subsection whose tables are NOT part of the screened universe.

    - `Gap vs catalyst`   the 2x2 summary, not a listing.
    - `Below the ... floor` the watchlist of names the $200M universe floor
      EXCLUDED. It is a different universe (checked by SUBFLOOR): folding it
      into the wider screen would put sub-floor names into the asymmetry
      table's "fails the gate" cell, where they do not belong - they were
      never candidates for the gate.
    - `Also cleared the gate` a prose list, never a table.
    """
    s = norm(subsection)
    if "gapvscatalyst" in s:
        return True
    if "alsocleared" in s:
        return True
    if "below" in s and "floor" in s:
        return True
    return False


def data_tables(tables, section_key):
    """The published data tables of a section: first column is `Ticker`.
    The gap-vs-catalyst summary table is NOT a listing and is excluded."""
    out = []
    for t in tables:
        if t["section"] != section_key:
            continue
        if norm(t["headers"][0]) != "ticker":
            continue
        if is_not_listing(t["subsection"]):
            continue
        out.append(t)
    return out


def collect_names(tables):
    names = []
    for t in tables:
        for r in t["rows"]:
            v = r.get(t["headers"][0], "").strip()
            if v:
                names.append(v)
    return names


# ------------------------------------------------------------------ the checks
def check_sections(lines, sections):
    problems = []
    positions = []
    for key, label in REQUIRED_SECTIONS:
        span = find_span(sections, key)
        if not span:
            problems.append(f"the section '{label}' is missing")
            positions.append(None)
        else:
            positions.append(span[0])
    present = [p for p in positions if p is not None]
    if len(present) == len(REQUIRED_SECTIONS) and present != sorted(present):
        problems.append("the sections are present but OUT OF ORDER — the contract's order is "
                        + " -> ".join(l for _, l in REQUIRED_SECTIONS))
    title = next((ln for ln in lines[:6] if ln.strip()), "")
    if not re.match(r"^#\s+NTRT gap brief", title, re.I):
        problems.append("the artifact does not open with the contract's title line "
                        "`# NTRT gap brief — <Weekday, DD Month YYYY>`")
    if not any(re.search(r"\bMode [AB]\b", ln, re.I) for ln in lines[:8]):
        problems.append("no mode banner — the reader must know whether this is the backend or "
                        "the screener fallback, and how live the snapshot is")
    record("SECTIONS", problems,
           f"the section skeleton is present and in order ({len(present)}), with the title "
           "line and the mode banner")


def check_section_empty(lines, sections):
    problems = []
    for key, label in REQUIRED_SECTIONS:
        span = find_span(sections, key)
        body = [ln for ln in strip_fences(body_of(lines, span)) if ln.strip()]
        if not body:
            problems.append(f"'{label}' is empty and does not say so in one line")
            continue
        content = [ln for ln in body if not re.match(r"^#{1,6}\s", ln)]
        if not content:
            problems.append(f"'{label}' carries no content and does not say so in one line")
            continue
        if len(content) == 1 and not re.match(
                r"^\W*(none|nothing|no\b|not applicable|n/?a|no names?\b|empty)\b",
                content[0].strip(), re.I):
            problems.append(f"'{label}' has one line that is not a 'nothing to report' note")
    record("SECTION_EMPTY", problems,
           "every section has content, or says in one line that it has none")


def check_no_catalysts(sections):
    problems = []
    for name, (_s, _e, raw) in sections.items():
        if any(w in name for w in FORBIDDEN_SECTION_WORDS):
            problems.append(f"the artifact has a catalyst section '{raw}' — the catalyst rides "
                            "in the row's last column, so a name can never appear twice")
    record("NO_CATALYSTS", problems,
           "no separate catalyst section — the catalyst rides in the row")


def check_one_name_once(tables):
    act = data_tables(tables, "worthyourattention")
    wide = data_tables(tables, "widerscreen")
    act_names = collect_names(act)
    wide_names = collect_names(wide)
    all_names = act_names + wide_names
    problems = []
    dupes = sorted({n for n in all_names if all_names.count(n) > 1})
    if dupes:
        problems.append(f"{len(dupes)} name(s) appear in more than one published table: "
                        f"{dupes[:10]} — the one-table rule is the whole point of the artifact")
    if not act_names:
        problems.append("the actionable table lists no names")
    record("ONE_NAME_ONCE", problems,
           f"every name appears in exactly one table ({len(act_names)} actionable + "
           f"{len(wide_names)} wider)")
    return act_names, wide_names


def check_csv_contract(csv_path):
    problems = []
    with open(csv_path, newline="", encoding="utf-8") as fh:
        rdr = csv.reader(fh)
        header = [h.strip() for h in next(rdr, [])]
        rows = list(rdr)
    if header != CSV_COLUMNS:
        problems.append(f"the CSV header is {header} — the contract's columns, in order, are "
                        f"{CSV_COLUMNS}")
    if not rows:
        problems.append("the CSV has no data rows")
    record("CSV_CONTRACT", problems,
           f"the CSV header carries the contract's {len(CSV_COLUMNS)} columns, in order, and "
           f"{len(rows)} screen rows")


def csv_index(csv_path):
    """{ticker: row-dict} for the CSV."""
    with open(csv_path, newline="", encoding="utf-8") as fh:
        return {r["ticker"].strip(): r for r in csv.DictReader(fh)}


def check_pct_adv(csv_path):
    problems = []
    with open(csv_path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        tick = r.get("ticker", "").strip()
        avg = num(r.get("avg_volume_30d"))
        p = (r.get("pct_of_adv") or "").strip()
        if avg is None or avg == 0:
            if p != "":
                problems.append(f"{tick}: pct_of_adv={p!r} but there is no ADV history — it "
                                f"must be EMPTY, never 0")
            continue
        if p == "":
            problems.append(f"{tick}: pct_of_adv is empty but the row carries a 30d ADV")
            continue
        pv = num(p)
        if pv is None:
            problems.append(f"{tick}: pct_of_adv={p!r} is not a number")
            continue
        vol = num(r.get("premarket_volume"))
        if vol is None:
            continue
        expect = vol / avg * 100.0
        if abs(pv - expect) > 0.0015:
            problems.append(f"{tick}: pct_of_adv={pv} but volume/ADV*100 = {expect:.3f}")
    record("PCT_ADV_EMPTY", problems,
           "pct_of_adv is empty (never 0) without ADV history and equals volume/ADV*100 "
           "elsewhere")


def check_noise_flag(csv_path):
    problems = []
    with open(csv_path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        tick = r.get("ticker", "").strip()
        p = (r.get("pct_of_adv") or "").strip()
        n = (r.get("noise") or "").strip().lower()
        pv = num(p)
        expect = (pv is None) or (pv < NOISE_PCT_ADV)
        if n not in ("true", "false"):
            problems.append(f"{tick}: noise={n!r} is not true/false")
            continue
        if (n == "true") != expect:
            problems.append(f"{tick}: noise={n} but pct_of_adv={p or 'empty'} (noise is true "
                            f"exactly when it is empty or < 1)")
    record("NOISE_FLAG", problems,
           "noise is true on exactly the rows whose pct_of_adv is empty or < 1")


def check_mktcap(tables, idx):
    problems = []
    seen = 0
    for t in data_tables(tables, "worthyourattention"):
        headers = t["headers"]
        if header_index(headers, "mktcap") is None:
            problems.append("the actionable table has no market-cap column")
            continue
        for r in t["rows"]:
            tick = r.get(headers[0], "").strip()
            cell = (col(r, headers, "mktcap") or "").strip()
            row = idx.get(tick)
            if row is None:
                continue
            want = fmt_mktcap(num(row.get("mkt_cap_usd")))
            if want is None:
                continue
            seen += 1
            if cell != want:
                problems.append(f"{tick}: market cap published as {cell!r}, the contract's "
                                f"rendering is {want!r}")
    record("MKTCAP_FORMAT", problems,
           f"every published market cap is scaled M/B/T ({seen} rows)")


def check_md_csv_agree(tables, idx):
    problems = []
    fields = 0

    def cmp(tick, label, md_raw, csv_raw, tol):
        nonlocal fields
        if md_raw is None or csv_raw is None:
            return
        fields += 1
        if abs(md_raw - csv_raw) > tol:
            problems.append(f"{tick}: {label} published as {md_raw:g} in the markdown but "
                            f"{csv_raw:g} in the CSV")

    for key in ("worthyourattention", "widerscreen"):
        for t in data_tables(tables, key):
            headers = t["headers"]
            for required in ("gap", "pctofadv"):
                if header_index(headers, COL_ALIASES[required][0]) is None and \
                        not any(header_index(headers, a) is not None
                                for a in COL_ALIASES[required]):
                    problems.append(f"a published table has no "
                                    f"{'gap %' if required == 'gap' else '% of 30d ADV'} "
                                    f"column — {headers}")
            for r in t["rows"]:
                tick = r.get(headers[0], "").strip()
                row = idx.get(tick)
                if row is None:
                    problems.append(f"{tick}: published in the markdown but absent from the CSV")
                    continue
                cmp(tick, "gap %", num(col(r, headers, "gap")),
                    num(row.get("premarket_change_pct")), TOL_1DP)
                csv_adv = num(row.get("pct_of_adv"))
                if csv_adv is None:
                    cell = (col(r, headers, "pctofadv") or "").strip()
                    if cell not in ("", "-", "—", "n/a"):
                        problems.append(f"{tick}: the CSV has no ADV history (pct_of_adv empty) "
                                        f"but the markdown publishes {cell!r}")
                else:
                    cmp(tick, "% of 30d ADV", num(col(r, headers, "pctofadv")), csv_adv, TOL_1DP)
                if key == "worthyourattention":
                    cmp(tick, "PM print", num(col(r, headers, "pmprint")),
                        num(row.get("premarket_close")), TOL_2DP)
                    cmp(tick, "prev close", num(col(r, headers, "prevclose")),
                        num(row.get("prev_close")), TOL_2DP)
    record("MD_CSV_AGREE", problems,
           f"the markdown and the CSV agree on every shared field ({fields} comparisons)")


def check_tldr(lines, sections):
    span = find_span(sections, "tldr")
    body = strip_fences(body_of(lines, span))
    bullets = [ln.strip() for ln in body if re.match(r"^\s*[-*]\s+\S", ln)]
    problems = []
    if len(bullets) != 3:
        problems.append(f"the TL;DR has {len(bullets)} bullets, not 3 — the contract fixes it "
                        f"at three: the shape, the %ADV reality check, the one name that "
                        f"matters")
    record("TLDR_BULLETS", problems, "the TL;DR has exactly 3 bullets")
    # The contract FIXES the order: 1 the shape, 2 the %ADV reality check,
    # 3 the one name that matters. So the reality check is the SECOND bullet —
    # not "any bullet that mentions ADV".
    adv = bullets[1] if len(bullets) > 1 else ""
    if not (re.search(r"%\s*adv|of\s+30[-\s]?day\s+adv|\badv\b", adv, re.I)
            and re.search(r"\d", adv)):
        record("TLDR_ADV_CHECK",
               ["the second TL;DR bullet is not the %ADV reality check — the contract fixes the "
                "order (shape / %ADV reality check / the one name that matters), and without "
                "that bullet the reader treats the screen as N tradeable names"],
               "")
    else:
        record("TLDR_ADV_CHECK", [], "the second TL;DR bullet is the %ADV reality check")


def gate_state(row):
    """(passes the gate, is a boundary case) for a CSV row, on the RAW values.

    The gate has THREE legs since v4: |gap| >= 3%, %ADV >= 5% and market cap
    >= $200M. The market-cap leg is what lets the brief publish the names the
    universe floor EXCLUDED (the `Below the $200M floor` watchlist) without
    those names counting as gate-passers - they were never candidates.

    A cap the CSV cannot supply is a BOUNDARY case, not a failure: an unknown
    cap cannot be verified either way. A cap that is KNOWN to be under the
    floor is a verified failure.
    """
    g = num(row.get("premarket_change_pct"))
    p = num(row.get("pct_of_adv"))
    c = num(row.get("mkt_cap_usd"))
    gap_ok = g is not None and abs(g) >= GATE_GAP_PCT
    adv_ok = p is not None and p >= GATE_PCT_ADV
    cap_ok = c is not None and c >= GATE_MKT_CAP
    boundary = ((g is not None and abs(abs(g) - GATE_GAP_PCT) <= BOUNDARY)
                or (p is not None and abs(p - GATE_PCT_ADV) <= BOUNDARY)
                or c is None)
    return (gap_ok and adv_ok and cap_ok), boundary


def check_gate(tables, idx, act_names, wide_names, also_names=()):
    problems = []
    for tick in act_names:
        row = idx.get(tick)
        if row is None:
            problems.append(f"{tick}: in the actionable table but not in the CSV")
            continue
        passes, boundary = gate_state(row)
        if not passes and not boundary:
            g = num(row.get("premarket_change_pct"))
            p = num(row.get("pct_of_adv"))
            c = num(row.get("mkt_cap_usd"))
            problems.append(f"{tick}: published as ACTIONABLE but |gap|={abs(g):.2f}% / "
                            f"%ADV={p} / cap={c} does not clear the gate (|gap| >= {GATE_GAP_PCT}% "
                            f"AND %ADV >= {GATE_PCT_ADV}% AND cap >= {GATE_MKT_CAP})")
    for tick in wide_names:
        row = idx.get(tick)
        if row is None:
            problems.append(f"{tick}: in the wider screen but not in the CSV")
            continue
        passes, boundary = gate_state(row)
        if passes and not boundary:
            g = num(row.get("premarket_change_pct"))
            p = num(row.get("pct_of_adv"))
            problems.append(f"{tick}: published in the WIDER SCREEN but it clears the gate "
                            f"(|gap|={abs(g):.2f}%, %ADV={p}) — it belongs in the actionable "
                            f"table")
    csv_gate = {t for t, r in idx.items() if gate_state(r)[0]}
    for tick in sorted(csv_gate - set(act_names) - set(also_names)):
        row = idx.get(tick)
        if not gate_state(row)[1]:
            problems.append(f"{tick}: clears the gate in the CSV but is missing from the "
                            f"actionable table — a gate-passing name may not be dropped "
                            f"silently")
    record("GATE", problems,
           f"the actionable table holds only gate-passing names ({len(act_names)}), the "
           f"wider screen the names that fail it ({len(wide_names)}), and every other "
           f"gate-passing name is listed under 'Also cleared the gate' ({len(also_names)})")


# ------------------------------------------------------------------ four-cell
def fourcell_table(tables):
    for t in tables:
        if "gapvscatalyst" in t["subsection"] or "gapvscatalyst" in t["section"]:
            return t
    return None


def parse_cell(cell):
    """-> (count, example_token, rest). The count is the leading integer."""
    s = cell.strip()
    m = re.match(r"^(\d+)\s*(.*)$", s)
    if not m:
        return None, None, s
    count = int(m.group(1))
    rest = re.sub(r"^[—\-–:·|,]\s*", "", m.group(2).strip()).strip()
    m2 = re.match(r"^(?:e\.g\.|eg\.|ex\.)\s*([A-Za-z][A-Za-z0-9.\-]{0,5})", rest)
    if m2:
        return count, m2.group(1), rest
    m3 = re.match(r"^([A-Za-z][A-Za-z0-9.\-]{0,5})\b", rest)
    if m3:
        return count, m3.group(1), rest
    return count, None, rest


def check_fourcell(tables, idx, act_names, wide_names, lines, subsections):
    problems = []
    ex_problems = []
    t = fourcell_table(tables)
    if t is None:
        problems.append("no gap-vs-catalyst table — the brief's real content is the asymmetry "
                        "between a gap, a driver and a tradeable book, and it must be published "
                        "as a 2x2 with counts")
        ex_problems.append("no gap-vs-catalyst table, so no cell carries an example")
        record("FOURCELL", problems, "")
        record("FOURCELL_EX", ex_problems, "")
        return

    hdr = [norm(h) for h in t["headers"]]
    col_idx = {}
    for i, h in enumerate(hdr):
        flat = h.replace(" ", "")
        # "Catalyst sourced" -> the sourced column; "No catalyst" -> the other one.
        # Matching on the words, not on a fixed spelling, so a header that reads
        # "No catalyst", "no-catalyst" or "Without catalyst" still resolves.
        if "catalyst" in flat and "sourced" in flat:
            col_idx["cat"] = i
        elif "catalyst" in flat:
            col_idx["nocat"] = i
    if "cat" not in col_idx or "nocat" not in col_idx:
        problems.append(f"the gap-vs-catalyst table has columns {t['headers']} — it needs a "
                        "catalyst-sourced column and a no-catalyst column")
        ex_problems.append("the gap-vs-catalyst table has no usable columns")
        record("FOURCELL", problems, "")
        record("FOURCELL_EX", ex_problems, "")
        return

    rows = {}
    for r in t["rows"]:
        label = norm(r.get(t["headers"][0], ""))
        if label.startswith("passestheactionablegate") or label.startswith("passesthegate"):
            rows["pass"] = r
        elif label.startswith("failsthegate") or label.startswith("fails"):
            rows["fail"] = r
    if "pass" not in rows or "fail" not in rows:
        problems.append(f"the gap-vs-catalyst table needs a 'passes the actionable gate' row "
                        f"and a 'fails the gate' row — it has {list(rows.keys())}")
        ex_problems.append("the gap-vs-catalyst table has no usable rows")
        record("FOURCELL", problems, "")
        record("FOURCELL_EX", ex_problems, "")
        return

    def catalyst_of(tick):
        row = idx.get(tick)
        if row is None:
            return None
        return (row.get("catalyst") or "").strip()

    expect = {
        ("pass", "cat"): sum(1 for tk in act_names if catalyst_of(tk)),
        ("pass", "nocat"): sum(1 for tk in act_names if catalyst_of(tk) == ""),
        ("fail", "cat"): sum(1 for tk in wide_names if catalyst_of(tk)),
        ("fail", "nocat"): sum(1 for tk in wide_names if catalyst_of(tk) == ""),
    }
    members = {
        ("pass", "cat"): [tk for tk in act_names if catalyst_of(tk)],
        ("pass", "nocat"): [tk for tk in act_names if catalyst_of(tk) == ""],
        ("fail", "cat"): [tk for tk in wide_names if catalyst_of(tk)],
        ("fail", "nocat"): [tk for tk in wide_names if catalyst_of(tk) == ""],
    }

    for rk, r in (("pass", rows["pass"]), ("fail", rows["fail"])):
        for ck in ("cat", "nocat"):
            colname = ck
            values = list(r.values())
            raw_cell = values[col_idx[colname]] if col_idx[colname] < len(values) else ""
            count, example, rest = parse_cell(raw_cell)
            if count is None:
                problems.append(f"the {rk}/{ck} cell ({raw_cell!r}) does not start with a count")
                continue
            if count != expect[(rk, ck)]:
                problems.append(f"the {rk}/{ck} cell publishes {count} but the artifact's own "
                                f"tables imply {expect[(rk, ck)]}")
            if count > 0:
                if not example:
                    ex_problems.append(f"the {rk}/{ck} cell publishes {count} but names no "
                                       f"example")
                elif example.upper() not in members[(rk, ck)]:
                    ex_problems.append(f"the {rk}/{ck} cell quotes {example!r}, which is not in "
                                       f"that cell ({members[(rk, ck)][:6]})")
            elif rest and not re.match(r"^\W*(none|nil|no\b|n/?a|—|-|nothing)\b", rest, re.I):
                ex_problems.append(f"the {rk}/{ck} cell is empty but says {rest!r} instead of "
                                   f"'none'")

    # the universe the table counts
    span = find_span(subsections, "gapvscatalyst")
    if span:
        caption = " ".join(ln.strip() for ln in body_of(lines, span)
                            if ln.strip() and not is_table_row(ln))
        universe = len(act_names) + len(wide_names)
        screen = len(idx)
        nums = [int(x) for x in re.findall(r"\d+", caption)]
        if universe not in nums:
            problems.append(f"the gap-vs-catalyst caption does not state the universe it "
                            f"counts (it should say {universe} names) — {caption[:120]!r}")
        elif screen not in nums:
            problems.append(f"the gap-vs-catalyst caption does not state the size of the "
                            f"screen it draws from (it should say {screen} screen names) — "
                            f"{caption[:120]!r}")
        else:
            ok_msg = (f"the four published counts match the artifact's own tables "
                      f"({expect[('pass', 'cat')]} tradeable / {expect[('pass', 'nocat')]} "
                      f"no driver / {expect[('fail', 'cat')]} missed / "
                      f"{expect[('fail', 'nocat')]} noise), and the caption states the universe "
                      f"({universe} checked names) and the screen it draws from ({screen})")
            record("FOURCELL", problems, ok_msg)
            record("FOURCELL_EX", ex_problems,
                   "every populated cell names an example that really sits in it")
            return
    record("FOURCELL", problems,
           f"the four published counts match the artifact's own tables "
           f"({expect[('pass', 'cat')]} tradeable / {expect[('pass', 'nocat')]} no driver / "
           f"{expect[('fail', 'cat')]} missed / {expect[('fail', 'nocat')]} noise)")
    record("FOURCELL_EX", ex_problems,
           "every populated cell names an example that really sits in it")


# ------------------------------------------------------------------ v4 checks
SUBFLOOR_MAX_PER_SIDE = 5      # the watchlist holds at most 5 rows per direction
ALSO_CLEARED_LINE = "Gate-passing names not in the table above:"


def find_subfloor_tables(tables):
    """The `Below the $200M floor` watchlist tables (a Ticker-first table in a
    subsection whose heading says 'below ... floor')."""
    out = []
    for t in tables:
        s = norm(t["subsection"])
        if "below" in s and "floor" in s and norm(t["headers"][0]) == "ticker":
            out.append(t)
    return out


def check_subfloor(tables, idx, act_names, wide_names):
    """The universe floor must not hide the day's biggest mover.

    The $200M market-cap floor is a LIQUIDITY floor, and it can hide the most
    violent name of the day (measured 2026-11-04: PARA -88.6% on a $1.8M cap,
    CRIS +87.7%, DKI +54.0% — none of them in the brief). The brief therefore
    publishes a watchlist of the names the floor excluded, and this check
    makes that block honest: every name in it is really below the floor, is in
    the CSV, is published nowhere else, and the block cannot be empty while the
    floor hides a bigger mover than the table's own.
    """
    problems = []
    sub_tables = find_subfloor_tables(tables)
    names = []
    for t in sub_tables:
        headers = t["headers"]
        neg = pos = 0
        for r in t["rows"]:
            tick = r.get(headers[0], "").strip()
            if not tick:
                continue
            names.append(tick)
            row = idx.get(tick)
            if row is None:
                problems.append(f"{tick}: published in the below-the-floor watchlist but "
                                f"absent from the CSV")
                continue
            c = num(row.get("mkt_cap_usd"))
            if c is not None and c >= GATE_MKT_CAP:
                problems.append(f"{tick}: published in the below-the-floor watchlist but its "
                                f"market cap is {fmt_mktcap(c)} — that is AT or ABOVE the "
                                f"$200M floor")
            g = num(col(r, headers, "gap"))
            if g is not None:
                if g < 0:
                    neg += 1
                else:
                    pos += 1
                cg = num(row.get("premarket_change_pct"))
                if cg is not None and abs(g - cg) > TOL_1DP:
                    problems.append(f"{tick}: the watchlist publishes gap {g:g}% but the CSV "
                                    f"carries {cg:g}%")
            p_csv = num(row.get("pct_of_adv"))
            cell = (col(r, headers, "pctofadv") or "").strip()
            if p_csv is None:
                if cell not in ("", "-", "—", "n/a"):
                    problems.append(f"{tick}: the CSV has no ADV history (pct_of_adv empty) "
                                    f"but the watchlist publishes {cell!r}")
            else:
                pv = num(cell)
                if pv is None or abs(pv - p_csv) > TOL_1DP:
                    problems.append(f"{tick}: the watchlist publishes %ADV {cell!r} but the CSV "
                                    f"carries {p_csv:g}")
        if neg > SUBFLOOR_MAX_PER_SIDE or pos > SUBFLOOR_MAX_PER_SIDE:
            problems.append(f"the below-the-floor watchlist holds {neg} down and {pos} up "
                            f"names — the contract caps it at {SUBFLOOR_MAX_PER_SIDE} per "
                            f"direction")
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        problems.append(f"{len(dupes)} name(s) appear more than once in the below-the-floor "
                        f"watchlist: {dupes[:10]}")
    clash = sorted(set(names) & (set(act_names) | set(wide_names)))
    if clash:
        problems.append(f"{len(clash)} name(s) are published BOTH in the watchlist and in a "
                        f"screened table: {clash[:10]} — one name, one table")
    # the floor must not hide the day's biggest mover
    below = []
    for tick, row in idx.items():
        g = num(row.get("premarket_change_pct"))
        c = num(row.get("mkt_cap_usd"))
        if g is None or c is None or c >= GATE_MKT_CAP:
            continue
        below.append((abs(g), tick, g))
    act_gaps = []
    for tick in act_names:
        row = idx.get(tick)
        g = num(row.get("premarket_change_pct")) if row else None
        if g is not None:
            act_gaps.append(abs(g))
    act_max = max(act_gaps) if act_gaps else 0.0
    if below:
        worst = max(below)
        if worst[0] > act_max + 1e-9:
            published_max = 0.0
            for tick in names:
                row = idx.get(tick)
                g = num(row.get("premarket_change_pct")) if row else None
                if g is not None:
                    published_max = max(published_max, abs(g))
            if published_max + 1e-9 < worst[0]:
                problems.append(f"the $200M floor hides {worst[1]} ({worst[2]:+.1f}%), a bigger "
                                f"mover than the actionable table's own biggest "
                                f"({act_max:.1f}%), but the watchlist does not publish it")
    record("SUBFLOOR", problems,
           f"the below-the-floor watchlist publishes {len(names)} name(s), all below the "
           f"$200M floor, in the CSV and nowhere else")
    return names


def parse_also_cleared(lines, subsections, idx):
    """(names, declared_count, present) for the `Also cleared the gate` section."""
    span = None
    for name, sp in subsections.items():
        if "alsocleared" in name:
            span = sp
            break
    if not span:
        return set(), None, False
    body = [ln for ln in body_of(lines, span) if ln.strip() and not is_table_row(ln)]
    declared = None
    for ln in body:
        s = ln.strip()
        if s.startswith(ALSO_CLEARED_LINE):
            m = re.search(r"(\d+)", s)
            if m:
                declared = int(m.group(1))
            break
    text = "\n".join(body)
    names = set()
    for tick in idx:
        if re.search(r"(?<![A-Za-z0-9\.\-])" + re.escape(tick) + r"(?![A-Za-z0-9\.\-])", text):
            names.add(tick)
    return names, declared, True


def check_also_cleared(tables, idx, act_names, wide_names, lines, subsections, subfloor_names):
    """A cap may SHORTEN the actionable table; it may never silently drop a name.

    The actionable table is capped per direction (a tape can put 40 names on
    one side). Everything the cap left out is listed by name under
    `Also cleared the gate`, with the count, so the reader can see that the
    table is a triage and not the whole tradeable set.
    """
    problems = []
    names, declared, present = parse_also_cleared(lines, subsections, idx)
    gate_pass = {t for t, r in idx.items() if gate_state(r)[0]}
    expected = gate_pass - set(act_names)
    missing = sorted(expected - names)
    if missing:
        problems.append(f"{len(missing)} gate-passing name(s) are neither in the actionable "
                        f"table nor listed under 'Also cleared the gate': {missing[:10]} — a "
                        f"cap may shorten the table, never silently drop a name")
    extra = sorted(names - expected)
    if extra:
        problems.append(f"'Also cleared the gate' lists {len(extra)} name(s) that do not "
                        f"belong there (they do not clear the gate, or they are already "
                        f"published): {extra[:10]}")
    if present:
        if declared is None:
            problems.append("'Also cleared the gate' does not state its count — the section "
                            f"must carry a line reading '{ALSO_CLEARED_LINE} <N>'")
        elif declared != len(names):
            problems.append(f"'Also cleared the gate' declares {declared} names but lists "
                            f"{len(names)}")
    elif expected:
        problems.append(f"{len(expected)} gate-passing name(s) are outside the actionable table "
                        f"but there is no 'Also cleared the gate' section")
    clash = sorted(set(names) & (set(act_names) | set(wide_names) | set(subfloor_names)))
    if clash:
        problems.append(f"{len(clash)} name(s) are listed under 'Also cleared the gate' and "
                        f"also published in a table: {clash[:10]}")
    record("ALSO_CLEARED", problems,
           f"every gate-passing name outside the actionable table is listed by name "
           f"({len(names)} listed, {len(expected)} expected)")


def check_reply(path, total):
    with open(path, encoding="utf-8", errors="replace") as fh:
        raw = fh.read()
    m = re.search(r"contract:\s*(\d+)\s*/\s*(\d+)", raw, re.I)
    if not m:
        print("  FAIL [REPLY] the reply publishes no `contract: N/N` line — the reader must be "
              "able to see the artifact was verified rather than assumed")
        return False
    if int(m.group(1)) != total or int(m.group(2)) != total:
        print(f"  FAIL [REPLY] the reply publishes contract: {m.group(1)}/{m.group(2)} but the "
              f"checker ran {total} checks")
        return False
    print(f"  ok   [REPLY] the reply publishes contract: {total}/{total}")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", required=True)
    ap.add_argument("--csv", required=True)
    ap.add_argument("--reply", default=None)
    args = ap.parse_args()

    for p in (args.md, args.csv):
        if not os.path.exists(p):
            print(f"FAIL missing file: {p}")
            sys.exit(2)

    with open(args.md, encoding="utf-8", errors="replace") as fh:
        lines = fh.read().split("\n")
    sections, subsections, tables = parse_markdown(lines)
    idx = csv_index(args.csv)

    print(f"[markdown] {args.md}")
    print(f"[csv]      {args.csv}")
    print()

    check_sections(lines, sections)
    check_section_empty(lines, sections)
    check_no_catalysts(sections)
    act_names, wide_names = check_one_name_once(tables)
    check_csv_contract(args.csv)
    check_md_csv_agree(tables, idx)
    check_pct_adv(args.csv)
    check_mktcap(tables, idx)
    check_noise_flag(args.csv)
    check_tldr(lines, sections)
    subfloor_names = check_subfloor(tables, idx, act_names, wide_names)
    also_names, _declared, _present = parse_also_cleared(lines, subsections, idx)
    check_gate(tables, idx, act_names, wide_names, also_names)
    check_also_cleared(tables, idx, act_names, wide_names, lines, subsections, subfloor_names)
    check_fourcell(tables, idx, act_names, wide_names, lines, subsections)

    print()
    failed = [n for n, good in RESULTS if not good]
    reply_ok = True
    if args.reply:
        if os.path.exists(args.reply):
            reply_ok = check_reply(args.reply, CONTRACT_CHECKS)
        else:
            print(f"  FAIL [REPLY] reply file not found: {args.reply}")
            reply_ok = False
    else:
        print("  --   [REPLY] no --reply given; the reply's contract line was not checked")

    if failed or not reply_ok:
        print()
        print(f"CONTRACT FAILED — {len(failed)} of {CONTRACT_CHECKS} checks failed:")
        for f in FAILURES:
            print(f"  - {f}")
        if not reply_ok:
            print("  - [REPLY] the reply does not publish the contract count")
        sys.exit(1)
    print(f"CONTRACT OK — contract: {CONTRACT_CHECKS}/{CONTRACT_CHECKS} ({CONTRACT_VERSION})")
    sys.exit(0)


if __name__ == "__main__":
    main()
