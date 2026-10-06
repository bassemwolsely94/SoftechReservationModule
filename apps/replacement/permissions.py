"""
apps/replacement/permissions.py — server-side RBAC for بدل الروشتة (doc 25 §8).

Rides the existing RoleModuleAccess matrix under the new module `replacement`, with the
same semantics as apps/supply/permissions.py:
  • once the matrix has ANY `replacement` row it is authoritative (explicit denial respected)
  • role allow-list only as a fallback while the module is unseeded
  • admin role / superuser always pass
Phase 0 actions: view (read everything in the user's branches) and edit (confirm/reject a
proposed link, acknowledge/resolve an exception, re-run one case). Finer-grained names
(post_purchase, approve_cash, view_profitability…) arrive with the phases that need them.
Branch scope is enforced in the queryset (scoped_cases), never by the UI.
"""
from rest_framework.permissions import SAFE_METHODS, BasePermission

MODULE = 'replacement'   # role fallbacks live in authz.FALLBACK_ROLES (single source)


def _profile(request):
    return getattr(request.user, 'staff_profile', None)


def replacement_allowed(request, action: str) -> bool:
    user = getattr(request, 'user', None)
    if user is not None and getattr(user, 'is_superuser', False):
        return True
    from .authz import role_allows
    return role_allows(_profile(request), action)


def scoped_cases(request, qs):
    """Restrict to the user's accessible branches (None = all)."""
    user = getattr(request, 'user', None)
    if user is not None and getattr(user, 'is_superuser', False):
        return qs
    p = _profile(request)
    if not p:
        return qs.none()
    ids = p.accessible_branch_ids
    return qs if ids is None else qs.filter(branch_id__in=ids)


class CanUseReplacement(BasePermission):
    """Entry gate = may VIEW the module. Every mutating action then checks its OWN permission
    (create / edit / approve / post + per-employee grant) via authz.require in the view/service."""
    message = 'ليس لديك صلاحية على وحدة بدل الروشتة.'

    def has_permission(self, request, view):
        return replacement_allowed(request, 'view')
