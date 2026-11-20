"""
apps/tests/test_c06_out_here.py

C06 (docs/full-project-audit/08 §C06) — /supply «ناقص هنا · موجود هناك»: A/B items at zero at a retail branch today
while another live branch holds sellable stock above its safety level. The pairing is the transfer engine's own;
read-only (nothing created, no SOFTECH call).
"""
import io
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.tests.factories import make_admin, make_item, make_user

TODAY = timezone.localdate()
URL = '/api/supply/out-here/'


class _Net(TestCase):

    def setUp(self):
        from apps.branches.models import Branch
        from apps.purchasing.models import DemandCalculationRun
        self.run = DemandCalculationRun.objects.create(status='success', calc_date=TODAY, finished_at=timezone.now())
        mk = lambda code, kind, order: Branch.objects.create(softech_branch_id=code, code=code, name=f'B{code}',
                                                            name_ar=f'B{code}', kind=kind, display_order=order,
                                                            is_active=True)
        self.hq = mk('100', Branch.KIND_HQ, 0)
        self.b130 = mk('130', Branch.KIND_RETAIL, 1)
        self.b140 = mk('140', Branch.KIND_RETAIL, 2)
        self.closed = mk('180', Branch.KIND_CLOSED, 9)
        self.item = make_item('FAST', 'F1')

    def metric(self, branch, item=None, **kw):
        from apps.purchasing.models import ItemDemandMetrics
        vals = dict(monthly_avg=10, gap=0, current_stock=0, safety_stock=5, in_transit_qty=0, abc_class='A',
                    pack_price=20, priority=0)
        vals.update(kw)
        return ItemDemandMetrics.objects.create(run=self.run, item=item or self.item, branch=branch,
                                                calc_date=TODAY, **vals)

    def stock(self, branch, qty, item=None, store='101'):
        from apps.catalog.models import ItemStock
        return ItemStock.objects.create(item=item or self.item, branch=branch, softech_store_code=store,
                                        quantity_on_hand=Decimal(str(qty)))

    def build(self, **kw):
        from apps.purchasing.out_here import build
        return build(run=self.run, **kw)


class RuleTests(_Net):

    def test_zero_here_surplus_there(self):
        self.metric(self.b130, gap=10)                      # need 10
        self.metric(self.b140, current_stock=30)
        self.stock(self.b140, 30)
        rows = self.build()['rows']
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual((r['branch_code'], r['item_code'], r['abc_class']), ('130', 'F1', 'A'))
        self.assertEqual(r['transfer_qty'], 10.0)
        self.assertEqual(r['sources'], [{'branch_code': '140', 'qty': 10.0, 'stock_now': 30.0, 'safety': 5.0}])
        self.assertEqual(r['value'], 200.0)

    def test_source_never_drops_below_safety(self):
        self.metric(self.b130, gap=10)
        self.metric(self.b140, safety_stock=5)
        self.stock(self.b140, 8)                            # only 3 above safety
        r = self.build()['rows'][0]
        self.assertEqual(r['transfer_qty'], 3.0)
        self.assertEqual(r['short_after'], 7.0)

    def test_nothing_above_safety_is_not_listed(self):
        self.metric(self.b130, gap=10)
        self.metric(self.b140, safety_stock=5)
        self.stock(self.b140, 5)
        self.assertEqual(self.build()['rows'], [])

    def test_uses_todays_stock_not_the_engine_snapshot(self):
        self.metric(self.b130, gap=10)                      # engine: zero here …
        self.stock(self.b130, 2)                            # … but it arrived since
        self.metric(self.b140)
        self.stock(self.b140, 40)
        self.assertEqual(self.build()['rows'], [])

    def test_closed_branch_is_neither_source_nor_destination(self):
        self.metric(self.b130, gap=10)
        self.metric(self.closed, gap=10)
        self.metric(self.b140)
        self.stock(self.closed, 100)
        self.assertEqual(self.build()['rows'], [])          # the only stock is in a closed branch
        self.assertNotIn('180', [b['branch_code'] for b in self.build()['branches']])

    def test_quarantine_store_is_not_a_source(self):
        self.metric(self.b130, gap=10)
        self.metric(self.b140)
        self.stock(self.b140, 50, store='102')
        self.assertEqual(self.build()['rows'], [])

    def test_hq_can_send(self):
        self.metric(self.b130, gap=6)
        self.metric(self.hq, safety_stock=0)
        self.stock(self.hq, 20)
        r = self.build()['rows'][0]
        self.assertEqual([s['branch_code'] for s in r['sources']], ['100'])
        self.assertEqual(r['transfer_qty'], 6.0)

    def test_only_a_and_b(self):
        c = make_item('SLOW', 'S1')
        self.metric(self.b130, item=c, gap=10, abc_class='C')
        self.metric(self.b140, item=c, abc_class='C')
        self.stock(self.b140, 50, item=c)
        self.assertEqual(self.build()['rows'], [])
        self.metric(self.b130, gap=10, abc_class='B')
        self.metric(self.b140, abc_class='B')
        self.stock(self.b140, 50)
        self.assertEqual([r['abc_class'] for r in self.build()['rows']], ['B'])
        self.assertEqual(self.build(classes=('A',))['rows'], [])

    def test_in_transit_enough_is_not_listed(self):
        self.metric(self.b130, gap=0, in_transit_qty=10)    # target 10, all of it on the way
        self.metric(self.b140)
        self.stock(self.b140, 50)
        self.assertEqual(self.build()['rows'], [])

    def test_hq_is_never_a_destination(self):
        self.metric(self.hq, gap=10)
        self.metric(self.b140)
        self.stock(self.b140, 50)
        self.assertEqual(self.build()['rows'], [])

    def test_every_retail_branch_in_the_summary(self):
        codes = [b['branch_code'] for b in self.build()['branches']]
        self.assertIn('130', codes)
        self.assertIn('140', codes)
        self.assertNotIn('100', codes)

    def test_nothing_is_written(self):
        from apps.purchasing.models import TransferRecommendation, TransferRecommendationRun
        self.metric(self.b130, gap=10)
        self.metric(self.b140)
        self.stock(self.b140, 30)
        self.build()
        self.assertEqual(TransferRecommendation.objects.count(), 0)
        self.assertEqual(TransferRecommendationRun.objects.count(), 0)

    def test_matches_the_transfer_engine(self):
        """When today's stock equals the engine snapshot, the list pairs exactly as TransferEngine does."""
        from apps.purchasing.models import TransferRecommendation
        from apps.purchasing.transfer_engine import TransferEngine
        self.metric(self.b130, gap=12, priority=12)
        self.metric(self.b140, current_stock=9, safety_stock=4)
        self.metric(self.hq, current_stock=20, safety_stock=10)
        self.stock(self.b140, 9)
        self.stock(self.hq, 20)
        TransferEngine(self.run).run()
        engine = sorted((r.from_branch.softech_branch_id, float(r.quantity))
                        for r in TransferRecommendation.objects.filter(to_branch=self.b130))
        mine = sorted((s['branch_code'], s['qty']) for s in self.build()['rows'][0]['sources'])
        self.assertEqual(mine, engine)


class ApiTests(_Net):

    def setUp(self):
        super().setUp()
        self.metric(self.b130, gap=10)
        self.metric(self.b140, gap=10)
        self.metric(self.hq)
        self.stock(self.hq, 100)

    def test_admin_sees_both_short_branches(self):
        _u, _s, client = make_admin('c06_admin')
        r = client.get(URL)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(sorted(x['branch_code'] for x in r.data['rows']), ['130', '140'])
        self.assertEqual(r.data['classes'], ['A', 'B'])

    def test_branch_filter(self):
        _u, _s, client = make_admin('c06_admin2')
        r = client.get(URL, {'branch': '140'})
        self.assertEqual([x['branch_code'] for x in r.data['rows']], ['140'])

    def test_branch_user_sees_own_branch_only(self):
        _u, _s, client = make_user('c06_buyer', role='purchasing', branch=self.b130)
        r = client.get(URL, {'branch': '130,140'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual([x['branch_code'] for x in r.data['rows']], ['130'])
        self.assertEqual([b['branch_code'] for b in r.data['branches']], ['130'])

    def test_without_purchasing_rights(self):
        from apps.tests.security.fixtures import seed_code_matrix
        from core.middleware import module_access
        seed_code_matrix()
        module_access.clear_cache()
        self.addCleanup(module_access.clear_cache)
        _u, _s, client = make_user('c06_pharm', role='pharmacist', branch=self.b130)
        self.assertEqual(client.get(URL).status_code, 403)

    def test_excel_shows_branch_names(self):
        from openpyxl import load_workbook
        _u, _s, client = make_admin('c06_admin3')
        r = client.get(URL, {'format': 'xlsx'})
        self.assertEqual(r.status_code, 200)
        wb = load_workbook(io.BytesIO(r.content))
        self.assertEqual(wb.sheetnames, ['ملخص الفروع', 'الأصناف'])
        lines = [row for row in wb['الأصناف'].iter_rows(min_row=2, values_only=True)]
        self.assertEqual(len(lines), 2)
        self.assertTrue(all(' · ' in row[0] for row in lines))       # «130 · name», never a bare code
