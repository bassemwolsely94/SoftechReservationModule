"""
apps/cheques/engine.py

Egyptian banking-day date engine.

Banking week in Egypt: Sunday (0) through Thursday (4).
Non-banking days: Friday (5), Saturday (6), plus official holidays in
the EgyptianHoliday table.

Public API:
  next_banking_day(date)       → first banking day >= given date
  compute_instalment_dates(start, count, interval_value, interval_unit)
                               → list of (nominal_date, banking_date) tuples
  preview_plan(first_due, count, total_amount, interval_value, interval_unit)
                               → list of dicts ready to display/create
"""
import calendar
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta

from django.core.cache import cache

# Weekday numbers that are never banking days in Egypt
_WEEKEND = {4, 5}   # Friday=4, Saturday=5  (Python weekday: Mon=0 … Sun=6)
# Note: Python weekday() → Mon=0, Tue=1, Wed=2, Thu=3, Fri=4, Sat=5, Sun=6


def _load_holiday_set(year_min: int, year_max: int) -> set:
    """
    Return a set of holiday dates for the year range, using a short cache.
    Cache key: 'eg_holidays_{year_min}_{year_max}'
    TTL: 3600 s (holidays don't change intra-day)
    """
    from .models import EgyptianHoliday

    cache_key = f'eg_holidays_{year_min}_{year_max}'
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    qs = EgyptianHoliday.objects.filter(
        date__year__gte=year_min,
        date__year__lte=year_max,
    ).values_list('date', flat=True)

    holiday_set = set(qs)

    # Also expand annual holidays into each year in range
    annual_qs = EgyptianHoliday.objects.filter(is_annual=True).values('date')
    for row in annual_qs:
        base = row['date']
        for yr in range(year_min, year_max + 1):
            try:
                # dateutil approach: replace year, adjust for leap years
                candidate = base.replace(year=yr)
                holiday_set.add(candidate)
            except ValueError:
                # Feb 29 in a non-leap year → skip
                pass

    cache.set(cache_key, holiday_set, timeout=3600)
    return holiday_set


def next_banking_day(d: date) -> date:
    """
    Return the first date >= d that is a valid Egyptian banking day.
    A day is a banking day iff:
      - It is not Friday (weekday 4) or Saturday (weekday 5)
      - It is not in the EgyptianHoliday table
    """
    holidays = _load_holiday_set(d.year, d.year + 1)
    candidate = d
    while True:
        if candidate.weekday() not in _WEEKEND and candidate not in holidays:
            return candidate
        candidate += timedelta(days=1)
        # Re-check holidays when we roll into a new year
        if candidate.year > d.year + 1:
            holidays = _load_holiday_set(d.year, candidate.year)


def _add_interval(base: date, value: int, unit: str) -> date:
    """Add interval_value × interval_unit to base date."""
    if unit == 'months':
        return base + relativedelta(months=value)
    if unit == 'weeks':
        return base + timedelta(weeks=value)
    # days
    return base + timedelta(days=value)


def compute_instalment_dates(
    first_due: date,
    count: int,
    interval_value: int,
    interval_unit: str,
) -> list[tuple[date, date]]:
    """
    Return list of (nominal_date, banking_date) tuples, length = count.
    nominal_date : raw computed date (e.g. exactly +1 month each time)
    banking_date : next_banking_day(nominal_date)
    """
    results = []
    nominal = first_due
    for _ in range(count):
        banking = next_banking_day(nominal)
        results.append((nominal, banking))
        nominal = _add_interval(first_due, interval_value * (len(results)), interval_unit)
    return results


def preview_plan(
    first_due: date,
    count: int,
    total_amount,   # Decimal or float
    interval_value: int,
    interval_unit: str,
) -> list[dict]:
    """
    Compute the instalment schedule without persisting anything.
    Each dict: { instalment_no, nominal_date, due_date, amount, adjusted }
    amount is evenly split; last cheque absorbs rounding remainder.
    adjusted = True when due_date != nominal_date.
    """
    from decimal import Decimal, ROUND_DOWN

    total = Decimal(str(total_amount))
    unit_amount = (total / count).quantize(Decimal('0.01'), rounding=ROUND_DOWN)
    remainder = total - unit_amount * count

    dates = compute_instalment_dates(first_due, count, interval_value, interval_unit)
    result = []
    for i, (nominal, banking) in enumerate(dates, start=1):
        amt = unit_amount + (remainder if i == count else Decimal('0'))
        result.append({
            'instalment_no': i,
            'nominal_date':  nominal,
            'due_date':      banking,
            'amount':        amt,
            'adjusted':      banking != nominal,
        })
    return result


def invalidate_holiday_cache():
    """Call this after seeding/editing holidays."""
    from django.core.cache import cache
    # broad wildcard clear — simpler than tracking all keys
    cache.clear()
