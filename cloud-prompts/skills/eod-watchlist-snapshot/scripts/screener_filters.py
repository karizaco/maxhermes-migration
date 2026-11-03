"""
screener_filters.py — helper for building TradingView stock_screener filter clauses.

Implements optimization #2: shrink the universe by adding min-market-cap and
min-volume filters to each screener call. TradingView-advanced stock_screener
accepts a `filters` parameter (list of {field, operator, value} dicts). The
TradingView field names for screener filters are documented at:
  https://www.tradingview.com/screener-docs/

Common filter fields:
  - market_cap_basic (**LISTING CURRENCY, NOT USD** — read the warning below)
  - change (today's % change)
  - volume (today's volume)
  - price (close)
  - average_volume_30d_calc
  - average_volume_10d_calc

.. warning::

   ``market_cap_basic`` is denominated in the instrument's **listing currency**, not USD.
   Verified 2026-11-03: a server-side filter of ``market_cap_basic > 300000000`` on the Japan
   endpoint still returns names whose market cap is JPY 385m — the field is compared as a JPY
   number. Share-count reconciliation confirms it: ``market_cap_basic / close`` returns the
   issuer's real share count (SAP 1.1626bn, Toyota 11.900bn, TSMC 25.770bn, Genmab 59.11m), all
   in local currency.

   Consequence: the ``min_market_cap_usd`` values below are **not** usable as server-side
   screener filters for a USD floor — a "$300M" floor sent to the Japan endpoint behaves as a
   JPY 300m floor (~$1.9M) and filters nothing. Use :func:`usd_floor_for_region` and apply the
   floor **client-side, after converting**::

       usd_cap = market_cap_basic * FX[listing_currency]
       keep = usd_cap >= floor_usd and (volume >= min_volume if min_volume else True)

   The values in :func:`filters_for_region` are kept for the screener-side pre-filter they were
   written for; read them as local-currency thresholds there.

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


# Per-region USD market-cap floors, applied CLIENT-SIDE after converting the
# listing-currency `market_cap_basic` to USD. See the module warning above.
#
# These are the floors the international artifact is written against; the numbers the
# 2026-10-28..30 artifacts used, in USD:
#
#   au $300M (+ vol >= 100k) | jp $300M | tw $200M | ca $200M | eu-de $300M (+ vol >= 50k)
#   eu-fr/eu-it/eu-es/eu-nl/eu-be/eu-at $100M | eu-ie $200M | eu-fi/eu-dk $100M
#   eu-pt/eu-gr $50M
USD_FLOORS: dict[str, tuple[float, int | None]] = {
    "au": (300_000_000, 100_000),
    "jp": (300_000_000, None),
    "tw": (200_000_000, None),
    "ca": (200_000_000, None),
    "eu-de": (300_000_000, 50_000),
    "eu-fr": (100_000_000, None),
    "eu-it": (100_000_000, None),
    "eu-es": (100_000_000, None),
    "eu-nl": (100_000_000, None),
    "eu-be": (100_000_000, None),
    "eu-at": (100_000_000, None),
    "eu-pt": (50_000_000, None),
    "eu-ie": (200_000_000, None),
    "eu-fi": (100_000_000, None),
    "eu-dk": (100_000_000, None),
    "eu-gr": (50_000_000, None),
}


def usd_floor_for_region(region: str) -> tuple[float, int | None]:
    """Return ``(floor_usd, min_volume)`` for a region.

    Apply this AFTER converting the listing-currency market cap to USD. See the module warning.

        usd_cap = market_cap_basic * FX[listing_currency]
        floor_usd, min_volume = usd_floor_for_region(region)
        keep = usd_cap >= floor_usd and (min_volume is None or volume >= min_volume)
    """
    return USD_FLOORS.get(region, (100_000_000, None))
