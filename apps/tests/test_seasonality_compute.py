"""
«↺ إعادة حساب الموسمية» posts to /api/forecasting/seasonality/compute/ with no item:
it recomputes every item (ForecastService.compute_all_seasonality) instead of failing
with "item_id مطلوب". With item_id it still computes that one item.
"""
import datetime
from decimal import Decimal

from django.test import TestCase

from apps.forecasting.models import SeasonalityIndex

from .factories import make_branch, make_user

URL = '/api/forecasting/seasonality/compute/'


class SeasonalityComputeTests(TestCase):
    def setUp(self):
        from apps.catalog.models import Item
        from apps.purchasing.models import SalesTransactionLine
        branch = make_branch()
        _, _, self.analyst = make_user('sz_sup', role='supervisor', branch=branch)
        _, _, self.seller = make_user('sz_sales', role='salesperson', branch=branch)
        self.item = Item.objects.create(softech_id='SZ1', name='SEASONAL', pack_price=100)
        self.sparse = Item.objects.create(softech_id='SZ2', name='SPARSE', pack_price=100)
        today = datetime.date.today()
        for i in range(10):                                  # sales in 10 distinct recent months
            d = (today.replace(day=1) - datetime.timedelta(days=30 * i + 5))
            qty = Decimal('30') if d.month in (12, 1) else Decimal('10')
            SalesTransactionLine.objects.create(
                softech_branchcode='130', softech_itemcode='SZ1', doccode='115', docnumber=f'S{i}',
                doc_date=d, item=self.item, transqty=qty, net_qty=qty)
        SalesTransactionLine.objects.create(                 # one month only → stays unseasonal
            softech_branchcode='130', softech_itemcode='SZ2', doccode='115', docnumber='T1',
            doc_date=today - datetime.timedelta(days=20), item=self.sparse, transqty=5, net_qty=5)

    def test_button_recomputes_every_item(self):
        r = self.analyst.post(URL, {}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['items'], 1)
        self.assertEqual(r.json()['rows'], 12)
        self.assertEqual(SeasonalityIndex.objects.filter(item=self.item).count(), 12)
        self.assertFalse(SeasonalityIndex.objects.filter(item=self.sparse).exists())
        # running it again replaces the rows, it does not add to them
        self.assertEqual(self.analyst.post(URL, {}, format='json').status_code, 200)
        self.assertEqual(SeasonalityIndex.objects.filter(item=self.item).count(), 12)

    def test_single_item_still_works_and_rules_hold(self):
        r = self.analyst.post(URL, {'item_id': self.item.id}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(len(r.json()['months']), 12)
        self.assertEqual(self.seller.post(URL, {}, format='json').status_code, 403)
        self.assertEqual(self.analyst.post(URL, {'years': 'x'}, format='json').status_code, 400)
        self.assertEqual(self.analyst.post(URL, {'years': 9}, format='json').status_code, 400)
