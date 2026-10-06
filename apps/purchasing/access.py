"""
apps/purchasing/access.py — who may operate the /supply workspace and start the
demand engine.

Owner decision (2026-10-02): besides the app roles, access follows the person's
SOFTECH user GROUP, so the replenishment team doesn't need a role change (their app
role — usually salesperson — keeps governing everything else). SOFTECH groups granted
by default (settings.SUPPLY_ERP_GROUPS):
    10 Administrator · 19 مخزن · 21 كارت صنف · 27 Internal Auditor
Anyone added to / removed from those groups in SOFTECH gains / loses access on the
next user sync. Inactive SOFTECH users never qualify.

  can_supply_write — approve / execute rate pushes, ISRs and توزيعة in /supply
  can_run_engine   — start a QUICK engine run (▶ تشغيل). Full re-sync, catch-up and
                     engine settings stay admin / pharmacist only.
Enforced server-side by the views; the frontend only reads the flags to show buttons.
"""
from django.conf import settings

SUPPLY_WRITE_ROLES = {'admin', 'supervisor', 'purchasing'}
ENGINE_ADMIN_ROLES = {'admin', 'pharmacist'}          # full re-sync / settings / overrides
ENGINE_RUN_ROLES   = ENGINE_ADMIN_ROLES | {'purchasing'}


def supply_groups() -> set:
    raw = getattr(settings, 'SUPPLY_ERP_GROUPS', '10,19,21,27')
    if isinstance(raw, (list, tuple, set)):
        return {str(g).strip() for g in raw if str(g).strip()}
    return {g.strip() for g in str(raw).split(',') if g.strip()}


def _profile(user):
    return getattr(user, 'staff_profile', None)


def _role(user):
    p = _profile(user)
    return getattr(p, 'role', None) if p else None


def erp_group_of(user):
    """The user's SOFTECH group code (str) or None. Uses the formal erp_user link when
    present, otherwise matches the SOFTECH user code (our usernames are the SOFTECH
    codes, e.g. '18', '1608'). Inactive SOFTECH users → None."""
    from apps.users.models import ERPUser
    if not getattr(user, 'is_authenticated', False):
        return None
    p = _profile(user)
    erp = getattr(p, 'erp_user', None) if p else None
    if erp is None:
        codes = {str(user.username).strip()}
        if p:
            codes |= {str(p.softech_user_id or '').strip(), str(p.softech_username or '').strip()}
        codes.discard('')
        erp = ERPUser.objects.filter(username__in=codes).order_by('-is_active').first()
    if erp is None or not erp.is_active:
        return None
    return str(erp.user_group or '').strip() or None


def in_supply_group(user) -> bool:
    return erp_group_of(user) in supply_groups()


def can_supply_write(user) -> bool:
    if not getattr(user, 'is_authenticated', False):
        return False
    if user.is_superuser or _role(user) in SUPPLY_WRITE_ROLES:
        return True
    return in_supply_group(user)


def can_run_engine(user) -> bool:
    """May start a quick engine run."""
    if not getattr(user, 'is_authenticated', False):
        return False
    if user.is_superuser or _role(user) in ENGINE_RUN_ROLES:
        return True
    return in_supply_group(user)


def is_engine_admin(user) -> bool:
    """May run full re-sync / pass engine parameter overrides."""
    return bool(getattr(user, 'is_authenticated', False) and
                (user.is_superuser or _role(user) in ENGINE_ADMIN_ROLES))
