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


def calls_qs(f, use_agent=True):
    """Customer calls in the filter range (transfers out; the agent filter applies when set, unless
    use_agent=False - missed calls lost in the queue have no agent)."""
    lo, hi = _bounds(f)
    qs = CdrCall.objects.filter(is_transfer=False, call_at__gte=lo, call_at__lt=hi)
    if use_agent and f.agent_ext:
        qs = qs.filter(agent_ext=f.agent_ext)
    return qs


def _day(dt):
    return timezone.localtime(dt).date()


def returned_map(calls, any_time=False) -> dict:
    """{call id: datetime of the first ANSWERED call (either direction) on the same number within
    pic_call_return_hours after it, or None}. `calls` = iterable of CdrCall-like rows with
    id, call_at, phone_key. Shared by the overview and the missed-calls tab (Task 10).
    `any_time=True` drops the window: ANY later answered call counts (the action list, doc 33 §7 -
    a row leaves «not returned» as soon as someone has called the number back)."""
    calls = list(calls)
    window = timedelta(hours=int(setting('pic_call_return_hours')))
    if any_time:
        window = timedelta(days=36500)
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
    call_to_purchase, call_to_purchase_same_day}} counted on CdrCall.pic only; `pics` limits the PICs (None = all)."""
    qs = calls_qs(f).exclude(pic='')
    if pics is not None:
        qs = qs.filter(pic__in=pics)
    rows = list(qs.values_list('pic', 'call_at', 'direction', 'status', 'billable_seconds'))
    window = int(setting('pic_call_purchase_days'))
    days_by_pic = _purchase_days({r[0] for r in rows})
    out = {}
    for pic, at, direction, status, billable in rows:
        o = out.setdefault(pic, {'in': 0, 'out': 0, 'answered': 0, 'missed': 0, 'last_call': None,
                                 'talk_seconds': 0, 'call_to_purchase': 0, 'call_to_purchase_same_day': 0,
                                 '_days': set()})
        o['in' if direction == 'inbound' else 'out'] += 1
        o['_days'].add(_day(at))
        if o['last_call'] is None or at > o['last_call']:
            o['last_call'] = at
        if status == 'answered':
            o['answered'] += 1
            o['talk_seconds'] += billable or 0
            if _followed_by_purchase(pic, _day(at), days_by_pic, window):
                o['call_to_purchase'] += 1
                if _followed_by_purchase(pic, _day(at), days_by_pic, 0):
                    o['call_to_purchase_same_day'] += 1
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
    calls_in = qs.filter(direction='inbound').count()
    calls_out = qs.exclude(direction='inbound').count()
    mq = calls_qs(f, use_agent=False)          # missed calls ignore the agent filter
    if pics is not None:
        mq = mq.filter(pic__in=pics)
    missed = list(mq.filter(direction='inbound').exclude(status='answered')
                  .only('id', 'call_at', 'phone_key'))
    rm = returned_map(missed)
    return {'calls_in': calls_in, 'calls_out': calls_out,
            'missed_not_returned': sum(1 for c in missed if rm[c.id] is None)}


def _new_pic_salespeople(f, access):
    """{pic: {salesperson codes on its first fact day in the period}} for the NEW PICs."""
    from apps.pic_analytics.queries.overview import classify_visitors
    new_pics = {p for p, lab in classify_visitors(f, access).items() if lab == 'new'}
    first = {}
    for pic, day, sp in f.facts(access).filter(pic__in=new_pics).values_list('pic', 'day', 'salesperson'):
        cur = first.get(pic)
        if cur is None or day < cur[0]:
            first[pic] = (day, {sp})
        elif day == cur[0]:
            cur[1].add(sp)
    return {pic: s for pic, (_d, s) in first.items()}


def agent_labels(exts) -> dict:
    """{extension: «name (ext)»} - staff name, else the PBX name, else the extension itself.
    Shared by the filter options and the conversion split."""
    exts = {x for x in exts if x}
    by_ext = {e.extension: e for e in AgentExtension.objects.filter(extension__in=exts).select_related('staff__user')}
    pbx = dict(CdrCall.objects.filter(agent_ext__in=exts).exclude(agent_name='')
               .order_by('call_at').values_list('agent_ext', 'agent_name'))
    out = {}
    for x in exts:
        e = by_ext.get(x)
        name = (e.staff.full_name if e and e.staff else '') or (e.pbx_name if e else '') or pbx.get(x) or x
        out[x] = f'{name} ({x})'
    return out


def _team_new_pics_sold(first_sp, codes):
    """Distinct NEW PICs whose first fact day carries one of the team's sales-agent user codes."""
    return sum(1 for s in first_sp.values() if s & codes) if codes else 0


def reach_stats(attempts):
    """attempts = outbound (ext, phone_key, day, answered) in time order. A number is 'reached' on a
    day when one of that agent's tries was answered. -> ({ext: [tries until reached, ...]},
    {ext: numbers never reached that day})."""
    seqs = defaultdict(list)
    for ext, key, day, answered in attempts:
        seqs[(ext, key, day)].append(answered)
    tries, not_reached = defaultdict(list), defaultdict(int)
    for (ext, _key, _d), seq in seqs.items():
        if True in seq:
            tries[ext].append(seq.index(True) + 1)
        else:
            not_reached[ext] += 1
    return tries, not_reached


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
    attempts = []                      # outbound (ext, phone_key, day, answered) in time order
    for ext, name, at, direction, status, billable, pic, key in rows:
        a = agg.setdefault(ext, {'pbx_name': '', 'calls_in': 0, 'calls_out': 0, 'answered': 0,
                                 'answered_pic': 0, 'talk_seconds': 0, 'pics': set(), 'ctp': 0, 'ctp0': 0,
                                 'unanswered_out': 0})
        a['pbx_name'] = a['pbx_name'] or name
        answered = status == 'answered'
        if direction == 'inbound':
            a['calls_in'] += 1
        else:
            a['calls_out'] += 1
            if not answered:
                a['unanswered_out'] += 1
            if key:
                attempts.append((ext, key, _day(at), answered))
        if answered:
            a['answered'] += 1
            a['talk_seconds'] += billable or 0
            if pic:
                a['answered_pic'] += 1          # denominator: answered calls that reach a PIC
                a['pics'].add(pic)
                if _followed_by_purchase(pic, _day(at), days_by_pic, window):
                    a['ctp'] += 1
                    if _followed_by_purchase(pic, _day(at), days_by_pic, 0):
                        a['ctp0'] += 1
    tries, not_reached = reach_stats(attempts)

    # sales side: a NEW pic is credited to the agent whose SOFTECH user code rang up its first sale
    first_sp = _new_pic_salespeople(f, access)
    sold = defaultdict(int)
    for codes_ in first_sp.values():
        for code in codes_:
            sold[code] += 1

    out = []
    for ext in sorted(agg, key=lambda e: (-(agg[e]['calls_in'] + agg[e]['calls_out']), e)):
        a, e = agg[ext], exts.get(ext)
        code = (e.staff.softech_user_id or '').strip() if e and e.staff else ''
        out.append({
            'agent_ext': ext,
            'staff_name': (e.staff.full_name or None) if e and e.staff else None,
            'pbx_name': e.pbx_name if e and e.pbx_name else a['pbx_name'],
            'calls_in': a['calls_in'], 'calls_out': a['calls_out'], 'answered': a['answered'],
            'talk_seconds': a['talk_seconds'], 'pics_reached': len(a['pics']),
            'call_to_purchase_pct': round(a['ctp'] / a['answered_pic'] * 100, 1) if a['answered_pic'] else None,
            'call_to_purchase_same_day_pct': (round(a['ctp0'] / a['answered_pic'] * 100, 1)
                                              if a['answered_pic'] else None),
            'new_pics_sold': sold.get(code, 0) if code else None,
            'unanswered_out': a['unanswered_out'],
            'avg_attempts_to_reach': round(sum(tries[ext]) / len(tries[ext]), 2) if tries.get(ext) else None,
            'not_reached': not_reached.get(ext, 0),
        })

    # the team figure: SOFTECH sales-agent user codes from the call-center config
    codes = set(CallCenterConfig.get_solo().sales_agent_usercodes or [])
    return {'rows': out, 'team_new_pics_sold': _team_new_pics_sold(first_sp, codes)}
