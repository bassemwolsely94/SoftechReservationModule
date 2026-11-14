"""
apps/tests/test_kpi_export.py  (doc 16, Phase 7)

Exercises the legacy-format KPI target workbook builder (apps/forecasting/kpi_export):
  • one sheet per model (a/b/avg) with the faithful layout
  • forecast targets injected on the target rows (>0 and Model A ≥ Model B for growth)
  • achieved values injected from KpiActualRollup on the achieved rows
  • the chain-total + weighted-score + management formulas are present
Synthetic rollups only — no live data / Sybase.
"""
from decimal import Decimal

from django.test import TestCase

from apps.branches.models import Branch
from apps.forecasting.models import KpiActualRollup as K
from apps.forecasting.kpi_export import build_target_workbook, forecast_targets

# the legacy 5-slot geometry the export keeps with ≤5 branches (KpiLayout(5))
TARGET_ROWS, ACH_ROWS = [8, 10, 12, 14, 16], [9, 11, 13, 15, 17]
from apps.forecasting.engine import round_up_step, ForecastEngine


def _roll(branch, y, m, metric, value):
    K.objects.create(branch=branch, year=y, month=m, metric=metric, value=Decimal(str(value)))


class KpiExportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.b = Branch.objects.create(softech_branch_id='160', code='160',
                                      name='Test 160', name_ar='فرع ١٦٠', is_operational=True)
        # history for the Oct-2026 forecast: base=2025-10, LM=2026-09, PM=2026-08
        for (y, m, mult) in [(2025, 10, 1.0), (2026, 9, 1.1), (2026, 8, 1.2)]:
            _roll(cls.b, y, m, K.M_CASH_DELIVERY, 1_000_000 * mult)
            _roll(cls.b, y, m, K.M_CREDIT, 500_000 * mult)
            _roll(cls.b, y, m, K.M_GROSS_PROFIT, 200_000 * mult)
            _roll(cls.b, y, m, K.M_CUSTOMERS, 2_000 * mult)
            _roll(cls.b, y, m, K.M_BEAUTY, 150_000 * mult)
        # export-month achieved (Oct 2026 MTD), incl. the cash/delivery/regular split
        _roll(cls.b, 2026, 10, K.M_CASH, 300_000)
        _roll(cls.b, 2026, 10, K.M_DELIVERY, 40_000)
        _roll(cls.b, 2026, 10, K.M_REGULAR, 10_000)
        _roll(cls.b, 2026, 10, K.M_CASH_DELIVERY, 350_000)
        _roll(cls.b, 2026, 10, K.M_CREDIT, 180_000)
        _roll(cls.b, 2026, 10, K.M_GROSS_PROFIT, 70_000)
        _roll(cls.b, 2026, 10, K.M_CUSTOMERS, 700)
        _roll(cls.b, 2026, 10, K.M_BEAUTY, 55_000)

    def test_forecast_targets_models(self):
        data = forecast_targets(2026, 10)
        row = next(b for b in data['branches'] if str(b['code']) == '160')
        cd = row['cash_delivery']
        # all models positive; Model A (growth) > Model B (trend blend) here
        self.assertGreater(float(cd['a']), 0)
        self.assertGreater(float(cd['b']), 0)
        self.assertGreater(float(cd['a']), float(cd['b']))
        # avg sits between A and B
        self.assertTrue(float(cd['b']) <= float(cd['avg']) <= float(cd['a']))

    def test_workbook_sheets_and_cells(self):
        wb = build_target_workbook(2026, 10, models=('a', 'b', 'avg'), days_elapsed=8)
        self.assertEqual(len(wb.sheetnames), 3)
        ws = wb[wb.sheetnames[0]]            # Model A sheet (160 first per legacy order)
        rt, ra = TARGET_ROWS[0], ACH_ROWS[0]
        self.assertEqual(str(ws[f'C{rt}'].value), '160')
        # target injected (>0) and MEMORABLE (rounded up to the per-KPI step)
        self.assertGreater(ws[f'I{rt}'].value, 0)                    # cash+del target
        self.assertEqual(ws[f'I{rt}'].value % 5000, 0)               # cash+del → nearest 5,000
        self.assertEqual(ws[f'L{rt}'].value % 5000, 0)               # credit   → 5,000
        self.assertEqual(ws[f'R{rt}'].value % 5000, 0)               # profit   → 5,000
        self.assertEqual(ws[f'U{rt}'].value % 50, 0)                 # customers→ 50
        self.assertEqual(ws[f'Z{rt}'].value % 2500, 0)               # beauty   → 2,500
        # achieved injected from rollup, as whole numbers
        self.assertEqual(ws[f'E{ra}'].value, 300000)                 # cash achieved
        self.assertEqual(ws[f'K{ra}'].value, 180000)                 # credit achieved
        self.assertEqual(ws[f'Q{ra}'].value, 70000)                  # profit achieved
        # key formulas present (verbatim legacy behaviour)
        self.assertEqual(ws[f'H{ra}'].value, f'=E{ra}+F{ra}+G{ra}')
        self.assertEqual(ws[f'J{ra}'].value, f'=H{ra}/I{ra}')
        self.assertEqual(ws['AI7'].value, '=SUM(AC7:AH7)')
        self.assertEqual(ws['J19'].value, '=H19/I19')
        # management block wired
        self.assertEqual(ws['AC24'].value, '=AG22-AG23')
        self.assertEqual(ws['AC25'].value, '=I19')
        self.assertTrue(ws.sheet_view.rightToLeft)

    def test_every_built_formula_survives_neutralising(self):
        # R5: the exports save through neutralise_formulas(wb, keep_safe_formulas=True); every
        # formula the builder writes must pass the safe-formula check, or the sheet would go dead
        from core.export_safety import is_safe_formula
        wb = build_target_workbook(2026, 10, models=('a', 'b', 'avg'), days_elapsed=8)
        formulas = [c.value for ws in wb.worksheets for row in ws.iter_rows() for c in row
                    if c.data_type == 'f']
        self.assertTrue(formulas)
        self.assertEqual([f for f in formulas if not is_safe_formula(f)], [])

    def test_scenario_formulas_survive_neutralising(self):
        from core.export_safety import is_safe_formula
        from apps.forecasting.kpi_export import build_scenario_workbook
        from apps.forecasting.models import ForecastScenario
        sc = ForecastScenario.objects.create(name='Exp', year=2026, month=10,
                                             scope_type='branch', model='avg')
        ForecastEngine().generate(sc)
        wb = build_scenario_workbook(sc)
        bad = [c.value for ws in wb.worksheets for row in ws.iter_rows() for c in row
               if c.data_type == 'f' and not is_safe_formula(c.value)]
        self.assertEqual(bad, [])

    def test_days_knobs(self):
        wb = build_target_workbook(2026, 10, models=('avg',), days_elapsed=8)
        ws = wb[wb.sheetnames[0]]
        self.assertEqual(ws['E1'].value, 31)     # Oct has 31 days
        self.assertEqual(ws['H1'].value, 8)

    def test_export_endpoint(self):
        from apps.tests.factories import make_admin
        _, _, client = make_admin('kpi_export_admin')
        resp = client.get('/api/forecasting/kpi-board/export/',
                           {'year': 2026, 'month': 10, 'models': 'avg'})
        self.assertEqual(resp.status_code, 200)
        self.assertIn('spreadsheetml', resp['Content-Type'])
        self.assertIn('kpi_target_2026_10.xlsx', resp['Content-Disposition'])
        self.assertTrue(resp.content[:2] == b'PK')      # xlsx is a zip

    def test_export_endpoint_bad_month(self):
        from apps.tests.factories import make_admin
        _, _, client = make_admin('kpi_export_admin2')
        resp = client.get('/api/forecasting/kpi-board/export/', {'year': 2026, 'month': 13})
        self.assertEqual(resp.status_code, 400)

    def test_round_up_step(self):
        self.assertEqual(int(round_up_step(1_162_969.05, 5000)), 1_165_000)   # up to 5,000
        self.assertEqual(int(round_up_step(1_160_000, 5000)), 1_160_000)      # already on step
        self.assertEqual(int(round_up_step(2713, 50)), 2750)                  # up to 50
        self.assertEqual(int(round_up_step(97_400, 2500)), 97_500)            # up to 2,500
        self.assertEqual(int(round_up_step(123.4, 1)), 123)                   # whole, half-up
        self.assertEqual(int(round_up_step(123.6, 1)), 124)

    def test_profit_exclusions_api(self):
        from apps.tests.factories import make_admin
        from apps.catalog.models import Item
        from apps.forecasting.models import ProfitExclusion
        it = Item.objects.create(softech_id='DLV9', name='DLV test', medicine_type='70')
        _, _, client = make_admin('pe_admin')
        # create by code
        r = client.post('/api/forecasting/profit-exclusions/', {'code': 'DLV9', 'note': 'fee'})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data['item_code'], 'DLV9')
        # list
        r = client.get('/api/forecasting/profit-exclusions/')
        self.assertEqual(r.status_code, 200)
        pid = ProfitExclusion.objects.get(item=it).id
        # bad code → 400
        r = client.post('/api/forecasting/profit-exclusions/', {'code': 'NOPE404'})
        self.assertEqual(r.status_code, 400)
        # delete
        r = client.delete(f'/api/forecasting/profit-exclusions/{pid}/')
        self.assertEqual(r.status_code, 204)
        self.assertFalse(ProfitExclusion.objects.filter(id=pid).exists())

    def test_scenario_export_endpoint(self):
        from apps.tests.factories import make_admin
        from apps.forecasting.models import ForecastScenario
        from apps.forecasting.engine import ForecastEngine
        sc = ForecastScenario.objects.create(name='Exp', year=2026, month=10,
                                             scope_type='branch', model='avg')
        ForecastEngine().generate(sc)
        _, _, client = make_admin('se_admin')
        r = client.get(f'/api/forecasting/scenarios/{sc.pk}/export/')
        self.assertEqual(r.status_code, 200)
        self.assertIn('spreadsheetml', r['Content-Type'])
        self.assertTrue(r.content[:2] == b'PK')

    def test_references_compute_and_apply(self):
        from apps.forecasting import references as R
        from apps.forecasting.models import ForecastScenario
        refs = R.compute(real_growth=0.15, inflation_annual=0.145, store=True)
        self.assertEqual(refs['growth_goal']['cash_delivery'], round(1.145 * 1.15 - 1, 4))  # money
        self.assertEqual(refs['growth_goal']['customer_count'], 0.15)                        # count
        self.assertTrue(0.0 <= refs['benchmark'].get('credit', 0) <= 0.40)                   # clamped
        sc = ForecastScenario.objects.create(name='R', year=2026, month=10,
                                             scope_type='branch', model='b')
        res = R.apply_to_scenario(sc)
        self.assertGreater(res['factors_updated'], 0)
        f = sc.factors.get(metric='cash_delivery')
        self.assertEqual(float(f.growth_goal), round(1.145 * 1.15 - 1, 4))

    def test_target_changes_audited(self):
        from apps.tests.factories import make_admin
        from apps.incentives.models import SalesTarget
        from apps.audit.models import AuditLog
        from apps.forecasting.models import ForecastScenario
        from apps.forecasting.engine import ForecastEngine
        _, _, client = make_admin('tgt_audit_admin')
        t = SalesTarget.objects.create(scope_type='branch', branch=self.b, metric='cash_delivery',
                                       period_start='2026-10-01', period_end='2026-10-31',
                                       target_value=1_000_000)
        # manual edit → audited with before/after
        r = client.patch(f'/api/incentives/targets/{t.id}/', {'target_value': 1_200_000}, format='json')
        self.assertEqual(r.status_code, 200)
        log = AuditLog.objects.filter(action='sales_target_changed', object_id=str(t.id)).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.changes['target_value'], [1_000_000.0, 1_200_000.0])
        # commit from a scenario → audited
        sc = ForecastScenario.objects.create(name='A', year=2026, month=10,
                                             scope_type='branch', model='avg')
        eng = ForecastEngine(); eng.generate(sc); eng.commit(sc, created_by=None)
        self.assertTrue(AuditLog.objects.filter(action='sales_target_committed').exists())

    def test_partial_month_projection(self):
        from apps.forecasting.engine import ForecastEngine
        from datetime import date
        from calendar import monthrange
        eng = ForecastEngine()
        today = date.today()
        # a completed past month passes through unchanged
        self.assertEqual(eng._project_full_month(Decimal('1000'), 2025, 1), Decimal('1000'))
        # current in-progress month, data complete through day 10 → scaled to full month
        eng._latest_complete_date = lambda y, m: date(today.year, today.month, 10)
        total = monthrange(today.year, today.month)[1]
        self.assertEqual(eng._project_full_month(Decimal('1000'), today.year, today.month),
                         Decimal('1000') * total / 10)

    def test_profit_margin_rule(self):
        # معامل الربحية target = ~23.5% of the cash-sales target (owner rule)
        from apps.forecasting.models import ForecastScenario, ForecastResult
        from apps.forecasting.engine import ForecastEngine, round_up_step, cash_profit_margin
        sc = ForecastScenario.objects.create(name='M', year=2026, month=10,
                                             scope_type='branch', model='avg')
        ForecastEngine().generate(sc)
        cd = ForecastResult.objects.get(scenario=sc, scope_key='160', metric='cash_delivery').target_value
        pr = ForecastResult.objects.get(scenario=sc, scope_key='160', metric='gross_profit').target_value
        self.assertEqual(pr, round_up_step(cash_profit_margin() * cd, 5000))
        self.assertTrue(0.225 <= float(pr) / float(cd) <= 0.245)

    def test_engine_rounds_target_keeps_forecast_exact(self):
        from apps.forecasting.models import ForecastScenario
        sc = ForecastScenario.objects.create(name='Oct test', year=2026, month=10,
                                             scope_type='branch', model='avg')
        ForecastEngine().generate(sc)
        rows = sc.results.filter(scope_key='160')
        self.assertTrue(rows.exists())
        for r in rows:
            step = {'cash_delivery': 5000, 'credit': 5000, 'gross_profit': 5000,
                    'customer_count': 50, 'beauty': 2500}[r.metric]
            self.assertEqual(int(r.target_value) % step, 0, f'{r.metric} target not on step')
            # forecast stays exact (not forced onto the step)
            self.assertGreater(r.forecast_value, 0)


# ── golden layout: the 5-branch export must stay byte-identical (piece 1, task 5) ──
import json
import os
from pathlib import Path

GOLDEN = Path(__file__).parent / 'fixtures' / 'kpi_export_5_golden.json'
# production display order (branches migration 0013): 160, 170, 140, 150, 130
FIVE = [('160', 1), ('170', 2), ('140', 3), ('150', 4), ('130', 5)]


def _plant_branch(code, order, mult, *, kind=Branch.KIND_RETAIL):
    b = Branch.objects.create(softech_branch_id=code, code=code, name=f'Branch {code}',
                              name_ar=f'فرع {code}', kind=kind, display_order=order)
    for (y, m, k) in [(2025, 10, 1.0), (2026, 9, 1.1), (2026, 8, 1.2)]:
        _roll(b, y, m, K.M_CASH_DELIVERY, round(800_000 * mult * k))
        _roll(b, y, m, K.M_CREDIT, round(300_000 * mult * k))
        _roll(b, y, m, K.M_GROSS_PROFIT, round(180_000 * mult * k))
        _roll(b, y, m, K.M_CUSTOMERS, round(1_500 * mult * k))
        _roll(b, y, m, K.M_BEAUTY, round(90_000 * mult * k))
    for metric, v in [(K.M_CASH, 250_000), (K.M_DELIVERY, 30_000), (K.M_REGULAR, 9_000),
                      (K.M_CASH_DELIVERY, 289_000), (K.M_CREDIT, 120_000),
                      (K.M_GROSS_PROFIT, 60_000), (K.M_CUSTOMERS, 600), (K.M_BEAUTY, 40_000),
                      (K.M_CALL_COUNT, 0)]:
        _roll(b, 2026, 10, metric, round(v * mult))
    return b


def _snapshot(wb):
    """Every cell's value/formula + number format, merged ranges and panes, per sheet."""
    out = {}
    for ws in wb.worksheets:
        cells = {}
        for row in ws.iter_rows():
            for c in row:
                if c.value is not None:
                    cells[c.coordinate] = [c.value, c.number_format]
        out[ws.title] = {'cells': cells,
                         'merged': sorted(str(r) for r in ws.merged_cells.ranges),
                         'freeze': ws.freeze_panes, 'rtl': bool(ws.sheet_view.rightToLeft)}
    return out


class KpiExportLayoutTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        # planted out of display order on purpose: the export must follow display_order
        for i, (code, order) in enumerate(sorted(FIVE)):
            _plant_branch(code, order, 1.0 + i * 0.15)
        cc = Branch.objects.create(softech_branch_id='CC', code='CC', name='Call Center',
                                   name_ar='الكول سنتر', kind=Branch.KIND_CALL_CENTER)
        for (y, m, k) in [(2025, 10, 1.0), (2026, 9, 1.1), (2026, 8, 1.2)]:
            _roll(cc, y, m, K.M_CASH_DELIVERY, round(200_000 * k))
            _roll(cc, y, m, K.M_GROSS_PROFIT, round(40_000 * k))
            _roll(cc, y, m, K.M_BEAUTY, round(20_000 * k))
            _roll(cc, y, m, K.M_CUSTOMERS, round(500 * k))
        for metric, v in [(K.M_CASH_DELIVERY, 75_000), (K.M_GROSS_PROFIT, 14_000),
                          (K.M_BEAUTY, 6_000), (K.M_CUSTOMERS, 150), (K.M_CALL_COUNT, 900)]:
            _roll(cc, 2026, 10, metric, v)

    def _build(self):
        return build_target_workbook(2026, 10, models=('a', 'b', 'avg'), days_elapsed=8)

    def test_five_branch_export_identical_to_baseline(self):
        snap = json.loads(json.dumps(_snapshot(self._build()), ensure_ascii=False))
        if os.environ.get('KPI_GOLDEN_WRITE') == '1':      # regenerate only on purpose
            GOLDEN.parent.mkdir(exist_ok=True)
            GOLDEN.write_text(json.dumps(snap, ensure_ascii=False, indent=1, sort_keys=True),
                              encoding='utf-8')
        golden = json.loads(GOLDEN.read_text(encoding='utf-8'))
        self.assertEqual(sorted(snap), sorted(golden))
        for title in golden:
            self.assertEqual(snap[title]['merged'], golden[title]['merged'], title)
            self.assertEqual(snap[title]['freeze'], golden[title]['freeze'], title)
            self.assertEqual(snap[title]['rtl'], golden[title]['rtl'], title)
            self.assertEqual(snap[title]['cells'], golden[title]['cells'], title)

    def test_six_branch_export_no_crash_and_shifted(self):
        from apps.forecasting.kpi_export import KpiLayout
        _plant_branch('230', 6, 1.9)
        ws = self._build()['Model A أكتوبر']
        L = KpiLayout(6)
        self.assertEqual([L.target_row(i) for i in range(6)], [8, 10, 12, 14, 16, 18])
        self.assertEqual((L.total_tgt_row, L.total_ach_row), (20, 21))
        self.assertEqual((L.cc_label_row, L.cc_tgt_row, L.cc_ach_row), (23, 24, 25))
        # six branch blocks, the new branch last (display_order 6)
        self.assertEqual([str(ws[f'C{r}'].value) for r in L.target_rows],
                         ['160', '170', '140', '150', '130', '230'])
        self.assertEqual(ws['E19'].value, round(250_000 * 1.9))              # 230 cash achieved
        # totals reference all six target / achieved rows
        self.assertEqual(ws['I20'].value, '=I8+I10+I12+I14+I16+I18')
        self.assertEqual(ws['H21'].value, '=H9+H11+H13+H15+H17+H19')
        self.assertEqual(ws['J21'].value, '=H21/I21')
        self.assertEqual(ws['AH9'].value, '=$AH$7*$J$21')
        # call-center block shifted by two: label row 23, targets 24, achieved 25
        self.assertEqual(ws['W23'].value, 'المبيعات')
        self.assertEqual(ws['D24'].value, 'call center')
        self.assertEqual(ws['E25'].value, 75000)
        self.assertEqual(ws['F25'].value, '=F24/$E$1*$H$1')
        self.assertEqual(ws['X25'].value, '=$J$25*$X$24')
        self.assertIn('IF(J$19>=90%,H$19,0)', ws['AG24'].value)              # 6th branch counted
        # management block shifted: 26..30
        self.assertEqual(ws['AC26'].value, '=AG24-AG25')
        self.assertEqual(ws['AC27'].value, '=I21')
        self.assertEqual(ws['AC28'].value, '=(IF(AC$21<(0.9*AC$7),AC$26/AC$27,J$21))')
        self.assertEqual(ws['AH30'].value, '=SUM(AC30:AG30)')

    def test_branch_order_follows_display_order(self):
        Branch.objects.filter(softech_branch_id='130').update(display_order=0)
        Branch.objects.filter(softech_branch_id='160').update(display_order=9)
        ws = self._build()['Avg (A+B) أكتوبر']
        self.assertEqual([str(ws[f'C{r}'].value) for r in (8, 10, 12, 14, 16)],
                         ['130', '170', '140', '150', '160'])

    def test_fewer_than_five_branches_keeps_legacy_rows(self):
        from apps.forecasting.kpi_export import KpiLayout
        L = KpiLayout(3)
        self.assertEqual((L.total_tgt_row, L.total_ach_row, L.cc_label_row, L.cc_tgt_row,
                          L.cc_ach_row), (18, 19, 21, 22, 23))
        self.assertEqual(L.ach_rows, [9, 11, 13, 15, 17])
