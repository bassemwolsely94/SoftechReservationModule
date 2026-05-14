"""
apps/transfers/views.py

Transfer Request ViewSet — full state machine + item management + chatter.
NO stock mutations. NO ERP calls. Communication + approval only.
"""
from django.utils import timezone
from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
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


def _is_hq(profile):
    """HQ-wide oversight roles."""
    return profile and profile.role in ('admin', 'purchasing', 'call_center')

def _can_supply_side(profile, tr):
    """Supplying branch staff + admin/purchasing can approve/reject/send-to-ERP."""
    if not profile:
        return False
    if profile.role in ('admin', 'purchasing'):
        return True
    return bool(profile.branch_id and profile.branch_id == tr.supplying_branch_id)

def _can_request_side(profile, tr):
    """Requesting branch staff + HQ can submit/edit/complete/cancel."""
    if not profile:
        return False
    if _is_hq(profile):
        return True
    return bool(profile.branch_id and profile.branch_id == tr.requesting_branch_id)


def _system_log(request_obj, message):
    TransferRequestMessage.log_system(request_obj, message)


def _notify(transfer_request, title, body, notif_type):
    """Fire in-app notification — non-fatal wrapper."""
    try:
        from apps.users.models import StaffProfile
        from apps.notifications.models import Notification

        # Notify destination branch staff + admins
        recipients = StaffProfile.objects.filter(
            branch=transfer_request.supplying_branch,
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
    filterset_fields    = ['status', 'requesting_branch', 'supplying_branch']
    search_fields       = [
        'request_number', 'notes',
        'items__item__name', 'items__item__softech_id',
    ]
    ordering_fields     = ['created_at', 'updated_at', 'status']
    ordering            = ['-created_at']

    def get_queryset(self):
        qs = TransferRequest.objects.select_related(
            'requesting_branch', 'supplying_branch',
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
            pass
        elif profile.branch:
            # Branch staff see requests where they are source OR destination
            qs = qs.filter(requesting_branch=profile.branch) | qs.filter(supplying_branch=profile.branch)
        else:
            return qs.none()

        # Date range filters
        date_from = self.request.query_params.get('date_from')
        date_to   = self.request.query_params.get('date_to')
        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)
        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)

        return qs

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

        if not _can_request_side(profile, tr):
            return Response(
                {'detail': 'فقط موظفو الفرع الطالب أو المشرفون يمكنهم تقديم الطلب'},
                status=status.HTTP_403_FORBIDDEN,
            )

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
            f'فرع {tr.requesting_branch} يطلب تحويل {tr.items.count()} صنف. يرجى المراجعة.',
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

        if not _can_supply_side(profile, tr):
            return Response(
                {'detail': 'فقط موظفو الفرع المصدر أو المشرفون يمكنهم اعتماد الطلب'},
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

        if not _can_supply_side(profile, tr):
            return Response(
                {'detail': 'فقط موظفو الفرع المصدر أو المشرفون يمكنهم رفض الطلب'},
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

        if not _can_supply_side(profile, tr):
            return Response(
                {'detail': 'فقط موظفو الفرع المصدر أو المشرفون يمكنهم طلب التعديل'},
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

        if not _can_supply_side(profile, tr):
            return Response(
                {'detail': 'فقط موظفو الفرع المصدر أو المشرفون يمكنهم الإرسال للـ ERP'},
                status=status.HTTP_403_FORBIDDEN,
            )

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

    # ── Dispatch (delivery tracking) ──────────────────────────────────────────

    @action(detail=True, methods=['post'], url_path='record-dispatch', url_name='record_dispatch')
    def record_dispatch(self, request, pk=None):
        """POST /{id}/record-dispatch/ — record dispatch with delivery person."""
        tr = self.get_object()
        profile = _profile(request)

        if not tr.can_dispatch:
            return Response(
                {'detail': 'لا يمكن تسجيل الإرسال في الحالة الحالية أو تم الإرسال مسبقاً'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        delivery_person = request.data.get('delivery_person_name', '').strip()
        if not delivery_person:
            return Response(
                {'detail': 'اسم مندوب التوصيل مطلوب'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        tr.delivery_person_name = delivery_person
        tr.dispatched_at = timezone.now()
        tr.dispatched_by = profile
        tr.save(update_fields=['delivery_person_name', 'dispatched_at', 'dispatched_by', 'updated_at'])

        _system_log(
            tr,
            f'تم الإرسال بواسطة {profile.full_name} — المندوب: {delivery_person}'
        )

        return Response(
            TransferRequestDetailSerializer(tr, context={'request': request}).data
        )

    # ── Complete ──────────────────────────────────────────────────────────────

    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        tr = self.get_object()
        profile = _profile(request)

        if not _can_request_side(profile, tr):
            return Response(
                {'detail': 'فقط موظفو الفرع الطالب أو المشرفون يمكنهم تأكيد الاستلام وإغلاق الطلب'},
                status=status.HTTP_403_FORBIDDEN,
            )

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

        if not _can_request_side(profile, tr):
            return Response(
                {'detail': 'فقط موظفو الفرع الطالب أو المشرفون يمكنهم إلغاء الطلب'},
                status=status.HTTP_403_FORBIDDEN,
            )

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

    # ── Chatter / Messages (text / image / voice) ─────────────────────────────

    @action(
        detail=True, methods=['get', 'post'], url_path='messages',
        parser_classes=[MultiPartParser, FormParser, JSONParser],
    )
    def messages(self, request, pk=None):
        tr = self.get_object()

        if request.method == 'GET':
            msgs = tr.messages.select_related('created_by__user').order_by('created_at')
            return Response(
                TransferRequestMessageSerializer(msgs, many=True, context={'request': request}).data
            )

        # POST — text, image, or voice note
        profile = _profile(request)
        serializer = TransferRequestMessageCreateSerializer(
            data=request.data, context={'request': request}
        )
        serializer.is_valid(raise_exception=True)

        msg = TransferRequestMessage.objects.create(
            request=tr,
            created_by=profile,
            **serializer.validated_data,
        )

        return Response(
            TransferRequestMessageSerializer(msg, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
        )

    # ── Chatter: delete a message (soft-delete) ──────────────────────────────

    @action(
        detail=True, methods=['delete'],
        url_path=r'messages/(?P<message_id>[0-9]+)',
        url_name='delete_message',
    )
    def delete_message(self, request, pk=None, message_id=None):
        """
        DELETE /api/transfers/{id}/messages/{message_id}/

        Soft-deletes a message. Only the author or an admin may delete.
        System messages (status logs) cannot be deleted.
        """
        tr = self.get_object()
        profile = _profile(request)

        try:
            msg = tr.messages.get(pk=message_id)
        except TransferRequestMessage.DoesNotExist:
            return Response({'detail': 'الرسالة غير موجودة'}, status=status.HTTP_404_NOT_FOUND)

        if msg.is_deleted:
            return Response({'detail': 'هذه الرسالة محذوفة مسبقاً'}, status=status.HTTP_400_BAD_REQUEST)

        if msg.message_type == 'system':
            return Response({'detail': 'لا يمكن حذف رسائل النظام'}, status=status.HTTP_403_FORBIDDEN)

        is_author = (msg.created_by_id and profile and msg.created_by_id == profile.id)
        is_admin  = (profile and profile.role == 'admin')
        if not is_author and not is_admin:
            return Response(
                {'detail': 'لا يمكنك حذف رسائل الآخرين'},
                status=status.HTTP_403_FORBIDDEN,
            )

        msg.is_deleted = True
        msg.deleted_at  = timezone.now()
        msg.deleted_by  = profile
        msg.save(update_fields=['is_deleted', 'deleted_at', 'deleted_by'])

        return Response(
            TransferRequestMessageSerializer(msg, context={'request': request}).data
        )

    # ── SOFTECH stktrans reference validation ─────────────────────────────────

    @action(detail=True, methods=['post'], url_path='validate-erp-ref')
    def validate_erp_ref(self, request, pk=None):
        """
        POST /{id}/validate-erp-ref/
        Body: {"doc_number": "...", "branch_code": "..."}
        Looks up the doc_number in SOFTECH stktransm to confirm it exists.
        Returns the transaction details if found, 404 if not.
        """
        doc_number = (request.data.get('doc_number') or '').strip()
        branch_code = (request.data.get('branch_code') or '').strip()

        if not doc_number or not branch_code:
            return Response(
                {'detail': 'doc_number و branch_code مطلوبان'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            from config.sybase import get_sybase_connection
            from apps.sync.sybase_queries import QUERY_VALIDATE_STKTRANS
            conn = get_sybase_connection()
            cursor = conn.cursor()
            cursor.execute(QUERY_VALIDATE_STKTRANS, [doc_number, branch_code])
            row = cursor.fetchone()
            conn.close()
        except Exception as e:
            return Response(
                {'detail': f'خطأ في الاتصال بـ SOFTECH: {str(e)}'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        if not row:
            return Response(
                {'valid': False, 'detail': 'رقم المستند غير موجود في النظام لهذا الفرع'},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response({
            'valid': True,
            'doc_number': row[0],
            'doc_code': row[1],
            'branch_code': row[2],
            'doc_date': str(row[3]) if row[3] else None,
            'doc_value': float(row[4]) if row[4] else None,
            'user_code': row[5],
        })

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

    # ── Print Receipt ─────────────────────────────────────────────────────────

    @action(detail=True, methods=['get'], url_path='print')
    def print_receipt(self, request, pk=None):
        """
        GET /api/transfers/{id}/print/

        Returns a clean data payload for printable receipt rendering.
        Logs the print action to the chatter.
        """
        tr      = self.get_object()
        profile = _profile(request)

        # Audit log
        _system_log(tr, f'تم طباعة الطلب بواسطة {profile.full_name if profile else "النظام"}')

        items_data = [
            {
                'item_code':    line.item.softech_id,
                'item_name':    line.item.name,
                'item_scientific': line.item.name_scientific,
                'quantity':     float(line.quantity),
                'notes':        line.notes,
            }
            for line in tr.items.select_related('item').all()
        ]

        receipt = {
            'doc_type':              'transfer',
            'request_number':        tr.request_number,
            'status':                tr.status,
            'status_label':          tr.status_label_ar,
            'requesting_branch':     (tr.requesting_branch.name_ar or tr.requesting_branch.name)
                                      if tr.requesting_branch_id else '—',
            'supplying_branch':      (tr.supplying_branch.name_ar or tr.supplying_branch.name)
                                      if tr.supplying_branch_id else '—',
            'created_by':            tr.created_by.full_name if tr.created_by_id else '—',
            'reviewed_by':           tr.reviewed_by.full_name if tr.reviewed_by_id else None,
            'erp_reference':         tr.erp_reference or None,
            'delivery_person_name':  tr.delivery_person_name or None,
            'notes':                 tr.notes,
            'rejection_reason':      tr.rejection_reason or None,
            'created_at':            tr.created_at.isoformat(),
            'submitted_at':          tr.submitted_at.isoformat() if tr.submitted_at else None,
            'reviewed_at':           tr.reviewed_at.isoformat() if tr.reviewed_at else None,
            'sent_to_erp_at':        tr.sent_to_erp_at.isoformat() if tr.sent_to_erp_at else None,
            'dispatched_at':         tr.dispatched_at.isoformat() if tr.dispatched_at else None,
            'completed_at':          tr.completed_at.isoformat() if tr.completed_at else None,
            'items':                 items_data,
            'total_items':           len(items_data),
            'printed_by':            profile.full_name if profile else '—',
            'printed_at':            timezone.now().isoformat(),
        }
        return Response(receipt)

    # ── WhatsApp Share ─────────────────────────────────────────────────────────

    @action(detail=True, methods=['post'], url_path='share-whatsapp')
    def share_whatsapp(self, request, pk=None):
        """
        POST /api/transfers/{id}/share-whatsapp/

        Generates a WhatsApp-ready message and logs the share event.
        """
        tr      = self.get_object()
        profile = _profile(request)

        req_branch  = (tr.requesting_branch.name_ar or tr.requesting_branch.name) if tr.requesting_branch_id else '—'
        sup_branch  = (tr.supplying_branch.name_ar  or tr.supplying_branch.name)  if tr.supplying_branch_id  else '—'
        created_str = tr.created_at.strftime('%Y-%m-%d %H:%M')

        lines = [
            '🔀 *طلب تحويل مخزون — صيدليات الرزيقي*',
            f'رقم الطلب: {tr.request_number}',
            f'الحالة: {tr.status_label_ar}',
            f'من فرع: {req_branch}',
            f'إلى فرع: {sup_branch}',
            '',
            '*الأصناف:*',
        ]
        for line in tr.items.select_related('item').all():
            lines.append(f'• {line.item.name} × {line.quantity}' +
                         (f' ({line.notes})' if line.notes else ''))
        if tr.notes:
            lines += ['', f'ملاحظات: {tr.notes}']
        if tr.erp_reference:
            lines += [f'مرجع ERP: {tr.erp_reference}']
        lines += ['', f'التاريخ: {created_str}']

        message_text = '\n'.join(lines)

        _system_log(tr, f'تم مشاركة الطلب عبر واتساب بواسطة {profile.full_name if profile else "النظام"}')

        return Response({'message_text': message_text})
