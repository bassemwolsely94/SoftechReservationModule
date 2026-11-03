"""
apps/pic_analytics/queries/groups.py — Branches / Salespeople / Channels / Categories tabs (doc 33 §4/§6).

Reads PicDayFact (through f.facts(access)), Customer and the label tables only. Every function returns
{'rows': [...], 'total': {... key 'all' ...}}. The 'all' row is computed over the whole scoped set, NOT as
the sum of the rows: a PIC (or a same-day visit at two branches) counts once in 'all' and once per group.
New / returning / reactivated labels are CHAIN-WIDE and come from overview.classify_visitors; a NEW PIC
counts as new ONLY in the group of its first fact row in the period (earliest day, then lowest branch id,
salesperson, channel); in its other groups it is not counted as new (it still counts in pics and visits).
Returning / reactivated PICs count in every group they visited ("returning" includes reactivated).
"""
from decimal import Decimal

from django.db.models import Count, Q, Sum

from apps.pic_analytics.queries.overview import ZERO, classify_visitors

CHANNEL_LABELS = {
    'cash': 'نقدي', 'delivery': 'توصيل', 'regular': 'عادي', 'credit': 'آجل', 'insurance': 'تأمين',
    'exclude': 'مستبعدة من مؤشرات KPI', 'other': 'أخرى', '': 'غير محدد',
}
UNCATEGORISED = 'غير مصنف'


def _qs(f, access):
    return f.facts(access).exclude(pic='')


def _row(key, label, pic_stats, labels, new_pics, access, f):
    """pic_stats: {pic: (net, gp, units, visits)} for one group; gp = KPI-board gross profit."""
    visitors = [p for p, s in pic_stats.items() if s[3] > 0]
    visits = sum(s[3] for s in pic_stats.values() if s[3] > 0)
    net = sum((s[0] for s in pic_stats.values()), ZERO)
    units = sum((s[2] for s in pic_stats.values()), ZERO)
    row = {
        'key': key, 'label': label, 'distinct_pics': len(visitors),
        'new': sum(1 for p in visitors if p in new_pics),
        'returning': sum(1 for p in visitors if labels.get(p) in ('returning', 'reactivated')),
        'reactivated': sum(1 for p in visitors if labels.get(p) == 'reactivated'),
        'visits': visits, 'net': net,
        'basket_net': round(net / visits, 2) if visits else None,
        'units_per_visit': round(units / visits, 2) if visits and not f.category else None,
    }
    if access.sees_cost:
        row['gp'] = None if f.category else sum((s[1] for s in pic_stats.values()), ZERO)
    return row


def _aggregate(qs, *group_fields):
    return qs.values(*group_fields, 'pic').annotate(
        s_net=Sum('enet'), s_gp=Sum('gp'), s_units=Sum('units'),
        s_vis=Count('day', distinct=True, filter=Q(invoices__gt=0)))


def _pic_stats(qs, group_field):
    """{group_key: {pic: (net, gp, units, visits)}} — visits = distinct days with invoices > 0."""
    out = {}
    for r in _aggregate(qs, group_field):
        out.setdefault(r[group_field], {})[r['pic']] = (
            r['s_net'] or ZERO, r['s_gp'] or ZERO, r['s_units'] or ZERO, r['s_vis'])
    return out


def _pic_stats_all(qs):
    return {r['pic']: (r['s_net'] or ZERO, r['s_gp'] or ZERO, r['s_units'] or ZERO, r['s_vis'])
            for r in _aggregate(qs)}


def _first_rows(qs, new_pics):
    """{pic: (branch_id, salesperson, channel_bucket)} of each NEW pic's first visit row in the period."""
    first = {}
    rows = (qs.filter(pic__in=new_pics, invoices__gt=0)
            .order_by('day', 'branch_id', 'salesperson', 'channel_bucket')
            .values_list('pic', 'branch_id', 'salesperson', 'channel_bucket'))
    for pic, b, s, c in rows:
        first.setdefault(pic, (b, s, c))
    return first


def _grouped(f, access, field, label_of, first_index):
    qs = _qs(f, access)
    labels = classify_visitors(f, access)
    new_pics = {p for p, c in labels.items() if c == 'new'}
    first = _first_rows(qs, new_pics) if new_pics else {}
    rows = []
    for key, pics in _pic_stats(qs, field).items():
        owned = {p for p in new_pics if p in first and first[p][first_index] == key}
        rows.append(_row(key, label_of(key), pics, labels, owned, access, f))
    rows.sort(key=lambda r: r['net'], reverse=True)
    return {'rows': rows, 'total': _row('all', 'الإجمالي', _pic_stats_all(qs), labels, new_pics, access, f)}


def by_branch(f, access) -> dict:
    from apps.branches.models import Branch
    names = {b.pk: f'{b.softech_branch_id} · {b.name_ar or b.name}' for b in Branch.objects.all()}
    return _grouped(f, access, 'branch_id', lambda k: names.get(k, 'بدون فرع' if k is None else str(k)), 0)


def salesperson_labeler():
    """code -> display name (shared with the filter options)."""
    from apps.analytics.views import _build_user_map, _user_name
    umap = _build_user_map()
    return lambda k: _user_name(umap, k) if k else 'غير محدد'


def by_salesperson(f, access) -> dict:
    return _grouped(f, access, 'salesperson', salesperson_labeler(), 1)


def by_channel(f, access) -> dict:
    return _grouped(f, access, 'channel_bucket', lambda k: CHANNEL_LABELS.get(k, k), 2)


def category_names(codes) -> dict:
    """{category code: Arabic (else English) name} from the catalog; shared with the filter options."""
    from apps.catalog.models import Item
    names = {}
    for code, ar, en in (Item.objects.filter(medicine_type__in=list(codes))
                         .values_list('medicine_type', 'medicine_type_name_ar', 'medicine_type_name').distinct()):
        if ar or en:
            names.setdefault(code, ar or en)
    return names


def category_label(code, names):
    return UNCATEGORISED if code in ('', '00') else (names.get(code) or code)


def by_category(f, access) -> dict:
    qs = _qs(f, access)
    labels = classify_visitors(f, access)
    new_pics = {p for p, c in labels.items() if c == 'new'}

    # merge every row of a pic-day; a category counts for that visit only where its net > 0
    merged = {}
    for pic, day, inv, cats in qs.values_list('pic', 'day', 'invoices', 'net_by_category'):
        m = merged.setdefault((pic, day), [0, {}])
        m[0] += inv
        for c, v in (cats or {}).items():
            m[1][c] = m[1].get(c, ZERO) + Decimal(str(v))
    visit_cats = {k: {c for c, v in m[1].items() if v > 0} for k, m in merged.items() if m[0] > 0}

    # a new PIC is attributed to the category with the largest positive net on its first visit day
    first_day = {}
    for pic, day in visit_cats:
        if pic in new_pics and (pic not in first_day or day < first_day[pic]):
            first_day[pic] = day
    new_cat = {}
    for pic, day in first_day.items():
        cats = {c: v for c, v in merged[(pic, day)][1].items() if v > 0}
        if cats:
            new_cat[pic] = sorted(cats.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]

    per_cat = {}          # code -> {'net': Decimal, 'pics': set, 'visits': int}
    for (pic, day), m in merged.items():
        for c, v in m[1].items():
            per_cat.setdefault(c, {'net': ZERO, 'pics': set(), 'visits': 0})['net'] += v
        for c in visit_cats.get((pic, day), ()):
            per_cat[c]['pics'].add(pic)
            per_cat[c]['visits'] += 1

    names = category_names(list(per_cat))

    rows = []
    for code, b in per_cat.items():
        pics = b['pics']
        row = {
            'key': code, 'label': category_label(code, names),
            'distinct_pics': len(pics),
            'new': sum(1 for p in pics if new_cat.get(p) == code),
            'returning': sum(1 for p in pics if labels.get(p) in ('returning', 'reactivated')),
            'reactivated': sum(1 for p in pics if labels.get(p) == 'reactivated'),
            'visits': b['visits'], 'net': b['net'],
            'basket_net': round(b['net'] / b['visits'], 2) if b['visits'] else None,
            'units_per_visit': None,
        }
        if access.sees_cost:
            row['gp'] = None      # gp is per whole fact row, never split by category
        rows.append(row)
    rows.sort(key=lambda r: r['net'], reverse=True)

    multi = sum(1 for cs in visit_cats.values() if len(cs) >= 2)
    return {'rows': rows,
            'total': _row('all', 'الإجمالي', _pic_stats_all(qs), labels, new_pics, access, f),
            'cross_category_rate': round(multi / len(visit_cats), 4) if visit_cats else None}
