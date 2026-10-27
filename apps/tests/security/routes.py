"""
apps/tests/security/routes.py

Shared catalogue of every /api/ route the project serves, plus the Tripwire
that keeps sweeps from touching anything outside the test database.

Routes are rendered from their patterns with placeholder arguments (ids → 1),
so detail routes mostly answer 404 — that still exercises auth and dispatch.
"""
import re
import threading
from unittest import mock

from django.urls import URLPattern, URLResolver, get_resolver
from rest_framework.permissions import AllowAny


# Reviewed public endpoints (anonymous access is intentional). Keep in sync with
# docs/architecture/04_API_REGISTRY.md when adding one.
KNOWN_PUBLIC_VIEWS = {
    # staff auth + 2FA login steps
    'apps.users.views.login_view', 'apps.users.views.refresh_view',
    'apps.users.views.logout_view',   # only revokes the token the caller presents
    # customer self-service portal (own magic-link auth inside the views)
    'apps.portal.views',
    # inbound webhooks (signature / secret-token checked inside the views)
    'apps.whatsapp.views.WebhookView', 'apps.social.views.MetaGraphWebhookView',
    'apps.social.views.TelegramWebhookView', 'apps.social.views.TikTokWebhookView',
    # public appearance theme (PUT checks admin inside), public demand capture,
    # tokenised delivery tracking, signed PBX recording links
    'apps.config.views.theme',
    'apps.demand.views.public_item_lookup', 'apps.demand.views.public_branches',
    'apps.demand.views.public_demand_interest',
    'apps.delivery.views.delivery_public_track',
    'apps.pbx.views.RecordingView',
    'apps.users.mfa',
}

_CONVERTERS = {
    'int': '1', 'str': 'x', 'slug': 'x', 'path': 'x',
    'uuid': '00000000-0000-0000-0000-000000000000',
}


def _render(pattern_str, id_value='1'):
    """Turn a route/regex pattern into a concrete path, or None if not renderable."""
    s = pattern_str
    if s.startswith('^'):
        if 'format' in s:
            return None                         # DRF format-suffix duplicates
        s = s.lstrip('^').rstrip('$')
        s = re.sub(r'\(\?P<[^>]+>[^)]*\)', id_value, s)
        s = s.replace('\\.', '.').replace('\\/', '/')
        if re.search(r'[()\[\]*+?|\\]', s):
            return None
        return s
    conv = dict(_CONVERTERS, int=id_value)
    s = re.sub(r'<(?:(\w+):)?\w+>', lambda m: conv.get(m.group(1) or 'str', 'x'), s)
    return s


def _walk(patterns, prefix='', id_value='1'):
    for p in patterns:
        part = _render(str(p.pattern), id_value)
        if part is None:
            continue
        if isinstance(p, URLResolver):
            yield from _walk(p.url_patterns, prefix + part, id_value)
        elif isinstance(p, URLPattern):
            yield '/' + prefix + part, p.callback


def view_id(callback):
    cls = getattr(callback, 'cls', None) or getattr(callback, 'view_class', None)
    if cls is not None:
        return f'{cls.__module__}.{cls.__name__}', cls
    return f'{callback.__module__}.{callback.__name__}', cls


def is_public(cls):
    perms = list(getattr(cls, 'permission_classes', None) or [])
    return cls is not None and (not perms or AllowAny in perms)


def api_routes(id_value='1'):
    """Every /api/ route rendered with `id_value` for numeric/regex path arguments."""
    seen = set()
    for path, cb in _walk(get_resolver().url_patterns, id_value=id_value):
        if path.startswith('/api/') and path not in seen:
            seen.add(path)
            yield path, cb


def known_public(view_id_):
    return any(view_id_ == k or view_id_.startswith(k + '.') for k in KNOWN_PUBLIC_VIEWS)


class Tripwire:
    """Nothing leaves the test process — every attempt is blocked AND recorded:

      softech_calls  SOFTECH connections — patched at the module attributes and at the
                     inner choke points of config/sybase.py (_connect_with_retry,
                     _ensure_jvm) that every connection passes, even when the caller
                     imported get_sybase_connection by name
      http_calls     requests.Session.request
      sockets        any Python socket connect (urllib, httpx/SDKs, AMI, SFTP, Redis, SMTP…).
                     PostgreSQL is unaffected: psycopg2 connects through libpq, not Python sockets
      subprocesses   subprocess.Popen
      threads        Thread.start becomes a no-op (join on such a thread returns at once);
                     ThreadPoolExecutor.submit returns a Future already failed with
                     ConnectionError, so as_completed() never hangs
    """

    _SOFTECH = (
        ('config.sybase.get_sybase_connection', 'get_sybase_connection'),
        ('config.sybase.get_branch_connection', 'get_branch_connection'),
        ('config.sybase.probe_connection', 'probe_connection'),
        ('config.sybase._connect_with_retry', '_connect_with_retry'),
        ('config.sybase._ensure_jvm', '_ensure_jvm'),
    )

    def __enter__(self):
        import socket
        import subprocess
        from concurrent.futures import Future, ThreadPoolExecutor
        self.softech_calls, self.http_calls, self.threads = [], [], []
        self.sockets, self.subprocesses = [], []
        self._patches = []
        tw = self

        def _sock_connect(sock_self, address, *a, **k):
            tw.sockets.append(repr(address))
            raise ConnectionError('offline in tests')

        def _create_connection(address, *a, **k):
            tw.sockets.append(repr(address))
            raise ConnectionError('offline in tests')

        def _popen_init(popen_self, args, *a, **k):
            tw.subprocesses.append(repr(args)[:200])
            raise OSError('subprocess blocked in tests')

        def _submit(pool_self, fn, *a, **k):
            tw.threads.append(f'{getattr(fn, "__module__", "?")}.'
                              f'{getattr(fn, "__qualname__", repr(fn))}')
            fut = Future()
            fut.set_exception(ConnectionError('offline in tests'))
            return fut

        _real_join = threading.Thread.join

        def _join(thread_self, timeout=None):
            if not thread_self._started.is_set():
                return None                   # start() was blocked — nothing to wait for
            return _real_join(thread_self, timeout)

        self._patches += [
            mock.patch.object(socket.socket, 'connect', _sock_connect),
            mock.patch.object(socket.socket, 'connect_ex', _sock_connect),
            mock.patch.object(socket, 'create_connection', _create_connection),
            mock.patch.object(subprocess.Popen, '__init__', _popen_init),
            mock.patch.object(ThreadPoolExecutor, 'submit', _submit),
            mock.patch.object(threading.Thread, 'join', _join),
        ]
        for target, _ in self._SOFTECH:
            self._patches.append(mock.patch(target, side_effect=self._softech(target)))
        self._patches.append(mock.patch('config.sybase.SoftechConnector.connect',
                                        autospec=True,
                                        side_effect=self._softech('config.sybase.SoftechConnector.connect')))
        self._patches.append(mock.patch('requests.sessions.Session.request',
                                        autospec=True, side_effect=self._http))

        def _start(thread_self):
            target = getattr(thread_self, '_target', None)
            name = getattr(target, '__qualname__', None) or repr(target)
            tw.threads.append(f'{getattr(target, "__module__", "?")}.{name}')
        self._patches.append(mock.patch.object(threading.Thread, 'start', _start))
        for p in self._patches:
            p.start()
        return self

    def _softech(self, name):
        def boom(*a, **k):
            self.softech_calls.append(name)
            raise ConnectionError('offline in tests')
        return boom

    def _http(self, *a, **k):
        self.http_calls.append(str(a[2]) if len(a) > 2 else '?')
        raise ConnectionError('offline in tests')

    def outside_count(self) -> int:
        """Attempts to leave the process other than SOFTECH (threads, HTTP, sockets, subprocesses)."""
        return len(self.threads) + len(self.http_calls) + len(self.sockets) + len(self.subprocesses)

    def __exit__(self, *exc):
        for p in reversed(self._patches):
            p.stop()


Offline = Tripwire   # name used by the original endpoint sweep
