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


class BranchScopedPermission(BasePermission):
    """
    Allows access only to data within the user's accessible branches.
    Object-level check — use has_object_permission.
    """
    def has_permission(self, request, view):
        return bool(_profile(request))

    def has_object_permission(self, request, view, obj):
        p = _profile(request)
        if not p:
            return False
        if p.role == 'admin' or p.access_all_branches:
            return True
        # Get branch from object
        branch = getattr(obj, 'branch', None)
        if branch is None:
            return True
        return p.can_access_branch(branch)


class IsActiveStaff(BasePermission):
    """User must have an active StaffProfile."""
    def has_permission(self, request, view):
        p = _profile(request)
        return bool(p and p.is_active)
