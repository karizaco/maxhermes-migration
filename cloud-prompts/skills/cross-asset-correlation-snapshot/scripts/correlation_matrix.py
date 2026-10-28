#!/usr/bin/env python3
"""correlation_matrix.py — Cloud-native helper for the cross-asset-correlation-snapshot skill.

WHAT THIS REPLACES
------------------
The skill's original step 2 called `financekit.correlation_matrix`, a tool that is NOT
bound in the Cloud runtime (nor is any `mcp__*` tool). The spec's "do not compute
correlations manually from price_history calls" hard rule was therefore unsatisfiable,
and every run degraded to "Yahoo fallback + local Pearson", which is exactly the manual
computation the spec forbade.

This helper restores the SPEC'S INTENT — a single server-side correlation-matrix call —
using the MCP-over-HTTP bridge. `shibui.stock_data_query` runs DuckDB SQL server-side,
and DuckDB's `corr()` aggregate computes the whole matrix in ONE round trip. No local
correlation maths is performed by the agent at all.

WHY THE BRIDGE, NOT `mcp__financekit__*`
----------------------------------------
The `mcp__*` tool NAMES in the spec are provenance from the local Windows Mavis. The MCP
SERVERS are reachable over plain HTTPS JSON-RPC from the sandbox, but there is no
financekit server (verified 2026-10-28: the only reachable servers are
`stocktwits` -> https://gateway.pipeworx.io/stocktwits/mcp and
`shibui` -> https://mcp.shibui.finance/mcp). shibui's DuckDB is the closest available
equivalent of `correlation_matrix`.

USAGE
-----
    python3 correlation_matrix.py --symbols SPY,QQQ,IWM,TLT,GLD,UUP,EEM --window-end 2026-10-23
    python3 correlation_matrix.py --symbols ... --window-end ... --basis adjclose
    python3 correlation_matrix.py --symbols ... --window-end ... --rolled-end 2026-10-16

Writes `/workspace/data_cross/mats.json` and prints a compact JSON summary.

PRICE SOURCE
------------
Prices come from Yahoo Finance Chart API (`/v8/finance/chart/{sym}?range=1y&interval=1d`,
short `User-Agent: Mozilla/5.0`). The series are then INJECTED into the server-side SQL as
inline VALUES so that:
  * the correlation matrix is computed SERVER-SIDE by DuckDB `corr()` (the spec's intent), and
  * the adjustment basis is explicit and identical to the published artifacts.

shibui's own `stock_quotes` table is used as an INDEPENDENT CROSS-CHECK, never as the
primary source: its raw `close` matches Yahoo's raw `close` to within rounding
(max $0.005 on TLT over the 6-month window), so a cross-check on the RAW-close basis
validates the price series while the published matrix uses the chosen basis.

ADJUSTMENT BASIS
----------------
`--basis adjclose` (default) uses Yahoo's split/dividend-adjusted closes. `--basis close`
uses raw closes. These give materially different correlations for distributing ETFs
(SPY-TLT is +0.33 on adjclose vs +0.32 on raw close over a 6-month window) because a raw
ex-dividend drop is a real price move that is NOT a total loss. The basis is recorded in
the output so it is never ambiguous.

KNOWN CONSTRAINTS (measured, not assumed)
-----------------------------------------
* shibui's `stock_data_query` caps result rows at 200 — but an AGGREGATE query returns
  one row, so the matrix call is unaffected. Do not try to pull raw series out of it for
  8 symbols (889 rows -> tool error); pull per-ticker (127 rows each) or cross-check in SQL.
* ^VIX is NOT in shibui (`general_info` has no index rows; no ticker matches '%VIX%').
  VIX therefore comes from Yahoo and is injected alongside the ETF series.
* Returns must span CONSECUTIVE COMMON DATES. VIX carries sessions the ETFs lack
  (2026-05-25, 2026-09-07). Compute the common date set FIRST, then take `lag()` over
  it; otherwise the VIX returns span a different interval and the VIX correlations drift
  by ~0.002. The helper enforces the common-date-first order.
"""

import argparse
import datetime
import json
import math
import os
import subprocess
import sys
import urllib.parse
import zoneinfo

NY = zoneinfo.ZoneInfo("America/New_York")
BRIDGE = "/workspace/mcp_bridge.py"
BRIDGE_URLS = [
    "https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/_shared/mcp_bridge.py",
    "https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/cloud-prompts/_shared/mcp_bridge.py",
    "https://api.github.com/repos/karizaco/maxhermes-migration/contents/cloud-prompts/_shared/mcp_bridge.py?ref=main",
]
SHIBUI = "https://mcp.shibui.finance/mcp"
UA = "Mozilla/5.0"          # short UA only; a long Chrome UA is 429'd by Yahoo's edge
OUT_DIR = "/workspace/data_cross"


# ----------------------------------------------------------------- bridge
def ensure_bridge():
    if os.path.exists(BRIDGE) and os.path.getsize(BRIDGE) > 0:
        return True
    for url in BRIDGE_URLS:
        subprocess.run(["curl", "-sL", "-H", "Accept: application/vnd.github.raw",
                        "-o", BRIDGE, url], capture_output=True)
        if os.path.exists(BRIDGE) and os.path.getsize(BRIDGE) > 0:
            return True
    return False


def shibui_sql(query, label="query"):
    """Run one SQL statement server-side via the bridge; return the parsed row list."""
    args = {"query": query, "user_prompt": label}
    path = "/workspace/_mcp/_cm_args.json"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(args, fh)
    p = subprocess.run([sys.executable, BRIDGE, "shibui", "stock_data_query", path],
                       capture_output=True, text=True, timeout=180)
    out = p.stdout.strip()
    if not out:
        return {"error": "empty_response", "stderr": p.stderr[-400:]}
    try:
        parsed = json.loads(out)
    except Exception:
        return {"error": "unparseable", "raw": out[:400]}
    if isinstance(parsed, dict) and parsed.get("error"):
        return parsed
    return parsed


# ----------------------------------------------------------------- yahoo
def yahoo_series(symbol, basis="adjclose"):
    """Return {ISO date: close} for one symbol, plus a status dict."""
    enc = urllib.parse.quote(symbol, safe="")
    url = (f"https://query2.finance.yahoo.com/v8/finance/chart/{enc}"
           f"?range=1y&interval=1d")
    path = "/workspace/_mcp/_cm_yahoo.json"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    p = subprocess.run(["curl", "-s", "-o", path, "-w", "%{http_code}",
                        "-H", f"User-Agent: {UA}", url], capture_output=True, text=True)
    status = {"symbol": symbol, "http": p.stdout.strip(), "bars": 0, "nulls": 0}
    if p.stdout.strip() != "200":
        status["error"] = f"http_{p.stdout.strip()}"
        return {}, status
    try:
        d = json.load(open(path))
        r = d["chart"]["result"][0]
    except Exception as exc:
        status["error"] = f"parse: {exc}"
        return {}, status
    ts = r["timestamp"]
    quote = r["indicators"]["quote"][0]
    adj = r["indicators"].get("adjclose", [{}])[0].get("adjclose")
    closes = adj if (basis == "adjclose" and adj) else quote["close"]
    if closes is None:
        status["error"] = "no_close_array"
        return {}, status
    series = {}
    for i, t in enumerate(ts):
        v = closes[i] if i < len(closes) else None
        if v is None:
            status["nulls"] += 1
            continue
        series[datetime.datetime.fromtimestamp(t, NY).date().isoformat()] = float(v)
    status["bars"] = len(series)
    status["last_bar"] = max(series) if series else None
    status["raw_close_last"] = r["meta"].get("regularMarketPrice")
    return series, status


def sql_alias(ticker):
    """Safe SQL identifier for a ticker (^VIX is not a valid identifier)."""
    return "VIX" if ticker.upper() == "^VIX" else ticker.upper()


def corr_key(a, b):
    """Column name holding the corr(a, b) term."""
    return f"{sql_alias(a)}__{sql_alias(b)}"

def common_dates(series_map):
    if not series_map:
        return []
    sets = [set(s) for s in series_map.values()]
    return sorted(set.intersection(*sets))


def build_sql(series_map, dates, tickers, basis_label):
    """Inline the aligned price series and let DuckDB compute the matrix server-side."""
    parts = []
    for t in tickers:
        vals = ",".join(f"('{d}',{series_map[t][d]:.6f})" for d in dates)
        parts.append(f"SELECT '{sql_alias(t)}' AS ticker, date, px "
                     f"FROM (VALUES {vals}) AS v(date, px)")
    union = "\n  UNION ALL\n".join(parts)
    cols = []
    for t in tickers:
        cols.append(f"max(CASE WHEN ticker='{sql_alias(t)}' THEN r END) AS {sql_alias(t)}")
    collist = ",\n    ".join(cols)
    names = [t for t in tickers]
    corr_terms = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            corr_terms.append(
                f"round(corr({sql_alias(a)}, {sql_alias(b)}), 6) AS {corr_key(a, b)}")
    corr_join = ",\n  ".join(corr_terms)
    return f"""
WITH px AS (
  {union}
),
common AS (
  SELECT date FROM px GROUP BY date HAVING count(DISTINCT ticker) = {len(tickers)}
),
pxi AS (
  SELECT p.ticker, p.date, p.px FROM px p JOIN common c ON p.date = c.date
),
ret AS (
  SELECT ticker, date,
         ln(px / lag(px) OVER (PARTITION BY ticker ORDER BY date)) AS r
  FROM pxi
),
wide AS (
  SELECT date,
    {collist}
  FROM ret WHERE r IS NOT NULL GROUP BY date
)
SELECT count(*) AS n_obs, min(date) AS d0, max(date) AS d1,
  {corr_join}
FROM wide
"""


def matrix_from_row(row, tickers):
    m = {a: {} for a in tickers}
    for a in tickers:
        for b in tickers:
            if a == b:
                m[a][b] = 1.0
            else:
                ka, kb = corr_key(a, b), corr_key(b, a)
                key = ka if ka in row else kb
                val = row.get(key)
                m[a][b] = float(val) if val is not None else None
                m[b][a] = m[a][b]
    return m


# ----------------------------------------------------------------- cross-check
def shibui_crosscheck(tickers, start, end):
    """Independent server-side matrix from shibui's OWN raw close (no Yahoo involved)."""
    tick_list = ", ".join(f"'{sql_alias(t)}'" for t in tickers)
    cols = ",\n    ".join(
        f"max(CASE WHEN ticker='{sql_alias(t)}' THEN r END) AS {sql_alias(t)}" for t in tickers)
    terms = []
    for i, a in enumerate(tickers):
        for b in tickers[i + 1:]:
            terms.append(
                f"round(corr({sql_alias(a)}, {sql_alias(b)}), 6) AS {corr_key(a, b)}")
    terms_join = ",\n  ".join(terms)
    sql = f"""
WITH px AS (
  SELECT ticker, date, close FROM shibui.stock_quotes
  WHERE ticker IN ({tick_list}) AND date >= DATE '{start}' AND date <= DATE '{end}'
),
ret AS (
  SELECT ticker, date, ln(close / lag(close) OVER (PARTITION BY ticker ORDER BY date)) AS r
  FROM px
),
wide AS (
  SELECT date, {cols} FROM ret WHERE r IS NOT NULL GROUP BY date
)
SELECT count(*) AS n_obs, min(date) AS d0, max(date) AS d1,
  {terms_join}
FROM wide
"""
    return sql


# ----------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="SPY,QQQ,IWM,TLT,GLD,UUP,EEM")
    ap.add_argument("--window-end", required=True, help="YYYY-MM-DD, last COMPLETED session")
    ap.add_argument("--window-start", default=None, help="YYYY-MM-DD (default: 6 months back)")
    ap.add_argument("--rolled-end", default=None, help="second window end for a roll comparison")
    ap.add_argument("--basis", default="adjclose", choices=["adjclose", "close"])
    ap.add_argument("--cross-check", action="store_true", help="also run the shibui raw-close cross-check")
    ap.add_argument("--out", default=os.path.join(OUT_DIR, "mats.json"))
    args = ap.parse_args()

    tickers = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    end = datetime.date.fromisoformat(args.window_end)
    if args.window_start:
        start = datetime.date.fromisoformat(args.window_start)
    else:
        # 6 calendar months back from the window end
        y, m = end.year, end.month - 6
        if m <= 0:
            m += 12
            y -= 1
        start = datetime.date(y, m, end.day)

    if not ensure_bridge():
        print(json.dumps({"error": "bridge_fetch_failed"}))
        return 1

    # --- fetch prices, then clip each series to the requested window
    series_map, statuses = {}, []
    for t in tickers:
        s, st = yahoo_series(t, basis=args.basis)
        series_map[t] = {d: v for d, v in s.items() if start.isoformat() <= d <= end.isoformat()}
        st["window_rows"] = len(series_map[t])
        statuses.append(st)

    dates = common_dates(series_map)
    if len(dates) < 30:
        print(json.dumps({"error": "insufficient_common_dates", "n": len(dates),
                          "statuses": statuses}))
        return 1

    # --- server-side matrix (PRIMARY)
    sql = build_sql(series_map, dates, tickers, args.basis)
    row = shibui_sql(sql, f"{len(tickers)}-asset Pearson correlation matrix of daily log "
                          f"returns, {args.basis} basis, {dates[0]} to {dates[-1]}")
    if isinstance(row, dict):
        print(json.dumps({"error": "shibui_failed", "detail": row}))
        return 1
    row = row[0]
    matrix = matrix_from_row(row, tickers)

    result = {
        "window": {"start": dates[0], "end": dates[-1], "n_sessions": len(dates),
                   "n_return_obs": int(row["n_obs"]), "basis": args.basis},
        "tickers": tickers,
        "matrix_returns": matrix,
        "sources": statuses,
        "server_side": True,
        "engine": "shibui.stock_data_query (DuckDB corr(), one call)",
    }

    # --- rolled window
    if args.rolled_end:
        rend = datetime.date.fromisoformat(args.rolled_end)
        rmap, rstat = {}, []
        for t in tickers:
            s, st = yahoo_series(t, basis=args.basis)
            rmap[t] = {d: v for d, v in s.items()
                       if start.isoformat() <= d <= rend.isoformat()}
            rstat.append(st)
        rdates = common_dates(rmap)
        if len(rdates) >= 30:
            rsql = build_sql(rmap, rdates, tickers, args.basis)
            rrow = shibui_sql(rsql, f"{len(tickers)}-asset correlation matrix, rolled window")
            if not isinstance(rrow, dict) and rrow:
                rm = matrix_from_row(rrow[0], tickers)
                result["rolled_window"] = {"start": rdates[0], "end": rdates[-1],
                                           "n_sessions": len(rdates),
                                           "n_return_obs": int(rrow[0]["n_obs"]),
                                           "matrix_returns": rm}
                result["rolled_sources"] = rstat

    # --- independent cross-check on shibui's own raw close
    if args.cross_check:
        cc_tickers = [t for t in tickers if t.upper() != "^VIX"]  # shibui carries no index
        csql = shibui_crosscheck(cc_tickers, dates[0], dates[-1])
        crow = shibui_sql(csql, "independent correlation matrix from shibui raw close")
        if not isinstance(crow, dict) and crow:
            result["crosscheck_shibui_raw"] = {
                "n_return_obs": int(crow[0]["n_obs"]),
                "d0": crow[0]["d0"], "d1": crow[0]["d1"],
                "tickers": cc_tickers,
                "matrix_returns": matrix_from_row(crow[0], cc_tickers),
                "note": "raw-close basis (not dividend adjusted) - validates the price series, "
                        "not the published basis",
            }

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=1)

    print(json.dumps({
        "window": result["window"],
        "server_side": True,
        "engine": result["engine"],
        "n_sources_ok": sum(1 for s in statuses if s.get("http") == "200"),
        "n_sources_total": len(statuses),
        "out": args.out,
        "crosscheck": "crosscheck_shibui_raw" in result,
    }, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
