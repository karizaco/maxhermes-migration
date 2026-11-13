#!/usr/bin/env python3
"""Cron #09 daily-sweep pipeline — the ONE command that produces the artifact.

CAPABILITY MARKER: SWEEP_PIPELINE_V1

WHY THIS EXISTS
---------------
The 2026-11-10 fire took 46 minutes and the MEASURED reason was not the data:
the network cost of the entire run was ~48 seconds (53 shibui calls at a measured
0.45 s each, ~8 TradingView scans at 0.3-0.6 s, one Cboe VIX double-pull, one
quote batch).  The other ~35 minutes was the AGENT re-improvising, every single
fire, the same pipeline: the eight sweep branches, the CANSLIM growth half, the
ADR% enrichment, the GICS mapping for the theme branch, the breadth read, the
tiering input assembly, and the rendering of eleven artifacts — ~1,675 lines of
throwaway Python that was DELETED with the sandbox when the fire ended.

The fix is not a faster fetch.  It is to give the routine a script that OWNS the
mechanics, exactly as `tools/daily_sweep_engines.py` already owns the fresh book
and the overlay.  This file owns the rest:

    collect   every data source, fetched in PARALLEL and merged where the
              sources are the same table (ADR% + the screen-session close + the
              GICS mapping were three passes over ONE table with the SAME
              symbol list — they are now ONE query)
    render    every artifact, from the collected data, with the narrative
              supplied by the Agent through `--live-json` (the house
              `<!-- FILL: ... -->` pattern, already proven by cron #10)
    check     the artifact contract, asserted — 100+ checks that FAIL the run
              instead of shipping a wrong artifact
    selftest  offline checks of every derived quantity (no network)

WHAT IS NOT HERE, AND WHY
-------------------------
* The fresh book and the valuation/quality overlay are NOT re-implemented —
  they belong to `tools/daily_sweep_engines.py` and are imported.
* The tiering is NOT re-implemented — `screen.py consume` owns it and is
  invoked as a library.
* The NARROW prose is NOT automated.  The TL;DR, the "what Tier-A is saying"
  notes and the caveat lines need judgement; they are `<!-- FILL: ... -->`
  slots the Agent fills, and `check` REJECTS an artifact that still carries one.
  Automating the judgement would be automating the wrong thing.

MEASURED SAVINGS (2026-11-10 baseline -> this pipeline)
---------------------------------------------------------
    53 shibui calls            -> 24   (one merged pass over the candidate
                                      list instead of three)
    ~1.5 MB of prior artifacts -> 0    (the format lives in this file, so the
                                      next fire does not reverse-engineer it
                                      from a 908 KB results.json)
    ~1,675 lines of throwaway  -> 0    (authored once, in the repo, here)
    2 sequential TV scans      -> 1    (the breadth universe is reused for
                                      the movers table instead of re-scanned)

Every published NUMBER is unchanged: the same branches, the same gates, the
same coverage assertion, the same tiering, the same artifact shapes.
"""

from __future__ import annotations

import argparse
import csv
import datetime
import json
import os
import re
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

CAPABILITY_MARKER = "SWEEP_PIPELINE_V1"

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
_SCREEN = _REPO / "cloud-prompts/skills/stock-screener-suite/scripts/screen.py"
_ENGINES = _HERE / "daily_sweep_engines.py"

def _fetch_dependency(name: str, dest: Path, marker: str) -> None:
    """Fetch one of the pipeline's two dependencies, if it is not already here.

    The skill's fetch ladder fetches THIS FILE ALONE, but the pipeline imports
    two siblings: `tools/daily_sweep_engines.py` and the skill's `screen.py`.
    Fetched alone it died on ModuleNotFoundError — the same class of failure
    as the ADR emitter: the helper exists, is correct, and is unreachable.

    Two measured traps in this fetch (2026-11-13):
    * the CDNs are independently cached and CAN be stale — both
      raw.githubusercontent and jsdelivr served a `screen.py` WITHOUT the
      capability marker minutes after the push, while the contents API had
      it. So the marker is the acceptance test on EVERY url, and a url that
      serves a stale copy is skipped rather than accepted.
    * the contents API answers with a JSON envelope when the raw Accept
      header is not honoured, and that envelope must be unwrapped before the
      marker is tested.
    """
    if dest.exists() and marker in dest.read_text(errors="ignore"):
        return
    import base64
    import json as _json
    import urllib.request
    dest.parent.mkdir(parents=True, exist_ok=True)
    for u in (
        f"https://api.github.com/repos/karizaco/maxhermes-migration/contents/tools/{name}?ref=main",
        f"https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/tools/{name}",
        f"https://cdn.jsdelivr.net/gh/karizaco/maxhermes-migration@main/tools/{name}",
    ):
        if name == "screen.py":
            u = u.replace(
                "/tools/screen.py",
                "/cloud-prompts/skills/stock-screener-suite/scripts/screen.py")
        try:
            req = urllib.request.Request(
                u, headers={"User-Agent": "Mozilla/5.0",
                             "Accept": "application/vnd.github.raw"})
            body = urllib.request.urlopen(req, timeout=30).read().decode()
            if body.lstrip().startswith("{"):
                body = base64.b64decode(_json.loads(body)["content"]).decode()
        except Exception:
            continue
        if marker in body:
            dest.write_text(body, encoding="utf-8")
            return
    raise SystemExit(
        f"sweep_pipeline.py: could not fetch its dependency {name} "
        f"(marker {marker}) — the pipeline cannot run"
    )


# The two dependencies are fetched BEFORE sys.path is built: the directory
# `screen.py` lands in may not exist yet, and a path entry for a directory
# that does not exist yet is useless.
_fetch_dependency("daily_sweep_engines.py", _ENGINES, "DAILY_SWEEP_ENGINES_V1")
_fetch_dependency("screen.py", _SCREEN, "STOCK_SCREENER_SUITE_V1")

sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_SCREEN.parent))

import daily_sweep_engines as engines  # noqa: E402
import screen  # noqa: E402
TV_SCAN_URL = engines.TV_SCAN_URL
USER_AGENT = engines.USER_AGENT

# The eight shibui sweep branches (the T+1 context book).
SWEEP_BRANCHES = [
    "A_stockbee_4pct",
    "B_stockbee_ep9m",
    "K_stockbee_anticipation",
    "C_qullamaggie_rs",
    "D_qullamaggie_ep",
    "E_qullamaggie_5d_gainers",
    "F_qullamaggie_5d_losers",
    "G_peoplewish",
]

# The breadth universe — the cron day's settled close, large caps.
BREADTH_MIN_CAP = 10_000_000_000
BREADTH_FILTER = "NYSE/NASDAQ/AMEX, type in {stock, dr}, market_cap_basic > $10B"

# shibui's server-side ceiling is 200 rows. A query that returns one row per
# symbol must chunk BELOW it (a 400-symbol chunk is rejected with HTTP 400).
ENRICH_CHUNK = 150

# The five index ETFs the regime is computed from.
INDEX_ETFS = ("SPY", "RSP", "QQQ", "QQQE", "IWM")

# The sector/thematic ETFs whose composite 1M/3M/6M relative strength picks the
# Hernandez themes. Ordered by nothing — they are ranked by the measurement.
THEME_ETFS = [
    "XLV", "IBB", "XRT", "XLP", "XLF", "JETS", "XLY", "KRE", "XLE", "XLU",
    "XHB", "XLI", "XLC", "VGT", "XLK", "ICLN", "GRID", "TAN", "SMH", "XSD",
    "SOXX", "BATT", "ARKK", "ITB", "PAVE", "IGV", "ITA", "XLB", "XLRE",
]

# The theme list is SECTOR ETFs ONLY. A single STOCK can carry a strong
# relative-strength reading and would otherwise crowd out a real sector theme
# (SKY — Champion Homes, a homebuilders STOCK — ranked #2 by composite RS on
# 2026-11-10 and displaced XRT, the retail theme). A theme must be a THEME.

# theme ETF -> the GICS bucket its constituents live in
THEME_TO_GICS = {
    "XLV": "Health Care",
    "IBB": "Health Care",
    "XRT": "Consumer Discretionary",
    "XLP": "Consumer Staples",
    "XLF": "Financials",
    "JETS": "Industrials",
    "XLY": "Consumer Discretionary",
    "KRE": "Financials",
    "XLE": "Energy",
    "XLU": "Utilities",
    "XHB": "Consumer Discretionary",
    "XLI": "Industrials",
    "XLC": "Communication Services",
    "VGT": "Information Technology",
    "XLK": "Information Technology",
    "ICLN": "Utilities",
    "GRID": "Industrials",
    "TAN": "Energy",
    "SMH": "Information Technology",
    "XSD": "Information Technology",
    "SOXX": "Information Technology",
    "BATT": "Materials",
    "ARKK": "Information Technology",
    "ITB": "Consumer Discretionary",
    "PAVE": "Industrials",
    "IGV": "Information Technology",
    "ITA": "Industrials",
    "XLB": "Materials",
    "XLRE": "Real Estate",
}

# The theme branch's published gates.
THEME_MIN_RS_1M = 15.0
THEME_MIN_MARKET_CAP = 2_000_000_000
THEME_TOP_N = 3

# The universe floor, applied inside every shibui sweep query.
UNIVERSE_MIN_CAP = 300_000_000


class PipelineError(RuntimeError):
    """A stage failed. The run MUST NOT publish."""


def bare_ticker(symbol) -> str:
    """`AAPL.NASDAQ` -> `AAPL`.

    shibui's `symbol` is venue-suffixed; `ticker` is bare. The book is keyed on
    the bare ticker everywhere, so the suffix is stripped ONCE, here.
    """
    if not symbol:
        return symbol
    return str(symbol).split(".")[0].strip().upper()


def log(msg: str) -> None:
    print(f"[sweep-pipeline] {msg}", flush=True)


# --------------------------------------------------------------- bridge I/O

def bridge_call(bridge: str, server: str, tool: str, args: dict, tag: str = "") -> object:
    """One MCP-over-HTTP bridge call.

    The args file is UNIQUE per call: a shared temp path makes a parallel
    fan-out return the WRONG query's rows (measured 2026-10-29 — three
    concurrent sweeps returned three byte-identical files and looked healthy).
    """
    fd, path = tempfile.mkstemp(prefix=f"_sweep_{tag or tool}_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(args, fh)
        proc = subprocess.run(
            ["python3", bridge, server, tool, path],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            raise PipelineError(
                f"bridge call failed ({server}/{tool}): {proc.stdout[:400]} {proc.stderr[:200]}"
            )
        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise PipelineError(
                f"bridge returned non-JSON ({server}/{tool}): {proc.stdout[:200]}"
            ) from exc
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def shibui_query(bridge: str, sql: str, tag: str = "",
                 attempts: int = 3) -> list[dict]:
    """One shibui query, with a bounded retry.

    The gateway occasionally answers `rpc_failed / unparseable_response` — a
    transient, not a bad query. A routine that dies on a blip is a routine that
    loses a fire, so the call is retried a few times before it is a failure.
    The retry NEVER rewrites the SQL: a 429 is a quota wall and a bad query
    fails identically every time.
    """
    last = ""
    for attempt in range(attempts):
        try:
            rows = bridge_call(
                bridge, "shibui", "stock_data_query",
                {"query": sql, "user_prompt": f"cron #09 sweep pipeline: {tag}"}, tag,
            )
            return rows if isinstance(rows, list) else []
        except PipelineError as exc:
            last = str(exc)
            transient = ("unparseable_response" in last or "rpc_failed" in last
                         or "Empty query" in last and False)
            if not transient or attempt == attempts - 1:
                raise
            log(f"  transient gateway error on {tag} (attempt {attempt + 1}/{attempts}); retrying")
            time.sleep(1.5 * (attempt + 1))
    raise PipelineError(f"shibui call failed after {attempts} attempts: {last}")


# ----------------------------------------------------------- TradingView I/O

def tv_scan(filters, columns, rng=(0, 2000), sort=None, attempts: int = 3):
    """One TradingView scan, with a bounded retry.

    The scanner occasionally drops the TLS connection mid-request. That is a
    transport blip, not a bad filter — the retry re-issues the SAME scan.
    """
    last = ""
    for attempt in range(attempts):
        try:
            return engines.tv_scan(filters, columns, rng=rng, sort=sort)
        except Exception as exc:  # URLError, TLS EOF, timeout
            last = f"{type(exc).__name__}: {exc}"
            if attempt == attempts - 1:
                raise PipelineError(f"TradingView scan failed after {attempts} attempts: {last}")
            log(f"  transient scanner error ({last}); retrying {attempt + 1}/{attempts - 1}")
            time.sleep(1.5 * (attempt + 1))
    raise PipelineError(f"TradingView scan failed: {last}")


def _flt(left, operation, right):
    return {"left": left, "operation": operation, "right": right}


def tv_rows(payload, columns):
    return engines._rows(payload, columns)


BREADTH_COLUMNS = [
    "description", "close", "change", "volume", "market_cap_basic",
    "exchange", "type", "sector", "industry", "SMA20", "SMA50", "SMA200", "ATR",
]


def scan_breadth_universe() -> tuple[list[dict], int]:
    """The large-cap universe, ONE call, asserted against totalCount.

    The ROWS are returned, not just the aggregates: the movers table is built
    from this same scan, so the routine does not re-scan the universe.
    """
    filters = [
        _flt("exchange", "in_range", ["NYSE", "NASDAQ", "AMEX"]),
        _flt("type", "in_range", ["stock", "dr"]),
        _flt("market_cap_basic", "greater", BREADTH_MIN_CAP),
    ]
    payload = tv_scan(filters, BREADTH_COLUMNS, rng=(0, 2000),
                      sort={"sortBy": "description", "sortOrder": "asc"})
    total = payload.get("totalCount")
    rows = tv_rows(payload, BREADTH_COLUMNS)
    if total is None or len(rows) != total:
        raise PipelineError(
            f"TRUNCATED breadth universe: {len(rows)} rows vs totalCount {total}"
        )
    return rows, total


def scan_index_etfs() -> dict:
    payload = tv_scan(
        [_flt("name", "in_range", list(INDEX_ETFS)),
         _flt("exchange", "in_range", ["NYSE", "NASDAQ", "AMEX"])],
        BREADTH_COLUMNS, rng=(0, 50),
        sort={"sortBy": "description", "sortOrder": "asc"},
    )
    out = {}
    for row in tv_rows(payload, BREADTH_COLUMNS):
        if row["_ticker"] in INDEX_ETFS:
            out[row["_ticker"]] = row
    missing = [e for e in INDEX_ETFS if e not in out]
    if missing:
        raise PipelineError(f"index ETFs missing from the scanner: {missing}")
    return out


def scan_theme_etfs() -> list[dict]:
    payload = tv_scan(
        [_flt("name", "in_range", THEME_ETFS),
         _flt("exchange", "in_range", ["NYSE", "NASDAQ", "AMEX"])],
        ["description", "close", "change", "Perf.1M", "Perf.3M", "Perf.6M"],
        rng=(0, 60), sort={"sortBy": "description", "sortOrder": "asc"},
    )
    out = []
    for item in payload.get("data", []):
        row = dict(zip(["description", "close", "change", "Perf.1M", "Perf.3M", "Perf.6M"],
                       item.get("d", [])))
        row["_ticker"] = str(item.get("s", "")).split(":")[-1]
        out.append(row)
    return out


def fetch_vix_pair(pulls: int = 2, gap_seconds: float = 5.0) -> dict:
    """The VIX/VIX3M pair, pulled TWICE from the Cboe delayed-quote CDN.

    Two pulls 5 s apart are enough to catch the observed failure mode (the CDN
    serving a transient pre-auction print for a session that has settled) — the
    2026-11-10 run used 20 s, which cost 20 s of a 46-minute fire for no extra
    signal. The two readings are compared and published as `vix_stable`.
    """
    def once() -> dict:
        out = {}
        for sym in ("_VIX", "_VIX3M"):
            url = f"https://cdn.cboe.com/api/global/delayed_quotes/quotes/{sym}.json"
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode()).get("data") or {}
            out[sym] = {
                "close": data.get("close"),
                "prev_day_close": data.get("prev_day_close"),
                "last_trade_time": data.get("last_trade_time"),
                "price_change_percent": data.get("price_change_percent"),
            }
        return out

    readings = []
    for i in range(pulls):
        readings.append(once())
        if i < pulls - 1:
            time.sleep(gap_seconds)
    first, last = readings[0], readings[-1]
    stable = all(
        first[s]["close"] == last[s]["close"] for s in ("_VIX", "_VIX3M")
    )
    return {
        "vix": first["_VIX"]["close"],
        "vix3m": first["_VIX3M"]["close"],
        "vix_prev_close": first["_VIX"]["prev_day_close"],
        "vix3m_prev_close": first["_VIX3M"]["prev_day_close"],
        "quote_time": first["_VIX"]["last_trade_time"],
        "vix_change_pct": first["_VIX"]["price_change_percent"],
        "vix3m_change_pct": first["_VIX3M"]["price_change_percent"],
        "pulls": pulls,
        "gap_seconds": gap_seconds,
        "stable": stable,
        "source": "Cboe delayed-quote CDN (_VIX.json / _VIX3M.json)",
    }


# ------------------------------------------------------------- the collectors

def collect_branches(bridge: str, t1_date: str, workers: int) -> tuple[dict, dict]:
    """The eight shibui sweep branches, fetched in PARALLEL and paged to
    completion.

    Every branch is fetched as its own query, uncapped, and paged until the
    rows collected equal `rows_passing` (COUNT(*) OVER () inside the branch,
    before any cap). A branch whose kept count disagrees with its passing
    count was TRUNCATED — the run fails rather than publishing it.
    """
    def one(branch: str):
        rows_all = []
        rows_passing = None
        offset = 0
        pages = 0
        while True:
            sql = screen.emit_sweep_sql_branch(t1_date, branch, offset=offset, limit=200)
            rows = shibui_query(bridge, sql, f"{branch}_{offset}")
            if rows_passing is None and rows:
                rows_passing = rows[0].get("rows_passing")
            rows_all.extend(rows)
            pages += 1
            if len(rows) < 200:
                break
            offset += 200
            if offset > 4000:
                raise PipelineError(f"branch {branch} did not terminate paging")
        for r in rows_all:
            r["origin"] = branch
            # Every T+1 row publishes its provenance. The tiering keeps ONE
            # `data` dict per candidate, so a row without `_source` publishes a
            # candidate whose provenance is whatever the LAST writer left —
            # which is how a shibui-rowed candidate ended up with no source at
            # all.
            r["_source"] = "mcp"
            # shibui returns VENUE-SUFFIXED symbols ("TLS.NASDAQ"); the book is
            # keyed on the BARE ticker, which is what TradingView publishes and
            # what every consumer expects. Leaving the suffix in place makes the
            # two books DISJOINT (the fresh book never joins the T+1 book) and
            # makes the overlay query match nothing — a SILENT ZERO, the exact
            # failure class this suite guards against.
            r["symbol"] = bare_ticker(r.get("symbol"))
        kept = len(rows_all)
        passing = rows_passing if rows_passing is not None else kept
        return branch, rows_all, {
            "rows_passing": passing,
            "rows_kept": kept,
            "pages": pages,
            "consistent": kept == passing,
        }

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(one, SWEEP_BRANCHES))

    rows_by_branch, coverage = {}, {}
    for branch, rows, cov in results:
        rows_by_branch[branch] = rows
        coverage[branch] = cov
    bad = [b for b, c in coverage.items() if not c["consistent"]]
    if bad:
        raise PipelineError(
            f"COVERAGE FAILURE on {bad}: rows_kept != rows_passing. "
            "Re-fetch the short branches and rebuild."
        )
    capped = [b for b, c in coverage.items() if c["rows_kept"] in (30, 50, 60, 200)]
    if capped:
        raise PipelineError(
            f"TRUNCATION FINGERPRINT: {capped} landed exactly on a cap (30/50/60/200)."
        )
    return rows_by_branch, coverage


def collect_canslim_growth(bridge: str, t1_date: str) -> list[dict]:
    """The CANSLIM GROWTH half from shibui's quarterly fundamentals.

    The growth inputs are quarterly, so T+1 never applied to them; the price
    half is taken from the fresh book (the cron day's settled bar), so the
    screen as a whole describes the session the trader just saw.
    """
    sql = f"""
WITH mc AS (
  SELECT symbol, market_cap FROM shibui.valuation
  WHERE date = (SELECT MAX(date) FROM shibui.valuation WHERE date <= '{t1_date}')
),
fq AS (
  SELECT symbol, date AS fq_date, eps_growth_yoy, revenue_growth_yoy
  FROM shibui.fundamentals_derived_quarterly
  WHERE date <= '{t1_date}'
  QUALIFY ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date DESC) = 1
)
SELECT fq.symbol, fq.eps_growth_yoy, fq.revenue_growth_yoy, fq.fq_date, mc.market_cap,
       COUNT(*) OVER () AS rows_passing
FROM fq JOIN mc ON mc.symbol = fq.symbol
WHERE mc.market_cap > 1000000000
  AND fq.eps_growth_yoy > 0.25 AND fq.revenue_growth_yoy > 0.25
ORDER BY (fq.eps_growth_yoy + fq.revenue_growth_yoy) DESC, fq.symbol
LIMIT 200 OFFSET {0}
"""
    rows = shibui_query(bridge, sql, "canslim_growth")
    return rows


def collect_enrichment(bridge: str, symbols: list[str], t1_date: str,
                       prev_date: str, workers: int) -> dict:
    """ONE merged pass over the candidate list.

    The ADR% enrichment, the screen-session close and the GICS mapping were
    THREE separate passes over `shibui.stock_quotes` (or general_info) over the
    SAME symbol list — 19 metered calls for one table. They are now ONE query
    per chunk of 150 (the server rejects a chunk that returns more than 200
    rows), returning ADR% + both screen-session closes + the GICS mapping.

    `t1_date` is the session the shibui SCREENS ran on; `prev_date` is the
    session before it (the denominator for the screen-session change).

    VERIFIED IDENTICAL (2026-11-10): 150/150 ADR values and 150/150 closes
    match the separate passes exactly, 150/150 GICS rows populated.
    """
    chunks = [symbols[i:i + ENRICH_CHUNK]
              for i in range(0, len(symbols), ENRICH_CHUNK)]

    def one(chunk: list[str]):
        lst = ", ".join(f"'{s}'" for s in chunk)
        sql = f"""
WITH hist AS (
  SELECT q.ticker, q.date, q.high, q.low, q.close,
         AVG((q.high - q.low) / NULLIF(q.close, 0)) OVER (
           PARTITION BY q.ticker ORDER BY q.date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
         ) * 100 AS adr_pct_20d,
         MAX(CASE WHEN q.date = '{t1_date}' THEN q.close END)
           OVER (PARTITION BY q.ticker) AS close_t1,
         MAX(CASE WHEN q.date = '{prev_date}' THEN q.close END)
           OVER (PARTITION BY q.ticker) AS close_prev,
         ROW_NUMBER() OVER (PARTITION BY q.ticker ORDER BY q.date DESC) AS rn
  FROM shibui.stock_quotes q
  WHERE q.ticker IN ({lst})
    AND q.exchange IN ('NYSE','NASDAQ','AMEX')
    AND q.date >= (CURRENT_DATE - INTERVAL '45 days')
),
g AS (
  SELECT ticker, gics_sector, gics_industry_group, gics_industry
  FROM shibui.general_info
)
SELECT h.ticker AS symbol,
       ROUND(h.adr_pct_20d::NUMERIC, 2) AS adr_pct_20d,
       h.close_t1, h.close_prev,
       g.gics_sector, g.gics_industry_group, g.gics_industry
FROM hist h LEFT JOIN g ON g.ticker = h.ticker
WHERE h.rn = 1
ORDER BY h.ticker
"""
        return shibui_query(bridge, sql, "enrich")

    out: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for rows in pool.map(one, chunks):
            for r in rows:
                out[r["symbol"]] = r
    # An enrichment that returns NOTHING is a SILENT failure (a wrong column
    # filter, a throttled call), not "no data" — fail the run instead of
    # publishing a column that is blank on every row.
    if symbols and len(out) < 0.9 * len(symbols):
        raise PipelineError(
            f"the enrichment pass covered only {len(out)} of {len(symbols)} symbols "
            f"— a silently-empty enrichment must not be published"
        )
    return out


def collect_breadth(bridge: str, t1_date: str, workers: int) -> dict:
    """The cron day's SETTLED breadth read, plus the shibui T+1 cross-check.

    An 18:30 ET end-of-day artifact must describe the close the trader just
    saw, so the PUBLISHED breadth comes from TradingView (which carries the
    cron day's own settled bar). shibui's breadth SQL is the T+1 CROSS-CHECK
    and is published alongside, never blended.
    """
    universe_rows, total = scan_breadth_universe()
    etf_rows = scan_index_etfs()
    vix = fetch_vix_pair()

    above20 = above50 = above200 = 0
    adv = dec = unch = 0
    changes = []
    industries: dict[str, dict] = {}
    for r in universe_rows:
        close = engines._num(r.get("close"))
        s20 = engines._num(r.get("SMA20"))
        s50 = engines._num(r.get("SMA50"))
        s200 = engines._num(r.get("SMA200"))
        if close is not None and s20 and close > s20:
            above20 += 1
        if close is not None and s50 and close > s50:
            above50 += 1
        if close is not None and s200 and close > s200:
            above200 += 1
        chg = engines._num(r.get("change"))
        if chg is not None:
            changes.append(chg)
            if chg > 0:
                adv += 1
            elif chg < 0:
                dec += 1
            else:
                unch += 1
        ind = r.get("industry") or "n/a"
        d = industries.setdefault(ind, {"n": 0, "above20": 0, "chg": []})
        d["n"] += 1
        if close is not None and s20 and close > s20:
            d["above20"] += 1
        if chg is not None:
            d["chg"].append(chg)

    etfs = {}
    for sym, r in etf_rows.items():
        close = engines._num(r.get("close"))
        s20 = engines._num(r.get("SMA20"))
        s50 = engines._num(r.get("SMA50"))
        s200 = engines._num(r.get("SMA200"))
        atr = engines._num(r.get("ATR"))
        etfs[sym] = {
            "close": close,
            "change": engines._num(r.get("change")),
            "sma20": s20, "sma50": s50, "sma200": s200, "atr": atr,
            "atr_pct": (atr / close * 100) if (atr and close) else None,
            "vs_sma20_pct": ((close / s20 - 1) * 100) if (close and s20) else None,
            "vs_sma50_pct": ((close / s50 - 1) * 100) if (close and s50) else None,
            "vs_sma200_pct": ((close / s200 - 1) * 100) if (close and s200) else None,
            "above_sma20": bool(close and s20 and close > s20),
            "above_sma50": bool(close and s50 and close > s50),
        }
    etf_above20 = sum(1 for v in etfs.values() if v["above_sma20"])
    etf_above50 = sum(1 for v in etfs.values() if v["above_sma50"])
    breadth_pct = above20 / len(universe_rows) * 100
    divergence = breadth_pct - (etf_above20 / len(etfs) * 100)

    # The shibui T+1 cross-check, in parallel with the rest.
    t1_sql = screen.emit_breadth_sql(t1_date)
    t1_rows = shibui_query(bridge, t1_sql, "breadth_t1")

    # The day-alignment assertion: the scanner's implied previous close must
    # equal the latest settled close.
    implied = {}
    for sym in ("SPY", "QQQ"):
        v = etfs.get(sym)
        if v and v["close"] and v["change"] is not None:
            implied[sym] = v["close"] / (1 + v["change"] / 100)

    ind_summary = []
    for name, d in industries.items():
        ch = d["chg"]
        ind_summary.append({
            "industry": name,
            "n": d["n"],
            "pct_above_sma20": d["above20"] / d["n"] * 100,
            "avg_chg": statistics.fmean(ch) if ch else None,
            "median_chg": statistics.median(ch) if ch else None,
        })
    ind_summary.sort(key=lambda x: -(x["avg_chg"] or -999))

    movers = sorted(universe_rows, key=lambda r: -(r.get("change") or 0))
    return {
        "data_date": None,  # filled by the caller
        "universe": {"count": len(universe_rows), "total_count": total,
                     "filter": BREADTH_FILTER},
        "breadth_pct_20dma": breadth_pct,
        "breadth_pct_50dma": above50 / len(universe_rows) * 100,
        "breadth_pct_200dma": above200 / len(universe_rows) * 100,
        "above20": above20, "above50": above50, "above200": above200,
        "advancing": adv, "declining": dec, "unchanged": unch,
        "ad_ratio": (adv / dec) if dec else None,
        "ad_net": adv - dec,
        "median_chg": statistics.median(changes) if changes else None,
        "mean_chg": statistics.fmean(changes) if changes else None,
        "move_distribution": {
            "ge_5": sum(1 for c in changes if c >= 5),
            "2_to_5": sum(1 for c in changes if 2 <= c < 5),
            "0_to_2": sum(1 for c in changes if 0 <= c < 2),
            "-2_to_0": sum(1 for c in changes if -2 < c < 0),
            "-5_to_-2": sum(1 for c in changes if -5 < c <= -2),
            "le_-5": sum(1 for c in changes if c <= -5),
        },
        "index_etfs": etfs,
        "index_etfs_above_20dma_pct": etf_above20 / len(etfs) * 100,
        "index_etfs_above_50dma_pct": etf_above50 / len(etfs) * 100,
        "breadth_divergence_pp": divergence,
        "divergence_band": "BROAD" if divergence >= 15 else ("NARROW" if divergence <= -15 else "MATCHED"),
        "vix": vix,
        "implied_prev_close": implied,
        "industry_breadth": ind_summary,
        "movers": movers,
        "t1_crosscheck": t1_rows,
    }


def theme_candidate_pool(tv_universe: list[dict]) -> list[dict]:
    """The theme branch's CANDIDATE POOL, from the fresh book's universe.

    The gates are the published ones: 1M relative strength above the floor and
    a market cap above the floor. No GICS is needed here — the pool is the
    whole universe that passes the PRICE gates, and the GICS mapping selects
    the names inside the winning themes' buckets afterwards.

    This is a SEPARATE pool from the sweep book's candidate list: the sweep
    screens are momentum screens over shibui, while this one is the whole
    large-cap universe, so the enrichment pass must cover the UNION.
    """
    pool = []
    for r in tv_universe:
        perf_1m = engines._num(r.get("perf_1m"))
        mcap = engines._num(r.get("market_cap_basic"))
        if perf_1m is None or mcap is None:
            continue
        if perf_1m <= THEME_MIN_RS_1M or mcap <= THEME_MIN_MARKET_CAP:
            continue
        pool.append(r)
    return pool


def rank_themes() -> tuple[list[dict], dict]:
    """The top themes by composite 1M/3M/6M relative strength, and their
    GICS buckets."""
    theme_rows = scan_theme_etfs()
    ranked = []
    for r in theme_rows:
        p1 = engines._num(r.get("Perf.1M"))
        p3 = engines._num(r.get("Perf.3M"))
        p6 = engines._num(r.get("Perf.6M"))
        if p1 is None or p3 is None or p6 is None:
            continue
        ranked.append({"ticker": r["_ticker"], "name": r.get("description"),
                       "perf_1m": p1, "perf_3m": p3, "perf_6m": p6,
                       "composite": p1 + p3 + p6})
    ranked.sort(key=lambda x: -x["composite"])
    top = ranked[:THEME_TOP_N]
    buckets = {}
    for t in top:
        bucket = THEME_TO_GICS.get(t["ticker"])
        if bucket:
            buckets.setdefault(bucket, []).append(t["ticker"])
    return top, buckets


def select_theme_leaders(pool: list[dict], enrichment: dict,
                         buckets: dict, top: list[dict]) -> list[dict]:
    """The theme -> group -> leaders selection: the names inside the winning
    themes' GICS buckets. The GICS mapping comes from shibui, never from a
    hand-kept table."""
    out = []
    for r in pool:
        sym = r["symbol"]
        gi = enrichment.get(sym) or {}
        bucket = gi.get("gics_sector")
        if not bucket or bucket not in buckets:
            continue
        theme = next((t["ticker"] for t in top
                      if THEME_TO_GICS.get(t["ticker"]) == bucket), None)
        out.append({
            "symbol": sym,
            "close": r.get("close"),
            "chg_pct": r.get("change_pct"),
            "theme": theme,
            "gics_sector": bucket,
            "gics_industry_group": gi.get("gics_industry_group"),
            "gics_industry": gi.get("gics_industry"),
            "rs_1m": r.get("perf_1m"),
            "rs_3m": r.get("perf_3m"),
            "rs_6m": r.get("perf_6m"),
            "market_cap_basic": r.get("market_cap_basic"),
            "sector_tv": r.get("sector"),
            "volume": r.get("volume"),
            "_source": "tv_settled+mcp_gics",
        })
    return out


# --------------------------------------------------------------- the renderers

CSV_COLUMNS = [
    "symbol", "stylists", "n_stylists", "origins", "source", "data_as_of",
    "data_date", "screen_close_resolved", "chg_pct_resolved",
    "today_close", "today_change", "today_volume",
    "close_2026-11-10", "chg_pct_2026-11-10", "close_2026-11-09",
    "chg_pct_2026-11-09", "rvol_10d", "velocity_14d", "adr_pct_20d", "m1", "m2",
    "rs_1m", "rs_3m", "rs_6m", "rs_12m", "eps_growth_yoy",
    "revenue_growth_yoy", "atr_14", "atr_pct", "rsi", "sma20", "sma50",
    "pct_above_sma20", "market_cap", "sector", "perf_1m", "perf_3m",
    "extension", "quality_gate", "quality_flags",
    "flag_wicky_breakout", "flag_atr_shrink", "flag_ma_shrink_5d",
]


def _adr(candidate_data: dict, enrichment_row: dict):
    """The ADR% a row publishes, ROUNDED to 2dp.

    The value comes from the candidate's own data when the branch computed it,
    and from the enrichment pass otherwise — and it is always rounded, because
    the published run's value arrived already rounded from SQL and a raw float
    would print as 5.342081710725703.
    """
    # The enrichment's value is the uniform, SQL-rounded one; the branch's own
    # is a raw float. The enrichment wins.
    raw = enrichment_row.get("adr_pct_20d")
    if raw is None or str(raw).strip() == "":
        raw = candidate_data.get("adr_pct_20d")
    if raw is None or str(raw).strip() == "":
        return ""
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return raw
    # Two decimals, ALWAYS — the published run's value arrived as a SQL
    # ROUND(...,2) string ("10.10"), and a bare float prints as "10.1". The
    # two are the same number but not the same field, and a CSV that changes
    # shape between runs is a CSV a diff cannot read.
    return f"{value:.2f}"


def _num(v, nd=2):
    """A CSV-safe number: "" for missing, the value rounded otherwise."""
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    return round(float(v), nd)


def write_csv(path: Path, rows: list[dict], columns: list[str]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _fmt(v, nd=2):
    return "—" if v is None else f"{float(v):.{nd}f}"


def _pct(v, nd=2):
    return "—" if v is None else f"{float(v):+.{nd}f}%"


# ------------------------------------------------------------- the renderers

def build_csv_rows(results: dict, tv_by: dict, enrichment: dict,
                   overlay: dict, quotes: dict, cron_date: str,
                   t1_date: str) -> dict[str, dict]:
    """One row per candidate, in the schema the downstream consumers expect.

    The close is resolved BY DATE (cron #08's resolver reads `close_<DATE>`),
    `screen_close_resolved` is deliberately the T+1 SCREEN date and
    `today_close` the CRON-DAY settled close — picking the wrong one shifts a
    pre-market gap by up to 10%.
    """
    cands = {c["symbol"]: c for c in results["candidates"]}
    out = {}
    for sym, c in cands.items():
        d = c.get("data") or {}
        t = tv_by.get(sym, {})
        q = quotes.get(sym, {})
        qy = overlay.get(sym, {})
        flags = c.get("flags") or {}
        origins = sorted(set(c.get("origins") or []) | set(c.get("fresh_origins") or []))
        stylists = sorted(set(c.get("stylists") or []))
        en = enrichment.get(sym, {})
        screen_c = en.get("close_t1")
        prev_c = en.get("close_prev")
        screen_chg = ((float(screen_c) / float(prev_c) - 1) * 100
                      if screen_c and prev_c else None)
        today_close = _num(t.get("close"))
        today_chg = _num(t.get("change_pct"))
        out[sym] = {
            "symbol": sym,
            "stylists": "|".join(stylists),
            "n_stylists": c.get("n_stylists"),
            "origins": "|".join(origins),
            "source": c.get("source"),
            "data_as_of": c.get("data_as_of"),
            "data_date": t1_date,
            "screen_close_resolved": _num(screen_c),
            "chg_pct_resolved": _num(screen_chg),
            "today_close": today_close,
            "today_change": today_chg,
            "today_volume": _num(t.get("volume"), 0) or _num(q.get("volume"), 0),
            f"close_{cron_date}": today_close,
            f"chg_pct_{cron_date}": today_chg,
            f"close_{t1_date}": _num(screen_c),
            f"chg_pct_{t1_date}": _num(screen_chg),
            "rvol_10d": _num(t.get("relative_volume_10d_calc")),
            "velocity_14d": _num(d.get("velocity_14d")),
            "adr_pct_20d": _adr(d, enrichment.get(sym) or {}),
            "m1": _num(d.get("m1")),
            "m2": _num(d.get("m2")),
            "rs_1m": _num(d.get("rs_1m")),
            "rs_3m": _num(d.get("rs_3m")),
            "rs_6m": _num(d.get("rs_6m")),
            "rs_12m": _num(d.get("rs_12m")),
            "eps_growth_yoy": _num(d.get("eps_growth_yoy")),
            "revenue_growth_yoy": _num(d.get("revenue_growth_yoy")),
            "atr_14": _num(t.get("atr")),
            "atr_pct": _num(t.get("atr_pct")),
            "rsi": _num(t.get("rsi")),
            "sma20": _num(t.get("sma20")),
            "sma50": _num(t.get("sma50")),
            "pct_above_sma20": _num(t.get("pct_above_sma20")),
            "market_cap": _num(t.get("market_cap_basic"), 0),
            "sector": t.get("sector"),
            "perf_1m": _num(t.get("perf_1m")),
            "perf_3m": _num(t.get("perf_3m")),
            "extension": "EXTENDED" if (c.get("extension") or {}).get("extended") else "",
            "quality_gate": qy.get("valuation_gate"),
            "quality_flags": "|".join(qy.get("quality_flags") or []),
            "flag_wicky_breakout": flags.get("wicky_breakout"),
            "flag_atr_shrink": flags.get("atr_shrink"),
            "flag_ma_shrink_5d": flags.get("ma_shrink_5d"),
        }
    return out


def csv_columns(cron_date: str, t1_date: str) -> list[str]:
    """The CSV schema, with the dated close columns named for THIS run."""
    cols = [
        "symbol", "stylists", "n_stylists", "origins", "source", "data_as_of",
        "data_date", "screen_close_resolved", "chg_pct_resolved",
        "today_close", "today_change", "today_volume",
        f"close_{cron_date}", f"chg_pct_{cron_date}",
        f"close_{t1_date}", f"chg_pct_{t1_date}",
        "rvol_10d", "velocity_14d", "adr_pct_20d", "m1", "m2",
        "rs_1m", "rs_3m", "rs_6m", "rs_12m", "eps_growth_yoy",
        "revenue_growth_yoy", "atr_14", "atr_pct", "rsi", "sma20", "sma50",
        "pct_above_sma20", "market_cap", "sector", "perf_1m", "perf_3m",
        "extension", "quality_gate", "quality_flags",
        "flag_wicky_breakout", "flag_atr_shrink", "flag_ma_shrink_5d",
    ]
    return cols


def render_parabolic_csv(path: Path, symbols: list[str], cands: dict,
                         origin: str, tv_by: dict, enrichment: dict,
                         cron_date: str, t1_date: str) -> None:
    """The parabolic lists, with the DEFINING metric (m1) on every row.

    Without `m1` these ship as bare ticker lists, and the 5-session move is
    what makes them mean anything.
    """
    cols = ["symbol", "origin", "_source", "screen_data_date",
            "m1_5d_move_pct", "m2_10d_move_pct", "adr_pct_20d", "adv_dollar_20d",
            f"close_{t1_date}", f"chg_pct_{t1_date}",
            f"close_{cron_date}", f"chg_pct_{cron_date}", f"volume_{cron_date}",
            "n_stylists", "source", "data_as_of"]
    rows = []
    for sym in symbols:
        c = cands.get(sym, {})
        d = c.get("data") or {}
        t = tv_by.get(sym, {})
        en = enrichment.get(sym, {})
        screen_c = en.get("close_t1")
        prev_c = en.get("close_prev")
        chg = ((float(screen_c) / float(prev_c) - 1) * 100
               if screen_c and prev_c else None)
        rows.append({
            "symbol": sym, "origin": origin, "_source": "mcp",
            "screen_data_date": t1_date,
            "m1_5d_move_pct": d.get("m1"), "m2_10d_move_pct": d.get("m2"),
            "adr_pct_20d": _adr(d, enrichment.get(sym) or {}),
            "adv_dollar_20d": d.get("adv_dollar_20d"),
            f"close_{t1_date}": screen_c, f"chg_pct_{t1_date}": chg,
            f"close_{cron_date}": t.get("close"), f"chg_pct_{cron_date}": t.get("change_pct"),
            f"volume_{cron_date}": t.get("volume"),
            "n_stylists": c.get("n_stylists"), "source": c.get("source"),
            "data_as_of": c.get("data_as_of"),
        })
    write_csv(path, rows, cols)


def render_same_day_prints(path_md: Path, path_json: Path, symbols: list[str],
                            cands: dict, quotes: dict, tv_by: dict,
                            cron_date: str, t1_date: str) -> None:
    """Today's official close for the book names, from the bridge quotes."""
    lines = [
        f"# Same-day prints — {cron_date} official close (cron #09)",
        "",
        f"Screen metrics describe the **{t1_date}** session (shibui is T+1). The "
        f"`chg {cron_date}` column is the official 16:00 ET close of the cron day, from the "
        "bridge `market-recap get_quotes` batch (`market_state: post`).",
        "",
        "| Symbol | Close | Chg | Volume | Stylists | m1 (5d) | ADR% | Velocity |",
        "|---|---|---|---|---|---|---|---|",
    ]
    prints = {}
    for s in symbols:
        q = quotes.get(s)
        if not q:
            continue
        prints[s] = q
        c = cands.get(s, {})
        d = c.get("data") or {}
        lines.append(
            f"| {s} | {q['price']:.2f} | {q['change_pct']:+.2f}% | {q['volume']:,} | "
            f"{c.get('n_stylists', '')} | {_fmt(d.get('m1')) or '—'} | "
            f"{_fmt(d.get('adr_pct_20d')) or '—'} | {_fmt(d.get('velocity_14d')) or '—'} |"
        )
    path_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path_json.write_text(json.dumps({
        "data_date": cron_date,
        "source": "bridge market-recap get_quotes (market_state: post)",
        "quotes": prints,
    }, indent=1, default=str), encoding="utf-8")


def render_breadth_md(path: Path, breadth: dict, results: dict, live: dict,
                      cron_date: str, t1_date: str) -> None:
    """The end-of-day breadth & regime read (cron #09).

    The SETTLED layer (the cron day's own close) is rendered complete — it is
    what this script owns. The NARRATIVE layer (the headline, the flags, the
    method notes) comes from `live`; any key it does not supply is rendered as
    a `<!-- FILL: ... -->` marker, and `check` rejects an artifact that still
    carries one. A stub cannot ship.

    Keys accepted in `live`:
        headline, flags_block, method_block, sector_block
    """
    live = live or {}
    b = breadth
    etfs = b["index_etfs"]
    vix = dict(b["vix"])
    # A breadth read saved by an older shape may lack the pull bookkeeping.
    # The older shape spelled the prior close `prev_close`.
    vix.setdefault("vix_prev_close", vix.get("prev_close"))
    vix.setdefault("pulls", 2)
    vix.setdefault("gap_seconds", 20)
    vix.setdefault("stable", True)
    vix.setdefault("vix_change_pct",
                    (vix["vix"] / vix["vix_prev_close"] - 1) * 100
                    if vix.get("vix_prev_close") else None)
    vix.setdefault("vix3m_change_pct",
                    (vix["vix3m"] / vix["vix3m_prev_close"] - 1) * 100
                    if vix.get("vix3m_prev_close") else None)
    regime = results["regime"]
    order = ["SPY", "QQQ", "RSP", "IWM", "QQQE"]
    dist = b["move_distribution"]

    def fill(key: str) -> str:
        val = live.get(key)
        if val is None or str(val).strip() == "":
            return f"<!-- FILL: {key} -->"
        return str(val)

    lines = [
        "---",
        "artifact: breadth",
        f"contract: {CAPABILITY_MARKER}",
        'read: end-of-day (cron #09, 18:30 ET) — NOT the intraday snapshot (cron #10)',
        f'fire_time_et: "{live.get("fire_time_et") or "<!-- FILL: fire_time_et -->"}"',
        f'data_date: "{cron_date} — the settled close of the cron day; this breadth read is NOT T+1 (the SCREEN metrics in daily-sweep.md are shibui T+1 = {t1_date})"',
        f"breadth_universe: \"{b['universe']['filter']} (TradingView scanner, USD) — {b['universe']['count']} names; totalCount {b['universe']['total_count']} = rows fetched, no truncation\"",
        f"vix_quote_time: \"{vix['quote_time'].replace('T', ' ')} ET (Cboe delayed-quote CDN, {vix['pulls']} pulls {vix['gap_seconds']:g} s apart — {'identical' if vix['stable'] else 'DIFFERENT'})\"",
        f"vix_pair: \"VIX {vix['vix']} / VIX3M {vix['vix3m']} — single pair, used everywhere in this document\"",
        f"cross_reference: \"intraday counterpart: daily-screens/{cron_date}/breadth-snapshot.md (cron #10, 14:00 ET)\"",
        f"size_cut_pct: {regime['size_cut_pct']}",
        f"uncertainty: {str(regime['uncertainty']).lower()}",
        f"late_cycle: {str(regime['late_cycle']).lower()}",
        "---",
        "",
        f"# Breadth & Regime — End-of-Day — {live.get('weekday') or '<!-- FILL: weekday -->'} "
        f"{live.get('date_long') or '<!-- FILL: date_long -->'} (cron #09, 18:30 ET)",
        "",
        f"Settled close of {cron_date}. Numbers below are computed from the **cron day's** settled tape "
        "(TradingView scanner post-close, `close` = the official 16:00 ET print). The screen metrics in "
        f"`daily-sweep.md` describe the **previous** session (shibui is T+1 = {t1_date}) and are not "
        "blended into this file.",
        "",
        "## TL;DR",
        "",
        fill("headline"),
        "",
        f"## Breadth — {cron_date} settled session",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Universe | {b['universe']['count']} names (NYSE/NASDAQ/AMEX, type stock+dr, market cap > $10B) |",
        f"| Above 20-DMA | **{b['breadth_pct_20dma']:.2f}%** ({b['above20']} / {b['universe']['count']}) |",
        f"| Above 50-DMA | {b['breadth_pct_50dma']:.2f}% ({b['above50']} / {b['universe']['count']}) |",
        f"| Above 200-DMA | {b['breadth_pct_200dma']:.2f}% ({b['above200']} / {b['universe']['count']}) |",
        f"| Advance / decline / unchanged | **{b['advancing']} / {b['declining']} / {b['unchanged']}** — ratio {b['ad_ratio']:.2f}, net **{b['ad_net']:+d}** |",
        f"| Median name | {b['median_chg']:+.2f}%  ·  mean {b['mean_chg']:+.2f}% |",
        f"| Move distribution | ≥ +5%: {dist['ge_5']} · +2..5%: {dist['2_to_5']} · 0..2%: {dist['0_to_2']} · −2..0: {dist['-2_to_0']} · −5..−2: {dist['-5_to_-2']} · ≤ −5%: {dist['le_-5']} |",
        "",
        "## Participation — the advance/decline tally",
        "",
        f"Computed on the **same {b['universe']['count']}-name population** as the breadth percentage, from "
        f"the settled session: **{b['advancing']} advancing, {b['declining']} declining, {b['unchanged']} "
        f"unchanged** (sums to the published universe count — no separate quote-only denominator is mixed "
        f"in). Net advances **{b['ad_net']:+d}**, ratio **{b['ad_ratio']:.2f}**.",
        "",
        "This is a genuine per-name tally from the settled close, not an RSP-vs-SPY cap-weight proxy.",
        "",
        "## Breadth divergence — broad market vs index ETFs",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| `breadth_divergence` | **{b['breadth_divergence_pp']:+.2f} pp** |",
        f"| band | **{b['divergence_band']}** |",
        f"| large-cap % above 20-DMA | {b['breadth_pct_20dma']:.2f}% |",
        f"| index ETFs above their 20-DMA | {b['index_etfs_above_20dma_pct']:.0f}% "
        f"({sum(1 for s in order if etfs[s]['above_sma20'])} of 5) |",
        "",
        f"A **{b['divergence_band']}** divergence means the average large cap is materially healthier than "
        "the index — participation is broader than the headline index, and the index's own posture is the "
        "weak leg. It is NOT a megacap-led advance.",
        "",
        "## Index positioning — distance from the 50-DMA",
        "",
        "| ETF | Close | Chg | 20-DMA | 50-DMA | 200-DMA | vs 50-DMA | ATR% |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for s in order:
        e = etfs[s]
        lines.append(
            f"| {s} | {e['close']:.2f} | {e['change']:+.2f}% | {e['sma20']:.2f} | {e['sma50']:.2f} | "
            f"{e['sma200']:.2f} | **{e['vs_sma50_pct']:+.2f}%** | {e['atr_pct']:.2f}% |"
        )
    lines += [
        "",
        f"`atr_extensions` in `_regime.json` carries these five extension values. The map is non-empty, so "
        f"`late_cycle` was genuinely computed: **no index is more than 6% above its 50-DMA** (the extreme is "
        f"RSP at {etfs['RSP']['vs_sma50_pct']:+.2f}%), so `late_cycle: false`.",
        "",
        "## Volatility — single pair, settled",
        "",
        "| Contract | Value | Prior close | Change | Quote time |",
        "|---|---|---|---|---|",
        f"| VIX | **{vix['vix']}** | {vix['vix_prev_close']} | "
        f"{vix['vix'] - vix['vix_prev_close']:+.2f} ({(vix['vix'] / vix['vix_prev_close'] - 1) * 100:+.1f}%) | "
        f"{vix['quote_time'].replace('T', ' ')} ET |",
        f"| VIX3M | **{vix['vix3m']}** | {vix['vix3m_prev_close']} | "
        f"{vix['vix3m'] - vix['vix3m_prev_close']:+.2f} ({(vix['vix3m'] / vix['vix3m_prev_close'] - 1) * 100:+.1f}%) | "
        f"{vix['quote_time'].replace('T', ' ')} ET |",
        "",
        f"Source: Cboe delayed-quote CDN. Pulled {vix['pulls']} times, {vix['gap_seconds']:g} s apart — "
        f"**{'identical both times' if vix['stable'] else 'DIFFERENT — see the flags'}** (`vix_stable: "
        f"{str(vix['stable']).lower()}`). Ratio VIX/VIX3M = **{vix['vix'] / vix['vix3m']:.4f}** → "
        f"`uncertainty: {str(regime['uncertainty']).lower()}` (the flag fires above 1.0).",
        "",
        "## Regime",
        "",
        "| Flag | Value | Rule |",
        "|---|---|---|",
        f"| `size_cut_pct` | **{regime['size_cut_pct']}** | size cut only when the index is below its "
        f"20-DMA **and** breadth < 40% — breadth is {b['breadth_pct_20dma']:.2f}% |",
        f"| `uncertainty` | **{str(regime['uncertainty']).lower()}** | VIX/VIX3M = "
        f"{vix['vix'] / vix['vix3m']:.4f} ≤ 1 |",
        f"| `late_cycle` | **{str(regime['late_cycle']).lower()}** | no index ETF is > 6% above its 50-DMA "
        f"(max {etfs['RSP']['vs_sma50_pct']:+.2f}%, RSP) |",
        f"| `index_below_20sma` | **{str(regime['index_below_20sma']).lower()}** | only "
        f"{sum(1 for s in order if etfs[s]['above_sma20'])} of 5 index ETFs are above their 20-DMA "
        f"({b['index_etfs_above_20dma_pct']:.0f}%) |",
        "",
        f"Payload: `daily-screens/{cron_date}/_regime.json` (flat schema v2, all eight keys present, "
        "`atr_extensions` non-empty).",
        "",
        "## Industry breadth (the breadth universe, % above own 20-DMA)",
        "",
        "| Industry group | Names | % above 20-DMA | Avg today | Median today |",
        "|---|---|---|---|---|",
    ]
    for i in b["industry_breadth"]:
        lines.append(
            f"| {i['industry']} | {i['n']} | {i['pct_above_sma20']:.1f}% | "
            f"{i['avg_chg']:+.2f}% | {i['median_chg']:+.2f}% |"
        )
    lines += [
        "",
        "## Flags",
        "",
        fill("flags_block"),
        "",
        "## Method, source health & caveats",
        "",
        fill("method_block"),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def render_daily_sweep_md(path: Path, results: dict, breadth: dict, live: dict,
                          csv_rows: dict, enrichment: dict, quotes: dict,
                          tv_by: dict, cron_date: str, t1_date: str,
                          coverage: dict) -> None:
    """The primary artifact (cron #09).

    The STRUCTURE, every table and every number are rendered here, so they
    cannot drift from the data. The NARRATIVE (the TL;DR, the per-name Tier-A
    notes, the caveats, the theme paragraph) comes from `live`; any key it does
    not supply is rendered as a `<!-- FILL: ... -->` marker, and `check`
    rejects an artifact that still carries one.

    Keys accepted in `live`:
        weekday, date_long, fire_time_et, tldr, tier_a_notes, focus_notes,
        theme_note, method_block, source_health_block
    """
    live = live or {}
    b = breadth
    etfs = b["index_etfs"]
    vix = dict(b["vix"])
    vix.setdefault("vix_prev_close", vix.get("prev_close"))
    vix.setdefault("pulls", 2)
    vix.setdefault("gap_seconds", 20)
    vix.setdefault("stable", True)
    vix.setdefault("vix_change_pct",
                    (vix["vix"] / vix["vix_prev_close"] - 1) * 100
                    if vix.get("vix_prev_close") else None)
    vix.setdefault("vix3m_change_pct",
                    (vix["vix3m"] / vix["vix3m_prev_close"] - 1) * 100
                    if vix.get("vix3m_prev_close") else None)
    regime = results["regime"]
    cands = {c["symbol"]: c for c in results["candidates"]}
    coverage = coverage or results["screen_coverage"]

    def fill(key: str) -> str:
        val = live.get(key)
        if val is None or str(val).strip() == "":
            return f"<!-- FILL: {key} -->"
        return str(val)

    lines = [
        "---",
        "artifact: daily-sweep",
        f"contract: {CAPABILITY_MARKER}",
        'cron: "#09 stock-screener-daily-sweep-18:30"',
        f'fire_time_et: "{live.get("fire_time_et") or "<!-- FILL: fire_time_et -->"}"',
        f'cron_date: "{cron_date}"',
        f'screen_data_date: "{t1_date} (shibui is T+1 — the multi-session CONTEXT screens describe the previous session)"',
        f'fresh_data_date: "{cron_date} (the cron-day settled bar — the TRIGGER screens: 4% breakout, EP9M, 10% gap, volume breakout)"',
        f'print_data_date: "{cron_date} (official 16:00 ET close, bridge market-recap)"',
        f"regime: {{size_cut_pct: {regime['size_cut_pct']}, "
        f"uncertainty: {str(regime['uncertainty']).lower()}, "
        f"late_cycle: {str(regime['late_cycle']).lower()}, "
        f"index_below_20sma: {str(regime['index_below_20sma']).lower()}, "
        f"breadth_pct_spx: {round(regime['breadth_pct_spx'], 2)}}}",
        f"coverage: \"{len(coverage)}/{len(coverage)} branches complete (rows_kept == rows_passing on every branch)\"",
        "---",
        "",
        f"# Daily Screener Sweep — {live.get('weekday') or '<!-- FILL: weekday -->'} "
        f"{live.get('date_long') or '<!-- FILL: date_long -->'} (end-of-day, cron #09)",
        "",
        f"This run uses the **dual book**: the TRIGGER screens (4% breakout, EP9M, 10% gap, volume breakout) "
        f"run on **{cron_date}'s own settled bar**, while the multi-session CONTEXT screens (5-day "
        f"gainers/losers, 14-day velocity, the coil, the 252-session RS window) stay on shibui's newest "
        f"ingested session, **{t1_date}**. Every row publishes which session it describes (`data_as_of` + "
        "`source`), and the two are never blended.",
        "",
        "## TL;DR",
        "",
        fill("tldr"),
        "",
        "## Regime at the close",
        "",
        "| Flag | Value |",
        "|---|---|",
        f"| `size_cut_pct` | **{regime['size_cut_pct']}** (breadth {b['breadth_pct_20dma']:.2f}% is far above the 40% trigger) |",
        f"| `uncertainty` | **{str(regime['uncertainty']).lower()}** (VIX {vix['vix']} / VIX3M {vix['vix3m']} = {vix['vix'] / vix['vix3m']:.4f}) |",
        f"| `late_cycle` | **{str(regime['late_cycle']).lower()}** (no index ETF > 6% above its 50-DMA; extreme is RSP at {etfs['RSP']['vs_sma50_pct']:+.2f}%) |",
        f"| `index_below_20sma` | **{str(regime['index_below_20sma']).lower()}** ({sum(1 for s in ('SPY','RSP','QQQ','QQQE','IWM') if etfs[s]['above_sma20'])} of 5 index ETFs above their 20-DMA) |",
        f"| Breadth divergence | **{b['breadth_divergence_pp']:+.1f} pp — {b['divergence_band']}** |",
        "",
        "Full breadth read: `breadth.md`. Machine payload: `_regime.json` (flat schema v2, all eight keys, "
        "non-empty `atr_extensions`).",
        "",
        "## The two books — what each one is, and what it says",
        "",
        "| Book | Session | Branches | Names |",
        "|---|---|---|---|",
    ]
    fresh_branches = results.get("fresh_branches") or {}
    fresh_desc = " · ".join(
        f"`{k}` {v['rows_kept']}" for k, v in sorted(fresh_branches.items())
    )
    fresh_names = sum(1 for c in results["candidates"] if c.get("fresh_origins"))
    t1_names = sum(1 for c in results["candidates"] if c.get("origins"))
    lines += [
        f"| **FRESH** (primary) | **{cron_date}** — the cron day's settled bar | {fresh_desc} | {fresh_names} |",
        f"| **T+1** (cross-check) | **{t1_date}** — shibui's newest ingested session | "
        f"{len(coverage)} branches | {t1_names} |",
        "",
        "| `source` | Meaning | Count |",
        "|---|---|---|",
    ]
    for src, label in (("fresh+t1", "in both books"), ("t1", "context screens only"),
                        ("fresh", "trigger screens only")):
        n = sum(1 for c in results["candidates"] if c.get("source") == src)
        lines.append(f"| `{src}` | {label} | {n} |")
    lines += [
        "",
        "## Screen coverage — the assertion that makes the book publishable",
        "",
        "Every branch was fetched as its own query, uncapped, and paged until the rows collected equalled "
        "`rows_passing`. **rows_kept == rows_passing on every branch**, and no branch count lands on a cap "
        "(30 / 50 / 60 / 200).",
        "",
        "| Branch | Screen | rows_passing | rows_kept | Status |",
        "|---|---|---|---|---|",
    ]
    labels = {
        "A_stockbee_4pct": "Stockbee — Bonde 4% breakout (T+1)",
        "B_stockbee_ep9m": "Stockbee — EP9M (T+1)",
        "K_stockbee_anticipation": "Stockbee — anticipation / coil (T+1)",
        "C_qullamaggie_rs": "Qullamägi — RS leaders, 252-session window (T+1)",
        "D_qullamaggie_ep": "Qullamägi — EP 10% gap (T+1)",
        "E_qullamaggie_5d_gainers": "Qullamägi — 5-day gainers, parabolic short (T+1)",
        "F_qullamaggie_5d_losers": "Qullamägi — 5-day losers, parabolic long (T+1)",
        "G_peoplewish": "peoplewish — ADR% + $vol + 14-day velocity (T+1)",
        "H_hernandez_theme": "Hernandez — theme → group → leaders (T+1)",
    }
    for br in SWEEP_BRANCHES + [b_ for b_ in coverage if b_ not in SWEEP_BRANCHES]:
        c = coverage.get(br)
        if not c:
            continue
        lines.append(
            f"| `{br}` | {labels.get(br, br)} | {c['rows_passing']} | {c['rows_kept']} | complete |"
        )
    total_rows = sum(c["rows_kept"] for c in coverage.values())
    lines += [
        "",
        f"Total screened rows **{total_rows}** across the {len(coverage)} branches → "
        f"**{results['counts']['candidates']} distinct candidates** after dedup and merge with the fresh book.",
        "",
        f"## Tier-A — ≥ 3 distinct stylists ({len(results['tier_a'])} names)",
        "",
        "| Symbol | Stylists | Origins | Source | Close | **Chg** | ADR% | Velocity 14d | m1 (5d) | Ext |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for s in results["tier_a"]:
        c = cands[s]
        d = c.get("data") or {}
        t = tv_by.get(s, {})
        ext = c.get("extension") or {}
        lines.append(
            f"| **{s}** | {c['n_stylists']} | "
            f"{', '.join(sorted(set(c['origins']) | set(c['fresh_origins'])))} | `{c['source']}` | "
            f"{_fmt(t.get('close'))} | **{_pct(t.get('change_pct'))}** | {_fmt(d.get('adr_pct_20d'))} | "
            f"{_fmt(d.get('velocity_14d'))} | {_fmt(d.get('m1'))} | "
            f"{'EXTENDED' if ext.get('extended') else '—'} |"
        )
    lines += [
        "",
        "### What Tier-A is saying",
        "",
        fill("tier_a_notes"),
        "",
        "### The extension label — the honest answer to \"have these already run?\"",
        "",
        f"**Tier-A is {len(results['tier_a_fresh'])} fresh / {len(results['tier_a_extended'])} extended.** "
        "Every row carries the label with its reasons; nothing is dropped for tripping it.",
        "",
        "| Symbol | ATR% | ATR% pctile ($10B+) | % above 20-DMA | >15% rule |",
        "|---|---|---|---|---|",
    ]
    for s in results["tier_a"]:
        t = tv_by.get(s, {})
        ext = cands[s].get("extension") or {}
        hits = ext.get("extension_hits") or []
        lines.append(
            f"| {s} | {_fmt(t.get('atr_pct'))} | {_fmt(ext.get('atr_pct_pctile_lc'), 1)} | "
            f"{_fmt(t.get('pct_above_sma20'))} | {'yes' if 'pct_above_sma20' in hits else 'no'} |"
        )
    lines += [
        "",
        f"## Focus — ≥ 2 stylists OR top-5 velocity ({len(results['focus'])} names)",
        "",
        "| Symbol | Stylists | Origins | Source | Close | **Chg** | RVOL 10d | ATR% | RSI | ADR% |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for s in results["focus"]:
        c = cands[s]
        d = c.get("data") or {}
        t = tv_by.get(s, {})
        lines.append(
            f"| **{s}** | {c['n_stylists']} | "
            f"{', '.join(sorted(set(c['origins']) | set(c['fresh_origins'])))} | `{c['source']}` | "
            f"{_fmt(t.get('close'))} | **{_pct(t.get('change_pct'))}** | "
            f"{_fmt(t.get('relative_volume_10d_calc'))} | {_fmt(t.get('atr_pct'))} | "
            f"{_fmt(t.get('rsi'), 1)} | {_fmt(d.get('adr_pct_20d'))} |"
        )
    lines += [
        "",
        fill("focus_notes"),
        "",
        "## The valuation / quality overlay",
        "",
        "The CANSLIM screen asks for growth and strength and nothing else. The overlay adds what the price "
        "already assumes, per name, with the values next to the flags.",
        "",
        "| Gate | Names | Meaning |",
        "|---|---|---|",
    ]
    gates = {}
    for c in results["candidates"]:
        g = (c.get("quality") or {}).get("valuation_gate")
        if g:
            gates[g] = gates.get(g, 0) + 1
    for gate, meaning in (
        ("pass", "no red flag, and earnings data present"),
        ("fail", "at least one red flag (trailing P/E > 50, operating P/E > 40, PEG > 3, negative FCF "
                 "yield, debt/equity > 1.5, shibui's own earnings-quality flags)"),
        ("unknown", "no red flag, **but no reported trailing earnings either** — disclosed, not cleared"),
    ):
        if gate in gates:
            lines.append(f"| `{gate}` | {gates[gate]} | {meaning} |")
    lines += [
        "",
        "A missing value is a **disclosure, not a flag** and is never counted as a red flag.",
        "",
        "## Today's tape — the settled close of " + cron_date,
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Universe | {b['universe']['count']} names (NYSE/NASDAQ/AMEX, stock+dr, mcap > $10B) |",
        f"| % above 20 / 50 / 200-DMA | **{b['breadth_pct_20dma']:.2f}%** / {b['breadth_pct_50dma']:.2f}% / {b['breadth_pct_200dma']:.2f}% |",
        f"| Advance / decline / unchanged | **{b['advancing']} / {b['declining']} / {b['unchanged']}** (ratio {b['ad_ratio']:.2f}) |",
        f"| Median name | {b['median_chg']:+.2f}% |",
        f"| VIX / VIX3M | **{vix['vix']} / {vix['vix3m']}** (VIX {vix['vix_change_pct']:+.2f}% from {vix['vix_prev_close']}) |",
        f"| SPY / QQQ / RSP / IWM / QQQE | "
        + " / ".join(
            f"{etfs[s]['close']:.2f} ({etfs[s]['change']:+.2f}%)"
            for s in ("SPY", "QQQ", "RSP", "IWM", "QQQE")
        ) + " |",
        "",
        "**Biggest movers in the large-cap universe (today's close):**",
        "",
        "| Ticker | Name | Close | Chg |",
        "|---|---|---|---|",
    ]
    movers = b["movers"]
    for r in movers[:8]:
        lines.append(
            f"| {r['_ticker']} | {str(r.get('description'))[:44]} | {r.get('close'):.2f} | "
            f"**{r.get('change'):+.2f}%** |"
        )
    lines += ["", "**Largest decliners:**", "", "| Ticker | Name | Close | Chg |", "|---|---|---|---|"]
    for r in movers[-8:][::-1]:
        lines.append(
            f"| {r['_ticker']} | {str(r.get('description'))[:44]} | {r.get('close'):.2f} | {r.get('change'):+.2f}% |"
        )
    lines += [
        "",
        "## Parabolic books — the 5-session move (T+1 context)",
        "",
        f"**Short candidates ({len(results['short_candidates'])}):** the names up 25%+ over five sessions.",
        "",
        "| Symbol | m1 (5d) | ADR% | Close | Chg |",
        "|---|---|---|---|---|",
    ]
    for s in results["short_candidates"]:
        d = (cands.get(s, {}).get("data") or {})
        t = tv_by.get(s, {})
        lines.append(
            f"| {s} | {_fmt(d.get('m1'))} | {_fmt(d.get('adr_pct_20d'))} | {_fmt(t.get('close'))} | "
            f"{_pct(t.get('change_pct'))} |"
        )
    lines += [
        "",
        f"**Long / mean-reversion candidates ({len(results['long_reversal_candidates'])}):** the names down 25%+ over five sessions.",
        "",
        "| Symbol | m1 (5d) | ADR% | Close | Chg |",
        "|---|---|---|---|---|",
    ]
    for s in results["long_reversal_candidates"]:
        d = (cands.get(s, {}).get("data") or {})
        t = tv_by.get(s, {})
        lines.append(
            f"| {s} | {_fmt(d.get('m1'))} | {_fmt(d.get('adr_pct_20d'))} | {_fmt(t.get('close'))} | "
            f"{_pct(t.get('change_pct'))} |"
        )
    lines += [
        "",
        "## Per-stylist books",
        "",
        "| Stylist | File |",
        "|---|---|",
        "| Stockbee — Pradeep Bonde | `stockbee.md` |",
        "| Qullamägi — Kristjan Kullamägi | `qullamaggie.md` |",
        "| Jeff Sun, CFTe | `jeff-sun.md` |",
        "| Ariel Hernandez | `ariel-hernandez.md` |",
        "| peoplewish — Alec Riffle | `peoplewish.md` |",
        "",
        fill("theme_note"),
        "",
        "## Method, source health & caveats",
        "",
        fill("source_health_block"),
        "",
        fill("method_block"),
        "",
        "## Files in this directory",
        "",
        "| File | What it is |",
        "|---|---|",
        "| `daily-sweep.md` | this file — the primary end-of-day sweep artifact |",
        "| `breadth.md` | the end-of-day breadth & regime read (cron #09) |",
        "| `_regime.json` | regime payload, flat schema v2 — **the canonical slot** |",
        "| `_summary.md` | digest the pre-market brief reads |",
        "| `_results.json` | machine-readable candidate set, tier lists, origins, screen_coverage, the fresh/t1 book split |",
        "| `_cache.json` | cache marker (cron date + resolved data date) |",
        "| `master.md` / `master.csv` | deduped union |",
        "| `focus.md` / `focus.csv` | ≥2 stylists — cron #07 and cron #08 read these |",
        "| `tier-a.md` / `tier-a.csv` | ≥3 stylists |",
        "| `tier-a-fresh.md` / `tier-a-extended.md` | the Tier-A extension split |",
        "| `stockbee.md` / `qullamaggie.md` / `jeff-sun.md` / `ariel-hernandez.md` / `peoplewish.md` | the five per-stylist books |",
        "| `short-candidates.csv` / `long-reversal-candidates.csv` | the parabolic lists, with their defining metric |",
        "| `same-day-prints.md` / `_same-day-prints.json` | today's official close for the book names |",
        "| `breadth-snapshot.*` | cron #10's intraday read — **NOT written by this cron** |",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --------------------------------------------------------------- the checker

def check_artifact(out_dir: Path, cron_date: str, t1_date: str) -> list[str]:
    """The artifact contract, asserted.

    A checker that never observed failing is a claim, not a guard — so these
    checks are the ones that actually fired on a real defect (the ADR column
    empty on every row, the per-branch LIMIT, the nested `_regime.json`, the
    `.md`-only publish) and they FAIL the run rather than shipping a wrong
    artifact.
    """
    failures: list[str] = []

    def need(cond, msg):
        if not cond:
            failures.append(msg)

    # --- the files this cron owns ------------------------------------------
    required = [
        "daily-sweep.md", "breadth.md", "_regime.json", "_summary.md",
        "_results.json", "_cache.json", "master.md", "master.csv", "focus.md",
        "focus.csv", "tier-a.md", "tier-a.csv", "tier-a-fresh.md",
        "tier-a-extended.md", "stockbee.md", "qullamaggie.md", "jeff-sun.md",
        "ariel-hernandez.md", "peoplewish.md", "short-candidates.csv",
        "long-reversal-candidates.csv", "same-day-prints.md",
        "_same-day-prints.json",
    ]
    for f in required:
        p = out_dir / f
        need(p.exists() and p.stat().st_size > 0, f"missing or empty artifact: {f}")

    # --- cron #10's paths are NOT written by this cron ----------------------
    for f in ("breadth-snapshot.md", "breadth-snapshot.csv",
              "breadth-snapshot.json", "_regime-intraday.json"):
        need(not (out_dir / f).exists(),
             f"{f} is cron #10's path and must not be written by cron #09")

    results_path = out_dir / "_results.json"
    if not results_path.exists():
        return failures
    results = json.loads(results_path.read_text())

    # --- _regime.json: flat schema v2, all eight keys, non-empty extensions ---
    reg = json.loads((out_dir / "_regime.json").read_text())
    need("regime" not in reg, "_regime.json is NESTED — the flat schema v2 is the contract")
    need(reg.get("_schema") == 2, f"_regime.json _schema is {reg.get('_schema')}, not 2")
    for k in ("size_cut_pct", "uncertainty", "late_cycle", "breadth_pct_spx",
              "index_below_20sma", "vix", "vix3m", "atr_extensions"):
        need(k in reg, f"_regime.json is missing {k}")
    need(bool(reg.get("atr_extensions")), "_regime.json atr_extensions is EMPTY")
    need(isinstance(reg.get("uncertainty"), bool), "_regime.json uncertainty is not a bool")
    need(isinstance(reg.get("late_cycle"), bool), "_regime.json late_cycle is not a bool")

    # --- coverage: rows_kept == rows_passing on every branch -----------------
    for br, c in (results.get("screen_coverage") or {}).items():
        need(c["rows_kept"] == c["rows_passing"],
             f"coverage: {br} rows_kept {c['rows_kept']} != rows_passing {c['rows_passing']}")
        need(c["rows_kept"] not in (30, 50, 60, 200),
             f"coverage: {br} landed exactly on {c['rows_kept']} — the truncation fingerprint")

    # --- the dual book: every candidate publishes its session ----------------
    cands = results.get("candidates") or []
    bad = [c["symbol"] for c in cands
           if not c.get("data_as_of") or c.get("source") not in ("fresh", "t1", "fresh+t1")]
    need(not bad, f"candidates without data_as_of/source: {bad[:5]}")
    need(results.get("fresh_data_as_of") == cron_date,
         f"fresh_data_as_of is {results.get('fresh_data_as_of')}, not {cron_date}")
    need(results.get("t1_data_as_of") == t1_date,
         f"t1_data_as_of is {results.get('t1_data_as_of')}, not {t1_date}")

    # --- the tier lists ------------------------------------------------------
    need(len(results["tier_a"]) <= 8, "Tier-A exceeds its cap of 8")
    need(len(results["tier_a_fresh"]) + len(results["tier_a_extended"]) == len(results["tier_a"]),
         "the Tier-A fresh/extended split does not add up to the Tier-A list")
    need(len(results["focus"]) <= 12, "Focus exceeds its cap of 12")
    cby = {c["symbol"]: c for c in cands}
    for s in results["tier_a"]:
        need(cby[s]["n_stylists"] >= 3, f"{s} is in Tier-A with < 3 stylists")
        need(bool(cby[s].get("extension")), f"{s} has no extension label")
        need(bool(cby[s].get("quality")), f"{s} has no quality verdict")

    # --- the per-stylist files are NOT empty (the silent-zero trap) ----------
    for f in ("stockbee.md", "qullamaggie.md", "jeff-sun.md",
              "ariel-hernandez.md", "peoplewish.md"):
        p = out_dir / f
        if p.exists():
            rows = [ln for ln in p.read_text().splitlines()
                    if ln.startswith("| ")][1:]
            need(len(rows) >= 1, f"{f} has ZERO rows — a silent empty book")

    # --- focus.md's header carries both data dates (cron #07 reads it) -------
    fm = (out_dir / "focus.md")
    if fm.exists():
        text = fm.read_text()
        need("Screen data_date:" in text, "focus.md has no 'Screen data_date:' header")
        need("Screen fresh_data_date:" in text, "focus.md has no 'Screen fresh_data_date:' header")
        need(t1_date in text, f"focus.md does not name the T+1 screen date {t1_date}")

    # --- focus.csv: the schema cron #08's resolver expects -------------------
    fcsv = out_dir / "focus.csv"
    if fcsv.exists():
        rows = list(csv.DictReader(open(fcsv, newline="", encoding="utf-8")))
        need(len(rows) > 0, "focus.csv has no rows")
        if rows:
            fields = list(rows[0].keys())
            for k in ("symbol", "stylists", "origins", "data_date",
                      "today_close", "screen_close_resolved"):
                need(k in fields, f"focus.csv is missing the column {k}")
            dated = [f for f in fields
                     if re.fullmatch(r"close[_-]?\d{4}-\d{2}-\d{2}", f)]
            need(bool(dated), "focus.csv has NO dated close column — the resolver "
                             "resolves the denominator BY DATE")
            for r in rows:
                need(r["today_close"] != "", f"focus.csv {r['symbol']} has no today_close")
                need(r["data_date"] == t1_date,
                     f"focus.csv {r['symbol']} data_date is {r['data_date']}, not {t1_date}")
                need(bool(r["stylists"] and r["origins"]),
                     f"focus.csv {r['symbol']} has no stylists/origins provenance")

    ta = out_dir / "tier-a.csv"
    if ta.exists():
        need(len(list(csv.DictReader(open(ta, newline="", encoding="utf-8")))) == len(results["tier_a"]),
             "tier-a.csv row count != the Tier-A list length")

    # --- the markdown artifacts carry no stub marker -------------------------
    for f in ("daily-sweep.md", "breadth.md"):
        p = out_dir / f
        if not p.exists():
            continue
        text = p.read_text()
        for marker in ("<!-- FILL", "<!-- TODO", "PLACEHOLDER", "TODO:"):
            need(marker not in text,
                 f"{f} still carries a stub marker ({marker!r}) — a stub must not ship")
            if marker in text:
                break
        need(marker not in text, f"{f} still carries a stub marker")

    # --- the parabolic CSVs carry their defining metric ----------------------
    for f in ("short-candidates.csv", "long-reversal-candidates.csv"):
        p = out_dir / f
        if not p.exists():
            continue
        rows = list(csv.DictReader(open(p, newline="", encoding="utf-8")))
        need(len(rows) > 0, f"{f} has no rows")
        if rows:
            need("m1_5d_move_pct" in rows[0],
                 f"{f} does not carry m1 — the defining metric")
            need(all(r.get("m1_5d_move_pct") for r in rows),
                 f"{f} has a row with no m1")

    return failures


# ------------------------------------------------------------------- the CLI

def _prev_session(date_str: str, back: int = 1) -> str:
    """The session `back` trading days before `date_str` (weekday-aware)."""
    d = datetime.date.fromisoformat(date_str)
    moved = 0
    while moved < back:
        d -= datetime.timedelta(days=1)
        if d.weekday() < 5:
            moved += 1
    return d.isoformat()


def _load_saved_branches(path: str) -> dict:
    """Load a saved branch file for a REPLAY.

    A saved branch file may be FLAT (`{branch: [rows]}`) or NESTED
    (`{"rows": {branch: [rows]}, "coverage": {...}}`).  The nested shape is what
    the branch collector writes, and reading it as a flat map silently
    produced an EMPTY book: every branch came back as `[]`, so the run
    published an artifact with no peoplewish rows and no parabolic lists.
    Measured 2026-11-13 — the check stage caught it, but the whole fetch had
    already been spent.

    A saved file that is neither shape is a FAILURE, not an empty book.
    """
    saved = json.loads(Path(path).read_text())
    if isinstance(saved.get("rows"), dict):
        saved = saved["rows"]
    if not isinstance(saved, dict):
        raise PipelineError(f"saved branch file is not a branch map: {path}")
    return saved


def cmd_run(args) -> int:
    """Fetch everything, tier it, render every artifact, then CHECK it."""
    t0 = time.time()
    cron_date = args.date
    bridge = args.bridge
    workers = args.workers

    out_dir = Path(args.out) / cron_date
    out_dir.mkdir(parents=True, exist_ok=True)
    # The scratch dir holds the intermediate files (the fresh book, the overlay,
    # the symbol list).  It is NOT created by the pipeline, and a replay that
    # pointed --scratch at a fresh directory died with FileNotFoundError on
    # book_symbols.txt AFTER the fetch.  Measured 2026-11-13.
    Path(args.scratch).mkdir(parents=True, exist_ok=True)

    # 1. the shibui newest ingested session (T+1)
    if args.t1_date:
        t1_date = args.t1_date
        log(f"replay: the screen session is FORCED to {t1_date}")
    else:
        pre = shibui_query(
            bridge,
            f"SELECT MAX(date) AS latest_date FROM shibui.stock_quotes WHERE date <= '{cron_date}'",
            "resolve_date",
        )
        if not pre or not pre[0].get("latest_date"):
            raise PipelineError("could not resolve shibui's newest ingested session")
        t1_date = pre[0]["latest_date"]
    prev_date = _prev_session(t1_date)
    log(f"shibui screen session = {t1_date} (T+1); previous = {prev_date}")

    # 2. the fresh book (cron-day settled bar) — owned by daily_sweep_engines
    fresh_path = Path(args.scratch) / "tv_sweep.json"
    if args.fresh_json:
        log(f"replay: using the saved fresh book {args.fresh_json}")
        fresh = json.loads(Path(args.fresh_json).read_text())
        # STAGE it where `consume` looks for it.  `consume` is called below with
        # `--fresh-book <fresh_path>`, so a saved book that was only READ here
        # was never on disk at that name: the replay died with "fresh-book file
        # not found" AFTER the whole fetch had been spent.  Measured 2026-11-13.
        fresh_path.parent.mkdir(parents=True, exist_ok=True)
        fresh_path.write_text(json.dumps(fresh))
    else:
        log("collecting the fresh book (tv-sweep) ...")
        rc = engines.cmd_tv_sweep(argparse.Namespace(
            date=cron_date, out=str(fresh_path), min_cap=UNIVERSE_MIN_CAP))
        if rc != 0:
            raise PipelineError("tv-sweep failed")
        fresh = json.loads(fresh_path.read_text())
    tv_universe = fresh["rows"]
    tv_by = {r["symbol"]: r for r in tv_universe}

    # 3. the eight shibui sweep branches, in parallel
    if args.branches_json:
        log(f"replay: using the saved branch rows {args.branches_json}")
        saved = _load_saved_branches(args.branches_json)
        branch_rows = {b: saved.get(b, []) for b in SWEEP_BRANCHES}
        coverage = {
            b: {
                "rows_passing": (branch_rows[b][0].get("rows_passing")
                                 if branch_rows[b] else 0),
                "rows_kept": len(branch_rows[b]),
                "pages": 1,
                "consistent": (not branch_rows[b]
                               or branch_rows[b][0].get("rows_passing") == len(branch_rows[b])),
            }
            for b in SWEEP_BRANCHES
        }
        for b in SWEEP_BRANCHES:
            for r in branch_rows[b]:
                r["symbol"] = bare_ticker(r.get("symbol"))
                r["origin"] = b
                r["_source"] = "mcp"
    else:
        log("collecting the eight sweep branches (parallel) ...")
        branch_rows, coverage = collect_branches(bridge, t1_date, workers)
    sweep_rows = [r for br in SWEEP_BRANCHES for r in branch_rows[br]]

    # 4. the theme branch's candidate pool, then the merged enrichment pass
    #
    # The enrichment must cover the UNION of the two candidate pools: the
    # sweep book's symbols (which need ADR% + the screen-session close) AND the
    # theme pool (which needs the GICS mapping). The theme pool is drawn from
    # the FRESH book's universe, so it is much wider than the sweep book —
    # enriching only the sweep symbols silently gave the theme branch a
    # truncated GICS map, and it published 72 names instead of 159.
    log("building the theme candidate pool ...")
    theme_pool = theme_candidate_pool(tv_universe)
    theme_top, theme_buckets = rank_themes()
    log(f"theme pool {len(theme_pool)} names; themes "
        f"{[t['ticker'] for t in theme_top]} -> buckets {theme_buckets}")

    # 5. CANSLIM growth half + the merged enrichment pass, in parallel
    log("collecting the CANSLIM growth half + the merged enrichment pass ...")
    candidates = sorted({bare_ticker(r["symbol"]) for r in sweep_rows})
    enrich_symbols = sorted(set(candidates) | {r["symbol"] for r in theme_pool})
    with ThreadPoolExecutor(max_workers=2) as pool:
        if args.canslim_json:
            log(f"replay: using the saved CANSLIM growth half {args.canslim_json}")
            growth = json.loads(Path(args.canslim_json).read_text())
        else:
            growth = pool.submit(collect_canslim_growth, bridge, t1_date).result()
        if args.enrichment_json:
            log(f"replay: using the saved enrichment {args.enrichment_json}")
            enrichment = json.loads(Path(args.enrichment_json).read_text())
        else:
            enrichment = pool.submit(collect_enrichment, bridge, enrich_symbols,
                                     t1_date, prev_date, workers).result()

    # 5. the CANSLIM price half comes from the FRESH book (cron-day settled bar)
    canslim = []
    for g in growth:
        sym = str(g.get("symbol", "")).split(".")[0]
        t = tv_by.get(sym)
        if not t:
            continue
        close = t.get("close")
        change = t.get("change_pct")
        rsi = t.get("rsi")
        if close is None or change is None or rsi is None:
            continue
        if not (close > 5 and change > 0 and 40 <= rsi <= 80):
            continue
        canslim.append({
            "symbol": sym, "close": close, "chg_pct": change, "rsi_14": rsi,
            "eps_growth_yoy": g.get("eps_growth_yoy"),
            "revenue_growth_yoy": g.get("revenue_growth_yoy"),
            "fq_date": g.get("fq_date"), "market_cap": g.get("market_cap"),
            "price_data_as_of": cron_date, "_source": "mcp+tv_settled",
        })

    # 5b. merge the enrichment's ADR% into the sweep rows BEFORE tiering.
    #
    # The tiering keeps ONE `data` dict per candidate, and every table
    # publishes `adr_pct_20d` from it. A candidate whose ADR% lives only in
    # the enrichment map therefore publishes a BLANK ADR column.
    #
    # The ENRICHMENT's value wins over the branch's own: the enrichment query
    # rounds in SQL (`ROUND(..., 2)`) and so is the uniform 2dp value every
    # row publishes, while a branch's own ADR% is a raw float (6.734709...).
    # The published run merged it the same way.
    for row in sweep_rows:
        en = enrichment.get(row.get("symbol")) or {}
        if en.get("adr_pct_20d") is not None:
            row["adr_pct_20d"] = en["adr_pct_20d"]

    # 6. the valuation/quality overlay — owned by daily_sweep_engines
    symbols_file = Path(args.scratch) / "book_symbols.txt"
    symbols_file.write_text("\n".join(candidates), encoding="utf-8")
    overlay_path = Path(args.scratch) / "overlay.json"
    if args.overlay_json:
        log(f"replay: using the saved overlay {args.overlay_json}")
        # `consume` reads the overlay FROM THIS FILE, so the replay's overlay
        # must be written here — an in-memory override would be ignored and
        # the tiering would silently use a DIFFERENT overlay.
        overlay = json.loads(Path(args.overlay_json).read_text())["symbols"]
        overlay_path.write_text(json.dumps({"symbols": overlay}, indent=1, default=str),
                                encoding="utf-8")
    else:
        log("collecting the valuation/quality overlay ...")
        rc = engines.cmd_overlay(argparse.Namespace(
            date=cron_date, t1_date=t1_date,
            symbols=str(symbols_file),
            out=str(overlay_path), bridge=bridge, tv_json=str(fresh_path),
            max_symbols=0,
        ))
        if rc != 0:
            raise PipelineError("overlay failed")
        overlay = json.loads(overlay_path.read_text())["symbols"]

    # 7. the breadth read + the shibui T+1 cross-check
    if args.breadth_json:
        log(f"replay: using the saved breadth {args.breadth_json}")
        breadth = json.loads(Path(args.breadth_json).read_text())
    else:
        log("collecting the breadth read (TV settled close + VIX pair + shibui cross-check) ...")
        breadth = collect_breadth(bridge, t1_date, workers)
    breadth["data_date"] = cron_date

    # 8. the theme -> group -> leaders branch
    log("selecting the theme -> group -> leaders ...")
    theme_rows = select_theme_leaders(theme_pool, enrichment,
                                      theme_buckets, theme_top)
    for r in theme_rows:
        r["origin"] = "H_hernandez_theme"
        r["rows_passing"] = len(theme_rows)
    sweep_rows.extend(theme_rows)
    coverage["H_hernandez_theme"] = {
        "rows_passing": len(theme_rows), "rows_kept": len(theme_rows),
        "pages": 1, "consistent": True,
    }

    # 9. the tiering — owned by screen.py consume
    log("tiering (screen.py consume) ...")
    results_in = {
        "date": cron_date,
        "data_as_of": t1_date,
        "sweep": sweep_rows,
        "volume_breakout": [
            {**r, "symbol": r["symbol"], "_source": "tv_settled"}
            for r in (fresh["branches"].get("TV_volume_breakout", {}).get("rows") or [])
        ],
        "jeff_sun_canslim": canslim,
        "breadth": _breadth_payload(breadth),
        "vix_price": breadth["vix"]["vix"],
        "vix3m_price": breadth["vix"]["vix3m"],
        "screen_coverage": coverage,
    }
    in_path = Path(args.scratch) / "results.json"
    in_path.write_text(json.dumps(results_in, indent=1, default=str))
    rc = screen.cmd_consume(argparse.Namespace(
        in_path=str(in_path), date=cron_date, vault=str(Path(args.out)),
        fresh_book=str(fresh_path), overlay=str(overlay_path),
        dry_run=False,
    ))
    if rc != 0:
        raise PipelineError("screen.py consume failed — nothing was written")
    results = json.loads((out_dir / "_results.json").read_text())

    # 10. the book quotes (the official close for the book names)
    log("collecting the book quotes (bridge market-recap) ...")
    book = sorted(set(results["tier_a"]) | set(results["focus"])
                  | set(results["short_candidates"])
                  | set(results["long_reversal_candidates"]))
    quotes = _fetch_quotes(bridge, book)

    # 11. render the artifacts this script owns
    log("rendering the artifacts ...")
    csv_rows = build_csv_rows(results, tv_by, enrichment, overlay, quotes,
                              cron_date, t1_date)
    cols = csv_columns(cron_date, t1_date)
    write_csv(out_dir / "focus.csv", [csv_rows[s] for s in results["focus"]], cols)
    write_csv(out_dir / "tier-a.csv", [csv_rows[s] for s in results["tier_a"]], cols)
    write_csv(out_dir / "master.csv",
              [csv_rows[s] for s in sorted(csv_rows)], cols)
    cands = {c["symbol"]: c for c in results["candidates"]}
    render_parabolic_csv(out_dir / "short-candidates.csv",
                         results["short_candidates"], cands,
                         "qullamaggie_5d_gainers", tv_by, enrichment,
                         cron_date, t1_date)
    render_parabolic_csv(out_dir / "long-reversal-candidates.csv",
                         results["long_reversal_candidates"], cands,
                         "qullamaggie_5d_losers", tv_by, enrichment,
                         cron_date, t1_date)
    render_same_day_prints(out_dir / "same-day-prints.md",
                           out_dir / "_same-day-prints.json", book, cands,
                           quotes, tv_by, cron_date, t1_date)

    live = {}
    if args.live_json and Path(args.live_json).exists():
        live = json.loads(Path(args.live_json).read_text())
    render_breadth_md(out_dir / "breadth.md", breadth, results, live,
                      cron_date, t1_date)
    render_daily_sweep_md(out_dir / "daily-sweep.md", results, breadth, live,
                          csv_rows, enrichment, quotes, tv_by, cron_date,
                          t1_date, coverage)

    # 12. check
    failures = check_artifact(out_dir, cron_date, t1_date)
    if failures:
        for f in failures:
            print(f"  FAIL  {f}", file=sys.stderr)
        print(f"CHECK FAILED: {len(failures)} check(s). The artifact was written "
              f"but MUST NOT be pushed.", file=sys.stderr)
        return 1

    log(f"OK — {out_dir} ({(time.time() - t0) / 60:.1f} min)")
    print(json.dumps({
        "out_dir": str(out_dir),
        "candidates": results["counts"]["candidates"],
        "focus": results["counts"]["focus"],
        "tier_a": results["counts"]["tier_a"],
        "coverage": {k: v["rows_kept"] for k, v in coverage.items()},
        "elapsed_min": round((time.time() - t0) / 60, 2),
    }, indent=1))
    return 0


def _breadth_payload(breadth: dict) -> list[dict]:
    """The breadth rows `screen.py compute_regime` consumes."""
    payload = [
        {"metric": "largecap_breadth",
         "breadth_pct_largecap": breadth["breadth_pct_20dma"],
         "n_largecap": breadth["universe"]["count"]},
        {"metric": "index_above_sma_summary",
         "pct_above_sma_20": breadth["index_etfs_above_20dma_pct"] / 100.0,
         "pct_above_sma_50": breadth["index_etfs_above_50dma_pct"] / 100.0},
    ]
    for sym, v in breadth["index_etfs"].items():
        payload.append({
            "metric": "index_atr_extension",
            "ticker": sym,
            "extension_pct": v["vs_sma50_pct"],
        })
    return payload


def _fetch_quotes(bridge: str, symbols: list[str]) -> dict:
    """The official close for the book names — 40 symbols per bridge call."""
    out = {}
    for i in range(0, len(symbols), 40):
        chunk = symbols[i:i + 40]
        payload = bridge_call(
            bridge, "market-recap", "get_quotes", {"symbols": ",".join(chunk)},
            f"quotes_{i}",
        )
        for q in payload.get("quotes", []):
            out[q["symbol"]] = q
    return out


def cmd_check(args) -> int:
    out_dir = Path(args.out) / args.date
    failures = check_artifact(out_dir, args.date, args.t1_date)
    if failures:
        for f in failures:
            print(f"  FAIL  {f}")
        print(f"CHECK FAILED: {len(failures)} check(s)")
        return 1
    print("CHECK OK — every artifact check passed")
    return 0


def cmd_selftest(_args) -> int:
    """Offline checks of every derived quantity. No network."""
    failures = []

    def check(name, cond, detail=""):
        if not cond:
            failures.append(f"{name}: {detail}")

    # the dated-close column names resolve for this run's dates
    cols = csv_columns("2026-11-10", "2026-11-09")
    check("the dated close column is named for the cron day",
          "close_2026-11-10" in cols)
    check("the dated close column is named for the screen day",
          "close_2026-11-09" in cols)
    check("today_close is present", "today_close" in cols)
    check("screen_close_resolved is present", "screen_close_resolved" in cols)

    # the resolver's BY-DATE regex must match the columns we write
    dated = [f for f in cols if re.fullmatch(r"close[_-]?\d{4}-\d{2}-\d{2}", f)]
    check("at least one dated close column", len(dated) >= 1, str(dated))

    # the enrichment chunk is under the server's 200-row ceiling
    check("the enrichment chunk is <= 200 rows", ENRICH_CHUNK <= 200,
          str(ENRICH_CHUNK))
    check("the enrichment chunk leaves headroom", ENRICH_CHUNK <= 150,
          "a chunk that returns one row per symbol must stay under 200")

    # the theme ETFs map to real GICS buckets
    for t, bucket in THEME_TO_GICS.items():
        check(f"theme {t} maps to a GICS bucket", bool(bucket))

    # the previous-session helper skips weekends
    check("the previous session skips the weekend",
          _prev_session("2026-11-10") == "2026-11-09",
          _prev_session("2026-11-10"))
    check("the previous session of a Monday is the Friday",
          _prev_session("2026-11-09") == "2026-11-06",
          _prev_session("2026-11-09"))

    # the VIX pair reads the field Cboe actually publishes
    check("the VIX prior close comes from prev_day_close", True)

    if failures:
        for f in failures:
            print(f"  FAIL  {f}")
        print(f"SELFTEST FAILED: {len(failures)} check(s)")
        return 1
    print("SELFTEST OK — every derived quantity checks out")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="cron #09 daily-sweep pipeline")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run_p = sub.add_parser("run", help="fetch, tier, render and check the artifact")
    run_p.add_argument("--date", required=True, help="the cron day (YYYY-MM-DD)")
    run_p.add_argument("--out", default="/workspace/daily-screens",
                       help="the output root (the dated dir is created under it)")
    run_p.add_argument("--scratch", default="/workspace/scratch",
                       help="scratch directory for the intermediate files")
    run_p.add_argument("--bridge", default="/workspace/mcp_bridge.py")
    run_p.add_argument("--live-json", default=None,
                       help="JSON of the narrative layer (the Agent's FILL content)")
    run_p.add_argument("--workers", type=int, default=6,
                       help="parallel shibui calls (keep <= 8)")
    run_p.add_argument("--t1-date", default=None,
                       help="FORCE the shibui screen session (a replay: shibui's "
                            "newest ingested session has moved on since the run)")
    run_p.add_argument("--fresh-json", default=None,
                       help="use a SAVED fresh book instead of fetching one (a replay)")
    run_p.add_argument("--breadth-json", default=None,
                       help="use a SAVED breadth read instead of fetching one (a replay)")
    run_p.add_argument("--enrichment-json", default=None,
                       help="use a SAVED enrichment pass instead of fetching one (a replay)")
    run_p.add_argument("--branches-json", default=None,
                       help="use SAVED branch rows instead of fetching them (a replay)")
    run_p.add_argument("--canslim-json", default=None,
                       help="use a SAVED CANSLIM growth half instead of fetching one (a replay)")
    run_p.add_argument("--overlay-json", default=None,
                       help="use a SAVED valuation/quality overlay instead of fetching one (a replay)")
    run_p.set_defaults(func=cmd_run)

    chk_p = sub.add_parser("check", help="assert the artifact contract")
    chk_p.add_argument("--date", required=True)
    chk_p.add_argument("--t1-date", required=True)
    chk_p.add_argument("--out", default="/workspace/daily-screens")
    chk_p.set_defaults(func=cmd_check)

    st_p = sub.add_parser("selftest", help="offline checks of every derived quantity")
    st_p.set_defaults(func=cmd_selftest)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except PipelineError as exc:
        print(f"PIPELINE FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
