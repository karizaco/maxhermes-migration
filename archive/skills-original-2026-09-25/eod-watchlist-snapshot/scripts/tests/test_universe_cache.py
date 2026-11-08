"""Tests for universe_cache.py — run with `python -m unittest tests.test_universe_cache`."""
import json
import shutil
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from universe_cache import UniverseCache


class TestUniverseCache(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="univ_cache_test_"))
        self.cache = UniverseCache(self.tmp, ttl_days=7, today=date(2026, 9, 22))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---------- is_loaded / is_stale ----------

    def test_empty_cache_is_not_loaded_and_is_stale(self):
        self.assertFalse(self.cache.is_loaded("au"))
        self.assertTrue(self.cache.is_stale("au"))

    def test_fresh_cache_is_loaded_and_not_stale(self):
        self.cache.refresh("au", ["ASX:BHP", "ASX:CBA"], source="tradingview_screener")
        self.assertTrue(self.cache.is_loaded("au"))
        self.assertFalse(self.cache.is_stale("au"))
        self.assertEqual(self.cache.age_days("au"), 0)

    def test_expired_cache_is_stale(self):
        self.cache.refresh("au", ["ASX:BHP"], source="tradingview_screener")
        # Move today forward past TTL
        later = UniverseCache(self.tmp, ttl_days=7, today=date(2026, 9, 30))
        self.assertTrue(later.is_stale("au"))
        self.assertEqual(later.age_days("au"), 8)

    # ---------- refresh + get ----------

    def test_refresh_with_plain_string_list(self):
        n = self.cache.refresh("au", ["ASX:BHP", "ASX:CBA", "ASX:RIO"])
        self.assertEqual(n, 3)
        self.assertEqual(self.cache.get("au"), ["ASX:BHP", "ASX:CBA", "ASX:RIO"])

    def test_refresh_with_dict_list_includes_market_cap(self):
        rows = [
            {"ticker": "ASX:BHP", "market_cap": 308000000000, "exchange": "ASX"},
            {"ticker": "ASX:CBA", "market_cap": 255000000000, "exchange": "ASX"},
            {"ticker": "ASX:NAB", "market_cap": 120000000000, "exchange": "ASX"},
        ]
        self.cache.refresh("au", rows)
        # Sorted by market_cap desc
        self.assertEqual(
            self.cache.get("au"),
            ["ASX:BHP", "ASX:CBA", "ASX:NAB"],
        )
        full = self.cache.get_full("au")
        self.assertEqual(full[0]["ticker"], "ASX:BHP")
        self.assertEqual(full[0]["market_cap"], 308000000000)

    def test_refresh_overwrites_previous(self):
        self.cache.refresh("au", ["OLD:TICKER"])
        self.cache.refresh("au", ["NEW:ONE", "NEW:TWO"])
        self.assertEqual(self.cache.get("au"), ["NEW:ONE", "NEW:TWO"])

    def test_refresh_sorts_market_cap_then_ticker(self):
        rows = [
            {"ticker": "B", "market_cap": 100},
            {"ticker": "A", "market_cap": 100},
            {"ticker": "C", "market_cap": 200},
            {"ticker": "D", "market_cap": None},
        ]
        self.cache.refresh("test", rows)
        tickers = self.cache.get("test")
        # C (200) > A,B (100) > D (None)
        self.assertEqual(tickers, ["C", "A", "B", "D"])

    # ---------- get / get_full edge cases ----------

    def test_get_returns_empty_when_not_loaded(self):
        self.assertEqual(self.cache.get("missing"), [])

    def test_get_full_handles_legacy_plain_string_format(self):
        # Simulate an old cache file with plain strings (legacy format)
        d = self.cache._dir("legacy")
        d.mkdir(parents=True, exist_ok=True)
        d.joinpath("tickers.json").write_text(json.dumps(["A:BHP", "A:CBA"]), encoding="utf-8")
        d.joinpath("meta.json").write_text(json.dumps({
            "fetched_at": "2026-09-15", "count": 2, "source": "old"
        }), encoding="utf-8")
        full = self.cache.get_full("legacy")
        self.assertEqual(full, [{"ticker": "A:BHP"}, {"ticker": "A:CBA"}])

    # ---------- invalidate ----------

    def test_invalidate_removes_files(self):
        self.cache.refresh("au", ["A:BHP"])
        self.assertTrue(self.cache.is_loaded("au"))
        self.cache.invalidate("au")
        self.assertFalse(self.cache.is_loaded("au"))
        self.assertTrue(self.cache.is_stale("au"))

    def test_invalidate_missing_is_noop(self):
        self.cache.invalidate("never-existed")  # should not raise

    # ---------- status ----------

    def test_status_reports_all_regions(self):
        self.cache.refresh("au", ["A:BHP"], source="tradingview_screener",
                          filters={"min_market_cap": 200_000_000})
        self.cache.refresh("jp", ["T:8306"], source="tradingview_screener")
        s = self.cache.status()
        self.assertIn("au", s)
        self.assertIn("jp", s)
        self.assertTrue(s["au"]["loaded"])
        self.assertFalse(s["au"]["stale"])
        self.assertEqual(s["au"]["count"], 1)
        self.assertEqual(s["au"]["filters"], {"min_market_cap": 200_000_000})

    def test_filters_with_set_value_gets_jsonified_to_list(self):
        # Sets aren't valid JSON; the cache should coerce them to lists
        self.cache.refresh("test", ["X:Y"], filters={"exchanges": {"ASX", "TWSE"}})
        s = self.cache.status()
        self.assertEqual(s["test"]["filters"]["exchanges"], ["ASX", "TWSE"])

    # ---------- TTL configuration ----------

    def test_shorter_ttl_makes_cache_stale_sooner(self):
        cache_long = UniverseCache(self.tmp, ttl_days=30, today=date(2026, 9, 22))
        cache_long.refresh("au", ["A:BHP"])
        later = UniverseCache(self.tmp, ttl_days=30, today=date(2026, 10, 5))
        self.assertFalse(later.is_stale("au"))  # 13 days, < 30
        very_later = UniverseCache(self.tmp, ttl_days=30, today=date(2026, 10, 25))
        self.assertTrue(very_later.is_stale("au"))  # 33 days

    def test_zero_ttl_means_always_stale(self):
        cache_zero = UniverseCache(self.tmp, ttl_days=0, today=date(2026, 9, 22))
        cache_zero.refresh("au", ["A:BHP"])
        self.assertTrue(cache_zero.is_stale("au"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
