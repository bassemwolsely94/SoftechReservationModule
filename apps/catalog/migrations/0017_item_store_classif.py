"""
Migration 0017 — Add store_classif + store_classif_name to catalog.Item.

Maps to SOFTECH:
  items.itemstoreclassif  → custdiscpclassif.custdiscpcode (FK)
  custdiscpclassif.custdiscpdescr resolves to store_classif_name.

This field is "تصنيف خصم التعاقدات" (Contract Discount Classification) in
the SOFTECH UI. It groups items into discount tiers for contract pricing.

Reference table (custdiscpclassif) has 37 codes. Most common in active items:
  '10' = Med: Local              (10,776 items)
  '9'  = (no reference match — legacy orphaned value, 2,144 items)
  NULL = not classified          (22,669 items)
  '25' = Med:Local 25% Shortage  (408 items)
  '15' = Med: Imported 18%       (328 items)

Full reference: docs/softech_items_reference.md
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0016_rename_is_premium_to_item_level'),
    ]

    operations = [
        migrations.AddField(
            model_name='item',
            name='store_classif',
            field=models.CharField(
                max_length=5, blank=True, db_index=True,
                verbose_name='تصنيف خصم التعاقدات',
                help_text=(
                    'SOFTECH items.itemstoreclassif → custdiscpclassif.custdiscpcode. '
                    'Contract discount classification tier. Common values: '
                    '10=Med Local, 11=Med Local Under License 20%, 12=Med Local 25%, '
                    '13=Med Imported/Egydrug 12%, 14=Med Imported/Agent 15%, '
                    '15=Med Imported 18%, 25=Med Local 25% Shortage, 84=SERVICES, '
                    '87=Children Supplies, 88=Baby Formula, 89=Baby Care, 90=Imported Devices.'
                ),
            ),
        ),
        migrations.AddField(
            model_name='item',
            name='store_classif_name',
            field=models.CharField(
                max_length=60, blank=True,
                verbose_name='اسم تصنيف التعاقدات',
                help_text='Resolved name from custdiscpclassif.custdiscpdescr.',
            ),
        ),
    ]
