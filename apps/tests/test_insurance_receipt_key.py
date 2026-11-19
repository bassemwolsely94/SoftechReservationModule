"""
Audit S-8 / D-10, owner-approved 2026-11-19: an insurance claim receipt is
(branch, doccode, docnumber), not docnumber alone.

SOFTECH numbers each document type separately per branch, so receipt 500 at branch 140 and
receipt 500 at branch 150 are two different receipts. Covered here:
- readiness check 7 (cross-claim double billing) flags only the same receipt;
- the claim-level unique key and the detailed manual-add guard admit genuine same-number
  receipts from other branches / doctypes and still refuse an exact duplicate;
- a legacy row with no doccode (could not be backfilled) still blocks — the guard never
  loosens for data it cannot tell apart;
- the doccode is stored on add, and a resync revert deletes only its own receipt.
"""
from datetime import date

from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.insurance import models as m
from apps.insurance import resync
from apps.insurance.importer import (
    InsuranceImportError, create_manual_prescription, find_receipt_in_claim,
)
from apps.insurance.validation import validate_claim_readiness
from apps.tests.test_insurance import _add_rx, _mk_claim


def _rx_data(docnumber, branch, doccode):
    from decimal import Decimal
    return {
        'softech_docnumber': docnumber, 'softech_docdate': date(2026, 8, 10),
        'softech_branchcode': branch, 'softech_doccode': doccode, 'softech_personcode': '4999',
        'patient_name': 'مريض', 'lines': [
            {'itemcode': '111', 'item_name': 'صنف', 'category': m.ITEM_CATEGORY_LOCAL,
             'origin_code': '0', 'imported_flag': False, 'store_classif': '10',
             'quantity': Decimal('1'), 'unit_price': Decimal('100'), 'line_total': Decimal('100')}],
        'local_before': Decimal('100'), 'imported_before': Decimal('0'), 'tarsia_before': Decimal('0'),
        'gross_before': Decimal('100'), 'local_discount': Decimal('17'), 'imported_discount': Decimal('0'),
        'tarsia_discount': Decimal('0'), 'total_discount': Decimal('17'), 'net_after': Decimal('83'),
        'softech_net': None,
    }


def _rx(claim, docnumber, branch, doccode):
    rx = _add_rx(claim, docnumber, local=100, branch=branch)
    rx.softech_doccode = doccode
    rx.save(update_fields=['softech_doccode'])
    return rx


class ReadinessDoubleBillingKeyTests(TestCase):
    """Readiness check 7 — cross_claim_duplicates."""

    def _severity(self, other_branch, other_doccode, my_doccode='115'):
        mine = _mk_claim(number='MT-RK-1')
        _rx(mine, '500', '140', my_doccode)
        other = _mk_claim(number='MT-RK-2', sub=mine.subclient)
        _rx(other, '500', other_branch, other_doccode)
        checks = {c['key']: c for c in validate_claim_readiness(mine)['checks']}
        return checks['cross_claim_duplicates']['severity']

    def test_same_number_at_another_branch_is_not_flagged(self):
        self.assertEqual(self._severity('150', '115'), 'ok')

    def test_same_number_of_another_doctype_is_not_flagged(self):
        self.assertEqual(self._severity('140', '30'), 'ok')

    def test_real_double_bill_is_still_flagged(self):
        self.assertEqual(self._severity('140', '115'), 'error')

    def test_legacy_row_without_doccode_is_still_flagged(self):
        self.assertEqual(self._severity('140', ''), 'error')


class ClaimReceiptKeyTests(TestCase):
    """Unique key (claim, branch, doccode, docnumber) and the detailed manual-add guard."""

    def setUp(self):
        self.claim = _mk_claim(number='MT-RK-3', pf='2026-08-01', pt='2026-08-31')

    def test_same_number_from_two_branches_can_both_be_added(self):
        a = create_manual_prescription(self.claim, _rx_data('600', '140', '115'))
        b = create_manual_prescription(self.claim, _rx_data('600', '150', '115'))
        self.assertNotEqual(a.pk, b.pk)
        self.assertEqual(self.claim.prescriptions.filter(softech_docnumber='600').count(), 2)

    def test_same_number_sale_and_return_can_both_be_added(self):
        create_manual_prescription(self.claim, _rx_data('601', '140', '115'))
        create_manual_prescription(self.claim, _rx_data('601', '140', '30'))
        self.assertEqual(self.claim.prescriptions.filter(softech_docnumber='601').count(), 2)

    def test_exact_duplicate_is_refused(self):
        create_manual_prescription(self.claim, _rx_data('602', '140', '115'))
        with self.assertRaises(InsuranceImportError):
            create_manual_prescription(self.claim, _rx_data('602', '140', '115'))

    def test_legacy_row_without_doccode_still_blocks_the_same_branch(self):
        _rx(self.claim, '603', '140', '')
        with self.assertRaises(InsuranceImportError):
            create_manual_prescription(self.claim, _rx_data('603', '140', '115'))
        self.assertFalse(find_receipt_in_claim(self.claim, '603', '150', '115'))

    def test_doccode_is_stored_on_add(self):
        rx = create_manual_prescription(self.claim, _rx_data('604', '140', '30'))
        self.assertEqual(rx.softech_doccode, '30')

    def test_database_key_refuses_an_exact_duplicate_row(self):
        _rx(self.claim, '605', '140', '115')
        _rx(self.claim, '605', '150', '115')                 # another branch: allowed
        with self.assertRaises(IntegrityError), transaction.atomic():
            _rx(self.claim, '605', '140', '115')


class ResyncRevertKeyTests(TestCase):
    """revert_resync restores one re-frozen receipt without touching a same-number receipt
    of another branch in the same claim."""

    def test_revert_deletes_only_its_own_receipt(self):
        claim = _mk_claim(number='MT-RK-4')
        mine = _rx(claim, '700', '140', '115')
        other = _rx(claim, '700', '150', '115')
        snap = resync._snapshot_prescription(mine)
        mine.net_after = 1
        mine.save(update_fields=['net_after'])             # the re-synced state
        run = m.ResyncRun.objects.create(claim=claim, payload={'changed': [snap]})
        resync.revert_resync(run)
        self.assertTrue(m.InsuranceClaimPrescription.objects.filter(pk=other.pk).exists())
        restored = m.InsuranceClaimPrescription.objects.get(pk=mine.pk)
        self.assertNotEqual(restored.net_after, 1)


class SingleReceiptFetchKeyTests(TestCase):
    """The SOFTECH single-receipt fetch hands its doccode to the add path."""

    def test_fetch_returns_the_receipts_doccode(self):
        from unittest import mock

        from apps.insurance import importer
        from apps.tests.test_insurance_doccode_lookups import BRANCH, DOC, HEADERS, LINES, _conn
        client = m.InsuranceClient.objects.create(name='عميل')
        sub = m.InsuranceSubClient.objects.create(client=client, name='فئة', softech_personcode='5008')
        claim = m.InsuranceClaim.objects.create(claim_number='MT-RK-5', subclient=sub,
                                                period_from=date(2026, 10, 1), period_to=date(2026, 10, 31))
        with mock.patch.object(importer, '_get_connection', return_value=_conn(LINES, HEADERS)):
            out = importer.fetch_single_rx_from_softech(DOC, claim, branchcode=BRANCH)
        self.assertEqual(out['softech_doccode'], '30')
