from datetime import date as D, datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.branches.models import Branch
from apps.catalog.models import Item
from apps.customers.models import Customer, PurchaseHistory, PurchaseHistoryLine
from apps.forecasting.kpi import KpiResolver
from apps.forecasting.models import ChannelBucketMap, ProfitExclusion
from apps.pic_analytics import build, rules
from apps.pic_analytics.models import PicDayFact, PicRollup


def at(y, m, d):
    return timezone.make_aware(datetime(y, m, d))


class PicBuildTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ba = Branch.objects.create(softech_branch_id='971', code='971', name='A', name_ar='أ', is_operational=True)
        cls.bb = Branch.objects.create(softech_branch_id='972', code='972', name='B', name_ar='ب', is_operational=True)
        cls.c1 = Customer.objects.create(name='p1', softech_pic='P1', softech_id='C-P1')
        cls.c2 = Customer.objects.create(name='p2', softech_pic='P2', softech_id='C-P2')
        cls.cph = Customer.objects.create(name='acct', softech_pic='ACCT-9', softech_id='C-PH',
                                          is_account_placeholder=True)
        cls.cm = Customer.objects.create(name='merged', softech_pic='PM', softech_id='C-PM', merged_into_pic='P1')
        cls.m10 = Item.objects.create(softech_id='T4A', name='a', medicine_type='10')
        cls.m50 = Item.objects.create(softech_id='T4B', name='b', medicine_type='50')
        ChannelBucketMap.objects.create(person_type='10', channel='91', label='cash', bucket='cash',
                                        counts_customer=True, include_in_profit=True, active=True)
        ChannelBucketMap.objects.create(person_type='10', channel='90', label='deliv', bucket='cash',
                                        subtype='delivery', counts_customer=True, include_in_profit=True, active=True)
        cls.n = 0

    def inv(self, cust, pic, when, total, branch=None, doc='115', lines=(), channel='91', user='u1'):
        PicBuildTests.n += 1
        ph = PurchaseHistory.objects.create(
            customer=cust, softech_invoice_id=f'T4-{PicBuildTests.n}', branch=branch or self.ba, doc_code=doc,
            total_amount=Decimal(total), invoice_date=when, sales_channel=channel, sales_person_type='10',
            softech_user=user, softech_phcode=pic)
        for item, qty, val, cost in lines:
            PurchaseHistoryLine.objects.create(purchase=ph, item=item, quantity=Decimal(qty), unit_price=Decimal(val),
                                               line_total=Decimal(val), cost_at_sale=Decimal(cost), list_price=Decimal(val))
        return ph

    def seed(self):
        # P1: earliest-ever sale before the window; two same-day invoices; a return
        self.inv(self.c1, 'P1', at(2026, 8, 10), '40')
        self.inv(self.c1, 'P1', at(2026, 10, 5), '100', lines=[(self.m10, 2, '100', '20')])
        self.inv(self.c1, 'P1', at(2026, 10, 5), '200', lines=[(self.m50, 1, '200', '70')])
        self.inv(self.c1, 'P1', at(2026, 10, 7), '50', doc='30', lines=[(self.m10, 1, '50', '20')])
        # P2: first-ever sale inside the window, two days
        self.inv(self.c2, 'P2', at(2026, 10, 3), '30', branch=self.bb, channel='90')
        self.inv(self.c2, 'P2', at(2026, 10, 9), '70', branch=self.bb)
        # placeholder / ACCT / merged invoices
        self.inv(self.cph, 'ACCT-9', at(2026, 10, 5), '500')
        self.inv(self.cm, 'PM', at(2026, 10, 6), '25')

    def test_same_day_invoices_one_fact_row(self):
        self.seed()
        build.build_day_facts(D(2026, 10, 1), D(2026, 10, 31))
        f = PicDayFact.objects.get(pic='P1', day=D(2026, 10, 5))
        self.assertEqual((f.invoices, f.net), (2, Decimal('300.00')))
        self.assertEqual(f.channel_bucket, 'cash')
        self.assertEqual(PicDayFact.objects.get(pic='P2', day=D(2026, 10, 3)).channel_bucket, 'delivery')

    def test_return_reduces_net_on_its_own_day(self):
        self.seed()
        build.build_day_facts(D(2026, 10, 1), D(2026, 10, 31))
        f = PicDayFact.objects.get(pic='P1', day=D(2026, 10, 7))
        self.assertEqual((f.invoices, f.returns, f.net), (0, 1, Decimal('-50.00')))
        self.assertEqual(f.cost, Decimal('-20.00'))

    def test_gp_and_categories(self):
        self.seed()
        build.build_day_facts(D(2026, 10, 1), D(2026, 10, 31))
        f = PicDayFact.objects.get(pic='P1', day=D(2026, 10, 5))
        self.assertEqual(f.cost, Decimal('110.00'))  # 2*20 + 1*70
        self.assertEqual(f.units, Decimal('3'))
        self.assertEqual(f.lines, 2)
        self.assertEqual({k: Decimal(v) for k, v in f.net_by_category.items()},
                         {'10': Decimal('100'), '50': Decimal('200')})

    def gp_seed(self):
        ChannelBucketMap.objects.create(person_type='10', channel='95', label='ins', bucket='exclude',
                                        include_in_profit=False, active=True)
        dlv = Item.objects.create(softech_id='T4D', name='dlv', medicine_type='10')
        ProfitExclusion.objects.create(item=dlv, active=True)
        # profit channel: 200 revenue - 60 cost, plus an excluded item (30 revenue, 1 cost) -> gp 140 over gp_net 200
        self.inv(self.c1, 'P1', at(2026, 10, 5), '230', lines=[(self.m10, 2, '200', '30'), (dlv, 1, '30', '1')])
        # non-profit channel line: ignored by gp
        self.inv(self.c1, 'P1', at(2026, 10, 5), '500', channel='95', lines=[(self.m50, 1, '500', '100')])
        # return of 50 revenue / 20 cost on the profit channel
        self.inv(self.c1, 'P1', at(2026, 10, 7), '50', doc='30', lines=[(self.m10, 1, '50', '20')])

    def test_gp_counts_profit_channels_and_skips_excluded_items(self):
        self.gp_seed()
        build.build_day_facts(D(2026, 10, 1), D(2026, 10, 31))
        f = PicDayFact.objects.get(pic='P1', day=D(2026, 10, 5), channel_bucket='cash')
        self.assertEqual((f.gp_net, f.gp), (Decimal('200.00'), Decimal('140.00')))
        x = PicDayFact.objects.get(pic='P1', day=D(2026, 10, 5), channel_bucket='exclude')
        self.assertEqual((x.gp_net, x.gp), (Decimal('0'), Decimal('0')))

    def test_return_reduces_gp(self):
        self.gp_seed()
        build.build_day_facts(D(2026, 10, 1), D(2026, 10, 31))
        r = PicDayFact.objects.get(pic='P1', day=D(2026, 10, 7))
        self.assertEqual((r.gp_net, r.gp), (Decimal('-50.00'), Decimal('-30.00')))

    def test_gp_equals_kpi_board_net_profit(self):
        from django.db.models import Sum
        self.gp_seed()
        self.seed()
        build.build_day_facts(D(2026, 10, 1), D(2026, 10, 31))
        kr = KpiResolver()
        kpi = kr._net_profit(None, D(2026, 10, 1), D(2026, 10, 31), kr.profit_channels)
        got = PicDayFact.objects.aggregate(s=Sum('gp'))['s']
        self.assertEqual(got, kpi.quantize(Decimal('0.01')))
        self.assertNotEqual(got, 0)

    def test_placeholder_sales_go_to_blank_pic(self):
        self.seed()
        build.build_day_facts(D(2026, 10, 1), D(2026, 10, 31))
        self.assertEqual(PicDayFact.objects.get(pic='', day=D(2026, 10, 5)).net, Decimal('500.00'))
        self.assertEqual(PicDayFact.objects.get(pic='', day=D(2026, 10, 6)).net, Decimal('25.00'))
        self.assertFalse(PicDayFact.objects.filter(pic__in=['ACCT-9', 'PM']).exists())

    def test_first_purchase_flag(self):
        self.seed()
        build.build_day_facts(D(2026, 10, 1), D(2026, 10, 31))
        self.assertFalse(PicDayFact.objects.get(pic='P1', day=D(2026, 10, 5)).is_first_purchase)
        self.assertTrue(PicDayFact.objects.get(pic='P2', day=D(2026, 10, 3)).is_first_purchase)
        self.assertFalse(PicDayFact.objects.get(pic='P2', day=D(2026, 10, 9)).is_first_purchase)
        self.assertFalse(PicDayFact.objects.filter(pic='', is_first_purchase=True).exists())

    def test_rebuild_is_idempotent(self):
        self.seed()
        n1 = build.build_day_facts(D(2026, 10, 1), D(2026, 10, 31))
        s1 = sum(PicDayFact.objects.values_list('net', flat=True))
        n2 = build.build_day_facts(D(2026, 10, 1), D(2026, 10, 31))
        self.assertEqual((n1, PicDayFact.objects.count()), (n2, n1))
        self.assertEqual(s1, sum(PicDayFact.objects.values_list('net', flat=True)))

    def test_cairo_local_day(self):
        self.inv(self.c1, 'P1', at(2026, 10, 12), '10')
        build.build_day_facts(D(2026, 10, 12), D(2026, 10, 12))
        self.assertEqual(PicDayFact.objects.get(pic='P1').day, D(2026, 10, 12))

    def test_rollup_frequency(self):
        self.seed()
        build.build_day_facts(D(2026, 8, 1), D(2026, 10, 31))
        n = build.build_rollups(D(2026, 10, 31))
        self.assertEqual(n, 2)
        r = PicRollup.objects.get(pic='P1')
        visits = [D(2026, 8, 10), D(2026, 10, 5)]
        self.assertEqual((r.months_a, r.streak_b), (rules.months_bought(visits, D(2026, 10, 31)),
                                                    rules.longest_streak(visits, D(2026, 10, 31))))
        self.assertEqual(r.cycle_bucket, rules.cycle_bucket(rules.cycle_days(visits)))
        self.assertEqual((r.first_purchase, r.last_purchase, r.prev_visit_before_last),
                         (D(2026, 8, 10), D(2026, 10, 5), D(2026, 8, 10)))
        self.assertEqual(r.lifetime_net, Decimal('290.00'))  # 40 + 300 - 50
        self.assertEqual(r.home_branch_id, self.ba.id)
        self.assertEqual(PicRollup.objects.get(pic='P2').home_branch_id, self.bb.id)

    def test_rollup_ignores_days_after_as_of(self):
        self.seed()
        build.build_day_facts(D(2026, 8, 1), D(2026, 10, 31))
        build.build_rollups(D(2026, 10, 4))
        self.assertEqual(PicRollup.objects.get(pic='P1').last_purchase, D(2026, 8, 10))
        self.assertEqual(PicRollup.objects.get(pic='P2').last_purchase, D(2026, 10, 3))

    def test_channel_bucket_map(self):
        m = build.channel_bucket_map()
        self.assertEqual((m['91'], m['90']), ('cash', 'delivery'))
