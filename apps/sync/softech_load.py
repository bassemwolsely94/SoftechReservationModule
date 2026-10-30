"""
SOFTECH load telemetry (doc 30, step 1.0) — how often, how long and how much we
ask of SOFTECH, per scheduled job / command / screen and per calling function.

Hooks live in config/sybase.py (every login and every query through
ConnectionWrapper/CursorWrapper), so no call site has to change. Counts are kept
in an in-process buffer and saved as hourly SoftechLoadStat rows at most once per
FLUSH_SECONDS — never a database write per query.

Not counted: statements a writer sends on the raw java.sql connection (`conn._conn`)
— their login still is.

Off with SOFTECH_LOAD_TELEMETRY=False.
"""
import atexit
import contextlib
import contextvars
import logging
import os
import sys
import threading
import time
from datetime import timedelta

from django.conf import settings

logger = logging.getLogger('elrezeiky.sync')

FLUSH_SECONDS = 60
RETENTION_DAYS = 30

_scope_var = contextvars.ContextVar('softech_scope', default=None)
_lock = threading.Lock()
_buffer = {}             # (hour_iso, node, scope, caller) -> [connects, conn_fail, conn_ms, queries, q_err, q_ms, max_q_ms, rows]
_last_flush = time.monotonic()
_last_purge = 0.0

_SKIP_FILES = ('config/sybase.py', 'apps/sync/softech_load.py')


def enabled() -> bool:
    return bool(getattr(settings, 'SOFTECH_LOAD_TELEMETRY', True))


# ── Scope: which job / command / request the work belongs to ──────────────────

def _default_scope() -> str:
    argv = sys.argv or ['']
    prog = os.path.basename(argv[0] or '')
    if any(s in prog for s in ('daphne', 'uvicorn', 'gunicorn')):
        return 'web'
    if len(argv) > 1 and prog.startswith('manage'):
        return 'web' if argv[1] == 'runserver' else f'cmd:{argv[1]}'
    return 'web'


_DEFAULT_SCOPE = _default_scope()


def current_scope() -> str:
    return _scope_var.get() or _DEFAULT_SCOPE


@contextlib.contextmanager
def scope(name: str):
    token = _scope_var.set(name)
    try:
        yield
    finally:
        _scope_var.reset(token)


def scoped(func, name: str):
    """Wrap a scheduled job so everything it asks of SOFTECH is filed under `name`."""
    def _run(*args, **kwargs):
        with scope(name):
            return func(*args, **kwargs)
    _run.__name__ = getattr(func, '__name__', 'job')
    _run.__wrapped__ = func
    return _run


def _caller() -> str:
    f = sys._getframe(2)
    fallback = None
    while f is not None:
        fn = f.f_code.co_filename.replace('\\', '/')
        if not fn.endswith(_SKIP_FILES):
            i = fn.rfind('/apps/')
            if i >= 0:
                return f'{fn[i + 1:]}:{f.f_code.co_name}'[:200]
            if fallback is None and '/config/' not in fn:
                fallback = f'{os.path.basename(fn)}:{f.f_code.co_name}'
        f = f.f_back
    return (fallback or 'unknown')[:200]


# ── Recording ─────────────────────────────────────────────────────────────────

def _hour_key() -> str:
    return time.strftime('%Y-%m-%dT%H:00:00', time.gmtime())


def _add(node, idx_values, max_ms=None):
    key = (_hour_key(), (node or 'unknown')[:64], current_scope()[:80], _caller())
    with _lock:
        b = _buffer.get(key)
        if b is None:
            b = _buffer[key] = [0, 0, 0, 0, 0, 0, 0, 0]
        for i, v in idx_values:
            b[i] += v
        if max_ms is not None and max_ms > b[6]:
            b[6] = max_ms
    _maybe_flush()


def record_connect(node: str, ms: float, ok: bool):
    if not enabled():
        return
    try:
        _add(node, [(0, 1), (1, 0 if ok else 1), (2, int(ms))])
    except Exception:   # telemetry must never break a SOFTECH call
        pass


def record_query(node: str, ms: float, ok: bool):
    if not enabled():
        return
    try:
        _add(node, [(3, 1), (4, 0 if ok else 1), (5, int(ms))], max_ms=int(ms))
    except Exception:
        pass


def record_fetch(node: str, rows: int, ms: float):
    """Rows pulled and the time spent pulling them (added to the query time)."""
    if not enabled() or (not rows and ms < 1):
        return
    try:
        _add(node, [(7, int(rows)), (5, int(ms))])
    except Exception:
        pass


# ── Saving ────────────────────────────────────────────────────────────────────

_UPSERT = """
INSERT INTO sync_softechloadstat
    (hour, node, scope, caller, connects, connect_failures, connect_ms,
     queries, query_errors, query_ms, max_query_ms, rows)
VALUES {values}
ON CONFLICT (hour, node, scope, caller) DO UPDATE SET
    connects         = sync_softechloadstat.connects         + EXCLUDED.connects,
    connect_failures = sync_softechloadstat.connect_failures + EXCLUDED.connect_failures,
    connect_ms       = sync_softechloadstat.connect_ms       + EXCLUDED.connect_ms,
    queries          = sync_softechloadstat.queries          + EXCLUDED.queries,
    query_errors     = sync_softechloadstat.query_errors     + EXCLUDED.query_errors,
    query_ms         = sync_softechloadstat.query_ms         + EXCLUDED.query_ms,
    max_query_ms     = GREATEST(sync_softechloadstat.max_query_ms, EXCLUDED.max_query_ms),
    rows             = sync_softechloadstat.rows             + EXCLUDED.rows
"""


def flush() -> int:
    """Save the buffer (incrementing existing hourly rows). Returns rows written."""
    global _last_flush, _buffer
    with _lock:
        data, _buffer = _buffer, {}
        _last_flush = time.monotonic()
    if not data:
        return 0
    from django.db import connection
    params, values = [], []
    for (hour, node, scope_name, caller), b in data.items():
        values.append('(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)')
        params.extend([hour + '+00:00', node, scope_name, caller, *b])
    try:
        with connection.cursor() as cur:
            cur.execute(_UPSERT.format(values=','.join(values)), params)
        _maybe_purge()
        return len(data)
    except Exception as exc:
        logger.warning('[softech_load] flush failed (%d buckets dropped): %s', len(data), exc)
        return 0


def _maybe_flush():
    if time.monotonic() - _last_flush < FLUSH_SECONDS:
        return
    try:
        from django.db import connection
        if connection.in_atomic_block:   # never write inside someone else's transaction
            return
    except Exception:
        return
    flush()


def _maybe_purge():
    global _last_purge
    if time.monotonic() - _last_purge < 86400 and _last_purge:
        return
    _last_purge = time.monotonic()
    from django.utils import timezone
    from apps.sync.models import SoftechLoadStat
    SoftechLoadStat.objects.filter(hour__lt=timezone.now() - timedelta(days=RETENTION_DAYS)).delete()


def _flush_at_exit():
    try:
        flush()
    except Exception:
        pass


atexit.register(_flush_at_exit)
