"""
apps/tests/test_sort_s1_ordering.py

Sortable-grid sweep (batch S1): the paged finance / payment-audit lists take a whitelisted DRF `ordering`
parameter, so the headers sort ALL rows on the server, not just the visible page.
(The dead-stock lines ordering is covered in test_dead_stock.OrderingTests.)
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase

from apps.finance.models import Account, ExpenseRecord, FinancialPeriod
from apps.payments.models import BankStatementImport, ExternalPayment, PaymentException
from .factories import make_admin, make_branch


class FinanceOrderingTests(TestCase):

    def setUp(self):
        self.branch = make_branch()
        _, _, self.client = make_admin('sort_fin')

    def test_accounts_order_by_name_and_level_both_directions(self):
        Account.objects.create(code='1', name='x', name_ar='ب', level=3)
        Account.objects.create(code='2', name='y', name_ar='أ', level=1)
        Account.objects.create(code='3', name='z', name_ar='ج', level=2)
        names = lambda q: [a['name_ar'] for a in self.client.get('/api/finance/accounts/' + q).data['results']]
        self.assertEqual(names('?ordering=level'), ['أ', 'ج', 'ب'])
        self.assertEqual(names('?ordering=-level'), ['ب', 'ج', 'أ'])
        self.assertEqual(names('?ordering=-name_ar'), ['ج', 'ب', 'أ'])

    def test_expenses_order_by_amount_branch_and_description_and_unknown_field_is_ignored(self):
        period = FinancialPeriod.objects.create(year=2026, month=3, period_type='month',
                                                period_start=date(2026, 3, 1), period_end=date(2026, 3, 28))
        for amount, desc in ((30, 'ج'), (10, 'أ'), (20, 'ب')):
            ExpenseRecord.objects.create(period=period, expense_date=date(2026, 3, 5), category='other',
                                         amount=Decimal(amount), description=desc, branch=self.branch)
        get = lambda q: [e['description'] for e in
                         self.client.get('/api/finance/expenses/?period_id=%s%s' % (period.id, q)).data['results']]
        self.assertEqual(get('&ordering=amount'), ['أ', 'ب', 'ج'])
        self.assertEqual(get('&ordering=-amount'), ['ج', 'ب', 'أ'])
        self.assertEqual(get('&ordering=description'), ['أ', 'ب', 'ج'])
        # a field outside ordering_fields is never used as a sort key
        self.assertEqual(len(get('&ordering=vendor')), 3)
        self.assertEqual(self.client.get('/api/finance/expenses/?ordering=branch__name').status_code, 200)


class PaymentAuditOrderingTests(TestCase):

    def setUp(self):
        self.branch = make_branch()
        _, _, self.client = make_admin('sort_audit')

    def test_statements_order_by_total_lines(self):
        method = ExternalPayment.METHOD_CHOICES[0][0]
        for bank, total in (('B', 30), ('A', 10), ('C', 20)):
            BankStatementImport.objects.create(branch=self.branch, bank_name=bank, payment_method=method,
                                               statement_from=date(2026, 3, 1), statement_to=date(2026, 3, 31),
                                               total_lines=total)
        banks = lambda q: [s['bank_name'] for s in
                           self.client.get('/api/payments/audit/statements/' + q).data['results']]
        self.assertEqual(banks('?ordering=total_lines'), ['A', 'C', 'B'])
        self.assertEqual(banks('?ordering=-total_lines'), ['B', 'C', 'A'])
        self.assertEqual(banks('?ordering=bank_name'), ['A', 'B', 'C'])

    def test_exceptions_order_by_type(self):
        types = [c[0] for c in PaymentException._meta.get_field('exception_type').choices][:3]
        for t in types:
            PaymentException.objects.create(exception_type=t)
        got = lambda q: [e['exception_type'] for e in
                         self.client.get('/api/payments/audit/exceptions/' + q).data['results']]
        self.assertEqual(got('?ordering=exception_type'), sorted(types))
        self.assertEqual(got('?ordering=-exception_type'), sorted(types, reverse=True))


class EveryWhitelistedFieldTests(TestCase):
    """Rule 9: every whitelisted ordering field, ascending and descending, answers 200 (a wrong field name is a 500),
    and ties across a page boundary neither repeat nor drop rows."""

    def setUp(self):
        self.branch = make_branch()
        _, _, self.client = make_admin('sort_every')

    def _all_ok(self, url, fields):
        sep = '&' if '?' in url else '?'
        for f in fields:
            for o in (f, '-' + f):
                r = self.client.get(f'{url}{sep}ordering={o}')
                self.assertEqual(r.status_code, 200, f'{url} ordering={o}: {r.status_code}')

    def test_payment_audit_and_finance_fields(self):
        method = ExternalPayment.METHOD_CHOICES[0][0]
        BankStatementImport.objects.create(branch=self.branch, bank_name='B', payment_method=method,
                                           statement_from=date(2026, 3, 1), statement_to=date(2026, 3, 31))
        PaymentException.objects.create(exception_type=PaymentException._meta.get_field('exception_type').choices[0][0])
        Account.objects.create(code='9', name='x')
        ExpenseRecord.objects.create(expense_date=date(2026, 3, 5), amount=Decimal('1'), branch=self.branch)
        from apps.finance.views import AccountListView, ExpenseRecordListView
        from apps.payments.audit_views import BankStatementImportViewSet, PaymentExceptionViewSet
        self._all_ok('/api/payments/audit/statements/', BankStatementImportViewSet.ordering_fields)
        self._all_ok('/api/payments/audit/exceptions/', PaymentExceptionViewSet.ordering_fields)
        self._all_ok('/api/finance/accounts/', AccountListView.ordering_fields)
        self._all_ok('/api/finance/expenses/', ExpenseRecordListView.ordering_fields)

    def test_dead_stock_fields_are_all_sortable(self):
        from apps.purchasing.dead_stock_views import LINE_ORDERS
        self._all_ok('/api/purchasing/dead-stock/lines/', LINE_ORDERS)

    def test_ties_across_pages_do_not_repeat_or_drop(self):
        for i in range(120):                                  # level has 3 values -> heavy ties across the 50-row page
            Account.objects.create(code=f'T{i:03}', name=f'n{i}', level=i % 3)
        seen = []
        for page in (1, 2, 3):
            seen += [a['id'] for a in self.client.get(f'/api/finance/accounts/?ordering=level&page={page}').data['results']]
        self.assertEqual(len(seen), 120)
        self.assertEqual(len(set(seen)), 120)
        method = ExternalPayment.METHOD_CHOICES[0][0]
        for i in range(120):
            BankStatementImport.objects.create(branch=self.branch, bank_name='same', payment_method=method,
                                               statement_from=date(2026, 3, 1), statement_to=date(2026, 3, 31))
        ids = []
        for page in (1, 2, 3):
            ids += [s['id'] for s in
                    self.client.get(f'/api/payments/audit/statements/?ordering=bank_name&page={page}').data['results']]
        self.assertEqual(len(set(ids)), 120)


class RosterOrderingTests(TestCase):

    def test_roster_ordering_whitelist_and_all_fields(self):
        from django.contrib.auth import get_user_model
        from rest_framework.test import APIClient
        from apps.insurance.roster import ROSTER_ORDERS
        from apps.tests.test_insurance_roster import _client, _claim, _rx
        u = get_user_model().objects.create_user(username='rost_sort', password='x', is_staff=True, is_superuser=True)
        api = APIClient(); api.force_authenticate(u)
        a = _client('جهة أ')
        claim = _claim(a)
        for name in ('كمال صبرى فهمى ناشد', 'أحمد سعيد على حسن', 'زينب محمود عبد الله سالم'):
            _rx(claim, name)
        for f in ROSTER_ORDERS:
            for o in (f, '-' + f):
                r = api.get('/api/insurance/rosters/', {'client_id': a.client_id, 'ordering': o})
                self.assertEqual(r.status_code, 200, o)
        asc = [x['name'] for x in api.get('/api/insurance/rosters/', {'client_id': a.client_id, 'ordering': 'name'}).json()['members']]
        desc = [x['name'] for x in api.get('/api/insurance/rosters/', {'client_id': a.client_id, 'ordering': '-name'}).json()['members']]
        self.assertEqual(asc, desc[::-1])
        self.assertEqual(len(asc), 3)
        self.assertEqual(api.get('/api/insurance/rosters/', {'client_id': a.client_id, 'ordering': 'password'}).status_code, 400)
