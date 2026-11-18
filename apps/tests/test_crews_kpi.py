"""Crews piece 2b: call-center crew KPIs from dated identities + the crew rollup builder.

The crew month must reproduce KpiResolver.compute_call_center_month / count_calls exactly when
every span covers the whole month, and narrow them to the span days otherwise. Returns follow the
owner's rule (Part B): the old cc_softech rule over the seller codes active in the month, plus a
date match on r_docdate. SOFTECH is always faked (an in-memory sqlite stktrans that runs the real
SQL, or a mock). Rollups land in forecasting.KpiActualRollup with crew set, branch NULL.
"""
import sqlite3
from datetime import date, datetime
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.branches.models import Branch
from apps.catalog.models import Category, Item
from apps.crews import kpi as crew_kpi
from apps.crews.models import Crew, CrewManualMember
from apps.customers.models import Customer, PurchaseHistory, PurchaseHistoryLine
from apps.forecasting.callcount import count_calls
from apps.forecasting.cc_softech import cc_returns_from_softech
from apps.forecasting.kpi import KpiResolver
from apps.forecasting.models import BeautyClassRule, KpiActualRollup

FIVE = ['cash_delivery', 'gross_profit', 'beauty', 'customer_count', 'pic_count']
SEED_FROM = date(2024, 8, 1)


def _when(d, h=12):
    return timezone.make_aware(datetime(d.year, d.month, d.day, h, 0))


def _cdr(day, src, mobile, disposition='ANSWERED'):
    return {'calldate': f'{day} 10:00:00', 'src': src, 'dst': '82' + mobile,
            'disposition': disposition}


class _Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.b1 = Branch.objects.create(softech_branch_id='981', code='981', name='B1')
        cls.b2 = Branch.objects.create(softech_branch_id='982', code='982', name='B2')
        cls.cust = Customer.objects.create(name='ع', softech_pic='PICCK', softech_id='C-CK')
        cat = Category.objects.create(softech_id='CAT-CK', name='c')
        cls.med = Item.objects.create(softech_id='CKMED', name='دواء', medicine_type='10', category=cat)
        cls.cosm = Item.objects.create(softech_id='CKCOS', name='تجميل', medicine_type='50', category=cat)
        BeautyClassRule.objects.create(medicine_type='50', label='Cosmetics', active=True)
        cls.n = 0

    def inv(self, user, day, total, *, doc='115', item=None, qty=1, cost=0, phc='', branch=None):
        type(self).n += 1
        ph = PurchaseHistory.objects.create(
            customer=self.cust, softech_invoice_id=f'CK-{self.n}', branch=branch or self.b1,
            doc_code=doc, total_amount=Decimal(total), invoice_date=_when(day),
            softech_user=user, softech_phcode=phc, sales_channel='91', sales_person_type='10')
        PurchaseHistoryLine.objects.create(
            purchase=ph, item=item or self.med, quantity=Decimal(qty), unit_price=Decimal(total),
            line_total=Decimal(total), cost_at_sale=Decimal(cost))
        return ph

    def crew(self, rows):
        """rows: [(usercode|'', extension|'', valid_from, valid_to)] -> call-center crew."""
        c = Crew.objects.create(name=f'كول {Crew.objects.count()}', type='call_center')
        for code, ext, frm, to in rows:
            CrewManualMember.objects.create(crew=c, mode='include', softech_usercode=code,
                                            pbx_extension=ext, valid_from=frm, valid_to=to,
                                            reason='t')
        return c


class CrewSalesTests(_Base):
    def _fixture(self):
        # June 2026: agents 62/63/64 + a non-agent 99 and a blank seller
        self.inv('62', date(2026, 6, 3), 1000, cost=600, phc='P1')
        self.inv('63', date(2026, 6, 10), 300, item=self.cosm, qty=3, cost=40, phc='P2')
        self.inv('64', date(2026, 6, 20), 500, cost=350, phc='P1', branch=self.b2)
        self.inv('62', date(2026, 6, 25), 100, doc='30', cost=60, phc='P1')
        self.inv('63', date(2026, 6, 28), 50, doc='30', item=self.cosm, cost=10, phc='P2')
        self.inv('99', date(2026, 6, 5), 777, cost=1, phc='P9')
        self.inv('', date(2026, 6, 5), 555, cost=1, phc='P8')
        self.inv('62', date(2026, 5, 31), 4444, cost=1, phc='P7')   # outside the month
        self.inv('62', date(2026, 7, 1), 3333, cost=1, phc='P6')

    def test_full_month_spans_equal_compute_call_center_month(self):
        self._fixture()
        old = KpiResolver().compute_call_center_month(2026, 6, ['62', '63', '64'])
        spans = [('62', SEED_FROM, date(2026, 6, 30)), ('63', SEED_FROM, date(2026, 6, 30)),
                 ('64', SEED_FROM, date(2026, 6, 30))]
        new = crew_kpi.compute_sales(2026, 6, spans)
        self.assertEqual(set(new), set(FIVE))
        for m in FIVE:
            self.assertEqual(new[m], old[m], m)
            self.assertIsInstance(new[m], Decimal)
        self.assertEqual(new['cash_delivery'], Decimal('1650'))     # 1000+300+500-100-50
        # and through the crew (seed-style open rows) the same five
        c = self.crew([('62', '', SEED_FROM, None), ('63', '', SEED_FROM, None),
                       ('64', '', SEED_FROM, None)])
        month = crew_kpi.compute_crew_month(c, 2026, 6, returns=False, cdr_rows=[])
        for m in FIVE:
            self.assertEqual(month.kpis[m], old[m], m)

    def test_partial_month_span_counts_only_inside_span(self):
        self.inv('62', date(2026, 6, 14), 200, phc='A')
        self.inv('62', date(2026, 6, 15), 300, phc='B')      # the span's first day
        self.inv('62', date(2026, 6, 30), 400, phc='C')
        c = self.crew([('62', '', date(2026, 6, 15), None)])
        month = crew_kpi.compute_crew_month(c, 2026, 6, returns=False, cdr_rows=[])
        self.assertEqual(month.kpis['cash_delivery'], Decimal('700'))
        self.assertEqual(month.kpis['customer_count'], Decimal('2'))
        # an ended span stops counting the day after valid_to
        c2 = self.crew([('62', '', SEED_FROM, date(2026, 6, 14))])
        m2 = crew_kpi.compute_crew_month(c2, 2026, 6, returns=False, cdr_rows=[])
        self.assertEqual(m2.kpis['cash_delivery'], Decimal('200'))

    def test_pic_count_distinct_across_members(self):
        self.inv('62', date(2026, 6, 3), 100, phc='SAME')
        self.inv('63', date(2026, 6, 4), 100, phc='SAME')
        self.inv('63', date(2026, 6, 5), 100, phc='OTHER')
        c = self.crew([('62', '', SEED_FROM, None), ('63', '', SEED_FROM, None)])
        month = crew_kpi.compute_crew_month(c, 2026, 6, returns=False, cdr_rows=[], per_member=True)
        self.assertEqual(month.kpis['pic_count'], Decimal('2'))
        per = {k: v['pic_count'] for k, v in month.per_member.items()}
        self.assertEqual(per, {('code', '62'): Decimal('1'), ('code', '63'): Decimal('2')})

    def test_cashiercode_never_credits(self):
        # PurchaseHistory carries the SELLER (stktransm.usercode) only; an invoice whose seller is
        # not a member is never credited, whoever rang it up or whose account it is on.
        ph = self.inv('99', date(2026, 6, 3), 900, phc='X')
        PurchaseHistory.objects.filter(pk=ph.pk).update(softech_personcode='62')
        self.inv('62', date(2026, 6, 3), 100, phc='Y')
        c = self.crew([('62', '', SEED_FROM, None)])
        month = crew_kpi.compute_crew_month(c, 2026, 6, returns=False, cdr_rows=[])
        self.assertEqual(month.kpis['cash_delivery'], Decimal('100'))
        self.assertEqual(month.kpis['customer_count'], Decimal('1'))

    def test_per_member_sums_to_total_for_additive_metrics(self):
        self._fixture()
        c = self.crew([('62', '', SEED_FROM, None), ('63', '', SEED_FROM, None),
                       ('64', '', date(2026, 6, 15), None)])
        month = crew_kpi.compute_crew_month(c, 2026, 6, returns=False, cdr_rows=[], per_member=True)
        self.assertEqual(set(month.per_member), {('code', '62'), ('code', '63'), ('code', '64')})
        for m in ('cash_delivery', 'gross_profit', 'beauty', 'customer_count'):
            self.assertEqual(sum(v[m] for v in month.per_member.values()), month.kpis[m], m)

    def test_no_sellers_skips_sales_but_counts_calls(self):
        self.inv('62', date(2026, 6, 3), 100, phc='A')
        c = self.crew([('', '10', SEED_FROM, None)])
        get_conn = mock.Mock()
        rows = [_cdr('2026-06-02', '10', '01000000001'), _cdr('2026-06-03', '10', '01000000002')]
        with mock.patch('apps.crews.softech_returns.get_sybase_connection', get_conn):
            month = crew_kpi.compute_crew_month(c, 2026, 6, cdr_rows=rows, per_member=True)
        self.assertEqual(month.kpis, {'call_count': Decimal('2')})
        self.assertIn('no_sellers', month.notes)
        self.assertNotIn('no_members', month.notes)
        self.assertEqual(month.gross, {})
        self.assertIsNone(month.returns)
        get_conn.assert_not_called()

    def test_no_identities_is_no_members(self):
        c = self.crew([])
        month = crew_kpi.compute_crew_month(c, 2026, 6, cdr_rows=[_cdr('2026-06-02', '10', '01000000001')])
        self.assertEqual(month.kpis, {})
        self.assertEqual(month.notes, ['no_members'])
        # a crew whose only member ended before the month is also empty
        c2 = self.crew([('62', '10', SEED_FROM, date(2026, 5, 31))])
        self.assertEqual(crew_kpi.compute_crew_month(c2, 2026, 6, cdr_rows=[]).notes, ['no_members'])


class _FakeSoftech:
    """get_sybase_connection stand-in: an in-memory stktrans table that really runs the returns
    SQL (sqlite reads it as written: ? parameters, EXISTS, IN, COUNT(DISTINCT)). Dates are
    'YYYYMMDD' strings, as the queries pass them."""

    def __init__(self):
        self.db = sqlite3.connect(':memory:')
        self.db.execute('CREATE TABLE stktrans (branchcode TEXT, doccode TEXT, docnumber INTEGER, '
                        'docdate TEXT, usercode TEXT, r_docnumber INTEGER, r_docdate TEXT, '
                        'transprice_total INTEGER, transqty INTEGER, newcostprice INTEGER)')
        self.executed = []

    def sale(self, docnumber, docdate, usercode, branch='1'):
        self.db.execute("INSERT INTO stktrans VALUES (?, '115', ?, ?, ?, NULL, NULL, 0, 1, 0)",
                        [branch, docnumber, docdate, usercode])

    def ret(self, docnumber, docdate, r_docnumber, r_docdate, amount, cost=0, branch='1'):
        self.db.execute("INSERT INTO stktrans VALUES (?, '30', ?, ?, '', ?, ?, ?, 1, ?)",
                        [branch, docnumber, docdate, r_docnumber, r_docdate, amount, cost])

    def __call__(self):
        return self

    def cursor(self):
        fake = self

        class _Cur:
            def execute(self, sql, params=()):
                fake.executed.append((sql, list(params)))
                self._cur = fake.db.execute(sql, list(params))

            def fetchone(self):
                return self._cur.fetchone()
        return _Cur()

    def close(self):
        pass


CREW_SYBASE = 'apps.crews.softech_returns.get_sybase_connection'
OLD_SYBASE = 'config.sybase.get_sybase_connection'


class CrewReturnsTests(_Base):
    """Owner ruling B + the date match (2026-11-18): a June doc-30 return line is the crew's when an
    original doc-115 sale at the same branch, number r_docnumber, by a seller code active in the
    month exists AND (r_docdate is NULL OR that sale's docdate = r_docdate). No look-back limit, no
    membership date on the original sale. cc_softech (the comparison's "old rule") keeps the
    number-only match."""

    def _softech(self):
        s = _FakeSoftech()
        s.sale(500, '20260602', '62')                       # plain June sale
        s.ret(9001, '20260610', 500, '20260602', 100, cost=60)
        s.sale(600, '20250105', '62')                       # reused number: 62's old sale ...
        s.sale(600, '20260510', '99')                       # ... the return is of 99's May sale
        s.ret(9002, '20260611', 600, '20260510', 40, cost=10)
        s.sale(700, '20260603', '63')                       # return without r_docdate
        s.ret(9003, '20260612', 700, None, 25, cost=5)
        s.sale(800, '20240715', '62')                       # 23 months before the return
        s.ret(9004, '20260613', 800, '20240715', 7, cost=2)
        s.sale(900, '20260604', '62', branch='2')           # same number, other branch
        s.ret(9005, '20260614', 900, '20260604', 1000, branch='1')
        s.ret(9006, '20260520', 500, '20260602', 3333)      # outside the month
        return s

    def test_crew_rule_needs_the_date_old_rule_does_not(self):
        from apps.crews.softech_returns import returns_for_codes
        from apps.forecasting.cc_softech import cc_returns_from_softech
        s = self._softech()
        with mock.patch(CREW_SYBASE, s):
            crew = returns_for_codes(2026, 6, ['62', '63'])
        with mock.patch(OLD_SYBASE, s):
            old = cc_returns_from_softech(2026, 6, ['62', '63'])
        # crew: 9001 (date match) + 9003 (no r_docdate → number only) + 9004 (23-month-old sale)
        self.assertEqual(crew, {'amount': Decimal('132'), 'profit': Decimal('65'), 'docs': 3})
        # old rule also counts 9002 (62's reused number 600, different date)
        self.assertEqual(old, {'amount': Decimal('172'), 'profit': Decimal('95'), 'docs': 4})

    def test_crew_returns_sql_parameterised(self):
        from apps.crews.softech_returns import returns_for_codes
        s = self._softech()
        with mock.patch(CREW_SYBASE, s):
            returns_for_codes(2026, 6, ['63', "6'2"])
        sql, params = s.executed[-1]
        self.assertNotIn("'62'", sql)
        self.assertNotIn("'63'", sql)
        self.assertNotIn('2026', sql)
        self.assertEqual(sql.count('?'), len(params))
        self.assertEqual(params, ['20260601', '20260701', '62', '63'])   # quotes stripped, sorted
        self.assertIn('r.r_docdate IS NULL OR o.docdate = r.r_docdate', ' '.join(sql.split()))

    def test_old_rule_in_list_parameterised_same_result(self):
        from apps.forecasting.cc_softech import cc_returns_from_softech
        s = self._softech()
        with mock.patch(OLD_SYBASE, s):
            res = cc_returns_from_softech(2026, 6, ["6'2", '63'])
        sql, params = s.executed[-1]
        self.assertNotIn("'62'", sql)
        self.assertIn('o.usercode IN (?,?)', ' '.join(sql.split()))
        self.assertEqual(params, ['62', '63'])
        self.assertEqual(res['amount'], Decimal('172'))

    def test_month_returns_subtracted_with_member_rule(self):
        # 62 joined in June 2026; its 2024 sale's return still counts (no membership date)
        self.inv('62', date(2026, 6, 3), 1000, cost=600, phc='P1')
        self.inv('63', date(2026, 6, 4), 200, cost=50, phc='P2')
        c = self.crew([('62', '', date(2026, 6, 1), None), ('63', '', SEED_FROM, None),
                       ('64', '', SEED_FROM, date(2026, 5, 31))])      # 64 left before June
        s = self._softech()
        with mock.patch(CREW_SYBASE, s):
            month = crew_kpi.compute_crew_month(c, 2026, 6, cdr_rows=[], per_member=True)
        self.assertEqual(month.returns, {'amount': Decimal('132'), 'profit': Decimal('65'), 'docs': 3})
        self.assertEqual(month.gross['cash_delivery'], Decimal('1200'))
        self.assertEqual(month.kpis['cash_delivery'], Decimal('1068'))
        self.assertEqual(month.kpis['gross_profit'], Decimal('485'))       # 550 - 65
        self.assertEqual(month.per_member[('code', '62')]['cash_delivery'], Decimal('893'))  # 1000-107
        self.assertEqual(month.per_member[('code', '63')]['cash_delivery'], Decimal('175'))  # 200-25
        self.assertNotIn(('code', '64'), month.per_member)
        # the crew query is asked for the codes active in the month only
        self.assertEqual(s.executed[0][1][2:], ['62', '63'])

    def test_full_month_equals_old_rollup_when_dates_match(self):
        """Money gate: full-month spans + the same codes + returns whose r_docdate matches (or is
        absent) → compute_crew_month == compute_call_center_month − cc_returns_from_softech."""
        CrewSalesTests._fixture(self)
        s = _FakeSoftech()
        s.sale(500, '20260602', '62')
        s.ret(9001, '20260610', 500, '20260602', 100, cost=60)
        s.sale(700, '20250603', '64', branch='2')
        s.ret(9003, '20260612', 700, None, 25, cost=5, branch='2')
        codes = ['62', '63', '64']
        old = KpiResolver().compute_call_center_month(2026, 6, codes)
        with mock.patch(OLD_SYBASE, s):
            ret = cc_returns_from_softech(2026, 6, codes)
        old['cash_delivery'] -= ret['amount']
        old['gross_profit'] -= ret['profit']
        c = self.crew([(code, '', SEED_FROM, None) for code in codes])
        with mock.patch(CREW_SYBASE, s):
            month = crew_kpi.compute_crew_month(c, 2026, 6, cdr_rows=[])
        self.assertEqual(ret['amount'], Decimal('125'))
        for m in FIVE:
            self.assertEqual(month.kpis[m], old[m], m)

    def test_returns_unreachable_marked_not_zero(self):
        self.inv('62', date(2026, 6, 3), 1000, cost=600, phc='P1')
        c = self.crew([('62', '', SEED_FROM, None)])
        boom = mock.Mock(side_effect=OSError('SOFTECH down'))
        with mock.patch(CREW_SYBASE, boom):
            month = crew_kpi.compute_crew_month(c, 2026, 6, cdr_rows=[])
        self.assertIn('returns_unreachable', month.notes)
        self.assertEqual(month.kpis['cash_delivery'], Decimal('1000'))    # gross, not zeroed
        self.assertEqual(month.kpis['gross_profit'], Decimal('400'))
        self.assertIsNone(month.returns)
        self.assertEqual(month.gross, {m: month.kpis[m] for m in FIVE})

    def test_no_codes_no_softech_call(self):
        from apps.crews.softech_returns import returns_for_codes
        get_conn = mock.Mock()
        with mock.patch(CREW_SYBASE, get_conn):
            self.assertEqual(returns_for_codes(2026, 6, []),
                             {'amount': Decimal('0'), 'profit': Decimal('0'), 'docs': 0})
        get_conn.assert_not_called()

    def test_per_member_off_by_default(self):
        self.inv('62', date(2026, 6, 3), 1000, cost=600, phc='P1')
        c = self.crew([('62', '', SEED_FROM, None)])
        s = self._softech()
        with mock.patch(CREW_SYBASE, s):
            month = crew_kpi.compute_crew_month(c, 2026, 6, cdr_rows=[])
        self.assertEqual(month.per_member, {})
        self.assertEqual(len(s.executed), 1)


class CrewCallCountTests(_Base):
    ROWS = [
        _cdr('2026-06-02', '10', '01000000001'),
        _cdr('2026-06-02', '12', '01000000001'),          # same mobile, other ext → once
        _cdr('2026-06-10', '12', '01000000002'),
        _cdr('2026-06-20', '15', '01000000003'),
        _cdr('2026-06-21', '15', '01000000004', 'NO ANSWER'),
        _cdr('2026-06-22', '11', '01000000005'),          # not an agent extension
        _cdr('2026-06-23', '10', '0123'),                 # not a mobile
    ]

    def test_call_count_spans_equal_count_calls_full_month(self):
        exts = ['10', '12', '15']
        spans = [(e, SEED_FROM, date(2026, 6, 30)) for e in exts]
        self.assertEqual(crew_kpi.count_calls_spans(self.ROWS, spans), count_calls(self.ROWS, exts))
        self.assertEqual(crew_kpi.count_calls_spans(self.ROWS, spans), 3)

    def test_call_count_excludes_calls_outside_span(self):
        spans = [('10', SEED_FROM, date(2026, 6, 30)),
                 ('12', date(2026, 6, 5), date(2026, 6, 30)),
                 ('15', SEED_FROM, date(2026, 6, 19))]
        # 12's 06-02 call is before its span; 15's 06-20 call is after its span
        self.assertEqual(crew_kpi.count_calls_spans(self.ROWS, spans), 2)
        c = self.crew([('62', '', SEED_FROM, None), ('', '10', SEED_FROM, None),
                       ('', '12', date(2026, 6, 5), None), ('', '15', SEED_FROM, date(2026, 6, 19))])
        month = crew_kpi.compute_crew_month(c, 2026, 6, returns=False, cdr_rows=self.ROWS, per_member=True)
        self.assertEqual(month.kpis['call_count'], Decimal('2'))
        self.assertEqual(month.per_member[('ext', '12')]['call_count'], Decimal('1'))

    def test_cdr_unavailable_note(self):
        c = self.crew([('62', '', SEED_FROM, None), ('', '10', SEED_FROM, None)])
        with mock.patch('apps.crews.kpi.cdr_configured', return_value=False):
            month = crew_kpi.compute_crew_month(c, 2026, 6, returns=False)
        self.assertNotIn('call_count', month.kpis)
        self.assertIn('cdr_unavailable', month.notes)

    def test_cdr_live_fetch_failure_marked(self):
        c = self.crew([('62', '', SEED_FROM, None), ('', '10', SEED_FROM, None)])
        with mock.patch('apps.crews.kpi.cdr_configured', return_value=True), \
                mock.patch('apps.crews.kpi.fetch_cdr_rows', side_effect=OSError('pbx down')):
            month = crew_kpi.compute_crew_month(c, 2026, 6, returns=False)
        self.assertNotIn('call_count', month.kpis)
        self.assertIn('cdr_unreachable', month.notes)


class BuildCrewRollupsCommandTests(_Base):
    def _crew_rows(self, c, year=2026, month=6):
        return {r.metric: r for r in KpiActualRollup.objects.filter(crew=c, year=year, month=month)}

    def test_build_command_writes_crew_rows_in_kpi_rollup(self):
        self.inv('62', date(2026, 6, 3), 1000, cost=600, phc='P1')
        cc = Branch.objects.create(softech_branch_id='CC', code='CC', name='Call Center',
                                   is_operational=False, kind=Branch.KIND_CALL_CENTER)
        KpiActualRollup.objects.create(branch=cc, year=2026, month=6, metric='cash_delivery',
                                       value=Decimal('5'))
        before = list(KpiActualRollup.objects.filter(branch__isnull=False)
                      .values_list('id', 'value'))
        c = self.crew([('62', '', SEED_FROM, None)])
        other = Crew.objects.create(name='وظيفي', type='job')
        archived = self.crew([('62', '', SEED_FROM, None)])
        archived.is_archived = True
        archived.save()
        boom = mock.Mock(side_effect=OSError('SOFTECH down'))
        out = StringIO()
        with mock.patch(CREW_SYBASE, boom), \
                mock.patch('apps.crews.kpi.cdr_configured', return_value=False):
            call_command('build_crew_rollups', year=2026, month=6, stdout=out, stderr=StringIO())
        # the legacy CC branch row is untouched
        self.assertEqual(list(KpiActualRollup.objects.filter(branch__isnull=False)
                              .values_list('id', 'value')), before)
        rows = self._crew_rows(c)
        # SOFTECH down: the two money metrics the returns adjust are not computable this run, so
        # no gross figure is written for them (Task 3 fix: never store a degraded number)
        self.assertEqual(set(rows), set(FIVE) - {'cash_delivery', 'gross_profit'})
        self.assertTrue(all(r.branch_id is None for r in rows.values()))
        self.assertIn('returns_unreachable', out.getvalue())     # notes go to stdout
        self.assertIn('cdr_unavailable', out.getvalue())
        self.assertFalse(KpiActualRollup.objects.filter(crew__in=[other, archived]).exists())
        # re-run with returns updates in place, never duplicates
        s = _FakeSoftech()
        s.sale(500, '20260603', '62')
        s.ret(9001, '20260610', 500, '20260603', 100, cost=60)
        with mock.patch(CREW_SYBASE, s), \
                mock.patch('apps.crews.kpi.cdr_configured', return_value=False):
            call_command('build_crew_rollups', crew=c.pk, year=2026, month=6, stdout=out)
        rows = self._crew_rows(c)
        self.assertEqual(rows['cash_delivery'].value, Decimal('900.00'))
        self.assertEqual(rows['gross_profit'].value, Decimal('360.00'))
        self.assertEqual(KpiActualRollup.objects.filter(crew=c, year=2026, month=6,
                                                        metric='cash_delivery').count(), 1)

    def test_build_command_cdr_csv(self):
        self._build_with_csv()

    def _build_with_csv(self):
        import csv
        import tempfile
        import os
        c = self.crew([('62', '', SEED_FROM, None), ('', '10', SEED_FROM, None)])
        fd, path = tempfile.mkstemp(suffix='.csv')
        os.close(fd)
        try:
            with open(path, 'w', newline='', encoding='utf-8') as f:
                w = csv.DictWriter(f, fieldnames=['calldate', 'src', 'dst', 'disposition'])
                w.writeheader()
                w.writerow(_cdr('2026-06-02', '10', '01000000001'))
                w.writerow(_cdr('2026-06-03', '10', '01000000002'))
            call_command('build_crew_rollups', crew=c.pk, year=2026, month=6, cdr_csv=path,
                         no_returns=True, stdout=StringIO())
        finally:
            os.remove(path)
        self.assertEqual(KpiActualRollup.objects.get(crew=c, year=2026, month=6,
                                                     metric='call_count').value, Decimal('2'))
        return c

    def test_no_returns_build_prints_returns_not_deducted(self):
        self.inv('62', date(2026, 6, 3), 1000, cost=600, phc='P1')
        c = self.crew([('62', '', SEED_FROM, None)])
        get_conn = mock.Mock()
        out = StringIO()
        with mock.patch(CREW_SYBASE, get_conn), \
                mock.patch('apps.crews.kpi.cdr_configured', return_value=False):
            call_command('build_crew_rollups', crew=c.pk, year=2026, month=6, no_returns=True,
                         stdout=out)
        get_conn.assert_not_called()
        self.assertEqual(set(self._crew_rows(c)), set(FIVE))
        self.assertIn('returns_not_deducted', out.getvalue())
        # extensions only (no seller): nothing to deduct, no such note
        c2 = self.crew([('', '10', SEED_FROM, None)])
        month = crew_kpi.compute_crew_month(c2, 2026, 6, returns=False, cdr_rows=[])
        self.assertNotIn('returns_not_deducted', month.notes)

    def test_rebuild_without_cdr_keeps_stored_call_count(self):
        # an unattended rebuild must never lose a figure it cannot recompute (Task 3 fix)
        c = self._build_with_csv()
        out = StringIO()
        with mock.patch('apps.crews.kpi.cdr_configured', return_value=False):
            call_command('build_crew_rollups', crew=c.pk, year=2026, month=6, no_returns=True,
                         stdout=out)
        rows = self._crew_rows(c)
        self.assertEqual(set(rows), set(FIVE) | {'call_count'})
        self.assertEqual(rows['call_count'].value, Decimal('2'))
        self.assertIn('kept stored call_count', out.getvalue())

    def test_month_with_nothing_computed_writes_nothing_and_warns(self):
        c = self.crew([('62', '', date(2026, 7, 1), None)])     # no identity in June
        KpiActualRollup.objects.create(crew=c, year=2026, month=6, metric='beauty', value=1)
        other = self.crew([('62', '', SEED_FROM, None)])
        KpiActualRollup.objects.create(crew=other, year=2026, month=6, metric='beauty', value=1)
        out = StringIO()
        call_command('build_crew_rollups', crew=c.pk, year=2026, month=6, stdout=out)
        self.assertIn('nothing computed', out.getvalue())
        self.assertIn('no_members', out.getvalue())
        # no members: nothing is computable, so the stored figure is kept, never deleted
        self.assertTrue(KpiActualRollup.objects.filter(crew=c, metric='beauty').exists())
        self.assertIn('kept stored beauty', out.getvalue())
        self.assertTrue(KpiActualRollup.objects.filter(crew=other).exists())  # other crew kept

    def test_metric_neither_computed_nor_unavailable_is_removed(self):
        self.inv('62', date(2026, 6, 3), 1000, cost=600, phc='P1')
        c = self.crew([('62', '', SEED_FROM, None)])
        KpiActualRollup.objects.create(crew=c, year=2026, month=6, metric='old_metric', value=1)
        with mock.patch('apps.crews.kpi.cdr_configured', return_value=False):
            call_command('build_crew_rollups', crew=c.pk, year=2026, month=6, no_returns=True,
                         stdout=StringIO())
        self.assertNotIn('old_metric', self._crew_rows(c))


class KpiRollupCrewConstraintTests(_Base):
    def test_branch_xor_crew(self):
        from django.db import IntegrityError, transaction
        c = self.crew([])
        with self.assertRaises(IntegrityError), transaction.atomic():
            KpiActualRollup.objects.create(branch=self.b1, crew=c, year=2026, month=6,
                                           metric='beauty', value=1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            KpiActualRollup.objects.create(year=2026, month=6, metric='beauty', value=1)
        KpiActualRollup.objects.create(crew=c, year=2026, month=6, metric='beauty', value=1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            KpiActualRollup.objects.create(crew=c, year=2026, month=6, metric='beauty', value=2)
        KpiActualRollup.objects.create(branch=self.b1, year=2026, month=6, metric='beauty', value=1)

    def test_crew_with_rollups_is_protected_and_has_history(self):
        from django.db.models import ProtectedError
        c = Crew.objects.create(name='ط', type='custom')
        self.assertFalse(c.has_history())
        KpiActualRollup.objects.create(crew=c, year=2026, month=11, metric='x', value=1)
        self.assertTrue(c.has_history())
        with self.assertRaises(ProtectedError):
            c.delete()

    def test_target_and_forecast_crew_fields(self):
        from django.db.models import PROTECT
        from apps.forecasting.models import ForecastResult
        from apps.incentives.models import SalesTarget
        c = self.crew([])
        self.assertEqual(SalesTarget.SCOPE_CREW, 'crew')
        self.assertIn(('crew', 'طاقم'), SalesTarget.SCOPE_CHOICES)
        t = SalesTarget.objects.create(scope_type=SalesTarget.SCOPE_CREW, crew=c, metric='beauty',
                                       period_start=date(2026, 6, 1), period_end=date(2026, 6, 30),
                                       target_value=1)
        self.assertEqual(t.crew_id, c.pk)
        for model in (ForecastResult, SalesTarget):
            f = model._meta.get_field('crew')
            self.assertTrue(f.null, model)
            self.assertIs(f.remote_field.on_delete, PROTECT, model)
            self.assertIs(f.related_model, Crew, model)
