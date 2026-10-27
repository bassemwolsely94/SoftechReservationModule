"""
apps/portal/views.py

Customer self-service portal API. Two public entry points (magic-link request +
token exchange); all other endpoints require a portal session and are HARD-SCOPED
to `request.user.customer`. A customer id is never accepted from the client.
"""
from django.core import signing
from rest_framework import status
from rest_framework.decorators import (
    api_view, authentication_classes, permission_classes, throttle_classes,
)
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.portal.auth import IsPortalCustomer, PortalSessionAuthentication
from apps.portal.serializers import (
    AuthExchangeSerializer, ReorderSerializer, RequestLinkSerializer,
)
from apps.portal.services import find_customer_by_phone, send_magic_link
from apps.portal.throttles import AuthExchangeThrottle, RequestLinkThrottle
from apps.portal.tokens import make_magic_token, make_session_token, read_magic_token

_GENERIC_LINK_MSG = 'إذا كان لديك حساب، فسيصلك رابط الدخول عبر واتساب.'


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
@throttle_classes([RequestLinkThrottle])
def request_link(request):
    """
    POST {phone} → ALWAYS 200 (never leaks whether the account exists).
    If a customer matches, mint a short-lived magic token and WhatsApp the link.
    """
    ser = RequestLinkSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    phone = ser.validated_data['phone']

    customer = find_customer_by_phone(phone)
    if customer is not None:
        token = make_magic_token(customer.softech_pic)
        send_magic_link(customer, token)

    return Response({'detail': _GENERIC_LINK_MSG}, status=status.HTTP_200_OK)


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_classes([AuthExchangeThrottle])
def auth_exchange(request):
    """POST {token} (magic-link) → issue a customer-scoped session token."""
    ser = AuthExchangeSerializer(data=request.data)
    ser.is_valid(raise_exception=True)

    pic = read_magic_token(ser.validated_data['token'])
    if not pic:
        return Response(
            {'detail': 'الرابط غير صالح أو منتهي الصلاحية'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    from apps.customers.models import Customer
    customer = Customer.objects.filter(softech_pic=pic).first()
    if customer is None:
        return Response(
            {'detail': 'الحساب غير موجود'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    return Response({
        'session_token': make_session_token(pic),
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

    return Response({'reservations': res_out, 'deliveries': del_out})


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
    from apps.branches.models import Branch
    branch = c.preferred_branch
    if branch is None or not branch.is_active:
        branch = Branch.objects.filter(is_active=True).order_by('id').first()
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

    from apps.reservations.models import Reservation
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

    return Response({
        'id': reservation.id,
        'status': reservation.status,
        'item': reservation.item_label,
        'branch': branch.name_ar,
        'detail': 'تم استلام طلبك وسيتواصل معك الفريق قريباً',
    }, status=status.HTTP_201_CREATED)
