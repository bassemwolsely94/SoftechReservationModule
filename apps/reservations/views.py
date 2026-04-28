from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from django.utils import timezone
from django.db.models import Count, Q
from datetime import date

from .models import Reservation, ReservationStatusLog, ReservationActivity
from .serializers import (
    ReservationListSerializer,
    ReservationDetailSerializer,
    ReservationCreateSerializer,
    ReservationUpdateSerializer,
    ChangeStatusSerializer,
    ReservationActivitySerializer,
    ReservationActivityCreateSerializer,
)


def get_profile(request):
    return getattr(request.user, 'staff_profile', None)


def log_activity(reservation, activity_type, message, staff, attachment=None, transfer_ref=None):
    """Helper: create a ReservationActivity entry."""
    activity = ReservationActivity.objects.create(
        reservation=reservation,
        activity_type=activity_type,
        message=message,
        created_by=staff,
        attachment=attachment,
        transfer_request_id_ref=transfer_ref,
    )
    return activity


class ReservationViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['status', 'priority', 'branch', 'assigned_to']
    search_fields = [
        'contact_name', 'contact_phone',
        'customer__name', 'customer__phone', 'item__name',
        'item__softech_id',
    ]
    ordering_fields = ['created_at', 'updated_at', 'follow_up_date', 'priority']
    ordering = ['-created_at']

    def get_queryset(self):
        qs = Reservation.objects.select_related(
            'customer', 'item', 'branch',
            'assigned_to__user', 'created_by__user',
        ).prefetch_related(
            'status_logs',
            'activities__created_by__user',
            'activities__mentioned_users',
        ).annotate(
            activity_count=Count('activities')
        )

        profile = get_profile(self.request)

        # Branch-scoped access: branch staff only see their branch
        if profile and profile.role not in ('admin', 'call_center', 'purchasing'):
            if profile.branch:
                qs = qs.filter(branch=profile.branch)

        date_from = self.request.query_params.get('date_from')
        date_to = self.request.query_params.get('date_to')
        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)
        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)

        return qs

    def get_serializer_class(self):
        if self.action == 'list':
            return ReservationListSerializer
        if self.action == 'create':
            return ReservationCreateSerializer
        if self.action in ('partial_update', 'update'):
            return ReservationUpdateSerializer
        return ReservationDetailSerializer

    def perform_create(self, serializer):
        staff = get_profile(self.request)
        reservation = serializer.save(created_by=staff)

        # Auto-log creation to status log
        ReservationStatusLog.objects.create(
            reservation=reservation,
            old_status='',
            new_status='pending',
            changed_by=staff,
            note='تم إنشاء الحجز',
        )

        # Auto-log to chatter
        log_activity(
            reservation=reservation,
            activity_type='status_changed',
            message=f'تم إنشاء الحجز للصنف "{reservation.item.name}" للعميل {reservation.customer.name}',
            staff=staff,
        )

    # ── Change Status ──────────────────────────────────────────────────────────

    @action(detail=True, methods=['post'], url_path='change-status')
    def change_status(self, request, pk=None):
        reservation = self.get_object()
        serializer = ChangeStatusSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        new_status = serializer.validated_data['status']
        note = serializer.validated_data.get('note', '')
        staff = get_profile(request)

        old_status = reservation.status
        if old_status == new_status:
            return Response({'detail': 'الحالة لم تتغير'}, status=status.HTTP_400_BAD_REQUEST)

        STATUS_LABELS = dict(Reservation.STATUS_CHOICES)

        # Status log
        ReservationStatusLog.objects.create(
            reservation=reservation,
            old_status=old_status,
            new_status=new_status,
            changed_by=staff,
            note=note,
        )

        # Chatter log
        old_label = STATUS_LABELS.get(old_status, old_status)
        new_label = STATUS_LABELS.get(new_status, new_status)
        chatter_msg = f'تم تغيير الحالة: {old_label} ← {new_label}'
        if note:
            chatter_msg += f'\nالملاحظة: {note}'

        log_activity(
            reservation=reservation,
            activity_type='status_changed',
            message=chatter_msg,
            staff=staff,
        )

        # Handle special status transitions
        if new_status == 'fulfilled':
            log_activity(
                reservation=reservation,
                activity_type='item_dispensed',
                message=f'تم صرف الصنف "{reservation.item.name}" للعميل {reservation.contact_name}',
                staff=staff,
            )

        reservation.status = new_status
        reservation.save(update_fields=['status', 'updated_at'])

        return Response(
            ReservationDetailSerializer(reservation, context={'request': request}).data
        )

    # ── Chatter: list activities ───────────────────────────────────────────────

    @action(detail=True, methods=['get'], url_path='activities')
    def activities(self, request, pk=None):
        reservation = self.get_object()
        activities = reservation.activities.select_related(
            'created_by__user'
        ).prefetch_related('mentioned_users').order_by('created_at')
        serializer = ReservationActivitySerializer(
            activities, many=True, context={'request': request}
        )
        return Response(serializer.data)

    # ── Chatter: post new activity ─────────────────────────────────────────────

    @action(detail=True, methods=['post'], url_path='log')
    def log(self, request, pk=None):
        reservation = self.get_object()
        staff = get_profile(request)

        serializer = ReservationActivityCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        d = serializer.validated_data
        activity = ReservationActivity.objects.create(
            reservation=reservation,
            activity_type=d.get('activity_type', 'note'),
            message=d.get('message', ''),
            created_by=staff,
            attachment=d.get('attachment'),
            transfer_request_id_ref=d.get('transfer_request_id_ref'),
        )
        if d.get('mentioned_users'):
            activity.mentioned_users.set(d['mentioned_users'])

        return Response(
            ReservationActivitySerializer(activity, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
        )

    # ── Dashboard summary ──────────────────────────────────────────────────────

    @action(detail=False, methods=['get'])
    def dashboard(self, request):
        today = date.today()
        qs = Reservation.objects.all()

        profile = get_profile(request)
        if profile and profile.role not in ('admin', 'call_center', 'purchasing'):
            if profile.branch:
                qs = qs.filter(branch=profile.branch)

        branch_id = request.query_params.get('branch')
        if branch_id:
            qs = qs.filter(branch_id=branch_id)

        data = {
            'pending': qs.filter(status='pending').count(),
            'available': qs.filter(status='available').count(),
            'contacted': qs.filter(status='contacted').count(),
            'confirmed': qs.filter(status='confirmed').count(),
            'follow_ups_today': qs.filter(
                follow_up_date=today,
                status__in=['pending', 'available', 'contacted']
            ).count(),
            'fulfilled_this_week': qs.filter(
                status='fulfilled',
                updated_at__date__gte=today.replace(day=today.day - today.weekday())
            ).count(),
            'urgent': qs.filter(
                priority='urgent',
                status__in=['pending', 'available', 'contacted']
            ).count(),
            'by_status': list(
                qs.values('status').annotate(count=Count('id')).order_by('status')
            ),
            'by_branch': list(
                qs.filter(status__in=['pending', 'available']).values(
                    'branch__name_ar', 'branch__name'
                ).annotate(count=Count('id')).order_by('-count')[:10]
            ),
        }
        return Response(data)
