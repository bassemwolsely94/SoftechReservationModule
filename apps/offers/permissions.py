"""RBAC for offers — money-critical, so writes are tightly gated.

Matrix module `offers` (Batch 4, Z-5a; owner 2026-10-27 — under المخزون, not POS): GET needs
view, POST create, PUT/PATCH edit, DELETE delete. Only on a database whose matrix was never
seeded does the old rule apply (read: any active staff; write: WRITE_ROLES) — an empty matrix
must not open offer writes to everyone."""
from rest_framework.permissions import BasePermission, SAFE_METHODS

WRITE_ROLES = {'admin', 'supervisor', 'purchasing'}


class CanManageOffers(BasePermission):
    message = 'ليس لديك صلاحية على العروض'

    def has_permission(self, request, view):
        p = getattr(request.user, 'staff_profile', None)
        if not (p and p.is_active):
            return False
        if view is not None and hasattr(view, 'action') and view.action is None:
            return True                       # a method the route lacks: DRF answers 405
        from core.middleware import module_access
        if 'offers' not in module_access.seeded_modules():   # offers rows not added yet (Z-5c)
            return request.method in SAFE_METHODS or p.role in WRITE_ROLES
        from core.permissions import matrix_allows
        m = request.method
        needed = (('view',) if m in SAFE_METHODS else ('create',) if m == 'POST'
                  else ('edit',) if m in ('PUT', 'PATCH') else ('delete',))
        return matrix_allows(p, 'offers', *needed)
