"""
apps/incentives/permissions.py

Incentives payroll is for all-branch quality managers and admins only (owner decision
2026-11-03). On top of the matrix grant (MatrixPermission, module 'incentives'), the caller must
hold the admin or quality_manager role AND see every branch (core.branch_scope.sees_everything):
a matrix override for another role, or a quality manager narrowed to some branches, is refused.
The caller's own progress (/api/incentives/my-progress/) is not payroll and stays open.
"""
from rest_framework.permissions import BasePermission

PAYROLL_ROLES = ('admin', 'quality_manager')


class IncentivesPayrollAccess(BasePermission):
    message = 'الحوافز متاحة لمدير الجودة والمدير على كل الفروع فقط.'

    def has_permission(self, request, view):
        from core.branch_scope import sees_everything
        user = request.user
        if not (user and user.is_authenticated):
            return False
        profile = getattr(user, 'staff_profile', None)
        if profile is None:
            return bool(user.is_superuser)
        return profile.role in PAYROLL_ROLES and sees_everything(profile) and not \
            profile.restricted_branches.exists()
