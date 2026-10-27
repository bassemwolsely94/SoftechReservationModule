"""
apps/tests/test_coupon_dashboard.py

Gift-coupon screen API (apps/vouchers/coupon_views.py) + daily misuse digest
(apps/vouchers/coupon_dashboard.py). No SOFTECH contact — every SOFTECH call is mocked.
"""
import datetime as dt
from unittest import mock

from django.test import TestCase, override_settings

from apps.audit.models import AuditLog
from apps.notifications.models import Notification
from apps.tests.factories import make_user
from apps.tests.test_coupon_lifecycle import NAMES, mv, stocked
from apps.vouchers import coupon_dashboard as dash
from apps.vouchers import coupon_lifecycle as lc
from apps.vouchers.models import CouponBatch, CouponSerial

D = dt.date
TODAY = dt.date.today()
YDAY = TODAY - dt.timedelta(days=1)
S1 = '27286-MFW296'
S2 = '27287-ABC123'
URL = '/api/vouchers/coupons/'


def _load_events():
    """S1: issued to 05HD759 then redeemed twice (2nd time by 07HD1); a junk-serial redemption
    yesterday at branch 130 by user 64 for customer 04HD731 (never issued anything)."""
    stocked(S1)
    stocked(S2, doc_p=65627, doc_s=65628)
    w0, w1 = TODAY - dt.timedelta(days=40), TODAY + dt.timedelta(days=1)
    rows = [
        mv('102230', '170', '100', 1, (TODAY - dt.timedelta(days=30)).isoformat(), S1, party='100', pic='05HD759'),
        mv('118639', '115', '170', 2, (TODAY - dt.timedelta(days=20)).isoformat(), S1, pic='05HD759'),
        mv('118639', '115', '140', 3, YDAY.isoformat(), S1, pic='07HD1'),
        mv('118639', '115', '130', 4, YDAY.isoformat(), '8452', pic='04HD731', qty=3),
    ]
    lc.store_events(rows, w0, w1, NAMES)
    lc.rebuild_summaries()


class PermissionTests(TestCase):
    def test_floor_roles_refused(self):
        for role in ('pharmacist', 'call_center', 'salesperson'):
            _, _, c = make_user(f'u_{role}', role=role)
            self.assertEqual(c.get(URL + 'overview/').status_code, 403, role)
            self.assertEqual(c.get(URL + 'serial/?q=' + S1).status_code, 403, role)

    def test_viewer_cannot_manage(self):
        _, _, c = make_user('qm', role='quality_manager')
        r = c.get(URL + 'overview/')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data['can_manage'])
        self.assertEqual(c.post(URL + 'batches/', {}, format='json').status_code, 403)
        self.assertEqual(c.post(URL + 'batches/1/push/', {'confirm': True}, format='json').status_code, 403)
        self.assertEqual(c.post(URL + 'sync/').status_code, 403)

    def test_manager_role(self):
        _, _, c = make_user('sup', role='supervisor')
        r = c.get(URL + 'overview/')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data['can_manage'])

    def test_anonymous(self):
        from rest_framework.test import APIClient
        self.assertIn(APIClient().get(URL + 'overview/').status_code, (401, 403))


class ReadTests(TestCase):
    def setUp(self):
        _load_events()
        _, _, self.c = make_user('adm', role='admin', access_all=True)

    def test_serial_history(self):
        r = self.c.get(URL + 'serial/', {'q': S1.lower()})
        self.assertEqual(r.status_code, 200)
        s = r.data['serials'][0]
        self.assertEqual(s['serial'], S1)
        self.assertEqual([e['kind'] for e in s['events']], ['issue', 'redeem', 'redeem'])
        self.assertIn('redeemed_twice', [a['code'] for a in s['anomalies']])

    def test_lookup_by_number_and_junk(self):
        r = self.c.get(URL + 'serial/', {'q': '27287'})
        self.assertEqual([s['serial'] for s in r.data['serials']], [S2])
        r = self.c.get(URL + 'serial/', {'q': '8452'})
        self.assertEqual(r.data['serials'], [])
        self.assertEqual(len(r.data['unlinked_events']), 1)
        self.assertEqual(self.c.get(URL + 'serial/').status_code, 400)

    def test_no_serial(self):
        r = self.c.get(URL + 'no-serial/', {'days': 7})
        self.assertEqual(r.data['by_branch'], [{'branch': '130', 'lines': 1, 'qty': 3.0}])
        self.assertEqual(r.data['by_user'][0]['usercode'], '64')
        self.assertEqual(self.c.get(URL + 'no-serial/', {'branch': '150'}).data['rows'], [])

    def test_customers(self):
        r = self.c.get(URL + 'customers/')
        pics = {x['pic']: x for x in r.data['rows']}
        self.assertEqual(pics['04HD731']['excess'], 3.0)
        self.assertEqual(pics['07HD1']['excess'], 1.0)
        self.assertNotIn('05HD759', pics)
        r = self.c.get(URL + 'customers/', {'pic': '05HD759'})
        self.assertEqual((r.data['issued'], r.data['redeemed']), (1.0, 1.0))

    def test_overview(self):
        r = self.c.get(URL + 'overview/')
        self.assertEqual(r.data['serials'], 2)
        self.assertEqual(r.data['no_serial_30d'][0]['branch'], '130')
        self.assertEqual(r.data['customers']['active_over'], 2)
        self.assertIn('writer_enabled', r.data)


class DigestTests(TestCase):
    def setUp(self):
        _load_events()
        make_user('adm', role='admin', access_all=True)
        make_user('sup', role='supervisor')
        make_user('ph', role='pharmacist')

    def test_digest_content(self):
        d = dash.daily_digest()
        self.assertEqual(d['day'], YDAY)
        self.assertEqual([e.raw_serial for e in d['no_serial']], ['8452'])
        self.assertEqual(d['no_serial_by_user'], {('130', '64'): 3.0})
        self.assertEqual([e.raw_serial for e in d['reused']], [S1])
        self.assertEqual({r['pic'] for r in d['customers_over']}, {'04HD731', '07HD1'})
        text = dash.digest_text(d)
        self.assertIn('8452', text)
        self.assertIn('04HD731', text)

    def test_notify_once_per_day_to_roles(self):
        d = dash.daily_digest()
        self.assertEqual(dash.notify_digest(d), 2)          # admin + supervisor, not the pharmacist
        self.assertEqual(dash.notify_digest(d), 0)          # deduped
        n = Notification.objects.get(recipient__role='admin', notification_type='coupon_digest')
        self.assertEqual(n.category, Notification.CATEGORY_REPORTS)

    def test_coupon_issued_to_customer_outside_points_is_flagged(self):
        from apps.customers.models import Customer
        Customer.objects.create(name='x', phone='01001112223', softech_pic='05HD999', points_enrolled=False)
        Customer.objects.create(name='y', phone='01001112224', softech_pic='05HD1', points_enrolled=True)
        stocked('27290-ZZZ111', doc_p=65700, doc_s=65701)
        stocked('27291-ZZZ112', doc_p=65702, doc_s=65703)
        lc.store_events([
            mv('102230', '170', '100', 9, YDAY.isoformat(), '27290-ZZZ111', party='100', pic='05HD999'),
            mv('102230', '170', '100', 10, YDAY.isoformat(), '27291-ZZZ112', party='100', pic='05HD1'),
        ], TODAY - dt.timedelta(days=40), TODAY + dt.timedelta(days=1), NAMES)
        d = dash.daily_digest()
        self.assertEqual([e.customer_pic for e, _ in d['ineligible_issues']], ['05HD999'])
        self.assertIn('05HD999 (خارج نظام النقاط)', dash.digest_text(d))

    def test_quiet_day_sends_nothing(self):
        d = dash.daily_digest(D(2020, 1, 1))
        self.assertTrue(dash.digest_is_empty(d))
        self.assertEqual(dash.notify_digest(d), 0)
        self.assertFalse(Notification.objects.filter(notification_type='coupon_digest').exists())


class BatchTests(TestCase):
    def setUp(self):
        stocked(S1)
        _, self.p, self.c = make_user('pur', role='purchasing')

    def _generate(self, **kw):
        with mock.patch('config.sybase.get_sybase_connection') as conn, \
                mock.patch('apps.vouchers.coupons.read_blocked_expiries', return_value=set()):
            conn.return_value = mock.Mock()
            return self.c.post(URL + 'batches/', kw, format='json')

    def test_generate_audited(self):
        r = self._generate(size=5)
        self.assertEqual(r.status_code, 201, r.data)
        b = CouponBatch.objects.get(pk=r.data['id'])
        self.assertEqual((b.size, b.serial_from, b.created_by_id), (5, 27287, self.p.pk))
        self.assertEqual(CouponSerial.objects.filter(batch=b).count(), 5)
        self.assertTrue(AuditLog.objects.filter(action='coupon_batch_generated', object_id=str(b.pk)).exists())
        self.assertEqual(self.c.get(URL + 'batches/').data['rows'][0]['id'], b.pk)

    def test_generate_size_limits(self):
        self.assertEqual(self._generate(size=0).status_code, 201)       # 0 → default size
        self.assertEqual(self._generate(size=10_000).status_code, 400)

    def test_generate_fails_closed_without_softech(self):
        with mock.patch('config.sybase.get_sybase_connection', side_effect=RuntimeError('down')):
            r = self.c.post(URL + 'batches/', {'size': 5}, format='json')
        self.assertEqual(r.status_code, 502)
        self.assertFalse(CouponBatch.objects.exists())

    def test_export_print_and_dataload(self):
        b = CouponBatch.objects.get(pk=self._generate(size=4).data['id'])
        r = self.c.get(URL + f'batches/{b.pk}/export/', {'kind': 'print'})
        self.assertEqual(r.status_code, 200)
        self.assertIn('spreadsheetml', r['Content-Type'])
        r = self.c.get(URL + f'batches/{b.pk}/export/', {'kind': 'dataload'})
        self.assertIn(b.serials.first().serial, r.content.decode('utf-8'))

    @override_settings(INVOICE_WRITER_ENABLED=False)
    def test_push_refused_when_writer_off(self):
        b = CouponBatch.objects.get(pk=self._generate(size=2).data['id'])
        with mock.patch('apps.vouchers.coupon_push.push_batch') as push:
            self.assertEqual(self.c.post(URL + f'batches/{b.pk}/push/', {}, format='json').status_code, 400)
            r = self.c.post(URL + f'batches/{b.pk}/push/', {'confirm': True}, format='json')
        self.assertEqual(r.status_code, 409)
        push.assert_not_called()

    @override_settings(INVOICE_WRITER_ENABLED=True)
    def test_push_busy_and_success(self):
        b = CouponBatch.objects.get(pk=self._generate(size=2).data['id'])
        busy = mock.MagicMock()
        busy.return_value.__enter__.return_value = False
        with mock.patch('apps.vouchers.coupon_dashboard.pg_lock', busy), \
                mock.patch('apps.vouchers.coupon_push.push_batch') as push:
            r = self.c.post(URL + f'batches/{b.pk}/push/', {'confirm': True}, format='json')
        self.assertEqual(r.status_code, 409)
        push.assert_not_called()

        def fake_push(batch, commit, force):
            CouponBatch.objects.filter(pk=batch.pk).update(status='stocked')
            return {'points': {'mode': 'live', 'wrote_to_softech': True, 'docnumber': 1},
                    'served': {'mode': 'live', 'wrote_to_softech': True, 'docnumber': 2}}
        with mock.patch('apps.vouchers.coupon_push.push_batch', side_effect=fake_push) as push:
            r = self.c.post(URL + f'batches/{b.pk}/push/', {'confirm': True}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        push.assert_called_once()
        self.assertTrue(push.call_args.kwargs['commit'])
        self.assertEqual(r.data['batch']['status'], 'stocked')
        log = AuditLog.objects.get(action='coupon_batch_stocked', object_id=str(b.pk))
        self.assertEqual(log.extra['after'], {'status': 'stocked'})
        # a stocked batch is never pushed again
        self.assertEqual(self.c.post(URL + f'batches/{b.pk}/push/', {'confirm': True},
                                     format='json').status_code, 400)

    def test_sync_busy(self):
        with mock.patch('apps.vouchers.coupon_dashboard.locked_sync', return_value=None):
            self.assertEqual(self.c.post(URL + 'sync/').status_code, 409)


class LockTests(TestCase):
    def test_pg_lock_acquire_release(self):
        with dash.pg_lock(123456) as got:
            self.assertTrue(got)
        from django.db import connection
        with connection.cursor() as cur:       # released → no advisory lock left in this session
            cur.execute("SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND objid=123456 "
                        "AND pid=pg_backend_pid()")
            self.assertEqual(cur.fetchone()[0], 0)
