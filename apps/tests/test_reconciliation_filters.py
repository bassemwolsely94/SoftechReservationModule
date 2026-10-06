"""
apps/tests/test_reconciliation_filters.py

Shared filters (apps/finance/recon_filters.py): multi-select suppliers, SEPARATE
invoice-date and payment-date ranges, document value range — applied the same way
to lists, reports and bulk actions.
"""
from datetime import date
from decimal import Decimal as D

from django.test import TestCase
from django.http import QueryDict

from apps.finance import recon_filters as RF, recon_actions as A, recon_reports as R
from apps.finance.models import ReconParty, APInvoice, Payment, MatchCandidate


class FilterTests(TestCase):

    def setUp(self):
        self.a = ReconParty.objects.create(party_type='supplier', softech_personcode='100', name='A')
        self.b = ReconParty.objects.create(party_type='supplier', softech_personcode='200', name='B')
        self.c = ReconParty.objects.create(party_type='supplier', softech_personcode='300', name='C')
        self.ia = self.inv(self.a, 1, date(2026, 1, 10), '500')
        self.ib = self.inv(self.b, 2, date(2026, 3, 10), '1500')
        self.ic = self.inv(self.c, 3, date(2026, 5, 10), '50')
        self.pa = self.pay(self.a, 11, date(2026, 6, 1), '500')      # paid LATER than invoiced
        self.pb = self.pay(self.b, 12, date(2026, 3, 12), '1500')

    def inv(self, party, no, d, v):
        return APInvoice.objects.create(party=party, branchcode='130', doccode='10', docnumber=str(no),
                                        docdate=d, doc_value=D(v), doc_value_pay=D('0'),
                                        party_type='supplier', source_hash='x')

    def pay(self, party, no, d, v):
        return Payment.objects.create(party=party, branchcode='130', cheqsno=no, direction='out',
                                      party_type='supplier', voucher_date=d, amount=D(v), is_unallocated=True)

    def f(self, **kw):
        q = QueryDict(mutable=True)
        q.update(kw)
        return RF.parse(q, 'supplier')

    def test_multi_select_suppliers(self):
        qs = RF.apply(APInvoice.objects.all(), self.f(personcodes='100,300'), 'invoice')
        self.assertEqual(set(qs.values_list('id', flat=True)), {self.ia.id, self.ic.id})

    def test_legacy_single_personcode_still_works(self):
        qs = RF.apply(APInvoice.objects.all(), self.f(personcode='200'), 'invoice')
        self.assertEqual(list(qs.values_list('id', flat=True)), [self.ib.id])

    def test_invoice_and_payment_dates_are_distinct(self):
        f = self.f(inv_date_from='2026-01-01', inv_date_to='2026-01-31')
        self.assertEqual(list(RF.apply(APInvoice.objects.all(), f, 'invoice').values_list('id', flat=True)),
                         [self.ia.id])
        # an invoice-date filter must not touch the payment list
        self.assertEqual(RF.apply(Payment.objects.all(), f, 'payment').count(), 2)
        g = self.f(pay_date_from='2026-06-01')
        self.assertEqual(list(RF.apply(Payment.objects.all(), g, 'payment').values_list('id', flat=True)),
                         [self.pa.id])
        self.assertEqual(RF.apply(APInvoice.objects.all(), g, 'invoice').count(), 3)

    def test_match_needs_both_sides_when_both_set(self):
        ca = MatchCandidate.objects.create(party=self.a, invoice=self.ia, payment=self.pa, proposed_amount=D('500'))
        cb = MatchCandidate.objects.create(party=self.b, invoice=self.ib, payment=self.pb, proposed_amount=D('1500'))
        f = self.f(inv_date_from='2026-01-01', inv_date_to='2026-01-31', pay_date_from='2026-06-01')
        self.assertEqual(list(RF.apply(MatchCandidate.objects.all(), f, 'candidate').values_list('id', flat=True)),
                         [ca.id])
        f2 = self.f(inv_date_from='2026-01-01', inv_date_to='2026-01-31', pay_date_to='2026-05-31')
        self.assertEqual(RF.apply(MatchCandidate.objects.all(), f2, 'candidate').count(), 0)

    def test_value_range(self):
        qs = RF.apply(APInvoice.objects.all(), self.f(amount_min='100', amount_max='1000'), 'invoice')
        self.assertEqual(list(qs.values_list('id', flat=True)), [self.ia.id])

    def test_report_honours_filters(self):
        rows = R.unpaid_invoices(f=self.f(personcodes='200'))
        self.assertEqual({r['docnumber'] for r in rows}, {'2'})

    def test_bulk_approve_only_touches_filtered(self):
        ca = MatchCandidate.objects.create(party=self.a, invoice=self.ia, payment=self.pa,
                                           proposed_amount=D('500'), confidence_class='high')
        cb = MatchCandidate.objects.create(party=self.b, invoice=self.ib, payment=self.pb,
                                           proposed_amount=D('1500'), confidence_class='high')
        A.bulk_approve(party_type='supplier', confidence_class='high', f=self.f(personcodes='200'))
        ca.refresh_from_db(); cb.refresh_from_db()
        self.assertEqual((ca.status, cb.status), ('proposed', 'approved'))
