"""Plan 2 / Task 3: versioned posting rules, source maps, line building, preview."""
import datetime
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase

from apps.audit.models import AuditLog
from apps.branches.models import Branch
from apps.finance.gl import rules as R
from apps.finance.gl.sources import SourceDoc, content_hash
from apps.finance.models import (
    GLAccount, GLAccountGroup, GLParty, GLSourceMap, LedgerEntry, PostingRule,
)
from apps.users.models import StaffProfile

D = datetime.date(2026, 3, 10)
DEC = Decimal


def doc(key='k1', branch='130', amounts=None, personcode='', attrs=None, source_type='sales_tenders',
        date=D, kind=''):
    return SourceDoc(source_type=source_type, source_key=key, doc_date=date, branch_code=branch,
                     kind=kind, personcode=personcode, amounts=amounts or {}, attrs=attrs or {})


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        user = User.objects.create(username='fin')
        cls.staff, _ = StaffProfile.objects.get_or_create(user=user)
        g = GLAccountGroup.objects.create(name='g', section='balance_sheet')
        mk = lambda code, **kw: GLAccount.objects.create(  # noqa: E731
            code=code, name=code, group=g, nature=kw.pop('nature', 'debit'),
            account_type=kw.pop('account_type', 'asset'), **kw)
        cls.a1302 = mk('1302')
        cls.a6002 = mk('6002', nature='credit', account_type='revenue')
        cls.a6006 = mk('6006', nature='credit', account_type='revenue')
        cls.a1341 = mk('1341', party_type='customer', requires_party=True)
        cls.a2341 = mk('2341', nature='credit', account_type='liability', party_type='supplier')
        cls.a5100 = mk('5100', account_type='expense')
        cls.agrp = mk('1300', is_posting=False)
        cls.ainactive = mk('9999', is_active=False)
        cls.b130 = Branch.objects.create(softech_branch_id='130', name='b130')
        cls.b100 = Branch.objects.create(softech_branch_id='100', name='hq')
        cls.b140 = Branch.objects.create(softech_branch_id='140', name='b140')

    def rule(self, lines, conditions=None, action='post', source_type='sales_tenders',
             granularity='document', priority=100, code='r1', eff=datetime.date(2026, 1, 1)):
        return R.save_rule(user=self.staff, code=code, source_type=source_type, effective_from=eff,
                           conditions=conditions or {}, lines=lines, action=action,
                           granularity=granularity, priority=priority)


CASH = [
    {'side': 'debit', 'account': '1302', 'amount': 'net', 'branch': 'source'},
    {'side': 'credit', 'account': '6002', 'amount': 'net', 'branch': 'source'},
]


class ValidationTests(Base):
    def test_unknown_field_or_condition_rejected(self):
        self.assertTrue(R.validate_rule('sales_tenders', {}, [
            {'side': 'debit', 'account': '1302', 'amount': 'bogus'},
            {'side': 'credit', 'account': '6002', 'amount': 'net'}], 'post'))
        self.assertTrue(R.validate_rule('sales_tenders', {'expcode_in': ['1']}, CASH, 'post'))
        self.assertTrue(R.validate_rule('sales_tenders', {'nope': ['1']}, CASH, 'post'))
        self.assertTrue(R.validate_rule('nope', {}, CASH, 'post'))
        bad = [dict(CASH[0], description='{evil}'), CASH[1]]
        self.assertTrue(R.validate_rule('sales_tenders', {}, bad, 'post'))
        self.assertEqual(R.validate_rule('sales_tenders', {'branch_in': ['130']}, CASH, 'post'), [])

    def test_account_checks_and_sides(self):
        for code in ('0000', '9999', '1300'):   # missing, inactive, non-posting
            lines = [dict(CASH[0], account=code), CASH[1]]
            self.assertTrue(R.validate_rule('sales_tenders', {}, lines, 'post'), code)
        self.assertTrue(R.validate_rule('sales_tenders', {}, [CASH[0]], 'post'))

    def test_skip_rule_with_lines_rejected(self):
        self.assertTrue(R.validate_rule('sales_tenders', {}, CASH, 'skip'))
        self.assertEqual(R.validate_rule('sales_tenders', {}, [], 'skip'), [])
        with self.assertRaises(R.RuleError):
            self.rule(CASH, action='skip')


class VersionTests(Base):
    def test_edit_creates_new_version_and_closes_old(self):
        v1 = self.rule(CASH)
        v2 = self.rule(CASH, eff=datetime.date(2026, 3, 1))
        v1.refresh_from_db()
        self.assertEqual((v1.version, v2.version), (1, 2))
        self.assertEqual(v1.effective_to, datetime.date(2026, 2, 28))
        self.assertIsNone(v2.effective_to)
        self.assertTrue(AuditLog.objects.filter(action='gl_rule_saved').count() == 2)
        with self.assertRaises(R.RuleError):
            self.rule(CASH, eff=datetime.date(2026, 3, 1))

    def test_select_rule_by_date_uses_old_version_before_change(self):
        v1 = self.rule(CASH)
        v2 = self.rule(CASH, eff=datetime.date(2026, 3, 1))
        rules = PostingRule.objects.all()
        self.assertEqual(R.select_rule(doc(date=datetime.date(2026, 2, 28)), rules), v1)
        self.assertEqual(R.select_rule(doc(date=datetime.date(2026, 3, 1)), rules), v2)

    def test_no_rule_and_condition_filtering(self):
        self.rule(CASH, conditions={'branch_in': ['130']})
        with self.assertRaises(R.RuleMiss) as cm:
            R.select_rule(doc(branch='140'), PostingRule.objects.all())
        self.assertEqual(cm.exception.kind, 'no_rule')
        self.rule(CASH, conditions={'branch_not_in': ['130']}, code='r2')
        self.assertEqual(R.select_rule(doc(branch='140'), PostingRule.objects.all()).code, 'r2')

    def test_priority_wins_equal_priority_tie_is_ambiguous(self):
        self.rule(CASH, code='a', priority=100)
        self.rule(CASH, code='b', priority=200)
        self.assertEqual(R.select_rule(doc(), PostingRule.objects.all()).code, 'b')
        self.rule(CASH, code='c', priority=200)
        with self.assertRaises(R.RuleMiss) as cm:
            R.select_rule(doc(), PostingRule.objects.all())
        self.assertEqual(cm.exception.kind, 'ambiguous_rule')


class BuildTests(Base):
    def build(self, rule, docs):
        return R.build_lines(rule, docs, hq_branch_id=self.b100.pk)

    def test_negative_amount_moves_side_and_zero_dropped(self):
        rule = self.rule([
            {'side': 'debit', 'account': '1302', 'amount': 'sales'},
            {'side': 'credit', 'account': '6002', 'amount': 'sales'},
            {'side': 'credit', 'account': '6006', 'amount': 'returns'},   # zero -> dropped
            {'side': 'debit', 'account': '5100', 'amount': 'net'},
            {'side': 'credit', 'account': '6006', 'amount': 'net'},
        ])
        lines = self.build(rule, [doc(amounts={'sales': DEC('100.00'), 'returns': DEC('0'),
                                               'net': DEC('-30.00')})])
        by = {(l['account_code']): l for l in lines}
        self.assertNotIn('6006_zero', by)
        self.assertEqual(by['5100']['credit'], DEC('30.00'))   # debit moved to credit
        self.assertEqual(by['5100']['debit'], DEC('0'))
        self.assertEqual(by['6006']['debit'], DEC('30.00'))
        self.assertEqual(sum(l['debit'] for l in lines), sum(l['credit'] for l in lines))
        self.assertEqual(len(lines), 4)

    def test_group_lines_summed_per_account_branch_party(self):
        rule = self.rule(CASH)
        lines = self.build(rule, [doc('a', amounts={'net': DEC('10.10')}),
                                  doc('b', amounts={'net': DEC('5.15')}),
                                  doc('c', branch='140', amounts={'net': DEC('2')})])
        got = {(l['account_code'], l['branch_id']): (l['debit'], l['credit']) for l in lines}
        self.assertEqual(got[('1302', self.b130.pk)], (DEC('15.25'), DEC('0')))
        self.assertEqual(got[('6002', self.b130.pk)], (DEC('0'), DEC('15.25')))
        self.assertEqual(got[('1302', self.b140.pk)], (DEC('2.00'), DEC('0')))
        self.assertEqual(len(lines), 4)
        self.assertEqual(set(lines[0]), {'account_code', 'debit', 'credit', 'branch_id', 'party_code',
                                         'description', 'cheque_no', 'due_date'})

    def test_unbalanced_rule_raises(self):
        rule = self.rule([
            {'side': 'debit', 'account': '1302', 'amount': 'sales'},
            {'side': 'credit', 'account': '6002', 'amount': 'returns'},
        ])
        with self.assertRaises(R.RuleMiss) as cm:
            self.build(rule, [doc(amounts={'sales': DEC('10'), 'returns': DEC('9')})])
        self.assertEqual(cm.exception.kind, 'unbalanced_rule')

    def test_unmapped_box_raises_unmapped_account(self):
        rule = self.rule([
            {'side': 'debit', 'account_map': 'bank', 'map_key': 'bankcode', 'amount': 'amount'},
            {'side': 'credit', 'account': '6002', 'amount': 'amount'},
        ], source_type='customer_collections')
        d = doc(source_type='customer_collections', amounts={'amount': DEC('5')}, attrs={'bankcode': '40'})
        with self.assertRaises(R.RuleMiss) as cm:
            self.build(rule, [d])
        self.assertEqual(cm.exception.kind, 'unmapped_account')
        self.assertEqual(cm.exception.detail['key'], '40')
        R.save_map(user=self.staff, kind='bank', source_value='40', account_code='1302',
                   branch_id=self.b140.pk)
        lines = self.build(rule, [d])
        by = {l['account_code']: l for l in lines}
        self.assertEqual(by['1302']['branch_id'], self.b130.pk)   # 'source' default -> doc branch

    def test_branch_modes_hq_map_none_and_unknown_branch(self):
        R.save_map(user=self.staff, kind='bank', source_value='40', account_code='1302',
                   branch_id=self.b140.pk)
        rule = self.rule([
            {'side': 'debit', 'account_map': 'bank', 'map_key': 'bankcode', 'amount': 'amount',
             'branch': 'map'},
            {'side': 'credit', 'account': '6002', 'amount': 'amount', 'branch': 'hq'},
            {'side': 'debit', 'account': '5100', 'amount': 'amount', 'branch': 'none'},
            {'side': 'credit', 'account': '6006', 'amount': 'amount', 'branch': 'source'},
        ], source_type='expenses')
        d = doc(source_type='expenses', amounts={'amount': DEC('4')}, attrs={'bankcode': '40'})
        by = {l['account_code']: l for l in self.build(rule, [d])}
        self.assertEqual(by['1302']['branch_id'], self.b140.pk)
        self.assertEqual(by['6002']['branch_id'], self.b100.pk)
        self.assertIsNone(by['5100']['branch_id'])
        self.assertEqual(by['6006']['branch_id'], self.b130.pk)
        with self.assertRaises(R.RuleMiss) as cm:
            self.build(rule, [doc(source_type='expenses', branch='999', amounts={'amount': DEC('4')},
                                  attrs={'bankcode': '40'})])
        self.assertEqual(cm.exception.kind, 'unmapped_account')
        self.assertEqual(cm.exception.detail['branch_code'], '999')

    def test_party_line_needs_confirmed_party(self):
        rule = self.rule([
            {'side': 'debit', 'account': '1341', 'amount': 'credit', 'party': 'source'},
            {'side': 'credit', 'account': '6002', 'amount': 'credit'},
        ], source_type='credit_sales')
        mk = lambda k, pc, amt: doc(k, source_type='credit_sales', personcode=pc,  # noqa: E731
                                    amounts={'credit': DEC(amt)})
        with self.assertRaises(R.RuleMiss) as cm:
            self.build(rule, [mk('a', '77', '10')])
        self.assertEqual((cm.exception.kind, cm.exception.detail['personcode']), ('unmapped_party', '77'))
        p = GLParty.objects.create(party_type='customer', code='C1', name='n',
                                   softech_personcode='77', status='proposed')
        with self.assertRaises(R.RuleMiss):          # a proposal never resolves
            self.build(rule, [mk('a', '77', '10')])
        p.status = 'confirmed'
        p.save()
        GLParty.objects.create(party_type='customer', code='C2', name='m',
                               softech_personcode='78', status='confirmed')
        lines = self.build(rule, [mk('a', '77', '10'), mk('b', '78', '4'), mk('c', '77', '1')])
        parties = {l['party_code']: l['debit'] for l in lines if l['account_code'] == '1341'}
        self.assertEqual(parties, {'C1': DEC('11.00'), 'C2': DEC('4.00')})

    def test_cheque_fields_and_description_placeholders(self):
        rule = self.rule([
            {'side': 'debit', 'account': '1302', 'amount': 'amount', 'cheque': True,
             'description': 'شيك {cheqno} فرع {branch} {date}'},
            {'side': 'credit', 'account': '6002', 'amount': 'amount'},
        ], source_type='cheque_maturity')
        d = doc(source_type='cheque_maturity', amounts={'amount': DEC('9')},
                attrs={'cheqno': '555', 'due_date': '2026-04-01'})
        l = self.build(rule, [d])[0]
        self.assertEqual((l['cheque_no'], l['due_date']), ('555', datetime.date(2026, 4, 1)))
        self.assertEqual(l['description'], 'شيك 555 فرع 130 2026-03-10')


class PreviewAndMapTests(Base):
    def test_preview_saves_nothing(self):
        rule = self.rule(CASH, granularity='branch_day')
        before = (LedgerEntry.objects.count(), PostingRule.objects.count())
        reader = lambda d1, d2, fetch: [  # noqa: E731
            doc('a', amounts={'net': DEC('10')}), doc('b', amounts={'net': DEC('5')}),
            doc('x', branch='999', amounts={'net': DEC('1')}),
            doc('s', branch='130', amounts={'net': DEC('1')}, source_type='sales_tenders',
                date=datetime.date(2025, 1, 1))]
        out = R.preview_rule(rule, D, D, readers={'sales_tenders': reader})
        self.assertEqual((LedgerEntry.objects.count(), PostingRule.objects.count()), before)
        self.assertEqual(out['totals']['entries'], 1)
        self.assertEqual(out['totals']['debit'], DEC('15.00'))
        self.assertEqual(out['totals']['debit'], out['totals']['credit'])
        self.assertEqual([e['kind'] for e in out['exceptions']], ['unmapped_account'])
        self.assertEqual(out['exceptions'][0]['source_key'], 'x')
        self.assertEqual(sorted(out['entries'][0]['source_keys']), ['a', 'b'])

    def test_preview_accepts_unsaved_draft_dict(self):
        draft = {'source_type': 'sales_tenders', 'conditions': {}, 'lines': CASH, 'action': 'post'}
        reader = lambda d1, d2, fetch: [doc('a', amounts={'net': DEC('3')})]  # noqa: E731
        out = R.preview_rule(draft, D, D, readers={'sales_tenders': reader})
        self.assertEqual(out['totals']['entries'], 1)
        self.assertEqual(PostingRule.objects.count(), 0)
        with self.assertRaises(R.RuleError):
            R.preview_rule(dict(draft, lines=[]), D, D, readers={'sales_tenders': reader})

    def test_save_map_audited_before_after(self):
        m = R.save_map(user=self.staff, kind='bank', source_value='40', account_code='1302', note='x')
        m2 = R.save_map(user=self.staff, kind='bank', source_value='40', account_code='6002')
        self.assertEqual(m.pk, m2.pk)
        self.assertEqual(GLSourceMap.objects.count(), 1)
        rows = list(AuditLog.objects.filter(action='gl_map_saved').order_by('id'))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1].old_data['account'], '1302')
        self.assertEqual(rows[1].new_data['account'], '6002')
        for bad in ({'kind': 'zzz', 'account_code': '1302'}, {'kind': 'bank', 'account_code': '1300'},
                    {'kind': 'bank', 'account_code': '0000'}):
            with self.assertRaises(R.RuleError):
                R.save_map(user=self.staff, source_value='1', **bad)


class ContentHashTests(SimpleTestCase):
    def test_hash_ignores_key_and_dict_order(self):
        a = doc('k1', amounts={'a': DEC('1.00'), 'b': DEC('2')}, attrs={'x': 1, 'y': 2})
        b = doc('k2', amounts={'b': DEC('2'), 'a': DEC('1.00')}, attrs={'y': 2, 'x': 1})
        self.assertEqual(content_hash(a), content_hash(b))
        self.assertNotEqual(content_hash(a), content_hash(doc('k1', amounts={'a': DEC('1.01'), 'b': DEC('2')},
                                                                attrs={'x': 1, 'y': 2})))
        self.assertEqual(len(content_hash(a)), 64)
