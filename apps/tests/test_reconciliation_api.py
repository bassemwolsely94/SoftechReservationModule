"""
apps/tests/test_reconciliation_api.py

Phase-C batch 4 — read-only reconciliation API (apps/finance/recon_views.py).
Auth-gated; verifies dashboard KPIs, candidate/exception lists + filters, the
workbench 3-pane payload, and the per-party حصر ledger equation. No SOFTECH.
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status

from apps.finance import recon_engine as E
from apps.finance.models import (
    ReconParty, APInvoice, Payment, Allocation, MatchCandidate, ReconException,
)
from .factories import make_admin

BASE = '/api/finance/reconciliation'


def _seed():
    party = ReconParty.objects.create(
        party_type='supplier', softech_personcode='4471', name='مورد',
        opening_balance=Decimal('0'), softech_balance=Decimal('-743.40'),
    )
    inv = APInvoice.objects.create(
        party=party, branchcode='130', doccode='10', docnumber='12207',
        docdate=date(2026, 8, 15), docnumber2='5213', doc_value=Decimal('743.40'),
        doc_value_pay=Decimal('0'), party_type='supplier',
    )
    pay = Payment.objects.create(
        party=party, branchcode='130', cheqsno=51703, direction='out',
        party_type='supplier', voucher_date=date(2026, 9, 18),
        amount=Decimal('743.40'), note='مورد 12207', is_unallocated=True,
    )
    return party, inv, pay


class ReconApiAuthTests(TestCase):

    def test_dashboard_requires_auth(self):
        resp = APIClient().get(f'{BASE}/dashboard/')
        self.assertIn(resp.status_code, (status.HTTP_401_UNAUTHORIZED,
                                         status.HTTP_403_FORBIDDEN))


class ReconApiTests(TestCase):

    def setUp(self):
        _, self.profile, self.client = make_admin('recon_admin')
        self.party, self.inv, self.pay = _seed()
        E.run_matching(party_type='supplier')   # populate candidates + exceptions

    def test_dashboard_kpis(self):
        resp = self.client.get(f'{BASE}/dashboard/')
        self.assertEqual(resp.status_code, 200)
        d = resp.json()
        self.assertEqual(d['invoices']['count'], 1)
        self.assertEqual(Decimal(str(d['invoices']['value'])), Decimal('743.40'))
        self.assertEqual(d['payments']['unallocated_count'], 1)
        self.assertGreaterEqual(d['candidates']['total'], 1)
        self.assertIn('high', d['candidates']['by_confidence'])

    def test_candidates_list_and_filter(self):
        resp = self.client.get(f'{BASE}/candidates/', {'confidence_class': 'high'})
        self.assertEqual(resp.status_code, 200)
        results = resp.json()['results']
        self.assertGreaterEqual(len(results), 1)
        c = results[0]
        # evidence + nested details present for the workbench
        self.assertTrue(c['evidence'])
        self.assertEqual(c['invoice_detail']['docnumber'], '12207')
        self.assertEqual(c['payment_detail']['cheqsno'], 51703)
        self.assertEqual(c['confidence_class'], 'high')

    def test_candidates_filter_by_personcode(self):
        resp = self.client.get(f'{BASE}/candidates/', {'personcode': '9999'})
        self.assertEqual(resp.json()['count'], 0)

    def test_workbench_by_invoice(self):
        resp = self.client.get(f'{BASE}/workbench/', {'invoice': self.inv.id})
        self.assertEqual(resp.status_code, 200)
        d = resp.json()
        self.assertEqual(d['focus'], 'invoice')
        self.assertEqual(d['invoice']['docnumber'], '12207')
        self.assertGreaterEqual(len(d['candidates']), 1)

    def test_workbench_by_payment(self):
        resp = self.client.get(f'{BASE}/workbench/', {'payment': self.pay.id})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['focus'], 'payment')

    def test_workbench_needs_param(self):
        resp = self.client.get(f'{BASE}/workbench/')
        self.assertEqual(resp.status_code, 400)

    def test_party_ledger_equation(self):
        resp = self.client.get(f'{BASE}/parties/4471/ledger/')
        self.assertEqual(resp.status_code, 200)
        eq = resp.json()['equation']
        # opening 0 + purchases 743.40 - returns 0 - payments 743.40 = 0
        self.assertEqual(Decimal(str(eq['purchases'])), Decimal('743.40'))
        self.assertEqual(Decimal(str(eq['payments'])), Decimal('743.40'))
        self.assertEqual(Decimal(str(eq['expected_closing'])), Decimal('0.00'))

    def test_party_ledger_404(self):
        resp = self.client.get(f'{BASE}/parties/0000/ledger/')
        self.assertEqual(resp.status_code, 404)

    def test_payments_unallocated_filter(self):
        resp = self.client.get(f'{BASE}/payments/', {'unallocated': '1'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['count'], 1)

    def test_exceptions_list(self):
        # the seeded voucher references invoice 12207 → it gets matched, so the
        # orphan case does not fire; add a truly orphan payment to assert the feed.
        Payment.objects.create(
            party=self.party, branchcode='130', cheqsno=99999, direction='out',
            party_type='supplier', voucher_date=date(2026, 9, 1),
            amount=Decimal('55.00'), note='بدون مرجع', is_unallocated=True,
        )
        E.run_matching(party_type='supplier')
        resp = self.client.get(f'{BASE}/exceptions/', {'exception_type': 'orphan_payment'})
        self.assertEqual(resp.status_code, 200)
        self.assertGreaterEqual(resp.json()['count'], 1)

    def test_parties_list(self):
        resp = self.client.get(f'{BASE}/parties/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['count'], 1)
