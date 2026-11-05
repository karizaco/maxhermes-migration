#!/usr/bin/env python3
"""
test_breadth_contract.py — prove the cron #10 breadth contract is satisfiable AND that
the checker actually catches a breach.

Why
---
A checker that only ever fails is a checker nobody trusts, and a contract nobody can
satisfy is a contract that gets skipped. This test does both:

  1. builds a synthetic breadth history (the shape of 2026-11-04: a broad market
     healing while the index posture stayed weak, a real advance/decline tally, a
     divergence that has been widening),
  2. runs `breadth_metrics.py` over it with the network layer stubbed,
  3. renders the contract-shaped artifact,
  4. runs `check_breadth_artifact.py` and requires exit 0,
  5. then MUTATES that artifact eight different ways and requires the checker to fail
     each time.

USAGE
    python3 tools/test_breadth_contract.py
Exit codes: 0 = all good; 1 = a breach was not caught (or a contract cannot be met).
"""

import csv
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BM_PATH = ROOT / "cloud-prompts" / "skills" / "stock-screener-suite" / "scripts" / "breadth_metrics.py"
CK_PATH = ROOT / "tools" / "check_breadth_artifact.py"


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bm = _load(BM_PATH, "bm")
ck = _load(CK_PATH, "ck")

PASS = "PASS"
FAIL = "FAIL"

# ----------------------------------------------------------------------------------
# the synthetic history — 262 sessions ending 2026-11-04
# ----------------------------------------------------------------------------------
SESSIONS = 262
END_DATE = "2026-11-04"
UNIVERSE_N = 909


def _session_dates(n):
    """`n` weekday dates ending 2026-11-04 (no holiday calendar — synthetic data)."""
    from datetime import date, timedelta
    out = []
    d = date(2026, 11, 4)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d -= timedelta(days=1)
    return list(reversed(out))


DATES = _session_dates(SESSIONS)


def _breadth_rows():
    """A breadth series that heals from ~26% to 69.42% over the window."""
    rows = []
    for i, d in enumerate(DATES):
        t = i / (SESSIONS - 1)
        pct20 = 26.0 + (69.42 - 26.0) * t
        pct50 = 28.0 + (65.35 - 28.0) * t
        rows.append({
            "date": d, "n_lc": UNIVERSE_N,
            "pct_above_sma_20": round(pct20, 6),
            "pct_above_sma_50": round(pct50, 6),
            "rows_passing": len(DATES),
        })
    return rows


def _index_rows():
    """The index ETFs stay weak while the broad market heals — the divergence case."""
    rows = []
    for i, d in enumerate(DATES):
        n20 = 2 if i > len(DATES) - 8 else (i % 3)
        rows.append({
            "date": d, "n_etf": 5, "n_above_sma_20": n20,
            "n_above_sma_50": 2 if i > len(DATES) - 12 else 1,
            "rows_passing": len(DATES),
        })
    return rows


def _ad_rows():
    """A rising advance/decline tally over the last 13 sessions."""
    rows = []
    for i, d in enumerate(DATES[-13:]):
        advancing = 360 + i * 30
        declining = 547 - i * 30
        rows.append({
            "date": d, "n": UNIVERSE_N, "advancing": advancing, "declining": declining,
            "unchanged": 2, "rows_passing": 13,
        })
    return rows


def _etf_rows():
    out = []
    for tkr, close, sma20, sma50, ext in (
        ("SPY", 752.10, 769.33, 767.22, -1.97),
        ("RSP", 219.98, 215.34, 215.02, 2.31),
        ("QQQ", 681.09, 724.43, 724.35, -5.97),
        ("QQQE", 115.89, 119.18, 119.80, -3.26),
        ("IWM", 279.14, 277.20, 283.86, -1.66),
    ):
        out.append({
            "symbol": f"{tkr}.X", "ticker": tkr, "date": END_DATE, "close": close,
            "sma_20": sma20, "sma_50": sma50, "atr_14": 4.2, "atr_252d_avg": 4.5,
            "extension_pct": ext, "atr_extension_multiple": round(ext / 4.5, 2),
        })
    return out


class FakeBridge:
    """Stands in for the shibui MCP bridge. No network, deterministic rows."""

    def __init__(self, *a, **k):
        self.calls = 0

    def query(self, sql):
        self.calls += 1
        if "COUNT(*) FILTER" in sql:
            return _ad_rows()
        if "atr_252d_avg" in sql and "ROWS BETWEEN 251" in sql:
            return _etf_rows()
        if "n_above_sma_20" in sql:
            return _index_rows()
        if "pct_above_sma_20" in sql:
            return _breadth_rows()
        return []

    def query_paged(self, sql_template, **fmt):
        rows = self.query(sql_template.format(limit=200, offset=0, **fmt))
        if rows and "rows_passing" in rows[0]:
            assert len(rows) == rows[0]["rows_passing"], "paged stub is inconsistent"
        return rows


def _stub_network():
    bm.Bridge = FakeBridge
    bm.fetch_vix_pair = lambda *a, **k: {
        "vix": 16.61, "vix3m": 18.80, "quote_time_et": "2026-11-05 13:49:31",
        "source": "Cboe delayed-quote CDN (_VIX.json / _VIX3M.json)",
        "session_mode": "regular hours — live print", "vix_stable": True,
        "prev_close": {"vix": 16.99, "vix3m": 19.06},
        "price_change_pct": {"vix": -2.24, "vix3m": -1.36},
        "vix_fetches": [], "quote_date": "2026-11-05",
    }


LIVE = {
    "fire_time_et": "2026-11-05 14:00:54 ET",
    "live_date": "2026-11-05",
    "vix_quote_time": "2026-11-05 13:49:31 ET (Cboe delayed-quote CDN)",
    "vix_pair": "VIX 16.61 / VIX3M 18.80 — single pair, used everywhere in this document",
    "banner": "Intraday read at the 14:00 ET fire. The breadth numbers describe the "
              "2026-11-04 settled session; the tape and the volatility pair are live.",
    "tldr": (
        "- Breadth healed to 69.42% of the 909 large caps above their own 20-DMA — the 94th "
        "percentile of its own trailing year (ABOVE_NORMAL).\n"
        "- The divergence is +29.42 pp (BROAD): the average large cap is materially healthier "
        "than the index, whose own posture is still weak (2 of 5 ETFs above their 20-DMA).\n"
        "- Participation confirmed it — 658 advancing against 250 declining, a 10-session net of "
        "+805 — but the breadth percentage is a SETTLED 2026-11-04 number, not the live tape."
    ),
    "tape_block": "| SPY | 756.13 | +0.54% | Cboe delayed-quote CDN |",
    "volatility_block": "| VIX | 16.61 | -2.24% | 2026-11-05 13:49:31 | Cboe delayed-quote CDN |",
    "flags_block": "None — no index reading in this file is arithmetically distorted, and the "
                   "universe count matches the CSV.",
    "method_block": (
        "- The breadth numbers and the advance/decline tally describe the **2026-11-04 settled "
        "session**; the tape and the volatility pair are **live 2026-11-05**. The two are "
        "labelled separately and never blended into one number.\n"
        "- The RSP-vs-SPY spread is a cap-weight participation proxy, not an advance/decline "
        "tally; the tally above is computed from the same universe's closes.\n"
        "- The universe is **not frozen** — the market-cap floor is applied to the latest "
        "`valuation` row, so the count moves as those rows refresh. Today's universe: 909 names."
    ),
}


def _render(tmpdir):
    """Build a conforming artifact set on disk."""
    _stub_network()
    metrics = bm.build_metrics(FakeBridge(), END_DATE, 380, 12)
    out_dir = Path(tmpdir) / "daily-screens" / "2026-11-05"
    out_dir.mkdir(parents=True, exist_ok=True)
    bm.write_outputs(metrics, out_dir, 30)
    md = bm.render_markdown(metrics, LIVE)
    (out_dir / "breadth-snapshot.md").write_text(md, encoding="utf-8")
    return metrics, out_dir


def _run_checker(out_dir, reply=None):
    cmd = [sys.executable, str(CK_PATH),
           "--md", str(out_dir / "breadth-snapshot.md"),
           "--csv", str(out_dir / "breadth-snapshot.csv"),
           "--json", str(out_dir / "breadth-snapshot.json"),
           "--regime", str(out_dir / "_regime-intraday.json")]
    if reply:
        cmd += ["--reply", reply]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode, proc.stdout + proc.stderr


# ----------------------------------------------------------------------------------
# the mutations — each MUST be caught
# ----------------------------------------------------------------------------------
def _mut_no_ad_row(md, out_dir):
    md = re.sub(r"^\| Advance/decline.*\n", "", md, flags=re.M)
    md = md.replace("658 advancing / 250 declining / 1 unchanged", "")
    return md


def _mut_percentile_out_of_range(md, out_dir):
    return re.sub(r"(`breadth_pctile_1y`\s*\|)\s*[\d.]+", r"\g<1> 140.2", md, count=1)


def _mut_no_divergence_band(md, out_dir):
    return re.sub(r"(`breadth_divergence`\s*\|[^|]*\|\s*)(BROAD|MATCHED|NARROW)",
                  r"\g<1>—", md, count=1)


def _mut_short_divergence_history(md, out_dir):
    return re.sub(r"^\| 2026-10-29 \| .*\n", "", md, flags=re.M)


def _mut_regime_as_one_string(md, out_dir):
    md = md.replace(
        "size_cut_pct: 0\nuncertainty: false\nlate_cycle: false",
        'regime: "size_cut 0% · uncertainty false · late_cycle false"',
    )
    return md


def _mut_two_bullet_tldr(md, out_dir):
    lines = [ln for ln in md.splitlines() if ln.startswith("- ")]
    # drop the third TL;DR bullet only
    idx = md.splitlines()
    seen = 0
    for i, ln in enumerate(idx):
        if ln.startswith("- "):
            seen += 1
            if seen == 3:
                del idx[i]
                break
    return "\n".join(idx) + "\n"


def _mut_csv_disagrees(md, out_dir):
    p = out_dir / "breadth-snapshot.csv"
    rows = list(csv.DictReader(open(p, newline="", encoding="utf-8")))
    fields = list(rows[0].keys())
    for r in rows:
        if r["is_data_date"] == "yes":
            r["pct_above_sma_20"] = "41.00"
    with open(p, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    return md


def _mut_empty_atr_extensions(md, out_dir):
    p = out_dir / "_regime-intraday.json"
    blob = json.load(open(p, encoding="utf-8"))
    blob["atr_extensions"] = {}
    json.dump(blob, open(p, "w", encoding="utf-8"), indent=2)
    return md


def _mut_missing_divergence_field(md, out_dir):
    return md.replace("`breadth_divergence`", "`divergence_spread`")


def _mut_fill_marker_survives(md, out_dir):
    return md.replace("## Flags", "## Flags\n\n<!-- FILL: flags_block -->")


def _mut_no_tldr(md, out_dir):
    md = re.sub(r"## TL;DR\n\n.*?\n\n", "## TL;DR\n\nn/a\n\n", md, count=1, flags=re.S)
    return md


MUTATIONS = [
    ("no advance/decline row in the headline table", _mut_no_ad_row),
    ("breadth_pctile_1y outside 0..100", _mut_percentile_out_of_range),
    ("divergence band missing", _mut_no_divergence_band),
    ("divergence history shorter than 5 sessions", _mut_short_divergence_history),
    ("regime flags concatenated into one string", _mut_regime_as_one_string),
    ("TL;DR with two bullets instead of three", _mut_two_bullet_tldr),
    ("CSV disagreeing with the markdown", _mut_csv_disagrees),
    ("empty atr_extensions in the regime payload", _mut_empty_atr_extensions),
    ("divergence published under the wrong field name", _mut_missing_divergence_field),
    ("an unfilled FILL marker surviving in the artifact", _mut_fill_marker_survives),
    ("the TL;DR section removed", _mut_no_tldr),
]


def main():
    results = []
    tmp = tempfile.mkdtemp(prefix="breadth_contract_")
    try:
        metrics, out_dir = _render(tmp)

        # ---- the contract must be SATISFIABLE -------------------------------------
        md_path = out_dir / "breadth-snapshot.md"
        baseline = md_path.read_text(encoding="utf-8")
        code, out = _run_checker(out_dir)
        if code != 0:
            results.append((FAIL, "a conforming artifact FAILS the checker", out.strip()))
        else:
            results.append((PASS, "a conforming artifact passes the checker", ""))

        # ---- the reply contract ----------------------------------------------------
        reply_path = Path(tmp) / "reply.txt"
        reply_path.write_text(
            "### Signal\n"
            "- Breadth divergence +29.42 pp (BROAD) — the average large cap is far healthier "
            "than the index.\n"
            "- Advance/decline 658 advancing / 250 declining on the 2026-11-04 settle.\n"
            "\n### Files\n- breadth-snapshot.md\n",
            encoding="utf-8")
        code, out = _run_checker(out_dir, reply=str(reply_path))
        if code != 0:
            results.append((FAIL, "a conforming reply FAILS the checker", out.strip()))
        else:
            results.append((PASS, "a conforming reply passes the checker", ""))

        # a reply that omits the divergence must fail
        reply_path.write_text(
            "### Signal\n- Breadth was healthy today.\n\n### Files\n- breadth-snapshot.md\n",
            encoding="utf-8")
        code, out = _run_checker(out_dir, reply=str(reply_path))
        if code == 0:
            results.append((FAIL, "a reply that omits the divergence passes the checker", ""))
        else:
            results.append((PASS, "a reply that omits the divergence is caught", ""))

        # ---- each mutation MUST be caught -------------------------------------------
        for name, mutate in MUTATIONS:
            # a fresh conforming set for every mutation
            mut_root = Path(tmp) / ("mut_" + re.sub(r"\W+", "_", name))
            _, mut_dir = _render(mut_root)
            md = mutate((mut_dir / "breadth-snapshot.md").read_text(encoding="utf-8"), mut_dir)
            (mut_dir / "breadth-snapshot.md").write_text(md, encoding="utf-8")
            code, out = _run_checker(mut_dir)
            if code == 0:
                results.append((FAIL, f"NOT CAUGHT: {name}", "the checker exited 0"))
            else:
                first = ""
                for line in out.splitlines():
                    if line.strip().startswith("- "):
                        first = line.strip()[2:]
                        break
                results.append((PASS, f"caught: {name}", first))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("=" * 78)
    print("cron #10 breadth artifact contract — regression test")
    print("=" * 78)
    failures = 0
    for status, name, detail in results:
        print(f"  {status}  {name}")
        if detail:
            print(f"        {detail[:150]}")
        if status == FAIL:
            failures += 1
    print("-" * 78)
    print(f"  {len(results) - failures}/{len(results)} checks behaved correctly")
    if failures:
        print(f"  RESULT: {failures} problem(s)")
        return 1
    print("  RESULT: the contract is satisfiable and every breach is caught")
    return 0


if __name__ == "__main__":
    sys.exit(main())
