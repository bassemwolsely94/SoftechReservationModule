"""
Who gets a phone alert, and on which number.

``resolve`` is deterministic: owners / assignees / on-shift staff / escalation list, minus the
actor, normalised with ``core.sms.sms_number`` and de-duplicated by phone (first staff wins).
"""
import re
from datetime import timedelta
from typing import NamedTuple, Optional

from django.db.models import Q
from django.utils import timezone

from core.sms import sms_number

from .events import EVENTS

DEVICE_RECENCY = timedelta(hours=4)
_WEEKDAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']


class Recipient(NamedTuple):
    staff: Optional[object]   # users.StaffProfile, or None for a bare branch mobile
    phone: str


def is_plausible_phone(phone):
    """After sms_number: Egyptian international form = '20' + 10 digits (12 digits). Rejects '20' from blanks/junk."""
    return bool(re.fullmatch(r'20\d{10}', phone or ''))


def _eligible(qs):
    """Active staff who may be alerted and have a phone."""
    return qs.filter(is_active=True, phone_alerts_enabled=True).exclude(phone='')


def _covers_day(assignment, shift, day):
    if assignment.valid_from > day:
        return False
    if assignment.valid_until is not None and assignment.valid_until < day:
        return False
    days = [d.strip().lower() for d in (shift.days_of_week or '').split(',') if d.strip()]
    return _WEEKDAYS[day.weekday()] in days


def _shift_covers(assignment, now):
    shift = assignment.shift
    if not shift.is_active:
        return False
    local = timezone.localtime(now)
    today, t = local.date(), local.time()
    start, end = shift.start_time, shift.end_time
    if start <= end:
        return start <= t <= end and _covers_day(assignment, shift, today)
    # Overnight shift: the evening part belongs to today, the after-midnight part to yesterday.
    if t >= start:
        return _covers_day(assignment, shift, today)
    if t <= end:
        return _covers_day(assignment, shift, today - timedelta(days=1))
    return False


def on_shift_staff(branch, now=None):
    """Staff of ``branch`` seen on a branch device within 4 h, plus those whose shift covers ``now``."""
    from apps.access.models import DeviceUser
    from apps.hr.models import ShiftAssignment
    from apps.users.models import StaffProfile

    if branch is None:
        return []
    now = now or timezone.now()
    # Device path: approved devices of this branch, and only staff whose home branch is this branch
    # (a visitor signed in on the PC is not "on shift" here).
    ids = set(DeviceUser.objects.filter(
        device__branch=branch, device__status='approved', user__branch=branch,
        last_seen__gte=now - DEVICE_RECENCY,
    ).values_list('user_id', flat=True))
    day = timezone.localtime(now).date()
    candidates = ShiftAssignment.objects.filter(
        shift__branch=branch, shift__is_active=True, valid_from__lte=day,
    ).filter(Q(valid_until__isnull=True) | Q(valid_until__gte=day - timedelta(days=1))
             ).select_related('shift')
    ids |= {a.staff_id for a in candidates if _shift_covers(a, now)}
    return list(_eligible(StaffProfile.objects.filter(pk__in=ids)).order_by('pk'))


def source_branch(event, source):
    """The branch a source record belongs to (None if it has none)."""
    if source is None or event is None:
        return None
    if event.source_model == 'notifications.phonealert':
        return source_branch(EVENTS.get(source.event), source.source)
    if event.source_model == 'transfers.transferrequest':
        return source.requesting_branch
    if event.source_model == 'tasks.operationaltask':
        if source.branch_id:
            return source.branch
        return source.created_by.branch if source.created_by_id else None
    return getattr(source, 'branch', None)


def _staff_by_ids(ids):
    from apps.users.models import StaffProfile
    return list(_eligible(StaffProfile.objects.filter(pk__in=ids)).order_by('pk'))


def _owners(kind, branch, escalation=False):
    from .models import WorkOwner
    base = WorkOwner.objects.filter(kind=kind, active=True, is_escalation=escalation)
    rows = list(base.filter(branch=branch)) if branch is not None else []
    if not rows:
        rows = list(base.filter(branch__isnull=True))
    return _staff_by_ids([r.staff_id for r in rows])


def _branch_mobile(branch):
    if branch is None:
        return ''
    from apps.branches.models import BranchSettings
    row = BranchSettings.objects.filter(branch=branch).first()
    return (row.alert_mobile or '').strip() if row else ''


def resolve(event, source, actor=None, now=None):
    """Recipients for ``event`` on ``source`` (for 'escalation', ``source`` is the original PhoneAlert)."""
    staff_list, extra = [], []
    branch = source_branch(event, source)

    if event.recipients == 'owner':
        staff_list = _owners(event.owner_kind, branch)
    elif event.recipients == 'person':
        ids = [source.assigned_to_id] if getattr(source, 'assigned_to_id', None) else []
        if event.source_model == 'tasks.operationaltask':
            ids += list(source.assignments.values_list('staff_id', flat=True))
        staff_list = _staff_by_ids(ids)
    elif event.recipients == 'branch':
        staff_list = on_shift_staff(branch, now)
        mobile = _branch_mobile(branch)
        if mobile:
            extra.append(mobile)
    elif event.recipients == 'escalation':
        from .models import PhoneAlertPolicy
        # «يُصعَّد إلى»: the escalated event's own list first, then the escalation row's list,
        # then the owner kind's escalation owners, then supervisors.
        orig = EVENTS.get(source.event) if source is not None else None
        chosen = []
        for key in ([orig.key] if orig else []) + [event.key]:
            policy = PhoneAlertPolicy.for_event(key)
            chosen = [s.pk for s in policy.escalate_to.all()] if policy else []
            if chosen:
                break
        if chosen:
            staff_list = _staff_by_ids(chosen)
        else:
            if orig and orig.owner_kind:
                staff_list = _owners(orig.owner_kind, branch, escalation=True)
            else:
                # Controller ruling: no owner_kind (person/branch events) and no escalate_to list
                # -> escalate to active supervisors.
                from apps.users.models import StaffProfile
                staff_list = list(_eligible(StaffProfile.objects.filter(role='supervisor')).order_by('pk'))

    actor_id = getattr(actor, 'pk', None)
    actor_phone = sms_number(actor.phone) if actor is not None and getattr(actor, 'phone', '') else None
    out, seen = [], set()
    for s in staff_list:
        phone = sms_number(s.phone)
        if not is_plausible_phone(phone) or s.pk == actor_id or phone == actor_phone or phone in seen:
            continue
        seen.add(phone)
        out.append(Recipient(s, phone))
    for raw in extra:
        phone = sms_number(raw)
        if not is_plausible_phone(phone) or phone == actor_phone or phone in seen:
            continue
        seen.add(phone)
        out.append(Recipient(None, phone))
    return out
