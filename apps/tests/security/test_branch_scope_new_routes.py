"""
Batch 5 follow-up — two routes that reached main after the Batch 5 sweep, caught by the canary
sweep on the merge: the screen-usage report (P-57) and the receipt checks (supply). A branch-bound
user sees their own branches; all-branch roles keep the whole network.
"""
from django.test import TestCase, override_settings

from apps.tests.factories import make_branch, make_user
from apps.users.models import RoleModuleAccess
from core.middleware import module_access

from .canary import Planter
from .fixtures import bearer_client, seed_code_matrix


@override_settings(RBAC_ENFORCEMENT='enforce')
class NewRouteScopeTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        seed_code_matrix()
        RoleModuleAccess.objects.filter(role='pharmacist').update(is_allowed=True)   # only branch scope stops them
        module_access.clear_cache()
        cls.a = make_branch('NR A', softech_id='NRA')
        cls.b = make_branch('NR B', softech_id='NRB')
        cls.ua, cls.pa, _ = make_user('nr_a', role='pharmacist', branch=cls.a)
        cls.ub, cls.pb, _ = make_user('nr_b', role='pharmacist', branch=cls.b)
        cls.adm, _, _ = make_user('nr_admin', role='admin', branch=cls.b)

    def setUp(self):
        module_access.clear_cache()

    def _plant(self, label, **over):
        from django.apps import apps
        model = apps.get_model(label)
        obj = Planter(self.a, self.ua, self.pa).build(model, marked=True)
        self.assertIsNotNone(obj, label)
        if over:
            model.objects.filter(pk=obj.pk).update(**over)
        return obj

    def test_usage_report_hr_approver_of_one_branch_sees_that_branch_only(self):
        self._plant('audit.ScreenView', branch=self.a, route='/nr-canary-route')
        for view in ('screens', 'staff', 'modules'):
            with self.subTest(view=view):
                own = bearer_client(self.ua).get('/api/audit/usage/', {'view': view})
                self.assertEqual(own.status_code, 200, own.content[:200])
                other = bearer_client(self.ub).get('/api/audit/usage/', {'view': view})
                self.assertEqual(other.status_code, 200, other.content[:200])
                self.assertNotIn('nr_a', other.content.decode())
                self.assertNotIn('nr-canary', other.content.decode())
        r = bearer_client(self.adm).get('/api/audit/usage/', {'view': 'screens'})
        self.assertIn('nr-canary', r.content.decode(), 'admin keeps every branch')

    def test_receipt_checks_scoped_by_branch_code(self):
        row = self._plant('procurement.ReceiptCheck', branch_code=self.a.softech_branch_id, status='open')
        ids = lambda c: {r.get('id') for r in c.get('/api/supply/receipts/').json()['rows']}   # noqa: E731
        self.assertIn(row.pk, ids(bearer_client(self.ua)))
        self.assertNotIn(row.pk, ids(bearer_client(self.ub)))
        self.assertIn(row.pk, ids(bearer_client(self.adm)))
        r = bearer_client(self.ub).post(f'/api/supply/receipts/{row.pk}/decide/', {'action': 'return'})
        self.assertEqual(r.status_code, 404, 'another branch cannot decide it')

    def test_shortage_transfer_plan_stays_branch_scoped_for_non_supply_staff(self):
        # supply staff (ERP supply group) plan transfers for any branch's list — a network operation;
        # a branch user without that group keeps the branch-scoped lookup
        sl = self._plant('shortage.ShortageList', branch=self.a)
        r = bearer_client(self.ub).get(f'/api/shortage/lists/{sl.pk}/transfer-plan/')
        self.assertEqual(r.status_code, 404, r.content[:200])
        r = bearer_client(self.ub).post(f'/api/shortage/lists/{sl.pk}/transfers/', {'coverage': 1.5}, format='json')
        self.assertIn(r.status_code, (403, 404), r.content[:200])
