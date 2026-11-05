#!/usr/bin/env python3
"""
test_cross_asset_contract.py — prove the cron #12 artifact contract is satisfiable AND
that the checker actually catches a breach.

Why
---
A checker that only ever fails is a checker nobody trusts, and a contract nobody can
satisfy is a contract that gets skipped. This test does both:

  1. builds a synthetic cross-asset session (the shape of a real 10:00 ET fire: a
     six-month window ending on the last COMPLETED session, an in-progress session
     that the partial matrix includes, and a matched-length prior-week matrix),
  2. renders an artifact from it with the real renderer,
  3. runs `check_cross_asset_artifact.py` and requires exit 0,
  4. then MUTATES that artifact eight different ways and requires the checker to fail
     each time,
  5. and proves the renderer REFUSES to write an artifact when one of its required
     inputs is missing — the silent-drop defect it was changed to prevent.

Nothing here touches the network: the data is synthetic and deterministic.

USAGE
    python3 tools/test_cross_asset_contract.py
Exit codes: 0 = all good; 1 = a breach was not caught (or a contract cannot be met).
"""

import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RENDER_PATH = (ROOT / "cloud-prompts" / "skills" / "cross-asset-correlation-snapshot"
               / "scripts" / "correlation_report.py")
CHECK_PATH = ROOT / "tools" / "check_cross_asset_artifact.py"

SYMS = ["SPY", "QQQ", "IWM", "TLT", "GLD", "UUP", "EEM", "^VIX"]

# A fixed, symmetric correlation matrix. SPY-TLT is deliberately POSITIVE (0.31) so the
# hedge implication exercises the "weak diversifier, not a hedge" branch.
OFFDIAG = {
    ("SPY", "QQQ"): 0.92, ("SPY", "IWM"): 0.76, ("SPY", "TLT"): 0.31,
    ("SPY", "GLD"): -0.16, ("SPY", "UUP"): -0.34, ("SPY", "EEM"): 0.77,
    ("SPY", "^VIX"): -0.79,
    ("QQQ", "IWM"): 0.71, ("QQQ", "TLT"): 0.16, ("QQQ", "GLD"): -0.10,
    ("QQQ", "UUP"): -0.29, ("QQQ", "EEM"): 0.88, ("QQQ", "^VIX"): -0.75,
    ("IWM", "TLT"): 0.48, ("IWM", "GLD"): -0.05, ("IWM", "UUP"): -0.29,
    ("IWM", "EEM"): 0.62, ("IWM", "^VIX"): -0.68,
    ("TLT", "GLD"): 0.05, ("TLT", "UUP"): 0.12, ("TLT", "EEM"): 0.09,
    ("TLT", "^VIX"): -0.19,
    ("GLD", "UUP"): -0.54, ("GLD", "EEM"): 0.05, ("GLD", "^VIX"): 0.12,
    ("UUP", "EEM"): -0.33, ("UUP", "^VIX"): 0.21,
    ("EEM", "^VIX"): -0.64,
}

WINDOW_START = "2026-05-04"
WINDOW_END = "2026-11-04"        # the last COMPLETED session
TODAY = "2026-11-05"             # the in-progress session
ART_DATE = "2026-11-05"

FAILURES = []


def fail(msg):
    FAILURES.append(msg)
    print(f"  FAIL {msg}")


def weekdays(start_iso, count):
    """count weekday dates ending at start_iso (inclusive), newest last."""
    d = date.fromisoformat(start_iso)
    out = []
    while len(out) < count:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d -= timedelta(days=1)
    return list(reversed(out))


def build_series():
    """{symbol: [[date, adjclose, rawclose], ...]} — 150 sessions ending TODAY."""
    days = weekdays(TODAY, 150)
    series = {}
    for i, sym in enumerate(SYMS):
        rows = []
        px = 100.0 + i * 37.0
        for j, d in enumerate(days):
            # deterministic pseudo-random walk
            px *= (1.0 + (((j * 37 + i * 17) % 23) - 11) / 1000.0)
            raw = round(px, 4)
            rows.append([d, raw, round(px * 0.999, 4)])
        series[sym] = rows
    return series, days


def matrix(scale=1.0):
    m = {a: {} for a in SYMS}
    for a in SYMS:
        for b in SYMS:
            if a == b:
                m[a][b] = 1.0
            else:
                key = (a, b) if (a, b) in OFFDIAG else (b, a)
                m[a][b] = round(OFFDIAG[key] * scale, 4)
    return m


def build_docs(tmp):
    series, days = build_series()
    series_path = tmp / "series.json"
    series_path.write_text(json.dumps(series), encoding="utf-8")

    in_window = [d for d in days if WINDOW_START <= d <= WINDOW_END]
    mats = {
        "window": {"start": WINDOW_START, "end": WINDOW_END,
                   "n_sessions": len(in_window), "n_return_obs": len(in_window) - 1,
                   "basis": "adjclose", "requested_end": "auto",
                   "end_derived_from_data": True},
        "tickers": SYMS,
        "matrix_returns": matrix(1.0),
        "matrix_returns_prior": matrix(0.97),
        "window_prior": {"start": "2026-04-27", "end": "2026-10-28",
                         "n_sessions": len(in_window), "n_return_obs": len(in_window) - 1,
                         "basis": "adjclose"},
        "sources": [{"symbol": s, "http": "200", "bars": len(days), "last_bar": TODAY}
                    for s in SYMS],
        "server_side": True,
        "engine": "shibui.stock_data_query (DuckDB corr(), one call)",
    }
    mats_path = tmp / "mats.json"
    mats_path.write_text(json.dumps(mats), encoding="utf-8")

    partial = {
        "matrix_returns": matrix(1.01),
        "window": {"start": WINDOW_START, "end": TODAY,
                   "n_sessions": len(in_window) + 1,
                   "n_return_obs": len(in_window), "basis": "adjclose"},
        "published_window_end": WINDOW_END,
        "includes_in_progress_session": True,
        "server_side": True,
        "engine": "shibui.stock_data_query (DuckDB corr(), one call)",
    }
    partial_path = tmp / "mats_partial.json"
    partial_path.write_text(json.dumps(partial), encoding="utf-8")
    return series_path, mats_path, partial_path


def run_renderer(tmp, series_path, mats_path, partial_path, out_path):
    cmd = [sys.executable, str(RENDER_PATH),
           "--current", str(mats_path),
           "--partial", str(partial_path),
           "--series", str(series_path),
           "--date", ART_DATE, "--iso-week", "2026-W45", "--fire-et", "10:00",
           "--regime", "stocks/bonds positively coupled but weak (SPY-TLT +0.31)",
           "--out", str(out_path)]
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p


def run_checker(art_path, mats_path, tmp, outputs_dir, reply=None):
    cmd = [sys.executable, str(CHECK_PATH),
           "--md", str(art_path), "--mats", str(mats_path),
           "--outputs-dir", str(outputs_dir)]
    if reply:
        cmd += ["--reply", str(reply)]
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p


def signal_line_of(art_text):
    m = re.search(r"^signal_line: (.*)$", art_text, re.M)
    return m.group(1).strip() if m else ""


def main():
    tmpdir = tempfile.mkdtemp(prefix="xasset-test-")
    tmp = Path(tmpdir)
    print(f"test_cross_asset_contract: workdir {tmpdir}")

    series_path, mats_path, partial_path = build_docs(tmp)
    art_path = tmp / f"{ART_DATE}.md"
    out_dir = tmp / "published"
    out_dir.mkdir()

    # ---- 1. the renderer produces a conforming artifact -----------------------
    p = run_renderer(tmp, series_path, mats_path, partial_path, art_path)
    if p.returncode != 0:
        fail(f"renderer exited {p.returncode}\n{p.stdout}\n{p.stderr}")
        print(f"test_cross_asset_contract: {len(FAILURES)} FAILURE(S)")
        return 1
    art = art_path.read_text(encoding="utf-8")
    print("  ok   renderer wrote a conforming artifact")

    # ---- 2. the checker passes it --------------------------------------------
    p = run_checker(art_path, mats_path, tmp, out_dir)
    if p.returncode != 0:
        fail("checker rejected a CONFORMING artifact:\n" + p.stdout)
    else:
        print("  ok   checker accepts the conforming artifact")

    # ---- 3. a conforming reply is accepted -----------------------------------
    sig = signal_line_of(art)
    if not sig:
        fail("the artifact carries no signal_line")
    reply_path = tmp / "reply.txt"
    reply_path.write_text(
        "### Signal\n" + sig + "\n\n### Method & caveats\n- synthetic\n", encoding="utf-8")
    p = run_checker(art_path, mats_path, tmp, out_dir, reply=reply_path)
    if p.returncode != 0:
        fail("checker rejected a CONFORMING reply:\n" + p.stdout)
    else:
        print("  ok   checker accepts the conforming reply")

    # ---- 4. mutations: the checker MUST fail each one ------------------------
    def mutate_and_expect_failure(name, fn, also_reply=None):
        m_art = tmp / f"mut_{name}.md"
        text = art
        text, reply_text = fn(text)
        m_art.write_text(text, encoding="utf-8")
        rp = None
        if reply_text is not None:
            rp = tmp / f"mut_{name}_reply.txt"
            rp.write_text(reply_text, encoding="utf-8")
        p = run_checker(m_art, mats_path, tmp, out_dir, reply=rp)
        if p.returncode == 0:
            fail(f"MUTATION NOT CAUGHT: {name}")
        else:
            print(f"  ok   checker catches: {name}")

    def m_stale_flag(text):
        return text.replace("window_end_derived_from_data: true",
                            "window_end_derived_from_data: false"), None

    def m_stale_contract(text):
        return text.replace("contract: cross-asset-v4", "contract: cross-asset-v3"), None

    def m_drop_section(text):
        i = text.find("## 📈 Performance")
        j = text.find("## 🧪 Effect of the excluded partial session")
        return text[:i] + text[j:], None

    def m_drop_band(text):
        return text.replace("🟧", ""), None

    def m_ragged_table(text):
        return text.replace("| **SPY** | S&P 500 |", "| **SPY** | S&P 500 | extra |"), None

    def m_no_signal_line(text):
        return re.sub(r"^signal_line: .*$", "signal_line:", text, flags=re.M), None

    def m_partial_overstates(text):
        # claims the proof while the in-progress session was NOT included
        text = text.replace("partial_includes_in_progress: yes",
                            "partial_includes_in_progress: no")
        return text, None

    def m_reply_without_implication(text):
        return text, ("### Signal\nSPY and TLT are correlated.\n\n"
                      "### Method & caveats\n- synthetic\n")

    def m_reply_without_threshold(text):
        return text, ("### Signal\n" + sig.replace("0.20", "twenty percent") + "\n\n"
                      "### Method & caveats\n- synthetic\n")

    mutate_and_expect_failure("stale-window-flag", m_stale_flag)
    mutate_and_expect_failure("stale-contract-marker", m_stale_contract)
    mutate_and_expect_failure("dropped-performance-section", m_drop_section)
    mutate_and_expect_failure("missing-colour-band", m_drop_band)
    mutate_and_expect_failure("ragged-table", m_ragged_table)
    mutate_and_expect_failure("missing-signal-line", m_no_signal_line)
    mutate_and_expect_failure("partial-overstates-its-proof", m_partial_overstates)
    mutate_and_expect_failure("reply-without-hedge-implication", m_reply_without_implication)
    mutate_and_expect_failure("reply-without-threshold", m_reply_without_threshold)

    # ---- 5. THE DUPLICATE WINDOW ---------------------------------------------
    # A second published artifact carrying the SAME window end must be refused.
    dup = out_dir / "2026-11-06.md"
    dup.write_text(art.replace(f"date: {ART_DATE}", "date: 2026-11-06"), encoding="utf-8")
    p = run_checker(art_path, mats_path, tmp, out_dir)
    if p.returncode == 0:
        fail("MUTATION NOT CAUGHT: duplicate-window (a second artifact already publishes "
             "the same window_end)")
    else:
        print("  ok   checker catches: duplicate-window")
    dup.unlink()

    # ---- 6. the renderer REFUSES a missing required input --------------------
    missing_series = tmp / "no_series.json"
    p = subprocess.run(
        [sys.executable, str(RENDER_PATH), "--current", str(mats_path),
         "--partial", str(partial_path), "--series", str(missing_series),
         "--date", ART_DATE, "--iso-week", "2026-W45", "--fire-et", "10:00",
         "--out", str(tmp / "nope.md")], capture_output=True, text=True)
    if p.returncode == 0:
        fail("the renderer wrote an artifact with --series pointing at a missing file "
             "— it must fail loudly")
    else:
        print(f"  ok   renderer refuses a missing --series (exit {p.returncode})")

    missing_partial = tmp / "no_partial.json"
    p = subprocess.run(
        [sys.executable, str(RENDER_PATH), "--current", str(mats_path),
         "--partial", str(missing_partial), "--series", str(series_path),
         "--date", ART_DATE, "--iso-week", "2026-W45", "--fire-et", "10:00",
         "--out", str(tmp / "nope.md")], capture_output=True, text=True)
    if p.returncode == 0:
        fail("the renderer wrote an artifact with --partial pointing at a missing file "
             "— it must fail loudly")
    else:
        print(f"  ok   renderer refuses a missing --partial (exit {p.returncode})")

    # ---- 7. the renderer refuses an OMITTED --series outright -----------------
    p = subprocess.run(
        [sys.executable, str(RENDER_PATH), "--current", str(mats_path),
         "--partial", str(partial_path),
         "--date", ART_DATE, "--iso-week", "2026-W45", "--fire-et", "10:00",
         "--out", str(tmp / "nope.md")], capture_output=True, text=True)
    if p.returncode == 0:
        fail("the renderer accepted an omitted --series — it must be required")
    else:
        print(f"  ok   renderer refuses an omitted --series (exit {p.returncode})")

    if FAILURES:
        print(f"test_cross_asset_contract: {len(FAILURES)} FAILURE(S)")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("test_cross_asset_contract: OK — the contract is satisfiable and every "
          "breach was caught")
    return 0


if __name__ == "__main__":
    sys.exit(main())
