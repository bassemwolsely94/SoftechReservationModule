"""How the attended Windows RPA agent signs in (modelled on apps/hr/attendance/agent_auth.py).

Each device belongs to one staff operator and sends its own secret in a header. Only the secret's
SHA-256 is stored, the lookup is on the hash and compared in constant time, and revoking a device
ends access. Unlike the attendance agent, the request runs AS the operator (request.user), so the
rpa module matrix and the "own jobs only" rule apply to the person sitting at that PC.
"""
import hashlib
import hmac
import secrets

from django.utils import timezone
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import BasePermission

from apps.audit.models import AuditLog

from .models import RpaDevice

HEADER = 'X-ElR-RPA-Agent'
_META_KEY = 'HTTP_X_ELR_RPA_AGENT'


def _as_bytes(value) -> bytes:
    return str(value).encode('utf-8', 'surrogateescape')


def hash_secret(secret) -> str:
    return hashlib.sha256(_as_bytes(secret)).hexdigest()


def device_for_secret(secret):
    """The unrevoked device holding this secret, or None."""
    if not secret:
        return None
    digest = hash_secret(secret)
    device = (RpaDevice.objects.select_related('staff__user')
              .filter(token_hash=digest, revoked_at__isnull=True).first())
    # The equality lookup on the hash is the real check; this compare repeats it in constant time
    # as a guard against a collation/normalising lookup ever matching a different string.
    if device is None or not hmac.compare_digest(_as_bytes(device.token_hash), _as_bytes(digest)):
        return None
    return device


def issue_device(*, staff, label, created_by):
    """Create a device for `staff`. Returns (device, secret); the secret cannot be read back later."""
    secret = secrets.token_urlsafe(32)
    device = RpaDevice.objects.create(staff=staff, label=str(label)[:120], token_hash=hash_secret(secret),
                                      created_by=created_by)
    AuditLog.log('rpa_device_issued', user=created_by, obj=device,
                 new_data={'label': device.label, 'staff_id': staff.pk},
                 note=f'إصدار جهاز روبوت لـ {staff.full_name}')
    return device, secret


class RpaDeviceAuthentication(BaseAuthentication):
    """request.user = the device's operator, request.auth = the RpaDevice."""

    def authenticate(self, request):
        sent = request.META.get(_META_KEY)
        if not sent:
            return None
        device = device_for_secret(sent)
        if device is None:
            raise AuthenticationFailed('غير مصرح')
        profile, user = device.staff, device.staff.user
        if not (profile.is_active and user.is_active):
            raise AuthenticationFailed('غير مصرح')
        RpaDevice.objects.filter(pk=device.pk).update(last_seen_at=timezone.now())
        return user, device

    def authenticate_header(self, request):
        return HEADER   # a missing secret is a 401, not a 403


class HasRpaDevice(BasePermission):

    def has_permission(self, request, view):
        return isinstance(request.auth, RpaDevice)
