"""
apps/catalog/pos_search.py

POS Speed Wave — read-only enrichment of item-search rows (thumbnail, strength,
per-branch stock, next action, stock age). No writes, no SOFTECH calls.
Quarantine stores (EXCLUDED_STORE_CODES) never count as stock.
"""
import re

from django.db.models import Sum

from .models import ItemStock, EXCLUDED_STORE_CODES

_NUM = r'\d+(?:\.\d+)?'
_STRENGTH_RE = re.compile(
    rf'(?<![\d.])({_NUM}(?:\s*/\s*{_NUM})?)\s*(MCG|MG|ML|IU|G|%)(?![A-Za-z])',
    re.IGNORECASE,
)


def extract_strength(name: str) -> str:
    """First «<n>[/<n>] <unit>» in the name, normalised ("5MG" -> "5 MG"); '' if none."""
    m = _STRENGTH_RE.search(name or '')
    if not m:
        return ''
    num = re.sub(r'\s+', '', m.group(1))
    return f'{num} {m.group(2).upper()}'


def network_stock(item_ids):
    """{item_id: [{'branch_id', 'qty'}, ...]} qty desc, operational branches only,
    quarantine stores excluded. Branches with a (zero-qty) stock row are listed."""
    if not item_ids:
        return {}
    rows = (ItemStock.objects.filter(item_id__in=item_ids,
                                     branch__is_operational=True)
            .exclude(softech_store_code__in=EXCLUDED_STORE_CODES)
            .values('item_id', 'branch_id').annotate(qty=Sum('quantity_on_hand')))
    out = {}
    for r in rows:
        out.setdefault(r['item_id'], []).append(
            {'branch_id': r['branch_id'], 'qty': float(r['qty'] or 0)})
    for lst in out.values():
        lst.sort(key=lambda b: (-b['qty'], b['branch_id']))
    return out


def primary_thumbs(item_ids):
    """{item_id: url} of the approved image — primary first, then lowest order."""
    if not item_ids:
        return {}
    from apps.product_experience.models import ProductMedia
    qs = (ProductMedia.objects.filter(item_id__in=item_ids, approved=True, media_type='image')
          .order_by('item_id', '-is_primary', 'order', 'id'))
    out = {}
    for m in qs:
        if m.item_id in out:
            continue
        f = m.thumbnail if m.thumbnail else m.file
        if f:
            out[m.item_id] = f.url
    return out


def next_action(here_qty, branch_stock, here_branch_id):
    """add (stock here) -> transfer (from the other branch with most stock) -> demand."""
    if (here_qty or 0) > 0:
        return {'kind': 'add'}
    best = None
    for b in branch_stock or []:
        if b['branch_id'] == here_branch_id or b['qty'] <= 0:
            continue
        if best is None or b['qty'] > best['qty'] or (
                b['qty'] == best['qty'] and b['branch_id'] < best['branch_id']):
            best = b
    if best:
        return {'kind': 'transfer', 'from_branch_id': best['branch_id']}
    return {'kind': 'demand'}


def stock_as_of():
    """ISO timestamp of the last successful stock sync (None if never)."""
    from apps.sync.freshness import get_freshness
    dom = get_freshness(['stock'])['domains'].get('stock') or {}
    return dom.get('last_success_at')


def enrich_rows(rows, branch_id):
    """Add thumb / strength / branch_stock / next_action to search rows in place."""
    ids = [r['item_id'] for r in rows if r.get('item_id')]
    stock, thumbs = network_stock(ids), primary_thumbs(ids)
    try:
        here = int(branch_id) if branch_id else None
    except (TypeError, ValueError):
        here = None
    for r in rows:
        iid = r.get('item_id')
        bs = stock.get(iid, []) if iid else []
        here_qty = r.get('qty_at_branch')
        if here_qty is None:
            here_qty = next((b['qty'] for b in bs if b['branch_id'] == here), 0)
        r['thumb'] = thumbs.get(iid) if iid else None
        r['strength'] = extract_strength(r.get('name', ''))
        r['branch_stock'] = bs
        r['next_action'] = next_action(here_qty, bs, here)
    return rows
