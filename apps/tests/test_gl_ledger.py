"""General Ledger service: drafts, approval, reversal (finance-gl Task 3)."""
import datetime
import threading
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase, TransactionTestCase

from apps.audit.models import AuditLog
from apps.branches.models import Branch
from apps.finance.models import (
    FinancialPeriod, GLAccountGroup, GLAccount, LedgerEntry, GLSequence,
)
from apps.users.models import StaffProfile
from core.threads import start_thread

D = datetime.date


def _make_fixtures(obj):
    obj.user = User.objects.create_user(username='gl_led_u', password='x')
    obj.staff, _ = StaffProfile.objects.get_or_create(user=obj.user)
    obj.user2 = User.objects.create_user(username='gl_led_u2', password='x')
    obj.staff2, _ = StaffProfile.objects.get_or_create(user=obj.user2)
    obj.group = GLAccountGroup.objects.create(name='نقدية', section='balance_sheet', order=1)
    obj.cash = GLAccount.objects.create(
        code='1101', name='الخزينة', group=obj.group, nature='debit', account_type='asset')
    obj.sales = GLAccount.objects.create(
        code='4101', name='المبيعات', group=obj.group, nature='credit', account_type='revenue')
    obj.supplier = GLAccount.objects.create(
        code='2101', name='الموردون', group=obj.group, nature='credit', account_type='liability',
        party_type='supplier', requires_party=True)


def _lines(amount='100.00', debit_acc='1101', credit_acc='4101', **extra):
    return [
        {'account_code': debit_acc, 'debit': Decimal(amount), 'credit': Decimal('0'), **extra},
        {'account_code': credit_acc, 'debit': Decimal('0'), 'credit': Decimal(amount)},
    ]


class LedgerServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        _make_fixtures(cls)

    def _draft(self, lines=None, entry_date=D(2026, 11, 4), **kw):
        from apps.finance.gl.ledger import save_draft
        return save_draft(user=self.staff, entry_date=entry_date, description='اختبار',
                          lines=lines if lines is not None else _lines(), **kw)

    def test_draft_may_be_unbalanced_but_approve_refuses(self):
        from apps.finance.gl.ledger import approve, LedgerError
        lines = _lines()
        lines[1]['credit'] = Decimal('90.00')
        e = self._draft(lines)
        self.assertEqual(e.status, 'draft')
        self.assertEqual(e.lines.count(), 2)
        self.assertEqual(e.period.year, 2026)
        self.assertEqual(e.period.month, 11)
        with self.assertRaises(LedgerError) as cm:
            approve(e.id, user=self.staff)
        self.assertEqual(cm.exception.code, 'unbalanced')
        self.assertTrue(cm.exception.message)
        e.refresh_from_db()
        self.assertEqual(e.status, 'draft')
        self.assertIsNone(e.number)

    def test_three_decimal_amount_rejected(self):
        from apps.finance.gl.ledger import LedgerError
        with self.assertRaises(LedgerError) as cm:
            self._draft(_lines(amount='10.005'))
        self.assertEqual(cm.exception.code, 'bad_amount')

    def test_negative_amount_rejected(self):
        from apps.finance.gl.ledger import LedgerError
        lines = _lines()
        lines[0]['debit'] = Decimal('-100.00')
        with self.assertRaises(LedgerError) as cm:
            self._draft(lines)
        self.assertEqual(cm.exception.code, 'bad_amount')

    def test_both_sides_or_zero_line_rejected(self):
        from apps.finance.gl.ledger import LedgerError
        lines = _lines()
        lines[0]['credit'] = Decimal('5')
        with self.assertRaises(LedgerError) as cm:
            self._draft(lines)
        self.assertEqual(cm.exception.code, 'bad_amount')
        lines = _lines()
        lines[0]['debit'] = Decimal('0')
        with self.assertRaises(LedgerError) as cm:
            self._draft(lines)
        self.assertEqual(cm.exception.code, 'bad_amount')

    def test_empty_draft_saved_but_approve_refuses(self):
        from apps.finance.gl.ledger import approve, LedgerError
        e = self._draft([])
        with self.assertRaises(LedgerError) as cm:
            approve(e.id, user=self.staff)
        self.assertEqual(cm.exception.code, 'empty')

    def test_inactive_and_non_posting_accounts_rejected(self):
        from apps.finance.gl.ledger import LedgerError
        GLAccount.objects.filter(code='4101').update(is_active=False)
        with self.assertRaises(LedgerError) as cm:
            self._draft()
        self.assertEqual(cm.exception.code, 'inactive_account')
        GLAccount.objects.filter(code='4101').update(is_active=True, is_posting=False)
        with self.assertRaises(LedgerError) as cm:
            self._draft()
        self.assertEqual(cm.exception.code, 'non_posting_account')

    def test_approve_assigns_sequential_numbers(self):
        from apps.finance.gl.ledger import approve
        a = approve(self._draft().id, user=self.staff)
        b = approve(self._draft().id, user=self.staff)
        self.assertEqual(a.number, 'JV-2026-000001')
        self.assertEqual(b.number, 'JV-2026-000002')
        self.assertEqual(a.status, 'approved')
        self.assertEqual(GLSequence.objects.get(year=2026).last, 2)

    def test_before_opening_refused(self):
        from apps.finance.gl.ledger import approve, LedgerError
        periods = FinancialPeriod.objects.count()
        with self.assertRaises(LedgerError) as cm:
            self._draft(entry_date=D(2025, 12, 31))
        self.assertEqual(cm.exception.code, 'before_opening')
        self.assertEqual(FinancialPeriod.objects.count(), periods)   # no old period created
        # approve keeps its own guard (a draft only the workbook reproducer may date back)
        e = self._draft(entry_date=D(2025, 12, 31), _allow_before_opening=True)
        with self.assertRaises(LedgerError) as cm:
            approve(e.id, user=self.staff)
        self.assertEqual(cm.exception.code, 'before_opening')

    def test_closed_period_refused(self):
        from apps.finance.gl.ledger import approve, LedgerError
        e = self._draft()
        FinancialPeriod.objects.filter(pk=e.period_id).update(status='closed', is_closed=True)
        with self.assertRaises(LedgerError) as cm:
            approve(e.id, user=self.staff)
        self.assertEqual(cm.exception.code, 'closed_period')
        e.refresh_from_db()
        self.assertEqual(e.status, 'draft')
        self.assertFalse(GLSequence.objects.filter(year=2026, last__gt=0).exists())

    def test_self_approval_allowed_and_audited(self):
        from apps.finance.gl.ledger import approve
        e = self._draft()
        e = approve(e.id, user=self.staff)
        self.assertEqual(e.created_by_id, self.staff.id)
        self.assertEqual(e.approved_by_id, self.staff.id)
        self.assertIsNotNone(e.approved_at)
        log = AuditLog.objects.get(action='gl_entry_approved', object_id=str(e.id))
        self.assertEqual(log.user_id, self.staff.id)
        self.assertEqual(log.new_data['created_by'], self.staff.id)
        self.assertEqual(log.new_data['approved_by'], self.staff.id)
        self.assertEqual(log.new_data['number'], 'JV-2026-000001')
        self.assertTrue(AuditLog.objects.filter(action='gl_entry_draft_saved',
                                                object_id=str(e.id)).exists())

    def test_reverse_mirrors_lines_and_marks_original(self):
        from apps.finance.gl.ledger import approve, reverse
        lines = _lines(amount='250.50', party_code='', description='سطر')
        orig = approve(self._draft(lines, source_type='test', source_key='src-1').id,
                       user=self.staff)
        mirror = reverse(orig.id, user=self.staff2, reason='خطأ في القيد')
        orig.refresh_from_db()
        self.assertEqual(orig.status, 'reversed')
        self.assertEqual(mirror.status, 'approved')
        self.assertEqual(mirror.reverses_id, orig.id)
        self.assertEqual(mirror.source_type, 'reversal')
        self.assertEqual(mirror.source_key, '')
        self.assertEqual(mirror.book, orig.book)
        self.assertEqual(mirror.entry_date, orig.entry_date)
        self.assertEqual(mirror.number, 'JV-2026-000002')
        self.assertEqual(mirror.approved_by_id, self.staff2.id)
        o_lines = list(orig.lines.order_by('line_no'))
        m_lines = list(mirror.lines.order_by('line_no'))
        self.assertEqual(len(o_lines), len(m_lines))
        for o, m in zip(o_lines, m_lines):
            self.assertEqual(o.account_id, m.account_id)
            self.assertEqual(o.debit, m.credit)
            self.assertEqual(o.credit, m.debit)
        self.assertTrue(AuditLog.objects.filter(action='gl_entry_reversed',
                                                object_id=str(orig.id)).exists())
        # the original's source key is free again for a corrected re-draft
        again = self._draft(source_type='test', source_key='src-1')
        self.assertEqual(again.status, 'draft')

    def test_reverse_twice_refused(self):
        from apps.finance.gl.ledger import approve, reverse, LedgerError
        orig = approve(self._draft().id, user=self.staff)
        reverse(orig.id, user=self.staff, reason='x')
        with self.assertRaises(LedgerError) as cm:
            reverse(orig.id, user=self.staff, reason='x')
        self.assertEqual(cm.exception.code, 'already_reversed')

    def test_reverse_of_reversal_refused(self):
        from apps.finance.gl.ledger import approve, reverse, LedgerError
        orig = approve(self._draft().id, user=self.staff)
        mirror = reverse(orig.id, user=self.staff, reason='x')
        with self.assertRaises(LedgerError) as cm:
            reverse(mirror.id, user=self.staff, reason='x')
        self.assertEqual(cm.exception.code, 'is_reversal')

    def test_reverse_of_draft_refused(self):
        from apps.finance.gl.ledger import reverse, LedgerError
        e = self._draft()
        with self.assertRaises(LedgerError) as cm:
            reverse(e.id, user=self.staff, reason='x')
        self.assertEqual(cm.exception.code, 'not_approved')
        self.assertNotEqual(LedgerEntry.objects.get(pk=e.pk).status, 'reversed')

    def test_reverse_into_closed_period_refused(self):
        # no explicit date: Plan 3 dates it in the first open month (test_gl_corrections)
        from apps.finance.gl.ledger import approve, reverse, LedgerError
        orig = approve(self._draft().id, user=self.staff)
        FinancialPeriod.objects.filter(pk=orig.period_id).update(status='closed', is_closed=True)
        with self.assertRaises(LedgerError) as cm:
            reverse(orig.id, user=self.staff, reason='x', entry_date=orig.entry_date)
        self.assertEqual(cm.exception.code, 'closed_period')
        orig.refresh_from_db()
        self.assertEqual(orig.status, 'approved')

    def test_approved_entry_not_editable_via_save_draft(self):
        from apps.finance.gl.ledger import approve, save_draft, LedgerError
        e = approve(self._draft().id, user=self.staff)
        with self.assertRaises(LedgerError) as cm:
            save_draft(user=self.staff, entry_date=D(2026, 11, 5), description='تعديل',
                       lines=_lines(amount='5.00'), entry=e)
        self.assertEqual(cm.exception.code, 'not_draft')
        e.refresh_from_db()
        self.assertEqual(e.entry_date, D(2026, 11, 4))
        self.assertEqual(e.lines.first().debit, Decimal('100.00'))

    def test_save_draft_replaces_lines(self):
        from apps.finance.gl.ledger import save_draft
        e = self._draft()
        e2 = save_draft(user=self.staff, entry_date=D(2026, 10, 2), description='معدل',
                        lines=_lines(amount='7.25'), entry=e)
        self.assertEqual(e2.pk, e.pk)
        self.assertEqual(e2.period.month, 10)
        self.assertEqual(list(e2.lines.values_list('debit', flat=True).order_by('line_no')),
                         [Decimal('7.25'), Decimal('0.00')])

    def test_source_conflict(self):
        from apps.finance.gl.ledger import LedgerError
        self._draft(source_type='test', source_key='dup')
        with self.assertRaises(LedgerError) as cm:
            self._draft(source_type='test', source_key='dup')
        self.assertEqual(cm.exception.code, 'source_conflict')

    def test_party_required_when_account_demands_it(self):
        from apps.finance.gl.ledger import approve, LedgerError
        e = self._draft(_lines(debit_acc='2101'))
        with self.assertRaises(LedgerError) as cm:
            approve(e.id, user=self.staff)
        self.assertEqual(cm.exception.code, 'party_required')
        ok = self._draft(_lines(debit_acc='2101', party_code='S-565'))
        self.assertEqual(approve(ok.id, user=self.staff).status, 'approved')

    def test_branch_required_when_account_demands_it(self):
        from apps.finance.gl.ledger import approve, LedgerError
        GLAccount.objects.filter(code='1101').update(requires_branch=True)
        e = self._draft()
        with self.assertRaises(LedgerError) as cm:
            approve(e.id, user=self.staff)
        self.assertEqual(cm.exception.code, 'branch_required')

    def test_audit_failure_rolls_back_approval(self):
        from apps.finance.gl.ledger import approve
        e = self._draft()
        with mock.patch.object(AuditLog, 'save', side_effect=RuntimeError('audit down')):
            with self.assertRaises(RuntimeError):
                approve(e.id, user=self.staff)
        e.refresh_from_db()
        self.assertEqual(e.status, 'draft')
        self.assertIsNone(e.number)
        self.assertIsNone(e.approved_by_id)
        self.assertFalse(GLSequence.objects.filter(year=2026, last__gt=0).exists())
        self.assertFalse(AuditLog.objects.filter(action='gl_entry_approved').exists())
        # the transaction is healthy afterwards: approval works once audit is back
        self.assertEqual(approve(e.id, user=self.staff).number, 'JV-2026-000001')

    def test_audit_failure_rolls_back_draft(self):
        with mock.patch.object(AuditLog, 'save', side_effect=RuntimeError('audit down')):
            with self.assertRaises(RuntimeError):
                self._draft(source_type='test', source_key='audit-fail')
        self.assertFalse(LedgerEntry.objects.filter(source_key='audit-fail').exists())

    def test_reversal_mirror_has_own_audit_row(self):
        from apps.finance.gl.ledger import approve, reverse
        orig = approve(self._draft().id, user=self.staff)
        mirror = reverse(orig.id, user=self.staff2, reason='قيد مكرر')
        log = AuditLog.objects.get(action='gl_entry_reversal_created', object_id=str(mirror.id))
        self.assertEqual(log.model_name, 'LedgerEntry')
        self.assertEqual(log.user_id, self.staff2.id)
        self.assertEqual(log.new_data['number'], mirror.number)
        self.assertEqual(log.new_data['reverses'], orig.id)
        self.assertEqual(len(log.new_data['lines']), 2)
        self.assertEqual(log.extra['reason'], 'قيد مكرر')
        orig_log = AuditLog.objects.get(action='gl_entry_reversed', object_id=str(orig.id))
        self.assertEqual(orig_log.new_data['status'], 'reversed')

    def test_unknown_branch_rejected(self):
        from apps.finance.gl.ledger import LedgerError
        branch = Branch.objects.create(softech_branch_id='979', name='GL test')
        ok = self._draft(_lines(branch_id=branch.id))
        self.assertEqual(ok.lines.get(line_no=1).branch_id, branch.id)
        missing = Branch.objects.order_by('-pk').values_list('pk', flat=True).first() + 1000
        with self.assertRaises(LedgerError) as cm:
            self._draft(_lines(branch_id=missing))
        self.assertEqual(cm.exception.code, 'bad_branch')
        self.assertTrue(cm.exception.message)
        with self.assertRaises(LedgerError) as cm:
            self._draft(_lines(branch_id='abc'))
        self.assertEqual(cm.exception.code, 'bad_branch')

    def test_reverse_before_original_refused(self):
        from apps.finance.gl.ledger import approve, reverse, LedgerError
        orig = approve(self._draft(entry_date=D(2026, 11, 10)).id, user=self.staff)
        with self.assertRaises(LedgerError) as cm:
            reverse(orig.id, user=self.staff, reason='x', entry_date=D(2026, 11, 9))
        self.assertEqual(cm.exception.code, 'reverse_before_original')
        self.assertTrue(cm.exception.message)
        orig.refresh_from_db()
        self.assertEqual(orig.status, 'approved')
        later = reverse(orig.id, user=self.staff, reason='x', entry_date=D(2026, 11, 12))
        self.assertEqual(later.entry_date, D(2026, 11, 12))

    def test_reverse_clears_deactivated_account(self):
        from apps.finance.gl.ledger import approve, reverse
        orig = approve(self._draft().id, user=self.staff)
        GLAccount.objects.filter(code='4101').update(is_active=False)
        self.assertEqual(reverse(orig.id, user=self.staff, reason='x').status, 'approved')


class LedgerConcurrencyTests(TransactionTestCase):
    def setUp(self):
        _make_fixtures(self)

    def test_concurrent_approve_single_number(self):
        from apps.finance.gl.ledger import save_draft, approve, LedgerError
        e = save_draft(user=self.staff, entry_date=D(2026, 11, 4), description='تزامن',
                       lines=_lines())
        barrier = threading.Barrier(2)
        results, errors = [], []

        def worker():
            try:
                barrier.wait(timeout=10)
                results.append(approve(e.id, user=self.staff).number)
            except LedgerError as exc:
                errors.append(exc.code)
            except Exception as exc:  # pragma: no cover - surfaced by the asserts
                errors.append(repr(exc))
            finally:
                connection.close()

        threads = [start_thread(worker, daemon=False) for _ in range(2)]
        for t in threads:
            t.join(timeout=30)
        self.assertEqual(results, ['JV-2026-000001'])
        self.assertEqual(errors, ['not_draft'])
        self.assertEqual(GLSequence.objects.get(year=2026).last, 1)
