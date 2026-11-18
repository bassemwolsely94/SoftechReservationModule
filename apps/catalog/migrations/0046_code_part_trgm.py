# The item search `code_part` tier (apps/catalog/wildcard.item_search) asks for digits INSIDE a
# code: softech_id / barcode / ItemBarcode.barcode `__contains`, which Django renders as
# "col"::text LIKE '%3690%'. No b-tree serves that, so each was a sequential scan (≈25–80 ms on
# the real catalog). Trigram GIN indexes on exactly that `col::text` expression answer it from
# the index (measured 0.1–0.3 ms). Trigrams need 3+ characters: a 2-digit fragment still scans
# (the planner walks the softech_id b-tree and stops at the LIMIT — ≈1 ms, acceptable).
# Catalog only; nothing here touches SOFTECH sync.

from django.db import migrations

SQL = [
    'CREATE INDEX IF NOT EXISTS catalog_item_softech_id_trgm '
    'ON catalog_item USING gin ((softech_id::text) gin_trgm_ops)',
    'CREATE INDEX IF NOT EXISTS catalog_item_barcode_trgm '
    'ON catalog_item USING gin ((barcode::text) gin_trgm_ops)',
    'CREATE INDEX IF NOT EXISTS catalog_itembarcode_barcode_trgm '
    'ON catalog_itembarcode USING gin ((barcode::text) gin_trgm_ops)',
]
REVERSE = [
    'DROP INDEX IF EXISTS catalog_item_softech_id_trgm',
    'DROP INDEX IF EXISTS catalog_item_barcode_trgm',
    'DROP INDEX IF EXISTS catalog_itembarcode_barcode_trgm',
]


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0045_folded_name_prefix'),
    ]

    operations = [
        migrations.RunSQL(SQL, REVERSE),
    ]
