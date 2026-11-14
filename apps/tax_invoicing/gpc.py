"""
apps/tax_invoicing/gpc.py — the GPC bricks EGS codes are registered under, and a suggested brick per item.

The brick list comes from the owner's GPC workbook (`manage.py load_gpc_bricks <file>`). Once loaded, a
code request must name a brick from it. The suggestion is learned from our own approved codes: the brick
most used by approved items of the same SOFTECH family, else the same category, else the same type
(Medicine / Cosmetics / …). It is only shown; a person picks the brick for every request.
"""
import re
from collections import Counter, defaultdict

import openpyxl
from django.db import transaction
from django.db.models import Q

from .models import TaxGpcBrick, TaxItemProfile

BRICK = re.compile(r'^\d{8}$')
SEARCH_LIMIT = 30


def _text(value):
    if value is None:
        return ''
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip()


def read_workbook(path, sheet=None):
    """[(code, name_en, name_ar)] from a sheet whose header row (within its first 10 rows) names a brick code
    column. Takes "Brick Code / Brick Description / Brick Name Arabic" and "BrickCode / BrickTitleAr / BrickTitle"."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        return _read_bricks([wb[sheet]] if sheet else wb.worksheets)
    finally:
        wb.close()


def _read_bricks(sheets):
    for ws in sheets:
        rows = ws.iter_rows(values_only=True)
        for _ in range(10):
            header = next(rows, None)
            if header is None:
                break
            names = [_text(h).lower().replace(' ', '') for h in header]
            if 'brickcode' not in names:
                continue
            code_i = names.index('brickcode')
            ar_i = next((i for i, n in enumerate(names) if n in ('bricknamearabic', 'bricktitlear')), None)
            en_i = next((i for i, n in enumerate(names) if n in ('brickdescription', 'bricktitle')), None)
            out = []
            for r in rows:
                code = _text(r[code_i]) if code_i < len(r) else ''
                if BRICK.match(code):
                    out.append((code, _text(r[en_i]) if en_i is not None else '', _text(r[ar_i]) if ar_i is not None else ''))
            return out
    raise ValueError('لا توجد ورقة فيها عمود Brick Code')


def load(rows):
    """Insert or update bricks; never deletes. The first name seen for a code wins over blanks."""
    merged = {}
    for code, en, ar in rows:
        old = merged.get(code, ('', ''))
        merged[code] = (old[0] or en, old[1] or ar)
    existing = {b.code: b for b in TaxGpcBrick.objects.all()}
    created = updated = 0
    with transaction.atomic():
        new = []
        for code, (en, ar) in merged.items():
            b = existing.get(code)
            if b is None:
                new.append(TaxGpcBrick(code=code, name_en=en[:300], name_ar=ar[:300]))
                created += 1
            elif (en and en != b.name_en) or (ar and ar != b.name_ar):
                b.name_en, b.name_ar = en[:300] or b.name_en, ar[:300] or b.name_ar
                b.save()
                updated += 1
        TaxGpcBrick.objects.bulk_create(new, batch_size=2000)
    return {'read': len(merged), 'created': created, 'updated': updated}


def loaded():
    return TaxGpcBrick.objects.exists()


def known(code):
    """True when the list is not loaded yet (nothing to check against) or holds this brick."""
    return not loaded() or TaxGpcBrick.objects.filter(code=code).exists()


def names(codes):
    return {b.code: b.name_ar or b.name_en for b in TaxGpcBrick.objects.filter(code__in=[c for c in codes if c])}


def _usage():
    """How often each brick is used by approved items, per family, category and type."""
    by = {'family': defaultdict(Counter), 'category': defaultdict(Counter), 'type': defaultdict(Counter)}
    rows = (TaxItemProfile.objects.filter(coding_status=TaxItemProfile.CODE_APPROVED, item__isnull=False)
            .exclude(gpc_code__in=['', '0'])
            .values_list('gpc_code', 'item__family_name', 'item__category__name', 'item__medicine_type_name'))
    for brick, family, category, kind in rows:
        if family:
            by['family'][family][brick] += 1
        if category:
            by['category'][category][brick] += 1
        if kind:
            by['type'][kind][brick] += 1
    return by


def suggest(profiles):
    """{profile_id: {'code', 'name', 'basis', 'share'}} for profiles linked to a catalog item."""
    profiles = list(profiles)
    if not profiles:
        return {}
    usage = _usage()
    out = {}
    for p in profiles:
        item = p.item
        if item is None:
            continue
        for basis, key in (('family', item.family_name), ('category', item.category.name if item.category_id else ''),
                           ('type', item.medicine_type_name)):
            counts = usage[basis].get(key) if key else None
            if counts:
                code, n = counts.most_common(1)[0]
                out[p.id] = {'code': code, 'basis': basis, 'basis_value': key, 'share': round(100 * n / sum(counts.values()))}
                break
    labels = names({s['code'] for s in out.values()})
    for s in out.values():
        s['name'] = labels.get(s['code'], '')
    return out


def search(q, limit=SEARCH_LIMIT):
    """Bricks by code prefix or name (Arabic or English), the ones our approved items use first."""
    q = (q or '').strip()
    qs = TaxGpcBrick.objects.all()
    if q:
        qs = qs.filter(Q(code__startswith=q) | Q(name_en__icontains=q) | Q(name_ar__icontains=q))
    used = Counter(TaxItemProfile.objects.filter(coding_status=TaxItemProfile.CODE_APPROVED)
                   .exclude(gpc_code__in=['', '0']).values_list('gpc_code', flat=True))
    rows = list(qs[:500])
    rows.sort(key=lambda b: (-used.get(b.code, 0), b.code))
    return [{'code': b.code, 'name_en': b.name_en, 'name_ar': b.name_ar, 'used': used.get(b.code, 0)} for b in rows[:limit]]
