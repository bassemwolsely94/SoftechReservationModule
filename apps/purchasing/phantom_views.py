"""
apps/purchasing/phantom_views.py — Phantom substitution (مبيعات وهمية) review API.

Read + human-review over the auto-detected flag (apps.purchasing.phantom):
  GET  candidates/   — flagged items (is_phantom_substitution=True) + metrics, filters
  GET  excluded/     — items a human marked "ليست مبيعات وهمية" (override='excluded')
  GET  summary/      — counts + med-type filter options + total order-reduction value
  GET  med-types/    — general-classification options for the filter
  POST confirm/      — human confirms it IS phantom (sticky: override='confirmed')
  POST exclude/      — human says NOT phantom (override='excluded', +note) → unflag
  POST reset/        — clear the override → back to auto (recompute from current ratio)

The flag itself is set by the detector each engine run; these endpoints only let a
human confirm/override it. No SOFTECH writes, no replenishment-math change.
"""
import logging
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.utils import timezone

from apps.catalog.models import Item
from . import phantom as P
from apps.catalog.wildcard import wq

logger = logging.getLogger(__name__)


def _staff(request):
    return getattr(request.user, 'staff_profile', None) or getattr(request.user, 'staffprofile', None)


def _row(it):
    return {
        'item_id': it.id, 'code': it.softech_id, 'name': it.name,
        'med_type': it.medicine_type_name_ar or it.medicine_type_name or '',
        'med_type_code': it.medicine_type or '',
        'unit_price': float(it.pack_price or 0), 'cost': float(it.cost_price or 0),
        'phantom_ratio': round(it.phantom_ratio or 0, 4),
        'contract_ratio': round(it.phantom_contract_ratio or 0, 4),
        'order_pct': round(it.phantom_order_pct if it.phantom_order_pct is not None else 1.0, 4),
        'buyback_qty': float(it.phantom_buyback_qty or 0),
        'sold_qty': float(it.phantom_sold_qty or 0),
        'genuine_need': float(it.phantom_genuine_need or 0),
        'tier': P.classify(it.phantom_ratio or 0, float(it.phantom_sold_qty or 0),
                           float(it.phantom_buyback_qty or 0)) or 'strong',
        'override': it.phantom_override, 'override_note': it.phantom_override_note,
        'reviewed': bool(it.phantom_override),
        'in_shortage': it.in_shortage,            # overlap with نواقص السوق
        'detected_at': it.phantom_detected_at,
    }


def _apply_filters(qs, request):
    med = request.GET.get('med')
    q = (request.GET.get('q') or '').strip()
    if med:
        qs = qs.filter(medicine_type=med)
    if q:
        from django.db.models import Q
        qs = qs.filter(wq(q, 'name') | Q(softech_id__icontains=q))
    return qs


_FIELDS = ('id', 'softech_id', 'name', 'medicine_type', 'medicine_type_name_ar',
           'medicine_type_name', 'pack_price', 'cost_price', 'phantom_ratio',
           'phantom_contract_ratio', 'phantom_order_pct', 'phantom_buyback_qty',
           'phantom_sold_qty', 'phantom_genuine_need', 'phantom_override',
           'phantom_override_note', 'in_shortage', 'phantom_detected_at')


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def phantom_candidates(request):
    qs = _apply_filters(Item.objects.filter(is_phantom_substitution=True), request).only(*_FIELDS)
    rows = [_row(it) for it in qs]
    rows.sort(key=lambda r: r['buyback_qty'] * r['cost'], reverse=True)   # by over-order value
    total_reduction = round(sum(r['buyback_qty'] * r['cost'] for r in rows), 2)
    return Response({'count': len(rows), 'total_order_reduction_value': total_reduction,
                     'items': rows})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def phantom_excluded(request):
    qs = _apply_filters(Item.objects.filter(phantom_override='excluded'), request).only(*_FIELDS)
    rows = [_row(it) for it in qs]
    rows.sort(key=lambda r: r['sold_qty'], reverse=True)
    return Response({'count': len(rows), 'items': rows})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def phantom_summary(request):
    flagged = Item.objects.filter(is_phantom_substitution=True)
    confirmed = flagged.filter(phantom_override='confirmed').count()
    pending = flagged.filter(phantom_override='').count()
    excluded = Item.objects.filter(phantom_override='excluded').count()
    strong = flagged.filter(phantom_ratio__gte=P.THRESHOLD).count()
    total = flagged.count()
    return Response({
        'flagged': total, 'strong': strong, 'watch': total - strong,
        'confirmed': confirmed, 'pending_review': pending, 'excluded': excluded,
        'threshold': P.THRESHOLD, 'watch_threshold': P.WATCH_THRESHOLD,
        'watch_min_buyback': P.WATCH_MIN_BUYBACK, 'window_months': P.FLAG_MONTHS,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def phantom_med_types(request):
    seen, opts = set(), []
    for it in (Item.objects.filter(is_phantom_substitution=True)
               .only('medicine_type', 'medicine_type_name_ar', 'medicine_type_name')):
        code = it.medicine_type or ''
        if code and code not in seen:
            seen.add(code)
            opts.append([code, it.medicine_type_name_ar or it.medicine_type_name or code])
    opts.sort(key=lambda x: x[1])
    return Response({'med_types': opts})


def _get_item(request):
    return Item.objects.filter(id=request.data.get('item_id')).first()


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def phantom_confirm(request):
    """Human confirms it IS phantom — sticky flag that survives ratio dips."""
    it = _get_item(request)
    if it is None:
        return Response({'detail': 'item not found'}, status=status.HTTP_404_NOT_FOUND)
    it.phantom_override = 'confirmed'
    it.is_phantom_substitution = True
    it.phantom_override_note = (request.data.get('note') or '')[:300]
    it.phantom_reviewed_by = _staff(request)
    it.phantom_reviewed_at = timezone.now()
    it.save(update_fields=['phantom_override', 'is_phantom_substitution',
                           'phantom_override_note', 'phantom_reviewed_by', 'phantom_reviewed_at'])
    logger.info('[PHANTOM] confirm %s (%s)', it.softech_id, it.name)
    return Response({'ok': True, 'item_id': it.id})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def phantom_exclude(request):
    """Human marks NOT phantom → unflag and keep it off the list (override='excluded')."""
    it = _get_item(request)
    if it is None:
        return Response({'detail': 'item not found'}, status=status.HTTP_404_NOT_FOUND)
    it.phantom_override = 'excluded'
    it.is_phantom_substitution = False
    it.phantom_override_note = (request.data.get('note') or '')[:300]
    it.phantom_reviewed_by = _staff(request)
    it.phantom_reviewed_at = timezone.now()
    it.save(update_fields=['phantom_override', 'is_phantom_substitution',
                           'phantom_override_note', 'phantom_reviewed_by', 'phantom_reviewed_at'])
    logger.info('[PHANTOM] exclude %s (%s)', it.softech_id, it.name)
    return Response({'ok': True, 'item_id': it.id})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def phantom_reset(request):
    """Clear a human override → back to auto; recompute the flag from the current ratio."""
    it = _get_item(request)
    if it is None:
        return Response({'detail': 'item not found'}, status=status.HTTP_404_NOT_FOUND)
    it.phantom_override = ''
    it.phantom_override_note = ''
    it.is_phantom_substitution = bool(
        P.classify(it.phantom_ratio or 0, float(it.phantom_sold_qty or 0),
                   float(it.phantom_buyback_qty or 0)) and it.is_stockable)
    it.phantom_reviewed_by = _staff(request)
    it.phantom_reviewed_at = timezone.now()
    it.save(update_fields=['phantom_override', 'phantom_override_note',
                           'is_phantom_substitution', 'phantom_reviewed_by', 'phantom_reviewed_at'])
    logger.info('[PHANTOM] reset %s → auto (flag=%s)', it.softech_id, it.is_phantom_substitution)
    return Response({'ok': True, 'item_id': it.id, 'is_phantom_substitution': it.is_phantom_substitution})
