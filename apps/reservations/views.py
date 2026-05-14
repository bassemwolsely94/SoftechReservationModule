from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from django.utils import timezone
from django.db.models import Count, Q
from datetime import date

from .models import Reservation, ReservationStatusLog, ReservationActivity, ReservationDownpayment
from .serializers import (
    ReservationListSerializer,
    ReservationDetailSerializer,
    ReservationCreateSerializer,
    ReservationUpdateSerializer,
    ChangeStatusSerializer,
    ReservationActivitySerializer,
    ReservationActivityCreateSerializer,
    ReservationDownpaymentSerializer,
    ReservationDownpaymentCreateSerializer,
)


# Roles that are allowed to see customer PII (name + phone)
_PII_ROLES = frozenset({'admin', 'call_center', 'pharmacist'})


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
        'customer__name', 'customer__phone',
        'item__name', 'item__softech_id',
        'manual_item_name',
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

    def perform_update(self, serializer):
        staff = get_profile(self.request)
        old_branch = serializer.instance.branch
        reservation = serializer.save()
        new_branch = reservation.branch
        if old_branch != new_branch:
            log_activity(
                reservation=reservation,
                activity_type='status_changed',
                message=f'تم تغيير الفرع من "{old_branch.name_ar or old_branch.name}" إلى "{new_branch.name_ar or new_branch.name}"',
                staff=staff,
            )
            # Notify branch staff of the reassignment
            try:
                from apps.notifications.models import Notification
                Notification.send_to_branch(
                    branch=new_branch,
                    notification_type='reservation_status',
                    title=f'حجز محوَّل إلى فرعك — {reservation.item_label}',
                    body=f'العميل: {reservation.contact_name}',
                    reservation=reservation,
                )
            except Exception:
                pass

    def perform_create(self, serializer):
        staff = get_profile(self.request)

        # ── Walk-in guest customer ────────────────────────────────────────────
        # If no customer was selected from search, auto-create (or find) a
        # guest Customer keyed by phone number.  Guest records have no softech_id
        # and are auto-merged with the real record when SOFTECH sync finds the
        # same mobile number.
        save_kwargs = {'created_by': staff}
        if not serializer.validated_data.get('customer'):
            from apps.customers.models import Customer as _Customer
            phone = (serializer.validated_data.get('contact_phone') or '').strip()
            name  = (serializer.validated_data.get('contact_name')  or '').strip()
            if phone:
                guest, _ = _Customer.objects.get_or_create(
                    phone=phone,
                    is_guest=True,
                    defaults={
                        'name':     name or 'زبون مباشر',
                        'is_guest': True,
                    },
                )
                save_kwargs['customer'] = guest

        reservation = serializer.save(**save_kwargs)

        # Auto-log creation to status log
        ReservationStatusLog.objects.create(
            reservation=reservation,
            old_status='',
            new_status='pending',
            changed_by=staff,
            note='تم إنشاء الحجز',
        )

        # Auto-log to chatter
        customer_label = (
            reservation.customer.name
            if reservation.customer_id
            else reservation.contact_name or 'زبون مباشر'
        )
        log_activity(
            reservation=reservation,
            activity_type='status_changed',
            message=f'تم إنشاء الحجز للصنف "{reservation.item_label}" للعميل {customer_label}',
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
                message=f'تم صرف الصنف "{reservation.item_label}" للعميل {reservation.contact_name}',
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

    # ── Chatter: post new activity (text / image / voice) ────────────────────

    @action(
        detail=True, methods=['post'], url_path='log',
        parser_classes=[MultiPartParser, FormParser, JSONParser],
    )
    def log(self, request, pk=None):
        """
        POST multipart/form-data OR application/json.

        Fields:
          activity_type       — one of ACTIVITY_TYPES (default: 'note')
          message             — text body (optional if attachment or voice_note given)
          attachment          — image file (optional)
          voice_note          — audio file: webm/ogg/mp3 (optional)
          mentioned_users     — list of StaffProfile PKs (optional)
          transfer_request_id_ref — int (optional)
        """
        reservation = self.get_object()
        staff = get_profile(request)

        serializer = ReservationActivityCreateSerializer(
            data=request.data,
            context={'request': request},
        )
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        d = serializer.validated_data
        activity = ReservationActivity.objects.create(
            reservation=reservation,
            activity_type=d.get('activity_type', 'note'),
            message=d.get('message', ''),
            created_by=staff,
            attachment=d.get('attachment'),
            voice_note=d.get('voice_note'),
            transfer_request_id_ref=d.get('transfer_request_id_ref'),
        )
        if d.get('mentioned_users'):
            activity.mentioned_users.set(d['mentioned_users'])

        return Response(
            ReservationActivitySerializer(activity, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
        )

    # ── Chatter: delete an activity (soft-delete) ────────────────────────────

    @action(
        detail=True, methods=['delete'],
        url_path=r'activities/(?P<activity_id>[0-9]+)',
        url_name='delete_activity',
    )
    def delete_activity(self, request, pk=None, activity_id=None):
        """
        DELETE /api/reservations/{id}/activities/{activity_id}/

        Soft-deletes the activity. Only the author or an admin can delete.
        The tombstone remains visible to all users with the deleter's name
        and timestamp.
        """
        reservation = self.get_object()
        profile = get_profile(request)

        try:
            activity = reservation.activities.get(pk=activity_id)
        except ReservationActivity.DoesNotExist:
            return Response({'detail': 'النشاط غير موجود'}, status=status.HTTP_404_NOT_FOUND)

        if activity.is_deleted:
            return Response({'detail': 'هذا النشاط محذوف مسبقاً'}, status=status.HTTP_400_BAD_REQUEST)

        # Permission: author or admin only
        is_author = (activity.created_by_id and profile and activity.created_by_id == profile.id)
        is_admin  = (profile and profile.role == 'admin')
        if not is_author and not is_admin:
            return Response(
                {'detail': 'لا يمكنك حذف رسائل الآخرين'},
                status=status.HTTP_403_FORBIDDEN,
            )

        # System auto-logs (status_changed, item_dispensed) cannot be deleted
        if activity.activity_type in ('status_changed', 'item_dispensed'):
            return Response(
                {'detail': 'لا يمكن حذف سجلات النظام التلقائية'},
                status=status.HTTP_403_FORBIDDEN,
            )

        activity.is_deleted = True
        activity.deleted_at  = timezone.now()
        activity.deleted_by  = profile
        activity.save(update_fields=['is_deleted', 'deleted_at', 'deleted_by'])

        return Response(
            ReservationActivitySerializer(activity, context={'request': request}).data
        )

    # ── Downpayments ──────────────────────────────────────────────────────────

    @action(detail=True, methods=['get', 'post'], url_path='downpayments')
    def downpayments(self, request, pk=None):
        reservation = self.get_object()

        if request.method == 'GET':
            dps = reservation.downpayments.select_related('received_by__user')
            total = sum(d.amount for d in dps)
            return Response({
                'total_paid': float(total),
                'downpayments': ReservationDownpaymentSerializer(dps, many=True).data,
            })

        # POST — record a new downpayment
        staff = get_profile(request)
        serializer = ReservationDownpaymentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        dp = ReservationDownpayment.objects.create(
            reservation=reservation,
            received_by=staff,
            **serializer.validated_data,
        )
        log_activity(
            reservation=reservation,
            activity_type='note',
            message=f'تم تسجيل دفعة مقدمة: {dp.amount} جنيه ({dp.get_payment_method_display()})'
                    + (f' — مرجع: {dp.reference_number}' if dp.reference_number else ''),
            staff=staff,
        )
        return Response(
            ReservationDownpaymentSerializer(dp).data,
            status=status.HTTP_201_CREATED,
        )

    # ── Print Receipt ─────────────────────────────────────────────────────────

    @action(detail=True, methods=['get'], url_path='print')
    def print_receipt(self, request, pk=None):
        """
        GET /api/reservations/{id}/print/

        Returns a clean data payload for printable receipt rendering.
        Respects PII permissions: customer name/phone are masked if the
        requesting user's role is not in _PII_ROLES.

        Logs a 'note' activity to create an audit trail of every print.
        """
        reservation = self.get_object()
        profile     = get_profile(request)
        can_see_pii = (profile and profile.role in _PII_ROLES)

        # Audit log
        log_activity(
            reservation=reservation,
            activity_type='note',
            message=f'تم طباعة إيصال الحجز',
            staff=profile,
        )

        item_name = reservation.item_label
        downpayments = list(
            reservation.downpayments.values('amount', 'payment_method', 'received_at')
        )
        total_paid = sum(d['amount'] for d in downpayments)

        receipt = {
            'doc_type':     'reservation',
            'doc_number':   reservation.id,
            'status':       reservation.status,
            'status_label': reservation.status_label_ar,
            'priority':     reservation.priority,
            'channel':      reservation.channel,
            'branch_name':  reservation.branch.name_ar or reservation.branch.name,
            'created_by':   reservation.created_by.full_name if reservation.created_by_id else '—',
            'created_at':   reservation.created_at.isoformat(),
            'updated_at':   reservation.updated_at.isoformat(),
            # Customer PII — masked by role
            'customer_name':  (
                (reservation.customer.name if reservation.customer_id else reservation.contact_name)
                if can_see_pii else '—'
            ),
            'customer_phone': (
                (reservation.customer.phone if reservation.customer_id else reservation.contact_phone)
                if can_see_pii else '—'
            ),
            # Item
            'item': {
                'name':         item_name,
                'softech_id':   reservation.item.softech_id if reservation.item_id else None,
                'scientific':   reservation.item.name_scientific if reservation.item_id else '',
                'quantity':     float(reservation.quantity_requested),
            },
            'notes':          reservation.notes,
            'expected_arrival_date': (
                reservation.expected_arrival_date.isoformat()
                if reservation.expected_arrival_date else None
            ),
            'downpayments': [
                {
                    'amount':         float(d['amount']),
                    'payment_method': d['payment_method'],
                    'received_at':    d['received_at'].isoformat() if hasattr(d['received_at'], 'isoformat') else str(d['received_at']),
                }
                for d in downpayments
            ],
            'total_paid': float(total_paid),
            'printed_by':  profile.full_name if profile else '—',
            'printed_at':  timezone.now().isoformat(),
        }
        return Response(receipt)

    # ── WhatsApp Share ─────────────────────────────────────────────────────────

    @action(detail=True, methods=['post'], url_path='share-whatsapp')
    def share_whatsapp(self, request, pk=None):
        """
        POST /api/reservations/{id}/share-whatsapp/

        Generates a WhatsApp-ready text message and logs the share event.
        The frontend opens https://wa.me/?text=<encoded> in a new tab.

        Respects PII permissions — customer name/phone masked if not authorized.
        """
        reservation = self.get_object()
        profile     = get_profile(request)
        can_see_pii = (profile and profile.role in _PII_ROLES)

        customer_name = (
            (reservation.customer.name if reservation.customer_id else reservation.contact_name)
            if can_see_pii else '—'
        )

        item_name = reservation.item_label
        branch_name = reservation.branch.name_ar or reservation.branch.name
        created_at_str = reservation.created_at.strftime('%Y-%m-%d %H:%M')

        lines = [
            '📋 *طلب حجز — صيدليات الرزيقي*',
            f'رقم الطلب: {reservation.id}',
            f'الحالة: {reservation.status_label_ar}',
            f'الفرع: {branch_name}',
            '',
            '*الصنف:*',
            f'• {item_name} × {reservation.quantity_requested}',
        ]
        if reservation.notes:
            lines += ['', f'ملاحظات: {reservation.notes}']
        if can_see_pii:
            lines += ['', f'العميل: {customer_name}']
        lines += ['', f'التاريخ: {created_at_str}']

        message_text = '\n'.join(lines)

        # Audit log
        log_activity(
            reservation=reservation,
            activity_type='note',
            message='تم مشاركة الحجز عبر واتساب',
            staff=profile,
        )

        return Response({'message_text': message_text})

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
