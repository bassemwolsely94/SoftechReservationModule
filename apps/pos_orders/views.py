"""
apps/pos_orders/views.py — Indirect-POS pending-order API.

NOTE: no SOFTECH writes. /push returns a dry-run plan (the exact payload + SQL we
would send) because POS_WRITER_ENABLED is off and there is no test instance.
"""
import uuid

from django.conf import settings
from django.db import IntegrityError
from rest_framework import generics, permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from .models import SoftechSalesOrder, CHANNEL_TO_PTCLASSIF, PAYTYPE_TO_SOFTECH, DOCKIND_TO_DOCCODE
from .serializers import OrderSerializer
from .permissions import CanOperatePosOrders, CanPushPosOrders
from .validators import validate_order
from .discount_authority import validate_discount_authority
from . import writer


def _staff(user):
    try:
        return user.staff_profile
    except Exception:
        return None


# Only these roles may attribute a sale to a DIFFERENT salesperson; everyone else is locked
# to their own usercode (enforced server-side in perform_create, not just the UI).
SELLER_OVERRIDE_ROLES = {'admin', 'supervisor'}
# Who may SEE the per-item discount ceiling ("≤ X%") on the POS. Kept to manager roles on
# purpose: showing the cap to every cashier would just anchor them to always max it out, which
# defeats the point of capping. Cashiers/salespeople get the silent clamp, not the number.
DISCOUNT_CAP_VIEWER_ROLES = {'admin', 'supervisor', 'pharmacist'}


def _can_change_seller(sp):
    return bool(sp and getattr(sp, 'role', None) in SELLER_OVERRIDE_ROLES)


def _can_see_discount_cap(sp):
    return bool(sp and getattr(sp, 'role', None) in DISCOUNT_CAP_VIEWER_ROLES)


def _valid_uuid(token):
    """Return the canonical UUID string if `token` is a valid UUID, else None — so a
    malformed client_token is ignored (fresh order) instead of 500-ing the UUIDField query."""
    token = (str(token).strip() if token else '')
    if not token:
        return None
    try:
        return str(uuid.UUID(token))
    except (ValueError, AttributeError, TypeError):
        return None


class OrderListCreateView(generics.ListCreateAPIView):
    serializer_class   = OrderSerializer
    permission_classes = [CanOperatePosOrders]

    def get_queryset(self):
        qs = SoftechSalesOrder.objects.all().prefetch_related('lines', 'payments')
        st = self.request.query_params.get('status')
        br = self.request.query_params.get('branch')
        if st:
            qs = qs.filter(status=st)
        if br:
            qs = qs.filter(branch_id=br)
        return qs

    def create(self, request, *args, **kwargs):
        """
        Idempotent create. The client may send a stable `client_token` (UUID) per order
        attempt; a replayed offline-queue create with the same token returns the EXISTING
        order (200) instead of making a duplicate. The DB unique constraint guards the
        race where two replays slip past the lookup.
        """
        token = _valid_uuid(request.data.get('client_token'))
        if token:
            existing = SoftechSalesOrder.objects.filter(client_token=token).first()
            if existing:
                return Response(OrderSerializer(existing).data, status=status.HTTP_200_OK)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            self.perform_create(serializer)
        except IntegrityError:
            existing = SoftechSalesOrder.objects.filter(client_token=token).first()
            if existing:
                return Response(OrderSerializer(existing).data, status=status.HTTP_200_OK)
            raise
        return Response(serializer.data, status=status.HTTP_201_CREATED,
                        headers=self.get_success_headers(serializer.data))

    def perform_create(self, serializer):
        sp = _staff(self.request.user)
        own = (sp.softech_user_id.strip() if sp and sp.softech_user_id else '')
        # a chosen مسئول البيع (usercode only) is honoured ONLY for privileged roles;
        # everyone else is forced to their own usercode regardless of what the client sends.
        chosen = (self.request.data.get('seller_usercode') or '').strip()
        seller = chosen if (chosen and _can_change_seller(sp)) else own
        token = _valid_uuid(self.request.data.get('client_token')) or uuid.uuid4()
        serializer.save(created_by=sp, seller_usercode=seller, client_token=token)


class OrderDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset           = SoftechSalesOrder.objects.all().prefetch_related('lines', 'payments')
    serializer_class   = OrderSerializer
    permission_classes = [permissions.IsAuthenticated]

    def update(self, request, *a, **k):
        order = self.get_object()
        if order.is_locked:
            return Response({'detail': 'الأمر مقفل (تم إرساله/تحصيله) — لا يمكن التعديل.'},
                            status=status.HTTP_409_CONFLICT)
        return super().update(request, *a, **k)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def ready_order(request, pk):
    """Validate + compute money fields (pricing.py); optionally accept explicit tenders."""
    order = SoftechSalesOrder.objects.get(pk=pk)
    tenders = request.data.get('tenders')   # [{pay_type, amount}, ...] or None
    live = bool(request.data.get('live', settings.POS_LIVE_PRICING))
    try:
        writer.prepare_order(order, tenders=tenders, live=live)
    except ValueError as e:
        return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    try:
        validate_order(order)
    except ValidationError as e:
        return Response({'detail': 'فشل التحقق من بيانات الأمر.', 'errors': e.detail},
                        status=status.HTTP_400_BAD_REQUEST)
    # Authority-aware discount check — a LIVE branch read, so only run it when a real
    # SOFTECH write could actually happen (writer enabled). In dry-run/preview mode it is
    # skipped, keeping previews instant and avoiding a needless branch round-trip.
    if writer.writer_enabled():
        try:
            disc_errs = validate_discount_authority(order)
        except Exception:
            disc_errs = []   # live-read failure must never block /ready
        if disc_errs:
            return Response({'detail': 'الخصم يتجاوز الصلاحية المسموح بها.',
                             'errors': {'discount_authority': disc_errs}},
                            status=status.HTTP_400_BAD_REQUEST)
    return Response(OrderSerializer(order).data)


@api_view(['POST'])
@permission_classes([CanPushPosOrders])
def push_order(request, pk):
    """
    'Send to Cashier'. Guarded:
      • Dry-run (default) — returns the payload + exact SQL, writes NOTHING. Runs the
        full field validation so the operator sees every error before going live.
      • Live — only when the writer gate is ON, the caller explicitly sends
        dry_run=false AND confirm=true, and the order passes the strict push checks
        (balance + claim data). Without confirm we return 409 with requires_confirm.
    """
    order = SoftechSalesOrder.objects.get(pk=pk)
    want_live = (request.data.get('dry_run') is False)
    dry = (not writer.writer_enabled()) or (not want_live)

    # Validate before anything: basic for dry-run, strict (balance/claim) for a live write.
    try:
        validate_order(order, for_push=not dry)
    except ValidationError as e:
        return Response({'detail': 'فشل التحقق من بيانات الأمر — لا يمكن الإرسال.', 'errors': e.detail},
                        status=status.HTTP_400_BAD_REQUEST)

    # A real cashier write demands an explicit confirmation token (anti-fat-finger).
    if not dry and not request.data.get('confirm'):
        return Response({'detail': 'الإرسال الفعلي إلى الكاشير يتطلب تأكيداً.', 'requires_confirm': True},
                        status=status.HTTP_409_CONFLICT)

    try:
        result = writer.push_order(order, dry_run=dry)
    except writer.WriterDisabled as e:
        return Response({'detail': str(e)}, status=status.HTTP_501_NOT_IMPLEMENTED)
    except ValueError as e:
        return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    result['live'] = (not dry)
    # Out-of-stock rejection (we don't write حجز) → 400 with the OOS lines (matches native منع الصرف).
    if result.get('stock_errors'):
        return Response({**result, 'detail': 'أصناف غير متوفرة بالرصيد — لا يمكن الإرسال.',
                         'errors': {'stock': [e['detail'] for e in result['stock_errors']]}},
                        status=status.HTTP_400_BAD_REQUEST)
    # Branch was unreachable → the order is safely queued for automatic retry (HTTP 202).
    if result.get('queued'):
        return Response({**result, 'detail': 'الفرع غير متصل — تم حفظ الأمر في الطابور وسيُرسل تلقائياً عند عودة الاتصال.'},
                        status=status.HTTP_202_ACCEPTED)
    return Response(result)


@api_view(['POST'])
@permission_classes([CanPushPosOrders])
def cancel_order(request, pk):
    order = SoftechSalesOrder.objects.get(pk=pk)
    try:
        writer.cancel_order(order)
    except (ValueError, writer.WriterDisabled) as e:
        return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(OrderSerializer(order).data)


@api_view(['GET'])
@permission_classes([CanOperatePosOrders])
def batch_availability_view(request):
    """
    Live per-batch stock for the POS batch-pick modal.
    GET ?branch=<id>&item=<softech_itemcode>[&store=<storecode>]
    Returns the available batches (expiry/qty) + a summary; out_of_stock ⇒ reservation.
    """
    from apps.branches.models import Branch
    from .batch_availability import available_batches, summarize
    item = (request.query_params.get('item') or '').strip()
    branch_id = request.query_params.get('branch')
    if not item or not branch_id:
        return Response({'detail': 'برجاء تحديد الفرع والصنف.'}, status=status.HTTP_400_BAD_REQUEST)
    try:
        branch = Branch.objects.get(pk=branch_id)
    except Branch.DoesNotExist:
        return Response({'detail': 'الفرع غير موجود.'}, status=status.HTTP_404_NOT_FOUND)
    store = (request.query_params.get('store') or branch.softech_branch_id or '').strip()
    try:
        batches = available_batches(branch.effective_db_host, store, item,
                                    branch.effective_db_port, branch.db_name or 'SOFTECHDB9')
    except Exception as e:
        return Response({'detail': f'تعذّر قراءة الأرصدة: {e}'}, status=status.HTTP_502_BAD_GATEWAY)
    return Response({'item': item, 'store': store, 'batches': batches, **summarize(batches)})


@api_view(['GET'])
@permission_classes([CanOperatePosOrders])
def contract_fields_view(request):
    """Per-contract "Contract Employee Data" field spec (which claim fields show + custom labels).
    GET ?branch=<id>&customer=<contract personcode>
    Returns {fields:[{slot,column,label_ar,label_en,is_date}]} from SOFTECH motalba_fields — the POS
    renders ONLY these fields (blacked-out ones omitted) with the per-contract labels."""
    from apps.branches.models import Branch
    from .contract_fields import contract_field_spec
    personcode = (request.query_params.get('customer') or '').strip()
    branch_id = request.query_params.get('branch')
    if not personcode or not branch_id:
        return Response({'detail': 'برجاء تحديد الفرع وعميل التعاقد.'}, status=status.HTTP_400_BAD_REQUEST)
    try:
        branch = Branch.objects.get(pk=branch_id)
    except Branch.DoesNotExist:
        return Response({'detail': 'الفرع غير موجود.'}, status=status.HTTP_404_NOT_FOUND)
    try:
        fields = contract_field_spec(branch.effective_db_host, branch.effective_db_port,
                                     branch.db_name or 'SOFTECHDB9', personcode)
    except Exception as e:
        return Response({'detail': f'تعذّر قراءة إعدادات حقول التعاقد: {e}'},
                        status=status.HTTP_502_BAD_GATEWAY)
    return Response({'customer': personcode, 'fields': fields})


@api_view(['GET'])
@permission_classes([CanOperatePosOrders])
def customer_types(request):
    """نوع العميل — the POS customer-type list (type → channel + discount source)."""
    from .customer_directory import POS_CUSTOMER_TYPES
    return Response({'types': POS_CUSTOMER_TYPES})


@api_view(['GET'])
@permission_classes([CanOperatePosOrders])
def customer_entities(request):
    """إسم العميل — entities of one نوع العميل. GET ?branch=&type=<key>[&q=]."""
    from apps.branches.models import Branch
    from .customer_directory import list_entities
    type_key = (request.query_params.get('type') or '').strip()
    branch_id = request.query_params.get('branch')
    q = (request.query_params.get('q') or '').strip() or None
    if not type_key or not branch_id:
        return Response({'detail': 'برجاء تحديد الفرع ونوع العميل.'}, status=status.HTTP_400_BAD_REQUEST)
    try:
        branch = Branch.objects.get(pk=branch_id)
    except Branch.DoesNotExist:
        return Response({'detail': 'الفرع غير موجود.'}, status=status.HTTP_404_NOT_FOUND)
    try:
        entities = list_entities(branch.effective_db_host, type_key, q=q,
                                 db_port=branch.effective_db_port, db_name=branch.db_name or 'SOFTECHDB9')
    except Exception as e:
        return Response({'entities': [], 'note': f'تعذّر القراءة: {e}'})
    return Response({'type': type_key, 'entities': entities})


@api_view(['GET'])
@permission_classes([CanOperatePosOrders])
def salespeople_view(request):
    """مسئول البيع — searchable list of {usercode, name} from SOFTECH users. GET ?branch=[&q=]."""
    from apps.branches.models import Branch
    from .customer_directory import salespeople
    branch_id = request.query_params.get('branch')
    q = (request.query_params.get('q') or '').strip() or None
    if not branch_id:
        return Response({'detail': 'برجاء تحديد الفرع.'}, status=status.HTTP_400_BAD_REQUEST)
    try:
        branch = Branch.objects.get(pk=branch_id)
    except Branch.DoesNotExist:
        return Response({'detail': 'الفرع غير موجود.'}, status=status.HTTP_404_NOT_FOUND)
    try:
        people = salespeople(branch.effective_db_host, q=q, db_port=branch.effective_db_port,
                             db_name=branch.db_name or 'SOFTECHDB9')
    except Exception as e:
        return Response({'salespeople': [], 'note': f'تعذّر القراءة: {e}'})
    return Response({'salespeople': people})


@api_view(['GET'])
@permission_classes([CanOperatePosOrders])
def branch_stores_view(request):
    """من حساب مخزن — stores of a branch (branch-dependent). GET ?branch="""
    from apps.branches.models import Branch
    from .customer_directory import branch_stores
    branch_id = request.query_params.get('branch')
    if not branch_id:
        return Response({'detail': 'برجاء تحديد الفرع.'}, status=status.HTTP_400_BAD_REQUEST)
    try:
        branch = Branch.objects.get(pk=branch_id)
    except Branch.DoesNotExist:
        return Response({'detail': 'الفرع غير موجود.'}, status=status.HTTP_404_NOT_FOUND)
    try:
        stores = branch_stores(branch.effective_db_host, branch.softech_branch_id,
                               db_port=branch.effective_db_port, db_name=branch.db_name or 'SOFTECHDB9')
    except Exception as e:
        return Response({'stores': [], 'note': f'تعذّر القراءة: {e}'})
    return Response({'branch': branch.softech_branch_id, 'stores': stores})


@api_view(['GET'])
@permission_classes([CanOperatePosOrders])
def queue_status(request):
    """Counts of orders waiting on connectivity — for the POS 'في الطابور' indicator."""
    from django.db.models import Count
    qs = SoftechSalesOrder.objects.filter(status__in=[
        SoftechSalesOrder.STATUS_QUEUED, SoftechSalesOrder.STATUS_PUSH_FAILED,
        SoftechSalesOrder.STATUS_PUSHING])
    branch = request.query_params.get('branch')
    if branch:
        qs = qs.filter(branch_id=branch)
    counts = {row['status']: row['c'] for row in qs.values('status').annotate(c=Count('id'))}
    return Response({
        'queued':      counts.get(SoftechSalesOrder.STATUS_QUEUED, 0),
        'push_failed': counts.get(SoftechSalesOrder.STATUS_PUSH_FAILED, 0),
        'pushing':     counts.get(SoftechSalesOrder.STATUS_PUSHING, 0),
        'writer_enabled': writer.writer_enabled(),
    })


@api_view(['POST'])
@permission_classes([CanPushPosOrders])
def flush_now(request):
    """Supervisor 'flush now' — retry queued (and optionally failed) orders immediately.
    Idempotent + collision-safe (push_order allocates the serial atomically at write)."""
    if not writer.writer_enabled():
        return Response({'detail': 'الكتابة الفعلية مُعطّلة (POS_WRITER_ENABLED=False).'},
                        status=status.HTTP_409_CONFLICT)
    statuses = [SoftechSalesOrder.STATUS_QUEUED]
    if request.data.get('include_failed'):
        statuses.append(SoftechSalesOrder.STATUS_PUSH_FAILED)
    qs = (SoftechSalesOrder.objects.filter(status__in=statuses)
          .select_related('branch').order_by('created_at')[:50])
    pushed = queued = failed = 0
    results = []
    for order in qs:
        try:
            res = writer.push_order(order, dry_run=False)
        except Exception as e:
            failed += 1; results.append({'id': order.pk, 'error': str(e)}); continue
        if res.get('queued'):
            queued += 1
        elif res.get('ok') or res.get('already_pushed'):
            pushed += 1; results.append({'id': order.pk, 'docnumber': res.get('docnumber')})
        else:
            failed += 1
    return Response({'pushed': pushed, 'still_queued': queued, 'failed': failed, 'results': results})


@api_view(['GET'])
@permission_classes([CanOperatePosOrders])
def discount_suggest(request):
    """
    SOFTECH-style suggested discount per item, by channel (operator can still edit).
    GET ?branch=<id>&channel=<cash|delivery|contract|…>&items=404,963[&personcode=]

    Discount behaviour differs by channel — this is the crux of correct pricing:
      • retail (cash/delivery/permanent/employee/vip) → CAP-ONLY, no auto-apply. The operator
        enters the discount; the per-item ceiling = min(item's own POS discount `items.posdiscp`,
        seller max `managerdiscount.max_custdiscp`). NOT custdiscounts — that table carries the
        contract/point-system schedule and would wrongly apply a loyalty/contract rate to a
        walk-in sale.
      • contract/insurance → AUTO-APPLY the customer's contracted rate (`custdiscounts` by
        category, keyed by the selected entity's personcode), bounded by the seller ceiling.

    Returns per item: `suggestions[code]` = rate to auto-apply (contract only; null for retail),
    `caps[code]` = the max % the operator may enter for that item. Read-only; graceful if down.
    """
    from apps.branches.models import Branch
    from .discount_authority import DiscountAuthorityReader
    items = [s.strip() for s in (request.query_params.get('items') or '').split(',') if s.strip()]
    branch_id = request.query_params.get('branch')
    channel = request.query_params.get('channel', 'cash')
    if not items or not branch_id:
        return Response({'detail': 'برجاء تحديد الفرع والأصناف.'}, status=status.HTTP_400_BAD_REQUEST)
    try:
        branch = Branch.objects.get(pk=branch_id)
    except Branch.DoesNotExist:
        return Response({'detail': 'الفرع غير موجود.'}, status=status.HTTP_404_NOT_FOUND)
    sp = _staff(request.user)
    seller = (sp.softech_user_id.strip() if sp and sp.softech_user_id else '')
    is_contract = channel in ('contract', 'insurance')
    suggestions, caps, ceiling = {}, {}, None
    try:
        reader = DiscountAuthorityReader(branch.effective_db_host, branch.effective_db_port,
                                         branch.db_name or 'SOFTECHDB9')
        try:
            # the seller's max grantable % — the ceiling for BOTH channel families
            ceiling = reader.max_authority(seller, branch.softech_branch_id)
            ceiling = float(ceiling) if ceiling is not None else None
            # contract/insurance only: the selected entity's personcode drives custdiscounts
            personcode = None
            if is_contract:
                personcode = (request.query_params.get('personcode') or '').strip() \
                    or reader.customer_personcode(channel)
            for it in items:
                rate, cap = None, None
                if is_contract:
                    cat = reader.item_category(it)
                    if personcode and cat:
                        c = reader.contracted(personcode, cat)
                        if c:
                            rate = float(c[0]) if c[1] else 0   # allow_sell=0 → 0 (cannot discount)
                    if rate is not None and ceiling is not None:
                        rate = min(rate, ceiling)
                    cap = ceiling                               # seller ceiling caps a contract override
                else:
                    # retail: CAP-ONLY. cap = min(item posdiscp, seller max); nothing auto-applied.
                    pd = reader.item_posdiscp(it)
                    pd = float(pd) if pd is not None else None
                    bounds = [b for b in (pd, ceiling) if b is not None]
                    cap = min(bounds) if bounds else None
                suggestions[it] = rate
                caps[it] = cap
        finally:
            reader.close()
    except Exception as e:
        return Response({'suggestions': {}, 'caps': {}, 'ceiling': None, 'note': f'تعذّر القراءة: {e}'})
    return Response({'suggestions': suggestions, 'caps': caps, 'ceiling': ceiling,
                     'source': 'contract' if is_contract else 'item_pos'})


@api_view(['GET'])
@permission_classes([CanOperatePosOrders])
def points_preview_view(request):
    """PIC loyalty-points status for the POS. GET ?channel=&pic=<softech_pic>
    Returns {eligible (channel carries a points programme), enrolled (SOFTECH
    localcustomers.picpoints=1)}. The points AMOUNT is per-item and computed by SOFTECH at
    finalization (not reproducible read-only — see points.py). The enrolment read is live + graceful."""
    from . import points as pts
    channel = request.query_params.get('channel', 'cash')
    pic = (request.query_params.get('pic') or '').strip()
    return Response({
        'eligible': pts.channel_earns_points(channel),
        'enrolled': pts.is_enrolled(pic) if pic else False,
        'pic': pic or None,
    })


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def reference_data(request):
    """Channel/payment/doc-kind → SOFTECH code maps + writer state, for the POS UI."""
    sp = _staff(request.user)
    return Response({
        'channels':     [{'value': k, 'ptclassifcode': v} for k, v in CHANNEL_TO_PTCLASSIF.items()],
        'payment_types': PAYTYPE_TO_SOFTECH,
        'doc_kinds':    DOCKIND_TO_DOCCODE,
        'writer_enabled': writer.writer_enabled(),
        'seller_usercode': (sp.softech_user_id.strip() if sp and sp.softech_user_id else ''),
        'seller_name': (sp.softech_username.strip() if sp and sp.softech_username else ''),
        'can_change_seller': _can_change_seller(sp),
        'can_see_discount_cap': _can_see_discount_cap(sp),
        'default_branch': (sp.branch_id if sp and sp.branch_id else None),   # auto-select the seller's branch
        'note': 'SOFTECH writes are disabled (no test instance). /push returns a dry-run plan.',
    })
