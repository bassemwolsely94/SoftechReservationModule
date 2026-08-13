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
from django.test import TestCase

from apps.tests.factories import make_user, make_admin, make_branch
from apps.personal.models import SoftechIdentityClaim, PersonalWidget
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
