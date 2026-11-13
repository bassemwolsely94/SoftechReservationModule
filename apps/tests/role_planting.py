"""Test helper: plant a new permission role in the role registry for the length of a `with` block.

    with planted_role():                       # 'night_cashier', every attribute at its default
        ...
    with planted_role('auditor', 'مراجع', 'Auditor', all_branches=True):
        ...

It appends a `Role` to `apps.users.roles.ROLES`, recomputes every derived constant (ROLES, ROLE_KEYS,
ROLE_CHOICES, ROLE_BY_KEY, ALL_BRANCH_ROLES, MFA_REQUIRED_ROLES, LEGACY_RBAC_ROLES) and swaps the
new values into every loaded module that copied one at import time (`from apps.users.roles import
ALL_BRANCH_ROLES`, `from .models import MFA_REQUIRED_ROLES`, aliases included) — found by object
identity, so a copy added later is covered without editing this file. Everything is restored on exit.

Not patched: model fields' `choices=` (bound when the model class was built — Django does not
validate choices on save, so a planted role still saves), and lists a module derived from a constant
at import (e.g. `ROLES = [r for r, _ in ROLE_CHOICES]`): those keep the ten real roles.
"""
from __future__ import annotations

import sys
from contextlib import contextmanager

from apps.users import roles

_DERIVED = ('ROLES', 'ROLE_KEYS', 'ROLE_CHOICES', 'ROLE_BY_KEY', 'ALL_BRANCH_ROLES',
            'MFA_REQUIRED_ROLES', 'LEGACY_RBAC_ROLES')


def _derive(all_roles):
    return {
        'ROLES': tuple(all_roles),
        'ROLE_KEYS': tuple(r.key for r in all_roles),
        'ROLE_CHOICES': [(r.key, r.description) for r in all_roles],
        'ROLE_BY_KEY': {r.key: r for r in all_roles},
        'ALL_BRANCH_ROLES': tuple(r.key for r in all_roles if r.all_branches),
        'MFA_REQUIRED_ROLES': frozenset(r.key for r in all_roles if r.mfa_required),
        'LEGACY_RBAC_ROLES': frozenset(r.key for r in all_roles if r.legacy_rbac_mode),
    }


@contextmanager
def planted_role(key='night_cashier', label_ar='كاشير ليلي', label_en='Night cashier', **attrs):
    """Yields the planted `Role`. `attrs` are Role fields (description, all_branches,
    mfa_required, legacy_rbac_mode); description defaults to label_en."""
    if roles.is_known(key):
        raise ValueError(f'{key!r} is already a registry role')
    attrs.setdefault('description', label_en)
    role = roles.Role(key, label_ar, label_en, **attrs)

    old = {name: getattr(roles, name) for name in _DERIVED}
    new = _derive(old['ROLES'] + (role,))
    # skip empty values: shared singletons like () must never be swapped by identity
    by_id = {id(value): name for name, value in old.items() if value}

    swapped = []   # (module, attribute, previous value)
    for module in list(sys.modules.values()):
        try:
            namespace = vars(module)
        except TypeError:
            continue
        for attr, value in list(namespace.items()):
            name = by_id.get(id(value))
            if name is not None and value is old[name]:
                swapped.append((module, attr, value))

    try:
        for module, attr, value in swapped:
            setattr(module, attr, new[by_id[id(value)]])
        yield role
    finally:
        for module, attr, value in swapped:
            setattr(module, attr, value)
