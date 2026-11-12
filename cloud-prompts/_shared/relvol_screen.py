#!/usr/bin/env python3
"""RELVOL_SCREEN_V1 — unusual options flow by RELATIVE volume.

Replaces the absolute-volume ranking of cron #16 with size-normalised measures, so a
$1.8B name can outrank a $5.2T one. Also emits the legacy absolute "series book" on the
routine's original 8-name universe, so the published put/call series stays comparable.

Sources
  chain    : Cboe delayed-quote option-chain CDN  (https://cdn.cboe.com/api/global/delayed_quotes/options/<SYM>.json)
  universe : TradingView america scanner (top-N by cash volume)
  cash vol : TradingView america scanner (volume column)
  baseline : Cboe historical options volume, all_symbols monthly file (previous + current month)

Usage
  python3 relvol_screen.py --date YYYY-MM-DD --out /workspace/options-flow/YYYY-MM-DD.md
                            [--universe 60] [--jobs 8] [--keep-raw DIR]
"""
import argparse, csv, collections, datetime, json, math, os, re, statistics, subprocess, sys, tempfile
from concurrent.futures import ThreadPoolExecutor

RELVOL_SCREEN_V1 = 1
# ENGINE_REV=2 — adds the universe-labelled front matter, the bias-tag self-check that ABORTS the
# write on a contradiction, the wide book (legacy method over the relative screen's universe) and
# the Pass A watchlist leg. The RELVOL_SCREEN_V1 marker is unchanged on purpose: the fetch ladder
# checks it, so it must stay exactly as it is. ENGINE_REV is the ADDITIONAL token a fetch must
# demand, so a copy of this file from before rev 2 cannot win the ladder.
ENGINE_REV = 2
# COLUMN_CONTRACT — the LAYOUT contract of the published tables, introduced 2026-11-12 on the
# user's request: the expiry date always gets its OWN column (ticker | side | strike | expiry),
# never a packed cell ("C 16.5 · 11-20", "NVDA P 175 2026-11-11"). The leader tables already
# followed it; the contrast table did not and now does.
#
# WHY ENGINE_REV STAYS 2: the deployed prompt's fetch ladder demands `ENGINE_REV=2` literally
# (cloud-prompts/cron-prompts/16-unusual-options-flow-daily.md). A rev-3 file would be REJECTED by
# that ladder on every URL, the engine would fall through to the legacy 8-name fallback, and the
# headline relative screen would silently disappear from the fleet — a layout request must never
# cost the headline. This change is purely additive and produces IDENTICAL NUMBERS, so a stale
# rev-2 copy differs only in table layout; the checker (tools/check_options_flow_artifact.py,
# clause F) catches that one-fire deviation instead of a marker. Bumping the rev requires a PROMPT
# redeploy in the same change — do them together or not at all.
COLUMN_CONTRACT = "expiry-column-v1"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
OCC = re.compile(r"^([A-Z]{1,6})(\d{2})(\d{2})(\d{2})([CP])(\d{8})$")
TV_URL = "https://scanner.tradingview.com/america/scan"
CBOE_CHAIN = "https://cdn.cboe.com/api/global/delayed_quotes/options/{sym}.json"
CBOE_MONTH = ("https://www.cboe.com/us/options/market_statistics/historical_data/download/all_symbols/"
              "?reportType=volume&month={m}&year={y}&volumeType=sum&volumeAggType=daily"
              "&exchanges=CBOE&exchanges=BATS&exchanges=C2&exchanges=EDGX")
REFERER = "https://www.cboe.com/us/options/market_statistics/historical_data/"

PASS_B = ["IWM", "GLD", "TLT", "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN"]
NAMES = {"IWM": "iShares Russell 2000 ETF", "GLD": "SPDR Gold Shares",
         "TLT": "iShares 20+ Year Treasury ETF", "AAPL": "Apple Inc.", "MSFT": "Microsoft Corp.",
         "NVDA": "NVIDIA Corp.", "GOOGL": "Alphabet Inc. (Class A)", "AMZN": "Amazon.com Inc."}

# The user's watchlist is a PUBLISHED FILE, fetched at run time (the local research/watchlist.yaml
# on the Mavis host is unreachable from the Cloud runtime — that is why Pass A never ran).
WATCHLIST_URLS = [
    "https://api.github.com/repos/karizaco/minimax-cloud-outputs/contents/refs/watchlist.yaml?ref=main",
    "https://raw.githubusercontent.com/karizaco/minimax-cloud-outputs/main/refs/watchlist.yaml",
    "https://cdn.jsdelivr.net/gh/karizaco/minimax-cloud-outputs@main/refs/watchlist.yaml",
]

# Bias tag thresholds — FIXED, and never taken from the previous artifact's tag.
# The tag names the side that DOMINATES the ratio, so a LOW put/call ratio is a CALL tag.
BIAS_CALL_BELOW, BIAS_PUT_ABOVE = 0.85, 1.20

# filters
MIN_VOL, MIN_THEO, MIN_VOI, MAX_DTE = 1000, 0.05, 1.0, 60
PEER_MIN_VOL = 50          # a "meaningfully traded" strike for the peer median
N_EXPIRIES = 4              # window = 4 earliest LISTED expiries per name
LEGACY_TOPN = 10           # series book: per-underlying top-N by volume
LEGACY_MIN_VOL, LEGACY_MIN_VOI, LEGACY_MAX_DTE = 200, 1.0, 60
EXCLUDE = {"SPY", "QQQ", "SOXL", "SOXS", "SMH", "TQQQ", "SQQQ", "UVXY", "VXX"}

errors = []          # real source failures (a name with no listed series is NOT a failure)
no_series = []       # symbols the Cboe CDN refuses: no listed options series


def curl(url, headers=None, data=None, timeout=60, retries=1):
    cmd = ["curl", "-sL", "--max-time", str(timeout), "-H", f"User-Agent: {UA}"]
    for h in (headers or []):
        cmd += ["-H", h]
    if data is not None:
        cmd += ["-X", "POST", "-H", "Content-Type: application/json", "--data-binary", data]
    cmd.append(url)
    last = None
    for _ in range(retries + 1):
        p = subprocess.run(cmd, capture_output=True)
        if p.returncode == 0 and p.stdout:
            return p.stdout
        last = p.stderr.decode(errors="replace")[:200]
    raise RuntimeError(f"curl failed: {last}")


def log(msg):
    print(f"[relvol] {msg}", file=sys.stderr, flush=True)


def curl_status(url, timeout=30):
    """HTTP status of a URL, or None. Used to tell "the watchlist is not published" (404) from
    "the fetch failed" (anything else)."""
    try:
        p = subprocess.run(["curl", "-sL", "--max-time", str(timeout), "-o", "/dev/null",
                            "-w", "%{http_code}", "-H", f"User-Agent: {UA}", url],
                           capture_output=True)
        code = p.stdout.decode(errors="replace").strip()
        return int(code) if code.isdigit() else None
    except Exception:
        return None


# ---------------------------------------------------------------- universe
def build_universe(n_top):
    """TradingView top-N by cash volume + the routine's Pass-B 8."""
    payload = {
        "filter": [
            {"left": "type", "operation": "in_range", "right": ["stock", "dr"]},
            {"left": "exchange", "operation": "in_range", "right": ["NASDAQ", "NYSE", "AMEX"]},
            {"left": "close", "operation": "greater", "right": 1},
        ],
        "options": {"lang": "en"},
        "symbols": {"query": {"types": []}, "tickers": []},
        "columns": ["name", "description", "close", "volume", "market_cap_basic", "sector", "exchange"],
        "sort": {"sortBy": "volume", "sortOrder": "desc"},
        "range": [0, n_top - 1],
    }
    uni, tv_rows = {}, 0
    try:
        raw = curl(TV_URL, headers=["Origin: https://www.tradingview.com", "Content-Type: application/json"],
                   data=json.dumps(payload), timeout=45)
        j = json.loads(raw)
        for it in j.get("data", []):
            v = it.get("d") or it.get("v") or []
            if len(v) < 5:
                continue
            sym = v[0]
            if sym in EXCLUDE:
                continue
            uni[sym] = dict(name=v[1], close=v[2], share_vol=v[3], mcap=v[4],
                            sector=v[5] if len(v) > 5 else None,
                            exchange=v[6] if len(v) > 6 else None, src="tv_top_volume")
            tv_rows += 1
    except Exception as e:
        errors.append(f"tradingview_universe:{type(e).__name__}")
        log(f"universe scan failed: {e}")
    # the Pass-B ETFs are funds, so the stock scan above misses them - ask for them by name
    try:
        payload2 = {
            "filter": [{"left": "name", "operation": "in_range", "right": PASS_B}],
            "options": {"lang": "en"},
            "symbols": {"query": {"types": []}, "tickers": []},
            "columns": ["name", "description", "close", "volume", "market_cap_basic", "sector", "exchange"],
            "range": [0, 20],
        }
        raw2 = curl(TV_URL, headers=["Origin: https://www.tradingview.com",
                                     "Content-Type: application/json"],
                    data=json.dumps(payload2), timeout=45)
        for it in json.loads(raw2).get("data", []):
            v = it.get("d") or it.get("v") or []
            if len(v) < 5:
                continue
            sym = v[0]
            if sym in uni and uni[sym].get("share_vol") is None:
                uni[sym].update(share_vol=v[3], close=v[2], mcap=v[4], name=v[1] or uni[sym]["name"])
    except Exception as e:
        errors.append(f"tradingview_passB:{type(e).__name__}")
        log(f"pass-B cash-volume lookup failed: {e}")
    for s in PASS_B:
        uni.setdefault(s, dict(name=NAMES.get(s, s), close=None, share_vol=None, mcap=None,
                                sector=None, exchange=None, src="passB"))
    log(f"universe: {len(uni)} symbols ({tv_rows} from TV, {len(PASS_B)} pass-B)")
    return uni


# ---------------------------------------------------------------- chains
def fetch_chain(sym):
    try:
        raw = curl(CBOE_CHAIN.format(sym=sym), timeout=90)
        if raw[:5] == b"<?xml":
            raise ValueError("no_listed_series (CDN AccessDenied)")
        j = json.loads(raw)
        opts = (j.get("data") or {}).get("options")
        if not isinstance(opts, list):
            raise ValueError("no options list")
        return sym, j, None
    except Exception as e:
        return sym, None, f"{type(e).__name__}:{str(e)[:80]}"


def parse_chain(sym, j):
    d = j.get("data") or {}
    rows = []
    for o in d.get("options") or []:
        s = o.get("option", "")
        m = OCC.match(s)
        if not m:
            continue
        try:
            exp = datetime.date(2000 + int(m.group(2)), int(m.group(3)), int(m.group(4)))
        except ValueError:
            continue
        vol = float(o.get("volume") or 0)
        oi = float(o.get("open_interest") or 0)
        iv = float(o.get("iv") or 0)
        rows.append(dict(sym=sym, contract=s, side=m.group(5), strike=int(m.group(6)) / 1000.0,
                         expiry=exp.isoformat(), vol=vol, oi=oi, theo=float(o.get("theo") or 0),
                         iv=(iv * 100 if iv > 0 else None),
                         last=float(o.get("last_trade_price") or 0),
                         bid=float(o.get("bid") or 0), ask=float(o.get("ask") or 0),
                         voi=(vol / oi if oi > 0 else None)))
    return dict(sym=sym, close=d.get("close"), prev=d.get("prev_day_close"),
                pct=d.get("price_change_percent"), uv=d.get("volume"),
                cur=d.get("current_price"), ts=j.get("timestamp"), rows=rows)


def chain_session_date(names):
    """The session the chains actually hold: modal date of contract last_trade_time."""
    votes = collections.Counter()
    for n in names.values():
        for r in n["rows"][:4000]:
            lt = r.get("lt")
            if lt:
                votes[lt[:10]] += 1
    return votes.most_common(1)[0][0] if votes else None


# ---------------------------------------------------------------- baseline
def fetch_month_hist(months):
    """Cboe all_symbols monthly files -> {underlying: {date: volume}}."""
    hist = collections.defaultdict(lambda: collections.defaultdict(int))
    ok = 0
    for (y, m) in months:
        try:
            raw = curl(CBOE_MONTH.format(m=m, y=y), headers=[f"Referer: {REFERER}"], timeout=120)
            txt = raw.decode("utf-8", "replace")
            if "Trade Date" not in txt[:200]:
                raise ValueError("not a csv")
            for row in csv.reader(txt.splitlines()):
                if len(row) > 5 and row[0][:2] == "20":
                    try:
                        hist[row[2]][row[0]] += int(row[5])
                    except ValueError:
                        pass
            ok += 1
        except Exception as e:
            errors.append(f"cboe_hist_{y}_{m:02d}:{type(e).__name__}")
            log(f"historical month {y}-{m:02d} failed: {e}")
    return hist, ok


def own_history(hist, sessions_before, n_avg=10):
    """per-underlying: last published session volume / mean of its own prior n_avg sessions."""
    out = {}
    for sym, by in hist.items():
        ds = sorted(by)
        if len(ds) < 3:
            continue
        base = ds[-1]
        prior = [d for d in ds[:-1]][-n_avg:]
        if not prior:
            continue
        avg = sum(by[d] for d in prior) / len(prior)
        out[sym] = dict(base=base, base_val=by[base], avg10=avg,
                        ratio=(by[base] / avg if avg else None), n_prior=len(prior))
    return out


# ---------------------------------------------------------------- metrics
def zassign(items, getter):
    vals = []
    for c in items:
        v = getter(c)
        vals.append(math.log10(v) if (v and v > 0) else None)
    good = [v for v in vals if v is not None]
    if len(good) < 3:
        for c in items:
            c["_z"] = 0.0
        return
    m = statistics.mean(good)
    sd = statistics.pstdev(good) or 1.0
    for c, v in zip(items, vals):
        c["_z"] = 0.0 if v is None else (v - m) / sd


def pfmt(v):
    """signed percent for an optional value"""
    return "n/a" if v is None else f"{v:+.1f}%"


def sfmt(v):
    """share volume for an optional value"""
    return "n/a" if v is None else f"{v:,.0f}"


def mfmt(v):
    """market cap for an optional value (None -> ETF), in RAW DOLLARS.

    FIX 2026-11-05: thousands separator added. A $5.0T cap printed as "$5001.5B",
    which reads like a typo. The value was right; the format was not.
    """
    if not v:
        return "ETF"
    return "$" + format(v / 1e9, ",.1f") + "B"


def money(strike, side, spot):
    if not spot:
        return "n/a", 0.0
    m = (strike - spot) / spot if side == "C" else (spot - strike) / spot
    return ("OTM" if m > 0 else "ITM"), m * 100


# ---------------------------------------------------------------- bias tag
def tag_from_ratio(ratio):
    """The FIXED bias-tag rule: the tag names the side that DOMINATES the ratio.

    put/call < 0.85 -> CALL, > 1.20 -> PUT, otherwise MIXED.
    """
    if ratio is None:
        return "MIXED"
    if ratio < BIAS_CALL_BELOW:
        return "CALL"
    if ratio > BIAS_PUT_ABOVE:
        return "PUT"
    return "MIXED"


class BiasTagMismatch(Exception):
    """A published tag contradicts the ratio it was derived from. Hard error: never publish it."""


def audit_bias_tag(rows, label, published_tag, published_ratio):
    """Re-derive the bias tag from the ROWS and compare it with the published tag.

    This is deliberately a second, independent derivation: `slice_stats` computes the tag
    from the same ratio it publishes, so comparing those two values could never fail. Here
    the tag is re-derived from the row set itself, so a bug in the stats path (a ratio
    computed over the wrong population, a tag copied from another slice) is caught.

    A mismatch is a HARD ERROR: the artifact is NOT written.
    """
    c = sum(r["vol"] for r in rows if r["side"] == "C")
    p = sum(r["vol"] for r in rows if r["side"] == "P")
    ratio = (p / c) if c else float("inf")
    expected = tag_from_ratio(ratio)
    if expected != published_tag or abs(ratio - published_ratio) > 0.005:
        raise BiasTagMismatch(
            f"{label}: published tag {published_tag} / ratio {published_ratio:.4f} but the rows "
            f"re-derive to {expected} / {ratio:.4f} (calls {c:,.0f}, puts {p:,.0f})")
    return expected


# ---------------------------------------------------------------- legacy method
def legacy_rows(names_map, syms, session):
    """The legacy (series) method: per-underlying top-N by volume, 4 earliest listed expiries,
    V/OI >= 1.0, volume >= 200, DTE <= 60. Shared by the series book, the wide book and Pass A so
    the three differ ONLY in their population."""
    out = []
    for s in syms:
        n = names_map.get(s)
        if not n:
            continue
        wset = set(n["window"])
        cand = [r for r in n["rows"] if r["expiry"] in wset and r["vol"] >= 100]
        cand.sort(key=lambda r: -r["vol"])
        for r in cand[:LEGACY_TOPN]:
            rr = dict(r)
            rr["dte"] = (datetime.date.fromisoformat(r["expiry"]) - session).days
            out.append(rr)
    out = [r for r in out if r["voi"] is not None and r["voi"] >= LEGACY_MIN_VOI
           and r["vol"] >= LEGACY_MIN_VOL and r["dte"] <= LEGACY_MAX_DTE]
    out.sort(key=lambda r: -r["voi"])
    return out


# ---------------------------------------------------------------- watchlist (Pass A)
def fetch_watchlist():
    """Fetch the PUBLISHED watchlist. Returns (tickers, status).

    status is one of: 'ok', 'absent' (404 everywhere), 'error'.
    """
    for u in WATCHLIST_URLS:
        raw = curl(u, headers=["Accept: application/vnd.github.raw"], timeout=30)
        if not raw:
            continue
        text = raw.decode("utf-8", "replace")
        if '"message"' in text[:200] and "ticker" not in text:
            continue                      # the contents API's 404/error envelope
        tickers = parse_watchlist(text)
        if tickers:
            return tickers, "ok"
    # did any URL answer 404?
    for u in WATCHLIST_URLS:
        code = curl_status(u)
        if code == 200:
            return [], "error"
    return [], "absent"


def parse_watchlist(text):
    """Parse the published watchlist YAML. Supports both shapes the fleet has used:
    a top-level `tickers:` list of plain symbols, and a `watchlist:` list of maps with a
    `ticker:` key."""
    tickers, in_watchlist = [], False
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.strip().startswith("#"):
            continue
        stripped = line.strip()
        if re.match(r"^[A-Za-z_][\w-]*:\s*$", stripped):
            in_watchlist = stripped.split(":")[0].strip() in ("watchlist", "tickers")
            continue
        if stripped.startswith("- "):
            body = stripped[2:].strip()
            if in_watchlist and re.fullmatch(r"[A-Za-z0-9.\-]+", body):
                tickers.append(body.upper())
                continue
            m = re.match(r"ticker:\s*([A-Za-z0-9.\-]+)", body)
            if in_watchlist and m:
                tickers.append(m.group(1).upper())
            continue
        if in_watchlist:
            m = re.match(r"ticker:\s*([A-Za-z0-9.\-]+)", stripped)
            if m:
                tickers.append(m.group(1).upper())
            elif re.fullmatch(r"[A-Za-z0-9.\-]+", stripped):
                tickers.append(stripped.upper())
    seen, out = set(), []
    for t in tickers:
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


# ---------------------------------------------------------------- main
def self_test():
    """Prove the bias-tag self-check BITES. A guard that cannot fail is decoration.

    Synthetic rows, no network: a wrong tag must raise, the right tag must pass.
    """
    def row(side, vol):
        return dict(side=side, vol=vol, theo=1.0, oi=10, voi=1.0, dte=1,
                    expiry="2026-11-10", strike=100.0, iv=30.0, sym="TEST")
    cases = [
        ("call-heavy", [row("C", 1000), row("P", 500)], 0.50, "CALL"),     # ratio < 0.85
        ("put-heavy", [row("C", 500), row("P", 1000)], 2.00, "PUT"),      # ratio > 1.20
        ("mixed", [row("C", 1000), row("P", 1000)], 1.00, "MIXED"),       # in between
    ]
    for label, rows, ratio, tag in cases:
        c = sum(r["vol"] for r in rows if r["side"] == "C")
        p = sum(r["vol"] for r in rows if r["side"] == "P")
        assert abs((p / c) - ratio) < 1e-9, f"{label}: fixture ratio wrong"
        assert tag_from_ratio(ratio) == tag, f"{label}: tag_from_ratio wrong"
        # the CORRECT tag passes
        audit_bias_tag(rows, label, tag, ratio)
        # the INVERTED tag must raise — this is the 2026-11-02 bug class
        wrong = {"CALL": "PUT", "PUT": "CALL", "MIXED": "PUT"}[tag]
        try:
            audit_bias_tag(rows, label, wrong, ratio)
        except BiasTagMismatch:
            pass
        else:
            print(f"self-test FAILED: {label} — a wrong tag ({wrong}) was accepted", file=sys.stderr)
            return 1
    print(json.dumps({"self_test": "passed", "cases": [c[0] for c in cases],
                      "engine_rev": ENGINE_REV, "marker": "RELVOL_SCREEN_V1"}, indent=1))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="session date YYYY-MM-DD (the fire's scheduled date)")
    ap.add_argument("--out")
    ap.add_argument("--universe", type=int, default=60)
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--keep-raw", default=None)
    ap.add_argument("--self-test", action="store_true",
                    help="run the bias-tag self-check unit test and exit (no network)")
    args = ap.parse_args()
    if args.self_test:
        return self_test()

    session = datetime.date.fromisoformat(args.date)
    uni = build_universe(args.universe)
    if not uni:
        print(json.dumps({"ok": False, "errors": errors})); return 2

    log(f"fetching {len(uni)} chains ...")
    chains = {}
    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        for sym, j, err in ex.map(fetch_chain, list(uni)):
            if err:
                if "no_listed_series" in err:
                    no_series.append(sym)
                    log(f"chain {sym}: no listed options series (CDN AccessDenied)")
                else:
                    errors.append(f"chain_{sym}:{err.split(':')[0]}")
                    log(f"chain {sym} FAILED {err}")
                continue
            chains[sym] = parse_chain(sym, j)
    names = {s: dict(uni[s], **{k: v for k, v in c.items() if k != "rows"})
             for s, c in chains.items()}
    for s in names:
        names[s]["rows"] = chains[s]["rows"]
    log(f"chains ok: {len(names)}/{len(uni)}")

    # baseline: previous + current month
    months = sorted({(session.year, session.month), ((session - datetime.timedelta(days=32)).year,
                                                      (session - datetime.timedelta(days=32)).month)})
    hist, ok_months = fetch_month_hist(months)
    own = own_history(hist, session)
    log(f"historical months ok: {ok_months}; symbols with baseline: {len(own)}")

    # ---- per-name aggregates + contract-level relative metrics (whole window) ----
    cont = []
    for s, n in names.items():
        rows = n["rows"]
        n["chain_vol"] = sum(r["vol"] for r in rows)
        n["window"] = sorted({r["expiry"] for r in rows})[:N_EXPIRIES]
        wset = set(n["window"])
        groups = collections.defaultdict(list)
        for r in rows:
            if r["vol"] >= PEER_MIN_VOL:
                groups[(r["expiry"], r["side"])].append(r["vol"])
        med = {k: statistics.median(v) for k, v in groups.items()}
        gvol = collections.defaultdict(float)
        for r in rows:
            gvol[(r["expiry"], r["side"])] += r["vol"]
        share = n.get("share_vol")
        for r in rows:
            if r["expiry"] not in wset:
                continue
            key = (r["expiry"], r["side"])
            pm = med.get(key, 0)
            r["dte"] = (datetime.date.fromisoformat(r["expiry"]) - session).days
            r["peer_ratio"] = (r["vol"] / pm) if pm > 0 else None
            r["grp_med"] = pm
            r["grp_n"] = len(groups.get(key, []))
            r["expiry_share"] = (r["vol"] / gvol[key]) if gvol[key] else None
            r["chain_share"] = (r["vol"] / n["chain_vol"]) if n["chain_vol"] else None
            r["opt_intensity"] = (r["vol"] / share) if share else None
            cont.append(r)
    for s, n in names.items():
        n["name_opt_intensity"] = (n["chain_vol"] / n["share_vol"]) if n.get("share_vol") else None

    elig = [c for c in cont if c["vol"] >= MIN_VOL and c["theo"] >= MIN_THEO
            and c["voi"] is not None and c["voi"] >= MIN_VOI and c["dte"] <= MAX_DTE
            and (datetime.date.fromisoformat(c["expiry"]) - session).days <= MAX_DTE]
    for c in elig:
        n = names[c["sym"]]
        c["dte"] = (datetime.date.fromisoformat(c["expiry"]) - session).days
        c["name"] = n["name"]; c["mcap"] = n.get("mcap"); c["share_vol"] = n.get("share_vol")
        c["close"] = n.get("close"); c["pct"] = n.get("pct"); c["chain_vol"] = n["chain_vol"]
        c["noic"] = n.get("name_opt_intensity")
        h = own.get(c["sym"], {})
        c["h_ratio"] = h.get("ratio"); c["h_base"] = h.get("base")
        c["h_base_val"] = h.get("base_val"); c["h_avg"] = h.get("avg10")
    for k, g in (("peer_ratio", lambda c: c["peer_ratio"]),
                 ("expiry_share", lambda c: c["expiry_share"]),
                 ("opt_intensity", lambda c: c["opt_intensity"]),
                 ("voi", lambda c: c["voi"]),
                 ("h_ratio", lambda c: c["h_ratio"])):
        zassign(elig, g)
        for c in elig:
            c["z_" + k] = c.pop("_z")
    for c in elig:
        c["score"] = (c["z_peer_ratio"] + c["z_expiry_share"] + c["z_opt_intensity"]
                      + c["z_voi"] + 1.5 * c["z_h_ratio"])

    by_score = sorted(elig, key=lambda c: -c["score"])
    by_abs = sorted(elig, key=lambda c: -c["vol"])
    multi = [c for c in by_score if c["dte"] >= 1]

    # ---- Pass A: the user's PUBLISHED watchlist (fetched at run time) ----
    # The local research/watchlist.yaml lives on the Mavis host and is unreachable from the Cloud
    # runtime, so this leg never ran there. The watchlist is now a published file, so Pass A is a
    # real pass: it is scanned with the legacy method and published with its own ratios.
    def slice_stats(rows):
        c = sum(r["vol"] for r in rows if r["side"] == "C")
        p = sum(r["vol"] for r in rows if r["side"] == "P")
        ratio = (p / c) if c else float("inf")
        tag = tag_from_ratio(ratio)
        pc = sum(r["vol"] * r["theo"] for r in rows if r["side"] == "C")
        pp = sum(r["vol"] * r["theo"] for r in rows if r["side"] == "P")
        return dict(rows=len(rows), c=int(c), p=int(p), ratio=ratio, tag=tag,
                    pc=pc, pp=pp, pr=(pp / pc if pc else None))

    wl_tickers, wl_status = fetch_watchlist()
    wl_tickers = [t for t in wl_tickers if t not in EXCLUDE]
    wl_names = {}
    pa_missing = []
    if wl_status == "ok" and wl_tickers:
        extra = [t for t in wl_tickers if t not in names]
        log(f"watchlist: {len(wl_tickers)} tickers ({len(extra)} outside the relative universe)")
        if extra:
            with ThreadPoolExecutor(max_workers=args.jobs) as ex:
                for sym, j, err in ex.map(fetch_chain, extra):
                    if err:
                        if "no_listed_series" in err:
                            pa_missing.append(sym)
                        else:
                            errors.append(f"watchlist_chain_{sym}:{err.split(':')[0]}")
                        continue
                    c = parse_chain(sym, j)
                    c["window"] = sorted({r["expiry"] for r in c["rows"]})[:N_EXPIRIES]
                    wl_names[sym] = c
        for t in wl_tickers:
            if t in names:
                wl_names[t] = names[t]
    pass_a_rows = legacy_rows(wl_names, wl_tickers, session) if wl_tickers else []
    pass_a_stats = slice_stats(pass_a_rows) if pass_a_rows else None
    pass_a_econ = slice_stats([r for r in pass_a_rows if r["theo"] >= 0.05]) if pass_a_rows else None

    # ---- legacy series book (continuity): PASS_B, top-N by volume, old filters ----
    leg = legacy_rows(names, PASS_B, session)

    # ---- wide book: the SAME legacy method over the relative screen's whole universe ----
    # Two populations, one headline is the failure this fixes: the series book's ratio describes 8
    # mega-caps, the relative screen describes ~60 names. The wide book is the same method over
    # the wider population, so the reader can compare like with like. It does NOT replace the
    # series book (that one carries the published series since 2026-10-16).
    wide = legacy_rows(names, list(names.keys()), session)
    wide_stats = slice_stats(wide)
    wide_econ = slice_stats([r for r in wide if r["theo"] >= 0.05])

    leg_stats = slice_stats(leg)
    leg_econ = slice_stats([r for r in leg if r["theo"] >= 0.05])
    leg_oif = slice_stats([r for r in leg if r["oi"] >= 50])
    penny = [r for r in leg if r["theo"] < 0.05]
    penny_share = (sum(r["vol"] for r in penny) / sum(r["vol"] for r in leg)) if leg else 0


    # ---- name-level tables ----
    nr = []
    for s, n in names.items():
        h = own.get(s)
        if not h or not h.get("ratio"):
            continue
        nr.append(dict(ratio=h["ratio"], sym=s, name=n["name"], base=h["base"],
                       base_val=h["base_val"], avg=h["avg10"], chain=n["chain_vol"],
                       share=n.get("share_vol"), optint=n.get("name_opt_intensity"),
                       mcap=n.get("mcap"), pct=n.get("pct")))
    nr.sort(key=lambda x: -x["ratio"])
    ni = sorted([x for x in nr if x["optint"]], key=lambda x: -x["optint"])

    # ---------------- artifact ----------------
    L = []
    W = L.append
    base_dates = sorted({h["base"] for h in own.values()})
    base_date = base_dates[-1] if base_dates else "n/a"

    leg_pr = leg_stats["pr"]
    leg_pr_s = f"{leg_pr:.2f}" if leg_pr is not None else "n/a"
    W(f"# Unusual options flow by RELATIVE volume — {args.date} "
      f"({session.strftime('%A')}, US cash session close 16:00 ET)\n")
    W("```")
    W(f"date: {args.date}")
    W("cron: 16-unusual-options-flow-daily")
    W("method: RELATIVE volume screen (size-normalised) — HEADLINE; the legacy absolute series book is secondary")
    W(f"engine: relvol_screen.py v{RELVOL_SCREEN_V1} rev{ENGINE_REV}")
    W(f"column_contract: {COLUMN_CONTRACT} — every contract table gives the expiry date its OWN "
      f"column (ticker | side | strike | expiry); no cell packs side + strike + date")
    W(f"headline_metric: the relative-volume screen (own-history + peer ratio, size-normalised) — "
      f"NOT a put/call ratio")
    W(f"relative_screen_universe: top {args.universe} US names by cash volume (TradingView america scanner) "
      f"+ the {len(PASS_B)} routine names — {len(names)} underlyings with a chain, {len(uni)-len(names)} without")
    W(f"series_book_universe: the {len(PASS_B)} Pass-B mega-caps ({', '.join(PASS_B)}) — legacy absolute "
      f"method, continuity with the published put/call series since 2026-10-16")
    W(f"series_book_bias: {leg_stats['tag']} (put/call {leg_stats['ratio']:.2f}) — contract-count ratio on "
      f"series_book_universe")
    W(f"series_book_economic_bias: {leg_econ['tag']} (put/call {leg_econ['ratio']:.2f}) — theo >= $0.05 slice "
      f"on series_book_universe")
    W(f"series_book_premium_ratio: {leg_pr_s} — premium-dollar ratio on series_book_universe")
    W(f"wide_book_universe: the {len(names)}-name relative-screen universe — the SAME legacy absolute method "
      f"applied to it (population-matched read for the series book)")
    W(f"wide_book_bias: {wide_stats['tag']} (put/call {wide_stats['ratio']:.2f}) — contract-count ratio on "
      f"wide_book_universe")
    W(f"wide_book_economic_bias: {wide_econ['tag']} (put/call {wide_econ['ratio']:.2f}) — theo >= $0.05 slice "
      f"on wide_book_universe")
    if pass_a_stats:
        W(f"pass_a_universe: the published watchlist (refs/watchlist.yaml) — {len(wl_tickers)} tickers "
          f"({', '.join(wl_tickers)}), scanned with the legacy absolute method")
        W(f"pass_a_bias: {pass_a_stats['tag']} (put/call {pass_a_stats['ratio']:.2f}) — contract-count ratio "
          f"on pass_a_universe")
    else:
        W(f"pass_a_universe: none — the published watchlist is "
          f"{'absent (HTTP 404) so Pass A was omitted' if wl_status == 'absent' else 'unavailable'}, "
          f"so Pass A was omitted rather than faked")
    W(f"bias_tag_thresholds: put/call < {BIAS_CALL_BELOW} -> CALL, > {BIAS_PUT_ABOVE} -> PUT, else MIXED "
      f"(the tag names the DOMINATING side)")
    W(f"contracts_in_window: {len(cont):,} (4 earliest listed expiries per name) | eligible: {len(elig):,}")
    W(f"filters: volume >= {MIN_VOL:,}, theo >= ${MIN_THEO}, V/OI >= {MIN_VOI}, DTE <= {MAX_DTE}")
    W("composite: z(peer_ratio) + z(expiry_share) + z(opt_pct_cash) + z(V/OI) + 1.5*z(own_history)")
    W("chain_source: Cboe delayed-quote option-chain CDN")
    W("universe_source: TradingView america scanner (top-N by cash volume)")
    W(f"baseline_source: Cboe historical options volume (all_symbols, {len(months)} monthly files) — "
      f"own-history measured on {base_date}")
    W(f"status: {'ok' if not errors else 'degraded'}"
      + (f" (no listed options series for: {', '.join(sorted(no_series))})" if no_series else ""))
    W("```\n")


    W("## Headline — relative-volume leaders, multi-day book (DTE ≥ 1)\n")
    W("Ranked by the composite relative score. Same-day expiry flow on an event day is dominated by the "
      "mega-caps; the multi-day book is where positioning accumulates — and it is where the relative "
      "screen and the absolute screen diverge most.\n")
    W("| Ticker | Side | Strike | Expiry | DTE | Volume | Open int | V/OI | Peer ratio | Share of expiry | "
      "Share of chain | Peer med vol | Day move | Opt % of cash | Own-hist | Theo | Moneyness | Mkt cap |")
    W("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for c in multi[:20]:
        lab, m = money(c["strike"], c["side"], c["close"])
        W(f"| {c['sym']} | {c['side']} | {c['strike']:g} | {c['expiry']} | {c['dte']} | {int(c['vol']):,} | "
          f"{int(c['oi']):,} | {c['voi']:.1f} | {c['peer_ratio']:.1f}x | {c['expiry_share']*100:.1f}% | "
          f"{c['chain_share']*100:.2f}% | {c['grp_med']:,.0f} | {pfmt(c['pct'])} | "
          f"{(c['opt_intensity'] or 0)*100:.3f}% | {c['h_ratio']:.2f}x | {c['theo']:.3f} | {lab} {m:+.1f}% | "
          f"{mfmt(c['mcap'])} |")
    W("")
    W("## Relative-volume leaders — all expiries (0DTE included)\n")
    W("| Ticker | Side | Strike | Expiry | DTE | Volume | Open int | V/OI | Peer ratio | Share of expiry | "
      "Share of chain | Peer med vol | Day move | Opt % of cash | Own-hist | Theo | Moneyness | Mkt cap |")
    W("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for c in by_score[:15]:
        lab, m = money(c["strike"], c["side"], c["close"])
        W(f"| {c['sym']} | {c['side']} | {c['strike']:g} | {c['expiry']} | {c['dte']} | {int(c['vol']):,} | "
          f"{int(c['oi']):,} | {c['voi']:.1f} | {c['peer_ratio']:.1f}x | {c['expiry_share']*100:.1f}% | "
          f"{c['chain_share']*100:.2f}% | {c['grp_med']:,.0f} | {pfmt(c['pct'])} | "
          f"{(c['opt_intensity'] or 0)*100:.3f}% | {c['h_ratio']:.2f}x | {c['theo']:.3f} | {lab} {m:+.1f}% | "
          f"{mfmt(c['mcap'])} |")
    W("")
    W("## Name level — options activity vs the name's own 10-session baseline\n")
    W(f"Last session published by Cboe's historical service: **{base_date}** (the service lags the live "
      "session by about a day, so the baseline is one session behind the contract screen — it is labelled "
      "on every row). This is the measure with no size dependence at all.\n")
    W("| Ticker | Name | Own-history ratio | Day move | Baseline options vol | Own 10-session avg | "
      "Chain vol | Cash vol | Opt % of cash | Mkt cap |")
    W("|---|---|---|---|---|---|---|---|---|---|")
    for r in nr[:20]:
        W(f"| {r['sym']} | {r['name'][:28]} | **{r['ratio']:.2f}x** | {pfmt(r['pct'])} | {r['base_val']:,.0f} | "
          f"{r['avg']:,.0f} | {r['chain']:,.0f} | {sfmt(r['share'])} | {(r['optint'] or 0)*100:.2f}% | "
          f"{mfmt(r['mcap'])} |")
    W("")
    W("**And the names that look loud on absolute volume but are quiet against their own history:**\n")
    W("| Ticker | Name | Own-history ratio | Day move | Baseline options vol | Own 10-session avg | Mkt cap |")
    W("|---|---|---|---|---|---|---|")
    for r in nr[-8:][::-1]:
        W(f"| {r['sym']} | {r['name'][:28]} | {r['ratio']:.2f}x | {pfmt(r['pct'])} | {r['base_val']:,.0f} | "
          f"{r['avg']:,.0f} | {mfmt(r['mcap'])} |")
    W("")
    W("## Name level — options contracts vs cash shares traded\n")
    W("Cross-name normaliser: how much of the name's actual share turnover is expressed in options.\n")
    W("| Ticker | Name | Opt contracts | Cash shares | Opt % of cash | Mkt cap |")
    W("|---|---|---|---|---|---|")
    for r in ni[:15]:
        W(f"| {r['sym']} | {r['name'][:28]} | {r['chain']:,.0f} | {sfmt(r['share'])} | "
          f"{(r['optint'] or 0)*100:.2f}% | {mfmt(r['mcap'])} |")
    W("")
    W("## Contrast — the absolute screen vs the relative screen\n")
    # The expiry date gets its OWN column on both sides. A packed cell ("NVDA P 175 2026-11-11")
    # cannot be sorted, filtered or read on its own, and the two sides then cannot be compared
    # cell by cell. This is the same column contract the leader tables above already follow.
    W("| Rank | Abs ticker | Side | Strike | Expiry | Volume | Rel ticker | Side | Strike | Expiry | "
      "Peer ratio | Share of expiry |")
    W("|---|---|---|---|---|---|---|---|---|---|---|---|")
    a10, r10 = by_abs[:10], multi[:10]
    for i in range(min(len(a10), len(r10))):
        a, b = a10[i], r10[i]
        W(f"| {i+1} | {a['sym']} | {a['side']} | {a['strike']:g} | {a['expiry']} | {int(a['vol']):,} | "
          f"{b['sym']} | {b['side']} | {b['strike']:g} | {b['expiry']} | {b['peer_ratio']:.0f}x | "
          f"{b['expiry_share']*100:.0f}% |")
    W("")
    if min(len(a10), len(r10)) < 10:
        W(f"_Only {min(len(a10), len(r10))} rows were available on each side of this comparison._\n")
    ov = len({c["sym"] for c in a10} & {c["sym"] for c in r10})
    W(f"**Overlap between the two top-10s: {ov} of 10 names.** The absolute screen is a roster of size; "
      "the relative screen is a roster of anomaly.\n")

    W("## Series book (absolute method) — continuity with the published put/call series\n")
    W(f"**Universe: the {len(PASS_B)} Pass-B mega-caps ({', '.join(PASS_B)}).** Every ratio in this "
      f"section describes THOSE {len(PASS_B)} names and nothing else — it is not the relative screen's "
      f"population. The legacy method, unchanged: per-underlying top-{LEGACY_TOPN} by volume, 4 earliest "
      f"listed expiries, V/OI ≥ {LEGACY_MIN_VOI}, volume ≥ {LEGACY_MIN_VOL}, DTE ≤ {LEGACY_MAX_DTE}. "
      f"**Bias tag: {leg_stats['tag']}** (put/call {leg_stats['ratio']:.2f}), thresholds "
      f"< {BIAS_CALL_BELOW} → CALL, > {BIAS_PUT_ABOVE} → PUT, else MIXED.\n")
    W("| Slice | Universe | Rows | Call volume | Put volume | P/C | Tag |")
    W("|---|---|---|---|---|---|---|")
    W(f"| All kept (series method) | {len(PASS_B)} Pass-B mega-caps | {leg_stats['rows']} | {leg_stats['c']:,} | {leg_stats['p']:,} | "
      f"{leg_stats['ratio']:.2f} | **{leg_stats['tag']}** |")
    W(f"| Economic flow (theo >= $0.05) | {len(PASS_B)} Pass-B mega-caps | {leg_econ['rows']} | {leg_econ['c']:,} | {leg_econ['p']:,} | "
      f"{leg_econ['ratio']:.2f} | **{leg_econ['tag']}** |")
    W(f"| Open-interest floor (OI >= 50) | {len(PASS_B)} Pass-B mega-caps | {leg_oif['rows']} | {leg_oif['c']:,} | {leg_oif['p']:,} | "
      f"{leg_oif['ratio']:.2f} | **{leg_oif['tag']}** |")
    W("")
    itm_prem = sum(r["vol"] * r["theo"] for r in leg if (
        (r["side"] == "C" and r["strike"] < (names[r["sym"]].get("close") or 1e9))
        or (r["side"] == "P" and r["strike"] > (names[r["sym"]].get("close") or -1e9))))
    all_prem = sum(r["vol"] * r["theo"] for r in leg)
    itm_share = (itm_prem / all_prem) if all_prem else None
    if leg_stats["pr"] is not None:
        W(f"**Premium-dollar read:** ${leg_stats['pc']:,.0f} of calls against ${leg_stats['pp']:,.0f} of "
          f"puts — a put/call premium ratio of {leg_stats['pr']:.2f}"
          + (f", and {itm_share*100:.1f}% of all premium changed hands in ITM contracts" if itm_share is not None else "")
          + ". "
          f"{penny_share*100:.1f}% of kept volume sits in contracts with a theoretical value below $0.05 "
          "(real contracts, trivial premium dollars) — publish both numbers, never the contract-count tag "
          "alone on a day when they disagree.\n")
    W("**Series book — top 10 strikes by V/OI:**\n")
    W("| Ticker | Side | Strike | Expiry | DTE | Volume | Open int | V/OI | IV | Moneyness | Theo |")
    W("|---|---|---|---|---|---|---|---|---|---|---|")
    for r in leg[:10]:
        lab, m = money(r["strike"], r["side"], names[r["sym"]].get("close"))
        W(f"| {r['sym']} | {r['side']} | {r['strike']:g} | {r['expiry']} | {r['dte']} | {int(r['vol']):,} | "
          f"{int(r['oi']):,} | {r['voi']:.1f} | {('n/a' if r['iv'] is None else format(r['iv'],'.1f')+'%')} | "
          f"{lab} {m:+.1f}% | {r['theo']:.3f} |")
    W("")
    W(f"_Series book: {leg_stats['rows']} rows / {leg_stats['c']+leg_stats['p']:,} contracts._\n")

    W("## Wide book — the same method over the relative screen's universe\n")
    W(f"**Universe: the {len(names)}-name relative-screen universe** (the top {args.universe} US names by "
      f"cash volume plus the {len(PASS_B)} routine names). This is the SAME legacy absolute method as "
      f"the series book above — per-underlying top-{LEGACY_TOPN} by volume, 4 earliest listed expiries, "
      f"V/OI ≥ {LEGACY_MIN_VOI}, volume ≥ {LEGACY_MIN_VOL}, DTE ≤ {LEGACY_MAX_DTE} — applied to the wide "
      f"population. Only the POPULATION differs from the series book, so the two rows are comparable: the "
      f"series book answers \"what did the {len(PASS_B)} mega-caps do\", the wide book answers \"what did "
      f"the market's most-traded {len(names)} names do\". It does NOT replace the series book, which carries "
      f"the published put/call series since 2026-10-16.\n")
    W("| Slice | Universe | Rows | Call volume | Put volume | P/C | Tag |")
    W("|---|---|---|---|---|---|---|")
    W(f"| All kept (legacy method, wide universe) | {len(names)} names | {wide_stats['rows']} | "
      f"{wide_stats['c']:,} | {wide_stats['p']:,} | {wide_stats['ratio']:.2f} | **{wide_stats['tag']}** |")
    W(f"| Economic flow (theo >= $0.05) | {len(names)} names | {wide_econ['rows']} | {wide_econ['c']:,} | "
      f"{wide_econ['p']:,} | {wide_econ['ratio']:.2f} | **{wide_econ['tag']}** |")
    W("")
    W(f"**Reading the two books together:** series book (the {len(PASS_B)} mega-caps) put/call "
      f"{leg_stats['ratio']:.2f} → **{leg_stats['tag']}**; wide book (the {len(names)} most-traded names) "
      f"put/call {wide_stats['ratio']:.2f} → **{wide_stats['tag']}**. A reader who sees only one of these "
      f"numbers is reading one population and will assume it is the market.\n")

    W("## Pass A — the published watchlist\n")
    if pass_a_stats:
        W(f"**Universe: the published watchlist** (`refs/watchlist.yaml` in the outputs repo) — "
          f"{len(wl_tickers)} tickers: {', '.join(wl_tickers)}. Scanned with the same legacy absolute method "
          f"(per-underlying top-{LEGACY_TOPN} by volume, 4 earliest listed expiries, V/OI ≥ {LEGACY_MIN_VOI}, "
          f"volume ≥ {LEGACY_MIN_VOL}, DTE ≤ {LEGACY_MAX_DTE}). This leg used to be omitted entirely, "
          f"because the watchlist only existed as a local file on the Mavis host; it is now fetched at run "
          f"time, so Pass A is a real pass.\n")
        W("| Slice | Universe | Rows | Call volume | Put volume | P/C | Tag |")
        W("|---|---|---|---|---|---|---|")
        W(f"| All kept (legacy method) | {len(wl_tickers)} watchlist names | {pass_a_stats['rows']} | "
          f"{pass_a_stats['c']:,} | {pass_a_stats['p']:,} | {pass_a_stats['ratio']:.2f} | "
          f"**{pass_a_stats['tag']}** |")
        if pass_a_econ:
            W(f"| Economic flow (theo >= $0.05) | {len(wl_tickers)} watchlist names | {pass_a_econ['rows']} | "
              f"{pass_a_econ['c']:,} | {pass_a_econ['p']:,} | {pass_a_econ['ratio']:.2f} | "
              f"**{pass_a_econ['tag']}** |")
        W("")
        W("**Pass A — top 10 strikes by V/OI:**\n")
        W("| Ticker | Side | Strike | Expiry | DTE | Volume | Open int | V/OI | IV | Theo |")
        W("|---|---|---|---|---|---|---|---|---|---|")
        for r in pass_a_rows[:10]:
            W(f"| {r['sym']} | {r['side']} | {r['strike']:g} | {r['expiry']} | {r['dte']} | "
              f"{int(r['vol']):,} | {int(r['oi']):,} | {r['voi']:.1f} | "
              f"{('n/a' if r['iv'] is None else format(r['iv'],'.1f')+'%')} | {r['theo']:.3f} |")
        W("")
        if pa_missing:
            W(f"_Watchlist names with no listed options series: {', '.join(sorted(pa_missing))}._\n")
    else:
        W(f"**Pass A was omitted.** The published watchlist (`refs/watchlist.yaml`) is "
          f"{'not published (HTTP 404)' if wl_status == 'absent' else 'unavailable'}, so there is no "
          f"watchlist population to report. Pass A is a real pass or it is absent — it is never faked with "
          f"an invented list, and no ratio is published for it.\n")

    no_pct = [s for s, n in names.items() if n.get("pct") is None]
    if no_pct:
        W(f"**Names with no daily move in the chain (`price_change_percent` null): {', '.join(sorted(no_pct))}.**\n")
    W("## Source health\n")
    W("| Source | URL / query | Status | Result |")
    W("|---|---|---|---|")
    W(f"| Cboe delayed-quote option chain | `https://cdn.cboe.com/api/global/delayed_quotes/options/{{SYM}}.json` | "
      f"{'ok' if len(names) == len(uni) else 'partial'} ({len(names)}/{len(uni)}) | "
      f"{sum(len(n['rows']) for n in names.values()):,} contracts parsed; "
      f"{len(uni)-len(names)} names without a chain: {', '.join(sorted(set(uni)-set(names))) or 'none'} "
      f"({len(no_series)} of them have no listed options series: {', '.join(sorted(no_series)) or 'none'}) |")
    W(f"| Cboe historical options volume (all_symbols) | `.../download/all_symbols/?reportType=volume&month=..&year=..` | "
      f"{'ok' if ok_months else 'failed'} | own-history baselines for {len(own)} underlyings; baseline session "
      f"{base_date}; monthly files: {', '.join(f'{y}-{m:02d}' for y, m in months)} |")
    W("| TradingView america scanner | `POST https://scanner.tradingview.com/america/scan` | "
      f"{'ok' if any(u['src']=='tv_top_volume' for u in uni.values()) else 'failed'} | universe + cash volume + "
      "market cap |")
    W("| Yahoo options chain (cross-check) | not fetched by the engine | skipped | the engine's contract layer is "
      "single-tape (Cboe); Yahoo remains the cross-check for a manual verification |")
    W(f"| Published watchlist (Pass A) | `refs/watchlist.yaml` in `karizaco/minimax-cloud-outputs` | "
      f"{'ok' if pass_a_stats else ('absent (HTTP 404)' if wl_status == 'absent' else 'unavailable')} | "
      f"{f'{len(wl_tickers)} tickers: ' + ', '.join(wl_tickers) if wl_tickers else 'Pass A omitted — no watchlist published'}"
      + (f"; no listed options series: {', '.join(sorted(pa_missing))}" if pa_missing else "") + " |")
    W("")
    if errors:
        W(f"**Source failures ({len(errors)}):** " + "; ".join(errors[:12]) + "\n")

    W("## Caveats\n")
    W(f"1. **The own-history baseline is a 4-venue number and it lags the live session.** Cboe's historical "
      f"service covers only the Cboe-operated venues (CBOE, BATS, C2, EDGX) while the chain covers every US "
      f"venue, so the *ratio* is internally consistent (4-venue vs 4-venue) but the absolute volumes are a "
      f"different universe from the chain column beside them. The service also publishes the current session "
      f"with a lag, so the baseline here is measured on {base_date} while the contract screen is "
      f"{args.date} — one session apart, labelled on every row.")
    W(f"2. **The peer median is over strikes with volume >= {PEER_MIN_VOL}.** Including the long tail of "
      "near-dead strikes would inflate every peer ratio; excluding them would suppress it. The group median "
      "and group size are published on every row so the ratio is auditable.")
    W("3. **A ratio on a trivial number is still a trivial number.** A high own-history ratio can rest on a "
      "few hundred contracts — always read the ratio next to the volume.")
    W("4. **The composite is an ensemble, not a statistic.** Every component is published per row so the "
      "ranking can be re-derived or re-weighted; a single-metric view is a sort away.")
    W("5. **V/OI is an upper bound on a gap day.** Cboe's open interest is the prior session's settled OI "
      "while the volume is today's session, so V/OI is inflated by construction when fresh positions open "
      "all session. The OI >= 50 slice in the series book exists for this reason.")
    W("6. **0DTE IV is degenerate after the close** and the 0DTE rows in the all-expiries table inherit it; "
      "the multi-day table is the interpretable one.")
    W("7. **Deep-ITM rows are often closing trades, not bets** — a large theoretical value with V/OI near 1 "
      "and a big open interest is the signature.")
    W("8. **The universe is the most-traded names, not the whole market** — a relative screen over a fixed "
      "universe can only find anomalies inside it.")
    W("9. **Three populations, three named books.** The relative screen covers the "
      f"{len(names)}-name relative-screen universe, the series book the {len(PASS_B)} Pass-B mega-caps, and "
      "Pass A the published watchlist. Their ratios describe different populations and are not "
      "interchangeable — which is why every ratio in this file names its universe.")
    W("")

    # The audit line the spec requires (cron #16's audit line carries the bias tag, so it must
    # carry the universe too — a tag without its population is the 2026-11-02 failure class).
    W(f"`unusual-options-flow target=options-flow:{args.date} underlyings={len(names)} "
      f"strikes_kept={leg_stats['rows']} bias={leg_stats['tag']} method=relative "
      f"bias_universe=pass-b-{len(PASS_B)}-mega-caps relative_universe=top-{args.universe}-us-by-cash-volume "
      f"wide_bias={wide_stats['tag']} pass_a_bias={(pass_a_stats['tag'] if pass_a_stats else 'none')}`")
    W("")

    # ---- THE SELF-CHECK: a tag that contradicts its own ratio is a HARD ERROR ----
    # Nothing is written until every published tag has been re-derived from its own rows. The 2026-11-02
    # artifact shipped a tag that contradicted its ratio (0.84 tagged PUT) and the series has been
    # re-read off that file ever since; a mismatch aborts the write rather than publishing it again.
    try:
        audit_bias_tag(leg, "series_book (all kept)", leg_stats["tag"], leg_stats["ratio"])
        audit_bias_tag([r for r in leg if r["theo"] >= 0.05], "series_book (economic slice)",
                       leg_econ["tag"], leg_econ["ratio"])
        audit_bias_tag([r for r in leg if r["oi"] >= 50], "series_book (OI floor)",
                       leg_oif["tag"], leg_oif["ratio"])
        audit_bias_tag(wide, "wide_book (all kept)", wide_stats["tag"], wide_stats["ratio"])
        audit_bias_tag([r for r in wide if r["theo"] >= 0.05], "wide_book (economic slice)",
                       wide_econ["tag"], wide_econ["ratio"])
        if pass_a_stats:
            audit_bias_tag(pass_a_rows, "pass_a (all kept)", pass_a_stats["tag"], pass_a_stats["ratio"])
            audit_bias_tag([r for r in pass_a_rows if r["theo"] >= 0.05], "pass_a (economic slice)",
                           pass_a_econ["tag"], pass_a_econ["ratio"])
    except BiasTagMismatch as e:
        log(f"BIAS TAG SELF-CHECK FAILED: {e}")
        print(json.dumps({"ok": False, "error": "bias_tag_mismatch", "detail": str(e),
                          "out": None, "errors": errors}, indent=1))
        print("BIAS-TAG SELF-CHECK FAILED — the artifact was NOT written. "
              "A tag that contradicts its own ratio is never published.", file=sys.stderr)
        return 3

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    open(args.out, "w").write("\n".join(L))

    if args.keep_raw:
        os.makedirs(args.keep_raw, exist_ok=True)
        json.dump({"uni": uni, "names": {k: {kk: vv for kk, vv in v.items() if kk != "rows"}
                                         for k, v in names.items()},
                   "own": own, "eligible": elig, "legacy": leg,
                   "errors": errors}, open(os.path.join(args.keep_raw, "relvol_raw.json"), "w"), default=str)

    print(json.dumps({"ok": True, "out": args.out, "underlyings": len(names), "universe": len(uni),
                      "chains_failed": sorted(set(uni) - set(names)),
                      "no_listed_series": sorted(no_series),
                      "itm_premium_share": (round(itm_share, 4) if itm_share is not None else None),
                      "contracts_in_window": len(cont), "eligible": len(elig),
                      "multi_day": len(multi), "baseline_session": base_date,
                      "baseline_symbols": len(own),
                      "series_bias": leg_stats["tag"], "series_ratio": round(leg_stats["ratio"], 2),
                      "series_rows": leg_stats["rows"],
                      "series_universe": "the 8 Pass-B mega-caps (" + ", ".join(PASS_B) + ")",
                      "series_premium_ratio": (round(leg_stats["pr"], 2) if leg_stats["pr"] is not None else None),
                      "series_econ_bias": leg_econ["tag"], "series_econ_ratio": round(leg_econ["ratio"], 2),
                      "wide_bias": wide_stats["tag"], "wide_ratio": round(wide_stats["ratio"], 2),
                      "wide_rows": wide_stats["rows"],
                      "wide_universe": f"the {len(names)}-name relative-screen universe",
                      "wide_econ_bias": wide_econ["tag"], "wide_econ_ratio": round(wide_econ["ratio"], 2),
                      "pass_a_status": wl_status,
                      "pass_a_universe": (", ".join(wl_tickers) if wl_tickers else None),
                      "pass_a_bias": (pass_a_stats["tag"] if pass_a_stats else None),
                      "pass_a_ratio": (round(pass_a_stats["ratio"], 2) if pass_a_stats else None),
                      "bias_tag_thresholds": f"<{BIAS_CALL_BELOW}=CALL, >{BIAS_PUT_ABOVE}=PUT, else MIXED",
                      "bias_tag_selfcheck": "passed",
                      "top_relative": [f"{c['sym']} {c['side']} {c['strike']:g} {c['expiry']}"
                                       for c in multi[:8]],
                      "top_own_history": [f"{r['sym']} {r['ratio']:.2f}x" for r in nr[:8]],
                      "errors": errors}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
