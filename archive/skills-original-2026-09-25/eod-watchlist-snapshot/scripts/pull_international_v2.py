"""
pull_international_v2.py — orchestrator for international EOD pull with caching,
enrichment, and movers-refresh.

Implements optimizations #1, #2, #4, #6, #7 from the cron-cost analysis:

  #1 universe cache — only re-pull screener every N days; daily fires use
     stock_prices against the cached ticker list (single round-trip per region)
  #2 filter clause — pass `filters=[...]` to screener to shrink universe
  #4 Yahoo enrichment — fill volume/pe/sector for top N by market cap
  #6 movers refresh — Tue-Fri, only re-pull tickers with |change_pct| > 3%
     yesterday; forward-fill the rest (skipped if yesterday's CSV missing)
  #7 shibui enrichment — pull volume/pe/sector from shibui for cross-listed
     tickers (CA/JP/TW/AU/DE/FR/IT — ~246+28+25+27 + small EU subsets)

Public API
----------
    orchestrator = IntlPullOrchestrator(
        csv_root=Path("..."),
        universe_cache=UniverseCache(...),
        shibui_resolver=ShibuiCrossListedResolver(...),
    )

    # Daily cron flow:
    region_data = {"au": [...rows from stock_prices...], ...}
    yahoo_enrich = {"au": {ticker: {volume, pe_ratio, sector}}, ...}
    orchestrator.assemble_all(region_data, yahoo_enrich=yahoo_enrich)
"""
from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Iterable, Optional

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))

from universe_cache import UniverseCache
from yahoo_enrich import YahooEnricher, extract_enrichment, merge_enrichment


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


class ShibuiCrossListedResolver:
    """Resolves cross-listed international tickers (CA/JP/TW/AU/EU) via shibui.

    Returns a dict {tv_ticker: {"volume", "pe_ratio", "sector", "market_cap"}}
    for any ticker that exists in shibui's general_info + valuation tables.
    Stub: the cron agent injects real shibui data; this class only validates
    and indexes it.
    """

    def __init__(self, shibui_data: dict | None = None):
        self.data = shibui_data or {}

    def resolve(self, tv_ticker: str) -> dict | None:
        return self.data.get(tv_ticker)

    def enrich_many(self, tv_tickers: Iterable[str]) -> dict[str, dict]:
        return {tv: self.resolve(tv) for tv in tv_tickers if self.resolve(tv)}


class MoversDetector:
    """Detects which tickers moved significantly in yesterday's CSV.

    Used by #6 (movers refresh on Tue-Fri): instead of pulling all ~14k rows,
    only pull tickers whose previous-day |change_pct| exceeded the threshold.
    Forward-fill non-mover rows from yesterday.
    """

    def __init__(self, csv_root: Path, threshold: float = 3.0, yesterday: date | None = None):
        self.csv_root = Path(csv_root)
        self.threshold = threshold
        self.yesterday = yesterday or (datetime.now().date() - timedelta(days=1))

    def find_movers(self, region: str) -> list[str] | None:
        """Return tickers that moved >threshold yesterday, or None if no CSV."""
        path = self.csv_root / region / f"{self.yesterday.isoformat()}.csv"
        if not path.exists():
            return None
        tickers = []
        with open(path, encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                try:
                    cp = float(row.get("change_pct") or 0)
                except ValueError:
                    continue
                if abs(cp) >= self.threshold:
                    tickers.append(row["ticker"])
        return tickers

    def load_previous_rows(self, region: str) -> dict[str, dict] | None:
        """Return ticker→row mapping from yesterday's CSV, or None if missing."""
        path = self.csv_root / region / f"{self.yesterday.isoformat()}.csv"
        if not path.exists():
            return None
        out = {}
        with open(path, encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                if "ticker" in row:
                    out[row["ticker"]] = row
        return out


class IntlPullOrchestrator:
    """Orchestrates daily international EOD pulls.

    Wires together:
      - UniverseCache (decides which tickers to pull today)
      - YahooEnricher (optional, fills volume/pe/sector for top N)
      - ShibuiCrossListedResolver (optional, fills volume/pe/sector from shibui)
      - MoversDetector (optional, Tue-Fri movers-only refresh + forward-fill)
    """

    DEFAULT_TOP_N_YAHOO = 500
    DEFAULT_MOVERS_THRESHOLD = 3.0

    def __init__(self, csv_root: Path,
                 universe_cache: UniverseCache | None = None,
                 yahoo_enricher: YahooEnricher | None = None,
                 shibui_resolver: ShibuiCrossListedResolver | None = None,
                 movers_detector: MoversDetector | None = None,
                 top_n_yahoo: int = DEFAULT_TOP_N_YAHOO,
                 movers_threshold: float = DEFAULT_MOVERS_THRESHOLD,
                 today: date | None = None):
        self.csv_root = Path(csv_root)
        self.universe_cache = universe_cache
        self.yahoo_enricher = yahoo_enricher or YahooEnricher()
        self.shibui_resolver = shibui_resolver or ShibuiCrossListedResolver()
        self.movers_detector = movers_detector
        self.top_n_yahoo = top_n_yahoo
        self.movers_threshold = movers_threshold
        self.today = today or datetime.now().date()

    # ---------- core assemble logic ----------

    def assemble_region(self, region: str, prices_rows: list[dict],
                        yahoo_enrichments: dict[str, dict] | None = None,
                        shibui_data: dict | None = None,
                        forward_fill_rows: dict[str, dict] | None = None,
                        cached_tickers: list[str] | None = None,
                        ) -> list[list[str]]:
        """Merge screener/stock_prices data + enrichments into final CSV rows.

        Args:
            region: e.g. "eu-de"
            prices_rows: list of {ticker, description, price, open, high, low,
                currency, exchange, change_percent, market_cap, dividend_yield}
                from stock_screener or stock_prices.
            yahoo_enrichments: {tv_ticker: {volume, pe_ratio, sector}} from
                Yahoo MCP compare_stocks calls (typically top N by market cap).
            shibui_data: {tv_ticker: {volume, pe_ratio, sector, market_cap}} from
                shibui-finance SQL (typically cross-listed intl tickers).
            forward_fill_rows: {tv_ticker: row_dict} from previous day's CSV for
                tickers not refreshed today (Tue-Fri movers mode).
            cached_tickers: full cached universe for the region. Used in movers
                mode to know which tickers to forward-fill (those not in
                prices_rows today).

        Returns: list of rows ready to write to CSV (each row is a list[str]).
        """
        yahoo_enrichments = yahoo_enrichments or {}
        shibui_data = shibui_data or {}
        forward_fill_rows = forward_fill_rows or {}

        rows: list[list[str]] = []
        fresh_tickers = {raw.get("ticker") for raw in prices_rows if raw.get("ticker")}

        # First, emit fresh rows for every ticker in prices_rows
        for raw in prices_rows:
            tv = raw.get("ticker", "")
            if not tv:
                continue

            shibui_row = shibui_data.get(tv)
            yahoo_row = yahoo_enrichments.get(tv)

            volume = (shibui_row or {}).get("volume") or (yahoo_row or {}).get("volume")
            pe_ratio = (shibui_row or {}).get("pe_ratio") or (yahoo_row or {}).get("pe_ratio")
            sector = (shibui_row or {}).get("sector") or (yahoo_row or {}).get("sector")

            rows.append([
                self.today.isoformat(),
                tv,
                raw.get("description", ""),
                fmt(raw.get("open")),
                fmt(raw.get("high")),
                fmt(raw.get("low")),
                fmt(raw.get("price")),
                fmt(volume),
                fmt(raw.get("change_percent")),
                fmt(raw.get("market_cap")),
                fmt(pe_ratio),
                sector or "",
                raw.get("currency", ""),
                raw.get("exchange", ""),
            ])

        # Second, in movers mode, emit forward-filled rows for cached tickers
        # that weren't refreshed today. Skip if no forward_fill_rows available.
        if forward_fill_rows and cached_tickers:
            for tv in cached_tickers:
                if tv in fresh_tickers:
                    continue
                if tv not in forward_fill_rows:
                    continue
                prior = forward_fill_rows[tv]
                # Forward-fill from yesterday; change_pct recomputed as 0
                # (yesterday's change is now today's reference)
                shibui_row = shibui_data.get(tv)
                yahoo_row = yahoo_enrichments.get(tv)
                volume = (shibui_row or {}).get("volume") or (yahoo_row or {}).get("volume") or prior.get("volume", "")
                pe_ratio = (shibui_row or {}).get("pe_ratio") or (yahoo_row or {}).get("pe_ratio") or prior.get("pe_ratio", "")
                sector = (shibui_row or {}).get("sector") or (yahoo_row or {}).get("sector") or prior.get("sector", "")

                rows.append([
                    self.today.isoformat(),
                    tv,
                    prior.get("name", ""),
                    prior.get("open", ""),
                    prior.get("high", ""),
                    prior.get("low", ""),
                    prior.get("close", ""),
                    fmt(volume) if not isinstance(volume, str) else volume,
                    "0.0",
                    prior.get("market_cap", ""),
                    fmt(pe_ratio) if not isinstance(pe_ratio, str) else pe_ratio,
                    sector,
                    prior.get("currency", ""),
                    prior.get("exchange", ""),
                ])

        return rows

    def assemble_all(self, region_data: dict[str, list[dict]],
                     region_yahoo_enrich: dict[str, dict[str, dict]] | None = None,
                     region_shibui_data: dict[str, dict[str, dict]] | None = None,
                     movers_regions: set[str] | None = None,
                     ) -> dict[str, int]:
        """Assemble and write CSVs for all regions.

        Args:
            region_data: {region: [rows from stock_prices today]}
            region_yahoo_enrich: {region: {tv_ticker: {volume, pe_ratio, sector}}}
            region_shibui_data: {region: {tv_ticker: {volume, pe_ratio, sector, ...}}}
            movers_regions: set of regions running in movers mode (forward-fill
                non-mover tickers from yesterday). If None and movers_detector
                is set, all regions default to movers mode.

        Returns: dict mapping region → row count written.
        """
        region_yahoo_enrich = region_yahoo_enrich or {}
        region_shibui_data = region_shibui_data or {}

        out = {}
        for region, prices_rows in region_data.items():
            yahoo = region_yahoo_enrich.get(region, {})
            shibui = region_shibui_data.get(region, {})

            # Forward-fill from previous day's CSV if movers mode is on
            ff = None
            cached = None
            is_movers = movers_regions is None or region in movers_regions
            if is_movers and self.movers_detector:
                ff = self.movers_detector.load_previous_rows(region) or {}
                # Cached universe = tickers we know about; if cache is loaded,
                # use it, otherwise fall back to yesterday's tickers
                if self.universe_cache and self.universe_cache.is_loaded(region):
                    cached = self.universe_cache.get(region)

            rows = self.assemble_region(
                region, prices_rows,
                yahoo_enrichments=yahoo,
                shibui_data=shibui,
                forward_fill_rows=ff,
                cached_tickers=cached,
            )
            if rows:
                self._write_csv(region, rows)
                out[region] = len(rows)
        return out

    # ---------- top-N helper for Yahoo enrichment ----------

    def select_top_n(self, region: str, prices_rows: list[dict], n: int | None = None
                     ) -> list[str]:
        """Pick the top-N tickers by market cap for Yahoo enrichment."""
        n = n or self.top_n_yahoo
        sorted_rows = sorted(
            prices_rows,
            key=lambda r: -(r.get("market_cap") or 0),
        )
        return [r["ticker"] for r in sorted_rows[:n] if r.get("ticker")]

    # ---------- file output ----------

    def _write_csv(self, region: str, rows: list[list[str]]) -> None:
        """Atomic write: tmp file + rename so a half-written CSV can't poison
        the historical_eod/<region>/YYYY-MM-DD.csv on crash mid-write."""
        out_dir = self.csv_root / region
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{self.today.isoformat()}.csv"
        tmp_path = out_path.with_suffix(".csv.tmp")
        with open(tmp_path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(HEADER)
            w.writerows(rows)
        tmp_path.replace(out_path)


# ---------- helper for cron agent: build Yahoo enrichment batches ----------

def build_yahoo_enrichment_plan(region: str, prices_rows: list[dict],
                                enricher: YahooEnricher | None = None,
                                top_n: int = 500) -> dict:
    """Returns a dict with {batches: [[(tv, yt), ...]], tv_to_yahoo: {tv: yt}}.

    The cron agent calls this to get the Yahoo call plan, makes the MCP calls,
    then passes the results back to assemble_region as `yahoo_enrichments`.
    """
    enricher = enricher or YahooEnricher()
    sorted_rows = sorted(prices_rows, key=lambda r: -(r.get("market_cap") or 0))
    top_tv_tickers = [r["ticker"] for r in sorted_rows[:top_n] if r.get("ticker")]
    tv_to_yahoo = dict(enricher.to_yahoo_tickers(top_tv_tickers))
    # Only keep mappable ones for batch plan
    batchable = [(tv, yt) for tv, yt in tv_to_yahoo.items() if yt is not None]
    batches = []
    cur = []
    for tv, yt in batchable:
        cur.append((tv, yt))
        if len(cur) >= 10:
            batches.append(cur)
            cur = []
    if cur:
        batches.append(cur)
    return {
        "batches": batches,
        "tv_to_yahoo": tv_to_yahoo,
        "unmappable": list(enricher.unmappable),
    }
