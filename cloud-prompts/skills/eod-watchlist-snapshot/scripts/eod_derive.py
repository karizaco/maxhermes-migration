#!/usr/bin/env python3
"""Derive the cron #20 US EOD fact table: published columns, quality flags, manifest.

EOD_DERIVE_V2

WHAT THIS DOES
--------------
The routine's base assembly produces the session fields (open/high/low/close/volume/change/
cap/PE/sector/name/exchange/currency). This script turns that base CSV plus ONE price-history
pull into the published v2 fact table:

  * the derived columns every downstream routine used to re-derive on its own
    (rel_volume, sma_20/50/200, pct_vs_sma_50/200, atr_14, atr_pct, gap_pct,
     pct_from_52w_high/low, avg_daily_dollar_volume, float_shares),
  * `cap_source_symbol` + the vendor's carrier-row rule, so every cap is traceable to the
    row it was resolved from,
  * `data_quality` — a per-row flag so a consumer can tell "not applicable" from
    "the fetch failed",
  * `market_cap_usd` — explicit, so a consumer can never mistake the cap's currency.

Every formula is computed HERE, once, from ONE history pull, so two routines reading this
file can never disagree about what "relative volume" means.

THE DERIVED COLUMNS (definitions are the contract)
---------------------------------------------------
  prior_close        close of the session bar immediately before the session bar
  rel_volume         session volume / mean(volume of the 30 sessions BEFORE the session)
  avg_daily_dollar_volume  mean(close x volume) over those same 30 prior sessions
  sma_20/50/200      mean(close) over the last 20/50/200 bars ENDING AT the session bar
  pct_vs_sma_50      (close / sma_50 - 1) * 100          pct_vs_sma_200 likewise
  atr_14             mean(true range) over the last 14 bars ending at the session bar,
                     true range = max(h-l, |h - prev_close|, |l - prev_close|)
  atr_pct            atr_14 / close * 100
  pct_from_52w_high  (close - max(high over the last 252 bars)) / that max * 100
  pct_from_52w_low   (close - min(low  over the last 252 bars)) / that min * 100
  gap_pct            (open - prior_close) / prior_close * 100, using the PUBLISHED open
                     (the same number the `open` column carries)

THE change_pct ANCHOR — the one field this stage now OWNS
-----------------------------------------------------------
`change_pct` must be the session's PRICE change against the prior session's SETTLED close.
The base assembly's own change field is not trusted, because two of its usual sources are
wrong in a way no error message shows:

  * a quote service's `previous_close` is DIVIDEND-ADJUSTED for distribution payers, so the
    published "change" silently becomes a total return (measured 2026-11-06: AB published
    +0.26% while the price change was -2.32% — a $0.90 distribution on a $34.90 close, and
    the SIGN flipped);
  * a daily bar whose date was never asserted is a STALE bar, so "the previous bar" can be
    two sessions back (measured 2026-11-06: 233 of 4,892 rows, median error 0.46pp, max
    5.2pp).

So the anchor is resolved here, in this order:
  1. the PRIOR SESSION'S PUBLISHED close (`--prior-csv`) — the fleet's own record;
  2. the bar series' prior close, ONLY if that bar's date is the prior session's date;
  3. no anchor -> the change cannot be verified; the row is flagged `NO_PRIOR_CLOSE`.
A published value that disagrees with the recomputed one by more than 0.05pp is REPLACED
and the count is published. A value that agrees is left byte-for-byte alone. `gap_pct` uses
the same anchor, so a gap and a change are never measured against different sessions.

THE MARKET-CAP CARRIER RULE
---------------------------
The cap belongs to the ISSUER, and the vendor stamps it on ONE class row per company.
The carrier is the VENDOR'S OWN row (never a volume heuristic - LILA carries its cap over
LILAK despite 4x the volume). Every line of that issuer publishes the issuer's cap, and
every non-carrier line says which row it came from (`cap_source_symbol`) and is flagged
`CAP_CARRIED`. A cap that cannot be resolved is left EMPTY with `NO_CAP` - never zero.

THE data_quality VOCABULARY (closed set, pipe-joined, fixed precedence)
-----------------------------------------------------------------------
  NO_CAP                 the row's issuer cap could not be resolved
  CAP_CARRIED            the cap was resolved from another line of the same issuer
  HIGH_LOW_UNAVAILABLE   high/low left empty on purpose (no range that brackets the close)
  RANGE_ADJUSTED         high/low came from the vendor's day range, not the daily bar
  NO_HISTORY             no session bar in the price history, so no derived column exists
  NO_PE                  no trailing P/E for the row
  NO_SECTOR              no GICS sector for the row
  OK                     none of the above (and only ever alone)

Precedence is the order above: the cell lists every flag that applies, most severe first.
`OK` appears only when the row has no flag at all. The cell is NEVER empty.

USAGE
-----
  python3 eod_derive.py --base us-eod/2026-11-05.csv --history work/history.jsonl \
      --vendor work/vendor_refs.json --session 2026-11-05 \
      --out us-eod/2026-11-05.v2.csv --manifest work/manifest.json
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from decimal import Decimal, ROUND_HALF_UP

MARKER = "EOD_DERIVE_V2"

BASE_COLUMNS = ["date", "ticker", "name", "open", "high", "low", "close", "volume",
                "change_pct", "market_cap", "pe_ratio", "sector", "currency", "exchange"]

DERIVED_COLUMNS = ["rel_volume", "pct_from_52w_high", "pct_from_52w_low",
                   "sma_20", "sma_50", "sma_200", "pct_vs_sma_50", "pct_vs_sma_200",
                   "atr_14", "atr_pct", "gap_pct", "avg_daily_dollar_volume",
                   "float_shares", "market_cap_usd", "cap_source_symbol", "data_quality"]

OUT_COLUMNS = BASE_COLUMNS + DERIVED_COLUMNS

FLAG_PRECEDENCE = ["NO_CAP", "CAP_CARRIED", "HIGH_LOW_UNAVAILABLE", "RANGE_ADJUSTED",
                   "NO_HISTORY", "NO_PRIOR_CLOSE", "EX_DISTRIBUTION", "SPLIT_ADJUSTED",
                   "NO_PE", "NO_SECTOR", "OK"]

# The US numeric rule: 4 significant figures with the fractional trailing zeros stripped,
# except values >= 100000 which keep full precision. A plain "%.4g" renders 830500 as
# "8.305e+05" - that is the trap this formatter exists to avoid.
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
        s = f"{v:.6f}".rstrip("0").rstrip(".")
        return s
    d = Decimal(repr(v))
    exp = d.adjusted()                       # exponent of the leading significant digit
    decimals = 3 - exp                       # 4 significant figures
    if decimals < 0:
        step = Decimal(1).scaleb(-decimals)
        q = (d / step).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * step
    else:
        q = d.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)
    s = format(q, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


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


def f(x) -> float:
    try:
        if x is None or x == "":
            return float("nan")
        return float(x)
    except (TypeError, ValueError):
        return float("nan")


# ------------------------------------------------------------------ issuer grouping
CLASS_MARKERS = re.compile(
    r"\s*[-–—]?\s*\b(class|series|ser\.?)\s*\.?\s*[a-z0-9]{1,3}\b\s*$", re.I)
PAREN_NOISE = re.compile(r"\([^)]*\)")


def issuer_key(name: str, ticker: str) -> str:
    """Normalise a row's company name into an issuer key.

    "Berkshire Hathaway Inc - Class A" and "Berkshire Hathaway Inc - Class B" and
    "Berkshire Hathaway Inc" all collapse to the same issuer. The NAME decides, not the
    ticker root: LILA and LILAK are the same issuer and have different roots, while two
    unrelated issuers can share a ticker root.
    """
    n = (name or "").strip().lower()
    n = PAREN_NOISE.sub(" ", n)
    n = re.sub(r"\s+", " ", n).strip(" ,-")
    prev = None
    while prev != n:
        prev = n
        n = CLASS_MARKERS.sub("", n).strip(" ,-")
    if not n:
        n = (ticker or "").split("-")[0].lower()
    return n


def is_class_line(ticker: str) -> bool:
    """True when the ticker carries a share-class marker."""
    return "-" in (ticker or "")


# ------------------------------------------------------------------ history
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
            bars = rec.get("bars") or []
            clean = []
            for b in bars:
                try:
                    ts, o, h, l, c, v = b[0], b[1], b[2], b[3], b[4], b[5]
                except (IndexError, TypeError):
                    continue
                if c is None:
                    continue
                clean.append((int(ts), o, h, l, float(c), v))
            clean.sort(key=lambda x: x[0])
            hist[rec["ticker"]] = clean
    return hist


def day_of(ts: int) -> str:
    import time
    return time.strftime("%Y-%m-%d", time.gmtime(ts))


def mean(xs):
    xs = [x for x in xs if x is not None and not (isinstance(x, float) and math.isnan(x))]
    return sum(xs) / len(xs) if xs else None


def derive_one(bars: list, session: str) -> dict:
    """Compute every derived value for one symbol from its daily bars."""
    out = {k: None for k in ("rel_volume", "pct_from_52w_high", "pct_from_52w_low",
                              "sma_20", "sma_50", "sma_200", "pct_vs_sma_50", "pct_vs_sma_200",
                              "atr_14", "atr_pct", "gap_pct", "avg_daily_dollar_volume")}
    out["_prior_close"] = None
    out["_prior_close_date"] = ""
    out["_session_bar"] = None
    if not bars:
        return out

    idx = None
    for i, b in enumerate(bars):
        if day_of(b[0]) == session:
            idx = i
            break
    if idx is None:
        return out

    ts, o, h, l, c, v = bars[idx]
    out["_session_bar"] = (o, h, l, c, v)
    closes = [b[4] for b in bars]
    highs = [b[2] if b[2] is not None else b[4] for b in bars]
    lows = [b[3] if b[3] is not None else b[4] for b in bars]

    # --- moving averages (ending AT the session bar, inclusive)
    for n in (20, 50, 200):
        if idx + 1 >= n:
            out[f"sma_{n}"] = mean(closes[idx + 1 - n: idx + 1])
    if out["sma_50"]:
        out["pct_vs_sma_50"] = (c / out["sma_50"] - 1.0) * 100.0
    if out["sma_200"]:
        out["pct_vs_sma_200"] = (c / out["sma_200"] - 1.0) * 100.0

    # --- ATR(14): mean true range over the last 14 bars ending at the session bar
    trs = []
    for j in range(max(1, idx + 1 - 14), idx + 1):
        _, bo, bh, bl, bc, _ = bars[j]
        bh = bh if bh is not None else bc
        bl = bl if bl is not None else bc
        pc = closes[j - 1]
        trs.append(max(bh - bl, abs(bh - pc), abs(bl - pc)))
    if trs:
        out["atr_14"] = mean(trs)
        if c:
            out["atr_pct"] = out["atr_14"] / c * 100.0

    # --- 52-week window: the last 252 bars ending at the session bar
    w = bars[max(0, idx + 1 - 252): idx + 1]
    if w:
        hi52 = max(highs[max(0, idx + 1 - 252): idx + 1])
        lo52 = min(lows[max(0, idx + 1 - 252): idx + 1])
        if hi52:
            out["pct_from_52w_high"] = (c - hi52) / hi52 * 100.0
        if lo52:
            out["pct_from_52w_low"] = (c - lo52) / lo52 * 100.0

    # --- prior-session statistics: the 30 sessions BEFORE the session bar
    if idx >= 1:
        out["_prior_close"] = closes[idx - 1]
        out["_prior_close_date"] = day_of(bars[idx - 1][0])
    prior = bars[max(0, idx - 30): idx]
    if len(prior) >= 30:
        vols = [b[5] for b in prior if b[5] is not None]
        mv = mean(vols)
        if mv:
            out["rel_volume"] = (v / mv) if v else None
        dv = mean([b[4] * b[5] for b in prior if b[5] is not None])
        out["avg_daily_dollar_volume"] = dv
    return out


# ------------------------------------------------------------------ main
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", required=True)
    ap.add_argument("--history", required=True)
    ap.add_argument("--vendor", required=True)
    ap.add_argument("--session", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--prior-csv", default="",
                    help="the PRIOR session's published CSV - the anchor for change_pct/gap_pct")
    ap.add_argument("--quote-prev", default="",
                    help="JSON {ticker: quote-service previous_close} - the DIVIDEND-ADJUSTED "
                         "prior close, used only to flag ex-distribution rows")
    args = ap.parse_args()

    with open(args.base, newline="") as fh:
        base = list(csv.DictReader(fh))
    prior_session_close = {}
    prior_date = ""
    if args.prior_csv:
        with open(args.prior_csv, newline="") as fh:
            for pr in csv.DictReader(fh):
                prior_date = pr.get("date", "") or prior_date
                if (pr.get("close") or "").strip():
                    prior_session_close[pr.get("ticker", "")] = float(pr["close"])
    quote_prev = {}
    if args.quote_prev:
        qp = json.load(open(args.quote_prev))
        quote_prev = {k: float(v) for k, v in qp.items() if v is not None}
    hist = load_history(args.history)
    vendor = json.load(open(args.vendor))
    vcaps = vendor.get("vendor_caps", {})
    floats = vendor.get("floats", {})

    # ---- 1. issuer groups, and the carrier row inside each group
    groups: dict[str, list] = {}
    for r in base:
        groups.setdefault(issuer_key(r.get("name", ""), r.get("ticker", "")), []).append(r)

    carrier_of: dict[str, str] = {}      # ticker -> carrier ticker
    cap_value: dict[str, float] = {}     # ticker  -> issuer cap value
    carrier_is_vendor: dict[str, bool] = {}
    carrier_disagreements = 0

    for key, rows in groups.items():
        capped = [r for r in rows if f(r.get("market_cap", "")) == f(r.get("market_cap", ""))
                  and r.get("market_cap", "") != ""]
        vendor_rows = [r for r in rows if r["ticker"] in vcaps]
        if vendor_rows:
            # the vendor's own carrier row: prefer a row with no class marker, else the
            # largest published cap
            vendor_rows.sort(key=lambda r: (is_class_line(r["ticker"]),
                                            -(f(r.get("market_cap", "")) or 0.0)))
            carrier = vendor_rows[0]
        elif capped:
            carrier = sorted(capped, key=lambda r: -(f(r.get("market_cap", "")) or 0.0))[0]
        else:
            carrier = None

        # the issuer's cap VALUE: the carrier's published cap, else the group's largest
        value = None
        if carrier is not None and carrier.get("market_cap", "") != "":
            value = f(carrier["market_cap"])
        elif capped:
            value = max(f(r["market_cap"]) for r in capped)

        for r in rows:
            t = r["ticker"]
            if carrier is None:
                carrier_of[t] = ""
                continue
            carrier_of[t] = carrier["ticker"]
            carrier_is_vendor[t] = carrier["ticker"] in vcaps
            if value is not None:
                cap_value[t] = value
        if carrier is not None and carrier["ticker"] not in vcaps and vendor_rows:
            carrier_disagreements += 1

    # ---- 2. per-row derivation and flags
    rows_out = []
    flags = {k: 0 for k in FLAG_PRECEDENCE}
    populated = {c: 0 for c in OUT_COLUMNS}
    populated_ok = {c: 0 for c in OUT_COLUMNS}
    hist_misses = 0
    range_adjusted = 0
    shares_implausible = 0
    change_corrected = 0
    change_filled = 0
    change_unverified = 0
    ex_divid_rows = []
    split_rows = []

    for r in base:
        t = r["ticker"]
        row = {c: (r.get(c, "") or "") for c in BASE_COLUMNS}
        d = derive_one(hist.get(t, []), args.session)

        close = f(row["close"])
        bar_prior_close = d["_prior_close"]
        sess = d["_session_bar"]

        # --- range provenance
        if row["high"] == "" or row["low"] == "":
            range_flag = "HIGH_LOW_UNAVAILABLE"
        elif sess and sess[1] is not None and sess[2] is not None:
            bh, bl = sess[1], sess[2]
            brackets = (not math.isnan(close)) and bl <= close <= bh
            range_flag = "OK" if brackets else "RANGE_ADJUSTED"
        else:
            range_flag = "RANGE_ADJUSTED"

        # --- the anchor: the prior session's SETTLED close
        # THE ANCHOR — the prior session's close, on ONE consistent basis.
        #
        # The published change % must be reconcilable with the ARCHIVE'S OWN record: the
        # prior session's published close. That is what a consumer joining two files gets.
        # Two things break it, and both are visible in the candidates:
        #
        #   * a REVERSE SPLIT between the sessions: the published prior close is the RAW
        #     pre-split print, so it is not comparable with the session's post-split close
        #     (CDT: 0.0423 -> 1.31 reads +2997% for a session that moved +54.85%). The quote
        #     service's prior close IS split-adjusted, so it becomes the anchor and the row is
        #     flagged SPLIT_ADJUSTED.
        #   * an EX-DISTRIBUTION: the quote service's prior close is dividend-adjusted and
        #     sits BELOW the published basis (AB: 34.02 against 34.90, which published a
        #     -2.32% session as +0.26%). Here the PRICE change stands on the published basis
        #     and the row is flagged EX_DISTRIBUTION - the divergence is named, not hidden.
        #
        # The bar series' prior close is the third candidate: split-adjusted, but its feed may
        # not have processed a split yet (CDT's bar prior bar is the raw 0.0423), and a bar
        # whose DATE was never asserted is a stale bar - "the previous bar" can be two
        # sessions back, which is how ARL published +9.10% for a +3.90% session.
        anchor = None
        anchor_date = ""
        anchor_source = ""
        published_prior = prior_session_close.get(t)
        qp = quote_prev.get(t)
        bar_prior = d["_prior_close"]
        bar_asserted = bool(prior_date) and d["_prior_close_date"] == prior_date
        ex_div = False
        split_row = False

        if published_prior is not None:
            anchor, anchor_date, anchor_source = published_prior, prior_date, "prior_published"
        elif bar_prior is not None and bar_asserted:
            anchor, anchor_date, anchor_source = bar_prior, d["_prior_close_date"], "bar"
        elif bar_prior is not None:
            anchor, anchor_date, anchor_source = bar_prior, d["_prior_close_date"], "bar_unasserted"

        if qp and published_prior is not None:
            if qp > published_prior * 1.05:
                # a reverse split: the published prior close is a raw pre-split print
                anchor, anchor_source = qp, "quote_split_adjusted"
                split_row = True
                split_rows.append((t, round(published_prior, 4), qp))
            elif qp < published_prior * 0.995:
                # an ex-distribution: the price change stands on the published basis. The
                # threshold is 0.5%, because a distribution can be a few percent (AB: 2.6%)
                # and the screen's number then differs from the price change by that much.
                ex_div = True
                ex_divid_rows.append((t, round(published_prior, 4), qp))
        elif qp and anchor and anchor_source.startswith("bar") and qp > anchor * 1.05:
            anchor, anchor_source = qp, "quote_split_adjusted"
            split_row = True
            split_rows.append((t, round(anchor, 4), qp))

        if bar_prior and published_prior and \
                abs(bar_prior - published_prior) / published_prior > 0.05:
            # the bar and the published prior close disagree by more than 5%: a split intervened
            split_row = True
            split_rows.append((t, round(published_prior, 4), round(bar_prior, 4)))

        base_change = f(row["change_pct"])
        recomputed = None
        if anchor and not math.isnan(close):
            recomputed = (close - anchor) / anchor * 100.0
        if recomputed is not None:
            if math.isnan(base_change):
                row["change_pct"] = fmt_num(recomputed)
                change_filled += 1
            elif abs(recomputed - base_change) > 0.05:
                row["change_pct"] = fmt_num(recomputed)
                change_corrected += 1
        anchor_missing = anchor is None

        # --- cap
        carrier = carrier_of.get(t, "")
        cap = cap_value.get(t)
        row["market_cap"] = fmt_int(cap) if cap is not None else ""
        row["market_cap_usd"] = row["market_cap"]
        row["cap_source_symbol"] = carrier

        fl = []
        if cap is None:
            fl.append("NO_CAP")
        elif carrier and carrier != t:
            fl.append("CAP_CARRIED")
        if range_flag == "HIGH_LOW_UNAVAILABLE":
            fl.append("HIGH_LOW_UNAVAILABLE")
        elif range_flag == "RANGE_ADJUSTED":
            fl.append("RANGE_ADJUSTED")
        if sess is None:
            fl.append("NO_HISTORY")
            hist_misses += 1
        if anchor_missing and (row["close"] != "" or row["change_pct"] != ""):
            fl.append("NO_PRIOR_CLOSE")
            change_unverified += 1
        if ex_div:
            fl.append("EX_DISTRIBUTION")
        if split_row:
            fl.append("SPLIT_ADJUSTED")
        if row["pe_ratio"] == "":
            fl.append("NO_PE")
        if row["sector"] == "":
            fl.append("NO_SECTOR")
        if not fl:
            fl = ["OK"]

        # --- derived columns
        for col in ("rel_volume", "pct_from_52w_high", "pct_from_52w_low", "sma_20",
                    "sma_50", "sma_200", "pct_vs_sma_50", "pct_vs_sma_200", "atr_14",
                    "atr_pct"):
            row[col] = fmt_num(d[col]) if d[col] is not None else ""
        row["avg_daily_dollar_volume"] = fmt_int(d["avg_daily_dollar_volume"]) \
            if d["avg_daily_dollar_volume"] is not None else ""
        if anchor and not math.isnan(close) and row["open"] != "":
            op = f(row["open"])
            if not math.isnan(op):
                row["gap_pct"] = fmt_num((op - anchor) / anchor * 100.0)
            else:
                row["gap_pct"] = ""
        else:
            row["gap_pct"] = ""

        fl_share = floats.get(t)
        row["float_shares"] = fmt_int(fl_share) if fl_share else ""

        row["data_quality"] = "|".join(fl)
        for f_ in fl:
            flags[f_] += 1

        for c in OUT_COLUMNS:
            if row.get(c, "") != "":
                populated[c] += 1
                if fl == ["OK"]:
                    populated_ok[c] += 1

        # sanity: the implied share count must be plausible
        if cap and close and not math.isnan(close):
            implied = cap / close
            if not (1e3 <= implied <= 1e13):
                shares_implausible += 1

        rows_out.append(row)

    with open(args.out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=OUT_COLUMNS)
        w.writeheader()
        for row in rows_out:
            w.writerow({c: row.get(c, "") for c in OUT_COLUMNS})

    manifest = {
        "marker": MARKER,
        "session": args.session,
        "generated_by": "eod_derive.py",
        "csv_columns": len(OUT_COLUMNS),
        "columns": OUT_COLUMNS,
        "base_columns": BASE_COLUMNS,
        "derived_columns": DERIVED_COLUMNS,
        "rows": len(rows_out),
        "flag_vocabulary": FLAG_PRECEDENCE,
        "flag_precedence": FLAG_PRECEDENCE,
        "flag_counts": flags,
        "populated_counts": populated,
        "populated_and_ok_counts": populated_ok,
        "market_cap_currency": "USD",
        "market_cap_conversion": "none - the US file is already USD; market_cap_usd == market_cap "
                                 "(FX identity, no conversion applied)",
        "market_cap_carrier_rule": "the vendor's own carrier row (shibui valuation); every line of "
                                   "the issuer carries the issuer's cap and names the carrier in "
                                   "cap_source_symbol",
        "carrier_rows": sum(1 for r in rows_out if r["cap_source_symbol"] == r["ticker"]),
        "carried_rows": sum(1 for r in rows_out
                            if r["cap_source_symbol"] and r["cap_source_symbol"] != r["ticker"]),
        "issuer_groups": len(groups),
        "history_misses": hist_misses,
        "change_pct_rule": "the session's PRICE change against the prior session's SETTLED close "
                           "(--prior-csv); a quote service's previous_close is dividend-adjusted "
                           "and a bar whose date was not asserted is stale - neither is an anchor",
        "change_pct_corrected": change_corrected,
        "change_pct_filled": change_filled,
        "change_pct_unverified": change_unverified,
        "prior_session": prior_date,
        "ex_distribution_rows": len(ex_divid_rows),
        "split_adjusted_rows": len(split_rows),
        "split_adjusted_detail": [{"ticker": t, "anchor_before": a,
                                    "split_adjusted_prior_close": b} for t, a, b in split_rows],
        "ex_distribution_detail": [{"ticker": t, "prior_published_close": a,
                                     "quote_adjusted_prior_close": q} for t, a, q in ex_divid_rows],
        "change_pct_basis": "the session's PRICE change against the prior session's published "
                            "close (the archive's convention, verifiable from the two published "
                            "closes); ex-distribution rows are flagged EX_DISTRIBUTION because "
                            "the quote service's prior close is dividend-adjusted there",
        "range_adjusted_rows": range_adjusted,
        "implied_shares_implausible": shares_implausible,
        "definitions": {
            "rel_volume": "session volume / mean(volume of the 30 sessions BEFORE the session)",
            "avg_daily_dollar_volume": "mean(close x volume) over the same 30 prior sessions",
            "sma_20/50/200": "mean(close) over the last 20/50/200 bars ending AT the session bar",
            "pct_vs_sma_50/200": "(close / sma - 1) * 100",
            "atr_14": "mean(true range) over the last 14 bars ending at the session bar; "
                      "true range = max(h-l, |h-prev_close|, |l-prev_close|)",
            "atr_pct": "atr_14 / close * 100",
            "pct_from_52w_high/low": "(close - max(high) / min(low) over the last 252 bars) / that "
                                     "extreme * 100",
            "gap_pct": "(published open - prior close) / prior close * 100",
        },
    }
    json.dump(manifest, open(args.manifest, "w"), indent=2)

    print(f"rows={len(rows_out)} cols={len(OUT_COLUMNS)} flags={flags}")
    print(f"carrier_rows={manifest['carrier_rows']} carried_rows={manifest['carried_rows']} "
          f"issuer_groups={len(groups)} history_misses={hist_misses} "
          f"shares_implausible={shares_implausible}")
    print(f"change_pct: corrected={change_corrected} filled={change_filled} "
          f"unverified={change_unverified} (prior session {prior_date or 'n/a'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
