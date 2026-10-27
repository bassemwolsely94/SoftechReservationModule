"""
apps/tests/test_pos_cancel_sync.py — Wave 3 inc2 (pos_cancel PG mirror).

Pure helpers of the sync + the trends endpoint over PosCancelDaily. No SOFTECH contact
(the live sweep needs Sybase and is verified in the app); here we test parsing + aggregation.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.pos_orders.pos_cancel_sync import _parse_day, _dec
from apps.pos_orders.models import PosCancelDaily
from .factories import make_pharmacist


class SyncHelperTests(TestCase):
    def test_parse_day_ase_and_iso(self):
        self.assertEqual(_parse_day('2026/09/14'), date(2026, 9, 14))   # ASE style 111
        self.assertEqual(_parse_day('2026-09-14'), date(2026, 9, 14))   # iso fallback
        self.assertEqual(_parse_day('2026/09/14 08:30:00'), date(2026, 9, 14))
        self.assertIsNone(_parse_day('garbage'))

    def test_dec_handles_null_and_rounds(self):
        self.assertEqual(_dec(None), Decimal('0.00'))
        self.assertEqual(_dec('12.349'), Decimal('12.35'))
        self.assertEqual(_dec(5), Decimal('5.00'))


class LostSalesTrendsViewTests(TestCase):
    def setUp(self):
        self.client = make_pharmacist()[2]   # (user, profile, api_client)
        today = timezone.now().date()
        # branch 170: two items across two days; branch 130: one item
        PosCancelDaily.objects.bulk_create([
            PosCancelDaily(branch_code='170', day=today, doccode='115', item_code='119729',
                           item_name='ENTRESTO 50MG', events=7, priced_events=7, lost_value='13413.17'),
            PosCancelDaily(branch_code='170', day=today - timedelta(days=1), doccode='115',
                           item_code='119729', item_name='ENTRESTO 50MG', events=2, priced_events=1,
                           lost_value='1000.00'),
            PosCancelDaily(branch_code='170', day=today, doccode='115', item_code='96690',
                           item_name='ASPIRIN', events=3, priced_events=2, lost_value='150.00'),
            PosCancelDaily(branch_code='130', day=today, doccode='115', item_code='96690',
                           item_name='ASPIRIN', events=1, priced_events=1, lost_value='75.00'),
        ])

    def _get(self, **params):
        return self.client.get('/api/pos-orders/lost-sales-trends/', params)

    def test_cross_branch_summary_and_top_items(self):
        r = self._get(days=30)
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertAlmostEqual(d['summary']['lost_value'], 14638.17, places=2)   # all rows
        # ENTRESTO leads (13413.17 + 1000.00 = 14413.17)
        self.assertEqual(d['top_items'][0]['item_code'], '119729')
        self.assertAlmostEqual(d['top_items'][0]['lost_value'], 14413.17, places=2)
        # by-branch split
        codes = {b['branch_code']: b['lost_value'] for b in d['by_branch']}
        self.assertAlmostEqual(codes['170'], 14563.17, places=2)
        self.assertAlmostEqual(codes['130'], 75.00, places=2)
        # daily series present (2 distinct days)
        self.assertEqual(len(d['daily']), 2)

    def test_branch_filter(self):
        d = self._get(days=30, branch='130').json()
        self.assertAlmostEqual(d['summary']['lost_value'], 75.00, places=2)
        self.assertEqual(len(d['top_items']), 1)
        self.assertEqual(d['top_items'][0]['item_code'], '96690')

    def test_window_excludes_old_rows(self):
        old = timezone.now().date() - timedelta(days=200)
        PosCancelDaily.objects.create(branch_code='170', day=old, doccode='115',
                                      item_code='999', item_name='OLD', events=1,
                                      priced_events=1, lost_value='9999.00')
        d = self._get(days=30).json()
        self.assertNotIn('999', [it['item_code'] for it in d['top_items']])
