#!/usr/bin/env python3
"""Contract test for tools/sweep_pipeline.py.

A checker that never observed failing is a claim, not a guard. This test runs
the pipeline's own `check` stage against deliberately BROKEN artifacts and
asserts that it catches each defect, and it runs `selftest` (the offline
checks of every derived quantity).

The defects it proves are caught are the ones this suite has actually shipped:

  * a stub marker left in the artifact (the narrative never filled in)
  * a truncated book (rows_kept != rows_passing)
  * a branch that landed exactly on a cap (the truncation fingerprint)
  * a candidate with no data_as_of / source (the session ambiguity)
  * an empty per-stylist file (the silent zero)
  * a missing `.csv` companion (the `.md`-only publish)
  * a focus.csv with no dated close column (the resolver's denominator)
  * a focus.csv row with no today_close or no provenance
  * a parabolic CSV with no m1 (the defining metric missing)
  * a nested _regime.json (the flat schema v2 contract break)

Usage:
    python3 tools/test_sweep_pipeline.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
PIPELINE = HERE / "sweep_pipeline.py"
sys.path.insert(0, str(HERE))

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"


def check(ok: bool, label: str, detail: str = "") -> tuple[int, list[str]]:
    line = f"  {PASS if ok else FAIL}  {label}"
    if detail:
        line += f"   {detail}"
    return (0 if ok else 1), [line]


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _minimal_artifact(root: Path, date: str, t1_date: str) -> Path:
    """A minimal but VALID artifact, which each test then breaks in one way."""
    out = root / date
    out.mkdir(parents=True, exist_ok=True)

    _write(out / "_regime.json", json.dumps({
        "_schema": 2, "size_cut_pct": 0, "uncertainty": False, "late_cycle": False,
        "breadth_pct_spx": 62.03, "index_below_20sma": True,
        "vix": 19.46, "vix3m": 20.64,
        "atr_extensions": {"SPY": {"extension_pct": -1.97}},
    }, indent=1))

    cands = [
        {"symbol": "AAA", "origins": ["A_stockbee_4pct", "B_stockbee_ep9m",
                                      "jeff_sun_canslim"], "fresh_origins": [],
         "data_as_of": t1_date, "source": "t1", "n_stylists": 3,
         "convergence_score": 3, "flags": {}, "data": {},
         "extension": {"extended": False}, "quality": {"valuation_gate": "pass"}},
        {"symbol": "BBB", "origins": ["A_stockbee_4pct", "B_stockbee_ep9m"],
         "fresh_origins": [], "data_as_of": t1_date, "source": "t1", "n_stylists": 1,
         "convergence_score": 2, "flags": {}, "data": {},
         "extension": {"extended": False}, "quality": {"valuation_gate": "pass"}},
    ]
    _write(out / "_results.json", json.dumps({
        "date": date, "data_as_of": t1_date,
        "regime": {"_schema": 2, "size_cut_pct": 0, "uncertainty": False,
                   "late_cycle": False, "breadth_pct_spx": 62.03,
                   "index_below_20sma": True, "vix": 19.46, "vix3m": 20.64,
                   "atr_extensions": {"SPY": {"extension_pct": -1.97}}},
        "counts": {"candidates": 2, "focus": 1, "tier_a": 1,
                   "short_candidates": 1, "long_reversal_candidates": 1},
        "tier_a_pool": 1, "tier_a_truncated": False,
        "screen_coverage": {
            "A_stockbee_4pct": {"rows_passing": 2, "rows_kept": 2, "consistent": True},
            "B_stockbee_ep9m": {"rows_passing": 1, "rows_kept": 1, "consistent": True},
        },
        "tier_a": ["AAA"], "focus": ["AAA"],
        "short_candidates": ["AAA"], "long_reversal_candidates": ["AAA"],
        "fresh_data_as_of": date, "t1_data_as_of": t1_date,
        "fresh_branches": {"A_tv_breakout_4pct": {"rows_passing": 1, "rows_kept": 1,
                                                   "data_as_of": date,
                                                   "source": "tradingview_scanner"}},
        "tier_a_fresh": ["AAA"], "tier_a_extended": [],
        "candidates": cands,
    }, indent=1))

    _write(out / "_cache.json", json.dumps({"cron_date": date, "data_as_of": t1_date}, indent=1))
    _write(out / "_summary.md", "# Daily sweep summary\n")

    for name, rows in (("stockbee.md", 2), ("qullamaggie.md", 1), ("jeff-sun.md", 1),
                       ("ariel-hernandez.md", 1), ("peoplewish.md", 1), ("master.md", 2),
                       ("focus.md", 1), ("tier-a.md", 1), ("tier-a-fresh.md", 1),
                       ("tier-a-extended.md", 0)):
        body = "# X\n\n| Symbol | Stylists |\n|---|---|\n" + "\n".join(
            f"| S{i} | 1 |" for i in range(rows)) + "\n"
        if name == "focus.md":
            body = (f"# Focus\n\nScreen data_date: {t1_date} (shibui T+1)\n"
                    f"Screen fresh_data_date: {date} (cron-day settled bar)\n\n"
                    + body)
        _write(out / name, body)

    csv_cols = ("symbol,stylists,n_stylists,origins,source,data_as_of,data_date,"
                "screen_close_resolved,chg_pct_resolved,today_close,today_change,"
                f"today_volume,close_{date},chg_pct_{date},close_{t1_date},"
                f"chg_pct_{t1_date},rvol_10d\n")
    # AAA,jeff_sun|qullamaggie|stockbee,3,<origins>,t1,<data_as_of>,<data_date>,
    # <screen_close>,<screen_chg>,<today_close>,<today_chg>,<today_vol>,
    # <close_date>,<chg_date>,<close_t1>,<chg_t1>,<rvol>
    csv_row = (f"AAA,jeff_sun|qullamaggie|stockbee,3,A_stockbee_4pct|"
               f"B_stockbee_ep9m|jeff_sun_canslim,t1,{t1_date},{t1_date},"
               "10.00,1.00,11.00,1.00,1000000,"
               f"11.00,1.00,10.00,1.00,1.50\n")
    _write(out / "focus.csv", csv_cols + csv_row)
    _write(out / "tier-a.csv", csv_cols + csv_row)
    _write(out / "master.csv", csv_cols + csv_row)
    par_cols = ("symbol,origin,_source,screen_data_date,m1_5d_move_pct,m2_10d_move_pct,"
                "adr_pct_20d,adv_dollar_20d\n")
    _write(out / "short-candidates.csv",
           par_cols + f"AAA,qullamaggie_5d_gainers,mcp,{t1_date},25.0,,5.0,1000000\n")
    _write(out / "long-reversal-candidates.csv",
           par_cols + f"AAA,qullamaggie_5d_losers,mcp,{t1_date},-25.0,,5.0,1000000\n")
    _write(out / "same-day-prints.md",
           "# Same-day prints\n\n| Symbol | Close | Chg | Volume |\n|---|---|---|---|\n| AAA | 11.00 | +1.00% | 1000000 |\n")
    _write(out / "_same-day-prints.json", json.dumps({"data_date": date, "quotes": {}}, indent=1))

    _write(out / "daily-sweep.md",
           "---\nartifact: daily-sweep\ncontract: SWEEP_PIPELINE_V1\n---\n\n"
           "# Daily Screener Sweep\n\n## TL;DR\n\n- ok\n\n## Tier-A\n\n| AAA |\n")
    _write(out / "breadth.md",
           "---\nartifact: breadth\ncontract: SWEEP_PIPELINE_V1\n---\n\n"
           "# Breadth & Regime\n\n## TL;DR\n\n- ok\n")
    return out


def main() -> int:
    failures: list[str] = []
    lines: list[str] = []

    # --- the pipeline's own selftest -----------------------------------------
    proc = subprocess.run([sys.executable, str(PIPELINE), "selftest"],
                          capture_output=True, text=True)
    n, ls = check(proc.returncode == 0, "the pipeline's selftest passes",
                  proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else "")
    failures += ls
    lines += ls

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        date, t1_date = "2026-11-10", "2026-11-09"

        # --- the happy path: a valid artifact passes -------------------------
        out = _minimal_artifact(root, date, t1_date)
        proc = subprocess.run(
            [sys.executable, str(PIPELINE), "check", "--date", date,
             "--t1-date", t1_date, "--out", str(root)],
            capture_output=True, text=True)
        n, ls = check(proc.returncode == 0, "a valid artifact passes the checker",
                      "" if proc.returncode == 0 else proc.stdout.strip())
        failures += ls
        lines += ls

        # --- each defect must be CAUGHT ---------------------------------------
        def broken(label: str, mutate) -> None:
            out2 = _minimal_artifact(root / label.replace(" ", "_"), date, t1_date)
            mutate(out2)
            p = subprocess.run(
                [sys.executable, str(PIPELINE), "check", "--date", date,
                 "--t1-date", t1_date, "--out", str(out2.parent)],
                capture_output=True, text=True)
            caught = p.returncode != 0
            n, ls = check(caught, f"the checker CATCHES: {label}",
                          "" if caught else "the artifact passed a broken check")
            failures.extend(ls)
            lines.extend(ls)

        def stub(md: Path):
            p = md / "daily-sweep.md"
            _write(p, p.read_text() + "\n<!-- FILL: tldr -->\n")

        broken("a stub marker left in daily-sweep.md", stub)

        def truncated(out2: Path):
            p = out2 / "_results.json"
            d = json.loads(p.read_text())
            d["screen_coverage"]["A_stockbee_4pct"]["rows_kept"] = 1
            _write(p, json.dumps(d, indent=1))

        broken("a truncated book (rows_kept != rows_passing)", truncated)

        def cap(out2: Path):
            p = out2 / "_results.json"
            d = json.loads(p.read_text())
            d["screen_coverage"]["A_stockbee_4pct"]["rows_passing"] = 50
            d["screen_coverage"]["A_stockbee_4pct"]["rows_kept"] = 50
            _write(p, json.dumps(d, indent=1))

        broken("a branch that landed exactly on a cap", cap)

        def no_session(out2: Path):
            p = out2 / "_results.json"
            d = json.loads(p.read_text())
            d["candidates"][0]["data_as_of"] = ""
            _write(p, json.dumps(d, indent=1))

        broken("a candidate with no data_as_of", no_session)

        def empty_stylist(out2: Path):
            _write(out2 / "stockbee.md", "# Stockbee\n\n| Symbol | Stylists |\n|---|---|\n")

        broken("an empty per-stylist file", empty_stylist)

        def no_csv(out2: Path):
            (out2 / "focus.csv").unlink()

        broken("a missing .csv companion", no_csv)

        def no_dated_close(out2: Path):
            # remove BOTH dated close columns, so the resolver has no
            # date-resolvable close at all
            p = out2 / "focus.csv"
            lines_ = p.read_text().splitlines()
            lines_[0] = (lines_[0]
                         .replace(f"close_{date}", "close_x")
                         .replace(f"close_{t1_date}", "close_y"))
            _write(p, "\n".join(lines_) + "\n")

        broken("a focus.csv with no dated close column", no_dated_close)

        def no_today_close(out2: Path):
            p = out2 / "focus.csv"
            lines_ = p.read_text().splitlines()
            parts = lines_[1].split(",")
            parts[9] = ""
            lines_[1] = ",".join(parts)
            _write(p, "\n".join(lines_) + "\n")

        broken("a focus.csv row with no today_close", no_today_close)

        def no_m1(out2: Path):
            p = out2 / "short-candidates.csv"
            lines_ = p.read_text().splitlines()
            parts = lines_[1].split(",")
            parts[4] = ""
            lines_[1] = ",".join(parts)
            _write(p, "\n".join(lines_) + "\n")

        broken("a parabolic CSV with no m1", no_m1)

        def nested_regime(out2: Path):
            p = out2 / "_regime.json"
            d = json.loads(p.read_text())
            _write(p, json.dumps({"regime": d}, indent=1))

        broken("a nested _regime.json", nested_regime)

        def empty_extensions(out2: Path):
            p = out2 / "_regime.json"
            d = json.loads(p.read_text())
            d["atr_extensions"] = {}
            _write(p, json.dumps(d, indent=1))

        broken("an empty atr_extensions map", empty_extensions)

    print("\n".join(lines))
    failed = [l for l in lines if FAIL in l]
    if failed:
        print(f"\n{FAIL}  {len(failed)} check(s) failed")
        return 1
    print(f"\n{PASS}  All {len(lines)} pipeline contract checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
