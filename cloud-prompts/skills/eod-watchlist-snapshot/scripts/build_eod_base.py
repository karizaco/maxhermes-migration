#!/usr/bin/env python3
"""Base assembly for cron #20 — the base stage (build_eod_base.py).

EOD_DERIVE_V2
EOD_BASE_V1

THE BASE OWNS THE NUMERIC FORMAT (the derive stage copies the base fields verbatim):
4 significant figures with the fractional trailing zeros stripped, values >= 100000 at full
precision, integers for volume / market cap / float.

THE PRICE SOURCE (measured 2026-11-11): the close is the VENUE's settled print
(Nasdaq /info `secondaryData`), not Yahoo's daily-bar close. The archive's own 2026-11-10
file proves it: it carries HAIN's 11-10 close as 0.135, which is Nasdaq's consolidated
record, while Yahoo's daily bar for that session says 0.14. Yahoo's daily bar holds a
pre-auction print for thin names; the venue's print is the close of record.

The Yahoo daily bar stays the source for the DERIVED columns (rel_volume, SMAs, ATR, the
52-week extremes) — one pull, one series — and its session bar is the cross-check.

Inputs : vendor_refs.json, history_merged.jsonl, quote_batch.json, nasdaq_info.json,
         cnbc.json, the PRIOR session's published CSV (the cap-rescale basis)
Output : base.csv (14 base columns) + quote_prev.json
"""
from __future__ import annotations
import csv, json, math, os, sys, time
from decimal import Decimal, ROUND_HALF_UP

SESSION = sys.argv[1] if len(sys.argv) > 1 else "2026-11-11"
PRIOR_SESSION = sys.argv[2] if len(sys.argv) > 2 else "2026-11-10"
VENDOR = sys.argv[3] if len(sys.argv) > 3 else "/workspace/work/vendor_refs.json"
HIST = sys.argv[4] if len(sys.argv) > 4 else "/workspace/work/history_merged.jsonl"
QUOTES = sys.argv[5] if len(sys.argv) > 5 else "/workspace/work/quote_batch.json"
OUT = sys.argv[6] if len(sys.argv) > 6 else "/workspace/work/base.csv"
CNBC = sys.argv[7] if len(sys.argv) > 7 else "/workspace/work/cnbc.json"
NASDAQ = sys.argv[8] if len(sys.argv) > 8 else "/workspace/work/nasdaq_info.json"
PRIOR_CSV = sys.argv[9] if len(sys.argv) > 9 else "/workspace/work/2026-11-10.csv"

BASE_COLUMNS = ["date", "ticker", "name", "open", "high", "low", "close", "volume",
                "change_pct", "market_cap", "pe_ratio", "sector", "currency", "exchange"]
FULL_PRECISION_FROM = 100000


def fmt_num(x) -> str:
    if x is None or x == "":
        return ""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return ""
    if math.isnan(v) or math.isinf(v):
        return ""
    if v == 0:
        return "0"
    if abs(v) >= FULL_PRECISION_FROM:
        return f"{v:.6f}".rstrip("0").rstrip(".")
    d = Decimal(repr(v))
    decimals = 3 - d.adjusted()
    if decimals < 0:
        step = Decimal(1).scaleb(-decimals)
        q = (d / step).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * step
    else:
        q = d.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)
    s = format(q, "f")
    return s.rstrip("0").rstrip(".") if "." in s else s


def fmt_int(x) -> str:
    if x is None or x == "":
        return ""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return ""
    if math.isnan(v) or math.isinf(v):
        return ""
    return str(int(round(v)))


def day_of(ts) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(int(ts)))


def load_history(path: str) -> dict:
    hist: dict[str, list] = {}
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
                    ts, o, h, l, c, v = b[0], b[1], b[2], b[3], b[4], b[5]
                except (IndexError, TypeError):
                    continue
                if c is None:
                    continue
                bars.append((int(ts), o, h, l, float(c), v))
            bars.sort(key=lambda x: x[0])
            if bars:
                hist[rec.get("ticker", "")] = bars
    return hist


def main() -> int:
    vendor = json.load(open(VENDOR))
    quotes = json.load(open(QUOTES)) if os.path.exists(QUOTES) else {}
    cnbc = json.load(open(CNBC)) if os.path.exists(CNBC) else {}
    nasdaq = json.load(open(NASDAQ)) if os.path.exists(NASDAQ) else {}
    hist = load_history(HIST)
    vcaps = vendor.get("vendor_caps", {})

    prior_close = {}
    prior_rows = 0
    if os.path.exists(PRIOR_CSV):
        for r in csv.DictReader(open(PRIOR_CSV)):
            prior_rows += 1
            if (r.get("close") or "").strip():
                prior_close[r["ticker"]] = float(r["close"])

    stats = {"rows": 0, "close_venue": 0, "close_bar": 0, "no_close": 0,
             "range_bar": 0, "range_venue": 0, "range_yahoo": 0, "range_cnbc": 0,
             "range_unavailable": 0, "volume_from_bar": 0, "no_bar": 0,
             "cap_vendor": 0, "cap_quote": 0, "cap_rescaled": 0, "cap_stale_basis": 0,
             "cap_implausible": 0, "cap_empty": 0, "pe_vendor": 0, "pe_quote": 0,
             "no_pe": 0, "no_sector": 0, "venue_vs_bar_diff": 0}

    out_rows = []
    for r in vendor.get("rows", []):
        t = r.get("ticker")
        if not t:
            continue
        stats["rows"] += 1
        bars = hist.get(t, [])
        sess = None
        prior_bar = None
        prior_date = ""
        for i, b in enumerate(bars):
            if day_of(b[0]) == SESSION:
                sess = b
                if i > 0:
                    prior_bar = bars[i - 1]
                    prior_date = day_of(bars[i - 1][0])
                break

        row = {c: "" for c in BASE_COLUMNS}
        row["date"] = SESSION
        row["ticker"] = t
        row["name"] = (r.get("name") or "").strip()
        row["exchange"] = r.get("exchange") or ""
        row["currency"] = r.get("currency") or "USD"
        sector = (r.get("gics_sector") or "").strip()
        row["sector"] = sector
        if not sector:
            stats["no_sector"] += 1

        nas = nasdaq.get(t) or {}
        cn = cnbc.get(t) or {}
        q = quotes.get(t) or {}

        # ---- the close of record: the venue's settled print, else the settled daily bar
        bar_close = float(sess[4]) if sess is not None else None
        venue_close = nas.get("close")
        close = None
        if venue_close is not None and venue_close > 0:
            close = float(venue_close)
            stats["close_venue"] += 1
            if bar_close and abs(close - bar_close) / max(bar_close, 1e-9) > 1e-6:
                stats["venue_vs_bar_diff"] += 1
        elif bar_close is not None:
            close = bar_close
            stats["close_bar"] += 1
        else:
            stats["no_close"] += 1

        # ---- the range: the first candidate that BRACKETS the published close
        fh = fl = ""
        if close is not None:
            cands = []
            if sess is not None and sess[1] is not None and sess[2] is not None:
                cands.append((sess[2], sess[1], "bar"))
            if nas.get("day_high") and nas.get("day_low"):
                cands.append((nas["day_low"], nas["day_high"], "venue"))
            if q.get("dayHigh") is not None and q.get("dayLow") is not None:
                cands.append((q["dayLow"], q["dayHigh"], "yahoo"))
            if cn.get("high") is not None and cn.get("low") is not None:
                cands.append((cn["low"], cn["high"], "cnbc"))
            for lo, hi, src in cands:
                if lo <= close <= hi:
                    fh, fl = fmt_num(hi), fmt_num(lo)
                    stats["range_" + src] += 1
                    break
            else:
                stats["range_unavailable"] += 1
            # widen in FORMATTED space so the published close can never sit outside the
            # published range after rounding
            fc0 = fmt_num(close)
            if fc0 and fh and float(fh) < float(fc0):
                fh = fc0
            if fc0 and fl and float(fl) > float(fc0):
                fl = fc0

        row["close"] = fmt_num(close) if close is not None else ""
        row["high"], row["low"] = fh, fl

        # ---- open + volume from the settled daily bar
        if sess is not None:
            _, o, h, l, c, v = sess
            if o is not None:
                op = fmt_num(o)
                if fh and fl and (float(fl) < float(op) < float(fh)):
                    row["open"] = op          # kept only when inside the session range
                elif not fh:
                    row["open"] = op
            if v is not None:
                row["volume"] = fmt_int(v)
                stats["volume_from_bar"] += 1
        else:
            stats["no_bar"] += 1

        # ---- market cap: the vendor's carrier row, rescaled onto this session
        cap = None
        vc = vcaps.get(t)
        if vc and vc.get("cap") is not None:
            cap = float(vc["cap"])
            stats["cap_vendor"] += 1
            cdate = vc.get("date")
            if cdate == SESSION:
                pass
            else:
                base_close = prior_close.get(t)
                if base_close is None and prior_bar is not None and prior_date == PRIOR_SESSION:
                    base_close = float(prior_bar[4])
                if base_close and close and cdate == PRIOR_SESSION:
                    cap = cap * (close / base_close)
                    stats["cap_rescaled"] += 1
                else:
                    stats["cap_stale_basis"] += 1
        else:
            mc = q.get("marketCap")
            if mc and "-" not in t:        # never take a per-line cap from a class line
                cap = float(mc)
                stats["cap_quote"] += 1
        if cap is None:
            stats["cap_empty"] += 1
        else:
            if close and cap:
                implied = cap / close
                if not (1e3 <= implied <= 1e13):
                    stats["cap_implausible"] += 1
                    cap = None
            if cap is not None:
                row["market_cap"] = fmt_int(cap)

        # ---- trailing P/E
        pe = r.get("trailing_pe")
        if pe is not None:
            row["pe_ratio"] = fmt_num(pe)
            stats["pe_vendor"] += 1
        else:
            qpe = q.get("trailingPE")
            if qpe:
                row["pe_ratio"] = fmt_num(qpe)
                stats["pe_quote"] += 1
            else:
                stats["no_pe"] += 1

        out_rows.append(row)

    with open(OUT, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=BASE_COLUMNS)
        w.writeheader()
        for row in out_rows:
            w.writerow(row)

    qp = {}
    for t, qq in quotes.items():
        pc = qq.get("previousClose")
        if pc:
            qp[t] = pc
    json.dump(qp, open(os.path.join(os.path.dirname(OUT) or ".", "quote_prev.json"), "w"))

    json.dump(stats, open("/workspace/work/base_stats.json", "w"), indent=1)
    print("base stats:", json.dumps(stats))
    print("wrote", OUT, len(out_rows), "rows; quote_prev", len(qp))
    return 0


if __name__ == "__main__":
    sys.exit(main())
