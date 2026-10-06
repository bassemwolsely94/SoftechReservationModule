"""
apps/tests/test_personal.py

Personal dashboard (apps.personal) — focus on the SECURITY SPINE:
widget data may only flow through an APPROVED identity claim OWNED by the
caller. Also covers the identity claim/review flow and the reused `my_tasks`
widget (shared selector with apps.tasks).

Supplier/customer widgets hit SOFTECH, so those data paths are exercised via
resolve_person_key (pure authorisation, no Sybase). The my_tasks widget is
mirror-only, so its data endpoint runs fully.
"""
from unittest.mock import patch

from django.test import TestCase, SimpleTestCase

from apps.tests.factories import make_user, make_admin, make_branch
from apps.personal.models import SoftechIdentityClaim, PersonalWidget, DocumentCommentEdit, DocumentRevision
from apps.personal.views import resolve_person_key, PersonalError
from apps.tasks.models import OperationalTask


class ResolvePersonKeyTests(TestCase):
    """The authorisation gate for every SOFTECH-live widget."""

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch()
        cls.user, cls.profile, _ = make_user('pers_owner', role='salesperson', branch=cls.branch)
        cls.other, cls.other_profile, _ = make_user('pers_other', role='salesperson', branch=cls.branch)

    def _claim(self, profile, kind, code, status):
        return SoftechIdentityClaim.objects.create(
            staff=profile, kind=kind, person_code=code, status=status,
        )

    def _widget(self, wtype, identity=None, staff=None):
        return PersonalWidget.objects.create(
            staff=staff or self.profile, widget_type=wtype, identity=identity,
        )

    def test_supplier_widget_requires_identity(self):
        w = self._widget('supplier_transactions')
        with self.assertRaises(PersonalError) as cm:
            resolve_person_key(w, self.profile)
        self.assertEqual(cm.exception.status, 409)

    def test_supplier_widget_rejects_pending_claim(self):
        claim = self._claim(self.profile, 'supplier', '5014', SoftechIdentityClaim.STATUS_PENDING)
        w = self._widget('supplier_transactions', identity=claim)
        with self.assertRaises(PersonalError) as cm:
            resolve_person_key(w, self.profile)
        self.assertEqual(cm.exception.status, 403)

    def test_supplier_widget_rejects_foreign_claim(self):
        """A claim owned by another user must never resolve for me."""
        foreign = self._claim(self.other_profile, 'supplier', '5014', SoftechIdentityClaim.STATUS_APPROVED)
        w = self._widget('supplier_transactions', identity=foreign)
        with self.assertRaises(PersonalError) as cm:
            resolve_person_key(w, self.profile)
        self.assertEqual(cm.exception.status, 403)

    def test_kind_mismatch_rejected(self):
        """A customer claim can't power a supplier widget."""
        claim = self._claim(self.profile, 'customer', '4231', SoftechIdentityClaim.STATUS_APPROVED)
        w = self._widget('supplier_transactions', identity=claim)
        with self.assertRaises(PersonalError):
            resolve_person_key(w, self.profile)

    def test_approved_owned_claim_resolves(self):
        claim = self._claim(self.profile, 'supplier', '5014', SoftechIdentityClaim.STATUS_APPROVED)
        w = self._widget('supplier_transactions', identity=claim)
        self.assertEqual(resolve_person_key(w, self.profile), '5014')

    def test_customer_approved_claim_resolves(self):
        claim = self._claim(self.profile, 'customer', '4231', SoftechIdentityClaim.STATUS_APPROVED)
        w = self._widget('customer_transactions', identity=claim)
        self.assertEqual(resolve_person_key(w, self.profile), '4231')

    def test_salesperson_falls_back_to_own_usercode(self):
        self.profile.softech_user_id = '777'
        self.profile.save(update_fields=['softech_user_id'])
        w = self._widget('my_sales')
        self.assertEqual(resolve_person_key(w, self.profile), '777')

    def test_salesperson_without_usercode_errors(self):
        self.profile.softech_user_id = ''
        self.profile.softech_username = ''
        self.profile.save(update_fields=['softech_user_id', 'softech_username'])
        w = self._widget('my_sales')
        with self.assertRaises(PersonalError) as cm:
            resolve_person_key(w, self.profile)
        self.assertEqual(cm.exception.status, 409)

    def test_self_widget_needs_no_code(self):
        w = self._widget('my_tasks')
        self.assertIsNone(resolve_person_key(w, self.profile))


class IdentityClaimApiTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch()
        cls.user, cls.profile, cls.client_ = make_user('claimer', role='salesperson', branch=cls.branch)
        cls.admin_user, cls.admin_profile, cls.admin_client = make_admin('pers_admin')

    def test_claim_creates_pending(self):
        r = self.client_.post('/api/personal/identities/',
                              {'kind': 'supplier', 'person_code': '5014', 'label': 'مورد عام'}, format='json')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data['status'], 'pending')

    def test_duplicate_claim_rejected(self):
        SoftechIdentityClaim.objects.create(staff=self.profile, kind='supplier', person_code='5014')
        r = self.client_.post('/api/personal/identities/',
                              {'kind': 'supplier', 'person_code': '5014'}, format='json')
        self.assertEqual(r.status_code, 409)

    def test_non_admin_cannot_review(self):
        claim = SoftechIdentityClaim.objects.create(staff=self.profile, kind='supplier', person_code='5014')
        r = self.client_.post(f'/api/personal/identities/{claim.id}/review/', {'action': 'approve'}, format='json')
        self.assertEqual(r.status_code, 403)
        claim.refresh_from_db()
        self.assertEqual(claim.status, 'pending')

    def test_admin_approves(self):
        claim = SoftechIdentityClaim.objects.create(staff=self.profile, kind='supplier', person_code='5014')
        r = self.admin_client.post(f'/api/personal/identities/{claim.id}/review/', {'action': 'approve'}, format='json')
        self.assertEqual(r.status_code, 200)
        claim.refresh_from_db()
        self.assertEqual(claim.status, 'approved')
        self.assertEqual(claim.reviewed_by_id, self.admin_profile.id)

    def test_cannot_delete_others_claim(self):
        claim = SoftechIdentityClaim.objects.create(staff=self.admin_profile, kind='supplier', person_code='9')
        r = self.client_.delete(f'/api/personal/identities/{claim.id}/')
        self.assertEqual(r.status_code, 403)


class MyTasksWidgetTests(TestCase):
    """The reused allocated-tasks widget (shared selector with apps.tasks)."""

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch()
        cls.user, cls.profile, cls.client_ = make_user('task_owner', role='pharmacist', branch=cls.branch)
        cls.other, cls.other_profile, _ = make_user('task_other', role='pharmacist', branch=cls.branch)
        # a task assigned to me (open) + one assigned to someone else
        OperationalTask.objects.create(title='مهمتي', assigned_to=cls.profile, status='open', branch=cls.branch)
        OperationalTask.objects.create(title='ليست لي', assigned_to=cls.other_profile, status='open', branch=cls.branch)
        OperationalTask.objects.create(title='مغلقة', assigned_to=cls.profile, status='completed', branch=cls.branch)

    def test_my_tasks_widget_returns_only_my_open_tasks(self):
        w = PersonalWidget.objects.create(staff=self.profile, widget_type='my_tasks')
        r = self.client_.get(f'/api/personal/widgets/{w.id}/data/')
        self.assertEqual(r.status_code, 200)
        data = r.data['data']
        titles = [t['title'] for t in data['tasks']]
        self.assertIn('مهمتي', titles)
        self.assertNotIn('ليست لي', titles)
        self.assertNotIn('مغلقة', titles)  # completed excluded

    def test_cannot_read_another_users_widget(self):
        w = PersonalWidget.objects.create(staff=self.other_profile, widget_type='my_tasks')
        r = self.client_.get(f'/api/personal/widgets/{w.id}/data/')
        self.assertEqual(r.status_code, 403)

    def test_shared_selector_matches_tasks_my_endpoint(self):
        """The widget and GET /api/tasks/my/ must agree (single source of truth)."""
        from apps.tasks.selectors import tasks_for_staff
        w = PersonalWidget.objects.create(staff=self.profile, widget_type='my_tasks')
        widget_ids = {t['id'] for t in self.client_.get(f'/api/personal/widgets/{w.id}/data/').data['data']['tasks']}
        selector_ids = set(tasks_for_staff(self.profile).values_list('id', flat=True))
        self.assertEqual(widget_ids, selector_ids)


class CommentWriteGateTests(TestCase):
    """The gated SOFTECH remarks write — permission, ownership, doc-type, audit."""

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch()
        cls.admin_user, cls.admin, cls.admin_client = make_admin('cw_admin')
        cls.user, cls.profile, cls.client_ = make_user('cw_user', role='salesperson', branch=cls.branch)
        # admin's approved supplier identity + transaction widget
        cls.claim = SoftechIdentityClaim.objects.create(
            staff=cls.admin, kind='supplier', person_code='5014',
            status=SoftechIdentityClaim.STATUS_APPROVED)
        cls.widget = PersonalWidget.objects.create(
            staff=cls.admin, widget_type='supplier_transactions', identity=cls.claim)
        cls.sales_widget = PersonalWidget.objects.create(
            staff=cls.admin, widget_type='my_sales')
        # a widget owned by the OTHER user
        cls.user_claim = SoftechIdentityClaim.objects.create(
            staff=cls.profile, kind='supplier', person_code='9',
            status=SoftechIdentityClaim.STATUS_APPROVED)
        cls.user_widget = PersonalWidget.objects.create(
            staff=cls.profile, widget_type='supplier_transactions', identity=cls.user_claim)

    def _post(self, client, widget_id, **extra):
        body = {'widget_id': widget_id, 'branchcode': '140', 'doccode': '10',
                'docnumber': '10791', 'comment': 'مرحبا'}
        body.update(extra)
        return client.post('/api/personal/documents/comment/', body, format='json')

    def test_capabilities_flag(self):
        self.assertTrue(self.admin_client.get('/api/personal/me/capabilities/').data['can_edit_erp_comments'])
        self.assertFalse(self.client_.get('/api/personal/me/capabilities/').data['can_edit_erp_comments'])

    def test_write_denied_without_permission(self):
        r = self._post(self.client_, self.user_widget.id)
        self.assertEqual(r.status_code, 403)

    def test_write_denied_on_foreign_widget(self):
        # admin has the permission but the widget belongs to another user
        r = self._post(self.admin_client, self.user_widget.id)
        self.assertEqual(r.status_code, 403)

    def test_write_rejected_for_non_transaction_widget(self):
        r = self._post(self.admin_client, self.sales_widget.id)
        self.assertEqual(r.status_code, 400)

    @patch('apps.personal.writeback.write_document_comment')
    def test_write_happy_path_uses_owned_personcode_and_audits(self, mock_write):
        mock_write.return_value = {'old': '', 'hq_result': 'ok',
                                   'branch_host': '1.2.3.4', 'branch_result': 'ok'}
        r = self._post(self.admin_client, self.widget.id)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data['ok'])
        # writeback was called with the personcode resolved from the owned claim
        _, kwargs = mock_write.call_args
        self.assertEqual(kwargs['expected_person_code'], '5014')
        self.assertEqual(kwargs['comment'], 'مرحبا')
        # an immutable audit row was written
        edit = DocumentCommentEdit.objects.get(docnumber='10791')
        self.assertEqual(edit.staff_id, self.admin.id)
        self.assertEqual(edit.new_comment, 'مرحبا')
        self.assertEqual(edit.hq_result, 'ok')


class WritebackUnitTests(SimpleTestCase):

    def test_docnum_param_strips_float(self):
        from apps.personal.writeback import _docnum_param
        self.assertEqual(_docnum_param('10791.0'), 10791)
        self.assertEqual(_docnum_param('10791'), 10791)

    def test_length_guard_rejects_over_100(self):
        from apps.personal.writeback import write_document_comment, CommentWriteError
        with self.assertRaises(CommentWriteError):
            write_document_comment(branchcode='140', doccode='10', docnumber='1',
                                   comment='x' * 101, expected_person_code='5014')


class RevisionHelperTests(SimpleTestCase):

    def test_marker_roundtrip_and_drift(self):
        from apps.personal.revision import build_marker, apply_marker, strip_marker, marker_present
        m = build_marker('BASSEM', 'R5')
        stamped = apply_marker('ملاحظتي', m)
        self.assertIn('R5]]', stamped)
        self.assertEqual(strip_marker(stamped), 'ملاحظتي')      # clean note recovered
        self.assertTrue(marker_present(stamped, 'R5'))           # in sync
        self.assertFalse(marker_present(stamped, 'R9'))          # wrong code → drift
        self.assertFalse(marker_present('ملاحظتي', 'R5'))        # stamp removed → drift

    def test_numstr_normalises(self):
        from apps.personal.revision import numstr
        self.assertEqual(numstr('10791.0'), '10791')
        self.assertEqual(numstr('10791'), '10791')


class RevisionApiTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch()
        cls.admin_user, cls.admin, cls.admin_client = make_admin('rev_admin')
        cls.claim = SoftechIdentityClaim.objects.create(
            staff=cls.admin, kind='supplier', person_code='5014',
            status=SoftechIdentityClaim.STATUS_APPROVED)
        cls.widget = PersonalWidget.objects.create(
            staff=cls.admin, widget_type='supplier_transactions', identity=cls.claim)
        cls.user, cls.profile, cls.client_ = make_user('rev_user', role='salesperson', branch=cls.branch)

    def _post(self, client, widget_id, **extra):
        body = {'widget_id': widget_id, 'kind': 'document', 'branchcode': '140',
                'doccode': '10', 'docnumber': '10791', 'revised': True}
        body.update(extra)
        return client.post('/api/personal/revision/', body, format='json')

    def test_revision_requires_permission(self):
        claim = SoftechIdentityClaim.objects.create(
            staff=self.profile, kind='supplier', person_code='9',
            status=SoftechIdentityClaim.STATUS_APPROVED)
        w = PersonalWidget.objects.create(
            staff=self.profile, widget_type='supplier_transactions', identity=claim)
        r = self._post(self.client_, w.id)
        self.assertEqual(r.status_code, 403)

    @patch('apps.personal.writeback.write_document_comment')
    def test_revise_creates_ledger_and_uses_transform(self, mock_write):
        mock_write.return_value = {'old': '', 'new': 'x [[..R1]]', 'hq_result': 'ok',
                                   'branch_host': '1.2.3.4', 'branch_result': 'ok'}
        r = self._post(self.admin_client, self.widget.id, revised=True)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data['revised'])
        rec = DocumentRevision.objects.get(staff=self.admin, docnumber='10791')
        self.assertEqual(rec.status, 'revised')
        self.assertTrue(rec.code.startswith('R'))
        # the marker is applied atomically via a transform callback
        _, kwargs = mock_write.call_args
        self.assertIn('transform', kwargs)
        self.assertEqual(kwargs['expected_person_code'], '5014')

    @patch('apps.personal.writeback.write_document_comment')
    def test_unrevise_revokes(self, mock_write):
        mock_write.return_value = {'old': 'x', 'new': 'x', 'hq_result': 'ok',
                                   'branch_host': '', 'branch_result': 'skipped'}
        self._post(self.admin_client, self.widget.id, revised=True)
        self._post(self.admin_client, self.widget.id, revised=False)
        rec = DocumentRevision.objects.get(staff=self.admin, docnumber='10791')
        self.assertEqual(rec.status, 'revoked')
