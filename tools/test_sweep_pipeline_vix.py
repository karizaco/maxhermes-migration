#!/usr/bin/env python3
"""Regression tests for cron #09's sweep pipeline — the volatility pair and
the regime prose.

Two defects, both measured on the 2026-11-19 18:30 ET fire:

1. `fetch_vix_pair()` had NO fallback. The Cboe delayed-quote CDN
   (`cdn.cboe.com/api/global/delayed_quotes/quotes/_VIX.json`) answered
   HTTP 403 - a Cloudflare "Attention Required" interstitial - from the
   Cloud egress, and the unhandled exception killed the whole pipeline at
   the breadth stage: the fire produced NO artifact at all. The pair now
   falls back to Yahoo's chart API, with BOTH symbols read from the SAME
   session bar and pinned to the cron day, and the published `source` names
   the source that actually served the numbers.

2. The regime renderer printed the size-cut fact as a LITERAL ("breadth
   {x}% is far above the 40% trigger"). On a session with breadth 21.20% -
   BELOW the trigger, with the index below its 20-DMA, so the size cut IS
   on (`size_cut_pct: 50`) - that literal told the reader the opposite of
   what the published flag said, in the same cell. The `uncertainty` rule
   cell had the mirror defect ("VIX/VIX3M = 1.0522 <= 1" while the flag
   fires ABOVE 1.0). Both cells are now computed from the data.

Run:  python3 tools/test_sweep_pipeline_vix.py
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PIPELINE = REPO / "tools" / "sweep_pipeline.py"

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))


def load_pipeline():
    spec = importlib.util.spec_from_file_location("sweep_pipeline_t", PIPELINE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def yahoo_payload(sym_close: dict[str, list[tuple[int, float]]], meta_time: int) -> bytes:
    """A minimal Yahoo chart-API body: timestamps + closes, plus meta."""
    ts = []
    closes = []
    for t, c in sym_close["_ts"]:
        ts.append(t)
        closes.append(c)
    return json.dumps({
        "chart": {"result": [{
            "meta": {"symbol": "VIX", "regularMarketTime": meta_time},
            "timestamp": ts,
            "indicators": {"quote": [{"close": closes}]},
        }], "error": None}
    }).encode()


def main() -> int:
    mod = load_pipeline()

    # ---- 1. the size-cut prose is computed, not asserted -------------------
    on = mod._size_cut_note({"size_cut_pct": 50}, 21.20)
    check("size cut on is stated from the data", "ON" in on and "21.20" in on, on)
    check("size cut on names the trigger direction", "UNDER" in on, on)
    off = mod._size_cut_note({"size_cut_pct": 0}, 55.0)
    check("size cut off is stated from the data", "off" in off and "55.00" in off, off)

    # the published flag must never contradict its own explanation
    for flag, breadth, want_on in ((50, 21.20, True), (0, 55.0, False),
                                    (50, 45.0, True), (0, 21.2, False)):
        note = mod._size_cut_note({"size_cut_pct": flag}, breadth)
        says_on = "size cut is ON" in note
        check(f"flag {flag} at breadth {breadth} renders consistently",
              says_on == want_on, note)

    # ---- 2. the VIX fallback, with the network stubbed ---------------------
    # Two daily bars: 2026-11-18 and 2026-11-19, anchored the way Yahoo
    # anchors them (08:00Z for ^VIX, 14:30Z for ^VIX3M).
    import datetime as _dt

    def _anchor(day: str, hour_utc: int) -> int:
        d = _dt.date.fromisoformat(day)
        return int(_dt.datetime(d.year, d.month, d.day, hour_utc,
                                 tzinfo=_dt.timezone.utc).timestamp())

    ts = [_anchor("2026-11-18", 8), _anchor("2026-11-19", 8)]
    closes = [24.56, 28.44]
    ts3 = [_anchor("2026-11-18", 14), _anchor("2026-11-19", 14)]

    def fake_urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "cdn.cboe.com" in url:
            raise OSError("HTTP Error 403: Forbidden")
        if "%5EVIX3M" in url:
            body = json.dumps({"chart": {"result": [{
                "meta": {"symbol": "VIX3M", "regularMarketTime": 1795154400},
                "timestamp": ts3, "indicators": {"quote": [{"close": [24.29, 27.03]}]},
            }]}}).encode()
        else:
            body = json.dumps({"chart": {"result": [{
                "meta": {"symbol": "VIX", "regularMarketTime": 1795154400},
                "timestamp": ts, "indicators": {"quote": [{"close": closes}]},
            }]}}).encode()
        return FakeResponse(body)

    real_urlopen = mod.urllib.request.urlopen
    mod.urllib.request.urlopen = fake_urlopen
    try:
        pair = mod.fetch_vix_pair(session_date="2026-11-19")
        check("the Cboe 403 does not kill the run", isinstance(pair, dict), str(pair)[:120])
        check("the fallback serves the VIX close", pair.get("vix") == 28.44, str(pair.get("vix")))
        check("the fallback serves the VIX3M close", pair.get("vix3m") == 27.03, str(pair.get("vix3m")))
        check("the published source names the fallback",
              "FALLBACK" in str(pair.get("source", "")), str(pair.get("source"))[:120])
        check("the prior close is carried for both symbols",
              pair.get("vix_prev_close") == 24.56 and pair.get("vix3m_prev_close") == 24.29,
              f"{pair.get('vix_prev_close')} / {pair.get('vix3m_prev_close')}")
        check("the change percentage is computed", round(pair.get("vix_change_pct"), 2) == 15.80,
              str(pair.get("vix_change_pct")))
        check("the fallback reason is recorded", "403" in str(pair.get("cboe_fallback_reason", "")),
              str(pair.get("cboe_fallback_reason"))[:80])

        # a replay on a later day must NOT publish a stale pair
        try:
            mod.fetch_vix_pair(session_date="2026-11-25")
            check("a session with no bar is refused, not faked", False, "no error raised")
        except Exception as exc:
            check("a session with no bar is refused, not faked", "no daily bar" in str(exc), str(exc)[:100])
    finally:
        mod.urllib.request.urlopen = real_urlopen

    # ---- 3. the Cboe path still works when it is reachable ----------------
    def cboe_urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        sym = "_VIX3M" if "_VIX3M" in url else "_VIX"
        close = 27.03 if sym == "_VIX3M" else 28.44
        prev = 24.29 if sym == "_VIX3M" else 24.56
        return FakeResponse(json.dumps({"data": {
            "close": close, "prev_day_close": prev,
            "last_trade_time": "2026-11-19T16:15:01",
            "price_change_percent": 11.28 if sym == "_VIX3M" else 15.80,
        }}).encode())

    mod.urllib.request.urlopen = cboe_urlopen
    try:
        pair = mod.fetch_vix_pair(session_date="2026-11-19")
        check("the Cboe path is still the primary source",
              "Cboe delayed-quote CDN" in str(pair.get("source", "")), str(pair.get("source"))[:100])
        check("the Cboe pair carries the same numbers", pair.get("vix") == 28.44, str(pair.get("vix")))
    finally:
        mod.urllib.request.urlopen = real_urlopen

    failed = [(n, d) for n, ok, d in results if not ok]
    for name, ok, detail in results:
        print(("  PASS  " if ok else "  FAIL  ") + name + (f"  [{detail}]" if detail else ""))
    if failed:
        print(f"\n{len(failed)} of {len(results)} checks FAILED")
        return 1
    print(f"\nAll {len(results)} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
