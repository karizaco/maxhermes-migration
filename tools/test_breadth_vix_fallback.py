#!/usr/bin/env python3
"""Regression tests for cron #10's breadth helper — the volatility pair and the
degraded-source count.

Two defects, both measured on the 2026-11-19 14:00 ET fire (reconstructed
2026-11-20):

1. `fetch_vix_pair()` had NO fallback. The Cboe delayed-quote CDN
   (`cdn.cboe.com/api/global/delayed_quotes/quotes/_VIX.json`) answers HTTP 403
   - a Cloudflare "Attention Required" interstitial - from this egress, for every
   User-Agent. `_fetch_vix_once()` swallows the failure, so the pair came back
   NULL: the regime's `uncertainty` flag silently read `false` and the artifact
   published a volatility-less breadth read. Cron #09's pipeline got the same
   fallback on the same day (commit 335cb99); cron #10 did not. The pair now
   falls back to Yahoo's chart API, PINNED to the fire day and the fire clock so
   a delayed replay publishes the print that existed at the fire, and the
   published `source` names the source that actually served the numbers.

2. The artifact published no `degraded_sources` count, so the reply's `errors:`
   had nothing to reconcile against. The renderer now writes the count into the
   front matter when the live layer supplies it, and omits it otherwise.

Run:  python3 tools/test_breadth_vix_fallback.py
"""

from __future__ import annotations

import datetime as _dt
import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HELPER = REPO / "cloud-prompts" / "skills" / "stock-screener-suite" / "scripts" / "breadth_metrics.py"

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))


def load_helper():
    spec = importlib.util.spec_from_file_location("breadth_metrics_t", HELPER)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


ET = _dt.timezone(_dt.timedelta(hours=-5))
FIRE_DAY = _dt.date(2026, 11, 19)


def _stamp(hour: int, minute: int, day: _dt.date = FIRE_DAY) -> _dt.datetime:
    return _dt.datetime(day.year, day.month, day.day, hour, minute, tzinfo=ET)


def synthetic_bars():
    """Five-minute bars for the 2026-11-18 and 2026-11-19 sessions.

    ^VIX carries a pre-market bar and a 16:15 settle; ^VIX3M runs 09:30-16:00.
    The two series must still resolve to the SAME bar at the fire clock.
    """
    vix = []
    vix3m = []
    for minute in (9 * 60 + 45, 10 * 60, 12 * 60, 14 * 60, 15 * 60, 16 * 60):
        vix.append((_stamp(minute // 60, minute % 60), 24.0 + minute / 1000))
        vix3m.append((_stamp(minute // 60, minute % 60), 23.0 + minute / 1000))
    # the prior session, so the change percentage has a base
    vix.append((_stamp(16, 0, FIRE_DAY - _dt.timedelta(days=1)), 24.56))
    vix3m.append((_stamp(16, 0, FIRE_DAY - _dt.timedelta(days=1)), 24.24))
    return vix, vix3m


def main() -> int:
    mod = load_helper()
    vix_bars, vix3m_bars = synthetic_bars()

    blocked = {"vix": None, "vix3m": None, "quote_time_et": None, "source": "unavailable",
               "prev_close": {}, "price_change_pct": {}, "session_mode": None,
               "quote_date": None}

    # ---- 1. the CDN is blocked -> the fallback serves the pair ----------------
    real_once = mod._fetch_vix_once
    real_bars = getattr(mod, "_yahoo_bars", None)
    mod._fetch_vix_once = lambda *a, **k: dict(blocked)

    def fetch(**kw):
        """Call the helper's pair fetch, tolerating an UNPATCHED signature."""
        try:
            return mod.fetch_vix_pair(**kw)
        except TypeError as exc:
            check("the helper accepts the pinned fallback arguments", False,
                  f"{exc} — the helper predates the fallback")
            return {}

    if real_bars is None:
        check("the helper HAS a Yahoo fallback (_yahoo_bars)", False,
              "the module has no _yahoo_bars — the volatility pair has no fallback")
        mod._yahoo_bars = lambda sym, p1, p2, iv: []
    else:
        mod._yahoo_bars = lambda sym, p1, p2, iv: (vix3m_bars if "VIX3M" in sym else vix_bars)
    try:
        pair = fetch(session_date="2026-11-19", fire_time_et="14:00:46")
        check("the blocked CDN does not produce a null pair", pair.get("vix") is not None, str(pair)[:160])
        check("the fallback serves the VIX print at the fire clock",
              pair.get("quote_time_et", "").startswith("2026-11-19 14:00"), str(pair.get("quote_time_et")))
        check("the published source names the fallback",
              "FALLBACK" in str(pair.get("source", "")), str(pair.get("source"))[:120])
        check("the CDN block is recorded on the pair", pair.get("cboe_blocked") is True,
              str(pair.get("cboe_blocked")))
        check("both symbols carry the SAME bar stamp",
              pair.get("vix") is not None and pair.get("vix3m") is not None,
              f"{pair.get('vix')} / {pair.get('vix3m')}")

        # ---- 2. the pair is PINNED to the fire clock --------------------------
        later = fetch(session_date="2026-11-19", fire_time_et="16:00:00")
        check("a different fire clock reads a different bar",
              later.get("quote_time_et", "").startswith("2026-11-19 16:00"),
              str(later.get("quote_time_et")))
        check("the pinned pair is not the newest bar",
              pair.get("quote_time_et") != later.get("quote_time_et"),
              f"{pair.get('quote_time_et')} vs {later.get('quote_time_et')}")

        # ---- 3. a session with no bar is REFUSED, not faked -------------------
        try:
            fetch(session_date="2026-11-25", fire_time_et="14:00:00")
            check("a session with no bar is refused, not faked", False, "no error raised")
        except Exception as exc:
            check("a session with no bar is refused, not faked", True, str(exc)[:80])
        excepted = True

        # ---- 4. an explicit override wins over the fallback -------------------
        override = {"vix": 27.56, "vix3m": 26.37, "quote_time_et": "2026-11-19 14:00:00 ET",
                    "source": "agent-supplied pinned pair", "session_mode": "replay"}
        got = fetch(session_date="2026-11-19", fire_time_et="14:00:46", override=override)
        check("an explicit override wins over the fallback",
              got.get("vix") == 27.56 and got.get("vix3m") == 26.37,
              f"{got.get('vix')} / {got.get('vix3m')}")
        check("the override's own source string is published",
              "pinned pair" in str(got.get("source", "")), str(got.get("source"))[:80])
    finally:
        mod._fetch_vix_once = real_once
        if real_bars is not None:
            mod._yahoo_bars = real_bars

    # ---- 5. the CDN path still wins when it serves ---------------------------
    serving = dict(blocked)
    serving.update({"vix": 23.54, "vix3m": 23.53, "quote_time_et": "2026-11-19 13:47:31 ET",
                    "source": "Cboe delayed-quote CDN (_VIX.json / _VIX3M.json)",
                    "session_mode": "regular hours — live print"})
    mod._fetch_vix_once = lambda *a, **k: dict(serving)
    try:
        pair = fetch(session_date="2026-11-19", fire_time_et="14:00:46")
        check("a CDN that serves the pair is not overridden by the fallback",
              pair.get("vix") == 23.54 and "Cboe" in str(pair.get("source")),
              f"{pair.get('vix')} / {pair.get('source')}")
        check("the CDN path does not claim to be blocked", not pair.get("cboe_blocked"),
              str(pair.get("cboe_blocked")))
    finally:
        mod._fetch_vix_once = real_once

    # ---- 6. the regime flag reads the pair it was given ---------------------
    rows = [
        {"metric": "largecap_breadth", "breadth_pct_largecap": 37.24},
        {"metric": "index_above_sma_summary", "pct_above_sma_20": 0.0},
        {"metric": "index_atr_extension", "ticker": "SPY", "extension_pct": -4.24},
    ]
    inverted = mod.compute_regime(rows, 27.56, 26.37)
    check("an inverted term structure sets uncertainty", inverted["uncertainty"] is True,
          str(inverted["uncertainty"]))
    flat = mod.compute_regime(rows, 26.37, 27.56)
    check("a normal term structure clears uncertainty", flat["uncertainty"] is False,
          str(flat["uncertainty"]))
    check("the size cut fires on the index and the breadth together",
          inverted["size_cut_pct"] == 50, str(inverted["size_cut_pct"]))
    check("late_cycle reads the ATR map (the `ticker` key trap)",
          "SPY" in inverted["atr_extensions"], str(inverted["atr_extensions"]))

    # ---- 7. the degraded-source count travels with the artifact -------------
    metrics = {
        "data_date": "2026-11-18",
        "breadth": {"pct_above_sma_20": 37.24, "pctile_1y": 16.7, "band": "BELOW_NORMAL",
                    "pct_above_sma_50": 51.82, "pctile_1y_50dma": 31.9, "band_50dma": "NORMAL"},
        "divergence": {"pp": 37.24, "band": "BROAD", "pctile_1y": 87.8,
                       "history_5d": [{"date": f"2026-11-{d:02d}", "pp": 1.0} for d in range(12, 17)]},
        "advance_decline": {"advancing": 381, "declining": 494, "unchanged": 3, "ad_ratio": 0.771,
                            "ad_net": -113, "ad_net_10d": -1256, "ad_ratio_10d": 0.749,
                            "adl_slope_10d": -72.41, "adl_since_start": -1939.0,
                            "adl_base_date": "2026-08-25", "adl_window_start": "2026-11-05",
                            "adl_window_end": "2026-11-18"},
        "index_etfs": {"symbols": ["SPY"], "n_etf": 5, "n_above_sma_20": 0, "n_above_sma_50": 1,
                       "pct_above_sma_20": 0.0, "pctile_1y": 16.0},
        "universe": {"filter": "NYSE/NASDAQ/AMEX, market cap > $10B", "n": 878,
                     "market_cap_floor": 10_000_000_000},
        "regime": inverted,
        "history": {"sessions": 263, "start": "2025-11-03", "end": "2026-11-18", "lookback_days": 380},
        "series": [{"date": "2026-11-18", "n_lc": 878, "pct_above_sma_20": 37.24,
                    "pct_above_sma_50": 51.82, "n_etf_above_sma_20": 0, "n_etf_above_sma_50": 1,
                    "n_etf": 5, "breadth_divergence_pp": 37.24, "advancing": 381, "declining": 494,
                    "unchanged": 3, "ad_net": -113, "adl_cum": -1939.0, "adl_slope_10d": -72.41,
                    "breadth_pctile_1y": 16.7, "divergence_pctile_1y": 87.8}],
        "etf_positioning": [],
        "vix": {"vix": 27.56, "vix3m": 26.37, "quote_time_et": "2026-11-19 14:00:00 ET",
                "source": "Yahoo fallback"},
    }
    live = {k: "x" for k in ("fire_time_et", "live_date", "vix_quote_time", "vix_pair",
                             "banner", "tldr", "tape_block", "volatility_block",
                             "flags_block", "method_block")}
    md_with = mod.render_markdown(metrics, dict(live, degraded_sources=2))
    check("the front matter publishes the degraded-source count",
          "degraded_sources: 2" in md_with, md_with[:400])
    md_without = mod.render_markdown(metrics, live)
    check("the count is omitted when the live layer does not supply one",
          "degraded_sources:" not in md_without, md_without[:400])

    # ---- report -------------------------------------------------------------
    failed = [r for r in results if not r[1]]
    for name, ok, detail in results:
        print(("OK   " if ok else "FAIL ") + name + (f"   [{detail}]" if detail and not ok else ""))
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        print("FAILURES:")
        for name, _ok, detail in failed:
            print(f"  - {name}  [{detail}]")
        return 1
    print("OK: cron #10 breadth volatility fallback and degraded-source count")
    return 0


if __name__ == "__main__":
    sys.exit(main())
