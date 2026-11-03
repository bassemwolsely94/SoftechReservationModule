"""PIC Analytics Task 8 — frequency classes, overdue list, retention and cohorts, on synthetic facts."""
from datetime import date as D, timedelta
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from apps.branches.models import Branch
from apps.customers.models import Customer
from apps.pic_analytics import build, rules
from apps.pic_analytics.access import Access
from apps.pic_analytics.models import PicAnalyticsAccess, PicDayFact
from apps.pic_analytics.queries.filters import FilterError, Filters
from apps.pic_analytics.queries.frequency import pic_frequency
from apps.pic_analytics.queries.retention import cohorts, frequency, overdue_list, retention_summary
from apps.tests.factories import make_user

D_ = Decimal


class RetBase(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.ba = Branch.objects.create(softech_branch_id='971', code='971', name='A', name_ar='أ', is_operational=True)
        cls.bb = Branch.objects.create(softech_branch_id='972', code='972', name='B', name_ar='ب', is_operational=True)
        _, cls.admin_p, _c = make_user('rt_admin', role='admin', branch=cls.ba)
        _, cls.mgr_p, _c = make_user('rt_mgr', role='pharmacist', branch=cls.ba)
        PicAnalyticsAccess.objects.create(staff=cls.mgr_p, granted_by=cls.admin_p)
        cls.mgmt, cls.mgr = Access(cls.admin_p.user), Access(cls.mgr_p.user)

    @staticmethod
    def fact(pic, day, branch, net=10, first=False, inv=1):
        return PicDayFact.objects.create(pic=pic, day=day, branch=branch, invoices=inv, net=D_(net), cost=D_(1),
                                         units=D_(1), lines=1, net_by_category={'10': str(net)},
                                         is_first_purchase=first)

    def flt(self, start=D(2026, 10, 1), end=D(2026, 10, 31), **kw):
        return Filters(start=start, end=end, **kw)


class FrequencyTests(RetBase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # P1: Aug, Sep, Oct (A=3, B=3); P2: single visit; P3: 10 distinct months (loyal)
        for d in (D(2026, 8, 1), D(2026, 9, 1), D(2026, 10, 2)):
            cls.fact('P1', d, cls.ba)
        cls.fact('P2', D(2026, 10, 5), cls.ba)
        for m in range(1, 11):
            cls.fact('P3', D(2026, m, 3), cls.ba)
        cls.fact('P3', D(2026, 10, 20), cls.ba)       # a second visit in the period

    def test_frequency_classes_match_rules(self):
        res = frequency(self.flt(), self.mgmt)
        self.assertEqual(sorted(res['a']), list(range(1, 13)))
        self.assertEqual(sorted(res['b']), list(range(1, 13)))
        vis = {'P1': [D(2026, 8, 1), D(2026, 9, 1), D(2026, 10, 2)], 'P2': [D(2026, 10, 5)],
               'P3': [D(2026, m, 3) for m in range(1, 11)] + [D(2026, 10, 20)]}
        end = D(2026, 10, 31)
        exp_a, exp_c = {}, {}
        for days in vis.values():
            a = rules.months_bought(days, end)
            exp_a[a] = exp_a.get(a, 0) + 1
            bk = rules.cycle_bucket(rules.cycle_days(days))
            exp_c[bk] = exp_c.get(bk, 0) + 1
        for k in range(1, 13):
            self.assertEqual(res['a'][k], exp_a.get(k, 0))
        self.assertEqual((res['b'][1], res['b'][3], res['b'][10]), (1, 1, 1))
        for b in ('m1', 'm2', 'm3', 'm4_6', 'm7_12', 'y1plus', ''):
            self.assertEqual(res['c'][b], exp_c.get(b, 0))
        self.assertEqual(res['c'][''], 1)              # single-visit P2
        self.assertEqual(res['loyal'], 1)              # P3 only (10 months)

    def test_rollup_and_on_the_fly_agree(self):
        yday = timezone.localdate() - timedelta(days=1)
        pics = ('Y1', 'Y2', 'Y3')
        for d in (yday, yday - timedelta(days=40), yday - timedelta(days=100)):
            self.fact('Y1', d, self.ba)
        self.fact('Y2', yday, self.bb)
        for d in (yday - timedelta(days=3), yday - timedelta(days=33)):
            self.fact('Y3', d, self.ba)
        build.build_rollups(yday)
        via_rollup = pic_frequency(pics, yday)
        computed = pic_frequency(pics, yday, force_compute=True)
        self.assertEqual(set(via_rollup), set(computed))
        for p in pics:
            a, b = via_rollup[p], computed[p]
            self.assertEqual((a['months_a'], a['streak_b'], a['cycle_bucket'], a['last_visit']),
                             (b['months_a'], b['streak_b'], b['cycle_bucket'], b['last_visit']))
            self.assertAlmostEqual(a['cycle_days'] or 0, b['cycle_days'] or 0, places=2)
        # frequency() through the rollup path gives the same class counts as the computed path
        f = self.flt(start=yday - timedelta(days=7), end=yday)
        res = frequency(f, self.mgmt)
        with mock.patch('apps.pic_analytics.queries.retention.pic_frequency',
                        lambda p, e: pic_frequency(p, e, force_compute=True)):
            self.assertEqual(frequency(f, self.mgmt), res)
        self.assertEqual(res['c'][''], 1)              # Y2 (single visit); Y1 and Y3 have cycles
        self.assertEqual(sum(res['a'].values()), 3)


class OverdueTests(RetBase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        Customer.objects.create(name='متأخر', softech_pic='O1', softech_id='R-O1', phone='01000000011')
        Customer.objects.create(name='منتظم', softech_pic='O2', softech_id='R-O2', phone='01000000012')
        # O1: last visit 23 days before the end, cycle ~12 days -> overdue at 1.5, not at 3
        for d in (D(2026, 9, 1), D(2026, 9, 11), D(2026, 9, 21), D(2026, 10, 8)):
            cls.fact('O1', d, cls.ba, net=500)
        # O2: last visit 5 days before the end, cycle 10 -> not overdue
        for d in (D(2026, 10, 6), D(2026, 10, 16), D(2026, 10, 26)):
            cls.fact('O2', d, cls.bb, net=50)
        cls.fact('O3', D(2026, 10, 12), cls.ba, net=70)    # single visit: no cycle, never overdue

    def test_overdue_uses_setting_factor(self):
        f = self.flt()
        self.assertEqual(frequency(f, self.mgmt)['overdue'], 1)
        lst = overdue_list(f, self.mgmt, 1)
        self.assertEqual(lst['count'], 1)
        row = lst['rows'][0]
        self.assertEqual((row['pic'], row['name'], row['last_visit']), ('O1', 'متأخر', D(2026, 10, 8)))
        cyc = rules.cycle_days([D(2026, 9, 1), D(2026, 9, 11), D(2026, 9, 21), D(2026, 10, 8)])
        self.assertAlmostEqual(row['cycle_days'], cyc, places=2)
        self.assertEqual(row['days_overdue'], round(23 - 1.5 * cyc))
        self.assertEqual(row['lifetime_net'], D_('2000'))
        mrow = overdue_list(f, self.mgr, 1)['rows'][0]
        self.assertNotEqual(mrow['phone'], '01000000011')      # a branch manager sees it masked
        with mock.patch('apps.pic_analytics.queries.retention.setting', return_value=3):
            self.assertEqual(frequency(f, self.mgmt)['overdue'], 0)
            self.assertEqual(overdue_list(f, self.mgmt, 1)['count'], 0)

    def test_branch_manager_lifetime_net_scoped_and_validation(self):
        self.fact('O1', D(2026, 10, 8), self.bb, net=1000)    # other branch, same day
        lst = overdue_list(self.flt(), self.mgr, 1)
        self.assertEqual(lst['rows'][0]['lifetime_net'], D_('2000'))   # branch A only
        for bad in (0, 'x', -1):
            with self.assertRaises(FilterError):
                overdue_list(self.flt(), self.mgmt, bad)
        with self.assertRaises(FilterError):
            overdue_list(self.flt(), self.mgmt, 1, page_size=500)


class RetentionCohortTests(RetBase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # cohort 2026-08: C1 (branch A), C2 (branch B); C1 returns in Sep and Oct, C2 in Oct
        cls.fact('C1', D(2026, 8, 10), cls.ba, first=True)
        cls.fact('C2', D(2026, 8, 12), cls.bb, first=True)
        cls.fact('C1', D(2026, 9, 5), cls.ba)
        cls.fact('C1', D(2026, 10, 5), cls.ba)
        cls.fact('C2', D(2026, 10, 6), cls.bb)
        cls.fact('C3', D(2026, 10, 9), cls.ba, first=True)     # cohort 2026-10

    def test_cohort_table_shape(self):
        res = cohorts(self.flt(), self.mgmt)
        self.assertEqual(len(res), 12)
        self.assertEqual((res[0]['cohort'], res[-1]['cohort']), ('2025-11', '2026-10'))
        by = {r['cohort']: r for r in res}
        self.assertEqual(by['2026-08']['size'], 2)
        self.assertEqual(by['2026-08']['months'], [50.0, 100.0])     # Sep: C1; Oct: C1 + C2
        self.assertEqual((by['2026-10']['size'], by['2026-10']['months']), (1, []))
        self.assertEqual(by['2025-11']['size'], 0)
        self.assertEqual(len(by['2025-11']['months']), 11)
        self.assertTrue(all(len(r['months']) <= 12 for r in res))

    def test_cohort_branch_manager_scope(self):
        by = {r['cohort']: r for r in cohorts(self.flt(), self.mgr)}
        self.assertEqual(by['2026-08']['size'], 1)                   # C2 started at branch B
        self.assertEqual(by['2026-08']['months'], [100.0, 100.0])

    def test_retention_summary(self):
        res = retention_summary(self.flt(data_from=D(2024, 8, 1)), self.mgmt)
        self.assertEqual(res['prev_period'], (D(2026, 8, 31), D(2026, 9, 30)))
        self.assertEqual(res['retention_pct'], 100.0)                # C1 (Sep) bought again in Oct
        old = self.flt(start=D(2024, 8, 1), end=D(2024, 8, 31), data_from=D(2024, 8, 1))
        self.assertIsNone(retention_summary(old, self.mgmt)['retention_pct'])
