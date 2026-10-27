"""
apps/callcenter/sla.py

CustomerCase SLA: deterministic default deadlines per priority, and hourly
auto-escalation of breached cases (scheduled in apps/sync/tasks.py).
"""
import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger('elrezeiky.callcenter')

DEFAULT_SLA_HOURS = {'urgent': 4, 'high': 8, 'normal': 24, 'low': 72}

# 'waiting' = blocked on the customer, so its clock doesn't escalate
ESCALATABLE_STATUSES = ('open', 'working')
ACTIVE_STATUSES = ('open', 'working', 'waiting', 'escalated')


def sla_hours(priority: str) -> int:
    hours = {**DEFAULT_SLA_HOURS, **getattr(settings, 'CALLCENTER_CASE_SLA_HOURS', {})}
    return hours.get(priority, hours['normal'])


def default_sla_due(priority: str, start=None):
    return (start or timezone.now()) + timedelta(hours=sla_hours(priority))


def backfill_missing_sla() -> int:
    """Active cases without a deadline get one counted from now (no backlog flood)."""
    from apps.callcenter.models import CustomerCase
    n = 0
    for case in CustomerCase.objects.filter(status__in=ACTIVE_STATUSES, sla_due__isnull=True):
        CustomerCase.objects.filter(pk=case.pk, sla_due__isnull=True).update(
            sla_due=default_sla_due(case.priority))
        n += 1
    return n


def escalate_breached_cases() -> int:
    """Escalate open/working cases past sla_due. Idempotent: escalated cases are skipped."""
    from django.db.models import Q
    from apps.audit.models import AuditLog
    from apps.callcenter.models import CaseEvent, CustomerCase
    from apps.notifications.models import Notification
    from apps.users.models import StaffProfile

    now = timezone.now()
    escalated = 0
    breached = CustomerCase.objects.filter(
        status__in=ESCALATABLE_STATUSES, sla_due__lt=now,
    ).select_related('customer', 'assigned_to')

    for case in breached:
        overdue_h = round((now - case.sla_due).total_seconds() / 3600, 1)
        reason = f'تصعيد تلقائي: تجاوز موعد SLA بـ {overdue_h} ساعة (الأولوية: {case.get_priority_display()})'
        with transaction.atomic():
            updated = CustomerCase.objects.filter(
                pk=case.pk, status__in=ESCALATABLE_STATUSES,
            ).update(status='escalated', escalated_at=now,
                     escalation_reason=reason, updated_at=now)
            if not updated:
                continue  # changed concurrently
            CaseEvent.objects.create(case=case, event_type='system', message=f'⏰ {reason}')
            AuditLog.log('case_sla_auto_escalated', obj=case,
                         changes={'status': [case.status, 'escalated']}, note=reason)

        recipients = StaffProfile.objects.filter(is_active=True).filter(
            Q(role__in=('admin', 'supervisor')) | Q(pk=case.assigned_to_id)
        ).distinct()
        title = f'⏰ تجاوز SLA — {case.case_number}'
        body = f'{case.title} — {case.customer.name}. {reason}'
        for staff in recipients:
            try:
                Notification.send_to_user(staff, 'case_sla_breach', title=title, body=body,
                                          dedup_key=f'case_sla:{case.pk}', dedup_once=True)
            except Exception:
                logger.exception('case SLA notify failed for case %s', case.pk)
        escalated += 1

    return escalated
