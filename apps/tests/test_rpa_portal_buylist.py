from unittest import mock

from django.test import TestCase

from apps.branches.models import Branch
from apps.catalog.models import Item, ItemSupplierLink
from apps.invoices.models import VendorProfile
from apps.purchasing.models import PivotSheetSnapshot
from apps.rpa.models import BuyList, BuyListLine
from apps.rpa.portal import buylist as bl
from apps.supply.models import SupplyDecision
from .factories import make_user


def _board(item, order):
    return {'rows': [{'item_id': item.pk, 'best': {'supplier': order[0]}, 'allocation': [],
                      'cells': [{'supplier': c, 'tier': 'main', 'effective_cost': 10 + n}
                                for n, c in enumerate(order)]}]}


class BuyListTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user, cls.staff, _ = make_user('bl_buyer', role='purchasing')
        cls.hq = Branch.objects.create(softech_branch_id='100', name='HQ', kind=Branch.KIND_HQ)
        VendorProfile.objects.create(name='Ibn Sina', softech_personcode='30')   # pick / send need a known code
        cls.items = [Item.objects.create(softech_id=f'BL{n}', name=f'item {n}', is_active=True)
                     for n in range(4)]

    def _pivot(self, gaps, supplier='565'):
        lines = [{'item_code': it.softech_id, 'total_gap': g, 'supplier_code': supplier}
                 for it, g in zip(self.items, gaps)]
        return PivotSheetSnapshot.objects.create(lines=lines, line_count=len(lines))

    def test_pivot_rounds_up_and_skips_zero(self):
        b = bl.create_from_pivot(self._pivot([2.2, 0, -1, 5]), staff=self.staff)
        self.assertEqual([ln.needed_qty for ln in b.lines.all()], [3, 5])
        self.assertTrue(all(ln.remaining_qty == ln.needed_qty for ln in b.lines.all()))

    def test_buylist_created_is_audited(self):
        from apps.audit.models import AuditLog
        bl.create_from_pivot(self._pivot([1, 1, 1, 1]), staff=self.staff)
        self.assertTrue(AuditLog.objects.filter(action='rpa_portal_buylist_created').exists())

    def test_unknown_item_is_error_not_line(self):
        b = bl.create_from_rows([{'item_code': 'NOPE', 'qty': 3}, {'item_code': 'BL0', 'qty': 1}],
                                staff=self.staff, file_sha256='a' * 64)
        self.assertEqual(b.lines.count(), 1)
        self.assertEqual(b.errors[0]['item_code'], 'NOPE')

    def test_default_supplier_from_board_then_setting(self):
        item = self.items[0]
        with mock.patch('apps.supply.comparison.build_board', return_value=_board(item, ['30', '565'])):
            b = bl.create_from_rows([{'item_code': 'BL0', 'qty': 2}], staff=self.staff, file_sha256='b' * 64)
        self.assertEqual(b.lines.get().chosen_supplier, '30')
        ItemSupplierLink.objects.create(item_code='BL1', item=self.items[1], supp_code='565')
        with mock.patch('apps.supply.comparison.build_board', return_value={'rows': []}):
            b2 = bl.create_from_rows([{'item_code': 'BL1', 'qty': 2}], staff=self.staff, file_sha256='c' * 64)
        self.assertEqual(b2.lines.get().chosen_supplier, '565')

    def test_default_supplier_falls_back_to_pivot_line(self):
        b = bl.create_from_pivot(self._pivot([1, 0, 0, 0], supplier='777'), staff=self.staff)
        self.assertEqual(b.lines.get().chosen_supplier, '777')

    def test_same_pivot_line_twice_refused(self):
        snap = self._pivot([1, 1, 0, 0])
        first = bl.create_from_pivot(snap, staff=self.staff)
        with self.assertRaises(bl.BuyListError) as cm:
            bl.create_from_pivot(snap, staff=self.staff)
        self.assertIn(str(first.pk), str(cm.exception))
        self.assertEqual(BuyList.objects.count(), 1)

    def _line(self, needed=10):
        b = bl.create_from_rows([{'item_code': 'BL0', 'qty': needed}], staff=self.staff,
                                file_sha256='d' * 64)
        return b, b.lines.get()

    def test_apply_result_short_makes_remainder(self):
        _, ln = self._line()
        bl.apply_result(ln, supplier_code='565', accepted=6, basket_id=1)
        ln.refresh_from_db()
        self.assertEqual(ln.remaining_qty, 4)
        self.assertEqual(ln.chosen_supplier, '')
        self.assertEqual(ln.tried[-1]['supplier'], '565')
        self.assertEqual(ln.tried[-1]['accepted'], 6)
        self.assertIn(ln, list(bl.remainders()))

    def test_apply_result_full_closes_line(self):
        _, ln = self._line()
        bl.apply_result(ln, supplier_code='565', accepted=10, basket_id=1)
        ln.refresh_from_db()
        self.assertEqual(ln.remaining_qty, 0)
        self.assertNotIn(ln, list(bl.remainders()))

    def test_pick_sets_supplier(self):
        _, ln = self._line()
        bl.pick(ln, '30', staff=self.staff)
        ln.refresh_from_db()
        self.assertEqual(ln.chosen_supplier, '30')

    def test_send_other_records_and_replays(self):
        b, ln = self._line()
        bl.pick(ln, '30', staff=self.staff)
        res = bl.send_other(b, '30', staff=self.staff)
        key = f'buylist-{b.pk}-30-1'
        self.assertEqual(res['order_ref'], key)
        self.assertFalse(res['replayed'])
        self.assertEqual(SupplyDecision.objects.filter(order_ref=key).count(), 1)
        ln.refresh_from_db()
        self.assertEqual(ln.remaining_qty, 0)
        again = bl.send_other(b, '30', staff=self.staff, idempotency_key=key)
        self.assertTrue(again['replayed'])
        self.assertEqual(SupplyDecision.objects.filter(order_ref=key).count(), 1)

    def test_send_other_refuses_portal_supplier(self):
        b, ln = self._line()
        bl.pick(ln, '565', staff=self.staff)
        with self.assertRaises(bl.BuyListError):
            bl.send_other(b, '565', staff=self.staff)

    def test_send_other_is_atomic_and_retry_orders_once(self):
        b, ln = self._line()
        bl.pick(ln, '30', staff=self.staff)
        with mock.patch.object(bl, 'apply_result', side_effect=RuntimeError('boom')):
            with self.assertRaises(RuntimeError):
                bl.send_other(b, '30', staff=self.staff)
        self.assertEqual(SupplyDecision.objects.filter(order_ref__startswith=f'buylist-{b.pk}-30-').count(), 0)
        ln.refresh_from_db()
        self.assertEqual(ln.remaining_qty, 10)
        res = bl.send_other(b, '30', staff=self.staff)
        self.assertEqual(res['order_ref'], f'buylist-{b.pk}-30-1')
        self.assertEqual(SupplyDecision.objects.filter(order_ref__startswith=f'buylist-{b.pk}-30-').count(), 1)

    def test_send_other_refuses_closed_list(self):
        b, ln = self._line()
        bl.pick(ln, '30', staff=self.staff)
        BuyList.objects.filter(pk=b.pk).update(status='closed')
        with self.assertRaises(bl.BuyListError):
            bl.send_other(b, '30', staff=self.staff)
        self.assertFalse(SupplyDecision.objects.exists())

    def test_send_other_refuses_foreign_key(self):
        b, ln = self._line()
        bl.pick(ln, '30', staff=self.staff)
        bl.send_other(b, '30', staff=self.staff)
        b2 = bl.create_from_rows([{'item_code': 'BL1', 'qty': 2}], staff=self.staff, file_sha256='e' * 64)
        bl.pick(b2.lines.get(), '30', staff=self.staff)
        with self.assertRaises(bl.BuyListError):
            bl.send_other(b2, '30', staff=self.staff, idempotency_key=f'buylist-{b.pk}-30-1')
