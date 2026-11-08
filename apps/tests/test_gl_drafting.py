"""Plan 2 / Task 6: drafting engine — idempotent drafts, exceptions, late changes."""
import datetime
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.branches.models import Branch
from apps.finance.gl import drafting as DR
from apps.finance.gl import rules as R
from apps.finance.gl.corrections import post_from_exception, post_late_correction, post_late_document
from apps.finance.gl.drafting_serializers import exception_json
from apps.finance.gl.ledger import LedgerError, approve, delete_draft, save_draft
from apps.finance.gl.ledger import reverse as ledger_reverse
from apps.finance.gl.sources import SourceDoc
from apps.finance.models import (
    FinancialPeriod, GLAccount, GLAccountGroup, GLDraftRun, GLParty, GLSourceDoc, LedgerEntry, LedgerLine,
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

    def run_engine(self, types=None, d1=D1, d2=D2, **kw):
        types = types or ['sales_tenders']
        run = DR.start_run(triggered_by='test', date_from=d1, date_to=d2, source_types=types)
        readers = {t: self.reader(t) for t in self.docs}
        return DR.draft_range(d1, d2, source_types=types, run=run, fetch=lambda sql: [],
                              readers=readers, **kw)

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

    def test_accepts_postings_follows_the_period(self):
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
        self.assertEqual(e1.description, 'نقدية b130 2026-03-10')
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
        self.assertEqual((ex.detail['group_key'], ex.detail['member_source_keys']), ('t1', ['t1']))
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

    def test_closed_branch_day_group_of_n_docs_gives_one_exception(self):
        """Ruling P19: an N-doc group changed in a closed month -> exactly one exception (first member),
        the others held without rows; reopening the month releases the whole group."""
        self.rule(granularity='branch_day')
        gk = 'cash:130:2026-03-10'
        self.docs['sales_tenders'] = [tender('t3', '30.00', pt='60'), tender('t1', '10.00'),
                                      tender('t2', '20.00', pt='40')]
        self.run_engine()
        a = self.live(gk).get()
        approve(a.id, user=self.staff)
        self.close_month(MAR10)
        self.docs['sales_tenders'] = [tender('t3', '33.00', pt='60'), tender('t1', '11.00'),
                                      tender('t2', '22.00', pt='40')]
        for _ in range(2):   # a re-run changes nothing and never adds a second exception
            n = LedgerEntry.objects.count()
            run = self.run_engine()
            self.assertEqual(LedgerEntry.objects.count(), n)
            ex = SourceException.objects.get(status='open')
            self.assertEqual((ex.kind, ex.source_doc.source_key), ('closed_period_change', 't1'))
            self.assertEqual(ex.detail['member_source_keys'], ['t1', 't2', 't3'])
            self.assertEqual((ex.detail['group_key'], ex.original_entry_id), (gk, a.id))
            self.assertEqual(ex.proposed_lines[0]['debit'], '66.00')
            self.assertEqual(run.counts['exceptions'], 1)
            self.assertEqual(SourceException.objects.count(), 1)
            self.assertEqual(set(GLSourceDoc.objects.values_list('status', flat=True)), {'exception'})
        a.refresh_from_db()
        self.assertEqual(a.status, 'approved')
        self.close_month(MAR10, 'open')
        run = self.run_engine()
        self.assertEqual((run.counts['reversed'], run.counts['created']), (1, 1))
        new = self.live(gk).get()
        self.assertEqual(self.amounts(new)[0][1], DEC('66.00'))
        self.assertEqual(set(GLSourceDoc.objects.values_list('status', 'entry_id')), {('drafted', new.id)})
        ex.refresh_from_db()
        self.assertEqual(ex.status, 'resolved')

    def test_closed_period_change_on_live_draft_names_the_entry(self):
        self.rule(granularity='branch_day')
        self.docs['sales_tenders'] = [tender('t1', '10.00'), tender('t2', '20.00', pt='40')]
        self.run_engine()
        draft = self.live('cash:130:2026-03-10').get()
        self.close_month(MAR10)
        self.docs['sales_tenders'] = [tender('t1', '15.00'), tender('t2', '20.00', pt='40')]
        self.run_engine()
        ex = SourceException.objects.get(status='open')
        self.assertEqual((ex.original_entry, ex.detail['entry_id']), (None, draft.id))
        self.assertEqual(ex.detail['member_source_keys'], ['t1', 't2'])
        self.assertEqual(LedgerEntry.objects.get(pk=draft.pk).status, 'draft')

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
        self.assertIsNotNone(old.heartbeat_at)
        GLDraftRun.objects.filter(pk=old.pk).update(heartbeat_at=timezone.now() - datetime.timedelta(minutes=20))
        with self.assertRaises(DR.DraftBusy):   # 20 min without a heartbeat: still alive
            DR.start_run(triggered_by='b', date_from=D1, date_to=D2, source_types=[])
        GLDraftRun.objects.filter(pk=old.pk).update(heartbeat_at=timezone.now() - datetime.timedelta(minutes=31))
        new = DR.start_run(triggered_by='b', date_from=D1, date_to=D2, source_types=[])
        old.refresh_from_db()
        self.assertEqual((old.status, new.status), ('failed', 'running'))

    def test_superseded_run_aborts(self):
        self.rule()
        self.docs['sales_tenders'] = [tender('t1', '10.00')]
        run = DR.start_run(triggered_by='a', date_from=D1, date_to=D2, source_types=['sales_tenders'])
        GLDraftRun.objects.filter(pk=run.pk).update(status='failed')   # taken over by another start
        run = DR.draft_range(D1, D2, source_types=['sales_tenders'], run=run, fetch=lambda sql: [],
                             readers={'sales_tenders': self.reader('sales_tenders')})
        self.assertEqual((run.status, run.detail['error']), ('failed', 'superseded'))
        self.assertFalse(LedgerEntry.objects.exists())

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
        self.assertIn('  created: 1\n', out.getvalue())
        self.assertIn('  new: 1\n', out.getvalue())
        self.assertFalse(LedgerEntry.objects.exists())
        self.assertFalse(GLSourceDoc.objects.exists())
        self.assertFalse(GLDraftRun.objects.exists())


class LateChangeSafetyTests(Base):
    MAR31 = datetime.date(2026, 3, 31)
    APR1 = datetime.date(2026, 4, 1)
    GRP = 'cash:130:2026-03-10'

    def test_move_out_of_closed_group_keeps_exception_open(self):
        """C1: closed-month group A keeps its exception; the doc drafts in open group B; no auto-resolve."""
        self.rule(granularity='branch_day')
        d2 = datetime.date(2026, 4, 30)
        self.docs['sales_tenders'] = [tender('t1', '100.00', date=self.MAR31),
                                      tender('t2', '50.00', pt='40', date=self.MAR31)]
        self.run_engine(d2=d2)
        a = self.live('cash:130:2026-03-31').get()
        approve(a.id, user=self.staff)
        a_lines = self.amounts(a)
        self.close_month(self.MAR31)
        self.docs['sales_tenders'][1] = tender('t2', '50.00', pt='40', date=self.APR1)
        for i in range(2):
            n = LedgerEntry.objects.count()
            run = self.run_engine(d2=d2)
            a.refresh_from_db()
            self.assertEqual((a.status, self.amounts(a)), ('approved', a_lines))
            b = self.live('cash:130:2026-04-01').get()
            self.assertEqual(self.amounts(b)[0][1], DEC('50.00'))
            self.assertEqual(GLSourceDoc.objects.get(source_key='t2').entry_id, b.id)
            # Ruling P19: ONE exception for group A, on its first member, listing every member
            ex = SourceException.objects.get(kind='closed_period_change')
            self.assertEqual((ex.source_doc.source_key, ex.status, ex.original_entry_id), ('t1', 'open', a.id))
            self.assertEqual(ex.detail['group_key'], 'cash:130:2026-03-31')
            self.assertEqual(ex.detail['member_source_keys'], ['t1', 't2'])
            self.assertFalse(SourceException.objects.filter(source_doc__source_key='t2').exists())
            if i == 1:   # run 2 changes nothing
                self.assertEqual(LedgerEntry.objects.count(), n)
                for k in ('created', 'replaced', 'reversed', 'deleted'):
                    self.assertEqual(run.counts[k], 0, k)

    def _two_closed_groups(self):
        """t1+t2 approved in A (closed); t1 changes (A's row sits on t1), then moves to closed B."""
        self.rule(granularity='branch_day')
        A, B = 'cash:130:2026-03-10', 'cash:130:2026-03-11'
        self.docs['sales_tenders'] = [tender('t1', '100.00'), tender('t2', '50.00', pt='40')]
        self.run_engine()
        a = self.live(A).get()
        approve(a.id, user=self.staff)
        self.close_month(MAR10)
        self.docs['sales_tenders'][0] = tender('t1', '90.00')
        self.run_engine()
        ex = SourceException.objects.get(kind='closed_period_change', status='open')
        self.assertEqual((ex.source_doc.source_key, ex.detail['group_key']), ('t1', A))
        self.docs['sales_tenders'][0] = tender('t1', '90.00', date=datetime.date(2026, 3, 11))
        return A, B, a, ex

    def test_closed_group_holder_prefers_member_still_in_group(self):
        """t1 (lowest key) left A for closed B: A's new row sits on t2, so B's row has t1 free."""
        self.rule(granularity='branch_day')
        A, B = 'cash:130:2026-03-10', 'cash:130:2026-03-11'
        self.docs['sales_tenders'] = [tender('t1', '100.00'), tender('t2', '50.00', pt='40')]
        self.run_engine()
        a = self.live(A).get()
        approve(a.id, user=self.staff)
        self.close_month(MAR10)
        self.docs['sales_tenders'][0] = tender('t1', '100.00', date=datetime.date(2026, 3, 11))
        run = self.run_engine()
        self.assertEqual(run.status, 'success')
        rows = {r.detail['group_key']: r for r in SourceException.objects.filter(
            kind='closed_period_change', status='open')}
        self.assertEqual(set(rows), {A, B})
        self.assertEqual(rows[A].source_doc.source_key, 't2')
        self.assertEqual(rows[A].original_entry_id, a.id)
        self.assertEqual(rows[B].source_doc.source_key, 't1')
        self.assertIsNone(rows[B].original_entry_id)

    def test_closed_group_holder_collision_reported_not_overwritten(self):
        A, B, a, ex = self._two_closed_groups()
        for _ in range(2):   # every run retries, and stays partial until the holder is free
            run = self.run_engine()
            self.assertEqual(run.status, 'partial')
            self.assertEqual(run.detail['group_errors'], {B: 'holder_busy'})
            row = SourceException.objects.get(kind='closed_period_change', status='open')
            self.assertEqual((row.pk, row.detail['group_key'], row.original_entry_id), (ex.pk, A, a.id))
            sd = GLSourceDoc.objects.get(source_key='t1')
            self.assertEqual((sd.status, sd.group_key), ('exception', B))

    def test_holder_collision_retried_once_the_correction_frees_the_holder(self):
        """Resolving A leaves t1 no open row, which the engine reads as "finance decided";
        resolving releases a member that moved to another group so B's change is not lost."""
        from apps.finance.gl.corrections import post_late_correction
        A, B, a, ex = self._two_closed_groups()
        self.run_engine()
        ex.refresh_from_db()
        fix = post_late_correction(a.id, ex.proposed_lines, user=self.staff, reason='x', exception_id=ex.id)
        self.assertEqual(GLSourceDoc.objects.get(source_key='t1').status, 'new')
        t2 = GLSourceDoc.objects.get(source_key='t2')
        self.assertEqual((t2.status, t2.group_key, t2.entry_id), ('drafted', A, a.id))
        run = self.run_engine()
        self.assertEqual(run.status, 'success')
        row = SourceException.objects.get(kind='closed_period_change', status='open')
        self.assertEqual((row.detail['group_key'], row.source_doc.source_key, row.original_entry_id), (B, 't1', None))
        # the corrected group A is not raised again, and nothing was reversed or replaced
        self.assertFalse(SourceException.objects.filter(status='open', detail__group_key=A).exists())
        a.refresh_from_db()
        self.assertEqual(a.status, 'approved')
        self.assertEqual(LedgerEntry.objects.get(pk=fix.pk).status, 'draft')

    # ── a group that already has a correction (Plan 3) ────────────────────────

    def _corrected_group(self, runs=1):
        """t1=100 + t2=50 approved, month closed, t1 -> 90, correction approved (effective 140)."""
        from apps.finance.gl.corrections import post_late_correction
        self.rule(granularity='branch_day')
        self.docs['sales_tenders'] = [tender('t1', '100.00'), tender('t2', '50.00', pt='40')]
        self.run_engine()
        a = self.live(self.GRP).get()
        approve(a.id, user=self.staff)
        self.close_month(MAR10)
        self.docs['sales_tenders'][0] = tender('t1', '90.00')
        for _ in range(runs):
            self.run_engine()
        ex = SourceException.objects.get(kind='closed_period_change', status='open')
        fix = post_late_correction(a.id, ex.proposed_lines, user=self.staff, reason='x', exception_id=ex.id)
        return a, approve(fix.id, user=self.staff)

    def effective_cash(self, entry):
        from apps.finance.gl.corrections import effective_lines
        return effective_lines(entry)[('1302', self.b130.pk, '')]

    def ledger_cash(self):
        """1302 net of every posted entry in the ledger."""
        total = DEC('0')
        for e in LedgerEntry.objects.filter(status__in=['approved', 'reversed']):
            for ln in e.lines.select_related('account').filter(account__code='1302'):
                total += ln.debit - ln.credit
        return total

    def test_resolve_puts_group_members_back_on_the_entry(self):
        a, _ = self._corrected_group(runs=2)   # the second run holds t2 in 'exception' too
        for key in ('t1', 't2'):
            sd = GLSourceDoc.objects.get(source_key=key)
            self.assertEqual((sd.status, sd.entry_id), ('drafted', a.id), key)
        run = self.run_engine()   # quiet: nothing to raise
        self.assertEqual(run.status, 'success')
        self.assertFalse(SourceException.objects.filter(status='open').exists())

    def test_second_change_after_correction_proposes_the_whole_group(self):
        from apps.finance.gl.corrections import post_late_correction
        a, _ = self._corrected_group(runs=2)
        self.docs['sales_tenders'][0] = tender('t1', '80.00')   # the source group is now 130
        self.run_engine()
        ex = SourceException.objects.get(kind='closed_period_change', status='open')
        self.assertEqual(ex.detail['member_source_keys'], ['t1', 't2'])
        self.assertEqual(DEC(ex.proposed_lines[0]['debit']), DEC('130.00'))
        fix = post_late_correction(a.id, ex.proposed_lines, user=self.staff, reason='y', exception_id=ex.id)
        self.assertEqual(self.amounts(fix), [('6002', DEC('10.00'), DEC('0.00')),
                                             ('1302', DEC('0.00'), DEC('10.00'))])
        approve(fix.id, user=self.staff)
        self.assertEqual(self.effective_cash(a), DEC('130.00'))

    def test_source_back_at_original_value_raises_a_row(self):
        from apps.finance.gl.corrections import post_late_correction
        a, _ = self._corrected_group()
        self.docs['sales_tenders'][0] = tender('t1', '100.00')   # back to 150; effective is 140
        run = self.run_engine()
        ex = SourceException.objects.get(kind='closed_period_change', status='open')
        self.assertEqual(run.counts['exceptions'], 1)
        fix = post_late_correction(a.id, ex.proposed_lines, user=self.staff, reason='y', exception_id=ex.id)
        approve(fix.id, user=self.staff)
        self.assertEqual(self.effective_cash(a), DEC('150.00'))

    def test_lines_equal_to_the_effective_figures_raise_no_row(self):
        a, _ = self._corrected_group()
        # a change that does not move the group's lines: t1 -> 80, t2 -> 60, still 140
        self.docs['sales_tenders'] = [tender('t1', '80.00'), tender('t2', '60.00', pt='40')]
        run = self.run_engine()
        self.assertEqual(run.status, 'success')
        self.assertFalse(SourceException.objects.filter(status='open').exists())
        self.assertEqual(set(GLSourceDoc.objects.values_list('status', flat=True)), {'drafted'})

    def test_pending_draft_correction_counts_in_the_comparison(self):
        """Effective alone says 150 with a draft to 140 waiting: back at 150 must not settle."""
        from apps.finance.gl.corrections import effective_lines, post_late_correction
        self.rule(granularity='branch_day')
        self.docs['sales_tenders'] = [tender('t1', '100.00'), tender('t2', '50.00', pt='40')]
        self.run_engine()
        a = self.live(self.GRP).get()
        approve(a.id, user=self.staff)
        self.close_month(MAR10)
        self.docs['sales_tenders'][0] = tender('t1', '90.00')
        self.run_engine()
        ex = SourceException.objects.get(kind='closed_period_change', status='open')
        post_late_correction(a.id, ex.proposed_lines, user=self.staff, reason='x', exception_id=ex.id)
        self.assertEqual(effective_lines(a)[('1302', self.b130.pk, '')], DEC('150.00'))
        self.docs['sales_tenders'][0] = tender('t1', '100.00')
        self.run_engine()
        self.assertTrue(SourceException.objects.filter(kind='closed_period_change', status='open').exists())

    def test_reopened_month_reverses_corrections_with_the_original(self):
        a, fix = self._corrected_group()
        self.close_month(MAR10, 'open')
        self.docs['sales_tenders'][0] = tender('t1', '80.00')   # the source group is now 130
        run = self.run_engine()
        self.assertEqual(run.status, 'success')
        a.refresh_from_db()
        fix.refresh_from_db()
        self.assertEqual((a.status, fix.status), ('reversed', 'reversed'))
        new = self.live(self.GRP).get()
        approve(new.id, user=self.staff)
        self.assertEqual(self.ledger_cash(), DEC('130.00'))
        self.assertEqual(fix.reversals.get().entry_date, fix.entry_date)

    def test_reopened_month_removes_a_draft_correction_audited(self):
        from apps.audit.models import AuditLog
        from apps.finance.gl.corrections import post_late_correction
        self.rule(granularity='branch_day')
        self.docs['sales_tenders'] = [tender('t1', '100.00'), tender('t2', '50.00', pt='40')]
        self.run_engine()
        a = self.live(self.GRP).get()
        approve(a.id, user=self.staff)
        self.close_month(MAR10)
        self.docs['sales_tenders'][0] = tender('t1', '90.00')
        self.run_engine()
        ex = SourceException.objects.get(kind='closed_period_change', status='open')
        fix = post_late_correction(a.id, ex.proposed_lines, user=self.staff, reason='x', exception_id=ex.id)
        self.close_month(MAR10, 'open')
        self.docs['sales_tenders'][0] = tender('t1', '80.00')
        self.assertEqual(self.run_engine().status, 'success')
        self.assertFalse(LedgerEntry.objects.filter(pk=fix.pk).exists())
        self.assertTrue(AuditLog.objects.filter(action='gl_entry_draft_deleted', object_id=str(fix.pk)).exists())
        a.refresh_from_db()
        self.assertEqual(a.status, 'reversed')
        approve(self.live(self.GRP).get().id, user=self.staff)
        self.assertEqual(self.ledger_cash(), DEC('130.00'))

    def test_correction_in_a_closed_month_blocks_the_reversal(self):
        a, fix = self._corrected_group()
        self.close_month(fix.entry_date)
        self.close_month(MAR10, 'open')
        self.docs['sales_tenders'][0] = tender('t1', '80.00')
        run = self.run_engine()
        a.refresh_from_db()
        fix.refresh_from_db()
        self.assertEqual((a.status, fix.status), ('approved', 'approved'))
        self.assertEqual(run.counts['reversed'], 0)
        ex = SourceException.objects.get(kind='closed_period_change', status='open')
        self.assertEqual(ex.original_entry_id, a.id)

    def test_vanished_group_in_reopened_month_reverses_corrections_too(self):
        a, fix = self._corrected_group()
        self.close_month(MAR10, 'open')
        self.docs['sales_tenders'] = []
        self.assertEqual(self.run_engine().status, 'success')
        a.refresh_from_db()
        fix.refresh_from_db()
        self.assertEqual((a.status, fix.status), ('reversed', 'reversed'))
        self.assertEqual(self.ledger_cash(), DEC('0'))

    def test_group_corrected_to_nothing_raises_no_row_when_it_vanishes(self):
        from apps.finance.gl.corrections import post_late_correction
        self.rule(granularity='branch_day')
        self.docs['sales_tenders'] = [tender('t1', '100.00'), tender('t2', '50.00', pt='40')]
        self.run_engine()
        a = self.live(self.GRP).get()
        approve(a.id, user=self.staff)
        self.close_month(MAR10)
        self.docs['sales_tenders'] = []
        self.run_engine(allow_mass_vanish=True)
        ex = SourceException.objects.get(kind='closed_period_change', status='open')
        fix = post_late_correction(a.id, [], user=self.staff, reason='x', exception_id=ex.id)
        approve(fix.id, user=self.staff)
        self.assertEqual(self.run_engine(allow_mass_vanish=True).status, 'success')
        self.assertFalse(SourceException.objects.filter(status='open').exists())

    def test_month_closing_mid_run_raises_instead_of_posting_into_a_later_month(self):
        """Minor 6: the engine's reversal stays in the entry's own month."""
        from unittest import mock
        self.rule(granularity='branch_day')
        self.docs['sales_tenders'] = [tender('t1', '100.00'), tender('t2', '50.00', pt='40')]
        self.run_engine()
        a = self.live(self.GRP).get()
        approve(a.id, user=self.staff)
        self.docs['sales_tenders'][0] = tender('t1', '90.00')
        self.close_month(MAR10)
        with mock.patch.object(DR, 'accepts_postings', return_value=True):   # passed the check, then closed
            self.run_engine()
        a.refresh_from_db()
        self.assertEqual(a.status, 'approved')
        self.assertFalse(a.reversals.exists())
        ex = SourceException.objects.get(kind='ledger_error', status='open')
        self.assertEqual(ex.detail['code'], 'closed_period')

    def test_resolve_order_does_not_release_a_member_already_posted(self):
        """Important 4: t1 moved A -> B; B's late document first, then A's correction."""
        from apps.finance.gl.corrections import post_late_correction, post_late_document
        self.rule(granularity='branch_day')
        A, B = self.GRP, 'cash:130:2026-03-11'
        self.docs['sales_tenders'] = [tender('t1', '100.00'), tender('t2', '50.00', pt='40')]
        self.run_engine()
        a = self.live(A).get()
        approve(a.id, user=self.staff)
        self.close_month(MAR10)
        self.docs['sales_tenders'][0] = tender('t1', '100.00', date=datetime.date(2026, 3, 11))
        self.run_engine()
        rows = {r.detail['group_key']: r for r in SourceException.objects.filter(
            kind='closed_period_change', status='open')}
        late = post_late_document(rows[B].id, user=self.staff)
        post_late_correction(a.id, rows[A].proposed_lines, user=self.staff, reason='x', exception_id=rows[A].id)
        t1 = GLSourceDoc.objects.get(source_key='t1')
        self.assertEqual((t1.status, t1.group_key, t1.entry_id), ('drafted', B, late.pk))
        self.assertEqual(self.run_engine().status, 'success')
        self.assertFalse(SourceException.objects.filter(status='open').exists())

    def test_resolve_a_first_does_not_release_a_member_with_its_own_open_row(self):
        from apps.finance.gl.corrections import post_late_correction, post_late_document
        self.rule(granularity='branch_day')
        A, B = self.GRP, 'cash:130:2026-03-11'
        self.docs['sales_tenders'] = [tender('t1', '100.00'), tender('t2', '50.00', pt='40')]
        self.run_engine()
        a = self.live(A).get()
        approve(a.id, user=self.staff)
        self.close_month(MAR10)
        self.docs['sales_tenders'][0] = tender('t1', '100.00', date=datetime.date(2026, 3, 11))
        self.run_engine()
        rows = {r.detail['group_key']: r for r in SourceException.objects.filter(
            kind='closed_period_change', status='open')}
        post_late_correction(a.id, rows[A].proposed_lines, user=self.staff, reason='x', exception_id=rows[A].id)
        self.assertEqual(GLSourceDoc.objects.get(source_key='t1').status, 'exception')
        late = post_late_document(rows[B].id, user=self.staff)
        t1 = GLSourceDoc.objects.get(source_key='t1')
        self.assertEqual((t1.status, t1.entry_id), ('drafted', late.pk))

    def _ignored_group(self, ignore_runs=2):
        """t1=100 + t2=50 approved, month closed, t1 -> 90, row ignored through the service."""
        from apps.finance.gl import plan2_adapter
        self.rule(granularity='branch_day')
        self.docs['sales_tenders'] = [tender('t1', '100.00'), tender('t2', '50.00', pt='40')]
        self.run_engine()
        a = self.live(self.GRP).get()
        approve(a.id, user=self.staff)
        self.close_month(MAR10)
        self.docs['sales_tenders'][0] = tender('t1', '90.00')
        for _ in range(ignore_runs):
            self.run_engine()
        ex = SourceException.objects.get(kind='closed_period_change', status='open')
        ex.status = 'ignored'
        ex.save(update_fields=['status'])
        plan2_adapter.closed_change_ignored(ex)
        return a

    def test_ignored_change_is_not_raised_again_while_the_source_stands(self):
        a = self._ignored_group()
        for key in ('t1', 't2'):
            sd = GLSourceDoc.objects.get(source_key=key)
            self.assertEqual((sd.status, sd.entry_id), ('drafted', a.id), key)
        for _ in range(2):
            run = self.run_engine()
            self.assertEqual(run.status, 'success')
            self.assertEqual(run.counts['exceptions'], 0)
            self.assertFalse(SourceException.objects.filter(status='open').exists())

    def test_change_after_an_ignore_proposes_the_whole_group(self):
        from apps.finance.gl.corrections import post_late_correction
        a = self._ignored_group()
        self.docs['sales_tenders'][0] = tender('t1', '80.00')   # the source group is now 130
        self.run_engine()
        ex = SourceException.objects.get(kind='closed_period_change', status='open')
        self.assertEqual(ex.detail['member_source_keys'], ['t1', 't2'])
        self.assertEqual(DEC(ex.proposed_lines[0]['debit']), DEC('130.00'))
        fix = post_late_correction(a.id, ex.proposed_lines, user=self.staff, reason='y', exception_id=ex.id)
        approve(fix.id, user=self.staff)
        self.assertEqual(self.effective_cash(a), DEC('130.00'))

    def test_ignored_new_group_stays_quiet_and_a_change_proposes_all_of_it(self):
        """No live entry to sit on: the members are 'skipped', still counted in the rebuild."""
        from apps.finance.gl import plan2_adapter
        self.rule(granularity='branch_day')
        self.close_month(MAR10)
        self.docs['sales_tenders'] = [tender('t1', '100.00'), tender('t2', '50.00', pt='40')]
        self.run_engine()
        self.run_engine()
        ex = SourceException.objects.get(kind='closed_period_change', status='open')
        ex.status = 'ignored'
        ex.save(update_fields=['status'])
        plan2_adapter.closed_change_ignored(ex)
        self.assertEqual(set(GLSourceDoc.objects.values_list('status', flat=True)), {'skipped'})
        run = self.run_engine()
        self.assertEqual((run.status, run.counts['exceptions']), ('success', 0))
        self.assertFalse(SourceException.objects.filter(status='open').exists())
        self.docs['sales_tenders'][0] = tender('t1', '90.00')
        self.run_engine()
        ex = SourceException.objects.get(kind='closed_period_change', status='open')
        self.assertEqual(ex.detail['member_source_keys'], ['t1', 't2'])
        self.assertEqual(DEC(ex.proposed_lines[0]['debit']), DEC('140.00'))

    def test_engine_reverse_path_still_handles_corrections_first(self):
        a, fix = self._corrected_group()
        with self.assertRaises(LedgerError):   # a person cannot, the engine's order can
            ledger_reverse(a.id, user=self.staff, reason='x')
        self.close_month(MAR10, 'open')
        self.docs['sales_tenders'][0] = tender('t1', '80.00')
        self.assertEqual(self.run_engine().status, 'success')
        a.refresh_from_db()
        fix.refresh_from_db()
        self.assertEqual((a.status, fix.status), ('reversed', 'reversed'))

    def test_crash_between_upsert_and_classify_is_repaired(self):
        from unittest import mock
        self.rule()
        self.docs['sales_tenders'] = [tender('t1', '100.00')]
        self.run_engine()
        self.docs['sales_tenders'] = [tender('t1', '90.00')]
        with mock.patch.object(DR._Engine, '_classify', side_effect=RuntimeError('crash')):
            run = self.run_engine()
        self.assertEqual(run.status, 'failed')
        self.assertEqual(self.amounts(self.live('t1').get())[0][1], DEC('100.00'))
        run = self.run_engine()
        self.assertEqual(run.status, 'success')
        self.assertEqual(self.amounts(self.live('t1').get())[0][1], DEC('90.00'))

    def test_skipped_doc_still_linked_to_live_entry_is_removed(self):
        self.rule()
        self.docs['sales_tenders'] = [tender('t1', '100.00')]
        self.run_engine()
        e = self.live('t1').get()
        skip = R.save_rule(user=self.staff, code='cash', source_type='sales_tenders',
                           effective_from=datetime.date(2026, 3, 1), conditions={}, lines=[], action='skip')
        # simulate a crash after classify (doc skipped) but before its old group was rebuilt
        GLSourceDoc.objects.filter(source_key='t1').update(status='skipped', rule=skip, group_key='')
        run = self.run_engine()
        self.assertEqual(run.counts['deleted'], 1)
        self.assertFalse(LedgerEntry.objects.filter(pk=e.pk).exists())
        sd = GLSourceDoc.objects.get(source_key='t1')
        self.assertEqual((sd.status, sd.entry_id), ('skipped', None))

    def test_old_group_failure_holds_doc_out_of_new_group(self):
        """I1c: B < A; A's rebuild raises a non-LedgerError -> doc never in two live entries."""
        from unittest import mock
        self.rule(granularity='branch_day')
        A, B = 'cash:130:2026-03-10', 'cash:130:2026-03-09'
        self.docs['sales_tenders'] = [tender('t1', '100.00'), tender('t2', '50.00', pt='40')]
        self.run_engine()
        approve(self.live(A).get().id, user=self.staff)
        self.docs['sales_tenders'][1] = tender('t2', '50.00', pt='40', date=datetime.date(2026, 3, 9))
        real = DR._Engine._group_locked

        def boom(engine, gk, triggers):
            if gk == A:
                raise RuntimeError('db hiccup')
            return real(engine, gk, triggers)
        with mock.patch.object(DR._Engine, '_group_locked', boom):
            run = self.run_engine()
        self.assertEqual(run.status, 'partial')
        self.assertIn(A, run.detail['group_errors'])
        self.assertEqual(self.amounts(self.live(A).get())[0][1], DEC('150.00'))
        self.assertFalse(self.live(B).exists())
        sd = GLSourceDoc.objects.get(source_key='t2')
        self.assertEqual(sd.status, 'exception')
        self.assertEqual(sd.exceptions.get(status='open').kind, 'ledger_error')
        run = self.run_engine()   # healthy again: A reversed + redrafted, then B
        self.assertEqual(run.status, 'success')
        self.assertEqual(self.amounts(self.live(A).get())[0][1], DEC('100.00'))
        self.assertEqual(self.amounts(self.live(B).get())[0][1], DEC('50.00'))
        self.assertFalse(SourceException.objects.filter(status='open').exists())

    def test_mass_vanish_guard(self):
        self.rule()
        self.docs['sales_tenders'] = [tender(f't{i}', '1.00') for i in range(12)]
        self.run_engine()
        self.docs['sales_tenders'] = []   # a silently empty read
        run = self.run_engine()
        self.assertEqual(run.status, 'partial')
        self.assertEqual(run.counts['vanished'], 0)
        self.assertEqual(run.detail['vanish_guard']['sales_tenders'], {'would_vanish': 12, 'seen': 12})
        self.assertEqual(LedgerEntry.objects.filter(status='draft').count(), 12)
        run = self.run_engine(allow_mass_vanish=True)
        self.assertEqual((run.status, run.counts['vanished'], run.counts['deleted']), ('success', 12, 12))

    def test_command_allow_mass_vanish_flag(self):
        from io import StringIO
        from unittest import mock

        from django.core.management import call_command
        self.rule()
        self.docs['sales_tenders'] = [tender(f't{i}', '1.00') for i in range(12)]
        self.run_engine()
        self.docs['sales_tenders'] = []
        with mock.patch.dict(DR.READERS, {'sales_tenders': self.reader('sales_tenders')}):
            out = StringIO()
            call_command('gl_draft', '--from', '2026-03-01', '--to', '2026-03-31',
                         '--source', 'sales_tenders', stdout=out)
            self.assertIn('status: partial', out.getvalue())
            out = StringIO()
            call_command('gl_draft', '--from', '2026-03-01', '--to', '2026-03-31',
                         '--source', 'sales_tenders', '--allow-mass-vanish', stdout=out)
        self.assertIn('  vanished: 12\n', out.getvalue())
        self.assertFalse(LedgerEntry.objects.exists())


class AccountantEditP21Tests(Base):
    """Ruling P21: an engine draft edited by an accountant is never replaced or reversed."""

    def edit_as_accountant(self, entry, amount):
        from apps.finance.gl.ledger import save_draft
        lines = [{'account_code': '1302', 'debit': DEC(amount), 'credit': DEC('0'), 'branch_id': self.b130.pk},
                 {'account_code': '6002', 'debit': DEC('0'), 'credit': DEC(amount), 'branch_id': self.b130.pk}]
        return save_draft(entry=entry, user=self.staff, entry_date=entry.entry_date, description='تعديل المحاسب',
                          lines=lines, book=entry.book, branch=entry.branch, source_type=entry.source_type,
                          source_key=entry.source_key)

    def test_source_change_after_accountant_edit_leaves_entry_and_raises(self):
        self.rule()
        self.docs['sales_tenders'] = [tender('t1', '100.00')]
        self.run_engine()
        e = self.live('t1').get()
        self.edit_as_accountant(e, '95.00')
        self.docs['sales_tenders'] = [tender('t1', '90.00')]
        for _ in range(2):
            run = self.run_engine()
            self.assertEqual((run.counts['replaced'], run.counts['reversed'], run.counts['created']), (0, 0, 0))
            e.refresh_from_db()
            self.assertEqual((e.status, e.description), ('draft', 'تعديل المحاسب'))
            self.assertEqual(self.amounts(e)[0][1], DEC('95.00'))
            ex = SourceException.objects.get(status='open')
            self.assertEqual((ex.kind, ex.detail['code'], ex.detail['entry_id'], ex.detail['group_key']),
                             ('ledger_error', 'edited_by_user', e.id, 't1'))
        self.assertEqual(GLSourceDoc.objects.get(source_key='t1').status, 'exception')

    def test_vanished_doc_does_not_delete_an_edited_draft(self):
        self.rule()
        self.docs['sales_tenders'] = [tender('t1', '100.00')]
        self.run_engine()
        e = self.live('t1').get()
        self.edit_as_accountant(e, '100.00')
        self.docs['sales_tenders'] = []
        run = self.run_engine()
        self.assertEqual(run.counts['deleted'], 0)
        self.assertTrue(LedgerEntry.objects.filter(pk=e.pk, status='draft').exists())
        self.assertEqual(SourceException.objects.get(status='open').detail['code'], 'edited_by_user')

    def test_unchanged_source_after_edit_raises_nothing(self):
        self.rule()
        self.docs['sales_tenders'] = [tender('t1', '100.00')]
        self.run_engine()
        e = self.live('t1').get()
        self.edit_as_accountant(e, '95.00')
        run = self.run_engine()
        self.assertEqual(run.counts['exceptions'], 0)
        self.assertFalse(SourceException.objects.exists())
        self.assertEqual(self.amounts(self.live('t1').get())[0][1], DEC('95.00'))

    def test_engine_own_saves_do_not_count_as_edits(self):
        self.rule()
        self.docs['sales_tenders'] = [tender('t1', '100.00')]
        self.run_engine()
        self.docs['sales_tenders'] = [tender('t1', '90.00')]
        self.run_engine()
        self.docs['sales_tenders'] = [tender('t1', '80.00')]
        run = self.run_engine()
        self.assertEqual(run.counts['replaced'], 1)
        self.assertFalse(SourceException.objects.exists())


class EditDecisionP23Tests(Base):
    """Ruling P23: the accountant decides — accept the new SOFTECH version or keep the edit."""
    edit_as_accountant = AccountantEditP21Tests.edit_as_accountant

    def edited_exception(self):
        self.rule()
        self.docs['sales_tenders'] = [tender('t1', '100.00')]
        self.run_engine()
        e = self.live('t1').get()
        self.edit_as_accountant(e, '95.00')
        self.docs['sales_tenders'] = [tender('t1', '90.00')]
        self.run_engine()
        return e, SourceException.objects.get(status='open')

    def test_exception_carries_proposed_lines_and_entry_status(self):
        e, ex = self.edited_exception()
        self.assertEqual(ex.detail['entry_status'], 'draft')
        got = [(ln['account_code'], ln['debit'], ln['credit']) for ln in ex.proposed_lines]
        self.assertEqual(got, [('1302', '90.00', '0'), ('6002', '0', '90.00')])
        self.assertEqual(ex.proposed_lines[0]['branch_id'], self.b130.pk)

    def test_accept_softech_replaces_the_edited_draft(self):
        e, ex = self.edited_exception()
        res = DR.accept_softech(ex.pk, user=self.staff, note='سوفتيك صح')
        self.assertEqual((res['date_from'], res['date_to'], res['source_types']), (MAR10, MAR10, ['sales_tenders']))
        ex.refresh_from_db()
        self.assertEqual((ex.status, ex.resolved_by, ex.resolution_note), ('resolved', self.staff, 'سوفتيك صح'))
        self.assertEqual(GLSourceDoc.objects.get(source_key='t1').status, 'new')
        from apps.audit.models import AuditLog
        a = AuditLog.objects.get(action='gl_entry_edit_released')
        self.assertEqual((a.object_id, a.user, a.new_data['exception_id']), (str(e.pk), self.staff, ex.pk))
        run = self.run_engine()
        self.assertEqual(run.counts['replaced'], 1)
        e.refresh_from_db()
        self.assertEqual(self.amounts(e)[0][1], DEC('90.00'))
        self.assertFalse(SourceException.objects.filter(status='open').exists())
        self.assertEqual(GLSourceDoc.objects.get(source_key='t1').status, 'drafted')

    def test_accept_softech_on_approved_entry_reverses_and_redrafts(self):
        self.rule()
        self.docs['sales_tenders'] = [tender('t1', '100.00')]
        self.run_engine()
        e = self.live('t1').get()
        self.edit_as_accountant(e, '95.00')
        approve(e.id, user=self.staff)
        self.docs['sales_tenders'] = [tender('t1', '90.00')]
        self.run_engine()
        ex = SourceException.objects.get(status='open')
        self.assertEqual(ex.detail['entry_status'], 'approved')
        DR.accept_softech(ex.pk, user=self.staff)
        run = self.run_engine()
        self.assertEqual((run.counts['reversed'], run.counts['created']), (1, 1))
        e.refresh_from_db()
        self.assertEqual(e.status, 'reversed')
        new = self.live('t1').get()
        self.assertEqual((new.status, self.amounts(new)[0][1]), ('draft', DEC('90.00')))

    def test_keep_edit_holds_until_the_next_softech_change(self):
        e, ex = self.edited_exception()
        DR.keep_edit(ex.pk, user=self.staff, note='تعديلي صح')
        ex.refresh_from_db()
        self.assertEqual((ex.status, ex.resolution_note), ('resolved', 'تعديلي صح'))
        sd = GLSourceDoc.objects.get(source_key='t1')
        self.assertEqual((sd.status, sd.entry_id, sd.group_key), ('drafted', e.pk, 't1'))
        from apps.audit.models import AuditLog
        self.assertTrue(AuditLog.objects.filter(action='gl_entry_edit_kept', object_id=str(e.pk),
                                                user=self.staff).exists())
        run = self.run_engine()   # SOFTECH unchanged: nothing happens
        for k in ('changed', 'replaced', 'reversed', 'created', 'exceptions'):
            self.assertEqual(run.counts[k], 0, k)
        self.assertFalse(SourceException.objects.filter(status='open').exists())
        self.assertEqual(self.amounts(self.live('t1').get())[0][1], DEC('95.00'))
        self.docs['sales_tenders'] = [tender('t1', '80.00')]   # the next change asks again
        run = self.run_engine()
        self.assertEqual(run.counts['replaced'], 0)
        ex2 = SourceException.objects.get(status='open')
        self.assertEqual((ex2.detail['code'], ex2.proposed_lines[0]['debit']), ('edited_by_user', '80.00'))

    def test_edit_after_release_is_protected_again(self):
        e, ex = self.edited_exception()
        DR.accept_softech(ex.pk, user=self.staff)
        self.run_engine()
        self.edit_as_accountant(e, '85.00')
        self.docs['sales_tenders'] = [tender('t1', '70.00')]
        run = self.run_engine()
        self.assertEqual(run.counts['replaced'], 0)
        self.assertEqual(SourceException.objects.get(status='open').detail['code'], 'edited_by_user')
        self.assertEqual(self.amounts(self.live('t1').get())[0][1], DEC('85.00'))

    def test_decisions_refuse_non_open_or_other_kinds(self):
        e, ex = self.edited_exception()
        DR.keep_edit(ex.pk, user=self.staff)
        with self.assertRaises(DR.DecisionError) as cm:
            DR.accept_softech(ex.pk, user=self.staff)
        self.assertEqual(cm.exception.code, 'not_open')
        other = SourceException.objects.create(source_doc=GLSourceDoc.objects.get(source_key='t1'),
                                               kind='no_rule', source_date=MAR10, message='m')
        for fn in (DR.accept_softech, DR.keep_edit):
            with self.assertRaises(DR.DecisionError) as cm:
                fn(other.pk, user=self.staff)
            self.assertEqual(cm.exception.code, 'not_edited_by_user')

    def test_keep_edit_on_vanished_doc_stops_asking(self):
        self.rule()
        self.docs['sales_tenders'] = [tender('t1', '100.00')]
        self.run_engine()
        e = self.live('t1').get()
        self.edit_as_accountant(e, '100.00')
        self.docs['sales_tenders'] = []
        self.run_engine()
        ex = SourceException.objects.get(status='open')
        DR.keep_edit(ex.pk, user=self.staff)
        run = self.run_engine()
        self.assertEqual((run.counts['deleted'], run.counts['exceptions']), (0, 0))
        self.assertTrue(LedgerEntry.objects.filter(pk=e.pk, status='draft').exists())
        self.assertFalse(SourceException.objects.filter(status='open').exists())

    def test_keep_edit_refused_when_a_doc_moved_to_another_group(self):
        self.rule(granularity='branch_day')
        self.docs['sales_tenders'] = [tender('t1', '100.00'), tender('t2', '50.00', pt='40')]
        self.run_engine()
        e = self.live('cash:130:2026-03-10').get()
        self.edit_as_accountant(e, '150.00')
        self.docs['sales_tenders'][1] = tender('t2', '50.00', pt='40', date=datetime.date(2026, 3, 11))
        self.run_engine()
        ex = SourceException.objects.get(status='open', source_doc__source_key='t2')
        self.assertEqual(ex.detail['code'], 'edited_by_user')
        with self.assertRaises(DR.DecisionError) as cm:
            DR.keep_edit(ex.pk, user=self.staff)
        self.assertEqual(cm.exception.code, 'moved')
        self.assertEqual(SourceException.objects.get(pk=ex.pk).status, 'open')
        DR.accept_softech(ex.pk, user=self.staff)   # accepting moves it cleanly
        self.run_engine()
        self.assertEqual(self.amounts(self.live('cash:130:2026-03-10').get())[0][1], DEC('100.00'))
        self.assertEqual(self.amounts(self.live('cash:130:2026-03-11').get())[0][1], DEC('50.00'))
        self.assertFalse(SourceException.objects.filter(status='open').exists())

    def test_keep_edit_refused_when_doc_still_sits_in_another_live_entry(self):
        """Review fix 1: a doc moves O -> G, both edited; G's row overwrites the doc's only open
        ledger_error row (group_key G). Keeping G must not relink it while O still carries it."""
        self.rule(granularity='branch_day')
        mar11 = datetime.date(2026, 3, 11)
        self.docs['sales_tenders'] = [tender('t1', '100.00'), tender('t2', '50.00', pt='40'),
                                      tender('t3', '30.00', date=mar11)]
        self.run_engine()
        o, g = self.live('cash:130:2026-03-10').get(), self.live('cash:130:2026-03-11').get()
        self.edit_as_accountant(o, '150.00')
        self.edit_as_accountant(g, '31.00')
        self.docs['sales_tenders'][1] = tender('t2', '50.00', pt='40', date=mar11)
        self.run_engine()
        ex = SourceException.objects.get(status='open', source_doc__source_key='t2')
        self.assertEqual(ex.detail['group_key'], 'cash:130:2026-03-11')   # overwritten by G
        sd = GLSourceDoc.objects.get(source_key='t2')
        self.assertEqual((sd.group_key, sd.entry_id), ('cash:130:2026-03-11', o.pk))
        with self.assertRaises(DR.DecisionError) as cm:
            DR.keep_edit(ex.pk, user=self.staff)
        self.assertEqual(cm.exception.code, 'moved')
        self.assertEqual(GLSourceDoc.objects.get(source_key='t2').entry_id, o.pk)
        self.assertEqual(SourceException.objects.get(pk=ex.pk).status, 'open')

    def test_keep_edit_refused_for_a_doc_now_skipped(self):
        self.rule()
        self.docs['sales_tenders'] = [tender('t1', '100.00')]
        self.run_engine()
        e = self.live('t1').get()
        self.edit_as_accountant(e, '95.00')
        self.rule(code='skip60', action='skip', priority=200, conditions={'kind_in': ['cash']})
        self.docs['sales_tenders'] = [tender('t1', '90.00')]
        self.run_engine()
        ex = SourceException.objects.get(status='open')
        with self.assertRaises(DR.DecisionError) as cm:
            DR.keep_edit(ex.pk, user=self.staff)
        self.assertEqual(cm.exception.code, 'skipped')
        self.assertIn('قاعدة تخطٍّ', cm.exception.message)

    def test_stale_version_and_running_engine_refused(self):
        e, ex = self.edited_exception()
        v = DR.proposal_version(ex.proposed_lines)
        for fn in (DR.accept_softech, DR.keep_edit):
            with self.assertRaises(DR.DecisionError) as cm:
                fn(ex.pk, user=self.staff, version='x' + v)
            self.assertEqual(cm.exception.code, 'stale')
        DR.start_run(triggered_by='x', date_from=D1, date_to=D2, source_types=[])
        with self.assertRaises(DR.DecisionError) as cm:
            DR.keep_edit(ex.pk, user=self.staff, version=v)
        self.assertEqual(cm.exception.code, 'busy')
        self.assertEqual(SourceException.objects.get(pk=ex.pk).status, 'open')

    def test_detail_carries_proposed_header_and_held_out_count(self):
        e, ex = self.edited_exception()
        self.assertEqual((ex.detail['proposed_entry_date'], ex.detail['held_out']), ('2026-03-10', 0))
        self.assertEqual(ex.detail['proposed_description'], 'نقدية b130 2026-03-10')


class LateChangeReviewTests(Base):
    """Plan 3 final review: a closed-month change is never lost and never counted twice."""
    GRP = 'cash:130:2026-03-10'

    def net_6002(self):
        """What the books say on 6002 (credit positive): every counted entry."""
        total = DEC('0')
        for ln in LedgerLine.objects.filter(account__code='6002', entry__status__in=('approved', 'reversed')):
            total += ln.credit - ln.debit
        return total

    def open_rows(self):
        return SourceException.objects.filter(kind='closed_period_change', status='open')

    def closed_change(self, old='100.00', new='90.00'):
        """An approved group in a closed month, then SOFTECH changes it. -> (the entry, its open row)."""
        self.rule(granularity='branch_day')
        self.docs['sales_tenders'] = [tender('t1', old)]
        self.run_engine()
        entry = self.live(self.GRP).get()
        approve(entry.id, user=self.staff)
        self.close_month(MAR10)
        self.docs['sales_tenders'][0] = tender('t1', new)
        self.run_engine()
        return entry, self.open_rows().get()

    def late_document(self):
        """A brand-new group in a closed month, posted and approved in the first open month."""
        self.rule(granularity='branch_day')
        self.close_month(MAR10)
        self.docs['sales_tenders'] = [tender('t1', '100.00')]
        self.run_engine()
        return approve(post_late_document(self.open_rows().get().pk, user=self.staff, reason='جديد').id,
                       user=self.staff)

    # C1
    def test_reversed_original_then_posting_from_the_open_row_cannot_double(self):
        entry, row = self.closed_change()
        self.assertEqual(row.original_entry_id, entry.id)
        ledger_reverse(entry.id, user=self.staff, reason='خطأ')
        fix = post_from_exception(row.id, user=self.staff, reason='تغير')
        self.assertEqual((fix.source_key, fix.corrects_id), (self.GRP, None))
        approve(fix.id, user=self.staff)
        self.assertEqual(self.net_6002(), DEC('90.00'))
        self.assertEqual(GLSourceDoc.objects.get(source_key='t1').entry_id, fix.id)
        self.run_engine()
        self.assertFalse(self.open_rows().exists())
        self.assertEqual(self.net_6002(), DEC('90.00'))

    # I3
    def test_deleted_correction_draft_reopens_its_row_and_posts_once(self):
        entry, row = self.closed_change()
        fix = post_late_correction(entry.id, None, user=self.staff, reason='تغير', exception_id=row.id)
        delete_draft(fix.id, user=self.staff)
        row.refresh_from_db()
        self.assertEqual((row.status, row.resolved_by, row.resolved_at, row.resolution_note), ('open', None, None, ''))
        self.assertEqual(GLSourceDoc.objects.get(source_key='t1').status, 'exception')
        self.assertTrue(AuditLog.objects.filter(action='gl_late_change_reopened', object_id=str(row.id)).exists())
        self.run_engine()   # stays open, one row: the change is still not in the books
        self.assertEqual(self.open_rows().get().pk, row.pk)
        self.assertEqual(self.net_6002(), DEC('100.00'))
        again = post_late_correction(entry.id, None, user=self.staff, reason='تغير', exception_id=row.id)
        approve(again.id, user=self.staff)
        self.run_engine()
        self.assertFalse(self.open_rows().exists())
        self.assertEqual(self.net_6002(), DEC('90.00'))

    def test_reversed_correction_reopens_its_row_and_posts_once(self):
        entry, row = self.closed_change()
        fix = post_late_correction(entry.id, None, user=self.staff, reason='تغير', exception_id=row.id)
        approve(fix.id, user=self.staff)
        self.assertEqual(self.net_6002(), DEC('90.00'))
        ledger_reverse(fix.id, user=self.staff, reason='خطأ')
        self.assertEqual(self.open_rows().get().pk, row.pk)
        self.assertEqual(self.net_6002(), DEC('100.00'))
        again = post_late_correction(entry.id, None, user=self.staff, reason='تغير', exception_id=row.id)
        self.assertEqual(again.source_key, fix.source_key)   # the reversed one holds the key no more
        approve(again.id, user=self.staff)
        self.run_engine()
        self.assertFalse(self.open_rows().exists())
        self.assertEqual(self.net_6002(), DEC('90.00'))

    def test_undoing_a_correction_beside_a_newer_open_row_adds_no_row(self):
        entry, row = self.closed_change()
        fix = post_late_correction(entry.id, None, user=self.staff, reason='تغير', exception_id=row.id)
        self.docs['sales_tenders'][0] = tender('t1', '80.00')
        self.run_engine()   # the draft no longer says what SOFTECH says: a new row for the group
        newer = self.open_rows().get()
        self.assertNotEqual(newer.pk, row.pk)
        delete_draft(fix.id, user=self.staff)
        self.assertEqual(self.open_rows().get().pk, newer.pk)
        row.refresh_from_db()
        self.assertEqual(row.status, 'resolved')

    def test_holder_busy_with_another_group_sends_the_members_back_to_the_engine(self):
        entry, row = self.closed_change()
        fix = post_late_correction(entry.id, None, user=self.staff, reason='تغير', exception_id=row.id)
        approve(fix.id, user=self.staff)
        SourceException.objects.create(source_doc=row.source_doc, kind='closed_period_change',
                                       source_date=MAR10, detail={'group_key': 'another'})
        ledger_reverse(fix.id, user=self.staff, reason='خطأ')
        row.refresh_from_db()
        self.assertEqual(row.status, 'resolved')
        self.assertEqual(GLSourceDoc.objects.get(source_key='t1').status, 'new')

    def test_the_engine_undoing_a_correction_reopens_nothing(self):
        entry, row = self.closed_change()
        fix = post_late_correction(entry.id, None, user=self.staff, reason='تغير', exception_id=row.id)
        approve(fix.id, user=self.staff)
        self.close_month(MAR10, 'open')
        self.docs['sales_tenders'][0] = tender('t1', '80.00')
        self.run_engine()   # the month reopened: the engine reverses both and redrafts the whole figure
        fix.refresh_from_db()
        self.assertEqual(fix.status, 'reversed')
        self.assertFalse(SourceException.objects.filter(status='open').exists())
        self.assertFalse(AuditLog.objects.filter(action='gl_late_change_reopened').exists())

    # N1
    def two_corrections(self, second):
        """100 → first correction to 90 → SOFTECH says `second` → second correction, both approved."""
        entry, r1 = self.closed_change()
        c1 = approve(post_from_exception(r1.id, user=self.staff, reason='1').id, user=self.staff)
        self.docs['sales_tenders'][0] = tender('t1', second)
        self.run_engine()
        r2 = self.open_rows().get()
        c2 = approve(post_from_exception(r2.id, user=self.staff, reason='2').id, user=self.staff)
        return entry, r1, r2, c1, c2

    def test_older_correction_reversed_reopens_with_what_the_documents_say_now(self):
        _, r1, _, c1, _ = self.two_corrections('95.00')
        ledger_reverse(c1.id, user=self.staff, reason='خطأ')
        self.assertEqual(self.net_6002(), DEC('105.00'))
        r1.refresh_from_db()
        self.assertEqual(r1.status, 'open')
        self.assertEqual(DEC(r1.proposed_lines[0]['debit']), DEC('95.00'))
        approve(post_from_exception(r1.id, user=self.staff, reason='تاني').id, user=self.staff)
        self.assertEqual(self.net_6002(), DEC('95.00'))
        self.run_engine()
        self.assertFalse(self.open_rows().exists())
        self.assertEqual(self.net_6002(), DEC('95.00'))

    def test_older_correction_reversed_with_a_run_first(self):
        _, r1, _, c1, _ = self.two_corrections('95.00')
        ledger_reverse(c1.id, user=self.staff, reason='خطأ')
        self.run_engine()
        r1.refresh_from_db()
        approve(post_from_exception(r1.id, user=self.staff, reason='تاني').id, user=self.staff)
        self.run_engine()
        self.assertFalse(self.open_rows().exists())
        self.assertEqual(self.net_6002(), DEC('95.00'))

    def test_older_correction_reversed_when_the_second_went_the_same_way(self):
        _, r1, _, c1, _ = self.two_corrections('80.00')
        ledger_reverse(c1.id, user=self.staff, reason='خطأ')
        self.assertEqual(self.net_6002(), DEC('90.00'))
        approve(post_from_exception(r1.id, user=self.staff, reason='تاني').id, user=self.staff)
        self.assertEqual(self.net_6002(), DEC('80.00'))

    def test_undo_with_nothing_left_to_correct_leaves_no_row(self):
        entry, row = self.closed_change()
        fix = approve(post_from_exception(row.id, user=self.staff, reason='تغير').id, user=self.staff)
        GLSourceDoc.objects.filter(source_key='t1').update(amounts={'net': '100.00', 'sales': '100.00', 'returns': '0'})
        ledger_reverse(fix.id, user=self.staff, reason='خطأ')
        row.refresh_from_db()
        self.assertEqual(row.status, 'resolved')
        self.assertFalse(self.open_rows().exists())
        sd = GLSourceDoc.objects.get(source_key='t1')
        self.assertEqual((sd.status, sd.entry_id), ('drafted', entry.id))
        self.assertEqual(AuditLog.objects.get(action='gl_late_change_reopened').new_data['state'], 'nothing_to_correct')

    def test_undo_with_nothing_left_also_ends_an_open_row(self):
        _, row = self.closed_change()
        fix = approve(post_from_exception(row.id, user=self.staff, reason='تغير').id, user=self.staff)
        self.docs['sales_tenders'][0] = tender('t1', '100.00')
        self.run_engine()   # 100 against 90 in the ledger: a new row
        newer = self.open_rows().get()
        ledger_reverse(fix.id, user=self.staff, reason='خطأ')
        self.assertFalse(self.open_rows().exists())
        newer.refresh_from_db()
        self.assertEqual(newer.status, 'resolved')
        self.assertEqual(self.net_6002(), DEC('100.00'))

    def test_lines_that_no_longer_build_refuse_to_post_until_a_redraft(self):
        entry, row = self.closed_change()
        fix = approve(post_from_exception(row.id, user=self.staff, reason='تغير').id, user=self.staff)
        GLAccount.objects.filter(code='6002').update(is_active=False)
        ledger_reverse(fix.id, user=self.staff, reason='خطأ')
        row.refresh_from_db()
        self.assertEqual((row.status, row.detail['lines_stale']), ('open', True))
        self.assertEqual(exception_json(row)['late_action'], 'redraft')
        with self.assertRaises(LedgerError) as cm:
            post_from_exception(row.id, user=self.staff, reason='تاني')
        self.assertEqual(cm.exception.code, 'lines_stale')
        self.assertEqual(self.net_6002(), DEC('100.00'))
        GLAccount.objects.filter(code='6002').update(is_active=True)
        self.run_engine()   # the run rewrites the row, and with it the flag
        row.refresh_from_db()
        self.assertNotIn('lines_stale', row.detail)
        approve(post_from_exception(row.id, user=self.staff, reason='تاني').id, user=self.staff)
        self.assertEqual(self.net_6002(), DEC('90.00'))

    # N2
    def assert_late_document_comes_back(self, row_id):
        row = SourceException.objects.get(pk=row_id)
        self.assertEqual(row.status, 'open')
        self.assertEqual(DEC(row.proposed_lines[0]['debit']), DEC('100.00'))
        self.assertEqual(self.net_6002(), DEC('0'))
        self.run_engine(d1=datetime.date(2026, 4, 1), d2=datetime.date(2026, 4, 28))   # the scheduled window
        self.assertEqual(self.open_rows().get().pk, row_id)
        again = post_from_exception(row_id, user=self.staff, reason='تاني')
        self.assertEqual(again.source_key, self.GRP)
        approve(again.id, user=self.staff)
        self.assertEqual(self.net_6002(), DEC('100.00'))
        self.run_engine()
        self.assertFalse(self.open_rows().exists())
        self.assertEqual(self.net_6002(), DEC('100.00'))

    def test_deleted_late_document_draft_reopens_its_row(self):
        self.rule(granularity='branch_day')
        self.close_month(MAR10)
        self.docs['sales_tenders'] = [tender('t1', '100.00')]
        self.run_engine()
        row = self.open_rows().get()
        doc = post_late_document(row.pk, user=self.staff, reason='جديد')
        delete_draft(doc.id, user=self.staff)
        self.assert_late_document_comes_back(row.pk)

    def test_reversed_late_document_reopens_its_row(self):
        doc = self.late_document()
        row_id = AuditLog.objects.get(action='gl_late_document_drafted', object_id=str(doc.id)).extra['exception_id']
        ledger_reverse(doc.id, user=self.staff, reason='خطأ')
        self.assert_late_document_comes_back(row_id)

    def test_deleting_an_ordinary_draft_reopens_nothing(self):
        self.rule(granularity='branch_day')
        self.docs['sales_tenders'] = [tender('t1', '100.00')]
        self.run_engine()
        delete_draft(self.live(self.GRP).get().id, user=self.staff)
        self.assertFalse(AuditLog.objects.filter(action='gl_late_change_reopened').exists())

    # button wording
    def test_the_row_says_where_a_post_lands(self):
        _, row = self.closed_change()
        self.assertEqual(exception_json(row)['late_post_date'], '2026-04-01')
        self.close_month(datetime.date(2026, 4, 1))
        self.assertEqual(exception_json(row)['late_post_date'], '2026-05-01')

    def test_a_late_document_changed_again_says_its_own_month(self):
        doc = self.late_document()
        self.close_month(datetime.date(2026, 4, 1), 'open')
        self.docs['sales_tenders'][0] = tender('t1', '90.00')
        self.run_engine()
        out = exception_json(self.open_rows().get())
        self.assertEqual((out['late_action'], out['late_post_date']), ('post', doc.entry_date.isoformat()))

    # I4
    def test_late_document_changed_again_corrects_in_its_own_open_month(self):
        doc = self.late_document()
        self.assertEqual(doc.entry_date, datetime.date(2026, 4, 1))
        self.run_engine()   # unchanged: quiet
        self.assertFalse(self.open_rows().exists())
        self.docs['sales_tenders'][0] = tender('t1', '90.00')
        self.run_engine()
        row = self.open_rows().get()
        self.assertEqual(row.original_entry_id, doc.id)
        fix = post_from_exception(row.id, user=self.staff, reason='تغير')
        self.assertEqual((fix.entry_date, fix.corrects_id), (doc.entry_date, doc.id))
        approve(fix.id, user=self.staff)
        self.run_engine()
        self.assertFalse(self.open_rows().exists())
        self.assertEqual(self.net_6002(), DEC('90.00'))

    def test_closed_month_rebuild_with_unchanged_nets_raises_no_row(self):
        lines = [{**CASH[0], 'description': 'نقدية {docnumber}'}, CASH[1]]
        self.rule(lines=lines)

        def doc(number):
            return SourceDoc('sales_tenders', 't1', MAR10, '130', 'cash', '',
                             {'net': DEC('100.00'), 'sales': DEC('100.00'), 'returns': DEC('0')},
                             {'paymenttype': '30', 'docnumber': number})
        self.docs['sales_tenders'] = [doc('A')]
        self.run_engine()
        entry = self.live('t1').get()
        approve(entry.id, user=self.staff)
        self.close_month(MAR10)
        self.docs['sales_tenders'] = [doc('B')]
        run = self.run_engine()
        self.assertEqual(run.counts['changed'], 1)
        self.assertFalse(self.open_rows().exists())
        sd = GLSourceDoc.objects.get(source_key='t1')
        self.assertEqual((sd.status, sd.entry_id), ('drafted', entry.id))
        self.assertEqual(self.live('t1').get().pk, entry.id)

    def test_unchanged_nets_end_an_open_row_too(self):
        _, row = self.closed_change()
        self.docs['sales_tenders'][0] = tender('t1', '100.00')
        self.run_engine()   # SOFTECH went back to what the books say
        row.refresh_from_db()
        self.assertEqual(row.status, 'resolved')

    # I5
    def test_the_row_says_what_can_be_done_with_it(self):
        entry, row = self.closed_change()
        self.assertEqual(exception_json(row)['late_action'], 'post')
        self.assertEqual(exception_json(row)['original_entry_status'], 'approved')
        fix = post_late_correction(entry.id, None, user=self.staff, reason='تغير', exception_id=row.id)
        self.docs['sales_tenders'][0] = tender('t1', '80.00')
        self.run_engine()
        newer = self.open_rows().get()
        out = exception_json(newer)
        self.assertEqual((out['late_action'], out['pending_draft']['id']), ('draft_pending', fix.id))
        self.close_month(MAR10, 'open')
        delete_draft(fix.id, user=self.staff)
        self.assertEqual(exception_json(newer)['late_action'], 'redraft')

    def test_after_a_reopen_the_redraft_clears_the_row(self):
        _, row = self.closed_change()
        self.close_month(MAR10, 'open')
        with self.assertRaises(LedgerError) as cm:
            post_from_exception(row.id, user=self.staff, reason='تغير')
        self.assertEqual(cm.exception.code, 'period_open')
        self.run_engine()
        row.refresh_from_db()
        self.assertEqual(row.status, 'resolved')
        self.assertEqual(self.live(self.GRP).get().status, 'draft')

    # M4
    def test_a_late_document_saved_by_the_accountant_is_not_an_edit(self):
        self.rule(granularity='branch_day')
        self.close_month(MAR10)
        self.docs['sales_tenders'] = [tender('t1', '100.00')]
        self.run_engine()
        doc = post_late_document(self.open_rows().get().pk, user=self.staff, reason='جديد')
        self.assertFalse(DR.edited_by_user(doc))
        save_draft(user=self.staff, entry=doc, entry_date=doc.entry_date, description='عدلها', book=doc.book,
                   source_type=doc.source_type, source_key=doc.source_key,
                   lines=[{'account_code': '1302', 'debit': DEC('100.00'), 'credit': DEC('0')},
                          {'account_code': '6002', 'debit': DEC('0'), 'credit': DEC('100.00')}])
        self.assertTrue(DR.edited_by_user(doc))

    def test_a_correction_saved_by_the_accountant_is_not_an_edit(self):
        entry, row = self.closed_change()
        fix = post_late_correction(entry.id, None, user=self.staff, reason='تغير', exception_id=row.id)
        self.assertFalse(DR.edited_by_user(fix))

    # Task 2
    def test_an_existing_row_follows_its_holder_doc_date(self):
        self.rule()   # document granularity: the group key has no date in it
        self.docs['sales_tenders'] = [tender('t1', '100.00')]
        self.run_engine()
        approve(self.live('t1').get().id, user=self.staff)
        self.close_month(MAR10)
        self.docs['sales_tenders'][0] = tender('t1', '90.00')
        self.run_engine()
        row = self.open_rows().get()
        self.assertEqual(row.source_date, MAR10)
        self.docs['sales_tenders'][0] = tender('t1', '80.00', date=datetime.date(2026, 3, 12))
        self.run_engine()
        row.refresh_from_db()
        self.assertEqual(row.source_date, datetime.date(2026, 3, 12))


class BranchCostHookP33Tests(Base):
    """Ruling P33: a run with sales_tenders refreshes the SOFTECH branch cost of its months,
    best-effort (a failure is recorded, the run is not failed)."""

    def cost_fetch(self, fail=False):
        calls = []

        def fetch(sql):
            calls.append(sql)
            if 'docvalue2' in sql:
                if fail:
                    raise RuntimeError('SOFTECH slow')
                return [{'branchcode': '130', 'doccode': '115', 'cost': DEC('70'), 'docval': DEC('100')},
                        {'branchcode': '130', 'doccode': '30', 'cost': DEC('5'), 'docval': DEC('8')}]
            return []
        fetch.calls = calls
        return fetch

    def go(self, fetch, types=('sales_tenders',)):
        run = DR.start_run(triggered_by='test', date_from=D1, date_to=D2, source_types=list(types))
        readers = {t: self.reader(t) for t in self.docs}
        return DR.draft_range(D1, D2, source_types=list(types), run=run, fetch=fetch, readers=readers)

    def test_sales_run_syncs_branch_cost(self):
        from apps.finance.models import GLBranchCost
        run = self.go(self.cost_fetch())
        self.assertEqual(run.status, 'success')
        self.assertEqual(run.detail['branch_cost_rows'], 1)
        row = GLBranchCost.objects.get()
        self.assertEqual((row.year, row.month, row.branch_code, row.net_cost), (2026, 3, '130', DEC('65.00')))
        self.assertEqual((row.sales_value, row.return_value, row.net_value), (DEC('100.00'), DEC('8.00'), DEC('92.00')))

    def test_branch_cost_failure_never_fails_the_run(self):
        run = self.go(self.cost_fetch(fail=True))
        self.assertEqual(run.status, 'success')
        self.assertIn('SOFTECH slow', run.detail['branch_cost_error'])

    def test_no_sync_without_sales_tenders(self):
        f = self.cost_fetch()
        self.go(f, types=('credit_sales',))
        self.assertFalse(any('docvalue2' in c for c in f.calls))
