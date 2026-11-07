"""
Round 2 / R2 — insurance and replacement money correctness (docs/security/2026-11-05-full-project-test-plan.md §7 R2).

Insurance — sources:
  * apps/insurance/reprice.py docstring (live goldens 2026-09-13, doccode 115), doc 21
    (21_SOFTECH_INSURANCE_REPRICE_WRITEBACK.md): BETADINE 85 → 95, VAT 14%, contract 17% →
    itemsaleprice_tax 83.3333, transprice 78.85, itemsalestax 9.6833; header re-footed by the edited
    lines' deltas only (reprice_service._compute).
  * reprice_service.apply_plan / apply_reprice: each receipt of a plan is written with the plan's prices
    to BOTH nodes (HQ + branch) — the price SOFTECH ends up holding is the plan's new price.
  * importer.recalculate_claim_final_totals + classifier.powerquery_totals_from_splits: the claim's
    final_* are rebuilt from the included prescriptions (exclusions out); net = Σ split·(1−rate).
  * importer.find_duplicate_receipt + memory "Motalba Membership & Naming": a receipt is ACTIVE in at
    most one overlapping-period, non-rejected claim; an excluded copy does not block.
Replacement — sources: apps/replacement/models.py (ck_replacement_payout_positive,
  ck_replacement_reversal_positive, append-only EntitlementLedgerEntry whose reversal = −original) and
  apps/replacement/ledger.py (balance = Σ amount; reverse() appends the compensating entry).
SOFTECH is mocked throughout (MagicMock connections); nothing reaches a node.
"""
from datetime import date
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase, override_settings

from apps.insurance import models as m
from apps.insurance import reprice_service as rs
from apps.insurance.classifier import powerquery_totals_from_splits
from apps.insurance.importer import find_duplicate_receipt, recalculate_claim_final_totals
from apps.insurance.reprice import recompute_line
from apps.replacement import ledger as L
from apps.replacement.models import (CashPayout, EntitlementLedgerEntry as E, ReplacementCase as RC,
                                     ReversalRequest)

from .factories import make_branch
from .test_softech_reprice_guard import RECEIPTS, _fake_read

D = Decimal
REASON = 'سعر متفق عليه مع الشركة'

# (label, new_price, qty, custdiscp, vat) → (itemsaleprice_tax, transprice, itemsalestax, transprice_total)
REPRICE = [
    ('golden BETADINE 95, 17%, VAT 14', '95', '1', '17', '14', '83.3333', '78.8500', '9.6833', '78.85'),
    ('BETADINE ×3',                     '95', '3', '17', '14', '83.3333', '78.8500', '9.6833', '236.55'),
    ('untaxed contract 25% ×2',         '240', '2', '25', '0', '240.0000', '180.0000', '0.0000', '360.00'),
    ('pack fraction 0.5, 10%',          '33.33', '0.5', '10', '0', '33.3300', '29.9970', '0.0000', '15.00'),
]


class RecomputeLineTests(SimpleTestCase):
    def test_reprice_table(self):
        for label, p, q, cd, vat, ex, tp, tax, total in REPRICE:
            with self.subTest(label):
                r = recompute_line(new_price=p, transqty=q, custdiscp=cd, vat_rate=vat)
                self.assertEqual(r['itemsaleprice'], D(p).quantize(D('0.01')))
                self.assertEqual((r['itemsaleprice_tax'], r['transprice'], r['itemsalestax'], r['transprice_total']),
                                 (D(ex), D(tp), D(tax), D(total)))

    def test_compute_reprices_only_the_edited_lines_and_refoots_by_delta(self):
        lines, header = RECEIPTS[('930593', '160')]
        new_lines, h, _ = rs._compute(lines, header, {'80052': D('210')})
        by = {l['itemcode']: l for l in new_lines}
        self.assertEqual(by['80052']['itemsaleprice'], D('210.00'))
        self.assertIs(by['124793'], [l for l in lines if l['itemcode'] == '124793'][0])     # untouched
        old = [l for l in lines if l['itemcode'] == '80052'][0]
        self.assertEqual(h['docvalue'], (header['docvalue'] + by['80052']['transprice_total']
                                         - old['transprice_total']).quantize(D('0.01')))
        self.assertEqual(h['docvalue1'], (header['docvalue1'] + D('10')).quantize(D('0.01')))


@override_settings(INSURANCE_SOFTECH_WRITE_ENABLED=True, WRITER_INSTANCE=True)
class PlanWritesThePlanPriceTests(TestCase):
    """After applying a plan, every receipt line SOFTECH holds (HQ and branch) carries the plan's price."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username='r2ins', password='x', is_staff=True,
                                                         is_superuser=True)
        client = m.InsuranceClient.objects.create(name='جنوب')
        sub = m.InsuranceSubClient.objects.create(client=client, name='العاملين')
        self.claim = m.InsuranceClaim.objects.create(claim_number='MT-R2-1', subclient=sub,
                                                     period_from=date(2026, 10, 1), period_to=date(2026, 10, 31))
        self.prices = {'111062': '240', '80052': '210', '124793': '770'}
        for (d, b), (lines, _h) in RECEIPTS.items():
            rx = m.InsuranceClaimPrescription.objects.create(claim=self.claim, softech_docnumber=d,
                                                             softech_branchcode=b, patient_name='مريض',
                                                             softech_docdate=date(2026, 10, 3))
            for ln in lines:
                m.InsuranceClaimLine.objects.create(prescription=rx, softech_itemcode=ln['itemcode'],
                                                    item_name='صنف', unit_price=self.prices[ln['itemcode']])
        self.hq, self.br = mock.MagicMock(), mock.MagicMock()
        self.hq.cursor.return_value.fetchone.return_value = None          # receipt not in a motalba yet
        for p in (mock.patch('apps.insurance.importer._get_connection'),
                  mock.patch.object(rs, '_read_receipt', side_effect=_fake_read)):
            p.start()
            self.addCleanup(p.stop)

    def _written_prices(self, conn):
        out = {}
        for c in conn.cursor.return_value.execute.call_args_list:
            sql, params = str(c.args[0]), c.args[1] if len(c.args) > 1 else []
            if 'stktrans SET itemsaleprice=?' in sql:
                value, docno, _b, _dc, code, _flag = params
                out[(str(docno), code)] = D(str(value))
        return out

    def test_every_receipt_is_written_with_the_plan_price_on_both_nodes(self):
        receipts = [{'docno': '931120', 'branch': '160', 'prices': {'111062': '240'}},
                    {'docno': '930593', 'branch': '160', 'prices': {'80052': '210', '124793': '770'}}]
        plan = rs.preview_plan(self.claim, receipts, user=self.user, source='item')
        self.assertFalse(plan.blocked, plan.preview)
        with mock.patch.object(rs, 'build_preview', return_value={
                'branch_consistency': {'reachable': True}, 'cust_branch_code': '4227', 'net_delta': '0'}), \
             mock.patch.object(rs, '_hq_conn', return_value=self.hq), \
             mock.patch.object(rs, '_open_branch', return_value=self.br):
            res = rs.apply_plan(plan, user=self.user, confirm_count=str(plan.receipt_count), reason=REASON)
        self.assertEqual((res['applied'], res['failed']), (2, 0), res)
        want = {(r['docno'], code): D(price) for r in receipts for code, price in r['prices'].items()}
        self.assertEqual(self._written_prices(self.hq), want)
        self.assertEqual(self._written_prices(self.br), want)
        # the audited after-values agree with what was written
        for e in m.SoftechRepriceEdit.objects.filter(field='itemsaleprice'):
            self.assertEqual(D(e.after), want[(e.row_key['docnumber'], e.row_key['itemcode'])])


class ClaimTotalsTests(TestCase):
    def setUp(self):
        client = m.InsuranceClient.objects.create(name='ش')
        sub = m.InsuranceSubClient.objects.create(client=client, name='ف')
        self.claim = m.InsuranceClaim.objects.create(
            claim_number='MT-R2-T', subclient=sub, period_from=date(2026, 10, 1), period_to=date(2026, 10, 31),
            applied_local_disc_pct=D('15'), applied_imported_disc_pct=D('10'), applied_tarsia_disc_pct=D('0'))
        self._n = 0

    def rx(self, lb, ib, tb, excluded=False):
        """A prescription whose stored figures follow the Power-Query formula at the claim's rates."""
        self._n += 1
        t = powerquery_totals_from_splits(D(lb), D(ib), D(tb), D('15'), D('10'), D('0'))
        rx = m.InsuranceClaimPrescription.objects.create(
            claim=self.claim, softech_docnumber=f'9{self._n:05d}', softech_branchcode='130',
            softech_docdate=date(2026, 10, 5), local_before=t['local_before'], imported_before=t['imported_before'],
            tarsia_before=t['tarsia_before'], gross_before=t['gross_before'], total_discount=t['total_discount'],
            net_after=t['net_after'])
        if excluded:
            m.InsuranceClaimExclusion.objects.create(prescription=rx, reason='R2')
        return rx

    def included(self):
        return [r for r in self.claim.prescriptions.all() if not hasattr(r, 'exclusion')]

    def test_claim_totals_equal_the_sum_of_included_prescriptions(self):
        for s in (('100.00', '0', '0'), ('20.00', '80.00', '0'), ('0', '0', '45.50'), ('60.00', '40.00', '0')):
            self.rx(*s)
        self.rx('999.00', '0', '0', excluded=True)
        recalculate_claim_final_totals(self.claim)
        self.claim.refresh_from_db()
        rows = self.included()
        self.assertEqual(self.claim.final_rx_count, 4)
        self.assertEqual(self.claim.final_gross_before, sum((r.gross_before for r in rows), D('0')))
        self.assertEqual(self.claim.final_net_after, sum((r.net_after for r in rows), D('0')))
        self.assertEqual(self.claim.final_total_discount, sum((r.total_discount for r in rows), D('0')))
        self.assertEqual(self.claim.final_gross_before - self.claim.final_total_discount, self.claim.final_net_after)

    def test_a_net_override_reaches_the_claim_total(self):
        # M-3 (owner, 2026-11-05): an adjustment's net_override (تجاوز مباشر) is the agreed net for that
        # prescription, in the claim total and in the invoice export alike.
        a = self.rx('100.00', '0', '0')                                       # net 85.00
        b = self.rx('200.00', '0', '0')                                       # net 170.00
        m.InsuranceClaimAdjustment.objects.create(prescription=b, net_override=D('150.00'), reason='R2')
        recalculate_claim_final_totals(self.claim)
        self.claim.refresh_from_db()
        self.assertEqual(self.claim.final_net_after, a.net_after + D('150.00'))
        self.assertEqual(self.claim.final_gross_before - self.claim.final_total_discount, self.claim.final_net_after)
        # the invoice export agrees, at the cover total and in the row's own day subtotal
        from apps.insurance.invoice_builder import build_invoice_dataset
        data = build_invoice_dataset(self.claim)
        self.assertEqual(D(str(data['claim_totals']['net_after'])), self.claim.final_net_after)
        self.assertEqual(D(str(data['claim_totals']['total_discount'])), self.claim.final_total_discount)
        ct = data['claim_totals']
        cats = sum(D(str(ct[k])) for k in ('local_discount', 'imported_discount', 'tarsia_discount'))
        self.assertEqual(cats, D(str(ct['total_discount'])))
        day_nets = sum(D(str(d['day_totals']['net_after'])) for d in data['days'])
        self.assertEqual(day_nets, self.claim.final_net_after)
        # the cover page's category rows add up to its total too
        cv = data['cover']
        self.assertEqual(D(str(cv['net_after'])), self.claim.final_net_after)
        self.assertEqual(sum(D(str(cv[k])) for k in ('local_net', 'imported_net', 'tarsia_net')),
                         self.claim.final_net_after)

    def test_claim_net_keeps_the_power_query_formula_over_the_summed_splits(self):
        # M-4, owner-accepted 2026-11-05 ("keep current method"): the claim net is the Power-Query formula
        # over the summed splits, rounded once, to match finance's workbook. It can differ by a few piasters
        # from Σ the printed row nets. Three rows of 10.05 local at 15%: rows 8.54 each = 25.62; claim 25.63.
        for _ in range(3):
            self.rx('10.05', '0', '0')
        recalculate_claim_final_totals(self.claim)
        self.claim.refresh_from_db()
        self.assertEqual(sum((r.net_after for r in self.included()), D('0')), D('25.62'))
        self.assertEqual(self.claim.final_net_after, D('25.63'))
        self.assertEqual(self.claim.final_net_after,
                         powerquery_totals_from_splits(D('30.15'), D('0'), D('0'),
                                                       D('15'), D('10'), D('0'))['net_after'])


class OneActiveClaimPerReceiptTests(TestCase):
    def setUp(self):
        client = m.InsuranceClient.objects.create(name='ق')
        sub = m.InsuranceSubClient.objects.create(client=client, name='ف')
        mk = lambda n, f, t, **kw: m.InsuranceClaim.objects.create(  # noqa: E731
            claim_number=n, subclient=sub, period_from=f, period_to=t, **kw)
        self.a = mk('MT-A', date(2026, 10, 1), date(2026, 10, 31))
        self.b = mk('MT-B', date(2026, 10, 1), date(2026, 10, 31))
        self.nov = mk('MT-NOV', date(2026, 11, 1), date(2026, 11, 30))
        self.rx = m.InsuranceClaimPrescription.objects.create(claim=self.a, softech_docnumber='777001',
                                                              softech_branchcode='130',
                                                              softech_docdate=date(2026, 10, 7))

    def test_a_receipt_active_in_one_claim_blocks_every_overlapping_claim(self):
        hits = find_duplicate_receipt(self.b, '777001', '130')
        self.assertEqual([h['claim_id'] for h in hits], [self.a.pk])
        self.assertEqual(find_duplicate_receipt(self.a, '777001', '130'), [])        # its own claim
        self.assertEqual(find_duplicate_receipt(self.nov, '777001', '130'), [])      # another month

    def test_an_excluded_or_dead_copy_does_not_block(self):
        m.InsuranceClaimExclusion.objects.create(prescription=self.rx, reason='moved')
        self.assertEqual(find_duplicate_receipt(self.b, '777001', '130'), [])
        self.rx.exclusion.delete()
        for dead in (m.InsuranceClaim.STATUS_REJECTED, m.InsuranceClaim.STATUS_CANCELLED):
            m.InsuranceClaim.objects.filter(pk=self.a.pk).update(status=dead)
            with self.subTest(dead):
                self.assertEqual(find_duplicate_receipt(self.b, '777001', '130'), [])


# ── replacement ──────────────────────────────────────────────────────────────
class _Case(TestCase):
    def setUp(self):
        self.branch = make_branch()
        self.case = RC.objects.create(number='R2-1', source_type=RC.SOURCE_INSURANCE_RX, status=RC.STATUS_DRAFT,
                                      branch=self.branch, branchcode=self.branch.softech_branch_id,
                                      entitlement=D('1300.00'), purchase_date=date(2026, 10, 5))


class PositiveAmountConstraintTests(_Case):
    def test_payout_and_reversal_amounts_must_be_positive(self):
        for amount in (D('0'), D('0.00'), D('-0.01'), D('-600')):
            with self.subTest(amount=amount):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    CashPayout.objects.create(case=self.case, amount=amount)
                with self.assertRaises(IntegrityError), transaction.atomic():
                    ReversalRequest.objects.create(case=self.case, kind='other', reason='R2', amount=amount)
        CashPayout.objects.create(case=self.case, amount=D('0.01'))
        ReversalRequest.objects.create(case=self.case, kind='other', reason='R2', amount=D('0.01'))


class LedgerReversalNetsToZeroTests(_Case):
    # (entry type, signed amount) — credits positive, debits negative (EntitlementLedgerEntry.clean)
    ENTRIES = [(E.TYPE_CREATED, '1300.00'), (E.TYPE_CASH, '-600.00'), (E.TYPE_PRODUCT, '-250.75'),
               (E.TYPE_UNCLASSIFIED, '-0.01'), (E.TYPE_POS_RETURN, '99.99')]

    def test_each_entry_plus_its_reversal_is_zero(self):
        for t, amt in self.ENTRIES:
            with self.subTest(t):
                e = L.ensure(self.case, t, D(amt))
                r = L.reverse(e, note='R2')
                self.assertEqual(e.amount + r.amount, D('0.00'))
                self.assertEqual(r.reverses_id, e.pk)
        self.assertEqual(L.balance(self.case), D('0.00'))
        self.assertTrue(all(v == D('0.00') for v in L.totals(self.case).values()), L.totals(self.case))

    def test_reversing_the_cash_payout_restores_the_balance(self):
        L.ensure(self.case, E.TYPE_CREATED, D('1300.00'))
        cash = L.ensure(self.case, E.TYPE_CASH, D('-600.00'))
        self.assertEqual(L.balance(self.case), D('700.00'))
        L.reverse(cash, note='voucher reversed')
        self.assertEqual(L.balance(self.case), D('1300.00'))
        self.assertEqual(L.totals(self.case)['cash'], D('0.00'))

    def test_an_entry_is_reversed_at_most_once_and_never_edited(self):
        e = L.ensure(self.case, E.TYPE_CASH, D('-600.00'))
        L.reverse(e)
        with self.assertRaises(IntegrityError), transaction.atomic():
            L.reverse(e)                                                       # reverses is one-to-one
        with self.assertRaises(ValidationError):
            E.objects.create(case=self.case, entry_type=E.TYPE_REVERSAL, amount=D('-1'), reverses=None)
        with self.assertRaises(ValidationError):
            E.objects.filter(pk=e.pk).update(amount=D('-1'))
        self.assertEqual(L.balance(self.case), D('0.00'))
