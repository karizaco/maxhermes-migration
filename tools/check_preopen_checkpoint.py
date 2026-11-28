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

# CHECKER_VERSION: 2026-11-28.1
#
# THE VERSION MARKER. Every other run-time dependency in this fleet carries one -
# CAPTURE_SCRIPT_VERSION (capture), PREOPEN_DIGEST_V2 / PREOPEN_EDGAR_DATE_V1
# (renderer), PUSH_ARTIFACT_VERSION (push helper), WINDOW_CHECK_V2 (window check) -
# so a fetch ladder can demand it and a STALE COPY CANNOT WIN. The checker was the
# ONE exception: the procedure referenced it three times and never fetched it, and it
# carried no marker, so a copy from any earlier day could be run in its place
# silently. Measured 2026-11-19: the sandbox carried the 2026-11-16 gate, which
# failed a CORRECT board and, worse, demanded the 2026-11-15.1 capture script - the
# build with NO SEC EDGAR leg, the one that cannot clear the mover-coverage floor.
# The marker is what makes that failure impossible to repeat.
#
# 2026-11-26.1 adds THE ANCHOR RULE: a tape carries the close its moves were measured
# against, and the gate checks that the tape agrees with it. Measured 2026-11-26: this
# gate, run against the tape the capture wrote on THANKSGIVING with the NYSE closed,
# PASSED all 179 of its checks - on a tape where 15.3% of the priced rows had a
# FLIPPED sign and the worst was off by 177 points. The gate verified the tape's SHAPE
# and never asked whether its MOVES were real. Now it does.
CHECKER_VERSION = "2026-11-28.1"

import argparse
import datetime
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
TAPE_EXTRA_KEYS = ["trending_ts", "trending_score", "volume", "exchange", "grounded_tool",
                    "news_date", "news_url", "pm_notional", "sign_conflict", "sentiment",
                    # THE ANCHOR (2026-11-26): the close the row's move was measured
                    # against, as the scanner published it. Additive - cron #17's
                    # consumer reads the keys it knows and ignores the rest.
                    "ref_close",
                    # THE ANCHOR MODE (2026-11-28): WHICH STATE the capture was in when
                    # it wrote the row - `aligned` (the scanner's `close` WAS the
                    # previous close) or `rolled` (the regular session was already open,
                    # so the scanner's `close` was a LIVE price and the anchor is the
                    # provider's implied reference instead) - and the scanner's
                    # published close beside it. The gap between the two IS the
                    # evidence that the session rolled, so the gate can check a rolled
                    # tape offline, exactly like an aligned one.
                    "ref_mode", "ref_scanner_close"]
# How old a catalyst may be and still explain a move that happened today. This MUST
# equal the capture script's own CATALYST_MAX_AGE_DAYS - check_script() asserts it,
# because a gate that reads a different window than the one that wrote the tape
# checks nothing.
CATALYST_MAX_AGE_DAYS = 4
# A date-only stamp: "2026-11-16" and nothing else. SEC EDGAR's filing dates arrive in
# exactly this shape, and they are why the board needs a date branch at all.
_DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# THE DATE CONTRACT — the marker a board carries when it renders a date-only catalyst as
# a DATE. A board that carries it is checked against the CURRENT rule; a board that
# carries NO marker was written before the rule existed and is GRANDFATHERED against it.
DATE_CONTRACT = "preopen-dates-v1"
# The day the date rule took effect. EDGAR (2026-11-17) is what introduced date-only
# `news_date` values into the tape, so that is the first day a board can carry a
# date-only catalyst at all - and the first day the rule is enforced. A board published
# before it is grandfathered.
DATE_RULE_EFFECTIVE = "2026-11-17"
# The capture script the procedure must demand. The version moves when the capture's
# MEASURED OUTPUT changes, so a stale copy cannot win the fetch ladder and publish a
# different number than the board.
CAPTURE_VERSION = "2026-11-28.1"
# ---------------------------------------------------------------------------
# THE ANCHOR RULE (2026-11-26).
# ---------------------------------------------------------------------------
# TradingView measures `premarket_change` against the PREVIOUS close, and the scanner
# publishes that same previous close in its `close` column. So on a live pre-market
# session the tape's own numbers satisfy
#
#     premarket_close / (1 + premarket_change/100)  ==  close
#
# and when the market is SHUT the scanner does not roll the pre-market session
# forward: it keeps serving the PREVIOUS session's anchor, so every move on the tape
# is measured from the wrong base.
#
# Measured 2026-11-26 (Thanksgiving, the NYSE closed): 242 of 242 tickers shared the
# previous tape's implied reference, 62% of the priced rows were wrong by more than a
# point, 15.3% had a FLIPPED SIGN, and the worst was off by 177 points. The band came
# back 168 up / 951 down - 85% decliners - which is an artifact of the stale base and
# not a market. AND THIS GATE PASSED ALL 179 OF ITS CHECKS on that tape, because every
# rule it had was about the tape's SHAPE and none of them asked whether a MOVE was real.
#
# So the tape now carries the anchor (`ref_close`) on every priced row, and the gate
# checks the tape against it. A stale-anchored tape FAILS instead of being published.
#
# The rule is GRANDFATHERED for tapes written before the capture started carrying the
# anchor: a historical artifact is never failed for a rule that post-dates it. Same
# shape as the date contract and the coverage floor.
ANCHOR_RULE_EFFECTIVE = "2026-11-27"
# THE ANCHOR MODE RULE (2026-11-28). The anchor rule above is instant-bound: the
# scanner's `close` column IS the previous close only while the PRE-MARKET session is
# live. The 09:50 slot fires twenty minutes after the open, where that column is a live
# price - so from 2026-11-28 a tape states which state it was written in, and carries
# the scanner's published close beside its anchor. A tape dated before this day is
# grandfathered, like every other rule here.
ANCHOR_MODE_EFFECTIVE = "2026-11-28"
# The share of priced rows whose implied reference must agree with their own anchor.
# On a live session it is ~100%; on a stale anchor it is ~0% (measured: 11%).
ANCHOR_MATCH_FLOOR = 0.90
# The relative tolerance: the implied reference is rebuilt from a ROUNDED percentage,
# so it is compared relatively, not exactly.
ANCHOR_TOLERANCE = 0.005
# THE REPO CONTEXT the gate reads its static sources from. The gate is not hermetic:
# it checks the procedure, the capture script, the renderer AND the two cron prompts
# the fleet deploys. A missing one is a PRECONDITION failure, not a check failure -
# see main().
REPO_CONTEXT = (
    ("cloud-prompts", "_shared", "preopen-capture.md"),
    ("cloud-prompts", "_shared", "preopen_capture.py"),
    ("cloud-prompts", "_shared", "preopen_digest.py"),
    ("cloud-prompts", "cron-prompts", "92a-preopen-catalyst-capture-0830.md"),
    ("cloud-prompts", "cron-prompts", "92b-preopen-catalyst-capture-0950.md"),
)
# THE MOVER COVERAGE FLOOR - the share of the MOVERS THE BOARD PUBLISHES that must
# carry a cause for the board to be doing its job.
#
# The metric is READER-FACING on purpose. The reader does not read 164 tape records;
# the reader reads the digest's top-movers table - the 15 rows the board publishes,
# the rows the trader acts on. Measured on Friday 2026-11-13 under this metric: 4 of
# the 15 published movers carried a catalyst at 08:30 (27%) and 6 of 15 at 09:50
# (40%) - both below the floor.
#
# The floor is 30%, and it is REACHABLE against the MEASURED answer rate: a 15-row
# movers table needs 5 explained movers (4/15 = 26.7% is below it; 5/15 = 33.3%
# clears it), and the catalyst pool (--top 20) is ranked by |%| in the same order
# the table is published, so a budget spent on the published movers can explain 8
# of 15. MEASURED on Friday 2026-11-13: 27% at 08:30 (BELOW) and 40% at 09:50
# (CLEARS) - the floor sits between the two real checkpoints, which is where a
# floor belongs: it fires when the provider answered for too few of the movers
# the board shows, and it stays quiet when it answered for enough of them.
#
# The WHOLE-TAPE coverage is still published, as CONTEXT. It is NOT the gate: on a
# 164-row tape a 40% floor needed 66 explained rows and could never be cleared, which
# made every checkpoint DEGRADED forever - a ratchet, not a gate.
MOVER_COVERAGE_FLOOR = 0.30
# How many movers the board publishes. The gated metric's denominator is the number
# of MOVERS among them, and a table of 15 and a table of 20 are different
# denominators.
MOVERS_TABLE_N = 15
# The marker a board rendered under the mover-coverage floor carries. A board with NO
# marker was written before the rule existed (see COVERAGE_RULE_EFFECTIVE).
COVERAGE_CONTRACT = "preopen-coverage-v2"
# The first checkpoint under the floor. A board published before this date and
# carrying no coverage marker is GRANDFATHERED against the rule: a historical
# artifact is never failed for a rule that post-dates it. The same shape as cron
# #17's `in-play-artifact-v1` / `v2` marker.
COVERAGE_RULE_EFFECTIVE = "2026-11-16"
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

    check(re.search(r"PREOPEN_DIGEST_V2", t) is not None,
          "the digest fetch demands the PREOPEN_DIGEST_V2 capability marker (the V2 "
          "renderer publishes the coverage line; a V1 copy would publish a board "
          "without one)")
    check(re.search(r"PREOPEN_MOVER_COVERAGE_V1", t) is not None,
          "the digest fetch ALSO demands the PREOPEN_MOVER_COVERAGE_V1 marker - the "
          "metric changed, so a stale V2 renderer (the old whole-tape floor) must not "
          "win the ladder")
    check(re.search(r"PREOPEN_EDGAR_DATE_V1", t) is not None,
          "the digest fetch ALSO demands the PREOPEN_EDGAR_DATE_V1 marker - the "
          "date-rendering rule changed, so a stale renderer that prints a filing date "
          "as a bare clock time must not win the ladder")
    check(re.search(r"PREOPEN_ANCHOR_MODE_V1", t) is not None,
          "the digest fetch ALSO demands the PREOPEN_ANCHOR_MODE_V1 marker - the "
          "renderer that publishes the board's ANCHOR line, so a board says whether it "
          "was taken before or after the open")

    # 9. THE MOVER COVERAGE FLOOR. The procedure is where the metric, the floor, the
    # arithmetic, the labels and the reply lines are SPECIFIED - the prompt is
    # byte-pinned, so this file is the only place the rule can live.
    check(re.search(r"MOVER_COVERAGE_FLOOR\s*=\s*0\.3[0-9]*\b", t) is not None,
          "the procedure states the MOVER COVERAGE FLOOR (30%)")
    check(re.search(r"mover_coverage\s*=\s*\(published movers carrying a catalyst\)\s*/\s*"
                    r"\(published movers\)", t) is not None,
          "the procedure states the gated metric (explained published movers over "
          "published movers) - NOT the whole tape")
    check(re.search(r"5 explained movers|5 of 15|ceil\(0\.30 x 15\)", t) is not None,
          "the procedure states the REACHABILITY arithmetic (5 explained movers clear "
          "a 15-row table)")
    check("4/15" in t and "6/15" in t,
          "the procedure quotes the measured 2026-11-13 reader-facing evidence "
          "(4/15 at 08:30 and 6/15 at 09:50)")
    check("16/164" in t and "20/218" in t,
          "the procedure quotes the whole-tape context (16/164 and 20/218)")
    check(re.search(r"degraded:", t) is not None,
          "the procedure's reply carries a `degraded:` line")
    check(re.search(r"NEVER SUPPRESSES THE CHECKPOINT", t, re.I) is not None,
          "the procedure states that the floor NEVER suppresses the checkpoint")
    check(re.search(r"GRANDFATHERED", t) is not None,
          "the procedure states that a pre-fix board is grandfathered against the floor")
    check(re.search(r"preopen-coverage-v\d+", t) is not None,
          "the procedure names the coverage contract marker")
    check(re.search(r"context", t, re.I) is not None,
          "the procedure states that the whole-tape coverage is CONTEXT, not the gate")

    # 8. the procedure demands the DATED capture script and states the gate. Without
    # these the procedure could keep asking for the 2026-11-09 script, which publishes
    # a ten-month-old press release as this morning's cause.
    check(re.search(rf"CAPTURE_SCRIPT_VERSION:\s*{re.escape(CAPTURE_VERSION)}", t) is not None,
          f"the procedure demands the {CAPTURE_VERSION} capture script (the one that "
          f"measures the MOVER coverage and publishes it)")
    # 8b. THE PROCEDURE MUST FETCH THE GATE ITSELF (2026-11-20).
    #
    # The checker was the ONE run-time dependency in this routine that the procedure
    # referenced but never fetched - and it carried no version marker, so a copy from
    # any earlier day could be run in its place silently. Measured 2026-11-19: the
    # sandbox carried the 2026-11-16 gate, whose `_fmt_et` has no `dates` branch, so
    # it computed "00:00:00" for a date-only EDGAR stamp and failed a CORRECT board
    # that printed "2026-11-18" - and because that gate also demanded the
    # 2026-11-15.1 capture script, obeying it would have forced the pre-EDGAR capture
    # (ZERO edgar references against the current build's 52) and turned a passing
    # checkpoint into a degraded one. The procedure must demand the CURRENT gate, or
    # this hole reopens the next time the sandbox's tools/ directory is re-seeded.
    check(re.search(rf"CHECKER_VERSION:\s*{re.escape(CHECKER_VERSION)}", t) is not None,
          f"the procedure demands the {CHECKER_VERSION} gate - a gate older than the "
          f"date contract fails a CORRECT board")
    # THE CANDIDATE SOURCE. The tape used to be built from Yahoo's `top_movers`, which
    # is a screener over the LAST COMPLETED session - so before the open it named
    # YESTERDAY's movers. Measured 2026-11-10: the 08:30 tape carried 49 rows and
    # covered 6 of the 50 names the brief published. The procedure must state that the
    # band is the candidate source.
    check(re.search(r"pre-market band", t, re.I) is not None,
          "the procedure states that the candidates come from TODAY's pre-market band")
    check(re.search(r"25,000\s*SHARES|25,000 shares", t) is not None,
          "the procedure states the absolute pre-market share floor")
    check("news_date" in t and "news_url" in t,
          "the procedure states that every catalyst carries a date and a source article")
    check("stale" in norm(t),
          "the procedure states the STALENESS rule (a catalyst that cannot be today's news is dropped)")
    check(re.search(r"never falls back to the capture clock", t, re.I) is not None,
          "the procedure states that the board never publishes the capture clock as the break time")
    # 9. the procedure states the RETRY POLICY and the two legs' separate accounting
    # (2026-11-17). A procedure that does not say so is a procedure whose reader
    # cannot tell WHY a checkpoint came back unexplained.
    check(re.search(r"ROUTER_ATTEMPTS|three times|retries the cheap leg", t, re.I) is not None,
          "the procedure states that the cheap leg is RETRIED")
    check(re.search(r"router_errors", t) is not None,
          "the procedure states that the router's failures are counted separately "
          "from the article feed's")
    check(re.search(r"article feed stops early|stops early on a repeated", t, re.I) is not None,
          "the procedure states that the metered article feed stops early on a "
          "repeated identical error")
    # 10. the procedure states the SOURCE OF RECORD and the CORRECTED degradation
    # cause (2026-11-17). A procedure that still says the budget was the cause sends
    # the reader looking for a problem that does not exist.
    check(re.search(r"SEC EDGAR|EDGAR", t) is not None,
          "the procedure states that SEC EDGAR is the source of record for a US "
          "listed issuer")
    check(re.search(r"size split", t, re.I) is not None,
          "the procedure states that the board publishes the size split (context)")
    check(re.search(r"budget did not reach", t, re.I) is None,
          "the procedure does NOT mandate the false 'the catalyst budget did not "
          "reach them' cause - the pool covers every mover the board publishes")

    # 11. THE MARKET-CLOSED GUARD (2026-11-26).
    #
    # The procedure ran on THANKSGIVING with the NYSE closed and published a tape of
    # INVENTED moves - 15.3% of the priced rows with a flipped sign, the worst off by
    # 177 points - and the gate passed all 179 of its checks on it. Two rules now
    # stand between a closed market and a published tape, and the procedure is where
    # they are stated:
    #
    #   * the shared WINDOW CHECK, the same gate every other routine in the fleet
    #     runs, so a holiday fire leaves a skip marker and NO artifact;
    #   * the ANCHOR GUARD inside the capture script, which checks the tape's own
    #     moves against the scanner's own close - a rule that needs no calendar, so
    #     it catches an unplanned closure and a half-day roll too.
    #
    # The procedure is the only place these can live: the prompts are byte-pinned.
    check(re.search(r"window_check\.sh", t) is not None,
          "the procedure runs the shared window check (a holiday fire must leave a "
          "marker and NO artifact)")
    check(re.search(r"WINDOW_CHECK_V2", t) is not None,
          "the window-check fetch demands the WINDOW_CHECK_V2 capability marker")
    check(re.search(r"CAPTURE_ANCHOR_GUARD_V1", t) is not None,
          "the capture fetch ALSO demands the CAPTURE_ANCHOR_GUARD_V1 marker - the "
          "build that refuses to write a tape on a stale scanner anchor")
    check(re.search(r"CAPTURE_ANCHOR_ROLL_V1", t) is not None,
          "the capture fetch ALSO demands the CAPTURE_ANCHOR_ROLL_V1 marker - the "
          "build that tells a SHUT market from an OPEN one instead of calling both "
          "of them closed")
    check(re.search(r"roll probe|ROLL PROBE|roll_probe", t, re.I) is not None,
          "the procedure states the ROLL PROBE - the rule that keeps the 09:50 slot "
          "from skipping every weekday on a live market")
    check(re.search(r"ref_close", t) is not None,
          "the procedure states that the tape carries the close each move was "
          "measured against")
    check(re.search(r"anchor", t, re.I) is not None,
          "the procedure states the ANCHOR rule")
    check(re.search(r"market is closed|closed market|market.{0,30}closed", t, re.I) is not None,
          "the procedure states that a closed market yields a marker and no tape")


# ---- static: the shared scripts -----------------------------------------------

def check_script(path):
    print("capture script:")
    t = read(path)
    if not t:
        bad(f"{path} is missing or empty")
        return
    check(re.search(r"CAPTURE_SCRIPT_VERSION:\s*\d{4}-\d{2}-\d{2}", t) is not None,
          "carries the CAPTURE_SCRIPT_VERSION marker")
    check(re.search(rf"CAPTURE_SCRIPT_VERSION:\s*{re.escape(CAPTURE_VERSION)}", t) is not None,
          f"the capture script IS the {CAPTURE_VERSION} one the procedure demands")
    check('call_top_movers(category="losers")' in t,
          "the capture scans the losers half (a gainers-only scan misses the worst movers)")
    check("-abs(" in t,
          "candidates are ranked by |%| so a decliner competes for a grounded catalyst")
    check("os.replace" in t and not re.search(r'open\(out,\s*"a"', t),
          "the tape is written with a temp file + rename, never appended")
    check("ALLOWED_SLOTS" in t and "resolve_slot" in t,
          "the slot is asserted against the allowed set and a late dispatch snaps down")
    m_slots = re.search(r"ALLOWED_SLOTS\s*=\s*\(([^)]*)\)", t)
    check(m_slots is not None and all(s in m_slots.group(1) for s in ALLOWED_SLOTS),
          f"the allowed slot set names every checkpoint slot {list(ALLOWED_SLOTS)}")
    for k in TAPE_KEYS:
        check(f'"{k}"' in t, f"the tape row carries the contract key {k!r}")
    check("not measurable" in norm(t) or "halted" not in t,
          "the script never publishes a halt count")
    # THE STALENESS GATE. Without this the script can date a catalyst and still
    # publish a stale one, and the tape's date field becomes decoration.
    # The CALL, not the name: `resolve_news_dateX(` still contains the substring
    # "resolve_news_date", so a name-only check cannot tell a dated capture from an
    # undated one.
    check(re.search(r"=\s*resolve_news_date\(", t) is not None and '"news_date"' in t,
          "the script dates every catalyst (resolve_news_date -> news_date)")
    # THE PUBLISHED DATE IS AGE-CHECKED IN ITS OWN RIGHT. The gate reads the provider's
    # NEWEST article (freshest), but the tape publishes the MATCHED article's stamp, and
    # the match is textual - it can land on a months-old article from the same company.
    # Measured 2026-11-11 08:30 ET: NOVT carried a catalyst dated 2026-02-22 (262 days
    # old) while the provider held a fresh Novanta article, so the board would have dated
    # a pre-open catalyst to the previous fiscal year. The published stamp must be checked
    # against the window itself, not only the newest article behind it.
    check(re.search(r"_parse_iso\(\s*nd\s*\)", t) is not None,
          "the script age-checks the PUBLISHED date (the matched article), not only the newest")
    # THE PRICE SOURCE. `top_movers` is a screener over the LAST COMPLETED session, so
    # before the open it returns yesterday's closes. The tape must take its price from
    # the scanner's premarket_* columns, and a name with no pre-market print must carry
    # NO number rather than yesterday's close.
    check("premarket_change" in t and "premarket_close" in t,
          "the script reads the scanner's premarket_change/premarket_close for the tape's price")
    check("call_scanner_premarket" in t,
          "the script calls the scanner for the current session's pre-market print")
    # THE CANDIDATE SOURCE, asserted on the CALL and not on the definition: a script
    # that defines call_scanner_band() and never calls it has yesterday's movers back.
    check(re.search(r"=\s*call_scanner_band\(", t) is not None,
          "the script takes its candidates from TODAY's pre-market band")
    m_floor = re.search(r"MIN_PM_SHARES\s*=\s*([1-9]\d*)", t)
    check(m_floor is not None,
          "the script carries the absolute pre-market share floor (a quote is not a "
          "market) - and the floor is a REAL number, not zero")
    check(re.search(r'"pct":\s*pr\.get\("pct"\)', t) is not None,
          "the tape row's pct comes from the pre-market print, not from the movers scan")
    check(re.search(r'"price":\s*pr\.get\("price"\)', t) is not None,
          "the tape row's price comes from the pre-market print")
    check(re.search(r'"src":\s*"stocktwits"', t) is not None,
          "a row with no pre-market print is published as a narrative row")
    check("polygon_io_news" in t,
          "the script reaches the article feed for the catalyst's publication date")
    m = re.search(r"CATALYST_MAX_AGE_DAYS\s*=\s*(\d+)", t)
    check(m is not None and int(m.group(1)) == CATALYST_MAX_AGE_DAYS,
          f"the script's staleness window matches the checker's ({CATALYST_MAX_AGE_DAYS} days)")

    # ------------------------------------------------------------------
    # THE CATALYST PIPELINE. Article first, then the router, both in parallel.
    #
    # Measured 2026-11-13: the SEQUENTIAL grounded calls were ~264s of the
    # capture's 270s - 98% of it - and 8 of the 16 calls on the live tape REFUSED.
    # The article feed answers the same question in 0.21-0.24s with a date AND a
    # URL, and 8 concurrent calls cost 20.2s against 101.8s serial, with no rate
    # limiting. So the feed goes first and the router's 15-25s is spent only on a
    # name the feed could not date.
    m_w = re.search(r"CATALYST_WORKERS\s*=\s*(\d+)", t)
    check("ThreadPoolExecutor" in t and m_w is not None and int(m_w.group(1)) > 1,
          "the catalyst calls run in parallel (a worker pool wider than one)")
    check("resolve_catalysts" in t and "article_catalyst" in t,
          "the capture resolves catalysts through the article-first pipeline")
    # THE ORDER IS THE POINT, and it is assertable from the source: the feed is
    # fetched before the router is consulted.
    m_ord = re.search(r"def resolve_catalysts.*?article_catalyst\(t, cutoff\).*?"
                      r"call_grounded\(t, names", t, re.S)
    check(m_ord is not None,
          "the article feed is consulted BEFORE the router (article first)")

    # ------------------------------------------------------------------
    # THE SIGN PROBE and the notional field.
    check("sign_conflict" in t and "SIGN_MARGIN" in t,
          "the capture probes the catalyst's direction against the move's")
    check("pm_notional" in t,
          "the capture publishes the pre-market dollar notional behind each print")

    # ------------------------------------------------------------------
    # A RETAIL NARRATIVE IS NOT A VERIFIED CAUSE. The base confidence on a row is
    # always "low"; only a DATED, in-window catalyst may raise it. Measured
    # 2026-11-12: 10 of the tape's 12 "high" rows were chatter with no date and
    # no article, and the checker's rule was scoped to the pipeworx provenance, so
    # they passed unchecked.
    check('"conf": "high"' not in t,
          "the script never ASSIGNS a 'high' confidence at row creation (only a "
          "dated catalyst may raise it)")
    check('"conf": "low"' in t,
          "the script assigns 'low' confidence to a row's default catalyst")

    # ------------------------------------------------------------------
    # A CREDIT FAILURE IS NOT "NO NEWS". The gateway answers an exhausted account
    # with "Insufficient credits", and a capture that cannot tell that from an
    # empty result publishes a tape with NO catalysts and reports no error at all.
    # Measured 2026-11-13 23:40 ET: every pack answered that way after the
    # balance ran out mid-run - and the run had to be made to SAY so.
    m_cm = re.search(r"CREDIT_MARKERS\s*=\s*\(([^)]*)\)", t)
    check(m_cm is not None
          and "insufficient credit" in norm(m_cm.group(1))
          and "_is_credit_error" in t,
          "the capture recognises a CREDIT failure and does not treat it as 'no news'")
    check(re.search(r"provider_errors", t) is not None,
          "the capture reports the provider failures in its own ledger")

    # ------------------------------------------------------------------
    # SEC EDGAR IS THE SOURCE OF RECORD (2026-11-17). Without it the coverage
    # floor could not be CLEARED: the news vendor's ticker index held no
    # in-window article for ANY of the 13 movers the 2026-11-16 checkpoints could
    # not explain (eight had zero articles ever; AKAN's newest was from 2024),
    # while EIGHT of the same thirteen had a catalyst-bearing filing in EDGAR
    # inside the window - DVLT's Nasdaq trading suspension, CGON's PIVOT-006
    # Phase 3 readout, LXEO's interim data. A capture with no source of record
    # for the filings that ARE the news cannot clear its own floor.
    # ------------------------------------------------------------------
    check("sec_edgar" in t and "edgar_catalyst" in t,
          "the capture resolves catalysts through SEC EDGAR - the source of record "
          "for a US listed issuer")
    check("efts.sec.gov" in t or "EDGAR_SEARCH_URL" in t,
          "the capture reaches EDGAR's search endpoint by CIK and by date")
    check("company_tickers.json" in t,
          "the capture maps a ticker to its CIK (the SEC's own ticker file)")
    # The EDGAR leg must sit BETWEEN the article feed and the router: a dated
    # filing beats an undated summary, and the router is the metered leg.
    m_ph = re.search(r"def resolve_catalysts.*?article_catalyst\(t, cutoff\).*?"
                     r"edgar_catalyst\(t, cutoff.*?call_grounded\(t, names", t, re.S)
    check(m_ph is not None,
          "the pipeline order is article feed -> EDGAR -> router (a dated filing beats "
          "an undated summary, and the router costs money)")
    check("EDGAR_ITEMS" in t and "sec_edgar" in t,
          "a filing's own 8-K ITEM NUMBERS are used as the catalyst classification")

    # ------------------------------------------------------------------
    # THE RETRY BELONGS ON THE CHEAP LEG (2026-11-17).
    #
    # Measured 2026-11-17: the grounded router answered 4 of 5 calls for AKAN
    # (confidence 0.85-0.95) and 3 of 5 for GP (0.95) when called ONE AT A TIME,
    # while `call_grounded` made exactly ONE call per name - and the 200-CREDIT
    # article feed was retried THREE times. The 2026-11-16 checkpoints then
    # explained 2 of the 15 movers they published (13%, under the 30% floor) at
    # 08:30 AND again at 09:50: a structural miss, not an outage. A capture that
    # asks the cheap leg once is asking it once for no reason.
    # ------------------------------------------------------------------
    m_ra = re.search(r"ROUTER_ATTEMPTS\s*=\s*(\d+)", t)
    check(m_ra is not None and int(m_ra.group(1)) >= 2,
          "the grounded router is RETRIED (one attempt per name left 13 of 15 "
          "published movers unexplained on 2026-11-16, at 08:30 and 09:50 alike)")
    check(re.search(r"def call_grounded\([^)]*attempts", t) is not None,
          "the router's retry budget is a parameter of call_grounded")
    # The feed is the EXPENSIVE leg: two identical failures are a dead index, so
    # the third metered attempt is spent only when the error CHANGED.
    check(re.search(r"err\s*==\s*last_err", t) is not None,
          "the article feed stops early on a REPEATED identical error (a dead index "
          "is not a blip, and every attempt is 200 credits)")

    # ------------------------------------------------------------------
    # THE ROUTER'S FAILURES MUST BE COUNTED (2026-11-17). They used to be
    # invisible: a name the router refused recorded the ARTICLE's error, so the
    # 2026-11-16 08:30 checkpoint - 10 article errors and 13 router refusals -
    # reported ONE distinct provider error, and thirteen published movers lost
    # their explanations while the reply's `errors:` number did not move. A quiet
    # tape with a loud error beats a loud-looking tape with a silent one.
    # ------------------------------------------------------------------
    check(re.search(r"router_error", t) is not None,
          "the capture records the ROUTER's failure separately from the article "
          "feed's (a name that lost its cause to a failure is not a name with no news)")
    check(re.search(r"router_errors", t) is not None,
          "the capture reports the router's failure count in its own ledger")
    m_led = re.search(r"errors \+= sorted\(\{c\.get\(\"router_error\"\).*?\}\)", t, re.S)
    check(m_led is not None,
          "the router's failures ENTER the errors ledger - a checkpoint whose router "
          "refused on every name must not report the market as quiet")

    # ------------------------------------------------------------------
    # THE MOVER COVERAGE FLOOR, IN THE CAPTURE.
    #
    # The capture is where the number is MEASURED: the board renders it from the
    # tape, so a capture that does not measure it publishes a board with no
    # coverage on it. The floor constant must match the checker's, or the two
    # sides disagree about what "degraded" means - and so must the width of the
    # movers table, because that is the metric's denominator.
    # ------------------------------------------------------------------
    m_cov = re.search(r"MOVER_COVERAGE_FLOOR\s*=\s*([0-9.]+)", t)
    check(m_cov is not None and abs(float(m_cov.group(1)) - MOVER_COVERAGE_FLOOR) < 1e-9,
          f"the capture's mover-coverage floor matches the checker's "
          f"({MOVER_COVERAGE_FLOOR})")
    m_tbl = re.search(r"MOVERS_TABLE_N\s*=\s*(\d+)", t)
    check(m_tbl is not None and int(m_tbl.group(1)) == MOVERS_TABLE_N,
          f"the capture's movers table matches the checker's ({MOVERS_TABLE_N} rows) - "
          f"a different width is a different denominator")
    check(re.search(r"mover_coverage", t) is not None,
          "the capture MEASURES the mover coverage")
    check(re.search(r"def published_movers", t) is not None,
          "the capture publishes the SAME movers table the digest renders")
    # THE DEGRADATION IS COUNTED EXACTLY ONCE. It is counted in the capture's own
    # ledger, so the reply's `errors:` number is measured rather than remembered -
    # and a ledger that counts it twice reports a failure the run did not have.
    cov_appends = [ln for ln in t.splitlines()
                   if "errors.append" in ln and "mover_coverage_below_floor" in ln]
    check(len(cov_appends) == 1,
          f"the capture counts the coverage degradation EXACTLY ONCE (one append site, "
          f"got {len(cov_appends)})")
    check(re.search(r"catalyst_coverage", t) is not None,
          "the capture still measures the WHOLE-TAPE coverage - it is published as "
          "CONTEXT")
    check(re.search(r"catalyst_price_only", t) is not None,
          "the capture breaks the uncovered rows down by provenance (price-only vs "
          "narrative-only)")

    # ------------------------------------------------------------------
    # THE ANCHOR GUARD (2026-11-26).
    #
    # The capture wrote a tape on THANKSGIVING, with the NYSE closed, and this gate
    # PASSED all 179 of its checks on it. Every rule it had was about the tape's
    # SHAPE; none of them asked whether a MOVE was real. So the capture now refuses
    # to write a tape it cannot stand behind: it pulls the scanner's own `close`
    # column in the SAME request it already makes, checks the tape's implied
    # reference against it, and fails closed with a MARKER when the two disagree.
    #
    # The check is asserted on the CALL and the CONSTANTS, not on a name: a script
    # that defines anchor_health() and never calls it has the guard in name only.
    # ------------------------------------------------------------------
    check(re.search(r"CAPTURE_ANCHOR_GUARD_V1", t) is not None,
          "the capture carries the CAPTURE_ANCHOR_GUARD_V1 capability marker")
    check(re.search(r"CAPTURE_ANCHOR_ROLL_V1", t) is not None,
          "the capture carries the CAPTURE_ANCHOR_ROLL_V1 capability marker")
    check(re.search(r"def\s+probe_session_roll", t) is not None,
          "the capture defines the ROLL PROBE - the measurement that tells a shut "
          "market from an open one")
    check(re.search(r"=\s*probe_session_roll\(", t) is not None,
          "the capture CALLS the roll probe - a probe that is only defined never "
          "runs")
    check(re.search(r"ref_mode", t) is not None,
          "the capture publishes the anchor MODE on every priced row")
    check(re.search(r"ref_scanner_close", t) is not None,
          "the capture publishes the scanner's own close beside the anchor - the "
          "evidence the gate checks a rolled tape with")
    check(re.search(r"def anchor_health", t) is not None,
          "the capture checks the scanner's anchor before it writes a tape")
    check(re.search(r"=\s*anchor_health\(", t) is not None,
          "the capture CALLS the anchor check - a guard that is only defined is a "
          "guard that never fires")
    check(re.search(r"market_closed", t) is not None,
          "the capture fails CLOSED on a stale anchor (a marker, not a tape)")
    check(re.search(r"ref_close", t) is not None,
          "the capture publishes the close each move was measured against")
    m_tol = re.search(r"ANCHOR_TOLERANCE\s*=\s*([0-9.]+)", t)
    check(m_tol is not None and abs(float(m_tol.group(1)) - ANCHOR_TOLERANCE) < 1e-9,
          f"the capture's anchor tolerance matches the checker's ({ANCHOR_TOLERANCE})")
    m_fl = re.search(r"ANCHOR_MATCH_FLOOR\s*=\s*([0-9.]+)", t)
    check(m_fl is not None and abs(float(m_fl.group(1)) - ANCHOR_MATCH_FLOOR) < 1e-9,
          f"the capture's anchor match floor matches the checker's "
          f"({ANCHOR_MATCH_FLOOR})")


def check_digest_script(path):
    print("digest renderer:")
    t = read(path)
    if not t:
        bad(f"{path} is missing or empty")
        return
    check("PREOPEN_DIGEST_V2" in t, "carries the PREOPEN_DIGEST_V2 marker")
    check("PREOPEN_MOVER_COVERAGE_V1" in t,
          "carries the PREOPEN_MOVER_COVERAGE_V1 marker (this renderer's metric)")
    check("PREOPEN_EDGAR_V1" in t,
          "carries the PREOPEN_EDGAR_V1 marker - the renderer that publishes the board "
          "whose catalyst leg is SEC EDGAR")
    check("PREOPEN_SIZE_SPLIT_V1" in t,
          "carries the PREOPEN_SIZE_SPLIT_V1 marker - the renderer that publishes the "
          "size split and the CORRECTED degradation cause")
    check("PREOPEN_EDGAR_DATE_V1" in t,
          "carries the PREOPEN_EDGAR_DATE_V1 marker - the renderer that publishes a "
          "date-only catalyst (an SEC EDGAR filing date) as a DATE and not as a clock time")
    check("PREOPEN_ANCHOR_MODE_V1" in t,
          "carries the PREOPEN_ANCHOR_MODE_V1 marker - the renderer that publishes the "
          "board's ANCHOR line, so a board says whether it was taken before or after "
          "the open")
    check(re.search(r"DATE_CONTRACT\s*=\s*[\"']preopen-dates-v\d+[\"']", t) is not None,
          "the renderer stamps the date contract on the board, so a pre-fix board can be "
          "grandfathered against the rule")
    check("DIGEST_COLUMNS" in t and "Ticker" in t,
          "the board's columns are fixed in code")
    check("TOP_N = 15" in t, "the board lists the top 15 movers")
    check(f"TOP_N = {MOVERS_TABLE_N}" in t,
          f"the board's table width matches the checker's ({MOVERS_TABLE_N} rows) - "
          f"the gated metric's denominator is that width")
    check("scanner" in t and "stocktwits" in t and "pipeworx" in t,
          "the board reports the row PROVENANCE split (scanner / stocktwits / pipeworx)")
    check("not measurable" in norm(t),
          "the board reports the halt state as not measurable")
    check("news_date" in t,
          "the board's 'When it broke' reads the tape's news_date, not the capture clock")
    # The break-time ASSIGNMENT has to read news_date - not merely mention it in a
    # comment. The renderer prints the capture clock in a column titled "When it
    # broke" unless the news date comes first.
    check(re.search(r"broke\s*=\s*r\.get\(\s*[\"']news_date[\"']", t) is not None,
          "the board's break-time column takes the NEWS date first, and only then the "
          "trending stamp")
    # ------------------------------------------------------------------
    # THE MOVER COVERAGE, IN THE RENDERER. The board is where the reader finds
    # out how much of the TABLE was explained, so the line and the banner have to
    # be rendered HERE and not left to the agent's prose.
    # ------------------------------------------------------------------
    check(re.search(r"COVERAGE_CONTRACT\s*=\s*[\"']preopen-coverage-v\d+[\"']", t) is not None,
          "the renderer stamps the coverage contract marker on the board")
    m_cf = re.search(r"MOVER_COVERAGE_FLOOR\s*=\s*([0-9.]+)", t)
    check(m_cf is not None and abs(float(m_cf.group(1)) - MOVER_COVERAGE_FLOOR) < 1e-9,
          f"the renderer's mover-coverage floor matches the checker's "
          f"({MOVER_COVERAGE_FLOOR})")
    check(re.search(r"\*\*mover coverage:\*\*", t) is not None,
          "the renderer publishes the GATED mover-coverage line in the header")
    check(re.search(r"\*\*catalyst coverage \(whole tape\):\*\*", t) is not None,
          "the renderer publishes the whole-tape coverage as CONTEXT, separately from "
          "the gated number")
    check(re.search(r"def published_movers", t) is not None,
          "the renderer measures the coverage of the MOVERS it publishes")
    check(re.search(r"DEGRADED", t) is not None,
          "the renderer raises the DEGRADED banner when the coverage is below the floor")


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

def _parse_date(v):
    """An ISO-8601 stamp as a date, or None."""
    try:
        s = str(v).strip().replace("Z", "+00:00")
        return datetime.datetime.fromisoformat(s).date()
    except Exception:
        return None


def _fmt_et(v, dates=True):
    """Render a tape timestamp the way the board renders it: ET wall clock.

    This is an INDEPENDENT copy of the renderer's rule, on purpose - a checker that
    calls the code under test proves nothing. tools/test_preopen_digest_contract.py
    pins the renderer's own conversion separately.

    `dates=True` is the CURRENT rule: a DATE-ONLY value (an SEC EDGAR filing date,
    "2026-11-16") renders as the DATE. `dates=False` is the LEGACY rule, which
    formatted every stamp as a clock time and so printed a filing date as "00:00:00" -
    a bare midnight with no date on it, which left the reader unable to tell whether the
    news broke today or yesterday. A board written before the rule existed is checked
    against the legacy rule; a board carrying the date contract is checked against the
    current one.
    """
    if not v:
        return "\u2014"
    s = str(v).strip()
    if dates and _DATE_ONLY_RE.match(s):
        return s
    try:
        from datetime import timezone
        from zoneinfo import ZoneInfo
    except Exception:
        return s[11:19] if len(s) >= 19 else s
    try:
        dt = datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return s[11:19] if len(s) >= 19 else s
    if dt.tzinfo is None:
        try:
            dt = dt.replace(tzinfo=ZoneInfo("America/New_York"))
        except Exception:
            pass
    else:
        try:
            dt = dt.astimezone(ZoneInfo("America/New_York"))
        except Exception:
            dt = dt.astimezone(timezone.utc)
    return dt.strftime("%H:%M:%S")


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


def _digest_date(digest_path):
    """The date a board belongs to, from its {date}-{slot}.md name."""
    stem = os.path.basename(digest_path)
    m = re.match(r"^(\d{4}-\d{2}-\d{2})-\d{4}\.md$", stem)
    if not m:
        return None
    try:
        return datetime.date.fromisoformat(m.group(1))
    except Exception:
        return None


def coverage_rule_applies(digest_text, digest_path):
    """Does THE MOVER COVERAGE FLOOR apply to this board?

    THE GRANDFATHER. A board that carries the CURRENT coverage marker is checked
    against the floor in full. A board that carries NO marker and PREDATES the
    floor's effective date is checked against the rules in force when it was
    written: a historical artifact is never failed for a rule that post-dates it.
    The same shape as cron #17's `in-play-artifact-v1` marker.

    A board that carries a LEGACY marker (the previous metric's marker) and was
    published ON OR AFTER the effective date is NOT grandfathered: it was written
    under a coverage rule, so it must publish the CURRENT metric. Grandfathering it
    would let a renderer that quietly went back to the old metric escape the gate -
    which is exactly the silent failure the rule exists to stop.
    """
    m = re.search(r"preopen-coverage-v\d+", digest_text)
    marker = m.group(0) if m else None
    if marker == COVERAGE_CONTRACT:
        return True, f"the board carries the CURRENT coverage marker ({marker})"
    d = _digest_date(digest_path)
    if d is not None and d < datetime.date.fromisoformat(COVERAGE_RULE_EFFECTIVE):
        return False, (f"the board carries {('the LEGACY marker ' + marker) if marker else 'NO coverage marker'} "
                       f"and was published on {d}, before the floor took effect "
                       f"({COVERAGE_RULE_EFFECTIVE}) - it is grandfathered against the rule")
    if marker is not None:
        return True, (f"the board carries the LEGACY coverage marker ({marker}) and was "
                      f"published on {d}, on or after the floor's effective date "
                      f"({COVERAGE_RULE_EFFECTIVE}) - it must publish the CURRENT metric")
    return True, ("the board carries NO coverage marker, so the floor applies to it "
                  "(a board written under the rule must publish its coverage)")


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

    # ------------------------------------------------------------------
    # WHEN THE CATALYST BROKE. This is the ARWR defect, made machine-checkable.
    #
    # Measured 2026-11-09 09:50: ARWR (-16.59%) carried Arrowhead's 2026-01-06
    # press release - "stock surging 17.81% to a new 52-week high", a story about the
    # opposite move from ten months earlier - at `conf: high`, and the board printed
    # "09:53:48" in its **When it broke** column because that column fell back to
    # the CAPTURE clock. The tape had no field that could have said "January 6".
    #
    # So: every row carries a news_date (and the article it came from in news_url),
    # no dated catalyst may be older than the window, and a catalyst the tape is
    # confident about must be dated.
    # ------------------------------------------------------------------
    missing_date = [r.get("ticker") for r in rows if "news_date" not in r]
    check(not missing_date,
          f"every row carries a news_date field ({len(missing_date)} missing)")
    missing_url = [r.get("ticker") for r in rows if "news_url" not in r]
    check(not missing_url,
          f"every row carries a news_url field ({len(missing_url)} missing)")

    # The tape's DATE comes from its own name: cron #17 merges the checkpoints by
    # slot, so {date}-{slot}.jsonl is the contract, not a convention.
    m = re.match(r"^(\d{4}-\d{2}-\d{2})-\d{4}\.jsonl$", os.path.basename(tape_path))
    tape_date = None
    if m:
        try:
            tape_date = datetime.date.fromisoformat(m.group(1))
        except Exception:
            tape_date = None
    check(tape_date is not None,
          f"the tape is named {{date}}-{{slot}}.jsonl so its date can be checked "
          f"(got {os.path.basename(tape_path)})")

    # ------------------------------------------------------------------
    # THE ANCHOR. Is the tape's MOVE the move the scanner says happened?
    #
    # Every rule above is about the tape's SHAPE. None of them asked whether its
    # numbers were real, and that is how a tape of INVENTED moves passed all 179
    # checks on 2026-11-26: the market was closed (Thanksgiving), the scanner's
    # pre-market columns kept their anchor on the previous session's close, and 15.3%
    # of the priced rows came out with a flipped sign - the worst off by 177 points.
    #
    # So a priced row now carries `ref_close`: the close the scanner published
    # alongside the move. The implied reference rebuilt from the row's own (price,
    # pct) must agree with it. The tape is checked against ITSELF, so the gate needs
    # no second source and no network - and a stale-anchored tape FAILS instead of
    # being published.
    #
    # Grandfathered for tapes written before the capture carried the anchor.
    # ------------------------------------------------------------------
    if (tape_date is not None
            and tape_date >= datetime.date.fromisoformat(ANCHOR_RULE_EFFECTIVE)):
        no_anchor = [r.get("ticker") for r in priced if r.get("ref_close") in (None, "")]
        check(not no_anchor,
              f"every priced row carries the close its move was measured against "
              f"({len(no_anchor)} missing)")
        matched = 0
        checked = 0
        offenders = []
        for r in priced:
            rc = r.get("ref_close")
            p = r.get("price")
            pct = r.get("pct")
            if rc in (None, "") or p is None or pct is None:
                continue
            try:
                rc = float(rc)
                p = float(p)
                pct = float(pct)
            except (TypeError, ValueError):
                continue
            if rc <= 0 or pct <= -100:
                continue
            implied = p / (1.0 + pct / 100.0)
            checked += 1
            if abs(implied - rc) / rc <= ANCHOR_TOLERANCE:
                matched += 1
            elif len(offenders) < 5:
                offenders.append(f"{r.get('ticker')} implied {implied:.4f} vs close {rc:.4f}")
        if checked:
            ratio = matched / checked
            check(ratio >= ANCHOR_MATCH_FLOOR,
                  f"the tape's moves agree with the close they were measured against "
                  f"({matched}/{checked} = {ratio:.0%}, floor {ANCHOR_MATCH_FLOOR:.0%}"
                  f"{'; offenders ' + str(offenders[:3]) if offenders else ''})")
        else:
            bad("the tape's anchor could not be verified at all - no priced row yields "
                "a comparable close")
    else:
        ok(f"the tape predates the anchor rule ({ANCHOR_RULE_EFFECTIVE}) - grandfathered")

    # ------------------------------------------------------------------
    # THE ANCHOR MODE RULE (2026-11-28).
    #
    # THE ANCHOR INVARIANT IS INSTANT-BOUND, AND ONE SLOT SITS PAST THAT INSTANT.
    # The anchor is checked against the scanner's `close` column, which IS the previous
    # close while the PRE-MARKET session is live. At the 09:30 ET OPEN the scanner ROLLS
    # that column to the LIVE regular-session price and freezes the pre-market columns
    # at their last values, so the invariant cannot hold after the open - and the 09:50
    # slot is scheduled `50 9 * * 1-5` ET, twenty minutes after it. The capture then
    # skipped every weekday and called a live market "closed" (measured 2026-11-27:
    # 100 of 1142 priced rows agreed, 8.8% against a 90% floor, on a market that was
    # OPEN and trading).
    #
    # So a tape now states WHICH STATE it was written in and carries the scanner's
    # published close beside its anchor:
    #
    #   * `aligned` - the scanner's `close` WAS the previous close, so the anchor and
    #     the scanner's close are the SAME figure. The pre-open path, unchanged.
    #   * `rolled`  - the regular session was already open, so the scanner's `close`
    #     was a LIVE price and the anchor is the provider's implied reference
    #     instead. The two MUST differ, and that difference IS the evidence.
    #
    # The rule is GRANDFATHERED for tapes written before it existed - the same shape as
    # the anchor rule and the coverage floor.
    # ------------------------------------------------------------------
    if (tape_date is not None
            and tape_date >= datetime.date.fromisoformat(ANCHOR_MODE_EFFECTIVE)):
        modes = {r.get("ref_mode") for r in priced}
        missing_mode = [r.get("ticker") for r in priced
                        if r.get("ref_mode") not in ("aligned", "rolled")]
        check(not missing_mode,
              f"every priced row states which state the capture was in "
              f"({len(missing_mode)} missing or invalid)")
        if len(modes) > 1:
            check(False,
                  f"the tape's rows disagree about the capture's state "
                  f"(got {sorted(str(m) for m in modes)})")
        mode = next((m for m in modes if m in ("aligned", "rolled")), None)
        same = 0
        differ = 0
        mode_checked = 0
        mode_offenders = []
        for r in priced:
            rc = r.get("ref_close")
            sc = r.get("ref_scanner_close")
            p = r.get("price")
            pct = r.get("pct")
            if rc in (None, "") or sc in (None, "") or p is None or pct is None:
                continue
            try:
                rc = float(rc)
                sc = float(sc)
                p = float(p)
                pct = float(pct)
            except (TypeError, ValueError):
                continue
            if rc <= 0:
                continue
            mode_checked += 1
            close_enough = abs(sc - rc) / rc <= ANCHOR_TOLERANCE
            if close_enough:
                same += 1
            else:
                differ += 1
            if len(mode_offenders) < 5 and mode == "rolled" and close_enough:
                mode_offenders.append(f"{r.get('ticker')} scanner close {sc:.4f} vs "
                                      f"anchor {rc:.4f}")
        if mode == "aligned":
            if mode_checked:
                ratio = same / mode_checked
                check(ratio >= ANCHOR_MATCH_FLOOR,
                      f"an ALIGNED tape's anchor IS the scanner's own close "
                      f"({same}/{mode_checked} = {ratio:.0%}, floor "
                      f"{ANCHOR_MATCH_FLOOR:.0%})")
        elif mode == "rolled":
            if mode_checked:
                ratio = differ / mode_checked
                check(ratio >= ANCHOR_MATCH_FLOOR,
                      f"a ROLLED tape's anchor is the implied reference and the "
                      f"scanner's close is a LIVE price, so the two must differ "
                      f"({differ}/{mode_checked} = {ratio:.0%}, floor "
                      f"{ANCHOR_MATCH_FLOOR:.0%}"
                      f"{'; offenders ' + str(mode_offenders[:3]) if mode_offenders else ''})")
            else:
                bad("a tape that claims the session rolled carries no comparable "
                    "scanner close - the evidence for the claim cannot be checked")
        else:
            bad("the tape states no anchor mode, so the gate cannot tell a pre-open "
                "tape from a post-open one")
    else:
        ok(f"the tape predates the anchor-mode rule ({ANCHOR_MODE_EFFECTIVE}) - "
           f"grandfathered")

    stale, undated_confident = [], []
    for r in rows:
        nd = r.get("news_date")
        if nd:
            d = _parse_date(nd)
            if d is None:
                stale.append((r.get("ticker"), nd, "unparseable"))
            elif tape_date is not None and (tape_date - d).days > CATALYST_MAX_AGE_DAYS:
                stale.append((r.get("ticker"), nd, f"{(tape_date - d).days}d old"))
        # A catalyst the tape is CONFIDENT about has to be dated. An undated one may
        # only ever ride at `low` confidence, because we cannot say when it broke.
        #
        # EVERY PROVENANCE, and that is the point. The rule used to be scoped to
        # `src == "pipeworx"`, so a stocktwits chatter reason - no publication stamp,
        # no article behind it - rode at `conf: high` unchecked. Measured on the
        # 2026-11-12 tape: 10 of the 12 "high" rows were exactly that, undated and
        # uncheckable, while only 2 were dated grounded catalysts.
        if (r.get("conf") in ("high", "medium") and not nd
                and (r.get("why") or r.get("src") == "pipeworx")):
            undated_confident.append((r.get("ticker"), r.get("conf"), r.get("src")))
    check(not stale,
          f"no catalyst is dated outside the {CATALYST_MAX_AGE_DAYS}-day window "
          f"(got {stale[:3]})")
    check(not undated_confident,
          f"no undated catalyst is published as high/medium confidence "
          f"(got {undated_confident[:3]})")

    # ------------------------------------------------------------------
    # A ROW WITH NEITHER A NUMBER NOR A CAUSE IS NOT A ROW.
    # It says nothing a reader can use and every consumer pays to carry it.
    # Measured on the 2026-11-12 tape: 11 of its 45 rows were exactly this.
    empty = [r.get("ticker") for r in rows
             if r.get("pct") is None and not r.get("why")]
    check(not empty,
          f"no row is published with neither a number nor a cause (got {empty[:5]})")

    # ------------------------------------------------------------------
    # THE SIGN PROBE. A cause that points the OTHER way from the move is not an
    # explanation of that move, so it cannot be published as a confident one.
    # Measured 2026-11-12: DGII (-20.50%) carried "beat Q4 2026 earnings
    # expectations" at `conf: high` WITH a date - the price was right, the cause
    # was not, and cron #17 reads this text at 15:50 as THE reason.
    conflicted = [r.get("ticker") for r in rows if r.get("sign_conflict")]
    check(all(r.get("conf") == "low" for r in rows if r.get("sign_conflict")),
          f"every row whose catalyst contradicts its move is demoted to low confidence "
          f"(got {[r.get('ticker') for r in rows if r.get('sign_conflict') and r.get('conf') != 'low'][:5]})")
    check(all(isinstance(r.get("sign_conflict"), bool) for r in rows),
          f"every row carries a sign_conflict verdict ({len(conflicted)} flagged)")
    check(all(("pm_notional" in r) for r in rows),
          "every row carries the pre-market dollar notional behind its print")
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
    grounded_rows = sum(1 for r in rows if r.get("src") == "pipeworx")
    dated_rows = sum(1 for r in rows if r.get("news_date"))
    check(f"**Dated catalysts:** {dated_rows} of {grounded_rows}" in t,
          f"the board reports the dated-catalyst count ({dated_rows} of {grounded_rows})")

    # the table
    tbl = parse_md_table(t.splitlines())
    header = [c.strip() for c in tbl[0]] if tbl else []
    check(header == DIGEST_COLUMNS,
          f"the table header is exactly {DIGEST_COLUMNS} (got {header})")
    body = tbl[1:] if tbl else []
    check(len(body) <= TOP_N, f"the table lists at most {TOP_N} rows (got {len(body)})")
    check(len(body) == min(TOP_N, n), f"the table lists the top {min(TOP_N, n)} movers")

    # ordering by |pct| desc.
    #
    # The cell is "+40.00%" - and float("+40.00%") RAISES, so every row used to fall
    # into the except branch and read -1.0. The list was then all -1.0, which is
    # already sorted, and the check could never fail: the board's ordering was
    # UNVERIFIED, not verified. The cell has to be parsed, not coerced.
    pcts = []
    for r in body:
        raw = (r[1] or "").strip().replace("%", "").replace(",", "").replace("+", "")
        raw = raw.replace("\u2212", "-").replace("\u2013", "-")
        try:
            pcts.append(abs(float(raw)))
        except Exception:
            pcts.append(-1.0)
    check(pcts == sorted(pcts, reverse=True),
          f"the rows are ranked by |%| descending (read {pcts[:6]})")

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

    # ------------------------------------------------------------------
    # "WHEN IT BROKE" MUST BE THE NEWS DATE.
    #
    # The column's whole job is to date the catalyst. The capture clock (`ts`) is
    # when the SCRIPT RAN, and publishing it there asserts that the news broke when
    # the script ran. For a catalyst that is older than the run that is a lie, and it
    # is the lie a trader reads before the open.
    # ------------------------------------------------------------------
    by_ticker = {r.get("ticker"): r for r in rows}
    wrong_time, cap_fallback = [], []
    # THE DATE CONTRACT. A board that carries the marker renders a date-only catalyst as
    # a DATE; a board that carries NO marker was written before that rule existed and is
    # checked against the LEGACY rule (every stamp as a clock time), so a pre-fix board
    # is not failed by a rule it was never written under.
    # THE MARKER MUST BE THE CURRENT CONTRACT, NOT "ANY VERSION OF IT".
    #
    # Measured 2026-11-20 by this file's own fault-injection case
    # (`a board that drops the date contract marker is caught`): the check read
    # `re.search(r"preopen-dates-v\d+", t)`, so a board carrying
    # `preopen-dates-v0` - a contract this gate does NOT implement - was accepted as
    # if it carried the current one, and was then checked against the current rule.
    # A gate that accepts a contract it cannot implement is a gate that checks
    # nothing. So the CURRENT contract is matched EXACTLY, and an UNKNOWN version is
    # its own failure: the gate must refuse to check such a board, not wave it
    # through under a rule it never wrote.
    has_date_contract = DATE_CONTRACT in t
    unknown_contract = sorted({m for m in re.findall(r"preopen-dates-v\d+", t)
                               if m != DATE_CONTRACT})
    dates = has_date_contract
    check(not unknown_contract,
          f"the board carries no UNKNOWN date-contract marker - this gate implements "
          f"{DATE_CONTRACT} only (got {unknown_contract})")
    for cells in body:
        if len(cells) < 5:
            continue
        tick = cells[0].strip()
        rec = by_ticker.get(tick)
        if rec is None:
            continue
        nd = rec.get("news_date")
        want = (_fmt_et(nd, dates) if nd
                else (_fmt_et(rec.get("trending_ts"), dates) if rec.get("trending_ts") else "\u2014"))
        got = cells[4].strip()
        if got != want:
            wrong_time.append((tick, got, want))
        if rec.get("ts") and got == _fmt_et(rec.get("ts"), dates) and want != got:
            cap_fallback.append(tick)
    check(not wrong_time,
          f"every row's 'When it broke' shows the NEWS date, not the capture clock "
          f"({len(wrong_time)} wrong: {wrong_time[:3]})")
    check(not cap_fallback,
          f"no row falls back to the capture clock for its break time ({cap_fallback[:3]})")
    # ------------------------------------------------------------------
    # A FILING DATE IS A DATE, NOT A CLOCK TIME.
    #
    # EDGAR (2026-11-17) put date-only `news_date` values into the tape - a filing date
    # with no time on it - and the renderer formatted every stamp as a clock time, so a
    # filing dated 2026-11-16 printed "00:00:00". Measured on the 2026-11-17 08:30
    # board: 6 of the 9 dated catalysts rendered "00:00:00", and three of them (FRTT,
    # FGL, GLAS) had no date ANYWHERE on the row - so the reader could not tell whether
    # the news broke today or yesterday. The column's whole job is WHEN.
    #
    # So a board published on or after the effective date must carry the date contract,
    # and no row on it may print a date-only catalyst as a bare clock time. A board
    # published BEFORE the effective date is grandfathered: it was written under the old
    # rule and is not failed by a rule it never saw.
    # ------------------------------------------------------------------
    dated_rows = [r for r in rows
                  if r.get("news_date")
                  and _DATE_ONLY_RE.match(str(r["news_date"]).strip())]
    if dated_rows:
        d = _digest_date(digest_path)
        check(has_date_contract or d is None or d < datetime.date.fromisoformat(DATE_RULE_EFFECTIVE),
              f"a board published on or after {DATE_RULE_EFFECTIVE} carries the "
              f"{DATE_CONTRACT} marker - it renders a filing date as a DATE")
        bad_midnight = [c[0].strip() for c in body
                        if len(c) >= 5 and by_ticker.get(c[0].strip()) is not None
                        and _DATE_ONLY_RE.match(str(by_ticker[c[0].strip()].get("news_date") or "").strip())
                        and c[4].strip() == "00:00:00"]
        check(not bad_midnight,
              f"no row prints a date-only catalyst as a bare clock time (00:00:00) "
              f"({len(bad_midnight)} rows: {bad_midnight[:3]})")

    # ------------------------------------------------------------------
    # THE MOVER COVERAGE FLOOR.
    #
    # The GATED number is the coverage of the MOVERS THE BOARD PUBLISHES - and it
    # is read off the board's OWN table, cross-referenced with the tape for the
    # cause. It is NOT the whole tape's coverage: a percentage over 164 rows says
    # how wide the band was, not how much of the board the reader is looking at was
    # explained.
    #
    # So the board has to PUBLISH the gated number, the arithmetic has to match the
    # published table, and a board below the floor has to carry the degradation in
    # the file a reader opens. A board at or above the floor must NOT carry one.
    # ------------------------------------------------------------------
    named = sum(1 for r in rows if r.get("why"))
    total = len(rows)
    cov_pct = (100.0 * named / total) if total else 0.0
    # THE PUBLISHED MOVERS - the rows of the board's table that carry a price.
    pub_rows = []
    for cells in body:
        if len(cells) < 2:
            continue
        rec = by_ticker.get(cells[0].strip())
        if rec is None or rec.get("pct") is None:
            continue              # a row with no price is not a mover
        pub_rows.append(rec)
    mv_total = len(pub_rows)
    mv_named = sum(1 for r in pub_rows if r.get("why"))
    mv_pct = (100.0 * mv_named / mv_total) if mv_total else None
    below = (mv_total == 0) or (mv_named / mv_total < MOVER_COVERAGE_FLOOR)
    applies, why = coverage_rule_applies(t, digest_path)
    if not applies:
        ok(f"the coverage floor does not apply to this board - {why}")
    else:
        # THE GATED LINE. Its numerator and denominator are the PUBLISHED MOVERS.
        m_mv = re.search(r"\*\*mover coverage:\*\*\s*(\d+)\s*/\s*(\d+)\s*\((\d+)%\)", t,
                         re.I)
        m_na = re.search(r"\*\*mover coverage:\*\*\s*n/a", t, re.I)
        if mv_total == 0:
            check(m_na is not None,
                  "the board publishes 'mover coverage: n/a' when it published no movers "
                  "table - a checkpoint that cannot show an explained mover cannot claim "
                  "coverage")
        elif check(m_mv is not None,
                   "the board publishes the MOVER COVERAGE line (explained movers / "
                   "published movers / percent) - a board that quietly stopped publishing "
                   "its coverage is the silent failure this rule exists to stop"):
            got_named, got_total, got_pct = (int(m_mv.group(1)), int(m_mv.group(2)),
                                              int(m_mv.group(3)))
            check(got_total == mv_total,
                  f"the gated line's denominator is the PUBLISHED MOVERS the table "
                  f"carries ({got_total} vs {mv_total}) - not the whole tape")
            check(got_named == mv_named,
                  f"the gated line's numerator is the published movers that carry a "
                  f"catalyst ({got_named} vs {mv_named})")
            check(got_pct == int(round(mv_pct)),
                  f"the gated percentage matches the arithmetic "
                  f"({got_pct}% vs {int(round(mv_pct))}%)")
        # THE WHOLE-TAPE COVERAGE IS CONTEXT, and it must be published SEPARATELY.
        # A board that published only the context line would be gating on the wrong
        # number - so the context line is checked against the tape's own numbers.
        m_ctx = re.search(r"\*\*catalyst coverage \(whole tape\):\*\*\s*(\d+)\s*/\s*"
                          r"(\d+)\s*\((\d+)%\)", t, re.I)
        if check(m_ctx is not None,
                 "the board publishes the WHOLE-TAPE coverage as context, separately "
                 "from the gated number"):
            check(int(m_ctx.group(1)) == named and int(m_ctx.group(2)) == total,
                  f"the whole-tape context line matches the tape ({m_ctx.group(1)}/"
                  f"{m_ctx.group(2)} vs {named}/{total})")
            check(int(m_ctx.group(3)) == int(round(cov_pct)),
                  f"the whole-tape context percentage matches its own arithmetic "
                  f"({m_ctx.group(3)}% vs {int(round(cov_pct))}%)")
        m_fl = re.search(r"\*\*floor:\*\*\s*(\d+)%", t)
        check(m_fl is not None and int(m_fl.group(1)) == int(round(MOVER_COVERAGE_FLOOR * 100)),
              f"the board publishes the floor it was measured against "
              f"({int(round(MOVER_COVERAGE_FLOOR * 100))}%)")
        # THE SIZE SPLIT (2026-11-17). It is CONTEXT, and it FAILS SOFT: the board
        # either publishes the split or says it could not be measured. It is never
        # silently absent - a split line that vanishes is the same silent failure as
        # a coverage line that vanishes.
        m_sz = re.search(r"\*\*Size split of the published movers:\*\*\s*(.+)", t)
        if check(m_sz is not None,
                 "the board publishes the SIZE SPLIT of the published movers (context; "
                 "it is why the coverage is what it is)"):
            sz = m_sz.group(1)
            check(re.search(r"unavailable|explained", sz) is not None,
                  "the size split either publishes the explained/ published counts or "
                  "says it is unavailable - it never publishes a wrong split")
        degraded = "DEGRADED" in t
        m_st = re.search(r"\*\*(BELOW FLOOR|AT OR ABOVE THE FLOOR)\*\*", t)
        if check(m_st is not None,
                 "the board states whether its mover coverage is below the floor"):
            stated_below = (m_st.group(1).upper() == "BELOW FLOOR")
            check(stated_below == below,
                  f"the board's floor verdict matches the arithmetic "
                  f"(stated {'BELOW FLOOR' if stated_below else 'AT OR ABOVE THE FLOOR'}, "
                  f"computed {'BELOW FLOOR' if below else 'AT OR ABOVE THE FLOOR'})")
        if below:
            check(degraded,
                  f"the board's mover coverage ({'n/a' if mv_pct is None else f'{mv_pct:.0f}%'}) "
                  f"is BELOW the floor ({MOVER_COVERAGE_FLOOR * 100:.0f}%) - it carries the "
                  f"DEGRADED banner")
            check(re.search(r"below the \d+% floor", t, re.I) is not None,
                  "the degradation says WHICH floor it fell below")
            if mv_total == 0:
                check(re.search(r"no movers table", t, re.I) is not None,
                      "the degradation says WHY the metric is undefined (the digest "
                      "published no movers table)")
            else:
                check(re.search(r"could not resolve a dated cause|no in-window article",
                                t, re.I) is not None,
                      "the degradation NAMES THE CAUSE (the pipeline could not resolve a "
                      "dated cause for those rows)")
                check(re.search(r"budget did not reach", t, re.I) is None,
                      "the degradation does NOT blame the catalyst budget - the pool is "
                      "sized to cover every mover the board publishes, so a budget "
                      "shortfall was never the constraint (it was wrong on 2026-11-16)")
            # WHICH names are unexplained. A degradation that says "some of them" is not
            # a finding: every unexplained mover on the board has to be named. When the
            # board published no movers at all there is nothing to name, and the
            # degradation's cause is the empty table itself.
            if mv_total == 0:
                ok("the board published no movers, so there is no unexplained mover to "
                   "name - the degradation names the empty table instead")
            else:
                pline = ""
                for ln in t.splitlines():
                    if "Unexplained movers in the published table" in ln:
                        pline = ln
                        break
                if check(bool(pline),
                         "the degradation LISTS the unexplained movers it publishes"):
                    missing = []
                    for rec in pub_rows:
                        if rec.get("why"):
                            continue
                        tick = str(rec.get("ticker") or "")
                        if tick not in pline:
                            missing.append(tick)
                    check(not missing,
                          f"every unexplained published mover is named in the list "
                          f"({missing[:5]})")
        else:
            check(not degraded,
                  f"the board's mover coverage ({mv_pct:.0f}%) is at or above the floor "
                  f"({MOVER_COVERAGE_FLOOR * 100:.0f}%) - it carries NO degradation banner")


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
    #
    # TWO LABEL SHAPES ARE ACCEPTED, because the fleet has TWO marker writers: this
    # family's own marker (`- **Reason:** ...`) and the shared window check's
    # fleet-wide marker (`- Reason: ...`), which is the shape every other routine in
    # the fleet publishes. Demanding only one of them failed a marker the fleet
    # legitimately produced - measured 2026-11-26, when the shared window check
    # declined this very checkpoint and the gate then rejected its marker.
    reason_line = ""
    for ln in t.splitlines():
        m_reason = re.search(r"\*?\*?Reason:\*?\*?", ln)
        if m_reason:
            reason_line = ln[m_reason.end():].strip()
            break
    check(bool(reason_line),
          f"the marker NAMES the reason (got {reason_line!r})")
    # THE SLOT, as a token. This family's marker writes the date-slot stem
    # ("2026-11-26-0830"); the shared window check's marker writes the slot on its
    # own ("0830 - SKIPPED"). A `-{slot}` substring test accepted only the first, so
    # the fleet's own marker shape was rejected by the fleet's own gate.
    check(re.search(rf"(?<!\d){re.escape(slot)}(?!\d)", t) is not None,
          f"the marker names its checkpoint slot ({slot})")
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
    # ------------------------------------------------------------------
    # THE REPO CONTEXT IS A PRECONDITION, NOT A CHECK (2026-11-20).
    #
    # Measured 2026-11-19: this gate was run WITHOUT --repo against a workspace that
    # has no cloud-prompts/ tree. Each of the four static sections then hit its
    # `bad(...); return` and skipped EVERY check it owns - so the gate ran 52 of its
    # 151 checks and printed "FAILED 6 of 52 checks", which reads exactly like an
    # ordinary failure report about the artifact. NINETY-NINE CHECKS OF COVERAGE
    # VANISHED SILENTLY, and the five "missing file" lines looked like defects in
    # the tape. A gate that can lose two thirds of its checks and still look like it
    # ran is not a gate.
    #
    # So the context is now a PRECONDITION: if any of the five files is missing the
    # gate REFUSES to run, names the exact paths, and exits 2. Exit 1 still means
    # "the artifact failed"; exit 2 means "the gate could not be set up" - two
    # different things, and a caller can tell them apart.
    # ------------------------------------------------------------------
    missing = [os.path.join(*parts) for parts in REPO_CONTEXT
               if not os.path.isfile(os.path.join(repo, *parts))]
    if missing:
        print("PRECONDITION FAILED - the repo context is incomplete.")
        print("This gate reads its static sources from the repo root; these are missing:")
        for _m in missing:
            print(f"  - {_m}")
        print()
        print("Fetch them from karizaco/maxhermes-migration@main, then re-run with --repo:")
        print("  R=<dir>; mkdir -p \"$R/cloud-prompts/_shared\" \"$R/cloud-prompts/cron-prompts\"")
        for _parts in REPO_CONTEXT:
            _p = "/".join(_parts)
            print("  curl -sL -H 'Accept: application/vnd.github.raw' \\")
            print(f"    -H \"Authorization: Bearer $GITHUB_TOKEN\" -o \"$R/{_p}\" \\")
            print(f"    \"https://api.github.com/repos/karizaco/maxhermes-migration/contents/{_p}?ref=main\"")
        print()
        print("A PARTIAL CHECK SET IS NOT A RESULT. The gate refuses to run one.")
        return 2
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
