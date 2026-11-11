#!/usr/bin/env python3
"""
test_preopen_checkpoint_contract.py — prove the checker actually CATCHES breaches.

A checker that has only ever been seen passing is a CLAIM, not a guard. This file
renders a CONFORMING artifact set (which must PASS), then mutates it one thing at a
time (each of which must FAIL). Every mutation's text actually changes — a mutation
that does not alter the file reports a false "NOT CAUGHT" and hides a dead check.

The breach list is not invented: every case is a defect this checkpoint has actually
suffered or could suffer.

  * 2026-11-09 — a gainers-only movers scan published a tape with no decliners
    (IRTC -30.7%, DKNG -21.3% and AXON -18.2% were missing).
  * 2026-11-09 — two agents running the same slot against the same shared /workspace
    each appended 50 rows, so the tape held 100 rows for 53 tickers.
  * The src labels still said "grok" after the xAI path was retired, so the board's
    provenance split counted rows that came from neither Grok nor a scanner.
  * A literal `date +%H%M` names a late dispatch "0833" — a slot cron #17 never reads.

USAGE
    python3 test_preopen_checkpoint_contract.py [--repo <repo-root>]

EXIT CODES
  0 = every conforming case passed and every breach was caught
  1 = at least one case failed
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.abspath(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CHECKER = os.path.join(REPO, "tools", "check_preopen_checkpoint.py")
DIGEST = os.path.join(REPO, "cloud-prompts", "_shared", "preopen_digest.py")
SHARED_FILES = (
    "cloud-prompts/_shared/preopen-capture.md",
    "cloud-prompts/_shared/preopen_capture.py",
    "cloud-prompts/_shared/preopen_digest.py",
    "cloud-prompts/cron-prompts/92a-preopen-catalyst-capture-0830.md",
    "cloud-prompts/cron-prompts/92b-preopen-catalyst-capture-0950.md",
)

RESULTS = []


def run_checker(repo, tape=None, digest=None, skipped=None, slot="0830"):
    cmd = [sys.executable, CHECKER, "--repo", repo, "--slot", slot]
    if tape:
        cmd += ["--tape", tape]
    if digest:
        cmd += ["--digest", digest]
    if skipped:
        cmd += ["--skipped", skipped]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode, r.stdout


def record(name, expect_pass, rc, out):
    ok = (rc == 0) if expect_pass else (rc != 0)
    RESULTS.append((name, ok, rc, out))
    tag = "PASS" if ok else "FAIL"
    print(f"  {tag}  {name}  (checker exit {rc}, expected {'0' if expect_pass else 'non-zero'})")
    if not ok:
        for line in out.splitlines():
            if line.strip().startswith("FAIL"):
                print(f"        {line.strip()}")
    return ok


def make_repo(dst, src=REPO):
    """A writable copy of the files the checker reads."""
    for rel in SHARED_FILES:
        d = os.path.join(dst, rel)
        os.makedirs(os.path.dirname(d), exist_ok=True)
        shutil.copy(os.path.join(src, rel), d)
    return dst


def build_conforming(tmp, n_priced=20, n_narrative=30, date="2026-11-09", slot="0830"):
    """A real tape + board, rendered by the REAL digest renderer from a synthetic
    snapshot that has the same shape the capture script writes."""
    feed = os.path.join(tmp, "preopen-feed")
    os.makedirs(feed, exist_ok=True)
    tape = os.path.join(feed, f"{date}-{slot}.jsonl")
    digest = os.path.join(feed, f"{date}-{slot}.md")
    rows = []
    for i in range(n_priced):
        pct = round(40.0 - i * 1.7, 2) if i % 2 == 0 else round(-(40.0 - i * 1.7), 2)
        grounded = (i % 3 == 0)
        rows.append({
            "ts": "2026-11-09T08:47:31-05:00",
            "src": "pipeworx" if grounded else "scanner",
            "ticker": f"M{i:03d}",
            "name": f"Mover {i} Inc",
            "pct": pct,
            "price": round(10.0 + i, 2),
            "cat": "earnings" if grounded else "other",
            "why": f"reported Q3 results, beat and raised ({i})" if grounded else None,
            "ref": "https://example.com/x" if grounded else None,
            "conf": "high" if grounded else "low",
            "trending_ts": None,
            "trending_score": None,
            "volume": 1234567,
            "exchange": "NASDAQ",
            # WHEN the catalyst broke, and the article it came from. Every row
            # carries the keys; a grounded row carries a value.
            "news_date": "2026-11-09T11:30:00Z" if grounded else None,
            "news_url": ("https://news.example.test/m%d" % i) if grounded else None,
        })
    for i in range(n_narrative):
        rows.append({
            "ts": "2026-11-09T08:47:31-05:00",
            "src": "stocktwits",
            "ticker": f"N{i:03d}",
            "name": f"Narrative {i} Inc",
            "pct": None,
            "price": None,
            "cat": "other",
            "why": None if i % 5 == 0 else f"retail chatter about a catalyst ({i})",
            "ref": None,
            "conf": "low" if i % 5 == 0 else "medium",
            "trending_ts": "2026-11-09T08:17:43-05:00",
            "trending_score": 5.2,
            "volume": None,
            "exchange": None,
            "news_date": None,
            "news_url": None,
        })
    with open(tape, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    subprocess.run([sys.executable, DIGEST, "--tape", tape, "--out", digest,
                    "--date", date, "--slot", slot], capture_output=True, text=True, check=True)
    return tape, digest


def mutate(path, old, new, replace_all=False):
    """Replace `old` with `new` — and REFUSE if the file's bytes did not change.
    A mutation whose text does not actually change reports a false 'NOT CAUGHT'."""
    s = open(path, encoding="utf-8").read()
    if old not in s:
        raise AssertionError(f"mutation target not found in {path}: {old[:70]!r}")
    s2 = s.replace(old, new) if replace_all else s.replace(old, new, 1)
    if s2 == s:
        raise AssertionError("mutation did not change the file")
    open(path, "w", encoding="utf-8").write(s2)


def rewrite_rows(path, fn):
    """Rewrite the tape's rows through fn(list_of_dicts) -> list_of_dicts."""
    rows = [json.loads(l) for l in open(path, encoding="utf-8").read().splitlines() if l.strip()]
    out = fn(rows)
    with open(path, "w", encoding="utf-8") as fh:
        for r in out:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


# ---- the breach cases ---------------------------------------------------------
# Each case returns True if the mutation was applied.

def m_double_ticker(tape, digest, repo):
    """Two runs of the same slot wrote 100 rows for 53 tickers (2026-11-09)."""
    def fn(rows):
        dup = dict(rows[0])
        dup["ts"] = "2026-11-09T08:52:19-05:00"
        return rows + [dup]
    rewrite_rows(tape, fn)
    return True


def m_gainers_only(tape, digest, repo):
    """The gainers-only scan: no decliners on the tape (2026-11-09)."""
    rewrite_rows(tape, lambda rows: [r for r in rows if not (r.get("pct") or 0) < 0])
    return True


def m_src_grok(tape, digest, repo):
    """A retired xAI label still on a row."""
    rewrite_rows(tape, lambda rows: [dict(r, src="grok") for r in rows[:1]] + rows[1:])
    return True


def m_missing_key(tape, digest, repo):
    """A row that lost a contract key."""
    rewrite_rows(tape, lambda rows: [dict(r) for r in rows])
    rows = [json.loads(l) for l in open(tape, encoding="utf-8").read().splitlines() if l.strip()]
    rows[0].pop("conf", None)
    with open(tape, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    return True


def m_stray_key(tape, digest, repo):
    """A row with a key nobody agreed on."""
    rows = [json.loads(l) for l in open(tape, encoding="utf-8").read().splitlines() if l.strip()]
    rows[0]["mystery"] = 1
    with open(tape, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    return True


def m_priced_without_price(tape, digest, repo):
    """A priced row whose price is missing."""
    rows = [json.loads(l) for l in open(tape, encoding="utf-8").read().splitlines() if l.strip()]
    for r in rows:
        if r.get("pct") is not None:
            r["price"] = None
            break
    with open(tape, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    return True


def m_scanner_row_without_number(tape, digest, repo):
    """A row from the movers scan with no number."""
    rows = [json.loads(l) for l in open(tape, encoding="utf-8").read().splitlines() if l.strip()]
    for r in rows:
        if r.get("src") == "scanner":
            r["pct"] = None
            r["price"] = None
            break
    with open(tape, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    return True


def m_narrative_with_number(tape, digest, repo):
    """A narrative row that carries a price it cannot have."""
    rows = [json.loads(l) for l in open(tape, encoding="utf-8").read().splitlines() if l.strip()]
    for r in rows:
        if r.get("src") == "stocktwits":
            r["pct"] = 3.3
            r["price"] = 11.1
            break
    with open(tape, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    return True


def m_wrong_record_count(digest, tape, repo):
    mutate(digest, "**records:**", "**records:** 999")
    return True


def m_bad_order(digest, tape, repo):
    """Swap the first two body rows: the |%| ordering is broken."""
    lines = open(digest, encoding="utf-8").read().split("\n")
    idx = [i for i, l in enumerate(lines)
           if l.strip().startswith("|") and "---" not in l and "Ticker" not in l]
    if len(idx) < 2:
        raise AssertionError("no table rows found to swap")
    i, j = idx[0], idx[1]
    lines[i], lines[j] = lines[j], lines[i]
    open(digest, "w", encoding="utf-8").write("\n".join(lines))
    return True


def m_bad_conf(digest, tape, repo):
    mutate(digest, "| low |", "| certain |", replace_all=True)
    return True


def m_no_halt_state(digest, tape, repo):
    mutate(digest, "not measurable", "0 halts")
    return True


def m_wall_clock_slot(repo, tape, digest):
    """The procedure names the slot with the wall clock."""
    p = os.path.join(repo, "cloud-prompts", "_shared", "preopen-capture.md")
    mutate(p, "export CP=0830", "export CP=$(TZ=America/New_York date +%H%M)")
    return True


def m_no_losers_half(repo, tape, digest):
    """The procedure scans the gainers half only."""
    p = os.path.join(repo, "cloud-prompts", "_shared", "preopen-capture.md")
    mutate(p, "| `top_movers` (losers) | `market-recap` | the same ground truth for the other direction. |",
           "| (removed) | (removed) | (removed) |")
    return True


def m_no_both_directions(repo, tape, digest):
    p = os.path.join(repo, "cloud-prompts", "_shared", "preopen-capture.md")
    mutate(p, "BOTH directions", "one direction")
    return True


def m_append_instead_of_replace(repo, tape, digest):
    """The tape is appended to again — the doubling defect."""
    p = os.path.join(repo, "cloud-prompts", "_shared", "preopen_capture.py")
    mutate(p, "os.replace(tmp, out)", 'open(out, "a").write(body)')
    return True


def m_no_losers_call(repo, tape, digest):
    p = os.path.join(repo, "cloud-prompts", "_shared", "preopen_capture.py")
    mutate(p, 'call_top_movers(category="losers")', "call_top_movers()")
    return True


def m_prices_from_the_movers_scan(repo, tape, digest):
    """The capture prices the tape from the LAST COMPLETED session again.

    Measured 2026-11-09: 14 of 14 testable priced rows carried the previous session's
    close and move (IRTC -30.70% at 90.22) while TradingView's own pre-market for IRTC
    that morning was +0.86% at 91.00. A tape that prices itself from yesterday is the
    defect, and the checker must catch a script that goes back to it.
    """
    p = os.path.join(repo, "cloud-prompts", "_shared", "preopen_capture.py")
    mutate(p, '"pct": pr.get("pct"),', '"pct": (mv or {}).get("change_pct"),')
    return True


def m_no_version_marker(repo, tape, digest):
    p = os.path.join(repo, "cloud-prompts", "_shared", "preopen_capture.py")
    mutate(p, "CAPTURE_SCRIPT_VERSION: 2026-11-11.1", "CAPTURE_SCRIPT_VERSION:")
    return True


def m_slot_guard_removed(repo, tape, digest):
    p = os.path.join(repo, "cloud-prompts", "_shared", "preopen_capture.py")
    mutate(p, "ALLOWED_SLOTS = (\"0830\", \"0920\", \"0950\")", "ALLOWED_SLOTS = ()")
    return True


def m_stale_news_date(tape, digest, repo):
    """A catalyst dated ten months before the tape - the ARWR defect.

    Measured 2026-11-09 09:50: ARWR (-16.59%) carried Arrowhead's 2026-01-06 press
    release ("stock surging 17.81% to a new 52-week high") at `conf: high`. A
    catalyst that cannot be today's news is not a cause, and the tape must not be
    able to carry one.
    """
    rows = [json.loads(l) for l in open(tape, encoding="utf-8").read().splitlines() if l.strip()]
    for r in rows:
        if r.get("src") == "pipeworx":
            r["news_date"] = "2026-01-06T15:32:23Z"
            r["news_url"] = "https://news.example.test/stale"
            break
    with open(tape, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    return True


def m_undated_confident(tape, digest, repo):
    """A grounded catalyst published as high confidence with no date."""
    rows = [json.loads(l) for l in open(tape, encoding="utf-8").read().splitlines() if l.strip()]
    for r in rows:
        if r.get("src") == "pipeworx":
            r["news_date"] = None
            r["news_url"] = None
            break
    with open(tape, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    return True


def m_missing_news_date_key(tape, digest, repo):
    """A row with no news_date field at all."""
    rows = [json.loads(l) for l in open(tape, encoding="utf-8").read().splitlines() if l.strip()]
    rows[0].pop("news_date", None)
    with open(tape, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    return True


def m_board_shows_capture_clock(digest, tape, repo):
    """The board's 'When it broke' shows the CAPTURE clock instead of the news date.

    This is the exact defect the ARWR row exposed: the column fell back to `ts`,
    which is when the script ran, and so told a reader that a ten-month-old press
    release broke forty minutes ago.
    """
    mutate(digest, "06:30:00", "08:47:31", replace_all=True)
    return True


def m_no_staleness_gate(repo, tape, digest):
    """The capture script no longer dates its catalysts."""
    p = os.path.join(repo, "cloud-prompts", "_shared", "preopen_capture.py")
    # The gate is a CALL to resolve_news_date(); the checker also requires the tape
    # to carry the field, so the quoted key is what has to disappear.
    mutate(p, '"news_date": None,', '"news_dateX": None,')
    return True


def m_stale_window_drift(repo, tape, digest):
    """The script's staleness window no longer matches the checker's."""
    p = os.path.join(repo, "cloud-prompts", "_shared", "preopen_capture.py")
    mutate(p, "CATALYST_MAX_AGE_DAYS = 4", "CATALYST_MAX_AGE_DAYS = 400")
    return True


def m_board_ignores_news_date(repo, tape, digest):
    """The renderer stops reading news_date for its break-time column."""
    p = os.path.join(repo, "cloud-prompts", "_shared", "preopen_digest.py")
    mutate(p, 'broke = r.get("news_date") or r.get("trending_ts") or ""',
           'broke = r.get("trending_ts") or ""')
    return True


def m_published_date_not_age_checked(repo, tape, digest):
    """The script stops age-checking the PUBLISHED catalyst date.

    Measured 2026-11-11 08:30 ET: NOVT carried a catalyst dated 2026-02-22 (262 days
    old). The gate read the provider's NEWEST article, but the tape published the
    MATCHED article's stamp and that stamp was never checked. This mutation points the
    published-date check back at `freshest` - the defect - and the checker must catch
    the script, not just the tape.
    """
    p = os.path.join(repo, "cloud-prompts", "_shared", "preopen_capture.py")
    mutate(p, "_parse_iso(nd) if nd else None",
           "_parse_iso(freshest) if freshest else None")
    return True


CASES = [
    # (name, expect_pass, mutator)
    ("a conforming tape + board passes the checker", True, None),
    ("a doubled tape (one row per ticker) is caught", False, m_double_ticker),
    ("a gainers-only tape (no decliners) is caught", False, m_gainers_only),
    ("a retired src=grok label is caught", False, m_src_grok),
    ("a row missing a contract key is caught", False, m_missing_key),
    ("a row with an unexpected key is caught", False, m_stray_key),
    ("a priced row without a price is caught", False, m_priced_without_price),
    ("a movers-scan row without a number is caught", False, m_scanner_row_without_number),
    ("a narrative row carrying a number is caught", False, m_narrative_with_number),
    ("a wrong record count on the board is caught", False, m_wrong_record_count),
    ("a board out of |%| order is caught", False, m_bad_order),
    ("a board row with an unknown conf token is caught", False, m_bad_conf),
    ("a board that publishes a halt COUNT is caught", False, m_no_halt_state),
    ("a procedure that names the slot with the wall clock is caught", False, m_wall_clock_slot),
    ("a procedure that scans the gainers half only is caught", False, m_no_losers_half),
    ("a procedure that does not state BOTH directions is caught", False, m_no_both_directions),
    ("a capture script that appends instead of replacing is caught", False, m_append_instead_of_replace),
    ("a capture script with no losers call is caught", False, m_no_losers_call),
    ("a capture script that prices from the last completed session is caught", False,
     m_prices_from_the_movers_scan),
    ("a capture script with no version marker is caught", False, m_no_version_marker),
    ("a capture script with no slot guard is caught", False, m_slot_guard_removed),
    ("a catalyst dated outside the window is caught", False, m_stale_news_date),
    ("an undated catalyst published as high confidence is caught", False, m_undated_confident),
    ("a row with no news_date field is caught", False, m_missing_news_date_key),
    ("a board that shows the capture clock as the break time is caught", False, m_board_shows_capture_clock),
    ("a capture script with no staleness gate is caught", False, m_no_staleness_gate),
    ("a capture script whose staleness window drifted from the checker's is caught", False, m_stale_window_drift),
    ("a renderer that ignores news_date is caught", False, m_board_ignores_news_date),
    ("a capture script that does not age-check the PUBLISHED date is caught", False,
     m_published_date_not_age_checked),
]


def run_skip_cases():
    """The fail-closed trail: a marker with no reason, and a tape beside a marker."""
    tmp = tempfile.mkdtemp(prefix="preopen-skip-")
    repo = make_repo(os.path.join(tmp, "repo"))
    feed = os.path.join(tmp, "preopen-feed")
    os.makedirs(feed, exist_ok=True)

    # 1. a marker with no reason
    marker = os.path.join(feed, "2026-11-09-0830.SKIPPED.md")
    open(marker, "w", encoding="utf-8").write(
        "# Pre-open catalyst capture — SKIPPED\n\n- **Checkpoint:** 2026-11-09-0830\n")
    rc, out = run_checker(repo, skipped=marker, slot="0830")
    record("a skip marker with no reason is caught", False, rc, out)

    # 2. a tape written BESIDE a skip marker — the worst outcome: the consumer reads
    #    a tape that has no catalyst in it as "no news".
    open(marker, "w", encoding="utf-8").write(
        "# Pre-open catalyst capture — SKIPPED\n\n- **Reason:** PIPEWORX_API_KEY unset\n"
        "- **Checkpoint:** 2026-11-09-0830\n")
    open(os.path.join(feed, "2026-11-09-0830.jsonl"), "w", encoding="utf-8").write("{}\n")
    rc, out = run_checker(repo, skipped=marker, slot="0830")
    record("a tape written beside a skip marker is caught", False, rc, out)
    shutil.rmtree(tmp, ignore_errors=True)


def main():
    print("conforming artifacts MUST pass:")
    for name, expect_pass, mutator in CASES:
        tmp = tempfile.mkdtemp(prefix="preopen-contract-")
        try:
            repo = make_repo(os.path.join(tmp, "repo"))
            tape, digest = build_conforming(tmp)
            if mutator:
                if not mutator(tape, digest, repo):
                    raise AssertionError(f"mutation not applied for {name}")
            rc, out = run_checker(repo, tape=tape, digest=digest, slot="0830")
            record(name, expect_pass, rc, out)
        except Exception as exc:
            record(name, expect_pass, 1, str(exc))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    print("the fail-closed trail MUST be gated:")
    run_skip_cases()

    failed = [r for r in RESULTS if not r[1]]
    print()
    print(f"{len(RESULTS) - len(failed)}/{len(RESULTS)} cases behaved as required")
    if failed:
        print("FAILED cases:")
        for name, _, rc, _ in failed:
            print(f"  - {name}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
