#!/usr/bin/env python3
"""
test_preopen_capture_anchor.py — the capture's ANCHOR states, end to end.

THE DEFECT THIS FILE EXISTS FOR. The anchor guard checks the tape's implied reference
against the scanner's own `close` column:

    premarket_close / (1 + premarket_change/100)  ==  close

That invariant holds ONLY while the PRE-MARKET session is live. At the 09:30 ET open
the scanner ROLLS the `close` column to the LIVE regular-session price and freezes the
pre-market columns, so the invariant cannot hold after the open. Cron #92b is scheduled
`50 9 * * 1-5` ET - twenty minutes after the open - so the guard refused every weekday
and called a live, trading market "closed" (measured 2026-11-27 09:50 ET: 100 of 1142
priced rows agreed, 8.8% against a 90% floor).

So the capture now takes its own second sample and asks the scanner whether its figures
MOVED: a settled close does not move, a live price does. These cases drive the real
`build()` in all three states and require it to behave.

  1. ALIGNED - pre-open. The anchor agrees; the tape is published with the scanner's own
     close as its anchor.
  2. ROLLED  - post-open. The anchor disagrees BUT the scanner's figures are moving, so
     the regular session is open and the tape is published with the provider's IMPLIED
     reference as its anchor.
  3. STALE   - the market is shut. The anchor disagrees and nothing moved, so the
     capture writes NO tape and declines.

Run:  python3 -B tools/test_preopen_capture_anchor.py
"""

import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "cloud-prompts", "_shared"))

import preopen_capture as pc  # noqa: E402

RESULTS = []


def record(name, ok, detail=""):
    RESULTS.append((name, ok))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


def band_rows(n=60, live_close=True):
    """A band of movers whose pre-market prints are anchored on `base`."""
    rows = {}
    for i in range(n):
        tk = f"T{i:03d}"
        price = 10.0 + i
        pct = 5.0 + i
        # The reference the pre-market move was measured against.
        base = price / (1.0 + pct / 100.0)
        rows[tk] = {
            "pct": pct, "price": price, "volume": 500000, "name": tk,
            "exchange": "NASDAQ",
            # Pre-open the scanner's `close` IS that reference; after the open it is a
            # LIVE price instead.
            "ref_close": (base * 1.02) if live_close else base,
            "reg_volume": 1000 + i,
        }
    return rows


def stub_everything(band, second_sample):
    """Replace every network call in the capture with a stub."""
    pc.call_trending = lambda: {"rows": []}
    pc.call_top_movers = lambda category="gainers", limit=40: {"movers": {}}
    pc.call_scanner_band = lambda pct=pc.BAND_PCT, limit=1000: {
        "rows": band, "up": len(band), "down": 0, "total": len(band), "truncated": []}
    pc.call_scanner_premarket = lambda tickers: {"rows": {}, "total": 0, "requested": 0}
    pc.call_scanner_closes = lambda tickers: {"rows": second_sample}
    pc.resolve_catalysts = lambda pool, run_dt, top_n, pool_names, pool_pcts: {}
    # No waiting in a test.
    pc.time = types.SimpleNamespace(sleep=lambda s: None)


def second_sample_from(band, moved):
    """The probe's second sample: the same names, moving or not."""
    out = {}
    for tk, r in band.items():
        c = r["ref_close"]
        v = r.get("reg_volume")
        if moved:
            c = c * 1.004
            v = (v or 0) + 17
        out[tk] = {"close": c, "volume": v}
    return out


def main():
    print("the capture's ANCHOR states:")

    # ---------------------------------------------------------------- 1. ALIGNED
    band = band_rows(live_close=False)
    stub_everything(band, second_sample_from(band, moved=False))
    res = pc.build("2026-11-28", "0830", top_n=20)
    ok = (not res.get("market_closed")) and res.get("rows")
    modes = {r.get("ref_mode") for r in (res.get("rows") or [])}
    ok = ok and modes == {"aligned"}
    priced = [r for r in (res.get("rows") or []) if r.get("pct") is not None]
    # In the aligned state the anchor IS the scanner's own close, and it agrees with
    # the row's own implied reference.
    agree = [r for r in priced
             if abs(r["price"] / (1.0 + r["pct"] / 100.0) - r["ref_close"]) / r["ref_close"] <= 0.005]
    ok = ok and priced and len(agree) == len(priced)
    record("a pre-open tape is published with the scanner's own close as its anchor",
           bool(ok), f"rows={len(res.get('rows') or [])} modes={modes} "
                     f"anchor_agrees={len(agree)}/{len(priced)}")

    # ----------------------------------------------------------------- 2. ROLLED
    band = band_rows(live_close=True)
    stub_everything(band, second_sample_from(band, moved=True))
    res = pc.build("2026-11-28", "0950", top_n=20)
    ok = (not res.get("market_closed")) and res.get("rows")
    modes = {r.get("ref_mode") for r in (res.get("rows") or [])}
    ok = ok and modes == {"rolled"}
    priced = [r for r in (res.get("rows") or []) if r.get("pct") is not None]
    # The anchor is the IMPLIED reference, and the scanner's live price rides beside
    # it, DIFFERING from it - that difference is the evidence.
    good = [r for r in priced
            if abs(r["price"] / (1.0 + r["pct"] / 100.0) - r["ref_close"]) / r["ref_close"] <= 0.005
            and r.get("ref_scanner_close") is not None
            and abs(r["ref_scanner_close"] - r["ref_close"]) / r["ref_close"] > 0.005]
    ok = ok and priced and len(good) == len(priced)
    record("a POST-OPEN tape is published with the implied reference as its anchor",
           bool(ok), f"rows={len(res.get('rows') or [])} modes={modes} "
                     f"evidence={len(good)}/{len(priced)}")

    # ----------------------------------------------------------------- 3. STALE
    band = band_rows(live_close=True)
    stub_everything(band, second_sample_from(band, moved=False))
    res = pc.build("2026-11-26", "0830", top_n=20)
    ok = bool(res.get("market_closed")) and not res.get("rows")
    reason = res.get("reason") or ""
    ok = ok and "roll probe confirms it" in reason
    record("a SHUT market is still REFUSED - the marker, and no tape", bool(ok),
           f"market_closed={res.get('market_closed')} reason={reason[:110]}")

    failed = [r for r in RESULTS if not r[1]]
    print()
    print(f"{len(RESULTS) - len(failed)}/{len(RESULTS)} cases behaved as required")
    if failed:
        for name, _ in failed:
            print(f"  - {name}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
