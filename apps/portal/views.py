"""
apps/portal/views.py

Customer self-service portal API. Two public entry points (magic-link request +
token exchange); all other endpoints require a portal session and are HARD-SCOPED
to `request.user.customer`. A customer id is never accepted from the client.
"""
from django.conf import settings
from django.core import signing
from django.db import connections, transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import (
    api_view, authentication_classes, permission_classes, throttle_classes,
)
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from core import public_guard
from core.threads import start_thread
from apps.portal.auth import IsPortalCustomer, PortalSessionAuthentication
from apps.portal.serializers import (
    AuthExchangeSerializer, ReorderSerializer, RequestLinkSerializer,
)
from apps.portal.services import (
    exchange_magic_link, find_customer_by_phone, issue_magic_link, send_magic_link,
)
from apps.portal.throttles import AuthExchangeThrottle, RequestLinkIPThrottle, RequestLinkThrottle

_GENERIC_LINK_MSG = 'إذا كان لديك حساب، فسيصلك رابط الدخول عبر واتساب.'

# Owner 2026-11-01 (Batch 6, W-5): at most this many online reorders per customer per day.
REORDER_DAILY_MAX = int(getattr(settings, 'PORTAL_REORDER_DAILY_MAX', 10))


def _mask_phone(phone: str) -> str:
    digits = ''.join(ch for ch in (phone or '') if ch.isdigit())
    if len(digits) < 4:
        return ''
    return '•••• ' + digits[-4:]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Public entry points (no session) — AllowAny + throttled
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_classes([RequestLinkThrottle, RequestLinkIPThrottle])
def request_link(request):
    """
    POST {phone} → ALWAYS 200 (never leaks whether the account exists).
    If a customer matches, mint a short-lived one-login magic link and WhatsApp it.
    """
    ser = RequestLinkSerializer(data=request.data)
    ser.is_valid(raise_exception=True)          # own fields first: a bad request never burns a slot
    phone = ser.validated_data['phone']

    # Self-hosted guard (N6). Bots and the per-phone daily cap get the same generic 200 as everyone
    # (nothing sent, nothing learnt); a stale/replayed/too-fast form is told to reload.
    try:
        public_guard.check_submission(request.data, 'portal_link',
                                      phone=public_guard.normalize_phone(phone))
    except public_guard.GuardError as e:
        if e.code in public_guard.SILENT_CODES:
            return Response({'detail': _GENERIC_LINK_MSG}, status=status.HTTP_200_OK)
        return Response({'detail': public_guard.GUARD_MESSAGES[e.code]},
                        status=status.HTTP_400_BAD_REQUEST)

    # The link is minted here; the WhatsApp send runs on a thread so a known and an unknown phone
    # answer in the same time (no timing oracle, N6 I3). A send failure is only logged.
    customer = find_customer_by_phone(phone)
    if customer is not None:
        start_thread(_send_link, args=(customer, issue_magic_link(customer)),
                     name='portal-magic-link')

    return Response({'detail': _GENERIC_LINK_MSG}, status=status.HTTP_200_OK)


def _send_link(customer, token):
    """The magic-link send, run on its own thread: the WhatsApp sender writes its log rows on this
    thread's database connection, so close it when done (send_magic_link logs its own failures)."""
    try:
        send_magic_link(customer, token)
    finally:
        connections.close_all()


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_classes([AuthExchangeThrottle])
def auth_exchange(request):
    """POST {token} (magic-link) → issue a customer-scoped session token. A link works once."""
    ser = AuthExchangeSerializer(data=request.data)
    ser.is_valid(raise_exception=True)

    spent = exchange_magic_link(ser.validated_data['token'])
    if spent is None:
        return Response(
            {'detail': 'الرابط غير صالح أو منتهي الصلاحية أو استُخدم من قبل'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    customer, session_token = spent
    return Response({
        'session_token': session_token,
        'customer': {'name': customer.name},
    })


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Session-scoped endpoints — portal auth ONLY (no staff JWT)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _portal(view):
    """Decorator stack applied to every authenticated portal endpoint."""
    view = authentication_classes([PortalSessionAuthentication])(view)
    view = permission_classes([IsPortalCustomer])(view)
    return view


@api_view(['POST'])
@_portal
def logout(request):
    """End THIS session on the server (the browser forgetting the token is not enough)."""
    request.user.login.revoke()
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['GET'])
@_portal
def me(request):
    c = request.user.customer
    tier_name, points = None, 0
    try:
        from apps.loyalty.models import LoyaltyAccount
        acct = LoyaltyAccount.objects.select_related('tier').filter(customer=c).first()
        if acct:
            points = acct.points_balance
            tier_name = acct.tier.name_ar if acct.tier_id else None
    except Exception:  # noqa: BLE001 — loyalty is optional
        pass

    return Response({
        'name': c.name,
        'phone_masked': _mask_phone(c.whatsapp_phone or c.phone),
        'segment': c.get_segment_display() if c.segment else None,
        'loyalty_tier': tier_name,
        'loyalty_points': points,
    })


@api_view(['GET'])
@_portal
def orders(request):
    """Active reservations + delivery orders (with tokenized public track links)."""
    c = request.user.customer

    from apps.reservations.models import Reservation
    reservations = (
        Reservation.objects.filter(customer=c)
        .select_related('item', 'branch')
        .order_by('-created_at')[:50]
    )
    res_out = [{
        'id': r.id,
        'item': r.item_label,
        'quantity': float(r.quantity_requested or 0),
        'status': r.status,
        'status_label': r.status_label_ar,
        'is_active': r.is_active,
        'branch': r.branch.name_ar if r.branch_id else '',
        'created_at': r.created_at,
    } for r in reservations]

    from apps.delivery.models import DeliveryOrder
    from apps.delivery.views import _TRACK_SALT
    deliveries = (
        DeliveryOrder.objects.filter(customer=c)
        .select_related('branch')
        .order_by('-created_at')[:50]
    )
    del_out = [{
        'id': d.id,
        'order_number': d.order_number,
        'status': d.status,
        'status_label': d.get_status_display(),
        'is_terminal': d.status in DeliveryOrder.TERMINAL_STATUSES,
        'branch': d.branch.name_ar if d.branch_id else '',
        'track_token': signing.dumps({'oid': d.pk}, salt=_TRACK_SALT),
        'created_at': d.created_at,
    } for d in deliveries]

    from apps.counselling.cards import token_for
    from apps.counselling.models import CounselCardSend
    cards_out = [{
        'created_at': s.created_at,
        'item_count': s.lines.count(),
        'token': token_for(s),
    } for s in CounselCardSend.objects.filter(customer=c, status='sent').order_by('-created_at')[:20]]

    return Response({'reservations': res_out, 'deliveries': del_out, 'counsel_cards': cards_out})


@api_view(['GET'])
@_portal
def loyalty(request):
    c = request.user.customer
    from apps.loyalty.models import LoyaltyAccount, PointTransaction

    acct = LoyaltyAccount.objects.select_related('tier').filter(customer=c).first()
    if acct is None:
        return Response({
            'enrolled': False,
            'points_balance': 0, 'points_lifetime': 0,
            'tier': None, 'transactions': [],
        })

    txns = (
        PointTransaction.objects.filter(account=acct)
        .order_by('-created_at')[:30]
    )
    return Response({
        'enrolled': True,
        'points_balance': acct.points_balance,
        'points_lifetime': acct.points_lifetime,
        'softech_points_balance': acct.softech_points_balance,
        'tier': ({'name': acct.tier.name_ar or acct.tier.name,
                  'icon': acct.tier.icon, 'color': acct.tier.color}
                 if acct.tier_id else None),
        'transactions': [{
            'points': t.points,
            'type': t.get_transaction_type_display(),
            'reason': t.reason,
            'balance_after': t.balance_after,
            'created_at': t.created_at,
        } for t in txns],
    })


@api_view(['GET'])
@_portal
def refills(request):
    """Chronic refill follow-up tasks due soon for this customer."""
    c = request.user.customer
    from apps.followups.models import FollowUpTask

    tasks = (
        FollowUpTask.objects.filter(customer=c, status__in=['pending', 'called'])
        .select_related('item')
        .order_by('due_date')[:50]
    )
    return Response({'refills': [{
        'id': t.id,
        'item': t.item.name if t.item_id else '',
        'item_id': t.item_id,
        'due_date': t.due_date,
        'days_until_due': t.days_until_due,
        'is_overdue': t.is_overdue,
        'task_type': t.get_task_type_display(),
    } for t in tasks]})


@api_view(['POST'])
@_portal
def reorder(request):
    """
    POST {item | manual_item_name, quantity?, notes?} → create a Reservation for
    THIS customer (order_source='online'). Branch is resolved server-side from the
    customer profile; the client cannot choose the customer or branch.
    """
    ser = ReorderSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    data = ser.validated_data
    c = request.user.customer

    # Resolve branch server-side.
    from django.core.exceptions import ImproperlyConfigured
    from apps.branches.models import Branch, hq_code
    branch = c.preferred_branch
    if branch is None or not branch.is_live:
        try:
            branch = Branch.objects.filter(softech_branch_id=hq_code()).first()
        except ImproperlyConfigured:      # no (or more than one) hq row → no branch to take it
            branch = None
    if branch is None:
        return Response(
            {'detail': 'لا يوجد فرع متاح حالياً لاستقبال الطلب'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Resolve item (catalog id) or fall back to a manual name.
    item = None
    manual_name = (data.get('manual_item_name') or '').strip()
    if data.get('item'):
        from apps.catalog.models import Item
        item = Item.objects.filter(pk=data['item']).first()
        if item is None and not manual_name:
            return Response(
                {'detail': 'الصنف غير موجود'},
                status=status.HTTP_400_BAD_REQUEST,
            )

    from apps.customers.models import Customer
    from apps.reservations.models import Reservation
    with transaction.atomic():
        Customer.objects.select_for_update().filter(pk=c.pk).first()     # one reorder at a time
        start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
        if Reservation.objects.filter(customer=c, order_source='online',
                                      created_at__gte=start).count() >= REORDER_DAILY_MAX:
            return Response(
                {'detail': f'وصلت للحد اليومي ({REORDER_DAILY_MAX} طلبات) — اتصل بالفرع لأي طلب إضافي'},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        reservation = Reservation.objects.create(
            customer=c,
            item=item,
            manual_item_name='' if item else manual_name,
            branch=branch,
            quantity_requested=data.get('quantity') or 1,
            status='pending',
            order_source='online',
            contact_name=c.name or '',
            contact_phone=(c.whatsapp_phone or c.phone or ''),
            notes=(data.get('notes') or '').strip(),
        )

    from apps.notifications.phone_alerts import hooks as phone_alert_hooks
    phone_alert_hooks.on_reservation_created(reservation)

    return Response({
        'id': reservation.id,
        'status': reservation.status,
        'item': reservation.item_label,
        'branch': branch.name_ar,
        'detail': 'تم استلام طلبك وسيتواصل معك الفريق قريباً',
    }, status=status.HTTP_201_CREATED)
