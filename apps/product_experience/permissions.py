"""
apps/product_experience/permissions.py

Custom permissions for the Product Experience Platform.
"""
from rest_framework.permissions import BasePermission, IsAuthenticated


class IsContentManager(BasePermission):
    """
    Allows write access to admin or purchasing roles.
    Read access is open to all authenticated users.
    """
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.method in ('GET', 'HEAD', 'OPTIONS'):
            return True
        # Write requires admin or purchasing role
        if request.user.is_staff or request.user.is_superuser:
            return True
        try:
            role = request.user.staff_profile.role
            return role in ('admin', 'purchasing')
        except AttributeError:
            return False


class IsMediaApprover(BasePermission):
    """Allows approving/rejecting media uploads."""
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_staff:
            return True
        try:
            return request.user.staff_profile.role == 'admin'
        except AttributeError:
            return False


class IsAdminOrReadOnly(BasePermission):
    """Admin can write, everyone authenticated can read."""
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.method in ('GET', 'HEAD', 'OPTIONS'):
            return True
        return request.user.is_staff or request.user.is_superuser
