"""
apps/pic_analytics/queries/pics.py — the PIC list tab (doc 33 §6): one row per PIC that visited in
the period. Sorting and paging happen in the database; the per-row detail (categories, channels,
branch of last visit, first/last purchase) is then read for the page's PICs only.
Amounts come from the user's branches; frequency / overdue labels are chain-wide (PicRollup).
"""
from decimal import Decimal

from django.db.models import Count, Max, Min, OuterRef, Q, Subquery, Sum

from apps.customers import access as cust_access
from apps.customers.models import Customer
from apps.pic_analytics import rules
from apps.pic_analytics.models import PicDayFact
from apps.pic_analytics.queries.calls import calls_by_pic
from apps.pic_analytics.queries.frequency import pic_frequency
from apps.pic_analytics.settings import setting

ZERO = Decimal('0')
ORDERS = {'net': 's_net', 'visits': 'visits', 'last_purchase': 'last_day',
          'days_since_last': 'last_day', 'name': 'name_sub'}


def _order_by(order):
    desc = (order or '-net').startswith('-')
    key = (order or '-net').lstrip('-')
    if key not in ORDERS:
        key, desc = 'net', True
    field = ORDERS[key]
    if key == 'days_since_last':          # most days since last = oldest last purchase
        desc = not desc
    return [('-' if desc else '') + field, 'pic']


def pic_rows(f, access, order='-net', page=1, page_size=50) -> dict:
    qs = f.facts(access).exclude(pic='')
    name = Customer.objects.filter(softech_pic=OuterRef('pic')).order_by('pk').values('name')[:1]
    agg = (qs.values('pic').annotate(
        s_net=Sum('enet'), s_gp=Sum('gp'), s_units=Sum('units'), s_inv=Sum('invoices'),
        visits=Count('day', distinct=True, filter=Q(invoices__gt=0)),
        last_day=Max('day', filter=Q(invoices__gt=0)), name_sub=Subquery(name))
        .filter(visits__gt=0))
    count = agg.count()
    page = max(int(page or 1), 1)
    page_size = max(int(page_size or 50), 1)
    chunk = list(agg.order_by(*_order_by(order))[(page - 1) * page_size: page * page_size])
    pics = [r['pic'] for r in chunk]

    # per-row detail for the page's PICs only
    cats, chans, last_visit = {}, {}, {}
    for pic, day, branch_id, inv, chan, bycat, enet in qs.filter(pic__in=pics).values_list(
            'pic', 'day', 'branch_id', 'invoices', 'channel_bucket', 'net_by_category', 'enet'):
        c = cats.setdefault(pic, {})
        for k, v in (bycat or {}).items():
            c[k] = c.get(k, ZERO) + Decimal(str(v))
        if inv > 0:
            if chan:
                chans.setdefault(pic, set()).add(chan)
            key = (day, enet or ZERO)
            if pic not in last_visit or key > last_visit[pic][0]:
                last_visit[pic] = (key, branch_id)
    span = {}
    for r in access.scope_facts(PicDayFact.objects.filter(pic__in=pics, invoices__gt=0, day__lte=f.end)
                                ).values('pic').annotate(first=Min('day'), last=Max('day')):
        span[r['pic']] = r
    freq = pic_frequency(pics, f.end)
    calls = calls_by_pic(f, set(pics))      # the page's PICs are already scoped visitors
    customers = {}
    for c in Customer.objects.filter(softech_pic__in=pics).order_by('-pk'):
        customers[c.softech_pic] = c            # lowest pk wins (iterated last)

    user = getattr(access.profile, 'user', None)
    factor = float(setting('pic_overdue_factor'))
    today = f.end
    rows = []
    for r in chunk:
        pic = r['pic']
        cust, fr, sp = customers.get(pic), freq.get(pic), span.get(pic, {})
        visits = r['visits']
        cl = calls.get(pic)
        last = sp.get('last')
        row = {
            'pic': pic, 'name': cust.name if cust else '', 'segment': cust.segment if cust else '',
            'last_branch': last_visit.get(pic, (None, None))[1],
            'net': r['s_net'] or ZERO, 'visits': visits, 'invoices': r['s_inv'] or 0,
            'units': None if f.category else (r['s_units'] or ZERO),
            'basket_net': round((r['s_net'] or ZERO) / visits, 2),
            'categories': sorted(k for k, v in cats.get(pic, {}).items() if v > 0),
            'channels': sorted(chans.get(pic, ())),
            'first_purchase': sp.get('first'), 'last_purchase': last,
            'days_since_last': (today - last).days if last else None,
            'months_a': fr['months_a'] if fr else None, 'streak_b': fr['streak_b'] if fr else None,
            'cycle_bucket': fr['cycle_bucket'] if fr else '',
            'overdue': bool(fr and fr['last_visit'] and rules.is_overdue(
                fr['last_visit'], fr['cycle_days'], today, factor)),
            'phone': cust.phone if cust else '',
            'calls_in': cl['in'] if cl else 0, 'calls_out': cl['out'] if cl else 0,
            'missed': cl['missed'] if cl else 0, 'last_call': cl['last_call'] if cl else None,
            'avg_days_between_calls': cl['avg_days_between'] if cl else None,
            'talk_time': cl['talk_seconds'] if cl else 0,
            'call_to_purchase': cl['call_to_purchase'] if cl else 0,
        }
        if cust and user is not None:
            visible = cust_access.phones_visible(user, cust)
        else:
            visible = False
        cust_access.mask_fields(row, ['phone'], visible)
        if access.sees_cost:
            gp = None if f.category else (r['s_gp'] or ZERO)
            row['gp'] = gp
        rows.append(row)
    return {'count': count, 'rows': rows}
