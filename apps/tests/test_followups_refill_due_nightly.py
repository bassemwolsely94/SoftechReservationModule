"""
Top-10 C08 (refill-due call list from buying behaviour) + C09 (scheduled follow-up pipeline,
stale auto-close, backlog retirement).

C08: the interval rule, the due window, consent, ranking by expected value, task anchoring, one call a
month, phone masking in the preview, branch scope and permission.
C09: the scheduler job exists, the stale rule (call-list / pinned tasks untouched, audited), the
nightly run is idempotent and switchable, and the backlog command changes nothing unless --apply.
"""
import datetime as dt
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.customers import consent
from apps.customers.models import Customer, PurchaseHistory, PurchaseHistoryLine
from apps.followups import call_lists, nightly, refill_due, services
from apps.followups.models import CallList, ChronicMedicationProfile, FollowUpTask

from .factories import make_admin, make_branch, make_call_center, make_customer, make_item, make_pharmacist

URL = '/api/followups/call-lists/'
TODAY = dt.date(2026, 11, 19)
D = dt.date


class IntervalRuleTests(SimpleTestCase):

    def test_median_gap_of_regular_purchases(self):
        dates = [D(2026, 7, 1), D(2026, 7, 31), D(2026, 8, 30), D(2026, 9, 29)]
        interval, eps = refill_due.usual_interval(dates, min_purchases=3, last_n=6, min_interval=7, max_interval=120)
        self.assertEqual((interval, len(eps)), (30, 4))

    def test_too_few_purchases_is_not_regular(self):
        interval, _ = refill_due.usual_interval([D(2026, 7, 1), D(2026, 7, 31)], min_purchases=3, last_n=6,
                                                min_interval=7, max_interval=120)
        self.assertIsNone(interval)

    def test_buys_within_a_week_are_one_episode(self):
        dates = [D(2026, 7, 1), D(2026, 7, 3), D(2026, 7, 31), D(2026, 8, 30)]
        interval, eps = refill_due.usual_interval(dates, min_purchases=3, last_n=6, min_interval=7, max_interval=120)
        self.assertEqual((interval, len(eps)), (30, 3))

    def test_median_ignores_one_long_gap_and_only_last_n_count(self):
        # an old 90-day gap falls outside the last 4 episodes; one 60-day gap does not move the median
        dates = [D(2026, 1, 1), D(2026, 4, 1), D(2026, 5, 1), D(2026, 5, 31), D(2026, 7, 30)]
        interval, _ = refill_due.usual_interval(dates, min_purchases=3, last_n=4, min_interval=7, max_interval=120)
        self.assertEqual(interval, 30)

    def test_interval_outside_bounds_is_not_regular(self):
        dates = [D(2025, 1, 1), D(2025, 6, 1), D(2025, 11, 1)]
        self.assertIsNone(refill_due.usual_interval(dates, min_purchases=3, last_n=6, min_interval=7,
                                                    max_interval=120)[0])

    def test_due_window(self):
        kw = {'overdue_min': 0, 'ahead': 3, 'max_lapse': 180}
        last = D(2026, 10, 20)
        self.assertEqual(refill_due.due_state(last, 30, TODAY, **kw), (True, D(2026, 11, 19), 0))
        self.assertTrue(refill_due.due_state(last, 32, TODAY, **kw)[0])          # due in 2 days (ahead 3)
        self.assertFalse(refill_due.due_state(last, 40, TODAY, **kw)[0])         # due in 10 days
        self.assertFalse(refill_due.due_state(D(2026, 4, 1), 30, TODAY, **kw)[0])   # lapsed > 180 days
        self.assertFalse(refill_due.due_state(last, 30, TODAY, overdue_min=7, ahead=0, max_lapse=180)[0])


def _when(d):
    return timezone.make_aware(dt.datetime.combine(d, dt.time(12, 0)))


class _Sales:
    seq = 0

    def sale(self, customer, item, d, total='100', channel='91', doc='115'):
        _Sales.seq += 1
        ph = PurchaseHistory.objects.create(
            customer=customer, softech_invoice_id=f'T-{_Sales.seq}-{customer.pk}', branch=self.branch,
            doc_code=doc, invoice_date=_when(d), sales_channel=channel,
            softech_phcode=customer.softech_pic or '', total_amount=Decimal(total))
        PurchaseHistoryLine.objects.create(purchase=ph, item=item, quantity=1, unit_price=Decimal(total),
                                           line_total=Decimal(total))
        return ph

    def regular(self, customer, item, total='100', every=30, n=4, last_days_ago=31):
        last = timezone.localdate() - dt.timedelta(days=last_days_ago)
        for k in range(n):
            self.sale(customer, item, last - dt.timedelta(days=every * k), total=total)


class RefillDueListTests(_Sales, TestCase):

    def setUp(self):
        cache.clear()
        self.branch = make_branch()
        self.user, self.admin, self.client_admin = make_admin('rd_admin')
        _, self.agent, _ = make_call_center('rd_agent')
        self.item = make_item('دواء ضغط', 'RD1')
        self.item2 = make_item('دواء سكر', 'RD2')
        self.c_hi = self._cust('عميل كبير', '01011110001', 'PIC1')
        self.c_lo = self._cust('عميل صغير', '01011110002', 'PIC2')
        self.regular(self.c_hi, self.item, total='400')
        self.regular(self.c_lo, self.item, total='100')
        for c in (self.c_hi, self.c_lo):
            consent.record(c, consent.REFILL, True, channel='call', source='staff')

    def _cust(self, name, phone, pic):
        c = make_customer(name, phone)
        Customer.objects.filter(pk=c.pk).update(softech_pic=pic, preferred_branch=self.branch)
        c.refresh_from_db()
        return c

    def _body(self, **kw):
        b = {'name': 'موعد صرف', 'script': 'علاجك لسه زي ما هو؟', 'criteria': {'refill_due': True},
             'agent_ids': [self.agent.pk]}
        b.update(kw)
        return b

    def test_due_customers_and_ranking_by_expected_value(self):
        due = refill_due.due_customers()
        self.assertEqual(set(due), {self.c_hi.pk, self.c_lo.pk})
        self.assertEqual(due[self.c_hi.pk]['items'][0]['interval'], 30)
        self.assertEqual(due[self.c_hi.pk]['value'], Decimal('400.00'))
        self.assertEqual(refill_due.rank(due), [self.c_hi.pk, self.c_lo.pk])

    def test_excluded_buyers(self):
        walkin = self._cust('حساب نقدي', '01011110003', 'ACCT-1')
        Customer.objects.filter(pk=walkin.pk).update(is_account_placeholder=True)
        contract = self._cust('تعاقد', '01011110004', 'PIC4')
        self.regular(walkin, self.item)
        for k in range(4):                                  # contract channel — not in CHANNELS
            self.sale(contract, self.item, timezone.localdate() - dt.timedelta(days=31 + 30 * k), channel='10')
        returns = self._cust('مرتجع', '01011110005', 'PIC5')
        for k in range(4):                                  # doc 30 = return, not a sale
            self.sale(returns, self.item, timezone.localdate() - dt.timedelta(days=31 + 30 * k), doc='30')
        self.assertEqual(set(refill_due.due_customers()), {self.c_hi.pk, self.c_lo.pk})

    def test_consent_filter(self):
        no_answer = self._cust('بدون موافقة', '01011110006', 'PIC6')
        refused = self._cust('رافض', '01011110007', 'PIC7')
        self.regular(no_answer, self.item)
        self.regular(refused, self.item)
        consent.record(refused, consent.REFILL, False, channel='call', source='staff')
        closed = self._cust('ملف مغلق', '01011110008', 'PIC8')
        self.regular(closed, self.item)
        consent.record(closed, consent.REFILL, True, channel='call', source='staff')
        Customer.objects.filter(pk=closed.pk).update(softech_status='0')

        p = call_lists.preview({'refill_due': True}, self.user)
        self.assertEqual((p['matching'], p['due_in_scope'], p['skipped']), (2, 5, 3))
        with override_settings(FOLLOWUPS_REFILL_DUE_CONSENT='not_withdrawn'):
            cache.clear()
            ids = {r['customer_id'] for r in call_lists.preview({'refill_due': True}, self.user)['sample']}
        self.assertIn(no_answer.pk, ids)
        self.assertNotIn(refused.pk, ids)
        self.assertNotIn(closed.pk, ids)

    def test_create_ranks_anchors_and_never_sends(self):
        r = self.client_admin.post(URL, self._body(), format='json')
        self.assertEqual(r.status_code, 201, r.data)
        tasks = list(FollowUpTask.objects.filter(call_list_id=r.data['id']).order_by('pk'))
        self.assertEqual([t.customer_id for t in tasks], [self.c_hi.pk, self.c_lo.pk])
        t = tasks[0]
        self.assertEqual((t.task_type, t.item_id, t.phcode), ('custom', self.item.pk, 'PIC1'))
        self.assertEqual(t.source_sale_date, timezone.localdate() - dt.timedelta(days=31))
        self.assertIn('موعد إعادة صرف', t.notes)
        # the WhatsApp refill reminder reads refill / chronic tasks only
        from apps.followups import refill_reminders
        self.assertNotIn('custom', refill_reminders.TASK_TYPES)

    def test_bought_after_the_call_auto_closes(self):
        cl_id = self.client_admin.post(URL, self._body(), format='json').data['id']
        self.sale(self.c_hi, self.item, timezone.localdate())
        services.auto_close_followup_tasks_from_erp(since_minutes=60 * 24 * 3)
        st = dict(FollowUpTask.objects.filter(call_list_id=cl_id).values_list('customer_id', 'status'))
        self.assertEqual(st, {self.c_hi.pk: 'auto_closed', self.c_lo.pk: 'pending'})

    def test_one_refill_call_a_month(self):
        cl_id = self.client_admin.post(URL, self._body(), format='json').data['id']
        FollowUpTask.objects.filter(call_list_id=cl_id).update(status='done')
        self.assertEqual(call_lists.preview({'refill_due': True}, self.user)['matching'], 0)

    def test_preview_masks_phone(self):
        type(self.admin).objects.filter(pk=self.admin.pk).update(can_see_customer_phone=False)
        self.user.refresh_from_db()
        sample = self.client_admin.post(f'{URL}preview/', {'criteria': {'refill_due': True}}, format='json').data['sample']
        self.assertEqual(len(sample), 2)
        for row in sample:
            self.assertNotIn(row['phone'], ('01011110001', '01011110002'))
            self.assertTrue(row['phone'].startswith('•'))

    def test_branch_scope(self):
        from core import branch_scope
        with mock.patch.object(branch_scope, 'branch_ids', return_value={987654}):
            p = call_lists.preview({'refill_due': True}, self.user)
        self.assertEqual((p['matching'], p['due_in_scope']), (0, 0))

    def test_permissions(self):
        _, _, pharm = make_pharmacist('rd_ph')
        self.assertEqual(pharm.post(URL, self._body(), format='json').status_code, 403)
        from rest_framework.test import APIClient
        self.assertIn(APIClient().post(f'{URL}preview/', {'criteria': {'refill_due': True}},
                                       format='json').status_code, (401, 403))
        self.assertFalse(CallList.objects.exists())


@override_settings(FOLLOWUPS_NIGHTLY_ENABLED=True)
class NightlyAndBacklogTests(_Sales, TestCase):

    def setUp(self):
        self.branch = make_branch()
        self.user, self.admin, _ = make_admin('ny_admin')
        self.item = make_item('دواء مزمن', 'NY1')
        self.cust = make_customer('مريض', '01022220001')
        Customer.objects.filter(pk=self.cust.pk).update(softech_pic='NYPIC', preferred_branch=self.branch)
        self.cust.refresh_from_db()

    def _task(self, due_days_ago, created_days_ago=None, **kw):
        t = FollowUpTask.objects.create(customer=self.cust, item=self.item, task_type=kw.pop('task_type', 'refill'),
                                        due_date=timezone.localdate() - dt.timedelta(days=due_days_ago), **kw)
        FollowUpTask.objects.filter(pk=t.pk).update(
            created_at=timezone.now() - dt.timedelta(days=created_days_ago or due_days_ago))
        return t

    def test_scheduler_job_registered(self):
        from .test_scheduler_locks import SCHEDULER_JOB_GUARDS, _registered
        jobs = _registered()
        self.assertIn('followups_nightly', jobs)
        self.assertEqual(jobs['followups_nightly'].get('max_instances'), 1)
        self.assertTrue(jobs['followups_nightly'].get('replace_existing'))
        self.assertEqual(SCHEDULER_JOB_GUARDS['followups_nightly'][0], 'advisory_lock')

    def test_stale_rule_spares_call_list_and_pinned_tasks(self):
        stale = self._task(10)
        fresh = self._task(1)
        late_new = self._task(10, created_days_ago=1)        # created already late: gets its chance first
        cl = CallList.objects.create(name='x')
        listed = self._task(10, task_type='custom', call_list=cl)
        pinned = self._task(10, is_pinned=True)
        res = services.escalate_overdue_tasks(overdue_days=3)
        self.assertEqual(res['escalated'], 1)
        st = dict(FollowUpTask.objects.values_list('pk', 'status'))
        self.assertEqual(st[stale.pk], 'missed')
        for t in (fresh, late_new, listed, pinned):
            self.assertEqual(st[t.pk], 'pending')
        log = AuditLog.objects.filter(action='followup_auto_closed').latest('pk')
        self.assertEqual(log.new_data['task_ids'], [stale.pk])

    def test_nightly_generates_once_and_is_switchable(self):
        ChronicMedicationProfile.objects.create(item=self.item, expected_duration_days=30, followup_before_days=5)
        self.sale(self.cust, self.item, timezone.localdate() - dt.timedelta(days=26))
        with override_settings(FOLLOWUPS_NIGHTLY_ENABLED=False):
            self.assertNotIn('created', nightly.run())
            self.assertEqual(nightly.run(dry_run=True, force=True)['created'], 1)   # force ignores the switch
        self.assertFalse(FollowUpTask.objects.exists())
        dry = nightly.run(dry_run=True)
        self.assertEqual(dry['created'], 1)
        self.assertFalse(FollowUpTask.objects.exists())
        self.assertEqual(nightly.run()['created'], 1)
        self.assertEqual(nightly.run()['created'], 0)            # idempotent
        self.assertEqual(FollowUpTask.objects.get().task_type, 'refill')
        self.assertTrue(AuditLog.objects.filter(action='followup_nightly').exists())

    def test_nightly_auto_closes_a_bought_task(self):
        t = self._task(2, created_days_ago=2, phcode='NYPIC', source_sale_date=timezone.localdate() - dt.timedelta(days=32))
        self.sale(self.cust, self.item, timezone.localdate() - dt.timedelta(days=1))
        self.assertEqual(nightly.run()['auto_closed'], 1)
        t.refresh_from_db()
        self.assertEqual(t.status, 'auto_closed')

    def test_backlog_dry_run_changes_nothing(self):
        old = self._task(90)
        out = StringIO()
        call_command('retire_followup_backlog', stdout=out)
        self.assertIn('DRY RUN', out.getvalue())
        old.refresh_from_db()
        self.assertEqual(old.status, 'pending')
        self.assertFalse(AuditLog.objects.filter(action='followup_backlog_retired').exists())

    def test_backlog_apply_cancels_with_reason_and_audit(self):
        old = self._task(90)
        recent = self._task(10)
        cl = CallList.objects.create(name='x')
        listed = self._task(90, task_type='custom', call_list=cl)
        call_command('retire_followup_backlog', '--apply', stdout=StringIO())
        st = {t.pk: t for t in FollowUpTask.objects.all()}
        self.assertEqual(st[old.pk].status, 'cancelled')
        self.assertIn('لا تُحتسب', st[old.pk].result_note)
        self.assertEqual(st[recent.pk].status, 'pending')
        self.assertEqual(st[listed.pk].status, 'pending')
        self.assertEqual(FollowUpTask.objects.count(), 3)         # never deleted
        log = AuditLog.objects.get(action='followup_backlog_retired')
        self.assertEqual(log.new_data['task_ids'], [old.pk])

    def test_backlog_flags(self):
        with self.assertRaises(CommandError):
            call_command('retire_followup_backlog', '--apply', '--dry-run', stdout=StringIO())
        with self.assertRaises(CommandError):
            call_command('retire_followup_backlog', '--created-before', 'not-a-date', stdout=StringIO())
