"""PIC Analytics Task 10 — missed & unanswered calls (doc 33 §4 returned rule, §7)."""
from datetime import date as D
from decimal import Decimal

from django.utils import timezone

from apps.config.models import SystemSetting
from apps.pbx.models import AgentExtension
from apps.pic_analytics.queries.filters import FilterError
from apps.pic_analytics.queries.missed import missed_rows, missed_summary, unanswered_summary
from apps.pic_analytics.queries.overview import overview
from apps.tests.test_pic_queries_calls import CallBase


def iso(dt):
    return timezone.localtime(dt).isoformat()


class MissedTests(CallBase):

    def miss(self, day=D(2026, 10, 5), hh=9, mm=0, key='1000000010', pic='', status='abandoned', **kw):
        return self.call(day, pic, 'inbound', status, key=key, hh=hh, mm=mm, **kw)

    def test_returned_within_window(self):
        self.miss(key='1000000010', hh=9)                                    # outbound answered 23 h later
        self.call(D(2026, 10, 6), '', 'outbound', 'answered', key='1000000010', hh=8)
        self.miss(key='1000000011', hh=9)                                    # 25 h later -> not returned
        self.call(D(2026, 10, 6), '', 'outbound', 'answered', key='1000000011', hh=10)
        s = missed_summary(self.flt(), self.mgmt)
        self.assertEqual((s['missed'], s['returned'], s['not_returned']), (2, 1, 1))
        self.assertEqual(s['median_minutes_to_return'], 23 * 60)

    def test_action_list_drops_rows_called_back_after_the_window(self):
        self.miss(key='1000000010', hh=9)                                    # called back 25 h later
        self.call(D(2026, 10, 6), '', 'outbound', 'answered', key='1000000010', hh=10)
        self.miss(key='1000000011', hh=9)                                    # never called back
        s = missed_summary(self.flt(), self.mgmt)
        self.assertEqual((s['returned'], s['not_returned']), (0, 2))        # KPI keeps the 24 h rule
        self.assertEqual(overview(self.flt(), self.mgmt)['missed_not_returned'], 2)
        rows = missed_rows(self.flt(), self.mgmt, True, 1)
        self.assertEqual(rows['count'], 1)
        self.assertEqual(rows['rows'][0]['customer_number'][-2:], '11')
        self.assertEqual(missed_rows(self.flt(), self.mgmt, False, 1)['count'], 2)

    def test_callback_pending_marker(self):
        from datetime import timedelta
        from apps.callcenter.models import CallLog
        c = self.miss(key='1000000010', hh=9)
        other = self.miss(key='1000000011', hh=9)
        due = timezone.now() + timedelta(days=1)
        CallLog.objects.create(phone_number=c.customer_number, direction='inbound', status='callback',
                               callback_due=due, source='manual')
        rows = {r['call_id']: r for r in missed_rows(self.flt(), self.mgmt, True, 1)['rows']}
        self.assertEqual(rows[c.id]['callback_pending'], {'due': iso(due)})
        self.assertIsNone(rows[other.id]['callback_pending'])

    def test_page_size_none_returns_everything(self):
        for i in range(3):
            self.miss(key=f'10000001{i}0', hh=9 + i)
        self.assertEqual(len(missed_rows(self.flt(), self.mgmt, False, 1, None)['rows']), 3)
        with self.assertRaises(FilterError):
            missed_rows(self.flt(), self.mgmt, False, 1, 0)

    def test_returned_by_inbound_answer_too(self):
        self.miss(hh=9)
        self.call(D(2026, 10, 5), '', 'inbound', 'answered', key='1000000010', hh=12)
        s = missed_summary(self.flt(), self.mgmt)
        self.assertEqual((s['missed'], s['returned'], s['median_minutes_to_return']), (1, 1, 180))

    def test_window_from_setting(self):
        self.miss(hh=9)
        self.call(D(2026, 10, 5), '', 'outbound', 'answered', key='1000000010', hh=12)   # 3 h later
        self.assertEqual(missed_summary(self.flt(), self.mgmt)['not_returned'], 0)
        SystemSetting.objects.create(key='pic_call_return_hours', label='x', value='2', value_type='integer')
        self.assertEqual(missed_summary(self.flt(), self.mgmt)['not_returned'], 1)

    def test_heatmap_cairo_hours(self):
        # 2026-10-10 is a Saturday; 00:30 Cairo = 22:30 UTC on Friday
        self.miss(day=D(2026, 10, 10), hh=0, mm=30, key='1000000012')
        self.miss(day=D(2026, 10, 10), hh=0, mm=45, key='1000000013')
        self.miss(day=D(2026, 10, 9), hh=23, mm=0, key='1000000014')        # Friday 23
        s = missed_summary(self.flt(), self.mgmt)
        self.assertEqual(sorted(s['heatmap']), [[0, 0, 2], [6, 23, 1]])

    def test_agent_filter_ignored_and_transfers_and_answered_excluded(self):
        self.miss(ext='')                                                   # lost in the queue
        self.miss(key='1000000011', ext='10', transfer=True)
        self.call(D(2026, 10, 5), '', 'inbound', 'answered', key='1000000015')
        f = self.flt(agent_ext='99')
        self.assertEqual(missed_summary(f, self.mgmt)['missed'], 1)
        self.assertEqual(overview(f, self.mgmt)['missed_not_returned'], 1)

    def test_summary_numbers_and_queues(self):
        self.miss(key='1000000010', hh=9)
        self.miss(key='1000000010', hh=10)
        self.miss(key='1000000011', hh=10, status='no_answer')
        s = missed_summary(self.flt(), self.mgmt)
        self.assertEqual((s['missed'], s['missed_numbers']), (3, 2))
        self.assertEqual(sum(q['missed'] for q in s['by_queue']), 3)

    def test_rows_sorted_by_value(self):
        c1 = self.miss(pic='N1', key='1000000020', hh=9)      # N1 net 350 by 10-31
        c2 = self.miss(pic='R1', key='1000000021', hh=9)      # R1 net 100
        c3 = self.miss(pic='', key='1000000022', hh=9)        # unknown number -> last
        c4 = self.miss(pic='R1', key='1000000021', hh=11)     # same value, later first
        res = missed_rows(self.flt(), self.mgmt, True, 1)
        self.assertEqual(res['count'], 4)
        self.assertEqual([r['call_at'] for r in res['rows']],
                         [iso(c1.call_at), iso(c4.call_at), iso(c2.call_at), iso(c3.call_at)])
        top = res['rows'][0]
        self.assertEqual((top['pic'], top['customer_name'], top['segment']), ('N1', 'جديد', 'vip'))
        self.assertEqual(top['lifetime_net'], Decimal('350'))
        self.assertEqual(top['last_purchase'], D(2026, 10, 20))
        self.assertIsNone(res['rows'][3]['lifetime_net'])
        self.assertEqual(top['customer_number'], '01000000020')        # admin sees a known customer's number
        self.assertIn('•', res['rows'][3]['customer_number'])          # unknown number stays masked

    def test_rows_return_and_purchase_flags(self):
        self.miss(pic='R1', key='1000000021', day=D(2026, 10, 7), hh=9)      # R1 bought 10-10 (3 d)
        self.call(D(2026, 10, 7), 'R1', 'outbound', 'answered', key='1000000021', hh=10)
        self.miss(pic='N1', key='1000000020', day=D(2026, 10, 1))
        rows = missed_rows(self.flt(), self.mgmt, False, 1)['rows']
        by = {r['pic']: r for r in rows}
        self.assertTrue(by['R1']['bought_within_7d'])
        self.assertEqual(by['R1']['minutes_to_return'], 60)
        self.assertIsNotNone(by['R1']['returned_at'])
        self.assertEqual(len(missed_rows(self.flt(), self.mgmt, True, 1)['rows']), 1)

    def test_management_only_and_page_validation(self):
        with self.assertRaises(PermissionError):
            missed_summary(self.flt(), self.mgr)
        with self.assertRaises(PermissionError):
            missed_rows(self.flt(), self.mgr, True, 1)
        with self.assertRaises(PermissionError):
            unanswered_summary(self.flt(), self.mgr)
        with self.assertRaises(FilterError):
            missed_rows(self.flt(), self.mgmt, True, 0)
        with self.assertRaises(FilterError):
            missed_rows(self.flt(), self.mgmt, True, 1, page_size=500)


class UnansweredTests(CallBase):

    def test_per_agent_attempts_and_reach(self):
        AgentExtension.objects.create(extension='12', pbx_name='Sara -CC12', staff=self.mgr_p)
        d = D(2026, 10, 6)
        for i in range(2):
            self.call(d, 'N1', 'outbound', 'no_answer', ext='12', hh=9, mm=i)
        self.call(d, 'N1', 'outbound', 'answered', ext='12', hh=9, mm=10)         # reached on try 3
        self.call(d, 'R1', 'outbound', 'busy', ext='12', key='1000000040', hh=9)  # never reached
        self.call(d, 'R1', 'outbound', 'no_answer', ext='13', key='1000000041', hh=9)
        res = unanswered_summary(self.flt(), self.mgmt)
        row = next(r for r in res if r['agent_ext'] == '12')
        self.assertEqual((row['attempts'], row['unanswered'], row['reached_numbers'], row['not_reached']),
                         (4, 3, 1, 1))
        self.assertEqual(row['avg_attempts_to_reach'], 3.0)
        self.assertEqual(row['pbx_name'], 'Sara -CC12')
        self.assertEqual(len(unanswered_summary(self.flt(agent_ext='13'), self.mgmt)), 1)
