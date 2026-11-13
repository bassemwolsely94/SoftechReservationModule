"""Branch classification Task 6 — one sellable-stock rule.

Catalog / POS stock leaves out: the quarantine stores 102/103/105 (any branch), HQ store 110
(the closed-branch residue), and every store of a branch whose kind is closed or pending.
SOFTECH-writing paths and incentives keep the quarantine-only set, and the SQL text they send
to SOFTECH is unchanged.
"""
import inspect

from django.db.models import Sum
from django.test import SimpleTestCase, TestCase

from apps.batches.store_roles import QUARANTINE_STORE_CODES, quarantine_sql_in
from apps.branches.models import Branch, _reset_hq_code_cache
from apps.catalog.models import (
    EXCLUDED_STORE_CODES, Item, ItemStock, exclude_unsellable, is_sellable, unsellable_q)
from .factories import make_item


def _branch(code, kind):
    return Branch.objects.create(softech_branch_id=code, name=code, name_ar=code, kind=kind)


def _stock(item, branch, store, qty):
    return ItemStock.objects.create(item=item, branch=branch, softech_store_code=store,
                                    quantity_on_hand=qty)


class _FakeCur:
    def __init__(self):
        self.sql = []

    def execute(self, sql, params=None):
        self.sql.append(sql)

    def fetchall(self):
        return []

    def close(self):
        pass


class _FakeConn:
    def __init__(self):
        self.cur = _FakeCur()

    def cursor(self):
        return self.cur

    def close(self):
        pass


class IsrWriterSqlTests(TestCase):
    def test_build_items_plan_sql_is_byte_identical(self):
        from unittest import mock
        from apps.purchasing import isr_writer
        _branch('130', Branch.KIND_RETAIL)
        conn = _FakeConn()
        with mock.patch('config.sybase.get_branch_connection', return_value=conn):
            isr_writer.build_items_plan('130', [('A1', 2)])
        stk = [s for s in conn.cur.sql if 'stkbal' in s]
        self.assertEqual(stk, ["SELECT itemcode, sum(nowqty) FROM stkbal WHERE branchcode=? "
                               "AND storecode NOT IN ('102','103','105') AND itemcode IN (?) "
                               "GROUP BY itemcode"])


class SellableStockTests(TestCase):
    def setUp(self):
        _reset_hq_code_cache()
        self.addCleanup(_reset_hq_code_cache)
        self.hq = _branch('100', Branch.KIND_HQ)
        self.shop = _branch('130', Branch.KIND_RETAIL)
        self.item = make_item('CONCOR 5MG', 'S0001')

    def _sellable_qty(self):
        qs = exclude_unsellable(ItemStock.objects.filter(item=self.item))
        return float(qs.aggregate(q=Sum('quantity_on_hand'))['q'] or 0)

    def test_store_110_at_hq_not_sellable(self):
        _stock(self.item, self.hq, '100', 4)
        s110 = _stock(self.item, self.hq, '110', 50)
        self.assertEqual(self._sellable_qty(), 4.0)
        self.assertFalse(is_sellable(s110))

    def test_store_110_at_a_retail_branch_is_sellable(self):
        s = _stock(self.item, self.shop, '110', 3)
        self.assertEqual(self._sellable_qty(), 3.0)
        self.assertTrue(is_sellable(s))

    def test_closed_branch_stock_not_sellable(self):
        b01 = _branch('B01', Branch.KIND_CLOSED)      # the test branch B01, closed
        s = _stock(self.item, b01, '100', 9)
        _stock(self.item, self.shop, '100', 2)
        self.assertEqual(self._sellable_qty(), 2.0)
        self.assertFalse(is_sellable(s))

    def test_pending_branch_stock_not_sellable(self):
        new = _branch('140', Branch.KIND_PENDING)
        s = _stock(self.item, new, '100', 6)
        self.assertEqual(self._sellable_qty(), 0.0)
        self.assertFalse(is_sellable(s))

    def test_quarantine_still_excluded(self):
        for store in ('102', '103', '105'):
            _stock(self.item, self.hq, store, 7)
            _stock(self.item, self.shop, store, 7)
        live = _stock(self.item, self.shop, '100', 1)
        self.assertEqual(self._sellable_qty(), 1.0)
        self.assertTrue(is_sellable(live))
        for s in ItemStock.objects.filter(softech_store_code__in=['102', '103', '105']):
            self.assertFalse(is_sellable(s))

    def test_item_level_annotation_uses_the_same_rule(self):
        _stock(self.item, self.hq, '100', 4)
        _stock(self.item, self.hq, '110', 50)
        _stock(self.item, self.hq, '102', 8)
        _stock(self.item, _branch('B01', Branch.KIND_CLOSED), '100', 9)
        _stock(self.item, self.shop, '101', 2)
        row = (Item.objects.filter(id=self.item.id)
               .annotate(t=Sum('stock_levels__quantity_on_hand',
                               filter=~unsellable_q('stock_levels__')))
               .get())
        self.assertEqual(float(row.t), 6.0)

    def test_catalog_list_total_stock_and_in_stock_filter(self):
        from .factories import make_user
        _stock(self.item, self.hq, '110', 50)
        _stock(self.item, _branch('B01', Branch.KIND_CLOSED), '100', 9)
        _user, _profile, client = make_user('t6_admin', role='admin', branch=self.shop,
                                            access_all=True)
        r = client.get('/api/items/', {'in_stock': 'true', 'search': 'CONCOR'})
        self.assertEqual(r.status_code, 200, r.content[:300])
        rows = r.data['results'] if isinstance(r.data, dict) else r.data
        self.assertEqual([x for x in rows if x['id'] == self.item.id], [])
        _stock(self.item, self.shop, '100', 3)
        r = client.get('/api/items/', {'search': 'CONCOR'})
        rows = r.data['results'] if isinstance(r.data, dict) else r.data
        row = next(x for x in rows if x['id'] == self.item.id)
        self.assertEqual(row['total_stock'], 3.0)

    def test_pos_network_stock_drops_closed_and_hq_110(self):
        from apps.catalog.pos_search import network_stock
        _stock(self.item, self.hq, '110', 50)
        _stock(self.item, _branch('B01', Branch.KIND_CLOSED), '100', 9)
        _stock(self.item, self.shop, '100', 3)
        self.assertEqual(network_stock([self.item.id])[self.item.id],
                         [{'branch_id': self.shop.id, 'qty': 3.0}])


class QuarantineSetUnchangedTests(SimpleTestCase):
    """SOFTECH-writing paths and incentives keep exactly 102/103/105, byte-identical SQL."""

    def test_constant(self):
        self.assertEqual(QUARANTINE_STORE_CODES, frozenset({'102', '103', '105'}))
        self.assertIs(EXCLUDED_STORE_CODES, QUARANTINE_STORE_CODES)
        self.assertEqual(quarantine_sql_in(), "('102','103','105')")
        self.assertEqual(quarantine_sql_in(', '), "('102', '103', '105')")

    def test_isr_writer_quarantine_set_unchanged(self):
        from apps.purchasing import isr_writer
        self.assertEqual(isr_writer._EXCLUDED_STORES, {'102', '103', '105'})
        self.assertEqual(isr_writer._QUARANTINE_SQL, "('102','103','105')")

    def test_isr_guards_sql_sent_to_softech_is_byte_identical(self):
        from apps.purchasing import isr_guards
        self.assertEqual(isr_guards._QUARANTINE_SQL, "('102','103','105')")
        conn = _FakeConn()

        class Plan:
            branchcode = '130'
            lines_snapshot = [{'itemcode': 'A1', 'itemqty': 2}]
        try:
            isr_guards.review_push(Plan(), conn)
        except Exception:
            pass            # only the SQL it sent matters here
        stk = [s for s in conn.cur.sql if 'stkbal' in s]
        self.assertEqual(stk, ["SELECT itemcode, sum(nowqty) FROM stkbal WHERE branchcode=? "
                               "AND storecode NOT IN ('102','103','105') AND itemcode IN (?) "
                               "GROUP BY itemcode"])

    def test_other_quarantine_sites_unchanged(self):
        from apps.batches.queries import QUERY_STOCK_IN_MOVEMENTS
        from apps.procurement.queries import QUERY_PROCUREMENT_STKBAL
        from apps.purchasing.queries import QUERY_STKBAL
        from apps.stockcount import engine as sc_engine
        from apps.stockcount.daily import picker
        from apps.supply import position
        from apps.supply.engine import allocation
        from apps.shortage import stock_check
        for q in (QUERY_STOCK_IN_MOVEMENTS, QUERY_PROCUREMENT_STKBAL, QUERY_STKBAL):
            self.assertIn("AND st" if 'stktrans' in q else "AND sb", q)
            self.assertIn("storecode  NOT IN ('102', '103', '105')\n", q)
        self.assertEqual(sc_engine._EXCLUDED_STORES, "('102','103','105')")
        self.assertEqual(set(picker.QUARANTINE_STORES), {'102', '103', '105'})
        self.assertEqual(set(position._EXCLUDED_STORES), {'102', '103', '105'})
        self.assertEqual(set(allocation._EXCLUDED_STORES), {'102', '103', '105'})
        self.assertEqual(set(stock_check._EXCLUDED_STORES), {'102', '103', '105'})

    def test_incentives_keep_quarantine_only(self):
        from apps.incentives import engine
        src = inspect.getsource(engine)
        self.assertNotIn('exclude_unsellable', src)
        self.assertIn('QUARANTINE_STORE_CODES', src)
