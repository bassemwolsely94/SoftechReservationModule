"""
apps/tests/test_reconciliation_writer.py

Phase-G — gated A/P allocation writer (apps/finance/recon_writer.py). The flag is
OFF, so these exercise build_plan + the dry-run gate + validations WITHOUT touching
SOFTECH. Confirms the reconstruction writes only chequestrans + stktransm (never a
cheques row) and is idempotency-guarded.
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase, override_settings

from apps.finance import recon_writer
from apps.finance.models import ReconParty, APInvoice, Payment, Allocation


def _setup(amount='840', doc_value='840', doc_value_pay='0'):
    party = ReconParty.objects.create(party_type='supplier', softech_personcode='4471', name='مورد')
    inv = APInvoice.objects.create(
        party=party, branchcode='130', doccode='10', docnumber='12362',
        docdate=date(2026, 9, 17), doc_value=Decimal(doc_value),
        doc_value_pay=Decimal(doc_value_pay), party_type='supplier',
    )
    pay = Payment.objects.create(
        party=party, branchcode='100', cheqsno=51684, direction='out',
        party_type='supplier', voucher_date=date(2026, 9, 20), amount=Decimal(amount),
        note='مورد 12362', usercode='1509', is_unallocated=True,
    )
    alloc = Allocation.objects.create(
        payment=pay, invoice=inv, amount=Decimal(amount),
        origin=Allocation.ORIGIN_APPROVED,
    )
    return party, inv, pay, alloc


class BuildPlanTests(TestCase):

    def test_plan_shape_and_statements(self):
        _, inv, pay, alloc = _setup()
        plan = recon_writer.build_plan(alloc)
        labels = [s['label'] for s in plan['statements']]
        # chequestrans insert precedes stktransm update (idempotency ordering)
        self.assertIn('chequestrans_insert', labels)
        self.assertIn('stktransm_update', labels)
        self.assertLess(labels.index('chequestrans_insert'), labels.index('stktransm_update'))
        # NEVER a cheques insert
        self.assertNotIn('cheques', ' '.join(s['sql'].lower() for s in plan['statements']).replace('chequestrans', ''))

    def test_chequestrans_values(self):
        _, inv, pay, alloc = _setup(amount='840')
        plan = recon_writer.build_plan(alloc)
        ct = next(s['sql'] for s in plan['statements'] if s['label'] == 'chequestrans_insert')
        self.assertIn('INSERT INTO SOFTECHDB9.dbo.chequestrans', ct)
        self.assertIn('51684', ct)                 # existing voucher cheqsno
        self.assertIn("'130'", ct)                 # invoice branch
        self.assertIn('12362', ct)                 # docnumber
        self.assertIn('9-17-2026 0:0:0.000', ct)   # SOFTECH date format
        self.assertIn("'100'", ct)                 # cheqbranchcode = voucher branch

    def test_full_payment_sets_status_90(self):
        _, inv, pay, alloc = _setup(amount='840', doc_value='840', doc_value_pay='0')
        plan = recon_writer.build_plan(alloc)
        self.assertEqual(plan['projected_fatcurrentstatus'], '90')
        upd = next(s['sql'] for s in plan['statements'] if s['label'] == 'stktransm_update')
        self.assertIn("fatcurrentstatus='90'", upd)
        self.assertIn('docvaluepay=840', upd)

    def test_partial_payment_sets_status_15(self):
        _, inv, pay, alloc = _setup(amount='300', doc_value='840', doc_value_pay='0')
        plan = recon_writer.build_plan(alloc)
        self.assertEqual(plan['projected_fatcurrentstatus'], '15')

    def test_incremental_paid_added(self):
        # invoice already has 500 paid; allocating 340 → 840 total → full
        _, inv, pay, alloc = _setup(amount='340', doc_value='840', doc_value_pay='500')
        plan = recon_writer.build_plan(alloc)
        self.assertEqual(plan['projected_docvaluepay'], '840')
        self.assertEqual(plan['projected_fatcurrentstatus'], '90')

    def test_zero_amount_rejected(self):
        _, inv, pay, alloc = _setup(amount='0')
        with self.assertRaises(recon_writer.ReconWriteError):
            recon_writer.build_plan(alloc)


class GateTests(TestCase):

    def test_dry_run_by_default_writes_nothing(self):
        _, inv, pay, alloc = _setup()
        res = recon_writer.push_allocation(alloc)   # dry_run defaults True
        self.assertTrue(res['dry_run'])
        self.assertFalse(res['written'])
        self.assertFalse(res['enabled'])            # flag off
        self.assertIn('plan', res)
        alloc.refresh_from_db()
        self.assertEqual(alloc.origin, Allocation.ORIGIN_APPROVED)   # unchanged

    @override_settings(AP_RECONCILE_WRITER_ENABLED=False)
    def test_flag_off_forces_dry_run_even_if_commit(self):
        _, inv, pay, alloc = _setup()
        res = recon_writer.push_allocation(alloc, dry_run=False)   # flag off → still dry
        self.assertTrue(res['dry_run'])
        self.assertFalse(res['written'])

    def test_only_approved_writable(self):
        _, inv, pay, alloc = _setup()
        alloc.origin = Allocation.ORIGIN_SOFTECH
        alloc.save()
        with self.assertRaises(recon_writer.ReconWriteError):
            recon_writer.push_allocation(alloc)

    def test_patientdata_gated_off_by_default(self):
        _, inv, pay, alloc = _setup()
        plan = recon_writer.build_plan(alloc)
        self.assertFalse(plan['patientdata_update_enabled'])
        self.assertNotIn('patientdata', ' '.join(s['sql'].lower() for s in plan['statements']))

    @override_settings(AP_RECONCILE_UPDATE_PATIENTDATA=True)
    def test_patientdata_included_when_enabled(self):
        _, inv, pay, alloc = _setup()
        plan = recon_writer.build_plan(alloc)
        self.assertTrue(plan['patientdata_update_enabled'])
        self.assertTrue(any('patientdata' in s['sql'].lower() for s in plan['statements']))


# ── LIVE PATH against a simulated SOFTECH (no real connection) ────────────────
import re
from unittest import mock


class _FakeSoftech:
    """Minimal in-memory stand-in for the 3 tables the live path touches."""

    def __init__(self, docvalue='840', docvaluepay='0', cheqvalue='840', bcrate='1',
                 existing=None, header_frozen=False):
        self.docvalue, self.paid = Decimal(docvalue), Decimal(docvaluepay)
        self.cheqvalue, self.bcrate = Decimal(cheqvalue), Decimal(bcrate)
        self.rows = list(existing or [])   # dicts: cheqsno, now, paid, inv(bool)
        self.header_frozen = header_frozen  # simulate an UPDATE that doesn't land
        self._last = None

    # DB-API cursor/connection surface
    def cursor(self):
        return self

    def close(self):
        pass

    def fetchone(self):
        return self._last

    def execute(self, sql):
        s = ' '.join(sql.split()).replace(' AT ISOLATION 0', '')
        if s.startswith('SELECT COUNT(*) FROM') and 'chequestrans' in s:
            self._last = (sum(1 for r in self.rows if r['inv']),)
        elif s.startswith('SELECT SUM(docvaluepaynow)') and 'WHERE branchcode=' in s:
            self._last = (sum((r['now'] for r in self.rows if r['inv']), Decimal('0')),)
        elif s.startswith('SELECT SUM(CASE WHEN doccode') and 'WHERE cheqsno=' in s:
            # signed voucher usage — the fake only holds purchase rows (+)
            self._last = (sum((r['now'] for r in self.rows), Decimal('0')),)
        elif s.startswith('SELECT SUM(docvaluepaynow)') and 'WHERE cheqsno=' in s:
            self._last = (sum((r['now'] for r in self.rows), Decimal('0')),)
        elif s.startswith('SELECT docvalue, docvaluepay'):
            self._last = (self.docvalue, self.paid, 'EGP', self.bcrate)
        elif s.startswith('SELECT docvaluepay FROM'):
            self._last = (self.paid,)
        elif s.startswith('SELECT cheqvalue FROM'):
            self._last = (self.cheqvalue,)
        elif s.startswith('SELECT docvaluepaynow FROM'):
            hit = [r for r in self.rows if r['inv']]
            self._last = (hit[-1]['now'],) if hit else None
        elif s.startswith('INSERT INTO') and 'chequestrans' in s:
            vals = re.search(r'VALUES \((.*)\)', s).group(1).split(', ')
            self.rows.append({'cheqsno': int(vals[0]), 'paid': Decimal(vals[6]),
                              'now': Decimal(vals[7]), 'inv': True})
            self._last = None
        elif s.startswith('DELETE FROM') and 'chequestrans' in s:
            self.rows = [r for r in self.rows if not r['inv']]
            self._last = None
        elif s.startswith('UPDATE') and 'stktransm' in s:
            if not self.header_frozen:
                self.paid = Decimal(re.search(r'docvaluepay=([\d.]+)', s).group(1))
            self._last = None
        else:
            raise AssertionError(f'unexpected SQL: {s}')


@override_settings(AP_RECONCILE_WRITER_ENABLED=True)
class LivePathTests(TestCase):

    def _push(self, fake, alloc):
        with mock.patch('config.sybase.get_sybase_connection', return_value=fake):
            return recon_writer.push_allocation(alloc, dry_run=False)

    def test_full_settlement_writes_and_marks_written(self):
        _, inv, pay, alloc = _setup(amount='840', doc_value='840')
        fake = _FakeSoftech()
        res = self._push(fake, alloc)
        self.assertTrue(res['written'])
        self.assertEqual(res['fatcurrentstatus'], '90')
        self.assertEqual(fake.paid, Decimal('840'))
        self.assertEqual(fake.rows[0]['paid'], Decimal('840'))
        alloc.refresh_from_db()
        self.assertEqual(alloc.origin, Allocation.ORIGIN_WRITTEN)

    def test_docvaluepaid_is_amount_due_before_this_voucher(self):
        # invoice 840, already 300 paid live; this voucher pays 200 → «مبلغ مستحق» = 540
        _, inv, pay, alloc = _setup(amount='200', doc_value='840', doc_value_pay='300')
        fake = _FakeSoftech(docvalue='840', docvaluepay='300', cheqvalue='200')
        res = self._push(fake, alloc)
        self.assertEqual(fake.rows[-1]['now'], Decimal('200'))
        self.assertEqual(fake.rows[-1]['paid'], Decimal('540'))   # owed BEFORE (not 500)
        self.assertEqual(res['fatcurrentstatus'], '15')           # still partial
        self.assertEqual(fake.paid, Decimal('500'))

    def test_due_chain_owner_case_10653(self):
        # 13,750 invoice; native 9,000 (45015) came first, OUR 4,750 (44995) clears it
        d = recon_writer.due_chain(Decimal('13750'), Decimal('13750'), [(('2026-07-29', 44995), Decimal('4750'))])
        self.assertEqual(d, [Decimal('4750.00')])                 # == paynow → «مغلق»

    def test_due_chain_is_chronological_and_latest_closes(self):
        # owner case 10746 done by us: 250 (earlier) then 8,000 (later) → 8,250 / 8,000
        d = recon_writer.due_chain(Decimal('8250'), Decimal('8250'),
                        [(('2026-08-06', 45154), Decimal('8000')), (('2026-08-06', 45151), Decimal('250'))])
        self.assertEqual(d, [Decimal('8250.00'), Decimal('8000.00')])

    def test_due_chain_refuses_inconsistent_numbers(self):
        with self.assertRaises(recon_writer.ReconWriteError):
            recon_writer.due_chain(Decimal('100'), Decimal('50'), [((1,), Decimal('80'))])

    def test_closing_voucher_has_due_equal_to_paynow(self):
        # the last 540 clears the invoice → docvaluepaid == paynow → SOFTECH shows «مغلق»
        _, inv, pay, alloc = _setup(amount='540', doc_value='840', doc_value_pay='300')
        fake = _FakeSoftech(docvalue='840', docvaluepay='300', cheqvalue='540')
        res = self._push(fake, alloc)
        self.assertEqual(fake.rows[-1]['paid'], fake.rows[-1]['now'])
        self.assertEqual(res['fatcurrentstatus'], '90')

    def test_live_overpay_blocked_nothing_written(self):
        _, inv, pay, alloc = _setup(amount='840', doc_value='840')
        fake = _FakeSoftech(docvaluepay='100')     # live already partly paid elsewhere
        with self.assertRaises(recon_writer.ReconWriteError):
            self._push(fake, alloc)
        self.assertEqual(fake.rows, [])
        self.assertEqual(fake.paid, Decimal('100'))

    def test_voucher_overallocation_blocked(self):
        _, inv, pay, alloc = _setup(amount='840', doc_value='840')
        # voucher 840 already has 500 allocated to some OTHER invoice
        fake = _FakeSoftech(existing=[{'cheqsno': 51684, 'now': Decimal('500'),
                                       'paid': Decimal('500'), 'inv': False}])
        with self.assertRaises(recon_writer.ReconWriteError):
            self._push(fake, alloc)
        self.assertEqual(len(fake.rows), 1)        # nothing inserted

    def test_foreign_currency_blocked(self):
        _, inv, pay, alloc = _setup()
        fake = _FakeSoftech(bcrate='48.5')
        with self.assertRaises(recon_writer.ReconWriteError):
            self._push(fake, alloc)
        self.assertEqual(fake.rows, [])

    def test_idempotent_retry_skips_writes(self):
        _, inv, pay, alloc = _setup()
        fake = _FakeSoftech(docvaluepay='840', existing=[
            {'cheqsno': 51684, 'now': Decimal('840'), 'paid': Decimal('840'), 'inv': True}])
        res = self._push(fake, alloc)
        self.assertTrue(res['already_present'])
        self.assertEqual(len(fake.rows), 1)        # no second insert

    def test_half_landed_header_is_surfaced_not_marked(self):
        _, inv, pay, alloc = _setup()
        # allocation row exists but header never moved (earlier half-landed write)
        fake = _FakeSoftech(docvaluepay='0', existing=[
            {'cheqsno': 51684, 'now': Decimal('840'), 'paid': Decimal('840'), 'inv': True}])
        with self.assertRaises(recon_writer.ReconWriteError):
            self._push(fake, alloc)
        alloc.refresh_from_db()
        self.assertEqual(alloc.origin, Allocation.ORIGIN_APPROVED)

    def test_header_update_not_landing_stops(self):
        _, inv, pay, alloc = _setup()
        fake = _FakeSoftech(header_frozen=True)
        with self.assertRaises(recon_writer.ReconWriteError):
            self._push(fake, alloc)
        alloc.refresh_from_db()
        self.assertEqual(alloc.origin, Allocation.ORIGIN_APPROVED)   # never marked written

    def test_every_live_interaction_is_audited(self):
        from apps.finance.models import ReconAuditEvent
        _, inv, pay, alloc = _setup()
        self._push(_FakeSoftech(), alloc)
        self.assertTrue(ReconAuditEvent.objects.filter(
            action='allocation_written', allocation=alloc).exists())
        _, inv2, pay2, alloc2 = _setup_other()
        with self.assertRaises(recon_writer.ReconWriteError):
            self._push(_FakeSoftech(docvaluepay='100'), alloc2)
        ev = ReconAuditEvent.objects.get(action='allocation_write_failed', allocation=alloc2)
        self.assertIn('over-pay', ev.after_state['error'])


def _setup_other():
    party = ReconParty.objects.create(party_type='supplier', softech_personcode='5000', name='مورد 2')
    inv = APInvoice.objects.create(
        party=party, branchcode='150', doccode='10', docnumber='777',
        docdate=date(2026, 9, 1), doc_value=Decimal('840'),
        doc_value_pay=Decimal('0'), party_type='supplier')
    pay = Payment.objects.create(
        party=party, branchcode='150', cheqsno=777, direction='out', party_type='supplier',
        voucher_date=date(2026, 9, 2), amount=Decimal('840'), note='777', is_unallocated=True)
    alloc = Allocation.objects.create(payment=pay, invoice=inv, amount=Decimal('840'),
                                      origin=Allocation.ORIGIN_APPROVED)
    return party, inv, pay, alloc


@override_settings(AP_RECONCILE_WRITER_ENABLED=True)
class ReversalTests(TestCase):

    def _written(self):
        _, inv, pay, alloc = _setup()
        fake = _FakeSoftech()
        with mock.patch('config.sybase.get_sybase_connection', return_value=fake):
            recon_writer.push_allocation(alloc, dry_run=False)
        alloc.refresh_from_db()
        return fake, alloc

    def test_reverse_restores_softech_and_rejects_candidate(self):
        from apps.finance.models import ReconAuditEvent
        fake, alloc = self._written()
        self.assertEqual(fake.paid, Decimal('840'))
        with mock.patch('config.sybase.get_sybase_connection', return_value=fake):
            res = recon_writer.reverse_allocation(alloc, note='خطأ')
        self.assertTrue(res['reversed'])
        self.assertEqual(fake.paid, Decimal('0'))
        self.assertEqual(res['fatcurrentstatus'], '15')
        self.assertEqual(fake.rows, [])
        self.assertFalse(Allocation.objects.filter(pk=alloc.pk).exists())
        self.assertTrue(ReconAuditEvent.objects.filter(action='allocation_reversed').exists())

    def test_refuses_native_softech_allocation(self):
        _, inv, pay, alloc = _setup()
        alloc.origin = Allocation.ORIGIN_SOFTECH
        alloc.save()
        with self.assertRaises(recon_writer.ReconWriteError):
            recon_writer.reverse_allocation(alloc)

    def test_refuses_written_without_our_audit_trail(self):
        _, inv, pay, alloc = _setup()
        alloc.origin = Allocation.ORIGIN_WRITTEN     # "written" but not by us
        alloc.save()
        with self.assertRaises(recon_writer.ReconWriteError):
            recon_writer.reverse_allocation(alloc)

    def test_candidate_marked_written_on_write(self):
        from apps.finance.models import MatchCandidate
        _, inv, pay, alloc = _setup()
        cand = MatchCandidate.objects.create(party=inv.party, invoice=inv, payment=pay,
                                             proposed_amount=Decimal('840'),
                                             status=MatchCandidate.STATUS_APPROVED)
        alloc.candidate = cand
        alloc.save()
        with mock.patch('config.sybase.get_sybase_connection', return_value=_FakeSoftech()):
            recon_writer.push_allocation(alloc, dry_run=False)
        cand.refresh_from_db()
        self.assertEqual(cand.status, MatchCandidate.STATUS_WRITTEN)
