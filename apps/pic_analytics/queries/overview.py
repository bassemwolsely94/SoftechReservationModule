"""
apps/pic_analytics/queries/overview.py — the Overview tab's KPI cards and monthly trend (doc 33 §4/§6).

Reads PicDayFact / PicRollup / Customer only. A VISIT is a (pic, day) with invoices > 0, so a PIC
is counted once per day however many invoices / rows it has. Amounts come from the user's
branches only; the new / returning / reactivated LABELS are chain-wide (doc 33 §5).
"returning" includes the reactivated PICs (reactivated is a sub-count, doc 33 §4).
"""
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Max, Min, Q, Sum
from django.db.models.functions import TruncMonth

from apps.customers.models import Customer
from apps.pic_analytics import rules
from apps.pic_analytics.models import PicDayFact

NEW_RELIABLE_FROM = '2025-08-01'
ZERO = Decimal('0')


def visitor_set(f, access, start=None, end=None):
    """Distinct PICs with a visit (invoices > 0) in the range, scoped like every other amount."""
    return set(f.facts(access, start=start, end=end).exclude(pic='').filter(invoices__gt=0)
               .values_list('pic', flat=True).distinct())


def classify_visitors(f, access, pics=None):
    """{pic: 'new'|'returning'|'reactivated'} for the PICs visiting in the period (or just `pics`),
    computed CHAIN-WIDE: first purchase / previous visit over all branches (doc 33 §5)."""
    visitors = f.facts(access).exclude(pic='').filter(invoices__gt=0)
    if pics is not None:
        visitors = visitors.filter(pic__in=pics)
    visitors = visitors.values('pic')
    hist = (PicDayFact.objects.filter(pic__in=visitors, invoices__gt=0).values('pic')
            .annotate(fp=Min('day'),
                      prev=Max('day', filter=Q(day__lt=f.start)),
                      fv=Min('day', filter=Q(day__gte=f.start, day__lte=f.end))))
    created = dict(Customer.objects.filter(softech_pic__in=visitors)
                   .values_list('softech_pic', 'softech_created_at'))
    out = {}
    for h in hist:
        if h['fv'] is None:        # visits only outside the period (chain-wide row of another scope)
            continue
        out[h['pic']] = rules.classify_pic(h['fp'], created.get(h['pic']), h['prev'], f.start, f.end, h['fv'])
    return out


def previous_period(f):
    days = (f.end - f.start).days + 1
    pend = f.start - timedelta(days=1)
    return pend - timedelta(days=days - 1), pend


def retention_pct_for(f, access, current_pics):
    """% of the previous equal-length period's PICs that bought again in `current_pics`;
    None when that period predates our history or had no PICs."""
    pstart, pend = previous_period(f)
    if pstart < f.data_from:
        return None
    r = rules.retention(visitor_set(f, access, pstart, pend), set(current_pics))
    return None if r is None else round(r * 100, 2)


def overview(f, access) -> dict:
    qs = f.facts(access).exclude(pic='')
    per_pic = list(qs.values('pic').annotate(
        s_net=Sum('enet'), s_cost=Sum('cost'), s_units=Sum('units'), s_inv=Sum('invoices'),
        s_vis=Count('day', distinct=True, filter=Q(invoices__gt=0))))
    visitors = [r for r in per_pic if r['s_vis'] > 0]
    n_pics = len(visitors)
    visits = sum(r['s_vis'] for r in visitors)
    net = sum((r['s_net'] or ZERO for r in per_pic), ZERO)
    cost = sum((r['s_cost'] or ZERO for r in per_pic), ZERO)
    units = sum((r['s_units'] or ZERO for r in per_pic), ZERO)
    invoices = sum(r['s_inv'] or 0 for r in per_pic)

    labels = classify_visitors(f, access)
    n_new = sum(1 for r in visitors if labels.get(r['pic']) == 'new')
    n_react = sum(1 for r in visitors if labels.get(r['pic']) == 'reactivated')

    # categories per visit: merge every row of a pic-day, count categories with positive net
    merged = {}
    for pic, day, inv, cats in qs.values_list('pic', 'day', 'invoices', 'net_by_category'):
        m = merged.setdefault((pic, day), [0, {}])
        m[0] += inv
        for c, v in (cats or {}).items():
            m[1][c] = m[1].get(c, ZERO) + Decimal(str(v))
    cat_counts = [sum(1 for v in m[1].values() if v > 0) for m in merged.values() if m[0] > 0]
    basket_categories = round(sum(cat_counts) / len(cat_counts), 2) if cat_counts else None

    # monthly trend; a PIC is "new" in its first visit month of the range
    month_rows = list(qs.annotate(m=TruncMonth('day')).values('m', 'pic').annotate(
        s_net=Sum('enet'), s_vis=Count('day', distinct=True, filter=Q(invoices__gt=0))))
    first_month, months = {}, {}
    for r in month_rows:
        key = r['m'].strftime('%Y-%m')
        b = months.setdefault(key, {'month': key, 'distinct_pics': 0, 'new': 0, 'visits': 0, 'net': ZERO})
        b['net'] += r['s_net'] or ZERO
        if r['s_vis'] > 0:
            b['distinct_pics'] += 1
            b['visits'] += r['s_vis']
            if r['pic'] not in first_month or key < first_month[r['pic']]:
                first_month[r['pic']] = key
    for pic, key in first_month.items():
        if labels.get(pic) == 'new':
            months[key]['new'] += 1

    # retention against the previous period of equal length (None when it predates our history)
    retention_pct = retention_pct_for(f, access, {x['pic'] for x in visitors})

    no_pic_net = ZERO
    if not f.has_pic_filters:
        no_pic_net = f.facts(access, pic_filters=False).filter(pic='').aggregate(s=Sum('enet'))['s'] or ZERO

    out = {
        'distinct_pics': n_pics, 'new': n_new, 'returning': n_pics - n_new, 'reactivated': n_react,
        'visits': visits, 'invoices': invoices, 'net': net,
        # units / categories are whole-basket figures: not meaningful under a category filter
        'units': None if f.category else units,
        'basket_net': round(net / visits, 2) if visits else None,
        'basket_units': None if f.category or not visits else round(units / visits, 2),
        'basket_categories': None if f.category else basket_categories,
        'visits_per_pic': round(visits / n_pics, 2) if n_pics else None,
        'retention_pct': retention_pct,
        'calls_in': None, 'calls_out': None, 'missed_not_returned': None,   # Task 9
        'no_pic_net': no_pic_net,
        'new_reliable_from': None if Customer.objects.filter(softech_created_at__isnull=False).exists()
        else NEW_RELIABLE_FROM,
        'by_month': [months[k] for k in sorted(months)],
    }
    if access.sees_cost:
        # cost is per whole fact row, so a category-filtered GP cannot be split honestly
        gp = None if f.category else net - cost
        out['gp'] = gp
        out['gp_pct'] = round(gp / net * 100, 2) if gp is not None and net else None
    return out
