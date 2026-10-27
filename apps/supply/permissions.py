"""
apps/supply/permissions.py — server-side RBAC for the supply orchestration API.

No new authorization system (§39): the supply workspace is purchasing-domain work, so it
rides the EXISTING RBAC matrix module `purchasing` via StaffProfile.can_do(), exactly like
apps/pos_orders/permissions.py does for `pos`:

  • once the RoleModuleAccess matrix has ANY row for `purchasing`, it is authoritative —
    deny-by-default, and an explicit admin denial is respected
  • a role allow-list is only a FALLBACK while the matrix has no `purchasing` rows at all
  • admin role and Django superusers always pass

Read (safe methods)  → purchasing/view
Write (everything else: import, confirm, transition, assign) → purchasing/edit
Hiding a button in React is never the authorization (CLAUDE.md rule 9).
"""
from rest_framework.permissions import BasePermission, SAFE_METHODS

MODULE = 'purchasing'

# Fallbacks mirror the purchasing writers' WRITE_ROLES (isr_views / rate_writer_views).
VIEW_FALLBACK_ROLES  = {'admin', 'supervisor', 'purchasing', 'quality_manager'}
WRITE_FALLBACK_ROLES = {'admin', 'supervisor', 'purchasing'}


def _profile(request):
    return getattr(request.user, 'staff_profile', None)


def supply_allowed(request, action: str) -> bool:
    """True when the requesting user may perform ``action`` ('view' | 'edit') on supply."""
    user = getattr(request, 'user', None)
    if user is not None and getattr(user, 'is_superuser', False):
        return True
    p = _profile(request)
    if not (p and p.is_active):
        return False
    if p.role == 'admin':
        return True
    try:
        from apps.users.models import RoleModuleAccess
        if RoleModuleAccess.objects.filter(module=MODULE).exists():
            # Matrix is seeded for this module → it is AUTHORITATIVE, including an
            # explicit denial (is_allowed=False) configured by an admin.
            return p.can_do(MODULE, action)
    except Exception:
        pass
    # Matrix not seeded for this module yet → role allow-list fallback.
    fallback = VIEW_FALLBACK_ROLES if action == 'view' else WRITE_FALLBACK_ROLES
    return p.role in fallback


class CanOperateSupply(BasePermission):
    """Safe methods need purchasing/view; unsafe methods need purchasing/edit."""
    message = 'ليس لديك صلاحية على وحدة التزويد والتوريد.'

    def has_permission(self, request, view):
        action = 'view' if request.method in SAFE_METHODS else 'edit'
        return supply_allowed(request, action)
