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
    item_ids = [l.item_id for l in lines_qs if l.item_id]
    stock = _branch_stock(item_ids, branch_id) if branch_id else {}
    items = {i.id: i for i in Item.objects.filter(id__in=item_ids)}

    out, summary = [], {'total_lines': 0, 'available': 0, 'out_of_stock': 0,
                        'blocked': 0, 'price_changed': 0, 'missing_item': 0}
    for l in lines_qs:
        summary['total_lines'] += 1
        it = items.get(l.item_id)
        if not it:
            summary['missing_item'] += 1
            out.append({'item_id': None, 'name': None, 'qty': float(l.quantity or 0),
                        'status': 'missing', 'blocked': True})
            continue

        old_price = float(l.unit_price or 0)
        cur_price = float(it.pack_price or 0)
        price_changed = abs(cur_price - old_price) > 0.005
        blocked = blocks_sale(it)
        # With a branch context, a missing stock row means 0 (out) — not "unknown".
        qty_avail = stock.get(it.id, 0.0) if branch_id else None
        in_stock = (qty_avail is None) or (qty_avail >= float(l.quantity or 0))

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
            'name': it.name,
            'qty': float(l.quantity or 0),
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

    return {
        'source_invoice': {'id': purchase.id, 'date': purchase.invoice_date.isoformat() if purchase.invoice_date else None},
        'branch': branch_id,
        'lines': out,
        'summary': summary,
    }


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
