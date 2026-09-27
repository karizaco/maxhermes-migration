"""Tests for pull_international_v2.py — uses synthetic in-memory data (no MCP)."""
import csv
import json
import shutil
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from universe_cache import UniverseCache
from yahoo_enrich import YahooEnricher, extract_enrichment, merge_enrichment
from pull_international_v2 import (
    IntlPullOrchestrator, ShibuiCrossListedResolver, MoversDetector,
    build_yahoo_enrichment_plan, fmt,
)


def make_screener_row(ticker, name, price, change, mcap, currency="EUR", exch="EURONEXT"):
    return {
        "ticker": ticker,
        "symbol": ticker.split(":")[1] if ":" in ticker else ticker,
        "description": name,
        "exchange": exch,
        "price": price,
        "open": price * 0.99,
        "high": price * 1.01,
        "low": price * 0.98,
        "currency": currency,
        "change_percent": change,
        "market_cap": mcap,
        "dividend_yield": 0.0,
    }


class TestShibuiCrossListedResolver(unittest.TestCase):
    def test_returns_data_for_known_tickers(self):
        resolver = ShibuiCrossListedResolver({
            "TSX:RY": {"volume": 12345, "pe_ratio": 12.5, "sector": "Financials"},
            "TSX:SHOP": {"volume": 67890, "pe_ratio": 80.0, "sector": "Technology"},
        })
        self.assertEqual(resolver.resolve("TSX:RY")["volume"], 12345)
        self.assertIsNone(resolver.resolve("ASX:BHP"))

    def test_enrich_many(self):
        resolver = ShibuiCrossListedResolver({"A": {"volume": 1}})
        out = resolver.enrich_many(["A", "B", "C"])
        self.assertEqual(set(out.keys()), {"A"})
        self.assertEqual(out["A"]["volume"], 1)


class TestMoversDetector(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.region_dir = self.tmp / "au"
        self.region_dir.mkdir()
        yesterday = (date(2026, 9, 22) - timedelta(days=1)).isoformat()
        path = self.region_dir / f"{yesterday}.csv"
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["date", "ticker", "name", "open", "high", "low", "close",
                        "volume", "change_pct", "market_cap", "pe_ratio", "sector",
                        "currency", "exchange"])
            w.writerow(["2026-09-21", "ASX:BHP", "BHP Group", "60", "62", "59", "61",
                        "1000000", "5.0", "300000000000", "10.0", "Materials",
                        "AUD", "ASX"])
            w.writerow(["2026-09-21", "ASX:CBA", "CBA", "150", "152", "149", "151",
                        "500000", "0.5", "250000000000", "20.0", "Financials",
                        "AUD", "ASX"])
            w.writerow(["2026-09-21", "ASX:NAB", "NAB", "38", "39", "37", "38.5",
                        "200000", "-2.0", "120000000000", "15.0", "Financials",
                        "AUD", "ASX"])
        self.detector = MoversDetector(self.tmp, threshold=3.0, yesterday=date(2026, 9, 21))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_find_movers_filters_above_threshold(self):
        movers = self.detector.find_movers("au")
        # BHP (+5%) and NAB (-2%) — wait, |-2| < 3, so only BHP passes
        self.assertEqual(movers, ["ASX:BHP"])

    def test_find_movers_returns_none_when_csv_missing(self):
        detector = MoversDetector(self.tmp, threshold=3.0, yesterday=date(2026, 1, 1))
        self.assertIsNone(detector.find_movers("au"))

    def test_load_previous_rows(self):
        rows = self.detector.load_previous_rows("au")
        self.assertIn("ASX:BHP", rows)
        self.assertEqual(rows["ASX:BHP"]["close"], "61")

    def test_load_previous_rows_returns_none_when_missing(self):
        detector = MoversDetector(self.tmp, threshold=3.0, yesterday=date(2026, 1, 1))
        self.assertIsNone(detector.load_previous_rows("au"))

    def test_threshold_is_inclusive(self):
        # Move NAB to exactly -3.0% to verify inclusive boundary
        detector = MoversDetector(self.tmp, threshold=3.0, yesterday=date(2026, 9, 21))
        # Re-write NAB with -3.0 (was -2.0)
        with open(self.tmp / "au" / "2026-09-21.csv", "a", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["2026-09-21", "ASX:WBC", "WBC", "34", "35", "33", "34.5",
                        "100000", "-3.0", "100000000000", "12.0", "Financials",
                        "AUD", "ASX"])
        movers = detector.find_movers("au")
        self.assertIn("ASX:WBC", movers)


class TestIntlPullOrchestrator(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.cache_root = self.tmp / "universe"
        self.csv_root = self.tmp / "csv"
        self.csv_root.mkdir()
        self.cache = UniverseCache(self.cache_root, ttl_days=7, today=date(2026, 9, 22))
        self.orchestrator = IntlPullOrchestrator(
            csv_root=self.csv_root,
            universe_cache=self.cache,
            today=date(2026, 9, 22),
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_csv(self, region, rows, day=date(2026, 9, 22)):
        path = self.csv_root / region / f"{day.isoformat()}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["date", "ticker", "name", "open", "high", "low", "close",
                        "volume", "change_pct", "market_cap", "pe_ratio", "sector",
                        "currency", "exchange"])
            w.writerows(rows)

    # ---------- assemble_region ----------

    def test_assemble_region_basic(self):
        rows_in = [
            make_screener_row("ASX:BHP", "BHP Group", 61.0, 1.5, 300e9, "AUD", "ASX"),
            make_screener_row("ASX:CBA", "CBA", 150.0, 0.5, 250e9, "AUD", "ASX"),
        ]
        out = self.orchestrator.assemble_region("au", rows_in)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0][1], "ASX:BHP")  # ticker
        self.assertEqual(out[0][2], "BHP Group")  # name
        self.assertEqual(out[0][12], "AUD")  # currency
        self.assertEqual(out[0][13], "ASX")  # exchange
        # volume/pe/sector should be empty (no enrichment)
        self.assertEqual(out[0][7], "")
        self.assertEqual(out[0][10], "")

    def test_assemble_region_with_yahoo_enrichment(self):
        rows_in = [make_screener_row("ASX:BHP", "BHP", 61.0, 1.5, 300e9, "AUD", "ASX")]
        yahoo = {"ASX:BHP": {"volume": 12345, "pe_ratio": 12.5, "sector": "Materials"}}
        out = self.orchestrator.assemble_region("au", rows_in, yahoo_enrichments=yahoo)
        self.assertEqual(out[0][7], "12345")
        self.assertEqual(out[0][10], "12.5")
        self.assertEqual(out[0][11], "Materials")

    def test_assemble_region_with_shibui_enrichment_takes_priority(self):
        rows_in = [make_screener_row("ASX:BHP", "BHP", 61.0, 1.5, 300e9, "AUD", "ASX")]
        yahoo = {"ASX:BHP": {"volume": 12345, "pe_ratio": 12.5, "sector": "Materials"}}
        shibui = {"ASX:BHP": {"volume": 99999, "pe_ratio": 11.0, "sector": "Energy"}}
        out = self.orchestrator.assemble_region(
            "au", rows_in, yahoo_enrichments=yahoo, shibui_data=shibui)
        # shibui wins (volume + pe_ratio + sector)
        self.assertEqual(out[0][7], "99999")
        # fmt() shortens whole floats to int form ("11" not "11.0"); that's
        # the documented behavior — see TestFmt
        self.assertEqual(out[0][10], "11")
        self.assertEqual(out[0][11], "Energy")

    def test_assemble_region_skips_rows_without_ticker(self):
        rows_in = [{"ticker": "", "description": "empty"}]
        out = self.orchestrator.assemble_region("au", rows_in)
        self.assertEqual(out, [])

    def test_assemble_region_skips_euronext_rows_yahoo_cannot_handle(self):
        # A Stockholm-listed ticker with no Yahoo mapping — should still appear
        # in the CSV but with empty enrichment (since we'd skip Yahoo for it)
        rows_in = [
            make_screener_row("OMXSTO:AZN", "AstraZeneca", 1651, 0.3, 200e9, "SEK", "OMXSTO"),
        ]
        out = self.orchestrator.assemble_region("eu-fi", rows_in)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0][12], "SEK")  # currency still present

    # ---------- assemble_all + file output ----------

    def test_assemble_all_writes_per_region_csv(self):
        region_data = {
            "au": [
                make_screener_row("ASX:BHP", "BHP", 61.0, 1.5, 300e9, "AUD", "ASX"),
                make_screener_row("ASX:CBA", "CBA", 150.0, 0.5, 250e9, "AUD", "ASX"),
            ],
            "jp": [
                make_screener_row("TSE:8306", "Mitsubishi UFJ", 3725, 4.0, 100e12, "JPY", "TSE"),
            ],
        }
        written = self.orchestrator.assemble_all(region_data)
        self.assertEqual(written, {"au": 2, "jp": 1})
        self.assertTrue((self.csv_root / "au" / "2026-09-22.csv").exists())
        self.assertTrue((self.csv_root / "jp" / "2026-09-22.csv").exists())
        with open(self.csv_root / "au" / "2026-09-22.csv", encoding="utf-8") as fh:
            reader = csv.reader(fh)
            header = next(reader)
            self.assertEqual(header[0], "date")
            rows = list(reader)
            self.assertEqual(len(rows), 2)

    def test_assemble_all_skips_regions_with_no_data(self):
        written = self.orchestrator.assemble_all({"au": []})
        self.assertEqual(written, {})

    def test_change_pct_negative_value(self):
        rows_in = [make_screener_row("ASX:NAB", "NAB", 38.0, -2.5, 120e9, "AUD", "ASX")]
        out = self.orchestrator.assemble_region("au", rows_in)
        self.assertEqual(out[0][8], "-2.5")

    # ---------- top-N ----------

    def test_select_top_n_picks_by_market_cap(self):
        rows_in = [
            make_screener_row("A:SMALL", "Small", 1.0, 0.1, 1e6, "X", "X"),
            make_screener_row("A:MED", "Medium", 10.0, 0.1, 1e9, "X", "X"),
            make_screener_row("A:BIG", "Big", 100.0, 0.1, 1e12, "X", "X"),
        ]
        top = self.orchestrator.select_top_n("au", rows_in, n=2)
        self.assertEqual(top, ["A:BIG", "A:MED"])

    def test_select_top_n_default(self):
        rows_in = [
            make_screener_row(f"A:{i}", f"T{i}", 1.0, 0.1, float(i), "X", "X")
            for i in range(600)
        ]
        top = self.orchestrator.select_top_n("au", rows_in)  # default 500
        self.assertEqual(len(top), 500)


class TestBuildYahooEnrichmentPlan(unittest.TestCase):
    def test_builds_batches_of_ten(self):
        rows_in = [
            make_screener_row(f"ASX:T{i}", f"T{i}", 1.0, 0.1, 100.0 * (100 - i), "AUD", "ASX")
            for i in range(25)
        ]
        plan = build_yahoo_enrichment_plan("au", rows_in, top_n=25)
        self.assertEqual(len(plan["batches"]), 3)
        self.assertEqual(len(plan["batches"][0]), 10)
        self.assertEqual(len(plan["batches"][1]), 10)
        self.assertEqual(len(plan["batches"][2]), 5)

    def test_top_n_caps_total_picked(self):
        rows_in = [
            make_screener_row(f"ASX:T{i}", f"T{i}", 1.0, 0.1, 100.0, "AUD", "ASX")
            for i in range(100)
        ]
        plan = build_yahoo_enrichment_plan("au", rows_in, top_n=10)
        self.assertEqual(len(plan["batches"]), 1)
        self.assertEqual(len(plan["batches"][0]), 10)


class TestFmt(unittest.TestCase):
    def test_none_returns_empty(self):
        self.assertEqual(fmt(None), "")

    def test_int_returns_int_string(self):
        self.assertEqual(fmt(123), "123")

    def test_whole_float_returns_int_string(self):
        self.assertEqual(fmt(100.0), "100")

    def test_decimal_float_trims_trailing_zeros(self):
        self.assertEqual(fmt(1.50), "1.5")
        self.assertEqual(fmt(1.234567), "1.2346")

    def test_string_passes_through(self):
        self.assertEqual(fmt("AUD"), "AUD")

    def test_bool_returns_lowercase(self):
        self.assertEqual(fmt(True), "true")


class TestIntegration(unittest.TestCase):
    """End-to-end: write a CSV, assemble a new orchestrator against a mocked
    Yahoo enrichment source, verify the output matches expectations."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_full_workflow(self):
        csv_root = self.tmp / "csv"
        csv_root.mkdir()
        # Simulate yesterday's CSV for forward-fill
        yesterday_dir = csv_root / "au"
        yesterday_dir.mkdir()
        with open(yesterday_dir / "2026-09-21.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["date", "ticker", "name", "open", "high", "low", "close",
                        "volume", "change_pct", "market_cap", "pe_ratio", "sector",
                        "currency", "exchange"])
            w.writerow(["2026-09-21", "ASX:STABLE", "Stable Co", "10", "11", "9", "10.5",
                        "100000", "0.5", "50000000", "15.0", "Industrials", "AUD", "ASX"])

        cache = UniverseCache(self.tmp / "cache", ttl_days=7, today=date(2026, 9, 22))
        cache.refresh("au", [
            {"ticker": "ASX:BHP", "market_cap": 300e9},
            {"ticker": "ASX:STABLE", "market_cap": 50e6},  # forward-fill candidate
        ])
        movers = MoversDetector(csv_root, threshold=3.0, yesterday=date(2026, 9, 21))
        orch = IntlPullOrchestrator(csv_root=csv_root, universe_cache=cache,
                                   movers_detector=movers, today=date(2026, 9, 22))

        # Movers mode: today's pull returned ONLY BHP (the mover).
        # STABLE is in the cached universe but was below the movers threshold
        # so it isn't in today's pull — orchestrator forward-fills it from yesterday.
        rows_today = [
            make_screener_row("ASX:BHP", "BHP Group", 61.0, 1.5, 300e9, "AUD", "ASX"),
        ]
        out = orch.assemble_region(
            "au",
            rows_today,
            yahoo_enrichments={"ASX:BHP": {
                "volume": 12345, "pe_ratio": 12.5, "sector": "Materials"
            }},
            forward_fill_rows=movers.load_previous_rows("au"),
            cached_tickers=cache.get("au"),
        )
        # BHP row + STABLE forward-fill row
        self.assertEqual(len(out), 2)
        # BHP gets Yahoo enrichment
        bhp_row = [r for r in out if r[1] == "ASX:BHP"][0]
        self.assertEqual(bhp_row[7], "12345")
        self.assertEqual(bhp_row[10], "12.5")
        # STABLE row was forward-filled from yesterday
        stable_row = [r for r in out if r[1] == "ASX:STABLE"][0]
        self.assertEqual(stable_row[6], "10.5")  # close from yesterday
        self.assertEqual(stable_row[10], "15.0")  # pe from yesterday
        self.assertEqual(stable_row[8], "0.0")    # change_pct reset to 0


if __name__ == "__main__":
    unittest.main(verbosity=2)
