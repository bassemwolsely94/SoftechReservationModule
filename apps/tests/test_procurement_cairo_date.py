"""
Procurement's "today" is Cairo's date (CI 2026-11-02 00:15 Cairo): between midnight and 02:00 Cairo
the UTC date is still yesterday, so purchases dated today dropped out of every window.
"""
import datetime
from unittest import mock

from django.test import SimpleTestCase
from django.utils import timezone

from apps.procurement.views import resolve_period

# 2026-11-01 23:00 UTC = 2026-11-02 01:00 Cairo
LATE_UTC = datetime.datetime(2026, 11, 1, 23, 0, tzinfo=datetime.timezone.utc)


class ProcurementCairoDateTests(SimpleTestCase):
    def test_default_window_ends_on_cairo_today(self):
        with mock.patch.object(timezone, 'now', return_value=LATE_UTC):
            since, until = resolve_period({})
        self.assertEqual(until, datetime.date(2026, 11, 2))

    def test_today_preset_is_cairo_today(self):
        with mock.patch.object(timezone, 'now', return_value=LATE_UTC):
            self.assertEqual(resolve_period({'period': 'today'}),
                             (datetime.date(2026, 11, 2), datetime.date(2026, 11, 2)))
