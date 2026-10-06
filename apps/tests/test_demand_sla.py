"""
apps/tests/test_demand_sla.py

Covers the demand-intake SLA escalation engine (TD-C003):
  - 'new' record unassigned past 10 min  → breach escalation to supervisors/admins/CC
  - 'assigned' record stalled past 20 min → breach escalation to the assignee
  - fresh records within SLA            → no escalation
  - idempotency: a second run within the repeat window does not re-notify
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.demand.models import DemandRecord, DemandLog
from apps.demand.service import escalate_breached_demand_sla
from apps.notifications.models import Notification
from .factories import make_branch, make_admin, make_user


def _make_demand(branch, status='new', minutes_old=0, assigned_to=None,
                 assigned_minutes_ago=None):
    """Create a DemandRecord and back-date timestamps so SLA math triggers.

    created_at is auto_now_add, so it is overwritten via queryset.update().
    """
    d = DemandRecord.objects.create(
        phone='01000000000',
        customer_name='عميل اختبار',
        branch=branch,
        status=status,
        assigned_to=assigned_to,
    )
    if minutes_old:
        DemandRecord.objects.filter(pk=d.pk).update(
            created_at=timezone.now() - timedelta(minutes=minutes_old)
        )
    if assigned_minutes_ago is not None:
        DemandRecord.objects.filter(pk=d.pk).update(
            assigned_at=timezone.now() - timedelta(minutes=assigned_minutes_ago)
        )
    return DemandRecord.objects.get(pk=d.pk)


class DemandSlaEscalationTests(TestCase):

    def setUp(self):
        self.branch = make_branch()
        # An admin is a recipient for both tiers (and bypasses the role gate).
        _, self.admin, _ = make_admin('sla_admin')

    def test_new_unassigned_breach_escalates(self):
        d = _make_demand(self.branch, status='new', minutes_old=15)  # > 10m

        n = escalate_breached_demand_sla()

        self.assertEqual(n, 1)
        notif = Notification.objects.filter(
            recipient=self.admin,
            notification_type='demand_sla_breach',
            demand_id_ref=d.id,
        ).first()
        self.assertIsNotNone(notif)
        self.assertEqual(notif.dedup_key, f'demand_sla:{d.id}:new')
        # A system audit line is written on the demand record.
        self.assertTrue(
            DemandLog.objects.filter(demand=d, log_type='system',
                                     message__icontains='SLA').exists()
        )

    def test_assigned_stalled_breach_notifies_assignee(self):
        _, assignee, _ = make_user('sla_assignee', role='pharmacist', branch=self.branch)
        d = _make_demand(
            self.branch, status='assigned',
            assigned_to=assignee, assigned_minutes_ago=30,  # > 20m
        )

        n = escalate_breached_demand_sla()

        self.assertEqual(n, 1)
        self.assertTrue(
            Notification.objects.filter(
                recipient=assignee,
                notification_type='demand_sla_breach',
                demand_id_ref=d.id,
                dedup_key=f'demand_sla:{d.id}:assigned',
            ).exists()
        )

    def test_fresh_record_within_sla_not_escalated(self):
        _make_demand(self.branch, status='new', minutes_old=3)   # < 10m

        n = escalate_breached_demand_sla()

        self.assertEqual(n, 0)
        self.assertFalse(
            Notification.objects.filter(notification_type='demand_sla_breach').exists()
        )

    def test_idempotent_within_repeat_window(self):
        _make_demand(self.branch, status='new', minutes_old=15)

        first  = escalate_breached_demand_sla()
        second = escalate_breached_demand_sla()

        self.assertEqual(first, 1)
        self.assertEqual(second, 0)   # deduped — no second notification
        self.assertEqual(
            Notification.objects.filter(
                recipient=self.admin, notification_type='demand_sla_breach'
            ).count(),
            1,
        )
