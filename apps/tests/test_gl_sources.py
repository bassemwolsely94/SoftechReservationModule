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

    def test_paymenttype_in_attrs_and_condition_matches_through_real_reader(self):
        """Final review #1: paymenttype_in was dead because tender docs carried attrs {}."""
        from apps.finance.gl.rules import rule_matches
        from apps.finance.models import PostingRule
        docs = {d.source_key: d for d in READERS['sales_tenders'](date(2026, 3, 1), date(2026, 3, 31), fake(self.rows()))}
        self.assertEqual(docs['bs:130:2026-03-05:40'].attrs, {'paymenttype': '40'})
        card_only = PostingRule(code='c', source_type='sales_tenders', effective_from=date(2026, 1, 1),
                                conditions={'paymenttype_in': ['40']}, lines=[], is_active=True)
        self.assertEqual([k for k, d in sorted(docs.items()) if rule_matches(card_only, d)],
                         ['bs:130:2026-03-05:40'])

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
        # same-branch box<->bank pair (Ruling P24): the payment leg posts, the receipt leg is its mirror
        self.assertEqual({k: d.kind for k, d in docs.items()},
                         {'chq:100:11': 'transfer_bank', 'chq:100:12': 'transfer_bank_mirror'})
        self.assertEqual(len(docs), 2)
        self.assertEqual(docs['chq:100:12'].attrs['tf_cheqsno'], '11')


class TransferKindP24Tests(SimpleTestCase):
    """Ruling P24: transfer vouchers carry the counterpart SOFTECH branch or bank (fake 2026 rows)."""

    def tf(self, **kw):
        base = dict(ptcode='-1', personcode='-180', financialdoccode='10', cheqdate=datetime(2026, 6, 10),
                    cheqregisterdate=datetime(2026, 6, 10))
        base.update(kw)
        return chq(**base)

    def run6(self, rows):
        return run_cheques(rows, date(2026, 6, 1), date(2026, 6, 30))[0]

    def test_hq_leg_paired_through_branch_leg(self):
        docs = self.run6([
            self.tf(branchcode='100', cheqsno='501', cheqtype='20', bankcode='10', cheqvalue=D('100000')),
            self.tf(branchcode='160', cheqsno='77', cheqtype='10', bankcode='70', tf_branchcode='100',
                    tf_cheqsno='501', cheqvalue=D('100000'))])
        hq, br = docs['chq:100:501'], docs['chq:160:77']
        self.assertEqual((hq.kind, hq.attrs['counterpart_branch']), ('transfer_branch', '160'))
        self.assertEqual((br.kind, br.attrs['counterpart_branch']), ('transfer_branch', '100'))
        self.assertEqual(hq.attrs['direction'], 'payment')
        self.assertEqual(br.attrs['direction'], 'receipt')

    def test_hq_leg_with_own_tf_branchcode(self):
        docs = self.run6([self.tf(branchcode='100', cheqsno='1', tf_branchcode='150', financialdoccode='90')])
        d = docs['chq:100:1']
        self.assertEqual((d.kind, d.attrs['counterpart_branch'], d.attrs['financialdoc']),
                         ('transfer_branch', '150', '90'))

    def test_bank_transfer_without_counterpart_branch(self):
        docs = self.run6([self.tf(branchcode='100', cheqsno='2', personcode='-181', tf_bankcode='04')])
        d = docs['chq:100:2']
        self.assertEqual((d.kind, d.attrs['tf_bankcode'], d.attrs['counterpart_branch']),
                         ('transfer_bank', '04', ''))

    def test_unpaired_transfer_stays_transfer(self):
        docs = self.run6([self.tf(branchcode='100', cheqsno='3'),
                          # own branch as tf_branchcode is not a counterpart
                          self.tf(branchcode='130', cheqsno='4', tf_branchcode='130')])
        self.assertEqual({d.kind for d in docs.values()}, {'transfer'})
        self.assertEqual(docs['chq:100:3'].attrs['counterpart_branch'], '')

    def test_two_different_branch_legs_naming_one_hq_voucher_is_ambiguous(self):
        docs = self.run6([
            self.tf(branchcode='100', cheqsno='9'),
            self.tf(branchcode='150', cheqsno='1', cheqtype='10', tf_branchcode='100', tf_cheqsno='9'),
            self.tf(branchcode='160', cheqsno='1', cheqtype='10', tf_branchcode='100', tf_cheqsno='9')])
        self.assertEqual(docs['chq:100:9'].kind, 'transfer')
        self.assertEqual(docs['chq:150:1'].kind, 'transfer_branch')

    def test_pairing_is_order_independent_and_keeps_source_keys(self):
        rows = [self.tf(branchcode='100', cheqsno='501', cheqtype='20', bankcode='10'),
                self.tf(branchcode='160', cheqsno='77', cheqtype='10', bankcode='70', tf_branchcode='100',
                        tf_cheqsno='501')]
        a = self.run6(rows)
        b = self.run6(list(reversed(rows)) + [self.tf(branchcode='999', cheqsno='0', cheqvalue=D('1'))])
        self.assertEqual({k: (d.kind, d.attrs['counterpart_branch']) for k, d in a.items()},
                         {k: (d.kind, d.attrs['counterpart_branch']) for k, d in b.items() if k in a})
        self.assertEqual(set(a), {'chq:100:501', 'chq:160:77'})

    def test_non_transfer_vouchers_untouched(self):
        docs = self.run6([self.tf(cheqsno='5', personcode='5001', ptcode='20', tf_branchcode='150')])
        d = docs['chq:100:5']
        self.assertEqual((d.source_type, d.kind, d.attrs['counterpart_branch']), ('supplier_payments', '', ''))

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
             'expcode': '43', 'expvalue': D('12.345'), 'expcomment': 'x', 'cheqsno': '77', 'bankcode': '50',
             'v_personcode': '-120', 'v_cheqdate': datetime(2026, 3, 5)}
        r.update(kw)
        return r

    def test_expense_doc(self):
        (d,) = READERS['expenses'](date(2026, 3, 1), date(2026, 3, 31), fake([self.row()]))
        self.assertEqual(d.source_key, 'exp:130:2026-03-05:1:4:77')
        self.assertEqual((d.source_type, d.kind, d.amounts), ('expenses', '43', {'amount': D('12.35')}))
        self.assertEqual(d.attrs, {'expcode': '43', 'bankcode': '50', 'cheqsno': '77', 'comment': 'x'})

    def test_expense_duplicate_key_marked_not_merged(self):
        docs = list(READERS['expenses'](date(2026, 3, 1), date(2026, 3, 31),
                                        fake([self.row(), self.row(expvalue=D('5'))])))
        self.assertEqual([d.kind for d in docs], ['__duplicate__'])
        self.assertEqual(docs[0].source_key, 'exp:130:2026-03-05:1:4:77')

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


class ExpenseKeyP8Tests(SimpleTestCase):
    def test_rows_differing_only_by_cheqsno_are_two_docs(self):
        base = {'branchcode': '130', 'expensedate': datetime(2026, 3, 5), 'intervalcode': '1', 'day_sno': '4',
                'expcode': '43', 'expvalue': D('5'), 'expcomment': '', 'bankcode': '50',
                'v_personcode': '-120', 'v_cheqdate': datetime(2026, 3, 5)}
        docs = list(READERS['expenses'](date(2026, 3, 1), date(2026, 3, 31),
                                        fake([dict(base, cheqsno='77'), dict(base, cheqsno='78')])))
        self.assertEqual([d.source_key for d in docs],
                         ['exp:130:2026-03-05:1:4:77', 'exp:130:2026-03-05:1:4:78'])
        self.assertNotIn('__duplicate__', [d.kind for d in docs])


class ExpenseVoucherLinkP20Tests(SimpleTestCase):
    """Ruling P20: expense <-> voucher link = same branch, voucher personcode '-120',
    |expensedate - cheqdate| <= 31 days. The fake fetch plays SOFTECH: it evaluates the two reader
    queries over small cheques / dailyexpenses tables with its own copy of the predicate."""

    def setUp(self):
        self.cheques = [
            chq(cheqsno='1', branchcode='130', personcode='-120', ptcode='-1', bankcode='50',
                cheqdate=datetime(2026, 3, 5)),                      # -120, expense 3 days later -> linked
            chq(cheqsno='2', branchcode='130', personcode='-120', ptcode='-1', bankcode='50',
                cheqdate=datetime(2026, 3, 1)),                      # -120, expense 40 days later -> not linked
            chq(cheqsno='3', branchcode='130', personcode='4490', ptcode='10', cheqtype='10', bankcode='50',
                cheqdate=datetime(2026, 3, 6)),                      # customer voucher -> never an expense
        ]
        self.expenses = [
            {'branchcode': '130', 'expensedate': datetime(2026, 3, 8), 'intervalcode': '1', 'day_sno': '1',
             'expcode': '12', 'expvalue': D('10'), 'expcomment': '', 'cheqsno': '1'},
            {'branchcode': '130', 'expensedate': datetime(2026, 4, 10), 'intervalcode': '1', 'day_sno': '2',
             'expcode': '12', 'expvalue': D('20'), 'expcomment': '', 'cheqsno': '2'},
            {'branchcode': '130', 'expensedate': datetime(2026, 3, 6), 'intervalcode': '1', 'day_sno': '3',
             'expcode': '12', 'expvalue': D('30'), 'expcomment': '', 'cheqsno': '3'},
        ]

    @staticmethod
    def _linked(e, c):
        return (e['branchcode'] == c['branchcode'] and str(e['cheqsno']) == str(c['cheqsno'])
                and c['personcode'] == '-120' and abs((e['expensedate'] - c['cheqdate']).days) <= 31)

    def fetch(self, sql):
        if 'dailyexpenses d WHERE' in sql:
            out = []
            for e in self.expenses:
                hits = [c for c in self.cheques if self._linked(e, c)]
                out.append({**e, 'bankcode': max((c['bankcode'] for c in hits), default=None),
                            'v_personcode': max((c['personcode'] for c in hits), default=None),
                            'v_cheqdate': max((c['cheqdate'] for c in hits), default=None)})
            return out
        return [{**c, 'has_expense': sum(1 for e in self.expenses if self._linked(e, c))}
                for c in self.cheques]

    def read(self, t, d1=date(2026, 3, 1), d2=date(2026, 4, 30)):
        return {d.source_key: d for d in READERS[t](d1, d2, self.fetch)}

    def test_minus_120_within_31_days_is_linked_and_dropped_from_treasury(self):
        exp = self.read('expenses')
        self.assertEqual(exp['exp:130:2026-03-08:1:1:1'].attrs['bankcode'], '50')
        self.assertNotIn('chq:130:1', self.read('treasury_other'))

    def test_minus_120_forty_days_apart_is_not_linked(self):
        exp = self.read('expenses')
        self.assertEqual(exp['exp:130:2026-04-10:1:2:2'].attrs['bankcode'], '')
        other = self.read('treasury_other')
        self.assertEqual(other['chq:130:2'].kind, 'expense_unlinked')

    def test_non_minus_120_voucher_never_dropped(self):
        self.assertEqual(self.read('expenses')['exp:130:2026-03-06:1:3:3'].attrs['bankcode'], '')
        self.assertIn('chq:130:3', self.read('customer_collections'))

    def test_reader_rechecks_returned_voucher_columns(self):
        """Defence in depth: even if SQL returned a voucher, the reader applies the same predicate."""
        base = {'branchcode': '130', 'expensedate': datetime(2026, 3, 5), 'intervalcode': '1', 'day_sno': '4',
                'expcode': '43', 'expvalue': D('1'), 'expcomment': '', 'cheqsno': '77', 'bankcode': '50'}
        rows = [dict(base, day_sno='1', v_personcode='-120', v_cheqdate=datetime(2026, 4, 5)),   # 31 days
                dict(base, day_sno='2', v_personcode='-120', v_cheqdate=datetime(2026, 4, 6)),   # 32 days
                dict(base, day_sno='3', v_personcode='5001', v_cheqdate=datetime(2026, 3, 5)),
                dict(base, day_sno='4', v_personcode=None, v_cheqdate=None, bankcode=None)]
        got = {d.source_key.split(':')[4]: d.attrs['bankcode']
               for d in READERS['expenses'](date(2026, 3, 1), date(2026, 3, 31), fake(rows))}
        self.assertEqual(got, {'1': '50', '2': '', '3': '', '4': ''})

    def test_sql_predicate_in_both_queries(self):
        chq_sql = sybase_gl.sql_cheques(date(2026, 3, 1), date(2026, 3, 31))
        exp_sql = sybase_gl.sql_expenses(date(2026, 3, 1), date(2026, 3, 31))
        for sql in (chq_sql, exp_sql):
            self.assertIn("c.personcode = '-120'", sql)
            self.assertIn('ABS(DATEDIFF(day, ', sql)
            self.assertIn(', c.cheqdate)) <= 31', sql)
            self.assertIn('CONVERT(varchar(20), c.cheqsno)', sql)
        self.assertIn('e.branchcode = c.branchcode', chq_sql)
        self.assertIn('CONVERT(varchar(20), e.cheqsno)', chq_sql)
        self.assertIn('d.branchcode = c.branchcode', exp_sql)
        self.assertIn('CONVERT(varchar(20), d.cheqsno)', exp_sql)
