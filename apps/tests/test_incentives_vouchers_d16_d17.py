"""
D-16 / D-17 (owner decisions 2026-11-19, docs/full-project-audit/14_DECISION_REGISTER.md; audit BE-10,
BE-11, BE-21).

D-16 "Refuse unless unlocked":
  * an incentive recalculation runs in one transaction — a crash mid-run rolls the delete back;
  * a recalculation, forced or not, never touches a finalized settlement or its transactions;
  * only an admin unlocks a finalized settlement, with a written reason, audited before/after.
D-17 "Protect":
  * a program's transactions / settlements / adjustments / logs and a voucher's redemptions are
    on_delete=PROTECT; the delete endpoints answer 409 with an Arabic message and offer archive;
  * archive (program is_active=False, voucher status=cancelled) keeps every audit row.
SOFTECH reads (_fetch_rows / _fetch_cross_period_returns) are replaced by synthetic rows.
"""
import datetime
from decimal import Decimal
from unittest import mock

from django.core.management import call_command
from django.db.models.deletion import ProtectedError
from django.test import TestCase, override_settings

from apps.incentives import engine as IE
from apps.incentives.models import (
    AdjustmentEntry, IncentiveAuditEvent, IncentiveCalculationLog, IncentiveProgram, IncentiveRule,
    IncentiveSettlement, IncentiveTransaction,
)
from apps.vouchers.models import Voucher, VoucherRedemption

from .factories import make_branch, make_user
from .test_money_offers_incentives import P_END, P_START, RETURNS, SALES, _row

D = Decimal
PERIOD = {'period_start': '2026-10-01', 'period_end': '2026-10-31'}

# a second ERP picture of the same period: every quantity changed
SALES_V2 = [_row('S1', '501', 'X1', D('9'), D('100.00')), _row('S3', '502', 'X1', D('7'), D('100.00'))]


def _fetch(sales):
    def fake(doc_code, start, end, person_codes=None, use_returns_template=False):
        return list(RETURNS if use_returns_template else sales)
    return fake


class _IncentiveBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('seed_permissions', verbosity=0)

    def setUp(self):
        patcher = mock.patch.object(IE, '_fetch_cross_period_returns', return_value=[])
        patcher.start()
        self.addCleanup(patcher.stop)
        _, self.u1, _ = make_user('d16_rep_1')
        _, self.u2, _ = make_user('d16_rep_2')
        for p, code in ((self.u1, '501'), (self.u2, '502')):
            p.softech_user_id = code
            p.save(update_fields=['softech_user_id'])
        _, self.admin, self.api = make_user('d16_admin', role='admin', access_all=True)
        self.prog = IncentiveProgram.objects.create(name='D16', start_date=P_START, end_date=P_END)
        IncentiveRule.objects.create(program=self.prog, incentive_type='percent', incentive_value=D('10'))

    def calc(self, sales=SALES, **kw):
        with mock.patch.object(IE, '_fetch_rows', side_effect=_fetch(sales)):
            return IE.calculate(self.prog.id, P_START, P_END, **kw)

    def rows(self, user=None):
        qs = IncentiveTransaction.objects.filter(program=self.prog)
        if user is not None:
            qs = qs.filter(user=user)
        return sorted((t.user_id, t.doc_no, t.doc_type, t.quantity, t.incentive_amount, t.pk) for t in qs)

    def finalize(self, user):
        return IncentiveSettlement.objects.create(
            program=self.prog, user=user, period_start=P_START, period_end=P_END,
            total_incentive=D('13.3330'), final_payout=D('13.3330'), transaction_count=3,
            is_finalized=True, finalized_by=self.admin)


class RecalculationIsTransactionalTests(_IncentiveBase):

    def test_a_crash_while_inserting_rolls_the_delete_back(self):
        self.calc()
        before = self.rows()
        self.assertEqual(len(before), 4)
        with mock.patch.object(IncentiveTransaction.objects, 'bulk_create', side_effect=RuntimeError('boom')):
            with self.assertRaises(RuntimeError):
                self.calc(sales=SALES_V2)
        # the period still holds the previous run (same rows, same primary keys) — never zero rows
        self.assertEqual(self.rows(), before)
        self.assertEqual(IncentiveCalculationLog.objects.filter(program=self.prog, mode='calculate').count(), 1)

    def test_two_runs_never_double_the_period(self):
        self.calc()
        self.calc()
        self.assertEqual(IncentiveTransaction.objects.filter(program=self.prog).count(), 4)

    def test_a_run_scoped_to_one_person_rebuilds_only_their_rows(self):
        self.calc()
        u2_before = self.rows(self.u2)
        self.calc(sales=SALES_V2, user_ids=[self.u1.pk])
        self.assertEqual(self.rows(self.u2), u2_before)
        self.assertEqual({r[3] for r in self.rows(self.u1) if r[2] == 'sale'}, {D('9.000')})


class FinalizedSettlementIsNeverTouchedTests(_IncentiveBase):

    def test_without_force_a_run_is_refused(self):
        self.calc()
        before = self.rows()
        self.finalize(self.u1)
        with self.assertRaises(ValueError):
            self.calc(sales=SALES_V2)
        self.assertEqual(self.rows(), before)

    def test_forced_run_keeps_the_finalized_settlement_and_its_rows(self):
        self.calc()
        u1_before = self.rows(self.u1)
        sett = self.finalize(self.u1)
        snapshot = IncentiveSettlement.objects.filter(pk=sett.pk).values().get()

        result = self.calc(sales=SALES_V2, force=True)

        # u1 (finalized): settlement and transactions exactly as they were
        self.assertEqual(IncentiveSettlement.objects.filter(pk=sett.pk).values().get(), snapshot)
        self.assertEqual(self.rows(self.u1), u1_before)
        # u2 (open): rebuilt from the new ERP picture
        self.assertEqual([r[3] for r in self.rows(self.u2)], [D('7.000')])
        self.assertEqual(result.finalized_user_ids, [self.u1.pk])
        self.assertEqual(result.created, 1)

    def test_forced_run_over_the_api_answers_with_the_kept_people(self):
        self.calc()
        self.finalize(self.u1)
        self.finalize(self.u2)
        url = f'/api/incentives/programs/{self.prog.id}/calculate/'
        with mock.patch.object(IE, '_fetch_rows', side_effect=_fetch(SALES_V2)):
            self.assertEqual(self.api.post(url, PERIOD, format='json').status_code, 409)
            r = self.api.post(url, {**PERIOD, 'force': True}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(sorted(r.json()['kept_finalized_user_ids']), sorted([self.u1.pk, self.u2.pk]))
        self.assertEqual(IncentiveSettlement.objects.filter(program=self.prog, is_finalized=True).count(), 2)
        self.assertEqual({r_[3] for r_ in self.rows() if r_[2] == 'sale'}, {D('2.000'), D('1.000'), D('5.000')})


@override_settings(RBAC_ENFORCEMENT='enforce')
class SettlementUnlockTests(_IncentiveBase):

    def url(self, sett):
        return f'/api/incentives/settlements/{sett.pk}/unlock/'

    def test_admin_unlocks_with_a_reason_and_it_is_audited(self):
        self.calc()
        sett = self.finalize(self.u1)
        r = self.api.post(self.url(sett), {'reason': 'خطأ في كود الصنف'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        sett.refresh_from_db()
        self.assertEqual((sett.is_finalized, sett.finalized_at, sett.finalized_by_id), (False, None, None))

        ev = IncentiveAuditEvent.objects.get(pk=r.json()['audit_event_id'])
        self.assertEqual((ev.action, ev.program_id, ev.settlement_id, ev.actor_id),
                         ('settlement_unlocked', self.prog.pk, sett.pk, self.admin.pk))
        self.assertEqual(ev.reason, 'خطأ في كود الصنف')
        self.assertEqual((ev.before['is_finalized'], ev.before['finalized_by'], ev.before['final_payout']),
                         (True, self.admin.pk, '13.3330'))
        self.assertEqual((ev.after['is_finalized'], ev.after['finalized_by']), (False, None))

        # unlocked → the next run (no force needed) recalculates that person
        self.calc(sales=SALES_V2)
        self.assertEqual({t[3] for t in self.rows(self.u1) if t[2] == 'sale'}, {D('9.000')})

    def test_a_reason_is_required(self):
        sett = self.finalize(self.u1)
        for body in ({}, {'reason': ''}, {'reason': '  ab '}):
            self.assertEqual(self.api.post(self.url(sett), body, format='json').status_code, 400)
        sett.refresh_from_db()
        self.assertTrue(sett.is_finalized)
        self.assertFalse(IncentiveAuditEvent.objects.exists())

    def test_an_open_settlement_has_nothing_to_unlock(self):
        sett = self.finalize(self.u1)
        IncentiveSettlement.objects.filter(pk=sett.pk).update(is_finalized=False)
        self.assertEqual(self.api.post(self.url(sett), {'reason': 'سبب كافي'}, format='json').status_code, 409)

    def test_other_payroll_roles_are_refused(self):
        sett = self.finalize(self.u1)
        for role in ('quality_manager', 'purchasing'):
            with self.subTest(role):
                _, _, client = make_user(f'd16_{role}', role=role, access_all=True)
                r = client.post(self.url(sett), {'reason': 'سبب كافي'}, format='json')
                self.assertEqual(r.status_code, 403, r.content)
        sett.refresh_from_db()
        self.assertTrue(sett.is_finalized)
        self.assertFalse(IncentiveAuditEvent.objects.exists())


@override_settings(RBAC_ENFORCEMENT='log')
class ProgramProtectAndArchiveTests(_IncentiveBase):

    def test_a_program_with_audit_rows_cannot_be_deleted(self):
        self.calc()
        self.finalize(self.u1)
        AdjustmentEntry.objects.create(program=self.prog, user=self.u2, period_start=P_START,
                                       period_end=P_END, amount=D('1'), reason='bonus')
        with self.assertRaises(ProtectedError):
            self.prog.delete()
        r = self.api.delete(f'/api/incentives/programs/{self.prog.pk}/')
        self.assertEqual(r.status_code, 409, r.content)
        self.assertIn('أرشفة', r.json()['detail'])
        self.assertTrue(r.json()['can_archive'])
        self.assertTrue(IncentiveProgram.objects.filter(pk=self.prog.pk).exists())
        self.assertEqual(IncentiveTransaction.objects.filter(program=self.prog).count(), 4)

    def test_archive_deactivates_and_keeps_every_audit_row(self):
        self.calc()
        self.finalize(self.u1)
        counts = (IncentiveTransaction.objects.count(), IncentiveSettlement.objects.count(),
                  IncentiveCalculationLog.objects.count())
        r = self.api.post(f'/api/incentives/programs/{self.prog.pk}/archive/', {'reason': 'انتهى'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.prog.refresh_from_db()
        self.assertFalse(self.prog.is_active)
        self.assertEqual((IncentiveTransaction.objects.count(), IncentiveSettlement.objects.count(),
                          IncentiveCalculationLog.objects.count()), counts)
        ev = IncentiveAuditEvent.objects.get(action='program_archived')
        self.assertEqual((ev.before, ev.after, ev.actor_id), ({'is_active': True}, {'is_active': False}, self.admin.pk))
        # archiving twice is refused
        self.assertEqual(self.api.post(f'/api/incentives/programs/{self.prog.pk}/archive/').status_code, 400)

    def test_a_program_without_audit_rows_still_deletes(self):
        empty = IncentiveProgram.objects.create(name='فارغ', start_date=P_START, end_date=P_END)
        IncentiveRule.objects.create(program=empty, incentive_type='percent', incentive_value=D('5'))
        self.assertEqual(self.api.delete(f'/api/incentives/programs/{empty.pk}/').status_code, 204)
        self.assertFalse(IncentiveProgram.objects.filter(pk=empty.pk).exists())


@override_settings(RBAC_ENFORCEMENT='log')
class VoucherProtectTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('seed_permissions', verbosity=0)

    def setUp(self):
        self.branch = make_branch()
        _, self.admin, self.api = make_user('d17_admin', role='admin', access_all=True)

    def voucher(self):
        return Voucher.objects.create(
            code=Voucher.generate_code(), title='قسيمة', voucher_type='discount_pct', discount_pct=10,
            branch=self.branch, created_by=self.admin, status='active', max_uses=10,
            valid_from=datetime.date.today())

    def test_a_voucher_with_redemptions_cannot_be_deleted(self):
        v = self.voucher()
        red = VoucherRedemption.objects.create(voucher=v, customer_phone='01000000000', redeemed_by=self.admin,
                                               branch=self.branch, discount_applied=D('5'), order_amount=D('50'))
        with self.assertRaises(ProtectedError):
            v.delete()
        r = self.api.delete(f'/api/vouchers/vouchers/{v.pk}/')
        self.assertEqual(r.status_code, 409, r.content)
        self.assertIn('إلغاء', r.json()['detail'])
        self.assertTrue(r.json()['can_archive'])
        self.assertTrue(VoucherRedemption.objects.filter(pk=red.pk).exists())

    def test_cancel_archives_and_keeps_the_redemptions(self):
        v = self.voucher()
        red = VoucherRedemption.objects.create(voucher=v, customer_phone='01000000000', redeemed_by=self.admin,
                                               branch=self.branch, discount_applied=D('5'), order_amount=D('50'))
        self.assertEqual(self.api.post(f'/api/vouchers/vouchers/{v.pk}/cancel/').status_code, 200)
        v.refresh_from_db()
        self.assertEqual(v.status, 'cancelled')
        self.assertTrue(VoucherRedemption.objects.filter(pk=red.pk, voucher=v).exists())
        r = self.api.delete(f'/api/vouchers/vouchers/{v.pk}/')
        self.assertEqual(r.status_code, 409)
        self.assertFalse(r.json()['can_archive'])      # already cancelled

    def test_a_voucher_never_redeemed_still_deletes(self):
        v = self.voucher()
        self.assertEqual(self.api.delete(f'/api/vouchers/vouchers/{v.pk}/').status_code, 204)
        self.assertFalse(Voucher.objects.filter(pk=v.pk).exists())
