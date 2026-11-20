"""
C30 — phantom-substitution monthly review list (apps/purchasing/phantom_review.py).

Only items that BECAME phantom in the month are listed; the digest goes to the owner only, once a
month; the review endpoint needs the phantom read grant. Read-only: no stock reduction, no SOFTECH.
"""
import datetime as dt
from decimal import Decimal
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.purchasing import phantom as P
from apps.purchasing import phantom_review as R
from apps.tests.factories import make_admin, make_item, make_user

URL = '/api/purchasing/phantom/monthly/'


def _at(y, m, d):
    return timezone.make_aware(dt.datetime(y, m, d, 12, 0))


def _flag(code, when, *, override='', buyback='10', cost='50', flagged=True):
    it = make_item(name=f'صنف {code}', softech_id=code)
    it.is_phantom_substitution = flagged
    it.phantom_flagged_at = when
    it.phantom_override = override
    it.phantom_buyback_qty = Decimal(buyback)
    it.phantom_sold_qty = Decimal('20')
    it.phantom_ratio = 0.5
    it.cost_price = Decimal(cost)
    it.save()
    return it


class FlaggedAtRuleTests(SimpleTestCase):
    NOW = dt.datetime(2026, 11, 3, 9, 0)
    OLD = dt.datetime(2026, 9, 1, 9, 0)

    def test_turning_on_stamps_now(self):
        self.assertEqual(P.next_flagged_at(False, True, None, self.NOW), self.NOW)

    def test_staying_on_keeps_the_first_date_even_when_missing(self):
        self.assertEqual(P.next_flagged_at(True, True, self.OLD, self.NOW), self.OLD)
        self.assertIsNone(P.next_flagged_at(True, True, None, self.NOW))      # legacy flag: not "new"

    def test_auto_unflag_clears_so_a_reflag_is_new_again(self):
        self.assertIsNone(P.next_flagged_at(True, False, self.OLD, self.NOW))

    def test_excluded_keeps_its_month(self):
        self.assertEqual(P.next_flagged_at(True, False, self.OLD, self.NOW, 'excluded'), self.OLD)


class MonthParseTests(SimpleTestCase):
    def test_parse(self):
        self.assertEqual(R.parse_month('2026-10'), dt.date(2026, 10, 1))
        self.assertEqual(R.parse_month('', today=dt.date(2026, 11, 20)), dt.date(2026, 11, 1))
        self.assertIsNone(R.parse_month('2026-13'))
        self.assertIsNone(R.parse_month('oct'))
        self.assertEqual(R.next_month(dt.date(2026, 12, 1)), dt.date(2027, 1, 1))


class MonthlyReviewTests(TestCase):
    def setUp(self):
        _flag('PH01', _at(2026, 10, 5), buyback='10', cost='50')                       # new, pending, 500
        _flag('PH02', _at(2026, 10, 20), override='confirmed', buyback='4', cost='25')  # new, reviewed, 100
        _flag('PH03', _at(2026, 10, 25), override='excluded', flagged=False)            # new, excluded
        _flag('PH04', _at(2026, 9, 30))                                                 # last month: not new
        _flag('PH05', None)                                                             # legacy flag: not new

    def test_only_items_first_flagged_in_the_month(self):
        data = R.monthly_review(dt.date(2026, 10, 1))
        self.assertEqual([r['code'] for r in data['items']], ['PH01', 'PH03', 'PH02'])   # pending first, then EGP
        self.assertEqual((data['count'], data['pending'], data['reviewed']), (3, 1, 2))
        self.assertEqual(data['egp_pending'], 500.0)
        self.assertEqual({r['code']: r['state'] for r in data['items']},
                         {'PH01': 'pending', 'PH02': 'confirmed', 'PH03': 'excluded'})

    def test_scan_stamps_new_flags_only(self):
        """The detector stamps the date the flag turns on, keeps it while on, clears it when off."""
        from apps.catalog.models import Item
        it = make_item(softech_id='SC01')
        Item.objects.filter(pk=it.pk).update(is_stockable=True)
        strong = {'is_phantom': True, 'phantom_ratio': 0.9, 'contract_ratio': 1.0, 'order_pct': 0.1,
                  'genuine_need': 1.0, 'tier': 'strong'}
        with mock.patch('config.sybase.get_sybase_connection'), \
                mock.patch.object(P, 'buyback_accounts', return_value=[]), \
                mock.patch.object(P, '_sales_metrics', return_value={'SC01': (20.0, 20.0, 5.0)}), \
                mock.patch.object(P, '_purchase_metrics', return_value={'SC01': (18.0, 4.0)}):
            with mock.patch.object(P, 'score_item', return_value=dict(strong)):
                P.scan()
            it.refresh_from_db()
            first = it.phantom_flagged_at
            self.assertIsNotNone(first)
            with mock.patch.object(P, 'score_item', return_value=dict(strong)):
                P.scan()
            it.refresh_from_db()
            self.assertEqual(it.phantom_flagged_at, first)
            with mock.patch.object(P, 'score_item', return_value={**strong, 'is_phantom': False}):
                P.scan()
            it.refresh_from_db()
            self.assertIsNone(it.phantom_flagged_at)


class DigestTests(TestCase):
    def setUp(self):
        _flag('DG01', _at(2026, 10, 5), buyback='10', cost='123')

    def test_owner_only_once_per_month(self):
        from apps.notifications.models import Notification
        _, admin, _ = make_admin('ph_admin')
        make_user('ph_pharm', role='pharmacist')
        make_user('ph_buyer', role='purchasing')
        self.assertEqual(R.send_monthly(today=dt.date(2026, 11, 1)), 1)
        self.assertEqual(R.send_monthly(today=dt.date(2026, 11, 2)), 0)     # re-run: same month
        sent = Notification.objects.filter(notification_type='monthly_report')
        self.assertEqual(sent.count(), 1)
        self.assertEqual(sent[0].recipient_id, admin.pk)
        self.assertIn('1,230', sent[0].body)
        self.assertIn('DG01', sent[0].body)

    def test_nothing_new_sends_nothing(self):
        make_admin('ph_admin2')
        self.assertEqual(R.send_monthly(today=dt.date(2026, 10, 1)), 0)     # September: no new flag


class PermissionTests(TestCase):
    def setUp(self):
        from apps.tests.security.fixtures import seed_code_matrix
        from core.middleware import module_access
        seed_code_matrix()
        module_access.clear_cache()
        self.addCleanup(module_access.clear_cache)
        cache.clear()
        self.addCleanup(cache.clear)
        _flag('PV01', timezone.now())

    def test_admin_reads_this_month(self):
        _, _, client = make_admin('pv_admin')
        r = client.get(URL)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['count'], 1)
        self.assertEqual(client.get(URL, {'month': 'bad'}).status_code, 400)

    def test_viewer_refused(self):
        _, _, client = make_user('pv_viewer', role='viewer')
        self.assertEqual(client.get(URL).status_code, 403)

    def test_anonymous_refused(self):
        from rest_framework.test import APIClient
        self.assertIn(APIClient().get(URL).status_code, (401, 403))

    def test_confirm_on_an_unflagged_item_stamps_the_date(self):
        it = _flag('PV02', None, flagged=False)
        _, _, client = make_admin('pv_admin2')
        self.assertEqual(client.post('/api/purchasing/phantom/confirm/', {'item_id': it.id},
                                     format='json').status_code, 200)
        it.refresh_from_db()
        self.assertIsNotNone(it.phantom_flagged_at)


class SchedulerTests(SimpleTestCase):
    def test_monthly_job_registered_and_classified(self):
        from apps.sync import tasks
        from apps.tests.test_scheduler_locks import SCHEDULER_JOB_GUARDS
        self.assertTrue(callable(tasks._run_phantom_review_monthly))
        self.assertEqual(SCHEDULER_JOB_GUARDS['phantom_review_monthly'][1],
                         'apps.purchasing.phantom_review.send_monthly')
