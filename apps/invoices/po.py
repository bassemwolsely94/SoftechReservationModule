"""
apps/invoices/po.py

Purchase-Order / Goods-Received matching — a SEPARATE, advisory workflow.

Compares what was ORDERED (a PurchaseOrder) against what the supplier INVOICED
(a SupplierInvoice), line by line, and reports quantity/price variances plus
items missing or extra. It is deliberately decoupled from SOFTECH posting: this
is a goods-received sanity check, never a gate on the post. Low-traffic by design.

Pure/deterministic given the two sets of lines; no SOFTECH contact.
"""
from __future__ import annotations

from decimal import Decimal

_QTY_TOL = Decimal('0.001')
_PRICE_TOL_PCT = Decimal('0.02')   # 2% price tolerance


def _d(v) -> Decimal:
    try:
        return Decimal(str(v or 0))
    except Exception:
        return Decimal('0')


def match_invoice_to_po(invoice, po) -> dict:
    """Return a variance report comparing invoice lines to PO lines by item.

    {
      po_number, invoice_id,
      lines: [{item_id, item_name, po_qty, inv_qty, qty_variance,
               po_price, inv_price, price_variance_pct, status}],
      missing_from_invoice: [...],   # ordered but not on the invoice
      extra_in_invoice: [...],       # invoiced but not ordered
      summary: {matched, qty_mismatch, price_mismatch, missing, extra}
    }
    status ∈ ok | qty_variance | price_variance | both
    """
    po_lines = {}
    for l in po.lines.select_related('item').all():
        po_lines.setdefault(l.item_id, {'item': l.item, 'qty': _d(0), 'price': _d(l.unit_price)})
        po_lines[l.item_id]['qty'] += _d(l.quantity)

    inv_lines = {}
    for l in invoice.lines.select_related('item').all():
        if not l.item_id:
            continue
        net = _d(l.unit_price)
        if net == 0 and _d(l.public_price) > 0:
            net = _d(l.public_price) * (1 - _d(l.discount_pct) / 100) * (1 - _d(l.extra_discount_pct) / 100)
        inv_lines.setdefault(l.item_id, {'item': l.item, 'qty': _d(0), 'price': net})
        inv_lines[l.item_id]['qty'] += _d(l.quantity)

    lines = []
    summary = {'matched': 0, 'qty_mismatch': 0, 'price_mismatch': 0, 'missing': 0, 'extra': 0}

    for item_id, po_l in po_lines.items():
        inv_l = inv_lines.get(item_id)
        if not inv_l:
            summary['missing'] += 1
            continue
        qty_var = inv_l['qty'] - po_l['qty']
        price_var_pct = (abs(inv_l['price'] - po_l['price']) / po_l['price']) if po_l['price'] else _d(0)
        qbad = abs(qty_var) > _QTY_TOL
        pbad = price_var_pct > _PRICE_TOL_PCT
        status = ('both' if qbad and pbad else 'qty_variance' if qbad
                  else 'price_variance' if pbad else 'ok')
        if status == 'ok':
            summary['matched'] += 1
        else:
            if qbad:
                summary['qty_mismatch'] += 1
            if pbad:
                summary['price_mismatch'] += 1
        lines.append({
            'item_id': item_id, 'item_name': po_l['item'].name,
            'po_qty': float(po_l['qty']), 'inv_qty': float(inv_l['qty']),
            'qty_variance': float(qty_var),
            'po_price': float(po_l['price']), 'inv_price': float(inv_l['price']),
            'price_variance_pct': round(float(price_var_pct), 4),
            'status': status,
        })

    missing = [{'item_id': i, 'item_name': d['item'].name, 'po_qty': float(d['qty'])}
               for i, d in po_lines.items() if i not in inv_lines]
    extra = [{'item_id': i, 'item_name': d['item'].name, 'inv_qty': float(d['qty'])}
             for i, d in inv_lines.items() if i not in po_lines]
    summary['extra'] = len(extra)

    return {
        'po_number': po.po_number, 'invoice_id': invoice.pk,
        'lines': lines, 'missing_from_invoice': missing, 'extra_in_invoice': extra,
        'summary': summary,
    }
