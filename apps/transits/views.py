"""
apps/transits/views.py

Transfers In Transit — REST API ViewSet.

Endpoints:
    GET  /api/transits/               — paginated list (grid)
    GET  /api/transits/{id}/          — full detail
    POST /api/transits/{id}/mark-received/   — mark as locally received
    POST /api/transits/{id}/add-note/        — add internal note
    POST /api/transits/{id}/force-close/     — admin: force close
    POST /api/transits/sync/                 — admin: trigger SOFTECH sync
    GET  /api/transits/dashboard/            — KPI widget data
    GET  /api/transits/analytics/            — full analytics

Role rules:
    - All authenticated branch staff can VIEW transfers for their own branches.
    - mark-received:  receiving branch staff + admin/purchasing
    - add-note:       any authenticated branch staff
    - force-close:    admin only
    - sync:           admin + purchasing
"""
import logging
from decimal import Decimal

from django.db import models as db_models
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import InTransitAuditEvent, InTransitNote, InTransitTransfer
from .serializers import (
    ForceCloseSerializer,
    InTransitNoteCreateSerializer,
    InTransitTransferDetailSerializer,
    InTransitTransferListSerializer,
    MarkReceivedSerializer,
    TransitDashboardSerializer,
)

logger = logging.getLogger('elrezeiky.transits')


def _profile(request):
    return getattr(request.user, 'staff_profile', None)


def _is_hq(profile):
    return profile and profile.role in ('admin', 'purchasing', 'call_center')


def _notify_transit(transfer, title, body, notif_type, *, branch=None, include_admins=True):
    """Fire in-app notification — non-fatal."""
    try:
        from apps.notifications.models import Notification
        target = branch or transfer.receiving_branch or transfer.supplying_branch
        if target:
            Notification.send_to_branch(
                branch=target,
                notification_type=notif_type,
                title=title,
                body=body or '',
                transfer_id=(
                    transfer.linked_request_id
                    if transfer.linked_request_id else None
                ),
                dedup_key=f'{notif_type}_{transfer.id}',
                include_admins=include_admins,
            )
    except Exception as exc:
        logger.warning('_notify_transit failed (non-fatal): %s', exc)


class InTransitTransferViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Transfers In Transit — read-only viewset + custom write actions.
    Uses ReadOnlyModelViewSet to prevent any accidental PATCH/DELETE on the
    cached SOFTECH data. Write actions are explicit @action decorators.
    """

    permission_classes = [IsAuthenticated]
    filter_backends    = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_fields   = [
        'transit_status', 'priority',
        'supplying_branch', 'receiving_branch',
        'cancellation_available', 'has_discrepancy',
    ]
    search_fields      = [
        'erp_doc_number',
        'erp_supplying_branch_code',
        'erp_receiving_branch_code',
    ]
    # Every grid column is sortable (asc/desc via the OrderingFilter `ordering`
    # param). The annotated keys below give MEANINGFUL orders where the raw
    # column would mislead: doc number sorts numerically (not '1000' < '999'),
    # priority sorts by severity (not alphabetically), and branches sort by
    # their resolved display name (falling back to the ERP code).
    ordering_fields    = [
        'doc_number_num', 'priority_rank',
        'supply_sort', 'recv_sort',
        'issue_date', 'days_in_transit', 'item_count', 'doc_value',
        'transit_status', 'cancellation_available',
        'last_synced_at',
    ]
    ordering           = ['-days_in_transit', '-issue_date']

    def get_queryset(self):
        from django.db.models import Case, IntegerField, Value, When
        from django.db.models.functions import Cast, Coalesce

        qs = InTransitTransfer.objects.select_related(
            'supplying_branch',
            'receiving_branch',
            'linked_request',
            'manually_received_by',
        ).prefetch_related(
            'notes__created_by',
        ).annotate(
            # numeric doc number (SOFTECH docnumbers are numeric strings)
            doc_number_num=Cast('erp_doc_number', output_field=db_models.BigIntegerField()),
            # severity order for priority (green → critical)
            priority_rank=Case(
                When(priority='green',    then=Value(0)),
                When(priority='yellow',   then=Value(1)),
                When(priority='orange',   then=Value(2)),
                When(priority='red',      then=Value(3)),
                When(priority='critical', then=Value(4)),
                default=Value(0),
                output_field=IntegerField(),
            ),
            # branch display-name sort keys (resolved name, else ERP code)
            supply_sort=Coalesce(
                'supplying_branch__name_ar', 'supplying_branch__name',
                'erp_supplying_branch_code',
            ),
            recv_sort=Coalesce(
                'receiving_branch__name_ar', 'receiving_branch__name',
                'erp_receiving_branch_code',
            ),
        )

        profile = _profile(self.request)
        if not profile:
            return qs.none()

        # HQ roles see everything
        if _is_hq(profile):
            pass
        elif profile.branch:
            qs = qs.filter(
                db_models.Q(supplying_branch=profile.branch) |
                db_models.Q(receiving_branch=profile.branch)
            )
        else:
            return qs.none()

        # Extra query-param filters
        qp = self.request.query_params

        date_from = qp.get('date_from')
        date_to   = qp.get('date_to')
        try:
            if date_from:
                qs = qs.filter(issue_date__gte=date_from)
            if date_to:
                qs = qs.filter(issue_date__lte=date_to)
        except Exception:
            pass

        min_days = qp.get('min_days')
        try:
            if min_days:
                qs = qs.filter(days_in_transit__gte=int(min_days))
        except (ValueError, TypeError):
            pass

        return qs

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return InTransitTransferDetailSerializer
        return InTransitTransferListSerializer

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        profile  = _profile(request)
        # Audit: log every view
        InTransitAuditEvent.log(
            instance, 'viewed',
            actor=profile,
            detail=f'عُرض التفصيل من قِبَل {profile.full_name if profile else "مجهول"}',
        )
        return super().retrieve(request, *args, **kwargs)

    # ── Picking-sheet export (ورقة التجميع) ───────────────────────────────────

    MAX_PICKING_EXPORT = 30   # orders per workbook — keeps the matrix printable

    def _sheet_response(self, request, transfers, mode):
        """Generate the workbook (picking/stocking), audit, return download."""
        from django.http import HttpResponse
        from .export import generate_picking_workbook

        label = 'ورقة تجميع' if mode == 'picking' else 'ورقة ترصيص'
        profile = _profile(request)
        try:
            content, filename, content_type = generate_picking_workbook(
                transfers, mode=mode)
        except Exception as exc:
            logger.exception('export-%s failed (%d transfers)', mode, len(transfers))
            return Response(
                {'detail': f'خطأ أثناء توليد {label}: {exc}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        for t in transfers:
            InTransitAuditEvent.log(
                t, 'exported', actor=profile,
                detail=f'{label} ({len(transfers)} إذن) — {filename}',
            )

        response = HttpResponse(content, content_type=content_type)
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response

    def _bulk_sheet_response(self, request, mode):
        """Shared bulk handler for export-picking / export-stocking."""
        ids = request.data.get('ids') or []
        if not isinstance(ids, list) or not ids:
            return Response({'detail': 'حدد أذونات الصرف المطلوب تصديرها (ids)'},
                            status=status.HTTP_400_BAD_REQUEST)
        if len(ids) > self.MAX_PICKING_EXPORT:
            return Response(
                {'detail': f'الحد الأقصى {self.MAX_PICKING_EXPORT} إذن في التصدير الواحد'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        transfers = list(
            self.get_queryset()
            .filter(id__in=ids)
            .order_by('erp_receiving_branch_code', 'erp_doc_number')
        )
        if not transfers:
            return Response({'detail': 'لا توجد أذونات مطابقة'},
                            status=status.HTTP_404_NOT_FOUND)

        return self._sheet_response(request, transfers, mode)

    @action(detail=True, methods=['get'], url_path='export-picking')
    def export_picking(self, request, pk=None):
        """
        GET /api/transits/{id}/export-picking/

        ورقة التجميع — picking + revision workbook, ordered by the SUPPLYING
        warehouse's picking config (مسار التجميع).
        """
        return self._sheet_response(request, [self.get_object()], 'picking')

    @action(detail=False, methods=['post'], url_path='export-picking')
    def export_picking_bulk(self, request):
        """
        POST /api/transits/export-picking/   body: {"ids": [1, 2, …]}

        Bulk ورقة التجميع: consolidated pick matrix (one qty column per order)
        + a revision sheet per order. Ids the caller cannot view are excluded.
        """
        return self._bulk_sheet_response(request, 'picking')

    @action(detail=True, methods=['get'], url_path='export-stocking')
    def export_stocking(self, request, pk=None):
        """
        GET /api/transits/{id}/export-stocking/

        ورقة الترصيص — same workbook structure but ordered by the RECEIVING
        branch's stocking config (ترتيب أرفف الفرع) so shelving is one walk.
        """
        return self._sheet_response(request, [self.get_object()], 'stocking')

    @action(detail=False, methods=['post'], url_path='export-stocking')
    def export_stocking_bulk(self, request):
        """
        POST /api/transits/export-stocking/   body: {"ids": [1, 2, …]}

        Bulk ورقة الترصيص — consolidated shelf-walk matrix + per-order sheets,
        classified by each order's receiving branch stocking config.
        """
        return self._bulk_sheet_response(request, 'stocking')

    # ── Mark Received ─────────────────────────────────────────────────────────

    @action(detail=True, methods=['post'], url_path='mark-received')
    def mark_received(self, request, pk=None):
        """
        POST /api/transits/{id}/mark-received/

        Mark a transfer as received locally. This does NOT touch SOFTECH.
        The next sync job will independently confirm ERP-side receipt.
        Allowed: receiving branch staff + admin/purchasing.
        """
        transfer = self.get_object()
        profile  = _profile(request)

        # Permission: receiving branch or HQ
        if not _is_hq(profile):
            if not (profile and profile.branch_id == transfer.receiving_branch_id):
                return Response(
                    {'detail': 'فقط موظفو الفرع المستلم أو المشرفون يمكنهم تسجيل الاستلام'},
                    status=status.HTTP_403_FORBIDDEN,
                )

        if transfer.transit_status not in ('in_transit', 'expired_pending'):
            return Response(
                {'detail': 'لا يمكن تسجيل الاستلام — حالة التحويل غير مؤهلة'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if transfer.manually_received_at:
            return Response(
                {'detail': 'تم تسجيل الاستلام مسبقاً'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ser = MarkReceivedSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        note_body = ser.validated_data.get('note', '').strip()

        now = timezone.now()
        transfer.transit_status     = 'received'
        transfer.manually_received_at = now
        transfer.manually_received_by = profile
        transfer.priority           = 'green'
        transfer.save(update_fields=[
            'transit_status', 'manually_received_at',
            'manually_received_by', 'priority', 'updated_at',
        ])

        # System note
        actor_name = profile.full_name if profile else 'مجهول'
        body = f'تم تسجيل الاستلام بواسطة {actor_name}'
        if note_body:
            body += f' — ملاحظة: {note_body}'
        InTransitNote.log_system(transfer, body)
        if note_body:
            InTransitNote.objects.create(
                transfer=transfer,
                note_type='note',
                body=note_body,
                created_by=profile,
            )

        InTransitAuditEvent.log(
            transfer, 'received',
            actor=profile,
            detail=body,
        )

        # Notify supplying branch that receipt was recorded
        _notify_transit(
            transfer,
            f'تم استلام تحويل {transfer.erp_doc_number}',
            f'سجّل فرع {transfer.receiving_branch} استلام التحويل.',
            'transit_received',
            branch=transfer.supplying_branch,
        )

        return Response(
            InTransitTransferDetailSerializer(
                transfer, context={'request': request}
            ).data
        )

    # ── Add Note ──────────────────────────────────────────────────────────────

    @action(detail=True, methods=['post'], url_path='add-note')
    def add_note(self, request, pk=None):
        """POST /api/transits/{id}/add-note/"""
        transfer = self.get_object()
        profile  = _profile(request)

        ser = InTransitNoteCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        note = InTransitNote.objects.create(
            transfer=transfer,
            note_type='note',
            body=ser.validated_data['body'],
            created_by=profile,
        )
        InTransitAuditEvent.log(
            transfer, 'note_added',
            actor=profile,
            detail=ser.validated_data['body'][:200],
        )

        from .serializers import InTransitNoteSerializer
        return Response(
            InTransitNoteSerializer(note).data,
            status=status.HTTP_201_CREATED,
        )

    # ── Force Close (admin only) ──────────────────────────────────────────────

    @action(detail=True, methods=['post'], url_path='force-close')
    def force_close(self, request, pk=None):
        """POST /api/transits/{id}/force-close/ — admin only."""
        transfer = self.get_object()
        profile  = _profile(request)

        if not profile or profile.role not in ('admin', 'purchasing'):
            return Response(
                {'detail': 'هذا الإجراء مخصص للمديرين ومسؤولي المشتريات فقط'},
                status=status.HTTP_403_FORBIDDEN,
            )

        if transfer.transit_status in ('received', 'force_closed'):
            return Response(
                {'detail': 'التحويل مُغلق بالفعل'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ser = ForceCloseSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        reason = ser.validated_data['reason']

        transfer.transit_status   = 'force_closed'
        transfer.force_close_reason = reason
        transfer.force_closed_by  = profile
        transfer.save(update_fields=[
            'transit_status', 'force_close_reason',
            'force_closed_by', 'updated_at',
        ])

        InTransitNote.log_system(
            transfer,
            f'🔒 أُغلق قسراً بواسطة {profile.full_name} — السبب: {reason}',
        )
        InTransitAuditEvent.log(
            transfer, 'force_closed',
            actor=profile,
            detail=reason,
        )

        return Response(
            InTransitTransferDetailSerializer(
                transfer, context={'request': request}
            ).data
        )

    # ── Manual SOFTECH Sync ───────────────────────────────────────────────────

    @action(detail=False, methods=['post'], url_path='sync')
    def trigger_sync(self, request):
        """
        POST /api/transits/sync/
        Admin / purchasing — manually trigger the SOFTECH sync job.
        Returns immediately; sync runs in background thread.
        """
        profile = _profile(request)
        if not profile or profile.role not in ('admin', 'purchasing'):
            return Response(
                {'detail': 'هذا الإجراء مخصص للمديرين ومسؤولي المشتريات'},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            from django.core.management import call_command
            import threading
            t = threading.Thread(
                target=call_command,
                args=('sync_in_transit',),
                kwargs={'verbosity': 0},
                daemon=True,
            )
            t.start()
        except Exception as exc:
            logger.error('Manual transit sync trigger failed: %s', exc)
            return Response(
                {'detail': f'فشل تشغيل المزامنة: {exc}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response({'detail': 'بدأت المزامنة في الخلفية — ستظهر النتائج خلال دقيقة.'})

    # ── Dashboard Widget ──────────────────────────────────────────────────────

    @action(detail=False, methods=['get'], url_path='dashboard')
    def dashboard(self, request):
        """GET /api/transits/dashboard/ — KPI widget."""
        import datetime
        from django.db.models import Avg, Count, Sum

        profile = _profile(request)
        if not profile:
            return Response({'detail': 'غير مصرح'}, status=status.HTTP_403_FORBIDDEN)

        qs = InTransitTransfer.objects.all()
        if not _is_hq(profile) and profile.branch:
            qs = qs.filter(
                db_models.Q(supplying_branch=profile.branch) |
                db_models.Q(receiving_branch=profile.branch)
            )

        today = datetime.date.today()

        in_transit_qs = qs.filter(transit_status='in_transit')

        agg = in_transit_qs.aggregate(
            total=Count('id'),
            total_value=Sum('doc_value'),
            avg_days=Avg('days_in_transit'),
        )

        priority_counts = {
            p: in_transit_qs.filter(priority=p).count()
            for p in ('critical', 'red', 'orange', 'yellow', 'green')
        }

        received_today = qs.filter(
            transit_status='received',
            manually_received_at__date=today,
        ).count()

        issued_today = qs.filter(issue_date=today).count()

        erp_mismatch_count = qs.filter(transit_status='erp_mismatch').count()

        cancel_cutoff = today + datetime.timedelta(days=1)
        cancellation_expiring = in_transit_qs.filter(
            cancellation_available=True,
            cancellation_expires_at__lte=cancel_cutoff,
        ).count()

        # Per-branch breakdowns
        by_supplying = list(
            in_transit_qs
            .values('supplying_branch__name_ar', 'supplying_branch__name', 'erp_supplying_branch_code')
            .annotate(count=Count('id'), value=Sum('doc_value'))
            .order_by('-count')[:10]
        )
        by_receiving = list(
            in_transit_qs
            .values('receiving_branch__name_ar', 'receiving_branch__name', 'erp_receiving_branch_code')
            .annotate(count=Count('id'), value=Sum('doc_value'))
            .order_by('-count')[:10]
        )

        data = {
            'total_in_transit':      agg['total'] or 0,
            'total_value':           agg['total_value'],
            'avg_days_in_transit':   round(agg['avg_days'], 1) if agg['avg_days'] else None,
            'critical_count':        priority_counts['critical'],
            'red_count':             priority_counts['red'],
            'orange_count':          priority_counts['orange'],
            'received_today':        received_today,
            'issued_today':          issued_today,
            'erp_mismatch_count':    erp_mismatch_count,
            'cancellation_expiring': cancellation_expiring,
            'by_supplying_branch':   by_supplying,
            'by_receiving_branch':   by_receiving,
        }

        return Response(data)

    # ── Analytics ─────────────────────────────────────────────────────────────

    @action(detail=False, methods=['get'], url_path='analytics')
    def analytics(self, request):
        """GET /api/transits/analytics/?days=30"""
        import datetime
        from django.db.models import Avg, Count, Sum

        profile = _profile(request)
        if not profile:
            return Response({'detail': 'غير مصرح'}, status=status.HTTP_403_FORBIDDEN)

        try:
            days = int(request.query_params.get('days', 30))
            days = max(7, min(days, 365))
        except (ValueError, TypeError):
            days = 30

        since = datetime.date.today() - datetime.timedelta(days=days)

        qs = InTransitTransfer.objects.filter(issue_date__gte=since)
        if not _is_hq(profile) and profile.branch:
            qs = qs.filter(
                db_models.Q(supplying_branch=profile.branch) |
                db_models.Q(receiving_branch=profile.branch)
            )

        total   = qs.count()
        in_tr   = qs.filter(transit_status='in_transit').count()
        received = qs.filter(transit_status='received').count()
        cancelled = qs.filter(transit_status='cancelled').count()
        force_closed = qs.filter(transit_status='force_closed').count()

        avg_transit_days = qs.filter(
            transit_status='received'
        ).aggregate(a=Avg('days_in_transit'))['a']

        # Priority distribution
        priority_dist = list(
            qs.filter(transit_status='in_transit')
            .values('priority')
            .annotate(count=Count('id'))
            .order_by('priority')
        )

        # Aging histogram (in-transit only)
        aging = {
            '0-2':   qs.filter(transit_status='in_transit', days_in_transit__lte=2).count(),
            '3-4':   qs.filter(transit_status='in_transit', days_in_transit__range=(3,4)).count(),
            '5-6':   qs.filter(transit_status='in_transit', days_in_transit__range=(5,6)).count(),
            '7-9':   qs.filter(transit_status='in_transit', days_in_transit__range=(7,9)).count(),
            '10+':   qs.filter(transit_status='in_transit', days_in_transit__gte=10).count(),
        }

        # Branch delay ranking (receiving branch with most overdue)
        delay_ranking = list(
            qs.filter(transit_status='in_transit', days_in_transit__gte=7)
            .values(
                'receiving_branch__name_ar',
                'receiving_branch__name',
                'erp_receiving_branch_code',
            )
            .annotate(
                overdue_count=Count('id'),
                total_value=Sum('doc_value'),
                avg_days=Avg('days_in_transit'),
            )
            .order_by('-overdue_count')[:10]
        )

        return Response({
            'days':              days,
            'total':             total,
            'in_transit':        in_tr,
            'received':          received,
            'cancelled':         cancelled,
            'force_closed':      force_closed,
            'avg_transit_days':  round(avg_transit_days, 1) if avg_transit_days else None,
            'priority_dist':     priority_dist,
            'aging':             aging,
            'delay_ranking':     delay_ranking,
        })

    # ── Branch Accountability Scorecard ───────────────────────────────────────

    @action(detail=False, methods=['get'], url_path='scorecard')
    def scorecard(self, request):
        """
        GET /api/transits/scorecard/?days=90

        Branch accountability ranking by RECEIVING branch:
          - fastest_receivers / slowest_receivers (avg days to receive, ≥3 sample)
          - highest_floating  (branches sitting on the most floating value)
          - most_mismatches   (branches with the most 125↔25 discrepancies)
        """
        import datetime
        from django.db.models import Avg, Count, Sum, Q

        profile = _profile(request)
        if not profile:
            return Response({'detail': 'غير مصرح'}, status=status.HTTP_403_FORBIDDEN)

        try:
            days = int(request.query_params.get('days', 90))
            days = max(7, min(days, 365))
        except (ValueError, TypeError):
            days = 90

        since = datetime.date.today() - datetime.timedelta(days=days)

        base = InTransitTransfer.objects.all()
        if not _is_hq(profile) and profile.branch:
            base = base.filter(
                db_models.Q(supplying_branch=profile.branch) |
                db_models.Q(receiving_branch=profile.branch)
            )

        # Received (incl. mismatched) within window — grouped by receiving branch
        received_rows = (
            base.filter(
                transit_status__in=('received', 'erp_mismatch'),
                erp_received_date__gte=since,
            )
            .exclude(receiving_branch__isnull=True)
            .values('receiving_branch', 'receiving_branch__name_ar', 'receiving_branch__name')
            .annotate(
                received_count=Count('id'),
                avg_receive_days=Avg('days_in_transit'),
                mismatch_count=Count('id', filter=Q(transit_status='erp_mismatch')),
            )
        )

        # Currently floating — grouped by receiving branch
        floating_rows = (
            base.filter(transit_status='in_transit')
            .exclude(receiving_branch__isnull=True)
            .values('receiving_branch', 'receiving_branch__name_ar', 'receiving_branch__name')
            .annotate(
                floating_count=Count('id'),
                floating_value=Sum('doc_value'),
                overdue_count=Count('id', filter=Q(days_in_transit__gte=7)),
            )
        )

        def _blank(bid, name):
            return {
                'branch_id': bid, 'branch_name': name,
                'received_count': 0, 'avg_receive_days': None, 'mismatch_count': 0,
                'floating_count': 0, 'floating_value': 0.0, 'overdue_count': 0,
            }

        rows = {}
        for r in received_rows:
            bid = r['receiving_branch']
            row = rows.setdefault(bid, _blank(
                bid, r['receiving_branch__name_ar'] or r['receiving_branch__name']))
            row['received_count']   = r['received_count']
            row['avg_receive_days'] = (
                round(r['avg_receive_days'], 1) if r['avg_receive_days'] is not None else None)
            row['mismatch_count']   = r['mismatch_count']
        for f in floating_rows:
            bid = f['receiving_branch']
            row = rows.setdefault(bid, _blank(
                bid, f['receiving_branch__name_ar'] or f['receiving_branch__name']))
            row['floating_count'] = f['floating_count']
            row['floating_value'] = float(f['floating_value'] or 0)
            row['overdue_count']  = f['overdue_count']

        all_rows = list(rows.values())

        # Fastest/slowest need a meaningful sample to be fair
        ranked = [r for r in all_rows
                  if r['received_count'] >= 3 and r['avg_receive_days'] is not None]

        return Response({
            'days':               days,
            'branches':           sorted(all_rows, key=lambda r: r['floating_value'], reverse=True),
            'fastest_receivers':  sorted(ranked, key=lambda r: r['avg_receive_days'])[:5],
            'slowest_receivers':  sorted(ranked, key=lambda r: r['avg_receive_days'], reverse=True)[:5],
            'highest_floating':   sorted([r for r in all_rows if r['floating_value'] > 0],
                                         key=lambda r: r['floating_value'], reverse=True)[:5],
            'most_mismatches':    sorted([r for r in all_rows if r['mismatch_count'] > 0],
                                         key=lambda r: r['mismatch_count'], reverse=True)[:5],
        })


# ══════════════════════════════════════════════════════════════════════════════
# Pick-zone management (replenishment picking-sheet classification)
#   /api/transits/pick-zones/       — zones (pick path, locations, special roles)
#   /api/transits/pick-rules/       — keyword rules, ordered by priority
#   /api/transits/item-overrides/   — per-item zone assignments (beats rules)
# Managed from the /pick-zones frontend. Read: any staff. Write: admin/purchasing.
# ══════════════════════════════════════════════════════════════════════════════

from rest_framework.permissions import SAFE_METHODS, BasePermission

from .models import ItemPickOverride, PickZone, PickZoneRule
from .serializers import (
    ItemPickOverrideSerializer,
    PickZoneRuleSerializer,
    PickZoneSerializer,
)


class PickZoneManagePermission(BasePermission):
    """Read for all authenticated staff; write for admin/purchasing only."""
    message = 'إدارة مناطق التجميع متاحة للإدارة والمشتريات فقط'

    # POST actions that only READ (computation, no mutation) — open to all staff
    READONLY_ACTIONS = ('preview', 'classify_items')

    def has_permission(self, request, view):
        profile = _profile(request)
        if not (request.user and request.user.is_authenticated and profile):
            return False
        if request.method in SAFE_METHODS:
            return True
        if getattr(view, 'action', None) in self.READONLY_ACTIONS:
            return True
        return profile.role in ('admin', 'purchasing')


def _branch_param(request):
    """?branch= → branch id or None (''/absent/'default' = the default config)."""
    raw = str(request.query_params.get('branch') or '').strip()
    if not raw or raw == 'default':
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _purpose_param(request):
    """?purpose= / body purpose → 'picking' (default) or 'stocking'."""
    raw = str(
        request.query_params.get('purpose')
        or getattr(request, 'data', {}).get('purpose', '')
        or ''
    ).strip()
    return raw if raw in ('picking', 'stocking') else 'picking'


class PickZoneViewSet(viewsets.ModelViewSet):
    serializer_class   = PickZoneSerializer
    permission_classes = [PickZoneManagePermission]
    pagination_class   = None

    def get_queryset(self):
        qs = PickZone.objects.annotate(
            rule_count=db_models.Count('rules', distinct=True),
            override_count=db_models.Count('item_overrides', distinct=True),
        ).order_by('sort_key', 'name')
        # scope to one config = (location, purpose)
        qs = qs.filter(purpose=_purpose_param(self.request))
        if 'branch' in self.request.query_params:
            branch_id = _branch_param(self.request)
            qs = qs.filter(branch_id=branch_id) if branch_id else qs.filter(branch__isnull=True)
        return qs

    def _enforce_exclusive_roles(self, zone):
        """Only one zone per (LOCATION, PURPOSE) config may hold each role."""
        for flag in ('is_price_zone', 'is_fridge_zone', 'is_fallback'):
            if getattr(zone, flag):
                PickZone.objects.exclude(pk=zone.pk).filter(
                    branch=zone.branch, purpose=zone.purpose,
                    **{flag: True}).update(**{flag: False})

    def perform_create(self, serializer):
        zone = serializer.save()
        self._enforce_exclusive_roles(zone)

    def perform_update(self, serializer):
        zone = serializer.save()
        self._enforce_exclusive_roles(zone)

    # ── Threshold setting ─────────────────────────────────────────────────────

    @action(detail=False, methods=['get', 'post'], url_path='settings')
    def zone_settings(self, request):
        """
        GET  → {price_threshold}
        POST → {price_threshold: <int>} updates the SystemSetting.
        """
        from apps.config.models import SystemSetting
        from .export import PRICE_THRESHOLD_DEFAULT

        if request.method == 'POST':
            try:
                threshold = int(float(request.data.get('price_threshold')))
                if threshold <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                return Response({'detail': 'قيمة حد الغوالي غير صالحة'},
                                status=status.HTTP_400_BAD_REQUEST)
            SystemSetting.objects.update_or_create(
                key='replenishment_price_threshold',
                defaults={'value': str(threshold), 'value_type': 'integer',
                          'label': 'حد سعر الغوالي (ج.م)',
                          'category': 'transfers'},
            )
            return Response({'price_threshold': threshold})

        threshold = SystemSetting.get('replenishment_price_threshold',
                                      PRICE_THRESHOLD_DEFAULT)
        return Response({'price_threshold': threshold})

    # ── Live classification preview (rule tester) ─────────────────────────────

    @action(detail=False, methods=['post'], url_path='preview')
    def preview(self, request):
        """
        POST {name, price?, requires_fridge?, item_code?}
        → {zone_id, zone_name, reason} — how the item classifies right now.
        """
        from .export import build_ruleset

        name = str(request.data.get('name') or '').strip()
        code = str(request.data.get('item_code') or '').strip() or None
        if not name and not code:
            return Response({'detail': 'أدخل اسم صنف أو كوده'},
                            status=status.HTTP_400_BAD_REQUEST)

        price  = request.data.get('price')
        fridge = bool(request.data.get('requires_fridge'))
        attrs  = None

        if code:
            from apps.catalog.models import Item
            from .export import ATTR_COLUMNS
            item = Item.objects.filter(softech_id=code).first()
            if item:
                name   = name or item.name
                price  = item.pack_price if price in (None, '') else price
                fridge = fridge or item.requires_fridge
                attrs  = {col: getattr(item, col, '') for col in ATTR_COLUMNS}

        branch_id = request.data.get('branch') or _branch_param(request)
        ruleset = build_ruleset(item_codes=[code] if code else [],
                                branch=branch_id,
                                purpose=_purpose_param(request))
        zone, tag, reason = ruleset.explain(name, price, fridge,
                                            itemcode=code, attrs=attrs)
        return Response({
            'zone_id':   getattr(zone, 'id', None),
            'zone_name': zone.name if zone else None,
            'tag':       tag,
            'reason':    reason,
        })

    # ── Uncategorized items (fallback-zone hits) ──────────────────────────────

    @action(detail=False, methods=['get'], url_path='uncategorized')
    def uncategorized(self, request):
        """
        GET ?q=&limit=  → active catalog items that currently land in the
        fallback zone (excluding overridden items), for reclassification.
        """
        from apps.catalog.models import Item
        from .export import build_ruleset

        q = str(request.query_params.get('q') or '').strip()
        try:
            limit = min(max(int(request.query_params.get('limit', 100)), 1), 500)
        except (TypeError, ValueError):
            limit = 100

        from .export import ATTR_COLUMNS
        branch_id = _branch_param(request)
        ruleset  = build_ruleset(branch=branch_id,
                                 purpose=_purpose_param(request))
        fallback = ruleset.fallback_zone

        items = Item.objects.filter(is_active=True)
        if q:
            items = items.filter(
                db_models.Q(name__icontains=q) |
                db_models.Q(softech_id__icontains=q)
            )

        results, scanned = [], 0
        for it in items.only('softech_id', 'name', 'pack_price',
                             'requires_fridge',
                             *ATTR_COLUMNS).order_by('name').iterator():
            scanned += 1
            if it.softech_id in ruleset.overrides:
                continue
            zone, _tag = ruleset.classify(
                it.name, it.pack_price, it.requires_fridge,
                itemcode=it.softech_id,
                attrs={col: getattr(it, col, '') for col in ATTR_COLUMNS},
            )
            if zone is fallback or zone is None:
                results.append({
                    'item_code': it.softech_id,
                    'item_name': it.name,
                    'price':     float(it.pack_price or 0),
                    'requires_fridge': it.requires_fridge,
                })
                if len(results) >= limit:
                    break

        return Response({
            'count':     len(results),
            'truncated': len(results) >= limit,
            'scanned':   scanned,
            'results':   results,
        })

    # ── Bootstrap defaults ────────────────────────────────────────────────────

    @action(detail=False, methods=['post'], url_path='seed-defaults')
    def seed_defaults(self, request):
        """Seed the built-in default zones + rules (no-op if zones exist)."""
        from .export import seed_default_pick_zones
        zones, rules = seed_default_pick_zones()
        return Response({'zones_created': zones, 'rules_created': rules})

    # ── Per-location bootstrap ────────────────────────────────────────────────

    @action(detail=False, methods=['post'], url_path='copy-defaults')
    def copy_defaults(self, request):
        """
        POST {branch: <id|null>, purpose: picking|stocking}

        Bootstrap the (location, purpose) config by cloning the config that
        CURRENTLY applies to it via the resolution chain — e.g. a branch
        stocking config starts from the default stocking config, or, if none,
        from the picking config. No-op if the target already has zones.
        """
        from apps.branches.models import Branch

        purpose = _purpose_param(request)
        branch = None
        if request.data.get('branch'):
            branch = Branch.objects.filter(id=request.data.get('branch')).first()
            if branch is None:
                return Response({'detail': 'حدد فرعاً/مخزناً صحيحاً'},
                                status=status.HTTP_400_BAD_REQUEST)

        if PickZone.objects.filter(branch=branch, purpose=purpose).exists():
            return Response({'detail': 'هذا الإعداد موجود بالفعل'},
                            status=status.HTTP_400_BAD_REQUEST)

        # Source = first non-empty config in the remaining resolution chain
        chain = []
        if branch:
            chain.append((None, purpose))
        if purpose == 'stocking':
            if branch:
                chain.append((branch.id, 'picking'))
            chain.append((None, 'picking'))
        source = []
        for b_id, p in chain:
            qs = PickZone.objects.filter(purpose=p)
            qs = qs.filter(branch_id=b_id) if b_id else qs.filter(branch__isnull=True)
            source = list(qs.prefetch_related('rules'))
            if source:
                break
        if not source:
            return Response(
                {'detail': 'لا يوجد إعداد مصدر للنسخ — أنشئ الإعداد الافتراضي أولاً'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        zones_created = rules_created = 0
        for z in source:
            clone = PickZone.objects.create(
                branch=branch, purpose=purpose,
                name=z.name, sort_key=z.sort_key,
                location=z.location, color=z.color, is_active=z.is_active,
                is_price_zone=z.is_price_zone, is_fridge_zone=z.is_fridge_zone,
                is_fallback=z.is_fallback,
            )
            zones_created += 1
            for r in z.rules.all():
                PickZoneRule.objects.create(
                    zone=clone, match_field=r.match_field, keywords=r.keywords,
                    priority=r.priority, is_active=r.is_active, note=r.note,
                )
                rules_created += 1

        return Response({'zones_created': zones_created,
                         'rules_created': rules_created})

    # ── Field-value dropdowns (from the item-master lookup sub-tables) ────────

    @action(detail=False, methods=['get'], url_path='field-values')
    def field_values(self, request):
        """
        GET ?field=shape|medicine_type|family|producer|origin|unit
        → distinct values of that item-master column with labels + item counts,
        for the rule-builder dropdowns.
        """
        from apps.catalog.models import Item
        from .export import MATCH_FIELDS

        field = str(request.query_params.get('field') or '').strip()
        if field not in MATCH_FIELDS:
            return Response(
                {'detail': f'field يجب أن يكون أحد: {", ".join(MATCH_FIELDS)}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        code_col, label_cols = MATCH_FIELDS[field]
        rows = (
            Item.objects.filter(is_active=True)
            .exclude(**{code_col: ''})
            .values(code_col, *label_cols)
            .annotate(item_count=db_models.Count('id'))
            .order_by('-item_count')
        )
        values = []
        for r in rows:
            label = next((r[c] for c in label_cols if r.get(c)), '') or r[code_col]
            values.append({
                'value': r[code_col],
                'label': label,
                'count': r['item_count'],
            })
        return Response({'field': field, 'values': values})

    # ── Bulk item classification (products-table column) ──────────────────────

    @action(detail=False, methods=['post'], url_path='classify-items')
    def classify_items(self, request):
        """
        POST {codes: [softech_id, …], branch?: <id>}
        → {code: {zone_name, reason, tag}} for showing the pick zone in the
        products/catalog tables. Max 500 codes per call.
        """
        from apps.catalog.models import Item
        from .export import ATTR_COLUMNS, build_ruleset

        codes = request.data.get('codes') or []
        if not isinstance(codes, list) or not codes:
            return Response({'detail': 'codes مطلوبة'},
                            status=status.HTTP_400_BAD_REQUEST)
        codes = [str(c).strip() for c in codes[:500] if str(c).strip()]

        branch_id = request.data.get('branch') or None
        ruleset = build_ruleset(item_codes=codes, branch=branch_id)

        out = {}
        for it in Item.objects.filter(softech_id__in=codes).only(
            'softech_id', 'name', 'pack_price', 'requires_fridge', *ATTR_COLUMNS,
        ):
            zone, tag, reason = ruleset.explain(
                it.name, it.pack_price, it.requires_fridge,
                itemcode=it.softech_id,
                attrs={col: getattr(it, col, '') for col in ATTR_COLUMNS},
            )
            out[it.softech_id] = {
                'zone_id':   getattr(zone, 'id', None),
                'zone_name': zone.name if zone else None,
                'reason':    reason,
                'tag':       tag,
            }
        return Response(out)


class PickZoneRuleViewSet(viewsets.ModelViewSet):
    serializer_class   = PickZoneRuleSerializer
    permission_classes = [PickZoneManagePermission]
    pagination_class   = None

    def get_queryset(self):
        qs = PickZoneRule.objects.select_related('zone').order_by('priority', 'id')
        # scope to one (location, purpose) config — rules belong to zones
        qs = qs.filter(zone__purpose=_purpose_param(self.request))
        if 'branch' in self.request.query_params:
            branch_id = _branch_param(self.request)
            qs = (qs.filter(zone__branch_id=branch_id) if branch_id
                  else qs.filter(zone__branch__isnull=True))
        return qs

    @action(detail=False, methods=['post'], url_path='reorder')
    def reorder(self, request):
        """POST {ordered_ids: [id, …]} — rewrites priorities in tens."""
        ids = request.data.get('ordered_ids') or []
        if not isinstance(ids, list) or not ids:
            return Response({'detail': 'ordered_ids مطلوبة'},
                            status=status.HTTP_400_BAD_REQUEST)
        rules = {r.id: r for r in PickZoneRule.objects.filter(id__in=ids)}
        for pos, rid in enumerate(ids):
            rule = rules.get(rid)
            if rule:
                rule.priority = (pos + 1) * 10
        PickZoneRule.objects.bulk_update(rules.values(), ['priority'])
        return Response({'detail': 'تم إعادة الترتيب', 'count': len(rules)})


class ItemPickOverrideViewSet(viewsets.ModelViewSet):
    serializer_class   = ItemPickOverrideSerializer
    permission_classes = [PickZoneManagePermission]

    def get_queryset(self):
        qs = ItemPickOverride.objects.select_related('item', 'zone', 'created_by')
        # scope to one (location, purpose) config (default = branch NULL)
        qs = qs.filter(purpose=_purpose_param(self.request))
        if 'branch' in self.request.query_params:
            branch_id = _branch_param(self.request)
            qs = (qs.filter(branch_id=branch_id) if branch_id
                  else qs.filter(branch__isnull=True))
        q = str(self.request.query_params.get('q') or '').strip()
        if q:
            qs = qs.filter(
                db_models.Q(item__name__icontains=q) |
                db_models.Q(item__softech_id__icontains=q) |
                db_models.Q(tag__icontains=q)
            )
        zone_id = self.request.query_params.get('zone')
        if zone_id:
            qs = qs.filter(zone_id=zone_id)
        return qs.order_by('-updated_at')

    def perform_create(self, serializer):
        serializer.save(created_by=_profile(self.request))
