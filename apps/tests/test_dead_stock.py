"""
apps/tests/test_dead_stock.py

P-27 part A (docs/product-review/06_SPEC_P-27_dead_stock_recovery.md): the read-only dead-stock list on
/cash-optimization. Dead = no local sale for N months (6) AND the oldest unit on hand arrived N+ months ago (FIFO over
the stock-ledger arrivals). HQ (100) is a warehouse: there a line is dead only when no branch sells the item. Lanes:
move (another branch sells it), return (nobody sells it, supplier class takes returns), stop. Nothing is written to
SOFTECH; no transfer or return is created.
"""
import datetime as dt
from decimal import Decimal
from unittest import mock

from django.test import TestCase

from apps.tests.factories import make_admin, make_branch, make_user

D = Decimal
TODAY = dt.date(2026, 11, 1)
ACTIVE = {'100', '130', '140', '150', '160', '170'}


def ago(months=0, days=0):
    return TODAY - dt.timedelta(days=round(months * 30.44) + days)


def row(item, branch, stock='0', rate='0', gap='0', last_sale=None, qty_365d='0', cost='10', **kw):
    return {'item': item, 'item_id': hash(item) % 10000, 'name': f'صنف {item}', 'branch': branch, 'stock': D(stock),
            'rate': D(rate), 'gap': D(gap), 'last_sale': last_sale, 'qty_365d': D(qty_365d), 'cost': D(cost),
            'hold': kw.get('hold', False), 'stockable': kw.get('stockable', True), 'fridge': kw.get('fridge', False),
            'no_more_use': kw.get('no_more_use', False)}


def classify(rows, **kw):
    from apps.purchasing.dead_stock import classify as C
    kw.setdefault('arrivals', {})
    kw.setdefault('suppliers', {})
    return C(rows, today=TODAY, active=kw.pop('active', ACTIVE), **kw)


def by(lines):
    return {(l['item'], l['branch']): l for l in lines}


class DeadRuleTests(TestCase):

    def test_no_sale_and_old_stock_is_dead_recent_sale_or_arrival_is_not(self):
        rows = [row('X', '130', stock='5', last_sale=ago(7)), row('Y', '130', stock='5', last_sale=ago(5)),
                row('Z', '130', stock='5', last_sale=ago(7)), row('X', '140', rate='2')]
        arrivals = {('130', 'X'): [(ago(8), D(5))], ('130', 'Y'): [(ago(8), D(5))], ('130', 'Z'): [(ago(2), D(5))]}
        got = by(classify(rows, arrivals=arrivals))
        self.assertIn(('X', '130'), got)
        self.assertNotIn(('Y', '130'), got)
        self.assertNotIn(('Z', '130'), got)

    def test_null_last_sale_and_no_arrival_in_the_year(self):
        line = by(classify([row('X', '130', stock='3')]))[('X', '130')]
        self.assertEqual((line['oldest_arrival'], line['age_note']), (None, 'older_than_year'))

    def test_fifo_small_recent_top_up_on_an_old_batch(self):
        arrivals = {('130', 'X'): [(ago(1), D(1)), (ago(9), D(10))]}         # newest first
        line = by(classify([row('X', '130', stock='5')], arrivals=arrivals))[('X', '130')]
        self.assertEqual(line['oldest_arrival'], ago(9))


class LaneTests(TestCase):

    def test_lanes(self):
        rows = [row('M', '130', stock='4'), row('M', '140', rate='3', gap='5'),
                row('R', '130', stock='4'), row('S', '130', stock='4'), row('T', '130', stock='4')]
        sup = {'R': ('565', '60'), 'S': ('900', '80')}
        got = by(classify(rows, suppliers=sup))
        self.assertEqual([got[(i, '130')]['lane'] for i in 'MRST'], ['move', 'return', 'stop', 'stop'])
        self.assertEqual(got[('T', '130')]['supplier_code'], '')

    def test_location_and_cause(self):
        rows = [row('H', '100', stock='9'),                                   # nobody sells it, only at HQ
                row('B', '130', stock='2'), row('B', '150', stock='2'),
                row('O', '100', stock='2'), row('O', '130', stock='2'),
                row('W', '100', stock='9'), row('W', '140', rate='2', gap='4')]   # HQ stock a branch sells: not dead
        got = by(classify(rows))
        self.assertEqual(got[('H', '100')]['location'], 'hq_only')
        self.assertEqual(got[('B', '130')]['location'], 'branches_only')
        self.assertEqual((got[('O', '130')]['location'], got[('O', '130')]['cause']), ('both', 'obsolete'))
        self.assertNotIn(('W', '100'), got)

    def test_exclusions(self):
        rows = [row('A', '130', stock='2', hold=True), row('B', '180', stock='2'), row('C', '110', stock='2'),
                row('D', '130', stock='2', stockable=False)]
        self.assertEqual(classify(rows, active=ACTIVE | {'110'}), [])


class MoveTests(TestCase):

    def test_targets_largest_room_first_whole_packs_max_four_never_hq(self):
        rows = [row('X', '130', stock='12.6'), row('X', '100', rate='9', gap='50'),
                row('X', '140', rate='1', gap='3'), row('X', '150', rate='1', gap='10'),
                row('X', '160', rate='1', gap='6'), row('X', '170', rate='1', gap='1'),
                row('X', '175', rate='1', gap='9')]
        line = by(classify(rows, active=ACTIVE | {'175'}))[('X', '130')]
        self.assertEqual([(t['branch'], t['qty']) for t in line['targets']], [('150', 10), ('175', 2)])
        self.assertNotIn('100', [t['branch'] for t in line['targets']])

    def test_short_dated_ranks_first_and_targets_by_rate(self):
        rows = [row('X', '130', stock='4', cost='100'), row('X', '140', rate='1', gap='10'),
                row('X', '150', rate='5', gap='2'), row('Y', '130', stock='9', cost='100'),
                row('Y', '140', rate='1', gap='9')]
        lines = classify(rows, soonest_expiry={('130', 'X'): TODAY + dt.timedelta(days=60)})
        self.assertEqual(lines[0]['item'], 'X')
        self.assertEqual(lines[0]['targets'][0]['branch'], '150')

    def test_no_move_back_threshold_fridge_and_conflict(self):
        rows = [row('X', '130', stock='5'), row('X', '140', rate='2', gap='5'), row('X', '150', rate='1', gap='5'),
                row('C', '130', stock='5', cost='2'), row('C', '140', rate='2', gap='5'),
                row('F', '130', stock='5', fridge=True), row('F', '140', rate='2', gap='5'),
                row('T', '130', stock='5'), row('T', '140', rate='2', gap='5')]
        got = by(classify(rows, sent_out={('140', 'X'): ago(3)}, open_transfers={('T', '130'): 'TR-26-5'}))
        self.assertEqual([t['branch'] for t in got[('X', '130')]['targets']], ['150'])
        self.assertTrue(got[('C', '130')]['flags']['below_threshold'])          # 5 × 2 EGP = 10 < 100
        self.assertEqual((got[('F', '130')]['targets'], got[('F', '130')]['flags']['fridge']), ([], True))
        self.assertEqual(got[('T', '130')]['flags']['conflict'], 'TR-26-5')


class SnapshotTests(TestCase):

    def setUp(self):
        from apps.catalog.models import Item
        from apps.purchasing.models import DemandCalculationRun, ItemDemandMetrics
        from django.utils import timezone
        self.run = DemandCalculationRun.objects.create(status='success', finished_at=timezone.now())
        b130, b140 = make_branch('فرع 130', '130'), make_branch('فرع 140', '140')
        dead = Item.objects.create(softech_id='DD', name='راكد', cost_price=D('50'))
        for b, stock, rate, gap in ((b130, 6, 0, 0), (b140, 0, 2, 8)):
            ItemDemandMetrics.objects.create(run=self.run, item=dead, branch=b, calc_date=TODAY,
                                             current_stock=stock, monthly_avg=rate, gap=gap)

    def test_recompute_replaces_lines_and_needs_no_softech(self):
        from apps.purchasing import dead_stock
        from apps.purchasing.models import DeadStockLine
        with mock.patch('config.sybase.get_sybase_connection', side_effect=AssertionError('no SOFTECH')):
            dead_stock.compute_snapshot(self.run, today=TODAY)
            snap = dead_stock.compute_snapshot(self.run, today=TODAY)
        lines = DeadStockLine.objects.filter(snapshot=snap)
        self.assertEqual(lines.count(), 1)
        line = lines.get()
        self.assertEqual((line.lane, line.branch_code, line.value), ('move', '130', D('300')))
        self.assertEqual(line.targets[0]['branch'], '140')
        self.assertEqual(DeadStockLine.objects.count(), 1)


class ApiTests(SnapshotTests):

    URL = '/api/purchasing/dead-stock/'

    def setUp(self):
        super().setUp()
        from apps.purchasing import dead_stock
        from apps.tests.security.fixtures import seed_code_matrix
        from core.middleware import module_access
        seed_code_matrix()
        module_access.clear_cache()
        self.addCleanup(module_access.clear_cache)
        dead_stock.compute_snapshot(self.run, today=TODAY)
        _, self.staff, self.admin = make_admin('ds_admin')

    def test_summary_lines_excel_and_decision_hides_the_line(self):
        from apps.audit.models import AuditLog
        r = self.admin.get(self.URL + 'summary/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['lanes']['move']['count'], 1)
        r = self.admin.get(self.URL + 'lines/')
        self.assertEqual(len(r.data['lines']), 1)
        self.assertIn('spreadsheetml', self.admin.get(self.URL + 'lines/?format=xlsx')['Content-Type'])
        self.assertEqual(len(self.admin.get(self.URL + 'lines/?q=راكد').data['lines']), 1)
        self.assertEqual(self.admin.get(self.URL + 'lines/?q=غيره').data['lines'], [])
        line = r.data['lines'][0]
        r = self.admin.post(self.URL + 'decisions/', {'item_id': line['item_id'], 'branch_code': '130',
                                                       'decision': 'exclude', 'reason': 'عرض قادم'}, format='json')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self.admin.get(self.URL + 'lines/').data['lines'], [])
        self.assertEqual(len(self.admin.get(self.URL + 'lines/?show_decided=1').data['lines']), 1)
        self.assertEqual(AuditLog.objects.filter(action='dead_stock_decision').count(), 1)

    def test_strategic_hold_is_audited(self):
        from apps.audit.models import AuditLog
        from apps.catalog.models import Item
        item = Item.objects.get(softech_id='DD')
        r = self.admin.post(self.URL + 'strategic-hold/', {'item_id': item.pk, 'hold': True}, format='json')
        self.assertEqual(r.status_code, 200)
        item.refresh_from_db()
        self.assertTrue(item.strategic_hold)
        self.assertEqual(AuditLog.objects.filter(action='dead_stock_strategic_hold').count(), 1)

    def test_branch_user_sees_own_branch_and_cannot_decide(self):
        from apps.branches.models import Branch
        _, _, ph140 = make_user('ds_ph140', role='pharmacist', branch=Branch.objects.get(softech_branch_id='140'))
        _, _, ph130 = make_user('ds_ph130', role='pharmacist', branch=Branch.objects.get(softech_branch_id='130'))
        self.assertEqual(ph140.get(self.URL + 'lines/').data['lines'], [])
        self.assertEqual(len(ph130.get(self.URL + 'lines/').data['lines']), 1)
        self.assertEqual(ph130.post(self.URL + 'decisions/', {'item_id': 1, 'branch_code': '130',
                                                              'decision': 'exclude', 'reason': 'x'},
                                    format='json').status_code, 403)
        self.assertEqual(ph130.post(self.URL + 'strategic-hold/', {'item_id': 1, 'hold': True},
                                    format='json').status_code, 403)


class PagingTests(ApiTests):

    def test_pages_in_rank_order_with_count_and_branch_list(self):
        from apps.catalog.models import Item
        from apps.purchasing import dead_stock
        from apps.purchasing.models import ItemDemandMetrics
        from apps.branches.models import Branch
        b130 = Branch.objects.get(softech_branch_id='130')
        for n in range(4):
            it = Item.objects.create(softech_id=f'P{n}', name=f'صفحة {n}', cost_price=D(10 + n))
            ItemDemandMetrics.objects.create(run=self.run, item=it, branch=b130, calc_date=TODAY, current_stock=5)
        dead_stock.compute_snapshot(self.run, today=TODAY)
        r = self.admin.get(self.URL + 'lines/?page_size=2&page=1').data
        self.assertEqual((r['count'], r['pages'], len(r['lines'])), (5, 3, 2))
        last = self.admin.get(self.URL + 'lines/?page_size=2&page=3').data['lines']
        self.assertEqual(len(last), 1)
        first_ids = [x['id'] for x in r['lines']]
        self.assertNotIn(last[0]['id'], first_ids)
        s = self.admin.get(self.URL + 'summary/').data
        self.assertEqual(s['branches'], [{'code': '130', 'name': 'فرع 130'}])
