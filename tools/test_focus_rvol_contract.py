#!/usr/bin/env python3
"""
test_focus_rvol_contract.py — hermetic test for check_focus_rvol_artifact.py.

A checker that has never been observed FAILING is a claim, not a check. This builds the two
shapes in a temp dir — a COMPLIANT artifact and the BROKEN shape that shipped on 2026-11-05
through 2026-11-11 — and asserts the checker exits 0 on the first and non-zero on the second.

No network. No repo checkout. Run:  python3 tools/test_focus_rvol_contract.py
"""

from __future__ import annotations

import csv
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CHECKER = os.path.join(HERE, "check_focus_rvol_artifact.py")

CSV_HEADER = [
    "symbol", "universe", "close", "rvol_intraday_live", "rvol_now", "rvol_prev",
    "rvol_at_09_38", "rvol_trend", "prev_session_rvol", "prev_session_rvol_source",
    "prev_session_rvol_published", "denominator_drift_pct", "bucket", "tier",
    "pm_vol", "pm_vol_source", "data timestamp",
]

# symbol, rvol_now, prev_session_rvol, source, tier
COMPLIANT = [
    ("FROG", "focus", 1.8297, 0.9218, "recomputed_same_feed", "ALERT"),
    ("LASR", "focus", 1.8069, 1.4976, "recomputed_same_feed", "ALERT"),
    ("ETON", "focus", 2.7432, 2.3140, "recomputed_same_feed", "WATCH"),
    ("OKLO", "focus", 1.1530, 1.0666, "recomputed_same_feed", "-"),
    ("RHLD", "focus", 0.8226, "n/a", "unavailable", "-"),
    ("FRVO", "wider", 2.6090, 0.4100, "recomputed_same_feed", "ALERT"),
    ("PRAX", "wider", 1.4000, 0.5300, "recomputed_same_feed", "NEAR MISS"),
]

# The shape that actually shipped: no provenance column, every prior reading n/a, and
# seven names above the bar with no baseline at all.
BROKEN = [
    ("ETON", "focus", 2.7432, "n/a", "", "WATCH"),
    ("QNT", "focus", 2.0793, "n/a", "", "WATCH"),
    ("RGTI", "focus", 2.0711, "n/a", "", "WATCH"),
    ("TMDX", "focus", 2.0079, "n/a", "", "WATCH"),
    ("FLY", "focus", 1.9335, "n/a", "", "WATCH"),
    ("FROG", "focus", 1.8297, "n/a", "", "WATCH"),
    ("LASR", "focus", 1.8069, "n/a", "", "WATCH"),
    ("OKLO", "focus", 1.1530, "n/a", "", "-"),
    ("CYRX", "focus", 1.0834, "n/a", "", "-"),
    ("IONQ", "focus", 0.9534, "n/a", "", "-"),
    ("RHLD", "focus", 0.8226, "n/a", "", "-"),
    ("KRMN", "focus", 0.5168, "n/a", "", "-"),
]


def write_csv(path: str, rows, with_source: bool) -> None:
    header = list(CSV_HEADER) if with_source else [
        c for c in CSV_HEADER if c != "prev_session_rvol_source"]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for sym, uni, now, prev, src, tier in rows:
            row = {
                "symbol": sym, "universe": uni, "close": "10.00",
                "rvol_intraday_live": "0.05",
                "rvol_now": now, "rvol_prev": now, "rvol_at_09_38": "0.04",
                "rvol_trend": "STABLE", "prev_session_rvol": prev,
                "prev_session_rvol_source": src, "prev_session_rvol_published": "n/a",
                "denominator_drift_pct": "n/a", "bucket": "RVOL Required",
                "tier": tier, "pm_vol": "0", "pm_vol_source": "not_subtracted",
                "data timestamp": "2026-11-12 09:45:00 ET",
            }
            w.writerow([row[c] for c in header])


def write_md(path: str, rows, compliant: bool) -> None:
    if compliant:
        alerts = ("## Alerts\n\n"
                  "- **FROG** - 1.83x vs 0.92x on the prior session (recomputed on the same "
                  "feed), close 4.10 - crossed UP through the 1.5x bar.\n"
                  "- **LASR** - 1.81x vs 1.50x on the prior session (recomputed on the same "
                  "feed), close 7.20 - crossed UP through the 1.5x bar.\n"
                  "- **FRVO** - 2.61x vs 0.41x on the prior session (recomputed on the same "
                  "feed), close 9.15 - crossed UP through the 1.5x bar.\n\n")
    else:
        alerts = ("## Alerts\n\n"
                  "**none** - and the reason matters. The previous session's CSV does not carry "
                  "today's names, so `prev_session_rvol` is `n/a` on every row and no crossing "
                  "can be proven for any of them.\n\n"
                  "- **ETON** - rvol_now **2.74x** vs rvol_prev 2.76x; prev-session reading n/a, "
                  "so the crossing test starts next session.\n"
                  "- **FROG** - rvol_now **1.83x** vs rvol_prev 2.16x; prev-session reading n/a.\n\n")
    def table(rows_subset):
        return "".join(f"| {s} | {u} | {n} | {p} | {sr or '—'} | {t} |\n"
                       for s, u, n, p, sr, t in rows_subset)

    body = (
        "---\n"
        "date: 2026-11-12\n"
        "cron: 07\n"
        "rvol_alert_threshold: 1.5\n"
        "universe_source: focus_plus_wider\n"
        "wider_universe_size: 2\n"
        "wider_universe_source: focus+master+17\n"
        "---\n\n"
        "# Focus RVOL snapshot — 2026-11-12\n\n"
        "## Focus table\n\n"
        "| symbol | universe | rvol_now | prev_session_rvol | prev_session_rvol_source | tier |\n"
        "|---|---|---|---|---|---|\n"
        + table([r for r in rows if r[1] == "focus"])
        + "\n## Wider universe\n\n"
        "| symbol | universe | rvol_now | prev_session_rvol | prev_session_rvol_source | tier |\n"
        "|---|---|---|---|---|---|\n"
        + table([r for r in rows if r[1] == "wider"])
        + "\n### Counts\n\n"
        "- universe size: " + str(len(rows)) + "\n"
        "- Required count: 7\n"
        "- alert count: " + ("3" if compliant else "0") + "\n"
        "- crossings: " + ("3" if compliant else "0") + "\n\n"
        + alerts
        + "## Method\n\n"
        "Baseline provenance: prior readings recomputed on the same feed with the identical "
        "formula and the same denominator as today's reading.\n"
        "`prev_session_rvol_source` is published on every row.\n"
    )
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)


def run_checker(md: str, csvp: str) -> tuple[int, str]:
    r = subprocess.run([sys.executable, CHECKER, "--md", md, "--csv", csvp],
                       capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def main() -> None:
    failures = []

    with tempfile.TemporaryDirectory() as tmp:
        # ---- the compliant shape must PASS
        md = os.path.join(tmp, "ok.md"); cp = os.path.join(tmp, "ok.csv")
        write_csv(cp, COMPLIANT, with_source=True)
        write_md(md, COMPLIANT, compliant=True)
        rc, out = run_checker(md, cp)
        if rc != 0:
            failures.append(f"the COMPLIANT artifact was rejected (exit {rc}):\n{out}")
        else:
            print("  ok   compliant artifact -> CONTRACT OK")

        # ---- the shape that shipped must FAIL, and specifically on the silencing clause
        md = os.path.join(tmp, "bad.md"); cp = os.path.join(tmp, "bad.csv")
        write_csv(cp, BROKEN, with_source=False)
        write_md(md, BROKEN, compliant=False)
        rc, out = run_checker(md, cp)
        if rc == 0:
            failures.append("the BROKEN artifact PASSED — the checker is a no-op")
        else:
            print("  ok   broken artifact -> CONTRACT FAILED")
        if "[C6]" not in out:
            failures.append("the broken artifact did not trip C6 (the alert-silencing clause)")
        else:
            print("  ok   broken artifact trips C6 (the alert-silencing clause)")

    if failures:
        print("\nTEST FAILED:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("\nTEST OK — the checker passes a compliant artifact and fails the broken one.")
    sys.exit(0)


if __name__ == "__main__":
    main()
