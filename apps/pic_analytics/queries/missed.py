"""
apps/pic_analytics/queries/missed.py — the «المكالمات الفائتة» tab (doc 33 §4 returned rule, §7).

Missed = inbound, not answered, not a transfer leg. Missed calls IGNORE the agent filter (a call lost
in the queue has no agent). Returned = calls.returned_map (answered call, either direction, same
number, within pic_call_return_hours). Management only. All times are Cairo-local.
Heatmap weekday: 0 = Saturday ... 6 = Friday (the Egyptian week).
"""
from collections import Counter, defaultdict
from decimal import Decimal
from statistics import median

from django.db.models import Max, Sum
from django.utils import timezone

from apps.customers import access as cust_access
from apps.customers.models import Customer
from apps.pbx.models import AgentExtension
from apps.pic_analytics.models import PicDayFact
from apps.pic_analytics.queries.calls import (
    _day, _followed_by_purchase, _purchase_days, calls_qs, reach_stats, returned_map)
from apps.pic_analytics.queries.retention import MAX_PAGE_SIZE, _int_param
from apps.pic_analytics.settings import setting

DENIED = 'تبويب المكالمات الفائتة للإدارة فقط'


def _require(access):
    if not access.sees_calls_tabs:
        raise PermissionError(DENIED)


def _missed(f):
    return list(calls_qs(f, use_agent=False).filter(direction='inbound').exclude(status='answered')
                .select_related('customer').order_by('call_at'))


def _minutes(call, returned_at):
    return round((returned_at - call.call_at).total_seconds() / 60, 1)


def _pending_callbacks(calls) -> dict:
    """{call id: {'due': iso}} for missed calls whose number already has a scheduled call-back
    (CallLog status='callback' on that number, due at/after the missed call)."""
    from apps.callcenter.models import CallLog
    numbers = {c.customer_number for c in calls if c.customer_number}
    if not numbers:
        return {}
    logs = defaultdict(list)
    for num, due in (CallLog.objects.filter(status='callback', phone_number__in=numbers, callback_due__isnull=False)
                     .values_list('phone_number', 'callback_due')):
        logs[num].append(due)
    out = {}
    for c in calls:
        dues = [d for d in logs.get(c.customer_number, ()) if d >= c.call_at]
        if dues:
            out[c.id] = {'due': timezone.localtime(min(dues)).isoformat()}
    return out


def missed_summary(f, access) -> dict:
    _require(access)
    calls = _missed(f)
    rm = returned_map(calls)
    mins = [_minutes(c, rm[c.id]) for c in calls if rm[c.id] is not None]
    heat = Counter()
    for c in calls:
        local = timezone.localtime(c.call_at)
        heat[((local.weekday() + 2) % 7, local.hour)] += 1      # Python Mon=0 -> Egyptian Sat=0
    queues = Counter(c.queue for c in calls)
    return {
        'missed': len(calls),
        'missed_numbers': len({c.phone_key for c in calls if c.phone_key}),
        'returned': len(mins), 'not_returned': len(calls) - len(mins),
        'median_minutes_to_return': median(mins) if mins else None,
        'heatmap': [[wd, hr, n] for (wd, hr), n in sorted(heat.items())],
        'by_queue': [{'queue': q, 'missed': n} for q, n in sorted(queues.items(), key=lambda x: (-x[1], x[0]))],
    }


def missed_rows(f, access, only_not_returned, page, page_size=50) -> dict:
    """Missed calls joined to their PIC, biggest lifetime net first, newest call first."""
    _require(access)
    page = _int_param(page, 'الصفحة', 1)
    # page_size=None = everything (internal, Excel export only; the HTTP layer always passes a capped int)
    page_size = None if page_size is None else _int_param(page_size, 'حجم الصفحة', 1, MAX_PAGE_SIZE)
    calls = _missed(f)
    rm = returned_map(calls)
    if only_not_returned:
        # the action list: a row leaves as soon as ANY answered call on its number follows it (no 24 h cut-off)
        followed = returned_map(calls, any_time=True)
        calls = [c for c in calls if followed[c.id] is None]

    pics = {c.pic for c in calls if c.pic}
    life = {r['pic']: r['s'] or Decimal('0') for r in PicDayFact.objects.filter(pic__in=pics, day__lte=f.end)
            .values('pic').annotate(s=Sum('net'))}
    last = {r['pic']: r['m'] for r in PicDayFact.objects.filter(pic__in=pics, invoices__gt=0, day__lte=f.end)
            .values('pic').annotate(m=Max('day'))}
    calls.sort(key=lambda c: c.call_at, reverse=True)
    calls.sort(key=lambda c: (0, 0) if c.pic not in life else (1, life[c.pic]), reverse=True)

    chunk = calls if page_size is None else calls[(page - 1) * page_size: page * page_size]
    cpics = {c.pic for c in chunk if c.pic}
    customers = {}
    for cu in Customer.objects.filter(softech_pic__in=cpics).order_by('-pk'):
        customers[cu.softech_pic] = cu              # lowest pk wins (iterated last)
    days = _purchase_days(cpics)
    window = int(setting('pic_call_purchase_days'))
    can_see = cust_access.phones_checker(getattr(access.profile, 'user', None))
    pending = _pending_callbacks(chunk)
    rows = []
    for c in chunk:
        cust = c.customer if c.customer_id else customers.get(c.pic)
        row = {
            'call_id': c.id, 'call_at': timezone.localtime(c.call_at).isoformat(),
            'customer_number': c.customer_number, 'queue': c.queue,
            'pic': c.pic, 'shared_pics': c.shared_pics or [],
            'customer_name': cust.name if cust else '', 'segment': cust.segment if cust else '',
            'last_purchase': last.get(c.pic) if c.pic else None,
            'lifetime_net': life.get(c.pic) if c.pic else None,
            'bought_within_7d': bool(c.pic) and _followed_by_purchase(c.pic, _day(c.call_at), days, window),
            'returned_at': rm[c.id].astimezone(timezone.get_current_timezone()).isoformat() if rm[c.id] else None,
            'minutes_to_return': _minutes(c, rm[c.id]) if rm[c.id] else None,
            'callback_pending': pending.get(c.id),
        }
        visible = bool(cust and can_see(cust))
        cust_access.mask_fields(row, ['customer_number'], visible)
        rows.append(row)
    return {'count': len(calls), 'rows': rows}


def unanswered_summary(f, access) -> list:
    """Outbound calls per agent extension (the agent filter applies): how many went unanswered and how
    many tries it took to reach a number (same reach rule as the call-center tab)."""
    _require(access)
    rows = list(calls_qs(f).filter(direction='outbound').exclude(agent_ext='').order_by('call_at')
                .values_list('agent_ext', 'agent_name', 'call_at', 'status', 'phone_key'))
    agg = {}
    attempts = []
    for ext, name, at, status, key in rows:
        a = agg.setdefault(ext, {'pbx_name': '', 'attempts': 0, 'unanswered': 0})
        a['pbx_name'] = a['pbx_name'] or name
        a['attempts'] += 1
        if status != 'answered':
            a['unanswered'] += 1
        if key:
            attempts.append((ext, key, _day(at), status == 'answered'))
    tries, not_reached = reach_stats(attempts)
    exts = {e.extension: e for e in AgentExtension.objects.filter(extension__in=list(agg))
            .select_related('staff__user')}
    out = []
    for ext in sorted(agg, key=lambda e: (-agg[e]['unanswered'], e)):
        a, e = agg[ext], exts.get(ext)
        t = tries.get(ext)
        out.append({
            'agent_ext': ext,
            'staff_name': (e.staff.full_name or None) if e and e.staff else None,
            'pbx_name': e.pbx_name if e and e.pbx_name else a['pbx_name'],
            'attempts': a['attempts'], 'unanswered': a['unanswered'],
            'reached_numbers': len(t) if t else 0, 'not_reached': not_reached.get(ext, 0),
            'avg_attempts_to_reach': round(sum(t) / len(t), 2) if t else None,
        })
    return out
