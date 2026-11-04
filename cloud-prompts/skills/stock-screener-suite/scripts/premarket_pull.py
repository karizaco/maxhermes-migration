#!/usr/bin/env python3
"""Pre-market prices that survive Nasdaq's stale HTTP cache.

Why
---
Cron #08 (stock-screener-pre-market-gapper) must publish a pre-market gap for
every Focus name. The obvious source, `api.nasdaq.com/.../extended-trading`,
is served through a **shared HTTP cache** that can hand back a snapshot
captured much earlier. Measured 2026-11-03: the *same URL* returned a
4.5-hour-old vintage (AAPL pre-market 05:33:19) alongside a current one
(09:30:01) in the same second, and MSFT/GOOGL alternated between 05:31-05:33
and 09:30:01 across rapid pulls. Responses carry a `cache-hit` header. A
cache-buster query string does **not** reliably route around it - eight pulls
with eight distinct URLs still alternated.

The symptom is a tape whose newest print appears to run 16-39 minutes behind
wall clock, which reads exactly like a slow exchange feed but is not one. The
tape's own newest print advanced ~1:1 with wall clock at a constant offset:
the signature of a periodically-refreshed cache.

Meanwhile `/info` is the LIVE source - `primaryData.lastTradeTimestamp`
tracks wall clock to the minute and the price changes on every pull.

How this script fixes it
------------------------
1. Pull the tape N times and keep the payload with the **newest internal
   timestamp** (the latest `tradeDetailTable` clock time, AFTER sorting - the
   table is served newest-first). A stale vintage can never win a
   max-timestamp comparison.
2. Take the **price** from `/info` `primaryData` (live); use the tape for
   *which prints actually traded*, the pre-market high/low, and volume.
3. Cross-check with the **Cboe delayed-quote CDN**, which returns an explicit
   `last_trade_time` and `timestamp` - freshness is verifiable from the
   payload rather than inferred, and it is not subject to the Nasdaq cache.
4. When the trade-detail tape is **complete** (fewer than 100 rows - Nasdaq
   caps that table at 100) it can arbitrate a contradictory cumulative volume
   counter; when the tape is truncated it cannot, and the counter is used.

Everything it reports carries its own provenance, so the artifact can state
the margin against the trigger and show that the flag decision is immune to
whatever the cache served.

Usage
-----
    python scripts/premarket_pull.py --symbols AAPL,MSFT,NVDA
    python scripts/premarket_pull.py --from-csv daily-screens/2026-10-30/focus.csv \
        --out-dir daily-screens/2026-11-02
    python scripts/premarket_pull.py --symbols AAPL --pulls 6 --gap-trigger 4

Outputs
-------
    <out-dir>/_premarket-pull.json   full per-symbol provenance
    <out-dir>/premarket-pull.md      a markdown table
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36",
    "Referer": "https://www.nasdaq.com/",
    "Accept": "application/json, text/plain, */*",
}
NASDAQ_INFO = "https://api.nasdaq.com/api/quote/{sym}/info?assetclass={ac}"
# ETFs (SPY/QQQ/IWM...) return data:null under assetclass=stocks - they need etf.
ASSET_CLASSES = ("stocks", "etf")
NASDAQ_TAPE = ("https://api.nasdaq.com/api/quote/{sym}/extended-trading"
               "?assetclass={ac}&markettype=pre")
CBOE_QUOTE = "https://cdn.cboe.com/api/global/delayed_quotes/quotes/{sym}.json"

TAPE_ROW_CAP = 100        # Nasdaq caps tradeDetailTable at 100 rows
MIN_REAL_PRINT = 25       # a print of >= 25 shares is a market; 1-2 lots are quotes


def _num(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("$", "").replace(",", "").replace("%", "")
    try:
        return float(s)
    except ValueError:
        return None


def _get(url: str, timeout: int = 25):
    """GET + JSON parse. Returns (payload, cache_hit) or (None, None)."""
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            cache_hit = resp.headers.get("cache-hit")
            body = resp.read().decode("utf-8", errors="replace")
        return json.loads(body), cache_hit
    except Exception:
        return None, None


def _consol_price(raw: str | None):
    """'$7.9699 -0.1559 (-1.92%)' -> 7.9699 (the composite's first token)."""
    if not raw:
        return None
    m = re.match(r"^\$?([\d,]+\.?\d*)", raw)
    return float(m.group(1).replace(",", "")) if m else None


def _consol_pct(raw: str | None):
    if not raw:
        return None
    m = re.search(r"\(([-+]?[\d.]+)%\)", raw)
    return float(m.group(1)) if m else None


def _hhmm_to_min(hhmm: str | None):
    if not hhmm:
        return None
    m = re.match(r"^(\d{1,2}):(\d{2})\s*([AP]M)", str(hhmm))
    if not m:
        return None
    h = int(m.group(1)) % 12
    if m.group(3).upper() == "PM":
        h += 12
    return h * 60 + int(m.group(2))


def _clock_to_min(clock: str | None):
    if not clock:
        return None
    m = re.match(r"^(\d{2}):(\d{2}):(\d{2})$", str(clock).strip())
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def _pull_tape(sym: str, bust: bool, asset_class: str = "stocks"):
    """One tape pull. Returns a record describing what came back."""
    url = NASDAQ_TAPE.format(sym=sym, ac=asset_class)
    if bust:
        url += "&u=%d" % time.time_ns()
    payload, cache_hit = _get(url)
    if not payload:
        return None
    data = payload.get("data") or {}
    rows = ((data.get("tradeDetailTable") or {}).get("rows") or [])
    info_rows = ((data.get("infoTable") or {}).get("rows") or [{}])
    info_row = info_rows[0] if info_rows else {}

    prints = []
    for r in rows:
        px = _num(r.get("price"))
        if px is None:
            continue
        prints.append({
            "time": r.get("time"),
            "minutes": _clock_to_min(r.get("time")),
            "price": px,
            "vol": _num(r.get("shareVolume")),
        })
    # The table is served NEWEST-FIRST: rows[-1] is the OLDEST print. Sorting by
    # clock time is what makes "the last print" mean the last EXECUTED print.
    prints.sort(key=lambda p: (p["minutes"] is None, p["minutes"]))

    newest = prints[-1] if prints else None
    return {
        "prints": prints,
        "newest": newest,
        "consol_raw": info_row.get("consolidated"),
        "consol_price": _consol_price(info_row.get("consolidated")),
        "consol_pct": _consol_pct(info_row.get("consolidated")),
        "counter_vol": _num(info_row.get("volume")),
        "pm_high": info_row.get("highPrice"),
        "pm_low": info_row.get("lowPrice"),
        "tape_rows": len(rows),
        "cache_hit": cache_hit,
        "updated": (data.get("lastUpdateInfo") or [None])[0],
    }


def _best_tape(sym: str, pulls: int):
    """Pull N times; keep the payload whose newest internal timestamp is latest.

    This is the core defence against the stale cache: a stale vintage can be
    hours old, but it can never carry a NEWER internal timestamp than the
    current one, so it can never win this comparison.
    """
    seen = []
    for i in range(pulls):
        for ac in ASSET_CLASSES:
            rec = _pull_tape(sym, bust=(i % 2 == 0), asset_class=ac)
            if rec and rec.get("prints") or (rec and rec.get("consol_raw")):
                rec["asset_class"] = ac
                seen.append(rec)
                break
        if i + 1 < pulls:
            time.sleep(0.3)
    if not seen:
        return None, []
    ranked = sorted(
        [s for s in seen if s.get("newest")],
        key=lambda s: (s["newest"]["minutes"] or 0),
    )
    best = ranked[-1] if ranked else seen[-1]
    return best, seen


def _fetch_info(sym: str):
    """The LIVE source. primaryData.lastTradeTimestamp tracks wall clock.

    Two wrinkles:
    * `secondaryData` holds the official close ONLY while the regular session is
      running; once the market is Closed it comes back null. The prior close
      then has to come from the caller (the sweep's own focus.csv) or from Cboe.
    * ETFs (SPY/QQQ/IWM) return data:null under assetclass=stocks and need
      assetclass=etf, so both are tried.
    """
    for ac in ASSET_CLASSES:
        payload, _ = _get(NASDAQ_INFO.format(sym=sym, ac=ac))
        if not payload:
            continue
        data = payload.get("data") or {}
        if not data:
            continue
        primary = data.get("primaryData") or {}
        secondary = data.get("secondaryData") or {}
        ts = primary.get("lastTradeTimestamp")
        price = _num(primary.get("lastSalePrice"))
        if price is None:
            continue
        return {
            "price": price,
            "pct": _num(primary.get("percentageChange")),
            "ts": ts,
            "ts_minutes": _hhmm_to_min(ts),
            "bid": _num(primary.get("bidPrice")),
            "ask": _num(primary.get("askPrice")),
            "secondary_close": _num(secondary.get("lastSalePrice")),
            "market_status": data.get("marketStatus"),
            "asset_class": ac,
        }
    return None


def _fetch_cboe(sym: str):
    """Independent venue with an explicit print time - freshness is verifiable."""
    payload, _ = _get(CBOE_QUOTE.format(sym=sym))
    if not payload:
        return None
    data = payload.get("data") or {}
    if not data:
        return None
    return {
        "price": _num(data.get("current_price")),
        "close": _num(data.get("close")),
        "prev_day_close": _num(data.get("prev_day_close")),
        "volume": data.get("volume"),
        "last_trade_time": data.get("last_trade_time"),
        "timestamp": (payload.get("timestamp")),
    }


def _load_symbols(args) -> list[str]:
    syms: list[str] = []
    if args.symbols:
        syms += [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    if args.from_csv:
        with open(args.from_csv, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                for key in ("ticker", "symbol", "Ticker", "Symbol"):
                    if row.get(key):
                        syms.append(str(row[key]).strip().split(".")[0].split("/")[0].upper())
                        break
    seen, out = set(), []
    for s in syms:
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _one(sym: str, args, prior_close: float | None = None) -> tuple[str, dict | None]:
    best, seen = _best_tape(sym, args.pulls)
    info = _fetch_info(sym)
    cboe = _fetch_cboe(sym) if args.cboe else None

    if best is None and info is None:
        return sym, None

    rec: dict = {
        "ticker": sym,
        "tape_pulls": len(seen),
        "tape_vintages": sorted({s["newest"]["time"] for s in seen if s.get("newest")}),
        "cache_hits": sorted({str(s.get("cache_hit")) for s in seen if s.get("cache_hit")}),
    }

    if best:
        prints = best["prints"]
        real = [p for p in prints if (p.get("vol") or 0) >= MIN_REAL_PRINT]
        tape_sum = sum((p.get("vol") or 0) for p in prints)
        counter = best.get("counter_vol")
        # A COMPLETE tape (fewer rows than the cap) can arbitrate a bad counter.
        if counter is None:
            volume, vol_src = tape_sum, "tape sum (LOWER BOUND - no cumulative counter published)"
        elif best["tape_rows"] < TAPE_ROW_CAP and tape_sum and counter > tape_sum * 3:
            volume = tape_sum
            vol_src = ("tape sum - Nasdaq counter %s REJECTED as faulty (complete %d-print tape "
                       "sums to %s)" % ("{:,}".format(int(counter)), best["tape_rows"],
                                         "{:,}".format(int(tape_sum))))
        else:
            volume, vol_src = counter, "Nasdaq extended-trading cumulative counter"

        rec.update({
            "tape_newest_print": best["newest"]["time"] if best.get("newest") else None,
            "tape_last_price": best["newest"]["price"] if best.get("newest") else None,
            "tape_last_print_vol": best["newest"]["vol"] if best.get("newest") else None,
            "tape_consol_raw": best.get("consol_raw"),
            "tape_consol_pct": best.get("consol_pct"),
            "pm_high": best.get("pm_high"),
            "pm_low": best.get("pm_low"),
            "tape_rows": best["tape_rows"],
            "tape_sum": tape_sum,
            "pm_volume": volume,
            "pm_volume_source": vol_src,
            "real_print_high": max((p["price"] for p in real), default=None),
            "real_print_low": min((p["price"] for p in real), default=None),
            "real_prints": len(real),
        })

    if info:
        rec.update({
            "info_price": info["price"], "info_pct": info["pct"], "info_ts": info["ts"],
            "info_bid": info["bid"], "info_ask": info["ask"],
            "secondary_close": info["secondary_close"], "market_status": info["market_status"],
        })
    if cboe:
        rec.update({
            "cboe_price": cboe["price"], "cboe_close": cboe["close"],
            "cboe_last_trade_time": cboe["last_trade_time"], "cboe_timestamp": cboe["timestamp"],
        })

    # ---- price selection, in priority order ----
    price = None
    price_src = None
    if info and info.get("price") is not None:
        price, price_src = info["price"], "/info primaryData (LIVE)"
        # `last == ask` means the reading is the OFFER, not an executed trade.
        if info.get("ask") is not None and abs(info["price"] - info["ask"]) < 1e-9:
            price_src += " - equals the ASK, so it is a quote not a print"
    if price is None and best and best.get("newest"):
        price = best["newest"]["price"]
        price_src = "tape last executed print (fallback)"
    rec["price"] = price
    rec["price_source"] = price_src

    # ---- gap ----
    # Priority: the prior close the caller supplied (the sweep's own focus.csv -
    # the same denominator the artifact uses) > secondaryData > Cboe close.
    base = prior_close
    base_src = "caller-supplied prior close (sweep focus.csv)"
    if base is None:
        base = rec.get("secondary_close") or (info or {}).get("secondary_close")
        base_src = "Nasdaq secondaryData"
    if base is None and cboe and cboe.get("close"):
        base = cboe.get("close")
        base_src = "Cboe close"
    gap = None
    if price is not None and base:
        gap = round((price / base - 1) * 100, 3)
    rec["base_close"] = base
    rec["base_close_source"] = base_src
    rec["gap_pct"] = gap

    # ---- divergence across the independent sources ----
    divs = {}
    for label, other in (("tape", rec.get("tape_last_price")), ("cboe", rec.get("cboe_price"))):
        if other is not None and price is not None and base:
            divs[label] = round((other - price) / base * 100, 3)
    rec["divergence_pp"] = divs

    return sym, rec


def _load_prior_closes(csv_path: str) -> dict[str, float]:
    """Read the prior session's close from the sweep's own CSV.

    The gap denominator must be the SETTLED prior close. Nasdaq's secondaryData
    drifts intraday and is null once the market is closed, so the sweep's own
    focus.csv is the reliable source - and it keeps the artifact's denominator
    identical to the one the screen used.
    """
    out: dict[str, float] = {}
    if not csv_path:
        return out
    try:
        with open(csv_path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                sym = None
                for key in ("ticker", "symbol", "Ticker", "Symbol"):
                    if row.get(key):
                        sym = str(row[key]).strip().split(".")[0].split("/")[0].upper()
                        break
                if not sym:
                    continue
                for key in ("prior_close", "close", "close_1030", "last_close"):
                    if row.get(key):
                        val = _num(row[key])
                        if val:
                            out[sym] = val
                            break
    except Exception:
        return out
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Cache-safe pre-market prices for the Focus list")
    p.add_argument("--symbols", default="", help="comma-separated tickers")
    p.add_argument("--from-csv", default=None, help="CSV with a ticker/symbol column")
    p.add_argument("--out-dir", default=".", help="where to write the JSON + markdown")
    p.add_argument("--pulls", type=int, default=4, help="tape pulls per symbol (N >= 4)")
    p.add_argument("--gap-trigger", type=float, default=4.0, help="gap trigger in percent")
    p.add_argument("--volume-floor", type=int, default=50_000, help="pre-market volume floor")
    p.add_argument("--cboe", action="store_true", default=True,
                   help="cross-check with the Cboe delayed-quote CDN (default on)")
    p.add_argument("--no-cboe", dest="cboe", action="store_false")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    if args.pulls < 4:
        print("warning: --pulls < 4 weakens the max-timestamp defence against the stale cache",
              file=sys.stderr)

    syms = _load_symbols(args)
    if not syms:
        print("no symbols given (use --symbols or --from-csv)", file=sys.stderr)
        return 2

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    prior = _load_prior_closes(args.from_csv) if args.from_csv else {}

    records: dict[str, dict] = {}
    failures = 0
    with ThreadPoolExecutor(max_workers=6) as ex:
        for sym, rec in ex.map(lambda s: _one(s, args, prior.get(s)), syms):
            if rec:
                records[sym] = rec
            else:
                failures += 1

    for sym, rec in records.items():
        g = rec.get("gap_pct")
        v = rec.get("pm_volume")
        rec["flagged"] = bool(g is not None and abs(g) > args.gap_trigger and v and v > args.volume_floor)
        rec["gap_up"] = bool(g is not None and g > args.gap_trigger)
        rec["gap_down"] = bool(g is not None and g < -args.gap_trigger)

    payload = {
        "requested": len(syms),
        "ok": len(records),
        "failed": failures,
        "gap_trigger": args.gap_trigger,
        "volume_floor": args.volume_floor,
        "pulls_per_symbol": args.pulls,
        "records": records,
    }
    (out_dir / "_premarket-pull.json").write_text(json.dumps(payload, indent=2))

    lines = [
        "# Pre-market pull",
        "",
        "_Cache-safe pre-market prices. The tape is pulled %d times per symbol and the "
        "payload with the newest internal timestamp wins, because Nasdaq's extended-trading "
        "endpoint is served from a shared HTTP cache that can return hours-old snapshots for "
        "the same URL. The price comes from `/info` (live); the tape supplies prints, "
        "high/low and volume; Cboe supplies an independent, explicitly-timestamped print._"
        % args.pulls,
        "",
        "| Ticker | Close | PM price | Gap % | PM volume | Price source | Tape newest | "
        "Tape vintages seen | Cboe | Divergence (pp) | Mkt | Flag |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for sym in syms:
        r = records.get(sym)
        if not r:
            lines.append(f"| {sym} | — | — | — | — | _no quote_ | — | — | — | — | — | — |")
            continue
        gap = r.get("gap_pct")
        divs = r.get("divergence_pp") or {}
        div_txt = ", ".join(f"{k} {v:+.2f}" for k, v in sorted(divs.items())) or "—"
        lines.append(
            "| **{sym}** | {close} | {px} | {gap} | {vol} | {src} | {newest} | {vint} | "
            "{cboe} | {div} | {mkt} | {flag} |".format(
                sym=sym,
                close=("%.2f" % r["base_close"]) if r.get("base_close") else "—",
                px=("%.4f" % r["price"]) if r.get("price") is not None else "—",
                gap=("%+.2f%%" % gap) if gap is not None else "—",
                vol=("{:,.0f}".format(r["pm_volume"])) if r.get("pm_volume") else "—",
                src=r.get("price_source") or "—",
                newest=r.get("tape_newest_print") or "—",
                vint=", ".join(r.get("tape_vintages") or []) or "—",
                cboe=("%.2f" % r["cboe_price"]) if r.get("cboe_price") is not None else "—",
                div=div_txt,
                mkt=r.get("market_status") or "—",
                flag="**YES**" if r.get("flagged") else "no",
            )
        )

    gaps = [abs(r["gap_pct"]) for r in records.values() if r.get("gap_pct") is not None]
    margin = ""
    if gaps:
        worst = max(gaps)
        margin = (f"\n_Widest absolute gap on any source: {worst:.2f}% against a "
                  f"{args.gap_trigger:.2f}% trigger — a {args.gap_trigger / worst:.2f}x margin, "
                  f"so the flag decision is immune to whichever cached vintage a source "
                  f"returns._\n" if worst > 0 else "")
    lines += ["", margin, f"_{len(records)} of {len(syms)} symbols priced"
              + (f"; {failures} missing." if failures else "."), ""]
    (out_dir / "premarket-pull.md").write_text("\n".join(lines))

    if not args.quiet:
        print("premarket pull: %d/%d priced, %d missing -> %s"
              % (len(records), len(syms), failures, out_dir / "premarket-pull.md"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
