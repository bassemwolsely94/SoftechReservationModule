"""
apps/pic_analytics/queries/retention.py — the «الولاء والتكرار» tab (doc 33 §4/§6): A/B/C frequency
classes, loyal and overdue PICs, retention against the previous period and monthly cohorts.

The PIC population is the PICs with a visit (invoices > 0) in the period, read through f.facts(access).
Frequency / overdue / first-purchase labels are CHAIN-WIDE (owner decision, doc 33 §5); only amounts
(lifetime net) and the visits that make a cohort "come back" follow the user's branches.
Frequency itself comes from queries/frequency.py (PicRollup when end == yesterday, else computed).
"""
from collections import defaultdict
from datetime import date
from decimal import Decimal

from django.db.models import Sum
from django.db.models.functions import TruncMonth

from apps.customers import access as cust_access
from apps.customers.models import Customer
from apps.pic_analytics import rules
from apps.pic_analytics.models import PicDayFact
from apps.pic_analytics.queries.filters import FilterError
from apps.pic_analytics.queries.frequency import pic_frequency
from apps.pic_analytics.queries.overview import previous_period, retention_pct_for, visitor_set
from apps.pic_analytics.settings import setting

ZERO = Decimal('0')
BUCKETS = ('m1', 'm2', 'm3', 'm4_6', 'm7_12', 'y1plus', '')
MAX_PAGE_SIZE = 200


def _overdue_map(f, access):
    """({pic: freq}, [overdue pic]) for the PICs visiting in the period; measured at f.end."""
    freq = pic_frequency(visitor_set(f, access), f.end)
    factor = float(setting('pic_overdue_factor'))
    overdue = [p for p, v in freq.items()
               if v['last_visit'] and rules.is_overdue(v['last_visit'], v['cycle_days'], f.end, factor)]
    return freq, overdue


def frequency(f, access) -> dict:
    freq, overdue = _overdue_map(f, access)
    a, b = {k: 0 for k in range(1, 13)}, {k: 0 for k in range(1, 13)}
    c = {k: 0 for k in BUCKETS}
    loyal_from = int(setting('pic_loyal_months'))
    loyal = 0
    for v in freq.values():
        if v['months_a'] in a:
            a[v['months_a']] += 1
        if v['streak_b'] in b:
            b[v['streak_b']] += 1
        c[v['cycle_bucket'] if v['cycle_bucket'] in c else ''] += 1
        if v['months_a'] >= loyal_from:
            loyal += 1
    return {'a': a, 'b': b, 'c': c, 'loyal': loyal, 'overdue': len(overdue)}


def _int_param(value, label, lo, hi=None):
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise FilterError(f'«{label}» غير صالح')
    if n < lo or (hi is not None and n > hi):
        raise FilterError(f'«{label}» غير صالح')
    return n


def overdue_list(f, access, page=1, page_size=50) -> dict:
    """PICs that visited in the period but are overdue at f.end, biggest lifetime net first."""
    page = _int_param(page, 'الصفحة', 1)
    page_size = _int_param(page_size, 'حجم الصفحة', 1, MAX_PAGE_SIZE)
    freq, overdue = _overdue_map(f, access)
    net = {r['pic']: r['s'] or ZERO for r in access.scope_facts(
        PicDayFact.objects.filter(pic__in=overdue, day__lte=f.end)).values('pic').annotate(s=Sum('net'))}
    overdue.sort(key=lambda p: (-net.get(p, ZERO), p))
    chunk = overdue[(page - 1) * page_size: page * page_size]
    customers = {}
    for c in Customer.objects.filter(softech_pic__in=chunk).order_by('-pk'):
        customers[c.softech_pic] = c            # lowest pk wins (iterated last)
    user = getattr(access.profile, 'user', None)
    factor = float(setting('pic_overdue_factor'))
    rows = []
    for pic in chunk:
        v, cust = freq[pic], customers.get(pic)
        since = (f.end - v['last_visit']).days
        row = {'pic': pic, 'name': cust.name if cust else '', 'phone': cust.phone if cust else '',
               'last_visit': v['last_visit'], 'cycle_days': round(v['cycle_days'], 2),
               'days_overdue': round(since - factor * v['cycle_days']), 'lifetime_net': net.get(pic, ZERO)}
        visible = bool(cust and user is not None and cust_access.phones_visible(user, cust))
        cust_access.mask_fields(row, ['phone'], visible)
        rows.append(row)
    return {'count': len(overdue), 'rows': rows}


def retention_summary(f, access) -> dict:
    current = visitor_set(f, access)
    return {'retention_pct': retention_pct_for(f, access, current), 'prev_period': previous_period(f)}


def _month_index(d):
    return d.year * 12 + d.month - 1


def cohorts(f, access) -> list:
    """Last 12 cohorts (month of a PIC's first-ever purchase) ending at f.end's month; for each, the
    % of the cohort with a visit k = 1..12 months later, up to f.end's month (later months omitted)."""
    last = _month_index(f.end)
    first = last - 11
    start = date(first // 12, first % 12 + 1, 1)
    # first sale day of each PIC (chain-wide flag); a branch manager keeps those first seen at their branches
    firsts = access.scope_facts(PicDayFact.objects.filter(
        is_first_purchase=True, invoices__gt=0, day__gte=start, day__lte=f.end).exclude(pic=''))
    cohort_of = {}
    for pic, day in firsts.values_list('pic', 'day').distinct():
        cohort_of[pic] = _month_index(day)
    members = defaultdict(set)
    for pic, m in cohort_of.items():
        members[m].add(pic)
    visited = defaultdict(set)        # month index -> pics with a visit that month
    if cohort_of:
        for pic, m in (f.facts(access, pic_filters=False, start=start).filter(invoices__gt=0, pic__in=list(cohort_of))
                       .annotate(mo=TruncMonth('day')).values_list('pic', 'mo').distinct()):
            visited[_month_index(m)].add(pic)
    out = []
    for m in range(first, last + 1):
        size = len(members[m])
        pcts = []
        for k in range(1, 13):
            if m + k > last:
                break
            pcts.append(round(len(members[m] & visited[m + k]) / size * 100, 2) if size else 0.0)
        out.append({'cohort': f'{m // 12:04d}-{m % 12 + 1:02d}', 'size': size, 'months': pcts})
    return out
