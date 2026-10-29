"""
CustomerCase SLA: default deadlines per priority + hourly auto-escalation.
"""
from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.callcenter.models import CaseEvent, CustomerCase
from apps.callcenter.sla import backfill_missing_sla, escalate_breached_cases
from apps.notifications.models import Notification
from .factories import make_admin, make_call_center, make_customer


class CaseSlaTests(TestCase):

    def setUp(self):
        self.customer = make_customer()
        _, self.admin, _ = make_admin('sla_admin')
        _, self.agent, _ = make_call_center('sla_agent')

    def _case(self, **kw):
        defaults = dict(customer=self.customer, category='complaint', title='تأخير توصيل')
        defaults.update(kw)
        return CustomerCase.objects.create(**defaults)

    def test_default_deadline_by_priority(self):
        before = timezone.now()
        urgent = self._case(priority='urgent')
        low = self._case(priority='low')
        self.assertAlmostEqual((urgent.sla_due - before).total_seconds() / 3600, 4, places=1)
        self.assertAlmostEqual((low.sla_due - before).total_seconds() / 3600, 72, places=1)

    @override_settings(CALLCENTER_CASE_SLA_HOURS={'normal': 2})
    def test_settings_override(self):
        before = timezone.now()
        case = self._case()
        self.assertAlmostEqual((case.sla_due - before).total_seconds() / 3600, 2, places=1)

    def test_explicit_deadline_kept(self):
        due = timezone.now() + timedelta(days=10)
        self.assertEqual(self._case(sla_due=due).sla_due, due)

    def test_breached_case_escalates_once_and_notifies(self):
        case = self._case(status='working', assigned_to=self.agent)
        CustomerCase.objects.filter(pk=case.pk).update(sla_due=timezone.now() - timedelta(hours=3))

        self.assertEqual(escalate_breached_cases(), 1)
        case.refresh_from_db()
        self.assertEqual(case.status, 'escalated')
        self.assertIn('SLA', case.escalation_reason)
        self.assertTrue(CaseEvent.objects.filter(case=case, event_type='system').exists())
        notified = set(Notification.objects.filter(notification_type='case_sla_breach')
                       .values_list('recipient_id', flat=True))
        self.assertIn(self.admin.pk, notified)
        self.assertIn(self.agent.pk, notified)

        self.assertEqual(escalate_breached_cases(), 0)   # idempotent

    def test_waiting_and_on_time_cases_not_escalated(self):
        waiting = self._case(status='waiting')
        CustomerCase.objects.filter(pk=waiting.pk).update(sla_due=timezone.now() - timedelta(hours=1))
        self._case()  # deadline in the future
        self.assertEqual(escalate_breached_cases(), 0)

    def test_backfill_counts_from_now(self):
        case = self._case()
        CustomerCase.objects.filter(pk=case.pk).update(
            sla_due=None, created_at=timezone.now() - timedelta(days=30))
        self.assertEqual(backfill_missing_sla(), 1)
        case.refresh_from_db()
        self.assertGreater(case.sla_due, timezone.now())
        self.assertEqual(escalate_breached_cases(), 0)
