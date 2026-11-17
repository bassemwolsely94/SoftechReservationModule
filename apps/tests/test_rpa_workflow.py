from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.audit.models import AuditLog
from apps.rpa import workflow
from apps.rpa.models import RpaDocument, RpaJob, RpaLine, RpaRecipe, RpaScreen
from apps.tests.factories import make_branch
from apps.users.models import StaffProfile


def _staff(name, role='admin'):
    user = get_user_model().objects.create_user(username=name, password='x')
    return StaffProfile.objects.get_or_create(user=user, defaults={'role': role})[0]


class _Base(TestCase):
    def setUp(self):
        self.uploader = _staff('t5_up')
        self.approver = _staff('t5_ap')
        self.screen = RpaScreen.objects.get(key='issue_125')
        self.job = RpaJob.objects.create(screen=self.screen, branch=make_branch('T5A', 'T5A'),
                                         created_by=self.uploader)
        self.doc = RpaDocument.objects.create(job=self.job, seq=1)
        RpaLine.objects.create(document=self.doc, row_no=2, itemcode='1', qty=1, status='matched')

    def _recipe(self, version, status='approved', creator=None):
        return RpaRecipe.objects.create(screen=self.screen, version=version, status=status,
                                        created_by=creator or self.uploader)


class JobApprovalTests(_Base):
    def test_uploader_cannot_approve(self):
        self._recipe(1)
        with self.assertRaises(PermissionDenied):
            workflow.approve_job(self.job, self.uploader)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, 'uploaded')

    def test_unmatched_line_blocks_approval(self):
        self._recipe(1)
        RpaLine.objects.create(document=self.doc, row_no=3, itemcode='9', qty=1, status='unmatched')
        with self.assertRaises(ValidationError):
            workflow.approve_job(self.job, self.approver)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, 'uploaded')

    def test_approval_freezes_latest_approved_recipe(self):
        self._recipe(1, 'retired')
        self._recipe(2)
        job = workflow.approve_job(self.job, self.approver)
        self.assertEqual(job.recipe.version, 2)
        self.assertEqual(job.status, 'approved')
        self.assertEqual(job.approved_by, self.approver)
        self.assertIsNotNone(job.approved_at)
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.status, 'approved')
        self.assertTrue(AuditLog.objects.filter(action='rpa_job_approved').exists())

    def test_no_approved_recipe_blocks(self):
        self._recipe(1, 'draft')
        with self.assertRaises(ValidationError):
            workflow.approve_job(self.job, self.approver)

    def test_matrix_permission_required(self):
        self._recipe(1)
        with self.assertRaises(PermissionDenied):
            workflow.approve_job(self.job, _staff('t5_view', 'viewer'))

    def test_already_approved_job_refused(self):
        self._recipe(1)
        workflow.approve_job(self.job, self.approver)
        with self.assertRaises(ValidationError):
            workflow.approve_job(self.job, self.approver)


class RecipeApprovalTests(_Base):
    def test_recipe_creator_cannot_approve_own(self):
        recipe = self._recipe(1, 'draft')
        with self.assertRaises(PermissionDenied):
            workflow.approve_recipe(recipe, self.uploader)

    def test_non_admin_cannot_approve_recipe(self):
        recipe = self._recipe(1, 'draft')
        with self.assertRaises(PermissionDenied):
            workflow.approve_recipe(recipe, _staff('t5_ph', 'pharmacist'))

    def test_new_recipe_approval_retires_previous(self):
        old = self._recipe(1)
        new = self._recipe(2, 'draft')
        result = workflow.approve_recipe(new, self.approver)
        old.refresh_from_db()
        self.assertEqual(old.status, 'retired')
        self.assertEqual(result.status, 'approved')
        self.assertEqual(result.approved_by, self.approver)
        log = AuditLog.objects.get(action='rpa_recipe_approved')
        self.assertEqual(str(old.id), str(log.old_data.get('previous_recipe_id')))

    def test_only_draft_can_be_approved(self):
        recipe = self._recipe(1, 'retired')
        with self.assertRaises(ValidationError):
            workflow.approve_recipe(recipe, self.approver)


class CancelTests(_Base):
    def test_cancel_refused_when_in_progress(self):
        self.doc.status = 'in_progress'
        self.doc.save()
        with self.assertRaises(ValidationError):
            workflow.cancel_job(self.job, self.uploader, 'x')
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, 'uploaded')

    def test_cancel_marks_documents_and_audits(self):
        workflow.cancel_job(self.job, self.uploader, 'خطأ في الملف')
        self.job.refresh_from_db()
        self.doc.refresh_from_db()
        self.assertEqual((self.job.status, self.doc.status), ('cancelled', 'cancelled'))
        self.assertTrue(AuditLog.objects.filter(action='rpa_job_cancelled').exists())

    def test_cancel_requires_reason(self):
        with self.assertRaises(ValidationError):
            workflow.cancel_job(self.job, self.uploader, '  ')


class RaceGuardTests(_Base):
    def _locks(self, ctx, table):
        return [q['sql'] for q in ctx.captured_queries if 'FOR UPDATE' in q['sql'] and table in q['sql']]

    def test_second_approved_recipe_refused_by_db(self):
        self._recipe(1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._recipe(2)

    def test_approve_recipe_locks_screen_row(self):
        self._recipe(1)
        new = self._recipe(2, 'draft')
        with CaptureQueriesContext(connection) as ctx:
            workflow.approve_recipe(new, self.approver)
        self.assertTrue(self._locks(ctx, 'rpa_rpascreen'))

    def test_approve_job_locks_screen_row(self):
        self._recipe(1)
        with CaptureQueriesContext(connection) as ctx:
            workflow.approve_job(self.job, self.approver)
        self.assertTrue(self._locks(ctx, 'rpa_rpascreen'))

    def test_cancel_locks_documents(self):
        with CaptureQueriesContext(connection) as ctx:
            workflow.cancel_job(self.job, self.uploader, 'x')
        self.assertTrue(self._locks(ctx, 'rpa_rpadocument'))

    def test_cancel_refused_when_posted(self):
        self.doc.status = 'posted'
        self.doc.save()
        with self.assertRaises(ValidationError):
            workflow.cancel_job(self.job, self.uploader, 'x')

    def test_later_recipe_approval_keeps_job_frozen_recipe(self):
        v1 = self._recipe(1)
        workflow.approve_job(self.job, self.approver)
        new = self._recipe(2, 'draft')
        workflow.approve_recipe(new, self.approver)
        self.job.refresh_from_db()
        self.assertEqual(self.job.recipe_id, v1.id)
