"""
apps/sync/middleware.py

SlowRequestMiddleware (P-56 §5 "measure before optimising"): every request that takes
longer than settings.SLOW_REQUEST_MS (default 1000) is saved as a SlowRequest with its
URL ROUTE pattern (no ids, no query string), status, duration and the user's role.
Logging never breaks or delays the response beyond one insert, and only slow
requests are written.
"""
import logging
import time

from django.conf import settings

logger = logging.getLogger('elrezeiky.sync')


class SlowRequestMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        started = time.monotonic()
        response = self.get_response(request)
        ms = int((time.monotonic() - started) * 1000)
        if ms >= int(getattr(settings, 'SLOW_REQUEST_MS', 1000)):
            try:
                self._record(request, response, ms)
            except Exception as exc:
                logger.debug('slow-request log skipped: %s', exc)
        return response

    @staticmethod
    def _record(request, response, ms):
        match = getattr(request, 'resolver_match', None)
        if match is None:
            return   # 404s and static files: no route to name
        route = (match.route or '')[:255]
        role = ''
        user = getattr(request, 'user', None)
        if user is not None and getattr(user, 'is_authenticated', False):
            role = getattr(getattr(user, 'staff_profile', None), 'role', '') or ''
        from apps.sync.models import SlowRequest
        SlowRequest.objects.create(path=route, method=request.method[:8],
                                   status_code=response.status_code, duration_ms=ms, role=role)
