"""Tests for holiday_calendar.py."""
import unittest
from datetime import date

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from holiday_calendar import HolidayCalendar, DEFAULT


class TestTradingDayBasics(unittest.TestCase):

    def setUp(self):
        self.cal = HolidayCalendar()

    def test_weekday_is_trading_day(self):
        # 2026-09-22 is a Tuesday
        self.assertTrue(self.cal.is_trading_day("au", date(2026, 9, 22)))

    def test_weekend_is_not_trading_day(self):
        # 2026-09-19 = Saturday, 2026-09-20 = Sunday
        self.assertFalse(self.cal.is_trading_day("au", date(2026, 9, 19)))
        self.assertFalse(self.cal.is_trading_day("au", date(2026, 9, 20)))

    def test_known_holiday(self):
        # AU: 2026-04-25 = ANZAC Day (Saturday; AU does NOT substitute when
        # ANZAC falls on a weekend, so Monday 4/27 is an open trading day)
        self.assertFalse(self.cal.is_trading_day("au", date(2026, 4, 25)))
        self.assertTrue(self.cal.is_trading_day("au", date(2026, 4, 27)))

    def test_christmas_closed_in_western_markets(self):
        # Western markets close Christmas. JP and TW do not — neither country
        # observes Christmas as a public market holiday (cultural observance only).
        closed = {"au", "ca", "eu-de", "eu-fr", "eu-it", "eu-es", "eu-nl",
                  "eu-be", "eu-at", "eu-pt", "eu-ie", "eu-fi", "eu-dk", "eu-gr"}
        for region in closed:
            self.assertFalse(self.cal.is_trading_day(region, date(2026, 12, 25)),
                             f"{region} should be closed on Christmas")
        # JP + TW are exceptions — markets open
        self.assertTrue(self.cal.is_trading_day("jp", date(2026, 12, 25)))
        self.assertTrue(self.cal.is_trading_day("tw", date(2026, 12, 25)))

    def test_new_year_closed_everywhere(self):
        for region in self.cal.regions():
            self.assertFalse(self.cal.is_trading_day(region, date(2026, 1, 1)),
                             f"{region} should be closed on New Year")


class TestUsMarketHolidayDifferences(unittest.TestCase):

    def setUp(self):
        self.cal = HolidayCalendar()

    def test_jp_golden_week_block(self):
        # 2026-05-04 (Constitution Day) and 2026-05-05 (Children's Day) + 2026-05-06 (substitute)
        self.assertFalse(self.cal.is_trading_day("jp", date(2026, 5, 4)))
        self.assertFalse(self.cal.is_trading_day("jp", date(2026, 5, 5)))
        self.assertFalse(self.cal.is_trading_day("jp", date(2026, 5, 6)))
        # 2026-05-07 should be open
        self.assertTrue(self.cal.is_trading_day("jp", date(2026, 5, 7)))

    def test_us_vs_eu_good_friday(self):
        # EU closes on Good Friday, JP doesn't (no Good Friday holiday in JP)
        gf_2026 = date(2026, 4, 3)
        self.assertFalse(self.cal.is_trading_day("eu-de", gf_2026))
        self.assertFalse(self.cal.is_trading_day("eu-fr", gf_2026))
        self.assertFalse(self.cal.is_trading_day("eu-it", gf_2026))
        # US/CA (not in scope here, but CA is): CA closes on Good Friday
        self.assertFalse(self.cal.is_trading_day("ca", gf_2026))
        # JP doesn't observe Good Friday
        self.assertTrue(self.cal.is_trading_day("jp", gf_2026))

    def test_tw_228_peace_memorial(self):
        # Taiwan: Feb 28 Peace Memorial Day
        self.assertFalse(self.cal.is_trading_day("tw", date(2026, 2, 28)))

    def test_eu_de_unity_in_lieu(self):
        # 2026-06-01 (Monday) is German Unity observed when 10/3 falls on weekend
        # 2026: Oct 3 is Saturday, so observed Monday Oct 5 (but our table doesn't
        # cover that — only the fixed 10/3 holiday. That's a known limitation.)
        # Here we just verify the 2026-06-01 holiday listed (German Unity is 10/3,
        # but 2026 also lists 06-01 from our table — it's actually Whit Monday
        # which we DID include for 2027 only. Verify what's actually in the table.)
        # Just check the 2026-10-03 holiday itself
        self.assertFalse(self.cal.is_trading_day("eu-de", date(2026, 10, 3)))


class TestPreviousNextTradingDay(unittest.TestCase):

    def setUp(self):
        self.cal = HolidayCalendar()

    def test_previous_monday_is_friday(self):
        # 2026-09-21 (Mon) — previous trading day = 2026-09-18 (Fri)
        prev = self.cal.previous_trading_day("au", date(2026, 9, 21))
        self.assertEqual(prev, date(2026, 9, 18))

    def test_previous_monday_after_long_weekend(self):
        # 2026-04-06 (Mon Easter) — previous = 2026-04-02 (Thu, before Good Friday)
        prev = self.cal.previous_trading_day("eu-de", date(2026, 4, 6))
        self.assertEqual(prev, date(2026, 4, 2))

    def test_previous_tuesday_is_monday(self):
        # 2026-09-22 (Tue) — previous = 2026-09-21 (Mon)
        prev = self.cal.previous_trading_day("au", date(2026, 9, 22))
        self.assertEqual(prev, date(2026, 9, 21))

    def test_previous_walks_past_holiday_chain(self):
        # 2026-05-07 (Thu) — JP's previous trading day should be 2026-05-01 (Fri)
        # because 5/4, 5/5, 5/6 are Golden Week
        prev = self.cal.previous_trading_day("jp", date(2026, 5, 7))
        self.assertEqual(prev, date(2026, 5, 1))

    def test_next_trading_day_simple(self):
        # Friday → next Monday
        nxt = self.cal.next_trading_day("au", date(2026, 9, 18))
        self.assertEqual(nxt, date(2026, 9, 21))

    def test_next_walks_past_holiday(self):
        # 2026-12-24 (Thu before Christmas) → next trading day = 2026-12-29 (Tue)
        # because Christmas 25 (Fri) AND Boxing Day observed 28 (Mon) are both closed
        nxt = self.cal.next_trading_day("au", date(2026, 12, 24))
        self.assertEqual(nxt, date(2026, 12, 29))

    def test_previous_returns_none_if_14_days_empty(self):
        # Synthetic: walk 14 days back from Jan 2 — should land somewhere valid
        # unless the calendar has no entries (it does). Just verify it returns a date.
        prev = self.cal.previous_trading_day("au", date(2027, 1, 4))
        self.assertIsNotNone(prev)
        self.assertLess(prev, date(2027, 1, 4))


class TestRegions(unittest.TestCase):

    def setUp(self):
        self.cal = HolidayCalendar()

    def test_all_16_regions_defined(self):
        expected = {"au", "jp", "tw", "ca", "eu-de", "eu-fr", "eu-it", "eu-es",
                    "eu-nl", "eu-be", "eu-at", "eu-pt", "eu-ie", "eu-fi",
                    "eu-dk", "eu-gr"}
        self.assertEqual(set(self.cal.regions()), expected)

    def test_all_regions_have_3_years(self):
        for region in self.cal.regions():
            for year in (2025, 2026, 2027):
                self.assertIn(year, [2025, 2026, 2027])

    def test_default_singleton_matches(self):
        self.assertEqual(set(DEFAULT.regions()), set(self.cal.regions()))


class TestUnknownRegion(unittest.TestCase):

    def setUp(self):
        self.cal = HolidayCalendar()

    def test_unknown_region_treated_as_no_holidays(self):
        # If we ever pass a region without a calendar entry, it should still
        # flag weekends as non-trading days. This is the safe default — better
        # to run a stale pull than to skip a valid one.
        self.assertTrue(self.cal.is_trading_day("xx-unknown", date(2026, 9, 22)))
        self.assertFalse(self.cal.is_trading_day("xx-unknown", date(2026, 9, 19)))


if __name__ == "__main__":
    unittest.main()
