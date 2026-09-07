"""
apps/demand/views.py

Views are thin — all business logic lives in service.py.
"""
from rest_framework import viewsets, filters, status
from rest_framework.decorators import action, api_view, permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.throttling import AnonRateThrottle
from rest_framework.response import Response


class PublicDemandThrottle(AnonRateThrottle):
    """Abuse guard for the unauthenticated self-service endpoints."""
    scope = 'public_demand'
    def get_rate(self):
        return '40/hour'
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Count, Sum, Q, F
from django.utils import timezone
from datetime import timedelta

from .models import DemandRecord, DemandItem, DemandFollowUp, DemandLog, ItemDemandStat
from .serializers import (
    DemandListSerializer, DemandDetailSerializer,
    DemandCreateSerializer, DemandUpdateSerializer,
    DemandItemSerializer, DemandItemWriteSerializer,
    DemandLogSerializer, DemandLogCreateSerializer,
    DemandFollowUpSerializer,
    AssignSerializer, FulfillSerializer, LostSerializer,
    ScheduleFollowupSerializer, TransitionSerializer,
    ItemDemandStatSerializer,
    RecoveryQueueSerializer, RecoverSerializer, NotifiedSerializer,
    DisqualifySerializer, OptOutSerializer, FromReservationSerializer,
)
from . import service


def _profile(request):
    return getattr(request.user, 'staff_profile', None)


class DemandViewSet(viewsets.ModelViewSet):
    """
    Central ViewSet for Customer Demand Records.

    CRUD:
        list, create, retrieve, partial_update

    State actions:
        assign              POST /{id}/assign/
        follow_up           POST /{id}/follow-up/
        stock_eta           POST /{id}/stock-eta/
        suggest_transfer    POST /{id}/suggest-transfer/
        flag_purchasing     POST /{id}/flag-purchasing/
        fulfill             POST /{id}/fulfill/
        mark_lost           POST /{id}/lost/
        cancel              POST /{id}/cancel/

    Item management:
        add_item            POST  /{id}/items/
        remove_item         DELETE /{id}/items/{item_id}/

    Communication:
        logs                GET/POST /{id}/logs/
        followups           GET     /{id}/followups/
        complete_followup   POST    /{id}/followups/{task_id}/complete/
        schedule_followup   POST    /{id}/schedule-followup/

    ERP:
        enrich_from_erp     POST /{id}/enrich/
        erp_lookup          GET  /erp-lookup/?phone=X&phcode=Y
    """

    permission_classes = [IsAuthenticated]
    filter_backends    = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields   = ['status', 'priority', 'branch', 'source', 'assigned_to']
    search_fields      = [
        'phone', 'customer_name', 'phcode', 'demand_number',
        'items__item__name', 'items__item__softech_id', 'items__item_name_free',
    ]
    ordering_fields = ['created_at', 'updated_at', 'follow_up_date', 'priority']
    ordering        = ['-created_at']

    def get_queryset(self):
        qs = DemandRecord.objects.select_related(
            'branch', 'customer', 'assigned_to__user', 'created_by__user',
        ).prefetch_related('items__item')

        profile = _profile(self.request)
        if not profile:
            return qs.none()

        # HQ roles see all
        if profile.role in ('admin', 'call_center', 'purchasing'):
            return qs

        # Branch staff see their branch only
        if profile.branch:
            return qs.filter(branch=profile.branch)

        return qs.none()

    def get_serializer_class(self):
        if self.action == 'list':
            return DemandListSerializer
        if self.action == 'create':
            return DemandCreateSerializer
        if self.action in ('update', 'partial_update'):
            return DemandUpdateSerializer
        return DemandDetailSerializer

    def perform_create(self, serializer):
        profile = _profile(self.request)
        data = serializer.validated_data
        items_data = data.pop('items', [])

        demand = service.create_demand(
            phone=data['phone'],
            customer_name=data.get('customer_name', ''),
            branch=data['branch'],
            created_by=profile,
            source=data.get('source', 'walk_in'),
            priority=data.get('priority', 'normal'),
            notes=data.get('notes', ''),
            phcode=data.get('phcode', ''),
            items_data=[
                {
                    'item': d.get('item').id if d.get('item') else None,
                    'item_name_free': d.get('item_name_free', ''),
                    'quantity': d.get('quantity', 1),
                    'demand_type': d.get('demand_type', 'out_of_stock'),
                    'notes': d.get('notes', ''),
                    'substitute_for_item': (
                        d.get('substitute_for_item').id if d.get('substitute_for_item') else None
                    ),
                    'manual_price': d.get('manual_price'),
                }
                for d in items_data
            ],
            follow_up_date=data.get('follow_up_date'),
        )
        # Replace the serializer's instance with the created demand
        serializer._data = DemandDetailSerializer(demand).data

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    # ── Assign ────────────────────────────────────────────────────────────────

    @action(detail=True, methods=['post'])
    def assign(self, request, pk=None):
        demand  = self.get_object()
        profile = _profile(request)

        from apps.users.models import StaffProfile
        assigned_to_id = request.data.get('assigned_to')
        if assigned_to_id:
            try:
                assignee = StaffProfile.objects.get(pk=assigned_to_id)
            except StaffProfile.DoesNotExist:
                return Response({'detail': 'الموظف غير موجود'}, status=400)
        else:
            # No assignee supplied → self-assign (the "تعيين" one-click action).
            assignee = profile
            if assignee is None:
                return Response({'detail': 'لا يوجد ملف موظف للمستخدم الحالي'}, status=400)

        demand = service.transition_status(
            demand, 'assigned', by=profile,
            note=request.data.get('note', ''),
            assigned_to=assignee,
        )
        return Response(DemandDetailSerializer(demand).data)

    # ── Follow-up ─────────────────────────────────────────────────────────────

    @action(detail=True, methods=['post'], url_path='follow-up')
    def follow_up(self, request, pk=None):
        demand  = self.get_object()
        profile = _profile(request)
        s = TransitionSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        demand = service.transition_status(demand, 'follow_up', by=profile, **s.validated_data)
        return Response(DemandDetailSerializer(demand).data)

    # ── Stock ETA ─────────────────────────────────────────────────────────────

    @action(detail=True, methods=['post'], url_path='stock-eta')
    def stock_eta(self, request, pk=None):
        demand  = self.get_object()
        profile = _profile(request)
        s = TransitionSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        eta_date = request.data.get('expected_stock_date')
        if eta_date:
            demand.expected_stock_date = eta_date
            demand.save(update_fields=['expected_stock_date'])
        demand = service.transition_status(demand, 'stock_eta', by=profile, **s.validated_data)
        return Response(DemandDetailSerializer(demand).data)

    # ── Suggest transfer ──────────────────────────────────────────────────────

    @action(detail=True, methods=['post'], url_path='suggest-transfer')
    def suggest_transfer(self, request, pk=None):
        demand  = self.get_object()
        profile = _profile(request)
        s = TransitionSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        demand = service.transition_status(demand, 'transfer_suggested', by=profile, **s.validated_data)
        return Response(DemandDetailSerializer(demand).data)

    # ── Flag purchasing ───────────────────────────────────────────────────────

    @action(detail=True, methods=['post'], url_path='flag-purchasing')
    def flag_purchasing(self, request, pk=None):
        demand  = self.get_object()
        profile = _profile(request)
        s = TransitionSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        demand = service.transition_status(demand, 'purchasing_flagged', by=profile, **s.validated_data)
        return Response(DemandDetailSerializer(demand).data)

    # ── Fulfill ───────────────────────────────────────────────────────────────

    @action(detail=True, methods=['post'])
    def fulfill(self, request, pk=None):
        demand  = self.get_object()
        profile = _profile(request)
        s = FulfillSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        demand = service.transition_status(
            demand, 'fulfilled', by=profile,
            **s.validated_data,
        )
        return Response(DemandDetailSerializer(demand).data)

    # ── Lost sale ─────────────────────────────────────────────────────────────

    @action(detail=True, methods=['post'])
    def lost(self, request, pk=None):
        demand  = self.get_object()
        profile = _profile(request)
        s = LostSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        demand = service.transition_status(
            demand, 'lost', by=profile,
            **s.validated_data,
        )
        return Response(DemandDetailSerializer(demand).data)

    # ── Cancel ────────────────────────────────────────────────────────────────

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        demand  = self.get_object()
        profile = _profile(request)
        s = TransitionSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        demand = service.transition_status(demand, 'cancelled', by=profile, **s.validated_data)
        return Response(DemandDetailSerializer(demand).data)

    # ── Items ─────────────────────────────────────────────────────────────────

    @action(detail=True, methods=['post', 'get'], url_path='items')
    def items(self, request, pk=None):
        demand = self.get_object()
        if request.method == 'GET':
            return Response(DemandItemSerializer(demand.items.all(), many=True).data)

        s = DemandItemWriteSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = dict(s.validated_data)
        manual_price = data.pop('manual_price', None)   # non-model field
        # Uncoded item with a hand-entered pack value → store it, flagged manual.
        if not data.get('item') and manual_price not in (None, ''):
            data['unit_price_snapshot'] = manual_price
            data['price_is_manual'] = True
            data['price_snapshot_at'] = timezone.now()
        item = DemandItem.objects.create(demand=demand, **data)
        return Response(DemandItemSerializer(item).data, status=201)

    @action(detail=True, methods=['delete'], url_path=r'items/(?P<item_id>[0-9]+)')
    def remove_item(self, request, pk=None, item_id=None):
        demand = self.get_object()
        try:
            DemandItem.objects.get(pk=item_id, demand=demand).delete()
        except DemandItem.DoesNotExist:
            return Response(status=404)
        return Response(status=204)

    # ── Recovery loop (Phase 1) ─────────────────────────────────────────────────

    def _get_line(self, demand, item_id):
        try:
            return demand.items.get(pk=item_id)
        except DemandItem.DoesNotExist:
            return None

    @action(detail=False, methods=['get'], url_path='recovery-queue')
    def recovery_queue(self, request):
        """Back-in-stock worklist: eligible lines flagged `available_again`,
        branch-scoped, sorted by potential value (desc)."""
        visible = self.get_queryset()
        qs = (
            DemandItem.objects.awaiting_winback()
            .filter(demand__in=visible)
            .select_related('demand', 'demand__branch', 'item')
            .annotate(_val=F('quantity') * F('unit_price_snapshot'))
            .order_by(F('_val').desc(nulls_last=True), '-back_in_stock_at')
        )
        page = self.paginate_queryset(qs)
        target = page if page is not None else qs
        data = RecoveryQueueSerializer(target, many=True).data
        return self.get_paginated_response(data) if page is not None else Response(data)

    @action(detail=True, methods=['post'], url_path=r'items/(?P<item_id>[0-9]+)/recover')
    def recover_item(self, request, pk=None, item_id=None):
        demand = self.get_object()
        line = self._get_line(demand, item_id)
        if line is None:
            return Response(status=404)
        s = RecoverSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        service.mark_recovered(
            line, revenue=s.validated_data.get('recovered_revenue'),
            by=_profile(request),
        )
        return Response(DemandItemSerializer(line).data)

    @action(detail=True, methods=['post'], url_path=r'items/(?P<item_id>[0-9]+)/notified')
    def notified_item(self, request, pk=None, item_id=None):
        demand = self.get_object()
        line = self._get_line(demand, item_id)
        if line is None:
            return Response(status=404)
        s = NotifiedSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        service.mark_notified(line, channel=s.validated_data['channel'], by=_profile(request))
        return Response(DemandItemSerializer(line).data)

    @action(detail=True, methods=['post'], url_path=r'items/(?P<item_id>[0-9]+)/opt-out')
    def opt_out_item(self, request, pk=None, item_id=None):
        demand = self.get_object()
        line = self._get_line(demand, item_id)
        if line is None:
            return Response(status=404)
        s = OptOutSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        service.opt_out_item(line, reason=s.validated_data.get('reason', ''), by=_profile(request))
        return Response(DemandItemSerializer(line).data)

    @action(detail=True, methods=['post'], url_path=r'items/(?P<item_id>[0-9]+)/disqualify')
    def disqualify_item(self, request, pk=None, item_id=None):
        """Approval-gated removal from the recovery loop (§5.8)."""
        profile = _profile(request)
        if not profile or not profile.can_do('demand', 'approve'):
            return Response({'detail': 'يتطلب صلاحية اعتماد على وحدة الطلبات'}, status=403)
        demand = self.get_object()
        line = self._get_line(demand, item_id)
        if line is None:
            return Response(status=404)
        s = DisqualifySerializer(data=request.data)
        s.is_valid(raise_exception=True)
        service.disqualify_item(line, reason=s.validated_data['reason'], by=profile)
        return Response(DemandItemSerializer(line).data)

    @action(detail=True, methods=['post'], url_path=r'items/(?P<item_id>[0-9]+)/requalify')
    def requalify_item(self, request, pk=None, item_id=None):
        """Reverse a disqualification (same approval permission)."""
        profile = _profile(request)
        if not profile or not profile.can_do('demand', 'approve'):
            return Response({'detail': 'يتطلب صلاحية اعتماد على وحدة الطلبات'}, status=403)
        demand = self.get_object()
        line = self._get_line(demand, item_id)
        if line is None:
            return Response(status=404)
        service.requalify_item(line, by=profile)
        return Response(DemandItemSerializer(line).data)

    # ── Demand ↔ Reservation bridge (Phase 1b, §5.9) ────────────────────────────

    @action(detail=True, methods=['post'], url_path=r'items/(?P<item_id>[0-9]+)/to-reservation')
    def item_to_reservation(self, request, pk=None, item_id=None):
        """Forward bridge: convert a recovered/in-stock demand line into a
        Reservation. Gated by reservations.create permission."""
        profile = _profile(request)
        if not profile or not profile.can_do('reservations', 'create'):
            return Response({'detail': 'يتطلب صلاحية إنشاء حجز'}, status=403)
        demand = self.get_object()
        line = self._get_line(demand, item_id)
        if line is None:
            return Response(status=404)
        res = service.convert_item_to_reservation(line, by=profile)
        return Response({
            'reservation_id': res.id,
            'item': DemandItemSerializer(line).data,
        }, status=201)

    @action(detail=False, methods=['post'], url_path='from-reservation')
    def from_reservation(self, request):
        """Reverse bridge: convert an expired/cancelled Reservation into a lost
        DemandRecord. Manager-gated by demand.approve."""
        profile = _profile(request)
        if not profile or not profile.can_do('demand', 'approve'):
            return Response({'detail': 'يتطلب صلاحية اعتماد على وحدة الطلبات'}, status=403)
        s = FromReservationSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        from apps.reservations.models import Reservation
        try:
            res = Reservation.objects.get(pk=s.validated_data['reservation_id'])
        except Reservation.DoesNotExist:
            return Response({'detail': 'الحجز غير موجود'}, status=404)
        if res.status not in ('expired', 'cancelled'):
            return Response(
                {'detail': 'يمكن التحويل فقط من حجز منتهٍ أو ملغى'}, status=400)

        demand = service.create_lost_demand_from_reservation(
            res, by=profile,
            lost_reason=s.validated_data.get('lost_reason', 'no_stock'),
            disqualified_reason=s.validated_data.get('disqualified_reason', ''),
        )
        return Response(DemandDetailSerializer(demand).data, status=201)

    # ── Logs / Chatter ────────────────────────────────────────────────────────

    @action(detail=True, methods=['get', 'post'], url_path='logs')
    def logs(self, request, pk=None):
        demand = self.get_object()
        if request.method == 'GET':
            return Response(
                DemandLogSerializer(demand.logs.order_by('created_at'), many=True).data
            )
        profile = _profile(request)
        s = DemandLogCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        log = DemandLog.objects.create(demand=demand, created_by=profile, **s.validated_data)
        return Response(DemandLogSerializer(log).data, status=201)

    # ── Follow-up tasks ───────────────────────────────────────────────────────

    @action(detail=True, methods=['get'], url_path='followups')
    def followups(self, request, pk=None):
        demand = self.get_object()
        return Response(DemandFollowUpSerializer(demand.followups.all(), many=True).data)

    @action(detail=True, methods=['post'], url_path='schedule-followup')
    def schedule_followup(self, request, pk=None):
        demand  = self.get_object()
        profile = _profile(request)
        s = ScheduleFollowupSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        task = service.schedule_followup(
            demand,
            hours_from_now=s.validated_data['hours_from_now'],
            task_type=s.validated_data['task_type'],
            note=s.validated_data.get('note', ''),
            created_by=profile,
        )
        return Response(DemandFollowUpSerializer(task).data, status=201)

    @action(detail=True, methods=['post'], url_path=r'followups/(?P<task_id>[0-9]+)/complete')
    def complete_followup(self, request, pk=None, task_id=None):
        demand  = self.get_object()
        profile = _profile(request)
        try:
            task = demand.followups.get(pk=task_id)
        except DemandFollowUp.DoesNotExist:
            return Response(status=404)

        outcome = request.data.get('outcome', '')
        note    = request.data.get('note', outcome)
        service.complete_followup(task, outcome=outcome, note=note, completed_by=profile)
        return Response(DemandFollowUpSerializer(task).data)

    # ── ERP integration ───────────────────────────────────────────────────────

    @action(detail=True, methods=['post'], url_path='enrich')
    def enrich_from_erp(self, request, pk=None):
        demand = self.get_object()
        result = service.enrich_demand_from_erp(demand)
        demand.refresh_from_db()
        return Response({
            'erp_found': result is not None,
            'phcode': demand.phcode,
            'customer_linked': demand.customer_id is not None,
            'erp_data': result,
        })

    @action(detail=False, methods=['get'], url_path='erp-lookup')
    def erp_lookup(self, request):
        phone  = request.query_params.get('phone')
        phcode = request.query_params.get('phcode')
        if not phone and not phcode:
            return Response({'detail': 'phone أو phcode مطلوب'}, status=400)
        result = service.lookup_customer_in_erp(phone=phone, phcode=phcode)
        return Response({'found': result is not None, 'data': result})

    @action(detail=False, methods=['get'], url_path='substitutes')
    def substitutes(self, request):
        """Phase 3 — in-stock same-molecule alternatives for an out-of-stock item.
        GET /api/demand/substitutes/?item=<id>&branch=<id>[&network=true]"""
        item_id   = request.query_params.get('item')
        branch_id = request.query_params.get('branch')
        network   = request.query_params.get('network') == 'true'
        if not item_id:
            return Response({'detail': 'item مطلوب'}, status=400)

        from apps.catalog.models import Item
        try:
            item = Item.objects.get(pk=item_id)
        except (Item.DoesNotExist, ValueError):
            return Response({'detail': 'الصنف غير موجود'}, status=404)

        branch = None
        if branch_id:
            from apps.branches.models import Branch
            branch = Branch.objects.filter(pk=branch_id).first()

        subs = service.find_substitutes(item, branch=branch, network=network)
        return Response({
            'item':        int(item_id),
            'scientific':  item.name_scientific,
            'substitutes': subs,
        })

    # ── Bulk actions (call-center throughput) ───────────────────────────────────

    @action(detail=False, methods=['post'], url_path='bulk')
    def bulk_action(self, request):
        """POST /api/demand/bulk/  body: {ids:[...], action, assigned_to?}
        Apply assign / cancel / flag_purchasing to many demands at once.
        Each item still goes through the state-machine, so invalid transitions
        are skipped, not forced."""
        profile  = _profile(request)
        action_  = request.data.get('action')
        ids      = request.data.get('ids') or []
        TARGET   = {'assign': 'assigned', 'cancel': 'cancelled', 'flag_purchasing': 'purchasing_flagged'}
        PERM     = {'assign': 'assign', 'cancel': 'delete', 'flag_purchasing': 'edit'}
        if not ids or action_ not in TARGET:
            return Response({'detail': 'بيانات غير صالحة'}, status=400)
        if not profile or not profile.can_do('demand', PERM[action_]):
            return Response({'detail': 'غير مصرح بهذا الإجراء'}, status=403)

        extra = {}
        if action_ == 'assign':
            from apps.users.models import StaffProfile
            try:
                extra['assigned_to'] = StaffProfile.objects.get(pk=request.data.get('assigned_to'))
            except (StaffProfile.DoesNotExist, ValueError, TypeError):
                return Response({'detail': 'الموظف غير موجود'}, status=400)

        visible = self.get_queryset().filter(id__in=ids)
        ok = skipped = 0
        for demand in visible:
            try:
                service.transition_status(demand, TARGET[action_], by=profile, **extra)
                ok += 1
            except Exception:
                skipped += 1   # invalid transition for this item's current state
        return Response({'ok': ok, 'skipped': skipped, 'total': len(ids)})


# ── Demand Dashboard ──────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def demand_dashboard(request):
    """
    GET /api/demand/dashboard/

    Returns full analytics for the Lost Sales & Demand Intelligence dashboard.
    Roles: admin, purchasing, call_center
    """
    profile = _profile(request)
    if not profile or profile.role not in ('admin', 'purchasing', 'call_center'):
        return Response({'detail': 'غير مصرح'}, status=403)

    try:
        window_days = max(1, min(int(request.query_params.get('days', 30)), 365))
    except (ValueError, TypeError):
        window_days = 30

    now        = timezone.now()
    today      = now.date()
    week_ago   = now - timedelta(days=7)
    month_ago  = now - timedelta(days=window_days)   # window honors ?days=

    branch_id = request.query_params.get('branch')
    base_qs   = DemandRecord.objects.all()
    if branch_id:
        base_qs = base_qs.filter(branch_id=branch_id)

    # ── KPIs ─────────────────────────────────────────────────────────────────
    total_30d     = base_qs.filter(created_at__gte=month_ago).count()
    active        = base_qs.filter(status__in=['new','assigned','follow_up','stock_eta','transfer_suggested','purchasing_flagged']).count()
    fulfilled_30d = base_qs.filter(status='fulfilled', fulfilled_at__gte=month_ago).count()
    lost_30d      = base_qs.filter(status='lost', updated_at__gte=month_ago).count()
    sla_breach    = base_qs.filter(status__in=['new','assigned']).count()  # approximate
    follow_ups_today = DemandFollowUp.objects.filter(
        demand__in=base_qs, status='pending', due_date__date=today
    ).count()
    overdue_followups = DemandFollowUp.objects.filter(
        demand__in=base_qs, status='pending', due_date__lt=now
    ).count()

    fulfillment_rate = (
        round(fulfilled_30d / total_30d * 100, 1) if total_30d else 0
    )
    lost_rate = (
        round(lost_30d / total_30d * 100, 1) if total_30d else 0
    )

    # ── Recovery loop ROI (Phase 1) ───────────────────────────────────────────
    rec_items = DemandItem.objects.filter(demand__in=base_qs)
    recovered_30d = rec_items.filter(item_status='recovered', recovered_at__gte=month_ago)
    recovered_revenue_30d = float(
        recovered_30d.aggregate(s=Sum('recovered_revenue'))['s'] or 0
    )
    recovered_count_30d = recovered_30d.count()
    open_recovery = rec_items.filter(item_status='available_again')
    open_recovery_count = open_recovery.count()
    open_recovery_value = float(
        open_recovery.annotate(v=F('quantity') * F('unit_price_snapshot'))
        .aggregate(s=Sum('v'))['s'] or 0
    )
    back_in_stock_30d = rec_items.filter(back_in_stock_at__gte=month_ago).count()
    recovery_rate = (
        round(recovered_count_30d / back_in_stock_30d * 100, 1) if back_in_stock_30d else 0
    )

    # Confirmed lost value (EGP) — Σ line_value of lost lines in window (Phase 2 seed).
    lost_value_30d = float(
        rec_items.filter(
            item_status='lost', demand__updated_at__gte=month_ago,
            unit_price_snapshot__isnull=False,
        ).annotate(v=F('quantity') * F('unit_price_snapshot'))
        .aggregate(s=Sum('v'))['s'] or 0
    )

    # ── Lost by reason ────────────────────────────────────────────────────────
    lost_reasons = list(
        base_qs.filter(status='lost', updated_at__gte=month_ago)
        .values('lost_reason')
        .annotate(count=Count('id'))
        .order_by('-count')
    )

    # ── Lost by branch ────────────────────────────────────────────────────────
    lost_by_branch = list(
        base_qs.filter(status='lost', updated_at__gte=month_ago)
        .values('branch__name_ar', 'branch__name', 'branch__id')
        .annotate(count=Count('id'))
        .order_by('-count')[:8]
    )
    for b in lost_by_branch:
        b['branch_name'] = b['branch__name_ar'] or b['branch__name']

    # ── Top demanded items (all statuses) ─────────────────────────────────────
    top_items = list(
        DemandItem.objects.filter(
            demand__in=base_qs, demand__created_at__gte=month_ago,
            item__isnull=False,
        )
        .values('item__id', 'item__name', 'item__softech_id')
        .annotate(
            demand_count   = Count('id'),
            lost_count     = Count('id', filter=Q(item_status='lost')),
            fulfilled_count = Count('id', filter=Q(item_status='fulfilled')),
            total_qty      = Sum('quantity'),
        )
        .order_by('-demand_count')[:15]
    )
    for i in top_items:
        total = i['demand_count']
        i['lost_rate']      = round(i['lost_count'] / total * 100) if total else 0
        i['fulfilled_rate'] = round(i['fulfilled_count'] / total * 100) if total else 0

    # ── Top LOST items (by lost count) ────────────────────────────────────────
    top_lost_items = list(
        DemandItem.objects.filter(
            demand__in=base_qs, demand__created_at__gte=month_ago,
            item__isnull=False, item_status='lost',
        )
        .values('item__id', 'item__name', 'item__softech_id')
        .annotate(count=Count('id'), lost_qty=Sum('quantity'))
        .order_by('-count')[:15]
    )

    # ── Chronic shortage items ────────────────────────────────────────────────
    chronic_items = list(
        ItemDemandStat.objects.filter(
            is_long_shortage=True,
        ).select_related('item', 'branch')
        .order_by('-demand_count_30d')[:10]
        .values(
            'item__id', 'item__name', 'item__softech_id',
            'branch__name_ar', 'demand_count_30d', 'lost_count_30d',
        )
    )

    # ── Discontinued items with active demand ─────────────────────────────────
    discontinued = list(
        ItemDemandStat.objects.filter(is_discontinued=True, demand_count_30d__gt=0)
        .select_related('item')
        .order_by('-demand_count_30d')[:10]
        .values('item__id', 'item__name', 'item__softech_id', 'demand_count_30d')
    )

    # ── Items to suggest for order ────────────────────────────────────────────
    suggest_order = list(
        ItemDemandStat.objects.filter(suggest_order=True)
        .select_related('item', 'branch')
        .order_by('-lost_value_30d', '-lost_count_30d')[:10]
        .values(
            'item__id', 'item__name', 'item__softech_id',
            'branch__name_ar', 'demand_count_30d', 'lost_count_30d',
            'lost_qty_30d', 'lost_value_30d',
        )
    )

    # ── Status distribution ───────────────────────────────────────────────────
    status_dist = list(
        base_qs.filter(created_at__gte=month_ago)
        .values('status')
        .annotate(count=Count('id'))
        .order_by('status')
    )

    # ── Branch performance ────────────────────────────────────────────────────
    branch_perf = list(
        base_qs.filter(created_at__gte=month_ago)
        .values('branch__name_ar', 'branch__name', 'branch__id')
        .annotate(
            total     = Count('id'),
            fulfilled = Count('id', filter=Q(status='fulfilled')),
            lost      = Count('id', filter=Q(status='lost')),
            active    = Count('id', filter=Q(status__in=['new','assigned','follow_up'])),
        )
        .order_by('-total')[:8]
    )
    for b in branch_perf:
        b['branch_name'] = b['branch__name_ar'] or b['branch__name']
        t = b['total']
        b['fulfillment_rate'] = round(b['fulfilled'] / t * 100) if t else 0
        b['lost_rate']        = round(b['lost'] / t * 100) if t else 0

    # ── Daily trend (last 30 days) ────────────────────────────────────────────
    daily_trend = []
    for i in range(29, -1, -1):
        d = (now - timedelta(days=i)).date()
        count = base_qs.filter(created_at__date=d).count()
        daily_trend.append({'date': str(d), 'count': count})

    return Response({
        'generated_at': now.isoformat(),

        'kpis': {
            'total_30d':          total_30d,
            'active':             active,
            'fulfilled_30d':      fulfilled_30d,
            'lost_30d':           lost_30d,
            'fulfillment_rate':   fulfillment_rate,
            'lost_rate':          lost_rate,
            'follow_ups_today':   follow_ups_today,
            'overdue_followups':  overdue_followups,
            'sla_breached':       sla_breach,
            'lost_value_30d':     lost_value_30d,
            # Recovery loop ROI (Phase 1)
            'recovered_revenue_30d': recovered_revenue_30d,
            'recovered_count_30d':   recovered_count_30d,
            'recovery_rate':         recovery_rate,
            'open_recovery_count':   open_recovery_count,
            'open_recovery_value':   open_recovery_value,
        },
        'window_days':         window_days,

        'status_distribution': status_dist,
        'lost_by_reason':      lost_reasons,
        'lost_by_branch':      lost_by_branch,
        'top_items':           top_items,
        'top_lost_items':      top_lost_items,
        'discontinued':        discontinued,
        'chronic_items':       chronic_items,
        'suggest_order':       suggest_order,
        'branch_performance':  branch_perf,
        'daily_trend':         daily_trend,
    })


# ── Lost-value reconciliation (Phase 2) ───────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def lost_value_reconciliation(request):
    """
    GET /api/demand/lost-value-reconciliation/

    Side-by-side, per item:
      • confirmed lost value  — Σ ItemDemandStat.lost_value_30d (NAMED demand, this module)
      • inferred lost revenue — purchasing MODULE 13 total_lost_revenue_30d (STATISTICAL)
    Coverage % = how much of the statistically-inferred loss we captured a real
    customer for. Rising coverage = capture discipline improving.

    Roles: admin, purchasing, call_center.
    """
    profile = _profile(request)
    if not profile or profile.role not in ('admin', 'purchasing', 'call_center'):
        return Response({'detail': 'غير مصرح'}, status=403)

    from django.db.models import Max
    from apps.catalog.models import Item
    try:
        from apps.purchasing.models import ItemDemandAggregated
    except Exception:
        ItemDemandAggregated = None

    # Confirmed (named demand) per item — sum across branches.
    confirmed = {
        r['item_id']: r
        for r in ItemDemandStat.objects.values('item_id')
        .annotate(value=Sum('lost_value_30d'), count=Sum('lost_count_30d'))
        .filter(value__gt=0)
    }

    # Inferred (statistical) per item — latest purchasing run.
    inferred = {}
    latest_calc = None
    if ItemDemandAggregated is not None:
        latest_calc = ItemDemandAggregated.objects.aggregate(d=Max('calc_date'))['d']
        if latest_calc:
            inferred = {
                r['item_id']: r
                for r in ItemDemandAggregated.objects
                .filter(calc_date=latest_calc, total_lost_revenue_30d__gt=0)
                .values('item_id', 'total_lost_revenue_30d', 'total_lost_qty_30d')
            }

    item_ids = set(confirmed) | set(inferred)
    names = {
        i['id']: i
        for i in Item.objects.filter(id__in=item_ids).values('id', 'name', 'softech_id')
    }

    rows = []
    for iid in item_ids:
        c  = confirmed.get(iid, {})
        n  = inferred.get(iid, {})
        cv = float(c.get('value') or 0)
        iv = float(n.get('total_lost_revenue_30d') or 0)
        nm = names.get(iid, {})
        rows.append({
            'item_id':               iid,
            'item_name':             nm.get('name', ''),
            'softech_id':            nm.get('softech_id', ''),
            'confirmed_lost_value':  round(cv, 2),
            'confirmed_lost_count':  int(c.get('count') or 0),
            'inferred_lost_revenue': round(iv, 2),
            'coverage_pct':          round(cv / iv * 100, 1) if iv > 0 else None,
        })
    rows.sort(key=lambda r: r['inferred_lost_revenue'], reverse=True)

    total_confirmed = round(sum(r['confirmed_lost_value'] for r in rows), 2)
    total_inferred  = round(sum(r['inferred_lost_revenue'] for r in rows), 2)

    return Response({
        'generated_at':                timezone.now().isoformat(),
        'latest_calc_date':            str(latest_calc) if latest_calc else None,
        'total_confirmed_lost_value':  total_confirmed,
        'total_inferred_lost_revenue': total_inferred,
        'overall_coverage_pct':        round(total_confirmed / total_inferred * 100, 1) if total_inferred else None,
        'items':                       rows[:100],
    })


# ── Demand-driven purchase suggestions ────────────────────────────────────────

def _purchase_suggestion_rows(item_ids=None):
    """Aggregate demand-driven reorder suggestions per item (across branches)."""
    qs = ItemDemandStat.objects.filter(suggest_order=True, suggested_order_qty__gt=0)
    if item_ids:
        qs = qs.filter(item_id__in=item_ids)
    rows = list(
        qs.values('item_id', 'item__name', 'item__softech_id')
        .annotate(
            suggested_qty=Sum('suggested_order_qty'),
            demand_count=Sum('demand_count_30d'),
            lost_count=Sum('lost_count_30d'),
            lost_value=Sum('lost_value_30d'),
        )
        .order_by('-lost_value', '-demand_count')[:200]
    )
    ids = [r['item_id'] for r in rows]
    from apps.catalog.models import ItemStock
    stock = {
        s['item_id']: float(s['t'] or 0)
        for s in ItemStock.objects.filter(item_id__in=ids).values('item_id').annotate(t=Sum('quantity_on_hand'))
    }
    for r in rows:
        r['network_stock'] = stock.get(r['item_id'], 0)
        r['suggested_qty'] = float(r['suggested_qty'] or 0)
        r['lost_value']    = float(r['lost_value'] or 0)
    return rows


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def purchase_suggestions(request):
    """
    GET /api/demand/purchase-suggestions/

    Demand-driven reorder list: items real customers asked for (open + lost units)
    with a suggested purchase quantity, sorted by confirmed lost value. The
    highest-confidence buy signal — a named human asked. Roles: admin, purchasing.
    """
    profile = _profile(request)
    if not profile or profile.role not in ('admin', 'purchasing', 'call_center'):
        return Response({'detail': 'غير مصرح'}, status=403)
    rows = _purchase_suggestion_rows()
    return Response({
        'generated_at': timezone.now().isoformat(),
        'count': len(rows),
        'suggestions': rows[:100],
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def push_purchase_suggestions(request):
    """
    POST /api/demand/purchase-suggestions/push/   body: {item_ids?: [...]}

    Pushes the selected (or all) demand-driven suggestions into the procurement
    hub as `demand_reorder` ProcurementAlerts. Skips items that already have an
    unresolved alert. Roles: admin, purchasing.
    """
    profile = _profile(request)
    if not profile or profile.role not in ('admin', 'purchasing'):
        return Response({'detail': 'يتطلب صلاحية على المشتريات'}, status=403)

    from apps.procurement.models import ProcurementAlert
    rows = _purchase_suggestion_rows(item_ids=request.data.get('item_ids') or None)
    created = 0
    for r in rows:
        code = r['item__softech_id'] or str(r['item_id'])
        if ProcurementAlert.objects.filter(
            alert_type='demand_reorder', entity_code=code, is_resolved=False,
        ).exists():
            continue
        ProcurementAlert.objects.create(
            alert_type='demand_reorder', severity='warning', entity_type='item',
            entity_code=code, entity_name=r['item__name'] or '',
            title=f"طلب شراء مقترح: {r['item__name']}",
            message=(
                f"طلبه {r['demand_count']} عميل · الكمية المقترحة {r['suggested_qty']:.0f} · "
                f"خسارة مؤكدة {r['lost_value']:.0f} ج.م · المخزون الحالي {r['network_stock']:.0f}"
            ),
            metric_value=r['suggested_qty'],
        )
        created += 1
    return Response({'created': created, 'considered': len(rows)})


# ── Capture leaderboard (data-discipline nudge) ───────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def capture_leaderboard(request):
    """
    GET /api/demand/capture-leaderboard/?days=30

    Who is logging customer demand (vs letting customers walk silently). Ranks
    staff by demands captured, with lost/fulfilled and total captured value.
    Roles: admin, supervisor, purchasing, call_center.
    """
    profile = _profile(request)
    if not profile or profile.role not in ('admin', 'supervisor', 'purchasing', 'call_center'):
        return Response({'detail': 'غير مصرح'}, status=403)
    try:
        days = max(1, min(int(request.query_params.get('days', 30)), 365))
    except (ValueError, TypeError):
        days = 30
    since = timezone.now() - timedelta(days=days)

    rows = list(
        DemandRecord.objects.filter(created_at__gte=since, created_by__isnull=False)
        .values('created_by')
        .annotate(
            total=Count('id'),
            lost=Count('id', filter=Q(status='lost')),
            fulfilled=Count('id', filter=Q(status='fulfilled')),
        )
        .order_by('-total')[:50]
    )
    # Captured potential value per creator (priced lines only).
    value_map = {
        r['demand__created_by']: float(r['v'] or 0)
        for r in DemandItem.objects.filter(
            demand__created_at__gte=since, demand__created_by__isnull=False,
            unit_price_snapshot__isnull=False,
        ).values('demand__created_by').annotate(v=Sum(F('quantity') * F('unit_price_snapshot')))
    }
    from apps.users.models import StaffProfile
    profiles = {
        p.id: p for p in StaffProfile.objects.filter(
            id__in=[r['created_by'] for r in rows]).select_related('branch')
    }
    for r in rows:
        p = profiles.get(r['created_by'])
        r['name']           = (getattr(p, 'full_name', None) or '—') if p else '—'
        r['branch']         = (p.branch.name_ar if p and p.branch_id else None) or '—'
        r['captured_value'] = round(value_map.get(r['created_by'], 0))
        r['fulfillment_rate'] = round(r['fulfilled'] / r['total'] * 100) if r['total'] else 0

    return Response({'days': days, 'generated_at': timezone.now().isoformat(), 'rows': rows})


# ── Substitution-acceptance analytics ─────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def substitution_analytics(request):
    """
    GET /api/demand/substitution-analytics/?days=90

    Which out-of-stock items customers accept a same-molecule substitute for
    (from `DemandItem.substitute_for_item`). Tells purchasing which substitute to
    stock and which dead SKU to drop. Roles: admin, purchasing, call_center.
    """
    profile = _profile(request)
    if not profile or profile.role not in ('admin', 'purchasing', 'call_center'):
        return Response({'detail': 'غير مصرح'}, status=403)
    try:
        days = max(1, min(int(request.query_params.get('days', 90)), 365))
    except (ValueError, TypeError):
        days = 90
    since = timezone.now() - timedelta(days=days)

    qs = DemandItem.objects.filter(
        substitute_for_item__isnull=False, item__isnull=False,
        demand__created_at__gte=since,
    )
    pairs = list(
        qs.values(
            'substitute_for_item', 'substitute_for_item__name',
            'item', 'item__name', 'item__softech_id',
        )
        .annotate(times=Count('id'), value=Sum(F('quantity') * F('unit_price_snapshot')))
        .order_by('-times')[:50]
    )
    for p in pairs:
        p['value'] = float(p['value'] or 0)
    by_molecule = list(
        qs.exclude(substitute_for_item__name_scientific='')
        .values('substitute_for_item__name_scientific')
        .annotate(times=Count('id')).order_by('-times')[:15]
    )
    return Response({
        'generated_at': timezone.now().isoformat(),
        'days': days,
        'total_substitutions': qs.count(),
        'pairs': pairs,
        'by_molecule': by_molecule,
    })


# ── Price-objection feedback ──────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def price_objections(request):
    """
    GET /api/demand/price-objections/?days=90

    Items lost specifically to price (lost_reason='price') — a stated-price
    sensitivity signal for the pricing team. Roles: admin, purchasing.
    """
    profile = _profile(request)
    if not profile or profile.role not in ('admin', 'purchasing', 'call_center'):
        return Response({'detail': 'غير مصرح'}, status=403)
    try:
        days = max(1, min(int(request.query_params.get('days', 90)), 365))
    except (ValueError, TypeError):
        days = 90
    since = timezone.now() - timedelta(days=days)

    rows = list(
        DemandItem.objects.filter(
            demand__status='lost', demand__lost_reason='price',
            demand__updated_at__gte=since, item__isnull=False,
        )
        .values('item', 'item__name', 'item__softech_id')
        .annotate(count=Count('id'), lost_value=Sum(F('quantity') * F('unit_price_snapshot')))
        .order_by('-count')[:50]
    )
    from apps.catalog.models import Item
    prices = {
        i['id']: float(i['pack_price'] or 0)
        for i in Item.objects.filter(id__in=[r['item'] for r in rows]).values('id', 'pack_price')
    }
    for r in rows:
        r['current_price'] = prices.get(r['item'], 0)
        r['lost_value']    = float(r['lost_value'] or 0)
    return Response({
        'generated_at': timezone.now().isoformat(),
        'days': days,
        'total': sum(r['count'] for r in rows),
        'items': rows,
    })


# ── Customer self-service "notify me" (public, shelf QR / link) ────────────────

import re as _re


def _valid_eg_phone(raw):
    d = _re.sub(r'\D', '', raw or '')
    return d if (_re.fullmatch(r'01\d{9}', d) or _re.fullmatch(r'0[2-9]\d{6,8}', d)) else None


@api_view(['GET'])
@permission_classes([AllowAny])
@throttle_classes([PublicDemandThrottle])
def public_item_lookup(request):
    """Minimal public item info for the notify page (name only — no catalog dump)."""
    from apps.catalog.models import Item, ItemBarcode
    item = None
    if request.query_params.get('id'):
        item = Item.objects.filter(pk=request.query_params['id'], is_active=True).first()
    elif request.query_params.get('barcode'):
        b = (ItemBarcode.objects.filter(barcode=request.query_params['barcode'], is_active=True)
             .select_related('item').first())
        item = b.item if (b and b.item and b.item.is_active) else None
    if not item:
        return Response({'found': False})
    return Response({'found': True, 'id': item.id, 'name': item.name, 'softech_id': item.softech_id})


@api_view(['GET'])
@permission_classes([AllowAny])
@throttle_classes([PublicDemandThrottle])
def public_branches(request):
    """Active branches for the notify page's branch picker (id + name only)."""
    from apps.branches.models import Branch
    rows = list(
        Branch.objects.filter(is_active=True)
        .values('id', 'name_ar', 'name').order_by('name_ar')
    )
    for b in rows:
        b['name'] = b.pop('name_ar') or b.get('name') or f"#{b['id']}"
    return Response({'branches': rows})


@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([PublicDemandThrottle])
def public_demand_interest(request):
    """Customer self-registers interest in an out-of-stock item → a demand record.
    Public, throttled, deduped. No sensitive data returned."""
    phone = _valid_eg_phone(request.data.get('phone'))
    if not phone:
        return Response({'detail': 'رقم هاتف غير صالح (موبايل 11 رقماً يبدأ بـ 01)'}, status=400)

    from apps.catalog.models import Item
    from apps.branches.models import Branch
    from .models import DemandRecord, DemandItem

    item = Item.objects.filter(pk=request.data.get('item'), is_active=True).first()
    if not item:
        return Response({'detail': 'الصنف غير متاح'}, status=400)
    branch = Branch.objects.filter(pk=request.data.get('branch'), is_active=True).first()
    if not branch:
        return Response({'detail': 'الفرع غير صحيح'}, status=400)

    # Dedup: same phone+item already open in the last 30 days → idempotent.
    if DemandItem.objects.filter(
        item=item, demand__phone=phone,
        demand__status__in=['new', 'assigned', 'follow_up', 'stock_eta',
                            'transfer_suggested', 'purchasing_flagged'],
        demand__created_at__gte=timezone.now() - timedelta(days=30),
    ).exists():
        return Response({'ok': True, 'already': True})

    demand = service.create_demand(
        phone=phone, customer_name=(request.data.get('name') or '').strip(),
        branch=branch, created_by=None, source='self_service',
        items_data=[{'item': item.id, 'quantity': 1}],
    )
    return Response({'ok': True, 'demand_number': demand.demand_number}, status=201)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def shelf_qr(request):
    """Staff: generate a printable shelf QR that deep-links to the notify page for
    an item at a branch. GET /api/demand/shelf-qr/?item=&branch="""
    item_id   = request.query_params.get('item')
    branch_id = request.query_params.get('branch')
    if not item_id or not branch_id:
        return Response({'detail': 'item و branch مطلوبان'}, status=400)
    try:
        host = request.get_host()
    except Exception:
        host = request.META.get('HTTP_HOST', '') or 'localhost'
    url = f"{request.scheme}://{host}/notify?item={item_id}&branch={branch_id}"
    try:
        import qrcode, io, base64
        buf = io.BytesIO()
        qrcode.make(url).save(buf, format='PNG')
        return Response({'url': url, 'qr_code': base64.b64encode(buf.getvalue()).decode()})
    except Exception as exc:
        return Response({'url': url, 'qr_code': None, 'detail': str(exc)})
