"""
Round 2 / R2 — Finance GL money correctness (docs/security/2026-11-05-full-project-test-plan.md §7 R2).

Table tests on synthetic data, Decimal throughout. Every expected value comes from the documented rules:
  * apps/finance/gl/ledger.py module docstring + docs/architecture/35_FINANCE_GENERAL_LEDGER.md:
      - approval requires Σdebit == Σcredit > 0, amounts ≥ 0 with at most 2 decimals, one side per line;
      - an approved entry is never edited — it is reversed by an approved mirror (debit↔credit).
  * apps/finance/gl/balances.py docstring: the trial balance counts approved + reversed entries,
    so a reversed original and its mirror both count and net to zero; drafts never count.
  * apps/finance/gl/views.py: LedgerError codes in CONFLICT_CODES (not_draft, …) answer 409.
  * apps/finance/gl/drafting.py + LedgerEntry constraint gl_live_source_key_unique: one live
    (draft/approved) entry per source key, so re-running the engine never duplicates a draft.
No SOFTECH: the drafting engine is fed by in-memory readers (test_gl_drafting.Base).
"""
import datetime
from decimal import Decimal

from django.core.management import call_command
from django.db.models import Count, Sum
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.finance.gl import balances, ledger
from apps.finance.models import GLAccount, GLAccountGroup, LedgerEntry, LedgerLine

from .factories import make_user
from .test_gl_drafting import Base as DraftingBase, tender

D = Decimal
ZERO = D('0.00')
DAY = datetime.date(2026, 3, 10)

# (description, [(account, debit, credit), …]) — each row balances by construction of the table.
ENTRIES = [
    ('cash sale',            [('1101', '100.00', '0'), ('4101', '0', '100.00')]),
    ('split receipt',        [('1101', '60.25', '0'), ('1102', '39.75', '0'), ('4101', '0', '100.00')]),
    ('expense, two lines',   [('5101', '0.01', '0'), ('5101', '12345.67', '0'), ('1101', '0', '12345.68')]),
    ('three-way credit',     [('1102', '999.99', '0'), ('4101', '0', '333.33'), ('4101', '0', '333.33'),
                              ('4101', '0', '333.33')]),
    ('large amounts',        [('1102', '9999999999.99', '0'), ('4101', '0', '9999999999.99')]),
]


def _lines(rows):
    return [{'account_code': a, 'debit': d, 'credit': c} for a, d, c in rows]


class _GL(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('seed_permissions', verbosity=0)
        cash = GLAccountGroup.objects.create(name='نقدية', section='balance_sheet', order=1)
        sales = GLAccountGroup.objects.create(name='مبيعات', section='trading', order=2)
        exp = GLAccountGroup.objects.create(name='مصروفات', section='pl', order=3)
        mk = GLAccount.objects.create
        mk(code='1101', name='الخزينة', group=cash, nature='debit', account_type='asset')
        mk(code='1102', name='البنك', group=cash, nature='debit', account_type='asset')
        mk(code='4101', name='المبيعات', group=sales, nature='credit', account_type='revenue')
        mk(code='5101', name='مصروف', group=exp, nature='debit', account_type='expense')

    def setUp(self):
        _, self.staff, _ = make_user('r2_gl_acct', role='accountant')

    def post(self, rows, desc='r2', day=DAY):
        e = ledger.save_draft(user=self.staff, entry_date=day, description=desc, lines=_lines(rows))
        return ledger.approve(e.id, user=self.staff)


def _sides(entry):
    agg = entry.lines.aggregate(d=Sum('debit'), c=Sum('credit'))
    return agg['d'] or ZERO, agg['c'] or ZERO


class PostedEntriesBalanceTests(_GL):
    def test_every_posted_entry_has_debits_equal_to_credits(self):
        for desc, rows in ENTRIES:
            with self.subTest(desc):
                e = self.post(rows, desc)
                d, c = _sides(e)
                self.assertEqual(e.status, 'approved')
                self.assertEqual(d, c)
                self.assertGreater(d, ZERO)
                expected = sum((D(r[1]) for r in rows), ZERO)       # the table's own Σdebit
                self.assertEqual(d, expected)

    def test_unbalanced_or_bad_amounts_never_post(self):
        # ledger.py: unbalanced → 'unbalanced'; > 2 decimals, negative, or both sides → 'bad_amount'.
        cases = [
            ('off by one cent', [('1101', '100.00', '0'), ('4101', '0', '99.99')], 'unbalanced'),
            ('three decimals',  [('1101', '1.005', '0'), ('4101', '0', '1.005')], 'bad_amount'),
            ('negative',        [('1101', '-5', '0'), ('4101', '0', '-5')], 'bad_amount'),
            ('both sides',      [('1101', '5', '5'), ('4101', '0', '0')], 'bad_amount'),
            ('all zero',        [('1101', '0', '0'), ('4101', '0', '0')], 'bad_amount'),
        ]
        for desc, rows, code in cases:
            with self.subTest(desc):
                with self.assertRaises(ledger.LedgerError) as cm:
                    self.post(rows, desc)
                self.assertEqual(cm.exception.code, code)
        self.assertFalse(LedgerEntry.objects.filter(status='approved').exists())

    def test_database_refuses_a_line_with_both_sides(self):
        # LedgerLine constraint gl_line_amounts_valid — the last line of defence under the service.
        from django.db import IntegrityError, transaction
        e = ledger.save_draft(user=self.staff, entry_date=DAY, description='x',
                              lines=_lines([('1101', '1', '0'), ('4101', '0', '1')]))
        acct = GLAccount.objects.get(code='1101')
        with self.assertRaises(IntegrityError), transaction.atomic():
            LedgerLine.objects.create(entry=e, line_no=9, account=acct, debit=D('1'), credit=D('1'))


class TrialBalanceTests(_GL):
    def _tb(self, d1=datetime.date(2026, 3, 1), d2=datetime.date(2026, 3, 31), **kw):
        rows = balances.trial_balance(d1, d2, **kw)
        return rows[:-1], rows[-1]

    def assert_balanced(self, rows, total):
        # Trial balance totals 0.00: Σ(debit − credit) over every column pair.
        for a, b in (('opening_debit', 'opening_credit'), ('period_debit', 'period_credit'),
                     ('closing_debit', 'closing_credit')):
            self.assertEqual(total[a] - total[b], ZERO, a)
            self.assertEqual(sum((r[a] for r in rows), ZERO), total[a])

    def test_trial_balance_totals_zero(self):
        for desc, rows in ENTRIES:
            self.post(rows, desc)
        rows, total = self._tb()
        self.assert_balanced(rows, total)
        self.assertEqual(total['period_debit'], sum((D(r[1]) for _, rr in ENTRIES for r in rr), ZERO))

    def test_drafts_never_count_and_opening_carries_forward(self):
        self.post(ENTRIES[0][1], day=datetime.date(2026, 2, 15))          # opening for March
        ledger.save_draft(user=self.staff, entry_date=DAY, description='draft only',
                          lines=_lines([('1101', '7.00', '0'), ('4101', '0', '7.00')]))
        rows, total = self._tb()
        self.assert_balanced(rows, total)
        self.assertEqual(total['period_debit'], ZERO)                     # the draft is not in
        self.assertEqual(total['opening_debit'], D('100.00'))
        self.assertEqual(total['closing_debit'], D('100.00'))

    def test_reversal_plus_original_is_zero_on_every_account(self):
        originals = [self.post(rows, desc) for desc, rows in ENTRIES]
        target = originals[2]
        mirror = ledger.reverse(target.id, user=self.staff, reason='R2 test')
        target.refresh_from_db()
        self.assertEqual((target.status, mirror.status, mirror.reverses_id), ('reversed', 'approved', target.id))
        net = (LedgerLine.objects.filter(entry__in=[target, mirror]).values('account__code')
               .annotate(d=Sum('debit'), c=Sum('credit')))
        self.assertTrue(net)
        for r in net:
            self.assertEqual(r['d'] - r['c'], ZERO, r['account__code'])
        self.assertEqual(_sides(mirror), tuple(reversed(_sides(target))))
        rows, total = self._tb()
        self.assert_balanced(rows, total)
        # The reversed entry no longer moves any balance: closing = the other four entries alone.
        others = [e for e in originals if e.pk != target.pk]
        exp = (LedgerLine.objects.filter(entry__in=others).values('account__code')
               .annotate(n=Sum('debit') - Sum('credit')))
        want = {r['account__code']: r['n'] for r in exp}
        got = {r['code']: r['closing_debit'] - r['closing_credit'] for r in rows}
        self.assertEqual({k: v for k, v in got.items() if v}, {k: v for k, v in want.items() if v})

    def test_a_reversal_cannot_be_reversed_or_repeated(self):
        e = self.post(ENTRIES[0][1])
        mirror = ledger.reverse(e.id, user=self.staff, reason='x')
        for target, code in ((e.id, 'already_reversed'), (mirror.id, 'is_reversal')):
            with self.subTest(code), self.assertRaises(ledger.LedgerError) as cm:
                ledger.reverse(target, user=self.staff, reason='again')
            self.assertEqual(cm.exception.code, code)
        self.assertEqual(LedgerEntry.objects.filter(reverses=e).count(), 1)


class ApprovedEntryIsFrozenApiTests(_GL):
    BASE = '/api/finance/gl/entries/'

    def setUp(self):
        super().setUp()
        _, self.acct, _ = make_user('r2_gl_api', role='accountant')
        self.c = APIClient()
        self.c.credentials(HTTP_AUTHORIZATION=f'Bearer {AccessToken.for_user(self.acct.user)}')

    def body(self, amount='50.00'):
        return {'entry_date': DAY.isoformat(), 'book': 'general', 'description': 'edit', 'lines': [
            {'account_code': '1101', 'debit': amount, 'credit': '0'},
            {'account_code': '4101', 'debit': '0', 'credit': amount}]}

    def test_editing_or_deleting_a_non_draft_entry_is_409(self):
        approved = self.post(ENTRIES[0][1])
        other = self.post(ENTRIES[1][1])
        mirror = ledger.reverse(other.id, user=self.staff, reason='x')
        other.refresh_from_db()
        for label, e in (('approved', approved), ('reversed', other), ('reversal mirror', mirror)):
            before = (e.status, _sides(e))
            with self.subTest(label):
                r = self.c.put(f'{self.BASE}{e.pk}/', self.body('1.00'), format='json')
                self.assertEqual(r.status_code, 409, r.content)
                self.assertEqual(r.data['code'], 'not_draft')
                r = self.c.delete(f'{self.BASE}{e.pk}/')
                self.assertEqual(r.status_code, 409, r.content)
                e.refresh_from_db()
                self.assertEqual((e.status, _sides(e)), before)

    def test_approving_twice_is_409_and_keeps_one_number(self):
        r = self.c.post(self.BASE, self.body(), format='json')
        self.assertEqual(r.status_code, 201, r.content)
        pk = r.data['id']
        self.assertEqual(self.c.post(f'{self.BASE}{pk}/approve/').status_code, 200)
        number = LedgerEntry.objects.get(pk=pk).number
        r = self.c.post(f'{self.BASE}{pk}/approve/')
        self.assertEqual(r.status_code, 409, r.content)
        self.assertEqual(LedgerEntry.objects.get(pk=pk).number, number)


class DraftingRunsNeverDuplicateTests(DraftingBase):
    def test_two_runs_over_one_period_leave_one_live_draft_per_source(self):
        self.rule()
        self.docs['sales_tenders'] = [tender('t1', '100.00'), tender('t2', '50.25', pt='40'),
                                      tender('t3', '0.01', date=datetime.date(2026, 3, 11))]
        first = self.run_engine()
        snapshot = sorted(LedgerEntry.objects.values_list('id', 'source_key'))
        second = self.run_engine()
        self.assertEqual((first.status, second.status), ('success', 'success'))
        self.assertEqual(sorted(LedgerEntry.objects.values_list('id', 'source_key')), snapshot)
        dupes = (LedgerEntry.objects.filter(status__in=['draft', 'approved']).exclude(source_key='')
                 .values('source_key').annotate(n=Count('id')).filter(n__gt=1))
        self.assertFalse(dupes.exists())
        for e in LedgerEntry.objects.all():                     # every draft the engine wrote balances
            d, c = _sides(e)
            self.assertEqual(d, c, e.source_key)

    def test_service_refuses_a_second_live_entry_for_one_source(self):
        rows = [{'account_code': '1302', 'debit': '5', 'credit': '0'},
                {'account_code': '6002', 'debit': '0', 'credit': '5'}]
        ledger.save_draft(user=self.staff, entry_date=datetime.date(2026, 3, 10), description='a',
                          lines=rows, source_type='sales_tenders', source_key='dup-1')
        with self.assertRaises(ledger.LedgerError) as cm:
            ledger.save_draft(user=self.staff, entry_date=datetime.date(2026, 3, 10), description='b',
                              lines=rows, source_type='sales_tenders', source_key='dup-1')
        self.assertEqual(cm.exception.code, 'source_conflict')
        self.assertEqual(LedgerEntry.objects.filter(source_key='dup-1').count(), 1)
