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

    # --- SQL lint: the SQL this skill emits must be structurally sound -------
    # Five defects shipped in screen.py and were only caught by running the
    # queries against the live database. Two of them were silent (an empty
    # result set, and one metric published under another metric's header).
    # The lint runs offline, so it works even when shibui is unreachable.
    try:
        import sql_lint

        emitters = [
            ("prefilter", screen.emit_prefilter_sql),
            ("sweep_stockbee", screen.emit_sweep_sql_stockbee),
            ("sweep_qullamaggie", screen.emit_sweep_sql_qullamaggie),
            ("sweep_peoplewish", screen.emit_sweep_sql_peoplewish),
            ("breadth", screen.emit_breadth_sql),
            ("reversal_bullish", screen.emit_reversal_bullish_sql),
            ("resolve_date", screen.emit_resolve_date_sql),
            ("weekly", screen.emit_weekly_sql),
        ]
        # The per-branch emitters are the path the run actually takes — a cap
        # must not be able to hide there.
        emitters += [
            (f"branch:{b}", (lambda b: (lambda d: screen.emit_sweep_sql_branch(d, b)))(b))
            for b in screen.SWEEP_BRANCHES
        ]
        lint_errors = 0
        for label, fn in emitters:
            issues = [i for i in sql_lint.lint_sql(fn(args.date), args.date) if i.severity == "ERROR"]
            lint_errors += len(issues)
            failures += (0 if not issues else 1)
            detail = issues[0].message if issues else ""
            lines.append(
                f"  {PASS if not issues else FAIL}  sql-lint {label:20s} "
                f"({detail[:90] if issues else 'clean'})"
            )
    except Exception as e:
        failures += 1
        lines.append(f"  {FAIL}  sql-lint raised {type(e).__name__}: {e}")

    # --- SQL lint regression: the linter must still catch the known defects -
    # If the linter ever stops flagging these, it has stopped protecting the
    # skill — so this is asserted, not merely logged.
    try:
        sys.path.insert(0, str(_SCRIPT_DIR / "testdata"))
        import broken_sweep_sql
        import sql_lint

        detected: set[str] = set()
        for _name, sql in broken_sweep_sql.CASES.items():
            for issue in sql_lint.lint_sql(sql, broken_sweep_sql.DATE):
                if issue.severity == "ERROR":
                    detected.add(issue.code)
        expected = {"L001", "L002", "L003", "L004", "L005"}
        missing = sorted(expected - detected)
        failures += (0 if not missing else 1)
        lines.append(
            f"  {PASS if not missing else FAIL}  sql-lint regression: broken fixtures "
            f"still detected ({', '.join(sorted(detected))})"
            + (f" — MISSING {missing}" if missing else "")
        )
    except Exception as e:
        failures += 1
        lines.append(f"  {FAIL}  sql-lint regression raised {type(e).__name__}: {e}")

    # --- GUARD 1: no per-branch LIMIT in ANY emitted SQL --------------------
    # The truncation that shipped twice. On 2026-11-04 the artifact published
    # `A_stockbee_4pct 50` and `B_stockbee_ep9m 50` — those are the CAPS, not
    # screen outcomes (the true passing counts that day were 233 and 236).
    # A per-branch LIMIT truncates the book while the query still SUCCEEDS,
    # so no downstream count goes red. Only the SQL's shape gives it away.
    try:
        import sql_lint

        offenders = []
        for label, fn in list(sql_dispatch.items()) + [
            (f"branch:{b}", (lambda b: (lambda d: screen.emit_sweep_sql_branch(d, b)))(b))
            for b in screen.SWEEP_BRANCHES
        ]:
            sql = fn(args.date)
            issues = [i for i in sql_lint.lint_sql(sql, args.date) if i.code == "L009"]
            if issues:
                offenders.append(f"{label}: {issues[0].message}")
        ok = not offenders
        failures += (0 if ok else 1)
        lines.append(
            f"  {PASS if ok else FAIL}  GUARD no per-branch LIMIT in any emitted SQL (L009)"
            + ("" if ok else f" \u2014 {offenders[0][:100]}")
        )
    except Exception as e:
        failures += 1
        lines.append(f"  {FAIL}  GUARD per-branch LIMIT check raised {type(e).__name__}: {e}")

    # --- GUARD 2: every branch reports rows_passing --------------------------
    # `rows_passing` (COUNT(*) OVER () inside the branch) is what makes the
    # truncation VISIBLE: it is the true count of names that passed the
    # branch's filter, carried on the rows themselves.
    try:
        missing = [
            b for b in screen.SWEEP_BRANCHES
            if "rows_passing" not in screen.emit_sweep_sql_branch(args.date, b)
        ]
        ok = not missing
        failures += (0 if ok else 1)
        lines.append(
            f"  {PASS if ok else FAIL}  GUARD every sweep branch reports rows_passing"
            + ("" if ok else f" \u2014 missing in {', '.join(missing)}")
        )
    except Exception as e:
        failures += 1
        lines.append(f"  {FAIL}  GUARD rows_passing check raised {type(e).__name__}: {e}")

    # --- GUARD 3: late_cycle can actually be TRUE ---------------------------
    # The breadth SQL emits the index identifier as `ticker`
    # (`SELECT 'index_atr_extension', ticker, close, ...`). compute_regime()
    # read `row.get("symbol")` ONLY, so atr_extensions came back EMPTY and
    # late_cycle could never be anything but False. A flag that can only ever
    # be false is not a flag \u2014 it needs a test that proves it can be true.
    try:
        extended_rows = [
            {"metric": "largecap_breadth", "breadth_pct_largecap": 71.0},
            {"metric": "index_above_sma_summary", "pct_above_sma_20": 0.8},
            # QQQ 14.29% above its 50-DMA \u2014 the flag's own threshold is 6%
            {"metric": "index_atr_extension", "ticker": "QQQ", "close": 600.0,
             "sma_50": 525.0, "extension_pct": 14.285714285714288},
        ]
        regime_ext = screen.compute_regime(extended_rows, 16.61, 18.8)
        ok = (
            regime_ext.get("late_cycle") is True
            and "QQQ" in regime_ext.get("atr_extensions", {})
        )
        failures += (0 if ok else 1)
        lines.append(
            f"  {PASS if ok else FAIL}  GUARD compute_regime late_cycle=True for an index "
            f"6%+ above its 50-DMA (ticker key)"
            + ("" if ok else f" \u2014 got late_cycle={regime_ext.get('late_cycle')}, "
                            f"atr_extensions={regime_ext.get('atr_extensions')}")
        )
        # the legacy `symbol` key and the documented `etf` key must work too
        legacy_ok = True
        for key in ("symbol", "etf"):
            alt = [dict(r) for r in extended_rows]
            alt[-1] = {("ticker" if k == "ticker" else k): v for k, v in alt[-1].items()}
            alt[-1][key] = alt[-1].pop("ticker")
            if screen.compute_regime(alt, 16.61, 18.8).get("late_cycle") is not True:
                legacy_ok = False
        failures += (0 if legacy_ok else 1)
        lines.append(
            f"  {PASS if legacy_ok else FAIL}  GUARD compute_regime reads the "
            f"symbol/ticker/etf key chain"
        )
    except Exception as e:
        failures += 1
        lines.append(f"  {FAIL}  GUARD late_cycle check raised {type(e).__name__}: {e}")

    # --- GUARD 4: the _regime.json schema is pinned --------------------------
    # The payload changed shape between 2026-11-03 (flat) and 2026-11-04
    # (nested under a `regime` key). A consumer doing d.get("late_cycle") on
    # the nested file gets None \u2014 indistinguishable from "not computed".
    try:
        ok = True
        detail = ""
        flat = screen.compute_regime(extended_rows, 16.61, 18.8)
        screen.assert_regime_schema(flat)
        try:
            screen.assert_regime_schema({"regime": flat})
            ok = False
            detail = "the nested shape was accepted"
        except screen.RegimeSchemaError:
            pass
        try:
            bad = dict(flat)
            bad.pop("late_cycle")
            screen.assert_regime_schema(bad)
            ok = False
            detail = "a missing key was accepted"
        except screen.RegimeSchemaError:
            pass
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "_regime.json"
            screen.write_regime_payload(out, flat)
            written = json.loads(out.read_text())
            if written.get("_schema") != screen.REGIME_SCHEMA_VERSION:
                ok = False
                detail = "the payload carries no _schema version"
            if "regime" in written:
                ok = False
                detail = "the payload was written nested"
            if written.get("late_cycle") is not True:
                ok = False
                detail = "late_cycle did not survive the write"
            if screen.read_regime(out).get("late_cycle") is not True:
                ok = False
                detail = "the round trip lost late_cycle"
            legacy = Path(td) / "legacy.json"
            legacy.write_text(json.dumps({"regime": flat, "_note": "x"}))
            if screen.read_regime(legacy).get("late_cycle") is not True:
                ok = False
                detail = "a legacy nested file did not read flat"
        failures += (0 if ok else 1)
        lines.append(
            f"  {PASS if ok else FAIL}  GUARD _regime.json has one declared shape, "
            f"a schema version, and a tolerant reader"
            + ("" if ok else f" \u2014 {detail}")
        )
    except Exception as e:
        failures += 1
        lines.append(f"  {FAIL}  GUARD regime schema check raised {type(e).__name__}: {e}")

    # --- GUARD 5: the coverage assertion fires on a short branch -------------
    try:
        complete = [
            {"origin": "A_stockbee_4pct", "symbol": "X", "rows_passing": 2},
            {"origin": "A_stockbee_4pct", "symbol": "Y", "rows_passing": 2},
        ]
        cov_ok = screen.branch_coverage(complete)
        passes_when_complete = not screen.coverage_failures(cov_ok)

        short = [{"origin": "A_stockbee_4pct", "symbol": "X", "rows_passing": 233}]
        cov_bad = screen.branch_coverage(short)
        fails = screen.coverage_failures(cov_bad)
        fires_when_short = (
            len(fails) == 1
            and fails[0].get("rows_passing") == 233
            and fails[0].get("rows_kept") == 1
        )
        ok = passes_when_complete and fires_when_short
        failures += (0 if ok else 1)
        lines.append(
            f"  {PASS if ok else FAIL}  GUARD coverage assertion: silent when complete, "
            f"fails loudly when a branch is short"
        )
    except Exception as e:
        failures += 1
        lines.append(f"  {FAIL}  GUARD coverage assertion raised {type(e).__name__}: {e}")

    # --- GUARD 6: the cap signature is recognisable --------------------------
    # A branch that returns EXACTLY 30 / 50 / 60 / 200 rows is a cap, not a
    # screen outcome. That is the fingerprint the artifact check looks for.
    try:
        capped = screen.branch_coverage([
            {"origin": "A_stockbee_4pct", "symbol": f"S{i}", "rows_passing": 50}
            for i in range(50)
        ])
        sig = screen.coverage_cap_signature(capped)
        ok = "A_stockbee_4pct" in sig
        failures += (0 if ok else 1)
        lines.append(
            f"  {PASS if ok else FAIL}  GUARD a kept-count that lands exactly on a cap is "
            f"flagged as the truncation signature"
        )
    except Exception as e:
        failures += 1
        lines.append(f"  {FAIL}  GUARD cap signature check raised {type(e).__name__}: {e}")

    # --- GUARD 7: the FRESH book merges, and every row says which session ----
    # The 2026-11-09 artifact published a book whose every metric was the
    # PREVIOUS session while it was read as "today's screen". A candidate must
    # carry `data_as_of` and `source`, and a name that is ONLY in the fresh
    # book must still reach the book.
    try:
        fresh_rows = [
            {"origin": "A_tv_breakout_4pct", "symbol": "FRESH1", "close": 10.0, "change_pct": 9.0},
            {"origin": "B_tv_ep9m", "symbol": "FRESH1", "close": 10.0, "volume": 9_000_000},
            {"origin": "A_tv_breakout_4pct", "symbol": "BOTH1", "close": 10.0, "change_pct": 9.0},
        ]
        ext = {
            "FRESH1": {"extended": True, "extension_reasons": ["RSI > 75 (80.0)"],
                       "extension_hits": ["rsi"], "extension_count": 1},
            "BOTH1": {"extended": False, "extension_reasons": [], "extension_hits": [], "extension_count": 0},
        }
        qual = {
            "BOTH1": {"quality_flags": ["trailing_pe", "free_cash_flow_yield"],
                      "quality_reasons": ["trailing P/E > 50 (120.59)", "negative free cash flow"],
                      "quality_clean": False},
        }
        cands = screen.tier_candidates(
            [{"origin": "A_stockbee_4pct", "symbol": "BOTH1", "rows_passing": 1}],
            set(), [], [], fresh_results=fresh_rows, extension_map=ext, quality_map=qual,
            fresh_data_as_of="2026-11-09", t1_data_as_of="2026-11-06",
        )
        ok_fresh = "FRESH1" in cands
        ok_both = "BOTH1" in cands
        ok_dates = (
            cands["FRESH1"].data_as_of == "2026-11-09"
            and cands["FRESH1"].source == "fresh"
            and cands["BOTH1"].data_as_of == "2026-11-09"
            and cands["BOTH1"].source == "fresh+t1"
            and cands["BOTH1"].origins == ["A_stockbee_4pct"]
        )
        ok_stylists = cands["BOTH1"].n_stylists == 1  # one stylist, two screens
        ok_quality = cands["BOTH1"].quality.get("quality_flags") == ["trailing_pe", "free_cash_flow_yield"]
        failures += (0 if (ok_fresh and ok_both and ok_dates and ok_stylists and ok_quality) else 1)
        lines.append(
            f"  {PASS if (ok_fresh and ok_both and ok_dates and ok_stylists and ok_quality) else FAIL}  "
            f"GUARD the fresh book merges and every row publishes data_as_of + source"
        )
    except Exception as e:
        failures += 1
        lines.append(f"  {FAIL}  GUARD fresh-book merge raised {type(e).__name__}: {e}")

    # --- GUARD 8: the extension label SPLITS the book, it never drops it -----
    try:
        cands = screen.tier_candidates(
            [{"origin": "A_stockbee_4pct", "symbol": f"S{i}", "rows_passing": 3} for i in range(3)],
            set(), [], [], extension_map={"S0": {"extended": True}, "S1": {"extended": False}},
        )
        ok = len(cands) == 3
        failures += (0 if ok else 1)
        lines.append(
            f"  {PASS if ok else FAIL}  GUARD an extension label never removes a name from the book"
        )
    except Exception as e:
        failures += 1
        lines.append(f"  {FAIL}  GUARD extension-label check raised {type(e).__name__}: {e}")

    # --- GUARD 9: the header line cron #07 reads is actually written ---------
    # Cron #07 reads `Screen data_date: <date> (shibui T+1)` out of focus.md
    # and reports lag_sessions from it. The writer never emitted that line, so
    # #07 had to infer the date from the folder name.
    try:
        with tempfile.TemporaryDirectory() as _tmp:
            _out = Path(_tmp) / "focus.md"
            screen.write_per_stylist_markdown(
                _out, "Focus", {}, screen_data_as_of="2026-11-06",
                fresh_data_as_of="2026-11-09", fresh_universe="3828 names",
            )
            _text = _out.read_text()
        ok = (
            "Screen data_date: 2026-11-06 (shibui T+1)" in _text
            and "Screen fresh_data_date: 2026-11-09 (cron-day settled bar)" in _text
        )
        failures += (0 if ok else 1)
        lines.append(
            f"  {PASS if ok else FAIL}  GUARD the focus.md header publishes both data dates"
        )
    except Exception as e:
        failures += 1
        lines.append(f"  {FAIL}  GUARD focus.md header check raised {type(e).__name__}: {e}")

    # --- GUARD: the ADR enrichment filters the RIGHT column ------------------
    # `shibui.stock_quotes.symbol` is VENUE-SUFFIXED (`AAPL.NASDAQ`); the bare
    # ticker is `q.ticker`. Filtering `q.symbol IN ('AAPL', ...)` matches nothing
    # and returns ZERO ROWS SILENTLY — which is exactly what the old emitter did,
    # so the ADR% column was empty on every candidate of every run (found
    # 2026-11-10). This guard fails if the filter ever goes back to `q.symbol`.
    try:
        _adr = screen.emit_adr_enrichment_sql(["AAPL", "MSFT", "NVDA"])
        _ok = (
            "q.ticker IN (" in _adr
            and "q.symbol IN (" not in _adr
            and "ticker AS symbol" in _adr
        )
        failures += (0 if _ok else 1)
        lines.append(
            f"  {PASS if _ok else FAIL}  GUARD the ADR enrichment filters q.ticker, not the "
            f"venue-suffixed q.symbol"
        )
    except Exception as e:
        failures += 1
        lines.append(f"  {FAIL}  GUARD ADR enrichment column check raised {type(e).__name__}: {e}")

    # --- GUARD: the ADR enrichment is REACHABLE from the CLI ------------------
    # `emit-sql adr_enrichment` existed as a function but was never exposed on the
    # CLI (the kind's `choices` list omitted it and `--symbols` was never
    # registered), so it could not be run at all.
    try:
        _proc = subprocess.run(
            [sys.executable, str(_SCRIPT_DIR / "screen.py"), "emit-sql",
             "adr_enrichment", "--symbols", "AAPL,MSFT"],
            capture_output=True, text=True,
        )
        _ok = _proc.returncode == 0 and "q.ticker IN ('AAPL', 'MSFT')" in _proc.stdout
        failures += (0 if _ok else 1)
        lines.append(
            f"  {PASS if _ok else FAIL}  GUARD emit-sql adr_enrichment is reachable on the CLI"
        )
    except Exception as e:
        failures += 1
        lines.append(f"  {FAIL}  GUARD ADR enrichment CLI check raised {type(e).__name__}: {e}")

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
