"""
Outbound call lists on follow-ups: selection rules, round-robin split, cap,
one notice per agent, close, permissions.
"""
from unittest import mock

from django.test import TestCase

from apps.customers.models import Customer
from apps.followups import call_lists
from apps.followups.models import CallList, FollowUpTask, RefillReminderOptOut
from apps.notifications.models import Notification
from .factories import make_admin, make_call_center, make_customer, make_pharmacist

URL = '/api/followups/call-lists/'


class CallListTests(TestCase):

    def setUp(self):
        self.admin_user, self.admin, self.client_admin = make_admin('cl_admin')
        _, self.a1, self.client_a1 = make_call_center('cl_a1')
        _, self.a2, _ = make_call_center('cl_a2')
        self.customers = [make_customer(f'عميل {i}', f'0101234{i:04d}') for i in range(6)]
        Customer.objects.filter(pk__in=[c.pk for c in self.customers]).update(
            segment='at_risk', days_since_last_visit=60)

    def _body(self, **kw):
        b = {'name': 'استرجاع العملاء', 'script': 'السلام عليكم…',
             'criteria': {'segments': ['at_risk'], 'inactive_days_min': 30},
             'agent_ids': [self.a1.pk, self.a2.pk]}
        b.update(kw)
        return b

    def test_create_splits_evenly_and_skips_ineligible(self):
        Customer.objects.filter(pk=self.customers[0].pk).update(phone='')
        RefillReminderOptOut.objects.create(customer=self.customers[1])
        FollowUpTask.objects.create(customer=self.customers[2], due_date='2026-11-09', status='pending')
        Customer.objects.filter(pk=self.customers[3].pk).update(days_since_last_visit=5)

        self.assertEqual(self.client_admin.post(f'{URL}preview/', self._body(), format='json').data['matching'], 2)
        r = self.client_admin.post(URL, self._body(), format='json')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data['size'], 2)
        tasks = FollowUpTask.objects.filter(call_list_id=r.data['id'])
        self.assertEqual(sorted(t.assigned_to_id for t in tasks), sorted([self.a1.pk, self.a2.pk]))
        self.assertTrue(all(t.task_type == 'custom' and t.assignments.count() == 1 for t in tasks))
        # one notice per agent, not one per task
        self.assertEqual(Notification.objects.filter(dedup_key=f'call_list:{r.data["id"]}').count(), 2)

    def test_tasks_show_in_agent_queue_with_script(self):
        self.client_admin.post(URL, self._body(agent_ids=[self.a1.pk]), format='json')
        q = self.client_a1.get('/api/followups/tasks/my-queue/').data['queue']
        self.assertEqual(len(q), 6)
        self.assertEqual(q[0]['call_list_script'], 'السلام عليكم…')

    def test_cap(self):
        with mock.patch.object(CallList, 'MAX_SIZE', 4):
            r = self.client_admin.post(URL, self._body(), format='json')
            self.assertEqual(r.data['size'], 4)
            self.assertTrue(self.client_admin.post(f'{URL}preview/', self._body(), format='json').data['capped'] is False)

    def test_progress_and_close(self):
        cl_id = self.client_admin.post(URL, self._body(), format='json').data['id']
        t = FollowUpTask.objects.filter(call_list_id=cl_id).first()
        t.status = 'done'
        t.save()
        row = next(x for x in self.client_admin.get(URL).data if x['id'] == cl_id)
        self.assertEqual((row['progress']['total'], row['progress']['done']), (6, 1))
        r = self.client_admin.post(f'{URL}{cl_id}/close/')
        self.assertEqual(r.data['cancelled_tasks'], 5)
        self.assertEqual(CallList.objects.get(pk=cl_id).status, 'closed')

    def test_validation_and_permissions(self):
        self.assertEqual(self.client_admin.post(URL, self._body(name=''), format='json').status_code, 400)
        self.assertEqual(self.client_admin.post(URL, self._body(criteria={}), format='json').status_code, 400)
        self.assertEqual(self.client_admin.post(URL, self._body(agent_ids=[]), format='json').status_code, 400)
        _, _, pharm = make_pharmacist('cl_ph')
        self.assertEqual(pharm.post(URL, self._body(), format='json').status_code, 403)
        # call-center agents may create (owner decision)
        self.assertEqual(self.client_a1.post(URL, self._body(), format='json').status_code, 201)

    def test_preview_respects_branch_scope(self):
        from core import branch_scope
        with mock.patch.object(branch_scope, 'branch_ids', return_value=[987654]):
            self.assertEqual(call_lists.preview({'segments': ['at_risk']}, self.admin_user)['matching'], 0)
