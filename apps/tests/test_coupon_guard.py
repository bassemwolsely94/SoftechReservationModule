"""
apps/tests/test_coupon_guard.py

Gift-coupon redemption guard (apps/vouchers/coupon_guard.py) + its hook in the POS validator.
No SOFTECH contact — the two read functions are patched.
"""
import datetime as dt
from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings
from rest_framework.exceptions import ValidationError

from apps.pos_orders.models import SoftechSalesOrder, SoftechSalesOrderLine
from apps.pos_orders.validators import validate_order
from apps.vouchers import coupon_guard as g
from .factories import make_branch

D = Decimal


def hist(stocked=1, redeemed=0, issued=1, pic='04HD731', last=None):
    return {'stocked': D(stocked), 'redeemed': D(redeemed), 'issued': D(issued),
            'issued_pic': pic, 'last_redeem': last}


class EvaluateTests(TestCase):
    def test_valid_coupon_passes(self):
        self.assertEqual(g.evaluate('27301-ABC123', hist(), D(1), '04HD731', []), [])

    def test_unknown_serial(self):
        errs = g.evaluate('27301-ABC123', hist(stocked=0), D(0), '04HD731', [])
        self.assertEqual(len(errs), 1)
        self.assertIn('غير مسجل', errs[0])

    def test_already_used(self):
        errs = g.evaluate('27301-ABC123', hist(redeemed=1, last=dt.date(2026, 9, 1)), D(1), '04HD731', [])
        self.assertTrue(any('مستخدم من قبل بتاريخ 2026-09-01' in e for e in errs))

    def test_return_restores_the_coupon(self):
        self.assertEqual(g.evaluate('27301-ABC123', hist(redeemed=0), D(1), '04HD731', []), [])

    def test_held_by_another_open_order(self):
        errs = g.evaluate('27301-ABC123', hist(), D(1), '04HD731', [42])
        self.assertTrue(any('#42' in e for e in errs))

    def test_not_issued_wrong_owner_not_at_branch(self):
        errs = g.evaluate('27301-ABC123', hist(issued=0, pic=''), D(0), '04HD731', [])
        self.assertTrue(any('لم يُصرف' in e for e in errs))
        self.assertTrue(any('غير موجود في مخزون هذا الفرع' in e for e in errs))
        errs = g.evaluate('27301-ABC123', hist(), D(1), '99HD1', [])
        self.assertEqual(errs, ['يجب تسجيل الفاتورة على كود صاحب الكوبون (04HD731).'])

    @override_settings(COUPON_GUARD_REQUIRE_OWNER=False, COUPON_GUARD_REQUIRE_ISSUED=False,
                       COUPON_GUARD_REQUIRE_BRANCH_STOCK=False)
    def test_rule_toggles(self):
        self.assertEqual(g.evaluate('27301-ABC123', hist(issued=0, pic='x'), D(0), 'y', []), [])

    def test_lot_serial_allows_up_to_stocked_qty(self):
        self.assertEqual(g.evaluate('20001-NXN518', hist(stocked=20, redeemed=19), D(1), '04HD731', []), [])
        self.assertTrue(g.evaluate('20001-NXN518', hist(stocked=20, redeemed=20), D(1), '04HD731', []))


class CheckSerialTests(TestCase):
    def test_bad_format(self):
        res = g.check_serial('8452')
        self.assertFalse(res['ok'])
        self.assertIn('كما هو مطبوع', res['errors'][0])

    def test_fail_closed_when_softech_unreachable(self):
        with mock.patch('config.sybase.get_sybase_connection', side_effect=OSError('down')):
            res = g.check_serial('27301-abc123')
        self.assertFalse(res['ok'])
        self.assertEqual(res['serial'], '27301-ABC123')
        self.assertIn('تعذّر التحقق', res['errors'][0])

    def test_reads_history_and_branch_stock(self):
        conn = mock.Mock()
        with mock.patch.object(g, 'read_serial_history', return_value=hist()) as rh, \
                mock.patch.object(g, 'read_branch_stock', return_value=(D(1), dt.date(2030, 3, 11))) as rb:
            res = g.check_serial('27301-ABC123', store_code='130', customer_pic='04HD731',
                                 hq_conn=conn, branch_conn=conn)
        self.assertTrue(res['ok'], res)
        rh.assert_called_once_with(conn, '27301-ABC123')
        rb.assert_called_once_with(conn, '130', '27301-ABC123')
        self.assertEqual((res['info']['issued_to'], res['info']['expiry']), ('04HD731', '2030-03-11'))


def _order(**kw):
    br = make_branch()
    kw.setdefault('store_code', '130')
    kw.setdefault('channel', 'cash')
    kw.setdefault('doc_kind', 'sale')
    return SoftechSalesOrder.objects.create(branch=br, softech_branchcode=br.softech_branch_id, **kw)


def _coupon_line(o, serial, qty=1):
    return SoftechSalesOrderLine.objects.create(order=o, softech_itemcode='118639', qty=D(qty),
                                                item_sale_price=D('0'), cust_discp=D('0'), batchno=serial)


class PosHookTests(TestCase):
    def test_off_by_default(self):
        o = _order(softech_pic='04HD731')
        _coupon_line(o, '8452')
        self.assertEqual(g.validate_order_coupons(o), {})

    @override_settings(COUPON_POS_GUARD_ENABLED=True)
    def test_blocks_push_with_reasons(self):
        o = _order(softech_pic='04HD731')
        _coupon_line(o, '27301-ABC123')
        _coupon_line(o, '27301-ABC123')
        _coupon_line(o, '27302-XYZ999', qty=2)
        with mock.patch.object(g, 'check_serial', return_value={
                'ok': False, 'errors': ['الكوبون 27301-ABC123 مستخدم من قبل — لا يمكن استخدامه مرة أخرى.']}):
            with self.assertRaises(ValidationError) as cm:
                validate_order(o)
        msgs = [str(m) for m in cm.exception.detail['coupons']]
        self.assertEqual(len(msgs), 3)
        self.assertTrue(any('مكرر' in m for m in msgs))
        self.assertTrue(any('الكمية 1' in m for m in msgs))

    @override_settings(COUPON_POS_GUARD_ENABLED=True)
    def test_open_order_holding_is_detected(self):
        other = _order(softech_pic='04HD731', status='pushed')
        _coupon_line(other, '27301-ABC123')
        o = _order(softech_pic='04HD731')
        self.assertEqual(g.open_orders_holding('27301-abc123', exclude_order_id=o.pk), [other.pk])
        self.assertEqual(g.open_orders_holding('27301-ABC123', exclude_order_id=other.pk), [])


class CheckEndpointTests(TestCase):
    URL = '/api/vouchers/coupons/check/'

    def test_requires_login(self):
        from .factories import make_anon_client
        self.assertIn(make_anon_client().get(self.URL, {'serial': '27301-ABC123'}).status_code, (401, 403))

    def test_staff_gets_the_verdict(self):
        from .factories import make_call_center
        _, _, client = make_call_center()
        with mock.patch.object(g, 'check_serial', return_value={'ok': True, 'serial': '27301-ABC123',
                                                                'errors': [], 'info': {}}) as cs:
            r = client.get(self.URL, {'serial': '27301-abc123', 'branch': '130', 'pic': '04HD731'})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['ok'])
        self.assertEqual(cs.call_args.kwargs['customer_pic'], '04HD731')


class NegativePriceExceptionTests(TestCase):
    def _neg_line_order(self, itemcode):
        o = _order(softech_pic='04HD731')
        SoftechSalesOrderLine.objects.create(order=o, softech_itemcode=itemcode, qty=D(1),
                                             item_sale_price=D('-50'), cust_discp=D('0'),
                                             batchno='27301-ABC123')
        return o

    def _price_errors(self, o):
        try:
            validate_order(o)
        except ValidationError as e:
            return [d for d in e.detail.get('lines_detail', []) if 'item_sale_price' in d]
        return []

    def test_rejected_while_guard_off(self):
        self.assertTrue(self._price_errors(self._neg_line_order('118639')))

    @override_settings(COUPON_POS_GUARD_ENABLED=True)
    def test_allowed_for_coupon_only_with_guard_on(self):
        with mock.patch.object(g, 'check_serial', return_value={'ok': True, 'errors': []}):
            self.assertEqual(self._price_errors(self._neg_line_order('118639')), [])
            self.assertTrue(self._price_errors(self._neg_line_order('12345')))


class WriterSerialAllocationTests(TestCase):
    """apps/pos_orders/writer._allocate_line: a coupon line takes EXACTLY its serial's row, not FEFO."""

    def _conn(self, row):
        cur = mock.Mock()
        cur.fetchone.return_value = row
        return mock.Mock(cursor=mock.Mock(return_value=cur)), cur

    def test_coupon_line_uses_its_own_serial_row(self):
        from apps.pos_orders import writer
        o = _order(softech_pic='04HD731')
        ln = _coupon_line(o, '27301-abc123')
        conn, cur = self._conn((dt.datetime(2030, 3, 11), 1.0))
        with mock.patch.object(writer, '_fefo_batches', side_effect=AssertionError('FEFO must not be used')):
            allocs = writer._allocate_line(conn, o, ln, True)
        self.assertEqual(allocs, [{'qty': D(1), 'expiry': '2030-03-11', 'batchno': '27301-ABC123',
                                   's_doccode': '000', 'reservation': False}])
        self.assertEqual(cur.execute.call_args.args[1], ['130', '118639', '27301-ABC123'])

    def test_missing_serial_row_refuses_instead_of_selling_another_coupon(self):
        from apps.pos_orders import writer
        o = _order(softech_pic='04HD731')
        ln = _coupon_line(o, '27301-ABC123')
        conn, _ = self._conn(None)
        with self.assertRaises(ValueError):
            writer._allocate_line(conn, o, ln, True)

    def test_other_items_keep_fefo(self):
        from apps.pos_orders import writer
        o = _order()
        ln = SoftechSalesOrderLine.objects.create(order=o, softech_itemcode='12345', qty=D(2),
                                                  item_sale_price=D('10'), cust_discp=D('0'))
        with mock.patch.object(writer, '_fefo_batches', return_value=[('2027-01-01', 5.0, None)]):
            allocs = writer._allocate_line(mock.Mock(), o, ln, True)
        self.assertEqual(allocs[0]['expiry'], '2027-01-01')


class BatchesEndpointCouponTests(TestCase):
    URL = '/api/pos-orders/batches/'

    def setUp(self):
        from .factories import make_call_center, make_item
        _, _, self.client = make_call_center()
        self.branch = make_branch()
        make_item('COUPON SERVED TO CUSTOMER', '118639')

    def _get(self):
        with mock.patch('apps.pos_orders.batch_availability.item_availability',
                        return_value=([{'expiry': '2030-03-11', 'qty': 1.0, 'batchno': '27301-ABC123'}], True)):
            return self.client.get(self.URL, {'branch': self.branch.pk, 'item': '118639', 'store': '130'})

    def test_lists_batches_while_guard_off(self):
        r = self._get()
        self.assertEqual(r.status_code, 200)
        self.assertNotEqual(r.json()['batch_action'], 'coupon_serial')

    @override_settings(COUPON_POS_GUARD_ENABLED=True)
    def test_asks_for_the_printed_serial_when_guard_on(self):
        r = self._get().json()
        self.assertEqual((r['batch_action'], r['batches']), ('coupon_serial', []))
