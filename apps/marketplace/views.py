"""
apps/marketplace/views.py — /api/marketplace/ (doc 38). MARKETPLACE_ENABLED off → every staff route 404.

  GET|POST  channels/                 list (view) · create (edit); `credentials` write-only
  GET|PATCH channels/<id>/            read (view) · edit (edit)
  POST      channels/<id>/push-stock/ push the availability snapshot (edit); dry-run while the push switch is off
  GET|POST  stores/                   branch-scoped list (view) · create (edit)
  PATCH     stores/<id>/              edit (edit)
  GET|POST  listings/                 ?channel=&q=&approved=&branch= with problem + qty · create unapproved (create)
  POST      listings/<id>/approve/ | unapprove/   (approve; audited)
  GET       orders/                   ?status=&channel=&branch= (branch-scoped, phone masked)
  GET       orders/<id>/              lines, problems, events, linked POS draft
  POST      orders/manual/            manual intake through the manual adapter (create)
  POST      orders/<id>/accept/ | reject/ {reason} | status/ {to_status, note}   (create)
  POST      settlements/              multipart: channel, file (.csv/.xlsx), column_map (JSON), period_from/to (edit)
  GET       settlements/ · settlements/<id>/?status=   (view)
  GET       push-log/                 ?channel= (view)
  POST      webhooks/<channel_code>/  platform entry: no staff session; own gate (flag + active channel +
                                      adapter signature). Exempt from the RBAC middleware (module_access).

Business rules live in intake / push / availability; these views only gate, scope and serialize.
Nothing here writes to SOFTECH.
"""
import logging
from decimal import Decimal, InvalidOperation

from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.exceptions import ParseError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.models import AuditLog
from apps.branches.models import Branch
from core import branch_scope
from core.permissions import matrix_permission
from core.sort_ordering import explicit_order_by

from . import intake, push, settlement
from .access import enabled
from .adapters import REGISTRY, get_adapter
from .models import SettlementBatch, ChannelListing, ChannelStore, ExternalOrder, MarketplaceChannel, PushLog
from .serializers import (ChannelSerializer, ListingSerializer, OrderDetailSerializer, OrderListSerializer,
                          PushLogSerializer, SettlementBatchSerializer, SettlementLineSerializer,
                          StoreSerializer)

logger = logging.getLogger('elrezeiky.marketplace')

M = 'marketplace'
EDIT_WRITES = matrix_permission(M, post=('edit',))          # GET view · POST/PATCH edit
VIEW_CREATE = matrix_permission(M)                           # GET view · POST create
APPROVE = matrix_permission(M, post=('approve',))


def _profile(request):
    return getattr(request.user, 'staff_profile', None)


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class _Gate:
    """Flag off → 404 for a signed-in caller (the module does not exist); anonymous still gets 401."""

    def initial(self, request, *args, **kwargs):
        if request.user and request.user.is_authenticated and not enabled():
            raise Http404
        super().initial(request, *args, **kwargs)


# ── channels ─────────────────────────────────────────────────────────────────────────────────────

CHANNEL_ORDERING = {'name': 'name', 'code': 'code', 'adapter': 'adapter', 'is_active': 'is_active'}


class ChannelListCreate(_Gate, generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated, EDIT_WRITES]
    serializer_class = ChannelSerializer

    def get_queryset(self):
        return MarketplaceChannel.objects.all().order_by(
            *explicit_order_by(self.request.query_params.get('ordering'), CHANNEL_ORDERING, ('name', 'id')))

    def perform_create(self, serializer):
        ch = serializer.save()
        AuditLog.log('marketplace_channel_created', user=_profile(self.request), obj=ch, request=self.request,
                     new_data=_channel_audit(ch))


def _channel_audit(ch):
    """Audit shape of a channel — never the credentials themselves, only whether they are set."""
    return {'code': ch.code, 'name': ch.name, 'adapter': ch.adapter, 'scope': ch.scope,
            'softech_personcode': ch.softech_personcode, 'price_rule': ch.price_rule, 'price_pct': str(ch.price_pct),
            'stock_buffer': str(ch.stock_buffer), 'max_qty_per_item': ch.max_qty_per_item,
            'is_active': ch.is_active, 'has_credentials': bool(ch.credentials)}


class ChannelDetail(_Gate, generics.RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated, EDIT_WRITES]
    serializer_class = ChannelSerializer
    queryset = MarketplaceChannel.objects.all()
    http_method_names = ['get', 'patch', 'head', 'options']

    def perform_update(self, serializer):
        before = _channel_audit(serializer.instance)
        ch = serializer.save()
        AuditLog.log('marketplace_channel_updated', user=_profile(self.request), obj=ch, request=self.request,
                     old_data=before, new_data=_channel_audit(ch),
                     extra={'credentials_changed': 'credentials' in serializer.validated_data})


class ChannelPushStock(_Gate, APIView):
    permission_classes = [IsAuthenticated, EDIT_WRITES]

    def post(self, request, pk):
        channel = get_object_or_404(MarketplaceChannel, pk=pk)
        profile = _profile(request)
        if branch_scope.branch_ids(request.user) is None:
            logs = push.push_stock(channel, user=profile)
        else:   # a branch-bound editor pushes only their own branches' stores
            stores = branch_scope.scope(ChannelStore.objects.filter(channel=channel, is_active=True)
                                        .select_related('branch'), request.user)
            logs = [log for s in stores for log in push.push_stock(channel, s, user=profile)]
        return Response(PushLogSerializer(logs, many=True).data)


# ── stores ───────────────────────────────────────────────────────────────────────────────────────

STORE_ORDERING = {'channel': 'channel__name', 'branch': 'branch__softech_branch_id', 'is_active': 'is_active'}


class StoreListCreate(_Gate, branch_scope.BranchScopedMixin, generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated, EDIT_WRITES]
    serializer_class = StoreSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        ch = _int(self.request.query_params.get('channel'))
        if ch:
            qs = qs.filter(channel_id=ch)
        return qs.order_by(*explicit_order_by(self.request.query_params.get('ordering'), STORE_ORDERING,
                                              ('channel__name', 'branch__softech_branch_id', 'id')))

    queryset = ChannelStore.objects.select_related('channel', 'branch')

    def perform_create(self, serializer):
        self.check_branch_value(serializer)
        s = serializer.save()
        AuditLog.log('marketplace_store_created', user=_profile(self.request), obj=s, request=self.request,
                     new_data=StoreSerializer(s).data)


class StoreDetail(_Gate, branch_scope.BranchScopedMixin, generics.RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated, EDIT_WRITES]
    serializer_class = StoreSerializer
    http_method_names = ['get', 'patch', 'head', 'options']

    queryset = ChannelStore.objects.select_related('channel', 'branch')

    def perform_update(self, serializer):
        self.check_branch_value(serializer)
        before = StoreSerializer(serializer.instance).data
        s = serializer.save()
        AuditLog.log('marketplace_store_updated', user=_profile(self.request), obj=s, request=self.request,
                     old_data=before, new_data=StoreSerializer(s).data)


# ── listings ─────────────────────────────────────────────────────────────────────────────────────

LISTING_ORDERING = {'item': 'item__name', 'code': 'item__softech_id', 'channel': 'channel__name',
                    'approved': 'approved', 'approved_at': 'approved_at'}


def _qty_branch(request):
    """Branch for the per-branch qty column: ?branch= when the user may see it, else their home branch."""
    requested = _int(request.query_params.get('branch'))
    if requested is not None:
        branch_scope.require(request.user, requested)
        return Branch.objects.filter(pk=requested).first()
    profile = _profile(request)
    return profile.branch if profile is not None and profile.branch_id else None


class ListingListCreate(_Gate, generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated, VIEW_CREATE]
    serializer_class = ListingSerializer

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        if self.request.method == 'GET':
            ctx['branch'] = _qty_branch(self.request)
        return ctx

    def get_queryset(self):
        p = self.request.query_params
        qs = ChannelListing.objects.select_related('item', 'channel', 'approved_by__user')
        ch = _int(p.get('channel'))
        if ch:
            qs = qs.filter(channel_id=ch)
        q = (p.get('q') or '').strip()
        if q:
            qs = qs.filter(Q(item__name__icontains=q) | Q(item__softech_id=q) | Q(external_sku=q))
        approved = (p.get('approved') or '').strip().lower()
        if approved in ('1', 'true', 'yes'):
            qs = qs.filter(approved=True)
        elif approved in ('0', 'false', 'no'):
            qs = qs.filter(approved=False)
        return qs.order_by(*explicit_order_by(p.get('ordering'), LISTING_ORDERING, ('item__name', 'id')))

    def perform_create(self, serializer):
        listing = serializer.save(approved=False, approved_by=None, approved_at=None)
        AuditLog.log('marketplace_listing_created', user=_profile(self.request), obj=listing, request=self.request,
                     new_data={'channel': listing.channel.code, 'item_id': listing.item_id,
                               'external_sku': listing.external_sku, 'allow_fridge': listing.allow_fridge})


class _ListingApproval(_Gate, APIView):
    permission_classes = [IsAuthenticated, APPROVE]
    approve = True

    def post(self, request, pk):
        listing = get_object_or_404(ChannelListing.objects.select_related('item', 'channel'), pk=pk)
        before = {'approved': listing.approved, 'approved_by': listing.approved_by_id,
                  'approved_at': listing.approved_at.isoformat() if listing.approved_at else None}
        profile = _profile(request)
        if self.approve:
            listing.approved, listing.approved_by, listing.approved_at = True, profile, timezone.now()
        else:
            listing.approved, listing.approved_by, listing.approved_at = False, None, None
        listing.save(update_fields=['approved', 'approved_by', 'approved_at'])
        AuditLog.log('marketplace_listing_approved' if self.approve else 'marketplace_listing_unapproved',
                     user=profile, obj=listing, request=request, old_data=before,
                     new_data={'approved': listing.approved, 'approved_by': listing.approved_by_id,
                               'approved_at': listing.approved_at.isoformat() if listing.approved_at else None},
                     extra={'channel': listing.channel.code, 'item_id': listing.item_id})
        return Response(ListingSerializer(listing, context={'request': request, 'branch': None}).data)


class ListingApprove(_ListingApproval):
    approve = True


class ListingUnapprove(_ListingApproval):
    approve = False


# ── orders ───────────────────────────────────────────────────────────────────────────────────────

ORDER_ORDERING = {'created_at': 'created_at', 'status': 'status', 'channel': 'channel__name',
                  'branch': 'branch__softech_branch_id', 'external_id': 'external_id',
                  'platform_total': 'platform_total', 'customer_name': 'customer_name'}


def _scoped_orders(request):
    return branch_scope.scope(ExternalOrder.objects.select_related('channel', 'branch', 'store', 'pos_order'),
                              request.user)


def _order_or_404(request, pk):
    return get_object_or_404(_scoped_orders(request), pk=pk)


def _detail(request, order):
    order = (_scoped_orders(request).prefetch_related('lines__item', 'events__by__user').get(pk=order.pk))
    return OrderDetailSerializer(order, context={'request': request}).data


class OrderList(_Gate, generics.ListAPIView):
    permission_classes = [IsAuthenticated, VIEW_CREATE]
    serializer_class = OrderListSerializer

    def get_queryset(self):
        p = self.request.query_params
        qs = _scoped_orders(self.request).annotate(n_lines=Count('lines'))
        if p.get('status'):
            qs = qs.filter(status=p['status'])
        ch = _int(p.get('channel'))
        if ch:
            qs = qs.filter(channel_id=ch)
        br = _int(p.get('branch'))
        if br:
            qs = qs.filter(branch_id=br)
        return qs.order_by(*explicit_order_by(p.get('ordering'), ORDER_ORDERING, ('-created_at', '-id')))


class OrderDetail(_Gate, APIView):
    permission_classes = [IsAuthenticated, VIEW_CREATE]

    def get(self, request, pk):
        return Response(_detail(request, _order_or_404(request, pk)))


def _manual_payload(data, store):
    """Validated manual-intake body → the dict ManualAdapter.parse_order reads. Raises ValueError."""
    from apps.catalog.models import Item
    external_id = str(data.get('external_id') or '').strip()
    if not external_id:
        raise ValueError('اكتب رقم الطلب عند المنصة.')
    payment_mode = data.get('payment_mode') or ExternalOrder.PAY_PLATFORM
    if payment_mode not in dict(ExternalOrder.PAY_CHOICES):
        raise ValueError('طريقة دفع غير معروفة.')
    raw_lines = data.get('lines')
    if not isinstance(raw_lines, list) or not raw_lines:
        raise ValueError('أضف صنفًا واحدًا على الأقل.')
    item_ids = [_int(l.get('item_id')) if isinstance(l, dict) else None for l in raw_lines]
    if any(i is None for i in item_ids):
        raise ValueError('صنف غير صحيح.')
    items = {i.pk: i for i in Item.objects.filter(pk__in=item_ids)}
    lines, total = [], Decimal(0)
    for raw, item_id in zip(raw_lines, item_ids):
        item = items.get(item_id)
        if item is None:
            raise ValueError('صنف غير موجود.')
        try:
            qty = Decimal(str(raw.get('qty', 1)))
            price = Decimal(str(raw.get('unit_price', 0)))
        except (InvalidOperation, ValueError):
            raise ValueError('كمية أو سعر غير صحيح.') from None
        if not qty.is_finite() or not price.is_finite() or qty <= 0 or price < 0:
            raise ValueError('كمية أو سعر غير صحيح.')
        total += qty * price
        lines.append({'item_id': item.pk, 'name': item.name, 'qty': str(qty), 'unit_price': str(price)})
    return {'external_id': external_id[:100], 'external_store_id': store.external_store_id,
            'customer_name': str(data.get('customer_name') or '')[:200],
            'customer_phone': str(data.get('customer_phone') or '')[:30],
            'address': str(data.get('address') or ''), 'payment_mode': payment_mode,
            'total': str(total), 'lines': lines}


class OrderManual(_Gate, APIView):
    permission_classes = [IsAuthenticated, VIEW_CREATE]

    def post(self, request):
        data = request.data if isinstance(request.data, dict) else {}
        channel = get_object_or_404(MarketplaceChannel, pk=_int(data.get('channel')) or 0)
        branch_id = _int(data.get('branch'))
        branch_scope.require(request.user, branch_id)
        active = ChannelStore.objects.filter(channel=channel, is_active=True)
        store = active.filter(branch_id=branch_id).first()
        if store is None:
            return Response({'detail': 'هذا الفرع غير مرتبط بالمنصة.'}, status=status.HTTP_400_BAD_REQUEST)
        # intake resolves the store from its platform code (per-branch) or as the channel's only store
        # (national): refuse up front when that would not land on this branch's store
        if channel.scope == MarketplaceChannel.SCOPE_PER_BRANCH:
            ambiguous = active.filter(external_store_id=store.external_store_id).exclude(pk=store.pk).exists()
        else:
            ambiguous = active.exclude(pk=store.pk).exists()
        if ambiguous:
            return Response({'detail': 'كود المتجر عند المنصة مكرر — راجع إعداد المتاجر.'},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            payload = _manual_payload(data, store)
            incoming = get_adapter('manual', channel).parse_order(payload)
            order, created = intake.ingest(channel, incoming, source=ExternalOrder.SOURCE_MANUAL,
                                           user=_profile(request))
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        if not branch_scope.allows(request.user, order.branch_id):   # duplicate id of another branch's order
            raise Http404
        return Response(_detail(request, order), status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class _OrderAction(_Gate, APIView):
    permission_classes = [IsAuthenticated, VIEW_CREATE]

    def act(self, request, order):
        raise NotImplementedError

    def post(self, request, pk):
        order = _order_or_404(request, pk)
        try:
            order = self.act(request, order)
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(_detail(request, order))


class OrderAccept(_OrderAction):
    def act(self, request, order):
        return intake.accept(order, _profile(request), request=request)


class OrderReject(_OrderAction):
    def act(self, request, order):
        reason = str(request.data.get('reason') or '').strip()
        if not reason:
            raise ValueError('اكتب سبب الرفض.')
        return intake.reject(order, _profile(request), reason, request=request)


class OrderStatus(_OrderAction):
    def act(self, request, order):
        to_status = str(request.data.get('to_status') or '')
        note = str(request.data.get('note') or '')[:300]
        return intake.set_status(order, to_status, _profile(request), note=note, request=request)


# ── push log ─────────────────────────────────────────────────────────────────────────────────────

PUSHLOG_ORDERING = {'at': 'at', 'kind': 'kind', 'ok': 'ok', 'channel': 'channel__name'}


class PushLogList(_Gate, generics.ListAPIView):
    permission_classes = [IsAuthenticated, VIEW_CREATE]
    serializer_class = PushLogSerializer

    def get_queryset(self):
        p = self.request.query_params
        qs = branch_scope.scope(PushLog.objects.select_related('channel', 'store'), self.request.user,
                                'store__branch')
        ch = _int(p.get('channel'))
        if ch:
            qs = qs.filter(channel_id=ch)
        return qs.order_by(*explicit_order_by(p.get('ordering'), PUSHLOG_ORDERING, ('-at', '-id')))


# ── settlements ──────────────────────────────────────────────────────────────────────────────────
# Settlement data is company-level for a channel (a payout covers every branch's orders and has no branch of
# its own), so it is visible to every holder of marketplace `view`; uploading needs `edit` (the middleware maps
# the POST the same way). CLAUDE.md security rule 2.

class SettlementListCreate(_Gate, generics.ListAPIView):
    permission_classes = [IsAuthenticated, EDIT_WRITES]
    serializer_class = SettlementBatchSerializer

    def get_queryset(self):
        qs = SettlementBatch.objects.select_related('channel', 'uploaded_by')
        ch = _int(self.request.query_params.get('channel'))
        return qs.filter(channel_id=ch) if ch else qs

    def post(self, request):
        import json
        d = request.data
        channel = get_object_or_404(MarketplaceChannel, pk=_int(d.get('channel')) or 0)
        upload = request.FILES.get('file')
        if upload is None:
            return Response({'detail': 'الملف مطلوب'}, status=400)
        try:
            cmap = json.loads(d.get('column_map') or '{}')
            if not isinstance(cmap, dict):
                raise ValueError
            frm, to = _date(d.get('period_from')), _date(d.get('period_to'))
        except (ValueError, TypeError):
            return Response({'detail': 'بيانات غير صحيحة'}, status=400)
        try:
            batch = settlement.import_csv(channel, upload, cmap, _profile(request), frm, to)
        except ValueError as exc:
            return Response({'detail': 'تعذر قراءة الملف', 'code': str(exc)}, status=400)
        counts = settlement.match(batch, user=_profile(request))
        data = SettlementBatchSerializer(batch).data
        data['match'] = counts
        return Response(data, status=status.HTTP_201_CREATED)


def _date(value):
    from datetime import date
    return date.fromisoformat(value) if value else None


class SettlementDetail(_Gate, APIView):
    permission_classes = [IsAuthenticated, EDIT_WRITES]

    def get(self, request, pk):
        batch = get_object_or_404(SettlementBatch.objects.select_related('channel', 'uploaded_by'), pk=pk)
        lines = batch.lines.all()
        if request.query_params.get('status'):
            lines = lines.filter(match_status=request.query_params['status'])
        data = SettlementBatchSerializer(batch).data
        data['lines'] = SettlementLineSerializer(lines, many=True).data
        return Response(data)


# ── platform webhook ─────────────────────────────────────────────────────────────────────────────

_NOT_FOUND = {'detail': 'غير موجود'}
_FORBIDDEN = {'detail': 'غير مسموح'}
_UNPROCESSABLE = {'detail': 'تعذر قبول الطلب'}


class WebhookView(APIView):
    """Inbound platform orders. No staff session: flag on + channel active + non-manual adapter, then the
    adapter's signature check. Never echoes the payload or credentials; nothing is stored on a failure."""
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request, channel_code):
        if not enabled():
            return Response(_NOT_FOUND, status=status.HTTP_404_NOT_FOUND)
        channel = (MarketplaceChannel.objects.filter(code=channel_code, is_active=True)
                   .exclude(adapter=MarketplaceChannel.ADAPTER_MANUAL).first())
        if channel is None or channel.adapter not in REGISTRY:
            return Response(_NOT_FOUND, status=status.HTTP_404_NOT_FOUND)
        adapter = get_adapter(channel.adapter, channel)
        if not adapter.verify_webhook(request):
            logger.warning('marketplace webhook signature refused: channel=%s', channel.code)
            return Response(_FORBIDDEN, status=status.HTTP_403_FORBIDDEN)
        try:
            payload = request.data
            if not isinstance(payload, dict):
                raise ValueError('payload')
            incoming = adapter.parse_order(payload)
            if not incoming.external_id:
                raise ValueError('external_id')
            order, created = intake.ingest(channel, incoming, source=ExternalOrder.SOURCE_API)
        except (ParseError, ValueError, TypeError, KeyError, AttributeError, ArithmeticError) as exc:
            logger.warning('marketplace webhook refused: channel=%s error=%s', channel.code, type(exc).__name__)
            return Response(_UNPROCESSABLE, status=422)
        return Response({'id': order.id, 'duplicate': not created},
                        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)
