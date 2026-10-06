"""
Migration 0016 — Rename is_premium → item_level and change to PositiveSmallIntegerField.

Reason: Initial mapping of items.itemslevel as 'Premium' was incorrect.
Sample items with itemslevel=1 include CENTRUM, ADVIL, ROGAINE, ASHWAGANDHA — imported brand
items, not a premium-only tier. Exact meaning needs business confirmation.
Renamed to neutral 'item_level' to store the raw value (0 or 1) without assumptions.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0015_item_channel_fields'),
    ]

    operations = [
        migrations.RenameField(
            model_name='item',
            old_name='is_premium',
            new_name='item_level',
        ),
        # PostgreSQL cannot cast boolean → smallint implicitly; use explicit USING clause
        migrations.RunSQL(
            sql='ALTER TABLE catalog_item ALTER COLUMN item_level TYPE smallint USING item_level::integer',
            reverse_sql='ALTER TABLE catalog_item ALTER COLUMN item_level TYPE boolean USING item_level::boolean',
        ),
        migrations.AlterField(
            model_name='item',
            name='item_level',
            field=models.PositiveSmallIntegerField(
                default=0,
                verbose_name='مستوى الصنف',
                help_text=(
                    'SOFTECH items.itemslevel. '
                    'Distribution: 0=standard (50,338 items), 1=special (1,014 items). '
                    'Exact business meaning needs confirmation — sample level=1 items include '
                    'CENTRUM SILVER, ADVIL, ROGAINE (imported brand-name items). '
                    'NOT narcotics. تصنيف جدول مخدرات maps to a different column. '
                    'TODO: confirm with business team.'
                ),
            ),
        ),
    ]
