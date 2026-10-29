"""
apps/tests/security/sweep.py

The role × route sweep engine (driven by test_role_sweep.py; Batches 4/5 reuse it).

Every protected /api/ route × GET and POST {} is sent by every non-admin role AND by
admin. Expectations come from the code role matrix via module_access.required().
classify() is the single source of truth for a request's verdict.
"""
import logging
from dataclasses import dataclass, field

from django.db import transaction
from django.test import override_settings

from core.middleware.module_access import required

from .fixtures import NON_ADMIN_ROLES, granted
from .routes import Tripwire, api_routes, handles, is_public, known_public, view_id

# Detail routes are called with an id no fixture can create, so a verdict never depends on
# the database's id sequence (fresh CI database vs reused local one). Until Batches 4/5
# seed real records, every denied detail request is therefore 'unproven', honestly.
SWEEP_ID = '987654321'

_OK_ALWAYS = {301, 503}          # trailing-slash redirect / feature switched off — no data
_REFUSED = {401, 403, 405}


def classify(allowed: bool, code, admin_code) -> str:
    """Verdict for one request: ok | leak | crash | overblock | unproven.

    Matrix denies the role:
      401/403/405, 301/503 → ok
      404 → ok when admin got further (genuine deny-by-404); 'unproven' when admin
            also got 404 — the route was never reached (id 1 doesn't exist), so the
            permission check is unexercised
      500/raised → crash;  anything else (2xx, 302, 400, 409, 415, 422, 429 …) → leak
            (400 means validation ran, so permission had already passed)
    Matrix grants the role: 403 → overblock · 500/raised → crash · else ok.
    """
    if code == 500 or isinstance(code, str):
        return 'crash'
    if allowed:
        return 'overblock' if code == 403 else 'ok'
    if code in _REFUSED or code in _OK_ALWAYS:
        return 'ok'
    if code == 404:
        return 'unproven' if admin_code == 404 else 'ok'
    return 'leak'


@dataclass
class SweepResult:
    leaks: set = field(default_factory=set)
    overblocks: set = field(default_factory=set)
    crashes: set = field(default_factory=set)
    unproven: set = field(default_factory=set)
    softech_reach: set = field(default_factory=set)     # denied role reached SOFTECH
    outside_reach: set = field(default_factory=set)     # denied role started thread/HTTP/socket/subprocess
    classified: int = 0


def protected_routes():
    """Every /api/ route that isn't a reviewed public endpoint."""
    for path, cb in api_routes(id_value=SWEEP_ID):
        vid, cls = view_id(cb)
        if not (is_public(cls) or known_public(vid)):
            yield path


def _call(client, method, path):
    try:
        with transaction.atomic():
            r = client.post(path, {}, format='json') if method == 'POST' else client.get(path)
            transaction.set_rollback(True)
        return r.status_code
    except Exception as exc:      # raised through the test client
        return f'raised {type(exc).__name__}'


def sweep(mode: str, clients: dict, roles=NON_ADMIN_ROLES, prefixes=None) -> SweepResult:
    """Run every role (plus admin as the reference caller) over every protected route —
    or only the /api/<prefix>/ routes in `prefixes` (Batch 4 per-module tests)."""
    res = SweepResult()
    routes = [p for p in protected_routes() if prefixes is None or p.split('/')[2] in prefixes]
    previous = logging.root.manager.disable
    logging.disable(logging.CRITICAL)      # thousands of expected RBAC/app warnings
    try:
        with override_settings(RBAC_ENFORCEMENT=mode), Tripwire() as tw:
            for path in routes:
                for method in ('GET', 'POST'):
                    need = required(path, method)
                    if need is None or not handles(path, method):     # no such endpoint (Z-11b)
                        continue
                    admin_code = _call(clients['admin'], method, path)
                    if classify(True, admin_code, admin_code) == 'crash':
                        res.crashes.add(f'admin {method} {path}')
                    for role in roles:
                        res.classified += 1
                        soft, out = len(tw.softech_calls), tw.outside_count()
                        code = _call(clients[role], method, path)
                        entry = f'{role} {method} {path}'
                        allowed = granted(role, *need)
                        if not allowed and len(tw.softech_calls) > soft:
                            res.softech_reach.add(entry)
                        if not allowed and tw.outside_count() > out:
                            res.outside_reach.add(entry)
                        verdict = classify(allowed, code, admin_code)
                        if verdict == 'leak':
                            res.leaks.add(entry)
                        elif verdict == 'crash':
                            res.crashes.add(entry)
                        elif verdict == 'overblock':
                            res.overblocks.add(entry)
                        elif verdict == 'unproven':
                            res.unproven.add(entry)
    finally:
        logging.disable(previous)
        # Rolled-back requests still write the (non-transactional) Django cache —
        # don't let ~19k sweep requests leave entries behind for later tests.
        from django.core.cache import cache
        cache.clear()
    return res
