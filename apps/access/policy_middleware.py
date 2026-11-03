"""
Zone policy middleware (N3): refuses what the role's zone does not allow.

Runs after ModuleAccessMiddleware, so the role's own module matrix has already been applied;
this only narrows. Mode is NETWORK_POLICY_ENFORCEMENT (off / log / enforce), read per request.
Never raises: an internal error lets the request through in log / off mode and refuses in enforce.
"""
import json
import logging

from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse

from core.auth_cookies import user_from_request
from core.middleware import module_access

from . import policy, session_policy
from .network import INTERNAL

log = logging.getLogger('elrezeiky.access')

LOG_DEDUPE_SECONDS = 600
DENY_DEDUPE_SECONDS = 60
MAX_BODY_BYTES = 1024 * 1024
ERROR_MESSAGE = 'تعذر التحقق من صلاحية الدخول — حاول مرة أخرى'


UNSAFE_LOG_SECONDS = 600


def enforce_problem():
    """Why `enforce` cannot be trusted with the current settings (access.E004 / E003), else None."""
    if not getattr(settings, 'NETWORK_ENFORCE_GUARD', True):
        return None
    if not getattr(settings, 'NETWORK_HEADER_TRUSTED', False):
        return ('access.E004: NETWORK_HEADER_TRUSTED is False, so inside and outside cannot be told apart')
    if not getattr(settings, 'NETWORK_PROXY_KEY', ''):
        return ('access.E003: NETWORK_PROXY_KEY is empty, so anything reaching Daphne could claim '
                'X-ElR-Network: internal')
    return None


def _log_unsafe(problem, switch='NETWORK_POLICY_ENFORCEMENT'):
    """The ERROR line for an unsafe enforce, at most once per UNSAFE_LOG_SECONDS per process and
    switch. `switch` names the setting that was downgraded (N3's, or N4's SOFTECH_GATE_ENFORCEMENT),
    so each has its own line and the runbook can grep for the one it switched."""
    try:
        if not cache.add(f'access:unsafe-enforce:{switch}:{problem[:12]}', 1, UNSAFE_LOG_SECONDS):
            return
    except Exception:
        pass
    log.error('%s=enforce refused (%s) — running as log until fixed', switch, problem)


def _mode():
    """off / log / enforce. An unknown value is log; enforce on an unsafe setup is log (I5)."""
    mode = str(getattr(settings, 'NETWORK_POLICY_ENFORCEMENT', 'log') or 'log').lower()
    if mode not in ('off', 'log', 'enforce'):
        return 'log'
    if mode == 'enforce':
        problem = enforce_problem()
        if problem:
            _log_unsafe(problem)
            return 'log'
    return mode


def _json_body(request):
    """Body-selected export routes only (BODY_EXPORTS), unsafe methods only. Fails closed: a body
    that is too big, unparseable or not a dict counts as the export, whatever the Content-Type
    (DRF parses `*/*` as JSON). Returns None for every other request, the body is never read."""
    rule = policy.BODY_EXPORTS.get(request.path_info)
    if not rule or request.method in ('GET', 'HEAD', 'OPTIONS'):
        return None
    forced = {rule[0]: rule[1]}
    try:
        if int(request.META.get('CONTENT_LENGTH') or 0) > MAX_BODY_BYTES:
            return forced
        body = json.loads(request.body or b'null')
    except Exception:
        return forced
    return body if isinstance(body, dict) else forced


def _user(request):
    """The signed-in user: the session user, else the JWT (resolved once per request)."""
    user = getattr(request, 'user', None)
    if user is not None and getattr(user, 'is_authenticated', False):
        return user
    return user_from_request(request)


def _scope(request, module):
    """Dedupe scope: the module, else the first two path segments after /api/."""
    if module:
        return module
    return '/'.join(request.path_info.split('/')[2:4])


class ZonePolicyMiddleware:

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        denied = self._check(request)
        if denied is not None:
            return denied
        return self.get_response(request)

    def _check(self, request):
        mode = _mode()
        if mode == 'off' or not request.path_info.startswith('/api/'):
            return None
        try:
            # the same policy subject as sign-in and refresh: a superuser without a profile is
            # admin, any other account without one is viewer (M1)
            profile = session_policy.subject(_user(request))
            if profile is None:
                return None
            access = getattr(request, 'access', None)
            if getattr(access, 'failed', False) and access.network.zone == INTERNAL:
                self._context_failed(request)      # F3 in the middleware too: open inside (M2)
                return None
            zone = getattr(access, 'zone', None)
            path = request.path_info
            need = module_access.required(path, request.method)
            module = need[0] if need else None
            export = policy.is_export(path, request.method, query=request.GET, body=_json_body(request))
            decision = policy.decide(profile, zone, path, request.method, module=module,
                                     export_request=export)
            if decision.allowed:
                return None
            self._log(mode, profile, decision.zone, decision.reason, request, _scope(request, module))
            if mode != 'enforce':
                return None
            return JsonResponse({'detail': policy.REASON_MESSAGES[decision.reason],
                                 'zone': decision.zone, 'reason': decision.reason}, status=403)
        except Exception:
            log.warning('zone policy check failed', exc_info=True)
            if mode == 'enforce':
                return JsonResponse({'detail': ERROR_MESSAGE, 'zone': None, 'reason': 'error'},
                                    status=403)
            return None

    @staticmethod
    def _context_failed(request):
        try:
            if cache.add('access:zone-noctx', 1, DENY_DEDUPE_SECONDS):
                log.error('zone policy: no access context on an internal network, allowed (%s %s)',
                          request.method, request.path_info)
        except Exception:
            log.error('zone policy: no access context on an internal network, allowed')

    @staticmethod
    def _log(mode, profile, zone, reason, request, scope):
        try:
            user = getattr(profile.user, 'username', '?')
            enforce = mode == 'enforce'
            ttl = DENY_DEDUPE_SECONDS if enforce else LOG_DEDUPE_SECONDS
            if not cache.add(f'access:zonelog:{mode}:{user}:{zone}:{reason}:{scope}', 1, ttl):
                return
            log.warning('%s user=%s role=%s zone=%s reason=%s %s %s',
                        'zone DENY' if enforce else 'zone would-deny', user, profile.role, zone,
                        reason, request.method, request.path_info)
        except Exception:
            log.warning('zone policy log failed', exc_info=True)
