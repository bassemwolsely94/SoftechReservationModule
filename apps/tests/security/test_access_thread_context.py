"""
N4 / Task 1 -- the request's access context and SOFTECH scope follow threads, pools and streamed
responses, so the gate at the SOFTECH connection sees who is asking from any of them.
"""
import ast
from pathlib import Path

from django.http import StreamingHttpResponse
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import path

from apps.access import context
from apps.sync import softech_load
from apps.tests.factories import make_user

ROOT = Path(__file__).resolve().parents[3]


class _Ctx:
    def __init__(self, role):
        self.role = role


class ThreadContextTests(SimpleTestCase):

    def test_start_thread_sees_access_context_and_scope(self):
        from core.threads import start_thread
        ctx = _Ctx('admin')
        token = context.access_context.set(ctx)
        seen = {}

        def fn():
            seen['ctx'] = context.current()
            seen['scope'] = softech_load.current_scope()
        try:
            with softech_load.scope('web:internal:admin'):
                t = start_thread(fn, name='ctx-test', daemon=True)
        finally:
            context.access_context.reset(token)
        t.join(5)
        self.assertIs(seen['ctx'], ctx)
        self.assertEqual(seen['scope'], 'web:internal:admin')
        self.assertEqual(t.name, 'ctx-test')
        self.assertTrue(t.daemon)

    def test_start_thread_passes_args_and_kwargs(self):
        from core.threads import start_thread
        out = []
        t = start_thread(lambda a, b=0: out.append((a, b)), args=(1,), kwargs={'b': 2})
        t.join(5)
        self.assertEqual(out, [(1, 2)])

    def test_pool_submit_sees_context_per_task(self):
        from core.threads import ContextThreadPoolExecutor
        seen = []

        def fn():
            seen.append(context.current())
        a, b = _Ctx('a'), _Ctx('b')
        with ContextThreadPoolExecutor(max_workers=2) as pool:
            tok = context.access_context.set(a)
            f1 = pool.submit(fn)
            context.access_context.reset(tok)
            tok = context.access_context.set(b)
            f2 = pool.submit(fn)
            context.access_context.reset(tok)
            f1.result()
            f2.result()
        self.assertEqual({id(x) for x in seen}, {id(a), id(b)})


def _stream_view(request):
    def gen():
        for i in range(2):
            acc = context.current()
            yield f'{i}:{acc.role if acc else None}:{softech_load.current_scope()};'.encode()
    return StreamingHttpResponse(gen())


urlpatterns = [path('stream/', _stream_view)]


@override_settings(ROOT_URLCONF='apps.tests.security.test_access_thread_context',
                   NETWORK_HEADER_TRUSTED=True, ACCESS_NETWORKS_TTL=0)
class StreamingContextTests(TestCase):

    def test_streaming_response_iterates_inside_request_context(self):
        from rest_framework_simplejwt.tokens import AccessToken
        user, _, _ = make_user('stream_ph', role='pharmacist')
        r = self.client.get('/stream/', HTTP_AUTHORIZATION=f'Bearer {AccessToken.for_user(user)}')
        body = b''.join(r.streaming_content).decode()
        self.assertIn('0:pharmacist:web:', body)
        self.assertIn('1:pharmacist:web:', body)


class NoBareThreadsGuard(SimpleTestCase):
    ALLOWED = {
        'apps/sync/tasks.py': 'APScheduler executor (jobs are scoped job:*)',
        'apps/sync/apps.py': 'atexit workaround, no SOFTECH',
    }
    NAMES = {'Thread', 'ThreadPoolExecutor'}

    def _offenders(self):
        out = []
        for base in ('apps', 'core'):
            for p in (ROOT / base).rglob('*.py'):
                rel = p.relative_to(ROOT).as_posix()
                if ('/tests/' in rel or '/migrations/' in rel or rel == 'core/threads.py'
                        or rel in self.ALLOWED):
                    continue
                tree = ast.parse(p.read_text(encoding='utf-8-sig'))
                aliases = set(self.NAMES)
                for n in ast.walk(tree):
                    if isinstance(n, ast.ImportFrom) and n.module in (
                            'threading', 'concurrent.futures'):
                        for a in n.names:
                            if a.name in self.NAMES:
                                aliases.add(a.asname or a.name)
                for n in ast.walk(tree):
                    if isinstance(n, ast.Call):
                        f = n.func
                        nm = f.id if isinstance(f, ast.Name) else (
                            f.attr if isinstance(f, ast.Attribute) else None)
                        if nm in aliases:
                            out.append(f'{rel}:{n.lineno}')
        return out

    def test_no_bare_threads_outside_core_threads(self):
        self.assertEqual(self._offenders(), [])

    def test_allowed_files_really_need_the_exception(self):
        for rel in self.ALLOWED:
            src = (ROOT / rel).read_text(encoding='utf-8')
            self.assertIn('ThreadPoolExecutor', src, rel)
