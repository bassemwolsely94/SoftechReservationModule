"""
«صندوق الإتاحة» — one supplier line → several catalog items ("بيبيلاك 1....2....3").
Matching several SPLITS the line into siblings (apps/supply/availability.set_line_items) so
cases / sourcing / order lists / KPIs keep seeing one item per line.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.supply import availability as av

User = get_user_model()


def _items(*names):
    from apps.catalog.models import Item
    return [Item.objects.create(softech_id=str(910000 + i), name=n, pack_price=100, cost_price=80)
            for i, n in enumerate(names)]


class SplitLineTests(TestCase):
    def setUp(self):
        from apps.supply.models import AvailabilityBatch, AvailabilityLine
        self.b1, self.b2, self.b3 = _items('BEBELAC 1 400GM', 'BEBELAC 2 400GM', 'BEBELAC 3 400GM')
        self.batch = AvailabilityBatch.objects.create(supplier_name='Supplier 565', raw_content='بيبيلاك 1....2....3')
        self.line = AvailabilityLine.objects.create(
            batch=self.batch, raw_text='🏷️بيبيلاك 1....2....3', supplier_qty=Decimal('20'), price=Decimal('210'),
            foc_qty=Decimal('2'), discount_pct=Decimal('5'), expiry='2027-06', is_unmatched=True)

    def group(self):
        from apps.supply.models import AvailabilityLine
        return list(AvailabilityLine.objects.filter(batch=self.batch).order_by('id'))

    def test_several_items_split_with_same_economics_and_no_alias(self):
        from apps.catalog.models import ItemAlias
        out = av.set_line_items(self.line, [self.b1.id, self.b2.id, self.b3.id])
        self.assertEqual([l.item_id for l in out], [self.b1.id, self.b2.id, self.b3.id])
        g = self.group()
        self.assertEqual(len(g), 3)
        for l in g:
            self.assertEqual((l.raw_text, l.supplier_qty, l.price, l.foc_qty, l.discount_pct, l.expiry),
                             (self.line.raw_text, Decimal('20'), Decimal('210'), Decimal('2'), Decimal('5'), '2027-06'))
            self.assertTrue(l.is_confirmed)
            self.assertFalse(l.is_unmatched)
        self.assertEqual([l.split_from_id for l in g], [None, self.line.id, self.line.id])
        self.assertFalse(ItemAlias.objects.exists())                  # one-to-many never taught

    def test_update_from_any_row_remove_and_unmatch(self):
        from apps.catalog.models import ItemAlias
        av.set_line_items(self.line, [self.b1.id, self.b2.id, self.b3.id])
        sibling = self.group()[2]
        av.set_line_items(sibling, [self.b1.id, self.b3.id])           # edit via a sibling row
        self.assertEqual([l.item_id for l in self.group()], [self.b1.id, self.b3.id])
        av.set_line_items(self.line, [self.b2.id])                      # back to one → taught
        self.assertEqual([l.item_id for l in self.group()], [self.b2.id])
        self.assertTrue(ItemAlias.objects.filter(item=self.b2).exists())
        av.set_line_items(self.line, [])
        g = self.group()
        self.assertEqual((len(g), g[0].item_id, g[0].is_unmatched, g[0].is_confirmed), (1, None, True, False))

    def test_deleting_the_original_removes_its_siblings(self):
        av.set_line_items(self.line, [self.b1.id, self.b2.id])
        self.line.delete()
        self.assertEqual(self.group(), [])

    def test_api(self):
        u = User.objects.create_superuser('sup', password='x')
        c = APIClient()
        c.force_authenticate(u)
        url = f'/api/supply/availability/{self.batch.pk}/lines/{self.line.pk}/items/'
        r = c.post(url, {'item_ids': [self.b1.id, self.b2.id]}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual([l['item'] for l in r.data['lines']], [self.b1.id, self.b2.id])
        self.assertEqual(r.data['lines'][1]['split_from'], self.line.pk)
        # only this group's review rows come back (the screen swaps them — no full re-analysis)
        self.assertEqual([x['line_id'] for x in r.data['rows']], [l['id'] for l in r.data['lines']])
        self.assertEqual({x['group_id'] for x in r.data['rows']}, {self.line.pk})
        self.assertEqual(c.post(url, {'item_ids': 'x'}, format='json').status_code, 400)
        self.assertEqual(c.post(url, {'item_ids': [999999]}, format='json').status_code, 400)
        rows = av.analyze_batch(self.batch)['lines']
        self.assertEqual({r['group_id'] for r in rows}, {self.line.pk})
        self.assertEqual([r['split'] for r in rows], [False, True])
