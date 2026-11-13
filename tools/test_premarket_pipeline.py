#!/usr/bin/env python3
"""
test_premarket_pipeline.py — OFFLINE regression tests for the cron #08 v6 pipeline.

A gate that has never been observed failing is a claim. These tests pin the
three behaviours the 2026-11-12 run analysis asked for, so a future edit that
breaks them fails here instead of shipping a wrong artifact:

  1. the tape pull stops as soon as the cached vintage STOPS CHANGING (min 2),
     and keeps pulling while it rotates - the measured behaviour that cut 36
     of 48 requests with identical output;
  2. `tape_lag_min` measures the print's age against the wall clock, and
     `driver_class` names the structural driver of a gap;
  3. the renderer produces an artifact the contract checker ACCEPTS, from the
     engine's own data (no hand-typed numbers).

USAGE
    python3 tools/test_premarket_pipeline.py
Exit 0 = all checks passed; 1 = at least one failure (each is printed).
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
ET = ZoneInfo("America/New_York")

FAILURES = []
CHECKS = 0


def ok(msg):
    global CHECKS
    CHECKS += 1
    print(f"  ok   {msg}")


def bad(msg):
    global CHECKS
    CHECKS += 1
    FAILURES.append(msg)
    print(f"  FAIL {msg}")


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def find_repo_file(rel):
    """Find an engine file in the repo layout OR beside the test.

    The test runs from the repo (tools/test_premarket_pipeline.py) and also from
    a sandbox that has only fetched the scripts (tools/premarket_pull.py), so
    both layouts are tried.
    """
    candidates = [
        ROOT / rel,
        HERE.parent / "cloud-prompts" / "skills" / "stock-screener-suite" / rel,
        HERE.parent / "cloud-prompts" / "skills" / "stock-screener-suite" / "scripts"
        / Path(rel).name,
        HERE / Path(rel).name,
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


PULL = None
RENDER = None
CHECK = None


def test_adaptive_pulls():
    """The pull must stop at min_pulls when the cached vintage is stable."""
    print("[adaptive pulls]")
    calls = {"n": 0}

    def fake_pull(sym, bust, asset_class="stocks"):
        calls["n"] += 1
        return {"prints": [{"time": "08:19:19", "minutes": 8 * 60 + 19, "price": 10.0,
                            "vol": 100}],
                "newest": {"time": "08:19:19", "minutes": 8 * 60 + 19, "price": 10.0,
                           "vol": 100},
                "consol_raw": "$10.00 0.00 (0.00%)", "consol_price": 10.0,
                "consol_pct": 0.0, "counter_vol": 1000, "pm_high": "$10.10",
                "pm_low": "$9.90", "tape_rows": 10, "cache_hit": "3001",
                "updated": "x"}

    PULL._pull_tape = fake_pull
    PULL.time.sleep = lambda *_: None
    calls["n"] = 0
    best, seen = PULL._best_tape("AAA", 4)
    if calls["n"] == 2:
        ok(f"a STABLE cached vintage stops the loop at 2 pulls (not 4) - {calls['n']} requests")
    else:
        bad(f"a stable cached vintage made {calls['n']} pulls, expected 2")

    # a ROTATING cache must keep being asked: that is the case the rule exists for
    state = {"i": 0}

    def rotating_pull(sym, bust, asset_class="stocks"):
        state["i"] += 1
        m = 8 * 60 + 19 + state["i"]
        return {"prints": [{"time": "%02d:%02d:%02d" % (m // 60, m % 60, 0), "minutes": m,
                            "price": 10.0, "vol": 100}],
                "newest": {"time": "%02d:%02d:%02d" % (m // 60, m % 60, 0), "minutes": m,
                           "price": 10.0, "vol": 100},
                "consol_raw": "$10.00", "consol_price": 10.0, "consol_pct": 0.0,
                "counter_vol": 1000, "pm_high": "$10.10", "pm_low": "$9.90",
                "tape_rows": 10, "cache_hit": "3001", "updated": "x"}

    PULL._pull_tape = rotating_pull
    state["i"] = 0
    best, seen = PULL._best_tape("AAA", 4)
    if len(seen) == 4:
        ok("a ROTATING cache is still pulled to the cap (4) and the newest vintage wins")
    else:
        bad(f"a rotating cache produced {len(seen)} pulls, expected 4")
    if best and best["newest"]["minutes"] == max(s["newest"]["minutes"] for s in seen):
        ok("the newest internal timestamp wins")
    else:
        bad("the newest internal timestamp did NOT win")
    PULL._pull_tape = getattr(PULL, "_pull_tape", None)


def test_lag():
    print("[tape lag]")
    # 08:19:19 is 20 minutes behind 08:39:19
    PULL._now_et = lambda: datetime(2026, 11, 12, 8, 39, 19, tzinfo=ET)
    lag = PULL._lag_minutes("08:19:19")
    if lag is not None and abs(lag - 20.0) < 0.01:
        ok(f"tape_lag_min measures the print's age ({lag} min)")
    else:
        bad(f"tape_lag_min returned {lag}, expected 20.0")
    if PULL._lag_minutes(None) is None:
        ok("a missing print has no lag (n/a), not a zero")
    else:
        bad("a missing print produced a lag")


def test_driver_class():
    print("[driver class]")
    proxies = {"SPY": {"premarket_change": -1.0}, "XLK": {"premarket_change": -2.5},
               "SMH": {"premarket_change": -4.0}}
    crypto = {"overnight_pct": -3.0, "from_et": "11-11 16:00 ET"}
    recs = {
        "MARA": {"tv_pm_pct": -5.5, "tv_sector": "Technology Services"},
        "AAA": {"tv_pm_pct": -1.2, "tv_sector": "Technology Services"},
        "BBB": {"tv_pm_pct": -0.5, "tv_sector": "Technology Services"},
        "CCC": {"tv_pm_pct": -5.5, "tv_sector": "Technology Services"},
        "DDD": {"tv_pm_pct": 9.0, "tv_sector": "Technology Services"},
        "EEE": {"tv_pm_pct": -2.2, "tv_sector": "Technology Services"},
        "FFF": {"tv_pm_pct": -4.0, "tv_sector": "Electronic Technology"},
        "GGG": {"tv_pm_pct": -4.0, "tv_sector": "Health Technology"},
    }
    PULL._classify_drivers(recs, proxies, crypto, {"CCC": {"confirmed": True,
                                                            "source": "issuer PR"}})
    expect = {
        "MARA": "CRYPTO_BETA",    # a crypto-linked equity tracking bitcoin
        "AAA": "MARKET_BETA",     # within 1.0pp of SPY
        "BBB": "NO_MOVE",         # under 1% - nothing to attribute
        "CCC": "CATALYST",        # a confirmed issuer event, no proxy within tolerance
        "DDD": "IDIOSYNCRATIC",   # a lone mover
        "EEE": "SECTOR_BETA",     # within 1.5pp of XLK
        "FFF": "SECTOR_BETA",     # within 1.5pp of SMH
        "GGG": "IDIOSYNCRATIC",   # its sector proxy (XLV) is not in the set
    }
    for sym, want in expect.items():
        got = recs[sym].get("driver_class")
        if got == want:
            ok(f"{sym} is classified {got}")
        else:
            bad(f"{sym} is classified {got}, expected {want}")
    for sym, rec in recs.items():
        if rec.get("driver_class") not in PULL.DRIVER_CLASSES:
            bad(f"{sym} has a driver_class outside the vocabulary")


def test_end_to_end():
    """The renderer must produce an artifact the checker ACCEPTS."""
    print("[end to end: render -> check]")
    tmp = Path(tempfile.mkdtemp(prefix="pmpipeline-"))
    recs = {}
    spec = [("AAA", 10.0, 10.6, 120000, 300, "FLAGGED"),
            ("BBB", 20.0, 19.4, 80000, 200, "BELOW"),
            ("CCC", 30.0, 31.0, 90000, 150, "BELOW")]   # +3.33% - below the bar
    for sym, close, px, vol, shares, verdict in spec:
        gap = round((px / close - 1) * 100, 3)
        recs[sym] = {
            "ticker": sym, "base_close": close, "base_close_source": "focus.csv+tradingview+cboe",
            "base_close_conflict": "", "pm_price": px, "pm_gap_pct": gap,
            "quote_price": px, "quote_gap_pct": gap, "exec_shares": shares,
            "exec_notional": shares * px, "pm_volume": vol,
            "pm_volume_source": "Nasdaq extended-trading cumulative counter",
            "info_bid": px - 0.1, "info_ask": px + 0.1,
            "pm_high": "$%.2f" % (px + 0.2), "pm_low": "$%.2f" % (px - 0.2),
            "pm_high_gap_pct": round(((px + 0.2) / close - 1) * 100, 3),
            "pm_low_gap_pct": round(((px - 0.2) / close - 1) * 100, 3),
            "tv_pm_pct": gap, "tv_pm_volume": vol, "tv_sector": "Technology Services",
            "tv_avg_volume_30d": 1000000, "tv_earnings_release_date": None,
            "stylists": "jeff_sun|stockbee", "origins": "A_stockbee_4pct|D_qullamaggie_ep",
            "tape_newest_print": "08:19:19", "tape_lag_min": 14.0, "tape_pulls": 2,
            "tape_vintage_count": 1, "tape_pulls_wave2": None,
            "prior_session_change": 3.25, "driver_class": "IDIOSYNCRATIC",
            "driver_basis": "no proxy within 1.5pp of %.2f" % gap,
            "verdict": verdict, "flag_reason": "test", "flagged": verdict == "FLAGGED",
        }
    pull = {
        "contract": "premarket-artifact-v6", "pull_marker": "premarket-pull-v2",
        "render_marker": "premarket-render-v1", "pulls_per_symbol": 4,
        "gap_trigger": 4.0, "volume_floor": 50000, "min_executed_shares": 25,
        "tape_waves": [{"wave": 1, "at_et": "08:36:00 ET", "symbols": 3}],
        "proxies": {"SPY": {"premarket_change": -0.7, "close": 757.12}},
        "crypto_proxy": None,
        "market_ladder": [{"ticker": "ZZZ", "gap_pct": -9.0, "pm_volume": 500000,
                           "market_cap": 5e9, "sector": "Technology Services",
                           "driver_class": "IDIOSYNCRATIC"}],
        "records": recs, "flagged": 1,
    }
    (tmp / "_premarket-pull.json").write_text(json.dumps(pull, indent=2))
    (tmp / "_universe.json").write_text(json.dumps({
        "status": "OK", "universe_date": "2026-11-11", "expected_prior_session": "2026-11-11",
        "universe_source": "focus.csv:today_close", "ref_close_column": "today_close",
    }, indent=2))
    (tmp / "premarket-context.json").write_text(json.dumps({
        "catalysts": {"ZZZ": {"confirmed": True, "source": "issuer PR", "note": "Q3 beat"}},
    }, indent=2))
    rc = RENDER.main(["--pull-json", str(tmp / "_premarket-pull.json"),
                      "--universe-manifest", str(tmp / "_universe.json"),
                      "--context", str(tmp / "premarket-context.json"),
                      "--out-dir", str(tmp), "--date", "2026-11-12", "--quiet"])
    if rc == 0:
        ok("the renderer produced the contract files")
    else:
        bad(f"the renderer exited {rc}")
        return
    md = tmp / "pre-market-gapper.md"
    csvp = tmp / "pre-market-gapper.csv"
    if md.exists() and csvp.exists():
        ok("both contract files exist")
    else:
        bad("a contract file is missing")
        return
    text = md.read_text()
    if "premarket-render-v1" in text and "premarket-pull-v2" in text:
        ok("the artifact carries both capability markers")
    else:
        bad("the artifact does not carry the capability markers")
    if "## Market ladder" in text:
        ok("the artifact has the Market ladder section")
    else:
        bad("the artifact has no Market ladder section")
    head = text.index("## Market ladder") if "## Market ladder" in text else -1
    foc = text.index("## Focus scan") if "## Focus scan" in text else -1
    if head >= 0 and foc >= 0 and head < foc:
        ok("the Market ladder comes BEFORE the Focus scan")
    else:
        bad("the Market ladder does not come before the Focus scan")
    proc = subprocess.run([sys.executable, str(HERE / "check_premarket_artifact.py"),
                           "--md", str(md), "--csv", str(csvp),
                           "--pull-json", str(tmp / "_premarket-pull.json")],
                          capture_output=True, text=True)
    if proc.returncode == 0:
        ok("the contract checker ACCEPTS the rendered artifact")
    else:
        bad("the contract checker REJECTED the rendered artifact:\n" + proc.stdout[-2000:])
    # a v5 artifact (an older one) must still be judged by the v5 clauses
    old = text.replace("premarket-artifact-v6", "premarket-artifact-v5")
    (tmp / "old.md").write_text(old)
    proc = subprocess.run([sys.executable, str(HERE / "check_premarket_artifact.py"),
                           "--md", str(tmp / "old.md"), "--csv", str(csvp),
                           "--pull-json", str(tmp / "_premarket-pull.json")],
                          capture_output=True, text=True)
    if "universe" in proc.stdout and "skipped" not in proc.stdout.split("[universe]")[1][:40]:
        ok("a v5 artifact still gets the v5 universe clauses")
    else:
        bad("the v5 universe clauses were skipped for a v5 artifact")


def main():
    global PULL, RENDER, CHECK
    pull_path = find_repo_file("cloud-prompts/skills/stock-screener-suite/scripts/premarket_pull.py")
    render_path = find_repo_file("cloud-prompts/skills/stock-screener-suite/scripts/render_premarket_artifact.py")
    check_path = find_repo_file("tools/check_premarket_artifact.py")
    print(f"engine files: pull={pull_path} render={render_path} check={check_path}")
    if not pull_path or not render_path or not check_path:
        print("test_premarket_pipeline: the engine files were not found")
        return 1
    PULL = load(pull_path, "pm_pull")
    RENDER = load(render_path, "pm_render")
    CHECK = load(check_path, "pm_check")
    test_adaptive_pulls()
    test_lag()
    test_driver_class()
    test_end_to_end()
    print()
    if FAILURES:
        print(f"FAILED — {len(FAILURES)} of {CHECKS} checks failed:")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print(f"OK — {CHECKS} checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
