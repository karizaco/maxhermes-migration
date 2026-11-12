#!/usr/bin/env python3
"""
check_bonde_artifact.py — assert the cron #04 artifact contract. Do not eyeball it.

The 2026-11-03 run produced a correct screen and a reader-hostile document: the
stop-vs-bar-low conflict was disclosed only in prose under `Method & caveats`, the
volume-conviction fact was a sentence in the review, there was no invalidation line,
and the promoted/not-promoted verdict sat 100 lines down. This script turns the
acceptance criteria into machine assertions, so a run that breaks the contract FAILS
instead of shipping.

USAGE
    python3 check_bonde_artifact.py --md daily-screens/<date>/reversal-bullish-3_55.md \
                                    --csv daily-screens/<date>/reversal-bullish-3_55.csv \
                                    [--reply <reply.txt>]

Exit codes: 0 = contract satisfied; 1 = at least one FAIL (each is printed).
"""

import argparse
import csv
import os
import re
import sys

SKELETON = ["TL;DR", "Candidates", "Promoted ideas", "Not promoted",
            "Bonde gate matrix", "Filter funnel", "Method, source health & caveats"]

REQUIRED_CSV_COLS = ["bar_low", "bar_high", "stop_class", "vol_vs_30d_avg_pct",
                     "capitulation", "stop_vs_bar_low_pct", "stop_capped",
                     "bar_low_vs_entry_pct", "invalidation_level"]
REQUIRED_CSV_VALUES = ["bar_low", "bar_high", "stop_class", "vol_vs_30d_avg_pct",
                       "capitulation"]
# v4 (2026-11-12) publishes BOTH stop levels, because Bonde's default is the body low and the
# shadow low is his sanctioned alternative. The columns are only required from v4 on.
V4_CSV_COLS = ["body_low", "body_stop_pct", "shadow_stop_pct", "body_stop_degenerate",
               "stop_placement"]
V4_CSV_VALUES = ["body_low", "body_stop_pct", "shadow_stop_pct", "body_stop_degenerate",
                 "stop_placement"]
STOP_CLASSES = {"STRUCTURAL", "BODY_LOW", "CAPPED", "NO_LEGAL_STOP",
                "NOISE_BREACH"}          # NOISE_BREACH: legacy v3 vocabulary
CAPITULATION_CLASSES = {"CAPITULATION", "LOW_VOLUME", "UNKNOWN"}
CONTRACT_VERSION = "bonde-artifact-v4"
LEGACY_CONTRACT_VERSIONS = {"bonde-artifact-v3"}
STOP_MAX_PCT = 2.5

# display-label aliases for the markdown table headers
MD_HEADER_ALIASES = {
    "bar_low": ("barlow",),
    "bar_high": ("barhigh",),
    "stop_class": ("stopclass",),
    "vol_vs_30d_avg_pct": ("volvs30davg",),
    "capitulation": ("capitulation",),
}

FAILURES = []

def resolve_bonde_path(path):
    """Prefer the Windows-safe 3_55 name; fall back to historical 3:55."""
    if path and os.path.exists(path):
        return path
    if not path:
        return path
    alt = path.replace("reversal-bullish-3_55", "reversal-bullish-3:55")
    if alt != path and os.path.exists(alt):
        return alt
    alt2 = path.replace("reversal-bullish-3:55", "reversal-bullish-3_55")
    if alt2 != path and os.path.exists(alt2):
        return alt2
    return path
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


def strip_fences(lines):
    """Return the lines that are NOT inside a fenced code block."""
    out, inside = [], False
    for ln in lines:
        if ln.strip().startswith("```"):
            inside = not inside
            continue
        if not inside:
            out.append(ln)
    return out


def sections(lines):
    """Map '## Heading' -> (start_index, end_index) over the whole document."""
    heads = []
    for i, ln in enumerate(lines):
        m = re.match(r"^##\s+(.*?)\s*$", ln)
        if m:
            heads.append((i, m.group(1).strip()))
    out = {}
    for n, (i, name) in enumerate(heads):
        end = heads[n + 1][0] if n + 1 < len(heads) else len(lines)
        out[name] = (i, end)
    return out


def section_lines(lines, secs, name):
    if name not in secs:
        return []
    i, j = secs[name]
    return lines[i + 1:j]


def candidates_table(lines, secs):
    """Parse the Candidates table -> (headers, rows) where rows are dicts."""
    body = section_lines(lines, secs, "Candidates")
    headers, rows = None, []
    for ln in body:
        if not ln.strip().startswith("|"):
            if headers:
                break
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
    return headers or [], rows


def promoted_blocks(body):
    """Split the Promoted ideas section into one block per '✅ IDEA' heading."""
    blocks, cur = [], None
    for ln in body:
        if "✅" in ln and re.search(r"IDEA", ln, re.I):
            cur = [ln]
            blocks.append(cur)
        elif cur is not None:
            cur.append(ln)
    return blocks


def check_md(path):
    print(f"[markdown] {path}")
    with open(path) as fh:
        raw = fh.read()
    lines = raw.split("\n")
    secs = sections(lines)

    # --- 1. the skeleton is fixed and in order ---------------------------------
    found = list(sections(lines).keys())
    if found == SKELETON:
        ok(f"section skeleton is the contract's, in order ({len(found)} sections)")
    else:
        bad(f"section skeleton mismatch\n         expected: {SKELETON}\n         found:    {found}")

    # --- 2. the verdict is reachable in the first 15 lines --------------------
    head = "\n".join(lines[:15])
    if re.search(r"Ideas promoted:\s*\d+", head):
        ok("the 'Ideas promoted' verdict is reachable within the first 15 lines")
    else:
        bad("the 'Ideas promoted' verdict is NOT reachable within the first 15 lines")

    # --- 3. TL;DR: exactly three bullets, and the count parses ----------------
    tldr = section_lines(lines, secs, "TL;DR")
    bullets = [ln for ln in tldr if re.match(r"^\s*[-*]\s+\S", ln)]
    if len(bullets) == 3:
        ok("the TL;DR has exactly 3 bullets")
    else:
        bad(f"the TL;DR must have exactly 3 bullets, found {len(bullets)}")
    m = re.search(r"Ideas promoted:\s*(\d+)", "\n".join(tldr))
    if not m:
        bad("the TL;DR has no parseable 'Ideas promoted: N' count")
        tldr_count = None
    else:
        tldr_count = int(m.group(1))
        ok(f"the TL;DR publishes 'Ideas promoted: {tldr_count}'")

    # --- 4. the artifact was produced by a known script version ----------------
    strict = CONTRACT_VERSION in raw
    if strict:
        ok(f"the artifact carries the current contract marker ({CONTRACT_VERSION})")
    elif any(v in raw for v in LEGACY_CONTRACT_VERSIONS):
        ok(f"the artifact carries the LEGACY contract marker "
           f"({sorted(v for v in LEGACY_CONTRACT_VERSIONS if v in raw)[0]}) — the v4 stop-rule "
           f"assertions are skipped for it")
    else:
        bad(f"the artifact does NOT carry a known contract marker ({CONTRACT_VERSION}) — it was "
            f"produced by an older copy of tools/reversal_bullish.py (a stale CDN cache). "
            f"Re-fetch the script and re-run it.")

    # --- 5. no review marker survived ----------------------------------------
    leftover = re.findall(r"<!--\s*REVIEW:[A-Z_]+", raw)
    if leftover:
        bad(f"an unreviewed placeholder is still in the artifact: {sorted(set(leftover))}")
    else:
        ok("no unreviewed placeholder markers left")

    # --- 6. promoted blocks vs the TL;DR count --------------------------------
    body = strip_fences(section_lines(lines, secs, "Promoted ideas"))
    blocks = promoted_blocks(body)
    if tldr_count is not None:
        if len(blocks) == tldr_count:
            ok(f"promoted-block count matches the TL;DR count ({len(blocks)})")
        else:
            bad(f"promoted-block count ({len(blocks)}) != TL;DR count ({tldr_count})")

    # --- 7. every promoted idea carries an invalidation test ------------------
    for n, blk in enumerate(blocks, 1):
        text = "\n".join(blk)
        head_line = blk[0].strip()
        if re.search(r"invalidat", text, re.I):
            ok(f"promoted idea {n} states its invalidation test")
        else:
            bad(f"promoted idea {n} has no invalidation test: {head_line}")
        if re.search(r"stop[_ ]?class|NOISE_BREACH|STRUCTURAL|CAPPED", text, re.I):
            ok(f"promoted idea {n} states its stop class")
        else:
            bad(f"promoted idea {n} does not state its stop_class: {head_line}")

    # --- 8. the candidates table carries the required columns -----------------
    headers, rows = candidates_table(lines, secs)
    hnorm = [norm(h) for h in headers]
    for col, aliases in MD_HEADER_ALIASES.items():
        if any(any(a in hn for a in aliases) for hn in hnorm):
            ok(f"the Candidates table has a '{col}' column")
        else:
            bad(f"the Candidates table is missing the '{col}' column")
    for n, r in enumerate(rows, 1):
        empty = [c for c in REQUIRED_CSV_VALUES
                 if not any(any(a in norm(h) for a in MD_HEADER_ALIASES[c])
                            and str(r.get(h, "")).strip() for h in headers)]
        if empty:
            bad(f"candidate row {n} has empty required cells: {empty}")
    if rows:
        ok(f"every candidate row ({len(rows)}) carries bar_low / bar_high / stop_class / "
           f"vol_vs_30d_avg_pct")
    if strict:
        # --- v4: both stop levels must be visible, and the published stop must be real
        for col, aliases in {"body_low": ("bodylow",), "stop_basis": ("stopbasis",)}.items():
            if any(any(a in hn for a in aliases) for hn in hnorm):
                ok(f"the Candidates table has a '{col}' column")
            else:
                bad(f"the Candidates table is missing the '{col}' column")
        for n, r in enumerate(rows, 1):
            cells = [str(r.get(h, "")).strip() for h in headers]
            if not all(cells):
                bad(f"candidate row {n} has an empty cell in a required column")

    # --- 9. every non-promoted candidate is accounted for ---------------------
    promoted_tickers = set()
    for blk in blocks:
        for t in re.findall(r"\b[A-Z]{1,5}\b", blk[0]):
            promoted_tickers.add(t)
    cand_tickers = []
    for r in rows:
        for h in headers:
            if norm(h) == "ticker":
                cand_tickers.append(str(r.get(h, "")).strip().strip("*"))
                break
    notprom = "\n".join(strip_fences(section_lines(lines, secs, "Not promoted")))
    for t in cand_tickers:
        if not t or t in promoted_tickers:
            continue
        if re.search(rf"\b{re.escape(t)}\b", notprom):
            if re.search(r"invalidat", notprom, re.I):
                ok(f"not-promoted candidate {t} is accounted for with an invalidation test")
            else:
                bad(f"not-promoted candidate {t} has no invalidation test")
        else:
            bad(f"candidate {t} appears in neither 'Promoted ideas' nor 'Not promoted'")
    return rows, cand_tickers, promoted_tickers, strict


def check_csv(path, md_rows, md_tickers, strict=False):
    print(f"[csv] {path}")
    with open(path, newline="") as fh:
        rdr = csv.DictReader(fh)
        cols = rdr.fieldnames or []
        rows = list(rdr)
    required = REQUIRED_CSV_COLS + (V4_CSV_COLS if strict else [])
    values = REQUIRED_CSV_VALUES + (V4_CSV_VALUES if strict else [])
    missing = [c for c in required if c not in cols]
    if missing:
        bad(f"the CSV header is missing required columns: {missing}")
    else:
        ok(f"the CSV header carries all required columns ({len(cols)} columns)")
    for n, r in enumerate(rows, 1):
        empties = [c for c in values if not str(r.get(c, "")).strip()]
        if empties:
            bad(f"CSV row {n} ({r.get('ticker')}) has empty required cells: {empties}")
        sc = str(r.get("stop_class", "")).strip().upper()
        if sc and sc not in STOP_CLASSES:
            bad(f"CSV row {n} ({r.get('ticker')}) has an invalid stop_class: {sc}")
        cap = str(r.get("capitulation", "")).strip().upper()
        if cap and cap not in CAPITULATION_CLASSES:
            bad(f"CSV row {n} ({r.get('ticker')}) has an invalid capitulation flag: {cap}")
    if strict:
        check_stop_rule(rows)
    if rows:
        ok(f"every CSV row ({len(rows)}) carries bar_low / bar_high / stop_class / "
           f"vol_vs_30d_avg_pct")
    csv_tickers = [str(r.get("ticker", "")).strip() for r in rows]
    if sorted(csv_tickers) == sorted([t for t in md_tickers if t]):
        ok("the CSV and the markdown carry the same candidate set")
    else:
        bad(f"the CSV candidates {csv_tickers} differ from the markdown {md_tickers}")
    return rows


def check_stop_rule(rows):
    """v4: the published stop must be a REAL, legal stop that follows Bonde's rule.

    Bonde's default is the low of the signal candle's BODY; the shadow (bar) low is his
    sanctioned ALTERNATIVE and is legal only within 2.5% of the entry. So:

      * a body low that is degenerate (it sits on the entry) forces the shadow low;
      * a body low that is usable stands, and the shadow must NOT be substituted for it
        (a shadow more than 2.5% away is not a legal stop at all);
      * a published stop at the entry (0.00% risk) is not a stop - it must be NO_LEGAL_STOP.
    """
    print("[stop-rule] Bonde's body-low default / shadow alternative / 2.5% cap")
    for n, r in enumerate(rows, 1):
        t = r.get("ticker")
        try:
            entry = float(r.get("entry_price"))
            stop = float(r.get("stop"))
            body_low = float(r.get("body_low"))
            bar_low = float(r.get("bar_low"))
            body_pct = float(r.get("body_stop_pct"))
            shadow_pct = float(r.get("shadow_stop_pct"))
        except (TypeError, ValueError):
            bad(f"CSV row {n} ({t}) has a non-numeric stop field")
            continue
        sc = str(r.get("stop_class", "")).strip().upper()
        basis = str(r.get("stop_basis", "")).strip().lower()
        degen = str(r.get("body_stop_degenerate", "")).strip().lower() == "yes"
        tol = 0.011
        if sc == "NO_LEGAL_STOP":
            ok(f"{t}: NO_LEGAL_STOP is published (no stop Bonde's rule accepts)")
        elif stop >= entry - tol:
            bad(f"{t}: the published stop {stop} is not below the entry {entry} — a 0.00% risk "
                f"line is not a stop (class {sc})")
        else:
            ok(f"{t}: the published stop {stop} is {entry - stop:.2f} below the entry "
               f"({(entry - stop) / entry * 100:.2f}%)")
        if degen and sc != "NO_LEGAL_STOP":
            if abs(stop - bar_low) > tol:
                bad(f"{t}: the body low is degenerate (it sits on the entry) but the published "
                    f"stop {stop} is not the shadow low {bar_low}")
            else:
                ok(f"{t}: a degenerate body low forces the shadow low ({bar_low})")
        if not degen and sc not in ("NO_LEGAL_STOP", "CAPPED"):
            if abs(stop - body_low) > tol:
                bad(f"{t}: the body low is usable ({body_low}) but the published stop is {stop} — "
                    f"Bonde's default is the body low; the shadow low may only be substituted when "
                    f"the body low is degenerate")
            else:
                ok(f"{t}: the published stop is Bonde's default body low ({body_low})")
        if "shadow" in basis and shadow_pct > STOP_MAX_PCT + 0.001:
            bad(f"{t}: the shadow low is {shadow_pct:.2f}% from the entry — over Bonde's "
                f"{STOP_MAX_PCT}% cap, so it is not a legal stop")
        if "no legal stop" in basis and sc != "NO_LEGAL_STOP":
            bad(f"{t}: the basis says there is no legal stop but the class is {sc}")
        if (entry - stop) / entry * 100 > STOP_MAX_PCT + 0.05:
            bad(f"{t}: the published stop is {(entry - stop) / entry * 100:.2f}% from the entry — "
                f"over Bonde's {STOP_MAX_PCT}% max loss")


def check_reply(path, csv_rows, promoted_tickers):
    print(f"[reply] {path}")
    with open(path) as fh:
        raw = fh.read()
    lines = raw.split("\n")
    # The risk line belongs in the SIGNAL section, not in the caveats. Bound the
    # region at the next heading — a 40-line window would swallow the caveats.
    start, end = None, len(lines)
    for i, ln in enumerate(lines):
        if re.match(r"^\s*#{2,4}\s*Signal", ln, re.I):
            start = i
            break
    if start is not None:
        for j in range(start + 1, min(len(lines), start + 60)):
            if re.match(r"^\s*#{2,4}\s", lines[j]):
                end = j
                break
        region = "\n".join(lines[start:end])
    else:
        region = "\n".join(lines[:40])
    for r in csv_rows:
        t = str(r.get("ticker", "")).strip()
        if t not in promoted_tickers:
            continue
        sc = str(r.get("stop_class", "")).strip().upper()
        if sc == "NO_LEGAL_STOP":
            bad(f"promoted name {t} has NO_LEGAL_STOP — a name with no legal stop cannot be "
                f"promoted")
            continue
        if sc != "BODY_LOW":
            continue
        if re.search(rf"\b{re.escape(t)}\b", region) and re.search(r"body[ _-]?low|inside the (signal )?bar", region, re.I):
            ok(f"promoted BODY_LOW name {t} has its risk line in the signal section")
        else:
            bad(f"promoted BODY_LOW name {t} has NO risk line in the signal section (the stop is "
                f"INSIDE the signal bar's range and may only be explained under "
                f"'Method & caveats')")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", required=True)
    ap.add_argument("--csv", required=True)
    ap.add_argument("--reply", default=None)
    args = ap.parse_args()
    args.md = resolve_bonde_path(args.md)
    args.csv = resolve_bonde_path(args.csv)

    for p in (args.md, args.csv):
        if not os.path.exists(p):
            print(f"FAIL missing file: {p}")
            sys.exit(1)

    md_rows, md_tickers, promoted_tickers, strict = check_md(args.md)
    csv_rows = check_csv(args.csv, md_rows, md_tickers, strict=strict)
    if args.reply and os.path.exists(args.reply):
        check_reply(args.reply, csv_rows, promoted_tickers)

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
