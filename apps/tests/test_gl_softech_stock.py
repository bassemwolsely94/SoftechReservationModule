"""Closing stock from SOFTECH storebal_date (finance-gl-close Task 3). SOFTECH is mocked; nothing real is read."""
import json
from datetime import date
from decimal import Decimal
from unittest import mock

from django.test import TestCase

from apps.branches.models import Branch
from apps.config.models import SystemSetting
from apps.finance.gl import softech_stock as ss
from apps.finance.queries import sybase_gl

D = date
LOGGER = 'elrezeiky.finance'


def _line(store, qty, cost):
    return {'storecode': store, 'nowqty': qty, 'nowcostprice': cost}


def _setting(key, value):
    SystemSetting.objects.update_or_create(
        key=key, defaults={'label': key, 'value': json.dumps(value), 'value_type': 'json'})


class FakeSoftech:
    """snapshots = {date: {store: [(qty, cost), ...]}}; a store with an empty list ran the report with no lines."""

    def __init__(self, snapshots, names=None):
        self.snapshots = snapshots
        self.names = names or {}

    def rows(self, as_of):
        return [_line(s, q, c) for s, lines in self.snapshots.get(as_of, {}).items() for q, c in lines]

    def datem(self, d1=None, d2=None):
        return [{'storebaldate': d, 'storecode': s} for d, stores in self.snapshots.items()
                if (d1 is None or d >= d1) and (d2 is None or d <= d2) for s in stores]

    def stores(self):
        return [{'storecode': s, 'storename': n} for s, n in self.names.items()]

    def __enter__(self):
        self._p = [mock.patch.object(sybase_gl, 'storebal_rows', self.rows),
                   mock.patch.object(sybase_gl, 'storebal_snapshots', self.datem),
                   mock.patch.object(sybase_gl, 'store_names', self.stores)]
        for p in self._p:
            p.start()
        return self

    def __exit__(self, *a):
        for p in self._p:
            p.stop()


class ReadStorebalTests(TestCase):
    def test_store_total_rounded_once_half_up(self):
        fake = FakeSoftech({D(2026, 1, 31): {'100': [(1, 0.333), (1, 0.333), (1, 0.334)]}})
        with fake:
            rows = ss.read_storebal(D(2026, 1, 31))
        self.assertEqual(rows, [ss.StoreRow('100', 3, Decimal('1.00'))])   # three rounded rows would give 0.99

    def test_half_cent_rounds_up_per_store(self):
        with FakeSoftech({D(2026, 1, 31): {'100': [(1, 0.005)], '101': [(1, 0.004)]}}):
            rows = {r.store_code: r.value for r in ss.read_storebal(D(2026, 1, 31))}
        self.assertEqual(rows, {'100': Decimal('0.01'), '101': Decimal('0.00')})

    def test_negative_rows_count(self):
        with FakeSoftech({D(2026, 1, 31): {'100': [(10, 2.5), (-4, 2.5)]}}):
            rows = ss.read_storebal(D(2026, 1, 31))
        self.assertEqual(rows[0].value, Decimal('15.00'))
        self.assertEqual(rows[0].rows, 2)

    def test_store_codes_are_stripped(self):
        with FakeSoftech({D(2026, 1, 31): {'100 ': [(1, 1.5)]}}):
            self.assertEqual(ss.read_storebal(D(2026, 1, 31))[0].store_code, '100')


class StoreMapTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Branch.objects.create(softech_branch_id='100', name='hq')
        Branch.objects.create(softech_branch_id='150', name='b150')
        Branch.objects.create(softech_branch_id='120', name='b120', kind=Branch.KIND_CLOSED)

    def test_quarantine_included_closed_excluded_by_default(self):
        m = ss.store_map(['110'])
        for quarantine in ('102', '103', '105', '152'):
            self.assertTrue(m[quarantine].included, quarantine)
        self.assertFalse(m['110'].included)
        self.assertFalse(m['120'].included)
        self.assertTrue(m['100'].included)
        self.assertTrue(m['150'].included)

    def test_default_branches(self):
        m = ss.store_map()
        for s in ('100', '101', '102', '103', '104', '105'):
            self.assertEqual(m[s].branch_code, '100')
        self.assertEqual(m['152'].branch_code, '150')
        self.assertEqual(m['150'].branch_code, '150')
        self.assertIn('b150', m['150'].label)

    def test_setting_overrides_store_inclusion_and_branch(self):
        _setting('gl_closing_stock_stores', {'105': {'included': False}, '152': {'branch': '100'},
                                             '120': {'included': True}})
        m = ss.store_map()
        self.assertFalse(m['105'].included)
        self.assertEqual(m['105'].branch_code, '100')       # untouched field keeps its default
        self.assertEqual(m['152'].branch_code, '100')
        self.assertTrue(m['152'].included)
        self.assertTrue(m['120'].included)                  # the setting beats the closed branch

    def test_invalid_setting_entry_ignored(self):
        _setting('gl_closing_stock_stores', {
            '105': {'included': 'no'}, '102': 'x', '103': {'bogus': 1}, '': {'included': False},
            '152': {'branch': ''}, '130': {'included': False}})
        with self.assertLogs(LOGGER, 'WARNING') as logs:
            m = ss.store_map()
        self.assertEqual(len(logs.records), 5)
        self.assertTrue(m['105'].included and m['102'].included and m['103'].included)
        self.assertEqual(m['152'].branch_code, '150')
        self.assertFalse(m['130'].included)                 # the one valid entry is applied

    def test_setting_that_is_not_an_object_is_ignored(self):
        _setting('gl_closing_stock_stores', ['105'])
        with self.assertLogs(LOGGER, 'WARNING'):
            m = ss.store_map()
        self.assertTrue(m['105'].included)


class ValuationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Branch.objects.create(softech_branch_id='100', name='hq')
        Branch.objects.create(softech_branch_id='130', name='b130')
        Branch.objects.create(softech_branch_id='120', name='b120', kind=Branch.KIND_CLOSED)

    JAN, FEB, MAR = D(2026, 1, 23), D(2026, 2, 28), D(2026, 3, 31)

    def snaps(self):
        return {
            self.JAN: {'100': [(1, 100.0)], '130': [(2, 50.0)], '120': [(1, 7.0)], '105': [(1, 5.0)]},
            self.MAR: {'100': [(1, 120.0)], '130': [(3, 50.0)], '120': [(1, 9.0)], '105': [(1, 6.0)]},
        }

    def test_totals_included_and_excluded(self):
        with FakeSoftech(self.snaps(), {'100': 'main'}):
            v = ss.valuation(self.MAR)
        self.assertEqual(v.total, Decimal('276.00'))             # 100 + 130 + 105 (quarantine counts)
        self.assertEqual(v.excluded_total, Decimal('9.00'))      # 120 closed
        self.assertEqual(v.missing_stores, [])
        self.assertEqual(v.carried_stores, [])
        by = {s['store_code']: s for s in v.stores}
        self.assertEqual(by['100']['store_name'], 'main')
        self.assertEqual(by['120']['included'], False)
        self.assertEqual(by['100']['snapshot_date'], self.MAR)
        self.assertEqual(by['105']['branch_code'], '100')
        self.assertFalse(by['100']['carried'])

    def test_expected_stores(self):
        snaps = self.snaps()
        snaps[self.MAR]['130'] = [(1, 0.0)]    # latest value zero -> no longer expected
        snaps[self.MAR]['140'] = []            # report ran, no lines: empty snapshot, ignored
        snaps[self.JAN]['140'] = [(1, 3.0)]    # earlier non-empty snapshot decides
        with FakeSoftech(snaps):
            self.assertEqual(ss.expected_stores(), {'100', '105', '140'})

    def test_missing_store_carried_forward_until_cutoff(self):
        _setting('gl_stock_carry_forward_until', '2026-10-31')
        snaps = self.snaps()
        del snaps[self.MAR]['130']                                # 130 absent on the quarter end
        with FakeSoftech(snaps):
            v = ss.valuation(self.MAR)
        self.assertEqual(v.carried_stores, ['130'])
        self.assertEqual(v.missing_stores, [])
        row = next(s for s in v.stores if s['store_code'] == '130')
        self.assertTrue(row['carried'])
        self.assertEqual(row['snapshot_date'], self.JAN)
        self.assertEqual(row['value'], Decimal('100.00'))
        self.assertEqual(v.total, Decimal('100.00') + Decimal('120.00') + Decimal('6.00'))

    def test_default_cutoff_is_end_of_october_2026(self):
        snaps = self.snaps()
        del snaps[self.MAR]['130']
        with FakeSoftech(snaps):
            self.assertEqual(ss.valuation(self.MAR).carried_stores, ['130'])

    def test_missing_store_reported_after_cutoff(self):
        _setting('gl_stock_carry_forward_until', '2026-02-28')
        snaps = self.snaps()
        del snaps[self.MAR]['130']
        with FakeSoftech(snaps):
            v = ss.valuation(self.MAR)
        self.assertEqual(v.missing_stores, ['130'])
        self.assertEqual(v.carried_stores, [])
        self.assertNotIn('130', [s['store_code'] for s in v.stores])
        self.assertEqual(v.total, Decimal('126.00'))

    def test_no_snapshot_for_date_after_cutoff_reports_all_expected_missing(self):
        _setting('gl_stock_carry_forward_until', '2026-02-28')
        with FakeSoftech(self.snaps()):
            v = ss.valuation(D(2026, 4, 30))
        self.assertEqual(v.missing_stores, ['100', '105', '130'])    # 120 is closed, never expected
        self.assertEqual(v.stores, [])
        self.assertEqual(v.total, Decimal('0.00'))

    def test_no_snapshot_for_date_before_cutoff_carries_every_expected_store(self):
        with FakeSoftech(self.snaps()):
            v = ss.valuation(D(2026, 4, 30))
        self.assertEqual(v.carried_stores, ['100', '105', '130'])
        self.assertEqual(v.missing_stores, [])
        self.assertEqual(v.total, Decimal('276.00'))

    def test_nothing_before_as_of_cannot_be_carried(self):
        with FakeSoftech(self.snaps()):
            v = ss.valuation(D(2026, 1, 1))
        self.assertEqual(v.missing_stores, ['100', '105', '130'])

    def test_carry_forward_skips_an_empty_earlier_snapshot(self):
        """The latest earlier date with lines, not the latest earlier date: a carried 0 would understate the stock."""
        snaps = {self.JAN: {'130': [(10, 100.0)]}, D(2026, 2, 28): {'130': []}}
        with FakeSoftech(snaps):
            v = ss.valuation(self.MAR)
        self.assertEqual(v.carried_stores, ['130'])
        row = next(s for s in v.stores if s['store_code'] == '130')
        self.assertEqual((row['value'], row['snapshot_date']), (Decimal('1000.00'), self.JAN))

    def test_only_empty_earlier_snapshots_is_missing(self):
        snaps = {D(2026, 2, 28): {'130': []}, D(2026, 4, 30): {'130': [(10, 100.0)]}}
        with FakeSoftech(snaps):
            v = ss.valuation(self.MAR)
        self.assertEqual((v.carried_stores, v.missing_stores), ([], ['130']))

    def test_a_line_with_no_quantity_or_cost_names_its_store(self):
        for line in ((None, 1.5), (1, None)):
            with FakeSoftech({self.MAR: {'130': [line]}}), self.assertRaises(ss.BadStockRow) as cm:
                ss.read_storebal(self.MAR)
            self.assertEqual((cm.exception.code, cm.exception.detail['store_code']), ('bad_stock_row', '130'))
            self.assertIn('130', str(cm.exception))

    def test_store_that_ran_with_no_lines_is_present_not_missing(self):
        snaps = self.snaps()
        snaps[self.MAR]['130'] = []
        with FakeSoftech(snaps):
            v = ss.valuation(self.MAR)
        self.assertEqual(v.missing_stores, [])
        self.assertEqual(next(s for s in v.stores if s['store_code'] == '130')['rows'], 0)
