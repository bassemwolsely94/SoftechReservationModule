"""PIC Analytics Task 7 — branch / salesperson / channel / category breakdowns, on synthetic facts."""
from datetime import date as D
from decimal import Decimal

from apps.pic_analytics.queries.groups import by_branch, by_category, by_channel, by_salesperson
from apps.tests.test_pic_queries_overview import Base

D_ = Decimal


def rows(res):
    return {r['key']: r for r in res['rows']}


class GroupTests(Base):

    def test_new_pic_attributed_to_first_invoice_salesperson(self):
        res = by_salesperson(self.flt(), self.mgmt)
        r = rows(res)
        # N1's first fact row: 2026-10-05, branch A, tie-break lowest salesperson 'u1'
        self.assertEqual((r['u1']['new'], r['u2']['new'], r['']['new']), (1, 0, 0))
        self.assertEqual(r['u2']['distinct_pics'], 1)          # still counted as a visitor there
        self.assertEqual(res['total']['new'], 1)
        self.assertEqual(res['total']['key'], 'all')
        # channel: all cash; branch: A (first row), not B
        self.assertEqual(rows(by_channel(self.flt(), self.mgmt))['cash']['new'], 1)
        b = rows(by_branch(self.flt(), self.mgmt))
        self.assertEqual((b[self.ba.pk]['new'], b[self.bb.pk]['new']), (1, 0))

    def test_returning_counted_once_per_group(self):
        b = rows(by_branch(self.flt(), self.mgmt))
        a = b[self.ba.pk]
        self.assertEqual((a['distinct_pics'], a['new'], a['returning'], a['reactivated']), (3, 1, 2, 1))
        self.assertEqual(a['label'], '961 · أ')
        self.assertEqual(b[self.bb.pk]['distinct_pics'], 1)    # N1 again, not new here
        self.assertEqual(b[self.bb.pk]['returning'], 0)

    def test_branch_rows_may_exceed_total_visits(self):
        self.fact('R1', D(2026, 10, 10), self.bb, 1, 5, 3, 1, {'10': 5})   # same day, second branch
        res = by_branch(self.flt(), self.mgmt)
        self.assertEqual(res['total']['visits'], 4)
        self.assertEqual(sum(r['visits'] for r in res['rows']), 5)
        self.assertEqual(res['total']['distinct_pics'], 3)
        self.assertEqual(res['total']['gp'], res['total']['net'] - Decimal('283'))

    def test_category_net_split(self):
        res = by_category(self.flt(), self.mgmt)
        r = rows(res)
        self.assertEqual((r['10']['net'], r['50']['net']), (D_('390'), D_('80')))
        self.assertEqual((r['10']['visits'], r['50']['visits']), (3, 2))
        self.assertIsNone(r['10']['gp'])
        self.assertIsNone(r['10']['units_per_visit'])
        self.assertEqual(res['total']['net'], D_('470'))

    def test_cross_category_rate(self):
        self.assertEqual(by_category(self.flt(), self.mgmt)['cross_category_rate'], 0.25)

    def test_branch_manager_scope_and_no_cost(self):
        res = by_branch(self.flt(), self.mgr)
        self.assertEqual([r['key'] for r in res['rows']], [self.ba.pk])
        for r in res['rows'] + [res['total']]:
            self.assertNotIn('gp', r)
        self.assertEqual(res['total']['visits'], 4 - 1)        # N1's branch-B visit is out of scope
        self.assertNotIn('gp', by_category(self.flt(), self.mgr)['rows'][0])
