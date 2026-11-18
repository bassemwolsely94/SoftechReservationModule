"""Crews piece 2b, Task 3: the call-center old-vs-crew comparison the owner signs off (money gate).

Per month x KPI: the stored CC rollup vs the old rule recomputed now vs the crew value, each
difference explained by a reason code; per person; per CC target; CC forecasts; owner questions.
SOFTECH and the CDR are always mocked; nothing here writes a money figure.
"""
import io
import os
import tempfile
from datetime import date, datetime
from decimal import Decimal
from unittest import mock

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.branches.models import Branch
from apps.catalog.models import Category, Item
from apps.crews import cc_comparison as C
from apps.crews import cc_seed
from apps.crews.models import Crew, CrewManualMember
from apps.customers.models import Customer, PurchaseHistory, PurchaseHistoryLine
from apps.forecasting.callcount import count_calls
from apps.forecasting.kpi import KpiResolver
from apps.forecasting.models import CallCenterConfig, KpiActualRollup
from apps.incentives.models import SalesTarget
from apps.users.models import ERPUser

JUNE = (2026, 6)
NO_RET = {'amount': Decimal('0'), 'profit': Decimal('0'), 'docs': 0}


def _when(d):
    return timezone.make_aware(datetime(d.year, d.month, d.day, 12, 0))


def _cdr(day, src, mobile):
    return {'calldate': f'{day} 10:00:00', 'src': src, 'dst': '82' + mobile,
            'disposition': 'ANSWERED'}


CDR = [_cdr('2026-06-02', '10', '01000000001'), _cdr('2026-06-03', '12', '01000000002'),
       _cdr('2026-06-04', '15', '01000000003'), _cdr('2026-06-05', '11', '01000000004')]


class _Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cfg = CallCenterConfig.get_solo()
        cfg.sales_agent_usercodes = ['62', '63', '64']
        cfg.call_agent_extensions = ['10', '12', '15']
        cfg.save()
        cls.cc = Branch.objects.create(softech_branch_id='CC', code='CC', name='Call Center',
                                       name_ar='الكول سنتر', is_operational=False,
                                       kind=Branch.KIND_CALL_CENTER)
        cls.b1 = Branch.objects.create(softech_branch_id='983', code='983', name='B1', name_ar='فرع ١')
        cls.cust = Customer.objects.create(name='ع', softech_pic='PICCMP', softech_id='C-CMP')
        cat = Category.objects.create(softech_id='CAT-CMP', name='c')
        cls.med = Item.objects.create(softech_id='CMPMED', name='دواء', medicine_type='10', category=cat)
        cls.n = 0

    def inv(self, user, day, total, *, doc='115', cost=0, phc=''):
        type(self).n += 1
        ph = PurchaseHistory.objects.create(
            customer=self.cust, softech_invoice_id=f'CMP-{self.n}', branch=self.b1, doc_code=doc,
            total_amount=Decimal(total), invoice_date=_when(day), softech_user=user,
            softech_phcode=phc, sales_channel='91', sales_person_type='10')
        PurchaseHistoryLine.objects.create(
            purchase=ph, item=self.med, quantity=Decimal(1), unit_price=Decimal(total),
            line_total=Decimal(total), cost_at_sale=Decimal(cost))

    def june_sales(self):
        self.inv('62', date(2026, 6, 3), 1000, cost=600, phc='P1')
        self.inv('63', date(2026, 6, 10), 300, cost=100, phc='P2')
        self.inv('64', date(2026, 6, 20), 500, cost=350, phc='P1')
        self.inv('99', date(2026, 6, 21), 700, cost=200, phc='P9')       # not a CC agent

    def store_old(self, overrides=None, skip=()):
        """Stored CC rollup = the old rule as it computes today (+ overrides)."""
        kpis = KpiResolver().compute_call_center_month(2026, 6, ['62', '63', '64'])
        kpis['call_count'] = Decimal(count_calls(CDR, ['10', '12', '15']))
        kpis.update(overrides or {})
        for metric, value in kpis.items():
            if metric not in skip:
                KpiActualRollup.objects.create(branch=self.cc, year=2026, month=6, metric=metric,
                                               value=value)
        return kpis

    def crew(self):
        cc_seed.seed()
        return Crew.objects.get(name=cc_seed.CC_CREW_NAME)

    def rows(self, result, **match):
        return [r for r in result['months']
                if all(r[k] == v for k, v in match.items())]

    def row(self, result, metric):
        found = self.rows(result, year=2026, month=6, metric=metric)
        self.assertEqual(len(found), 1, metric)
        return found[0]


class ReasonTests(_Base):
    def test_identical_membership_gives_same_reason(self):
        self.june_sales()
        self.store_old()
        res = C.compare(self.crew(), JUNE, JUNE, returns=False, cdr_rows_by_month={JUNE: CDR})
        self.assertEqual(len(res['months']), len(C.METRICS))
        for metric in C.METRICS:
            r = self.row(res, metric)
            self.assertEqual(r['reason'], 'same', r)
            self.assertEqual(r['crew'], r['stored'], metric)
        self.assertEqual(self.row(res, 'cash_delivery')['crew'], 1800.0)
        self.assertEqual(self.row(res, 'call_count')['crew'], 3.0)      # ext 11 is not a member
        self.assertEqual(res['totals']['reasons'], {'same': len(C.METRICS)})

    def test_extra_member_gives_membership_reason(self):
        self.june_sales()
        self.store_old()
        crew = self.crew()
        CrewManualMember.objects.create(crew=crew, mode='include', softech_usercode='99',
                                        valid_from=date(2026, 6, 1), reason='t')
        res = C.compare(crew, JUNE, JUNE, returns=False, cdr_rows_by_month={JUNE: CDR})
        r = self.row(res, 'cash_delivery')
        self.assertEqual(r['reason'], 'membership')
        self.assertEqual((r['stored'], r['old_now'], r['crew']), (1800.0, 1800.0, 2500.0))
        self.assertEqual((r['diff_stored_crew'], r['diff_old_crew']), (700.0, 700.0))
        self.assertEqual(self.row(res, 'call_count')['reason'], 'same')
        # per person: 99 has crew figures and no old figure
        p = [x for x in res['people'] if x['member_key'] == "code:99" and x['metric'] == 'cash_delivery']
        self.assertEqual(len(p), 1)
        self.assertEqual((p[0]['old'], p[0]['crew']), (0.0, 700.0))

    def test_stored_drift_reason(self):
        self.june_sales()
        self.store_old(overrides={'cash_delivery': Decimal('1500')}, skip=('beauty',))
        res = C.compare(self.crew(), JUNE, JUNE, returns=False, cdr_rows_by_month={JUNE: CDR})
        r = self.row(res, 'cash_delivery')
        self.assertEqual(r['reason'], 'drift_since_build')
        self.assertEqual((r['stored'], r['old_now'], r['crew']), (1500.0, 1800.0, 1800.0))
        b = self.row(res, 'beauty')
        self.assertEqual((b['reason'], b['stored']), ('no_stored_value', None))

    def test_return_before_membership_reason(self):
        # old rule: 62's return of a May sale counts; the crew joined in June, so it does not
        self.june_sales()
        self.store_old(overrides={'cash_delivery': Decimal('1700'), 'gross_profit': Decimal('700')})
        old_ret = {'amount': Decimal('100'), 'profit': Decimal('50'), 'docs': 1}
        with mock.patch.object(C, 'cc_returns_from_softech', return_value=old_ret), \
                mock.patch('apps.crews.softech_returns.returns_for_spans', return_value=NO_RET):
            res = C.compare(self.crew(), JUNE, JUNE, returns=True, cdr_rows_by_month={JUNE: CDR})
        r = self.row(res, 'cash_delivery')
        self.assertEqual(r['reason'], 'return_before_membership')
        self.assertEqual((r['stored'], r['old_now'], r['crew']), (1700.0, 1700.0, 1800.0))
        self.assertEqual(self.row(res, 'gross_profit')['reason'], 'return_before_membership')
        self.assertEqual(self.row(res, 'beauty')['reason'], 'same')

    def test_report_marks_unrecomputable_call_count(self):
        self.june_sales()
        self.store_old()
        with mock.patch('apps.crews.cc_comparison.cdr_configured', return_value=False), \
                mock.patch('apps.crews.kpi.cdr_configured', return_value=False), \
                mock.patch.object(C, 'cc_returns_from_softech', side_effect=OSError('down')), \
                mock.patch('apps.crews.softech_returns.returns_for_spans', side_effect=OSError('down')):
            res = C.compare(self.crew(), JUNE, JUNE, returns=True)
        calls = self.row(res, 'call_count')
        self.assertEqual(calls['reason'], 'cdr_unavailable')
        self.assertIsNone(calls['crew'])            # «غير محسوب», never 0
        self.assertIsNone(calls['old_now'])
        self.assertEqual(calls['stored'], 3.0)
        money = self.row(res, 'cash_delivery')
        self.assertEqual(money['reason'], 'returns_unreachable')
        self.assertIsNone(money['crew'])
        self.assertIsNone(money['old_now'])
        # metrics that need no returns are still compared
        self.assertEqual(self.row(res, 'customer_count')['reason'], 'same')
        md = C.markdown_summary(res)
        self.assertIn('cdr_unavailable', md)
        self.assertIn('غير محسوب', md)

    def test_cdr_csv_adds_a_question(self):
        self.store_old()
        res = C.compare(self.crew(), JUNE, JUNE, returns=False, cdr_rows_by_month={JUNE: CDR},
                        cdr_from_csv=True)
        self.assertTrue(any('CSV' in q for q in res['questions']))


class SectionTests(_Base):
    def test_targets_section_shows_salestarget_zero_and_board_value(self):
        self.june_sales()
        self.store_old(overrides={'cash_delivery': Decimal('1500')})
        t = SalesTarget.objects.create(scope_type=SalesTarget.SCOPE_BRANCH, branch=self.cc,
                                       metric='cash_delivery', period_start=date(2026, 6, 1),
                                       period_end=date(2026, 6, 30), target_value=Decimal('2000'))
        res = C.compare(self.crew(), JUNE, JUNE, returns=False, cdr_rows_by_month={JUNE: CDR})
        self.assertEqual(len(res['targets']), 1)
        row = res['targets'][0]
        self.assertEqual(row['target_id'], t.pk)
        self.assertEqual(row['target'], 2000.0)
        self.assertEqual(row['achieved_board'], 1500.0)
        self.assertEqual(row['achieved_salestarget_today'], 0.0)   # PurchaseHistory of branch CC
        self.assertEqual(row['achieved_crew'], 1800.0)
        self.assertEqual((row['pct_board'], row['pct_crew']), (75.0, 90.0))
        self.assertEqual((row['pace_board'], row['pace_crew']), ('missed', 'missed'))
        self.assertTrue(any('actual_value' in q for q in res['questions']))
        self.assertTrue(any('value-for-value' in q for q in res['questions']))

    def test_forecasts_section_lists_cc_rows(self):
        from apps.forecasting.models import ForecastResult, ForecastScenario
        self.store_old()
        sc = ForecastScenario.objects.create(name='نوفمبر', year=2026, month=11)
        ForecastResult.objects.create(scenario=sc, branch=self.cc, scope_key='CC', metric='beauty',
                                      forecast_value=Decimal('100'), target_value=Decimal('111'))
        ForecastResult.objects.create(scenario=sc, branch=self.b1, scope_key='983', metric='beauty',
                                      forecast_value=Decimal('5'), target_value=Decimal('6'))
        res = C.compare(self.crew(), JUNE, JUNE, returns=False, cdr_rows_by_month={JUNE: CDR})
        self.assertEqual([(f['metric'], f['forecast'], f['target']) for f in res['forecasts']],
                         [('beauty', 100.0, 111.0)])

    def test_generic_member_labelled_unattributed_seller(self):
        self.june_sales()
        self.store_old()
        ERPUser.objects.create(username='64', user_group='17', full_name='كاشير محطة')
        res = C.compare(self.crew(), JUNE, JUNE, returns=False, cdr_rows_by_month={JUNE: CDR})
        p64 = [x for x in res['people'] if x['member_key'] == 'code:64']
        self.assertTrue(p64)
        for x in p64:
            self.assertTrue(x['generic'])
            self.assertEqual(x['label'], 'بائع غير محدد')
        p62 = [x for x in res['people'] if x['member_key'] == 'code:62']
        self.assertFalse(p62[0]['generic'])
        self.assertEqual(p62[0]['label'], 'مندوب 62')
        cd = {x['member_key']: x for x in res['people'] if x['metric'] == 'cash_delivery'}
        self.assertEqual((cd['code:62']['old'], cd['code:62']['crew']), (1000.0, 1000.0))

    def test_workbook_sheets_and_no_formulas(self):
        from openpyxl import load_workbook
        self.june_sales()
        self.store_old()
        crew = self.crew()
        CrewManualMember.objects.create(crew=crew, mode='include', softech_usercode='77',
                                        label='=HYPERLINK("http://x","y")',
                                        valid_from=date(2026, 6, 1), reason='t')
        res = C.compare(crew, JUNE, JUNE, returns=False, cdr_rows_by_month={JUNE: CDR})
        buf = io.BytesIO()
        C.build_workbook(res).save(buf)
        wb = load_workbook(io.BytesIO(buf.getvalue()))
        self.assertEqual(wb.sheetnames[:6], ['ملخص', 'حسب الشخص', 'المستهدفات', 'التنبؤات',
                                             'أسئلة للمالك', 'شرح الفروق'])
        texts = []
        for ws in wb.worksheets:
            self.assertTrue(ws.sheet_view.rightToLeft, ws.title)
            for row in ws.iter_rows():
                for cell in row:
                    self.assertNotEqual(cell.data_type, 'f', (ws.title, cell.coordinate))
                    if isinstance(cell.value, str):
                        texts.append(cell.value)
        self.assertIn('=HYPERLINK("http://x","y")', texts)
        self.assertTrue(any('غير تجميعي' in t for t in texts))      # pic_count per person
        self.assertTrue(any(REASON in t for t in texts for REASON in [C.REASONS['same']['ar']]))


class CommandTests(_Base):
    def test_seed_in_transaction_leaves_no_rows(self):
        self.june_sales()
        self.store_old()
        with tempfile.TemporaryDirectory() as d:
            md, xlsx = os.path.join(d, 'cc.md'), os.path.join(d, 'cc.xlsx')
            with mock.patch('apps.crews.cc_comparison.cdr_configured', return_value=False), \
                    mock.patch('apps.crews.kpi.cdr_configured', return_value=False):
                call_command('compare_call_center_crew', '--from', '2026-06', '--to', '2026-06',
                             '--no-returns', '--seed-in-transaction', '--md', md, '--out', xlsx,
                             stdout=io.StringIO())
            with open(md, encoding='utf-8') as f:
                text = f.read()
            self.assertIn('cash_delivery', text)
            self.assertIn('1,800', text)
            self.assertTrue(os.path.getsize(xlsx) > 0)
        self.assertFalse(Crew.objects.exists())
        self.assertFalse(CrewManualMember.objects.exists())
        self.assertFalse(AuditLog.objects.filter(action='crew_cc_seeded').exists())
