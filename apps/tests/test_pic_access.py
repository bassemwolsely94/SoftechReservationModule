"""
apps/tests/test_pic_access.py

PIC Analytics (doc 33 §5) — who may open the dashboard and what each person sees:
management (admin / RBAC pic_analytics view) → everything; a NAMED branch manager (active
PicAnalyticsAccess grant) → own branches only, never cost/GP, calls tabs or grants.
"""
import datetime as _dt

from django.test import TestCase

from apps.audit.models import AuditLog
from apps.pic_analytics.access import Access, can_open
from apps.pic_analytics.models import PicAnalyticsAccess, PicDayFact
from apps.tests.factories import make_branch, make_branch2, make_user
from apps.users.models import RoleModuleAccess

DAY = _dt.date(2026, 10, 1)


def _fact(branch, pic='P1'):
    return PicDayFact.objects.create(pic=pic, day=DAY, branch=branch, invoices=1, net=10)


class Base(TestCase):

    def setUp(self):
        self.b1 = make_branch('فرع أ', 'B01')
        self.b2 = make_branch2('فرع ب', 'B02')
        for action in ('view', 'export'):
            RoleModuleAccess.objects.update_or_create(
                role='supervisor', module='pic_analytics', action=action, defaults={'is_allowed': True})
        _, self.admin_p, self.admin = make_user('pa_admin', role='admin', branch=self.b1)
        _, self.sup_p, self.sup = make_user('pa_sup', role='supervisor', branch=self.b1)
        _, self.ph_p, self.ph = make_user('pa_ph', role='pharmacist', branch=self.b1)
        self.f1, self.f2 = _fact(self.b1), _fact(self.b2)

    def grant(self, profile=None):
        return PicAnalyticsAccess.objects.create(staff=profile or self.ph_p, granted_by=self.admin_p)


class AccessTests(Base):

    def test_admin_and_supervisor_see_all(self):
        for p in (self.admin_p, self.sup_p):
            a = Access(p.user)
            self.assertTrue(a.management and a.can_view and a.sees_cost and a.sees_calls_tabs)
            self.assertIsNone(a.branch_ids)
            self.assertEqual(a.scope_facts(PicDayFact.objects.all()).count(), 2)
            self.assertTrue(can_open(p.user))
        self.assertTrue(Access(self.sup_p.user).can_export)
        self.assertFalse(Access(self.sup_p.user).can_manage_access)
        self.assertTrue(Access(self.admin_p.user).can_manage_access)

    def test_pharmacist_without_grant_denied(self):
        a = Access(self.ph_p.user)
        self.assertFalse(a.can_view or a.can_export or a.management or a.branch_manager)
        self.assertEqual(a.branch_ids, set())
        self.assertEqual(a.scope_facts(PicDayFact.objects.all()).count(), 0)
        self.assertFalse(can_open(self.ph_p.user))
        self.assertEqual(self.ph.get('/api/pic-analytics/grants/').status_code, 403)

    def test_named_manager_sees_own_branch_only(self):
        self.grant()
        a = Access(self.ph_p.user)
        self.assertTrue(a.branch_manager and a.can_view and a.can_export and not a.management)
        self.assertEqual(a.branch_ids, {self.b1.pk})
        self.assertEqual(list(a.scope_facts(PicDayFact.objects.all())), [self.f1])
        self.assertTrue(can_open(self.ph_p.user))
        self.assertTrue(self.ph.get('/api/auth/me/').json()['can_pic_analytics'])

    def test_all_branch_grantees_still_own_branch_only(self):
        # quality_manager (ALL_BRANCH_ROLE) and access_all_branches=True never widen a grantee
        _, qm_p, _ = make_user('pa_qm', role='quality_manager', branch=self.b1)
        self.grant(qm_p)
        self.assertEqual(Access(qm_p.user).branch_ids, {self.b1.pk})
        self.ph_p.access_all_branches = True
        self.ph_p.save()
        self.grant()
        a = Access(self.ph_p.user)
        self.assertEqual(a.branch_ids, {self.b1.pk})
        self.assertEqual(list(a.scope_facts(PicDayFact.objects.all())), [self.f1])

    def test_grantee_allowed_minus_restricted_and_no_branch(self):
        self.ph_p.allowed_branches.add(self.b2)
        self.grant()
        self.assertEqual(Access(self.ph_p.user).branch_ids, {self.b1.pk, self.b2.pk})
        self.ph_p.restricted_branches.add(self.b2)
        self.assertEqual(Access(self.ph_p.user).branch_ids, {self.b1.pk})
        _, nb_p, _ = make_user('pa_nb', role='pharmacist', branch=self.b1)
        nb_p.branch = None
        nb_p.save()
        self.grant(nb_p)
        a = Access(nb_p.user)
        self.assertEqual(a.branch_ids, set())
        self.assertFalse(a.can_view)

    def test_migration_seeds_supervisor_permissions(self):
        # rows come from migration 0002, not from Base.setUp (which uses update_or_create)
        from importlib import import_module
        mod = import_module('apps.pic_analytics.migrations.0002_seed_pic_analytics_permissions')
        self.assertEqual(RoleModuleAccess.objects.filter(module='pic_analytics', role='supervisor', is_allowed=True).count(), 2)
        RoleModuleAccess.objects.filter(module='pic_analytics').delete()
        from django.apps import apps as dj_apps
        mod.grant(dj_apps, None)
        mod.grant(dj_apps, None)  # idempotent
        rows = RoleModuleAccess.objects.filter(module='pic_analytics')
        self.assertEqual(set(rows.values_list('role', 'action')), {('supervisor', 'view'), ('supervisor', 'export')})
        self.assertTrue(all(r.is_allowed for r in rows))

    def test_revoked_grant_denies(self):
        g = self.grant()
        self.assertTrue(Access(self.ph_p.user).can_view)
        from django.utils import timezone
        g.revoked_at = timezone.now()
        g.save()
        a = Access(self.ph_p.user)
        self.assertFalse(a.can_view)
        self.assertEqual(a.branch_ids, set())

    def test_branch_manager_never_sees_cost(self):
        self.grant()
        a = Access(self.ph_p.user)
        self.assertFalse(a.sees_cost)
        self.assertFalse(a.can_manage_access)
        self.assertEqual(self.ph.get('/api/pic-analytics/grants/').status_code, 403)

    def test_branch_manager_no_calls_tabs(self):
        self.grant()
        self.assertFalse(Access(self.ph_p.user).sees_calls_tabs)
        self.assertTrue(Access(self.sup_p.user).sees_calls_tabs)

    def test_branch_param_ignored_for_branch_manager(self):
        self.grant()
        a = Access(self.ph_p.user)
        # asking for the other branch (or both) never widens the scope
        self.assertEqual(a.allowed_branch_ids({self.b2.pk}), set())
        self.assertEqual(a.allowed_branch_ids({self.b1.pk, self.b2.pk}), {self.b1.pk})
        self.assertEqual(a.allowed_branch_ids(None), {self.b1.pk})
        # a real request carrying ?branch=<other>: scope_facts still returns only own facts
        from rest_framework.test import APIRequestFactory
        req = APIRequestFactory().get('/x/', {'branch': self.b2.pk})
        req.user = self.ph_p.user
        self.assertEqual(list(Access(req).scope_facts(PicDayFact.objects.all())), [self.f1])
        m = Access(self.sup_p.user)
        self.assertEqual(m.allowed_branch_ids({self.b2.pk}), {self.b2.pk})
        self.assertIsNone(m.allowed_branch_ids(None))


class GrantTests(Base):

    def test_grant_and_revoke_audited(self):
        r = self.admin.post('/api/pic-analytics/grants/', {'staff_id': self.ph_p.pk, 'note': 'مدير فرع أ'}, format='json')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self.admin.post('/api/pic-analytics/grants/', {'staff_id': self.ph_p.pk},
                                         format='json').status_code, 400)
        cands = self.admin.get('/api/pic-analytics/grants/candidates/?q=pa_ph').json()['rows']
        self.assertTrue(next(c for c in cands if c['id'] == self.ph_p.pk)['granted'])
        self.assertTrue(Access(self.ph_p.user).can_view)
        self.assertEqual(self.admin.post(f'/api/pic-analytics/grants/{r.json()["id"]}/revoke/').status_code, 200)
        self.assertFalse(Access(self.ph_p.user).can_view)
        self.assertEqual(AuditLog.objects.filter(action='pic_analytics_access_granted').count(), 1)
        self.assertEqual(AuditLog.objects.filter(action='pic_analytics_access_revoked').count(), 1)

    def test_only_admin_manages_grants(self):
        for c in (self.sup, self.ph):
            self.assertEqual(c.post('/api/pic-analytics/grants/', {'staff_id': self.ph_p.pk},
                                    format='json').status_code, 403)
            self.assertEqual(c.get('/api/pic-analytics/grants/candidates/').status_code, 403)
