"""
customers/repeat_order.py — rebuild a past order into a fresh cart proposal,
REVALIDATING every line against today's reality. Never a blind copy (rule 4/7):

  • price   — current Item.pack_price vs what was paid (flag drift)
  • stock   — live branch availability (flag out-of-stock)
  • safety/status — catalog.safety.blocks_sale (flag blocked; pharmacy safety wins)

Deterministic, read-only. The cashier confirms; nothing is auto-added.
"""
from django.db.models import Sum

from apps.catalog.models import Item, ItemStock, EXCLUDED_STORE_CODES
from apps.catalog.safety import item_safety_flags, blocks_sale


def build_repeat_order(purchase, *, branch_id=None):
    """Revalidate a PurchaseHistory into a proposed cart. branch_id → live stock."""
    lines_qs = purchase.lines.select_related('item').all()
    res = revalidate_lines(
        [{'item_id': l.item_id, 'qty': l.quantity, 'unit_price': l.unit_price} for l in lines_qs],
        branch_id=branch_id)
    return {
        'source_invoice': {'id': purchase.id, 'date': purchase.invoice_date.isoformat() if purchase.invoice_date else None},
        'branch': branch_id,
        'lines': res['lines'],
        'summary': res['summary'],
    }


def revalidate_lines(lines, *, branch_id=None):
    """Revalidate raw lines against today's price / stock / safety.

    Each input line: {"item_id" | "softech_itemcode", "qty", "unit_price"?}. Returns
    {"lines": [...], "summary": {...}} — the shape build_repeat_order always returned.
    Shared by the repeat-order and the contract "last prescription" flows."""
    codes = [str(l['softech_itemcode']).strip() for l in lines
             if not l.get('item_id') and l.get('softech_itemcode')]
    by_code = {i.softech_id: i for i in Item.objects.filter(softech_id__in=codes)} if codes else {}
    ids = [l['item_id'] for l in lines if l.get('item_id')]
    by_id = {i.id: i for i in Item.objects.filter(id__in=ids)} if ids else {}

    resolved = []
    for l in lines:
        it = by_id.get(l.get('item_id')) if l.get('item_id') else             by_code.get(str(l.get('softech_itemcode') or '').strip())
        resolved.append((l, it))
    item_ids = [it.id for _, it in resolved if it]
    stock = _branch_stock(item_ids, branch_id) if branch_id else {}

    out, summary = [], {'total_lines': 0, 'available': 0, 'out_of_stock': 0,
                        'blocked': 0, 'price_changed': 0, 'missing_item': 0}
    for l, it in resolved:
        summary['total_lines'] += 1
        qty = float(l.get('qty') or 0)
        if not it:
            summary['missing_item'] += 1
            out.append({'item_id': None, 'name': None, 'qty': qty,
                        'status': 'missing', 'blocked': True})
            continue

        old_price = float(l.get('unit_price') or 0)
        cur_price = float(it.pack_price or 0)
        price_changed = abs(cur_price - old_price) > 0.005
        blocked = blocks_sale(it)
        # With a branch context, a missing stock row means 0 (out) — not "unknown".
        qty_avail = stock.get(it.id, 0.0) if branch_id else None
        in_stock = (qty_avail is None) or (qty_avail >= qty)

        if blocked:
            summary['blocked'] += 1
        elif branch_id and not in_stock:
            summary['out_of_stock'] += 1
        else:
            summary['available'] += 1
        if price_changed:
            summary['price_changed'] += 1

        out.append({
            'item_id': it.id,
            'softech_id': it.softech_id,
            'batch_required': bool(it.batch_required),
            'name': it.name,
            'qty': qty,
            'old_unit_price': old_price,
            'current_pack_price': cur_price,
            'price_changed': price_changed,
            'price_delta': round(cur_price - old_price, 3),
            'qty_available': qty_avail,
            'in_stock': in_stock,
            'blocked': blocked,
            'safety_flags': item_safety_flags(it),
            'status': 'blocked' if blocked else ('out_of_stock' if (branch_id and not in_stock) else 'ok'),
        })

    return {'lines': out, 'summary': summary}


def last_sale_for(customer):
    """The customer's most recent SALE invoice (doc_code 115), or None."""
    return (customer.purchases.filter(doc_code='115')
            .order_by('-invoice_date').first())


def _branch_stock(item_ids, branch_id):
    rows = (ItemStock.objects
            .filter(item_id__in=item_ids, branch_id=branch_id)
            .exclude(softech_store_code__in=EXCLUDED_STORE_CODES)
            .values('item_id').annotate(qty=Sum('quantity_on_hand')))
    return {r['item_id']: float(r['qty'] or 0) for r in rows}
