"""Tests for run_intl_cron.py — the cron-time orchestrator."""
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from run_intl_cron import (
    plan_cron_run,
    finalize_cron_run,
    previous_trading_day_for_movers,
    _detect_regressions,
    _emit_audit_lines,
)
from holiday_calendar import HolidayCalendar


def _make_cache_root():
    """Create a temp cache root with UniverseCache seeded for all 16 regions."""
    return Path(tempfile.mkdtemp())


def _seed_universe_cache(root: Path, today: date, tickers_by_region: dict[str, list[str]]):
    """Populate the universe cache for the given regions."""
    from universe_cache import UniverseCache
    cache = UniverseCache(root, today=today)
    for region, tickers in tickers_by_region.items():
        # Sort by market_cap desc — pass fake market_caps so we can verify ordering
        rows = [
            {"ticker": t, "market_cap": (len(tickers) - i) * 1_000_000,
             "exchange": "ASX" if region == "au" else "TSE"}
            for i, t in enumerate(tickers)
        ]
        cache.refresh(region, rows)


class TestPlanCronRun(unittest.TestCase):

    def setUp(self):
        self.universe_root = _make_cache_root()
        self.enrich_root = _make_cache_root()
        self.csv_root = Path(self.universe_root) / "historical_eod"
        self.csv_root.mkdir()
        self.today = date(2026, 9, 22)  # Tuesday
        # Seed cache for a few regions
        _seed_universe_cache(self.universe_root, self.today, {
            "au": [f"ASX:T{i:03d}" for i in range(2000)],
            "jp": [f"TSE:J{i:03d}" for i in range(2000)],
            "tw": [f"TWSE:T{i:03d}" for i in range(2000)],
        })

    def test_plan_returns_required_keys(self):
        plan = plan_cron_run(
            today=self.today,
            csv_root=self.csv_root,
            universe_cache_root=self.universe_root,
            enrichment_cache_root=self.enrich_root,
        )
        for k in ("today", "skip_regions", "screener_refresh", "stock_prices",
                  "yahoo_batches", "movers_regions", "audit"):
            self.assertIn(k, plan)

    def test_skip_regions_includes_holidays(self):
        # 2026-09-22 (Tue) is JP's Respect for the Aged Day → JP skipped
        plan = plan_cron_run(
            today=self.today,
            csv_root=self.csv_root,
            universe_cache_root=self.universe_root,
            enrichment_cache_root=self.enrich_root,
        )
        self.assertIn("jp", plan["skip_regions"])
        self.assertNotIn("au", plan["skip_regions"])

    def test_skip_regions_includes_weekend(self):
        # 2026-09-19 = Saturday → all regions skipped
        plan = plan_cron_run(
            today=date(2026, 9, 19),
            csv_root=self.csv_root,
            universe_cache_root=self.universe_root,
            enrichment_cache_root=self.enrich_root,
        )
        self.assertEqual(len(plan["skip_regions"]), 16)

    def test_yahoo_batches_size_is_ten(self):
        plan = plan_cron_run(
            today=self.today,
            csv_root=self.csv_root,
            universe_cache_root=self.universe_root,
            enrichment_cache_root=self.enrich_root,
            top_n_yahoo=500,
        )
        for batch in plan["yahoo_batches"]:
            self.assertLessEqual(len(batch), 10)
            # Each entry is (tv, yt)
            for entry in batch:
                self.assertEqual(len(entry), 2)
                self.assertIn(":", entry[0])  # EXCHANGE:SYMBOL

    def test_yahoo_call_count_first_run(self):
        # Day 1 with no enrichment cache → all top-N tickers need volume refresh
        plan = plan_cron_run(
            today=self.today,
            csv_root=self.csv_root,
            universe_cache_root=self.universe_root,
            enrichment_cache_root=self.enrich_root,
            top_n_yahoo=500,
        )
        # JP is skipped (Respect for the Aged Day). Active regions: au + tw.
        # Each region: 500 tickers / 10 per batch = 50 batches × 10 = 500 calls.
        # Total: 1000.
        self.assertEqual(plan["audit"]["yahoo_call_count"], 1000)

    def test_yahoo_call_count_drops_after_cache_warmup(self):
        # Day 30+: only new tickers + volume refresh needed
        # First seed enrichment cache with fresh volume for all top-N
        from enrichment_cache import EnrichmentCache
        ec = EnrichmentCache(self.enrich_root, today=self.today)
        warmup = {}
        for region in ("au", "tw"):
            for i in range(500):
                tv = f"{'ASX' if region == 'au' else 'TWSE'}:T{i:03d}"
                warmup[tv] = {"volume": 1000, "pe_ratio": 10, "sector": "Tech"}
        ec.bulk_set(warmup)

        # Run plan again — only need refresh for tickers beyond top-500
        plan = plan_cron_run(
            today=self.today,
            csv_root=self.csv_root,
            universe_cache_root=self.universe_root,
            enrichment_cache_root=self.enrich_root,
            top_n_yahoo=500,
        )
        # All top-500 are fresh → no batches needed
        self.assertEqual(plan["audit"]["yahoo_call_count"], 0)

    def test_movers_mode_enabled_mon_thu(self):
        plan = plan_cron_run(
            today=date(2026, 9, 21),  # Monday
            csv_root=self.csv_root,
            universe_cache_root=self.universe_root,
            enrichment_cache_root=self.enrich_root,
        )
        # Movers auto-enabled Mon-Thu
        self.assertTrue(plan["audit"]["movers_enabled"])
        self.assertGreater(len(plan["movers_regions"]), 0)

    def test_movers_mode_disabled_on_friday(self):
        plan = plan_cron_run(
            today=date(2026, 9, 25),  # Friday
            csv_root=self.csv_root,
            universe_cache_root=self.universe_root,
            enrichment_cache_root=self.enrich_root,
        )
        self.assertFalse(plan["audit"]["movers_enabled"])
        self.assertEqual(plan["movers_regions"], [])

    def test_screener_refresh_for_stale_regions(self):
        # Seed cache as 7 days old
        old_today = self.today - timedelta(days=8)
        _seed_universe_cache(self.universe_root, old_today, {
            "au": [f"ASX:T{i:03d}" for i in range(100)],
        })
        plan = plan_cron_run(
            today=self.today,
            csv_root=self.csv_root,
            universe_cache_root=self.universe_root,
            enrichment_cache_root=self.enrich_root,
        )
        self.assertIn("au", plan["screener_refresh"])

    def test_no_movers_when_disabled(self):
        plan = plan_cron_run(
            today=date(2026, 9, 22),  # Tuesday
            csv_root=self.csv_root,
            universe_cache_root=self.universe_root,
            enrichment_cache_root=self.enrich_root,
            movers_enabled=False,
        )
        self.assertFalse(plan["audit"]["movers_enabled"])
        self.assertEqual(plan["movers_regions"], [])


class TestPreviousTradingDayForMovers(unittest.TestCase):

    def test_monday_uses_friday(self):
        # 2026-09-21 = Monday → previous = 2026-09-18 (Fri)
        prev = previous_trading_day_for_movers(date(2026, 9, 21))
        self.assertEqual(prev, date(2026, 9, 18))

    def test_tuesday_uses_monday(self):
        # 2026-09-22 = Tuesday → previous = 2026-09-21 (Mon)
        prev = previous_trading_day_for_movers(date(2026, 9, 22))
        self.assertEqual(prev, date(2026, 9, 21))

    def test_friday_uses_thursday(self):
        # 2026-09-25 = Friday → previous = 2026-09-24 (Thu)
        prev = previous_trading_day_for_movers(date(2026, 9, 25))
        self.assertEqual(prev, date(2026, 9, 24))


class TestFinalizeCronRun(unittest.TestCase):

    def setUp(self):
        self.universe_root = _make_cache_root()
        self.enrich_root = _make_cache_root()
        self.csv_root = Path(self.universe_root) / "historical_eod"
        self.csv_root.mkdir()
        self.today = date(2026, 9, 22)
        _seed_universe_cache(self.universe_root, self.today, {
            "au": ["ASX:BHP", "ASX:CBA", "ASX:RIO"],
            "jp": ["TSE:7203", "TSE:9984"],  # will be skipped — JP holiday
        })

    def test_finalize_writes_csv(self):
        responses = {
            "region_data": {
                "au": [
                    {"ticker": "ASX:BHP", "description": "BHP Group",
                     "price": 40.5, "open": 40.0, "high": 41.0, "low": 39.8,
                     "currency": "AUD", "exchange": "ASX",
                     "change_percent": 1.5, "market_cap": 130_000_000_000},
                    {"ticker": "ASX:CBA", "description": "Commonwealth Bank",
                     "price": 150.0, "open": 149.0, "high": 151.0, "low": 148.5,
                     "currency": "AUD", "exchange": "ASX",
                     "change_percent": 0.7, "market_cap": 200_000_000_000},
                ],
            },
            "yahoo_enrich": {
                "au": {
                    "ASX:BHP": {"volume": 5_000_000, "pe_ratio": 12.0, "sector": "Materials"},
                    "ASX:CBA": {"volume": 2_000_000, "pe_ratio": 18.0, "sector": "Financials"},
                },
            },
        }
        result = finalize_cron_run(
            responses=responses,
            today=self.today,
            csv_root=self.csv_root,
            universe_cache_root=self.universe_root,
            enrichment_cache_root=self.enrich_root,
        )
        self.assertIn("au", result["regions"])
        self.assertEqual(result["regions"]["au"], 2)
        # Verify CSV was written
        csv_path = self.csv_root / "au" / f"{self.today.isoformat()}.csv"
        self.assertTrue(csv_path.exists())

    def test_finalize_writes_enrichment_back_to_cache(self):
        responses = {
            "region_data": {
                "au": [
                    {"ticker": "ASX:BHP", "description": "BHP", "price": 40.5,
                     "open": 40.0, "high": 41.0, "low": 39.8,
                     "currency": "AUD", "exchange": "ASX",
                     "change_percent": 1.5, "market_cap": 130_000_000_000},
                ],
            },
            "yahoo_enrich": {
                "au": {
                    "ASX:BHP": {"volume": 5_000_000, "pe_ratio": 12.0, "sector": "Materials"},
                },
            },
        }
        finalize_cron_run(
            responses=responses,
            today=self.today,
            csv_root=self.csv_root,
            universe_cache_root=self.universe_root,
            enrichment_cache_root=self.enrich_root,
        )
        # Verify cache was populated
        from enrichment_cache import EnrichmentCache
        ec = EnrichmentCache(self.enrich_root, today=self.today)
        entry = ec.get("ASX:BHP")
        self.assertEqual(entry["volume"], 5_000_000)
        self.assertEqual(entry["pe_ratio"], 12.0)
        self.assertEqual(entry["sector"], "Materials")
        self.assertTrue(entry["_fresh"]["volume"])

    def test_finalize_emits_audit_lines(self):
        responses = {"region_data": {"au": []}, "yahoo_enrich": {}}
        result = finalize_cron_run(
            responses=responses,
            today=self.today,
            csv_root=self.csv_root,
            universe_cache_root=self.universe_root,
            enrichment_cache_root=self.enrich_root,
        )
        # Empty region_data → no rows → no per-region audit, but a summary
        # may still be emitted (or not, depending on whether regions is empty)
        self.assertIsInstance(result["audit_lines"], list)


class TestRegressionDetector(unittest.TestCase):

    def setUp(self):
        self.csv_root = Path(tempfile.mkdtemp())
        self.today = date(2026, 9, 22)
        # Create 5 prior days of CSVs for "au" with 100 rows each
        for i in range(1, 6):
            day = self.today - timedelta(days=i)
            d = self.csv_root / "au"
            d.mkdir(parents=True, exist_ok=True)
            with open(d / f"{day.isoformat()}.csv", "w", encoding="utf-8") as fh:
                fh.write("date,ticker,name,open,high,low,close,volume,change_pct,market_cap,pe_ratio,sector,currency,exchange\n")
                for j in range(100):
                    fh.write(f"{day.isoformat()},T{j:03d},,\n")

    def test_no_alert_when_count_stable(self):
        alerts = _detect_regressions(self.today, self.csv_root, {"au": 100})
        self.assertEqual(alerts, [])

    def test_alert_when_count_drops_more_than_30pct(self):
        alerts = _detect_regressions(self.today, self.csv_root, {"au": 50})
        self.assertEqual(len(alerts), 1)
        self.assertIn("region=au", alerts[0])
        self.assertIn("today=50", alerts[0])

    def test_no_alert_when_too_few_prior_days(self):
        # Only 1 prior day → not enough to compute median
        import shutil
        shutil.rmtree(self.csv_root / "au")
        (self.csv_root / "au").mkdir()
        with open(self.csv_root / "au" / "2026-09-21.csv", "w", encoding="utf-8") as fh:
            fh.write("date,ticker\n")
            for j in range(100):
                fh.write("2026-09-21,T\n")
        alerts = _detect_regressions(self.today, self.csv_root, {"au": 50})
        self.assertEqual(alerts, [])


class TestEmitAuditLines(unittest.TestCase):

    def test_per_region_lines(self):
        lines = _emit_audit_lines(date(2026, 9, 22), {"au": 1623, "jp": 2000})
        self.assertEqual(len(lines), 3)  # 2 regions + 1 summary
        self.assertIn("region=au rows=1623", lines[0])
        self.assertIn("region=jp rows=2000", lines[1])
        self.assertIn("regions=2 rows=3623", lines[2])

    def test_empty_region_dict(self):
        lines = _emit_audit_lines(date(2026, 9, 22), {})
        self.assertEqual(len(lines), 1)  # just summary
        self.assertIn("regions=0 rows=0", lines[0])


if __name__ == "__main__":
    unittest.main()
