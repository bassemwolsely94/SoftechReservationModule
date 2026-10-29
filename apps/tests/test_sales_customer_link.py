"""Synced invoices belong to their PIC customer, or (no PIC) to the placeholder of their SOFTECH
sales account — never to a Customer whose softech_id (a per-branch PIC serial) equals the
account code. Bug found 2026-10-28: 8 of 355,496 PIC invoices were linked to the PIC's customer."""
import datetime as dt
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase

from apps.branches.models import Branch
from apps.customers.account_link import CustomerLinker, ensure_account_placeholders, placeholder_pic
from apps.customers.models import Customer, PurchaseHistory
from apps.sync.models import SyncRun

PERSONS = {'1510': ('Walk-In Customer', '11', '91'),
           '5007': ('ك(معاشات)_شمال القاهرة توزيع', '10', '10')}


def _sale(personcode, docnumber, phcode, total='50'):
    """One stktrans⋈stktransm row in QUERY_CUSTOMER_SALES_LINES_* column order."""
    d = dt.datetime(2026, 10, 27)
    return [personcode, '130', '115', Decimal(docnumber), d, '87116', Decimal('1'), Decimal(total),
            Decimal(total), '01', '1776', phcode, '', '10', PERSONS.get(personcode, ('', '', ''))[2],
            Decimal('40'), d, Decimal(total), Decimal('0'), Decimal('14'), Decimal('0'), Decimal('0')]


class FakeConn:
    """Sales rows for the sales query; personsdata rows for the account-name lookup;
    DISTINCT document → personcode rows for relink_purchase_customers."""

    def __init__(self, sales):
        self.sales = sales
        self.closed = False

    def cursor(self):
        conn = self

        class Cur:
            def execute(self, sql, params=None, timeout=None):
                if 'personsdata' in sql:
                    self.rows = [(pc, *PERSONS[pc]) for pc in (params or []) if pc in PERSONS]
                elif 'SELECT DISTINCT' in sql:
                    self.rows = [(r[1], r[2], r[3], r[4], r[0]) for r in conn.sales]
                else:
                    self.rows = conn.sales

            def fetchall(self):
                return self.rows

        return Cur()

    def close(self):
        self.closed = True


class SalesSyncLinkTests(TestCase):

    def setUp(self):
        Branch.objects.create(softech_branch_id='130', name='B130', name_ar='فرع ١٣٠')
        self.person = Customer.objects.create(name='صيدلية دكتور باسم', softech_pic='130HD14864', softech_id='14864')
        # decoys: PIC customers whose per-branch SERIAL equals the account codes
        self.decoy_1510 = Customer.objects.create(name='منال محمد', softech_pic='05HD1510', softech_id='1510')
        self.decoy_5007 = Customer.objects.create(name='يوسينا نبيل', softech_pic='08HD5007', softech_id='5007')

    def _sync(self, rows):
        from apps.sync.tasks import sync_sales
        return sync_sales(FakeConn(rows), SyncRun.objects.create(status='running'), query='SELECT x')

    def test_pic_invoice_goes_to_the_pic_customer(self):
        self._sync([_sale('1510', 463235, '130HD14864')])
        ph = PurchaseHistory.objects.get()
        self.assertEqual(ph.customer, self.person)
        self.assertEqual(ph.softech_personcode, '1510')

    def test_no_pic_invoice_goes_to_the_account_placeholder_named_from_softech(self):
        self._sync([_sale('5007', 418445, '')])
        ph = PurchaseHistory.objects.get()
        self.assertNotEqual(ph.customer, self.decoy_5007)
        self.assertTrue(ph.customer.is_account_placeholder)
        self.assertEqual(ph.customer.softech_pic, 'ACCT-5007')
        self.assertEqual(ph.customer.name, 'ك(معاشات)_شمال القاهرة توزيع')
        self.assertEqual(ph.customer.softech_ptclassifcode, '10')

    def test_unknown_pic_falls_back_to_the_account_not_a_serial_match(self):
        self._sync([_sale('1510', 463300, '130HD99999')])
        ph = PurchaseHistory.objects.get()
        self.assertEqual(ph.customer.softech_pic, 'ACCT-1510')
        self.assertEqual(ph.softech_phcode, '130HD99999')

    def test_one_placeholder_per_account_and_resync_is_stable(self):
        rows = [_sale('1510', 1, ''), _sale('1510', 2, ''), _sale('5007', 3, '')]
        self._sync(rows)
        self._sync(rows)
        self.assertEqual(Customer.objects.filter(is_account_placeholder=True).count(), 2)
        self.assertEqual(PurchaseHistory.objects.count(), 3)


class AccountPlaceholderTests(TestCase):

    def test_placeholder_without_softech_gets_a_code_name_then_is_refreshed(self):
        ids = ensure_account_placeholders(['5007'])
        c = Customer.objects.get(pk=ids['5007'])
        self.assertEqual((c.name, c.softech_pic, c.is_account_placeholder), ('حساب 5007', 'ACCT-5007', True))
        ensure_account_placeholders(['5007'], conn=FakeConn([]))
        c.refresh_from_db()
        self.assertEqual(c.name, 'ك(معاشات)_شمال القاهرة توزيع')

    def test_linker_never_maps_by_softech_id(self):
        Customer.objects.create(name='decoy', softech_pic='05HD1510', softech_id='1510')
        linker = CustomerLinker()
        cid = linker.resolve('', '1510')
        self.assertEqual(Customer.objects.get(pk=cid).softech_pic, placeholder_pic('1510'))

    def test_placeholders_stay_out_of_people_features(self):
        from apps.customers.recognition import recognize
        ensure_account_placeholders(['1510'])
        Customer.objects.filter(softech_pic='ACCT-1510').update(name='Walk-In Customer', phone='01000000000')
        self.assertEqual(recognize('Walk-In Customer')['matches'], [])
        self.assertEqual(recognize('01000000000')['matches'], [])


class RelinkCommandTests(TestCase):

    def setUp(self):
        self.branch = Branch.objects.create(softech_branch_id='130', name='B130', name_ar='فرع ١٣٠')
        self.person = Customer.objects.create(name='صيدلية دكتور باسم', softech_pic='130HD14864', softech_id='14864')
        self.decoy = Customer.objects.create(name='منال محمد', softech_pic='05HD1510', softech_id='1510')
        when = dt.datetime(2026, 10, 27, 12, tzinfo=dt.timezone.utc)
        for dn, pic in ((463235, '130HD14864'), (463236, '')):
            PurchaseHistory.objects.create(customer=self.decoy, branch=self.branch, doc_code='115',
                                           docnumber=str(dn), invoice_date=when, softech_phcode=pic,
                                           softech_invoice_id=f'130-115-{dn}-20261027')
        self.conn = FakeConn([_sale('1510', 463235, '130HD14864'), _sale('1510', 463236, '')])

    def _run(self, *args):
        out = StringIO()
        with mock.patch('config.sybase.get_sybase_connection', return_value=self.conn):
            call_command('relink_purchase_customers', '--start', '2026-10-27', '--end', '2026-10-28',
                         *args, stdout=out)
        return out.getvalue()

    def test_dry_run_changes_nothing(self):
        out = self._run()
        self.assertIn('DRY RUN', out)
        self.assertEqual(PurchaseHistory.objects.filter(customer=self.decoy).count(), 2)
        self.assertFalse(Customer.objects.filter(is_account_placeholder=True).exists())
        self.assertFalse(SyncRun.objects.exists())

    def test_apply_relinks_and_records_the_run(self):
        self._run('--apply')
        by_doc = {p.docnumber: p for p in PurchaseHistory.objects.select_related('customer')}
        self.assertEqual(by_doc['463235'].customer, self.person)
        self.assertEqual(by_doc['463236'].customer.softech_pic, 'ACCT-1510')
        self.assertEqual({p.softech_personcode for p in by_doc.values()}, {'1510'})
        run = SyncRun.objects.get()
        self.assertEqual((run.status, run.records_synced), ('success', 2))
        self.assertEqual(run.progress['stats']['to_pic'], 1)


class AnalyticsAccountFilterTests(TestCase):

    def test_account_filter_uses_the_invoice_account_code(self):
        from apps.analytics.views import _purchase_qs_filtered
        b = Branch.objects.create(softech_branch_id='130', name='B130', name_ar='فرع ١٣٠')
        decoy = Customer.objects.create(name='يوسينا نبيل', softech_pic='08HD5007', softech_id='5007')
        when = dt.datetime(2026, 10, 27, 12, tzinfo=dt.timezone.utc)
        PurchaseHistory.objects.create(customer=decoy, branch=b, doc_code='115', docnumber='1',
                                       invoice_date=when, softech_invoice_id='a', softech_personcode='1510')
        hit = PurchaseHistory.objects.create(customer=decoy, branch=b, doc_code='115', docnumber='2',
                                             invoice_date=when, softech_invoice_id='b', softech_personcode='5007')
        qs = _purchase_qs_filtered({'person_main_codes': '5007'})
        self.assertEqual(list(qs.values_list('id', flat=True)), [hit.id])
