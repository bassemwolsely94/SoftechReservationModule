"""
apps/finance/recon_labels.py

Human labels for the reconciliation screens and exports: SOFTECH branch code →
branch name, SOFTECH usercode → the SOFTECH username of whoever created the
document. Both tables are tiny (≈20 branches, ≈400 users), so they are loaded
once and cached for a few minutes.

Note: ERPUser stores the SOFTECH *usercode* in `username` and the SOFTECH login
name (`users.userid`, e.g. "nabil makram") in `user_id`.
"""
from __future__ import annotations

import time

_TTL = 600
_cache = {'at': 0.0, 'branches': {}, 'users': {}}


def _maps():
    if time.time() - _cache['at'] > _TTL:
        from apps.branches.models import Branch
        from apps.users.models import ERPUser
        _cache['branches'] = {str(b.softech_branch_id): (b.name_ar or b.name or '')
                              for b in Branch.objects.all()}
        _cache['users'] = dict(ERPUser.objects.values_list('username', 'user_id'))
        _cache['at'] = time.time()
    return _cache


def branch_name(code) -> str:
    return _maps()['branches'].get(str(code or '').strip(), '')


def branch_label(code) -> str:
    code = str(code or '').strip()
    name = branch_name(code)
    return f'{code} · {name}' if name else code


def user_name(code) -> str:
    return (_maps()['users'].get(str(code or '').strip(), '') or '').strip()


def user_label(code) -> str:
    code = str(code or '').strip()
    if not code:
        return '—'
    name = user_name(code)
    return f'{name} ({code})' if name else code
