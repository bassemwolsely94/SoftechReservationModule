"""A PurchaseHistory INSERT that leaves out softech_personcode must not abort the sales sync.

2026-10-28: a run_scheduler started before customers 0028 kept inserting PurchaseHistory
without the new NOT NULL column → null → every fast-sync bulk_create failed (receipt
140-30-15560-20261028 first in the batch) and no later sale could land. customers 0029
gives the column a DB DEFAULT '' so such an insert lands, and the next correct sync
rewrites the account code through ON CONFLICT."""
import datetime as dt

from django.db import connection
from django.test import TestCase

from apps.branches.models import Branch
from apps.customers.models import Customer, PurchaseHistory

TABLE = 'customers_purchasehistory'


class PersoncodeDbDefaultTests(TestCase):

    def setUp(self):
        self.branch = Branch.objects.create(softech_branch_id='140', name='B140', name_ar='فرع ١٤٠')
        self.customer = Customer.objects.create(name='Walk-In', softech_pic='ACCT-1510')
        self.template = PurchaseHistory.objects.create(
            customer=self.customer, branch=self.branch, softech_invoice_id='140-30-15559-20261028',
            doc_code='30', docnumber='15559', total_amount='598.40',
            invoice_date=dt.datetime(2026, 10, 28, tzinfo=dt.timezone.utc), softech_personcode='1510')

    def _stale_insert(self, invoice_id):
        """INSERT the way a process built before 0028 does: every column but softech_personcode."""
        with connection.cursor() as c:
            c.execute('SELECT column_name FROM information_schema.columns WHERE table_name = %s', [TABLE])
            cols = [r[0] for r in c.fetchall() if r[0] not in ('id', 'softech_invoice_id', 'softech_personcode')]
            col_sql = ', '.join(cols)
            c.execute(f'INSERT INTO {TABLE} (softech_invoice_id, {col_sql}) '
                      f'SELECT %s, {col_sql} FROM {TABLE} WHERE id = %s', [invoice_id, self.template.id])

    def test_column_has_blank_server_default(self):
        with connection.cursor() as c:
            c.execute('SELECT is_nullable, column_default FROM information_schema.columns '
                      'WHERE table_name = %s AND column_name = %s', [TABLE, 'softech_personcode'])
            nullable, default = c.fetchone()
        self.assertEqual(nullable, 'NO')          # still NOT NULL — the sale row is never dropped or nulled
        self.assertIn("''", default or '')

    def test_insert_without_personcode_lands_and_next_sync_fills_it(self):
        self._stale_insert('140-30-15560-20261028')
        ph = PurchaseHistory.objects.get(softech_invoice_id='140-30-15560-20261028')
        self.assertEqual(ph.softech_personcode, '')

        # the next correct sync upserts the same receipt (sync_sales' ON CONFLICT update_fields)
        PurchaseHistory.objects.bulk_create(
            [PurchaseHistory(customer=self.customer, branch=self.branch,
                             softech_invoice_id='140-30-15560-20261028', softech_personcode='1510')],
            update_conflicts=True, unique_fields=['softech_invoice_id'], update_fields=['softech_personcode'])
        ph.refresh_from_db()
        self.assertEqual(ph.softech_personcode, '1510')
