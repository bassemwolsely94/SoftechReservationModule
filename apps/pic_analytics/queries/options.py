"""
apps/pic_analytics/queries/options.py — the values the filter bar offers (doc 33 §6).

Every list is limited to what the user may see: facts in the report period, scoped to the user's
branches (a branch manager's salespeople come only from their branches). The other filters are
ignored here so choosing one never empties the lists of the others. Labels reuse groups.py / calls.py.
"""
from dataclasses import replace

from django.db.models import CharField, F, Func

from apps.customers.models import Customer
from apps.pic_analytics.queries import groups
from apps.pic_analytics.queries.calls import agent_labels, calls_qs

FREQUENCY_LABELS = [
    ('m1', 'كل شهر أو أقل'), ('m2', 'كل شهرين'), ('m3', 'كل 3 شهور'),
    ('m4_6', 'كل 4–6 شهور'), ('m7_12', 'كل 7–12 شهر'), ('y1plus', 'سنة أو أكثر'),
]


def filter_options(f, access) -> dict:
    base = replace(f, salesperson='', channel_bucket='', category='', segment='', customer_type='',
                   frequency='', agent_ext='', q='', memo={})
    facts = base.facts(access, pic_filters=False)

    label_of = groups.salesperson_labeler()
    codes = sorted(set(facts.exclude(salesperson='').values_list('salesperson', flat=True).distinct()))
    salespeople = sorted(({'code': c, 'label': label_of(c)} for c in codes), key=lambda r: r['label'])

    keys = (facts.annotate(k=Func(F('net_by_category'), function='jsonb_object_keys', output_field=CharField()))
            .values_list('k', flat=True).distinct())
    cat_codes = set(keys)
    names = groups.category_names(cat_codes)
    categories = sorted(({'code': c, 'label': groups.category_label(c, names)} for c in cat_codes),
                        key=lambda r: r['label'])

    chans = set(facts.values_list('channel_bucket', flat=True).distinct())
    channels = [{'code': c, 'label': groups.CHANNEL_LABELS.get(c, c)} for c in sorted(chans) if c]

    pics = facts.exclude(pic='').values('pic').distinct()
    types = {}
    for code, label in (Customer.objects.filter(softech_pic__in=pics).exclude(softech_ptclassifcode='')
                        .values_list('softech_ptclassifcode', 'person_classif_label').distinct()):
        if not types.get(code):
            types[code] = label
    customer_types = [{'code': c, 'label': types[c] or c} for c in sorted(types)]

    out = {
        'salespeople': salespeople, 'categories': categories, 'channels': channels,
        'customer_types': customer_types,
        'segments': [{'code': k, 'label': v} for k, v in Customer.SEGMENT_CHOICES],
        'frequency': [{'code': k, 'label': v} for k, v in FREQUENCY_LABELS],
    }
    if access.sees_calls_tabs:
        exts = sorted(set(calls_qs(base).exclude(agent_ext='').values_list('agent_ext', flat=True).distinct()))
        labels = agent_labels(exts)
        out['agents'] = [{'ext': x, 'label': labels[x]} for x in exts]
    return out
