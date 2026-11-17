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


def build_conforming(tmp, n_priced=20, n_narrative=30, date="2026-11-09", slot="0830",
                     grounded_mod=2):
    """A real tape + board, rendered by the REAL digest renderer from a synthetic
    snapshot that has the same shape the capture script writes.

    `grounded_mod` decides how many of the priced rows carry a catalyst (every
    `grounded_mod`-th one), so the fixture can be built either side of the MOVER
    COVERAGE FLOOR.

    THE ARITHMETIC IS THE POINT. The board publishes the top 15 rows by |%|, and
    with 20 priced rows those are the 15 biggest movers - so the gated metric is
    (the grounded rows among the first 15) / 15:

      * `grounded_mod=2` (the default) -> i = 0,2,4,6,8,10,12,14 -> 8 of 15 ->
        53% -> AT OR ABOVE THE 50% FLOOR, and the board carries NO banner;
      * `grounded_mod=4` -> i = 0,4,8,12 -> 4 of 15 -> 27% -> BELOW THE FLOOR.

    And the WHOLE-TAPE coverage of the default fixture is (8 + 30) / 50 = 76% - well
    above any floor. That is deliberate: the gate is on the MOVERS THE BOARD
    PUBLISHES, so a tape whose band looks well covered and whose published movers
    are mostly unexplained must still be DEGRADED. The context line alone must
    never satisfy the gate.
    """
    feed = os.path.join(tmp, "preopen-feed")
    os.makedirs(feed, exist_ok=True)
    tape = os.path.join(feed, f"{date}-{slot}.jsonl")
    digest = os.path.join(feed, f"{date}-{slot}.md")
    rows = []
    for i in range(n_priced):
        pct = round(40.0 - i * 1.7, 2) if i % 2 == 0 else round(-(40.0 - i * 1.7), 2)
        grounded = (i % grounded_mod == 0)
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
            # The pre-market DOLLAR behind the print, and the sign probe's verdict.
            "pm_notional": round(1234567 * (10.0 + i), 2),
            "sign_conflict": False,
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
            # A narrative row carries a REASON. A row with neither a number nor a
            # cause is not published at all, so the conforming tape has none.
            "why": f"retail chatter about a catalyst ({i})",
            "ref": None,
            "conf": "low",
            "trending_ts": "2026-11-09T08:17:43-05:00",
            "trending_score": 5.2,
            "volume": None,
            "exchange": None,
            "news_date": None,
            "news_url": None,
            "pm_notional": None,
            "sign_conflict": False,
        })
    with open(tape, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    subprocess.run([sys.executable, DIGEST, "--tape", tape, "--out", digest,
                    "--date", date, "--slot", slot], capture_output=True, text=True, check=True)
    return tape, digest


def build_low_coverage(tmp, date="2026-11-09", slot="0830"):
    """A CONFORMING tape whose MOVER COVERAGE is BELOW the 30% floor.

    20 priced rows, only every fourth one explained -> 4 of the 15 published movers
    carry a cause (27%), while the 30 narrative rows all carry a reason, so the
    WHOLE-TAPE coverage is 38/50 (76%) - comfortably above the floor it is not
    measured against. The board must render the mover coverage and raise the
    DEGRADED banner; the checker must accept it, because a degraded run that SAYS
    it degraded is a correct artifact.
    """
    return build_conforming(tmp, n_priced=20, n_narrative=30, date=date, slot=slot,
                            grounded_mod=4)


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


def m_wrong_record_count(tape, digest, repo):
    mutate(digest, "**records:**", "**records:** 999")
    return True


def m_bad_order(tape, digest, repo):
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


def m_bad_conf(tape, digest, repo):
    mutate(digest, "| low |", "| certain |", replace_all=True)
    return True


def m_no_halt_state(tape, digest, repo):
    mutate(digest, "not measurable", "0 halts")
    return True


def m_wall_clock_slot(tape, digest, repo):
    """The procedure names the slot with the wall clock."""
    p = os.path.join(repo, "cloud-prompts", "_shared", "preopen-capture.md")
    mutate(p, "export CP=0830", "export CP=$(TZ=America/New_York date +%H%M)")
    return True


def m_no_losers_half(tape, digest, repo):
    """The procedure scans the gainers half only."""
    p = os.path.join(repo, "cloud-prompts", "_shared", "preopen-capture.md")
    mutate(p, "| `top_movers` (losers) | `market-recap` | the same universe for the other "
               "direction. |",
           "| (removed) | (removed) | (removed) |")
    return True


def m_no_both_directions(tape, digest, repo):
    p = os.path.join(repo, "cloud-prompts", "_shared", "preopen-capture.md")
    mutate(p, "Both directions are mandatory", "One direction is enough")
    return True


def m_append_instead_of_replace(tape, digest, repo):
    """The tape is appended to again — the doubling defect."""
    p = os.path.join(repo, "cloud-prompts", "_shared", "preopen_capture.py")
    mutate(p, "os.replace(tmp, out)", 'open(out, "a").write(body)')
    return True


def m_no_losers_call(tape, digest, repo):
    p = os.path.join(repo, "cloud-prompts", "_shared", "preopen_capture.py")
    mutate(p, 'call_top_movers(category="losers")', "call_top_movers()")
    return True


def m_prices_from_the_movers_scan(tape, digest, repo):
    """The capture prices the tape from the LAST COMPLETED session again.

    Measured 2026-11-09: 14 of 14 testable priced rows carried the previous session's
    close and move (IRTC -30.70% at 90.22) while TradingView's own pre-market for IRTC
    that morning was +0.86% at 91.00. A tape that prices itself from yesterday is the
    defect, and the checker must catch a script that goes back to it.
    """
    p = os.path.join(repo, "cloud-prompts", "_shared", "preopen_capture.py")
    mutate(p, '"pct": pr.get("pct"),', '"pct": (mv or {}).get("change_pct"),')
    return True


def m_no_version_marker(tape, digest, repo):
    p = os.path.join(repo, "cloud-prompts", "_shared", "preopen_capture.py")
    # The target is DERIVED from the file, so the mutation can never go stale: a
    # literal version string in the test is a false PASS waiting to happen (see the
    # audit note in main()).
    s = open(p, encoding="utf-8").read()
    m = re.search(r"CAPTURE_SCRIPT_VERSION:\s*\d{4}-\d{2}-\d{2}\.\d+", s)
    if not m:
        raise AssertionError("the capture script carries no CAPTURE_SCRIPT_VERSION marker")
    mutate(p, m.group(0), "CAPTURE_SCRIPT_VERSION:")
    return True


def m_chatter_high(tape, digest, repo):
    """A RETAIL-CHATTER reason published as high confidence with no date.

    Measured 2026-11-12: 10 of the tape's 12 "high" rows were exactly this - a
    stocktwits reason with no publication stamp and no article behind it. The
    checker's rule used to be scoped to the pipeworx provenance, so they passed
    unchecked. An undated catalyst may only ever ride at "low".
    """
    rows = [json.loads(l) for l in open(tape, encoding="utf-8").read().splitlines() if l.strip()]
    for r in rows:
        if r.get("src") == "stocktwits" and r.get("why"):
            r["conf"] = "high"
            break
    with open(tape, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    return True


def m_sign_conflict_high(tape, digest, repo):
    """A catalyst that CONTRADICTS its move, published as high confidence.

    Measured 2026-11-12: DGII (-20.50%) carried "beat Q4 2026 earnings
    expectations" at `conf: high` WITH a date. The price was right, the cause was
    not, and cron #17 reads that text at 15:50 as THE reason. A contradicted cause
    must be demoted.
    """
    rows = [json.loads(l) for l in open(tape, encoding="utf-8").read().splitlines() if l.strip()]
    for r in rows:
        if r.get("src") == "pipeworx":
            r["sign_conflict"] = True
            r["conf"] = "high"
            break
    with open(tape, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    return True


def m_empty_row(tape, digest, repo):
    """A row with NEITHER a number NOR a cause.

    Measured 2026-11-12: 11 of the tape's 45 rows were exactly this. Such a row
    says nothing a reader can use, and every consumer pays to carry it.
    """
    rows = [json.loads(l) for l in open(tape, encoding="utf-8").read().splitlines() if l.strip()]
    rows.append({
        "ts": "2026-11-09T08:47:31-05:00", "src": "stocktwits", "ticker": "Z999",
        "name": "Nothing Inc", "pct": None, "price": None, "cat": "other", "why": None,
        "ref": None, "conf": "low", "trending_ts": None, "trending_score": None,
        "volume": None, "exchange": None, "news_date": None, "news_url": None,
        "pm_notional": None, "sign_conflict": False,
    })
    with open(tape, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    return True


def m_missing_pm_notional(tape, digest, repo):
    """A row with no pre-market notional.

    The notional is what tells a consumer which of the survivors was real: measured
    2026-11-13, 10 of the board's 15 rows sat on under $3M of pre-market notional.
    """
    rows = [json.loads(l) for l in open(tape, encoding="utf-8").read().splitlines() if l.strip()]
    for r in rows:
        if r.get("pct") is not None:
            r.pop("pm_notional", None)
            break
    with open(tape, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    return True


def m_router_before_article(tape, digest, repo):
    """The capture consults the ROUTER before the article feed.

    The order is the point: the feed answers in 0.21-0.24s with a date AND a URL,
    while the router takes 15-25s and refuses more often than it answers (measured
    2026-11-13: its own polygon path errored on 4 of 8 names the feed served). A
    capture that spends the router first spends 98% of its wall clock there.
    """
    p = os.path.join(repo, "cloud-prompts", "_shared", "preopen_capture.py")
    mutate(p, "art = dict(zip(pool, ex.map(lambda t: article_catalyst(t, cutoff), pool)))",
           "art = {}")
    mutate(p, "gnd = dict(zip(need, ex.map(lambda t: call_grounded(t, names.get(t)), need)))",
           "gnd = dict(zip(need, ex.map(lambda t: call_grounded(t, names.get(t)), need)))"
           "  # router first")
    return True


def m_no_parallelism(tape, digest, repo):
    """The capture runs its catalyst calls one at a time.

    Measured 2026-11-13: the sequential grounded calls were ~264s of the capture's
    270s - 98% of it - while 8 concurrent calls took 20.2s against 101.8s serial.
    """
    p = os.path.join(repo, "cloud-prompts", "_shared", "preopen_capture.py")
    mutate(p, "CATALYST_WORKERS = 8", "CATALYST_WORKERS = 0")
    mutate(p, "with _cf.ThreadPoolExecutor(max_workers=CATALYST_WORKERS) as ex:",
           "with _cf.ThreadPoolExecutor(max_workers=1) as ex:")
    return True


def m_script_assigns_high(tape, digest, repo):
    """The capture ASSIGNS a 'high' confidence at row creation.

    A row's confidence may only be raised by a DATED, in-window catalyst. If the
    script hands out 'high' by default, a retail-chatter reason rides at 'high'
    unchecked - measured 2026-11-12, 10 of the tape's 12 'high' rows.
    """
    p = os.path.join(repo, "cloud-prompts", "_shared", "preopen_capture.py")
    mutate(p, '"conf": "low",', '"conf": "high",', replace_all=True)
    return True



def m_credit_failure_ignored(tape, digest, repo):
    """The capture stops recognising a CREDIT failure.

    The gateway answers an exhausted account with "Insufficient credits. This tool
    costs 200 credits" - which looks like an empty result to a caller that cannot
    tell them apart. A capture that cannot tell them apart publishes a tape with
    NO catalysts and reports no error: the tape looks like a quiet pre-market, and
    the quiet is a lie.
    """
    p = os.path.join(repo, "cloud-prompts", "_shared", "preopen_capture.py")
    mutate(p, "CREDIT_MARKERS = (\"insufficient credit\", \"paid feature\", \"free allowance\",\n"
               "                  \"purchase more\", \"upgrade your plan\")",
           "CREDIT_MARKERS = ()")
    return True



def m_no_band_call(tape, digest, repo):
    """The capture stops taking its candidates from TODAY's pre-market band.

    The band is what makes the tape able to serve a brief: the 2026-11-10 tape carried
    49 rows and covered 6 of the 50 names the brief published, because the candidate
    source was Yahoo's `top_movers` - a screener over the LAST COMPLETED session.
    A capture that goes back to that has to be caught.
    """
    p = os.path.join(repo, "cloud-prompts", "_shared", "preopen_capture.py")
    mutate(p, "band = call_scanner_band()", 'band = {"rows": {}, "total": 0}')
    return True


def m_no_share_floor(tape, digest, repo):
    """The capture stops dropping a pre-market print below the absolute share floor.

    Below 25,000 pre-market shares is a quote, not a market - and it is the same
    number cron #25's fourth gate leg uses. A capture that drops the floor fills the
    tape with prints that the brief will throw away anyway.
    """
    p = os.path.join(repo, "cloud-prompts", "_shared", "preopen_capture.py")
    mutate(p, "MIN_PM_SHARES = 25_000", "MIN_PM_SHARES = 0")
    mutate(p, "pm_shares(pm_rows[tk]) < MIN_PM_SHARES", "False")
    return True


def m_slot_guard_removed(tape, digest, repo):
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


def m_board_shows_capture_clock(tape, digest, repo):
    """The board's 'When it broke' shows the CAPTURE clock instead of the news date.

    This is the exact defect the ARWR row exposed: the column fell back to `ts`,
    which is when the script ran, and so told a reader that a ten-month-old press
    release broke forty minutes ago.
    """
    mutate(digest, "06:30:00", "08:47:31", replace_all=True)
    return True


def m_no_staleness_gate(tape, digest, repo):
    """The capture script no longer dates its catalysts."""
    p = os.path.join(repo, "cloud-prompts", "_shared", "preopen_capture.py")
    # The gate is a CALL to resolve_news_date(); the checker also requires the tape
    # to carry the field, so the quoted key is what has to disappear.
    # The gate is the DATEING: the call to resolve_news_date() and the field it
    # writes. Removing the name (everywhere) takes both away, and the checker must
    # catch a script that no longer dates its catalysts.
    mutate(p, "resolve_news_date", "resolve_news_dateX", replace_all=True)
    return True


def m_stale_window_drift(tape, digest, repo):
    """The script's staleness window no longer matches the checker's."""
    p = os.path.join(repo, "cloud-prompts", "_shared", "preopen_capture.py")
    mutate(p, "CATALYST_MAX_AGE_DAYS = 4", "CATALYST_MAX_AGE_DAYS = 400")
    return True


def m_board_ignores_news_date(tape, digest, repo):
    """The renderer stops reading news_date for its break-time column."""
    p = os.path.join(repo, "cloud-prompts", "_shared", "preopen_digest.py")
    mutate(p, 'broke = r.get("news_date") or r.get("trending_ts") or ""',
           'broke = r.get("trending_ts") or ""')
    return True


def m_published_date_not_age_checked(tape, digest, repo):
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


def m_capture_stops_counting_the_degradation(tape, digest, repo):
    """The capture stops counting a mover-coverage degradation as an error.

    The floor is a DEGRADATION, and a degradation the run does not count is a
    footnote. Measured 2026-11-13: the board explained 4 of the 15 movers it
    published and the checkpoint reported nothing about it.
    """
    p = os.path.join(repo, "cloud-prompts", "_shared", "preopen_capture.py")
    mutate(p,
           'errors.append(f"mover_coverage_below_floor: {cov_detail}")',
           'pass  # the coverage degradation is no longer counted as an error')
    return True


def m_capture_counts_the_degradation_twice(tape, digest, repo):
    """The capture counts the SAME degradation TWICE.

    The degradation is counted in the capture's own ledger, so the reply's
    `errors:` number is measured rather than remembered. A ledger that counts it
    twice reports a failure the run did not have - and the number a reader reads is
    the number that has to be right.
    """
    p = os.path.join(repo, "cloud-prompts", "_shared", "preopen_capture.py")
    mutate(p,
           'errors.append(f"mover_coverage_below_floor: {cov_detail}")',
           'errors.append(f"mover_coverage_below_floor: {cov_detail}")\n'
           '        errors.append(f"mover_coverage_below_floor: {cov_detail}")')
    return True


def m_no_coverage_line(tape, digest, repo):
    """The board stops publishing the GATED mover coverage.

    A board that quietly stops publishing its coverage is exactly the silent
    failure the rule exists to stop: the tape priced the movers, explained almost
    none of them, and said nothing.
    """
    s = open(digest, encoding="utf-8").read()
    lines = s.splitlines(True)
    hit = [i for i, l in enumerate(lines) if "**mover coverage:**" in l]
    if not hit:
        raise AssertionError("the fixture board carries no mover-coverage line to remove")
    del lines[hit[0]]
    out = "".join(lines)
    if out == s:
        raise AssertionError("the mutation did not change the board")
    open(digest, "w", encoding="utf-8").write(out)
    return True


def m_context_line_alone(tape, digest, repo):
    """The board publishes the WHOLE-TAPE context line and NOTHING else.

    The context line is not the gate. A board that dropped the gated number and
    kept the context number has stopped measuring what the reader reads, and the
    checker must catch it - otherwise the gate is satisfied by a statistic about
    the band's width.
    """
    s = open(digest, encoding="utf-8").read()
    lines = s.splitlines(True)
    hit = [i for i, l in enumerate(lines) if "**mover coverage:**" in l]
    if not hit:
        raise AssertionError("the fixture board carries no mover-coverage line to remove")
    del lines[hit[0]]
    out = "".join(lines)
    if out == s:
        raise AssertionError("the mutation did not change the board")
    open(digest, "w", encoding="utf-8").write(out)
    return True


def m_whole_tape_numbers_in_the_gated_line(tape, digest, repo):
    """The gated line publishes the WHOLE TAPE's numbers instead of the table's.

    The metric is the coverage of the MOVERS THE BOARD PUBLISHES. A board that
    publishes the whole tape's numbers in the gated line is measuring the wrong
    thing - the denominator is the published table, and a reader who checks the
    arithmetic finds a number about a different set of rows.
    """
    s = open(digest, encoding="utf-8").read()
    m = re.search(r"\*\*mover coverage:\*\*\s*(\d+)\s*/\s*(\d+)\s*\((\d+)%\)", s)
    if not m:
        raise AssertionError("the fixture board carries no mover-coverage line")
    rows = [json.loads(l) for l in open(tape, encoding="utf-8").read().splitlines() if l.strip()]
    whole_named = sum(1 for r in rows if r.get("why"))
    whole_total = len(rows)
    whole_pct = int(round(100.0 * whole_named / whole_total))
    out = (s[:m.start()] + f"**mover coverage:** {whole_named}/{whole_total} ({whole_pct}%)"
           + s[m.end():])
    if out == s:
        raise AssertionError("the mutation did not change the board")
    open(digest, "w", encoding="utf-8").write(out)
    return True


def m_wrong_coverage_arithmetic(tape, digest, repo):
    """The board publishes a mover coverage the published table cannot support.

    The percentage is not decoration: it is (explained published movers / published
    movers), and a board whose numerator does not match its own table is a
    measurement that cannot be audited.
    """
    s = open(digest, encoding="utf-8").read()
    m = re.search(r"\*\*mover coverage:\*\*\s*(\d+)\s*/\s*(\d+)\s*\((\d+)%\)", s)
    if not m:
        raise AssertionError("the fixture board carries no mover-coverage line")
    named, total, pct = m.group(1), m.group(2), m.group(3)
    out = (s[:m.start()] + f"**mover coverage:** {int(named) + 7}/{total} ({pct}%)"
           + s[m.end():])
    if out == s:
        raise AssertionError("the mutation did not change the board")
    open(digest, "w", encoding="utf-8").write(out)
    return True


def m_no_degradation_banner(tape, digest, repo):
    """A below-floor board with the DEGRADED banner removed.

    The degradation has to be visible in the .md a reader OPENS, not only in the
    reply. A board that measures the coverage and stays quiet about it is the
    2026-11-13 failure with a number attached.
    """
    s = open(digest, encoding="utf-8").read()
    lines = s.splitlines(True)
    # the banner is the quoted block above the table (the "> " lines)
    hit = [i for i, l in enumerate(lines) if l.startswith("> ")]
    if not hit:
        raise AssertionError("the fixture board carries no degradation banner")
    for i in reversed(hit):
        del lines[i]
    out = "".join(lines)
    if out == s:
        raise AssertionError("the mutation did not change the board")
    open(digest, "w", encoding="utf-8").write(out)
    return True


def m_degraded_banner_on_a_healthy_board(tape, digest, repo):
    """A board AT the floor that carries a degradation banner.

    The banner has to mean something: a board at or above the floor that cries
    wolf trains the reader to ignore the word.
    """
    s = open(digest, encoding="utf-8").read()
    lines = s.splitlines(True)
    idx = next((i for i, l in enumerate(lines) if l.startswith("# Pre-open")), None)
    if idx is None:
        raise AssertionError("the fixture board has no title line")
    lines.insert(idx + 1, "> ⚠ **DEGRADED — catalyst coverage is below the floor.**\n")
    out = "".join(lines)
    if out == s:
        raise AssertionError("the mutation did not change the board")
    open(digest, "w", encoding="utf-8").write(out)
    return True


def m_renderer_drops_the_coverage_line(tape, digest, repo):
    """The renderer stops publishing the catalyst coverage."""
    p = os.path.join(repo, "cloud-prompts", "_shared", "preopen_digest.py")
    # EVERY occurrence: the renderer prints the gated line in two branches (the
    # normal one and the no-movers-table one), and a mutation that only hit the
    # first would leave the second publishing the line - a false PASS.
    mutate(p, "**mover coverage:**", "**mover pct:**", replace_all=True)
    return True


def m_procedure_drops_the_floor(tape, digest, repo):
    """The procedure lowers the floor out of the record."""
    p = os.path.join(repo, "cloud-prompts", "_shared", "preopen-capture.md")
    mutate(p, "MOVER_COVERAGE_FLOOR = 0.30", "MOVER_COVERAGE_FLOOR = 0.05")
    return True



# ---- the retry-policy breaches (2026-11-17) ----------------------------------
#
# The retry policy is asserted on the capture's SOURCE by check_script(). These
# cases are the other half: they prove the gates BITE - that a capture which gives
# the policy up is caught by the checker, and not merely described.


def m_no_router_retry(tape, digest, repo):
    """The capture asks the grounded router for a name exactly ONCE.

    Measured 2026-11-17: called ONE AT A TIME, the router answered 4 of 5 calls for
    AKAN (confidence 0.85-0.95) and 3 of 5 for GP (0.95) - the same names that came
    back refused when they were fired eight-wide. The capability was always there.
    `call_grounded` made one call, so the 2026-11-16 checkpoints explained 2 of the
    15 movers they published (13%, under the 30% floor) - at 08:30 AND at 09:50.
    A capture that asks the cheap leg once is asking it once for no reason.
    """
    p = os.path.join(repo, "cloud-prompts", "_shared", "preopen_capture.py")
    mutate(p, "ROUTER_ATTEMPTS = 3", "ROUTER_ATTEMPTS = 1")
    return True


def m_feed_retries_forever(tape, digest, repo):
    """The metered article feed never stops on a repeated identical error.

    An article call is 200 CREDITS. Measured 2026-11-17: DVLT's feed answered
    `tool_error` on 4 of 4 calls and a bare empty result on a fifth - the index does
    not exist. Three identical failures cost 600 credits and return the same nothing,
    so the third attempt is spent only when the error CHANGED.
    """
    p = os.path.join(repo, "cloud-prompts", "_shared", "preopen_capture.py")
    mutate(p, "        if err == last_err and i + 1 < attempts:", "        if False:")
    return True


def m_router_errors_uncounted(tape, digest, repo):
    """The capture does not COUNT the router's failures.

    They used to be invisible: a name the router refused recorded the ARTICLE's
    error, so the 2026-11-16 08:30 checkpoint - 10 article errors and 13 router
    refusals - reported ONE distinct provider error. Thirteen published movers lost
    their explanations to a provider hiccup while the reply's `errors:` number did
    not move. A quiet tape with a loud error beats a loud-looking tape with a silent
    one.
    """
    p = os.path.join(repo, "cloud-prompts", "_shared", "preopen_capture.py")
    mutate(p, '    errors += sorted({c.get("router_error") for c in cats.values() if c.get("router_error")})',
           '    pass  # the router errors are not counted')
    return True



# ---- the source-of-record and the corrected-cause breaches (2026-11-17) --------


def m_no_edgar_source(tape, digest, repo):
    """The capture stops using SEC EDGAR - the SOURCE OF RECORD.

    Measured 2026-11-17: the news vendor's ticker index held NO in-window article
    for ANY of the 13 movers the 2026-11-16 checkpoints could not explain (eight
    had zero articles ever; AKAN's newest was from 2024), while EIGHT of the same
    thirteen had a catalyst-bearing filing in EDGAR inside the window - DVLT's
    Nasdaq trading suspension, CGON's PIVOT-006 Phase 3 readout, LXEO's interim
    data. A capture with no source of record for the filings that ARE the news
    cannot clear its own floor.
    """
    p = os.path.join(repo, "cloud-prompts", "_shared", "preopen_capture.py")
    mutate(p, 'EDGAR_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"',
           'EDGAR_SEARCH_URL = "https://example.invalid/search"')
    mutate(p, 'EDGAR_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"',
           'EDGAR_TICKERS_URL = "https://example.invalid/tickers.json"')
    mutate(p, "ex.map(lambda t: edgar_catalyst(t, cutoff, ciks), need_edgar))",
           "ex.map(lambda t: None, need_edgar))")
    mutate(p, '"origin": "edgar"', '"origin": "none"')
    return True


def m_no_size_split(tape, digest, repo):
    """The board stops publishing the SIZE SPLIT.

    The split is CONTEXT, and it is why the coverage is what it is: a board whose
    movers are overwhelmingly micro-caps is a board the news vendor cannot cover.
    A split line that VANISHES is the same silent failure as a coverage line that
    vanishes - the reader is left with a percentage and no population.
    """
    s = open(digest, encoding="utf-8").read()
    lines = s.splitlines(True)
    hit = [i for i, l in enumerate(lines) if "Size split of the published movers" in l]
    if not hit:
        raise AssertionError("the fixture board carries no size split")
    for i in reversed(hit):
        del lines[i]
    out = "".join(lines)
    if out == s:
        raise AssertionError("the mutation did not change the board")
    open(digest, "w", encoding="utf-8").write(out)
    return True


def m_budget_cause_restored(tape, digest, repo):
    """The board goes back to blaming the CATALYST BUDGET.

    It said "the catalyst budget did not reach them" on 2026-11-16, and that was
    FALSE: the pool is the top N by |%|, the table is the top 15 of the same
    ranking, and all fifteen had a router call. The real cause was the provider's
    ticker index. A board that names the wrong cause sends the reader looking for
    a budget problem that does not exist.
    """
    s = open(digest, encoding="utf-8").read()
    # The rendered cause text wraps across lines, so the target is an unbroken
    # fragment of it - a mutation whose target does not exist is reported as a
    # failure by the harness, never as a false pass.
    out = s.replace("the catalyst pool is sized to cover every mover this",
                    "the catalyst budget did not reach them")
    if out == s:
        raise AssertionError("the fixture board does not carry the corrected cause")
    open(digest, "w", encoding="utf-8").write(out)
    return True


CASES = [
    # (name, expect_pass, mutator, fixture_builder)
    ("a conforming tape + board passes the checker", True, None),
    ("a conforming tape BELOW the mover-coverage floor passes the checker (it says it "
     "degraded)", True, None, build_low_coverage),
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
    ("a capture script that does not take its candidates from the pre-market band is caught",
     False, m_no_band_call),
    ("a capture script with no absolute pre-market share floor is caught", False,
     m_no_share_floor),
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
    ("a retail-chatter reason published as high confidence is caught", False, m_chatter_high),
    ("a catalyst that contradicts its move at high confidence is caught", False,
     m_sign_conflict_high),
    ("a row with neither a number nor a cause is caught", False, m_empty_row),
    ("a row with no pre-market notional is caught", False, m_missing_pm_notional),
    ("a capture script that consults the router before the article feed is caught", False,
     m_router_before_article),
    ("a capture script that runs its catalyst calls one at a time is caught", False,
     m_no_parallelism),
    ("a capture script that assigns 'high' confidence at row creation is caught", False,
     m_script_assigns_high),
    ("a capture script that cannot tell a credit failure from 'no news' is caught", False,
     m_credit_failure_ignored),
    # THE MOVER COVERAGE FLOOR - the GATED metric.
    ("a board that stops publishing the gated mover coverage is caught", False,
     m_no_coverage_line),
    ("a board that publishes ONLY the whole-tape context line is caught", False,
     m_context_line_alone, build_low_coverage),
    ("a gated line that publishes the WHOLE TAPE's numbers is caught", False,
     m_whole_tape_numbers_in_the_gated_line),
    ("a board whose mover-coverage arithmetic does not match its published table is caught",
     False, m_wrong_coverage_arithmetic),
    ("a below-floor board with the DEGRADED banner removed is caught", False,
     m_no_degradation_banner, build_low_coverage),
    ("a board at the floor that carries a DEGRADED banner is caught", False,
     m_degraded_banner_on_a_healthy_board),
    ("a renderer that stops publishing the coverage line is caught", False,
     m_renderer_drops_the_coverage_line),
    ("a procedure that drops the coverage floor is caught", False,
     m_procedure_drops_the_floor),
    ("a capture that stops counting a coverage degradation as an error is caught", False,
     m_capture_stops_counting_the_degradation),
    ("a capture that counts the coverage degradation TWICE is caught", False,
     m_capture_counts_the_degradation_twice),
    # THE RETRY POLICY AND THE TWO LEGS' ACCOUNTING (2026-11-17).
    ("a capture that asks the grounded router ONCE is caught", False, m_no_router_retry),
    ("a capture that does not stop the metered feed on a repeated error is caught", False,
     m_feed_retries_forever),
    ("a capture that does not COUNT the router's failures is caught", False,
     m_router_errors_uncounted),
    # THE SOURCE OF RECORD AND THE CORRECTED CAUSE (2026-11-17).
    ("a capture that stops using SEC EDGAR as its source of record is caught", False,
     m_no_edgar_source),
    ("a board that stops publishing the SIZE SPLIT is caught", False,
     m_no_size_split),
    ("a board that blames the CATALYST BUDGET again is caught", False,
     m_budget_cause_restored, build_low_coverage),
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
    for case in CASES:
        name, expect_pass, mutator = case[0], case[1], case[2]
        builder = case[3] if len(case) > 3 else build_conforming
        tmp = tempfile.mkdtemp(prefix="preopen-contract-")
        try:
            repo = make_repo(os.path.join(tmp, "repo"))
            tape, digest = builder(tmp)
            if mutator:
                if not mutator(tape, digest, repo):
                    raise AssertionError(f"mutation not applied for {name}")
            rc, out = run_checker(repo, tape=tape, digest=digest, slot="0830")
            record(name, expect_pass, rc, out)
        except Exception as exc:
            # A mutation that could not be APPLIED is not a checker verdict - it is a
            # broken test. Recording it as "caught" (rc=1 against an expected catch)
            # is a FALSE PASS: the case goes green without the checker ever running.
            # The 2026-11-12 audit found one: the version-marker mutation targeted
            # `CAPTURE_SCRIPT_VERSION: 2026-11-11.1` while the script carried
            # `2026-11-11.2`, so mutate() raised and the case "passed" vacuously.
            print(f"  FAIL  {name}  (the mutation could not be applied: {exc})")
            RESULTS.append((name, False, 1, str(exc)))
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
