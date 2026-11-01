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

from core.middleware import module_access

from . import policy

log = logging.getLogger('elrezeiky.access')

LOG_DEDUPE_SECONDS = 600
MAX_BODY_BYTES = 1024 * 1024
ERROR_MESSAGE = 'تعذر التحقق من صلاحية الدخول — حاول مرة أخرى'


def _mode():
    mode = str(getattr(settings, 'NETWORK_POLICY_ENFORCEMENT', 'log') or 'log').lower()
    return mode if mode in ('off', 'log', 'enforce') else 'log'


def _json_body(request):
    """The parsed JSON body for body-selected export routes only; None when not JSON / too big."""
    if request.path_info not in policy.BODY_EXPORTS:
        return None
    ctype = (request.META.get('CONTENT_TYPE') or '').lower()
    if not ctype.startswith('application/json'):
        return None
    try:
        if int(request.META.get('CONTENT_LENGTH') or 0) > MAX_BODY_BYTES:
            return None
        return json.loads(request.body or b'null')
    except Exception:
        return None


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
            profile = module_access._staff_profile(request)
            if profile is None:
                return None
            access = getattr(request, 'access', None)
            zone = getattr(access, 'zone', None)
            path = request.path_info
            need = module_access.required(path, request.method)
            module = need[0] if need else None
            export = policy.is_export(path, request.method, query=request.GET, body=_json_body(request))
            decision = policy.decide(profile, zone, path, request.method, module=module,
                                     export_request=export)
            if decision.allowed:
                return None
            self._log(mode, profile, decision.zone, decision.reason, request)
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
    def _log(mode, profile, zone, reason, request):
        try:
            user = getattr(profile.user, 'username', '?')
            path = request.path_info
            if mode == 'enforce':
                label = 'zone DENY'
            else:
                label = 'zone would-deny'
                if not cache.add(f'access:zonelog:{user}:{zone}:{reason}:{path}', 1,
                                 LOG_DEDUPE_SECONDS):
                    return
            log.warning('%s user=%s role=%s zone=%s reason=%s %s %s',
                        label, user, profile.role, zone, reason, request.method, path)
        except Exception:
            log.warning('zone policy log failed', exc_info=True)
