"""
Per-account login lockout (security batch N0, H8).

The per-IP throttle (LoginRateThrottle) does nothing against a guesser who rotates addresses.
This adds a per-ACCOUNT limit: FAIL_LIMIT wrong passwords / wrong 2FA codes inside WINDOW lock
the account for LOCK_FOR (counted from the last failure). The state is derived from
UserActivityLog rows — DB-backed, so it survives restarts and holds across worker processes.
A real successful login (or an admin unlock) starts the count again.

Identifiers that match no account get the same treatment through a cache counter, so a guesser
cannot tell a real account from a made-up one by when the 429 appears.
"""
import hashlib
from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone

FAIL_LIMIT = 5
WINDOW = timedelta(minutes=15)
LOCK_FOR = timedelta(minutes=15)

LOCKED_MESSAGE = 'تم إيقاف الدخول مؤقتاً بسبب محاولات خاطئة متكررة. حاول بعد 15 دقيقة أو تواصل مع المدير'

_FAIL_ACTIONS = ('login_failed', 'mfa_failed')
# A completed login ends the streak. `mfa_challenge` (password OK, code still owed) does not.
_RESET_ACTIONS = ('login_success', 'mfa_verified', 'login_unlocked')


def _logs():
    from .models import UserActivityLog
    return UserActivityLog.objects


def _since(profile, now):
    """Failures older than this no longer count."""
    since = now - WINDOW
    last_reset = (_logs().filter(target_user=profile, action__in=_RESET_ACTIONS)
                  .order_by('-created_at').values_list('created_at', flat=True).first())
    return max(since, last_reset) if last_reset else since


def locked_until(profile):
    """When the account's lock ends, or None when it is not locked."""
    now = timezone.now()
    fails = list(_logs().filter(target_user=profile, action__in=_FAIL_ACTIONS,
                                created_at__gt=_since(profile, now))
                 .order_by('-created_at').values_list('created_at', flat=True)[:FAIL_LIMIT])
    if len(fails) < FAIL_LIMIT:
        return None
    until = fails[0] + LOCK_FOR
    return until if until > now else None


def register_lock(profile, ip):
    """Record the lock once and tell the admins. Safe to call after every failure."""
    now = timezone.now()
    if _logs().filter(target_user=profile, action='login_locked',
                      created_at__gt=_since(profile, now)).exists():
        return
    until = locked_until(profile)
    if not until:
        return
    _logs().create(target_user=profile, changed_by=None, action='login_locked', ip_address=ip,
                   new_value={'locked_until': until.isoformat()},
                   note=f'{FAIL_LIMIT} محاولات خاطئة خلال {int(WINDOW.total_seconds() // 60)} دقيقة')
    try:
        from apps.notifications.models import Notification
        Notification.send_to_roles(
            ['admin'], 'system',
            title=f'تم إيقاف دخول {profile.full_name or profile.user.username} مؤقتاً',
            body='محاولات دخول خاطئة متكررة. يمكن رفع الإيقاف من صفحة إدارة المستخدمين.',
            dedup_key=f'login-lock:{profile.id}',
        )
    except Exception:
        pass     # an alert transport problem must never change the login response


def unlock(profile, by_profile, ip):
    _logs().create(target_user=profile, changed_by=by_profile, action='login_unlocked',
                   ip_address=ip, note='رفع إيقاف الدخول')


# ── Identifiers that match no account ────────────────────────────────────────

def _unknown_key(identifier):
    return 'login-unknown:' + hashlib.sha256(identifier.strip().lower().encode()).hexdigest()[:32]


def unknown_identifier_locked(identifier: str) -> bool:
    return (cache.get(_unknown_key(identifier)) or 0) >= FAIL_LIMIT


def note_unknown_failure(identifier: str) -> None:
    key = _unknown_key(identifier)
    ttl = int(LOCK_FOR.total_seconds())
    cache.add(key, 0, ttl)
    try:
        cache.incr(key)
    except ValueError:
        cache.set(key, 1, ttl)
