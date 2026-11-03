"""
Anonymous allow-list gate for /api/ (N6): a request with no signed-in user may only reach the
paths in public_paths.PUBLIC_PREFIXES. Mode is PUBLIC_API_ENFORCEMENT (off / log / enforce), read
per request; an unknown value runs as log. Not zone-dependent. Never raises: an internal error
passes the request in log / off mode and refuses it in enforce.
"""
import logging

from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse

from core.client_ip import client_ip

from .public_paths import is_public

log = logging.getLogger('elrezeiky.access')

LOG_DEDUPE_SECONDS = 600
DENY_MESSAGE = 'يلزم تسجيل الدخول'


def mode():
    value = str(getattr(settings, 'PUBLIC_API_ENFORCEMENT', 'log') or 'log').lower()
    return value if value in ('off', 'log', 'enforce') else 'log'


def _ip(request):
    access = getattr(request, 'access', None)
    net = getattr(access, 'network', None)
    return getattr(net, 'ip', None) or client_ip(request) or '-'


def _deny():
    return JsonResponse({'detail': DENY_MESSAGE}, status=401)


class PublicApiMiddleware:

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        current = 'log'
        try:
            current = mode()
            if current != 'off' and request.path_info.startswith('/api/'):
                access = getattr(request, 'access', None)
                anonymous = access is None or getattr(access, 'user_id', None) is None
                if anonymous and not is_public(request.path_info, request.method):
                    if current == 'enforce':
                        return _deny()
                    self._log(request)
        except Exception:
            log.error('public gate failed', exc_info=True)
            if current == 'enforce':
                return _deny()
        return self.get_response(request)

    @staticmethod
    def _log(request):
        ip = _ip(request)
        try:
            if not cache.add(f'access:public-gate:{request.path_info}:{ip}', 1, LOG_DEDUPE_SECONDS):
                return
        except Exception:
            pass
        log.warning('public gate would-deny %s %s ip=%s', request.method, request.path_info, ip)
