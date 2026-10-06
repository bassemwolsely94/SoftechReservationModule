"""
Mirror SOFTECH itemssuppliers into catalog.ItemSupplierLink (nightly, 04:30 — and on demand):

    python manage.py sync_item_suppliers

Read-only on SOFTECH. A failed read leaves the existing mirror untouched.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Mirror SOFTECH itemssuppliers (supplier ↔ item links + supplier item codes).'

    def handle(self, *args, **opts):
        from apps.catalog.supplier_links import sync_item_suppliers
        out = sync_item_suppliers()
        self.stdout.write(self.style.SUCCESS(
            f"itemssuppliers: {out['rows']} links ({out['with_code']} with a supplier code) — "
            f"+{out['created']} ~{out['updated']} -{out['deleted']}"))
