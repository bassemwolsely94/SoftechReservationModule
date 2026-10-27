"""
Golden/regression tests for the insurance claims module.

Covers the deterministic financial core (Power-Query net formula, per-line
discount), the cross-claim duplicate-receipt guard, detailed manual-prescription
creation + totals, manual-only (no-SOFTECH) claim creation, name-separation
matching, and lock-guard enforcement on submitted claims.

No SOFTECH/Sybase access — fixtures are built in the local DB and manual
prescriptions use a fabricated fetch-result dict, so these run in CI.
"""
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.insurance import models as m
from apps.insurance.classifier import (
    powerquery_totals_from_splits, calculate_line_discount,
)
from apps.insurance.importer import (
    find_duplicate_receipt, create_manual_prescription,
    recalculate_claim_final_totals,
)
from apps.insurance.separation import match_name, normalize_name, _tokens
from apps.insurance import separation as sep


# ── helpers ──────────────────────────────────────────────────────────────────
def _mk_claim(pf='2026-08-01', pt='2026-08-31', number='MT-T-0001',
              status=m.InsuranceClaim.STATUS_DRAFT, sub=None,
              l=17, i=6, t=0):
    if sub is None:
        client = m.InsuranceClient.objects.create(name='جهة اختبار')
        sub = m.InsuranceSubClient.objects.create(client=client, name='فئة اختبار')
    return m.InsuranceClaim.objects.create(
        claim_number=number, subclient=sub,
        period_from=date.fromisoformat(pf), period_to=date.fromisoformat(pt),
        status=status,
        applied_local_disc_pct=l, applied_imported_disc_pct=i, applied_tarsia_disc_pct=t,
    )


def _add_rx(claim, docnumber, local=0, imported=0, tarsia=0, docdate='2026-08-10',
            branch='160', is_manual=False):
    return m.InsuranceClaimPrescription.objects.create(
        claim=claim, softech_docnumber=docnumber,
        softech_docdate=date.fromisoformat(docdate), softech_branchcode=branch,
        local_before=local, imported_before=imported, tarsia_before=tarsia,
        gross_before=local + imported + tarsia, is_manual=is_manual,
    )


# ── 1. Deterministic financial core ──────────────────────────────────────────
class PowerQueryNetTests(TestCase):
    def test_pq_net_golden(self):
        # 1000 local @17% + 1000 imported @6% = 830 + 940 = 1770
        r = powerquery_totals_from_splits(
            Decimal('1000'), Decimal('1000'), Decimal('0'),
            Decimal('17'), Decimal('6'), Decimal('0'))
        self.assertEqual(Decimal(str(r['gross_before'])), Decimal('2000.00'))
        self.assertEqual(Decimal(str(r['net_after'])), Decimal('1770.00'))
        self.assertEqual(Decimal(str(r['total_discount'])), Decimal('230.00'))

    def test_pq_net_with_tarsia(self):
        r = powerquery_totals_from_splits(
            Decimal('500'), Decimal('0'), Decimal('300'),
            Decimal('17'), Decimal('6'), Decimal('10'))
        # 500*0.83 + 300*0.90 = 415 + 270 = 685
        self.assertEqual(Decimal(str(r['net_after'])), Decimal('685.00'))

    def test_pq_aggregate_not_perline(self):
        # aggregate discount over the SUM per category, then sum nets — the
        # finance-team methodology.  Two local lines 300+700 @17% = 1000*0.83=830.
        r = powerquery_totals_from_splits(
            Decimal('1000'), Decimal('0'), Decimal('0'),
            Decimal('17'), Decimal('6'), Decimal('0'))
        self.assertEqual(Decimal(str(r['net_after'])), Decimal('830.00'))

    def test_line_discount(self):
        disc, net = calculate_line_discount(
            m.ITEM_CATEGORY_IMPORTED, Decimal('1000'),
            Decimal('17'), Decimal('6'), Decimal('0'))
        self.assertEqual(disc, Decimal('60.00'))
        self.assertEqual(net, Decimal('940.00'))
        disc2, net2 = calculate_line_discount(
            m.ITEM_CATEGORY_LOCAL, Decimal('1000'),
            Decimal('17'), Decimal('6'), Decimal('0'))
        self.assertEqual(net2, Decimal('830.00'))


# ── 2. Cross-claim duplicate-receipt guard ───────────────────────────────────
class DuplicateReceiptTests(TestCase):
    def setUp(self):
        self.client_obj = m.InsuranceClient.objects.create(name='ج')
        self.sub = m.InsuranceSubClient.objects.create(client=self.client_obj, name='ف')

    def test_same_month_flagged(self):
        a = _mk_claim(number='A', sub=self.sub)
        b = _mk_claim(number='B', sub=self.sub)          # overlapping Aug period
        _add_rx(a, '555001', local=100)
        dups = find_duplicate_receipt(b, '555001')
        self.assertEqual(len(dups), 1)
        self.assertEqual(dups[0]['claim_number'], 'A')

    def test_different_month_not_flagged(self):
        a = _mk_claim(number='A', sub=self.sub)
        b = _mk_claim(number='B', sub=self.sub, pf='2026-09-01', pt='2026-09-30')
        _add_rx(a, '555002', local=100)
        self.assertEqual(find_duplicate_receipt(b, '555002'), [])

    def test_rejected_peer_not_flagged(self):
        a = _mk_claim(number='A', sub=self.sub, status=m.InsuranceClaim.STATUS_REJECTED)
        b = _mk_claim(number='B', sub=self.sub)
        _add_rx(a, '555003', local=100)
        self.assertEqual(find_duplicate_receipt(b, '555003'), [])

    def test_self_not_flagged(self):
        a = _mk_claim(number='A', sub=self.sub)
        _add_rx(a, '555004', local=100)
        self.assertEqual(find_duplicate_receipt(a, '555004'), [])


# ── 3. Detailed manual prescription (no SOFTECH) ─────────────────────────────
class ManualPrescriptionTests(TestCase):
    def _rx_data(self, docnumber):
        return {
            'softech_docnumber': docnumber,
            'softech_docdate':   date(2026, 7, 20),
            'softech_branchcode': '150',
            'softech_personcode': '4999',
            'patient_name':      'مريض اختبار',
            'lines': [
                {'itemcode': '111', 'item_name': 'صنف محلى', 'category': m.ITEM_CATEGORY_LOCAL,
                 'origin_code': '0', 'imported_flag': False, 'store_classif': '10',
                 'quantity': Decimal('1'), 'unit_price': Decimal('1000'), 'line_total': Decimal('1000')},
                {'itemcode': '222', 'item_name': 'صنف مستورد', 'category': m.ITEM_CATEGORY_IMPORTED,
                 'origin_code': '1', 'imported_flag': True, 'store_classif': '10',
                 'quantity': Decimal('1'), 'unit_price': Decimal('1000'), 'line_total': Decimal('1000')},
            ],
            'local_before': Decimal('1000'), 'imported_before': Decimal('1000'),
            'tarsia_before': Decimal('0'), 'gross_before': Decimal('2000'),
            'local_discount': Decimal('170'), 'imported_discount': Decimal('60'),
            'tarsia_discount': Decimal('0'), 'total_discount': Decimal('230'),
            'net_after': Decimal('1770'), 'softech_net': None,
        }

    def test_detailed_creates_real_prescription_with_lines(self):
        claim = _mk_claim(number='M1')
        rx = create_manual_prescription(claim, self._rx_data('700100'), position='before')
        self.assertTrue(rx.is_manual)
        self.assertEqual(rx.manual_position, 'before')
        self.assertEqual(rx.lines.count(), 2)
        claim.refresh_from_db()
        self.assertEqual(Decimal(str(claim.final_net_after)), Decimal('1770.00'))

    def test_duplicate_docnumber_in_same_claim_rejected(self):
        claim = _mk_claim(number='M2')
        create_manual_prescription(claim, self._rx_data('700200'))
        with self.assertRaises(Exception):
            create_manual_prescription(claim, self._rx_data('700200'))

    def test_delete_restores_totals(self):
        claim = _mk_claim(number='M3')
        rx = create_manual_prescription(claim, self._rx_data('700300'))
        claim.refresh_from_db()
        self.assertGreater(Decimal(str(claim.final_net_after)), Decimal('0'))
        rx.delete()
        recalculate_claim_final_totals(claim)
        claim.refresh_from_db()
        self.assertEqual(Decimal(str(claim.final_net_after)), Decimal('0.00'))


# ── 3b. Partial-pack gross precision (apply-master must not re-multiply 3dp qty) ─
class PartialPackPrecisionTests(TestCase):
    """
    JUSPRIN: pack of 3 strips, pack price 81 → 2 strips = 54.00 (SOFTECH gross).
    The stored quantity column keeps only 3 decimals (⅔ → 0.667), while the frozen
    line_total was computed at import from the full-precision qty (0.66667×81=54.00).
    apply_current_master must derive the new gross by SCALING the frozen gross by
    the price ratio — NOT re-multiplying 0.667 (which inflates 54.00 → 54.03).
    """
    _seq = 0
    def _line(self, claim, unit_price, line_total, qty, cat=m.ITEM_CATEGORY_LOCAL):
        PartialPackPrecisionTests._seq += 1
        rx = _add_rx(claim, f'9143{PartialPackPrecisionTests._seq:02d}', local=float(line_total))
        return m.InsuranceClaimLine.objects.create(
            prescription=rx, softech_itemcode='122342', item_name='جوسبرين',
            item_category=cat, quantity=Decimal(qty), unit_price=Decimal(unit_price),
            line_total=Decimal(line_total),
            discount_pct=Decimal('17'),
            discount_amt=(Decimal(line_total) * Decimal('0.17')).quantize(Decimal('0.01')),
            net_amount=(Decimal(line_total) * Decimal('0.83')).quantize(Decimal('0.01')),
            softech_imported_flag=False, softech_store_classif='10',
        )

    def test_apply_master_preserves_gross_when_price_unchanged(self):
        from apps.catalog.models import Item
        from apps.insurance.discrepancy import apply_current_master
        # Catalog master with the SAME public pack price (81) — nothing should move
        Item.objects.create(softech_id='122342', name='جوسبرين',
                            is_imported=False, store_classif='10', pack_price=Decimal('81'))
        claim = _mk_claim(number='JP1')
        ln = self._line(claim, '81.000', '54.00', '0.667')
        apply_current_master(claim)          # apply BOTH price + category
        ln.refresh_from_db()
        # Must stay 54.00 — the bug produced 54.03 (81 × 0.667 truncated qty)
        self.assertEqual(Decimal(str(ln.line_total)), Decimal('54.00'))

    def test_apply_master_scales_gross_when_price_changes(self):
        from apps.catalog.models import Item
        from apps.insurance.discrepancy import apply_current_master
        # Public pack price rose 81 → 90; 2 strips should be 90/3×2 = 60.00
        Item.objects.create(softech_id='122342', name='جوسبرين',
                            is_imported=False, store_classif='10', pack_price=Decimal('90'))
        claim = _mk_claim(number='JP2')
        ln = self._line(claim, '81.000', '54.00', '0.667')
        apply_current_master(claim)
        ln.refresh_from_db()
        self.assertEqual(Decimal(str(ln.line_total)), Decimal('60.00'))

    def test_value_discrepancy_flag_isolates_corrupted_line(self):
        from apps.catalog.models import Item
        from apps.insurance.discrepancy import line_variance_map
        Item.objects.create(softech_id='122342', name='جوسبرين',
                            is_imported=False, store_classif='10', pack_price=Decimal('81'))
        claim = _mk_claim(number='JP3')
        good = self._line(claim, '81.000', '54.00', '0.667')   # imported correctly
        bad  = self._line(claim, '81.000', '54.03', '0.667')   # corrupted (81×0.667)
        whole = self._line(claim, '81.000', '81.00', '1.000')  # whole pack — never flagged
        vmap = line_variance_map(claim, [good, bad, whole])
        self.assertFalse(vmap[good.pk]['value_discrepancy'])
        self.assertTrue(vmap[bad.pk]['value_discrepancy'])
        self.assertFalse(vmap[whole.pk]['value_discrepancy'])

    def test_discount_discrepancy_flag(self):
        """Our net (uniform rate) ≠ SOFTECH's own line net ⇒ discount_discrepancy."""
        from apps.insurance.discrepancy import line_variance_map
        from apps.catalog.models import Item
        Item.objects.create(softech_id='125074', name='اسبرين', is_imported=False,
                            store_classif='10', pack_price=Decimal('78'))
        claim = _mk_claim(number='DD1')
        ln = self._line(claim, '78.000', '78.00', '1.000')   # local 17% → our net 64.74
        ln.softech_itemcode = '125074'
        ln.net_amount = Decimal('64.74')
        ln.softech_line_net = Decimal('73.32')               # SOFTECH charged 6%
        ln.save()
        v = line_variance_map(claim, [ln])[ln.pk]
        self.assertTrue(v['discount_discrepancy'])
        self.assertEqual(Decimal(str(v['softech_net_diff'])), Decimal('-8.58'))
        # a line whose nets agree is not flagged
        ln.softech_line_net = Decimal('64.74'); ln.save()
        self.assertFalse(line_variance_map(claim, [ln])[ln.pk]['discount_discrepancy'])

    def test_exact_fractional_qty_not_flagged(self):
        """Fractional qty already exact at 3dp (3.5, 1.6, 0.4) is NOT a discrepancy."""
        from apps.catalog.models import Item
        from apps.insurance.discrepancy import line_variance_map
        Item.objects.create(softech_id='2036', name='تيبونينا',
                            is_imported=False, store_classif='10', pack_price=Decimal('90'))
        claim = _mk_claim(number='JP4')
        # 90 × 3.5 = 315.000 exactly — clean product, must not flag
        a = self._line(claim, '90.000', '315.00', '3.500')
        # 60 × 1.6 = 96.000 exactly
        Item.objects.create(softech_id='195', name='كارب',
                            is_imported=False, store_classif='10', pack_price=Decimal('60'))
        b = self._line(claim, '60.000', '96.00', '1.600')
        vmap = line_variance_map(claim, [a, b])
        self.assertFalse(vmap[a.pk]['value_discrepancy'])
        self.assertFalse(vmap[b.pk]['value_discrepancy'])


# ── 3c. Flagged-line revision workflow (API) ─────────────────────────────────
class RevisionWorkflowTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='rev', password='x', is_staff=True, is_superuser=True)
        self.api = APIClient(); self.api.force_authenticate(self.user)
        from apps.catalog.models import Item
        Item.objects.create(softech_id='122342', name='جوسبرين',
                            is_imported=False, store_classif='10', pack_price=Decimal('81'))

    def _corrupted_claim(self):
        claim = _mk_claim(number='RV1')
        rx = _add_rx(claim, '914329', local=54.03)
        ln = m.InsuranceClaimLine.objects.create(
            prescription=rx, softech_itemcode='122342', item_name='جوسبرين',
            item_category=m.ITEM_CATEGORY_LOCAL, quantity=Decimal('0.667'),
            unit_price=Decimal('81'), line_total=Decimal('54.03'),
            discount_pct=Decimal('17'), discount_amt=Decimal('9.19'), net_amount=Decimal('44.84'),
            softech_imported_flag=False, softech_store_classif='10')
        return claim, rx, ln

    def test_flagged_lines_lists_value_discrepancy(self):
        claim, rx, ln = self._corrupted_claim()
        r = self.api.get(f'/api/insurance/claims/{claim.id}/flagged-lines/')
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body['value_count'], 1)
        self.assertIn('value', body['lines'][0]['flags'])

    def test_review_line_records_approval(self):
        claim, rx, ln = self._corrupted_claim()
        r = self.api.post(
            f'/api/insurance/claims/{claim.id}/prescriptions/{rx.id}/lines/{ln.id}/review/',
            {'approved': True, 'note': 'مطابق للتعاقد'}, format='json')
        self.assertEqual(r.status_code, 200)
        ln.refresh_from_db()
        self.assertTrue(ln.review_approved)
        self.assertEqual(ln.review_note, 'مطابق للتعاقد')
        self.assertIsNotNone(ln.reviewed_at)
        # audit event recorded
        self.assertTrue(claim.audit_events.filter(action='line_review').exists())

    def test_review_line_allowed_on_locked_claim(self):
        claim, rx, ln = self._corrupted_claim()
        claim.status = m.InsuranceClaim.STATUS_SUBMITTED
        claim.save(update_fields=['status'])
        r = self.api.post(
            f'/api/insurance/claims/{claim.id}/prescriptions/{rx.id}/lines/{ln.id}/review/',
            {'approved': True}, format='json')
        self.assertEqual(r.status_code, 200)   # metadata-only, not lock-guarded

    def test_repair_write_path_corrects_gross_and_is_revertible(self):
        """The SOFTECH round-trip is mocked; the write/aggregate/undo path is real."""
        from apps.insurance.management.commands.repair_partial_pack_gross import Command
        from apps.insurance.discrepancy import revert_apply_run
        claim, rx, ln = self._corrupted_claim()
        recalculate_claim_final_totals(claim); claim.refresh_from_db()
        rates = {
            m.ITEM_CATEGORY_LOCAL:    Decimal('17'),
            m.ITEM_CATEGORY_IMPORTED: Decimal('6'),
            m.ITEM_CATEGORY_TARSIA:   Decimal('0'),
        }
        Command()._write_repair(claim, [(ln, Decimal('54.00'))], rates)
        ln.refresh_from_db()
        self.assertEqual(Decimal(str(ln.line_total)), Decimal('54.00'))
        self.assertEqual(Decimal(str(ln.net_amount)), Decimal('44.82'))   # 54.00 × 0.83
        run = claim.apply_runs.latest('id')
        self.assertEqual(run.lines_updated, 1)
        self.assertTrue(claim.audit_events.filter(action='gross_repair').exists())
        # revert restores the corrupted value byte-for-byte
        revert_apply_run(run)
        ln.refresh_from_db()
        self.assertEqual(Decimal(str(ln.line_total)), Decimal('54.03'))


# ── 3d. Readiness: short patient-name check + per-branch breakdown ────────────
class ShortNameReadinessTests(TestCase):
    def _check(self, claim):
        from apps.insurance.validation import validate_claim_readiness
        rep = validate_claim_readiness(claim)
        return next(c for c in rep['checks'] if c['key'] == 'short_patient_names')

    def test_quadruple_names_pass(self):
        claim = _mk_claim(number='NM1')
        _add_rx(claim, '800001', local=100, branch='160')
        m.InsuranceClaimPrescription.objects.filter(claim=claim).update(
            patient_name='احمد محمد علي حسن')   # 4 tokens
        c = self._check(claim)
        self.assertEqual(c['severity'], 'ok')

    def test_short_names_flagged_and_tiered_by_branch(self):
        claim = _mk_claim(number='NM2')
        r1 = _add_rx(claim, '800010', local=100, branch='160'); r1.patient_name = 'احمد'; r1.save()            # فردى
        r2 = _add_rx(claim, '800011', local=100, branch='160'); r2.patient_name = 'احمد محمد'; r2.save()       # ثنائى
        r3 = _add_rx(claim, '800012', local=100, branch='170'); r3.patient_name = 'احمد محمد علي'; r3.save()   # ثلاثى
        r4 = _add_rx(claim, '800013', local=100, branch='170'); r4.patient_name = 'احمد محمد علي حسن'; r4.save()  # pass
        c = self._check(claim)
        self.assertEqual(c['severity'], 'warning')
        self.assertEqual(c['count'], 3)
        self.assertEqual(c['tiers'], {'فردى': 1, 'ثنائى': 1, 'ثلاثى': 1})
        by_branch = {b['branch']: b for b in c['branches']}
        self.assertEqual(by_branch['160']['failed'], 2)   # فردى + ثنائى
        self.assertEqual(by_branch['170']['failed'], 1)   # ثلاثى only (رباعى passes)
        self.assertEqual(by_branch['170']['total'], 2)


# ── 3e. SOFTECH re-price recompute (pure, golden-validated) ──────────────────
class RepriceRecomputeTests(TestCase):
    def test_taxed_line_matches_betadine_golden(self):
        # BETADINE 10% (14% VAT, 17% contract): 85 → 95, verified live on #549566
        from apps.insurance.reprice import recompute_line
        r = recompute_line(new_price='95', transqty='1', custdiscp='17', vat_rate='14')
        self.assertEqual(r['itemsaleprice_tax'], Decimal('83.3333'))   # 95/1.14
        self.assertEqual(r['transprice'],        Decimal('78.8500'))   # 95×0.83
        self.assertEqual(r['itemsalestax'],      Decimal('9.6833'))    # net×14/114
        self.assertEqual(r['transprice_total'],  Decimal('78.85'))

    def test_normal_line_no_vat(self):
        from apps.insurance.reprice import recompute_line
        r = recompute_line(new_price='270', transqty='1', custdiscp='17', vat_rate='0')
        self.assertEqual(r['itemsaleprice_tax'], Decimal('270.0000'))  # no VAT → = price
        self.assertEqual(r['itemsalestax'],      Decimal('0.0000'))
        self.assertEqual(r['transprice_total'],  Decimal('224.10'))    # 270×0.83

    def test_units_line_scales_total(self):
        from apps.insurance.reprice import recompute_line
        r = recompute_line(new_price='81', transqty='0.66667', custdiscp='17', vat_rate='0')
        # 81×0.83 = 67.23 net unit; ×0.66667 = 44.82
        self.assertEqual(r['transprice_total'], Decimal('44.82'))

    def test_header_refoot_is_incremental_when_docvalue_ne_sum(self):
        # Receipt whose stored docvalue (4343.66) != Σ transprice_total (4244.06)
        # because of a partial-pack line — header must shift by the EDITED line's
        # delta only (+8.30), NOT be rebuilt to an absolute Σ.
        from apps.insurance.reprice_service import _compute
        header = {'docvalue': '4343.66', 'docvalue1': '4957.0', 'docvalue3': '161.26'}
        lines = [
            {'itemcode': '128721', 'transqty': '1.0', 'itemsaleprice': '240.0',
             'itemsaleprice_tax': '240.0', 'itemsalestax': '0.0', 'transprice': '199.2',
             'transprice_total': '199.2', 'additionaldiscp': '0.0', 'custdiscp': '17.0'},
            # partial-pack quirk line: transprice_total (24.9) != transprice×qty (124.5)
            {'itemcode': '86673', 'transqty': '1.66667', 'itemsaleprice': '90.0',
             'itemsaleprice_tax': '90.0', 'itemsalestax': '0.0', 'transprice': '74.7',
             'transprice_total': '24.9', 'additionaldiscp': '0.0', 'custdiscp': '17.0'},
        ]
        _nl, h, _d = _compute(lines, header, {'128721': Decimal('250')})
        self.assertEqual(h['docvalue'],  Decimal('4351.96'))   # 4343.66 + 8.30
        self.assertEqual(h['docvalue1'], Decimal('4967.00'))   # 4957 + 10
        self.assertEqual(h['docvalue3'], Decimal('161.26'))    # unchanged

    def test_reprice_duplicate_item_targeted_by_dblitemflag(self):
        # Same itemcode on 2 lines distinguished by dblitemflag → allowed (each targeted).
        from apps.insurance.reprice_service import _compute, RepriceError
        header = {'docvalue': '200', 'docvalue1': '240', 'docvalue3': '0'}
        L = lambda t, flag: {'itemcode': '555', 'transqty': '1.0', 'itemsaleprice': '120.0',
                             'itemsaleprice_tax': '120.0', 'itemsalestax': '0.0', 'transprice': '99.6',
                             'transprice_total': t, 'additionaldiscp': '0.0', 'custdiscp': '17.0',
                             'dblitemflag': flag}
        nl, h, diffs = _compute([L('99.60', '1'), L('99.60', '2')], header, {'555': Decimal('130')})
        self.assertEqual(len([d for d in diffs if d['itemcode'] == '555']), 2)  # both lines edited
        # but two lines with the SAME (itemcode, dblitemflag) are indistinguishable → refuse
        with self.assertRaises(RepriceError):
            _compute([L('99.60', '1'), L('99.60', '1')], header, {'555': Decimal('130')})

    def test_reprice_refuses_partial_pack_line(self):
        from apps.insurance.reprice_service import _compute, RepriceError
        header = {'docvalue': '100', 'docvalue1': '120', 'docvalue3': '0'}
        lines = [{'itemcode': '86673', 'transqty': '1.66667', 'itemsaleprice': '90.0',
                  'itemsaleprice_tax': '90.0', 'itemsalestax': '0.0', 'transprice': '74.7',
                  'transprice_total': '24.9', 'additionaldiscp': '0.0', 'custdiscp': '17.0'}]
        with self.assertRaises(RepriceError):
            _compute(lines, header, {'86673': Decimal('95')})

    def test_header_refoot_matches_betadine_receipt(self):
        # #549566: lines 114/95/220 → gross 429.00, net 356.07, VAT 9.68
        from apps.insurance.reprice import recompute_line, refoot_header
        lines = [
            recompute_line(new_price='114', transqty='1', custdiscp='17', vat_rate='0'),
            recompute_line(new_price='95',  transqty='1', custdiscp='17', vat_rate='14'),
            recompute_line(new_price='220', transqty='1', custdiscp='17', vat_rate='0'),
        ]
        h = refoot_header(lines)
        self.assertEqual(h['docvalue1'], Decimal('429.00'))
        self.assertEqual(h['docvalue'],  Decimal('356.07'))
        self.assertEqual(h['docvalue3'], Decimal('9.68'))


# ── 3f. SOFTECH re-price writeback GUARDS (no SOFTECH access) ─────────────────
class RepriceWriteGuardTests(TestCase):
    """The apply/rebalance/revert paths must refuse before any Sybase connection."""
    def setUp(self):
        self.claim = _mk_claim(number='WG1')

    @override_settings(INSURANCE_SOFTECH_WRITE_ENABLED=False)
    def test_apply_blocked_when_flag_off(self):
        from apps.insurance.reprice_service import apply_reprice, RepriceError
        with self.assertRaises(RepriceError) as cm:
            apply_reprice(self.claim, '549566', '140', {'121191': '95'}, confirm=True)
        self.assertIn('معطّلة', str(cm.exception))

    @override_settings(INSURANCE_SOFTECH_WRITE_ENABLED=True)
    def test_apply_blocked_without_confirm(self):
        from apps.insurance.reprice_service import apply_reprice, RepriceError
        with self.assertRaises(RepriceError) as cm:
            apply_reprice(self.claim, '549566', '140', {'121191': '95'}, confirm=False)
        self.assertIn('التأكيد', str(cm.exception))

    @override_settings(INSURANCE_SOFTECH_WRITE_ENABLED=True)
    def test_apply_blocked_on_locked_claim(self):
        from apps.insurance.reprice_service import apply_reprice, RepriceError
        self.claim.status = m.InsuranceClaim.STATUS_SUBMITTED
        self.claim.save(update_fields=['status'])
        with self.assertRaises(RepriceError) as cm:
            apply_reprice(self.claim, '549566', '140', {'121191': '95'}, confirm=True)
        self.assertIn('مسودة', str(cm.exception))

    @override_settings(INSURANCE_SOFTECH_WRITE_ENABLED=False)
    def test_rebalance_and_revert_blocked_when_flag_off(self):
        from apps.insurance.reprice_service import rebalance_run, revert_run, RepriceError
        run = m.SoftechRepriceRun.objects.create(
            claim=self.claim, docnumber='549566', branchcode='140',
            cust_branch_code='4227', net_delta=Decimal('1.0'),
            status=m.SoftechRepriceRun.STATUS_APPLIED)
        with self.assertRaises(RepriceError):
            rebalance_run(run, confirm=True)
        with self.assertRaises(RepriceError):
            revert_run(run)

    @override_settings(INSURANCE_SOFTECH_WRITE_ENABLED=True)
    def test_rebalance_blocked_without_confirm_and_when_already_done(self):
        from apps.insurance.reprice_service import rebalance_run, RepriceError
        run = m.SoftechRepriceRun.objects.create(
            claim=self.claim, docnumber='549566', branchcode='140',
            cust_branch_code='4227', net_delta=Decimal('1.0'),
            status=m.SoftechRepriceRun.STATUS_APPLIED)
        with self.assertRaises(RepriceError):
            rebalance_run(run, confirm=False)          # no confirm
        run.rebalanced = True; run.save(update_fields=['rebalanced'])
        with self.assertRaises(RepriceError):
            rebalance_run(run, confirm=True)           # already rebalanced


# ── 4. Name-separation matching ──────────────────────────────────────────────
class SeparationMatchTests(TestCase):
    def _m(self, rx, listed):
        return match_name(_tokens(normalize_name(rx)), _tokens(normalize_name(listed)))

    def test_exact_full(self):
        ok, typ, _ = self._m('احمد محمد علي', 'احمد محمد علي')
        self.assertTrue(ok); self.assertEqual(typ, 'full')

    def test_ordered_full_with_extra_middle(self):
        ok, typ, _ = self._m('احمد محمد حسن علي', 'احمد محمد علي')
        self.assertTrue(ok)

    def test_two_token_requires_exact(self):
        ok, _, _ = self._m('راضى ماهر حسن', 'راضى ماهر')
        self.assertFalse(ok)

    def test_unrelated_no_match(self):
        ok, _, _ = self._m('سمير صادق بولس', 'احمد محمد علي')
        self.assertFalse(ok)


# ── 5. Lock-guard + manual-only claim (API) ──────────────────────────────────
class ApiGuardTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='tester', password='x', is_staff=True, is_superuser=True)
        self.api = APIClient()
        self.api.force_authenticate(self.user)
        self.client_obj = m.InsuranceClient.objects.create(name='ج')
        self.sub = m.InsuranceSubClient.objects.create(client=self.client_obj, name='ف')

    def test_locked_claim_rejects_apply(self):
        claim = _mk_claim(number='L1', sub=self.sub,
                          status=m.InsuranceClaim.STATUS_SUBMITTED)
        r = self.api.post(f'/api/insurance/claims/{claim.id}/apply-current-master/', {}, format='json')
        self.assertEqual(r.status_code, 423)

    def test_locked_claim_rejects_supplement_post(self):
        claim = _mk_claim(number='L2', sub=self.sub,
                          status=m.InsuranceClaim.STATUS_PAID)
        r = self.api.post(f'/api/insurance/claims/{claim.id}/supplements/',
                          {'label': 'x', 'net_after': 10}, format='json')
        self.assertEqual(r.status_code, 423)

    def test_create_manual_claim_without_personcode(self):
        # sub has NO softech_personcode
        r = self.api.post('/api/insurance/claims/create-manual/', {
            'subclient_id': self.sub.id,
            'period_from': '2026-08-01', 'period_to': '2026-08-31',
        }, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        cid = r.json()['claim']['id']
        claim = m.InsuranceClaim.objects.get(pk=cid)
        self.assertEqual(claim.status, m.InsuranceClaim.STATUS_DRAFT)
        self.assertEqual(claim.prescriptions.count(), 0)

    def test_duplicate_add_conflicts_then_force(self):
        a = _mk_claim(number='D1', sub=self.sub)
        b = _mk_claim(number='D2', sub=self.sub)
        _add_rx(a, '900900', local=100)
        # simple manual add of the same receipt into B → 409 (no SOFTECH so the
        # duplicate check runs BEFORE the SOFTECH fetch is reached only if we
        # bypass fetch; here we assert the detector directly).
        self.assertEqual(len(find_duplicate_receipt(b, '900900')), 1)


# ── 7. RBAC — server-side module access ──────────────────────────────────────
class RbacTests(TestCase):
    def _user(self, username, role=None, superuser=False):
        u = get_user_model().objects.create_user(username=username, password='x',
                                                  is_staff=True, is_superuser=superuser)
        if role is not None:
            from apps.users.models import StaffProfile
            StaffProfile.objects.create(
                user=u, role=role, is_active=True,
                softech_username=username, softech_user_id=username, phone='0')
        api = APIClient(); api.force_authenticate(u)
        return api

    def test_ungranted_role_denied(self):
        api = self._user('sales1', role='salesperson')   # no insurance grant
        self.assertEqual(api.get('/api/insurance/claims/').status_code, 403)

    def test_granted_role_allowed(self):
        # purchasing was granted insurance via migration 0024
        api = self._user('buyer1', role='purchasing')
        self.assertEqual(api.get('/api/insurance/claims/').status_code, 200)

    def test_admin_role_allowed(self):
        api = self._user('adm1', role='admin')
        self.assertEqual(api.get('/api/insurance/claims/').status_code, 200)

    def test_superuser_bypass(self):
        api = self._user('root1', superuser=True)         # no staff_profile
        self.assertEqual(api.get('/api/insurance/claims/').status_code, 200)

    def test_view_only_role_cannot_write(self):
        # grant salesperson VIEW only on insurance, then a write must 403
        from apps.users.models import RoleModuleAccess
        RoleModuleAccess.objects.create(role='call_center', module='insurance', action='view', is_allowed=True)
        api = self._user('cc1', role='call_center')
        self.assertEqual(api.get('/api/insurance/claims/').status_code, 200)      # view ok
        # a create (write) needs 'edit' → denied
        r = api.post('/api/insurance/claims/create-manual/',
                     {'subclient_id': 999999, 'period_from': '2026-08-01', 'period_to': '2026-08-31'}, format='json')
        self.assertEqual(r.status_code, 403)


# ── 6. Audit trail ───────────────────────────────────────────────────────────
class AuditTrailTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='auditor', password='x', is_staff=True, is_superuser=True)
        self.api = APIClient(); self.api.force_authenticate(self.user)
        self.sub = m.InsuranceSubClient.objects.create(
            client=m.InsuranceClient.objects.create(name='ج'), name='ف')

    def test_status_change_is_audited(self):
        claim = _mk_claim(number='AU1', sub=self.sub)
        r = self.api.post(f'/api/insurance/claims/{claim.id}/change-status/',
                          {'status': m.InsuranceClaim.STATUS_READY}, format='json')
        self.assertEqual(r.status_code, 200)
        ev = claim.audit_events.filter(action='status_change')
        self.assertEqual(ev.count(), 1)
        self.assertEqual(ev.first().before, {'status': 'draft'})
        self.assertEqual(ev.first().after, {'status': 'ready'})

    def test_exclude_is_audited(self):
        claim = _mk_claim(number='AU2', sub=self.sub)
        rx = _add_rx(claim, '811001', local=100)
        r = self.api.post(
            f'/api/insurance/claims/{claim.id}/prescriptions/{rx.id}/exclude/',
            {'reason': 'مكرر'}, format='json')
        self.assertIn(r.status_code, (200, 201))
        self.assertTrue(claim.audit_events.filter(action='rx_exclude').exists())

    def test_audit_log_endpoint(self):
        claim = _mk_claim(number='AU3', sub=self.sub)
        self.api.post(f'/api/insurance/claims/{claim.id}/change-status/',
                      {'status': m.InsuranceClaim.STATUS_READY}, format='json')
        r = self.api.get(f'/api/insurance/claims/{claim.id}/audit-log/')
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertGreaterEqual(body['count'], 1)
        self.assertEqual(body['events'][0]['action'], 'status_change')
        self.assertIn('action_label', body['events'][0])
