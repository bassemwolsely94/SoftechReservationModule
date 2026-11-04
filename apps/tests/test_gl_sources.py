"""Plan 2 Task 4: sales / credit / purchase source readers. Never touches SOFTECH (fake fetch)."""
from datetime import date, datetime
from decimal import Decimal
from unittest import mock

from django.test import SimpleTestCase, TestCase

from apps.finance.gl.sources import READERS, SourceDoc, content_hash
from apps.finance.gl.sources import purchases as purchases_mod  # noqa: F401  (registers)
from apps.finance.gl.sources import sales as sales_mod  # noqa: F401  (registers)
from apps.finance.queries import sybase_gl
from apps.finance.recon_models import APInvoice, ReconParty

D = Decimal


def fake(rows):
    calls = []

    def fetch(sql):
        calls.append(sql)
        return list(rows)
    fetch.calls = calls
    return fetch


class TendersTests(SimpleTestCase):
    def rows(self):
        dt = datetime(2026, 3, 5)
        return [
            {'branchcode': '130', 'doccode': '115.0', 'docdate': dt, 'paymenttype': '30', 's': D('1000.005')},
            {'branchcode': '130', 'doccode': '30', 'docdate': dt, 'paymenttype': '30', 's': D('100')},
            {'branchcode': '130', 'doccode': '115', 'docdate': dt, 'paymenttype': '40', 's': D('50')},
            {'branchcode': '130', 'doccode': '115', 'docdate': dt, 'paymenttype': '10', 's': D('999')},
            {'branchcode': '130', 'doccode': '115', 'docdate': dt, 'paymenttype': '50', 's': D('7')},
        ]

    def test_tenders_net_sales_minus_returns_per_branch_day(self):
        docs = {d.source_key: d for d in READERS['sales_tenders'](date(2026, 3, 1), date(2026, 3, 31), fake(self.rows()))}
        cash = docs['bs:130:2026-03-05:30']
        self.assertEqual(cash.kind, 'cash')
        self.assertEqual(cash.amounts, {'sales': D('1000.01'), 'returns': D('100.00'), 'net': D('900.01')})
        self.assertEqual(cash.doc_date, date(2026, 3, 5))
        self.assertEqual(docs['bs:130:2026-03-05:40'].kind, 'card')

    def test_credit_tender_excluded_from_tenders(self):
        keys = [d.source_key for d in READERS['sales_tenders'](date(2026, 3, 1), date(2026, 3, 31), fake(self.rows()))]
        self.assertFalse(any(k.endswith(':10') for k in keys))

    def test_unknown_paymenttype_kept_as_kind(self):
        docs = {d.source_key: d for d in READERS['sales_tenders'](date(2026, 3, 1), date(2026, 3, 31), fake(self.rows()))}
        self.assertEqual(docs['bs:130:2026-03-05:50'].kind, 'pt50')

    def test_one_query_per_calendar_month(self):
        f = fake([])
        list(READERS['sales_tenders'](date(2026, 1, 20), date(2026, 3, 10), f))
        self.assertEqual(len(f.calls), 3)
        self.assertTrue(all(c.lstrip().upper().startswith('SELECT') for c in f.calls))


class CreditTests(SimpleTestCase):
    def row(self, doccode='115', credit='600'):
        return {'branchcode': '130', 'doccode': doccode, 'docnumber': '1234.0', 'docdate': datetime(2026, 3, 5),
                'personcode': '7001.0', 'credit': D(credit), 'docvalue': D('1000'), 'docvalue1': D('1100'),
                'docvalue3': D('50')}

    def test_credit_doc_shares_prorated_and_quantised(self):
        (doc,) = READERS['credit_sales'](date(2026, 3, 1), date(2026, 3, 31), fake([self.row()]))
        self.assertEqual(doc.source_key, 'cs:130:115:1234:2026-03-05')
        self.assertEqual(doc.personcode, '7001')
        self.assertEqual(doc.amounts, {'credit': D('600.00'), 'gross_share': D('660.00'),
                                       'discount_share': D('60.00'), 'tax_share': D('30.00')})

    def test_credit_return_is_negative(self):
        (doc,) = READERS['credit_sales'](date(2026, 3, 1), date(2026, 3, 31), fake([self.row('30')]))
        self.assertEqual(doc.amounts['credit'], D('-600.00'))
        self.assertEqual(doc.amounts['gross_share'], D('-660.00'))
        self.assertEqual(doc.amounts['discount_share'], D('-60.00'))

    def test_zero_docvalue_shares_equal_credit(self):
        r = self.row()
        r['docvalue'] = D('0')
        (doc,) = READERS['credit_sales'](date(2026, 3, 1), date(2026, 3, 31), fake([r]))
        self.assertEqual(doc.amounts['gross_share'], D('600.00'))
        self.assertEqual(doc.amounts['discount_share'], D('0.00'))


class SqlTests(SimpleTestCase):
    def test_sql_is_select_and_bounded(self):
        for sql in (sybase_gl.sql_branchesales(date(2026, 3, 1), date(2026, 3, 31)),
                    sybase_gl.sql_credit_docs(date(2026, 3, 1), date(2026, 3, 31))):
            self.assertTrue(sql.lstrip().upper().startswith('SELECT'))
            self.assertIn("'2026-03-01'", sql)
            self.assertIn("'2026-04-01'", sql)
            self.assertNotIn(' TOP ', sql.upper())

    def test_open_fetch_refuses_non_select(self):
        with mock.patch.object(sybase_gl, 'get_sybase_connection') as g:
            with sybase_gl.open_fetch() as fetch:
                for bad in ('DELETE FROM x', 'update x set a=1', 'select 1; drop table x', ''):
                    with self.assertRaises(ValueError):
                        fetch(bad)
            g.return_value.close.assert_called_once()
            g.return_value.cursor.assert_not_called()


class PurchaseTests(TestCase):
    def setUp(self):
        self.sup = ReconParty.objects.create(party_type='supplier', softech_personcode='5001', name='S')
        self.cust = ReconParty.objects.create(party_type='customer', softech_personcode='7001', name='C')

    def mk(self, branch, doccode, num, d=date(2026, 3, 5), party=None, value='100', **kw):
        party = party or self.sup
        return APInvoice.objects.create(party=party, branchcode=branch, doccode=doccode, docnumber=num,
                                        docdate=d, doc_value=D(value), party_type=party.party_type, **kw)

    def test_purchase_keys_include_branch_doccode_and_date(self):
        self.mk('100', '10', '55')
        self.mk('130', '10', '55', docnumber2='X1', due_date=date(2026, 4, 1))
        self.mk('100', '120', '9', value='-40.005')
        self.mk('100', '10', '77', party=self.cust)                  # customer: excluded
        self.mk('100', '10', '78', d=date(2026, 5, 1))               # out of range
        docs = {d.source_key: d for d in READERS['purchases'](date(2026, 3, 1), date(2026, 3, 31), None)}
        self.assertEqual(set(docs), {'ap:100:10:55:2026-03-05', 'ap:130:10:55:2026-03-05', 'ap:100:120:9:2026-03-05'})
        d = docs['ap:130:10:55:2026-03-05']
        self.assertEqual((d.kind, d.personcode, d.amounts), ('invoice', '5001', {'value': D('100.00')}))
        self.assertEqual(d.attrs, {'doccode': '10', 'docnumber': '55', 'docnumber2': 'X1', 'due_date': '2026-04-01'})
        r = docs['ap:100:120:9:2026-03-05']
        self.assertEqual((r.kind, r.amounts), ('return', {'value': D('40.01')}))


class HashTests(SimpleTestCase):
    def test_hash_changes_when_amount_changes_not_when_order_changes(self):
        a = SourceDoc('x', 'k1', date(2026, 1, 1), '100', 'cash', '', {'a': D('1'), 'b': D('2')}, {})
        b = SourceDoc('x', 'k2', date(2026, 1, 1), '100', 'cash', '', {'b': D('2'), 'a': D('1')}, {})
        c = SourceDoc('x', 'k1', date(2026, 1, 1), '100', 'cash', '', {'a': D('1.01'), 'b': D('2')}, {})
        self.assertEqual(content_hash(a), content_hash(b))
        self.assertNotEqual(content_hash(a), content_hash(c))
