"""
apps/finance/recon_lines.py

Item lines of ONE invoice/return, read live from SOFTECH stktrans only when a user
presses «أصناف الفاتورة» (never bulk-loaded). AT ISOLATION 0 so the read never
waits on other sessions' locks; cached briefly per invoice; item names from the
catalog mirror. Read-only.
"""
from __future__ import annotations

import time
from decimal import Decimal

from .models import APInvoice

_CACHE: dict = {}
_TTL = 600


def _dec(v):
    try:
        return Decimal(str(v)) if v is not None else None
    except Exception:
        return None


def invoice_lines(invoice: APInvoice) -> dict:
    hit = _CACHE.get(invoice.id)
    if hit and time.time() - hit[0] < _TTL:
        return hit[1]
    from config.sybase import get_sybase_connection
    from apps.catalog.models import Item
    d = invoice.docdate
    dn = int(str(invoice.docnumber).split('.')[0])
    br, dc = str(invoice.branchcode).strip(), str(invoice.doccode).strip()
    if not (br.isdigit() and dc.isdigit()):
        return {'lines': [], 'error': 'مفتاح المستند غير صالح'}
    sql = (f"SELECT itemcode, transqty, transprice, pharmacydiscp, transprice_total, "
           f"itemexpirydate, itemsaleprice, storecode, r_docnumber "
           f"FROM SOFTECHDB9.dbo.stktrans WHERE branchcode='{br}' AND doccode='{dc}' "
           f"AND docnumber={dn} AND docdate='{d.month}-{d.day}-{d.year} 0:0:0.000' AT ISOLATION 0")
    conn = get_sybase_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql)
        cols = [c[0] for c in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        try:
            conn.close()
        except Exception:
            pass
    codes = {str(r['itemcode']).strip() for r in rows}
    names = dict(Item.objects.filter(softech_id__in=codes).values_list('softech_id', 'name'))
    lines, total = [], Decimal('0')
    for r in rows:
        code = str(r['itemcode']).strip()
        disc = _dec(r['pharmacydiscp']) or Decimal('0')
        line_total = _dec(r['transprice_total']) or Decimal('0')
        total += line_total
        exp = r.get('itemexpirydate')
        lines.append({
            'itemcode': code, 'name': names.get(code, ''),
            'qty': _dec(r['transqty']), 'price': _dec(r['transprice']),
            'discount_pct': disc, 'total': line_total,
            'sale_price': _dec(r['itemsaleprice']),
            'expiry': exp.date().isoformat() if hasattr(exp, 'date') else (str(exp)[:10] if exp else ''),
            'store': str(r.get('storecode') or '').strip(),
            'is_free': disc >= Decimal('100'),           # FOC line (pharmacydiscp = 100)
            'returned_from': (str(r.get('r_docnumber')).split('.')[0]
                              if r.get('r_docnumber') and float(r['r_docnumber'] or 0) > 0 else ''),
        })
    data = {'lines': lines, 'count': len(lines), 'lines_total': total,
            'doc_value': invoice.doc_value, 'comments': invoice.comments}
    _CACHE[invoice.id] = (time.time(), data)
    return data
