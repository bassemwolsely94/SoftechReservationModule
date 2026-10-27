"""
Server-side permissions for the market-shortage (نواقص السوق, /market-shortage) and
phantom-sales (مبيعات وهمية, /phantom-sales) APIs. Until 2026-10-26 these endpoints
only required a login; the role limit lived in the React RequireRole alone, so any
staff member could confirm/dismiss a shortage — which writes itemmodified /
itemcode_alt2 / itemnomoreuse to SOFTECH via shortage_writer (CLAUDE.md rule 9).

Matrix module: the screens are the نواقص domain, so the 'shortage' grants decide
(pharmacist / supervisor / purchasing hold shortage/approve; quality_manager holds
view + export). The URLs live under /api/purchasing/, so a 'purchasing' grant for the
same action is accepted too.

Each endpoint names the action it needs:
  reads (candidates, deltas, lists, search, trends, …) → view
  Excel export                                          → export
  flag / unflag / dismiss / retrieve (SOFTECH writes)   → approve
  phantom confirm / exclude / reset (local only)        → edit

Admins bypass the matrix (as StaffProfile.can_do does). Fallback: if the matrix was
never seeded (RoleModuleAccess empty) the old frontend role list decides instead, so
a fresh install neither locks everyone out nor opens the screens to every role.
"""
import logging

from rest_framework.permissions import BasePermission

logger = logging.getLogger('elrezeiky.rbac')

MODULES = ('shortage', 'purchasing')
FALLBACK_ROLES = {'admin', 'purchasing', 'pharmacist', 'supervisor', 'quality_manager'}
DENIED = 'ليس لديك صلاحية لهذا الإجراء في النواقص'


def _profile(request):
    user = getattr(request, 'user', None)
    return getattr(user, 'staff_profile', None) or getattr(user, 'staffprofile', None)


def _matrix_seeded():
    from core.middleware import module_access
    return module_access._grants()[1]


def can(profile, action):
    """True when the matrix grants `action` on shortage or purchasing."""
    if profile is None:
        return False
    if profile.role == 'admin':
        return True
    if not _matrix_seeded():
        logger.error('RBAC matrix empty — shortage permission falls back to role list')
        return profile.role in FALLBACK_ROLES
    return any(profile.can_do(m, action) for m in MODULES)


def requires(action):
    """A DRF permission class that needs `action` (see the table above)."""

    class ShortageAccess(BasePermission):
        message = DENIED

        def has_permission(self, request, view):
            if not (request.user and request.user.is_authenticated):
                return False
            return can(_profile(request), action)

    ShortageAccess.__name__ = f'ShortageAccess_{action}'
    return ShortageAccess


CanView = requires('view')
CanExport = requires('export')
CanEdit = requires('edit')
CanApprove = requires('approve')
