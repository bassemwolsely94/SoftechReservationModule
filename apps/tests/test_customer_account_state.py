"""B7 step 1 — SOFTECH account state mirrored from HQ and enforced on /pos, reservations, reminders, coupons."""
from unittest import mock

from django.test import TestCase

from apps.customers import account_state as AS
from apps.customers.models import Customer


def cust(pic, **kw):
    return Customer.objects.create(name='x', phone='0100' + pic[-4:].rjust(7, '0'), softech_pic=pic, **kw)


class StateRuleTests(TestCase):
    def test_flags_to_decisions(self):
        cases = {
            'A1': ({}, ('active', False, True, True)),
            'A2': ({'softech_status': '0'}, ('closed', True, False, False)),
            'A3': ({'softech_status': '5'}, ('deceased', True, False, False)),
            'A4': ({'softech_deceased': True, 'softech_status': '1'}, ('deceased', True, False, False)),
            'A5': ({'softech_locked': True}, ('entity', False, False, False)),
            'A6': ({'points_enrolled': False}, ('active', False, False, True)),
            'A7': ({'softech_status': ''}, ('active', False, True, True)),       # blank = unset, not blocked
        }
        for pic, (kw, want) in cases.items():
            s = AS.state(cust(pic, **kw))
            self.assertEqual((s['code'], s['blocked'], s['points'], s['reminders']), want, pic)
        self.assertEqual(AS.for_pic('A2')['message'], AS.CLOSED_MSG)
        self.assertIsNone(AS.for_pic('NOPE'))
        self.assertTrue(AS.state(None)['points'])


class SyncTests(TestCase):
    def test_sync_customers_fills_the_flags(self):
        from apps.sync.tasks import sync_customers
        from apps.sync.models import SyncRun
        row = ['130', 15, 'n', '', '', None, '01001234567', '', 'HD', 0, '04HD15', '130', '', '', '',
               '0', 1, 0, 0]

        class Cur:
            def __init__(self):
                self.rows = []

            def execute(self, sql, *a):
                self.rows = [tuple(row)] if 'localcustomers' in sql and 'personphones' not in sql else []

            def fetchall(self):
                return self.rows

        conn = mock.Mock()
        conn.cursor.side_effect = Cur
        sync_customers(conn, SyncRun.objects.create())
        c = Customer.objects.get(softech_pic='04HD15')
        self.assertEqual((c.softech_status, c.softech_locked, c.softech_deceased, c.points_enrolled),
                         ('0', True, False, False))


class EnforcementTests(TestCase):
    def setUp(self):
        from apps.tests.factories import make_branch, make_user
        self.branch = make_branch('A', '130')
        _, self.staff, self.api = make_user('cc', role='admin', branch=self.branch)

    def _order(self, pic, *, coupon=False, kind='sale'):
        from apps.pos_orders.models import SoftechSalesOrder, SoftechSalesOrderLine
        o = SoftechSalesOrder.objects.create(branch=self.branch, softech_branchcode='130', store_code='130',
                                             channel='cash', doc_kind=kind, softech_pic=pic,
                                             return_of_invoice=1 if kind == 'return' else None)
        from apps.vouchers import coupons
        SoftechSalesOrderLine.objects.create(order=o, softech_itemcode=coupons.served_item() if coupon else '100',
                                             qty=1, item_sale_price=-50 if coupon else 10)
        return o

    def _errors(self, order):
        from rest_framework.exceptions import ValidationError
        from apps.pos_orders.validators import validate_order
        try:
            validate_order(order)
        except ValidationError as e:
            return e.detail
        return {}

    def test_pos_refuses_closed_and_deceased_sales_but_not_returns(self):
        cust('C1', softech_status='0')
        cust('C2', softech_status='5')
        cust('C3')
        self.assertEqual(str(self._errors(self._order('C1')).get('softech_pic')), AS.CLOSED_MSG)
        self.assertEqual(str(self._errors(self._order('C2')).get('softech_pic')), AS.DECEASED_MSG)
        self.assertNotIn('softech_pic', self._errors(self._order('C3')))
        self.assertNotIn('softech_pic', self._errors(self._order('C1', kind='return')))

    def test_coupon_refused_for_customer_outside_points(self):
        cust('P1', points_enrolled=False)
        cust('P2', softech_locked=True)
        cust('P3')
        for pic in ('P1', 'P2'):
            errs = self._errors(self._order(pic, coupon=True))
            self.assertIn(AS.NO_POINTS_MSG, [str(m) for m in errs.get('coupons', [])], pic)
        errs = self._errors(self._order('P3', coupon=True))
        self.assertNotIn(AS.NO_POINTS_MSG, [str(m) for m in errs.get('coupons', [])])

    def test_pos_points_enrollment_respects_the_mirror(self):
        from apps.pos_orders import points
        cust('E1', points_enrolled=False)
        with mock.patch('apps.loyalty.pic_bridge.is_softech_points_enrolled', return_value=True):
            self.assertFalse(points.is_enrolled('E1'))
            self.assertTrue(points.is_enrolled('UNKNOWN'))

    def test_reservation_refused_even_with_force(self):
        from apps.catalog.models import Item
        c = cust('R1', softech_status='0')
        item = Item.objects.create(softech_id='900001', name='DRUG', is_active=True)
        r = self.api.post('/api/reservations/?force=true',
                          {'customer': c.pk, 'item': item.pk, 'branch': self.branch.pk, 'quantity': 1,
                           'contact_name': 'x', 'contact_phone': c.phone}, format='json')
        self.assertEqual(r.status_code, 400, r.data)
        self.assertEqual(r.data['account_state'], 'closed')

    def test_customer_api_exposes_state(self):
        c = cust('S1', softech_status='5')
        r = self.api.get(f'/api/customers/{c.pk}/')
        self.assertEqual(r.data['account_state']['code'], 'deceased')


from . import test_refill_reminders as TR


class ReminderTests(TR._Base):
    def test_closed_deceased_and_entity_customers_get_no_reminder(self):
        ok = self.task(due=1)
        for i, kw in enumerate(({'softech_status': '0'}, {'softech_status': '5'}, {'softech_locked': True})):
            c = self.customer(f'c{i}', f'0100765432{i}', f'B{i}')
            Customer.objects.filter(pk=c.pk).update(**kw)
            self.task(Customer.objects.get(pk=c.pk), due=1)
        to_send, skipped, rows = TR.RR.candidates()
        self.assertEqual(skipped['account_state'], 3)
        blocked = {r['task_id'] for r in rows if r['reason'] == 'account_state'}
        self.assertNotIn(ok.pk, blocked)
        self.assertEqual(len(blocked), 3)
