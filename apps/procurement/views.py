"""
apps/procurement/views.py

Procurement Intelligence Platform — API views.

All endpoints are read-only analytics except:
  - POST /trigger/          → trigger engine run (admin only)
  - PATCH /alerts/{id}/resolve/  → resolve alert
"""
import threading
import datetime as _dt
from decimal import Decimal

from django.utils import timezone
from django.db.models import (
    Sum, Count, Avg, Min, Max, Q, F, OuterRef, Subquery,
)
from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.response import Response

from .models import (
    PurchaseLine, SupplierProfile, SupplierItemMapping,
    ProcurementEngineRun, ProcurementSnapshot, BuyerPerformance,
    ProcurementAlert, SupplierSegmentation,
    SupplierCategory, SupplierClassificationRule,
)
from .serializers import (
    PurchaseLineSerializer,
    SupplierProfileSerializer, SupplierProfileListSerializer,
    SupplierItemMappingSerializer,
    ProcurementEngineRunSerializer,
    ProcurementSnapshotSerializer,
    BuyerPerformanceSerializer,
    ProcurementAlertSerializer, ProcurementAlertResolveSerializer,
    SupplierSegmentationSerializer,
    PurchaseLineEnhancedSerializer,
    SupplierProfileEnhancedSerializer,
    SupplierCategorySerializer, SupplierClassificationRuleSerializer,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _d(val, default=Decimal('0')):
    """Safe Decimal conversion."""
    try:
        return Decimal(str(val)) if val is not None else default
    except Exception:
        return default


def _latest_run():
    return ProcurementEngineRun.objects.filter(status='success').order_by('-started_at').first()


def _parse_int(request, param, default):
    try:
        return int(request.query_params.get(param, default))
    except (TypeError, ValueError):
        return default


# ── Module 1: Purchasing Overview ─────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def procurement_overview(request):
    """
    KPI overview cards: latest snapshot + trend data.
    """
    snap = ProcurementSnapshot.objects.order_by('-snapshot_date').first()
    if not snap:
        return Response({'detail': 'No snapshot available. Run the engine first.'}, status=404)

    snap_data = ProcurementSnapshotSerializer(snap).data

    # Monthly trend (last 13 months for MoM chart)
    today = timezone.now().date()
    trend = []
    for i in range(12, -1, -1):
        month_start = (today.replace(day=1) - _dt.timedelta(days=i * 30)).replace(day=1)
        if i > 0:
            month_end = (today.replace(day=1) - _dt.timedelta(days=(i - 1) * 30)).replace(day=1)
        else:
            # current month — include through today
            next_month = (today.replace(day=28) + _dt.timedelta(days=4)).replace(day=1)
            month_end = next_month
        agg = apply_dimension_filters(
            PurchaseLine.objects.filter(doc_date__gte=month_start, doc_date__lt=month_end),
            request.query_params,
        ).aggregate(
            net_val=Sum('net_value'),
            net_qty=Sum('net_qty'),
            invs=Count('doc_number', distinct=True),
            items=Count('item_code', distinct=True),
        )
        trend.append({
            'month': month_start.strftime('%Y-%m'),
            'net_value':     float(agg['net_val'] or 0),
            'net_qty':       float(agg['net_qty'] or 0),
            'invoice_count': agg['invs'] or 0,
            'item_count':    agg['items'] or 0,
        })

    return Response({
        'snapshot': snap_data,
        'monthly_trend': trend,
    })


# ── Module 2: Supplier Performance ───────────────────────────────────────────

class SupplierPerformanceListView(generics.ListAPIView):
    """
    List all supplier profiles with computed performance metrics.
    Supports: search, ordering, filter by classif_code / score range.
    """
    permission_classes = [IsAuthenticated]
    serializer_class   = SupplierProfileListSerializer

    def get_queryset(self):
        qs = SupplierProfile.objects.all()
        q = self.request.query_params.get('q', '').strip()
        if q:
            qs = qs.filter(
                Q(supplier_name__icontains=q) | Q(supplier_code__icontains=q)
            )
        classif = self.request.query_params.get('classif', '').strip()
        if classif:
            qs = qs.filter(classif_code=classif)
        min_score = self.request.query_params.get('min_score')
        if min_score:
            qs = qs.filter(total_score__gte=min_score)
        ordering = self.request.query_params.get('ordering', '-total_score')
        allowed = {
            'total_score', '-total_score',
            'net_purchase_value', '-net_purchase_value',
            'avg_margin_pct', '-avg_margin_pct',
            'return_pct', '-return_pct',
            'value_30d', '-value_30d',
        }
        if ordering in allowed:
            qs = qs.order_by(ordering)
        return qs


class SupplierPerformanceDetailView(generics.RetrieveAPIView):
    """Full supplier profile including all scoring details."""
    permission_classes = [IsAuthenticated]
    serializer_class   = SupplierProfileSerializer
    queryset           = SupplierProfile.objects.all()
    lookup_field       = 'supplier_code'


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def supplier_purchase_history(request, supplier_code):
    """
    Monthly purchase history for a specific supplier (last 12 months).
    """
    today = timezone.now().date()
    lines = PurchaseLine.objects.filter(
        supplier_code=supplier_code,
        doc_date__gte=today - _dt.timedelta(days=365),
    )

    monthly = {}
    for line in lines.values('doc_date', 'net_value', 'net_qty', 'is_return', 'doc_number', 'item_code'):
        key = line['doc_date'].strftime('%Y-%m') if hasattr(line['doc_date'], 'strftime') else str(line['doc_date'])[:7]
        if key not in monthly:
            monthly[key] = {'month': key, 'purchase_value': 0, 'return_value': 0, 'net_qty': 0, 'invoices': set(), 'items': set()}
        if line['is_return']:
            monthly[key]['return_value'] += float(line['net_value'])
        else:
            monthly[key]['purchase_value'] += float(line['net_value'])
        monthly[key]['net_qty']  += float(line['net_qty'])
        monthly[key]['invoices'].add(line['doc_number'])
        monthly[key]['items'].add(line['item_code'])

    result = []
    for k in sorted(monthly.keys()):
        m = monthly[k]
        result.append({
            'month':          k,
            'purchase_value': round(m['purchase_value'], 2),
            'return_value':   abs(round(m['return_value'], 2)),
            'net_value':      round(m['purchase_value'] + m['return_value'], 2),
            'net_qty':        round(m['net_qty'], 2),
            'invoice_count':  len(m['invoices']),
            'item_count':     len(m['items']),
        })

    sp = SupplierProfile.objects.filter(supplier_code=supplier_code).first()
    return Response({
        'supplier': SupplierProfileSerializer(sp).data if sp else None,
        'history':  result,
    })


# ── Module 3 + 4: Item Procurement + Supplier-Item Matrix ─────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def item_procurement_analysis(request, item_code):
    """
    Per-item procurement analysis: all suppliers, price history, best supplier.
    """
    days = _parse_int(request, 'days', 365)
    today = timezone.now().date()
    since = today - _dt.timedelta(days=days)

    mappings = SupplierItemMapping.objects.filter(item_code=item_code).order_by('-confidence_score')
    lines = PurchaseLine.objects.filter(
        item_code=item_code, doc_date__gte=since,
    ).order_by('doc_date').values(
        'doc_date', 'supplier_code', 'unit_price', 'net_qty', 'net_value', 'is_return'
    )

    price_history = []
    for line in lines:
        price_history.append({
            'date':          str(line['doc_date']),
            'supplier_code': line['supplier_code'],
            'unit_price':    float(line['unit_price']),
            'net_qty':       float(line['net_qty']),
            'net_value':     float(line['net_value']),
            'is_return':     line['is_return'],
        })

    return Response({
        'item_code':     item_code,
        'supplier_mappings': SupplierItemMappingSerializer(mappings, many=True).data,
        'price_history': price_history,
    })


class SupplierItemMappingListView(generics.ListAPIView):
    """
    Full supplier-item mapping table (Module 4 — OCR learning table).
    """
    permission_classes = [IsAuthenticated]
    serializer_class   = SupplierItemMappingSerializer

    def get_queryset(self):
        qs = SupplierItemMapping.objects.all()
        q = self.request.query_params.get('q', '').strip()
        if q:
            qs = qs.filter(
                Q(item_name__icontains=q) | Q(item_code__icontains=q)
                | Q(supplier_name__icontains=q) | Q(supplier_code__icontains=q)
            )
        supplier_code = self.request.query_params.get('supplier_code', '').strip()
        if supplier_code:
            qs = qs.filter(supplier_code=supplier_code)
        item_code = self.request.query_params.get('item_code', '').strip()
        if item_code:
            qs = qs.filter(item_code=item_code)
        primary_only = self.request.query_params.get('primary_only', '').strip().lower()
        if primary_only in ('1', 'true', 'yes'):
            qs = qs.filter(is_primary=True)
        min_confidence = self.request.query_params.get('min_confidence')
        if min_confidence:
            qs = qs.filter(confidence_score__gte=min_confidence)
        ordering = self.request.query_params.get('ordering', '-purchase_count')
        allowed = {
            'purchase_count', '-purchase_count',
            'confidence_score', '-confidence_score',
            'last_purchase_date', '-last_purchase_date',
            'price_drift_pct', '-price_drift_pct',
        }
        if ordering in allowed:
            qs = qs.order_by(ordering)
        return qs


# ── Module 5: Purchase Margin Engine ──────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def margin_analysis(request):
    """
    Margin breakdown: by supplier, by item, distribution histogram.
    """
    days = _parse_int(request, 'days', 90)
    today = timezone.now().date()
    since = today - _dt.timedelta(days=days)

    base_qs = PurchaseLine.objects.filter(doc_date__gte=since, is_return=False)

    # By supplier
    by_supplier = list(
        base_qs.values('supplier_code')
        .annotate(
            avg_margin=Avg('margin_pct'),
            net_value=Sum('net_value'),
            item_count=Count('item_code', distinct=True),
        )
        .order_by('avg_margin')[:30]
    )

    # By item (bottom margins)
    by_item = list(
        base_qs.values('item_code')
        .annotate(avg_margin=Avg('margin_pct'), net_value=Sum('net_value'))
        .order_by('avg_margin')[:20]
    )

    # Histogram buckets
    buckets = [
        ('<0%',    base_qs.filter(margin_pct__lt=0).aggregate(c=Count('id'))['c'] or 0),
        ('0-10%',  base_qs.filter(margin_pct__gte=0,  margin_pct__lt=10).aggregate(c=Count('id'))['c'] or 0),
        ('10-20%', base_qs.filter(margin_pct__gte=10, margin_pct__lt=20).aggregate(c=Count('id'))['c'] or 0),
        ('20-30%', base_qs.filter(margin_pct__gte=20, margin_pct__lt=30).aggregate(c=Count('id'))['c'] or 0),
        ('30-40%', base_qs.filter(margin_pct__gte=30, margin_pct__lt=40).aggregate(c=Count('id'))['c'] or 0),
        ('>40%',   base_qs.filter(margin_pct__gte=40).aggregate(c=Count('id'))['c'] or 0),
    ]

    overall = base_qs.aggregate(
        avg_margin=Avg('margin_pct'),
        net_value=Sum('net_value'),
        line_count=Count('id'),
    )

    return Response({
        'period_days':  days,
        'overall':      {k: float(v) if v else 0 for k, v in overall.items()},
        'by_supplier': [
            {
                'supplier_code': r['supplier_code'],
                'avg_margin':    round(float(r['avg_margin'] or 0), 2),
                'net_value':     round(float(r['net_value'] or 0), 2),
                'item_count':    r['item_count'],
            }
            for r in by_supplier
        ],
        'by_item': [
            {
                'item_code':  r['item_code'],
                'avg_margin': round(float(r['avg_margin'] or 0), 2),
                'net_value':  round(float(r['net_value'] or 0), 2),
            }
            for r in by_item
        ],
        'histogram': [{'range': b[0], 'count': b[1]} for b in buckets],
    })


# ── Module 6: Supplier Return Engine ──────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def return_analysis(request):
    """
    Supplier return analysis: return rate, top returners, return trend.
    """
    days = _parse_int(request, 'days', 90)
    today = timezone.now().date()
    since = today - _dt.timedelta(days=days)

    top_returners = list(
        SupplierProfile.objects.filter(
            invoice_count__gte=2, return_pct__gt=0
        ).order_by('-return_pct')[:20].values(
            'supplier_code', 'supplier_name', 'return_pct',
            'net_return_value', 'net_purchase_value', 'invoice_count'
        )
    )

    # Return trend monthly
    returns_monthly = {}
    for line in PurchaseLine.objects.filter(doc_date__gte=since, is_return=True).values('doc_date', 'net_value'):
        key = str(line['doc_date'])[:7]
        returns_monthly[key] = returns_monthly.get(key, 0) + float(line['net_value'])

    return Response({
        'period_days':   days,
        'top_returners': [
            {**r, 'return_pct': float(r['return_pct']),
             'net_return_value': float(r['net_return_value']),
             'net_purchase_value': float(r['net_purchase_value'])}
            for r in top_returners
        ],
        'return_trend': [
            {'month': k, 'return_value': abs(round(v, 2))}
            for k, v in sorted(returns_monthly.items())
        ],
    })


# ── Module 8: Price Control Engine ───────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def price_control(request):
    """
    Price drift alerts and price variance analysis.
    """
    min_drift = _parse_int(request, 'min_drift', 10)
    min_purchases = _parse_int(request, 'min_purchases', 3)

    drifters = SupplierItemMapping.objects.filter(
        price_drift_pct__gte=min_drift,
        purchase_count__gte=min_purchases,
    ).order_by('-price_drift_pct')[:50]

    return Response({
        'min_drift_threshold': min_drift,
        'items':               SupplierItemMappingSerializer(drifters, many=True).data,
    })


# ── Module 9: Procurement Optimization ───────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def procurement_optimization(request):
    """
    Buy/avoid recommendations: best suppliers per item, underperformers.
    """
    days = _parse_int(request, 'days', 90)
    today = timezone.now().date()
    since = today - _dt.timedelta(days=days)

    # Best-value suppliers (high score, low return, high margin)
    top_suppliers = SupplierProfile.objects.filter(
        total_score__gte=60, last_purchase_date__gte=today - _dt.timedelta(days=90)
    ).order_by('-total_score')[:10]

    # Items with multiple suppliers — price saving opportunity
    multi_supplier_items = list(
        SupplierItemMapping.objects.values('item_code', 'item_name')
        .annotate(
            supplier_count=Count('supplier_code', distinct=True),
            min_avg_price=Min('avg_price'),
            max_avg_price=Max('avg_price'),
        )
        .filter(supplier_count__gte=2, min_avg_price__gt=0)
        .annotate(
            saving_pct=((F('max_avg_price') - F('min_avg_price')) / F('min_avg_price') * 100)
        )
        .order_by('-saving_pct')[:20]
        .values('item_code', 'item_name', 'supplier_count', 'min_avg_price', 'max_avg_price', 'saving_pct')
    )

    # Suppliers to avoid (high return rate + low score)
    avoid = SupplierProfile.objects.filter(
        return_pct__gt=20, total_score__lt=40, invoice_count__gte=3,
    ).order_by('total_score')[:10]

    return Response({
        'period_days':    days,
        'top_suppliers':  SupplierProfileListSerializer(top_suppliers, many=True).data,
        'avoid_suppliers': SupplierProfileListSerializer(avoid, many=True).data,
        'price_saving_items': [
            {
                'item_code':      r['item_code'],
                'item_name':      r['item_name'],
                'supplier_count': r['supplier_count'],
                'min_price':      round(float(r['min_avg_price']), 4),
                'max_price':      round(float(r['max_avg_price']), 4),
                'saving_pct':     round(float(r['saving_pct'] or 0), 1),
            }
            for r in multi_supplier_items
        ],
    })


# ── Module 10: Buyer Performance ──────────────────────────────────────────────

class BuyerPerformanceListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class   = BuyerPerformanceSerializer

    def get_queryset(self):
        # Latest period only
        latest = BuyerPerformance.objects.order_by('-period_end').values('period_end').first()
        if not latest:
            return BuyerPerformance.objects.none()
        qs = BuyerPerformance.objects.filter(period_end=latest['period_end'])
        ordering = self.request.query_params.get('ordering', '-procurement_score')
        allowed = {
            'procurement_score', '-procurement_score',
            'net_purchase_value', '-net_purchase_value',
            'avg_margin_pct', '-avg_margin_pct',
            'return_pct', '-return_pct',
        }
        if ordering in allowed:
            qs = qs.order_by(ordering)
        return qs


# ── Module 11: Branch Procurement ────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def branch_procurement(request):
    """
    Branch-level procurement KPIs.
    """
    days = _parse_int(request, 'days', 90)
    today = timezone.now().date()
    since = today - _dt.timedelta(days=days)

    branches = list(
        PurchaseLine.objects.filter(doc_date__gte=since)
        .values('branch_code')
        .annotate(
            net_value=Sum('net_value'),
            net_qty=Sum('net_qty'),
            purchase_value=Sum('net_value', filter=Q(is_return=False)),
            return_value=Sum('net_value', filter=Q(is_return=True)),
            invoice_count=Count('doc_number', distinct=True),
            item_count=Count('item_code', distinct=True),
            supplier_count=Count('supplier_code', distinct=True),
            avg_margin=Avg('margin_pct', filter=Q(is_return=False)),
        )
        .order_by('-net_value')
    )

    total_val = sum(float(b['net_value'] or 0) for b in branches)
    result = []
    for b in branches:
        pv = float(b['purchase_value'] or 0)
        rv = abs(float(b['return_value'] or 0))
        result.append({
            'branch_code':     b['branch_code'],
            'net_value':       round(float(b['net_value'] or 0), 2),
            'purchase_value':  round(pv, 2),
            'return_value':    round(rv, 2),
            'return_pct':      round(rv / pv * 100, 2) if pv > 0 else 0,
            'invoice_count':   b['invoice_count'],
            'item_count':      b['item_count'],
            'supplier_count':  b['supplier_count'],
            'avg_margin_pct':  round(float(b['avg_margin'] or 0), 2),
            'pct_of_total':    round(float(b['net_value'] or 0) / total_val * 100, 2) if total_val > 0 else 0,
        })

    return Response({'period_days': days, 'branches': result})


# ── Purchase Lines: filtered list ─────────────────────────────────────────────

class PurchaseLineListView(generics.ListAPIView):
    """
    Raw purchase lines with filtering. Used for drill-down.
    """
    permission_classes = [IsAuthenticated]
    serializer_class   = PurchaseLineSerializer
    # This view does its own filtering + ordering and caps the queryset with a
    # slice. The global DRF filter backends (OrderingFilter) would call
    # .order_by() on the already-sliced queryset → "Cannot reorder a query once
    # a slice has been taken". Disable them and skip pagination so the slice
    # stands and the response is a plain JSON array.
    filter_backends    = []
    pagination_class   = None

    def get_queryset(self):
        qs = PurchaseLine.objects.select_related('item', 'branch')
        supplier = self.request.query_params.get('supplier_code', '').strip()
        if supplier:
            qs = qs.filter(supplier_code=supplier)
        item = self.request.query_params.get('item_code', '').strip()
        if item:
            qs = qs.filter(item_code=item)
        branch = self.request.query_params.get('branch_code', '').strip()
        if branch:
            qs = qs.filter(branch_code=branch)
        buyer = self.request.query_params.get('buyer_code', '').strip()
        if buyer:
            qs = qs.filter(buyer_code=buyer)
        is_return = self.request.query_params.get('is_return', '').strip().lower()
        if is_return == 'true':
            qs = qs.filter(is_return=True)
        elif is_return == 'false':
            qs = qs.filter(is_return=False)
        date_from = self.request.query_params.get('date_from', '').strip()
        date_to   = self.request.query_params.get('date_to', '').strip()
        if date_from:
            qs = qs.filter(doc_date__gte=date_from)
        if date_to:
            qs = qs.filter(doc_date__lte=date_to)
        ordering = self.request.query_params.get('ordering', '-doc_date')
        allowed = {'doc_date', '-doc_date', 'net_value', '-net_value', 'margin_pct', '-margin_pct'}
        if ordering in allowed:
            qs = qs.order_by(ordering)
        return qs[:500]  # cap at 500 lines per request


# ── Engine Runs ───────────────────────────────────────────────────────────────

class EngineRunListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class   = ProcurementEngineRunSerializer
    queryset           = ProcurementEngineRun.objects.all()[:30]


@api_view(['POST'])
@permission_classes([IsAdminUser])
def trigger_engine(request):
    """
    Trigger a new procurement engine run in a background thread.
    Only admin users.
    """
    from .engine import run_procurement_engine

    days = _parse_int(request, 'days', 365)
    triggered_by = str(request.user)

    def _run():
        run_procurement_engine(lookback_days=days, triggered_by=triggered_by)

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    return Response({
        'detail':  'Procurement engine started.',
        'days':    days,
        'user':    triggered_by,
    }, status=status.HTTP_202_ACCEPTED)


# ── Alerts ────────────────────────────────────────────────────────────────────

class AlertListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class   = ProcurementAlertSerializer

    def get_queryset(self):
        qs = ProcurementAlert.objects.all()
        severity = self.request.query_params.get('severity', '').strip()
        if severity:
            qs = qs.filter(severity=severity)
        alert_type = self.request.query_params.get('alert_type', '').strip()
        if alert_type:
            qs = qs.filter(alert_type=alert_type)
        is_resolved = self.request.query_params.get('is_resolved', '').strip().lower()
        if is_resolved == 'true':
            qs = qs.filter(is_resolved=True)
        elif is_resolved == 'false':
            qs = qs.filter(is_resolved=False)
        entity_type = self.request.query_params.get('entity_type', '').strip()
        if entity_type:
            qs = qs.filter(entity_type=entity_type)
        return qs[:200]


@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def resolve_alert(request, pk):
    """Mark an alert as resolved."""
    try:
        alert = ProcurementAlert.objects.get(pk=pk)
    except ProcurementAlert.DoesNotExist:
        return Response({'detail': 'Alert not found.'}, status=404)

    if alert.is_resolved:
        return Response({'detail': 'Alert already resolved.'}, status=400)

    serializer = ProcurementAlertResolveSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    alert.is_resolved     = True
    alert.resolved_at     = timezone.now()
    alert.resolved_by     = serializer.validated_data['resolved_by']
    alert.resolution_notes = serializer.validated_data.get('resolution_notes', '')
    alert.save(update_fields=['is_resolved', 'resolved_at', 'resolved_by', 'resolution_notes'])

    return Response(ProcurementAlertSerializer(alert).data)


# ── Snapshot history ──────────────────────────────────────────────────────────

class SnapshotListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class   = ProcurementSnapshotSerializer
    queryset           = ProcurementSnapshot.objects.all()[:90]


# ── v3: shared purchase-history filter helper ─────────────────────────────────

def _hist_list(params, key):
    """Split a comma-separated multi-value param into a clean list, or None."""
    raw = params.get(key)
    if not raw:
        return None
    vals = [v.strip() for v in str(raw).split(',') if v.strip()]
    return vals or None


def _hist_num(params, key):
    try:
        return float(params.get(key))
    except (TypeError, ValueError):
        return None


def _parse_date(s):
    try:
        return _dt.datetime.strptime(str(s).strip()[:10], '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return None


def resolve_period(params):
    """
    Resolve the active date window from the shared filter bar, returning
    (since, until) inclusive dates.  Priority:
      explicit date_from/date_to  >  period preset  >  legacy `days`  >  90d.
    Presets mirror the narrative-reports selector: today / week / month(mtd) /
    quarter / year / all.
    """
    today = timezone.now().date()
    df, dtt = params.get('date_from', '').strip(), params.get('date_to', '').strip()
    if df or dtt:
        return (_parse_date(df) or (today - _dt.timedelta(days=3650)),
                _parse_date(dtt) or today)

    period = params.get('period', '').strip().lower()
    if period in ('today', 'day'):
        return today, today
    if period == 'yesterday':
        y = today - _dt.timedelta(days=1); return y, y
    if period == 'week':
        return today - _dt.timedelta(days=6), today
    if period in ('month', 'mtd'):
        return today.replace(day=1), today
    if period == 'quarter':
        qm = today.month - ((today.month - 1) % 3)
        return today.replace(month=qm, day=1), today
    if period in ('year', 'ytd'):
        return today.replace(month=1, day=1), today
    if period == 'all':
        return today - _dt.timedelta(days=3650), today

    try:
        days = int(params.get('days'))
    except (TypeError, ValueError):
        days = 0
    if days:
        return today - _dt.timedelta(days=days), today
    return today - _dt.timedelta(days=90), today


def apply_dimension_filters(qs, p):
    """
    Shared, page-agnostic slicing dimensions used by the global filter bar:
      branch (multi), supplier_category (multi), item attributes (multi),
      item_level, is_imported, supplier_code.  NO date filter (see resolve_period).
    """
    branches = _hist_list(p, 'branch') or _hist_list(p, 'branch_code')
    if branches:
        qs = qs.filter(branch_code__in=branches)

    cats = _hist_list(p, 'supplier_category')
    if cats:
        qs = qs.filter(supplier_category__in=cats)

    for key, field in _HIST_ITEM_FIELDS.items():
        vals = _hist_list(p, key)
        if vals:
            qs = qs.filter(**{f'{field}__in': vals})

    levels = _hist_list(p, 'item_level')
    if levels:
        try:
            qs = qs.filter(item__item_level__in=[int(x) for x in levels])
        except (ValueError, TypeError):
            pass

    imported = p.get('is_imported', '').strip()
    if imported == '1':
        qs = qs.filter(item__is_imported=True)
    elif imported == '0':
        qs = qs.filter(item__is_imported=False)

    supplier = p.get('supplier_code', '').strip()
    if supplier:
        qs = qs.filter(supplier_code=supplier)

    return qs


def apply_common_filters(qs, p, date_field='doc_date'):
    """Date window (resolve_period) + all shared slicing dimensions."""
    since, until = resolve_period(p)
    qs = qs.filter(**{f'{date_field}__gte': since, f'{date_field}__lte': until})
    return apply_dimension_filters(qs, p)


# Multi-select item-attribute filters (param → PurchaseLine field via item FK).
# Labels mirror the SOFTECH item card, matching the /purchasing filter set.
_HIST_ITEM_FIELDS = {
    'medicine_type':  'item__medicine_type',   # تصنيف عام
    'shape_code':     'item__shape_code',       # الشكل الدوائى
    'effect_code':    'item__effect_code',      # الاستخدام
    'origin_code':    'item__origin_code',      # المنشأ
    'producer_code':  'item__producer_code',    # الشركة المنتجة
    'family_code':    'item__family_code',      # العائلة
}


def apply_history_filters(qs, p):
    """
    Apply every purchase-history filter to `qs` (unordered, unsliced).
    Shared by the list view, the summary endpoint, and any export so the three
    always agree on what "matches".
    """
    supplier   = p.get('supplier_code', '').strip()
    item       = p.get('item_code', '').strip()
    buyer      = p.get('buyer_code', '').strip()
    q          = p.get('q', '').strip()
    return_type = p.get('return_type', '').strip()

    # Date window from the shared bar (period / custom range / days), same as
    # every analytics endpoint.
    since, until = resolve_period(p)
    qs = qs.filter(doc_date__gte=since, doc_date__lte=until)

    if supplier:
        qs = qs.filter(supplier_code=supplier)
    if item:
        qs = qs.filter(item_code=item)
    branches = _hist_list(p, 'branch') or _hist_list(p, 'branch_code')
    if branches:
        qs = qs.filter(branch_code__in=branches)
    if buyer:
        qs = qs.filter(buyer_code=buyer)
    if q:
        qs = qs.filter(
            Q(item_code__icontains=q)
            | Q(supplier_code__icontains=q)
            | Q(doc_number__icontains=q)
            | Q(buyer_code__icontains=q)
            | Q(item__name__icontains=q)
        )

    is_return_p = p.get('is_return', '').strip().lower()
    if is_return_p in ('true', '1'):
        qs = qs.filter(is_return=True)
    elif is_return_p in ('false', '0'):
        qs = qs.filter(is_return=False)

    is_foc_p = p.get('is_foc', '').strip().lower()
    if is_foc_p in ('true', '1'):
        qs = qs.filter(is_foc=True)
    elif is_foc_p in ('false', '0'):
        qs = qs.filter(is_foc=False)

    if return_type:
        qs = qs.filter(return_type=return_type)

    # Supplier category — now multi-select (comma list) with single-value fallback
    cats = _hist_list(p, 'supplier_category')
    if cats:
        qs = qs.filter(supplier_category__in=cats)

    # Item-attribute multi-select filters (SOFTECH dimensions)
    for key, field in _HIST_ITEM_FIELDS.items():
        vals = _hist_list(p, key)
        if vals:
            qs = qs.filter(**{f'{field}__in': vals})

    levels = _hist_list(p, 'item_level')
    if levels:
        try:
            qs = qs.filter(item__item_level__in=[int(x) for x in levels])
        except (ValueError, TypeError):
            pass

    imported = p.get('is_imported', '').strip()
    if imported == '1':
        qs = qs.filter(item__is_imported=True)
    elif imported == '0':
        qs = qs.filter(item__is_imported=False)

    # Numeric ranges
    mm_min, mm_max = _hist_num(p, 'margin_min'), _hist_num(p, 'margin_max')
    if mm_min is not None:
        qs = qs.filter(margin_pct__gte=mm_min)
    if mm_max is not None:
        qs = qs.filter(margin_pct__lte=mm_max)
    ec_min, ec_max = _hist_num(p, 'eff_cost_min'), _hist_num(p, 'eff_cost_max')
    if ec_min is not None:
        qs = qs.filter(effective_cost__gte=ec_min)
    if ec_max is not None:
        qs = qs.filter(effective_cost__lte=ec_max)
    v_min, v_max = _hist_num(p, 'value_min'), _hist_num(p, 'value_max')
    if v_min is not None:
        qs = qs.filter(net_value__gte=v_min)
    if v_max is not None:
        qs = qs.filter(net_value__lte=v_max)

    return qs


_HIST_ORDERINGS = {
    'doc_date', '-doc_date',
    'net_value', '-net_value',
    'margin_pct', '-margin_pct',
    'effective_cost', '-effective_cost',
    'vat_value', '-vat_value',
    'bonus_qty', '-bonus_qty',
}


# ── v2/v3: Purchase History (enhanced, with SOFTECH + range filters) ──────────

class PurchaseHistoryView(generics.ListAPIView):
    """
    Enhanced purchase history. Filters (all optional, item-attrs multi-select):
      supplier_code, item_code, branch_code, buyer_code, q, date_from, date_to,
      is_return, is_foc, return_type, supplier_category (csv),
      medicine_type / shape_code / effect_code / origin_code / producer_code /
      family_code / item_level (csv), is_imported,
      margin_min/max, eff_cost_min/max, value_min/max.
    Max 1000 lines per request; use /history/summary/ for totals over all matches.
    """
    permission_classes = [IsAuthenticated]
    serializer_class   = PurchaseLineEnhancedSerializer
    # Self-filters + self-orders and caps with a slice; disable global DRF
    # backends (OrderingFilter would reorder the sliced queryset and 500) and
    # pagination so the [:1000] cap holds and the response is a JSON array.
    filter_backends    = []
    pagination_class   = None

    def get_queryset(self):
        qs = apply_history_filters(
            PurchaseLine.objects.select_related('item', 'branch'),
            self.request.query_params,
        )
        ordering = self.request.query_params.get('ordering', '-doc_date')
        if ordering in _HIST_ORDERINGS:
            qs = qs.order_by(ordering)
        return qs[:1000]


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def purchase_history_summary(request):
    """
    Totals over the FULL filtered set (not just the 1000 shown rows), so the
    history header can show accurate aggregates.  Same filters as /history/.
    """
    qs = apply_history_filters(PurchaseLine.objects.all(), request.query_params)
    agg = qs.aggregate(
        line_count     = Count('id'),
        paid_value     = Sum('net_value', filter=Q(is_return=False)),
        return_value   = Sum('net_value', filter=Q(is_return=True)),
        bonus_units    = Sum('bonus_qty'),
        foc_lines      = Count('id', filter=Q(is_foc=True)),
        vat_total      = Sum('vat_value'),
        avg_margin     = Avg('margin_pct', filter=Q(is_return=False)),
        suppliers      = Count('supplier_code', distinct=True),
        items          = Count('item_code', distinct=True),
        invoices       = Count('doc_number', distinct=True),
    )
    return Response({
        'line_count':   agg['line_count'] or 0,
        'paid_value':   float(agg['paid_value'] or 0),
        'return_value': abs(float(agg['return_value'] or 0)),
        'bonus_units':  float(agg['bonus_units'] or 0),
        'foc_lines':    agg['foc_lines'] or 0,
        'vat_total':    float(agg['vat_total'] or 0),
        'avg_margin':   round(float(agg['avg_margin'] or 0), 2),
        'suppliers':    agg['suppliers'] or 0,
        'items':        agg['items'] or 0,
        'invoices':     agg['invoices'] or 0,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def procurement_filter_options(request):
    """
    Dropdown options for the history filter panel, scoped to items that actually
    appear in PurchaseLine so the lists stay relevant.  Mirrors the SOFTECH
    dimensions used by /purchasing.
    """
    from apps.catalog.models import Item

    item_ids = (
        PurchaseLine.objects.exclude(item__isnull=True)
        .values_list('item_id', flat=True).distinct()
    )
    base = Item.objects.filter(id__in=item_ids)

    def _codelist(code_field, name_field, name_ar_field=None):
        fields = [code_field, name_field] + ([name_ar_field] if name_ar_field else [])
        seen = {}
        for r in base.exclude(**{code_field: ''}).values(*fields).distinct():
            code = r.get(code_field)
            if not code:
                continue
            nm   = r.get(name_field) or ''
            nmar = (r.get(name_ar_field) or '') if name_ar_field else ''
            if code not in seen or not seen[code]['name']:
                seen[code] = {'code': code, 'name': nmar or nm or code}
        return sorted(seen.values(), key=lambda x: (x['name'] or '').lower())

    categories = list(
        SupplierCategory.objects.filter(is_active=True)
        .values('code', 'name_ar', 'color').order_by('sort_order', 'code')
    )

    # Branches that appear in purchase lines (code + name from Branch cache).
    # NOTE: override the model's default -doc_date ordering, else Django adds
    # doc_date to the SELECT and DISTINCT degenerates to (branch, date) pairs.
    from apps.branches.models import Branch
    branch_codes = list(
        PurchaseLine.objects.exclude(branch_code='')
        .order_by('branch_code')
        .values_list('branch_code', flat=True).distinct()
    )
    branch_names = {
        b.softech_branch_id: b.name
        for b in Branch.objects.filter(softech_branch_id__in=branch_codes)
    }
    branches = sorted(
        ({'code': c, 'name': branch_names.get(c, c)} for c in branch_codes),
        key=lambda x: x['code'],
    )

    return Response({
        'supplier_categories': [
            {'code': c['code'], 'name': c['name_ar'], 'color': c['color']} for c in categories
        ],
        'branches': branches,
        'medicine_types': _codelist('medicine_type', 'medicine_type_name', 'medicine_type_name_ar'),
        'families':       _codelist('family_code',   'family_name',   'family_name_ar'),
        'producers':      _codelist('producer_code', 'producer_name'),
        'origins':        _codelist('origin_code',   'origin_name',   'origin_name_ar'),
        'shapes':         _codelist('shape_code',    'shape_name',    'shape_name_ar'),
        'effects':        _codelist('effect_code',   'effect_name',   'effect_name_ar'),
    })


# ── v2: Supplier Segmentation ─────────────────────────────────────────────────

class SupplierSegmentationListView(generics.ListAPIView):
    """
    List all supplier segmentations with optional filters:
      category, q (search name/code), min_value
    """
    permission_classes = [IsAuthenticated]
    serializer_class   = SupplierSegmentationSerializer

    def get_queryset(self):
        qs = SupplierSegmentation.objects.all()
        category = self.request.query_params.get('category', '').strip()
        q        = self.request.query_params.get('q', '').strip()
        min_val  = self.request.query_params.get('min_value')

        if category:
            qs = qs.filter(supplier_category=category)
        if q:
            qs = qs.filter(
                Q(supplier_name__icontains=q) | Q(supplier_code__icontains=q)
            )
        if min_val:
            qs = qs.filter(purchase_value_365d__gte=min_val)

        ordering = self.request.query_params.get('ordering', '-purchase_value_365d')
        allowed  = {
            'purchase_value_365d', '-purchase_value_365d',
            'supplier_category', '-supplier_category',
            'foc_rate_pct', '-foc_rate_pct',
            'return_pct', '-return_pct',
        }
        if ordering in allowed:
            qs = qs.order_by(ordering)

        return qs


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def supplier_segmentation_summary(request):
    """
    Aggregate KPIs per supplier category:
      total suppliers, total purchase value, avg FOC rate, avg return rate,
      share of total purchase value.
    """
    since, until = resolve_period(request.query_params)
    days = (until - since).days or 1

    scoped = apply_dimension_filters(
        PurchaseLine.objects.filter(doc_date__gte=since, doc_date__lte=until),
        request.query_params,
    )
    all_value = _d(scoped.filter(is_return=False).aggregate(v=Sum('net_value'))['v'])

    rows = list(
        scoped
        .values('supplier_category')
        .annotate(
            total_value   = Sum('net_value', filter=Q(is_return=False)),
            return_value  = Sum('net_value', filter=Q(is_return=True)),
            total_qty     = Sum('net_qty', filter=Q(is_return=False)),
            supplier_count = Count('supplier_code', distinct=True),
            invoice_count  = Count('doc_number', distinct=True),
            foc_lines      = Count('id', filter=Q(is_foc=True, is_return=False)),
            total_lines    = Count('id', filter=Q(is_return=False)),
        )
        .order_by('-total_value')
    )

    result = []
    for r in rows:
        cat      = r['supplier_category'] or 'UNKNOWN'
        tv       = _d(r['total_value'])
        rv       = abs(_d(r['return_value']))
        tl       = r['total_lines'] or 1
        result.append({
            'category':         cat,
            'category_display': {
                'OFFICIAL_DISTRIBUTOR': 'موزع رسمي',
                'MANUFACTURER':         'مصنع',
                'SMALL_WAREHOUSE':      'مستودع صغير',
                'PATIENT_REPURCHASE':   'شراء من مريض',
                'INTERNAL_TRANSFER':    'تحويل داخلي',
                'SERVICE_VENDOR':       'مورد خدمات',
                'UNKNOWN':              'غير مصنف',
            }.get(cat, cat),
            'supplier_count':   r['supplier_count'],
            'invoice_count':    r['invoice_count'],
            'total_value':      float(tv),
            'return_value':     float(rv),
            'return_pct':       round(float(rv / tv * 100) if tv > 0 else 0, 2),
            'foc_rate_pct':     round(float(r['foc_lines']) / tl * 100, 2),
            'share_of_total':   round(float(tv / all_value * 100) if all_value > 0 else 0, 2),
        })

    return Response({
        'period_days':      days,
        'total_value':      float(all_value),
        'categories':       result,
    })


@api_view(['PATCH'])
@permission_classes([IsAdminUser])
def update_supplier_segmentation(request, pk):
    """
    Manually override a supplier's category.
    Sets manual_override=True so auto-classification won't change it.
    """
    try:
        seg = SupplierSegmentation.objects.get(pk=pk)
    except SupplierSegmentation.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=404)

    new_cat = request.data.get('supplier_category', '').strip()
    notes   = request.data.get('notes', '').strip()

    valid_cats = list(
        SupplierCategory.objects.filter(is_active=True).values_list('code', flat=True)
    )
    if new_cat and new_cat not in valid_cats:
        return Response({'detail': f'Invalid category. Choose from: {valid_cats}'}, status=400)

    if new_cat:
        seg.supplier_category = new_cat
        seg.manual_override   = True
        seg.auto_classified   = False
    if notes:
        seg.notes = notes

    seg.save(update_fields=['supplier_category', 'manual_override', 'auto_classified', 'notes'])

    # Back-fill PurchaseLine and SupplierProfile
    PurchaseLine.objects.filter(supplier_code=seg.supplier_code).update(
        supplier_category=seg.supplier_category,
    )
    SupplierProfile.objects.filter(supplier_code=seg.supplier_code).update(
        supplier_category=seg.supplier_category,
    )

    return Response(SupplierSegmentationSerializer(seg).data)


# ── v2: FOC Analysis ──────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def foc_analysis(request):
    """
    Free-of-charge (FOC) analysis:
      - Network-level FOC rate
      - Top FOC-giving suppliers
      - FOC trend (monthly)
      - Effective cost vs nominal cost comparison
    """
    since, until = resolve_period(request.query_params)
    days = (until - since).days or 1

    base = apply_dimension_filters(
        PurchaseLine.objects.filter(doc_date__gte=since, doc_date__lte=until, is_return=False),
        request.query_params,
    )

    overall = base.aggregate(
        total_lines   = Count('id'),
        foc_lines     = Count('id', filter=Q(is_foc=True)),
        bonus_lines   = Count('id', filter=Q(bonus_qty__gt=0)),
        bonus_units   = Sum('bonus_qty'),
        paid_units    = Sum('net_qty'),
        total_value   = Sum('net_value'),
        avg_cost      = Avg('unit_price', filter=Q(is_foc=False)),
        avg_eff_cost  = Avg('effective_cost', filter=Q(effective_cost__gt=0)),
    )

    total_l = overall['total_lines'] or 1
    foc_rate = round((overall['foc_lines'] or 0) / total_l * 100, 2)
    # Bonus-unit yield: free units as a share of all units received.
    paid_u  = float(overall['paid_units'] or 0)
    bonus_u = float(overall['bonus_units'] or 0)
    bonus_unit_pct = round(bonus_u / (paid_u + bonus_u) * 100, 2) if (paid_u + bonus_u) > 0 else 0

    # Top FOC suppliers — ranked by free units actually delivered.
    top_foc = list(
        base.values('supplier_code')
        .annotate(
            total_lines = Count('id'),
            foc_lines   = Count('id', filter=Q(is_foc=True)),
            bonus_units = Sum('bonus_qty'),
            foc_value   = Sum('raw_value', filter=Q(is_foc=True)),
        )
        .filter(foc_lines__gt=0)
        .annotate(foc_pct=Count('id', filter=Q(is_foc=True)) * 100.0 / Count('id'))
        .order_by('-bonus_units', '-foc_lines')[:20]
    )

    # Enrich with supplier names
    supp_names = {
        sp.supplier_code: sp.supplier_name
        for sp in SupplierProfile.objects.filter(
            supplier_code__in=[r['supplier_code'] for r in top_foc]
        ).only('supplier_code', 'supplier_name')
    }

    # FOC monthly trend
    foc_monthly: dict = {}
    for line in base.filter(is_foc=True).values('doc_date'):
        key = str(line['doc_date'])[:7]
        foc_monthly[key] = foc_monthly.get(key, 0) + 1

    total_monthly: dict = {}
    for line in base.values('doc_date'):
        key = str(line['doc_date'])[:7]
        total_monthly[key] = total_monthly.get(key, 0) + 1

    foc_trend = [
        {
            'month':      k,
            'foc_lines':  foc_monthly.get(k, 0),
            'total_lines': total_monthly.get(k, 0),
            'foc_rate':   round(foc_monthly.get(k, 0) / total_monthly.get(k, 1) * 100, 2),
        }
        for k in sorted(total_monthly.keys())
    ]

    return Response({
        'period_days':  days,
        'overall': {
            'total_lines':   overall['total_lines'] or 0,
            'foc_lines':     overall['foc_lines'] or 0,
            'bonus_lines':   overall['bonus_lines'] or 0,
            'foc_rate_pct':  foc_rate,
            'bonus_units':   round(bonus_u, 2),
            'bonus_unit_pct': bonus_unit_pct,
            'total_value':   float(overall['total_value'] or 0),
            'avg_unit_price':    round(float(overall['avg_cost'] or 0), 4),
            'avg_effective_cost': round(float(overall['avg_eff_cost'] or 0), 4),
        },
        'top_foc_suppliers': [
            {
                'supplier_code': r['supplier_code'],
                'supplier_name': supp_names.get(r['supplier_code'], r['supplier_code']),
                'total_lines':   r['total_lines'],
                'foc_lines':     r['foc_lines'],
                'bonus_units':   round(float(r['bonus_units'] or 0), 2),
                'foc_rate_pct':  round(float(r.get('foc_pct') or 0), 2),
                'foc_value':     round(float(r['foc_value'] or 0), 2),
            }
            for r in top_foc
        ],
        'monthly_trend': foc_trend,
    })


# ── v2: Expiry Return Analysis ────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def expiry_return_analysis(request):
    """
    Expiry return analysis:
      - Total expiry returns vs normal returns
      - Top branches with expiry returns
      - Top items returned as expired
      - Monthly expiry return trend
    """
    since, until = resolve_period(request.query_params)
    days = (until - since).days or 1

    ret_base = apply_dimension_filters(
        PurchaseLine.objects.filter(doc_date__gte=since, doc_date__lte=until, is_return=True),
        request.query_params,
    )

    summary = ret_base.aggregate(
        total_returns   = Count('id'),
        expiry_returns  = Count('id', filter=Q(return_type='expiry')),
        normal_returns  = Count('id', filter=Q(return_type='normal')),
        total_value     = Sum('net_value'),
        expiry_value    = Sum('net_value', filter=Q(return_type='expiry')),
    )

    total_r  = summary['total_returns'] or 1
    expiry_r = summary['expiry_returns'] or 0
    expiry_pct = round(expiry_r / total_r * 100, 2)

    # Top branches by expiry returns
    top_branches = list(
        ret_base.filter(return_type='expiry')
        .values('branch_code')
        .annotate(
            expiry_count = Count('id'),
            expiry_value = Sum('net_value'),
        )
        .order_by('-expiry_count')[:15]
    )

    # Top items returned as expired
    top_items = list(
        ret_base.filter(return_type='expiry')
        .values('item_code')
        .annotate(
            expiry_count = Count('id'),
            expiry_value = Sum('net_value'),
        )
        .order_by('-expiry_count')[:20]
    )

    # Monthly trend
    monthly: dict = {}
    for line in ret_base.values('doc_date', 'return_type'):
        key = str(line['doc_date'])[:7]
        if key not in monthly:
            monthly[key] = {'month': key, 'expiry': 0, 'normal': 0}
        if line['return_type'] == 'expiry':
            monthly[key]['expiry'] += 1
        else:
            monthly[key]['normal'] += 1

    return Response({
        'period_days': days,
        'summary': {
            'total_returns':   summary['total_returns'] or 0,
            'expiry_returns':  expiry_r,
            'normal_returns':  summary['normal_returns'] or 0,
            'expiry_pct':      expiry_pct,
            'total_value':     abs(round(float(summary['total_value'] or 0), 2)),
            'expiry_value':    abs(round(float(summary['expiry_value'] or 0), 2)),
        },
        'top_branches': [
            {
                'branch_code':   r['branch_code'],
                'expiry_count':  r['expiry_count'],
                'expiry_value':  abs(round(float(r['expiry_value'] or 0), 2)),
            }
            for r in top_branches
        ],
        'top_items': [
            {
                'item_code':    r['item_code'],
                'expiry_count': r['expiry_count'],
                'expiry_value': abs(round(float(r['expiry_value'] or 0), 2)),
            }
            for r in top_items
        ],
        'monthly_trend': sorted(monthly.values(), key=lambda x: x['month']),
    })


# ── v2: Tax Burden Analysis ───────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def tax_burden_analysis(request):
    """
    Tax burden (VAT) analysis:
      - Network tax burden rate
      - Top suppliers by tax burden
      - Monthly tax trend
    """
    since, until = resolve_period(request.query_params)
    days = (until - since).days or 1

    base = apply_dimension_filters(
        PurchaseLine.objects.filter(doc_date__gte=since, doc_date__lte=until, is_return=False),
        request.query_params,
    )

    overall = base.aggregate(
        total_value = Sum('net_value'),
        total_vat   = Sum('vat_value'),
        lines_with_vat = Count('id', filter=Q(vat_value__gt=0)),
    )

    tv  = float(overall['total_value'] or 0)
    tvat = float(overall['total_vat'] or 0)
    tax_rate = round(tvat / tv * 100, 3) if tv > 0 else 0

    # Top suppliers by absolute tax burden
    by_supplier = list(
        base.filter(vat_value__gt=0)
        .values('supplier_code')
        .annotate(
            total_value = Sum('net_value'),
            total_vat   = Sum('vat_value'),
        )
        .order_by('-total_vat')[:20]
    )

    supp_names = {
        sp.supplier_code: sp.supplier_name
        for sp in SupplierProfile.objects.filter(
            supplier_code__in=[r['supplier_code'] for r in by_supplier]
        ).only('supplier_code', 'supplier_name')
    }

    # Monthly VAT trend
    vat_monthly: dict = {}
    for line in base.filter(vat_value__gt=0).values('doc_date', 'net_value', 'vat_value'):
        key = str(line['doc_date'])[:7]
        if key not in vat_monthly:
            vat_monthly[key] = {'month': key, 'net_value': 0.0, 'vat_value': 0.0}
        vat_monthly[key]['net_value'] += float(line['net_value'] or 0)
        vat_monthly[key]['vat_value'] += float(line['vat_value'] or 0)

    return Response({
        'period_days': days,
        'overall': {
            'total_purchase_value': round(tv, 2),
            'total_vat':            round(tvat, 2),
            'tax_rate_pct':         tax_rate,
            'lines_with_vat':       overall['lines_with_vat'] or 0,
        },
        'by_supplier': [
            {
                'supplier_code': r['supplier_code'],
                'supplier_name': supp_names.get(r['supplier_code'], r['supplier_code']),
                'total_value':   round(float(r['total_value'] or 0), 2),
                'total_vat':     round(float(r['total_vat'] or 0), 2),
                'tax_rate_pct':  round(
                    float(r['total_vat'] or 0) / float(r['total_value'] or 1) * 100, 3
                ),
            }
            for r in by_supplier
        ],
        'monthly_trend': [
            {**m, 'tax_rate_pct': round(m['vat_value'] / m['net_value'] * 100, 3) if m['net_value'] > 0 else 0}
            for m in sorted(vat_monthly.values(), key=lambda x: x['month'])
        ],
    })


# ── v2: Enhanced Supplier Performance ────────────────────────────────────────

class SupplierPerformanceEnhancedListView(generics.ListAPIView):
    """
    Enhanced supplier list with v2 scoring (FOC, tax, effective cost dimensions).
    """
    permission_classes = [IsAuthenticated]
    serializer_class   = SupplierProfileEnhancedSerializer

    def get_queryset(self):
        qs = SupplierProfile.objects.all()
        q  = self.request.query_params.get('q', '').strip()
        if q:
            qs = qs.filter(
                Q(supplier_name__icontains=q) | Q(supplier_code__icontains=q)
            )
        category = self.request.query_params.get('category', '').strip()
        if category:
            qs = qs.filter(supplier_category=category)
        min_score = self.request.query_params.get('min_score')
        if min_score:
            qs = qs.filter(enhanced_total_score__gte=min_score)

        ordering = self.request.query_params.get('ordering', '-enhanced_total_score')
        allowed  = {
            'enhanced_total_score', '-enhanced_total_score',
            'total_score', '-total_score',
            'net_purchase_value', '-net_purchase_value',
            'foc_rate_pct', '-foc_rate_pct',
            'avg_tax_burden_pct', '-avg_tax_burden_pct',
            'return_pct', '-return_pct',
        }
        if ordering in allowed:
            qs = qs.order_by(ordering)
        return qs


# ── Dashboard summary endpoint ────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def procurement_dashboard(request):
    """
    All-in-one dashboard data: snapshot + alerts + top suppliers + engine status.
    """
    snap = ProcurementSnapshot.objects.order_by('-snapshot_date').first()
    latest_run = _latest_run()
    running = ProcurementEngineRun.objects.filter(status='running').exists()

    open_alerts = ProcurementAlert.objects.filter(is_resolved=False)
    alert_counts = {
        'total':    open_alerts.count(),
        'critical': open_alerts.filter(severity='critical').count(),
        'warning':  open_alerts.filter(severity='warning').count(),
        'info':     open_alerts.filter(severity='info').count(),
    }
    recent_alerts = ProcurementAlertSerializer(
        open_alerts.order_by('-detected_at')[:5], many=True
    ).data

    top_suppliers = SupplierProfileListSerializer(
        SupplierProfile.objects.order_by('-total_score')[:10], many=True
    ).data

    return Response({
        'snapshot':      ProcurementSnapshotSerializer(snap).data if snap else None,
        'latest_run':    ProcurementEngineRunSerializer(latest_run).data if latest_run else None,
        'engine_running': running,
        'alert_counts':  alert_counts,
        'recent_alerts': recent_alerts,
        'top_suppliers': top_suppliers,
    })


# ── v3: Admin-managed Supplier Categories ─────────────────────────────────────

class ReadOnlyOrAdmin(IsAuthenticated):
    """Any authenticated user may read; only staff/admin may write."""
    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        if request.method in ('GET', 'HEAD', 'OPTIONS'):
            return True
        return bool(request.user and request.user.is_staff)


class SupplierCategoryListCreateView(generics.ListCreateAPIView):
    """List all supplier categories (read: any auth user; write: staff)."""
    permission_classes = [ReadOnlyOrAdmin]
    serializer_class   = SupplierCategorySerializer
    filter_backends    = []
    pagination_class   = None

    def get_queryset(self):
        qs = SupplierCategory.objects.all()
        if self.request.query_params.get('active_only', '').lower() in ('1', 'true'):
            qs = qs.filter(is_active=True)
        return qs.order_by('sort_order', 'code')


class SupplierCategoryDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [ReadOnlyOrAdmin]
    serializer_class   = SupplierCategorySerializer
    queryset           = SupplierCategory.objects.all()


class SupplierClassificationRuleListCreateView(generics.ListCreateAPIView):
    permission_classes = [ReadOnlyOrAdmin]
    serializer_class   = SupplierClassificationRuleSerializer
    filter_backends    = []
    pagination_class   = None

    def get_queryset(self):
        qs = SupplierClassificationRule.objects.select_related('category')
        ptcode = self.request.query_params.get('ptcode', '').strip()
        if ptcode:
            qs = qs.filter(ptcode=ptcode)
        return qs.order_by('ptcode', 'ptclassifcode')


class SupplierClassificationRuleDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [ReadOnlyOrAdmin]
    serializer_class   = SupplierClassificationRuleSerializer
    queryset           = SupplierClassificationRule.objects.all()


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def softech_person_codes(request):
    """
    Reference data for the rule editor: SOFTECH person types + classifications
    (from the synced apps.sync cache).  Optionally ?ptcode=20 to filter classifs.
    """
    from apps.sync.models import SoftechPersonType, SoftechPersonClassif

    types = list(
        SoftechPersonType.objects.values('ptcode', 'ptdescr', 'ptedescr').order_by('ptcode')
    )
    classif_qs = SoftechPersonClassif.objects.all()
    ptcode = request.query_params.get('ptcode', '').strip()
    if ptcode:
        classif_qs = classif_qs.filter(ptcode=ptcode)
    classifs = list(
        classif_qs.values('ptcode', 'ptclassifcode', 'ptclassifdescr')
        .order_by('ptcode', 'ptclassifcode')
    )
    return Response({'person_types': types, 'classifications': classifs})


@api_view(['POST'])
@permission_classes([IsAdminUser])
def reclassify_suppliers(request):
    """
    Re-run supplier classification (Stage 2.5 only) against the current rules —
    a fast way to apply category/rule edits without a full engine run.
    Runs in a background thread; manual overrides are preserved.
    """
    from .engine import classify_supplier_segments

    def _run():
        run = ProcurementEngineRun.objects.create(
            period_days=365, triggered_by=f'reclassify:{request.user}', status='running',
        )
        try:
            classify_supplier_segments(run)
            run.finish('success')
        except Exception as e:  # pragma: no cover
            run.finish('failed', str(e))

    threading.Thread(target=_run, daemon=True).start()
    return Response({'detail': 'Supplier reclassification started.'},
                    status=status.HTTP_202_ACCEPTED)
