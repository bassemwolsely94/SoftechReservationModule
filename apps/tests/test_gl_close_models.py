"""Close and comparison models, account feed, Plan 2 adapter (finance-gl Plan 3, Task 1)."""
import datetime
from decimal import Decimal

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase
from django.utils import timezone

from apps.finance.gl import plan2_adapter
from apps.finance.models import (
    ClosingStockSnapshot, ClosingStockStore, FinancialPeriod, GLAccount, GLAccountGroup,
    GLComparisonLine, GLDraftRun, GLParty, GLSoftechCheck, GLSourceDoc, LedgerEntry,
    SourceException,
)
from apps.users.models import StaffProfile

D = datetime.date


def _fixtures(obj):
    obj.user = User.objects.create_user(username='gl_close_u', password='x')
    obj.staff, _ = StaffProfile.objects.get_or_create(user=obj.user)
    obj.period = FinancialPeriod.objects.create(
        year=2031, month=3, period_type='month', period_start=D(2031, 3, 1),
        period_end=D(2031, 3, 31), label='2031-03')
    obj.group = GLAccountGroup.objects.create(name='مبيعات', section='income', order=1)


def _entry(obj, **kw):
    vals = dict(entry_date=D(2031, 3, 5), period=obj.period, book='general', created_by=obj.staff)
    vals.update(kw)
    return LedgerEntry.objects.create(**vals)


class CloseModelsTests(TestCase):
    def setUp(self):
        _fixtures(self)
        self.check = GLSoftechCheck.objects.create(
            key='t1_sales', label='المبيعات', kind='movement', source='sales', sign='credit')

    def test_comparison_line_unique_per_period_check_branch_party(self):
        kw = dict(period=self.period, softech_check=self.check, party_code='',
                  ledger_amount=Decimal('10'), softech_amount=Decimal('10'), difference=Decimal('0'))
        GLComparisonLine.objects.create(**kw)
        with self.assertRaises(IntegrityError), transaction.atomic():
            GLComparisonLine.objects.create(**kw)
        GLComparisonLine.objects.create(**{**kw, 'party_code': 'S1'})

    def test_needs_explanation_when_difference_changes_after_explaining(self):
        line = GLComparisonLine.objects.create(
            period=self.period, softech_check=self.check, ledger_amount=Decimal('100'),
            softech_amount=Decimal('90'), difference=Decimal('10.00'))
        self.assertTrue(line.needs_explanation)
        line.explanation = 'فرق توقيت'
        line.explained_difference = Decimal('10.00')
        self.assertFalse(line.needs_explanation)
        line.difference = Decimal('12.00')
        self.assertTrue(line.needs_explanation)
        line.difference = Decimal('0.50')
        line.explanation = ''
        line.explained_difference = None
        self.assertFalse(line.needs_explanation)

    def test_account_feed_defaults_auto(self):
        acc = GLAccount.objects.create(
            code='4101', name='المبيعات', group=self.group, nature='credit', account_type='revenue')
        self.assertEqual(acc.feed, 'auto')

    def test_entry_corrects_protects_original(self):
        original = _entry(self)
        corr = _entry(self, corrects=original)
        self.assertEqual(list(original.corrections.all()), [corr])
        with self.assertRaises(ProtectedError):
            original.delete()

    def test_period_closing_stock_link(self):
        snap = ClosingStockSnapshot.objects.create(
            period=self.period, as_of=D(2031, 3, 31), total=Decimal('500.00'),
            excluded_total=Decimal('0'), read_by=self.staff)
        ClosingStockStore.objects.create(
            snapshot=snap, store_code='101', store_name='مخزن', included=True, rows=3,
            value=Decimal('500.00'), snapshot_date=D(2031, 3, 30), carried=True)
        self.period.closing_stock = snap
        self.period.save()
        self.period.refresh_from_db()
        self.assertEqual(self.period.closing_stock_id, snap.pk)
        self.assertEqual(snap.stores.count(), 1)
        snap.delete()
        self.period.refresh_from_db()
        self.assertIsNone(self.period.closing_stock_id)


class Plan2AdapterTests(TestCase):
    def setUp(self):
        _fixtures(self)

    def _doc(self, key='k1', day=D(2031, 3, 10), **kw):
        return GLSourceDoc.objects.create(
            source_type='sales', source_key=key, doc_date=day, content_hash='h', **kw)

    def test_party_names_and_personcodes_confirmed_only(self):
        GLParty.objects.create(party_type='supplier', code='S1', name='مورد ١',
                               softech_personcode='77', status='confirmed')
        GLParty.objects.create(party_type='supplier', code='S2', name='مورد ٢',
                               softech_personcode='78', status='proposed')
        self.assertEqual(plan2_adapter.party_names(['S1', 'S2', 'S9']),
                         {'S1': 'مورد ١', 'S2': 'مورد ٢'})
        self.assertEqual(plan2_adapter.party_personcodes(['S1', 'S2']), {'S1': '77'})
        self.assertEqual(plan2_adapter.party_names([]), {})

    def test_open_exception_count_by_source_date(self):
        doc = self._doc()
        SourceException.objects.create(source_doc=doc, kind='no_rule', source_date=D(2031, 3, 10))
        SourceException.objects.create(source_doc=doc, kind='unmapped_party',
                                       source_date=D(2031, 4, 1))
        SourceException.objects.create(source_doc=doc, kind='ledger_error',
                                       source_date=D(2031, 3, 12), status='resolved')
        self.assertEqual(plan2_adapter.open_exception_count(D(2031, 3, 1), D(2031, 3, 31)), 1)

    def test_closed_period_change_and_resolve(self):
        original = _entry(self, status='approved')
        draft = _entry(self)
        doc = self._doc()
        exc = SourceException.objects.create(
            source_doc=doc, kind='closed_period_change', source_date=D(2031, 3, 10),
            original_entry=original, proposed_lines=[{'account_code': '4101'}],
            detail={'group_key': 'g', 'member_source_keys': ['k1', 'k2'], 'entry_id': draft.pk})
        cpc = plan2_adapter.closed_period_change(exc.pk)
        self.assertEqual(cpc.original_entry, original)
        self.assertEqual(cpc.draft_entry_id, draft.pk)
        self.assertEqual(cpc.group_key, 'g')
        self.assertEqual(cpc.member_source_keys, ['k1', 'k2'])
        self.assertEqual(cpc.proposed_lines, [{'account_code': '4101'}])
        self.assertEqual(cpc.source_date, D(2031, 3, 10))
        self.assertEqual(cpc.status, 'open')

        plan2_adapter.mark_exception_resolved(exc.pk, user=self.staff, entry=draft)
        exc.refresh_from_db()
        self.assertEqual(exc.status, 'resolved')
        self.assertEqual(exc.resolved_by, self.staff)
        self.assertIsNotNone(exc.resolved_at)

    def test_last_draft_run_through(self):
        self.assertIsNone(plan2_adapter.last_draft_run_through(self.period))
        short = GLDraftRun.objects.create(status='success', date_from=D(2031, 3, 1),
                                          date_to=D(2031, 3, 20))
        typed = GLDraftRun.objects.create(status='success', date_from=D(2031, 3, 1),
                                          date_to=D(2031, 3, 31), source_types=['sales'])
        failed = GLDraftRun.objects.create(status='failed', date_from=D(2031, 3, 1),
                                           date_to=D(2031, 3, 31))
        self.assertIsNone(plan2_adapter.last_draft_run_through(self.period))
        full = GLDraftRun.objects.create(status='partial', date_from=D(2031, 2, 1),
                                         date_to=D(2031, 4, 2))
        full.finished_at = timezone.now()
        full.save()
        self.assertEqual(plan2_adapter.last_draft_run_through(self.period), full.finished_at)
        self.assertTrue(short.pk and typed.pk and failed.pk)
