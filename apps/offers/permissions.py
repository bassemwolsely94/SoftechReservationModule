"""RBAC for offers — money-critical, so writes are tightly gated."""
from rest_framework.permissions import BasePermission, SAFE_METHODS

WRITE_ROLES = {'admin', 'supervisor', 'purchasing'}


class CanManageOffers(BasePermission):
    """Read: any active staff. Write: admin/supervisor/purchasing only."""
    def has_permission(self, request, view):
        p = getattr(request.user, 'staff_profile', None)
        if not (p and p.is_active):
            return False
        if request.method in SAFE_METHODS:
            return True
        return p.role in WRITE_ROLES
