"""
catalog/universal.py — one unified POS search across items, customers, orders and
reservations, so the cashier has a single box instead of four.

SAFETY RULE (rules 4/5, non-negotiable): item *identity* — the SOFTECH code and
the barcode used to pick the physical drug — is matched **exactly only**. Fuzzy /
trigram matching is used solely for human-readable NAMES (discovery). A cashier
must never land on the wrong medicine because a code fuzzy-matched. Exact-identity
hits are returned first and marked `exact=True`; name hits are clearly separate.

Deterministic, read-only, PG-only (optional live-free branch stock read from the
mirror). No SOFTECH write, no LLM (rule 10).
"""
from django.db.models import Q, Sum

from .models import Item, ItemStock, ItemBarcode, EXCLUDED_STORE_CODES
from .search_index import normalize_search_text
from .safety import item_safety_flags
from apps.catalog.wildcard import wq

# Result caps keep the box instant; the view may override per request.
DEFAULT_LIMIT = 8
TYPES = ('items', 'customers', 'orders', 'reservations')


def universal_search(query, *, branch_id=None, limit=DEFAULT_LIMIT, types=None):
    """Return grouped results: {'items': [...], 'customers': [...], ...}."""
    raw = (query or '').strip()
    types = tuple(types) if types else TYPES
    out = {t: [] for t in types}
    if len(raw) < 2:
        return out

    if 'items' in types:
        out['items'] = _search_items(raw, branch_id=branch_id, limit=limit)
    if 'customers' in types:
        out['customers'] = _search_customers(raw, limit=limit)
    if 'orders' in types:
        out['orders'] = _search_orders(raw, branch_id=branch_id, limit=limit)
    if 'reservations' in types:
        out['reservations'] = _search_reservations(raw, branch_id=branch_id, limit=limit)
    return out


# ── items ───────────────────────────────────────────────────────────────────────
def _search_items(raw, *, branch_id, limit):
    # The system-wide search rules (apps/catalog/wildcard.py): * and % = any characters,
    # parts in order, space literal; ranked code/barcode (EXACT only — never a prefix here,
    # safety rule above) → learned memory → literal text → pattern → any word order →
    # Arabic by sound → typo-tolerant «تقريبي» only when nothing else matched.
    from .wildcard import item_search, parse
    tiers = item_search(raw, limit=limit * 3, active_only=False, code_prefix=False)
    # the normalized haystack still catches punctuation / spacing variants («pan-adol»)
    if not parse(raw)['wild']:
        nq = normalize_search_text(raw)
        have = {i for i, _ in tiers}
        extra = [i for i in Item.objects.filter(search_name__icontains=nq).order_by()
                 .values_list('id', flat=True)[: limit * 3] if i not in have]
        if extra:
            tiers = [t for t in tiers if t[1] != 'approx'] + [(i, 'literal') for i in extra]
    tier_of = dict(tiers)
    exact_ids = {i for i, t in tiers if t == 'code'}
    ordered_ids = [i for i, _ in tiers]
    if not ordered_ids:
        return []

    items = {i.id: i for i in Item.objects.filter(id__in=ordered_ids)}
    stock_map = _branch_stock(ordered_ids, branch_id) if branch_id else {}

    results = []
    for iid in ordered_ids:
        it = items.get(iid)
        if not it:
            continue
        row = {
            'type': 'item',
            'id': it.id,
            'softech_id': it.softech_id,
            'name': it.name,
            'name_scientific': it.name_scientific,
            'barcode': it.barcode,
            'pack_price': float(it.pack_price or 0),
            'exact': iid in exact_ids,
            'learned': tier_of.get(iid) == 'learned',
            'sound': tier_of.get(iid) == 'sound',
            'approx': tier_of.get(iid) == 'approx',
            'safety_flags': item_safety_flags(it),
        }
        if branch_id:
            row['qty_at_branch'] = stock_map.get(iid, 0.0)
        results.append(row)
        if len(results) >= limit:
            break
    return results


def _branch_stock(item_ids, branch_id):
    rows = (
        ItemStock.objects
        .filter(item_id__in=item_ids, branch_id=branch_id)
        .exclude(softech_store_code__in=EXCLUDED_STORE_CODES)
        .values('item_id')
        .annotate(qty=Sum('quantity_on_hand'))
    )
    return {r['item_id']: float(r['qty'] or 0) for r in rows}


# ── customers ─────────────────────────────────────────────────────────────────────
def _search_customers(raw, *, limit):
    from apps.customers.models import Customer
    digits = raw.replace(' ', '')
    q = (
        wq(raw, 'name')
        | Q(phone__icontains=digits) | Q(phone_alt__icontains=digits)
        | Q(whatsapp_phone__icontains=digits)
        | Q(softech_pic__iexact=raw) | Q(softech_id__iexact=raw)
    )
    rows = Customer.objects.filter(q).only(
        'id', 'name', 'phone', 'whatsapp_phone', 'softech_pic', 'segment'
    )[:limit]
    return [{
        'type': 'customer',
        'id': c.id,
        'name': c.name,
        'phone': c.phone,
        'whatsapp_phone': c.whatsapp_phone or c.phone,
        'softech_pic': c.softech_pic,
        'segment': c.segment,
    } for c in rows]


# ── orders (indirect-POS) ──────────────────────────────────────────────────────────
def _search_orders(raw, *, branch_id, limit):
    from apps.pos_orders.models import SoftechSalesOrder
    q = wq(raw, 'customer_name') | Q(softech_pic__iexact=raw)
    if raw.isdigit():
        q |= Q(pk=int(raw)) | Q(softech_docnumber=raw)
    qs = SoftechSalesOrder.objects.filter(q)
    if branch_id:
        qs = qs.filter(branch_id=branch_id)
    qs = qs.select_related('branch').order_by('-id')[:limit]
    return [{
        'type': 'order',
        'id': o.id,
        'status': o.status,
        'status_label': o.get_status_display(),
        'customer_name': o.customer_name or o.softech_pic,
        'softech_docnumber': str(o.softech_docnumber) if o.softech_docnumber else None,
    } for o in qs]


# ── reservations ───────────────────────────────────────────────────────────────────
def _search_reservations(raw, *, branch_id, limit):
    from apps.reservations.models import Reservation
    digits = raw.replace(' ', '')
    q = (
        wq(raw, 'contact_name') | Q(contact_phone__icontains=digits)
        | Q(manual_item_name__icontains=raw) | Q(item__name__icontains=raw)
    )
    if raw.isdigit():
        q |= Q(pk=int(raw))
    qs = Reservation.objects.filter(q)
    if branch_id:
        qs = qs.filter(branch_id=branch_id)
    qs = qs.select_related('item').order_by('-id')[:limit]
    return [{
        'type': 'reservation',
        'id': r.id,
        'status': r.status,
        'status_label': r.get_status_display(),
        'contact_name': r.contact_name,
        'item_name': (r.item.name if r.item_id else r.manual_item_name),
    } for r in qs]
