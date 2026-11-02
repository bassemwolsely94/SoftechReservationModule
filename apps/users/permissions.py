"""
apps/users/permissions.py  —  Phase 9

Custom permission classes enforcing role + branch access.
BACKEND IS FINAL AUTHORITY — frontend checks are UX only.
"""
from rest_framework.permissions import BasePermission


def _profile(request):
    return getattr(request.user, 'staff_profile', None)


class IsAdminRole(BasePermission):
    """Only admin role."""
    def has_permission(self, request, view):
        p = _profile(request)
        return bool(p and p.role == 'admin' and p.is_active)


class IsAdminOrCallCenter(BasePermission):
    """Admin or call center."""
    def has_permission(self, request, view):
        p = _profile(request)
        return bool(p and p.role in ('admin', 'call_center') and p.is_active)


class CanSeeCustomerPII(BasePermission):
    """Deny purchasing role from seeing customer personal data."""
    def has_permission(self, request, view):
        p = _profile(request)
        if not p:
            return False
        return p.role != 'purchasing'


class IsActiveStaff(BasePermission):
    """User must have an active StaffProfile."""
    def has_permission(self, request, view):
        p = _profile(request)
        return bool(p and p.is_active)
