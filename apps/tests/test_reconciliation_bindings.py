"""
apps/tests/test_reconciliation_bindings.py

Owner decisions 2026-09-29 (doc 23 §21): a مقبوضات that refunds part of a مدفوعات is bound
to it and the payment is matched NET; a receipt naming a purchase invoice is bound +
flagged for a decision (numbers unchanged); returns referencing a purchase reduce its
«الصافي بعد المرتجع»; chain partners are readable on every chain member.
"""
from datetime import date
from decimal import Decimal as D

from django.test import TestCase

from apps.finance import recon_engine as E
from apps.finance.models import (APInvoice, MatchCandidate, Payment, ReconException, ReconParty,
                                 ReturnLink)
from apps.finance.recon_bindings import bind_all


def _party():
    return ReconParty.objects.create(party_type='supplier', softech_personcode='4471', name='مورد')


def _inv(p, no, value, d=date(2026, 6, 28), is_return=False, paid='0'):
    return APInvoice.objects.create(party=p, branchcode='130', doccode='120' if is_return else '10',
                                    docnumber=no, docdate=d, doc_value=D(value), doc_value_pay=D(paid),
                                    party_type='supplier', is_return=is_return, source_hash='x')


def _v(p, sno, amount, cheqtype='20', note='', cheqno='', d=date(2026, 6, 29)):
    return Payment.objects.create(party=p, branchcode='130', cheqsno=sno, cheqtype=cheqtype, direction='out',
                                  party_type='supplier', voucher_date=d, amount=D(amount), note=note,
                                  cheqno=cheqno, is_unallocated=True)


class BindingTests(TestCase):

    def setUp(self):
        self.p = _party()

    def test_refund_binds_to_payment_and_payment_is_matched_net(self):
        # owner case 130/50400 11,954 − receipt 50401 10,780 = 1,174 = invoice 11954
        inv = _inv(self.p, '11954', '1174')
        pay = _v(self.p, 50400, '11954', note='مخزن الكرمة فاتورة 11954')
        rec = _v(self.p, 50401, '10780', cheqtype='10', note='مقبوضات رقم 50400')
        bind_all('supplier')
        pay.refresh_from_db(); rec.refresh_from_db()
        self.assertEqual(rec.bound_payment_id, pay.id)
        self.assertEqual(pay.net_amount, D('1174'))
        self.assertIn('50401', pay.bind_note)
        E.run_matching(party_type='supplier')
        c = MatchCandidate.objects.get(invoice=inv, payment=pay, status='proposed')
        self.assertEqual(c.proposed_amount, D('1174'))
        self.assertEqual(c.confidence_class, MatchCandidate.CONF_HIGH)   # exact NET + reference

    def test_receipt_naming_a_purchase_is_bound_and_flagged_numbers_unchanged(self):
        inv = _inv(self.p, '32016', '211', d=date(2026, 9, 14))
        rec = _v(self.p, 62468, '211', cheqtype='10', cheqno='32016', d=date(2026, 9, 14))
        bind_all('supplier')
        rec.refresh_from_db(); inv.refresh_from_db()
        self.assertEqual(rec.bound_invoice_id, inv.id)
        self.assertTrue(ReconException.objects.filter(exception_type='receipt_on_invoice', status='open',
                                                      payment=rec, invoice=inv).exists())
        self.assertEqual(inv.remaining_calc, D('211'))                  # not changed until decided
        self.assertEqual(rec.unallocated_amount, 0)                     # explained, not orphan

    def test_open_return_referencing_a_purchase_reduces_its_net(self):
        inv = _inv(self.p, '500', '1000')
        ret = _inv(self.p, '77', '300', is_return=True)
        ReturnLink.objects.create(return_invoice=ret, purchase_invoice=inv, purchase_branchcode='130',
                                  purchase_docnumber='500', amount=D('300'))
        inv = APInvoice.objects.get(pk=inv.pk)
        self.assertEqual(inv.remaining_calc, D('1000'))
        self.assertEqual(inv.open_return_credit, D('300'))
        self.assertEqual(inv.net_remaining, D('700'))

    def test_chain_partners_are_readable(self):
        a = _v(self.p, 1, '500', d=date(2026, 9, 1))
        b = _v(self.p, 2, '500', cheqtype='10', d=date(2026, 9, 2))
        Payment.objects.filter(pk=a.pk).update(chain_role='reversed', chain_key='K1')
        Payment.objects.filter(pk=b.pk).update(chain_role='reversal', chain_key='K1')
        bind_all('supplier')
        a.refresh_from_db()
        self.assertIn('130/2', a.chain_partners)

    def test_bindings_are_idempotent_and_clear_when_gone(self):
        pay = _v(self.p, 50400, '11954')
        rec = _v(self.p, 50401, '10780', cheqtype='10', note='رقم 50400')
        bind_all('supplier'); bind_all('supplier')
        pay.refresh_from_db()
        self.assertEqual(pay.refunded_amount, D('10780'))                # not doubled
        Payment.objects.filter(pk=rec.pk).update(note='', cheqno='')
        bind_all('supplier')
        pay.refresh_from_db()
        self.assertEqual(pay.refunded_amount, D('0'))
