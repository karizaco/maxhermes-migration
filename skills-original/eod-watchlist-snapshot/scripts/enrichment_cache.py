"""
enrichment_cache.py — per-ticker TTL cache for Yahoo volume/pe/sector enrichment.

The v2 flow calls `mcp__yahoo-finance__compare_stocks` 800 times/day (16 regions
* 500 top-by-market-cap tickers / 10-per-batch) to fill volume/pe_ratio/sector
columns that the TradingView screener strips. That dominates the cron compute
budget.

Most of those calls return data that hasn't changed since yesterday — pe_ratio
and sector rarely change in a week, and volume from yesterday is good enough
for backtesting. So we cache per-ticker with field-specific TTLs:

  volume    — TTL 1 day  (changes daily; cheap to refresh)
  pe_ratio  — TTL 30 days (changes on earnings; basically static otherwise)
  sector    — TTL 30 days (effectively permanent; sector reclassifications are rare)

On day 1 we still pay 800 calls. By day 30, only ~50 calls/day remain
(essentially the daily volume refresh for the top-500 + any IPOs from the past
week).

Public API
----------
    cache = EnrichmentCache(
        root=Path("research/enrichment_cache"),
        ttl_days={"volume": 1, "pe_ratio": 30, "sector": 30},
    )
    cache.get(ticker) -> {"volume": int|None, "pe_ratio": float|None,
                          "sector": str|None, "_fresh": {field, ...}}
    cache.set(ticker, {"volume": ..., "pe_ratio": ..., "sector": ...},
              fields=["volume"])  # partial-update
    cache.stale_fields(ticker, today) -> set[str]  # which fields need refresh
    cache.bulk_stale_fields(tickers, today) -> {ticker: set[str]}
    cache.status() -> dict  # diagnostic report

Storage
-------
    <root>/cache.json — single dict keyed by ticker. Per-field `last_fetched`
    timestamps let us partial-refresh (volume can refresh independently of
    sector). Approx 500 bytes per ticker * 8000 tickers = ~4 MB total.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable

DEFAULT_TTL = {"volume": 1, "pe_ratio": 30, "sector": 30}


class EnrichmentCache:
    """Per-ticker TTL cache for Yahoo enrichment fields."""

    def __init__(self, root: Path,
                 ttl_days: dict[str, int] | None = None,
                 today: date | None = None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.ttl = dict(ttl_days) if ttl_days else dict(DEFAULT_TTL)
        self.today = today or datetime.now().date()
        self._path = self.root / "cache.json"

    # ---------- low-level ----------

    def _read(self) -> dict:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def _write(self, data: dict) -> None:
        # Atomic write: tmp then rename, so a half-written file doesn't poison
        # the cache on crash.
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
        tmp.replace(self._path)

    # ---------- public API ----------

    def get(self, ticker: str) -> dict:
        """Return cached enrichment for `ticker`. Schema:
            {"volume": ..., "pe_ratio": ..., "sector": ...,
             "_last_fetched": {"volume": "YYYY-MM-DD", ...},
             "_fresh": {"volume": bool, ...}}

        `_fresh` indicates which fields are still within TTL on `self.today`.
        Missing fields or missing ticker → empty dict with all fields stale.
        """
        data = self._read()
        entry = data.get(ticker, {})
        fields = {f: entry.get(f) for f in self.ttl}
        last = entry.get("_last_fetched", {})
        fresh = {}
        for f, ttl in self.ttl.items():
            lf = last.get(f)
            if not lf:
                fresh[f] = False
                continue
            try:
                fetched = datetime.fromisoformat(lf).date()
            except ValueError:
                fresh[f] = False
                continue
            fresh[f] = (self.today - fetched) < timedelta(days=ttl)
        return {**fields, "_last_fetched": last, "_fresh": fresh}

    def set(self, ticker: str, fields: dict, only: Iterable[str] | None = None
            ) -> None:
        """Store selected fields for `ticker`. If `only` is given, only those
        field names are updated (others keep their prior value + freshness).
        """
        allowed = set(only) if only else set(self.ttl)
        unknown = allowed - set(self.ttl)
        if unknown:
            raise ValueError(f"unknown enrichment fields: {unknown}")

        data = self._read()
        entry = dict(data.get(ticker, {}))
        last = dict(entry.get("_last_fetched", {}))
        for f in allowed:
            if fields.get(f) is not None:
                entry[f] = fields[f]
                last[f] = self.today.isoformat()
        entry["_last_fetched"] = last
        data[ticker] = entry
        self._write(data)

    def bulk_set(self, fields_by_ticker: dict[str, dict],
                  only: Iterable[str] | None = None) -> None:
        """Bulk version of set() — single read + single write."""
        allowed = set(only) if only else set(self.ttl)
        unknown = allowed - set(self.ttl)
        if unknown:
            raise ValueError(f"unknown enrichment fields: {unknown}")

        data = self._read()
        for ticker, fields in fields_by_ticker.items():
            entry = dict(data.get(ticker, {}))
            last = dict(entry.get("_last_fetched", {}))
            for f in allowed:
                if fields.get(f) is not None:
                    entry[f] = fields[f]
                    last[f] = self.today.isoformat()
            entry["_last_fetched"] = last
            data[ticker] = entry
        self._write(data)

    def stale_fields(self, ticker: str) -> set[str]:
        """Return the set of field names that need refreshing for `ticker`."""
        entry = self.get(ticker)
        return {f for f, ok in entry["_fresh"].items() if not ok}

    def bulk_stale_fields(self, tickers: Iterable[str]) -> dict[str, set[str]]:
        """Bulk version of stale_fields() — single read pass."""
        data = self._read()
        out: dict[str, set[str]] = {}
        for ticker in tickers:
            entry = data.get(ticker, {})
            last = entry.get("_last_fetched", {})
            stale = set()
            for f, ttl in self.ttl.items():
                lf = last.get(f)
                if not lf:
                    stale.add(f)
                    continue
                try:
                    fetched = datetime.fromisoformat(lf).date()
                except ValueError:
                    stale.add(f)
                    continue
                if (self.today - fetched) >= timedelta(days=ttl):
                    stale.add(f)
            out[ticker] = stale
        return out

    def invalidate(self, ticker: str) -> None:
        """Force-refresh next time: drop the entry entirely."""
        data = self._read()
        data.pop(ticker, None)
        self._write(data)

    def size(self) -> int:
        """Count of cached tickers."""
        return len(self._read())

    def status(self) -> dict:
        """Diagnostic report: count, field-freshness histogram, sample tickers."""
        data = self._read()
        n = len(data)
        fresh_counts = {f: 0 for f in self.ttl}
        for entry in data.values():
            last = entry.get("_last_fetched", {})
            for f, ttl in self.ttl.items():
                lf = last.get(f)
                if not lf:
                    continue
                try:
                    fetched = datetime.fromisoformat(lf).date()
                except ValueError:
                    continue
                if (self.today - fetched) < timedelta(days=ttl):
                    fresh_counts[f] += 1
        return {
            "cached_tickers": n,
            "fresh_count": fresh_counts,
            "stale_count": {f: n - fresh_counts[f] for f in self.ttl},
            "ttl_days": dict(self.ttl),
            "path": str(self._path),
        }

    # Exchange priority for dedupe. Lower index = preferred. Mirrors the
    # PRIMARY_LISTING map in UniverseCache — kept inline here to avoid an
    # import cycle. Update both in lockstep when adding new exchanges.
    PRIMARY_EXCHANGE_PRIORITY = [
        "TSE", "TWSE", "TSX", "XETR", "MIL", "AMS", "EPA", "BME", "BSE",
        "VIE", "LIS", "ISE", "HEL", "CPH", "ATHEX", "ASX",
        "NEO", "TSXV", "CSE",
        "FWB", "TRADEGATE", "GETTEX", "MUN", "DUS", "HAM", "HAN", "SWB",
        "LSX", "LS", "BER", "STU",
        "EUROTLX", "EURONEXT",
        "NAG", "FSE", "SAPSE", "TPEX",
    ]

    def dedupe_primary_listing(self) -> tuple[int, int]:
        """Merge Yahoo enrichment entries for the same company under the
        primary-listing ticker. Mirrors UniverseCache.dedupe_primary_listing.

        Returns (removed_count, merged_field_count).
        """
        from collections import defaultdict
        data = self._read()
        priority = {e: i for i, e in enumerate(self.PRIMARY_EXCHANGE_PRIORITY)}

        groups: dict[str, list[str]] = defaultdict(list)
        for tv in data:
            if ":" not in tv:
                continue
            _, sym = tv.split(":", 1)
            groups[sym].append(tv)

        removed = 0
        merged = 0
        for sym, tickers in list(groups.items()):
            if len(tickers) <= 1:
                continue
            canonical = min(tickers,
                            key=lambda t: (priority.get(t.split(":", 1)[0], 9999), t))
            canonical_data = data[canonical]
            for tv in tickers:
                if tv == canonical:
                    continue
                sec = data[tv]
                # Merge per-field timestamps
                cf = canonical_data.setdefault("_last_fetched", {})
                sf = sec.get("_last_fetched", {})
                if isinstance(sf, dict):
                    for field, date in sf.items():
                        if field not in cf or date > cf.get(field, ""):
                            cf[field] = date
                # Fill in any missing fields
                for k, v in sec.items():
                    if k == "_last_fetched":
                        continue
                    if k not in canonical_data or canonical_data.get(k) is None:
                        if v is not None:
                            canonical_data[k] = v
                            merged += 1
                del data[tv]
                removed += 1

        self._write(data)
        return (removed, merged)
