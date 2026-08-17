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
    ApproveWithQuantitiesSerializer,
    CompleteWithReceiptSerializer,
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


def _notify(transfer_request, title, body, notif_type, *, branch=None, include_admins=True):
    """
    Fire in-app notification — non-fatal wrapper.

    branch: Branch instance to notify (defaults to supplying_branch).
            Pass requesting_branch for response notifications (approve/reject/revision).
    include_admins: also notifies admin/purchasing roles via send_to_branch's include_admins flag.

    Uses Notification.send_to_branch() so WS push, dedup, and NotificationLog all work.
    """
    try:
        from apps.notifications.models import Notification
        target_branch = branch or transfer_request.supplying_branch
        if target_branch:
            Notification.send_to_branch(
                branch=target_branch,
                notification_type=notif_type,
                title=title,
                body=body or '',
                transfer_id=transfer_request.id,
                dedup_key=f'{notif_type}_{transfer_request.id}',
                include_admins=include_admins,
            )
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

        # Date range filters — wrap in try/except so malformed input returns
        # an empty queryset rather than a 500 from the DB driver
        date_from = self.request.query_params.get('date_from')
        date_to   = self.request.query_params.get('date_to')
        try:
            if date_from:
                qs = qs.filter(created_at__date__gte=date_from)
            if date_to:
                qs = qs.filter(created_at__date__lte=date_to)
        except Exception:
            pass  # silently ignore invalid date strings

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

        serializer = ApproveWithQuantitiesSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        items_data = {
            i['item_id']: i['approved_quantity']
            for i in serializer.validated_data.get('items', [])
        }

        tr.status = 'approved'
        tr.reviewed_by = profile
        tr.reviewed_at = timezone.now()
        tr.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'updated_at'])

        # Persist per-item approved quantities when supplied
        if items_data:
            for line in tr.items.all():
                if line.item_id in items_data:
                    line.approved_quantity = items_data[line.item_id]
                    line.save(update_fields=['approved_quantity'])

        _system_log(tr, f'تم اعتماد الطلب بواسطة {profile.full_name}')
        _notify(
            tr,
            f'تم اعتماد طلبك — {tr.request_number}',
            f'تمت الموافقة على طلب التحويل. يمكنك الآن إرساله للـ ERP.',
            'transfer_response',
            branch=tr.requesting_branch,  # notify the requesting branch, not the supplying one
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
            branch=tr.requesting_branch,  # notify the requesting branch, not the supplying one
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
        _notify(
            tr,
            f'يحتاج طلبك تعديلاً — {tr.request_number}',
            tr.revision_notes,
            'transfer_response',
            branch=tr.requesting_branch,  # notify the requesting branch to make changes
        )

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

        erp_ref = serializer.validated_data.get('erp_reference', '').strip()

        tr.status = 'sent_to_erp'
        tr.sent_to_erp_at = timezone.now()
        tr.sent_to_erp_by = profile
        tr.erp_reference = erp_ref

        update_fields = ['status', 'sent_to_erp_at', 'sent_to_erp_by', 'erp_reference', 'updated_at']

        # If a doc number was provided, queue ERP match verification immediately
        if erp_ref:
            tr.erp_match_status   = 'pending'
            tr.erp_check_attempts = 0
            update_fields += ['erp_match_status', 'erp_check_attempts']

        tr.save(update_fields=update_fields)

        ref_label = f' (مرجع: {erp_ref})' if erp_ref else ''
        _system_log(
            tr,
            f'تم الإرسال للـ ERP بواسطة {profile.full_name}{ref_label}'
        )
        if erp_ref:
            _system_log(tr, f'🔍 جارٍ التحقق من المستند {erp_ref} في SOFTECH — قد يستغرق ذلك عدة ساعات حتى يتم استلام البيانات من الفرع المصدر.')

        return Response(
            TransferRequestDetailSerializer(tr, context={'request': request}).data
        )

    # ── Check ERP Match (manual trigger) ─────────────────────────────────────

    @action(detail=True, methods=['post'], url_path='check-erp-match')
    def check_erp_match(self, request, pk=None):
        """
        POST /{id}/check-erp-match/
        Admin / purchasing only — manually trigger ERP match verification.
        Runs ERPMatcher, persists result, logs to chatter, returns updated serializer.
        """
        tr = self.get_object()
        profile = _profile(request)

        if not profile or profile.role not in ('admin', 'purchasing'):
            return Response(
                {'detail': 'هذا الإجراء مخصص للمشرفين ومسؤولي المشتريات فقط'},
                status=status.HTTP_403_FORBIDDEN,
            )

        if tr.status not in ('sent_to_erp', 'completed'):
            return Response(
                {'detail': 'يمكن التحقق من المطابقة فقط للطلبات المُرسَلة إلى ERP'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Rate limit: max one check per 20 seconds to protect the Sybase connection
        if tr.erp_last_checked:
            elapsed = (timezone.now() - tr.erp_last_checked).total_seconds()
            if elapsed < 20:
                remaining = int(20 - elapsed) + 1
                return Response(
                    {'detail': f'يرجى الانتظار {remaining} ثانية قبل إعادة الفحص.'},
                    status=status.HTTP_429_TOO_MANY_REQUESTS,
                )

        from .erp_matcher import ERPMatcher, apply_match_result, ERP_MATCH_UPDATE_FIELDS

        result = ERPMatcher(tr).run()
        apply_match_result(tr, result)

        # If auto-search discovered the docnumber, persist it to erp_reference
        update_fields = list(ERP_MATCH_UPDATE_FIELDS)
        if result.get('discovered_doc') and not tr.erp_reference:
            tr.erp_reference = result['discovered_doc']
            if 'erp_reference' not in update_fields:
                update_fields.append('erp_reference')

        tr.save(update_fields=update_fields)

        # Log result to chatter
        _system_log(tr, result['detail'])

        # Notify both branches if matched
        if result['status'] in ('matched', 'partial'):
            _notify(
                tr,
                f'تم التحقق من مستند ERP — {tr.request_number}',
                result['detail'],
                'transfer_response',
                branch=tr.requesting_branch,
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

        serializer = CompleteWithReceiptSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        items_data = {
            i['item_id']: i['received_quantity']
            for i in serializer.validated_data.get('items', [])
        }

        tr.status = 'completed'
        tr.completed_at = timezone.now()
        tr.save(update_fields=['status', 'completed_at', 'updated_at'])

        # Persist per-item received quantities when supplied
        if items_data:
            for line in tr.items.all():
                if line.item_id in items_data:
                    line.received_quantity = items_data[line.item_id]
                    line.save(update_fields=['received_quantity'])

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

        # Notify the OTHER side that a message arrived
        # (system log entries never trigger notifications)
        if msg.message_type != 'system' and profile:
            snippet = (msg.message or '📎 مرفق')[:60]
            sender_name = profile.full_name
            if profile.branch_id == tr.requesting_branch_id:
                # Sender is requesting branch → notify supplying branch
                _notify(
                    tr,
                    f'رسالة جديدة — {tr.request_number}',
                    f'{sender_name}: {snippet}',
                    'transfer_request',
                    branch=tr.supplying_branch,
                )
            elif profile.branch_id == tr.supplying_branch_id:
                # Sender is supplying branch → notify requesting branch
                _notify(
                    tr,
                    f'رسالة جديدة — {tr.request_number}',
                    f'{sender_name}: {snippet}',
                    'transfer_response',
                    branch=tr.requesting_branch,
                )
            # HQ/admin senders → no cross-branch notification to avoid noise

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

        # Only log the print event when the caller explicitly opts in (prevents
        # chatter spam from automatic print previews / pre-renders)
        if request.query_params.get('log') == '1':
            _system_log(tr, f'تم طباعة الطلب بواسطة {profile.full_name if profile else "النظام"}')

        items_data = [
            {
                'item_code':         line.item.softech_id,
                'item_name':         line.item.name,
                'item_scientific':   line.item.name_scientific,
                'quantity':          float(line.quantity),
                'approved_quantity': float(line.approved_quantity) if line.approved_quantity is not None else None,
                'received_quantity': float(line.received_quantity) if line.received_quantity is not None else None,
                'notes':             line.notes,
            }
            for line in tr.items.select_related('item').all()
        ]

        # QR code — encodes the transfer number for scanning on receipt
        qr_b64 = None
        try:
            import base64, io, qrcode
            qr = qrcode.QRCode(version=1, box_size=4, border=2,
                               error_correction=qrcode.constants.ERROR_CORRECT_L)
            qr.add_data(tr.request_number)
            qr.make(fit=True)
            img = qr.make_image(fill_color='black', back_color='white')
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            qr_b64 = base64.b64encode(buf.getvalue()).decode()
        except Exception:
            pass  # qrcode not installed or error — omit QR silently

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
            'qr_code_base64':        qr_b64,
        }
        return Response(receipt)

    # ── Transfer Analytics ────────────────────────────────────────────────────

    @action(detail=False, methods=['get'])
    def analytics(self, request):
        """
        GET /api/transfers/analytics/?days=30
        KPIs + top items + branch flow + rejection-by-branch.
        """
        from django.db.models import Count, Q, Sum
        from datetime import timedelta

        profile = _profile(request)
        if not profile:
            return Response({'detail': 'مطلوب تسجيل الدخول'}, status=status.HTTP_401_UNAUTHORIZED)

        days = max(1, min(int(request.query_params.get('days', 30)), 365))
        since = timezone.now() - timedelta(days=days)

        qs = TransferRequest.objects.filter(created_at__gte=since)

        # Branch-scope the same way the list view does
        if profile.role not in ('admin', 'purchasing', 'call_center'):
            if profile.branch_id:
                qs = qs.filter(
                    Q(requesting_branch_id=profile.branch_id) |
                    Q(supplying_branch_id=profile.branch_id)
                )
            else:
                qs = qs.none()

        total     = qs.count()
        completed = qs.filter(status='completed').count()
        rejected  = qs.filter(status='rejected').count()
        pending   = qs.filter(status='pending').count()

        # Average cycle time: submitted → completed (in hours)
        avg_cycle = None
        completed_timed = qs.filter(
            status='completed',
            submitted_at__isnull=False,
            completed_at__isnull=False,
        ).values_list('submitted_at', 'completed_at')
        if completed_timed:
            durations = [
                (c - s).total_seconds() / 3600
                for s, c in completed_timed
                if s and c
            ]
            avg_cycle = round(sum(durations) / len(durations), 1) if durations else None

        # Average response time: submitted → reviewed (in hours)
        avg_response = None
        reviewed_timed = qs.filter(
            submitted_at__isnull=False,
            reviewed_at__isnull=False,
        ).values_list('submitted_at', 'reviewed_at')
        if reviewed_timed:
            durations = [
                (r - s).total_seconds() / 3600
                for s, r in reviewed_timed
                if s and r
            ]
            avg_response = round(sum(durations) / len(durations), 1) if durations else None

        # Top transferred items
        top_items = list(
            TransferRequestItem.objects
            .filter(request__in=qs)
            .values('item__name', 'item__softech_id')
            .annotate(request_count=Count('id'), total_qty=Sum('quantity'))
            .order_by('-request_count')[:20]
        )

        # Branch-to-branch flow
        branch_flow = list(
            qs.filter(supplying_branch__isnull=False)
            .values('requesting_branch__name_ar', 'supplying_branch__name_ar')
            .annotate(count=Count('id'))
            .order_by('-count')[:10]
        )

        # Rejection rate by supplying branch
        rejection_by_branch = list(
            qs.filter(supplying_branch__isnull=False)
            .values('supplying_branch__name_ar')
            .annotate(
                total=Count('id'),
                rejected=Count('id', filter=Q(status='rejected')),
            )
            .order_by('-total')[:10]
        )

        return Response({
            'period_days': days,
            'kpis': {
                'total':               total,
                'completed':           completed,
                'rejected':            rejected,
                'pending':             pending,
                'completion_rate':     round(completed / total * 100, 1) if total else 0,
                'rejection_rate':      round(rejected  / total * 100, 1) if total else 0,
                'avg_cycle_hours':     avg_cycle,
                'avg_response_hours':  avg_response,
            },
            'top_items':           top_items,
            'branch_flow':         branch_flow,
            'rejection_by_branch': rejection_by_branch,
        })

    # ── Discrepancy Report ────────────────────────────────────────────────────

    @action(detail=False, methods=['get'], url_path='discrepancy-report')
    def discrepancy_report(self, request):
        """
        GET /api/transfers/discrepancy-report/
        Returns completed transfers where received_quantity differs from approved_quantity.
        Requires admin or purchasing role.
        """
        from django.db.models import F

        profile = _profile(request)
        if not profile or profile.role not in ('admin', 'purchasing'):
            return Response(
                {'detail': 'هذا التقرير مخصص للمشرفين ومسؤولي المشتريات فقط'},
                status=status.HTTP_403_FORBIDDEN,
            )

        lines = (
            TransferRequestItem.objects
            .filter(
                request__status='completed',
                approved_quantity__isnull=False,
                received_quantity__isnull=False,
            )
            .exclude(approved_quantity=F('received_quantity'))
            .select_related(
                'request__requesting_branch',
                'request__supplying_branch',
                'item',
            )
            .order_by('-request__completed_at')[:200]
        )

        data = []
        for line in lines:
            approved = float(line.approved_quantity)
            received = float(line.received_quantity)
            delta    = approved - received
            pct      = round(delta / approved * 100, 1) if approved else 0
            data.append({
                'request_number':    line.request.request_number,
                'request_id':        line.request_id,
                'completed_at':      line.request.completed_at.isoformat() if line.request.completed_at else None,
                'requesting_branch': (line.request.requesting_branch.name_ar or line.request.requesting_branch.name)
                                     if line.request.requesting_branch_id else '—',
                'supplying_branch':  (line.request.supplying_branch.name_ar or line.request.supplying_branch.name)
                                     if line.request.supplying_branch_id else '—',
                'item_name':         line.item.name,
                'item_code':         line.item.softech_id,
                'approved_quantity': approved,
                'received_quantity': received,
                'discrepancy':       round(delta, 3),
                'discrepancy_pct':   pct,
                'short':             delta > 0,
            })

        return Response({'discrepancies': data, 'total': len(data)})

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
            item_code = f' [{line.item.softech_id}]' if line.item.softech_id else ''
            lines.append(f'• {line.item.name}{item_code} × {line.quantity}' +
                         (f' ({line.notes})' if line.notes else ''))
        if tr.notes:
            lines += ['', f'ملاحظات: {tr.notes}']
        if tr.erp_reference:
            lines += [f'مرجع ERP: {tr.erp_reference}']
        lines += ['', f'التاريخ: {created_str}']

        message_text = '\n'.join(lines)

        _system_log(tr, f'تم مشاركة الطلب عبر واتساب بواسطة {profile.full_name if profile else "النظام"}')

        return Response({'message_text': message_text})
