#!/usr/bin/env python3
"""
shibui_caps.py — the market-cap cross-check for cron #26, without the SQL footguns.

WHY THIS FILE EXISTS
--------------------
The 2026-11-12 run built its shibui cap query by hand in the shell and got it wrong
TWICE in a row. Both mistakes cost a METERED bridge call — the allowance is 50 calls
per day per egress IP and it is SHARED ACROSS THE WHOLE FLEET, so two wasted calls
are 4% of the fleet's day:

  1. a `sed`-built IN-list produced `'K''Y''T''X'` — the query matched nothing and
     returned an empty set with NO error, which reads exactly like "shibui has no
     data for these names";
  2. dropping the `QUALIFY` window returned 11,370 rows against the tool's 200-row
     cap — a hard error.

So the query lives here, the ticker list is built in Python (never in the shell), and
the window function and the LIMIT are baked in.

USAGE
    python3 shibui_caps.py --tickers "NVDA,NBIS,CRWV" --date 2026-11-11 --out caps.json
    python3 shibui_caps.py --file tickers.txt --date 2026-11-11
    python3 shibui_caps.py --tickers "A,B,C" --date 2026-11-11 --json-only

OUTPUT
    A JSON list on stdout and in --out:
    [{"ticker": "NVDA", "date": "2026-11-11", "market_cap": 4204265999999.99}, ...]
    plus a "_meta" key carrying the call count and any per-chunk error.

EXIT CODES
    0 = at least one row came back
    2 = the bridge is missing, or every call failed — the caller records it in
        `## Source health` and moves on. A missing cap is never a missing name.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile

SHIBUI_CAPS_V1 = "shibui-caps-v1"
CHUNK = 150                      # the tool's hard cap is 200 rows; one row per ticker
QUERY = ("SELECT ticker, date, market_cap FROM shibui.valuation "
         "WHERE ticker IN ({tickers}) AND date <= '{date}' "
         "QUALIFY row_number() OVER (PARTITION BY ticker ORDER BY date DESC) = 1 "
         "ORDER BY ticker LIMIT {limit}")


def default_bridge():
    for p in ("/workspace/mcp_bridge.py",
              os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp_bridge.py")):
        if os.path.exists(p):
            return p
    return None


def call_bridge(bridge, query, user_prompt, timeout=120):
    """One shibui call. Returns a list of row dicts (empty on failure)."""
    with tempfile.TemporaryDirectory() as td:
        qf = os.path.join(td, "q.txt")
        af = os.path.join(td, "a.json")
        with open(qf, "w") as fh:
            fh.write(query)
        with open(af, "w") as fh:
            json.dump({"query": query, "user_prompt": user_prompt}, fh)
        try:
            r = subprocess.run([sys.executable, bridge, "shibui", "stock_data_query", af],
                               capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return [], "timeout"
        if r.returncode != 0:
            return [], (r.stderr or r.stdout or "exit %d" % r.returncode)[:300]
        try:
            d = json.loads(r.stdout)
        except Exception:
            return [], "unparseable response"
        if isinstance(d, dict) and d.get("error"):
            return [], str(d.get("detail") or d.get("error"))[:300]
        if not isinstance(d, list):
            return [], "unexpected shape: %s" % type(d).__name__
        return d, ""


def main():
    ap = argparse.ArgumentParser(description="shibui valuation caps, safely")
    ap.add_argument("--tickers", default="", help="comma-separated tickers")
    ap.add_argument("--file", default=None, help="file with one ticker per line")
    ap.add_argument("--date", required=True, help="as-of date (YYYY-MM-DD); the latest "
                                                  "row on or before it is taken")
    ap.add_argument("--out", default=None, help="write the JSON here")
    ap.add_argument("--bridge", default=None, help="path to mcp_bridge.py")
    ap.add_argument("--json-only", action="store_true",
                    help="stdout carries only the JSON (no banner)")
    args = ap.parse_args()

    tickers = []
    if args.file:
        with open(args.file) as fh:
            for ln in fh:
                t = ln.strip().split(",")[0].strip().upper()
                if t:
                    tickers.append(t)
    for t in (args.tickers or "").split(","):
        t = t.strip().upper()
        if t:
            tickers.append(t)
    # de-duplicate, keep order
    seen, uniq = set(), []
    for t in tickers:
        if t not in seen:
            seen.add(t)
            uniq.append(t)

    bridge = args.bridge or default_bridge()
    if not bridge or not os.path.exists(bridge):
        print("shibui_caps: BRIDGE UNAVAILABLE (%s) - no cap cross-check is possible; "
              "record `shibui unavailable` in Source health" % (bridge or "not found"),
              file=sys.stderr)
        return 2
    if not uniq:
        print(json.dumps({"rows": [], "_meta": {"marker": SHIBUI_CAPS_V1, "calls": 0,
                                                "tickers": 0, "error": "no tickers given"}}))
        return 0

    rows, errors, calls = [], [], 0
    for i in range(0, len(uniq), CHUNK):
        chunk = uniq[i:i + CHUNK]
        inl = ",".join("'%s'" % t for t in chunk)
        q = QUERY.format(tickers=inl, date=args.date, limit=len(chunk) + 10)
        data, err = call_bridge(bridge, q,
                                "latest valuation market cap per ticker on or before %s"
                                % args.date)
        calls += 1
        if err:
            errors.append("chunk %d: %s" % (i // CHUNK, err))
            continue
        for r in data:
            if not isinstance(r, dict):
                continue
            t = (r.get("ticker") or "").strip().upper()
            if not t:
                continue
            try:
                mc = float(r.get("market_cap"))
            except (TypeError, ValueError):
                continue
            rows.append({"ticker": t, "date": r.get("date"), "market_cap": mc})

    out = {"rows": rows,
           "_meta": {"marker": SHIBUI_CAPS_V1, "calls": calls, "tickers": len(uniq),
                     "returned": len(rows), "as_of": args.date, "errors": errors}}
    text = json.dumps(out, indent=1)
    if args.out:
        with open(args.out, "w") as fh:
            fh.write(text)
    if not args.json_only:
        print("shibui_caps: %d call(s), %d/%d tickers returned%s"
              % (calls, len(rows), len(uniq),
                 (", errors: " + "; ".join(errors)) if errors else ""), file=sys.stderr)
    print(text)
    return 0 if rows else 2


if __name__ == "__main__":
    sys.exit(main())
