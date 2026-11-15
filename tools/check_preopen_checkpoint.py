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
                    "news_date", "news_url", "pm_notional", "sign_conflict", "sentiment"]
# How old a catalyst may be and still explain a move that happened today. This MUST
# equal the capture script's own CATALYST_MAX_AGE_DAYS - check_script() asserts it,
# because a gate that reads a different window than the one that wrote the tape
# checks nothing.
CATALYST_MAX_AGE_DAYS = 4
# THE CATALYST COVERAGE FLOOR - the share of the tape that must carry a cause for the
# tape to be doing its job. Measured on Friday 2026-11-13 the 08:30 checkpoint wrote
# 164 records and only 16 carried a catalyst (9.8%), and the 09:50 checkpoint wrote
# 218 records and only 20 carried one (9.2%) - the tape priced the movers and
# explained almost none of them, and NOTHING said so. A tape that is 90% unexplained
# reads exactly like a tape that found no news.
#
# 40% flags both Friday checkpoints, and a floor of 10% would have been cleared by
# accident on a day when the tape explained one name in ten. The floor changes how a
# result is LABELLED; it never decides whether the tape is produced.
COVERAGE_FLOOR = 0.40
# The marker a board rendered under the floor carries. A board with NO marker was
# written before the rule existed (see COVERAGE_RULE_EFFECTIVE).
COVERAGE_CONTRACT = "preopen-coverage-v1"
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

    # 9. THE CATALYST COVERAGE FLOOR. The procedure is where the floor, the
    # arithmetic, the labels and the reply lines are SPECIFIED - the prompt is
    # byte-pinned, so this file is the only place the rule can live.
    check(re.search(r"CATALYST_COVERAGE_FLOOR\s*=\s*0\.4[0-9]*\b", t) is not None,
          "the procedure states the COVERAGE FLOOR (40%)")
    check(re.search(r"catalyst_coverage\s*=\s*\(records with a non-null `why`\)\s*/\s*"
                    r"\(total records\)", t) is not None,
          "the procedure states the coverage arithmetic (named `why` rows over total rows)")
    check("16/164" in t and "20/218" in t,
          "the procedure quotes the measured 2026-11-13 evidence (16/164 and 20/218)")
    check(re.search(r"degraded:", t) is not None,
          "the procedure's reply carries a `degraded:` line")
    check(re.search(r"NEVER SUPPRESSES THE CHECKPOINT", t, re.I) is not None,
          "the procedure states that the floor NEVER suppresses the checkpoint")
    check(re.search(r"GRANDFATHERED", t) is not None,
          "the procedure states that a pre-fix board is grandfathered against the floor")
    check(re.search(r"preopen-coverage-v\d+", t) is not None,
          "the procedure names the coverage contract marker")

    # 8. the procedure demands the DATED capture script and states the gate. Without
    # these the procedure could keep asking for the 2026-11-09 script, which publishes
    # a ten-month-old press release as this morning's cause.
    check(re.search(r"CAPTURE_SCRIPT_VERSION:\s*2026-11-13", t) is not None,
          "the procedure demands the 2026-11-13 capture script (the one that takes its "
          "candidates from TODAY's pre-market band)")
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
    # THE CATALYST COVERAGE FLOOR, IN THE CAPTURE.
    #
    # The capture is where the number is MEASURED: the board renders it from the
    # tape, so a capture that does not measure it publishes a board with no
    # coverage on it. The floor constant must match the checker's, or the two
    # sides disagree about what "degraded" means.
    # ------------------------------------------------------------------
    m_cov = re.search(r"CATALYST_COVERAGE_FLOOR\s*=\s*([0-9.]+)", t)
    check(m_cov is not None and abs(float(m_cov.group(1)) - COVERAGE_FLOOR) < 1e-9,
          f"the capture's coverage floor matches the checker's ({COVERAGE_FLOOR})")
    check(re.search(r"catalyst_coverage", t) is not None,
          "the capture MEASURES the catalyst coverage")
    check(re.search(r"errors\.append\(\s*f?[\"']catalyst_coverage_below_floor:", t) is not None,
          "the capture counts a coverage degradation in its OWN error ledger (one error)")
    check(re.search(r"catalyst_price_only", t) is not None,
          "the capture breaks the uncovered rows down by provenance (price-only vs "
          "narrative-only)")


def check_digest_script(path):
    print("digest renderer:")
    t = read(path)
    if not t:
        bad(f"{path} is missing or empty")
        return
    check("PREOPEN_DIGEST_V2" in t, "carries the PREOPEN_DIGEST_V2 marker")
    check("DIGEST_COLUMNS" in t and "Ticker" in t,
          "the board's columns are fixed in code")
    check("TOP_N = 15" in t, "the board lists the top 15 movers")
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
    # THE CATALYST COVERAGE, IN THE RENDERER. The board is where the reader finds
    # out how much of the tape was explained, so the line and the banner have to be
    # rendered HERE and not left to the agent's prose.
    # ------------------------------------------------------------------
    check(re.search(r"COVERAGE_CONTRACT\s*=\s*[\"']preopen-coverage-v\d+[\"']", t) is not None,
          "the renderer stamps the coverage contract marker on the board")
    m_cf = re.search(r"COVERAGE_FLOOR\s*=\s*([0-9.]+)", t)
    check(m_cf is not None and abs(float(m_cf.group(1)) - COVERAGE_FLOOR) < 1e-9,
          f"the renderer's coverage floor matches the checker's ({COVERAGE_FLOOR})")
    check(re.search(r"\*\*catalyst coverage:\*\*", t) is not None,
          "the renderer publishes the catalyst coverage line in the header")
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


def _fmt_et(v):
    """Render a tape timestamp the way the board renders it: ET wall clock.

    This is an INDEPENDENT copy of the renderer's rule, on purpose - a checker that
    calls the code under test proves nothing. tools/test_preopen_digest_contract.py
    pins the renderer's own conversion separately.
    """
    if not v:
        return "\u2014"
    s = str(v).strip()
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
    """Does THE CATALYST COVERAGE FLOOR apply to this board?

    THE GRANDFATHER. A board that carries the CURRENT coverage marker is checked
    against the floor in full. A board that carries a LEGACY marker, or NO marker
    at all and PREDATES the floor's effective date, is checked against the rules
    in force when it was written: a historical artifact is never failed for a rule
    that post-dates it. The same shape as cron #17's `in-play-artifact-v1` marker.

    A board with no marker that is dated ON OR AFTER the effective date is NOT
    grandfathered - it was written under the rule, so it must carry the line. That
    is what stops a renderer that quietly stopped publishing its coverage from
    escaping the gate.
    """
    m = re.search(r"preopen-coverage-v\d+", digest_text)
    marker = m.group(0) if m else None
    if marker == COVERAGE_CONTRACT:
        return True, f"the board carries the CURRENT coverage marker ({marker})"
    if marker is not None:
        return False, (f"the board carries the LEGACY coverage marker ({marker}) - it "
                       "is checked against the rules in force when it was written")
    d = _digest_date(digest_path)
    if d is not None and d < datetime.date.fromisoformat(COVERAGE_RULE_EFFECTIVE):
        return False, (f"the board carries NO coverage marker and was published on {d}, "
                       f"before the floor took effect ({COVERAGE_RULE_EFFECTIVE}) - it "
                       "is grandfathered against the rule")
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
    for cells in body:
        if len(cells) < 5:
            continue
        tick = cells[0].strip()
        rec = by_ticker.get(tick)
        if rec is None:
            continue
        nd = rec.get("news_date")
        want = (_fmt_et(nd) if nd
                else (_fmt_et(rec.get("trending_ts")) if rec.get("trending_ts") else "\u2014"))
        got = cells[4].strip()
        if got != want:
            wrong_time.append((tick, got, want))
        if rec.get("ts") and got == _fmt_et(rec.get("ts")) and want != got:
            cap_fallback.append(tick)
    check(not wrong_time,
          f"every row's 'When it broke' shows the NEWS date, not the capture clock "
          f"({len(wrong_time)} wrong: {wrong_time[:3]})")
    check(not cap_fallback,
          f"no row falls back to the capture clock for its break time ({cap_fallback[:3]})")

    # ------------------------------------------------------------------
    # THE CATALYST COVERAGE FLOOR.
    #
    # The tape's whole job is WHO / WHAT / WHEN for every name materially moving
    # pre-market. Measured on Friday 2026-11-13 the 08:30 tape carried 164 records
    # and only 16 of them carried a catalyst (9.8%), and the 09:50 tape carried 218
    # and 20 (9.2%) - the movers were priced and almost none of them explained, and
    # nothing said so. A tape that is 90% unexplained reads exactly like a tape that
    # found no news.
    #
    # So the board has to PUBLISH the coverage, the arithmetic has to match the tape,
    # and a board below the floor has to carry the degradation in the file a reader
    # opens. A board at or above the floor must NOT carry one.
    # ------------------------------------------------------------------
    named = sum(1 for r in rows if r.get("why"))
    total = len(rows)
    cov_pct = (100.0 * named / total) if total else 0.0
    price_only = [r for r in rows if not r.get("why") and r.get("pct") is not None]
    below = bool(total) and (named / total) < COVERAGE_FLOOR
    applies, why = coverage_rule_applies(t, digest_path)
    if not applies:
        ok(f"the coverage floor does not apply to this board - {why}")
    else:
        m_cov = re.search(r"\*\*catalyst coverage:\*\*\s*(\d+)\s*/\s*(\d+)\s*\((\d+)%\)", t,
                           re.I)
        if check(m_cov is not None,
                 "the board publishes the CATALYST COVERAGE line (named rows / total "
                 "rows / percent) - a board that quietly stopped publishing its "
                 "coverage is the silent failure this rule exists to stop"):
            got_named, got_total, got_pct = (int(m_cov.group(1)), int(m_cov.group(2)),
                                              int(m_cov.group(3)))
            check(got_total == total,
                  f"the coverage line's denominator is the tape's record count "
                  f"({got_total} vs {total})")
            check(got_named == named,
                  f"the coverage line's numerator is the tape's named-record count "
                  f"({got_named} vs {named})")
            check(got_pct == int(round(cov_pct)),
                  f"the coverage percentage matches the arithmetic "
                  f"({got_pct}% vs {int(round(cov_pct))}%)")
        m_fl = re.search(r"\*\*floor:\*\*\s*(\d+)%", t)
        check(m_fl is not None and int(m_fl.group(1)) == int(round(COVERAGE_FLOOR * 100)),
              f"the board publishes the floor it was measured against "
              f"({int(round(COVERAGE_FLOOR * 100))}%)")
        # The COUNTS travel with the percentage, so the number is auditable.
        m_un = re.search(r"\*\*unexplained:\*\*\s*(\d+)\s+records", t)
        check(m_un is not None and int(m_un.group(1)) == (total - named),
              f"the board publishes the uncovered count "
              f"({int(m_un.group(1)) if m_un else '?'} vs {total - named})")
        degraded = "DEGRADED" in t
        m_st = re.search(r"\*\*(BELOW FLOOR|AT OR ABOVE THE FLOOR)\*\*", t)
        if check(m_st is not None,
                 "the board states whether its coverage is below the floor"):
            stated_below = (m_st.group(1).upper() == "BELOW FLOOR")
            check(stated_below == below,
                  f"the board's floor verdict matches the arithmetic "
                  f"(stated {'BELOW FLOOR' if stated_below else 'AT OR ABOVE THE FLOOR'}, "
                  f"computed {'BELOW FLOOR' if below else 'AT OR ABOVE THE FLOOR'})")
        if below:
            check(degraded,
                  f"the board's coverage ({cov_pct:.0f}%) is BELOW the floor "
                  f"({COVERAGE_FLOOR * 100:.0f}%) - it carries the DEGRADED banner")
            check(re.search(r"below the \d+% floor", t, re.I) is not None,
                  "the degradation says WHICH floor it fell below")
            check("price-only" in norm(t),
                  "the degradation names the PRICE-ONLY rows (priced, no cause)")
            check(re.search(r"grounded catalyst call", t, re.I) is not None,
                  "the degradation NAMES THE CAUSE (the grounded catalyst call did not "
                  "explain those rows)")
            # WHICH names are price-only. A degradation that says "some of them" is not
            # a finding: every price-only row on the board has to be named.
            pline = ""
            for ln in t.splitlines():
                if "Price-only names" in ln:
                    pline = ln
                    break
            if check(bool(pline),
                     "the degradation LISTS the price-only names"):
                by_ticker = {r.get("ticker"): r for r in rows}
                missing = []
                for cells in body:
                    if len(cells) < 2:
                        continue
                    rec = by_ticker.get(cells[0].strip())
                    if rec is None or rec.get("why") or rec.get("pct") is None:
                        continue          # not a price-only row
                    if cells[0].strip() not in pline:
                        missing.append(cells[0].strip())
                check(not missing,
                      f"every price-only row on the board is named in the price-only "
                      f"list ({missing[:5]})")
        else:
            check(not degraded,
                  f"the board's coverage ({cov_pct:.0f}%) is at or above the floor "
                  f"({COVERAGE_FLOOR * 100:.0f}%) - it carries NO degradation banner")


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
