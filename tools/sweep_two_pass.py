#!/usr/bin/env python3
"""
sweep_two_pass.py — run tools/sweep_pipeline.py in TWO passes so the metered
MCP bridge allowance is spent ONCE.

SWEEP_TWO_PASS_V1

WHY
---
The pipeline's own contract (§4.5.5 of the stock-screener-suite skill) is:

    1. python3 sweep_pipeline.py run --date <D> ...        # fetch, tier, render
    2. the Agent writes the narrative into scratch/live.json
    3. python3 sweep_pipeline.py run --date <D> --live-json scratch/live.json

Step 3 is a SECOND `cmd_run`, and `cmd_run` re-runs every fetch stage. The
bridge is METERED — 50 tool calls/day per egress IP, shared across the whole
fleet — so step 3 spends the allowance a second time on data that was already
fetched in step 1. The pipeline's `--replay` flags (--fresh-json,
--breadth-json, --enrichment-json, --branches-json, --canslim-json,
--overlay-json) exist for exactly this, but NOTHING on the first pass saves
those stage outputs to disk, so the flags have nothing to point at.

The defect is silent: the second run usually succeeds, and the artifact looks
perfect. What it costs is the fleet's shared bridge allowance.

THE FIX
-------
This wrapper imports sweep_pipeline and patches the four COLLECTOR functions
in memory so that

  * pass 1 fetches everything and PERSISTS each collector's result under
    <scratch>/pass1/, and
  * pass 2 replays those persisted results (no network, no bridge calls) with
    the Agent's narrative rendered on top.

The pipeline file on disk is never modified. `tools/sweep_pipeline.py` already
writes `scratch/tv_sweep.json` and `scratch/overlay.json` itself, so those two
are reused as-is via the pipeline's own `--fresh-json` / `--overlay-json`
flags; only the four stages it does not persist are captured here.

USAGE
-----
    # pass 1 — the fetch (the bridge allowance is spent HERE, once)
    python3 sweep_two_pass.py --phase 1 --date 2026-11-24

    # the Agent reads the rendered artifact, then writes the narrative:
    python3 - <<'PY'
    import json
    live = { "weekday": "...", "tldr": "...", ... }
    json.dump(live, open("/workspace/scratch/live-<DATE>.json", "w"))
    PY

    # pass 2 — re-render with the narrative, on the SAME data, no refetch
    python3 sweep_two_pass.py --phase 2 --date 2026-11-24 \
        --live-json /workspace/scratch/live-2026-11-24.json

Phase 1 is EXPECTED to exit 1: the pipeline's check stage rejects an artifact
that still carries a `<!-- FILL: ... -->` stub marker, and the narrative does
not exist yet. The files are written; phase 2 re-renders and re-checks them.

EXIT CODES
----------
    0  the pipeline's own check passed (phase 2)
    1  the pipeline's check failed (expected in phase 1 — stubs)
    2  this wrapper could not find its inputs
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

CAPABILITY_MARKER = "SWEEP_TWO_PASS_V1"

DEFAULT_PIPELINE = "/workspace/tools/sweep_pipeline.py"
DEFAULT_SCRATCH = "/workspace/scratch"


def _load_pipeline(path: str):
    sys.path.insert(0, str(Path(path).resolve().parent))
    import sweep_pipeline  # noqa: E402
    return sweep_pipeline


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="cron #09 two-pass sweep driver")
    p.add_argument("--phase", choices=["1", "2"], required=True,
                   help="1 = fetch and persist; 2 = replay and render the narrative")
    p.add_argument("--date", required=True, help="the cron day (YYYY-MM-DD)")
    p.add_argument("--out", default="/workspace/daily-screens")
    p.add_argument("--scratch", default=DEFAULT_SCRATCH)
    p.add_argument("--bridge", default="/workspace/mcp_bridge.py")
    p.add_argument("--pipeline", default=DEFAULT_PIPELINE)
    p.add_argument("--live-json", default=None,
                   help="the Agent's narrative (phase 2)")
    p.add_argument("--workers", type=int, default=6,
                   help="parallel shibui calls (keep <= 8)")
    p.add_argument("--t1-date", default=None,
                   help="FORCE the shibui screen session (a replay)")
    a = p.parse_args(argv)

    if not Path(a.pipeline).exists():
        print(f"sweep_two_pass.py: pipeline not found: {a.pipeline}", file=sys.stderr)
        return 2

    sp = _load_pipeline(a.pipeline)
    scratch = Path(a.scratch)
    save_dir = scratch / "pass1"

    def save(name, obj):
        save_dir.mkdir(parents=True, exist_ok=True)
        (save_dir / name).write_text(json.dumps(obj, indent=1, default=str))
        print(f"[saved] {name}")

    if a.phase == "1":
        # --- capture every stage output the pipeline does not persist itself ---
        real = {k: getattr(sp, k) for k in
                ("collect_branches", "collect_canslim_growth",
                 "collect_enrichment", "collect_breadth")}

        def wrap(key, fname):
            def inner(*args, **kwargs):
                out = real[key](*args, **kwargs)
                save(fname, out)
                return out
            return inner

        sp.collect_branches = wrap("collect_branches", "branches.json")
        sp.collect_canslim_growth = wrap("collect_canslim_growth", "canslim.json")
        sp.collect_enrichment = wrap("collect_enrichment", "enrichment.json")
        sp.collect_breadth = wrap("collect_breadth", "breadth.json")
    else:
        need = ["branches.json", "canslim.json", "enrichment.json", "breadth.json"]
        missing = [n for n in need if not (save_dir / n).exists()]
        if missing:
            print(f"sweep_two_pass.py: pass 1 outputs missing: {missing} "
                  f"(run --phase 1 first)", file=sys.stderr)
            return 2
        b = json.loads((save_dir / "branches.json").read_text())
        # collect_branches returns the PAIR (rows, coverage), and phase 1
        # persisted that pair verbatim — so the file on disk is a 2-element
        # ARRAY, not a dict. Reading it as a dict ("b['rows']") raises
        # TypeError: list indices must be integers. Accept BOTH shapes.
        if isinstance(b, dict):
            rows_b, cov_b = b.get("rows"), b.get("coverage")
        else:
            rows_b, cov_b = b[0], b[1]
        # keep the REAL coverage, because the pipeline's own replay path
        # rebuilds it with pages=1.
        sp.collect_branches = lambda *ar, **kw: (rows_b, cov_b)
        sp.collect_canslim_growth = lambda *ar, **kw: json.loads(
            (save_dir / "canslim.json").read_text())
        sp.collect_enrichment = lambda *ar, **kw: json.loads(
            (save_dir / "enrichment.json").read_text())
        sp.collect_breadth = lambda *ar, **kw: json.loads(
            (save_dir / "breadth.json").read_text())

    args = argparse.Namespace(
        date=a.date, out=a.out, scratch=a.scratch, bridge=a.bridge,
        live_json=a.live_json, workers=a.workers, t1_date=a.t1_date,
        fresh_json=None, breadth_json=None, enrichment_json=None,
        branches_json=None, canslim_json=None, overlay_json=None,
    )

    if a.phase == "2":
        # the pipeline already persists these two on the first pass
        tv = scratch / "tv_sweep.json"
        ov = scratch / "overlay.json"
        if tv.exists():
            args.fresh_json = str(tv)
        if ov.exists():
            args.overlay_json = str(ov)

    rc = sp.cmd_run(args)
    print(f"phase {a.phase} rc={rc}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
