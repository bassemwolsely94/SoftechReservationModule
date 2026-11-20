"""
C11 / P-37 — the identified-sale rate (share of sale invoices on a customer code) on the morning brief
(«أمس») and the /me «📈 مبيعاتي» widget. Both must show the SAME number gamification judges for a fixture
day (apps/gamification/pic.py): a PIC on the header counts, blank = walk-in, shared / house codes
(PicExclusion) never count, returns are not sales, other branches / users never leak in.
"""
import datetime as dt
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from apps.gamification import pic as G
from apps.gamification.engine import day_bounds
from apps.tests.factories import make_branch, make_branch2, make_customer

DAY = dt.date(2026, 11, 2)
N = [0]


def _inv(branch, phcode, *, user='U7', doc='115', day=DAY):
    from apps.customers.models import PurchaseHistory
    N[0] += 1
    return PurchaseHistory.objects.create(
        customer=make_customer(), softech_invoice_id=f'C11-{N[0]}', branch=branch, doc_code=doc,
        softech_phcode=phcode, softech_user=user, total_amount=Decimal('100'),
        invoice_date=timezone.make_aware(dt.datetime.combine(day, dt.time(12, 0))))


class IdentifiedRateTests(TestCase):
    def setUp(self):
        self.b, self.other = make_branch(), make_branch2()
        _inv(self.b, '01HD1')
        _inv(self.b, '01HD2')
        _inv(self.b, 'HOUSE')                       # a shared house code: excluded
        _inv(self.b, '')                            # walk-in
        _inv(self.b, '01HD3', doc='30')             # a return: not a sale
        _inv(self.b, '01HD4', user='U8')            # another salesperson, same branch
        _inv(self.other, '')                        # another branch
        _inv(self.b, '', day=DAY - dt.timedelta(days=1))    # the day before
        p = mock.patch.object(G, '_excluded', return_value=frozenset({'HOUSE'}))
        p.start()
        self.addCleanup(p.stop)

    def test_brief_line_is_the_gamification_number(self):
        from apps.insights import brief
        total, on_pic = G.branch_capture_rate(self.b, DAY, DAY)
        self.assertEqual((total, on_pic), (5, 3))                  # 01HD1, 01HD2, 01HD4 of 5 sales
        line = brief._identified_line(self.b, DAY)
        self.assertIn('60%', line)
        self.assertIn('(3 من 5)', line)
        self.assertIn(f'الهدف {G.capture_pct()}%', line)

    def test_brief_yesterday_section_carries_the_line(self):
        from apps.insights import brief
        lines, _ = brief._yesterday_section(self.b, DAY)
        self.assertTrue(any('فواتير على كود عميل: 60%' in l for l in lines))

    def test_no_sales_shows_a_dash(self):
        from apps.insights import brief
        self.assertEqual(brief._identified_line(self.b, DAY + dt.timedelta(days=3)), '• فواتير على كود عميل: —')

    def test_me_widget_is_the_gamification_number(self):
        from apps.personal import providers
        with mock.patch.object(timezone, 'localdate', return_value=DAY + dt.timedelta(days=1)):
            out = providers._identified('U7', 7)
        start, end = day_bounds(DAY)
        self.assertEqual(G.capture_by_user(start, end, ['U7'])['U7'], (4, 2))
        self.assertEqual(out['yesterday'], {'invoices': 4, 'on_pic': 2, 'pct': 50.0})
        self.assertEqual(out['period'], {'invoices': 5, 'on_pic': 2, 'pct': 40.0})   # + the walk-in the day before
        self.assertEqual(out['target_pct'], G.capture_pct())

    def test_me_widget_payload_includes_it_for_the_callers_usercode_only(self):
        from apps.personal import providers
        with mock.patch.object(timezone, 'localdate', return_value=DAY + dt.timedelta(days=1)):
            out = providers._my_sales('U8', {'period_days': 7})
        self.assertEqual(out['identified']['yesterday'], {'invoices': 1, 'on_pic': 1, 'pct': 100.0})
