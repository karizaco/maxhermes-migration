#!/usr/bin/env python3
"""
CAPTURE_SCRIPT_VERSION: 2026-11-11.1
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
  4. ask_pipeworx_grounded (market-recap pack) -> a per-name catalyst with evidence
      and a confidence score, for the movers that call 1 did not cover.
  5. polygon_io_news      (polygon-io pack)   -> the DATE the catalyst broke, and the
      article it came from. Call 4 answers "what happened" but it does not say WHEN:
      measured 2026-11-09, it returned ARWR's January 6, 2026 obesity press release
      for a name that fell 16.6% that morning, and stamped it `conf: high`.

The grounded-call budget is spent on the biggest movers by |%|, in BOTH directions:
ranking by change_pct instead would put every decliner behind every gainer and the
worst pre-open loser would never get a catalyst.

**Prices always come from calls 2 and 3.** Calls 1, 4 and 5 explain; they never price.
A percentage that disagrees with the movers scan by more than 2pp is marked
`unverified`.

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
import datetime
import json
import os
import re
import sys
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
        return {"error": "rpc_failed", "raw": raw[:200]}
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
    out = rpc(PACK_POLYGON, "polygon_io_news",
              {"ticker": ticker, "limit": limit},
              prefer=["results"])
    if "error" in out:
        return []
    res = out.get("results")
    return res if isinstance(res, list) else []


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


def resolve_news_date(ticker, answer, cutoff):
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
    """
    articles = call_polygon_news(ticker)
    dated = []
    for a in articles:
        dt = _parse_iso(a.get("published_utc"))
        if dt is None:
            continue
        if cutoff is not None and dt > cutoff:
            continue
        dated.append((dt, a))
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


def build(date_str, checkpoint, top_n=8):
    tr = call_trending()
    tm = call_top_movers()
    tm_dn = call_top_movers(category="losers")
    if "error" in tr and "error" in tm:
        return {"error": f"both sources failed: trending={tr.get('error')} movers={tm.get('error')}"}
    trending = {r["ticker"]: r for r in (tr.get("rows") or [])}
    movers = tm.get("movers") or {}
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

    candidates = []
    seen = set()
    # Rank by the ABSOLUTE move, not by change_pct: the grounded-call budget is finite and
    # must reach the biggest movers in BOTH directions. Ranking by change_pct puts every
    # decliner behind every gainer, so the worst pre-open loser never gets a catalyst.
    for tk, m in sorted(movers.items(), key=lambda kv: -abs(kv[1].get("change_pct") or 0)):
        if tk in seen or not liquid(m):
            continue
        seen.add(tk)
        candidates.append(tk)
    for tk in trending:
        if tk not in seen:
            seen.add(tk)
            candidates.append(tk)

    # THE PRE-MARKET PRINT. The movers scan (calls 2 and 3) ranks by the last COMPLETED
    # session's move, so before the open it names YESTERDAY's movers and carries
    # YESTERDAY's closes. The tape is about the session that is about to open, so the
    # numbers come from the scanner's `premarket_*` columns for THIS session.
    #
    # One call for the whole candidate set. A name the scanner does not carry has NO
    # pre-market print, and the tape must not invent one: it keeps a NULL number and is
    # published as a narrative row, exactly like a trending-only name.
    pm = call_scanner_premarket(candidates)
    pm_rows = pm.get("rows") or {}
    pm_error = pm.get("error")
    priced_now = sum(1 for tk in candidates if tk in pm_rows)

    # Re-order the candidates by THIS session's absolute pre-market move. The
    # grounded-call budget is finite and is spent in this order, so the order must follow
    # the session the tape is about: ranked by the movers scan's move (the last COMPLETED
    # session's), the budget would go to the previous session's biggest movers and
    # today's would never get a catalyst. Names with no pre-market print keep their place
    # after every priced name - they are narrative rows, and a narrative row does not
    # compete for a grounded call.
    if pm_rows:
        candidates.sort(key=lambda tk: (-abs((pm_rows.get(tk) or {}).get("pct") or 0), tk))

    rows = []
    stale_dropped = []          # names whose catalyst was rejected as too old
    grounded_budget = top_n
    for tk in candidates:
        mv = movers.get(tk)
        trr = trending.get(tk)
        if not mv and not trr:
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
                "conf": "high" if trr and trr.get("why") else "low",
                "trending_ts": (trr or {}).get("ts"),
                "trending_score": (trr or {}).get("score"),
                "volume": pr.get("volume"),
                "exchange": pr.get("exchange"),
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
                "news_date": None,
                "news_url": None,
            }
        # A mover with no trending reason: ask the grounded router for one, then DATE
        # it. The router is good at "what happened" and blind to "when" - so every
        # answer it gives is age-checked against the provider's own stamps before it
        # is allowed onto the tape.
        # A grounded catalyst is only worth a call for a row that HAS a number: the
        # catalyst explains a MOVE, and a row with no pre-market print has no move to
        # explain. It also keeps `src` honest - a pipeworx row carries a price.
        if pr and not rec["why"] and grounded_budget > 0:
            grounded_budget -= 1
            g = call_grounded(tk, rec["name"])
            if g.get("answer") and not g.get("refusal"):
                rec["why"] = g["answer"]
                rec["cat"] = infer_cat(g["answer"])
                rec["ref"] = g.get("evidence")
                rec["conf"] = "high" if (g.get("confidence") or 0) >= 0.7 else "medium"
                rec["src"] = "pipeworx"
                rec["grounded_tool"] = g.get("tool_used")
                nd, nurl, freshest = resolve_news_date(tk, rec["why"], row_dt)
                if freshest is None:
                    # No dated evidence for this company at all. Keep the cause, but
                    # stop claiming to know when it broke and stop calling it high
                    # confidence: an undated cause is a weaker claim, not a false one.
                    rec["news_date"] = None
                    rec["news_url"] = None
                    rec["conf"] = "low"
                elif (row_dt.date() - _parse_iso(freshest).date()).days > CATALYST_MAX_AGE_DAYS:
                    # STALE. The newest thing the provider holds for this company is
                    # older than the window, so this answer cannot be describing
                    # today's move however confident it sounds. Drop the cause and
                    # keep the price - the honest row is a price with no catalyst.
                    rec["why"] = None
                    rec["ref"] = None
                    rec["cat"] = "other"
                    rec["conf"] = "low"
                    # The row keeps its price and loses only the cause. It was priced
                    # from the scanner, so "scanner" is still its true provenance.
                    rec["src"] = "scanner"
                    rec["grounded_tool"] = None
                    rec["news_date"] = None
                    rec["news_url"] = None
                    stale_dropped.append(tk)
                else:
                    rec["news_date"] = nd
                    rec["news_url"] = nurl
        rows.append(rec)
    return {"rows": rows, "as_of": tm.get("as_of"),
            "trending_count": len(trending), "mover_count": len(movers),
            "gainers": len(tm.get("movers") or {}), "losers": len(tm_dn.get("movers") or {}),
            # How many rows carry THIS session's pre-market print, and how many are
            # narrative-only because the name did not trade pre-market.
            "premarket_priced": priced_now,
            "premarket_unprinted": len(candidates) - priced_now,
            "premarket_error": pm_error,
            "stale_dropped": stale_dropped,
            "errors": [e for e in (tr.get("error"), tm.get("error"), tm_dn.get("error"),
                                   pm_error) if e]}


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
        print(f"# dry run — {len(res['rows'])} rows, movers={res['mover_count']}, "
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
          f"(movers scan: {res.get('gainers')} up + {res.get('losers')} down, "
          f"{res['mover_count']} names, "
          f"trending={res['trending_count']}, "
          f"premarket_priced={res.get('premarket_priced')}, "
          f"premarket_unprinted={res.get('premarket_unprinted')}, "
          f"as_of={res.get('as_of')}, stale_dropped={len(res.get('stale_dropped') or [])}, "
          f"errors={len(res.get('errors') or [])})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
