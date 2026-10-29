"""
apps/replacement/golden.py — B1 pilot readiness: golden-template comparison (doc 25 §21).

READ-ONLY against SOFTECH. Takes a purchase that staff posted NATIVELY on a virtual supplier
(stktransm + stktrans, doccode 10), rebuilds the same purchase through the exact path a case uses
(legs.build_purchase_invoice → invoices.writer.build_plan) inside a PG transaction that is always
rolled back, and diffs every column the writer would send against the native row.

Fields that are assigned at save time (serial, dates, running balance, line number, user) or that
the module sets on purpose (docnumber2 = case token, D14) are not compared — they are listed in
IGNORED so the report says so instead of hiding them.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.db import transaction

IGNORED_HEADER = {'docnumber', 'docdate', 'docwritedate', 'usercode', 'docnumber2', 'ptclassifcode',
                  'supplier_name', 'trans_time', 'vf2'}
IGNORED_LINE = {'docnumber', 'docdate', 'usercode', 'newqty', 'dblitemflag', 'item_name', 'newcostprice',
                'trans_time'}
TOL = Decimal('0.01')


def _norm(v):
    if v is None:
        return None
    if isinstance(v, (int, float, Decimal)):
        return Decimal(str(v))
    s = str(v).strip()
    try:
        return Decimal(s)
    except Exception:
        return s[:10] if len(s) >= 10 and s[4:5] == '-' else s     # datetimes → the date part


def _same(a, b) -> bool:
    a, b = _norm(a), _norm(b)
    if isinstance(a, Decimal) and isinstance(b, Decimal):
        return abs(a - b) <= TOL
    if a in (None, '', 'None') and b in (None, '', 'None'):
        return True
    return a == b


def diff_plan(native_header: dict, native_lines: list[dict], plan: dict) -> dict:
    """Pure: column-by-column differences between the native document and our dry-run plan.
    Only columns present on BOTH sides are compared (the plan holds exactly what we send)."""
    out = {'header': [], 'lines': [], 'missing_lines': [], 'extra_lines': [],
           'ignored': {'header': sorted(IGNORED_HEADER), 'line': sorted(IGNORED_LINE)}}
    for k, ours in plan['header'].items():
        if k in IGNORED_HEADER or k not in native_header:
            continue
        if not _same(ours, native_header[k]):
            out['header'].append({'field': k, 'native': str(native_header[k]), 'ours': str(ours)})
    native_by_item = {str(l.get('itemcode', '')).strip(): l for l in native_lines}
    ours_by_item = {str(l.get('itemcode', '')).strip(): l for l in plan['lines']}
    out['missing_lines'] = sorted(set(native_by_item) - set(ours_by_item))
    out['extra_lines'] = sorted(set(ours_by_item) - set(native_by_item))
    for code in sorted(set(native_by_item) & set(ours_by_item)):
        n, o = native_by_item[code], ours_by_item[code]
        for k, ours in o.items():
            if k in IGNORED_LINE or k not in n:
                continue
            if not _same(ours, n[k]):
                out['lines'].append({'itemcode': code, 'field': k, 'native': str(n[k]), 'ours': str(ours)})
    out['identical'] = not (out['header'] or out['lines'] or out['missing_lines'] or out['extra_lines'])
    return out


def read_native(branchcode: str, docnumber: int, docdate: date) -> tuple[dict, list[dict]]:
    """SELECT-only read of one native purchase on its branch DB (branch + doccode + number + date:
    per-branch sequences collide, never query a bare docnumber)."""
    from apps.branches.models import Branch
    from apps.invoices import writer as IW
    from config.sybase import get_branch_connection
    br = Branch.objects.get(softech_branch_id=branchcode)
    conn = get_branch_connection(br.effective_db_host, br.effective_db_port, br.db_name or 'SOFTECHDB9')
    try:
        day = f'{docdate:%Y-%m-%d}'
        args = [branchcode, int(docnumber), day, day]
        where = ("branchcode=? AND doccode='10' AND docnumber=? AND docdate >= convert(datetime, ?) "
                 "AND docdate < dateadd(day, 1, convert(datetime, ?))")
        hdr = IW._one_dict(conn, f'SELECT * FROM stktransm WHERE {where}', args)
        if not hdr:
            raise ValueError(f'لم يتم العثور على فاتورة الشراء {branchcode}/{docnumber} بتاريخ {docdate}')
        lines = IW._all_dicts(conn, f'SELECT * FROM stktrans WHERE {where} ORDER BY dblitemflag', args)
    finally:
        conn.close()
    return hdr, lines


def compare(branchcode: str, docnumber: int, docdate: date, *, native=None) -> dict:
    """Rebuild the native purchase through the case path and diff it. Nothing is kept in PG
    (the invoice is created inside a rolled-back transaction) and nothing is written to SOFTECH."""
    from apps.branches.models import Branch
    from apps.catalog.models import Item
    from apps.invoices import writer as IW
    from .legs import PURCHASE_LINE_EXTRA, build_purchase_invoice
    hdr, lines = native or read_native(branchcode, docnumber, docdate)
    supplier = str(hdr.get('cust_branch_code', '')).strip()
    report = {'native': f'{branchcode}/10/{docnumber} {docdate}', 'supplier': supplier,
              'native_value': str(hdr.get('docvalue')), 'price_notes': []}
    with transaction.atomic():
        calc_lines = []
        for l in lines:
            code = str(l['itemcode']).strip()
            item = Item.objects.filter(softech_id=code).first()
            if item is None:
                report['price_notes'].append(f'الصنف {code} غير موجود في الكتالوج')
                continue
            # the case path prices from the catalog public price; note when SOFTECH's differs
            public = Decimal(str(item.pack_price or 0))
            native_public = Decimal(str(l.get('itemsaleprice_tax') or l.get('itemsaleprice') or 0))
            if abs(public - native_public) > TOL:
                report['price_notes'].append(f'الصنف {code}: سعر الجمهور في الكتالوج {public} ≠ SOFTECH {native_public}')
            qty = Decimal(str(l['transqty']))
            calc_lines.append({'item': item, 'itemcode': code, 'qty': qty, 'public_price': public,
                               'deduction_pct': Decimal(str(l.get('pharmacydiscp') or 0)),
                               'unit_net': Decimal(str(l['transprice'])),
                               'entitlement': Decimal(str(l.get('transprice_total') or 0)),
                               # what the operator types from the box (the purchase leg's expiry input)
                               'expiry': str(l.get('itemexpirydate') or '')[:10]})
        branch = Branch.objects.get(softech_branch_id=branchcode)
        inv = build_purchase_invoice(branch, supplier, calc_lines, invoice_number='0', notes='golden compare')
        plan = IW.build_plan(inv, line_extra=PURCHASE_LINE_EXTRA)
        report['plan_value'] = str(plan['doc_value'])
        transaction.set_rollback(True)
    report['diff'] = diff_plan(hdr, lines, plan)
    return report
