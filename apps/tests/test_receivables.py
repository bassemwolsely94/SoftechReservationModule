"""
apps/tests/test_receivables.py

P-41 (docs/product-review/06_SPEC_P-41_contract_receivables.md): contract receivables from the customer side of the
A/P–A/R mirror. Read-only toward SOFTECH. Owner decisions 2026-10-31: agreed days count from the END of the invoice
month; where SOFTECH links under 70 % of a contract's sales to receipts, collection days are estimated by paying the
oldest invoices first (FIFO), labelled as an estimate; insurance co-pay accounts are grouped by company.
"""
import datetime as dt
import io
from decimal import Decimal
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, TestCase

from apps.tests.factories import make_admin, make_user

D = dt.date
AS_OF = D(2026, 10, 31)


def _party(code='4227', name='ك(عاملين)_جنوب القاهرة توزيع', balance='0'):
    from apps.finance.models import ReconParty
    return ReconParty.objects.create(party_type='customer', softech_personcode=code, name=name,
                                     softech_balance=Decimal(balance))


def _inv(party, no, day, value, doccode='115', pay='0'):
    from apps.finance.models import APInvoice
    return APInvoice.objects.create(party=party, branchcode='100', doccode=doccode, docnumber=str(no), docdate=day,
                                    doc_value=Decimal(value), doc_value_pay=Decimal(pay), party_type='customer',
                                    is_return=(doccode == '30'))


def _pay(party, sno, day, amount, cheqtype='10'):
    from apps.finance.models import Payment
    return Payment.objects.create(party=party, branchcode='100', cheqsno=sno, cheqtype=cheqtype, direction='in',
                                  party_type='customer', voucher_date=day, amount=Decimal(amount))


def _alloc(pay, inv, amount, origin='softech'):
    from apps.finance.models import Allocation
    return Allocation.objects.create(payment=pay, invoice=inv, amount=Decimal(amount), origin=origin)


class GroupNameTests(SimpleTestCase):

    def test_co_pay_suffix_is_dropped(self):
        from apps.finance.receivables import group_name
        self.assertEqual(group_name('D M S 10%'), 'D M S')
        self.assertEqual(group_name('D M S 0% - بدون تحمل صفر%'), 'D M S')
        self.assertEqual(group_name('ايجيكير بدون تحمل صفر%'), 'ايجيكير')
        self.assertEqual(group_name('Med sure 25%'), 'Med sure')
        self.assertEqual(group_name('ك(عاملين)_جنوب القاهرة توزيع'), 'ك(عاملين)_جنوب القاهرة توزيع')


class EngineTests(TestCase):

    def setUp(self):
        from apps.finance.models import ContractReceivableTerms
        self.p = _party(balance='-2100')
        self.terms = ContractReceivableTerms.objects.create(personcode='4227', party=self.p, name=self.p.name,
                                                            group_name='جنوب القاهرة', agreed_days=45)
        self.a = _inv(self.p, 1, D(2026, 8, 10), '1000', pay='1000')
        self.b = _inv(self.p, 2, D(2026, 8, 20), '2000')
        self.c = _inv(self.p, 3, D(2026, 10, 20), '500')
        _inv(self.p, 9, D(2026, 9, 20), '100', doccode='30')
        self.pay = _pay(self.p, 50, D(2026, 9, 25), '1300')
        _alloc(self.pay, self.a, '1000')

    def test_open_invoices_aging_and_overdue(self):
        from apps.finance.receivables import open_invoices
        rows = {r['docnumber']: r for r in open_invoices('4227', as_of=AS_OF)}
        self.assertEqual(set(rows), {'2', '3'})
        b = rows['2']
        self.assertEqual((b['open'], b['bucket'], b['expected_date']), (Decimal('2000'), '61-90', D(2026, 10, 15)))
        self.assertTrue(b['overdue'])                   # Aug month end + 45 days = 15 Oct < 31 Oct
        self.assertEqual(b['expected_basis'], 'agreed')
        self.assertFalse(rows['3']['overdue'])          # Oct month end + 45 = 15 Dec
        self.assertEqual(rows['3']['bucket'], '0-30')

    def test_fifo_estimate_when_links_are_thin(self):
        from apps.finance.receivables import measured_days
        m = measured_days('4227', as_of=AS_OF)
        # links cover 1000 of 3500 sales (28.6 %) → oldest-first: 1000 × 46 + 300 × 36 over 1300 = 43.7
        self.assertEqual((m['method'], m['days'], m['coverage_pct']), ('fifo', Decimal('43.7'), Decimal('28.6')))

    def test_linked_days_when_coverage_is_high(self):
        from apps.finance.receivables import measured_days
        _alloc(self.pay, self.b, '300')
        p2 = _pay(self.p, 51, D(2026, 10, 30), '1900')
        _alloc(p2, self.b, '1700')
        _alloc(p2, self.c, '200')
        m = measured_days('4227', as_of=AS_OF)
        # (1000×46 + 300×36 + 1700×71 + 200×10) / 3200 = 56.09 → 56.1; coverage 3200 / 3500 = 91.4 %
        self.assertEqual((m['method'], m['days'], m['max_days']), ('linked', Decimal('56.1'), 71))

    def test_contract_summary_balances_with_softech(self):
        from apps.finance.receivables import contract_summary
        s = contract_summary('4227', as_of=AS_OF)
        self.assertEqual((s['open'], s['on_account'], s['open_returns']),
                         (Decimal('2500'), Decimal('300'), Decimal('100')))
        self.assertEqual(s['net_receivable'], Decimal('2100'))
        self.assertEqual(s['softech_receivable'], Decimal('2100'))   # SOFTECH −2100 in the owed convention
        self.assertEqual(s['difference'], Decimal('0'))
        self.assertEqual(s['overdue'], Decimal('2000'))
        self.assertEqual(s['buckets']['61-90'], Decimal('2000'))

    def test_no_agreed_days_falls_back_to_measured_and_says_so(self):
        from apps.finance.receivables import open_invoices
        self.terms.agreed_days = None
        self.terms.save()
        b = {r['docnumber']: r for r in open_invoices('4227', as_of=AS_OF)}['2']
        self.assertEqual(b['expected_basis'], 'measured')
        self.assertEqual(b['expected_date'], D(2026, 8, 20) + dt.timedelta(days=44))   # 43.7 → 44 days

    def test_groups_add_up(self):
        from apps.finance.models import ContractReceivableTerms
        from apps.finance.receivables import summary
        p2 = _party('4288', 'ك(معاشات)_جنوب القاهرة توزيع', balance='-50')
        ContractReceivableTerms.objects.create(personcode='4288', party=p2, name=p2.name, group_name='جنوب القاهرة')
        _inv(p2, 7, D(2026, 10, 1), '50')
        s = summary(as_of=AS_OF)
        g = {x['group_name']: x for x in s['groups']}['جنوب القاهرة']
        self.assertEqual((g['open'], len(g['contracts'])), (Decimal('2550'), 2))
        self.assertEqual(s['totals']['net_receivable'], Decimal('2150'))


class RegistryTests(TestCase):

    def test_seed_groups_co_pay_accounts_and_is_idempotent(self):
        from apps.finance.models import ContractReceivableTerms
        from apps.finance.receivables import seed_terms
        with mock.patch('apps.finance.receivables_probe.contract_personcodes', return_value=['4473', '4474', '4227']), \
             mock.patch('apps.finance.receivables.get_party_balances', return_value=[
                 {'personcode': '4473', 'personname': 'D M S 10%'}, {'personcode': '4474', 'personname': 'D M S 20%'},
                 {'personcode': '4227', 'personname': 'ك(عاملين)_جنوب القاهرة توزيع'}]):
            self.assertEqual(seed_terms(), 3)
            self.assertEqual(seed_terms(), 0)
        self.assertEqual(set(ContractReceivableTerms.objects.filter(group_name='D M S')
                             .values_list('personcode', flat=True)), {'4473', '4474'})


class SyncTests(TestCase):

    def test_customer_sync_needs_a_contract_list(self):
        with self.assertRaises(CommandError):
            call_command('sync_ap_reconciliation', '--party-type', 'customer', stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command('sync_ap_reconciliation', '--party-type', 'both', stdout=io.StringIO())

    def test_contracts_sync_reads_one_tracked_account_at_a_time(self):
        from apps.finance.models import ContractReceivableTerms, ReconciliationRun
        from apps.finance.queries import sybase_reconciliation as q
        ContractReceivableTerms.objects.create(personcode='4227', name='A')
        ContractReceivableTerms.objects.create(personcode='4288', name='B')
        ContractReceivableTerms.objects.create(personcode='9999', name='C', is_tracked=False)
        seen = []

        def rec(party_type, date_from, date_to, branch=None, personcode=None, **kw):
            seen.append((party_type, personcode))
            return []
        with mock.patch.object(q, 'get_invoices', rec), mock.patch.object(q, 'get_vouchers', rec), \
             mock.patch.object(q, 'get_allocations', rec), mock.patch.object(q, 'get_party_balances', return_value=[]):
            call_command('sync_ap_reconciliation', '--party-type', 'customer', '--contracts', stdout=io.StringIO())
        self.assertEqual({pc for _, pc in seen}, {'4227', '4288'})
        self.assertTrue(all(pt == 'customer' for pt, _ in seen))
        self.assertEqual(ReconciliationRun.objects.get().party_type, 'customer')


class FreshnessTests(TestCase):

    def test_customer_runs_feed_ar_contracts_not_ap(self):
        from django.utils import timezone
        from apps.finance.models import ReconciliationRun
        from apps.sync.freshness import _SOURCES, DOMAINS
        self.assertIn('ar_contracts', DOMAINS)
        ReconciliationRun.objects.create(status='success', party_type='customer', finished_at=timezone.now())
        self.assertIsNone(_SOURCES['ap_reconciliation']()['last_success_at'])
        self.assertIsNotNone(_SOURCES['ar_contracts']()['last_success_at'])


class WriterGuardTests(TestCase):

    def test_customer_allocation_is_refused(self):
        from apps.finance.recon_writer import ReconWriteError, build_plan
        p = _party()
        a = _alloc(_pay(p, 1, D(2026, 10, 1), '10'), _inv(p, 1, D(2026, 9, 1), '10'), '10', origin='approved')
        with self.assertRaises(ReconWriteError):
            build_plan(a)


class ApiTests(TestCase):

    URL = '/api/finance/receivables/'

    def setUp(self):
        from apps.finance.models import ContractReceivableTerms
        from apps.tests.security.fixtures import seed_code_matrix
        from core.middleware import module_access
        seed_code_matrix()
        module_access.clear_cache()
        self.addCleanup(module_access.clear_cache)
        self.p = _party(balance='-500')
        self.t = ContractReceivableTerms.objects.create(personcode='4227', party=self.p, name=self.p.name,
                                                        group_name='جنوب القاهرة')
        _inv(self.p, 1, D(2026, 9, 1), '500')
        _, self.admin_staff, self.admin = make_admin('rcv_admin')

    def test_summary_invoices_terms_export(self):
        r = self.admin.get(self.URL + 'summary/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['totals']['open'], 500.0)
        self.assertEqual(self.admin.get(self.URL + '4227/invoices/').status_code, 200)
        self.assertEqual(self.admin.get(self.URL + 'terms/').status_code, 200)
        r = self.admin.get(self.URL + 'export/')
        self.assertEqual(r.status_code, 200)
        self.assertIn('spreadsheetml', r['Content-Type'])

    def test_terms_change_is_audited(self):
        from apps.finance.models import ReconAuditEvent
        r = self.admin.patch(self.URL + 'terms/', {'personcode': '4227', 'agreed_days': 60}, format='json')
        self.assertEqual(r.status_code, 200)
        self.t.refresh_from_db()
        self.assertEqual((self.t.agreed_days, self.t.entered_by_id), (60, self.admin_staff.pk))
        ev = ReconAuditEvent.objects.get(action='contract_terms_changed')
        self.assertEqual((ev.before_state.get('agreed_days'), ev.after_state.get('agreed_days')), (None, 60))
        self.assertEqual(self.admin.patch(self.URL + 'terms/', {'personcode': '4227', 'agreed_days': -3},
                                          format='json').status_code, 400)

    def test_branch_user_and_non_finance_refused(self):
        from apps.tests.factories import make_branch
        _, _, ph = make_user('rcv_ph', role='pharmacist', branch=make_branch('B', '130'))
        _, _, sales = make_user('rcv_sales', role='salesperson')
        for c in (ph, sales):
            self.assertEqual(c.get(self.URL + 'summary/').status_code, 403)
            self.assertEqual(c.patch(self.URL + 'terms/', {'personcode': '4227', 'agreed_days': 1},
                                     format='json').status_code, 403)
