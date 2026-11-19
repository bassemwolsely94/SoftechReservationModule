"""Full audit BE-15: the business day is the Cairo day, not the UTC day.

`timezone.now()` is UTC (USE_TZ=True, TIME_ZONE='Africa/Cairo'), so `timezone.now().date()` is a day
behind Cairo between 00:00 and 02:00/03:00 local time. Every business-day site uses
`timezone.localdate()`; the guard below keeps new UTC-day sites out, and names the reviewed ones.
"""
import datetime as dt
import re
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase
from django.utils import timezone

ROOT = Path(__file__).resolve().parents[2]
UTC_DAY = re.compile(r'\bnow\(\)\.date\(\)')

# Reviewed sites that stay on the UTC day, each with its reason. Remove a line when its site changes.
REVIEWED = {
    # The ETA API windows are built in UTC, so "today" there is the UTC day on purpose.
    'apps/tax_invoicing/eta_history.py': 1,
    # Discount / reward eligibility — waiting for the owner's decision (CLAUDE.md: ask before a
    # discount or pricing change). Recommended: localdate, so a voucher ends at Cairo midnight.
    'apps/vouchers/models.py': 2,
    'apps/loyalty/models.py': 1,
}

# 2026-11-15 23:30 UTC is 2026-11-16 01:30 in Cairo (UTC+2 in November).
LATE_UTC = dt.datetime(2026, 11, 15, 23, 30, tzinfo=dt.timezone.utc)
NEW_YEAR_UTC = dt.datetime(2026, 12, 31, 23, 30, tzinfo=dt.timezone.utc)


class UtcDayGuardTests(SimpleTestCase):
    def test_no_new_utc_day_sites(self):
        found = {}
        for base in ('apps', 'core', 'config'):
            for path in (ROOT / base).rglob('*.py'):
                rel = path.relative_to(ROOT).as_posix()
                if '/tests/' in rel or '/migrations/' in rel or path.name.startswith('test_'):
                    continue
                n = len(UTC_DAY.findall(path.read_text(encoding='utf-8')))
                if n:
                    found[rel] = n
        self.assertEqual(found, REVIEWED,
                         'timezone.now().date() is the UTC day — use timezone.localdate() for a business day, '
                         'or add the site to REVIEWED with its reason')


class CairoDayTests(SimpleTestCase):
    def test_localdate_is_the_cairo_day_at_01_30(self):
        with mock.patch('django.utils.timezone.now', return_value=LATE_UTC):
            self.assertEqual(timezone.localdate(), dt.date(2026, 11, 16))

    def test_batch_days_to_expiry_counts_from_the_cairo_day(self):
        from apps.batches.models import StockBatch
        b = StockBatch(expiry_date=dt.date(2026, 11, 16))
        with mock.patch('django.utils.timezone.now', return_value=LATE_UTC):
            self.assertEqual(b.days_to_expiry, 0)          # the UTC day said 1

    def test_a_batch_that_expired_yesterday_is_flagged_after_cairo_midnight(self):
        from apps.batches.models import StockBatch
        b = StockBatch(expiry_date=dt.date(2026, 11, 15), is_expired=False)
        with mock.patch('django.utils.timezone.now', return_value=LATE_UTC), \
                mock.patch.object(StockBatch, 'save') as save:
            b.flag_expired()
        self.assertTrue(b.is_expired)                      # the UTC day left it "valid" until 02:00
        save.assert_called_once()

    def test_a_commerce_document_on_new_years_night_is_numbered_in_the_new_year(self):
        from apps.commerce import models as cm
        qs = mock.MagicMock()
        qs.filter.return_value.order_by.return_value.values_list.return_value.first.return_value = None
        doc_type = mock.Mock(number_prefix='QT')
        with mock.patch('django.utils.timezone.now', return_value=NEW_YEAR_UTC), \
                mock.patch.object(cm.CommerceDocument, 'objects', qs):
            number = cm.next_document_number(doc_type)
        self.assertTrue(number.startswith('QT-2027-'), number)
