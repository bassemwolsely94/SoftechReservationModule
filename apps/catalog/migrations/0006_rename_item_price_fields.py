"""
Migration: catalog 0006

Rename the two price fields on catalog.Item for permanent clarity:

  OLD NAME          NEW NAME      SOFTECH source      Meaning
  ──────────────    ──────────    ─────────────────   ──────────────────────────────────
  unit_price     →  pack_price   itemsaleprice        Full box / pack retail price
  unit_sale_price → unit_price   unitsaleprice        Price per individual unit / strip

The rename order matters:
  1. unit_price → pack_price          (frees the column name "unit_price")
  2. unit_sale_price → unit_price     (occupies the now-free name)
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0005_alter_item_phcode'),
    ]

    operations = [
        # Step 1: rename the full-pack field first so "unit_price" is free
        migrations.RenameField(
            model_name='item',
            old_name='unit_price',
            new_name='pack_price',
        ),
        # Step 2: promote the per-unit field into the vacated name
        migrations.RenameField(
            model_name='item',
            old_name='unit_sale_price',
            new_name='unit_price',
        ),
    ]
