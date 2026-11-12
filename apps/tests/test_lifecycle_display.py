"""
Data lifecycle stage 3, task 10 -- a file retention removed shows a calm note, not a broken file.
"""
import datetime

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework import serializers

from apps.data_lifecycle.models import HeldFile
from apps.invoices.models import SupplierInvoice
from apps.tasks.models import OperationalTask, TaskAttachment
from apps.tasks.serializers import TaskAttachmentSerializer
from apps.tests.factories import make_branch, make_user
from apps.users.models import RoleModuleAccess
from core.middleware import module_access


def _held(att, field='file', restored=False, moved=None, model='tasks.TaskAttachment'):
    now = moved or timezone.now()
    return HeldFile.objects.create(
        original_path='x/a.png', hold_path='h.png', rule_key='r', sha256='0' * 64, moved_at=now,
        purge_after=now + datetime.timedelta(days=30),
        restored_at=timezone.now() if restored else None,
        primary_model=model, primary_pk=str(att.pk), primary_field=field)


class RemovedNoteTests(TestCase):
    def setUp(self):
        owner = make_user('disp_owner', role='admin', branch=make_branch())[1]
        self.task = OperationalTask.objects.create(title='t', created_by=owner, assigned_to=owner)

    def _att(self, name=''):
        return TaskAttachment.objects.create(task=self.task, file=name)

    def test_removed_field_reports_date(self):
        att = self._att()
        held = _held(att)
        data = TaskAttachmentSerializer(att).data
        self.assertEqual(data['retention_removed'], {'file': timezone.localtime(held.moved_at).date().isoformat()})

    def test_never_had_file_reports_nothing(self):
        data = TaskAttachmentSerializer(self._att()).data
        self.assertNotIn('retention_removed', data)

    def test_restored_file_shows_no_note(self):
        att = self._att()
        _held(att, restored=True)
        self.assertNotIn('retention_removed', TaskAttachmentSerializer(att).data)

    def test_present_file_shows_no_note(self):
        att = self._att('tasks/a.png')
        _held(att)
        self.assertNotIn('retention_removed', TaskAttachmentSerializer(att).data)

    def test_newest_held_file_wins(self):
        att = self._att()
        _held(att, moved=timezone.now() - datetime.timedelta(days=5))
        newest = _held(att)
        data = TaskAttachmentSerializer(att).data
        self.assertEqual(data['retention_removed']['file'], timezone.localtime(newest.moved_at).date().isoformat())

    def _list_queries(self, atts):
        with CaptureQueriesContext(connection) as ctx:
            data = TaskAttachmentSerializer(atts, many=True).data
        return len(ctx), data

    def test_list_makes_one_lookup_query(self):
        with_file = [self._att('tasks/a%d.png' % i) for i in range(3)]
        base, _ = self._list_queries(with_file)
        removed = [self._att() for _ in range(4)]
        for a in removed:
            _held(a)
        n, data = self._list_queries(with_file + removed)
        self.assertEqual(n - base, 1)
        self.assertEqual(sum('retention_removed' in d for d in data), 4)

    def test_list_without_empty_field_makes_no_query(self):
        n, _ = self._list_queries([self._att('tasks/a.png')])
        self.assertEqual(n, 0)


class _TaskWithAttachments(serializers.ModelSerializer):
    """A nested many=True field, as on the reservation, call center and task detail serializers."""
    attachments = TaskAttachmentSerializer(many=True, read_only=True)

    class Meta:
        model = OperationalTask
        fields = ('id', 'attachments')


class NestedListTests(TestCase):
    def test_nested_list_makes_one_lookup_for_the_page(self):
        owner = make_user('disp_nested', role='admin', branch=make_branch())[1]
        task = OperationalTask.objects.create(title='t', created_by=owner, assigned_to=owner)
        for _ in range(4):
            _held(TaskAttachment.objects.create(task=task, file=''))
        with CaptureQueriesContext(connection) as ctx:
            data = _TaskWithAttachments(task).data
        lookups = [q for q in ctx.captured_queries if 'data_lifecycle_heldfile' in q['sql']]
        self.assertEqual(len(lookups), 1)
        self.assertEqual(sum('retention_removed' in d for d in data['attachments']), 4)


class ReOcrRemovedImageTests(TestCase):
    def setUp(self):
        module_access.clear_cache()
        for a in ('view', 'edit'):
            RoleModuleAccess.objects.create(role='purchasing', module='invoices', action=a)
        branch = make_branch()
        self.client_ = make_user('disp_pur', role='purchasing', branch=branch)[2]
        self.inv = SupplierInvoice.objects.create(branch=branch)

    def tearDown(self):
        module_access.clear_cache()

    def test_reocr_on_removed_image_returns_message(self):
        _held(self.inv, field='source_image', model='invoices.SupplierInvoice')
        resp = self.client_.post(f'/api/invoices/invoices/{self.inv.pk}/run-ocr/', {}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('الاحتفاظ', resp.json()['detail'])
        self.inv.refresh_from_db()
        self.assertNotEqual(self.inv.status, 'processing')

    def test_reocr_without_any_image_keeps_plain_message(self):
        resp = self.client_.post(f'/api/invoices/invoices/{self.inv.pk}/run-ocr/', {}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertNotIn('الاحتفاظ', resp.json()['detail'])
