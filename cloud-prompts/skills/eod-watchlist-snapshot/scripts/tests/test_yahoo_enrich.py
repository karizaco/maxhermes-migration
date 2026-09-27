"""Tests for yahoo_enrich.py — run with `python -m unittest tests.test_yahoo_enrich`."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from yahoo_enrich import (
    YahooEnricher, TV_TO_YAHOO_SUFFIX, EURONEXT_SYMBOL_MAP,
    to_yahoo_ticker, euronext_suffix, extract_enrichment, merge_enrichment,
)


class TestToYahooTicker(unittest.TestCase):
    def test_known_americas(self):
        self.assertEqual(to_yahoo_ticker("ASX:BHP"), "BHP.AX")
        self.assertEqual(to_yahoo_ticker("TSE:8306"), "8306.T")
        self.assertEqual(to_yahoo_ticker("TWSE:2330"), "2330.TW")
        self.assertEqual(to_yahoo_ticker("TPEX:3105"), "3105.TWO")
        self.assertEqual(to_yahoo_ticker("NEO:RY"), "RY.TO")
        self.assertEqual(to_yahoo_ticker("TSX:SHOP"), "SHOP.TO")

    def test_european_unions_per_country(self):
        # Amsterdam
        self.assertEqual(to_yahoo_ticker("EURONEXT:ASML"), "ASML.AS")
        self.assertEqual(to_yahoo_ticker("EURONEXT:ADYEN"), "ADYEN.AS")
        # Brussels
        self.assertEqual(to_yahoo_ticker("EURONEXT:ABI"), "ABI.BR")
        self.assertEqual(to_yahoo_ticker("EURONEXT:ARGX"), "ARGX.BR")
        # Paris
        self.assertEqual(to_yahoo_ticker("EURONEXT:OR"), "OR.PA")
        self.assertEqual(to_yahoo_ticker("EURONEXT:MC"), "MC.PA")
        # Lisbon
        self.assertEqual(to_yahoo_ticker("EURONEXT:EDP"), "EDP.LS")
        # Dublin
        self.assertEqual(to_yahoo_ticker("EURONEXT:A5G"), "A5G.IR")
        # Unknown Euronext symbol defaults to Amsterdam
        self.assertEqual(to_yahoo_ticker("EURONEXT:UNKNOWNXYZ"), "UNKNOWNXYZ.AS")

    def test_euronext_suffix_helper(self):
        self.assertEqual(euronext_suffix("EURONEXT:ASML"), ".AS")
        self.assertEqual(euronext_suffix("EURONEXT:MC"), ".PA")
        self.assertIsNone(euronext_suffix("ASX:BHP"))
        self.assertIsNone(euronext_suffix("TSX:RY"))

    def test_other_european_exchanges(self):
        self.assertEqual(to_yahoo_ticker("BME:SAN"), "SAN.MC")
        self.assertEqual(to_yahoo_ticker("MIL:1NVDA"), "1NVDA.MI")
        self.assertEqual(to_yahoo_ticker("VIE:NVDA"), "NVDA.VI")
        self.assertEqual(to_yahoo_ticker("ATHEX:EEE"), "EEE.AT")
        self.assertEqual(to_yahoo_ticker("OMXCOP:NOVO_B"), "NOVO_B.CO")
        self.assertEqual(to_yahoo_ticker("OMXHEX:NDA_FI"), "NDA_FI.HE")

    def test_german_exchanges_use_DE_suffix(self):
        # Xetra, Stuttgart, Frankfurt all map to .DE
        self.assertEqual(to_yahoo_ticker("XETRA:SAP"), "SAP.DE")
        self.assertEqual(to_yahoo_ticker("SWB:NVD"), "NVD.DE")
        self.assertEqual(to_yahoo_ticker("FRA:DBK"), "DBK.DE")

    def test_unknown_exchange_returns_none(self):
        self.assertIsNone(to_yahoo_ticker("FOO:BAR"))

    def test_bare_ticker_passes_through(self):
        self.assertEqual(to_yahoo_ticker("AAPL"), "AAPL")

    def test_custom_map_override(self):
        custom_map = dict(TV_TO_YAHOO_SUFFIX)
        custom_map["ASX"] = ".XYZ"
        self.assertEqual(to_yahoo_ticker("ASX:BHP", custom_map), "BHP.XYZ")


class TestYahooEnricher(unittest.TestCase):
    def test_batch_groups_correctly(self):
        enricher = YahooEnricher()
        tv = ["ASX:BHP", "ASX:CBA", "ASX:RIO", "TSE:8306", "TSX:SHOP",
              "EURONEXT:ABI", "EURONEXT:OR", "EURONEXT:ASML",
              "BME:SAN", "MIL:ENI", "ATHEX:EEE", "OMXCOP:NOVO_B"]
        batches = enricher.batch(tv, batch_size=10)
        self.assertEqual(len(batches), 2)
        self.assertEqual(len(batches[0]), 10)
        self.assertEqual(len(batches[1]), 2)

    def test_unmappable_tickers_dropped_and_logged(self):
        unmappable = []
        enricher = YahooEnricher(unmappable_log=unmappable)
        tv = ["ASX:BHP", "FOO:BAR", "BAZ:QUX"]
        batches = enricher.batch(tv, batch_size=10)
        self.assertEqual(len(batches), 1)
        self.assertEqual(len(batches[0]), 1)  # only BHP made it
        self.assertEqual(batches[0], [("ASX:BHP", "BHP.AX")])
        self.assertIn("FOO:BAR", unmappable)
        self.assertIn("BAZ:QUX", unmappable)

    def test_to_yahoo_tickers_pairs(self):
        enricher = YahooEnricher()
        result = enricher.to_yahoo_tickers(["ASX:BHP", "FOO:BAR", "EURONEXT:ASML"])
        self.assertEqual(result, [
            ("ASX:BHP", "BHP.AX"),
            ("FOO:BAR", None),
            ("EURONEXT:ASML", "ASML.AS"),
        ])

    def test_batch_with_smaller_batch_size(self):
        enricher = YahooEnricher()
        tv = ["ASX:BHP", "ASX:CBA", "ASX:RIO", "TSE:8306"]
        batches = enricher.batch(tv, batch_size=2)
        self.assertEqual(len(batches), 2)
        self.assertEqual(len(batches[0]), 2)
        self.assertEqual(len(batches[1]), 2)

    def test_empty_input(self):
        enricher = YahooEnricher()
        self.assertEqual(enricher.batch([]), [])
        self.assertEqual(enricher.to_yahoo_tickers([]), [])

    def test_unmappable_log_shared_state(self):
        enricher = YahooEnricher()
        enricher.batch(["FOO:A", "BAR:B"])
        self.assertEqual(enricher.unmappable, ["FOO:A", "BAR:B"])


class TestExtractEnrichment(unittest.TestCase):
    def test_extracts_volume_pe_sector(self):
        row = {
            "regularMarketVolume": 1234567,
            "trailingPE": 25.4,
            "sector": "Technology",
            "currentPrice": 100.0,  # ignore
            "longName": "Foo Inc",   # ignore
        }
        out = extract_enrichment(row)
        self.assertEqual(out, {
            "volume": 1234567,
            "pe_ratio": 25.4,
            "sector": "Technology",
        })

    def test_falls_back_to_volume_key(self):
        row = {"volume": 999, "trailingPe": 10, "sector": "Energy"}
        out = extract_enrichment(row)
        self.assertEqual(out, {"volume": 999, "pe_ratio": 10, "sector": "Energy"})

    def test_handles_missing_fields(self):
        out = extract_enrichment({})
        self.assertEqual(out, {"volume": None, "pe_ratio": None, "sector": None})


class TestMergeEnrichment(unittest.TestCase):
    def test_fills_only_missing_fields(self):
        base = {"volume": "", "pe_ratio": "", "sector": "",
                "ticker": "ASX:BHP", "close": 100}
        enrich = {"volume": 5000000, "pe_ratio": 25.0, "sector": "Tech"}
        out = merge_enrichment(enrich, base)
        self.assertEqual(out["volume"], 5000000)
        self.assertEqual(out["pe_ratio"], 25.0)
        self.assertEqual(out["sector"], "Tech")
        self.assertEqual(out["ticker"], "ASX:BHP")  # base preserved
        self.assertEqual(out["close"], 100)

    def test_does_not_overwrite_existing_values(self):
        base = {"volume": 1000, "pe_ratio": 99, "sector": "Existing"}
        enrich = {"volume": 5000000, "pe_ratio": 25.0, "sector": "New"}
        out = merge_enrichment(enrich, base)
        self.assertEqual(out["volume"], 1000)
        self.assertEqual(out["pe_ratio"], 99)
        self.assertEqual(out["sector"], "Existing")

    def test_partial_enrichment(self):
        base = {"volume": "", "pe_ratio": "", "sector": ""}
        enrich = {"volume": 5000000}  # only volume
        out = merge_enrichment(enrich, base)
        self.assertEqual(out["volume"], 5000000)
        self.assertEqual(out["pe_ratio"], "")
        self.assertEqual(out["sector"], "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
