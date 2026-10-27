"""
/supply + engine access by SOFTECH user group (apps/purchasing/access.py), the
quick-run-only rule on the engine trigger, and توزيعة option B (established items
only move when piled up above a ceiling).
"""
import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.purchasing import access

User = get_user_model()


def _user(username, *, role='salesperson', group=None, group_active=True):
    from apps.users.models import ERPUser, StaffProfile
    u = User.objects.create_user(username=username, password='x')
    StaffProfile.objects.create(user=u, role=role)
    if group is not None:
        ERPUser.objects.create(username=username, user_group=str(group), is_active=group_active)
    return u


@override_settings(SUPPLY_ERP_GROUPS='10,19,21,27')
class AccessByGroupTests(TestCase):
    def test_store_group_member_gets_supply_and_quick_engine(self):
        u = _user('18', group=19)                       # مخزن, app role salesperson
        self.assertTrue(access.can_supply_write(u))
        self.assertTrue(access.can_run_engine(u))
        self.assertFalse(access.is_engine_admin(u))     # no full re-sync / settings

    def test_administrator_and_internal_auditor_groups(self):
        self.assertTrue(access.can_supply_write(_user('1001', group=10)))
        self.assertTrue(access.can_supply_write(_user('1608', group=27)))

    def test_other_groups_get_nothing(self):
        u = _user('1399', group=14)                     # صيدلي
        self.assertFalse(access.can_supply_write(u))
        self.assertFalse(access.can_run_engine(u))

    def test_inactive_softech_user_gets_nothing(self):
        self.assertFalse(access.can_supply_write(_user('45', group=19, group_active=False)))

    def test_no_softech_user_gets_nothing(self):
        self.assertFalse(access.can_supply_write(_user('9999')))

    def test_purchasing_role_without_group(self):
        u = _user('p1', role='purchasing')
        self.assertTrue(access.can_supply_write(u))
        self.assertTrue(access.can_run_engine(u))
        self.assertFalse(access.is_engine_admin(u))

    def test_pharmacist_is_engine_admin_but_not_supply(self):
        u = _user('ph1', role='pharmacist')
        self.assertTrue(access.is_engine_admin(u))
        self.assertFalse(access.can_supply_write(u))

    @override_settings(SUPPLY_ERP_GROUPS='19')
    def test_groups_follow_the_setting(self):
        self.assertFalse(access.can_supply_write(_user('1608', group=27)))


@override_settings(SUPPLY_ERP_GROUPS='10,19,21,27')
class EndpointTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_me_exposes_flags(self):
        self.client.force_authenticate(_user('18', group=19))
        data = self.client.get('/api/auth/me/').json()
        self.assertTrue(data['can_supply_write'])
        self.assertTrue(data['can_run_engine'])

    def test_engine_trigger_refuses_full_resync_for_group_member(self):
        self.client.force_authenticate(_user('18', group=19))
        r = self.client.post('/api/purchasing/trigger/', {'full': True}, format='json')
        self.assertEqual(r.status_code, 403)
        r = self.client.post('/api/purchasing/trigger/', {'params': {'x': 1}}, format='json')
        self.assertEqual(r.status_code, 403)

    def test_engine_trigger_refuses_outsiders(self):
        self.client.force_authenticate(_user('1399', group=14))
        self.assertEqual(self.client.post('/api/purchasing/trigger/', {}, format='json').status_code, 403)

    def test_rates_approve_needs_supply_access(self):
        from apps.purchasing.models import SalesRatePush
        p = SalesRatePush.objects.create(status=SalesRatePush.STATUS_PROPOSED)
        self.client.force_authenticate(_user('1399', group=14))
        self.assertEqual(self.client.post(f'/api/purchasing/rates/pushes/{p.id}/approve/').status_code, 403)
        self.client.force_authenticate(_user('18', group=19))
        self.assertEqual(self.client.post(f'/api/purchasing/rates/pushes/{p.id}/approve/').status_code, 200)


class DistributionOptionBTests(TestCase):
    """Established items: never seeded/introduced, but moved when piled up."""

    def setUp(self):
        from apps.branches.models import Branch
        from apps.catalog.models import Item
        from apps.purchasing.models import (DemandCalculationRun, ItemDemandAggregated,
                                            ItemDemandMetrics)
        self.run = DemandCalculationRun.objects.create(status='success')
        today = datetime.date.today()
        self.branches = {c: Branch.objects.create(softech_branch_id=c, name=f'b{c}', db_host='h',
                                                  is_active=True, is_operational=True)
                         for c in ('130', '140', '150', '160', '170')}

        def item(code, stock_by_branch, rate):
            it = Item.objects.create(softech_id=code, name=f'ITEM {code}', pack_price=100)
            ItemDemandAggregated.objects.create(run=self.run, item=it, calc_date=today,
                                                total_current_stock=sum(stock_by_branch.values()),
                                                total_monthly_avg=rate * 5)
            for bc, b in self.branches.items():
                ItemDemandMetrics.objects.create(run=self.run, item=it, branch=b, calc_date=today,
                                                 current_stock=stock_by_branch.get(bc, 0),
                                                 monthly_avg=rate)
            return it
        # established: sells at all 5 branches; 140 holds 40 vs ceiling 6
        item('E1', {'130': 2, '140': 40, '150': 2, '160': 2, '170': 2}, rate=4)
        # established, nobody over the ceiling → must NOT appear at all
        item('E2', {'130': 3, '140': 3, '150': 3, '160': 3, '170': 3}, rate=4)

    def _analyze(self):
        from apps.purchasing import distribution as d
        ceilings = {bc: {'E1': (2.0, 6.0), 'E2': (3.0, 6.0)} for bc in self.branches}
        ceilings['140']['E1'] = (40.0, 6.0)
        return d.analyze(run=self.run, use_age=False, ceilings=ceilings)

    def test_established_item_moves_only_when_piled_up(self):
        sugs = {s['itemcode']: s for s in self._analyze()}
        self.assertIn('E1', sugs)
        self.assertEqual(sugs['E1']['category'], 'over_piled')
        self.assertEqual(sugs['E1']['from_branch'], '140')
        self.assertIn('established', sugs['E1']['signals'])
        self.assertNotIn('E2', sugs)          # established, not piled up → left to rates
