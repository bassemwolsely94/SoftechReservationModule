"""
apps/catalog/supplier_links.py — the PG mirror of SOFTECH ``itemssuppliers`` (owner
2026-10-05: "every supplier's codes match even while SOFTECH is down").

  sync_from_rows(rows)    → upsert + prune (pure, testable; rows = (itemcode, suppcode,
                            suppitemcode, main_supp))
  sync_item_suppliers()   → one read-only SELECT on SOFTECH, then sync_from_rows
  resolve_codes(supp, codes) → {supplier code → SOFTECH itemcode}, unambiguous only
  carried_item_ids(supp, item_ids) → which of these items the supplier carries

Read-only towards SOFTECH. A code that maps to several items for the same supplier is
AMBIGUOUS and never resolved (same rule as invoices/supplier_items.resolve_codes).
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

QUERY = ("SELECT itemcode, suppcode, suppitemcode, main_supp "
         "FROM SOFTECHDB9.dbo.itemssuppliers")
_BATCH = 5000


def _s(v) -> str:
    return str(v).strip() if v is not None else ''


def sync_from_rows(rows) -> dict:
    """Mirror the given itemssuppliers rows: insert new pairs, update changed codes / main
    flag, delete pairs SOFTECH no longer has. Only called with a COMPLETE read — a failed
    or partial read must never prune the mirror."""
    from django.db import transaction
    from .models import Item, ItemSupplierLink
    wanted = {}
    for itemcode, suppcode, code, main in rows:
        ic, sc = _s(itemcode), _s(suppcode)
        if ic and sc:
            wanted[(ic, sc)] = (_s(code)[:60], _s(main) == '1')
    item_ids = dict(Item.objects.filter(softech_id__in={ic for ic, _ in wanted})
                    .values_list('softech_id', 'id'))
    have = {(r.item_code, r.supp_code): r for r in ItemSupplierLink.objects.all()
            .only('id', 'item_code', 'supp_code', 'supp_item_code', 'is_main', 'item_id')}
    new, changed = [], []
    for key, (code, main) in wanted.items():
        iid = item_ids.get(key[0])
        row = have.get(key)
        if row is None:
            new.append(ItemSupplierLink(item_code=key[0], supp_code=key[1], supp_item_code=code,
                                        is_main=main, item_id=iid))
        elif (row.supp_item_code, row.is_main, row.item_id) != (code, main, iid):
            row.supp_item_code, row.is_main, row.item_id = code, main, iid
            changed.append(row)
    gone = [r.id for k, r in have.items() if k not in wanted]
    with transaction.atomic():
        ItemSupplierLink.objects.bulk_create(new, batch_size=_BATCH)
        ItemSupplierLink.objects.bulk_update(changed, ['supp_item_code', 'is_main', 'item'],
                                             batch_size=_BATCH)
        for i in range(0, len(gone), _BATCH):
            ItemSupplierLink.objects.filter(id__in=gone[i:i + _BATCH]).delete()
    return {'rows': len(wanted), 'created': len(new), 'updated': len(changed), 'deleted': len(gone),
            'with_code': sum(1 for c, _ in wanted.values() if c)}


def sync_item_suppliers() -> dict:
    """Read the whole of itemssuppliers from SOFTECH (HQ) and mirror it."""
    from config.sybase import get_sybase_connection
    conn = get_sybase_connection()
    try:
        cur = conn.cursor()
        cur.execute(QUERY)
        rows = cur.fetchall()
    finally:
        conn.close()
    out = sync_from_rows(rows)
    logger.info('[supplier_links] itemssuppliers mirrored: %s', out)
    return out


def resolve_codes(supp_code: str, codes) -> dict:
    """{supplier's code → SOFTECH itemcode} from the mirror — only codes that point to
    exactly ONE item for this supplier."""
    from .models import ItemSupplierLink
    supp = _s(supp_code)
    wanted = {_s(c) for c in (codes or []) if _s(c)}
    if not supp or not wanted:
        return {}
    by_code: dict = {}
    for code, ic in (ItemSupplierLink.objects.filter(supp_code=supp, supp_item_code__in=wanted)
                     .values_list('supp_item_code', 'item_code')):
        by_code.setdefault(code, set()).add(ic)
    return {c: next(iter(s)) for c, s in by_code.items() if len(s) == 1}


def carried_item_ids(supp_code: str, item_ids) -> set:
    """Which of these catalog items this supplier carries (has an itemssuppliers link)."""
    from .models import ItemSupplierLink
    supp = _s(supp_code)
    ids = [i for i in (item_ids or []) if i]
    if not supp or not ids:
        return set()
    return set(ItemSupplierLink.objects.filter(supp_code=supp, item_id__in=ids)
               .values_list('item_id', flat=True))


def link_code(supp_code: str, itemcode: str, code: str) -> None:
    """Keep the mirror current right after a confirmed write to SOFTECH (invoice inject)."""
    from .models import Item, ItemSupplierLink
    supp, ic, code = _s(supp_code), _s(itemcode), _s(code)[:60]
    if not (supp and ic and code):
        return
    iid = Item.objects.filter(softech_id=ic).values_list('id', flat=True).first()
    # the writer keeps code ↔ item 1:1 per supplier (an approved reassignment moved it here)
    ItemSupplierLink.objects.filter(supp_code=supp, supp_item_code=code).exclude(item_code=ic) \
        .update(supp_item_code='')
    ItemSupplierLink.objects.update_or_create(item_code=ic, supp_code=supp,
                                              defaults={'supp_item_code': code, 'item_id': iid})
