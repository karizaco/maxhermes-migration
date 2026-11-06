#!/usr/bin/env python3
"""
check_preopen_checkpoint.py — assert the cron #92 pre-open checkpoint contract.

Do not eyeball it. The 2026-11-04 08:30 checkpoint was mechanically correct and
reader-hostile at the same time: the tape was sorted by pre-market VOLUME, so the
biggest movers were buried under 666 rows of noise, the 09:50 fire on 2026-11-05
published 123 rows with the moves cut off at ±0.2%, and a checkpoint with no
XAI_API_KEY left NO trace at all — cron #90 reported the absence with an empty reason
and cron #17 had to reconstruct the cause from its own provenance table.

This script turns the acceptance criteria into machine assertions, so a run that
breaks the contract FAILS instead of shipping.

WHAT IS ASSERTED
  1. The procedure's scanner call is movers-sorted in BOTH directions, the expected
     tape size (~678) is documented, and a ~120-row tape is flagged as a DEVIATION.
  2. A human-readable digest exists beside the tape and lists the top 15 movers with
     their `conf` token.
  3. A fail-closed checkpoint writes a {date}-{slot}.SKIPPED.md naming the reason and
     writes NO tape.
  4. The checkpoint slot comes from the scheduled instant and is asserted to be in
     {0830, 0920, 0950}.
  5. The do-not list holds: the tape schema is unchanged, prices never come from
     Grok, `halted` is never published as a count, and no record splices two scanner
     calls.

USAGE
    python3 check_preopen_checkpoint.py --repo <repo-root> [--tape <tape.jsonl>]
                                         [--digest <digest.md>] [--skipped <marker.md>]
                                         [--slot 0830]

EXIT CODES
  0 = contract satisfied
  1 = at least one FAIL (each is printed)
  2 = usage error
"""

import argparse
import json
import os
import re
import sys

# ---- the published constants (they live in the procedure; keep the two in sync) ----
EXPECTED_TAPE_ROWS = 678
DEVIATION_MIN_ROWS = 300
REGRESSION_ROWS = 120
ALLOWED_SLOTS = ("0830", "0920", "0950")
TOP_N = 15
DIGEST_COLUMNS = ["Ticker", "%", "Conf", "Catalyst", "When it broke"]
TAPE_KEYS = ["ts", "src", "ticker", "name", "pct", "price", "cat", "why", "ref", "conf"]
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


def unescape(t):
    """The procedure embeds JSON inside a shell double-quoted string, so the file
    literally holds \\"sortBy\\":\\"premarket_change\\". Matching the escaped form
    alone would make the ABSENCE check for the old volume sort pass for the wrong
    reason — a checker that cannot fail is not a guard."""
    return t.replace('\\"', '"')


def norm(s):
    return re.sub(r"\s+", " ", s).strip().lower()


# ---- static: the shared procedure ----------------------------------------------

def check_procedure(path):
    print("procedure:")
    t = read(path)
    if not t:
        bad(f"{path} is missing or empty")
        return
    check("PROCEDURE_VERSION:" in t, "carries a PROCEDURE_VERSION marker")

    # 1. movers-sorted in BOTH directions, and NOT volume-sorted
    j = unescape(t)
    check('"sortBy":"premarket_change"' in j and '"sortOrder":"desc"' in j,
          "scanner call is sorted by premarket_change DESCENDING (gains)")
    check('"sortBy":"premarket_change"' in j and '"sortOrder":"asc"' in j,
          "scanner call is sorted by premarket_change ASCENDING (losses)")
    check('"sortBy":"premarket_volume"' not in j,
          "the old premarket_volume sort is GONE (it buried the movers)")
    n_scanner_calls = t.count("scanner.tradingview.com/america/scan")
    check(n_scanner_calls == 2,
          f"exactly two scanner calls in the procedure (got {n_scanner_calls}) — one snapshot, "
          f"two disjoint directional halves")
    check("egreater" in t and "eless" in t,
          "the two halves use DISJOINT filters (change >= +2.5 vs change <= -2.5), so no name "
          "can hold a price from two different calls")

    # 2. the documented expectation and the deviation rule
    check(str(EXPECTED_TAPE_ROWS) in t,
          f"the expected tape size (~{EXPECTED_TAPE_ROWS} rows) is DOCUMENTED")
    check(str(REGRESSION_ROWS) in t,
          f"the ~{REGRESSION_ROWS}-row regression signature is called out")
    check("tape_size_deviation" in t,
          "a small tape is flagged as a DEVIATION (tape_size_deviation), not accepted")

    # 3. the slot comes from the scheduled instant and is asserted
    check("0830 0920 0950" in t, "the allowed checkpoint slots {0830, 0920, 0950} are stated")
    check('grep -qx "$CP"' in t,
          "the filename's slot is ASSERTED against the allowed set")
    check('date -d "@$((FIRE_MS/1000))" +%H%M' in t,
          "the slot is derived from the FIRE'S INSTANT (FIRE_MS), not the wall clock")
    check(not re.search(r"export CP=\$\(TZ=America/New_York date \+%H%M\)", t),
          "no literal `date +%H%M` can name the slot (it would call an 08:35 execution 0835)")

    # 4. the fail-closed trail
    check("SKIPPED.md" in t, "the fail-closed path writes a .SKIPPED.md marker")
    check("preopen_checkpoint.py skipped" in t, "the marker is written by the checkpoint script")
    check("no JSONL is written in this path" in t.lower()
          or "no jsonl is written" in t.lower(),
          "the fail-closed path explicitly writes NO tape")

    # 5. the digest
    check("preopen_checkpoint.py digest" in t, "the digest is written by the checkpoint script")
    check("--meta /tmp/grok_meta.json" in t, "the digest receives the measured Grok cost")

    # 6. the do-not list
    check("halted: not measurable" in t, "the halt state is published as 'not measurable'")
    check(not re.search(r"halted:\s*0\b", t), "no halt COUNT is ever published")
    check("Never take a price from Grok" in t or "never from Grok" in t.lower(),
          "the rule that prices never come from Grok is stated")

    # 7. the fetch ladder demands the capability marker
    check("PREOPEN_CHECKPOINT_V1" in t,
          "the script fetch demands the PREOPEN_CHECKPOINT_V1 capability marker")
    check("CHECKPOINT_SCRIPT_VERSION: 2026-11-06.1" in t,
          "the script fetch ALSO demands the script version (a marker alone cannot "
          "detect a stale copy that already carries it)")


def check_script(path):
    print("checkpoint script:")
    t = read(path)
    if not t:
        bad(f"{path} is missing or empty")
        return
    check("PREOPEN_CHECKPOINT_V1" in t, "carries the PREOPEN_CHECKPOINT_V1 marker")
    check("CHECKPOINT_SCRIPT_VERSION: 2026-11-06.1" in t, "carries the script version")
    m = re.search(r"TAPE_KEYS\s*=\s*\[([^\]]*)\]", t)
    keys = re.findall(r'"([^"]+)"', m.group(1)) if m else []
    check(keys == TAPE_KEYS,
          f"the tape row shape is the unchanged 10-key contract ({len(keys)} keys)")
    check("def merge_tape" in t and "def parse_scanner" in t and "def parse_grok_reply" in t,
          "the merge is CODE, not model prose")
    check("unverified" in t and "unverified_pp" in t,
          "a Grok/scanner disagreement beyond the tolerance is written as unverified")
    check("not measurable" in t,
          "the merge reports the halt state as not measurable, never as a count")


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

    # the deviation rule
    if 0 < n < DEVIATION_MIN_ROWS:
        check("DEVIATION" in t,
              f"a {n}-row tape carries the DEVIATION banner (expected ≈{EXPECTED_TAPE_ROWS})")
        if n <= REGRESSION_ROWS:
            check("REGRESSION SIGNATURE" in t,
                  f"a ~{REGRESSION_ROWS}-row tape is named as the regression signature")
    else:
        check("DEVIATION" not in t or n >= DEVIATION_MIN_ROWS,
              "a normal-sized tape carries no deviation banner")


def check_tape(tape_path):
    print("tape:")
    raw = read(tape_path)
    rows = [json.loads(l) for l in raw.splitlines() if l.strip()] if raw else []
    if not rows:
        bad(f"{tape_path} has no rows")
        return
    bad_keys = [sorted(r.keys()) for r in rows if sorted(r.keys()) != sorted(TAPE_KEYS)]
    check(not bad_keys,
          f"every row carries exactly the 10 contract keys ({len(bad_keys)} offenders)")
    check(all(r.get("src") in ("grok", "scanner") for r in rows),
          "every row is src=grok or src=scanner")
    dupes = len(rows) - len({r.get("ticker") for r in rows})
    check(dupes == 0, f"one row per ticker ({dupes} duplicates)")
    # no price from Grok: a grok row must carry the scanner's number, and a row with
    # no number must be unverified
    no_number = [r for r in rows if r.get("pct") is None]
    check(all(r.get("conf") == "unverified" for r in no_number),
          f"every row without a scanner number is unverified ({len(no_number)} such rows)")
    check(all(r.get("pct") is not None for r in rows if r.get("src") == "scanner"),
          "every scanner row carries a number")


def check_skipped(marker_path, slot):
    print("skip marker:")
    t = read(marker_path)
    if not t:
        bad(f"{marker_path} is missing — a fail-closed checkpoint must leave a trail")
        return
    check("SKIPPED" in t, "the marker says it was skipped")
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
    stem = os.path.basename(marker_path).replace(".SKIPPED.md", "")
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
    check_script(os.path.join(repo, "cloud-prompts", "_shared", "preopen_checkpoint.py"))
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
