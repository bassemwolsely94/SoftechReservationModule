"""
apps/tests/test_kpi_rollup.py  (doc 16, Phase 1)

Exercises KpiResolver bucketing against synthetic PurchaseHistory rows:
channel → bucket mapping, returns netting (doc 30), customer-count scope,
gross-profit scope (non-credit), and beauty classification by medicine_type.
Mirrors the validated تحقيق مايو 2026 definitions without needing live data.
"""
from datetime import datetime, date
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.branches.models import Branch
from apps.catalog.models import Item, Category
from apps.customers.models import Customer, PurchaseHistory, PurchaseHistoryLine
from apps.forecasting.models import ChannelBucketMap, BeautyClassRule, KpiActualRollup
from apps.forecasting.kpi import KpiResolver


def _bucket(pt, ch, bucket, subtype='', cust=False, profit=False):
    return ChannelBucketMap.objects.create(
        person_type=pt, channel=ch, label=ch, bucket=bucket, subtype=subtype,
        counts_customer=cust, include_in_profit=profit, active=True,
    )


class KpiResolverTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.branch = Branch.objects.create(softech_branch_id='990', code='990', name='KPI Test')
        cls.cust = Customer.objects.create(name='ت', softech_pic='PICKPI', softech_id='C-KPI')
        cat = Category.objects.create(softech_id='CAT-KPI', name='cosm')
        cls.med = Item.objects.create(softech_id='MED001', name='دواء', medicine_type='10', category=cat)
        cls.cosm = Item.objects.create(softech_id='COS001', name='مكياج', medicine_type='50', category=cat)

        # config: cash {91 plain, 90 delivery, 11 no-cust}, credit {10}, insurance {15}, exclude {16}
        _bucket('10', '91', 'cash', '',         cust=True,  profit=True)
        _bucket('10', '90', 'cash', 'delivery', cust=True,  profit=True)
        _bucket('10', '11', 'cash', '',         cust=False, profit=True)
        _bucket('10', '10', 'credit', '',       cust=False, profit=False)
        _bucket('10', '15', 'insurance', '',    cust=False, profit=False)
        _bucket('10', '16', 'exclude', '',      cust=False, profit=False)
        BeautyClassRule.objects.create(medicine_type='50', label='Cosmetics', active=True)

        d = timezone.make_aware(datetime(2026, 5, 10, 12, 0))
        cls._inv(cls, 'S1', '115', '91', 1000, item=cls.med, qty=2, price=500, cost=300, phc='P1')
        cls._inv(cls, 'S2', '115', '91', 300,  item=cls.cosm, qty=3, price=100, cost=40, phc='P2', when=d)
        cls._inv(cls, 'S3', '115', '90', 500,  item=cls.med, qty=1, price=500, cost=350, phc='P3', when=d)
        cls._inv(cls, 'S4', '115', '11', 200,  item=cls.med, qty=1, price=200, cost=150, phc='P4', when=d)
        cls._inv(cls, 'S5', '115', '10', 700,  item=cls.med, qty=1, price=700, cost=500, phc='P5', when=d)
        cls._inv(cls, 'S6', '115', '16', 999,  item=cls.med, qty=1, price=999, cost=1,   phc='P6', when=d)
        cls._inv(cls, 'R1', '30',  '91', 100,  item=cls.med, qty=1, price=100, cost=60,  phc='P1', when=d)

    def _inv(self, ref, doc, ch, total, item, qty, price, cost, phc, when=None):
        when = when or timezone.make_aware(datetime(2026, 5, 10, 12, 0))
        ph = PurchaseHistory.objects.create(
            customer=self.cust, softech_invoice_id=ref, branch=self.branch,
            doc_code=doc, total_amount=Decimal(total), invoice_date=when,
            sales_channel=ch, sales_person_type='10', softech_phcode=phc,
        )
        PurchaseHistoryLine.objects.create(
            purchase=ph, item=item, quantity=Decimal(qty),
            unit_price=Decimal(price), line_total=Decimal(total), cost_at_sale=Decimal(cost),
        )

    def setUp(self):
        self.m = KpiResolver().compute_branch_month(self.branch.id, 2026, 5)

    def test_cash_delivery_bucket_and_returns_netting(self):
        # cash bucket = 91(1000+300) + 90(500) + 11(200) − return 91(100) = 1900
        self.assertEqual(self.m['cash_delivery'], Decimal('1900'))
        self.assertEqual(self.m['delivery'], Decimal('500'))
        self.assertEqual(self.m['cash'], Decimal('1400'))  # 1000+300+200 − 100

    def test_credit_and_insurance_and_exclude(self):
        self.assertEqual(self.m['credit'], Decimal('700'))
        self.assertEqual(self.m['insurance'], Decimal('0'))
        # net_revenue = cash(1900) + credit(700) + insurance(0); exclude 16 omitted
        self.assertEqual(self.m['net_revenue'], Decimal('2600'))

    def test_customer_count_scope(self):
        # counts_customer channels = 91, 90 → distinct phc {P1,P2,P3}; P4(11),P5(10),P6(16) excluded
        self.assertEqual(self.m['customer_count'], Decimal('3'))

    def test_gross_profit_non_credit_only(self):
        # profit channels 91,90,11: (1000-600)+(300-120)+(500-350)+(200-150) − return(100-60)
        # = 400+180+150+50 − 40 = 740
        self.assertEqual(self.m['gross_profit'], Decimal('740'))

    def test_beauty_by_medicine_type(self):
        # only cosmetics item (medicine_type 50) on a non-exclude channel: S2 line_total 300
        self.assertEqual(self.m['beauty'], Decimal('300'))


class SalesTargetKpiMetricTests(TestCase):
    """SalesTarget.actual_value() routes KPI metrics through the bucket resolver (Phase 2)."""
    @classmethod
    def setUpTestData(cls):
        from datetime import date
        from apps.customers.models import Customer as _C
        cls.branch = Branch.objects.create(softech_branch_id='991', code='991', name='TGT', is_operational=True)
        cust = _C.objects.create(name='x', softech_pic='PICT', softech_id='C-T')
        _bucket('10', '91', 'cash', '', cust=True, profit=True)
        _bucket('10', '10', 'credit', '', cust=False, profit=False)
        when = timezone.make_aware(datetime(2026, 5, 5, 10, 0))
        for ref, ch, amt in [('T1', '91', 1000), ('T2', '91', 500), ('T3', '10', 2000)]:
            PurchaseHistory.objects.create(
                customer=cust, softech_invoice_id=ref, branch=cls.branch, doc_code='115',
                total_amount=Decimal(amt), invoice_date=when, sales_channel=ch,
                sales_person_type='10', softech_phcode=ref)
        cls.d1, cls.d2 = date(2026, 5, 1), date(2026, 5, 31)

    def test_cash_metric_actual_via_resolver(self):
        from apps.incentives.models import SalesTarget
        t = SalesTarget.objects.create(
            scope_type='branch', branch=self.branch, metric='cash_delivery',
            period_start=self.d1, period_end=self.d2, target_value=Decimal('2000'))
        self.assertEqual(t.actual_value(), 1500.0)          # 1000 + 500
        self.assertEqual(t.attainment()['pct'], 75.0)

    def test_credit_metric_actual_via_resolver(self):
        from apps.incentives.models import SalesTarget
        t = SalesTarget.objects.create(
            scope_type='branch', branch=self.branch, metric='credit',
            period_start=self.d1, period_end=self.d2, target_value=Decimal('2000'))
        self.assertEqual(t.actual_value(), 2000.0)

    def test_board_view_structure_and_attainment(self):
        from types import SimpleNamespace
        from apps.forecasting.models import KpiActualRollup as K
        from apps.forecasting.views import KpiBoardView
        from apps.incentives.models import SalesTarget
        # materialise a rollup actual + a target, then read the board
        K.objects.create(branch=self.branch, year=2026, month=5, metric='cash_delivery', value=Decimal('1500'))
        SalesTarget.objects.create(
            scope_type='branch', branch=self.branch, metric='cash_delivery',
            period_start=self.d1, period_end=self.d2, target_value=Decimal('2000'))
        data = KpiBoardView().get(SimpleNamespace(query_params={'year': '2026', 'month': '5'})).data
        self.assertTrue(data['has_data'])
        row = next(b for b in data['branches'] if b['code'] == '991')
        cell = row['cells']['cash_delivery']
        self.assertEqual(cell['actual'], 1500.0)
        self.assertEqual(cell['target'], 2000.0)
        self.assertEqual(cell['pct'], 75.0)
        self.assertEqual(cell['pace'], 'missed')  # May 2026 is in the past


class ForecastEngineTests(TestCase):
    """ForecastEngine Models A/B/avg + commit (doc 16, Phase 3), on seeded rollups."""
    @classmethod
    def setUpTestData(cls):
        from apps.forecasting.models import KpiActualRollup as K
        cls.branch = Branch.objects.create(softech_branch_id='992', code='992', name='FC', is_operational=True)
        # target Sept 2026 → base=2025-09, LM=2026-08, PM=2026-07
        for (y, m, v) in [(2025, 9, 1000), (2026, 8, 1200), (2026, 7, 1100)]:
            K.objects.create(branch=cls.branch, year=y, month=m, metric='cash_delivery', value=Decimal(v))

    def _scenario(self, model='a'):
        from apps.forecasting.models import ForecastScenario
        from apps.forecasting.engine import ForecastEngine
        sc = ForecastScenario.objects.create(
            name='t', year=2026, month=9, model=model,
            incentive_threshold=Decimal('0.90'), benchmark_growth=Decimal('0.30'))
        ForecastEngine.ensure_factors(sc)
        # pin cash_delivery factors to known values
        f = sc.factors.get(metric='cash_delivery')
        f.growth_goal = Decimal('0.20'); f.w_lm = Decimal('0.50')
        f.w_pm = Decimal('0.30'); f.w_yoy = Decimal('0.20'); f.seasonality_index = Decimal('1')
        f.save()
        return sc

    def test_model_a(self):
        from apps.forecasting.engine import ForecastEngine
        from apps.forecasting.models import ForecastResult
        sc = self._scenario('a')
        ForecastEngine().generate(sc)
        r = ForecastResult.objects.get(scenario=sc, branch=self.branch, metric='cash_delivery')
        self.assertEqual(r.base_value, Decimal('1000.00'))
        self.assertEqual(r.model_a, Decimal('1200.00'))          # 1000×1.20
        self.assertEqual(r.forecast_value, Decimal('1200.00'))
        self.assertEqual(r.target_value, Decimal('1333.33'))     # 1200÷0.90

    def test_model_b_blend(self):
        from apps.forecasting.engine import ForecastEngine
        from apps.forecasting.models import ForecastResult
        sc = self._scenario('b')
        ForecastEngine().generate(sc)
        r = ForecastResult.objects.get(scenario=sc, branch=self.branch, metric='cash_delivery')
        # 0.5×1200 + 0.3×1100 + 0.2×(1000×1.3) = 600+330+260 = 1190
        self.assertEqual(r.model_b, Decimal('1190.00'))
        self.assertEqual(r.forecast_value, Decimal('1190.00'))

    def test_model_avg(self):
        from apps.forecasting.engine import ForecastEngine
        from apps.forecasting.models import ForecastResult
        sc = self._scenario('avg')
        ForecastEngine().generate(sc)
        r = ForecastResult.objects.get(scenario=sc, branch=self.branch, metric='cash_delivery')
        self.assertEqual(r.forecast_value, Decimal('1195.00'))   # (1200+1190)/2

    def test_commit_creates_targets(self):
        from datetime import date
        from apps.forecasting.engine import ForecastEngine
        from apps.incentives.models import SalesTarget
        sc = self._scenario('a')
        eng = ForecastEngine()
        eng.generate(sc)
        eng.commit(sc)
        t = SalesTarget.objects.get(branch=self.branch, metric='cash_delivery',
                                    period_start=date(2026, 9, 1))
        self.assertEqual(float(t.target_value), 1333.33)
        self.assertEqual(sc.status, 'committed')


class BacktestTests(TestCase):
    """ForecastEngine.compute_models + BacktestService accuracy/winner (doc 16, Phase 4)."""

    def test_compute_models_math(self):
        from apps.forecasting.engine import ForecastEngine
        a, b = ForecastEngine.compute_models(
            Decimal('1000'), Decimal('1000'), Decimal('1000'),
            growth=Decimal('0.20'), w_lm=Decimal('0.5'), w_pm=Decimal('0.3'),
            w_yoy=Decimal('0.2'), seasonality=Decimal('1'),
            bench=Decimal('0.30'), infl=Decimal('0'), promo=Decimal('0'))
        self.assertEqual(a, Decimal('1200.0'))                     # 1000×1.2
        self.assertEqual(b, Decimal('1060.0'))                     # 500+300+0.2×1300

    def test_accumulator_metrics(self):
        from apps.forecasting.backtest import _Acc
        acc = _Acc()
        acc.add(1200, 1000)   # +20% error
        self.assertAlmostEqual(acc.mape(), 20.0)
        self.assertAlmostEqual(acc.bias(), 20.0)   # over-forecast
        self.assertAlmostEqual(acc.wape(), 20.0)
        self.assertAlmostEqual(acc.rmse(), 200.0)

    def test_backtest_picks_winner(self):
        from apps.forecasting.models import KpiActualRollup as K, BacktestResult
        from apps.forecasting.backtest import BacktestService
        b = Branch.objects.create(softech_branch_id='993', code='993', name='BT', is_operational=True)
        # target 2026-06 → base 2025-06, LM 2026-05, PM 2026-04 (all = 1000, actual 1000)
        for (y, m) in [(2025, 6), (2026, 4), (2026, 5), (2026, 6)]:
            K.objects.create(branch=b, year=y, month=m, metric='cash_delivery', value=Decimal('1000'))
        run = BacktestService().run(months_back=12, metrics=['cash_delivery'])
        ra = BacktestResult.objects.get(run=run, metric='cash_delivery', model='a')
        rb = BacktestResult.objects.get(run=run, metric='cash_delivery', model='b')
        self.assertEqual(ra.n_points, 1)
        self.assertAlmostEqual(float(ra.wape), 20.0, places=1)     # A: 1200 vs 1000
        self.assertAlmostEqual(float(rb.wape), 6.0, places=1)      # B: 1060 vs 1000
        self.assertTrue(rb.is_winner)
        self.assertFalse(ra.is_winner)


class CallCountTests(TestCase):
    """CDR call-count logic (doc 16, Phase 5) — extraction + per-day distinct."""

    def test_extract_mobile(self):
        from apps.forecasting.callcount import extract_mobile
        self.assertEqual(extract_mobile('8201063650014'), '01063650014')  # GoIP prefix stripped
        self.assertEqual(extract_mobile('01063650014'), '01063650014')     # already 11-digit
        self.assertIsNone(extract_mobile('26224103'))                      # 8-digit landline
        self.assertIsNone(extract_mobile('103'))                           # queue ext
        self.assertIsNone(extract_mobile('8200000000014'))                 # last-11 not 01…

    def test_count_calls_per_day_distinct(self):
        from apps.forecasting.callcount import count_calls
        rows = [
            # agent 15, two answered calls to the SAME customer on ONE day → counts once
            {'calldate': '2026-05-01 10:00', 'src': '15', 'dst': '8201063650014', 'disposition': 'ANSWERED'},
            {'calldate': '2026-05-01 14:00', 'src': '15', 'dst': '8201063650014', 'disposition': 'ANSWERED'},
            # same customer on a DIFFERENT day → counts again (per-day distinct)
            {'calldate': '2026-05-02 09:00', 'src': '12', 'dst': '8301063650014', 'disposition': 'ANSWERED'},
            # different customer, answered → counts
            {'calldate': '2026-05-01 11:00', 'src': '10', 'dst': '8201200107789', 'disposition': 'ANSWERED'},
            # NOT answered → excluded
            {'calldate': '2026-05-01 12:00', 'src': '15', 'dst': '8201111111111', 'disposition': 'NO ANSWER'},
            # non-agent extension → excluded
            {'calldate': '2026-05-01 13:00', 'src': '170', 'dst': '8201222222222', 'disposition': 'ANSWERED'},
            # landline (not 11-digit mobile) → excluded
            {'calldate': '2026-05-01 15:00', 'src': '15', 'dst': '26224103', 'disposition': 'ANSWERED'},
        ]
        # day1: {01063650014, 01200107789} = 2 ; day2: {01063650014} = 1 → 3
        self.assertEqual(count_calls(rows, ['10', '12', '15']), 3)
        # global distinct = {01063650014, 01200107789} = 2
        self.assertEqual(count_calls(rows, ['10', '12', '15'], per_day_distinct=False), 2)


class DiscountMetricTests(TestCase):
    """Discount metrics (doc 16) — tax-inclusive list vs paid; freq by ACTUAL discount."""
    @classmethod
    def setUpTestData(cls):
        cls.b = Branch.objects.create(softech_branch_id='996', code='996', name='D', is_operational=True)
        cls.cust = Customer.objects.create(name='d', softech_pic='PICD', softech_id='C-D')
        it = Item.objects.create(softech_id='ITD', name='d', medicine_type='10')
        _bucket('10', '91', 'cash', '', cust=True, profit=True)
        d = timezone.make_aware(datetime(2026, 6, 10, 12))
        # Line A: list 100 (tax-incl), paid 90 → 10% discount. Line B: list 100, paid 100 → none.
        for ref, paid, phc in [('DA', 90, 'P1'), ('DB', 100, 'P2')]:
            ph = PurchaseHistory.objects.create(customer=cls.cust, softech_invoice_id=ref, branch=cls.b,
                 doc_code='115', total_amount=Decimal(paid), invoice_date=d, sales_channel='91',
                 sales_person_type='10', softech_phcode=phc)
            PurchaseHistoryLine.objects.create(purchase=ph, item=it, quantity=Decimal(1),
                 unit_price=Decimal(paid), line_total=Decimal(paid), cost_at_sale=Decimal(50),
                 list_price=Decimal(100))

    def test_discount_value_is_tax_inclusive_list_minus_paid(self):
        r = KpiResolver(); s, e = date(2026, 6, 1), date(2026, 6, 30)
        self.assertEqual(r.resolve('gross_sales', branch_ids=[self.b.id], start=s, end=e), Decimal('200.00'))
        self.assertEqual(r.resolve('discount_value', branch_ids=[self.b.id], start=s, end=e), Decimal('10.00'))
        self.assertEqual(r.resolve('discount_pct', branch_ids=[self.b.id], start=s, end=e), Decimal('5.00'))

    def test_discount_freq_uses_actual_discount(self):
        # 1 of 2 lines actually discounted → 50% (NOT driven by pharmacy/additional flags)
        r = KpiResolver(); s, e = date(2026, 6, 1), date(2026, 6, 30)
        self.assertEqual(r.resolve('discount_freq', branch_ids=[self.b.id], start=s, end=e), Decimal('50.00'))


class EdgeCaseTests(TestCase):
    """Robustness: empty config, zero targets, empty months (doc 16)."""

    def test_resolver_empty_config_returns_zero(self):
        # No ChannelBucketMap / BeautyClassRule seeded → every metric resolves to 0, no crash.
        r = KpiResolver()
        s, e = date(2026, 5, 1), date(2026, 5, 31)
        for m in ['cash_delivery', 'credit', 'gross_profit', 'customer_count', 'beauty', 'net_revenue']:
            self.assertEqual(r.resolve(m, start=s, end=e), Decimal('0'))

    def test_attainment_zero_target_no_crash(self):
        from apps.incentives.models import SalesTarget
        br = Branch.objects.create(softech_branch_id='995', code='995', name='Z')
        t = SalesTarget.objects.create(scope_type='branch', branch=br, metric='cash_delivery',
                                       period_start=date(2026, 5, 1), period_end=date(2026, 5, 31),
                                       target_value=Decimal('0'))
        a = t.attainment()
        self.assertEqual(a['pct'], 0)
        self.assertIn(a['pace'], ('met', 'missed', 'ahead', 'behind'))

    def test_board_empty_month(self):
        from apps.forecasting.views import KpiBoardView
        from types import SimpleNamespace
        data = KpiBoardView().get(SimpleNamespace(query_params={'year': '2000', 'month': '1'})).data
        self.assertFalse(data['has_data'])
        self.assertEqual(data['branches'], [])

    def test_category_no_lines_returns_zero(self):
        cat = Category.objects.create(softech_id='EMPTYCAT', name='empty')
        r = KpiResolver()
        s, e = date(2026, 5, 1), date(2026, 5, 31)
        self.assertEqual(r.resolve('net_revenue', category_id=cat.id, start=s, end=e), Decimal('0'))
        self.assertEqual(r.resolve('order_count', category_id=cat.id, start=s, end=e), Decimal('0'))


class ScopeResolverTests(TestCase):
    """Salesperson + category scope resolution (doc 16, Phase 6)."""
    @classmethod
    def setUpTestData(cls):
        cls.b = Branch.objects.create(softech_branch_id='994', code='994', name='SC', is_operational=True)
        cls.cust = Customer.objects.create(name='x', softech_pic='PICSC', softech_id='C-SC')
        catA = Category.objects.create(softech_id='CA', name='catA')
        catB = Category.objects.create(softech_id='CB', name='catB')
        cls.catA = catA
        cls.itA = Item.objects.create(softech_id='ITA', name='a', medicine_type='10', category=catA)
        cls.itB = Item.objects.create(softech_id='ITB', name='b', medicine_type='10', category=catB)
        _bucket('10', '91', 'cash', '', cust=True, profit=True)
        d = timezone.make_aware(datetime(2026, 6, 10, 12))
        # invoice by user U1: 1 line catA (600) + 1 line catB (400); total 1000
        ph1 = PurchaseHistory.objects.create(customer=cls.cust, softech_invoice_id='I1', branch=cls.b,
              doc_code='115', total_amount=Decimal(1000), invoice_date=d, sales_channel='91',
              sales_person_type='10', softech_user='U1', softech_phcode='P1')
        PurchaseHistoryLine.objects.create(purchase=ph1, item=cls.itA, quantity=Decimal(1),
              unit_price=Decimal(600), line_total=Decimal(600), cost_at_sale=Decimal(400))
        PurchaseHistoryLine.objects.create(purchase=ph1, item=cls.itB, quantity=Decimal(1),
              unit_price=Decimal(400), line_total=Decimal(400), cost_at_sale=Decimal(300))
        # invoice by user U2: 1 line catA (500); total 500
        ph2 = PurchaseHistory.objects.create(customer=cls.cust, softech_invoice_id='I2', branch=cls.b,
              doc_code='115', total_amount=Decimal(500), invoice_date=d, sales_channel='91',
              sales_person_type='10', softech_user='U2', softech_phcode='P2')
        PurchaseHistoryLine.objects.create(purchase=ph2, item=cls.itA, quantity=Decimal(1),
              unit_price=Decimal(500), line_total=Decimal(500), cost_at_sale=Decimal(350))

    def test_salesperson_scope_header_based(self):
        r = KpiResolver()
        s, e = date(2026, 6, 1), date(2026, 6, 30)
        # U1 = whole invoice total 1000 (header-based); orders 1
        self.assertEqual(r.resolve('net_revenue', softech_user='U1', start=s, end=e), Decimal('1000'))
        self.assertEqual(r.resolve('order_count', softech_user='U1', start=s, end=e), Decimal('1'))

    def test_category_scope_line_based(self):
        r = KpiResolver()
        s, e = date(2026, 6, 1), date(2026, 6, 30)
        # catA line totals: 600 (I1) + 500 (I2) = 1100 (line-based, NOT whole invoices)
        self.assertEqual(r.resolve('net_revenue', category_id=self.catA.id, start=s, end=e), Decimal('1100'))
        # catA gross profit: (600-400)+(500-350) = 350
        self.assertEqual(r.resolve('gross_profit', category_id=self.catA.id, start=s, end=e), Decimal('350'))
        # orders containing catA = 2 invoices
        self.assertEqual(r.resolve('order_count', category_id=self.catA.id, start=s, end=e), Decimal('2'))

    def test_extended_metrics(self):
        # I1: 2 lines total 1000 (P1); I2: 1 line total 500 (P2) — both channel 91
        from apps.config.models import SystemSetting
        r = KpiResolver()
        s, e = date(2026, 6, 1), date(2026, 6, 30)
        self.assertEqual(r.resolve('pic_count', start=s, end=e), Decimal('2'))           # P1,P2
        self.assertEqual(r.resolve('multi_item_txn_count', start=s, end=e), Decimal('1')) # I1 only
        self.assertEqual(r.resolve('basket_value', start=s, end=e), Decimal('750.00'))    # 1500/2
        self.assertEqual(r.resolve('basket_units', start=s, end=e), Decimal('1.50'))      # 3 units/2
        self.assertEqual(r.resolve('bulk_txn_count', start=s, end=e), Decimal('0'))       # default 5000
        SystemSetting.objects.create(key='kpi_bulk_sale_threshold', label='bulk', value='700', value_type='decimal')
        self.assertEqual(r.resolve('bulk_txn_count', start=s, end=e), Decimal('1'))       # I1 (1000)≥700
        # header-only: category variant returns 0 for now
        self.assertEqual(r.resolve('basket_value', category_id=self.catA.id, start=s, end=e), Decimal('0'))

    def test_derived_metrics(self):
        r = KpiResolver()
        s, e = date(2026, 6, 1), date(2026, 6, 30)
        # net_revenue 1500 (I1 1000 + I2 500); gross profit 200+100+150 = 450 → margin 30%
        self.assertEqual(r.resolve('gross_margin_pct', start=s, end=e), Decimal('30.00'))
        self.assertEqual(r.resolve('revenue_per_customer', start=s, end=e), Decimal('750.00'))  # 1500/2
        self.assertEqual(r.resolve('cross_category_rate', start=s, end=e), Decimal('50.00'))     # I1 spans 2 cats

    def test_units_sold_exclusion(self):
        from apps.forecasting.models import UnitCountExclusion
        r = KpiResolver()
        s, e = date(2026, 6, 1), date(2026, 6, 30)
        self.assertEqual(r.resolve('units_sold', start=s, end=e), Decimal('3'))   # itA×2 + itB×1
        UnitCountExclusion.objects.create(item=self.itA, note='test')             # exclude itA
        self.assertEqual(KpiResolver().resolve('units_sold', start=s, end=e), Decimal('1'))  # only itB


class GrowthMathTests(TestCase):
    """Growth period-bounds + shift math (doc 16 Phase 2)."""
    def test_quarter_bounds(self):
        from apps.forecasting.growth import _quarter_bounds, _shift_quarter, _shift_month
        self.assertEqual(_quarter_bounds(2026, 2), (date(2026, 4, 1), date(2026, 6, 30)))
        self.assertEqual(_shift_quarter(2026, 1, -1), (2025, 4))   # Q1 → prior-year Q4
        self.assertEqual(_shift_month(2026, 1, -1), (2025, 12))

    def test_compare_shapes(self):
        from apps.forecasting.growth import GrowthService
        d = GrowthService().compare('net_revenue', year=2026, period=2,
                                    period_type='quarter', comparison='yoy_quarter')
        self.assertEqual(d['current_label'], '2026-Q2')
        self.assertEqual(d['comparison_label'], '2025-Q2')


class GuardrailTests(TestCase):
    """Reward+guardrail eligibility (doc 16 Phase 3)."""
    def test_operator_logic(self):
        from apps.forecasting.models import MetricGuardrail
        g = MetricGuardrail(guardrail_metric='discount_pct', operator='lte', threshold=Decimal('10'))
        self.assertTrue(g.passes(8)); self.assertFalse(g.passes(12))
        g.operator = 'gte'
        self.assertTrue(g.passes(12)); self.assertFalse(g.passes(8))

    def test_no_guardrails_pass_by_default(self):
        from apps.forecasting.guardrails import evaluate_guardrails
        res = evaluate_guardrails('branch', date(2026, 5, 1), date(2026, 5, 31), branch_ids=[999999])
        self.assertTrue(res['passed'])
        self.assertEqual(res['checks'], [])

    def test_failing_guardrail_blocks(self):
        from apps.forecasting.models import MetricGuardrail
        from apps.forecasting.guardrails import evaluate_guardrails
        # a guardrail that can never pass (net_revenue < 0) → blocks
        MetricGuardrail.objects.create(scope_type='chain', guardrail_metric='net_revenue',
                                       operator='lt', threshold=Decimal('0'))
        res = evaluate_guardrails('chain', date(2026, 5, 1), date(2026, 5, 31))
        self.assertFalse(res['passed'])
