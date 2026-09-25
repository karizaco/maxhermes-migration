"""
universe_cache.py — per-region ticker universe cache for EOD market snapshot.

Implements optimization #1 from the cron-cost analysis: cache the ticker list
per region and refresh it on a TTL (default 7 days) instead of re-pulling via
the TradingView stock_screener on every cron fire. This:

  - Eliminates the screener's "ignores offset" multi-page overlap problem
  - Shrinks the per-cron MCP budget from 16 stock_screener calls to 16
    stock_prices calls (cheaper, single round-trip per region)
  - Lets us keep the full 4935-row US universe via shibui without 25 calls
    (run shibui universe query once a month, cache the ticker list)

Public API
----------
    cache = UniverseCache(root=Path("..."), ttl_days=7)
    cache.get("eu-de") -> list[str] of tickers (cached or refreshed)
    cache.refresh("eu-de", tickers=..., fetched_at=..., source="tradingview_screener")
    cache.is_stale("eu-de") -> bool
    cache.invalidate("eu-de")

File layout
-----------
    <root>/<region>/meta.json — TTL + source + ticker count + last fetch
    <root>/<region>/tickers.json — list of {ticker, market_cap, exchange} dicts
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable


DEFAULT_TTL_DAYS = 7


class UniverseCache:
    """Per-region ticker universe cache with TTL."""

    def __init__(self, root: Path, ttl_days: int = DEFAULT_TTL_DAYS, today=None):
        self.root = Path(root)
        self.ttl_days = ttl_days
        self.today = today or datetime.now().date()

    # ---------- low-level helpers ----------

    def _dir(self, region: str) -> Path:
        d = self.root / region
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _meta_path(self, region: str) -> Path:
        return self._dir(region) / "meta.json"

    def _tickers_path(self, region: str) -> Path:
        return self._dir(region) / "tickers.json"

    def _read_meta(self, region: str) -> dict | None:
        p = self._meta_path(region)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None

    def _write_meta(self, region: str, meta: dict) -> None:
        self._meta_path(region).write_text(
            json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8"
        )

    # ---------- public API ----------

    def is_loaded(self, region: str) -> bool:
        """True if both meta + tickers files exist."""
        return self._meta_path(region).exists() and self._tickers_path(region).exists()

    def is_stale(self, region: str) -> bool:
        """True if cache is missing OR past TTL."""
        meta = self._read_meta(region)
        if not meta:
            return True
        fetched = datetime.fromisoformat(meta["fetched_at"]).date()
        return (self.today - fetched) >= timedelta(days=self.ttl_days)

    def age_days(self, region: str) -> int | None:
        """Days since the cache was last refreshed, or None if missing."""
        meta = self._read_meta(region)
        if not meta:
            return None
        fetched = datetime.fromisoformat(meta["fetched_at"]).date()
        return (self.today - fetched).days

    def get(self, region: str) -> list[str]:
        """Return cached tickers for region (sorted). Empty if not loaded."""
        p = self._tickers_path(region)
        if not p.exists():
            return []
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
        # Support both formats: list[str] or list[{ticker, market_cap, ...}]
        if data and isinstance(data[0], dict):
            return [r["ticker"] for r in data]
        return list(data)

    def get_full(self, region: str) -> list[dict]:
        """Return cached ticker dicts (with market_cap + exchange) for region."""
        p = self._tickers_path(region)
        if not p.exists():
            return []
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
        if data and isinstance(data[0], str):
            # Plain-list format → no metadata, return as minimal dicts
            return [{"ticker": t} for t in data]
        return list(data)

    def refresh(self, region: str, tickers: Iterable[dict] | Iterable[str],
                source: str = "tradingview_screener",
                filters: dict | None = None) -> int:
        """Overwrite the cache for `region` with the given tickers.

        `tickers` may be either:
          - list[str] of tickers (no metadata)
          - list[dict] each with at least {ticker, market_cap?, exchange?}

        `filters` is recorded in meta for traceability; values are coerced to
        JSON-safe types (sets→sorted lists, tuples→lists, anything else→str).

        Returns the count written.
        """
        rows = list(tickers)
        # Normalize to list[dict]
        if rows and isinstance(rows[0], str):
            rows = [{"ticker": t} for t in rows]
        # Sort by market_cap desc (when present), then by ticker asc
        rows.sort(key=lambda r: (-(r.get("market_cap") or 0), r.get("ticker", "")))

        self._tickers_path(region).write_text(
            json.dumps(rows, indent=1), encoding="utf-8"
        )
        meta = {
            "fetched_at": self.today.isoformat(),
            "count": len(rows),
            "source": source,
            "filters": self._jsonify(filters) if filters else {},
            "ttl_days": self.ttl_days,
        }
        self._write_meta(region, meta)
        return len(rows)

    @staticmethod
    def _jsonify(obj):
        """Recursively convert obj to JSON-safe types (sets/tuples → lists)."""
        if isinstance(obj, dict):
            return {k: UniverseCache._jsonify(v) for k, v in obj.items()}
        if isinstance(obj, (set, frozenset)):
            return sorted(UniverseCache._jsonify(v) for v in obj)
        if isinstance(obj, (list, tuple)):
            return [UniverseCache._jsonify(v) for v in obj]
        if isinstance(obj, (str, int, float, bool)) or obj is None:
            return obj
        return str(obj)

    def invalidate(self, region: str) -> None:
        """Delete cache files for `region` (forces refresh on next get)."""
        for p in (self._meta_path(region), self._tickers_path(region)):
            if p.exists():
                p.unlink()

    # ---------- multi-pass support ----------
    # Long-tail capture: when the single-call stock_screener hits its 2000-row cap,
    # the cache is just "top 2000 by market cap" for that region. The basic
    # screen_stocks tool accepts a `filters` array with market_cap_basic partitioning,
    # so we can run 3 disjoint ASC-sorted passes and union the long-tail names.
    #
    # 2026-09-24: empirically the gain was +1,200 names across 4 capped regions
    # (jp +201, tw +201, ca +216, eu-de +582). The orchestrator should call this
    # method on any region where the previous single-call fetch returned >= 2000 rows.
    # Sort order ASC is critical: it captures the BOTTOM of each market_cap bucket,
    # which is guaranteed new vs. the top-2000 cached.

    DEFAULT_PASSES = [
        ("A_micro", 0,                200_000_000),     # market_cap <= 200M USD
        ("B_small", 200_000_000,      1_000_000_000),   # 200M-1B USD
        ("C_mid",   1_000_000_000,    10_000_000_000),  # 1B-10B USD
    ]

    def merge(self, region: str, new_rows: Iterable[dict],
              source_suffix: str = "_multi_pass",
              fetch_now: bool = True) -> tuple[int, int]:
        """Append long-tail ticker rows to the cache without overwriting.

        Existing tickers (by `ticker` field) are NOT overwritten; their market_cap
        and exchange stay as-is. New rows are appended in the order given, then the
        file is re-sorted by market_cap desc.

        Args:
            region: e.g. "jp", "eu-de"
            new_rows: iterable of dicts with at least {ticker, market_cap?, exchange?}
            source_suffix: appended to existing `source` field in meta (e.g.
                           "tradingview_screener_multi_pass")
            fetch_now: update `fetched_at` to today. Set False to preserve the
                       original fetch timestamp (useful when only extending).

        Returns:
            (existing_count_before, added_count) — tuple.
        """
        existing = self.get_full(region)
        existing_tickers = {row["ticker"] for row in existing if "ticker" in row}
        before = len(existing_tickers)

        added = 0
        for row in new_rows:
            ticker = row.get("ticker") if isinstance(row, dict) else None
            if not ticker:
                continue
            if ticker in existing_tickers:
                continue
            existing.append(row)
            existing_tickers.add(ticker)
            added += 1

        if added > 0:
            # Re-sort by market_cap desc (or ticker asc when missing)
            existing.sort(key=lambda r: (-(r.get("market_cap") or 0), r.get("ticker", "")))
            self._tickers_path(region).write_text(
                json.dumps(existing, indent=1), encoding="utf-8"
            )

        meta = self._read_meta(region) or {}
        if fetch_now or not meta:
            meta["fetched_at"] = self.today.isoformat()
        meta["count"] = len(existing)
        prev_source = meta.get("source", "tradingview_screener")
        if source_suffix not in prev_source:
            meta["source"] = prev_source + source_suffix
        meta["multi_pass"] = True
        meta["ttl_days"] = self.ttl_days
        self._write_meta(region, meta)
        return (before, added)

    def mark_delisted(self, region: str, tickers: Iterable[str],
                      reason: str = "missing_data") -> int:
        """Flag tickers as delisted. Does NOT remove them — adds `delisted: true`
        so the orchestrator can skip them on next price-pull.

        Use when a ticker has been N/A in price/volume for >= N consecutive
        sessions (typically 30+). The delisted field is sticky and survives
        multi-pass merges; call `clear_delisted()` to reset.

        Args:
            region: e.g. "jp", "eu-de"
            tickers: iterable of ticker strings to mark
            reason: free-text reason, recorded on each ticker row

        Returns:
            Count actually marked (skips already-delisted).
        """
        wanted = set(tickers)
        if not wanted:
            return 0
        rows = self.get_full(region)
        marked = 0
        for row in rows:
            ticker = row.get("ticker")
            if ticker not in wanted:
                continue
            if row.get("delisted"):
                continue
            row["delisted"] = True
            row["delisted_reason"] = reason
            row["delisted_at"] = self.today.isoformat()
            marked += 1
        if marked > 0:
            self._tickers_path(region).write_text(
                json.dumps(rows, indent=1), encoding="utf-8"
            )
        return marked

    def clear_delisted(self, region: str) -> int:
        """Remove the delisted flag from all tickers in region.

        Use after a successful price-pull that revives a previously-marked
        ticker (e.g., resumed trading after halt). Returns count cleared.
        """
        rows = self.get_full(region)
        cleared = 0
        for row in rows:
            if row.get("delisted"):
                row.pop("delisted", None)
                row.pop("delisted_reason", None)
                row.pop("delisted_at", None)
                cleared += 1
        if cleared > 0:
            self._tickers_path(region).write_text(
                json.dumps(rows, indent=1), encoding="utf-8"
            )
        return cleared

    def mark_priority(self, region: str, tickers: Iterable[str]) -> int:
        """Flag tickers as priority (always included in enrichment top-N).

        Use for user watchlist tickers or any name that should be in the
        Yahoo enrichment batch regardless of market_cap rank. Priority tickers
        keep their flag across multi-pass merges; call `clear_priority()` to
        reset.

        Args:
            region: e.g. "jp", "eu-de"
            tickers: iterable of ticker strings to mark

        Returns:
            Count actually marked (skips already-priority).
        """
        wanted = set(tickers)
        if not wanted:
            return 0
        rows = self.get_full(region)
        marked = 0
        for row in rows:
            ticker = row.get("ticker")
            if ticker not in wanted:
                continue
            if row.get("priority"):
                continue
            row["priority"] = True
            marked += 1
        if marked > 0:
            self._tickers_path(region).write_text(
                json.dumps(rows, indent=1), encoding="utf-8"
            )
        return marked

    def clear_priority(self, region: str) -> int:
        """Remove the priority flag from all tickers in region. Returns count cleared."""
        rows = self.get_full(region)
        cleared = 0
        for row in rows:
            if row.get("priority"):
                row.pop("priority", None)
                cleared += 1
        if cleared > 0:
            self._tickers_path(region).write_text(
                json.dumps(rows, indent=1), encoding="utf-8"
            )
        return cleared

    def get_priority(self, region: str) -> list[str]:
        """Return ticker list of priority-flagged rows for region. Empty if none."""
        return [r["ticker"] for r in self.get_full(region) if r.get("priority")]

    def get_active(self, region: str) -> list[dict]:
        """Return cached ticker dicts with `delisted: true` filtered out."""
        return [r for r in self.get_full(region) if not r.get("delisted")]

    # Primary-listing priority. When the screener returns the same company under
    # multiple exchange variants (e.g. NVD on FWB/GETTEX/MUN/SWB all = Nvidia),
    # collapse to the most-preferred variant per region. 2026-09-24 scan found
    # 996 multi-listed tickers in CA and 596 in EU-DE — biggest savings.
    PRIMARY_LISTING = {
        "jp": ["TSE", "NAG", "FSE", "SAPSE"],
        "tw": ["TWSE", "TPEX"],
        "ca": ["TSX", "NEO", "TSXV", "CSE"],
        "eu-de": ["XETR", "FWB", "TRADEGATE", "GETTEX", "MUN", "DUS", "HAM",
                  "HAN", "SWB", "LSX", "LS", "BER", "STU"],
        "eu-it": ["MIL", "EUROTLX"],
        "eu-nl": ["AMS", "AS", "EURONEXT"],
        "eu-fr": ["EPA", "EURONEXT"],
        "eu-es": ["BME"],
        "eu-be": ["BSE", "BRU"],
        "eu-at": ["VIE"],
        "eu-pt": ["LIS"],
        "eu-ie": ["ISE", "Dublin"],
        "eu-fi": ["HEL"],
        "eu-dk": ["CPH"],
        "eu-gr": ["ATHEX", "ATH"],
        "au": ["ASX"],
    }

    def dedupe_primary_listing(self, region: str) -> int:
        """Collapse multi-listed tickers to one row per underlying company.

        The screener returns every exchange where a stock trades. Same company
        under different exchange prefixes are redundant for our purposes
        (EOD pricing, sector enrichment); one canonical row is enough.

        Uses PRIMARY_LISTING priority for the region. When the preferred exchange
        isn't present, picks the first variant by sorted symbol.

        Returns count of rows removed.
        """
        rows = self.get_full(region)
        priority = self.PRIMARY_LISTING.get(region, [])
        priority_index = {e: i for i, e in enumerate(priority)}

        # Group by underlying symbol (everything after the first ':')
        groups: dict[str, list[dict]] = {}
        for row in rows:
            ticker = row.get("ticker", "")
            if ":" not in ticker:
                continue
            exch, sym = ticker.split(":", 1)
            groups.setdefault(sym, []).append(row)

        kept: list[dict] = []
        removed = 0
        for sym, group in groups.items():
            if len(group) == 1:
                kept.append(group[0])
                continue
            # Sort by priority_index (lower = preferred), then by exchange string
            group.sort(key=lambda r: (
                priority_index.get(r.get("ticker", "").split(":", 1)[0], 999),
                r.get("ticker", "")
            ))
            kept.append(group[0])
            for dup in group[1:]:
                removed += 1
                # Track which exchanges were collapsed under this canonical row
                kept[-1].setdefault("also_listed_on", []).append(
                    dup.get("ticker", "")
                )

        if removed > 0:
            kept.sort(key=lambda r: (-(r.get("market_cap") or 0), r.get("ticker", "")))
            self._tickers_path(region).write_text(
                json.dumps(kept, indent=1), encoding="utf-8"
            )
            meta = self._read_meta(region) or {}
            meta.setdefault("dedupe_log", []).append({
                "at": self.today.isoformat(),
                "removed": removed,
                "method": "primary_listing_priority",
            })
            self._write_meta(region, meta)
        return removed

    def detect_delisting_candidates(self, region: str, csv_root: Path,
                                     lookback_days: int = 30,
                                     na_threshold: int = 25) -> list[str]:
        """Scan recent CSVs and return tickers that look delisted.

        Heuristic: a ticker is a delisting candidate when, in the last
        `lookback_days` days, its close price is N/A AND volume is N/A
        (or zero) for at least `na_threshold` days.

        Args:
            region: e.g. "eu-de"
            csv_root: parent dir containing `<region>/YYYY-MM-DD.csv`
            lookback_days: how many trailing days to consider
            na_threshold: how many of those must be N/A to flag

        Returns:
            List of ticker symbols that meet the threshold. Empty list when
            insufficient history (e.g., < lookback_days days available).
        """
        region_dir = Path(csv_root) / region
        if not region_dir.exists():
            return []
        # Find the most recent N CSV files
        files = sorted(region_dir.glob("*.csv"), reverse=True)[:lookback_days]
        if len(files) < lookback_days:
            return []  # not enough history to make a confident call

        from collections import defaultdict
        na_counts: dict[str, int] = defaultdict(int)
        for csv in files:
            seen_today: set[str] = set()
            for line in open(csv, encoding="utf-8"):
                line = line.strip()
                if not line or line.startswith("date,"):
                    continue
                parts = line.split(",")
                if len(parts) < 8:
                    continue
                ticker = parts[1]
                if ticker in seen_today:
                    continue  # avoid counting the same ticker twice if it appears in multiple rows
                seen_today.add(ticker)
                close = parts[6]
                vol = parts[7]
                if close in ("N/A", "", "null") and vol in ("N/A", "", "null", "0"):
                    na_counts[ticker] += 1

        return [t for t, n in na_counts.items() if n >= na_threshold]

    def detect_stale_for_yahoo_probe(self, region: str,
                                      probe_results: dict[str, dict],
                                      na_persistence_days: int = 3) -> list[str]:
        """Return tickers to consider delisted based on Yahoo probe results.

        `probe_results` maps ticker -> {"price": float|None, "volume": int|None,
        "market_state": str|None}. A ticker is flagged when:
          - price is None (Yahoo doesn't have it)
          - volume is None or 0
          - market_state is "CLOSED" or None
        The caller is responsible for the actual Yahoo MCP probe and for
        accumulating probe results over multiple sessions. This method just
        aggregates them into a candidate list.

        Args:
            region: e.g. "eu-de"
            probe_results: ticker -> last-N-days Yahoo probe observations
            na_persistence_days: how many of the last N probes must be N/A
        """
        candidates = []
        for ticker, results in probe_results.items():
            n = len(results)
            if n < na_persistence_days:
                continue
            na_count = sum(1 for r in results
                           if r.get("price") is None
                           and (r.get("volume") in (None, 0)))
            if na_count >= na_persistence_days:
                candidates.append(ticker)
        return candidates

    def set_isin(self, region: str, ticker_to_isin: dict[str, str]) -> int:
        """Set ISIN on ticker rows. Used by `dedupe_by_isin` for cross-region
        dedupe (companies dual-listed across regions share the same ISIN).

        `ticker_to_isin` maps ticker -> ISIN string. Returns count actually set
        (skips tickers not in cache).
        """
        rows = self.get_full(region)
        isin_map = {r.get("ticker"): r.get("isin") for r in rows}
        changed = 0
        for ticker, isin in ticker_to_isin.items():
            if ticker in isin_map and isin_map[ticker] != isin:
                # Update ISIN field
                for row in rows:
                    if row.get("ticker") == ticker:
                        row["isin"] = isin
                        changed += 1
                        break
        if changed:
            self._tickers_path(region).write_text(
                json.dumps(rows, indent=1), encoding="utf-8"
            )
        return changed

    def dedupe_by_isin(self, region_to_rows: dict[str, list[dict]],
                        primary_region_order: list[str] | None = None) -> int:
        """Cross-region dedupe using ISIN as the join key.

        Walks rows from multiple regions; for any ISIN that appears in 2+
        regions' rows, keeps one canonical and removes the rest. The
        `primary_region_order` controls which region wins on conflict
        (first match in the list). Default: prefer the region whose name
        comes first alphabetically (e.g., "eu-de" before "us" before "us-nyse").

        Returns count of cross-region duplicates removed. DOES NOT write
        to disk — caller is responsible for invoking `refresh()` on each
        region with the pruned rows.

        NOTE: requires `isin` field to be populated on at least some rows.
        Without ISIN, this method is a no-op.
        """
        if not primary_region_order:
            primary_region_order = sorted(region_to_rows.keys())

        # Build isin -> (region, ticker)
        isin_index: dict[str, list[tuple[str, str]]] = {}
        for region, rows in region_to_rows.items():
            for row in rows:
                isin = row.get("isin")
                if not isin:
                    continue
                isin_index.setdefault(isin, []).append((region, row.get("ticker")))

        # For each ISIN with duplicates, keep first by primary_region_order
        removed_total = 0
        for isin, occurrences in isin_index.items():
            if len(occurrences) <= 1:
                continue
            # Sort by primary_region_order
            occurrences.sort(key=lambda x: (
                primary_region_order.index(x[0]) if x[0] in primary_region_order else 999,
                x[1],
            ))
            # Keep first, mark rest as removed
            for region, ticker in occurrences[1:]:
                if region in region_to_rows:
                    region_to_rows[region] = [
                        r for r in region_to_rows[region]
                        if r.get("ticker") != ticker
                    ]
                    removed_total += 1
        return removed_total

    def status(self) -> dict:
        """Return a status report across all cached regions."""
        out = {}
        for d in sorted(self.root.iterdir()) if self.root.exists() else []:
            if not d.is_dir():
                continue
            region = d.name
            meta = self._read_meta(region)
            if not meta:
                out[region] = {"loaded": False}
                continue
            out[region] = {
                "loaded": True,
                "count": meta.get("count"),
                "fetched_at": meta.get("fetched_at"),
                "age_days": self.age_days(region),
                "stale": self.is_stale(region),
                "source": meta.get("source"),
                "filters": meta.get("filters", {}),
            }
        return out
