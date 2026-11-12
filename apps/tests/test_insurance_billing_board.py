"""
«فئات الفوترة» board (apps/insurance/billing_board.py) and «أصناف المطالبة» Excel
(apps/insurance/claim_items_export.py): a receipt never leaves another group silently,
deleting a group frees its receipts, auto-assign takes only the unassigned, every change
is audited, and the items export covers one motalba or several.
"""
import io
from datetime import date
from decimal import Decimal

import openpyxl
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.insurance import models as m
from apps.insurance.billing_board import build_board
from apps.insurance.claim_items_export import combine

_n = iter(range(7000, 99999))


def _claim(name='جهة أ', **kw):
    c = m.InsuranceClient.objects.create(name=name)
    sub = m.InsuranceSubClient.objects.create(client=c, name='العاملين')
    return m.InsuranceClaim.objects.create(claim_number=f'MT-B-{next(_n)}', subclient=sub,
                                           period_from=date(2026, 10, 1), period_to=date(2026, 10, 31), **kw)


def _rx(claim, net, lines=()):
    rx = m.InsuranceClaimPrescription.objects.create(
        claim=claim, softech_docnumber=str(next(_n)), softech_branchcode='160', softech_docdate=date(2026, 10, 5),
        patient_name=f'مريض {next(_n)}', net_after=Decimal(net), gross_before=Decimal(net))
    for code, cat, gross, net_l in lines:
        m.InsuranceClaimLine.objects.create(prescription=rx, softech_itemcode=code, item_name=f'صنف {code}',
                                            item_category=cat, quantity=1, line_total=Decimal(gross),
                                            discount_amt=Decimal(gross) - Decimal(net_l), net_amount=Decimal(net_l))
    return rx


class BillingBoardTests(TestCase):
    def setUp(self):
        self.claim = _claim()
        self.a = m.InsuranceClaimBillingGroup.objects.create(claim=self.claim, code='A', name='أ')
        self.b = m.InsuranceClaimBillingGroup.objects.create(claim=self.claim, code='B', name='ب')
        self.r1, self.r2, self.r3 = _rx(self.claim, 100), _rx(self.claim, 50), _rx(self.claim, 30)
        u = get_user_model().objects.create_user(username='bb', password='x', is_staff=True, is_superuser=True)
        self.api = APIClient()
        self.api.force_authenticate(u)

    def _assign(self, group, ids, move=False):
        return self.api.post(f'/api/insurance/billing-groups/{group.pk}/assign-rx/',
                             {'prescription_ids': ids, 'move': move}, format='json')

    def test_board_rows_groups_and_balance(self):
        self._assign(self.a, [self.r1.pk])
        b = build_board(self.claim)
        self.assertEqual(len(b['rows']), 3)
        self.assertEqual(b['totals']['unassigned_count'], 2)
        self.assertEqual(b['totals']['unassigned_net'], 80.0)
        self.assertEqual(next(g for g in b['groups'] if g['id'] == self.a.pk)['net_after'], 100.0)
        self.assertTrue(b['totals']['balanced'])
        r = self.api.get(f'/api/insurance/claims/{self.claim.pk}/billing-board/')
        self.assertEqual(r.status_code, 200)

    def test_receipt_in_other_group_never_moves_silently(self):
        self._assign(self.a, [self.r1.pk])
        r = self._assign(self.b, [self.r1.pk, self.r2.pk])
        self.assertEqual(r.status_code, 409)
        self.assertEqual([c['key'] for c in r.json()['conflicts']], [f'p{self.r1.pk}'])
        self.r1.refresh_from_db(); self.r2.refresh_from_db()
        self.assertEqual((self.r1.billing_group_id, self.r2.billing_group_id), (self.a.pk, None))
        r = self._assign(self.b, [self.r1.pk, self.r2.pk], move=True)
        self.assertEqual(r.status_code, 200)
        self.r1.refresh_from_db(); self.a.refresh_from_db(); self.b.refresh_from_db()
        self.assertEqual(self.r1.billing_group_id, self.b.pk)
        self.assertEqual((self.a.net_after, self.b.net_after), (Decimal('0'), Decimal('150')))   # both re-totalled
        self.assertTrue(self.claim.audit_events.filter(action='billing_group').exists())

    def test_delete_group_frees_its_receipts(self):
        self._assign(self.a, [self.r1.pk, self.r2.pk])
        r = self.api.delete(f'/api/insurance/billing-groups/{self.a.pk}/')
        self.assertEqual((r.status_code, r.json()['freed']), (200, 2))
        self.assertEqual(build_board(self.claim)['totals']['unassigned_count'], 3)

    def test_auto_assign_takes_only_unassigned_and_excluded_stay_out(self):
        self._assign(self.a, [self.r1.pk])
        m.InsuranceClaimExclusion.objects.create(prescription=self.r3, reason='خارج')
        r = self.api.post(f'/api/insurance/billing-groups/{self.b.pk}/auto-assign/')
        self.assertEqual(r.json()['assigned'], 1)          # only r2: r1 is in A, r3 excluded
        self.r1.refresh_from_db()
        self.assertEqual(self.r1.billing_group_id, self.a.pk)
        self.assertEqual(len(build_board(self.claim)['rows']), 2)

    def test_unassign_selected(self):
        self._assign(self.a, [self.r1.pk, self.r2.pk])
        r = self.api.post(f'/api/insurance/billing-groups/{self.a.pk}/unassign-rx/',
                          {'prescription_ids': [self.r2.pk]}, format='json')
        self.assertEqual(r.json()['unassigned'], 1)
        self.a.refresh_from_db()
        self.assertEqual(self.a.net_after, Decimal('100'))

    def test_locked_claim_refuses_changes(self):
        self.claim.status = 'submitted'; self.claim.save()
        self.assertEqual(self._assign(self.a, [self.r1.pk]).status_code, 423)
        self.assertEqual(self.api.delete(f'/api/insurance/billing-groups/{self.a.pk}/').status_code, 423)


class ClaimItemsExportTests(TestCase):
    def setUp(self):
        self.c1 = _claim('جهة أ')
        self.c2 = _claim('جهة ب')
        _rx(self.c1, 90, [('A', 'local', 100, 90), ('B', 'imported', 50, 45)])
        _rx(self.c2, 80, [('A', 'local', 80, 72)])
        u = get_user_model().objects.create_user(username='ie', password='x', is_staff=True, is_superuser=True)
        self.api = APIClient()
        self.api.force_authenticate(u)

    def test_combine_sums_items_across_motalbas(self):
        from apps.insurance.discrepancy import claim_items_for_revision
        rows = combine([(c, claim_items_for_revision(c)['items']) for c in (self.c1, self.c2)])
        a = next(r for r in rows if r['item_code'] == 'A')
        self.assertEqual((a['gross'], a['net'], a['motalba_count'], a['line_count']), (180.0, 162.0, 2, 2))
        self.assertEqual(a['discount_pct'], 10.0)

    def test_single_motalba_export(self):
        r = self.api.get(f'/api/insurance/claims/{self.c1.pk}/claim-items/', {'format': 'xlsx'})
        self.assertEqual(r.status_code, 200)
        wb = openpyxl.load_workbook(io.BytesIO(r.content))
        self.assertEqual(wb.sheetnames, ['أصناف المطالبة'])

    def test_multi_motalba_export_only_ticked(self):
        r = self.api.get('/api/insurance/portfolio/', {'from': '2026-10-01', 'to': '2026-10-31',
                                                       'format': 'items_xlsx', 'claim_ids': f'{self.c2.pk},{self.c1.pk}'})
        self.assertEqual(r.status_code, 200)
        wb = openpyxl.load_workbook(io.BytesIO(r.content))
        self.assertEqual(wb.sheetnames, ['مجمع', 'تفصيلى'])
        detail = [c.value for c in wb['تفصيلى']['B'] if c.value]
        self.assertEqual(detail[1], self.c2.claim_number)        # the ticked order is kept
