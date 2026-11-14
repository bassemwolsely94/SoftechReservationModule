"""
Purchasing pivot v2 (view=pivot) follows the live branch list (branch classification piece 1,
task 5): the HQ block is found by kind (never a literal '100'), the retail blocks come from
Branch.objects.live() in code order, and a newly classified live retail branch gets its own column.
"""
import io
from datetime import date

from django.test import TestCase
from openpyxl import load_workbook

from apps.branches.models import Branch, _reset_hq_code_cache
from apps.purchasing.models import DemandCalculationRun, ItemDemandMetrics
from apps.tests.factories import make_admin, make_item

TODAY = date(2026, 10, 26)


class PivotV2BranchesTests(TestCase):
    def setUp(self):
        _reset_hq_code_cache()
        self.addCleanup(_reset_hq_code_cache)
        self.run = DemandCalculationRun.objects.create(status='success')
        self.item = make_item('PIV1', 'S1')
        self.hq = self._branch('900', Branch.KIND_HQ, 0)          # HQ is NOT '100' here
        self.retail = [self._branch(c, Branch.KIND_RETAIL, o)
                       for c, o in [('160', 1), ('170', 2), ('140', 3), ('150', 4), ('130', 5)]]
        self._branch('110', Branch.KIND_CLOSED, 6)
        self._branch('CC', Branch.KIND_CALL_CENTER, 7)
        _, _, self.client = make_admin('pivot_v2_admin')
        # the factory's home branch B01 is a test branch, not part of this network
        Branch.objects.filter(softech_branch_id='B01').update(kind=Branch.KIND_CLOSED)

    def _branch(self, code, kind, order):
        b = Branch.objects.create(softech_branch_id=code, code=code, name=f'B{code}',
                                  name_ar=f'فرع {code}', kind=kind, display_order=order)
        ItemDemandMetrics.objects.create(run=self.run, item=self.item, branch=b, calc_date=TODAY,
                                         current_stock=5, monthly_avg=10, gap=4)
        return b

    def _rows(self):
        r = self.client.get('/api/purchasing/export/?view=pivot')
        self.assertEqual(r.status_code, 200)
        ws = load_workbook(io.BytesIO(r.content), read_only=True).active
        return [list(row) for row in ws.iter_rows(values_only=True)]

    def _blocks(self, hdr):
        """Branch-block prefixes in row-2 order ('900' for '900.الرصيد-الحالى' …)."""
        out = []
        for h in hdr:
            if isinstance(h, str) and h.endswith('.الرصيد-الحالى') and not h.startswith('Total'):
                out.append(h.split('.')[0])
        return out

    def test_pivot_v2_hq_column_by_kind(self):
        rows = self._rows()
        hdr = rows[1]
        self.assertEqual(self._blocks(hdr)[0], '900')             # HQ block first, found by kind
        self.assertNotIn('100.الرصيد-الحالى', hdr)
        # HQ block = 6 cols (no coverage / priority); retail blocks keep 8
        self.assertNotIn('900.معامل-التغطية-بالشهور', hdr)
        self.assertIn('160.معامل-التغطية-بالشهور', hdr)
        # closed and call-center branches never get a block
        self.assertNotIn('110', self._blocks(hdr))
        self.assertNotIn('CC', self._blocks(hdr))
        # every row has the same width as the headers
        self.assertTrue(all(len(r) == len(hdr) for r in rows))

    def test_pivot_v2_retail_blocks_follow_code_order(self):
        # code order (owner), not display_order: HQ first, then 130 … 170
        self.assertEqual(self._blocks(self._rows()[1]),
                         ['900', '130', '140', '150', '160', '170'])

    def test_pivot_v2_includes_new_live_branch(self):
        self._branch('230', Branch.KIND_RETAIL, 0)      # display_order 0 must not move it first
        rows = self._rows()
        hdr = rows[1]
        self.assertEqual(self._blocks(hdr), ['900', '130', '140', '150', '160', '170', '230'])
        self.assertIn('230.RankCoverage', hdr)
        self.assertIn('230.RankDeficit', hdr)
        self.assertIn('230.Rank', hdr)
        self.assertTrue(all(len(r) == len(hdr) for r in rows))
        # its data reaches the sheet (stock 5 in its block)
        col = hdr.index('230.الرصيد-الحالى')
        self.assertEqual(rows[2][col], 5)
