"""
Multi-select list filters on the finance & admin screens (batch 4, core/multi_filter.py).

Every converted «كل …» list filter takes one value as before or several as a comma list (?k=a,b, or
repeated ?k=a&k=b). Two values = the union, one value = as before, nothing = every row the user may
see. Filters run after the existing branch scoping / permissions, so they can only narrow.

  A. finance — journal, COA, parties, rules, expenses, schema, payments
  B. admin   — vouchers + gift coupons, users, audit, devices, phone-alerts log
  C. ops     — POS exception center + lost-sales trend, incentives log, PIC analytics
"""
import datetime
import datetime as dt
from datetime import date as D, timedelta
from decimal import Decimal

from django.core.cache import cache
from django.core.management import call_command
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone

from apps.access import devices as dev_api
from apps.access.models import Device
from apps.audit.models import AbuseFlag, AuditLog
from apps.branches.models import Branch
from apps.customers.models import Customer
from apps.finance.models import (
    ExpenseRecord, FinanceSchemaTable, FinancialPeriod, GLAccount, GLAccountGroup, GLParty,
    GLSourceDoc, LedgerEntry, PostingRule, SourceException,
)
from apps.incentives.models import IncentiveCalculationLog, IncentiveProgram
from apps.notifications.phone_alerts.models import PhoneAlert
from apps.payments.models import ExternalPayment
from apps.pic_analytics.access import Access
from apps.pic_analytics.models import PicAnalyticsAccess, PicDayFact, PicRollup
from apps.pic_analytics.queries.filters import FilterError, Filters
from apps.pos_orders.models import PosCancelDaily, SoftechSalesOrder as S
from apps.tests.factories import make_branch, make_branch2, make_user
from apps.tests.security.fixtures import seed_code_matrix
from apps.vouchers.models import CouponEvent, Voucher
from core.middleware import module_access

GL = '/api/finance/gl/'


def _rows(resp):
    data = resp.data
    return data.get('results', data) if hasattr(data, 'get') else data


# ══════════════════════════════════════════════════════════════════════════════════════════
# A. Finance
# ══════════════════════════════════════════════════════════════════════════════════════════

def _body(date='2026-03-01'):
    return {'entry_date': date, 'book': 'general', 'description': 'قيد تجربة', 'lines': [
        {'account_code': '1101', 'debit': '100.00', 'credit': '0'},
        {'account_code': '4101', 'debit': '0', 'credit': '100.00'},
    ]}


@override_settings(RBAC_ENFORCEMENT='log')
class _GLBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('seed_permissions', verbosity=0)
        cls.cash = GLAccountGroup.objects.create(name='نقدية', section='balance_sheet', order=1)
        cls.sales = GLAccountGroup.objects.create(name='المبيعات', section='trading', order=2)
        cls.other = GLAccountGroup.objects.create(name='أخرى', section='pl', order=3)
        GLAccount.objects.create(code='1101', name='الخزينة', group=cls.cash, nature='debit',
                                 account_type='asset', statement_line='cash')
        GLAccount.objects.create(code='4101', name='المبيعات', group=cls.sales, nature='credit',
                                 account_type='revenue', statement_line='net_sales')
        GLAccount.objects.create(code='6101', name='مصروف', group=cls.other, nature='debit',
                                 account_type='expense')

    def setUp(self):
        self.b1 = make_branch('فرع م1', 'MF01')
        self.b2 = make_branch2('فرع م2', 'MF02')
        self.b3 = make_branch('فرع م3', 'MF03')
        _, self.admin, self.c = make_user('msfa_admin', role='admin', access_all=True)

    def tearDown(self):
        module_access.clear_cache()

    def get(self, path, **params):
        r = self.c.get(GL + path, params)
        self.assertEqual(r.status_code, 200, getattr(r, 'data', r.content))
        return r


# ── Journal entries ───────────────────────────────────────────────────────────

class FinanceMSJournalEntriesTests(_GLBase):
    def setUp(self):
        super().setUp()
        self.e1, self.e2, self.e3 = (self.draft() for _ in range(3))
        LedgerEntry.objects.filter(pk=self.e1).update(status='draft', book='general', branch=self.b1,
                                                      source_type='')
        LedgerEntry.objects.filter(pk=self.e2).update(status='approved', book='cash', branch=self.b2,
                                                      source_type='sales_tenders')
        LedgerEntry.objects.filter(pk=self.e3).update(status='reversed', book='credit', branch=self.b3,
                                                      source_type='purchases')

    def draft(self):
        r = self.c.post(GL + 'entries/', _body(), format='json')
        self.assertEqual(r.status_code, 201, r.content)
        return r.data['id']

    def ids(self, **params):
        return {e['id'] for e in _rows(self.get('entries/', **params))}

    def test_status_two_one_none(self):
        self.assertEqual(self.ids(status='draft,approved'), {self.e1, self.e2})
        self.assertEqual(self.ids(status='approved'), {self.e2})
        self.assertEqual(self.ids(), {self.e1, self.e2, self.e3})

    def test_status_repeated_param(self):
        r = self.c.get(GL + 'entries/?status=draft&status=reversed')
        self.assertEqual({e['id'] for e in _rows(r)}, {self.e1, self.e3})

    def test_book_two_one(self):
        self.assertEqual(self.ids(book='cash,credit'), {self.e2, self.e3})
        self.assertEqual(self.ids(book='general'), {self.e1})

    def test_branch_two_one_and_junk(self):
        self.assertEqual(self.ids(branch=f'{self.b1.id},{self.b3.id}'), {self.e1, self.e3})
        self.assertEqual(self.ids(branch=str(self.b2.id)), {self.e2})
        self.assertEqual(self.ids(branch='abc'), set())          # junk only = nothing, never all

    def test_source_two_one_and_manual(self):
        self.assertEqual(self.ids(source_type='sales_tenders,purchases'), {self.e2, self.e3})
        self.assertEqual(self.ids(source_type='purchases'), {self.e3})
        self.assertEqual(self.ids(source_type='manual'), {self.e1})                  # '' = manual
        self.assertEqual(self.ids(source_type='manual,sales_tenders'), {self.e1, self.e2})


# ── Journal exceptions tab (source · branch) ──────────────────────────────────

class FinanceMSExceptionsTests(_GLBase):
    D = datetime.date(2026, 3, 10)

    def setUp(self):
        super().setUp()
        self.x1 = self.exc('k1', 'sales_tenders', self.b1.softech_branch_id)
        self.x2 = self.exc('k2', 'purchases', self.b2.softech_branch_id)
        self.x3 = self.exc('k3', 'expenses', self.b3.softech_branch_id)

    def exc(self, key, source_type, branch_code):
        doc = GLSourceDoc.objects.create(source_type=source_type, source_key=key, doc_date=self.D,
                                         branch_code=branch_code, amounts={'net': '10.00'},
                                         content_hash=key, status='exception')
        return SourceException.objects.create(source_doc=doc, kind='no_rule', source_date=self.D,
                                              message='m').id

    def ids(self, **params):
        return {e['id'] for e in _rows(self.get('exceptions/', **params))}

    def test_source_two_one_none(self):
        self.assertEqual(self.ids(source_type='sales_tenders,purchases'), {self.x1, self.x2})
        self.assertEqual(self.ids(source_type='expenses'), {self.x3})
        self.assertEqual(self.ids(), {self.x1, self.x2, self.x3})

    def test_branch_two_one(self):
        self.assertEqual(self.ids(branch=f'{self.b1.id},{self.b3.id}'), {self.x1, self.x3})
        self.assertEqual(self.ids(branch=str(self.b2.id)), {self.x2})

    def test_counts_take_several_sources(self):
        r = self.get('exceptions/counts/', source_type='sales_tenders,purchases')
        self.assertEqual(r.data['total'], 2)
        self.assertEqual(self.get('exceptions/counts/', source_type='expenses').data['total'], 1)
        self.assertEqual(self.get('exceptions/counts/').data['total'], 3)


# ── Chart of accounts (group) ─────────────────────────────────────────────────

class FinanceMSAccountsGroupTests(_GLBase):
    def codes(self, **params):
        return {a['code'] for a in self.get('accounts/', **params).data}

    def test_group_two_one_none(self):
        self.assertEqual(self.codes(group=f'{self.cash.id},{self.other.id}'), {'1101', '6101'})
        self.assertEqual(self.codes(group=str(self.sales.id)), {'4101'})
        self.assertEqual(self.codes(), {'1101', '4101', '6101'})

    def test_group_junk_matches_nothing(self):
        self.assertEqual(self.codes(group='x'), set())


# ── Parties (status · type) ───────────────────────────────────────────────────

class FinanceMSPartiesTests(_GLBase):
    def setUp(self):
        super().setUp()
        self.p1 = GLParty.objects.create(party_type='supplier', code='S1', name='مورد', status='proposed').id
        self.p2 = GLParty.objects.create(party_type='customer', code='C1', name='عميل', status='confirmed').id
        self.p3 = GLParty.objects.create(party_type='employee', code='E1', name='موظف', status='unmapped').id

    def ids(self, **params):
        return {p['id'] for p in _rows(self.get('parties/', **params))}

    def test_status_two_one_none(self):
        self.assertEqual(self.ids(status='proposed,unmapped'), {self.p1, self.p3})
        self.assertEqual(self.ids(status='confirmed'), {self.p2})
        self.assertEqual(self.ids(), {self.p1, self.p2, self.p3})

    def test_type_two_one(self):
        self.assertEqual(self.ids(type='supplier,customer'), {self.p1, self.p2})
        self.assertEqual(self.ids(type='employee'), {self.p3})


# ── Posting rules (source) ────────────────────────────────────────────────────

class FinanceMSRulesTests(_GLBase):
    def setUp(self):
        super().setUp()
        for code, st in (('r.sales', 'sales_tenders'), ('r.purch', 'purchases'), ('r.exp', 'expenses')):
            PostingRule.objects.create(code=code, source_type=st, effective_from=datetime.date(2026, 1, 1))

    def codes(self, **params):
        return {r['code'] for r in _rows(self.get('rules/', **params))}

    def test_source_two_one_none(self):
        self.assertEqual(self.codes(source_type='sales_tenders,expenses'), {'r.sales', 'r.exp'})
        self.assertEqual(self.codes(source_type='purchases'), {'r.purch'})
        self.assertEqual(self.codes(), {'r.sales', 'r.purch', 'r.exp'})


# ── Expenses (category · sub-category · branch) ───────────────────────────────

@override_settings(RBAC_ENFORCEMENT='log')
class FinanceMSExpensesTests(TestCase):
    URL = '/api/finance/expenses/'

    def setUp(self):
        call_command('seed_permissions', verbosity=0)
        self.b1 = make_branch('فرع م1', 'MF01')
        self.b2 = make_branch2('فرع م2', 'MF02')
        self.b3 = make_branch('فرع م3', 'MF03')
        _, _, self.admin_c = make_user('msfa_exp_admin', role='admin', access_all=True)
        _, _, self.pharm_c = make_user('msfa_exp_pharm', role='pharmacist', branch=self.b1)
        self.period = FinancialPeriod.objects.create(
            period_type='month', year=2026, month=3, label='2026-03',
            period_start=datetime.date(2026, 3, 1), period_end=datetime.date(2026, 3, 31))
        self.x1 = self.exp('rent', 'إيجار محل', self.b1, '100')
        self.x2 = self.exp('payroll', 'رواتب', self.b2, '200')
        self.x3 = self.exp('utilities', 'كهرباء', self.b3, '300')

    def tearDown(self):
        module_access.clear_cache()

    def exp(self, cat, sub, branch, amount):
        return ExpenseRecord.objects.create(expense_date=datetime.date(2026, 3, 5), category=cat,
                                            sub_category=sub, branch=branch, amount=Decimal(amount),
                                            period=self.period).id

    def ids(self, client=None, **params):
        r = (client or self.admin_c).get(self.URL, params)
        self.assertEqual(r.status_code, 200, getattr(r, 'data', r.content))
        return {row['id'] for row in _rows(r)}

    def test_category_two_one_none(self):
        self.assertEqual(self.ids(category='rent,utilities'), {self.x1, self.x3})
        self.assertEqual(self.ids(category='payroll'), {self.x2})
        self.assertEqual(self.ids(), {self.x1, self.x2, self.x3})

    def test_sub_category_two_one(self):
        self.assertEqual(self.ids(sub_category='رواتب,كهرباء'), {self.x2, self.x3})
        self.assertEqual(self.ids(sub_category='إيجار'), {self.x1})      # still a contains-match

    def test_branch_two_one(self):
        self.assertEqual(self.ids(branch_id=f'{self.b1.id},{self.b2.id}'), {self.x1, self.x2})
        self.assertEqual(self.ids(branch_id=str(self.b3.id)), {self.x3})

    def test_branch_filter_never_widens_scope(self):
        self.assertEqual(self.ids(self.pharm_c, branch_id=f'{self.b1.id},{self.b2.id}'), {self.x1})
        self.assertEqual(self.ids(self.pharm_c, branch_id=str(self.b2.id)), set())
        self.assertEqual(self.ids(self.pharm_c, branch_id='junk'), set())

    def test_breakdown_and_subcategories_take_several(self):
        q = {'year': 2026, 'month': 3, 'category': 'rent,payroll'}
        r = self.admin_c.get(self.URL + 'breakdown/', q)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual({row['category'] for row in r.data['by_category']}, {'rent', 'payroll'})
        r = self.admin_c.get(self.URL + 'breakdown/', {'year': 2026, 'month': 3, 'branch_id': str(self.b3.id)})
        self.assertEqual({row['category'] for row in r.data['by_category']}, {'utilities'})
        r = self.admin_c.get(self.URL + 'subcategories/', {**q, 'branch_id': f'{self.b1.id},{self.b3.id}'})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual({row['sub_category'] for row in r.data}, {'إيجار محل'})


# ── Schema discovery (category) ───────────────────────────────────────────────

@override_settings(RBAC_ENFORCEMENT='log')
class FinanceMSSchemaTests(TestCase):
    URL = '/api/finance/schema/'

    def setUp(self):
        call_command('seed_permissions', verbosity=0)
        _, _, self.c = make_user('msfa_schema_admin', role='admin', access_all=True)
        self.t1 = FinanceSchemaTable.objects.create(table_name='t_journal', category='journal').id
        self.t2 = FinanceSchemaTable.objects.create(table_name='t_cash', category='cash').id
        self.t3 = FinanceSchemaTable.objects.create(table_name='t_bank', category='bank').id

    def tearDown(self):
        module_access.clear_cache()

    def ids(self, **params):
        r = self.c.get(self.URL, params)
        self.assertEqual(r.status_code, 200, getattr(r, 'data', r.content))
        return {row['id'] for row in _rows(r)}

    def test_category_two_one_none(self):
        self.assertEqual(self.ids(category='journal,bank'), {self.t1, self.t3})
        self.assertEqual(self.ids(category='cash'), {self.t2})
        self.assertEqual(self.ids(), {self.t1, self.t2, self.t3})


# ── External payments (method · status · branch) ──────────────────────────────

@override_settings(RBAC_ENFORCEMENT='log')
class FinanceMSPaymentsTests(TestCase):
    URL = '/api/payments/'

    def setUp(self):
        call_command('seed_permissions', verbosity=0)
        self.b1 = make_branch('فرع م1', 'MF01')
        self.b2 = make_branch2('فرع م2', 'MF02')
        self.b3 = make_branch('فرع م3', 'MF03')
        _, _, self.admin_c = make_user('msfa_pay_admin', role='admin', access_all=True)
        _, _, self.pharm_c = make_user('msfa_pay_pharm', role='pharmacist', branch=self.b1)
        self.p1 = self.pay(self.b1, 'cash', 'pending')
        self.p2 = self.pay(self.b2, 'instapay', 'confirmed')
        self.p3 = self.pay(self.b3, 'vodafone_cash', 'disputed')

    def tearDown(self):
        module_access.clear_cache()

    def pay(self, branch, method, status):
        return ExternalPayment.objects.create(branch=branch, method=method, status=status,
                                              amount=Decimal('150.00')).id

    def ids(self, client=None, **params):
        r = (client or self.admin_c).get(self.URL, params)
        self.assertEqual(r.status_code, 200, getattr(r, 'data', r.content))
        return {row['id'] for row in _rows(r)}

    def test_method_two_one_none(self):
        self.assertEqual(self.ids(method='cash,vodafone_cash'), {self.p1, self.p3})
        self.assertEqual(self.ids(method='instapay'), {self.p2})
        self.assertEqual(self.ids(), {self.p1, self.p2, self.p3})

    def test_status_two_one(self):
        self.assertEqual(self.ids(status='pending,disputed'), {self.p1, self.p3})
        self.assertEqual(self.ids(status='confirmed'), {self.p2})

    def test_status_repeated_param(self):
        r = self.admin_c.get(self.URL + '?status=pending&status=confirmed')
        self.assertEqual({row['id'] for row in _rows(r)}, {self.p1, self.p2})

    def test_branch_two_one(self):
        self.assertEqual(self.ids(branch=f'{self.b2.id},{self.b3.id}'), {self.p2, self.p3})
        self.assertEqual(self.ids(branch=str(self.b1.id)), {self.p1})

    def test_branch_filter_never_widens_scope(self):
        self.assertEqual(self.ids(self.pharm_c, branch=f'{self.b1.id},{self.b2.id}'), {self.p1})
        self.assertEqual(self.ids(self.pharm_c, branch=str(self.b2.id)), set())
        self.assertEqual(self.ids(self.pharm_c, branch='junk'), set())


# ══════════════════════════════════════════════════════════════════════════════════════════
# B. Admin / vouchers / phone alerts
# ══════════════════════════════════════════════════════════════════════════════════════════

@override_settings(RBAC_ENFORCEMENT='log')
class _Base(TestCase):
    URL = ''

    def setUp(self):
        cache.clear()
        seed_code_matrix()
        self.b1 = make_branch('فرع أ1', 'AM01')
        self.b2 = make_branch2('فرع أ2', 'AM02')
        self.b3 = make_branch('فرع أ3', 'AM03')
        _, self.admin, self.admin_c = make_user('ms_adm_admin', role='admin', access_all=True)

    def tearDown(self):
        module_access.clear_cache()
        cache.clear()

    def ids(self, client=None, url=None, **params):
        r = (client or self.admin_c).get(url or self.URL, params)
        self.assertEqual(r.status_code, 200, getattr(r, 'data', r))
        return {row['id'] for row in _rows(r)}


# ── Vouchers ──────────────────────────────────────────────────────────────────

class AdminMSVoucherListTests(_Base):
    URL = '/api/vouchers/vouchers/'

    def setUp(self):
        super().setUp()
        self.v1 = self.voucher('active', 'discount_pct', 'public')
        self.v2 = self.voucher('expired', 'discount_fixed', 'private')
        self.v3 = self.voucher('cancelled', 'credit', 'first_time')

    def voucher(self, status, vtype, cat):
        return Voucher.objects.create(code=Voucher.generate_code(), title='ق', voucher_type=vtype,
                                      voucher_category=cat, discount_pct=10, discount_amount=5,
                                      branch=self.b1, created_by=self.admin, status=status, max_uses=10,
                                      valid_from=dt.date.today())

    def test_status_two_one_none(self):
        self.assertEqual(self.ids(status='active,expired'), {self.v1.id, self.v2.id})
        self.assertEqual(self.ids(status='cancelled'), {self.v3.id})
        self.assertEqual(self.ids(), {self.v1.id, self.v2.id, self.v3.id})

    def test_status_repeated_param(self):
        r = self.admin_c.get(self.URL + '?status=active&status=cancelled')
        self.assertEqual({row['id'] for row in _rows(r)}, {self.v1.id, self.v3.id})

    def test_type_two_one(self):
        self.assertEqual(self.ids(type='discount_pct,credit'), {self.v1.id, self.v3.id})
        self.assertEqual(self.ids(type='discount_fixed'), {self.v2.id})

    def test_category_two_one(self):
        self.assertEqual(self.ids(category='public,private'), {self.v1.id, self.v2.id})
        self.assertEqual(self.ids(category='first_time'), {self.v3.id})


class AdminMSCouponNoSerialTests(_Base):
    URL = '/api/vouchers/coupons/no-serial/'

    def setUp(self):
        super().setUp()
        for n, br in enumerate(('130', '150', '170'), start=1):
            CouponEvent.objects.create(leg='served', itemcode='99', kind='redeem', doccode='115',
                                       branchcode=br, docnumber=9000 + n, docdate=dt.date.today(),
                                       qty=1, usercode='7')

    def branches(self, **params):
        r = self.admin_c.get(self.URL, {'days': 7, **params})
        self.assertEqual(r.status_code, 200, r.data)
        return {row['branch'] for row in r.data['by_branch']}, r.data

    def test_branch_two_one_none(self):
        got, data = self.branches(branch='130,170')
        self.assertEqual(got, {'130', '170'})
        self.assertEqual({row['branchcode'] for row in data['rows']}, {'130', '170'})
        self.assertEqual(self.branches(branch='150')[0], {'150'})
        self.assertEqual(self.branches()[0], {'130', '150', '170'})

    def test_branch_list_offers_every_branch_in_the_window(self):
        _, data = self.branches(branch='150')
        self.assertEqual(data['branches'], ['130', '150', '170'])


# ── Users (role) ──────────────────────────────────────────────────────────────

class AdminMSUserRoleTests(_Base):
    URL = '/api/users/staff/'

    def setUp(self):
        super().setUp()
        _, self.p1, _ = make_user('ms_adm_pharm', role='pharmacist', branch=self.b1)
        _, self.p2, _ = make_user('ms_adm_sales', role='salesperson', branch=self.b1)
        _, self.p3, _ = make_user('ms_adm_cc', role='call_center', branch=self.b2)
        self.mine = {self.p1.id, self.p2.id, self.p3.id}

    def picked(self, **params):
        return self.ids(page_size=200, **params) & self.mine

    def test_role_two_one_none(self):
        self.assertEqual(self.picked(role='pharmacist,salesperson'), {self.p1.id, self.p2.id})
        self.assertEqual(self.picked(role='call_center'), {self.p3.id})
        self.assertEqual(self.picked(), self.mine)


# ── Audit log (action) + abuse flags (severity) ───────────────────────────────

class AdminMSAuditTests(_Base):
    LOGS = '/api/audit/logs/'
    FLAGS = '/api/audit/flags/'

    def setUp(self):
        super().setUp()
        _, self.qm, self.qm_c = make_user('ms_adm_qm', role='quality_manager', branch=self.b1)
        self.l1 = AuditLog.objects.create(action='user_login', user=self.admin, user_name='a')
        self.l2 = AuditLog.objects.create(action='user_login_failed', user=self.admin, user_name='a')
        self.l3 = AuditLog.objects.create(action='sync_completed', user=self.admin, user_name='a')
        self.q1 = AuditLog.objects.create(action='user_login', user=self.qm, user_name='q')
        self.mine = {self.l1.id, self.l2.id, self.l3.id, self.q1.id}
        self.f1 = self.flag('critical')
        self.f2 = self.flag('warning')
        self.f3 = self.flag('info')

    def flag(self, severity):
        return AbuseFlag.objects.create(staff=self.admin, flag_type='frequent_cancellations',
                                        severity=severity, status='open', description='x')

    def logs(self, client=None, **params):
        return self.ids(client, self.LOGS, page_size=100, **params) & self.mine

    def test_action_two_one_none(self):
        self.assertEqual(self.logs(action='user_login,user_login_failed'),
                         {self.l1.id, self.l2.id, self.q1.id})
        self.assertEqual(self.logs(action='sync_completed'), {self.l3.id})
        self.assertEqual(self.logs(), self.mine)

    def test_action_never_widens_own_trail(self):
        # a non-admin sees only their own audit trail, whatever actions they tick
        self.assertEqual(self.logs(self.qm_c, action='user_login,user_login_failed,sync_completed'),
                         {self.q1.id})

    def test_severity_two_one_none(self):
        self.assertEqual(self.ids(url=self.FLAGS, severity='critical,warning'), {self.f1.id, self.f2.id})
        self.assertEqual(self.ids(url=self.FLAGS, severity='info'), {self.f3.id})
        self.assertEqual(self.ids(url=self.FLAGS), {self.f1.id, self.f2.id, self.f3.id})


# ── Devices (branch · kind) ───────────────────────────────────────────────────

class AdminMSDeviceTests(_Base):
    URL = '/api/access/devices/'

    def setUp(self):
        super().setUp()
        self.d1 = self.dev('branch_pc', self.b1)
        self.d2 = self.dev('phone', self.b2)
        self.d3 = self.dev('kiosk', self.b3)

    def dev(self, kind, branch):
        return Device.objects.create(secret_hash=dev_api.hash_secret(dev_api.new_secret()), name=kind,
                                     kind=kind, branch=branch)

    def picked(self, **params):
        return self.ids(**params) & {self.d1.id, self.d2.id, self.d3.id}

    def test_kind_two_one_none(self):
        self.assertEqual(self.picked(kind='branch_pc,phone'), {self.d1.id, self.d2.id})
        self.assertEqual(self.picked(kind='kiosk'), {self.d3.id})
        self.assertEqual(self.picked(), {self.d1.id, self.d2.id, self.d3.id})

    def test_branch_two_one(self):
        self.assertEqual(self.picked(branch=f'{self.b1.id},{self.b3.id}'), {self.d1.id, self.d3.id})
        self.assertEqual(self.picked(branch=str(self.b2.id)), {self.d2.id})

    def test_junk_branch_still_refused(self):
        self.assertEqual(self.admin_c.get(self.URL, {'branch': f'{self.b1.id},abc'}).status_code, 400)


# ── Phone alerts log (status · event) ─────────────────────────────────────────

class AdminMSPhoneAlertLogTests(_Base):
    URL = '/api/notifications/phone-alerts/log/'

    def setUp(self):
        super().setUp()
        self.a1 = PhoneAlert.objects.create(event='transfer_hq_submitted', phone='201000000041', status='failed')
        self.a2 = PhoneAlert.objects.create(event='task_assigned', phone='201000000042', status='expired')
        self.a3 = PhoneAlert.objects.create(event='reservation_sourcing', phone='201000000043', status='sent')

    def test_status_two_one_none(self):
        self.assertEqual(self.ids(status='failed,expired'), {self.a1.id, self.a2.id})
        self.assertEqual(self.ids(status='sent'), {self.a3.id})
        self.assertEqual(self.ids(), {self.a1.id, self.a2.id, self.a3.id})

    def test_event_two_one(self):
        self.assertEqual(self.ids(event='transfer_hq_submitted,reservation_sourcing'), {self.a1.id, self.a3.id})
        self.assertEqual(self.ids(event='task_assigned'), {self.a2.id})


# ══════════════════════════════════════════════════════════════════════════════════════════
# C. POS exceptions / incentives / PIC analytics
# ══════════════════════════════════════════════════════════════════════════════════════════

# ── POS exception center ──────────────────────────────────────────────────────

class OpsMSExceptionCenterTests(TestCase):
    URL = '/api/pos-orders/exceptions/'

    def setUp(self):
        self.b1 = make_branch('فرع س1', 'MX01')
        self.b2 = make_branch2('فرع س2', 'MX02')
        self.b3 = make_branch('فرع س3', 'MX03')
        self.admin_c = make_user('msx_admin', role='admin', branch=self.b1, access_all=True)[2]
        self.pharm_c = make_user('msx_pharm', role='pharmacist', branch=self.b1)[2]
        self.o1, self.o2, self.o3 = (self._failed(b) for b in (self.b1, self.b2, self.b3))

    def tearDown(self):
        module_access.clear_cache()

    def _failed(self, br):
        return S.objects.create(branch=br, softech_branchcode=br.softech_branch_id,
                                store_code=br.softech_branch_id[:3], channel='cash', doc_kind='sale',
                                customer_name='T', status=S.STATUS_PUSH_FAILED, doc_value='10')

    def ids(self, client=None, query=''):
        r = (client or self.admin_c).get(self.URL + query)
        self.assertEqual(r.status_code, 200, r.content[:200])
        b = next(x for x in r.json()['buckets'] if x['key'] == 'push_failed')
        return {o['id'] for o in b['orders']}

    def test_branch_two_one_none(self):
        self.assertEqual(self.ids(query=f'?branch={self.b1.id},{self.b3.id}'), {self.o1.id, self.o3.id})
        self.assertEqual(self.ids(query=f'?branch={self.b2.id}'), {self.o2.id})
        self.assertEqual(self.ids(), {self.o1.id, self.o2.id, self.o3.id})

    def test_branch_repeated_param(self):
        self.assertEqual(self.ids(query=f'?branch={self.b1.id}&branch={self.b2.id}'), {self.o1.id, self.o2.id})

    def test_junk_branch_matches_nothing(self):
        self.assertEqual(self.ids(query='?branch=abc'), set())

    def test_never_widens_scope(self):
        # a b1 pharmacist asking for b1 + b2 still sees only b1; asking for b2 alone sees nothing
        self.assertEqual(self.ids(self.pharm_c, f'?branch={self.b1.id},{self.b2.id}'), {self.o1.id})
        self.assertEqual(self.ids(self.pharm_c, f'?branch={self.b2.id}'), set())


class OpsMSLostSalesTrendsTests(TestCase):
    URL = '/api/pos-orders/lost-sales-trends/'

    def setUp(self):
        self.admin_c = make_user('msl_admin', role='admin', branch=make_branch('B170', 'L170'),
                                 access_all=True)[2]
        self.pharm_c = make_user('msl_pharm', role='pharmacist', branch=make_branch('B130', 'L130'))[2]
        today = timezone.now().date()
        PosCancelDaily.objects.bulk_create([
            PosCancelDaily(branch_code=code, day=today, doccode='115', item_code=f'I{code}',
                           item_name=code, events=1, priced_events=1, lost_value=v)
            for code, v in (('L170', '100.00'), ('L130', '20.00'), ('L150', '3.00'))])

    def tearDown(self):
        module_access.clear_cache()

    def codes(self, client=None, **params):
        r = (client or self.admin_c).get(self.URL, {'days': 30, **params})
        self.assertEqual(r.status_code, 200, r.content[:200])
        return {b['branch_code'] for b in r.json()['by_branch']}

    def test_branch_codes_two_one_none(self):
        self.assertEqual(self.codes(branch='L170,L150'), {'L170', 'L150'})
        self.assertEqual(self.codes(branch='L130'), {'L130'})
        self.assertEqual(self.codes(), {'L170', 'L130', 'L150'})

    def test_never_widens_scope(self):
        self.assertEqual(self.codes(self.pharm_c, branch='L130,L170'), {'L130'})
        self.assertEqual(self.codes(self.pharm_c, branch='L170'), set())


# ── Incentives calculation log ───────────────────────────────────────────────

@override_settings(RBAC_ENFORCEMENT='log')
class OpsMSIncentiveLogModeTests(TestCase):
    URL = '/api/incentives/logs/'

    def setUp(self):
        seed_code_matrix()
        _, self.admin_p, self.admin_c = make_user('msi_admin', role='admin', access_all=True)
        self.program = IncentiveProgram.objects.create(name='برنامج م', start_date=D(2026, 9, 1),
                                                       end_date=D(2026, 9, 30))
        self.calc = self._log('calculate')
        self.sim = self._log('simulate')

    def tearDown(self):
        module_access.clear_cache()

    def _log(self, mode):
        return IncentiveCalculationLog.objects.create(program=self.program, triggered_by=self.admin_p,
                                                      period_start=D(2026, 9, 1), period_end=D(2026, 9, 30),
                                                      mode=mode)

    def ids(self, **params):
        r = self.admin_c.get(self.URL, {'program': self.program.id, **params})
        self.assertEqual(r.status_code, 200, r.content[:200])
        return {row['id'] for row in _rows(r)}

    def test_mode_two_one_none(self):
        self.assertEqual(self.ids(mode='calculate,simulate'), {self.calc.id, self.sim.id})
        self.assertEqual(self.ids(mode='simulate'), {self.sim.id})
        self.assertEqual(self.ids(), {self.calc.id, self.sim.id})


# ── PIC Analytics filter bar ─────────────────────────────────────────────────

class OpsMSPicFiltersTests(TestCase):
    """Filters.facts — the one place every PIC Analytics figure reads its rows from."""

    @classmethod
    def setUpTestData(cls):
        cls.ba, cls.bb, cls.bc = (Branch.objects.create(softech_branch_id=c, code=c, name=c, name_ar=c,
                                                        is_operational=True) for c in ('M91', 'M92', 'M93'))
        _, cls.admin_p, cls.admin_c = make_user('msp_admin', role='admin', branch=cls.ba)
        _, cls.mgr_p, cls.mgr_c = make_user('msp_mgr', role='pharmacist', branch=cls.ba)
        cls.mgr_p.allowed_branches.add(cls.bb)
        PicAnalyticsAccess.objects.create(staff=cls.mgr_p, granted_by=cls.admin_p)
        Customer.objects.create(name='a', softech_pic='PA', softech_id='MS-PA', phone='01000000071',
                                segment='vip', softech_ptclassifcode='1')
        Customer.objects.create(name='b', softech_pic='PB', softech_id='MS-PB', phone='01000000072',
                                segment='regular', softech_ptclassifcode='2')
        Customer.objects.create(name='c', softech_pic='PC', softech_id='MS-PC', phone='01000000073',
                                segment='at_risk', softech_ptclassifcode='3')
        cls.day = D(2026, 10, 5)
        cls.fa = cls.fact('PA', cls.ba, 'u1', 'cash', {'10': 60, '50': 40})
        cls.fb = cls.fact('PB', cls.bb, 'u2', 'delivery', {'20': 30})
        cls.fc = cls.fact('PC', cls.bc, 'u3', 'contract', {'50': 5})

    @classmethod
    def fact(cls, pic, branch, sp, chan, cats):
        return PicDayFact.objects.create(pic=pic, day=cls.day, branch=branch, salesperson=sp, channel_bucket=chan,
                                         invoices=1, net=Decimal(sum(cats.values())), lines=1,
                                         net_by_category={k: str(v) for k, v in cats.items()})

    def setUp(self):
        self.mgmt, self.mgr = Access(self.admin_p.user), Access(self.mgr_p.user)

    def flt(self, **kw):
        return Filters(start=D(2026, 10, 1), end=D(2026, 10, 31), **kw)

    def pics(self, f, access=None):
        return set(f.facts(access or self.mgmt).values_list('pic', flat=True))

    def test_salesperson_two_one_none(self):
        self.assertEqual(self.pics(self.flt(salesperson=('u1', 'u3'))), {'PA', 'PC'})
        self.assertEqual(self.pics(self.flt(salesperson='u2')), {'PB'})       # a plain string still works
        self.assertEqual(self.pics(self.flt()), {'PA', 'PB', 'PC'})

    def test_channel_two_one(self):
        self.assertEqual(self.pics(self.flt(channel_bucket='cash,delivery')), {'PA', 'PB'})
        self.assertEqual(self.pics(self.flt(channel_bucket=('contract',))), {'PC'})

    def test_segment_and_customer_type_two_one(self):
        self.assertEqual(self.pics(self.flt(segment=('vip', 'at_risk'))), {'PA', 'PC'})
        self.assertEqual(self.pics(self.flt(segment=('regular',))), {'PB'})
        self.assertEqual(self.pics(self.flt(customer_type=('1', '2'))), {'PA', 'PB'})
        self.assertEqual(self.pics(self.flt(customer_type=('3',))), {'PC'})

    def test_category_two_sums_one_as_before(self):
        rows = {r['pic']: r['enet'] for r in self.flt(category=('10', '20')).facts(self.mgmt).values('pic', 'enet')}
        self.assertEqual(rows, {'PA': Decimal('60'), 'PB': Decimal('30')})
        rows = {r['pic']: r['enet'] for r in self.flt(category=('50',)).facts(self.mgmt).values('pic', 'enet')}
        self.assertEqual(rows, {'PA': Decimal('40'), 'PC': Decimal('5')})
        rows = {r['pic']: r['enet'] for r in self.flt(category=('10', '50')).facts(self.mgmt).values('pic', 'enet')}
        self.assertEqual(rows, {'PA': Decimal('100'), 'PC': Decimal('5')})

    def test_frequency_two_one(self):
        y = timezone.localdate() - timedelta(days=1)
        PicDayFact.objects.filter(pk__in=[self.fa.pk, self.fb.pk, self.fc.pk]).update(day=y)
        for pic, bucket in (('PA', 'm1'), ('PB', 'm2'), ('PC', 'm3')):
            PicRollup.objects.create(pic=pic, as_of=y, cycle_bucket=bucket)
        self.assertEqual(self.pics(Filters(start=y, end=y, frequency=('m1', 'm3'))), {'PA', 'PC'})
        self.assertEqual(self.pics(Filters(start=y, end=y, frequency=('m2',))), {'PB'})
        self.assertEqual(self.pics(Filters(start=y, end=y)), {'PA', 'PB', 'PC'})

    def test_from_request_comma_and_repeated(self):
        rf = RequestFactory()
        f = Filters.from_request(rf.get('/x', {'from': '2026-10-01', 'to': '2026-10-31',
                                               'salesperson': 'u1,u2', 'agent': '11'}), self.mgmt)
        self.assertEqual((f.salesperson, f.agent_ext, f.channel_bucket), (('u1', 'u2'), ('11',), ()))
        f = Filters.from_request(rf.get('/x?from=2026-10-01&to=2026-10-31&branch=1&branch=2'
                                        '&segment=vip&segment=regular'), self.mgmt)
        self.assertEqual((f.branch_ids, f.segment), ({1, 2}, ('vip', 'regular')))
        with self.assertRaises(FilterError):     # a non-number branch is refused, as before
            Filters.from_request(rf.get('/x', {'from': '2026-10-01', 'to': '2026-10-31', 'branch': '1,x'}), self.mgmt)

    def test_branch_two_one_none_management(self):
        self.assertEqual(self.pics(self.flt(branch_ids={self.ba.id, self.bc.id})), {'PA', 'PC'})
        self.assertEqual(self.pics(self.flt(branch_ids={self.bb.id})), {'PB'})
        self.assertEqual(self.pics(self.flt()), {'PA', 'PB', 'PC'})

    def test_branch_manager_never_widens(self):
        # the manager's branches are ba (home) + bb (allowed); bc is never theirs
        self.assertEqual(self.pics(self.flt(), self.mgr), {'PA', 'PB'})
        self.assertEqual(self.pics(self.flt(branch_ids={self.ba.id, self.bc.id}), self.mgr), {'PA'})
        self.assertEqual(self.pics(self.flt(branch_ids={self.bc.id}), self.mgr), set())

    def test_api_multi_values_end_to_end(self):
        base = '/api/pic-analytics/pics/?from=2026-10-01&to=2026-10-31'
        r = self.admin_c.get(base + '&salesperson=u1,u3&channel=cash&channel=contract')
        self.assertEqual(r.status_code, 200, r.content[:200])
        self.assertEqual({row['pic'] for row in r.json()['rows']}, {'PA', 'PC'})
        r = self.mgr_c.get(base + f'&branch={self.ba.id},{self.bc.id}')
        self.assertEqual(r.status_code, 200, r.content[:200])
        self.assertEqual({row['pic'] for row in r.json()['rows']}, {'PA'})
