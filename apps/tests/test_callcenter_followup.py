"""
Call → follow-up: scheduling a follow-up from a SAVED call keeps the task type and
the reminder chosen in the modal (bug: create_followup used to read only
due_date/notes/item, so every task became 'refill' with no reminder).
"""
import datetime

from django.test import TestCase
from django.utils import timezone

from apps.callcenter.models import CallLog
from apps.followups.models import FollowUpTask
from .factories import make_branch, make_call_center, make_customer, make_item


class CreateFollowupFromCallTests(TestCase):
    def setUp(self):
        self.branch = make_branch()
        _, self.profile, self.client_ = make_call_center()
        self.customer = make_customer()
        self.call = CallLog.objects.create(phone_number=self.customer.phone, customer=self.customer,
                                           branch=self.branch)
        self.url = f'/api/callcenter/calls/{self.call.pk}/create-followup/'
        self.due = (timezone.localdate() + datetime.timedelta(days=3)).isoformat()

    def test_type_and_reminder_kept(self):
        remind = (timezone.now() + datetime.timedelta(days=2)).replace(microsecond=0)
        r = self.client_.post(self.url, {'due_date': self.due, 'task_type': 'chronic',
                                         'reminder_at': remind.isoformat(), 'notes': 'اتصل بعد يومين'},
                              format='json')
        self.assertEqual(r.status_code, 201, r.content)
        task = FollowUpTask.objects.get(pk=r.json()['task_id'])
        self.assertEqual(task.task_type, 'chronic')
        self.assertEqual(task.reminder_at, remind)
        self.assertEqual(task.status, 'pending')
        self.assertEqual(task.customer, self.customer)
        self.assertEqual(task.assigned_to, self.profile)
        self.call.refresh_from_db()
        self.assertEqual(self.call.followup_task, task)

    def test_defaults_and_item(self):
        item = make_item()
        r = self.client_.post(self.url, {'due_date': self.due, 'item_id': item.pk}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        task = FollowUpTask.objects.get(pk=r.json()['task_id'])
        self.assertEqual(task.task_type, 'refill')        # model default when none chosen
        self.assertIsNone(task.reminder_at)
        self.assertEqual(task.item, item)

    def test_validation(self):
        self.assertEqual(self.client_.post(self.url, {}, format='json').status_code, 400)
        r = self.client_.post(self.url, {'due_date': self.due, 'task_type': 'nope'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertFalse(FollowUpTask.objects.exists())
        no_customer = CallLog.objects.create(phone_number='01099999999', branch=self.branch)
        r = self.client_.post(f'/api/callcenter/calls/{no_customer.pk}/create-followup/',
                              {'due_date': self.due}, format='json')
        self.assertEqual(r.status_code, 400)
