"""
apps/tests/test_reconciliation_reports.py

Finance reports (apps/finance/recon_reports.py): unpaid-invoice split (covered /
under review / no voucher) and incomplete payments (part-paid invoices + part-used
vouchers), plus the Excel builders. PostgreSQL only.
"""
from datetime import date
from decimal import Decimal as D

from django.test import TestCase

from apps.finance import recon_reports as R
from apps.finance.models import ReconParty, APInvoice, Payment, Allocation, MatchCandidate


class ReportTests(TestCase):

    def setUp(self):
        self.party = ReconParty.objects.create(party_type='supplier', softech_personcode='4471', name='مورد')

    def inv(self, no, value, paid='0'):
        return APInvoice.objects.create(party=self.party, branchcode='130', doccode='10',
                                        docnumber=str(no), docdate=date(2026, 8, 1),
                                        doc_value=D(value), doc_value_pay=D(paid), party_type='supplier')

    def pay(self, no, amount):
        return Payment.objects.create(party=self.party, branchcode='130', cheqsno=no, direction='out',
                                      party_type='supplier', voucher_date=date(2026, 8, 10),
                                      amount=D(amount), is_unallocated=True)

    def test_unpaid_split(self):
        covered = self.inv(1, '500')
        review = self.inv(2, '300')
        self.inv(3, '200')                                    # nothing covers it
        self.inv(4, '100', paid='100')                        # already paid in SOFTECH
        Allocation.objects.create(payment=self.pay(10, '500'), invoice=covered, amount=D('500'),
                                  origin=Allocation.ORIGIN_APPROVED)
        MatchCandidate.objects.create(party=self.party, invoice=review, payment=self.pay(11, '300'),
                                      proposed_amount=D('300'), confidence_class='low')
        rows = {r['docnumber']: r for r in R.unpaid_invoices()}
        self.assertNotIn('4', rows)
        self.assertEqual(rows['1']['matched_approved'], D('500'))
        self.assertEqual(rows['1']['unpaid_uncovered'], D('0'))
        self.assertEqual(rows['2']['under_review'], D('300'))
        self.assertEqual(rows['3']['unpaid_uncovered'], D('200'))
        s = R.supplier_summary(list(rows.values()))[0]
        self.assertEqual(s['unpaid_uncovered'], D('200'))
        self.assertEqual(s['unpaid_invoices'], 1)

    def test_partial_payments(self):
        part = self.inv(1, '1000')
        v1, v2 = self.pay(10, '300'), self.pay(11, '250')
        Allocation.objects.create(payment=v1, invoice=part, amount=D('300'), origin=Allocation.ORIGIN_WRITTEN)
        Allocation.objects.create(payment=v2, invoice=part, amount=D('200'), origin=Allocation.ORIGIN_APPROVED)
        full = self.inv(2, '400')
        Allocation.objects.create(payment=self.pay(12, '400'), invoice=full, amount=D('400'),
                                  origin=Allocation.ORIGIN_SOFTECH)
        inv_rows, pay_rows = R.partial_payments()
        self.assertEqual([r['docnumber'] for r in inv_rows], ['1'])
        r = inv_rows[0]
        self.assertEqual(r['paid'], D('500'))
        self.assertEqual(r['remaining'], D('500'))
        self.assertEqual(r['vouchers_count'], 2)
        self.assertIn('بانتظار الكتابة', r['vouchers'])
        self.assertEqual([p['voucher'] for p in pay_rows], ['130/11'])   # 250 voucher, 200 used
        self.assertEqual(pay_rows[0]['unallocated'], D('50'))

    def test_excel_builders(self):
        self.inv(3, '200')
        for build in (R.build_unpaid_xlsx, R.build_review_xlsx, R.build_partial_xlsx,
                      R.build_returns_chains_xlsx):
            data = build()
            self.assertTrue(data.startswith(b'PK'))        # a real xlsx (zip) payload
