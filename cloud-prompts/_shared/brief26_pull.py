#!/usr/bin/env python3
"""
brief26_pull.py — ONE command that produces the merged table cron #26's brief is built from.

WHY THIS FILE EXISTS
--------------------
The 2026-11-12 run took ~37 assistant turns, of which the data phase was ~12, and the
whole HTTP data plane behind those 12 turns took 3.3 SECONDS. The cost was the number
of round trips, not the bandwidth. This helper collapses the data phase into one call
and, more importantly, makes the "ONE PULL PER BRIEF" rule MECHANICAL rather than a
thing the operator has to remember:

  * the ±3% band is pulled once, with `range:[0,1000]` and the scanner's own
    `totalCount` asserted on BOTH screens (a truncated band publishes floors, not
    counts — see the 2026-11-05 incident);
  * the targeted pull asks for ONLY the names the band cannot see (the watchlist's
    ETFs, the trending names outside ±3%), so the two pulls can never disagree and no
    tie-break rule is needed. On 2026-11-12 a 33-name targeted pull overlapped the band
    on 22 names, which is what forced a "which pull wins" adjudication and let a stale
    figure (MSTR) reach the prose;
  * the market cap is reconciled with the CORROBORATED source, not the median. Measured
    2026-11-12: on all six names where the three sources disagreed by >15%, Nasdaq's
    `/summary` MarketCap was the furthest from an independently verified figure, and the
    median the old rule prescribed was worse than the scanner's own number on five of
    the six (BSBR would have been published at ~$36.6bn against an actual ~$18.4bn).
    Nasdaq's MarketCap is unreliable for ADRs and complex share structures;
    stockanalysis.com publishes a DIRECT share count, which is the tiebreak — BUT only
    when the site agrees with ITSELF. A count that does not reconcile with the site's
    own market cap at the site's own price is on a different basis (ordinary shares
    against a per-ADS price) and inflates the published cap by 20x-477x, so it is
    rejected and the ADS-basis implied counts are used instead (v2, 2026-11-17);
  * the earnings roster comes from Nasdaq's own calendar, so cron #19's file being
    absent (HTTP 404) degrades the run to one substitute instead of two.

USAGE
    python3 brief26_pull.py --date 2026-11-12 --out merged.json
    python3 brief26_pull.py --date 2026-11-12 --out merged.json --extra-tickers "NBIS,NVDA"
    python3 brief26_pull.py --date 2026-11-12 --out merged.json --no-cap-reconcile

OUTPUT
    A JSON document: {"date", "pulled_at_et", "band", "rows", "earnings", "watchlist",
    "timings", "errors"} — `rows` is the merged table every table and the CSV are
    built from, keyed by the BARE ticker.

EXIT CODES
    0 = the band was pulled and the merged table was written
    3 = the band pull failed or was truncated (do NOT publish a brief from a partial
        screen — this is the 2026-11-05 failure mode)
"""
import argparse
import concurrent.futures as cf
import datetime
import zoneinfo
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request

BRIEF26_PULL_V3 = "brief26-pull-v3"

COLS = ["name", "description", "close", "change", "change_abs", "volume",
        "average_volume_30d_calc", "premarket_close", "premarket_change",
        "premarket_high", "premarket_low", "premarket_volume", "market_cap_basic",
        "sector", "exchange", "type", "halted", "premarket_time",
        "earnings_release_next_date"]
COLS_CSV = ",".join(COLS)

OUTPUTS = "https://raw.githubusercontent.com/karizaco/minimax-cloud-outputs/main"
UA_NASDAQ = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Accept": "application/json"}
UA_SA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

BAND_GAIN = {
    "filter": [
        {"left": "type", "operation": "in_range", "right": ["stock", "dr"]},
        {"left": "exchange", "operation": "in_range", "right": ["NASDAQ", "NYSE", "AMEX"]},
        {"left": "premarket_change", "operation": "in_range", "right": [3, 1000]},
        {"left": "premarket_volume", "operation": "greater", "right": 0}],
    "options": {"lang": "en"}, "markets": ["america"],
    "symbols": {"query": {"types": []}, "tickers": []},
    "columns": COLS,
    "sort": {"sortBy": "premarket_change", "sortOrder": "desc"},
    "range": [0, 1000]}

BAND_LOSE = dict(BAND_GAIN,
                 filter=[{"left": "type", "operation": "in_range", "right": ["stock", "dr"]},
                         {"left": "exchange", "operation": "in_range", "right": ["NASDAQ", "NYSE", "AMEX"]},
                         {"left": "premarket_change", "operation": "in_range", "right": [-1000, -3]},
                         {"left": "premarket_volume", "operation": "greater", "right": 0}],
                 sort={"sortBy": "premarket_change", "sortOrder": "asc"})


# THE TAIL SCREEN - the names the +/-3% band cannot see.
#
# WHY (measured 2026-11-02..2026-11-10, seven sessions, 175 top regular-session
# gainers): the band only ever fetches a name that ALREADY moved 3%. The day's
# extremes were mostly not movers before the open - 45 of the 74 absent top-25
# gainers had a pre-market gap inside +/-3% - so the band never saw them. This
# screen fetches every name with a pre-market print and a gap inside +/-15%,
# sorted by PRE-MARKET VOLUME, which is what puts the "printed hard, has not
# moved" names at the front.
#
# It does NOT affect band["complete"]: that flag is about the +/-3% counts, and
# the tail screen is truncated by design (its totalCount is far above the row
# cap), so it carries its own tail_complete flag.
BAND_TAIL = {
    "filter": [
        {"left": "type", "operation": "in_range", "right": ["stock", "dr"]},
        {"left": "exchange", "operation": "in_range", "right": ["NASDAQ", "NYSE", "AMEX"]},
        {"left": "premarket_change", "operation": "in_range", "right": [-15, 15]},
        {"left": "premarket_volume", "operation": "greater", "right": 0}],
    "options": {"lang": "en"}, "markets": ["america"],
    "symbols": {"query": {"types": []}, "tickers": []},
    "columns": COLS,
    "sort": {"sortBy": "premarket_volume", "sortOrder": "desc"},
    "range": [0, 400]}


# ------------------------------------------------------------------ utilities
# DST-AWARE: the sandbox's America/New_York DOES observe DST (2026-07-15 12:00 UTC is
# 08:00 EDT = UTC-4; 2026-11-20 12:00 UTC is 07:00 EST = UTC-5). A hardcoded -5 is an
# hour EARLY for every date from mid-March to early November.
ET = zoneinfo.ZoneInfo("America/New_York")


def now_et():
    return datetime.datetime.now(ET)


def log(msg):
    print("[brief26_pull] %s" % msg, file=sys.stderr)


def fetch_json(url, headers=None, timeout=30):
    req = urllib.request.Request(url, headers=headers or UA_NASDAQ)
    with urllib.request.urlopen(req, timeout=timeout) as fh:
        return json.loads(fh.read().decode("utf-8", "ignore"))


def fetch_text(url, timeout=30):
    req = urllib.request.Request(url, headers=UA_NASDAQ)
    with urllib.request.urlopen(req, timeout=timeout) as fh:
        return fh.read().decode("utf-8", "ignore")


def here(name):
    """Find a sibling helper wherever the caller put it.

    The routine fetches brief26_pull.py, shibui_caps.py and tv_scan.py into ONE
    directory (the SKILL says so), but the helper must also work when they land in
    different places — so look beside itself first, then in the usual spots.
    """
    cands = [os.path.join(os.path.dirname(os.path.abspath(__file__)), name),
             os.path.join("/workspace/_shared", name),
             os.path.join("/workspace/tools", name),
             os.path.join("/workspace", name)]
    for c in cands:
        if os.path.exists(c):
            return c
    return cands[0]


def run_tv(mode, body=None, names=None, out=None):
    """tv_scan.py is the validated client; reuse it rather than hand-building a body."""
    cmd = [sys.executable, here("tv_scan.py"), mode]
    if body:
        cmd += ["--body", body]
    if names:
        cmd += ["--names", names, "--columns", COLS_CSV]
    if out:
        cmd += ["--out", out]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        return None, (r.stderr or r.stdout or "exit %d" % r.returncode)[:400]
    return out, ""


def norm_rows(obj):
    """Normalise both tv_scan output shapes into a list of dicts."""
    out = []
    if isinstance(obj, dict) and "data" in obj:
        for r in obj["data"]:
            vals = r["d"] if isinstance(r, dict) and "d" in r else r
            rec = dict(zip(COLS, vals))
            rec["ticker"] = rec.get("name")
            out.append(rec)
    elif isinstance(obj, dict):
        for t, r in obj.items():
            vals = r["d"] if isinstance(r, dict) and "d" in r else r
            rec = dict(zip(COLS, vals))
            rec["ticker"] = t
            out.append(rec)
    return out


def num(v):
    try:
        return float(str(v).replace("$", "").replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------ sources
def pull_band(workdir, timings):
    """The ±3% band, both sides, with totalCount asserted."""
    band = {"gainers": [], "decliners": [], "tail": [], "complete": True,
            "tail_complete": True, "totals": {}}
    for label, body, key in (("gainers", BAND_GAIN, "gainers"), ("losers", BAND_LOSE, "decliners"),
                             ("tail", BAND_TAIL, "tail")):
        bf = os.path.join(workdir, "body_%s.json" % label)
        of = os.path.join(workdir, "band_%s.json" % label)
        with open(bf, "w") as fh:
            json.dump(body, fh)
        t0 = time.time()
        path, err = run_tv("scan", body=bf, out=of)
        timings["band_%s" % label] = round(time.time() - t0, 2)
        if not path:
            raise SystemExit("brief26_pull: the %s screen failed: %s" % (label, err))
        d = json.load(open(path))
        rows = norm_rows(d)
        total = d.get("totalCount")
        if total is not None and len(rows) != total:
            if key == "tail":
                band["tail_complete"] = False
                log("!! the tail screen returned %d rows against totalCount %d - the tail is "
                    "a FLOOR, not the whole cohort" % (len(rows), total))
            else:
                band["complete"] = False
                log("!! the %s screen returned %d rows against totalCount %d - the counts are "
                    "FLOORS" % (label, len(rows), total))
        for r in rows:
            r["screen"] = key
        band[key] = rows
        # PERSIST the scanner's own totalCount next to the row count. It used to be logged and
        # then DROPPED, so the artifact had no way to say "1000 of 1384" - and the builder
        # printed rows against themselves (a tautology) and called the band exact.
        band["totals"][key] = {"rows": len(rows), "totalCount": total}
        log("%s: %d rows (totalCount %s)" % (label, len(rows), total))
    # The truncation guard above sets complete=False, and it used to be overwritten here by an
    # unconditional `band["complete"] = True` — so a TRUNCATED band was published as complete and
    # the counts read as exact when they were floors. That is the 2026-11-05 failure mode the
    # whole `len(rows) == totalCount` assert exists to catch. (Fixed 2026-11-13.)
    return band


def pull_watchlist(timings):
    t0 = time.time()
    try:
        txt = fetch_text(OUTPUTS + "/refs/watchlist.yaml")
    except Exception as e:
        log("watchlist unavailable: %s" % e)
        return []
    timings["watchlist"] = round(time.time() - t0, 2)
    tickers = re.findall(r"^\s*-\s*ticker:\s*([A-Za-z0-9.\-]+)\s*$", txt, re.M)
    log("watchlist: %d tickers" % len(tickers))
    return tickers


def pull_targeted(names, workdir, timings):
    """A targeted pull for names the BAND cannot see. Never overlaps the band."""
    if not names:
        return [], 0
    of = os.path.join(workdir, "targeted.json")
    t0 = time.time()
    path, err = run_tv("pull", names=",".join(names), out=of)
    timings["targeted"] = round(time.time() - t0, 2)
    if not path:
        log("targeted pull failed: %s" % err)
        return [], 0
    rows = norm_rows(json.load(open(path)))
    for r in rows:
        r["screen"] = "targeted"
    log("targeted: %d names asked, %d rows" % (len(names), len(rows)))
    return rows, len(names)


def nasdaq_summary(sym):
    try:
        d = fetch_json("https://api.nasdaq.com/api/quote/%s/summary?assetclass=stocks" % sym)
        sd = (d.get("data") or {}).get("summaryData") or {}
        mc = ((sd.get("MarketCap") or {}).get("value"))
        pc = ((sd.get("PreviousClose") or {}).get("value"))
        return sym, num(mc), num(pc)
    except Exception:
        return sym, None, None


def stockanalysis_shares(sym):
    """The site's own share count — AND its own market cap and its own price.

    The count is usable only when the site agrees with ITSELF: `sharesout × price`
    must reconcile with the `marketcap` field on the SAME page. When it does not, the
    `sharesout` field is on a different basis from the price it would be multiplied by
    — for an ADR that is the ORDINARY share count against a per-ADS price — and the
    published cap comes out inflated by the ratio. Measured 2026-11-16 on the stock
    count this routine fetched: ADXN 63x, BLRX 327x, RADX 281x, IMOS 20x, and two of
    those four names passed the $100M quality gate on the inflated number.

    So the site is asked a question it can answer from one page: is the share count
    you publish the count behind the market cap you publish? The site's own implied
    count (`marketcap ÷ price`) is returned too, because on a mismatch that is the
    count the site actually used.
    """
    try:
        h = fetch_text("https://stockanalysis.com/stocks/%s/statistics/" % sym.lower(),
                       timeout=25)
    except Exception:
        return sym, None
    sh = re.search(r'id:"sharesout",title:"[^"]*",value:"[^"]*",hover:"([\d,\.]+)"', h)
    mc = re.search(r'id:"marketcap",title:"[^"]*",value:"[^"]*",hover:"([\d,\.]+)"', h)
    if not sh:
        return sym, None
    shares = num(sh.group(1))
    market_cap = num(mc.group(1)) if mc else None
    # the site's own quote blob: `p` is the last regular-session price (`pd`/`ep` are
    # the previous close and the extended-hours print, and must not be picked up)
    q = re.search(r'quote:\{([^}]*)\}', h)
    px = None
    if q:
        m = re.search(r'[,{]p:([\d.]+)', q.group(1))
        if m:
            px = num(m.group(1))
    implied = None
    if market_cap and px:
        implied = market_cap / px
    if not (shares and market_cap and px):
        status = "untestable"       # the site could not be asked the question
    elif abs(shares * px - market_cap) <= 0.25 * market_cap:
        status = "ok"               # the count IS the count behind the site's own cap
    else:
        status = "mismatch"         # the count is on a different basis from the price
    return sym, {"shares": shares, "market_cap": market_cap, "price": px,
                 "implied_shares": implied, "status": status,
                 "basis_ok": status == "ok"}


def nasdaq_earnings(date, timings):
    t0 = time.time()
    try:
        d = fetch_json("https://api.nasdaq.com/api/calendar/earnings?date=%s" % date)
    except Exception as e:
        log("earnings calendar unavailable: %s" % e)
        return {}
    timings["earnings_calendar"] = round(time.time() - t0, 2)
    out = {}
    for r in ((d.get("data") or {}).get("rows") or []):
        t = (r.get("symbol") or "").strip().upper()
        if not t:
            continue
        out[t] = {"name": r.get("name"), "time": r.get("time"),
                  "eps": r.get("epsForecast"), "market_cap": r.get("marketCap"),
                  "fiscal_quarter": r.get("fiscalQuarter")}
    log("earnings calendar: %d rows" % len(out))
    return out


# ------------------------------------------------------------------ cap reconciliation
def reconcile_caps(rows, as_of, timings, use_shibui=True, use_stockanalysis=True):
    """Publish the CORROBORATED cap, not the median.

    The three sources each imply a SHARE COUNT for the same session:
        implied_scanner = market_cap_basic / close
        implied_nasdaq  = nasdaq_market_cap / nasdaq_previous_close
        implied_shibui  = shibui_market_cap / close          (same basis as the scanner)
    and stockanalysis.com publishes the share count DIRECTLY, which is the only
    uncorrupted tiebreak. The published cap is always shares x the session close, so
    it is on the gate's basis by construction and cannot go stale like a cached
    market-cap field can.
    """
    cand = [r for r in rows if r.get("market_cap_basic") and r.get("close")]
    if not cand:
        return {}
    syms = [r["ticker"] for r in cand]

    t0 = time.time()
    nq = {}
    with cf.ThreadPoolExecutor(max_workers=12) as ex:
        for sym, mc, pc in ex.map(nasdaq_summary, syms):
            nq[sym] = (mc, pc)
    timings["nasdaq_summary"] = round(time.time() - t0, 2)
    log("nasdaq /summary: %d/%d resolved" % (sum(1 for v in nq.values() if v[0]), len(syms)))

    flagged = []
    for r in cand:
        t = r["ticker"]
        sc = r["market_cap_basic"] / r["close"]
        ncap, nprev = nq.get(t, (None, None))
        nsh = (ncap / nprev) if (ncap and nprev) else None
        if nsh and abs(nsh - sc) / sc > 0.15:
            flagged.append(t)
        r["implied_shares_scanner"] = sc
        r["implied_shares_nasdaq"] = nsh
    log("cap disagreement >15%%: %d names -> %s" % (len(flagged), flagged[:12]))

    shib = {}
    if use_shibui and flagged:
        t0 = time.time()
        try:
            r = subprocess.run([sys.executable, here("shibui_caps.py"),
                                "--tickers", ",".join(flagged), "--date", as_of],
                               capture_output=True, text=True, timeout=180)
            d = json.loads(r.stdout)
            for row in d.get("rows", []):
                shib[row["ticker"]] = row
            log("shibui: %d/%d flagged names" % (len(shib), len(flagged)))
        except Exception as e:
            log("shibui unavailable: %s" % e)
        timings["shibui_caps"] = round(time.time() - t0, 2)

    sa = {}
    if use_stockanalysis and flagged:
        t0 = time.time()
        with cf.ThreadPoolExecutor(max_workers=6) as ex:
            for sym, sh in ex.map(stockanalysis_shares, flagged):
                if sh:
                    sa[sym] = sh
        timings["stockanalysis"] = round(time.time() - t0, 2)
        log("stockanalysis: %d/%d flagged names" % (len(sa), len(flagged)))

    basis_mismatch = []
    for r in cand:
        t = r["ticker"]
        close = r["close"]
        sc_sh = r.get("implied_shares_scanner")
        n_sh = r.get("implied_shares_nasdaq")
        s_row = shib.get(t)
        s_sh = (s_row["market_cap"] / close) if (s_row and close) else None
        r["implied_shares_shibui"] = s_sh
        r["market_cap_nasdaq"] = nq.get(t, (None, None))[0]
        r["market_cap_shibui"] = s_row["market_cap"] if s_row else None
        site = sa.get(t)
        r["shares_outstanding_sa"] = (site or {}).get("shares")
        r["stockanalysis_market_cap"] = (site or {}).get("market_cap")
        r["stockanalysis_price"] = (site or {}).get("price")
        r["stockanalysis_implied_shares"] = (site or {}).get("implied_shares")
        r["cap_basis_mismatch"] = False

        if t not in flagged:
            r["market_cap_published"] = r["market_cap_basic"]
            r["cap_source"] = "scanner"
            continue

        # THE CAP RULE, in the order that matters:
        #   1. stockanalysis's own count is usable when the site agrees with ITSELF
        #      (count x its own price == its own market cap) - that is a count
        #      corroborated by two of the site's own fields;
        #   2. when the site DISAGREES with itself the count is on a different basis
        #      from the price (ordinary shares against a per-ADS price), so it is not
        #      used at all: the ADS-basis implied counts are the candidates and their
        #      median is published, and the name is FLAGGED as a basis mismatch;
        #   3. when the site could not be READ the count is UNAVAILABLE, not wrong -
        #      the median is published and the name is NOT flagged as a mismatch,
        #      because "we could not ask" is not "the source disagrees".
        # A flagged row always carries at least two implied counts (the scanner's and
        # Nasdaq's), so the median always exists - there is no third branch.
        imp = sorted([x for x in (sc_sh, s_sh, n_sh) if x])
        if len(imp) % 2:
            median = imp[len(imp) // 2]
        else:
            # the textbook median of an even-length list is the MEAN of the two
            # middle values - taking the upper one (what this code used to do) biases
            # every two-source name towards the HIGHER share count, and therefore
            # towards a HIGHER market cap and an easier pass on the $100M gate.
            median = (imp[len(imp) // 2 - 1] + imp[len(imp) // 2]) / 2.0

        # THE SITE'S COUNT IS REJECTED ONLY WHEN IT IS AN OUTLIER ON THE WRONG SIDE.
        #
        # The site publishes a share count that is sometimes the ORDINARY count and
        # sometimes the ADS count, and its own market cap is sometimes on the other
        # basis - so "the site disagrees with itself" does NOT tell you which of its
        # two fields is wrong. Measured 2026-11-16:
        #   ADXN   site's count 127,410,834 (ORDINARY) vs the ADS-basis counts
        #          0.95M/1.20M/1.52M -> the site's count is 106x too big, and the
        #          published cap came out 106x too big (a $4.9M shell at $517M);
        #   SKHY   site's count 722,000,000 (ADS, 1 ADS = 1/10 common) vs the
        #          ordinary-basis counts 5.00B/6.86B/7.11B -> the site's count is 7x
        #          SMALLER, and it is the RIGHT one ($95B, corroborated by SK hynix's
        #          own ADR ratio and its 6.9bn FY2025 weighted-average count).
        # The asymmetry is the rule: an ADS-equivalent count can never EXCEED the
        # ordinary count (1 ADS = N ordinary, N >= 1), so a count that sits far ABOVE
        # every other source's count cannot be the ADS count - it is the ordinary one.
        # A count that sits far BELOW them is the ADS count and is kept.
        #
        # So the site's count is rejected iff it is more than 2x the median implied
        # count AND it disagrees with EVERY implied count by more than 2x (no other
        # source corroborates it). Then the ADS-basis implied counts are published.
        site_shares = (site or {}).get("shares")
        rejected = False
        if site_shares and median:
            too_big = site_shares > 2.0 * median
            uncorroborated = all(site_shares > 2.0 * x for x in imp)
            if too_big and uncorroborated:
                rejected = True
        if site and site.get("shares") and not rejected:
            shares = site["shares"]
            r["cap_source"] = "stockanalysis_shares x close"
        else:
            shares = median
            if rejected:
                r["cap_source"] = ("median implied shares x close "
                                    "(stockanalysis count rejected: ordinary-share basis)")
                r["cap_basis_mismatch"] = True
                basis_mismatch.append(t)
            else:
                r["cap_source"] = "median implied shares x close (stockanalysis unavailable)"
        r["market_cap_published"] = (shares * close) if (shares and close) else r["market_cap_basic"]
    return {"flagged": flagged, "nasdaq_resolved": sum(1 for v in nq.values() if v[0]),
            "shibui_resolved": len(shib), "stockanalysis_resolved": len(sa),
            "basis_mismatch": basis_mismatch}


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser(description="the merged table for cron #26")
    ap.add_argument("--date", required=True, help="the brief's date (YYYY-MM-DD)")
    ap.add_argument("--out", required=True, help="write the merged table here")
    ap.add_argument("--workdir", default=None)
    ap.add_argument("--extra-tickers", default="",
                    help="comma-separated names to price outside the band "
                         "(the StockTwits list, the earnings names)")
    ap.add_argument("--no-cap-reconcile", action="store_true")
    ap.add_argument("--no-earnings", action="store_true")
    args = ap.parse_args()

    t_start = time.time()
    workdir = args.workdir or tempfile.mkdtemp(prefix="brief26_")
    os.makedirs(workdir, exist_ok=True)
    timings, errors = {}, []

    # A BASIS GUARD. During the pre-market the scanner's `close` is the last completed
    # session's close, which is the basis every published number assumes. Once the
    # regular session is live the scanner serves the LIVE price in `close`, so the cap
    # reconciliation and every "prior close" in the brief would be computed against a
    # price that is not a close. The routine runs at 08:30 ET; this says so out loud
    # rather than producing a plausible-looking artifact on the wrong basis.
    et = now_et()
    in_session = (et.weekday() < 5 and et.hour >= 9 and (et.hour, et.minute) >= (9, 30)
                  and (et.hour, et.minute) <= (16, 0))
    if in_session:
        msg = ("the regular session is LIVE (%s ET) - the scanner's `close` is the live "
               "price, not the prior close, so the cap basis and every published prior "
               "close are wrong. Run this at 08:30 ET." % et.strftime("%H:%M"))
        errors.append(msg)
        log("!! " + msg)

    band = pull_band(workdir, timings)
    band_names = {r["ticker"] for r in band["gainers"] + band["decliners"] + band["tail"]}
    log("band: %d gainers, %d decliners, %d tail, complete=%s tail_complete=%s"
        % (len(band["gainers"]), len(band["decliners"]), len(band["tail"]),
           band["complete"], band["tail_complete"]))

    watch = pull_watchlist(timings)
    extra = [t.strip().upper() for t in (args.extra_tickers or "").split(",") if t.strip()]
    want = []
    for t in watch + extra:
        if t and t not in band_names and t not in want:
            want.append(t)
    targeted, asked = pull_targeted(want, workdir, timings)

    merged = {}
    # The TAIL goes in FIRST so a name the +/-3% band also carried keeps the band's
    # row (and its "band" screen tag) - the tail screen is the wider net, not a
    # replacement for the band.
    for r in band["tail"] + band["gainers"] + band["decliners"] + targeted:
        merged[r["ticker"]] = r
    rows = list(merged.values())
    log("merged: %d names (%d from the band, %d targeted)"
        % (len(rows), len(band_names), len(targeted)))

    capmeta = {}
    if not args.no_cap_reconcile:
        try:
            capmeta = reconcile_caps(rows, args.date, timings)
        except Exception as e:
            errors.append("cap reconciliation failed: %s" % e)
            log("cap reconciliation failed: %s" % e)
    else:
        for r in rows:
            r["market_cap_published"] = r.get("market_cap_basic")
            r["cap_source"] = "scanner (reconciliation skipped)"
    # a name with no cap at all (a fund, a name with no price) carries an empty cap,
    # not a silently-absent one
    for r in rows:
        if not r.get("market_cap_basic"):
            r["market_cap_published"] = None
            r["cap_source"] = "no cap published (no market_cap_basic)"

    earnings = {} if args.no_earnings else nasdaq_earnings(args.date, timings)

    out = {
        "date": args.date,
        "pulled_at_et": now_et().strftime("%Y-%m-%d %H:%M:%S"),
        "marker": BRIEF26_PULL_V3,
        "band": {"gainers": len(band["gainers"]), "decliners": len(band["decliners"]),
                 "complete": band["complete"], "totals": band.get("totals", {})},
        "band_gainers": [r["ticker"] for r in band["gainers"]],
        "band_decliners": [r["ticker"] for r in band["decliners"]],
        "targeted_asked": asked, "targeted_returned": len(targeted),
        "watchlist": watch,
        "cap_meta": capmeta,
        "rows": rows,
        "earnings": earnings,
        "timings": timings,
        "errors": errors,
        "elapsed_s": round(time.time() - t_start, 2),
    }
    with open(args.out, "w") as fh:
        json.dump(out, fh, indent=1, default=str)
    log("wrote %s — %d rows, %.1fs total" % (args.out, len(rows), out["elapsed_s"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
