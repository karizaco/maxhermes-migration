"""
holiday_calendar.py — per-exchange trading-day calendar for the 16 regions.

The v2 cron needs to know two things:

  1. Is `today` a trading day for `<region>`? Skip the cron if not (don't
     write a stale CSV on a holiday).
  2. What was the most recent prior trading day? Movers-mode uses this as the
     anchor for "yesterday" — Mon pulls from Friday, Tue from Mon, etc.

Holiday data is public and stable year-over-year, but the specific dates shift
each year. This module ships a hardcoded list for 2025 + 2026 + 2027 covering
the 16 regions in scope. It's intentionally simple — no observed-day handling,
no lunar calendars — the goal is "good enough" to avoid empty/stale CSVs.

Public API
----------
    cal = HolidayCalendar()
    cal.is_trading_day(region, date) -> bool
    cal.previous_trading_day(region, date) -> date
    cal.regions() -> list[str]
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable


# Region code → (trading days/week). Used to skip weekends consistently.
# All 16 regions are Mon-Fri; the SHIBOL/religious exceptions are baked into
# the holiday list below.
TRADING_WEEKDAYS = {0, 1, 2, 3, 4}  # Mon=0 .. Fri=4


# Per-region holiday lists for 2025 / 2026 / 2027.
# Source: each exchange's published holiday calendar. Lunar/Easter-based holidays
# (JP Golden Week overlap, EU Good Friday) are precomputed.
# Dates use ISO format. Keep these sorted within each year for readability.
HOLIDAYS: dict[str, dict[int, list[date]]] = {
    "au": {  # ASX
        2025: [
            date(2025, 1, 1),   # New Year's Day
            date(2025, 1, 27),  # Australia Day observed (Sunday → Monday)
            date(2025, 4, 18),  # Good Friday
            date(2025, 4, 21),  # Easter Monday
            date(2025, 4, 25),  # ANZAC Day
            date(2025, 6, 9),   # King's Birthday
            date(2025, 12, 25), # Christmas
            date(2025, 12, 26), # Boxing Day
        ],
        2026: [
            date(2026, 1, 1),
            date(2026, 1, 26),
            date(2026, 4, 3),   # Good Friday
            date(2026, 4, 6),   # Easter Monday
            date(2026, 4, 25),
            date(2026, 6, 8),
            date(2026, 12, 25),
            date(2026, 12, 28), # Boxing Day observed (26=Fri+Sat, observed Mon)
        ],
        2027: [
            date(2027, 1, 1),
            date(2027, 1, 26),
            date(2027, 3, 26),  # Good Friday
            date(2027, 3, 29),  # Easter Monday
            date(2027, 4, 26),  # ANZAC Day observed (Sun → Mon)
            date(2027, 6, 14),  # King's Birthday
            date(2027, 12, 27), # Christmas observed (Sat → Mon)
            date(2027, 12, 28), # Boxing Day observed (Sun → Mon)
        ],
    },
    "jp": {  # TSE
        2025: [
            date(2025, 1, 1), date(2025, 1, 13),
            date(2025, 2, 11), date(2025, 2, 24),
            date(2025, 3, 20), date(2025, 4, 29),
            date(2025, 5, 3), date(2025, 5, 4), date(2025, 5, 5), date(2025, 5, 6),
            date(2025, 7, 21), date(2025, 8, 11),
            date(2025, 9, 15), date(2025, 9, 23),
            date(2025, 10, 13), date(2025, 11, 3), date(2025, 11, 24),
        ],
        2026: [
            date(2026, 1, 1), date(2026, 1, 12),
            date(2026, 2, 11), date(2026, 2, 23),
            date(2026, 3, 20), date(2026, 4, 29),
            date(2026, 5, 4), date(2026, 5, 5), date(2026, 5, 6),
            date(2026, 7, 20), date(2026, 8, 11),
            date(2026, 9, 21), date(2026, 9, 22), date(2026, 9, 23),
            date(2026, 10, 12), date(2026, 11, 3), date(2026, 11, 23),
        ],
        2027: [
            date(2027, 1, 1), date(2027, 1, 11),
            date(2027, 2, 11), date(2027, 2, 23),
            date(2027, 3, 22), date(2027, 4, 29),
            date(2027, 5, 3), date(2027, 5, 4), date(2027, 5, 5),
            date(2027, 7, 19), date(2027, 8, 11),
            date(2027, 9, 20), date(2027, 9, 21), date(2027, 9, 22), date(2027, 9, 23),
            date(2027, 10, 11), date(2027, 11, 3), date(2027, 11, 23),
        ],
    },
    "tw": {  # TWSE
        2025: [
            date(2025, 1, 1), date(2025, 1, 27), date(2025, 1, 28),
            date(2025, 2, 28), date(2025, 4, 3), date(2025, 4, 4),
            date(2025, 5, 1), date(2025, 5, 30), date(2025, 9, 1),
            date(2025, 10, 10), date(2025, 10, 24),
        ],
        2026: [
            date(2026, 1, 1), date(2026, 2, 16), date(2026, 2, 17),
            date(2026, 2, 27), date(2026, 3, 27), date(2026, 5, 1),
            date(2026, 6, 19), date(2026, 9, 25),
            date(2026, 10, 10), date(2026, 10, 26),
        ],
        2027: [
            date(2027, 1, 1), date(2027, 2, 5), date(2027, 2, 6),
            date(2027, 2, 16), date(2027, 3, 26), date(2027, 5, 1),
            date(2027, 6, 9), date(2027, 9, 15),
            date(2027, 10, 10), date(2027, 10, 25),
        ],
    },
    "ca": {  # TSX
        2025: [
            date(2025, 1, 1), date(2025, 2, 17), date(2025, 4, 18),
            date(2025, 5, 19), date(2025, 7, 1), date(2025, 8, 4),
            date(2025, 9, 1), date(2025, 10, 13),
            date(2025, 11, 11), date(2025, 12, 25), date(2025, 12, 26),
        ],
        2026: [
            date(2026, 1, 1), date(2026, 2, 16), date(2026, 4, 3),
            date(2026, 5, 18), date(2026, 7, 1), date(2026, 8, 3),
            date(2026, 9, 7), date(2026, 10, 12),
            date(2026, 11, 11), date(2026, 12, 25), date(2026, 12, 28),
        ],
        2027: [
            date(2027, 1, 1), date(2027, 2, 15), date(2027, 3, 26),
            date(2027, 5, 24), date(2027, 7, 1), date(2027, 8, 2),
            date(2027, 9, 6), date(2027, 10, 11),
            date(2027, 11, 11), date(2027, 12, 27), date(2027, 12, 28),
        ],
    },
    "eu-de": {  # Xetra — common EU holidays, DE-specific bits
        2025: [
            date(2025, 1, 1), date(2025, 4, 18), date(2025, 4, 21),
            date(2025, 5, 1), date(2025, 6, 9),
            date(2025, 12, 25), date(2025, 12, 26),
        ],
        2026: [
            date(2026, 1, 1), date(2026, 4, 3), date(2026, 4, 6),
            date(2026, 5, 1), date(2026, 6, 1),
            date(2026, 12, 25), date(2026, 12, 28),
        ],
        2027: [
            date(2027, 1, 1), date(2027, 3, 26), date(2027, 3, 29),
            date(2027, 5, 1), date(2027, 5, 24),  # Whit Monday
            date(2027, 12, 27), date(2027, 12, 28),
        ],
    },
    "eu-fr": {  # Euronext Paris
        2025: [
            date(2025, 1, 1), date(2025, 4, 18), date(2025, 4, 21),
            date(2025, 5, 1), date(2025, 12, 25), date(2025, 12, 26),
        ],
        2026: [
            date(2026, 1, 1), date(2026, 4, 3), date(2026, 4, 6),
            date(2026, 5, 1), date(2026, 12, 25),
        ],
        2027: [
            date(2027, 1, 1), date(2027, 3, 26), date(2027, 3, 29),
            date(2027, 5, 1), date(2027, 12, 27),
        ],
    },
    "eu-it": {  # Borsa Italiana
        2025: [
            date(2025, 1, 1), date(2025, 4, 18), date(2025, 4, 21),
            date(2025, 4, 25), date(2025, 5, 1),
            date(2025, 8, 15), date(2025, 11, 1),
            date(2025, 12, 25), date(2025, 12, 26),
        ],
        2026: [
            date(2026, 1, 1), date(2026, 1, 6), date(2026, 4, 3),
            date(2026, 4, 6), date(2026, 4, 25), date(2026, 5, 1),
            date(2026, 8, 15), date(2026, 11, 1),
            date(2026, 12, 25), date(2026, 12, 26),
        ],
        2027: [
            date(2027, 1, 1), date(2027, 1, 6), date(2027, 3, 26),
            date(2027, 3, 29), date(2027, 4, 25), date(2027, 5, 1),
            date(2027, 8, 15), date(2027, 11, 1),
            date(2027, 12, 27), date(2027, 12, 28),
        ],
    },
    "eu-es": {  # BME Madrid
        2025: [
            date(2025, 1, 1), date(2025, 1, 6), date(2025, 4, 18),
            date(2025, 4, 21), date(2025, 5, 1),
            date(2025, 8, 15), date(2025, 10, 12),
            date(2025, 11, 1), date(2025, 12, 6),
            date(2025, 12, 25), date(2025, 12, 26),
        ],
        2026: [
            date(2026, 1, 1), date(2026, 1, 6), date(2026, 4, 3),
            date(2026, 4, 6), date(2026, 5, 1),
            date(2026, 8, 15), date(2026, 10, 12),
            date(2026, 11, 1), date(2026, 12, 6),
            date(2026, 12, 25), date(2026, 12, 26),
        ],
        2027: [
            date(2027, 1, 1), date(2027, 1, 6), date(2027, 3, 26),
            date(2027, 3, 29), date(2027, 5, 1),
            date(2027, 8, 15), date(2027, 10, 12),
            date(2027, 11, 1), date(2027, 12, 6),
            date(2027, 12, 25), date(2027, 12, 26),
        ],
    },
    "eu-nl": {  # Euronext Amsterdam
        2025: [
            date(2025, 1, 1), date(2025, 4, 18), date(2025, 4, 21),
            date(2025, 4, 26), date(2025, 5, 5),
            date(2025, 5, 29), date(2025, 6, 9),
            date(2025, 12, 25), date(2025, 12, 26),
        ],
        2026: [
            date(2026, 1, 1), date(2026, 4, 3), date(2026, 4, 6),
            date(2026, 4, 27), date(2026, 5, 5),
            date(2026, 5, 14), date(2026, 6, 1),
            date(2026, 12, 25), date(2026, 12, 28),
        ],
        2027: [
            date(2027, 1, 1), date(2027, 3, 26), date(2027, 3, 29),
            date(2027, 4, 26), date(2027, 5, 5),
            date(2027, 5, 27), date(2027, 6, 1),
            date(2027, 12, 27), date(2027, 12, 28),
        ],
    },
    "eu-be": {  # Euronext Brussels
        2025: [
            date(2025, 1, 1), date(2025, 4, 18), date(2025, 4, 21),
            date(2025, 5, 1), date(2025, 5, 29),
            date(2025, 7, 21), date(2025, 8, 15),
            date(2025, 11, 1), date(2025, 11, 11),
            date(2025, 12, 25), date(2025, 12, 26),
        ],
        2026: [
            date(2026, 1, 1), date(2026, 4, 3), date(2026, 4, 6),
            date(2026, 5, 1), date(2026, 5, 14),
            date(2026, 7, 21), date(2026, 8, 15),
            date(2026, 11, 1), date(2026, 11, 11),
            date(2026, 12, 25), date(2026, 12, 28),
        ],
        2027: [
            date(2027, 1, 1), date(2027, 3, 26), date(2027, 3, 29),
            date(2027, 5, 1), date(2027, 5, 27),
            date(2027, 7, 21), date(2027, 8, 15),
            date(2027, 11, 1), date(2027, 11, 11),
            date(2027, 12, 27), date(2027, 12, 28),
        ],
    },
    "eu-at": {  # Vienna
        2025: [
            date(2025, 1, 1), date(2025, 1, 6), date(2025, 4, 18),
            date(2025, 4, 21), date(2025, 5, 1),
            date(2025, 6, 9), date(2025, 10, 26),
            date(2025, 11, 1), date(2025, 12, 8),
            date(2025, 12, 25), date(2025, 12, 26),
        ],
        2026: [
            date(2026, 1, 1), date(2026, 1, 6), date(2026, 4, 3),
            date(2026, 4, 6), date(2026, 5, 1),
            date(2026, 6, 1), date(2026, 10, 26),
            date(2026, 11, 1), date(2026, 12, 8),
            date(2026, 12, 25), date(2026, 12, 28),
        ],
        2027: [
            date(2027, 1, 1), date(2027, 1, 6), date(2027, 3, 26),
            date(2027, 3, 29), date(2027, 5, 1),
            date(2027, 6, 1), date(2027, 10, 26),
            date(2027, 11, 1), date(2027, 12, 8),
            date(2027, 12, 27), date(2027, 12, 28),
        ],
    },
    "eu-pt": {  # Euronext Lisbon
        2025: [
            date(2025, 1, 1), date(2025, 4, 18), date(2025, 4, 25),
            date(2025, 5, 1), date(2025, 6, 10),
            date(2025, 8, 15), date(2025, 10, 5),
            date(2025, 11, 1), date(2025, 12, 1),
            date(2025, 12, 25), date(2025, 12, 26),
        ],
        2026: [
            date(2026, 1, 1), date(2026, 4, 3), date(2026, 4, 25),
            date(2026, 5, 1), date(2026, 6, 4),
            date(2026, 8, 15), date(2026, 10, 5),
            date(2026, 11, 1), date(2026, 12, 1),
            date(2026, 12, 25), date(2026, 12, 28),
        ],
        2027: [
            date(2027, 1, 1), date(2027, 3, 26), date(2027, 4, 25),
            date(2027, 5, 1), date(2027, 6, 3),
            date(2027, 8, 15), date(2027, 10, 5),
            date(2027, 11, 1), date(2027, 12, 1),
            date(2027, 12, 27), date(2027, 12, 28),
        ],
    },
    "eu-ie": {  # Euronext Dublin
        2025: [
            date(2025, 1, 1), date(2025, 2, 3), date(2025, 4, 18),
            date(2025, 4, 21), date(2025, 5, 5),
            date(2025, 6, 2), date(2025, 8, 4),
            date(2025, 10, 27), date(2025, 12, 25), date(2025, 12, 26),
        ],
        2026: [
            date(2026, 1, 1), date(2026, 2, 2), date(2026, 4, 3),
            date(2026, 4, 6), date(2026, 5, 4),
            date(2026, 6, 1), date(2026, 8, 3),
            date(2026, 10, 26), date(2026, 12, 25), date(2026, 12, 28),
        ],
        2027: [
            date(2027, 1, 1), date(2027, 2, 1), date(2027, 3, 26),
            date(2027, 3, 29), date(2027, 5, 3),
            date(2027, 6, 7), date(2027, 8, 2),
            date(2027, 10, 25), date(2027, 12, 27), date(2027, 12, 28),
        ],
    },
    "eu-fi": {  # Nasdaq Helsinki
        2025: [
            date(2025, 1, 1), date(2025, 1, 6), date(2025, 4, 18),
            date(2025, 4, 21), date(2025, 5, 1),
            date(2025, 6, 20), date(2025, 6, 21),
            date(2025, 12, 6), date(2025, 12, 24),
            date(2025, 12, 25), date(2025, 12, 26),
        ],
        2026: [
            date(2026, 1, 1), date(2026, 1, 6), date(2026, 4, 3),
            date(2026, 4, 6), date(2026, 5, 1),
            date(2026, 6, 19), date(2026, 6, 20),
            date(2026, 12, 6), date(2026, 12, 24),
            date(2026, 12, 25), date(2026, 12, 28),
        ],
        2027: [
            date(2027, 1, 1), date(2027, 1, 6), date(2027, 3, 26),
            date(2027, 3, 29), date(2027, 5, 1),
            date(2027, 6, 25), date(2027, 6, 26),
            date(2027, 12, 6), date(2027, 12, 24),
            date(2027, 12, 27), date(2027, 12, 28),
        ],
    },
    "eu-dk": {  # Nasdaq Copenhagen
        2025: [
            date(2025, 1, 1), date(2025, 4, 17), date(2025, 4, 18),
            date(2025, 4, 21), date(2025, 5, 1),
            date(2025, 6, 5), date(2025, 12, 24),
            date(2025, 12, 25), date(2025, 12, 26),
        ],
        2026: [
            date(2026, 1, 1), date(2026, 4, 2), date(2026, 4, 3),
            date(2026, 4, 6), date(2026, 5, 1),
            date(2026, 5, 14), date(2026, 12, 24),
            date(2026, 12, 25), date(2026, 12, 28),
        ],
        2027: [
            date(2027, 1, 1), date(2027, 3, 25), date(2027, 3, 26),
            date(2027, 3, 29), date(2027, 5, 1),
            date(2027, 5, 13), date(2027, 12, 24),
            date(2027, 12, 27), date(2027, 12, 28),
        ],
    },
    "eu-gr": {  # Athens Exchange
        2025: [
            date(2025, 1, 1), date(2025, 1, 6), date(2025, 2, 3),
            date(2025, 2, 27), date(2025, 4, 18), date(2025, 4, 21),
            date(2025, 4, 25), date(2025, 5, 1),
            date(2025, 6, 9), date(2025, 8, 15),
            date(2025, 10, 28), date(2025, 12, 25), date(2025, 12, 26),
        ],
        2026: [
            date(2026, 1, 1), date(2026, 1, 6), date(2026, 2, 2),
            date(2026, 2, 23), date(2026, 4, 3), date(2026, 4, 6),
            date(2026, 4, 10), date(2026, 5, 1),
            date(2026, 6, 1), date(2026, 8, 15),
            date(2026, 10, 27), date(2026, 12, 25), date(2026, 12, 28),
        ],
        2027: [
            date(2027, 1, 1), date(2027, 1, 6), date(2027, 2, 1),
            date(2027, 2, 15), date(2027, 3, 26), date(2027, 3, 29),
            date(2027, 4, 9), date(2027, 5, 1),
            date(2027, 6, 7), date(2027, 8, 15),
            date(2027, 10, 26), date(2027, 12, 27), date(2027, 12, 28),
        ],
    },
}


class HolidayCalendar:
    """Holiday calendar for the 16 regions in scope."""

    def regions(self) -> list[str]:
        return list(HOLIDAYS.keys())

    def is_trading_day(self, region: str, d: date) -> bool:
        """True iff `d` is a weekday AND not in the region's holiday list."""
        if d.weekday() not in TRADING_WEEKDAYS:
            return False
        return d not in self._holidays_for(region, d.year)

    def previous_trading_day(self, region: str, d: date) -> date | None:
        """Return the most recent prior trading day strictly before `d`.
        Walks backwards up to 14 days. Returns None if none found (suggests
        a long regional closure — caller should treat as anomaly)."""
        cur = d - timedelta(days=1)
        for _ in range(14):
            if self.is_trading_day(region, cur):
                return cur
            cur -= timedelta(days=1)
        return None

    def next_trading_day(self, region: str, d: date) -> date | None:
        """Return the next trading day strictly after `d`. Same 14-day limit."""
        cur = d + timedelta(days=1)
        for _ in range(14):
            if self.is_trading_day(region, cur):
                return cur
            cur += timedelta(days=1)
        return None

    def _holidays_for(self, region: str, year: int) -> set[date]:
        per_year = HOLIDAYS.get(region, {})
        return set(per_year.get(year, []))


# Module-level singleton for convenience
DEFAULT = HolidayCalendar()
