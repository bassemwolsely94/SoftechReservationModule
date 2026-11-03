"""PIC analytics T1 — SOFTECH localcustomers.custdate mirrored as Customer.softech_created_at."""
from datetime import date, datetime
from unittest import mock

from django.test import TestCase

from apps.customers.models import Customer

BASE = ['130', 15, 'n', '', '', None, '01001234567', '', 'HD', 0, '04HD15', '130', '', '', '',
        '1', 0, 0, 1]


def _sync(row):
    from apps.sync.models import SyncRun
    from apps.sync.tasks import sync_customers

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


class CustdateSyncTests(TestCase):
    def test_custdate_stored_as_softech_created_at(self):
        _sync(BASE + [datetime(2019, 5, 3)])
        self.assertEqual(Customer.objects.get(softech_pic='04HD15').softech_created_at, date(2019, 5, 3))

    def test_old_row_layout_without_custdate_leaves_field_null(self):
        _sync(BASE)
        self.assertIsNone(Customer.objects.get(softech_pic='04HD15').softech_created_at)
