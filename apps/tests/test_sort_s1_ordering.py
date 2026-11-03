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
