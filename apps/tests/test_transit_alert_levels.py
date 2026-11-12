"""Transit alerts write a note + audit event only when the alert level changes
(data lifecycle stage 3); the daily digest and counters keep running."""
import datetime
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from apps.transits.management.commands.sync_in_transit import Command
from apps.transits.models import InTransitAuditEvent, InTransitNote, InTransitTransfer
from .factories import make_branch, make_branch2


class TransitAlertLevelTests(TestCase):
    def setUp(self):
        self.hq = make_branch('HQ', '100')
        self.giza = make_branch2('Giza', '140')
        self.cmd = Command()

    def _t(self, days, level='', sent_days_ago=None, status='in_transit', **extra):
        sent = (timezone.now() - datetime.timedelta(days=sent_days_ago)
                if sent_days_ago is not None else None)
        return InTransitTransfer.objects.create(
            erp_doc_number='7001', erp_supplying_branch_code='100', supplying_branch=self.hq,
            erp_receiving_branch_code='140', receiving_branch=self.giza,
            issue_date=datetime.date.today() - datetime.timedelta(days=days),
            days_in_transit=days, transit_status=status, item_count=1,
            last_alert_level=level, last_alert_sent_at=sent, **extra)

    def _counts(self, t):
        return (InTransitNote.objects.filter(transfer=t, note_type='alert').count(),
                InTransitAuditEvent.objects.filter(transfer=t, action='alert_sent').count())

    def test_same_level_next_day_writes_no_note(self):
        t = self._t(15, level='d14', sent_days_ago=1, alert_notification_count=3)
        before = self._counts(t)
        with mock.patch.object(Command, '_send_branch_digest') as digest:
            self.cmd._fire_alerts()
        self.assertEqual(self._counts(t), before)
        digest.assert_called_once()
        t.refresh_from_db()
        self.assertEqual(t.alert_notification_count, 4)
        self.assertEqual(t.last_alert_sent_at.date(), timezone.now().date())

    def test_level_change_writes_one_note_and_event(self):
        t = self._t(15, level='d7', sent_days_ago=1)
        before = self._counts(t)
        with mock.patch.object(Command, '_send_branch_digest'):
            self.cmd._fire_alerts()
        after = self._counts(t)
        self.assertEqual((after[0] - before[0], after[1] - before[1]), (1, 1))
        t.refresh_from_db()
        self.assertEqual(t.last_alert_level, 'd14')

    def test_local_alert_writes_once(self):
        t = self._t(10, level='', status='received',
                    manually_received_at=timezone.now() - datetime.timedelta(days=5))
        self.assertEqual(self.cmd._fire_local_receipt_alerts(), 1)
        InTransitTransfer.objects.filter(pk=t.pk).update(
            last_alert_sent_at=timezone.now() - datetime.timedelta(days=1))
        self.assertEqual(self.cmd._fire_local_receipt_alerts(), 1)
        self.assertEqual(self._counts(t)[0], 1)
        t.refresh_from_db()
        self.assertEqual(t.alert_notification_count, 2)

    def test_mismatch_alert_still_written(self):
        t = self._t(5, reconciliation={'missing_items': [1], 'qty_diffs': [], 'extra_items': []})
        self.cmd._notify_mismatch(t)
        self.cmd._notify_mismatch(t)
        self.assertEqual(self._counts(t)[0], 2)
