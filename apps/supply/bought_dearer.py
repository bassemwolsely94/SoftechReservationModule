"""
apps/supply/bought_dearer.py — «اشترينا أغلى»: the monthly report of purchase lines bought dearer while a
cheaper accredited supplier was available (C17, docs/full-project-audit/08_BUSINESS_OPTIMIZATION_OPPORTUNITIES.md).

Visibility only. The owner rejected splitting the order lists by winning supplier (memory
supplier_price_comparison), so this proposes nothing and orders nothing; it shows per buyer and per
supplier the EGP we paid above the cheapest RECENT supplier for the same item.

Same rules as «مقارنة أسعار الشراء» (price_history.py), reused, not re-written:
  • cost = (net value + VAT) ÷ (paid units + free units) — VAT-inclusive for every line, and the free
    units of a bonus purchase lower its cost (_line_discount). A pure free line (no paid units, or a
    ~100% discount) is never a purchase and never the price to beat;
  • fair across public-price changes: every line is a DISCOUNT % off the public price on its invoice;
  • who is compared: distributors / manufacturers / other head tiers (HEAD_TIERS); warehouses and the
    virtual / contract / clearing accounts are never a price to beat; one company = one column
    (SUPPLIER_GROUPS), so buying from a sister account is never "dearer";
  • "cheaper was available" = another company's discount on the same item within STALE_DAYS BEFORE (or
    on) the line's date beats it by more than BETTER_PCT points.

EGP above = (best discount − line discount) × the line's public price × (paid + free units).
Company-level (HQ purchasing), so only all-branch users see it. PostgreSQL only — no SOFTECH.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict
from datetime import timedelta

from .comparison import BETTER_PCT, TIER_LABELS, _f, _line_discount, _profiles
from .price_history import HEAD_TIERS, STALE_DAYS, _company, _company_tier


def month_bounds(month: dt.date):
    start = month.replace(day=1)
    end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    return start, end


def _buyer_names(codes) -> dict:
    from apps.procurement.models import BuyerPerformance
    out = {}
    for r in (BuyerPerformance.objects.filter(buyer_code__in=list(codes)).exclude(buyer_name='')
              .order_by('buyer_code', '-period_end').values('buyer_code', 'buyer_name')):
        out.setdefault(r['buyer_code'], r['buyer_name'])
    return out


def _branch_names() -> dict:
    from apps.branches.models import Branch
    return {str(b['softech_branch_id']): (b['name_ar'] or b['name'] or '')
            for b in Branch.objects.values('softech_branch_id', 'name_ar', 'name')}


def build(month: dt.date) -> dict:
    from apps.catalog.models import Item
    from apps.procurement.models import PurchaseLine
    start, end = month_bounds(month)
    lines = list(PurchaseLine.objects.filter(doc_date__gte=start - timedelta(days=STALE_DAYS), doc_date__lt=end,
                                             is_return=False, net_qty__gt=0, public_price__gt=0,
                                             item__isnull=False)
                 .order_by('doc_date', 'id')
                 .values('id', 'item_id', 'item_code', 'supplier_code', 'buyer_code', 'branch_code',
                         'doc_number', 'doc_date', 'net_qty', 'bonus_qty', 'net_value', 'vat_value',
                         'public_price'))
    prof = _profiles({l['supplier_code'] for l in lines})
    comp_of = {}
    for code in {l['supplier_code'] for l in lines}:
        key, name, accounts = _company(code, prof)
        comp_of[code] = (key, name, _company_tier(accounts, prof))

    per_item = defaultdict(list)                         # item_id → priced head-tier lines, by date
    for l in lines:
        key, name, tier = comp_of[l['supplier_code']]
        if tier not in HEAD_TIERS:
            continue                                     # warehouses / virtual accounts: never compared
        d, cost = _line_discount(l)
        if d is None or not (-0.5 < d < 0.9):            # pure free lines and mis-keyed lines
            continue
        per_item[l['item_id']].append({**l, 'company': key, 'company_name': name, 'tier': tier,
                                       'd': d, 'cost': cost,
                                       'units': (_f(l['net_qty']) or 0) + (_f(l['bonus_qty']) or 0)})

    checked, out = 0, []
    for iid, ls in per_item.items():
        for i, l in enumerate(ls):
            if not (start <= l['doc_date'] < end):
                continue
            checked += 1
            since = l['doc_date'] - timedelta(days=STALE_DAYS)
            best = None
            for o in ls:                                 # a cheaper price we could have had at the time
                if o['doc_date'] > l['doc_date']:
                    break
                if o['doc_date'] < since or o['company'] == l['company']:
                    continue
                if best is None or o['d'] > best['d']:
                    best = o
            if best is None or (best['d'] - l['d']) * 100 <= BETTER_PCT:
                continue
            public = _f(l['public_price']) or 0
            out.append({
                'item_id': iid, 'code': l['item_code'], 'date': l['doc_date'].isoformat(),
                'doc_number': l['doc_number'], 'branch_code': l['branch_code'],
                'buyer_code': (l['buyer_code'] or '').strip(),
                'supplier': l['company'], 'supplier_name': l['company_name'],
                'tier_label': TIER_LABELS.get(l['tier'], l['tier']),
                'units': round(l['units'], 3), 'public_price': public,
                'discount_pct': round(l['d'] * 100, 2), 'unit_cost': round(l['cost'], 2),
                'cheaper_supplier': best['company_name'], 'cheaper_date': best['doc_date'].isoformat(),
                'cheaper_discount_pct': round(best['d'] * 100, 2),
                'gap_pct': round((best['d'] - l['d']) * 100, 2),
                'egp_above': round((best['d'] - l['d']) * public * l['units'], 2),
            })

    items = {i.id: i.name for i in Item.objects.filter(pk__in={r['item_id'] for r in out}).only('id', 'name')}
    buyers = _buyer_names({r['buyer_code'] for r in out if r['buyer_code']})
    branches = _branch_names()
    by_sup, by_buyer = {}, {}
    for r in out:
        r['name'] = items.get(r['item_id'], '')
        r['buyer_name'] = buyers.get(r['buyer_code'], '')
        r['branch_name'] = branches.get(r['branch_code'], '')      # never a bare branch code on screen
        s = by_sup.setdefault(r['supplier'], {'key': r['supplier'], 'name': r['supplier_name'], 'lines': 0,
                                              'egp_above': 0.0})
        b = by_buyer.setdefault(r['buyer_code'], {'code': r['buyer_code'], 'name': r['buyer_name'], 'lines': 0,
                                                  'egp_above': 0.0})
        for g in (s, b):
            g['lines'] += 1
            g['egp_above'] = round(g['egp_above'] + r['egp_above'], 2)
    out.sort(key=lambda r: (-r['egp_above'], r['date'], r['code']))
    return {
        'month': start.strftime('%Y-%m'), 'better_pct': BETTER_PCT, 'stale_days': STALE_DAYS,
        'totals': {'lines_checked': checked, 'lines': len(out),
                   'egp_above': round(sum(r['egp_above'] for r in out), 2)},
        'by_supplier': sorted(by_sup.values(), key=lambda g: -g['egp_above']),
        'by_buyer': sorted(by_buyer.values(), key=lambda g: -g['egp_above']),
        'lines': out,
    }


def to_excel(rep) -> bytes:
    import io
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from core.export_safety import neutralise_formulas
    wb = Workbook()
    head_font, head_fill = Font(name='Arial', bold=True, color='FFFFFF'), PatternFill('solid', fgColor='022871')

    def sheet(ws, title, heads, rows):
        ws.title = title
        ws.sheet_view.rightToLeft = True
        ws.append(heads)
        for c in ws[1]:
            c.font, c.fill = head_font, head_fill
        for r in rows:
            ws.append(r)
        ws.freeze_panes = 'A2'

    sheet(wb.active, 'السطور', ['التاريخ', 'رقم الفاتورة', 'الفرع', 'المشتري', 'المورد', 'الكود', 'الصنف', 'الكمية',
                                'سعر الجمهور', 'خصمنا %', 'تكلفة الوحدة', 'الأرخص', 'تاريخه', 'خصمه %',
                                'الفرق %', 'دفعنا زيادة (ج)'],
          [[r['date'], r['doc_number'], r['branch_name'] or r['branch_code'],
            r['buyer_name'] or r['buyer_code'], r['supplier_name'], r['code'], r['name'], r['units'],
            r['public_price'], r['discount_pct'], r['unit_cost'], r['cheaper_supplier'], r['cheaper_date'],
            r['cheaper_discount_pct'], r['gap_pct'], r['egp_above']] for r in rep['lines']])
    sheet(wb.create_sheet(), 'حسب المورد', ['المورد', 'سطور', 'دفعنا زيادة (ج)'],
          [[g['name'], g['lines'], g['egp_above']] for g in rep['by_supplier']])
    sheet(wb.create_sheet(), 'حسب المشتري', ['المشتري', 'سطور', 'دفعنا زيادة (ج)'],
          [[g['name'] or g['code'] or '—', g['lines'], g['egp_above']] for g in rep['by_buyer']])
    neutralise_formulas(wb)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
