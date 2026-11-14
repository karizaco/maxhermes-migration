#!/usr/bin/env python3
"""
CAPTURE_SCRIPT_VERSION: 2026-11-13.2
preopen_capture.py — write the pre-open catalyst tape.

WHY THIS EXISTS
---------------
A 15:50 ET digest can see where a stock IS, not where it came from, and not the
catalyst as it was understood at the open. This script records that: for each name
moving pre-market or at the open, WHO moved, WHAT moved it, and WHEN the news broke.

FIVE CALLS, FIVE JOBS
--------------------
  1. trending_symbols      (stocktwits pack)  -> candidates + a natural-language
      reason + a timestamp for each. This is the retail/WSB/X-chatter signal and
      it is LIVE: the summary carries its own `summary_at` stamp.
  2. top_movers gainers   (market-recap pack) -> GROUND TRUTH price, %chg, volume.
  3. top_movers losers    (market-recap pack) -> the SAME ground truth for the other
      DIRECTION. The two calls are DISJOINT halves of one movers scan (a name cannot
      be both a top gainer and a top loser), so merging them can never put two prices
      on one record. A gainers-only scan is not a pre-open tape: on 2026-11-09 it
      missed IRTC -30.7%, DKNG -21.3% and AXON -18.2%, the day's worst decliners.
THE CATALYST PIPELINE - ARTICLE FIRST, THEN THE ROUTER, BOTH IN PARALLEL
-------------------------------------------------------------------------
  4. polygon_io_news      (polygon-io pack)   -> THE CATALYST, consulted FIRST.
      It answers in 0.21-0.24s with the publication stamp AND the article URL,
      and it is consulted before the router because it is 60-100x cheaper and
      more reliable at the one thing the router cannot do: say WHEN. Measured
      2026-11-13: the direct feed returned a dated article for 6 of 8 large
      names while the router's own polygon path errored on 4 of the same 8.
      The published article is the provider's NEWEST, so its stamp IS the
      provider's freshest stamp - the ARWR/NOVT defect cannot arise here.
  5. ask_pipeworx_grounded (market-recap pack) -> a per-name catalyst with
      evidence and confidence, spent ONLY on a name the feed could not date.

  Both phases run in PARALLEL: measured 2026-11-13, 8 concurrent grounded calls
  took 20.19s against 101.77s serial, with no rate limiting. The sequential
  calls had been ~264s of the capture's 270s - 98% of its wall clock.

  A row's confidence is `low` unless a DATED, in-window, checkable catalyst
  raises it; a retail-chatter reason can never earn more than `low`. A cause
  whose direction contradicts the move is demoted and flagged `sign_conflict`.

The grounded-call budget is spent on the biggest movers by |%|, in BOTH directions:
ranking by change_pct instead would put every decliner behind every gainer and the
worst pre-open loser would never get a catalyst.

**Prices always come from calls 2 and 3.** Calls 1, 4 and 5 explain; they never price.
A percentage that disagrees with the movers scan by more than 2pp is marked
`unverified`.

THE CANDIDATE SOURCE - WHY THE BAND EXISTS
------------------------------------------
The tape's candidates used to come from Yahoo's `top_movers`, which is a PREDEFINED
SCREENER over the LAST COMPLETED REGULAR SESSION. Before the open, that session is
YESTERDAY: so the tape named yesterday's movers, and the brief's screen - which is
TODAY's pre-market movers - barely intersected it.

Measured on the 2026-11-10 fire: the 08:30 checkpoint carried **49 rows** and covered
**6 of the 50 names the brief published**. On 2026-11-12 the 08:30 tape covered **21 of
693** screen names (3.0%) and **9 of 21** actionable names. A tape that cannot see
today's movers cannot serve a brief about today's movers.

So the candidate source is now the **CURRENT session's pre-market band**: every US stock
trading more than +/-2.5% pre-market, pulled from the TradingView scanner in TWO
DISJOINT halves (the gainers and the decliners, exactly like the movers scan's two
halves). The band IS today's tape, so the names the brief publishes are the names the
tape carries. Measured on 2026-11-12 at 09:04 ET the band held 693 names; at 08:30 ET
it held ~380, and the tape now carries every one of them that cleared the floor.

The `top_movers` scan is NOT removed: it still supplies the previous session's movers,
which is where a name that is being watched BEFORE it gaps comes from, and the checker
(`tools/check_preopen_checkpoint.py`) asserts that the losers half is scanned too.

THE PRE-MARKET PRINT - WHY CALL 6 EXISTS
-----------------------------------------
Calls 2 and 3 (top_movers) are Yahoo's PREDEFINED SCREENER over the last COMPLETED
REGULAR SESSION. Before the open, that session is the PREVIOUS day, so those calls
returned FRIDAY's movers with FRIDAY's closes, and the tape published them as if they
were this morning's pre-market.

Measured on the 2026-11-09 08:30 tape: 14 of 14 testable priced rows were EXACTLY the
previous session's close and the previous session's move (IRTC -30.70% at 90.22, from
130.19 on Nov 5 to 90.22 on Nov 6). TradingView's own pre-market for IRTC that morning
was +0.86% at 91.00. The tape was reporting Friday's move as if it were Monday's
pre-market, and the 2026-11-09 commit that "fixed" the tape then read its own output as
Monday's decliners.

So call 6 asks the TRADINGVIEW SCANNER for the CURRENT session's pre-market print
(`premarket_change` / `premarket_close`) for the names the tape carries, and the tape's
`pct` and `price` come from THAT. The movers scan (calls 2 and 3) still decides WHICH
names are on the tape; the scanner supplies the number that belongs to the session the
tape is about.

Two rules follow, and both are about not inventing a number:
  * A name the scanner does not carry has NO pre-market print. It keeps `pct`/`price`
    NULL and is published as a narrative row (`src: stocktwits`), exactly like a
    trending-only name. It DID NOT trade pre-market, and that is the honest result.
  * The grounded-call budget is spent on the biggest movers by THIS session's |%|, not
    by the previous session's. Otherwise the budget would buy catalysts for yesterday's
    movers and today's would never get one.

The tape's row shape is a CONTRACT with cron #17, so this changes no key: `pct` and
`price` are populated from the scanner instead of the movers scan, and nothing else about
a row changes.

THE STALENESS GATE - WHY THIS FILE NOW CARRIES A DATE
-----------------------------------------------------
A catalyst without a date is a claim with nothing behind it. Measured on the
2026-11-09 09:50 checkpoint, ARWR (-16.59%) carried the 2026-01-06 press release
"Arrowhead announced significant positive interim trial results ... with stock
surging 17.81% to a new 52-week high" - a story about the opposite move, from ten
months earlier - and the board printed "09:53:48" in its **When it broke** column,
because that column fell back to the CAPTURE clock. The board therefore asserted,
in a column whose whole job is to say when the news broke, that a January press
release broke forty minutes ago.

So every catalyst is now DATED (call 5) and dated catalysts are AGE-CHECKED:

  * `news_date` - the article's `published_utc`, ISO-8601, or null if no date could
    be resolved. The board prints it; it never invents one.
  * `news_url`  - the article the catalyst came from, so the claim is checkable.
  * A catalyst whose newest dated evidence for that company is older than
    CATALYST_MAX_AGE_DAYS is DROPPED: `why` goes to null, the row reverts to
    `src: scanner` (its price, and nothing else) and the name is listed in the run's
    stale-dropped report. A cause that cannot be today's news is not a cause.
  * A catalyst whose date cannot be resolved is KEPT but demoted to `conf: low`
    with `news_date: null`, and the board shows an em-dash rather than a clock. An
    undated cause is a weaker claim, not a false one.

Both rules are checked by tools/check_preopen_checkpoint.py, and the ARWR case
itself is a fault-injection case in tools/test_preopen_checkpoint_contract.py.

xAI / Grok is OPTIONAL. The xAI chat API no longer serves live search
(`search_parameters` returns HTTP 410 "Live search is deprecated"), and the
Agent Tools API that replaces it is not enabled on most keys. Pipeworx does the
job without it. If XAI_API_KEY is set AND `XAI_MODEL` names a model that answers
without search, its output is added as a second opinion at `conf: medium`.

USAGE
  preopen_capture.py                        # today, this checkpoint, default path
  preopen_capture.py --date 2026-11-03 --checkpoint 0830 --out /tmp/tape.jsonl
  preopen_capture.py --dry-run              # print, do not write

EXIT CODES
  0 = tape written (or correctly skipped: no key)
  1 = a source failed outright
  2 = usage error
"""

import argparse
import concurrent.futures as _cf
import datetime
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

GATEWAY = "https://gateway.pipeworx.io"
PACK_MARKET = "market-recap"
PACK_STOCKTWITS = "stocktwits"
# The article feed. It is a SEPARATE pack from market-recap: the grounded router uses
# polygon_io_news internally and returns a SUMMARY of an article with no date and no
# URL, so the router alone cannot tell a January press release from a this-morning
# one. Calling the provider directly is what gives every catalyst a real
# `published_utc`. (The pack is not listed in market-recap's tools/list; it is
# reachable through the same gateway and through discover_tools.)
PACK_POLYGON = "polygon-io"
CAT_PATTERNS = [
    ("acquisition", r"\bacquir|acquisition|merger|to buy|takeover|buyout|definitive agreement"),
    ("fda", r"\bfda|approval|approved|cleared by the fda|priority review|breakthrough therapy"),
    ("trial", r"\bphase\s*[123]|clinical trial|trial results|pivotal|data readout"),
    ("earnings", r"\bearnings|q[1-4]\b|beat|missed|results|revenue|eps"),
    ("guidance", r"\bguidance|outlook|forecast|raises? (its )?full|lowers? (its )?full"),
    ("guidance-cut", r"\bcut(?:s)? (its )?(guidance|outlook)|withdraws? guidance"),
    ("offering", r"\boffering|at-the-market|atm\b|shelf|raise[s]? capital|\bupload\b"),
    ("halt", r"\bhalt|luld|trading halt|resum"),
    ("downgrade", r"\bdowngrade|lowers? (its )?price target|cuts? (its )?price target"),
    ("dividend", r"\bdividend|buyback|repurchase"),
    ("spin", r"\bspin-?off|spinout|stake sale"),
]
CAT_VOCAB = {"acquisition", "merger", "earnings", "guidance", "fda", "trial", "offering",
             "halt", "downgrade", "guidance-cut", "spin", "dividend", "other"}
DISAGREE_PP = 2.0
# Liquidity floor, mirroring the skill's own open-slot floor. Without it the movers scan
# returns 600+ rows dominated by sub-$1 shells that genuinely moved hundreds of percent
# (measured 2026-11-06: NEXR +742% at $2.01, RCT +68% at $0.0505, SITC -83% at $0.61).
MIN_PRICE = 1.0
MIN_DOLLAR_VOL = 1_000_000
# The floor on a name that HAS a pre-market print is NOT a price floor and NOT the
# movers scan's dollar volume: it is the SIZE OF THE PRINT, in SHARES. A pre-market
# print of fewer than 25,000 shares is one seller, not a market, and it is dropped
# from the tape.
#
# SHARES, and not a dollar notional, for two reasons. First, a share count is MONOTONE
# in time: a name that has printed 25,000 shares by 08:30 has printed more by 09:22,
# so the floor never excludes a name that later qualifies (a notional floor is not:
# the price can fall under it). Second, it is the SAME instrument and the SAME number
# as cron #25's fourth gate leg, so the tape and the brief that reads it speak one
# language: below 25,000 pre-market shares is a quote, not a market.
#
# Measured on the 2026-11-12 screen at 09:04 ET: a $100K pre-market-notional floor
# keeps 251 of 693 names and the floor's purpose is visible in what it removes
# (VECA $28.6K, OPRX $15.8K, DSS $0.2K - quote prints) and in what it KEEPS:
# PARA, whose pre-market print was $48.96M, and PSFE at $358,898.
#
# The floor is deliberately NOT a $1 price floor either. The old one was, and it
# deleted the day's most violent prints for being cheap: PARA +79%, ICMB +57%,
# CENN +38% - all real money on a low-priced share - which is exactly what cron
# #25's below-the-floor watchlist exists to publish. Measured on the 2026-11-13 band
# at 07:57 ET: the $100K-notional floor kept 72 of 458 names and DROPPED CRIS
# (-10.6% on 39,053 shares, $19,956) - a real mover on a cheap share, and one of the
# names cron #25 has to publish. The 25,000-SHARE floor keeps 118 of the same 458 and
# keeps CRIS.
MIN_PM_SHARES = 25_000
# The pre-market band: +/-2.5%. Historically the tape was a "+/-3% snapshot" (678 rows
# on 2026-11-04) and then a "+/-2.5% movers-sorted snapshot" (849 rows on 2026-11-06),
# and 2.5% is the width that keeps the day's biggest movers inside the tape.
BAND_PCT = 2.5
# How old a catalyst may be and still be allowed to explain today's move.
#
# FOUR DAYS, and not one: the 08:30 checkpoint on a MONDAY has to reach Friday's and
# the weekend's news, or every Monday board would look like a quiet one.
#
# The gate exists because a cause that cannot be today's news is not a cause.
# Measured 2026-11-09: ARWR fell 16.6% and the router attached Arrowhead's
# 2026-01-06 obesity press release ("stock surging 17.81% to a new 52-week high") as
# the reason, at `conf: high`. The provider's newest dated evidence for ARWR that
# day was 2026-09-30, so a four-day window rejects the claim; the honest tape row is
# the price with no catalyst.
CATALYST_MAX_AGE_DAYS = 4

# ---------------------------------------------------------------------------
# THE CATALYST PIPELINE - ARTICLE FIRST, THEN THE ROUTER, BOTH IN PARALLEL
# ---------------------------------------------------------------------------
# Measured 2026-11-13 (the 2026-11-13 09:50 checkpoint): the SEQUENTIAL grounded
# calls were ~264s of the capture's 270s - 98% of it - while the four feed calls
# took 2.6s. And the two paths are not equally good:
#
#   * the ARTICLE feed (polygon_io_news) costs 0.21-0.24s per name and answers
#     DIRECTLY: measured 2026-11-13 at 22:49 ET, 6 of 8 large names returned a
#     dated article from the feed;
#   * the ROUTER (ask_pipeworx_grounded) costs 15s when it answers and 21s when
#     it REFUSES - and its own polygon path returned `tool_error` on 4 of the
#     same 8 names the direct feed served. The useless path is the slow one.
#
# So the feed goes FIRST and the router only spends a call on a name the feed
# could not date. The router's 15-25s is then spent on the names that actually
# need it (a press release the feed missed), instead of on a name that was
# going to refuse anyway.
#
# PARALLELISM is safe at this width: measured 8 concurrent grounded calls in
# 20.19s against 101.77s serial - 5.0x - with no rate limiting and no HTTP
# failure (the `tool_error`/`not_in_source` values are the router's own
# refusals, identical to its serial behaviour). 8 concurrent article fetches
# took 1.98s against 14.80s serial.
CATALYST_WORKERS = 8
# How many names are put in contention for a catalyst at all. The pool is the
# cheapest pass - one article fetch each - so it can be wider than the router
# budget; the router budget stays `top_n` and is spent only on pool names the
# feed could not date.
# The pool IS the budget: one article call per name that can earn a cause. It is
# NOT wider than that, because every article call is a metered provider call
# (200 credits each, measured 2026-11-13) and the wallet is finite - a pool twice
# the budget would double the checkpoint's provider spend for names that never
# reach the board.
CATALYST_POOL_MULT = 1

# ---------------------------------------------------------------------------
# THE SIGN PROBE - does the catalyst's direction agree with the move's?
# ---------------------------------------------------------------------------
# A positive story on a negative row is the ARWR defect in a new costume: on
# 2026-11-12 DGII (-20.50%) carried "Digi International beat Q4 2026 earnings
# expectations with $0.78 EPS versus consensus of $0.76" at `conf: high` WITH a
# date. The price was right (the regular session closed -11.72%), so the stock
# did fall - but the cause published on the tape does not explain the fall, and
# cron #17 reads this text at 15:50 as THE reason.
#
# The probe counts direction words in the catalyst and compares the SIGN of the
# score with the sign of the move. A margin is required, because a story can
# carry both directions ("sold off despite a strong beat"): a score of zero or
# one is no evidence of a contradiction. Measured against all 18 catalysts on
# the 2026-11-12 tape, a margin of 2 flags exactly the rows whose published
# cause does not explain the move and nothing else.
SIGN_MARGIN = 2
SIGN_POS = ("beat", "beats", "record", "upgrade", "upgraded", "approval", "approved",
            "surge", "surged", "surging", "soared", "soars", "spiked", "spikes",
            "skyrocketed", "jumped", "jumps", "climbed", "rallied",
            "strong", "stronger", "bullish",
            "rally", "rallying", "higher", "buyback", "repurchase", "awarded",
            "boost", "surpass", "surpassing", "exceed", "exceeding", "tops",
            "outperform", "growth", "positive", "upbeat", "improved",
            "raised guidance", "raises guidance", "raised its", "raises its",
            "record revenue", "record profit")
SIGN_NEG = ("miss", "missed", "misses", "fell short", "short of", "downgrade",
            "downgraded", "weak", "weaker", "weakness", "softer", "lower", "sell-off",
            "selloff", "sold off", "slump", "plunge", "plunged", "warning", "warns",
            "delay", "delayed", "resign", "resignation", "probe", "lawsuit",
            "trading halt", "luld", "loss", "losses", "dilution", "worry", "worried", "concern",
            "concerns", "turmoil", "turbulent", "troubled", "unfavorable", "negative",
            "offering", "at-the-market", "shelf offering", "raise capital",
            "raises capital", "raising capital", "cut guidance", "cuts guidance",
            "lowers guidance", "pullback", "give back", "short interest", "bearish")
# THE HEDGE CLAUSE. A catalyst often states the cause and then reports the DEBATE
# about it - "..., though some question whether backlog can convert into sustained
# profitability and point to continuing operating losses and dilution concerns".
# The negative words there belong to the bears, not to the cause, and counting them
# makes the probe fire on a perfectly good catalyst. So the probe reads only the
# text BEFORE the hedge: the cause is always stated first.
SIGN_HEDGE = re.compile(
    r"\b(?:though|although|however|while others|others (?:worry|focus|caution|argue|note|question)"
    r"|some (?:traders|see|argue|question|count)|while bulls|bulls argued|bears)\b", re.I)

UA = {"User-Agent": "MaxHermes-Cron/1.0"}

# The checkpoint slots cron #17 merges by NAME. A slot is a slot, never a wall clock.
ALLOWED_SLOTS = ("0830", "0920", "0950")
# How late a dispatch may be and still snap down onto the slot it belongs to.
SNAP_MAX_MIN = 90


def resolve_slot(cp):
    """Return (slot, note). A late dispatch snaps DOWN; past the window it refuses.

    A literal `date +%H%M` names an 08:35 execution "0835" -- a slot cron #17 never
    reads, because it merges the checkpoints by slot name. Worse, a phantom slot sorts
    AFTER 0950, so a consumer replaying the checkpoints oldest-first would replay the
    08:30 tape LAST. Measured 2026-11-05: the 08:30 slot's work began at 10:09 ET after
    a platform stall and a wall-clock slot would have named its file 1010.
    """
    if cp in ALLOWED_SLOTS:
        return cp, None
    try:
        mins = int(cp[:2]) * 60 + int(cp[2:])
    except Exception:
        return None, f"unparseable checkpoint slot {cp!r}"
    best = None
    for s in ALLOWED_SLOTS:
        sm = int(s[:2]) * 60 + int(s[2:])
        if sm <= mins and (best is None or sm > best[0]):
            best = (sm, s)
    if best and (mins - best[0]) <= SNAP_MAX_MIN:
        return best[1], (f"slot {cp} snapped DOWN to {best[1]} "
                         f"({mins - best[0]} min late dispatch)")
    return None, (f"checkpoint slot {cp} is more than {SNAP_MAX_MIN} min past its own "
                  f"slot — no filename invented")


def _et():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("America/New_York")
    except Exception:
        return datetime.timezone(datetime.timedelta(hours=-5))


# A CREDIT FAILURE IS NOT A "NO NEWS" ANSWER. The gateway answers an exhausted
# account with "Insufficient credits. This tool costs 200 credits" or "This is a
# paid feature. Today's free allowance is used up" - and a caller that cannot tell
# that from an empty result silently publishes a tape with NO catalysts and reports
# no error at all. Measured 2026-11-13 23:40 ET: every pack answered that way
# after the account's balance ran out mid-run.
CREDIT_MARKERS = ("insufficient credit", "paid feature", "free allowance",
                  "purchase more", "upgrade your plan")


def _is_credit_error(msg):
    m = str(msg or "").lower()
    return any(k in m for k in CREDIT_MARKERS)


def rpc(pack, tool, args, timeout=120, prefer=None):
    """One JSON-RPC tools/call against a gateway pack.

    The tool's `content` array can carry MORE THAN ONE text block, and each block can be
    a JSON string containing JSON. `ask_pipeworx_grounded` returns two blocks — the
    answer object and the underlying source payload — concatenated in one text run when
    joined. So: parse each block separately, decode up to twice, and pick the first
    document that actually carries what the caller asked for.
    """
    url = f"{GATEWAY}/{pack}/mcp"
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": tool, "arguments": args}}
    headers = {"Content-Type": "application/json",
               "Accept": "application/json, text/event-stream"}
    key = os.environ.get("PIPEWORX_API_KEY")
    if key:
        headers["Authorization"] = "Bearer " + key
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers)
    try:
        raw = urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as exc:
        return {"error": f"http_{exc.code}"}
    except Exception as exc:
        return {"error": f"transport: {str(exc)[:120]}"}
    data = None
    try:
        data = json.loads(raw)
    except Exception:
        for line in reversed(raw.splitlines()):
            if line.startswith("data: "):
                try:
                    data = json.loads(line[6:])
                    break
                except Exception:
                    pass
    if not isinstance(data, dict) or "result" not in data:
        msg = ""
        if isinstance(data, dict) and isinstance(data.get("error"), dict):
            msg = str(data["error"].get("message") or "")
        return {"error": (f"rpc_failed: {msg[:140]}" if msg else "rpc_failed"),
                "detail": msg[:200], "raw": raw[:200],
                "credit": _is_credit_error(msg)}
    res = data["result"]
    if res.get("isError"):
        return {"error": "tool_error", "detail": str(res.get("content"))[:300]}

    docs = []
    for c in res.get("content", []) or []:
        if c.get("type") != "text":
            continue
        blob = c.get("text", "")
        for _ in range(3):
            if not isinstance(blob, str):
                break
            try:
                blob = json.loads(blob)
            except Exception:
                break
        if isinstance(blob, dict) and blob:
            docs.append(blob)
    if not docs:
        return {"error": "no_json_content"}
    if prefer:
        for d in docs:
            if any(k in d for k in prefer):
                return d
    return docs[0]


def call_trending():
    """Candidates with a live reason and a timestamp."""
    out = rpc(PACK_STOCKTWITS, "trending_symbols", {}, prefer=["symbols"])
    if "error" in out:
        return {"error": out["error"]}
    rows = []
    for s in out.get("symbols", []) or []:
        tr = s.get("trends") or {}
        rows.append({
            "ticker": (s.get("symbol") or "").upper(),
            "name": s.get("title"),
            "why": (tr.get("summary") or "").strip() or None,
            "ts": tr.get("summary_at"),
            "score": s.get("trending_score"),
            "sector": s.get("sector"),
        })
    return {"rows": [r for r in rows if r["ticker"]]}


def call_scanner_premarket(tickers):
    """The CURRENT session's pre-market print for these tickers.

    The TradingView scanner carries `premarket_change` and `premarket_close`: the move
    and the print of the session that is ABOUT TO OPEN. This is the only source in the
    fleet that answers "what is this name doing right now" before the bell - Yahoo's
    quote fields (and therefore the movers scan) carry the LAST COMPLETED SESSION's
    close and move until the open.

    One POST for the whole candidate set, zipped BY COLUMN NAME so a reordered or
    shortened column list cannot put a price into a percent column. A ticker the
    scanner does not carry is simply ABSENT from the result - the caller must treat
    that as "no pre-market print", never as a zero.
    """
    syms = [t for t in tickers if t]
    if not syms:
        return {"rows": {}, "error": "no tickers"}
    cols = ["name", "description", "premarket_change", "premarket_close",
            "premarket_volume", "exchange"]
    body = {"filter": [{"left": "type", "operation": "equal", "right": "stock"},
                       {"left": "name", "operation": "in_range", "right": syms}],
            "columns": cols, "range": [0, len(syms) + 5]}
    req = urllib.request.Request(
        "https://scanner.tradingview.com/america/scan",
        data=json.dumps(body).encode(),
        headers={**UA, "Content-Type": "application/json"})
    try:
        res = json.loads(urllib.request.urlopen(req, timeout=45).read())
    except Exception as exc:
        return {"rows": {}, "error": f"scanner_failed: {str(exc)[:120]}"}
    out = {}
    for row in res.get("data") or []:
        d = row.get("d") or []
        if len(d) < len(cols):
            continue
        rec = dict(zip(cols, d))
        t = (rec.get("name") or "").upper()
        if not t:
            continue
        try:
            pm_chg = float(rec.get("premarket_change"))
            pm_px = float(rec.get("premarket_close"))
        except (TypeError, ValueError):
            # No pre-market print for this name (it never traded pre-market). That is
            # a fact, and it is published as a NULL number, never as 0.
            continue
        out[t] = {"pct": pm_chg, "price": pm_px,
                   "volume": rec.get("premarket_volume"),
                   "name": rec.get("description"), "exchange": rec.get("exchange")}
    return {"rows": out, "total": len(out), "requested": len(syms)}


def call_scanner_band(pct=BAND_PCT, limit=1000):
    """The CURRENT session's pre-market BAND: every US stock moving more than +/-pct.

    Two DISJOINT pulls - the gainers (`premarket_change > pct`, sorted descending) and
    the decliners (`premarket_change < -pct`, sorted ascending). A name cannot be in
    both halves, so no record can ever carry two prices, exactly like the movers
    scan's two halves.

    This is the tape's CANDIDATE SOURCE, and it is the reason the tape can serve a
    brief: Yahoo's `top_movers` is a screener over the LAST COMPLETED session, so
    before the open it names YESTERDAY's movers. The band is today's actual pre-market
    tape.

    `range` is a page size, not a filter: each half is checked against `totalCount`
    and a truncated half is REPORTED, never silently published as a whole tape.
    """
    out = {}
    counts = {}
    truncated = []
    for side, op, right, order in (("up", "egreater", pct, "desc"),
                                    ("down", "eless", -pct, "asc")):
        body = {"filter": [{"left": "type", "operation": "equal", "right": "stock"},
                           {"left": "exchange", "operation": "not_in_range",
                            "right": ["OTC"]},
                           {"left": "premarket_change", "operation": op, "right": right}],
                "columns": ["name", "description", "premarket_change", "premarket_close",
                            "premarket_volume", "exchange"],
                "sort": {"sortBy": "premarket_change", "sortOrder": order},
                "range": [0, limit]}
        req = urllib.request.Request(
            "https://scanner.tradingview.com/america/scan",
            data=json.dumps(body).encode(),
            headers={**UA, "Content-Type": "application/json"})
        try:
            res = json.loads(urllib.request.urlopen(req, timeout=45).read())
        except Exception as exc:
            return {"error": f"band_failed: {str(exc)[:120]}", "rows": {}}
        data = res.get("data") or []
        counts[side] = len(data)
        total = res.get("totalCount")
        if isinstance(total, int) and total > len(data):
            truncated.append(f"{side}: {len(data)} of {total}")
        for row in data:
            d = row.get("d") or []
            if len(d) < 6:
                continue
            rec = dict(zip(["name", "description", "premarket_change", "premarket_close",
                            "premarket_volume", "exchange"], d))
            t = (rec.get("name") or "").upper()
            if not t:
                continue
            try:
                pm_chg = float(rec.get("premarket_change"))
                pm_px = float(rec.get("premarket_close"))
            except (TypeError, ValueError):
                continue
            out[t] = {"pct": pm_chg, "price": pm_px,
                      "volume": rec.get("premarket_volume"),
                      "name": rec.get("description"), "exchange": rec.get("exchange")}
    return {"rows": out, "up": counts.get("up", 0), "down": counts.get("down", 0),
            "total": len(out), "truncated": truncated}


def call_top_movers(category="gainers", limit=40):
    """Ground-truth prices for the movers."""
    out = rpc(PACK_MARKET, "top_movers", {"category": category, "limit": limit}, prefer=["movers"])
    if "error" in out:
        return {"error": out["error"]}
    movers = {}
    for m in out.get("movers", []) or []:
        movers[(m.get("symbol") or "").upper()] = {
            "price": m.get("price"), "change_pct": m.get("change_pct"),
            "volume": m.get("volume"), "name": m.get("name"),
            "exchange": m.get("exchange")}
    return {"movers": movers, "as_of": out.get("as_of"), "total": out.get("total")}


def call_grounded(ticker, name=None):
    """A per-name catalyst with evidence, URL and confidence."""
    who = f"{name} ({ticker})" if name else ticker
    # Ask for NEWS routing explicitly. The router will otherwise reach for SEC filings
    # first and come back empty ("not_in_source") on a name that moved on a press release.
    q = (f"What specific news, press release, analyst action or corporate event moved "
         f"{who} stock sharply right now? Prefer company news, press releases and news wires "
         "over SEC filing index entries. Give the one-clause reason and the source URL.")
    out = rpc(PACK_MARKET, "ask_pipeworx_grounded", {"question": q},
              prefer=["ask_pipeworx_grounded"])
    if "error" in out:
        return {"error": out["error"]}
    r = out.get("ask_pipeworx_grounded") or {}
    ans = (r.get("answer") or "").strip()
    # The router sometimes restates the PRICE MOVE instead of naming a catalyst, and
    # sometimes reaches for the wrong source. Both are caught here, not downstream.
    if ans and re.search(r"(moved|rose|fell|up |down )\s*\$?\d|\d+(\.\d+)?%\s*(increase|decrease|move)", ans, re.I):
        ans = ""
    newsish = ("news", "press", "wire", "article", "headline", "8k", "sec_events")
    tool = (r.get("tool_used") or "")
    if ans and not any(t in tool.lower() for t in newsish):
        ans = ""                      # a filing index entry is not a catalyst
    conf = r.get("confidence") or 0
    if ans and conf < 0.6:
        ans = ""
    return {"answer": ans or None, "evidence": r.get("evidence"),
            "confidence": conf, "refusal": r.get("refusal_reason"),
            "tool_used": r.get("tool_used"), "second_source": r.get("second_source")}


def fetch_articles(ticker, limit=8, attempts=3):
    """The provider's articles for one ticker, with the FAILURE kept separate.

    Returns (articles, error).

    IT RETRIES, because the pack FAILS INTERMITTENTLY: measured 2026-11-13
    23:50-00:20 ET, the same ticker returned `tool_error` for 8 calls in one batch
    and answered the next 18. And the failure is kept SEPARATE from the empty
    result on purpose: "the provider errored" and "the provider holds nothing" are
    different facts, and the second one silently costs a name its dated catalyst -
    the pipeline would send it to the expensive router and publish a price with no
    cause, which is exactly what the article-first design is here to prevent.
    """
    err = None
    detail = None
    for i in range(attempts):
        out = rpc(PACK_POLYGON, "polygon_io_news", {"ticker": ticker, "limit": limit},
                  prefer=["results"])
        if "error" not in out:
            res = out.get("results")
            return (res if isinstance(res, list) else []), None
        err = out.get("error")
        detail = out.get("detail")
        if out.get("credit"):
            # The account is exhausted. Retrying cannot help and would only spend
            # the run's wall clock: fail fast and let the run REPORT it.
            return [], f"{err}: {detail}" if detail else err
        time.sleep(0.4 * (i + 1))
    return [], (f"{err}: {detail}" if detail else err)


def call_polygon_news(ticker, limit=8):
    """The provider's articles for one ticker, each with its own publication stamp.

    WHY THIS IS NOT THE ROUTER
    --------------------------
    `ask_pipeworx_grounded` answers "what happened" and returns a SUMMARY of an
    article. It does not return the article's date, and it does not return the URL
    even when the question demands it (measured 2026-11-09: the question said "Give
    the one-clause reason and the source URL" and the payload carried no URL and no
    date). A summary with no date cannot be age-checked, and an un-age-checkable
    summary is exactly how a ten-month-old press release becomes this morning's
    headline at `conf: high`.

    The provider is reachable through the same gateway under its own pack, and every
    article carries `published_utc`, `article_url`, `title` and `description`. That is
    the field the staleness gate needs.
    """
    arts, _err = fetch_articles(ticker, limit=limit)
    return arts


def _parse_iso(s):
    """An ISO-8601 stamp as an aware datetime, or None."""
    try:
        raw = str(s).strip().replace("Z", "+00:00")
        dt = datetime.datetime.fromisoformat(raw)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt


def _iso_z(dt):
    return dt.astimezone(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


# Words that carry no signal when matching an article to a catalyst sentence.
_STOP = {"the", "and", "for", "with", "its", "was", "were", "has", "have", "had",
         "that", "this", "from", "after", "into", "over", "than", "then", "they",
         "stock", "shares", "company", "announced", "reported", "said"}


def _tokens(text):
    if not text:
        return set()
    return {t for t in re.findall(r"[a-z0-9]{3,}", str(text).lower()) if t not in _STOP}


def resolve_news_date(ticker, answer, cutoff, articles=None):
    """Date a grounded catalyst, and expose how fresh that company's news actually is.

    Returns (news_date_iso, news_url, freshest_iso):
      * news_date_iso - the publication stamp of the article the catalyst came from:
                        the best textual match to the grounded answer, or the
                        freshest article for the name when nothing matches. None if
                        no date could be resolved.
      * news_url      - that article's URL, so the claim can be checked. None if
                        there is no article.
      * freshest_iso  - the publication stamp of the NEWEST dated article the
                        provider holds for this company, or None.

    The gate reads `freshest_iso`, not `news_date_iso`, and that is deliberate. The
    router reads the SAME provider, so if the provider's newest article for a name
    is old, the router cannot have found anything newer - and its answer is not
    about today's move no matter how confident it sounds. Gating on the match alone
    would let a good-text match to a January article through.

    `cutoff` is the capture instant: an article published after the snapshot cannot
    be the cause of a move the snapshot recorded.

    `articles` is the ALREADY-FETCHED article list, when the caller has one. The
    article-first pipeline fetches every name's articles ONCE and reuses the list
    here, so a dated catalyst costs one provider call instead of two.
    """
    if articles is None:
        articles = call_polygon_news(ticker)
    dated = []
    for a in articles:
        # The caller may hand over the RAW articles or the ALREADY-PARSED (dt, a)
        # pairs the pipeline built. Both are accepted, so one fetch serves both.
        if isinstance(a, tuple):
            dt, art = a
        else:
            dt = _parse_iso(a.get("published_utc"))
            art = a
        if dt is None:
            continue
        if cutoff is not None and dt > cutoff:
            continue
        dated.append((dt, art))
    if not dated:
        return None, None, None
    dated.sort(key=lambda p: p[0], reverse=True)
    freshest_dt, freshest = dated[0]

    chosen_dt, chosen = freshest_dt, freshest
    if answer:
        aw = _tokens(answer)
        if aw:
            scored = []
            for dt, a in dated:
                at = _tokens((a.get("title") or "") + " " + (a.get("description") or ""))
                scored.append((len(aw & at), dt, a))
            scored.sort(key=lambda s: (-s[0], -s[1].timestamp()))
            if scored and scored[0][0] > 0:
                chosen_dt, chosen = scored[0][1], scored[0][2]
    return _iso_z(chosen_dt), chosen.get("article_url"), _iso_z(freshest_dt)


def infer_cat(text):
    if not text:
        return "other"
    t = text.lower()
    for cat, pat in CAT_PATTERNS:
        if re.search(pat, t):
            return cat
    return "other"


def pm_notional(pr):
    """The DOLLAR behind a pre-market print: shares x price.

    The tape is a tape of MOVERS, and a mover is measured in money, not in percent.
    The share floor keeps a QUOTE out; this number is what tells a consumer which of
    the survivors was real. Measured on the 2026-11-13 tape: of the board's 15 rows,
    10 sat on under $3M of pre-market notional and only 5 on $5M or more - so the
    board's top was, that day, a thin-money board.
    """
    try:
        return round(float(pr.get("volume") or 0) * float(pr.get("price") or 0), 2)
    except Exception:
        return None


def sign_score(text):
    """The direction-word score of a catalyst text: (positive hits, negative hits).

    POSITIVE = a cause that should push the stock UP (a beat, an approval, a raise).
    NEGATIVE = a cause that should push it DOWN (a miss, a cut, a resignation).

    Only the text BEFORE the hedge clause is read - see SIGN_HEDGE.
    """
    t = str(text or "").lower()
    m = SIGN_HEDGE.search(t)
    if m:
        t = t[:m.start()]
    pos = sum(1 for w in SIGN_POS if re.search(r"\b" + re.escape(w), t))
    neg = sum(1 for w in SIGN_NEG if re.search(r"\b" + re.escape(w), t))
    return pos, neg


def sentiment_conflict(sentiment, pct):
    """True when the provider's OWN sentiment for the ticker contradicts the move.

    The provider's `sentiment` is EXACT for that ticker - it is the provider's own
    judgement of the story - where the direction-word probe over the prose is a
    guess. So a row that carries a sentiment is judged by it, and the word probe is
    the fallback for a router or a chatter catalyst that carries none.

    None when there is no usable opinion (no sentiment, or no move to compare).
    """
    s = str(sentiment or "").lower()
    if s not in ("positive", "negative"):
        return None
    if pct is None:
        return None
    try:
        p = float(pct)
    except Exception:
        return None
    if p == 0:
        return None
    return (s == "positive") != (p > 0)


def sign_conflict(text, pct):
    """True when the catalyst's direction contradicts the move's direction.

    None when there is nothing to compare (no number, or no text).

    TWO GUARDS, both earned on real data:
      * a MARGIN is required. A catalyst can carry both directions - "sold off
        despite a strong Q3 beat" - and a score of zero or one is no evidence of a
        contradiction;
      * a MATERIAL move is required. A row that did not move (|%| below the
        band's own width) has no direction to contradict.

    Measured against every catalyst on the 2026-11-12 and 2026-11-13 tapes, this
    flags exactly the rows whose published cause does not explain the move
    (DGII -20.50% on "beat Q4 earnings expectations"; ONDS -5.41% on "stronger
    revenue outlook") and nothing else - it stays silent on LUNR +17.82%, whose
    negative words all belong to the hedge clause, and on AMD +3.01% and
    AVGO +3.28%, whose negative words are about a DIFFERENT company.
    """
    if pct is None or not text:
        return None
    try:
        p = float(pct)
    except Exception:
        return None
    if abs(p) < BAND_PCT:
        return None
    pos, neg = sign_score(text)
    score = pos - neg
    if abs(score) < SIGN_MARGIN:
        return False
    return (score > 0) != (p > 0)


def article_catalyst(ticker, cutoff, limit=8, name=None):
    """The provider's TICKER-SCOPED insight for this company, as a dated catalyst.

    Every article carries `insights`: a per-ticker entry with a `sentiment` and a
    one-clause `sentiment_reasoning`. THAT entry is the catalyst - not the headline.

    WHY THE INSIGHT AND NOT THE HEADLINE. Measured 2026-11-13 23:14 ET: the newest
    headline for SST (System1, -38.92%) was "NIQ Global Intelligence plc (NIQ) Q3
    Earnings and Revenues Surpass Estimates" - a story about a DIFFERENT company,
    and a POSITIVE one, on a row that fell 39%. The provider tags that article to
    both tickers, so the article's `tickers` list does NOT exclude it. But the
    article's `insights` carry a SEPARATE entry per ticker, and the SST entry
    reads "Expected to post a quarterly loss of $1.30 per share with a 43.5%
    year-over-year deterioration, and revenues projected to decline 50.7% from the
    year-ago quarter" - at `sentiment: negative`, which is the direction of the
    move. The insight is the ticker-scoped, direction-scoped explanation; the
    headline is neither.

    So the catalyst is the insight for the REQUESTED ticker (matched EXACTLY, so a
    "SST.WS" warrant entry cannot pass for "SST"), and the direction comes from the
    provider's own `sentiment` - which is exact, where a direction-word probe over
    the prose is a guess.
    """
    articles, ferr = fetch_articles(ticker, limit=limit)
    want = (ticker or "").upper()
    dated = []
    for a in articles:
        dt = _parse_iso(a.get("published_utc"))
        if dt is None:
            continue
        if cutoff is not None and dt > cutoff:
            continue
        ins = None
        for i in (a.get("insights") or []):
            if str(i.get("ticker") or "").upper() == want:
                ins = i
                break
        if ins is None:
            # No insight scoped to THIS ticker: the article is about other companies
            # (the provider tags multi-company articles to every ticker in them), so
            # it is not this company's cause.
            continue
        dated.append((dt, a, ins))
    if not dated:
        return {"title": None, "date": None, "url": None, "freshest": None,
                "articles": [], "in_window": False, "error": ferr,
                "sentiment": None}
    dated.sort(key=lambda p: p[0], reverse=True)
    dt, a, ins = dated[0]
    age = (cutoff.date() - dt.date()).days if cutoff is not None else 0
    why = (ins.get("sentiment_reasoning") or "").strip() or (a.get("title") or "").strip()
    return {"title": why or None,
            "date": _iso_z(dt), "url": a.get("article_url"), "freshest": _iso_z(dt),
            "articles": [(d, art) for d, art, _ in dated],
            "in_window": age <= CATALYST_MAX_AGE_DAYS,
            "error": ferr, "sentiment": ins.get("sentiment")}


def resolve_catalysts(pool, cutoff, budget, names=None, pcts=None):
    """The catalyst pipeline: the ARTICLE FEED FIRST, then the router. Both parallel.

    Returns {ticker: result}, where a result carries the catalyst and its proof:
      why     - the catalyst text
      date    - the article's publication stamp, or None
      url     - the article, so the claim can be checked
      conf    - the confidence token this cause earns (see the rules below)
      src     - the row's provenance after the catalyst is applied
      tool    - which provider produced it
      origin  - "article" | "router" | "stale" | "none"
      ref     - the router's evidence string, when the router produced it

    THE ORDER IS THE POINT. The feed is 60-100x cheaper than the router and it
    answers with a date and a URL, so it goes first and the router's 15-25s is
    spent only on a name the feed could not date - a press release the feed
    missed. Measured 2026-11-13: 8 sequential grounded calls cost 264s and 8 of the
    16 calls on the live tape REFUSED; 8 concurrent calls cost 20.2s.

    THE CONFIDENCE RULES, in one place:
      * an article catalyst is dated, in-window, checkable AND its direction agrees
        with the move -> "high"; if the direction cannot be confirmed -> "medium";
        and a CONTRADICTED one is demoted to "low" and flagged (see sign_conflict);
      * a router catalyst keeps the router's own confidence, but only while it is
        DATED and in-window - an undated cause is "low", and a stale one is
        DROPPED (the cause goes, the price stays);
      * a retail-chatter cause is "low" - it has no date and no URL, so it cannot
        be a verified cause however loudly it is phrased.
    """
    names = names or {}
    pcts = pcts or {}
    pool = [t for t in pool if t]
    if not pool:
        return {}
    # PHASE A - the article feed, for every name in the pool. Cheap, and it dates.
    with _cf.ThreadPoolExecutor(max_workers=CATALYST_WORKERS) as ex:
        art = dict(zip(pool, ex.map(lambda t: article_catalyst(t, cutoff), pool)))
    # PHASE B - the router, only for the names the feed could not date, and never
    # more than the budget.
    need = [t for t in pool if not (art.get(t) or {}).get("in_window")][:budget]
    with _cf.ThreadPoolExecutor(max_workers=CATALYST_WORKERS) as ex:
        gnd = dict(zip(need, ex.map(lambda t: call_grounded(t, names.get(t)), need)))

    out = {}
    for t in pool:
        a = art.get(t) or {}
        if a.get("in_window") and a.get("title"):
            # The headline is the provider's OWN record of what happened: dated,
            # checkable, and its direction is measurable. It earns "high" when it
            # agrees with the move and the move is material; "medium" when the
            # direction cannot be confirmed. A headline that points the OTHER way
            # is demoted and flagged by sign_conflict().
            pct = pcts.get(t)
            agree = sentiment_conflict(a.get("sentiment"), pct)
            try:
                material = pct is not None and abs(float(pct)) >= BAND_PCT
            except Exception:
                material = False
            if agree is True:
                # The provider's own sentiment for this ticker contradicts the move.
                conf = "low"
            elif agree is False and material:
                conf = "high"
            else:
                conf = "medium"
            out[t] = {"why": a["title"], "date": a["date"], "url": a.get("url"),
                      "conf": conf, "src": "pipeworx", "tool": "polygon_io_news",
                      "origin": "article", "ref": a.get("url"), "error": a.get("error"),
                      "sentiment": a.get("sentiment")}
            continue
        g = gnd.get(t) or {}
        if not (g.get("answer") and not g.get("refusal")):
            out[t] = {"why": None, "date": None, "url": None, "conf": "low",
                      "src": "scanner", "tool": None, "origin": "none", "ref": None,
                      "error": a.get("error")}
            continue
        nd, nurl, freshest = resolve_news_date(t, g["answer"], cutoff, a.get("articles"))
        conf = "high" if (g.get("confidence") or 0) >= 0.7 else "medium"
        fresh = _parse_iso(freshest)
        if fresh is None:
            # No dated evidence for this company at all. Keep the cause, but stop
            # claiming to know when it broke and stop calling it high confidence:
            # an undated cause is a weaker claim, not a false one.
            nd = nurl = None
            conf = "low"
        elif (cutoff.date() - fresh.date()).days > CATALYST_MAX_AGE_DAYS:
            # STALE. The newest thing the provider holds for this company is older
            # than the window, so this answer cannot be describing today's move
            # however confident it sounds. Drop the cause, keep the price.
            out[t] = {"why": None, "date": None, "url": None, "conf": "low",
                      "src": "scanner", "tool": None, "origin": "stale", "ref": None,
                      "error": a.get("error")}
            continue
        else:
            # The gate above proved the provider HOLDS something newer than the
            # window for this company. It did NOT prove that the article this answer
            # matched IS that newer thing: the match is textual, so it can land on a
            # months-old article from the same company. Publishing that stamp as
            # "when it broke" is the ARWR defect in a new costume - measured
            # 2026-11-11 08:30 ET, NOVT carried a catalyst dated 2026-02-22 (262 days
            # old) while the provider held a fresh article for Novanta. A date we
            # cannot vouch for is not a date: keep the cause, drop the stamp, demote.
            nd_dt = _parse_iso(nd) if nd else None
            if nd_dt is not None and (cutoff.date() - nd_dt.date()).days > CATALYST_MAX_AGE_DAYS:
                nd = nurl = None
                conf = "low"
        out[t] = {"why": g["answer"], "date": nd, "url": nurl, "conf": conf,
                  "src": "pipeworx", "tool": g.get("tool_used"), "origin": "router",
                  "ref": g.get("evidence"), "error": a.get("error")}
    return out


def build(date_str, checkpoint, top_n=8):
    tr = call_trending()
    tm = call_top_movers()
    tm_dn = call_top_movers(category="losers")
    # THE BAND: today's actual pre-market movers, in two disjoint halves.
    band = call_scanner_band()
    band_error = band.get("error")
    if "error" in tr and "error" in tm and band_error:
        return {"error": f"every source failed: trending={tr.get('error')} "
                         f"movers={tm.get('error')} band={band_error}"}
    trending = {r["ticker"]: r for r in (tr.get("rows") or [])}
    movers = tm.get("movers") or {}
    band_rows = band.get("rows") or {}
    # The decliners are the DISJOINT other half of the same movers scan (a name cannot be
    # both a top gainer and a top loser), so merging the two halves can never put two
    # prices on one record. Measured 2026-11-09: the gainers-only default missed IRTC
    # -30.7%, DKNG -21.3% and AXON -18.2% -- the biggest pre-open decliners of the day.
    for _tk, _m in (tm_dn.get("movers") or {}).items():
        movers.setdefault(_tk, _m)

    # Names the tape should carry: trending names that also moved, plus the top movers.
    def liquid(m):
        if not m:
            return False
        px = m.get("price")
        dv = (px or 0) * (m.get("volume") or 0)
        return (px or 0) >= MIN_PRICE and dv >= MIN_DOLLAR_VOL

    def pm_shares(r):
        """The size of the pre-market print, in shares. A print of fewer than
        MIN_PM_SHARES shares is a QUOTE, not a market, and the tape does not carry it."""
        try:
            return float(r.get("volume") or 0)
        except (TypeError, ValueError):
            return 0.0

    candidates = []
    seen = set()
    # 1. THE BAND FIRST. It is today's tape: the names the brief publishes are the names
    # the tape carries. Ranked by the ABSOLUTE move, not by change_pct: the grounded-call
    # budget is finite and must reach the biggest movers in BOTH directions. Ranking by
    # change_pct puts every decliner behind every gainer, so the worst pre-open loser
    # never gets a catalyst.
    for tk, r in sorted(band_rows.items(), key=lambda kv: -abs(kv[1].get("pct") or 0)):
        if tk in seen:
            continue
        seen.add(tk)
        candidates.append(tk)
    # 2. The retail chatter signal, for the names that are being watched before they gap.
    for tk in trending:
        if tk not in seen:
            seen.add(tk)
            candidates.append(tk)
    # 3. The movers scan's liquid names - YESTERDAY's movers, which the band cannot see
    #    because they have not moved today yet. They keep the old floor (price and dollar
    #    volume of the last completed session), because their pre-market print is what
    #    the band and the scanner decide, not the movers data.
    for tk, m in sorted(movers.items(), key=lambda kv: -abs(kv[1].get("change_pct") or 0)):
        if tk in seen or not liquid(m):
            continue
        seen.add(tk)
        candidates.append(tk)

    # THE PRE-MARKET PRINT. The movers scan (calls 2 and 3) ranks by the last COMPLETED
    # session's move, so before the open it names YESTERDAY's movers and carries
    # YESTERDAY's closes. The tape is about the session that is about to open, so the
    # numbers come from the scanner's `premarket_*` columns for THIS session.
    #
    # The band rows are ALREADY priced - they come from the same pull that chose them -
    # so only the names the band did not cover are asked for. One call for that
    # remainder. A name the scanner does not carry has NO pre-market print, and the tape
    # must not invent one: it keeps a NULL number and is published as a narrative row,
    # exactly like a trending-only name.
    leftovers = [tk for tk in candidates if tk not in band_rows]
    pm = call_scanner_premarket(leftovers)
    pm_rows = dict(band_rows)
    pm_rows.update(pm.get("rows") or {})
    pm_error = pm.get("error")
    priced_candidates = sum(1 for tk in candidates if tk in pm_rows)

    # Re-order the candidates by THIS session's absolute pre-market move. The
    # grounded-call budget is finite and is spent in this order, so the order must follow
    # the session the tape is about: ranked by the movers scan's move (the last COMPLETED
    # session's), the budget would go to the previous session's biggest movers and
    # today's would never get a catalyst. Names with no pre-market print keep their place
    # after every priced name - they are narrative rows, and a narrative row does not
    # compete for a grounded call.
    if pm_rows:
        candidates.sort(key=lambda tk: (-abs((pm_rows.get(tk) or {}).get("pct") or 0), tk))

    # THE CATALYST POOL - the names in contention for a dated cause, biggest mover
    # first. The pool is the CHEAP pass (one article fetch each), so it is wider
    # than the router budget; the router budget stays `top_n` and is spent only on
    # pool names the feed could not date.
    run_dt = datetime.datetime.now(_et())
    pool_n = max(CATALYST_POOL_MULT * top_n, top_n)
    pool = [tk for tk in candidates if tk in pm_rows][:pool_n]
    pool_names = {}
    for tk in pool:
        pool_names[tk] = ((pm_rows.get(tk) or {}).get("name")
                          or (movers.get(tk) or {}).get("name")
                          or (trending.get(tk) or {}).get("name"))
    pool_pcts = {tk: (pm_rows.get(tk) or {}).get("pct") for tk in pool}
    cats = resolve_catalysts(pool, run_dt, top_n, pool_names, pool_pcts)

    rows = []
    stale_dropped = []          # names whose catalyst was rejected as too old
    thin_dropped = []           # names whose pre-market print was a quote, not a market
    empty_dropped = []          # names that carried neither a number nor a cause
    for tk in candidates:
        mv = movers.get(tk)
        trr = trending.get(tk)
        # A band name is on the tape because it MOVED TODAY, even when the movers scan
        # has never heard of it and no one is tweeting about it.
        if not mv and not trr and tk not in band_rows:
            continue
        # THE QUOTE FLOOR. A pre-market print of fewer than MIN_PM_SHARES shares is one
        # seller, not a market, and the tape is a tape of MOVERS. The name is dropped
        # rather than published with a number that means nothing.
        if tk in pm_rows and pm_shares(pm_rows[tk]) < MIN_PM_SHARES:
            thin_dropped.append(tk)
            continue
        # ONE capture instant per row: it stamps the row AND bounds the article
        # search, so a catalyst can never post-date the record that carries it.
        row_dt = datetime.datetime.now(_et())
        # THIS session's pre-market print. `pm` is the only source of a pre-market
        # number, so a row without one carries NO number - it is a narrative row, never a
        # mover carrying yesterday's close.
        pr = pm_rows.get(tk)
        if pr:
            rec = {
                "ts": row_dt.isoformat(timespec="seconds"),
                "src": "scanner",
                "ticker": tk,
                "name": pr.get("name") or (mv or {}).get("name") or (trr or {}).get("name"),
                "pct": pr.get("pct"),
                "price": pr.get("price"),
                "cat": infer_cat((trr or {}).get("why")),
                "why": (trr or {}).get("why"),
                "ref": None,
                # A RETAIL NARRATIVE IS NOT A VERIFIED CAUSE. The chatter summary has
                # no publication stamp and no article behind it, so it can never earn
                # more than "low" however loudly it is phrased. Measured on the
                # 2026-11-12 tape: 10 of the 12 "high" rows were exactly this - a
                # stocktwits reason, undated and uncheckable.
                "conf": "low",
                "trending_ts": (trr or {}).get("ts"),
                "trending_score": (trr or {}).get("score"),
                "volume": pr.get("volume"),
                "exchange": pr.get("exchange"),
                # The DOLLAR behind the print, and the sign probe's verdict.
                "pm_notional": pm_notional(pr),
                "sign_conflict": False,
                # The provider's own sentiment for this ticker, when it has one.
                "sentiment": None,
                # WHEN the catalyst broke, and the article it came from. Both are null
                # until a grounded catalyst is dated; see resolve_news_date().
                "news_date": None,
                "news_url": None,
            }
        else:
            # NO pre-market print for this name. It did not trade before the open, so
            # there is no number to publish. The row keeps its narrative (if any) and
            # carries no number at all - never the previous session's close.
            rec = {
                "ts": row_dt.isoformat(timespec="seconds"),
                "src": "stocktwits",
                "ticker": tk,
                "name": (mv or {}).get("name") or (trr or {}).get("name"),
                "pct": None,
                "price": None,
                "cat": infer_cat((trr or {}).get("why")),
                "why": (trr or {}).get("why"),
                "ref": None,
                "conf": "low",
                "trending_ts": (trr or {}).get("ts"),
                "trending_score": (trr or {}).get("score"),
                "volume": None,
                "exchange": (mv or {}).get("exchange"),
                "pm_notional": None,
                "sign_conflict": False,
                "sentiment": None,
                "news_date": None,
                "news_url": None,
            }
        # THE CATALYST. The pool's results are already computed (the article feed
        # first, then the router, both in parallel), so applying one is a lookup -
        # not a 15-25s call in the middle of the row loop. A grounded catalyst is
        # only worth a call for a row that HAS a number: the catalyst explains a
        # MOVE, and a row with no pre-market print has no move to explain.
        cat = cats.get(tk)
        if cat and cat.get("origin") == "stale":
            # The provider's newest article for this company is older than the
            # window, so the cause cannot be today's news. It goes; the price stays.
            stale_dropped.append(tk)
        if cat and cat.get("why"):
            rec["why"] = cat["why"]
            rec["cat"] = infer_cat(cat["why"])
            rec["ref"] = cat.get("ref")
            rec["conf"] = cat.get("conf") or "low"
            rec["src"] = cat.get("src") or "scanner"
            rec["grounded_tool"] = cat.get("tool")
            rec["news_date"] = cat.get("date")
            rec["news_url"] = cat.get("url")
            rec["sentiment"] = cat.get("sentiment")
        # THE SIGN PROBE. A cause that points the OTHER way is not an explanation of
        # this move, so it can never be published as a confident one. Measured on the
        # 2026-11-12 tape: DGII (-20.50%) carried "beat Q4 2026 earnings expectations"
        # at `conf: high` WITH a date - the price was right (the regular session closed
        # -11.72%), the cause was not.
        _conflict = (sentiment_conflict(rec["sentiment"], rec["pct"])
                     if rec.get("sentiment") else sign_conflict(rec["why"], rec["pct"]))
        if _conflict:
            rec["conf"] = "low"
            rec["sign_conflict"] = True
        # A ROW WITH NEITHER A NUMBER NOR A CAUSE IS NOT A ROW. It says nothing a
        # reader can use, and every consumer pays to carry it. Measured on the
        # 2026-11-12 tape: 11 of its 45 rows were exactly this.
        if rec["pct"] is None and not rec["why"]:
            empty_dropped.append(tk)
            continue
        rows.append(rec)
    return {"rows": rows, "as_of": tm.get("as_of"),
            "trending_count": len(trending), "mover_count": len(movers),
            "gainers": len(tm.get("movers") or {}), "losers": len(tm_dn.get("movers") or {}),
            # THE BAND: how many names today's pre-market tape held, and how many of
            # them the quote floor removed.
            "band_up": band.get("up"), "band_down": band.get("down"),
            "band_total": band.get("total"),
            "band_truncated": band.get("truncated") or [],
            "band_error": band_error,
            "thin_dropped": thin_dropped,
            # How many rows carry THIS session's pre-market print, and how many are
            # narrative-only because the name did not trade pre-market. These count the
            # rows the tape ACTUALLY carries: a name whose print was too thin to keep is
            # not a priced row, and saying otherwise would overstate the tape.
            "premarket_priced": sum(1 for r in rows if r.get("src") in ("scanner", "pipeworx")),
            "premarket_unprinted": sum(1 for r in rows if r.get("src") == "stocktwits"),
            "premarket_candidates_priced": priced_candidates,
            "premarket_error": pm_error,
            "stale_dropped": stale_dropped,
            "thin_dropped": thin_dropped,
            "empty_dropped": empty_dropped,
            # THE CATALYST PIPELINE's own ledger, so the run reports what it spent.
            "catalyst_pool": len(pool),
            "article_errors": sum(1 for c in cats.values() if c.get("error")),
            # A CREDIT FAILURE MUST APPEAR IN THE RUN'S ERRORS. The provider answers
            # an exhausted account with an error, and a caller that treats it as an
            # empty result publishes a tape with no catalysts and reports no error.
            "provider_errors": sorted({c.get("error") for c in cats.values()
                                        if c.get("error")}),
            "catalyst_dated": sum(1 for r in rows if r.get("news_date")),
            "catalyst_article": sum(1 for c in cats.values() if c.get("origin") == "article"),
            "catalyst_router": sum(1 for c in cats.values() if c.get("origin") == "router"),
            "sign_conflicts": sum(1 for r in rows if r.get("sign_conflict")),
            "errors": [e for e in (tr.get("error"), tm.get("error"), tm_dn.get("error"),
                                   band_error, pm_error) if e]
                      + sorted({c.get("error") for c in cats.values() if c.get("error")})}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--checkpoint")
    ap.add_argument("--out")
    ap.add_argument("--top", type=int, default=12)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    now = datetime.datetime.now(_et())
    date_str = args.date or now.strftime("%Y-%m-%d")
    cp, slot_note = resolve_slot(args.checkpoint or now.strftime("%H%M"))
    if cp is None:
        # Fail closed with a MARKER, never with a phantom filename. The marker must NEVER
        # wear the tape's .jsonl name: cron #17 would parse it as tape and call every
        # line malformed.
        tape0 = args.out or f"/workspace/preopen-feed/{date_str}-{args.checkpoint}.jsonl"
        out0 = (tape0[:-6] if tape0.endswith(".jsonl") else tape0) + ".DEVIATION.slot.md"
        os.makedirs(os.path.dirname(out0), exist_ok=True)
        with open(out0, "w", encoding="utf-8") as fh:
            fh.write("# Pre-open catalyst capture — SLOT DEVIATION\n\n"
                     f"- **Reason:** {slot_note}\n"
                     f"- **Requested checkpoint:** {args.checkpoint}\n"
                     f"- **Tape:** none. No tape was written, because cron #17 merges the "
                     f"checkpoints by slot name and would never read an invented one.\n")
        print(f"preopen capture: SLOT DEVIATION — {slot_note} (marker: {out0})")
        return 0
    if slot_note:
        print(f"preopen capture: {slot_note}")

    if not os.environ.get("PIPEWORX_API_KEY") and not os.environ.get("XAI_API_KEY"):
        print("preopen capture: PIPEWORX_API_KEY unset — nothing written")
        return 0

    res = build(date_str, cp, args.top)
    if "error" in res:
        print(json.dumps(res))
        return 1

    lines = [json.dumps(r, ensure_ascii=False) for r in res["rows"]]
    body = "\n".join(lines) + ("\n" if lines else "")

    if args.dry_run:
        print(f"# dry run — {len(res['rows'])} rows, band={res.get('band_total')}, "
              f"movers={res['mover_count']}, "
              f"trending={res['trending_count']}, as_of={res.get('as_of')}, "
              f"premarket_priced={res.get('premarket_priced')}, "
              f"premarket_unprinted={res.get('premarket_unprinted')}")
        print(body)
        return 0

    out = args.out or f"/workspace/preopen-feed/{date_str}-{cp}.jsonl"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    # ATOMIC, never append. A slot's tape holds ONE snapshot. Appending meant that two
    # agents running the same slot against the same shared /workspace produced a tape
    # with one row per ticker PER RUN -- 100 rows for 53 tickers, measured 2026-11-09
    # 08:30 ET -- which breaks the fleet's "one row per ticker" rule and makes cron #17
    # read a stale record as the latest one.
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(body)
    os.replace(tmp, out)
    # The three numbers here are DIFFERENT things and must not be written as an
    # equation: `gainers`/`losers` are how many names each half of the scan
    # returned, and `mover_count` is how many distinct names they added up to.
    # Printed as "movers=20 = 20 up / 10 down" it reads as an arithmetic claim that
    # is simply false.
    print(f"preopen capture: wrote {len(res['rows'])} records to {out} "
          f"(pre-market band: {res.get('band_up')} up + {res.get('band_down')} down, "
          f"{res.get('band_total')} names, "
          f"quote-floor drops={len(res.get('thin_dropped') or [])}, "
          f"movers scan: {res.get('gainers')} up + {res.get('losers')} down, "
          f"{res['mover_count']} names, "
          f"trending={res['trending_count']}, "
          f"premarket_priced={res.get('premarket_priced')}, "
          f"premarket_unprinted={res.get('premarket_unprinted')}, "
          f"as_of={res.get('as_of')}, stale_dropped={len(res.get('stale_dropped') or [])}, "
          f"catalysts: dated={res.get('catalyst_dated')} "
          f"(article={res.get('catalyst_article')}, router={res.get('catalyst_router')}), "
          f"pool={res.get('catalyst_pool')}, article_errors={res.get('article_errors')}, "
          f"sign_conflicts={res.get('sign_conflicts')}, "
          f"empty_dropped={len(res.get('empty_dropped') or [])}, "
          f"provider_errors={len(res.get('provider_errors') or [])}, "
          f"errors={len(res.get('errors') or [])})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
