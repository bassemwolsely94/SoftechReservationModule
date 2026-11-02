"""PIC Analytics Task 6 — overview KPIs + PIC list (doc 33 §4-§6), on synthetic facts."""
from datetime import date as D, datetime
from decimal import Decimal

from django.test import RequestFactory, TestCase
from django.utils import timezone

from apps.branches.models import Branch
from apps.customers.models import Customer, PurchaseHistory
from apps.pic_analytics import build
from apps.pic_analytics.access import Access
from apps.pic_analytics.models import PicAnalyticsAccess, PicDayFact, PicRollup
from apps.pic_analytics.queries.filters import FilterError, Filters
from apps.pic_analytics.queries.overview import overview
from apps.pic_analytics.queries.pics import pic_rows
from apps.tests.factories import make_user

D_ = Decimal


class Base(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.ba = Branch.objects.create(softech_branch_id='961', code='961', name='A', name_ar='أ', is_operational=True)
        cls.bb = Branch.objects.create(softech_branch_id='962', code='962', name='B', name_ar='ب', is_operational=True)
        _, cls.admin_p, _c = make_user('q_admin', role='admin', branch=cls.ba)
        _, cls.mgr_p, _c = make_user('q_mgr', role='pharmacist', branch=cls.ba)
        PicAnalyticsAccess.objects.create(staff=cls.mgr_p, granted_by=cls.admin_p)
        cls.mgmt, cls.mgr = Access(cls.admin_p.user), Access(cls.mgr_p.user)
        Customer.objects.create(name='جديد', softech_pic='N1', softech_id='Q-N1', phone='01000000001',
                                softech_created_at=D(2026, 10, 1), segment='vip')
        Customer.objects.create(name='عائد', softech_pic='R1', softech_id='Q-R1', phone='01000000002',
                                softech_created_at=D(2025, 1, 1))
        Customer.objects.create(name='مُعاد', softech_pic='RE', softech_id='Q-RE', phone='01000000003',
                                softech_created_at=D(2024, 1, 1))
        cls.fact('N1', D(2026, 10, 5), cls.ba, 1, 100, 60, 2, {'10': 60, '50': 40}, sp='u1')
        cls.fact('N1', D(2026, 10, 5), cls.ba, 1, 50, 30, 1, {'10': 50}, sp='u2')
        cls.fact('N1', D(2026, 10, 20), cls.bb, 1, 200, 120, 4, {'10': 200})
        cls.fact('R1', D(2026, 7, 1), cls.ba, 1, 10, 5, 1, {'10': 10})
        cls.fact('R1', D(2026, 9, 15), cls.ba, 1, 10, 5, 1, {'10': 10})
        cls.fact('R1', D(2026, 10, 10), cls.ba, 1, 80, 50, 2, {'10': 80})
        cls.fact('RE', D(2025, 6, 1), cls.ba, 1, 5, 3, 1, {'10': 5})
        cls.fact('RE', D(2026, 10, 12), cls.ba, 1, 40, 20, 1, {'50': 40})
        cls.fact('GONE', D(2026, 9, 20), cls.ba, 1, 10, 5, 1, {'10': 10})
        cls.fact('', D(2026, 10, 6), cls.ba, 1, 30, 20, 1, {'10': 30})
        PicRollup.objects.create(pic='R1', as_of=D(2026, 11, 1), first_purchase=D(2026, 7, 1),
                                 last_purchase=D(2026, 10, 10), months_a=9, streak_b=2,
                                 cycle_days=D_('10'), cycle_bucket='m1')

    @staticmethod
    def fact(pic, day, branch, inv, net, cost, units, cats, sp='', chan='cash'):
        return PicDayFact.objects.create(pic=pic, day=day, branch=branch, salesperson=sp, channel_bucket=chan,
                                         invoices=inv, net=D_(net), cost=D_(cost), units=D_(units),
                                         gp_net=D_(net), gp=D_(net) - D_(cost),
                                         lines=1, net_by_category={k: str(v) for k, v in cats.items()})

    def flt(self, **kw):
        kw.setdefault('start', D(2026, 10, 1))
        kw.setdefault('end', D(2026, 10, 31))
        return Filters(**kw)


class OverviewTests(Base):

    def test_counts_new_returning_reactivated(self):
        o = overview(self.flt(), self.mgmt)
        self.assertEqual((o['distinct_pics'], o['new'], o['returning'], o['reactivated']), (3, 1, 2, 1))
        self.assertEqual([m['month'] for m in o['by_month']], ['2026-10'])
        self.assertEqual((o['by_month'][0]['distinct_pics'], o['by_month'][0]['new']), (3, 1))
        self.assertEqual(o['retention_pct'], 50.0)       # prev period: R1, GONE; R1 came back
        self.assertEqual(o['new_reliable_from'], None)

    def test_visits_per_pic_and_basket(self):
        o = overview(self.flt(), self.mgmt)
        self.assertEqual((o['visits'], o['invoices']), (4, 5))     # N1 two days (3 invoices)
        self.assertEqual(o['net'], D_('470'))
        self.assertEqual(o['units'], D_('10'))
        self.assertEqual((o['basket_net'], o['basket_units']), (D_('117.5'), D_('2.5')))
        self.assertEqual(o['basket_categories'], 1.25)
        self.assertEqual(o['visits_per_pic'], 1.33)
        self.assertEqual(o['gp'], D_('190'))
        self.assertEqual(o['gp_pct'], round(D_(190) / D_(470) * 100, 2))
        self.assertEqual(o['no_pic_net'], D_('30'))
        self.assertEqual(o['calls_in'], 0)

    def test_gp_uses_gp_fields_not_header_net(self):
        PicDayFact.objects.filter(pic='N1', day=D(2026, 10, 5)).update(gp_net=D_('1000'), gp=D_('250'))
        base = PicDayFact.objects.filter(day__gte=D(2026, 10, 1), day__lte=D(2026, 10, 31)).exclude(pic='')
        from django.db.models import Sum
        a = base.aggregate(g=Sum('gp'), n=Sum('gp_net'))
        o = overview(self.flt(), self.mgmt)
        self.assertEqual(o['gp'], a['g'])
        self.assertEqual(o['gp_pct'], round(a['g'] / a['n'] * 100, 2))

    def test_no_pic_sales_line_reconciles(self):
        PicDayFact.objects.all().delete()
        Customer.objects.all().delete()
        c = Customer.objects.create(name='p', softech_pic='Z1', softech_id='Z-1')
        n = [0]

        def inv(pic, day, total, doc='115'):
            n[0] += 1
            PurchaseHistory.objects.create(
                customer=c, softech_invoice_id=f'Q6-{n[0]}', branch=self.ba, doc_code=doc,
                total_amount=D_(total), invoice_date=timezone.make_aware(datetime(2026, 10, day, 12)),
                sales_channel='91', sales_person_type='10', softech_user='u1', softech_phcode=pic)
        inv('Z1', 3, '100')
        inv('', 4, '30')
        inv('ACCT-9', 5, '70')
        inv('Z1', 6, '20', doc='30')
        build.build_day_facts(D(2026, 10, 1), D(2026, 10, 31))
        o = overview(self.flt(), self.mgmt)
        total = sum(p.total_amount * (-1 if p.doc_code == '30' else 1) for p in PurchaseHistory.objects.all())
        self.assertEqual(o['net'] + o['no_pic_net'], total)
        self.assertEqual(o['no_pic_net'], D_('100'))

    def test_branch_manager_amounts_from_own_branch_only(self):
        o = overview(self.flt(), self.mgr)                  # manager of A
        self.assertEqual(o['net'], D_('270'))               # N1's 200 at B excluded
        self.assertEqual(o['visits'], 3)
        self.assertEqual(o['no_pic_net'], D_('30'))
        self.fact('BONLY', D(2026, 10, 15), self.bb, 1, 999, 1, 1, {'10': 999})
        o = overview(self.flt(), self.mgr)
        self.assertEqual((o['distinct_pics'], o['net']), (3, D_('270')))
        self.assertEqual(o['new'], 1)                       # N1 still labelled new chain-wide
        # a branch filter cannot widen the manager's scope
        o2 = overview(self.flt(branch_ids={self.bb.pk}), self.mgr)
        self.assertEqual(o2['distinct_pics'], 0)
        self.assertEqual(overview(self.flt(), self.mgmt)['distinct_pics'], 4)

    def test_gp_absent_for_branch_manager(self):
        o = overview(self.flt(), self.mgr)
        self.assertNotIn('gp', o)
        self.assertNotIn('gp_pct', o)
        self.assertIn('gp', overview(self.flt(), self.mgmt))
        self.assertNotIn('gp', pic_rows(self.flt(), self.mgr)['rows'][0])

    def test_range_clamped_to_history(self):
        req = RequestFactory().get('/x', {'from': '2020-01-01', 'to': '2099-01-01'})
        f = Filters.from_request(req, self.mgmt)
        self.assertEqual(f.start, D(2024, 8, 1))
        self.assertEqual(f.end, timezone.localdate())
        self.assertTrue(f.clamped)
        self.assertEqual((f.data_from, f.data_to), (D(2024, 8, 1), timezone.localdate()))
        ok = Filters.from_request(RequestFactory().get('/x', {'from': '2026-10-01', 'to': '2026-10-31',
                                                              'branch': '1,2', 'category': '10'}), self.mgmt)
        self.assertFalse(ok.clamped)
        self.assertEqual((ok.branch_ids, ok.category), ({1, 2}, '10'))
        for bad in ({}, {'from': '2026-10-01'}, {'from': 'x', 'to': '2026-10-02'},
                    {'from': '2026-10-05', 'to': '2026-10-01'}):
            with self.assertRaises(FilterError):
                Filters.from_request(RequestFactory().get('/x', bad), self.mgmt)
        self.assertTrue(issubclass(FilterError, ValueError))

    def test_new_reliable_fallback_and_filters(self):
        o = overview(self.flt(category='50'), self.mgmt)     # category net only
        self.assertEqual((o['net'], o['distinct_pics']), (D_('80'), 2))
        self.assertIsNone(o['gp'])
        self.assertEqual((o['units'], o['basket_units'], o['basket_categories']), (None, None, None))
        self.assertIsNone(pic_rows(self.flt(category='50'), self.mgmt)['rows'][0]['units'])
        self.fact('NEG', D(2026, 10, 8), self.ba, 1, 5, 1, 1, {'50': -5})     # key present, net <= 0
        o = overview(self.flt(category='50'), self.mgmt)
        self.assertEqual((o['net'], o['distinct_pics'], o['visits']), (D_('80'), 2, 2))
        self.assertEqual(overview(self.flt(segment='vip'), self.mgmt)['distinct_pics'], 1)
        self.assertEqual(overview(self.flt(frequency='m2'), self.mgmt)['distinct_pics'], 1)
        self.assertEqual(overview(self.flt(channel_bucket='delivery'), self.mgmt)['distinct_pics'], 0)
        Customer.objects.update(softech_created_at=None)
        self.assertEqual(overview(self.flt(), self.mgmt)['new_reliable_from'], '2025-08-01')


class PicListTests(Base):

    def test_pic_list_sort_and_page(self):
        r = pic_rows(self.flt(), self.mgmt, '-net', 1, 50)
        self.assertEqual(r['count'], 3)
        self.assertEqual([x['pic'] for x in r['rows']], ['N1', 'R1', 'RE'])
        n1 = r['rows'][0]
        self.assertEqual((n1['net'], n1['gp'], n1['visits'], n1['invoices'], n1['units']),
                         (D_('350'), D_('140'), 2, 3, D_('7')))
        self.assertEqual((n1['categories'], n1['channels'], n1['last_branch']), (['10', '50'], ['cash'], self.bb.pk))
        self.assertEqual((n1['first_purchase'], n1['last_purchase']), (D(2026, 10, 5), D(2026, 10, 20)))
        self.assertEqual(n1['basket_net'], D_('175'))
        self.assertEqual(n1['calls_in'], 0)
        r1 = r['rows'][1]
        self.assertEqual((r1['months_a'], r1['cycle_bucket']), (3, 'm2'))   # computed to 2026-10-31, not the rollup's 9
        self.assertEqual(r1['first_purchase'], D(2026, 7, 1))
        self.assertFalse(r1['overdue'])       # 21 days since last vs cycle 50.5 d
        self.assertEqual([x['pic'] for x in pic_rows(self.flt(), self.mgmt, 'net')['rows']], ['RE', 'R1', 'N1'])
        self.assertEqual([x['pic'] for x in pic_rows(self.flt(), self.mgmt, 'days_since_last')['rows']][0], 'N1')
        self.assertEqual([x['pic'] for x in pic_rows(self.flt(), self.mgmt, '-days_since_last')['rows']][0], 'R1')
        self.assertEqual([x['pic'] for x in pic_rows(self.flt(), self.mgmt, '-last_purchase')['rows']][0], 'N1')
        p2 = pic_rows(self.flt(), self.mgmt, '-net', 2, 2)
        self.assertEqual((p2['count'], [x['pic'] for x in p2['rows']]), (3, ['RE']))
        self.assertEqual(len(pic_rows(self.flt(), self.mgmt, 'bogus')['rows']), 3)

    def test_phone_masked_and_branch_manager_figures(self):
        row = pic_rows(self.flt(), self.mgmt)['rows'][0]
        self.assertEqual(row['phone'], '01000000001')         # admin sees phones
        m = {x['pic']: x for x in pic_rows(self.flt(), self.mgr)['rows']}
        self.assertNotEqual(m['N1']['phone'], '01000000001')  # not an own customer -> masked
        self.assertEqual((m['N1']['net'], m['N1']['visits'], m['N1']['last_purchase']), (D_('150'), 1, D(2026, 10, 5)))


class FrequencyToDateTests(Base):

    def test_frequency_follows_report_to_date_not_rollup(self):
        from datetime import timedelta
        from apps.pic_analytics.queries.frequency import pic_frequency
        yesterday = timezone.localdate() - timedelta(days=1)
        self.assertEqual(pic_frequency({'R1'}, yesterday)['R1']['months_a'], 9)          # rollup
        fr = pic_frequency({'R1'}, D(2026, 10, 31))['R1']                                # computed
        self.assertEqual((fr['months_a'], fr['streak_b'], fr['cycle_bucket'], fr['last_visit']),
                         (3, 2, 'm2', D(2026, 10, 10)))
        early = pic_frequency({'R1'}, D(2026, 9, 30))['R1']                              # later days ignored
        self.assertEqual((early['months_a'], early['last_visit']), (2, D(2026, 9, 15)))
        self.assertEqual(pic_rows(self.flt(), self.mgmt)['rows'][1]['months_a'], 3)

    def test_overdue_and_days_since_last_relative_to_to_date(self):
        self.fact('OD', D(2026, 10, 1), self.ba, 1, 10, 5, 1, {'10': 10})
        self.fact('OD', D(2026, 10, 3), self.ba, 1, 10, 5, 1, {'10': 10})
        late = {r['pic']: r for r in pic_rows(self.flt(), self.mgmt)['rows']}['OD']
        self.assertTrue(late['overdue'])                       # 28 d since 10-03 > 1.5 x 2 d
        self.assertEqual(late['days_since_last'], 28)
        early = {r['pic']: r for r in pic_rows(self.flt(end=D(2026, 10, 4)), self.mgmt)['rows']}['OD']
        self.assertFalse(early['overdue'])
        self.assertEqual(early['days_since_last'], 1)
