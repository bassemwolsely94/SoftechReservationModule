"""Plan 2 / Task 6: drafting engine — idempotent drafts, exceptions, late changes."""
import datetime
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from apps.branches.models import Branch
from apps.finance.gl import drafting as DR
from apps.finance.gl import rules as R
from apps.finance.gl.ledger import approve
from apps.finance.gl.sources import SourceDoc
from apps.finance.models import (
    FinancialPeriod, GLAccount, GLAccountGroup, GLDraftRun, GLParty, GLSourceDoc, LedgerEntry,
    SourceException,
)
from apps.users.models import StaffProfile

DEC = Decimal
D1 = datetime.date(2026, 3, 1)
D2 = datetime.date(2026, 3, 31)
MAR10 = datetime.date(2026, 3, 10)

CASH = [
    {'side': 'debit', 'account': '1302', 'amount': 'net', 'branch': 'source', 'description': 'نقدية {branch} {date}'},
    {'side': 'credit', 'account': '6002', 'amount': 'net', 'branch': 'source'},
]
CREDIT = [
    {'side': 'debit', 'account': '1341', 'amount': 'credit', 'branch': 'hq', 'party': 'source',
     'description': 'آجل {docnumber}'},
    {'side': 'credit', 'account': '6003', 'amount': 'credit', 'branch': 'hq'},
]


def tender(key, amount, date=MAR10, branch='130', pt='30'):
    return SourceDoc('sales_tenders', key, date, branch, 'cash', '',
                     {'net': DEC(amount), 'sales': DEC(amount), 'returns': DEC('0')},
                     {'paymenttype': pt})


def credit(key, amount, personcode, date=MAR10):
    return SourceDoc('credit_sales', key, date, '130', '', personcode,
                     {'credit': DEC(amount), 'gross_share': DEC(amount), 'discount_share': DEC('0'),
                      'tax_share': DEC('0')}, {'doccode': '115', 'docnumber': key})


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        user = User.objects.create(username='fin-dr')
        cls.staff, _ = StaffProfile.objects.get_or_create(user=user)
        g = GLAccountGroup.objects.create(name='g', section='balance_sheet')
        mk = lambda code, **kw: GLAccount.objects.create(  # noqa: E731
            code=code, name=code, group=g, nature=kw.pop('nature', 'debit'),
            account_type=kw.pop('account_type', 'asset'), **kw)
        mk('1302')
        mk('6002', nature='credit', account_type='revenue')
        mk('6006', nature='credit', account_type='revenue')
        mk('6003', nature='credit', account_type='revenue')
        mk('1341', party_type='customer', requires_party=True)
        cls.b130 = Branch.objects.create(softech_branch_id='130', name='b130')
        cls.b100 = Branch.objects.create(softech_branch_id='100', name='hq')
        cls.p1 = GLParty.objects.create(party_type='customer', code='C1', name='c1',
                                        softech_personcode='501', status='confirmed')
        cls.p2 = GLParty.objects.create(party_type='customer', code='C2', name='c2',
                                        softech_personcode='502', status='proposed')

    def setUp(self):
        self.docs = {'sales_tenders': [], 'credit_sales': []}
        self.fail_types = set()

    def reader(self, t):
        def read(d1, d2, fetch):
            if t in self.fail_types:
                raise RuntimeError('SOFTECH down')
            return [d for d in self.docs[t] if d1 <= d.doc_date <= d2]
        return read

    def run_engine(self, types=None):
        types = types or ['sales_tenders']
        run = DR.start_run(triggered_by='test', date_from=D1, date_to=D2, source_types=types)
        readers = {t: self.reader(t) for t in self.docs}
        return DR.draft_range(D1, D2, source_types=types, run=run, fetch=lambda sql: [],
                              readers=readers)

    def rule(self, code='cash', lines=CASH, source_type='sales_tenders', granularity='document',
             action='post', eff=datetime.date(2026, 1, 1), priority=100, conditions=None):
        return R.save_rule(user=self.staff, code=code, source_type=source_type, effective_from=eff,
                           conditions=conditions or {}, lines=lines if action == 'post' else [],
                           action=action, granularity=granularity, priority=priority)

    def live(self, key):
        return LedgerEntry.objects.filter(source_key=key, status__in=['draft', 'approved'])

    def amounts(self, entry):
        return [(ln.account.code, ln.debit, ln.credit)
                for ln in entry.lines.select_related('account').order_by('line_no')]

    def close_month(self, d, status='closed'):
        p, _ = FinancialPeriod.objects.get_or_create(
            year=d.year, month=d.month, period_type='month',
            defaults={'period_start': d.replace(day=1), 'period_end': d.replace(day=28)})
        p.status = status
        p.save()


class SystemTests(Base):
    def test_system_user_is_gl_drafting(self):
        self.assertEqual(DR.system_user().user.username, 'gl-drafting')

    def test_accepts_postings_fallback(self):
        self.assertTrue(DR.accepts_postings(MAR10))
        self.close_month(MAR10, 'closing')
        self.assertFalse(DR.accepts_postings(MAR10))
        self.close_month(MAR10, 'open')
        self.assertTrue(DR.accepts_postings(MAR10))


class DraftingTests(Base):
    def test_first_run_drafts_second_run_changes_nothing(self):
        self.rule()
        self.docs['sales_tenders'] = [tender('t1', '100.00'), tender('t2', '50.00', branch='130', pt='40')]
        run = self.run_engine()
        self.assertEqual(run.status, 'success')
        self.assertEqual(run.counts['new'], 2)
        self.assertEqual(run.counts['created'], 2)
        e1 = self.live('t1').get()
        self.assertEqual(e1.status, 'draft')
        self.assertEqual(e1.created_by, DR.system_user())
        self.assertEqual(e1.source_type, 'sales_tenders')
        self.assertEqual(e1.description, 'نقدية 130 2026-03-10')
        self.assertEqual(self.amounts(e1), [('1302', DEC('100.00'), 0), ('6002', 0, DEC('100.00'))])
        ids = sorted(LedgerEntry.objects.values_list('id', flat=True))
        sd = GLSourceDoc.objects.get(source_key='t1')
        self.assertEqual((sd.status, sd.entry_id, sd.version), ('drafted', e1.id, 1))

        run2 = self.run_engine()
        self.assertEqual(run2.counts['unchanged'], 2)
        for k in ('new', 'changed', 'created', 'replaced', 'reversed', 'deleted', 'exceptions'):
            self.assertEqual(run2.counts[k], 0, k)
        self.assertEqual(sorted(LedgerEntry.objects.values_list('id', flat=True)), ids)
        self.assertEqual(self.amounts(self.live('t1').get()), self.amounts(e1))

    def test_branch_day_groups_tenders_into_one_entry(self):
        self.rule(granularity='branch_day')
        self.docs['sales_tenders'] = [tender('t1', '100.00'), tender('t2', '50.00', pt='40'),
                                      tender('t3', '7.00', branch='100')]
        self.run_engine()
        e = self.live('cash:130:2026-03-10').get()
        self.assertEqual(self.amounts(e), [('1302', DEC('150.00'), 0), ('6002', 0, DEC('150.00'))])
        self.assertEqual(e.branch, self.b130)
        self.assertEqual(GLSourceDoc.objects.filter(entry=e).count(), 2)
        self.assertTrue(self.live('cash:100:2026-03-10').exists())

    def test_changed_doc_replaces_draft_lines(self):
        self.rule(granularity='branch_day')
        self.docs['sales_tenders'] = [tender('t1', '100.00'), tender('t2', '50.00', pt='40')]
        self.run_engine()
        e = self.live('cash:130:2026-03-10').get()
        self.docs['sales_tenders'][0] = tender('t1', '120.00')
        run = self.run_engine()
        self.assertEqual(run.counts['changed'], 1)
        self.assertEqual(run.counts['replaced'], 1)
        e2 = self.live('cash:130:2026-03-10').get()
        self.assertEqual(e2.id, e.id)
        self.assertEqual(self.amounts(e2), [('1302', DEC('170.00'), 0), ('6002', 0, DEC('170.00'))])
        self.assertEqual(GLSourceDoc.objects.get(source_key='t1').version, 2)

    def test_changed_doc_after_approval_reverses_and_redrafts(self):
        self.rule()
        self.docs['sales_tenders'] = [tender('t1', '100.00')]
        self.run_engine()
        original = self.live('t1').get()
        approve(original.id, user=self.staff)
        self.docs['sales_tenders'] = [tender('t1', '90.00')]
        run = self.run_engine()
        self.assertEqual(run.counts['reversed'], 1)
        original.refresh_from_db()
        self.assertEqual(original.status, 'reversed')
        self.assertEqual(LedgerEntry.objects.filter(reverses=original).count(), 1)
        new = self.live('t1').get()
        self.assertEqual(new.status, 'draft')
        self.assertEqual(self.amounts(new), [('1302', DEC('90.00'), 0), ('6002', 0, DEC('90.00'))])
        self.assertEqual(GLSourceDoc.objects.get(source_key='t1').entry_id, new.id)
        n = LedgerEntry.objects.count()
        run2 = self.run_engine()
        self.assertEqual((run2.counts['reversed'], run2.counts['created'], run2.counts['replaced']), (0, 0, 0))
        self.assertEqual(LedgerEntry.objects.count(), n)

    def test_changed_doc_in_closed_period_raises_exception_only(self):
        self.rule()
        self.docs['sales_tenders'] = [tender('t1', '100.00')]
        self.run_engine()
        original = self.live('t1').get()
        approve(original.id, user=self.staff)
        self.close_month(MAR10)
        self.docs['sales_tenders'] = [tender('t1', '90.00')]
        n = LedgerEntry.objects.count()
        self.run_engine()
        original.refresh_from_db()
        self.assertEqual(original.status, 'approved')
        self.assertEqual(LedgerEntry.objects.count(), n)
        ex = SourceException.objects.get(source_doc__source_key='t1', status='open')
        self.assertEqual(ex.kind, 'closed_period_change')
        self.assertEqual(ex.original_entry, original)
        self.assertEqual(ex.proposed_lines[0]['debit'], '90.00')
        self.run_engine()   # re-run: nothing more
        self.assertEqual(LedgerEntry.objects.count(), n)
        self.assertEqual(SourceException.objects.filter(source_doc__source_key='t1').count(), 1)
        # month reopened → the retry reverses and redrafts
        self.close_month(MAR10, 'open')
        run = self.run_engine()
        self.assertEqual(run.counts['reversed'], 1)
        self.assertEqual(self.amounts(self.live('t1').get())[0][1], DEC('90.00'))
        ex.refresh_from_db()
        self.assertEqual(ex.status, 'resolved')

    def test_new_doc_in_closed_period_is_exception(self):
        self.rule()
        self.close_month(MAR10)
        self.docs['sales_tenders'] = [tender('t1', '100.00')]
        self.run_engine()
        self.assertFalse(LedgerEntry.objects.exists())
        ex = SourceException.objects.get(source_doc__source_key='t1')
        self.assertEqual((ex.kind, ex.original_entry), ('closed_period_change', None))

    def test_vanished_doc_reverses_approved_entry(self):
        self.rule()
        self.docs['sales_tenders'] = [tender('t1', '100.00'), tender('t2', '5.00')]
        self.run_engine()
        e1 = self.live('t1').get()
        approve(e1.id, user=self.staff)
        e2 = self.live('t2').get()   # stays draft
        self.docs['sales_tenders'] = []
        run = self.run_engine()
        self.assertEqual(run.counts['vanished'], 2)
        self.assertEqual((run.counts['reversed'], run.counts['deleted']), (1, 1))
        e1.refresh_from_db()
        self.assertEqual(e1.status, 'reversed')
        self.assertFalse(LedgerEntry.objects.filter(pk=e2.pk).exists())
        sd = GLSourceDoc.objects.get(source_key='t1')
        self.assertEqual((sd.status, sd.entry_id), ('vanished', None))
        run2 = self.run_engine()
        self.assertEqual((run2.counts['vanished'], run2.counts['reversed']), (0, 0))

    def test_vanished_doc_in_closed_period_is_exception(self):
        self.rule()
        self.docs['sales_tenders'] = [tender('t1', '100.00')]
        self.run_engine()
        e1 = self.live('t1').get()
        approve(e1.id, user=self.staff)
        self.close_month(MAR10)
        self.docs['sales_tenders'] = []
        self.run_engine()
        self.run_engine()
        e1.refresh_from_db()
        self.assertEqual(e1.status, 'approved')
        ex = SourceException.objects.get(source_doc__source_key='t1')
        self.assertEqual((ex.kind, ex.original_entry_id, ex.status), ('closed_period_change', e1.id, 'open'))

    def test_unmapped_party_blocks_only_that_doc(self):
        self.rule(code='cr', lines=CREDIT, source_type='credit_sales', granularity='branch_day')
        self.docs['credit_sales'] = [credit('c1', '10.00', '501'), credit('c2', '20.00', '502')]
        self.run_engine(['credit_sales'])
        e = self.live('cr:130:2026-03-10').get()
        self.assertEqual(self.amounts(e), [('1341', DEC('10.00'), 0), ('6003', 0, DEC('10.00'))])
        self.assertEqual(e.lines.first().branch, self.b100)
        self.assertEqual(GLSourceDoc.objects.get(source_key='c1').status, 'drafted')
        sd2 = GLSourceDoc.objects.get(source_key='c2')
        self.assertEqual(sd2.status, 'exception')
        self.assertEqual(sd2.exceptions.get().kind, 'unmapped_party')

    def test_exception_auto_resolves_after_party_confirmed(self):
        self.rule(code='cr', lines=CREDIT, source_type='credit_sales', granularity='branch_day')
        self.docs['credit_sales'] = [credit('c1', '10.00', '501'), credit('c2', '20.00', '502')]
        self.run_engine(['credit_sales'])
        self.run_engine(['credit_sales'])   # still unconfirmed: one open exception, not two
        self.assertEqual(SourceException.objects.filter(source_doc__source_key='c2').count(), 1)
        GLParty.objects.filter(pk=self.p2.pk).update(status='confirmed')
        self.run_engine(['credit_sales'])
        e = self.live('cr:130:2026-03-10').get()
        self.assertEqual([a[1] for a in self.amounts(e) if a[1]], [DEC('10.00'), DEC('20.00')])
        sd2 = GLSourceDoc.objects.get(source_key='c2')
        self.assertEqual((sd2.status, sd2.entry_id), ('drafted', e.id))
        ex = sd2.exceptions.get()
        self.assertEqual(ex.status, 'resolved')
        self.assertEqual(ex.resolution_note, 'حُلّ تلقائياً عند إعادة الترحيل')

    def test_ambiguous_and_unbalanced_rules_become_exceptions(self):
        self.rule(code='a', conditions={'paymenttype_in': ['30']})
        self.rule(code='b', conditions={'paymenttype_in': ['30']})
        self.rule(code='u', conditions={'paymenttype_in': ['40']}, lines=[
            CASH[0], {'side': 'credit', 'account': '6002', 'amount': 'sales', 'branch': 'source'}])
        self.docs['sales_tenders'] = [tender('t1', '10.00'),
                                      SourceDoc('sales_tenders', 't2', MAR10, '130', 'card', '',
                                                {'net': DEC('10'), 'sales': DEC('12'), 'returns': DEC('2')},
                                                {'paymenttype': '40'})]
        run = self.run_engine()
        self.assertFalse(LedgerEntry.objects.exists())
        self.assertEqual(run.counts['exceptions'], 2)
        self.assertEqual(SourceException.objects.get(source_doc__source_key='t1').kind, 'ambiguous_rule')
        self.assertEqual(SourceException.objects.get(source_doc__source_key='t2').kind, 'unbalanced_rule')

    def test_rule_edit_redrafts_only_from_effective_from(self):
        v1 = self.rule()
        early = tender('t1', '10.00', date=datetime.date(2026, 3, 5))
        late = tender('t2', '20.00', date=datetime.date(2026, 3, 20))
        self.docs['sales_tenders'] = [early, late]
        self.run_engine()
        e_early = self.live('t1').get()
        early_before = (e_early.id, self.amounts(e_early))
        R.save_rule(user=self.staff, code='cash', source_type='sales_tenders',
                    effective_from=datetime.date(2026, 3, 15), conditions={},
                    lines=[CASH[0], dict(CASH[1], account='6006')])
        run = self.run_engine()
        self.assertEqual(run.counts['replaced'], 1)
        e_early = self.live('t1').get()
        self.assertEqual((e_early.id, self.amounts(e_early)), early_before)
        self.assertEqual(self.amounts(self.live('t2').get())[1][0], '6006')
        v1.refresh_from_db()
        self.assertEqual(v1.effective_to, datetime.date(2026, 3, 14))
        self.assertEqual(GLSourceDoc.objects.get(source_key='t1').rule_id, v1.id)

    def test_skip_rule_marks_doc_skipped_no_entry(self):
        self.rule(action='skip')
        self.docs['sales_tenders'] = [tender('t1', '10.00')]
        run = self.run_engine()
        self.assertEqual(run.counts['skipped'], 1)
        self.assertEqual(GLSourceDoc.objects.get(source_key='t1').status, 'skipped')
        self.assertFalse(LedgerEntry.objects.exists())

    def test_zero_group_is_skipped(self):
        self.rule(granularity='branch_day')
        self.docs['sales_tenders'] = [tender('t1', '10.00'), tender('t2', '-10.00', pt='40')]
        run = self.run_engine()
        self.assertFalse(LedgerEntry.objects.exists())
        self.assertEqual(set(GLSourceDoc.objects.values_list('status', flat=True)), {'skipped'})
        self.assertIn('cash:130:2026-03-10', run.detail['zero_groups'])

    def test_missing_hq_branch_is_unmapped_account(self):
        Branch.objects.filter(pk=self.b100.pk).update(softech_branch_id='999')
        self.rule(code='cr', lines=CREDIT, source_type='credit_sales')
        self.docs['credit_sales'] = [credit('c1', '10.00', '501')]
        self.run_engine(['credit_sales'])
        ex = SourceException.objects.get(source_doc__source_key='c1')
        self.assertEqual((ex.kind, ex.detail), ('unmapped_account', {'branch_code': '100'}))
        self.assertFalse(LedgerEntry.objects.exists())

    def test_duplicate_marker_becomes_exception(self):
        self.rule()
        self.docs['sales_tenders'] = [SourceDoc('sales_tenders', 'dup1', MAR10, '130', '__duplicate__', '', {}, {})]
        self.run_engine()
        self.assertEqual(SourceException.objects.get(source_doc__source_key='dup1').kind, 'duplicate_source_key')
        self.assertFalse(LedgerEntry.objects.exists())

    def test_ledger_error_becomes_exception(self):
        self.rule()
        self.docs['sales_tenders'] = [tender('t1', '10000000000000000.00'), tender('t2', '1.00')]
        run = self.run_engine()   # save_draft refuses an amount over the column size
        ex = SourceException.objects.get(source_doc__source_key='t1')
        self.assertEqual((ex.kind, ex.detail['code']), ('ledger_error', 'bad_amount'))
        self.assertEqual(GLSourceDoc.objects.get(source_key='t1').status, 'exception')
        self.assertTrue(self.live('t2').exists())
        self.assertEqual(run.status, 'success')

    def test_second_run_while_running_refused(self):
        DR.start_run(triggered_by='a', date_from=D1, date_to=D2, source_types=[])
        with self.assertRaises(DR.DraftBusy):
            DR.start_run(triggered_by='b', date_from=D1, date_to=D2, source_types=[])
        self.assertEqual(GLDraftRun.objects.filter(status='running').count(), 1)

    def test_stale_running_run_is_failed_on_start(self):
        old = DR.start_run(triggered_by='a', date_from=D1, date_to=D2, source_types=[])
        GLDraftRun.objects.filter(pk=old.pk).update(started_at=timezone.now() - datetime.timedelta(hours=3))
        new = DR.start_run(triggered_by='b', date_from=D1, date_to=D2, source_types=[])
        old.refresh_from_db()
        self.assertEqual((old.status, new.status), ('failed', 'running'))

    def test_reader_failure_gives_partial_and_no_vanish(self):
        self.rule()
        self.rule(code='cr', lines=CREDIT, source_type='credit_sales')
        self.docs['sales_tenders'] = [tender('t1', '10.00')]
        self.docs['credit_sales'] = [credit('c1', '10.00', '501')]
        self.run_engine(['sales_tenders', 'credit_sales'])
        self.fail_types = {'sales_tenders'}
        self.docs['credit_sales'].append(credit('c3', '5.00', '501'))
        run = self.run_engine(['sales_tenders', 'credit_sales'])
        self.assertEqual(run.status, 'partial')
        self.assertIn('sales_tenders', run.detail['reader_errors'])
        self.assertIsNotNone(run.finished_at)
        self.assertEqual(GLSourceDoc.objects.get(source_key='t1').status, 'drafted')
        self.assertTrue(self.live('t1').exists())
        self.assertTrue(self.live('c3').exists())   # other types still drafted

    def test_date_change_moves_doc_between_branch_day_groups(self):
        self.rule(granularity='branch_day')
        self.docs['sales_tenders'] = [tender('t1', '100.00'), tender('t2', '50.00', pt='40')]
        self.run_engine()
        old = self.live('cash:130:2026-03-10').get()
        approve(old.id, user=self.staff)
        self.docs['sales_tenders'][1] = tender('t2', '50.00', pt='40', date=datetime.date(2026, 3, 11))
        run = self.run_engine()
        old.refresh_from_db()
        self.assertEqual(old.status, 'reversed')
        self.assertEqual(run.counts['reversed'], 1)
        self.assertEqual(self.amounts(self.live('cash:130:2026-03-10').get())[0][1], DEC('100.00'))
        self.assertEqual(self.amounts(self.live('cash:130:2026-03-11').get())[0][1], DEC('50.00'))
        self.assertEqual(GLSourceDoc.objects.get(source_key='t2').entry, self.live('cash:130:2026-03-11').get())
        n = LedgerEntry.objects.count()
        self.run_engine()
        self.assertEqual(LedgerEntry.objects.count(), n)

    def test_cosmetic_change_keeps_approved_entry(self):
        self.rule()
        self.docs['sales_tenders'] = [tender('t1', '100.00')]
        self.run_engine()
        e = self.live('t1').get()
        approve(e.id, user=self.staff)
        d = tender('t1', '100.00')
        self.docs['sales_tenders'] = [SourceDoc(d.source_type, d.source_key, d.doc_date, d.branch_code,
                                                d.kind, d.personcode, d.amounts, {**d.attrs, 'note': 'x'})]
        run = self.run_engine()
        self.assertEqual((run.counts['changed'], run.counts['reversed']), (1, 0))
        e.refresh_from_db()
        self.assertEqual(e.status, 'approved')
        self.assertEqual(GLSourceDoc.objects.get(source_key='t1').entry_id, e.id)


class CommandTests(Base):
    def test_dry_run_rolls_back(self):
        from io import StringIO
        from unittest import mock

        from django.core.management import call_command
        self.rule()
        self.docs['sales_tenders'] = [tender('t1', '100.00')]
        out = StringIO()
        with mock.patch.dict(DR.READERS, {'sales_tenders': self.reader('sales_tenders')}):
            call_command('gl_draft', '--from', '2026-03-01', '--to', '2026-03-31',
                         '--source', 'sales_tenders', '--dry-run', stdout=out)
        self.assertIn('created', out.getvalue())
        self.assertFalse(LedgerEntry.objects.exists())
        self.assertFalse(GLSourceDoc.objects.exists())
        self.assertFalse(GLDraftRun.objects.exists())
