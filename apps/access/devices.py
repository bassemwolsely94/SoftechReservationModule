"""
Device registry helpers (N2). The cookie value is a random secret; only its sha256 is stored.
"""
import hashlib
import secrets

from .network import INTERNAL

COOKIE = 'erp_device'
COOKIE_MAX_AGE = 400 * 24 * 3600

_MOBILE_MARKERS = ('mobile', 'iphone', 'android', 'ipad')


def new_secret():
    return secrets.token_urlsafe(32)


def hash_secret(secret):
    return hashlib.sha256(secret.encode()).hexdigest()


def from_secret(secret):
    """The device a cookie value names, or None for a missing, unknown or retired one."""
    if not secret:
        return None
    from .models import Device
    return Device.objects.filter(secret_hash=hash_secret(secret)).exclude(status='retired').first()


def guess_kind(user_agent, network):
    ua = (user_agent or '').lower()
    if any(m in ua for m in _MOBILE_MARKERS):
        return 'phone'
    site = getattr(network, 'site', None)
    if getattr(network, 'zone', None) == INTERNAL and site and site.branch_id:
        return 'branch_pc'
    return 'personal_laptop'


def snapshot(device):
    return {
        'name': device.name,
        'kind': device.kind,
        'status': device.status,
        'branch': device.branch_id,
        'owner': device.owner_id,
        'allowed_roles': list(device.allowed_roles or []),
        'status_note': device.status_note,
    }
