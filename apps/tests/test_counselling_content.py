"""
Project 4 — pharmacist-approved counselling sheets (apps/counselling).
Content model, read helpers shared with Project 5, review workflow and its permissions.
"""
from django.test import TestCase, override_settings

from apps.counselling import selectors
from apps.counselling.models import CounsellingContent, CounsellingContentItem, CounsellingContentVersion
from apps.users.models import RoleModuleAccess

from .factories import make_item, make_user

ON = dict(COUNSELLING_CONTENT_ENABLED=True)


def _approved_sheet(item, profile, **fields):
    c = CounsellingContent.objects.create(title=item.name, created_by=profile, **fields)
    CounsellingContentItem.objects.create(content=c, item=item, linked_by=profile)
    v = CounsellingContentVersion.objects.create(
        content=c, version=1, data={f: getattr(c, f) for f in CounsellingContentVersion.snapshot_fields()},
        approved_by=profile)
    c.version, c.approved_version, c.status, c.approved_by = 1, v, 'approved', profile
    c.save()
    return c


class AdminLockTests(TestCase):
    """Deferred minor: approved versions cannot be deleted and item links are not edited in admin
    (both go through the audited services)."""
    def test_admin_is_read_only_for_versions_and_links(self):
        from django.contrib import admin
        from django.test import RequestFactory
        req = RequestFactory().get('/')
        req.user = make_user('adm_lock', role='admin')[0]
        req.user.is_superuser = req.user.is_staff = True
        va = admin.site._registry[CounsellingContentVersion]
        la = admin.site._registry[CounsellingContentItem]
        self.assertFalse(va.has_delete_permission(req))
        self.assertFalse(va.has_change_permission(req))
        for perm in (la.has_add_permission(req), la.has_change_permission(req), la.has_delete_permission(req)):
            self.assertFalse(perm)


@override_settings(**ON)
class ContentModelTests(TestCase):
    def setUp(self):
        _, self.ph, _ = make_user('ph_c1', role='pharmacist')
        self.item = make_item('أموكسيل 500', 'CN001')

    def test_version_row_is_immutable(self):
        c = _approved_sheet(self.item, self.ph, dose_ar='قرص')
        v = c.approved_version
        with self.assertRaises(ValueError):
            v.save()

    @override_settings(COUNSELLING_CONTENT_ENABLED=False)
    def test_helpers_none_when_switch_off(self):
        _approved_sheet(self.item, self.ph, dose_ar='قرص')
        self.assertIsNone(selectors.approved_content(self.item))
        self.assertIsNone(selectors.approved_usage_text(self.item))

    def test_helpers_read_approved_snapshot_not_live_fields(self):
        c = _approved_sheet(self.item, self.ph, dose_ar='قرص')
        c.dose_ar = 'قرصين'
        c.status = 'draft'
        c.save()
        self.assertEqual(selectors.approved_content(self.item)['dose_ar'], 'قرص')
        self.assertEqual(selectors.approved_content(self.item)['version'], 1)

    def test_usage_text_joins_parts(self):
        _approved_sheet(self.item, self.ph, dose_ar='قرص واحد', frequency_ar='مرتين يومياً', with_food='after')
        self.assertEqual(selectors.approved_usage_text(self.item), 'قرص واحد — مرتين يومياً — بعد الأكل')

    def test_retired_sheet_returns_none(self):
        c = _approved_sheet(self.item, self.ph, dose_ar='قرص')
        c.status = 'retired'
        c.save()
        self.assertIsNone(selectors.approved_content(self.item))

    def test_unlinked_item_returns_none(self):
        self.assertIsNone(selectors.approved_content(self.item))
        self.assertIsNone(selectors.sheet_for(self.item))

    def test_counselling_module_seeded(self):
        def allowed(role, action):
            return RoleModuleAccess.objects.get(role=role, module='counselling', action=action).is_allowed
        self.assertTrue(allowed('pharmacist', 'approve'))
        self.assertTrue(allowed('pharmacist', 'edit'))
        self.assertFalse(allowed('supervisor', 'approve'))
        self.assertFalse(allowed('supervisor', 'edit'))
        self.assertFalse(allowed('salesperson', 'edit'))
        self.assertTrue(allowed('salesperson', 'view'))
        self.assertFalse(allowed('quality_manager', 'approve'))


BASE = '/api/counselling/content/'
SHEET = {'title': 'أموكسيل', 'how_to_use_ar': 'يبلع مع الماء', 'dose_ar': 'كبسولة', 'frequency_ar': '3 مرات'}


@override_settings(**ON)
class ReviewApiTests(TestCase):
    def setUp(self):
        _, self.ph, self.ph_c = make_user('ph_api', role='pharmacist')
        _, self.sp, self.sp_c = make_user('sp_api', role='salesperson')
        _, self.sv, self.sv_c = make_user('sv_api', role='supervisor', access_all=True)
        self.item = make_item('أموكسيل 500 كبسول', 'CN010')
        self.item2 = make_item('أموكسيل 500 كبسول 24', 'CN011')

    def _create(self, client=None, items=None):
        return (client or self.ph_c).post(BASE, {**SHEET, 'item_ids': items or [self.item.pk]}, format='json')

    def test_salesperson_cannot_create_or_approve(self):
        self.assertEqual(self._create(self.sp_c).status_code, 403)
        cid = self._create().data['id']
        self.assertEqual(self.sp_c.post(f'{BASE}{cid}/approve/').status_code, 403)
        self.assertEqual(self.sp_c.get(f'{BASE}{cid}/').status_code, 200)        # read is fine

    def test_view_roles_never_see_draft_text(self):
        """Review finding 1: the content API must not hand draft / AI-draft text to view-only roles."""
        cid = self._create().data['id']
        self.ph_c.patch(f'{BASE}{cid}/', {'dose_ar': 'مسودة لم تعتمد'}, format='json')
        for url in (f'{BASE}{cid}/', BASE):
            body = str(self.sp_c.get(url).data)
            self.assertNotIn('مسودة لم تعتمد', body, url)
        self.assertIn('مسودة لم تعتمد', str(self.ph_c.get(f'{BASE}{cid}/').data))

    def test_supervisor_cannot_approve(self):
        cid = self._create().data['id']
        self.assertEqual(self.sv_c.post(f'{BASE}{cid}/approve/').status_code, 403)
        self.assertEqual(self.sv_c.patch(f'{BASE}{cid}/', {'dose_ar': 'x'}, format='json').status_code, 403)

    def test_pharmacist_can_create_and_approve_own(self):
        r = self._create()
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['status'], 'draft')
        r = self.ph_c.post(f"{BASE}{r.data['id']}/approve/")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual((r.data['status'], r.data['version']), ('approved', 1))
        self.assertEqual(selectors.approved_content(self.item)['dose_ar'], 'كبسولة')

    def test_edit_after_approve_reverts_to_draft_but_keeps_serving_version(self):
        cid = self._create().data['id']
        self.ph_c.post(f'{BASE}{cid}/approve/')
        r = self.ph_c.patch(f'{BASE}{cid}/', {'dose_ar': 'كبسولتان'}, format='json')
        self.assertEqual(r.data['status'], 'draft')
        self.assertTrue(r.data['has_unapproved_changes'])
        self.assertEqual(selectors.approved_content(self.item)['dose_ar'], 'كبسولة')
        self.ph_c.post(f'{BASE}{cid}/approve/')
        got = selectors.approved_content(self.item)
        self.assertEqual((got['dose_ar'], got['version']), ('كبسولتان', 2))

    def test_item_cannot_join_two_sheets(self):
        self._create()
        r = self._create()
        self.assertEqual(r.status_code, 400)
        cid = self._create(items=[self.item2.pk]).data['id']
        r = self.ph_c.post(f'{BASE}{cid}/link/', {'item_ids': [self.item.pk]}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_approve_requires_usage_or_dose(self):
        r = self.ph_c.post(BASE, {'title': 'x', 'item_ids': [self.item.pk]}, format='json')
        self.assertEqual(self.ph_c.post(f"{BASE}{r.data['id']}/approve/").status_code, 400)

    def test_every_change_audited(self):
        from apps.audit.models import AuditLog
        cid = self._create().data['id']
        self.ph_c.post(f'{BASE}{cid}/link/', {'item_ids': [self.item2.pk]}, format='json')
        self.ph_c.post(f'{BASE}{cid}/approve/')
        self.ph_c.post(f'{BASE}{cid}/retire/', {'reason': 'خطأ في الجرعة'}, format='json')
        acts = set(AuditLog.objects.filter(object_id=str(cid)).values_list('action', flat=True))
        self.assertTrue({'counselling_drafted', 'counselling_item_linked', 'counselling_approved',
                         'counselling_retired'} <= acts, acts)

    def test_retire_needs_reason_and_stops_serving(self):
        cid = self._create().data['id']
        self.ph_c.post(f'{BASE}{cid}/approve/')
        self.assertEqual(self.ph_c.post(f'{BASE}{cid}/retire/', {}, format='json').status_code, 400)
        self.ph_c.post(f'{BASE}{cid}/retire/', {'reason': 'سحب'}, format='json')
        self.assertIsNone(selectors.approved_content(self.item))

    @override_settings(COUNSELLING_CONTENT_ENABLED=False)
    def test_content_routes_503_when_switch_off(self):
        self.assertEqual(self.ph_c.get(BASE).status_code, 503)
        self.assertEqual(self._create().status_code, 503)

    def test_suggest_items_never_links(self):
        cid = self._create().data['id']
        r = self.ph_c.get(f'{BASE}{cid}/suggest-items/')
        self.assertEqual(r.status_code, 200)
        self.assertIn(self.item2.pk, [s['item_id'] for s in r.data['results']])
        self.assertEqual(CounsellingContentItem.objects.filter(content_id=cid).count(), 1)

    def test_status_endpoint_open_to_staff(self):
        r = self.sp_c.get('/api/counselling/status/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['content'], True)
