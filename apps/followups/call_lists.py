"""
apps/followups/call_lists.py

Outbound call campaigns built on follow-ups: pick a group of customers, create one
'custom' FollowUpTask each, split evenly between the chosen agents. Agents work the
list from their existing queue (my-queue), dialing with click-to-dial; outcomes,
call logs and auto-close are the normal follow-up ones.

Deterministic selection — no AI. Skips: no phone, refill opt-out, an open task already.
"""
import logging
from datetime import date

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from .models import CallList, FollowUpTask, FollowUpTaskAssignment, RefillReminderOptOut

logger = logging.getLogger('elrezeiky.followups')

OPEN_STATUSES = ('pending', 'called')
CREATOR_ROLES = ('admin', 'supervisor', 'call_center')   # owner decision 2026-11-09


def candidates(criteria: dict, user):
    """Customers matching the criteria, inside the user's branch scope, with a phone."""
    from apps.customers.models import Customer
    from core import branch_scope
    from core.multi_filter import filter_in, multi_ids

    qs = Customer.objects.exclude(phone='').filter(is_guest=False)
    ids = branch_scope.branch_ids(user)
    if ids is not None:
        qs = qs.filter(preferred_branch_id__in=ids)

    segments = [s for s in (criteria.get('segments') or []) if s]
    if segments:
        qs = qs.filter(segment__in=segments)
    # one or several branches (criteria saved before multi-select carry branch_id); narrows the
    # branch scope above, never widens it
    branch_ids = multi_ids(criteria, 'branch_ids') or multi_ids(criteria, 'branch_id')
    qs = filter_in(qs, 'preferred_branch_id', branch_ids)
    min_days = criteria.get('inactive_days_min')
    if min_days not in (None, ''):
        qs = qs.filter(days_since_last_visit__gte=int(min_days))
    max_days = criteria.get('inactive_days_max')
    if max_days not in (None, ''):
        qs = qs.filter(days_since_last_visit__lte=int(max_days))

    qs = (qs.exclude(pk__in=RefillReminderOptOut.objects.values('customer_id'))
            .exclude(pk__in=FollowUpTask.objects.filter(status__in=OPEN_STATUSES, customer__isnull=False)
                                                .values('customer_id')))
    return qs.order_by('-ltv', 'pk')


def preview(criteria: dict, user) -> dict:
    qs = candidates(criteria, user)
    total = qs.count()
    return {'matching': total, 'will_create': min(total, CallList.MAX_SIZE),
            'cap': CallList.MAX_SIZE, 'capped': total > CallList.MAX_SIZE}


def create_call_list(*, name: str, script: str, criteria: dict, agents: list, actor, user) -> CallList:
    """Create the list, its tasks (round-robin over `agents`), one notice per agent. Atomic."""
    from apps.audit.models import AuditLog
    from apps.notifications.models import Notification

    customers = list(candidates(criteria, user)[:CallList.MAX_SIZE])
    today = date.today()
    with transaction.atomic():
        cl = CallList.objects.create(name=name, script=script, criteria=criteria,
                                     created_by=actor, size=len(customers))
        tasks = FollowUpTask.objects.bulk_create([
            FollowUpTask(customer=c, branch_id=c.preferred_branch_id, task_type='custom',
                         due_date=today, call_list=cl,
                         assigned_to=agents[i % len(agents)], is_pinned=True,
                         pinned_by=actor, pinned_at=timezone.now())
            for i, c in enumerate(customers)
        ], batch_size=500)
        FollowUpTaskAssignment.objects.bulk_create([
            FollowUpTaskAssignment(task=t, staff=t.assigned_to, assigned_by=actor,
                                   assignment_reason='call_list')
            for t in tasks
        ], batch_size=500, ignore_conflicts=True)
        AuditLog.log('call_list_created', user=actor, obj=cl,
                     new_data={'criteria': criteria, 'size': len(customers),
                               'agents': [a.pk for a in agents]},
                     note=f'{name}: {len(customers)} عميل على {len(agents)} موظف')

    per_agent = {}
    for t in tasks:
        per_agent[t.assigned_to] = per_agent.get(t.assigned_to, 0) + 1
    for staff, n in per_agent.items():
        try:
            Notification.send_to_user(staff, 'followup', title=f'📞 قائمة اتصال جديدة: {name}',
                                      body=f'{n} عميل في طابورك — ابدأ من «طابوري».',
                                      dedup_key=f'call_list:{cl.pk}', dedup_once=True)
        except Exception:
            logger.exception('call list %s: notify failed for staff %s', cl.pk, staff.pk)
    return cl


def progress(lists) -> dict:
    """{list_id: {total, open, reached, done, no_answer}} in one query."""
    rows = (FollowUpTask.objects.filter(call_list__in=lists).values('call_list_id')
            .annotate(total=Count('id'),
                      open=Count('id', filter=Q(status='pending')),
                      no_answer=Count('id', filter=Q(status='called')),
                      done=Count('id', filter=Q(status__in=('done', 'auto_closed'))),
                      missed=Count('id', filter=Q(status__in=('missed', 'cancelled')))))
    return {r['call_list_id']: r for r in rows}


def close_call_list(cl: CallList, actor) -> int:
    """Close the list; still-open tasks are cancelled (kept for history)."""
    from apps.audit.models import AuditLog
    with transaction.atomic():
        n = FollowUpTask.objects.filter(call_list=cl, status__in=OPEN_STATUSES).update(
            status='cancelled', result_note='أُغلقت قائمة الاتصال')
        cl.status, cl.closed_at = 'closed', timezone.now()
        cl.save(update_fields=['status', 'closed_at'])
        AuditLog.log('call_list_closed', user=actor, obj=cl, note=f'{cl.name}: ألغيت {n} مهمة مفتوحة')
    return n
