"""Period helpers and late-change corrections into the open month (finance-gl Plan 3, Task 2)."""
import datetime
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase

from apps.audit.models import AuditLog
from apps.finance.gl import corrections, plan2_adapter
from apps.finance.gl.corrections import effective_lines, post_late_correction, post_late_document
from apps.finance.gl.ledger import LedgerError, approve, reverse, save_draft
from apps.finance.gl.periods import (
    accepts_postings, first_open_period_after, month_period, next_month, previous_month,
)
from apps.finance.models import (
    FinancialPeriod, GLAccount, GLAccountGroup, GLSourceDoc, LedgerEntry, PostingRule,
    SourceException,
)
from apps.users.models import StaffProfile

D = datetime.date
DEC = Decimal
EXPENSE, PAYABLE = '5100', '2341'


def _lines(amount, debit=EXPENSE, credit=PAYABLE):
    return [{'account_code': debit, 'debit': DEC(amount), 'credit': DEC('0')},
            {'account_code': credit, 'debit': DEC('0'), 'credit': DEC(amount)}]


def _set_status(day, status):
    period = month_period(day)
    period.status = status
    period.save()
    return period


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        user = User.objects.create_user(username='gl_corr_u', password='x')
        cls.staff, _ = StaffProfile.objects.get_or_create(user=user)
        group = GLAccountGroup.objects.create(name='g', section='balance_sheet')
        GLAccount.objects.create(code=EXPENSE, name='مصروف', group=group, nature='debit',
                                 account_type='expense')
        GLAccount.objects.create(code=PAYABLE, name='مستحق', group=group, nature='credit',
                                 account_type='liability')

    def original(self, amount='1000.00', day=D(2026, 2, 10), source_key='doc-1', close=True):
        entry = approve(save_draft(user=self.staff, entry_date=day, description='أصل', book='cash',
                                   lines=_lines(amount), source_type='expenses',
                                   source_key=source_key).id, user=self.staff)
        if close:
            _set_status(day, 'closed')
        return entry

    def amounts(self, entry):
        return [(ln.account.code, ln.debit, ln.credit)
                for ln in entry.lines.select_related('account').order_by('line_no')]

    def correct(self, original, amount, **kw):
        return post_late_correction(original.id, _lines(amount), user=self.staff,
                                    reason=kw.pop('reason', 'تغير المستند'), **kw)

    def exception(self, *, original=None, entry_id=None, group_key='cash:130:2026-02-10',
                  keys=('t1', 't2', 't3'), lines=None, day=D(2026, 2, 10), rule=None):
        docs = [GLSourceDoc.objects.create(source_type='expenses', source_key=k, doc_date=day,
                                           content_hash='h', status='exception', group_key=group_key,
                                           rule=rule) for k in keys]
        detail = {'group_key': group_key, 'entry_id': entry_id, 'member_source_keys': list(keys),
                  'entry_date': None}
        proposed = [{'account_code': ln['account_code'], 'debit': str(ln['debit']),
                     'credit': str(ln['credit']), 'branch_id': None, 'party_code': '',
                     'description': 'بيان', 'cheque_no': '', 'due_date': None}
                    for ln in (lines if lines is not None else _lines('1100.00'))]
        return SourceException.objects.create(
            source_doc=docs[0], kind='closed_period_change', source_date=day, detail=detail,
            original_entry=original, proposed_lines=proposed)


class PeriodHelperTests(Base):
    def test_accepts_postings_false_for_closing_and_closed(self):
        day = D(2026, 5, 10)
        self.assertTrue(accepts_postings(day))
        _set_status(day, 'closing')
        self.assertFalse(accepts_postings(day))
        _set_status(day, 'closed')
        self.assertFalse(accepts_postings(day))

    def test_month_period_get_or_create_is_the_ledger_one(self):
        from apps.finance.gl import ledger
        self.assertIs(ledger._period_for, month_period)
        p = month_period(D(2026, 2, 28))
        self.assertEqual((p.period_start, p.period_end), (D(2026, 2, 1), D(2026, 2, 28)))
        self.assertEqual(month_period(D(2026, 2, 1)).pk, p.pk)

    def test_previous_and_next_month_cross_the_year(self):
        dec = month_period(D(2026, 12, 15))
        jan = next_month(dec)
        self.assertEqual((jan.year, jan.month), (2027, 1))
        self.assertEqual(previous_month(jan).pk, dec.pk)

    def test_previous_month_of_the_opening_month_is_none(self):
        self.assertIsNone(previous_month(month_period(D(2026, 1, 20))))

    def test_first_open_period_after_skips_closed_months(self):
        for m in (1, 2, 3):
            _set_status(D(2026, m, 1), 'closed')
        self.assertEqual(first_open_period_after(D(2026, 2, 14)).period_start, D(2026, 4, 1))

    def test_first_open_period_after_creates_the_next_month(self):
        self.assertFalse(FinancialPeriod.objects.filter(year=2026, month=9).exists())
        p = first_open_period_after(D(2026, 8, 31))
        self.assertEqual((p.year, p.month, p.status), (2026, 9, 'open'))

    def test_first_open_period_after_ignores_the_month_itself_and_stops_at_a_gap(self):
        _set_status(D(2026, 7, 1), 'open')   # July exists and is open; June is missing
        self.assertEqual(first_open_period_after(D(2026, 5, 1)).period_start, D(2026, 6, 1))


class ClosingGuardTests(Base):
    def test_approve_into_closing_period_refused_unless_close_service(self):
        entry = save_draft(user=self.staff, entry_date=D(2026, 3, 31), description='x', lines=_lines('10.00'))
        _set_status(D(2026, 3, 31), 'closing')
        with self.assertRaises(LedgerError) as cm:
            approve(entry.id, user=self.staff)
        self.assertEqual(cm.exception.code, 'period_closing')
        self.assertEqual(cm.exception.message, 'الفترة قيد الإقفال')
        entry.refresh_from_db()
        self.assertEqual(entry.status, 'draft')
        self.assertEqual(approve(entry.id, user=self.staff, _close_service=True).status, 'approved')

    def test_close_service_does_not_open_a_closed_period(self):
        entry = save_draft(user=self.staff, entry_date=D(2026, 3, 31), description='x', lines=_lines('10.00'))
        _set_status(D(2026, 3, 31), 'closed')
        with self.assertRaises(LedgerError) as cm:
            approve(entry.id, user=self.staff, _close_service=True)
        self.assertEqual(cm.exception.code, 'closed_period')


class ReverseClosedMonthTests(Base):
    def test_reverse_of_closed_month_entry_lands_in_first_open_month(self):
        orig = self.original()
        _set_status(D(2026, 3, 1), 'closed')
        mirror = reverse(orig.id, user=self.staff, reason='خطأ')
        orig.refresh_from_db()
        self.assertEqual(orig.status, 'reversed')
        self.assertEqual(mirror.entry_date, D(2026, 4, 1))
        self.assertEqual((mirror.period.year, mirror.period.month), (2026, 4))
        self.assertEqual(mirror.corrects_id, orig.id)
        self.assertEqual(mirror.reverses_id, orig.id)

    def test_reverse_explicit_date_in_non_open_period_refused(self):
        orig = self.original()
        with self.assertRaises(LedgerError) as cm:
            reverse(orig.id, user=self.staff, reason='خطأ', entry_date=D(2026, 2, 20))
        self.assertEqual(cm.exception.code, 'closed_period')
        orig.refresh_from_db()
        self.assertEqual(orig.status, 'approved')

    def test_reverse_explicit_open_date_of_closed_month_entry_still_marks_corrects(self):
        orig = self.original()
        mirror = reverse(orig.id, user=self.staff, reason='خطأ', entry_date=D(2026, 6, 15))
        self.assertEqual((mirror.entry_date, mirror.corrects_id), (D(2026, 6, 15), orig.id))

    def test_reverse_in_open_month_has_no_corrects(self):
        orig = self.original(close=False)
        mirror = reverse(orig.id, user=self.staff, reason='خطأ')
        self.assertEqual((mirror.entry_date, mirror.corrects_id), (orig.entry_date, None))


class ReverseWithCorrectionsTests(Base):
    def test_refused_with_an_approved_correction_then_allowed_after_reversing_it(self):
        orig = self.original()
        fix = approve(self.correct(orig, '1100.00').id, user=self.staff)
        with self.assertRaises(LedgerError) as cm:
            reverse(orig.id, user=self.staff, reason='خطأ')
        self.assertEqual(cm.exception.code, 'has_corrections')
        self.assertEqual(cm.exception.message, 'القيد ده عليه تصحيحات، اعكس التصحيحات الأول')
        orig.refresh_from_db()
        self.assertEqual(orig.status, 'approved')
        reverse(fix.id, user=self.staff, reason='خطأ')
        self.assertEqual(reverse(orig.id, user=self.staff, reason='خطأ').reverses_id, orig.id)
        orig.refresh_from_db()
        self.assertEqual(orig.status, 'reversed')
        self.assertEqual(effective_lines(orig), {})

    def test_refused_with_a_draft_correction(self):
        orig = self.original()
        self.correct(orig, '1100.00')
        with self.assertRaises(LedgerError) as cm:
            reverse(orig.id, user=self.staff, reason='خطأ')
        self.assertEqual(cm.exception.code, 'has_corrections')


class EffectiveLinesTests(Base):
    KEY_DR, KEY_CR = (EXPENSE, None, ''), (PAYABLE, None, '')

    def test_original_alone(self):
        self.assertEqual(effective_lines(self.original()),
                         {self.KEY_DR: DEC('1000.00'), self.KEY_CR: DEC('-1000.00')})

    def test_draft_correction_does_not_count(self):
        orig = self.original()
        self.correct(orig, '1100.00')
        self.assertEqual(effective_lines(orig)[self.KEY_DR], DEC('1000.00'))

    def test_approved_correction_counts_once(self):
        orig = self.original()
        approve(self.correct(orig, '1100.00').id, user=self.staff)
        self.assertEqual(effective_lines(orig),
                         {self.KEY_DR: DEC('1100.00'), self.KEY_CR: DEC('-1100.00')})

    def test_reversed_original_nets_to_nothing(self):
        """The original's own status is 'reversed'; its mirror (corrects=original) cancels it."""
        orig = self.original()
        reverse(orig.id, user=self.staff, reason='خطأ')
        orig.refresh_from_db()
        self.assertEqual(orig.status, 'reversed')
        self.assertEqual(effective_lines(orig), {})

    def test_original_reversed_while_its_month_was_open_nets_to_nothing(self):
        """That mirror has no corrects link, and the month closed later."""
        orig = self.original(close=False)
        reverse(orig.id, user=self.staff, reason='خطأ')
        _set_status(orig.entry_date, 'closed')
        orig.refresh_from_db()
        self.assertEqual(effective_lines(orig), {})

    def test_reversed_correction_in_open_month_nets_out(self):
        orig = self.original()
        fix = approve(self.correct(orig, '1100.00').id, user=self.staff)
        reverse(fix.id, user=self.staff, reason='خطأ')
        self.assertEqual(effective_lines(orig)[self.KEY_DR], DEC('1000.00'))

    def test_reversed_correction_after_its_month_closed_nets_out(self):
        orig = self.original()
        fix = approve(self.correct(orig, '1100.00').id, user=self.staff)
        _set_status(fix.entry_date, 'closed')
        mirror = reverse(fix.id, user=self.staff, reason='خطأ')
        self.assertEqual(mirror.corrects_id, fix.id)   # points at the correction, not the original
        self.assertEqual(effective_lines(orig)[self.KEY_DR], DEC('1000.00'))
        fix.refresh_from_db()
        self.assertEqual(effective_lines(fix), {})


class LateCorrectionTests(Base):
    def test_correction_contains_only_the_net_difference(self):
        orig = self.original()
        fix = self.correct(orig, '1100.00', reason='فاتورة معدلة')
        self.assertEqual(fix.status, 'draft')
        self.assertEqual(fix.entry_date, D(2026, 3, 1))
        self.assertEqual(self.amounts(fix), [(EXPENSE, DEC('100.00'), DEC('0.00')),
                                             (PAYABLE, DEC('0.00'), DEC('100.00'))])
        self.assertEqual((fix.book, fix.source_type, fix.corrects_id), ('cash', 'expenses', orig.id))
        self.assertEqual(fix.source_key, 'doc-1#corr:2026-03:1')
        self.assertEqual(fix.description, f'تصحيح قيد {orig.number} — فاتورة معدلة')
        log = AuditLog.objects.get(action='gl_late_correction_drafted', object_id=str(fix.id))
        self.assertEqual(log.user_id, self.staff.id)
        self.assertEqual(log.new_data['corrects'], orig.id)

    def test_second_correction_nets_against_original_plus_first(self):
        orig = self.original()
        approve(self.correct(orig, '1100.00').id, user=self.staff)
        second = self.correct(orig, '1050.00')
        self.assertEqual(self.amounts(second), [(PAYABLE, DEC('50.00'), DEC('0.00')),
                                                (EXPENSE, DEC('0.00'), DEC('50.00'))])
        self.assertEqual(second.source_key, 'doc-1#corr:2026-03:2')

    def test_correction_refused_while_an_earlier_one_is_still_a_draft(self):
        """Only approved corrections net, so a second one now would count the difference twice."""
        orig = self.original()
        self.correct(orig, '1100.00')
        with self.assertRaises(LedgerError) as cm:
            self.correct(orig, '1050.00')
        self.assertEqual(cm.exception.code, 'correction_pending')
        self.assertEqual(orig.corrections.count(), 1)

    def test_correction_refused_when_original_period_open(self):
        orig = self.original(close=False)
        with self.assertRaises(LedgerError) as cm:
            self.correct(orig, '1100.00')
        self.assertEqual(cm.exception.code, 'period_open')

    def test_nothing_to_correct(self):
        orig = self.original()
        with self.assertRaises(LedgerError) as cm:
            self.correct(orig, '1000.00')
        self.assertEqual(cm.exception.code, 'nothing_to_correct')
        self.assertFalse(orig.corrections.exists())

    def test_lines_aggregate_by_account_branch_party(self):
        orig = self.original()
        lines = [{'account_code': EXPENSE, 'debit': '600.00', 'credit': '0'},
                 {'account_code': EXPENSE, 'debit': '500.00', 'credit': '0'},
                 {'account_code': PAYABLE, 'debit': '0', 'credit': '1100.00'}]
        fix = post_late_correction(orig.id, lines, user=self.staff, reason='x')
        self.assertEqual(self.amounts(fix), [(EXPENSE, DEC('100.00'), DEC('0.00')),
                                             (PAYABLE, DEC('0.00'), DEC('100.00'))])

    def test_correction_of_a_reversed_original_posts_the_whole_lines(self):
        orig = self.original()
        reverse(orig.id, user=self.staff, reason='خطأ')
        fix = self.correct(orig, '900.00')
        self.assertEqual(self.amounts(fix), [(EXPENSE, DEC('900.00'), DEC('0.00')),
                                             (PAYABLE, DEC('0.00'), DEC('900.00'))])

    def test_correction_refused_for_draft_reversal_and_correction_originals(self):
        draft = save_draft(user=self.staff, entry_date=D(2026, 2, 10), description='x', lines=_lines('5.00'))
        orig = self.original(close=False)
        other = self.original(source_key='doc-2')
        fix = approve(self.correct(orig, '1100.00').id, user=self.staff)
        mirror = reverse(other.id, user=self.staff, reason='x')
        for entry, code in ((draft, 'original_is_draft'), (mirror, 'is_reversal'), (fix, 'is_correction')):
            with self.assertRaises(LedgerError) as cm:
                self.correct(entry, '1.00')
            self.assertEqual(cm.exception.code, code)

    def test_manual_originals_do_not_collide_on_an_empty_source_key(self):
        one = self.original(source_key='', close=False)
        two = self.original(source_key='', amount='7.00')
        self.assertNotEqual(self.correct(one, '1100.00').source_key, self.correct(two, '8.00').source_key)

    def test_editing_a_correction_draft_keeps_the_link(self):
        orig = self.original()
        fix = self.correct(orig, '1100.00')
        fix = save_draft(user=self.staff, entry=fix, entry_date=fix.entry_date, book=fix.book,
                         description=fix.description, lines=_lines('150.00'),
                         source_type=fix.source_type, source_key=fix.source_key)
        self.assertEqual(LedgerEntry.objects.get(pk=fix.pk).corrects_id, orig.id)


class ExceptionCorrectionTests(Base):
    def test_correction_resolves_exception(self):
        orig = self.original()
        change = plan2_adapter.ClosedPeriodChange(
            exception_id=77, status='open', original_entry=orig, draft_entry_id=orig.id,
            source_date=orig.entry_date, group_key='grp', member_source_keys=['a', 'b'])
        with mock.patch.object(corrections, 'plan2_adapter') as adapter:
            adapter.closed_period_change.return_value = change
            fix = self.correct(orig, '1100.00', exception_id=77)
        adapter.closed_period_change.assert_called_once_with(77, for_update=True)
        adapter.mark_exception_resolved.assert_called_once_with(77, user=self.staff, entry=fix)
        self.assertEqual(fix.source_key, 'grp#corr:exc77')

    def test_group_exception_posts_one_correction_keyed_by_group_key(self):
        orig = self.original()
        exc = self.exception(original=orig, entry_id=orig.id)
        fix = post_late_correction(orig.id, exc.proposed_lines, user=self.staff, reason='x',
                                   exception_id=exc.id)
        self.assertTrue(fix.source_key.startswith(exc.detail['group_key']))
        self.assertEqual(fix.source_key, f'{exc.detail["group_key"]}#corr:exc{exc.id}')
        self.assertEqual(self.amounts(fix)[0], (EXPENSE, DEC('100.00'), DEC('0.00')))
        exc.refresh_from_db()
        self.assertEqual((exc.status, exc.resolved_by_id), ('resolved', self.staff.id))
        log = AuditLog.objects.get(action='gl_late_correction_drafted', object_id=str(fix.id))
        self.assertEqual(log.extra['group_key'], exc.detail['group_key'])
        self.assertEqual(log.extra['member_source_keys'], ['t1', 't2', 't3'])
        self.assertEqual(log.old_data, {'exception_status': 'open'})
        self.assertEqual(log.new_data['exception_status'], 'resolved')
        with self.assertRaises(LedgerError) as cm:
            post_late_correction(orig.id, exc.proposed_lines, user=self.staff, reason='x',
                                 exception_id=exc.id)
        self.assertEqual(cm.exception.code, 'exception_not_open')
        self.assertEqual(orig.corrections.count(), 1)

    def test_exception_with_live_draft_refused(self):
        day = D(2026, 2, 10)
        draft = save_draft(user=self.staff, entry_date=day, description='x', lines=_lines('5.00'))
        orig = self.original()
        exc = self.exception(original=orig, entry_id=draft.id)
        n = LedgerEntry.objects.count()
        with self.assertRaises(LedgerError) as cm:
            post_late_correction(orig.id, exc.proposed_lines, user=self.staff, reason='x', exception_id=exc.id)
        self.assertEqual(cm.exception.code, 'exception_has_draft')
        self.assertEqual(LedgerEntry.objects.count(), n)
        exc.refresh_from_db()
        self.assertEqual(exc.status, 'open')

    def test_exception_for_another_entry_refused(self):
        orig = self.original(close=False)
        other = self.original(source_key='doc-2')
        exc = self.exception(original=other, entry_id=other.id)
        with self.assertRaises(LedgerError) as cm:
            post_late_correction(orig.id, exc.proposed_lines, user=self.staff, reason='x', exception_id=exc.id)
        self.assertEqual(cm.exception.code, 'exception_mismatch')

    def test_failed_correction_leaves_the_exception_open(self):
        orig = self.original()
        exc = self.exception(original=orig, entry_id=orig.id, lines=_lines('1000.00'))
        with self.assertRaises(LedgerError) as cm:
            post_late_correction(orig.id, exc.proposed_lines, user=self.staff, reason='x', exception_id=exc.id)
        self.assertEqual(cm.exception.code, 'nothing_to_correct')
        exc.refresh_from_db()
        self.assertEqual(exc.status, 'open')


class LateDocumentTests(Base):
    def rule(self):
        return PostingRule.objects.create(code='late-doc', source_type='expenses', book='credit',
                                          effective_from=D(2026, 1, 1))

    def test_new_document_in_closed_month_drafted_in_first_open_month(self):
        _set_status(D(2026, 2, 1), 'closed')
        _set_status(D(2026, 3, 1), 'closed')
        exc = self.exception(rule=self.rule())
        entry = post_late_document(exc.id, user=self.staff)
        self.assertEqual((entry.status, entry.entry_date), ('draft', D(2026, 4, 1)))
        self.assertEqual(entry.source_key, exc.detail['group_key'])
        self.assertEqual((entry.book, entry.source_type), ('credit', 'expenses'))
        self.assertIsNone(entry.corrects_id)
        self.assertIn('2026-02-10', entry.description)
        self.assertEqual(self.amounts(entry), [(EXPENSE, DEC('1100.00'), DEC('0.00')),
                                               (PAYABLE, DEC('0.00'), DEC('1100.00'))])
        exc.refresh_from_db()
        self.assertEqual(exc.status, 'resolved')
        log = AuditLog.objects.get(action='gl_late_document_drafted', object_id=str(entry.id))
        self.assertEqual(log.extra['member_source_keys'], ['t1', 't2', 't3'])
        with self.assertRaises(LedgerError) as cm:
            post_late_document(exc.id, user=self.staff)
        self.assertEqual(cm.exception.code, 'exception_not_open')
        self.assertEqual(LedgerEntry.objects.filter(source_key=exc.detail['group_key']).count(), 1)

    def test_second_exception_for_the_same_group_hits_source_conflict(self):
        _set_status(D(2026, 2, 1), 'closed')
        exc = self.exception(keys=('t1',))
        post_late_document(exc.id, user=self.staff)
        exc2 = self.exception(keys=('t2',))
        with self.assertRaises(LedgerError) as cm:
            post_late_document(exc2.id, user=self.staff)
        self.assertEqual(cm.exception.code, 'source_conflict')
        exc2.refresh_from_db()
        self.assertEqual(exc2.status, 'open')

    def test_refused_with_original_or_live_draft(self):
        orig = self.original()
        exc = self.exception(original=orig, entry_id=orig.id)
        with self.assertRaises(LedgerError) as cm:
            post_late_document(exc.id, user=self.staff)
        self.assertEqual(cm.exception.code, 'exception_has_original')
        draft = save_draft(user=self.staff, entry_date=D(2026, 2, 10), description='x', lines=_lines('5.00'))
        exc2 = self.exception(entry_id=draft.id, keys=('d1',), group_key='g2')
        with self.assertRaises(LedgerError) as cm:
            post_late_document(exc2.id, user=self.staff)
        self.assertEqual(cm.exception.code, 'exception_has_draft')

    def test_refused_when_the_month_is_open_again(self):
        exc = self.exception()
        with self.assertRaises(LedgerError) as cm:
            post_late_document(exc.id, user=self.staff)
        self.assertEqual(cm.exception.code, 'period_open')

    def test_empty_proposal_refused(self):
        _set_status(D(2026, 2, 1), 'closed')
        exc = self.exception(lines=[])
        with self.assertRaises(LedgerError) as cm:
            post_late_document(exc.id, user=self.staff)
        self.assertEqual(cm.exception.code, 'empty')
