"""
apps/users/sessions.py — ending a user's sessions (Batch 3, A-3).

A JWT can't be recalled, so "log this user out everywhere" means: blacklist every refresh token
(no renewal) — the access token then dies within its 1-hour lifetime. A DISABLED account is
refused at once: core.auth_cookies.CookieJWTAuthentication and /api/auth/refresh/ both check
StaffProfile.is_active on every request. "Remember this device" tokens carry a fingerprint of
the password + 2FA secret (apps.users.mfa), so a password change, an admin reset or a 2FA reset
cancels them without any stored list.
"""
import logging

logger = logging.getLogger('elrezeiky.users')


def account_active(user) -> bool:
    """Django user active AND (when it has one) staff profile active."""
    if user is None or not user.is_active:
        return False
    profile = getattr(user, 'staff_profile', None)
    return profile is None or bool(profile.is_active)


def end_sessions(user) -> int:
    """Blacklist every outstanding refresh token of `user`. Returns how many were revoked."""
    from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
    revoked = 0
    for token in OutstandingToken.objects.filter(user=user):
        _, created = BlacklistedToken.objects.get_or_create(token=token)
        revoked += int(created)
    logger.info('[sessions] user=%s — %d refresh token(s) revoked', user.pk, revoked)
    return revoked
