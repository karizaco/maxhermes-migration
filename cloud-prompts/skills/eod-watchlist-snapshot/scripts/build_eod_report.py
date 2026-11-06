#!/usr/bin/env python3
"""Build the cron #20 US EOD markdown report from the derived fact table.

EOD_DERIVE_V2

The report is COMPUTED from the published CSV, never hand-written, so the prose cannot
drift from the numbers. Sections, in this fixed order:

    # EOD US market snapshot - <session>
    ## TL;DR
    ## Coverage
    ## Market read
    ## Top movers
    ## Source health
    ## Method & caveats

The TL;DR is exactly three bullets (shape / the one consequential move / the caveat that
changes how to read it). The Coverage table publishes BOTH the populated counts and the
per-flag counts of `data_quality`. The Market read is a table, never prose. The Method
section states the market-cap currency and the conversion direction, because the same
column has been written two ways in this archive before.

USAGE
-----
  python3 build_eod_report.py --csv out.csv --manifest manifest.json --history hist.jsonl \
      --session 2026-11-05 --out out.md --source-health source_health.json
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import sys
import time
from collections import Counter, defaultdict

MARKER = "EOD_DERIVE_V2"

INDEX_PROXIES = [("S&P 500", "SPY"), ("Nasdaq 100", "QQQ"), ("Russell 2000", "IWM"),
                 ("Dow Jones", "DIA"), ("S&P 500 equal-weight", "RSP")]

SECTOR_ETFS = {
    "Information Technology": "XLK", "Industrials": "XLI", "Health Care": "XLV",
    "Communication Services": "XLC", "Energy": "XLE", "Materials": "XLB",
    "Consumer Discretionary": "XLY", "Real Estate": "XLRE",
    "Consumer Staples": "XLP", "Financials": "XLF", "Utilities": "XLU",
}

SECTOR_ORDER = list(SECTOR_ETFS.keys())


def f(x):
    try:
        if x is None or x == "":
            return float("nan")
        return float(x)
    except (TypeError, ValueError):
        return float("nan")


def load_history(path: str) -> dict:
    hist = {}
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            bars = []
            for b in rec.get("bars") or []:
                try:
                    bars.append((int(b[0]), float(b[4])))
                except (IndexError, TypeError, ValueError):
                    continue
            if bars:
                hist[rec["ticker"]] = bars
    return hist


def session_move(hist: dict, symbol: str, session: str):
    """(close, change_pct) for a symbol on the session, from the daily history."""
    bars = hist.get(symbol)
    if not bars:
        return None, None
    idx = None
    for i, (ts, c) in enumerate(bars):
        if time.strftime("%Y-%m-%d", time.gmtime(ts)) == session:
            idx = i
            break
    if idx is None or idx == 0:
        return (bars[idx][1] if idx is not None else None), None
    close, prev = bars[idx][1], bars[idx - 1][1]
    if not prev:
        return close, None
    return close, (close / prev - 1.0) * 100.0


def fmt_pct(x):
    if x is None or (isinstance(x, float) and x != x):
        return "n/a"
    return f"{x:+.2f}%"


def fmt_price(x):
    if x is None:
        return "n/a"
    return f"{x:,.2f}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--history", required=True)
    ap.add_argument("--session", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--source-health", default="")
    ap.add_argument("--provenance", default="")
    args = ap.parse_args()

    rows = list(csv.DictReader(open(args.csv, newline="")))
    manifest = json.load(open(args.manifest))
    hist = load_history(args.history)

    closes = [r for r in rows if r["close"]]
    ups = [r for r in closes if f(r["change_pct"]) > 0]
    downs = [r for r in closes if f(r["change_pct"]) < 0]
    flats = [r for r in closes if f(r["change_pct"]) == 0]
    changes = [f(r["change_pct"]) for r in closes if f(r["change_pct"]) == f(r["change_pct"])]
    median = statistics.median(changes) if changes else float("nan")

    # ---- index proxies
    idx_rows = []
    for label, sym in INDEX_PROXIES:
        c, ch = session_move(hist, sym, args.session)
        if c is not None:
            idx_rows.append((label, sym, c, ch))

    # ---- sector read
    by_sector = defaultdict(list)
    for r in closes:
        if r["sector"]:
            by_sector[r["sector"]].append(f(r["change_pct"]))
    sector_rows = []
    for s in SECTOR_ORDER:
        vals = by_sector.get(s)
        if not vals:
            continue
        etf = SECTOR_ETFS[s]
        _, etf_ch = session_move(hist, etf, args.session)
        sector_rows.append((s, statistics.mean(vals), statistics.median(vals), len(vals),
                            sum(1 for v in vals if v > 0), sum(1 for v in vals if v < 0),
                            etf, etf_ch))
    sector_rows.sort(key=lambda x: x[1])

    # ---- movers (volume >= 100k)
    liq = [r for r in rows if r["close"] and f(r["volume"]) >= 100000
           and f(r["change_pct"]) == f(r["change_pct"])]
    gainers = sorted(liq, key=lambda r: -f(r["change_pct"]))[:10]
    losers = sorted(liq, key=lambda r: f(r["change_pct"]))[:10]

    # ---- the one consequential move
    biggest = max(liq, key=lambda r: abs(f(r["change_pct"]))) if liq else None

    flags = manifest["flag_counts"]
    populated = manifest["populated_counts"]

    # ---- TL;DR
    head = ""
    if idx_rows:
        head = (f"the tape was driven by the index proxies: "
                + ", ".join(f"{l} {fmt_pct(ch)}" for l, _, _, ch in idx_rows[:2]))
    tl1 = (f"**{len(closes)} of {len(rows)} US-listed symbols carry a settled "
           f"{args.session} close**, and {head}."
           if head else
           f"**{len(closes)} of {len(rows)} US-listed symbols carry a settled "
           f"{args.session} close**.")
    if biggest:
        tl2 = (f"The one consequential move is **{biggest['ticker']}** "
               f"({biggest['name']}), {fmt_pct(f(biggest['change_pct']))} on "
               f"{int(f(biggest['volume'])):,} shares"
               + (f", {biggest['sector']}" if biggest["sector"] else "") + ".")
    else:
        tl2 = "No liquid mover qualified for the top-movers table."
    tl3 = (f"**{flags.get('CAP_CARRIED', 0)} rows carry a cap resolved from another line of "
           f"the same issuer** and {flags.get('NO_CAP', 0)} carry no cap at all - the market cap "
           f"is an ISSUER-level number, so a consumer must deduplicate on `cap_source_symbol` "
           f"before building any cap-weighted aggregate.")

    # ---- coverage table
    cov = []
    for col, label, basis in [
        ("close", "close", "consolidated 16:00 ET auction print, checked against an independent reading"),
        ("change_pct", "change_pct", "settled close vs the split-adjusted prior close"),
        ("volume", "volume", "settled session volume"),
        ("high", "high", "session range, always bracketing the close"),
        ("low", "low", "session range, always bracketing the close"),
        ("open", "open", "09:30 ET print, kept only when inside the session range"),
        ("market_cap", "market_cap", "issuer-level cap from the vendor's carrier row, rescaled to this session"),
        ("market_cap_usd", "market_cap_usd", "equal to market_cap - the US file is already USD"),
        ("pe_ratio", "pe_ratio", "trailing P/E"),
        ("sector", "sector", "GICS sector"),
        ("rel_volume", "rel_volume", "session volume / mean volume of the prior 30 sessions"),
        ("sma_50", "sma_50", "mean close over the last 50 sessions"),
        ("sma_200", "sma_200", "mean close over the last 200 sessions"),
        ("atr_14", "atr_14", "mean true range over the last 14 sessions"),
        ("gap_pct", "gap_pct", "open vs the prior close"),
        ("avg_daily_dollar_volume", "avg_daily_dollar_volume", "mean(close x volume) over the prior 30 sessions"),
        ("float_shares", "float_shares", "vendor public float"),
        ("cap_source_symbol", "cap_source_symbol", "the row the cap was resolved from"),
    ]:
        cov.append((label, populated.get(col, 0), basis))

    # ---- source health
    src_rows = []
    if args.source_health and os.path.exists(args.source_health):
        src_rows = json.load(open(args.source_health))

    out = []
    A = out.append
    A(f"# EOD US market snapshot — {args.session}")
    A("")
    if args.provenance:
        A(args.provenance)
        A("")
    A("## TL;DR")
    A("")
    A(f"- {tl1}")
    A(f"- {tl2}")
    A(f"- {tl3}")
    A("")
    A("## Coverage")
    A("")
    A("| Column | Rows populated | Basis |")
    A("|---|---|---|")
    for label, n, basis in cov:
        A(f"| `{label}` | {n} | {basis} |")
    A("")
    A(f"Rows: **{len(rows)}**. Settled closes: **{len(closes)}**.")
    A("")
    A("### Data-quality flags (per row, `data_quality`)")
    A("")
    A("| Flag | Rows | Meaning |")
    A("|---|---|---|")
    meaning = {
        "NO_CAP": "the row's issuer cap could not be resolved — the cell is empty, never zero",
        "CAP_CARRIED": "the cap was resolved from another line of the same issuer (`cap_source_symbol`)",
        "HIGH_LOW_UNAVAILABLE": "high/low left empty on purpose — no range that brackets the close",
        "RANGE_ADJUSTED": "high/low came from the vendor's day range, not the daily bar",
        "NO_HISTORY": "no session bar in the price history, so no derived column exists",
        "NO_PE": "no trailing P/E for the row",
        "NO_SECTOR": "no GICS sector for the row",
        "OK": "none of the above",
    }
    for flag in manifest["flag_precedence"]:
        A(f"| `{flag}` | {flags.get(flag, 0)} | {meaning.get(flag, '')} |")
    A("")
    A("## Market read")
    A("")
    if idx_rows:
        A("| Index | Proxy | Close | Change |")
        A("|---|---|---|---|")
        for label, sym, c, ch in idx_rows:
            A(f"| {label} | {sym} | {fmt_price(c)} | {fmt_pct(ch)} |")
        A("")
    A(f"Advancers {len(ups)} · decliners {len(downs)} · unchanged {len(flats)} · "
      f"median name {fmt_pct(median)}.")
    A("")
    if sector_rows:
        A("| Sector | Avg move | Median move | Names | Up | Down | Sector ETF | ETF move |")
        A("|---|---|---|---|---|---|---|---|")
        for s, avg, med, n, u, d, etf, etf_ch in sector_rows:
            A(f"| {s} | {avg:+.2f}% | {med:+.2f}% | {n} | {u} | {d} | {etf} | {fmt_pct(etf_ch)} |")
        A("")
        A("The two columns are expected to disagree: the average is over every listed name "
          "(mostly micro-caps), the ETF is cap-weighted. This is an unweighted sector read.")
        A("")
    A("## Top movers (volume ≥ 100,000)")
    A("")
    for title, block in (("Gainers", gainers), ("Losers", losers)):
        A(f"### {title}")
        A("")
        A("| Ticker | Name | Close | Change | Volume | Rel. volume | ATR % | Sector |")
        A("|---|---|---|---|---|---|---|---|")
        for r in block:
            A(f"| {r['ticker']} | {r['name']} | {r['close']} | {fmt_pct(f(r['change_pct']))} | "
              f"{int(f(r['volume'])):,} | {r['rel_volume'] or 'n/a'} | {r['atr_pct'] or 'n/a'} | "
              f"{r['sector']} |")
        A("")
    A("## Source health")
    A("")
    if src_rows:
        A("| Source | Use | Status |")
        A("|---|---|---|")
        for s in src_rows:
            A(f"| {s.get('source','')} | {s.get('use','')} | {s.get('status','')} |")
    else:
        A("| Source | Use | Status |")
        A("|---|---|---|")
        A("| (not supplied to this builder) | | |")
    A("")
    A("## Method & caveats")
    A("")
    A(f"- **CSV**: `{os.path.basename(args.csv)}` — **{manifest['csv_columns']} columns** "
      f"(the base 14 session columns plus {len(manifest['derived_columns'])} derived/provenance "
      f"columns). A consumer reading by position still gets the same first 14 columns.")
    A(f"- **Market-cap currency**: `market_cap` is **USD**. `market_cap_usd` is published "
      f"explicitly and equals it. **Conversion direction: none — no FX conversion is applied "
      f"to this file**, because every row's listing currency is USD. The identity to assert "
      f"downstream is `cap_usd * 1.0 == cap_local`; on the international file the same "
      f"identity is `usd_cap * FX_per_USD == market_cap_local` (a MULTIPLY against a "
      f"local-per-USD rate).")
    A(f"- **Market-cap carrier rule**: the cap belongs to the ISSUER and is resolved from the "
      f"vendor's own carrier row — never a volume heuristic. {manifest['carrier_rows']} rows "
      f"carry their own issuer's cap; {manifest['carried_rows']} rows carry it from another line "
      f"of the same issuer and say which one in `cap_source_symbol`. "
      f"**One issuer now appears on more than one row, so a cap-weighted aggregate MUST "
      f"deduplicate on `cap_source_symbol` first.**")
    A(f"- **`data_quality`**: every row carries a flag from a closed vocabulary; a cell can hold "
      f"several flags joined with `|`, in the fixed precedence "
      f"{' > '.join(manifest['flag_precedence'])}. `OK` appears only when nothing else applies. "
      f"The cell is never empty, so a consumer can always tell 'not applicable' from "
      f"'the fetch failed'.")
    A("- **Derived columns are computed once, here**, from a single price-history pull, so two "
      "routines reading this file cannot disagree about what relative volume means. "
      + "; ".join(f"`{k}` = {v}" for k, v in manifest["definitions"].items()) + ".")
    A(f"- **A close is never published outside its own range.** {flags.get('RANGE_ADJUSTED', 0)} "
      f"rows take their high/low from the vendor's day range (the daily bar did not bracket the "
      f"close) and {flags.get('HIGH_LOW_UNAVAILABLE', 0)} rows carry empty high/low because no "
      f"range bracketed the close at all.")
    A("- **A missing value is empty, never zero.** A cap that cannot be resolved is empty and "
      "flagged `NO_CAP`.")
    A("- **The price history is split-adjusted**, so the moving averages, the ATR and the 52-week "
      "extremes are on the same adjusted basis as the session close.")
    A(f"- **Base columns are unchanged from the published session file**: the derive stage adds "
      f"columns and the carrier rule; it does not restate a single price, volume, P/E, sector or "
      f"name. The only base value that changes is `market_cap` on a row that now carries its "
      f"issuer's cap (the issuer-level number) instead of no cap at all.")
    A("")
    A(f"Artifact: `{os.path.basename(args.csv)}` ({len(rows)} rows).")
    A("")

    with open(args.out, "w") as fh:
        fh.write("\n".join(out))
    print(f"wrote {args.out} ({len(out)} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
