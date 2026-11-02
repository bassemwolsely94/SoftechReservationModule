"""
«مزامنة سوفتك بنفس الأسعار»: the catalog-applied prices become one guarded re-price
plan (one run per receipt, all its items), and the SOFTECH reconciliation counts our
applied re-price runs instead of the import-time SOFTECH net.  SOFTECH is mocked.
"""
from datetime import date
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.insurance import models as m
from apps.insurance import reprice_service as rs
from apps.insurance.discrepancy import compute_softech_gross_reconciliation
from apps.insurance.softech_sync import catalog_sync_receipts, softech_status_map

_n = iter(range(1, 10_000))


def _line(code, price):
    p = Decimal(price)
    return {'itemcode': code, 'transqty': Decimal('1'), 'itemsaleprice': p, 'itemsaleprice_tax': p,
            'itemsalestax': Decimal('0'), 'transprice': p * Decimal('0.83'),
            'transprice_total': p * Decimal('0.83'), 'additionaldiscp': Decimal('0'),
            'custdiscp': Decimal('17'), 'newcostprice': Decimal('0'), 'bonusqty': Decimal('0'),
            'dblitemflag': Decimal('1')}


class CatalogSyncTests(TestCase):
    def setUp(self):
        client = m.InsuranceClient.objects.create(name='جنوب')
        sub = m.InsuranceSubClient.objects.create(client=client, name='العاملين')
        self.claim = m.InsuranceClaim.objects.create(
            claim_number='MT-CS-1', subclient=sub, period_from=date(2026, 10, 1), period_to=date(2026, 10, 31))
        self.run = m.InsuranceApplyMasterRun.objects.create(claim=self.claim, apply_price=True)
        # receipt A: two items re-priced by the catalog, one untouched
        self.a = self._rx('930593', softech_net='747.00')
        self._cat_line(self.a, '80052', old='200', new='210')
        self._cat_line(self.a, '124793', old='700', new='770')
        m.InsuranceClaimLine.objects.create(prescription=self.a, softech_itemcode='555', unit_price='50')
        # receipt B: one item re-priced
        self.b = self._rx('931120', softech_net='136.95')
        self._cat_line(self.b, '111062', old='165', new='240')

    def _rx(self, docno, softech_net):
        return m.InsuranceClaimPrescription.objects.create(
            claim=self.claim, softech_docnumber=docno, softech_branchcode='160', sequence=next(_n),
            softech_docdate=date(2026, 10, 3), softech_net=Decimal(softech_net),
            net_after=Decimal(softech_net))

    def _cat_line(self, rx, code, old, new):
        ln = m.InsuranceClaimLine.objects.create(prescription=rx, softech_itemcode=code, unit_price=new)
        m.InsuranceClaimLineBackup.objects.create(run=self.run, line=ln, unit_price=old)
        return ln

    def test_one_entry_per_receipt_with_all_its_changed_items(self):
        receipts, info = catalog_sync_receipts(self.claim)
        by = {r['docno']: r['prices'] for r in receipts}
        self.assertEqual(by['930593'], {'80052': '210.00', '124793': '770.00'})
        self.assertEqual(by['931120'], {'111062': '240.00'})
        self.assertEqual(info['conflicts'], [])

    def test_undone_apply_excluded_receipt_and_conflicts_are_left_out(self):
        self._cat_line(self.a, '80052', old='200', new='215')     # same item, other price, same receipt
        m.InsuranceClaimExclusion.objects.create(prescription=self.b, reason='x')
        receipts, info = catalog_sync_receipts(self.claim)
        self.assertEqual({r['docno']: r['prices'] for r in receipts}, {'930593': {'124793': '770.00'}})
        self.assertEqual(info['conflicts'][0]['itemcode'], '80052')
        self.assertEqual(info['skipped_excluded'], 1)
        self.run.reverted = True; self.run.save()
        self.assertEqual(catalog_sync_receipts(self.claim)[0], [])

    def _applied_run(self, docno, prices, net_after):
        run = m.SoftechRepriceRun.objects.create(
            claim=self.claim, docnumber=docno, branchcode='160', status=m.SoftechRepriceRun.STATUS_APPLIED,
            new_prices=prices)
        m.SoftechRepriceEdit.objects.create(run=run, node='HQ', table='stktransm', field='docvalue',
                                            before='0', after=net_after)
        return run

    def test_status_map_pending_then_edited(self):
        st = softech_status_map(self.claim)
        self.assertEqual(st[('931120', '160')]['status'], 'pending')
        self._applied_run('931120', {'111062': '240'}, '199.20')
        st = softech_status_map(self.claim)
        self.assertEqual(st[('931120', '160')]['status'], 'edited')
        self.assertEqual(st[('931120', '160')]['softech_net'], Decimal('199.20'))
        # a WRONG price written to SOFTECH keeps the receipt pending (the 931120 incident)
        m.SoftechRepriceRun.objects.all().delete()
        self._applied_run('931120', {'111062': '931120'}, '772829.60')
        self.assertEqual(softech_status_map(self.claim)[('931120', '160')]['status'], 'pending')

    def test_reconciliation_uses_softech_net_after_our_runs(self):
        self.b.net_after = Decimal('199.20'); self.b.save()
        with mock.patch('apps.insurance.invoice_builder._effective_rx_values',
                        side_effect=lambda rx, claim: {'net_after': rx.net_after}):
            before = compute_softech_gross_reconciliation(self.claim)
            row = next(r for r in before['prescriptions'] if r['docnumber'] == '931120')
            self.assertEqual(row['softech_status'], 'pending')
            self.assertTrue(row['sequence'])
            self._applied_run('931120', {'111062': '240'}, '199.20')
            after = compute_softech_gross_reconciliation(self.claim)
        self.assertFalse(any(r['docnumber'] == '931120' for r in after['prescriptions']))
        self.assertEqual(after['fixed_by_softech'], 1)

    def test_preview_skips_items_softech_already_has(self):
        lines = {('930593', '160'): [_line('80052', '210'), _line('124793', '700')],
                 ('931120', '160'): [_line('111062', '240')]}
        header = {'docvalue': Decimal('747'), 'docvalue1': Decimal('900'), 'docvalue2': Decimal('0'),
                  'docvalue3': Decimal('0'), 'cust_branch_code': '4227', 'trans_time': None}
        user = get_user_model().objects.create_user(username='cs', password='x')
        with mock.patch('apps.insurance.importer._get_connection'), \
             mock.patch.object(rs, '_read_receipt', side_effect=lambda c, d, b, k: (lines[(d, b)], header)):
            receipts, info = catalog_sync_receipts(self.claim)
            plan = rs.preview_plan(self.claim, receipts, user=user, source='catalog', skip_matching=True, info=info)
        self.assertEqual(plan.receipt_count, 1)
        self.assertEqual(plan.plan[0], {'docno': '930593', 'branch': '160', 'prices': {'124793': '770.00'}})
        self.assertEqual(plan.preview['already_in_softech'], {'receipts': 1, 'items': 2})
