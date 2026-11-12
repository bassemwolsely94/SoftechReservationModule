"""
«أصناف المطالبة» Excel: the whole items table of one motalba, or of several motalbas
(sheet «مجمع» = one row per item summed across them, sheet «تفصيلى» = item × motalba).
Rows come from discrepancy.claim_items_for_revision — the same numbers as the tab.
"""
import io
from decimal import Decimal

from django.http import HttpResponse
from openpyxl import Workbook
from core.export_safety import neutralise_formulas

from .discrepancy import claim_items_for_revision
from .portfolio_export import _sheet

_ITEM_COLS = [
    ('item_code', 'الكود', 10, 'text'), ('item_name', 'الصنف', 40, 'text'),
    ('origin', 'المنشأ', 16, 'text'), ('contract_classif', 'تصنيف التعاقدات', 18, 'text'),
    ('basic_discount_txt', 'خصم أساسى', 9, 'text'), ('category_label', 'التصنيف', 11, 'text'),
    ('line_count', 'عدد بنود الصرف', 9, 'int'), ('total_qty', 'الكمية', 10, 'money'),
    ('gross', 'الإجمالى', 14, 'money'), ('discount_pct', 'نسبة الخصم', 9, 'pct'),
    ('discount', 'قيمة الخصم', 13, 'money'), ('net', 'الصافى', 14, 'money'),
]


def _prep(it):
    it = dict(it)
    it['basic_discount_txt'] = f"{it['basic_discount']}%" if it.get('basic_discount') is not None else ''
    if it.get('is_mixed'):
        it['category_label'] = ' / '.join(f"{c['label']} ×{c['count']}" for c in it.get('categories') or [])
    return it


def combine(per_claim):
    """[(claim, items)] → one row per item code summed across the claims."""
    agg = {}
    for claim, items in per_claim:
        for it in items:
            a = agg.get(it['item_code'])
            if a is None:
                a = agg[it['item_code']] = dict(
                    it, line_count=0, total_qty=Decimal('0'), gross=Decimal('0'), discount=Decimal('0'),
                    net=Decimal('0'), motalbas=set(), cats={})
            a['line_count'] += it['line_count']
            for k in ('total_qty', 'gross', 'discount', 'net'):
                a[k] += Decimal(str(it[k] or 0))
            a['motalbas'].add(claim.pk)
            for c in it.get('categories') or []:
                a['cats'][c['category']] = (c['label'], a['cats'].get(c['category'], (c['label'], 0))[1] + c['count'])
    rows = []
    for a in agg.values():
        cats = a.pop('cats')
        a['motalba_count'] = len(a.pop('motalbas'))
        a['is_mixed'] = len(cats) > 1
        a['categories'] = [{'category': k, 'label': lbl, 'count': n} for k, (lbl, n) in sorted(cats.items())]
        if not a['is_mixed'] and cats:
            a['category_label'] = next(iter(cats.values()))[0]
        a['discount_pct'] = round(float(a['discount'] / a['gross'] * 100), 2) if a['gross'] else 0.0
        for k in ('total_qty', 'gross', 'discount', 'net'):
            a[k] = float(a[k])
        rows.append(a)
    rows.sort(key=lambda r: r['gross'], reverse=True)
    return rows


def _seq(rows):
    for i, r in enumerate(rows, start=1):
        r['seq'] = i
    return rows


def generate_items_excel(claims, *, filename='claim_items.xlsx'):
    claims = list(claims)
    per_claim = [(c, claim_items_for_revision(c)['items']) for c in claims]
    wb = Workbook()
    seq = [('seq', 'م', 5, 'int')]
    if len(claims) == 1:
        c = claims[0]
        rows = _seq([_prep(it) for it in per_claim[0][1]])
        _sheet(wb, 'أصناف المطالبة', seq + _ITEM_COLS, rows, first=True,
               note=f'أصناف المطالبة {c.claim_number} — {c.subclient} — {c.period_from} ← {c.period_to}')
    else:
        rows = _seq([_prep(it) for it in combine(per_claim)])
        cols = seq + _ITEM_COLS[:6] + [('motalba_count', 'عدد المطالبات', 9, 'int')] + _ITEM_COLS[6:]
        _sheet(wb, 'مجمع', cols, rows, first=True,
               note=f'أصناف {len(claims)} مطالبة: ' + '، '.join(c.claim_number for c in claims)[:240])
        detail = []
        for c, items in per_claim:
            for it in items:
                detail.append(dict(_prep(it), claim_number=c.claim_number,
                                   client=c.subclient.client.name if c.subclient_id else '',
                                   subclient=c.subclient.name if c.subclient_id else '',
                                   period=f'{c.period_from or ""} ← {c.period_to or ""}'))
        _sheet(wb, 'تفصيلى', seq + [
            ('claim_number', 'المطالبة', 15, 'text'), ('client', 'الجهة', 28, 'text'),
            ('subclient', 'الفئة', 14, 'text'), ('period', 'الفترة', 24, 'text'),
        ] + _ITEM_COLS, _seq(detail), group='claim_number')
    buf = io.BytesIO()
    neutralise_formulas(wb).save(buf)
    resp = HttpResponse(buf.getvalue(),
                        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    resp['Content-Disposition'] = f'attachment; filename="{filename}"'
    return resp
