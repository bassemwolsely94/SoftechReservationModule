"""Crews piece 2b, Task 2: call-center crew KPIs from dated identities + shadow rollup builder.

The crew month must reproduce KpiResolver.compute_call_center_month / cc_returns_from_softech /
count_calls exactly when every span covers the whole month, and narrow them to the span days
otherwise. SOFTECH is always mocked (apps.crews.softech_returns.get_sybase_connection).
"""
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
from apps.crews.models import Crew, CrewKpiRollup, CrewManualMember
from apps.customers.models import Customer, PurchaseHistory, PurchaseHistoryLine
from apps.forecasting.callcount import count_calls
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


def _sybase(rows):
    """A get_sybase_connection mock whose cursor returns `rows` in turn (one per execute)."""
    conn = mock.MagicMock()
    cur = conn.cursor.return_value
    cur.fetchone.side_effect = list(rows)
    return mock.Mock(return_value=conn), cur


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
        month = crew_kpi.compute_crew_month(c, 2026, 6, returns=False, cdr_rows=[])
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
        month = crew_kpi.compute_crew_month(c, 2026, 6, returns=False, cdr_rows=[])
        self.assertEqual(set(month.per_member), {('code', '62'), ('code', '63'), ('code', '64')})
        for m in ('cash_delivery', 'gross_profit', 'beauty', 'customer_count'):
            self.assertEqual(sum(v[m] for v in month.per_member.values()), month.kpis[m], m)

    def test_no_sellers_skips_sales_but_counts_calls(self):
        self.inv('62', date(2026, 6, 3), 100, phc='A')
        c = self.crew([('', '10', SEED_FROM, None)])
        get_conn = mock.Mock()
        rows = [_cdr('2026-06-02', '10', '01000000001'), _cdr('2026-06-03', '10', '01000000002')]
        with mock.patch('apps.crews.softech_returns.get_sybase_connection', get_conn):
            month = crew_kpi.compute_crew_month(c, 2026, 6, cdr_rows=rows)
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


class CrewReturnsTests(_Base):
    def test_returns_subtracted_and_sql_parameterised(self):
        self.inv('62', date(2026, 6, 3), 1000, cost=600, phc='P1')
        c = self.crew([('62', '', SEED_FROM, None), ('63', '', date(2026, 6, 1), None)])
        get_conn, cur = _sybase([(Decimal('120'), Decimal('45'), 2)])
        with mock.patch('apps.crews.softech_returns.get_sybase_connection', get_conn):
            month = crew_kpi.compute_crew_month(c, 2026, 6, cdr_rows=[], per_member=False)
        self.assertEqual(month.kpis['cash_delivery'], Decimal('880'))
        self.assertEqual(month.kpis['gross_profit'], Decimal('355'))
        self.assertNotIn('returns_unreachable', month.notes)
        self.assertEqual(month.gross['cash_delivery'], Decimal('1000'))
        self.assertEqual(month.gross['gross_profit'], Decimal('400'))
        self.assertEqual(month.returns, {'amount': Decimal('120'), 'profit': Decimal('45'), 'docs': 2})
        sql, params = cur.execute.call_args[0]
        self.assertNotIn("'62'", sql)
        self.assertNotIn("'63'", sql)
        self.assertIn('o.usercode = ?', sql)
        self.assertEqual(sql.count('?'), len(params))
        # month bounds, then (usercode, from, to-exclusive) per span; every date a YYYYMMDD string
        self.assertEqual(params[:2], ['20260601', '20260701'])
        spans = [tuple(params[i:i + 3]) for i in range(2, len(params), 3)]
        self.assertIn(('62', '20250427', '20260701'), spans)   # clipped to the 400-day lookback
        self.assertIn(('63', '20260601', '20260701'), spans)
        for p in params:
            self.assertIsInstance(p, str)

    def test_returns_sql_span_starts_at_lookback(self):
        c = self.crew([('62', '', date(2020, 1, 1), None)])
        get_conn, cur = _sybase([(None, None, 0)])
        with mock.patch('apps.crews.softech_returns.get_sybase_connection', get_conn):
            crew_kpi.compute_crew_month(c, 2026, 6, cdr_rows=[], per_member=False)
        params = cur.execute.call_args[0][1]
        self.assertEqual(params[2:], ['62', '20250427', '20260701'])   # 2026-06-01 − 400 days

    def test_returns_unreachable_marked_not_zero(self):
        self.inv('62', date(2026, 6, 3), 1000, cost=600, phc='P1')
        c = self.crew([('62', '', SEED_FROM, None)])
        boom = mock.Mock(side_effect=OSError('SOFTECH down'))
        with mock.patch('apps.crews.softech_returns.get_sybase_connection', boom):
            month = crew_kpi.compute_crew_month(c, 2026, 6, cdr_rows=[])
        self.assertIn('returns_unreachable', month.notes)
        self.assertEqual(month.kpis['cash_delivery'], Decimal('1000'))    # gross, not zeroed
        self.assertEqual(month.kpis['gross_profit'], Decimal('400'))
        self.assertIsNone(month.returns)
        self.assertEqual(month.gross, {m: month.kpis[m] for m in FIVE})

    def test_returns_sql_differs_from_cc_softech_only_in_usercode_predicate(self):
        import re
        from apps.crews.softech_returns import returns_for_spans
        from apps.forecasting.cc_softech import cc_returns_from_softech
        old_conn, old_cur = _sybase([(None, None, 0)])
        with mock.patch('config.sybase.get_sybase_connection', old_conn):
            cc_returns_from_softech(2026, 6, ['62', '63'])
        old_sql = old_cur.execute.call_args[0][0]
        new_conn, new_cur = _sybase([(None, None, 0)])
        spans = [('62', SEED_FROM, date(2026, 6, 30)), ('63', SEED_FROM, date(2026, 6, 30))]
        with mock.patch('apps.crews.softech_returns.get_sybase_connection', new_conn):
            returns_for_spans(2026, 6, spans)
        new_sql, params = new_cur.execute.call_args[0]

        def norm(s):
            return ' '.join(s.split())
        old_n = re.sub(r"AND o\.usercode IN \([^)]*\)", 'AND <USERS>', norm(old_sql))
        span = r"\(o\.usercode = \? AND o\.docdate >= \? AND o\.docdate < \?\)"
        new_n, k = re.subn(rf"AND \({span}(?: OR {span})*\)", 'AND <USERS>', norm(new_sql))
        self.assertEqual(k, 1)
        for p in params[:2]:                         # the month bounds, rendered as legacy inlines them
            new_n = new_n.replace('?', f"'{p}'", 1)
        self.assertEqual(old_n.count('<USERS>'), 1)
        self.assertEqual(new_n, old_n)

    def test_no_spans_no_softech_call(self):
        from apps.crews.softech_returns import returns_for_spans
        get_conn = mock.Mock()
        with mock.patch('apps.crews.softech_returns.get_sybase_connection', get_conn):
            self.assertEqual(returns_for_spans(2026, 6, []),
                             {'amount': Decimal('0'), 'profit': Decimal('0'), 'docs': 0})
        get_conn.assert_not_called()


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
        month = crew_kpi.compute_crew_month(c, 2026, 6, returns=False, cdr_rows=self.ROWS)
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
    def test_build_command_writes_only_shadow_table(self):
        self.inv('62', date(2026, 6, 3), 1000, cost=600, phc='P1')
        cc = Branch.objects.create(softech_branch_id='CC', code='CC', name='Call Center',
                                   is_operational=False, kind=Branch.KIND_CALL_CENTER)
        KpiActualRollup.objects.create(branch=cc, year=2026, month=6, metric='cash_delivery',
                                       value=Decimal('5'))
        before = list(KpiActualRollup.objects.values_list('id', 'value'))
        c = self.crew([('62', '', SEED_FROM, None)])
        other = Crew.objects.create(name='وظيفي', type='job')
        archived = self.crew([('62', '', SEED_FROM, None)])
        archived.is_archived = True
        archived.save()
        boom = mock.Mock(side_effect=OSError('SOFTECH down'))
        out = StringIO()
        with mock.patch('apps.crews.softech_returns.get_sybase_connection', boom), \
                mock.patch('apps.crews.kpi.cdr_configured', return_value=False):
            call_command('build_crew_rollups', year=2026, month=6, stdout=out, stderr=StringIO())
        self.assertEqual(list(KpiActualRollup.objects.values_list('id', 'value')), before)
        rows = {r.metric: r for r in CrewKpiRollup.objects.filter(crew=c, year=2026, month=6)}
        self.assertEqual(set(rows), set(FIVE))
        self.assertEqual(rows['cash_delivery'].value, Decimal('1000.00'))
        self.assertIn('returns_unreachable', rows['cash_delivery'].notes)
        self.assertIn('cdr_unavailable', rows['pic_count'].notes)
        self.assertFalse(CrewKpiRollup.objects.filter(crew__in=[other, archived]).exists())
        # re-run with returns + CDR csv updates in place, never duplicates
        get_conn, _ = _sybase([(Decimal('100'), Decimal('40'), 1)])
        with mock.patch('apps.crews.softech_returns.get_sybase_connection', get_conn), \
                mock.patch('apps.crews.kpi.cdr_configured', return_value=False):
            call_command('build_crew_rollups', crew=c.pk, year=2026, month=6, stdout=out)
        rows = {r.metric: r for r in CrewKpiRollup.objects.filter(crew=c, year=2026, month=6)}
        self.assertEqual(rows['cash_delivery'].value, Decimal('900.00'))
        self.assertEqual(rows['gross_profit'].value, Decimal('360.00'))
        self.assertNotIn('returns_unreachable', rows['cash_delivery'].notes)
        self.assertEqual(CrewKpiRollup.objects.filter(crew=c, year=2026, month=6,
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
        self.assertEqual(CrewKpiRollup.objects.get(crew=c, year=2026, month=6,
                                                   metric='call_count').value, Decimal('2'))
        return c

    def test_no_returns_build_marks_rows_returns_not_deducted(self):
        self.inv('62', date(2026, 6, 3), 1000, cost=600, phc='P1')
        c = self.crew([('62', '', SEED_FROM, None)])
        get_conn = mock.Mock()
        with mock.patch('apps.crews.softech_returns.get_sybase_connection', get_conn),                 mock.patch('apps.crews.kpi.cdr_configured', return_value=False):
            call_command('build_crew_rollups', crew=c.pk, year=2026, month=6, no_returns=True,
                         stdout=StringIO())
        get_conn.assert_not_called()
        rows = CrewKpiRollup.objects.filter(crew=c, year=2026, month=6)
        self.assertEqual(set(rows.values_list('metric', flat=True)), set(FIVE))
        for r in rows:
            self.assertIn('returns_not_deducted', r.notes, r.metric)
        # extensions only (no seller): nothing to deduct, no such note
        c2 = self.crew([('', '10', SEED_FROM, None)])
        month = crew_kpi.compute_crew_month(c2, 2026, 6, returns=False, cdr_rows=[])
        self.assertNotIn('returns_not_deducted', month.notes)

    def test_rebuild_without_cdr_removes_stale_call_count(self):
        c = self._build_with_csv()
        with mock.patch('apps.crews.kpi.cdr_configured', return_value=False):
            call_command('build_crew_rollups', crew=c.pk, year=2026, month=6, no_returns=True,
                         stdout=StringIO())
        rows = CrewKpiRollup.objects.filter(crew=c, year=2026, month=6)
        self.assertEqual(set(rows.values_list('metric', flat=True)), set(FIVE))
        self.assertIn('cdr_unavailable', rows.first().notes)

    def test_month_with_nothing_computed_writes_nothing_and_warns(self):
        c = self.crew([('62', '', date(2026, 7, 1), None)])     # no identity in June
        CrewKpiRollup.objects.create(crew=c, year=2026, month=6, metric='beauty', value=1)
        out = StringIO()
        call_command('build_crew_rollups', crew=c.pk, year=2026, month=6, stdout=out)
        self.assertIn('nothing computed', out.getvalue())
        self.assertIn('no_members', out.getvalue())
        self.assertFalse(CrewKpiRollup.objects.filter(crew=c).exists())   # stale row removed
