"""
apps/insurance/permissions.py

Server-side access control for the confidential insurance module, layered on the
project's dynamic RBAC (StaffProfile.can_do → RoleModuleAccess).  BACKEND IS THE
FINAL AUTHORITY — frontend/nav checks are UX only.

Action mapping (per request) onto the RBAC action vocabulary:
    GET/HEAD/OPTIONS            → 'view'
    change-status (issue/submit)→ 'finalize'
    DELETE                      → 'delete'
    everything else that writes → 'edit'

admin bypasses (can_do returns True for admin); every other role needs an
explicit RoleModuleAccess grant, so an un-granted role is denied by default.
"""
from rest_framework.permissions import BasePermission, SAFE_METHODS


def _profile(request):
    return getattr(request.user, 'staff_profile', None)


def _action_for(request, view):
    if request.method in SAFE_METHODS:
        return 'view'
    if getattr(view, 'action', None) in ('change_status',):
        return 'finalize'
    if request.method == 'DELETE':
        return 'delete'
    return 'edit'


class _ModuleAccess(BasePermission):
    module = None

    def has_permission(self, request, view):
        u = request.user
        if not (u and u.is_authenticated):
            return False
        if u.is_superuser:                       # Django superuser always allowed
            return True
        p = _profile(request)
        if not (p and p.is_active):
            return False
        return p.can_do(self.module, _action_for(request, view))


class InsuranceModuleAccess(_ModuleAccess):
    module = 'insurance'


class CommerceModuleAccess(_ModuleAccess):
    module = 'commerce'
