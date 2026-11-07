"""
/api/counselling/ — Project 4 (doc 34).

status/            switches for the frontend (any signed-in staff)
content/…          the pharmacist review screen (`counselling` module; 503 while the content switch is off)
assistant/<id>/    staff drug assistant (POS view; 404 while the assistant switch is off)
cards/preview|send/ the WhatsApp counselling card (POS create to send)
"""
from django.conf import settings
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.sort_ordering import explicit_order_by

from . import services
from .models import CounsellingContent
from .permissions import CounsellingAccess, can
from .selectors import content_enabled
from .serializers import CounsellingContentSerializer, CounsellingVersionSerializer
from core.permissions import RouteModulePermission  # round 2, D6


def _profile(request):
    return getattr(request.user, 'staff_profile', None)


def _ser(request, obj, many=False):
    return CounsellingContentSerializer(obj, many=many,
                                        context={'show_drafts': can(_profile(request), 'edit')}).data


def _flag(name):
    return bool(getattr(settings, name, False))


class StatusView(APIView):
    permission_classes = [IsAuthenticated, RouteModulePermission]

    def get(self, request):
        from apps.pos_orders.permissions import CanViewPos
        from .permissions import PosCreate
        p = _profile(request)
        return Response({
            'assistant': _flag('DRUG_ASSISTANT_ENABLED'),
            'content': _flag('COUNSELLING_CONTENT_ENABLED'),
            'cards': _flag('COUNSEL_CARD_SEND_ENABLED'),
            # who may use the counter parts (same checks the endpoints make), so the UI shows no dead ends
            'can_assistant': CanViewPos().has_permission(request, self),
            'can_send': PosCreate().has_permission(request, self),
            'home_branch_id': getattr(p, 'branch_id', None),
        })


class _ContentGate:
    """Every content route answers 503 while COUNSELLING_CONTENT_ENABLED is off (commerce pattern)."""
    permission_classes = [IsAuthenticated, CounsellingAccess]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not content_enabled():
            from rest_framework.exceptions import APIException

            class Off(APIException):
                status_code = 503
                default_detail = 'الميزة غير مفعّلة'
            raise Off()


ORDERING = {'updated_at': 'updated_at', 'title': 'title', 'status': 'status', 'version': 'version',
            'approved_at': 'approved_at'}


class ContentListCreate(_ContentGate, generics.ListCreateAPIView):
    serializer_class = CounsellingContentSerializer
    counselling_action = 'create'

    def get_serializer_context(self):
        return {**super().get_serializer_context(), 'show_drafts': can(_profile(self.request), 'edit')}

    def get_queryset(self):
        qs = CounsellingContent.objects.select_related('approved_by', 'updated_by')
        st = self.request.query_params.get('status')
        if st:
            qs = qs.filter(status=st)
        q = (self.request.query_params.get('q') or '').strip()
        if q:
            qs = qs.filter(Q(title__icontains=q) | Q(links__item__name__icontains=q)
                           | Q(links__item__softech_id=q)).distinct()
        return qs.order_by(*explicit_order_by(self.request.query_params.get('ordering'), ORDERING,
                                              ('-updated_at', '-id')))

    def create(self, request, *args, **kwargs):
        c = services.create_sheet(_profile(request), request.data, request.data.get('item_ids') or [])
        return Response(_ser(request, c), status=status.HTTP_201_CREATED)


class ContentDetail(_ContentGate, APIView):
    counselling_action = 'edit'

    def get(self, request, pk):
        return Response(_ser(request, get_object_or_404(CounsellingContent, pk=pk)))

    def patch(self, request, pk):
        c = services.edit_sheet(_profile(request), get_object_or_404(CounsellingContent, pk=pk), request.data)
        return Response(_ser(request, c))


class _ContentAction(_ContentGate, APIView):
    def _content(self, pk):
        return get_object_or_404(CounsellingContent, pk=pk)


class ContentSubmit(_ContentAction):
    def post(self, request, pk):
        return Response(_ser(request, services.submit(_profile(request), self._content(pk))))


class ContentApprove(_ContentAction):
    counselling_action = 'approve'

    def post(self, request, pk):
        c = self._content(pk)
        services.approve(_profile(request), c)
        c.refresh_from_db()
        return Response(_ser(request, c))


class ContentRetire(_ContentAction):
    counselling_action = 'approve'

    def post(self, request, pk):
        c = services.retire(_profile(request), self._content(pk), request.data.get('reason', ''))
        return Response(_ser(request, c))


class ContentLink(_ContentAction):
    def post(self, request, pk):
        c = self._content(pk)
        services.link_items(_profile(request), c, request.data.get('item_ids') or [])
        return Response(_ser(request, c))


class ContentUnlink(_ContentAction):
    def post(self, request, pk):
        c = self._content(pk)
        raw = request.data.get('item_id')
        if not str(raw or '').isdigit():          # was int(None) → 500 (round 2 R3 seeded sweep)
            return Response({'detail': 'item_id مطلوب'}, status=status.HTTP_400_BAD_REQUEST)
        services.unlink_item(_profile(request), c, int(raw))
        return Response(_ser(request, c))


class ContentSuggestItems(_ContentAction):
    # Reads follow `counselling → view` like every other sheet read (round 2 R3, owner default §8 Q5:
    # the matrix wins). Linking a suggested item is still ContentLink (edit).

    def get(self, request, pk):
        return Response({'results': services.suggest_items(self._content(pk))})


class ContentVersions(_ContentAction):
    def get(self, request, pk):
        c = self._content(pk)
        return Response({'results': CounsellingVersionSerializer(c.versions.select_related('approved_by'),
                                                                 many=True).data})


class NeedsContent(_ContentGate, APIView):
    # The screen's FIRST tab: view-only roles opened /counselling straight onto a 403 (round 2 R3,
    # owner default §8 Q5 — the matrix wins). Read-only list of sold items with no sheet.

    def get(self, request):
        return Response({'results': services.needs_content_queue()})


class ContentAiDraft(_ContentGate, APIView):
    """POST {item_id} → a new DRAFT sheet pre-filled by AI for a pharmacist to review."""
    counselling_action = 'edit'

    def post(self, request):
        from apps.catalog.models import Item
        from .ai_draft import draft_for_item
        raw = request.data.get('item_id')
        if not str(raw or '').isdigit():
            return Response({'detail': 'item_id مطلوب'}, status=status.HTTP_400_BAD_REQUEST)
        c = draft_for_item(_profile(request), get_object_or_404(Item, pk=int(raw)))
        return Response(_ser(request, c), status=status.HTTP_201_CREATED)


class AssistantView(APIView):
    """GET assistant/<item_id>/?branch=<id> — POS view; 404 while DRUG_ASSISTANT_ENABLED is off."""

    def get_permissions(self):
        from apps.pos_orders.permissions import CanViewPos
        return [IsAuthenticated(), CanViewPos()]

    def get(self, request, item_id):
        from django.http import Http404
        from apps.catalog.models import Item
        from core import branch_scope
        from .assistant import assistant_payload
        if not _flag('DRUG_ASSISTANT_ENABLED'):
            raise Http404
        raw = request.query_params.get('branch')
        branch_id = int(raw) if str(raw or '').isdigit() else None
        if branch_id is not None and not branch_scope.allows(request.user, branch_id):
            return Response({'detail': 'لا تملك صلاحية هذا الفرع'}, status=status.HTTP_403_FORBIDDEN)
        item = get_object_or_404(Item, pk=item_id)
        return Response(assistant_payload(item, branch_id=branch_id, profile=_profile(request)))


class _CardBase(APIView):
    """Counter (POS) action: GET = pos view, POST = pos create (the RBAC middleware maps cards/ to pos)."""

    def get_permissions(self):
        from apps.pos_orders.permissions import CanViewPos
        from .permissions import PosCreate
        if self.request.method in ('GET', 'HEAD', 'OPTIONS'):
            return [IsAuthenticated(), CanViewPos()]
        return [IsAuthenticated(), PosCreate()]

    def _customer(self, request):
        from apps.customers.models import Customer
        raw = request.data.get('customer_id') if request.method == 'POST' else request.query_params.get('customer')
        return get_object_or_404(Customer, pk=int(raw)) if str(raw or '').isdigit() else None


class CardPreview(_CardBase):
    def post(self, request):
        from .cards import plan_card
        return Response(plan_card(customer=self._customer(request), phone=request.data.get('phone', ''),
                                  item_ids=request.data.get('item_ids') or [],
                                  phone_index=request.data.get('phone_index')))


class CardSend(_CardBase):
    def post(self, request):
        from apps.branches.models import Branch
        from core import branch_scope
        from .cards import send_card
        raw = request.data.get('branch_id')
        branch = get_object_or_404(Branch, pk=int(raw)) if str(raw or '').isdigit() else None
        if branch is None or not branch_scope.allows(request.user, branch.pk):
            return Response({'detail': 'اختر فرعاً من فروعك'}, status=status.HTTP_400_BAD_REQUEST)
        send = send_card(customer=self._customer(request), phone=request.data.get('phone', ''),
                         item_ids=request.data.get('item_ids') or [], actor=_profile(request), branch=branch,
                         source=request.data.get('source', 'pos'),
                         idempotency_key=request.data.get('idempotency_key', ''),
                         resend=bool(request.data.get('resend')),
                         phone_index=request.data.get('phone_index'))
        return Response({'id': send.pk, 'status': send.status, 'status_label': send.get_status_display(),
                         'fail_reason': send.fail_reason, 'phone': send.phone_masked,
                         'items': send.lines.count()},
                        status=status.HTTP_201_CREATED)
