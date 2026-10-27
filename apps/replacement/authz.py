"""
apps/replacement/authz.py — WHO may do WHAT on a بدل case (doc 25 §8, owner D12).

Two layers, both server-side:
  1. Role matrix (RoleModuleAccess, module 'replacement'): view / create / edit / approve /
     finalize(=post legs). Authoritative once seeded; role fallback while unseeded.
  2. Optional per-employee ReplacementGrant: switches an action off for that person, limits the
     source types / settlement modes they may use, caps case size, approval amount and how far
     they may LOWER the deduction (patient-favourable override).
"""
from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import PermissionDenied

from . import config as C

MODULE = 'replacement'
ACTION_TO_MATRIX = {'view': 'view', 'create': 'create', 'edit': 'edit', 'approve': 'approve', 'post': 'finalize'}
FALLBACK_ROLES = {
    'view':    {'admin', 'supervisor', 'purchasing', 'quality_manager', 'pharmacist'},
    'create':  {'admin', 'supervisor', 'pharmacist'},
    'edit':    {'admin', 'supervisor'},
    'approve': {'admin', 'supervisor'},
    'post':    {'admin', 'supervisor'},
}


def grant(staff):
    g = getattr(staff, 'replacement_grant', None) if staff else None
    return g if (g is not None and g.is_active) else None


def role_allows(staff, action: str) -> bool:
    if staff is None or not staff.is_active:
        return False
    if getattr(staff.user, 'is_superuser', False) or staff.role == 'admin':
        return True
    from apps.users.models import RoleModuleAccess
    if RoleModuleAccess.objects.filter(module=MODULE).exists():
        return staff.can_do(MODULE, ACTION_TO_MATRIX[action])
    return staff.role in FALLBACK_ROLES[action]


def allows(staff, action: str) -> bool:
    if not role_allows(staff, action):
        return False
    g = grant(staff)
    if g is None:
        return True
    flag = {'create': g.can_create, 'approve': g.can_approve, 'post': g.can_post}.get(action, True)
    return bool(flag)


def require(staff, action: str, case=None, amount=None):
    """Raise PermissionDenied unless `staff` may perform `action` (on `case`, for `amount`)."""
    if not allows(staff, action):
        raise PermissionDenied('ليس لديك صلاحية لهذا الإجراء على حالات البدل.')
    if case is not None and staff and not getattr(staff.user, 'is_superuser', False):
        ids = staff.accessible_branch_ids
        if ids is not None and case.branch_id not in ids:
            raise PermissionDenied('هذه الحالة خارج فروعك.')
    g = grant(staff)
    if g is None or case is None:
        return
    if g.allowed_sources and case.source_type not in g.allowed_sources:
        raise PermissionDenied('غير مسموح لك بهذا النوع من حالات البدل.')
    if g.allowed_modes and case.settlement_mode not in g.allowed_modes:
        raise PermissionDenied('غير مسموح لك بطريقة الصرف هذه.')
    if amount is not None:
        cap = g.approve_limit if action == 'approve' else g.max_case_entitlement if action == 'create' else None
        if cap is not None and Decimal(amount) > cap:
            raise PermissionDenied(f'المبلغ يتجاوز الحد المسموح لك ({cap}).')


def max_override_pp(staff) -> Decimal:
    """How many percentage points this employee may LOWER the rule's deduction."""
    g = grant(staff)
    if g is not None:
        return Decimal(g.max_override_pp)
    if staff is None:
        return Decimal('0')
    return Decimal(str(C.get('ROLE_MAX_OVERRIDE_PP').get(staff.role, 0)))
