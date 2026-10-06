"""
apps/offers/validation.py — sanity checks that surface CONTRADICTIONS in an offer
config, so setup mistakes are caught before an offer goes live:

  • no matching items (a selector that resolves to nothing)
  • sell-at-loss (بيع بالخسارة): the discount pushes an item below its cost
  • overlap: another active offer targets the same items in an overlapping window
  • priority ambiguity: an overlapping, non-stackable offer shares this priority

Read-only, deterministic. Returns a list of {level, code, msg}.
"""
from decimal import Decimal

from django.db.models import F, ExpressionWrapper, DecimalField

from .targeting import resolve_offer_items

_DEC = DecimalField(max_digits=14, decimal_places=4)
_SAMPLE_CAP = 8000


def _ids(offer):
    if offer.target_all:
        return None
    return set(resolve_offer_items(offer, only_ids=True)[:_SAMPLE_CAP])


def _windows_overlap(a, b):
    a0, a1 = a.starts_at, a.ends_at
    b0, b1 = b.starts_at, b.ends_at
    if a1 and b0 and a1 < b0:
        return False
    if b1 and a0 and b1 < a0:
        return False
    return True


def _loss_count(offer, ids):
    """Items whose post-discount net price would drop below cost (بيع بالخسارة)."""
    from apps.catalog.models import Item
    qs = Item.objects.filter(cost_price__gt=0)
    if ids is not None:
        qs = qs.filter(id__in=ids)
    item_card = getattr(offer, 'authorization_source', 'item_card') == 'item_card'
    if item_card:
        # each item discounted at its own pos_discp
        net = ExpressionWrapper(F('pack_price') * (Decimal('1') - F('pos_discp') / Decimal('100')), output_field=_DEC)
        qs = qs.filter(pos_discp__gt=0)
    else:
        v = Decimal(str(offer.value or 0))
        if v <= 0:
            return 0
        net = ExpressionWrapper(F('pack_price') * (Decimal('1') - v / Decimal('100')), output_field=_DEC)
    return qs.annotate(net=net).filter(cost_price__gt=F('net')).count()


def validate_offer(offer):
    from .models import Offer
    warnings = []
    ids = _ids(offer)

    # 1) no matching items
    if not offer.target_all:
        if not ids:
            warnings.append({'level': 'error', 'code': 'no_items',
                             'msg': 'لا توجد أصناف مطابقة — راجع المحدِّد أو الأصناف المضمّنة.'})
            return warnings   # nothing else to check

    # 2) sell-at-loss
    if offer.offer_type in ('percent', 'fixed', 'bxgy', 'mix_match'):
        loss = _loss_count(offer, ids)
        if loss:
            warnings.append({'level': 'warn', 'code': 'loss',
                             'msg': f'⚠ قد يُباع {loss} صنف بأقل من التكلفة (بيع بالخسارة).'})

    # 3) overlap + priority ambiguity vs other active offers
    others = list(Offer.objects.filter(status='active').exclude(pk=offer.pk)
                  .prefetch_related('items', 'categories', 'tags', 'branches', 'excluded_items')[:60])
    overlaps = []
    for o in others:
        if not _windows_overlap(offer, o):
            continue
        oids = _ids(o)
        shares = (ids is None or oids is None or bool(ids & oids))
        if not shares:
            continue
        name = o.name_ar or o.name
        overlaps.append((o, name))
        if o.priority == offer.priority and not (offer.stackable and o.stackable):
            warnings.append({'level': 'warn', 'code': 'priority',
                             'msg': f'تعارض أولوية: «{name}» يشترك في نفس الأولوية ({offer.priority}) وغير قابل للدمج.'})
    for o, name in overlaps[:5]:
        warnings.append({'level': 'warn', 'code': 'overlap',
                         'msg': f'يتداخل مع «{name}» في الأصناف والتوقيت — تأكد من الأولوية/الدمج.'})

    return warnings
