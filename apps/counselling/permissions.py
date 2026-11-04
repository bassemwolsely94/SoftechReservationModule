"""
Server-side permissions for counselling. The RBAC matrix (`counselling` module) is authoritative;
the frontend only hides buttons for comfort.
"""
from rest_framework.permissions import BasePermission

from core.permissions import matrix_allows


def _profile(request):
    return getattr(request.user, 'staff_profile', None)


def can(profile, action: str) -> bool:
    return bool(profile and profile.is_active and matrix_allows(profile, 'counselling', action))


class CounsellingAccess(BasePermission):
    """view on reads; the view's `counselling_action` (default edit) on writes."""
    def has_permission(self, request, view):
        p = _profile(request)
        if request.method in ('GET', 'HEAD', 'OPTIONS'):
            needed = getattr(view, 'counselling_read_action', 'view')
        else:
            needed = getattr(view, 'counselling_action', 'edit')
        return can(p, needed)


class PosCreate(BasePermission):
    """Sending a counselling card is a counter action: the `pos` create grant. As the POS views,
    the operator role list applies only while no `pos` row is seeded (never "allow everyone")."""
    def has_permission(self, request, view):
        p = _profile(request)
        if not (p and p.is_active):
            return False
        if p.role == 'admin':
            return True
        from core.middleware import module_access
        if 'pos' not in module_access.seeded_modules():
            from apps.pos_orders.permissions import PUSH_ROLES
            return p.role in PUSH_ROLES
        return matrix_allows(p, 'pos', 'create')
