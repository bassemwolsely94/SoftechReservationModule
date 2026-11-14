"""Role registry: the single source for permission-role keys, labels and attributes.

Must not import Django models (core.branch_scope imports this module).
Derived constants are computed once at import time from ROLES.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Role:
    key: str
    label_ar: str
    label_en: str
    description: str                   # the text shown in ROLE_CHOICES
    all_branches: bool = False         # sees every branch (core.branch_scope)
    mfa_required: bool = True          # new roles default to 2FA (fail closed)
    legacy_rbac_mode: bool = False     # True = follows RBAC_ENFORCEMENT (log/enforce);
                                       # False = matrix always enforced (new roles)


ROLES: tuple[Role, ...] = (
    Role('admin', 'مدير النظام', 'Admin', 'Admin — Full Access',
         all_branches=True, mfa_required=True, legacy_rbac_mode=True),
    Role('call_center', 'كول سنتر', 'Call center', 'Call Center — All Branches',
         all_branches=True, mfa_required=False, legacy_rbac_mode=True),
    Role('pharmacist', 'صيدلاني', 'Pharmacist', 'Pharmacist — Own Branch',
         all_branches=False, mfa_required=False, legacy_rbac_mode=True),
    Role('salesperson', 'مندوب مبيعات', 'Salesperson', 'Sales Person — Own Branch',
         all_branches=False, mfa_required=False, legacy_rbac_mode=True),
    Role('purchasing', 'مشتريات', 'Purchasing', 'Purchasing — HQ Only',
         all_branches=True, mfa_required=True, legacy_rbac_mode=True),
    Role('delivery', 'توصيل', 'Delivery', 'Delivery',
         all_branches=False, mfa_required=False, legacy_rbac_mode=True),
    Role('viewer', 'مشاهد فقط', 'Viewer', 'Viewer — Read Only',
         all_branches=False, mfa_required=False, legacy_rbac_mode=True),
    Role('supervisor', 'مشرف', 'Supervisor', 'Supervisor — Call Center Supervisor',
         all_branches=True, mfa_required=True, legacy_rbac_mode=True),
    Role('quality_manager', 'مدير الجودة', 'Quality manager', 'Quality Manager — QA & Scoring',
         all_branches=True, mfa_required=False, legacy_rbac_mode=True),
    # finance data is company-level (ruling R7, security decision B-1)
    Role('accountant', 'محاسب', 'Accountant', 'Accountant — General Ledger',
         all_branches=True, mfa_required=False, legacy_rbac_mode=True),
)

ROLE_KEYS: tuple[str, ...] = tuple(r.key for r in ROLES)
ROLE_CHOICES: list[tuple[str, str]] = [(r.key, r.description) for r in ROLES]
ROLE_BY_KEY: dict[str, Role] = {r.key: r for r in ROLES}
ALL_BRANCH_ROLES: tuple[str, ...] = tuple(r.key for r in ROLES if r.all_branches)
MFA_REQUIRED_ROLES: frozenset[str] = frozenset(r.key for r in ROLES if r.mfa_required)
LEGACY_RBAC_ROLES: frozenset[str] = frozenset(r.key for r in ROLES if r.legacy_rbac_mode)


def role_label(key: str, lang: str = 'ar') -> str:
    role = ROLE_BY_KEY.get(key)
    if role is None:
        return key
    return role.label_en if lang == 'en' else role.label_ar


def is_known(key: str) -> bool:
    return key in ROLE_BY_KEY


def as_api() -> list[dict]:
    return [{'value': r.key, 'label_ar': r.label_ar, 'label_en': r.label_en,
             'description': r.description} for r in ROLES]
