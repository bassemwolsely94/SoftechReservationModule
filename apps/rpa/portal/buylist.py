"""Buy lists for the supplier-portal robot: sources, supplier ranking, pick, remainder.

The buyer's list of items to order. Quantities are whole packs (rounded UP). Nothing here
writes SOFTECH; ``send_other`` only records supply decisions through the existing
``commit_order`` (the WhatsApp / Excel order list path).
"""
from __future__ import annotations

import math

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.rpa.models import BuyList, BuyListLine, SupplierPortal

DEFAULT_SUPPLIER_ORDER = ['565', '30', '260']


class BuyListError(ValueError):
    pass


def _audit(action, obj, *, staff, note='', extra=None):
    try:
        AuditLog.log(action, user=staff, obj=obj, note=note[:255], extra=extra)
    except Exception:  # audit is non-fatal, as everywhere in the project
        pass


# ── ranking and default supplier ───────────────────────────────────────────────

def rank_suppliers(item_ids):
    """{item_id: [supplier_code, ...]} best first, from the supplier comparison board.
    Only suppliers with a SOFTECH code are returned (name-only suppliers cannot be ordered)."""
    from apps.supply.comparison import build_board
    ids = [int(i) for i in item_ids]
    if not ids:
        return {}
    board = build_board(item_ids=ids)
    out = {}
    for row in board.get('rows', []):
        codes = []

        def add(key):
            if key and not str(key).startswith('name:') and str(key) not in codes:
                codes.append(str(key))
        if row.get('best'):
            add(row['best']['supplier'])
        for a in row.get('allocation') or []:
            add(a.get('supplier'))
        cells = sorted((c for c in row.get('cells') or [] if c.get('tier') != 'warehouse'),
                       key=lambda c: (c.get('effective_cost') is None, c.get('effective_cost') or 0))
        for c in cells:
            add(c.get('supplier'))
        out[row['item_id']] = codes
    return out


def _fallback_supplier(item, pivot_supplier=''):
    from apps.catalog.models import ItemSupplierLink
    from apps.config.models import SystemSetting
    order = SystemSetting.get('portal_supplier_order', DEFAULT_SUPPLIER_ORDER) or DEFAULT_SUPPLIER_ORDER
    carried = set(ItemSupplierLink.objects.filter(item_code=item.softech_id)
                  .values_list('supp_code', flat=True))
    for code in order:
        if str(code) in carried:
            return str(code)
    return str(pivot_supplier or '')


def _default_suppliers(items, pivot_suppliers=None):
    pivot_suppliers = pivot_suppliers or {}
    ranks = rank_suppliers([i.pk for i in items])
    return {i.pk: (ranks.get(i.pk) or [None])[0] or _fallback_supplier(i, pivot_suppliers.get(i.pk, ''))
            for i in items}


# ── creation ───────────────────────────────────────────────────────────────────

def _build(source_kind, source_ref, entries, *, staff):
    """entries: [{'code', 'qty' (raw), 'key', 'supplier'}] in list order. Returns a BuyList whose
    ``.errors`` attribute lists the unknown item codes (never guessed, never a line)."""
    from apps.catalog.models import Item
    errors = []
    wanted = []
    for e in entries:
        needed = math.ceil(float(e['qty']) - 1e-9)
        if needed <= 0:
            continue
        wanted.append((e, needed))
    codes = {str(e['code']) for e, _ in wanted}
    items = {i.softech_id: i for i in Item.objects.filter(softech_id__in=codes)}
    good = []
    for e, needed in wanted:
        item = items.get(str(e['code']))
        if item is None:
            errors.append({'item_code': str(e['code']), 'error': 'صنف غير معروف'})
            continue
        good.append((e, needed, item))

    keys = [e['key'] for e, _, _ in good]
    clash = (BuyListLine.objects.filter(source_key__in=keys, open_guard=True)
             .values_list('source_key', 'buylist_id').first())
    if clash:
        raise BuyListError(f'السطر موجود في قائمة شراء مفتوحة (رقم {clash[1]})')

    defaults = _default_suppliers([i for _, _, i in good],
                                  {i.pk: e.get('supplier', '') for e, _, i in good})
    try:
        with transaction.atomic():
            bl = BuyList.objects.create(source_kind=source_kind, source_ref=source_ref, created_by=staff)
            BuyListLine.objects.bulk_create([
                BuyListLine(buylist=bl, seq=n, item=item, needed_qty=needed, remaining_qty=needed,
                            chosen_supplier=defaults.get(item.pk, ''), source_key=e['key'])
                for n, (e, needed, item) in enumerate(good, start=1)])
    except IntegrityError:
        raise BuyListError('السطر موجود في قائمة شراء مفتوحة')
    bl.errors = errors
    _audit('rpa_portal_buylist_created', bl, staff=staff,
           note=f'{source_kind} {source_ref}', extra={'lines': len(good), 'errors': len(errors)})
    return bl


def create_from_pivot(snapshot, *, staff, supplier_codes=None):
    codes = {str(c) for c in supplier_codes} if supplier_codes else None
    entries = []
    for ln in snapshot.lines or []:
        if codes is not None and str(ln.get('supplier_code', '')) not in codes:
            continue
        entries.append({'code': ln['item_code'], 'qty': ln.get('total_gap') or 0,
                        'key': f'pivot:{snapshot.pk}:{ln["item_code"]}',
                        'supplier': str(ln.get('supplier_code') or '')})
    return _build('pivot', str(snapshot.pk), entries, staff=staff)


def create_from_isr(push, *, staff):
    entries = [{'code': ln['itemcode'], 'qty': ln.get('itemqty') or 0,
                'key': f'isr:{push.pk}:{ln["itemcode"]}'} for ln in push.lines_snapshot or []]
    return _build('isr', str(push.pk), entries, staff=staff)


def create_from_rows(rows, *, staff, file_sha256):
    entries = [{'code': r['item_code'], 'qty': r.get('qty') or 0,
                'key': f'upload:{file_sha256[:16]}:{r["item_code"]}'} for r in rows]
    return _build('upload', file_sha256[:16], entries, staff=staff)


# ── pick / result / remainder ──────────────────────────────────────────────────

def pick(line, supplier_code, *, staff):
    if line.buylist.status != 'open':
        raise BuyListError('القائمة مغلقة')
    from apps.rpa.portal.jobs import assert_line_not_frozen
    assert_line_not_frozen(line)
    supplier_code = str(supplier_code or '').strip()[:120]
    if not supplier_code:
        raise BuyListError('اختر المورد')
    before = line.chosen_supplier
    line.chosen_supplier = supplier_code
    line.save(update_fields=['chosen_supplier'])
    try:
        AuditLog.log('rpa_portal_line_picked', user=staff, obj=line,
                     old_data={'chosen_supplier': before}, new_data={'chosen_supplier': supplier_code},
                     note=f'buy list {line.buylist_id} line {line.seq}: {before or "-"} -> {supplier_code}')
    except Exception:  # audit is non-fatal, as everywhere in the project
        pass
    return line


def rows_from_sheet(parsed):
    """Rows of an uploaded buy-list sheet (apps.rpa.sheet.parse_issue_sheet output) as
    ([{'item_code', 'qty'}], errors). A quantity that is not a number is an error, never guessed."""
    rows, errors = [], []
    for r in parsed:
        code = str(r.get('itemcode') or '').strip()
        try:
            qty = float(str(r.get('qty') or '').strip())
        except ValueError:
            qty = None
        if not code or qty is None or not math.isfinite(qty):
            errors.append({'item_code': code, 'row_no': r.get('row_no'), 'error': 'كمية غير مفهومة'})
            continue
        rows.append({'item_code': code, 'qty': qty})
    return rows, errors


def apply_result(line, *, supplier_code, accepted, basket_id):
    accepted = max(0, int(accepted))
    line.tried = list(line.tried or []) + [{
        'supplier': str(supplier_code), 'accepted': accepted,
        'at': timezone.now().isoformat(), 'basket': basket_id}]
    line.remaining_qty = max(0, line.remaining_qty - accepted)
    if line.remaining_qty > 0:
        line.chosen_supplier = ''
    line.save(update_fields=['tried', 'remaining_qty', 'chosen_supplier'])
    return line


def remainders(*, staff=None):
    qs = BuyListLine.objects.filter(buylist__status='open', remaining_qty__gt=0).exclude(tried=[])
    return qs.select_related('item', 'buylist')


# ── suppliers without a portal ─────────────────────────────────────────────────

def send_other(buylist, supplier_code, *, staff, lang='ar', idempotency_key=None):
    """Record an order list for a supplier that has no portal. The default key is
    ``buylist-<pk>-<code>-<n>`` with n = previous sends to this supplier + 1. Passing a key that
    was already used replays that send (no new decisions, no line changes)."""
    from apps.branches.models import Branch, hq_code
    from apps.invoices.models import VendorProfile
    from apps.supply.execution import commit_order
    from apps.supply.models import SupplyDecision
    supplier_code = str(supplier_code)
    if SupplierPortal.objects.filter(supplier_code=supplier_code).exists():
        raise BuyListError('هذا المورد له موقع — يُرسل عبر الروبوت وليس كقائمة واتساب')
    prefix = f'buylist-{buylist.pk}-{supplier_code}-'
    if idempotency_key and not str(idempotency_key).startswith(prefix):
        raise BuyListError('مفتاح الإرسال لا يخص هذه القائمة وهذا المورد')
    # One transaction: the list row is locked first, so two sends serialise; the decisions
    # and the line updates commit together or not at all.
    with transaction.atomic():
        locked = BuyList.objects.select_for_update().get(pk=buylist.pk)
        if locked.status != 'open':
            raise BuyListError('القائمة مغلقة')
        if idempotency_key:
            prior = list(SupplyDecision.objects.filter(order_ref=idempotency_key))
            if prior:
                res = commit_order([], idempotency_key=idempotency_key, staff=staff, lang=lang)
                return {'order_ref': idempotency_key, 'text': res['text'], 'replayed': True,
                        'lines': len(prior)}
        lines = list(locked.lines.select_related('item').filter(
            chosen_supplier=supplier_code, remaining_qty__gt=0))
        if not lines:
            raise BuyListError('لا توجد أسطر مختارة لهذا المورد')
        vendor = VendorProfile.objects.filter(softech_personcode=supplier_code).first()
        hq = Branch.objects.get(softech_branch_id=hq_code())
        n = (SupplyDecision.objects.filter(order_ref__startswith=prefix)
             .values('order_ref').distinct().count()) + 1
        key = idempotency_key or f'{prefix}{n}'
        res = commit_order(
            [{'item_id': ln.item_id, 'qty': ln.remaining_qty, 'branch_id': hq.pk,
              'reason': ln.reason or f'قائمة شراء {buylist.pk}'} for ln in lines],
            idempotency_key=key, supplier=vendor, staff=staff, lang=lang)
        if not res['replayed']:
            for ln in lines:
                apply_result(ln, supplier_code=supplier_code, accepted=ln.remaining_qty, basket_id=None)
    return {'order_ref': res['order_ref'], 'text': res['text'], 'replayed': res['replayed'],
            'lines': len(lines)}
