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


def lock_end(times):
    """THE lock rule, shared by real accounts (UserActivityLog) and unknown identifiers (cache),
    so the two answer identically at every moment.

    `times` = the failure times since the last reset. FAIL_LIMIT failures inside WINDOW lock
    from that moment: the lock runs to the last such failure + LOCK_FOR, and it stays in force
    even after the failures themselves age out of WINDOW. Returns that end time or None.
    """
    times = sorted(times)
    end = None
    for i in range(FAIL_LIMIT - 1, len(times)):
        if times[i] - times[i - FAIL_LIMIT + 1] <= WINDOW:
            end = times[i] + LOCK_FOR
    return end


def _failure_times(profile, now):
    """Failures that can still matter: after the last completed login / unlock, and recent
    enough that a lock they caused could still be running."""
    horizon = now - WINDOW - LOCK_FOR
    last_reset = (_logs().filter(target_user=profile, action__in=_RESET_ACTIONS)
                  .order_by('-created_at').values_list('created_at', flat=True).first())
    if last_reset and last_reset > horizon:
        horizon = last_reset
    return list(_logs().filter(target_user=profile, action__in=_FAIL_ACTIONS,
                               created_at__gt=horizon).values_list('created_at', flat=True))


def locked_until(profile):
    """When the account's lock ends, or None when it is not locked."""
    now = timezone.now()
    end = lock_end(_failure_times(profile, now))
    return end if end and end > now else None


def register_lock(profile, ip):
    """Record the lock once and tell the admins. Safe to call after every failure."""
    until = locked_until(profile)
    if not until:
        return
    began = until - LOCK_FOR
    if _logs().filter(target_user=profile, action='login_locked',
                      created_at__gt=began - LOCK_FOR).exists():
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
    return 'login-unknown:' + hashlib.sha256(identifier.strip().encode()).hexdigest()[:32]


def _unknown_times(identifier, now):
    horizon = now - WINDOW - LOCK_FOR
    return [t for t in (cache.get(_unknown_key(identifier)) or []) if t > horizon]


def unknown_identifier_locked(identifier: str) -> bool:
    now = timezone.now()
    end = lock_end(_unknown_times(identifier, now))
    return bool(end and end > now)


def note_unknown_failure(identifier: str) -> None:
    now = timezone.now()
    times = _unknown_times(identifier, now) + [now]
    cache.set(_unknown_key(identifier), times[-4 * FAIL_LIMIT:],
              int((WINDOW + LOCK_FOR).total_seconds()))
