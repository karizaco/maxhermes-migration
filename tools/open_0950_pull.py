#!/usr/bin/env python3
"""
open_0950_pull.py — cron #17 `us-stocks-in-play`, OPEN slot: the 09:50 ET pull.

CAPABILITY MARKER: OPEN_0950_PULL_V1

WHY THIS EXISTS
---------------
The 2026-11-10 open fire took 46m52s and burned ~20 minutes of it on two
DISCARDED pulls and one WRONG pull. Every defect below was measured, and each
one is SILENT — the script never crashed, it published plausible numbers:

1. ``chartPreviousClose`` in a MULTI-DAY range is the close BEFORE the range
   starts, not the prior session. With ``range=10d`` the reference price was
   ~10 sessions old, so every move was a TEN-DAY move: NVDA read -21.50%
   instead of -4.10%, QQQ -6.55% instead of ~-0.26%, and the whole board
   looked like a crash while the index was -0.30%. **FIX: the prior close is
   the last non-null close of the PRIOR SESSION's bars, from the same
   response. ``chartPreviousClose`` is used ONLY for ``range=1d``.**
2. Some 5-minute bars carry a NULL close. A picker that takes the 09:45 bar's
   close drops those names SILENTLY — 1,276 of 7,857 in one pull. **FIX: the
   price is the last NON-NULL close at or before the cut** (and the bar's
   VOLUME still counts — a null close does not make its volume vanish).
3. The COOKIE'd chart session is throttled by the egress edge; the COOKIE-LESS
   one is not. The throttled body is ``Edge: Too Many Requests`` — the
   ``Edge:`` prefix defeats a ``startswith("Too Many")`` check, so it surfaced
   as a JSON parse error and the pull kept hammering a throttled endpoint with
   no backoff. **FIX: no cookie, no crumb, and ``Edge:``/429 is classified as
   THROTTLE (pause, back off, resume) — never as a parse error.**
4. The pull wrote its output file ONLY on completion, so killing it destroyed
   ~3,945 completed fetches (~7 minutes) with nothing on disk to resume from.
   **FIX: one JSONL line per symbol as it lands; a retry resumes.**
5. The venue-prefixed TradingView symbol (``NASDAQ:NVDA``) 404s on Yahoo.
   **FIX: the bare ticker, with ``/`` mapped to ``-``.**
6. The pull was REQUEST-bound, not source-bound: one ``curl`` process per
   symbol ran at 12.4 req/s, while a keep-alive connection per worker ran the
   SAME requests at 62-101 req/s on the same cold symbols (measured
   2026-11-13: 40 live symbols in 0.6s with 8 workers; 240 cold symbols at
   101.3 req/s vs 12.4 req/s). **FIX: one keep-alive connection per worker.**

WHAT THIS ENGINE PUBLISHES
--------------------------
* the universe (three unpaginated scanner calls), the pre-filter union and the
  pull set;
* the 09:50 ET state per symbol: price, gap, session volume to 09:50, the
  prior close, the 20-minute gap verdict and ``pace``;
* BOTH pace bases (see PACE) so the basis can be settled on evidence;
* a PUBLISH GATE that refuses to publish a broken reconstruction.

PACE — TWO BASES, ONE PUBLISHED (2026-11-13)
-------------------------------------------
The OPEN slot's pace is measured against the elapsed-session share, so the
numerator must sit on the DAILY-BAR basis. The current (published) basis uses

    vol_basis_factor    = yahoo_5m_total(PRIOR session) / polygon_daily(PRIOR session)
    session_vol_to_0950 = yahoo_5m_volume_through_09:50 / vol_basis_factor
    pace                = session_vol_to_0950 / avg_vol_10d / 0.125

but the PRIOR session's 5-minute series comes from Yahoo's ARCHIVE, which
sums to only ~79-99% of its own official daily volume (measured 2026-11-12,
median ~0.79 on the 2026-11-11 session), while the LIVE session's 5-minute
series matches its live daily bar (0.999). Dividing a LIVE numerator by an
ARCHIVED factor therefore inflates the pace by roughly 10-25% — measured on
the published 2026-11-10 board as **~12%** (factor median 0.8918), which moves
~30 names between TECH_WATCH and Tier B (no Tier A/Soft-A name changes tier).

The alternative basis keeps both terms on the LIVE feed:

    vol_to_0950_official = daily_volume_live_today * (vol_to_0950 / y5m_total_to_pull)
    pace_live_basis      = vol_to_0950_official / avg_vol_10d / 0.125

**This engine publishes BOTH and the artifact still publishes ``pace`` (the
current basis) as the contract's pace column.** The new basis is published as
``pace_live_basis`` so the 15:50 SETTLED RVol can arbitrate on the next fire
of the same session — the settled session is the ground truth. Only after that
comparison does the basis change, and it must not change in the same commit.

THE PUBLISH GATE (a broken reconstruction must not reach an artifact)
---------------------------------------------------------------------
G1  INDEX (exact, drift-tolerant). The reconstructed 09:50 move for SPY/QQQ
    must sit within 0.75pp of the live index move the caller supplies (the
    bridge returns it). The 09:50->quote drift is ~0.1-0.2pp in practice; the
    2026-11-10 ten-day-basis defect was 6.3pp on QQQ. Tolerance 0.75pp.
G2  PRIOR CLOSE (exact). Every PUBLISHED name's reconstructed prior close must
    equal Yahoo's OWN daily close for the prior session within 0.5%. This is
    the check that catches defect #1 outright: measured 39 of 39 live names
    within 0.5% (SPY 759.79 vs 759.81), and the 10-day basis was off by ~10%.
G3  COMPLETENESS. Every published name must carry a price, a prior close, a
    gap, a pace and a verdict; the published count must equal the floor-cleared
    count. A truncated pull is a FAILURE, never a shorter board.
G4  BASIS SANITY (blunt, wide). The median |reconstructed move - the scanner's
    change| over the published set must be under 12pp. The correct basis reads
    3.16pp on the published 2026-11-10 set (the scanner's own `change` column
    LAGS, so this is deliberately loose); a ten-day-basis board reads >20pp.
    It is a last-resort detector, not a precision check.

A failed gate exits NON-ZERO and names the failure.

SUB-COMMANDS
------------
``universe``  the TradingView universe + the pre-filter union (the pull set)
``pull``      the Yahoo 5-minute pull (durable, resumable, throttle-aware)
``daily``     today's live 1-day bars + the prior session's official close
``gate``      the publish gate over a finished pull
``run``       universe -> pull -> floors -> daily -> gate, in one go
``selftest``  offline checks of every rule above (no network)

Every subcommand writes JSON and exits non-zero on a failed assertion.
"""

from __future__ import annotations

import argparse
import gzip
import http.client
import json
import os
import queue
import ssl
import sys
import threading
import time
import urllib.parse
import urllib.request
import zlib
from datetime import datetime, timedelta, timezone

CAPABILITY_MARKER = "OPEN_0950_PULL_V1"

# --- published constants ----------------------------------------------------
PACE_CONSTANT = 0.125
PACE_BAND_LOW = 0.1077
PACE_BAND_HIGH = 0.1649
OPEN_DOLLAR_FLOOR = 500_000.0
OPEN_PRICE_FLOOR = 1.0
OPEN_CAP_FLOOR = 50_000_000.0
PREFILTER_TURNOVER_MIN = 100_000.0
PREFILTER_MOVE_PP = 2.0
GATE_INDEX_TOLERANCE_PP = 0.75
GATE_PRIOR_CLOSE_TOLERANCE_PCT = 0.5
GATE_BASIS_SANITY_PP = 12.0
# The shared gap helper's thresholds (cloud-prompts/_shared/preopen_feed.py).
NOISE_BAND_PCT = 2.0
HELD_RATIO = 0.50

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")
CHART_HOST = "query1.finance.yahoo.com"
TV_SCAN_URL = "https://scanner.tradingview.com/america/scan"

CUT = "09:50"

# Levered / inverse / single-stock-levered products, matched as SUBSTRINGS:
# TradingView spells them "ProShares UltraPro QQQ" and "UltraShort", so a
# word-boundary rule leaks TQQQ/SQQQ onto the board (measured 2026-11-12: the
# substring rule drops 840 levered/inverse lines, the word-boundary rule 733
# and leaks 107). The ISSUER name is deliberately NOT a token — "proshares"
# would exclude the whole issuer's line, including its non-leveraged funds.
LEVERED_SUBSTRINGS = ("ultra", "leverag", "inverse", "2x", "3x", "-2x", "-3x",
                      " bear ", " bull ", "short ")


def et_zone():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("America/New_York")
    except Exception:
        return timezone(timedelta(hours=-5))


ET = et_zone()


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def yahoo_symbol(tv_symbol: str) -> str:
    """``NASDAQ:NVDA`` -> ``NVDA``; ``NYSE:SNUS/PH`` -> ``SNUS-PH``.

    Yahoo 404s on the venue prefix, and a ``/`` in a preferred-class ticker has
    to be a dash (ALL-P-B, not ALL-PB).
    """
    return tv_symbol.split(":")[-1].replace("/", "-")


def verdict(open_pct, now_pct):
    """The shared gap verdict (preopen_feed.py). `reverse` covers both signs."""
    if open_pct is None or now_pct is None:
        return "unknown"
    if abs(open_pct) < NOISE_BAND_PCT:
        return "no_move"
    if open_pct * now_pct < 0:
        return "reverse"
    if abs(now_pct) >= abs(open_pct) * HELD_RATIO:
        return "held"
    if abs(now_pct - open_pct) >= abs(open_pct) * (1 - HELD_RATIO):
        return "faded"
    return "held"


def classify_body(body: str):
    """(kind, payload) for a Yahoo chart response body.

    kind is one of: OK | THROTTLE | SYMBOL_MISSING | BAD_BODY.
    The edge's throttle body starts with ``Edge: ``, which defeats a
    ``startswith("Too Many")`` check — that is how a throttle used to be
    reported as a JSON parse error.
    """
    if not body:
        return "BAD_BODY", "empty body"
    head = body[:200].lower()
    if "too many requests" in head or "rate limit" in head:
        return "THROTTLE", body[:120]
    if body.lstrip().startswith("{"):
        try:
            d = json.loads(body)
        except Exception:
            return "BAD_BODY", "unparseable json"
        res = (d.get("chart") or {}).get("result")
        if not res:
            err = ((d.get("chart") or {}).get("error") or {})
            code = str(err.get("code") or "").lower()
            if "not found" in code or "no data" in code or "delisted" in code:
                return "SYMBOL_MISSING", err.get("description", code)
            return "BAD_BODY", json.dumps(err)[:160]
        return "OK", res[0]
    return "BAD_BODY", body[:120]


def _decompress(raw, enc):
    enc = (enc or "").lower()
    if "gzip" in enc:
        return gzip.decompress(raw)
    if "deflate" in enc:
        return zlib.decompress(raw)
    return raw


# --------------------------------------------------------------------------- #
# the Yahoo client — one keep-alive connection per worker
# --------------------------------------------------------------------------- #
class Throttle(Exception):
    """The edge refused the session. Stop, back off, resume."""


class YahooPuller:
    """A keep-alive HTTP client for the Yahoo chart endpoint.

    Measured 2026-11-13 on 240 cold symbols: one curl process per symbol ran
    at 12.4 req/s, this runs the SAME requests at 101.3 req/s, because the TLS
    handshake and the fork/exec were the cost, not Yahoo. On live data
    (2026-11-12 session) it pulled 40 symbols in 0.6s with 8 workers.
    """

    def __init__(self, timeout=25.0):
        self.timeout = timeout
        self.ctx = ssl.create_default_context()
        self.conn = None

    def _connect(self):
        self.conn = http.client.HTTPSConnection(
            CHART_HOST, 443, timeout=self.timeout, context=self.ctx)

    def close(self):
        try:
            if self.conn:
                self.conn.close()
        except Exception:
            pass
        self.conn = None

    def _request(self, path):
        self.conn.request("GET", path, headers={
            "User-Agent": UA,
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
        })
        resp = self.conn.getresponse()
        raw = resp.read()
        enc = resp.getheader("Content-Encoding")
        if resp.will_close:
            self.close()
        if resp.status == 429:
            raise Throttle("HTTP 429")
        return _decompress(raw, enc).decode("utf-8", "replace")

    def get(self, path: str):
        if self.conn is None:
            self._connect()
        try:
            return self._request(path)
        except Throttle:
            raise
        except Exception:
            # a stale keep-alive connection is normal: drop it and retry once
            self.close()
            self._connect()
            try:
                return self._request(path)
            except Throttle:
                raise
            except Exception as e:
                return "ERR:%s" % e


def chart_path(sym: str, rng: str = "2d", interval: str = "5m") -> str:
    return ("/v8/finance/chart/%s?interval=%s&range=%s&includePrePost=false"
            % (urllib.parse.quote(sym), interval, rng))


# --------------------------------------------------------------------------- #
# record construction
# --------------------------------------------------------------------------- #
def build_record(sym: str, res: dict, date: str, prior: str) -> dict:
    """The 09:50 ET state for one symbol, from ONE chart response.

    The prior close is the PRIOR SESSION's last non-null bar close — NOT
    ``meta.chartPreviousClose``, which in a multi-day range is the close
    before the range starts (measured 2026-11-10: it made every move a
    ten-day move).
    """
    meta = res.get("meta", {})
    ts = res.get("timestamp") or []
    q = (res.get("indicators", {}).get("quote") or [{}])[0]
    closes = q.get("close") or []
    opens = q.get("open") or []
    vols = q.get("volume") or []

    def cell(arr, i):
        return arr[i] if i < len(arr) else None

    by_date = {}
    for i, t in enumerate(ts):
        d = datetime.fromtimestamp(t, ET)
        by_date.setdefault(d.strftime("%Y-%m-%d"), []).append((d.strftime("%H:%M"), i))

    rec = {
        "symbol": sym,
        "meta_chart_previous_close": meta.get("chartPreviousClose"),
        "prior_close_source": "prior_session_last_non_null_bar",
    }

    pri = by_date.get(prior, [])
    pc = None
    pvol = 0.0
    for _hh, i in pri:
        c = cell(closes, i)
        if c is not None:
            pc = c
        pvol += (cell(vols, i) or 0)
    rec["prior_close"] = pc
    rec["y5m_total_prior"] = pvol
    rec["n_prior_bars"] = len(pri)

    day = by_date.get(date, [])
    rec["n_day_bars"] = len(day)
    if not day:
        rec["status"] = "NO_PRINT"
        return rec

    px = None
    open930 = None
    vol_to_cut = 0.0
    vol_to_pull = 0.0
    path = []
    for hh, i in day:
        c = cell(closes, i)
        v = cell(vols, i) or 0
        o = cell(opens, i)
        if hh <= CUT:
            # the VOLUME of a bar is real even when its close is null — it must
            # count towards the session total (a null-close bar dropped its
            # volume and under-counted the window)
            vol_to_cut += v
            if c is not None:
                if open930 is None and o is not None:
                    open930 = o
                px = c
                path.append([hh, c, v])
        vol_to_pull += v

    rec["close_0950"] = px
    rec["open_0930"] = open930
    rec["session_vol_to_0950_raw"] = vol_to_cut
    rec["y5m_total_to_pull"] = vol_to_pull
    rec["path"] = path
    if px is None:
        rec["status"] = "NO_PRICE_BEFORE_CUT"
        return rec
    if pc is None:
        rec["status"] = "NO_PRIOR_CLOSE"
        return rec

    rec["chg_pct_0950"] = (px / pc - 1.0) * 100.0
    rec["gap_pct"] = ((open930 / pc - 1.0) * 100.0) if open930 else None
    rec["gap_verdict"] = verdict(rec["gap_pct"], rec["chg_pct_0950"])
    rec["status"] = "OK"
    return rec


def attach_pace(rec: dict, avg10: dict, global_factor=None) -> dict:
    """Both pace bases, from the same record and the polygon's avg10."""
    avg = (avg10.get("avg10") or {})
    ps = avg10.get("prior_session") or {}
    ps_vol = ps.get("volumes") or {}
    a = avg.get(rec["symbol"])
    a = a.get("avg") if isinstance(a, dict) else a
    rec["avg_vol_10d"] = a
    if not a:
        rec["pace"] = None
        rec["pace_live_basis"] = None
        rec["vol_basis_factor"] = None
        rec["vol_basis_source"] = "no_denominator"
        return rec
    prior_daily = ps_vol.get(rec["symbol"])
    factor = None
    if prior_daily and rec.get("y5m_total_prior"):
        factor = rec["y5m_total_prior"] / prior_daily
        rec["vol_basis_source"] = "per_symbol"
    else:
        rec["vol_basis_source"] = "global_median"
    if factor is None:
        factor = global_factor or 1.0
    rec["vol_basis_factor"] = factor
    sv = (rec.get("session_vol_to_0950_raw") or 0) / factor
    rec["session_vol_to_0950"] = sv
    rec["pace"] = (sv / a / PACE_CONSTANT) if sv else None
    dl = rec.get("daily_volume_live_today")
    tp = rec.get("y5m_total_to_pull")
    if dl and tp:
        vol_official = dl * ((rec.get("session_vol_to_0950_raw") or 0) / tp)
        rec["vol_to_0950_official"] = vol_official
        rec["pace_live_basis"] = vol_official / a / PACE_CONSTANT
    else:
        rec["vol_to_0950_official"] = None
        rec["pace_live_basis"] = None
    return rec


# --------------------------------------------------------------------------- #
# the universe + the pre-filter union
# --------------------------------------------------------------------------- #
TV_COLUMNS = ["description", "sector", "industry", "close", "change", "volume",
               "gap", "relative_volume_10d_calc", "market_cap_basic", "exchange",
               "premarket_change", "premarket_volume", "premarket_close"]


def tv_scan(filt, columns=None):
    """ONE unpaginated scan call, verified against its own totalCount.

    `range` pagination returns DUPLICATE rows and MISSES others (measured
    2026-11-06), so the universe is always pulled in one call.
    """
    cols = columns or TV_COLUMNS
    body = {"filter": filt, "options": {"lang": "en"}, "markets": ["america"],
            "symbols": {"query": {"types": []}, "tickers": []},
            "columns": cols, "range": [0, 30000],
            "sort": {"sortBy": "volume", "sortOrder": "desc"}}
    req = urllib.request.Request(
        TV_SCAN_URL, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=180) as r:
        d = json.loads(r.read().decode())
    total = d.get("totalCount")
    rows = d.get("data") or []
    if len(rows) != total:
        raise SystemExit("TV scan truncated: %d rows vs totalCount %d" % (len(rows), total))
    out = {}
    for row in rows:
        rec = dict(zip(cols, row["d"]))
        rec["tv_symbol"] = row["s"]
        out[row["s"]] = rec
    return out, total


def is_leveraged(desc: str) -> bool:
    d = " " + (desc or "").lower() + " "
    return any(k in d for k in LEVERED_SUBSTRINGS)


def is_preferred(ticker: str, desc: str) -> bool:
    d = (desc or "").lower()
    t = (ticker or "").upper()
    return ("preferred" in d or "/P" in t or d.endswith(" pfd")
            or "mandatory convertible preferred" in d)


def is_warrant_or_unit(ticker: str, desc: str) -> bool:
    d = (desc or "").lower()
    t = (ticker or "").upper()
    if " warrant" in d or " warrants" in d or "right to purchase" in d:
        return True
    if "units" in d and ("each representing" in d or "units," in d):
        return True
    if t.endswith((".W", ".WT", ".WS")):
        return True
    return False


def build_universe():
    """Three unpaginated scan calls -> the tradeable universe + the pull set."""
    cash, n_cash = tv_scan([
        {"left": "type", "operation": "in_range", "right": ["stock", "dr"]},
        {"left": "exchange", "operation": "in_range",
         "right": ["NASDAQ", "NYSE", "AMEX", "NYSEARCA"]}])
    funds, n_funds = tv_scan([
        {"left": "type", "operation": "equal", "right": "fund"},
        {"left": "exchange", "operation": "in_range",
         "right": ["NASDAQ", "NYSE", "AMEX", "NYSEARCA"]}])
    otc, n_otc = tv_scan([
        {"left": "type", "operation": "in_range", "right": ["stock", "dr"]},
        {"left": "exchange", "operation": "equal", "right": "OTC"},
        {"left": "volume", "operation": "greater", "right": 300000}])

    universe = {}
    dropped = {"warrant_unit": 0, "preferred": 0, "leveraged": 0}
    for src, kind in ((cash, "cash"), (funds, "funds"), (otc, "otc")):
        for s, rec in src.items():
            ticker = s.split(":")[-1]
            desc = rec.get("description") or ""
            if is_warrant_or_unit(ticker, desc):
                dropped["warrant_unit"] += 1
                continue
            if is_preferred(ticker, desc):
                dropped["preferred"] += 1
                continue
            if kind == "funds" and is_leveraged(desc):
                dropped["leveraged"] += 1
                continue
            rec["kind"] = kind
            universe[s] = rec

    legs = {"turnover": 0, "move": 0, "noprice": 0}
    pull = []
    for s, rec in universe.items():
        close, vol = rec.get("close"), rec.get("volume") or 0
        chg, gap = rec.get("change"), rec.get("gap")
        noprice = close in (None, 0) or not isinstance(close, (int, float))
        t_leg = (not noprice) and (close * vol) >= PREFILTER_TURNOVER_MIN
        m_leg = ((isinstance(chg, (int, float)) and abs(chg) >= PREFILTER_MOVE_PP)
                 or (isinstance(gap, (int, float)) and abs(gap) >= PREFILTER_MOVE_PP))
        legs["turnover"] += int(t_leg)
        legs["move"] += int(m_leg)
        legs["noprice"] += int(noprice)
        if t_leg or m_leg or noprice:
            pull.append(s)

    return {
        "universe": universe,
        "pull_set": sorted(pull),
        "counts": {"tv_cash": n_cash, "tv_funds": n_funds, "tv_otc": n_otc,
                   "tradeable": len(universe), "pull_set": len(pull)},
        "dropped": dropped,
        "prefilter_legs": legs,
        "prefilter": {
            "turnover": "close * volume >= %d" % PREFILTER_TURNOVER_MIN,
            "move": "|change| >= %spp OR |gap| >= %spp" % (PREFILTER_MOVE_PP, PREFILTER_MOVE_PP),
            "noprice": "the scanner cannot price the symbol",
            "rule": "UNION of the three legs",
        },
    }


def select_published(records, universe, avg10):
    """The open slot's floors, applied to the reconstructed 09:50 state.

    price >= $1, market cap >= $50m (soft), session $ volume to 09:50 >= $0.5m,
    and the 09:50 trigger (|chg| >= 3% OR |gap| >= 3%).
    """
    avg = (avg10.get("avg10") or {})
    out = []
    for sym, rec in records.items():
        if rec.get("status") != "OK":
            continue
        px = rec.get("close_0950")
        if px is None or px < OPEN_PRICE_FLOOR:
            continue
        # the records are keyed by the TRADINGVIEW symbol; polygon's avg10 and
        # prior-session volumes are keyed by the BARE ticker
        ticker = rec.get("symbol") or sym.split(":")[-1]
        a = avg.get(ticker)
        a = a.get("avg") if isinstance(a, dict) else a
        if not a:
            continue
        prior_daily = ((avg10.get("prior_session") or {}).get("volumes") or {}).get(ticker)
        factor = None
        if prior_daily and rec.get("y5m_total_prior"):
            factor = rec["y5m_total_prior"] / prior_daily
        if factor is None:
            factor = rec.get("vol_basis_factor") or 1.0
        sv = (rec.get("session_vol_to_0950_raw") or 0) / factor
        dvol = sv * px
        if dvol < OPEN_DOLLAR_FLOOR:
            continue
        tvr = universe.get(rec.get("tv_symbol") or "", {})
        mcap = tvr.get("market_cap_basic")
        if mcap is not None and mcap < OPEN_CAP_FLOOR:
            continue
        chg = rec.get("chg_pct_0950")
        gap = rec.get("gap_pct")
        if not (abs(chg) >= 3 or (gap is not None and abs(gap) >= 3)):
            continue
        rec["session_vol_to_0950"] = sv
        rec["session_dollar_vol_0950"] = dvol
        rec["market_cap"] = mcap
        rec["name"] = tvr.get("description") or ""
        rec["sector"] = tvr.get("sector")
        rec["exchange"] = tvr.get("exchange")
        out.append(sym)
    return sorted(out)


def rebase_on_official(records, published, avg10):
    """Re-base the published set on the OFFICIAL prior close, then re-apply
    the trigger and the floors.

    The 5-minute series' last bar close is only an APPROXIMATION of the
    session close: the closing auction print does not always land in the bar
    series. Measured 2026-11-13 on the 2026-11-12 session: **26 of 646
    published names** had a 5-minute-derived prior close more than 0.5% away
    from Yahoo's own daily close (up to 1.4% on a $1.39 name). The published
    reference price MUST be the official close — the gap and the move are
    measured against it.

    A name whose move falls below the trigger after the re-base LEAVES the
    published set, and the artifact says how many left.
    """
    kept = []
    dropped = []
    for sym in published:
        rec = records.get(sym) or {}
        official = rec.get("daily_close_prior_official")
        if official:
            if abs(official - (rec.get("prior_close") or official)) > 1e-9:
                rec["prior_close_5m_bar"] = rec.get("prior_close")
                rec["prior_close"] = official
                rec["prior_close_source"] = "official_daily_close"
            pc = official
            rec["chg_pct_0950"] = (rec["close_0950"] / pc - 1.0) * 100.0
            rec["gap_pct"] = ((rec["open_0930"] / pc - 1.0) * 100.0) if rec.get("open_0930") else None
            rec["gap_verdict"] = verdict(rec["gap_pct"], rec["chg_pct_0950"])
        chg = rec.get("chg_pct_0950")
        gap = rec.get("gap_pct")
        if not (chg is not None and (abs(chg) >= 3 or (gap is not None and abs(gap) >= 3))):
            rec["dropped_after_rebase"] = True
            dropped.append(sym)
            continue
        sv = rec.get("session_vol_to_0950")
        px = rec.get("close_0950")
        if sv is None or px is None or sv * px < OPEN_DOLLAR_FLOOR:
            rec["dropped_after_rebase"] = True
            dropped.append(sym)
            continue
        kept.append(sym)
    return kept, dropped


# --------------------------------------------------------------------------- #
# the pull
# --------------------------------------------------------------------------- #
def load_done(path):
    """Symbols already on disk — a retry resumes instead of restarting.

    KEYED BY THE TRADINGVIEW SYMBOL (the work list's key). Keying by the Yahoo
    symbol instead made every round look "incomplete" and re-fetched the whole
    universe (measured 2026-11-13: 8,627 symbols re-pulled because
    `NASDAQ:NVDA` never matched `NVDA`).
    """
    done = {}
    if not os.path.exists(path):
        return done
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            key = rec.get("tv_symbol") or rec.get("symbol")
            if key:
                done[key] = rec
    return done


def pull(symbols, out_jsonl, date, prior, workers=12, rng="2d",
         max_rounds=4, backoff=20.0, progress=True):
    """The Yahoo 5-minute pull. Durable, resumable, throttle-aware."""
    done = load_done(out_jsonl)
    todo = [s for s in symbols if s not in done]
    stats = {"requested": len(symbols), "resumed": len(done), "fetched": 0,
             "missing": 0, "bad_body": 0, "throttle_rounds": 0,
             "errors": {}, "elapsed_s": 0.0}
    if not todo:
        stats["landed"] = len(done)
        stats["fetched"] = len([r for r in done.values() if r.get("status") == "OK"])
        stats["missing"] = len([r for r in done.values() if r.get("status") == "SYMBOL_MISSING"])
        stats["bad_body"] = len([r for r in done.values() if r.get("status") == "BAD_BODY"])
        return done, stats


    q = queue.Queue()
    for s in todo:
        q.put(s)
    lock = threading.Lock()
    fh = open(out_jsonl, "a", encoding="utf-8")
    t0 = time.time()

    def worker():
        puller = YahooPuller()
        try:
            while True:
                try:
                    tv = q.get_nowait()
                except queue.Empty:
                    return
                try:
                    body = puller.get(chart_path(yahoo_symbol(tv), rng=rng))
                except Throttle:
                    with lock:
                        q.put(tv)
                    raise
                kind, payload = classify_body(body)
                if kind == "THROTTLE":
                    with lock:
                        q.put(tv)
                    raise Throttle(payload)
                with lock:
                    if kind == "OK":
                        rec = build_record(yahoo_symbol(tv), payload, date, prior)
                        rec["tv_symbol"] = tv
                    elif kind == "SYMBOL_MISSING":
                        rec = {"symbol": yahoo_symbol(tv), "tv_symbol": tv,
                               "status": "SYMBOL_MISSING"}
                    else:
                        rec = {"symbol": yahoo_symbol(tv), "tv_symbol": tv,
                               "status": "BAD_BODY", "detail": str(payload)[:160]}
                        stats["errors"][str(payload)[:60]] = \
                            stats["errors"].get(str(payload)[:60], 0) + 1
                    fh.write(json.dumps(rec) + "\n")
                    fh.flush()
                    if progress and len(done) % 250 == 0:
                        pass
        finally:
            puller.close()
            try:
                fh.flush()
            except Exception:
                pass

    for rnd in range(max_rounds):
        stats["throttle_rounds"] = rnd
        threads = [threading.Thread(target=worker, daemon=True) for _ in range(workers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        done = load_done(out_jsonl)
        remaining = [s for s in todo if s not in done]
        stats["fetched"] = len([r for r in done.values() if r.get("status") == "OK"])
        stats["missing"] = len([r for r in done.values() if r.get("status") == "SYMBOL_MISSING"])
        stats["bad_body"] = len([r for r in done.values() if r.get("status") == "BAD_BODY"])
        stats["landed"] = len(done)
        if not remaining:
            break
        sys.stderr.write("open_0950_pull: %d symbols outstanding after round %d; "
                         "backing off %ds before resuming\n" % (len(remaining), rnd, backoff))
        stats["errors"]["outstanding_after_round_%d" % rnd] = len(remaining)
        time.sleep(backoff)
        todo = remaining
        q = queue.Queue()
        for s in todo:
            q.put(s)
    fh.flush()
    fh.close()
    stats["elapsed_s"] = round(time.time() - t0, 1)
    done = load_done(out_jsonl)
    missing = [s for s in symbols if s not in done]
    stats["missing_symbols"] = len(missing)
    stats["landed"] = len(done)
    if missing:
        sys.stderr.write("open_0950_pull: %d symbols never landed — the pull is "
                         "INCOMPLETE and must not be published as a shorter board\n"
                         % len(missing))
    return done, stats


def daily_bars(symbols, date, prior, workers=12):
    """Per symbol: today's LIVE daily volume + the PRIOR session's OFFICIAL close.

    One 1-day request per name gives both: the live-basis pace anchor and the
    exact prior close the gate checks the reconstruction against.
    """
    out = {}
    q = queue.Queue()
    for s in symbols:
        q.put(s)
    lock = threading.Lock()

    def worker():
        puller = YahooPuller()
        try:
            while True:
                try:
                    sym = q.get_nowait()
                except queue.Empty:
                    return
                try:
                    body = puller.get(chart_path(yahoo_symbol(sym), rng="10d", interval="1d"))
                except Throttle:
                    with lock:
                        q.put(sym)
                    return
                kind, payload = classify_body(body)
                if kind != "OK":
                    continue
                ts = payload.get("timestamp") or []
                vols = ((payload.get("indicators", {}).get("quote") or [{}])[0].get("volume") or [])
                closes = ((payload.get("indicators", {}).get("quote") or [{}])[0].get("close") or [])
                rec = {}
                for i, t in enumerate(ts):
                    d = datetime.fromtimestamp(t, ET).strftime("%Y-%m-%d")
                    v = vols[i] if i < len(vols) else None
                    c = closes[i] if i < len(closes) else None
                    if d == date:
                        rec["daily_volume_live_today"] = v
                    elif d == prior:
                        rec["daily_close_prior_official"] = c
                        rec["daily_volume_prior_official"] = v
                with lock:
                    out[sym] = rec
        finally:
            puller.close()

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return out


# --------------------------------------------------------------------------- #
# the publish gate
# --------------------------------------------------------------------------- #
def run_gate(records, index_live=None, published=None, daily=None,
             scanner_change=None):
    """Refuse to publish a broken reconstruction.

    index_live:     {"SPY": -0.26, "QQQ": -0.23} — the live index moves the
                    caller already has (the MCP bridge returns them).
    published:      the symbols that reach the artifact.
    daily:          {sym: {"daily_close_prior_official": x, ...}} — Yahoo's
                    own daily bars for the published names.
    scanner_change: {sym: change_pct} — the scanner's own live change (a
                    deliberately LOOSE cross-check: that column LAGS).
    """
    failures = []
    checks = {}
    published = published if published is not None else list(records.keys())
    moves = {}
    for sym, rec in records.items():
        if rec.get("status") == "OK" and rec.get("chg_pct_0950") is not None:
            # keyed by the BARE ticker: the index names (SPY/QQQ) and the
            # scanner's change column are bare, the records are TV-keyed
            moves[rec.get("symbol") or sym.split(":")[-1]] = rec["chg_pct_0950"]

    # --- G1: the index ------------------------------------------------------
    for sym, live in (index_live or {}).items():
        got = moves.get(sym)
        if got is None:
            failures.append("G1: %s has no reconstructed 09:50 move (the index must "
                            "be in the pull set)" % sym)
            continue
        if abs(got - live) > GATE_INDEX_TOLERANCE_PP:
            failures.append("G1: %s reconstructed 09:50 move %+.2f%% vs the live index "
                            "move %+.2f%% — %.2fpp apart, over the %.2fpp tolerance (a "
                            "broken reconstruction)" % (sym, got, live,
                                                        abs(got - live),
                                                        GATE_INDEX_TOLERANCE_PP))
        else:
            checks["index_%s" % sym] = round(got - live, 3)
    checks["index_checked"] = sorted((index_live or {}).keys())

    # --- G2: the prior close, against Yahoo's OWN daily bar -----------------
    checked = off = 0
    for sym in published:
        d = (daily or {}).get(sym) or {}
        official = d.get("daily_close_prior_official")
        rec = records.get(sym) or {}
        if not rec:
            rec = next((v for v in records.values()
                        if v.get("symbol") == sym), {}) or {}
        mine = rec.get("prior_close")
        if official is None or mine is None:
            continue
        checked += 1
        diff = (mine / official - 1.0) * 100.0
        if abs(diff) > GATE_PRIOR_CLOSE_TOLERANCE_PCT:
            off += 1
            failures.append("G2: %s reconstructed prior close %.4f vs Yahoo's own daily "
                            "close %.4f (%+.2f%% apart, over %.2f%%) — the prior close is "
                            "not the prior session's close" % (sym, mine, official, diff,
                                                                GATE_PRIOR_CLOSE_TOLERANCE_PCT))
    checks["prior_close_checked"] = checked
    checks["prior_close_off"] = off

    # --- G3: completeness ---------------------------------------------------
    incomplete = []
    for sym in published:
        rec = records.get(sym) or {}
        if not rec:
            rec = next((v for v in records.values()
                        if v.get("symbol") == sym), {}) or {}
        if rec.get("status") != "OK" or not rec.get("close_0950") \
                or not rec.get("prior_close") or rec.get("pace") is None \
                or not rec.get("gap_verdict"):
            incomplete.append(sym)
    if incomplete:
        failures.append("G3: %d published names are missing a price, a prior close, a "
                        "pace or a verdict: %s" % (len(incomplete),
                                                  ", ".join(incomplete[:10])))
    checks["published"] = len(published)

    # --- G4: the basis sanity band (deliberately loose) ----------------------
    if scanner_change:
        diffs = []
        for sym in published:
            rec = records.get(sym) or {}
            ticker = (rec.get("symbol") or sym.split(":")[-1]) if rec else sym.split(":")[-1]
            sc = scanner_change.get(ticker)
            if sc is None or ticker not in moves:
                continue
            diffs.append(abs(moves[ticker] - sc))
        if diffs:
            diffs.sort()
            median = diffs[len(diffs) // 2]
            checks["basis_sanity_median_pp"] = round(median, 3)
            checks["basis_sanity_n"] = len(diffs)
            if median > GATE_BASIS_SANITY_PP:
                failures.append("G4: the median |reconstructed move - scanner change| over "
                                "the published set is %.2fpp, over the %.2fpp band — a "
                                "systematically wrong basis" % (median, GATE_BASIS_SANITY_PP))

    return {"ok": not failures, "failures": failures, "checks": checks,
            "priced": len(moves)}


# --------------------------------------------------------------------------- #
# selftest — offline, no network
# --------------------------------------------------------------------------- #
def selftest():
    fails = []
    tally = {"ok": 0}

    def check(name, cond, detail=""):
        if cond:
            tally["ok"] += 1
            print("  ok   %s" % name)
        else:
            fails.append(name)
            print("  FAIL %s %s" % (name, detail))

    def bar(ts, o, c, v):
        return {"ts": ts, "o": o, "c": c, "v": v}

    def mk(prior_bars, day_bars, meta_pc=100.0):
        ts, closes, opens, vols = [], [], [], []
        for b in prior_bars + day_bars:
            ts.append(b["ts"])
            closes.append(b["c"])
            opens.append(b["o"])
            vols.append(b["v"])
        return {"meta": {"chartPreviousClose": meta_pc},
                "timestamp": ts,
                "indicators": {"quote": [{"close": closes, "open": opens, "volume": vols}]}}

    # --- 1. the prior close comes from the PRIOR SESSION's bars --------------
    d_prior = datetime(2026, 11, 9, 15, 55, tzinfo=ET)
    prior_bars = [bar(d_prior.timestamp(), 178.0, 179.5, 1000)]
    d_40 = datetime(2026, 11, 10, 9, 40, tzinfo=ET)
    d_45 = datetime(2026, 11, 10, 9, 45, tzinfo=ET)
    day_bars = [bar(d_40.timestamp(), 171.0, 171.5, 500)]
    rec = build_record("NVDA", mk(prior_bars, day_bars, meta_pc=220.0),
                       "2026-11-10", "2026-11-09")
    check("prior close is the PRIOR SESSION's last bar, not meta.chartPreviousClose",
          rec["prior_close"] == 179.5, "got %r" % rec["prior_close"])
    check("the move is computed against that prior close",
          abs(rec["chg_pct_0950"] - (171.5 / 179.5 - 1) * 100) < 1e-6,
          "got %r" % rec.get("chg_pct_0950"))
    check("the stale meta.chartPreviousClose is retained for audit only",
          rec["meta_chart_previous_close"] == 220.0)

    # --- 2. a NULL close must not drop the name or its volume ---------------
    day_bars2 = [bar(d_40.timestamp(), 171.0, None, 300),
                 bar(d_45.timestamp(), 170.5, 170.0, 700)]
    rec2 = build_record("X", mk(prior_bars, day_bars2), "2026-11-10", "2026-11-09")
    check("a null close does not drop the name", rec2.get("status") == "OK",
          "got %r" % rec2.get("status"))
    check("the price is the last NON-NULL close at or before the cut",
          rec2.get("close_0950") == 170.0, "got %r" % rec2.get("close_0950"))
    check("the volume to the cut sums the bars WITH a null close too",
          rec2.get("session_vol_to_0950_raw") == 1000,
          "got %r" % rec2.get("session_vol_to_0950_raw"))

    # --- 3. the throttle body is classified as a THROTTLE -------------------
    k, _ = classify_body("Edge: Too Many Requests")
    check("'Edge: Too Many Requests' is a THROTTLE", k == "THROTTLE", "got %r" % k)
    k, _ = classify_body("Too Many Requests")
    check("'Too Many Requests' is a THROTTLE", k == "THROTTLE", "got %r" % k)
    k, _ = classify_body('{"chart":{"result":null,"error":{"code":"Not Found",'
                         '"description":"No data found, symbol may be delisted"}}}')
    check("a delisted symbol is SYMBOL_MISSING, not a parse error",
          k == "SYMBOL_MISSING", "got %r" % k)
    k, _ = classify_body("<html>oops</html>")
    check("an html shell is a BAD_BODY, not a THROTTLE", k == "BAD_BODY", "got %r" % k)

    # --- 4. the Yahoo symbol form ------------------------------------------
    check("the venue prefix is stripped", yahoo_symbol("NASDAQ:NVDA") == "NVDA")
    check("a slash class becomes a dash", yahoo_symbol("NYSE:SNUS/PH") == "SNUS-PH")

    # --- 5. the universe filters --------------------------------------------
    check("'ProShares UltraPro QQQ' is levered (substring, not word-boundary)",
          is_leveraged("ProShares UltraPro QQQ"))
    check("'Direxion Daily Semiconductor Bull 3X ETF' is levered",
          is_leveraged("Direxion Daily Semiconductor Bull 3X ETF"))
    check("'ProShares Bitcoin ETF' is NOT levered", not is_leveraged("ProShares Bitcoin ETF"))
    check("'ProShares Short Russell2000' IS levered",
          is_leveraged("ProShares Short Russell2000"))
    check("'Direxion Daily S&P 500 Bear 1X ETF' IS levered (no 2x/3x token)",
          is_leveraged("Direxion Daily S&P 500 Bear 1X ETF"))
    check("'ProShares UltraShort QQQ' IS levered", is_leveraged("ProShares UltraShort QQQ"))
    check("'iShares Core S&P 500 ETF' is NOT levered",
          not is_leveraged("iShares Core S&P 500 ETF"))
    check("a depositary preferred is excluded",
          is_preferred("SNUS/PH", "Santander Depositary Shares Preferred Stock"))
    check("a common share is not excluded", not is_preferred("AAPL", "Apple Inc."))
    check("a warrant is excluded", is_warrant_or_unit("ABCW", "ABC Warrant"))
    check("'Unity Software Inc.' is NOT a warrant (suffix rule must not fire)",
          not is_warrant_or_unit("U", "Unity Software Inc."))

    # --- 6. the gate catches a broken reconstruction -------------------------
    good = {"SPY": {"status": "OK", "chg_pct_0950": -0.26, "prior_close": 700.0,
                    "close_0950": 698.2, "pace": 1.2, "gap_verdict": "held"},
            "AAPL": {"status": "OK", "chg_pct_0950": 1.0, "prior_close": 100.0,
                     "close_0950": 101.0, "pace": 1.1, "gap_verdict": "held"}}
    g = run_gate(good, {"SPY": -0.26}, published=list(good.keys()))
    check("a consistent reconstruction passes the gate", g["ok"], str(g["failures"]))
    bad = {"SPY": {"status": "OK", "chg_pct_0950": -6.55, "prior_close": 700.0,
                   "close_0950": 654.2, "pace": 1.2, "gap_verdict": "held"},
           "AAPL": {"status": "OK", "chg_pct_0950": -6.0, "prior_close": 100.0,
                    "close_0950": 94.0, "pace": 1.1, "gap_verdict": "held"}}
    g2 = run_gate(bad, {"SPY": -0.26}, published=list(bad.keys()))
    check("a broken reconstruction FAILS the gate", not g2["ok"])
    check("the gate names the index mismatch",
          any("SPY" in f for f in g2["failures"]), str(g2["failures"]))

    # --- 7. G2: the exact prior-close check ---------------------------------
    d = {"SPY": {"daily_close_prior_official": 700.0}}
    g3 = run_gate(good, {"SPY": -0.26}, published=["SPY"], daily=d)
    check("G2 passes when the reconstructed prior close equals the daily bar",
          g3["ok"], str(g3["failures"]))
    g4 = run_gate(good, {"SPY": -0.26}, published=["SPY"],
                  daily={"SPY": {"daily_close_prior_official": 500.0}})
    check("G2 FAILS when the prior close is 10 sessions old",
          not g4["ok"] and any("G2" in f for f in g4["failures"]), str(g4["failures"]))

    # --- 8. the pace scales --------------------------------------------------
    avg10 = {"avg10": {"X": {"avg": 1000.0, "n": 10}},
             "prior_session": {"date": "2026-11-09", "volumes": {"X": 10000.0}}}
    r = {"symbol": "X", "status": "OK", "session_vol_to_0950_raw": 500.0,
         "y5m_total_prior": 8000.0, "y5m_total_to_pull": 9000.0,
         "daily_volume_live_today": 9500.0}
    attach_pace(r, avg10)
    check("the factor is y5m_total_prior / polygon_daily(prior)",
          abs(r["vol_basis_factor"] - 0.8) < 1e-9, "got %r" % r["vol_basis_factor"])
    check("pace = (session_vol / avg_vol_10d) / 0.125",
          abs(r["pace"] - (625.0 / 1000.0 / 0.125)) < 1e-9, "got %r" % r["pace"])
    check("the live basis uses today's live daily volume",
          abs(r["pace_live_basis"] - (9500.0 * (500.0 / 9000.0) / 1000.0 / 0.125)) < 1e-9,
          "got %r" % r["pace_live_basis"])

    # --- 9. the re-base on the OFFICIAL prior close -------------------------
    rb = {"NYSE:ABR": {"symbol": "ABR", "tv_symbol": "NYSE:ABR", "status": "OK",
                       "close_0950": 1.46, "open_0930": 1.45, "prior_close": 1.4099,
                       "daily_close_prior_official": 1.40,
                       "session_vol_to_0950": 400000.0,
                       "chg_pct_0950": (1.46 / 1.4099 - 1) * 100,
                       "gap_pct": (1.45 / 1.4099 - 1) * 100, "gap_verdict": "held"}}
    kept, dropped = rebase_on_official(rb, ["NYSE:ABR"], {})
    check("the re-base replaces the 5m prior close with the OFFICIAL close",
          rb["NYSE:ABR"]["prior_close"] == 1.40,
          str(rb["NYSE:ABR"]["prior_close"]))
    check("the 5m prior close is kept for audit",
          rb["NYSE:ABR"].get("prior_close_5m_bar") == 1.4099)
    check("the move is recomputed against the official close",
          abs(rb["NYSE:ABR"]["chg_pct_0950"] - (1.46 / 1.40 - 1) * 100) < 1e-9,
          str(rb["NYSE:ABR"]["chg_pct_0950"]))
    check("the re-base keeps a name that still clears the trigger",
          kept == ["NYSE:ABR"] and not dropped)
    rb2 = json.loads(json.dumps(rb))
    rb2["NYSE:ABR"]["daily_close_prior_official"] = 1.4550  # the move collapses into the noise
    kept2, dropped2 = rebase_on_official(rb2, ["NYSE:ABR"], {})
    check("a name that falls below the trigger after the re-base LEAVES the set",
          kept2 == [] and dropped2 == ["NYSE:ABR"])

    # --- 10. the verdict matches the shared helper --------------------------
    check("verdict: a 5% gap held at +4% is 'held'", verdict(5.0, 4.0) == "held")
    check("verdict: a 5% gap at +1% is 'faded'", verdict(5.0, 1.0) == "faded")
    check("verdict: a 5% gap at -1% is 'reverse'", verdict(5.0, -1.0) == "reverse")
    check("verdict: a 1% open is 'no_move'", verdict(1.0, 1.5) == "no_move")

    # --- 11. the resume path -------------------------------------------------
    import tempfile
    tmp = tempfile.mkdtemp()
    jl = os.path.join(tmp, "records.jsonl")
    recs = {"A": {"symbol": "A", "status": "OK"}}
    with open(jl, "w") as fh:
        fh.write(json.dumps(recs["A"]) + "\n")
    check("a completed symbol is not re-fetched on a retry",
          "A" in load_done(jl))

    print()
    total = tally["ok"] + len(fails)
    if fails:
        print("SELFTEST FAILED — %d of %d checks failed: %s"
              % (len(fails), total, ", ".join(fails)))
        return 1
    print("SELFTEST OK — %d checks passed" % total)
    return 0


# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    u = sub.add_parser("universe")
    u.add_argument("--out", required=True)

    p = sub.add_parser("pull")
    p.add_argument("--universe", required=True)
    p.add_argument("--date", required=True)
    p.add_argument("--prior", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--workers", type=int, default=12)
    p.add_argument("--range", dest="rng", default="2d")
    p.add_argument("--backoff", type=float, default=20.0)
    p.add_argument("--rounds", type=int, default=4)

    d = sub.add_parser("daily")
    d.add_argument("--records", required=True)
    d.add_argument("--symbols", required=True, help="a file with one symbol per line")
    d.add_argument("--date", required=True)
    d.add_argument("--prior", required=True)
    d.add_argument("--out", required=True)
    d.add_argument("--workers", type=int, default=12)

    g = sub.add_parser("gate")
    g.add_argument("--records", required=True)
    g.add_argument("--published", default="")
    g.add_argument("--daily", default="")
    g.add_argument("--index-live", default="")
    g.add_argument("--out", default="")

    r = sub.add_parser("run")
    r.add_argument("--date", required=True)
    r.add_argument("--prior", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--avg10", default="/workspace/avg10.json")
    r.add_argument("--index-live", default="")
    r.add_argument("--workers", type=int, default=12)

    sub.add_parser("selftest")

    a = ap.parse_args()
    if getattr(a, "out", None):
        os.makedirs(a.out, exist_ok=True)

    if a.cmd == "selftest":
        sys.exit(selftest())

    if a.cmd == "universe":
        uu = build_universe()
        path = os.path.join(a.out, "universe.json")
        json.dump(uu, open(path, "w"))
        print(json.dumps({"counts": uu["counts"], "dropped": uu["dropped"],
                          "prefilter_legs": uu["prefilter_legs"]}, indent=1))
        print("wrote %s" % path)
        return

    if a.cmd == "pull":
        uu = json.load(open(a.universe))
        jsonl = os.path.join(a.out, "records.jsonl")
        recs, stats = pull(uu["pull_set"], jsonl, a.date, a.prior,
                           workers=a.workers, rng=a.rng, backoff=a.backoff,
                           max_rounds=a.rounds)
        print(json.dumps(stats, indent=1))
        return

    if a.cmd == "daily":
        recs = load_done(a.records)
        syms = [s.strip() for s in open(a.symbols) if s.strip()]
        vols = daily_bars(syms, a.date, a.prior, workers=a.workers)
        json.dump(vols, open(a.out, "w"))
        print("daily bars for %d of %d names" % (len(vols), len(syms)))
        return

    if a.cmd == "gate":
        recs = load_done(a.records)
        live = {}
        for part in [x for x in a.index_live.split(",") if x.strip()]:
            if "=" in part:
                k, v = part.split("=", 1)
                live[k.strip().upper()] = float(v)
        pub = None
        if a.published and os.path.exists(a.published):
            pub = [x.strip() for x in open(a.published) if x.strip()]
        daily = {}
        if a.daily and os.path.exists(a.daily):
            daily = json.load(open(a.daily))
        res = run_gate(recs, live, published=pub, daily=daily)
        print(json.dumps(res, indent=1))
        if a.out:
            json.dump(res, open(a.out, "w"))
        sys.exit(0 if res["ok"] else 1)

    if a.cmd == "run":
        uu = build_universe()
        json.dump(uu, open(os.path.join(a.out, "universe.json"), "w"))
        jsonl = os.path.join(a.out, "records.jsonl")
        recs, stats = pull(uu["pull_set"], jsonl, a.date, a.prior, workers=a.workers)
        avg10 = {}
        if os.path.exists(a.avg10):
            avg10 = json.load(open(a.avg10))
        pub = select_published(recs, uu["universe"], avg10)
        daily = daily_bars(pub, a.date, a.prior, workers=a.workers)
        for sym, d in daily.items():
            if sym in recs:
                recs[sym].update(d)
        pub, dropped = rebase_on_official(recs, pub, avg10)
        for sym in pub:
            attach_pace(recs[sym], avg10)
        with open(jsonl, "w", encoding="utf-8") as fh:
            for rec in recs.values():
                fh.write(json.dumps(rec) + "\n")
        scanner_change = {s.split(":")[-1]: r.get("change")
                          for s, r in uu["universe"].items()}
        live = {}
        for part in [x for x in a.index_live.split(",") if x.strip()]:
            if "=" in part:
                k, v = part.split("=", 1)
                live[k.strip().upper()] = float(v)
        gate = run_gate(recs, live, published=pub, daily=daily,
                        scanner_change=scanner_change)
        rebased = len([r for r in recs.values()
                       if r.get("prior_close_source") == "official_daily_close"])
        summary = {"stats": stats, "gate": gate, "counts": uu["counts"],
                   "dropped": uu["dropped"], "prefilter_legs": uu["prefilter_legs"],
                   "published": len(pub), "published_after_rebase": len(pub),
                   "dropped_after_rebase": len(dropped),
                   "rebased_on_official_close": rebased}
        json.dump(summary, open(os.path.join(a.out, "summary.json"), "w"), indent=1)
        with open(os.path.join(a.out, "published.txt"), "w") as fh:
            fh.write("\n".join(pub) + "\n")
        print(json.dumps(summary, indent=1))
        sys.exit(0 if gate["ok"] else 1)


if __name__ == "__main__":
    main()
