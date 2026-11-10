#!/usr/bin/env python3
"""
check_preopen_checkpoint.py — the machine gate for cron #92's pre-open checkpoint.

WHAT IT GATES
-------------
The pre-open tape (`.jsonl`) and the board that sits beside it (`.md`), plus the shared
files that produce them. The gate exists because the three rules that matter were, until
now, enforced only in prose:

  1. ONE ROW PER TICKER. The tape is written atomically now, but the rule is still the
     one cron #17 depends on: it merges the checkpoints and reads the LAST record per
     ticker, so a doubled tape makes it read a stale record as the latest one.
     (Measured 2026-11-09 08:30 ET: 100 rows for 53 tickers, from two agents running
     the same slot against the same shared /workspace.)
  2. MOVERS IN BOTH DIRECTIONS. A gainers-only scan is not a pre-open tape — on
     2026-11-09 it missed IRTC -30.7%, DKNG -21.3% and AXON -18.2%, the day's three
     worst movers. The gate now asserts the tape carries priced movers on BOTH sides.
  3. PRICES FROM THE MOVERS SCAN ONLY. A narrative call explains; it never prices.

WHAT CHANGED AND WHY
--------------------
The 2026-11-08 rewrite replaced the TradingView sweep with a Pipeworx movers scan, and
the checker was never updated with it: it still asserted two `scanner.tradingview.com`
calls, a ~678-row tape and a 120-row "regression signature" — none of which exist any
more, so it FAILED against the current repo and could not gate anything. The row-count
heuristic is gone: the tape's size is now set by the movers scan plus the trending
snapshot, so a row count proves nothing. Direction coverage and one-row-per-ticker do.

USAGE
  check_preopen_checkpoint.py --repo <repo-root>
      [--tape <tape.jsonl>] [--digest <board.md>] [--skipped <marker.md>] [--slot 0830]
"""
import argparse
import json
import os
import re
import sys

# ---- the published constants -------------------------------------------------
ALLOWED_SLOTS = ("0830", "0920", "0950")
TOP_N = 15
DIGEST_COLUMNS = ["Ticker", "%", "Conf", "Catalyst", "When it broke"]
# The 10 keys cron #17 merges on — UNCHANGED since 2026-11-04.
TAPE_KEYS = ["ts", "src", "ticker", "name", "pct", "price", "cat", "why", "ref", "conf"]
# Provenance extras the capture script adds. They are additive: the consumer ignores
# them, and the board reads the timestamp and the volume from them.
TAPE_EXTRA_KEYS = ["trending_ts", "trending_score", "volume", "exchange", "grounded_tool"]
# The row's PROVENANCE, not a vendor.
ALLOWED_SRC = ("scanner", "pipeworx", "stocktwits")
# A priced row is one that came from the movers scan: src is scanner (price only) or
# pipeworx (price + a grounded catalyst). A stocktwits row is narrative-only.
PRICED_SRC = ("scanner", "pipeworx")
CONFIDENCES = ("high", "medium", "low", "unverified")

FAILURES = []
CHECKS = 0


def ok(msg):
    global CHECKS
    CHECKS += 1
    print(f"  PASS  {msg}")


def bad(msg):
    global CHECKS
    CHECKS += 1
    FAILURES.append(msg)
    print(f"  FAIL  {msg}")


def check(cond, msg):
    if cond:
        ok(msg)
    else:
        bad(msg)
    return bool(cond)


def read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except Exception:
        return ""


def norm(s):
    return re.sub(r"\s+", " ", s).strip().lower()


# ---- static: the shared procedure ---------------------------------------------

def check_procedure(path):
    print("procedure:")
    t = read(path)
    if not t:
        bad(f"{path} is missing or empty")
        return

    # 1. the movers scan covers BOTH directions, as DISJOINT halves
    check(re.search(r"top_movers.{0,40}gainers", t, re.I | re.S) is not None,
          "the procedure scans the GAINERS half of the movers universe")
    check(re.search(r"top_movers.{0,40}losers", t, re.I | re.S) is not None,
          "the procedure scans the LOSERS half too — a gainers-only tape is not a tape")
    check("both directions" in norm(t),
          "the procedure states that the scan covers BOTH directions")
    check("disjoint" in norm(t),
          "the two halves are DISJOINT, so no record can hold two prices")

    # 2. the slot comes from the FIRE'S INSTANT and never from a literal wall clock
    for s in ALLOWED_SLOTS:
        check(s in t, f"the allowed checkpoint slot {s} is stated")
    check(not re.search(r"export\s+CP=\$\(TZ=America/New_York date \+%H%M\)", t),
          "no literal `date +%H%M` can name the slot (it would call an 08:35 execution 0835)")
    check("wall clock" in norm(t) and "slot" in norm(t),
          "the procedure says the slot is the FIRE'S slot, not the wall clock")

    # 3. one snapshot per slot: the tape is written atomically
    check(re.search(r"atomic", t, re.I) is not None,
          "the procedure states the tape is written ATOMICALLY (one snapshot per slot)")
    check("one row per ticker" in norm(t),
          "the one-row-per-ticker rule is stated")

    # 4. the board is part of the checkpoint
    check("preopen_digest.py" in t, "the procedure renders the board with preopen_digest.py")
    check(re.search(r"preopen-feed/\$\{DATE\}-\$\{CP\}\.md", t) is not None,
          "the procedure names the digest file beside the tape")
    check(re.search(r"preopen-feed/\$\{DATE\}-\$\{CP\}\.jsonl", t) is not None,
          "the procedure names the tape file")

    # 5. the fail-closed trail
    check("SLOT DEVIATION" in t or "DEVIATION.slot.md" in t,
          "a slot outside the allowed set leaves a marker instead of a phantom filename")

    # 6. the do-not list
    check("not measurable" in norm(t),
          "the halt state is published as 'not measurable'")
    check(not re.search(r"halted:\s*0\b", t), "no halt COUNT is ever published")
    check(re.search(r"prices are never taken from the narrative calls", t, re.I) is not None,
          "the rule that prices never come from a narrative call is stated")
    check(re.search(r"xai/grok is not used", t, re.I) is not None,
          "the procedure states that xAI/Grok is not used (live search is 410)")

    # 7. the fetch ladder demands a capability marker — and a VERSION, because a
    # marker alone cannot detect a stale copy that already carries it.
    check(re.search(r"CAPTURE_SCRIPT_VERSION:\s*\d{4}-\d{2}-\d{2}", t) is not None,
          "the script fetch demands the CAPTURE_SCRIPT_VERSION marker")
    check(re.search(r"PREOPEN_DIGEST_V1", t) is not None,
          "the digest fetch demands the PREOPEN_DIGEST_V1 capability marker")


# ---- static: the shared scripts -----------------------------------------------

def check_script(path):
    print("capture script:")
    t = read(path)
    if not t:
        bad(f"{path} is missing or empty")
        return
    check(re.search(r"CAPTURE_SCRIPT_VERSION:\s*\d{4}-\d{2}-\d{2}", t) is not None,
          "carries the CAPTURE_SCRIPT_VERSION marker")
    check('call_top_movers(category="losers")' in t,
          "the capture scans the losers half (a gainers-only scan misses the worst movers)")
    check("-abs(" in t,
          "candidates are ranked by |%| so a decliner competes for a grounded catalyst")
    check("os.replace" in t and not re.search(r'open\(out,\s*"a"', t),
          "the tape is written with a temp file + rename, never appended")
    check("ALLOWED_SLOTS" in t and "resolve_slot" in t,
          "the slot is asserted against the allowed set and a late dispatch snaps down")
    for k in TAPE_KEYS:
        check(f'"{k}"' in t, f"the tape row carries the contract key {k!r}")
    check("not measurable" in norm(t) or "halted" not in t,
          "the script never publishes a halt count")


def check_digest_script(path):
    print("digest renderer:")
    t = read(path)
    if not t:
        bad(f"{path} is missing or empty")
        return
    check("PREOPEN_DIGEST_V1" in t, "carries the PREOPEN_DIGEST_V1 marker")
    check("DIGEST_COLUMNS" in t and "Ticker" in t,
          "the board's columns are fixed in code")
    check("TOP_N = 15" in t, "the board lists the top 15 movers")
    check("scanner" in t and "stocktwits" in t and "pipeworx" in t,
          "the board reports the row PROVENANCE split (scanner / stocktwits / pipeworx)")
    check("not measurable" in norm(t),
          "the board reports the halt state as not measurable")


def check_prompts(repo):
    print("prompts:")
    for name in ("92a-preopen-catalyst-capture-0830.md", "92b-preopen-catalyst-capture-0950.md"):
        p = os.path.join(repo, "cloud-prompts", "cron-prompts", name)
        t = read(p)
        if not t:
            bad(f"{name} is missing")
            continue
        check("how many names the scanner flagged" not in t,
              f"{name}: no longer asks for a halt COUNT (the column is null on every row)")
        check(any("digest" in ln.lower() and ".md" in ln for ln in t.splitlines()),
              f"{name}: names the companion digest file (preopen-feed/{{date}}-{{HHMM}}.md)")
        check("SKIPPED" in t,
              f"{name}: mentions the skip marker")


# ---- dynamic: the artifacts -----------------------------------------------------

def parse_md_table(lines):
    """Return the rows of the digest's markdown table as lists of cells."""
    rows = []
    for ln in lines:
        s = ln.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if all(set(c) <= set("-: ") and c for c in cells):
            continue          # the separator row
        rows.append(cells)
    return rows


def check_tape(tape_path):
    print("tape:")
    raw = read(tape_path)
    rows = [json.loads(l) for l in raw.splitlines() if l.strip()] if raw else []
    if not rows:
        bad(f"{tape_path} has no rows")
        return

    missing = [r.get("ticker") for r in rows
               if any(k not in r for k in TAPE_KEYS)]
    check(not missing,
          f"every row carries the 10 contract keys ({len(missing)} offenders)")
    stray = sorted({k for r in rows for k in r.keys()
                    if k not in TAPE_KEYS and k not in TAPE_EXTRA_KEYS})
    check(not stray, f"no unexpected keys in a tape row (got {stray})")

    bad_src = sorted({r.get("src") for r in rows if r.get("src") not in ALLOWED_SRC})
    check(not bad_src,
          f"every row's src is the row's real provenance {ALLOWED_SRC} (got {bad_src})")

    # THE rule cron #17 depends on.
    dupes = len(rows) - len({r.get("ticker") for r in rows})
    check(dupes == 0, f"one row per ticker ({dupes} duplicates)")

    # Prices come from the movers scan only.
    priced = [r for r in rows if r.get("pct") is not None]
    check(all(r.get("price") is not None for r in priced),
          f"every priced row carries a price too ({len(priced)} priced rows)")
    unpriced_priced_src = [r.get("ticker") for r in rows
                           if r.get("src") in PRICED_SRC and r.get("pct") is None]
    check(not unpriced_priced_src,
          f"no row from the movers scan lacks a number ({unpriced_priced_src[:5]})")

    # BOTH directions — the rule the gainers-only scan broke.
    ups = [r for r in priced if (r.get("pct") or 0) > 0]
    downs = [r for r in priced if (r.get("pct") or 0) < 0]
    check(len(ups) > 0, f"the tape carries priced GAINERS ({len(ups)})")
    check(len(downs) > 0, f"the tape carries priced LOSERS ({len(downs)})")

    # The narrative rows are the honest ones: a row with no price carries no number.
    narrative = [r for r in rows if r.get("src") == "stocktwits"]
    check(all(r.get("pct") is None for r in narrative),
          f"every narrative-only row carries no number ({len(narrative)} such rows)")
    return rows


def check_digest(tape_path, digest_path, slot):
    print("digest:")
    t = read(digest_path)
    tape = read(tape_path)
    if not t:
        bad(f"{digest_path} is missing — the human-readable board must exist beside the tape")
        return
    rows = [json.loads(l) for l in tape.splitlines() if l.strip()] if tape else []
    n = len(rows)

    # beside the tape
    check(os.path.basename(digest_path).startswith(os.path.basename(tape_path).rsplit(".", 1)[0]),
          "the digest sits beside the tape (same date-slot stem)")
    check(os.path.basename(digest_path) == f"{os.path.basename(tape_path).rsplit('.', 1)[0]}.md",
          f"the digest is named {{date}}-{slot}.md")

    # header counts
    check(f"**records:** {n}" in t, f"the header carries the record count ({n})")
    grok = sum(1 for r in rows if r.get("src") == "grok")
    scanner = sum(1 for r in rows if r.get("src") == "scanner")
    unv = sum(1 for r in rows if r.get("conf") == "unverified")
    check(f"**grok:** {grok}" in t, f"the header carries the Grok/scanner split (grok {grok})")
    check(f"**scanner:** {scanner}" in t, f"the header carries the scanner count ({scanner})")
    check(f"**unverified:** {unv}" in t, f"the header carries the unverified count ({unv})")
    check("$" in t, "the header carries the measured Grok cost")
    check("not measurable" in norm(t), "the board publishes the halt state as not measurable")

    # the table
    tbl = parse_md_table(t.splitlines())
    header = [c.strip() for c in tbl[0]] if tbl else []
    check(header == DIGEST_COLUMNS,
          f"the table header is exactly {DIGEST_COLUMNS} (got {header})")
    body = tbl[1:] if tbl else []
    check(len(body) <= TOP_N, f"the table lists at most {TOP_N} rows (got {len(body)})")
    check(len(body) == min(TOP_N, n), f"the table lists the top {min(TOP_N, n)} movers")

    # ordering by |pct| desc
    pcts = []
    for r in body:
        try:
            pcts.append(abs(float(r[1])))
        except Exception:
            pcts.append(-1.0)
    check(pcts == sorted(pcts, reverse=True),
          "the rows are ranked by |%| descending")

    # every row carries a visible conf
    confs = [r[2].replace("⚠", "").strip() for r in body if len(r) > 2]
    check(all(c in CONFIDENCES for c in confs),
          f"every row carries a conf token from {CONFIDENCES}")

    # An unverified row must be OBVIOUS — the bare word "unverified" in a column of
    # other words is not obvious. The marker is what makes it stand out.
    unv_cells = [r for r in body if len(r) > 2 and "unverified" in r[2]]
    check(all("⚠" in r[2] for r in unv_cells),
          f"every unverified row is marked as such ({len(unv_cells)} in the table)")

    # a one-sided tape is a DEVIATION and the board has to say so
    priced = [r for r in rows if r.get("pct") is not None]
    one_sided = priced and not (
        [r for r in priced if (r.get("pct") or 0) > 0]
        and [r for r in priced if (r.get("pct") or 0) < 0])
    if one_sided:
        check("DEVIATION" in t,
              "a one-sided tape (no decliners) carries the DEVIATION banner")
    else:
        check("DEVIATION" not in t,
              "a tape with movers on both sides carries no deviation banner")


def check_skipped(marker_path, slot):
    print("skip marker:")
    t = read(marker_path)
    if not t:
        bad(f"{marker_path} is missing — a fail-closed checkpoint must leave a trail")
        return
    check("SKIPPED" in t or "SLOT DEVIATION" in t,
          "the marker says the checkpoint was skipped")
    # The reason must be ON THE SAME LINE as the label: a regex that can cross a
    # newline accepts an empty reason, which is exactly the 2026-11-03 failure
    # (cron #90 reported the absence "with an empty reason").
    reason_line = ""
    for ln in t.splitlines():
        if "**Reason:**" in ln:
            reason_line = ln.split("**Reason:**", 1)[1].strip()
            break
    check(bool(reason_line),
          f"the marker NAMES the reason (got {reason_line!r})")
    check(f"-{slot}" in t, f"the marker names its checkpoint slot ({slot})")
    stem = os.path.basename(marker_path)
    for suffix in (".SKIPPED.md", ".DEVIATION.slot.md"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    tape = os.path.join(os.path.dirname(marker_path), stem + ".jsonl")
    check(not os.path.exists(tape),
          "no JSONL was written beside the skip marker (a tape without a catalyst is worse "
          "than no tape)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--tape")
    ap.add_argument("--digest")
    ap.add_argument("--skipped")
    ap.add_argument("--slot", default="0830")
    a = ap.parse_args()

    repo = os.path.abspath(a.repo)
    check_procedure(os.path.join(repo, "cloud-prompts", "_shared", "preopen-capture.md"))
    check_script(os.path.join(repo, "cloud-prompts", "_shared", "preopen_capture.py"))
    check_digest_script(os.path.join(repo, "cloud-prompts", "_shared", "preopen_digest.py"))
    check_prompts(repo)

    if a.tape:
        check_tape(a.tape)
        if a.digest:
            check_digest(a.tape, a.digest, a.slot)
    if a.skipped:
        check_skipped(a.skipped, a.slot)

    print()
    if FAILURES:
        print(f"FAILED {len(FAILURES)} of {CHECKS} checks:")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print(f"PASSED all {CHECKS} checks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
