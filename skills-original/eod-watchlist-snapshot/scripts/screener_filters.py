"""
screener_filters.py — helper for building TradingView stock_screener filter clauses.

Implements optimization #2: shrink the universe by adding min-market-cap and
min-volume filters to each screener call. TradingView-advanced stock_screener
accepts a `filters` parameter (list of {field, operator, value} dicts). The
TradingView field names for screener filters are documented at:
  https://www.tradingview.com/screener-docs/

Common filter fields:
  - market_cap_basic (USD)
  - change (today's % change)
  - volume (today's volume)
  - price (close)
  - average_volume_30d_calc
  - average_volume_10d_calc

Common operators: greater, less, greater_or_equal, less_or_equal, equal,
in_range, not_equal, has, has_none_of, cross_above, cross_below, etc.

Usage
-----
    from screener_filters import default_filters

    filters = default_filters(min_market_cap_usd=200_000_000, min_volume=100_000)
    # → [{"field": "market_cap_basic", "operator": "greater", "value": 200000000},
    #    {"field": "volume", "operator": "greater", "value": 100000}]

    # Pass to the MCP call:
    mcp__tradingview-advanced__stock_screener(
        country="australia", stock_type="common", exclude_otc=True,
        limit=2000, compact=False, filters=filters,
    )
"""
from __future__ import annotations

from typing import Iterable


def default_filters(
    min_market_cap_usd: float | None = 200_000_000,
    min_volume: float | None = None,
    min_change_pct: float | None = None,
    max_change_pct: float | None = None,
) -> list[dict]:
    """Return a TradingView screener filter list with sensible defaults.

    Default: drop companies under $200M market cap. This typically cuts EU-DE
    from 33k → ~1500 actively-traded names, JP from 3,898 → ~3,200, CA from
    4,165 → ~2,800.

    Pass None to disable a filter dimension.
    """
    filters = []
    if min_market_cap_usd is not None:
        filters.append({
            "field": "market_cap_basic",
            "operator": "greater",
            "value": float(min_market_cap_usd),
        })
    if min_volume is not None:
        filters.append({
            "field": "volume",
            "operator": "greater",
            "value": float(min_volume),
        })
    if min_change_pct is not None:
        filters.append({
            "field": "change",
            "operator": "greater",
            "value": float(min_change_pct),
        })
    if max_change_pct is not None:
        filters.append({
            "field": "change",
            "operator": "less",
            "value": float(max_change_pct),
        })
    return filters


def filters_for_region(region: str) -> list[dict]:
    """Per-region filter presets. Override defaults for markets with
    different liquidity profiles."""
    presets = {
        # Mature large-cap markets — keep loose filter
        "jp": default_filters(min_market_cap_usd=300_000_000),
        "tw": default_filters(min_market_cap_usd=200_000_000),
        "ca": default_filters(min_market_cap_usd=200_000_000),
        # EU — German Frankfurt has 33k names; tighten filter
        "eu-de": default_filters(min_market_cap_usd=300_000_000, min_volume=50_000),
        # AU — mostly mid-caps; use a tighter floor to skip micro-caps
        "au": default_filters(min_market_cap_usd=300_000_000, min_volume=100_000),
        # Smaller markets — looser filter (capture the whole universe)
        "eu-fr": default_filters(min_market_cap_usd=100_000_000),
        "eu-it": default_filters(min_market_cap_usd=100_000_000),
        "eu-es": default_filters(min_market_cap_usd=100_000_000),
        "eu-nl": default_filters(min_market_cap_usd=100_000_000),
        "eu-be": default_filters(min_market_cap_usd=100_000_000),
        "eu-at": default_filters(min_market_cap_usd=100_000_000),
        "eu-pt": default_filters(min_market_cap_usd=50_000_000),
        "eu-ie": default_filters(min_market_cap_usd=200_000_000),
        "eu-fi": default_filters(min_market_cap_usd=100_000_000),
        "eu-dk": default_filters(min_market_cap_usd=100_000_000),
        "eu-gr": default_filters(min_market_cap_usd=50_000_000),
    }
    return presets.get(region, default_filters())
