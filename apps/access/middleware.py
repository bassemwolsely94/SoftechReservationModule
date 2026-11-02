"""
Attaches request.access, and files the request's SOFTECH load under network + role (N1, log only).
"""
import logging

from django.conf import settings
from django.core.cache import cache

from apps.sync import softech_load

from . import context

log = logging.getLogger('elrezeiky.access')

# One line per (zone, ip, role) per window, not one per request: until split DNS is live every
# company request is "external" and would otherwise flood platform.log and journald.
LOG_DEDUPE_SECONDS = 600


class AccessContextMiddleware:

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            ctx = context.for_request(request)
        except Exception:
            log.warning('access context failed; treating the request as external', exc_info=True)
            ctx = context.fallback()
        request.access = ctx
        token = context.access_context.set(ctx)
        try:
            self._log_external(request, ctx)
            with softech_load.scope(f'web:{ctx.network.zone}:{ctx.role or "anon"}'):
                return self.get_response(request)
        finally:
            context.access_context.reset(token)

    @staticmethod
    def _log_external(request, ctx):
        try:
            if (getattr(settings, 'NETWORK_POLICY_ENFORCEMENT', 'log') == 'log'
                    and ctx.network.zone != 'internal' and request.path.startswith('/api/')):
                role = ctx.role or 'anon'
                key = f'access:extlog:{ctx.network.zone}:{ctx.network.ip}:{role}'
                if cache.add(key, 1, LOG_DEDUPE_SECONDS):
                    log.info('external request (first in %ss) user=%s role=%s ip=%s %s %s',
                             LOG_DEDUPE_SECONDS, ctx.user_id, role, ctx.network.ip,
                             request.method, request.path)
        except Exception:
            log.warning('access log line failed', exc_info=True)
