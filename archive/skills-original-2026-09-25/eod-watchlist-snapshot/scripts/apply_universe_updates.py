"""Apply multi-pass screener updates to the universe cache.

Reads a JSON file mapping region -> [ticker_dicts] and calls
UniverseCache.merge() for each region. Use this when running additional
screen_stocks calls (3 ASC-sorted market_cap range passes) AFTER the
initial stock_screener refresh, so the new long-tail names are appended
without overwriting the existing top-2000.

Input format:
  {"jp": [{"symbol": "TSE:9999", "market_cap_basic": 1.5e9, "exchange": "TSE"}, ...],
   "eu-de": [...]}

Usage:
  python apply_universe_updates.py <updates.json> \\
    --universe-cache-root "C:\\path\\to\\research\\universe_cache" \\
    [--today YYYY-MM-DD]
"""
from __future__ import annotations
import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from universe_cache import UniverseCache


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("updates_json", help="JSON file with {region: [ticker_dicts]}")
    parser.add_argument("--universe-cache-root", required=True,
                        help="Path to universe_cache root")
    parser.add_argument("--today", default=None,
                        help="Override today (YYYY-MM-DD); defaults to local date")
    args = parser.parse_args()

    updates_path = Path(args.updates_json)
    if not updates_path.exists():
        print(f"ERROR: {updates_path} not found", file=sys.stderr)
        sys.exit(1)

    updates = json.load(open(updates_path, encoding="utf-8"))
    today = (datetime.strptime(args.today, "%Y-%m-%d").date()
             if args.today else date.today())

    cache = UniverseCache(Path(args.universe_cache_root), today=today)

    # Track per-region added counts for the summary
    summary: dict[str, dict] = {}

    for region, rows in updates.items():
        # Convert screener rows (symbol/market_cap_basic/exchange) to our
        # internal format (ticker/market_cap/exchange)
        normalized = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            ticker = r.get("symbol") or r.get("ticker")
            if not ticker:
                continue
            normalized.append({
                "ticker": ticker,
                "market_cap": r.get("market_cap_basic", r.get("market_cap")),
                "exchange": r.get("exchange"),
                "added_by_pass": r.get("added_by_pass", "multi_pass"),
            })

        before, added = cache.merge(region, normalized,
                                     source_suffix="_multi_pass_apply")
        summary[region] = {"received": len(rows), "added": added, "existing": before}

    # Always run dedupe after merging — same-company, different-exchange
    # rows pile up across multi-pass calls
    for region in updates:
        removed = cache.dedupe_primary_listing(region)
        summary[region]["deduped"] = removed

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
