"""Month close, auto-reversal and reopen (finance-gl Plan 3, Task 6). SOFTECH is mocked; nothing real is read.

TestCase throughout (ruling): a TransactionTestCase would flush the kept test DB and wipe the migration seeds. So
there is no two-connection race here; the status a concurrent approve sees is the one the service really sets,
read from inside the patched SOFTECH call (step b runs while the month is in `closing`).
"""
import datetime
from decimal import Decimal
from unittest import mock

from django.core.exceptions import PermissionDenied
from django.test import TestCase
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.branches.models import Branch
from apps.config.models import SystemSetting
from apps.finance import recon_labels
from apps.finance.gl import close as close_service
from apps.finance.gl import compare, corrections, ledger, softech_checks
from apps.finance.gl.balances import trial_balance
from apps.finance.gl.close import CloseError, checklist, close_month, reopen_month
from apps.finance.gl.ledger import LedgerError, approve, reverse, save_draft
from apps.finance.gl.periods import month_period, next_month
from apps.finance.gl.softech_stock import Valuation
from apps.finance.gl.statements import trading_and_pl
from apps.finance.models import (ClosingStockSnapshot, FinancialPeriod, GLAccount, GLAccountGroup,
                                 GLComparisonLine, GLDraftRun, GLSoftechCheck, GLSourceDoc, LedgerEntry,
                                 SourceException)
from apps.tests.factories import make_admin, make_user

D = datetime.date
Z = Decimal('0')
Y0 = D(2026, 1, 1)
JAN, FEB, MAR, APR = D(2026, 1, 31), D(2026, 2, 28), D(2026, 3, 31), D(2026, 4, 30)
LOGGER = 'elrezeiky.finance'

# code -> (group, section, statement_line)
ACCOUNTS = {
    '1301': ('النقديه بالصندوق', 'balance_sheet', 'cash'),
    '1390': ('بضاعة آخر المدة', 'balance_sheet', 'inventory'),
    '2341': ('المدفوعات التجاريه', 'balance_sheet', 'suppliers'),
    '2400': ('حقوق الملكيه', 'balance_sheet', 'capital'),
    '5100': ('تكلفة المبيعات', 'trading', 'net_purchases'),
    '5301': ('محزون أول المده', 'trading', 'opening_stock'),
    '5302': ('مخزون آخر المدة', 'trading', 'closing_stock'),
}


def _d(v):
    return Decimal(str(v))


def _store(code, value, *, as_of, included=True, carried_from=None):
    return {'store_code': code, 'store_name': f'مخزن {code}', 'branch_code': code, 'included': included,
            'rows': 3, 'value': _d(value), 'snapshot_date': carried_from or as_of,
            'carried': carried_from is not None}


class CloseBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        _, cls.staff, _ = make_admin('gl_close_admin')
        groups = {}
        for code, (gname, section, line) in ACCOUNTS.items():
            if gname not in groups:
                groups[gname] = GLAccountGroup.objects.create(name=gname, section=section, order=len(groups))
            GLAccount.objects.create(code=code, name=f'acc {code}', group=groups[gname], nature='debit',
                                     account_type='asset', statement_line=line,
                                     requires_branch=code in ('1390', '5302'))
        cls.b1 = Branch.objects.create(softech_branch_id='961', name='B1')
        cls.b2 = Branch.objects.create(softech_branch_id='962', name='B2')
        cls.b3 = Branch.objects.create(softech_branch_id='963', name='B3')
        # as seeded by migration 0025; written here too, since a TransactionTestCase elsewhere (test_gl_ledger)
        # flushes a kept test DB's migration rows
        GLSoftechCheck.objects.update_or_create(key='stock_at_cost', defaults=dict(
            label='المخزون بالتكلفة', kind='balance', account_codes=['1390'], group_names=[],
            source='stock_at_cost', sign='debit', per_party=False, blocks_close=False))
        GLSoftechCheck.objects.update_or_create(key='supplier_balance', defaults=dict(
            label='أرصدة الموردين', kind='balance', account_codes=['2341'], group_names=[],
            source='supplier_balance', sign='credit', per_party=True, blocks_close=False))

    def setUp(self):
        recon_labels._cache['at'] = 0   # the label map is cached for 10 minutes; do not leave ours for other tests
        self.addCleanup(recon_labels._cache.__setitem__, 'at', 0)
        self.stock = {JAN: {'961': _d('1000.50'), '962': _d(500)}, FEB: {'961': _d(1200)},
                      MAR: {'961': _d(1300)}, APR: {'961': _d(1400)}}
        self.softech = {}   # the other comparison sources: {source: figures}
        self.valuations = {}   # a Valuation to return as it is for a date, instead of self.stock
        self.during_read = None   # called while close_month is reading SOFTECH (the month is 'closing')
        p = mock.patch('apps.finance.gl.softech_stock.valuation', side_effect=self._valuation)
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.object(softech_checks, 'figures', side_effect=self._figures)
        p.start()
        self.addCleanup(p.stop)

    def _valuation(self, as_of):
        if self.during_read and FinancialPeriod.objects.filter(period_end=as_of, status='closing').exists():
            self.during_read()
        if as_of in self.valuations:
            return self.valuations[as_of]
        stores = [_store(c, v, as_of=as_of) for c, v in self.stock.get(as_of, {}).items()]
        return Valuation(as_of=as_of, stores=stores, total=sum((s['value'] for s in stores), Decimal('0.00')))

    def _figures(self, source, period):
        if source == 'stock_at_cost':
            return softech_checks.stock_at_cost(period)
        return self.softech.get(source, {})

    def post(self, amount, day, debit='5100', credit='2341', branch=None):
        bid = (branch or self.b1).id
        e = save_draft(user=self.staff, entry_date=day, description='x', lines=[
            {'account_code': debit, 'debit': _d(amount), 'credit': Z, 'branch_id': bid},
            {'account_code': credit, 'debit': Z, 'credit': _d(amount), 'branch_id': bid}])
        return approve(e.id, user=self.staff)

    def ready(self, period):
        """Comparison computed, and whatever a blocking check flags explained."""
        compare.compute(period)
        for line in GLComparisonLine.objects.filter(period=period, softech_check__blocks_close=True).select_related(
                'softech_check'):
            if line.needs_explanation:
                compare.explain(line.pk, user=self.staff, text='يترحل عند الإقفال')

    def blocking_check(self):
        """No seeded check blocks the close today, so a test of that item owns one: 5100 against the sales source."""
        return GLSoftechCheck.objects.create(key='t_blocks', label='فحص يمنع', kind='movement', account_codes=['5100'],
                                             group_names=[], source='sales', sign='debit', blocks_close=True)

    def close(self, day):
        period = month_period(day)
        self.ready(period)
        return close_month(period.pk, user=self.staff)

    def close_through(self, *days):
        for day in days:
            self.close(day)

    def status(self, day):
        return month_period(day).status

    def items(self, day):
        return {i['key']: i for i in checklist(month_period(day))}

    def balance(self, code, upto):
        rows = [r for r in trial_balance(Y0, upto) if r['code'] == code]
        return (rows[0]['closing_debit'] - rows[0]['closing_credit']) if rows else Decimal('0.00')

    def balances(self, upto):
        return {r['code']: r['closing_debit'] - r['closing_credit'] for r in trial_balance(Y0, upto)
                if r['closing_debit'] != r['closing_credit']}

    def close_entries(self):
        return LedgerEntry.objects.filter(source_type__in=('closing_stock', 'closing_stock_rev'))

    def live(self, key):
        return LedgerEntry.objects.get(source_key=key, status='approved')


class ChecklistTests(CloseBase):
    def test_item_order_and_shape(self):
        items = checklist(month_period(JAN))
        self.assertEqual([i['key'] for i in items], [
            'previous_closed', 'no_drafts', 'no_exceptions', 'comparison_fresh', 'comparison_explained',
            'suppliers_explained', 'drafting_ran', 'stock_snapshot'])
        self.assertEqual([i['key'] for i in items if not i['blocking']], ['suppliers_explained', 'drafting_ran'])
        for i in items:
            self.assertLessEqual({'key', 'label_ar', 'ok', 'blocking', 'detail'}, set(i))

    def test_checklist_blocks_on_drafts_exceptions_stale_comparison_unexplained_and_missing_stock(self):
        # stale: nothing computed yet
        self.assertFalse(self.items(JAN)['comparison_fresh']['ok'])
        self.blocking_check()
        self.softech['sales'] = {('961', ''): _d(70)}
        compare.compute(month_period(JAN))
        items = self.items(JAN)
        self.assertTrue(items['comparison_fresh']['ok'])
        self.assertFalse(items['comparison_explained']['ok'])
        self.ready(month_period(JAN))
        items = self.items(JAN)
        self.assertTrue(all(i['ok'] for i in items.values() if i['blocking']), items)

        draft = save_draft(user=self.staff, entry_date=D(2026, 1, 10), description='x', lines=[
            {'account_code': '5100', 'debit': _d(5), 'credit': Z, 'branch_id': self.b1.id},
            {'account_code': '2341', 'debit': Z, 'credit': _d(5), 'branch_id': self.b1.id}])
        item = self.items(JAN)['no_drafts']
        self.assertFalse(item['ok'])
        self.assertIn('1', item['detail'])
        self.assertEqual(item['link'], {'status': 'draft', 'date_from': '2026-01-01', 'date_to': '2026-01-31'})
        draft.delete()

        doc = GLSourceDoc.objects.create(source_type='t', source_key='k1', doc_date=D(2026, 1, 5), content_hash='h')
        exc = SourceException.objects.create(source_doc=doc, kind='ledger_error', source_date=D(2026, 1, 5),
                                             detail={'code': 'edited_by_user'}, message='m')
        self.assertFalse(self.items(JAN)['no_exceptions']['ok'])
        exc.delete()

        self.post(50, D(2026, 1, 12))   # approved after the computation
        self.assertFalse(self.items(JAN)['comparison_fresh']['ok'])
        self.ready(month_period(JAN))

        self.valuations[JAN] = Valuation(as_of=JAN, stores=[], missing_stores=['961'])
        item = self.items(JAN)['stock_snapshot']
        self.assertFalse(item['ok'])
        self.assertIn('2026-01-31', item['detail'])
        self.assertIn('961 · B1', item['detail'])
        self.assertNotIn('961 (', item['detail'])   # the label alone when the store is its branch
        self.assertIn('شغّل تقرير رصيد المخازن في تاريخ من سوفتيك لهذا التاريخ', item['detail'])

    def test_missing_hq_store_keeps_its_code_beside_the_branch_label(self):
        Branch.objects.create(softech_branch_id='100', name='HQ')
        self.valuations[JAN] = Valuation(as_of=JAN, stores=[], missing_stores=['102', '103'])
        detail = self.items(JAN)['stock_snapshot']['detail']
        self.assertIn('102 (100 · HQ)', detail)
        self.assertIn('103 (100 · HQ)', detail)

    def test_changed_difference_needs_explaining_again(self):
        self.blocking_check()
        self.softech['sales'] = {('961', ''): _d(70)}
        self.ready(month_period(JAN))
        self.assertTrue(self.items(JAN)['comparison_explained']['ok'])
        self.softech['sales'] = {('961', ''): _d(80)}
        compare.compute(month_period(JAN))
        self.assertFalse(self.items(JAN)['comparison_explained']['ok'])

    def test_stock_check_does_not_block_and_reads_zero_after_the_close(self):
        period = month_period(JAN)
        compare.compute(period)
        stock_lines = GLComparisonLine.objects.filter(period=period, softech_check__key='stock_at_cost')
        self.assertEqual(stock_lines.get(branch=self.b1).difference, _d('-1000.50'))   # 1390 is 0 before the close
        self.assertTrue(self.items(JAN)['comparison_explained']['ok'])
        self.assertEqual(close_month(period.pk, user=self.staff).status, 'closed')
        compare.compute(period)
        self.assertEqual({ln.difference for ln in stock_lines}, {Z})

    def test_suppliers_unexplained_does_not_block(self):
        self.post(300, D(2026, 1, 10))   # 2341 on the ledger, nothing on SOFTECH's side
        self.ready(month_period(JAN))
        item = self.items(JAN)['suppliers_explained']
        self.assertFalse(item['ok'])
        self.assertFalse(item['blocking'])
        self.assertIn('300', item['detail'])
        self.assertEqual(close_month(month_period(JAN).pk, user=self.staff).status, 'closed')

    def test_drafting_ran_is_a_note_only(self):
        item = self.items(JAN)['drafting_ran']
        self.assertFalse(item['ok'])
        self.assertFalse(item['blocking'])
        self.assertEqual(item['detail'], 'التسجيل الآلي من سوفتيك لم يغطِّ الشهر كله')
        GLDraftRun.objects.create(status='success', date_from=Y0, date_to=JAN, source_types=[])
        self.assertTrue(self.items(JAN)['drafting_ran']['ok'])

    def test_softech_down_shows_on_the_stock_item_only(self):
        with mock.patch('apps.finance.gl.softech_stock.valuation', side_effect=TimeoutError('timeout')):
            with self.assertLogs(LOGGER, level='WARNING'):
                items = self.items(JAN)
        self.assertFalse(items['stock_snapshot']['ok'])
        self.assertNotIn('timeout', items['stock_snapshot']['detail'])


class CloseTests(CloseBase):
    def test_close_posts_closing_stock_per_branch_and_reversal_on_first(self):
        period = self.close(JAN)
        self.assertEqual(period.status, 'closed')
        self.assertTrue(period.is_closed)
        self.assertEqual(period.closed_by, self.staff)
        self.assertIsNotNone(period.closed_at)

        entry = self.live('closing_stock:2026-01')
        self.assertEqual((entry.entry_date, entry.book, entry.source_type), (JAN, 'closing', 'closing_stock'))
        self.assertIn('بضاعة آخر المدة 2026-01', entry.description)
        lines = {(ln.account.code, ln.branch_id): (ln.debit, ln.credit) for ln in entry.lines.all()}
        self.assertEqual(lines, {
            ('1390', self.b1.id): (_d('1000.50'), Z), ('5302', self.b1.id): (Z, _d('1000.50')),
            ('1390', self.b2.id): (_d(500), Z), ('5302', self.b2.id): (Z, _d(500))})

        rev = self.live('closing_stock_rev:2026-01')
        self.assertEqual((rev.entry_date, rev.book, rev.source_type), (D(2026, 2, 1), 'closing', 'closing_stock_rev'))
        self.assertIn('عكس تلقائي لبضاعة آخر المدة 2026-01', rev.description)
        self.assertIsNone(rev.reverses_id)
        self.assertEqual(entry.status, 'approved')   # own entry, not reverse(): reopen needs the original live

        self.assertEqual(self.balance('1390', JAN), _d('1500.50'))
        self.assertEqual(self.balance('1390', D(2026, 2, 1)), Z)

        snap = period.closing_stock
        self.assertEqual((snap.total, snap.entry, snap.reversal, snap.read_by),
                         (_d('1500.50'), entry, rev, self.staff))
        self.assertEqual(snap.stores.get(store_code='961').branch, self.b1)
        self.assertTrue(AuditLog.objects.filter(action='gl_period_closed', object_id=str(period.pk)).exists())

    def test_excluded_store_is_kept_on_the_snapshot_but_not_posted(self):
        self.valuations[JAN] = Valuation(
            as_of=JAN, total=_d(100), excluded_total=_d(40),
            stores=[_store('961', 100, as_of=JAN), _store('962', 40, as_of=JAN, included=False)])
        period = self.close(JAN)
        self.assertEqual(self.balance('1390', JAN), _d(100))
        snap = period.closing_stock
        self.assertEqual(snap.excluded_total, _d(40))
        self.assertFalse(snap.stores.get(store_code='962').included)

    def test_negative_branch_flips_sides_and_zero_branch_is_dropped(self):
        self.stock[JAN] = {'961': _d(-200), '962': _d(500), '963': Z}
        period = self.close(JAN)
        entry = self.live('closing_stock:2026-01')
        lines = {(ln.account.code, ln.branch_id): (ln.debit, ln.credit) for ln in entry.lines.all()}
        self.assertEqual(lines, {
            ('1390', self.b1.id): (Z, _d(200)), ('5302', self.b1.id): (_d(200), Z),
            ('1390', self.b2.id): (_d(500), Z), ('5302', self.b2.id): (Z, _d(500))})
        rev = self.live('closing_stock_rev:2026-01')
        lines = {(ln.account.code, ln.branch_id): (ln.debit, ln.credit) for ln in rev.lines.all()}
        self.assertEqual(lines[('1390', self.b1.id)], (_d(200), Z))
        self.assertEqual(lines[('1390', self.b2.id)], (Z, _d(500)))
        self.assertEqual(self.balance('1390', JAN), _d(300))
        self.assertEqual(self.balance('1390', D(2026, 2, 1)), Z)
        self.assertEqual(period.closing_stock.stores.get(store_code='963').value, Z)

    def test_all_zero_stock_closes_with_no_entries(self):
        self.stock[JAN] = {'961': Z}
        period = self.close(JAN)
        self.assertEqual(period.status, 'closed')
        self.assertFalse(self.close_entries().exists())
        self.assertIsNone(period.closing_stock.entry)

    def test_stock_on_a_store_with_no_branch_fails_the_close(self):
        self.stock[JAN] = {'999': _d(10)}
        with self.assertRaises(CloseError) as cm:
            self.close(JAN)
        self.assertEqual(cm.exception.code, 'unknown_branch')
        self.assertEqual(self.status(JAN), 'open')
        self.assertFalse(self.close_entries().exists())

    def test_monthly_and_ytd_trading_account_after_two_closes(self):
        self.post(200, Y0, debit='5301', credit='2400')
        self.post(1000, D(2026, 1, 15))
        self.post(700, D(2026, 2, 15))
        self.stock[JAN] = {'961': _d(300)}
        self.stock[FEB] = {'961': _d(450)}
        self.close_through(JAN, FEB)

        feb = trading_and_pl(D(2026, 2, 1), FEB)
        self.assertEqual(feb['net_purchases'], _d(700))
        self.assertEqual(feb['closing_stock'], _d(150))   # Δstock
        self.assertEqual(feb['cost_of_sales'], _d(550))

        ytd = trading_and_pl(Y0, FEB)
        self.assertEqual(ytd['opening_stock'], _d(200))
        self.assertEqual(ytd['closing_stock'], _d(450))
        self.assertEqual(ytd['cost_of_sales'], _d(1450))   # 1700 − (450 − 200)

    def test_close_requires_previous_month_closed(self):
        period = month_period(FEB)
        self.ready(period)
        self.assertFalse(self.items(FEB)['previous_closed']['ok'])
        with self.assertRaises(CloseError) as cm:
            close_month(period.pk, user=self.staff)
        self.assertEqual(cm.exception.code, 'checklist')
        self.assertFalse(next(i for i in cm.exception.items if i['key'] == 'previous_closed')['ok'])
        self.assertEqual(self.status(FEB), 'open')
        self.close(JAN)
        self.assertTrue(self.items(FEB)['previous_closed']['ok'])

    def test_first_ledger_month_needs_no_previous(self):
        self.assertTrue(self.items(JAN)['previous_closed']['ok'])

    def test_close_refused_when_not_open(self):
        self.close(JAN)
        with self.assertRaises(CloseError) as cm:
            close_month(month_period(JAN).pk, user=self.staff)
        self.assertEqual(cm.exception.code, 'not_open')
        self.assertEqual(self.close_entries().count(), 2)

    def test_snapshot_missing_blocks_and_posts_nothing(self):
        period = month_period(JAN)
        self.ready(period)
        self.valuations[JAN] = Valuation(as_of=JAN, stores=[_store('961', 100, as_of=JAN)], total=_d(100),
                                         missing_stores=['962'])
        with self.assertRaises(CloseError) as cm:
            close_month(period.pk, user=self.staff)
        self.assertEqual(cm.exception.code, 'snapshot_missing')
        self.assertEqual(self.status(JAN), 'open')
        self.assertFalse(self.close_entries().exists())
        self.assertFalse(ClosingStockSnapshot.objects.filter(period=period).exists())
        self.assertIn('962', next(i for i in cm.exception.items if i['key'] == 'stock_snapshot')['detail'])

    def test_carried_stock_closes_with_note(self):
        self.valuations[JAN] = Valuation(
            as_of=JAN, total=_d(150), carried_stores=['962'],
            stores=[_store('961', 100, as_of=JAN), _store('962', 50, as_of=JAN, carried_from=D(2025, 12, 31))])
        self.ready(month_period(JAN))
        item = self.items(JAN)['stock_snapshot']
        self.assertTrue(item['ok'])
        self.assertIn('محمول من 2025-12-31', item['detail'])
        period = close_month(month_period(JAN).pk, user=self.staff)
        row = period.closing_stock.stores.get(store_code='962')
        self.assertTrue(row.carried)
        self.assertEqual(row.snapshot_date, D(2025, 12, 31))
        self.assertEqual(self.balance('1390', JAN), _d(150))

    def test_softech_failure_returns_period_to_open_without_entries(self):
        period = month_period(JAN)
        self.ready(period)
        with mock.patch('apps.finance.gl.softech_stock.valuation', side_effect=TimeoutError('softech timeout')):
            with self.assertRaises(TimeoutError):
                close_month(period.pk, user=self.staff)
        self.assertEqual(self.status(JAN), 'open')
        self.assertFalse(self.close_entries().exists())
        row = AuditLog.objects.get(action='gl_period_close_failed', object_id=str(period.pk))
        self.assertIn('softech timeout', row.extra['error'])
        self.assertEqual((row.old_data['status'], row.new_data['status']), ('closing', 'open'))

    def test_failure_after_the_closing_entry_leaves_nothing(self):
        period = month_period(JAN)
        self.ready(period)
        real_post = close_service._post

        def post(lines, **kw):
            if kw['source_type'] == 'closing_stock_rev':
                self.assertTrue(self.close_entries().exists())   # the closing entry is in, inside the transaction
                raise RuntimeError('boom')
            return real_post(lines, **kw)

        with mock.patch.object(close_service, '_post', side_effect=post), self.assertRaises(RuntimeError):
            close_month(period.pk, user=self.staff)
        period.refresh_from_db()
        self.assertEqual(period.status, 'open')
        self.assertIsNone(period.closing_stock)
        self.assertFalse(self.close_entries().exists())
        self.assertFalse(ClosingStockSnapshot.objects.filter(period=period).exists())
        self.assertTrue(AuditLog.objects.filter(action='gl_period_close_failed', object_id=str(period.pk)).exists())

    def test_next_month_must_be_open_before_anything_posts(self):
        period = month_period(JAN)
        self.ready(period)
        for status in ('closing', 'closed'):
            FinancialPeriod.objects.filter(pk=next_month(period).pk).update(status=status)
            with self.assertRaises(CloseError) as cm:
                close_month(period.pk, user=self.staff)
            self.assertEqual(cm.exception.code, 'next_not_open')
            self.assertEqual(self.status(JAN), 'open')
            self.assertFalse(self.close_entries().exists())

    def _closing_since(self, day, minutes):
        started = timezone.now() - datetime.timedelta(minutes=minutes)
        FinancialPeriod.objects.filter(pk=month_period(day).pk).update(status='closing', closing_started_at=started)
        return started

    def test_token_is_set_during_the_close_and_cleared_after(self):
        period = month_period(JAN)
        self.ready(period)
        seen = []
        self.during_read = lambda: seen.append(FinancialPeriod.objects.get(pk=period.pk).closing_started_at)
        closed = close_month(period.pk, user=self.staff)
        self.assertIsNotNone(seen[0])
        self.assertIsNone(closed.closing_started_at)

    def test_failure_clears_the_token(self):
        period = month_period(JAN)
        self.ready(period)
        with mock.patch('apps.finance.gl.softech_stock.valuation', side_effect=TimeoutError('x')), \
                self.assertRaises(TimeoutError):
            close_month(period.pk, user=self.staff)
        period.refresh_from_db()
        self.assertIsNone(period.closing_started_at)

    def test_young_closing_is_refused_and_left_closing(self):
        period = month_period(JAN)
        self.ready(period)
        started = self._closing_since(JAN, 29)
        with self.assertRaises(CloseError) as cm:
            close_month(period.pk, user=self.staff)
        self.assertEqual(cm.exception.code, 'close_running')
        period.refresh_from_db()
        self.assertEqual((period.status, period.closing_started_at), ('closing', started))
        self.assertFalse(self.close_entries().exists())
        self.assertFalse(AuditLog.objects.filter(action='gl_period_close_takeover', object_id=str(period.pk)).exists())

    def test_old_closing_is_taken_over(self):
        period = month_period(JAN)
        self.ready(period)
        started = self._closing_since(JAN, 31)
        closed = close_month(period.pk, user=self.staff)
        self.assertEqual(closed.status, 'closed')
        self.assertIsNone(closed.closing_started_at)
        self.assertEqual(self.close_entries().count(), 2)
        row = AuditLog.objects.get(action='gl_period_close_takeover', object_id=str(period.pk))
        self.assertEqual(row.old_data, {'status': 'closing', 'closing_started_at': started.isoformat()})
        self.assertEqual(row.new_data['status'], 'closing')

    def test_takeover_with_a_failing_checklist_returns_the_month_to_open(self):
        period = month_period(JAN)
        self.ready(period)
        self._closing_since(JAN, 31)
        self._draft_during_close()
        with self.assertRaises(CloseError) as cm:
            close_month(period.pk, user=self.staff)
        self.assertEqual(cm.exception.code, 'checklist')
        period.refresh_from_db()
        self.assertEqual((period.status, period.closing_started_at), ('open', None))
        self.assertTrue(AuditLog.objects.filter(action='gl_period_close_takeover', object_id=str(period.pk)).exists())

    def test_superseded_run_aborts_without_posting(self):
        period = month_period(JAN)
        self.ready(period)
        newer = timezone.now() + datetime.timedelta(minutes=31)
        self.during_read = lambda: FinancialPeriod.objects.filter(pk=period.pk).update(closing_started_at=newer)
        with self.assertRaises(CloseError) as cm:
            close_month(period.pk, user=self.staff)
        self.assertEqual(cm.exception.code, 'superseded')
        period.refresh_from_db()
        self.assertEqual((period.status, period.closing_started_at), ('closing', newer))   # the newer run owns it
        self.assertFalse(self.close_entries().exists())
        self.assertFalse(ClosingStockSnapshot.objects.filter(period=period).exists())
        row = AuditLog.objects.get(action='gl_period_close_failed', object_id=str(period.pk))
        self.assertEqual(row.extra['code'], 'superseded')

    def test_run_whose_month_left_closing_aborts_without_posting(self):
        period = month_period(JAN)
        self.ready(period)
        self.during_read = lambda: FinancialPeriod.objects.filter(pk=period.pk).update(
            status='open', closing_started_at=None)
        with self.assertRaises(CloseError) as cm:
            close_month(period.pk, user=self.staff)
        self.assertEqual(cm.exception.code, 'superseded')
        self.assertFalse(self.close_entries().exists())

    def _draft_during_close(self):
        return save_draft(user=self.staff, entry_date=D(2026, 1, 20), description='x', lines=[
            {'account_code': '5100', 'debit': _d(5), 'credit': Z, 'branch_id': self.b1.id},
            {'account_code': '2341', 'debit': Z, 'credit': _d(5), 'branch_id': self.b1.id}])

    def test_approve_during_closing_gets_period_closing(self):
        period = month_period(JAN)
        self.ready(period)
        seen = {}

        def attempt():
            seen['status'] = FinancialPeriod.objects.get(pk=period.pk).status
            draft = self._draft_during_close()
            try:
                approve(draft.id, user=self.staff)
            except LedgerError as e:
                seen['code'] = e.code
            draft.delete()

        self.during_read = attempt
        self.assertEqual(close_month(period.pk, user=self.staff).status, 'closed')
        self.assertEqual(seen, {'status': 'closing', 'code': 'period_closing'})

    def test_close_service_approves_into_closing_only_with_its_flag(self):
        FinancialPeriod.objects.filter(pk=month_period(JAN).pk).update(status='closing')
        draft = self._draft_during_close()
        with self.assertRaises(LedgerError) as cm:
            approve(draft.id, user=self.staff)
        self.assertEqual(cm.exception.code, 'period_closing')
        self.assertEqual(approve(draft.id, user=self.staff, _close_service=True).status, 'approved')

    def test_draft_landing_during_close_fails_the_recheck(self):
        period = month_period(JAN)
        self.ready(period)
        self.during_read = self._draft_during_close
        with self.assertRaises(CloseError) as cm:
            close_month(period.pk, user=self.staff)
        self.assertEqual(cm.exception.code, 'checklist')
        self.assertFalse(next(i for i in cm.exception.items if i['key'] == 'no_drafts')['ok'])
        self.assertEqual(self.status(JAN), 'open')
        self.assertFalse(self.close_entries().exists())
        self.assertTrue(AuditLog.objects.filter(action='gl_period_close_failed', object_id=str(period.pk)).exists())

    def test_december_waits_for_year_end_and_posts_nothing(self):
        dec = month_period(D(2026, 12, 1))
        FinancialPeriod.objects.filter(pk=month_period(D(2026, 11, 1)).pk).update(status='closed')
        self.stock[D(2026, 12, 31)] = {'961': _d(100)}
        self.ready(dec)
        with self.assertRaises(CloseError) as cm:
            close_month(dec.pk, user=self.staff)
        self.assertEqual(cm.exception.code, 'year_end_pending')
        dec.refresh_from_db()
        self.assertEqual(dec.status, 'open')
        self.assertFalse(self.close_entries().exists())

    def test_close_and_reopen_require_finalize(self):
        _, accountant, _ = make_user('gl_close_acct', role='accountant')
        period = month_period(JAN)
        self.ready(period)
        with self.assertRaises(PermissionDenied):
            close_month(period.pk, user=accountant)
        self.assertEqual(self.status(JAN), 'open')
        close_month(period.pk, user=self.staff)
        with self.assertRaises(PermissionDenied):
            reopen_month(period.pk, user=accountant, reason='x')
        self.assertEqual(self.status(JAN), 'closed')


class ReopenTests(CloseBase):
    def test_reopen_reverses_close_entries_and_trial_balance_returns_to_before(self):
        self.post(1000, D(2026, 1, 15))
        before = self.balances(FEB)
        period = self.close(JAN)
        self.assertNotEqual(self.balances(JAN), before)

        months = reopen_month(period.pk, user=self.staff, reason='فاتورة متأخرة')
        self.assertEqual([m.pk for m in months], [period.pk])
        period.refresh_from_db()
        self.assertEqual(period.status, 'open')
        self.assertFalse(period.is_closed)
        self.assertIsNone(period.closing_stock)
        self.assertIsNone(period.closed_by)
        self.assertIsNone(period.closed_at)
        self.assertEqual(self.balances(JAN), before)
        self.assertEqual(self.balances(FEB), before)
        self.assertEqual(self.balance('1390', JAN), Z)

        entries = list(self.close_entries())
        self.assertEqual({e.status for e in entries}, {'reversed'})
        for e in entries:
            mirror = e.reversals.get()
            self.assertEqual((mirror.entry_date, mirror.source_key), (e.entry_date, ''))
            self.assertEqual(mirror.notes, 'فاتورة متأخرة')

        row = AuditLog.objects.get(action='gl_period_reopened', object_id=str(period.pk))
        self.assertEqual(row.extra['reason'], 'فاتورة متأخرة')
        self.assertEqual(row.extra['months'], ['2026-01'])

        self.assertEqual(self.close(JAN).status, 'closed')   # the keys are free again
        self.assertEqual(self.balance('1390', JAN), _d('1500.50'))

    def test_reopen_cascades_to_later_closed_months(self):
        self.close_through(JAN, FEB, MAR)
        jan_entry = self.live('closing_stock:2026-01')
        before = self.balances(JAN)

        months = reopen_month(month_period(FEB).pk, user=self.staff, reason='تصحيح')
        self.assertEqual([m.label for m in months], ['2026-02', '2026-03'])
        self.assertEqual([self.status(d) for d in (JAN, FEB, MAR)], ['closed', 'open', 'open'])
        jan_entry.refresh_from_db()
        self.assertEqual(jan_entry.status, 'approved')
        self.assertFalse(self.close_entries().filter(status='approved').exclude(
            source_key__endswith=':2026-01').exists())
        self.assertEqual(self.balances(JAN), before)
        self.assertEqual(self.balance('1390', MAR), Z)   # Jan reversed on 1 Feb, Feb and Mar undone

        self.close_through(FEB, MAR)
        self.assertEqual([self.status(d) for d in (JAN, FEB, MAR)], ['closed', 'closed', 'closed'])
        self.assertEqual(self.balance('1390', MAR), _d(1300))

    def test_reopen_later_month_out_of_order_refused_by_previous_closed(self):
        self.close_through(JAN, FEB, MAR)
        reopen_month(month_period(FEB).pk, user=self.staff, reason='x')
        period = month_period(MAR)
        self.ready(period)
        with self.assertRaises(CloseError) as cm:
            close_month(period.pk, user=self.staff)   # Feb must close first
        self.assertEqual(cm.exception.code, 'checklist')

    def test_reopen_refused_beyond_three_closed_months(self):
        self.close_through(JAN, FEB, MAR, APR)
        with self.assertRaises(CloseError) as cm:
            reopen_month(month_period(JAN).pk, user=self.staff, reason='x')
        self.assertEqual(cm.exception.code, 'outside_window')
        self.assertEqual(self.status(JAN), 'closed')
        self.assertEqual(self.status(APR), 'closed')
        self.assertEqual(self.close_entries().filter(status='reversed').count(), 0)
        months = reopen_month(month_period(FEB).pk, user=self.staff, reason='x')
        self.assertEqual(len(months), 3)

    def test_window_setting_narrows_the_reopen(self):
        SystemSetting.objects.create(key='gl_reopen_window_months', label='x', value='1', value_type='integer')
        self.close_through(JAN, FEB)
        with self.assertRaises(CloseError) as cm:
            reopen_month(month_period(JAN).pk, user=self.staff, reason='x')
        self.assertEqual(cm.exception.code, 'outside_window')
        reopen_month(month_period(FEB).pk, user=self.staff, reason='x')

    def test_reopen_needs_reason_and_a_closed_month(self):
        period = self.close(JAN)
        with self.assertRaises(CloseError) as cm:
            reopen_month(period.pk, user=self.staff, reason='   ')
        self.assertEqual(cm.exception.code, 'reason_required')
        self.assertEqual(self.status(JAN), 'closed')
        with self.assertRaises(CloseError) as cm:
            reopen_month(month_period(FEB).pk, user=self.staff, reason='x')
        self.assertEqual(cm.exception.code, 'not_closed')

    def test_reopen_refused_while_the_next_month_is_closing(self):
        period = self.close(JAN)
        FinancialPeriod.objects.filter(pk=month_period(FEB).pk).update(status='closing')
        with self.assertRaises(CloseError) as cm:
            reopen_month(period.pk, user=self.staff, reason='x')
        self.assertEqual(cm.exception.code, 'close_running')
        self.assertEqual(self.status(JAN), 'closed')
        self.assertEqual(self.close_entries().filter(status='approved').count(), 2)

    def test_close_entries_cannot_be_reversed_outside_a_reopen(self):
        self.close(JAN)
        for key in ('closing_stock:2026-01', 'closing_stock_rev:2026-01'):
            with self.assertRaises(LedgerError) as cm:
                reverse(self.live(key).pk, user=self.staff, reason='x')
            self.assertEqual(cm.exception.code, 'close_entry')
            self.assertEqual(cm.exception.message, 'ده قيد إقفال، إعادة فتح الشهر هي الطريق')
        self.assertEqual(self.close_entries().filter(status='approved').count(), 2)

    def test_every_close_source_type_is_refused_by_reverse_and_correction(self):
        for source_type in ('year_end', 'year_end_stock'):
            draft = save_draft(user=self.staff, entry_date=D(2026, 1, 10), description='x', source_type=source_type,
                               lines=[{'account_code': '5100', 'debit': _d(5), 'credit': Z, 'branch_id': self.b1.id},
                                      {'account_code': '2341', 'debit': Z, 'credit': _d(5), 'branch_id': self.b1.id}])
            entry = approve(draft.pk, user=self.staff)
            for call in (lambda: reverse(entry.pk, user=self.staff, reason='x'),
                         lambda: corrections.post_late_correction(entry.pk, [], user=self.staff, reason='x')):
                with self.assertRaises(LedgerError) as cm:
                    call()
                self.assertEqual(cm.exception.code, 'close_entry')

    def test_close_entries_cannot_be_corrected_reopen_is_the_route(self):
        self.close_through(JAN, FEB)
        entry = self.live('closing_stock:2026-02')
        with self.assertRaises(LedgerError) as cm:
            corrections.post_late_correction(entry.pk, [
                {'account_code': '1390', 'debit': _d(1250), 'credit': Z, 'branch_id': self.b1.id},
                {'account_code': '5302', 'debit': Z, 'credit': _d(1250), 'branch_id': self.b1.id},
            ], user=self.staff, reason='x')
        self.assertEqual(cm.exception.code, 'close_entry')
        self.assertFalse(entry.corrections.exists())
        self.assertEqual(len(reopen_month(month_period(JAN).pk, user=self.staff, reason='x')), 2)

    def test_reopen_dates_every_mirror_as_its_original(self):
        self.close_through(JAN, FEB)
        with mock.patch.object(ledger, 'reverse', wraps=ledger.reverse) as spy:
            reopen_month(month_period(JAN).pk, user=self.staff, reason='x')
        self.assertEqual(spy.call_count, 4)
        for call in spy.call_args_list:
            original = LedgerEntry.objects.get(pk=call.args[0])
            self.assertEqual(call.kwargs['entry_date'], original.entry_date)
            self.assertTrue(call.kwargs['_close_service'])

    def test_reopen_racing_the_next_months_close_raises_instead_of_moving_a_mirror(self):
        """The next month turns `closing` under the reopen: the mirror must not slide into a later month."""
        self.close(JAN)
        real = ledger.reverse

        def racing(*a, **kw):
            FinancialPeriod.objects.filter(pk=month_period(FEB).pk).update(status='closing')
            return real(*a, **kw)

        with mock.patch.object(ledger, 'reverse', side_effect=racing), self.assertRaises(LedgerError) as cm:
            reopen_month(month_period(JAN).pk, user=self.staff, reason='x')
        self.assertEqual(cm.exception.code, 'closed_period')
        self.assertEqual(self.status(JAN), 'closed')
        self.assertFalse(LedgerEntry.objects.filter(source_type='reversal').exists())
        self.assertEqual(self.close_entries().filter(status='approved').count(), 2)

    def test_reopen_refused_while_a_later_month_not_next_to_it_is_closing(self):
        self.close_through(JAN, FEB)
        FinancialPeriod.objects.filter(pk=month_period(MAR).pk).update(status='closing')
        with self.assertRaises(CloseError) as cm:
            reopen_month(month_period(JAN).pk, user=self.staff, reason='x')
        self.assertEqual(cm.exception.code, 'close_running')
        self.assertEqual(self.close_entries().filter(status='reversed').count(), 0)

    def test_reopen_never_leaves_a_closed_correction_on_an_open_original(self):
        """Task 2's flagged state: the correction's month closed, its original's month open. The cascade reopens
        every later closed month, so an open month has no closed month after it."""
        self.close(JAN)
        original = self.post(100, D(2026, 2, 10))
        self.close(FEB)
        correction = corrections.post_late_correction(original.pk, [
            {'account_code': '5100', 'debit': _d(120), 'credit': Z, 'branch_id': self.b1.id},
            {'account_code': '2341', 'debit': Z, 'credit': _d(120), 'branch_id': self.b1.id},
        ], user=self.staff, reason='x')
        approve(correction.pk, user=self.staff)
        self.assertEqual(correction.entry_date, D(2026, 3, 1))
        self.close(MAR)

        reopen_month(month_period(FEB).pk, user=self.staff, reason='x')
        original.refresh_from_db()
        correction.refresh_from_db()
        self.assertEqual(original.period.status, 'open')
        self.assertEqual(correction.period.status, 'open')
        statuses = list(FinancialPeriod.objects.filter(period_type='month', period_start__gte=Y0).order_by(
            'period_start').values_list('status', flat=True))
        first_open = statuses.index('open')
        self.assertEqual(set(statuses[first_open:]), {'open'})   # closed months are always a run from the start
