"""
yahoo_enrich.py — fill volume / pe_ratio / sector for international CSVs.

Implements optimization #4 from the cron-cost analysis: after TradingView
stock_screener produces the ticker list + OHLCV for a region, batch the
top-N (default 500, by market cap) through Yahoo MCP compare_stocks to fill
in volume / pe_ratio / sector (which the screener doesn't return).

Public API
----------
    enricher = YahooEnricher(tv_to_yahoo_map=DEFAULT_MAP)
    yahoo_tickers = enricher.to_yahoo_tickers(["ASX:BHP", "ASX:CBA"])
    # → ["BHP.AX", "CBA.AX"]
    plan = enricher.batch(["ASX:BHP", "ASX:CBA", "ASX:RIO"], batch_size=10)
    # → [[("ASX:BHP","BHP.AX"), ("ASX:CBA","CBA.AX"), ...]]  batches of 10

    # To call MCP:
    for batch in plan:
        yahoo_batch = [yt for _, yt in batch]
        rows = mcp__yahoo-finance__compare_stocks(tickers=yahoo_batch)
        for (tv, yt), row in zip(batch, rows):
            enrichments[tv] = extract_volume_pe_sector(row)
"""
from __future__ import annotations

from typing import Callable, Iterable


# TradingView exchange prefix → Yahoo suffix.
# Yahoo uses ISO-style suffixes appended after a dot. Some TV exchanges don't
# have a Yahoo equivalent (covered by `unmappable` set).
TV_TO_YAHOO_SUFFIX: dict[str, str] = {
    # Major exchanges — Yahoo supports all of these
    "ASX": ".AX",      # Australian Securities Exchange
    "TSE": ".T",       # Tokyo Stock Exchange (some symbols .TY)
    "TWSE": ".TW",     # Taiwan Stock Exchange
    "TPEX": ".TWO",    # Taipei Exchange
    "NEO": ".TO",      # NEO/Cboe Canada (TSX)
    "TSX": ".TO",
    "EURONEXT": ".AS", # Euronext Amsterdam default; per-symbol overrides handled below
    "XETRA": ".DE",
    "SWB": ".DE",      # Stuttgart (use DE suffix as fallback)
    "FRA": ".DE",      # Frankfurt
    "BME": ".MC",      # Bolsas y Mercados Españoles
    "MIL": ".MI",      # Borsa Italiana
    "VIE": ".VI",      # Vienna
    "ATHEX": ".AT",    # Athens
    "OMXCOP": ".CO",   # Copenhagen
    "OMXHEX": ".HE",   # Helsinki
    "OMXSTO": ".ST",   # Stockholm
    "LSE": ".L",       # London (NOT in scope here, but supported)
}

# Euronext is a single TV prefix but maps to 7 country suffixes. We disambiguate
# per-symbol via EuronextSymbolMatcher (see below).
EURONEXT_SYMBOL_MAP: dict[str, str] = {
    # Amsterdam
    "ASML": ".AS", "SHELL": ".AS", "UNA": ".AS", "INGA": ".AS",
    "ADYEN": ".AS", "AD": ".AS", "HEIA": ".AS", "PHIA": ".AS",
    "REN": ".AS", "KPN": ".AS", "MT": ".AS", "BESI": ".AS",
    "AKZA": ".AS", "IMCD": ".AS", "ASRNL": ".AS", "NN": ".AS",
    "RAND": ".AS", "AGN": ".AS", "UMG": ".AS", "AALB": ".AS",
    "VPK": ".AS", "CTPNV": ".AS", "EXO": ".AS", "DSFIR": ".AS",
    "WKL": ".AS", "FLOW": ".AS", "PRX": ".AS", "ASM": ".AS",
    "CVC": ".AS", "CCEP": ".AS",
    # Brussels
    "ABI": ".BR", "KBC": ".BR", "ARGX": ".BR", "UCB": ".BR",
    "AGS": ".BR", "ELI": ".BR", "LOTB": ".BR", "ACKB": ".BR",
    "GBLB": ".BR", "SOF": ".BR", "DIE": ".BR", "UMI": ".BR",
    "WDP": ".BR", "SYENS": ".BR", "SOLB": ".BR", "COBH": ".BR",
    "MELE": ".BR", "TUB": ".BR", "ONTEX": ".BR",
    # Paris
    "OR": ".PA", "MC": ".PA", "SAN": ".PA", "BNP": ".PA", "AI": ".PA",
    "AIR": ".PA", "BN": ".PA", "CA": ".PA", "SU": ".PA", "ENGI": ".PA",
    "VIE": ".PA", "DG": ".PA", "EL": ".PA", "SIE": ".PA", "RMS": ".PA",
    "CAP": ".PA", "PUB": ".PA", "DSY": ".PA", "LR": ".PA",
    # Lisbon
    "EDP": ".LS", "GALP": ".LS", "BCP": ".LS", "EDPR": ".LS", "JMT": ".LS",
    # Dublin
    "A5G": ".IR", "RYA": ".IR", "BIRG": ".IR", "KRX": ".IR", "KRZ": ".IR",
    "GL9": ".IR",
}


# Mapping: TV ticker (full like "EURONEXT:ASML") → Yahoo suffix override
def euronext_suffix(tv_ticker: str) -> str | None:
    """If tv_ticker is an Euronext-listed symbol, return the country-specific suffix."""
    if not tv_ticker.startswith("EURONEXT:"):
        return None
    symbol = tv_ticker.split(":", 1)[1]
    return EURONEXT_SYMBOL_MAP.get(symbol, ".AS")  # default to Amsterdam if unknown


def to_yahoo_ticker(tv_ticker: str,
                    tv_to_yahoo_map: dict[str, str] | None = None) -> str | None:
    """Convert a TradingView 'EXCHANGE:SYMBOL' ticker to Yahoo 'SYMBOL.SUFFIX' form.

    Returns None if the exchange has no Yahoo equivalent (caller should skip).
    """
    if ":" not in tv_ticker:
        # Bare ticker, no exchange info — pass through
        return tv_ticker

    exch, symbol = tv_ticker.split(":", 1)

    # Euronext disambiguation
    eur = euronext_suffix(tv_ticker)
    if eur is not None:
        return symbol + eur

    # Standard mapping
    map_ = tv_to_yahoo_map or TV_TO_YAHOO_SUFFIX
    suffix = map_.get(exch)
    if suffix is None:
        return None
    return symbol + suffix


class YahooEnricher:
    """Build batched Yahoo MCP call plans and parse enrichment responses."""

    def __init__(self, tv_to_yahoo_map: dict[str, str] | None = None,
                 unmappable_log: list[str] | None = None):
        self.tv_to_yahoo_map = tv_to_yahoo_map or TV_TO_YAHOO_SUFFIX
        self.unmappable = unmappable_log if unmappable_log is not None else []

    def to_yahoo_tickers(self, tv_tickers: Iterable[str]) -> list[tuple[str, str | None]]:
        """Returns list of (tv_ticker, yahoo_ticker_or_None) tuples."""
        out = []
        for tv in tv_tickers:
            yt = to_yahoo_ticker(tv, self.tv_to_yahoo_map)
            if yt is None:
                self.unmappable.append(tv)
            out.append((tv, yt))
        return out

    def batch(self, tv_tickers: Iterable[str], batch_size: int = 10
              ) -> list[list[tuple[str, str]]]:
        """Group TV tickers into Yahoo-compatible batches.

        Each batch is a list of (tv_ticker, yahoo_ticker) tuples; the caller
        sends the yahoo_tickers to compare_stocks and zips the response back.

        Tickers with no Yahoo mapping are dropped (and logged to unmappable).
        """
        batches: list[list[tuple[str, str]]] = []
        current: list[tuple[str, str]] = []
        for tv, yt in self.to_yahoo_tickers(tv_tickers):
            if yt is None:
                continue
            current.append((tv, yt))
            if len(current) >= batch_size:
                batches.append(current)
                current = []
        if current:
            batches.append(current)
        return batches


def extract_enrichment(row: dict) -> dict:
    """From a Yahoo compare_stocks row, pull the fields our CSV schema needs.

    Yahoo's compare_stocks response is markdown by default, or JSON with the
    caller's `response_format='json'` flag. Field names match the yahoo-finance
    MCP convention:
        - regularMarketVolume (or 'volume' in some versions)
        - trailingPE
        - sector
    """
    return {
        "volume": row.get("regularMarketVolume") or row.get("volume"),
        "pe_ratio": row.get("trailingPE") or row.get("trailingPe"),
        "sector": row.get("sector"),
    }


def merge_enrichment(row: dict, base_row: dict) -> dict:
    """Merge enrichment fields into an existing screener row (volume/pe/sector)."""
    out = dict(base_row)
    for k, v in row.items():
        if v is not None and (k not in out or out.get(k) in (None, "")):
            out[k] = v
    return out
