"""
Owner decisions D-13 and D-14 (2026-11-19), docs/full-project-audit/14_DECISION_REGISTER.md.

D-13 (BE-7): every LoyaltyAccount balance change (earn, redeem, adjust, expire) runs under a row
lock, so two changes at the same moment can no longer overwrite each other.
D-14 (BE-8 follow-up): the adjust roles may DEDUCT referral points with a written reason, at most
LOYALTY_REFERRAL_DEDUCT_MAX (500) per deduction; more is admin only; audited in the ledger.
"""
import threading
import unittest

from django.db import connection
from django.db.models import Sum
from django.test import TestCase, TransactionTestCase, override_settings

from apps.loyalty.models import LoyaltyAccount, PointTransaction
from apps.tests.factories import (
    make_admin, make_call_center, make_customer, make_pharmacist, make_supervisor,
)


def _ledger_sum(account):
    return PointTransaction.objects.filter(account=account).aggregate(s=Sum('points'))['s'] or 0


class StaleCopyNoLostUpdateTests(TestCase):
    """Two in-memory copies of the same account (what two requests hold). Before D-13 the second
    write saved its stale balance and the first change was lost."""

    def setUp(self):
        self.customer = make_customer()
        self.account = LoyaltyAccount.objects.create(customer=self.customer)
        # Start the ledger consistent with the balance.
        self.account.add_points(500, reason='opening')

    def _copies(self):
        return (LoyaltyAccount.objects.get(pk=self.account.pk),
                LoyaltyAccount.objects.get(pk=self.account.pk))

    def _assert_balance(self, expected):
        self.account.refresh_from_db()
        self.assertEqual(self.account.points_balance, expected)
        self.assertEqual(_ledger_sum(self.account), expected)

    def test_earn_then_earn(self):
        a, b = self._copies()
        a.add_points(10, reason='x')
        b.add_points(10, reason='y')
        self._assert_balance(520)
        self.account.refresh_from_db()
        self.assertEqual(self.account.points_lifetime, 520)

    def test_earn_then_redeem(self):
        a, b = self._copies()
        a.add_points(100, reason='x')
        b.redeem_points(50, reason='y')
        self._assert_balance(550)
        self.account.refresh_from_db()
        self.assertEqual(self.account.points_redeemed, 50)

    def test_adjust_then_expire(self):
        a, b = self._copies()
        a.adjust_points(-100, reason='x', by_staff=None)
        b.expire_points(1000)                      # capped at the LOCKED balance (400), not 500
        self._assert_balance(0)

    def test_redeem_checks_the_locked_balance(self):
        a, b = self._copies()
        a.redeem_points(450, reason='x')
        with self.assertRaises(ValueError):
            b.redeem_points(100, reason='y')       # b still believes the balance is 500
        self._assert_balance(50)

    def test_expire_nothing_writes_nothing(self):
        self.account.expire_points(500)
        before = PointTransaction.objects.count()
        self.assertIsNone(self.account.expire_points(10))
        self.assertEqual(PointTransaction.objects.count(), before)

    def test_ledger_row_has_balance_before_and_after(self):
        tx = self.account.add_points(7, reason='x')
        self.assertEqual((tx.balance_before, tx.balance_after), (500, 507))
        self.assertEqual(self.account.points_balance, 507)   # the caller's copy is refreshed


@unittest.skipUnless(connection.vendor == 'postgresql', 'row locks need PostgreSQL')
class ConcurrentBalanceChangesTests(TransactionTestCase):
    """Two threads, two DB connections, the same account at the same time: no lost update."""

    ROUNDS = 15

    def setUp(self):
        self.customer = make_customer()
        self.account = LoyaltyAccount.objects.create(customer=self.customer)
        self.account.add_points(1000, reason='opening')

    def _run(self, *workers):
        barrier = threading.Barrier(len(workers))
        errors = []

        def wrap(fn):
            def run():
                try:
                    barrier.wait(timeout=10)
                    for _ in range(self.ROUNDS):
                        fn(LoyaltyAccount.objects.get(pk=self.account.pk))
                except Exception as exc:     # surfaced in the main thread below
                    errors.append(exc)
                finally:
                    connection.close()
            return run

        threads = [threading.Thread(target=wrap(w)) for w in workers]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
        self.assertEqual(errors, [])
        self.account.refresh_from_db()

    def test_two_threads_earn(self):
        self._run(lambda acc: acc.add_points(10, reason='a'),
                  lambda acc: acc.add_points(10, reason='b'))
        self.assertEqual(self.account.points_balance, 1000 + 2 * 10 * self.ROUNDS)
        self.assertEqual(_ledger_sum(self.account), self.account.points_balance)
        self.assertEqual(self.account.points_lifetime, self.account.points_balance)

    def test_earn_and_redeem_at_once(self):
        self._run(lambda acc: acc.add_points(10, reason='earn'),
                  lambda acc: acc.redeem_points(5, reason='redeem'))
        self.assertEqual(self.account.points_balance, 1000 + 10 * self.ROUNDS - 5 * self.ROUNDS)
        self.assertEqual(_ledger_sum(self.account), self.account.points_balance)
        self.assertEqual(self.account.points_redeemed, 5 * self.ROUNDS)

    def test_referral_deduct_and_earn_at_once(self):
        self._run(lambda acc: acc.adjust_points(-20, reason='deduct', by_staff=None,
                                                source_type='referral', allow_negative=False),
                  lambda acc: acc.add_points(10, reason='earn', source_type='referral'))
        self.assertEqual(self.account.points_balance, 1000 - 10 * self.ROUNDS)
        self.assertEqual(_ledger_sum(self.account), self.account.points_balance)


@override_settings(LOYALTY_REFERRAL_DEDUCT_MAX=500)
class ReferralDeductionRuleTests(TestCase):
    """D-14: deduct referral points with a reason, ≤500 per deduction unless admin."""

    def setUp(self):
        self.customer = make_customer()
        self.account = LoyaltyAccount.objects.create(customer=self.customer)
        self.account.add_points(2000, reason='opening', source_type='referral')
        self.url = f'/api/loyalty/customers/{self.customer.pk}/adjust/'

    def _deduct(self, client, points, reason='العميل استبدلها في الفرع'):
        return client.post(self.url, {'points': -points, 'reason': reason,
                                      'adjust_type': 'referral'}, format='json')

    def _balance(self):
        self.account.refresh_from_db()
        return self.account.points_balance

    def test_call_center_can_deduct_up_to_500(self):
        _, staff, client = make_call_center('d14_cc')
        r = self._deduct(client, 500)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['crm_points_balance'], 1500)
        self.assertEqual(r.data['balance_before'], 2000)
        self.assertEqual(self._balance(), 1500)

    def test_audit_row(self):
        _, staff, client = make_call_center('d14_cc_audit')
        r = self._deduct(client, 120, reason='خصم بطلب العميل')
        tx = PointTransaction.objects.get(pk=r.data['transaction_id'])
        self.assertEqual(tx.points, -120)
        self.assertEqual(tx.transaction_type, 'adjust')
        self.assertEqual(tx.source_type, 'referral')
        self.assertEqual(tx.reason, 'خصم بطلب العميل')
        self.assertEqual(tx.created_by, staff)
        self.assertEqual((tx.balance_before, tx.balance_after), (2000, 1880))
        self.assertIsNotNone(tx.created_at)
        listed = self.client_for_ledger(client)
        self.assertEqual(listed[0]['balance_before'], 2000)
        self.assertEqual(listed[0]['created_by_name'], staff.full_name)

    def client_for_ledger(self, client):
        r = client.get(f'/api/loyalty/customers/{self.customer.pk}/transactions/')
        self.assertEqual(r.status_code, 200)
        return r.data.get('results', r.data) if isinstance(r.data, dict) else r.data

    def test_over_500_refused_for_call_center_and_supervisor(self):
        for maker, name in ((make_call_center, 'd14_cc2'), (make_supervisor, 'd14_sup')):
            _, _, client = maker(name)
            r = self._deduct(client, 501)
            self.assertEqual(r.status_code, 403, name)
            self.assertEqual(r.data['error_code'], 'loyalty_referral_deduct_over_limit')
        self.assertEqual(self._balance(), 2000)
        self.assertFalse(PointTransaction.objects.filter(points__lt=0).exists())

    def test_admin_can_go_over_the_limit(self):
        _, _, client = make_admin('d14_admin')
        r = self._deduct(client, 1200)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(self._balance(), 800)

    def test_reason_required(self):
        _, _, client = make_call_center('d14_cc3')
        for reason in ('', '   '):
            r = self._deduct(client, 50, reason=reason)
            self.assertEqual(r.status_code, 400)
            self.assertEqual(r.data['error_code'], 'loyalty_reason_required')
        self.assertEqual(self._balance(), 2000)

    def test_other_roles_refused(self):
        _, _, client = make_pharmacist('d14_ph')
        r = self._deduct(client, 10)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self._balance(), 2000)

    def test_never_below_zero(self):
        _, _, client = make_admin('d14_admin2')
        r = self._deduct(client, 2001)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data['error_code'], 'loyalty_insufficient_points')
        self.assertEqual(self._balance(), 2000)

    def test_positive_referral_still_adds_and_records_who(self):
        _, staff, client = make_call_center('d14_cc4')
        r = client.post(self.url, {'points': 30, 'reason': 'إحالة', 'adjust_type': 'referral'},
                        format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self._balance(), 2030)
        self.assertEqual(PointTransaction.objects.get(pk=r.data['transaction_id']).created_by, staff)
