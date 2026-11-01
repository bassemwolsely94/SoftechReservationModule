"""
Attaches request.access, and files the request's SOFTECH load under network + role (N1, log only).
"""
import contextvars
import logging

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
            ctx = context.fallback(request)
            log.error('access context failed; network %s from the label alone', ctx.network.zone,
                      exc_info=True)
        request.access = ctx
        token = context.access_context.set(ctx)
        try:
            self._log_external(request, ctx)
            with softech_load.scope(f'web:{ctx.network.zone}:{ctx.role or "anon"}'):
                response = self.get_response(request)
                if getattr(response, 'streaming', False) and not getattr(response, 'is_async', False):
                    # The body is produced after this frame returns and the reset below runs;
                    # pull every chunk inside the request's own context so the generator
                    # (a SOFTECH read, say) is still gated as this user.
                    response.streaming_content = self._in_context(
                        contextvars.copy_context(), response.streaming_content)
                return response
        finally:
            context.access_context.reset(token)

    @staticmethod
    def _in_context(ctx, chunks):
        it = iter(chunks)
        while True:
            try:
                chunk = ctx.run(next, it)
            except StopIteration:
                return
            yield chunk

    @staticmethod
    def _log_external(request, ctx):
        try:
            from .policy_middleware import _mode
            if (_mode() == 'log'
                    and ctx.network.zone != 'internal' and request.path.startswith('/api/')):
                role = ctx.role or 'anon'
                key = f'access:extlog:{ctx.network.zone}:{ctx.network.ip}:{role}'
                if cache.add(key, 1, LOG_DEDUPE_SECONDS):
                    log.info('external request (first in %ss) user=%s role=%s ip=%s %s %s',
                             LOG_DEDUPE_SECONDS, ctx.user_id, role, ctx.network.ip,
                             request.method, request.path)
        except Exception:
            log.warning('access log line failed', exc_info=True)
