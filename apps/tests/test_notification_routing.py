"""
apps/tests/test_notification_routing.py

P-55 Parts B + C (docs/product-review/06_SPEC_P-55):
  • overdue transfers → ONE digest per receiving branch per day, to that branch's
    managers (pharmacist / supervisor) + the HQ coordinators (transit_digest_recipients,
    default admins); a same-day re-run sends nothing more
  • notification_routing: 'off' suppresses a type, 'instant' keeps today's behaviour,
    'roles' narrows who gets it
  • 3 consecutive failed runs of one sync lane → one admin alert per lane per day
  • retention: read > 30 days and unread > 90 days are deleted; announcements stay
"""
import datetime

from django.test import TestCase
from django.utils import timezone

from apps.config.models import SystemSetting
from apps.notifications.models import Notification
from apps.sync.models import SyncRun
from apps.transits.management.commands.sync_in_transit import Command
from apps.transits.models import InTransitTransfer
from .factories import make_admin, make_branch, make_branch2, make_user

TODAY = datetime.date.today()


def _json_setting(key, value):
    import json
    SystemSetting.objects.update_or_create(
        key=key, defaults={'value': json.dumps(value), 'value_type': 'json', 'label': key})


class TransitDigestTests(TestCase):

    def setUp(self):
        self.hq = make_branch('HQ', '100')
        self.giza = make_branch2('Giza', '140')
        _, self.admin, _ = make_admin('dg_admin')
        _, self.manager, _ = make_user('dg_pharm', role='pharmacist', branch=self.giza)
        _, self.seller, _ = make_user('dg_sales', role='salesperson', branch=self.giza)
        self.started = timezone.now()
        for i, days in enumerate((5, 8, 9, 15, 20)):
            InTransitTransfer.objects.create(
                erp_doc_number=str(905000 + i), erp_supplying_branch_code='100', supplying_branch=self.hq,
                erp_receiving_branch_code='140', receiving_branch=self.giza,
                issue_date=TODAY - datetime.timedelta(days=days), days_in_transit=days,
                transit_status='in_transit', last_synced_at=timezone.now(), item_count=1)

    def _count(self, staff):
        return Notification.objects.filter(recipient=staff, notification_type__startswith='transit_').count()

    def test_one_digest_per_recipient_per_day(self):
        Command()._fire_alerts(verified_since=self.started)

        self.assertEqual(self._count(self.manager), 1)
        self.assertEqual(self._count(self.admin), 1)
        self.assertEqual(self._count(self.seller), 0)
        n = Notification.objects.get(recipient=self.manager)
        self.assertEqual(n.notification_type, 'transit_critical')   # oldest is 20 days
        self.assertIn('5', n.body)                                  # 5 transfers awaiting receipt
        self.assertIn('20', n.body)                                 # oldest age

    def test_same_day_rerun_sends_nothing_more(self):
        Command()._fire_alerts(verified_since=self.started)
        Command()._fire_alerts(verified_since=self.started)
        self.assertEqual(self._count(self.manager), 1)
        self.assertEqual(self._count(self.admin), 1)

    def test_coordinator_setting_replaces_admin_default(self):
        _, coordinator, _ = make_user('dg_coord', role='purchasing', branch=self.hq)
        _json_setting('transit_digest_recipients', [coordinator.pk])
        Command()._fire_alerts(verified_since=self.started)
        self.assertEqual(self._count(coordinator), 1)
        self.assertEqual(self._count(self.admin), 0)
        self.assertEqual(self._count(self.manager), 1)


class RoutingSettingTests(TestCase):

    def setUp(self):
        _, self.staff, _ = make_user('rt_pharm', role='pharmacist')

    def test_off_suppresses_a_type(self):
        _json_setting('notification_routing', {'demand_created': {'mode': 'off'}})
        self.assertIsNone(Notification.send_to_user(self.staff, 'demand_created', 'x'))

    def test_instant_and_unlisted_keep_current_behaviour(self):
        _json_setting('notification_routing', {'demand_created': {'mode': 'instant'}})
        self.assertIsNotNone(Notification.send_to_user(self.staff, 'demand_created', 'x'))
        self.assertIsNotNone(Notification.send_to_user(self.staff, 'demand_assigned', 'y'))

    def test_roles_narrow_the_audience(self):
        _json_setting('notification_routing', {'demand_created': {'mode': 'instant', 'roles': ['admin']}})
        self.assertIsNone(Notification.send_to_user(self.staff, 'demand_created', 'x'))


class SyncFailureAlertTests(TestCase):

    def setUp(self):
        _, self.admin, _ = make_admin('sf_admin')

    def _runs(self, *statuses, lane='fast'):
        for st in statuses:
            SyncRun.objects.create(status=st, lane=lane, completed_at=timezone.now())

    def _alerts(self):
        return Notification.objects.filter(recipient=self.admin, notification_type='sync_failure').count()

    def test_three_failures_in_a_row_alert_once_a_day(self):
        from apps.sync.maintenance import alert_failing_lanes
        self._runs('success', 'failed', 'failed', 'failed')
        alert_failing_lanes()
        alert_failing_lanes()
        self.assertEqual(self._alerts(), 1)

    def test_two_failures_do_not_alert(self):
        from apps.sync.maintenance import alert_failing_lanes
        self._runs('failed', 'failed', 'success', 'failed', 'failed')
        alert_failing_lanes()
        self.assertEqual(self._alerts(), 0)

    def test_lanes_are_counted_separately(self):
        from apps.sync.maintenance import alert_failing_lanes
        self._runs('failed', 'failed', lane='fast')
        self._runs('failed', lane='slow')
        alert_failing_lanes()
        self.assertEqual(self._alerts(), 0)


class NotificationRetentionTests(TestCase):

    def test_windows(self):
        from apps.sync.maintenance import prune_notifications
        _, staff, _ = make_user('ret_pharm', role='pharmacist')

        def notif(read, days, kind='demand_created'):
            n = Notification.objects.create(recipient=staff, notification_type=kind, title='t', is_read=read)
            Notification.objects.filter(pk=n.pk).update(created_at=timezone.now() - datetime.timedelta(days=days))
            return n.pk

        gone = {notif(True, 31), notif(False, 91)}
        kept = {notif(True, 10), notif(False, 80), notif(True, 400, kind='announcement')}

        prune_notifications()

        left = set(Notification.objects.values_list('pk', flat=True))
        self.assertEqual(left, kept)
        self.assertFalse(gone & left)
