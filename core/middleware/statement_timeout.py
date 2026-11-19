"""
Web-only statement timeout (performance Stage 2, design §6 / §10).

WEB_STATEMENT_TIMEOUT_ENABLED (default off) + WEB_STATEMENT_TIMEOUT_MS (30000). When on, every
PostgreSQL connection used by a WEB REQUEST thread runs `SET statement_timeout`, so one runaway
query cannot hold a web process for minutes. Covered: the `default` and `audit_log` connections
of the request thread (opened before or during the request).

Never covered: the scheduler and management commands (no request), and background threads the
web process starts (PIC export jobs, OCR): a new thread does not inherit the request thread's
marker. That is why this is not a process-wide `OPTIONS -c statement_timeout`.

The marker is thread-local: Django runs a request's sync middleware and view on one thread
(under Daphne, a new thread per request).
"""
import threading
from contextlib import contextmanager

from django.conf import settings
from django.db import connections
from django.db.backends.signals import connection_created
from django.dispatch import receiver

ALIASES = ('default', 'audit_log')
_state = threading.local()


def timeout_ms():
    """The configured limit in ms, or 0 when the flag is off."""
    if not getattr(settings, 'WEB_STATEMENT_TIMEOUT_ENABLED', False):
        return 0
    return max(0, int(getattr(settings, 'WEB_STATEMENT_TIMEOUT_MS', 30000) or 0))


def _apply(conn, ms):
    with conn.cursor() as cur:
        cur.execute('SET statement_timeout = %s', [ms])


@contextmanager
def web_request_scope(ms):
    previous = getattr(_state, 'ms', 0)
    _state.ms = ms
    try:
        yield
    finally:
        _state.ms = previous


@receiver(connection_created, dispatch_uid='elrezeiky_web_statement_timeout')
def on_connection_created(sender, connection, **kwargs):
    ms = getattr(_state, 'ms', 0)
    if ms and getattr(connection, 'alias', None) in ALIASES:
        _apply(connection, ms)


def _apply_to_open(ms):
    for alias in ALIASES:
        if alias not in connections:
            continue
        conn = connections[alias]
        if conn.connection is not None:
            _apply(conn, ms)


class WebStatementTimeoutMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        ms = timeout_ms()
        if not ms:
            return self.get_response(request)
        with web_request_scope(ms):
            _apply_to_open(ms)       # a connection this thread already holds (persistent)
            return self.get_response(request)
