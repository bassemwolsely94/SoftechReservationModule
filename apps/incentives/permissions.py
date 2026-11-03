"""
apps/incentives/permissions.py

Incentives payroll is for all-branch admins, quality managers and purchasing only (owner decisions
2026-11-03). On top of the matrix grant (MatrixPermission, module 'incentives'), the caller must
hold one of those roles AND see every branch (core.branch_scope.sees_everything): a matrix
override for another role, or one of these roles narrowed to some branches, is refused.
The caller's own progress (/api/incentives/my-progress/) is not payroll and stays open.
"""
from rest_framework.permissions import BasePermission

PAYROLL_ROLES = ('admin', 'quality_manager', 'purchasing')


class IncentivesPayrollAccess(BasePermission):
    message = 'الحوافز متاحة للمدير ومدير الجودة والمشتريات على كل الفروع فقط.'

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
