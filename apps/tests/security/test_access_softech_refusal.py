"""N4 / Task 4 - a SOFTECH refusal is never "branch offline"; POS stays single-post.

A refused connection (SoftechAccessDenied) or a refused write (SoftechReadOnlyError /
SoftechZoneWriteDenied) must never be classified as a connectivity problem: the POS writer
QUEUES unreachable orders and the scheduler later flushes them WITH SYSTEM RIGHTS, so a
queued refusal would post an order the gate had refused. Refused orders are push_failed;
a later push from an allowed place posts them exactly once (vf2 idempotency).

No real Sybase: get_branch_connection is replaced by the REAL _connect_with_retry over a
Mock driver, so the gate decision is taken where production takes it.
"""
from unittest import mock

from django.core.cache import cache
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView

from apps.access import softech_gate as gate
from apps.access.softech_gate import GateDecision
from apps.invoices import writer as invoices_writer
from apps.pos_orders import writer as pos_writer
from apps.pos_orders.models import SoftechSalesOrder
from apps.sync import tasks as sync_tasks
from apps.tests.factories import make_branch
from config import sybase
from config.sybase import SoftechAccessDenied, SoftechReadOnlyError, SoftechZoneWriteDenied
from core.errors import public_error

CHECK = 'apps.access.softech_gate.check'
MODE = 'apps.access.softech_gate.mode'
REFUSED = GateDecision(gate.NONE, 'zone_no_read', 'web:external:salesperson', 'Z3')
ALLOWED = GateDecision(gate.FULL, None, 'web:internal:cashier', 'Z1')

CLASSIFIERS = (pos_writer._is_unreachable, invoices_writer._is_unreachable,
               sync_tasks._is_connection_error)
MARKERS = (pos_writer._UNREACHABLE_HINTS + invoices_writer._UNREACHABLE_HINTS
           + sync_tasks._CONNECTION_ERROR_MARKERS)


class ClassifierTests(SimpleTestCase):

    def test_refusals_are_not_unreachable(self):
        refusals = [
            SoftechAccessDenied(),
            SoftechZoneWriteDenied(),
            # Messages that DO contain a connectivity marker must still not count: the
            # global read-only refusal echoes the refused SQL, which can name any column.
            SoftechAccessDenied('connection refused by the gate', reason='zone_no_read'),
            SoftechZoneWriteDenied('socket timeout - refused'),
            SoftechReadOnlyError('SOFTECH is in read-only mode; refused: UPDATE t SET timeout=1'),
        ]
        for exc in refusals:
            for classify in CLASSIFIERS:
                with self.subTest(exc=type(exc).__name__, msg=str(exc), fn=classify.__module__):
                    self.assertFalse(classify(exc))

    def test_refusal_copy_has_no_connectivity_marker(self):
        for text in (gate.DENY_MESSAGE, gate.WRITE_DENY_MESSAGE,
                     str(SoftechAccessDenied()), str(SoftechZoneWriteDenied())):
            for marker in MARKERS:
                self.assertNotIn(marker, text.lower())

    def test_real_connectivity_errors_still_queue(self):
        exc = Exception('JZ006: Caught IOException: java.net.ConnectException: Connection refused')
        for classify in CLASSIFIERS:
            self.assertTrue(classify(exc))


class _FakeSoftech:
    """The branch DB as the writer sees it: one cursor answering the vf2 lookup from the rows
    'inserted' so far. begin/commit/rollback/close are no-ops."""

    def __init__(self):
        self.rows = []          # [(vf2, docnumber)]

    def cursor(self):
        store = self

        class _Cur:
            def execute(self, sql, params):
                self.result = [(d,) for v, d in store.rows if v == params[2]]

            def fetchall(self):
                return self.result

            def close(self):
                pass

        return _Cur()

    def begin(self): pass
    def commit(self): pass
    def rollback(self): pass
    def close(self): pass


@override_settings(POS_WRITER_ENABLED=True, SOFTECH_READ_ONLY=False)
class PosRefusalTests(TestCase):

    def setUp(self):
        cache.clear()
        branch = make_branch()
        branch.db_host = '10.0.0.130'
        branch.save()
        self.order = SoftechSalesOrder.objects.create(
            branch=branch, softech_branchcode='130', store_code='130', softech_pic='130HD9668',
            status=SoftechSalesOrder.STATUS_READY)
        self.softech = _FakeSoftech()
        self.driver = mock.Mock(name='driver')
        self.driver.connect.return_value = self.softech
        test = self

        def real_gate_connect(*args, **kwargs):     # what get_branch_connection does, minus JVM
            return sybase._connect_with_retry(test.driver, 'jdbc:x', mock.Mock(),
                                              label='branch 10.0.0.130')

        def fake_execute_write(conn, order, seller):  # serial allocation + the INSERTs
            docnumber = 9001 + len(test.softech.rows)
            test.softech.rows.append((pos_writer.softech_token(order), docnumber))
            return {'ok': True, 'docnumber': docnumber}

        self.execute_write = mock.Mock(side_effect=fake_execute_write)
        for p in (mock.patch.object(pos_writer, 'build_payload', return_value={}),
                  mock.patch('apps.pos_orders.stock.check_item_restrictions', return_value=[]),
                  mock.patch('apps.pos_orders.stock.enabled', return_value=False),
                  mock.patch('config.sybase.get_branch_connection', side_effect=real_gate_connect),
                  mock.patch('config.sybase._load', return_value=mock.Mock()),
                  mock.patch('config.sybase.time.sleep'),
                  mock.patch(MODE, return_value='enforce'),
                  mock.patch.object(pos_writer, '_execute_write', self.execute_write)):
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        cache.clear()

    def push(self, decision):
        with mock.patch(CHECK, return_value=decision):
            return pos_writer.push_order(self.order, dry_run=False)

    def test_pos_push_refused_is_push_failed_not_queued(self):
        with self.assertRaises(SoftechAccessDenied):
            self.push(REFUSED)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, SoftechSalesOrder.STATUS_PUSH_FAILED)
        self.assertNotEqual(self.order.status, SoftechSalesOrder.STATUS_QUEUED)
        self.assertIn('SOFTECH غير متاح', self.order.erp_error)
        self.assertNotIn('unreachable', self.order.erp_error)
        self.driver.connect.assert_not_called()
        self.execute_write.assert_not_called()
        self.assertEqual(self.softech.rows, [])

    def test_pos_push_after_refusal_posts_once(self):
        with self.assertRaises(SoftechAccessDenied):
            self.push(REFUSED)
        self.order.refresh_from_db()

        res = self.push(ALLOWED)                      # cashier on an approved PC
        self.assertTrue(res['ok'])
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, SoftechSalesOrder.STATUS_PUSHED)
        self.assertEqual(self.execute_write.call_count, 1)
        self.assertEqual(len(self.softech.rows), 1)

        # PG lost the docnumber after the commit (crash): the vf2 tag is found, no re-insert.
        SoftechSalesOrder.objects.filter(pk=self.order.pk).update(
            status=SoftechSalesOrder.STATUS_PUSH_FAILED, softech_docnumber=None)
        self.order.refresh_from_db()
        res = self.push(ALLOWED)
        self.assertEqual(res['mode'], 'idempotent_recovered')
        self.assertFalse(res['wrote_to_softech'])
        self.assertEqual(self.execute_write.call_count, 1)
        self.assertEqual(len(self.softech.rows), 1)

        # And the plain repeat on a pushed order never reaches SOFTECH at all.
        self.order.refresh_from_db()
        res = self.push(ALLOWED)
        self.assertTrue(res['already_pushed'])
        self.assertEqual(len(self.softech.rows), 1)


class PublicErrorTests(SimpleTestCase):

    def test_public_error_shows_refusal_text(self):
        request = RequestFactory().post('/api/pos/orders/1/push/')
        request.user = mock.Mock(staff_profile=mock.Mock(role='cashier'))
        for exc, text in ((SoftechAccessDenied(), gate.DENY_MESSAGE),
                          (SoftechZoneWriteDenied(), gate.WRITE_DENY_MESSAGE)):
            with self.assertLogs('elrezeiky.errors'):
                out = public_error(request, exc)
            self.assertEqual(out, text)
            self.assertNotIn('خطأ داخلي', out)

    def test_other_errors_stay_hidden(self):
        request = RequestFactory().post('/x/')
        request.user = mock.Mock(staff_profile=mock.Mock(role='cashier'))
        with self.assertLogs('elrezeiky.errors'):
            out = public_error(request, RuntimeError('host 10.0.0.5 table stktransm5'))
        self.assertIn('خطأ داخلي', out)
        self.assertNotIn('stktransm5', out)


class _Raises(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    exc = None

    def get(self, request):
        raise self.exc


class ExceptionHandlerTests(SimpleTestCase):

    def call(self, exc):
        view = _Raises.as_view(exc=exc)
        return view(APIRequestFactory().get('/x/'))

    def test_uncaught_refusal_is_403(self):
        for exc, text in ((SoftechAccessDenied(reason='zone_no_read'), gate.DENY_MESSAGE),
                          (SoftechZoneWriteDenied(), gate.WRITE_DENY_MESSAGE)):
            res = self.call(exc)
            self.assertEqual(res.status_code, 403)
            self.assertEqual(res.data, {'detail': text, 'code': 'softech_zone'})

    def test_other_api_errors_unchanged(self):
        res = self.call(ValidationError({'qty': ['bad']}))
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data, {'qty': ['bad']})


class RepriceTransientTests(SimpleTestCase):
    """The insurance re-price retries once on a flaky link — never on a refusal (N4)."""

    def test_refusal_is_not_transient_even_with_marker_text(self):
        from apps.insurance.reprice_service import _is_transient
        from config.sybase import SoftechAccessDenied, SoftechZoneWriteDenied
        self.assertFalse(_is_transient(SoftechAccessDenied('socket timeout')))
        self.assertFalse(_is_transient(SoftechZoneWriteDenied('JZ0C0')))
        self.assertTrue(_is_transient(RuntimeError('JZ0C0 Connection is already closed')))
