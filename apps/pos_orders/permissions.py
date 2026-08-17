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
    """Create / view POS orders — any active staff member."""
    def has_permission(self, request, view):
        p = _profile(request)
        return bool(p and p.is_active)


class CanPushPosOrders(BasePermission):
    """Push-to-cashier and cancel — operator roles only."""
    def has_permission(self, request, view):
        p = _profile(request)
        if not (p and p.is_active):
            return False
        if p.role == 'admin':
            return True
        try:
            if p.can_do('pos_orders', 'create'):
                return True
        except Exception:
            pass
        return p.role in PUSH_ROLES
