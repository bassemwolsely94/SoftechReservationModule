"""N4 final fix wave - the whole-branch review's I1-I4 and must-fix minors.

I1  require_write(): a refused flush / push-batch answers 403 and claims nothing; a refused push of an
    order that was already queued puts it back to queued (the system job finishes it).
I2  gate audit rows go through the `audit_log` alias: an outer rollback keeps them; the dedupe key is
    set only after the row was saved.
I3  the shortage flag / unflag / dismiss / retrieve views ask the gate before changing PG.
I4  access.E005 / access.W003 for SOFTECH_GATE_ENFORCEMENT.
M1 FileResponse keeps file_to_stream; M2 no dead threading imports; M3 streaming closers run in the
request context; M4 set_rollback() on a refusal; M5 reprice never retries a refusal; M8 the unsafe
line names its switch; M9 whoami hides the gate mode from anonymous callers; M10 observation rows
carry the statement's first keyword and the matched write word.
"""
import ast
import contextvars
import io
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.core.cache import cache
from django.db import connections, transaction
from django.http import FileResponse, StreamingHttpResponse
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from rest_framework.permissions import AllowAny
from rest_framework.test import APIClient, APIRequestFactory
from rest_framework.views import APIView

from apps.access import context as access_context
from apps.access import softech_gate as gate
from apps.access.middleware import AccessContextMiddleware
from apps.access.softech_gate import GateDecision
from apps.audit.models import AuditLog
from apps.pos_orders import writer as pos_writer
from apps.pos_orders.models import SoftechSalesOrder
from apps.sync.softech_load import scope as softech_scope
from apps.tests.factories import make_branch, make_item, make_user
from config import sybase
from config.sybase import SoftechAccessDenied, SoftechZoneWriteDenied

from .test_access_softech_refusal import _FakeSoftech

ROOT = Path(__file__).resolve().parents[3]
CHECK = 'apps.access.softech_gate.check'
MODE = 'apps.access.softech_gate.mode'
READ_Z2 = GateDecision(gate.READ, 'zone_no_write', 'web:internal:supervisor', 'Z2')
NONE_Z3 = GateDecision(gate.NONE, 'zone_no_read', 'web:external:supervisor', 'Z3')
FULL_Z1 = GateDecision(gate.FULL, None, 'web:internal:supervisor', 'Z1')


def _rows():
    return AuditLog.objects.filter(action=gate.AUDIT_ACTION)


# ── I1 / I3: the shared pre-check ─────────────────────────────────────────────

class RequireWriteTests(TestCase):

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def test_enforce_read_is_refused_and_audited_once(self):
        with mock.patch(CHECK, return_value=READ_Z2), mock.patch(MODE, return_value='enforce'), \
                mock.patch.object(gate, 'note') as note:
            self.assertEqual(gate.require_write('x'), READ_Z2)
        note.assert_called_once()
        self.assertTrue(note.call_args.kwargs['enforced'])

    def test_enforce_none_is_refused_without_a_second_row(self):
        # check() returns NONE only in enforce and has already noted it
        with mock.patch(CHECK, return_value=NONE_Z3), mock.patch(MODE, return_value='enforce'), \
                mock.patch.object(gate, 'note') as note:
            self.assertEqual(gate.require_write('x'), NONE_Z3)
        note.assert_not_called()

    def test_full_and_log_mode_pass(self):
        with mock.patch(CHECK, return_value=FULL_Z1), mock.patch(MODE, return_value='enforce'):
            self.assertIsNone(gate.require_write('x'))
        with mock.patch(CHECK, return_value=READ_Z2), mock.patch(MODE, return_value='log'), \
                mock.patch.object(gate, 'note') as note:
            self.assertIsNone(gate.require_write('x'))
        note.assert_not_called()

    @override_settings(SOFTECH_GATE_ENFORCEMENT='enforce', NETWORK_ENFORCE_GUARD=False)
    def test_real_check_refuses_outside_in_enforce(self):
        user, _, _ = make_user('rw_sales', role='salesperson')
        net = SimpleNamespace(zone='external', ip='1.2.3.4', site=None)
        token = access_context.access_context.set(access_context.AccessContext(
            network=net, user_id=user.pk, role='salesperson', device=None, zone='Z4'))
        self.addCleanup(access_context.access_context.reset, token)
        with softech_scope('web:external:salesperson'):
            refused = gate.require_write('probe')
        self.assertEqual(refused.grant, gate.NONE)
        self.assertEqual(_rows().count(), 1)


@override_settings(POS_WRITER_ENABLED=True)
class FlushNowGateTests(TestCase):
    URL = '/api/pos-orders/flush/'

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        _, _, self.client = make_user('flush_admin', role='admin')
        self.order = SoftechSalesOrder.objects.create(
            branch=make_branch(), softech_branchcode='130', store_code='130',
            softech_pic='130HD9668', status=SoftechSalesOrder.STATUS_QUEUED)

    def test_refused_flush_is_403_and_leaves_queued_orders_alone(self):
        with mock.patch(CHECK, return_value=READ_Z2), mock.patch(MODE, return_value='enforce'), \
                mock.patch.object(pos_writer, 'push_order') as push:
            r = self.client.post(self.URL, {'include_failed': True}, format='json')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json(), {'detail': gate.WRITE_DENY_MESSAGE, 'code': 'softech_zone'})
        push.assert_not_called()
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, SoftechSalesOrder.STATUS_QUEUED)

    def test_log_mode_flush_still_runs(self):
        with mock.patch(CHECK, return_value=READ_Z2), mock.patch(MODE, return_value='log'), \
                mock.patch.object(pos_writer, 'push_order', return_value={'queued': True}) as push:
            r = self.client.post(self.URL, {}, format='json')
        self.assertEqual(r.status_code, 200)
        push.assert_called_once()


class InvoicePushBatchGateTests(TestCase):
    URL = '/api/invoices/invoices/push-batch/'

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        _, profile, self.client = make_user('inv_admin', role='admin')
        profile.softech_user_id = '1509'
        profile.save(update_fields=['softech_user_id'])

    def test_refused_push_batch_is_403_before_any_invoice(self):
        from apps.invoices import writer as inv_writer
        with mock.patch(CHECK, return_value=NONE_Z3), mock.patch(MODE, return_value='enforce'), \
                mock.patch.object(inv_writer, 'push_final') as push:
            r = self.client.post(self.URL, {'invoice_ids': [1, 2], 'confirm_count': '2'}, format='json')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json(), {'detail': gate.DENY_MESSAGE, 'code': 'softech_zone'})
        push.assert_not_called()


class InvoiceSinglePushGateTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        _, profile, self.client = make_user('inv1_admin', role='admin')
        profile.softech_user_id = '1509'
        profile.save(update_fields=['softech_user_id'])

    def test_refused_single_push_is_403_and_changes_nothing(self):
        from apps.invoices import writer as inv_writer
        from apps.invoices.models import SupplierInvoice
        inv = SupplierInvoice.objects.create(branch=make_branch(), status='confirmed')
        with mock.patch(CHECK, return_value=NONE_Z3), mock.patch(MODE, return_value='enforce'),                 mock.patch.object(inv_writer, 'push_final') as push:
            r = self.client.post(f'/api/invoices/invoices/{inv.pk}/push/', {}, format='json')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json(), {'detail': gate.DENY_MESSAGE, 'code': 'softech_zone'})
        push.assert_not_called()
        inv.refresh_from_db()
        self.assertEqual(inv.status, 'confirmed')


class ShortageGateTests(TestCase):
    PUSH = 'apps.purchasing.shortage_writer.push_item'

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        _, _, self.client = make_user('sg_admin', role='admin')
        self.item = make_item(softech_id='SG001')

    def _post(self, what, decision, mode='enforce', **body):
        with mock.patch(CHECK, return_value=decision), mock.patch(MODE, return_value=mode), \
                mock.patch(self.PUSH, return_value=True) as push:
            r = self.client.post(f'/api/purchasing/shortage/{what}/',
                                 {'item_id': self.item.id, **body}, format='json')
        return r, push

    def test_refused_flag_changes_nothing_and_queues_nothing(self):
        self.item.shortage_softech_synced = True
        self.item.save(update_fields=['shortage_softech_synced'])
        r, push = self._post('flag', READ_Z2)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()['code'], 'softech_zone')
        push.assert_not_called()
        self.item.refresh_from_db()
        self.assertFalse(self.item.in_shortage)
        self.assertTrue(self.item.shortage_softech_synced)      # nothing left for the system job

    def test_refused_unflag(self):
        self.item.in_shortage = True
        self.item.shortage_softech_synced = True
        self.item.save(update_fields=['in_shortage', 'shortage_softech_synced'])
        r, push = self._post('unflag', NONE_Z3)
        self.assertEqual(r.status_code, 403)
        push.assert_not_called()
        self.item.refresh_from_db()
        self.assertTrue(self.item.in_shortage)
        self.assertTrue(self.item.shortage_softech_synced)

    def test_refused_dismiss_that_writes_softech(self):
        self.item.in_shortage = True
        self.item.save(update_fields=['in_shortage'])
        r, push = self._post('dismiss', READ_Z2, reason='other')
        self.assertEqual(r.status_code, 403)
        push.assert_not_called()
        self.item.refresh_from_db()
        self.assertFalse(self.item.shortage_dismissed)
        self.assertTrue(self.item.in_shortage)

    def test_dismiss_with_no_softech_write_is_gated_too(self):         # I3: always, any state
        r, push = self._post('dismiss', READ_Z2, reason='other')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()['code'], 'softech_zone')
        push.assert_not_called()
        self.item.refresh_from_db()
        self.assertFalse(self.item.shortage_dismissed)

    def test_dismiss_allowed_when_not_refused(self):
        r, push = self._post('dismiss', READ_Z2, mode='log', reason='other')
        self.assertEqual(r.status_code, 200)
        push.assert_not_called()
        self.item.refresh_from_db()
        self.assertTrue(self.item.shortage_dismissed)

    def test_refused_retrieve_of_a_pending_unsynced_item(self):        # I3: the narrow hole
        self.item.shortage_dismissed = True
        self.item.shortage_dismiss_reason = 'on_request'
        self.item.shortage_supply_suspended = False
        self.item.shortage_softech_synced = False
        self.item.save(update_fields=['shortage_dismissed', 'shortage_dismiss_reason',
                                      'shortage_supply_suspended', 'shortage_softech_synced'])
        r, push = self._post('retrieve', READ_Z2)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()['code'], 'softech_zone')
        push.assert_not_called()
        self.item.refresh_from_db()
        self.assertTrue(self.item.shortage_dismissed)
        self.assertEqual(self.item.shortage_dismiss_reason, 'on_request')
        self.assertFalse(self.item.shortage_softech_synced)

    def test_refused_retrieve_of_a_suspended_item(self):
        self.item.shortage_dismissed = True
        self.item.shortage_supply_suspended = True
        self.item.shortage_softech_synced = True
        self.item.save(update_fields=['shortage_dismissed', 'shortage_supply_suspended',
                                      'shortage_softech_synced'])
        r, push = self._post('retrieve', READ_Z2)
        self.assertEqual(r.status_code, 403)
        push.assert_not_called()
        self.item.refresh_from_db()
        self.assertTrue(self.item.shortage_dismissed)
        self.assertTrue(self.item.shortage_softech_synced)

    def test_log_mode_flag_unchanged(self):
        r, push = self._post('flag', READ_Z2, mode='log')
        self.assertEqual(r.status_code, 200)
        push.assert_called_once()
        self.item.refresh_from_db()
        self.assertTrue(self.item.in_shortage)


# ── I1 defence in depth: a refused push of an already-queued order stays queued ──

@override_settings(POS_WRITER_ENABLED=True, SOFTECH_READ_ONLY=False)
class QueuedOrderRefusalTests(TestCase):

    def setUp(self):
        cache.clear()
        branch = make_branch()
        branch.db_host = '10.0.0.130'
        branch.save()
        self.softech = _FakeSoftech()
        self.driver = mock.Mock(name='driver')
        self.driver.connect.return_value = self.softech
        test = self

        def real_gate_connect(*args, **kwargs):
            return sybase._connect_with_retry(test.driver, 'jdbc:x', mock.Mock(), label='branch')

        def first_statement_is_a_write(conn, order, seller):
            conn.prepareStatement('UPDATE serials SET n = n + 1')   # the serial allocation
            return {'ok': True, 'docnumber': 1}

        self.make = lambda status: SoftechSalesOrder.objects.create(
            branch=branch, softech_branchcode='130', store_code='130', softech_pic='130HD9668',
            status=status)
        for p in (mock.patch.object(pos_writer, 'build_payload', return_value={}),
                  mock.patch('apps.pos_orders.stock.check_item_restrictions', return_value=[]),
                  mock.patch('apps.pos_orders.stock.enabled', return_value=False),
                  mock.patch('config.sybase.get_branch_connection', side_effect=real_gate_connect),
                  mock.patch('config.sybase._load', return_value=mock.Mock()),
                  mock.patch('config.sybase.time.sleep'),
                  mock.patch(MODE, return_value='enforce'),
                  mock.patch.object(pos_writer, '_execute_write',
                                    side_effect=first_statement_is_a_write)):
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(cache.clear)

    def _push(self, order, decision):
        with mock.patch(CHECK, return_value=decision):
            return pos_writer.push_order(order, dry_run=False)

    def test_queued_order_refused_at_connect_stays_queued(self):
        order = self.make(SoftechSalesOrder.STATUS_QUEUED)
        with self.assertRaises(SoftechAccessDenied):
            self._push(order, NONE_Z3)
        order.refresh_from_db()
        self.assertEqual(order.status, SoftechSalesOrder.STATUS_QUEUED)
        self.driver.connect.assert_not_called()

    def test_queued_order_refused_at_first_write_stays_queued(self):
        order = self.make(SoftechSalesOrder.STATUS_QUEUED)
        with self.assertRaises(SoftechZoneWriteDenied):
            self._push(order, READ_Z2)
        order.refresh_from_db()
        self.assertEqual(order.status, SoftechSalesOrder.STATUS_QUEUED)
        self.assertIn('kept queued', order.erp_error)

    def test_ready_order_refused_is_still_push_failed(self):
        order = self.make(SoftechSalesOrder.STATUS_READY)
        with self.assertRaises(SoftechAccessDenied):
            self._push(order, NONE_Z3)
        order.refresh_from_db()
        self.assertEqual(order.status, SoftechSalesOrder.STATUS_PUSH_FAILED)


# ── I2: the gate row survives the caller's rollback ───────────────────────────

class GateRowSurvivesRollbackTests(TestCase):
    """The test lists the `audit_log` mirror, which Django does NOT wrap in the test transaction:
    it is a second, autocommit connection to the same test database - as in production. So a row
    it writes survives the rollback of the caller's atomic block (and is deleted by hand after).
    No TransactionTestCase: its flush would wipe the migration-seeded rows of the --keepdb DB."""
    databases = {'default', 'audit_log'}

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.addCleanup(lambda: AuditLog.objects.using('audit_log')
                        .filter(action=gate.AUDIT_ACTION, note__startswith='i2-').delete())
        net = SimpleNamespace(zone='external', ip='1.2.3.4', site=None)
        token = access_context.access_context.set(access_context.AccessContext(
            network=net, user_id=None, role=None, device=None, zone='Z4'))
        self.addCleanup(access_context.access_context.reset, token)

    def test_refusal_inside_a_rolled_back_atomic_keeps_its_row(self):
        refusal = GateDecision(gate.NONE, 'i2-zone_no_read', 'web:external:anon', 'Z4')
        with self.assertRaises(SoftechAccessDenied):
            with transaction.atomic():           # e.g. insurance rebalance: SOFTECH last in atomic
                gate.note(refusal, 'reprice', enforced=True, mode='enforce')
                raise SoftechAccessDenied(reason=refusal.reason)
        rows = list(AuditLog.objects.using('audit_log')
                    .filter(action=gate.AUDIT_ACTION, note__startswith='i2-'))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].extra['reason'], 'i2-zone_no_read')
        self.assertTrue(rows[0].extra['enforced'])


class DedupeAfterInsertTests(TestCase):

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        net = SimpleNamespace(zone='external', ip='1.2.3.4', site=None)
        token = access_context.access_context.set(access_context.AccessContext(
            network=net, user_id=None, role=None, device=None, zone='Z4'))
        self.addCleanup(access_context.access_context.reset, token)

    def test_a_lost_row_does_not_silence_the_next_refusal(self):
        with mock.patch.object(gate, '_write_row', return_value=False):
            with self.assertLogs('elrezeiky.access', 'ERROR'):
                gate.note(NONE_Z3, 'probe', enforced=True, mode='enforce')
        self.assertEqual(_rows().count(), 0)
        gate.note(NONE_Z3, 'probe', enforced=True, mode='enforce')     # the next refusal
        self.assertEqual(_rows().count(), 1)
        gate.note(NONE_Z3, 'probe', enforced=True, mode='enforce')     # now deduped
        self.assertEqual(_rows().count(), 1)

    def test_n1_audit_log_write_has_no_default_savepoint(self):
        with mock.patch.object(gate.transaction, 'atomic', side_effect=AssertionError('savepoint')),                 mock.patch.object(gate, 'connections', mock.MagicMock()):
            with mock.patch('apps.audit.models.AuditLog.log', return_value=object()):
                self.assertTrue(gate._insert_row(gate.AUDIT_DB_ALIAS, None, 'n1', {}))
            with mock.patch('apps.audit.models.AuditLog.log', return_value=object()):
                with self.assertRaises(AssertionError):      # the default fallback does use one
                    gate._insert_row('default', None, 'n1', {})

    def test_n2_fallback_warns_once_and_does_not_set_the_dedupe_key(self):
        def fake(alias, *a):
            return alias == 'default'
        with mock.patch.object(gate, '_audit_aliases', return_value=('audit_log', 'default')),                 mock.patch.object(gate, '_insert_row', side_effect=lambda al, *a: fake(al)):
            with self.assertLogs('elrezeiky.access', 'WARNING') as cm:
                gate.note(NONE_Z3, 'probe', enforced=True, mode='enforce')
            self.assertTrue(any('falling back' in m for m in cm.output))
            gate.note(NONE_Z3, 'probe', enforced=True, mode='enforce')   # the warning is deduped
        self.assertEqual(len([m for m in cm.output if 'falling back' in m]), 1)

    def test_n2_fallback_retries_the_row_next_time(self):
        calls = []

        def fake(alias, *a):
            calls.append(alias)
            return alias == 'default'
        with mock.patch.object(gate, '_audit_aliases', return_value=('audit_log', 'default')),                 mock.patch.object(gate, '_insert_row', side_effect=fake):
            gate.note(NONE_Z3, 'probe', enforced=True, mode='enforce')
            gate.note(NONE_Z3, 'probe', enforced=True, mode='enforce')
        self.assertEqual(calls.count('default'), 2)

    def test_n4_lost_error_is_throttled(self):
        with mock.patch.object(gate, '_write_row', return_value=False):
            with self.assertLogs('elrezeiky.access', 'ERROR') as cm:
                for _ in range(5):
                    gate.note(NONE_Z3, 'probe', enforced=True, mode='enforce')
        self.assertEqual(len([m for m in cm.output if 'audit row lost' in m]), 1)

    def test_audit_alias_is_configured_as_a_mirror(self):
        self.assertIn('audit_log', connections.databases)
        self.assertEqual(connections.databases['audit_log']['TEST']['MIRROR'], 'default')
        self.assertEqual(gate._audit_aliases()[0], 'audit_log')


# ── I4: system checks ─────────────────────────────────────────────────────────

class GateSwitchCheckTests(SimpleTestCase):

    def _ids(self):
        from django.core.checks import run_checks
        return {m.id for m in run_checks() if m.id and m.id.startswith('access.')}

    @override_settings(SOFTECH_GATE_ENFORCEMENT='enforce', NETWORK_ENFORCE_GUARD=True,
                       NETWORK_HEADER_TRUSTED=False, NETWORK_POLICY_ENFORCEMENT='log')
    def test_enforce_on_an_unsafe_setup_is_e005(self):
        self.assertIn('access.E005', self._ids())

    @override_settings(SOFTECH_GATE_ENFORCEMENT='enforced')
    def test_unknown_value_is_w003(self):
        self.assertIn('access.W003', self._ids())

    @override_settings(SOFTECH_GATE_ENFORCEMENT='enforce', NETWORK_ENFORCE_GUARD=True,
                       NETWORK_HEADER_TRUSTED=True, NETWORK_PROXY_KEY='k' * 32)
    def test_enforce_on_a_safe_setup_is_clean(self):
        ids = self._ids()
        self.assertNotIn('access.E005', ids)
        self.assertNotIn('access.W003', ids)

    def test_runbook_step_5_names_the_checks_and_its_own_grep(self):
        text = (ROOT / 'deploy' / 'LINKDATACENTER_VPS_RUNBOOK.md').read_text(encoding='utf-8')
        n4 = text[text.index('#### Batch N4 on the live server'):]
        self.assertIn('access.E005', n4)
        self.assertIn('access.W003', n4)
        self.assertIn("grep 'SOFTECH_GATE_ENFORCEMENT=enforce refused'", n4)
        self.assertIn('softech_mode', n4[n4.index('Step 6'):])


# ── Minors ────────────────────────────────────────────────────────────────────

def _through_middleware(response):
    mw = AccessContextMiddleware(lambda request: response)
    fake = SimpleNamespace(network=SimpleNamespace(zone='internal', ip='10.0.0.1'),
                           role='pharmacist', user_id=1)
    with mock.patch('apps.access.context.for_request', return_value=fake):
        return mw(RequestFactory().get('/api/x/'))


class StreamingWrapperTests(SimpleTestCase):

    def test_file_response_keeps_file_to_stream(self):                             # M1
        res = _through_middleware(FileResponse(io.BytesIO(b'abc')))
        self.assertIsNotNone(res.file_to_stream)
        self.assertEqual(b''.join(res.streaming_content), b'abc')

    def test_disconnect_closes_the_generator_inside_the_request_context(self):     # M3
        var = contextvars.ContextVar('m3_var', default=None)
        state = {}

        def gen():
            token = var.set('inside')
            try:
                yield b'a'
                yield b'b'
            finally:
                var.reset(token)                 # ValueError if run in another Context
                state['cleaned'] = True

        res = _through_middleware(StreamingHttpResponse(gen()))
        it = iter(res.streaming_content)
        self.assertEqual(next(it), b'a')
        res.close()                              # the client went away mid-stream
        self.assertTrue(state.get('cleaned'))

    def test_error_mid_stream_propagates(self):                                     # M3
        def gen():
            yield b'a'
            raise RuntimeError('boom')

        res = _through_middleware(StreamingHttpResponse(gen()))
        it = iter(res.streaming_content)
        next(it)
        with self.assertRaises(RuntimeError):
            next(it)


class NoDeadThreadingImports(SimpleTestCase):                                       # M2

    def test_threading_imports_are_used(self):
        out = []
        for base in ('apps', 'core'):
            for p in (ROOT / base).rglob('*.py'):
                rel = p.relative_to(ROOT).as_posix()
                if '/migrations/' in rel:
                    continue
                tree = ast.parse(p.read_text(encoding='utf-8-sig'))
                bound = {}
                for n in ast.walk(tree):
                    if isinstance(n, ast.Import):
                        for a in n.names:
                            if a.name == 'threading':
                                bound[a.asname or a.name] = n.lineno
                    elif isinstance(n, ast.ImportFrom) and n.module == 'threading':
                        for a in n.names:
                            bound[a.asname or a.name] = n.lineno
                if not bound:
                    continue
                used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
                out += [f'{rel}:{line} {name}' for name, line in bound.items() if name not in used]
        self.assertEqual(out, [])


class _Raises(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        raise SoftechZoneWriteDenied()


class RefusalRollbackTests(TestCase):                                               # M4

    def test_refusal_marks_an_atomic_request_for_rollback(self):
        conn = connections['default']
        with mock.patch.dict(conn.settings_dict, {'ATOMIC_REQUESTS': True}):
            with transaction.atomic():
                res = _Raises.as_view()(APIRequestFactory().get('/x/'))
                self.assertEqual(res.status_code, 403)
                self.assertTrue(transaction.get_rollback())


class RepriceRefusalNotRetriedTests(TestCase):                                      # M5

    def test_refusal_with_a_transient_word_is_not_retried(self):
        # apply_plan retries once only when _is_transient() says so
        from apps.insurance import reprice_service as rs
        refusal = SoftechAccessDenied('refused (socket timeout)', reason='zone_no_read')
        self.assertFalse(rs._is_transient(refusal))
        self.assertTrue(rs._is_transient(Exception('socket timeout')))


class UnsafeLineNamesSwitchTests(SimpleTestCase):                                   # M8

    @override_settings(SOFTECH_GATE_ENFORCEMENT='enforce', NETWORK_POLICY_ENFORCEMENT='enforce',
                       NETWORK_ENFORCE_GUARD=True, NETWORK_HEADER_TRUSTED=False)
    def test_each_switch_gets_its_own_line(self):
        from apps.access.policy_middleware import _mode
        cache.clear()
        self.addCleanup(cache.clear)
        with self.assertLogs('elrezeiky.access', 'ERROR') as logs:
            self.assertEqual(gate.mode(), 'log')
            self.assertEqual(_mode(), 'log')
        text = '\n'.join(logs.output)
        self.assertIn('SOFTECH_GATE_ENFORCEMENT=enforce refused', text)
        self.assertIn('NETWORK_POLICY_ENFORCEMENT=enforce refused', text)


@override_settings(NETWORK_HEADER_TRUSTED=True, NETWORK_PROXY_KEY='', ACCESS_POLICY_TTL=0,
                   SOFTECH_GATE_ENFORCEMENT='enforce', NETWORK_POLICY_ENFORCEMENT='log')
class WhoamiAnonymousTests(TestCase):                                               # M9

    def test_anonymous_gets_no_gate_mode(self):
        cache.clear()
        d = APIClient().get('/api/access/whoami/', HTTP_X_ELR_NETWORK='external').json()
        self.assertIsNone(d['softech_gate_mode'])
        self.assertIsNone(d['softech_access'])

    def test_anonymous_gets_no_policy_mode(self):
        cache.clear()
        d = APIClient().get('/api/access/whoami/', HTTP_X_ELR_NETWORK='external').json()
        self.assertIsNone(d['policy_mode'])

    def test_signed_in_still_gets_it(self):
        from rest_framework_simplejwt.tokens import AccessToken
        cache.clear()
        user, _, _ = make_user('wh_m9', role='pharmacist')
        d = APIClient().get('/api/access/whoami/', HTTP_X_ELR_NETWORK='internal',
                            HTTP_AUTHORIZATION=f'Bearer {AccessToken.for_user(user)}').json()
        self.assertEqual(d['softech_gate_mode'], 'enforce')
        self.assertEqual(d['policy_mode'], 'log')


class ObservationSignatureTests(TestCase):                                          # M10

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        net = SimpleNamespace(zone='internal', ip='10.0.0.9', site=None)
        token = access_context.access_context.set(access_context.AccessContext(
            network=net, user_id=None, role=None, device=None, zone='Z2'))
        self.addCleanup(access_context.access_context.reset, token)

    def test_log_mode_row_carries_first_keyword_and_write_word_not_the_sql(self):
        check = sybase._zone_write_check(READ_Z2, 'branch 130', observe_only=True)
        check("SELECT load, qty FROM stkbal WHERE note = 'secret'")
        row = _rows().get()
        self.assertEqual((row.extra['sql_first'], row.extra['write_word']), ('SELECT', 'LOAD'))
        self.assertNotIn('secret', str(row.extra))

    def test_preflight_groups_by_the_signature(self):
        from apps.access import preflight
        check = sybase._zone_write_check(READ_Z2, 'branch 130', observe_only=True)
        check('UPDATE stkbal SET qty = 1')
        items = {i.code: i for i in preflight.check_softech(timezone.now())}
        self.assertTrue(any('[UPDATE / UPDATE]' in n for n in items['softech_would_deny'].names))
