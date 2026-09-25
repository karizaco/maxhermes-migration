"""Tests for enrichment_cache.py."""
import unittest
from datetime import date, timedelta
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from enrichment_cache import EnrichmentCache, DEFAULT_TTL


class TestEnrichmentCacheBasics(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(self._tmpdir())
        self.cache = EnrichmentCache(self.tmp, today=date(2026, 9, 22))

    def _tmpdir(self):
        import tempfile
        return tempfile.mkdtemp()

    def test_empty_cache_returns_empty_dict(self):
        result = self.cache.get("ASX:BHP")
        self.assertEqual(result["volume"], None)
        self.assertEqual(result["pe_ratio"], None)
        self.assertEqual(result["sector"], None)
        self.assertEqual(result["_fresh"], {"volume": False, "pe_ratio": False, "sector": False})

    def test_set_then_get_round_trip(self):
        self.cache.set("ASX:BHP", {"volume": 1234567, "pe_ratio": 12.5, "sector": "Materials"})
        result = self.cache.get("ASX:BHP")
        self.assertEqual(result["volume"], 1234567)
        self.assertEqual(result["pe_ratio"], 12.5)
        self.assertEqual(result["sector"], "Materials")

    def test_set_today_is_fresh(self):
        self.cache.set("ASX:BHP", {"volume": 100})
        result = self.cache.get("ASX:BHP")
        self.assertTrue(result["_fresh"]["volume"])  # TTL=1, same day → fresh
        # pe_ratio + sector never set → still stale
        self.assertFalse(result["_fresh"]["pe_ratio"])
        self.assertFalse(result["_fresh"]["sector"])

    def test_set_with_only_subset_updates_partially(self):
        self.cache.set("ASX:BHP", {"volume": 100, "pe_ratio": 10.0, "sector": "Tech"})
        # Advance to day 2: volume is stale (TTL=1, day=1 elapsed), pe/sector fresh
        cache2 = EnrichmentCache(self.tmp, today=date(2026, 9, 23))
        self.cache.set("ASX:BHP", {"volume": 200}, only=["volume"])
        result = cache2.get("ASX:BHP")
        self.assertEqual(result["volume"], 200)  # updated
        self.assertEqual(result["pe_ratio"], 10.0)  # preserved
        self.assertEqual(result["sector"], "Tech")  # preserved

    def test_set_only_unknown_field_raises(self):
        with self.assertRaises(ValueError):
            self.cache.set("ASX:BHP", {"not_a_field": 1}, only=["not_a_field"])

    def test_set_preserves_prior_freshness_on_other_fields(self):
        self.cache.set("ASX:BHP", {"volume": 100, "pe_ratio": 10.0})
        # Day 31: pe_ratio is stale (TTL=30, day=30 elapsed → not fresh)
        cache2 = EnrichmentCache(self.tmp, today=date(2026, 10, 22))
        cache2.set("ASX:BHP", {"volume": 200}, only=["volume"])
        result = cache2.get("ASX:BHP")
        # volume freshness advanced to day 31
        self.assertTrue(result["_fresh"]["volume"])
        # pe_ratio stayed on day 1
        self.assertFalse(result["_fresh"]["pe_ratio"])


class TestStaleness(unittest.TestCase):

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())

    def _cache(self, day):
        return EnrichmentCache(self.tmp, today=day)

    def test_volume_stale_after_one_day(self):
        self._cache(date(2026, 9, 22)).set("X", {"volume": 1})
        day2 = self._cache(date(2026, 9, 23))
        result = day2.get("X")
        self.assertFalse(result["_fresh"]["volume"])

    def test_pe_ratio_fresh_within_thirty_days(self):
        self._cache(date(2026, 9, 22)).set("X", {"pe_ratio": 12.0})
        day15 = self._cache(date(2026, 10, 6))  # +14 days
        result = day15.get("X")
        self.assertTrue(result["_fresh"]["pe_ratio"])

    def test_pe_ratio_stale_after_thirty_days(self):
        self._cache(date(2026, 9, 22)).set("X", {"pe_ratio": 12.0})
        day32 = self._cache(date(2026, 10, 23))  # +31 days
        result = day32.get("X")
        self.assertFalse(result["_fresh"]["pe_ratio"])

    def test_stale_fields_returns_set(self):
        cache = self._cache(date(2026, 9, 22))
        cache.set("X", {"pe_ratio": 10.0})
        # Day 2: volume + sector still missing → stale; pe still fresh
        day2 = self._cache(date(2026, 9, 23))
        stale = day2.stale_fields("X")
        self.assertEqual(stale, {"volume", "sector"})

    def test_bulk_stale_fields(self):
        cache = self._cache(date(2026, 9, 22))
        cache.set("A", {"volume": 1, "pe_ratio": 10})
        cache.set("B", {"sector": "Tech"})
        cache.set("C", {})  # nothing
        day2 = self._cache(date(2026, 9, 23))
        out = day2.bulk_stale_fields(["A", "B", "C", "D"])
        # A: day1 set {volume, pe_ratio}; day2 volume stale (TTL=1), pe still fresh, sector never set
        self.assertEqual(out["A"], {"volume", "sector"})
        # B: day1 set {sector}; day2 sector still fresh, volume+pe never set
        self.assertEqual(out["B"], {"volume", "pe_ratio"})
        # C: nothing set on day1 → all 3 stale on day2
        self.assertEqual(out["C"], {"volume", "pe_ratio", "sector"})
        # D: never cached → same as C
        self.assertEqual(out["D"], {"volume", "pe_ratio", "sector"})


class TestBulkAndPersistence(unittest.TestCase):

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())

    def test_bulk_set_one_pass(self):
        cache = EnrichmentCache(self.tmp, today=date(2026, 9, 22))
        cache.bulk_set({
            "A": {"volume": 1, "pe_ratio": 10},
            "B": {"sector": "Tech"},
        })
        self.assertEqual(cache.get("A")["volume"], 1)
        self.assertEqual(cache.get("B")["sector"], "Tech")

    def test_bulk_set_with_only_subset(self):
        cache = EnrichmentCache(self.tmp, today=date(2026, 9, 22))
        cache.set("A", {"volume": 1, "pe_ratio": 10, "sector": "Energy"})
        # Advance: bulk-set volume only → pe/sector preserved
        day2 = EnrichmentCache(self.tmp, today=date(2026, 9, 23))
        day2.bulk_set({"A": {"volume": 999}}, only=["volume"])
        result = day2.get("A")
        self.assertEqual(result["volume"], 999)
        self.assertEqual(result["pe_ratio"], 10)
        self.assertEqual(result["sector"], "Energy")

    def test_persistence_across_instances(self):
        cache1 = EnrichmentCache(self.tmp, today=date(2026, 9, 22))
        cache1.set("X", {"volume": 100, "pe_ratio": 12.0})
        cache2 = EnrichmentCache(self.tmp, today=date(2026, 9, 22))
        self.assertEqual(cache2.get("X")["volume"], 100)
        self.assertEqual(cache2.get("X")["pe_ratio"], 12.0)

    def test_size(self):
        cache = EnrichmentCache(self.tmp, today=date(2026, 9, 22))
        self.assertEqual(cache.size(), 0)
        cache.set("A", {"volume": 1})
        cache.set("B", {"volume": 2})
        self.assertEqual(cache.size(), 2)

    def test_invalidate_drops_entry(self):
        cache = EnrichmentCache(self.tmp, today=date(2026, 9, 22))
        cache.set("X", {"volume": 100})
        cache.invalidate("X")
        result = cache.get("X")
        self.assertEqual(result["volume"], None)  # gone

    def test_status_reports_freshness(self):
        cache = EnrichmentCache(self.tmp, today=date(2026, 9, 22))
        cache.set("A", {"volume": 1, "pe_ratio": 10, "sector": "Tech"})
        cache.set("B", {"pe_ratio": 12})
        cache.set("C", {"sector": "Energy"})
        st = cache.status()
        self.assertEqual(st["cached_tickers"], 3)
        self.assertEqual(st["fresh_count"]["volume"], 1)
        self.assertEqual(st["fresh_count"]["pe_ratio"], 2)
        self.assertEqual(st["fresh_count"]["sector"], 2)
        self.assertEqual(st["ttl_days"], {"volume": 1, "pe_ratio": 30, "sector": 30})


class TestDefaultTtl(unittest.TestCase):

    def test_default_ttl_values(self):
        self.assertEqual(DEFAULT_TTL, {"volume": 1, "pe_ratio": 30, "sector": 30})

    def test_custom_ttl_overrides(self):
        import tempfile
        cache = EnrichmentCache(Path(tempfile.mkdtemp()),
                                 ttl_days={"volume": 7, "pe_ratio": 90, "sector": 365})
        self.assertEqual(cache.ttl["volume"], 7)
        self.assertEqual(cache.ttl["pe_ratio"], 90)
        self.assertEqual(cache.ttl["sector"], 365)


if __name__ == "__main__":
    unittest.main()
