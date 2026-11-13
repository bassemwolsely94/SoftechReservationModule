"""Sync creates new SOFTECH branches as `pending` and tells admins; existing
branches' curated fields (kind, is_operational, pos_enabled, display_order) are
never touched."""
from unittest import mock

from django.db import connection
from django.test import TestCase, override_settings

from apps.branches.models import Branch
from apps.notifications.models import Notification
from apps.sync import tasks
from apps.sync.models import SyncRun
from apps.tests.factories import make_user
from apps.tests.test_sync_r7 import _Conn


@override_settings(RBAC_ENFORCEMENT='log')
class BranchSyncPendingTests(TestCase):

    def setUp(self):
        self.run = SyncRun.objects.create()
        self.admin, _, _ = make_user('bp_admin', role='admin')

    def _sync(self, *rows):
        return tasks.sync_branches(_Conn(list(rows)), self.run)

    def test_new_softech_branch_created_pending(self):
        self._sync(('230', 'فرع جديد', 'New Branch', 'addr', '012'))
        b = Branch.objects.get(softech_branch_id='230')
        self.assertEqual(b.kind, Branch.KIND_PENDING)
        self.assertFalse(b.is_operational)
        self.assertFalse(b.pos_enabled)

    def test_new_branch_notifies_admins_once(self):
        row = ('230', 'فرع جديد', 'New Branch', 'addr', '012')
        self._sync(row)
        self._sync(row)
        qs = Notification.objects.filter(notification_type='branch_pending',
                                         recipient__user=self.admin)
        self.assertEqual(qs.count(), 1)
        self.assertEqual(qs.first().dedup_key, 'branch_pending:230')

    def test_failed_notice_does_not_poison_the_sync(self):
        """A database error inside the admin notice is rolled back to its own savepoint: the next
        branch and the sync log still save."""
        def broken_notice(*a, **kw):
            with connection.cursor() as cur:
                cur.execute('SELECT 1/0')

        with mock.patch.object(Notification, 'send_to_admins', side_effect=broken_notice):
            count = self._sync(('232', 'أ', 'A', 'x', 'y'), ('233', 'ب', 'B', 'x', 'y'))
        self.assertEqual(count, 2)
        self.assertTrue(Branch.objects.filter(softech_branch_id='233').exists())
        from apps.sync.models import SyncLog
        self.assertTrue(SyncLog.objects.filter(sync_run=self.run, table_name='branches').exists())

    def test_existing_branch_curated_fields_untouched(self):
        Branch.objects.create(softech_branch_id='231', name='Old', code='231',
                              kind=Branch.KIND_CLOSED, is_operational=False,
                              pos_enabled=True, display_order=7)
        self._sync(('231', 'س', 'Renamed', 'x', 'y'))
        b = Branch.objects.get(softech_branch_id='231')
        self.assertEqual((b.kind, b.is_operational, b.pos_enabled, b.display_order),
                         (Branch.KIND_CLOSED, False, True, 7))
        self.assertEqual(b.name, 'Renamed')
        self.assertFalse(Notification.objects.filter(
            notification_type='branch_pending').exists())


@override_settings(RBAC_ENFORCEMENT='log', SOFTECH_HQ_BRANCH_CODE='100')
class BranchSyncFreshHqTests(TestCase):
    """Fresh database: the configured HQ branch arrives as hq, not pending, so hq_code() works."""

    def setUp(self):
        from apps.branches.models import _reset_hq_code_cache
        _reset_hq_code_cache()
        self.addCleanup(_reset_hq_code_cache)
        Branch.objects.all().delete()
        self.run = SyncRun.objects.create()
        make_user('bp_admin2', role='admin')

    def _sync(self, *rows):
        return tasks.sync_branches(_Conn(list(rows)), self.run)

    def test_configured_hq_created_as_hq_when_none_exists(self):
        from apps.branches.models import hq_code
        self._sync(('100', 'الرئيسي', 'HQ', 'a', 'p'), ('130', 'فرع', 'B130', 'a', 'p'))
        hq = Branch.objects.get(softech_branch_id='100')
        self.assertEqual((hq.kind, hq.is_operational), (Branch.KIND_HQ, True))
        self.assertEqual(Branch.objects.get(softech_branch_id='130').kind, Branch.KIND_PENDING)
        self.assertEqual(hq_code(), '100')
        self.assertEqual(list(Notification.objects.filter(notification_type='branch_pending')
                              .values_list('dedup_key', flat=True).distinct()), ['branch_pending:130'])

    def test_configured_code_stays_pending_when_an_hq_exists(self):
        Branch.objects.create(softech_branch_id='971', name='HQ', code='971', kind=Branch.KIND_HQ)
        self._sync(('100', 'الرئيسي', 'HQ', 'a', 'p'))
        self.assertEqual(Branch.objects.get(softech_branch_id='100').kind, Branch.KIND_PENDING)
