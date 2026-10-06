"""
apps/offers/targeting.py — Odoo-style flexible product selector for offers.

Pick items by ANY whitelisted items-master field (producer / supplier / internal
classification / category / origin / shape / effect / unit / level / insurance),
boolean flags (fridge / fast-moving / imported / …), and numeric ranges
(pack_price / unit_price / item_level), combined AND/OR — plus manual include /
exclude lists and an overridable stock-availability gate.

Two consistent evaluators:
  • build_target_q(spec)     — Django Q for DB resolution + the config preview.
  • item_matches_spec(spec, item) — pure-Python, used by the engine per basket line.

WHITELIST ONLY: an unknown field is ignored (never interpolated into a query),
so a saved spec can't reach arbitrary columns.
"""
from django.db.models import Q, Sum

# public field key → (model field, type). Arabic UI labels map onto these:
#   شركة منتجة = producer, المورد الرئيسى = supplier, التصنيف الداخلى = store_classif / medicine_type
FIELDS = {
    'producer_code':  ('producer_code',  'str'),
    'producer_name':  ('producer_name',  'str'),
    'supplier_code':  ('supplier_code',  'str'),
    'supplier_name':  ('supplier_name',  'str'),
    'name':           ('name',           'str'),   # item name (اسم الصنف)
    'name_scientific':('name_scientific','str'),   # scientific name
    'family_code':    ('family_code',    'str'),
    'family_name':    ('family_name',    'str'),
    'medicine_type':      ('medicine_type',      'str'),  # التصنيف العام (code)
    'medicine_type_name': ('medicine_type_name', 'str'),  # التصنيف العام (name)
    'store_classif':  ('store_classif',  'str'),
    'origin_code':    ('origin_code',    'str'),
    'origin_name':    ('origin_name',    'str'),
    'shape_code':     ('shape_code',     'str'),
    'shape_name':     ('shape_name',     'str'),
    'effect_code':    ('effect_code',    'str'),
    'unit_code':      ('unit_code',      'str'),
    'unit_name':      ('unit_name',      'str'),
    'insurance_type': ('insurance_type', 'str'),
    'category':       ('category_id',    'num'),
    'item_level':     ('item_level',     'num'),
    'pack_price':     ('pack_price',     'num'),
    'unit_price':     ('unit_price',     'num'),
    'requires_fridge':('requires_fridge','bool'),
    'is_fast_moving': ('is_fast_moving', 'bool'),
    'is_imported':    ('is_imported',    'bool'),
    'no_more_use':    ('no_more_use',    'bool'),
    'item_archive':   ('item_archive',   'bool'),
    'is_stockable':   ('is_stockable',   'bool'),
    'in_shortage':    ('in_shortage',    'bool'),
}

# operator → Django lookup builder
_LOOKUP = {
    'eq':       lambda f, v: Q(**{f: v}),
    'ne':       lambda f, v: ~Q(**{f: v}),
    'in':       lambda f, v: Q(**{f + '__in': v}),           # يتضمن (multi)
    'not_in':   lambda f, v: ~Q(**{f + '__in': v}),          # لا يتضمن (multi)
    'contains': lambda f, v: Q(**{f + '__icontains': v}),    # يحتوي
    'gte':      lambda f, v: Q(**{f + '__gte': v}),
    'lte':      lambda f, v: Q(**{f + '__lte': v}),
    'range':    lambda f, v: Q(**{f + '__range': v}),
    'is_true':  lambda f, v: Q(**{f: True}),
    'is_false': lambda f, v: Q(**{f: False}),
}


def build_target_q(spec):
    """spec → Django Q (empty Q ⇒ match nothing). AND (match=all) / OR (match=any)."""
    rules = (spec or {}).get('rules') or []
    if not rules:
        return None
    match_all = (spec.get('match', 'all') != 'any')
    combined = None
    for r in rules:
        mapping = FIELDS.get(r.get('field'))
        op = r.get('op')
        if not mapping or op not in _LOOKUP:
            continue
        mf, _typ = mapping
        q = _LOOKUP[op](mf, r.get('value'))
        if combined is None:
            combined = q
        else:
            combined = (combined & q) if match_all else (combined | q)
    return combined


# ── Python evaluator (engine per-line) ───────────────────────────────────────────
def item_matches_spec(spec, item):
    rules = (spec or {}).get('rules') or []
    if not rules:
        return False
    match_all = (spec.get('match', 'all') != 'any')
    results = []
    for r in rules:
        mapping = FIELDS.get(r.get('field'))
        if not mapping:
            results.append(False)
            continue
        mf, typ = mapping
        results.append(_py_op(r.get('op'), getattr(item, mf, None), r.get('value'), typ))
    return all(results) if match_all else any(results)


def _py_op(op, actual, val, typ):
    if op == 'is_true':
        return bool(actual) is True
    if op == 'is_false':
        return bool(actual) is False
    if actual is None:
        return False
    if typ in ('num',):
        try:
            a = float(actual)
        except (TypeError, ValueError):
            return False
        if op == 'eq':     return a == _f(val)
        if op == 'ne':     return a != _f(val)
        if op == 'in':     return a in [_f(x) for x in (val or [])]
        if op == 'not_in': return a not in [_f(x) for x in (val or [])]
        if op == 'gte':    return a >= _f(val)
        if op == 'lte':    return a <= _f(val)
        if op == 'range':  return _f(val[0]) <= a <= _f(val[1])
        return False
    s = str(actual)
    if op == 'eq':       return s == str(val)
    if op == 'ne':       return s != str(val)
    if op == 'in':       return s in [str(x) for x in (val or [])]
    if op == 'not_in':   return s not in [str(x) for x in (val or [])]
    if op == 'contains': return str(val).lower() in s.lower()
    return False


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return float('nan')


def classification_match(filters, item):
    """Legacy classification_filters {field: [values]} → Python bool (OR)."""
    for field, values in (filters or {}).items():
        if values and str(getattr(item, field, '') or '') in {str(v) for v in values}:
            return True
    return False


# ── DB resolution (config preview + Channel-A posdiscp targeting) ─────────────────
def resolve_offer_items(offer, *, branch_id=None, only_ids=False):
    """
    Resolve the concrete Item queryset an offer targets: (spec ∪ manual-includes ∪
    categories ∪ tags ∪ classification) − manual-excludes, then the stock gate.
    """
    from apps.catalog.models import Item, ItemStock, EXCLUDED_STORE_CODES

    if offer.target_all:
        qs = Item.objects.all()
    else:
        q = None
        spec_q = build_target_q(offer.target_spec)
        if spec_q is not None:
            q = spec_q
        inc = list(offer.items.values_list('id', flat=True))
        if inc:
            q = (q | Q(id__in=inc)) if q is not None else Q(id__in=inc)
        cats = list(offer.categories.values_list('id', flat=True))
        if cats:
            q = (q | Q(category_id__in=cats)) if q is not None else Q(category_id__in=cats)
        tags = list(offer.tags.values_list('id', flat=True))
        if tags:
            q = (q | Q(tags__in=tags)) if q is not None else Q(tags__in=tags)
        for field, values in (offer.classification_filters or {}).items():
            if values:
                cq = Q(**{f'{field}__in': [str(v) for v in values]})
                q = (q | cq) if q is not None else cq
        qs = Item.objects.filter(q).distinct() if q is not None else Item.objects.none()

    excl = list(offer.excluded_items.values_list('id', flat=True))
    if excl:
        qs = qs.exclude(id__in=excl)

    if offer.require_stock and branch_id:
        in_stock = (ItemStock.objects
                    .filter(branch_id=branch_id)
                    .exclude(softech_store_code__in=EXCLUDED_STORE_CODES)
                    .values('item_id').annotate(q=Sum('quantity_on_hand'))
                    .filter(q__gt=0).values_list('item_id', flat=True))
        qs = qs.filter(id__in=in_stock)

    return qs.values_list('id', flat=True) if only_ids else qs


def preview_items(*, target_all=False, target_spec=None, include_ids=None, category_ids=None,
                  tag_ids=None, classification_filters=None, exclude_ids=None,
                  require_stock=False, branch_id=None):
    """
    Resolve an Item queryset from RAW selector params (unsaved offer) — powers the
    config-UI preview so the admin sees exactly which products they selected.
    """
    from apps.catalog.models import Item, ItemStock, EXCLUDED_STORE_CODES

    if target_all:
        qs = Item.objects.all()
    else:
        q = build_target_q(target_spec)
        if include_ids:
            q = (q | Q(id__in=include_ids)) if q is not None else Q(id__in=include_ids)
        if category_ids:
            cq = Q(category_id__in=category_ids)
            q = (q | cq) if q is not None else cq
        if tag_ids:
            tq = Q(tags__in=tag_ids)
            q = (q | tq) if q is not None else tq
        for field, values in (classification_filters or {}).items():
            if values and field in {m[0] for m in FIELDS.values()}:
                cq = Q(**{f'{field}__in': [str(v) for v in values]})
                q = (q | cq) if q is not None else cq
        qs = Item.objects.filter(q).distinct() if q is not None else Item.objects.none()

    if exclude_ids:
        qs = qs.exclude(id__in=exclude_ids)
    if require_stock and branch_id:
        in_stock = (ItemStock.objects.filter(branch_id=branch_id)
                    .exclude(softech_store_code__in=EXCLUDED_STORE_CODES)
                    .values('item_id').annotate(q=Sum('quantity_on_hand'))
                    .filter(q__gt=0).values_list('item_id', flat=True))
        qs = qs.filter(id__in=in_stock)
    return qs
