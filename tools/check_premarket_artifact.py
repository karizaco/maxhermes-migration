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
import json
import os
import re
import sys

# Capability marker. The fetch ladder demands it: an OLD checker does not know
# about the v6 fields, and a run that passes an old check is not a checked run.
PREMARKET_CHECK_V2 = "PREMARKET_CHECK_V2"

# ---- the published constants (they live in the skill spec; keep the two in sync) ----
GAP_TRIGGER_PCT = 4.0
MIN_PM_VOLUME_SHARES = 50_000
MIN_EXECUTED_SHARES = 25

CONTRACT_VERSION = "premarket-artifact-v6"

# The v5 clauses (the universe/denominator session) apply from v5 ONWARDS; the
# v6 clauses (the tape lag, the driver class, the prior session's change) apply
# from v6. A version comparison is explicit so that bumping CONTRACT_VERSION
# never silently DISABLES a clause an older artifact already satisfies.
V5_COLS = ("universe_date", "ref_close_date", "universe_source")
V6_COLS = ("tape_lag_min", "driver_class", "prior_session_change")

DRIVER_CLASSES = {"CATALYST", "CRYPTO_BETA", "MARKET_BETA", "SECTOR_BETA",
                  "IDIOSYNCRATIC", "NO_MOVE"}

PULL_MARKER = "premarket-pull-v2"
RENDER_MARKER = "premarket-render-v1"


def ver_at_least(ver, target):
    """'premarket-artifact-v5' >= 'premarket-artifact-v5' -> True."""
    def n(v):
        m = re.search(r"v(\d+)$", str(v or ""))
        return int(m.group(1)) if m else 0
    return n(ver) >= n(target)

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


def _split(v):
    """Split a provenance field on ';' or '|'.

    The sweep's focus.csv writes `origins` and `stylists` PIPE-separated
    (A_stockbee_4pct|B_stockbee_ep9m|...), while the older schema used ';'.
    Splitting only on ';' counted every name as ONE origin and collapsed the
    setup-quality ranking to |gap| order.
    """
    return [x.strip() for x in re.split(r"[;|]", str(v or "")) if x.strip()]


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
        if ver_at_least(ver, "premarket-artifact-v6"):
            if PULL_MARKER in (ml or ""):
                ok(f"the marker line carries the pull capability marker ({PULL_MARKER})")
            else:
                bad(f"the marker line does not carry the pull capability marker "
                    f"({PULL_MARKER}) - a cached OLD pull script can write the OLD shape")
            if RENDER_MARKER in (ml or ""):
                ok(f"the marker line carries the renderer capability marker ({RENDER_MARKER})")
            else:
                bad(f"the marker line does not carry the renderer capability marker "
                    f"({RENDER_MARKER}) - the markdown must be engine-owned")

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
    if not ver_at_least(version, "premarket-artifact-v5"):
        req = [c for c in req if c not in V5_COLS]
    if ver_at_least(version, "premarket-artifact-v6"):
        req = req + list(V6_COLS)
    missing = [c for c in req if c not in cols]
    if missing:
        bad(f"the CSV header is missing required columns: {missing}")
    else:
        ok(f"the CSV header carries all required columns ({len(cols)} columns)")
    if not rows:
        bad("the CSV has no data rows")
        return rows

    req_vals = list(REQUIRED_CSV_VALUES)
    if not ver_at_least(version, "premarket-artifact-v5"):
        req_vals = [c for c in req_vals if c not in V5_COLS]
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
        # v6: the driver class and the tape lag are FIELDS, and a field that is
        # silently empty is a silent failure, not a missing value.
        if ver_at_least(version, "premarket-artifact-v6"):
            dc = str(r.get("driver_class", "")).strip().upper()
            if not dc:
                bad(f"CSV row {n} ({tick}) has no driver_class - a gap that clears the bar is "
                    f"not automatically a setup, and the reader has to be told which it is")
            elif dc not in DRIVER_CLASSES:
                bad(f"CSV row {n} ({tick}) has an invalid driver_class: {dc} "
                    f"(allowed: {', '.join(sorted(DRIVER_CLASSES))})")
            lag = str(r.get("tape_lag_min", "")).strip()
            if not lag:
                bad(f"CSV row {n} ({tick}) has no tape_lag_min - a print's age against the wall "
                    f"clock is what makes a stale tape visible")
            else:
                lv = num(lag)
                if lv is None and lag.lower() not in ("n/a", "na"):
                    bad(f"CSV row {n} ({tick}) has a non-numeric tape_lag_min: {lag!r}")
                elif lv is not None and lv < 0:
                    bad(f"CSV row {n} ({tick}) has a negative tape_lag_min: {lv}")
            if not str(r.get("prior_session_change", "")).strip():
                bad(f"CSV row {n} ({tick}) has no prior_session_change - 'n/a' is the honest "
                    f"value, an empty cell is not")
        # a column that is a PLACEHOLDER on EVERY row is a silent failure, not a
        # missing value (measured 2026-11-13: pm_volume_pct_30d published "n/a" on
        # all 12 rows because the renderer read a differently named field).
        if ver_at_least(version, "premarket-artifact-v6") and "pm_volume_pct_30d" in cols:
            placeholders = sum(1 for r in rows
                               if str(r.get("pm_volume_pct_30d", "")).strip().lower()
                               in ("n/a", "na", "-", ""))
            if placeholders == len(rows) and rows:
                bad("pm_volume_pct_30d is a placeholder on EVERY row - a field that carries no "
                    "information on every row is a silent failure, not a missing value")
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
        origins = _split(r.get("origins"))
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
        st = len(_split(r.get("stylists")))
        og = len(_split(r.get("origins")))
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


def check_reply_ladder(pull_path, region):
    """v6: the reply's Signal section must name the market's biggest gaps.

    The artifact's PRIMARY table is the market ladder, so the reply's Signal
    section leads with it. A reply that names only the Focus book is reporting
    the wrong book at the reader.
    """
    if not pull_path or not os.path.exists(pull_path):
        return
    print("[reply] the market ladder")
    try:
        with open(pull_path, encoding="utf-8") as fh:
            pull = json.load(fh)
    except Exception as e:
        bad(f"the pull JSON could not be read ({e})")
        return
    ladder = pull.get("market_ladder") or []
    if not ladder:
        ok("the engine saw no market-wide gap leaders - nothing to name")
        return
    top = [str(t.get("ticker", "")).strip() for t in ladder[:3]]
    named = [t for t in top if re.search(rf"\b{re.escape(t)}\b", region)]
    if len(named) >= min(3, len(top)):
        ok(f"the reply's Signal section names the market's top gaps ({', '.join(top)})")
    else:
        bad(f"the reply's Signal section names {len(named)} of the market's top gaps "
            f"({', '.join(top)}) - the market's book leads the artifact, so it leads the reply")


def check_ladder(lines, secs, version):
    """v6: the MARKET's gaps are the PRIMARY table.

    The Focus list is a momentum screen built on the PREVIOUS session, so it
    structurally cannot contain a name whose move has not happened yet -
    measured 2026-11-12, the Focus book held 0 of the day's real movers. A
    pre-market gapper whose headline is the Focus book's count is therefore
    reporting the wrong book.
    """
    if not ver_at_least(version, "premarket-artifact-v6"):
        return []
    print("[section] Market ladder")
    hit = find_section(secs, "marketladder")
    if not hit:
        bad("the artifact has no '## Market ladder' section - the market's pre-market gaps are "
            "the PRIMARY table and the Focus book follows them")
        return []
    body = strip_fences(section_body(lines, secs, "marketladder"))
    headers, lrows = md_table(body)
    if not headers or not lrows:
        # No table. That is only OK when the ENGINE saw no gap leaders either -
        # the ladder is CONTEXT and a failed ladder scan must not sink the
        # Focus book. check_ladder_against_pull() decides, because it knows
        # what the engine actually saw.
        print("  note the Market ladder section has no table - the engine's data decides "
              "whether that is a defect")
        return []
    ok(f"the Market ladder section carries a table ({len(lrows)} rows)")
    fs = find_section(secs, "focusscan")
    if fs and hit[1][0] > fs[1][0]:
        bad("the Market ladder comes AFTER the Focus scan - the market's book must lead")
    else:
        ok("the Market ladder comes before the Focus scan")
    tickers = []
    for r in lrows:
        for h in (r.keys() or []):
            if norm(h) in ("ticker", "symbol", "name"):
                tickers.append(str(r.get(h, "")).strip().strip("*"))
                break
    return tickers


def check_ladder_against_pull(pull_path, ladder_tickers):
    """The ladder the artifact published must be the ladder the ENGINE saw."""
    if not pull_path or not os.path.exists(pull_path):
        return
    print("[pull] the market ladder against the engine's data")
    try:
        with open(pull_path, encoding="utf-8") as fh:
            pull = json.load(fh)
    except Exception as e:
        bad(f"the pull JSON could not be read ({e})")
        return
    expected = [str(t.get("ticker", "")).strip() for t in (pull.get("market_ladder") or [])]
    if not expected:
        if ladder_tickers:
            bad("the engine saw no market-wide gap leaders but the artifact published a ladder "
                "table - the table is not the engine's data")
        else:
            ok("the engine saw no market-wide gap leaders - nothing to cross-check")
        return
    if not ladder_tickers:
        bad(f"the engine saw {len(expected)} market-wide gap leaders and the artifact published "
            f"NO ladder table - the market's book was dropped")
        return
    # the markdown publishes the top N; the FULL list stays in the pull JSON
    expected = expected[:len(ladder_tickers)] if ladder_tickers else []
    if sorted(ladder_tickers) == sorted(expected):
        ok(f"the published ladder matches the engine's market_ladder ({len(expected)} names)")
    else:
        bad(f"the published ladder ({len(ladder_tickers)} names) differs from the engine's "
            f"market_ladder ({len(expected)} names) - the table was not rendered from the pull")


def check_universe(rows, version=CONTRACT_VERSION, flags_text=""):
    """v5: the artifact must name the universe's session and the denominator's
    session, and they must be ONE date each for the whole artifact.

    A gap computed against a different session than the universe belongs to is
    the wrong-number bug this contract exists to stop, so it is a hard failure.
    """
    if not ver_at_least(version, "premarket-artifact-v5"):
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
            # The DEGRADED state: the expected session's sweep has not published,
            # so the Focus list is one session old and the reference close was
            # taken from the INDEPENDENT sources. It is ACCEPTED only when the
            # artifact says so in `## Flags` AND no row's close came from the
            # stale file - otherwise the gap would be measured against a price
            # that belongs to a different session, which is the bug this
            # clause exists to stop.
            flagged = "universe_stale" in (flags_text or "")
            indep = all(("focus.csv" not in str(r_.get("ref_close_source") or ""))
                        for r_ in rows)
            if flagged and indep:
                ok(f"the universe is a session stale ({u} vs {r}) and the artifact publishes it; "
                   f"every reference close came from an independent source")
            elif not flagged:
                bad(f"the universe session ({u}) and the denominator session ({r}) differ and "
                    f"the artifact does not publish `universe_stale` in ## Flags - a stale "
                    f"universe must be stated, not hidden")
            else:
                bad(f"the universe session ({u}) and the denominator session ({r}) differ and a "
                    f"reference close came from the STALE file - the close must come from the "
                    f"independent sources only")
        else:
            ok(f"the universe session and the denominator session agree ({u})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", required=True)
    ap.add_argument("--csv", required=True)
    ap.add_argument("--reply", default=None)
    ap.add_argument("--pull-json", default=None,
                    help="the _premarket-pull.json - lets the checker cross-check the published "
                         "market ladder against the engine's data")
    args = ap.parse_args()

    for p in (args.md, args.csv):
        if not os.path.exists(p):
            print(f"FAIL missing file: {p}")
            sys.exit(1)

    lines, secs, md_rows, ver, flagged, scanned = check_md(args.md)
    version = ver or CONTRACT_VERSION
    rows = check_csv(args.csv, md_rows, flagged, scanned, version)
    check_universe(rows, version,
                   "\n".join(strip_fences(section_body(lines, secs, "flags"))))
    ladder_tickers = check_ladder(lines, secs, version)
    check_ladder_against_pull(args.pull_json, ladder_tickers)
    check_nonqualifying(lines, secs, rows)
    check_flags(lines, secs, rows)
    if args.reply and os.path.exists(args.reply):
        check_reply(args.reply, rows)
        if args.reply:
            with open(args.reply, encoding="utf-8", errors="replace") as fh:
                reply_raw = fh.read()
            rlines = reply_raw.split("\n")
            start = None
            for i, ln in enumerate(rlines):
                if re.match(r"^\s*#{2,4}\s*Signal", ln, re.I):
                    start = i
                    break
            end = len(rlines)
            if start is not None:
                for j in range(start + 1, min(len(rlines), start + 80)):
                    if re.match(r"^\s*#{2,4}\s", rlines[j]):
                        end = j
                        break
            region = "\n".join(rlines[start:end]) if start is not None else reply_raw
            check_reply_ladder(args.pull_json, region)
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
