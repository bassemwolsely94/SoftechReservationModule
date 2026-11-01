"""
Device registry helpers (N2). The cookie value is a random secret; only its sha256 is stored.
"""
import hashlib
import logging
import secrets

from .network import INTERNAL

logger = logging.getLogger('elrezeiky.access')

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
    returns (None, None, False), and the sign-in goes on without a device."""
    try:
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
            notify_new_device(device, profile, net)
        return device, secret, created
    except Exception as exc:
        logger.warning('device enroll skipped: %s', exc)
        return None, None, False


def notify_new_device(device, profile, net=None):
    """Tell the user and every active admin that a new device awaits approval. Never raises."""
    try:
        from apps.notifications.models import Notification
        from apps.users.models import StaffProfile
        label = net.label_ar if net is not None else ''
        title = '💻 جهاز جديد بانتظار الاعتماد'
        body = (f'{profile.full_name or profile.user.username} — {device.name}'
                + (f' — {label}' if label else ''))
        recipients = {profile.pk: profile}
        for admin in StaffProfile.objects.filter(role='admin', is_active=True):
            recipients[admin.pk] = admin
        for sp in recipients.values():
            Notification.send_to_user(sp, 'system', title, body, dedup_key=f'device_new_{device.pk}')
    except Exception as exc:
        logger.debug('notify_new_device skipped: %s', exc)
