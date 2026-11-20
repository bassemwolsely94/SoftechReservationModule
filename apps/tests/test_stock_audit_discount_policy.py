"""
C07 (audit doc 08, P-36): check 12 «خصم فوق السياسة» — a REPORT ONLY rule on the stock-audit ledger.
Expected discount = max(item ceiling posdiscp, class discount set for the invoice's channel, the
customer's own discount_percent). Contracts (10), donations (16) and compensations (17) are excluded.
It ships disabled and every result says "unvalidated"; it never changes a discount.
"""
import datetime as _dt
from decimal import Decimal

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.stock_audit.models import StockAuditFinding, StockAuditRule, StockLedgerLine
from apps.stock_audit.params import ParamError, ensure_rules, validate_params
from apps.stock_audit.rules import (RULES, RuleContext, check_discount_above_policy, expected_discount,
                                    parse_class_discounts)
from apps.tests.factories import make_branch, make_branch2, make_user

from .test_stock_audit_engine import ln

D = _dt.date(2026, 10, 25)
KEY = ('160', 1000, D)


def ctx(**kw):
    return RuleContext(_dt.date(2026, 9, 27), _dt.date(2026, 10, 27), **kw)


def p(**kw):
    return {**RULES['discount_above_policy']['defaults'], **kw}


def sale(**kw):
    line = ln(**kw)
    line.custdiscp = Decimal(str(kw.get('custdiscp', 0)))
    return line


class ExpectedDiscountTests(SimpleTestCase):
    def test_highest_of_item_ceiling_class_and_customer(self):
        c = ctx(item_ceiling={'100001': Decimal('10')}, customer_disc_of_invoice={KEY: Decimal('5')})
        self.assertEqual(expected_discount('100001', KEY, '91', c, {}), Decimal('10'))       # item ceiling
        self.assertEqual(expected_discount('100001', KEY, '30', c, {'30': Decimal('12')}), Decimal('12'))  # class
        c2 = ctx(customer_disc_of_invoice={KEY: Decimal('15')})
        self.assertEqual(expected_discount('100001', KEY, '91', c2, {}), Decimal('15'))      # customer's own
        self.assertEqual(expected_discount('999', ('x', 1, D), None, ctx(), {}), Decimal('0'))

    def test_parse_class_discounts(self):
        self.assertEqual(parse_class_discounts(['30:12', ' 11 : 5 ', 'bad']), {'30': Decimal('12'), '11': Decimal('5')})


class DiscountAbovePolicyTests(SimpleTestCase):
    def test_breach_above_item_ceiling_with_egp(self):
        c = ctx(item_ceiling={'100001': Decimal('10')}, channel_of_invoice={KEY: '91'})
        out = check_discount_above_policy([sale(custdiscp=15, transqty=2, itemsaleprice=100)], p(), c)
        self.assertEqual(len(out), 1)
        f = out[0]
        self.assertEqual(f['value_egp'], Decimal('10.00'))            # 100 × 2 × (15 − 10)%
        self.assertEqual(f['metric'], Decimal('5.0000'))
        self.assertTrue(f['evidence']['unvalidated'])
        self.assertIn('غير معتمد', f['message_ar'])
        self.assertIn('unvalidated', f['message_en'])

    def test_within_policy_or_tolerance_is_not_a_breach(self):
        c = ctx(item_ceiling={'100001': Decimal('10')})
        self.assertEqual(check_discount_above_policy([sale(custdiscp=10)], p(), c), [])
        self.assertEqual(check_discount_above_policy([sale(custdiscp='10.4')], p(), c), [])   # tolerance 0.5
        self.assertEqual(check_discount_above_policy([sale(custdiscp=0)], p(), c), [])

    def test_class_discount_for_the_channel_is_policy(self):
        c = ctx(item_ceiling={'100001': Decimal('10')}, channel_of_invoice={KEY: '30'})
        line = sale(custdiscp=12)
        self.assertEqual(len(check_discount_above_policy([line], p(), c)), 1)
        self.assertEqual(check_discount_above_policy([line], p(class_discounts=['30:12']), c), [])

    def test_excluded_channels_people_and_non_sales(self):
        for ch in ('10', '16', '17'):
            c = ctx(channel_of_invoice={KEY: ch})
            self.assertEqual(check_discount_above_policy([sale(custdiscp=20)], p(), c), [], ch)
        self.assertEqual(check_discount_above_policy([sale(custdiscp=20, personcode='4785')], p(), ctx()), [])
        self.assertEqual(check_discount_above_policy([sale(custdiscp=20, doccode='30')], p(), ctx()), [])
        self.assertEqual(check_discount_above_policy([sale(custdiscp=20, transqty=-1)], p(), ctx()), [])

    def test_severity_by_egp(self):
        out = check_discount_above_policy([sale(custdiscp=50, transqty=10, itemsaleprice=100)], p(), ctx())
        self.assertEqual((out[0]['severity'], out[0]['value_egp']), ('critical', Decimal('500.00')))


class DiscountPolicyParamsAndEngineTests(TestCase):
    def test_class_discount_entries_are_validated(self):
        self.assertEqual(validate_params('discount_above_policy', {'class_discounts': ['30:12']}),
                         {'class_discounts': ['30:12']})
        for bad in (['30'], ['30:abc'], ['30:120'], [':5']):
            with self.assertRaises(ParamError, msg=bad):
                validate_params('discount_above_policy', {'class_discounts': bad})

    def test_rule_ships_disabled_and_the_engine_stores_nothing(self):
        from apps.branches.models import Branch
        from apps.stock_audit.engine import run_stock_audit
        Branch.objects.create(softech_branch_id='160', name='B160', name_ar='فرع ١٦٠')
        ensure_rules()
        self.assertFalse(StockAuditRule.objects.get(code='discount_above_policy').enabled)
        line = sale(custdiscp=40)
        line.save()
        run = run_stock_audit(today=_dt.date(2026, 10, 26), triggered_by='test', rules=['discount_above_policy'])
        self.assertEqual(run.counts['discount_above_policy'], {'skipped': 'disabled'})
        self.assertFalse(StockAuditFinding.objects.filter(rule_code='discount_above_policy').exists())

    def test_never_writes_ledger_lines(self):
        line = sale(custdiscp=40)
        line.save()
        before = list(StockLedgerLine.objects.values())
        check_discount_above_policy(list(StockLedgerLine.objects.all()), p(), ctx())
        self.assertEqual(list(StockLedgerLine.objects.values()), before)


class DiscountPolicyPreviewApiTests(TestCase):
    URL = '/api/stock-audit/discount-policy/'

    def setUp(self):
        from apps.stock_audit.models import StockAuditAccess
        self.b1, self.b2 = make_branch('فرع أ', 'B01'), make_branch2('فرع ب', 'B02')
        today = timezone.localdate()
        for bc, n in (('B01', 1), ('B02', 2)):
            StockLedgerLine.objects.create(**{k: v for k, v in sale(branchcode=bc, docnumber=n, docdate=today,
                                                                    custdiscp=30).__dict__.items()
                                              if not k.startswith('_') and k != 'id'})
        _, admin_p, _ = make_user('dp_admin', role='admin', branch=self.b1)
        _, self.ph_p, self.ph = make_user('dp_ph', role='pharmacist', branch=self.b1)
        _, _, self.sup = make_user('dp_sup', role='supervisor', branch=self.b1)
        _, _, self.viewer = make_user('dp_view', role='viewer', branch=self.b1)
        self.grant = lambda: StockAuditAccess.objects.create(staff=self.ph_p, granted_by=admin_p)

    def test_needs_stock_audit_access(self):
        self.assertEqual(self.viewer.get(self.URL).status_code, 403)
        self.assertEqual(self.ph.get(self.URL).status_code, 403)       # no named-manager grant

    def test_management_sees_all_branches_labelled_unvalidated(self):
        r = self.sup.get(self.URL)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.data['unvalidated'])
        self.assertFalse(r.data['rule_enabled'])
        self.assertEqual({b['key'] for b in r.data['by_branch']}, {'B01', 'B02'})
        self.assertEqual(r.data['breach_lines'], 2)
        self.assertTrue(r.data['validation_steps'])
        self.assertFalse(StockAuditFinding.objects.exists())             # preview stores nothing

    def test_branch_manager_sees_only_own_branch(self):
        self.grant()
        r = self.ph.get(self.URL, {'branch': 'B02'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['by_branch'], [])                       # another branch: nothing
        r = self.ph.get(self.URL)
        self.assertEqual({b['key'] for b in r.data['by_branch']}, {'B01'})

    def test_window_is_capped(self):
        today = timezone.localdate()
        r = self.sup.get(self.URL, {'from': (today - _dt.timedelta(days=60)).isoformat(), 'to': today.isoformat()})
        self.assertEqual(r.status_code, 400)

    def test_read_only(self):
        self.assertEqual(self.sup.post(self.URL, {}, format='json').status_code, 405)
