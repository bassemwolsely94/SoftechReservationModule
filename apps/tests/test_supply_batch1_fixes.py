"""
/supply batch 1 fixes (owner 2026-10-24):
  • «التوزيعة» category filter — the screen sent category[]=… (axios array style) which the
    server never read, so every filter returned all categories; the preview analysed twice.
  • demand engine sales pull — the open-ended query timed out on HQ every run and the run
    silently re-used stale sales; it now pulls date-bounded windows (catchup.backfill_sales).
"""
import datetime
from unittest import mock

from django.test import SimpleTestCase, TestCase
from django.http import QueryDict
from rest_framework.test import APIClient

from apps.purchasing import isr_views


class DistributionCategoryTests(SimpleTestCase):
    def test_every_query_format(self):
        self.assertEqual(isr_views._categories(QueryDict('category=new_no_rate,over_piled')),
                         ['new_no_rate', 'over_piled'])
        self.assertEqual(isr_views._categories(QueryDict('category=a&category=b')), ['a', 'b'])
        self.assertEqual(isr_views._categories(QueryDict('category[]=a&category[]=b')), ['a', 'b'])
        self.assertIsNone(isr_views._categories(QueryDict('')))


class DistributionPreviewTests(TestCase):
    def test_one_analysis_filtered_list_and_full_counts(self):
        from .factories import make_user
        user, _, _ = make_user('dist_viewer', role='purchasing')
        sugs = [{'category': 'new_no_rate', 'total_qty': 2}, {'category': 'over_piled', 'total_qty': 5},
                {'category': 'over_piled', 'total_qty': 1}]
        c = APIClient()
        c.force_authenticate(user)
        with mock.patch('apps.purchasing.distribution.analyze', return_value=sugs) as an:
            r = c.get('/api/purchasing/isr/distribution/?category=over_piled')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(an.call_count, 1)                                   # was 2
        self.assertEqual([x['category'] for x in r.data['suggestions']], ['over_piled', 'over_piled'])
        self.assertEqual(r.data['summary']['total'], 3)                      # counts cover everything
        self.assertEqual(r.data['summary']['by_category']['new_no_rate']['count'], 1)


class EngineSalesPullTests(SimpleTestCase):
    def _engine(self):
        from apps.purchasing.engine import DemandEngine
        e = DemandEngine.__new__(DemandEngine)
        e._softech_ok = False
        return e

    def test_pulls_bounded_windows_from_the_lookback(self):
        e = self._engine()
        res = {'rows_upserted': 120, 'chunks': 1, 'latest': datetime.date.today(), 'start': None, 'end': None}
        with mock.patch('apps.purchasing.catchup.backfill_sales', return_value=res) as bf, \
                mock.patch.object(type(e), '_purge_old_rows', return_value=7):
            out = e._sync_from_softech(10)
        self.assertEqual(out, (120, 7))
        self.assertTrue(e._softech_ok)
        self.assertEqual(bf.call_args.kwargs['since'], datetime.date.today() - datetime.timedelta(days=10))

    def test_softech_down_is_recorded_not_hidden(self):
        e = self._engine()
        with mock.patch('apps.purchasing.catchup.backfill_sales', side_effect=RuntimeError('JZ006 timed out')), \
                mock.patch.object(type(e), '_purge_old_rows', return_value=0):
            out = e._sync_from_softech(10)
        self.assertEqual(out, (0, 0))
        self.assertFalse(e._softech_ok)                  # → run.softech_available=False → ⚠ on screen
