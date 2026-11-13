#!/usr/bin/env python3
"""Regression tests for the cron #09 sweep pipeline's REPLAY path.

The 2026-11-12 fire was resumed in place on 2026-11-13 and had to be rebuilt
from saved passes.  Three defects on that path cost real time:

1. `--scratch` pointed at a directory that did not exist.  The pipeline never
   created it, so the run died with FileNotFoundError on `book_symbols.txt`
   AFTER the theme pool had been built.

2. `--fresh-json` was only READ.  `consume` is called with `--fresh-book
   <scratch>/tv_sweep.json`, so the saved book was never on disk at that name
   and the run died with "fresh-book file not found" AFTER the whole fetch.

3. `--branches-json` was read as a FLAT `{branch: [rows]}` map.  The branch
   collector writes a NESTED `{"rows": {...}, "coverage": {...}}` file, so every
   branch came back EMPTY and the artifact had no peoplewish rows and no
   parabolic lists.  The check stage caught it, but the fetch was already spent.

Run:  python3 tools/test_sweep_replay.py
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PIPELINE = REPO / "tools" / "sweep_pipeline.py"

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))


spec = importlib.util.spec_from_file_location("sp_test", PIPELINE)
sp = importlib.util.module_from_spec(spec)
sys.modules["sp_test"] = sp
spec.loader.exec_module(sp)

BRANCH = "A_stockbee_4pct"
ROWS = [{"origin": BRANCH, "symbol": "AAA.NYSE", "close": 10.0, "rows_passing": 1}]

with tempfile.TemporaryDirectory() as td:
    td = Path(td)

    # --- 3. the saved branch file: flat AND nested both load --------------
    flat = td / "flat.json"
    flat.write_text(json.dumps({BRANCH: ROWS}))
    nested = td / "nested.json"
    nested.write_text(json.dumps({"rows": {BRANCH: ROWS}, "coverage": {BRANCH: {"rows_passing": 1}}}))

    got_flat = sp._load_saved_branches(str(flat))
    check("a FLAT saved branch file loads", got_flat.get(BRANCH) == ROWS)
    got_nested = sp._load_saved_branches(str(nested))
    check("a NESTED saved branch file loads its rows",
          got_nested.get(BRANCH) == ROWS, f"keys {list(got_nested)}")
    check("the nested shape does not silently produce an empty book",
          bool(got_nested.get(BRANCH)))

    # --- 1. the scratch dir is created ------------------------------------
    scratch = td / "does-not-exist-yet" / "scratch"
    out = td / "out"
    fresh = td / "fresh.json"
    fresh.write_text(json.dumps({"data_as_of": "2026-11-12", "rows": [], "branches": {}}))
    branches = td / "branches.json"
    branches.write_text(json.dumps({"rows": {BRANCH: ROWS}}))
    r = subprocess.run([sys.executable, str(PIPELINE), "run",
                        "--date", "2026-11-12", "--t1-date", "2026-11-11",
                        "--out", str(out), "--scratch", str(scratch),
                        "--bridge", "/nonexistent/bridge.py",
                        "--fresh-json", str(fresh),
                        "--branches-json", str(branches),
                        "--live-json", str(td / "live.json")],
                       capture_output=True, text=True, timeout=600)
    check("the run created the scratch directory it was pointed at",
          scratch.is_dir(), f"rc={r.returncode}")
    # --- 2. the saved fresh book is staged where consume looks for it ------
    check("the saved fresh book is staged at scratch/tv_sweep.json",
          (scratch / "tv_sweep.json").exists())
    check("the staged fresh book holds the saved book",
          (scratch / "tv_sweep.json").exists()
          and json.loads((scratch / "tv_sweep.json").read_text()).get("data_as_of") == "2026-11-12")

failed = 0
for name, ok, detail in results:
    print(("ok   " if ok else "FAIL ") + name + (f"   [{detail}]" if detail else ""))
    if not ok:
        failed += 1
print(f"\n{len(results) - failed} checks passed, {failed} failed")
sys.exit(1 if failed else 0)
