"""
R7 — apps/sync per-app tests.

Route groups (apps/sync/urls.py), one view test each:
  status/  trigger/  logs/  branch-health/  scheduler-status/  freshness/  softech-load/
  slow-requests/  writer-switches/

Permission: logs/ and scheduler-status/ need the `sync` matrix module (admin only in the code
matrix); softech-load / writer-switches are admin-only in the view; trigger is IsAdminUser.
Business rules: the SOFTECH → Django mappings (branches, categories, ERP users, ERP permission
flags) fed with synthetic cursor rows, the value converters, connection-error classification and
the nightly reservation auto-expire. SOFTECH is never contacted; no thread is started.
"""
import datetime
import json
from decimal import Decimal
from unittest import mock

from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone

from apps.branches.models import Branch
from apps.config.models import SystemSetting
from apps.sync import softech_load as sl
from apps.sync import tasks
from apps.sync.middleware import SlowRequestMiddleware
from apps.sync.models import SlowRequest, SyncLog, SyncRun
from apps.tests.factories import make_branch, make_item, make_user
from apps.tests.security.fixtures import bearer_client, seed_code_matrix
from core.middleware import module_access

API = '/api/sync/'


# ── fake SOFTECH cursor: every execute() returns the next queued result ───────

class _Cursor:
    def __init__(self, conn):
        self.conn = conn
        self._rows = []

    def execute(self, sql, params=None):
        self.conn.sql.append(sql)
        self._rows = list(self.conn.results.pop(0)) if self.conn.results else []

    def fetchall(self):
        return self._rows

    def close(self):
        pass


class _Conn:
    def __init__(self, *results):
        self.results = list(results)
        self.sql = []

    def cursor(self):
        return _Cursor(self)


@override_settings(RBAC_ENFORCEMENT='log')
class _Base(TestCase):

    def setUp(self):
        seed_code_matrix()
        self.admin_user, self.admin, self.admin_c = make_user('r7sync_admin', role='admin', access_all=True)
        self.pharm_user, self.pharm, self.pharm_c = make_user('r7sync_pharm', role='pharmacist')

    def tearDown(self):
        module_access.clear_cache()


# ── Views ─────────────────────────────────────────────────────────────────────

class SyncViewTests(_Base):

    def test_status_without_and_with_a_run(self):
        self.assertEqual(self.pharm_c.get(API + 'status/').data, {'status': 'no_sync_yet'})
        run = SyncRun.objects.create(status='success', records_synced=7)
        SyncLog.objects.create(sync_run=run, table_name='items', records_processed=7)
        r = self.pharm_c.get(API + 'status/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.data['id'], r.data['status'], r.data['records_synced']), (run.id, 'success', 7))
        self.assertEqual(r.data['logs'][0]['table_name'], 'items')

    def test_logs_admin_only_by_matrix(self):
        SyncRun.objects.create(status='success')
        r = bearer_client(self.pharm_user).get(API + 'logs/')
        self.assertEqual(r.status_code, 403)
        r = bearer_client(self.admin_user).get(API + 'logs/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data), 1)

    def test_trigger_needs_staff_and_runs_in_background(self):
        self.assertEqual(self.pharm_c.post(API + 'trigger/', {}, format='json').status_code, 403)
        self.admin_user.is_staff = True
        self.admin_user.save()
        with mock.patch('apps.sync.views.start_thread') as st:
            r = self.admin_c.post(API + 'trigger/', {'lane': 'fast'}, format='json')
        self.assertEqual(r.status_code, 202)
        self.assertEqual((r.data['lane'], r.data['status']), ('fast', 'running'))
        st.assert_called_once()
        self.assertEqual(st.call_args.kwargs['name'], 'manual-sync-fast')

    def test_trigger_refuses_to_pile_on_a_running_sync(self):
        self.admin_user.is_staff = True
        self.admin_user.save()
        run = SyncRun.objects.create(status='running')
        with mock.patch('apps.sync.views.start_thread') as st:
            r = self.admin_c.post(API + 'trigger/', {}, format='json')
        st.assert_not_called()
        self.assertEqual(r.status_code, 202)
        self.assertEqual((r.data['id'], r.data['detail']), (run.id, 'sync already in progress'))

    def test_branch_health_orders_hq_first_then_worst(self):
        make_branch('الرئيسي', '100')
        health = {
            'h-ok':  {'branch_id': 'B01', 'consecutive_failures': 0},
            'h-dn':  {'branch_id': 'B02', 'consecutive_failures': 1},
            'h-ch':  {'branch_id': 'B03', 'consecutive_failures': 5},
            'h-hq':  {'branch_id': '100', 'consecutive_failures': 2},
        }
        SystemSetting.objects.create(key='crm_branch_health', label='h', value=json.dumps(health),
                                     value_type='json')
        r = self.pharm_c.get(API + 'branch-health/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual([n['host'] for n in r.data['nodes']], ['h-hq', 'h-ch', 'h-dn', 'h-ok'])
        self.assertEqual(r.data['summary'], {'total': 4, 'ok': 1, 'down': 2, 'chronic': 1})
        self.assertTrue(r.data['nodes'][0]['is_hq'])
        self.assertEqual(r.data['nodes'][0]['name'], 'الرئيسي')
        self.assertNotIn('probe', r.data)

    def test_scheduler_status_alive_and_dead(self):
        c = bearer_client(self.admin_user)
        self.assertEqual(c.get(API + 'scheduler-status/').data['running'], False)
        s = SystemSetting.objects.create(key=tasks.SCHEDULER_HEARTBEAT_KEY, label='hb',
                                         value=datetime.datetime.now(datetime.timezone.utc).isoformat())
        r = c.get(API + 'scheduler-status/')
        self.assertTrue(r.data['running'])
        self.assertEqual(r.data['threshold'], 180)
        s.value = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=10)).isoformat()
        s.save()
        r = c.get(API + 'scheduler-status/')
        self.assertFalse(r.data['running'])
        self.assertGreaterEqual(r.data['seconds_ago'], 599)
        self.assertEqual(bearer_client(self.pharm_user).get(API + 'scheduler-status/').status_code, 403)

    def test_freshness_limited_to_requested_domains(self):
        run = SyncRun.objects.create(status='success')
        SyncLog.objects.create(sync_run=run, table_name='branches', records_processed=3)
        r = self.pharm_c.get(API + 'freshness/', {'domains': 'branches, nope'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(list(r.data['domains'].keys()), ['branches'])
        self.assertFalse(r.data['domains']['branches']['stale'])

    @override_settings(SOFTECH_LOAD_TELEMETRY=True)
    def test_softech_load_report(self):
        self.assertEqual(self.pharm_c.get(API + 'softech-load/').status_code, 403)
        sl.flush()                                   # start from an empty buffer
        with sl.scope('r7-job'):
            sl.record_connect('HQ', 120, ok=True)
            sl.record_connect('HQ', 80, ok=False)
            sl.record_query('HQ', 40, ok=True)
            sl.record_query('HQ', 60, ok=False)
            sl.record_fetch('HQ', 25, 5)
        r = self.admin_c.get(API + 'softech-load/', {'hours': 'x'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['hours'], 24)
        t = r.data['totals']
        self.assertEqual((t['connects'], t['connect_failures'], t['connect_ms'], t['queries'],
                          t['query_errors'], t['query_ms'], t['max_query_ms'], t['rows']),
                         (2, 1, 200, 2, 1, 105, 60, 25))
        self.assertEqual([s['scope'] for s in r.data['by_scope']], ['r7-job'])
        self.assertEqual(r.data['by_node'][0]['label'], 'HQ')

    def test_slow_requests_report(self):
        for ms in (1500, 2500, 9000):
            SlowRequest.objects.create(path='api/x/', method='GET', status_code=200, duration_ms=ms)
        self.assertEqual(self.pharm_c.get(API + 'slow-requests/').status_code, 403)
        r = self.admin_c.get(API + 'slow-requests/', {'days': '99'})
        self.assertEqual(r.data['days'], 30)
        self.assertEqual(r.data['endpoints'], [{'path': 'api/x/', 'method': 'GET', 'count': 3,
                                                'p95_ms': 9000, 'max_ms': 9000}])

    def test_writer_switches_admin_only(self):
        self.assertEqual(self.pharm_c.get(API + 'writer-switches/').status_code, 403)
        r = self.admin_c.get(API + 'writer-switches/')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data['flags'])
        self.assertTrue(all(f['code_default'] is False for f in r.data['flags']))


# ── Mappings fed with synthetic SOFTECH rows ──────────────────────────────────

class SyncMappingTests(TestCase):

    def test_sync_branches_creates_then_keeps_admin_fields(self):
        run = SyncRun.objects.create()
        n = tasks.sync_branches(_Conn([('R71', 'فرع س', 'Branch S', 'شارع 1', '0123')]), run)
        self.assertEqual(n, 1)
        b = Branch.objects.get(softech_branch_id='R71')
        self.assertEqual((b.name, b.name_ar, b.code, b.address, b.phone, b.is_active),
                         ('Branch S', 'فرع س', 'R71', 'شارع 1', '0123', True))
        # admin closes the branch and edits its Arabic name; a later sync must not undo that
        b.is_active, b.name_ar = False, 'فرع مغلق'
        b.save()
        tasks.sync_branches(_Conn([('R71', 'جديد', None, 'x', 'y')]), run)
        b.refresh_from_db()
        self.assertEqual((b.name, b.name_ar, b.address, b.is_active), ('جديد', 'فرع مغلق', 'شارع 1', False))
        self.assertEqual(SyncLog.objects.filter(table_name='branches').count(), 2)

    def test_sync_categories_upserts(self):
        from apps.catalog.models import Category
        run = SyncRun.objects.create()
        tasks.sync_categories(_Conn([('C71', 'Analgesic', 'مسكنات'), ('C72', None, None)]), run)
        tasks.sync_categories(_Conn([('C71', 'Pain', 'مسكن')]), run)
        c = Category.objects.get(softech_id='C71')
        self.assertEqual((c.name, c.name_ar), ('Pain', 'مسكن'))
        self.assertEqual(Category.objects.get(softech_id='C72').name, '')

    def test_sync_users_active_flag_and_fallbacks(self):
        from apps.users.models import ERPUser
        run = SyncRun.objects.create()
        rows = [
            ('11', 'ahmed', 'G1', '0', 'B01', '100', 'أحمد علي'),
            ('12', None, 'G2', '1', 'B02', '100'),      # login falls back to userid; nomore=1 → inactive
            ('', '', 'G3', '0', '', ''),                 # no login at all → skipped
        ]
        self.assertEqual(tasks.sync_users(_Conn(rows), run), 2)
        a = ERPUser.objects.get(username='ahmed')
        self.assertEqual((a.user_id, a.user_group, a.branch_code, a.full_name, a.is_active),
                         ('11', 'G1', 'B01', 'أحمد علي', True))
        b = ERPUser.objects.get(username='12')
        self.assertEqual((b.full_name, b.is_active), ('', False))

    def test_sync_erp_permissions_flags(self):
        from apps.users.models import ErpGroupPermission, ErpScreen, ErpUserGroup
        groups = [(5, 'Cashiers', '0'), (6, 'Blocked', 1), ('bad', 'x', 0)]
        screens = [('w_sales', 'مبيعات', 'Sales', 'POS', 'SUB', 3), ('', 'skip', '', '', '', 0),
                   ('w_sales', 'dup', 'dup', 'POS', 'SUB', 4)]
        perms = [(5, 'w_sales', 1, '1', 0, '1.0', 'true', 0, 0, 0, 0, 0, 0, 0),
                 (99, 'w_sales', 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1)]   # unknown group → skipped
        total = tasks.sync_erp_permissions(_Conn(groups, screens, perms), SyncRun.objects.create())
        self.assertEqual(total, 2 + 1 + 1)
        self.assertFalse(ErpUserGroup.objects.get(usergroup=5).is_blocked)
        self.assertTrue(ErpUserGroup.objects.get(usergroup=6).is_blocked)
        self.assertEqual(ErpScreen.objects.get(mitemname='w_sales').descr_ar, 'dup')
        p = ErpGroupPermission.objects.get()
        self.assertEqual((p.can_enable, p.can_show, p.can_retrieve, p.can_save, p.can_datain, p.can_print),
                         (True, True, False, True, True, False))

    def test_value_converters(self):
        self.assertEqual(tasks._to_decimal('12.50'), Decimal('12.50'))
        self.assertEqual(tasks._to_decimal(None), Decimal('0'))
        self.assertEqual(tasks._to_decimal('abc'), Decimal('0'))
        self.assertEqual(tasks._to_date(datetime.datetime(2026, 1, 2, 3, 4)), datetime.date(2026, 1, 2))
        self.assertEqual(tasks._to_date(datetime.date(2026, 1, 2)), datetime.date(2026, 1, 2))
        self.assertIsNone(tasks._to_date('2026-01-02'))
        self.assertIsNone(tasks._aware('x'))
        aware = tasks._aware(datetime.datetime(2026, 7, 1, 12, 0))
        self.assertEqual(aware.utcoffset(), datetime.timedelta(hours=3))     # Cairo summer time
        already = timezone.now()
        self.assertIs(tasks._aware(already), already)
        self.assertTrue(tasks._b('1') and tasks._b(1) and tasks._b('True'))
        self.assertFalse(tasks._b('0') or tasks._b(None) or tasks._b('yes'))

    def test_connection_error_classification(self):
        from config.sybase import SoftechAccessDenied
        self.assertTrue(tasks._is_connection_error(Exception('JZ0C0: Connection is already closed.')))
        self.assertTrue(tasks._is_connection_error(Exception('read Timed Out')))
        self.assertFalse(tasks._is_connection_error(Exception('syntax error near FROM')))
        self.assertFalse(tasks._is_connection_error(SoftechAccessDenied('timeout')))


# ── Nightly reservation auto-expire (business rule) ───────────────────────────

class AutoExpireReservationTests(TestCase):

    def setUp(self):
        from apps.reservations.models import Reservation
        self.branch = make_branch()
        self.item = make_item()

        def mk(status, days_old):
            r = Reservation.objects.create(item=self.item, branch=self.branch, contact_name='x',
                                           contact_phone='0100', status=status)
            Reservation.objects.filter(pk=r.pk).update(
                created_at=timezone.now() - datetime.timedelta(days=days_old))
            return r
        self.mk = mk

    def test_expires_only_stale_open_states_after_setting_days(self):
        from apps.reservations.models import Reservation
        SystemSetting.objects.create(key='reservation_expiry_days', label='d', value='10',
                                     value_type='integer')
        stale_pending = self.mk('pending', 11)
        stale_contacted = self.mk('contacted', 30)
        fresh = self.mk('pending', 9)
        confirmed = self.mk('confirmed', 40)
        tasks._auto_expire_reservations()
        status = dict(Reservation.objects.values_list('pk', 'status'))
        self.assertEqual(status, {stale_pending.pk: 'expired', stale_contacted.pk: 'expired',
                                  fresh.pk: 'pending', confirmed.pk: 'confirmed'})
        log = stale_contacted.status_logs.get()
        self.assertEqual((log.old_status, log.new_status, log.note),
                         ('contacted', 'expired', 'انتهت مدة الحجز تلقائياً بعد 10 يوماً'))

    def test_default_is_30_days(self):
        from apps.reservations.models import Reservation
        a = self.mk('available', 29)
        b = self.mk('available', 31)
        tasks._auto_expire_reservations()
        self.assertEqual(Reservation.objects.get(pk=a.pk).status, 'available')
        self.assertEqual(Reservation.objects.get(pk=b.pk).status, 'expired')


# ── SlowRequestMiddleware ─────────────────────────────────────────────────────

class SlowRequestMiddlewareTests(TestCase):

    @override_settings(SLOW_REQUEST_MS=0)
    def test_records_route_and_role(self):
        _, profile, _ = make_user('r7sync_mw', role='viewer')
        req = RequestFactory().get('/api/x/5/')
        req.user = profile.user
        req.resolver_match = mock.Mock(route='api/x/<int:pk>/')
        resp = SlowRequestMiddleware(lambda r: mock.Mock(status_code=201))(req)
        self.assertEqual(resp.status_code, 201)
        row = SlowRequest.objects.get()
        self.assertEqual((row.path, row.method, row.status_code, row.role),
                         ('api/x/<int:pk>/', 'GET', 201, 'viewer'))

    @override_settings(SLOW_REQUEST_MS=0)
    def test_unrouted_request_not_recorded(self):
        req = RequestFactory().get('/static/x.js')
        SlowRequestMiddleware(lambda r: mock.Mock(status_code=404))(req)
        self.assertFalse(SlowRequest.objects.exists())
