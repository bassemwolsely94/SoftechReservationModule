"""
apps/tests/test_reconciliation_allocator.py

Max-allocation pass (apps/finance/recon_allocator.py): each strategy in isolation
(pure), the ordering/capacity rules, and the integration into run_matching.
No SOFTECH.
"""
from datetime import date, timedelta
from decimal import Decimal as D

from django.test import TestCase

from apps.finance import recon_allocator as RA, recon_engine as E
from apps.finance.models import (
    ReconParty, APInvoice, Payment, Allocation, MatchCandidate,
)

T0 = date(2026, 6, 1)


def oi(i, days, amt, refs=()):
    return RA.OpenInvoice(i, T0 + timedelta(days=days), D(amt), tuple(refs))


def ov(i, days, amt, tokens=()):
    return RA.OpenVoucher(i, T0 + timedelta(days=days), D(amt), frozenset(tokens))


def _by(props):
    return {(p['invoice'].id, p['voucher'].id): (p['strategy'], p['amount']) for p in props}


class StrategyTests(TestCase):

    def test_exact_unique(self):
        props = RA.allocate([oi(1, 0, '500'), oi(2, 1, '700')], [ov(10, 20, '700')],
                            strategies=['exact_unique'])
        self.assertEqual(_by(props), {(2, 10): ('exact_unique', D('700'))})

    def test_exact_unique_refuses_two_equal_invoices(self):
        props = RA.allocate([oi(1, 0, '700'), oi(2, 1, '700')], [ov(10, 20, '700')],
                            strategies=['exact_unique'])
        self.assertEqual(props, [])

    def test_exact_unique_refuses_rival_voucher(self):
        props = RA.allocate([oi(1, 0, '700')], [ov(10, 20, '700'), ov(11, 25, '700')],
                            strategies=['exact_unique'])
        self.assertEqual(props, [])

    def test_oldest_prefix(self):
        invs = [oi(1, 0, '100'), oi(2, 5, '250'), oi(3, 9, '400')]
        props = RA.allocate(invs, [ov(10, 30, '350')], strategies=['subset_oldest'])
        self.assertEqual(set(_by(props)), {(1, 10), (2, 10)})

    def test_window_run_unique(self):
        invs = [oi(1, 0, '100'), oi(2, 5, '250'), oi(3, 9, '400'), oi(4, 12, '90')]
        props = RA.allocate(invs, [ov(10, 30, '650')], strategies=['subset_window'])
        self.assertEqual(set(_by(props)), {(2, 10), (3, 10)})

    def test_window_run_ambiguous_skipped(self):
        invs = [oi(1, 0, '300'), oi(2, 5, '300'), oi(3, 9, '300')]
        props = RA.allocate(invs, [ov(10, 30, '600')], strategies=['subset_window'])
        self.assertEqual(props, [])            # (1,2) and (2,3) both sum to 600

    def test_window_excludes_too_old_invoice(self):
        invs = [oi(1, 0, '500')]
        props = RA.allocate(invs, [ov(10, 400, '500')], strategies=['subset_window'])
        self.assertEqual(props, [])

    def test_installments(self):
        props = RA.allocate([oi(1, 0, '900')],
                            [ov(10, 7, '300'), ov(11, 14, '300'), ov(12, 21, '300')],
                            strategies=['installments'])
        self.assertEqual({k[1] for k in _by(props)}, {10, 11, 12})

    def test_multi_ref(self):
        invs = [oi(1, 0, '100', refs=['11552']), oi(2, 1, '250', refs=['11548']), oi(3, 2, '999')]
        props = RA.allocate(invs, [ov(10, 5, '350', tokens=['11552', '11548'])],
                            strategies=['multi_ref'])
        self.assertEqual(set(_by(props)), {(1, 10), (2, 10)})

    def test_fifo_residual_partial_oldest_first(self):
        invs = [oi(1, 0, '100'), oi(2, 5, '250'), oi(3, 9, '400')]
        props = RA.allocate(invs, [ov(10, 30, '300')], strategies=['fifo_residual'])
        got = _by(props)
        self.assertEqual(got[(1, 10)], ('fifo_residual', D('100')))
        self.assertEqual(got[(2, 10)], ('fifo_residual', D('200')))    # partial
        self.assertNotIn((3, 10), got)

    def test_fifo_never_uses_future_invoice(self):
        props = RA.allocate([oi(1, 60, '100')], [ov(10, 0, '100')], strategies=['fifo_residual'])
        self.assertEqual(props, [])

    def test_order_consumes_capacity_once(self):
        # exact match wins; FIFO then only sees what is left
        invs = [oi(1, 0, '100'), oi(2, 5, '700')]
        props = RA.allocate(invs, [ov(10, 20, '700'), ov(11, 30, '60')])
        got = _by(props)
        self.assertEqual(got[(2, 10)][0], 'exact_unique')
        self.assertEqual(got[(1, 11)], ('fifo_residual', D('60')))
        total_on_inv2 = sum(p['amount'] for p in props if p['invoice'].id == 2)
        self.assertEqual(total_on_inv2, D('700'))                     # never over-allocated


class IntegrationTests(TestCase):

    def setUp(self):
        self.party = ReconParty.objects.create(party_type='supplier', softech_personcode='4471')

    def inv(self, no, days, value, paid='0'):
        return APInvoice.objects.create(
            party=self.party, branchcode='130', doccode='10', docnumber=str(no),
            docdate=T0 + timedelta(days=days), doc_value=D(value), doc_value_pay=D(paid),
            party_type='supplier')

    def pay(self, no, days, amount, note=''):
        return Payment.objects.create(
            party=self.party, branchcode='130', cheqsno=no, direction='out', party_type='supplier',
            voucher_date=T0 + timedelta(days=days), amount=D(amount), note=note, is_unallocated=True)

    def test_run_matching_adds_subset_group(self):
        a, b = self.inv(5001, 0, '120'), self.inv(5002, 3, '380')
        self.inv(5003, 40, '999')
        p = self.pay(9001, 20, '500')                  # empty note: only the sum can tell
        E.run_matching(party_type='supplier')
        cs = MatchCandidate.objects.filter(payment=p, status='proposed')
        self.assertEqual({c.invoice_id for c in cs}, {a.id, b.id})
        self.assertTrue(all(c.confidence_class == 'high' for c in cs))
        self.assertEqual(len({c.group_key for c in cs}), 1)

    def test_header_paid_invoice_not_offered(self):
        self.inv(5001, 0, '500', paid='500')           # SOFTECH already shows it paid
        self.pay(9001, 20, '500')
        E.run_matching(party_type='supplier')
        self.assertFalse(MatchCandidate.objects.filter(strategy__in=[
            'exact_unique', 'subset_oldest', 'subset_window', 'fifo_residual']).exists())

    def test_approved_capacity_respected(self):
        a = self.inv(5001, 0, '500')
        p1 = self.pay(9001, 10, '500', note='5001')    # pairwise high → approve it
        p2 = self.pay(9002, 20, '500')
        E.run_matching(party_type='supplier')
        from apps.finance import recon_actions as A
        A.approve_candidate(MatchCandidate.objects.get(invoice=a, payment=p1))
        E.run_matching(party_type='supplier')
        self.assertFalse(MatchCandidate.objects.filter(payment=p2, invoice=a, status='proposed').exists())

    def test_rerun_is_idempotent(self):
        self.inv(5001, 0, '120'); self.inv(5002, 3, '380')
        self.pay(9001, 20, '500')
        E.run_matching(party_type='supplier')
        n1 = MatchCandidate.objects.filter(status='proposed').count()
        E.run_matching(party_type='supplier')
        self.assertEqual(MatchCandidate.objects.filter(status='proposed').count(), n1)


class SameAmountNearestTests(TestCase):

    def test_picks_invoice_nearest_in_date(self):
        invs = [oi(1, 0, '500'), oi(2, 40, '500'), oi(3, 58, '500')]
        props = RA.allocate(invs, [ov(10, 60, '500')], strategies=['same_amount_nearest'])
        self.assertEqual(set(_by(props)), {(3, 10)})

    def test_exact_tie_left_for_human(self):
        invs = [oi(1, 50, '500'), oi(2, 50, '500')]
        props = RA.allocate(invs, [ov(10, 60, '500')], strategies=['same_amount_nearest'])
        self.assertEqual(props, [])

    def test_single_match_left_to_exact_unique(self):
        props = RA.allocate([oi(1, 0, '500')], [ov(10, 5, '500')], strategies=['same_amount_nearest'])
        self.assertEqual(props, [])
