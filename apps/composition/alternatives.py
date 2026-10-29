"""
Verified alternatives for the POS (Speed Wave Task 8).

An alternative is another active item whose APPROVED composition (ItemMoleculeIndex rows with
source='approved') has the identical molecule set. Nothing here reads Item.name_scientific or
parser-proposed rows, and nothing is substituted automatically — the POS shows the list and the
pharmacist confirms. Read-only; never touches SOFTECH.
"""
from collections import defaultdict
from decimal import Decimal

from apps.catalog.models import Item
from apps.catalog.pos_search import extract_strength, network_stock, primary_thumbs
from apps.catalog.safety import blocks_sale
from .models import ItemMoleculeIndex

_APPROVED = ItemMoleculeIndex.SOURCE_APPROVED


def _norm(v):
    return None if v is None else Decimal(v).normalize()


def _sig_row(r):
    return ((r.molecule or '').strip().upper(), _norm(r.strength_value),
            (r.strength_unit or '').strip().upper())


def _molecules(sig):
    return frozenset(m for m, _, _ in sig)


def _fmt_sig(sig):
    parts = []
    for m, v, u in sorted(sig, key=lambda s: s[0]):
        parts.append(f'{v:f} {u}'.strip() if v is not None else '')
    return ' / '.join(p for p in parts if p)


def alternatives_for(item_id, *, branch_id=None, limit=20):
    empty = {'verified': False, 'same': [], 'other': []}
    own = list(ItemMoleculeIndex.objects.filter(item_id=item_id))
    if not own or any(r.source != _APPROVED for r in own):
        return empty
    sig = frozenset(_sig_row(r) for r in own)
    mols = _molecules(sig)
    forms = {(r.dosage_form or '').strip().upper() for r in own}

    # candidates: any item sharing at least one approved molecule with the original
    cand_ids = (ItemMoleculeIndex.objects
                .filter(source=_APPROVED, item__is_active=True,
                        molecule__in={r.molecule for r in own})
                .exclude(item_id=item_id).values_list('item_id', flat=True).distinct())
    rows_by_item = defaultdict(list)
    for r in ItemMoleculeIndex.objects.filter(item_id__in=list(cand_ids)):
        rows_by_item[r.item_id].append(r)

    same_ids, other_ids, forms_of = [], [], {}
    for iid, rs in rows_by_item.items():
        if any(r.source != _APPROVED for r in rs):
            continue                                   # any unapproved row disqualifies
        csig = frozenset(_sig_row(r) for r in rs)
        if _molecules(csig) != mols:
            continue                                   # combos need the FULL molecule set
        cform = {(r.dosage_form or '').strip().upper() for r in rs}
        forms_of[iid] = rs[0].dosage_form
        (same_ids if csig == sig and cform == forms else other_ids).append(iid)

    all_ids = same_ids + other_ids
    # archived / sale-stopped items are never offered (pharmacy safety wins)
    items = {i.id: i for i in Item.objects.filter(id__in=all_ids, is_active=True)
             if not blocks_sale(i)}
    stock, thumbs = network_stock(all_ids), primary_thumbs(all_ids)
    try:
        here = int(branch_id) if branch_id else None
    except (TypeError, ValueError):
        here = None

    def build(iid):
        it = items[iid]
        bs = stock.get(iid, [])
        here_qty = sum(b['qty'] for b in bs if b['branch_id'] == here) if here else 0.0
        csig = frozenset(_sig_row(r) for r in rows_by_item[iid])
        return {
            'item_id': it.id, 'softech_id': it.softech_id, 'name': it.name,
            'strength': extract_strength(it.name) or _fmt_sig(csig),
            'dosage_form': forms_of.get(iid, ''),
            'pack_price': float(it.pack_price) if it.pack_price is not None else None,
            'unit_price': float(it.unit_price) if it.unit_price is not None else None,
            'thumb': thumbs.get(iid), 'here_qty': here_qty, 'branch_stock': bs,
            # pass-through so the POS can add the pick as a normal line (same shape as a search row)
            'barcode': it.barcode, 'pack_qty': it.pack_qty, 'unit_name': it.unit_name,
            'batch_required': it.batch_required, 'is_stockable': it.is_stockable,
            'qty_at_branch': here_qty if here else None,
        }

    def ordered(ids):
        out = [build(i) for i in ids if i in items]
        out.sort(key=lambda r: (-r['here_qty'], r['pack_price'] or 0, r['name']))
        return out[:limit]

    return {'verified': True, 'same': ordered(same_ids), 'other': ordered(other_ids)}
