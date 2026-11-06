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

# Every method the matrix maps: GET → view, POST → a write grant, PUT / PATCH → edit, DELETE →
# delete (Batch 4, Z-12 — GET / POST only until then). A method the view lacks is skipped.
METHODS = ('GET', 'POST', 'PUT', 'PATCH', 'DELETE')

# Round 2, R4 step 3: screens behind a feature flag answer 503 while it is off, which every sweep
# reads as "ok" — the view behind it was never checked. The sweeps run with these READ/feature flags
# ON. Send and SOFTECH-write switches stay OFF (and the Tripwire blocks any send anyway).
FEATURE_FLAGS_ON = {
    'DAILY_COUNT_ENABLED': True,              # Project 2 daily counts (apps/stockcount/daily)
    'USAGE_PRINT_ENABLED': True,              # Project 5 usage slip (apps/usage_print)
    'MISSED_SALES_ENABLED': True,             # Project 3 missed sales (apps/pos_orders)
    'MISSED_CALL_CALLBACKS_ENABLED': True,    # Project 3 call-backs (apps/pbx, pic_analytics)
    'COUNSELLING_CONTENT_ENABLED': True,      # Project 4 counselling sheets (apps/counselling)
}

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
            if method == 'GET':
                r = client.get(path)
            elif method == 'DELETE':
                r = client.delete(path)
            else:                                       # POST / PUT / PATCH with an empty body
                r = getattr(client, method.lower())(path, {}, format='json')
            transaction.set_rollback(True)
        return r.status_code
    except Exception as exc:      # raised through the test client
        return f'raised {type(exc).__name__}'


# ── Round 2, R3: real records behind detail routes ───────────────────────────────────────────────
# A detail route rendered with SWEEP_ID answers 404 to everyone, so a denied role's 404 proves
# nothing ('unproven'). seed_detail_paths() finds, per such route, a model whose planted row admin
# CAN reach: it tries the view's own model first, then the app's models closest in name to the
# path, and keeps the first one for which admin gets past 404. The sweep then sends every role to
# that real path; verdicts and baselines keep the canonical SWEEP_ID path, so pks never leak into
# baseline lines.
_PLACEHOLDERS = (SWEEP_ID, 'x', '00000000-0000-0000-0000-000000000000')
_MAX_CANDIDATES = 8


def _norm(s):
    return ''.join(ch for ch in str(s).lower() if ch.isalnum())


def _placeholder_kwargs(match):
    return [k for k, v in match.kwargs.items() if str(v) in _PLACEHOLDERS]


def _view_model(cls):
    for attr in ('queryset',):
        qs = getattr(cls, attr, None)
        if qs is not None and hasattr(qs, 'model'):
            return qs.model
    ser = getattr(cls, 'serializer_class', None)
    meta = getattr(ser, 'Meta', None)
    return getattr(meta, 'model', None)


def _candidates(path, match, kwarg):
    """Models that may sit behind `kwarg` of `path`, most likely first."""
    from difflib import SequenceMatcher

    from django.apps import apps as django_apps
    cb = match.func
    cls = getattr(cb, 'cls', None) or getattr(cb, 'view_class', None)
    out = []
    if cls is not None and kwarg == (getattr(cls, 'lookup_url_kwarg', None)
                                     or getattr(cls, 'lookup_field', None) or 'pk'):
        m = _view_model(cls)
        if m is not None:
            out.append(m)
    module = getattr(cls, '__module__', None) or getattr(cb, '__module__', '')
    app = django_apps.get_containing_app_config(module)
    segs = [s for s in path.split('/') if s and s not in _PLACEHOLDERS]
    hint_kw = kwarg.lower()
    for suf in ('_pk', '_id', '_code', '_key'):
        hint_kw = hint_kw[:-len(suf)] if hint_kw.endswith(suf) else hint_kw
    # the segment written just before this kwarg's placeholder names its model most often
    idx = list(match.kwargs).index(kwarg)
    parts = path.strip('/').split('/')
    ph = [i for i, s in enumerate(parts) if s in _PLACEHOLDERS]
    before = parts[ph[idx] - 1] if idx < len(ph) and ph[idx] > 0 else ''
    hints = [_norm(h) for h in (hint_kw, before, before.rstrip('s'), getattr(cls, '__name__', ''),
                                getattr(cb, '__name__', '')) + tuple(segs[-2:]) if h and _norm(h)]
    pool = list(app.get_models()) if app else []
    if hint_kw not in ('pk', 'id', 'key', 'code', 'slug'):
        pool += [m for m in django_apps.get_models() if _norm(m.__name__) == _norm(hint_kw)]

    def score(m):
        name = _norm(m.__name__)
        return max(SequenceMatcher(None, name, h).ratio() for h in hints) if hints else 0
    for m in sorted(pool, key=score, reverse=True):
        if m not in out and not m._meta.proxy and m._meta.managed:
            out.append(m)
    return out[:_MAX_CANDIDATES]


def _value_for(obj, kwarg, cls):
    lookup = getattr(cls, 'lookup_field', None) if cls is not None else None
    if kwarg in ('pk', 'id') or kwarg.endswith(('_pk', '_id')):
        return obj.pk
    if lookup and lookup != 'pk' and hasattr(obj, lookup):
        return getattr(obj, lookup)
    if hasattr(obj, kwarg) and not callable(getattr(obj, kwarg)):
        return getattr(obj, kwarg)
    return obj.pk


def _fill(path, values):
    """Put values (in kwarg order) into the placeholder segments of path."""
    parts, it = path.split('/'), iter(values)
    out = []
    for s in parts:
        if s in _PLACEHOLDERS:
            v = next(it, None)
            out.append(s if v is None else str(v))
        else:
            out.append(s)
    return '/'.join(out)


def _parent_value(obj, kwarg, planter):
    """Value for an outer kwarg (a parent record) taken from the child's own FK, so the nested
    path is consistent; a planted neutral row of the closest-named model otherwise."""
    want = _norm(kwarg.rsplit('_', 1)[0] if kwarg.endswith(('_pk', '_id')) else kwarg)
    for f in obj._meta.concrete_fields:
        if f.is_relation and want and (_norm(f.name) == want or _norm(f.related_model.__name__) == want
                                       or _norm(f.related_model.__name__).endswith(want)):
            return getattr(obj, f.attname)
    for f in obj._meta.concrete_fields:              # nested router: parent is the only FK
        if f.is_relation and f.related_model.__module__.split('.')[:2] == obj.__module__.split('.')[:2]:
            return getattr(obj, f.attname)
    return None


def seed_detail_paths(admin_client, planter, routes) -> dict:
    """{canonical SWEEP_ID path: real path} for every route admin cannot reach with SWEEP_ID."""
    with override_settings(**FEATURE_FLAGS_ON):
        return _seed_detail_paths(admin_client, planter, routes)


def _seed_detail_paths(admin_client, planter, routes) -> dict:
    from django.urls import Resolver404, resolve
    seeded = {}
    for path in routes:
        if not any(seg in _PLACEHOLDERS for seg in path.split('/')):
            continue
        methods = [m for m in METHODS if required(path, m) is not None and handles(path, m)]
        if not methods:
            continue
        if any(_call(admin_client, m, path) != 404 for m in methods):
            continue
        try:
            match = resolve(path)
        except Resolver404:
            continue
        kws = _placeholder_kwargs(match)
        if not kws:
            continue
        cls = getattr(match.func, 'cls', None) or getattr(match.func, 'view_class', None)
        last = kws[-1]
        for model in _candidates(path, match, last):
            obj = planter.instance(model)
            if obj is None:
                continue
            vals = [_parent_value(obj, k, planter) for k in kws[:-1]] + [_value_for(obj, last, cls)]
            real = _fill(path, vals)
            if real == path:
                continue
            if any(_call(admin_client, m, real) not in (404,) for m in methods):
                seeded[path] = real
                break
    return seeded


def sweep(mode: str, clients: dict, roles=NON_ADMIN_ROLES, prefixes=None, seeded=None) -> SweepResult:
    """Run every role (plus admin as the reference caller) over every protected route —
    or only the /api/<prefix>/ routes in `prefixes` (Batch 4 per-module tests). `seeded` maps a
    canonical detail path to the same route with a real record (seed_detail_paths)."""
    seeded = seeded or {}
    res = SweepResult()
    routes = [p for p in protected_routes() if prefixes is None or p.split('/')[2] in prefixes]
    previous = logging.root.manager.disable
    logging.disable(logging.CRITICAL)      # thousands of expected RBAC/app warnings
    try:
        with override_settings(RBAC_ENFORCEMENT=mode, **FEATURE_FLAGS_ON), Tripwire() as tw:
            for path in routes:
                for method in METHODS:
                    need = required(path, method)
                    if need is None or not handles(path, method):     # no such endpoint (Z-11b)
                        continue
                    real = seeded.get(path, path)
                    admin_code = _call(clients['admin'], method, real)
                    if classify(True, admin_code, admin_code) == 'crash':
                        res.crashes.add(f'admin {method} {path}')
                    for role in roles:
                        res.classified += 1
                        soft, out = len(tw.softech_calls), tw.outside_count()
                        code = _call(clients[role], method, real)
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


def planted_detail_paths(client, planter, routes, marker) -> dict:
    """Round 2, R4 step 2: {canonical GET detail path: path to a PLANTED (marked) record} for every
    detail route where `client` (admin, the positive control) sees the marker at that path."""
    from django.apps import apps as django_apps
    from django.urls import Resolver404, resolve
    out = {}
    with override_settings(**FEATURE_FLAGS_ON):
        for path in routes:
            if not any(seg in _PLACEHOLDERS for seg in path.split('/')) or not handles(path, 'GET'):
                continue
            try:
                match = resolve(path)
            except Resolver404:
                continue
            kws = _placeholder_kwargs(match)
            if not kws:
                continue
            cls = getattr(match.func, 'cls', None) or getattr(match.func, 'view_class', None)
            for model in _candidates(path, match, kws[-1]):
                # the model's own planted row, else the neutral parent of one (a push whose marked
                # lines are planted). Without this the next candidate's id was used on this route,
                # which only worked when the two ids happened to match.
                pk = planter.planted.get(model._meta.label)
                if pk is None:
                    pk = getattr(planter.neutral.get(model), 'pk', None)
                if pk is None:
                    continue
                obj = django_apps.get_model(model._meta.label).objects.filter(pk=pk).first()
                if obj is None:
                    continue
                vals = [_parent_value(obj, k, planter) for k in kws[:-1]] + [_value_for(obj, kws[-1], cls)]
                real = _fill(path, vals)
                try:
                    with transaction.atomic():
                        r = client.get(real)
                        transaction.set_rollback(True)
                    body = r.content.decode('utf-8', 'replace') if 'json' in r.get('Content-Type', '') else ''
                except Exception:          # noqa: BLE001 — crashes are the role sweep's business
                    continue
                if r.status_code == 200 and marker in body:
                    out[path] = real
                    break
    return out
