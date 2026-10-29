"""
Mass assignment — workflow and points records (Batch 4, Z-10b).

Before: generic updates took fields only the workflow should set. A PATCH could move a stock-count
session to "variance ready", mark a follow-up done or a shortage list submitted — exactly what
gamification scores — without doing the work; anyone logged in could reassign or cancel anyone's
task; a call-center agent could set their own call-quality score or re-attribute a call; an
availability list's status / operator could be rewritten; an incentive adjustment could be added
to or changed in a period whose settlement is already finalized, or written for yourself; and an
invoice bundle's processing state could be forged.

Now: those fields are read-only or the generic update is closed where no screen uses it; status
moves only through the workflow actions (submit / close / outcome / complete / quality …).
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.callcenter.models import CallLog
from apps.followups.models import FollowUpTask
from apps.incentives.models import AdjustmentEntry, IncentiveProgram, IncentiveSettlement
from apps.invoices.models import InvoiceBatch
from apps.shortage.models import ShortageList
from apps.stockcount.models import StockCountSession
from apps.supply.models import AvailabilityBatch
from apps.tasks.models import OperationalTask
from apps.tests.factories import make_branch, make_customer, make_user
from core.middleware import module_access

from .fixtures import bearer_client, seed_code_matrix


@override_settings(RBAC_ENFORCEMENT='log')
class _Base(TestCase):

    def setUp(self):
        seed_code_matrix()
        self.branch = make_branch()
        _, self.admin_profile, _ = make_user('z10b_admin', role='admin', branch=self.branch, access_all=True)
        _, self.other, _ = make_user('z10b_other', role='pharmacist', branch=self.branch)
        self.c = bearer_client(self.admin_profile.user)

    def tearDown(self):
        module_access.clear_cache()


class PointsWorkflowTests(_Base):

    def test_a_stock_count_reaches_variance_only_by_counting(self):
        s = StockCountSession.objects.create(name='s', branch_code='B01', doccodes=['10'])
        r = self.c.patch(f'/api/stockcount/sessions/{s.pk}/',
                         {'status': 'variance_ready', 'variance_at': timezone.now().isoformat()}, format='json')
        self.assertEqual(r.status_code, 405)
        s.refresh_from_db()
        self.assertEqual((s.status, s.variance_at), ('draft', None))

    def test_a_follow_up_is_done_only_through_its_actions(self):
        t = FollowUpTask.objects.create(customer=make_customer(), branch=self.branch, task_type='refill',
                                        status='pending', due_date=date.today())
        r = self.c.patch(f'/api/followups/tasks/{t.pk}/', {'status': 'done', 'assigned_to': self.other.pk,
                                                            'completed_at': timezone.now().isoformat()},
                         format='json')
        self.assertEqual(r.status_code, 405)
        t.refresh_from_db()
        self.assertEqual((t.status, t.assigned_to_id, t.completed_at), ('pending', None, None))

    def test_a_shortage_list_is_submitted_only_through_submit(self):
        sl = ShortageList.objects.create(branch=self.branch, status='open', created_by=self.admin_profile)
        self.assertEqual(self.c.patch(f'/api/shortage/lists/{sl.pk}/', {'status': 'submitted'},
                                      format='json').status_code, 405)
        sl.refresh_from_db()
        self.assertEqual(sl.status, 'open')

    def test_submit_still_submits(self):
        sl = ShortageList.objects.create(branch=self.branch, status='open', created_by=self.admin_profile)
        self.assertEqual(self.c.post(f'/api/shortage/lists/{sl.pk}/submit/').status_code, 200)


class TaskTests(_Base):

    def setUp(self):
        super().setUp()
        self.owner = self.other
        self.task = OperationalTask.objects.create(title='t', created_by=self.owner, assigned_to=self.owner)
        _, self.outsider, _ = make_user('z10b_outsider', role='salesperson', branch=self.branch)

    def test_an_outsider_cannot_reassign_or_cancel_someone_elses_task(self):
        c = bearer_client(self.outsider.user)
        r = c.patch(f'/api/tasks/{self.task.pk}/', {'assigned_to': self.outsider.pk, 'status': 'cancelled'},
                    format='json')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(c.delete(f'/api/tasks/{self.task.pk}/').status_code, 403)
        self.task.refresh_from_db()
        self.assertEqual((self.task.assigned_to_id, self.task.status), (self.owner.pk, 'open'))

    def test_the_assignee_and_a_manager_still_edit_it(self):
        own = bearer_client(self.owner.user)
        self.assertEqual(own.patch(f'/api/tasks/{self.task.pk}/', {'priority': 'high'}, format='json').status_code, 200)
        self.assertEqual(self.c.patch(f'/api/tasks/{self.task.pk}/', {'priority': 'low'}, format='json').status_code, 200)


class CallLogTests(_Base):

    def test_quality_score_and_handler_are_not_client_set(self):
        log = CallLog.objects.create(phone_number='01012345678', direction='inbound', status='no_answer',
                                     purpose='general', handled_by=self.admin_profile)
        r = self.c.patch(f'/api/callcenter/calls/{log.pk}/', {'quality_score': 100, 'handled_by': self.other.pk,
                                                              'status': 'answered'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        log.refresh_from_db()
        self.assertEqual((log.quality_score, log.handled_by_id, log.status), (None, self.admin_profile.pk, 'answered'))


class AvailabilityTests(_Base):

    def test_status_and_operator_are_not_client_set(self):
        b = AvailabilityBatch.objects.create(supplier_name='S', operator=self.admin_profile)
        r = self.c.patch(f'/api/supply/availability/{b.pk}/', {'status': 'actioned', 'operator': self.other.pk,
                                                               'notes': 'n'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        b.refresh_from_db()
        self.assertEqual((b.status, b.operator_id, b.notes), ('open', self.admin_profile.pk, 'n'))


class IncentiveAdjustmentTests(_Base):

    def setUp(self):
        super().setUp()
        self.program = IncentiveProgram.objects.create(name='p', start_date=date(2026, 9, 1), end_date=date(2026, 9, 30))
        self.period = {'period_start': '2026-09-01', 'period_end': '2026-09-30'}
        IncentiveSettlement.objects.create(program=self.program, user=self.other, period_start=date(2026, 9, 1),
                                           period_end=date(2026, 9, 30), is_finalized=True)

    def _post(self, user, **period):
        return self.c.post('/api/incentives/adjustments/', {'program': self.program.pk, 'user': user.pk,
                                                            'amount': '500', 'reason': 'r', **(period or self.period)},
                           format='json')

    def test_no_adjustment_is_added_to_a_finalized_settlement(self):
        self.assertEqual(self._post(self.other).status_code, 409)
        self.assertFalse(AdjustmentEntry.objects.exists())

    def test_an_adjustment_is_not_moved_into_a_finalized_settlement(self):
        a = AdjustmentEntry.objects.create(program=self.program, user=self.other, amount=Decimal('5'), reason='r',
                                           period_start=date(2026, 10, 1), period_end=date(2026, 10, 31))
        r = self.c.patch(f'/api/incentives/adjustments/{a.pk}/', {**self.period, 'amount': '900'}, format='json')
        self.assertEqual(r.status_code, 409)
        a.refresh_from_db()
        self.assertEqual(a.amount, Decimal('5'))

    def test_no_one_adjusts_their_own_incentive(self):
        r = self._post(self.admin_profile, period_start='2026-10-01', period_end='2026-10-31')
        self.assertEqual(r.status_code, 403)
        self.assertFalse(AdjustmentEntry.objects.exists())

    def test_an_open_period_is_still_adjusted(self):
        self.assertEqual(self._post(self.other, period_start='2026-10-01', period_end='2026-10-31').status_code, 201)


class InvoiceBatchTests(_Base):

    def test_a_bundles_processing_state_is_not_client_set(self):
        b = InvoiceBatch.objects.create(branch=self.branch, status='processing')
        r = self.c.patch(f'/api/invoices/invoice-batches/{b.pk}/', {'status': 'ready', 'detected_count': 99},
                         format='json')
        self.assertEqual(r.status_code, 405)
        b.refresh_from_db()
        self.assertEqual(b.status, 'processing')
