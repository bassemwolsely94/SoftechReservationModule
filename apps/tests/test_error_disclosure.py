"""
apps/tests/test_error_disclosure.py

Unexpected exception text (SOFTECH hosts, SQL, driver messages) must not reach
non-admin users; admins keep the technical text; the full error is logged with
a reference code users can quote. See core/errors.py.
"""
import ast
import subprocess
from pathlib import Path
from unittest import mock

from django.test import RequestFactory, TestCase, override_settings

from core.errors import public_error

from .factories import make_branch, make_user

ECHO_KEYS = ('detail', 'error', 'note', 'message', 'reason')
LEAK = 'JZ006: Caught IOException: connect to 192.168.77.5:5000 SOFTECHDB9.dbo.stkbalexpiry'
# UAT W5 (2026-11-17): what the office server showed every role, DEBUG being on there
JDBC_LEAK = ('java.sql.SQLException: JZ003: Incorrect URL format. URL: '
             'jdbc:sybase:Tds:softech-uat-host.example:5000/SOFTECHDB9')


class PublicErrorUnitTests(TestCase):

    def _req(self, role):
        user, _, _ = make_user(f'err_{role}', role=role, branch=make_branch())
        req = RequestFactory().get('/api/x/')
        req.user = user
        return req

    @override_settings(DEBUG=False)
    def test_non_admin_gets_reference_only_and_error_is_logged(self):
        with self.assertLogs('elrezeiky.errors', level='ERROR') as logs:
            msg = public_error(self._req('pharmacist'), RuntimeError(LEAK))
        self.assertNotIn('192.168', msg)
        self.assertNotIn('SOFTECHDB9', msg)
        ref = msg.split('مرجع: ')[1].rstrip(')')
        self.assertTrue(any(ref in line and '192.168.77.5' in line for line in logs.output))

    @override_settings(DEBUG=True)
    def test_debug_does_not_open_the_technical_text(self):
        # the office dev server runs DEBUG on the LAN (UAT W5): DEBUG must not show non-admins the text
        with self.assertLogs('elrezeiky.errors', level='ERROR'):
            msg = public_error(self._req('purchasing'), RuntimeError(JDBC_LEAK))
        self.assertNotIn('softech-uat-host', msg)
        self.assertNotIn('java.sql', msg)
        self.assertIn('مرجع', msg)

    def test_no_request_gets_reference_only(self):
        with self.assertLogs('elrezeiky.errors', level='ERROR'):
            msg = public_error(None, RuntimeError(JDBC_LEAK))
        self.assertNotIn('softech-uat-host', msg)
        self.assertIn('مرجع', msg)

    @override_settings(DEBUG=False)
    def test_admin_keeps_technical_text(self):
        with self.assertLogs('elrezeiky.errors', level='ERROR'):
            msg = public_error(self._req('admin'), RuntimeError(LEAK))
        self.assertIn('JZ006', msg)
        self.assertIn('مرجع', msg)


@override_settings(DEBUG=False)
class EndpointDisclosureTests(TestCase):
    URL = '/api/pos-orders/batches/'

    def setUp(self):
        self.branch = make_branch()

    def _get(self, role):
        _, _, client = make_user(f'pos_{role}', role=role, branch=self.branch)
        with mock.patch('apps.pos_orders.batch_availability.item_availability',
                        side_effect=RuntimeError(LEAK)), \
             self.assertLogs('elrezeiky.errors', level='ERROR'):
            return client.get(self.URL, {'branch': self.branch.pk, 'item': '123'})

    def test_pharmacist_sees_no_internals(self):
        r = self._get('pharmacist')
        self.assertEqual(r.status_code, 502)
        self.assertNotIn('192.168', r.json()['detail'])
        self.assertIn('مرجع', r.json()['detail'])

    def test_admin_sees_technical_detail(self):
        r = self._get('admin')
        self.assertIn('JZ006', r.json()['detail'])


@override_settings(DEBUG=True)            # as the office server runs (UAT W5)
class SoftechReadErrorTests(TestCase):
    """UAT W5: the ISR push review, the stock count snapshot and the POS lookups showed the JDBC
    text with the SOFTECH host and connection URL when SOFTECH could not be read."""

    def setUp(self):
        self.branch = make_branch()

    def _no_leak(self, text):
        self.assertNotIn('softech-uat-host', text)
        self.assertNotIn('java.sql', text)
        self.assertIn('مرجع', text)

    def test_isr_push_review(self):
        from apps.purchasing.models import IsrPush
        p = IsrPush.objects.create(branchcode=self.branch.softech_branch_id)
        _, _, client = make_user('err_isr_purch', role='purchasing', branch=self.branch)
        with mock.patch('config.sybase.get_branch_connection', side_effect=RuntimeError(JDBC_LEAK)),              self.assertLogs('elrezeiky.errors', level='ERROR'):
            r = client.get(f'/api/purchasing/isr/pushes/{p.pk}/push-review/')
        self.assertEqual(r.status_code, 502, r.content)
        self._no_leak(r.json()['detail'])

    def test_stock_count_snapshot(self):
        from apps.stockcount.models import StockCountSession
        _, prof, client = make_user('err_sc_pharm', role='pharmacist', branch=self.branch)
        s = StockCountSession.objects.create(name='UAT', branch_code=self.branch.softech_branch_id,
                                             status='draft', created_by=prof)
        with mock.patch('apps.stockcount.engine.generate_snapshot', side_effect=RuntimeError(JDBC_LEAK)),              self.assertLogs('elrezeiky.errors', level='ERROR'):
            r = client.post(f'/api/stockcount/sessions/{s.pk}/generate-snapshot/', {}, format='json')
        self.assertEqual(r.status_code, 503, r.content)
        self._no_leak(r.json()['detail'])

    def test_pos_branch_stores_note(self):
        _, _, client = make_user('err_pos_pharm', role='pharmacist', branch=self.branch)
        with mock.patch('apps.pos_orders.customer_directory.branch_stores', side_effect=RuntimeError(JDBC_LEAK)),              self.assertLogs('elrezeiky.errors', level='ERROR'):
            r = client.get('/api/pos-orders/branch-stores/', {'branch': self.branch.pk})
        self.assertEqual(r.status_code, 200, r.content)
        self._no_leak(r.json()['note'])

    def test_personal_dashboard_transactions(self):
        from apps.personal import queries
        with mock.patch.object(queries, '_rows', side_effect=RuntimeError(JDBC_LEAK)),              mock.patch.object(queries, '_one', side_effect=RuntimeError(JDBC_LEAK)),              self.assertLogs('elrezeiky.errors', level='ERROR'):
            out = queries.customer_transactions('123')
        self._no_leak(out['error'])


class NoBroadExceptionEchoTests(TestCase):
    """Static guard: no view may echo a caught `Exception` into a response again."""
    # note / message / reason too (UAT W5: the POS lookups answered {'note': f'تعذّر القراءة: {e}'})

    def test_broad_exception_text_never_returned_raw(self):
        root = Path(__file__).resolve().parents[2]
        offenders = []
        for path in (root / 'apps').rglob('*.py'):
            rel = path.relative_to(root).as_posix()
            if '/tests/' in rel or '/migrations/' in rel:
                continue
            try:
                tree = ast.parse(path.read_text(encoding='utf-8-sig'))
            except SyntaxError:
                continue
            for handler in ast.walk(tree):
                if not (isinstance(handler, ast.ExceptHandler) and handler.name
                        and isinstance(handler.type, ast.Name) and handler.type.id == 'Exception'):
                    continue
                name = handler.name
                for node in ast.walk(ast.Module(body=handler.body, type_ignores=[])):
                    if not (isinstance(node, ast.Call) and getattr(node.func, 'id', '') in
                            ('Response', 'DRFResponse', 'JsonResponse')):
                        continue
                    if not node.args or not isinstance(node.args[0], ast.Dict):
                        continue
                    for key, val in zip(node.args[0].keys, node.args[0].values):
                        if not (isinstance(key, ast.Constant) and key.value in ECHO_KEYS):
                            continue
                        raw = any(isinstance(n, ast.Name) and n.id == name for n in ast.walk(val)) and \
                            not any(isinstance(n, ast.Call) and getattr(n.func, 'id', '') == 'public_error'
                                    for n in ast.walk(val))
                        if raw:
                            offenders.append(f'{rel}:{node.lineno}')
        self.assertEqual(offenders, [], 'Use core.errors.public_error(request, exc):\n' + '\n'.join(offenders))
