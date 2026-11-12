"""Month periods of the General Ledger: the one get-or-create, and which month takes postings.

Imported by ``ledger`` and ``drafting``, so it depends on neither.
"""
import calendar
import datetime

from apps.finance.models import FinancialPeriod

OPENING_DATE = datetime.date(2026, 1, 1)


def month_period(day: datetime.date) -> FinancialPeriod:
    """Get or create the month FinancialPeriod for `day` (safe against a concurrent create)."""
    last = calendar.monthrange(day.year, day.month)[1]
    period, _ = FinancialPeriod.objects.get_or_create(
        year=day.year, month=day.month, period_type='month',
        defaults={'period_start': day.replace(day=1), 'period_end': day.replace(day=last)})
    return period


def previous_month(period: FinancialPeriod) -> FinancialPeriod | None:
    """The month before `period`; None for the month the books open in."""
    first = datetime.date(period.year, period.month, 1)
    if first <= OPENING_DATE:
        return None
    return month_period(first - datetime.timedelta(days=1))


def next_month(period: FinancialPeriod) -> FinancialPeriod:
    return month_period(datetime.date(period.year + period.month // 12, period.month % 12 + 1, 1))


def accepts_postings(day: datetime.date) -> bool:
    return month_period(day).status == 'open'


def first_open_period_after(day: datetime.date) -> FinancialPeriod:
    """The earliest open month after `day`'s month. A month with no row yet is an open one, so
    this walks month by month (creating as it goes) instead of jumping over a gap."""
    period = next_month(month_period(day))
    while period.status != 'open':
        period = next_month(period)
    return period
