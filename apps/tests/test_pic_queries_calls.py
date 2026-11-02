"""PIC Analytics Task 9 — calls per PIC, overview call cards, call-center tab (doc 33 §4-§6)."""
from datetime import date as D, datetime, timedelta

from django.utils import timezone

from apps.customers.models import Customer
from apps.pbx.models import AgentExtension, CdrCall
from apps.pic_analytics.queries.calls import call_center, calls_by_pic, returned_map
from apps.pic_analytics.queries.overview import overview
from apps.pic_analytics.queries.pics import pic_rows
from apps.tests.test_pic_queries_overview import Base


def at(day, hh=10, mm=0):
    return timezone.make_aware(datetime(day.year, day.month, day.day, hh, mm))


class CallBase(Base):
    _n = 0

    @classmethod
    def call(cls, day, pic='', direction='inbound', status='answered', ext='10', key='1000000001',
             hh=10, mm=0, billable=60, transfer=False, match=None):
        cls._n += 1
        return CdrCall.objects.create(
            cdr_key=f'k{cls._n}', unique_id=f'u{cls._n}', call_at=at(day, hh, mm), direction=direction,
            status=status, is_transfer=transfer, customer_number='0' + key, phone_key=key,
            agent_ext=ext, agent_name='Agent ' + ext, billable_seconds=billable if status == 'answered' else 0,
            pic=pic, pic_match=match or ('single' if pic else 'none'))


class CallsByPicTests(CallBase):

    def test_counts_and_talk_time(self):
        self.call(D(2026, 10, 5), 'N1', 'inbound', 'answered', billable=120)
        self.call(D(2026, 10, 5), 'N1', 'inbound', 'abandoned')
        self.call(D(2026, 10, 9), 'N1', 'outbound', 'no_answer')
        self.call(D(2026, 10, 11), 'N1', 'outbound', 'answered', billable=30)
        c = calls_by_pic(self.flt(), {'N1'})['N1']
        self.assertEqual((c['in'], c['out'], c['answered'], c['missed']), (2, 2, 2, 1))
        self.assertEqual(c['talk_seconds'], 150)
        self.assertEqual(c['last_call'], at(D(2026, 10, 11)))
        self.assertEqual(c['avg_days_between'], 3.0)       # dates 5, 9, 11 -> gaps 4, 2

    def test_transfer_legs_ignored(self):
        self.call(D(2026, 10, 5), 'N1')
        self.call(D(2026, 10, 5), 'N1', transfer=True)
        self.assertEqual(calls_by_pic(self.flt(), {'N1'})['N1']['in'], 1)
        self.assertEqual(overview(self.flt(), self.mgmt)['calls_in'], 1)

    def test_shared_number_counted_on_latest_buyer_only(self):
        # one call on a number shared by N1 and R1 was resolved to R1 only
        self.call(D(2026, 10, 12), 'R1', match='shared_latest')
        got = calls_by_pic(self.flt(), None)
        self.assertEqual(got['R1']['in'], 1)
        self.assertNotIn('N1', got)

    def test_unresolved_shared_number_counted_once_in_totals(self):
        self.call(D(2026, 10, 12), '', match='shared_unresolved')
        self.assertEqual(calls_by_pic(self.flt(), None), {})
        self.assertEqual(overview(self.flt(), self.mgmt)['calls_in'], 1)

    def test_call_to_purchase_window(self):
        # R1 bought 2026-10-10. A call on 10-03 is exactly 7 days before (counts); 10-02 is 8 (not)
        self.call(D(2026, 10, 3), 'R1')
        self.call(D(2026, 10, 2), 'R1')
        self.assertEqual(calls_by_pic(self.flt(), {'R1'})['R1']['call_to_purchase'], 1)

    def test_call_range_is_cairo_day(self):
        self.call(D(2026, 10, 31), 'N1', hh=23, mm=59)
        self.call(D(2026, 11, 1), 'N1', hh=0, mm=1)
        self.assertEqual(calls_by_pic(self.flt(), {'N1'})['N1']['in'], 1)


class OverviewCallTests(CallBase):

    def test_missed_not_returned(self):
        d = D(2026, 10, 5)
        self.call(d, '', 'inbound', 'abandoned', key='1000000010', hh=9)            # returned in 2 h
        self.call(d, '', 'outbound', 'answered', key='1000000010', hh=11)
        self.call(d, '', 'inbound', 'no_answer', key='1000000011', hh=9)            # nothing
        self.call(d, '', 'inbound', 'abandoned', key='1000000012', hh=9)            # answered after 25 h
        self.call(d + timedelta(days=1), '', 'inbound', 'answered', key='1000000012', hh=10)
        o = overview(self.flt(), self.mgmt)
        self.assertEqual((o['calls_in'], o['calls_out'], o['missed_not_returned']), (4, 1, 2))

    def test_returned_map(self):
        m = self.call(D(2026, 10, 5), '', 'inbound', 'busy', key='1000000020', hh=9)
        r = self.call(D(2026, 10, 5), '', 'inbound', 'answered', key='1000000020', hh=10)
        self.assertEqual(returned_map([m]), {m.id: r.call_at})

    def test_branch_manager_calls_only_for_own_branch_pics(self):
        Customer.objects.create(name='ب', softech_pic='BONLY', softech_id='Q-B', phone='01000000009',
                                softech_created_at=D(2020, 1, 1))
        self.fact('BONLY', D(2026, 10, 8), self.bb, 1, 10, 5, 1, {'10': 10})
        self.call(D(2026, 10, 9), 'BONLY', key='1000000030')
        self.call(D(2026, 10, 9), 'R1', key='1000000031')
        f = self.flt()
        self.assertEqual(overview(f, self.mgmt)['calls_in'], 2)
        self.assertEqual(overview(f, self.mgr)['calls_in'], 1)
        rows = {r['pic']: r for r in pic_rows(f, self.mgr)['rows']}
        self.assertNotIn('BONLY', rows)
        self.assertEqual(rows['R1']['calls_in'], 1)
        self.assertEqual(rows['N1']['calls_in'], 0)
        mrows = {r['pic']: r for r in pic_rows(f, self.mgmt)['rows']}
        self.assertEqual(mrows['BONLY']['calls_in'], 1)


class CallCenterTests(CallBase):

    def test_attempts_to_reach(self):
        d = D(2026, 10, 6)
        for i in range(3):
            self.call(d, 'N1', 'outbound', 'no_answer', ext='12', hh=9, mm=i)
        self.call(d, 'N1', 'outbound', 'answered', ext='12', hh=9, mm=10)
        for i in range(2):                                   # never reached that day
            self.call(d, 'R1', 'outbound', 'busy', ext='12', key='1000000040', hh=9, mm=i)
        res = call_center(self.flt(), self.mgmt)
        row = res['rows'][0]
        self.assertEqual(row['agent_ext'], '12')
        self.assertEqual(row['avg_attempts_to_reach'], 4.0)
        self.assertEqual(row['not_reached'], 1)
        self.assertEqual((row['calls_out'], row['unanswered_out'], row['answered']), (6, 5, 1))
        self.assertEqual(row['pics_reached'], 1)

    def test_rows_names_and_call_to_purchase(self):
        AgentExtension.objects.create(extension='15', pbx_name='Eman -CC15', staff=self.mgr_p)
        self.call(D(2026, 10, 3), 'R1', ext='15', billable=100)      # bought 10-10 -> within 7 d
        self.call(D(2026, 10, 2), 'R1', ext='15', billable=50)       # 8 d -> not
        self.call(D(2026, 10, 4), '', ext='')                        # no extension -> ignored
        res = call_center(self.flt(), self.mgmt)
        self.assertEqual(len(res['rows']), 1)
        row = res['rows'][0]
        self.assertEqual(row['pbx_name'], 'Eman -CC15')
        self.assertTrue(row['staff_name'])
        self.assertEqual((row['answered'], row['talk_seconds']), (2, 150))
        self.assertEqual(row['call_to_purchase_pct'], 50.0)

    def test_team_new_pics_sold_and_branch_manager_refused(self):
        from apps.forecasting.models import CallCenterConfig
        cfg = CallCenterConfig.get_solo()
        cfg.sales_agent_usercodes = ['u1']
        cfg.save()
        self.call(D(2026, 10, 3), 'N1', ext='15')
        # N1's first fact day (10-05) has rows for u1 and u2 -> counts once
        self.assertEqual(call_center(self.flt(), self.mgmt)['team_new_pics_sold'], 1)
        with self.assertRaises(PermissionError):
            call_center(self.flt(), self.mgr)
