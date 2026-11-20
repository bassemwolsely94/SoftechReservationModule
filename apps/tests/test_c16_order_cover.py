"""
apps/tests/test_c16_order_cover.py

C16 (docs/full-project-audit/08_BUSINESS_OPTIMIZATION_OPPORTUNITIES.md): the P-31 «شراء رغم تغطية عالية» rule
(network cover ≥ receipt_check_cover_months, default 6, or stock with no sales) is shown on the order sheet
itself — the pivot «أولويات النواقص», the network export and the 📦 Network tab — before the buy. Advisory only:
it never changes a gap, never writes to SOFTECH.
"""
import io
import json
from decimal import Decimal

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.tests.factories import make_admin, make_item, make_user

TODAY = timezone.localdate()
COV_COL = 'Total.معامل-التغطية-بالشهور'
GAP_COL = 'Total.الفرق-مطلوب/راكد'


def _setting(key, value):
    from apps.config.models import SystemSetting
    SystemSetting.objects.update_or_create(key=key, defaults={'label': key, 'value': json.dumps(value),
                                                             'value_type': 'json'})


class CoverFlagRuleTests(SimpleTestCase):
    """The rule itself, with the limit passed in (no database)."""

    def _f(self, stock, rate, limit=6):
        from apps.purchasing.pivot_sheets import buy_cover_flag
        return buy_cover_flag(stock, rate, limit)

    def test_six_months_is_flagged(self):
        f = self._f(60, 10)
        self.assertEqual(f['months'], Decimal('6.00'))
        self.assertTrue(f['warn'])
        self.assertIn('6.0', f['label'])

    def test_just_under_is_not(self):
        f = self._f(59, 10)
        self.assertEqual(f['months'], Decimal('5.90'))
        self.assertFalse(f['warn'])
        self.assertEqual(f['label'], '')

    def test_rounds_like_the_p31_sheet(self):
        # 5.996 months → 6.00 on the sheet the receipt check reads, so flagged here too
        self.assertTrue(self._f(Decimal('59.96'), 10)['warn'])

    def test_stock_without_sales_is_flagged(self):
        f = self._f(5, 0)
        self.assertIsNone(f['months'])
        self.assertTrue(f['warn'])
        self.assertIn('بلا مبيعات', f['label'])

    def test_nothing_held_nothing_sold_is_quiet(self):
        self.assertFalse(self._f(0, 0)['warn'])
        self.assertFalse(self._f(None, None)['warn'])
        self.assertFalse(self._f(0, 5)['warn'])

    def test_limit_moves_the_line(self):
        self.assertTrue(self._f(30, 10, limit=3)['warn'])
        self.assertFalse(self._f(30, 10, limit=4)['warn'])


class CoverLimitSettingTests(TestCase):

    def test_same_setting_as_the_receipt_check(self):
        from apps.procurement.receipt_check import cover_months
        from apps.purchasing.pivot_sheets import buy_cover_limit
        self.assertEqual(buy_cover_limit(), 6.0)
        _setting('receipt_check_cover_months', 3)
        self.assertEqual(buy_cover_limit(), 3.0)
        self.assertEqual(buy_cover_limit(), cover_months())


class _Fixture(TestCase):

    def setUp(self):
        from apps.branches.models import Branch
        from apps.purchasing.models import DemandCalculationRun, ItemDemandAggregated, ItemDemandMetrics
        self.run = DemandCalculationRun.objects.create(status='success')
        br = Branch.objects.create(softech_branch_id='130', name='ElNozha', is_active=True)
        self.need = make_item('NEED', 'C1')          # 0 stock, rate 10 → buy, no warning
        self.rest = make_item('REST', 'C2')          # 8 stock, rate 1 → 8 months → warning
        self.dead = make_item('DEAD', 'C3')          # 2 stock, no sales → warning
        self.ok = make_item('OK', 'C4')              # 20 stock, rate 10 → 2 months → no warning
        for it, rate, stock, gap in ((self.need, 10, 0, 4), (self.rest, 1, 8, -3), (self.dead, 0, 2, -2),
                                     (self.ok, 10, 20, -1)):
            ItemDemandMetrics.objects.create(run=self.run, item=it, branch=br, calc_date=TODAY, monthly_avg=rate,
                                             current_stock=stock, gap=gap)
            ItemDemandAggregated.objects.create(run=self.run, item=it, calc_date=TODAY, total_monthly_avg=rate,
                                                total_current_stock=stock, total_gap=gap, abc_class='A')
        _u, _s, self.client_ = make_admin('c16_admin')


class PivotSheetTests(_Fixture):

    def _book(self):
        from openpyxl import load_workbook
        r = self.client_.get('/api/purchasing/export/?view=pivot')
        self.assertEqual(r.status_code, 200)
        return load_workbook(io.BytesIO(r.content)).active

    def test_column_sits_with_the_advisory_flags(self):
        from apps.purchasing.pivot_sheets import BUY_COVER_LABEL
        ws = self._book()
        hdr = [c.value for c in ws[2]]
        col = hdr.index(BUY_COVER_LABEL)
        self.assertEqual(hdr[col - 1], 'ذروة طلب غير مؤكدة')
        self.assertEqual(hdr[col + 1], 'يوجد أرخص (المورد الأفضل)')
        self.assertEqual(ws[1][col].value, 'بيانات الصنف')   # still inside the item-info group
        self.assertEqual(len([c for c in ws[1] if c.value == 'بيانات الصنف']), 23)

    def test_flags_and_colours_the_over_covered_items_only(self):
        from apps.purchasing.pivot_sheets import BUY_COVER_LABEL
        ws = self._book()
        hdr = [c.value for c in ws[2]]
        col, cov, code = hdr.index(BUY_COVER_LABEL), hdr.index(COV_COL), hdr.index('itemcode')
        rows = {r[code].value: r for r in ws.iter_rows(min_row=3)}
        self.assertIn('8.0 شهر', rows['C2'][col].value)
        self.assertIn('بلا مبيعات', rows['C3'][col].value)
        self.assertIn(rows['C1'][col].value, (None, ''))
        self.assertIn(rows['C4'][col].value, (None, ''))
        orange = rows['C2'][cov].fill.fgColor.rgb
        self.assertTrue(str(orange).endswith('FED7AA'))
        self.assertFalse(str(rows['C4'][cov].fill.fgColor.rgb).endswith('FED7AA'))

    def test_never_changes_the_order_qty(self):
        ws = self._book()
        hdr = [c.value for c in ws[2]]
        gap, code = hdr.index(GAP_COL), hdr.index('itemcode')
        rows = {r[code].value: r[gap].value for r in ws.iter_rows(min_row=3)}
        self.assertEqual(rows['C1'], 4)
        self.assertEqual(rows['C2'], -3)

    def test_matches_what_the_receipt_check_reads(self):
        """The P-31 sheet keeps the same cover for the same item, so the receipt check flags the same lines."""
        from apps.procurement.receipt_check import NO_SALES, cover_months
        from apps.purchasing.models import PivotSheetSnapshot
        from apps.purchasing.pivot_sheets import BUY_COVER_LABEL
        ws = self._book()
        hdr = [c.value for c in ws[2]]
        col, code = hdr.index(BUY_COVER_LABEL), hdr.index('itemcode')
        warned = {r[code].value for r in ws.iter_rows(min_row=3) if r[col].value}
        covers = PivotSheetSnapshot.objects.get().covers
        p31 = {c for c, v in covers.items() if v == NO_SALES or float(v) >= cover_months()}
        self.assertEqual(warned, p31)

    def test_setting_moves_the_sheet(self):
        from apps.purchasing.pivot_sheets import BUY_COVER_LABEL
        _setting('receipt_check_cover_months', 10)
        ws = self._book()
        hdr = [c.value for c in ws[2]]
        col, code = hdr.index(BUY_COVER_LABEL), hdr.index('itemcode')
        rows = {r[code].value: r[col].value for r in ws.iter_rows(min_row=3)}
        self.assertIn(rows['C2'], (None, ''))          # 8 months < 10
        self.assertTrue(rows['C3'])                    # no sales is always flagged


class NetworkExportAndScreenTests(_Fixture):

    def test_network_export_has_cover_and_warning(self):
        from openpyxl import load_workbook
        from apps.purchasing.pivot_sheets import BUY_COVER_LABEL
        r = self.client_.get('/api/purchasing/export/?view=aggregated')
        self.assertEqual(r.status_code, 200)
        rows = [list(x) for x in load_workbook(io.BytesIO(r.content), read_only=True).active.iter_rows(values_only=True)]
        hdr_i = next(i for i, x in enumerate(rows) if 'رمز الصنف' in x)
        hdr = rows[hdr_i]
        stock = hdr.index('إجمالي المخزون')
        self.assertEqual(hdr[stock + 1:stock + 3], ['تغطية الشبكة (شهور)', BUY_COVER_LABEL])
        by = {x[hdr.index('رمز الصنف')]: x for x in rows[hdr_i + 1:] if x and x[hdr.index('رمز الصنف')]}
        self.assertEqual(by['C2'][stock + 1], 8.0)
        self.assertIn('شراء رغم تغطية', by['C2'][stock + 2])
        self.assertIn(by['C4'][stock + 2], (None, ''))

    def test_network_tab_carries_the_badge(self):
        r = self.client_.get('/api/purchasing/aggregated/')
        self.assertEqual(r.status_code, 200)
        data = r.data['results'] if isinstance(r.data, dict) else r.data
        by = {x['item_code']: x['network_cover'] for x in data}
        self.assertEqual(by['C2'], {'months': 8.0, 'warn': True, 'label': by['C2']['label']})
        self.assertTrue(by['C3']['warn'])
        self.assertIsNone(by['C3']['months'])
        self.assertFalse(by['C1']['warn'])
        self.assertEqual(by['C4']['months'], 2.0)

    def test_without_purchasing_rights(self):
        from apps.tests.security.fixtures import seed_code_matrix
        from core.middleware import module_access
        seed_code_matrix()
        module_access.clear_cache()
        self.addCleanup(module_access.clear_cache)
        _u, _s, client = make_user('c16_pharm', role='pharmacist')
        self.assertEqual(client.get('/api/purchasing/aggregated/').status_code, 403)
        self.assertEqual(client.get('/api/purchasing/export/?view=pivot').status_code, 403)
