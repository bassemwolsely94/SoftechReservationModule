import datetime as _dt
import logging
import threading

from rest_framework import viewsets, mixins, status, generics
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.response import Response

from .models import StockBatch, NearExpiryAlert, PurchaseExpiryAuditRun
from .serializers import (
    StockBatchSerializer, StockBatchListSerializer,
    NearExpiryAlertSerializer, FEFORecommendationSerializer,
    PurchaseExpiryAuditRunSerializer,
)
from .service import BatchService

logger = logging.getLogger('elrezeiky.batches')


# ── Purchase-Expiry Physical Audit ────────────────────────────────────────────

def _parse_date(val):
    """Parse 'YYYY-MM-DD' (or 'YYYY-MM') to a date, or None."""
    if not val:
        return None
    s = str(val).strip()
    for fmt in ('%Y-%m-%d', '%Y-%m'):
        try:
            return _dt.datetime.strptime(s[:10] if fmt == '%Y-%m-%d' else s[:7], fmt).date()
        except ValueError:
            continue
    return None


def _branch_list(data):
    """Accept branches as a list, a single value, or a comma string."""
    raw = data.get('branches') or data.get('branch') or []
    if isinstance(raw, str):
        raw = [b.strip() for b in raw.split(',') if b.strip()]
    elif not isinstance(raw, (list, tuple)):
        raw = [str(raw)]
    return [str(b).strip() for b in raw if str(b).strip()]


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def purchase_expiry_candidates(request):
    """
    Physical near-expiry audit report.

    Body:
      from        'YYYY-MM-DD' | 'YYYY-MM'   (required — ENTERED-EXPIRY window start)
      to          'YYYY-MM-DD' | 'YYYY-MM'   (required — expiry window end, inclusive)
      branches    []|str|csv                 (optional — default: all in mirror)
      categories  []                         (optional — default main categories)
      only_in_stock bool                     (default true)
      min_qty     number                     (default 0)

    Returns the candidate item worklist (purchase-entry trigger ∩ in-stock now).
    Hits SOFTECH live for the current-stock check, so it may take a few seconds.
    """
    from .expiry_audit import audit_candidates

    date_from = _parse_date(request.data.get('from'))
    date_to   = _parse_date(request.data.get('to'))
    if not date_from or not date_to:
        return Response({'detail': 'يجب تحديد الفترة (from / to).'},
                        status=status.HTTP_400_BAD_REQUEST)
    if date_from > date_to:
        return Response({'detail': 'تاريخ البداية بعد تاريخ النهاية.'},
                        status=status.HTTP_400_BAD_REQUEST)

    branches   = _branch_list(request.data) or None
    categories = request.data.get('categories') or None
    only_in_stock = request.data.get('only_in_stock', True)
    if isinstance(only_in_stock, str):
        only_in_stock = only_in_stock.lower() != 'false'
    try:
        from decimal import Decimal
        min_qty = Decimal(str(request.data.get('min_qty', 0)))
    except Exception:
        min_qty = 0

    sort = request.data.get('sort') or None
    imported_only = request.data.get('imported_only', False)
    if isinstance(imported_only, str):
        imported_only = imported_only.lower() == 'true'
    min_var = request.data.get('min_value_at_risk')

    try:
        rows = audit_candidates(
            date_from, date_to, branch_codes=branches,
            categories=categories, only_in_stock=only_in_stock, min_qty=min_qty,
            sort=sort, imported_only=imported_only, min_value_at_risk=min_var,
        )
    except Exception as e:
        logger.exception('purchase_expiry_candidates failed')
        return Response({'detail': f'خطأ أثناء توليد التقرير: {e}'},
                        status=status.HTTP_503_SERVICE_UNAVAILABLE)

    return Response({
        'from': date_from.isoformat(), 'to': date_to.isoformat(),
        'branches': branches or 'ALL',
        'only_in_stock': only_in_stock,
        'count': len(rows),
        'items': rows,
    })


class PurchaseExpiryRunListView(generics.ListAPIView):
    """GET — recent purchase-expiry backfill runs (status/counters)."""
    permission_classes = [IsAuthenticated]
    serializer_class   = PurchaseExpiryAuditRunSerializer
    queryset           = PurchaseExpiryAuditRun.objects.all()[:30]


@api_view(['POST'])
@permission_classes([IsAdminUser])
def trigger_purchase_expiry_sync(request):
    """
    Kick off a purchase-expiry backfill in a background thread (admin only).

    Body: years|from|to, branch, categories (all optional; mirror the CLI).
    Re-runnable — after re-classifying more suppliers as "main", call this again
    to pull the newly-included suppliers' history.
    """
    from .expiry_audit import run_backfill, MAIN_SUPPLIER_CATEGORIES

    today = _dt.date.today()
    date_to = _parse_date(request.data.get('to')) or today
    date_from = _parse_date(request.data.get('from'))
    if not date_from:
        years = int(request.data.get('years', 3) or 3)
        try:
            date_from = date_to.replace(year=date_to.year - years, day=1)
        except ValueError:
            date_from = date_to.replace(year=date_to.year - years, day=1, month=date_to.month)
    if date_from > date_to:
        return Response({'detail': 'الفترة غير صحيحة.'}, status=status.HTTP_400_BAD_REQUEST)

    branch = (request.data.get('branch') or '').strip()
    categories = request.data.get('categories') or list(MAIN_SUPPLIER_CATEGORIES)
    triggered_by = str(request.user)

    run = PurchaseExpiryAuditRun.objects.create(
        window_from=date_from, window_to=date_to, branch_scope=branch,
        categories=categories, triggered_by=triggered_by,
    )

    def _run():
        try:
            run_backfill(run, date_from, date_to, branch=branch or None,
                         categories=categories)
            run.finish('success')
        except Exception as e:   # noqa: BLE001
            logger.exception('purchase-expiry backfill failed (run #%s)', run.pk)
            run.finish('failed', error=str(e))

    threading.Thread(target=_run, daemon=True).start()

    return Response({
        'detail': 'بدأت مزامنة صلاحيات الشراء في الخلفية.',
        'run': PurchaseExpiryAuditRunSerializer(run).data,
    }, status=status.HTTP_202_ACCEPTED)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def spawn_expiry_count_session(request):
    """
    Create a physical stock-count session (mode=expiry_audit) from the audit
    report, so staff can pull the items and record their real shelf expiry.

    Body:
      branch      required — one branch per count session
      from / to   required — the ENTERED-EXPIRY window that defined the candidates
      categories  optional
      item_codes  optional — explicit subset; else all candidates for the branch
      name        optional
    """
    from .expiry_audit import audit_candidates, MAIN_SUPPLIER_CATEGORIES
    from .models import PurchaseExpiryEntry
    from apps.stockcount.models import StockCountSession, StockCountSnapshot
    from apps.stockcount.engine import generate_snapshot

    branch = (request.data.get('branch') or '').strip()
    date_from = _parse_date(request.data.get('from'))
    date_to   = _parse_date(request.data.get('to'))
    if not branch:
        return Response({'detail': 'كود الفرع مطلوب.'}, status=status.HTTP_400_BAD_REQUEST)
    if not date_from or not date_to:
        return Response({'detail': 'يجب تحديد الفترة (from / to).'},
                        status=status.HTTP_400_BAD_REQUEST)

    categories = request.data.get('categories') or None
    item_codes = request.data.get('item_codes')
    if item_codes and isinstance(item_codes, (list, tuple)):
        codes = [str(c).strip() for c in item_codes if str(c).strip()]
    else:
        try:
            cands = audit_candidates(
                date_from, date_to, branch_codes=[branch],
                categories=categories, only_in_stock=True,
            )
        except Exception as e:
            logger.exception('spawn_expiry_count_session candidate lookup failed')
            return Response({'detail': f'خطأ أثناء جلب الأصناف: {e}'},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        codes = [c['item_code'] for c in cands]

    if not codes:
        return Response({'detail': 'لا توجد أصناف مطابقة للمعايير في هذا الفرع.'},
                        status=status.HTTP_400_BAD_REQUEST)

    profile = getattr(request.user, 'staff_profile', None)
    name = (request.data.get('name') or
            f'جرد صلاحية — فرع {branch} — {date_from} : {date_to}')

    session = StockCountSession.objects.create(
        name=name, mode='expiry_audit', branch_code=branch,
        date_from=date_from, date_to=date_to,
        item_codes_filter=codes, created_by=profile,
        notes='مولّدة من محرك تدقيق صلاحيات الشراء (أصناف من موردين رئيسيين).',
    )

    # Snapshot current stock for exactly these items (filtered-stock path).
    try:
        count = generate_snapshot(session)
    except ValueError as e:
        session.delete()
        return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        session.delete()
        logger.exception('spawn_expiry_count_session snapshot failed')
        return Response({'detail': f'خطأ في الاتصال بـ SOFTECH: {e}'},
                        status=status.HTTP_503_SERVICE_UNAVAILABLE)

    # Backfill the entered-expiry hint (earliest keyed expiry within the window)
    # onto each snapshot. Chain-wide (NOT filtered by branch) — purchases are
    # received centrally then distributed, so the expiry entry lives at HQ while
    # the stock sits at this branch. Same semantics as the report.
    from django.db.models import Min
    cats = categories or list(MAIN_SUPPLIER_CATEGORIES)
    hint_qs = (
        PurchaseExpiryEntry.objects
        .filter(entered_expiry__gte=date_from, entered_expiry__lte=date_to,
                supplier_category__in=cats, item_code__in=codes)
        .values('item_code').annotate(hint=Min('entered_expiry'))
    )
    hints = {r['item_code']: r['hint'] for r in hint_qs}
    to_update = []
    for snap in StockCountSnapshot.objects.filter(session=session):
        h = hints.get(snap.item_code)
        if h:
            snap.entered_expiry_hint = h
            to_update.append(snap)
    if to_update:
        StockCountSnapshot.objects.bulk_update(to_update, ['entered_expiry_hint'])

    return Response({
        'detail': f'تم إنشاء جلسة جرد صلاحية لـ {count} صنف.',
        'session_id': session.pk,
        'item_count': count,
        'branch_code': branch,
        'status': session.status,
    }, status=status.HTTP_201_CREATED)


class StockBatchViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """
    GET /api/batches/                    — list (filter: item, branch, vendor, expiring_in_days)
    GET /api/batches/{id}/               — full detail with movements
    GET /api/batches/fefo/?item=&branch= — FEFO-ordered list for dispatch
    GET /api/batches/near-expiry/        — near-expiry dashboard summary
    GET /api/batches/alerts/             — NearExpiryAlert list
    POST /api/batches/{id}/quarantine/   — quarantine a batch
    """
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = StockBatch.objects.select_related('item', 'branch', 'vendor', 'received_by')
        p  = self.request.query_params

        if p.get('item'):
            qs = qs.filter(item_id=p['item'])
        if p.get('branch'):
            qs = qs.filter(branch_id=p['branch'])
        if p.get('vendor'):
            qs = qs.filter(vendor_id=p['vendor'])
        if p.get('expiring_in_days'):
            from django.utils import timezone
            from datetime import timedelta
            cutoff = timezone.now().date() + timedelta(days=int(p['expiring_in_days']))
            qs = qs.filter(expiry_date__lte=cutoff, is_expired=False, current_qty__gt=0)
        if p.get('is_quarantined'):
            qs = qs.filter(is_quarantined=p['is_quarantined'].lower() == 'true')
        if p.get('is_expired'):
            qs = qs.filter(is_expired=p['is_expired'].lower() == 'true')

        return qs.order_by('expiry_date', 'id')

    def get_serializer_class(self):
        if self.action in ('list', 'fefo'):
            return StockBatchListSerializer
        return StockBatchSerializer

    @action(detail=False, methods=['get'])
    def fefo(self, request):
        """FEFO-ordered active batches for a given item × branch."""
        item_id   = request.query_params.get('item')
        branch_id = request.query_params.get('branch')
        if not item_id or not branch_id:
            return Response({'detail': 'item و branch مطلوبان.'}, status=status.HTTP_400_BAD_REQUEST)

        batches = BatchService.fefo_batches(int(item_id), int(branch_id))
        serializer = FEFORecommendationSerializer(batches, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'], url_path='near-expiry')
    def near_expiry(self, request):
        """Near-expiry KPI summary for dashboard."""
        branch_id = request.query_params.get('branch')
        days      = int(request.query_params.get('days', 180))
        data      = BatchService.near_expiry_summary(
            branch_id=int(branch_id) if branch_id else None,
            days=days,
        )
        return Response(data)

    @action(detail=False, methods=['get'])
    def alerts(self, request):
        """Active (unresolved) NearExpiryAlert list."""
        qs = NearExpiryAlert.objects.filter(
            resolved_at__isnull=True
        ).select_related('batch', 'batch__item', 'batch__branch', 'batch__vendor')

        if request.query_params.get('branch'):
            qs = qs.filter(batch__branch_id=request.query_params['branch'])
        if request.query_params.get('threshold'):
            qs = qs.filter(threshold_days=request.query_params['threshold'])

        qs = qs.order_by('batch__expiry_date')
        serializer = NearExpiryAlertSerializer(qs, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def quarantine(self, request, pk=None):
        """Put a batch into quarantine (quality hold)."""
        batch  = self.get_object()
        reason = request.data.get('reason', '')
        if not reason:
            return Response({'detail': 'سبب العزل مطلوب.'}, status=status.HTTP_400_BAD_REQUEST)

        # Require approval for quarantine if not admin
        profile = request.user.staff_profile
        if profile.role not in ('admin', 'quality_manager'):
            # Submit approval request first; actual quarantine happens on approval
            from apps.approvals.service import ApprovalService
            ApprovalService.submit(
                workflow_code='batch_quarantine',
                subject_object=batch,
                title=f'عزل دفعة: {batch.item.name} — {batch.batch_number}',
                requested_by=profile,
                context_data={
                    'batch_id': batch.pk,
                    'reason':   reason,
                    'qty':      str(batch.current_qty),
                },
            )
            return Response(
                {'detail': 'تم رفع طلب عزل الدفعة للاعتماد.'},
                status=status.HTTP_202_ACCEPTED,
            )

        BatchService.quarantine(batch=batch, reason=reason, performed_by=profile)
        return Response({'detail': 'تم عزل الدفعة.'}, status=status.HTTP_200_OK)
