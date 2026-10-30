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
    """The all-branch roles (core.branch_scope.ALL_BRANCH_ROLES) or access_all_branches."""

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

    Admins always pass (as StaffProfile.can_do). If `module` was never seeded (no row for it at
    all) nothing is denied, so a fresh install — or a database holding only some data
    migrations' rows — does not lock everyone but admins out; the gap is logged instead.
    Per module since Batch 4, Z-5c (was: any row anywhere = whole matrix seeded)."""
    if profile is None or not profile.is_active:
        return False
    if profile.role == 'admin':
        return True
    from core.middleware import module_access
    if module not in module_access.seeded_modules():
        import logging
        logging.getLogger('elrezeiky.rbac').error('RBAC module %s not seeded — %s not enforced', module, actions)
        return True
    if any(profile.can_do(module, a) for a in actions):
        return True
    # SOFTECH supply groups work purchasing with the purchasing role's grants (Z-2).
    return module == 'purchasing' and module_access.supply_member(profile) and any(
        (module, a) in module_access._grants()[0].get('purchasing', set()) for a in actions)


class MatrixPermission(BasePermission):
    """Checks the matrix per request. The view names its module and, optionally,
    the actions each viewset action needs:

        permission_classes = [IsAuthenticated, MatrixPermission]
        rbac_module  = 'incentives'
        rbac_actions = {'finalize': ('finalize',), 'export_settlements': ('export',)}

    Anything not listed: GET/HEAD/OPTIONS → view, POST → create, PUT/PATCH → edit,
    DELETE → delete (or the view's `rbac_delete` tuple). An empty tuple means the
    action is open to every logged-in user (e.g. a lookup other screens read)."""
    message = 'ليس لديك صلاحية لهذا الإجراء'

    def has_permission(self, request, view):
        from rest_framework.permissions import SAFE_METHODS
        needed = (getattr(view, 'rbac_actions', None) or {}).get(getattr(view, 'action', None))
        if needed is None:
            if request.method in SAFE_METHODS:
                needed = ('view',)
            elif request.method == 'POST':
                needed = ('create',)
            elif request.method in ('PUT', 'PATCH'):
                needed = ('edit',)
            else:
                needed = getattr(view, 'rbac_delete', ('delete',))
        if not needed:
            return True
        return matrix_allows(_get_profile(request), view.rbac_module, *needed)


def matrix_permission(module: str, *, get=('view',), post=('create',), edit=('edit',), delete=('delete',),
                      actions=None):
    """MatrixPermission for views that don't carry `rbac_module` (function views mostly):

        FINANCE = matrix_permission('finance')                     # GET view · POST create
        @permission_classes([IsAuthenticated, matrix_permission('finance', post=('approve',))])

    PUT/PATCH need `edit`, DELETE `delete` (both overridable, e.g. delete=('edit',) where the
    editors remove lines). `actions` maps a viewset action to its own tuple, whatever the method
    (e.g. {'quality': ('view',)} where the view's role check decides). Same checks as matrix_allows
    (Batch 4)."""
    class _ModuleMatrix(BasePermission):
        message = MatrixPermission.message

        def has_permission(self, request, view):
            from rest_framework.permissions import SAFE_METHODS
            m = request.method
            if view is not None and not hasattr(view, m.lower()):
                return True                  # no handler for the method: DRF answers 405 (Z-5b)
            needed = (actions or {}).get(getattr(view, 'action', None))
            if needed is None:
                needed = (get if m in SAFE_METHODS else post if m == 'POST'
                          else edit if m in ('PUT', 'PATCH') else delete)
            return matrix_allows(_get_profile(request), module, *needed)

    _ModuleMatrix.__name__ = _ModuleMatrix.__qualname__ = f'Matrix_{module}'
    return _ModuleMatrix


def deny_unless(request, module: str, *actions):
    """For function views: None when the matrix allows any of `actions`, else a 403."""
    if matrix_allows(_get_profile(request), module, *actions):
        return None
    return Response({'detail': 'ليس لديك صلاحية لهذا الإجراء'}, status=status.HTTP_403_FORBIDDEN)
