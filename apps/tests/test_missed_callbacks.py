"""
apps/tests/test_missed_callbacks.py — Project 3 (b): missed inbound call → automatic call-back.

One call-back per number, repeat misses raise its count, labelled / returned / already-queued
numbers skipped, auto-close on an answered call, after-hours due time, manual close stamped,
and the scheduler hook is a no-op while the flag is off.
"""
import uuid
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.callcenter.models import CallLog
from apps.pbx import missed_callbacks as MC
from apps.notifications.phone_alerts.events import EVENTS
from apps.notifications.phone_alerts.models import PhoneAlert, PhoneAlertAttempt, PhoneAlertPolicy, WorkOwner
from apps.notifications.phone_alerts.sender import build_staff_alert
from apps.pbx.models import CdrCall
from apps.users.models import StaffProfile
from apps.pic_analytics.models import PhoneLabel
from .factories import make_call_center

CAIRO = ZoneInfo('Africa/Cairo')
ON = override_settings(MISSED_CALL_CALLBACKS_ENABLED=True, MISSED_CALL_OPEN_HOUR=9,
                       MISSED_CALL_CLOSE_HOUR=23, MISSED_CALL_DUE_MINUTES=15)


def _cdr(key='01012345678', *, ago_min=30, status='no_answer', direction='inbound', at=None):
    return CdrCall.objects.create(
        cdr_key=uuid.uuid4().hex[:40], unique_id=uuid.uuid4().hex[:20],
        call_at=at or timezone.now() - timedelta(minutes=ago_min), direction=direction, status=status,
        customer_number=key, phone_key=key)


@ON
class QueueTests(TestCase):
    def test_creates_callback_per_missed_call(self):
        c = _cdr()
        s = MC.run()
        self.assertEqual(s['created'], 1)
        log = CallLog.objects.get()
        self.assertEqual((log.status, log.source, log.missed_cdr, log.missed_count, log.handled_by,
                          log.branch), ('callback', 'pbx', c, 1, None, None))
        self.assertTrue(AuditLog.objects.filter(action='missed_call_callback_created').exists())
        self.assertEqual(MC.run()['created'], 0)                    # idempotent

    def test_repeat_miss_increments_count(self):
        _cdr(ago_min=50)
        MC.run()
        _cdr(ago_min=10)
        MC.run()
        self.assertEqual(CallLog.objects.count(), 1)
        self.assertEqual(CallLog.objects.get().missed_count, 2)

    def test_two_misses_in_one_run_make_one_callback(self):
        _cdr(ago_min=50)
        _cdr(ago_min=10)
        MC.run()
        self.assertEqual(CallLog.objects.get().missed_count, 2)

    def test_labelled_number_skipped(self):
        PhoneLabel.objects.create(phone_key='01012345678', label='supplier')
        _cdr()
        self.assertEqual(MC.run()['skipped_labelled'], 1)
        self.assertFalse(CallLog.objects.exists())

    def test_already_returned_skipped(self):
        _cdr(ago_min=30)
        _cdr(ago_min=20, status='answered', direction='outbound')
        self.assertEqual(MC.run()['skipped_returned'], 1)
        self.assertFalse(CallLog.objects.exists())

    def test_existing_open_callback_blocks(self):
        CallLog.objects.create(phone_number='01012345678', status='callback',
                               callback_due=timezone.now())
        _cdr()
        self.assertEqual(MC.run()['skipped_open'], 1)
        self.assertEqual(CallLog.objects.count(), 1)

    def test_answered_and_transfer_and_old_calls_ignored(self):
        _cdr(status='answered')
        CdrCall.objects.filter(pk=_cdr(key='01000000001').pk).update(is_transfer=True)
        _cdr(key='01000000002', ago_min=60 * 25)
        self.assertEqual(MC.run()['created'], 0)

    def test_auto_close_on_answered(self):
        _cdr(ago_min=30)
        MC.run()
        _cdr(ago_min=5, status='answered', direction='outbound')
        self.assertEqual(MC.run()['closed'], 1)
        log = CallLog.objects.get()
        self.assertEqual((log.status, log.callback_resolution), ('answered', 'auto_returned'))
        self.assertIsNotNone(log.callback_resolved_at)
        self.assertTrue(AuditLog.objects.filter(action='missed_call_callback_auto_closed').exists())

    def test_due_after_hours(self):
        def at(h, m=0, day=3):
            return datetime(2026, 11, day, h, m, tzinfo=CAIRO)
        self.assertEqual(MC.due_for(at(14, 0)), at(14, 15))
        self.assertEqual(MC.due_for(at(23, 30)), at(9, 0, day=4))
        self.assertEqual(MC.due_for(at(2, 0)), at(9, 0))
        self.assertEqual(MC.due_for(at(8, 0)), at(9, 0))


@ON
class ManualCloseTests(TestCase):
    def test_manual_close_stamped(self):
        _cdr()
        MC.run()
        log = CallLog.objects.get()
        _, _, client = make_call_center()
        r = client.patch(f'/api/callcenter/calls/{log.pk}/', {'status': 'answered'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        log.refresh_from_db()
        self.assertEqual(log.callback_resolution, 'manual')
        r = client.get('/api/callcenter/calls/pending-callbacks/?mode=all&auto=1')
        self.assertEqual(r.status_code, 200)

    def test_queue_lists_auto_flag(self):
        _cdr()
        MC.run()
        _, _, client = make_call_center()
        rows = client.get('/api/callcenter/calls/pending-callbacks/?mode=all&auto=1').json()
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]['is_auto_callback'])
        self.assertEqual(rows[0]['missed_count'], 1)


@ON
class OverdueAlertTests(TestCase):
    """An open automatic call-back past its due time raises ONE phone alert to the call-back owners."""

    def setUp(self):
        u = User.objects.create_user('cb_owner', password='x')
        self.owner = StaffProfile.objects.create(user=u, role='call_center', phone='01000000077')
        WorkOwner.objects.create(kind='callcenter_callbacks', staff=self.owner)

    def _queue(self, due_ago_min=5):
        _cdr()
        MC.queue_missed_callbacks()
        log = CallLog.objects.get()
        CallLog.objects.filter(pk=log.pk).update(callback_due=timezone.now() - timedelta(minutes=due_ago_min))
        return log

    def _run(self):
        # deliveries run on a thread after commit: run them inline on the test connection
        from apps.notifications.phone_alerts import dispatch
        with patch.object(dispatch, 'start_thread', side_effect=lambda t, args=(), **kw: t(*args)),                 patch.object(dispatch, '_close_db'), self.captureOnCommitCallbacks(execute=True):
            return MC.run()

    def test_overdue_alerts_owner_once(self):
        log = self._queue()
        self.assertEqual(self._run()['alerted'], 1)
        alert = PhoneAlert.objects.get(event='callback_overdue')
        self.assertEqual((alert.source, alert.recipient_staff), (log, self.owner))
        PhoneAlert.objects.filter(pk=alert.pk).update(status='acknowledged')
        self.assertEqual(self._run()['alerted'], 0)              # never a second alert
        self.assertEqual(PhoneAlert.objects.filter(event='callback_overdue').count(), 1)

    def test_send_switch_off_is_dry_run(self):
        self._queue()
        self._run()
        att = PhoneAlertAttempt.objects.get()
        self.assertEqual(att.result, 'dry_run')

    def test_not_yet_due_no_alert(self):
        self._queue(due_ago_min=-30)
        self.assertEqual(self._run()['alerted'], 0)

    def test_policy_never_no_alert(self):
        PhoneAlertPolicy.objects.filter(event='callback_overdue').update(mode='never')
        self._queue()
        self.assertEqual(self._run()['alerted'], 0)
        self.assertFalse(PhoneAlert.objects.exists())

    def test_no_owner_no_alert(self):
        WorkOwner.objects.all().delete()
        self._queue()
        self.assertEqual(self._run()['alerted'], 0)

    def test_manual_callback_not_alerted(self):
        CallLog.objects.create(phone_number='01055555555', status='callback',
                               callback_due=timezone.now() - timedelta(minutes=5))
        self.assertEqual(self._run()['alerted'], 0)

    def test_closed_callback_closes_alert_and_text_has_no_number(self):
        log = self._queue()
        self._run()
        alert = PhoneAlert.objects.get(event='callback_overdue')
        variables, _ = build_staff_alert(alert)
        texts = ' '.join(v['text'] for v in variables)
        self.assertIn(f'#{log.pk}', texts)
        self.assertNotIn('01012345678', texts)
        CallLog.objects.filter(pk=log.pk).update(status='answered')
        log.refresh_from_db()
        self.assertFalse(EVENTS['callback_overdue'].is_open(log))


class FlagOffTests(TestCase):
    def test_flag_off_noop(self):
        from apps.sync import tasks
        _cdr()
        with patch('config.issabel.cdr_configured', return_value=True), \
                patch('apps.pbx.cdr.sync_cdr') as sync, patch('apps.pbx.cdr.notify_bridge_silence'):
            sync.return_value.status, sync.return_value.fetched, sync.return_value.stored = 'success', 0, 0
            tasks._run_pbx_cdr_sync()
        self.assertFalse(CallLog.objects.exists())
