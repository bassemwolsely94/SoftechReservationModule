"""
apps/approvals/permissions.py

RBAC for the generic approval inbox. Backend is the final authority (frontend
route guards are UX only). Uses StaffProfile.can_do('approvals', <action>) when the
RBAC matrix is seeded; otherwise falls back to the approver role allow-list so the
inbox is never accidentally locked out before `seed_permissions` runs.

Per-step decide eligibility is still enforced separately in
ApprovalService._assert_eligible — this class only gates inbox access.
"""
from rest_framework.permissions import BasePermission

# Roles that approve at least one workflow step (see seed_approval_workflows).
APPROVER_ROLES = {'admin', 'supervisor', 'pharmacist', 'purchasing', 'quality_manager'}


def _profile(request):
    return getattr(request.user, 'staff_profile', None)


class CanViewApprovals(BasePermission):
    """View the approval inbox / workflows. Approver roles only."""
    def has_permission(self, request, view):
        p = _profile(request)
        if not (p and p.is_active):
            return False
        if p.role == 'admin':
            return True
        try:
            if p.can_do('approvals', 'view'):
                return True
        except Exception:
            pass
        return p.role in APPROVER_ROLES
