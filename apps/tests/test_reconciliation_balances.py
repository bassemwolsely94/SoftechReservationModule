"""
apps/tests/test_reconciliation_balances.py

Phase-C batch F — حصر balance snapshot + ledger timeline (apps/finance/recon_balances.py
+ the timeline endpoint). Pure computation over the mirror + fabricated SOFTECH
balance rows; no Sybase.
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase

from apps.finance import recon_balances as B
from apps.finance.models import ReconParty, APInvoice, Payment
from .factories import make_admin

BASE = '/api/finance/reconciliation'


def _party(pc='4471', opening='0'):
    return ReconParty.objects.create(
        party_type='supplier', softech_personcode=pc, name='',
        opening_balance=Decimal(opening),
    )


def _inv(party, docnumber, value, is_return=False, docdate=date(2026, 8, 15)):
    return APInvoice.objects.create(
        party=party, branchcode='130', doccode='120' if is_return else '10',
        docnumber=docnumber, docdate=docdate, doc_value=Decimal(value),
        doc_value_pay=Decimal('0'), is_return=is_return, party_type='supplier',
    )


def _pay(party, cheqsno, amount, vdate=date(2026, 9, 18)):
    return Payment.objects.create(
        party=party, branchcode='130', cheqsno=cheqsno, direction='out',
        party_type='supplier', voucher_date=vdate, amount=Decimal(amount),
        note='', is_unallocated=True,
    )


class ApplyBalancesTests(TestCase):

    def test_apply_updates_party(self):
        p = _party('4471')
        rows = [{
            'personcode': '4471', 'personname': 'مورد شركات 30', 'ptcode': '20',
            'ptclassifcode': '80', 'softech_balance': '1593666.38',
            'opening_balance': '100000.00',
        }]
        stats = B.apply_balances(rows)
        self.assertEqual(stats['updated'], 1)
        p.refresh_from_db()
        self.assertEqual(p.softech_balance, Decimal('1593666.380'))
        self.assertEqual(p.opening_balance, Decimal('100000.000'))
        self.assertEqual(p.name, 'مورد شركات 30')          # blank name backfilled
        self.assertEqual(p.ptclassifcode, '80')
        self.assertIsNotNone(p.softech_balance_at)

    def test_apply_counts_missing(self):
        stats = B.apply_balances([{'personcode': '9999', 'softech_balance': '5'}])
        self.assertEqual(stats['updated'], 0)
        self.assertEqual(stats['missing'], 1)


class EquationTests(TestCase):

    def test_equation_math(self):
        p = _party('4471', opening='1000')
        p.softech_balance = Decimal('1100')
        p.save()
        _inv(p, '1', '500')                 # purchase +500
        _inv(p, '2', '100', is_return=True) # return  -100
        _pay(p, 1, '300')                   # payment -300
        eq = B.reconciliation_equation(p)
        self.assertEqual(eq['purchases'], Decimal('500'))
        self.assertEqual(eq['returns'], Decimal('100'))
        self.assertEqual(eq['payments'], Decimal('300'))
        self.assertEqual(eq['expected_closing'], Decimal('1100'))   # 1000+500-100-300
        self.assertEqual(eq['unexplained_variance'], Decimal('0'))  # softech 1100 == expected


class SnapshotEquationTests(TestCase):
    """F2 — the SOFTECH personnewbal snapshot ties the ledger to reality."""

    def test_snapshot_balance_and_split_variance(self):
        from datetime import datetime
        from django.utils import timezone
        p = _party('4471', opening='0')
        p.softech_balance = Decimal('1000')   # personsdata master says owed 1000
        p.save()
        # purchase 800 at t1, personnewbal after = -1000 (owed 1000, incl. ~200 VAT/other)
        inv = _inv(p, '1', '800', docdate=date(2026, 1, 10))
        inv.person_new_bal = Decimal('-1000')
        inv.trans_time = timezone.make_aware(datetime(2026, 1, 10, 9, 0))
        inv.save()
        # payment 0 later? keep just the purchase so snapshot = -(-1000) = 1000 owed
        eq = B.reconciliation_equation(p)
        self.assertEqual(eq['snapshot_balance'], Decimal('1000'))       # SOFTECH trail
        self.assertEqual(eq['expected_closing'], Decimal('800'))        # our model (net docvalue)
        self.assertEqual(eq['model_vs_snapshot'], Decimal('200'))       # posting-model gap (the VAT/other)
        self.assertEqual(eq['snapshot_vs_softech'], Decimal('0'))       # snapshot ties to master

    def test_no_snapshot_omits_keys(self):
        p = _party('5000', opening='1000')
        p.softech_balance = Decimal('1100'); p.save()
        _inv(p, '1', '100')   # no person_new_bal / trans_time set
        eq = B.reconciliation_equation(p)
        self.assertIsNone(eq['snapshot_balance'])
        self.assertNotIn('model_vs_snapshot', eq)


class TimelineTests(TestCase):

    def test_running_balance_chronological(self):
        p = _party('4471', opening='1000')
        _inv(p, '1', '500', docdate=date(2026, 1, 10))                 # +500 → 1500
        _pay(p, 1, '300', vdate=date(2026, 2, 5))                      # -300 → 1200
        _inv(p, '2', '100', is_return=True, docdate=date(2026, 3, 1))  # -100 → 1100
        tl = B.build_ledger_timeline(p)
        self.assertEqual(tl['event_count'], 3)
        kinds = [e['kind'] for e in tl['events']]
        self.assertEqual(kinds, ['purchase', 'payment', 'return'])
        balances = [e['running_balance'] for e in tl['events']]
        self.assertEqual(balances, [Decimal('1500'), Decimal('1200'), Decimal('1100')])
        # final running == equation expected_closing
        self.assertEqual(balances[-1], tl['equation']['expected_closing'])


class TimelineApiTests(TestCase):

    def setUp(self):
        _, self.profile, self.client = make_admin('recon_admin')
        self.p = _party('4471', opening='0')
        _inv(self.p, '12207', '743.40')
        _pay(self.p, 51703, '743.40')

    def test_timeline_endpoint(self):
        resp = self.client.get(f'{BASE}/parties/4471/timeline/')
        self.assertEqual(resp.status_code, 200)
        d = resp.json()
        self.assertEqual(d['event_count'], 2)
        self.assertIn('equation', d)
        self.assertEqual(d['party']['softech_personcode'], '4471')

    def test_timeline_404(self):
        resp = self.client.get(f'{BASE}/parties/0000/timeline/')
        self.assertEqual(resp.status_code, 404)
