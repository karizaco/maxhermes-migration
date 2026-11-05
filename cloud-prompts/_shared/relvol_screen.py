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
    """market cap for an optional value (None -> ETF)"""
    if not v:
        return "ETF"
    return "$" + format(v / 1e9, ".1f") + "B"


def money(strike, side, spot):
    if not spot:
        return "n/a", 0.0
    m = (strike - spot) / spot if side == "C" else (spot - strike) / spot
    return ("OTM" if m > 0 else "ITM"), m * 100


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="session date YYYY-MM-DD (the fire's scheduled date)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--universe", type=int, default=60)
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--keep-raw", default=None)
    args = ap.parse_args()

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

    # ---- legacy series book (continuity): PASS_B, top-N by volume, old filters ----
    leg = []
    for s in PASS_B:
        if s not in names:
            continue
        n = names[s]
        wset = set(n["window"])
        cand = [r for r in n["rows"] if r["expiry"] in wset and r["vol"] >= 100]
        cand.sort(key=lambda r: -r["vol"])
        for r in cand[:LEGACY_TOPN]:
            r = dict(r)
            r["dte"] = (datetime.date.fromisoformat(r["expiry"]) - session).days
            leg.append(r)
    leg = [r for r in leg if r["voi"] is not None and r["voi"] >= LEGACY_MIN_VOI
           and r["vol"] >= LEGACY_MIN_VOL and r["dte"] <= LEGACY_MAX_DTE]
    leg.sort(key=lambda r: -r["voi"])

    def slice_stats(rows):
        c = sum(r["vol"] for r in rows if r["side"] == "C")
        p = sum(r["vol"] for r in rows if r["side"] == "P")
        ratio = (p / c) if c else float("inf")
        tag = "CALL" if ratio < 0.85 else ("PUT" if ratio > 1.20 else "MIXED")
        pc = sum(r["vol"] * r["theo"] for r in rows if r["side"] == "C")
        pp = sum(r["vol"] * r["theo"] for r in rows if r["side"] == "P")
        return dict(rows=len(rows), c=int(c), p=int(p), ratio=ratio, tag=tag,
                    pc=pc, pp=pp, pr=(pp / pc if pc else None))

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
                       mcap=(n.get("mcap") or 0) / 1e9, pct=n.get("pct")))
    nr.sort(key=lambda x: -x["ratio"])
    ni = sorted([x for x in nr if x["optint"]], key=lambda x: -x["optint"])

    # ---------------- artifact ----------------
    L = []
    W = L.append
    base_dates = sorted({h["base"] for h in own.values()})
    base_date = base_dates[-1] if base_dates else "n/a"

    W(f"# Unusual options flow by RELATIVE volume — {args.date} "
      f"({session.strftime('%A')}, US cash session close 16:00 ET)\n")
    W("```")
    W(f"date: {args.date}")
    W("cron: 16-unusual-options-flow-daily")
    W("method: RELATIVE volume screen (size-normalised) — headline; the absolute series book is secondary")
    W(f"engine: relvol_screen.py v{RELVOL_SCREEN_V1}")
    W(f"universe: {len(names)} underlyings with a chain (TV top-{args.universe} by cash volume + the "
      f"{len(PASS_B)} routine names); {len(uni) - len(names)} without a chain")
    W(f"contracts_in_window: {len(cont):,} (4 earliest listed expiries per name) | eligible: {len(elig):,}")
    W(f"filters: volume >= {MIN_VOL:,}, theo >= ${MIN_THEO}, V/OI >= {MIN_VOI}, DTE <= {MAX_DTE}")
    W("composite: z(peer_ratio) + z(expiry_share) + z(opt_pct_cash) + z(V/OI) + 1.5*z(own_history)")
    W("chain_source: Cboe delayed-quote option-chain CDN")
    W("universe_source: TradingView america scanner (top-N by cash volume)")
    W(f"baseline_source: Cboe historical options volume (all_symbols, {len(months)} monthly files) — "
      f"own-history measured on {base_date}")
    W(f"series_book_bias: {leg_stats['tag']} (put/call {leg_stats['ratio']:.2f}) — legacy absolute method, "
      f"for continuity with the published series")
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
    W("| Rank | Absolute screen (top 10 by raw contract volume) | Relative screen (multi-day top 10) |")
    W("|---|---|---|")
    a10, r10 = by_abs[:10], multi[:10]
    for i in range(min(len(a10), len(r10))):
        a, b = a10[i], r10[i]
        W(f"| {i+1} | {a['sym']} {a['side']} {a['strike']:g} {a['expiry']} ({int(a['vol']):,} cts) | "
          f"{b['sym']} {b['side']} {b['strike']:g} {b['expiry']} (peer {b['peer_ratio']:.0f}x, "
          f"{b['expiry_share']*100:.0f}% of its expiry) |")
    W("")
    if min(len(a10), len(r10)) < 10:
        W(f"_Only {min(len(a10), len(r10))} rows were available on each side of this comparison._\n")
    ov = len({c["sym"] for c in a10} & {c["sym"] for c in r10})
    W(f"**Overlap between the two top-10s: {ov} of 10 names.** The absolute screen is a roster of size; "
      "the relative screen is a roster of anomaly.\n")

    W("## Series book (absolute method) — continuity with the published put/call series\n")
    W(f"The legacy method, unchanged: the routine's {len(PASS_B)} names, per-underlying top-{LEGACY_TOPN} by "
      f"volume, 4 earliest listed expiries, V/OI ≥ {LEGACY_MIN_VOI}, volume ≥ {LEGACY_MIN_VOL}, DTE ≤ "
      f"{LEGACY_MAX_DTE}. **Bias tag: {leg_stats['tag']}** (put/call {leg_stats['ratio']:.2f}).\n")
    W("| Slice | Rows | Call volume | Put volume | P/C | Tag |")
    W("|---|---|---|---|---|---|")
    W(f"| All kept (series method) | {leg_stats['rows']} | {leg_stats['c']:,} | {leg_stats['p']:,} | "
      f"{leg_stats['ratio']:.2f} | **{leg_stats['tag']}** |")
    W(f"| Economic flow (theo >= $0.05) | {leg_econ['rows']} | {leg_econ['c']:,} | {leg_econ['p']:,} | "
      f"{leg_econ['ratio']:.2f} | **{leg_econ['tag']}** |")
    W(f"| Open-interest floor (OI >= 50) | {leg_oif['rows']} | {leg_oif['c']:,} | {leg_oif['p']:,} | "
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
    W("")

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
                      "top_relative": [f"{c['sym']} {c['side']} {c['strike']:g} {c['expiry']}"
                                       for c in multi[:8]],
                      "top_own_history": [f"{r['sym']} {r['ratio']:.2f}x" for r in nr[:8]],
                      "errors": errors}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
