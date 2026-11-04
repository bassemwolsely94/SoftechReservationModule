"""General Ledger model constraints (finance-gl Task 2)."""
import datetime
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.finance.models import (
    FinancialPeriod, GLAccountGroup, GLAccount, LedgerEntry, LedgerLine, GLSequence,
)
from django.contrib.auth.models import User

from apps.users.models import StaffProfile


class GLModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username='gl_u', password='x')
        cls.staff, _ = StaffProfile.objects.get_or_create(user=cls.user)
        cls.period = FinancialPeriod.objects.create(
            year=2026, month=11, period_type='month',
            period_start=datetime.date(2026, 11, 1), period_end=datetime.date(2026, 11, 30))
        cls.group = GLAccountGroup.objects.create(name='نقدية', section='balance_sheet', order=1)
        cls.acc = GLAccount.objects.create(
            code='1101', name='الخزينة', group=cls.group, nature='debit',
            account_type='asset', statement_line='cash')

    def _entry(self, **kw):
        defaults = dict(entry_date=datetime.date(2026, 11, 4), period=self.period,
                        book='general', description='t', created_by=self.staff)
        defaults.update(kw)
        return LedgerEntry.objects.create(**defaults)

    def test_line_cannot_have_debit_and_credit(self):
        e = self._entry()
        with self.assertRaises(IntegrityError), transaction.atomic():
            LedgerLine.objects.create(entry=e, line_no=1, account=self.acc,
                                      debit=Decimal('5'), credit=Decimal('5'))

    def test_negative_amount_rejected_by_db(self):
        e = self._entry()
        with self.assertRaises(IntegrityError), transaction.atomic():
            LedgerLine.objects.create(entry=e, line_no=1, account=self.acc,
                                      debit=Decimal('-1'), credit=Decimal('0'))

    def test_live_source_key_unique(self):
        first = self._entry(source_key='k1', source_type='x')
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._entry(source_key='k1', source_type='x')
        first.status = 'reversed'
        first.save()
        self._entry(source_key='k1', source_type='x')  # allowed again
        self._entry(source_key='')
        self._entry(source_key='')  # blank keys never collide

    def test_period_status_syncs_is_closed(self):
        p = FinancialPeriod.objects.create(
            year=2026, month=12, period_type='month',
            period_start=datetime.date(2026, 12, 1), period_end=datetime.date(2026, 12, 31))
        self.assertEqual(p.status, 'open')
        self.assertFalse(p.is_closed)
        p.status = 'closed'
        p.save()
        p.refresh_from_db()
        self.assertTrue(p.is_closed)
        p.status = 'open'
        p.save()
        p.refresh_from_db()
        self.assertFalse(p.is_closed)

    def test_closed_period_keeps_closed_status_after_save(self):
        p = FinancialPeriod.objects.create(
            year=2025, month=1, period_type='month', status='closed',
            period_start=datetime.date(2025, 1, 1), period_end=datetime.date(2025, 1, 31))
        p.label = 'x'
        p.save()
        p.refresh_from_db()
        self.assertTrue(p.is_closed)
        self.assertEqual(p.status, 'closed')

    def test_sequence(self):
        s = GLSequence.objects.create(year=2026)
        self.assertEqual(s.last, 0)
