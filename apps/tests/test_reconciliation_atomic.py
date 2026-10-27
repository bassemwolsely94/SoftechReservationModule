"""
apps/tests/test_reconciliation_atomic.py

Atomic SOFTECH writes (recon_writer._atomic, doc 23 §19): the chequestrans insert/
delete and the stktransm header update land TOGETHER or not at all; a rollback is
verified by re-reading SOFTECH; and complete_half_reversal repairs only a provably
half-landed reversal.
"""
import copy
from decimal import Decimal as D
from unittest import mock

from django.test import TestCase, override_settings

from apps.finance import recon_writer as W
from apps.finance.models import Allocation, ReconAuditEvent
from .test_reconciliation_writer import _FakeSoftech, _setup


class _TxFake(_FakeSoftech):
    """_FakeSoftech + real transaction semantics (snapshot on begin)."""

    def __init__(self, *a, fail_header=False, broken_rollback=False, **kw):
        super().__init__(*a, **kw)
        self.fail_header = fail_header
        self.broken_rollback = broken_rollback
        self._snap = None

    def begin(self):
        self._snap = (copy.deepcopy(self.rows), self.paid)

    def commit(self):
        self._snap = None

    def rollback(self):
        if self._snap and not self.broken_rollback:
            self.rows, self.paid = self._snap
        self._snap = None

    def execute(self, sql):
        s = ' '.join(sql.split())
        if s.startswith('set lock wait'):
            self._last = None
            return
        if self.fail_header and s.startswith('UPDATE') and 'stktransm' in s:
            raise RuntimeError('Could not acquire a lock within the specified wait period')
        if s.startswith('UPDATE') and 'chequestrans' in s and 'docvaluepaynow=' in s:
            import re as _re
            self.rows[-1]['now'] = D(_re.search(r'docvaluepaynow=([\d.]+)', s).group(1))
            self._last = None
            return
        return super().execute(sql)


@override_settings(AP_RECONCILE_WRITER_ENABLED=True)
class AtomicWriteTests(TestCase):

    def push(self, fake, alloc):
        with mock.patch('config.sybase.get_sybase_connection', return_value=fake):
            return W.push_allocation(alloc, dry_run=False)

    def test_header_lock_timeout_rolls_back_the_insert(self):
        _, inv, pay, alloc = _setup()
        fake = _TxFake(fail_header=True)
        with self.assertRaises(W.ReconWriteError) as cm:
            self.push(fake, alloc)
        self.assertNotIsInstance(cm.exception, W.ReconWriteIntegrityError)   # clean rollback
        self.assertEqual(fake.rows, [])                                        # insert undone
        self.assertEqual(fake.paid, D('0'))
        alloc.refresh_from_db()
        self.assertEqual(alloc.origin, Allocation.ORIGIN_APPROVED)             # retry-able

    def test_dead_connection_rollback_is_proven_on_a_fresh_connection(self):
        _, inv, pay, alloc = _setup()
        fake = _TxFake(fail_header=True)
        fake.dead = False
        orig_rollback, orig_execute = fake.rollback, fake.execute

        def rollback():                      # HQ drops right as the transaction fails
            orig_rollback()
            fake.dead = True

        def execute(sql):
            if fake.dead:
                raise RuntimeError('JZ0C0: Connection is already closed')
            return orig_execute(sql)

        fake.rollback, fake.execute = rollback, execute
        calls = []

        def connect():
            calls.append(1)
            if len(calls) > 1:               # the fresh connection works
                fake.dead = False
            return fake

        with mock.patch('config.sybase.get_sybase_connection', side_effect=connect), \
                mock.patch('time.sleep'):
            with self.assertRaises(W.ReconWriteError) as cm:
                W.push_allocation(alloc, dry_run=False)
        self.assertNotIsInstance(cm.exception, W.ReconWriteIntegrityError)
        self.assertEqual(fake.rows, [])
        self.assertTrue(ReconAuditEvent.objects.filter(
            allocation=alloc, after_state__steps__contains=['rollback_verified_fresh_connection']).exists())

    def _partially_linked(self, ours=True):
        """Our earlier write linked this voucher to the invoice for only 300 of 840."""
        _, inv, pay, alloc = _setup()
        fake = _TxFake()
        fake.rows = [{'cheqsno': int(pay.cheqsno), 'paid': D('840'), 'now': D('300'), 'inv': True}]
        fake.paid = D('300')
        if ours:
            ReconAuditEvent.objects.create(action='allocation_written', allocation=alloc)
        return fake, alloc

    def test_existing_partial_link_is_topped_up_not_duplicated(self):
        fake, alloc = self._partially_linked()
        res = self.push(fake, alloc)
        self.assertEqual(res['topped_up'], '540')
        self.assertEqual(len(fake.rows), 1)                  # same row, raised
        self.assertEqual(fake.rows[0]['now'], D('840'))
        self.assertEqual(fake.paid, D('840'))                # header raised by the difference
        alloc.refresh_from_db()
        self.assertEqual(alloc.origin, Allocation.ORIGIN_WRITTEN)

    def test_native_partial_link_is_never_modified(self):
        fake, alloc = self._partially_linked(ours=False)
        with self.assertRaises(W.ReconWriteError):
            self.push(fake, alloc)
        self.assertEqual(fake.rows[0]['now'], D('300'))
        self.assertEqual(fake.paid, D('300'))

    def test_unverifiable_rollback_is_an_integrity_stop(self):
        _, inv, pay, alloc = _setup()
        fake = _TxFake(fail_header=True, broken_rollback=True)
        with self.assertRaises(W.ReconWriteIntegrityError):
            self.push(fake, alloc)

    def test_happy_path_still_commits(self):
        _, inv, pay, alloc = _setup()
        fake = _TxFake()
        self.assertTrue(self.push(fake, alloc)['written'])
        self.assertEqual(fake.paid, D('840'))


@override_settings(AP_RECONCILE_WRITER_ENABLED=True)
class AtomicReversalTests(TestCase):

    def written(self, fake):
        _, inv, pay, alloc = _setup()
        with mock.patch('config.sybase.get_sybase_connection', return_value=fake):
            W.push_allocation(alloc, dry_run=False)
        alloc.refresh_from_db()
        return alloc

    def test_reversal_header_failure_restores_the_row(self):
        fake = _TxFake()
        alloc = self.written(fake)
        fake.fail_header = True
        with mock.patch('config.sybase.get_sybase_connection', return_value=fake):
            with self.assertRaises(W.ReconWriteError):
                W.reverse_allocation(alloc)
        self.assertEqual(len(fake.rows), 1)          # DELETE rolled back — nothing half-landed
        self.assertEqual(fake.paid, D('840'))
        self.assertTrue(Allocation.objects.filter(pk=alloc.pk, origin='written').exists())

    def test_complete_half_reversal_only_when_proven(self):
        fake = _TxFake()
        alloc = self.written(fake)
        fake.rows = []                               # simulate: DELETE landed, header did not
        with mock.patch('config.sybase.get_sybase_connection', return_value=fake):
            res = W.complete_half_reversal(alloc, note='test')
        self.assertTrue(res['reversed'])
        self.assertEqual(fake.paid, D('0'))
        self.assertFalse(Allocation.objects.filter(pk=alloc.pk).exists())
        self.assertTrue(ReconAuditEvent.objects.filter(action='allocation_reversed',
                                                       before_state__half_landed=True).exists())

    def _half_written(self, *, failed_attempt=True):
        """Our INSERT landed, the header UPDATE never ran, local row still 'approved'."""
        _, inv, pay, alloc = _setup()
        fake = _TxFake()
        fake.rows = [{'cheqsno': int(pay.cheqsno), 'paid': D('840'), 'now': D('840'), 'inv': True}]
        if failed_attempt:
            ReconAuditEvent.objects.create(action='allocation_write_failed', allocation=alloc,
                                           after_state={'error': 'Read timed out'})
        return fake, alloc

    def test_complete_half_write_only_when_proven(self):
        fake, alloc = self._half_written()
        with mock.patch('config.sybase.get_sybase_connection', return_value=fake):
            res = W.complete_half_write(alloc)
        self.assertTrue(res['written'])
        self.assertEqual(fake.paid, D('840'))                 # header raised by exactly the amount
        self.assertEqual(len(fake.rows), 1)                   # no second INSERT
        alloc.refresh_from_db()
        self.assertEqual(alloc.origin, Allocation.ORIGIN_WRITTEN)
        self.assertTrue(ReconAuditEvent.objects.filter(action='allocation_written', allocation=alloc).exists())

    def test_complete_half_write_accepts_row_relabelled_softech_by_ingest(self):
        fake, alloc = self._half_written()
        Allocation.objects.filter(pk=alloc.pk).update(origin=Allocation.ORIGIN_SOFTECH)
        alloc.refresh_from_db()
        with mock.patch('config.sybase.get_sybase_connection', return_value=fake):
            self.assertTrue(W.complete_half_write(alloc)['written'])
        self.assertEqual(fake.paid, D('840'))

    def test_complete_half_write_refuses_a_confirmed_write(self):
        fake, alloc = self._half_written()
        ReconAuditEvent.objects.create(action='allocation_written', allocation=alloc)
        with mock.patch('config.sybase.get_sybase_connection', return_value=fake):
            with self.assertRaises(W.ReconWriteError):
                W.complete_half_write(alloc)
        self.assertEqual(fake.paid, D('0'))

    def test_complete_half_write_refuses_without_our_failed_attempt(self):
        fake, alloc = self._half_written(failed_attempt=False)
        with mock.patch('config.sybase.get_sybase_connection', return_value=fake):
            with self.assertRaises(W.ReconWriteError):
                W.complete_half_write(alloc)
        self.assertEqual(fake.paid, D('0'))

    def test_complete_half_write_refuses_when_header_already_covers_it(self):
        fake, alloc = self._half_written()
        fake.paid = D('840')                                  # header in sync — not half-landed
        with mock.patch('config.sybase.get_sybase_connection', return_value=fake):
            with self.assertRaises(W.ReconWriteError):
                W.complete_half_write(alloc)
        self.assertEqual(fake.paid, D('840'))

    def test_rechain_after_write_touches_only_our_links_on_written_invoices(self):
        fake = _TxFake()
        alloc = self.written(fake)                    # ours: has an allocation_written audit
        from apps.finance.models import APInvoice
        other = APInvoice.objects.create(party=alloc.invoice.party, branchcode='130', doccode='10',
                                         docnumber='99999', docdate=alloc.invoice.docdate,
                                         doc_value=D('5'), party_type='supplier')
        native = Allocation.objects.create(payment=alloc.payment, invoice=other,
                                           amount=D('5'), origin=Allocation.ORIGIN_SOFTECH)
        seen = []
        with mock.patch.object(W, 'fix_due_before',
                               side_effect=lambda inv, allocs, **k: seen.append((inv.id, [a.id for a in allocs]))
                               or {'changes': [{'closes': True}]}):
            res = W.rechain_after_write({alloc.invoice_id, native.invoice_id}, conn=fake)
        self.assertEqual(seen, [(alloc.invoice_id, [alloc.id])])     # native invoice untouched
        self.assertEqual((res['invoices'], res['now_closed']), (1, 1))

    def test_complete_half_reversal_refuses_when_row_present(self):
        fake = _TxFake()
        alloc = self.written(fake)
        with mock.patch('config.sybase.get_sybase_connection', return_value=fake):
            with self.assertRaises(W.ReconWriteError):
                W.complete_half_reversal(alloc)
        self.assertEqual(fake.paid, D('840'))
