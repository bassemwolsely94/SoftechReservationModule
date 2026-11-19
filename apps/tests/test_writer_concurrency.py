"""
Full audit Wave 4 — concurrency harness for the SOFTECH writers' double-post guards.

docs/full-project-audit/10_TEST_STRATEGY_AND_RESULTS.md ("Concurrency — no test runs two writers at once") and
13_IMPLEMENTATION_ROADMAP.md Wave 4. Each test starts TWO real threads, each with its own PostgreSQL
connection (= two web workers / a click + the flush job), releases them together, and asserts that exactly
ONE SOFTECH post happens. The guards under test are the ones registered in
apps/tests/security/softech_write_manifest.py:

  POS push        writer.push_order          atomic PG claim → PUSHING (P-11)
  pos_cancel      write_pos_cancel_batch     claim-before-write under a per-run token (round 2 S-3)
  ISR push        isr_writer.push_isr_record advisory lock per draft + status re-read (P-15)
  A/P allocation  recon_writer.push_allocation advisory locks on invoice + voucher (S-2)
  purchase invoice invoices.writer.push_final atomic PG flip → 'pushing'

SOFTECH is never contacted: the connection is a mock / in-memory fake and the write step is a recorder.
To force a real overlap, the write step of whichever thread gets there first WAITS until the other thread has
finished — so the second caller always runs while the first is mid-write. If a guard ever let both in, both
writers record a post (and wait out a short timeout) and the test fails on the count.

TransactionTestCase: the guards rely on committed rows and on separate database sessions, which a TestCase's
single wrapping transaction cannot give. Django runs these after every TestCase, so their flush cannot wipe
data another module needs (precedent: test_gl_ledger.LedgerConcurrencyTests).
"""
import threading
from contextlib import ExitStack
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.db import connections
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from core.threads import start_thread

WAIT = 10          # seconds: a guard that lets both callers in costs one WAIT, then fails on the count


class Race:
    """Two (or n) callers released together; the first one into the SOFTECH write is held there until every
    other caller has returned."""

    def __init__(self, n=2):
        self.n = n
        self._start = threading.Barrier(n)
        self._checked = threading.Barrier(n)
        self._cond = threading.Condition()
        self._finished = 0
        self._lock = threading.Lock()
        self.posts = []                 # one entry per SOFTECH post (thread name, payload)

    # ── hooks wired into the code under test through mocks ─────────────────────
    def checkpoint(self, result=None):
        """side_effect: every caller has passed its in-memory checks before any of them claims."""
        def _hit(*a, **k):
            self._checked.wait(timeout=WAIT)
            return result
        return _hit

    def post(self, result):
        """side_effect for the SOFTECH write: record it, then hold until the other callers are done."""
        def _hit(*a, **k):
            with self._lock:
                self.posts.append((threading.current_thread().name, a[1:3] if len(a) > 2 else a))
            with self._cond:
                self._cond.wait_for(lambda: self._finished >= self.n - 1, timeout=WAIT)
            return result(*a, **k) if callable(result) else result
        return _hit

    # ── driver ──────────────────────────────────────────────────────────────────
    def run(self, fn):
        """Run fn(i) on n threads at once; returns [(kind, value)] per thread, kind 'ok' or 'error'."""
        outcomes = [None] * self.n

        def worker(i):
            try:
                self._start.wait(timeout=WAIT)
                outcomes[i] = ('ok', fn(i))
            except Exception as exc:                # surfaced by the asserts
                outcomes[i] = ('error', exc)
            finally:
                connections.close_all()          # this thread's sessions (default + audit_log)
                with self._cond:
                    self._finished += 1
                    self._cond.notify_all()

        threads = [start_thread(worker, args=(i,), name=f'caller-{i}', daemon=False) for i in range(self.n)]
        for t in threads:
            t.join(timeout=4 * WAIT)
        assert not any(t.is_alive() for t in threads), 'a caller hung'
        return outcomes


def _patches(stack, *patches):
    for p in patches:
        stack.enter_context(p)


def _branch(code, host=None):
    from apps.branches.models import Branch
    return Branch.objects.get_or_create(softech_branch_id=code, defaults={
        'name': code, 'name_ar': code, 'is_active': True, 'db_host': host or f'10.0.0.{code[-2:]}'})[0]


# ── POS sale push ─────────────────────────────────────────────────────────────

@override_settings(WRITER_INSTANCE=True, POS_WRITER_ENABLED=True)
class PosPushRaceTests(TransactionTestCase):
    databases = {'default', 'audit_log'}

    def setUp(self):
        from apps.pos_orders.models import SoftechSalesOrder, SoftechSalesOrderLine
        self.M = SoftechSalesOrder
        br = _branch('B31', host='10.0.0.31')
        self.order = SoftechSalesOrder.objects.create(
            branch=br, softech_branchcode=br.softech_branch_id, store_code='B31', channel='cash',
            doc_kind='sale', customer_name='TEST', seller_usercode='2050', status=SoftechSalesOrder.STATUS_READY)
        SoftechSalesOrderLine.objects.create(order=self.order, item=None, softech_itemcode='107295',
                                             item_name='ITM1', qty=1, item_sale_price=108, sale_tax_pct=0,
                                             cust_discp=0, new_cost_price='81.1306')

    def test_push_button_and_flush_job_post_the_sale_once(self):
        from apps.pos_orders import stock, writer
        race = Race()
        with ExitStack() as stack:
            _patches(stack,
                     mock.patch('config.sybase.get_branch_connection', return_value=mock.MagicMock()),
                     mock.patch.object(writer, 'build_payload', side_effect=race.checkpoint({})),
                     mock.patch.object(writer, '_pending_docnumber_by_vf2', return_value=None),
                     mock.patch.object(writer, '_execute_write',
                                       side_effect=race.post({'ok': True, 'docnumber': 470001})),
                     mock.patch.object(stock, 'check_item_restrictions', return_value=[]),
                     mock.patch.object(stock, 'enabled', return_value=False))
            out = race.run(lambda i: writer.push_order(self.M.objects.get(pk=self.order.pk), dry_run=False))

        self.assertEqual(len(race.posts), 1, f'the sale was posted {len(race.posts)} times: {out}')
        modes = sorted(v['mode'] for kind, v in out if kind == 'ok')
        self.assertEqual(modes, ['busy', 'commit'], out)
        self.order.refresh_from_db()
        self.assertEqual((self.order.status, int(self.order.softech_docnumber)), (self.M.STATUS_PUSHED, 470001))


# ── pos_cancel lost-sale log ──────────────────────────────────────────────────

@override_settings(WRITER_INSTANCE=True, POS_CANCEL_WRITE_ENABLED=True)
class PosCancelRaceTests(TransactionTestCase):
    databases = {'default', 'audit_log'}

    def setUp(self):
        from apps.pos_orders.models import PosSelectionEvent
        self.E = PosSelectionEvent
        br = _branch('B32', host='10.0.0.32')
        for code in ('96690', '96691', '96692'):
            PosSelectionEvent.objects.create(
                branch=br, softech_branchcode='B32', doc_kind='sale', event_type='add', item_code=code,
                item_name='ASPIRIN', itemsaleprice='28.5', transprice='28.5', transqty=1, transprice_total=28.5,
                custcode='1510', seller_usercode='1509', occurred_at=timezone.now() - timedelta(minutes=600))

    def test_two_scheduler_processes_insert_each_row_once(self):
        from apps.pos_orders import pos_cancel_writer as PCW
        from apps.pos_orders import writer as W
        race = Race()
        with ExitStack() as stack:
            _patches(stack,
                     mock.patch('config.sybase.get_branch_connection', return_value=mock.MagicMock()),
                     mock.patch.object(PCW, '_sold_codes_by_cart', side_effect=race.checkpoint({})),
                     mock.patch.object(W, '_exec_insert', side_effect=race.post(None)))
            out = race.run(lambda i: PCW.write_pos_cancel_batch(dry_run=False))

        codes = sorted(row['itemcode'] for _, (table, row) in race.posts)
        self.assertEqual(codes, ['96690', '96691', '96692'], f'pos_cancel rows posted: {codes} — {out}')
        written = sorted(v['written'] for kind, v in out if kind == 'ok')
        self.assertEqual(written, [0, 3], out)
        self.assertEqual(self.E.objects.filter(softech_written_at__isnull=True).count(), 0)
        self.assertEqual(self.E.objects.exclude(write_error='').count(), 0)        # no claim token left behind


# ── ISR push ──────────────────────────────────────────────────────────────────

@override_settings(WRITER_INSTANCE=True, ISR_WRITER_ENABLED=True)
class IsrPushRaceTests(TransactionTestCase):
    databases = {'default', 'audit_log'}

    def setUp(self):
        from apps.purchasing import isr_writer as W
        from apps.purchasing.models import IsrPush as P
        from apps.tests.factories import make_hq
        from apps.tests.test_isr_guards import _lines
        self.W, self.P = W, P
        _branch('100'), _branch('160')
        make_hq('100', self)
        p = W._persist_proposal(source='100', dest='160', kind=P.KIND_HQ_TO_BRANCH, lines=_lines(('A', 2)))
        P.objects.filter(pk=p.pk).update(status=P.STATUS_APPROVED)
        self.pk = p.pk

    def test_two_clicks_write_one_isr(self):
        from apps.purchasing import isr_guards
        race = Race()
        with ExitStack() as stack:
            _patches(stack,
                     mock.patch('config.sybase.get_branch_connection', return_value=mock.MagicMock()),
                     mock.patch.object(isr_guards, 'check_push', return_value=None),
                     mock.patch.object(isr_guards, 'review_push', return_value={'needs_reason': False, 'issues': []}),
                     mock.patch.object(isr_guards, 'enforce_review', return_value=None),
                     mock.patch.object(self.W, '_write_isr', side_effect=race.post(
                         {'verified': True, 'committed': True, 'isrdocnumber': 900001})))
            out = race.run(lambda i: self.W.push_isr_record(self.P.objects.get(pk=self.pk)))

        self.assertEqual(len(race.posts), 1, f'the ISR was written {len(race.posts)} times: {out}')
        kinds = sorted(kind for kind, _ in out)
        self.assertEqual(kinds, ['error', 'ok'], out)
        self.assertIsInstance(next(v for kind, v in out if kind == 'error'), ValueError)
        p = self.P.objects.get(pk=self.pk)
        self.assertEqual((p.status, int(p.isrdocnumber)), (self.P.STATUS_PUSHED, 900001))


# ── A/P allocation (سداد) ─────────────────────────────────────────────────────

class _SharedFakeSoftech:
    """One in-memory SOFTECH (test_reconciliation_writer._FakeSoftech) shared by both callers; every
    chequestrans INSERT is a post."""

    def __init__(self, race):
        from apps.tests.test_reconciliation_writer import _FakeSoftech
        self.fake, self.race = _FakeSoftech(), race
        self._insert = race.post(None)

    def __call__(self, *a, **k):               # get_sybase_connection()
        return self

    def cursor(self):
        return self

    def close(self):
        pass

    def fetchone(self):
        return self.fake.fetchone()

    def execute(self, sql):
        if sql.lstrip().upper().startswith('INSERT') and 'chequestrans' in sql:
            self._insert(None, 'chequestrans', sql)
        return self.fake.execute(sql)


@override_settings(WRITER_INSTANCE=True, AP_RECONCILE_WRITER_ENABLED=True)
class ApAllocationRaceTests(TransactionTestCase):
    databases = {'default', 'audit_log'}

    def setUp(self):
        from apps.tests.test_reconciliation_writer import _setup
        _, self.inv, self.pay, self.alloc = _setup()

    def test_two_writes_of_one_allocation_post_one_chequestrans(self):
        from apps.finance import recon_writer
        from apps.finance.models import Allocation
        race = Race()
        softech = _SharedFakeSoftech(race)
        with mock.patch('config.sybase.get_sybase_connection', side_effect=softech):
            out = race.run(lambda i: recon_writer.push_allocation(
                Allocation.objects.get(pk=self.alloc.pk), dry_run=False))

        self.assertEqual(len(race.posts), 1, f'chequestrans posted {len(race.posts)} times: {out}')
        self.assertEqual(len(softech.fake.rows), 1)
        self.assertEqual(softech.fake.paid, Decimal('840'))                 # the invoice is paid once, not twice
        kinds = sorted(kind for kind, _ in out)
        self.assertEqual(kinds, ['error', 'ok'], out)
        self.assertIsInstance(next(v for kind, v in out if kind == 'error'), recon_writer.ReconWriteError)
        self.alloc.refresh_from_db()
        self.assertEqual(self.alloc.origin, Allocation.ORIGIN_WRITTEN)

    def test_two_vouchers_on_one_invoice_never_write_at_the_same_time(self):
        """Different allocations, same invoice: the invoice lock serialises them, so the second write
        always reads the header the first one left (no lost update of docvaluepay)."""
        from apps.finance import recon_writer
        from apps.finance.models import Allocation, Payment
        other = Payment.objects.create(party=self.pay.party, branchcode='100', cheqsno=51685, direction='out',
                                       party_type='supplier', voucher_date=self.pay.voucher_date,
                                       amount=Decimal('840'), note='مورد 12362', usercode='1509',
                                       is_unallocated=True)
        second = Allocation.objects.create(payment=other, invoice=self.inv, amount=Decimal('840'),
                                           origin=Allocation.ORIGIN_APPROVED)
        race = Race()
        softech = _SharedFakeSoftech(race)
        pks = [self.alloc.pk, second.pk]
        with mock.patch('config.sybase.get_sybase_connection', side_effect=softech):
            out = race.run(lambda i: recon_writer.push_allocation(
                Allocation.objects.get(pk=pks[i]), dry_run=False))

        self.assertEqual(len(race.posts), 1, f'two writes ran on one invoice at once: {out}')
        self.assertIsInstance(next(v for kind, v in out if kind == 'error'), recon_writer.ReconWriteError)


# ── purchase invoice push ─────────────────────────────────────────────────────

@override_settings(WRITER_INSTANCE=True, INVOICE_WRITER_ENABLED=True)
class PurchaseInvoiceRaceTests(TransactionTestCase):
    databases = {'default', 'audit_log'}

    def setUp(self):
        from apps.invoices.models import InvoiceLine, SupplierInvoice, VendorProfile
        from apps.tests.factories import make_item
        self.M = SupplierInvoice
        br = _branch('B33', host='10.0.0.33')
        vendor = VendorProfile.objects.create(name='V', softech_personcode='5014', is_main=True)
        self.inv = SupplierInvoice.objects.create(branch=br, vendor=vendor, supplier_name='S',
                                                  invoice_number='777', status='confirmed')
        InvoiceLine.objects.create(invoice=self.inv, item=make_item(softech_id='90792'), manual_name='X',
                                   quantity=5, public_price=28, unit_price=22)

    def test_two_users_post_the_invoice_once(self):
        from apps.invoices import writer
        race = Race()
        ok = {'ok': True, 'errors': [], 'warnings': [], 'notices': []}
        with ExitStack() as stack:
            _patches(stack,
                     mock.patch.object(writer, 'build_plan', side_effect=race.checkpoint({})),
                     mock.patch('apps.invoices.validations.validate_invoice', return_value=ok),
                     mock.patch.object(writer, 'branch_host', return_value='h'),
                     mock.patch.object(writer, 'compute', return_value=([], {})),
                     mock.patch('config.sybase.get_branch_connection', return_value=mock.MagicMock()),
                     mock.patch.object(writer, '_q1', return_value=None),            # no SOFTECH duplicate yet
                     mock.patch.object(writer, 'read_stkbal', return_value={}),
                     mock.patch.object(writer, 'read_supplier', return_value={'ptclassifcode': '1'}),
                     mock.patch.object(writer, '_run_write_batch', side_effect=race.post(
                         {'ok': True, 'committed': True, 'docnumber': 880001})))
            out = race.run(lambda i: writer.push_final(self.M.objects.get(pk=self.inv.pk), dry_run=False,
                                                       usercode='1509'))

        self.assertEqual(len(race.posts), 1, f'the invoice was posted {len(race.posts)} times: {out}')
        kinds = sorted(kind for kind, _ in out)
        self.assertEqual(kinds, ['error', 'ok'], out)
        self.assertIsInstance(next(v for kind, v in out if kind == 'error'), ValueError)
        self.inv.refresh_from_db()
        self.assertEqual((self.inv.status, int(self.inv.softech_docnumber)), ('finalized', 880001))
