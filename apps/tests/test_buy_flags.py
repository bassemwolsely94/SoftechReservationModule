"""
Purchase-side advisory flags on شيت النواقص (apps/purchasing/buy_flags.py, doc 22 §10).

💲 يوجد أرخص = the «مقارنة أسعار الشراء» verdict, nothing recomputed.
🎁 بونص زائد = a bonus deal (free ≥ 5 % of paid) on an ESTABLISHED item that bought more than
6 months of network sales; virtual / contract accounts are never judged. Read-only: no
quantity changes, no SOFTECH.
"""
import datetime
from decimal import Decimal

from django.test import SimpleTestCase, TestCase

from apps.purchasing import buy_flags as F

TODAY = datetime.date(2026, 10, 26)


def _buy(item, supplier, days_ago, *, qty, bonus, value=None, n=[0]):
    from apps.procurement.models import PurchaseLine
    n[0] += 1
    value = value if value is not None else qty * 80
    return PurchaseLine.objects.create(
        branch_code='100', supplier_code=supplier, doc_number=f'F{n[0]}', doccode='10',
        doc_date=TODAY - datetime.timedelta(days=days_ago), item_code=item.softech_id, item=item,
        net_qty=Decimal(str(qty)), raw_qty=Decimal(str(qty)), net_value=Decimal(str(value)),
        raw_value=Decimal(str(value)), bonus_qty=Decimal(str(bonus)), vat_value=Decimal('0'),
        public_price=Decimal('100'))


class FocOverbuyTests(TestCase):
    def setUp(self):
        from apps.catalog.models import Item
        from apps.procurement.models import SupplierProfile
        from apps.purchasing.models import SalesTransactionLine
        SupplierProfile.objects.create(supplier_code='D1', supplier_name='RAMCO', classif_code='60')
        SupplierProfile.objects.create(supplier_code='V1', supplier_name='virtual', classif_code='80')
        self.old = Item.objects.create(softech_id='OLD1', name='OLD', pack_price=100)
        self.new = Item.objects.create(softech_id='NEW1', name='NEW', pack_price=100)
        for code, item, day in (('OLD1', self.old, datetime.date(2025, 11, 1)),     # sold for a year
                                ('NEW1', self.new, datetime.date(2026, 9, 1))):     # a launch
            SalesTransactionLine.objects.create(softech_branchcode='130', softech_itemcode=code, doccode='115',
                                                docnumber=f'S-{code}', doc_date=day, item=item, transqty=5,
                                                net_qty=5)
        self.rates = {self.old.id: 10.0, self.new.id: 10.0}

    def flags(self):
        return F.foc_overbuy_flags(today=TODAY, rates=self.rates)

    def test_overbuy_on_established_item(self):
        _buy(self.old, 'D1', 30, qty=100, bonus=20, value=8000)      # 120 units = 12 months
        d = self.flags()[self.old.id]
        self.assertEqual((d['qty'], d['bonus_qty'], d['cover_months']), (100.0, 20.0, 12.0))
        self.assertEqual(d['supplier'], 'RAMCO')
        # 60 units beyond 6 months × (8000 / 120) per unit
        self.assertAlmostEqual(d['excess_value'], 4000.0, places=2)
        self.assertIn('بونص زائد: 100+20 من RAMCO', F.foc_label(d))

    def test_within_cover_small_bonus_launch_and_virtual_are_not_flagged(self):
        _buy(self.old, 'D1', 30, qty=50, bonus=5)                     # 5.5 months — fine
        _buy(self.old, 'D1', 20, qty=100, bonus=2)                    # bonus 2 % — not a deal
        _buy(self.new, 'D1', 10, qty=100, bonus=20)                   # launch: sold for 1 month only
        _buy(self.old, 'V1', 15, qty=200, bonus=40)                   # virtual account — never judged
        self.assertEqual(self.flags(), {})

    def test_same_day_lines_form_one_deal_and_no_sales_means_open_cover(self):
        self.rates[self.old.id] = 0.0
        _buy(self.old, 'D1', 40, qty=10, bonus=1)
        d = self.flags()[self.old.id]
        self.assertIsNone(d['cover_months'])
        self.assertIn('بدون مبيعات حالياً', F.foc_label(d))

    def test_outside_window_is_ignored(self):
        _buy(self.old, 'D1', F.WINDOW_DAYS + 5, qty=100, bonus=20)
        self.assertEqual(self.flags(), {})


class CheaperFlagTests(SimpleTestCase):
    def test_only_cheaper_rows_and_label(self):
        board = {'items': [
            {'item_id': 1, 'state': 'cheaper', 'paid_pct': 21.5, 'last': {'discount_pct': 21.2},
             'best': {'name': 'Akhnaton', 'discount_pct': 25.1}, 'saving_month': 2112.8},
            {'item_id': 2, 'state': 'best'},
            {'item_id': 3, 'state': 'single'},
        ]}
        flags = F.cheaper_supplier_flags(board=board)
        self.assertEqual(list(flags), [1])
        self.assertEqual(F.cheaper_label(flags[1]),
                         'يوجد أرخص: Akhnaton 25.1% بدل 21.5% — توفير 2,113 ج.م/شهر')
