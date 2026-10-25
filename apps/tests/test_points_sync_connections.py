"""Points balance sync (doc 30, F6): all 200-PIC chunks share ONE SOFTECH login;
a dropped connection is reopened once, then the run stops."""
from unittest import mock

from django.test import TestCase

from apps.customers.models import Customer
from apps.loyalty import pic_bridge
from apps.loyalty.models import LoyaltyAccount


class _Cur:
    def __init__(self, conn):
        self.conn = conn

    def execute(self, sql, params):
        self.conn.queries += 1
        if self.conn.fail or (self.conn.fail_after is not None and self.conn.queries > self.conn.fail_after):
            raise RuntimeError('SybConnectionDeadException')
        self.params = params

    def fetchall(self):
        return [[p, 10, 3] for p in self.params]


class _Conn:
    opened = []

    def __init__(self, fail=False, fail_after=None):
        self.fail, self.fail_after, self.queries, self.closed = fail, fail_after, 0, False
        _Conn.opened.append(self)

    def cursor(self):
        return _Cur(self)

    def close(self):
        self.closed = True


class PointsSyncConnectionTests(TestCase):

    def setUp(self):
        _Conn.opened = []
        for i in range(450):
            c = Customer.objects.create(name=f'C{i}', phone=f'01{i:08d}', softech_pic=f'12HD{i}')
            LoyaltyAccount.objects.create(customer=c)

    def test_three_chunks_one_login(self):
        with mock.patch.object(pic_bridge, 'get_sybase_connection', lambda: _Conn()):
            updated = pic_bridge.sync_all_softech_balances()
        self.assertEqual(len(_Conn.opened), 1)
        self.assertEqual(_Conn.opened[0].queries, 3)
        self.assertTrue(_Conn.opened[0].closed)
        self.assertEqual(updated, 450)
        self.assertEqual(LoyaltyAccount.objects.filter(softech_points_balance=7).count(), 450)

    def test_dropped_connection_reopened_once_then_stops(self):
        conns = iter([dict(fail_after=1), dict(fail=True)])   # dies after chunk 1; reconnect dead too
        with mock.patch.object(pic_bridge, 'get_sybase_connection', lambda: _Conn(**next(conns))):
            updated = pic_bridge.sync_all_softech_balances()
        self.assertEqual(len(_Conn.opened), 2)                 # one reconnect, no more
        self.assertEqual(updated, 200)                         # chunk 1 kept, run stopped
        self.assertTrue(all(c.closed for c in _Conn.opened))

    def test_dropped_connection_recovers(self):
        conns = iter([dict(fail_after=1), dict()])
        with mock.patch.object(pic_bridge, 'get_sybase_connection', lambda: _Conn(**next(conns))):
            updated = pic_bridge.sync_all_softech_balances()
        self.assertEqual((len(_Conn.opened), updated), (2, 450))

    def test_softech_down_no_crash(self):
        def down():
            raise RuntimeError('login timeout')
        with mock.patch.object(pic_bridge, 'get_sybase_connection', down):
            self.assertEqual(pic_bridge.sync_all_softech_balances(), 0)
