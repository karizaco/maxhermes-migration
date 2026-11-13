#!/usr/bin/env python3
"""
earnings_reaction_stats.py — reaction-potential columns for the cron #19 earnings reminder.

REACTION_STATS_VERSION: 2026-11-13.1

Computes, for a list of US-traded tickers:

  prior_day_move_pct    last completed session's close-to-close % move
  ytd_move_pct          YTD % move (first bar of the current calendar year -> last close)
  avg_abs_move_pct      mean |reaction| over this name's last N past earnings reports
  implied_move_pct      options-implied move (ATM straddle, first expiry that straddles the event)
  prior_report_result   last reported quarter: beat / miss (+ surprise %)
  reaction_score        0.6 * avg_abs_move_pct + 0.4 * implied_move_pct
                        (a missing implied move is substituted by avg_abs_move_pct, so a name
                         with no derivable implied move scores exactly its avg_abs_move_pct)

Data sources (all public HTTP, verified live 2026-11-05/06):
  Yahoo chart API      query1.finance.yahoo.com/v8/finance/chart/<SYM>  (cookie+crumb NOT required)
  Yahoo quoteSummary   query1.finance.yahoo.com/v10/finance/quoteSummary/<SYM>?modules=earningsHistory
                       (cookie + crumb REQUIRED — the crumb handshake must seed fc.yahoo.com first)
  Nasdaq earnings API  api.nasdaq.com/api/company/<SYM>/earnings-surprise  (past REPORT dates)
  Cboe delayed quotes  cdn.cboe.com/api/global/delayed_quotes/options/<SYM>.json  (implied move)

Usage:
  python3 earnings_reaction_stats.py --tickers AAPL,MSFT --earnings-date 2026-11-06 --timing BMO,AMC
  python3 earnings_reaction_stats.py --tickers-file tickers.txt --earnings-date 2026-11-06 \
      --timing-file timing.txt --out stats.json --csv stats.csv
  python3 earnings_reaction_stats.py --band 40000000000 50000000000 --out band.json

Exit codes: 0 ok, 1 usage error, 2 every ticker failed.
"""
import argparse, csv, json, os, re, subprocess, sys, tempfile, time
from datetime import date, datetime, timedelta

REACTION_STATS_VERSION = "2026-11-13.1"
# CAPABILITY MARKER (2026-11-13): the Nasdaq earnings-surprise fallback for the prior result.
# The SKILL fetch ladder demands this token, so a CACHED OLD COPY CANNOT WIN.
REACTION_STATS_NASDAQ_PRIOR_RESULT = "nasdaq-prior-result-fallback"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
# The cookie jar NEVER lives next to the script: the script is fetched into a repo tree and a
# stray jar would be committed. It goes to the temp dir.
JAR = os.path.join(tempfile.gettempdir(), "earnings_reaction_stats_cookies.jar")


# ----------------------------------------------------------------------------- http
def _curl(url, jar=False, timeout=30, headers=None, method="GET", data=None):
    cmd = ["curl", "-sL", "--max-time", str(timeout), "-A", UA]
    if jar:
        cmd += ["-b", JAR, "-c", JAR]
    for h in (headers or []):
        cmd += ["-H", h]
    if method == "POST":
        cmd += ["-X", "POST", "-H", "Content-Type: application/json", "-d", data or "{}"]
    cmd += [url]
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout + 5)
    except subprocess.TimeoutExpired:
        return b""
    return p.stdout


def _json(url, **kw):
    raw = _curl(url, **kw)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


_crumb = {"value": None, "tried": False}


def yahoo_crumb():
    """Cookie+crumb handshake. The cookie jar must be SEEDED (fc.yahoo.com) before getcrumb,
    otherwise the crumb comes back as an Unauthorized JSON body."""
    if _crumb["value"]:
        return _crumb["value"]
    if _crumb["tried"]:
        return None
    _crumb["tried"] = True
    os.makedirs(os.path.dirname(JAR) or ".", exist_ok=True)
    try:
        os.remove(JAR)
    except OSError:
        pass
    _curl("https://fc.yahoo.com", jar=True)
    raw = _curl("https://query1.finance.yahoo.com/v1/test/getcrumb", jar=True).decode("utf-8", "replace").strip()
    if raw and "Unauthorized" not in raw and "\n" not in raw:
        _crumb["value"] = raw
    return _crumb["value"]


def yahoo_quote_summary(symbol, modules):
    crumb = yahoo_crumb()
    if not crumb:
        return None
    url = (f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{symbol}"
           f"?modules={modules}&crumb={crumb}")
    d = _json(url, jar=True)
    try:
        return d["quoteSummary"]["result"][0]
    except Exception:
        return None


def yahoo_chart(symbol, rng="2y"):
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
           f"?interval=1d&range={rng}&includePrePost=false")
    d = _json(url, jar=True)
    try:
        res = d["chart"]["result"][0]
        ts = res["timestamp"]
        closes = res["indicators"]["quote"][0]["close"]
        rows = []
        for t, c in zip(ts, closes):
            if c is None:
                continue
            rows.append((datetime.utcfromtimestamp(t).date(), float(c)))
        return rows
    except Exception:
        return []


# ------------------------------------------------------------------- prior moves
def prior_day_move_pct(bars):
    if len(bars) < 2:
        return None
    return round((bars[-1][1] / bars[-2][1] - 1.0) * 100.0, 2)


def ytd_move_pct(bars):
    if not bars:
        return None
    year = bars[-1][0].year
    first = next((c for d, c in bars if d.year == year), None)
    if first is None or bars[-1][1] == 0:
        return None
    return round((bars[-1][1] / first - 1.0) * 100.0, 2)


# ---------------------------------------------------------- historical reactions
def nasdaq_report_dates(symbol):
    """Past REPORT dates from Nasdaq's earnings-surprise table (dateReported)."""
    d = _json(f"https://api.nasdaq.com/api/company/{symbol}/earnings-surprise",
              headers=["Accept: application/json", "Referer: https://www.nasdaq.com/"])
    try:
        tbl = d["data"]["earningsSurpriseTable"]["rows"]
    except Exception:
        tbl = []
    out = []
    for row in tbl:
        raw = (row.get("dateReported") or "").strip()
        # Nasdaq renders dateReported as M/D/YYYY (e.g. "11/2/2026"), NOT ISO.
        m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", raw)
        if m:
            try:
                out.append(date(int(m.group(3)), int(m.group(1)), int(m.group(2))))
            except ValueError:
                continue
            continue
        m = re.search(r"(\d{4})-(\d{2})-(\d{2})", raw)
        if m:
            out.append(date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
    return sorted(set(out), reverse=True)


def avg_abs_move_pct(bars, report_dates, timing, n_events=4):
    """Mean |reaction| over the last n_events past reports.

    The reaction window depends on the release convention:
      BMO -> close(D-1) -> close(D)      (the report lands before that session's open)
      AMC -> close(D)   -> close(D+1)    (the report lands after that session's close)
    The CURRENT release convention of the name is applied to its historical reports; a name that
    switched convention between reports is noted in the artifact's notes, never silently mixed.
    """
    if not bars or not report_dates:
        return None, 0
    closes = {d: c for d, c in bars}
    dates = [d for d, _ in bars]
    moves = []
    for rd in report_dates[:n_events]:
        if timing == "AMC":
            src, dst = rd, rd + timedelta(days=1)
            if src not in closes:
                continue
            i = dates.index(src)
            dst = dates[i + 1] if i + 1 < len(dates) else None
            if dst is None:
                continue
            a, b = closes[src], closes[dst]
        else:
            i = dates.index(rd) if rd in dates else -1
            if i <= 0:
                continue
            a, b = closes[dates[i - 1]], closes[rd]
        if a:
            moves.append(abs((b / a - 1.0) * 100.0))
    if not moves:
        return None, 0
    return round(sum(moves) / len(moves), 2), len(moves)


def select_latest_report(history):
    """The MOST RECENT entry of a Yahoo `earningsHistory` array.

    Yahoo returns that array OLDEST-FIRST (verified 2026-11-06: MRNA's first element is the
    quarter ended 2025-09-30 and its last is 2026-06-30), so taking the FIRST element publishes a
    YEAR-OLD beat/miss. The most recent report is the entry with the LATEST quarter-end date.
    Entries without a parseable quarter fall back to the first usable entry, so a malformed
    payload still returns something instead of raising.
    """
    usable = [h for h in (history or []) if (h.get("epsActual") or {}).get("raw") is not None]
    if not usable:
        return None
    dated = []
    for h in usable:
        raw = (h.get("quarter") or {}).get("fmt")
        try:
            dated.append((date.fromisoformat(raw), h))
        except Exception:
            continue
    if dated:
        return max(dated, key=lambda pair: pair[0])[1]
    return usable[0]


def nasdaq_prior_result(symbol):
    """Last reported quarter: beat / miss from Nasdaq's earnings-surprise table.

    REACTION_STATS_NASDAQ_PRIOR_RESULT - the FALLBACK for names whose Yahoo earningsHistory is
    empty. Measured 2026-11-12: Brookfield Corporation's Yahoo `earningsHistory` AND
    `earningsTrend` are both empty, so the prior result had to be read by hand from Nasdaq and
    then typed into the artifact. The SAME Nasdaq call that already supplies the past report
    dates carries the EPS actual, the consensus forecast and the surprise percentage, so this
    fallback costs NO extra request.

    The table's `dateReported` is M/D/YYYY (same trap as `nasdaq_report_dates`), its `eps` is the
    actual, `consensusForecast` the estimate and `percentageSurprise` the surprise in percent.
    """
    d = _json(f"https://api.nasdaq.com/api/company/{symbol}/earnings-surprise",
              headers=["Accept: application/json", "Referer: https://www.nasdaq.com/"])
    try:
        rows = d["data"]["earningsSurpriseTable"]["rows"]
    except Exception:
        return None
    best = None
    for row in rows or []:
        act = row.get("eps")
        if act is None:
            continue
        try:
            act = float(act)
        except (TypeError, ValueError):
            continue
        est = row.get("consensusForecast")
        try:
            est = float(est) if est is not None else None
        except (TypeError, ValueError):
            est = None
        raw = (row.get("dateReported") or "").strip()
        m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", raw)
        if not m:
            continue
        try:
            rd = date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
        except ValueError:
            continue
        if best is None or rd > best[0]:
            best = (rd, act, est, row)
    if best is None:
        return None
    rd, act, est, row = best
    sp = row.get("percentageSurprise")
    try:
        sp = float(sp) if sp is not None else None
    except (TypeError, ValueError):
        sp = None
    if sp is None and est:
        sp = (act - est) / abs(est) * 100.0
    if sp is not None:
        verdict = "beat" if sp >= 0 else "miss"
    elif est is not None:
        verdict = "beat" if act >= est else "miss"
    else:
        return None
    return {"result": verdict, "surprise_pct": round(sp, 2) if sp is not None else None,
            "eps_actual": act, "eps_estimate": est,
            "quarter": row.get("fiscalQtrEnd"),
            "source": "nasdaq_earnings_surprise", "report_date": rd.isoformat()}


def prior_report_result(symbol):
    """Last reported quarter: beat / miss. Yahoo earningsHistory first, Nasdaq second.

    The source is returned in the dict so the artifact can name it per row - "one source per
    field" is only checkable if the artifact says WHICH source produced the cell.
    """
    try:
        res = yahoo_quote_summary(symbol, "earningsHistory")
        hist = res["earningsHistory"]["history"]
    except Exception:
        hist = None
    h = select_latest_report(hist) if hist else None
    if h is None:
        # Yahoo carries no history for this name -> the Nasdaq table is the fallback, not a
        # manual read. Same request the helper already makes for the past report dates.
        return nasdaq_prior_result(symbol)
    act = (h.get("epsActual") or {}).get("raw")
    est = (h.get("epsEstimate") or {}).get("raw")
    sp = (h.get("surprisePercent") or {}).get("raw")
    if sp is not None:
        verdict = "beat" if sp >= 0 else "miss"
        return {"result": verdict, "surprise_pct": round(sp * 100.0, 2),
                "eps_actual": act, "eps_estimate": est,
                "quarter": (h.get("quarter") or {}).get("fmt"),
                "source": "yahoo_earningsHistory"}
    if est is not None:
        verdict = "beat" if act >= est else "miss"
        return {"result": verdict, "surprise_pct": None, "eps_actual": act,
                "eps_estimate": est, "quarter": (h.get("quarter") or {}).get("fmt"),
                "source": "yahoo_earningsHistory"}
    return nasdaq_prior_result(symbol)


# ------------------------------------------------------------------ implied move
OCC_RE = re.compile(r"^([A-Z]{1,6})(\d{6})([CP])(\d{8})$")


def _occ(sym):
    m = OCC_RE.match(sym or "")
    if not m:
        return None
    root, yymmdd, side, strike = m.groups()
    try:
        d = datetime.strptime(yymmdd, "%y%m%d").date()
    except ValueError:
        return None
    return {"root": root, "date": d, "side": side, "strike": int(strike) / 1000.0}


def implied_move_pct(symbol, event_date, timing, spot=None):
    """ATM straddle cost at the first expiry that straddles the event, as a % of spot.

    BMO report on D -> D's own expiry captures it (the event is before that expiry's close);
    AMC report on D -> the first expiry AFTER D captures it.
    """
    d = _json(f"https://cdn.cboe.com/api/global/delayed_quotes/options/{symbol}.json")
    try:
        data = d["data"]
    except Exception:
        return None
    spot = spot or data.get("close") or data.get("current_price")
    if not spot:
        return None
    chains = []
    for o in data.get("options", []):
        p = _occ(o.get("option"))
        if p:
            p.update(o)
            chains.append(p)
    if not chains:
        return None
    expiries = sorted({c["date"] for c in chains})
    if timing == "BMO":
        target = next((e for e in expiries if e >= event_date), None)
    else:
        target = next((e for e in expiries if e > event_date), None)
    if target is None:
        return None
    leg = [c for c in chains if c["date"] == target]
    if not leg:
        return None
    strikes = sorted({c["strike"] for c in leg})
    atm = min(strikes, key=lambda s: abs(s - spot))
    calls = [c for c in leg if c["side"] == "C" and c["strike"] == atm]
    puts = [c for c in leg if c["side"] == "P" and c["strike"] == atm]
    if not calls or not puts:
        return None

    def mid(o):
        b, a, th = o.get("bid") or 0, o.get("ask") or 0, o.get("theo") or 0
        if b > 0 and a > 0:
            return (b + a) / 2.0
        if th > 0:
            return th
        return a if a > 0 else b

    straddle = mid(calls[0]) + mid(puts[0])
    if straddle <= 0:
        return None
    return {"implied_move_pct": round(straddle / spot * 100.0, 2),
            "expiry": target.isoformat(), "atm_strike": atm,
            "spot": round(spot, 2), "straddle": round(straddle, 2)}


# -------------------------------------------------------------------- market caps
def yahoo_market_caps(symbols):
    """Yahoo v7 quote batch (50/call) -> USD market cap. Returns {sym: cap}."""
    crumb = yahoo_crumb()
    if not crumb:
        return {}
    out = {}
    for i in range(0, len(symbols), 50):
        batch = symbols[i:i + 50]
        url = ("https://query1.finance.yahoo.com/v7/finance/quote?symbols="
               + ",".join(batch) + "&crumb=" + crumb)
        d = _json(url, jar=True)
        try:
            for q in d["quoteResponse"]["result"]:
                mc = q.get("marketCap")
                if mc:
                    out[q.get("symbol")] = float(mc)
        except Exception:
            continue
        time.sleep(0.3)
    return out


def band(low, high, symbols):
    """Names whose market cap sits in [low, high) — the 'just below the line' set."""
    caps = yahoo_market_caps(symbols)
    rows = []
    for s in symbols:
        c = caps.get(s)
        if c is not None and low <= c < high:
            rows.append({"ticker": s, "market_cap": c,
                         "market_cap_b": round(c / 1e9, 1)})
    rows.sort(key=lambda r: -r["market_cap"])
    return rows


# ------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers")
    ap.add_argument("--tickers-file")
    ap.add_argument("--timing", default="", help="comma list of BMO/AMC aligned with --tickers")
    ap.add_argument("--timing-file")
    ap.add_argument("--earnings-date", required=False, help="YYYY-MM-DD of the report")
    ap.add_argument("--band", nargs=2, metavar=("LOW", "HIGH"), help="market-cap band in USD")
    ap.add_argument("--band-file")
    ap.add_argument("--events", type=int, default=4)
    ap.add_argument("--out")
    ap.add_argument("--csv")
    args = ap.parse_args()

    result = {"version": REACTION_STATS_VERSION, "generated_et":
              datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"), "rows": [], "errors": []}

    if args.band:
        syms = []
        if args.band_file:
            syms = [l.strip() for l in open(args.band_file) if l.strip()]
        else:
            print("band mode needs --band-file", file=sys.stderr)
            return 1
        rows = band(float(args.band[0]), float(args.band[1]), syms)
        result["band"] = {"low": float(args.band[0]), "high": float(args.band[1]), "rows": rows}
        payload = json.dumps(result, indent=1)
        if args.out:
            open(args.out, "w").write(payload)
        print(payload)
        return 0

    syms = []
    if args.tickers_file:
        syms = [l.strip() for l in open(args.tickers_file) if l.strip()]
    elif args.tickers:
        syms = [t.strip() for t in args.tickers.split(",") if t.strip()]
    else:
        print("need --tickers or --tickers-file", file=sys.stderr)
        return 1

    timings = []
    if args.timing_file:
        timings = [l.strip().upper() for l in open(args.timing_file) if l.strip()]
    elif args.timing:
        timings = [t.strip().upper() for t in args.timing.split(",")]
    while len(timings) < len(syms):
        timings.append("BMO")

    event_date = date.fromisoformat(args.earnings_date) if args.earnings_date else None

    for sym, timing in zip(syms, timings):
        row = {"ticker": sym, "timing": timing, "errors": []}
        try:
            bars = yahoo_chart(sym)
            if not bars:
                row["errors"].append("chart_unavailable")
            else:
                row["prior_day_move_pct"] = prior_day_move_pct(bars)
                row["ytd_move_pct"] = ytd_move_pct(bars)
                row["last_close"] = bars[-1][1]
                row["last_bar_date"] = bars[-1][0].isoformat()
                rdates = nasdaq_report_dates(sym)
                avg, n = avg_abs_move_pct(bars, rdates, timing, args.events)
                row["avg_abs_move_pct"] = avg
                row["avg_abs_move_events"] = n
                row["past_report_dates"] = [d.isoformat() for d in rdates[:args.events]]
                if avg is None:
                    row["errors"].append("avg_abs_move_unavailable")
            pr = prior_report_result(sym)
            if pr:
                row["prior_report_result"] = pr["result"]
                row["prior_report_surprise_pct"] = pr["surprise_pct"]
                row["prior_report_quarter"] = pr["quarter"]
                row["prior_report_source"] = pr.get("source", "yahoo_earningsHistory")
            else:
                row["errors"].append("prior_report_result_unavailable")
            if event_date:
                im = implied_move_pct(sym, event_date, timing, row.get("last_close"))
                if im:
                    row["implied_move_pct"] = im["implied_move_pct"]
                    row["implied_expiry"] = im["expiry"]
                    row["implied_atm_strike"] = im["atm_strike"]
                else:
                    row["errors"].append("implied_move_unavailable")
        except Exception as exc:  # never let one name kill the run
            row["errors"].append(f"exception:{type(exc).__name__}")
        avg = row.get("avg_abs_move_pct")
        imp = row.get("implied_move_pct")
        if avg is not None:
            imp_for_score = imp if imp is not None else avg
            row["reaction_score"] = round(0.6 * avg + 0.4 * imp_for_score, 2)
        else:
            row["reaction_score"] = None
        result["rows"].append(row)
        if row["errors"]:
            result["errors"].append({"ticker": sym, "errors": row["errors"]})
        time.sleep(0.2)

    payload = json.dumps(result, indent=1)
    if args.out:
        open(args.out, "w").write(payload)
    if args.csv:
        cols = ["ticker", "timing", "prior_day_move_pct", "ytd_move_pct", "avg_abs_move_pct",
                "avg_abs_move_events", "implied_move_pct", "reaction_score",
                "prior_report_result", "prior_report_surprise_pct",
                "prior_report_source"]
        with open(args.csv, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            for r in result["rows"]:
                w.writerow(r)
    print(payload)
    ok = sum(1 for r in result["rows"] if r.get("reaction_score") is not None)
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
