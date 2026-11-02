"""
Batch 5 — the older modules with their own role lists (demand, transfers, transits, call center,
follow-ups, QA, chatter) now go through core/branch_scope:

  • branch staff: home + allowed − restricted (a branch role WITHOUT a branch sees nothing — several
    dashboards used to fall open to every branch);
  • supervisor / quality manager see every branch (owner decision B-3);
  • transfers / transits stay visible to the requesting OR supplying (receiving) side (decision 3),
    but seeing every branch does NOT make an all-branch role every branch's side in the workflow;
  • a client-chosen branch on create must be one of the user's.
"""
from django.test import TestCase, override_settings

from apps.tests.factories import make_branch, make_user
from apps.users.models import RoleModuleAccess
from core.middleware import module_access

from .canary import Planter
from .fixtures import bearer_client, seed_code_matrix
from .test_branch_isolation import _ids


@override_settings(RBAC_ENFORCEMENT='enforce')
class HelperMigrationTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        seed_code_matrix()
        RoleModuleAccess.objects.filter(role='pharmacist').update(is_allowed=True)   # only branch scope stops them
        module_access.clear_cache()
        cls.a = make_branch('Mig A', softech_id='MGA')
        cls.b = make_branch('Mig B', softech_id='MGB')
        cls.c = make_branch('Mig C', softech_id='MGC')
        cls.ua, cls.pa, _ = make_user('mig_a', role='pharmacist', branch=cls.a)
        cls.ub, cls.pb, _ = make_user('mig_b', role='pharmacist', branch=cls.b)
        cls.sup, cls.psup, _ = make_user('mig_sup', role='supervisor', branch=cls.c)
        cls.qm, _, _ = make_user('mig_qm', role='quality_manager', branch=cls.c)

    def setUp(self):
        module_access.clear_cache()
        self.A, self.B = bearer_client(self.ua), bearer_client(self.ub)
        self.SUP, self.QM = bearer_client(self.sup), bearer_client(self.qm)

    def _plant(self, model_label, branch=None, **over):
        from django.apps import apps
        model = apps.get_model(model_label)
        obj = Planter(branch or self.a, self.ua, self.pa).build(model, marked=True)
        self.assertIsNotNone(obj, f'could not build {model_label}')
        if over:
            model.objects.filter(pk=obj.pk).update(**over)
            obj.refresh_from_db()
        return obj

    def _scoped_list(self, url, obj):
        self.assertIn(obj.pk, _ids(self.A.get(url)), 'own branch must still see it')
        self.assertNotIn(obj.pk, _ids(self.B.get(url)), 'another branch must not')
        self.assertIn(obj.pk, _ids(self.SUP.get(url)), 'supervisor is all-branch (B-3)')

    # ── lists ─────────────────────────────────────────────────────────────────
    def test_demand(self):
        rec = self._plant('demand.DemandRecord')
        self._scoped_list('/api/demand/', rec)
        self.assertIn(rec.pk, _ids(self.QM.get('/api/demand/')))

    def test_followup_tasks(self):
        self._scoped_list('/api/followups/tasks/', self._plant('followups.FollowUpTask'))

    def test_qa_inspections(self):
        self._scoped_list('/api/qa/inspections/', self._plant('qa.QAInspection'))

    def test_callcenter_calls(self):
        self._scoped_list('/api/callcenter/calls/', self._plant('callcenter.CallLog'))

    def test_transfers_both_sides_and_supervisor(self):
        tr = self._plant('transfers.TransferRequest', requesting_branch=self.a, supplying_branch=self.c)
        self.assertIn(tr.pk, _ids(self.A.get('/api/transfers/')))
        self.assertNotIn(tr.pk, _ids(self.B.get('/api/transfers/')))
        self.assertIn(tr.pk, _ids(self.SUP.get('/api/transfers/')))
        # supplying side B sees it once B supplies
        type(tr).objects.filter(pk=tr.pk).update(supplying_branch=self.b)
        self.assertIn(tr.pk, _ids(self.B.get('/api/transfers/')))

    def test_transits_both_sides(self):
        t = self._plant('transits.InTransitTransfer', supplying_branch=self.a, receiving_branch=self.c,
                        erp_doc_number='123')        # the list casts it to a number
        self.assertIn(t.pk, _ids(self.A.get('/api/transits/')))
        self.assertNotIn(t.pk, _ids(self.B.get('/api/transits/')))

    def test_allowed_branches_count(self):
        """The old rules ignored allowed_branches — the helper honours them."""
        rec = self._plant('demand.DemandRecord')
        self.assertNotIn(rec.pk, _ids(self.B.get('/api/demand/')))
        self.pb.allowed_branches.add(self.a)
        self.assertIn(rec.pk, _ids(self.B.get('/api/demand/')))

    # ── workflow sides: seeing all ≠ acting for all ───────────────────────────
    def test_supervisor_is_not_every_branchs_supply_side(self):
        from apps.transfers.views import _can_request_side, _can_supply_side
        tr = self._plant('transfers.TransferRequest', requesting_branch=self.a, supplying_branch=self.b)
        self.assertFalse(_can_supply_side(self.psup, tr))
        self.assertFalse(_can_request_side(self.psup, tr))
        type(tr).objects.filter(pk=tr.pk).update(supplying_branch=self.c)
        tr.refresh_from_db()
        self.assertTrue(_can_supply_side(self.psup, tr), 'home branch side still works')
        self.assertTrue(_can_request_side(self.pa, tr))
        self.assertFalse(_can_request_side(self.pb, tr))

    def test_supplying_side_cannot_edit_the_request(self):
        tr = self._plant('transfers.TransferRequest', requesting_branch=self.a, supplying_branch=self.b,
                         status='draft')
        r = self.B.patch(f'/api/transfers/{tr.pk}/', {'notes': 'x'}, format='json')
        self.assertEqual(r.status_code, 403, r.content[:300])

    # ── client-chosen branches ────────────────────────────────────────────────
    def test_followups_dashboard_branch_param_cannot_widen(self):
        self.assertEqual(self.B.get('/api/followups/tasks/dashboard/', {'branch': self.a.pk}).status_code, 403)
        self.assertEqual(self.B.get('/api/followups/tasks/dashboard/').status_code, 200)

    def test_branchless_branch_role_sees_nothing_on_dashboards(self):
        self._plant('callcenter.CallLog')
        u, p, _ = make_user('mig_nobranch', role='pharmacist', branch=self.a)
        p.branch = None
        p.save(update_fields=['branch'])
        r = bearer_client(u).get('/api/callcenter/calls/dashboard/')
        self.assertEqual(r.status_code, 200, r.content[:300])
        self.assertEqual(r.json()['total_calls'], 0)

    def test_chatter_follows_the_helper(self):
        rec = self._plant('reservations.Reservation')
        url = f'/api/notifications/chatter/reservation/{rec.pk}/'
        self.assertEqual(self.B.get(url).status_code, 403)
        self.assertEqual(self.A.get(url).status_code, 200)
        self.assertEqual(self.SUP.get(url).status_code, 200)      # B-3: all-branch

    def test_transfer_chatter_is_scoped_to_both_sides(self):
        """The lookup named a model / field that don't exist, so transfer chatter was open."""
        tr = self._plant('transfers.TransferRequest', requesting_branch=self.a, supplying_branch=self.c)
        url = f'/api/notifications/chatter/transfer/{tr.pk}/'
        self.assertEqual(self.B.get(url).status_code, 403)
        self.assertEqual(self.A.get(url).status_code, 200)
