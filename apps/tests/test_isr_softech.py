"""
«طلبات التوريد / ISR» by SOFTECH's rule (apps/purchasing/isr_softech.py, owner 2026-10-24).

SOFTECH's own ISRs to 160, decoded read-only: qty = ceil(rate × 0.8 − stock) for every line,
itemqty_cfarma = ceil(maximum − stock). Ours: the same target (or the maximum), minus
transit, < 0.16 pack → 0, whole packs, HQ options, SOFTECH-screen filters. SOFTECH is never
touched here: the server-100 read is replaced by fixed rows.
"""
from unittest import mock

from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from apps.purchasing import isr_softech as S


def _items(*codes, cost=10.0):
    return {c: {'name': f'ITEM {c}', 'price': 20.0, 'cost': cost, 'supplier': '77'} for c in codes}


def _st(**kw):
    return S.rule_settings(kw)


class NeedRuleTests(SimpleTestCase):
    def test_threshold_and_whole_packs(self):
        self.assertEqual(S.softech_need(1.15, 1.0, 0), 0)        # 0.15 pack → nothing
        self.assertEqual(S.softech_need(1.16, 1.0, 0), 1)        # 0.16 → one whole pack
        self.assertEqual(S.softech_need(8.0, 2.0, 0), 6)         # exact → no extra pack
        self.assertEqual(S.softech_need(8.0, 2.0, 1.5), 5)       # 4.5 → 5 (transit deducted)
        self.assertEqual(S.softech_need(0.8 * 10, 2, 0), 6)      # no float drift (8.000…1)
        self.assertEqual(S.softech_need(3, 5, 0), 0)             # above → 0, never negative

    def test_softech_examples(self):
        """Lines of SOFTECH ISR #26100673 (160): qty = ceil(rate × 0.8 − stock)."""
        st = _st(hq_only=False, cap_hq=False)
        rows = {'2675': (181.0, 228.5, 342.8), '4179': (64.0, 144.9, 217.4), '99863': (59.001, 158.8, 238.2)}
        lines, _ = S.plan_lines(rows, {}, {}, _items(*rows), st)
        got = {l['itemcode']: (l['itemqty'], l['itemqty_cfarma']) for l in lines}
        self.assertEqual(got, {'2675': (2, 162.0), '4179': (52, 154.0), '99863': (69, 180.0)})

    def test_defaults_are_softechs(self):
        st = _st()
        self.assertEqual((st['target'], st['order_months'], st['hq_only'], st['cap_hq']),
                         ('order_point', 0.8, False, False))   # HQ options off (owner)
        self.assertFalse(S.SCREEN_DEFAULTS['hq_only'] or S.SCREEN_DEFAULTS['cap_hq'])
        self.assertEqual(S.SCREEN_DEFAULTS['medicine_type'], '10')          # SOFTECH's ISRs: Medicine
        for bad in ({'target': 'all'}, {'order_months': 20}, {'stock': 'x'}, {'origin': 'mars'},
                    {'coverage_months': 'abc'}):
            with self.assertRaises(ValueError):
                S.rule_settings(bad)


class PlanLinesTests(SimpleTestCase):
    ROWS = {
        'A': (2.0, 10.0, 15.0),     # order point 8 → need 6; max 15 → 13
        'B': (9.0, 10.0, 15.0),     # above the order point (8) but under the max
        'C': (0.0, 0.1, 1.0),       # slow: 0.08 → under 0.16 pack
        'D': (0.0, 5.0, 7.5),       # HQ has none
        'E': (0.0, 0.0, 0.0),       # no rate, no max
    }
    HQ = {'A': 3.7, 'B': 50, 'C': 9, 'E': 9}

    def test_order_point_target_with_hq_options(self):
        lines, stats = S.plan_lines(self.ROWS, self.HQ, {}, _items(*self.ROWS), _st(hq_only=True, cap_hq=True))
        self.assertEqual([(l['itemcode'], l['itemqty'], l['need'], l['capped']) for l in lines],
                         [('A', 3, 6, True)])                               # capped at HQ's 3 whole packs
        self.assertEqual(stats, {'considered': 5, 'no_need': 2, 'below_fraction': 1, 'hq_none': 1,
                                 'capped': 1, 'lines': 1})

    def test_hq_options_off(self):
        lines, _ = S.plan_lines(self.ROWS, self.HQ, {}, _items(*self.ROWS), _st(hq_only=False, cap_hq=False))
        self.assertEqual({l['itemcode']: l['itemqty'] for l in lines}, {'A': 6, 'D': 4})
        only, _ = S.plan_lines(self.ROWS, self.HQ, {}, _items(*self.ROWS), _st(hq_only=True, cap_hq=False))
        self.assertEqual({l['itemcode']: l['itemqty'] for l in only}, {'A': 6})   # not capped, D dropped

    def test_max_target_and_order_point_filter(self):
        st = _st(target='max', hq_only=False, cap_hq=False)
        lines, _ = S.plan_lines(self.ROWS, self.HQ, {}, _items(*self.ROWS), st)
        self.assertEqual({l['itemcode']: l['itemqty'] for l in lines}, {'A': 13, 'B': 6, 'C': 1, 'D': 8})
        st['below_order_point'] = True                                      # only below rate × 0.8
        lines, stats = S.plan_lines(self.ROWS, self.HQ, {}, _items(*self.ROWS), st)
        self.assertNotIn('B', {l['itemcode'] for l in lines})
        self.assertEqual(stats['above_order_point'], 1)
        st = _st(target='max', coverage_months=2, hq_only=False, cap_hq=False)   # rate × typed coverage
        self.assertEqual({l['itemcode']: l['itemqty'] for l in S.plan_lines(
            self.ROWS, {}, {}, _items(*self.ROWS), st)[0]}['A'], 18)

    def test_transit_and_stock_filter(self):
        lines, _ = S.plan_lines(self.ROWS, self.HQ, {'A': 5.0}, _items(*self.ROWS), _st())
        a = next(l for l in lines if l['itemcode'] == 'A')
        self.assertEqual((a['itemqty'], a['transit']), (1, 5.0))           # 8 − 2 − 5
        self.assertIn('D', {l['itemcode'] for l in lines})                  # HQ has none — kept by default
        _, stats = S.plan_lines(self.ROWS, self.HQ, {}, _items(*self.ROWS), _st(stock='with'))
        self.assertEqual(stats['stock_filter'], 3)                          # C, D, E have no stock

    def test_items_not_orderable_are_counted(self):
        _, stats = S.plan_lines(self.ROWS, self.HQ, {}, _items('A'), _st())
        self.assertEqual(stats['not_orderable'], 4)


def _user(username, *, role='salesperson', group=None):
    from django.contrib.auth import get_user_model
    from apps.users.models import ERPUser, StaffProfile
    u = get_user_model().objects.create_user(username=username, password='x')
    StaffProfile.objects.create(user=u, role=role)
    if group is not None:
        ERPUser.objects.create(username=username, user_group=str(group), is_active=True)
    return u


class ProposeApiTests(TestCase):
    URL = '/api/purchasing/isr/propose/'

    def setUp(self):
        from apps.branches.models import Branch
        from apps.catalog.models import Item
        Branch.objects.create(softech_branch_id='160', name='Bab ElHadid')
        for code, mt in (('A', '10'), ('B', '10'), ('Z', '50')):
            Item.objects.create(softech_id=code, name=f'ITEM {code}', pack_price=20, cost_price=10,
                                is_stockable=True, medicine_type=mt, supplier_code='77')
        rows = {'A': (2.0, 10.0, 15.0), 'B': (9.0, 10.0, 15.0), 'Z': (0.0, 10.0, 15.0)}
        p = mock.patch.object(S, '_read_softech', return_value=(rows, {'A': 20, 'B': 20, 'Z': 20}, '2026-10-24 12:00'))
        p.start()
        self.addCleanup(p.stop)
        self.c = APIClient()

    def test_needs_write_access(self):
        self.c.force_authenticate(_user('viewer'))
        self.assertEqual(self.c.post(self.URL, {'branch': '160'}, format='json').status_code, 403)

    def test_proposal_stores_rule_settings_and_stats(self):
        self.c.force_authenticate(_user('boss', role='admin'))
        r = self.c.post(self.URL, {'branch': '160', 'from_hq': True, 'medicine_type': '10'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual([(l['itemcode'], l['itemqty']) for l in r.data['lines']], [('A', 6)])   # Z = cosmetics
        self.assertEqual(r.data['params']['rule'], 'softech')
        self.assertEqual(r.data['params']['settings']['order_months'], 0.8)
        self.assertEqual(r.data['params']['stats']['lines'], 1)
        self.assertEqual(r.data['params']['as_of'], '2026-10-24 12:00')
        self.assertEqual((r.data['kind'], r.data['branchcode'], r.data['dest_branchcode']), ('hq_to_branch', '100', '160'))
        self.assertIn('hq_none', r.data['stat_labels'])

    def test_nothing_needed_explains_why(self):
        self.c.force_authenticate(_user('boss', role='admin'))
        r = self.c.post(self.URL, {'branch': '160', 'name': 'NOTHING*LIKE'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data['stats']['not_orderable'], 3)

    def test_bad_setting_is_400_and_engine_rule_still_available(self):
        self.c.force_authenticate(_user('boss', role='admin'))
        self.assertEqual(self.c.post(self.URL, {'branch': '160', 'order_months': 99}, format='json').status_code, 400)
        with mock.patch('apps.purchasing.isr_writer.build_plan',
                        return_value={'lines': [], 'run_id': None, 'coverage_months': None}) as bp:
            r = self.c.post(self.URL, {'branch': '160', 'rule': 'engine'}, format='json')
        self.assertEqual((r.status_code, bp.call_count), (400, 1))

    def test_filter_options(self):
        self.c.force_authenticate(_user('viewer'))
        r = self.c.get('/api/purchasing/isr/filter-options/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['defaults']['target'], 'order_point')
        self.assertIn(['77', ''], r.data['supplier'])
