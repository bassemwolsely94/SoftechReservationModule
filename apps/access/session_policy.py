"""
Sessions follow the access zone (N3).

Every token carries `zone` (Z1-Z4 at the time it was issued or last refreshed) and `auth_at`
(epoch seconds of the sign-in, kept across refresh rotation; old tokens fall back to `iat`).
Sign-in and refresh re-evaluate the zone from the request itself (network + the erp_device
cookie's status) - the sign-in request has no session yet.

Mode is NETWORK_POLICY_ENFORCEMENT, read per call: refusals (blocked sign-in, refresh past the
cap or blocked) happen only in `enforce`; `log` writes a "zone would-deny" line and goes on;
`off` does nothing but the claims are still stamped. Nothing here raises into the sign-in path.
"""
import logging
import time
from types import SimpleNamespace

from django.conf import settings

from .devices import COOKIE, from_secret
from .network import INTERNAL, request_network
from .policy import REASON_MESSAGES, policy_for
from .zones import Z3, Z4, ZONE_LABELS, zone_for

log = logging.getLogger('elrezeiky.access')

EXTERNAL_ZONES = (Z3, Z4)
EXPIRED_MESSAGE = 'انتهت مدة الجلسة المسموحة من خارج شبكة الشركة — سجّل الدخول من جديد'
ENROL_INSIDE_MESSAGE = 'فعّل المصادقة الثنائية من داخل شبكة الشركة أولاً'
ALERT_TITLE = 'دخول من خارج الشبكة'


def _now():
    return time.time()


def mode():
    from .policy_middleware import _mode
    return _mode()


def message(reason):
    if reason == 'expired':
        return EXPIRED_MESSAGE
    if reason == 'mfa_enrol_inside':
        return ENROL_INSIDE_MESSAGE
    return REASON_MESSAGES.get(reason, REASON_MESSAGES['blocked'])


# ── who: the policy subject of a user ───────────────────────────────────────────────────

def subject(user):
    """What the zone policy is applied to for `user`: the StaffProfile; for a superuser without
    one, the admin rows; for any other user without one, the viewer rows (the role the app already
    shows such an account as), so a service account keeps working inside and is blocked outside."""
    if user is None:
        return None
    profile = getattr(user, 'staff_profile', None)
    if profile is not None:
        return profile
    if getattr(user, 'is_superuser', False):
        return SimpleNamespace(role='admin', user=user,
                               external_export=False, external_softech_write=False)
    return SimpleNamespace(role='viewer', user=user,
                           external_export=False, external_softech_write=False)


# ── zone of a sign-in / refresh request ─────────────────────────────────────────────────

def network_internal(request):
    """True when the request's network is internal; False on any error. Never raises."""
    try:
        return request_network(request).zone == INTERNAL
    except Exception:
        return False


def request_zone(request):
    """Z1-Z4 from the request's network and its device cookie. Never raises: when the network
    cannot be read the request is Z4; when only the device lookup fails on an internal network it
    is Z2 (fail open inside, logged as an error - F3)."""
    try:
        net = request_network(request)
    except Exception:
        log.warning('sign-in zone failed, treated as Z4', exc_info=True)
        return Z4
    try:
        device = from_secret(request.COOKIES.get(COOKIE))
        return zone_for(net.zone, device.status if device is not None else None)
    except Exception:
        if net.zone == INTERNAL:
            log.error('sign-in device lookup failed on an internal network, treated as Z2', exc_info=True)
        else:
            log.warning('sign-in device lookup failed, treated as Z4', exc_info=True)
        return zone_for(net.zone, None)


def _on_error(request, what):
    """Enforce-mode lookup error: True = refuse. Fails open (ERROR log) on an internal network,
    closed outside (F3)."""
    if network_internal(request):
        log.error('zone %s check failed on an internal network, allowed', what, exc_info=True)
        return False
    log.warning('zone %s check failed outside, refused', what, exc_info=True)
    return True


# ── claims ──────────────────────────────────────────────────────────────────────────────

def stamp(refresh, zone, auth_at=None):
    """Set the `zone` and `auth_at` claims (call before .access_token, which copies them)."""
    refresh['zone'] = zone
    refresh['auth_at'] = int(auth_at if auth_at is not None else _now())


def auth_at_of(token):
    """The sign-in time of a token: `auth_at`, else its `iat` (tokens from before N3)."""
    value = token.get('auth_at') or token.get('iat')
    return int(value) if value is not None else None


# ── the policy for sessions ─────────────────────────────────────────────────────────────

def _policy(profile, zone):
    if profile is None:
        return None
    return policy_for(profile.role, zone or Z4)     # signed-in, no zone = Z4


def cap_hours(profile, zone):
    pol = _policy(profile, zone)
    return pol.max_session_hours if pol is not None and pol.max_session_hours else None


def mfa_required_in_zone(profile, zone):
    pol = _policy(profile, zone)
    return bool(pol is not None and pol.require_mfa)


def blocked(profile, zone):
    pol = _policy(profile, zone)
    return pol is not None and pol.access == 'none'


def refresh_allowed(profile, token, zone):
    """(True, None) or (False, 'blocked' | 'expired')."""
    if blocked(profile, zone):
        return False, 'blocked'
    cap = cap_hours(profile, zone)
    if cap:
        auth_at = auth_at_of(token)
        if auth_at is None or _now() - auth_at > cap * 3600:
            return False, 'expired'
    return True, None


def refresh_max_age(profile, zone, auth_at):
    """Refresh-cookie max_age in seconds: the rest of the zone's cap, capped at the normal
    lifetime. None (the normal lifetime) outside enforce mode, without a cap, or on any error."""
    try:
        if mode() != 'enforce':
            return None
        cap = cap_hours(profile, zone)
        if not cap:
            return None
        normal = int(settings.SIMPLE_JWT['REFRESH_TOKEN_LIFETIME'].total_seconds())
        start = auth_at if auth_at is not None else int(_now())
        return max(0, min(normal, int(start + cap * 3600 - _now())))
    except Exception:
        log.warning('session cap cookie failed', exc_info=True)
        return None


# ── decisions with mode + logging ───────────────────────────────────────────────────────

def would_deny(request, profile, zone, reason, scope):
    """The middleware's deduped 'zone would-deny' / 'zone DENY' line. Never raises."""
    try:
        from .policy_middleware import ZonePolicyMiddleware
        ZonePolicyMiddleware._log(mode(), profile, zone, reason, request, scope)
    except Exception:
        log.warning('zone session log failed', exc_info=True)


def login_refusal(request, profile, zone):
    """'blocked' when this sign-in must be refused (enforce only), else None. In log mode a
    blocked sign-in is logged and goes on. On error: enforce refuses, log / off go on."""
    current = mode()
    if current == 'off' or profile is None:
        return None
    try:
        if not blocked(profile, zone):
            return None
    except Exception:
        if current != 'enforce':
            log.warning('zone sign-in check failed', exc_info=True)
            return None
        return 'blocked' if _on_error(request, 'sign-in') else None
    would_deny(request, profile, zone, 'blocked', 'login')
    return 'blocked' if current == 'enforce' else None


def enrol_refusal(request, profile, zone):
    """'mfa_enrol_inside' when a first 2FA enrolment at sign-in comes from outside the network
    (Z3/Z4, or no zone) and the policy is enforced, else None; log mode logs it (F1). Enrolment
    from settings in a running session is not a sign-in and never comes here."""
    current = mode()
    if current == 'off' or profile is None:
        return None
    if (zone or Z4) not in EXTERNAL_ZONES:
        return None
    would_deny(request, profile, zone or Z4, 'mfa_enrol_inside', 'login-enrol')
    return 'mfa_enrol_inside' if current == 'enforce' else None


def login_needs_mfa(request, profile, zone):
    """True when the zone forces 2FA on this sign-in (enforce only; log mode logs it). On error:
    enforce asks for 2FA, log / off go on."""
    current = mode()
    if current == 'off' or profile is None:
        return False
    try:
        needed = mfa_required_in_zone(profile, zone)
    except Exception:
        if current != 'enforce':
            log.warning('zone 2FA check failed', exc_info=True)
            return False
        return _on_error(request, '2FA')
    if not needed:
        return False
    if current == 'enforce':
        return True
    would_deny(request, profile, zone, 'mfa', 'login-mfa')
    return False


def refresh_refusal(request, profile, token, zone):
    """'blocked' / 'expired' when this refresh must be refused (enforce only), else None."""
    current = mode()
    if current == 'off' or profile is None:
        return None
    try:
        ok, reason = refresh_allowed(profile, token, zone)
    except Exception:
        if current != 'enforce':
            log.warning('zone refresh check failed', exc_info=True)
            return None
        return 'blocked' if _on_error(request, 'refresh') else None
    if ok:
        return None
    would_deny(request, profile, zone, reason, 'refresh')
    return reason if current == 'enforce' else None


# ── external sign-in alert ──────────────────────────────────────────────────────────────

def alert_external_login(profile, zone, request=None):
    """Z3 / Z4 sign-in in enforce mode: tell the user (once per hour) and the admins (hourly
    digest), after commit. Never raises. Off / log send nothing (F4): a wrong proxy setup in log
    mode would otherwise alert every user every hour."""
    try:
        if profile is None or getattr(profile, 'pk', None) is None or zone not in EXTERNAL_ZONES:
            return
        if mode() != 'enforce':
            return
        from django.db import transaction
        ip = ''
        try:
            from core.client_ip import client_ip
            ip = (client_ip(request) or '') if request is not None else ''
        except Exception:
            pass
        transaction.on_commit(lambda: _send_alert(profile, zone, ip))
    except Exception:
        log.warning('external sign-in alert skipped', exc_info=True)


def _digest_body(who, where):
    try:
        from django.utils import timezone
        from apps.users.models import UserActivityLog
        start = timezone.now().replace(minute=0, second=0, microsecond=0)
        n = UserActivityLog.objects.filter(action__in=('login_success', 'mfa_verified'), network='external',
                                           created_at__gte=start).count()
        return f'دخول من خارج الشبكة خلال هذه الساعة: {max(n, 1)} — آخرها {who} ({where}) — راجع /access/devices'
    except Exception:
        return f'{who} — {where}'


def _send_alert(profile, zone, ip):
    try:
        from django.utils import timezone
        from apps.notifications.models import Notification
        from . import devices
        hour = timezone.now().strftime('%Y%m%d%H')
        who = profile.full_name or profile.user.username
        where = ZONE_LABELS.get(zone, zone)
        body = f'تم تسجيل الدخول إلى حسابك من خارج شبكة الشركة ({where})' + (f' — {ip}' if ip else '') \
            + ' — إن لم تكن أنت فغيّر كلمة المرور فوراً وأبلغ المدير'
        try:
            Notification.send_to_user(profile, 'system', f'🌐 {ALERT_TITLE}', body,
                                      dedup_key=f'login_external_user_{profile.pk}_{hour}',
                                      dedup_once=True, bypass_role_gate=True)
        except Exception as exc:
            log.warning('external sign-in alert to user %s failed: %s', profile.pk, exc)
        devices.admin_digest(f'🌐 {ALERT_TITLE}', _digest_body(who, where),
                             f'login_external_digest_{hour}', exclude_pk=profile.pk, refresh_body=True)
    except Exception as exc:
        log.warning('external sign-in alert skipped: %s', exc)
