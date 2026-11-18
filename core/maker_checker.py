"""
core/maker_checker.py — nobody approves a document they created themselves (UAT W5b, 2026-11-17).

Used by the human approval endpoints of money documents: ISR replenishment (apps.purchasing),
GL journal entries (apps.finance.gl) and price-change requests (apps.discount_approvals).
Internal service paths (month close, opening balances) do not call it.

The admin role is exempt while SELF_APPROVAL_ADMIN_EXEMPT is True (default): today the owner's
admin account both prepares and approves (one real ISR on the 2026-11-16 copy was exactly that).
Switch it off once real roles are assigned (owner decision D4) to make the rule absolute.
"""
from django.conf import settings

MESSAGE = 'لا يمكنك اعتماد مستند أنشأته بنفسك — يعتمده زميل آخر.'


def _user_id(person):
    """A User, a StaffProfile or None → the auth user id (None when unknown)."""
    if person is None:
        return None
    if hasattr(person, 'user_id') and not hasattr(person, 'is_superuser'):
        return person.user_id            # StaffProfile
    return getattr(person, 'pk', None)   # User


def _approver_user(approver):
    return getattr(approver, 'user', approver) if not hasattr(approver, 'is_superuser') else approver


def refusal(maker, approver):
    """None when `approver` may approve what `maker` created; else the Arabic refusal message.
    `maker` / `approver`: a User or a StaffProfile. An unknown maker (engine-made) never blocks."""
    maker_id, approver_id = _user_id(maker), _user_id(approver)
    if maker_id is None or approver_id is None or maker_id != approver_id:
        return None
    user = _approver_user(approver)
    profile = getattr(user, 'staff_profile', None)
    is_admin = bool(getattr(user, 'is_superuser', False) or (profile is not None and profile.is_admin))
    if is_admin and getattr(settings, 'SELF_APPROVAL_ADMIN_EXEMPT', True):
        return None
    return MESSAGE
