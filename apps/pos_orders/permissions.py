"""
apps/pos_orders/permissions.py

RBAC for the Indirect-POS module. Backend is final authority (frontend gating is
UX only). Uses StaffProfile.can_do('pos_orders', <action>) when the RBAC matrix is
seeded; otherwise falls back to a role allow-list.
"""
from rest_framework.permissions import BasePermission

# Roles allowed to push a pending order to the cashier / cancel one, when the
# RBAC matrix has no explicit pos_orders rows yet.
PUSH_ROLES = {'admin', 'supervisor', 'call_center', 'pharmacist', 'salesperson'}


def _profile(request):
    return getattr(request.user, 'staff_profile', None)


class CanOperatePosOrders(BasePermission):
    """POS orders follow the `pos` matrix (Batch 4, Z-5b): GET view, POST create, PUT/PATCH edit,
    DELETE delete. PUSH_ROLES only while no `pos` row is seeded (as CanViewPos) — "any active
    staff" let delivery, purchasing, quality and viewer read and create sale orders, and any
    logged-in user DELETE any order."""
    def has_permission(self, request, view):
        p = _profile(request)
        if not (p and p.is_active):
            return False
        if p.role == 'admin':
            return True
        if view is not None and not hasattr(view, request.method.lower()):
            return True                                  # no handler for the method: DRF answers 405
        from core.middleware import module_access
        if 'pos' not in module_access.seeded_modules():
            return p.role in PUSH_ROLES                  # no `pos` rows seeded yet (as CanViewPos)
        from core.permissions import matrix_allows
        from rest_framework.permissions import SAFE_METHODS
        m = request.method
        needed = (('view',) if m in SAFE_METHODS else ('create',) if m == 'POST'
                  else ('edit',) if m in ('PUT', 'PATCH') else ('delete',))
        return matrix_allows(p, 'pos', *needed)


class CanPushPosOrders(BasePermission):
    """Push-to-cashier and cancel — operator roles only.

    Authoritative source is the RBAC matrix (`pos`/create); the PUSH_ROLES
    allow-list is only a fallback for a DB where the `pos` rows aren't seeded yet.
    """
    def has_permission(self, request, view):
        p = _profile(request)
        if not (p and p.is_active):
            return False
        if p.role == 'admin':
            return True
        try:
            if p.can_do('pos', 'create'):
                return True
        except Exception:
            pass
        return p.role in PUSH_ROLES


class CanViewPos(BasePermission):
    """Contract-assist / FEFO helper endpoints — roles with the POS module (`pos`/view).

    The RBAC matrix is authoritative: once a role has ANY `pos` row (seeded), an explicit
    denial is final. PUSH_ROLES is the fallback only for a role with no `pos` rows at all.
    A failing matrix lookup denies — it never falls back to allow.
    """
    def has_permission(self, request, view):
        p = _profile(request)
        if not (p and p.is_active):
            return False
        if p.role == 'admin':
            return True
        try:
            from apps.users.models import RoleModuleAccess
            if RoleModuleAccess.objects.filter(role=p.role, module='pos').exists():
                return bool(p.can_do('pos', 'view'))
        except Exception:
            return False
        return p.role in PUSH_ROLES
