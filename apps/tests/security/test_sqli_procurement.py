"""
SQL injection — procurement supplier-category backfill (apps/procurement/engine.py).
SupplierCategory.code is free text staff type; it must never be pasted into SQL.
"""
from datetime import date

from django.test import TestCase

from apps.procurement import engine
from apps.procurement.models import PurchaseLine

PAYLOAD = "x' END; DROP TABLE p;--"   # fits supplier_category (25)


def _line(supplier, n):
    return PurchaseLine.objects.create(branch_code='100', supplier_code=supplier, doc_number=str(n),
                                       doc_date=date(2026, 10, 1), item_code='IT001', doccode='10')


class SupplierCategoryBackfillTests(TestCase):

    def test_category_text_lands_verbatim(self):
        a, b, c = _line('1268', 1), _line("12'68", 2), _line('9999', 3)
        engine._backfill_purchase_line_categories({'1268': PAYLOAD, "12'68": 'main', '': 'x'})
        a.refresh_from_db(); b.refresh_from_db(); c.refresh_from_db()
        self.assertEqual(a.supplier_category, PAYLOAD)
        self.assertEqual(b.supplier_category, 'main')
        self.assertEqual(c.supplier_category, '')          # not in the map → cleared, as before
        self.assertEqual(PurchaseLine.objects.count(), 3)

    def test_empty_map_changes_nothing(self):
        a = _line('1268', 1)
        PurchaseLine.objects.filter(pk=a.pk).update(supplier_category='keep')
        engine._backfill_purchase_line_categories({})
        a.refresh_from_db()
        self.assertEqual(a.supplier_category, 'keep')
