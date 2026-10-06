"""
apps/pos_orders/views.py — Indirect-POS pending-order API.

NOTE: no SOFTECH writes. /push returns a dry-run plan (the exact payload + SQL we
would send) because POS_WRITER_ENABLED is off and there is no test instance.
"""
import logging
import uuid

from django.conf import settings
from django.db import IntegrityError

logger = logging.getLogger('pos_orders')
from rest_framework import generics, permissions, status
from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import MultiPartParser, FormParser
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


# On contract / permanent / claim channels the discount is RETRIEVED (the contracted rate)
# and locked — only managers may change it. Normal salespeople accept whatever is retrieved.
CONTRACT_DISCOUNT_EDIT_ROLES = {'admin', 'supervisor'}


def _can_edit_contract_discount(sp):
    return bool(sp and getattr(sp, 'role', None) in CONTRACT_DISCOUNT_EDIT_ROLES)


def _branch_of(request):
    """Optional branch from the request body (for corpus attribution)."""
    from apps.branches.models import Branch
    bid = (request.data or {}).get('branch')
    if bid and str(bid).isdigit():
        return Branch.objects.filter(pk=int(bid)).first()
    return None


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
        # ── POS channel RBAC (server-authoritative) — a member may only create orders on
        # the sales channels they're allowed. Managers get all; empty allow-list = all.
        sp = _staff(request.user)
        channel = (request.data.get('channel') or '').strip()
        if sp and channel and not sp.can_pos_channel(channel):
            return Response({'detail': 'غير مصرّح لك بالبيع على هذه القناة.',
                             'errors': {'channel': ['قناة بيع غير مصرّح بها لهذا المستخدم.']}},
                            status=status.HTTP_403_FORBIDDEN)
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
        order = serializer.save(created_by=sp, seller_usercode=seller, client_token=token)
        # RETURN (مرتجع): the backend is authoritative — mirror the ORIGINAL finalized sale's lines +
        # refund tenders from SOFTECH (source_raw never round-trips through the client). A bad invoice or
        # an offline branch rolls the order back and surfaces the reason. (Full return; partial later.)
        if order.doc_kind == 'return' and order.return_of_invoice:
            # `return_lines` (optional) = [{dblitemflag, qty}] to return a SUBSET (partial return); absent
            # or the full set → full return mirroring the sale's exact payment rows.
            selection = self.request.data.get('return_lines') or None
            try:
                writer.build_return_from_sale(order, selection=selection)
            except ValueError as e:
                order.delete()
                raise ValidationError({'return_of_invoice': str(e)})


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


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def return_lookup(request):
    """Preview a finalized invoice for RETURN (read-only, NO order created). Query: ?branch=&invoice=.
    Returns the sale's date + line summary + payments so the cashier can confirm before creating the
    return; the authoritative mirror (with source_raw) happens server-side at order create."""
    from apps.branches.models import Branch
    try:
        branch = Branch.objects.filter(pk=int(request.query_params.get('branch'))).first()
    except (TypeError, ValueError):
        branch = None
    invoice = (request.query_params.get('invoice') or '').strip()
    if not branch:
        return Response({'detail': 'الفرع مطلوب.'}, status=status.HTTP_400_BAD_REQUEST)
    if not invoice.isdigit():
        return Response({'detail': 'رقم فاتورة غير صحيح.'}, status=status.HTTP_400_BAD_REQUEST)
    try:
        docdate, lines, pays = writer.read_finalized_sale(branch, branch.softech_branch_id, int(invoice))
    except ValueError as e:
        return Response({'detail': str(e)}, status=status.HTTP_404_NOT_FOUND)
    # best-effort item names from the catalog mirror (never blocks the lookup)
    names = {}
    try:
        from apps.catalog.models import Item
        codes = [str(l['itemcode']).strip() for l in lines]
        names = {str(c).strip(): n for c, n in
                 Item.objects.filter(softech_itemcode__in=codes).values_list('softech_itemcode', 'name')}
    except Exception:
        names = {}
    disp = [{
        'dblitemflag': int(l.get('dblitemflag') or 0),   # stable ref for partial-return selection
        'itemcode': str(l['itemcode']).strip(),
        'item_name': names.get(str(l['itemcode']).strip(), str(l['itemcode']).strip()),
        'qty': float(l['transqty'] or 0),                        # الكمية المباعة (sold)
        'returned_prev': float(l.get('returned_prev') or 0),     # مرتجع سابق
        'returnable': float(l.get('returnable') or 0),           # what can still be returned
        'blocked': bool(l.get('blocked')),                       # reservation → can't return here
        'block_reason': l.get('block_reason') or '',
        'unit_price': float(l['itemsaleprice'] or 0),
        'cust_discp': float(l['custdiscp'] or 0),
        'line_total': float(l['transprice_total'] or 0),
        'is_reservation': bool(l.get('is_reservation')),
    } for l in lines]
    # full-invoice-only flag (empftime) for the sale's account — the sale lines carry personcode = account.
    full_only = False
    try:
        acct = str((lines[0].get('personcode') or '')).strip()
        if acct:
            _o = SoftechSalesOrder(branch=branch, softech_branchcode=branch.softech_branch_id,
                                   cust_branch_code=acct, channel='contract')
            full_only = writer.read_return_full_only(_o)
    except Exception:
        full_only = False
    return Response({
        'invoice': int(invoice), 'docdate': docdate[:10], 'branch': branch.pk,
        'line_count': len(disp), 'lines': disp, 'full_only': full_only,
        'returnable_total': round(sum(d['line_total'] for d in disp if not d['blocked'] and d['returnable'] > 0), 2),
        'total': round(sum(d['line_total'] for d in disp), 2),
        'payments': [{'type': p['paymenttype'], 'value': p['paymentvalue']} for p in pays],
    })


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
    # Manager-locked contract/permanent discount — deterministic role rule (no live read),
    # so it applies in dry-run AND live: a non-manager may not apply/raise a discount on
    # contract/permanent/claim channels. Admins/supervisors bypass.
    from .discount_authority import validate_contract_discount_role
    role_errs = validate_contract_discount_role(order, _can_edit_contract_discount(_staff(request.user)))
    if role_errs:
        return Response({'detail': 'خصم قنوات التعاقد/العملاء الدائمين مقصور على المدير.',
                         'errors': {'discount_authority': role_errs}},
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

    # Offer approval gate (Phase 3): a live push of an order carrying an unapproved
    # offer discount is blocked server-side, before anything. No-op for non-offer orders.
    if not dry:
        from apps.offers.order_attach import push_blocked_by_offer_approval
        blocked = push_blocked_by_offer_approval(order)
        if blocked:
            return Response({'detail': blocked, 'requires_offer_approval': True},
                            status=status.HTTP_409_CONFLICT)

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

    # Offer usage pre-check (Phase 3, step 5): never POST an over-limit promo.
    # No-op for non-offer orders (no lines with discount_source='offer').
    offer_customer = None
    if not dry:
        from apps.offers.order_attach import resolve_order_customer
        from apps.offers.usage import precheck_order
        offer_customer = resolve_order_customer(order)
        exhausted = precheck_order(order, offer_customer)
        if exhausted:
            return Response({'detail': exhausted, 'offer_usage_exhausted': True},
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
    # NOTE: offer uses are consumed when the queued order actually POSTS (via the
    # flush path), not here — see docs/PHASE3_OFFER_EXECUTION_DESIGN.md §9.
    if result.get('queued'):
        return Response({**result, 'detail': 'الفرع غير متصل — تم حفظ الأمر في الطابور وسيُرسل تلقائياً عند عودة الاتصال.'},
                        status=status.HTTP_202_ACCEPTED)

    # Sale POSTED successfully → commit offer uses (flip OfferApplication.was_applied).
    # Idempotent + locked. A rare race that over-consumes after the sale already
    # posted is logged + flagged (we never fail a posted sale).
    if not dry:
        from apps.offers.usage import consume_offer_uses, UsageLimitExceeded
        try:
            consumed = consume_offer_uses(order, customer=offer_customer)
            if consumed:
                result['offer_uses_consumed'] = len(consumed)
        except UsageLimitExceeded as e:
            logger.error('[pos_orders] order=%s POSTED but offer overused (%s) — flagged for review',
                         order.pk, e.scope)
            result['offer_overuse'] = True
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


def build_order_whatsapp_message(order):
    """Format a WhatsApp-ready digital-receipt text for a saved POS order (Wave 7). Pure — builds
    the message from the order's own persisted lines/totals; no SOFTECH read, no side-effects.
    Line net is derived from item_sale_price × qty × (1 − disc%) so it is correct whether or not
    the order has been priced yet; header totals prefer the stored doc_value_* when present."""
    S = SoftechSalesOrder
    br = order.branch
    branch_name = (br.name_ar or br.name) if br else ''
    when = (order.created_at.strftime('%Y-%m-%d %H:%M') if order.created_at else '')
    kind = 'مرتجع' if order.doc_kind == 'return' else 'إيصال بيع'
    head_no = f'POS-{order.pk}'
    if order.softech_final_docnumber:
        head_no += f' · فاتورة {int(order.softech_final_docnumber)}'
    elif order.softech_docnumber:
        head_no += f' · مستند {int(order.softech_docnumber)}'

    lines = [f'🧾 *{kind} — صيدليات الرزيقي*', f'أمر رقم: {head_no}']
    if branch_name:
        lines.append(f'الفرع: {branch_name}')
    who = order.softech_pic or order.customer_name
    if who:
        lines.append(f'العميل: {who}')
    if when:
        lines.append(f'التاريخ: {when}')
    lines.append('')

    order_lines = list(order.lines.all())
    lines.append(f'*الأصناف ({len(order_lines)}):*')
    gross = disc = 0.0
    for i, l in enumerate(order_lines, 1):
        price = float(l.item_sale_price or 0)
        qty = float(l.qty or 0)
        dp = float(l.cust_discp or 0)
        g = price * qty
        net_line = g * (1 - dp / 100.0)
        gross += g
        disc += (g - net_line)
        tail = f' (خصم {dp:g}%)' if dp else ''
        lines.append(f'{i}. {l.item_name or l.softech_itemcode} × {qty:g} — {net_line:.2f} ج.م{tail}')

    # prefer the stored, backend-priced header totals when the order has been prepared
    show_gross = float(order.doc_value_gross) if order.doc_value_gross else round(gross, 2)
    show_net   = float(order.doc_value) if order.doc_value else round(gross - disc, 2)
    show_disc  = round(show_gross - show_net, 2)
    lines += ['', f'الإجمالي: {show_gross:.2f} ج.م']
    if show_disc > 0.005:
        lines.append(f'الخصم: {show_disc:.2f} ج.م')
    lines.append(f'*الصافي: {show_net:.2f} ج.م*')
    if order.status == S.STATUS_SETTLED:
        lines.append('✅ تم التحصيل')
    elif order.status in (S.STATUS_PUSHED, S.STATUS_READY, S.STATUS_QUEUED):
        lines.append('⏳ بانتظار إتمام الكاشير')
    lines += ['', 'شكراً لتعاملكم مع صيدليات الرزيقي 🌿']
    return '\n'.join(lines)


@api_view(['POST'])
@permission_classes([CanOperatePosOrders])
def share_whatsapp(request, pk):
    """POST /pos-orders/<pk>/share-whatsapp/ — return a WhatsApp-ready digital-receipt message for a
    saved order (+ the customer's phone when available). The frontend opens wa.me/<phone>?text=… ;
    the actual send is the operator's explicit action. Read-only: no SOFTECH write, no status change."""
    try:
        order = SoftechSalesOrder.objects.select_related('branch', 'customer').prefetch_related('lines').get(pk=pk)
    except SoftechSalesOrder.DoesNotExist:
        return Response({'detail': 'الأمر غير موجود.'}, status=status.HTTP_404_NOT_FOUND)
    phone = ''
    if order.customer_id:
        phone = (order.customer.whatsapp_phone or order.customer.phone or '').strip()
    return Response({'message_text': build_order_whatsapp_message(order), 'phone': phone})


@api_view(['GET'])
@permission_classes([CanOperatePosOrders])
def lost_sales_view(request):
    """POS-AUDIT / lost-sales (Wave 3) — read-only aggregates from SOFTECH `pos_cancel`, the
    «سجل المبيعات الغير مخزنة» log (POS lines entered then NOT committed to stktrans). Surfaces top
    abandoned items (lost-sale signal) + cancellations by cashier + value-at-risk for one branch.
    GET ?branch=<id>&days=<n> (default 14). READ-ONLY: never writes to SOFTECH."""
    from datetime import timedelta
    from django.utils import timezone
    from apps.branches.models import Branch
    from .pos_cancel_read import read_pos_cancel, shape_lost_sales

    branch_id = request.query_params.get('branch')
    if not branch_id:
        return Response({'detail': 'برجاء تحديد الفرع.'}, status=status.HTTP_400_BAD_REQUEST)
    try:
        branch = Branch.objects.get(pk=branch_id)
    except Branch.DoesNotExist:
        return Response({'detail': 'الفرع غير موجود.'}, status=status.HTTP_404_NOT_FOUND)
    try:
        days = max(1, min(90, int(request.query_params.get('days', 14))))
    except (TypeError, ValueError):
        days = 14
    since = timezone.now() - timedelta(days=days)
    if not branch.effective_db_host:
        return Response({'detail': 'لا يوجد سيرفر لهذا الفرع.'}, status=status.HTTP_400_BAD_REQUEST)
    try:
        totals, item_rows, cashier_rows = read_pos_cancel(
            branch.effective_db_host, branch.softech_branch_id, since,
            branch.effective_db_port, branch.db_name or 'SOFTECHDB9')
    except Exception as e:
        return Response({'detail': f'تعذّر قراءة سجل الإلغاء: {e}'}, status=status.HTTP_502_BAD_GATEWAY)

    # resolve names from OUR mirrors (no extra SOFTECH round-trip): items ← catalog, cashiers ← staff.
    item_names, cashier_names = {}, {}
    try:
        from apps.catalog.models import Item
        codes = [str(r[0]).strip() for r in (item_rows or [])]
        item_names = {str(c).strip(): n for c, n in
                      Item.objects.filter(softech_id__in=codes).values_list('softech_id', 'name')}
    except Exception:
        pass
    try:
        from apps.users.models import StaffProfile
        ucodes = [str(r[0]).strip() for r in (cashier_rows or [])]
        for sp in StaffProfile.objects.filter(softech_user_id__in=ucodes).select_related('user'):
            cashier_names[str(sp.softech_user_id).strip()] = (
                sp.user.get_full_name() or sp.user.username) if sp.user_id else sp.softech_user_id
    except Exception:
        pass

    data = shape_lost_sales(totals, item_rows, cashier_rows, item_names, cashier_names)
    data['branch'] = branch.id
    data['branch_name'] = branch.name_ar or branch.name
    data['days'] = days
    data['since'] = since.isoformat()
    return Response(data)


@api_view(['GET'])
@permission_classes([CanOperatePosOrders])
def lost_sales_trends_view(request):
    """Historical lost-sale trends from the PosCancelDaily mirror (Wave 3 inc2) — fast PG read, no
    Sybase. Cross-branch by default; filterable. GET ?days=30&branch=<code>&doccode=115&limit=25.
    Returns period summary, top lost items, by-branch split, and a daily time series (for a chart)."""
    from datetime import timedelta
    from django.utils import timezone
    from django.db.models import Sum, F
    from .models import PosCancelDaily

    try:
        days = max(1, min(365, int(request.query_params.get('days', 30))))
    except (TypeError, ValueError):
        days = 30
    try:
        limit = max(1, min(100, int(request.query_params.get('limit', 25))))
    except (TypeError, ValueError):
        limit = 25
    since = (timezone.now() - timedelta(days=days)).date()

    qs = PosCancelDaily.objects.filter(day__gte=since)
    branch = (request.query_params.get('branch') or '').strip()
    if branch:
        qs = qs.filter(branch_code=branch)
    doccode = (request.query_params.get('doccode') or '').strip()
    if doccode:
        qs = qs.filter(doccode=doccode)

    summary = qs.aggregate(lost_value=Sum('lost_value'), priced_events=Sum('priced_events'),
                           events=Sum('events'))
    top_items = list(
        qs.values('item_code', 'item_name')
          .annotate(lost_value=Sum('lost_value'), priced_events=Sum('priced_events'),
                    events=Sum('events'))
          .order_by('-lost_value')[:limit])
    by_branch = list(
        qs.values('branch_code')
          .annotate(lost_value=Sum('lost_value'), priced_events=Sum('priced_events'))
          .order_by('-lost_value'))
    daily = list(
        qs.values('day')
          .annotate(lost_value=Sum('lost_value'), priced_events=Sum('priced_events'))
          .order_by('day'))

    def _f(v):
        return round(float(v or 0), 2)
    return Response({
        'days': days,
        'since': since.isoformat(),
        'summary': {
            'lost_value': _f(summary['lost_value']),
            'priced_events': int(summary['priced_events'] or 0),
            'events': int(summary['events'] or 0),
        },
        'top_items': [{**r, 'lost_value': _f(r['lost_value'])} for r in top_items],
        'by_branch': [{**r, 'lost_value': _f(r['lost_value'])} for r in by_branch],
        'daily': [{'day': r['day'].isoformat(), 'lost_value': _f(r['lost_value']),
                   'priced_events': int(r['priced_events'] or 0)} for r in daily],
    })


@api_view(['POST'])
@permission_classes([CanOperatePosOrders])
def selection_events_ingest(request):
    """Capture POS item-selection telemetry (Wave 3 inc3) into PosSelectionEvent — later batch-written
    to SOFTECH pos_cancel. Fire-and-forget from the POS: a bad row is skipped, never 500s the client.
    Body: {branch, cart_token, events:[{item,item_code,item_name,doc_kind,event_type,itemsaleprice,
    transprice,transqty,transprice_total,custcode,occurred_at}]}. Attribution (seller/created_by) is
    server-authoritative — the client cannot spoof who selected."""
    from decimal import Decimal, InvalidOperation
    from django.utils.dateparse import parse_datetime
    from django.utils import timezone
    from apps.branches.models import Branch
    from .models import PosSelectionEvent

    sp = _staff(request.user)
    seller = (sp.softech_user_id.strip() if sp and sp.softech_user_id else '')[:5]
    try:
        branch = Branch.objects.filter(pk=int(request.data.get('branch'))).first()
    except (TypeError, ValueError):
        branch = None
    if not branch:
        return Response({'detail': 'الفرع مطلوب.'}, status=status.HTTP_400_BAD_REQUEST)
    token = _valid_uuid(request.data.get('cart_token'))
    events = request.data.get('events') or []
    if not isinstance(events, list):
        return Response({'detail': 'events must be a list.'}, status=status.HTTP_400_BAD_REQUEST)

    def _d(v):
        try:
            return Decimal(str(v or 0))
        except (InvalidOperation, TypeError, ValueError):
            return Decimal('0')

    objs = []
    for e in events[:200]:                      # hard cap per request
        code = str(e.get('item_code') or '').strip()[:6]
        if not code:
            continue
        occ = parse_datetime(e.get('occurred_at') or '') or timezone.now()
        et = e.get('event_type')
        objs.append(PosSelectionEvent(
            cart_token=token, branch=branch, softech_branchcode=(branch.softech_branch_id or '')[:5],
            doc_kind=('return' if e.get('doc_kind') == 'return' else 'sale'),
            event_type=(PosSelectionEvent.EVENT_CLEAR if et == 'clear' else PosSelectionEvent.EVENT_ADD),
            item_id=(e.get('item') or None), item_code=code, item_name=str(e.get('item_name') or '')[:120],
            itemsaleprice=_d(e.get('itemsaleprice')), transprice=_d(e.get('transprice')),
            transqty=_d(e.get('transqty')), transprice_total=_d(e.get('transprice_total')),
            custcode=str(e.get('custcode') or '')[:8], seller_usercode=seller,
            occurred_at=occ, created_by=sp,
        ))
    if objs:
        PosSelectionEvent.objects.bulk_create(objs, batch_size=200)
    return Response({'captured': len(objs)}, status=status.HTTP_202_ACCEPTED)


# Prescription image upload limits (PG-only — this is OUR metadata, not a SOFTECH write).
_RX_MAX_BYTES = 12 * 1024 * 1024
_RX_TYPES = {'image/jpeg', 'image/png', 'image/webp', 'image/heic', 'image/heif'}


@api_view(['POST'])
@permission_classes([CanOperatePosOrders])
@parser_classes([MultiPartParser, FormParser])
def upload_prescription(request, pk):
    """
    Attach a prescription image to a POS order (multipart). PG-only metadata — never the
    SOFTECH write path. Foundation for OCR-Rx (Phase C): the stored image is what an OCR
    pass reads. Field name: `prescription_image` (or `file`).
    """
    try:
        order = SoftechSalesOrder.objects.get(pk=pk)
    except SoftechSalesOrder.DoesNotExist:
        return Response({'detail': 'أمر غير موجود'}, status=status.HTTP_404_NOT_FOUND)
    if order.is_locked:
        return Response({'detail': 'الأمر مقفل — لا يمكن تعديله.'}, status=status.HTTP_409_CONFLICT)
    f = request.FILES.get('prescription_image') or request.FILES.get('file')
    if not f:
        return Response({'detail': 'لم تُرفق صورة.'}, status=status.HTTP_400_BAD_REQUEST)
    if f.size > _RX_MAX_BYTES:
        return Response({'detail': 'حجم الصورة يتجاوز الحد المسموح (12 ميجابايت).'},
                        status=status.HTTP_400_BAD_REQUEST)
    if getattr(f, 'content_type', None) and f.content_type not in _RX_TYPES:
        return Response({'detail': 'نوع الملف غير مدعوم — استخدم صورة (JPEG/PNG/WebP).'},
                        status=status.HTTP_400_BAD_REQUEST)
    order.prescription_image = f
    order.save(update_fields=['prescription_image'])
    return Response({'prescription_image': order.prescription_image.url if order.prescription_image else None})


@api_view(['POST'])
@permission_classes([CanOperatePosOrders])
@parser_classes([MultiPartParser, FormParser])
def prescription_ocr(request):
    """
    Stateless OCR-Rx: a prescription image → Gemini drug-name reading → catalog matches.
    Returns, per written line, CANDIDATE items (n-best) for the cashier to CONFIRM — never
    auto-added (pharmacy safety wins, rule 4/10). No order, no SOFTECH. Reuses the shortage
    OCR + item-matching flywheel.
    """
    import os
    f = request.FILES.get('image') or request.FILES.get('prescription_image') or request.FILES.get('file')
    if not f:
        return Response({'detail': 'لم تُرفق صورة.'}, status=status.HTTP_400_BAD_REQUEST)
    if f.size > _RX_MAX_BYTES:
        return Response({'detail': 'حجم الصورة يتجاوز الحد المسموح (12 ميجابايت).'}, status=status.HTTP_400_BAD_REQUEST)
    if getattr(f, 'content_type', None) and f.content_type not in _RX_TYPES:
        return Response({'detail': 'نوع الملف غير مدعوم — استخدم صورة.'}, status=status.HTTP_400_BAD_REQUEST)

    # P2: run ALL engines in parallel (Gemini + in-house EasyOCR/Tesseract), ensemble the
    # readings (catalog arbitrates + consensus boost), and bank per-engine for the metrics.
    from apps.vision.ocr import run_engines, pick_primary, build_consensus
    api_key = getattr(settings, 'GOOGLE_API_KEY', '') or os.environ.get('GOOGLE_API_KEY', '')
    engine_readings = run_engines(f, api_key=api_key)
    engine, primary = pick_primary(engine_readings)
    if not primary:
        return Response({'lines': [], 'detail': 'تعذّرت قراءة الصورة — جرّب صورة أوضح.'},
                        status=status.HTTP_200_OK)
    consensus = build_consensus(engine_readings)
    lines = _readings_to_candidates(primary, consensus=consensus, primary_engine=engine)
    # bank the OCR event into the in-house corpus (best-effort — never blocks)
    from apps.vision.models import record_sample
    try:
        f.seek(0)
    except Exception:
        pass
    sample = record_sample(module='pos_rx', media_type='image', engine=(engine or 'gemini'), image=f,
                           raw_readings=primary, user=request.user,
                           branch=_branch_of(request), source_ref=request.data.get('source_ref', ''))
    if sample:   # store per-engine readings for the accuracy comparison
        try:
            sample.engine_readings = engine_readings
            sample.save(update_fields=['engine_readings'])
        except Exception:
            pass
    return Response({'engine': engine, 'engines': sorted(engine_readings.keys()),
                     'sample_id': getattr(sample, 'id', None), 'lines': lines})


def _readings_to_candidates(readings, consensus=None, primary_engine=''):
    """Shared: n-best drug readings → ranked catalog candidates (OCR + voice both use this).
    Runs find_best_matches per reading, unions by item keeping the best score, top-3.
    ENSEMBLE: when `consensus` (item_id → engines) is given, an item several engines agree
    on is boosted and tagged with the agreeing engines — the catalog is the arbiter."""
    from apps.shortage.matching import find_best_matches
    consensus = consensus or {}
    out = []
    for r in readings:
        reads = r.get('readings') or []
        strength = (r.get('strength') or '').strip()
        seen = {}
        for reading in reads[:3]:
            for m in find_best_matches((str(reading) + ' ' + strength).strip(), top_n=3):
                iid = m['item_id']
                if iid not in seen or m['score'] > seen[iid]['score']:
                    seen[iid] = m
        cands = []
        for m in seen.values():
            iid = m['item_id']
            engs = consensus.get(iid) or ([primary_engine] if primary_engine else [])
            boost = 1 + 0.15 * max(0, len(engs) - 1)   # consensus across engines ranks up
            cands.append({
                'item_id': iid, 'softech_id': m['item_softech_id'],
                'name': m['item_name'], 'scientific': m.get('item_scientific') or '',
                'pack_price': float(m['item_sale_price'] or 0),
                'score': round(float(m['score']) * boost, 3), 'learned': bool(m.get('learned')),
                'engines': engs,
            })
        cands.sort(key=lambda c: -c['score'])
        out.append({
            'readings': [str(x) for x in reads],
            'strength': strength,
            'qty': r.get('qty'),
            'candidates': cands[:3],
        })
    return out


_AUDIO_MAX_BYTES = 20 * 1024 * 1024
_VOICE_ITEMS_PROMPT = (
    'Audio of an Egyptian pharmacy customer (Arabic, English, or mixed) naming the medicines '
    'they want. Return STRICT JSON ONLY: {"lines":[{"readings":[...],"strength":"...","qty":number-or-null}]}\n'
    '- one object per distinct medicine mentioned, in order.\n'
    '- "readings": 1-3 plausible REAL medication names (Egyptian/international market), most-likely first.\n'
    '- "strength": dosage/pack if said (e.g. "10mg","500"), else "".\n'
    '- "qty": the number said next to it, else null.\n'
    '- Keep Arabic names in Arabic, English in Latin; do NOT translate. Ignore greetings/chit-chat.'
)


def _voice_items_gemini(audio_bytes, mime_type, api_key):
    """Audio → structured drug readings (same shape as _ocr_gemini's readings). [] on failure."""
    import json as _json
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        return []
    client = genai.Client(api_key=api_key) if api_key else genai.Client()
    part = types.Part.from_bytes(data=audio_bytes, mime_type=mime_type or 'audio/webm')
    for model in ('gemini-2.5-flash', 'gemini-2.0-flash', 'gemini-flash-latest'):
        try:
            resp = client.models.generate_content(
                model=model, contents=[part, types.Part.from_text(text=_VOICE_ITEMS_PROMPT)],
                config=types.GenerateContentConfig(response_mime_type='application/json'))
            data = _json.loads(resp.text)
            readings = []
            for ln in (data.get('lines') or []):
                reads = [str(x).strip() for x in (ln.get('readings') or []) if str(x).strip()]
                if reads:
                    readings.append({'readings': reads, 'strength': str(ln.get('strength') or '').strip(),
                                     'qty': ln.get('qty')})
            if readings:
                return readings
        except Exception:
            continue
    return []


@api_view(['POST'])
@permission_classes([CanOperatePosOrders])
@parser_classes([MultiPartParser, FormParser])
def voice_entry(request):
    """
    Voice item entry: an audio clip of the customer naming medicines → drug readings →
    catalog candidates for the cashier to CONFIRM (never auto-added — rule 4/10). No order,
    no SOFTECH. Reuses the same matching flywheel as OCR-Rx.
    """
    import os
    f = request.FILES.get('audio') or request.FILES.get('file')
    if not f:
        return Response({'detail': 'لم يُرفق تسجيل صوتي.'}, status=status.HTTP_400_BAD_REQUEST)
    if f.size > _AUDIO_MAX_BYTES:
        return Response({'detail': 'حجم التسجيل يتجاوز الحد المسموح.'}, status=status.HTTP_400_BAD_REQUEST)
    api_key = getattr(settings, 'GOOGLE_API_KEY', '') or os.environ.get('GOOGLE_API_KEY', '')
    audio_bytes = f.read()
    readings = _voice_items_gemini(audio_bytes, getattr(f, 'content_type', '') or 'audio/webm', api_key)
    if not readings:
        return Response({'lines': [], 'detail': 'لم أفهم الأصناف — جرّب النطق بوضوح.'}, status=status.HTTP_200_OK)
    # bank the voice event into the in-house corpus (best-effort)
    from django.core.files.base import ContentFile
    from apps.vision.models import record_sample
    sample = record_sample(module='pos_voice', media_type='audio', engine='gemini',
                           audio=ContentFile(audio_bytes, name=getattr(f, 'name', 'voice.webm') or 'voice.webm'),
                           raw_readings=readings, user=request.user, branch=_branch_of(request),
                           source_ref=request.data.get('source_ref', ''))
    return Response({'sample_id': getattr(sample, 'id', None), 'lines': _readings_to_candidates(readings)})


@api_view(['POST'])
@permission_classes([CanOperatePosOrders])
def prescription_ocr_teach(request):
    """
    Flywheel: when the cashier CONFIRMS a candidate for a raw OCR reading, teach the
    alias so the exact reading resolves instantly next time (learn_alias). PG-only.
    Body: { raw_name, item_id }.
    """
    from apps.catalog.models import Item
    from apps.shortage.matching import learn_alias
    raw = (request.data.get('raw_name') or '').strip()
    item = Item.objects.filter(pk=request.data.get('item_id')).first()
    if not raw or not item:
        return Response({'detail': 'raw_name و item_id مطلوبان.'}, status=status.HTTP_400_BAD_REQUEST)
    try:
        # learn the chosen item; if the cashier picked another than the machine's first
        # suggestion, that suggestion is remembered as rejected for this reading
        from apps.shortage.learning import learn_correction
        learn_correction(raw, suggested=request.data.get('suggested_item_id') or None,
                         chosen=[item], source='pos_rx_ocr')
    except Exception:
        pass   # teaching is best-effort — never fail the flow
    # record the ground truth onto the OCR/voice corpus sample (best-effort)
    from apps.vision.models import add_confirmation
    add_confirmation(request.data.get('sample_id'), reading=raw, item=item)
    return Response({'taught': True, 'softech_id': item.softech_id})


# Sales counted as a real referral (a committed / posted sale, not a draft or cancellation).
_REFERRAL_STATUSES = (SoftechSalesOrder.STATUS_QUEUED, SoftechSalesOrder.STATUS_PUSHED,
                      SoftechSalesOrder.STATUS_SETTLED)


@api_view(['GET'])
@permission_classes([CanOperatePosOrders])
def referral_stats(request):
    """
    Referring-doctor performance: committed POS sales grouped by referral doctor →
    orders, total net value, distinct patients, last referral. Filters: from / to
    (doc_date), branch. PG-only report.
    """
    from django.db.models import Count, Sum, Max
    qs = (SoftechSalesOrder.objects
          .filter(status__in=_REFERRAL_STATUSES)
          .exclude(referral_doctor_name='', referral_doctor_code=''))
    frm, to, br = (request.query_params.get(k) for k in ('from', 'to', 'branch'))
    if frm:
        qs = qs.filter(doc_date__gte=frm)
    if to:
        qs = qs.filter(doc_date__lte=to)
    if br and str(br).isdigit():
        qs = qs.filter(branch_id=int(br))
    rows = (qs.values('referral_doctor_code', 'referral_doctor_name')
            .annotate(orders=Count('id'), total_net=Sum('doc_value'),
                      patients=Count('softech_pic', distinct=True), last_referral=Max('doc_date'))
            .order_by('-orders', '-total_net'))
    results = [{
        'doctor_code': r['referral_doctor_code'] or '',
        'doctor_name': r['referral_doctor_name'] or '(بدون اسم)',
        'orders': r['orders'],
        'total_net': float(r['total_net'] or 0),
        'patients': r['patients'],
        'last_referral': r['last_referral'].isoformat() if r['last_referral'] else None,
    } for r in rows]
    return Response({
        'results': results,
        'summary': {
            'doctors': len(results),
            'orders': sum(x['orders'] for x in results),
            'total_net': round(sum(x['total_net'] for x in results), 2),
        },
    })


@api_view(['GET'])
@permission_classes([CanOperatePosOrders])
def batch_availability_view(request):
    """
    Live per-batch stock for the POS batch-pick modal.
    GET ?branch=<id>&item=<softech_itemcode>[&store=<storecode>]
    Returns the available batches (expiry/qty) + a summary; out_of_stock ⇒ reservation.
    """
    from apps.branches.models import Branch
    from .batch_availability import item_availability, summarize, batch_action
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
        batches, stockable = item_availability(branch.effective_db_host, store, item,
                                               branch.effective_db_port, branch.db_name or 'SOFTECHDB9')
    except Exception as e:
        return Response({'detail': f'تعذّر قراءة الأرصدة: {e}'}, status=status.HTTP_502_BAD_GATEWAY)
    # SOFTECH items.itempartno «رقم القطعة أو الباتش» (synced to catalog.Item.batch_required):
    # authoritative "batch selection is mandatory" flag, returned so every POS add-path (favorites,
    # barcode, repeat — not just item search) drives the batch matrix correctly.
    from apps.catalog.models import Item
    batch_required = Item.objects.filter(softech_id=item).values_list('batch_required', flat=True).first()
    # authoritative batch matrix (CASE 1-5) decided server-side; the POS enforces this verdict.
    verdict = batch_action(batches, batch_required=bool(batch_required), stockable=stockable)
    # non-stockable (service/fee) items: NOT out-of-stock — a plain line, never a reservation.
    return Response({'item': item, 'store': store, 'stockable': stockable, 'batches': batches,
                     'batch_required': bool(batch_required),
                     'batch_action': verdict['action'], **summarize(batches)})


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
    """نوع العميل — the POS customer-type list (type → channel + discount source),
    filtered to the channels THIS staff member may operate (server-side RBAC)."""
    from .customer_directory import POS_CUSTOMER_TYPES
    sp = _staff(request.user)
    types = POS_CUSTOMER_TYPES
    if sp:
        types = [t for t in types if sp.can_pos_channel(t.get('channel'))]
    return Response({'types': types})


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


def _exception_row(o, now):
    """Compact, read-only view of one order for the Exception Center (no lines/payload dump)."""
    from apps.pos_orders.models import SoftechSalesOrder as _S
    # age = minutes since the event that stalled it (push time if pushed, else last update)
    anchor = o.erp_executed_at or o.updated_at or o.created_at
    age_min = int((now - anchor).total_seconds() // 60) if anchor else None
    err = (o.erp_error or '').strip()
    return {
        'id': o.pk,
        'status': o.status,
        'status_display': o.get_status_display(),
        'doc_kind': o.doc_kind,
        'branch': o.branch_id,
        'branch_name': (o.branch.name_ar or o.branch.name) if o.branch_id else '',
        'customer': o.softech_pic or o.customer_name or '',
        'channel': o.channel,
        'doc_value': float(o.doc_value or 0),
        'softech_docnumber': int(o.softech_docnumber) if o.softech_docnumber else None,
        'seller_usercode': o.seller_usercode or '',
        'created_at': o.created_at.isoformat() if o.created_at else None,
        'updated_at': o.updated_at.isoformat() if o.updated_at else None,
        'erp_executed_at': o.erp_executed_at.isoformat() if o.erp_executed_at else None,
        'age_min': age_min,
        'error': (err[:280] + '…') if len(err) > 280 else err,
        'needs_review': bool(o.needs_review),
        'review_reason': o.review_reason or '',
    }


def exception_buckets(qs, now, queued_stale=10, pushing_stale=5, pushed_stale=120):
    """Pure bucketing of POS-order exceptions (Wave 8) — decoupled from HTTP so it is unit-testable.
    `qs` is a SoftechSalesOrder queryset (optionally branch-filtered); `now` an aware datetime.
    Staleness thresholds are in minutes. Returns the list of bucket dicts (count / value / orders)."""
    from django.db.models import Count, Sum
    from datetime import timedelta
    S = SoftechSalesOrder
    specs = [
        # reconcile.py flagged: pending rows vanished with no final doc (possible silent cashier
        # Delete or lookup miss) — the sharpest leakage signal, so it leads and is its own bucket.
        ('leakage', 'اختفى بلا فاتورة نهائية (خطر تسرّب)', 'error',
         qs.filter(needs_review=True)),
        ('push_failed', 'فشل الإرسال', 'error',
         qs.filter(status=S.STATUS_PUSH_FAILED)),
        ('stuck_pushing', 'متوقف أثناء الإرسال', 'error',
         qs.filter(status=S.STATUS_PUSHING, updated_at__lt=now - timedelta(minutes=pushing_stale))),
        ('stuck_queued', 'عالق في الطابور (انقطاع الاتصال)', 'warn',
         qs.filter(status=S.STATUS_QUEUED, updated_at__lt=now - timedelta(minutes=queued_stale))),
        # exclude already-flagged (leakage) orders so they are not counted twice.
        ('awaiting_cashier', 'بانتظار الكاشير (متأخر)', 'warn',
         qs.filter(status=S.STATUS_PUSHED, needs_review=False,
                   erp_executed_at__lt=now - timedelta(minutes=pushed_stale))),
    ]
    buckets = []
    for key, label, severity, bqs in specs:
        bqs = bqs.order_by('created_at')
        agg = bqs.aggregate(c=Count('id'), v=Sum('doc_value'))
        buckets.append({
            'key': key, 'label': label, 'severity': severity,
            'count': agg['c'] or 0,
            'value_at_risk': round(float(agg['v'] or 0), 2),
            'orders': [_exception_row(o, now) for o in bqs[:200]],
        })
    return buckets


@api_view(['GET'])
@permission_classes([CanOperatePosOrders])
def exceptions_view(request):
    """POS-order Exception Center — a read-only aggregator (Wave 8) that buckets the orders needing
    a human: push failures, orders orphaned mid-push, orders stuck waiting on connectivity, and
    pushed orders sitting too long awaiting the cashier (settlement / leakage risk). Reuses the
    existing order model + status lifecycle; it NEVER writes to SOFTECH and NEVER mutates a status —
    the manager acts via the existing gated flush / cancel / push endpoints.
    Query: ?branch=<id> &queued_stale_min= &pushing_stale_min= &pushed_stale_min=."""
    from django.utils import timezone
    now = timezone.now()

    def _mins(key, default):
        try:
            return max(0, int(request.query_params.get(key, default)))
        except (TypeError, ValueError):
            return default
    queued_stale  = _mins('queued_stale_min', 10)
    pushing_stale = _mins('pushing_stale_min', 5)
    pushed_stale  = _mins('pushed_stale_min', 120)

    qs = SoftechSalesOrder.objects.select_related('branch')
    branch = request.query_params.get('branch')
    if branch:
        qs = qs.filter(branch_id=branch)

    buckets = exception_buckets(qs, now, queued_stale, pushing_stale, pushed_stale)
    return Response({
        'generated_at': now.isoformat(),
        'writer_enabled': writer.writer_enabled(),
        'thresholds': {'queued_stale_min': queued_stale,
                       'pushing_stale_min': pushing_stale,
                       'pushed_stale_min': pushed_stale},
        'total_count': sum(b['count'] for b in buckets),
        'total_value_at_risk': round(sum(b['value_at_risk'] for b in buckets), 2),
        'buckets': buckets,
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
        'can_edit_contract_discount': _can_edit_contract_discount(sp),
        # None = all channels; else the explicit allow-list this member may operate
        'allowed_channels': (sorted(sp.pos_channels()) if (sp and sp.pos_channels() is not None) else None),
        'default_branch': (sp.branch_id if sp and sp.branch_id else None),   # auto-select the seller's branch
        'note': 'SOFTECH writes are disabled (no test instance). /push returns a dry-run plan.',
    })
