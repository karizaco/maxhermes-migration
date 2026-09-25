"""Tests for screener_filters.py."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from screener_filters import default_filters, filters_for_region


class TestDefaultFilters(unittest.TestCase):
    def test_default_returns_market_cap_filter(self):
        f = default_filters()
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["field"], "market_cap_basic")
        self.assertEqual(f[0]["operator"], "greater")
        self.assertEqual(f[0]["value"], 200_000_000)

    def test_custom_market_cap(self):
        f = default_filters(min_market_cap_usd=500_000_000)
        self.assertEqual(f[0]["value"], 500_000_000)

    def test_disabled_market_cap(self):
        f = default_filters(min_market_cap_usd=None)
        self.assertEqual(f, [])

    def test_volume_filter(self):
        f = default_filters(min_volume=200_000)
        self.assertEqual(len(f), 2)
        self.assertEqual(f[1]["field"], "volume")
        self.assertEqual(f[1]["value"], 200_000)

    def test_change_pct_band(self):
        f = default_filters(min_change_pct=-5.0, max_change_pct=5.0)
        self.assertEqual(len(f), 3)
        self.assertEqual(f[1]["operator"], "greater")
        self.assertEqual(f[1]["value"], -5.0)
        self.assertEqual(f[2]["operator"], "less")
        self.assertEqual(f[2]["value"], 5.0)

    def test_all_filters_together(self):
        f = default_filters(
            min_market_cap_usd=200_000_000,
            min_volume=100_000,
            min_change_pct=-2.0,
            max_change_pct=10.0,
        )
        self.assertEqual(len(f), 4)
        fields = [x["field"] for x in f]
        self.assertEqual(fields, ["market_cap_basic", "volume", "change", "change"])


class TestFiltersForRegion(unittest.TestCase):
    def test_known_region_has_preset(self):
        f = filters_for_region("jp")
        self.assertGreater(len(f), 0)
        # JP preset uses $300M floor
        self.assertEqual(f[0]["value"], 300_000_000)

    def test_unknown_region_falls_back_to_default(self):
        f = filters_for_region("xx-unknown")
        # Falls back to default_filters with $200M cap
        self.assertEqual(f[0]["value"], 200_000_000)

    def test_eu_de_has_volume_floor(self):
        f = filters_for_region("eu-de")
        fields = [x["field"] for x in f]
        self.assertIn("volume", fields)

    def test_au_has_volume_floor(self):
        f = filters_for_region("au")
        fields = [x["field"] for x in f]
        self.assertIn("volume", fields)

    def test_eu_pt_lowest_floor(self):
        # PT has few large caps; allow smaller caps
        f = filters_for_region("eu-pt")
        self.assertEqual(f[0]["value"], 50_000_000)

    def test_eu_gr_lowest_floor(self):
        f = filters_for_region("eu-gr")
        self.assertEqual(f[0]["value"], 50_000_000)

    def test_all_preset_regions_return_non_empty(self):
        regions = ["au", "jp", "tw", "ca", "eu-de", "eu-fr", "eu-it",
                   "eu-es", "eu-nl", "eu-be", "eu-at", "eu-pt", "eu-ie",
                   "eu-fi", "eu-dk", "eu-gr"]
        for r in regions:
            f = filters_for_region(r)
            self.assertGreater(len(f), 0, msg=f"empty filters for {r}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
