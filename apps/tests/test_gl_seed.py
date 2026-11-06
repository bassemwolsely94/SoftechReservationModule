"""Plan 2 / Task 7: seed rules and maps, freshness domain, scheduler window, draft-now endpoints."""
import datetime
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.branches.models import Branch
from apps.finance.gl import drafting, rules as R, seed
from apps.finance.models import (
    FinancialPeriod, GLAccount, GLAccountGroup, GLDraftRun, GLSourceMap, PostingRule,
)
from apps.sync import tasks
from apps.sync.freshness import get_freshness
from apps.tests.factories import make_user

BASE = '/api/finance/gl/'
D = datetime.date


def _all_codes():
    codes = set()
    for r in seed.RULES:
        codes.update(seed._rule_accounts(r))
    codes.update(a for _, a, _, _ in seed.BANK_MAPS)
    codes.update(a for _, a in seed.EXPENSE_MAPS)
    codes.update(a for _, a in seed.INTERCOMPANY_MAPS)
    return sorted(codes)


def _make_accounts(codes):
    g, _ = GLAccountGroup.objects.get_or_create(name='seed-g', section='balance_sheet')
    for c in codes:
        party = {'1341': 'customer', '2341': 'supplier'}.get(c, 'none')
        GLAccount.objects.get_or_create(
            code=c, defaults=dict(name=c, group=g, nature='debit', account_type='asset',
                                  party_type=party))


def _make_branches():
    for code in ('100', '130', '140', '150', '160', '170'):
        Branch.objects.get_or_create(softech_branch_id=code, defaults={'name': f'b{code}'})


class SeedTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        _make_accounts(_all_codes())
        _make_branches()
        cls.user = drafting.system_user()

    def test_seed_rules_all_validate(self):
        res = seed.seed_gl_drafting(user=self.user)
        self.assertEqual(res['skipped'], [])
        self.assertEqual(len(res['rules_created']), len(seed.RULES))
        self.assertEqual(len(res['maps_created']), len(seed.BANK_MAPS) + len(seed.EXPENSE_MAPS)
                         + len(seed.INTERCOMPANY_MAPS))
        for rule in PostingRule.objects.all():
            self.assertEqual(R.validate_rule(rule.source_type, rule.conditions, rule.lines,
                                             rule.action), [], rule.code)
        m = GLSourceMap.objects.get(kind='bank', source_value='40')
        self.assertEqual((m.account.code, m.branch.softech_branch_id), ('1302', '130'))
        self.assertEqual(GLSourceMap.objects.get(kind='bank', source_value='10').branch.softech_branch_id,
                         '100')

    def test_company_bank_maps_carry_hq_branch(self):
        seed.seed_gl_drafting(user=self.user)
        for code in ('04', '06', '01'):
            self.assertEqual(GLSourceMap.objects.get(kind='bank', source_value=code)
                             .branch.softech_branch_id, '100', code)
        self.assertFalse(GLSourceMap.objects.filter(kind='bank', branch__isnull=True).exists())

    def test_bank_maps_skipped_and_reported_without_hq_branch(self):
        Branch.objects.filter(softech_branch_id='100').delete()
        res = seed.seed_gl_drafting(user=self.user)
        skipped = {(s['what'], s['code']): s for s in res['skipped']}
        for code in ('04', '06', '01'):
            self.assertEqual(skipped[('map', f'bank:{code}')]['reason'], 'missing_branch')
            self.assertFalse(GLSourceMap.objects.filter(kind='bank', source_value=code).exists())

    def test_seed_is_idempotent_and_keeps_finance_edits(self):
        seed.seed_gl_drafting(user=self.user)
        v1 = PostingRule.objects.get(code='sales.cash', version=1)
        R.save_rule(user=self.user, code='sales.cash', source_type=v1.source_type,
                    effective_from=D(2026, 6, 1), conditions=v1.conditions, lines=v1.lines,
                    granularity=v1.granularity, book=v1.book, description='edited')
        bank = GLSourceMap.objects.get(kind='bank', source_value='40')
        R.save_map(user=self.user, kind='bank', source_value='40', account_code='1301',
                   branch_id=bank.branch_id)
        res = seed.seed_gl_drafting(user=self.user)
        self.assertEqual(res['rules_created'], [])
        self.assertEqual(res['maps_created'], [])
        self.assertEqual(PostingRule.objects.filter(code='sales.cash').count(), 2)
        self.assertEqual(PostingRule.objects.filter(code='sales.cash').order_by('-version').first().version, 2)
        self.assertEqual(GLSourceMap.objects.get(kind='bank', source_value='40').account.code, '1301')

    def test_missing_accounts_and_branches_are_reported_not_raised(self):
        GLAccount.objects.filter(code='6006').delete()      # sales.card
        GLAccount.objects.filter(code='1316').delete()      # bank map 01
        Branch.objects.filter(softech_branch_id='150').delete()   # bank map 60
        res = seed.seed_gl_drafting(user=self.user)
        skipped = {(s['what'], s['code']): s for s in res['skipped']}
        self.assertEqual(skipped[('rule', 'sales.card')]['accounts'], ['6006'])
        self.assertEqual(skipped[('map', 'bank:01')]['reason'], 'missing_account')
        self.assertEqual(skipped[('map', 'bank:60')]['reason'], 'missing_branch')
        self.assertFalse(PostingRule.objects.filter(code='sales.card').exists())
        # a later run (account now present) fills the gap
        _make_accounts(['6006'])
        res2 = seed.seed_gl_drafting(user=self.user)
        self.assertIn('sales.card', res2['rules_created'])

    def test_empty_chart_skips_everything_without_error(self):
        GLAccount.objects.all().delete()
        res = seed.seed_gl_drafting(user=self.user)
        # only rules with no static account (skip / all-mapped) can be created
        self.assertEqual(sorted(res['rules_created']),
                         ['expenses.box', 'purchases.branch', 'treasury.box_bank_in', 'treasury.box_bank_mirror',
                          'treasury.box_bank_out', 'treasury.hq_transfer_in', 'treasury.hq_transfer_out'])
        self.assertEqual(res['maps_created'], [])
        self.assertTrue(res['skipped'])

    def test_supplier_cash_debit_lands_on_the_box_branch(self):
        from decimal import Decimal
        from apps.finance.gl.sources import SourceDoc
        from apps.finance.models import GLParty
        seed.seed_gl_drafting(user=self.user)
        GLParty.objects.create(party_type='supplier', code='92', name='s', softech_personcode='5001',
                               status='confirmed')
        rule = PostingRule.objects.get(code='supplier.cash')
        d = SourceDoc('supplier_payments', 'chq:100:1', D(2026, 3, 10), '100', '', '5001',
                      {'amount': Decimal('50')},
                      {'bankcode': '40', 'financialdoc': '10', 'direction': 'payment'})
        hq = Branch.objects.get(softech_branch_id='100').pk
        lines = R.build_lines(rule, [d], hq_branch_id=hq)
        by = {l['account_code']: l for l in lines}
        b130 = Branch.objects.get(softech_branch_id='130').pk
        self.assertEqual(by['5100']['branch_id'], b130)
        self.assertEqual(by['1302']['branch_id'], b130)

    def test_supplier_cash_two_legs_through_2341_per_supplier(self):
        """Ruling P25: Dr 5100 / Cr 2341 (party) / Dr 2341 (party) / Cr box, one 2341 pair per supplier."""
        from decimal import Decimal
        from apps.finance.gl.sources import SourceDoc
        from apps.finance.models import GLParty, LedgerEntry
        seed.seed_gl_drafting(user=self.user)
        for code, pc in (('92', '5001'), ('105', '5002')):
            GLParty.objects.create(party_type='supplier', code=code, name=code, softech_personcode=pc,
                                   status='confirmed')
        day = D(2026, 3, 10)

        def pay(sno, pc, amount, note):
            return SourceDoc('supplier_payments', f'chq:140:{sno}', day, '140', '', pc,
                             {'amount': Decimal(amount)},
                             {'bankcode': '50', 'financialdoc': '10', 'direction': 'payment', 'note': note})
        docs = [pay('1', '5001', '100', 'فاتورة 77'), pay('2', '5002', '40', 'ف 9'),
                pay('3', '5001', '10', 'ف 78'), pay('4', '9999', '5', 'غير مؤكد')]
        run = drafting.start_run(triggered_by='t', date_from=day, date_to=day, source_types=['supplier_payments'])
        run = drafting.draft_range(day, day, source_types=['supplier_payments'], run=run, fetch=lambda sql: [],
                                   readers={'supplier_payments': lambda d1, d2, f: docs})
        e = LedgerEntry.objects.get(source_type='supplier_payments')
        b140 = Branch.objects.get(softech_branch_id='140').pk
        got = [(ln.account.code, ln.party_code, ln.debit, ln.credit, ln.branch_id, ln.description)
               for ln in e.lines.select_related('account').order_by('line_no')]
        z = Decimal('0')
        self.assertEqual(got, [
            ('5100', '', Decimal('150.00'), z, b140, 'مشتريات نقدية b140 2026-03-10'),
            ('2341', '92', z, Decimal('110.00'), b140, 'مشتريات نقدية 92 فاتورة 77'),
            ('2341', '92', Decimal('110.00'), z, b140, 'مشتريات نقدية 92 فاتورة 77'),
            ('1302', '', z, Decimal('150.00'), b140, ''),
            ('2341', '105', z, Decimal('40.00'), b140, 'مشتريات نقدية 105 ف 9'),
            ('2341', '105', Decimal('40.00'), z, b140, 'مشتريات نقدية 105 ف 9'),
        ])   # lines in first-seen order (build_lines), one 2341 pair per supplier
        # the unconfirmed supplier's voucher is an exception on its own, the day still drafts
        from apps.finance.models import SourceException
        ex = SourceException.objects.select_related('source_doc').get()
        self.assertEqual((ex.source_doc.source_key, ex.kind), ('chq:140:4', 'unmapped_party'))

    def _map_bank_02(self):
        R.save_map(user=self.user, kind='bank', source_value='02', account_code='1310',
                   branch_id=Branch.objects.get(softech_branch_id='100').pk)

    def _transfer_rows(self):
        from datetime import datetime
        base = dict(ptcode='-1', personcode='-180', financialdoccode='10', cheqdate=datetime(2026, 6, 10),
                    cheqregisterdate=datetime(2026, 6, 10), cheqno='', banktype='0', has_expense=0,
                    chequenote='', tf_branchcode=None, tf_bankcode=None, tf_cheqsno=None)

        def r(**kw):
            return {**base, **kw}
        from decimal import Decimal as Dec
        return [
            # HQ pays 100K from box 10 to branch 160; the 160 leg (box 70) points back at it
            r(branchcode='100', cheqsno='501', cheqtype='20', bankcode='10', cheqvalue=Dec('100000')),
            r(branchcode='160', cheqsno='77', cheqtype='10', bankcode='70', tf_branchcode='100',
              tf_cheqsno='501', cheqvalue=Dec('100000')),
            # 1-1-style «قيد تسوية» (financialdoc 90) stays an exception
            r(branchcode='100', cheqsno='1', cheqtype='20', bankcode='10', tf_branchcode='150',
              financialdoccode='90', cheqvalue=Dec('20000000')),
            # box 10 -> bank 04 at HQ, both legs present: posted once
            # live pair: box 10 -> bank 02; the bank leg 16119 points at the box leg 16118 (no tf_cheqsno)
            r(branchcode='100', cheqsno='16118', cheqtype='20', bankcode='10', personcode='-181', tf_type='1',
              tf_bankcode='02', tf_cheqsno=None, cheqvalue=Dec('31500')),
            r(branchcode='100', cheqsno='16119', cheqtype='10', bankcode='02', personcode='-181', banktype='1',
              tf_type='0', tf_bankcode='10', tf_cheqsno='16118', cheqvalue=Dec('31500')),
            # HQ leg nobody points at (P28) and a branch<->branch pair (P29): exceptions, never 1320
            r(branchcode='100', cheqsno='700', cheqtype='20', bankcode='10', cheqvalue=Dec('5')),
            r(branchcode='150', cheqsno='8', cheqtype='20', bankcode='60', tf_branchcode='160', tf_cheqsno='9',
              cheqvalue=Dec('7')),
        ]

    def test_intercompany_transfers_draft_both_companies_and_bank_once(self):
        """Ruling P24 end to end through the real treasury reader (fake SOFTECH rows)."""
        from decimal import Decimal
        from apps.finance.models import LedgerEntry, SourceException
        seed.seed_gl_drafting(user=self.user)
        self._map_bank_02()   # bank 02 of the live pair (not in the seed maps)
        rows = self._transfer_rows()
        day = D(2026, 6, 10)
        run = drafting.start_run(triggered_by='t', date_from=day, date_to=day, source_types=['treasury_other'])
        run = drafting.draft_range(day, day, source_types=['treasury_other'], run=run,
                                   fetch=lambda sql: list(rows))
        hq = Branch.objects.get(softech_branch_id='100').pk
        b160 = Branch.objects.get(softech_branch_id='160').pk
        z = Decimal('0')

        def lines(key):
            e = LedgerEntry.objects.get(source_key=key)
            return [(ln.account.code, ln.debit, ln.credit, ln.branch_id)
                    for ln in e.lines.select_related('account').order_by('line_no')]
        keys = set(LedgerEntry.objects.values_list('source_key', flat=True))
        self.assertEqual(keys, {'chq:100:501', 'chq:160:77', 'chq:100:16118'})
        hq_key, br_key, bank_key = 'chq:100:501', 'chq:160:77', 'chq:100:16118'
        self.assertEqual(lines(hq_key), [('2406', Decimal('100000.00'), z, hq), ('1301', z, Decimal('100000.00'), hq)])
        self.assertEqual(lines(br_key), [('1302', Decimal('100000.00'), z, b160), ('2404', z, Decimal('100000.00'), b160)])
        self.assertEqual(lines(bank_key), [('1310', Decimal('31500.00'), z, hq), ('1301', z, Decimal('31500.00'), hq)])
        ex = list(SourceException.objects.values_list('source_doc__source_key', 'kind'))
        self.assertEqual(sorted(ex), [('chq:100:1', 'no_rule'), ('chq:100:700', 'no_rule'), ('chq:150:8', 'no_rule')])
        self.assertEqual(LedgerEntry.objects.get(source_key=bank_key).description,
                         'تحويل بين الخزينة والبنك b100 2026-06-10')

    def test_box_bank_pair_drafted_once_across_two_runs(self):
        """Ruling P27: the mirror is decided by the row, so drafting only the bank leg's day later
        never adds a second entry."""
        from datetime import datetime
        from apps.finance.models import LedgerEntry
        seed.seed_gl_drafting(user=self.user)
        self._map_bank_02()   # bank 02 of the live pair (not in the seed maps)
        rows = [r for r in self._transfer_rows() if r['cheqsno'] in ('16118', '16119')]
        rows[1] = {**rows[1], 'cheqdate': datetime(2026, 6, 11), 'cheqregisterdate': datetime(2026, 6, 11)}
        for d1, d2, fetched in ((D(2026, 6, 10), D(2026, 6, 11), rows), (D(2026, 6, 11), D(2026, 6, 11), rows[1:])):
            run = drafting.start_run(triggered_by='t', date_from=d1, date_to=d2, source_types=['treasury_other'])
            # the bounded partner lookup (P30) still sees the box leg drafted in the first run
            run = drafting.draft_range(d1, d2, source_types=['treasury_other'], run=run,
                                       fetch=lambda sql, f=fetched: list(rows if 'DATEDIFF(day, c.cheqdate' in sql else f))
            self.assertEqual(run.status, 'success', run.detail)
            self.assertEqual(list(LedgerEntry.objects.filter(status__in=['draft', 'approved'])
                                  .values_list('source_key', flat=True)), ['chq:100:16118'])

    def test_seeded_rule_table(self):
        seed.seed_gl_drafting(user=self.user)
        got = {}
        for r in PostingRule.objects.all():
            lines = [(ln['side'], ln.get('account') or f"{ln['account_map']}:{ln['map_key']}",
                      ln['amount'], ln.get('branch', 'source'), ln.get('party', ''),
                      bool(ln.get('cheque'))) for ln in r.lines]
            got[r.code] = (r.source_type, r.granularity, r.book, r.action, r.conditions, lines)
        S, H, M = 'source', 'hq', 'map'
        bank = 'bank:bankcode'
        tfbank, ic = 'bank:tf_bankcode', 'intercompany:counterpart_branch'
        want = {
            'sales.cash': ('sales_tenders', 'branch_day', 'cash', 'post',
                           {'kind_in': ['cash'], 'branch_not_in': ['100']},
                           [('debit', '1302', 'net', S, '', False), ('credit', '6002', 'net', S, '', False)]),
            'sales.hq_store': ('sales_tenders', 'branch_day', 'cash', 'post',
                               {'kind_in': ['cash'], 'branch_in': ['100']},
                               [('debit', '1301', 'net', H, '', False), ('credit', '6011', 'net', H, '', False)]),
            'sales.card': ('sales_tenders', 'branch_day', 'cash', 'post', {'kind_in': ['card']},
                           [('debit', 'card_clearing:branch_code', 'net', M, '', False),
                            ('credit', '6006', 'net', S, '', False)]),
            'sales.change_discount': ('sales_tenders', 'branch_day', 'cash', 'post',
                                      {'kind_in': ['change_discount']},
                                      [('debit', '6022', 'net', S, '', False),
                                       ('credit', '6002', 'net', S, '', False)]),
            'sales.hq_change_discount': ('sales_tenders', 'branch_day', 'cash', 'post',
                                         {'kind_in': ['change_discount'], 'branch_in': ['100']},
                                         [('debit', '6022', 'net', H, '', False),
                                          ('credit', '6011', 'net', H, '', False)]),
            'sales.credit': ('credit_sales', 'party_day', 'credit', 'post', {},
                             [('debit', '1341', 'credit', H, 'source', False),
                              ('credit', '6003', 'credit', H, '', False),
                              ('debit', '6021', 'discount_share', H, '', False),
                              ('credit', '6003', 'discount_share', H, '', False)]),
            'purchases.hq': ('purchases', 'document', 'credit', 'post',
                             {'branch_in': ['100'], 'kind_in': ['invoice']},
                             [('debit', '5104', 'value', H, '', False),
                              ('credit', '2341', 'value', H, 'source', False)]),
            'purchases.hq_return': ('purchases', 'document', 'credit', 'post',
                                    {'branch_in': ['100'], 'kind_in': ['return']},
                                    [('debit', '2341', 'value', H, 'source', False),
                                     ('credit', '5105', 'value', H, '', False)]),
            'purchases.branch': ('purchases', 'document', 'credit', 'skip',
                                 {'branch_not_in': ['100']}, []),
            'supplier.cash': ('supplier_payments', 'branch_day', 'cash', 'post',
                              {'financialdoc_in': ['10'], 'direction_in': ['payment']},
                              [('debit', '5100', 'amount', M, '', False),
                               ('credit', '2341', 'amount', M, 'source', False),
                               ('debit', '2341', 'amount', M, 'source', False),
                               ('credit', bank, 'amount', M, '', False)]),
            'supplier.cheque': ('supplier_payments', 'document', 'credit', 'post',
                                {'financialdoc_in': ['20'], 'direction_in': ['payment']},
                                [('debit', '2341', 'amount', H, 'source', False),
                                 ('credit', '2343', 'amount', H, '', True)]),
            'cheque.maturity': ('cheque_maturity', 'document', 'general', 'post',
                                {'direction_in': ['payment']},
                                [('debit', '2343', 'amount', H, '', True),
                                 ('credit', bank, 'amount', M, '', False)]),
            'customer.collection': ('customer_collections', 'document', 'general', 'post',
                                    {'financialdoc_in': ['10', '20'], 'direction_in': ['receipt']},
                                    [('debit', bank, 'amount', M, '', False),
                                     ('credit', '1341', 'amount', H, 'source', False)]),
            'expenses.box': ('expenses', 'branch_day', 'cash', 'post', {},
                             [('debit', 'expense:expcode', 'amount', S, '', False),
                              ('credit', bank, 'amount', M, '', False)]),
            'treasury.transfer_in': ('treasury_other', 'document', 'general', 'post',
                                     {'kind_in': ['transfer'], 'direction_in': ['receipt']},
                                     [('debit', bank, 'amount', M, '', False),
                                      ('credit', '1320', 'amount', H, '', False)]),
            'treasury.transfer_out': ('treasury_other', 'document', 'general', 'post',
                                      {'kind_in': ['transfer'], 'direction_in': ['payment']},
                                      [('debit', '1320', 'amount', H, '', False),
                                       ('credit', bank, 'amount', M, '', False)]),
            # Ruling P24
            'treasury.branch_transfer_out': ('treasury_other', 'document', 'cash', 'post',
                                             {'kind_in': ['transfer_branch'], 'branch_not_in': ['100'],
                                              'direction_in': ['payment'], 'financialdoc_in': ['10']},
                                             [('debit', '2404', 'amount', S, '', False),
                                              ('credit', bank, 'amount', M, '', False)]),
            'treasury.branch_transfer_in': ('treasury_other', 'document', 'cash', 'post',
                                            {'kind_in': ['transfer_branch'], 'branch_not_in': ['100'],
                                             'direction_in': ['receipt'], 'financialdoc_in': ['10']},
                                            [('debit', bank, 'amount', M, '', False),
                                             ('credit', '2404', 'amount', S, '', False)]),
            'treasury.hq_transfer_out': ('treasury_other', 'document', 'cash', 'post',
                                         {'kind_in': ['transfer_branch'], 'branch_in': ['100'],
                                          'direction_in': ['payment'], 'financialdoc_in': ['10']},
                                         [('debit', ic, 'amount', H, '', False),
                                          ('credit', bank, 'amount', M, '', False)]),
            'treasury.hq_transfer_in': ('treasury_other', 'document', 'cash', 'post',
                                        {'kind_in': ['transfer_branch'], 'branch_in': ['100'],
                                         'direction_in': ['receipt'], 'financialdoc_in': ['10']},
                                        [('debit', bank, 'amount', M, '', False),
                                         ('credit', ic, 'amount', H, '', False)]),
            'treasury.box_bank_in': ('treasury_other', 'document', 'cash', 'post',
                                     {'kind_in': ['transfer_bank'], 'direction_in': ['receipt'],
                                      'financialdoc_in': ['10']},
                                     [('debit', bank, 'amount', M, '', False),
                                      ('credit', tfbank, 'amount', M, '', False)]),
            'treasury.box_bank_out': ('treasury_other', 'document', 'cash', 'post',
                                      {'kind_in': ['transfer_bank'], 'direction_in': ['payment'],
                                       'financialdoc_in': ['10']},
                                      [('debit', tfbank, 'amount', M, '', False),
                                       ('credit', bank, 'amount', M, '', False)]),
            'treasury.box_bank_mirror': ('treasury_other', 'document', 'cash', 'skip',
                                         {'kind_in': ['transfer_bank_mirror'], 'financialdoc_in': ['10']}, []),
        }
        self.assertEqual(got, want)
        for code in ('treasury.branch_transfer_out', 'treasury.branch_transfer_in', 'treasury.hq_transfer_out',
                     'treasury.hq_transfer_in', 'treasury.box_bank_in', 'treasury.box_bank_out',
                     'treasury.box_bank_mirror'):
            self.assertEqual(PostingRule.objects.get(code=code).priority, 120, code)
        self.assertEqual(PostingRule.objects.get(code='supplier.cash').lines[1]['description'],
                         'مشتريات نقدية {party} {note}')
        ics = {m.source_value: (m.account.code, m.branch.softech_branch_id)
               for m in GLSourceMap.objects.filter(kind='intercompany')}
        self.assertEqual(ics, {'130': ('2408', '100'), '140': ('2413', '100'), '150': ('2405', '100'),
                               '160': ('2406', '100'), '170': ('2417', '100')})
        hq = PostingRule.objects.get(code='sales.hq_change_discount')
        self.assertEqual(hq.priority, 110)
        self.assertEqual(hq.lines[0]['description'], 'خصم فكة المركز {date}')
        self.assertEqual(PostingRule.objects.get(code='sales.change_discount').priority, 100)

    def test_change_discount_credits_6011_at_hq_and_6002_at_branches(self):
        """Tender 60 «خصم فكة»: HQ cash sales sit on 6011, so the HQ rule (priority 110) wins there."""
        from decimal import Decimal
        from apps.finance.gl.sources import SourceDoc
        from apps.finance.models import LedgerEntry
        seed.seed_gl_drafting(user=self.user)
        day = D(2026, 3, 10)

        def t60(key, branch):
            return SourceDoc('sales_tenders', key, day, branch, 'change_discount', '',
                             {'net': Decimal('0.50'), 'sales': Decimal('0.50'), 'returns': Decimal('0')},
                             {'paymenttype': '60'})
        docs = [t60('hq60', '100'), t60('b60', '140')]
        run = drafting.start_run(triggered_by='t', date_from=day, date_to=day, source_types=['sales_tenders'])
        run = drafting.draft_range(day, day, source_types=['sales_tenders'], run=run, fetch=lambda sql: [],
                                   readers={'sales_tenders': lambda d1, d2, f: docs})
        self.assertEqual(run.status, 'success', run.detail)
        hq = Branch.objects.get(softech_branch_id='100')
        b140 = Branch.objects.get(softech_branch_id='140')

        def lines(key):
            e = LedgerEntry.objects.get(source_key=key)
            return e, [(ln.account.code, ln.debit, ln.credit, ln.branch_id)
                       for ln in e.lines.select_related('account').order_by('line_no')]
        e, got = lines('sales.hq_change_discount:100:2026-03-10')
        self.assertEqual(got, [('6022', Decimal('0.50'), 0, hq.pk), ('6011', 0, Decimal('0.50'), hq.pk)])
        self.assertEqual(e.description, 'خصم فكة المركز 2026-03-10')
        _, got = lines('sales.change_discount:140:2026-03-10')
        self.assertEqual(got, [('6022', Decimal('0.50'), 0, b140.pk), ('6002', 0, Decimal('0.50'), b140.pk)])

    def test_management_command(self):
        call_command('seed_gl_drafting', verbosity=0)
        self.assertTrue(PostingRule.objects.filter(code='sales.credit').exists())


class FreshnessTests(TestCase):
    def test_freshness_domain_reads_last_run(self):
        out = get_freshness(['gl_drafting'])['domains']['gl_drafting']
        self.assertIsNone(out['last_success_at'])
        now = timezone.now()
        GLDraftRun.objects.create(status='partial', date_from=D(2026, 3, 1), date_to=D(2026, 3, 2),
                                  finished_at=now)
        out = get_freshness(['gl_drafting'])['domains']['gl_drafting']
        self.assertIsNotNone(out['last_success_at'])
        self.assertFalse(out['last_run_failed'])
        GLDraftRun.objects.create(status='failed', date_from=D(2026, 3, 1), date_to=D(2026, 3, 2),
                                  finished_at=now)
        out = get_freshness(['gl_drafting'])['domains']['gl_drafting']
        self.assertTrue(out['last_run_failed'])
        self.assertIsNotNone(out['last_success_at'])


class SchedulerTests(TestCase):
    def test_registered_at_0830(self):
        from .test_scheduler_jobs import _FakeScheduler
        captured = {}

        class _Capture(_FakeScheduler):
            def add_job(self, func, trigger, *args, **kwargs):
                captured[kwargs.get('id')] = kwargs
                super().add_job(func, trigger, *args, **kwargs)

        with mock.patch.object(tasks, 'BackgroundScheduler', _Capture), \
             mock.patch.object(tasks, '_patch_apscheduler_for_python312', lambda: None), \
             mock.patch.object(tasks, '_scheduler', None):
            tasks.start_scheduler()
        job = captured['gl_drafting']
        self.assertEqual((job['hour'], job['minute']), (8, 30))
        self.assertEqual(job['max_instances'], 1)

    def test_scheduler_window_starts_at_earliest_open_month(self):
        today = D(2026, 11, 4)
        self.assertEqual(tasks._gl_drafting_window(today), (D(2026, 10, 1), D(2026, 11, 3)))
        # accepts_postings get-or-creates the month, so the row exists by now
        FinancialPeriod.objects.filter(year=2026, month=10, period_type='month').update(
            status='closed', is_closed=True)
        self.assertEqual(tasks._gl_drafting_window(today), (D(2026, 11, 1), D(2026, 11, 3)))

    @override_settings(GL_DRAFTING_SCHEDULE_ENABLED=False)
    def test_job_is_off_by_default_switch(self):
        """Ruling P22: scheduled drafting does nothing until the owner flips the switch."""
        from django.conf import settings as dj
        from apps.finance.gl import drafting as DRmod
        self.assertFalse(dj.GL_DRAFTING_SCHEDULE_ENABLED)
        with mock.patch.object(tasks, '_gl_drafting_window') as win, \
             mock.patch.object(DRmod, 'draft_range') as dr, \
             mock.patch.object(tasks, '_gl_drafting_off_logged', False):
            self.assertIsNone(tasks._run_gl_drafting())
            with self.assertLogs('elrezeiky.sync', 'INFO') as logs:
                tasks._gl_drafting_off_logged = False
                tasks._run_gl_drafting()
                tasks._run_gl_drafting()
        self.assertEqual(sum('scheduled drafting is off' in m for m in logs.output), 1)   # logged once
        win.assert_not_called()
        dr.assert_not_called()
        self.assertFalse(GLDraftRun.objects.exists())

    def test_settings_default_is_off(self):
        from django.conf import settings as dj
        src = open(dj.BASE_DIR / 'config' / 'settings.py', encoding='utf-8').read()
        self.assertIn("GL_DRAFTING_SCHEDULE_ENABLED = config('GL_DRAFTING_SCHEDULE_ENABLED', default=False, cast=bool)", src)

    @override_settings(GL_DRAFTING_SCHEDULE_ENABLED=True)
    def test_job_crash_marks_run_failed_with_finished_at_and_error(self):
        with mock.patch.object(tasks, '_gl_drafting_window', return_value=(D(2026, 10, 1), D(2026, 11, 3))), \
             mock.patch.object(drafting, 'draft_range', side_effect=RuntimeError('boom')):
            self.assertIsNone(tasks._run_gl_drafting())
        run = GLDraftRun.objects.get()
        self.assertEqual(run.status, 'failed')
        self.assertIsNotNone(run.finished_at)
        self.assertEqual(run.detail['error'], 'RuntimeError: boom')

    @override_settings(GL_DRAFTING_SCHEDULE_ENABLED=True)
    def test_job_uses_scheduler_trigger_and_survives_busy(self):
        with mock.patch.object(tasks, '_gl_drafting_window', return_value=(D(2026, 10, 1), D(2026, 11, 3))), \
             mock.patch.object(drafting, 'draft_range') as dr:
            tasks._run_gl_drafting()
        self.assertEqual(GLDraftRun.objects.get().triggered_by, 'scheduler')
        dr.assert_called_once()
        # the first run is still 'running' -> the second call hits DraftBusy and returns quietly
        with mock.patch.object(tasks, '_gl_drafting_window', return_value=(D(2026, 10, 1), D(2026, 11, 3))), \
             mock.patch.object(drafting, 'draft_range') as dr2:
            self.assertIsNone(tasks._run_gl_drafting())
        dr2.assert_not_called()


class RunEndpointTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('seed_permissions', verbosity=0)

    def setUp(self):
        _, _, self.acct = make_user('gs_acct', role='accountant')
        _, _, self.viewer = make_user('gs_viewer', role='viewer', access_all=True)
        _, _, self.pharm = make_user('gs_pharm', role='pharmacist')
        self.body = {'date_from': '2026-03-01', 'date_to': '2026-03-31'}

    def test_run_endpoint_202_then_409_while_running(self):
        with mock.patch('apps.finance.gl.drafting_views.start_thread') as st:
            r = self.acct.post(BASE + 'drafting/run/', self.body, format='json')
            self.assertEqual(r.status_code, 202, r.content)
            run = GLDraftRun.objects.get(pk=r.data['run_id'])
            self.assertEqual((run.status, run.date_from, run.date_to), ('running', D(2026, 3, 1), D(2026, 3, 31)))
            self.assertTrue(run.triggered_by.startswith('user:'))
            st.assert_called_once()
            r2 = self.acct.post(BASE + 'drafting/run/', self.body, format='json')
            self.assertEqual(r2.status_code, 409)
            self.assertEqual(st.call_count, 1)

    def test_run_endpoint_background_target_runs_the_engine(self):
        with mock.patch('apps.finance.gl.drafting_views.start_thread') as st:
            r = self.acct.post(BASE + 'drafting/run/', {**self.body, 'source_types': ['expenses']},
                               format='json')
        target, kw = st.call_args.args[0], st.call_args.kwargs
        with mock.patch.object(drafting, 'draft_range') as dr:
            target(*kw['args'])
        self.assertEqual(dr.call_args.kwargs['source_types'], ['expenses'])
        self.assertEqual(dr.call_args.kwargs['run'].pk, r.data['run_id'])

    def test_run_endpoint_validates_input(self):
        for body in ({}, {'date_from': 'x', 'date_to': '2026-01-01'},
                     {'date_from': '2026-03-05', 'date_to': '2026-03-01'},
                     {**self.body, 'source_types': ['nope']}):
            self.assertEqual(self.acct.post(BASE + 'drafting/run/', body, format='json').status_code, 400, body)
        self.assertFalse(GLDraftRun.objects.exists())

    def test_run_endpoint_needs_ledger_create(self):
        from apps.users.models import RoleModuleAccess
        from core.middleware import module_access
        # view-only: all-branch + ledger.view, no ledger.create
        RoleModuleAccess.objects.update_or_create(
            role='supervisor', module='ledger', action='view', defaults={'is_allowed': True})
        RoleModuleAccess.objects.update_or_create(
            role='supervisor', module='ledger', action='create', defaults={'is_allowed': False})
        # create but not all-branch: ledger.create granted, access_all_branches False
        for a in ('view', 'create'):
            RoleModuleAccess.objects.update_or_create(
                role='pharmacist', module='ledger', action=a, defaults={'is_allowed': True})
        module_access.clear_cache()
        _, _, view_only = make_user('gs_viewonly', role='supervisor', access_all=True)
        _, _, scoped = make_user('gs_scoped', role='pharmacist', access_all=False)
        with mock.patch('apps.finance.gl.drafting_views.start_thread') as st:
            self.assertEqual(view_only.get(BASE + 'drafting/runs/').status_code, 200)
            self.assertEqual(view_only.post(BASE + 'drafting/run/', self.body, format='json').status_code, 403)
            self.assertEqual(scoped.get(BASE + 'drafting/runs/').status_code, 403)
            self.assertEqual(scoped.post(BASE + 'drafting/run/', self.body, format='json').status_code, 403)
            self.assertEqual(self.viewer.post(BASE + 'drafting/run/', self.body, format='json').status_code, 403)
            st.assert_not_called()
        self.assertFalse(GLDraftRun.objects.exists())

    def test_draft_now_works_with_schedule_switch_off(self):
        with self.settings(GL_DRAFTING_SCHEDULE_ENABLED=False), \
             mock.patch('apps.finance.gl.drafting_views.start_thread') as st:
            r = self.acct.post(BASE + 'drafting/run/', self.body, format='json')
        self.assertEqual(r.status_code, 202, r.content)
        st.assert_called_once()

    def test_draft_now_before_opening_date_refused(self):
        r = self.acct.post(BASE + 'drafting/run/', {'date_from': '2025-12-31', 'date_to': '2026-01-05'},
                           format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('2026-01-01', r.data['detail'])
        self.assertFalse(GLDraftRun.objects.exists())

    def test_background_crash_sets_finished_at_and_error(self):
        from apps.finance.gl import drafting_views
        run = drafting.start_run(triggered_by='t', date_from=D(2026, 3, 1), date_to=D(2026, 3, 2), source_types=[])
        with mock.patch.object(drafting, 'draft_range', side_effect=ValueError('bad')):
            drafting_views._background(run.pk, D(2026, 3, 1), D(2026, 3, 2), None)
        run.refresh_from_db()
        self.assertEqual((run.status, run.detail['error']), ('failed', 'ValueError: bad'))
        self.assertIsNotNone(run.finished_at)

    def test_failed_thread_start_marks_run_failed(self):
        with mock.patch('apps.finance.gl.drafting_views.start_thread', side_effect=RuntimeError('x')):
            self.acct.raise_request_exception = False
            r = self.acct.post(BASE + 'drafting/run/', self.body, format='json')
        self.assertEqual(r.status_code, 500)
        self.assertEqual(GLDraftRun.objects.get().status, 'failed')

    def test_runs_list_and_detail(self):
        run = GLDraftRun.objects.create(status='success', date_from=D(2026, 3, 1), date_to=D(2026, 3, 2),
                                        counts={'drafted': 3})
        r = self.acct.get(BASE + 'drafting/runs/?limit=5')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['results'][0]['counts'], {'drafted': 3})
        self.assertEqual(self.acct.get(f'{BASE}drafting/runs/{run.pk}/').data['status'], 'success')
        self.assertEqual(self.acct.get(f'{BASE}drafting/runs/999999/').status_code, 404)
        self.assertEqual(self.pharm.get(BASE + 'drafting/runs/').status_code, 403)
