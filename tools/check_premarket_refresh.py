#!/usr/bin/env python3
"""
check_premarket_refresh.py — assert the cron #26b pre-market-refresh artifact contract.

Do not eyeball it. Cron #26b is the only routine in this cluster with NO machine gate: its
decision-bearing sections (## Bottom line, ## What to watch at the open, ## Gap quality) were
rewritten on 2026-11-07 and had exactly one live fire before this checker existed. Two
consecutive fires then published DIFFERENT skeletons (7 front-matter keys vs 11, unnumbered
sections vs numbered, gap-quality before the top-of-book vs after it) and two published a thin
tape block that silently showed 18 of 44 and 20 of 48 qualifying names. A reader cannot see
those defects and a linter that checks only "the file is non-empty" will not find them.

This script turns the acceptance criteria into machine assertions, so a run that breaks the
contract FAILS instead of shipping.

USAGE
    python3 check_premarket_refresh.py --md daily-briefs/<date>-pre-market-refresh.md \
                                       --csv daily-briefs/<date>-pre-market-refresh.csv \
                                       [--morning-csv daily-briefs/<date>-pre-market.csv] \
                                       [--reply <reply.txt>]

Exit codes: 0 = contract satisfied; 1 = at least one FAIL (each is printed).
"""

import argparse
import csv
import os
import re
import sys

CONTRACT_VERSION = "premarket-refresh-v1"

# ---- the pinned front matter, in order (the spec's "The artifact skeleton — PINNED") ----
REQUIRED_FM = ["date", "cron", "fire_time_et", "snapshot_et", "source", "status",
               "changes_since_morning", "up_3pct", "down_3pct", "screen_complete"]
OPTIONAL_FM = ["routine", "pull_late", "market_open_at_pull", "morning_brief"]
CRON_VALUE = "26-agentic-pre-market-brief-refresh"

# ---- the pinned section skeleton (prefix-matched, so "### Thin tape — …" still matches) ----
SKELETON = [
    "## Bottom line",
    "## What to watch at the open",
    "## 1. Refreshed top-of-book",
    "### Top 15 gainers",
    "### Top 10 decliners",
    "### Thin tape",
    "## 2. Gap quality",
    "## 3. What changed since the morning brief",
    "## 4. Verdict",
    "## 5. Source health",
]

# ---- the Driver vocabulary (the spec's fixed table) ----
DRIVERS = {"CASH-OUT", "CASH-IN", "LIABILITY-RESOLVED", "ASSET-VALUE", "EARNINGS-RAISE",
           "EARNINGS-RECONFIRM", "EARNINGS-CUT", "CORPORATE-EVENT", "SECTOR-BETA", "NONE",
           "unclassified"}
SETUP_CLASSES = {"CASH-OUT", "CASH-IN", "LIABILITY-RESOLVED", "ASSET-VALUE", "EARNINGS-RAISE"}

CSV_HEADER = ["ticker", "name", "premarket_close", "premarket_change_pct", "premarket_volume",
              "avg_volume_30d", "pct_of_adv", "prior_close", "prior_session_change_pct",
              "live_close", "live_change_pct", "live_volume", "market_cap", "sector", "exchange",
              "screen_complete"]

SIDE_WORDS = ("back to/below", "below", "above", "reclaim", "above/below")
PLACEHOLDERS = ("TODO", "TBD", "FIXME", "XXX", "<", ">", "{{", "}}", "PLACEHOLDER", "???")

RESULTS = []


def check(ok, name, detail=""):
    RESULTS.append((bool(ok), name, detail))
    return bool(ok)


def read(path):
    if not path or not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return f.read()


def parse_front_matter(text):
    if not text.startswith("---"):
        return None, []
    end = text.find("\n---", 3)
    if end < 0:
        return None, []
    block = text[3:end].strip("\n")
    fm = {}
    for line in block.split("\n"):
        if ":" in line:
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip()
    return fm, block.split("\n")


def headings(text):
    out = []
    in_fence = False
    for line in text.split("\n"):
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if re.match(r"^#{2,3} ", line):
            out.append(line.strip())
    return out


def table_rows(text, header_contains):
    """Rows of the first markdown table whose header contains every token in header_contains."""
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if all(any(tok.lower() in c.lower() for c in cells) for tok in header_contains):
            rows = []
            j = i + 2
            while j < len(lines) and lines[j].startswith("|"):
                rc = [c.strip() for c in lines[j].strip().strip("|").split("|")]
                if not all(set(c) <= set("-: ") for c in rc):
                    rows.append(rc)
                j += 1
            return rows, cells
    return [], []


def num(s):
    """Parse a number out of a table cell; None when there is none."""
    if s is None:
        return None
    t = s.replace(",", "").replace("$", "").replace("%", "").strip()
    m = re.search(r"-?\d+(?:\.\d+)?", t)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", required=True)
    ap.add_argument("--csv", dest="csv_path", required=True)
    ap.add_argument("--morning-csv", dest="morning_csv", default=None)
    ap.add_argument("--reply", default=None)
    args = ap.parse_args()

    text = read(args.md)
    if text is None:
        print("FAIL MD-READ — %s is missing" % args.md)
        return 1

    # ---------------- front matter ----------------
    fm, _ = parse_front_matter(text)
    if not check(fm is not None, "FM-PARSE", "front matter block"):
        report()
        return 1
    missing = [k for k in REQUIRED_FM if k not in fm]
    check(not missing, "FM-KEYS", "missing: %s" % ", ".join(missing))
    extra = [k for k in fm if k not in REQUIRED_FM and k not in OPTIONAL_FM]
    check(not extra, "FM-NO-EXTRA-KEYS", "unpinned keys: %s" % ", ".join(extra))
    check(fm.get("cron") == CRON_VALUE,
          "FM-CRON", "cron is %r, expected %r" % (fm.get("cron"), CRON_VALUE))
    check(bool(re.match(r"^\d{4}-\d{2}-\d{2}$", fm.get("date", ""))),
          "FM-DATE", "date is %r" % fm.get("date"))
    check(bool(re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$", fm.get("fire_time_et", ""))),
          "FM-FIRE-TIME", "fire_time_et is %r" % fm.get("fire_time_et"))
    check(bool(re.match(r"^\d{2}:\d{2}$", fm.get("snapshot_et", ""))),
          "FM-SNAPSHOT", "snapshot_et is %r" % fm.get("snapshot_et"))
    check(fm.get("status") == "ok", "FM-STATUS", "status is %r" % fm.get("status"))
    for k in ("changes_since_morning", "up_3pct", "down_3pct"):
        check(str(fm.get(k, "")).strip().lstrip("-").isdigit(), "FM-INT-%s" % k,
              "%s is %r" % (k, fm.get(k)))
    check(fm.get("screen_complete") in ("true", "false"), "FM-SCREEN-COMPLETE",
          "screen_complete is %r" % fm.get("screen_complete"))

    # ---------------- skeleton ----------------
    hs = headings(text)
    idx, ok_order = 0, True
    missing_h = []
    for want in SKELETON:
        found = None
        for i in range(idx, len(hs)):
            if hs[i].startswith(want) or hs[i].startswith(want.split(" —")[0]):
                found = i
                break
        if found is None:
            ok_order = False
            missing_h.append(want)
        else:
            idx = found + 1
    check(ok_order, "SKELETON", "missing or out of order: %s" % "; ".join(missing_h))

    # ---------------- ## Bottom line ----------------
    bl = []
    if "## Bottom line" in text:
        seg = text.split("## Bottom line", 1)[1]
        seg = re.split(r"\n## ", seg, 1)[0]
        bl = [l.strip() for l in seg.split("\n") if re.match(r"^\s*[123]\.\s", l)]
    check(len(bl) == 3, "BL-THREE-LINES", "Bottom line has %d numbered lines" % len(bl))
    if bl:
        l1 = bl[0]
        check(bool(re.search(r"\d", l1)), "BL-L1-DIGIT", "line 1 carries no digit")
        check("invalidat" in l1.lower(), "BL-L1-INVALIDATION", "line 1 carries no 'invalidat*'")
        drv = None
        for d in sorted(DRIVERS, key=len, reverse=True):
            if d in l1:
                drv = d
                break
        cash = "no name carries an anchored catalyst" in l1.lower()
        if cash:
            check(True, "BL-L1-CASH-CASE", "no anchored catalyst declared")
        else:
            check(drv is not None, "BL-L1-DRIVER",
                  "line 1 names no Driver from the vocabulary")
            check(drv is not None and (drv + "+ANCHORED") in l1,
                  "BL-L1-ANCHORED",
                  "line 1's Driver is not %s+ANCHORED" % drv)
        check(bool(re.search(r"invalidat\w*\s+(?:by\s+)?", l1, re.I)) and
              ("prior close" in l1.lower() or "PM low" in l1.lower()),
              "BL-L1-LEVELS", "line 1 carries no invalidation level")
    for i, l in enumerate(bl):
        check(len(l) > 40, "BL-L%d-LENGTH" % (i + 1), "line %d is too short to be a decision" % (i + 1))

    # ---------------- ## What to watch at the open ----------------
    rows, _ = table_rows(text, ["Prior close", "PM last", "PM low", "PM high", "Trigger",
                                "Invalidation"])
    check(len(rows) == 3, "WATCH-THREE", "watch table has %d rows" % len(rows))
    for r in rows:
        if len(r) < 7:
            check(False, "WATCH-COLUMNS", "row has %d columns" % len(r))
            continue
        check(all(r[i] for i in (1, 2, 3, 4, 5, 6)), "WATCH-LEVELS",
              "row %s has an empty level" % r[0])
        check(any(w in r[6].lower() for w in SIDE_WORDS), "WATCH-INVALIDATION-SIDE",
              "row %s's invalidation carries no side: %r" % (r[0], r[6]))

    # ---------------- ## Gap quality ----------------
    gq, gq_head = table_rows(text, ["Gap %", "PM range", "Hold %", "pm %ADV", "Driver",
                                    "Key level", "Invalidation"])
    check(len(gq) == 25, "GQ-25-ROWS", "gap-quality table has %d rows" % len(gq))
    gq_tickers = []
    for r in gq:
        if len(r) < 10:
            check(False, "GQ-COLUMNS", "row has %d columns" % len(r))
            continue
        gq_tickers.append(r[0])
        d = r[7].strip()
        base = d[:-len("+ANCHORED")] if d.endswith("+ANCHORED") else d
        check(base in DRIVERS, "GQ-DRIVER-VOCABULARY",
              "%s's Driver %r is not in the fixed vocabulary" % (r[0], d))
        check(r[8].strip() != "", "GQ-KEY-LEVEL", "%s has no key level" % r[0])
        check(any(w in r[9].lower() for w in SIDE_WORDS), "GQ-INVALIDATION-SIDE",
              "%s's invalidation carries no side: %r" % (r[0], r[9]))
        check(num(r[2]) is not None, "GQ-GAP", "%s has no gap %%" % r[0])
    check(len(set(gq_tickers)) == len(gq_tickers), "GQ-UNIQUE", "duplicate ticker in gap quality")

    # ---------------- top of book ----------------
    g_rows, _ = table_rows(text, ["Ticker", "Pre-market", "%", "Mkt cap", "Snapshot"])
    d_rows, _ = table_rows(text, ["Ticker", "Pre-market", "%", "Mkt cap", "Snapshot"])
    # the gainer and decliner tables have the same header — split by position. A block ends at
    # the next heading, a bold stand-alone paragraph ("**Thin tape** — …") or a blockquote.
    STOP = re.compile(r"^\s*(#{2,4} |\*\*[^*]+\*\*\s|>\s)")

    def rows_of(block):
        out = []
        for line in block.split("\n"):
            if STOP.match(line) and not line.startswith("|"):
                break
            if line.startswith("|") and not re.match(r"^\|[\s\-|:]+\|$", line):
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                if cells and cells[0] not in ("Ticker", "") and not set(cells[0]) <= set("-: "):
                    out.append(cells)
        return out

    def block_after(pattern):
        m = re.search(pattern, text)
        if not m:
            return ""
        seg = text[m.end():]
        out = []
        for line in seg.split("\n"):
            if STOP.match(line) and not line.startswith("|"):
                break
            out.append(line)
        return "\n".join(out)

    gain = rows_of(block_after(r"###\s*Top 15 gainers"))
    decl = rows_of(block_after(r"###\s*Top 10 decliners"))
    check(len(gain) == 15, "TOPG-15", "gainers table has %d rows" % len(gain))
    check(len(decl) == 10, "TOPD-10", "decliners table has %d rows" % len(decl))
    ggaps = [num(r[3]) for r in gain if len(r) > 3]
    check(all(a is not None for a in ggaps) and ggaps == sorted(ggaps, reverse=True),
          "TOPG-SORTED", "gainers are not sorted by gap descending")
    dgaps = [num(r[3]) for r in decl if len(r) > 3]
    check(all(a is not None for a in dgaps) and dgaps == sorted(dgaps),
          "TOPD-SORTED", "decliners are not sorted by gap ascending")
    top_tickers = [r[0] for r in gain] + [r[0] for r in decl]
    check(top_tickers == gq_tickers,
          "GQ-MATCHES-TOP", "gap-quality tickers != the headline tables' tickers")

    # ---------------- thin tape: the claim must match the rows ----------------
    # the block is a "### Thin tape" heading and/or a bold stand-alone paragraph
    # ("**Thin tape** — …"); the segment runs to the next level-2 heading either way.
    marks = [m.start() for m in re.finditer(r"###\s*Thin tape|\*\*Thin tape\*\*", text)]
    if marks:
        start = min(marks)
        rest = text[start:]
        nxt = re.search(r"\n## ", rest)
        seg = rest[:nxt.start()] if nxt else rest[:8000]
        trows = []
        for line in seg.split("\n"):
            if line.startswith("|"):
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                if cells and cells[0] not in ("Ticker",) and not set(cells[0]) <= set("-: "):
                    trows.append(cells)
        claim = re.search(r"(\d+)\s+gainers?\s+and\s+(\d+)\s+decliners?\s+qualify", seg)
        if claim:
            cg, cd = int(claim.group(1)), int(claim.group(2))
            published = len(trows)
            of_m = re.search(r"showing\s+(\d+)\s+of\s+(\d+)", seg, re.I)
            if of_m:
                check(published == int(of_m.group(1)), "THIN-N-OF-M",
                      "claims %s of %s, shows %d" % (of_m.group(1), of_m.group(2), published))
            else:
                check(published == cg + cd, "THIN-COMPLETE",
                      "claims %d + %d qualifiers, publishes %d rows" % (cg, cd, published))
        else:
            check(True, "THIN-NO-CLAIM", "no qualifier count claimed")
    else:
        check(False, "THIN-PRESENT", "no thin-tape block found")

    # ---------------- the companion CSV ----------------
    csv_text = read(args.csv_path)
    header, rows = [], []
    if csv_text is None:
        check(False, "CSV-READ", "%s is missing" % args.csv_path)
    else:
        with open(args.csv_path, newline="", encoding="utf-8") as f:
            rdr = csv.reader(f)
            header = next(rdr, [])
            rows = list(rdr)
    check(header == CSV_HEADER, "CSV-HEADER", "header is %s" % ",".join(header[:4]) + "…")
    check(len({r[0] for r in rows}) == len(rows), "CSV-UNIQUE", "duplicate ticker in the CSV")
    check(all(r[7].strip() for r in rows), "CSV-PRIOR-CLOSE", "a row has an empty prior_close")
    check(all(r[2].strip() for r in rows), "CSV-PREMARKET", "a row has an empty premarket_close")
    live_blank = all((r[9].strip() == "" and r[10].strip() == "" and r[11].strip() == "") for r in rows)
    market_open = str(fm.get("market_open_at_pull", "")).lower() == "true"
    if market_open:
        check(not live_blank, "CSV-LIVE-PRESENT",
              "market_open_at_pull is true but live_* are blank on every row")
    else:
        check(live_blank, "CSV-LIVE-BLANK-PREOPEN",
              "the pull was pre-open, so live_* must be BLANK on every row (never 0)")
    sc = set(r[15].strip() for r in rows) if rows and len(rows[0]) > 15 else set()
    check(sc in ({"true"}, {"false"}), "CSV-SCREEN-COMPLETE",
          "screen_complete values on the rows: %s" % sorted(sc))
    if fm.get("screen_complete") in ("true", "false") and sc:
        check(fm.get("screen_complete") in sc, "CSV-SCREEN-COMPLETE-MATCHES-FM",
              "front matter says %r, the rows say %s" % (fm.get("screen_complete"), sorted(sc)))
    if fm.get("screen_complete") == "true":
        up, down = num(fm.get("up_3pct")), num(fm.get("down_3pct"))
        if up is not None and down is not None:
            check(len(rows) == int(up + down), "CSV-BAND-COUNT",
                  "up_3pct + down_3pct = %d, the CSV has %d rows" % (int(up + down), len(rows)))

    # ---------------- traceability: the MD's numbers come from the CSV ----------------
    by_tic = {r[0]: r for r in rows}
    # gap-quality gap % vs the CSV's premarket_change_pct
    for r in gq:
        if len(r) < 10:
            continue
        t = r[0]
        if t not in by_tic:
            check(False, "TRACE-IN-CSV", "%s is in the markdown but not the CSV" % t)
            continue
        csv_gap = num(by_tic[t][3])
        md_gap = num(r[2])
        if csv_gap is not None and md_gap is not None:
            check(abs(csv_gap - md_gap) <= 0.011, "TRACE-GAP",
                  "%s: markdown %+.2f%% vs CSV %+.2f%%" % (t, md_gap, csv_gap))

    # ---------------- snapshot consistency ----------------
    snap = fm.get("snapshot_et", "")
    if snap:
        stale = re.findall(r"\b(\d{2}:\d{2})\s*ET\b", text)
        others = set(s for s in stale if s != snap)
        # Source health may quote other clocks (a stall time, an open time); the ROWS may not.
        rowclocks = set()
        for r in gain + decl:
            if len(r) > 1:
                rowclocks.add(r[-1].replace(" ET", "").strip())
        check(not (rowclocks - {snap}), "SNAPSHOT-CONSISTENT",
              "row snapshot stamps %s differ from the front matter %s" % (sorted(rowclocks), snap))

    # ---------------- placeholders ----------------
    for ph in PLACEHOLDERS:
        if ph in ("<", ">"):
            continue
        check(ph not in text, "NO-PLACEHOLDER", "the file contains %r" % ph)

    # ---------------- the changes count, recomputed from the two CSVs ----------------
    if args.morning_csv:
        mrows = []
        if os.path.exists(args.morning_csv):
            with open(args.morning_csv, newline="", encoding="utf-8") as f:
                mrows = list(csv.DictReader(f))
        if mrows:
            m = {}
            for r in mrows:
                try:
                    m[r["ticker"]] = float(r["gap_pct"])
                except (KeyError, ValueError):
                    pass
            live = {}
            for r in rows:
                g = num(r[3])
                if g is not None:
                    live[r[0]] = g
            both = [t for t in live if t in m]
            moved = [t for t in both if abs(live[t] - m[t]) > 0.2]
            declared = num(fm.get("changes_since_morning", ""))
            check(declared is not None and abs(declared - len(moved)) <= 1,
                  "CHANGES-SINCE-MORNING",
                  "declared %r, recomputed %d" % (fm.get("changes_since_morning"), len(moved)))
            check(len(both) > 0, "CHANGES-BASE",
                  "no name is in both the morning CSV and the refresh CSV")

    # ---------------- reply, when given ----------------
    if args.reply:
        reply = read(args.reply) or ""
        check("push:" in reply, "REPLY-PUSH", "the reply carries no push line")
        check(re.search(r"errors:\s*\d+", reply) is not None, "REPLY-ERRORS",
              "the reply carries no errors line")
        check(re.search(r"\d+\s*min after", reply) is not None, "REPLY-LATENCY",
              "the reply's push line carries no delivery latency")

    report()
    return 1 if any(not ok for ok, _, _ in RESULTS) else 0


def report():
    passed = sum(1 for ok, _, _ in RESULTS if ok)
    failed = [(n, d) for ok, n, d in RESULTS if not ok]
    for ok, name, detail in RESULTS:
        if not ok:
            print("FAIL %-28s %s" % (name, detail))
    print("%d checks, %d passed, %d failed" % (len(RESULTS), passed, len(failed)))
    if failed:
        print("CONTRACT NOT SATISFIED (%s)" % CONTRACT_VERSION)


if __name__ == "__main__":
    sys.exit(main())
