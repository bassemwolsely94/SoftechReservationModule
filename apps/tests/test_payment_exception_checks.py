"""
Payment exception checks (2026-11-05): PaymentAuditService.detect_exceptions /
calculate_anomaly_score / _escalate_to_abuse_flag against the real ExternalPayment fields
(created_by, method, payment_date), the payment_anomaly AbuseFlag, and the
run_payment_exception_checks command behind payments.exception_checks_enabled. Synthetic data.
"""
import io
from datetime import timedelta
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.audit.models import AbuseFlag
from apps.config.models import SystemSetting
from apps.payments.audit_service import PaymentAuditService as S
from apps.payments.models import ExternalPayment, PaymentException
from apps.tests.factories import make_branch, make_branch2, make_user


def _types(payment):
    return set(PaymentException.objects.filter(payment=payment).values_list('exception_type', flat=True))


class _Base(TestCase):

    def setUp(self):
        self.b1 = make_branch('فرع الاختبار أ', 'PX1')
        self.b2 = make_branch2('فرع الاختبار ب', 'PX2')
        self.user, self.profile, _ = make_user('payexc_cashier', role='pharmacist', branch=self.b1)
        self.today = timezone.localdate()

    def pay(self, amount='100.00', *, user='default', branch=None, method='instapay', days_ago=0,
            status='confirmed'):
        return ExternalPayment.objects.create(
            branch=branch or self.b1, method=method, amount=Decimal(amount),
            payment_date=self.today - timedelta(days=days_ago), status=status,
            created_by=self.user if user == 'default' else user,
        )


class DuplicateTests(_Base):

    def test_same_user_amount_method_day_is_a_duplicate(self):
        self.pay()
        b = self.pay()
        created = S.detect_exceptions(b.pk)
        self.assertEqual([e.exception_type for e in created], ['duplicate'])
        exc = created[0]
        self.assertEqual(exc.severity, 'critical')
        self.assertIn('اليوم', exc.detail)

    def test_different_method_amount_or_day_or_cancelled_is_not(self):
        self.pay(method='vodafone_cash')
        self.pay(amount='101.00')
        self.pay(days_ago=1)
        self.pay(status='cancelled')
        p = self.pay()
        S.detect_exceptions(p.pk)
        self.assertNotIn('duplicate', _types(p))

    def test_other_user_is_not_a_duplicate(self):
        other, _, _ = make_user('payexc_other', role='pharmacist', branch=self.b1)
        self.pay(user=other)
        p = self.pay()
        S.detect_exceptions(p.pk)
        self.assertNotIn('duplicate', _types(p))

    def test_null_creator_skips_duplicate_and_branch(self):
        self.pay(user=None)
        p = self.pay(user=None, branch=self.b2)
        self.assertEqual(S.detect_exceptions(p.pk), [])


class DelayedTests(_Base):

    def test_pending_three_days_fires(self):
        p = self.pay(status='pending', days_ago=3)
        self.assertIn('delayed', [e.exception_type for e in S.detect_exceptions(p.pk)])

    def test_pending_two_days_or_confirmed_old_does_not(self):
        p1 = self.pay(status='pending', days_ago=2, amount='1')
        p2 = self.pay(status='confirmed', days_ago=10, amount='2')
        S.detect_exceptions(p1.pk)
        S.detect_exceptions(p2.pk)
        self.assertNotIn('delayed', _types(p1) | _types(p2))


class WrongBranchTests(_Base):

    def test_branch_user_recording_for_another_branch_fires_with_labels(self):
        p = self.pay(branch=self.b2)
        exc = [e for e in S.detect_exceptions(p.pk) if e.exception_type == 'wrong_branch']
        self.assertEqual(len(exc), 1)
        self.assertIn('فرع الاختبار أ', exc[0].detail)
        self.assertIn('فرع الاختبار ب', exc[0].detail)
        self.assertNotIn(str(self.b2.pk) + ' ', exc[0].detail)

    def test_own_branch_does_not_fire(self):
        p = self.pay()
        S.detect_exceptions(p.pk)
        self.assertNotIn('wrong_branch', _types(p))

    def test_all_branch_users_are_skipped(self):
        cc, _, _ = make_user('payexc_cc', role='call_center', branch=self.b1)
        flagged, _, _ = make_user('payexc_all', role='pharmacist', branch=self.b1, access_all=True)
        for u in (cc, flagged):
            p = self.pay(user=u, branch=self.b2, amount=str(u.pk))
            S.detect_exceptions(p.pk)
            self.assertNotIn('wrong_branch', _types(p))

    def test_creator_without_profile_is_skipped(self):
        from django.contrib.auth.models import User
        u = User.objects.create(username='payexc_noprofile')
        p = self.pay(user=u, branch=self.b2)
        self.assertEqual(S.detect_exceptions(p.pk), [])


class AnomalyTests(_Base):

    def _history(self, n, user='default'):
        for i, amt in enumerate(['100', '110', '90', '105', '95', '100'][:n]):
            self.pay(amt, user=user, days_ago=i + 1)

    def test_under_five_samples_scores_zero(self):
        self._history(4)
        p = self.pay('100000')
        self.assertEqual(S.calculate_anomaly_score(p), Decimal('0'))
        self.assertFalse(AbuseFlag.objects.exists())

    def test_null_creator_scores_zero(self):
        self._history(6, user=None)
        p = self.pay('100000', user=None)
        self.assertEqual(S.calculate_anomaly_score(p), Decimal('0'))

    def test_normal_amount_scores_low_and_cancelled_history_ignored(self):
        self._history(6)
        self.pay('999999', status='cancelled', days_ago=1)
        p = self.pay('102')
        self.assertLess(S.calculate_anomaly_score(p), Decimal('70'))
        self.assertFalse(PaymentException.objects.filter(exception_type='anomaly').exists())

    def test_outlier_scores_high_and_raises_one_linked_flag(self):
        self._history(6)
        p = self.pay('5000')
        score = S.calculate_anomaly_score(p)
        self.assertEqual(score, Decimal('100'))
        flags = AbuseFlag.objects.filter(flag_type='payment_anomaly')
        self.assertEqual(flags.count(), 1)
        flag = flags.get()
        flag.full_clean()
        self.assertEqual((flag.staff, flag.severity, flag.status, flag.count, flag.window_hours),
                         (self.profile, 'critical', 'open', 1, 2160))
        self.assertEqual(flag.evidence['payment_id'], p.pk)
        self.assertEqual(flag.evidence['samples'], 6)
        self.assertEqual(set(flag.evidence), {'payment_id', 'score', 'mean', 'stdev', 'samples'})
        self.assertIn(p.get_method_display(), flag.description)
        self.assertIn('5000', flag.description)
        exc = PaymentException.objects.get(payment=p, exception_type='anomaly')
        self.assertEqual(exc.abuse_flag_id, flag.pk)
        self.assertEqual(exc.anomaly_score, Decimal('100'))

        # rerun (and a reviewed flag) → still one flag, one exception
        flag.status = 'reviewed'
        flag.save()
        S.calculate_anomaly_score(p)
        self.assertEqual(AbuseFlag.objects.filter(flag_type='payment_anomaly').count(), 1)
        self.assertEqual(PaymentException.objects.filter(payment=p, exception_type='anomaly').count(), 1)

    def test_outlier_without_profile_records_exception_but_no_flag(self):
        from django.contrib.auth.models import User
        u = User.objects.create(username='payexc_noprofile2')
        self._history(6, user=u)
        p = self.pay('5000', user=u)
        self.assertEqual(S.calculate_anomaly_score(p), Decimal('100'))
        self.assertFalse(AbuseFlag.objects.exists())
        exc = PaymentException.objects.get(payment=p, exception_type='anomaly')
        self.assertIsNone(exc.abuse_flag_id)


class RerunAndCommandTests(_Base):

    def _scenario(self):
        self.pay('100')
        self.pay('100')                                   # duplicate pair
        self.pay('50', status='pending', days_ago=4)      # delayed
        self.pay('60', branch=self.b2)                    # wrong branch
        for i, amt in enumerate(['100', '110', '90', '105', '95']):
            self.pay(amt, method='fawry', days_ago=i + 1)
        self.outlier = self.pay('9000', method='fawry')

    def _run(self, *args):
        out = io.StringIO()
        call_command('run_payment_exception_checks', *args, stdout=out)
        return out.getvalue()

    def test_rerun_is_idempotent(self):
        self._scenario()
        first = S.run_exception_checks(days=7)
        self.assertEqual(first['exceptions_created'], 4)   # 2 duplicates + delayed + wrong branch
        self.assertEqual((first['anomalies_created'], first['flags_created']), (1, 1))
        before = PaymentException.objects.count()
        second = S.run_exception_checks(days=7)
        self.assertEqual((second['exceptions_created'], second['anomalies_created'], second['flags_created']),
                         (0, 0, 0))
        self.assertEqual(PaymentException.objects.count(), before)

    def test_checks_never_change_payments(self):
        self._scenario()
        snap = list(ExternalPayment.objects.order_by('pk').values())
        S.run_exception_checks(days=7)
        self.assertEqual(list(ExternalPayment.objects.order_by('pk').values()), snap)

    def test_command_off_by_default_and_force_runs(self):
        self._scenario()
        self.assertIn('Skipped', self._run())
        self.assertFalse(PaymentException.objects.exists())
        self.assertIn('Checked', self._run('--force'))
        self.assertTrue(PaymentException.objects.exists())

    def test_command_runs_when_switch_on(self):
        self._scenario()
        SystemSetting.objects.create(key='payments.exception_checks_enabled', label='x',
                                     value='true', value_type='boolean')
        self.assertIn('Checked', self._run('--days', '3'))
        self.assertTrue(AbuseFlag.objects.filter(flag_type='payment_anomaly').exists())

    def test_seeded_switch_defaults_off(self):
        from apps.config.management.commands.seed_config import DEFAULT_SETTINGS
        row = next(d for d in DEFAULT_SETTINGS if d.get('key') == 'payments.exception_checks_enabled')
        self.assertEqual((row['value'], row['value_type'], row['label']),
                         ('false', 'boolean', 'فحص استثناءات المدفوعات تلقائياً'))
