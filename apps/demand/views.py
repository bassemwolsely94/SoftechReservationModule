"""
apps/demand/views.py

Views are thin — all business logic lives in service.py.
"""
from rest_framework import viewsets, filters, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Count, Sum, Q
from django.utils import timezone
from datetime import timedelta

from .models import DemandRecord, DemandItem, FollowUpTask, DemandLog, ItemDemandStat
from .serializers import (
    DemandListSerializer, DemandDetailSerializer,
    DemandCreateSerializer, DemandUpdateSerializer,
    DemandItemSerializer, DemandItemWriteSerializer,
    DemandLogSerializer, DemandLogCreateSerializer,
    FollowUpTaskSerializer,
    AssignSerializer, FulfillSerializer, LostSerializer,
    ScheduleFollowupSerializer, TransitionSerializer,
    ItemDemandStatSerializer,
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
        s = AssignSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        from apps.users.models import StaffProfile
        try:
            assignee = StaffProfile.objects.get(pk=s.validated_data['assigned_to'])
        except StaffProfile.DoesNotExist:
            return Response({'detail': 'الموظف غير موجود'}, status=400)

        demand = service.transition_status(
            demand, 'assigned', by=profile,
            note=s.validated_data.get('note', ''),
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
        item = DemandItem.objects.create(demand=demand, **s.validated_data)
        return Response(DemandItemSerializer(item).data, status=201)

    @action(detail=True, methods=['delete'], url_path=r'items/(?P<item_id>[0-9]+)')
    def remove_item(self, request, pk=None, item_id=None):
        demand = self.get_object()
        try:
            DemandItem.objects.get(pk=item_id, demand=demand).delete()
        except DemandItem.DoesNotExist:
            return Response(status=404)
        return Response(status=204)

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
        return Response(FollowUpTaskSerializer(demand.followups.all(), many=True).data)

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
        return Response(FollowUpTaskSerializer(task).data, status=201)

    @action(detail=True, methods=['post'], url_path=r'followups/(?P<task_id>[0-9]+)/complete')
    def complete_followup(self, request, pk=None, task_id=None):
        demand  = self.get_object()
        profile = _profile(request)
        try:
            task = demand.followups.get(pk=task_id)
        except FollowUpTask.DoesNotExist:
            return Response(status=404)

        outcome = request.data.get('outcome', '')
        note    = request.data.get('note', outcome)
        service.complete_followup(task, outcome=outcome, note=note, completed_by=profile)
        return Response(FollowUpTaskSerializer(task).data)

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

    now        = timezone.now()
    today      = now.date()
    week_ago   = now - timedelta(days=7)
    month_ago  = now - timedelta(days=30)

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
    follow_ups_today = FollowUpTask.objects.filter(
        demand__in=base_qs, status='pending', due_date__date=today
    ).count()
    overdue_followups = FollowUpTask.objects.filter(
        demand__in=base_qs, status='pending', due_date__lt=now
    ).count()

    fulfillment_rate = (
        round(fulfilled_30d / total_30d * 100, 1) if total_30d else 0
    )
    lost_rate = (
        round(lost_30d / total_30d * 100, 1) if total_30d else 0
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

    # ── Items to suggest for order ────────────────────────────────────────────
    suggest_order = list(
        ItemDemandStat.objects.filter(suggest_order=True)
        .select_related('item', 'branch')
        .order_by('-lost_count_30d')[:10]
        .values(
            'item__id', 'item__name', 'item__softech_id',
            'branch__name_ar', 'demand_count_30d', 'lost_count_30d', 'lost_qty_30d',
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
        },

        'status_distribution': status_dist,
        'lost_by_reason':      lost_reasons,
        'lost_by_branch':      lost_by_branch,
        'top_items':           top_items,
        'chronic_items':       chronic_items,
        'suggest_order':       suggest_order,
        'branch_performance':  branch_perf,
        'daily_trend':         daily_trend,
    })
