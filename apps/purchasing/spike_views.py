"""
apps/purchasing/spike_views.py — Demand-spike (📈) review API.

Lists auto-detected spikes and lets a human REVIEW-GATE the order cap: a STRONG
spike is flagged automatically, but المطلوب is cut only for items a human confirms
(spike_confirmed) AND only when the cap is activated for the run. WATCH spikes are
monitor-only and cannot be confirmed. Read + review only; the flag is recomputed
each engine run (apps.purchasing.spike + engine MODULE 10.7).

  GET  candidates/  — flagged spikes (strong+watch) + current stock/المطلوب, filters
  GET  summary/     — counts (strong / watch / confirmed / pending)
  GET  med-types/   — general-classification filter options
  POST confirm/     — human confirms a STRONG spike → cap-eligible
  POST unconfirm/   — revert to monitor-only (no cap)
"""
import logging
from django.conf import settings
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.utils import timezone
from django.db.models import Q

from apps.catalog.models import Item
from apps.purchasing.models import DemandCalculationRun, ItemDemandAggregated
from . import spike as S
from apps.catalog.wildcard import wq

logger = logging.getLogger(__name__)


def _staff(request):
    return getattr(request.user, 'staff_profile', None) or getattr(request.user, 'staffprofile', None)


def _latest_agg(item_ids):
    """{item_id: aggregated_row} from the latest successful run — for stock/المطلوب."""
    run = (DemandCalculationRun.objects.filter(status='success').order_by('-id').first()
           or DemandCalculationRun.objects.order_by('-id').first())
    if run is None:
        return {}
    return {a.item_id: a for a in ItemDemandAggregated.objects.filter(
        run=run, item_id__in=item_ids).only(
        'item_id', 'total_current_stock', 'total_gap', 'total_monthly_avg', 'abc_class')}


def _row(it, agg):
    a = agg.get(it.id)
    stock = float(a.total_current_stock) if a else 0.0
    order = max(0.0, float(a.total_gap)) if a else 0.0           # المطلوب
    ma = float(a.total_monthly_avg) if a else 0.0
    cost = float(it.cost_price or 0)
    recent = it.spike_recent or 0.0
    # what a 1-month cap would order vs current → units the cap would avoid
    capped = min(order, recent * S.CAP_MONTHS)
    return {
        'item_id': it.id, 'code': it.softech_id, 'name': it.name,
        'med_type': it.medicine_type_name_ar or it.medicine_type_name or '',
        'med_type_code': it.medicine_type or '',
        'tier': it.spike_tier, 'ratio': round(it.spike_ratio or 0, 1),
        'recent': round(recent, 1), 'prior': round(it.spike_prior or 0, 2),
        'monthly_avg': round(ma, 1), 'stock': round(stock, 0),
        'order_qty': round(order, 0), 'capped_qty': round(capped, 0),
        'avoided_value': round(max(0.0, order - capped) * cost, 0),
        'abc': (a.abc_class if a else ''), 'cost': cost,
        'confirmed': it.spike_confirmed, 'detected_at': it.spike_detected_at,
    }


_FIELDS = ('id', 'softech_id', 'name', 'medicine_type', 'medicine_type_name_ar',
           'medicine_type_name', 'cost_price', 'spike_tier', 'spike_ratio',
           'spike_recent', 'spike_prior', 'spike_confirmed', 'spike_detected_at')


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def spike_candidates(request):
    qs = Item.objects.filter(is_spike=True)
    tier = request.GET.get('tier')
    if tier in ('strong', 'watch'):
        qs = qs.filter(spike_tier=tier)
    med = request.GET.get('med')
    if med:
        qs = qs.filter(medicine_type=med)
    q = (request.GET.get('q') or '').strip()
    if q:
        qs = qs.filter(wq(q, 'name') | Q(softech_id__icontains=q))
    items = list(qs.only(*_FIELDS))
    agg = _latest_agg([it.id for it in items])
    rows = [_row(it, agg) for it in items]
    rows.sort(key=lambda r: (r['tier'] != 'strong', -r['ratio']))   # strong first, then ratio
    total_avoided = round(sum(r['avoided_value'] for r in rows if r['confirmed']), 0)
    return Response({'count': len(rows), 'confirmed_avoided_value': total_avoided, 'items': rows})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def spike_summary(request):
    flagged = Item.objects.filter(is_spike=True)
    strong = flagged.filter(spike_tier='strong').count()
    confirmed = flagged.filter(spike_tier='strong', spike_confirmed=True).count()
    return Response({
        'flagged': flagged.count(), 'strong': strong, 'watch': flagged.filter(spike_tier='watch').count(),
        'confirmed': confirmed, 'pending_review': strong - confirmed,
        'strong_ratio': S.STRONG_RATIO, 'watch_ratio': S.WATCH_RATIO, 'cap_months': S.CAP_MONTHS,
        'cap_active': bool(getattr(settings, 'CASH_APPLY_SPIKE_CAP', False)),
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def spike_med_types(request):
    seen, opts = set(), []
    for it in Item.objects.filter(is_spike=True).only('medicine_type', 'medicine_type_name_ar', 'medicine_type_name'):
        code = it.medicine_type or ''
        if code and code not in seen:
            seen.add(code); opts.append([code, it.medicine_type_name_ar or it.medicine_type_name or code])
    opts.sort(key=lambda x: x[1])
    return Response({'med_types': opts})


def _get_item(request):
    return Item.objects.filter(id=request.data.get('item_id')).first()


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def spike_confirm(request):
    """Confirm a STRONG spike as an unsustained burst → eligible for the order cap."""
    it = _get_item(request)
    if it is None:
        return Response({'detail': 'item not found'}, status=status.HTTP_404_NOT_FOUND)
    if it.spike_tier != 'strong':
        return Response({'detail': 'يمكن تأكيد الذروة القوية فقط (المراقبة لا تُقلَّل).'},
                        status=status.HTTP_400_BAD_REQUEST)
    it.spike_confirmed = True
    it.spike_reviewed_by = _staff(request)
    it.spike_reviewed_at = timezone.now()
    it.save(update_fields=['spike_confirmed', 'spike_reviewed_by', 'spike_reviewed_at'])
    logger.info('[SPIKE] confirm %s (%s)', it.softech_id, it.name)
    return Response({'ok': True, 'item_id': it.id})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def spike_unconfirm(request):
    """Revert to monitor-only (no cap) — e.g. it's a genuine new-product ramp."""
    it = _get_item(request)
    if it is None:
        return Response({'detail': 'item not found'}, status=status.HTTP_404_NOT_FOUND)
    it.spike_confirmed = False
    it.spike_reviewed_by = _staff(request)
    it.spike_reviewed_at = timezone.now()
    it.save(update_fields=['spike_confirmed', 'spike_reviewed_by', 'spike_reviewed_at'])
    logger.info('[SPIKE] unconfirm %s (%s)', it.softech_id, it.name)
    return Response({'ok': True, 'item_id': it.id})
