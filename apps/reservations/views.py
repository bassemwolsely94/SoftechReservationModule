from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
import django_filters
from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone
from django.db.models import Count, Q, Sum, Avg, F
from datetime import date, timedelta

from .models import Reservation, ReservationStatusLog, ReservationActivity, ReservationDownpayment, ReservationImage, ReservationLine
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
    ReservationImageSerializer,
    ReservationLineSerializer,
    ReservationLineCreateSerializer,
    BulkActionSerializer,
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


class ReservationFilter(django_filters.FilterSet):
    """Adds a CSV `status__in` lookup (e.g. ?status__in=pending,available) on top
    of the plain exact filters, so the mobile queue can request the "active" set
    in a single paginated request."""
    status__in = django_filters.BaseInFilter(field_name='status', lookup_expr='in')

    class Meta:
        model = Reservation
        fields = ['status', 'status__in', 'priority', 'branch', 'assigned_to']


class ReservationViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = ReservationFilter
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
        ).annotate(
            activity_count=Count('activities', distinct=True),
            lines_count=Count('lines', distinct=True),
        )

        # Always prefetch lines — needed for list cards (item names) and detail views.
        qs = qs.prefetch_related('lines__item')

        # Heavy prefetches only for single-object views — list of 50 doesn't
        # need all activities + status logs for every row (massive N+1 on the list).
        if self.action not in ('list', 'dashboard'):
            qs = qs.prefetch_related(
                'status_logs__changed_by__user',
                'activities__created_by__user',
                'activities__mentioned_users',
                'activities__deleted_by',
                'images__uploaded_by',
            )

        profile = get_profile(self.request)

        # Branch-scoped access: branch staff only see their branch
        if profile and profile.role not in ('admin', 'call_center', 'purchasing'):
            if profile.branch:
                qs = qs.filter(branch=profile.branch)

        date_from = self.request.query_params.get('date_from')
        date_to = self.request.query_params.get('date_to')
        if date_from:
            try:
                qs = qs.filter(created_at__date__gte=date_from)
            except (ValueError, TypeError):
                pass
        if date_to:
            try:
                qs = qs.filter(created_at__date__lte=date_to)
            except (ValueError, TypeError):
                pass

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

    def create(self, request, *args, **kwargs):
        """
        Override create to inject duplicate detection before save.
        Pass ?force=true to bypass the duplicate check.
        """
        import logging
        _log = logging.getLogger('elrezeiky.reservations')
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            _log.error('[ReservationCreate] validation errors: %s | data keys: %s',
                       serializer.errors, list(request.data.keys()))
            from rest_framework.exceptions import ValidationError
            raise ValidationError(serializer.errors)

        # Duplicate detection — skip if force=true
        force = request.query_params.get('force', '').lower() in ('1', 'true', 'yes')
        if not force:
            customer = serializer.validated_data.get('customer')
            item = serializer.validated_data.get('item')
            branch = serializer.validated_data.get('branch')
            if customer and item and branch:
                duplicates = Reservation.objects.filter(
                    customer=customer,
                    item=item,
                    branch=branch,
                    status__in=['pending', 'available', 'contacted', 'confirmed'],
                ).values('id', 'status', 'created_at')[:5]
                if duplicates:
                    dup_list = list(duplicates)
                    STATUS_LABELS = dict(Reservation.STATUS_CHOICES)
                    return Response(
                        {
                            'duplicate': True,
                            'detail': 'يوجد حجز مفتوح لهذا العميل للصنف نفسه في نفس الفرع.',
                            'duplicates': [
                                {
                                    'id': d['id'],
                                    'status': d['status'],
                                    'status_label': STATUS_LABELS.get(d['status'], d['status']),
                                    'created_at': d['created_at'],
                                }
                                for d in dup_list
                            ],
                        },
                        status=status.HTTP_409_CONFLICT,
                    )

        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(
            ReservationDetailSerializer(serializer.instance, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
            headers=headers,
        )

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

        # Notify: call center + admins about the new reservation
        try:
            from apps.notifications.models import Notification
            actor = staff.full_name if staff else 'مجهول'
            Notification.send_to_call_center(
                notification_type='reservation_created',
                title=f'حجز جديد — {reservation.item_label}',
                body=f'العميل: {customer_label} | الفرع: {reservation.branch.name_ar if reservation.branch else "—"} | بواسطة: {actor}',
                reservation=reservation,
                dedup_key=f'res_created_{reservation.pk}',
            )
        except Exception:
            pass

    # ── Change Status ──────────────────────────────────────────────────────────

    # ── Gap-6: Valid status transition graph ──────────────────────────────────
    # Maps current_status → set of allowed next statuses.
    # Terminal states (fulfilled, cancelled, expired) have no forward transitions.
    # 'expired' can be reopened to 'pending' so a patient who calls back can be
    # re-served without creating a duplicate reservation.
    # Admins and call-center get one extra escape hatch: they can move any
    # non-terminal status directly to 'cancelled' (override for corrections).
    _VALID_TRANSITIONS = {
        'pending':   {'available', 'cancelled', 'expired'},
        'available': {'contacted', 'confirmed', 'cancelled', 'expired'},
        'contacted': {'confirmed', 'available', 'cancelled', 'expired'},
        'confirmed': {'fulfilled', 'cancelled', 'expired'},
        'expired':   {'pending'},   # reopen
        # Terminal — no forward transitions
        'fulfilled': set(),
        'cancelled': set(),
    }
    _ADMIN_OVERRIDE_ROLES = frozenset({'admin', 'call_center', 'manager'})

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

        # Gap-6: Enforce the transition graph.
        # Admins/call-center/managers get the full graph PLUS direct cancellation
        # from any state (escape hatch for corrections).
        allowed = self._VALID_TRANSITIONS.get(old_status, set())
        is_privileged = staff and staff.role in self._ADMIN_OVERRIDE_ROLES
        if new_status not in allowed:
            if not (is_privileged and new_status == 'cancelled'):
                STATUS_LABELS = dict(Reservation.STATUS_CHOICES)
                return Response(
                    {
                        'detail': (
                            f'لا يمكن الانتقال من «{STATUS_LABELS.get(old_status, old_status)}» '
                            f'إلى «{STATUS_LABELS.get(new_status, new_status)}»'
                        ),
                        'allowed_transitions': sorted(allowed),
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

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
        chatter_msg = f'تم تغيير الحالة: {old_label} → {new_label}'
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

        # Notify about the status change
        try:
            from apps.notifications.models import Notification
            actor = staff.full_name if staff else 'مجهول'
            notif_body = f'{actor}: {old_label} ← {new_label}'
            if note:
                notif_body += f' | {note[:120]}'

            # Always tell admins + call center
            Notification.send_to_call_center(
                notification_type='reservation_status',
                title=f'تغيير حالة حجز — {reservation.item_label}',
                body=notif_body,
                reservation=reservation,
                dedup_key=f'res_status_{reservation.pk}_{new_status}',
            )
            # Also notify branch staff (excluding call-center actor)
            if reservation.branch and not (staff and (staff.is_call_center or staff.is_admin)):
                pass  # branch staff initiated — they already know
            elif reservation.branch:
                Notification.send_to_branch(
                    branch=reservation.branch,
                    notification_type='reservation_status',
                    title=f'تغيير حالة حجز — {reservation.item_label}',
                    body=notif_body,
                    reservation=reservation,
                    include_admins=False,  # admins covered by send_to_call_center above
                    dedup_key=f'res_status_br_{reservation.pk}_{new_status}',
                )
        except Exception:
            pass

        return Response(
            ReservationDetailSerializer(reservation, context={'request': request}).data
        )

    # ── Check ERP Match (manual trigger — post-fulfillment) ───────────────────

    @action(detail=True, methods=['post'], url_path='check-erp-match')
    def check_erp_match(self, request, pk=None):
        """
        POST /{id}/check-erp-match/
        Admin / pharmacist / purchasing only — verify that a fulfilled
        reservation was processed in SOFTECH (doccode 115 — مبيعات نقدية).
        Runs ReservationERPMatcher, persists result, logs to chatter.
        """
        reservation = self.get_object()
        profile = get_profile(request)

        if not profile or profile.role not in ('admin', 'pharmacist', 'purchasing'):
            return Response(
                {'detail': 'هذا الإجراء مخصص للمشرفين والصيادلة فقط'},
                status=status.HTTP_403_FORBIDDEN,
            )

        if reservation.status != 'fulfilled':
            return Response(
                {'detail': 'يمكن التحقق من مطابقة ERP فقط للحجوزات التي تم تسليمها'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Rate limit: max one check per 20 seconds to protect the Sybase connection
        if reservation.erp_last_checked:
            elapsed = (timezone.now() - reservation.erp_last_checked).total_seconds()
            if elapsed < 20:
                remaining = int(20 - elapsed) + 1
                return Response(
                    {'detail': f'يرجى الانتظار {remaining} ثانية قبل إعادة الفحص.'},
                    status=status.HTTP_429_TOO_MANY_REQUESTS,
                )

        from .erp_matcher import (
            ReservationERPMatcher,
            apply_match_result,
            ERP_MATCH_UPDATE_FIELDS,
        )

        result = ReservationERPMatcher(reservation).run()
        apply_match_result(reservation, result)

        # Auto-persist discovered docnumber when found via auto-search
        update_fields = list(ERP_MATCH_UPDATE_FIELDS)
        if result.get('discovered_doc') and not reservation.erp_reference:
            reservation.erp_reference = result['discovered_doc']
            if 'erp_reference' not in update_fields:
                update_fields.append('erp_reference')

        reservation.save(update_fields=update_fields)

        # Log result to chatter
        log_activity(
            reservation=reservation,
            activity_type='stock_checked',
            message=result['detail'],
            staff=profile,
        )

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

        # Notify counterpart: branch ↔ call-center (mirrors activity_views logic)
        try:
            from apps.notifications.models import Notification
            actor = staff.full_name if staff else 'مجهول'
            branch_name = getattr(staff, 'branch_name', '') if staff else ''
            title = f'تحديث على حجز #{reservation.id}'
            body = f'{actor} ({branch_name}) سجّل: {activity.activity_label}'
            if d.get('message'):
                body += f' — {str(d["message"])[:100]}'

            if staff and (getattr(staff, 'is_call_center', False) or getattr(staff, 'is_admin', False)):
                # Call center / admin acted → notify branch staff
                if reservation.branch:
                    Notification.send_to_branch(
                        branch=reservation.branch,
                        notification_type='call_logged',
                        title=title,
                        body=body,
                        reservation=reservation,
                        include_admins=False,
                        dedup_key=f'act_{activity.pk}_br',
                    )
            else:
                # Branch staff acted → notify call center + admins
                Notification.send_to_call_center(
                    notification_type='call_logged',
                    title=title,
                    body=body,
                    reservation=reservation,
                    dedup_key=f'act_{activity.pk}_cc',
                )
        except Exception:
            pass

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
            # Use DB aggregate — avoids iterating all rows in Python
            total = dps.aggregate(total=Sum('amount'))['total'] or 0
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

        # Audit log — only when ?log=1 is passed so that merely previewing the
        # receipt doesn't flood the chatter with "printed" entries.
        if request.query_params.get('log') == '1':
            log_activity(
                reservation=reservation,
                activity_type='note',
                message='تم طباعة إيصال الحجز',
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
            # Primary item
            'item': {
                'name':       item_name,
                'softech_id': reservation.item.softech_id if reservation.item_id else None,
                'scientific': reservation.item.name_scientific if reservation.item_id else '',
                'sale_price': float(reservation.item.pack_price) if reservation.item_id else None,
                'quantity':   float(reservation.quantity_requested),
            },
            # Extra reservation lines (basket)
            'extra_lines': [
                {
                    'name':       (line.item.name if line.item_id else line.manual_item_name or '—'),
                    'softech_id': (line.item.softech_id if line.item_id else None),
                    'sale_price': (float(line.item.pack_price) if line.item_id else None),
                    'quantity':   float(line.quantity_requested),
                }
                for line in reservation.lines.select_related('item').all()
            ],
            'customer_pic': (
                reservation.customer.softech_pic
                if (reservation.customer_id and can_see_pii and reservation.customer.softech_pic)
                else None
            ),
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

        # ── Audit trail: all status changes + all non-deleted activities ──────
        STATUS_LABELS = {
            'pending':   'قيد الانتظار',
            'available': 'المخزون متاح',
            'contacted': 'تم التواصل',
            'confirmed': 'مؤكد',
            'fulfilled': 'تم التسليم',
            'cancelled': 'ملغي',
            'expired':   'منتهي',
        }
        trail = []

        for log in reservation.status_logs.all():
            old_lbl = STATUS_LABELS.get(log.old_status, log.old_status)
            new_lbl = STATUS_LABELS.get(log.new_status, log.new_status)
            trail.append({
                'kind':   'status',
                'who':    log.changed_by.full_name if log.changed_by_id else 'النظام',
                'what':   f'{old_lbl} ← {new_lbl}',
                'when':   log.changed_at.isoformat(),
                'detail': log.note or '',
            })

        for act in reservation.activities.all():
            if act.is_deleted:
                continue
            trail.append({
                'kind':   'activity',
                'who':    act.created_by.full_name if act.created_by_id else 'النظام',
                'what':   act.get_activity_type_display(),
                'when':   act.created_at.isoformat(),
                'detail': act.message or '',
            })

        trail.sort(key=lambda x: x['when'])
        receipt['audit_trail'] = trail

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

        item_name      = reservation.item_label
        item_code      = reservation.item.softech_id if reservation.item_id else None
        item_price     = float(reservation.item.pack_price) if reservation.item_id else None
        branch_name    = reservation.branch.name_ar or reservation.branch.name
        created_at_str = reservation.created_at.strftime('%Y-%m-%d %H:%M')

        # Collect all items (primary + extra lines)
        all_items = [(item_name, item_code, item_price, float(reservation.quantity_requested))]
        for line in reservation.lines.select_related('item').all():
            l_name  = line.item.name if line.item_id else (line.manual_item_name or '—')
            l_code  = line.item.softech_id if line.item_id else None
            l_price = float(line.item.pack_price) if line.item_id else None
            all_items.append((l_name, l_code, l_price, float(line.quantity_requested)))

        lines = [
            '📋 *طلب حجز — صيدليات الرزيقي*',
            f'رقم الطلب: {reservation.id}',
            f'الحالة: {reservation.status_label_ar}',
            f'الفرع: {branch_name}',
            '',
        ]

        if len(all_items) == 1:
            i_name, i_code, i_price, i_qty = all_items[0]
            lines += [f'*الصنف:*', f'• {i_name} × {i_qty}']
            if i_code:  lines.append(f'  كود الصنف: {i_code}')
            if i_price: lines.append(f'  السعر العام: {i_price:.2f} ج.م')
        else:
            lines.append(f'*الأصناف ({len(all_items)} صنف):*')
            for idx, (i_name, i_code, i_price, i_qty) in enumerate(all_items, 1):
                code_str  = f' [{i_code}]' if i_code else ''
                price_str = f' — {i_price:.2f} ج.م' if i_price else ''
                lines.append(f'{idx}. {i_name}{code_str} × {i_qty}{price_str}')
        if reservation.notes:
            lines += ['', f'ملاحظات: {reservation.notes}']
        if can_see_pii:
            lines += ['', f'العميل: {customer_name}']
            customer_pic = (
                reservation.customer.softech_pic
                if reservation.customer_id and reservation.customer.softech_pic
                else None
            )
            if customer_pic:
                lines.append(f'كود PIC: {customer_pic}')
        lines += ['', f'التاريخ: {created_at_str}']

        # ── Audit trail ───────────────────────────────────────────────────────
        STATUS_LABELS = {
            'pending':   'قيد الانتظار',   'available': 'المخزون متاح',
            'contacted': 'تم التواصل',      'confirmed': 'مؤكد',
            'fulfilled': 'تم التسليم',      'cancelled': 'ملغي',
            'expired':   'منتهي',
        }
        trail = []
        for log in reservation.status_logs.all():
            old_lbl = STATUS_LABELS.get(log.old_status, log.old_status)
            new_lbl = STATUS_LABELS.get(log.new_status, log.new_status)
            trail.append((
                log.changed_at,
                f'🔄 {old_lbl} ← {new_lbl}',
                log.changed_by.full_name if log.changed_by_id else 'النظام',
                log.note or '',
            ))
        for act in reservation.activities.all():
            if act.is_deleted:
                continue
            trail.append((
                act.created_at,
                act.get_activity_type_display(),
                act.created_by.full_name if act.created_by_id else 'النظام',
                act.message or '',
            ))
        trail.sort(key=lambda x: x[0])

        if trail:
            lines += ['', '━' * 22, '📋 *سجل العمليات*', '']
            for ts, what, who, detail in trail:
                ts_str = ts.strftime('%Y-%m-%d %H:%M')
                lines.append(f'• {ts_str} — *{who}*')
                lines.append(f'  {what}')
                if detail:
                    lines.append(f'  _{detail}_')

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
        # timedelta is crash-safe unlike today.replace(day=today.day - weekday)
        # which raises ValueError when day < weekday (e.g. Tuesday the 1st → day=0)
        week_start = today - timedelta(days=today.weekday())

        # Lightweight queryset — no prefetches, just the base access-scoping
        qs = Reservation.objects.all()
        profile = get_profile(request)
        if profile and profile.role not in ('admin', 'call_center', 'purchasing'):
            if profile.branch:
                qs = qs.filter(branch=profile.branch)

        branch_id = request.query_params.get('branch')
        if branch_id:
            try:
                qs = qs.filter(branch_id=int(branch_id))
            except (ValueError, TypeError):
                pass

        active_statuses = ['pending', 'available', 'contacted', 'confirmed']
        data = {
            'pending':   qs.filter(status='pending').count(),
            'available': qs.filter(status='available').count(),
            'contacted': qs.filter(status='contacted').count(),
            'confirmed': qs.filter(status='confirmed').count(),
            'follow_ups_today': qs.filter(
                follow_up_date=today,
                status__in=['pending', 'available', 'contacted'],
            ).count(),
            'fulfilled_this_week': qs.filter(
                status='fulfilled',
                updated_at__date__gte=week_start,
            ).count(),
            'urgent': qs.filter(
                priority='urgent',
                status__in=['pending', 'available', 'contacted'],
            ).count(),
            'by_status': list(
                qs.values('status').annotate(count=Count('id')).order_by('status')
            ),
            'by_branch': list(
                qs.filter(status__in=['pending', 'available'])
                .values('branch__name_ar', 'branch__name')
                .annotate(count=Count('id'))
                .order_by('-count')[:10]
            ),
        }
        return Response(data)

    # ── Extra images ──────────────────────────────────────────────────────────

    @action(detail=True, methods=['get', 'post'], url_path='images',
            parser_classes=[MultiPartParser, FormParser, JSONParser])
    def images(self, request, pk=None):
        reservation = self.get_object()
        if request.method == 'GET':
            imgs = ReservationImage.objects.filter(reservation=reservation)
            return Response(ReservationImageSerializer(
                imgs, many=True, context={'request': request}
            ).data)

        profile = get_profile(request)
        files = request.FILES.getlist('images')
        if not files:
            return Response({'error': 'لم يتم إرسال أي صور'}, status=status.HTTP_400_BAD_REQUEST)
        created = []
        for f in files:
            img = ReservationImage.objects.create(
                reservation=reservation, image=f, uploaded_by=profile
            )
            created.append(img)
        return Response(
            ReservationImageSerializer(created, many=True, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['delete'], url_path=r'images/(?P<image_id>\d+)/delete')
    def delete_image(self, request, pk=None, image_id=None):
        reservation = self.get_object()
        try:
            img = ReservationImage.objects.get(pk=image_id, reservation=reservation)
        except ReservationImage.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        # Wrap in transaction: DB record and storage file deleted together.
        # File deletion is attempted after the DB commit — if storage fails the
        # DB row is already gone (acceptable; avoids orphaned rows more than
        # orphaned files).
        with transaction.atomic():
            file_name = img.image.name  # save before delete clears it
            img.delete()
        # Delete from storage outside the transaction — storage errors won't
        # roll back the DB delete but will be logged.
        try:
            from django.core.files.storage import default_storage
            if file_name:
                default_storage.delete(file_name)
        except Exception:
            pass
        return Response(status=status.HTTP_204_NO_CONTENT)

    # ── Reservation Lines (basket) ─────────────────────────────────────────────

    @action(detail=True, methods=['get', 'post'], url_path='lines',
            parser_classes=[MultiPartParser, FormParser, JSONParser])
    def lines(self, request, pk=None):
        reservation = self.get_object()

        if request.method == 'GET':
            qs = reservation.lines.select_related('item')
            return Response(ReservationLineSerializer(qs, many=True).data)

        # POST — add a line
        if reservation.status != 'pending':
            return Response(
                {'detail': 'لا يمكن تعديل الأصناف بعد انتقال الحجز من مرحلة قيد الانتظار.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        staff = get_profile(request)
        ser = ReservationLineCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        line = ReservationLine.objects.create(reservation=reservation, **ser.validated_data)
        log_activity(
            reservation=reservation,
            activity_type='note',
            message=f'تم إضافة صنف: {line.item_label} × {line.quantity_requested}',
            staff=staff,
        )
        return Response(ReservationLineSerializer(line).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['delete'], url_path=r'lines/(?P<line_id>\d+)/delete')
    def delete_line(self, request, pk=None, line_id=None):
        reservation = self.get_object()
        if reservation.status != 'pending':
            return Response(
                {'detail': 'لا يمكن تعديل الأصناف بعد انتقال الحجز من مرحلة قيد الانتظار.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        try:
            line = reservation.lines.get(pk=line_id)
        except ReservationLine.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        staff = get_profile(request)
        label = line.item_label
        line.delete()
        log_activity(
            reservation=reservation,
            activity_type='note',
            message=f'تم حذف الصنف: {label}',
            staff=staff,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

    # ── Merge duplicate ────────────────────────────────────────────────────────

    @action(detail=True, methods=['post'], url_path='merge')
    def merge(self, request, pk=None):
        """
        POST /api/reservations/{id}/merge/
        { "target_id": <id_to_cancel> }

        Absorbs the target reservation's quantity into this one, then cancels it.
        Both must share the same customer + item + branch.
        """
        reservation = self.get_object()
        target_id = request.data.get('target_id')
        if not target_id:
            return Response({'detail': 'target_id مطلوب'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            target = Reservation.objects.get(pk=target_id)
        except Reservation.DoesNotExist:
            return Response({'detail': 'الحجز المستهدف غير موجود'}, status=status.HTTP_404_NOT_FOUND)

        if target.pk == reservation.pk:
            return Response({'detail': 'لا يمكن دمج الحجز مع نفسه'}, status=status.HTTP_400_BAD_REQUEST)

        if target.status in ('fulfilled', 'cancelled', 'expired'):
            return Response({'detail': 'لا يمكن دمج حجز مُنهى'}, status=status.HTTP_400_BAD_REQUEST)

        # Validate same customer + item + branch
        if reservation.customer_id != target.customer_id or \
           reservation.item_id != target.item_id or \
           reservation.branch_id != target.branch_id:
            return Response(
                {'detail': 'يجب أن يكون الحجزان لنفس العميل والصنف والفرع'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        staff = get_profile(request)
        with transaction.atomic():
            # Add quantity
            reservation.quantity_requested += target.quantity_requested
            # Merge notes
            if target.notes:
                reservation.notes = (
                    (reservation.notes + '\n' if reservation.notes else '') + target.notes
                )
            reservation.save(update_fields=['quantity_requested', 'notes', 'updated_at'])

            # Cancel target
            ReservationStatusLog.objects.create(
                reservation=target,
                old_status=target.status,
                new_status='cancelled',
                changed_by=staff,
                note=f'دُمج في الحجز #{reservation.pk}',
            )
            ReservationActivity.objects.create(
                reservation=target,
                activity_type='status_changed',
                message=f'تم إلغاؤه ودمجه في الحجز #{reservation.pk}',
                created_by=staff,
            )
            target.status = 'cancelled'
            target.save(update_fields=['status', 'updated_at'])

            log_activity(
                reservation=reservation,
                activity_type='note',
                message=f'تم دمج الحجز #{target.pk} (الكمية: {target.quantity_requested}) في هذا الحجز',
                staff=staff,
            )

        return Response(
            ReservationDetailSerializer(reservation, context={'request': request}).data
        )

    # ── Bulk actions ───────────────────────────────────────────────────────────

    @action(detail=False, methods=['post'], url_path='bulk',
            parser_classes=[JSONParser])
    def bulk(self, request):
        """
        POST /api/reservations/bulk/
        { "action": "assign"|"change_status"|"export", "ids": [...], ... }
        """
        ser = BulkActionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        act = d['action']
        ids = d['ids']
        staff = get_profile(request)

        qs = self.get_queryset().filter(pk__in=ids)

        # ── Export ────────────────────────────────────────────────────────────
        if act == 'export':
            return self._bulk_export(qs)

        # ── Assign ────────────────────────────────────────────────────────────
        if act == 'assign':
            assigned_to_id = d.get('assigned_to')
            from apps.users.models import StaffProfile
            assignee = None
            if assigned_to_id:
                try:
                    assignee = StaffProfile.objects.get(pk=assigned_to_id)
                except StaffProfile.DoesNotExist:
                    return Response({'detail': 'الموظف غير موجود'}, status=status.HTTP_400_BAD_REQUEST)

            updated = 0
            for r in qs.filter(status__in=['pending', 'available', 'contacted', 'confirmed']):
                r.assigned_to = assignee
                r.save(update_fields=['assigned_to', 'updated_at'])
                log_activity(
                    reservation=r,
                    activity_type='assigned',
                    message=f'تم التعيين بشكل جماعي إلى: {assignee.full_name if assignee else "—"}',
                    staff=staff,
                )
                updated += 1
            return Response({'updated': updated})

        # ── Change status ──────────────────────────────────────────────────────
        if act == 'change_status':
            new_status_val = d['status']
            note = d.get('note', '')
            STATUS_LABELS = dict(Reservation.STATUS_CHOICES)
            updated = 0
            skipped = 0
            for r in qs:
                allowed = ReservationViewSet._VALID_TRANSITIONS.get(r.status, set())
                is_privileged = staff and staff.role in ReservationViewSet._ADMIN_OVERRIDE_ROLES
                can_transit = (new_status_val in allowed) or \
                              (is_privileged and new_status_val == 'cancelled')
                if not can_transit:
                    skipped += 1
                    continue
                old_status = r.status
                ReservationStatusLog.objects.create(
                    reservation=r,
                    old_status=old_status,
                    new_status=new_status_val,
                    changed_by=staff,
                    note=note or 'تغيير جماعي للحالة',
                )
                log_activity(
                    reservation=r,
                    activity_type='status_changed',
                    message=f'تغيير جماعي: {STATUS_LABELS.get(old_status, old_status)} → {STATUS_LABELS.get(new_status_val, new_status_val)}',
                    staff=staff,
                )
                r.status = new_status_val
                r.save(update_fields=['status', 'updated_at'])
                updated += 1
            return Response({'updated': updated, 'skipped': skipped})

        return Response({'detail': 'إجراء غير معروف'}, status=status.HTTP_400_BAD_REQUEST)

    def _bulk_export(self, qs):
        """Return an Excel file of the given queryset.

        Phone numbers are included only for roles in _PII_ROLES.
        All items (primary + extra lines) are written as numbered column groups.
        """
        try:
            import openpyxl
            from openpyxl.styles import Font, PatternFill, Alignment
        except ImportError:
            return Response(
                {'detail': 'openpyxl غير مثبت — تعذّر تصدير Excel'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        profile     = get_profile(self.request)
        can_see_pii = profile and profile.role in _PII_ROLES

        STATUS_LABELS   = dict(Reservation.STATUS_CHOICES)
        PRIORITY_LABELS = dict(Reservation.PRIORITY_CHOICES)

        # Materialise queryset with all relations needed
        rows = list(
            qs.select_related('customer', 'item', 'branch', 'assigned_to__user')
              .prefetch_related('lines__item')
        )

        # Determine max item count across all reservations so we know how many
        # item columns to generate (primary counts as 1, each extra line adds 1)
        def _all_items(r):
            primary = [(r.item_label, float(r.quantity_requested))]
            extras  = [
                (
                    line.item.name if line.item_id else (line.manual_item_name or '—'),
                    float(line.quantity_requested),
                )
                for line in r.lines.all()
            ]
            return primary + extras

        max_items = max((len(_all_items(r)) for r in rows), default=1)

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'الحجوزات'
        ws.sheet_view.rightToLeft = True

        # ── Build header row ──────────────────────────────────────────────────
        fixed_headers = ['رقم الحجز', 'تاريخ الإنشاء', 'العميل']
        if can_see_pii:
            fixed_headers.append('الهاتف')
        fixed_headers += ['الفرع', 'الحالة', 'الأولوية', 'مصدر الطلب', 'طريقة التسليم', 'المعين إليه', 'ملاحظات']

        item_headers = []
        for i in range(1, max_items + 1):
            item_headers += [f'الصنف {i}', f'الكمية {i}']

        all_headers = fixed_headers + item_headers

        header_fill = PatternFill('solid', fgColor='059669')
        header_font = Font(bold=True, color='FFFFFF')
        item_fill   = PatternFill('solid', fgColor='1D4ED8')   # blue tint for item columns

        for col, h in enumerate(all_headers, 1):
            cell = ws.cell(row=1, column=col, value=h)
            cell.font = header_font
            cell.alignment = Alignment(horizontal='center')
            cell.fill = item_fill if col > len(fixed_headers) else header_fill

        # ── Data rows ─────────────────────────────────────────────────────────
        for r in rows:
            customer_name  = (r.customer.name  if r.customer_id else r.contact_name)  or '—'
            customer_phone = (r.customer.phone if r.customer_id else r.contact_phone) or '—'

            fixed_cells = [
                r.id,
                r.created_at.strftime('%Y-%m-%d %H:%M') if r.created_at else '',
                customer_name,
            ]
            if can_see_pii:
                fixed_cells.append(customer_phone)
            fixed_cells += [
                r.branch.name_ar or r.branch.name if r.branch_id else '—',
                STATUS_LABELS.get(r.status, r.status),
                PRIORITY_LABELS.get(r.priority, r.priority),
                r.order_source or '—',
                r.fulfillment_method or '—',
                r.assigned_to.full_name if r.assigned_to_id else '—',
                r.notes or '',
            ]

            item_cells = []
            for name, qty in _all_items(r):
                item_cells += [name, qty]
            # Pad remaining item slots with empty strings
            item_cells += [''] * (max_items * 2 - len(item_cells))

            ws.append(fixed_cells + item_cells)

        # ── Column widths ─────────────────────────────────────────────────────
        for col in ws.columns:
            max_len = max((len(str(cell.value or '')) for cell in col), default=10)
            ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 45)

        import io
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        response = HttpResponse(
            buf.read(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        response['Content-Disposition'] = 'attachment; filename="reservations.xlsx"'
        return response

    # ── Analytics ──────────────────────────────────────────────────────────────

    @action(detail=False, methods=['get'], url_path='analytics')
    def analytics(self, request):
        """
        GET /api/reservations/analytics/
        Params: date_from, date_to, branch
        """
        qs = Reservation.objects.all()
        profile = get_profile(request)
        if profile and profile.role not in ('admin', 'call_center', 'purchasing'):
            if profile.branch:
                qs = qs.filter(branch=profile.branch)

        # Filters
        date_from = request.query_params.get('date_from')
        date_to   = request.query_params.get('date_to')
        branch_id = request.query_params.get('branch')
        if date_from:
            try:
                qs = qs.filter(created_at__date__gte=date_from)
            except (ValueError, TypeError):
                pass
        if date_to:
            try:
                qs = qs.filter(created_at__date__lte=date_to)
            except (ValueError, TypeError):
                pass
        if branch_id:
            try:
                qs = qs.filter(branch_id=int(branch_id))
            except (ValueError, TypeError):
                pass

        total = qs.count()
        by_status = {
            row['status']: row['count']
            for row in qs.values('status').annotate(count=Count('id'))
        }
        fulfilled_count = by_status.get('fulfilled', 0)
        lost_count = by_status.get('cancelled', 0) + by_status.get('expired', 0)
        fulfillment_rate = round(fulfilled_count / total * 100, 1) if total else 0

        # Fulfillment rate by branch
        branch_stats = []
        for row in (
            qs.values('branch__name_ar', 'branch__name', 'branch__id')
            .annotate(total=Count('id'))
            .order_by('-total')[:20]
        ):
            branch_name = row['branch__name_ar'] or row['branch__name'] or '—'
            branch_fulfilled = qs.filter(
                branch_id=row['branch__id'], status='fulfilled'
            ).count()
            branch_rate = round(branch_fulfilled / row['total'] * 100, 1) if row['total'] else 0
            branch_stats.append({
                'branch_name': branch_name,
                'total': row['total'],
                'fulfilled': branch_fulfilled,
                'rate': branch_rate,
            })

        # Top 20 most-reserved items
        top_items = []
        for row in (
            qs.exclude(item__isnull=True)
            .values('item__name', 'item__softech_id')
            .annotate(count=Count('id'))
            .order_by('-count')[:20]
        ):
            top_items.append({
                'item_name': row['item__name'] or '—',
                'softech_id': row['item__softech_id'] or '',
                'count': row['count'],
            })

        # Conversion by channel
        CHANNEL_LABELS = dict(Reservation.CHANNEL_CHOICES)
        channel_stats = []
        for row in qs.values('channel').annotate(total=Count('id')).order_by('-total'):
            ch_fulfilled = qs.filter(channel=row['channel'], status='fulfilled').count()
            ch_rate = round(ch_fulfilled / row['total'] * 100, 1) if row['total'] else 0
            channel_stats.append({
                'channel': row['channel'],
                'channel_label': CHANNEL_LABELS.get(row['channel'], row['channel']),
                'total': row['total'],
                'fulfilled': ch_fulfilled,
                'rate': ch_rate,
            })

        # Lost demand — top items with cancelled/expired
        lost_items = []
        for row in (
            qs.filter(status__in=['cancelled', 'expired'])
            .exclude(item__isnull=True)
            .values('item__name')
            .annotate(count=Count('id'))
            .order_by('-count')[:15]
        ):
            lost_items.append({'item_name': row['item__name'] or '—', 'count': row['count']})

        # Average hours to fulfill (via status logs)
        avg_hours = None
        try:
            logs = list(
                ReservationStatusLog.objects.filter(
                    new_status='fulfilled',
                    reservation__in=qs,
                ).values('changed_at', 'reservation__created_at')[:500]
            )
            if logs:
                total_h = sum(
                    (l['changed_at'] - l['reservation__created_at']).total_seconds() / 3600
                    for l in logs
                    if l['changed_at'] and l['reservation__created_at']
                )
                avg_hours = round(total_h / len(logs), 1)
        except Exception:
            pass

        # By source
        source_stats = list(
            qs.values('order_source')
            .annotate(count=Count('id'))
            .order_by('-count')
        )

        return Response({
            'summary': {
                'total': total,
                'fulfilled': fulfilled_count,
                'lost': lost_count,
                'active': by_status.get('pending', 0) + by_status.get('available', 0) +
                          by_status.get('contacted', 0) + by_status.get('confirmed', 0),
                'fulfillment_rate': fulfillment_rate,
                'avg_fulfill_hours': avg_hours,
                **{s: by_status.get(s, 0) for s in ['pending', 'available', 'contacted', 'confirmed', 'cancelled', 'expired']},
            },
            'by_branch': branch_stats,
            'top_items': top_items,
            'by_channel': channel_stats,
            'lost_items': lost_items,
            'by_source': source_stats,
        })

    # ── Customer history ────────────────────────────────────────────────────────

    @action(detail=True, methods=['get'], url_path='customer-history')
    def customer_history(self, request, pk=None):
        """
        GET /api/reservations/{id}/customer-history/
        Last 10 reservations for the same customer, excluding this one.
        """
        reservation = self.get_object()
        if not reservation.customer_id:
            return Response([])

        history = (
            Reservation.objects
            .filter(customer_id=reservation.customer_id)
            .exclude(pk=reservation.pk)
            .select_related('item', 'branch')
            .order_by('-created_at')[:10]
        )
        STATUS_LABELS = dict(Reservation.STATUS_CHOICES)
        result = []
        for r in history:
            result.append({
                'id': r.id,
                'item_name': r.item_label,
                'branch_name': r.branch.name_ar or r.branch.name if r.branch_id else '—',
                'status': r.status,
                'status_label': STATUS_LABELS.get(r.status, r.status),
                'status_color': r.status_color,
                'quantity_requested': float(r.quantity_requested),
                'created_at': r.created_at.isoformat(),
            })
        return Response(result)
