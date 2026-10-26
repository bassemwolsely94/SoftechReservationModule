"""
core/permissions.py

Reusable DRF permission classes + a decorator that enforce the dynamic
RoleModuleAccess table.  Admins bypass ALL module checks.

Usage in a ViewSet:
    from core.permissions import ModulePermission, require_module

    class ReservationViewSet(viewsets.ModelViewSet):
        permission_classes = [IsAuthenticated, ModulePermission('reservations', 'view')]

    # Or with a fine-grained decorator on an action:
    @action(detail=True, methods=['post'])
    @require_module('reservations', 'approve')
    def approve(self, request, pk=None): ...
"""
from functools import wraps
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework import status


def _get_profile(request):
    return getattr(request.user, 'staff_profile', None)


class ModulePermission(BasePermission):
    """
    DRF permission class factory — checks RoleModuleAccess for a (module, action) pair.
    Instantiate with the module name and required action:
        permission_classes = [IsAuthenticated, ModulePermission('reservations', 'view')]
    """

    def __init__(self, module: str, action: str = 'view'):
        self.module = module
        self.required_action = action
        super().__init__()

    def has_permission(self, request, view):
        profile = _get_profile(request)
        if not profile or not profile.is_active:
            return False
        return profile.can_do(self.module, self.required_action)

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)


class IsAdminRole(BasePermission):
    """Only the 'admin' role may pass."""

    def has_permission(self, request, view):
        profile = _get_profile(request)
        return bool(profile and profile.role == 'admin' and profile.is_active)


class IsHQRole(BasePermission):
    """Admin, call_center, or purchasing (HQ roles that see all branches)."""

    def has_permission(self, request, view):
        profile = _get_profile(request)
        return bool(profile and profile.can_see_all_branches and profile.is_active)


class IsNotViewer(BasePermission):
    """Reject viewer-only accounts from mutating anything."""

    def has_permission(self, request, view):
        from rest_framework.permissions import SAFE_METHODS
        if request.method in SAFE_METHODS:
            return True
        profile = _get_profile(request)
        return bool(profile and profile.role != 'viewer' and profile.is_active)


def require_module(module: str, action: str = 'view'):
    """
    Decorator for ViewSet action methods.
    Returns 403 immediately if the requesting user lacks the module+action grant.

    Example:
        @action(detail=True, methods=['post'])
        @require_module('transfers', 'approve')
        def approve(self, request, pk=None):
            ...
    """
    def decorator(func):
        @wraps(func)
        def wrapper(self_or_request, *args, **kwargs):
            # Support both function-based views (request is first arg)
            # and ViewSet methods (self is first arg, request is second).
            if hasattr(self_or_request, 'method'):
                request = self_or_request
            else:
                request = args[0] if args else kwargs.get('request')

            profile = _get_profile(request)
            if not profile or not profile.can_do(module, action):
                return Response(
                    {'detail': f'ليس لديك صلاحية تنفيذ هذه العملية ({module}.{action})'},
                    status=status.HTTP_403_FORBIDDEN,
                )
            return func(self_or_request, *args, **kwargs)
        return wrapper
    return decorator


# ── Per-action matrix checks (with the empty-matrix safety net) ───────────────

def matrix_allows(profile, module: str, *actions) -> bool:
    """True when the RoleModuleAccess matrix grants any of `actions` on `module`.

    Admins always pass (as StaffProfile.can_do). If the matrix was never seeded
    (RoleModuleAccess empty) nothing is denied — the same safety net as
    core.middleware.module_access — so a fresh install does not lock everyone but
    admins out; the gap is logged instead."""
    if profile is None or not profile.is_active:
        return False
    if profile.role == 'admin':
        return True
    from core.middleware import module_access
    if not module_access._grants()[1]:
        import logging
        logging.getLogger('elrezeiky.rbac').error('RBAC matrix empty — %s.%s not enforced', module, actions)
        return True
    return any(profile.can_do(module, a) for a in actions)


def deny_unless(request, module: str, *actions):
    """For function views: None when the matrix allows any of `actions`, else a 403."""
    if matrix_allows(_get_profile(request), module, *actions):
        return None
    return Response({'detail': 'ليس لديك صلاحية لهذا الإجراء'}, status=status.HTTP_403_FORBIDDEN)
