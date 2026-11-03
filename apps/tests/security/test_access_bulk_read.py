"""N5 / Task 5 - bulk-read anomaly alert and temporary block."""
from io import StringIO
from types import SimpleNamespace

from datetime import timedelta

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.management import call_command
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.test import RequestFactory, TestCase, override_settings
from rest_framework.response import Response

from apps.access import bulk_read
from apps.access.devices import DeviceInfo
from apps.access.export_middleware import ExportAuditMiddleware
from apps.access.network import NetworkInfo
from apps.audit.models import AuditLog
from apps.notifications.models import Notification
from apps.tests.factories import make_user

LIMITS = dict(BULK_READ_ROWS_PER_HOUR=10, BULK_EXPORTS_PER_HOUR=2, BULK_READ_BLOCK_MINUTES=30)


def _rows_view(n):
    return lambda req: JsonResponse({'count': n, 'results': [{'id': i} for i in range(n)]})


@override_settings(BULK_READ_ENFORCEMENT='log', **LIMITS)
class BulkReadTests(TestCase):

    def setUp(self):
        cache.clear()
        self.rf = RequestFactory()
        self.user, self.profile, _ = make_user('bulk_user', role='supervisor')
        self.admin_user, self.admin_profile, _ = make_user('bulk_admin', role='admin')

    def _call(self, view, path='/api/customers/', user=None, method='get', **kw):
        user = user or self.user
        req = getattr(self.rf, method)(path, **kw)
        req.user = user
        req.access = SimpleNamespace(
            zone='Z1', user_id=user.pk,
            device=DeviceInfo(public_id='dev-1', status='approved', name='Desk', kind='pc'),
            network=NetworkInfo(zone='external', ip='41.1.1.1', site=None))
        return ExportAuditMiddleware(view)(req)

    def _block(self, profile, minutes=30):
        type(profile).objects.filter(pk=profile.pk).update(
            bulk_read_blocked_until=timezone.now() + timedelta(minutes=minutes))

    def _alerts(self):
        return list(AuditLog.objects.filter(action='bulk_read_alert'))

    def test_rows_counted_from_paginated_and_list_bodies(self):
        self.assertEqual(bulk_read.rows_in(Response({'count': 9, 'results': [1, 2, 3]})), 3)
        self.assertEqual(bulk_read.rows_in(Response([1, 2])), 2)
        self.assertEqual(bulk_read.rows_in(Response({'id': 3})), 1)
        self.assertEqual(bulk_read.rows_in(Response({})), 0)
        self.assertEqual(bulk_read.rows_in(JsonResponse({'results': [1, 2, 3, 4]})), 4)
        self.assertEqual(bulk_read.rows_in(JsonResponse([1], safe=False)), 1)
        self.assertEqual(bulk_read.rows_in(HttpResponse(b'x', content_type='text/plain')), 0)
        self.assertIsNone(bulk_read.record(self.user, rows=4))
        self.assertIsNone(bulk_read.record(self.user, rows=5))
        self.assertEqual(bulk_read.record(self.user, rows=2), 'rows')

    def test_crossing_alerts_once_per_hour(self):
        self._call(_rows_view(6))
        self.assertEqual(self._alerts(), [])
        self._call(_rows_view(6))
        self._call(_rows_view(6))
        rows = self._alerts()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].extra['kind'], 'rows')
        self.assertEqual(rows[0].extra['limit'], 10)
        self.assertEqual(rows[0].extra['count'], 12)
        note = Notification.objects.get(recipient=self.admin_profile)
        self.assertEqual(note.title, 'قراءة بيانات بكمية غير معتادة')
        self.assertIn('bulk_user', note.body)
        self.assertIn('خارج الشبكة', note.body)
        self.assertIn('limit 10', note.body)
        self.assertNotIn('خادم', note.body)

    def test_log_mode_alerts_never_blocks(self):
        for _ in range(3):
            self._call(_rows_view(6))
        self.assertEqual(len(self._alerts()), 1)
        self.assertFalse(bulk_read.blocked(self.user))
        r = self._call(_rows_view(1))
        self.assertEqual(r.status_code, 200)

    @override_settings(BULK_READ_ENFORCEMENT='enforce')
    def test_enforce_blocks_customer_reads_for_minutes(self):
        self._call(_rows_view(6))
        self._call(_rows_view(6))
        self.assertTrue(bulk_read.blocked(self.user))
        r = self._call(_rows_view(1))
        self.assertEqual(r.status_code, 403)
        self.assertIn(b'bulk_read', r.content)
        self.assertIn('كمية غير معتادة'.encode('unicode_escape'), r.content)
        # an unrelated path is untouched
        self.assertEqual(self._call(_rows_view(1), path='/api/items/').status_code, 200)
        # so is another user
        self.assertEqual(self._call(_rows_view(1), user=self.admin_user).status_code, 200)
        # an export is refused too
        self.assertEqual(self._call(lambda req: HttpResponse(b'x'),
                                    path='/api/orders/export/').status_code, 403)
        self.profile.refresh_from_db()
        self.assertGreater(self.profile.bulk_read_blocked_until, timezone.now() + timedelta(minutes=29))
        # writes at the counter keep working while blocked
        self.assertEqual(self._call(_rows_view(1), method='post').status_code, 200)

    @override_settings(BULK_READ_ENFORCEMENT='enforce')
    def test_admin_alerted_never_blocked(self):
        for _ in range(3):
            self._call(_rows_view(6), user=self.admin_user)
        self.assertEqual(len(self._alerts()), 1)
        self.assertFalse(bulk_read.blocked(self.admin_user))
        self.assertEqual(self._call(_rows_view(1), user=self.admin_user).status_code, 200)

    def test_exports_counted_toward_export_limit(self):
        def view(req):
            return HttpResponse(b'a,b', content_type='text/csv')
        self._call(view, path='/api/orders/export/')
        self.assertEqual(self._alerts(), [])
        self._call(view, path='/api/orders/export/')
        self._call(view, path='/api/orders/export/')
        rows = self._alerts()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].extra['kind'], 'exports')
        self.assertEqual(rows[0].extra['limit'], 2)
        self.assertEqual(AuditLog.objects.filter(action='export_taken').count(), 3)

    @override_settings(BULK_READ_ENFORCEMENT='off')
    def test_off_mode_counts_nothing(self):
        for _ in range(3):
            self._call(_rows_view(6))
        self.assertEqual(self._alerts(), [])

    def test_clear_bulk_block_command(self):
        self._block(self.profile)
        out = StringIO()
        call_command('clear_bulk_block', 'bulk_user', stdout=out)
        self.assertFalse(bulk_read.blocked(User.objects.get(pk=self.user.pk)))
        row = self._alerts()[0]
        self.assertTrue(row.extra['cleared'])
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            call_command('clear_bulk_block', 'nobody', stdout=out)

    def test_unknown_mode_is_log_and_w004(self):
        from apps.access.checks import bulk_read_settings_check
        with override_settings(BULK_READ_ENFORCEMENT='enfroce'):
            self.assertEqual(bulk_read.mode(), 'log')
            self.assertIn('access.W004', [m.id for m in bulk_read_settings_check(None)])
            for _ in range(3):
                self._call(_rows_view(6))
            self.assertFalse(bulk_read.blocked(self.user))
        with override_settings(BULK_READ_ENFORCEMENT='enforce'):
            self.assertEqual(bulk_read_settings_check(None), [])

    def test_preflight_item(self):
        from apps.access import preflight
        items = preflight.check_bulk_read()
        self.assertEqual([i.code for i in items], ['bulk_read_mode'])

    def test_block_expiry(self):
        self._block(self.profile, minutes=-1)
        self.assertFalse(bulk_read.blocked(User.objects.get(pk=self.user.pk)))
        self._block(self.profile, minutes=5)
        self.assertTrue(bulk_read.blocked(User.objects.get(pk=self.user.pk)))

    def test_superuser_and_profileless_never_blocked(self):
        su = User.objects.create_superuser('bulk_su', password='x')
        plain = User.objects.create_user('bulk_plain', password='x')
        self.assertFalse(bulk_read.blocked(su))
        self.assertFalse(bulk_read.blocked(plain))
        with override_settings(BULK_READ_ENFORCEMENT='enforce'):
            for u in (su, plain):
                bulk_read.alert(u, 'rows', SimpleNamespace(path='/api/customers/'), 11)
                self.assertFalse(bulk_read.blocked(u))

    def test_detail_get_counts_one_row(self):
        self.assertEqual(bulk_read.rows_in(JsonResponse({'id': 5, 'name': 'x'})), 1)
        for _ in range(11):
            self._call(lambda req: JsonResponse({'id': 5}), path='/api/customers/5/')
        self.assertEqual(len(self._alerts()), 1)

    def test_clear_when_no_block_writes_no_audit(self):
        out = StringIO()
        call_command('clear_bulk_block', 'bulk_user', stdout=out)
        self.assertIn('no bulk-read block', out.getvalue())
        self.assertEqual(self._alerts(), [])
