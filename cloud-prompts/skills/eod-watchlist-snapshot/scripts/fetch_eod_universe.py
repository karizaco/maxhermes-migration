#!/usr/bin/env python3
"""Fetch the US EOD universe and the vendor's reference tables in ONE joined keyset sweep.

EOD_SETTLE_V1

WHY ONE JOINED SWEEP
--------------------
The bridge is metered (50 calls/day per egress without a key, 200 with one) and every call
costs one unit REGARDLESS of how many rows it returns. The old path queried three tables
separately per 150-symbol chunk (universe + valuation + ownership_stats), which cost
~2 calls per chunk = ~66 calls for a 4,900-symbol universe and blew the daily allowance.

One JOINED query per 200-symbol page returns the universe, the carrier caps, the floats, the
trailing P/E and the GICS sector in a single row per symbol, so the whole universe costs
~25 calls.

PAGINATION IS KEYSET, SEQUENTIAL, AND NEVER CONCURRENT
------------------------------------------------------
`LIMIT/OFFSET` needs a unique `ORDER BY` or pages overlap and rows go missing; concurrent
paging makes shibui throttle and return EMPTY bodies (an empty body is an outage, never
"no rows"). Keyset (`WHERE symbol > :last ORDER BY symbol LIMIT 200`) with concurrency 1 is
the safe form. The bridge caps every query at 200 rows.

OUTPUT
------
vendor_sweep.jsonl: one row per symbol:
  {symbol, ticker, name, exchange, currency, gics_sector, market_cap, cap_date,
   shares_float, trailing_pe}
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

MARKER = "EOD_SETTLE_V1"

BRIDGE = os.environ.get("MCP_BRIDGE", "/workspace/mcp_bridge.py")
ARGS_FILE = "/tmp/shibui_universe.json"

SQL = """SELECT gi.symbol, gi.ticker, gi.name, gi.exchange, gi.currency, gi.gics_sector,
 v.market_cap, v.date AS cap_date, o.shares_float, f.trailing_pe
FROM shibui.general_info gi
LEFT JOIN (SELECT symbol, market_cap, date FROM shibui.valuation
           QUALIFY row_number() OVER (PARTITION BY symbol ORDER BY date DESC)=1) v ON v.symbol=gi.symbol
LEFT JOIN (SELECT symbol, shares_float FROM shibui.ownership_stats) o ON o.symbol=gi.symbol
LEFT JOIN (SELECT symbol, trailing_pe, date FROM shibui.fundamentals_derived_daily
           QUALIFY row_number() OVER (PARTITION BY symbol ORDER BY date DESC)=1) f ON f.symbol=gi.symbol
WHERE gi.country_iso='US' AND gi.symbol > '{last}'
ORDER BY gi.symbol LIMIT 200"""


def query(sql: str, retries: int = 4) -> list[dict]:
    with open(ARGS_FILE, "w") as fh:
        json.dump({"query": sql, "user_prompt": "us eod universe sweep"}, fh)
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
        time.sleep(3 + 4 * attempt)
    raise RuntimeError(f"query failed: {last}\nSQL: {sql[:200]}")


def main() -> int:
    out_path = sys.argv[1]
    refs_path = sys.argv[2] if len(sys.argv) > 2 else ""
    last = ""
    pages = 0
    kept = 0
    seen: set[str] = set()
    dupes = 0
    t0 = time.time()
    with open(out_path, "w") as fh:
        while True:
            rows = query(SQL.format(last=last))
            if not rows:
                break
            pages += 1
            kept += len(rows)
            for r in rows:
                if r["symbol"] in seen:
                    dupes += 1
                seen.add(r["symbol"])
                fh.write(json.dumps(r, separators=(",", ":")) + "\n")
            newlast = rows[-1]["symbol"]
            if newlast == last:
                print("NO PROGRESS - aborting", file=sys.stderr)
                break
            last = newlast
            if pages % 5 == 0:
                print(f"  page={pages} rows={kept} uniq={len(seen)} last={last} "
                      f"{time.time()-t0:.0f}s", flush=True)
            if len(rows) < 200:
                break
    caps = 0
    floats = 0
    pe = 0
    sectors = 0
    with open(out_path) as fh:
        for line in fh:
            r = json.loads(line)
            caps += r.get("market_cap") is not None
            floats += r.get("shares_float") is not None
            pe += r.get("trailing_pe") is not None
            sectors += bool(r.get("gics_sector"))
    print(f"universe={kept} unique={len(seen)} dupes={dupes} pages={pages} "
          f"caps={caps} floats={floats} pe={pe} sectors={sectors} "
          f"elapsed={time.time()-t0:.0f}s")
    if dupes:
        print(f"FAIL: {dupes} duplicate symbols - the sweep lost its keyset guarantee",
              file=sys.stderr)
        return 1
    if refs_path:
        # the same data in the shape `build_eod_base.py` consumes: the rows plus the
        # vendor's own cap-carrier map (the rows that carry a non-null cap)
        rows = []
        vcaps = {}
        floats_map = {}
        for line in open(out_path):
            r = json.loads(line)
            rows.append(r)
            if r.get("market_cap") is not None:
                vcaps[r["ticker"]] = {"cap": r["market_cap"], "date": r.get("cap_date")}
            if r.get("shares_float") is not None:
                floats_map[r["ticker"]] = r["shares_float"]
        json.dump({"rows": rows, "vendor_caps": vcaps, "floats": floats_map,
                   "as_of": {"vendor_valuation_max_date":
                             max([r.get("cap_date") for r in rows if r.get("cap_date")],
                                 default=None)}},
                  open(refs_path, "w"))
        print(f"wrote {refs_path} ({len(rows)} rows, {len(vcaps)} carrier caps)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
