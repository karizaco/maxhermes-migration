#!/usr/bin/env python3
"""Same-day prints for a candidate list — the "what did it do today" column.

Why
---
The 18:30 ET sweep runs on shibui's most recent *ingested* close, which is
normally one session behind the cron day (shibui is T+1). Every screen metric
— ADR, relative strength, velocity, moving averages, volume — therefore
describes yesterday's tape. The trader, however, is acting on today's.

This script fetches today's official 4:00 PM close and change for every
candidate from the Nasdaq public quote API and writes them next to the screen
output, so a Tier-A list carries both "why it was picked" (yesterday's
metrics) and "what it did since" (today's print).

It is deliberately a separate step: the screen is Tier-1 shibui SQL, and this
is a Tier-2 enrichment that must never be allowed to fail the run.

Usage
-----
    python scripts/same_day_prints.py --symbols AAPL,MSFT,NVDA
    python scripts/same_day_prints.py --from-csv daily-screens/2026-10-28/master.csv \
        --out-dir daily-screens/2026-10-28
    python scripts/same_day_prints.py --symbols AAPL --bridge /path/to/mcp_bridge.py

Outputs
-------
    <out-dir>/_same-day-prints.json   {ticker: {close, change_pct, volume, ...}}
    <out-dir>/same-day-prints.md      a markdown table
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
NASDAQ_INFO = "https://api.nasdaq.com/api/quote/{sym}/info?assetclass={ac}"


def _num(v):
    """Nasdaq returns '$26.52' / '+1.41%' as strings."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("$", "").replace(",", "").replace("%", "")
    try:
        return float(s)
    except ValueError:
        return None


def _parse_trade_date(raw: str | None) -> str | None:
    """'Nov 2, 2026' -> '2026-11-02'."""
    if not raw:
        return None
    for fmt in ("%b %d, %Y", "%b %d, %Y %I:%M %p", "%Y-%m-%d"):
        try:
            import datetime as dt
            return dt.datetime.strptime(raw.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _fetch_one(sym: str) -> tuple[str, dict | None]:
    """Fetch one symbol.

    Nasdaq returns the 4:00 PM close in `secondaryData` while the after-hours
    session is running, but `secondaryData` is null once the market is closed
    and before the next open — then `primaryData` holds the last trade, which
    may be a PRIOR session. The record therefore carries the trade date and a
    `session` label, so a caller can tell today's print from a stale one.
    """
    for asset_class in ("stocks", "etf"):
        url = NASDAQ_INFO.format(sym=sym.upper(), ac=asset_class)
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=25) as resp:
                payload = json.loads(resp.read().decode())
        except Exception:
            continue
        data = payload.get("data") or {}
        primary = data.get("primaryData") or {}
        secondary = data.get("secondaryData") or {}

        close = _num(secondary.get("lastSalePrice"))
        change = _num(secondary.get("percentageChange"))
        session = "official_close"
        if close is None:
            close = _num(primary.get("lastSalePrice"))
            change = _num(primary.get("percentageChange"))
            session = "last_trade"
        if close is None:
            continue

        key_stats = data.get("keyStats") or {}
        day_range = key_stats.get("dayrange") or {}
        rng = day_range.get("value") if isinstance(day_range, dict) else None
        return sym.upper(), {
            "close": close,
            "change_pct": change,
            "volume": _num(primary.get("volume")),
            "after_hours": _num(primary.get("lastSalePrice")) if session == "official_close" else None,
            "day_range": rng,
            "company": data.get("companyName"),
            "asset_class": asset_class,
            "market_status": data.get("marketStatus"),
            "session": session,
            "trade_date": _parse_trade_date(
                secondary.get("lastTradeTimestamp") or primary.get("lastTradeTimestamp")
            ),
        }
    return sym.upper(), None


def find_bridge(explicit: str | None) -> Path | None:
    """Locate mcp_bridge.py — it is not needed for the Nasdaq path but the
    script prints the resolved shibui date when one is available."""
    cands = []
    if explicit:
        cands.append(Path(explicit))
    if os.environ.get("MCP_BRIDGE_PATH"):
        cands.append(Path(os.environ["MCP_BRIDGE_PATH"]))
    here = Path(__file__).resolve()
    cands.append(here.parent.parent.parent / "_shared" / "mcp_bridge.py")
    cands.append(here.parent / "mcp_bridge.py")
    for c in cands:
        if c.exists():
            return c
    return None


def shibui_latest_date(bridge: Path | None) -> str | None:
    """Resolve shibui's latest ingested date (best effort, never fatal)."""
    if bridge is None:
        return None
    args_file = Path("/tmp/_same_day_resolve.json")
    args_file.write_text(json.dumps({
        "query": "SELECT MAX(date) AS latest_date FROM shibui.stock_quotes",
        "user_prompt": "resolve the latest ingested date for a same-day print column",
    }))
    try:
        out = subprocess.run(
            ["python3", str(bridge), "shibui", "stock_data_query", str(args_file)],
            capture_output=True, text=True, timeout=120,
        ).stdout
        rows = json.loads(out)
        if isinstance(rows, list) and rows:
            return rows[0].get("latest_date")
    except Exception:
        return None
    return None


def load_symbols(args) -> list[str]:
    syms: list[str] = []
    if args.symbols:
        syms += [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    if args.from_csv:
        with open(args.from_csv, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                for key in ("ticker", "symbol", "Ticker", "Symbol"):
                    if row.get(key):
                        syms.append(str(row[key]).strip().split(".")[0].split("/")[0].upper())
                        break
    # de-duplicate, preserve order
    seen, out = set(), []
    for s in syms:
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Fetch same-day official prints for a candidate list")
    p.add_argument("--symbols", default="", help="comma-separated tickers")
    p.add_argument("--from-csv", default=None, help="CSV with a ticker/symbol column")
    p.add_argument("--out-dir", default=".", help="where to write the JSON + markdown")
    p.add_argument("--bridge", default=None, help="path to mcp_bridge.py (for the shibui date stamp)")
    p.add_argument("--data-date", default=None, help="the date the screen was built on")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    syms = load_symbols(args)
    if not syms:
        print("no symbols given (use --symbols or --from-csv)", file=sys.stderr)
        return 2

    bridge = find_bridge(args.bridge)
    data_date = args.data_date or shibui_latest_date(bridge)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    prints: dict[str, dict] = {}
    failures = 0
    with ThreadPoolExecutor(max_workers=12) as ex:
        for sym, rec in ex.map(_fetch_one, syms):
            if rec:
                prints[sym] = rec
            else:
                failures += 1

    payload = {
        "data_date": data_date,
        "requested": len(syms),
        "ok": len(prints),
        "failed": failures,
        "prints": prints,
    }
    (out_dir / "_same-day-prints.json").write_text(json.dumps(payload, indent=2))

    lines = [
        "# Same-day prints",
        "",
        f"_Screen data date {data_date or 'unknown'}. Prints for the candidate list._",
        "",
        "A print is the official 4:00 PM close when the market is in its after-hours session "
        "(`official_close`); otherwise it is the most recent trade (`last_trade`), and the "
        "`Session` column says which one it is — a `last_trade` row dated before the cron "
        "day is a stale print, not today's.",
        "",
        "| Ticker | Close | Change | Volume | Session | Print date | Company |",
        "|---|---|---|---|---|---|---|",
    ]
    for sym in syms:
        rec = prints.get(sym)
        if not rec:
            lines.append(f"| {sym} | — | — | — | — | _no quote_ |")
            continue
        change = rec.get("change_pct")
        change_txt = f"{change:+.2f}%" if change is not None else "—"
        volume = rec.get("volume") or 0
        lines.append(
            f"| **{sym}** | {rec['close']:.2f} | {change_txt} | {volume:,.0f} | "
            f"{rec.get('session') or '—'} | {rec.get('trade_date') or '—'} | "
            f"{rec.get('company') or '—'} |"
        )
    lines += [
        "",
        f"_{len(prints)} of {len(syms)} symbols priced"
        + (f"; {failures} had no quote (delisted, halted, or not a listed security)."
           if failures else "."),
        "",
    ]
    (out_dir / "same-day-prints.md").write_text("\n".join(lines))

    if not args.quiet:
        print(f"same-day prints: {len(prints)}/{len(syms)} priced, {failures} missing "
              f"-> {out_dir / 'same-day-prints.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
