"""
apps/followups/call_lists.py

Outbound call campaigns built on follow-ups: pick a group of customers, create one
'custom' FollowUpTask each, split evenly between the chosen agents. Agents work the
list from their existing queue (my-queue), dialing with click-to-dial; outcomes,
call logs and auto-close are the normal follow-up ones.

Deterministic selection — no AI. Skips: no phone, refill opt-out, an open task already.
Criterion `refill_due` (C08): customers due for a refill from their own buying interval
(refill_due.py), ranked by expected value, consent per FOLLOWUPS_REFILL_DUE_CONSENT.
"""
import logging
from datetime import date

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from . import refill_due
from .models import CallList, FollowUpTask, FollowUpTaskAssignment

logger = logging.getLogger('elrezeiky.followups')

OPEN_STATUSES = ('pending', 'called')
CREATOR_ROLES = ('admin', 'supervisor', 'call_center')   # owner decision 2026-11-09


def _base(criteria: dict, user):
    """Named customers with a phone, inside the user's branch scope (narrowed by the chosen branches)."""
    from apps.customers.models import Customer
    from core import branch_scope
    from core.multi_filter import filter_in, multi_ids

    qs = Customer.objects.exclude(phone='').filter(is_guest=False, is_account_placeholder=False)
    ids = branch_scope.branch_ids(user)
    if ids is not None:
        qs = qs.filter(preferred_branch_id__in=ids)
    # one or several branches (criteria saved before multi-select carry branch_id); narrows the
    # branch scope above, never widens it
    branch_ids = multi_ids(criteria, 'branch_ids') or multi_ids(criteria, 'branch_id')
    return filter_in(qs, 'preferred_branch_id', branch_ids)


def candidates(criteria: dict, user):
    """Customers matching the criteria, inside the user's branch scope, with a phone."""
    from apps.customers import consent      # P-05: staff calls need no opt-in, but a "no" is honoured

    qs = _base(criteria, user)
    if criteria.get('refill_due'):
        # C08: consent per FOLLOWUPS_REFILL_DUE_CONSENT, and at most one refill call a month
        qs = refill_due.consent_filter(qs).exclude(pk__in=refill_due.recently_called_ids())
    else:
        segments = [s for s in (criteria.get('segments') or []) if s]
        if segments:
            qs = qs.filter(segment__in=segments)
        min_days = criteria.get('inactive_days_min')
        if min_days not in (None, ''):
            qs = qs.filter(days_since_last_visit__gte=int(min_days))
        max_days = criteria.get('inactive_days_max')
        if max_days not in (None, ''):
            qs = qs.filter(days_since_last_visit__lte=int(max_days))
        qs = consent.exclude_withdrawn(qs, consent.REFILL, 'call')
    qs = qs.exclude(pk__in=FollowUpTask.objects.filter(status__in=OPEN_STATUSES, customer__isnull=False)
                                               .values('customer_id'))
    return qs.order_by('-ltv', 'pk')


def selection(criteria: dict, user, limit=None):
    """(total, [Customer] in call order, refill-due map or None). Refill-due lists are ranked by the
    expected value of the due refills (refill_due.rank); the others by lifetime value."""
    qs = candidates(criteria, user)
    if not criteria.get('refill_due'):
        return qs.count(), (list(qs[:limit]) if limit else []), None
    due = refill_due.due_customers_cached()
    ok = set(qs.filter(pk__in=list(due)).values_list('pk', flat=True)) if due else set()
    ranked = [cid for cid in refill_due.rank(due) if cid in ok]
    picked = ranked[:limit] if limit else []
    by_id = qs.model.objects.in_bulk(picked)
    return len(ranked), [by_id[c] for c in picked if c in by_id], due


def _item_names(customers, due) -> dict:
    from apps.catalog.models import Item
    ids = {it['item_id'] for c in customers for it in due[c.pk]['items']}
    return dict(Item.objects.filter(pk__in=ids).values_list('pk', 'name')) if ids else {}


def _sample(customers, due, user) -> list:
    """Top rows of a refill-due preview — phone masked unless the user may see it (customers.access)."""
    from apps.customers import access
    names = _item_names(customers, due)
    out = []
    for c in customers:
        row = due[c.pk]
        out.append({
            'customer_id': c.pk, 'name': c.name,
            'phone': access.customer_phone(user, c, c.phone),
            'expected_value': str(row['value']), 'max_overdue': row['max_overdue'],
            'items': [{'name': names.get(it['item_id'], ''), 'interval': it['interval'],
                       'last': str(it['last']), 'due': str(it['due']), 'overdue': it['overdue'],
                       'value': str(it['value'])} for it in row['items'][:3]],
            'more_items': max(len(row['items']) - 3, 0),
        })
    return out


def preview(criteria: dict, user) -> dict:
    total, sample, due = selection(criteria, user, limit=10 if criteria.get('refill_due') else None)
    out = {'matching': total, 'will_create': min(total, CallList.MAX_SIZE),
           'cap': CallList.MAX_SIZE, 'capped': total > CallList.MAX_SIZE}
    if due is not None:
        in_scope = (_base(criteria, user).filter(pk__in=list(due)).count()) if due else 0
        out.update({'refill_due': True, 'due_in_scope': in_scope, 'skipped': in_scope - total,
                    'consent_mode': refill_due.cfg('CONSENT'), 'sample': _sample(sample, due, user)})
    return out


def create_call_list(*, name: str, script: str, criteria: dict, agents: list, actor, user) -> CallList:
    """Create the list, its tasks (round-robin over `agents`), one notice per agent. Atomic."""
    from apps.audit.models import AuditLog
    from apps.notifications.models import Notification

    _, customers, due = selection(criteria, user, limit=CallList.MAX_SIZE)
    today = date.today()
    names = _item_names(customers, due) if due else {}

    def _task(i, c):
        t = FollowUpTask(customer=c, branch_id=c.preferred_branch_id, task_type='custom',
                         due_date=today, call_list=cl,
                         assigned_to=agents[i % len(agents)], is_pinned=True,
                         pinned_by=actor, pinned_at=timezone.now())
        if due:
            # C08: anchored on the top due item, so the ERP auto-close marks it bought (the outcome)
            # when the same PIC buys it after the last sale. Type stays 'custom': the WhatsApp refill
            # reminder reads refill / chronic tasks only — this list never sends anything.
            row = due[c.pk]
            top = row['items'][0]
            t.item_id, t.source_sale_date = top['item_id'], top['last']
            t.phcode = (c.softech_pic or '')[:30]
            t.notes = refill_due.task_note(row, names)
        return t

    with transaction.atomic():
        cl = CallList.objects.create(name=name, script=script, criteria=criteria,
                                     created_by=actor, size=len(customers))
        tasks = FollowUpTask.objects.bulk_create([_task(i, c) for i, c in enumerate(customers)],
                                                 batch_size=500)
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
