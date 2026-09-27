#!/usr/bin/env python3
"""
Reusable international EOD pull — reads MCP stock_screener artifacts from
the latest session and writes one CSV per region under
C:/Users/admin/.minimax/projects/coding-shared/research/historical_eod/<region>/<DATE>.csv

Also seeds the universe cache (universe_cache.py) so future cron runs can
use stock_prices against the cached ticker list instead of re-pulling the
screener. See pull_international_v2.py for the cached flow.

Designed to be run AFTER the agent has executed stock_screener MCP calls for
each region. The agent invokes stock_screener with country={australia,japan,
taiwan,canada,germany,france,italy,spain,netherlands,belgium,austria,portugal,
ireland,finland,denmark,greece}, limit=2000, exclude_otc=true, stock_type=common.
Each tool call produces TWO .txt artifacts (clean + envelope). This script
reads them, dedupes by ticker, writes per-region CSVs, AND saves the universe
cache as a side-effect.

Usage from the cron routine's agent prompt:
  python "C:/Users/admin/.minimax/agents/mavis/skills/eod-watchlist-snapshot/scripts/pull_international.py"

Optional: pass EOD_DATE env var to override today's date (for backfills).
"""
import csv
import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from universe_cache import UniverseCache

ARTIFACT_DIR = Path(
    r"C:\Users\admin\.minimax\v2\sessions"
)
CSV_ROOT = Path(
    r"C:\Users\admin\.minimax\projects\coding-shared\research\historical_eod"
)
UNIVERSE_CACHE_ROOT = Path(
    r"C:\Users\admin\.minimax\projects\coding-shared\research\universe_cache"
)

# Country → region_label mapping (used to assign each artifact to its region)
COUNTRY_TO_REGION = {
    "australia": "au", "japan": "jp", "taiwan": "tw", "canada": "ca",
    "germany": "eu-de", "france": "eu-fr", "italy": "eu-it", "spain": "eu-es",
    "netherlands": "eu-nl", "belgium": "eu-be", "austria": "eu-at",
    "portugal": "eu-pt", "ireland": "eu-ie", "finland": "eu-fi",
    "denmark": "eu-dk", "greece": "eu-gr",
}

DATE = os.environ.get("EOD_DATE") or datetime.now().strftime("%Y-%m-%d")
HEADER = ["date", "ticker", "name", "open", "high", "low", "close",
          "volume", "change_pct", "market_cap", "pe_ratio", "sector",
          "currency", "exchange"]


def fmt(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return str(v).lower()
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if v == int(v):
            return str(int(v))
        return f"{v:.4f}".rstrip("0").rstrip(".")
    return str(v)


def parse_artifact(path):
    """Three formats in the wild:
       (A) pretty-printed multi-line JSON: {"country":..., "rows":[{...}]}
       (B) MCP envelope single-line:        {"content":[{"type":"text","text":"<A>"}]}
       (C) chunked JSONL:                   {"type":"tool_output_chunks",...}
    Returns list of dict rows, or [] on failure."""
    raw = path.read_text(encoding="utf-8", errors="replace").lstrip("\ufeff").strip()
    if not raw:
        return []

    if raw.startswith('{"type":"tool_output_chunks"'):
        rows = []
        for ln in raw.split("\n"):
            ln = ln.strip()
            if not ln or ln.startswith('{"type":"tool_output_chunks"'):
                continue
            try:
                chunk = json.loads(ln)
                text = chunk.get("text", "")
                if text:
                    try:
                        rows.extend(json.loads(text))
                    except json.JSONDecodeError:
                        pass
            except json.JSONDecodeError:
                continue
        return rows

    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return []

    if isinstance(obj, dict) and "rows" in obj:
        return obj.get("rows", [])

    if isinstance(obj, dict):
        for block in obj.get("content", []):
            if block.get("type") == "text":
                try:
                    inner = json.loads(block["text"])
                    if isinstance(inner, dict) and "rows" in inner:
                        return inner["rows"]
                    if isinstance(inner, list):
                        return inner
                except json.JSONDecodeError:
                    continue
    return []


def discover_dedup(cutoff_min=30):
    """Find all stock_screener artifacts from the last `cutoff_min` minutes.
    Each tool call produces TWO .txt files (clean + envelope). Group by
    first-16-char prefix and pick the smaller (clean) one per call.
    Returns list of file paths."""
    if not ARTIFACT_DIR.exists():
        return []
    session_dirs = sorted(
        [d for d in ARTIFACT_DIR.iterdir() if d.is_dir()],
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )
    if not session_dirs:
        return []
    latest = session_dirs[0]
    outputs = latest / "reports" / "tool-outputs"
    if not outputs.exists():
        return []

    cutoff = datetime.now() - timedelta(minutes=cutoff_min)
    by_prefix = {}
    for f in outputs.glob("*.txt"):
        try:
            mtime = datetime.fromtimestamp(f.stat().st_mtime)
            sz = f.stat().st_size
        except OSError:
            continue
        if mtime < cutoff:
            continue
        # Filter: stock_screener responses are 30KB-1.5MB.
        if sz < 30_000 or sz > 1_500_000:
            continue
        prefix = f.stem.split("-")[0][:16]
        if prefix not in by_prefix or sz < by_prefix[prefix].stat().st_size:
            by_prefix[prefix] = f

    return sorted(by_prefix.values(), key=lambda f: f.stat().st_mtime)


def main():
    files = discover_dedup()
    if not files:
        print("ERROR: no stock_screener artifacts found", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(files)} deduped stock_screener files", file=sys.stderr)

    region_batches = {}
    for f in files:
        rows = parse_artifact(f)
        if not rows:
            continue
        head = f.read_text(encoding="utf-8", errors="replace")[:500]
        m = re.search(r'"country"\s*:\s*"([^"]+)"', head)
        if not m:
            print(f"  WARN: cannot find country in {f.name}", file=sys.stderr)
            continue
        country = m.group(1)
        region = COUNTRY_TO_REGION.get(country)
        if not region:
            print(f"  WARN: unknown country '{country}' in {f.name}", file=sys.stderr)
            continue
        region_batches.setdefault(region, []).append(rows)

    # Seed the universe cache as a side-effect (opt #1) so future cron runs
    # can use stock_prices against the cached ticker list.
    cache = UniverseCache(UNIVERSE_CACHE_ROOT, ttl_days=7,
                          today=datetime.strptime(DATE, "%Y-%m-%d").date())
    cache_seeded = []

    written = []
    for region, batches in region_batches.items():
        rows = [r for batch in batches for r in batch]
        if not rows:
            continue
        # Dedupe by ticker — TradingView screener ignores offset, so multi-call
        # pages overlap (returns same top-N by market_cap). Keep first occurrence.
        seen = set()
        deduped = []
        for r in rows:
            t = r.get("ticker", "")
            if t and t not in seen:
                seen.add(t)
                deduped.append(r)

        # ----- Write CSV (unchanged behavior) -----
        out_dir = CSV_ROOT / region
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{DATE}.csv"
        with open(out_path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(HEADER)
            for r in deduped:
                w.writerow([
                    DATE,
                    r.get("ticker", ""),
                    r.get("description", ""),
                    fmt(r.get("open")),
                    fmt(r.get("high")),
                    fmt(r.get("low")),
                    fmt(r.get("price")),
                    "",  # volume — not in screener
                    fmt(r.get("change_percent")),
                    fmt(r.get("market_cap")),
                    "",  # pe_ratio — not in screener
                    "",  # sector — not in screener
                    r.get("currency", ""),
                    r.get("exchange", ""),
                ])
        size_kb = out_path.stat().st_size / 1024
        n_dup = len(rows) - len(deduped)
        dup_msg = f" (deduped {n_dup})" if n_dup else ""
        print(f"  WROTE {out_path}  ({len(deduped)} rows{dup_msg}, {size_kb:.1f} KB)", file=sys.stderr)
        written.append((region, len(deduped), str(out_path)))

        # ----- Seed universe cache -----
        # Only seed if it's missing or stale. The screener pulled everything
        # for this region today, so we treat today's run as a fresh capture.
        try:
            # Keep full metadata (ticker + market_cap + exchange) so v2 can
            # sort by market cap when picking top-N for Yahoo enrichment.
            ticker_rows = [
                {
                    "ticker": r.get("ticker", ""),
                    "market_cap": r.get("market_cap"),
                    "exchange": r.get("exchange", ""),
                }
                for r in deduped
            ]
            cache.refresh(
                region, ticker_rows,
                source="tradingview_screener",
                filters={"auto_seeded_from": "pull_international.py"},
            )
            cache_seeded.append((region, len(ticker_rows)))
            print(f"  SEEDED cache  {region:10s}  ({len(ticker_rows)} tickers)", file=sys.stderr)
        except Exception as e:
            print(f"  WARN: failed to seed cache for {region}: {e}", file=sys.stderr)

    print(f"\n=== SUMMARY ===", file=sys.stderr)
    for region, n, path in written:
        print(f"  {region:10s}  {n:6d}  {path}", file=sys.stderr)
    total = sum(n for _, n, _ in written)
    print(f"  {'TOTAL':10s}  {total:6d}", file=sys.stderr)
    print(f"\nCache seeded for {len(cache_seeded)} regions.", file=sys.stderr)


if __name__ == "__main__":
    main()
