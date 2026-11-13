#!/usr/bin/env python3
"""Regression tests for the cron #09 sweep engines.

Covers the two defects measured on the 2026-11-12 fire:

1. `daily_sweep_engines.overlay_quality` built ONE request carrying every
   symbol in a single IN list.  With the whole book (3,814 tickers) the bridge
   answered an EMPTY body (`rpc_failed` / `unparseable_response`), which reads
   exactly like "no rows" — so the overlay silently returned {} and every
   candidate was published with no valuation verdict.  The symbol list is now
   chunked (200 per call).

2. `screen.py consume` wrote `ariel-hernandez.md` from the CANSLIM proxy, so the
   Hernandez theme -> group -> leaders funnel's own names reached no per-stylist
   file at all, and the file duplicated jeff-sun.md's names.

Run:  python3 tools/test_daily_sweep_engines.py
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ENGINES = REPO / "tools" / "daily_sweep_engines.py"
SCREEN = REPO / "cloud-prompts" / "skills" / "stock-screener-suite" / "scripts" / "screen.py"

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))


def load(path: Path, alias: str):
    spec = importlib.util.spec_from_file_location(alias, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[alias] = mod
    spec.loader.exec_module(mod)
    return mod


dse = load(ENGINES, "dse_test")
scr = load(SCREEN, "scr_test")


# ---------------------------------------------------------------- overlay chunking
class _FakeBridge:
    """Counts the chunks and records the symbol count in each IN list.

    The engine pages a chunk with LIMIT/OFFSET, so the fake answers the first
    page with one row per symbol and every later page with nothing - exactly
    how the real bridge behaves for a 200-symbol chunk.
    """

    def __init__(self) -> None:
        self.chunks: list[int] = []
        self.calls = 0
        self.n = 0

    def __call__(self, bridge, server, tool, args):
        import re as _re
        self.calls += 1
        query = args["query"]
        start = query.index("ticker IN (") + len("ticker IN (")
        end = query.index(")", start)
        n = len([x for x in query[start:end].split(",") if x.strip()])
        m = _re.search(r"OFFSET (\d+)", query)
        offset = int(m.group(1)) if m else 0
        if offset == 0:
            self.chunks.append(n)
            rows = [{"symbol": f"S{self.n + i}", "t1_close": 1.0} for i in range(n)]
            self.n += n
            return rows
        return []


fake = _FakeBridge()
dse._bridge_call = fake          # the engine calls the module-level helper
syms = [f"T{i}" for i in range(850)]
out = dse.overlay_quality("bridge", syms, "2026-11-11")
check("overlay_quality chunks the symbol list",
      fake.chunks == [200, 200, 200, 200, 50], f"chunk sizes {fake.chunks}")
check("every chunk is within the bridge's comfortable size",
      all(n <= 200 for n in fake.chunks), f"max {max(fake.chunks)}")
check("overlay_quality returns one row per symbol",
      len(out) == len(syms), f"{len(out)} of {len(syms)}")
check("the chunking costs ceil(n/200) chunks, not one request",
      len(fake.chunks) == 5, f"{len(fake.chunks)} chunks")


# a chunk that the bridge cannot answer must NOT look like "no rows"
class _BrokenBridge:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, bridge, server, tool, args):
        self.calls += 1
        if self.calls == 2:
            raise dse.EngineError('bridge call failed: {"error": "rpc_failed"}')
        return [{"symbol": "X1", "t1_close": 1.0}]


broken = _BrokenBridge()
dse._bridge_call = broken
try:
    dse.overlay_quality("bridge", [f"T{i}" for i in range(450)], "2026-11-11")
    raised = False
except dse.EngineError:
    raised = True
check("a broken chunk raises instead of returning a short book", raised)

# ---------------------------------------------------------------- consume: ariel file
def _row(symbol, origin, **extra):
    d = {"symbol": symbol, "close": 10.0, "chg_pct": 1.0, "rows_passing": 1}
    d.update(extra)
    return {"origin": origin, **d}


with tempfile.TemporaryDirectory() as td:
    payload = {
        "date": "2026-11-12",
        "data_as_of": "2026-11-11",
        "sweep": [
            _row("THEM", "H_hernandez_theme"),
            _row("CAN", "jeff_sun_canslim"),
            _row("SB", "A_stockbee_4pct"),
        ],
        "screen_coverage": {
            "H_hernandez_theme": {"rows_passing": 1, "rows_kept": 1},
            "jeff_sun_canslim": {"rows_passing": 1, "rows_kept": 1},
            "A_stockbee_4pct": {"rows_passing": 1, "rows_kept": 1},
        },
        "breadth": [{"metric": "largecap_breadth", "breadth_pct_largecap": 55.0}],
        "vix_price": 16.0,
        "vix3m_price": 17.0,
    }
    src = Path(td) / "results.json"
    src.write_text(json.dumps(payload))
    import subprocess
    r = subprocess.run([sys.executable, str(SCREEN), "consume", "--in", str(src),
                        "--date", "2026-11-12", "--vault", td],
                       capture_output=True, text=True, timeout=300)
    outdir = Path(td) / "2026-11-12"
    ariel = (outdir / "ariel-hernandez.md").read_text() if (outdir / "ariel-hernandez.md").exists() else ""
    jeff = (outdir / "jeff-sun.md").read_text() if (outdir / "jeff-sun.md").exists() else ""
    check("consume exits 0", r.returncode == 0, r.stderr[-200:])
    check("ariel-hernandez.md carries the theme-funnel name",
          "THEM" in ariel, ariel[:120])
    check("ariel-hernandez.md does not carry the CANSLIM proxy name",
          "CAN" not in ariel)
    check("jeff-sun.md still carries the CANSLIM name", "CAN" in jeff)

# ---------------------------------------------------------------- report
failed = 0
for name, ok, detail in results:
    print(("ok   " if ok else "FAIL ") + name + (f"   [{detail}]" if detail else ""))
    if not ok:
        failed += 1
print(f"\n{len(results) - failed} checks passed, {failed} failed")
sys.exit(1 if failed else 0)
