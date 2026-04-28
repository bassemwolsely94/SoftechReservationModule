"""
apps/transfers/views.py

Transfer Request ViewSet — full state machine + item management + chatter.
NO stock mutations. NO ERP calls. Communication + approval only.
"""
from django.utils import timezone
from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend

from .models import TransferRequest, TransferRequestItem, TransferRequestMessage
from .serializers import (
    TransferRequestListSerializer,
    TransferRequestDetailSerializer,
    TransferRequestCreateSerializer,
    TransferRequestUpdateSerializer,
    TransferRequestItemWriteSerializer,
    TransferRequestMessageSerializer,
    TransferRequestMessageCreateSerializer,
    RejectSerializer,
    RevisionSerializer,
    SendToERPSerializer,
)


def _profile(request):
    return getattr(request.user, 'staff_profile', None)


def _can_review(profile):
    """Who can approve/reject: admin, purchasing, call_center (HQ roles)."""
    return profile and profile.role in ('admin', 'purchasing', 'call_center')


def _system_log(request_obj, message):
    TransferRequestMessage.log_system(request_obj, message)


def _notify(transfer_request, title, body, notif_type):
    """Fire in-app notification — non-fatal wrapper."""
    try:
        from apps.users.models import StaffProfile
        from apps.notifications.models import Notification

        # Notify destination branch staff + admins
        recipients = StaffProfile.objects.filter(
            branch=transfer_request.destination_branch,
            is_active=True,
        ) | StaffProfile.objects.filter(
            role__in=('admin', 'purchasing'),
            is_active=True,
        )

        for staff in recipients.distinct():
            try:
                Notification.objects.create(
                    recipient=staff,
                    title=title,
                    body=body or '',
                    notification_type=notif_type,
                )
            except Exception:
                pass
    except Exception:
        pass


class TransferRequestViewSet(viewsets.ModelViewSet):
    """
    CRUD + state machine for transfer requests.

    Standard CRUD:
        list, create, retrieve, partial_update, destroy

    State machine actions:
        submit          POST /{id}/submit/
        approve         POST /{id}/approve/
        reject          POST /{id}/reject/
        request_revision POST /{id}/revision/
        send_to_erp     POST /{id}/send-to-erp/
        complete        POST /{id}/complete/
        cancel          POST /{id}/cancel/

    Item management:
        add_item        POST  /{id}/items/
        remove_item     DELETE /{id}/items/{item_id}/

    Chatter:
        messages        GET/POST /{id}/messages/
    """

    permission_classes  = [IsAuthenticated]
    filter_backends     = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields    = ['status', 'source_branch', 'destination_branch']
    search_fields       = [
        'request_number', 'notes',
        'items__item__name', 'items__item__softech_id',
    ]
    ordering_fields     = ['created_at', 'updated_at', 'status']
    ordering            = ['-created_at']

    def get_queryset(self):
        qs = TransferRequest.objects.select_related(
            'source_branch', 'destination_branch',
            'created_by__user', 'reviewed_by__user',
        ).prefetch_related(
            'items__item',
            'messages__created_by__user',
        )

        profile = _profile(self.request)
        if not profile:
            return qs.none()

        # HQ roles see all
        if profile.role in ('admin', 'purchasing', 'call_center'):
            return qs

        # Branch staff see requests where they are source OR destination
        if profile.branch:
            return qs.filter(
                source_branch=profile.branch
            ) | qs.filter(
                destination_branch=profile.branch
            )

        return qs.none()

    def get_serializer_class(self):
        if self.action == 'list':
            return TransferRequestListSerializer
        if self.action == 'create':
            return TransferRequestCreateSerializer
        if self.action in ('update', 'partial_update'):
            return TransferRequestUpdateSerializer
        return TransferRequestDetailSerializer

    def perform_create(self, serializer):
        profile = _profile(self.request)
        tr = serializer.save(created_by=profile)
        _system_log(tr, f'تم إنشاء الطلب بواسطة {profile.full_name}')

    def perform_destroy(self, instance):
        if instance.status not in ('draft', 'cancelled'):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('لا يمكن حذف طلب تم تقديمه. استخدم الإلغاء بدلاً من ذلك.')
        instance.delete()

    # ── Submit ────────────────────────────────────────────────────────────────

    @action(detail=True, methods=['post'])
    def submit(self, request, pk=None):
        tr = self.get_object()
        profile = _profile(request)

        if not tr.can_submit:
            return Response(
                {'detail': 'لا يمكن تقديم هذا الطلب — تأكد من إضافة أصناف وأن الحالة صحيحة'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        tr.status = 'pending'
        tr.submitted_at = timezone.now()
        tr.save(update_fields=['status', 'submitted_at', 'updated_at'])

        _system_log(tr, f'تم تقديم الطلب بواسطة {profile.full_name}')
        _notify(
            tr,
            f'طلب تحويل جديد — {tr.request_number}',
            f'فرع {tr.source_branch} يطلب تحويل {tr.items.count()} صنف. يرجى المراجعة.',
            'transfer_request',
        )

        return Response(
            TransferRequestDetailSerializer(tr, context={'request': request}).data
        )

    # ── Approve ───────────────────────────────────────────────────────────────

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        tr = self.get_object()
        profile = _profile(request)

        if not _can_review(profile):
            return Response(
                {'detail': 'ليس لديك صلاحية اعتماد الطلبات'},
                status=status.HTTP_403_FORBIDDEN,
            )
        if not tr.can_approve:
            return Response(
                {'detail': 'هذا الطلب لا يمكن اعتماده في حالته الحالية'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        tr.status = 'approved'
        tr.reviewed_by = profile
        tr.reviewed_at = timezone.now()
        tr.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'updated_at'])

        _system_log(tr, f'تم اعتماد الطلب بواسطة {profile.full_name}')
        _notify(
            tr,
            f'تم اعتماد طلبك — {tr.request_number}',
            f'تمت الموافقة على طلب التحويل. يمكنك الآن إرساله للـ ERP.',
            'transfer_response',
        )

        return Response(
            TransferRequestDetailSerializer(tr, context={'request': request}).data
        )

    # ── Reject ────────────────────────────────────────────────────────────────

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        tr = self.get_object()
        profile = _profile(request)

        if not _can_review(profile):
            return Response(
                {'detail': 'ليس لديك صلاحية رفض الطلبات'},
                status=status.HTTP_403_FORBIDDEN,
            )
        if not tr.can_reject:
            return Response(
                {'detail': 'هذا الطلب لا يمكن رفضه في حالته الحالية'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = RejectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        tr.status = 'rejected'
        tr.reviewed_by = profile
        tr.reviewed_at = timezone.now()
        tr.rejection_reason = serializer.validated_data['rejection_reason']
        tr.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'rejection_reason', 'updated_at'])

        _system_log(tr, f'تم رفض الطلب بواسطة {profile.full_name}. السبب: {tr.rejection_reason}')
        _notify(
            tr,
            f'تم رفض طلبك — {tr.request_number}',
            f'سبب الرفض: {tr.rejection_reason}',
            'transfer_response',
        )

        return Response(
            TransferRequestDetailSerializer(tr, context={'request': request}).data
        )

    # ── Request Revision ──────────────────────────────────────────────────────

    @action(detail=True, methods=['post'], url_path='revision')
    def request_revision(self, request, pk=None):
        tr = self.get_object()
        profile = _profile(request)

        if not _can_review(profile):
            return Response(
                {'detail': 'ليس لديك صلاحية طلب التعديل'},
                status=status.HTTP_403_FORBIDDEN,
            )
        if not tr.can_request_revision:
            return Response(
                {'detail': 'لا يمكن طلب التعديل في الحالة الحالية'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = RevisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        tr.status = 'needs_revision'
        tr.reviewed_by = profile
        tr.reviewed_at = timezone.now()
        tr.revision_notes = serializer.validated_data['revision_notes']
        tr.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'revision_notes', 'updated_at'])

        _system_log(tr, f'طُلب التعديل بواسطة {profile.full_name}: {tr.revision_notes}')

        return Response(
            TransferRequestDetailSerializer(tr, context={'request': request}).data
        )

    # ── Send to ERP ───────────────────────────────────────────────────────────

    @action(detail=True, methods=['post'], url_path='send-to-erp')
    def send_to_erp(self, request, pk=None):
        tr = self.get_object()
        profile = _profile(request)

        if not tr.can_send_to_erp:
            return Response(
                {'detail': 'يجب اعتماد الطلب أولاً قبل الإرسال للـ ERP'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = SendToERPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        tr.status = 'sent_to_erp'
        tr.sent_to_erp_at = timezone.now()
        tr.sent_to_erp_by = profile
        tr.erp_reference = serializer.validated_data.get('erp_reference', '')
        tr.save(update_fields=[
            'status', 'sent_to_erp_at', 'sent_to_erp_by', 'erp_reference', 'updated_at'
        ])

        erp_ref = f' (مرجع: {tr.erp_reference})' if tr.erp_reference else ''
        _system_log(
            tr,
            f'تم الإرسال للـ ERP بواسطة {profile.full_name}{erp_ref}'
        )

        return Response(
            TransferRequestDetailSerializer(tr, context={'request': request}).data
        )

    # ── Complete ──────────────────────────────────────────────────────────────

    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        tr = self.get_object()
        profile = _profile(request)

        if tr.status != 'sent_to_erp':
            return Response(
                {'detail': 'يجب إرسال الطلب للـ ERP أولاً'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        tr.status = 'completed'
        tr.completed_at = timezone.now()
        tr.save(update_fields=['status', 'completed_at', 'updated_at'])

        _system_log(tr, f'تم إغلاق الطلب كمكتمل بواسطة {profile.full_name}')

        return Response(
            TransferRequestDetailSerializer(tr, context={'request': request}).data
        )

    # ── Cancel ────────────────────────────────────────────────────────────────

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        tr = self.get_object()
        profile = _profile(request)

        if not tr.can_cancel:
            return Response(
                {'detail': 'لا يمكن إلغاء هذا الطلب في حالته الحالية'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        tr.status = 'cancelled'
        tr.save(update_fields=['status', 'updated_at'])

        _system_log(tr, f'تم إلغاء الطلب بواسطة {profile.full_name}')

        return Response({'detail': 'تم إلغاء الطلب'})

    # ── Item management ───────────────────────────────────────────────────────

    @action(detail=True, methods=['post', 'get'], url_path='items')
    def items(self, request, pk=None):
        tr = self.get_object()

        if request.method == 'GET':
            from .serializers import TransferRequestItemSerializer
            return Response(
                TransferRequestItemSerializer(tr.items.all(), many=True).data
            )

        # POST — add item
        if not tr.is_editable:
            return Response(
                {'detail': 'لا يمكن تعديل الأصناف في حالة الطلب الحالية'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = TransferRequestItemWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item_obj = serializer.validated_data['item']

        if tr.items.filter(item=item_obj).exists():
            return Response(
                {'detail': f'الصنف "{item_obj.name}" موجود بالفعل في الطلب'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        line = TransferRequestItem.objects.create(request=tr, **serializer.validated_data)
        from .serializers import TransferRequestItemSerializer
        return Response(
            TransferRequestItemSerializer(line).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['delete', 'patch'], url_path=r'items/(?P<item_id>[0-9]+)')
    def item_detail(self, request, pk=None, item_id=None):
        tr = self.get_object()

        if not tr.is_editable:
            return Response(
                {'detail': 'لا يمكن تعديل الأصناف في حالة الطلب الحالية'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            line = tr.items.get(pk=item_id)
        except TransferRequestItem.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        if request.method == 'DELETE':
            line.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)

        # PATCH — update qty/notes
        serializer = TransferRequestItemWriteSerializer(
            line, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        from .serializers import TransferRequestItemSerializer
        return Response(TransferRequestItemSerializer(line).data)

    # ── Chatter / Messages ────────────────────────────────────────────────────

    @action(detail=True, methods=['get', 'post'], url_path='messages')
    def messages(self, request, pk=None):
        tr = self.get_object()

        if request.method == 'GET':
            msgs = tr.messages.select_related('created_by__user').order_by('created_at')
            return Response(
                TransferRequestMessageSerializer(msgs, many=True).data
            )

        # POST
        profile = _profile(request)
        serializer = TransferRequestMessageCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        msg = TransferRequestMessage.objects.create(
            request=tr,
            created_by=profile,
            **serializer.validated_data,
        )

        return Response(
            TransferRequestMessageSerializer(msg).data,
            status=status.HTTP_201_CREATED,
        )

    # ── Stock lookup (for UI) ─────────────────────────────────────────────────

    @action(detail=False, methods=['get'], url_path='item_stock')
    def item_stock(self, request):
        """
        GET /api/transfers/item_stock/?item_id=123
        Returns stock at ALL branches for one item.
        """
        item_id = request.query_params.get('item_id')
        if not item_id:
            return Response({'detail': 'item_id مطلوب'}, status=status.HTTP_400_BAD_REQUEST)

        from apps.catalog.models import Item, ItemStock
        from apps.reservations.models import Reservation
        from django.db.models import Count, Q

        try:
            item = Item.objects.get(pk=item_id)
        except Item.DoesNotExist:
            return Response({'detail': 'الصنف غير موجود'}, status=status.HTTP_404_NOT_FOUND)

        stocks = ItemStock.objects.filter(item=item).select_related('branch')
        res_counts = (
            Reservation.objects
            .filter(item=item, status__in=['pending', 'available', 'contacted', 'confirmed'])
            .values('branch_id')
            .annotate(count=Count('id'))
        )
        res_map = {r['branch_id']: r['count'] for r in res_counts}

        return Response({
            'item': {
                'id': item.id,
                'name': item.name,
                'softech_id': item.softech_id,
                'name_scientific': item.name_scientific,
            },
            'stock_by_branch': [
                {
                    'branch_id':          s.branch.id,
                    'branch_name':        s.branch.name_ar or s.branch.name,
                    'quantity_on_hand':   float(s.quantity_on_hand),
                    'monthly_qty':        float(s.monthly_qty),
                    'active_reservations': res_map.get(s.branch_id, 0),
                }
                for s in stocks
            ],
        })
