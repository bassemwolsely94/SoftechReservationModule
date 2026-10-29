"""ERP match poll (doc 30, F4): one SOFTECH login per cycle, not per transfer; a dropped
link is retried once and never recorded as "document not found"."""
import datetime
from unittest import mock

from django.test import TestCase

from apps.sync import tasks
from apps.sync.sybase_queries import QUERY_VALIDATE_STKTRANS
from apps.tests.factories import make_branch, make_user
from apps.transfers.models import TransferRequest

HEADER = ['1001', '125', '130', datetime.datetime(2026, 10, 20), 500.0, '', 'S1']


class _Cur:
    def __init__(self, conn):
        self.conn, self._one, self.description = conn, None, []

    def execute(self, sql, params=None):
        self.conn.queries += 1
        if self.conn.dead_after is not None and self.conn.queries > self.conn.dead_after:
            raise RuntimeError('SybConnectionDeadException')
        self._one = list(HEADER) if sql == QUERY_VALIDATE_STKTRANS else None

    def fetchone(self):
        return self._one

    def fetchall(self):
        return []

    def close(self):
        pass


class _Conn:
    opened = []

    def __init__(self, dead_after=None):
        self.dead_after, self.queries, self.closed = dead_after, 0, False
        _Conn.opened.append(self)

    def cursor(self):
        return _Cur(self)

    def close(self):
        self.closed = True


class ErpMatchPollConnectionTests(TestCase):

    def setUp(self):
        _Conn.opened = []
        src, dst = make_branch('مصدر', '130'), make_branch('طالب', '140')
        _, staff, _ = make_user('ph', role='pharmacist', branch=dst)
        self.trs = [TransferRequest.objects.create(
            requesting_branch=dst, supplying_branch=src, created_by=staff,
            status='sent_to_erp', erp_match_status='pending', erp_reference=str(1001 + i))
            for i in range(3)]

    def _poll(self, opener):
        with mock.patch('config.sybase.get_sybase_connection', opener):
            tasks._poll_erp_matches()
        return [TransferRequest.objects.get(pk=t.pk).erp_match_status for t in self.trs]

    def test_one_login_for_the_whole_cycle(self):
        self.assertEqual(self._poll(lambda: _Conn()), ['matched'] * 3)
        self.assertEqual(len(_Conn.opened), 1)
        self.assertTrue(_Conn.opened[0].closed)

    def test_dropped_link_reconnects_and_retries(self):
        conns = iter([dict(dead_after=3), dict()])      # 1st transfer ok, then the link dies
        self.assertEqual(self._poll(lambda: _Conn(**next(conns))), ['matched'] * 3)
        self.assertEqual(len(_Conn.opened), 2)

    def test_link_dead_on_retry_leaves_transfer_pending(self):
        conns = iter([dict(dead_after=3), dict(dead_after=0), dict()])
        self.assertEqual(self._poll(lambda: _Conn(**next(conns))), ['matched', 'pending', 'matched'])

    def test_softech_down_marks_nothing_not_found(self):
        def down():
            raise RuntimeError('login timeout')
        self.assertEqual(self._poll(down), ['pending'] * 3)

    def test_manual_check_still_opens_its_own_connection(self):
        from apps.transfers.erp_matcher import ERPMatcher
        with mock.patch('config.sybase.get_sybase_connection', lambda: _Conn()):
            self.assertEqual(ERPMatcher(self.trs[0]).run()['status'], 'matched')
        self.assertTrue(_Conn.opened[0].closed)
