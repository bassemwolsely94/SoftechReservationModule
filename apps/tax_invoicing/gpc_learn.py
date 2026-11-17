"""
apps/tax_invoicing/gpc_learn.py — the GPC brick we can suggest for an item from what is already known, no AI.

Sources, first hit wins:
1. decisions — bricks people confirmed on coding decisions for items of the same SOFTECH family;
2. eta — bricks of codes ETA's production system approved for items of the same family;
3. sheet — the item's own brick from the owner's sheet (TaxItemProfile.gpc_code, see `load_sheet_bricks`);
4. medicine — a medicine with nothing better gets the medicines brick.
A family source counts only with at least MIN_ITEMS items and the top brick on at least MIN_SHARE of them, so a
mixed family gives nothing and the next source is tried. A suggestion is only shown; a person confirms the brick.
The query count does not grow with the number of profiles.
"""
from collections import Counter, defaultdict

from django.db.models import F, OuterRef, Subquery

from apps.catalog.models import Item

from .gpc import BRICK
from .models import EtaCodeUsage, TaxCodingDecision

MIN_ITEMS = 3
MIN_SHARE = 0.8
MEDICINE_BRICK = '10005845'


def _top(counts):
    """(brick, share, n) when the family is settled enough, else None."""
    n = sum(counts.values())
    if n < MIN_ITEMS:
        return None
    brick, top = counts.most_common(1)[0]
    share = round(top / n, 4)
    return (brick, share, n) if share >= MIN_SHARE else None


def _decision_counts(families):
    by = defaultdict(Counter)
    rows = (TaxCodingDecision.objects
            .filter(decision=TaxCodingDecision.DECISION_CODE, profile__item__family_name__in=families)
            .exclude(brick='').values_list('profile__item__family_name', 'brick'))
    for family, brick in rows:
        if BRICK.match(brick):
            by[family][brick] += 1
    return by


def _eta_counts(families):
    family = Item.objects.filter(softech_id=OuterRef('itemcode')).values('family_name')[:1]
    rows = (EtaCodeUsage.objects.filter(system='production', status__iregex=r'^(approved|active)$')
            .exclude(gpc='').exclude(itemcode='')
            .filter(itemcode__in=Item.objects.filter(family_name__in=families).values('softech_id'))
            .annotate(family=Subquery(family))
            .order_by('itemcode', F('active_from').desc(nulls_last=True))
            .values_list('family', 'itemcode', 'gpc'))
    by = defaultdict(Counter)
    seen = set()
    for fam, itemcode, brick in rows:    # one vote per item, its newest approved code
        if fam and BRICK.match(brick) and itemcode not in seen:
            seen.add(itemcode)
            by[fam][brick] += 1
    return by


def learned(profiles):
    """{profile_id: {'code', 'source', 'share', 'n', 'basis'}} for the profiles that have a learned brick."""
    profiles = list(profiles)
    if not profiles:
        return {}
    item_ids = {p.item_id for p in profiles if p.item_id}
    items = {i['pk']: i for i in Item.objects.filter(pk__in=item_ids)
             .values('pk', 'family_name', 'medicine_type_name')} if item_ids else {}
    families = sorted({i['family_name'] for i in items.values() if i['family_name']})
    by_decision = _decision_counts(families) if families else {}
    by_eta = _eta_counts(families) if families else {}
    tops = {'decisions': {f: _top(c) for f, c in by_decision.items()},
            'eta': {f: _top(c) for f, c in by_eta.items()}}

    out = {}
    for p in profiles:
        item = items.get(p.item_id) or {}
        family = item.get('family_name') or ''
        hit = None
        for source in ('decisions', 'eta'):
            top = tops[source].get(family) if family else None
            if top:
                brick, share, n = top
                hit = {'code': brick, 'source': source, 'share': share, 'n': n, 'basis': f'العائلة {family}'}
                break
        if hit is None and BRICK.match(p.gpc_code or ''):
            hit = {'code': p.gpc_code, 'source': 'sheet', 'share': 1.0, 'n': 1, 'basis': 'ملف الأكواد'}
        if hit is None and item.get('medicine_type_name') == 'Medicine':
            hit = {'code': MEDICINE_BRICK, 'source': 'medicine', 'share': 1.0, 'n': 0, 'basis': 'دواء'}
        if hit:
            out[p.pk] = hit
    return out
