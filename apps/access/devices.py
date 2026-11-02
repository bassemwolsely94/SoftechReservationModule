"""
Device registry helpers (N2). The cookie value is a random secret; only its sha256 is stored.
"""
import hashlib
import logging
import secrets
from dataclasses import dataclass

from django.core.cache import cache

from .network import INTERNAL

logger = logging.getLogger('elrezeiky.access')

COOKIE = 'erp_device'
COOKIE_MAX_AGE = 400 * 24 * 3600
DEVICE_CACHE_SECONDS = 60
TOUCH_SECONDS = 600
BLOCKED_MESSAGE = 'هذا الجهاز موقوف — تواصل مع المدير'

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


# -- Enrollment at sign-in (N2) -------------------------------------------------------

_BROWSERS = (('edg/', 'Edge'), ('opr/', 'Opera'), ('firefox', 'Firefox'), ('chrome', 'Chrome'),
             ('safari', 'Safari'))
_SYSTEMS = (('iphone', 'iPhone'), ('ipad', 'iPad'), ('android', 'Android'), ('windows', 'Windows'),
            ('mac os', 'Mac'), ('macintosh', 'Mac'), ('linux', 'Linux'))


def ua_short(user_agent):
    """A short browser + OS phrase from a User-Agent ('متصفح' when nothing is recognised)."""
    ua = (user_agent or '').lower()
    browser = next((label for key, label in _BROWSERS if key in ua), '')
    system = next((label for key, label in _SYSTEMS if key in ua), '')
    return ' '.join(p for p in (browser, system) if p) or 'متصفح'


def _network(request):
    from .network import request_network
    acc = getattr(request, 'access', None)
    return acc.network if acc else request_network(request)


def enroll(request, profile):
    """Resolve or create the device of this browser and record the sign-in on it.

    Returns (device, new_secret_or_None, created). Never raises: on error it logs a warning and
    returns (None, None, False), and the sign-in goes on without a device.
    Only the SPA enrols (its requests carry X-Requested-With: XMLHttpRequest): scripts and
    body-token clients get no device and no `dev` claim (N2 final wave, I-3)."""
    try:
        if (request.META.get('HTTP_X_REQUESTED_WITH') or '') != 'XMLHttpRequest':
            return None, None, False
        from django.db import transaction
        from django.utils import timezone
        from .models import Device, DeviceUser
        net = _network(request)
        user_agent = (request.META.get('HTTP_USER_AGENT') or '')[:300]
        now = timezone.now()
        with transaction.atomic():
            device = from_secret(request.COOKIES.get(COOKIE))
            secret, created = None, False
            site_name = net.site.name if net.site else ''
            if device is None:
                secret = new_secret()
                created = True
                who = profile.full_name or profile.user.username
                name = f'{ua_short(user_agent)} — {who}'[:120]
                internal_branch = net.site.branch_id if (net.zone == INTERNAL and net.site) else None
                device = Device.objects.create(
                    secret_hash=hash_secret(secret), name=name,
                    kind=guess_kind(user_agent, net), status='pending',
                    branch_id=internal_branch or profile.branch_id, owner=profile,
                    first_ip=net.ip, first_network=net.zone,
                )
            device.last_ip = net.ip
            device.last_network = net.zone
            device.last_site = site_name[:120]
            device.last_seen = now
            device.user_agent = user_agent
            device.save(update_fields=['last_ip', 'last_network', 'last_site', 'last_seen', 'user_agent'])
            link, _ = DeviceUser.objects.get_or_create(device=device, user=profile)
            link.last_seen = now
            link.save(update_fields=['last_seen'])
        if created:
            # after commit, so a rolled-back sign-in sends nothing and a slow push never holds the txn
            transaction.on_commit(lambda: notify_new_device(device, profile, net))
        return device, secret, created
    except Exception as exc:
        logger.warning('device enroll skipped: %s', exc)
        return None, None, False


MFA_REMEMBER_DAYS = 30


def remember_mfa(device, profile):
    """Remember a completed 2FA on this device for the profile. Only an APPROVED device earns a
    remember (a pending one never skips 2FA, nor inherits it when approved later). Never raises."""
    if device is None or device.status != 'approved':
        return
    try:
        from django.utils import timezone
        from .models import DeviceUser
        link, _ = DeviceUser.objects.get_or_create(device=device, user=profile)
        link.mfa_remembered_at = timezone.now()
        from apps.users.mfa import _device_fingerprint
        link.mfa_remembered_epoch = profile.mfa_device_epoch or 0    # informational: the fingerprint carries the epoch, this column is not read back
        link.mfa_remembered_fp = _device_fingerprint(profile.user)
        link.save(update_fields=['mfa_remembered_at', 'mfa_remembered_epoch', 'mfa_remembered_fp'])
    except Exception as exc:
        logger.warning('remember_mfa skipped: %s', exc)


def mfa_remembered(request, profile):
    """True when the request's cookie device is approved and 2FA was remembered on it for this
    profile within 30 days and at the current device epoch. Never raises."""
    try:
        from datetime import timedelta
        from django.utils import timezone
        from .models import DeviceUser
        device = from_secret(request.COOKIES.get(COOKIE))
        if device is None or device.status != 'approved':
            return False
        link = DeviceUser.objects.filter(device=device, user=profile).first()
        if link is None or link.mfa_remembered_at is None:
            return False
        age = timezone.now() - link.mfa_remembered_at
        if age < timedelta(0) or age > timedelta(days=MFA_REMEMBER_DAYS):
            return False
        from apps.users.mfa import _device_fingerprint     # password + 2FA secret + epoch
        return bool(link.mfa_remembered_fp) and link.mfa_remembered_fp == _device_fingerprint(profile.user)
    except Exception as exc:
        logger.debug('mfa_remembered skipped: %s', exc)
        return False


def notify_new_device(device, profile, net=None):
    """Alert the user (every new device) and the active admins (one digest per hour, not one per
    device). Each recipient is tried on its own. Never raises."""
    try:
        from django.utils import timezone
        from apps.notifications.models import Notification
        from apps.users.models import StaffProfile
        from .models import Device
        label = net.label_ar if net is not None else ''
        title = '💻 جهاز جديد بانتظار الاعتماد'
        body = (f'{profile.full_name or profile.user.username} — {device.name}'
                + (f' — {label}' if label else ''))
        try:
            Notification.send_to_user(profile, 'system', title, body, dedup_key=f'device_new_{device.pk}')
        except Exception as exc:
            logger.warning('device alert to user %s failed: %s', profile.pk, exc)
        pending = Device.objects.filter(status='pending').count()
        hour = timezone.now().strftime('%Y%m%d%H')
        digest = f'أجهزة جديدة بانتظار الاعتماد: {pending} — افتح /access/devices'
        for admin in StaffProfile.objects.filter(role='admin', is_active=True).exclude(pk=profile.pk):
            try:
                Notification.send_to_user(admin, 'system', '💻 أجهزة جديدة بانتظار الاعتماد', digest,
                                          dedup_key=f'device_digest_{hour}', dedup_once=True)
            except Exception as exc:
                logger.warning('device digest to admin %s failed: %s', admin.pk, exc)
    except Exception as exc:
        logger.warning('notify_new_device skipped: %s', exc)


# -- Resolving the device of a request (N2) ---------------------------------------------

@dataclass(frozen=True)
class DeviceInfo:
    public_id: str
    status: str
    name: str
    kind: str


_NONE = 'none'      # cached "no such device", so an unknown cookie costs no query either


def _client_ip(request):
    try:
        from core.client_ip import client_ip
        return client_ip(request)
    except Exception:
        return None


def _touch(request, pk):
    """last_seen / last_ip at most once per TOUCH_SECONDS per device."""
    if not cache.add(f'access:devtouch:{pk}', 1, TOUCH_SECONDS):
        return
    from django.utils import timezone
    from .models import Device
    fields = {'last_seen': timezone.now()}
    net = _network(request)
    if net is not None and net.ip:
        fields['last_ip'] = net.ip
        fields['last_network'] = net.zone
        fields['last_site'] = (net.site.name if net.site else '')[:120]
    else:
        ip = _client_ip(request)
        if ip:
            fields['last_ip'] = ip
    Device.objects.filter(pk=pk).update(**fields)


def resolve(request):
    """The DeviceInfo of the request's device cookie, or None. Never raises."""
    try:
        secret = request.COOKIES.get(COOKIE)
        if not secret:
            return None
        key = f'access:dev:{hash_secret(secret)}'
        hit = cache.get(key)
        if hit is None:
            device = from_secret(secret)
            if device is None:
                hit = _NONE
            else:
                hit = (device.pk, DeviceInfo(str(device.public_id), device.status, device.name, device.kind))
            cache.set(key, hit, DEVICE_CACHE_SECONDS)
        if hit == _NONE:
            return None
        pk, info = hit
        _touch(request, pk)
        return info
    except Exception as exc:
        logger.debug('device resolve skipped: %s', exc)
        return None


def blocked_cookie(request):
    """True when the request carries the cookie of a BLOCKED device (refused at sign-in)."""
    info = resolve(request)
    return info is not None and info.status == 'blocked'


def is_revoked(public_id):
    """True when the device is blocked or retired. False for None, unknown ids or any error."""
    if not public_id:
        return False
    try:
        key = f'access:devrev:{public_id}'
        hit = cache.get(key)
        if hit is None:
            from .models import Device
            hit = Device.objects.filter(public_id=public_id, status__in=('blocked', 'retired')).exists()
            cache.set(key, hit, DEVICE_CACHE_SECONDS)
        return bool(hit)
    except Exception as exc:
        logger.debug('device is_revoked skipped: %s', exc)
        return False


def invalidate(device):
    """Drop the cached status now and again after commit (a request between the two would
    otherwise re-cache the pre-commit status for a minute)."""
    from django.db import transaction
    keys = [f'access:dev:{device.secret_hash}', f'access:devrev:{device.public_id}']
    cache.delete_many(keys)
    transaction.on_commit(lambda: cache.delete_many(keys))


def invalidate_signal(sender, instance, **kwargs):
    invalidate(instance)


# -- Admin status changes (N2) -----------------------------------------------------------

def _request_fields(request):
    if request is None:
        return {}
    from apps.users.views import _request_network_fields
    fields = _request_network_fields(request)
    ip = _client_ip(request)
    if ip:
        fields['ip_address'] = ip
    return fields


RETIRED_MESSAGE = 'الجهاز متقاعد — لا يمكن إعادة تفعيله'


class RetiredDevice(Exception):
    pass


def set_status(device, status, by, note='', request=None):
    """Change a device's status: save (so the cache drops via post_save), audit, activity log.
    Never use QuerySet.update here - it would skip the invalidation."""
    from django.utils import timezone
    from apps.audit.models import AuditLog
    from apps.users.models import UserActivityLog
    if device.status == status:
        return device                       # no change, no audit row
    if device.status == 'retired':
        raise RetiredDevice(RETIRED_MESSAGE)   # retired is final
    request = getattr(request, '_request', request)
    before = snapshot(device)
    old_status = device.status
    device.status = status
    device.status_note = (note or '').strip()[:200]
    device.updated_by = by
    fields = ['status', 'status_note', 'updated_by']
    if status == 'approved':
        device.approved_by = by
        device.approved_at = timezone.now()
        fields += ['approved_by', 'approved_at']
    device.save(update_fields=fields)
    invalidate(device)
    AuditLog.log('device_changed', user=by, obj=device,
                 changes={'before': before, 'after': snapshot(device)}, note=device.status_note,
                 request=request)
    UserActivityLog.objects.create(target_user=device.owner, changed_by=by, action='device_status',
                                   old_value=old_status, new_value=status, note=device.status_note,
                                   device=device, **_request_fields(request))
    return device
