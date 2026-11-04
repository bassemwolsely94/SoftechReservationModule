"""Plan 2 Task 4: sales / credit / purchase source readers. Never touches SOFTECH (fake fetch)."""
from datetime import date, datetime
from decimal import Decimal
from unittest import mock

from django.test import SimpleTestCase, TestCase

from apps.finance.gl.sources import READERS, SourceDoc, content_hash
from apps.finance.gl.sources import purchases as purchases_mod  # noqa: F401  (registers)
from apps.finance.gl.sources import sales as sales_mod  # noqa: F401  (registers)
from apps.finance.gl.sources import treasury as treasury_mod  # noqa: F401
from apps.finance.gl.sources import expenses as expenses_mod  # noqa: F401
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
                'pmin': '7001.0', 'pmax': '7001.0', 'credit': D(credit), 'docvalue': D('1000'), 'docvalue1': D('1100'),
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
        self.assertEqual(doc.amounts['tax_share'], D('0.00'))

    def test_mixed_personcodes_one_doc_empty_party(self):
        r = self.row()
        r['pmax'] = '7002'
        docs = list(READERS['credit_sales'](date(2026, 3, 1), date(2026, 3, 31), fake([r])))
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0].personcode, '')
        self.assertEqual(docs[0].attrs['mixed_personcodes'], ['7001', '7002'])


class SqlTests(SimpleTestCase):
    def test_sql_is_select_and_bounded(self):
        for sql in (sybase_gl.sql_branchesales(date(2026, 3, 1), date(2026, 3, 31)),
                    sybase_gl.sql_credit_docs(date(2026, 3, 1), date(2026, 3, 31))):
            self.assertTrue(sql.lstrip().upper().startswith('SELECT'))
            self.assertIn("'2026-03-01'", sql)
            self.assertIn("'2026-04-01'", sql)
            self.assertNotIn(' TOP ', sql.upper())

    def test_month_chunks_cross_year(self):
        self.assertEqual(list(sybase_gl.month_chunks(date(2025, 12, 20), date(2026, 1, 5))),
                         [(date(2025, 12, 20), date(2025, 12, 31)), (date(2026, 1, 1), date(2026, 1, 5))])

    def test_open_fetch_refuses_non_select(self):
        with mock.patch.object(sybase_gl, 'get_sybase_connection') as g:
            with sybase_gl.open_fetch() as fetch:
                for bad in ('DELETE FROM x', 'update x set a=1', 'select 1; drop table x', 'SELECT a INTO t FROM x', 'select a into #t from x', ''):
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


def chq(**kw):
    r = {'cheqsno': '1', 'branchcode': '100', 'financialdoccode': '10', 'cheqtype': '20', 'cheqno': '9',
         'cheqdate': datetime(2026, 3, 5), 'cheqregisterdate': datetime(2026, 3, 5), 'bankcode': '40',
         'personcode': '5001', 'ptcode': '20', 'cheqvalue': D('100'), 'chequenote': 'n', 'tf_branchcode': None,
         'tf_bankcode': None, 'tf_cheqsno': None, 'banktype': '0', 'has_expense': 0}
    r.update(kw)
    return r


def run_cheques(rows, d1=date(2026, 3, 1), d2=date(2026, 3, 31)):
    f = fake(rows)
    out = {}
    for t in ('supplier_payments', 'cheque_maturity', 'customer_collections', 'treasury_other'):
        for d in READERS[t](d1, d2, f):
            out[d.source_key] = d
    return out, f


class ChequeReaderTests(SimpleTestCase):
    def test_pos_rows_dropped(self):
        docs, _ = run_cheques([chq(cheqsno='1', personcode='-170'),
                               chq(cheqsno='2', personcode='-170', financialdoccode='30')])
        self.assertEqual(docs, {})

    def test_expense_vouchers_dropped_only_when_referenced(self):
        docs, _ = run_cheques([chq(cheqsno='1', personcode='-120', ptcode='-1', has_expense=1),
                               chq(cheqsno='2', personcode='-120', ptcode='-1', has_expense=0)])
        self.assertEqual(set(docs), {'chq:100:2'})
        self.assertEqual((docs['chq:100:2'].source_type, docs['chq:100:2'].kind),
                         ('treasury_other', 'expense_unlinked'))

    def test_cheque_emits_issue_on_register_date_and_maturity_on_due_date(self):
        docs, _ = run_cheques([chq(financialdoccode='20', cheqdate=datetime(2026, 4, 20),
                                   cheqregisterdate=datetime(2026, 3, 5), cheqno='C7')],
                              date(2026, 3, 1), date(2026, 4, 30))
        issue, due = docs['chq:100:1'], docs['chqdue:100:1']
        self.assertEqual((issue.source_type, issue.doc_date), ('supplier_payments', date(2026, 3, 5)))
        self.assertEqual((due.source_type, due.doc_date), ('cheque_maturity', date(2026, 4, 20)))
        self.assertEqual(issue.amounts, {'amount': D('100.00')})
        self.assertEqual(issue.attrs['direction'], 'payment')
        self.assertEqual(issue.attrs['cheqno'], 'C7')
        self.assertEqual(issue.attrs['due_date'], '2026-04-20')
        self.assertEqual(issue.attrs['bank_type'], '0')
        self.assertEqual(issue.personcode, '5001')

    def test_issue_outside_range_but_due_inside_emits_only_maturity(self):
        docs, _ = run_cheques([chq(financialdoccode='20', cheqdate=datetime(2026, 4, 20),
                                   cheqregisterdate=datetime(2026, 3, 5))],
                              date(2026, 4, 1), date(2026, 4, 30))
        self.assertEqual(set(docs), {'chqdue:100:1'})

    def test_non_cheque_uses_cheqdate_and_no_maturity(self):
        docs, _ = run_cheques([chq(financialdoccode='10', cheqdate=datetime(2026, 3, 9),
                                   cheqregisterdate=datetime(2026, 3, 2))])
        self.assertEqual(docs['chq:100:1'].doc_date, date(2026, 3, 9))
        self.assertNotIn('chqdue:100:1', docs)

    def test_ptcode_routes_to_source_type(self):
        rows = [chq(cheqsno=str(i), ptcode=pt, personcode=pc, cheqtype='10' if pt == '10' else '20')
                for i, (pt, pc) in enumerate([('20', '5001'), ('10', '7001'), ('30', '3'), ('60', '4'),
                                              ('70', '5'), ('80', '6'), ('99', '7'), ('-1', '-180')], 1)]
        docs, _ = run_cheques(rows)
        got = {k: (d.source_type, d.kind) for k, d in docs.items()}
        self.assertEqual(got, {
            'chq:100:1': ('supplier_payments', ''), 'chq:100:2': ('customer_collections', ''),
            'chq:100:3': ('treasury_other', 'employee'), 'chq:100:4': ('treasury_other', 'partner'),
            'chq:100:5': ('treasury_other', 'asset_supplier'), 'chq:100:6': ('treasury_other', 'sister_company'),
            'chq:100:7': ('treasury_other', 'other'), 'chq:100:8': ('treasury_other', 'transfer')})
        self.assertEqual(docs['chq:100:2'].attrs['direction'], 'receipt')

    def test_transfer_legs_are_two_docs(self):
        docs, _ = run_cheques([
            chq(cheqsno='11', ptcode='-1', personcode='-180', cheqtype='20', bankcode='40', tf_branchcode='100',
                tf_bankcode='04', tf_cheqsno='12'),
            chq(cheqsno='12', ptcode='-1', personcode='-181', cheqtype='10', bankcode='04', tf_branchcode='100',
                tf_bankcode='40', tf_cheqsno='11')])
        self.assertEqual({d.kind for d in docs.values()}, {'transfer'})
        self.assertEqual(len(docs), 2)
        self.assertEqual(docs['chq:100:12'].attrs['tf_cheqsno'], '11')

    def test_one_fetch_per_month_for_all_four_types(self):
        _, f = run_cheques([chq()], date(2026, 3, 1), date(2026, 4, 30))
        self.assertEqual(len(f.calls), 2)

    def test_row_seen_in_two_month_chunks_emitted_once(self):
        docs, f = run_cheques([chq(financialdoccode='20', cheqdate=datetime(2026, 4, 2),
                                   cheqregisterdate=datetime(2026, 3, 30))], date(2026, 3, 1), date(2026, 4, 30))
        self.assertEqual(sorted(docs), ['chq:100:1', 'chqdue:100:1'])

    def test_sql_shape(self):
        sql = sybase_gl.sql_cheques(date(2026, 3, 1), date(2026, 3, 31))
        self.assertTrue(sql.lstrip().upper().startswith('SELECT'))
        self.assertIn('CONVERT(varchar(10), c.ptcode)', sql)
        self.assertIn('CONVERT(varchar(20), e.cheqsno)', sql)
        self.assertIn('banktype', sql)


class ExpenseReaderTests(SimpleTestCase):
    def row(self, **kw):
        r = {'branchcode': '130', 'expensedate': datetime(2026, 3, 5), 'intervalcode': '1', 'day_sno': '4',
             'expcode': '43', 'expvalue': D('12.345'), 'expcomment': 'x', 'cheqsno': '77', 'bankcode': '50'}
        r.update(kw)
        return r

    def test_expense_doc(self):
        (d,) = READERS['expenses'](date(2026, 3, 1), date(2026, 3, 31), fake([self.row()]))
        self.assertEqual(d.source_key, 'exp:130:2026-03-05:1:4')
        self.assertEqual((d.source_type, d.kind, d.amounts), ('expenses', '43', {'amount': D('12.35')}))
        self.assertEqual(d.attrs, {'expcode': '43', 'bankcode': '50', 'cheqsno': '77', 'comment': 'x'})

    def test_expense_duplicate_key_marked_not_merged(self):
        docs = list(READERS['expenses'](date(2026, 3, 1), date(2026, 3, 31),
                                        fake([self.row(), self.row(expvalue=D('5'))])))
        self.assertEqual([d.kind for d in docs], ['__duplicate__'])
        self.assertEqual(docs[0].source_key, 'exp:130:2026-03-05:1:4')

    def test_sql_shape(self):
        sql = sybase_gl.sql_expenses(date(2026, 3, 1), date(2026, 3, 31))
        self.assertTrue(sql.lstrip().upper().startswith('SELECT'))
        self.assertIn('dailyexpenses', sql)


class CheckCommandTests(TestCase):
    def test_mirror_diff_zero_when_vouchers_agree(self):
        from contextlib import contextmanager
        from io import StringIO
        from django.core.management import call_command
        from apps.finance.recon_models import Payment
        party = ReconParty.objects.create(party_type='supplier', softech_personcode='5001', name='S')
        Payment.objects.create(party=party, branchcode='100', cheqsno=1, direction='out', party_type='supplier',
                               voucher_date=date(2026, 3, 5), amount=D('100'))
        f = fake([chq()])

        @contextmanager
        def of():
            yield f
        out = StringIO()
        with mock.patch.object(sybase_gl, 'open_fetch', of):
            call_command('gl_check_sources', '--source', 'supplier_payments', '--from', '2026-03-01',
                         '--to', '2026-03-31', stdout=out)
        self.assertIn('diff           0.00', out.getvalue())
