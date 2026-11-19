"""
C25 / P-34 tiered cover under a cash budget (apps/purchasing/cover_tiers.py + cover_tiers_views.py) — READ-ONLY.

Owner decisions 2026-11-19: tiers by sales value per branch (A = top 80%, B = next 15%, C = rest); cover targets
A 1.5 / B 1.0 / C 0.5 months as SystemSettings; the cash need compared with 75 / 100 / 125% of last month's purchases
(doc 10 − doc 120, real suppliers), funding A → B → C.
"""
import datetime as dt
import io
from decimal import Decimal as D
from unittest import mock

from django.test import TestCase, override_settings

from apps.purchasing import cover_tiers as CT
from apps.tests.factories import make_admin, make_hq, make_user

URL = '/api/purchasing/cover-tiers/'


def r(code, value):
    return {'itemcode': code, 'sales_value': D(value)}


class TierMathTests(TestCase):
    """Pure functions — no DB."""

    def test_abc_split_80_15_rest(self):
        rows = [r('A1', 50), r('A2', 30), r('B1', 10), r('B2', 5), r('C1', 3), r('C2', 2), r('Z0', 0)]
        CT.assign_tiers(rows, D('80'), D('95'))
        got = {x['itemcode']: x['tier'] for x in rows}
        # cumulative share BEFORE the row: 0, 50 → A · 80, 90 → B · 95, 98 → C · no value → C
        self.assertEqual(got, {'A1': 'A', 'A2': 'A', 'B1': 'B', 'B2': 'B', 'C1': 'C', 'C2': 'C', 'Z0': 'C'})

    def test_the_item_that_crosses_80_is_still_a(self):
        rows = [r('X', 70), r('Y', 20), r('Z', 10)]       # before Y: 70% < 80 → A
        CT.assign_tiers(rows, D('80'), D('95'))
        self.assertEqual([x['tier'] for x in rows], ['A', 'A', 'B'])

    def test_ties_are_reproducible_by_item_code(self):
        rows = [r('K2', 50), r('K1', 50)]
        CT.assign_tiers(rows, D('50'), D('95'))
        self.assertEqual({x['itemcode']: x['tier'] for x in rows}, {'K1': 'A', 'K2': 'B'})

    def test_no_sales_at_all_is_c(self):
        rows = [r('N1', 0), r('N2', 0)]
        CT.assign_tiers(rows, D('80'), D('95'))
        self.assertEqual({x['tier'] for x in rows}, {'C'})

    def test_months_of_cover(self):
        self.assertEqual(CT.months_of_cover(D('3'), D('2')), D('1.50'))
        self.assertEqual(CT.months_of_cover(D('-2'), D('4')), D('0.00'))
        self.assertIsNone(CT.months_of_cover(D('5'), D('0')))

    def test_need_uses_the_isr_whole_pack_rule(self):
        self.assertEqual(CT.line_need(D('10'), D('1.5'), D('4'), D('2')), 9)       # 15 − 6
        self.assertEqual(CT.line_need(D('10'), D('0.5'), D('4.9'), D('0')), 0)      # 0.1 pack < 0.16 → 0
        self.assertEqual(CT.line_need(D('10'), D('0.5'), D('4.8'), D('0')), 1)      # 0.2 pack → 1
        self.assertEqual(CT.line_need(D('0'), D('1.5'), D('0'), D('0')), 0)         # no rate, no need
        self.assertEqual(CT.line_need(D('2'), D('1'), D('5'), D('0')), 0)           # above target

    def test_budget_fit_funds_a_then_b_then_c(self):
        needs = {'A': D('100'), 'B': D('50'), 'C': D('30')}
        fit = CT.fit_budget(needs, D('120'))
        self.assertEqual((fit['A'], fit['B'], fit['C'], fit['total'], fit['left']),
                         (D('100'), D('20'), D('0'), D('120'), D('0')))
        fit = CT.fit_budget(needs, D('200'))
        self.assertEqual((fit['total'], fit['left']), (D('180'), D('20')))
        self.assertEqual(CT.fit_budget(needs, D('0'))['total'], D('0'))

    def test_75_100_125_levels(self):
        report = {'settings': {'months': {'A': D('1.5'), 'B': D('1'), 'C': D('0.5')}}, 'lines': [
            _line('A', need_value='600'), _line('B', need_value='300'), _line('C', need_value='100')]}
        out = CT.summarize(report, {'value': D('1000'), 'start': None, 'end': None, 'month_label': ''})
        lv = {l['pct']: l for l in out['budget']['levels']}
        self.assertEqual(list(lv), [75, 100, 125])
        self.assertEqual(lv[75]['budget'], D('750.00'))
        self.assertEqual((lv[75]['funded']['A'], lv[75]['funded']['B'], lv[75]['funded']['C']),
                         (D('600'), D('150'), D('0')))
        self.assertEqual(lv[75]['short'], D('250'))
        self.assertEqual((lv[100]['funded_total'], lv[100]['short'], lv[100]['left']), (D('1000'), D('0'), D('0')))
        self.assertEqual((lv[125]['funded_total'], lv[125]['left']), (D('1000'), D('250.00')))

    def test_tier_cover_is_stock_value_over_monthly_cost(self):
        report = {'settings': {'months': {'A': D('1.5'), 'B': D('1'), 'C': D('0.5')}}, 'lines': [
            _line('A', stock_value='57', monthly_cost='100'), _line('A', stock_value='0', monthly_cost='0')]}
        self.assertEqual(CT.summarize(report)['tiers']['A']['cover_months'], D('0.57'))
        self.assertIsNone(CT.summarize(report)['tiers']['B']['cover_months'])


def _line(tier, **kw):
    base = {'tier': tier, 'branch_code': '130', 'branch_name': 'فرع 130', 'sales_value': D('0'),
            'stock_value': D('0'), 'monthly_cost': D('0'), 'need_value': D('0'), 'excess_value': D('0'),
            'need_qty': 0, 'no_cost': False, 'at_zero': False}
    base.update({k: D(v) for k, v in kw.items()})
    if base['need_value'] > 0:
        base['need_qty'] = 1
    return base


def _branch(code, kind='retail'):
    from apps.branches.models import Branch
    return Branch.objects.update_or_create(
        softech_branch_id=code,
        defaults={'code': code, 'name': f'فرع {code}', 'name_ar': f'فرع {code}', 'kind': kind,
                  'is_active': True, 'is_operational': True})[0]


class _Data(TestCase):
    """Branches 130 + 140 (retail), 110 (closed), HQ 100; one successful engine run."""

    @classmethod
    def setUpTestData(cls):
        from apps.catalog.models import Item
        from apps.purchasing.models import DemandCalculationRun, ItemDemandMetrics
        cls.b130, cls.b140 = _branch('130'), _branch('140')
        cls.closed = _branch('110', kind='closed')
        cls.run = DemandCalculationRun.objects.create(status='success', calc_date=dt.date(2026, 11, 18))

        def item(code, cost, **kw):
            return Item.objects.create(softech_id=code, name=f'صنف {code}', cost_price=D(cost), is_active=True, **kw)

        # branch 130: value 800 (A), 150 (B), 50 (C); 1000 total
        cls.fast = item('F1', '10')
        cls.mid = item('M1', '20')
        cls.slow = item('S1', '5')
        cls.nocost = item('N1', '0')
        cls.gift = item('G1', '3', is_stockable=False)            # not orderable → left out
        rows = [
            (cls.fast, cls.b130, '20', '800', '6', '0'),   # A: target 30, need 24 → 240 EGP; cover 0.30
            (cls.mid, cls.b130, '5', '150', '2', '1'),     # B: target 5, need 2 → 40 EGP
            (cls.slow, cls.b130, '2', '50', '0', '0'),     # C: target 1, need 1 → 5 EGP
            (cls.nocost, cls.b130, '1', '0', '0', '0'),    # C (no value), need 1, no cost → 0 EGP
            (cls.gift, cls.b130, '9', '900', '0', '0'),
            (cls.fast, cls.b140, '4', '40', '10', '0'),    # A at 140 (alone): target 6, need 0; excess 4 × 10
            (cls.fast, cls.closed, '9', '90', '0', '0'),   # closed branch: never in the report
        ]
        hq = make_hq('100')
        rows.append((cls.fast, hq, '50', '500', '0', '0'))     # HQ is not a cover target
        for it, b, rate, value, stock, transit in rows:
            ItemDemandMetrics.objects.create(run=cls.run, item=it, branch=b, calc_date=cls.run.calc_date,
                                             monthly_avg=D(rate), monthly_value=D(value), current_stock=D(stock),
                                             in_transit_qty=D(transit))

    def setUp(self):
        make_hq('100', self)


class ReportTests(_Data):

    def _lines(self, **kw):
        return {(l['itemcode'], l['branch_code']): l for l in CT.build_report(**kw)['lines']}

    def test_lines_tiers_need_and_cash_at_cost(self):
        got = self._lines()
        self.assertEqual(set(got), {('F1', '130'), ('M1', '130'), ('S1', '130'), ('N1', '130'), ('F1', '140')})
        f = got[('F1', '130')]
        self.assertEqual((f['tier'], f['need_qty'], f['need_value'], f['cover_months']), ('A', 24, D('240.00'), D('0.30')))
        m = got[('M1', '130')]
        self.assertEqual((m['tier'], m['need_qty'], m['need_value']), ('B', 2, D('40.00')))
        s = got[('S1', '130')]
        self.assertEqual((s['tier'], s['need_qty'], s['need_value']), ('C', 1, D('5.00')))
        n = got[('N1', '130')]
        self.assertEqual((n['tier'], n['need_qty'], n['need_value'], n['no_cost']), ('C', 1, D('0.00'), True))
        f140 = got[('F1', '140')]
        self.assertEqual((f140['tier'], f140['need_qty'], f140['excess_value']), ('A', 0, D('40.00')))

    def test_summary_cash_per_tier_equals_its_lines(self):
        rep = CT.build_report()
        summ = CT.summarize(rep)
        self.assertEqual(summ['tiers']['A']['need_value'], D('240.00'))
        self.assertEqual(summ['tiers']['B']['need_value'], D('40.00'))
        self.assertEqual(summ['tiers']['C']['need_value'], D('5.00'))
        self.assertEqual(summ['total']['need_value'], sum(l['need_value'] for l in rep['lines']))
        self.assertEqual(summ['tiers']['C']['no_cost_needing'], 1)
        self.assertEqual([b['branch_code'] for b in summ['branches']], ['130', '140'])

    def test_tiers_are_per_branch_and_a_branch_filter_does_not_change_them(self):
        both = self._lines()
        only = self._lines(branch_codes={'140'})
        self.assertEqual(set(only), {('F1', '140')})
        self.assertEqual(only[('F1', '140')]['tier'], both[('F1', '140')]['tier'])

    def test_settings_override(self):
        from apps.config.models import SystemSetting
        SystemSetting.objects.create(key='cover_tier_a_months', label='x', value='2', value_type='decimal')
        SystemSetting.objects.create(key='cover_tier_c_months', label='x', value='nonsense', value_type='string')
        st = CT.tier_settings()
        self.assertEqual(st['months'], {'A': D('2'), 'B': D('1.0'), 'C': D('0.5')})   # bad value → default
        f = self._lines()[('F1', '130')]
        self.assertEqual((f['target_months'], f['need_qty']), (D('2'), 34))           # 40 − 6

    def test_cut_override_moves_the_split(self):
        from apps.config.models import SystemSetting
        SystemSetting.objects.create(key='cover_tier_a_cut_pct', label='x', value='90', value_type='decimal')
        self.assertEqual(self._lines()[('M1', '130')]['tier'], 'A')      # 80% before it < 90

    def test_no_softech_call(self):
        with mock.patch('config.sybase.get_sybase_connection', side_effect=AssertionError('SOFTECH read')):
            CT.summarize(CT.build_report(), CT.last_month_purchases(dt.date(2026, 11, 19)))

    def test_no_run_is_an_empty_report(self):
        from apps.purchasing.models import DemandCalculationRun
        DemandCalculationRun.objects.update(status='failed')
        rep = CT.build_report()
        self.assertIsNone(rep['run'])
        self.assertEqual(rep['lines'], [])


class LastMonthPurchasesTests(TestCase):

    def _pl(self, n, doccode, value, day, supplier='5001'):
        from apps.procurement.models import PurchaseLine
        PurchaseLine.objects.create(branch_code='100', supplier_code=supplier, doc_number=str(n), doc_date=day,
                                    item_code='X1', doccode=doccode, is_return=doccode == '120',
                                    net_value=D(value))

    def test_doc_10_net_of_returns_last_calendar_month_real_suppliers(self):
        self._pl(1, '10', '1000', dt.date(2026, 10, 3))
        self._pl(2, '120', '-200', dt.date(2026, 10, 31))
        self._pl(3, '10', '500', dt.date(2026, 10, 15), supplier='1268')    # internal account: not a purchase
        self._pl(4, '10', '700', dt.date(2026, 11, 2))                      # this month: not counted
        self._pl(5, '10', '300', dt.date(2026, 9, 30))                      # older: not counted
        got = CT.last_month_purchases(dt.date(2026, 11, 19))
        self.assertEqual((got['value'], got['start'], got['end'], got['month_label']),
                         (D('800.00'), dt.date(2026, 10, 1), dt.date(2026, 10, 31), '2026-10'))

    def test_january_looks_at_december(self):
        self.assertEqual(CT.previous_month(dt.date(2027, 1, 5)), (dt.date(2026, 12, 1), dt.date(2026, 12, 31)))


class ApiTests(_Data):
    """The view answers the engine's numbers, scoped and permissioned."""

    def setUp(self):
        super().setUp()
        _, _, self.admin = make_admin('cover_admin')

    def test_summary_for_the_whole_network_has_the_budget(self):
        from apps.procurement.models import PurchaseLine
        PurchaseLine.objects.create(branch_code='100', supplier_code='5001', doc_number='1',
                                    doc_date=dt.date.today().replace(day=1) - dt.timedelta(days=3),
                                    item_code='X1', doccode='10', net_value=D('200'))
        resp = self.admin.get(URL + 'summary/')
        self.assertEqual(resp.status_code, 200)
        d = resp.json()
        self.assertEqual(d['tiers']['A']['need_value'], 240.0)
        self.assertEqual(d['settings']['months'], {'A': 1.5, 'B': 1.0, 'C': 0.5})
        self.assertEqual([l['pct'] for l in d['budget']['levels']], [75, 100, 125])
        self.assertEqual(d['budget']['levels'][1]['funded']['A'], 200.0)       # 100% of 200, A first
        self.assertEqual(d['budget']['levels'][1]['funded']['B'], 0.0)

    def test_branch_filter_hides_the_budget(self):
        d = self.admin.get(URL + 'summary/?branch=130').json()
        self.assertIsNone(d['budget'])
        self.assertTrue(d['budget_note'])
        self.assertEqual([b['branch_code'] for b in d['branches']], ['130'])

    def test_lines_filter_sort_and_page(self):
        d = self.admin.get(URL + 'lines/?tier=A').json()
        self.assertEqual({(l['itemcode'], l['branch_code']) for l in d['lines']}, {('F1', '130'), ('F1', '140')})
        d = self.admin.get(URL + 'lines/?need=1&ordering=-need_value').json()
        self.assertEqual([l['itemcode'] for l in d['lines']], ['F1', 'M1', 'S1', 'N1'])
        d = self.admin.get(URL + 'lines/?page_size=2&page=2').json()
        self.assertEqual((d['count'], d['pages'], len(d['lines'])), (5, 3, 2))
        self.assertEqual(self.admin.get(URL + 'lines/?ordering=evil').status_code, 400)

    def test_branch_user_sees_only_own_branch_and_no_budget(self):
        _, _, viewer = make_user('cover_viewer_140', role='viewer', branch=self.b140)
        d = viewer.get(URL + 'lines/').json()
        self.assertEqual({l['branch_code'] for l in d['lines']}, {'140'})
        self.assertEqual(viewer.get(URL + 'lines/?branch=130').json()['lines'], [])   # asking is not enough
        self.assertIsNone(viewer.get(URL + 'summary/').json()['budget'])

    @override_settings(RBAC_ENFORCEMENT='enforce')
    def test_needs_purchasing_view(self):
        from apps.tests.security.fixtures import seed_code_matrix
        seed_code_matrix()
        _, _, pharm = make_user('cover_pharm', role='pharmacist', branch=self.b130)
        self.assertEqual(pharm.get(URL + 'summary/').status_code, 403)
        self.assertEqual(pharm.get(URL + 'lines/').status_code, 403)
        _, _, buyer = make_user('cover_buyer', role='purchasing', branch=self.b130)
        self.assertEqual(buyer.get(URL + 'summary/').status_code, 200)

    def test_anonymous_is_refused(self):
        from rest_framework.test import APIClient
        self.assertIn(APIClient().get(URL + 'summary/').status_code, (401, 403))

    def test_excel_export_has_branch_names_and_every_line(self):
        import openpyxl
        resp = self.admin.get(URL + 'lines/?format=xlsx')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp['Content-Type'].startswith('application/vnd.openxmlformats'))
        wb = openpyxl.load_workbook(io.BytesIO(resp.content))
        self.assertEqual(wb.sheetnames, ['ملخص', 'الأسطر'])
        lines = list(wb['الأسطر'].iter_rows(min_row=2, values_only=True))
        self.assertEqual(len(lines), 5)
        self.assertEqual({row[2] for row in lines}, {'فرع 130', 'فرع 140'})
        summary = [row for row in wb['ملخص'].iter_rows(values_only=True) if row and row[0] == 'الإجمالي']
        self.assertEqual(summary[0][7], 285.0)                    # 240 + 40 + 5 + 0

    def test_export_neutralises_formula_text(self):
        from apps.catalog.models import Item
        Item.objects.filter(softech_id='F1').update(name='=HYPERLINK("http://x")')
        resp = self.admin.get(URL + 'lines/?format=xlsx')
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(resp.content))
        cells = [row[1] for row in wb['الأسطر'].iter_rows(min_row=2)]
        self.assertIn('=HYPERLINK("http://x")', [c.value for c in cells])
        self.assertFalse(any(c.data_type == 'f' for c in cells))            # written as text, never a formula
