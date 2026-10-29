"""
Authorization — background jobs and SOFTECH reads only for roles the matrix grants (Batch 4, Z-2;
owner decision 2026-10-27: purchasing access = the code matrix + SOFTECH supply groups).

Before: any logged-in role could start the catalog enrichment / score jobs; pharmacist (no
finance or purchasing grant) could start finance discovery / sync and the purchasing engine,
catch-up, item sync and seasonality pull; supervisor the KPI rebuild and the ISR fulfilment
read; salesperson, call center and delivery a SOFTECH replication check on any item. And under
RBAC enforce, the 15 salespeople in SOFTECH supply groups — the replenishment team, admitted by
apps/purchasing/access.py — would lose every purchasing screen, because the middleware only
knows roles.
"""
from django.test import TestCase, override_settings

from apps.purchasing import access
from apps.tests.factories import make_user
from apps.users.management.commands.seed_permissions import PERMISSIONS
from apps.users.models import ERPUser
from core.middleware import module_access

from .fixtures import bearer_client, seed_code_matrix
from .routes import Tripwire

# Every line of role_softech_reach / role_outside_reach on 2026-10-27.
REACH = [
    ('call_center', 'GET', '/api/pricing-approvals/replication/item/x/'),
    ('delivery', 'GET', '/api/pricing-approvals/replication/item/x/'),
    ('salesperson', 'GET', '/api/pricing-approvals/replication/item/x/'),
    ('pharmacist', 'GET', '/api/purchasing/isr/fulfilment/recent/'),
    ('supervisor', 'GET', '/api/purchasing/isr/fulfilment/recent/'),
    ('pharmacist', 'POST', '/api/purchasing/catchup/'),
    ('pharmacist', 'POST', '/api/purchasing/seasonality/refresh/'),
    ('pharmacist', 'POST', '/api/purchasing/sync-items/'),
    ('pharmacist', 'POST', '/api/purchasing/trigger/'),
    ('pharmacist', 'POST', '/api/finance/trigger-discover/'),
    ('pharmacist', 'POST', '/api/finance/trigger-sync/'),
    ('supervisor', 'POST', '/api/forecasting/kpi-board/refresh/'),
] + [(role, 'POST', path)
     for role in ('call_center', 'delivery', 'quality_manager', 'salesperson', 'supervisor', 'viewer')
     for path in ('/api/enrichment/batches/', '/api/enrichment/recompute-scores/')]


def _blocked_by_matrix(response):
    return response.status_code == 403 and 'module' in (response.json() if response.content else {})


@override_settings(RBAC_ENFORCEMENT='log')          # today's production: only the views decide
class TriggerRefusedTests(TestCase):

    def setUp(self):
        seed_code_matrix()
        self.clients = {role: bearer_client(make_user(f'z2_{role}', role=role)[0])
                        for role in {r for r, _, _ in REACH}}

    def tearDown(self):
        module_access.clear_cache()

    def test_no_job_or_softech_read_for_roles_without_the_grant(self):
        reached = []
        with Tripwire() as tw:
            for role, method, path in REACH:
                soft, out = len(tw.softech_calls), tw.outside_count()
                c = self.clients[role]
                r = c.post(path, {}, format='json') if method == 'POST' else c.get(path)
                if r.status_code not in (401, 403) or len(tw.softech_calls) > soft or tw.outside_count() > out:
                    reached.append(f'{role} {method} {path} → {r.status_code}')
        self.assertEqual(reached, [])


class PurchasingAccessFollowsMatrixTests(TestCase):

    def _granted(self, *actions):
        return {r for r, mods in PERMISSIONS.items() if set(actions) & set(mods.get('purchasing', ()))}

    def test_role_sets_match_the_code_matrix(self):
        self.assertEqual(access.SUPPLY_WRITE_ROLES, self._granted('approve') | {'admin'})
        self.assertEqual(access.ENGINE_RUN_ROLES, self._granted('create', 'edit') | {'admin'})
        self.assertEqual(access.ENGINE_ADMIN_ROLES, {'admin'})


@override_settings(RBAC_ENFORCEMENT='enforce')
class SupplyGroupUnderEnforceTests(TestCase):

    def setUp(self):
        seed_code_matrix()
        self.member, _, _ = make_user('z2_store', role='salesperson')
        ERPUser.objects.create(username='z2_store', full_name='Store Keeper', user_group='19', is_active=True)
        self.outsider, _, _ = make_user('z2_counter', role='salesperson')

    def tearDown(self):
        module_access.clear_cache()

    def test_supply_group_salesperson_reaches_purchasing(self):
        with Tripwire():
            r = bearer_client(self.member).get('/api/purchasing/runs/latest/')
        self.assertFalse(_blocked_by_matrix(r), 'replenishment team locked out by enforce')

    def test_other_salesperson_still_blocked(self):
        with Tripwire():      # runs/latest follows `shortage` view since Z-7a (Market Shortage)
            r = bearer_client(self.outsider).get('/api/purchasing/summary/')
        self.assertTrue(_blocked_by_matrix(r))

    def test_supply_group_still_runs_the_engine(self):
        self.assertTrue(access.can_run_engine(self.member))
        self.assertFalse(access.can_run_engine(self.outsider))
