"""
D-15 (owner, 2026-11-19) — the insurance cover page matches the claim totals.

Source: docs/full-project-audit/04_BACKEND_AUDIT.md BE-16 + 14_DECISION_REGISTER.md D-15.
The cover's category rows (محلى / مستورد / الترسية) used to be float ``round(before × pct / 100, 2)``:
binary error + banker's rounding, so the three rows could miss the claim's Decimal total discount by
piasters. Now (apps/insurance/invoice_builder.cover_category_discounts):
  * each category discount is Decimal, rounded HALF-UP to 0.01 per category;
  * the cover TOTAL is the claim's own figure (claim.final_* from recalculate_claim_final_totals, or the
    billing group's Power-Query total) — never a second calculation;
  * the residual piaster is settled on the category with the largest discount (ties: local first).
"""
from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase, TestCase

from apps.insurance import models as m
from apps.insurance.classifier import powerquery_totals_from_splits
from apps.insurance.importer import recalculate_claim_final_totals
from apps.insurance.invoice_builder import build_invoice_dataset, cover_category_discounts

D = Decimal
CATS = ('local', 'imported', 'tarsia')


def _old_float_cover(before, pct):
    """The pre-D-15 formula, kept here only to pin the golden differences."""
    return round(float(before) * float(pct) / 100, 2)


class CoverCategoryDiscountsTests(SimpleTestCase):
    """The pure helper: half-up per category, residual on the largest category."""

    def split(self, befores, rates, total, override_delta=None):
        return cover_category_discounts(dict(zip(CATS, map(D, befores))), dict(zip(CATS, map(D, rates))),
                                        D(total), override_delta)

    def test_half_up_at_x_xx5(self):
        # 0.10 × 15% = 0.015 → 0.02 ; 10.05 × 10% = 1.005 → 1.01 ; 0.30 × 25% = 0.075 → 0.08
        for before, rate, want in (('0.10', '15', '0.02'), ('10.05', '10', '1.01'), ('0.30', '25', '0.08'),
                                   ('100.30', '15', '15.05'), ('100.45', '10', '10.05')):
            with self.subTest(before=before, rate=rate):
                got = self.split((before, '0', '0'), (rate, '0', '0'), want)
                self.assertEqual(got['local'], D(want))
                # what the float formula printed — the golden difference D-15 removes
                self.assertNotEqual(D(str(_old_float_cover(before, rate))), D(want))

    def test_results_are_decimal_cents(self):
        got = self.split(('123.45', '67.89', '10.00'), ('15', '10', '5'), '25.80')
        for c in CATS:
            self.assertIsInstance(got[c], Decimal)
            self.assertEqual(got[c], got[c].quantize(D('0.01')))

    def test_rows_always_add_up_to_the_claim_total(self):
        # the claim net is rounded once over the summed splits (M-4), so its total discount can sit a
        # piaster away from the three half-up rows; the rows still add up to it exactly.
        for lb, ib, tb, lr, ir, tr in (('100.30', '100.45', '0', '15', '10', '0'),
                                       ('10.05', '20.05', '30.05', '15', '10', '5'),
                                       ('0.10', '0.15', '0.05', '15', '10', '30'),
                                       ('1234.56', '789.01', '45.67', '17', '12', '3')):
            pq = powerquery_totals_from_splits(D(lb), D(ib), D(tb), D(lr), D(ir), D(tr))
            got = self.split((lb, ib, tb), (lr, ir, tr), pq['total_discount'])
            with self.subTest(splits=(lb, ib, tb)):
                self.assertEqual(sum(got.values(), D('0')), pq['total_discount'])

    def test_residual_goes_to_the_largest_category(self):
        # rows 15.05 + 10.05 = 25.10; claim total 25.09 → −0.01 on محلى (largest)
        got = self.split(('100.30', '100.45', '0'), ('15', '10', '0'), '25.09')
        self.assertEqual(got, {'local': D('15.04'), 'imported': D('10.05'), 'tarsia': D('0.00')})
        # the largest is chosen by discount, not by category order
        got = self.split(('10.00', '200.00', '0'), ('15', '10', '0'), '21.51')
        self.assertEqual(got, {'local': D('1.50'), 'imported': D('20.01'), 'tarsia': D('0.00')})

    def test_a_tie_settles_on_local_first(self):
        got = self.split(('100.00', '100.00', '0'), ('10', '10', '0'), '20.01')
        self.assertEqual(got, {'local': D('10.01'), 'imported': D('10.00'), 'tarsia': D('0.00')})

    def test_net_override_moves_are_part_of_their_category(self):
        got = self.split(('100.00', '0', '0'), ('15', '0', '0'), '35.00',
                         {'local_discount': D('20.00'), 'imported_discount': D('0'), 'tarsia_discount': D('0')})
        self.assertEqual(got['local'], D('35.00'))

    def test_no_residual_needs_no_settling(self):
        got = self.split(('100.00', '50.00', '20.00'), ('15', '10', '5'), '21.00')
        self.assertEqual(got, {'local': D('15.00'), 'imported': D('5.00'), 'tarsia': D('1.00')})

    def test_a_large_residual_is_settled_but_logged(self):
        with self.assertLogs('apps.insurance.invoice_builder', level='WARNING'):
            got = self.split(('100.00', '0', '0'), ('15', '0', '0'), '16.00')
        self.assertEqual(got['local'], D('16.00'))


class CoverMatchesClaimTotalsTests(TestCase):
    """build_invoice_dataset: the cover rows add up to the claim's own final_* totals."""

    def claim(self, rates, number):
        client = m.InsuranceClient.objects.create(name=f'ش{number}')
        sub = m.InsuranceSubClient.objects.create(client=client, name='ف')
        return m.InsuranceClaim.objects.create(
            claim_number=f'MT-D15-{number}', subclient=sub, period_from=date(2026, 10, 1),
            period_to=date(2026, 10, 31), applied_local_disc_pct=D(rates[0]),
            applied_imported_disc_pct=D(rates[1]), applied_tarsia_disc_pct=D(rates[2]))

    def rx(self, claim, n, splits, rates, group=None):
        t = powerquery_totals_from_splits(*map(D, splits), *map(D, rates))
        return m.InsuranceClaimPrescription.objects.create(
            claim=claim, softech_docnumber=f'8{claim.id:03d}{n:03d}', softech_branchcode='130',
            softech_docdate=date(2026, 10, 5), local_before=t['local_before'],
            imported_before=t['imported_before'], tarsia_before=t['tarsia_before'],
            gross_before=t['gross_before'], local_discount=t['local_discount'],
            imported_discount=t['imported_discount'], tarsia_discount=t['tarsia_discount'],
            total_discount=t['total_discount'], net_after=t['net_after'], billing_group=group)

    def assert_cover_matches(self, cv, gross, discount, net):
        self.assertEqual(D(str(cv['gross_before'])), gross)
        self.assertEqual(D(str(cv['total_discount'])), discount)
        self.assertEqual(D(str(cv['net_after'])), net)
        self.assertEqual(sum(D(str(cv[f'{c}_discount'])) for c in CATS), discount)
        self.assertEqual(sum(D(str(cv[f'{c}_net'])) for c in CATS), net)
        for c in CATS:
            self.assertEqual(D(str(cv[f'{c}_before'])) - D(str(cv[f'{c}_discount'])), D(str(cv[f'{c}_net'])))

    CLAIMS = [
        # golden: float rows printed 15.04 + 10.04 = 25.08 against the claim's 25.09
        (('15', '10', '0'), [('100.30', '100.45', '0')]),
        (('15', '10', '0'), [('10.05', '0', '0')] * 3),                       # M-4 claim (net 25.63)
        (('15', '10', '5'), [('10.05', '20.05', '30.05'), ('0.10', '0.15', '0.05'), ('99.99', '0', '1.01')]),
        (('17', '12', '3'), [('1234.56', '789.01', '45.67'), ('0.30', '0.70', '0'), ('55.55', '44.45', '3.33')]),
        (('25', '30', '0'), [('0.06', '0.05', '0'), ('100.18', '200.25', '0')]),
    ]

    def test_cover_sum_equals_the_claim_total_for_several_claims(self):
        for i, (rates, rows) in enumerate(self.CLAIMS):
            claim = self.claim(rates, i)
            for n, splits in enumerate(rows):
                self.rx(claim, n, splits, rates)
            recalculate_claim_final_totals(claim)
            claim.refresh_from_db()
            with self.subTest(claim=i):
                cv = build_invoice_dataset(claim)['cover']
                self.assert_cover_matches(cv, claim.final_gross_before, claim.final_total_discount,
                                          claim.final_net_after)

    def test_golden_claim_rows(self):
        rates, rows = self.CLAIMS[0]
        claim = self.claim(rates, 'g')
        self.rx(claim, 0, rows[0], rates)
        recalculate_claim_final_totals(claim)
        claim.refresh_from_db()
        self.assertEqual(claim.final_total_discount, D('25.09'))
        cv = build_invoice_dataset(claim)['cover']
        old = _old_float_cover('100.30', 15) + _old_float_cover('100.45', 10)
        self.assertEqual(D(str(round(old, 2))), D('25.08'))          # the BE-16 mismatch
        self.assertEqual((D(str(cv['local_discount'])), D(str(cv['imported_discount']))),
                         (D('15.04'), D('10.05')))                    # half-up rows, residual on محلى

    def test_billing_group_cover_matches_the_group_totals(self):
        rates = ('15', '10', '5')
        claim = self.claim(rates, 'bg')
        grp = m.InsuranceClaimBillingGroup.objects.create(claim=claim, code='A', name='أ')
        self.rx(claim, 0, ('100.30', '100.45', '0.05'), rates, group=grp)
        self.rx(claim, 1, ('10.05', '0', '0'), rates, group=grp)
        self.rx(claim, 2, ('500.00', '0', '0'), rates)                # another group's row
        data = build_invoice_dataset(claim, billing_group=grp)
        pq = powerquery_totals_from_splits(D('110.35'), D('100.45'), D('0.05'), *map(D, rates))
        self.assert_cover_matches(data['cover'], pq['gross_before'], pq['total_discount'], pq['net_after'])
        ct = data['claim_totals']
        self.assertEqual(D(str(ct['net_after'])), pq['net_after'])
