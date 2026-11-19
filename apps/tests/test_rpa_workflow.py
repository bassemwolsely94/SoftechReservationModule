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


# a recipe that can run a safe dry run (workflow.recipe_problems is empty)
VALID_CONTENT = dict(
    window_title='إذن صرف',
    line_cells=[{'kind': 'field', 'value': 'itemcode'}, {'kind': 'keys', 'value': r'\{TAB}'},
                {'kind': 'field', 'value': 'qty'}, {'kind': 'keys', 'value': r'\{ENTER}'}],
    cancel_keys=[{'kind': 'keys', 'value': r'\{ESC}'}])


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

    def _recipe(self, version, status='approved', creator=None, **content):
        content = {**VALID_CONTENT, **content}
        return RpaRecipe.objects.create(screen=self.screen, version=version, status=status,
                                        created_by=creator or self.uploader, **content)


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


class RecipeContentTests(_Base):
    """A recipe that cannot end a dry run safely is never approved; drafts are edited, approved ones never."""

    def test_empty_cancel_keys_refused_at_approval(self):
        recipe = self._recipe(1, 'draft', cancel_keys=[])
        with self.assertRaises(ValidationError) as ctx:
            workflow.approve_recipe(recipe, self.approver)
        self.assertIn('مفاتيح الإلغاء', str(ctx.exception.detail))
        recipe.refresh_from_db()
        self.assertEqual(recipe.status, 'draft')

    def test_bare_key_and_empty_popup_and_unknown_field_refused(self):
        bad = [
            dict(cancel_keys=[{'kind': 'keys', 'value': '{ESC}'}]),            # not DataLoad form
            dict(popups=[{'title_contains': ' ', 'text_contains': '', 'answer_keys': r'\{ENTER}'}]),
            dict(popups=[{'title_contains': 'حفظ', 'answer_keys': '{ENTER}'}]),
            dict(line_cells=[{'kind': 'field', 'value': 'price'}]),
            dict(line_cells=[{'kind': 'field', 'value': 'reference'}]),
            dict(ref_cells=[{'kind': 'field', 'value': 'qty'}]),
            dict(header_checklist=['']),
        ]
        for n, content in enumerate(bad, start=1):
            recipe = self._recipe(n, 'draft', **content)
            with self.assertRaises(ValidationError, msg=content):
                workflow.approve_recipe(recipe, self.approver)

    def test_older_version_than_approved_refused(self):
        old_draft = self._recipe(1, 'draft')
        self._recipe(2)
        with self.assertRaises(ValidationError):
            workflow.approve_recipe(old_draft, self.approver)

    def test_edit_draft_then_another_admin_approves(self):
        recipe = self._recipe(1, 'draft', cancel_keys=[])
        editor = _staff('t5_ed')
        popups = [{'title_contains': 'تأكيد', 'text_contains': 'إلغاء', 'answer_keys': r'\{ENTER}'}]
        workflow.edit_recipe(recipe, editor, {'cancel_keys': [{'kind': 'keys', 'value': r'\{ESC}'}],
                                              'popups': popups, 'header_checklist': ['المخزن 101'],
                                              'ref_cells': [{'kind': 'field', 'value': 'reference'}]})
        recipe.refresh_from_db()
        self.assertEqual(recipe.popups, popups)
        log = AuditLog.objects.get(action='rpa_recipe_edited')
        self.assertEqual(log.old_data['cancel_keys'], [])
        with self.assertRaises(PermissionDenied):            # the editor is not the second pair of eyes
            workflow.approve_recipe(recipe, editor)
        self.assertEqual(workflow.approve_recipe(recipe, self.approver).status, 'approved')

    def test_edit_records_the_last_editor_on_the_recipe(self):
        recipe = self._recipe(1, 'draft')
        self.assertIsNone(recipe.edited_by_id)
        editor = _staff('t5_ed2')
        workflow.edit_recipe(recipe, editor, {'header_checklist': ['المخزن 101']})
        recipe.refresh_from_db()
        self.assertEqual(recipe.edited_by_id, editor.id)
        self.assertIsNotNone(recipe.edited_at)
        workflow.edit_recipe(recipe, self.approver, {'header_checklist': ['المخزن 102']})
        recipe.refresh_from_db()
        self.assertEqual(recipe.edited_by_id, self.approver.id)

    def test_last_editor_is_refused_even_without_the_audit_log(self):
        # four-eyes rests on the recipe row, not on AuditLog (which retention may prune)
        recipe = self._recipe(1, 'draft')
        editor = _staff('t5_ed3')
        workflow.edit_recipe(recipe, editor, {'header_checklist': ['المخزن 101']})
        AuditLog.objects.filter(action='rpa_recipe_edited').delete()
        with self.assertRaises(PermissionDenied) as ctx:
            workflow.approve_recipe(recipe, editor)
        self.assertIn('عدّلتها', str(ctx.exception.detail))
        recipe.refresh_from_db()
        self.assertEqual(recipe.status, 'draft')

    def test_an_earlier_editor_may_approve_after_someone_else_edited_last(self):
        recipe = self._recipe(1, 'draft')
        first, last = _staff('t5_ed4'), _staff('t5_ed5')
        workflow.edit_recipe(recipe, first, {'header_checklist': ['أ']})
        workflow.edit_recipe(recipe, last, {'header_checklist': ['ب']})
        with self.assertRaises(PermissionDenied):
            workflow.approve_recipe(recipe, last)
        approved = workflow.approve_recipe(recipe, first)
        self.assertEqual((approved.status, approved.edited_by_id), ('approved', last.id))

    def test_edit_refused_for_approved_non_admin_unknown_and_invalid(self):
        approved = self._recipe(1)
        with self.assertRaises(ValidationError):
            workflow.edit_recipe(approved, self.approver, {'cancel_keys': [{'kind': 'keys', 'value': r'\{F4}'}]})
        draft = self._recipe(2, 'draft')
        with self.assertRaises(PermissionDenied):
            workflow.edit_recipe(draft, _staff('t5_ph2', 'pharmacist'), {'header_checklist': ['x']})
        for changes in ({'save_keys': []}, {'line_cells': []}, {}, {'cancel_keys': []},
                        {'popups': [{'answer_keys': r'\{ENTER}'}]}):
            with self.assertRaises(ValidationError, msg=changes):
                workflow.edit_recipe(draft, self.approver, changes)
        self.assertFalse(AuditLog.objects.filter(action='rpa_recipe_edited').exists())

    def test_screen_enable_is_admin_and_audited(self):
        with self.assertRaises(PermissionDenied):
            workflow.set_screen_enabled(self.screen, _staff('t5_ph3', 'pharmacist'), True)
        screen = workflow.set_screen_enabled(self.screen, self.approver, True)
        self.assertTrue(screen.enabled)
        self.assertFalse(screen.live)
        log = AuditLog.objects.get(action='rpa_screen_changed')
        self.assertEqual((log.old_data, log.new_data), ({'enabled': False}, {'enabled': True}))


class CancelKeepsFinishedDocumentsTests(_Base):
    def test_dry_run_ok_and_softech_documents_are_left_alone(self):
        done = RpaDocument.objects.create(job=self.job, seq=2, status='dry_run_ok')
        held = RpaDocument.objects.create(job=self.job, seq=3, status='needs_person', softech_docnumber=55)
        workflow.cancel_job(self.job, self.uploader, 'انتهينا')
        for doc, status in ((self.doc, 'cancelled'), (done, 'dry_run_ok'), (held, 'needs_person')):
            doc.refresh_from_db()
            self.assertEqual(doc.status, status)
        log = AuditLog.objects.get(action='rpa_job_cancelled')
        self.assertEqual(sorted(log.new_data['documents_kept']), sorted([done.pk, held.pk]))


class CreateJobBranchTests(_Base):
    def _upload(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        return SimpleUploadedFile('s.csv', 'كود الصنف,الكمية\n1,2\n'.encode('utf-8'))

    def test_branch_without_softech_server_or_code_refused(self):
        src, dst = make_branch('T5S', 'T5S'), make_branch('T5D', 'T5D')
        kw = dict(profile=self.uploader, screen_key='issue_125', store_code='', upload=self._upload())
        with self.assertRaises(ValidationError) as ctx:          # tests have no central SYBASE_HOST
            workflow.create_job(branch=src, target_branch=dst, **kw)
        self.assertIn('branch', ctx.exception.detail)
        src.db_host = '10.1.1.1'
        src.save(update_fields=['db_host'])
        dst.softech_branch_id = ' '
        with self.assertRaises(ValidationError) as ctx:
            workflow.create_job(branch=src, target_branch=dst, **kw)
        self.assertIn('target_branch', ctx.exception.detail)
        self.assertFalse(RpaJob.objects.filter(branch=src).exists())
        dst.softech_branch_id = 'T5D'
        job = workflow.create_job(branch=src, target_branch=dst, **dict(kw, upload=self._upload()))
        self.assertEqual(job.status, 'uploaded')
