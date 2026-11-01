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

from django.conf import settings

from .devices import COOKIE, from_secret
from .network import request_network
from .policy import REASON_MESSAGES, policy_for
from .zones import Z3, Z4, ZONE_LABELS, zone_for

log = logging.getLogger('elrezeiky.access')

EXTERNAL_ZONES = (Z3, Z4)
EXPIRED_MESSAGE = 'انتهت مدة الجلسة المسموحة من خارج شبكة الشركة — سجّل الدخول من جديد'
ALERT_TITLE = 'دخول من خارج الشبكة'


def _now():
    return time.time()


def mode():
    from .policy_middleware import _mode
    return _mode()


def message(reason):
    return EXPIRED_MESSAGE if reason == 'expired' else REASON_MESSAGES.get(reason, REASON_MESSAGES['blocked'])


# ── zone of a sign-in / refresh request ─────────────────────────────────────────────────

def request_zone(request):
    """Z1-Z4 from the request's network and its device cookie. Z4 on any error. Never raises."""
    try:
        net = request_network(request)
        device = from_secret(request.COOKIES.get(COOKIE))
        return zone_for(net.zone, device.status if device is not None else None)
    except Exception:
        log.warning('sign-in zone failed, treated as Z4', exc_info=True)
        return Z4


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
        log.warning('zone sign-in check failed', exc_info=True)
        return 'blocked' if current == 'enforce' else None
    would_deny(request, profile, zone, 'blocked', 'login')
    return 'blocked' if current == 'enforce' else None


def login_needs_mfa(request, profile, zone):
    """True when the zone forces 2FA on this sign-in (enforce only; log mode logs it). On error:
    enforce asks for 2FA, log / off go on."""
    current = mode()
    if current == 'off' or profile is None:
        return False
    try:
        needed = mfa_required_in_zone(profile, zone)
    except Exception:
        log.warning('zone 2FA check failed', exc_info=True)
        return current == 'enforce'
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
        log.warning('zone refresh check failed', exc_info=True)
        return 'blocked' if current == 'enforce' else None
    if ok:
        return None
    would_deny(request, profile, zone, reason, 'refresh')
    return reason if current == 'enforce' else None


# ── external sign-in alert ──────────────────────────────────────────────────────────────

def alert_external_login(profile, zone, request=None):
    """Z3 / Z4 sign-in: tell the user (once per hour) and the admins (hourly digest), after
    commit. Never raises."""
    try:
        if profile is None or zone not in EXTERNAL_ZONES:
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
        n = UserActivityLog.objects.filter(action='login_success', network='external',
                                           created_at__gte=start).count()
        return f'دخول من خارج الشبكة خلال هذه الساعة: {max(n, 1)} — أولها {who} ({where}) — راجع /access/devices'
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
                             f'login_external_digest_{hour}', exclude_pk=profile.pk)
    except Exception as exc:
        log.warning('external sign-in alert skipped: %s', exc)
