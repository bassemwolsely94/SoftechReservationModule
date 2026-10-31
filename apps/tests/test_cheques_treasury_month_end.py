"""
The treasury dashboard crashed (500, ValueError) on the 29th–31st of a month: a leftover
"same day next month" date.replace() ran before the real 30-day window was computed.
"""
import datetime
from unittest import mock

from django.test import TestCase

from apps.tests.factories import make_admin


class _Jan31(datetime.date):
    @classmethod
    def today(cls):
        return cls(2027, 1, 31)


class TreasuryMonthEndTests(TestCase):
    def test_treasury_works_on_the_31st(self):
        _, _, client = make_admin('treasury_31')
        with mock.patch('apps.cheques.views.date', _Jan31):
            r = client.get('/api/cheques/treasury/')
        self.assertEqual(r.status_code, 200, r.content[:300])
