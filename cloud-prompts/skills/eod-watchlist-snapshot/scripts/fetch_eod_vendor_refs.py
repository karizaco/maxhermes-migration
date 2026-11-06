#!/usr/bin/env python3
"""Pull the US EOD reference tables from the vendor (shibui) over the MCP-over-HTTP bridge.

EOD_DERIVE_V2

TWO TABLES, TWO JOBS
--------------------
1. `valuation` — the vendor's OWN market-cap carrier rows. The vendor stamps a cap on one
   class row per company and leaves the siblings null, so the set of rows that carry a
   non-null cap IS the carrier map. It is never re-derived by a volume heuristic
   (LILA carries its cap over LILAK despite 4x the volume).
2. `ownership_stats` — `shares_float`, the public float, which the liquidity floors in the
   other routines apply by hand.

PAGINATION IS KEYSET, SEQUENTIAL, AND NEVER CONCURRENT
------------------------------------------------------
`LIMIT/OFFSET` needs a unique `ORDER BY` or pages overlap and rows go missing; concurrent
paging makes the server throttle and return EMPTY bodies (an empty body is an outage, never
"no rows"). Keyset (`symbol > :last ORDER BY symbol LIMIT 200`) with concurrency 1 is the
safe form. The bridge caps every query at 200 rows, so the symbol list is chunked to 150.

OUTPUT
------
vendor_refs.json: {"as_of": {...}, "vendor_caps": {ticker: {"cap":…, "date":…}},
                   "floats": {ticker: shares_float}, "universe": {ticker: symbol}}
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

BRIDGE = os.environ.get("MCP_BRIDGE", "/workspace/mcp_bridge.py")
ARGS_FILE = "/tmp/shibui_q.json"


def query(sql: str, retries: int = 3) -> list[dict]:
    with open(ARGS_FILE, "w") as fh:
        json.dump({"query": sql, "user_prompt": "us eod reference tables"}, fh)
    last = ""
    for attempt in range(retries):
        proc = subprocess.run([sys.executable, BRIDGE, "shibui", "stock_data_query", ARGS_FILE],
                              capture_output=True, text=True)
        body = (proc.stdout or "").strip()
        if body:
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                last = body[:200]
        else:
            last = "empty_body"
        time.sleep(2 + 3 * attempt)
    raise RuntimeError(f"query failed: {last}\nSQL: {sql[:200]}")


def chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def main() -> int:
    universe = json.load(open(sys.argv[1]))
    out_path = sys.argv[2]

    syms = [r["symbol"] for r in universe]
    tickers = {r["symbol"]: r["ticker"] for r in universe}

    vendor_caps: dict[str, dict] = {}
    floats: dict[str, float] = {}
    max_dates: dict[str, str] = {}

    for chunk in chunks(syms, 150):
        in_list = ",".join("'%s'" % s for s in chunk)
        sql = ("SELECT symbol, market_cap, date FROM shibui.valuation "
               f"WHERE symbol IN ({in_list}) "
               "QUALIFY row_number() OVER (PARTITION BY symbol ORDER BY date DESC)=1")
        for row in query(sql):
            t = tickers.get(row["symbol"])
            if not t:
                continue
            max_dates[t] = row.get("date") or ""
            if row.get("market_cap") is not None:
                vendor_caps[t] = {"cap": row["market_cap"], "date": row.get("date")}

        sql = ("SELECT symbol, shares_float FROM shibui.ownership_stats "
               f"WHERE symbol IN ({in_list})")
        for row in query(sql):
            t = tickers.get(row["symbol"])
            if t and row.get("shares_float") is not None:
                floats[t] = row["shares_float"]

    out = {
        "as_of": {
            "vendor_valuation_max_date": max(sorted(max_dates.values())) if max_dates else None,
            "valuation_date_histogram": {},
        },
        "vendor_caps": vendor_caps,
        "floats": floats,
        "universe": {r["ticker"]: r["symbol"] for r in universe},
    }
    hist: dict[str, int] = {}
    for d in max_dates.values():
        hist[d] = hist.get(d, 0) + 1
    out["as_of"]["valuation_date_histogram"] = hist
    json.dump(out, open(out_path, "w"))
    print(f"universe={len(universe)} vendor_caps={len(vendor_caps)} floats={len(floats)} "
          f"dates={hist}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
