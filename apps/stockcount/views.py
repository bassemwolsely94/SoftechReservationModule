"""
apps/stockcount/views.py  — v2

Transaction-driven Stock Count System.

Endpoints
---------
POST   /api/stockcount/sessions/
GET    /api/stockcount/sessions/
GET    /api/stockcount/sessions/{id}/
PATCH  /api/stockcount/sessions/{id}/
DELETE /api/stockcount/sessions/{id}/

POST   /api/stockcount/sessions/{id}/preview_items/
       → Query SOFTECH; return item list + expected quantities (no DB write)

POST   /api/stockcount/sessions/{id}/generate_snapshot/
       → Capture immutable stock snapshot; update session.status

GET    /api/stockcount/sessions/{id}/export_sheet/
       → Download count sheet (xlsx or csv with blank counted_qty)

POST   /api/stockcount/sessions/{id}/upload_results/
       → Upload filled count sheet; calculate variances

GET    /api/stockcount/sessions/{id}/variance_report/
       → JSON variance report with per-item detail

GET    /api/stockcount/sessions/{id}/adjustment_export/
       → Download variance sheet coloured by surplus/deficit (xlsx)

GET    /api/stockcount/sessions/{id}/snapshots/
       → Paginated snapshot list (supports ?variance_type=surplus|deficit|ok)
"""
import logging

from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import StockCountSession, StockCountSnapshot, DOCCODE_LABELS
from .serializers import (
    StockCountSessionListSerializer,
    StockCountSessionDetailSerializer,
    StockCountSessionCreateSerializer,
    StockCountSnapshotSerializer,
)

logger = logging.getLogger('elrezeiky.stockcount')


class SnapshotPagination(PageNumberPagination):
    page_size            = 200
    page_size_query_param = 'page_size'
    max_page_size        = 1000


class StockCountSessionViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    pagination_class   = None   # sessions list is small — no pagination needed

    # ── Queryset ──────────────────────────────────────────────────────────────

    def get_queryset(self):
        qs     = StockCountSession.objects.select_related(
            'created_by', 'snapshot_by', 'uploaded_by',
        )
        branch = self.request.query_params.get('branch_code')
        st     = self.request.query_params.get('status')
        mode   = self.request.query_params.get('mode')
        if branch:
            qs = qs.filter(branch_code=branch)
        if st:
            qs = qs.filter(status=st)
        if mode:
            qs = qs.filter(mode=mode)
        return qs.order_by('-created_at')

    # ── Serializer dispatch ───────────────────────────────────────────────────

    def get_serializer_class(self):
        if self.action == 'create':
            return StockCountSessionCreateSerializer
        if self.action == 'retrieve':
            return StockCountSessionDetailSerializer
        return StockCountSessionListSerializer

    def perform_create(self, serializer):
        profile = getattr(self.request.user, 'staff_profile', None)
        serializer.save(created_by=profile)

    def create(self, request, *args, **kwargs):
        """Override to return full session data (including id) after create."""
        ser = StockCountSessionCreateSerializer(
            data=request.data,
            context=self.get_serializer_context(),
        )
        ser.is_valid(raise_exception=True)
        self.perform_create(ser)
        # Return the full list-serializer payload so the frontend gets `id`
        response_ser = StockCountSessionListSerializer(
            ser.instance,
            context=self.get_serializer_context(),
        )
        return Response(response_ser.data, status=status.HTTP_201_CREATED)

    # ─────────────────────────────────────────────────────────────────────────
    # Action: preview_items
    # ─────────────────────────────────────────────────────────────────────────

    @action(detail=True, methods=['post'], url_path='preview-items')
    def preview_items(self, request, pk=None):
        """
        Query SOFTECH and return the list of items + current stock quantities
        that would be included in this count session.
        Does NOT write to the database.
        """
        session = self.get_object()
        from .engine import preview_items as engine_preview

        try:
            items = engine_preview(
                mode              = session.mode,
                branch_code       = session.branch_code,
                doccodes          = session.doccodes or [],
                date_from         = session.date_from.strftime('%Y-%m-%d') if session.date_from else None,
                date_to           = session.date_to.strftime('%Y-%m-%d')   if session.date_to   else None,
                user_code         = session.user_code_filter or '',
                category_filter   = session.category_filter or '',
                item_codes_filter = session.item_codes_filter or [],
            )
        except Exception as e:
            logger.exception('preview_items failed for session %s', session.pk)
            return Response(
                {'detail': f'خطأ في الاتصال بـ SOFTECH: {e}'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        doccode_detail = [
            {'code': dc, 'label': DOCCODE_LABELS.get(dc, dc)}
            for dc in (session.doccodes or [])
        ]
        return Response({
            'session_id':   session.pk,
            'session_name': session.name,
            'branch_code':  session.branch_code,
            'item_count':   len(items),
            'doccodes':     doccode_detail,
            'items': [
                {
                    'item_code':     it['item_code'],
                    'item_name':     it['item_name'],
                    'item_medicine': it.get('item_medicine', ''),
                    'category_name': it.get('category_name', ''),
                    'expected_qty':  float(it.get('qty', 0)),
                }
                for it in items
            ],
        })

    # ─────────────────────────────────────────────────────────────────────────
    # Action: generate_snapshot
    # ─────────────────────────────────────────────────────────────────────────

    @action(detail=True, methods=['post'], url_path='generate-snapshot')
    def generate_snapshot(self, request, pk=None):
        """
        Capture immutable stock snapshot for this session.
        Sets session.status = 'snapshot_taken'.
        Safe to call multiple times (re-snapshot); previous snapshots are deleted.
        """
        session = self.get_object()

        if session.status in ('variance_ready', 'closed'):
            return Response(
                {'detail': 'لا يمكن إعادة أخذ اللقطة بعد رفع نتائج الجرد'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from .engine import generate_snapshot as eng_snap

        try:
            count = eng_snap(session)
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.exception('generate_snapshot failed for session %s', session.pk)
            return Response(
                {'detail': f'خطأ في الاتصال بـ SOFTECH: {e}'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        profile = getattr(request.user, 'staff_profile', None)
        session.refresh_from_db()
        session.snapshot_by = profile
        session.save(update_fields=['snapshot_by'])

        return Response({
            'detail':       f'تم أخذ لقطة لـ {count} صنف',
            'item_count':   count,
            'snapshot_at':  session.snapshot_at,
            'session_id':   session.pk,
            'status':       session.status,
        })

    # ─────────────────────────────────────────────────────────────────────────
    # Action: export_sheet
    # ─────────────────────────────────────────────────────────────────────────

    @action(detail=True, methods=['get'], url_path='export-sheet')
    def export_sheet(self, request, pk=None):
        """
        Download the count sheet file.
        The counted_qty column is left blank for the user to fill.
        Marks session.status = 'exported' (if it was snapshot_taken).
        """
        from django.http import HttpResponse
        from .excel_io import generate_count_sheet

        session = self.get_object()

        if session.status == 'draft':
            return Response(
                {'detail': 'يجب أخذ لقطة أولاً قبل تصدير ورقة الجرد'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            content, filename, content_type = generate_count_sheet(
                session, include_variance=False
            )
        except Exception as e:
            logger.exception('export_sheet failed for session %s', session.pk)
            return Response(
                {'detail': f'خطأ أثناء توليد الملف: {e}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # Mark exported
        if session.status == 'snapshot_taken':
            session.status      = 'exported'
            session.exported_at = timezone.now()
            session.save(update_fields=['status', 'exported_at', 'updated_at'])

        response = HttpResponse(content, content_type=content_type)
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response

    # ─────────────────────────────────────────────────────────────────────────
    # Action: upload_results
    # ─────────────────────────────────────────────────────────────────────────

    @action(detail=True, methods=['post'], url_path='upload-results')
    def upload_results(self, request, pk=None):
        """
        Upload filled count sheet (xlsx or csv).
        Validates structure, matches item_codes, calculates variances.

        Multipart form:  file = <the Excel/CSV>
        """
        from .excel_io import parse_count_sheet
        from .engine import process_upload

        session = self.get_object()

        if session.status not in ('snapshot_taken', 'exported', 'uploaded', 'variance_ready'):
            return Response(
                {'detail': 'لا توجد لقطة لهذه الجلسة — يجب أخذ لقطة أولاً'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        uploaded_file = request.FILES.get('file')
        if not uploaded_file:
            return Response(
                {'detail': 'لم يتم رفع أي ملف'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Parse
        try:
            rows = parse_count_sheet(uploaded_file.read(), uploaded_file.name)
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.exception('parse_count_sheet failed for session %s', session.pk)
            return Response(
                {'detail': f'خطأ في قراءة الملف: {e}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not rows:
            return Response(
                {'detail': 'لم يتم العثور على أي بيانات في الملف'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Process
        profile = getattr(request.user, 'staff_profile', None)
        try:
            summary = process_upload(session, rows, uploaded_by=profile)
        except Exception as e:
            logger.exception('process_upload failed for session %s', session.pk)
            return Response(
                {'detail': f'خطأ أثناء معالجة البيانات: {e}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response({
            'detail':          f'تم معالجة {summary["accepted"]} صنف بنجاح',
            'processed':        summary['accepted'],       # frontend key
            'accepted':         summary['accepted'],
            'rejected':         summary['rejected'],
            'unmatched_count':  summary['unmatched'],     # frontend key
            'unmatched':        summary['unmatched'],
            'surplus_count':    summary['surplus_count'],
            'deficit_count':    summary['deficit_count'],
            'ok_count':         summary['ok_count'],
            'total_items':      summary['total_items'],
            'session_status':   session.status,
        })

    # ─────────────────────────────────────────────────────────────────────────
    # Action: count_item  (live barcode/aisle count entry)
    # ─────────────────────────────────────────────────────────────────────────

    @action(detail=True, methods=['post'], url_path='count-item')
    def count_item(self, request, pk=None):
        """
        Record a single counted item live from the floor (mobile barcode entry).
        Body: { item_code, counted_qty }. item_code = SOFTECH itemcode (catalog
        softech_id). Computes variance instantly; never mutates expected_qty.
        """
        from decimal import Decimal, InvalidOperation
        from .engine import apply_single_count
        from .models import StockCountSnapshot

        session = self.get_object()
        if session.status == 'draft':
            return Response({'detail': 'يجب أخذ اللقطة أولاً قبل الجرد'}, status=status.HTTP_400_BAD_REQUEST)
        if session.status == 'closed':
            return Response({'detail': 'الجلسة مغلقة'}, status=status.HTTP_400_BAD_REQUEST)

        code = str(request.data.get('item_code', '')).strip()
        if not code:
            return Response({'detail': 'كود الصنف مطلوب'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            counted = Decimal(str(request.data.get('counted_qty')))
        except (InvalidOperation, TypeError, ValueError):
            return Response({'detail': 'كمية غير صالحة'}, status=status.HTTP_400_BAD_REQUEST)
        if counted < 0:
            return Response({'detail': 'الكمية يجب ألا تكون سالبة'}, status=status.HTTP_400_BAD_REQUEST)

        physical_expiry = request.data.get('physical_expiry')  # optional 'YYYY-MM-DD'

        profile = getattr(request.user, 'staff_profile', None)
        snap = apply_single_count(session, code, counted, by=profile,
                                  physical_expiry=physical_expiry)
        if snap is None:
            return Response({'detail': 'هذا الصنف ليس ضمن نطاق هذه الجلسة'}, status=status.HTTP_404_NOT_FOUND)

        total      = StockCountSnapshot.objects.filter(session=session).count()
        counted_n  = StockCountSnapshot.objects.filter(session=session, counted_qty__isnull=False).count()
        VLABEL = {'ok': 'مطابق', 'surplus': 'زيادة', 'deficit': 'نقص'}
        return Response({
            'item_code':      snap.item_code,
            'item_name':      snap.item_name,
            'expected_qty':   float(snap.expected_qty),
            'counted_qty':    float(snap.counted_qty),
            'difference':     float(snap.difference),
            'variance_type':  snap.variance_type,
            'variance_label': VLABEL.get(snap.variance_type, ''),
            'entered_expiry_hint': snap.entered_expiry_hint.isoformat() if snap.entered_expiry_hint else None,
            'physical_expiry':     snap.physical_expiry.isoformat() if snap.physical_expiry else None,
            'progress':       {'counted': counted_n, 'total': total},
            'session_status': session.status,
        })

    # ─────────────────────────────────────────────────────────────────────────
    # Action: variance_report
    # ─────────────────────────────────────────────────────────────────────────

    @action(detail=True, methods=['get'], url_path='variance-report')
    def variance_report(self, request, pk=None):
        """
        Return full variance report as JSON.

        Query params:
          ?variance_type=surplus|deficit|ok|all  (default: all)
          ?min_abs_diff=<number>                 (filter by minimum absolute difference)
        """
        session = self.get_object()

        if session.status not in ('uploaded', 'variance_ready', 'closed'):
            return Response(
                {'detail': 'لا توجد نتائج جرد لهذه الجلسة بعد'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        qs = session.snapshots.all()

        # Filter by variance type
        vtype = request.query_params.get('variance_type', 'all')
        if vtype in ('surplus', 'deficit', 'ok'):
            qs = qs.filter(variance_type=vtype)
        elif vtype == 'discrepancy':   # surplus + deficit
            qs = qs.filter(variance_type__in=['surplus', 'deficit'])

        # Filter by minimum absolute difference
        min_diff = request.query_params.get('min_abs_diff')
        if min_diff:
            try:
                from django.db.models import Func, FloatField
                from decimal import Decimal
                threshold = Decimal(min_diff)
                qs = [s for s in qs if s.difference is not None and abs(s.difference) >= threshold]
            except Exception:
                pass

        # Sort: by absolute difference descending (biggest discrepancies first)
        snapshots = sorted(
            qs if isinstance(qs, list) else list(qs),
            key=lambda s: abs(s.difference or 0),
            reverse=True,
        )

        rows = []
        for s in snapshots:
            rows.append({
                'item_code':      s.item_code,
                'item_name':      s.item_name,
                'item_medicine':  s.item_medicine,
                'category_name':  s.category_name,
                'expected_qty':   float(s.expected_qty),
                'counted_qty':    float(s.counted_qty) if s.counted_qty is not None else None,
                'difference':     float(s.difference)  if s.difference  is not None else None,
                'variance_type':  s.variance_type,
                'erp_doccode':    '50' if s.variance_type == 'surplus' else ('150' if s.variance_type == 'deficit' else ''),
            })

        # Summary
        all_snaps = list(session.snapshots.all())
        total_surplus_qty = sum(
            float(s.difference) for s in all_snaps
            if s.variance_type == 'surplus' and s.difference
        )
        total_deficit_qty = sum(
            abs(float(s.difference)) for s in all_snaps
            if s.variance_type == 'deficit' and s.difference
        )

        return Response({
            'session_id':     session.pk,
            'session_name':   session.name,
            'branch_code':    session.branch_code,
            'snapshot_at':    session.snapshot_at,
            'uploaded_at':    session.uploaded_at,
            'summary': {
                'item_count':    session.item_count,
                'surplus_count': session.surplus_count,
                'deficit_count': session.deficit_count,
                'ok_count':      session.ok_count,
                'not_counted':   session.item_count - session.surplus_count - session.deficit_count - session.ok_count,
                'total_surplus_qty': round(total_surplus_qty, 3),
                'total_deficit_qty': round(total_deficit_qty, 3),
            },
            'items':          rows,       # named 'items' to match frontend
            'filter_applied': vtype,
        })

    # ─────────────────────────────────────────────────────────────────────────
    # Action: adjustment_export
    # ─────────────────────────────────────────────────────────────────────────

    @action(detail=True, methods=['get'], url_path='adjustment-export')
    def adjustment_export(self, request, pk=None):
        """
        Download the variance/adjustment sheet (xlsx or csv).
        Rows are colour-coded: green=surplus, red=deficit.
        Includes ERP doccode mapping: surplus→50, deficit→150.
        """
        from django.http import HttpResponse
        from .excel_io import generate_count_sheet

        session = self.get_object()

        if session.status not in ('uploaded', 'variance_ready', 'closed'):
            return Response(
                {'detail': 'لا توجد نتائج جرد لهذه الجلسة بعد'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            content, filename, content_type = generate_count_sheet(
                session, include_variance=True
            )
        except Exception as e:
            logger.exception('adjustment_export failed for session %s', session.pk)
            return Response(
                {'detail': f'خطأ أثناء توليد الملف: {e}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        response = HttpResponse(content, content_type=content_type)
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response

    # ─────────────────────────────────────────────────────────────────────────
    # Action: snapshots (sub-list)
    # ─────────────────────────────────────────────────────────────────────────

    @action(detail=True, methods=['get'], url_path='snapshots')
    def snapshots_list(self, request, pk=None):
        """
        Paginated list of snapshots for this session.
        ?variance_type=surplus|deficit|ok|all
        ?search=<text>  (searches item_code and item_name)
        """
        session = self.get_object()
        qs      = session.snapshots.all()

        vtype = request.query_params.get('variance_type')
        if vtype in ('surplus', 'deficit', 'ok'):
            qs = qs.filter(variance_type=vtype)

        search = request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(
                item_code__icontains=search
            ) | qs.filter(
                item_name__icontains=search
            )

        paginator = SnapshotPagination()
        page      = paginator.paginate_queryset(qs, request)
        ser       = StockCountSnapshotSerializer(page, many=True)
        return paginator.get_paginated_response(ser.data)

    # ─────────────────────────────────────────────────────────────────────────
    # Action: close session
    # ─────────────────────────────────────────────────────────────────────────

    @action(detail=True, methods=['post'], url_path='close')
    def close_session(self, request, pk=None):
        session = self.get_object()
        if session.status == 'closed':
            return Response({'detail': 'الجلسة مغلقة بالفعل'})
        session.status     = 'closed'
        session.updated_at = timezone.now()
        session.save(update_fields=['status', 'updated_at'])
        return Response({'detail': 'تم إغلاق جلسة الجرد', 'status': 'closed'})
