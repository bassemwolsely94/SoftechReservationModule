"""
Supplier price comparison (owner batch 2026-10-07, apps/supply/comparison.py):
offer cost at today's public price (price / discount / last real purchase / typical, then the
bonus), head-to-head ranking (>1 % cheaper or a bonus within 1 %), warehouses as their own
tier, virtual / contract suppliers never a price to beat, quota-aware split of the need,
old-public-price purchases marked, and the API + Excel export.
"""
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from apps.supply import comparison as cmp


def _offer(**kw):
    base = dict(price=None, discount_pct=None, bonus_buy=None, foc_qty=None, match_reason={})
    base.update(kw)
    return SimpleNamespace(**base)


class EstimateTests(SimpleTestCase):
    """Costs come from OUR purchase history only; the list contributes its bonus (owner 2026-10-08)."""
    P = 100.0

    def test_history_discount_at_todays_public_price(self):
        e = cmp.estimate_offer(_offer(), self.P, history=(15, 'history'))
        self.assertEqual((e['basis'], e['effective_cost'], e['discount_pct']), ('history', 85.0, 15.0))

    def test_written_price_and_discount_are_ignored(self):
        e = cmp.estimate_offer(_offer(price=Decimal('60'), discount_pct=Decimal('30')), self.P, history=(10, 'history'))
        self.assertEqual(e['effective_cost'], 90.0)
        self.assertIsNone(cmp.estimate_offer(_offer(price=Decimal('60')), self.P)['effective_cost'])

    def test_bonus_from_the_list_applies(self):
        e = cmp.estimate_offer(_offer(bonus_buy=Decimal('10'), foc_qty=Decimal('1')), self.P, history=(25, 'history'))
        self.assertAlmostEqual(e['effective_cost'], round(75 * 10 / 11, 2))


class BoardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from apps.catalog.models import Item, ItemSupplierLink
        from apps.invoices.models import VendorProfile
        from apps.procurement.models import PurchaseLine, SupplierProfile
        from apps.supply.models import AvailabilityBatch, AvailabilityLine
        cls.item = Item.objects.create(softech_id='880001', name='TRESIBA 100IU FLEXTOUCH', is_active=True,
                                       pack_price=Decimal('500'), supplier_code='276')
        cls.item2 = Item.objects.create(softech_id='880002', name='BRUFEN 400MG 30TAB', is_active=True,
                                        pack_price=Decimal('100'))
        for code, name, cl in [('786', 'EGY DRUG -SHERIF', '60'), ('565', 'PHARMA OVER SEAS', '60'),
                               ('777', 'مخازن الوطنية', '50'), ('4470', 'تعاقد افتراضي', '80'),
                               ('276', 'NOVO NORDISK', '70')]:
            SupplierProfile.objects.create(supplier_code=code, supplier_name=name, classif_code=cl)
        cls.v = {c: VendorProfile.objects.create(name=n, softech_personcode=c)
                 for c, n in [('786', 'المصرية شريف'), ('565', 'فارما اوفرسيز'), ('777', 'الوطنية')]}
        ItemSupplierLink.objects.create(item_code='880001', item=cls.item, supp_code='276', is_main=True)
        today = date.today()

        def buy(supp, days_ago, value, qty, public, bonus=0, item='880001'):
            PurchaseLine.objects.create(branch_code='100', supplier_code=supp, doc_number=f'{supp}{days_ago}',
                                        doc_date=today - timedelta(days=days_ago), item_code=item, doccode='10',
                                        net_qty=Decimal(qty), net_value=Decimal(value), bonus_qty=Decimal(bonus),
                                        public_price=Decimal(public), unit_price=Decimal(value) / Decimal(qty))
        buy('786', 40, '850', '2', '500')            # 15 % off
        buy('565', 20, '880', '2', '500')            # 12 % off
        buy('4470', 10, '500', '2', '500')           # 50 % — contract buy-back, never a price to beat
        buy('565', 200, '700', '2', '400')           # older, at the OLD public price
        buy('777', 15, '800', '2', '500')            # warehouse: 20 % off
        buy('786', 30, '75', '1', '100', item='880002')
        buy('565', 30, '75', '1', '100', item='880002')

        def lst(code, *lines):
            b = AvailabilityBatch.objects.create(supplier=cls.v[code], supplier_name=cls.v[code].name)
            for item, kw in lines:
                AvailabilityLine.objects.create(batch=b, raw_text='x', item=item, **kw)
            return b
        lst('786', (cls.item, {'quota': Decimal('2')}), (cls.item2, {}))
        lst('565', (cls.item, {}), (cls.item2, {'bonus_buy': Decimal('25'), 'foc_qty': Decimal('1'),
                                               'bonus_tiers': [[25, 1]]}))
        lst('777', (cls.item, {'discount_pct': Decimal('35')}))   # written discount: ignored

    def _board(self, need=None):
        from unittest import mock
        dem = {self.item.id: {'residual': 5, 'required': 5, 'stock': 1, 'in_transit': 2, 'monthly_rate': 6},
               self.item2.id: {'residual': 0, 'required': 0}}
        with mock.patch.object(cmp, '_demand', lambda ids: {i: dem.get(i, {}) for i in ids}):
            return cmp.build_board()

    def test_ranking_tiers_and_exclusions(self):
        b = self._board()
        row = next(r for r in b['rows'] if r['item_id'] == self.item.id)
        cells = {c['supplier']: c for c in row['cells']}
        self.assertEqual(row['best']['supplier'], '786')                 # 15 % beats 12 %
        self.assertEqual(cells['786']['basis'], 'history')
        self.assertEqual(cells['565']['verdict'], 'pricier')
        self.assertEqual(cells['777']['tier'], 'warehouse')
        self.assertEqual(cells['777']['verdict'], 'cheaper')            # 20 % (history, not the 35 % text)
        self.assertEqual(cells['777']['discount_pct'], 20.0)
        self.assertIn('warehouse_cheaper', row['flags'])
        self.assertEqual([s['key'] for s in b['warehouses']], ['777'])
        # quota 2 at the winner → the rest from the next cheapest distributor
        self.assertEqual([(a['supplier'], a['qty']) for a in row['allocation']], [('786', 2), ('565', 3)])
        # the contract buy-back supplier is nowhere
        self.assertNotIn('4470', [x['code'] for x in row['network']['bought']])
        self.assertIsNone(row['bought_elsewhere'])
        self.assertEqual(row['main_supplier']['code'], '276')

    def test_bonus_wins_within_one_percent_and_not_needed(self):
        row = next(r for r in self._board()['rows'] if r['item_id'] == self.item2.id)
        self.assertEqual(row['state'], 'not_needed')
        self.assertEqual(row['best']['supplier'], '565')                 # 25+1 bonus → cheaper anyway
        cells = {c['supplier']: c for c in row['cells']}
        self.assertEqual(cells['565']['bonus'], '25+1')

    def test_old_public_price_marked(self):
        net = cmp.supplier_network([self.item.id])[self.item.id]
        old = [b for b in net['bought'] if b['code'] == '565'][0]
        self.assertFalse(old['old_price'])                              # its LAST buy was at today's price
        hist = cmp.purchase_history(['880001'])
        self.assertEqual(hist[('880001', '565')]['best']['discount_pct'], 12.5)   # 700/2 off 400

    def test_api_and_excel(self):
        from .factories import make_user
        user, _, _ = make_user('op_compare', role='purchasing')
        c = APIClient()
        c.force_authenticate(user)
        r = c.get('/api/supply/comparison/?days=14')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['summary']['items'], 2)
        x = c.get('/api/supply/comparison/?format=xlsx')
        self.assertEqual(x.status_code, 200)
        self.assertTrue(x.content[:2] == b'PK')
        n = c.get(f'/api/supply/comparison/network/{self.item.id}/')
        self.assertEqual(n.status_code, 200)
        nobody, _, _ = make_user('cashier_compare', role='cashier')
        c.force_authenticate(nobody)
        self.assertEqual(c.get('/api/supply/comparison/').status_code, 403)


class FallbackTests(TestCase):
    """A supplier that never sold us the item: its sister branch's price, else its usual
    discount on the same manufacturer — and a firmer figure wins inside the 1 % band."""

    @classmethod
    def setUpTestData(cls):
        from apps.catalog.models import Item
        from apps.invoices.models import VendorProfile
        from apps.procurement.models import PurchaseLine, SupplierProfile
        from apps.supply.models import AvailabilityBatch, AvailabilityLine
        mk = lambda sid, name: Item.objects.create(softech_id=sid, name=name, is_active=True,
                                                   pack_price=Decimal('100'), producer_name='EVA PHARMA')
        cls.a, cls.b, cls.c = mk('881001', 'ITEM A'), mk('881002', 'ITEM B'), mk('881003', 'ITEM C')
        for code in ('786', '4327', '565'):
            SupplierProfile.objects.create(supplier_code=code, supplier_name=f'S{code}', classif_code='60')
        vp = {c: VendorProfile.objects.create(name=f'V{c}', softech_personcode=c) for c in ('4327', '565')}
        today = date.today()
        n = 0

        def buy(supp, item, value):
            nonlocal n
            n += 1
            PurchaseLine.objects.create(branch_code='100', supplier_code=supp, doc_number=str(n), doc_date=today - timedelta(days=5),
                                        item_code=item, doccode='10', net_qty=Decimal('1'), net_value=Decimal(value),
                                        public_price=Decimal('100'), unit_price=Decimal(value),
                                        item=Item.objects.get(softech_id=item))
        buy('786', '881001', '80')                         # Sherif sold A at 20 % → Zaytoun inherits it
        for _ in range(3):
            buy('565', '881003', '75')                     # PO: 25 % on EVA PHARMA → its median for B
        buy('565', '881002', '75.5')                       # …but PO also really sold B at 24.5 %
        for item in (cls.a, cls.b):
            for code in ('4327', '565'):
                b = AvailabilityBatch.objects.create(supplier=vp[code], supplier_name=vp[code].name)
                AvailabilityLine.objects.create(batch=b, raw_text='x', item=item)

    def test_sister_branch_and_manufacturer_fallbacks(self):
        from unittest import mock
        with mock.patch.object(cmp, '_demand', lambda ids: {i: {'residual': 1} for i in ids}):
            board = cmp.build_board()
        row = {r['item_id']: r for r in board['rows']}
        za = {c['supplier']: c for c in row[self.a.id]['cells']}['4327']
        self.assertEqual((za['basis'], za['discount_pct']), ('group_history', 20.0))
        self.assertEqual(row[self.a.id]['best']['supplier'], '565')    # PO's EVA median 25 % beats 20 %
        # B: PO's real 24.5 % beats nothing cheaper by >1 % — and the firm figure is chosen
        self.assertEqual(row[self.b.id]['best']['supplier'], '565')
        self.assertEqual(row[self.b.id]['best']['basis'], 'history')


class AkhnatonAndOfferMemoryTests(TestCase):
    """أخناتون sends lists as 124 but we buy under 3031 — one company; and every list is
    remembered as "this supplier sells this item"."""

    @classmethod
    def setUpTestData(cls):
        from apps.catalog.models import Item
        from apps.invoices.models import VendorProfile
        from apps.procurement.models import PurchaseLine, SupplierProfile
        from apps.supply.models import AvailabilityBatch, AvailabilityLine
        cls.item = Item.objects.create(softech_id='882001', name='ANTOPRAL 40MG 7TAB', is_active=True, pack_price=Decimal('100'))
        SupplierProfile.objects.create(supplier_code='124', supplier_name='اخناتون  ايفا', classif_code='10')
        SupplierProfile.objects.create(supplier_code='3031', supplier_name='اخناتون ادوية', classif_code='10')
        PurchaseLine.objects.create(branch_code='100', supplier_code='3031', doc_number='1', doc_date=date.today() - timedelta(days=9),
                                    item_code='882001', doccode='10', net_qty=Decimal('2'), net_value=Decimal('160'),
                                    public_price=Decimal('100'), unit_price=Decimal('80'), item=cls.item)
        cls.vp = VendorProfile.objects.create(name='AKHNATON EVA', softech_personcode='124')
        old = AvailabilityBatch.objects.create(supplier=cls.vp, supplier_name='AKHNATON EVA')
        AvailabilityBatch.objects.filter(pk=old.pk).update(created_at=old.created_at - timedelta(days=60))
        AvailabilityLine.objects.create(batch=old, raw_text='انتوبرال 40', item=cls.item, is_confirmed=True)
        b = AvailabilityBatch.objects.create(supplier=cls.vp, supplier_name='AKHNATON EVA')
        cls.line = AvailabilityLine.objects.create(batch=b, raw_text='انتوبرال ٤٠ بونص 10+1', item=cls.item,
                                                   bonus_buy=Decimal('10'), foc_qty=Decimal('1'))

    def test_history_under_3031_prices_the_124_list(self):
        from unittest import mock
        with mock.patch.object(cmp, '_demand', lambda ids: {i: {'residual': 3} for i in ids}):
            row = cmp.build_board()['rows'][0]
        c = row['cells'][0]
        self.assertEqual((c['supplier'], c['basis']), ('124', 'group_history'))
        self.assertEqual(c['last_buy']['supplier_code'], '3031')
        self.assertAlmostEqual(c['effective_cost'], round(80 * 10 / 11, 2))      # 20 % + bonus 10+1
        self.assertEqual(row['state'], 'buy')
        offered = row['network']['offered_by']
        self.assertEqual((offered[0]['code'], offered[0]['times'], offered[0]['confirmed']), ('124', 2, True))

    def test_confirmed_earlier_list_counts_as_carried(self):
        from apps.supply import availability as av
        self.assertEqual(av.carried_or_offered('124', [self.item.id]), {self.item.id})
        self.assertEqual(av.carried_or_offered('565', [self.item.id]), set())
