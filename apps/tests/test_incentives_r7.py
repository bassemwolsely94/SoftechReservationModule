"""
Incentives (apps/incentives) — R7 per-app tests.

One view test per router registration / view in apps/incentives/urls.py, the payroll gate on
top of the matrix (pharmacist / supervisor refused), and the payroll rule end to end:
calculate (percent rule, in-period return nets the sale) → finalize (payout = transactions +
adjustments) → receipt. The SOFTECH reads (_fetch_rows, _fetch_cross_period_returns,
fetch_near_expiry_stock) are mocked; nothing connects.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings

from apps.incentives.models import (
    AdjustmentEntry, IncentiveCalculationLog, IncentiveProgram, IncentiveRule, IncentiveRuleItem,
    IncentiveSettlement, IncentiveTransaction, SalesTarget,
)
from apps.tests.factories import make_item, make_user
from apps.tests.security.fixtures import bearer_client, seed_code_matrix
from core.middleware import module_access

API = '/api/incentives/'
PERIOD = {'period_start': '2026-09-01', 'period_end': '2026-09-30'}
P0, P1 = date(2026, 9, 1), date(2026, 9, 30)


def _row(doc, person, day, item, qty, price, ref=None, expiry=None):
    return (doc, person, datetime(2026, 9, day, 10, 0), '120', ref, item, f'name {item}',
            Decimal(qty), Decimal(price), expiry)


SALES = [
    _row('D1', 'P1', 10, 'A1', '2', '50'),        # 2 × 50 × 10% = 10.0000
    _row('D2', 'P1', 11, 'B9', '1', '80'),        # no rule for B9 → no transaction
    _row('D3', 'ZZ', 11, 'A1', '1', '50'),        # unknown usercode → skipped
]
RETURNS = [_row('R1', 'P1', 12, 'A1', '1', '50', ref='D1')]   # −(1 × 50 × 10%) = −5.0000


@override_settings(RBAC_ENFORCEMENT='log')
class _Base(TestCase):

    def setUp(self):
        seed_code_matrix()
        self.admin_user, self.admin_profile, _ = make_user('r7inc_admin', role='admin', access_all=True)
        self.admin = bearer_client(self.admin_user)
        _, self.rep, _ = make_user('r7inc_rep', role='salesperson')
        self.rep.softech_user_id = 'P1'
        self.rep.save()
        self.program = IncentiveProgram.objects.create(name='R7 برنامج', start_date=P0, end_date=P1)
        self.rule = IncentiveRule.objects.create(program=self.program, rule_name='A1 10%', item_code='A1',
                                                 incentive_type='percent', incentive_value=Decimal('10'))

    def tearDown(self):
        module_access.clear_cache()

    def _url(self, suffix=''):
        return f'{API}programs/{self.program.pk}/{suffix}'

    def _calculate(self, client=None, **extra):
        with mock.patch('apps.incentives.engine._fetch_rows', side_effect=[SALES, RETURNS]), \
                mock.patch('apps.incentives.engine._fetch_cross_period_returns', return_value=[]):
            return (client or self.admin).post(self._url('calculate/'), {**PERIOD, **extra}, format='json')


class PayrollRuleTests(_Base):
    """The business rule: net incentive per person, then payout = transactions + adjustments."""

    def test_calculate_nets_the_return_against_the_sale(self):
        r = self._calculate()
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertEqual(body['created'], 2)
        self.assertEqual(body['total_by_user'], {str(self.rep.pk): 5.0})
        self.assertEqual(body['skipped_person_codes'], ['ZZ'])
        sale = IncentiveTransaction.objects.get(doc_type='sale')
        ret = IncentiveTransaction.objects.get(doc_type='return')
        self.assertEqual((sale.incentive_amount, sale.quantity, sale.is_reversed),
                         (Decimal('10.0000'), Decimal('2.000'), False))
        self.assertEqual((ret.incentive_amount, ret.quantity, ret.ref_doc_no),
                         (Decimal('-5.0000'), Decimal('-1.000'), 'D1'))
        log = IncentiveCalculationLog.objects.get(pk=body['log_id'])
        self.assertEqual((log.mode, log.transactions_created), ('calculate', 2))

    def test_finalize_pays_transactions_plus_adjustments_and_locks_the_period(self):
        self._calculate()
        AdjustmentEntry.objects.create(program=self.program, user=self.rep, period_start=P0, period_end=P1,
                                       amount=Decimal('2.50'), reason='bonus')
        r = self.admin.post(self._url('finalize/'), {**PERIOD, 'notes': 'Sep'}, format='json')
        self.assertEqual(r.json()['finalized_count'], 1)
        sett = IncentiveSettlement.objects.get()
        self.assertEqual((sett.total_incentive, sett.total_adjustments, sett.final_payout),
                         (Decimal('5.00'), Decimal('2.50'), Decimal('7.50')))
        self.assertEqual((sett.transaction_count, sett.is_finalized, sett.notes), (2, True, 'Sep'))
        # finalizing again skips it; recalculating needs force
        self.assertEqual(self.admin.post(self._url('finalize/'), PERIOD, format='json').json()['skipped_count'], 1)
        self.assertEqual(self._calculate().status_code, 409)
        self.assertEqual(self._calculate(force=True).status_code, 200)
        sett.refresh_from_db()
        self.assertFalse(sett.is_finalized)

    def test_finalize_without_transactions_is_400(self):
        self.assertEqual(self.admin.post(self._url('finalize/'), PERIOD, format='json').status_code, 400)
        self.assertEqual(self.admin.post(self._url('finalize/'), {}, format='json').status_code, 400)


class ProgramViewTests(_Base):

    def test_list_create_retrieve(self):
        r = self.admin.post(f'{API}programs/', {'name': 'جديد', 'start_date': '2026-10-01',
                                                'end_date': '2026-10-31'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(IncentiveProgram.objects.get(pk=r.json()['id']).created_by, self.admin_profile)
        rows = self.admin.get(f'{API}programs/', {'is_active': 'true'}).json()
        rows = rows.get('results', rows)
        self.assertEqual(len(rows), 2)
        self.assertEqual(self.admin.get(self._url()).json()['rules'][0]['item_code'], 'A1')

    def test_calculate_validates_the_period(self):
        self.assertEqual(self.admin.post(self._url('calculate/'), {'period_start': '2026-09-30',
                                                                   'period_end': '2026-09-01'},
                                         format='json').status_code, 400)
        self.assertEqual(self.admin.post(self._url('calculate/'), {**PERIOD, 'user_ids': ['x']},
                                         format='json').status_code, 400)

    def test_simulate_writes_no_transactions(self):
        with mock.patch('apps.incentives.engine._fetch_rows', side_effect=[SALES, RETURNS]), \
                mock.patch('apps.incentives.engine._fetch_cross_period_returns', return_value=[]):
            r = self.admin.post(self._url('simulate/'), {**PERIOD, 'user_ids': [self.rep.pk]}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()['simulated'])
        self.assertEqual(r.json()['total_by_user'], {str(self.rep.pk): 5.0})
        self.assertFalse(IncentiveTransaction.objects.exists())
        self.assertEqual(IncentiveCalculationLog.objects.get().mode, 'simulate')

    def test_simulate_softech_down_is_500_with_message(self):
        with mock.patch('apps.incentives.engine._fetch_rows', side_effect=ConnectionError('down')):
            r = self.admin.post(self._url('simulate/'), PERIOD, format='json')
        self.assertEqual(r.status_code, 500)
        self.assertIn('فشل المحاكاة', r.json()['detail'])

    def test_report_aggregates_per_user(self):
        self._calculate()
        body = self.admin.get(self._url('report/'), {**PERIOD, 'user_id': self.rep.pk}).json()
        self.assertEqual(body['grand_total_incentive'], 5.0)
        row = body['rows'][0]
        self.assertEqual((row['sale_count'], row['return_count'], row['person_code']), (1, 1, 'P1'))
        self.assertEqual(len(row['transactions']), 2)
        self.assertEqual(self.admin.get(self._url('report/')).status_code, 400)

    def test_near_expiry_report(self):
        self.assertIn('note', self.admin.get(self._url('near-expiry-report/'), PERIOD).json())
        rule = IncentiveRule.objects.create(program=self.program, rule_name='expiry', incentive_type='fixed_per_unit',
                                            incentive_value=Decimal('3'), expiry_within_days=60)
        IncentiveTransaction.objects.create(
            program=self.program, rule=rule, user=self.rep, item_code='E1', item_name='e', doc_no='X1',
            quantity=Decimal('4'), unit_price=Decimal('10'), incentive_amount=Decimal('12'),
            period_start=P0, period_end=P1, erp_date=date(2026, 9, 5), branch_code='120',
            expiry_date=date(2026, 9, 25), expiry_days_remaining=20)
        body = self.admin.get(self._url('near-expiry-report/'), PERIOD).json()
        self.assertEqual(body['grand_totals']['total_incentive'], 12.0)
        self.assertEqual(body['grand_totals']['qty_sold'], 4.0)
        self.assertEqual(body['item_ranking'][0]['item_code'], 'E1')
        self.assertEqual(self.admin.get(self._url('near-expiry-report/')).status_code, 400)

    def test_clone_copies_rules_and_items(self):
        IncentiveRuleItem.objects.create(rule=self.rule, item_code='A2', incentive_override=Decimal('1'))
        r = self.admin.post(self._url('clone/'), {'new_start_date': '2026-10-01', 'new_end_date': '2026-10-31'},
                            format='json')
        self.assertEqual(r.status_code, 201, r.content)
        clone = IncentiveProgram.objects.get(pk=r.json()['id'])
        self.assertEqual(clone.name, 'نسخة من R7 برنامج')
        self.assertEqual(list(clone.rules.values_list('item_code', flat=True)), ['A1'])
        self.assertEqual(IncentiveRuleItem.objects.filter(rule__program=clone).count(), 1)
        self.assertEqual(self.admin.post(self._url('clone/'), {}, format='json').status_code, 400)

    def test_export_settlements_is_an_xlsx(self):
        self._calculate()
        self.admin.post(self._url('finalize/'), PERIOD, format='json')
        r = self.admin.get(self._url('export-settlements/'), PERIOD)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r['Content-Type'].startswith('application/vnd.openxmlformats'))
        self.assertEqual(self.admin.get(self._url('export-settlements/')).status_code, 400)

    def test_roi_report_compares_windows(self):
        from apps.purchasing.models import SalesTransactionLine
        for day, qty in ((date(2026, 8, 20), 30), (date(2026, 9, 10), 60)):
            SalesTransactionLine.objects.create(
                softech_branchcode='120', softech_itemcode='A1', doccode='115', docnumber=f'S{qty}',
                doc_date=day, transqty=qty, net_qty=Decimal(qty), net_revenue=Decimal(qty * 10))
        body = self.admin.get(self._url('roi-report/'), {**PERIOD, 'comparison_days': '30'}).json()
        self.assertEqual(body['velocity']['before_daily_qty'], 1.0)    # 30 units / 30 days
        self.assertEqual(body['velocity']['during_daily_qty'], 2.0)    # 60 units / 30 days
        self.assertEqual(body['item_breakdown'][0]['item_code'], 'A1')

    def test_roi_report_without_items_is_400(self):
        self.rule.delete()
        self.assertEqual(self.admin.get(self._url('roi-report/'), PERIOD).status_code, 400)

    def test_roi_report_bad_comparison_days_is_400(self):
        self.admin.raise_request_exception = False
        r = self.admin.get(self._url('roi-report/'), {**PERIOD, 'comparison_days': 'abc'})
        self.assertEqual(r.status_code, 400)


class RuleViewTests(_Base):

    def test_create_and_filter(self):
        r = self.admin.post(f'{API}rules/', {'program': self.program.pk, 'rule_name': 'list rule',
                                             'incentive_type': 'fixed_per_unit', 'incentive_value': '2'},
                            format='json')
        self.assertEqual(r.status_code, 201, r.content)
        rows = self.admin.get(f'{API}rules/', {'program': self.program.pk, 'is_active': 'true'}).json()
        rows = rows.get('results', rows)
        self.assertEqual(len(rows), 2)

    def test_item_list_actions(self):
        url = f'{API}rules/{self.rule.pk}/'
        self.assertEqual(self.admin.post(url + 'add-item/', {}, format='json').status_code, 400)
        self.assertEqual(self.admin.post(url + 'add-item/', {'item_code': 'A2', 'incentive_override': 'x'},
                                         format='json').status_code, 400)
        self.assertEqual(self.admin.post(url + 'add-item/', {'item_code': 'A2', 'incentive_override': '1.5'},
                                         format='json').status_code, 201)
        self.assertEqual(self.admin.post(url + 'add-item/', {'item_code': 'A2'}, format='json').status_code, 200)
        r = self.admin.post(url + 'import-items/', {'mode': 'append', 'items': [
            {'item_code': 'A2', 'incentive_override': '3'}, {'item_code': 'A3'}, {'item_code': ''}]},
            format='json')
        self.assertEqual(r.json(), {'created': 1, 'updated': 1, 'deleted': 0, 'total': 2})
        self.assertEqual(IncentiveRuleItem.objects.get(item_code='A2').incentive_override, Decimal('3.0000'))
        self.assertEqual(self.admin.post(url + 'import-items/', {'mode': 'bad'}, format='json').status_code, 400)
        self.assertEqual(self.admin.post(url + 'import-items/', {'items': 'x'}, format='json').status_code, 400)
        self.assertEqual(self.admin.delete(url + 'remove-item/?item_code=A3').status_code, 204)
        self.assertEqual(self.admin.delete(url + 'remove-item/?item_code=A3').status_code, 404)
        self.assertEqual(self.admin.delete(url + 'remove-item/').status_code, 400)
        self.assertEqual(self.admin.delete(url + 'clear-items/').json(), {'deleted': 1})

    def test_import_items_from_csv_replaces(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        IncentiveRuleItem.objects.create(rule=self.rule, item_code='OLD')
        csv = 'item_code,item_name,incentive_override\nC1,c one,2\nC2,,bad\n'.encode()
        r = self.admin.post(f'{API}rules/{self.rule.pk}/import-items/',
                            {'csv_file': SimpleUploadedFile('i.csv', csv, 'text/csv')}, format='multipart')
        self.assertEqual(r.json(), {'created': 2, 'updated': 0, 'deleted': 1, 'total': 2})
        self.assertIsNone(IncentiveRuleItem.objects.get(item_code='C2').incentive_override)


class LedgerViewTests(_Base):

    def test_transactions_settlements_receipt_and_logs(self):
        self._calculate()
        self.admin.post(self._url('finalize/'), PERIOD, format='json')
        rows = self.admin.get(f'{API}transactions/', {'program': self.program.pk, 'doc_type': 'return',
                                                     'user_id': self.rep.pk, **PERIOD}).json()
        rows = rows.get('results', rows)
        self.assertEqual([t['doc_no'] for t in rows], ['R1'])
        rows = self.admin.get(f'{API}settlements/', {'program': self.program.pk, 'is_finalized': 'true'}).json()
        rows = rows.get('results', rows)
        self.assertEqual(len(rows), 1)
        body = self.admin.get(f'{API}settlements/{rows[0]["id"]}/receipt/').json()
        self.assertEqual(body['item_summary'], [{
            'item_code': 'A1', 'item_name': 'name A1', 'rule_name': 'A1 10%', 'qty_sold': 2.0,
            'qty_returned': 1.0, 'net_qty': 1.0, 'total_incentive': 5.0, 'line_count': 2}])
        logs = self.admin.get(f'{API}logs/', {'program': self.program.pk, 'mode': 'calculate'}).json()
        self.assertEqual(len(logs.get('results', logs)), 1)

    def test_adjustments_are_blocked_on_self_and_on_finalized_periods(self):
        payload = {'program': self.program.pk, 'user': self.rep.pk, 'amount': '4.00', 'reason': 'x', **PERIOD}
        r = self.admin.post(f'{API}adjustments/', payload, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        adj = AdjustmentEntry.objects.get()
        self.assertEqual(adj.created_by, self.admin_profile)
        self.assertEqual(self.admin.post(f'{API}adjustments/', {**payload, 'user': self.admin_profile.pk},
                                         format='json').status_code, 403)
        self.assertEqual(self.admin.patch(f'{API}adjustments/{adj.pk}/', {'amount': '5'},
                                          format='json').status_code, 200)
        rows = self.admin.get(f'{API}adjustments/', {'program': self.program.pk, 'user_id': self.rep.pk,
                                                    **PERIOD}).json()
        self.assertEqual(len(rows.get('results', rows)), 1)
        IncentiveSettlement.objects.create(program=self.program, user=self.rep, period_start=P0, period_end=P1,
                                           is_finalized=True)
        self.assertEqual(self.admin.post(f'{API}adjustments/', payload, format='json').status_code, 409)
        self.assertEqual(self.admin.patch(f'{API}adjustments/{adj.pk}/', {'amount': '6'},
                                          format='json').status_code, 409)
        self.assertEqual(self.admin.delete(f'{API}adjustments/{adj.pk}/').status_code, 400)
        adj.refresh_from_db()
        self.assertEqual(adj.amount, Decimal('5.00'))


class StockAndProgressViewTests(_Base):

    STOCK = [
        {'itemcode': 'N1', 'item_name': 'n1', 'itemexpirydate': '2026-11-14', 'itemqty': 5.0,
         'storecode': '100', 'branchcode': '0', 'batchno': '', 'days_remaining': 9,
         'expiry_bucket': '0-30', 'is_quarantine': False},
        {'itemcode': 'N2', 'item_name': 'n2', 'itemexpirydate': '2027-01-14', 'itemqty': 2.5,
         'storecode': '160', 'branchcode': '0', 'batchno': '', 'days_remaining': 70,
         'expiry_bucket': '61-90', 'is_quarantine': False},
    ]

    def test_near_expiry_stock_summaries(self):
        with mock.patch('apps.incentives.engine.fetch_near_expiry_stock', return_value=self.STOCK) as f:
            body = self.admin.get(f'{API}near-expiry-stock/', {'expiry_within_days': '90',
                                                               'store_codes': '100,160'}).json()
        f.assert_called_once_with(expiry_within_days=90, store_codes=['100', '160'], item_codes=None,
                                  include_quarantine=False)
        self.assertEqual((body['total_items'], body['total_qty']), (2, 7.5))
        self.assertEqual(body['summary_by_bucket'][0], {'bucket': '0-30', 'count': 1, 'qty': 5.0})
        self.assertEqual(body['summary_by_store'][0], {'store_code': '100', 'total_qty': 5.0})

    def test_near_expiry_stock_validates_and_hides_driver_errors(self):
        self.assertEqual(self.admin.get(f'{API}near-expiry-stock/', {'expiry_within_days': '0'}).status_code, 400)
        self.assertEqual(self.admin.get(f'{API}near-expiry-stock/', {'item_codes': "1'--"}).status_code, 400)
        with mock.patch('apps.incentives.engine.fetch_near_expiry_stock', side_effect=ConnectionError('h:5000')):
            r = self.admin.get(f'{API}near-expiry-stock/')
        self.assertEqual(r.status_code, 503)
        self.assertNotIn('5000', r.json()['detail'])

    def test_suggest_items_scores_expiry_and_margin(self):
        item = make_item(name='near expiry', softech_id='N1')
        item.pack_price, item.cost_price = Decimal('100'), Decimal('60')
        item.save()
        with mock.patch('apps.incentives.engine.fetch_near_expiry_stock', return_value=self.STOCK[:1]):
            body = self.admin.get(f'{API}suggest-items/').json()
        self.assertEqual(body['count'], 1)
        row = body['items'][0]
        self.assertEqual(row['tags'], ['near_expiry', 'high_margin'])
        self.assertEqual(row['margin_pct'], 40.0)
        self.assertAlmostEqual(row['score'], 45.0 + 16.0)       # (1 − 9/90)×50 + 40/50×20

    def test_suggest_items_bad_days_is_400(self):
        self.admin.raise_request_exception = False
        self.assertEqual(self.admin.get(f'{API}suggest-items/', {'expiry_within_days': 'abc'}).status_code, 400)

    def test_my_progress(self):
        no_code = bearer_client(make_user('r7inc_nocode', role='pharmacist')[0])
        self.assertEqual(no_code.get(f'{API}my-progress/').status_code, 400)
        rep = bearer_client(self.rep.user)
        with mock.patch('apps.incentives.engine.get_my_progress', return_value=[{'program_id': 1}]):
            body = rep.get(f'{API}my-progress/').json()
        self.assertEqual(body['employee']['person_code'], 'P1')
        self.assertEqual(body['programs'], [{'program_id': 1}])

    def test_my_progress_simulates_up_to_today(self):
        today = date.today()
        self.program.start_date, self.program.end_date = today - timedelta(days=4), today + timedelta(days=5)
        self.program.save()
        sales = [(*_row('D1', 'P1', 10, 'A1', '2', '50')[:2], datetime.combine(today, datetime.min.time()),
                  *_row('D1', 'P1', 10, 'A1', '2', '50')[3:])]
        with mock.patch('apps.incentives.engine._fetch_rows', side_effect=[sales, []]), \
                mock.patch('apps.incentives.engine._fetch_cross_period_returns', return_value=[]):
            body = bearer_client(self.rep.user).get(f'{API}my-progress/').json()
        prog = body['programs'][0]
        self.assertEqual(prog['program_id'], self.program.pk)
        self.assertEqual(prog['earned_to_date'], 10.0)
        self.assertFalse(IncentiveCalculationLog.objects.exists())


class SalesTargetViewTests(_Base):

    def test_admin_creates_and_lists_targets_with_attainment(self):
        r = self.admin.post(f'{API}targets/', {'scope_type': 'chain', 'metric': 'orders',
                                               'period_start': '2026-01-01', 'period_end': '2026-01-31',
                                               'target_value': '100'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        att = r.json()['attainment']
        self.assertEqual((att['actual'], att['target'], att['pct'], att['pace']), (0, 100.0, 0.0, 'missed'))
        tid = r.json()['id']
        self.assertEqual(self.admin.patch(f'{API}targets/{tid}/', {'target_value': '120'},
                                          format='json').status_code, 200)
        from apps.audit.models import AuditLog
        self.assertTrue(AuditLog.objects.filter(action='sales_target_changed').exists())
        rows = self.admin.get(f'{API}targets/', {'scope': 'chain'}).json()
        self.assertEqual(len(rows.get('results', rows)), 1)
        self.assertEqual(self.admin.delete(f'{API}targets/{tid}/').status_code, 204)
        self.assertFalse(SalesTarget.objects.exists())

    def test_pharmacist_reads_but_cannot_set_targets(self):
        pharm = bearer_client(make_user('r7inc_pharm_t', role='pharmacist')[0])
        self.assertEqual(pharm.get(f'{API}targets/').status_code, 200)
        r = pharm.post(f'{API}targets/', {'scope_type': 'chain', 'metric': 'orders', 'period_start': '2026-01-01',
                                          'period_end': '2026-01-31', 'target_value': '1'}, format='json')
        self.assertEqual(r.status_code, 403)
        self.assertFalse(SalesTarget.objects.exists())


class IncentivesPermissionR7Tests(_Base):

    def test_pharmacist_and_supervisor_are_refused_payroll(self):
        for role in ('pharmacist', 'supervisor'):
            c = bearer_client(make_user(f'r7inc_{role}', role=role)[0])
            self.assertEqual(c.get(f'{API}programs/').status_code, 403, role)
            self.assertEqual(c.get(f'{API}near-expiry-stock/').status_code, 403, role)
            self.assertEqual(c.get(f'{API}suggest-items/').status_code, 403, role)
            with mock.patch('apps.incentives.engine._fetch_rows') as fetch:
                self.assertEqual(c.post(self._url('calculate/'), PERIOD, format='json').status_code, 403, role)
            fetch.assert_not_called()
        self.assertFalse(IncentiveTransaction.objects.exists())

    def test_quality_manager_narrowed_to_one_branch_is_refused(self):
        _, qm, _ = make_user('r7inc_qm', role='quality_manager', access_all=True)
        self.assertEqual(bearer_client(qm.user).get(f'{API}programs/').status_code, 200)
        from apps.tests.factories import make_branch2
        qm.restricted_branches.add(make_branch2())
        self.assertEqual(bearer_client(qm.user).get(f'{API}programs/').status_code, 403)
