"""
apps/tests/test_receivables_probe.py

P-41 step 0 (docs/product-review/06_SPEC_P-41_contract_receivables.md): a SELECT-only pass over every contract
account — invoices (115) and returns (30), receipts (cheques) and SOFTECH's own receipt→invoice links
(chequestrans) — to measure collection days and how much of each contract's sales the links cover. The query
functions are mocked here; every query is filtered to one contract's account code.
"""
import datetime as dt
import io
import os
import tempfile
from decimal import Decimal
from unittest import mock

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from apps.finance import receivables_probe as P

D = dt.date


def inv(no, day, value, doccode='115', pay=0):
    return {'branchcode': '100', 'doccode': doccode, 'docnumber': no, 'docdate': day, 'cust_branch_code': '4227',
            'docvalue': value, 'docvaluepay': pay}


def rcpt(sno, day, value, cheqtype='10'):
    return {'branchcode': '100', 'cheqsno': sno, 'cheqdate': day, 'cheqvalue': value, 'cheqtype': cheqtype,
            'personcode': '4227'}


def alloc(sno, no, inv_day, amount, doccode='115'):
    return {'cheqsno': sno, 'cheqbranchcode': '100', 'branchcode': '100', 'doccode': doccode, 'docnumber': no,
            'docdate': inv_day, 'docvaluepaynow': amount}


class SummaryTests(SimpleTestCase):

    def test_value_weighted_days_coverage_and_on_account(self):
        invoices = [inv(1, D(2026, 6, 10), 1000), inv(2, D(2026, 6, 25), 3000), inv(3, D(2026, 7, 5), 1000),
                    inv(9, D(2026, 6, 30), 200, doccode='30')]
        receipts = [rcpt(50, D(2026, 7, 31), 4500), rcpt(51, D(2026, 8, 2), 100, cheqtype='20')]
        allocs = [alloc(50, 1, D(2026, 6, 10), 1000), alloc(50, 2, D(2026, 6, 25), 3000)]
        s = P.summarize('4227', invoices, receipts, allocs)
        # (1000 × 51 + 3000 × 36) / 4000 = 39.75
        self.assertEqual(s['collection_days'], Decimal('39.8'))
        self.assertEqual(s['collection_days_max'], 51)
        self.assertEqual(s['invoice_count'], 3)
        self.assertEqual(s['invoice_value'], Decimal('5000'))
        self.assertEqual(s['return_value'], Decimal('200'))
        self.assertEqual(s['allocation_coverage_pct'], Decimal('80.0'))   # 4000 of 5000
        self.assertEqual(s['receipts_by_type'], {'10': {'count': 1, 'value': Decimal('4500')},
                                                 '20': {'count': 1, 'value': Decimal('100')}})
        self.assertEqual(s['on_account'], Decimal('500'))                 # receipt 50: 4500 − 4000 linked
        self.assertEqual(s['reliable'], True)

    def test_unreliable_when_links_are_thin(self):
        invoices = [inv(1, D(2026, 6, 10), 1000), inv(2, D(2026, 6, 25), 3000)]
        receipts = [rcpt(50, D(2026, 7, 31), 4000)]
        allocs = [alloc(50, 1, D(2026, 6, 10), 1000)]
        s = P.summarize('4227', invoices, receipts, allocs)
        self.assertEqual(s['allocation_coverage_pct'], Decimal('25.0'))
        self.assertFalse(s['reliable'])

    def test_no_allocations(self):
        s = P.summarize('4227', [inv(1, D(2026, 6, 10), 1000)], [], [])
        self.assertIsNone(s['collection_days'])
        self.assertEqual(s['allocation_coverage_pct'], Decimal('0.0'))
        self.assertFalse(s['reliable'])


class ContractListTests(TestCase):

    def test_contract_accounts_from_sales_history(self):
        from django.utils import timezone
        from apps.customers.models import PurchaseHistory
        from apps.tests.factories import make_branch, make_customer
        br, cust = make_branch('B', '130'), make_customer()
        now = timezone.now()
        for pc, ch, days in (('4227', '10', 10), ('4227', '10', 40), ('4288', '10', 100), ('9001', '91', 5),
                             ('4300', '10', 500)):
            PurchaseHistory.objects.create(branch=br, customer=cust, softech_personcode=pc,
                                           softech_invoice_id=f'{pc}-{days}', sales_channel=ch,
                                           invoice_date=now - dt.timedelta(days=days))
        self.assertEqual(P.contract_personcodes(), ['4227', '4288'])


class CommandTests(TestCase):

    def test_every_query_is_one_contract_and_a_csv_is_written(self):
        calls = []

        def fake(kind):
            def f(party_type, date_from, date_to, branch=None, personcode=None, **kw):
                calls.append((kind, party_type, personcode))
                return {'inv': [inv(1, D(2026, 6, 10), 1000)], 'rcpt': [rcpt(50, D(2026, 7, 31), 1000)],
                        'alloc': [alloc(50, 1, D(2026, 6, 10), 1000)]}[kind]
            return f
        out_dir = tempfile.mkdtemp()
        with mock.patch.object(P, 'get_invoices', fake('inv')), mock.patch.object(P, 'get_vouchers', fake('rcpt')), \
             mock.patch.object(P, 'get_allocations', fake('alloc')), \
             mock.patch.object(P, 'get_party_balances', return_value=[{'personcode': '4227', 'personname': 'X',
                                                                      'ptcode': '10', 'ptclassifcode': '10',
                                                                      'softech_balance': -500}]):
            stdout = io.StringIO()
            call_command('probe_contract_receivables', '--personcodes', '4227,4288', '--out-dir', out_dir,
                         stdout=stdout)
        self.assertTrue(calls)
        self.assertTrue(all(pt == 'customer' and pc in ('4227', '4288') for _, pt, pc in calls))
        files = os.listdir(out_dir)
        self.assertEqual(len(files), 1)
        self.assertIn('4227', open(os.path.join(out_dir, files[0]), encoding='utf-8-sig').read())
        self.assertIn('51', stdout.getvalue())               # collection days printed

    def test_list_only_reads_nothing_from_softech(self):
        with mock.patch.object(P, 'get_invoices', side_effect=AssertionError('SOFTECH read')):
            stdout = io.StringIO()
            call_command('probe_contract_receivables', '--personcodes', '4227', '--list-only', stdout=stdout)
        self.assertIn('4227', stdout.getvalue())
