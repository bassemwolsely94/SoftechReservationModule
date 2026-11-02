"""
apps/pic_analytics/queries/calls.py — PBX calls joined to PICs (doc 33 §4 call statuses, §5, §6).

Reads pbx.CdrCall only (+ PicDayFact for call -> purchase). Transfer legs never count. A shared
number counts once, on CdrCall.pic; the overview totals count every customer call in range
(including pic='' / unresolved) for management. All dates are Cairo-local.
"""
from bisect import bisect_right
from collections import defaultdict
from datetime import datetime, time, timedelta

from django.utils import timezone

from apps.pbx.models import AgentExtension, CdrCall
from apps.pic_analytics.models import PicDayFact
from apps.pic_analytics.settings import setting


def _bounds(f):
    tz = timezone.get_current_timezone()
    lo = timezone.make_aware(datetime.combine(f.start, time.min), tz)
    hi = timezone.make_aware(datetime.combine(f.end + timedelta(days=1), time.min), tz)
    return lo, hi


def calls_qs(f):
    """Customer calls in the filter range (transfers out; the agent filter applies when set)."""
    lo, hi = _bounds(f)
    qs = CdrCall.objects.filter(is_transfer=False, call_at__gte=lo, call_at__lt=hi)
    if f.agent_ext:
        qs = qs.filter(agent_ext=f.agent_ext)
    return qs


def _day(dt):
    return timezone.localtime(dt).date()


def returned_map(calls) -> dict:
    """{call id: datetime of the first ANSWERED call (either direction) on the same number within
    pic_call_return_hours after it, or None}. `calls` = iterable of CdrCall-like rows with
    id, call_at, phone_key. Shared by the overview and the missed-calls tab (Task 10)."""
    calls = list(calls)
    window = timedelta(hours=int(setting('pic_call_return_hours')))
    keys = {c.phone_key for c in calls if c.phone_key}
    out = {c.id: None for c in calls}
    if not keys:
        return out
    lo = min(c.call_at for c in calls)
    hi = max(c.call_at for c in calls) + window
    answered = defaultdict(list)
    for key, at in (CdrCall.objects.filter(phone_key__in=keys, status='answered', is_transfer=False,
                                           call_at__gt=lo, call_at__lte=hi)
                    .order_by('call_at').values_list('phone_key', 'call_at')):
        answered[key].append(at)
    for c in calls:
        times = answered.get(c.phone_key)
        if not times:
            continue
        i = bisect_right(times, c.call_at)
        if i < len(times) and times[i] <= c.call_at + window:
            out[c.id] = times[i]
    return out


def _purchase_days(pics):
    days = defaultdict(set)
    for pic, day in (PicDayFact.objects.filter(pic__in=pics, invoices__gt=0)
                     .values_list('pic', 'day').distinct()):
        days[pic].add(day)
    return days


def _followed_by_purchase(pic, call_day, days_by_pic, window):
    last = call_day + timedelta(days=window)
    return any(call_day <= d <= last for d in days_by_pic.get(pic, ()))


def calls_by_pic(f, pics=None) -> dict:
    """{pic: {in, out, answered, missed, last_call, avg_days_between, talk_seconds,
    call_to_purchase}} counted on CdrCall.pic only; `pics` limits the PICs (None = all)."""
    qs = calls_qs(f).exclude(pic='')
    if pics is not None:
        qs = qs.filter(pic__in=pics)
    rows = list(qs.values_list('pic', 'call_at', 'direction', 'status', 'billable_seconds'))
    window = int(setting('pic_call_purchase_days'))
    days_by_pic = _purchase_days({r[0] for r in rows})
    out = {}
    for pic, at, direction, status, billable in rows:
        o = out.setdefault(pic, {'in': 0, 'out': 0, 'answered': 0, 'missed': 0, 'last_call': None,
                                 'talk_seconds': 0, 'call_to_purchase': 0, '_days': set()})
        o['in' if direction == 'inbound' else 'out'] += 1
        o['_days'].add(_day(at))
        if o['last_call'] is None or at > o['last_call']:
            o['last_call'] = at
        if status == 'answered':
            o['answered'] += 1
            o['talk_seconds'] += billable or 0
            if _followed_by_purchase(pic, _day(at), days_by_pic, window):
                o['call_to_purchase'] += 1
        elif direction == 'inbound':
            o['missed'] += 1
    for o in out.values():
        days = sorted(o.pop('_days'))
        o['avg_days_between'] = (round((days[-1] - days[0]).days / (len(days) - 1), 1)
                                 if len(days) > 1 else None)
    return out


def call_totals(f, pics=None) -> dict:
    """Overview call cards. `pics=None` (management) counts every customer call in range,
    unresolved shared numbers included, once; a set restricts to those PICs."""
    qs = calls_qs(f)
    if pics is not None:
        qs = qs.filter(pic__in=pics)
    calls_in = calls_out = 0
    missed = []
    for c in qs.only('id', 'call_at', 'direction', 'status', 'phone_key'):
        if c.direction == 'inbound':
            calls_in += 1
            if c.status != 'answered':
                missed.append(c)
        else:
            calls_out += 1
    rm = returned_map(missed)
    return {'calls_in': calls_in, 'calls_out': calls_out,
            'missed_not_returned': sum(1 for c in missed if rm[c.id] is None)}


def _new_pics_sold(f, access, codes):
    """Distinct NEW PICs whose first fact row(s) in the period carry a sales-agent user code."""
    from apps.pic_analytics.queries.overview import classify_visitors
    if not codes:
        return 0
    new_pics = {p for p, lab in classify_visitors(f, access).items() if lab == 'new'}
    first = {}
    for pic, day, sp in f.facts(access).filter(pic__in=new_pics).values_list('pic', 'day', 'salesperson'):
        cur = first.get(pic)
        if cur is None or day < cur[0]:
            first[pic] = (day, {sp})
        elif day == cur[0]:
            cur[1].add(sp)
    return sum(1 for _d, s in first.values() if s & codes)


def call_center(f, access) -> dict:
    """Per agent extension (management only): {'rows': [...], 'team_new_pics_sold': n}."""
    if not access.sees_calls_tabs:
        raise PermissionError('تبويب مركز الاتصال للإدارة فقط')
    from apps.forecasting.models import CallCenterConfig

    rows = list(calls_qs(f).exclude(agent_ext='').order_by('call_at').values_list(
        'agent_ext', 'agent_name', 'call_at', 'direction', 'status', 'billable_seconds',
        'pic', 'phone_key'))
    window = int(setting('pic_call_purchase_days'))
    days_by_pic = _purchase_days({r[6] for r in rows if r[6]})
    exts = {e.extension: e for e in AgentExtension.objects.filter(
        extension__in={r[0] for r in rows}).select_related('staff__user')}

    agg = {}
    attempts = defaultdict(list)       # (ext, phone_key, day) -> [answered?, ...] in time order
    for ext, name, at, direction, status, billable, pic, key in rows:
        a = agg.setdefault(ext, {'pbx_name': '', 'calls_in': 0, 'calls_out': 0, 'answered': 0,
                                 'talk_seconds': 0, 'pics': set(), 'ctp': 0, 'unanswered_out': 0})
        a['pbx_name'] = a['pbx_name'] or name
        answered = status == 'answered'
        if direction == 'inbound':
            a['calls_in'] += 1
        else:
            a['calls_out'] += 1
            if not answered:
                a['unanswered_out'] += 1
            if key:
                attempts[(ext, key, _day(at))].append(answered)
        if answered:
            a['answered'] += 1
            a['talk_seconds'] += billable or 0
            if pic:
                a['pics'].add(pic)
                if _followed_by_purchase(pic, _day(at), days_by_pic, window):
                    a['ctp'] += 1
    tries, not_reached = defaultdict(list), defaultdict(int)
    for (ext, _key, _d), seq in attempts.items():
        if True in seq:
            tries[ext].append(seq.index(True) + 1)
        else:
            not_reached[ext] += 1

    out = []
    for ext in sorted(agg, key=lambda e: (-(agg[e]['calls_in'] + agg[e]['calls_out']), e)):
        a, e = agg[ext], exts.get(ext)
        out.append({
            'agent_ext': ext,
            'staff_name': (e.staff.full_name or None) if e and e.staff else None,
            'pbx_name': e.pbx_name if e and e.pbx_name else a['pbx_name'],
            'calls_in': a['calls_in'], 'calls_out': a['calls_out'], 'answered': a['answered'],
            'talk_seconds': a['talk_seconds'], 'pics_reached': len(a['pics']),
            'call_to_purchase_pct': round(a['ctp'] / a['answered'] * 100, 1) if a['answered'] else None,
            'unanswered_out': a['unanswered_out'],
            'avg_attempts_to_reach': round(sum(tries[ext]) / len(tries[ext]), 2) if tries.get(ext) else None,
            'not_reached': not_reached.get(ext, 0),
        })

    # sales side: SOFTECH user codes are not tied to extensions -> one team figure
    codes = set(CallCenterConfig.get_solo().sales_agent_usercodes or [])
    return {'rows': out, 'team_new_pics_sold': _new_pics_sold(f, access, codes)}
