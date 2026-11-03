"""
Public (no login) counselling card page — /api/public/counsel/<token>/ (listed in
apps/access/public_paths.py under /api/public/ and in the security test's KNOWN_PUBLIC_VIEWS).

The token is a signed send id (cards.TOKEN_SALT), valid COUNSEL_CARD_TOKEN_DAYS. The page shows the
customer's first name, the branch and, per item, the pinned APPROVED sheet; if the pharmacist has
since re-approved it the current approved text («تم تحديث»), if withdrawn a notice and no text.
Never a phone number, customer id, staff name or price. Drafts are never shown.
"""
from django.conf import settings
from django.core import signing
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle

from apps.audit.models import AuditLog

from .cards import TOKEN_SALT
from .models import CounselCardOptOut, CounselCardSend

_GONE = {'detail': 'الرابط غير صالح أو منتهي الصلاحية'}


class PublicCounselThrottle(AnonRateThrottle):
    """Per-IP cap on the anonymous counselling link (tokens are signed; this stops enumeration)."""
    scope = 'public_counsel'
    rate = '600/hour'


def _send_from(token):
    try:
        data = signing.loads(str(token), salt=TOKEN_SALT,
                             max_age=int(getattr(settings, 'COUNSEL_CARD_TOKEN_DAYS', 90)) * 86400)
    except (signing.BadSignature, ValueError, TypeError):
        return None
    sid = data.get('s') if isinstance(data, dict) else None
    if not isinstance(sid, int):
        return None
    return (CounselCardSend.objects.select_related('branch')
            .filter(pk=sid, status='sent').first())


def _line(l):
    c = l.content
    if c.status == 'retired' or c.approved_version_id is None or not c.links.filter(item_id=l.item_id).exists():
        return {'name': l.item.name, 'withdrawn': True}
    current = c.approved_version
    return {'name': l.item.name, 'withdrawn': False, 'updated': current.pk != l.version_id,
            'content': current.data}


def _branch_phone(branch):
    for attr in ('phone', 'mobile', 'telephone'):
        v = getattr(branch, attr, '') if branch else ''
        if v:
            return str(v)
    return ''


@api_view(['GET'])
@authentication_classes([])          # a stale staff cookie must never 401 the public page
@permission_classes([AllowAny])
@throttle_classes([PublicCounselThrottle])
def counsel_card_public(request, token):
    send = _send_from(token)
    if send is None:
        return Response(_GONE, status=status.HTTP_404_NOT_FOUND)
    if send.first_opened_at is None:
        CounselCardSend.objects.filter(pk=send.pk, first_opened_at__isnull=True).update(
            first_opened_at=timezone.now())
    lines = send.lines.select_related('item', 'content', 'content__approved_version').order_by('id')
    return Response({
        'first_name': send.first_name,
        'branch_name': (send.branch.name_ar or send.branch.name) if send.branch else '',
        'branch_phone': _branch_phone(send.branch),
        'sent_at': send.created_at.date().isoformat(),
        'items': [_line(l) for l in lines],
    })


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_classes([PublicCounselThrottle])
def counsel_card_opt_out(request, token):
    send = _send_from(token)
    if send is None:
        return Response(_GONE, status=status.HTTP_404_NOT_FOUND)
    _, created = CounselCardOptOut.objects.get_or_create(
        phone_hash=send.phone_hash, customer=send.customer, defaults={'source': 'link'})
    if created:
        AuditLog.log('counsel_card_opt_out', obj=send, extra={'source': 'link'})
    return Response({'ok': True, 'detail': 'تم إيقاف رسائل الإرشادات'})
