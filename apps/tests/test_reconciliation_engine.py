"""
apps/tests/test_reconciliation_engine.py

Phase-C batch 3 — the matching engine (apps/finance/recon_engine.py). Pure scoring
+ DB-backed run_matching, no SOFTECH. Uses the real golden shape (invoice 12207 /
voucher note "مورد 12207" / 743.40) plus the multi-invoice / multi-payment /
conflict / anomaly cases from §10–§13.
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase

from apps.finance import recon_engine as E
from apps.finance.models import (
    ReconParty, APInvoice, Payment, MatchCandidate, MatchEvidence, ReconException,
)


def _party(pc='4471', pt='supplier'):
    return ReconParty.objects.create(party_type=pt, softech_personcode=pc, name='مورد')


def _inv(party, docnumber='12207', value='743.40', docdate=date(2026, 8, 15),
         branch='130', docnumber2='5213'):
    return APInvoice.objects.create(
        party=party, branchcode=branch, doccode='10', docnumber=docnumber,
        docdate=docdate, docnumber2=docnumber2, doc_value=Decimal(value),
        doc_value_pay=Decimal('0'), party_type=party.party_type,
    )


def _pay(party, cheqsno, amount='743.40', note='مورد 12207',
         vdate=date(2026, 9, 18), branch='130', unalloc=True):
    return Payment.objects.create(
        party=party, branchcode=branch, cheqsno=cheqsno, direction='out',
        party_type=party.party_type, voucher_date=vdate, amount=Decimal(amount),
        note=note, is_unallocated=unalloc,
    )


# ── pure scoring ──────────────────────────────────────────────────────────────

class ScoringTests(TestCase):

    def test_number_tokens_leading_zeros(self):
        toks = E.number_tokens('فاتورة 001254 ف 12207')
        self.assertIn('001254', toks)
        self.assertIn('1254', toks)      # stripped variant
        self.assertIn('12207', toks)
        self.assertNotIn('12', E.number_tokens('ف 12'))   # too short

    def test_golden_scores_100_high(self):
        p = _party()
        inv, pay = _inv(p), _pay(p, 51703)
        score, ev = E.score_candidate(inv, pay, Decimal('743.40'), Decimal('743.40'))
        self.assertEqual(score, Decimal('100.00'))
        self.assertEqual(E.classify(score), MatchCandidate.CONF_HIGH)
        signals = {e['signal']: e['outcome'] for e in ev}
        self.assertEqual(signals['amount'], 'exact')
        self.assertEqual(signals['reference'], 'exact')
        self.assertEqual(signals['branch'], 'exact')

    def test_partial_amount_lowers_score(self):
        p = _party()
        inv = _inv(p, value='1000')
        pay = _pay(p, 1, amount='400', note='no ref')
        score, ev = E.score_candidate(inv, pay, Decimal('1000'), Decimal('400'))
        amount_ev = next(e for e in ev if e['signal'] == 'amount')
        self.assertEqual(amount_ev['outcome'], 'approximate')
        self.assertLess(score, Decimal('85'))

    def test_reference_carries_confidence_without_amount(self):
        p = _party()
        inv = _inv(p, docnumber='12207', value='1000')
        pay = _pay(p, 1, amount='300', note='دفعة ف 12207')   # partial but ref-exact
        score, ev = E.score_candidate(inv, pay, Decimal('1000'), Decimal('300'))
        ref = next(e for e in ev if e['signal'] == 'reference')
        self.assertEqual(ref['outcome'], 'exact')
        self.assertGreaterEqual(score, Decimal('60'))   # ref+temporal+branch keep it ≥ medium


# ── DB-backed run_matching ────────────────────────────────────────────────────

class RunMatchingTests(TestCase):

    def test_golden_proposal_persisted(self):
        p = _party()
        inv, pay = _inv(p), _pay(p, 51703)
        run = E.run_matching(party_type='supplier')
        self.assertEqual(run.mode, 'suggest')
        cand = MatchCandidate.objects.get(invoice=inv, payment=pay)
        self.assertEqual(cand.status, MatchCandidate.STATUS_PROPOSED)
        self.assertEqual(cand.confidence_class, MatchCandidate.CONF_HIGH)
        self.assertEqual(cand.proposed_amount, Decimal('743.400'))
        self.assertEqual(cand.rules_version, 'v1')
        self.assertTrue(cand.evidence.exists())

    def test_one_payment_covers_many_invoices(self):
        p = _party()
        a = _inv(p, docnumber='111', value='400')
        b = _inv(p, docnumber='222', value='600')
        pay = _pay(p, 1, amount='1000', note='فواتير 111 و 222')
        E.run_matching(party_type='supplier')
        ca = MatchCandidate.objects.get(invoice=a, payment=pay)
        cb = MatchCandidate.objects.get(invoice=b, payment=pay)
        self.assertEqual(ca.status, MatchCandidate.STATUS_PROPOSED)
        self.assertEqual(cb.status, MatchCandidate.STATUS_PROPOSED)
        # capacity split, no false conflict
        self.assertEqual(ca.proposed_amount + cb.proposed_amount, Decimal('1000.000'))
        self.assertNotEqual(ca.confidence_class, MatchCandidate.CONF_CONFLICT)

    def test_many_payments_one_invoice(self):
        p = _party()
        inv = _inv(p, docnumber='30000', value='1000')
        p1 = _pay(p, 1, amount='600', note='ف 30000')
        p2 = _pay(p, 2, amount='400', note='ف 30000', vdate=date(2026, 9, 20))
        E.run_matching(party_type='supplier')
        c1 = MatchCandidate.objects.get(invoice=inv, payment=p1)
        c2 = MatchCandidate.objects.get(invoice=inv, payment=p2)
        self.assertEqual(c1.proposed_amount + c2.proposed_amount, Decimal('1000.000'))

    def test_conflict_two_full_payments_same_invoice(self):
        p = _party()
        inv = _inv(p, docnumber='12207', value='743.40')
        p1 = _pay(p, 1, amount='743.40', note='ف 12207', vdate=date(2026, 9, 18))
        p2 = _pay(p, 2, amount='743.40', note='ف 12207', vdate=date(2026, 9, 25))
        E.run_matching(party_type='supplier')
        c1 = MatchCandidate.objects.get(invoice=inv, payment=p1)
        c2 = MatchCandidate.objects.get(invoice=inv, payment=p2)
        self.assertEqual(c1.confidence_class, MatchCandidate.CONF_CONFLICT)
        self.assertEqual(c2.confidence_class, MatchCandidate.CONF_CONFLICT)

    def test_weak_same_amount_voucher_is_not_a_conflict(self):
        # owner case 160/32325: the voucher names the invoice (100) — an old voucher of the
        # same amount with no reference (50) must not turn the clear winner into «تعارض»
        p = _party()
        inv = _inv(p, docnumber='12207', value='743.40')
        good = _pay(p, 1, amount='743.40', note='ف 12207', vdate=date(2026, 8, 16))
        _pay(p, 2, amount='743.40', note='', vdate=date(2023, 1, 10))
        E.run_matching(party_type='supplier')
        c = MatchCandidate.objects.get(invoice=inv, payment=good)
        self.assertNotEqual(c.confidence_class, MatchCandidate.CONF_CONFLICT)
        self.assertEqual(c.confidence_class, MatchCandidate.CONF_HIGH)

    def test_voucher_is_locked_to_the_invoice_it_names(self):
        # owner case supplier 4471: identical 630 invoices; the voucher's serial names 30841 —
        # no strategy may hand it to the older 30720 (they had, shifting links one back)
        p = _party()
        older = _inv(p, docnumber='30720', value='630')
        named = _inv(p, docnumber='30841', value='630')
        pay = _pay(p, 60730, amount='630', note='', vdate=date(2026, 8, 1))
        Payment.objects.filter(pk=pay.pk).update(cheqno='30841')
        E.run_matching(party_type='supplier')
        props = MatchCandidate.objects.filter(payment=pay, status='proposed')
        self.assertEqual({c.invoice_id for c in props}, {named.id})
        self.assertFalse(MatchCandidate.objects.filter(payment=pay, invoice=older, status='proposed').exists())

    def test_idempotent_reruns(self):
        p = _party()
        _inv(p); _pay(p, 51703)
        E.run_matching(party_type='supplier')
        n1 = MatchCandidate.objects.count()
        E.run_matching(party_type='supplier')
        self.assertEqual(MatchCandidate.objects.count(), n1)  # proposals replaced, not duplicated

    def test_scope_by_personcode(self):
        p1 = _party(pc='4471')
        p2 = _party(pc='5000')
        _inv(p1); _pay(p1, 1)
        _inv(p2, docnumber='888'); _pay(p2, 2, note='ف 888', amount='743.40')
        E.run_matching(personcode='4471')
        self.assertTrue(MatchCandidate.objects.filter(party=p1).exists())
        self.assertFalse(MatchCandidate.objects.filter(party=p2).exists())


# ── anomaly emission ──────────────────────────────────────────────────────────

class ExceptionTests(TestCase):

    def test_orphan_payment(self):
        p = _party()
        # a payment with a note that matches no invoice, and no invoices at all
        _pay(p, 99, note='بدون مرجع', amount='123.45')
        E.run_matching(party_type='supplier')
        self.assertTrue(ReconException.objects.filter(
            party=p, exception_type=ReconException.TYPE_ORPHAN_PAYMENT).exists())

    def test_duplicate_payment(self):
        p = _party()
        _pay(p, 1, amount='500', note='x', vdate=date(2026, 9, 1))
        _pay(p, 2, amount='500', note='x', vdate=date(2026, 9, 1))
        E.run_matching(party_type='supplier')
        exc = ReconException.objects.filter(
            party=p, exception_type=ReconException.TYPE_DUPLICATE_PAYMENT)
        self.assertTrue(exc.exists())
        self.assertEqual(exc.first().severity, 'critical')

    def test_same_day_same_amount_naming_different_invoices_is_not_a_duplicate(self):
        # contract supplier 4471: two 630 vouchers the same day, each naming its own invoice
        p = _party()
        a = _pay(p, 60920, amount='630', note='', vdate=date(2026, 8, 6))
        b = _pay(p, 60950, amount='630', note='', vdate=date(2026, 8, 6))
        Payment.objects.filter(pk=a.pk).update(cheqno='30968')
        Payment.objects.filter(pk=b.pk).update(cheqno='30993')
        E.run_matching(party_type='supplier')
        self.assertFalse(ReconException.objects.filter(
            party=p, exception_type=ReconException.TYPE_DUPLICATE_PAYMENT, status='open').exists())

    def test_unpaid_old_invoice(self):
        p = _party()
        _inv(p, docnumber='777', value='900', docdate=date(2024, 1, 1))
        E.run_matching(party_type='supplier')
        self.assertTrue(ReconException.objects.filter(
            party=p, exception_type=ReconException.TYPE_UNPAID_OLD).exists())
