#!/usr/bin/env python3
"""Smoke-test for stock-screener-suite.

Walks every emit-sql kind, every Finviz URL builder, and the consume path
on a dry-run JSON stub. Prints a one-line PASS/FAIL summary per check.
Exit code = number of failures (0 = all passed).

Use before merging changes to screen.py — under 5 seconds to run, no MCP
calls.

Examples:
    python scripts/smoke_test.py
    python scripts/smoke_test.py --date 2026-09-18
    python scripts/smoke_test.py --quiet
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from datetime import date as _date
from pathlib import Path

# Allow running as a script from anywhere — resolve siblings of this file.
_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))

import screen  # noqa: E402  (intentional — adjust sys.path before import)


PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"
WARN = "\033[33mWARN\033[0m"


def check(ok: bool, label: str, detail: str = "") -> tuple[int, list[str]]:
    status = PASS if ok else FAIL
    line = f"  {status}  {label}"
    if detail:
        line += f"   {detail}"
    return (0 if ok else 1), [line]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Smoke-test stock-screener-suite")
    p.add_argument("--date", default="2026-09-18", help="date to use for emit-sql checks (default: a known settled bar)")
    p.add_argument("--quiet", action="store_true", help="only print FAIL lines")
    args = p.parse_args(argv)

    failures = 0
    lines: list[str] = []

    # --- Plan emitter ---
    n_fail, n_lines = check(hasattr(screen, "cmd_plan"), "screen.cmd_plan exists", "the daily-sweep plan emitter")
    failures += n_fail; lines += n_lines

    # --- emit-sql kinds (mapped to the actual emit_*_sql functions in screen.py) ---
    sql_dispatch = {
        "prefilter":       screen.emit_prefilter_sql,
        "sweep":           screen.emit_sweep_sql,
        "sweep_stockbee":  screen.emit_sweep_sql_stockbee,
        "sweep_qullamaggie": screen.emit_sweep_sql_qullamaggie,
        "sweep_peoplewish": screen.emit_sweep_sql_peoplewish,
        "breadth":         screen.emit_breadth_sql,
        "reversal_bullish": screen.emit_reversal_bullish_sql,
        "weekly":          screen.emit_weekly_sql,
        "resolve_date":    screen.emit_resolve_date_sql,
    }
    for kind, fn in sql_dispatch.items():
        try:
            sql = fn(args.date)
            ok = isinstance(sql, str) and len(sql) > 50
            failures += (0 if ok else 1)
            lines.append(f"  {PASS if ok else FAIL}  emit-sql {kind:18s} ({len(sql)} chars)")
        except Exception as e:
            failures += 1
            lines.append(f"  {FAIL}  emit-sql {kind} raised {type(e).__name__}: {e}")

    # --- Reversal-bullish top-level subcommand (alias) ---
    # Verify the argparse layer registers 'reversal-bullish' as a subcommand.
    try:
        result = subprocess.run(
            [sys.executable, str(_SCRIPT_DIR / "screen.py"), "reversal-bullish", args.date],
            capture_output=True, text=True, timeout=10,
        )
        ok = result.returncode == 0 and "Reversal bullish" in result.stdout
        failures += (0 if ok else 1)
        lines.append(f"  {PASS if ok else FAIL}  `screen.py reversal-bullish <date>` top-level subcommand works")
    except Exception as e:
        failures += 1
        lines.append(f"  {FAIL}  reversal-bullish subcommand raised {type(e).__name__}: {e}")

    # --- Finviz URL builders ---
    for kind, fn in screen.FINVIZ_BUILDERS.items():
        try:
            url = fn()
            ok = isinstance(url, str) and url.startswith("https://finviz.com/")
            failures += (0 if ok else 1)
            lines.append(f"  {PASS if ok else FAIL}  finviz-url {kind:18s} -> {url[:60]}...")
        except Exception as e:
            failures += 1
            lines.append(f"  {FAIL}  finviz-url {kind} raised {type(e).__name__}: {e}")

    # --- consume dry-run on a synthetic JSON ---
    stub = {
        "date": args.date,
        "data_as_of": args.date,
        "run_at_utc": _date.today().isoformat(),
        "prefilter": [],
        "sweep_stockbee": [
            {"origin": "A_stockbee_4pct", "symbol": "AAA.NASDAQ", "close": 10, "volume": 1_000_000, "chg_pct": 5.0},
            {"origin": "B_stockbee_ep9m", "symbol": "AAA.NASDAQ", "close": 10, "velocity_14d": 30.0},
            {"origin": "A_stockbee_4pct", "symbol": "BBB.NASDAQ", "close": 12, "volume": 800_000, "chg_pct": 4.5},
        ],
        "sweep_qullamaggie": [
            {"origin": "D_qullamaggie_ep", "symbol": "AAA.NASDAQ", "close": 10, "gap_pct": 21.0},
            {"origin": "G_peoplewish", "symbol": "AAA.NASDAQ", "close": 10, "adr_pct_20d": 6.0, "velocity_14d": 50.0},
            {"origin": "E_qullamaggie_5d_gainers", "symbol": "CCC.NASDAQ", "close": 5, "gain_5d": 35.0},
        ],
        "sweep_peoplewish": [
            {"origin": "G_peoplewish", "symbol": "AAA.NASDAQ", "close": 10, "adr_pct_20d": 6.0, "velocity_14d": 60.0},
            {"origin": "G_peoplewish", "symbol": "DDD.NASDAQ", "close": 7, "adr_pct_20d": 8.0, "velocity_14d": 45.0},
        ],
        "jeff_sun_canslim": [],
        "ariel_sector_rs": [],
        "volume_breakout": [],
        "breadth": {
            "largecap_breadth_pct_above_sma_20": 25.05,
            "index_pct_above_sma_20": 20.0,
            "index_pct_above_sma_50": 40.0,
            "indices_atr_extension_pct": {"SPY": 0.26, "QQQ": 1.62, "IWM": -3.74, "QQQE": -1.66, "RSP": -2.28},
        },
        "vix_price": 14.81,
        "vix3m_price": 18.24,
    }
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as fh:
        json.dump(stub, fh)
        tmp = Path(fh.name)
    try:
        # Run consume via subprocess so the --dry-run path handles file
        # IO (the in-process call would need a Namespace and is harder to
        # verify clean-up of side-effects).
        result = subprocess.run(
            [sys.executable, str(_SCRIPT_DIR / "screen.py"), "consume",
             "--in", str(tmp), "--date", args.date, "--dry-run"],
            capture_output=True, text=True, timeout=30,
        )
        ok = result.returncode == 0 and "DRY-RUN tier-a count" in result.stdout
        detail = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else result.stderr.strip()
        failures += (0 if ok else 1)
        lines.append(f"  {PASS if ok else FAIL}  consume --dry-run end-to-end ({detail[:80]})")
    finally:
        tmp.unlink(missing_ok=True)

    # --- write_csv _source column ---
    from screen import write_csv
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "test.csv"
        write_csv(p, [{"symbol": "X", "origin": "test", "_source": "mcp"}])
        content = p.read_text()
        ok = "_source" in content and "mcp" in content
        failures += (0 if ok else 1)
        lines.append(f"  {PASS if ok else FAIL}  write_csv preserves _source column header")

    # --- compute_regime on the Agent's pre-aggregated shape ---
    regime = screen.compute_regime(
        stub["breadth"],
        stub["vix_price"],
        stub["vix3m_price"],
    )
    ok = (
        regime.get("breadth_pct_spx") == 25.05
        and regime.get("index_below_20sma") is True
        and "SPY" in regime.get("atr_extensions", {})
        and regime.get("size_cut_pct") == 50  # index<20 AND breadth<40
    )
    failures += (0 if ok else 1)
    lines.append(
        f"  {PASS if ok else FAIL}  compute_regime handles Agent pre-aggregated breadth "
        f"(breadth={regime.get('breadth_pct_spx')}, size_cut={regime.get('size_cut_pct')})"
    )

    # Final summary
    if not args.quiet or failures:
        print("\n".join(lines))
    if failures:
        print(f"\n{FAIL}  {failures} check(s) failed")
        return 1
    print(f"\n{PASS}  All smoke tests passed")
    return 0


def _argparse_namespace(**kwargs):
    """Tiny helper for the type stub; argparse.Namespace is a plain object."""
    import argparse
    return argparse.Namespace(**kwargs)


if __name__ == "__main__":
    sys.exit(main())
