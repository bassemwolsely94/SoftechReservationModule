"""
apps/tests/test_cash_view.py

P-40 (docs/product-review/06_SPEC_P-40_13_week_cash_view.md): the 13-week cash view. Weeks run Saturday–Friday (owner
2026-10-31); dated items on a non-banking day move to the next banking day. Lines: cash and delivery sales (8-week
mean / min / max), contract collections (P-41), post-dated supplier bank cheques (financialdoccode 20, date = cheqdate),
supplier payables by due date (P-42) netted against the same supplier's unallocated post-dated cheques, new purchases
(13-week run rate or the "what if" budget) at the category credit days, fixed outflows, planned cheques; memo lines
(internal accounts, early pay, payables without terms) never change the closings. Read-only toward SOFTECH.
"""
import datetime as dt
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.tests.factories import make_admin, make_branch, make_customer, make_user

D = dt.date
AS_OF = D(2026, 10, 31)        # Saturday → week 1 = 31 Oct – 6 Nov


def _party(code, name='', ptype='supplier'):
    from apps.finance.models import ReconParty
    return ReconParty.objects.get_or_create(softech_personcode=code,
                                            defaults={'party_type': ptype, 'name': name or code})[0]


def _inv(party, no, day, value, pay='0', doccode='10'):
    from apps.finance.models import APInvoice
    return APInvoice.objects.create(party=party, branchcode='100', doccode=doccode, docnumber=str(no), docdate=day,
                                    doc_value=Decimal(value), doc_value_pay=Decimal(pay), party_type=party.party_type)


def _cheque(party, sno, day, amount, fdc='20'):
    from apps.finance.models import Payment
    return Payment.objects.create(party=party, branchcode='100', cheqsno=sno, cheqtype='20', financial_doc_code=fdc,
                                  direction='out', party_type='supplier', voucher_date=day, amount=Decimal(amount))


def _term(party, days, category='any'):
    from apps.finance.models import SupplierTerm
    return SupplierTerm.objects.create(party=party, category=category, credit_days=days, effective_from=D(2020, 1, 1))


def _line(view, key):
    return next(x for x in view['lines'] if x['key'] == key)


def _fixture():
    """Opening 100,000 · 565 owes 8,000 due 31 Oct (→ Sun 1 Nov) with a 5,000 unallocated cheque on 10 Nov ·
    30 has a 2,000 cheque on Sat 14 Nov (→ Sun 15 Nov) already allocated to its paid invoice · contract 4227, 6,000
    on 5 Oct, 30 agreed days from month end → Mon 30 Nov · rent 10,000 on the 5th · 786 owes 1,500 with no terms ·
    internal 1268 owes 9,999 with a 4,444 cheque."""
    from apps.finance.models import Allocation, CashOpeningBalance, ContractReceivableTerms, FixedOutflow
    from apps.finance.supplier_terms import recompute
    CashOpeningBalance.objects.create(as_of=D(2026, 10, 30), amount=Decimal('100000'))
    p565 = _party('565', 'Pharma Overseas')
    _term(p565, 30)
    _inv(p565, 1, D(2026, 10, 1), '8000')
    _cheque(p565, 1, D(2026, 11, 10), '5000')
    p30 = _party('30', 'Ramco')
    paid = _inv(p30, 2, D(2026, 10, 2), '2000', pay='2000')
    Allocation.objects.create(payment=_cheque(p30, 2, D(2026, 11, 14), '2000'), invoice=paid, amount=Decimal('2000'))
    c = _party('4227', 'عاملين', ptype='customer')
    ContractReceivableTerms.objects.create(personcode='4227', party=c, name='عاملين', agreed_days=30)
    _inv(c, 3, D(2026, 10, 5), '6000', doccode='115')
    FixedOutflow.objects.create(label='إيجار', category='rent', amount=Decimal('10000'), frequency='monthly',
                                day_of_month=5, start=D(2026, 1, 1))
    _inv(_party('786', 'Egy Drug'), 4, D(2026, 10, 3), '1500')
    internal = _party('1268', 'كوبونات')
    _inv(internal, 5, D(2026, 10, 4), '9999')
    _cheque(internal, 5, D(2026, 11, 3), '4444')
    recompute()


class CashViewFixtureTests(TestCase):

    def setUp(self):
        _fixture()

    def test_closings_to_the_piastre(self):
        from apps.finance.cash_view import build_cash_view
        v = build_cash_view(AS_OF)
        self.assertEqual(v['weeks'][0]['start'], AS_OF)
        self.assertEqual(len(v['weeks']), 13)
        base = [Decimal(x) for x in ('87000', '82000', '80000', '80000', '86000', '76000', '76000', '76000', '76000',
                                     '66000', '66000', '66000', '66000')]
        self.assertEqual(v['closing']['base'], base)
        self.assertEqual(v['closing']['low'], [b - Decimal('1500') for b in base])     # no-terms in week 1 only
        self.assertEqual(v['closing']['high'], base)

    def test_each_line_in_its_week(self):
        from apps.finance.cash_view import build_cash_view
        v = build_cash_view(AS_OF)
        self.assertEqual(_line(v, 'supplier_cheques')['base'][1:3], [Decimal('5000'), Decimal('2000')])
        self.assertEqual(_line(v, 'supplier_payables')['base'][0], Decimal('3000'))     # 8,000 − the 5,000 cheque
        self.assertEqual(sum(_line(v, 'supplier_payables')['base']), Decimal('3000'))   # the paid invoice is not here
        self.assertEqual(_line(v, 'contract_collections')['base'][4], Decimal('6000'))
        fixed = _line(v, 'fixed_outflows')['base']
        self.assertEqual((fixed[0], fixed[5], fixed[9]), (Decimal('10000'),) * 3)       # 5 Nov · Sun 6 Dec · 5 Jan
        self.assertEqual(_line(v, 'no_terms')['base'][0], Decimal('1500'))
        internal = _line(v, 'internal_accounts')
        self.assertEqual(internal['group'], 'memo')
        # its 4,444 cheque pays part of its own 9,999 (netted like real suppliers): 5,555 open + 4,444 cheque, apart
        self.assertEqual(sum(internal['base']), Decimal('9999'))

    def test_drill_down_rows_add_up_to_the_cell(self):
        from apps.finance.cash_view import build_cash_view, line_rows
        v = build_cash_view(AS_OF)
        rows = line_rows(AS_OF, 'supplier_payables', 0)
        self.assertEqual(sum(Decimal(str(r['amount'])) for r in rows), _line(v, 'supplier_payables')['base'][0])

    def test_no_opening_no_closings(self):
        from apps.finance.cash_view import build_cash_view
        from apps.finance.models import CashOpeningBalance
        CashOpeningBalance.objects.all().delete()
        v = build_cash_view(AS_OF)
        self.assertIsNone(v['opening'])
        self.assertEqual(v['closing'], {'low': None, 'base': None, 'high': None})
        self.assertEqual(v['net']['base'][0], Decimal('-13000'))


class SalesLineTests(TestCase):

    def test_eight_week_mean_min_max_net_of_returns(self):
        from apps.customers.models import PurchaseHistory
        from apps.finance.cash_view import build_cash_view
        branch, cust = make_branch(), make_customer()
        n = 0

        def sale(day, value, channel='91', doc='115'):
            nonlocal n
            n += 1
            PurchaseHistory.objects.create(customer=cust, branch=branch, softech_invoice_id=f'ph{n}', doc_code=doc,
                                           total_amount=Decimal(value), sales_channel=channel,
                                           invoice_date=timezone.make_aware(dt.datetime.combine(day, dt.time(13))))
        for i in range(8):                                     # weeks starting 5 Sep … 24 Oct
            sale(D(2026, 9, 5) + dt.timedelta(days=7 * i + 2), str(1000 * (i + 1)), channel='91' if i % 2 else '90')
        sale(D(2026, 10, 28), '500', doc='30')                 # a return in the last week → 7,500
        sale(D(2026, 10, 28), '99999', channel='10')           # contract sales are not cash
        sale(D(2026, 8, 20), '99999')                          # older than 8 weeks
        sales = _line(build_cash_view(AS_OF), 'cash_sales')
        self.assertEqual((sales['low'][0], sales['base'][0], sales['high'][0]),
                         (Decimal('1000'), Decimal('4437.50'), Decimal('7500')))


class PurchasesLineTests(TestCase):

    def setUp(self):
        from apps.catalog.models import Item
        from apps.procurement.models import PurchaseLine
        Item.objects.create(softech_id='LOC', name='local', is_imported=False)
        self.p = _party('565', 'Pharma Overseas')
        _term(self.p, 30)
        for i in range(13):                                    # 1,000 a week over 1 Aug … 30 Oct
            day = D(2026, 8, 1) + dt.timedelta(days=7 * i + 1)
            PurchaseLine.objects.create(branch_code='100', supplier_code='565', doc_number=str(100 + i), doc_date=day,
                                        item_code='LOC', item=Item.objects.get(), doccode='10',
                                        net_value=Decimal('1000'), raw_value=Decimal('1000'))

    def test_run_rate_at_credit_days_and_what_if_changes_only_this_line(self):
        from apps.finance.cash_view import build_cash_view
        from apps.finance.models import CashViewSnapshot
        base = build_cash_view(AS_OF)
        o3 = _line(base, 'new_purchases')['base']
        # bought in week k, due 30 days later = week k + 4; week 1 counts only the 6 days after as_of
        self.assertEqual(o3[:4], [Decimal('0')] * 4)
        self.assertEqual((o3[4], o3[5], o3[12]), (Decimal('857.14'), Decimal('1000.00'), Decimal('1000.00')))
        what_if = build_cash_view(AS_OF, purchase_budget_weekly=Decimal('7000'))
        self.assertEqual(_line(what_if, 'new_purchases')['base'][5], Decimal('7000.00'))
        for key in ('supplier_payables', 'supplier_cheques', 'fixed_outflows', 'cash_sales'):
            self.assertEqual(_line(what_if, key)['base'], _line(base, key)['base'])
        self.assertFalse(CashViewSnapshot.objects.exists())


class PlannedChequesTests(TestCase):

    def test_pending_instalments_of_active_plans_only(self):
        from apps.cheques.models import ChequeInstalment, ChequePlan
        from apps.finance.cash_view import build_cash_view

        def plan(status):
            return ChequePlan.objects.create(title='خطة', status=status, payee_name='مورد', total_amount=Decimal('900'),
                                             first_due_date=D(2026, 11, 9))
        active, draft = plan('active'), plan('draft')
        for no, (p, st, amt) in enumerate(((active, 'pending', '300'), (active, 'issued', '400'),
                                            (draft, 'pending', '500')), start=1):
            ChequeInstalment.objects.create(plan=p, instalment_no=no, amount=Decimal(amt), nominal_date=D(2026, 11, 9),
                                            due_date=D(2026, 11, 9), status=st)
        line = _line(build_cash_view(AS_OF), 'planned_cheques')
        self.assertEqual(line['base'][1], Decimal('300'))
        self.assertEqual(sum(line['base']), Decimal('300'))


class SnapshotTests(TestCase):

    def test_weekly_snapshot_idempotent_and_scheduled(self):
        from unittest import mock
        from apps.finance.models import CashViewSnapshot
        from apps.sync import tasks
        tasks._run_cash_view_snapshot()
        tasks._run_cash_view_snapshot()
        self.assertEqual(CashViewSnapshot.objects.count(), 1)

        from .test_scheduler_jobs import _FakeScheduler
        captured = {}

        class _Capture(_FakeScheduler):
            def add_job(self, func, trigger, *args, **kwargs):
                captured[kwargs.get('id')] = kwargs
                super().add_job(func, trigger, *args, **kwargs)

        with mock.patch.object(tasks, 'BackgroundScheduler', _Capture), \
             mock.patch.object(tasks, '_patch_apscheduler_for_python312', lambda: None), \
             mock.patch.object(tasks, '_scheduler', None):
            tasks.start_scheduler()
        job = captured['cash_view_weekly_snapshot']
        self.assertEqual((job['day_of_week'], job['hour']), ('sat', 6))


class CashApiTests(TestCase):

    URL = '/api/finance/cash-view/'

    def setUp(self):
        from apps.tests.security.fixtures import seed_code_matrix
        from core.middleware import module_access
        seed_code_matrix()
        module_access.clear_cache()
        self.addCleanup(module_access.clear_cache)
        _, self.staff, self.admin = make_admin('cv_admin')
        _fixture()

    def test_view_drill_inputs_audit_export(self):
        from apps.finance.models import FixedOutflow, ReconAuditEvent
        r = self.admin.get(self.URL)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data['closing']['base']), 13)
        r = self.admin.get(self.URL + 'lines/supplier_cheques/?week=1')
        self.assertEqual(sum(x['amount'] for x in r.data['rows']), 5000)
        r = self.admin.post(self.URL + 'opening-balance/', {'as_of': '2026-10-31', 'amount': '120000',
                                                            'note': 'خزينة + بنك'}, format='json')
        self.assertEqual(r.status_code, 201)
        r = self.admin.post(self.URL + 'fixed-outflows/', {'label': 'مرتبات', 'category': 'salaries',
                                                           'amount': '50000', 'frequency': 'monthly',
                                                           'day_of_month': 28, 'start': '2026-11-01'}, format='json')
        self.assertEqual(r.status_code, 201)
        r = self.admin.patch(self.URL + 'fixed-outflows/', {'id': r.data['id'], 'amount': '55000'}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(FixedOutflow.objects.get(label='مرتبات').amount, Decimal('55000'))
        events = ReconAuditEvent.objects.filter(action='cash_input_changed')
        self.assertEqual(events.count(), 3)
        self.assertEqual(events.order_by('performed_at').last().before_state['amount'], '50000.00')
        self.assertEqual(self.admin.post(self.URL + 'fixed-outflows/', {'label': 'x', 'category': 'bogus',
                                                                        'amount': '1', 'frequency': 'monthly'},
                                         format='json').status_code, 400)
        self.assertEqual(self.admin.get(self.URL + '?purchase_budget_weekly=5000').status_code, 200)
        self.assertIn('spreadsheetml', self.admin.get(self.URL + 'export/')['Content-Type'])

    def test_branch_user_and_non_finance_refused(self):
        _, _, ph = make_user('cv_ph', role='pharmacist', branch=make_branch('B', '130'))
        _, _, sales = make_user('cv_sales', role='salesperson')
        for c in (ph, sales):
            for path in ('', 'lines/supplier_cheques/?week=1', 'opening-balance/', 'fixed-outflows/', 'export/'):
                self.assertEqual(c.get(self.URL + path).status_code, 403, path)
            self.assertEqual(c.post(self.URL + 'opening-balance/', {'as_of': '2026-10-31', 'amount': '1'},
                                    format='json').status_code, 403)
