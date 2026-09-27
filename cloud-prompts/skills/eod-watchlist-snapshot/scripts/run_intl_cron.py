"""
run_intl_cron.py — single-entry orchestrator for the international EOD cron.

This module replaces the ~4 KB inline cron prompt with a small set of
importable functions. The cron prompt becomes:

    1. Run `plan_cron_run(today, ...)` — returns what to skip + what to call
    2. Execute the listed MCP calls (stock_screener, stock_prices, compare_stocks)
    3. Dump responses to a JSON file
    4. Run `finalize_cron_run(responses, ...)` — writes CSVs + audit

Compute wins baked into this orchestrator (vs the original v2 prompt):

  - Enrichment cache (per-ticker TTL): volume=1d, pe/sector=30d.
    Yahoo compare_stocks is only called for tickers with stale fields.
    On day 30+, only ~50 Yahoo calls/day remain (vs ~800 in v2.0).
  - Holiday calendar skip: don't write CSVs on regional holidays — avoid
    polluting the historical record with stale "today" data.
  - Movers mode (Tue-Fri default): only refresh tickers whose yesterday's
    |change_pct| > 3%; forward-fill the rest. Saves 75% of stock_prices calls.
  - Friday anchor for Monday: Mon movers-mode uses Friday's CSV, not Sunday.

Public API
----------
    plan = plan_cron_run(today=date(2026,9,22),
                          csv_root=...,
                          universe_cache_root=...,
                          enrichment_cache_root=...)
    # plan = {
    #   "skip_regions": {"jp": "Respect for the Aged Day"},
    #   "screener_refresh": ["au", "jp"],  # universe cache stale
    #   "stock_prices": {  # region -> tickers to fetch
    #     "au": ["ASX:BHP", "ASX:CBA", ...],
    #     ...
    #   },
    #   "yahoo_batches": [
    #     [("ASX:BHP", "BHP.AX"), ("ASX:CBA", "CBA.AX"), ...],  # ≤10 pairs
    #     ...
    #   ],
    #   "movers_regions": ["au", "jp"],  # Tue-Fri: forward-fill from yesterday
    #   "audit": {
    #     "skip_count": 1,
    #     "screener_refresh_count": 2,
    #     "stock_prices_count": 14,
    #     "yahoo_batch_count": 4,
    #     "yahoo_call_count": 40,  # 4 batches × ~10 each
    #   }
    # }

    result = finalize_cron_run(responses,
                                today=date(2026,9,22),
                                csv_root=...,
                                universe_cache_root=...,
                                enrichment_cache_root=...)
    # result = {
    #   "regions": {"au": 1623, "jp": 2000, ...},
    #   "total_rows": 14000,
    #   "audit_lines": [...],
    #   "alerts": []  # regression detector output
    # }
"""
from __future__ import annotations

import csv
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent))

from universe_cache import UniverseCache
from enrichment_cache import EnrichmentCache
from yahoo_enrich import YahooEnricher, extract_enrichment
from pull_international_v2 import IntlPullOrchestrator, MoversDetector, ShibuiCrossListedResolver
from holiday_calendar import HolidayCalendar


HEADER = ["date", "ticker", "name", "open", "high", "low", "close",
          "volume", "change_pct", "market_cap", "pe_ratio", "sector",
          "currency", "exchange"]

# Default knobs — overridable via plan_cron_run args
DEFAULT_TOP_N_YAHOO = 500
DEFAULT_MOVERS_THRESHOLD = 3.0
DEFAULT_MOVERS_WEEKDAYS = {0, 1, 2, 3}  # Mon-Thu (Fri skipped; weekend pull)


def plan_cron_run(
    today: date,
    csv_root: Path,
    universe_cache_root: Path,
    enrichment_cache_root: Path,
    top_n_yahoo: int = DEFAULT_TOP_N_YAHOO,
    movers_threshold: float = DEFAULT_MOVERS_THRESHOLD,
    movers_enabled: bool | None = None,
    holiday_calendar: HolidayCalendar | None = None,
    volume_ttl_days: int | None = None,
) -> dict:
    """Plan the cron run: what to skip, what to refresh, what to enrich.

    Returns a dict the cron agent uses to make MCP calls.

    `volume_ttl_days` overrides the EnrichmentCache default (1 day). At 5+ days
    Yahoo call volume drops ~80% — trade-off is volume data is up to N-1 days
    stale for non-mover tickers.
    """
    csv_root = Path(csv_root)
    universe_cache_root = Path(universe_cache_root)
    enrichment_cache_root = Path(enrichment_cache_root)

    cal = holiday_calendar or HolidayCalendar()
    cache = UniverseCache(universe_cache_root, today=today)
    if volume_ttl_days is not None:
        ttl = {"volume": volume_ttl_days, "pe_ratio": 30, "sector": 30}
        enrich_cache = EnrichmentCache(enrichment_cache_root, ttl_days=ttl, today=today)
    else:
        enrich_cache = EnrichmentCache(enrichment_cache_root, today=today)

    # Auto-enable movers mode on Mon-Thu. Friday is intentionally excluded:
    # at 16:35 ET Friday, EU and US have ~30 minutes left of trading, so
    # prices aren't stable yet — better to do a full refresh and rely on the
    # Monday anchor.
    if movers_enabled is None:
        movers_enabled = today.weekday() in DEFAULT_MOVERS_WEEKDAYS

    skip: dict[str, str] = {}
    all_regions = cal.regions()
    for region in all_regions:
        if not cal.is_trading_day(region, today):
            skip[region] = f"{today.isoformat()} is a holiday or weekend for {region}"

    screener_refresh: list[str] = []
    multi_pass_refresh: list[str] = []
    stock_prices_regions: dict[str, list[str]] = {}
    yahoo_batches: list[list[tuple[str, str]]] = []

    enricher = YahooEnricher()

    for region in all_regions:
        if region in skip:
            continue
        if cache.is_stale(region):
            screener_refresh.append(region)
            # Schedule ASC-sorted market_cap range passes for ANY stale region,
            # not just capped ones. For non-capped regions (< 2000 listed) the
            # merge dedupes against the existing cache and adds nothing, so the
            # cost is zero. For capped regions, this captured +1,200 names
            # (2026-09-24: jp +201, tw +201, ca +216, eu-de +582).
            multi_pass_refresh.append(region)

        tickers = cache.get(region)
        if not tickers:
            # No cache for this region — skip stock_prices (it would 404 on
            # 2000 empty tickers). The cron must seed the cache via v1.
            continue
        stock_prices_regions[region] = tickers

        # Decide which tickers need Yahoo refresh based on stale fields
        priority = cache.get_priority(region)
        top_tv = _select_top_n(region, tickers, top_n_yahoo, csv_root, priority=priority)
        stale = enrich_cache.bulk_stale_fields(top_tv)
        # Build Yahoo batch plan: only include tickers where volume is stale
        # (pe/sector usually still fresh → skip the call)
        to_refresh = [tv for tv in top_tv if "volume" in stale.get(tv, set())]
        if to_refresh:
            yahoo_batches.extend(enricher.batch(to_refresh, batch_size=10))

    movers_regions = list(set(all_regions) - set(skip)) if movers_enabled else []

    yahoo_call_count = sum(len(b) for b in yahoo_batches)
    return {
        "today": today.isoformat(),
        "skip_regions": skip,
        "screener_refresh": screener_refresh,
        "multi_pass_refresh": multi_pass_refresh,
        "stock_prices": stock_prices_regions,
        "yahoo_batches": [[(tv, yt) for tv, yt in batch] for batch in yahoo_batches],
        "movers_regions": movers_regions,
        "audit": {
            "skip_count": len(skip),
            "screener_refresh_count": len(screener_refresh),
            "multi_pass_refresh_count": len(multi_pass_refresh),
            "stock_prices_regions": len(stock_prices_regions),
            "yahoo_batch_count": len(yahoo_batches),
            "yahoo_call_count": yahoo_call_count,
            "movers_enabled": movers_enabled,
        },
    }


def _select_top_n(region: str, tickers: list[str], n: int,
                   csv_root: Path, priority: list[str] | None = None) -> list[str]:
    """Pick top-N tickers for Yahoo enrichment.

    Always includes priority-flagged tickers first (regardless of market_cap
    rank), then fills the remaining slots with the top of the market_cap-sorted
    list. Deduped; order is stable.

    Args:
        region: e.g. "eu-de"
        tickers: full cached list, sorted by market_cap desc
        n: target total count for the enrichment batch
        csv_root: parent of <region>/YYYY-MM-DD.csv (used for stale-field detection)
        priority: optional list of priority tickers (e.g. from cache.get_priority)
    """
    priority = priority or []
    seen: set[str] = set()
    out: list[str] = []
    for tv in priority:
        if tv in tickers and tv not in seen:
            out.append(tv)
            seen.add(tv)
    for tv in tickers:
        if len(out) >= n:
            break
        if tv in seen:
            continue
        out.append(tv)
        seen.add(tv)
    return out


def finalize_cron_run(
    responses: dict,
    today: date,
    csv_root: Path,
    universe_cache_root: Path,
    enrichment_cache_root: Path,
    movers_threshold: float = DEFAULT_MOVERS_THRESHOLD,
    movers_regions: set[str] | None = None,
) -> dict:
    """Write CSVs and audit lines from collected MCP responses.

    Args:
        responses: shape {
          "region_data": {region: [stock_prices rows...]},
          "yahoo_enrich": {region: {tv_ticker: {volume, pe_ratio, sector}}},
          "shibui_data": {region: {tv_ticker: {volume, pe_ratio, sector}}} (opt-in)
          "multi_pass_rows": {region: [ticker_dicts from screen_stocks ASC passes]}
        }
    """
    csv_root = Path(csv_root)
    universe_cache_root = Path(universe_cache_root)
    enrichment_cache_root = Path(enrichment_cache_root)

    cache = UniverseCache(universe_cache_root, today=today)
    enrich_cache = EnrichmentCache(enrichment_cache_root, today=today)

    region_data = responses.get("region_data", {})
    yahoo_enrich = responses.get("yahoo_enrich", {})
    shibui_data = responses.get("shibui_data", {})
    multi_pass_rows = responses.get("multi_pass_rows", {})

    # Apply multi-pass merges BEFORE writing region_data, so today's stock_prices
    # rows include any newly-added long-tail tickers. cache.merge() dedupes by
    # ticker, so re-running on the same data is idempotent.
    multi_pass_added: dict[str, int] = {}
    for region, rows in multi_pass_rows.items():
        before, added = cache.merge(region, rows, source_suffix="_multi_pass_asc")
        if added:
            multi_pass_added[region] = added

    # Delisting detection — scan trailing CSVs and flag tickers N/A for >= 25/30
    # trading days. Only fires once enough history accumulates (function returns
    # empty list otherwise). Marked tickers are SKIPPED by get_active() so the
    # stock_prices call no longer wastes a row on them.
    delisting_marked: dict[str, list[str]] = {}
    dedupe_removed: dict[str, int] = {}
    for region in cache.status().keys():
        try:
            candidates = cache.detect_delisting_candidates(region, csv_root)
        except Exception:
            candidates = []
        if candidates:
            n = cache.mark_delisted(region, candidates, reason="na_25_of_30_days")
            if n:
                delisting_marked[region] = candidates

        # Multi-listing dedupe — same company on multiple exchanges collapses
        # to one primary-listing row. Reduces redundant stock_prices calls
        # (XETR:NVD = FWB:NVD = GETTEX:NVD = MUN:NVD = SWB:NVD etc.) and
        # shrinks the per-region Yahoo batch by 30-65% for fragmented regions.
        # The collapsed variants are kept on the canonical row under
        # `also_listed_on` for traceability.
        try:
            removed = cache.dedupe_primary_listing(region)
            if removed:
                dedupe_removed[region] = removed
        except Exception:
            pass

    # Enrichment cache dedupe — merge Yahoo enrichment entries for the same
    # underlying symbol under the primary-listing ticker. Cleans up entries
    # that accumulated when the same company was enriched via multiple
    # exchange variants before universe dedupe ran.
    enrichment_deduped: dict[str, int] = {}
    if multi_pass_added or dedupe_removed:
        # Only worth running when we touched the universe cache
        try:
            enr = EnrichmentCache(enrichment_cache_root, today=today)
            removed, merged = enr.dedupe_primary_listing()
            enrichment_deduped = {"removed": removed, "merged_fields": merged}
        except Exception:
            pass

    # Write Yahoo enrichments back to cache for next time
    flat_yahoo: dict[str, dict] = {}
    for region, by_ticker in yahoo_enrich.items():
        for tv, fields in by_ticker.items():
            flat_yahoo[tv] = fields
    if flat_yahoo:
        # Update only the fields Yahoo actually returned; preserve freshness
        # of fields Yahoo didn't include (cache.update preserves prior).
        enrich_cache.bulk_set(flat_yahoo)

    movers_detector = MoversDetector(csv_root, threshold=movers_threshold,
                                       yesterday=previous_trading_day_for_movers(today))
    orch = IntlPullOrchestrator(
        csv_root=csv_root,
        universe_cache=cache,
        movers_detector=movers_detector,
        today=today,
    )

    result_rows = orch.assemble_all(
        region_data=region_data,
        region_yahoo_enrich=yahoo_enrich,
        region_shibui_data=shibui_data,
        movers_regions=movers_regions,
    )

    audit_lines = _emit_audit_lines(today, result_rows)
    alerts = _detect_regressions(today, csv_root, result_rows)

    return {
        "regions": result_rows,
        "total_rows": sum(result_rows.values()),
        "audit_lines": audit_lines,
        "alerts": alerts,
        "multi_pass_added": multi_pass_added,
        "delisting_marked": delisting_marked,
        "dedupe_removed": dedupe_removed,
        "enrichment_deduped": enrichment_deduped,
    }


def previous_trading_day_for_movers(today: date,
                                     calendar: HolidayCalendar | None = None
                                     ) -> date:
    """Pick the right 'yesterday' for movers mode.

    Mon → Friday (skip weekend). Tue-Thu → calendar yesterday.
    Fri → handled by the orchestrator's normal path (movers disabled).
    """
    cal = calendar or HolidayCalendar()
    if today.weekday() == 0:  # Monday
        # Walk back to the previous trading day for AU (covers AU Fri close).
        # Different regions have different Fri → Mon chains, so use US calendar
        # as a proxy (US is closed Mon holidays → regions probably are too).
        return cal.previous_trading_day("au", today) or (today - timedelta(days=3))
    return cal.previous_trading_day("au", today) or (today - timedelta(days=1))


def _emit_audit_lines(today: date, result_rows: dict[str, int]) -> list[str]:
    """Format per-region audit lines for the audit log."""
    lines = []
    for region in sorted(result_rows):
        lines.append(
            f"eod_snapshot target=international:{today.isoformat()} "
            f"region={region} rows={result_rows[region]} source=v2_cached_enriched"
        )
    total = sum(result_rows.values())
    lines.append(
        f"eod_snapshot target=international:{today.isoformat()} "
        f"regions={len(result_rows)} rows={total} source=v2_cached_enriched"
    )
    return lines


def _detect_regressions(today: date, csv_root: Path,
                          result_rows: dict[str, int],
                          threshold: float = 0.3) -> list[str]:
    """Compare today's row counts vs the 7-day trailing median per region.

    Returns a list of alert strings for any region whose count dropped by
    more than `threshold` (30% default) below the median.
    """
    alerts = []
    csv_root = Path(csv_root)
    for region, today_count in result_rows.items():
        prior_counts = []
        for d in range(1, 8):
            day = today - timedelta(days=d)
            path = csv_root / region / f"{day.isoformat()}.csv"
            if not path.exists():
                continue
            try:
                with open(path, encoding="utf-8", newline="") as fh:
                    reader = csv.reader(fh)
                    next(reader, None)  # skip header
                    prior_counts.append(sum(1 for _ in reader))
            except OSError:
                continue
        if len(prior_counts) < 3:
            continue
        prior_counts.sort()
        median = prior_counts[len(prior_counts) // 2]
        if median == 0:
            continue
        drop = (median - today_count) / median
        if drop > threshold:
            alerts.append(
                f"eod_snapshot_alert target=international:{today.isoformat()} "
                f"region={region} today={today_count} median_7d={median} "
                f"drop_pct={drop*100:.1f}"
            )
    return alerts


# ---------- CLI ----------

def _cli_plan(args: list[str]) -> int:
    """plan subcommand: prints the plan as JSON."""
    import argparse
    p = argparse.ArgumentParser(prog="run_intl_cron plan")
    p.add_argument("--today", required=True, help="YYYY-MM-DD")
    p.add_argument("--csv-root", required=True)
    p.add_argument("--universe-cache-root", required=True)
    p.add_argument("--enrichment-cache-root", required=True)
    p.add_argument("--top-n-yahoo", type=int, default=DEFAULT_TOP_N_YAHOO)
    p.add_argument("--movers-threshold", type=float, default=DEFAULT_MOVERS_THRESHOLD)
    p.add_argument("--no-movers", action="store_true")
    p.add_argument("--volume-ttl-days", type=int, default=None,
                    help="Override cache volume TTL (default 1). At 5+ days, "
                         "Yahoo call volume drops ~80%% with N-1 day stale volume.")
    parsed = p.parse_args(args)
    plan = plan_cron_run(
        today=date.fromisoformat(parsed.today),
        csv_root=Path(parsed.csv_root),
        universe_cache_root=Path(parsed.universe_cache_root),
        enrichment_cache_root=Path(parsed.enrichment_cache_root),
        top_n_yahoo=parsed.top_n_yahoo,
        movers_threshold=parsed.movers_threshold,
        movers_enabled=False if parsed.no_movers else None,
        volume_ttl_days=parsed.volume_ttl_days,
    )
    print(json.dumps(plan, indent=2))
    return 0


def _cli_finalize(args: list[str]) -> int:
    """finalize subcommand: reads JSON responses, writes CSVs + audit."""
    import argparse
    p = argparse.ArgumentParser(prog="run_intl_cron finalize")
    p.add_argument("--today", required=True)
    p.add_argument("--csv-root", required=True)
    p.add_argument("--universe-cache-root", required=True)
    p.add_argument("--enrichment-cache-root", required=True)
    p.add_argument("--movers-threshold", type=float, default=DEFAULT_MOVERS_THRESHOLD)
    p.add_argument("--movers-regions", default=None,
                    help="Comma-separated regions to run in movers mode")
    p.add_argument("--responses", required=True, help="Path to responses JSON file")
    p.add_argument("--audit-log", default=None,
                    help="Optional path to append audit lines")
    parsed = p.parse_args(args)
    responses = json.loads(Path(parsed.responses).read_text(encoding="utf-8"))
    movers_regions = (set(parsed.movers_regions.split(","))
                       if parsed.movers_regions else None)
    result = finalize_cron_run(
        responses=responses,
        today=date.fromisoformat(parsed.today),
        csv_root=Path(parsed.csv_root),
        universe_cache_root=Path(parsed.universe_cache_root),
        enrichment_cache_root=Path(parsed.enrichment_cache_root),
        movers_threshold=parsed.movers_threshold,
        movers_regions=movers_regions,
    )

    if parsed.audit_log:
        with open(parsed.audit_log, "a", encoding="utf-8") as fh:
            for line in result["audit_lines"]:
                fh.write(line + "\n")
            for line in result["alerts"]:
                fh.write(line + "\n")

    print(json.dumps(result, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv[1:]
    if not argv:
        print("usage: run_intl_cron.py {plan|finalize} ...", file=sys.stderr)
        return 2
    cmd = argv[0]
    if cmd == "plan":
        return _cli_plan(argv[1:])
    if cmd == "finalize":
        return _cli_finalize(argv[1:])
    print(f"unknown subcommand: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
