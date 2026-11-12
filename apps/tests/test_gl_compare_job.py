"""Nightly ledger-vs-SOFTECH refresh and its freshness domain (finance-gl Plan 3, Task 11). SOFTECH is mocked."""
import datetime
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.finance.gl import compare
from apps.finance.gl.ledger import approve, save_draft
from apps.finance.gl.periods import month_period
from apps.finance.models import (FinancialPeriod, GLAccount, GLAccountGroup, GLComparisonLine,
                                 GLSoftechCheck)
from apps.sync import tasks
from apps.sync.freshness import get_freshness
from apps.users.models import StaffProfile

D = datetime.date
Z = Decimal('0')


class JobBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        u = User.objects.create_user(username='gl_job_u', password='x')
        cls.staff, _ = StaffProfile.objects.get_or_create(user=u)
        g = GLAccountGroup.objects.create(name='مجموعة اختبار', section='income', order=1)
        GLAccount.objects.create(code='9200', name='نقدية', group=g, nature='debit', account_type='asset')
        GLAccount.objects.create(code='9201', name='مبيعات', group=g, nature='credit', account_type='revenue')

    def post(self, day):
        e = save_draft(user=self.staff, entry_date=day, description='x', lines=[
            {'account_code': '9200', 'debit': Decimal('10'), 'credit': Z},
            {'account_code': '9201', 'debit': Z, 'credit': Decimal('10')}])
        return approve(e.id, user=self.staff)

    def month_with_entry(self, month):
        p = month_period(D(2026, month, 1))
        self.post(D(2026, month, 5))
        return p


@override_settings(GL_DRAFTING_SCHEDULE_ENABLED=True)
class JobTests(JobBase):
    def test_job_computes_open_months_only(self):
        mar, apr = self.month_with_entry(3), self.month_with_entry(4)
        may = month_period(D(2026, 5, 1))           # open, no entries: nothing to compute
        jun = self.month_with_entry(6)
        FinancialPeriod.objects.filter(pk=apr.pk).update(status='closed', is_closed=True)
        before = FinancialPeriod.objects.count()
        with mock.patch.object(compare, 'compute', return_value=[]) as comp:
            done = tasks._run_gl_compare_refresh()
        self.assertEqual(done, 2)
        self.assertEqual([c.args[0].pk for c in comp.call_args_list], [mar.pk, jun.pk])
        self.assertTrue(all(c.kwargs['user'] is None for c in comp.call_args_list))
        self.assertNotIn(may.pk, [c.args[0].pk for c in comp.call_args_list])
        self.assertEqual(FinancialPeriod.objects.count(), before)   # no period created

    def test_job_continues_after_month_failure(self):
        mar, apr = self.month_with_entry(3), self.month_with_entry(4)

        def fake(period, **kw):
            if period.pk == mar.pk:
                raise RuntimeError('softech down')
            return []
        with mock.patch.object(compare, 'compute', side_effect=fake) as comp, \
                self.assertLogs('elrezeiky.sync', level='ERROR'):
            done = tasks._run_gl_compare_refresh()
        self.assertEqual(done, 1)
        self.assertEqual(comp.call_count, 2)

    def test_busy_month_is_skipped(self):
        self.month_with_entry(3)
        with mock.patch.object(compare, 'refresh_lock') as lock, \
                mock.patch.object(compare, 'compute') as comp, \
                self.assertLogs('elrezeiky.sync', level='WARNING'):
            lock.return_value.__enter__.return_value = False
            self.assertEqual(tasks._run_gl_compare_refresh(), 0)
        comp.assert_not_called()

    @override_settings(GL_DRAFTING_SCHEDULE_ENABLED=False)
    def test_off_by_default_switch_does_nothing(self):
        self.month_with_entry(3)
        with mock.patch.object(compare, 'compute') as comp, \
                mock.patch.object(tasks, '_gl_compare_off_logged', False):
            self.assertIsNone(tasks._run_gl_compare_refresh())
        comp.assert_not_called()

    def test_catchup_runs_only_when_last_comparison_is_over_a_day_old(self):
        mar = self.month_with_entry(3)
        chk = GLSoftechCheck.objects.create(key='t_job', label='t', kind='movement', account_codes=['9201'],
                                            source='sales', sign='credit')
        line = GLComparisonLine.objects.create(period=mar, softech_check=chk, ledger_amount=Z,
                                               softech_amount=Z, difference=Z, computed_at=timezone.now())
        with mock.patch.object(tasks, '_run_gl_compare_refresh', return_value=1) as job:
            self.assertIsNone(tasks._run_gl_compare_catchup())
            job.assert_not_called()
            GLComparisonLine.objects.filter(pk=line.pk).update(
                computed_at=timezone.now() - datetime.timedelta(days=2))
            tasks._run_gl_compare_catchup()
            job.assert_called_once()

    def test_catchup_runs_when_nothing_was_ever_computed(self):
        with mock.patch.object(tasks, '_run_gl_compare_refresh', return_value=0) as job:
            tasks._run_gl_compare_catchup()
        job.assert_called_once()


class FreshnessAndScheduleTests(JobBase):
    def test_freshness_domain_reads_latest_computed_at(self):
        mar = month_period(D(2026, 3, 1))
        chk = GLSoftechCheck.objects.create(key='t_job2', label='t', kind='movement', account_codes=['9201'],
                                            source='sales', sign='credit')
        self.assertIsNone(get_freshness(['gl_compare'])['domains']['gl_compare']['last_success_at'])
        old, new = timezone.now() - datetime.timedelta(days=3), timezone.now() - datetime.timedelta(hours=1)
        for party, at in (('a', old), ('b', new)):
            ln = GLComparisonLine.objects.create(period=mar, softech_check=chk, party_code=party, ledger_amount=Z,
                                                 softech_amount=Z, difference=Z)
            GLComparisonLine.objects.filter(pk=ln.pk).update(computed_at=at)   # auto_now: set it past save()
        out = get_freshness(['gl_compare'])['domains']['gl_compare']
        self.assertEqual(out['label_ar'], 'مقارنة الحسابات بسوفتيك')
        self.assertEqual(datetime.datetime.fromisoformat(out['last_success_at']), new)

    def test_registered_at_0330_and_catchup(self):
        from .test_scheduler_jobs import _FakeScheduler
        captured = {}

        class _Capture(_FakeScheduler):
            def add_job(self, func, trigger, *args, **kwargs):
                captured[kwargs.get('id')] = (trigger, kwargs)
                super().add_job(func, trigger, *args, **kwargs)

        with mock.patch.object(tasks, 'BackgroundScheduler', _Capture), \
                mock.patch.object(tasks, '_patch_apscheduler_for_python312', lambda: None), \
                mock.patch.object(tasks, '_scheduler', None):
            tasks.start_scheduler()
        trig, job = captured['gl_compare_refresh']
        self.assertEqual((trig, job['hour'], job['minute'], job['max_instances']), ('cron', 3, 30, 1))
        self.assertEqual(captured['gl_compare_catchup'][0], 'date')
