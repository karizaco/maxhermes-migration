#!/usr/bin/env python3
"""
check_premarket_artifact.py — assert the cron #08 pre-market-gapper artifact contract.

Do not eyeball it. The 2026-11-03 run was mechanically correct and reader-hostile:
the most valuable finding of the run (PURR straddling the 4% bar — the tape said +3.07%,
the live quote said +4.43%, and the pre-market high said +5.87%) lived in a prose
paragraph; the size rule that killed three phantom gappers (CAI +5.53% on 10 shares,
CVI -6.99% on 1 share, MTZ +3.93% on 1-share prints) was a sentence; and the best setup
in the scan (CDNA, five origins / three stylists) went nowhere and appeared nowhere in
the reply. This script turns those acceptance criteria into machine assertions, so a
run that breaks the contract FAILS instead of shipping.

USAGE
    python3 check_premarket_artifact.py --md daily-screens/<date>/pre-market-gapper.md \
                                        --csv daily-screens/<date>/pre-market-gapper.csv \
                                        [--reply <reply.txt>]

Exit codes: 0 = contract satisfied; 1 = at least one FAIL (each is printed).
"""

import argparse
import csv
import os
import re
import sys

# ---- the published constants (they live in the skill spec; keep the two in sync) ----
GAP_TRIGGER_PCT = 4.0
MIN_PM_VOLUME_SHARES = 50_000
MIN_EXECUTED_SHARES = 25

CONTRACT_VERSION = "premarket-artifact-v5"

VERDICTS = {
    "FLAGGED",              # clears on the tape AND size
    "BORDERLINE_THIN",      # the bar was printed, but the market behind it is too thin
    "BORDERLINE_TAPE_ONLY",  # clears on the live quote, not on the executed tape
    "BORDERLINE_INTRADAY",   # crossed the bar intraday, not at the snapshot
    "NO_PRINT",              # no executed print at all
    "BELOW",                 # printed, but below the bar on every reading
}

# required sections, in order. Matched by normalized prefix so a dated or annotated
# heading ("## Focus scan — all 12 names") still satisfies the contract.
REQUIRED_SECTIONS = [
    "tldr",
    "focusscan",
    "focusnamesthatdidnotqualify",
    "flags",
    "methodsourcehealthcaveats",
]

# required CSV columns
REQUIRED_CSV_COLS = [
    "ticker", "ref_close", "ref_close_source", "pm_gap_pct", "pm_volume",
    "exec_shares", "exec_notional", "verdict",
    # v5: the universe's own date and the denominator's session are published
    # per row - a gap without its session is an unanchored number.
    "universe_date", "ref_close_date", "universe_source",
]
# columns that must carry a value on EVERY row. `pm_gap_pct` and `pm_volume` are
# deliberately NOT here: a name with no executed print (NO_PRINT) has no gap and no
# volume, and inventing one would be a worse lie than an empty cell.
REQUIRED_CSV_VALUES = ["ticker", "ref_close", "ref_close_source", "exec_shares", "verdict",
                       "universe_date", "ref_close_date", "universe_source"]

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


def sections(lines):
    """Map '## Heading' -> (start, end) over the whole document."""
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


def find_section(secs, key):
    """Return (name, (start, end)) for the first section whose normalized heading
    starts with `key`, else None."""
    for name, span in secs.items():
        if norm(name).startswith(key):
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


def md_table(body):
    """Parse the first markdown table in `body` -> (headers, rows)."""
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


def marker_line(raw):
    """The one-line contract header the artifact must carry."""
    for ln in raw.split("\n")[:40]:
        if "contract:" in ln.lower() and "flagged:" in ln.lower():
            return ln
    return None


def parse_marker(ln):
    ver = re.search(r"contract:\s*(premarket-artifact-v\d+)", ln, re.I)
    flagged = re.search(r"flagged:\s*(\d+)", ln, re.I)
    scanned = re.search(r"scanned:\s*(\d+)", ln, re.I)
    return (ver.group(1) if ver else None,
            int(flagged.group(1)) if flagged else None,
            int(scanned.group(1)) if scanned else None)


def check_md(path):
    print(f"[markdown] {path}")
    with open(path, encoding="utf-8", errors="replace") as fh:
        raw = fh.read()
    lines = raw.split("\n")
    secs = sections(lines)

    # --- 1. the required sections, in order -----------------------------------
    found = [norm(name) for name in secs]
    positions = []
    for key in REQUIRED_SECTIONS:
        hit = find_section(secs, key)
        if not hit:
            bad(f"the artifact is missing the required section '{key}'")
            positions.append(None)
        else:
            positions.append(hit[1][0])
    present = [p for p in positions if p is not None]
    if len(present) == len(REQUIRED_SECTIONS):
        if present == sorted(present):
            ok(f"the required sections are present and in order ({len(present)})")
        else:
            bad("the required sections are present but OUT OF ORDER — the contract's order is "
                + " -> ".join(REQUIRED_SECTIONS))

    # --- 2. the contract marker ------------------------------------------------
    ml = marker_line(raw)
    if not ml:
        bad("the artifact carries no contract marker line — expected a line with "
            f"`contract: {CONTRACT_VERSION} ... flagged: N ... scanned: M`")
        ver = flagged = scanned = None
    else:
        ver, flagged, scanned = parse_marker(ml)
        if ver == CONTRACT_VERSION:
            ok(f"the artifact carries the current contract marker ({ver})")
        elif ver and ver < CONTRACT_VERSION:
            # A HISTORICAL artifact built under an older contract is not a defect.
            # The v5 clauses (the universe/date assertion) are not applied to it.
            ok(f"the artifact carries the older contract marker ({ver}) — the v5 universe "
               f"clauses are not applied to a pre-v5 artifact")
        else:
            bad(f"the artifact carries contract '{ver}', expected '{CONTRACT_VERSION}' — it was "
                f"produced by an older copy of the script or the spec. Re-read the skill spec "
                f"and rebuild it.")
        if flagged is not None:
            ok(f"the marker line publishes the flagged count ({flagged})")
        else:
            bad("the marker line has no parseable `flagged: N` count")
        if scanned is not None:
            ok(f"the marker line publishes the scanned count ({scanned})")
        else:
            bad("the marker line has no parseable `scanned: N` count")

    # --- 3. the scan table carries a verdict column and every CSV name ---------
    scan_body = strip_fences(section_body(lines, secs, "focusscan"))
    headers, rows = md_table(scan_body)
    if not headers:
        bad("the Focus scan section has no markdown table")
        rows = []
    else:
        hnorm = [norm(h) for h in headers]
        if any("verdict" in h for h in hnorm):
            ok("the Focus scan table has a 'Verdict' column")
        else:
            bad("the Focus scan table has NO 'Verdict' column — the verdict is a first-class "
                "field, not something the reader has to infer from two numbers")
        for col in ("gap", "exec", "volume"):
            if any(col in h for h in hnorm):
                ok(f"the Focus scan table has a '{col}' column")
            else:
                bad(f"the Focus scan table is missing the '{col}' column")
    return lines, secs, rows, ver, flagged, scanned


def check_csv(path, md_rows, md_verdict_flagged, md_scanned, version=CONTRACT_VERSION):
    print(f"[csv] {path}")
    with open(path, newline="", encoding="utf-8") as fh:
        rdr = csv.DictReader(fh)
        cols = rdr.fieldnames or []
        rows = list(rdr)
    req = list(REQUIRED_CSV_COLS)
    if version != CONTRACT_VERSION:
        req = [c for c in req if c not in ("universe_date", "ref_close_date", "universe_source")]
    missing = [c for c in req if c not in cols]
    if missing:
        bad(f"the CSV header is missing required columns: {missing}")
    else:
        ok(f"the CSV header carries all required columns ({len(cols)} columns)")
    if not rows:
        bad("the CSV has no data rows")
        return rows

    req_vals = list(REQUIRED_CSV_VALUES)
    if version != CONTRACT_VERSION:
        req_vals = [c for c in req_vals
                    if c not in ("universe_date", "ref_close_date", "universe_source")]
    for n, r in enumerate(rows, 1):
        tick = str(r.get("ticker", "")).strip()
        empties = [c for c in req_vals if not str(r.get(c, "")).strip()]
        if empties:
            bad(f"CSV row {n} ({tick}) has empty required cells: {empties}")
        v = str(r.get("verdict", "")).strip().upper()
        if v and v not in VERDICTS:
            bad(f"CSV row {n} ({tick}) has an invalid verdict: {v} "
                f"(allowed: {', '.join(sorted(VERDICTS))})")
        es = num(r.get("exec_shares"))
        if es is None:
            bad(f"CSV row {n} ({tick}) has a non-numeric exec_shares: "
                f"{r.get('exec_shares')!r}")
        else:
            if es < 0:
                bad(f"CSV row {n} ({tick}) has a negative exec_shares: {es}")
            en = num(r.get("exec_notional"))
            if en is not None and es > 0 and en <= 0:
                bad(f"CSV row {n} ({tick}) has exec_shares={es:g} but exec_notional={en:g}")
    ok(f"every CSV row ({len(rows)}) carries verdict / exec_shares / ref_close_source")

    # --- the gate arithmetic -------------------------------------------------
    def row_flag(r):
        g = num(r.get("pm_gap_pct"))
        vol = num(r.get("pm_volume"))
        es = num(r.get("exec_shares"))
        if g is None or vol is None or es is None:
            return False
        return (abs(g) >= GAP_TRIGGER_PCT and vol >= MIN_PM_VOLUME_SHARES
                and es >= MIN_EXECUTED_SHARES)

    flagged_rows = [r for r in rows
                    if str(r.get("verdict", "")).strip().upper() == "FLAGGED"]
    should_flag = [r for r in rows if row_flag(r)]

    for r in flagged_rows:
        tick = str(r.get("ticker", "")).strip()
        g = num(r.get("pm_gap_pct"))
        vol = num(r.get("pm_volume"))
        es = num(r.get("exec_shares"))
        why = []
        if g is None or abs(g) < GAP_TRIGGER_PCT:
            why.append(f"gap {r.get('pm_gap_pct')} < {GAP_TRIGGER_PCT}%")
        if vol is None or vol < MIN_PM_VOLUME_SHARES:
            why.append(f"volume {r.get('pm_volume')} < {MIN_PM_VOLUME_SHARES:,}")
        if es is None or es < MIN_EXECUTED_SHARES:
            why.append(f"exec_shares {r.get('exec_shares')} < {MIN_EXECUTED_SHARES}")
        if why:
            bad(f"row {tick} is FLAGGED but fails the gate: {'; '.join(why)} — a name below the "
                f"published minimum is never counted as a flag")

    thin = [r for r in rows
            if (num(r.get("exec_shares")) is not None
                and num(r.get("exec_shares")) < MIN_EXECUTED_SHARES
                and str(r.get("verdict", "")).strip().upper() == "FLAGGED")]
    if thin:
        bad(f"{len(thin)} row(s) with exec_shares < {MIN_EXECUTED_SHARES} are counted as flags")

    if len(flagged_rows) == len(should_flag):
        ok(f"count(FLAGGED) == count(rows where |gap|>={GAP_TRIGGER_PCT} and "
           f"pm_volume>={MIN_PM_VOLUME_SHARES:,} and exec_shares>={MIN_EXECUTED_SHARES}) "
           f"= {len(flagged_rows)}")
    else:
        bad(f"count(FLAGGED)={len(flagged_rows)} != count(rows meeting the gate)="
            f"{len(should_flag)} — a name that clears the gate is not marked FLAGGED, or a name "
            f"that fails it is")

    # --- the marker count must agree with the data ----------------------------
    if md_verdict_flagged is not None and md_verdict_flagged != len(flagged_rows):
        bad(f"the marker line says flagged: {md_verdict_flagged} but the CSV has "
            f"{len(flagged_rows)} FLAGGED row(s)")
    if md_scanned is not None and md_scanned != len(rows):
        bad(f"the marker line says scanned: {md_scanned} but the CSV has {len(rows)} row(s)")

    # --- the markdown table and the CSV must carry the same set ---------------
    md_tickers = []
    for r in md_rows:
        for h in (r.keys() or []):
            if norm(h) in ("ticker", "symbol", "name"):
                md_tickers.append(str(r.get(h, "")).strip().strip("*"))
                break
    csv_tickers = [str(r.get("ticker", "")).strip() for r in rows]
    if sorted(md_tickers) == sorted([t for t in csv_tickers if t]):
        ok("the CSV and the markdown scan table carry the same name set")
    else:
        bad(f"the markdown scan table {sorted(md_tickers)} differs from the CSV "
            f"{sorted(csv_tickers)}")
    return rows


def check_nonqualifying(lines, secs, rows):
    """`## Focus names that did not qualify` must carry every non-flagged name,
    with its screen provenance and a setup verdict."""
    print("[section] Focus names that did not qualify")
    body = strip_fences(section_body(lines, secs, "focusnamesthatdidnotqualify"))
    if not body:
        bad("the 'Focus names that did not qualify' section is empty")
        return []
    text = "\n".join(body)
    nonflag = [r for r in rows if str(r.get("verdict", "")).strip().upper() != "FLAGGED"]
    if not nonflag:
        ok("every scanned name is FLAGGED — the section has nothing to list")
        return []
    for r in nonflag:
        tick = str(r.get("ticker", "")).strip()
        if not tick:
            continue
        if not re.search(rf"\b{re.escape(tick)}\b", text):
            bad(f"non-qualifying name {tick} does not appear in the section")
            continue
        origins = [o.strip() for o in str(r.get("origins", "")).split(";") if o.strip()]
        if origins:
            missing = [o for o in origins if o not in text]
            if missing:
                bad(f"non-qualifying name {tick} is missing its screen provenance: {missing}")
            else:
                ok(f"non-qualifying name {tick} carries its screen provenance")
        else:
            bad(f"non-qualifying name {tick} has no `origins` value in the CSV, so its screen "
                f"provenance cannot be published")
        if not re.search(r"setup", text, re.I):
            bad(f"the section states no setup verdict — every non-qualifying name needs one "
                f"line saying whether it was a good setup that went nowhere or a bad setup")
            break
    else:
        ok("every non-qualifying name appears in the section")
    return nonflag


def check_flags(lines, secs, rows):
    """`## Flags` carries the per-name suspect numbers — the thin prints."""
    print("[section] Flags")
    body = strip_fences(section_body(lines, secs, "flags"))
    if not body:
        bad("the '## Flags' section is empty — per-name suspect numbers belong there")
        return
    text = "\n".join(body)
    suspects = []
    for r in rows:
        es = num(r.get("exec_shares"))
        g = num(r.get("pm_gap_pct"))
        if es is None or g is None:
            continue
        if es < MIN_EXECUTED_SHARES and abs(g) >= GAP_TRIGGER_PCT:
            suspects.append(str(r.get("ticker", "")).strip())
    for tick in suspects:
        if re.search(rf"\b{re.escape(tick)}\b", text):
            ok(f"thin print {tick} (exec_shares < {MIN_EXECUTED_SHARES}) is named in Flags")
        else:
            bad(f"thin print {tick} (exec_shares < {MIN_EXECUTED_SHARES}) is NOT named in the "
                f"Flags section — a print that small is a per-name suspect number")


def ranking(rows):
    """The non-qualifying names ordered by setup quality: stylists desc, then
    origins desc, then |gap| desc. The spec states this order; the reply must
    name the top 2."""
    def key(r):
        st = num(r.get("stylists")) or 0
        og = len([o for o in str(r.get("origins", "")).split(";") if o.strip()])
        g = abs(num(r.get("pm_gap_pct")) or 0.0)
        return (-st, -og, -g, str(r.get("ticker", "")))
    nonflag = [r for r in rows if str(r.get("verdict", "")).strip().upper() != "FLAGGED"]
    return sorted(nonflag, key=key)


def check_reply(path, rows):
    print(f"[reply] {path}")
    with open(path, encoding="utf-8", errors="replace") as fh:
        raw = fh.read()
    lines = raw.split("\n")
    start, end = None, len(lines)
    for i, ln in enumerate(lines):
        if re.match(r"^\s*#{2,4}\s*Signal", ln, re.I):
            start = i
            break
    if start is None:
        bad("the reply has no '### Signal' section — the shared reply format requires it")
        region = "\n".join(lines)
    else:
        for j in range(start + 1, min(len(lines), start + 80)):
            if re.match(r"^\s*#{2,4}\s", lines[j]):
                end = j
                break
        region = "\n".join(lines[start:end])

    ranked = ranking(rows)
    if not ranked:
        ok("every scanned name is FLAGGED — no non-qualifying name to name in the reply")
        return
    expected = [str(r.get("ticker", "")).strip() for r in ranked[:2]]
    named = [t for t in expected if re.search(rf"\b{re.escape(t)}\b", region)]
    if len(named) >= 2:
        ok(f"the reply's Signal section names the top 2 non-qualifying names "
           f"({', '.join(expected)})")
    else:
        bad(f"the reply's Signal section names {len(named)} of the top 2 non-qualifying names "
            f"({', '.join(expected)}) — a trader who tracks this list needs to know a "
            f"high-quality setup went nowhere")

    flagged = [str(r.get("ticker", "")).strip() for r in rows
               if str(r.get("verdict", "")).strip().upper() == "FLAGGED"]
    for tick in flagged:
        if not re.search(rf"\b{re.escape(tick)}\b", region):
            bad(f"FLAGGED name {tick} is not named in the reply's Signal section")


def check_universe(rows, version=CONTRACT_VERSION):
    """v5: the artifact must name the universe's session and the denominator's
    session, and they must be ONE date each for the whole artifact.

    A gap computed against a different session than the universe belongs to is
    the wrong-number bug this contract exists to stop, so it is a hard failure.
    """
    if version != CONTRACT_VERSION:
        print("[universe] skipped (the artifact predates the universe contract)")
        return
    print("[universe] the universe date and the denominator session")
    if not rows:
        bad("the CSV has no rows, so the universe cannot be proven")
        return
    udates = {str(r.get("universe_date", "")).strip() for r in rows}
    rdates = {str(r.get("ref_close_date", "")).strip() for r in rows}
    if len(udates) != 1 or "" in udates:
        bad(f"every row must carry the SAME universe_date, found {sorted(udates)}")
    else:
        ok(f"every row carries the same universe_date ({udates.pop()})")
    if len(rdates) != 1 or "" in rdates:
        bad(f"every row must carry the SAME ref_close_date, found {sorted(rdates)}")
    else:
        ok(f"every row carries the same ref_close_date ({rdates.pop()})")
    if len(udates) == 1 and len(rdates) == 1:
        u = next(iter(udates)); r = next(iter(rdates))
        if u != r:
            bad(f"the universe session ({u}) and the denominator session ({r}) differ - "
                f"the gaps are measured against a session the universe does not belong to")
        else:
            ok(f"the universe session and the denominator session agree ({u})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", required=True)
    ap.add_argument("--csv", required=True)
    ap.add_argument("--reply", default=None)
    args = ap.parse_args()

    for p in (args.md, args.csv):
        if not os.path.exists(p):
            print(f"FAIL missing file: {p}")
            sys.exit(1)

    lines, secs, md_rows, ver, flagged, scanned = check_md(args.md)
    version = ver or CONTRACT_VERSION
    rows = check_csv(args.csv, md_rows, flagged, scanned, version)
    check_universe(rows, version)
    check_nonqualifying(lines, secs, rows)
    check_flags(lines, secs, rows)
    if args.reply and os.path.exists(args.reply):
        check_reply(args.reply, rows)
    elif args.reply:
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
